"""Recovery policies and baselines, one small class each.

A policy is pure over the provenance graph and the run record. The orchestrator asks it
before every tool action and once when the oracle reveals a fault, then applies the plan.
"""

from dataclasses import dataclass, field
from typing import Literal

from mar.artifacts import ProvenanceGraph, ToolAction

Decision = Literal["allow", "buffer", "block"]
RestartFrom = Literal["scratch", "findings", "plan"]

STAGE_OF_KIND: dict[str, RestartFrom] = {"finding": "findings", "plan_step": "plan", "executed_step": "plan"}


@dataclass
class RecoveryPlan:
    restart_from: RestartFrom | None = None
    invalidate: set[str] = field(default_factory=set)
    restore_snapshot: bool = False
    compensate: list[str] = field(default_factory=list)
    rerun: list[str] = field(default_factory=list)
    purge_notes: Literal["none", "coarse", "fine"] = "none"


class RecoveryPolicy:
    """Default: allow everything, never restart. Subclasses override what they change."""

    name = "none"
    verify_every_artifact = False

    def on_tool_request(self, action: ToolAction, graph: ProvenanceGraph) -> Decision:
        return "allow"

    def on_reveal(self, fault_id: str, graph: ProvenanceGraph, run) -> RecoveryPlan:
        return RecoveryPlan()


class NoRecovery(RecoveryPolicy):
    name = "none"


class RestartScratch(RecoveryPolicy):
    name = "restart_scratch"

    def on_reveal(self, fault_id, graph, run) -> RecoveryPlan:
        return RecoveryPlan(restart_from="scratch")


class RestartStage(RecoveryPolicy):
    """Discard everything from the faulty stage on; keep earlier artifacts."""

    name = "restart_stage"

    def on_reveal(self, fault_id, graph, run) -> RecoveryPlan:
        return RecoveryPlan(restart_from=STAGE_OF_KIND[graph.artifacts[fault_id].kind])


class AlwaysVerify(RecoveryPolicy):
    """A verifier LLM call checks every artifact before it is passed on. Uses no oracle."""

    name = "always_verify"
    verify_every_artifact = True


class DAIRollback(RecoveryPolicy):
    """Dependency-aware invalidation; restore=False is the ablation without environment restore."""

    name = "dai_rollback"

    def __init__(self, restore: bool = True) -> None:
        self.restore = restore


class StagedCommit(RecoveryPolicy):
    """Buffer irreversible actions until their inputs are cleared or a budget expires."""

    name = "staged_commit"


class TaintGate(RecoveryPolicy):
    """Block sink actions whose provenance includes untrusted content (FIDES/CaMeL spirit)."""

    name = "taint_gate"


class StageEverything(RecoveryPolicy):
    """Cordon-style upper bound."""

    name = "stage_everything"


class AgentDojoDefenses(RecoveryPolicy):
    """AgentDojo's built-in PI detector / tool filter inserted as pipeline elements."""

    name = "agentdojo_defenses"


POLICIES: dict[str, type[RecoveryPolicy]] = {
    cls.name: cls
    for cls in (NoRecovery, RestartScratch, RestartStage, AlwaysVerify, DAIRollback, StagedCommit, TaintGate, StageEverything, AgentDojoDefenses)
}
