"""EBU R128 loudness analysis via ffmpeg ebur128 filter."""

import re
import subprocess

import numpy as np

from analyze_loudness import _ffmpeg_kwargs

SILENCE_THRESHOLD = -60


def run_ebur128(
    path: str,
    ss: float | None = None,
    duration: float | None = None,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, dict]:
    """Run ffmpeg ebur128 and return (time, momentary, short_term, summary).

    Parses per-frame lines emitted by the ebur128 filter and the final
    summary block.  All loudness values are in LUFS.
    """
    cmd = ["ffmpeg"]
    if ss is not None:
        cmd += ["-ss", str(ss)]
    cmd += ["-i", path]
    if duration is not None:
        cmd += ["-t", str(duration)]
    cmd += ["-af", "ebur128=peak=true", "-f", "null", "-"]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=600, **_ffmpeg_kwargs())
    warnings: list[str] = []
    if r.returncode != 0:
        import sys
        msg = f"ffmpeg exited with code {r.returncode}"
        print(f"[warn] {msg}", file=sys.stderr)
        warnings.append(msg)
    output = r.stderr

    # Per-frame pattern:  t: 1.234  TARGET:-23 LUFS  M: -20.1 S: -22.3
    # M/S may also be "-inf" or "nan" for silent frames.
    _num = r"-?(?:inf|nan|[\d.]+)"
    pattern = re.compile(
        rf"t:\s*([\d.]+)\s+TARGET.*?M:\s*({_num})\s+S:\s*({_num})"
    )
    rows = pattern.findall(output)
    if not rows:
        tail = "\n".join(output.splitlines()[-30:])
        raise RuntimeError(f"No ebur128 data parsed. Last 30 lines of ffmpeg output:\n{tail}")

    arr = np.array(rows, dtype=float)
    t, M, S = arr[:, 0], arr[:, 1], arr[:, 2]

    # Summary block (appears after the last frame).  Integrated / LRA can be
    # "-inf" when the source is silent; ``_num`` mirrors the per-frame regex.
    summary: dict[str, float] = {}
    summary_idx = output.rfind("Summary")
    if summary_idx != -1:
        summary_text = output[summary_idx:]
        m = re.search(rf"I:\s*({_num})\s*LUFS", summary_text)
        if m:
            summary["integrated"] = float(m.group(1))
        m = re.search(rf"LRA:\s*({_num})\s*LU", summary_text)
        if m:
            summary["lra"] = float(m.group(1))
        m = re.search(r"True peak:\s*\n\s*Peak:\s*(.*?)\s*dBFS", summary_text)
        if m:
            peaks = [float(v) for v in m.group(1).split() if v != "-inf"]
            summary["true_peak"] = max(peaks) if peaks else float("-inf")

    if warnings:
        summary["warnings"] = warnings
    return t, M, S, summary


def compute_stats(arr: np.ndarray, label: str, threshold: float = SILENCE_THRESHOLD) -> dict:
    """Compute descriptive statistics for a loudness array.

    Values at or below `threshold` are treated as silence and excluded.
    Returns None for numeric fields if all samples are below the threshold
    (NDJSON requires JSON-serializable values and NaN is not valid JSON).
    """
    v = arr[arr > threshold]
    # Drop non-finite entries (NaN, +inf, -inf) after the threshold cut so they
    # cannot poison median/percentile results.
    v = v[np.isfinite(v)]
    if len(v) == 0:
        return {
            "label": label,
            "median": None, "mean": None,
            "p10": None, "p90": None,
            "min": None, "max": None,
        }
    return {
        "label": label,
        "median": float(np.median(v)),
        "mean": float(np.mean(v)),
        "p10": float(np.percentile(v, 10)),
        "p90": float(np.percentile(v, 90)),
        "min": float(np.min(v)),
        "max": float(np.max(v)),
    }
