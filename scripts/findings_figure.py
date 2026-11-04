"""One four-panel figure of the Phase 1 findings for the README.

Usage: python scripts/findings_figure.py runs/phase1_flash/aggregate.parquet docs/findings.png
"""

import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402

from scripts.plots import _bar_with_ci, baseline_groups  # noqa: E402

CONDITIONS = ["none", "restart_stage", "restart_scratch", "always_verify"]


def propagation_panel(ax, df: pd.DataFrame) -> None:
    faulted = df[(df["condition"] == "none") & df["judged_ignored"].notna()]
    groups = {fid.replace("plan_step_", "plan step\n").replace("finding_", "finding\n"): (~g["judged_ignored"].astype(bool)).astype(float).tolist()
              for fid, g in faulted.groupby("fault_id")}
    _bar_with_ci(ax, groups, "Propagation rate by fault template (judged)", "fraction of faults")
    ax.tick_params(axis="x", labelsize=7)


def taint_panel(ax, df: pd.DataFrame) -> None:
    faulted = df[(df["condition"] == "none") & df["judged_under_taint"].notna()]
    stage = faulted["fault_id"].str.split("_").str[0]
    labels, width = ["finding", "plan"], 0.38
    for offset, metric, label in ((-width / 2, "judged_under_taint", "under-taint"), (width / 2, "judged_over_taint", "over-taint")):
        means = [faulted.loc[stage == s, metric].mean() for s in labels]
        ax.bar([i + offset for i in range(2)], means, width, label=label)
    ax.set_xticks(range(2), ["finding fault", "plan-step fault"])
    ax.set_ylabel("artifacts per run")
    ax.set_title("Citation taint vs counterfactual change (judged)")
    ax.legend(frameon=False)


def baselines_panel(ax, df: pd.DataFrame) -> None:
    utility = baseline_groups(df, "utility")
    calls = baseline_groups(df, "llm_calls")
    irreversible = baseline_groups(df, "irreversible_actions")
    x = range(len(CONDITIONS))
    ax.bar([i - 0.2 for i in x], [sum(utility[c]) / len(utility[c]) for c in CONDITIONS], 0.4, label="utility")
    ax.bar([i + 0.2 for i in x], [sum(irreversible[c]) / len(irreversible[c]) for c in CONDITIONS], 0.4, label="irreversible actions / run")
    ax.set_xticks(list(x), CONDITIONS, rotation=20, ha="right")
    ax.set_ylim(0, 1.25)
    ax.set_title("Baselines after an applied fault")
    ax.legend(frameon=False, loc="upper left")
    twin = ax.twinx()
    twin.plot(list(x), [sum(calls[c]) / len(calls[c]) for c in CONDITIONS], "ko-", label="LLM calls / run")
    twin.set_ylabel("LLM calls per run")
    twin.set_ylim(0, 37)
    twin.legend(frameon=False, loc="upper right")


def floor_panel(ax, df: pd.DataFrame) -> None:
    clean = df[df["fault_id"].isna() & (df["condition"] == "none")].groupby("task_id").first()
    kinds = ["findings", "plan_steps", "executed_steps"]
    judged = [clean[f"floor_judged_{k}"].mean() for k in kinds]
    exact = [clean[f"floor_{k}"].mean() for k in kinds]
    ax.bar([i - 0.2 for i in range(3)], exact, 0.4, label="exact text diff", color="#bbbbbb")
    ax.bar([i + 0.2 for i in range(3)], judged, 0.4, label="LLM judge")
    ax.set_xticks(range(3), [k.replace("_", " ") for k in kinds])
    ax.set_ylabel("fraction differing")
    ax.set_title("Clean-vs-clean noise floor (mean over 20 tasks)")
    ax.legend(frameon=False)


def main(parquet: Path, out: Path) -> None:
    df = pd.read_parquet(parquet)
    fig, axes = plt.subplots(2, 2, figsize=(13, 8.5))
    propagation_panel(axes[0, 0], df)
    floor_panel(axes[0, 1], df)
    taint_panel(axes[1, 0], df)
    baselines_panel(axes[1, 1], df)
    fig.tight_layout()
    fig.savefig(out, dpi=160)


if __name__ == "__main__":
    main(Path(sys.argv[1]), Path(sys.argv[2]))
