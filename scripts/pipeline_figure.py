"""Hand-placed diagram: the fan-out pipeline with declared provenance, one faulted run and its twin from a
shared checkpoint, the judge, and the recovery baselines.

Usage: python scripts/pipeline_figure.py docs/pipeline.png
Writes docs/pipeline.png and docs/pipeline.pdf.
"""

import sys
from pathlib import Path

from scripts import figure_style as style

style.apply()
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch  # noqa: E402

AGENT, ARTIFACT, FAULT, TWIN, MEASURE, RECOVER, CHECKPOINT = "#dce9f9", "#ffffff", "#fde0d3", "#eeeeeb", "#e3f3ec", "#fff3cf", "#f4f4f1"
EDGE = "#6b6a66"


def box(ax, x, y, w, h, text, color, fontsize=5.8, weight="normal", edge=EDGE):
    ax.add_patch(FancyBboxPatch((x - w / 2, y - h / 2), w, h, boxstyle="round,pad=0.01,rounding_size=0.08",
                                facecolor=color, edgecolor=edge, linewidth=0.7))
    ax.text(x, y, text, ha="center", va="center", fontsize=fontsize, linespacing=1.3, fontweight=weight, color=style.INK)


def arrow(ax, a, b, color=EDGE, lw=0.9, rad=0.0, text="", text_dy=0.1, fontsize=5.8, ls="-"):
    ax.add_patch(FancyArrowPatch(a, b, arrowstyle="-|>", mutation_scale=8, color=color, linewidth=lw, linestyle=ls,
                                 connectionstyle=f"arc3,rad={rad}", shrinkA=1.5, shrinkB=1.5))
    if text:
        ax.text((a[0] + b[0]) / 2, (a[1] + b[1]) / 2 + text_dy, text, ha="center", va="bottom", fontsize=fontsize, color=style.MUTED)


def stack(ax, x, y, labels, w=0.62, h=0.26, gap=0.06):
    """Small artifact boxes stacked vertically, centred on (x, y); returns their centre points top to bottom."""
    total = len(labels) * h + (len(labels) - 1) * gap
    centres = []
    for i, label in enumerate(labels):
        cy = y + total / 2 - h / 2 - i * (h + gap)
        box(ax, x, cy, w, h, label, ARTIFACT, fontsize=5.6)
        centres.append((x, cy))
    return centres


def lane_label(ax, x, y, text):
    ax.text(x, y, text, ha="left", va="center", fontsize=6.5, fontweight="bold", color=style.INK)


def main(out: Path) -> None:
    fig, ax = plt.subplots(figsize=(7.0, 4.0))
    ax.set_xlim(0, 11.2)
    ax.set_ylim(0, 6.3)
    ax.axis("off")

    # Row 1: the pipeline; citations are written inside each artifact node.
    y = 5.0
    lane_label(ax, 0.1, 5.95, "Pipeline")
    ax.add_patch(FancyBboxPatch((1.4, 5.55), 9.55, 0.3, boxstyle="round,pad=0.01,rounding_size=0.08", facecolor=CHECKPOINT, edgecolor="none"))
    ax.text(6.2, 5.7, "AgentDojo workspace environment (inbox, calendar, drive): the Researcher reads it, the Executor reads and writes it, the checker scores its final state",
            ha="center", va="center", fontsize=5.4, color=style.MUTED)
    box(ax, 0.65, y, 0.9, 0.55, "task\nprompt", ARTIFACT)
    box(ax, 2.075, y, 1.35, 0.6, "Researcher\nread-only tools", AGENT, weight="bold")
    stack(ax, 3.45, y, ["f1", "f2", "f3"], w=0.8)
    box(ax, 4.825, y, 1.35, 0.6, "Planner\ncites findings", AGENT, weight="bold")
    stack(ax, 6.3, y, ["p1 ← f1, f2", "p2 ← f3"], w=1.0)
    box(ax, 7.775, y, 1.35, 0.6, "Executor\none call per step", AGENT, weight="bold")
    stack(ax, 9.25, y, ["e1 ← p1", "e2 ← p2"], w=1.0)
    box(ax, 10.5, y, 0.9, 0.55, "checker\nutility", CHECKPOINT)
    for a, b in ((1.1, 1.4), (2.75, 3.05), (3.85, 4.15), (5.5, 5.8), (6.8, 7.1), (8.45, 8.75), (9.75, 10.05)):
        arrow(ax, (a, y), (b, y))
    ax.text(6.3, 4.35, "declared provenance: each plan step records the finding ids it cites, each executed step its plan step",
            ha="center", va="center", fontsize=5.6, color=style.BLUE)

    # Row 2: one faulted run and its twin from the same checkpoint.
    lane_label(ax, 0.1, 3.8, "One run: fault, twin, judge")
    box(ax, 1.35, 2.6, 2.5, 0.8, "checkpoint before the fault\nenvironment snapshot\n+ clean artifacts so far", CHECKPOINT)
    yf, yt = 3.2, 2.0
    box(ax, 4.0, yf, 2.2, 0.62, "fault injected into f2\none of 12 frozen templates", FAULT, weight="bold")
    box(ax, 4.0, yt, 2.2, 0.62, "twin: f2 left intact", TWIN, weight="bold")
    arrow(ax, (2.6, 2.75), (2.9, yf), rad=-0.2)
    arrow(ax, (2.6, 2.45), (2.9, yt), rad=0.2)
    box(ax, 6.5, yf, 2.2, 0.62, "Planner and Executor continue\n→ p1′, p2′, e1′, e2′", ARTIFACT)
    box(ax, 6.5, yt, 2.2, 0.62, "Planner and Executor continue\n→ p1, p2, e1, e2", ARTIFACT)
    arrow(ax, (5.1, yf), (5.4, yf))
    arrow(ax, (5.1, yt), (5.4, yt))
    box(ax, 8.4, 2.6, 1.5, 0.9, "LLM judge\nper matched pair:\nwould a downstream\nagent act the same?", MEASURE, weight="bold")
    arrow(ax, (7.6, yf), (7.65, 2.8), rad=0.1)
    arrow(ax, (7.6, yt), (7.65, 2.4), rad=-0.1)
    box(ax, 10.35, 2.6, 1.6, 0.9, "changed artifacts vs.\ndeclared descendants\n→ under-taint,\nover-taint, ignored", MEASURE)
    arrow(ax, (9.15, 2.6), (9.55, 2.6))

    # Row 3: recovery baselines.
    lane_label(ax, 0.1, 1.25, "Recovery baselines")
    box(ax, 1.35, 0.55, 2.5, 0.75, "oracle reveals the fault\nPhase 1: at the end of the run\nPhase 2: Δ steps after injection", CHECKPOINT)
    box(ax, 5.0, 0.55, 4.2, 0.75,
        "restart_scratch   roll back the environment, rerun everything\n"
        "restart_stage      roll back to the checkpoint, rerun from that stage\n"
        "always_verify      verifier call before every hand-off, no oracle", RECOVER, fontsize=5.4)
    arrow(ax, (2.6, 0.55), (2.9, 0.55))
    box(ax, 9.2, 0.55, 3.8, 0.75,
        "the rerun is scored by the checker, but the first attempt's\nirreversible actions already happened: side effects are\ncounted from the tool-action log, not from utility", TWIN, fontsize=5.3)
    arrow(ax, (7.1, 0.55), (7.3, 0.55))

    fig.subplots_adjust(left=0.01, right=0.99, top=0.99, bottom=0.01)
    style.save(fig, out)


if __name__ == "__main__":
    main(Path(sys.argv[1]))
