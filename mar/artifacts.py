"""Artifact schemas and the declared provenance graph.

Every artifact records its producer, cited inputs, tool reads, and note reads. This is
what the orchestrator can see; ground-truth influence comes from counterfactual twins.
"""

from typing import Annotated, Literal

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


AnyArtifact = Annotated[Finding | PlanStep | ExecutedStep | NoteEntry, Field(discriminator="kind")]


class ProvenanceGraph(BaseModel):
    artifacts: dict[str, AnyArtifact] = Field(default_factory=dict)
    tool_actions: dict[str, ToolAction] = Field(default_factory=dict)

    def add(self, artifact: Artifact) -> None:
        self.artifacts[artifact.id] = artifact

    def descendants(self, artifact_id: str) -> set[str]:
        """Everything that transitively cites the artifact; declared provenance only."""
        children: dict[str, set[str]] = {}
        for artifact in self.artifacts.values():
            for cited in artifact.cites:
                children.setdefault(cited, set()).add(artifact.id)
        return self._closure(artifact_id, children)

    def ancestors(self, artifact_id: str) -> set[str]:
        parents = {a.id: set(a.cites) for a in self.artifacts.values()}
        return self._closure(artifact_id, parents)

    @staticmethod
    def _closure(start: str, edges: dict[str, set[str]]) -> set[str]:
        seen: set[str] = set()
        frontier = [start]
        while frontier:
            for nxt in edges.get(frontier.pop(), ()):
                if nxt not in seen:
                    seen.add(nxt)
                    frontier.append(nxt)
        return seen
