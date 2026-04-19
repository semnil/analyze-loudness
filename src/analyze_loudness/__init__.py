"""analyze-loudness: YouTube audio loudness analyzer (BS.1770 / EBU R128)."""

import math
import os
import sys
from pathlib import Path

# Make the py-desktop-app-common submodule importable as `desktop_app_common`.
_VENDOR = Path(__file__).resolve().parents[2] / "vendor" / "py-desktop-app-common" / "src"
if _VENDOR.is_dir() and str(_VENDOR) not in sys.path:
    sys.path.insert(0, str(_VENDOR))

from desktop_app_common.platform import subprocess_kwargs as _subprocess_kwargs  # noqa: E402,F401


def _ffmpeg_kwargs() -> dict:
    """Return subprocess kwargs with LC_ALL=C for ffmpeg / ffprobe.

    ffmpeg / ffprobe stderr / stdout parsers in this package assume '.' as
    the decimal separator.  Non-C locales can substitute ',' and break the
    regexes.  Apply unconditionally so every ffmpeg / ffprobe invocation is
    robust, not just the ebur128 one.
    """
    kwargs = dict(_subprocess_kwargs())
    env = dict(kwargs["env"]) if "env" in kwargs else os.environ.copy()
    env["LC_ALL"] = "C"
    env["LANG"] = "C"
    kwargs["env"] = env
    return kwargs


__version__ = "1.1.4"

# Result JSON schema version.  Bump when the shape of /analyze output or
# saved JSON files changes in a way that frontends must reason about.
SCHEMA_VERSION = 1


def _json_safe(value):
    """Recursively replace non-finite floats (NaN, inf, -inf) with None.

    JSON (and thus NDJSON) does not support NaN/Infinity; ``JSON.parse`` on
    the frontend rejects them.  This helper walks dicts / lists / tuples and
    normalizes every non-finite float to ``None`` before ``json.dumps``.
    """
    # bool is a subclass of int; keep it as-is so JSON emits true/false
    # rather than coercing it to a float branch below.
    if isinstance(value, bool):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, dict):
        return {k: _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    return value
