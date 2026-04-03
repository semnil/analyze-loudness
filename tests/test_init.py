"""Tests for analyze_loudness.__init__ module."""

import subprocess
from unittest.mock import patch

from analyze_loudness import _subprocess_kwargs


class TestSubprocessKwargs:
    def test_returns_empty_dict_on_non_windows(self):
        with patch("analyze_loudness.sys") as mock_sys:
            mock_sys.platform = "linux"
            mock_sys.frozen = False
            result = _subprocess_kwargs()
        assert result == {}

    def test_returns_empty_dict_on_windows_not_frozen(self):
        with patch("analyze_loudness.sys") as mock_sys:
            mock_sys.platform = "win32"
            del mock_sys.frozen  # getattr(..., False) returns False
            result = _subprocess_kwargs()
        assert result == {}

    def test_returns_startupinfo_on_windows_frozen(self):
        with patch("analyze_loudness.sys") as mock_sys:
            mock_sys.platform = "win32"
            mock_sys.frozen = True
            result = _subprocess_kwargs()
        assert "startupinfo" in result
        si = result["startupinfo"]
        assert isinstance(si, subprocess.STARTUPINFO)
        assert si.dwFlags & subprocess.STARTF_USESHOWWINDOW
