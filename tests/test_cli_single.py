"""Single-source CLI analysis with real local audio and its output figure."""

import wave
from unittest.mock import patch

import numpy as np
import pytest
from PIL import Image

from analyze_loudness import cli


@pytest.mark.parametrize("duration, expected_start, expected_duration", [(None, None, None), (0.05, 1.0, 3.0)])
def test_single_audio_analysis_writes_plot(tmp_path, capsys, duration, expected_start, expected_duration):
    source = tmp_path / "tone.wav"
    rate = 48000
    samples = (np.sin(2 * np.pi * 1000 * np.arange(rate * 5) / rate) * 10000).astype("<i2")
    with wave.open(str(source), "wb") as audio:
        audio.setparams((1, 2, rate, 0, "NONE", "not compressed"))
        audio.writeframes(samples.tobytes())
    out = tmp_path / "out"
    args = [str(source), "--output-dir", str(out)]
    if duration is not None:
        args += ["--duration", str(duration)]
    with patch.object(cli, "run_ebur128", wraps=cli.run_ebur128) as run:
        cli.main(args)
    run.assert_called_once_with(str(source.resolve()), ss=expected_start, duration=expected_duration)
    filename = "tone_loudness.png" if duration is None else "tone_0m_loudness.png"
    with Image.open(out / filename) as image:
        image.verify()
    output = capsys.readouterr().out
    assert "Short-term median" in output
    assert "Silence (S<-40)" in output
    assert "[done] Plot" in output


@pytest.mark.parametrize("contents", [None, "{broken"])
def test_unreadable_saved_track_does_not_create_comparison(tmp_path, contents):
    source = tmp_path / "saved.json"
    if contents is not None:
        source.write_text(contents, encoding="utf-8")
    out = tmp_path / "out"
    with pytest.raises(SystemExit, match="cannot read"):
        cli.main([str(source), str(source), "--output-dir", str(out)])
    assert list(out.iterdir()) == []
