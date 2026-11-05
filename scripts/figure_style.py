"""Shared matplotlib style for the paper and README figures.

Colours are the first categorical slots of a palette validated for colour-vision deficiency
(adjacent-pair OKLab dE >= 8); series keep a fixed colour across every figure.
"""

import matplotlib
import matplotlib.pyplot as plt

BLUE, ORANGE, AQUA = "#2a78d6", "#eb6834", "#1baf7a"
GRAY, INK, MUTED, GRID = "#b5b4ae", "#1c1c1a", "#52514e", "#e6e5e1"
FAULT_TYPE_COLOR = {"accidental": BLUE, "adversarial": ORANGE, "other": AQUA}


def apply() -> None:
    matplotlib.use("Agg")
    plt.rcParams.update({
        "font.size": 7, "axes.titlesize": 7.5, "axes.labelsize": 7, "xtick.labelsize": 6.5, "ytick.labelsize": 6.5,
        "legend.fontsize": 6.5, "axes.titleweight": "bold", "axes.titlelocation": "left",
        "axes.spines.top": False, "axes.spines.right": False, "axes.edgecolor": GRAY, "axes.linewidth": 0.6,
        "xtick.color": MUTED, "ytick.color": MUTED, "xtick.major.width": 0.6, "ytick.major.width": 0.6,
        "text.color": INK, "axes.labelcolor": MUTED, "axes.titlecolor": INK,
        "axes.grid": True, "axes.grid.axis": "y", "grid.color": GRID, "grid.linewidth": 0.5, "axes.axisbelow": True,
        "legend.frameon": False, "legend.handlelength": 1.0, "legend.handleheight": 0.8,
        "savefig.dpi": 220, "pdf.fonttype": 42,
    })


def save(fig, out) -> None:
    """Write the PNG the README embeds and a vector PDF next to it for the paper."""
    fig.savefig(out)
    fig.savefig(str(out).rsplit(".", 1)[0] + ".pdf")
