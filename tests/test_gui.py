"""Tests for analyze_loudness.gui module."""

import base64
import json
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
