"""Tests for analyze_loudness.cli module."""

import argparse

import pytest

from analyze_loudness.cli import parse_args, _positive_float


class TestPositiveFloat:
    def test_valid_positive(self):
        assert _positive_float("5.0") == 5.0
        assert _positive_float("0.1") == 0.1

    def test_zero_raises(self):
        with pytest.raises(argparse.ArgumentTypeError, match="positive"):
            _positive_float("0")

    def test_negative_raises(self):
        with pytest.raises(argparse.ArgumentTypeError, match="positive"):
            _positive_float("-5")

    def test_non_numeric_raises(self):
        with pytest.raises(ValueError):
            _positive_float("abc")


class TestParseArgs:
    def test_url_only(self):
        args = parse_args(["https://example.com"])
        assert args.sources == ["https://example.com"]
        assert args.duration is None
        assert args.output_dir == "."

    def test_with_duration(self):
        args = parse_args(["https://example.com", "--duration", "10"])
        assert args.duration == 10.0

    def test_with_output_dir(self):
        args = parse_args(["https://example.com", "--output-dir", "/tmp/out"])
        assert args.output_dir == "/tmp/out"

    def test_missing_url_exits(self):
        with pytest.raises(SystemExit):
            parse_args([])

    def test_invalid_duration_exits(self):
        with pytest.raises(SystemExit):
            parse_args(["https://example.com", "--duration", "-1"])


class TestPositiveFloatBoundary:
    """Extended boundary tests for _positive_float."""

    def test_infinity_raises(self):
        with pytest.raises(argparse.ArgumentTypeError, match="positive finite"):
            _positive_float("inf")

    def test_negative_infinity_raises(self):
        with pytest.raises(argparse.ArgumentTypeError, match="positive finite"):
            _positive_float("-inf")

    def test_nan_raises(self):
        with pytest.raises(argparse.ArgumentTypeError, match="positive finite"):
            _positive_float("nan")

    def test_very_small_positive_accepted(self):
        assert _positive_float("0.001") == pytest.approx(0.001)

    def test_upper_bound_accepted(self):
        assert _positive_float("240") == pytest.approx(240.0)

    def test_above_upper_bound_raises(self):
        with pytest.raises(argparse.ArgumentTypeError, match="240"):
            _positive_float("1e9")


def _single(n_frames, title):
    t = [round(0.1 * (i + 1), 2) for i in range(n_frames)]
    return {
        "meta": {"schema_version": 2, "source_url": f"https://example.com/{title}"},
        "title": title,
        "summary": {"integrated": -20.0, "true_peak": -1.0, "lra": 5.0, "gate_threshold": -30.0},
        "series": {"t": t, "S": [-20.0] * n_frames, "M": [-21.0] * n_frames},
    }


class TestCompareArgs:
    def test_several_sources(self):
        args = parse_args(["https://a", "b.json", "https://c"])
        assert args.sources == ["https://a", "b.json", "https://c"]

    def test_too_many_sources_exits(self):
        with pytest.raises(SystemExit):
            parse_args([f"https://x/{i}" for i in range(7)])

    def test_duration_with_comparison_exits(self):
        with pytest.raises(SystemExit):
            parse_args(["https://a", "https://b", "--duration", "5"])

    def test_single_json_exits(self):
        with pytest.raises(SystemExit):
            parse_args(["result.json"])

    def test_url_ending_in_json_is_a_url(self):
        args = parse_args(["https://example.com/feed.json"])
        assert args.sources == ["https://example.com/feed.json"]


class TestCompareRun:
    def _write(self, tmp_path, name, doc):
        import json
        f = tmp_path / name
        f.write_text(json.dumps(doc), encoding="utf-8")
        return str(f)

    def test_json_sources_write_comparison(self, tmp_path):
        import json
        from analyze_loudness.cli import main
        a = self._write(tmp_path, "a.json", _single(600, "a"))
        b = self._write(tmp_path, "b.json", _single(400, "b"))
        out = tmp_path / "out"
        main([a, b, "--output-dir", str(out)])
        doc = json.loads((out / "loudness_compare.json").read_text(encoding="utf-8"))
        assert doc["meta"]["schema_version"] == 3
        assert [len(tr["series"]["t"]) for tr in doc["compare"]["tracks"]] == [400, 400]
        assert (out / "loudness_compare.png").stat().st_size > 0

        main([a, b, "--output-dir", str(out)])
        assert (out / "loudness_compare_2.json").exists()
        assert (out / "loudness_compare_2.png").exists()

    def test_comparison_json_rejected_as_source(self, tmp_path):
        from analyze_loudness.cli import main
        from analyze_loudness.compare import build_compare
        a = self._write(tmp_path, "a.json", _single(50, "a"))
        cmp = self._write(tmp_path, "c.json", build_compare([_single(50, "x"), _single(40, "y")]))
        with pytest.raises(SystemExit, match="comparison"):
            main([a, cmp, "--output-dir", str(tmp_path / "out")])

    def test_invalid_json_source_rejected(self, tmp_path):
        from analyze_loudness.cli import main
        a = self._write(tmp_path, "a.json", _single(50, "a"))
        bad = self._write(tmp_path, "bad.json", {"title": "x"})
        with pytest.raises(SystemExit, match="summary or series"):
            main([a, bad, "--output-dir", str(tmp_path / "out")])
