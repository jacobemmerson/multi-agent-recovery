"""Per-run metrics and aggregation of runs/ into one parquet table.

Under/over-taint (RQ1), re-execution divergence (RQ2), residual irreversible actions vs Δ
(RQ3), unauthorized actions, collateral invalidation, re-infection, recomputed vs retained
work, latency, tokens, and tracking overhead. Aggregation filters by manifest fields.
"""

import json
import math
import random
from pathlib import Path

import pandas as pd

from mar.judge import STAGE_ORDER, Differs, exact_diff, match_artifacts, noise_floor


def taint(declared: set[str], counterfactual: set[str]) -> dict[str, int]:
    return {
        "under_taint": len(counterfactual - declared),
        "over_taint": len(declared - counterfactual),
    }


def counterfactual_changed(faulted, twin, fault_artifact_id: str, differs: Differs = exact_diff) -> set[str]:
    """Faulted-run artifacts at or after the fault's stage whose twin partner differs or is missing."""
    fault_stage = STAGE_ORDER[faulted.graph.artifacts[fault_artifact_id].kind]
    changed = set()
    for mine, theirs in match_artifacts(faulted.graph, twin.graph):
        if mine is None or mine.id == fault_artifact_id or STAGE_ORDER[mine.kind] < fault_stage:
            continue
        if theirs is None or differs(mine, theirs):
            changed.add(mine.id)
    return changed


def taint_for_run(faulted, twin, differs: Differs = exact_diff) -> dict:
    fault_id = next(e["artifact_id"] for e in faulted.events if e["kind"] == "fault_injected")
    declared = faulted.graph.descendants(fault_id)
    changed = counterfactual_changed(faulted, twin, fault_id, differs)
    return taint(declared, changed) | {
        "declared_descendants": len(declared),
        "counterfactual_changed": len(changed),
        "ignored": not changed,
    }


def divergence(recovered_run, twin_run, floor: dict[str, float]) -> float:
    raise NotImplementedError


def harm(run) -> dict[str, int]:
    raise NotImplementedError


def cost(run) -> dict[str, float]:
    raise NotImplementedError


def bootstrap_ci(values, n: int = 1000, seed: int = 0, level: float = 0.95) -> tuple[float, float]:
    """Percentile bootstrap interval for the mean."""
    values = list(values)
    if not values:
        return (math.nan, math.nan)
    rng = random.Random(seed)
    means = sorted(sum(rng.choices(values, k=len(values))) / len(values) for _ in range(n))
    lo = means[int((1 - level) / 2 * n)]
    hi = means[min(int((1 + level) / 2 * n), n - 1)]
    return (lo, hi)


def _with_noise_floor(frame: pd.DataFrame, runs_dir: Path) -> pd.DataFrame:
    """Clean-vs-clean floor per (task, condition) from the two lowest clean repeats, joined onto every row of that group."""
    from mar.run import load_run

    clean = frame[frame["fault_id"].isna()]
    for (task_id, condition), group in clean.groupby(["task_id", "condition"]):
        if len(group) < 2:
            continue
        first, second = group.sort_values("repeat")["run_id"].iloc[:2]
        floor = noise_floor(load_run(runs_dir / first), load_run(runs_dir / second))
        mask = (frame["task_id"] == task_id) & (frame["condition"] == condition)
        for key in ("findings", "plan_steps", "executed_steps"):
            frame.loc[mask, f"floor_{key}"] = floor[key]
    return frame


def aggregate(runs_dir: Path, out: Path) -> pd.DataFrame:
    """One row per finished run: manifest fields plus result fields. Written to `out` as parquet."""
    rows = []
    skipped = 0
    for manifest_path in sorted(runs_dir.glob("*/manifest.json")):
        result_path = manifest_path.parent / "result.json"
        if not result_path.exists():
            skipped += 1
            continue
        manifest = json.loads(manifest_path.read_text())
        if "prompt_hashes" in manifest:
            manifest["prompt_hashes"] = json.dumps(manifest["prompt_hashes"])
        rows.append(manifest | json.loads(result_path.read_text()))
    frame = pd.DataFrame(rows)
    if len(frame) and {"task_id", "condition", "fault_id", "repeat"} <= set(frame.columns):
        frame = _with_noise_floor(frame, runs_dir)
    out.parent.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(out, index=False)
    print(f"aggregated {len(frame)} runs to {out}" + (f", skipped {skipped} unfinished" if skipped else ""))
    return frame
