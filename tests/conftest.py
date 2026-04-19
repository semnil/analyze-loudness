"""Test session setup: register static_ffmpeg binaries on PATH.

This lets the test suite run on hosts that do not have ffmpeg / ffprobe
installed system-wide (the ``static-ffmpeg`` package bundles binaries as
a pip dependency).  If ``static_ffmpeg`` is unavailable the fixture is a
no-op -- tests that require the binary will fall back to system PATH.
"""

import pytest


@pytest.fixture(scope="session", autouse=True)
def _register_static_ffmpeg():
    try:
        import static_ffmpeg
        static_ffmpeg.add_paths()
    except Exception:
        pass
    yield
