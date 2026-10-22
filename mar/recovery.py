"""Recovery policies and baselines, one small class each.

A policy is pure over the provenance graph and the run record. The orchestrator asks it
before every tool action and once when the oracle reveals a fault, then applies the plan.
"""

from dataclasses import dataclass, field
from typing import Literal, Protocol

from mar.artifacts import ProvenanceGraph, ToolAction

Decision = Literal["allow", "buffer", "block"]


@dataclass
class RecoveryPlan:
    invalidate: set[str] = field(default_factory=set)
    restore_snapshot: bool = False
    compensate: list[str] = field(default_factory=list)
    rerun: list[str] = field(default_factory=list)
    purge_notes: Literal["none", "coarse", "fine"] = "none"


class RecoveryPolicy(Protocol):
    name: str

    def on_tool_request(self, action: ToolAction, graph: ProvenanceGraph) -> Decision: ...

    def on_reveal(self, fault_id: str, graph: ProvenanceGraph, run) -> RecoveryPlan: ...


class NoRecovery:
    name = "none"

    def on_tool_request(self, action, graph) -> Decision:
        return "allow"

    def on_reveal(self, fault_id, graph, run) -> RecoveryPlan:
        return RecoveryPlan()


class RestartScratch:
    name = "restart_scratch"


class RestartStage:
    name = "restart_stage"


class AlwaysVerify:
    name = "always_verify"


class DAIRollback:
    """Dependency-aware invalidation; restore=False is the ablation without environment restore."""

    name = "dai_rollback"

    def __init__(self, restore: bool = True) -> None:
        self.restore = restore


class StagedCommit:
    """Buffer irreversible actions until their inputs are cleared or a budget expires."""

    name = "staged_commit"


class TaintGate:
    """Block sink actions whose provenance includes untrusted content (FIDES/CaMeL spirit)."""

    name = "taint_gate"


class StageEverything:
    """Cordon-style upper bound."""

    name = "stage_everything"


class AgentDojoDefenses:
    """AgentDojo's built-in PI detector / tool filter inserted as pipeline elements."""

    name = "agentdojo_defenses"


POLICIES = {
    cls.name: cls
    for cls in (NoRecovery, RestartScratch, RestartStage, AlwaysVerify, DAIRollback, StagedCommit, TaintGate, StageEverything, AgentDojoDefenses)
}
