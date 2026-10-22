"""Per-run metrics and aggregation of runs/ into one parquet table.

Under/over-taint (RQ1), re-execution divergence (RQ2), residual irreversible actions vs Δ
(RQ3), unauthorized actions, collateral invalidation, re-infection, recomputed vs retained
work, latency, tokens, and tracking overhead. Aggregation filters by manifest fields.
"""

from pathlib import Path

import pandas as pd

from mar.judge import STAGE_ORDER, exact_diff, match_by_position


def taint(declared: set[str], counterfactual: set[str]) -> dict[str, int]:
    return {
        "under_taint": len(counterfactual - declared),
        "over_taint": len(declared - counterfactual),
    }


def counterfactual_changed(faulted, twin, fault_artifact_id: str) -> set[str]:
    """Faulted-run artifacts at or after the fault's stage whose twin partner differs or is missing."""
    fault_stage = STAGE_ORDER[faulted.graph.artifacts[fault_artifact_id].kind]
    changed = set()
    for mine, theirs in match_by_position(faulted.graph, twin.graph):
        if mine is None or mine.id == fault_artifact_id or STAGE_ORDER[mine.kind] < fault_stage:
            continue
        if theirs is None or exact_diff(mine, theirs):
            changed.add(mine.id)
    return changed


def taint_for_run(faulted, twin) -> dict:
    fault_id = next(e["artifact_id"] for e in faulted.events if e["kind"] == "fault_injected")
    declared = faulted.graph.descendants(fault_id)
    changed = counterfactual_changed(faulted, twin, fault_id)
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


def aggregate(runs_dir: Path, out: Path) -> pd.DataFrame:
    raise NotImplementedError
