"""CLI entry point and main orchestration."""

import argparse
import math
import shutil
import tempfile
from pathlib import Path

import numpy as np

from analyze_loudness.download import download_audio, probe_duration, compute_middle, sanitize_filename
from analyze_loudness.analysis import run_ebur128, compute_stats
from analyze_loudness.plot import plot_analysis


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
    parser.add_argument("url", help="YouTube video URL")
    parser.add_argument(
        "--duration", type=_positive_float, default=None,
        help="Minutes to extract from the middle (default: full duration)",
    )
    parser.add_argument(
        "--output-dir", default=".",
        help="Directory for output files (default: current directory)",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    if not shutil.which("ffmpeg"):
        import static_ffmpeg
        static_ffmpeg.add_paths()
    args = parse_args(argv)
    outdir = Path(args.output_dir).resolve()
    outdir.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="loudness_") as workdir:
        # Step 1: Download audio
        print(f"[1/3] Downloading audio: {args.url}")
        src, title = download_audio(args.url, workdir)
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
    silence_pct = (np.sum(np.isnan(S) | (S < -40)) / len(S) * 100) if len(S) else 0.0

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
