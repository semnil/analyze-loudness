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


class TestResolveSource:
    @patch("analyze_loudness.download.download_audio", return_value=("/tmp/x.opus", "Title"))
    def test_url_is_downloaded(self, mock_dl, tmp_path):
        from analyze_loudness.download import resolve_source
        assert resolve_source("https://example.com/v", str(tmp_path)) == ("/tmp/x.opus", "Title")
        mock_dl.assert_called_once()

    @patch("analyze_loudness.download.download_audio")
    def test_local_file_used_in_place(self, mock_dl, tmp_path):
        from analyze_loudness.download import resolve_source
        f = tmp_path / "My Song.wav"
        f.write_bytes(b"RIFF")
        path, title = resolve_source(str(f), str(tmp_path / "work"))
        assert path == str(f.resolve())
        assert title == "My Song"
        mock_dl.assert_not_called()

    def test_missing_file_raises(self, tmp_path):
        from analyze_loudness.download import resolve_source
        with pytest.raises(FileNotFoundError):
            resolve_source(str(tmp_path / "nope.wav"), str(tmp_path))

    def test_local_path_expands_home(self):
        import os
        from analyze_loudness.download import local_path
        assert local_path("~/x.wav") == os.path.realpath(os.path.expanduser("~/x.wav"))


class TestNetworkPaths:
    UNC = [r"\\host\share\a.wav", "//host/share/a.wav", r"\\?\C:\a.wav", r"\\.\pipe\x", "\\/host/share/a.wav"]

    def test_detected(self):
        from analyze_loudness.download import is_network_path
        for p in self.UNC:
            assert is_network_path(p), p
        for p in ["/Users/me/a.wav", r"C:\music\a.wav", "a.wav", "~/a.wav", "https://example.com/v"]:
            assert not is_network_path(p), p

    @patch("analyze_loudness.download.local_path", side_effect=AssertionError("resolved a network path"))
    def test_resolve_source_refuses_before_touching_the_path(self, _resolve, tmp_path):
        from analyze_loudness.download import resolve_source
        for p in self.UNC + self.NT_NAMESPACE:
            with pytest.raises(ValueError, match="(?i)network"):
                resolve_source(p, str(tmp_path))

    # NT namespace paths, including the ones "." / ".." segments normalize to it.
    NT_NAMESPACE = [r"\??\UNC\host\share\a.wav", "/??/UNC/host/share/a.wav", r"\??\C:\a.wav",
                    r"\.\??\UNC\host\share\a.wav", r"\dir\..\??\UNC\host\share\a.wav", "\\??\\"]

    def test_nt_namespace_detected(self):
        from analyze_loudness.download import is_network_path
        for p in self.NT_NAMESPACE:
            assert is_network_path(p), p
        for p in [r"\Users\me\a.wav", r"C:\dir\..\??\a.wav", r"..\??\a.wav", "/Users/me/??/a.wav"]:
            assert not is_network_path(p), p
