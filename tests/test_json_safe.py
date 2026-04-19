"""Tests for _json_safe utility (V-04)."""

import math

import pytest

from analyze_loudness import _json_safe


class TestJsonSafe:
    """V-04: Recursive NaN/Inf sanitization."""

    def test_finite_float_unchanged(self):
        assert _json_safe(3.14) == 3.14

    def test_nan_replaced(self):
        assert _json_safe(float("nan")) is None

    def test_inf_replaced(self):
        assert _json_safe(float("inf")) is None

    def test_neg_inf_replaced(self):
        assert _json_safe(float("-inf")) is None

    def test_nested_dict(self):
        data = {"a": {"b": float("nan"), "c": 1.0}}
        result = _json_safe(data)
        assert result["a"]["b"] is None
        assert result["a"]["c"] == 1.0

    def test_nested_list(self):
        data = [1.0, [float("inf"), 2.0], float("-inf")]
        result = _json_safe(data)
        assert result == [1.0, [None, 2.0], None]

    def test_tuple_converted_to_list(self):
        data = (float("nan"), 1.0)
        result = _json_safe(data)
        assert result == [None, 1.0]

    def test_non_float_unchanged(self):
        assert _json_safe("hello") == "hello"
        assert _json_safe(42) == 42
        assert _json_safe(True) is True
        assert _json_safe(None) is None

    def test_complex_nested_structure(self):
        """Realistic result structure with NaN in series."""
        data = {
            "summary": {
                "integrated": float("nan"),
                "true_peak": float("-inf"),
                "lra": 5.2,
            },
            "series": {
                "S": [float("nan"), -20.0, float("inf")],
                "M": [-18.0, -19.0],
            },
        }
        result = _json_safe(data)
        assert result["summary"]["integrated"] is None
        assert result["summary"]["true_peak"] is None
        assert result["summary"]["lra"] == 5.2
        assert result["series"]["S"] == [None, -20.0, None]
        assert result["series"]["M"] == [-18.0, -19.0]

    def test_empty_structures(self):
        assert _json_safe({}) == {}
        assert _json_safe([]) == []
        assert _json_safe(()) == []
