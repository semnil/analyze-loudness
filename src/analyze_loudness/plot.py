"""Generate loudness analysis plots."""

import os

import numpy as np

os.environ.setdefault("MPLBACKEND", "Agg")
import matplotlib
import matplotlib.pyplot as plt
from matplotlib.gridspec import GridSpec

from analyze_loudness.analysis import SILENCE_THRESHOLD, compute_stats, compute_silence_pct

# Use a CJK-capable font if available, fallback to sans-serif
for _font in ("Meiryo", "Yu Gothic", "Hiragino Sans", "Noto Sans CJK JP", "MS Gothic"):
    if _font in {f.name for f in matplotlib.font_manager.fontManager.ttflist}:
        matplotlib.rcParams["font.family"] = _font
        break


def _moving_avg(x: np.ndarray, w: int = 60) -> np.ndarray:
    kernel = np.ones(w) / w
    padded = np.pad(x, (w // 2, w // 2), mode="edge")
    return np.convolve(padded, kernel, mode="valid")[: len(x)]


def _segment_stats(t: np.ndarray, S: np.ndarray, seg_sec: float = 5 * 60):
    starts = np.arange(0, t[-1], seg_sec)
    means, p10s, p90s = [], [], []
    for s in starts:
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
    return starts, np.array(means), np.array(p10s), np.array(p90s)


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
    silence_pct = compute_silence_pct(t, S)

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

    def _fmt(x, suffix="", sign=""):
        if x is None:
            return "N/A"
        return f"{x:{sign}.1f}{suffix}"

    table_data = [
        [
            f"{t[-1] / 60:.1f} min ({len(t)} frames)",
            _fmt(intg, " LUFS"),
            _fmt(true_peak, " dBFS", "+"),
            _fmt(lra, " LU"),
        ],
        [
            _fmt(st['median'], " LUFS"),
            f"{_fmt(st['p10'])} / {_fmt(st['p90'])} LUFS",
            _fmt(mo['median'], " LUFS"),
            f"{_fmt(mo['p10'])} / {_fmt(mo['p90'])} LUFS",
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
    if len(S_valid) > 0:
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
    if len(M_valid) > 0:
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
    segments, means_a, p10s_a, p90s_a = _segment_stats(t, S, seg_sec)
    x = np.arange(len(segments))
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


# Track colours on a white background.  Mirror of trackColors (light) in
# frontend/theme.js; change both together.
TRACK_COLORS = ["#B71C1C", "#1A237E", "#CC79A7", "#7E57C2", "#006064", "#3E2723"]


def plot_compare(doc: dict, stats: list[dict], out_path: str) -> None:
    """Comparison figure: per-track table, overlaid timeline and histograms,
    and one 5-minute segment chart per track.  Every line carries its track
    number so the figure reads without colour."""
    tracks = doc["compare"]["tracks"]
    n = len(tracks)
    arrays = []
    for tr in tracks:
        s = tr["series"]
        arrays.append(tuple(
            np.array([np.nan if v is None else float(v) for v in s[k]], dtype=float)
            for k in ("t", "S", "M")))

    fig = plt.figure(figsize=(16, 11 + 1.6 * n))
    gs = GridSpec(
        3 + n, 2, figure=fig,
        height_ratios=[0.12 * (n + 1), 2, 1.2] + [0.8] * n,
        hspace=0.45, wspace=0.25, top=0.95,
    )
    fig.suptitle(
        f"Loudness Comparison ({n} tracks, first {doc['compare']['truncate_sec'] / 60:.1f} min)"
        "\nBS.1770 / EBU R128",
        fontsize=15, fontweight="bold", y=0.99,
    )

    def _fmt(x, sign=""):
        return "N/A" if x is None else f"{x:{sign}.1f}"

    ax_tbl = fig.add_subplot(gs[0, :])
    ax_tbl.axis("off")
    col_labels = ["#", "Track", "Integrated", "Integrated (full)", "True Peak (full)",
                  "LRA (full)", "S-term Median", "Mom. Median", "Silence"]
    cells = []
    for i, (tr, st) in enumerate(zip(tracks, stats)):
        title = tr.get("title") or "untitled"
        cells.append([
            str(i + 1), title if len(title) <= 32 else title[:31] + "\u2026",
            _fmt(st["integrated"]), _fmt(tr["summary"].get("integrated")),
            _fmt(tr["summary"].get("true_peak"), "+"), _fmt(tr["summary"].get("lra")),
            _fmt(st["short_term"]["median"]), _fmt(st["momentary"]["median"]),
            f"{_fmt(st['silence_pct'])}%",
        ])
    tbl = ax_tbl.table(cellText=cells, colLabels=col_labels, loc="center",
                       cellLoc="center", bbox=[0.0, 0.0, 1.0, 1.0],
                       colWidths=[0.03, 0.27] + [0.7 / 7] * 7)
    tbl.auto_set_font_size(False)
    tbl.set_fontsize(9)
    for (row, col), cell in tbl.get_celld().items():
        cell.set_edgecolor("#CCCCCC")
        if row == 0:
            cell.set_facecolor("#E1BEE7")
            cell.set_text_props(fontweight="bold")
        elif col == 0:
            cell.set_text_props(color=TRACK_COLORS[row - 1], fontweight="bold")
        elif col == 1:
            cell.set_text_props(ha="left")
            cell.PAD = 0.02

    ax0 = fig.add_subplot(gs[1, :])
    for i, (t, S, _M) in enumerate(arrays):
        step = max(1, len(t) // 3000)
        td = t[::step] / 60
        sm = _moving_avg(S[::step])
        col = TRACK_COLORS[i]
        ax0.plot(td, sm, color=col, linewidth=1.8, label=f"{i + 1}")
        ax0.annotate(str(i + 1), (td[-1], sm[-1]), xytext=(4, 0), textcoords="offset points",
                     color=col, fontsize=10, fontweight="bold", va="center")
    ax0.axhline(-23, color="#4CAF50", linestyle="--", alpha=0.6, linewidth=1.2,
                label="Target \u221223 LUFS")
    ax0.set_ylabel("Short-term LUFS (60s moving avg)")
    ax0.set_xlabel("Time (min)")
    ax0.set_title("Short-term Loudness")
    ax0.set_ylim(-55, -5)
    ax0.legend(loc="upper right", fontsize=9, ncol=n + 1)
    ax0.grid(True, alpha=0.3)

    bins = np.arange(-55, -5, 0.5)
    for col_idx, (key, name) in enumerate(((1, "Short-term"), (2, "Momentary"))):
        ax = fig.add_subplot(gs[2, col_idx])
        for i, arr in enumerate(arrays):
            v = arr[key]
            v = v[np.isfinite(v) & (v > SILENCE_THRESHOLD)]
            if len(v) == 0:
                continue
            ax.hist(v, bins=bins, density=True, histtype="step", linewidth=1.6,
                    color=TRACK_COLORS[i], label=str(i + 1))
        ax.set_xlabel(f"{name} Loudness (LUFS)")
        ax.set_ylabel("Density")
        ax.set_title(f"{name} Distribution")
        ax.legend(fontsize=9, ncol=n)
        ax.grid(True, alpha=0.3)

    for i, (t, S, _M) in enumerate(arrays):
        ax = fig.add_subplot(gs[3 + i, :])
        starts, means, p10s, p90s = _segment_stats(t, S)
        x = np.arange(len(starts))
        col = TRACK_COLORS[i]
        ax.bar(x, means, color=col, alpha=0.75)
        ax.errorbar(x, means, yerr=[means - p10s, p90s - means],
                    fmt="none", ecolor="gray", alpha=0.6, capsize=3)
        ax.set_xticks(x)
        ax.set_xticklabels([f"{int(s / 60)}\u2013{int((s + 300) / 60)}" for s in starts], fontsize=8)
        title = tracks[i].get("title") or "untitled"
        ax.set_title(f"{i + 1}: {title}  (5-minute segments, error bars P10\u2013P90)",
                     fontsize=10, color=col, loc="left")
        ax.set_ylabel("Mean S LUFS")
        ax.grid(True, alpha=0.3, axis="y")

    plt.savefig(out_path, dpi=150, bbox_inches="tight", facecolor="white", edgecolor="none")
    plt.close(fig)
    print(f"[output] Plot saved: {out_path}")
