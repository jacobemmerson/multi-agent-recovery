"""The orchestrator. The only module with side effects.

Runs one task (or an N-task memory session), wraps every agent call and tool action,
records provenance and events, applies faults and the recovery policy, and writes
runs/<run_id>/. fork_twin starts a counterfactual run from a pre-injection snapshot.
"""

import json
import subprocess
import time
import zlib
from collections.abc import Callable
from datetime import datetime, timezone
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from typing import Literal

from agentdojo.functions_runtime import TaskEnvironment

from mar.agents import Executor, Planner, Researcher, ToolResult, Verifier, load_prompt, prompt_hashes, tool_loop
from mar.artifacts import Artifact, Finding, PlanStep, ProvenanceGraph, ToolAction
from mar.config import ExperimentConfig, TaskSet, load_experiment, load_task_set
from mar.env import TOOL_ACTION_CLASSES, ActionClass, Env
from mar.faults import FaultTemplate, Oracle, inject, load_templates, position_for, templates_hash
from mar.llm import LLMClient, LLMResponse
from mar.metrics import taint_for_run
from mar.recovery import POLICIES, NoRecovery, RecoveryPolicy


@dataclass
class RunRecord:
    run_id: str
    directory: Path
    manifest: dict[str, Any]
    graph: ProvenanceGraph = field(default_factory=ProvenanceGraph)
    events: list[dict[str, Any]] = field(default_factory=list)
    result: dict[str, Any] | None = None

    @classmethod
    def start(cls, runs_dir: Path, manifest: dict[str, Any]) -> "RunRecord":
        directory = runs_dir / manifest["run_id"]
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "manifest.json").write_text(json.dumps(manifest, indent=2, default=str))
        return cls(manifest["run_id"], directory, manifest)

    def add_artifact(self, artifact: Artifact) -> None:
        self.graph.add(artifact)
        self.emit("artifact", id=artifact.id, artifact_kind=artifact.kind, producer=artifact.producer, cites=artifact.cites)

    def add_tool_action(self, action: ToolAction) -> None:
        self.graph.tool_actions[action.id] = action
        self.emit("tool_action", **action.model_dump(exclude={"result"}))

    def emit(self, kind: str, **payload: Any) -> None:
        event = {"seq": len(self.events), "kind": kind, **payload}
        self.events.append(event)
        with (self.directory / "events.jsonl").open("a") as handle:
            handle.write(json.dumps(event) + "\n")

    def finish(self, result: dict[str, Any]) -> None:
        self.result = result
        (self.directory / "manifest.json").write_text(json.dumps(self.manifest, indent=2, default=str))
        (self.directory / "provenance.json").write_text(self.graph.model_dump_json(indent=2))
        artifacts_dir = self.directory / "artifacts"
        artifacts_dir.mkdir(exist_ok=True)
        for artifact in self.graph.artifacts.values():
            (artifacts_dir / f"{artifact.id}.json").write_text(artifact.model_dump_json(indent=2))
        (self.directory / "result.json").write_text(json.dumps(result, indent=2, default=str))


def load_run(directory: Path) -> RunRecord:
    manifest = json.loads((directory / "manifest.json").read_text())
    record = RunRecord(manifest["run_id"], directory, manifest)
    events_path = directory / "events.jsonl"
    if events_path.exists():
        record.events = [json.loads(line) for line in events_path.read_text().splitlines() if line]
    provenance_path = directory / "provenance.json"
    if provenance_path.exists():
        record.graph = ProvenanceGraph.model_validate_json(provenance_path.read_text())
    result_path = directory / "result.json"
    if result_path.exists():
        record.result = json.loads(result_path.read_text())
    return record


def git_sha() -> str:
    try:
        return subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True).stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return "unknown"


def build_manifest(
    config: ExperimentConfig,
    *,
    run_id: str,
    suite: str,
    task_id: str,
    condition: str,
    fault_id: str | None,
    repeat: int,
    seed: int,
    parent_run_id: str | None = None,
    branch_point: str | None = None,
) -> dict[str, Any]:
    return {
        "run_id": run_id,
        "experiment": config.name,
        "suite": suite,
        "task_id": task_id,
        "condition": condition,
        "fault_id": fault_id,
        "repeat": repeat,
        "seed": seed,
        "model": config.model.name,
        "benchmark_version": config.benchmark_version,
        "git_sha": git_sha(),
        "templates_hash": templates_hash(config.fault_templates),
        "prompt_hashes": prompt_hashes(),
        "parent_run_id": parent_run_id,
        "branch_point": branch_point,
        "started_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }


class EnvToolRuntime:
    """ToolRuntime over an Env: executes, tags, and reports every tool action."""

    def __init__(
        self,
        env: Env,
        step_id: str,
        on_action: Callable[[ToolAction], None] | None = None,
        allowed: set[str] | None = None,
    ) -> None:
        self.env = env
        self.step_id = step_id
        self.on_action = on_action
        self.allowed = allowed
        self.count = 0

    def tool_schemas(self) -> list[dict[str, Any]]:
        schemas = self.env.tool_schemas()
        if self.allowed is None:
            return schemas
        return [s for s in schemas if s["function"]["name"] in self.allowed]

    def call(self, name: str, args: dict[str, Any]) -> ToolResult:
        self.count += 1
        if self.allowed is not None and name not in self.allowed:
            return ToolResult("blocked", "tool not available to this agent", f"{self.step_id}:a{self.count}")
        result, error = self.env.call(name, args)
        output = error if error is not None else _stringify(result)
        known = name in TOOL_ACTION_CLASSES
        action = ToolAction(
            id=f"{self.step_id}:a{self.count}",
            step_id=self.step_id,
            tool=name,
            args=args,
            action_class=self.env.action_class(name).value if known else "unknown",
            authorized=known and self.env.is_authorized(name),
            result=output[:2000],
        )
        if self.on_action:
            self.on_action(action)
        return ToolResult("error" if error is not None else "ok", output, action.id)


def _stringify(result: Any) -> str:
    if isinstance(result, str):
        return result
    if hasattr(result, "model_dump"):
        return json.dumps(result.model_dump(), default=str)
    if isinstance(result, list):
        return json.dumps([r.model_dump() if hasattr(r, "model_dump") else r for r in result], default=str)
    return json.dumps(result, default=str)


def day1(task_ids: list[str], suite: str, llm: LLMClient, benchmark_version: str = "v1.2") -> list[dict[str, Any]]:
    """Single-agent clean runs: does the model solve the task at all, and how fast?"""
    rows = []
    for task_id in task_ids:
        env = Env(suite, task_id, benchmark_version)
        runtime = EnvToolRuntime(env, "day1")
        started = time.perf_counter()
        loop = tool_loop(load_prompt("executor"), env.prompt, llm, runtime)
        rows.append(
            {
                "task_id": task_id,
                "utility": env.check_utility(loop.output),
                "llm_calls": loop.llm_calls,
                "tool_calls": runtime.count,
                "seconds": round(time.perf_counter() - started, 1),
                "truncated": loop.truncated,
            }
        )
    return rows


def read_only_tools(env: Env) -> set[str]:
    return {t.name for t in env.tools if TOOL_ACTION_CLASSES.get(t.name) is ActionClass.READ_ONLY}


@dataclass
class Checkpoint:
    """Clean state at a stage boundary; a twin or a stage restart resumes from here."""

    stage: Literal["findings", "plan"]
    artifacts: list[Artifact]
    snapshot: TaskEnvironment
    trace: list = field(default_factory=list)


@dataclass
class PipelineResult:
    output: str
    utility: bool
    llm_calls: int
    plan_retries: int
    checkpoint_before_fault: Checkpoint | None = None
    fault_applied: bool | None = None
    fault_artifact_id: str | None = None
    recovered: bool = False
    recovery_llm_calls: int = 0
    discarded_artifacts: int = 0
    verifier_rejections: int = 0


class _RecordingLLM:
    """Wraps the client so every call becomes an llm_call event. Prompts are untouched."""

    def __init__(self, llm: LLMClient, record: RunRecord) -> None:
        self.llm = llm
        self.record = record
        self.calls = 0

    def complete(self, messages, tools=None, schema=None) -> LLMResponse:
        response = self.llm.complete(messages, tools=tools, schema=schema)
        self.calls += 1
        self.record.emit(
            "llm_call",
            model=response.model,
            system_fingerprint=response.system_fingerprint,
            usage=response.usage,
            n_tool_calls=len(response.tool_calls),
            structured=schema is not None,
        )
        return response


def run_pipeline(
    env: Env,
    llm: LLMClient,
    record: RunRecord,
    task_id: str,
    checkpoint: Checkpoint | None = None,
    fault: tuple[FaultTemplate, int] | None = None,
    policy: RecoveryPolicy | None = None,
    delay: int | Literal["all"] = "all",
) -> PipelineResult:
    """Researcher → planner → one executor per step, with an optional fault at a stage boundary.

    `fault` is (template, position_seed); the position within the stage is derived from the seed.
    When the oracle reveals the fault (after `delay` executor steps, or at the end for "all"), the
    policy's plan is applied: a restart reruns from scratch or from the clean checkpoint.
    """
    policy = policy or NoRecovery()
    recording = _RecordingLLM(llm, record)
    inputs = {"task_id": task_id, "prompt": env.prompt}
    result = PipelineResult(output="", utility=False, llm_calls=0, plan_retries=0)
    verifier = Verifier() if policy.verify_every_artifact else None

    if checkpoint is not None:
        env.restore(checkpoint.snapshot)
        env.trace = list(checkpoint.trace)
        findings = [a for a in checkpoint.artifacts if a.kind == "finding"]
        steps = [a for a in checkpoint.artifacts if a.kind == "plan_step"]
        for artifact in checkpoint.artifacts:
            record.add_artifact(artifact.model_copy(deep=True))
    else:
        findings, steps = [], []

    if checkpoint is None:
        def research() -> list[Any]:
            runtime = EnvToolRuntime(env, f"{task_id}:research", on_action=record.add_tool_action, allowed=read_only_tools(env))
            return Researcher().run(inputs, recording, runtime)

        findings = _verified(research, verifier, inputs, recording, result)
        findings = _maybe_inject(fault, "finding", findings, findings, env, record, task_id, result, stage_name="findings")
        for finding in findings:
            record.add_artifact(finding)

    plan_retries = 0
    if checkpoint is None or checkpoint.stage == "findings":
        steps = _verified(lambda: Planner().run({**inputs, "findings": findings}, recording), verifier, inputs, recording, result)
        plan_retries = steps[0].content["retries"] if steps else 0
        steps = _maybe_inject(fault, "plan_step", steps, findings + steps, env, record, task_id, result, stage_name="plan")
        for step in steps:
            record.add_artifact(step)

    oracle = Oracle(result.fault_artifact_id, 0, delay) if result.fault_applied and result.fault_artifact_id else None

    by_id = {f.id: f for f in findings}
    outputs = []
    revealed: str | None = None
    for n, step in enumerate(steps, 1):
        context = "\n".join(f"- {by_id[c].content.get('text', '')}" for c in step.cites if c in by_id)
        runtime = EnvToolRuntime(env, step.id, on_action=record.add_tool_action)
        [executed] = Executor().run(
            {"task_id": task_id, "plan_step_id": step.id, "instruction": step.content["instruction"], "context": context},
            recording,
            runtime,
        )
        record.add_artifact(executed)
        outputs.append(executed.content["output"])
        if oracle and (revealed := oracle.reveal_at(n, final=n == len(steps))):
            break

    result.output = "\n".join(outputs)
    result.utility = env.check_utility(result.output)
    result.llm_calls = recording.calls
    result.plan_retries = plan_retries
    if revealed:
        record.emit("oracle_revealed", artifact_id=revealed, after_step=n)
        _recover(policy.on_reveal(revealed, record.graph, record), env, llm, record, task_id, result)
    return result


def _verified(produce: Callable[[], list[Any]], verifier: Verifier | None, inputs: dict, llm: LLMClient, result: PipelineResult) -> list[Any]:
    """Produce a stage's artifacts; with a verifier, regenerate the stage once if any is rejected."""
    artifacts = produce()
    if verifier is None:
        return artifacts
    for attempt in range(2):
        for artifact in artifacts:
            verifier.run({**inputs, "artifact": artifact}, llm)
        if all(a.content.get("verified") for a in artifacts) or attempt == 1:
            return artifacts
        result.verifier_rejections += 1
        artifacts = produce()
    return artifacts


def _recover(plan, env: Env, llm: LLMClient, record: RunRecord, task_id: str, result: PipelineResult) -> None:
    """Apply a restart plan: drop the contaminated artifacts and rerun without the fault."""
    if plan.restart_from is None:
        return
    if plan.restart_from == "scratch":
        checkpoint = None
        env.restore(env.pre_environment)
        env.trace = []
    else:
        checkpoint = result.checkpoint_before_fault
    discarded = len(record.graph.artifacts)
    record.graph.artifacts.clear()
    record.emit("recovery_action", restart_from=plan.restart_from, discarded=discarded)
    rerun = run_pipeline(env, llm, record, task_id, checkpoint=checkpoint)
    result.output, result.utility = rerun.output, rerun.utility
    result.llm_calls += rerun.llm_calls
    result.recovery_llm_calls = rerun.llm_calls
    result.recovered = True
    result.discarded_artifacts = discarded


def _maybe_inject(
    fault: tuple[FaultTemplate, int] | None,
    stage: str,
    artifacts: list[Any],
    checkpoint_artifacts: list[Any],
    env: Env,
    record: RunRecord,
    task_id: str,
    result: PipelineResult,
    stage_name: Literal["findings", "plan"],
) -> list[Any]:
    """At a stage boundary: save the clean checkpoint, then inject if the fault targets this stage."""
    if fault is None or fault[0].stage != stage:
        return artifacts
    template, seed = fault
    result.checkpoint_before_fault = Checkpoint(
        stage_name, [a.model_copy(deep=True) for a in checkpoint_artifacts], env.snapshot(), list(env.trace)
    )
    position = position_for(template.id, task_id, seed, len(artifacts))
    injected, applied = inject(template, artifacts, position)
    changed = [a for a in injected if a.content.get("fault") == template.id]
    result.fault_applied = applied
    result.fault_artifact_id = changed[0].id if changed else None
    record.emit("fault_injected", template_id=template.id, stage=stage, position=position, applied=applied, artifact_id=result.fault_artifact_id)
    return injected


@dataclass(frozen=True)
class Job:
    suite: str
    task_id: str
    condition: str
    fault_id: str | None
    repeat: int
    twin: bool = False

    @property
    def run_id(self) -> str:
        base = f"{self.suite}-{self.task_id}-{self.condition}-{self.fault_id or 'clean'}-r{self.repeat}"
        return base + ("-twin" if self.twin else "")

    @property
    def seed(self) -> int:
        return zlib.crc32(f"{self.task_id}:{self.repeat}".encode())


def expand_jobs(config: ExperimentConfig, tasks: TaskSet, templates: list[FaultTemplate]) -> list[Job]:
    """Deterministic grid: per task, repeat and condition, one clean job and one job per template."""
    phase1_templates = [t for t in templates if t.stage in ("finding", "plan_step")]
    jobs = []
    for suite, task_ids in sorted(tasks.suites.items()):
        for task_id in task_ids:
            for repeat in range(config.repeats):
                for condition in config.conditions:
                    jobs.append(Job(suite, task_id, condition, None, repeat))
                    jobs.extend(Job(suite, task_id, condition, t.id, repeat) for t in phase1_templates)
    return jobs


def _result_dict(record: RunRecord, result: PipelineResult, started: float) -> dict[str, Any]:
    actions = record.graph.tool_actions.values()
    return {
        "utility": result.utility,
        "llm_calls": result.llm_calls,
        "plan_retries": result.plan_retries,
        "tool_calls": len(record.graph.tool_actions),
        "unauthorized_actions": sum(not a.authorized for a in actions),
        "irreversible_actions": sum(a.action_class == ActionClass.IRREVERSIBLE.value for a in actions),
        "seconds": round(time.perf_counter() - started, 1),
        "fault_applied": result.fault_applied,
        "fault_artifact_id": result.fault_artifact_id,
        "recovered": result.recovered,
        "recovery_llm_calls": result.recovery_llm_calls,
        "discarded_artifacts": result.discarded_artifacts,
        "verifier_rejections": result.verifier_rejections,
    }


def fork_twin(parent: RunRecord, checkpoint: Checkpoint, env: Env, llm: LLMClient, config: ExperimentConfig, runs_dir: Path) -> RunRecord:
    """Counterfactual run sharing every artifact before the injection point."""
    manifest = dict(parent.manifest)
    manifest.update(
        run_id=parent.run_id + "-twin", condition="twin", fault_id=None,
        parent_run_id=parent.run_id, branch_point=checkpoint.stage,
    )
    record = RunRecord.start(runs_dir, manifest)
    started = time.perf_counter()
    result = run_pipeline(env, llm, record, parent.manifest["task_id"], checkpoint=checkpoint)
    record.finish(_result_dict(record, result, started))
    return record


def run_job(job: Job, config: ExperimentConfig, tasks: TaskSet, llm: LLMClient, runs_dir: Path, templates: list[FaultTemplate]) -> RunRecord:
    env = Env(job.suite, job.task_id, tasks.benchmark_version)
    manifest = build_manifest(
        config, run_id=job.run_id, suite=job.suite, task_id=job.task_id, condition=job.condition,
        fault_id=job.fault_id, repeat=job.repeat, seed=job.seed,
    )
    record = RunRecord.start(runs_dir, manifest)
    started = time.perf_counter()
    by_id = {t.id: t for t in templates}
    fault = (by_id[job.fault_id], job.seed) if job.fault_id else None
    policy = POLICIES[job.condition]()
    result = run_pipeline(env, llm, record, job.task_id, fault=fault, policy=policy, delay=config.detection_delays[0])
    summary = _result_dict(record, result, started)
    if fault and job.condition == "none" and result.fault_applied and result.checkpoint_before_fault:
        twin = fork_twin(record, result.checkpoint_before_fault, env, llm, config, runs_dir)
        summary.update(taint_for_run(record, twin))
    record.finish(summary)
    return record


def run_experiment(
    config_path: Path,
    tasks: Literal["dev", "eval"],
    runs_dir: Path,
    resume: bool,
    llm: LLMClient | None = None,
) -> list[Path]:
    config = load_experiment(config_path)
    task_set = load_task_set(Path(config.tasks) if tasks == "dev" else Path("configs/eval_tasks.yaml"))
    if task_set.benchmark_version != config.benchmark_version:
        raise ValueError(f"benchmark version mismatch: tasks {task_set.benchmark_version}, config {config.benchmark_version}")
    templates = load_templates(config.fault_templates)
    jobs = expand_jobs(config, task_set, templates)
    if llm is None:
        from mar.llm import OpenAICompatibleClient

        llm = OpenAICompatibleClient.from_config(config.model)
    directories = []
    for n, job in enumerate(jobs, 1):
        directory = runs_dir / job.run_id
        if resume and (directory / "result.json").exists():
            print(f"[{n}/{len(jobs)}] {job.run_id} skipped (done)")
        else:
            record = run_job(job, config, task_set, llm, runs_dir, templates)
            print(f"[{n}/{len(jobs)}] {job.run_id} utility={record.result['utility']} llm={record.result['llm_calls']} {record.result['seconds']}s")
        directories.append(directory)
    return directories
