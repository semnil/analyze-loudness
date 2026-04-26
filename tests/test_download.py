"""Tests for analyze_loudness.download module (loudness-specific wrappers)."""

from unittest.mock import patch, MagicMock

import pytest

from analyze_loudness.download import probe_duration, download_audio


class TestProbeDuration:
    @patch("analyze_loudness.download.probe_info", return_value=(2, 123.456))
    def test_returns_duration(self, mock_probe):
        result = probe_duration("/fake/audio.opus")
        assert result == pytest.approx(123.456)
        mock_probe.assert_called_once_with("/fake/audio.opus")

    @patch("analyze_loudness.download.probe_info", side_effect=RuntimeError("could not determine duration"))
    def test_missing_duration_raises(self, mock_probe):
        with pytest.raises(RuntimeError, match="could not determine duration"):
            probe_duration("/fake/audio.opus")

    @patch("analyze_loudness.download.probe_info", return_value=(1, 60.0))
    def test_discards_channels(self, mock_probe):
        result = probe_duration("/path/to/file.opus")
        assert result == 60.0


class TestDownloadAudio:
    def _mock_ydl(self, info):
        ctx = MagicMock()
        ctx.__enter__ = MagicMock(return_value=ctx)
        ctx.__exit__ = MagicMock(return_value=False)
        ctx.extract_info = MagicMock(return_value=info)
        return ctx

    @patch("analyze_common.download.YoutubeDL")
    def test_returns_file_and_title(self, mock_ydl_cls, tmp_path):
        fake_file = tmp_path / "abc123.opus"
        fake_file.write_text("fake audio")
        mock_ydl_cls.return_value = self._mock_ydl({"title": "Test Title"})

        result = download_audio("https://example.com", str(tmp_path))
        assert result == (str(fake_file), "Test Title")

    @patch("analyze_common.download.YoutubeDL")
    def test_no_file_raises(self, mock_ydl_cls, tmp_path):
        mock_ydl_cls.return_value = self._mock_ydl({"title": "Title"})
        with pytest.raises(FileNotFoundError, match="no audio file"):
            download_audio("https://example.com", str(tmp_path))

    @patch("analyze_common.download.YoutubeDL")
    def test_missing_title_falls_back_to_untitled(self, mock_ydl_cls, tmp_path):
        fake_file = tmp_path / "abc.opus"
        fake_file.write_text("data")
        mock_ydl_cls.return_value = self._mock_ydl({})

        _, title = download_audio("https://example.com", str(tmp_path))
        assert title == "Untitled"

    @patch("analyze_common.download.YoutubeDL")
    def test_extract_info_error_raises_runtime(self, mock_ydl_cls, tmp_path):
        ctx = self._mock_ydl({})
        ctx.extract_info.side_effect = Exception("network error")
        mock_ydl_cls.return_value = ctx
        with pytest.raises(RuntimeError, match="yt-dlp failed"):
            download_audio("https://example.com", str(tmp_path))

    @patch("analyze_common.download.YoutubeDL")
    def test_passes_opus_postprocessor(self, mock_ydl_cls, tmp_path):
        fake_file = tmp_path / "abc.opus"
        fake_file.write_text("data")
        mock_ydl_cls.return_value = self._mock_ydl({"title": "T"})

        download_audio("https://example.com/watch?v=X", str(tmp_path))
        opts = mock_ydl_cls.call_args[0][0]
        assert opts["postprocessors"][0]["preferredcodec"] == "opus"
        assert str(tmp_path) in opts["outtmpl"]
