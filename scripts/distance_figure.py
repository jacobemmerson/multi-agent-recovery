"""Does a fault's effect fade down the pipeline? Judged change rate of downstream artifacts by pipeline hop from
the faulted artifact, split by whether a citation path exists, against the clean-vs-clean floor; plus whether a
change at the plan step persists into its executed step.

Usage: python scripts/distance_figure.py runs/phase1_flash docs/distance.png
Reads judge.json and provenance.json of every faulted `none` run; writes docs/distance.png, docs/distance.pdf and
docs/tables/distance.{tex,md}.
"""

import json
import sys
from collections import defaultdict
from pathlib import Path

import pandas as pd

from mar.judge import STAGE_ORDER
from mar.metrics import bootstrap_ci
from scripts import figure_style as style

style.apply()
import matplotlib.pyplot as plt  # noqa: E402

KIND_LABEL = {"plan_step": "plan steps", "executed_step": "executed steps"}


def citation_distance(artifacts: dict, start: str) -> dict[str, int]:
    children = defaultdict(set)
    for artifact in artifacts.values():
        for cited in artifact["cites"]:
            children[cited].add(artifact["id"])
    distance, frontier = {start: 0}, [start]
    while frontier:
        node = frontier.pop(0)
        for child in children[node]:
            if child not in distance:
                distance[child] = distance[node] + 1
                frontier.append(child)
    return distance


def downstream_artifacts(runs_dir: Path) -> pd.DataFrame:
    """One row per artifact strictly downstream of the fault in a faulted `none` run. An artifact with no twin at the
    same position counts as changed, as it does in the noise floor and the taint metrics."""
    rows = []
    for directory in sorted(runs_dir.glob("*-none-*")):
        if directory.name.endswith("-twin") or not (directory / "judge.json").exists():
            continue
        manifest = json.loads((directory / "manifest.json").read_text())
        result = json.loads((directory / "result.json").read_text())
        if manifest["fault_id"] is None or not result.get("fault_applied"):
            continue
        artifacts = json.loads((directory / "provenance.json").read_text())["artifacts"]
        twin = json.loads((runs_dir / (directory.name + "-twin") / "provenance.json").read_text())["artifacts"]
        verdicts = json.loads((directory / "judge.json").read_text())
        fault = result["fault_artifact_id"]
        fault_stage = STAGE_ORDER[artifacts[fault]["kind"]]
        distance = citation_distance(artifacts, fault)

        def changed(artifact_id: str) -> bool:
            """Same rule as the noise floor and the taint metrics: no twin at this position counts as changed."""
            if artifact_id not in twin:
                return True
            if artifact_id in verdicts:
                return bool(verdicts[artifact_id]["differs"])
            return artifacts[artifact_id]["content"] != twin[artifact_id]["content"]

        for artifact_id, artifact in artifacts.items():
            if artifact_id == fault or STAGE_ORDER[artifact["kind"]] <= fault_stage:
                continue
            plan_step = artifact["cites"][0] if artifact["kind"] == "executed_step" else None
            rows.append({
                "run": directory.name, "fault_stage": manifest["fault_id"].split("_")[0], "kind": artifact["kind"],
                "hops": STAGE_ORDER[artifact["kind"]] - fault_stage, "cited": artifact_id in distance,
                "changed": changed(artifact_id), "unmatched": artifact_id not in twin,
                "plan_step_changed": changed(plan_step) if plan_step in artifacts else None,
            })
    return pd.DataFrame(rows)


def judged_floor(runs_dir: Path) -> dict[str, float]:
    aggregate = pd.read_parquet(runs_dir / "aggregate.parquet")
    clean = aggregate[aggregate["fault_id"].isna() & (aggregate["condition"] == "none")].groupby("task_id").first()
    return {"plan_step": clean["floor_judged_plan_steps"].mean(), "executed_step": clean["floor_judged_executed_steps"].mean()}


def mean_ci(values):
    values = [float(v) for v in values]
    mean = sum(values) / len(values)
    lo, hi = bootstrap_ci(values)
    return mean, mean - lo, hi - mean


def rate_bars(ax, groups: list[tuple[str, pd.DataFrame]], floors: list[float] | None, title: str) -> None:
    """Per group, a cited and an uncited bar of the judged change rate with intervals, and the floor as a gray tick."""
    width = 0.34
    for j, (cited, label, color) in enumerate(((True, "citation path from the fault", style.BLUE), (False, "no citation path", style.ORANGE))):
        xs, means, los, his = [], [], [], []
        for i, (_, g) in enumerate(groups):
            sub = g[g["cited"] == cited]
            if sub.empty:
                continue
            m, lo, hi = mean_ci(sub["changed"])
            xs.append(i + (j - 0.5) * (width + 0.03))
            means.append(m)
            los.append(lo)
            his.append(hi)
            ax.text(xs[-1], 0.02, f"n={len(sub)}", ha="center", va="bottom", fontsize=5, color="white")
        ax.bar(xs, means, width, color=color, label=label, zorder=3)
        ax.errorbar(xs, means, yerr=(los, his), fmt="none", ecolor=style.INK, elinewidth=0.8, capsize=0, zorder=4)
    if floors is not None:
        for i, floor in enumerate(floors):
            ax.hlines(floor, i - 0.42, i + 0.42, color=style.MUTED, linewidth=1.2, zorder=5,
                      label="clean-vs-clean floor" if i == 0 else None)
    ax.set_xticks(range(len(groups)), [label for label, _ in groups])
    ax.tick_params(axis="x", length=0)
    ax.set_ylim(0, 1)
    ax.set_title(title)


def distance_table(df: pd.DataFrame, floor: dict[str, float]) -> pd.DataFrame:
    """Judged change rate by hop from the fault, split by citation path, with the clean-vs-clean floor; plus,
    for finding faults, the executed-step rate conditional on whether its plan step changed."""
    def cell(sub):
        if sub.empty:
            return "", ""
        m, lo, hi = mean_ci(sub["changed"])
        return f"{m:.2f} [{m - lo:.2f}, {m + hi:.2f}]", str(len(sub))
    rows = []
    def add(fault, artifacts, g, kind):
        cited, n_cited = cell(g[g["cited"]])
        uncited, n_uncited = cell(g[~g["cited"]])
        rows.append({"fault": fault, "artifacts": artifacts, "cited": cited, "n": n_cited, "uncited": uncited, "n ": n_uncited, "floor": f"{floor[kind]:.2f}"})
    for stage, kind, hops in (("finding", "plan_step", 1), ("finding", "executed_step", 2), ("plan", "executed_step", 1)):
        add("finding" if stage == "finding" else "plan step", f"{KIND_LABEL[kind]}, {hops} hop{'s' if hops > 1 else ''}",
            df[(df["fault_stage"] == stage) & (df["kind"] == kind)], kind)
    executed = df[(df["fault_stage"] == "finding") & (df["kind"] == "executed_step") & df["plan_step_changed"].notna()]
    add("finding", "executed steps, plan step changed", executed[executed["plan_step_changed"] == True], "executed_step")  # noqa: E712
    add("finding", "executed steps, plan step unchanged", executed[executed["plan_step_changed"] == False], "executed_step")  # noqa: E712
    return pd.DataFrame(rows)


def write_table(table: pd.DataFrame, out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    header = "| " + " | ".join(table.columns) + " |\n|" + "---|" * len(table.columns) + "\n"
    rows = "".join("| " + " | ".join(str(v) for v in row) + " |\n" for row in table.itertuples(index=False))
    (out_dir / "distance.md").write_text(header + rows)
    body = table.to_latex(index=False, escape=True, column_format="llrrrrr")
    (out_dir / "distance.tex").write_text(
        "\\begin{table}[t]\n\\centering\n\\small\n" + body
        + "\\caption{Judged change rate of downstream artifacts by pipeline hop from the faulted artifact, split by whether a "
          "citation path from the fault exists (cited / uncited, with counts), and the clean-vs-clean floor for that artifact kind. An artifact with no twin at the "
          "same position counts as changed, as in the floor. Brackets are 95\\% bootstrap intervals. The last two rows condition a "
          "finding fault's executed steps on whether their plan step changed.}\n"
          "\\label{tab:distance}\n\\end{table}\n")


def main(runs_dir: Path, out: Path) -> None:
    df = downstream_artifacts(runs_dir)
    floor = judged_floor(runs_dir)
    write_table(distance_table(df, floor), out.parent / "tables")
    fig, axes = plt.subplots(1, 3, figsize=(7.0, 2.5), layout="constrained")

    finding = df[df["fault_stage"] == "finding"]
    rate_bars(axes[0], [("plan steps\n(1 hop)", finding[finding["kind"] == "plan_step"]),
                        ("executed steps\n(2 hops)", finding[finding["kind"] == "executed_step"])],
              [floor["plan_step"], floor["executed_step"]], "(a) Finding faults")
    axes[0].set_ylabel("fraction judged changed vs. twin")

    plan = df[df["fault_stage"] == "plan"]
    rate_bars(axes[1], [("executed steps\n(1 hop)", plan[plan["kind"] == "executed_step"])],
              [floor["executed_step"]], "(b) Plan-step faults")
    axes[1].set_xlim(-0.8, 0.8)
    axes[1].legend(loc="upper right", fontsize=5.8)

    executed = finding[(finding["kind"] == "executed_step") & finding["plan_step_changed"].notna()]
    rate_bars(axes[2], [("plan step\nchanged", executed[executed["plan_step_changed"] == True]),  # noqa: E712
                        ("plan step\nunchanged", executed[executed["plan_step_changed"] == False])],  # noqa: E712
              None, "(c) Finding faults, 2 hops:\nexecuted step given its plan step")
    axes[2].set_ylabel("fraction of executed steps changed")
    style.save(fig, out)


if __name__ == "__main__":
    main(Path(sys.argv[1]), Path(sys.argv[2]))
