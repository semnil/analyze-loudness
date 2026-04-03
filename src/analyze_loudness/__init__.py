"""analyze-loudness: YouTube audio loudness analyzer (BS.1770 / EBU R128)."""

import subprocess
import sys

__version__ = "1.0.0"


def _subprocess_kwargs() -> dict:
    """Return extra kwargs for subprocess calls to hide console on Windows GUI."""
    if sys.platform == "win32" and getattr(sys, "frozen", False):
        si = subprocess.STARTUPINFO()
        si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        return {"startupinfo": si}
    return {}
