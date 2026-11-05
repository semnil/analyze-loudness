"""The ffmpeg / ffprobe on PATH, read through the app's own parsers.

The input is a 1 kHz stereo sine written with numpy, so the expected values
come from BS.1770 rather than from any ffmpeg build: for a sine of peak A in
both channels, the integrated loudness is 10*log10(2 * A**2 / 2) LUFS, the
relative gate is 10 LU below it, and the true peak is 20*log10(A) dBTP.

With ``EXPECT_FFMPEG_DIR`` set (.github/workflows/ffmpeg-watch.yml and
release.yaml), the binaries in that directory go first on PATH, must be the ones found, and a
missing one fails the module instead of skipping it.
"""

import math
import os
import shutil
import struct
import wave
from pathlib import Path

import numpy as np
import pytest

from analyze_loudness import _find_executable as find_executable
from analyze_loudness.analysis import run_ebur128
from analyze_loudness.download import probe_duration

SAMPLE_RATE = 48000
SECONDS = 10
FREQUENCY = 1000
AMPLITUDE = 0.125
# ffmpeg prints the summary to one decimal place.
TOLERANCE = 0.1


@pytest.fixture(scope="module", autouse=True)
def _binaries():
    expected = os.environ.get("EXPECT_FFMPEG_DIR")
    if not expected:
        if find_executable("ffmpeg") is None or find_executable("ffprobe") is None:
            pytest.skip("ffmpeg / ffprobe not on PATH")
        yield
        return
    directory = Path(expected).resolve()
    patch = pytest.MonkeyPatch()
    patch.setenv("PATH", str(directory) + os.pathsep + os.environ.get("PATH", ""))
    try:
        for tool in ("ffmpeg", "ffprobe"):
            found = find_executable(tool)
            assert found is not None and Path(found).parent.resolve() == directory, (
                f"{tool} resolves to {found}, not to a file in {directory}")
        yield
    finally:
        patch.undo()


@pytest.fixture(scope="module")
def tone(tmp_path_factory):
    t = np.arange(SAMPLE_RATE * SECONDS) / SAMPLE_RATE
    pcm = np.round(AMPLITUDE * 32767 * np.sin(2 * math.pi * FREQUENCY * t)).astype("<i2")
    path = tmp_path_factory.mktemp("tone") / "tone.wav"
    with wave.open(str(path), "wb") as out:
        out.setnchannels(2)
        out.setsampwidth(2)
        out.setframerate(SAMPLE_RATE)
        out.writeframes(np.repeat(pcm, 2).tobytes())
    return str(path), int(np.max(np.abs(pcm))) / 32767


def test_ebur128_summary_matches_bs1770(tone):
    path, peak = tone
    integrated = 10 * math.log10(2 * peak ** 2 / 2)
    _, _, _, summary = run_ebur128(path)
    assert abs(summary["integrated"] - integrated) <= TOLERANCE
    assert abs(summary["gate_threshold"] - (integrated - 10)) <= TOLERANCE
    assert abs(summary["true_peak"] - 20 * math.log10(peak)) <= TOLERANCE
    assert "warnings" not in summary


def test_ebur128_frames_cover_the_file_every_100_ms(tone):
    t, M, S, _ = run_ebur128(tone[0])
    assert np.allclose(np.diff(t), 0.1, atol=1e-3)
    assert abs(t[-1] - SECONDS) <= 0.1
    assert len(M) == len(S) == len(t)


def test_ebur128_reads_a_file_with_a_non_ascii_name(tone, tmp_path):
    path, peak = tone
    renamed = tmp_path / "音源 テスト.wav"
    shutil.copyfile(path, renamed)
    _, _, _, summary = run_ebur128(str(renamed))
    assert abs(summary["true_peak"] - 20 * math.log10(peak)) <= TOLERANCE
    assert "warnings" not in summary


def test_ebur128_reads_a_file_with_a_tag_that_is_not_utf8(tone, tmp_path):
    path, peak = tone
    value = "日本語タイトル".encode("cp932") + b"\0"
    value += b"\0" * (len(value) % 2)
    info = b"INFO" + b"INAM" + struct.pack("<I", len(value)) + value
    riff = Path(path).read_bytes()[8:] + b"LIST" + struct.pack("<I", len(info)) + info
    tagged = tmp_path / "tagged.wav"
    tagged.write_bytes(b"RIFF" + struct.pack("<I", len(riff)) + riff)
    _, _, _, summary = run_ebur128(str(tagged))
    assert abs(summary["true_peak"] - 20 * math.log10(peak)) <= TOLERANCE
    assert "warnings" not in summary


def test_ebur128_failure_names_a_non_ascii_file_in_its_own_letters(tmp_path):
    broken = tmp_path / "音源 テスト.wav"
    broken.write_bytes(b"not audio")
    with pytest.raises(RuntimeError, match="音源 テスト"):
        run_ebur128(str(broken))


def test_ffprobe_reads_the_duration(tone):
    assert probe_duration(tone[0]) == pytest.approx(SECONDS, abs=1e-3)
