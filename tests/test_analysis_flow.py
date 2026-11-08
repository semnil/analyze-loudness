"""Analysis, streaming and cache contracts through the GUI's HTTP endpoint."""

import http.client
import json
import os
import subprocess
import threading
from collections import OrderedDict
from http.server import HTTPServer
from pathlib import Path
from unittest.mock import Mock

import numpy as np
import pytest

from analyze_loudness import gui


@pytest.fixture
def analysis_app(tmp_path, monkeypatch):
    monkeypatch.setattr(gui, "_cache_dir", str(tmp_path))
    monkeypatch.setattr(gui, "_result_cache", OrderedDict())
    monkeypatch.setattr(gui, "_loaded_cache_data", OrderedDict())
    monkeypatch.setattr(gui, "_cache_seq", 0)
    monkeypatch.setattr(gui, "_speed_factor", 50.0)
    server = HTTPServer(("127.0.0.1", 0), gui.AnalyzeHandler)
    yield server
    server.server_close()


def analyze(server, source, duration=None):
    thread = threading.Thread(target=server.handle_request)
    thread.start()
    connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=5)
    try:
        connection.request("POST", "/analyze", json.dumps({"url": source, "duration": duration}),
                           {"Content-Type": "application/json"})
        response = connection.getresponse()
        assert response.status == 200
        assert response.getheader("Content-Type") == "application/x-ndjson"
        return [json.loads(line) for line in response.read().splitlines()]
    finally:
        connection.close()
        thread.join(timeout=5)
        assert not thread.is_alive()


def fake_analysis(monkeypatch, summary=None):
    resolve = Mock(return_value=("download.opus", "Clip"))
    run = Mock(return_value=(np.arange(1, 33) * 0.1,
                            np.array([-120.7] * 3 + [-22.0] * 29),
                            np.array([-120.7] * 29 + [-20, -30, -50]),
                            summary or {"integrated": -22, "true_peak": -1, "lra": 4}))
    monkeypatch.setattr(gui, "resolve_source", resolve)
    monkeypatch.setattr(gui, "probe_duration", Mock(return_value=180.0))
    monkeypatch.setattr(gui, "run_ebur128", run)
    return resolve, run


def test_analysis_with_no_length_to_extract_takes_the_probed_length(analysis_app, monkeypatch):
    _, run = fake_analysis(monkeypatch)
    monkeypatch.setattr(gui, "compute_middle", Mock(return_value=(None, None, "using full duration")))
    events = analyze(analysis_app, "https://example.com/audio", 5)
    progress = [event for event in events if event["type"] == "progress"]
    assert progress[2]["duration_sec"] == 180
    assert events[-1]["type"] == "result"
    run.assert_called_once_with("download.opus", ss=None, duration=None)


def test_analysis_emits_result_then_reuses_disk_cache(analysis_app, monkeypatch):
    resolve, run = fake_analysis(monkeypatch, {"integrated": -22, "warnings": ["partial audio"]})
    monkeypatch.setattr(gui.time, "monotonic", Mock(side_effect=[100.0, 102.0]))
    source = "https://example.com/audio"
    events = analyze(analysis_app, source, 1)
    progress = [event for event in events if event["type"] == "progress"]
    assert [event["stage"] for event in progress] == ["download", "download", "analyze", "stats"]
    assert progress[2]["duration_sec"] == 60
    assert progress[2]["estimate_sec"] == 1
    assert {"type": "warning", "message": "partial audio"} in events
    result = events[-1]["data"]
    assert events[-1]["type"] == "result"
    assert result["title"] == "Clip"
    assert result["summary"]["short_term"]["median"] == -30
    assert result["summary"]["silence_pct"] == pytest.approx(33.3)
    assert result["meta"]["source_url"] == source
    run.assert_called_once_with("download.opus", ss=60.0, duration=60.0)
    assert gui._speed_factor == pytest.approx(44.0)
    workdir = resolve.call_args.args[1]
    assert not Path(workdir).exists()
    assert json.loads(Path(gui._cache_file(source, 1)).read_text(encoding="utf-8")) == result
    assert analyze(analysis_app, source, 1) == [
        {"type": "progress", "stage": "cache", "message": "Using cached result..."},
        {"type": "result", "data": result},
    ]
    assert resolve.call_count == run.call_count == 1


@pytest.mark.parametrize("error, expected", [
    (FileNotFoundError("missing decoder"), "missing decoder"),
    (RuntimeError("decoder stopped"), "Analysis failed: decoder stopped"),
    (subprocess.CalledProcessError(1, ["ffmpeg", "secret-url"], stderr=b"x" * 250),
     "External tool failed during analysis: " + "x" * 200),
    (subprocess.CalledProcessError(1, ["ffmpeg", "secret-url"]), "External tool failed during analysis"),
    (subprocess.CalledProcessError(1, ["ffmpeg", "secret-url"], stderr="  text tail \n"),
     "External tool failed during analysis: text tail"),
])
def test_failed_analysis_streams_error_and_releases_files(analysis_app, monkeypatch, error, expected):
    resolve, run = fake_analysis(monkeypatch)
    run.side_effect = error
    events = analyze(analysis_app, "https://example.com/audio")
    assert events[-1] == {"type": "error", "error": expected}
    assert not any(event["type"] == "result" for event in events)
    assert not gui._result_cache
    assert not Path(resolve.call_args.args[1]).exists()


def test_changed_local_file_invalidates_cache(analysis_app, tmp_path):
    source = tmp_path / "clip.wav"
    source.write_bytes(b"first")
    os.utime(source, (100, 100))
    gui._cache_put(str(source), None, {"version": 1})
    assert gui._cache_get(str(source), None) == {"version": 1}
    os.utime(source, (200, 200))
    assert gui._cache_get(str(source), None) is None
    gui._cache_put(str(source), None, {"version": 2})
    assert gui._cache_get(str(source), None) == {"version": 2}


def test_fresh_result_replaces_loaded_data_and_broken_disk_cache_is_a_miss(analysis_app):
    source = "https://example.com/audio"
    gui.AnalyzeHandler._cache_loaded(source, {"version": 1})
    assert gui._cache_get(source, None) == {"version": 1}
    cache = Path(gui._cache_put(source, None, {"version": 2}))
    assert gui._cache_get(source, None) == {"version": 2}
    cache.write_text("{broken", encoding="utf-8")
    assert gui._cache_get(source, None) is None
    cache.unlink()
    assert gui._cache_get(source, None) is None


def test_loaded_cache_access_refreshes_eviction_order(analysis_app, monkeypatch):
    monkeypatch.setattr(gui, "_CACHE_MAX_ENTRIES", 2)
    for source in ("https://a", "https://b"):
        gui.AnalyzeHandler._cache_loaded(source, {"source": source})
    assert gui._cache_get("https://a", None) == {"source": "https://a"}
    gui.AnalyzeHandler._cache_loaded("https://c", {"source": "https://c"})
    assert gui._cache_get("https://b", None) is None
    assert gui._cache_get("https://a", None) == {"source": "https://a"}


def test_local_file_is_analysed_by_its_resolved_path(analysis_app, monkeypatch, tmp_path):
    resolve, _ = fake_analysis(monkeypatch)
    source = tmp_path / "clip.wav"
    source.write_bytes(b"RIFF")
    events = analyze(analysis_app, str(source))
    assert events[-1]["type"] == "result"
    assert resolve.call_args.args[0] == str(source)


def test_client_leaving_during_analysis_ends_the_stream_quietly(analysis_app, monkeypatch):
    monkeypatch.setattr(gui.AnalyzeHandler, "_run_analysis", Mock(side_effect=gui._ClientDisconnected()))
    assert analyze(analysis_app, "https://example.com/audio") == []


@pytest.mark.parametrize("error", [
    FileNotFoundError("missing decoder"),
    subprocess.CalledProcessError(1, ["ffmpeg"], stderr=b"boom"),
    RuntimeError("decoder stopped"),
])
def test_client_leaving_while_the_error_is_sent_ends_quietly(analysis_app, monkeypatch, error):
    monkeypatch.setattr(gui.AnalyzeHandler, "_run_analysis", Mock(side_effect=error))
    send = Mock(side_effect=gui._ClientDisconnected())
    monkeypatch.setattr(gui.AnalyzeHandler, "_send_event", send)
    assert analyze(analysis_app, "https://example.com/audio") == []
    send.assert_called_once()
    assert send.call_args.args == ("error",)


def test_zero_elapsed_time_leaves_the_speed_factor_alone(analysis_app, monkeypatch):
    fake_analysis(monkeypatch)
    monkeypatch.setattr(gui.time, "monotonic", Mock(return_value=100.0))
    events = analyze(analysis_app, "https://example.com/audio")
    assert events[-1]["type"] == "result"
    assert gui._speed_factor == 50.0


def test_unreadable_local_source_keys_the_cache_without_a_modification_time(tmp_path):
    missing = str(tmp_path / "gone.wav")
    assert gui._cache_key(missing, 3.0) == (missing, 3.0, None)


def test_entry_dropped_while_its_file_is_read_is_a_miss(analysis_app, monkeypatch, tmp_path):
    source = "https://example.com/audio"
    path = Path(gui._cache_put(source, None, {"version": 1}))
    # The entry leaves the map after its file was found, before the map is checked again.
    def evicted(url, duration):
        gui._result_cache.clear()
        return str(path)
    monkeypatch.setattr(gui, "_cache_file", evicted)
    assert gui._cache_get(source, None) is None


def test_eviction_tolerates_a_cache_file_that_is_already_gone(analysis_app):
    source = "https://example.com/audio"
    first = Path(gui._cache_put(source, None, {"version": 1}))
    first.unlink()
    second = Path(gui._cache_put(source, None, {"version": 2}))
    assert json.loads(second.read_text(encoding="utf-8")) == {"version": 2}


def test_leaving_without_a_window_does_nothing(monkeypatch):
    monkeypatch.setattr(gui, "_window", None)
    gui.AnalyzeHandler.exit_for_update(object(), "close")


def test_frozen_base_dir_is_the_bundle(monkeypatch, tmp_path):
    monkeypatch.setattr(gui.sys, "frozen", True, raising=False)
    monkeypatch.setattr(gui.sys, "_MEIPASS", str(tmp_path), raising=False)
    assert gui._get_base_dir() == tmp_path
