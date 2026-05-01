"""analyze-loudness: YouTube audio loudness analyzer (BS.1770 / EBU R128)."""

import sys
from pathlib import Path

_VENDOR = Path(__file__).resolve().parents[2] / "vendor" / "py-analyze-common" / "src"
if _VENDOR.is_dir() and str(_VENDOR) not in sys.path:
    sys.path.insert(0, str(_VENDOR))

from analyze_common.ffmpeg import ffmpeg_kwargs as _ffmpeg_kwargs  # noqa: E402,F401
from analyze_common.json_util import json_safe as _json_safe  # noqa: E402,F401

__version__ = "1.3.0"

SCHEMA_VERSION = 1
