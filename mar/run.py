"""The orchestrator. The only module with side effects.

Runs one task (or an N-task memory session), wraps every agent call and tool action,
records provenance and events, applies faults and the recovery policy, and writes
runs/<run_id>/. fork_twin starts a counterfactual run from a pre-injection snapshot.
"""

import json
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from mar.agents import ToolResult, load_prompt, tool_loop
from mar.artifacts import ProvenanceGraph, ToolAction
from mar.config import ExperimentConfig
from mar.env import TOOL_ACTION_CLASSES, Env
from mar.llm import LLMClient


@dataclass
class RunRecord:
    run_id: str
    directory: Path
    manifest: dict[str, Any]
    graph: ProvenanceGraph = field(default_factory=ProvenanceGraph)
    events: list[dict[str, Any]] = field(default_factory=list)

    def emit(self, kind: str, **payload: Any) -> None:
        event = {"seq": len(self.events), "kind": kind, **payload}
        self.events.append(event)
        with (self.directory / "events.jsonl").open("a") as handle:
            handle.write(json.dumps(event) + "\n")

    def finish(self, result: dict[str, Any]) -> None:
        (self.directory / "provenance.json").write_text(self.graph.model_dump_json(indent=2))
        (self.directory / "result.json").write_text(json.dumps(result, indent=2))


class EnvToolRuntime:
    """ToolRuntime over an Env: executes, tags, and reports every tool action."""

    def __init__(self, env: Env, step_id: str, on_action: Callable[[ToolAction], None] | None = None) -> None:
        self.env = env
        self.step_id = step_id
        self.on_action = on_action
        self.count = 0

    def tool_schemas(self) -> list[dict[str, Any]]:
        return self.env.tool_schemas()

    def call(self, name: str, args: dict[str, Any]) -> ToolResult:
        self.count += 1
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


def run_task(config: ExperimentConfig, condition: str, task_ids: list[str], fault_id: str | None, repeat: int, runs_dir: Path) -> RunRecord:
    raise NotImplementedError


def fork_twin(parent: RunRecord, branch_point: int, runs_dir: Path) -> RunRecord:
    """Counterfactual run sharing every artifact before the injection point."""
    raise NotImplementedError
