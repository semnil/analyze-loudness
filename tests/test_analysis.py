"""Tests for analyze_loudness.analysis module."""

from unittest.mock import patch, MagicMock

import numpy as np
import pytest

from analyze_loudness.analysis import SILENCE_THRESHOLD, compute_stats, run_ebur128


class TestComputeStats:
    def test_normal_input(self):
        arr = np.array([-20.0, -22.0, -18.0, -25.0, -19.0])
        result = compute_stats(arr, "test")
        assert result["label"] == "test"
        assert isinstance(result["median"], float)
        assert isinstance(result["mean"], float)
        assert result["p10"] <= result["median"] <= result["p90"]

    def test_all_silence_returns_none(self):
        arr = np.array([-70.0, -80.0, -90.0])
        result = compute_stats(arr, "silent")
        assert result["median"] is None
        assert result["mean"] is None
        assert result["p10"] is None
        assert result["p90"] is None

    def test_empty_array_returns_none(self):
        arr = np.array([])
        result = compute_stats(arr, "empty")
        assert result["median"] is None

    def test_single_value(self):
        arr = np.array([-20.0])
        result = compute_stats(arr, "single")
        assert result["median"] == -20.0
        assert result["mean"] == -20.0

    def test_custom_threshold(self):
        arr = np.array([-20.0, -50.0, -55.0])
        result_default = compute_stats(arr, "t1")
        result_strict = compute_stats(arr, "t2", threshold=-40)
        assert result_default["median"] != result_strict["median"]

    def test_values_at_threshold_excluded(self):
        arr = np.array([SILENCE_THRESHOLD, -20.0, -25.0])
        result = compute_stats(arr, "boundary")
        # SILENCE_THRESHOLD exactly should be excluded (> not >=)
        assert result["min"] == -25.0

    def test_stats_keys(self):
        arr = np.array([-20.0, -22.0, -18.0])
        result = compute_stats(arr, "keys")
        expected_keys = {"label", "median", "mean", "p10", "p90", "min", "max"}
        assert set(result.keys()) == expected_keys


class TestRunEbur128:
    def test_invalid_file_raises(self):
        with pytest.raises(RuntimeError, match="No ebur128 data"):
            run_ebur128("/nonexistent/file.wav")

    def test_ss_and_duration_params_accepted(self):
        """Verify the function accepts ss/duration without type errors."""
        with pytest.raises((RuntimeError, FileNotFoundError)):
            run_ebur128("/nonexistent.wav", ss=10.0, duration=30.0)


MOCK_EBUR128_STDERR = """\
[Parsed_ebur128_0 @ 0x1234] t: 0.100    TARGET:-23 LUFS    M: -20.1 S: -22.3    I: -23.0 LUFS    LRA:   5.0 LU
[Parsed_ebur128_0 @ 0x1234] t: 0.200    TARGET:-23 LUFS    M: -19.5 S: -21.8    I: -22.5 LUFS    LRA:   5.1 LU
[Parsed_ebur128_0 @ 0x1234] t: 0.300    TARGET:-23 LUFS    M: -18.0 S: -20.1    I: -22.0 LUFS    LRA:   5.2 LU

[Parsed_ebur128_0 @ 0x1234] Summary:

  Integrated loudness:
    I:         -22.0 LUFS
    Threshold: -32.0 LUFS

  Loudness range:
    LRA:         5.2 LU
    Threshold: -42.0 LUFS
    LRA low:   -26.0 LUFS
    LRA high:  -20.8 LUFS

  True peak:
    Peak:        0.3 dBFS
"""


class TestRunEbur128Parsing:
    """Test ebur128 stderr parsing with mocked subprocess."""

    @patch("analyze_loudness.analysis.subprocess.run")
    def test_parses_per_frame_data(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stderr=MOCK_EBUR128_STDERR)
        t, M, S, summary = run_ebur128("/fake/audio.opus")
        assert len(t) == 3
        assert t[0] == pytest.approx(0.1)
        assert M[0] == pytest.approx(-20.1)
        assert S[0] == pytest.approx(-22.3)

    @patch("analyze_loudness.analysis.subprocess.run")
    def test_parses_summary_integrated(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stderr=MOCK_EBUR128_STDERR)
        _, _, _, summary = run_ebur128("/fake/audio.opus")
        assert summary["integrated"] == pytest.approx(-22.0)

    @patch("analyze_loudness.analysis.subprocess.run")
    def test_parses_summary_lra(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stderr=MOCK_EBUR128_STDERR)
        _, _, _, summary = run_ebur128("/fake/audio.opus")
        assert summary["lra"] == pytest.approx(5.2)

    @patch("analyze_loudness.analysis.subprocess.run")
    def test_parses_summary_true_peak(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stderr=MOCK_EBUR128_STDERR)
        _, _, _, summary = run_ebur128("/fake/audio.opus")
        assert summary["true_peak"] == pytest.approx(0.3)

    @patch("analyze_loudness.analysis.subprocess.run")
    def test_no_summary_block(self, mock_run):
        stderr = (
            "[Parsed_ebur128_0 @ 0x1] t: 0.100    TARGET:-23 LUFS"
            "    M: -20.0 S: -22.0\n"
        )
        mock_run.return_value = MagicMock(returncode=0, stderr=stderr)
        _, _, _, summary = run_ebur128("/fake/audio.opus")
        assert summary == {}

    @patch("analyze_loudness.analysis.subprocess.run")
    def test_ss_and_duration_in_command(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stderr=MOCK_EBUR128_STDERR)
        run_ebur128("/fake/audio.opus", ss=10.0, duration=30.0)
        cmd = mock_run.call_args[0][0]
        assert "-ss" in cmd
        assert "10.0" in cmd
        assert "-t" in cmd
        assert "30.0" in cmd

    @patch("analyze_loudness.analysis.subprocess.run")
    def test_no_data_raises(self, mock_run):
        mock_run.return_value = MagicMock(returncode=1, stderr="some error\n")
        with pytest.raises(RuntimeError, match="No ebur128 data"):
            run_ebur128("/fake/audio.opus")

    @patch("analyze_loudness.analysis.subprocess.run")
    def test_true_peak_negative_inf(self, mock_run):
        stderr = MOCK_EBUR128_STDERR.replace("0.3 dBFS", "-inf dBFS")
        mock_run.return_value = MagicMock(returncode=0, stderr=stderr)
        _, _, _, summary = run_ebur128("/fake/audio.opus")
        assert summary["true_peak"] == float("-inf")


class TestComputeStatsNanInf:
    """V-01, V-02: NaN/Inf handling in compute_stats."""

    def test_nan_values_excluded(self):
        arr = np.array([-20.0, np.nan, -25.0, np.nan])
        result = compute_stats(arr, "nan_test")
        assert result["median"] is not None
        # NaN should be stripped; only -20 and -25 contribute
        assert result["min"] == -25.0
        assert result["max"] == -20.0

    def test_inf_values_excluded(self):
        arr = np.array([-20.0, np.inf, -25.0, -np.inf])
        result = compute_stats(arr, "inf_test")
        # +inf passes threshold, -inf does not; +inf removed by isfinite
        assert result["median"] is not None
        assert result["min"] == -25.0
        assert result["max"] == -20.0

    def test_all_nan_returns_none(self):
        arr = np.array([np.nan, np.nan, np.nan])
        result = compute_stats(arr, "all_nan")
        assert result["median"] is None
        assert result["mean"] is None

    def test_mixed_nan_inf_silence(self):
        # -70 is below threshold, nan and inf are non-finite
        arr = np.array([-70.0, np.nan, np.inf, -20.0])
        result = compute_stats(arr, "mixed")
        assert result["median"] == -20.0
        assert result["mean"] == -20.0


class TestRunEbur128InfNanFrames:
    """V-03: Parsing frames with -inf / nan M/S values."""

    @patch("analyze_loudness.analysis.subprocess.run")
    def test_inf_frame_parsed(self, mock_run):
        stderr = (
            "[Parsed_ebur128_0 @ 0x1] t: 0.100    TARGET:-23 LUFS"
            "    M: -inf S: -inf\n"
            "[Parsed_ebur128_0 @ 0x1] t: 0.200    TARGET:-23 LUFS"
            "    M: -20.0 S: -22.0\n"
        )
        mock_run.return_value = MagicMock(returncode=0, stderr=stderr)
        t, M, S, summary = run_ebur128("/fake/audio.opus")
        assert len(t) == 2
        assert M[0] == float("-inf")
        assert S[0] == float("-inf")
        assert M[1] == pytest.approx(-20.0)

    @patch("analyze_loudness.analysis.subprocess.run")
    def test_nan_frame_parsed(self, mock_run):
        stderr = (
            "[Parsed_ebur128_0 @ 0x1] t: 0.100    TARGET:-23 LUFS"
            "    M: nan S: nan\n"
            "[Parsed_ebur128_0 @ 0x1] t: 0.200    TARGET:-23 LUFS"
            "    M: -18.0 S: -19.0\n"
        )
        mock_run.return_value = MagicMock(returncode=0, stderr=stderr)
        t, M, S, _ = run_ebur128("/fake/audio.opus")
        assert len(t) == 2
        assert np.isnan(M[0])
        assert np.isnan(S[0])

    @patch("analyze_loudness.analysis.subprocess.run")
    def test_all_inf_integration_with_compute_stats(self, mock_run):
        """All-silent audio: every frame is -inf -> stats return None."""
        stderr = (
            "[Parsed_ebur128_0 @ 0x1] t: 0.100    TARGET:-23 LUFS"
            "    M: -inf S: -inf\n"
            "[Parsed_ebur128_0 @ 0x1] t: 0.200    TARGET:-23 LUFS"
            "    M: -inf S: -inf\n"
        )
        mock_run.return_value = MagicMock(returncode=0, stderr=stderr)
        _, M, S, _ = run_ebur128("/fake/audio.opus")
        st = compute_stats(S, "silent")
        mo = compute_stats(M, "silent")
        assert st["median"] is None
        assert mo["median"] is None


class TestSilenceThreshold:
    def test_value(self):
        assert SILENCE_THRESHOLD == -60
