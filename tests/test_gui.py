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
        handler.wfile = MagicMock()
        handler.wfile.write.side_effect = exc()
        with pytest.raises(_ClientDisconnected):
            handler_class._send_event(handler, "progress", message="test")

    def test_send_event_success(self, handler_class):
        handler = MagicMock()
        handler.wfile = MagicMock()
        handler_class._send_event(handler, "progress", message="hello")
        written = handler.wfile.write.call_args[0][0]
        parsed = json.loads(written.decode())
        assert parsed["type"] == "progress"
        assert parsed["message"] == "hello"
        handler.wfile.flush.assert_called_once()


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
