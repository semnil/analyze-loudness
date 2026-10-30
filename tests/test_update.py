"""Tests for analyze_loudness.update and the files that must agree with it."""

import base64
import re
from pathlib import Path

from analyze_loudness import __version__
from analyze_loudness.update import PUBLIC_KEY, UPDATE_CONFIG

ROOT = Path(__file__).resolve().parent.parent


def test_config_identifies_this_app():
    assert UPDATE_CONFIG.product == "analyze-loudness"
    assert UPDATE_CONFIG.repo == "semnil/analyze-loudness"
    assert UPDATE_CONFIG.current_version == __version__
    assert UPDATE_CONFIG.manifest_url == \
        "https://github.com/semnil/analyze-loudness/releases/latest/download/latest.json"


def test_public_key_is_an_ed25519_key():
    assert len(base64.b64decode(PUBLIC_KEY, validate=True)) == 32


def test_temp_prefix_is_covered_by_the_orphan_sweep():
    # gui._cleanup_orphan_tempdirs removes loudness_* directories.
    assert UPDATE_CONFIG.temp_prefix.startswith("loudness_")


def test_installer_waits_on_the_apps_mutex():
    import importlib.util
    spec = importlib.util.spec_from_file_location("_build", ROOT / "build.py")
    build = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(build)
    installer_script = (ROOT / "installer.iss").read_text(encoding="utf-8")
    assert build._read_mutex_name() == UPDATE_CONFIG.mutex_name == "com.semnil.loudness-analyzer"
    assert "/DMyAppMutex={_read_mutex_name()}" in (ROOT / "build.py").read_text(encoding="utf-8")
    assert "#ifndef MyAppMutex" in installer_script
    assert '#include "vendor\\py-analyze-common\\installer\\auto_update.iss"' in installer_script
    assert (ROOT / "vendor/py-analyze-common/installer/auto_update.iss").is_file()


def test_installer_args_reach_the_include():
    from analyze_common.update import INSTALLER_ARGS
    include = (ROOT / "vendor/py-analyze-common/installer/auto_update.iss").read_text(encoding="utf-8")
    assert "/UPDATE=1" in INSTALLER_ARGS.split()
    assert "{param:UPDATE|0}" in include


def test_bundle_carries_the_update_code_and_assets():
    spec = (ROOT / "analyze-loudness.spec").read_text(encoding="utf-8")
    from analyze_common.server import GuiHandler
    from analyze_common.web import SETTINGS_JS
    for path in [SETTINGS_JS] + [path for path, _ in GuiHandler._SHARED_ASSETS.values()]:
        assert f"vendor/py-analyze-common/src/analyze_common/web/{path.name}" in spec
    for module in ("analyze_loudness.update", "analyze_common.update", "analyze_common.ed25519",
                   "analyze_common.settings", "analyze_common.server", "analyze_common.window", "certifi"):
        assert f'"{module}"' in spec


def test_certifi_is_a_gui_dependency():
    import certifi
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    gui = re.search(r"^gui = \[(.*)\]$", pyproject, re.M).group(1)
    assert '"certifi"' in gui
    assert Path(certifi.where()).is_file()


def test_release_signs_the_assets_it_publishes():
    workflow = (ROOT / ".github/workflows/release.yaml").read_text(encoding="utf-8")
    build = (ROOT / "build.py").read_text(encoding="utf-8")
    assert "--config analyze_loudness.update:UPDATE_CONFIG" in workflow
    assert "secrets.UPDATE_SIGNING_KEY" in workflow
    assert "darwin-aarch64=artifacts/Loudness-Analyzer.dmg" in workflow
    assert '"Loudness-Analyzer.dmg"' in build
    assert "artifacts/latest.json" in workflow.split("files: |", 1)[1]
