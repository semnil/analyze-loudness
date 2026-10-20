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


@pytest.fixture(autouse=True)
def _isolated_settings(tmp_path_factory, monkeypatch):
    """Keep the app's settings file in a temp folder, for the store gui.py has
    already built and for any built during the test."""
    import sys

    import analyze_loudness  # noqa: F401  (puts vendor/py-analyze-common on sys.path)
    from analyze_common import settings as settings_module
    from analyze_common import update as update_module
    from analyze_common.settings import SETTINGS_NAME

    folder = tmp_path_factory.mktemp("settings")
    monkeypatch.setattr(settings_module, "settings_dir", lambda product: folder / product)
    monkeypatch.setattr(update_module, "settings_dir", lambda product: folder / product)
    gui = sys.modules.get("analyze_loudness.gui")
    store = getattr(gui, "_settings", None)
    if store is not None:
        monkeypatch.setattr(store, "path", folder / gui.UPDATE_CONFIG.product / SETTINGS_NAME)
    return folder
