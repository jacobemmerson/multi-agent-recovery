"""The orchestrator. The only module with side effects.

Runs one task (or an N-task memory session), wraps every agent call and tool action,
records provenance and events, applies faults and the recovery policy, and writes
runs/<run_id>/. fork_twin starts a counterfactual run from a pre-injection snapshot.
"""

import json
import subprocess
import time
from collections.abc import Callable
from datetime import datetime, timezone
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from typing import Literal

from agentdojo.functions_runtime import TaskEnvironment

from mar.agents import Executor, Planner, Researcher, ToolResult, load_prompt, prompt_hashes, tool_loop
from mar.artifacts import Artifact, Finding, PlanStep, ProvenanceGraph, ToolAction
from mar.config import ExperimentConfig
from mar.env import TOOL_ACTION_CLASSES, ActionClass, Env
from mar.faults import templates_hash
from mar.llm import LLMClient, LLMResponse


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


@dataclass
class PipelineResult:
    output: str
    utility: bool
    llm_calls: int
    plan_retries: int
    checkpoint_before_fault: Checkpoint | None = None


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
    fault: Any = None,
) -> PipelineResult:
    """Researcher → planner → one executor per step. Fault hooks land with the fault injector."""
    recording = _RecordingLLM(llm, record)
    inputs = {"task_id": task_id, "prompt": env.prompt}

    research_runtime = EnvToolRuntime(env, f"{task_id}:research", on_action=record.add_tool_action, allowed=read_only_tools(env))
    findings = Researcher().run(inputs, recording, research_runtime)
    for finding in findings:
        record.add_artifact(finding)

    steps = Planner().run({**inputs, "findings": findings}, recording)
    for step in steps:
        record.add_artifact(step)
    plan_retries = steps[0].content["retries"] if steps else 0

    by_id = {f.id: f for f in findings}
    outputs = []
    for step in steps:
        context = "\n".join(f"- {by_id[c].content.get('text', '')}" for c in step.cites if c in by_id)
        runtime = EnvToolRuntime(env, step.id, on_action=record.add_tool_action)
        [executed] = Executor().run(
            {"task_id": task_id, "plan_step_id": step.id, "instruction": step.content["instruction"], "context": context},
            recording,
            runtime,
        )
        record.add_artifact(executed)
        outputs.append(executed.content["output"])

    output = "\n".join(outputs)
    return PipelineResult(output=output, utility=env.check_utility(output), llm_calls=recording.calls, plan_retries=plan_retries)


def run_task(config: ExperimentConfig, condition: str, task_ids: list[str], fault_id: str | None, repeat: int, runs_dir: Path) -> RunRecord:
    raise NotImplementedError


def fork_twin(parent: RunRecord, branch_point: int, runs_dir: Path) -> RunRecord:
    """Counterfactual run sharing every artifact before the injection point."""
    raise NotImplementedError
