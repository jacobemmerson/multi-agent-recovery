"""The Phase 1 results figure: propagation per template, noise floor, taint, and baselines as small multiples.

Usage: python scripts/findings_figure.py runs/phase1_flash/aggregate.parquet docs/findings.png
Writes docs/findings.png and docs/findings.pdf.
"""

import sys
from pathlib import Path

import pandas as pd

from mar.metrics import bootstrap_ci
from scripts import figure_style as style
from scripts.plots import baseline_groups

style.apply()
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.lines import Line2D  # noqa: E402

CONDITIONS = ["none", "restart_stage", "restart_scratch", "always_verify"]
CONDITION_LABELS = ["none", "restart\nstage", "restart\nscratch", "always\nverify"]
STAGES = [("finding", "Finding faults"), ("plan", "Plan-step faults")]
TYPES = ["accidental", "adversarial", "other"]
STRENGTHS = ["obvious", "subtle"]


def mean_ci(values):
    values = [float(v) for v in values]
    mean = sum(values) / len(values)
    lo, hi = bootstrap_ci(values)
    return mean, mean - lo, hi - mean


def faulted_runs(df: pd.DataFrame) -> pd.DataFrame:
    faulted = df[(df["condition"] == "none") & df["fault_id"].notna() & df["judged_ignored"].notna()].copy()
    parts = faulted["fault_id"].str.extract(r"^(finding|plan_step)_(\w+?)_(obvious|subtle)$")
    faulted["stage"] = parts[0].str.replace("plan_step", "plan")
    faulted["type"], faulted["strength"] = parts[1], parts[2]
    faulted["propagated"] = 1 - faulted["judged_ignored"].astype(float)
    return faulted


def propagation_panel(ax, df: pd.DataFrame) -> None:
    faulted = faulted_runs(df)
    rows = [(stage, label, t, s) for stage, label in STAGES for t in TYPES for s in STRENGTHS]
    y = 0
    ticks, labels = [], []
    for stage, stage_label in STAGES:
        ax.text(-0.02, y + 0.15, stage_label, transform=ax.get_yaxis_transform(), ha="right", va="center",
                fontsize=7, fontweight="bold", color=style.INK)
        y += 1.1
        for t in TYPES:
            for s in STRENGTHS:
                g = faulted[(faulted["stage"] == stage) & (faulted["type"] == t) & (faulted["strength"] == s)]
                mean, lo, hi = mean_ci(g["propagated"])
                color = style.FAULT_TYPE_COLOR[t]
                ax.errorbar(mean, y, xerr=[[lo], [hi]], fmt="o", color=color, ms=4, elinewidth=1, capsize=0, zorder=3)
                ticks.append(y)
                labels.append(f"{t}, {s} ({len(g)})")
                y += 1
        y += 0.6
    ax.set_yticks(ticks, labels)
    ax.set_ylim(y - 0.6, -0.6)
    ax.set_xlim(0, 1.04)
    ax.set_xticks([0, 0.25, 0.5, 0.75, 1.0], ["0", "", "0.5", "", "1"])
    ax.grid(axis="x")
    ax.grid(False, axis="y")
    ax.tick_params(axis="y", length=0)
    ax.set_xlabel("fraction of applied faults that changed a downstream artifact")
    ax.set_title("(a) Propagation by fault template")
    handles = [Line2D([], [], marker="o", color=style.FAULT_TYPE_COLOR[t], ls="", ms=4, label=t) for t in TYPES]
    ax.legend(handles=handles, loc="lower left", ncol=1, bbox_to_anchor=(0.0, 0.0), borderaxespad=0.2)


def grouped_bars(ax, categories, series, width=0.36):
    """series: list of (label, color, means, (lo_err, hi_err) or None). Leaves a 2px-equivalent gap between fills."""
    x = range(len(categories))
    k = len(series)
    for j, (label, color, means, errs) in enumerate(series):
        offset = (j - (k - 1) / 2) * (width + 0.03)
        xs = [i + offset for i in x]
        ax.bar(xs, means, width, color=color, label=label, zorder=3)
        if errs is not None:
            ax.errorbar(xs, means, yerr=errs, fmt="none", ecolor=style.INK, elinewidth=0.8, capsize=0, zorder=4)
    ax.set_xticks(list(x), categories)
    ax.tick_params(axis="x", length=0)


def floor_panel(ax, df: pd.DataFrame) -> None:
    clean = df[df["fault_id"].isna() & (df["condition"] == "none")].groupby("task_id").first()
    kinds = ["findings", "plan_steps", "executed_steps"]
    exact = [clean[f"floor_{k}"].mean() for k in kinds]
    judged = [clean[f"floor_judged_{k}"].mean() for k in kinds]
    grouped_bars(ax, ["findings", "plan\nsteps", "executed\nsteps"],
                 [("exact text diff", style.GRAY, exact, None), ("LLM judge", style.BLUE, judged, None)])
    ax.set_ylim(0, 1.3)
    ax.set_yticks([0, 0.2, 0.4, 0.6, 0.8, 1.0])
    ax.set_ylabel("fraction of artifacts changed")
    ax.set_title("(b) Noise floor")
    ax.legend(loc="upper right", ncol=1)


def taint_panel(ax, df: pd.DataFrame) -> None:
    faulted = faulted_runs(df)
    series = []
    for label, color, metric in (("under-taint", style.BLUE, "judged_under_taint"), ("over-taint", style.ORANGE, "judged_over_taint")):
        stats = [mean_ci(faulted.loc[faulted["stage"] == s, metric]) for s, _ in STAGES]
        series.append((label, color, [m for m, _, _ in stats], ([lo for _, lo, _ in stats], [hi for _, _, hi in stats])))
    grouped_bars(ax, ["finding\nfault", "plan-step\nfault"], series)
    ax.set_ylim(0, 0.9)
    ax.set_ylabel("artifacts per run")
    ax.set_title("(c) Taint vs. twin")
    ax.legend(loc="upper right")


def baseline_panel(ax, df: pd.DataFrame, metric: str, title: str, ylabel: str, ylim, fmt: str, ci: bool = True) -> None:
    groups = baseline_groups(df, metric)
    stats = [mean_ci(groups[c]) for c in CONDITIONS]
    colors = [style.GRAY] + [style.BLUE] * 3
    x = range(len(CONDITIONS))
    ax.bar(list(x), [m for m, _, _ in stats], 0.6, color=colors, zorder=3)
    if ci:
        ax.errorbar(list(x), [m for m, _, _ in stats], yerr=([lo for _, lo, _ in stats], [hi for _, _, hi in stats]),
                    fmt="none", ecolor=style.INK, elinewidth=0.8, capsize=0, zorder=4)
    for i, (m, _, hi) in enumerate(stats):
        ax.text(i, m + (hi if ci else 0) + ylim * 0.02, fmt.format(m), ha="center", va="bottom", fontsize=6, color=style.INK)
    ax.set_xticks(list(x), CONDITION_LABELS, fontsize=6)
    ax.tick_params(axis="x", length=0)
    ax.set_ylim(0, ylim)
    ax.set_ylabel(ylabel)
    ax.set_title(title)


def main(parquet: Path, out: Path) -> None:
    """Writes <out> (propagation, noise floor, taint) and <stem>_baselines.<ext> (the four baseline panels)."""
    df = pd.read_parquet(parquet)
    fig, axes = plt.subplots(1, 3, figsize=(7.0, 2.9), width_ratios=[1.9, 1, 1], layout="constrained")
    propagation_panel(axes[0], df)
    floor_panel(axes[1], df)
    taint_panel(axes[2], df)
    style.save(fig, out)

    fig, axes = plt.subplots(1, 4, figsize=(7.0, 2.1), layout="constrained")
    baseline_panel(axes[0], df, "utility", "(a) Utility after a fault", "pass rate", 1.15, "{:.2f}")
    baseline_panel(axes[1], df, "llm_calls", "(b) Cost", "LLM calls per run", 30, "{:.1f}", ci=False)
    baseline_panel(axes[2], df, "irreversible_actions", "(c) Side effects", "irreversible actions per run", 1.0, "{:.2f}")
    baseline_panel(axes[3], df, "unauthorized_actions", "(d) Unauthorized", "unauthorized actions per run", 0.1, "{:.2f}", ci=False)
    style.save(fig, out.with_name(out.stem + "_baselines" + out.suffix))


if __name__ == "__main__":
    main(Path(sys.argv[1]), Path(sys.argv[2]))
