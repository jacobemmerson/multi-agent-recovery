"""Per-run metrics and aggregation of runs/ into one parquet table.

Under/over-taint (RQ1), re-execution divergence (RQ2), residual irreversible actions vs Δ
(RQ3), unauthorized actions, collateral invalidation, re-infection, recomputed vs retained
work, latency, tokens, and tracking overhead. Aggregation filters by manifest fields.
"""

from pathlib import Path

import pandas as pd


def taint(declared: set[str], counterfactual: set[str]) -> dict[str, int]:
    return {
        "under_taint": len(counterfactual - declared),
        "over_taint": len(declared - counterfactual),
    }


def divergence(recovered_run, twin_run, floor: dict[str, float]) -> float:
    raise NotImplementedError


def harm(run) -> dict[str, int]:
    raise NotImplementedError


def cost(run) -> dict[str, float]:
    raise NotImplementedError


def aggregate(runs_dir: Path, out: Path) -> pd.DataFrame:
    raise NotImplementedError
