"""Generate loudness analysis plots."""

import os

import numpy as np

os.environ.setdefault("MPLBACKEND", "Agg")
import matplotlib
import matplotlib.pyplot as plt
from matplotlib.gridspec import GridSpec

from analyze_loudness.analysis import SILENCE_THRESHOLD, compute_stats

# Use a CJK-capable font if available, fallback to sans-serif
for _font in ("Meiryo", "Yu Gothic", "Noto Sans CJK JP", "MS Gothic"):
    if _font in {f.name for f in matplotlib.font_manager.fontManager.ttflist}:
        matplotlib.rcParams["font.family"] = _font
        break


def _moving_avg(x: np.ndarray, w: int = 60) -> np.ndarray:
    kernel = np.ones(w) / w
    padded = np.pad(x, (w // 2, w // 2), mode="edge")
    return np.convolve(padded, kernel, mode="valid")[: len(x)]


def plot_analysis(
    t: np.ndarray,
    M: np.ndarray,
    S: np.ndarray,
    summary: dict,
    title: str,
    out_path: str,
) -> None:
    """Generate a 4-row loudness analysis figure and save as PNG.

    Layout:
        Row 0 (full width) : Numerical summary table
        Row 1 (full width) : Short-term loudness timeline with 60s moving average
        Row 2 left / right : Short-term / Momentary histograms
        Row 3 (full width) : 5-minute segment bar chart with P10-P90 error bars
    """
    # Downsample to ~3000 points for responsive plotting
    step = max(1, len(t) // 3000)
    td = t[::step] / 60
    Sd = S[::step]
    S_smooth = _moving_avg(Sd)

    intg = summary.get("integrated", np.nan)
    true_peak = summary.get("true_peak", float("nan"))
    lra = summary.get("lra", float("nan"))
    c = "#9C27B0"

    st = compute_stats(S, "Short-term")
    mo = compute_stats(M, "Momentary")
    silence_pct = np.sum(S < -40) / len(S) * 100

    fig = plt.figure(figsize=(16, 16))
    gs = GridSpec(
        4, 2, figure=fig,
        height_ratios=[0.6, 2, 1.2, 1.2],
        hspace=0.35, wspace=0.25,
    )
    fig.suptitle(
        f"Loudness Analysis: {title}\nBS.1770 / EBU R128",
        fontsize=15, fontweight="bold", y=0.98,
    )

    # ---- Row 0: Summary table ----
    ax_tbl = fig.add_subplot(gs[0, :])
    ax_tbl.axis("off")

    table_data = [
        [
            f"{t[-1] / 60:.1f} min ({len(t)} frames)",
            f"{intg:.1f} LUFS",
            f"{true_peak:+.1f} dBFS",
            f"{lra:.1f} LU",
        ],
        [
            f"{st['median']:.1f} LUFS",
            f"{st['p10']:.1f} / {st['p90']:.1f} LUFS",
            f"{mo['median']:.1f} LUFS",
            f"{mo['p10']:.1f} / {mo['p90']:.1f} LUFS",
        ],
    ]
    col_labels = [
        ["Duration", "Integrated", "True Peak (max)", "LRA"],
        ["S-term Median", "S-term P10/P90", "Mom. Median", "Mom. P10/P90"],
    ]

    tbl0 = ax_tbl.table(
        cellText=[table_data[0]],
        colLabels=col_labels[0],
        loc="upper center",
        cellLoc="center",
        bbox=[0.0, 0.52, 1.0, 0.48],
    )
    tbl1 = ax_tbl.table(
        cellText=[table_data[1]],
        colLabels=col_labels[1],
        loc="lower center",
        cellLoc="center",
        bbox=[0.0, 0.0, 1.0, 0.48],
    )

    for tbl in (tbl0, tbl1):
        tbl.auto_set_font_size(False)
        tbl.set_fontsize(10)
        for (row, col), cell in tbl.get_celld().items():
            cell.set_edgecolor("#CCCCCC")
            if row == 0:
                cell.set_facecolor("#E1BEE7")
                cell.set_text_props(fontweight="bold", fontsize=9)
            else:
                cell.set_facecolor("white")

    silence_text = f"Silence (S < -40 LUFS): {silence_pct:.1f}%"
    ax_tbl.text(
        1.0, -0.05, silence_text,
        transform=ax_tbl.transAxes,
        fontsize=9, ha="right", va="top", color="#666666",
    )

    # ---- Row 1: Short-term timeline ----
    ax0 = fig.add_subplot(gs[1, :])
    ax0.fill_between(td, Sd, -70, alpha=0.15, color=c)
    ax0.plot(td, Sd, color=c, alpha=0.25, linewidth=0.4)
    ax0.plot(td, S_smooth, color=c, linewidth=2, label="60s moving avg")
    ax0.axhline(intg, color=c, linestyle="-", alpha=0.7, linewidth=1.2,
                label=f"I: {intg:.1f} LUFS")
    ax0.axhline(-23, color="#4CAF50", linestyle="--", alpha=0.5, linewidth=1.2,
                label="Target \u221223 LUFS")
    ax0.axhline(-14, color="#F44336", linestyle=":", alpha=0.4, linewidth=1.2,
                label="\u221214 LUFS")
    ax0.set_ylabel("Short-term LUFS")
    ax0.set_xlabel("Time (min)")
    ax0.set_title("Short-term Loudness (3s window)")
    ax0.set_ylim(-55, -5)
    ax0.set_xlim(0, td[-1])
    ax0.legend(loc="upper right", fontsize=9)
    ax0.grid(True, alpha=0.3)

    # ---- Row 2 left: Short-term histogram ----
    ax1 = fig.add_subplot(gs[2, 0])
    S_valid = S[S > SILENCE_THRESHOLD]
    bins = np.arange(-55, -5, 0.5)
    ax1.hist(S_valid, bins=bins, alpha=0.7, color=c, density=True)
    ax1.axvline(intg, color=c, linestyle="-", alpha=0.8, linewidth=2,
                label=f"I: {intg:.1f}")
    med_s = float(np.median(S_valid))
    ax1.axvline(med_s, color="white", linestyle="--", alpha=0.8, linewidth=1.5,
                label=f"Median: {med_s:.1f}")
    ax1.set_xlabel("Short-term Loudness (LUFS)")
    ax1.set_ylabel("Density")
    ax1.set_title("Short-term Distribution")
    ax1.legend(fontsize=9)
    ax1.grid(True, alpha=0.3)

    # ---- Row 2 right: Momentary histogram ----
    ax2 = fig.add_subplot(gs[2, 1])
    M_valid = M[M > SILENCE_THRESHOLD]
    ax2.hist(M_valid, bins=bins, alpha=0.7, color=c, density=True)
    med_m = float(np.median(M_valid))
    ax2.axvline(med_m, color="white", linestyle="--", alpha=0.8, linewidth=1.5,
                label=f"Median: {med_m:.1f}")
    ax2.set_xlabel("Momentary Loudness (LUFS)")
    ax2.set_ylabel("Density")
    ax2.set_title("Momentary Distribution")
    ax2.legend(fontsize=9)
    ax2.grid(True, alpha=0.3)

    # ---- Row 3: 5-minute segment bars ----
    ax3 = fig.add_subplot(gs[3, :])
    seg_sec = 5 * 60
    segments = np.arange(0, t[-1], seg_sec)
    means, p10s, p90s = [], [], []
    for s in segments:
        i0 = np.searchsorted(t, s, side="left")
        i1 = np.searchsorted(t, s + seg_sec, side="left")
        sv = S[i0:i1]
        sv = sv[sv > SILENCE_THRESHOLD]
        if len(sv) > 0:
            means.append(np.mean(sv))
            p10s.append(np.percentile(sv, 10))
            p90s.append(np.percentile(sv, 90))
        else:
            means.append(np.nan)
            p10s.append(np.nan)
            p90s.append(np.nan)

    x = np.arange(len(segments))
    means_a = np.array(means)
    p10s_a = np.array(p10s)
    p90s_a = np.array(p90s)
    ax3.bar(x, means_a, color=c, alpha=0.7)
    ax3.errorbar(
        x, means_a,
        yerr=[means_a - p10s_a, p90s_a - means_a],
        fmt="none", ecolor="gray", alpha=0.5, capsize=3,
    )
    ax3.set_xticks(x)
    ax3.set_xticklabels(
        [f"{int(s / 60)}\u2013{int((s + seg_sec) / 60)}" for s in segments], fontsize=8,
    )
    ax3.set_xlabel("Time Segment (min)")
    ax3.set_ylabel("Mean Short-term LUFS")
    ax3.set_title("5-Minute Segment Average (error bars: P10\u2013P90)")
    ax3.axhline(intg, color=c, linestyle="-", alpha=0.5, linewidth=1)
    ax3.grid(True, alpha=0.3, axis="y")

    plt.savefig(out_path, dpi=150, bbox_inches="tight", facecolor="white", edgecolor="none")
    plt.close(fig)
    print(f"[output] Plot saved: {out_path}")
