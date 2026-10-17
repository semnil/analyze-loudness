"""Tests for analyze_loudness.compare."""

import math

import numpy as np
import pytest

from analyze_loudness import SCHEMA_VERSION
from analyze_loudness.compare import (
    MAX_TRACKS, build_compare, build_result, common_frames, gated_integrated,
    truncated_stats, validate_compare, validate_single, validate_tracks,
)

WARMUP = [-120.7, -120.7, -120.7]


def _track(n_frames, s=-20.0, m=-21.0, title="T", gate_threshold=-31.0):
    t = [round(0.1 * (i + 1), 2) for i in range(n_frames)]
    return {
        "meta": {"schema_version": 2, "source_url": f"https://example.com/{title}"},
        "title": title,
        "summary": {"integrated": -20.0, "true_peak": -1.0, "lra": 5.0,
                    "gate_threshold": gate_threshold},
        "series": {"t": t, "S": [s] * n_frames, "M": [m] * n_frames},
    }


class TestGatedIntegrated:
    def test_constant_level(self):
        M = WARMUP + [-20.0] * 50
        t = [0.1 * (i + 1) for i in range(len(M))]
        assert gated_integrated(M, t) == pytest.approx(-20.0)

    def test_relative_gate_drops_quiet_blocks(self):
        # Half at -20, half at -40: the relative gate sits near -33, so only
        # the -20 blocks count.
        M = WARMUP + [-20.0] * 50 + [-40.0] * 50
        t = [0.1 * (i + 1) for i in range(len(M))]
        assert gated_integrated(M, t) == pytest.approx(-20.0)

    def test_absolute_gate_and_non_finite(self):
        M = WARMUP + [-20.0] * 10 + [-80.0, float("nan"), float("-inf"), None]
        t = [0.1 * (i + 1) for i in range(len(M))]
        assert gated_integrated(M, t) == pytest.approx(-20.0)

    def test_all_silent_is_none(self):
        M = WARMUP + [-80.0] * 10
        t = [0.1 * (i + 1) for i in range(len(M))]
        assert gated_integrated(M, t) is None

    def test_warmup_frames_are_not_blocks(self):
        # Warm-up frames above the absolute gate would otherwise count.
        M = [-10.0, -10.0, -10.0] + [-20.0] * 20
        t = [0.1 * (i + 1) for i in range(len(M))]
        assert gated_integrated(M, t) == pytest.approx(-20.0)


class TestCommonFrames:
    def test_shortest_track_wins(self):
        assert common_frames([_track(100), _track(40), _track(70)]) == 40

    def test_rounded_times_still_align(self):
        a, b = _track(50), _track(60)
        # ffmpeg-style jitter in the stored times must not drop a frame.
        b["series"]["t"] = [round(x + 0.004, 3) for x in b["series"]["t"]]
        assert common_frames([a, b]) == 50


class TestBuildCompare:
    def test_cuts_every_track_to_the_shortest(self):
        doc = build_compare([_track(100, title="a"), _track(40, title="b")])
        tracks = doc["compare"]["tracks"]
        assert [len(tr["series"]["t"]) for tr in tracks] == [40, 40]
        assert [len(tr["series"]["M"]) for tr in tracks] == [40, 40]
        assert doc["compare"]["truncate_sec"] == pytest.approx(4.0)
        assert doc["meta"]["schema_version"] == SCHEMA_VERSION == 3
        assert "summary" not in doc and "series" not in doc

    def test_whole_track_summary_is_kept(self):
        long = _track(100, title="a")
        doc = build_compare([long, _track(40, title="b")])
        assert doc["compare"]["tracks"][0]["summary"] == long["summary"]
        assert len(long["series"]["t"]) == 100  # input left untouched

    @pytest.mark.parametrize("n", [1, MAX_TRACKS + 1])
    def test_track_count_bounds(self, n):
        with pytest.raises(ValueError):
            build_compare([_track(10) for _ in range(n)])

    def test_result_passes_its_own_validation(self):
        doc = build_compare([_track(30), _track(20), _track(25)])
        assert validate_compare(doc) is None


class TestTruncatedStats:
    def test_stats_cover_the_stored_series_only(self):
        tr = _track(60, s=-25.0, m=-26.0)
        tr["series"]["M"][:3] = WARMUP
        tr["series"]["S"][:29] = [-120.7] * 29
        st = truncated_stats(tr)
        assert st["frames"] == 60
        assert st["duration_sec"] == pytest.approx(6.0)
        assert st["integrated"] == pytest.approx(-26.0)
        assert st["short_term"]["median"] == pytest.approx(-25.0)
        assert st["momentary"]["p10"] == pytest.approx(-26.0)
        # S warm-up (first 3 s) is excluded from the silence share.
        assert st["silence_pct"] == pytest.approx(0.0)

    def test_non_numeric_values_are_silence(self):
        tr = _track(40)
        tr["series"]["S"][35:] = ["x", True, None, "-20", -20.0]
        st = truncated_stats(tr)
        assert st["silence_pct"] == pytest.approx(4 / 11 * 100)

    def test_null_values_are_silence(self):
        tr = _track(40)
        tr["series"]["S"][35:] = [None] * 5
        st = truncated_stats(tr)
        assert st["silence_pct"] > 0
        assert math.isfinite(st["short_term"]["median"])


class TestValidateCompare:
    def _doc(self, *tracks):
        return {"meta": {"schema_version": 3}, "compare": {"truncate_sec": 1.0, "tracks": list(tracks)}}

    def test_tracks_must_be_an_array(self):
        assert "array" in validate_compare({"compare": {"tracks": {}}})

    @pytest.mark.parametrize("n", [1, MAX_TRACKS + 1])
    def test_track_count(self, n):
        assert "tracks" in validate_compare(self._doc(*[_track(5) for _ in range(n)]))

    def test_nested_comparison_rejected(self):
        inner = self._doc(_track(5), _track(5))
        err = validate_compare(self._doc(_track(5), inner))
        assert "Track 2" in err and "comparison" in err

    def test_bad_track_named_by_number(self):
        bad = _track(5)
        del bad["series"]["M"]
        assert "Track 2:" in validate_compare(self._doc(_track(5), bad))

    def test_frame_counts_must_match(self):
        assert "same number of frames" in validate_compare(self._doc(_track(5), _track(6)))

    def test_empty_track_rejected(self):
        assert "no frames" in validate_tracks([_track(5), _track(0)])

    def test_non_numeric_time_rejected(self):
        bad = _track(5)
        bad["series"]["t"][2] = "x"
        assert "Track 2" in validate_tracks([_track(5), bad])

    def test_schema_version_must_be_int(self):
        doc = self._doc(_track(5), _track(5))
        doc["meta"]["schema_version"] = "3"
        assert "schema_version" in validate_compare(doc)


class TestValidateSingle:
    def test_valid(self):
        assert validate_single(_track(5)) is None

    def test_bool_schema_version_rejected(self):
        tr = _track(5)
        tr["meta"]["schema_version"] = True
        assert "schema_version" in validate_single(tr)


class TestBuildResult:
    def test_shape_and_rounding(self):
        t = np.array([0.1 * (i + 1) for i in range(40)])
        S = np.full(40, -20.04)
        M = np.full(40, -21.06)
        res = build_result(t, M, S, {"integrated": -20.0, "true_peak": -1.0, "lra": 4.0,
                                     "gate_threshold": -30.04}, "Title", "https://example.com")
        assert res["meta"]["schema_version"] == SCHEMA_VERSION
        assert res["meta"]["source_url"] == "https://example.com"
        assert res["summary"]["gate_threshold"] == -30.0
        assert res["summary"]["frames"] == 40
        assert res["series"]["S"][0] == -20.0
        assert res["series"]["M"][0] == -21.1
        assert validate_single(res) is None
