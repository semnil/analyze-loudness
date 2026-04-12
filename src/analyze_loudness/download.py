"""Download audio via yt-dlp Python API and probe media info via ffprobe."""

import json
import re
import subprocess
from pathlib import Path

from yt_dlp import YoutubeDL

from analyze_loudness import _subprocess_kwargs


def _run(cmd: list[str]) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(cmd, check=True, capture_output=True, text=True,
                              **_subprocess_kwargs())
    except subprocess.CalledProcessError as e:
        stderr_tail = (e.stderr or "")[-500:]
        raise RuntimeError(f"{cmd[0]} failed (exit {e.returncode}): {stderr_tail}") from e


def probe_duration(path: str) -> float:
    """Return media duration in seconds via ffprobe."""
    r = _run([
        "ffprobe", "-v", "quiet",
        "-print_format", "json",
        "-show_format", path,
    ])
    info = json.loads(r.stdout)
    dur = info.get("format", {}).get("duration")
    if dur is None:
        raise RuntimeError(f"ffprobe could not determine duration for: {path}")
    return float(dur)


def sanitize_filename(name: str) -> str:
    """Remove or replace characters that are unsafe for filenames."""
    name = re.sub(r'[\\/:*?"<>|]', "_", name)
    name = name.strip(". ")
    return name[:200] if name else "untitled"


def download_audio(url: str, workdir: str) -> tuple[str, str]:
    """Download audio track via yt-dlp Python API and return (file_path, title)."""
    template = str(Path(workdir) / "%(id)s.%(ext)s")
    opts = {
        "format": "bestaudio/best",
        "outtmpl": template,
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "postprocessors": [{
            "key": "FFmpegExtractAudio",
            "preferredcodec": "opus",
            "preferredquality": "0",
        }],
    }
    try:
        with YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=True)
    except Exception as e:
        raise RuntimeError(f"yt-dlp failed: {e}") from e

    title = (info or {}).get("title") or "Untitled"
    files = [f for f in Path(workdir).iterdir() if f.is_file()]
    if files:
        return str(files[0]), title
    raise FileNotFoundError("yt-dlp produced no audio file")


def compute_middle(total_sec: float, duration_min: float) -> tuple[float, float, str]:
    """Return (start_sec, extract_sec, info_message) for the middle segment."""
    extract_sec = duration_min * 60
    if total_sec <= extract_sec:
        msg = f"[info] Source shorter than {duration_min}m -- using full duration ({total_sec:.0f}s)"
        return 0.0, total_sec, msg
    start = (total_sec - extract_sec) / 2
    msg = f"[info] Total {total_sec:.0f}s -> extracting {start:.0f}s - {start + extract_sec:.0f}s"
    return start, extract_sec, msg
