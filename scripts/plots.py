"""Figures from runs/aggregate.parquet: noise floor, propagation, taint, baselines.

Usage: python scripts/plots.py runs/aggregate.parquet figures/
"""

import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402

from mar.metrics import bootstrap_ci  # noqa: E402


def _bar_with_ci(ax, groups: dict[str, list[float]], title: str, ylabel: str) -> None:
    labels = list(groups)
    means = [sum(v) / len(v) if v else 0.0 for v in groups.values()]
    cis = [bootstrap_ci(v) if v else (0.0, 0.0) for v in groups.values()]
    errors = [[m - lo for m, (lo, _) in zip(means, cis)], [hi - m for m, (_, hi) in zip(means, cis)]]
    ax.bar(range(len(labels)), means, yerr=errors, capsize=3)
    ax.set_xticks(range(len(labels)), labels, rotation=45, ha="right")
    ax.set_title(title)
    ax.set_ylabel(ylabel)


def taint_column(df: pd.DataFrame, name: str) -> str:
    """The judge's version of a taint column when `mar judge` has run, else the exact-diff one."""
    judged = f"judged_{name}"
    return judged if judged in df.columns else name


def plot_propagation(df: pd.DataFrame, out: Path) -> None:
    ignored = taint_column(df, "ignored")
    faulted = df[(df["condition"] == "none") & df["fault_id"].notna() & df[ignored].notna()]
    groups = {fid: (~g[ignored].astype(bool)).astype(float).tolist() for fid, g in faulted.groupby("fault_id")}
    fig, ax = plt.subplots(figsize=(9, 4))
    _bar_with_ci(ax, groups, f"Propagation: fraction of faults that changed downstream artifacts ({ignored})", "fraction")
    fig.tight_layout()
    fig.savefig(out / "propagation.png", dpi=150)


def plot_taint(df: pd.DataFrame, out: Path) -> None:
    under, over = taint_column(df, "under_taint"), taint_column(df, "over_taint")
    faulted = df[(df["condition"] == "none") & df[under].notna()]
    faulted = faulted.assign(stage=faulted["fault_id"].str.split("_").str[0])
    fig, axes = plt.subplots(1, 2, figsize=(9, 4))
    for ax, metric in zip(axes, (under, over)):
        groups = {stage: g[metric].astype(float).tolist() for stage, g in faulted.groupby("stage")}
        _bar_with_ci(ax, groups, metric.replace("_", " "), "artifacts")
    fig.tight_layout()
    fig.savefig(out / "taint.png", dpi=150)


def baseline_groups(df: pd.DataFrame, metric: str) -> dict[str, list[float]]:
    """Per condition, the metric over runs whose fault actually applied; unapplied faults are clean runs."""
    landed = df[df["fault_applied"] == True]  # noqa: E712 -- pandas boolean column with NaNs
    return {c: g[metric].astype(float).tolist() for c, g in landed.groupby("condition")}


def plot_baselines(df: pd.DataFrame, out: Path) -> None:
    fig, axes = plt.subplots(1, 3, figsize=(13, 4))
    _bar_with_ci(axes[0], baseline_groups(df, "utility"), "Utility after an applied fault", "pass rate")
    _bar_with_ci(axes[1], baseline_groups(df, "llm_calls"), "Cost", "LLM calls per run")
    _bar_with_ci(axes[2], baseline_groups(df, "completion_tokens"), "Cost", "completion tokens per run")
    fig.tight_layout()
    fig.savefig(out / "baselines.png", dpi=150)


def plot_noise_floor(df: pd.DataFrame, out: Path) -> None:
    """Noise floor per task from clean runs, if the aggregate carries it (added by a later analysis step)."""
    kinds = ("findings", "plan_steps", "executed_steps")
    prefix = "floor_judged_" if "floor_judged_findings" in df.columns else "floor_"
    columns = [prefix + kind for kind in kinds if prefix + kind in df.columns]
    if not columns:
        return
    clean = df[df["fault_id"].isna()].groupby("task_id")[columns].mean()
    ax = clean.plot.bar(figsize=(9, 4), title="Clean-vs-clean noise floor per task")
    ax.set_ylabel("fraction differing")
    ax.figure.tight_layout()
    ax.figure.savefig(out / "noise_floor.png", dpi=150)


def main(parquet: Path, out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    df = pd.read_parquet(parquet)
    for plot in (plot_propagation, plot_taint, plot_baselines, plot_noise_floor):
        try:
            plot(df, out_dir)
        except (KeyError, ValueError) as error:
            print(f"{plot.__name__}: skipped ({error})")
    print(f"figures in {out_dir}")


if __name__ == "__main__":
    main(Path(sys.argv[1]), Path(sys.argv[2]))
