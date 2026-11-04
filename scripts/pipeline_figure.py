"""Hand-placed diagram of the fan-out pipeline, fault injection, twins, judge and recovery.

Usage: python scripts/pipeline_figure.py docs/pipeline.png
"""

import sys

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch  # noqa: E402

AGENT, ARTIFACT, FAULT, CHECK, MEASURE, RECOVER = "#dbe9ff", "#ffffff", "#ffd6d6", "#fff3c4", "#e9ddff", "#e3f4e3"


def box(ax, x, y, w, h, text, color, fontsize=9, style="round,pad=0.02,rounding_size=0.15", lw=1.0):
    ax.add_patch(FancyBboxPatch((x - w / 2, y - h / 2), w, h, boxstyle=style, facecolor=color, edgecolor="#444444", linewidth=lw))
    ax.text(x, y, text, ha="center", va="center", fontsize=fontsize, linespacing=1.25)


def arrow(ax, a, b, style="-", color="#444444", text="", lw=1.2, rad=0.0):
    ax.add_patch(FancyArrowPatch(a, b, arrowstyle="-|>", mutation_scale=11, linestyle=style, color=color, linewidth=lw,
                                 connectionstyle=f"arc3,rad={rad}", shrinkA=2, shrinkB=2))
    if text:
        ax.text((a[0] + b[0]) / 2, (a[1] + b[1]) / 2 + 0.22, text, ha="center", va="bottom", fontsize=7.5, color="#333333")


def main(out: str) -> None:
    fig, ax = plt.subplots(figsize=(14, 7.2))
    ax.set_xlim(0, 14)
    ax.set_ylim(0, 7.2)
    ax.axis("off")

    y = 5.9
    xs = {"prompt": 0.9, "researcher": 2.6, "findings": 4.35, "planner": 6.0, "plan": 7.7, "executor": 9.4, "executed": 11.1}
    box(ax, xs["prompt"], y, 1.2, 0.7, "task\nprompt", ARTIFACT)
    box(ax, xs["researcher"], y, 1.5, 0.8, "Researcher\nread-only tools", AGENT)
    box(ax, xs["findings"], y, 1.4, 0.8, "findings\nf0 .. fn", ARTIFACT)
    box(ax, xs["planner"], y, 1.5, 0.8, "Planner\ncites findings", AGENT)
    box(ax, xs["plan"], y, 1.4, 0.8, "plan steps\np0 .. pm", ARTIFACT)
    box(ax, xs["executor"], y, 1.5, 0.8, "Executor\none per step, tools", AGENT)
    box(ax, xs["executed"], y, 1.5, 0.8, "executed steps\nexec:p0 .. exec:pm", ARTIFACT)
    for a, b in zip(list(xs.values())[:-1], list(xs.values())[1:]):
        arrow(ax, (a + 0.7, y), (b - 0.7, y))

    box(ax, 13.0, y, 1.3, 0.8, "AgentDojo checker\nutility = final\nstate only", CHECK, fontsize=8)
    arrow(ax, (xs["executed"] + 0.75, y), (12.35, y))
    ax.text(7.0, 6.75, "AgentDojo workspace environment: inbox, calendar, drive. Researcher reads; Executor reads and writes (send_email, create_event ...)",
            ha="center", fontsize=8.5, color="#333333", style="italic")

    y2 = 4.35
    for stage, x in (("findings", xs["findings"]), ("plan", xs["plan"])):
        box(ax, x, y2 + 0.35, 1.9, 0.6, "checkpoint: env snapshot\n+ clean artifacts so far", CHECK, fontsize=7.5)
        arrow(ax, (x, y - 0.4), (x, y2 + 0.63), style="--")
    box(ax, xs["findings"] + 0.85, y2 - 0.55, 2.6, 0.75,
        "fault: one finding\naccidental wrong date / amount, adversarial\ninjected instruction, other stale or timeout", FAULT, fontsize=7.5)
    box(ax, xs["plan"] + 0.85, y2 - 0.55, 2.6, 0.75,
        "fault: one plan step\naccidental wrong parameter, adversarial\ninjected step, other stale plan", FAULT, fontsize=7.5)
    arrow(ax, (xs["findings"] + 0.3, y2 + 0.08), (xs["findings"] + 0.5, y2 - 0.17), style="--")
    arrow(ax, (xs["plan"] + 0.3, y2 + 0.08), (xs["plan"] + 0.5, y2 - 0.17), style="--")
    arrow(ax, (xs["findings"] + 1.6, y2 - 0.17), (xs["planner"], y - 0.4), style="--", color="#b03030", text="faulted findings")
    arrow(ax, (xs["plan"] + 1.6, y2 - 0.17), (xs["executor"], y - 0.4), style="--", color="#b03030", text="faulted plan")
    ax.text(0.3, y2 + 0.35, "fault schedule:\none fault per run,\nat a stage boundary,\nfrozen templates,\nseeded position", fontsize=7.5, va="center", color="#333333")

    y3 = 2.45
    box(ax, 2.6, y3, 2.6, 0.9, "twin run\nforked from the same checkpoint,\nno fault, same prompt", "#eeeeee", fontsize=8)
    arrow(ax, (xs["findings"] - 0.95, y2 + 0.35), (2.6, y3 + 0.47), style="--", color="#777777", rad=0.25)
    arrow(ax, (xs["plan"] - 0.95, y2 + 0.2), (3.9, y3 + 0.3), style="--", color="#777777", rad=-0.35)
    box(ax, 6.4, y3, 3.0, 0.9, "LLM judge\nfaulted artifact vs twin artifact at the same\nposition: same actions downstream?", MEASURE, fontsize=8)
    arrow(ax, (3.9, y3), (4.9, y3))
    arrow(ax, (xs["executed"] + 0.3, y - 0.4), (7.6, y3 + 0.47), style="--", color="#777777", rad=0.15)
    box(ax, 11.3, y3, 3.6, 0.9, "counterfactually changed set\nvs declared descendants (citations)\n→ under-taint, over-taint, ignored", MEASURE, fontsize=8)
    arrow(ax, (7.9, y3), (9.5, y3))
    ax.text(0.3, y3, "measurement\n(offline, cached)", fontsize=7.5, va="center", color="#333333")

    y4 = 0.85
    box(ax, 2.6, y4, 2.6, 0.9, "oracle reveals the fault\nPhase 1: at the end of the run\nPhase 2: Δ steps after injection", CHECK, fontsize=8)
    box(ax, 7.6, y4, 5.8, 0.9,
        "restart_scratch: roll the environment back, rerun everything\nrestart_stage: roll back to the checkpoint, rerun from the faulted stage\nalways_verify: verifier LLM call before every hand-off, no oracle",
        RECOVER, fontsize=8)
    arrow(ax, (3.9, y4), (4.7, y4))
    arrow(ax, (10.5, y4), (13.6, y4), text="rerun → checker; side effects\nof the first attempt remain")
    ax.text(0.3, y4, "recovery\nbaselines", fontsize=7.5, va="center", color="#333333")

    ax.text(7.0, 0.12, "Every run writes manifest, events (LLM calls, tool actions, fault, recovery), artifacts and provenance to runs/<run_id>/.",
            ha="center", fontsize=7.5, color="#555555")
    fig.tight_layout()
    fig.savefig(out, dpi=200)


if __name__ == "__main__":
    main(sys.argv[1])
