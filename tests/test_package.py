"""Tests for the package's import-time setup."""

import importlib.util
import sys

import analyze_loudness


def _run_init(monkeypatch):
    spec = importlib.util.spec_from_file_location("analyze_loudness_reexecuted", analyze_loudness.__file__)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_vendor_path_is_not_added_twice(monkeypatch):
    vendor = str(analyze_loudness._VENDOR)
    assert vendor in sys.path
    monkeypatch.setattr(sys, "path", list(sys.path))
    _run_init(monkeypatch)
    assert sys.path.count(vendor) == 1


def test_vendor_path_is_added_when_missing(monkeypatch):
    vendor = str(analyze_loudness._VENDOR)
    monkeypatch.setattr(sys, "path", [p for p in sys.path if p != vendor])
    _run_init(monkeypatch)
    assert sys.path[0] == vendor
