# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for analyze-loudness GUI application."""

import os
import sys

ROOT = os.path.abspath(".")
IS_WINDOWS = sys.platform == "win32"
IS_MAC = sys.platform == "darwin"

_EXE = ".exe" if IS_WINDOWS else ""
_BINARIES = [
    (os.path.join(ROOT, f"build_assets/bin/ffmpeg{_EXE}"), "bin"),
    (os.path.join(ROOT, f"build_assets/bin/ffprobe{_EXE}"), "bin"),
    (os.path.join(ROOT, f"build_assets/bin/deno{_EXE}"), "bin"),
]

a = Analysis(
    ["src/analyze_loudness/gui.py"],
    pathex=[
        os.path.join(ROOT, "src"),
        os.path.join(ROOT, "vendor/py-desktop-app-common/src"),
    ],
    binaries=_BINARIES,
    datas=[
        (os.path.join(ROOT, "frontend"), "frontend"),
        (os.path.join(ROOT, "THIRD_PARTY_LICENSES.txt"), "."),
    ],
    hiddenimports=[
        "analyze_loudness",
        "analyze_loudness.analysis",
        "analyze_loudness.download",
        "analyze_loudness.gui",
        "desktop_app_common",
        "desktop_app_common.platform",
        "desktop_app_common.theme",
        "desktop_app_common.assets",
        "webview",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "matplotlib",
        "tkinter",
        "static_ffmpeg",
        "aws_sam_cli",
        "awscli",
        "botocore",
        "pytest",
        "cryptography",
    ],
    noarchive=False,
)

pyz = PYZ(a.pure)

_ICON = None
if IS_WINDOWS and os.path.exists(os.path.join(ROOT, "build_assets/icon.ico")):
    _ICON = os.path.join(ROOT, "build_assets/icon.ico")
elif IS_MAC and os.path.exists(os.path.join(ROOT, "build_assets/icon.icns")):
    _ICON = os.path.join(ROOT, "build_assets/icon.icns")

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="analyze-loudness",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=not IS_MAC,
    console=False,
    icon=_ICON,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=not IS_MAC,
    upx_exclude=[],
    name="analyze-loudness",
)

if IS_MAC:
    app = BUNDLE(
        coll,
        name="Loudness Analyzer.app",
        icon=_ICON,
        bundle_identifier="com.semnil.loudness-analyzer",
        version="1.1.4",
        info_plist={
            "CFBundleName": "Loudness Analyzer",
            "CFBundleDisplayName": "Loudness Analyzer",
            "CFBundleShortVersionString": "1.1.4",
            "CFBundleVersion": "1.1.4",
            "LSMinimumSystemVersion": "11.0",
            "NSHighResolutionCapable": True,
            "LSEnvironment": {"PYTHONIOENCODING": "utf-8"},
        },
    )
