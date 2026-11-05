"""LaTeX tables of the Phase 1 findings from an aggregate parquet, one .tex file per table.

Usage: python scripts/latex_tables.py runs/phase1_flash/aggregate.parquet docs/tables
Each table is a pandas DataFrame; `render` wraps `DataFrame.to_latex` in a table environment
with booktabs rules. Brackets are 95% percentile-bootstrap intervals on the mean.
"""

import sys
from pathlib import Path

import pandas as pd

from mar.metrics import bootstrap_ci

STAGE = {"finding": "finding", "plan": "plan step"}
CONDITIONS = ["none", "restart_stage", "restart_scratch", "always_verify"]


def mean_ci(values, digits: int = 2) -> str:
    values = [float(v) for v in values]
    lo, hi = bootstrap_ci(values)
    return f"{sum(values) / len(values):.{digits}f} [{lo:.{digits}f}, {hi:.{digits}f}]"


def _faulted(df: pd.DataFrame) -> pd.DataFrame:
    faulted = df[(df["condition"] == "none") & df["fault_id"].notna() & df["judged_ignored"].notna()].copy()
    faulted["stage"] = faulted["fault_id"].str.split("_").str[0].map(STAGE)
    faulted["propagated"] = 1 - faulted["judged_ignored"].astype(float)
    return faulted


def propagation_table(df: pd.DataFrame) -> pd.DataFrame:
    rows = {}
    for fault_id, g in _faulted(df).groupby("fault_id"):
        rows[fault_id] = {"n": len(g), "propagated": mean_ci(g["propagated"]),
                          "downstream artifacts changed": mean_ci(g["judged_counterfactual_changed"]),
                          "utility": f"{g['utility'].mean():.2f}"}
    return pd.DataFrame.from_dict(rows, orient="index").rename_axis("fault")


def taint_table(df: pd.DataFrame) -> pd.DataFrame:
    """Metrics as rows and the two fault stages as columns, so the table fits a text column."""
    columns = {}
    for stage, g in _faulted(df).groupby("stage"):
        columns[stage + " fault"] = {
            "applied faults": len(g),
            "ignored (no downstream change)": f"{g['judged_ignored'].mean():.2f}",
            "under-taint, artifacts per run": mean_ci(g["judged_under_taint"]),
            "over-taint, artifacts per run": mean_ci(g["judged_over_taint"]),
            "runs with any under-taint": f"{(g['judged_under_taint'] > 0).mean():.2f}",
            "runs with any over-taint": f"{(g['judged_over_taint'] > 0).mean():.2f}",
            "declared descendants unchanged": f"{g['judged_over_taint'].sum() / g['declared_descendants'].sum():.2f}",
            "changed artifacts not declared": f"{g['judged_under_taint'].sum() / g['judged_counterfactual_changed'].sum():.2f}",
        }
    return pd.DataFrame(columns).rename_axis("metric")


def noise_floor_table(df: pd.DataFrame) -> pd.DataFrame:
    clean = df[df["fault_id"].isna() & (df["condition"] == "none")].groupby("task_id").first()
    rows = {}
    for kind in ("findings", "plan_steps", "executed_steps"):
        judged, exact = clean[f"floor_judged_{kind}"], clean[f"floor_{kind}"]
        rows[kind.replace("_", " ")] = {"judged mean": f"{judged.mean():.2f}", "judged median": f"{judged.median():.2f}",
                                        "tasks at 0": int((judged == 0).sum()), "tasks at 1": int((judged == 1).sum()),
                                        "exact mean": f"{exact.mean():.2f}"}
    return pd.DataFrame.from_dict(rows, orient="index").rename_axis("artifact kind")


def baselines_table(df: pd.DataFrame) -> pd.DataFrame:
    landed = df[df["fault_applied"] == True]  # noqa: E712 -- boolean column with NaNs
    clean_utility = df[df["fault_id"].isna()].groupby("condition")["utility"].mean()
    rows = {}
    for condition in CONDITIONS:
        g = landed[landed["condition"] == condition]
        if g.empty:
            continue
        rows[condition] = {"n": len(g), "utility": mean_ci(g["utility"]), "clean utility": f"{clean_utility[condition]:.2f}",
                           "LLM calls": f"{g['llm_calls'].mean():.1f}", "completion tokens": f"{g['completion_tokens'].mean():.0f}",
                           "seconds": f"{g['seconds'].mean():.0f}", "irreversible actions": mean_ci(g["irreversible_actions"]),
                           "unauthorized actions": f"{g['unauthorized_actions'].mean():.2f}",
                           "discarded artifacts": f"{g['discarded_artifacts'].mean():.1f}",
                           "recovery calls": f"{g['recovery_llm_calls'].mean():.1f}"}
    return pd.DataFrame.from_dict(rows, orient="index").rename_axis("condition")


def utility_by_outcome_table(df: pd.DataFrame) -> pd.DataFrame:
    faulted = _faulted(df)
    outcome = faulted["judged_ignored"].map({True: "ignored", False: "propagated"})
    rows = {k: {"n": len(g), "utility": mean_ci(g["utility"])} for k, g in faulted.groupby(outcome)}
    return pd.DataFrame.from_dict(rows, orient="index").rename_axis("fault outcome")


def adversarial_table(df: pd.DataFrame) -> pd.DataFrame:
    adversarial = df[df["fault_id"].fillna("").str.contains("adversarial") & (df["fault_applied"] == True)].copy()  # noqa: E712
    adversarial["stage"] = adversarial["fault_id"].str.split("_").str[0].map(STAGE)
    rows = []
    for condition in CONDITIONS:
        for stage, g in adversarial[adversarial["condition"] == condition].groupby("stage"):
            rows.append({"condition": condition, "stage": stage, "n": len(g),
                         "runs with unauthorized action": f"{(g['unauthorized_actions'] > 0).mean():.2f}",
                         "unauthorized actions per run": f"{g['unauthorized_actions'].mean():.2f}",
                         "utility": f"{g['utility'].mean():.2f}"})
    return pd.DataFrame(rows).set_index(["condition", "stage"])


TABLES = {
    "propagation": (propagation_table, "Propagation by fault template, condition none, judged."),
    "taint": (taint_table, "Declared descendants of the fault vs.\\ artifacts the judge marks as changed against the twin. Under-taint: changed but not a declared descendant; over-taint: declared descendant but unchanged. The last two rows are over-taint as a fraction of all declared descendants and under-taint as a fraction of all changed artifacts."),
    "noise_floor": (noise_floor_table, "Clean-vs-clean noise floor per artifact kind, 20 tasks."),
    "baselines": (baselines_table, "Restart baselines over runs whose fault applied."),
    "utility_by_outcome": (utility_by_outcome_table, "Utility conditional on whether the fault propagated."),
    "adversarial": (adversarial_table, "Adversarial faults: unauthorized actions by condition and stage."),
}


def render(table: pd.DataFrame, caption: str, label: str) -> str:
    # reset_index puts the index name in the header row instead of to_latex's second header line
    body = table.reset_index().to_latex(index=False, escape=True, column_format="l" * table.index.nlevels + "r" * len(table.columns))
    return "\\begin{table}[t]\n\\centering\n\\small\n" + body + f"\\caption{{{caption}}}\n\\label{{{label}}}\n\\end{{table}}\n"


def main(parquet: Path, out_dir: Path) -> None:
    df = pd.read_parquet(parquet)
    out_dir.mkdir(parents=True, exist_ok=True)
    for name, (build, caption) in TABLES.items():
        (out_dir / f"{name}.tex").write_text(render(build(df), caption, f"tab:{name}"))
    print(f"wrote {len(TABLES)} tables to {out_dir}")


if __name__ == "__main__":
    main(Path(sys.argv[1]), Path(sys.argv[2]))
