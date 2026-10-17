"""Tests for analyze_loudness.plot."""

import matplotlib
import numpy as np
import pytest

from analyze_loudness.compare import build_compare, truncated_stats
from analyze_loudness.plot import plot_analysis, plot_compare

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402


def _series(n_frames, level):
    t = np.round(np.arange(1, n_frames + 1) * 0.1, 2)
    return t, np.full(n_frames, level, dtype=float)


def _burst(n_frames=6000):
    # Quiet floor with a short loud burst: the segment mean sits above P90.
    t, S = _series(n_frames, -57.1)
    S[200:210] = -10.0
    return t, S


def _doc(t, S, title):
    return {
        "meta": {"schema_version": 3}, "title": title,
        "summary": {"integrated": -20.0, "true_peak": -1.0, "lra": 1.0},
        "series": {"t": t.tolist(), "S": S.tolist(), "M": S.tolist()},
    }


def test_burst_mean_lies_outside_p10_p90():
    t, S = _burst()
    seg = S[:3000]
    assert np.mean(seg) > np.percentile(seg, 90)


@pytest.mark.parametrize("make", [_burst, lambda: _series(6000, -21.06)], ids=["burst", "constant"])
def test_single_figure_draws(tmp_path, make):
    t, S = make()
    out = tmp_path / "single.png"
    plot_analysis(t, S, S, {"integrated": -21.0, "true_peak": -1.0, "lra": 0.0}, "x", str(out))
    assert out.stat().st_size > 0


@pytest.mark.parametrize("make", [_burst, lambda: _series(6000, -21.06)], ids=["burst", "constant"])
def test_comparison_figure_draws(tmp_path, make):
    t, S = make()
    t2, S2 = _series(6000, -20.0)
    doc = build_compare([_doc(t, S, "a"), _doc(t2, S2, "b")])
    out = tmp_path / "compare.png"
    plot_compare(doc, [truncated_stats(tr) for tr in doc["compare"]["tracks"]], str(out))
    assert out.stat().st_size > 0


def test_p10_p90_drawn_at_their_own_positions():
    from analyze_loudness.plot import _draw_p10_p90
    fig, ax = plt.subplots()
    p10s = np.array([-57.1, -30.0, np.nan])
    p90s = np.array([-57.1, -20.0, np.nan])
    _draw_p10_p90(ax, np.arange(3), p10s, p90s)
    spans = ax.collections[0].get_segments()
    assert [tuple(s[:, 1]) for s in spans[:2]] == [(-57.1, -57.1), (-30.0, -20.0)]
    plt.close(fig)
