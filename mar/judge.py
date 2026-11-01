"""Artifact comparison: exact diff, LLM judge, noise floor, and agreement with hand labels.

AgentDojo checkers judge final state only, so intermediate artifacts need their own judge.
Every propagation or divergence number is read against the clean-vs-clean noise floor.
"""

import json
import random
from pathlib import Path
from typing import Any, Callable

import pandas as pd

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
    return sum(j == h for j, h in zip(judge_labels, hand_labels, strict=True)) / len(judge_labels)


JUDGMENTS_FILE = "judge.json"


def _finished_runs(runs_dir: Path) -> dict[Path, tuple[dict, dict]]:
    runs = {}
    for manifest_path in sorted(runs_dir.glob("*/manifest.json")):
        result_path = manifest_path.parent / "result.json"
        if result_path.exists():
            runs[manifest_path.parent] = (json.loads(manifest_path.read_text()), json.loads(result_path.read_text()))
    return runs


def pairs_to_judge(runs_dir: Path) -> list[tuple[Path, Path]]:
    """(faulted `none` run, its twin) for every applied fault with a finished twin, and the two lowest
    clean repeats per (task, condition). The left run's directory owns judge.json."""
    runs = _finished_runs(runs_dir)
    clean: dict[tuple[str, str], list[tuple[int, Path]]] = {}
    pairs = []
    for directory, (manifest, result) in runs.items():
        if manifest["condition"] == "twin" or "error" in result:
            continue
        if manifest["fault_id"] is None:
            clean.setdefault((manifest["task_id"], manifest["condition"]), []).append((manifest["repeat"], directory))
        elif manifest["condition"] == "none" and result.get("fault_applied") and "twin_error" not in result:
            twin = runs_dir / (directory.name + "-twin")
            if twin in runs:
                pairs.append((directory, twin))
    for repeats in clean.values():
        if len(repeats) >= 2:
            (_, first), (_, second) = sorted(repeats)[:2]
            pairs.append((first, second))
    return sorted(pairs)


def _judgeable(left, right) -> list[tuple[Artifact, Artifact]]:
    """Matched pairs with both sides present; for a faulted run, only artifacts at or after the fault stage,
    excluding the fault itself (the set `metrics.counterfactual_changed` reads)."""
    fault_id = next((e["artifact_id"] for e in left.events if e["kind"] == "fault_injected"), None)
    fault_stage = STAGE_ORDER[left.graph.artifacts[fault_id].kind] if fault_id in left.graph.artifacts else -1
    return [
        (a, b) for a, b in match_artifacts(left.graph, right.graph)
        if a is not None and b is not None and a.id != fault_id and STAGE_ORDER[a.kind] >= fault_stage
    ]


def _env_prompt(suite: str, task_id: str) -> str:
    from mar.env import Env

    return Env(suite, task_id).prompt


def judge_runs(
    runs_dir: Path,
    llm: LLMClient,
    task_prompt_for: Callable[[str, str], str] = _env_prompt,
    rejudge: bool = False,
) -> dict[str, int]:
    """Judge every pair from `pairs_to_judge`, writing judge.json after each pair so the batch resumes."""
    from mar.run import load_run

    counts = {"pairs": 0, "artifacts_judged": 0, "skipped": 0, "identical": 0}
    prompts: dict[tuple[str, str], str] = {}
    for left_dir, right_dir in pairs_to_judge(runs_dir):
        left, right = load_run(left_dir), load_run(right_dir)
        key = (left.manifest["suite"], left.manifest["task_id"])
        prompts.setdefault(key, task_prompt_for(*key))
        path = left_dir / JUDGMENTS_FILE
        judgments = {} if rejudge or not path.exists() else json.loads(path.read_text())
        counts["pairs"] += 1
        for a, b in _judgeable(left, right):
            if a.id in judgments:
                counts["skipped"] += 1
            elif not exact_diff(a, b):
                judgments[a.id] = {"differs": False, "reason": "identical text"}
                counts["identical"] += 1
            else:
                judgments[a.id] = judge_verdict(a, b, llm, prompts[key])
                counts["artifacts_judged"] += 1
        path.write_text(json.dumps(judgments, indent=1))
    return counts


def load_judgments(directory: Path) -> dict[str, bool]:
    path = directory / JUDGMENTS_FILE
    if not path.exists():
        return {}
    return {artifact_id: v["differs"] for artifact_id, v in json.loads(path.read_text()).items()}


def judged_differs(judgments: dict[str, bool]) -> Differs:
    """Judge verdict by artifact id, falling back to exact diff for anything unjudged."""
    return lambda a, b: judgments[a.id] if a.id in judgments else exact_diff(a, b)


def sample_for_hand_labels(runs_dir: Path, n: int = 50, seed: int = 0) -> pd.DataFrame:
    from mar.run import load_run

    rows = []
    for left_dir, right_dir in pairs_to_judge(runs_dir):
        judgments = load_judgments(left_dir)
        if not judgments:
            continue
        left, right = load_run(left_dir), load_run(right_dir)
        for a, b in _judgeable(left, right):
            if a.id in judgments:
                rows.append({"run_id": left.run_id, "artifact_id": a.id, "kind": a.kind, "text_a": artifact_text(a),
                             "text_b": artifact_text(b), "judge_differs": judgments[a.id], "hand_differs": ""})
    chosen = random.Random(seed).sample(rows, min(n, len(rows)))
    return pd.DataFrame(chosen, columns=["run_id", "artifact_id", "kind", "text_a", "text_b", "judge_differs", "hand_differs"])
