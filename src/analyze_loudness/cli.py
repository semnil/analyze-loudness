"""CLI entry point and main orchestration."""

import argparse
import json
import math
import shutil
import tempfile
from pathlib import Path


from analyze_loudness import _json_safe
from analyze_loudness.download import (
    compute_middle, is_url, probe_duration, resolve_source, sanitize_filename,
)
from analyze_loudness.analysis import run_ebur128, compute_stats, compute_silence_pct
from analyze_loudness.compare import (
    MAX_TRACKS, build_compare, build_result, is_compare, truncated_stats, validate_single,
    validate_tracks,
)
from analyze_loudness.plot import plot_analysis, plot_compare


def _positive_float(value: str) -> float:
    f = float(value)
    if not math.isfinite(f) or f <= 0:
        raise argparse.ArgumentTypeError(f"must be a positive finite number, got {value}")
    if f > 240:
        raise argparse.ArgumentTypeError("duration must be <= 240 minutes")
    return f


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Download a YouTube video and analyze its loudness (BS.1770 / EBU R128)",
    )
    parser.add_argument(
        "sources", nargs="+",
        help=f"YouTube video URL or local audio file.  2-{MAX_TRACKS} sources compare "
             "them; a comparison also accepts single results saved as .json",
    )
    parser.add_argument(
        "--duration", type=_positive_float, default=None,
        help="Minutes to extract from the middle (default: full duration; single source only)",
    )
    parser.add_argument(
        "--output-dir", default=".",
        help="Directory for output files (default: current directory)",
    )
    args = parser.parse_args(argv)
    if len(args.sources) > MAX_TRACKS:
        parser.error(f"at most {MAX_TRACKS} sources can be compared")
    if len(args.sources) > 1 and args.duration is not None:
        parser.error("--duration cannot be used with a comparison")
    if len(args.sources) == 1 and _is_json_source(args.sources[0]):
        parser.error("a saved .json result can only be used in a comparison (2 or more sources)")
    return args


def _is_json_source(source: str) -> bool:
    return (not source.startswith(("http://", "https://"))
            and source.lower().endswith(".json"))


def main(argv: list[str] | None = None) -> None:
    if not shutil.which("ffmpeg"):
        import static_ffmpeg
        static_ffmpeg.add_paths()
    args = parse_args(argv)
    outdir = Path(args.output_dir).resolve()
    outdir.mkdir(parents=True, exist_ok=True)
    if len(args.sources) > 1:
        _run_compare(args.sources, outdir)
        return
    url = args.sources[0]

    with tempfile.TemporaryDirectory(prefix="loudness_") as workdir:
        # Step 1: Download audio (or use the local file)
        print(f"[1/3] {'Downloading audio' if is_url(url) else 'Reading file'}: {url}")
        src, title = _resolve(url, workdir)
        print(f"       -> {title}")

        # Step 2: EBU R128 analysis
        ss, dur = None, None
        if args.duration is not None:
            total_sec = probe_duration(src)
            ss, dur, info_msg = compute_middle(total_sec, args.duration)
            print(info_msg)
        print("[2/3] Running EBU R128 loudness analysis...")
        t, M, S, summary = run_ebur128(src, ss=ss, duration=dur)

    # Step 3: Summary + plot
    st = compute_stats(S, "Short-term")
    mo = compute_stats(M, "Momentary")
    silence_pct = compute_silence_pct(t, S)

    dur_label = f"_{int(args.duration)}m" if args.duration is not None else ""
    label = f"{title}{dur_label}"
    safe_name = f"{sanitize_filename(title)}{dur_label}"
    print()
    print("=" * 56)
    print(f"  {label}")
    print("=" * 56)
    def _fmt(x):
        return "N/A" if x is None else f"{x:.1f}"

    print(f"  Duration          : {t[-1] / 60:.1f} min ({len(t)} frames)")
    print(f"  Integrated        : {summary.get('integrated', '?')} LUFS")
    print(f"  True Peak (max)   : {summary.get('true_peak', '?')} dBFS")
    print(f"  LRA               : {summary.get('lra', '?')} LU")
    print(f"  Short-term median : {_fmt(st['median'])} LUFS")
    print(f"  Short-term P10/P90: {_fmt(st['p10'])} / {_fmt(st['p90'])} LUFS")
    print(f"  Momentary  median : {_fmt(mo['median'])} LUFS")
    print(f"  Momentary  P10/P90: {_fmt(mo['p10'])} / {_fmt(mo['p90'])} LUFS")
    print(f"  Silence (S<-40)   : {silence_pct:.1f}%")
    print("=" * 56)

    png_path = str(outdir / f"{safe_name}_loudness.png")
    print(f"\n[3/3] Generating plot...")
    plot_analysis(t, M, S, summary, label, png_path)

    print(f"\n[done] Plot : {png_path}")


def _load_track(source: str) -> dict:
    try:
        data = json.loads(Path(source).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        raise SystemExit(f"error: cannot read {source}: {e}")
    if is_compare(data):
        raise SystemExit(f"error: {source} is a comparison; pass single results")
    err = validate_single(data)
    if err:
        raise SystemExit(f"error: {source}: {err}")
    return data


def _resolve(source: str, workdir: str) -> tuple[str, str]:
    try:
        return resolve_source(source, workdir)
    except (FileNotFoundError, ValueError) as e:
        raise SystemExit(f"error: {e}")


def _analyze_track(url: str) -> dict:
    with tempfile.TemporaryDirectory(prefix="loudness_") as workdir:
        src, title = _resolve(url, workdir)
        print(f"       -> {title}")
        t, M, S, summary = run_ebur128(src)
    for w in summary.pop("warnings", []):
        print(f"       [warn] {w}")
    return build_result(t, M, S, summary, title, url if is_url(url) else src)


def _unique_stem(outdir: Path, stem: str) -> str:
    """First of stem, stem_2, stem_3, ... with neither .json nor .png taken."""
    n, candidate = 1, stem
    while (outdir / f"{candidate}.json").exists() or (outdir / f"{candidate}.png").exists():
        n += 1
        candidate = f"{stem}_{n}"
    return candidate


def _run_compare(sources: list[str], outdir: Path) -> None:
    tracks = []
    for i, source in enumerate(sources):
        print(f"[{i + 1}/{len(sources)}] {source}")
        tracks.append(_load_track(source) if _is_json_source(source) else _analyze_track(source))
    err = validate_tracks(tracks)
    if err:
        raise SystemExit(f"error: {err}")

    doc = build_compare(tracks)
    cut = doc["compare"]["tracks"]
    stats = [truncated_stats(track) for track in cut]

    def _fmt(x, sign=""):
        return "N/A" if x is None else f"{x:{sign}.1f}"

    print()
    print(f"Comparison: first {doc['compare']['truncate_sec'] / 60:.1f} min of each track "
          "(True Peak / LRA / full Integrated: whole track)")
    rows = [
        ("Integrated", lambda track, st: _fmt(st["integrated"])),
        ("Integrated (full)", lambda track, st: _fmt(track["summary"].get("integrated"))),
        ("True Peak (full)", lambda track, st: _fmt(track["summary"].get("true_peak"), "+")),
        ("LRA (full)", lambda track, st: _fmt(track["summary"].get("lra"))),
        ("S-term median", lambda track, st: _fmt(st["short_term"]["median"])),
        ("S-term P10/P90", lambda track, st: f"{_fmt(st['short_term']['p10'])}/{_fmt(st['short_term']['p90'])}"),
        ("Mom. median", lambda track, st: _fmt(st["momentary"]["median"])),
        ("Mom. P10/P90", lambda track, st: f"{_fmt(st['momentary']['p10'])}/{_fmt(st['momentary']['p90'])}"),
        ("Silence %", lambda track, st: _fmt(st["silence_pct"])),
    ]
    print(f"  {'':18}" + "".join(f"{'#' + str(i + 1):>14}" for i in range(len(cut))))
    for label, get in rows:
        print(f"  {label:18}" + "".join(f"{get(track, st):>14}" for track, st in zip(cut, stats)))
    for i, track in enumerate(cut):
        print(f"  #{i + 1}: {track.get('title') or 'untitled'}")

    stem = _unique_stem(outdir, "loudness_compare")
    json_path = outdir / f"{stem}.json"
    json_path.write_text(
        json.dumps(_json_safe(doc), indent=2, ensure_ascii=False, allow_nan=False),
        encoding="utf-8",
    )
    png_path = str(outdir / f"{stem}.png")
    plot_compare(doc, stats, png_path)
    print(f"\n[done] JSON : {json_path}")
    print(f"[done] Plot : {png_path}")
