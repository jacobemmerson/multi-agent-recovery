"""The orchestrator. The only module with side effects.

Runs one task (or an N-task memory session), wraps every agent call and tool action,
records provenance and events, applies faults and the recovery policy, and writes
runs/<run_id>/. fork_twin starts a counterfactual run from a pre-injection snapshot.
"""

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from mar.artifacts import ProvenanceGraph
from mar.config import ExperimentConfig


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


def run_task(config: ExperimentConfig, condition: str, task_ids: list[str], fault_id: str | None, repeat: int, runs_dir: Path) -> RunRecord:
    raise NotImplementedError


def fork_twin(parent: RunRecord, branch_point: int, runs_dir: Path) -> RunRecord:
    """Counterfactual run sharing every artifact before the injection point."""
    raise NotImplementedError
