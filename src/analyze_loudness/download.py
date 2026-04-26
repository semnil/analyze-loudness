"""Download audio via yt-dlp Python API and probe media info via ffprobe."""

from analyze_common.download import (  # noqa: F401
    compute_middle,
    download_audio,
    sanitize_filename,
)
from analyze_common.ffmpeg import probe_info


def probe_duration(path: str) -> float:
    """Return media duration in seconds via ffprobe."""
    _channels, duration_sec = probe_info(path)
    return duration_sec
