"""Artifact comparison: exact diff, LLM judge, noise floor, and agreement with hand labels.

AgentDojo checkers judge final state only, so intermediate artifacts need their own judge.
Every propagation or divergence number is read against the clean-vs-clean noise floor.
"""

from itertools import zip_longest

from mar.artifacts import Artifact, ProvenanceGraph
from mar.llm import LLMClient


def exact_diff(a: Artifact, b: Artifact) -> bool:
    return a.content != b.content


def judge_diff(a: Artifact, b: Artifact, llm: LLMClient) -> bool:
    raise NotImplementedError


KINDS = ("finding", "plan_step", "executed_step")


def _ordered(graph: ProvenanceGraph, kind: str) -> list[Artifact]:
    items = [a for a in graph.artifacts.values() if a.kind == kind]
    if kind == "plan_step":
        return sorted(items, key=lambda a: a.index)
    return sorted(items, key=lambda a: a.id)


def match_by_position(a: ProvenanceGraph, b: ProvenanceGraph) -> list[tuple[Artifact | None, Artifact | None]]:
    """Pair artifacts of the same kind by position; an unmatched tail pairs with None."""
    pairs: list[tuple[Artifact | None, Artifact | None]] = []
    for kind in KINDS:
        pairs.extend(zip_longest(_ordered(a, kind), _ordered(b, kind)))
    return pairs


def _differs(pair: tuple[Artifact | None, Artifact | None]) -> bool:
    x, y = pair
    return x is None or y is None or exact_diff(x, y)


def noise_floor(run_a, run_b) -> dict[str, float]:
    """Fraction of positions that differ, per kind, between two runs of the same task."""
    pairs = match_by_position(run_a.graph, run_b.graph)
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
