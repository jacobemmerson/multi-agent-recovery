"""Artifact comparison: exact diff, LLM judge, noise floor, and agreement with hand labels.

AgentDojo checkers judge final state only, so intermediate artifacts need their own judge.
Every propagation or divergence number is read against the clean-vs-clean noise floor.
"""

from mar.artifacts import Artifact, ProvenanceGraph
from mar.llm import LLMClient


TEXT_FIELD = {"finding": "text", "plan_step": "instruction", "executed_step": "output", "note_entry": "text"}


def artifact_text(artifact: Artifact) -> str:
    """The artifact's substantive text; metadata such as retries, verified, fault is ignored."""
    return str(artifact.content.get(TEXT_FIELD[artifact.kind], ""))


def exact_diff(a: Artifact, b: Artifact) -> bool:
    return artifact_text(a) != artifact_text(b)


def judge_diff(a: Artifact, b: Artifact, llm: LLMClient) -> bool:
    raise NotImplementedError


KINDS = ("finding", "plan_step", "executed_step")
STAGE_ORDER = {kind: i for i, kind in enumerate(KINDS)}


def match_artifacts(a: ProvenanceGraph, b: ProvenanceGraph) -> list[tuple[Artifact | None, Artifact | None]]:
    """Pair artifacts of the same kind by id (ids are deterministic per task and position);
    an artifact with no partner pairs with None."""
    pairs: list[tuple[Artifact | None, Artifact | None]] = []
    for kind in KINDS:
        mine = {x.id: x for x in a.artifacts.values() if x.kind == kind}
        theirs = {x.id: x for x in b.artifacts.values() if x.kind == kind}
        for artifact_id in sorted(mine | theirs):
            pairs.append((mine.get(artifact_id), theirs.get(artifact_id)))
    return pairs


def _differs(pair: tuple[Artifact | None, Artifact | None]) -> bool:
    x, y = pair
    return x is None or y is None or exact_diff(x, y)


def noise_floor(run_a, run_b) -> dict[str, float]:
    """Fraction of positions that differ, per kind, between two runs of the same task."""
    pairs = match_artifacts(run_a.graph, run_b.graph)
    floor: dict[str, float] = {}
    for kind, key in zip(KINDS, ("findings", "plan_steps", "executed_steps")):
        of_kind = [p for p in pairs if (p[0] or p[1]).kind == kind]
        floor[key] = sum(map(_differs, of_kind)) / len(of_kind) if of_kind else 0.0
    tools_a = [t.tool for t in sorted(run_a.graph.tool_actions.values(), key=lambda t: t.id)]
    tools_b = [t.tool for t in sorted(run_b.graph.tool_actions.values(), key=lambda t: t.id)]
    floor["tool_sequence_differs"] = tools_a != tools_b
    return floor


def agreement(judge_labels: list[bool], hand_labels: list[bool]) -> float:
    raise NotImplementedError
