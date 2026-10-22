"""Artifact schemas and the declared provenance graph.

Every artifact records its producer, cited inputs, tool reads, and note reads. This is
what the orchestrator can see; ground-truth influence comes from counterfactual twins.
"""

from typing import Literal

from pydantic import BaseModel, Field


class Artifact(BaseModel):
    id: str
    kind: Literal["finding", "plan_step", "executed_step", "note_entry"]
    producer: str
    task_id: str
    branch_id: str = "main"
    cites: list[str] = Field(default_factory=list)
    tool_reads: list[str] = Field(default_factory=list)
    note_reads: list[str] = Field(default_factory=list)
    content: dict = Field(default_factory=dict)


class Finding(Artifact):
    kind: Literal["finding"] = "finding"
    source: str


class PlanStep(Artifact):
    kind: Literal["plan_step"] = "plan_step"
    index: int


class ExecutedStep(Artifact):
    kind: Literal["executed_step"] = "executed_step"
    plan_step_id: str


class NoteEntry(Artifact):
    kind: Literal["note_entry"] = "note_entry"


class ToolAction(BaseModel):
    id: str
    step_id: str
    tool: str
    args: dict
    action_class: str
    authorized: bool
    result: str | None = None


class ProvenanceGraph(BaseModel):
    artifacts: dict[str, Artifact] = Field(default_factory=dict)
    tool_actions: dict[str, ToolAction] = Field(default_factory=dict)

    def add(self, artifact: Artifact) -> None:
        self.artifacts[artifact.id] = artifact

    def descendants(self, artifact_id: str) -> set[str]:
        raise NotImplementedError

    def ancestors(self, artifact_id: str) -> set[str]:
        raise NotImplementedError
