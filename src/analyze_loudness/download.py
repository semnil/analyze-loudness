"""Download audio via yt-dlp Python API and probe media info via ffprobe."""

from pathlib import Path

from analyze_common.download import (  # noqa: F401
    compute_middle,
    download_audio,
    is_url,
    sanitize_filename,
)
from analyze_common.ffmpeg import probe_info

# Local audio / video files the GUI offers in its file dialog and accepts by
# drag and drop.  ffmpeg decides what it can actually read.
AUDIO_EXTENSIONS = (
    ".wav", ".mp3", ".m4a", ".flac", ".ogg", ".opus",
    ".wma", ".aac", ".aiff", ".aif", ".webm", ".mkv", ".mp4",
)


def is_network_path(source: str) -> bool:
    r"""True for UNC and device paths (two leading slashes or backslashes, as in
    \\host\share, //host/share, \\?\ and \\.\).  These are refused before
    the path is resolved or opened: on Windows, resolving or opening one
    connects to the named host."""
    return source[:2].replace("/", "\\") == "\\\\"


def local_path(source: str) -> str:
    """Absolute path of a local source (``~`` expanded)."""
    return str(Path(source).expanduser().resolve())


def resolve_source(source: str, workdir: str) -> tuple[str, str]:
    """(audio path, title): downloads a URL, or uses a local file as-is.

    A local file's title is its name without the extension.
    """
    if is_url(source):
        return download_audio(source, workdir)
    if is_network_path(source):
        raise ValueError(f"Network (UNC) paths are not accepted: {source}")
    path = Path(local_path(source))
    if not path.is_file():
        raise FileNotFoundError(f"File not found: {source}")
    return str(path), path.stem


def probe_duration(path: str) -> float:
    """Return media duration in seconds via ffprobe."""
    _channels, duration_sec = probe_info(path)
    return duration_sec
