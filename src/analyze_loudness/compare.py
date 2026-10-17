"""Single-result documents, comparison documents, and truncated statistics.

A comparison holds 2-6 single results cut to the shortest track.  Statistics
over the cut range are derived from the stored series and never saved; the
GUI receives them from /compare and /load instead of computing them.
"""

import math
from datetime import datetime, timezone

import numpy as np

from analyze_loudness import SCHEMA_VERSION, __version__, _json_safe
from analyze_loudness.analysis import compute_silence_pct, compute_stats

MAX_TRACKS = 6
MIN_TRACKS = 2

GATE_ABSOLUTE = -70.0
GATE_RELATIVE_OFFSET = -10.0
GATE_BLOCK_SEC = 0.4


def _round1(v):
    return round(v, 1) if v is not None else None


def make_meta(source_url: str | None = None) -> dict:
    meta = {
        "schema_version": SCHEMA_VERSION,
        "version": __version__,
        "analyzed_at": datetime.now(timezone.utc).isoformat(),
    }
    if source_url is not None:
        meta["source_url"] = source_url
    return meta


def build_result(t, M, S, summary_raw: dict, title: str, url: str) -> dict:
    """Single-result document as served by /analyze and saved by the GUI."""
    st = compute_stats(S, "Short-term")
    mo = compute_stats(M, "Momentary")
    silence_pct = compute_silence_pct(t, S)
    result = {
        "meta": make_meta(url),
        "title": title,
        "summary": {
            "duration_sec": round(float(t[-1]), 1),
            "frames": len(t),
            "integrated": summary_raw.get("integrated"),
            "true_peak": summary_raw.get("true_peak"),
            "lra": summary_raw.get("lra"),
            "gate_threshold": _round1(summary_raw.get("gate_threshold")),
            "short_term": _stats_block(st),
            "momentary": _stats_block(mo),
            "silence_pct": round(silence_pct, 1),
        },
        "series": {
            "t": [round(float(v), 2) for v in t],
            "S": [round(float(v), 1) for v in S],
            "M": [round(float(v), 1) for v in M],
        },
    }
    return _json_safe(result)


def _stats_block(stats: dict) -> dict:
    return {k: _round1(stats[k]) for k in ("median", "mean", "p10", "p90")}


def is_compare(data) -> bool:
    return isinstance(data, dict) and "compare" in data


def validate_single(data) -> str | None:
    """Error message for a malformed single-result document, else None."""
    if not isinstance(data, dict):
        return "Invalid loudness JSON: expected an object"
    if "summary" not in data or "series" not in data:
        return "Invalid loudness JSON: missing summary or series"
    series = data["series"]
    if not isinstance(series, dict) or not all(
        isinstance(series.get(k), list) for k in ("t", "S", "M")
    ):
        return "Invalid loudness JSON: series must contain t, S, M arrays"
    if not (len(series["t"]) == len(series["S"]) == len(series["M"])):
        return "Invalid loudness JSON: series t/S/M length mismatch"
    meta = data.get("meta")
    if isinstance(meta, dict) and "schema_version" in meta:
        # bool is rejected explicitly because isinstance(True, int) is True.
        # An absent field is allowed for pre-schema JSON.
        sv = meta["schema_version"]
        if not isinstance(sv, int) or isinstance(sv, bool):
            return "Invalid loudness JSON: meta.schema_version must be an integer"
    return None


def _is_number(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def validate_tracks(tracks) -> str | None:
    """Error message when `tracks` cannot be compared, else None."""
    if not isinstance(tracks, list) or not (MIN_TRACKS <= len(tracks) <= MAX_TRACKS):
        return f"expected an array of {MIN_TRACKS}-{MAX_TRACKS} tracks"
    for i, track in enumerate(tracks):
        if is_compare(track):
            return f"Track {i + 1}: a comparison cannot be a track"
        err = validate_single(track)
        if err:
            return f"Track {i + 1}: {err}"
        t = track["series"]["t"]
        if not t:
            return f"Track {i + 1}: series has no frames"
        if not all(_is_number(x) for x in t):
            return f"Track {i + 1}: series.t must contain finite numbers"
    return None


def validate_compare(data) -> str | None:
    """Error message for a malformed comparison document, else None."""
    if not isinstance(data, dict):
        return "Invalid comparison JSON: expected an object"
    meta = data.get("meta")
    if isinstance(meta, dict) and "schema_version" in meta:
        sv = meta["schema_version"]
        if not isinstance(sv, int) or isinstance(sv, bool):
            return "Invalid comparison JSON: meta.schema_version must be an integer"
    comp = data.get("compare")
    if not isinstance(comp, dict):
        return "Invalid comparison JSON: compare must be an object"
    err = validate_tracks(comp.get("tracks"))
    if err:
        return f"Invalid comparison JSON: {err}"
    if len({len(tr["series"]["t"]) for tr in comp["tracks"]}) != 1:
        return "Invalid comparison JSON: tracks must have the same number of frames"
    return None


def first_gated_index(t) -> int:
    """First frame with a complete momentary window (gate.js _firstGatedIndex)."""
    if len(t) == 0:
        return 0
    frame = float(t[1] - t[0]) if len(t) > 1 else 0.0
    full = float(t[0]) + GATE_BLOCK_SEC - frame * 1.5
    i = 0
    while i < len(t) and t[i] < full:
        i += 1
    return i


def gated_integrated(M, t) -> float | None:
    """BS.1770 Integrated rebuilt from Momentary blocks, relative gate recomputed."""
    start = first_gated_index(t)
    blocks = [float(m) for m in M[start:]
              if m is not None and math.isfinite(m) and m > GATE_ABSOLUTE]
    if not blocks:
        return None
    rel = 10 * math.log10(sum(10 ** (m / 10) for m in blocks) / len(blocks)) + GATE_RELATIVE_OFFSET
    kept = [m for m in blocks if m > rel]
    if not kept:
        return None
    return 10 * math.log10(sum(10 ** (m / 10) for m in kept) / len(kept))


def common_frames(tracks: list[dict]) -> int:
    """Frame count every track keeps: up to the shortest track's last instant."""
    end = min(float(tr["series"]["t"][-1]) for tr in tracks)
    counts = []
    for tr in tracks:
        t = tr["series"]["t"]
        frame = float(t[1] - t[0]) if len(t) > 1 else 0.0
        counts.append(sum(1 for x in t if x <= end + frame / 2))
    return min(counts)


def truncate_track(track: dict, n: int) -> dict:
    out = dict(track)
    out["series"] = {k: list(track["series"][k][:n]) for k in ("t", "S", "M")}
    return out


def build_compare(tracks: list[dict]) -> dict:
    """Comparison document: each track cut to the shortest one."""
    if not (MIN_TRACKS <= len(tracks) <= MAX_TRACKS):
        raise ValueError(f"expected {MIN_TRACKS}-{MAX_TRACKS} tracks, got {len(tracks)}")
    n = common_frames(tracks)
    cut = [truncate_track(tr, n) for tr in tracks]
    return {
        "meta": make_meta(),
        "compare": {
            "truncate_sec": float(cut[0]["series"]["t"][-1]),
            "tracks": cut,
        },
    }


def _num_array(values) -> np.ndarray:
    """Non-numbers (null, strings, booleans) become NaN, which statistics treat as silence."""
    return np.array([float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else np.nan
                     for v in values], dtype=float)


def truncated_stats(track: dict) -> dict:
    """Statistics over a track's stored (already cut) series."""
    t = _num_array(track["series"]["t"])
    S = _num_array(track["series"]["S"])
    M = _num_array(track["series"]["M"])
    st = compute_stats(S, "Short-term")
    mo = compute_stats(M, "Momentary")
    return {
        "duration_sec": float(t[-1]),
        "frames": len(t),
        "integrated": gated_integrated(M.tolist(), t.tolist()),
        "short_term": {k: st[k] for k in ("median", "p10", "p90")},
        "momentary": {k: mo[k] for k in ("median", "p10", "p90")},
        "silence_pct": compute_silence_pct(t, S),
    }
