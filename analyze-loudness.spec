# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for analyze-loudness GUI application."""

import os

ROOT = os.path.abspath(".")

a = Analysis(
    ["src/analyze_loudness/gui.py"],
    pathex=[os.path.join(ROOT, "src")],
    binaries=[
        (os.path.join(ROOT, "build_assets/bin/ffmpeg.exe"), "bin"),
        (os.path.join(ROOT, "build_assets/bin/ffprobe.exe"), "bin"),
        (os.path.join(ROOT, "build_assets/bin/yt-dlp.exe"), "bin"),
        (os.path.join(ROOT, "build_assets/bin/deno.exe"), "bin"),
    ],
    datas=[
        (os.path.join(ROOT, "frontend"), "frontend"),
        (os.path.join(ROOT, "THIRD_PARTY_LICENSES.txt"), "."),
    ],
    hiddenimports=[
        "analyze_loudness",
        "analyze_loudness.analysis",
        "analyze_loudness.download",
        "analyze_loudness.gui",
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

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="analyze-loudness",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    icon=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="analyze-loudness",
)
