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
        assert args.url == "https://example.com"
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
