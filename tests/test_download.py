"""Tests for analyze_loudness.download module."""

import subprocess
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from analyze_loudness.download import (
    sanitize_filename, compute_middle, probe_duration,
    _run, fetch_title, download_audio,
)


class TestSanitizeFilename:
    def test_removes_unsafe_chars(self):
        result = sanitize_filename('test:file*name?"<>|')
        assert ":" not in result
        assert "*" not in result
        assert "?" not in result
        assert '"' not in result
        assert "<" not in result
        assert ">" not in result
        assert "|" not in result

    def test_replaces_with_underscore(self):
        result = sanitize_filename("a:b")
        assert result == "a_b"

    def test_strips_dots_and_spaces(self):
        result = sanitize_filename("  ..test.. ")
        assert not result.startswith(".")
        assert not result.startswith(" ")

    def test_empty_string_returns_untitled(self):
        assert sanitize_filename("") == "untitled"
        assert sanitize_filename("...") == "untitled"

    def test_truncates_long_name(self):
        long_name = "a" * 300
        result = sanitize_filename(long_name)
        assert len(result) <= 200

    def test_japanese_title_preserved(self):
        title = "【ポケモン】メタモンと始める街づくり"
        result = sanitize_filename(title)
        assert "ポケモン" in result

    def test_backslash_and_slash(self):
        result = sanitize_filename("path/to\\file")
        assert "/" not in result
        assert "\\" not in result


class TestComputeMiddle:
    def test_full_duration_when_shorter(self):
        ss, dur, msg = compute_middle(300.0, 10.0)
        assert ss == 0.0
        assert dur == 300.0
        assert "full duration" in msg

    def test_middle_extraction(self):
        ss, dur, msg = compute_middle(3600.0, 10.0)
        expected_dur = 600.0
        expected_ss = (3600.0 - 600.0) / 2
        assert dur == expected_dur
        assert ss == expected_ss
        assert "extracting" in msg

    def test_exact_match(self):
        ss, dur, msg = compute_middle(600.0, 10.0)
        assert ss == 0.0
        assert dur == 600.0

    def test_returns_three_values(self):
        result = compute_middle(1000.0, 5.0)
        assert len(result) == 3
        assert isinstance(result[2], str)


class TestProbeDuration:
    @patch("analyze_loudness.download._run")
    def test_returns_duration(self, mock_run):
        mock_run.return_value = MagicMock(
            stdout='{"format": {"duration": "123.456"}}'
        )
        result = probe_duration("/fake/audio.opus")
        assert result == pytest.approx(123.456)

    @patch("analyze_loudness.download._run")
    def test_missing_duration_raises(self, mock_run):
        mock_run.return_value = MagicMock(stdout='{"format": {}}')
        with pytest.raises(RuntimeError, match="could not determine duration"):
            probe_duration("/fake/audio.opus")

    @patch("analyze_loudness.download._run")
    def test_missing_format_raises(self, mock_run):
        mock_run.return_value = MagicMock(stdout='{}')
        with pytest.raises(RuntimeError, match="could not determine duration"):
            probe_duration("/fake/audio.opus")

    @patch("analyze_loudness.download._run")
    def test_calls_ffprobe_with_correct_args(self, mock_run):
        mock_run.return_value = MagicMock(
            stdout='{"format": {"duration": "60.0"}}'
        )
        probe_duration("/path/to/file.opus")
        cmd = mock_run.call_args[0][0]
        assert cmd[0] == "ffprobe"
        assert "/path/to/file.opus" in cmd


class TestRun:
    @patch("analyze_loudness.download._subprocess_kwargs", return_value={})
    @patch("analyze_loudness.download.subprocess.run")
    def test_success(self, mock_run, mock_kwargs):
        mock_run.return_value = MagicMock(returncode=0, stdout="ok\n")
        result = _run(["echo", "hello"])
        assert result.stdout == "ok\n"
        mock_run.assert_called_once()

    @patch("analyze_loudness.download._subprocess_kwargs", return_value={})
    @patch("analyze_loudness.download.subprocess.run")
    def test_calledprocesserror_raises_runtime(self, mock_run, mock_kwargs):
        mock_run.side_effect = subprocess.CalledProcessError(
            1, "yt-dlp", stderr="some error text"
        )
        with pytest.raises(RuntimeError, match="yt-dlp failed"):
            _run(["yt-dlp", "--version"])

    @patch("analyze_loudness.download._subprocess_kwargs", return_value={})
    @patch("analyze_loudness.download.subprocess.run")
    def test_stderr_truncated_to_500(self, mock_run, mock_kwargs):
        long_stderr = "x" * 1000
        mock_run.side_effect = subprocess.CalledProcessError(
            1, "cmd", stderr=long_stderr
        )
        with pytest.raises(RuntimeError) as exc_info:
            _run(["cmd"])
        # The message includes at most 500 chars of stderr
        assert len(exc_info.value.args[0]) < 600


class TestFetchTitle:
    @patch("analyze_loudness.download._run")
    def test_returns_title(self, mock_run):
        mock_run.return_value = MagicMock(stdout="My Video Title\n")
        assert fetch_title("https://example.com") == "My Video Title"

    @patch("analyze_loudness.download._run")
    def test_returns_untitled_on_error(self, mock_run):
        mock_run.side_effect = RuntimeError("failed")
        assert fetch_title("https://example.com") == "Untitled"

    @patch("analyze_loudness.download._run")
    def test_returns_untitled_on_empty_output(self, mock_run):
        mock_run.return_value = MagicMock(stdout="")
        assert fetch_title("https://example.com") == "Untitled"

    @patch("analyze_loudness.download._run")
    def test_multiline_takes_first(self, mock_run):
        mock_run.return_value = MagicMock(stdout="First Line\nSecond Line\n")
        assert fetch_title("https://example.com") == "First Line"


class TestDownloadAudio:
    @patch("analyze_loudness.download._run")
    @patch("analyze_loudness.download.fetch_title", return_value="Test Title")
    def test_returns_file_and_title(self, mock_title, mock_run, tmp_path):
        # Create a fake downloaded file
        fake_file = tmp_path / "abc123.opus"
        fake_file.write_text("fake audio")

        result = download_audio("https://example.com", str(tmp_path))
        assert result == (str(fake_file), "Test Title")

    @patch("analyze_loudness.download._run")
    @patch("analyze_loudness.download.fetch_title", return_value="Title")
    def test_no_file_raises(self, mock_title, mock_run, tmp_path):
        with pytest.raises(FileNotFoundError, match="no audio file"):
            download_audio("https://example.com", str(tmp_path))

    @patch("analyze_loudness.download._run")
    @patch("analyze_loudness.download.fetch_title", return_value="Title")
    def test_calls_ytdlp_with_correct_args(self, mock_title, mock_run, tmp_path):
        fake_file = tmp_path / "abc.opus"
        fake_file.write_text("data")
        download_audio("https://example.com/watch?v=X", str(tmp_path))
        cmd = mock_run.call_args[0][0]
        assert cmd[0] == "yt-dlp"
        assert "-x" in cmd
        assert "https://example.com/watch?v=X" in cmd
