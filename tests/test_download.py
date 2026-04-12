"""Tests for analyze_loudness.download module."""

import subprocess
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from analyze_loudness.download import (
    sanitize_filename, compute_middle, probe_duration,
    _run, download_audio,
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


class TestDownloadAudio:
    def _mock_ydl(self, info):
        ctx = MagicMock()
        ctx.__enter__ = MagicMock(return_value=ctx)
        ctx.__exit__ = MagicMock(return_value=False)
        ctx.extract_info = MagicMock(return_value=info)
        return ctx

    @patch("analyze_loudness.download.YoutubeDL")
    def test_returns_file_and_title(self, mock_ydl_cls, tmp_path):
        fake_file = tmp_path / "abc123.opus"
        fake_file.write_text("fake audio")
        mock_ydl_cls.return_value = self._mock_ydl({"title": "Test Title"})

        result = download_audio("https://example.com", str(tmp_path))
        assert result == (str(fake_file), "Test Title")

    @patch("analyze_loudness.download.YoutubeDL")
    def test_no_file_raises(self, mock_ydl_cls, tmp_path):
        mock_ydl_cls.return_value = self._mock_ydl({"title": "Title"})
        with pytest.raises(FileNotFoundError, match="no audio file"):
            download_audio("https://example.com", str(tmp_path))

    @patch("analyze_loudness.download.YoutubeDL")
    def test_missing_title_falls_back_to_untitled(self, mock_ydl_cls, tmp_path):
        fake_file = tmp_path / "abc.opus"
        fake_file.write_text("data")
        mock_ydl_cls.return_value = self._mock_ydl({})

        _, title = download_audio("https://example.com", str(tmp_path))
        assert title == "Untitled"

    @patch("analyze_loudness.download.YoutubeDL")
    def test_extract_info_error_raises_runtime(self, mock_ydl_cls, tmp_path):
        ctx = self._mock_ydl({})
        ctx.extract_info.side_effect = Exception("network error")
        mock_ydl_cls.return_value = ctx
        with pytest.raises(RuntimeError, match="yt-dlp failed"):
            download_audio("https://example.com", str(tmp_path))

    @patch("analyze_loudness.download.YoutubeDL")
    def test_passes_opus_postprocessor(self, mock_ydl_cls, tmp_path):
        fake_file = tmp_path / "abc.opus"
        fake_file.write_text("data")
        mock_ydl_cls.return_value = self._mock_ydl({"title": "T"})

        download_audio("https://example.com/watch?v=X", str(tmp_path))
        opts = mock_ydl_cls.call_args[0][0]
        assert opts["postprocessors"][0]["preferredcodec"] == "opus"
        assert str(tmp_path) in opts["outtmpl"]
