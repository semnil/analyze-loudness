"""Tests for analyze_loudness.gui module."""

import base64
import json
import os
import threading
from http.server import HTTPServer
from unittest.mock import patch, MagicMock

import pytest


@pytest.fixture
def handler_class():
    """Import AnalyzeHandler with mocked dependencies."""
    with patch("analyze_loudness.gui.webview"):
        from analyze_loudness.gui import AnalyzeHandler
        return AnalyzeHandler


@pytest.fixture
def server(handler_class):
    """Create a test HTTP server."""
    srv = HTTPServer(("127.0.0.1", 0), handler_class)
    yield srv
    srv.server_close()


@pytest.fixture
def mock_window():
    """Set up a mock pywebview window and restore after test."""
    import analyze_loudness.gui as gui_mod
    old = gui_mod._window
    gui_mod._window = MagicMock()
    yield gui_mod._window
    gui_mod._window = old


def _post(server, path, body=None):
    """Send a POST request to the test server and return (status, body_dict)."""
    import http.client
    port = server.server_address[1]
    conn = http.client.HTTPConnection("127.0.0.1", port)
    payload = json.dumps(body).encode() if body else b""
    headers = {"Content-Type": "application/json",
               "Content-Length": str(len(payload))}
    conn.request("POST", path, body=payload, headers=headers)
    resp = conn.getresponse()
    data = resp.read().decode()
    conn.close()
    try:
        return resp.status, json.loads(data)
    except json.JSONDecodeError:
        return resp.status, data


def _serve_post(server, path, body=None):
    """Handle one request in a thread and return (status, body_dict)."""
    t = threading.Thread(target=server.handle_request)
    t.start()
    result = _post(server, path, body)
    t.join(timeout=5)
    return result


class TestAnalyzeValidation:
    def test_missing_url(self, server):
        status, body = _serve_post(server, "/analyze", {})
        assert status == 400
        assert "error" in body

    def test_invalid_url_type(self, server):
        status, body = _serve_post(server, "/analyze", {"url": 123})
        assert status == 400
        assert "url" in body["error"].lower()

    def test_negative_duration(self, server):
        status, body = _serve_post(server, "/analyze", {"url": "https://x.com", "duration": -1})
        assert status == 400
        assert "positive" in body["error"]

    def test_non_numeric_duration(self, server):
        status, body = _serve_post(server, "/analyze", {"url": "https://x.com", "duration": "abc"})
        assert status == 400
        assert "number" in body["error"]

    def test_404_for_unknown_post(self, server):
        status, _ = _serve_post(server, "/unknown", {})
        assert status == 404


class TestLoadValidation:
    def test_load_cancel_returns_not_loaded(self, server, mock_window):
        mock_window.create_file_dialog.return_value = None
        status, body = _serve_post(server, "/load", {})
        assert status == 200
        assert body["loaded"] is False

    def test_load_invalid_json_file(self, server, mock_window, tmp_path):
        bad_file = tmp_path / "bad.json"
        bad_file.write_text("not json at all")
        mock_window.create_file_dialog.return_value = str(bad_file)
        status, body = _serve_post(server, "/load", {})
        assert status == 400
        assert "error" in body

    def test_load_missing_fields(self, server, mock_window, tmp_path):
        bad_file = tmp_path / "incomplete.json"
        bad_file.write_text(json.dumps({"title": "test"}))
        mock_window.create_file_dialog.return_value = str(bad_file)
        status, body = _serve_post(server, "/load", {})
        assert status == 400
        assert "summary" in body["error"].lower() or "series" in body["error"].lower()

    def test_load_valid_json(self, server, mock_window, tmp_path):
        valid_data = {
            "title": "Test",
            "summary": {"integrated": -20},
            "series": {"t": [0], "S": [-20], "M": [-21]},
        }
        good_file = tmp_path / "good.json"
        good_file.write_text(json.dumps(valid_data))
        mock_window.create_file_dialog.return_value = str(good_file)
        status, body = _serve_post(server, "/load", {})
        assert status == 200
        assert body["loaded"] is True
        assert body["data"]["title"] == "Test"


class TestSaveValidation:
    def test_save_missing_data(self, server):
        status, body = _serve_post(server, "/save", {})
        assert status == 400
        assert "data" in body["error"].lower()

    def test_save_cancel(self, server, mock_window):
        mock_window.create_file_dialog.return_value = None
        status, body = _serve_post(server, "/save", {"data": {"test": 1}})
        assert status == 200
        assert body["saved"] is False

    def test_save_success(self, server, mock_window, tmp_path):
        save_path = tmp_path / "out.json"
        mock_window.create_file_dialog.return_value = str(save_path)
        status, body = _serve_post(server, "/save", {"data": {"key": "val"}, "filename": "test.json"})
        assert status == 200
        assert body["saved"] is True
        saved = json.loads(save_path.read_text(encoding="utf-8"))
        assert saved["key"] == "val"


class TestSaveImageValidation:
    def test_save_image_missing_data_url(self, server):
        status, body = _serve_post(server, "/save-image", {})
        assert status == 400
        assert "dataUrl" in body["error"]

    def test_save_image_invalid_prefix(self, server):
        status, body = _serve_post(server, "/save-image", {"dataUrl": "not-a-data-url"})
        assert status == 400

    def test_save_image_cancel(self, server, mock_window):
        mock_window.create_file_dialog.return_value = None
        b64 = base64.b64encode(b"\x89PNG fake").decode()
        status, body = _serve_post(server, "/save-image", {
            "dataUrl": f"data:image/png;base64,{b64}",
        })
        assert status == 200
        assert body["saved"] is False

    def test_save_image_success(self, server, mock_window, tmp_path):
        save_path = tmp_path / "out.png"
        mock_window.create_file_dialog.return_value = str(save_path)
        png_bytes = b"\x89PNG\r\n\x1a\n" + b"\x00" * 20
        b64 = base64.b64encode(png_bytes).decode()
        status, body = _serve_post(server, "/save-image", {
            "dataUrl": f"data:image/png;base64,{b64}",
            "filename": "test.png",
        })
        assert status == 200
        assert body["saved"] is True
        assert save_path.read_bytes() == png_bytes


class TestClientDisconnected:
    """Tests for _ClientDisconnected and _send_event error handling."""

    @pytest.mark.parametrize("exc", [BrokenPipeError, ConnectionAbortedError, ConnectionResetError])
    def test_send_event_raises_on_disconnect(self, handler_class, exc):
        from analyze_loudness.gui import _ClientDisconnected
        handler = MagicMock()
        handler.request = MagicMock()
        handler.request.sendall.side_effect = exc()
        with pytest.raises(_ClientDisconnected):
            handler_class._send_event(handler, "progress", message="test")

    def test_send_event_success(self, handler_class):
        handler = MagicMock()
        handler.request = MagicMock()
        handler_class._send_event(handler, "progress", message="hello")
        written = handler.request.sendall.call_args[0][0]
        parsed = json.loads(written.decode())
        assert parsed["type"] == "progress"
        assert parsed["message"] == "hello"


class TestHostHeaderValidation:
    """V-08: DNS rebinding defense via Host header check."""

    def test_invalid_host_rejected_on_post(self, server):
        """POST with attacker-controlled Host header should get 403."""
        import http.client
        port = server.server_address[1]
        t = threading.Thread(target=server.handle_request)
        t.start()
        conn = http.client.HTTPConnection("127.0.0.1", port)
        conn.request("POST", "/analyze", b"{}",
                      {"Host": "evil.attacker.com",
                       "Content-Type": "application/json",
                       "Content-Length": "2"})
        resp = conn.getresponse()
        assert resp.status == 403
        conn.close()
        t.join(timeout=5)

    def test_invalid_host_rejected_on_get(self, server):
        """GET with attacker-controlled Host header should get 403."""
        import http.client
        port = server.server_address[1]
        t = threading.Thread(target=server.handle_request)
        t.start()
        conn = http.client.HTTPConnection("127.0.0.1", port)
        conn.request("GET", "/index.html", headers={"Host": "evil.com"})
        resp = conn.getresponse()
        assert resp.status == 403
        conn.close()
        t.join(timeout=5)

    def test_localhost_host_accepted(self, server):
        """Host: localhost should be accepted."""
        import http.client
        port = server.server_address[1]
        t = threading.Thread(target=server.handle_request)
        t.start()
        conn = http.client.HTTPConnection("127.0.0.1", port)
        conn.request("POST", "/analyze", b"{}",
                      {"Host": "localhost",
                       "Content-Type": "application/json",
                       "Content-Length": "2"})
        resp = conn.getresponse()
        # Should pass host check (400 from missing url, not 403)
        assert resp.status == 400
        conn.close()
        t.join(timeout=5)


class TestDurationBoolGuard:
    """V-12: Boolean duration should be rejected."""

    def test_duration_true_rejected(self, server):
        status, body = _serve_post(server, "/analyze",
                                   {"url": "https://example.com", "duration": True})
        assert status == 400
        assert "number" in body["error"]

    def test_duration_false_rejected(self, server):
        status, body = _serve_post(server, "/analyze",
                                   {"url": "https://example.com", "duration": False})
        assert status == 400
        assert "number" in body["error"]


class TestDurationBoundary:
    """V-10 extension: Additional duration boundary values for /analyze."""

    def test_duration_zero_rejected(self, server):
        status, body = _serve_post(server, "/analyze",
                                   {"url": "https://example.com", "duration": 0})
        assert status == 400
        assert "positive" in body["error"]

    def test_duration_infinity_rejected(self, server):
        status, body = _serve_post(server, "/analyze",
                                   {"url": "https://example.com", "duration": float("inf")})
        assert status == 400
        assert "finite" in body["error"]

    def test_duration_nan_rejected(self, server):
        # NaN is not finite
        status, body = _serve_post(server, "/analyze",
                                   {"url": "https://example.com", "duration": float("nan")})
        assert status == 400
        assert "finite" in body["error"]


class TestUrlValidation:
    """Extended URL validation tests."""

    def test_ftp_scheme_rejected(self, server):
        status, body = _serve_post(server, "/analyze",
                                   {"url": "ftp://example.com/file.mp3"})
        assert status == 400
        assert "http" in body["error"].lower()

    def test_javascript_scheme_rejected(self, server):
        status, body = _serve_post(server, "/analyze",
                                   {"url": "javascript:alert(1)"})
        assert status == 400

    def test_empty_string_rejected(self, server):
        status, body = _serve_post(server, "/analyze", {"url": ""})
        assert status == 400

    def test_whitespace_only_rejected(self, server):
        status, body = _serve_post(server, "/analyze", {"url": "   "})
        assert status == 400


class TestLoadSchemaVersion:
    """V-09: schema_version type validation edge cases."""

    def test_schema_version_bool_rejected(self, server, mock_window, tmp_path):
        data = {
            "meta": {"schema_version": True},
            "summary": {"integrated": -20},
            "series": {"t": [0], "S": [-20], "M": [-21]},
        }
        f = tmp_path / "bool_sv.json"
        f.write_text(json.dumps(data))
        mock_window.create_file_dialog.return_value = str(f)
        status, body = _serve_post(server, "/load", {})
        assert status == 400
        assert "integer" in body["error"]

    def test_schema_version_string_rejected(self, server, mock_window, tmp_path):
        data = {
            "meta": {"schema_version": "1"},
            "summary": {"integrated": -20},
            "series": {"t": [0], "S": [-20], "M": [-21]},
        }
        f = tmp_path / "str_sv.json"
        f.write_text(json.dumps(data))
        mock_window.create_file_dialog.return_value = str(f)
        status, body = _serve_post(server, "/load", {})
        assert status == 400
        assert "integer" in body["error"]

    def test_schema_version_float_rejected(self, server, mock_window, tmp_path):
        data = {
            "meta": {"schema_version": 1.5},
            "summary": {"integrated": -20},
            "series": {"t": [0], "S": [-20], "M": [-21]},
        }
        f = tmp_path / "float_sv.json"
        f.write_text(json.dumps(data))
        mock_window.create_file_dialog.return_value = str(f)
        status, body = _serve_post(server, "/load", {})
        assert status == 400
        assert "integer" in body["error"]

    def test_schema_version_valid_int_accepted(self, server, mock_window, tmp_path):
        data = {
            "meta": {"schema_version": 1, "source_url": "https://example.com"},
            "summary": {"integrated": -20},
            "series": {"t": [0], "S": [-20], "M": [-21]},
        }
        f = tmp_path / "int_sv.json"
        f.write_text(json.dumps(data))
        mock_window.create_file_dialog.return_value = str(f)
        status, body = _serve_post(server, "/load", {})
        assert status == 200
        assert body["loaded"] is True

    def test_schema_version_absent_accepted(self, server, mock_window, tmp_path):
        """Pre-schema JSON without meta.schema_version should load fine."""
        data = {
            "summary": {"integrated": -20},
            "series": {"t": [0], "S": [-20], "M": [-21]},
        }
        f = tmp_path / "no_sv.json"
        f.write_text(json.dumps(data))
        mock_window.create_file_dialog.return_value = str(f)
        status, body = _serve_post(server, "/load", {})
        assert status == 200
        assert body["loaded"] is True


class TestLoadNanInfFallback:
    """V-11: /load with NaN/Inf in external JSON triggers _json_safe fallback."""

    def test_load_json_with_nan_value(self, server, mock_window, tmp_path):
        """NaN in loaded JSON should be sanitized by _json_response fallback."""
        # Write a file with a NaN-like value that Python json.loads accepts
        # when allow_nan=True (the default)
        import json as json_mod
        data = {
            "summary": {"integrated": float("nan")},
            "series": {"t": [0], "S": [-20], "M": [-21]},
        }
        f = tmp_path / "nan.json"
        # Write with allow_nan=True so NaN literal appears in file
        f.write_text(json_mod.dumps(data, allow_nan=True))
        mock_window.create_file_dialog.return_value = str(f)
        status, body = _serve_post(server, "/load", {})
        # Should succeed: _json_response fallback sanitizes NaN -> null
        assert status == 200
        assert body["loaded"] is True
        assert body["data"]["summary"]["integrated"] is None

    def test_load_json_with_infinity(self, server, mock_window, tmp_path):
        import json as json_mod
        data = {
            "meta": {"source_url": "https://example.com"},
            "summary": {"true_peak": float("inf")},
            "series": {"t": [0], "S": [-20], "M": [-21]},
        }
        f = tmp_path / "inf.json"
        f.write_text(json_mod.dumps(data, allow_nan=True))
        mock_window.create_file_dialog.return_value = str(f)
        status, body = _serve_post(server, "/load", {})
        assert status == 200
        assert body["data"]["summary"]["true_peak"] is None


class TestLoadFileSizeLimit:
    """V-17 (from pair checklist): /load rejects files exceeding _MAX_LOAD_BYTES."""

    def test_oversized_file_rejected(self, server, handler_class, mock_window, tmp_path, monkeypatch):
        # A small cap stands in for the real one so the test does not write 210 MB.
        monkeypatch.setattr(handler_class, "_MAX_LOAD_BYTES", 1024)
        big_file = tmp_path / "huge.json"
        big_file.write_bytes(b"x" * (1024 + 1))
        mock_window.create_file_dialog.return_value = str(big_file)
        status, body = _serve_post(server, "/load", {})
        assert status == 400
        assert "MB" in body["error"]


class TestLoadNonDict:
    """Edge case: /load with a JSON array instead of object."""

    def test_array_json_rejected(self, server, mock_window, tmp_path):
        f = tmp_path / "array.json"
        f.write_text(json.dumps([1, 2, 3]))
        mock_window.create_file_dialog.return_value = str(f)
        status, body = _serve_post(server, "/load", {})
        assert status == 400
        assert "object" in body["error"].lower()


class TestCacheLruEviction:
    """V-05: Cache LRU eviction logic."""

    def test_cache_evicts_oldest_entry(self):
        """Inserting > _CACHE_MAX_ENTRIES should evict oldest."""
        import analyze_loudness.gui as gui_mod
        import os
        from collections import OrderedDict
        old_cache = OrderedDict(gui_mod._result_cache)
        old_seq = gui_mod._cache_seq
        try:
            gui_mod._result_cache.clear()
            gui_mod._cache_seq = 0
            paths = []
            for i in range(gui_mod._CACHE_MAX_ENTRIES + 3):
                url = f"https://example.com/v{i}"
                result = {"title": f"test{i}", "summary": {}, "series": {}}
                path = gui_mod._cache_put(url, None, result)
                paths.append(path)

            # Cache should be at max size
            assert len(gui_mod._result_cache) == gui_mod._CACHE_MAX_ENTRIES
            # Oldest entries should have been evicted (files deleted)
            for p in paths[:3]:
                assert not os.path.exists(p)
            # Latest entries should still exist
            for p in paths[-gui_mod._CACHE_MAX_ENTRIES:]:
                assert os.path.exists(p)
        finally:
            gui_mod._result_cache = old_cache
            gui_mod._cache_seq = old_seq

    def test_cache_put_same_key_replaces(self):
        """Re-putting the same key should replace the old file."""
        import analyze_loudness.gui as gui_mod
        import os
        from collections import OrderedDict
        old_cache = OrderedDict(gui_mod._result_cache)
        old_seq = gui_mod._cache_seq
        try:
            gui_mod._result_cache.clear()
            gui_mod._cache_seq = 0
            url = "https://example.com/dup"
            path1 = gui_mod._cache_put(url, None, {"v": 1})
            path2 = gui_mod._cache_put(url, None, {"v": 2})
            assert path1 != path2
            assert not os.path.exists(path1)
            assert os.path.exists(path2)
            assert len(gui_mod._result_cache) == 1
        finally:
            gui_mod._result_cache = old_cache
            gui_mod._cache_seq = old_seq


class TestDialogBusyRejection:
    """Concurrent dialog requests should be rejected with 409."""

    def test_load_rejected_while_dialog_open(self, server, mock_window):
        """A second /load while the first dialog is still open returns 409."""
        import analyze_loudness.gui as gui_mod

        dialog_entered = threading.Event()
        dialog_release = threading.Event()

        def blocking_dialog(*args, **kwargs):
            dialog_entered.set()
            dialog_release.wait(timeout=5)
            return None

        mock_window.create_file_dialog.side_effect = blocking_dialog

        first_result = {}

        def first_load():
            first_result.update(dict(zip(
                ("status", "body"),
                _serve_post(server, "/load", {}),
            )))

        t1 = threading.Thread(target=first_load)
        t1.start()
        dialog_entered.wait(timeout=5)

        status2, body2 = _serve_post(server, "/load", {})
        assert status2 == 409
        assert "dialog" in body2["error"].lower()

        dialog_release.set()
        t1.join(timeout=5)
        assert first_result["status"] == 200

    def test_save_rejected_while_dialog_open(self, server, mock_window):
        """A /save while a /load dialog is open returns 409."""
        import analyze_loudness.gui as gui_mod

        dialog_entered = threading.Event()
        dialog_release = threading.Event()

        def blocking_dialog(*args, **kwargs):
            dialog_entered.set()
            dialog_release.wait(timeout=5)
            return None

        mock_window.create_file_dialog.side_effect = blocking_dialog

        def first_load():
            _serve_post(server, "/load", {})

        t1 = threading.Thread(target=first_load)
        t1.start()
        dialog_entered.wait(timeout=5)

        status2, body2 = _serve_post(server, "/save", {"data": {"x": 1}})
        assert status2 == 409
        assert "dialog" in body2["error"].lower()

        dialog_release.set()
        t1.join(timeout=5)


class TestMetaGeneration:
    def test_meta_fields_present(self):
        from analyze_loudness import __version__
        from datetime import datetime, timezone
        meta = {
            "version": __version__,
            "analyzed_at": datetime.now(timezone.utc).isoformat(),
            "source_url": "https://example.com/watch?v=test",
        }
        assert meta["version"] == __version__
        assert "T" in meta["analyzed_at"]
        assert meta["source_url"].startswith("https://")


def _parallel_get_failures(server, rounds=5, parallel=24):
    """Open ``parallel`` connections at once per round; return the failed requests."""
    import socket
    port = server.server_address[1]
    failures = []

    def one():
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=10) as s:
                s.sendall(b"GET /index.html HTTP/1.1\r\nHost: 127.0.0.1\r\nConnection: close\r\n\r\n")
                data = b""
                while chunk := s.recv(65536):
                    data += chunk
            if not data.startswith(b"HTTP/1.0 200"):
                failures.append(data[:40])
        except OSError as e:
            failures.append(type(e).__name__)

    for _ in range(rounds):
        threads = [threading.Thread(target=one) for _ in range(parallel)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
    return failures


class TestHTTPServerBacklog:
    def test_parallel_page_load_connections_are_all_served(self, handler_class):
        from analyze_loudness.gui import _HTTPServer
        srv = _HTTPServer(("127.0.0.1", 0), handler_class)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        try:
            assert _parallel_get_failures(srv) == []
        finally:
            srv.shutdown()
            srv.server_close()


def _single(n_frames, title="T"):
    t = [round(0.1 * (i + 1), 2) for i in range(n_frames)]
    return {
        "meta": {"schema_version": 2, "source_url": f"https://example.com/{title}"},
        "title": title,
        "summary": {"integrated": -20.0, "true_peak": -1.0, "lra": 5.0, "gate_threshold": -30.0},
        "series": {"t": t, "S": [-20.0] * n_frames, "M": [-21.0] * n_frames},
    }


class TestCompareEndpoint:
    def test_builds_cut_comparison_with_stats(self, server):
        status, body = _serve_post(server, "/compare", {"tracks": [_single(80, "a"), _single(50, "b")]})
        assert status == 200
        tracks = body["data"]["compare"]["tracks"]
        assert [len(tr["series"]["t"]) for tr in tracks] == [50, 50]
        assert body["data"]["meta"]["schema_version"] == 3
        assert len(body["stats"]) == 2
        assert body["stats"][0]["frames"] == 50
        assert body["stats"][0]["integrated"] == pytest.approx(-21.0)

    @pytest.mark.parametrize("n", [1, 7])
    def test_track_count_bounds(self, server, n):
        status, body = _serve_post(server, "/compare", {"tracks": [_single(10) for _ in range(n)]})
        assert status == 400
        assert "tracks" in body["error"]

    def test_invalid_track_named(self, server):
        bad = _single(10)
        bad["series"]["S"] = bad["series"]["S"][:5]
        status, body = _serve_post(server, "/compare", {"tracks": [_single(10), bad]})
        assert status == 400
        assert "Track 2:" in body["error"]

    def test_comparison_as_track_rejected(self, server):
        nested = {"compare": {"tracks": [_single(10), _single(10)]}}
        status, body = _serve_post(server, "/compare", {"tracks": [_single(10), nested]})
        assert status == 400
        assert "comparison" in body["error"]

    def test_empty_track_rejected(self, server):
        status, body = _serve_post(server, "/compare", {"tracks": [_single(10), _single(0)]})
        assert status == 400
        assert "no frames" in body["error"]

    def test_oversized_request_rejected(self, server, handler_class, monkeypatch):
        monkeypatch.setattr(handler_class, "_MAX_BODY_BYTES", 100)
        status, body = _serve_post(server, "/compare", {"tracks": [_single(10), _single(10)]})
        assert status == 413


class TestLoadComparison:
    def _write(self, tmp_path, doc):
        f = tmp_path / "cmp.json"
        f.write_text(json.dumps(doc))
        return str(f)

    def test_comparison_loads_with_stats_and_skips_cache(self, server, mock_window, tmp_path):
        import analyze_loudness.gui as gui_mod
        from analyze_loudness.compare import build_compare
        doc = build_compare([_single(30, "a"), _single(20, "b")])
        doc["meta"]["source_url"] = "https://example.com/cmp"
        mock_window.create_file_dialog.return_value = self._write(tmp_path, doc)
        before = dict(gui_mod._loaded_cache_data)
        status, body = _serve_post(server, "/load", {})
        assert status == 200
        assert body["loaded"] is True
        assert "compare" in body["data"]
        assert len(body["stats"]) == 2
        assert dict(gui_mod._loaded_cache_data) == before

    def test_invalid_comparison_rejected(self, server, mock_window, tmp_path):
        doc = {"compare": {"tracks": [_single(10)]}}
        mock_window.create_file_dialog.return_value = self._write(tmp_path, doc)
        status, body = _serve_post(server, "/load", {})
        assert status == 400
        assert "tracks" in body["error"]


class TestLocalSourceValidation:
    def test_missing_local_file_rejected(self, server, tmp_path):
        status, body = _serve_post(server, "/analyze", {"url": str(tmp_path / "nope.wav")})
        assert status == 400
        assert "not found" in body["error"].lower()

    def test_file_scheme_rejected(self, server, tmp_path):
        status, body = _serve_post(server, "/analyze", {"url": "file://" + str(tmp_path / "a.wav")})
        assert status == 400
        assert "http" in body["error"].lower()

    def test_cache_key_follows_local_mtime(self, tmp_path):
        import os
        from analyze_loudness.gui import _cache_key
        f = tmp_path / "a.wav"
        f.write_bytes(b"x")
        os.utime(f, (1000, 1000))
        k1 = _cache_key(str(f), None)
        os.utime(f, (2000, 2000))
        assert _cache_key(str(f), None) != k1
        assert _cache_key("https://example.com/v", None) == ("https://example.com/v", None)

    def test_loaded_local_result_not_cached(self, server, mock_window, tmp_path):
        import analyze_loudness.gui as gui_mod
        doc = _single(10)
        doc["meta"]["source_url"] = str(tmp_path / "a.wav")
        f = tmp_path / "r.json"
        f.write_text(json.dumps(doc))
        mock_window.create_file_dialog.return_value = str(f)
        before = dict(gui_mod._loaded_cache_data)
        status, body = _serve_post(server, "/load", {})
        assert status == 200
        assert dict(gui_mod._loaded_cache_data) == before


class TestBrowse:
    def test_cancel(self, server, mock_window):
        mock_window.create_file_dialog.return_value = None
        status, body = _serve_post(server, "/browse", {})
        assert status == 200
        assert body["selected"] is False

    def test_selected_path(self, server, mock_window):
        mock_window.create_file_dialog.return_value = ["/music/a.flac"]
        status, body = _serve_post(server, "/browse", {})
        assert body == {"selected": True, "path": "/music/a.flac"}
        file_types = mock_window.create_file_dialog.call_args.kwargs["file_types"]
        assert "*.flac" in file_types[0] and "*.wav" in file_types[0]


def _upload(server, data, name, length=None):
    import http.client
    from urllib.parse import quote
    t = threading.Thread(target=server.handle_request)
    t.start()
    conn = http.client.HTTPConnection("127.0.0.1", server.server_address[1])
    conn.request("POST", "/upload", body=data, headers={
        "Content-Type": "application/octet-stream",
        "Content-Length": str(len(data) if length is None else length),
        "X-Filename": quote(name),
    })
    resp = conn.getresponse()
    body = json.loads(resp.read().decode())
    conn.close()
    t.join(timeout=5)
    return resp.status, body


class TestUpload:
    def test_stores_file_in_upload_dir(self, server):
        import analyze_loudness.gui as gui_mod
        status, body = _upload(server, b"RIFFdata", "clip.wav")
        assert status == 200
        assert os.path.dirname(body["path"]) == gui_mod._upload_dir
        with open(body["path"], "rb") as f:
            assert f.read() == b"RIFFdata"
        status2, body2 = _upload(server, b"other", "clip.wav")
        assert body2["path"] != body["path"]
        assert body2["path"].endswith("clip_1.wav")

    def test_traversal_name_stays_in_upload_dir(self, server):
        import analyze_loudness.gui as gui_mod
        status, body = _upload(server, b"x", "../../evil.wav")
        assert status == 200
        assert os.path.dirname(body["path"]) == gui_mod._upload_dir

    def test_unsupported_extension_rejected(self, server):
        status, body = _upload(server, b"x", "notes.txt")
        assert status == 400
        assert ".txt" in body["error"]

    def test_too_large_rejected(self, server, handler_class, monkeypatch):
        monkeypatch.setattr(handler_class, "_MAX_UPLOAD", 4)
        status, body = _upload(server, b"12345", "a.wav")
        assert status == 413


class TestContentTypeGate:
    """Simple (no-preflight) cross-origin content types are refused."""

    @pytest.mark.parametrize("ctype", ["text/plain", "application/x-www-form-urlencoded", ""])
    def test_analyze_rejects_simple_types(self, server, tmp_path, ctype):
        import http.client
        body = json.dumps({"url": str(tmp_path / "a.wav")}).encode()
        t = threading.Thread(target=server.handle_request)
        t.start()
        conn = http.client.HTTPConnection("127.0.0.1", server.server_address[1])
        headers = {"Content-Length": str(len(body))}
        if ctype:
            headers["Content-Type"] = ctype
        conn.request("POST", "/analyze", body=body, headers=headers)
        resp = conn.getresponse()
        resp.read()
        conn.close()
        t.join(timeout=5)
        assert resp.status == 415

    def test_json_with_charset_accepted(self, server, tmp_path):
        import http.client
        body = json.dumps({"url": str(tmp_path / "a.wav")}).encode()
        t = threading.Thread(target=server.handle_request)
        t.start()
        conn = http.client.HTTPConnection("127.0.0.1", server.server_address[1])
        conn.request("POST", "/analyze", body=body, headers={
            "Content-Type": "application/json; charset=utf-8", "Content-Length": str(len(body))})
        resp = conn.getresponse()
        resp.read()
        conn.close()
        t.join(timeout=5)
        assert resp.status == 400  # reached validation: the file does not exist

    def test_upload_needs_octet_stream(self, server):
        import http.client
        from urllib.parse import quote
        t = threading.Thread(target=server.handle_request)
        t.start()
        conn = http.client.HTTPConnection("127.0.0.1", server.server_address[1])
        conn.request("POST", "/upload", body=b"x", headers={
            "Content-Type": "text/plain", "Content-Length": "1", "X-Filename": quote("a.wav")})
        resp = conn.getresponse()
        resp.read()
        conn.close()
        t.join(timeout=5)
        assert resp.status == 415


class TestNetworkPathRejected:
    @pytest.mark.parametrize("path", [r"\\host\share\a.wav", "//host/share/a.wav", r"\\?\C:\a.wav"])
    def test_rejected_before_any_file_access(self, server, path):
        with patch("analyze_loudness.gui.os.path.isfile", side_effect=AssertionError("touched the path")), \
             patch("analyze_loudness.gui.local_path", side_effect=AssertionError("resolved the path")):
            status, body = _serve_post(server, "/analyze", {"url": path})
        assert status == 400
        assert "network" in body["error"].lower()


class TestCommonCss:
    def _get(self, handler_class, path):
        import http.client
        from http.server import HTTPServer
        srv = HTTPServer(("127.0.0.1", 0), handler_class)
        t = threading.Thread(target=srv.handle_request)
        t.start()
        conn = http.client.HTTPConnection("127.0.0.1", srv.server_address[1], timeout=10)
        conn.request("GET", path, headers={"Host": "127.0.0.1"})
        resp = conn.getresponse()
        body = resp.read()
        conn.close()
        t.join(timeout=5)
        srv.server_close()
        return resp, body

    def test_common_css_served_from_analyze_common(self, handler_class):
        from analyze_common.web import COMMON_CSS
        resp, body = self._get(handler_class, "/common/common.css?v=1")
        assert resp.status == 200
        assert resp.getheader("Content-Type").startswith("text/css")
        assert body == COMMON_CSS.read_bytes()

    def test_update_js_served_from_analyze_common(self, handler_class):
        from analyze_common.web import UPDATE_JS
        resp, body = self._get(handler_class, "/common/update.js")
        assert resp.status == 200
        assert resp.getheader("Content-Type").startswith("text/javascript")
        assert body == UPDATE_JS.read_bytes()

    def test_index_loads_update_js_before_main_js(self, handler_class):
        from pathlib import Path
        html = (Path(__import__('analyze_loudness.gui', fromlist=['FRONTEND_DIR']).FRONTEND_DIR) / "index.html").read_text(encoding="utf-8")
        assert 0 <= html.index('src="common/update.js"') < html.index('src="main.js"')

    def test_settings_js_carries_the_stored_theme_and_language(self, handler_class):
        import analyze_loudness.gui as gui_mod
        from analyze_common.web import SETTINGS_JS
        gui_mod._ui_settings.update({"theme": "dark"})
        gui_mod._ui_settings.update({"lang": "ja"})
        resp, body = self._get(handler_class, "/common/settings.js")
        assert resp.status == 200
        assert resp.getheader("Content-Type").startswith("text/javascript")
        assert resp.getheader("Cache-Control") == "no-store"
        assert body == b'window.analyzeSettingsStored = {"theme": "dark", "lang": "ja"};\n' + SETTINGS_JS.read_bytes()

    def test_settings_js_without_a_settings_file(self, handler_class):
        resp, body = self._get(handler_class, "/common/settings.js")
        assert resp.status == 200
        assert body.startswith(b'window.analyzeSettingsStored = {"theme": "auto", "lang": null};\n')

    def test_settings_js_carries_only_allowed_values(self, handler_class):
        import analyze_loudness.gui as gui_mod
        path = gui_mod._settings.path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"theme": "</script><script>alert(1)</script>", "lang": "\";alert(1);\""}), encoding="utf-8")
        resp, body = self._get(handler_class, "/common/settings.js")
        assert resp.status == 200
        assert body.startswith(b'window.analyzeSettingsStored = {"theme": "auto", "lang": null};\n')
        assert b"alert" not in body

    def test_index_loads_settings_js_before_i18n_js(self, handler_class):
        from pathlib import Path
        html = (Path(__import__('analyze_loudness.gui', fromlist=['FRONTEND_DIR']).FRONTEND_DIR) / "index.html").read_text(encoding="utf-8")
        assert 0 <= html.index('src="common/settings.js"') < html.index('src="i18n.js"')

    def test_index_loads_common_css_before_style_css(self, handler_class):
        from pathlib import Path
        html = (Path(__import__('analyze_loudness.gui', fromlist=['FRONTEND_DIR']).FRONTEND_DIR) / "index.html").read_text(encoding="utf-8")
        assert 0 <= html.index('href="common/common.css"') < html.index('href="style.css"')


@pytest.fixture
def update_settings(_isolated_settings):
    """The app's one settings store, in the temp folder conftest set up."""
    import analyze_loudness.gui as gui_mod
    return gui_mod._settings


class TestUpdateEndpoints:
    def test_status_outside_the_packaged_app(self, server, update_settings):
        from analyze_loudness import __version__
        status, body = _serve_post(server, "/update/status", {})
        assert status == 200
        assert body == {"current": __version__, "supported": False, "launch_check": True}

    def test_launch_check_is_saved_to_the_settings_file(self, server, update_settings):
        status, body = _serve_post(server, "/update/settings", {"launch_check": False})
        assert (status, body) == (200, {"launch_check": False})
        assert json.loads(update_settings.path.read_text(encoding="utf-8")) == {"update_check_at_launch": False}
        status, body = _serve_post(server, "/update/status", {})
        assert body["launch_check"] is False

    def test_launch_check_can_be_turned_back_on(self, server, update_settings):
        update_settings.set("update_check_at_launch", False)
        status, body = _serve_post(server, "/update/settings", {"launch_check": True})
        assert (status, body) == (200, {"launch_check": True})
        assert update_settings.get("update_check_at_launch", None) is True

    @pytest.mark.parametrize("payload", [{}, {"launch_check": "false"}, {"launch_check": 0}, {"launch_check": None}])
    def test_settings_need_a_boolean(self, server, update_settings, payload):
        status, body = _serve_post(server, "/update/settings", payload)
        assert status == 400
        assert not update_settings.path.exists()

    def test_settings_write_failure(self, server, update_settings):
        with patch.object(update_settings, "set", side_effect=OSError(13, "Permission denied")):
            status, body = _serve_post(server, "/update/settings", {"launch_check": False})
        assert status == 500
        assert "could not be saved" in body["error"]

    def test_check_offers_a_newer_version(self, server):
        with patch("analyze_loudness.gui._updater.check", return_value="9.0.0"):
            status, body = _serve_post(server, "/update/check", {})
        assert (status, body) == (200, {"available": True, "version": "9.0.0"})

    def test_check_up_to_date(self, server):
        with patch("analyze_loudness.gui._updater.check", return_value=None):
            status, body = _serve_post(server, "/update/check", {})
        assert (status, body) == (200, {"available": False})

    def test_check_failure(self, server):
        from analyze_common.update import UpdateError
        with patch("analyze_loudness.gui._updater.check", side_effect=UpdateError("HTTP 404 from x")):
            status, body = _serve_post(server, "/update/check", {})
        assert status == 502
        assert body["error"] == "HTTP 404 from x"

    @pytest.mark.parametrize("payload", [{}, {"version": 5}, {"version": ""}])
    def test_install_needs_a_version(self, server, payload):
        with patch("analyze_loudness.gui._updater.install") as install:
            status, body = _serve_post(server, "/update/install", payload)
        assert status == 400
        install.assert_not_called()

    def test_install_failure(self, server, mock_window):
        from analyze_common.update import UpdateError
        with patch("analyze_loudness.gui._updater.install",
                   side_effect=UpdateError("The downloaded update does not match its signature")), \
             patch("analyze_loudness.gui._exit_now") as exit_now:
            status, body = _serve_post(server, "/update/install", {"version": "9.0.0"})
        assert status == 500
        assert "signature" in body["error"]
        mock_window.destroy.assert_not_called()
        exit_now.assert_not_called()

    def test_windows_handoff_closes_the_window(self, server, mock_window):
        from analyze_common.update import Handoff
        with patch("analyze_loudness.gui._updater.install", return_value=Handoff("close")) as install, \
             patch("analyze_loudness.gui._exit_now") as exit_now:
            status, body = _serve_post(server, "/update/install", {"version": "9.0.0"})
        assert (status, body) == (200, {"restarting": True})
        install.assert_called_once_with("9.0.0")
        mock_window.destroy.assert_called_once()
        exit_now.assert_not_called()

    def test_mac_handoff_exits_at_once(self, server, mock_window):
        from analyze_common.update import Handoff
        with patch("analyze_loudness.gui._updater.install", return_value=Handoff("immediate")), \
             patch("analyze_loudness.gui._exit_now") as exit_now:
            status, body = _serve_post(server, "/update/install", {"version": "9.0.0"})
        assert (status, body) == (200, {"restarting": True})
        exit_now.assert_called_once()
        mock_window.destroy.assert_not_called()

    def test_relaunch_failure_keeps_running(self, server, mock_window):
        from analyze_common.update import Handoff
        with patch("analyze_loudness.gui._updater.install",
                   return_value=Handoff(None, restart_error="Resource busy")), \
             patch("analyze_loudness.gui._exit_now") as exit_now:
            status, body = _serve_post(server, "/update/install", {"version": "9.0.0"})
        assert (status, body) == (200, {"installed": True, "restart_error": "Resource busy"})
        exit_now.assert_not_called()
        mock_window.destroy.assert_not_called()

    def test_install_refuses_other_content_types(self, server):
        import http.client
        t = threading.Thread(target=server.handle_request)
        t.start()
        conn = http.client.HTTPConnection("127.0.0.1", server.server_address[1])
        with patch("analyze_loudness.gui._updater.install") as install:
            conn.request("POST", "/update/install", body=b'{"version": "9.0.0"}',
                         headers={"Content-Type": "text/plain"})
            resp = conn.getresponse()
            resp.read()
        conn.close()
        t.join(timeout=5)
        assert resp.status == 415
        install.assert_not_called()

    def test_exit_now_does_the_atexit_cleanup(self, tmp_path):
        import analyze_loudness.gui as gui_mod
        cache, upload = tmp_path / "cache", tmp_path / "upload"
        cache.mkdir()
        upload.mkdir()
        with patch.object(gui_mod, "_cache_dir", str(cache)), \
             patch.object(gui_mod, "_upload_dir", str(upload)), \
             patch.object(gui_mod, "_cleanup_orphan_tempdirs") as sweep, \
             patch.object(gui_mod.os, "_exit") as exit_:
            gui_mod._exit_now()
        assert not cache.exists() and not upload.exists()
        sweep.assert_called_once()
        exit_.assert_called_once_with(0)


class TestUiSettingsEndpoint:
    def test_update_and_ui_settings_share_one_store(self):
        import analyze_loudness.gui as gui_mod
        assert gui_mod._updater.settings is gui_mod._settings
        assert gui_mod._ui_settings.settings is gui_mod._settings

    def test_theme_is_saved_to_the_settings_file(self, server, update_settings):
        status, body = _serve_post(server, "/settings", {"theme": "dark"})
        assert (status, body) == (200, {"theme": "dark", "lang": None})
        assert json.loads(update_settings.path.read_text(encoding="utf-8")) == {"theme": "dark"}

    def test_language_is_saved_next_to_the_update_setting(self, server, update_settings):
        update_settings.set("update_check_at_launch", False)
        status, body = _serve_post(server, "/settings", {"lang": "ja"})
        assert (status, body) == (200, {"theme": "auto", "lang": "ja"})
        assert json.loads(update_settings.path.read_text(encoding="utf-8")) == {
            "update_check_at_launch": False, "lang": "ja"}

    @pytest.mark.parametrize("payload", [{}, {"theme": "blue"}, {"lang": "fr"}, {"font": "large"},
                                         {"theme": "dark", "lang": "ja"}])
    def test_anything_else_is_refused_without_writing(self, server, update_settings, payload):
        status, body = _serve_post(server, "/settings", payload)
        assert status == 400
        assert body["error"]
        assert not update_settings.path.exists()

    def test_a_failed_write_is_a_server_error(self, server, update_settings, monkeypatch):
        def refuse(key, value):
            raise PermissionError(13, "Permission denied")
        monkeypatch.setattr(update_settings, "set", refuse)
        status, body = _serve_post(server, "/settings", {"theme": "dark"})
        assert status == 500
        assert "Permission denied" in body["error"]

    @pytest.mark.parametrize("theme", ["dark", "light"])
    def test_window_opens_in_the_stored_theme_color(self, update_settings, monkeypatch, theme):
        import analyze_loudness.gui as gui_mod
        from analyze_common.ui_settings import BG_DARK, BG_LIGHT
        gui_mod._ui_settings.update({"theme": theme})
        webview = MagicMock()
        monkeypatch.setattr(gui_mod, "webview", webview)
        monkeypatch.setattr(gui_mod, "hold_instance_mutex", MagicMock())
        monkeypatch.setattr(gui_mod, "_HTTPServer", MagicMock(return_value=MagicMock(server_address=("127.0.0.1", 1))))
        monkeypatch.setattr(gui_mod, "_window", None)
        gui_mod.main()
        assert webview.create_window.call_args.kwargs["background_color"] == (BG_DARK if theme == "dark" else BG_LIGHT)

    def test_window_keeps_its_color_until_the_page_paints(self, update_settings, monkeypatch):
        import analyze_loudness.gui as gui_mod
        webview = MagicMock()
        shown = []
        monkeypatch.setattr(gui_mod, "webview", webview)
        monkeypatch.setattr(gui_mod, "hold_instance_mutex", MagicMock())
        monkeypatch.setattr(gui_mod, "_HTTPServer", MagicMock(return_value=MagicMock(server_address=("127.0.0.1", 1))))
        monkeypatch.setattr(gui_mod, "_window", None)
        monkeypatch.setattr(gui_mod, "show_window_color_until_paint", shown.append)
        gui_mod.main()
        assert shown == [webview.create_window.return_value]
