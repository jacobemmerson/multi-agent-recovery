"""Artifact comparison: exact diff, LLM judge, noise floor, and agreement with hand labels.

AgentDojo checkers judge final state only, so intermediate artifacts need their own judge.
Every propagation or divergence number is read against the clean-vs-clean noise floor.
"""

import json
from typing import Any, Callable

from mar.agents import load_prompt
from mar.artifacts import Artifact, ProvenanceGraph
from mar.llm import LLMClient


TEXT_FIELD = {"finding": "text", "plan_step": "instruction", "executed_step": "output", "note_entry": "text"}


def artifact_text(artifact: Artifact) -> str:
    """The artifact's substantive text; metadata such as retries, verified, fault is ignored."""
    return str(artifact.content.get(TEXT_FIELD[artifact.kind], ""))


def exact_diff(a: Artifact, b: Artifact) -> bool:
    return artifact_text(a) != artifact_text(b)


Differs = Callable[[Artifact, Artifact], bool]

JUDGE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"same": {"type": "boolean"}, "reason": {"type": "string"}},
    "required": ["same", "reason"],
    "additionalProperties": False,
}


def judge_verdict(a: Artifact, b: Artifact, llm: LLMClient, task_prompt: str = "") -> dict[str, Any]:
    """One judge call; a malformed verdict counts as a difference so a judge outage never hides propagation."""
    user = (
        f"Task given to the pipeline:\n{task_prompt}\n\n"
        f"Artifact kind: {a.kind}\n\n"
        f"Artifact A:\n{artifact_text(a)}\n\n"
        f"Artifact B:\n{artifact_text(b)}"
    )
    messages = [{"role": "system", "content": load_prompt("judge")}, {"role": "user", "content": user}]
    response = llm.complete(messages, schema=JUDGE_SCHEMA)
    try:
        verdict = json.loads(response.content or "")
        return {"differs": not bool(verdict["same"]), "reason": str(verdict.get("reason", ""))}
    except (json.JSONDecodeError, KeyError, TypeError) as error:
        return {"differs": True, "reason": f"judge_error: {type(error).__name__}: {response.content!r}"}


def judge_diff(a: Artifact, b: Artifact, llm: LLMClient, task_prompt: str = "") -> bool:
    return judge_verdict(a, b, llm, task_prompt)["differs"]


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


def pair_differs(pair: tuple[Artifact | None, Artifact | None], differs: Differs = exact_diff) -> bool:
    x, y = pair
    return x is None or y is None or differs(x, y)


def noise_floor(run_a, run_b, differs: Differs = exact_diff) -> dict[str, float]:
    """Fraction of positions that differ, per kind, between two runs of the same task."""
    pairs = match_artifacts(run_a.graph, run_b.graph)
    floor: dict[str, float] = {}
    for kind, key in zip(KINDS, ("findings", "plan_steps", "executed_steps")):
        of_kind = [p for p in pairs if (p[0] or p[1]).kind == kind]
        floor[key] = sum(pair_differs(p, differs) for p in of_kind) / len(of_kind) if of_kind else 0.0
    tools_a = [t.tool for t in sorted(run_a.graph.tool_actions.values(), key=lambda t: t.id)]
    tools_b = [t.tool for t in sorted(run_b.graph.tool_actions.values(), key=lambda t: t.id)]
    floor["tool_sequence_differs"] = tools_a != tools_b
    return floor


def agreement(judge_labels: list[bool], hand_labels: list[bool]) -> float:
    raise NotImplementedError
