"""GUI application: pywebview window + local HTTP server for analysis."""

import atexit
import base64
import json
import os
import shutil
import sys
import tempfile
import threading
import time
from datetime import datetime, timezone
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path

import numpy as np
import webview

from analyze_loudness import __version__
from analyze_loudness.analysis import run_ebur128, compute_stats
from analyze_loudness.download import download_audio, probe_duration, compute_middle


def _get_base_dir() -> Path:
    """Return the base directory for bundled resources."""
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS)
    return Path(__file__).resolve().parent.parent.parent


FRONTEND_DIR = _get_base_dir() / "frontend"

# Calibrated ebur128 speed factor (updated at runtime)
_speed_factor = 55.0

# pywebview window reference (set in main())
_window = None

# Analysis result cache — avoids re-analysis for same URL + duration
_cache_dir = tempfile.mkdtemp(prefix="loudness_cache_")
atexit.register(shutil.rmtree, _cache_dir, True)
_result_cache: dict[tuple, str] = {}  # (url, duration) -> json path


def _cache_file(url: str, duration: float | None) -> str | None:
    path = _result_cache.get((url, duration))
    return path if path and os.path.exists(path) else None


def _cache_get(url: str, duration: float | None) -> dict | None:
    path = _cache_file(url, duration)
    if path:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    return None


_cache_seq = 0


def _cache_put(url: str, duration: float | None, result_dict: dict) -> str:
    global _cache_seq
    key = (url, duration)
    _cache_seq += 1
    fname = f"cache_{_cache_seq:04d}.json"
    path = os.path.join(_cache_dir, fname)
    Path(path).write_text(
        json.dumps(result_dict, indent=2, ensure_ascii=False), encoding="utf-8",
    )
    _result_cache[key] = path
    return path


class _ClientDisconnected(Exception):
    """Raised when the client aborts the NDJSON stream."""


class AnalyzeHandler(SimpleHTTPRequestHandler):
    """Serves frontend files and handles /analyze POST requests."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(FRONTEND_DIR), **kwargs)

    def _read_json_body(self) -> dict:
        length = int(self.headers.get("Content-Length", 0))
        if not length:
            return {}
        try:
            return json.loads(self.rfile.read(length))
        except (json.JSONDecodeError, ValueError):
            return {}

    @staticmethod
    def _dialog_path(result) -> str | None:
        """Extract file path from pywebview dialog result."""
        if not result:
            return None
        return result if isinstance(result, str) else result[0]

    def do_POST(self):
        if self.path == "/save":
            self._handle_save()
            return
        if self.path == "/save-image":
            self._handle_save_image()
            return
        if self.path == "/load":
            self._handle_load()
            return
        if self.path != "/analyze":
            self.send_error(404)
            return

        body = self._read_json_body()
        url = body.get("url", "")
        duration = body.get("duration")

        if not url or not isinstance(url, str):
            self._json_error(400, "Missing or invalid 'url' field")
            return

        if duration is not None:
            try:
                duration = float(duration)
                if duration <= 0:
                    self._json_error(400, "'duration' must be a positive number")
                    return
            except (ValueError, TypeError):
                self._json_error(400, "'duration' must be a number")
                return

        # Stream NDJSON progress + final result
        self.send_response(200)
        self.send_header("Content-Type", "application/x-ndjson")
        self.end_headers()

        try:
            self._run_analysis(url, duration)
        except _ClientDisconnected:
            return
        except FileNotFoundError as e:
            try:
                self._send_event("error", error=str(e))
            except _ClientDisconnected:
                return
        except Exception as e:
            try:
                self._send_event("error", error=f"Analysis failed: {e}")
            except _ClientDisconnected:
                return

    def _run_analysis(self, url, duration_min):
        cached = _cache_get(url, duration_min)
        if cached:
            self._send_event("progress", stage="cache",
                             message="Using cached result...")
            self._send_event("result", data=cached)
            return

        with tempfile.TemporaryDirectory(prefix="loudness_") as workdir:
            # Stage 1: Download
            self._send_event("progress", stage="download",
                             message="Downloading audio...")
            src, title = download_audio(url, workdir)
            self._send_event("progress", stage="download",
                             message=f"Downloaded: {title}")

            # Probe duration for time estimate
            total_sec = probe_duration(src)

            # Stage 2: Middle extraction (if requested)
            ss, dur = None, None
            analyze_sec = total_sec
            if duration_min is not None:
                ss, dur, _ = compute_middle(total_sec, duration_min)
                analyze_sec = dur

            global _speed_factor
            estimate_sec = max(1, round(analyze_sec / _speed_factor))
            self._send_event("progress", stage="analyze",
                             message="Running EBU R128 analysis...",
                             estimate_sec=estimate_sec,
                             duration_sec=round(analyze_sec))

            # Stage 3: Analysis (with timing for calibration)
            t0 = time.monotonic()
            t, M, S, summary_raw = run_ebur128(src, ss=ss, duration=dur)
            elapsed = time.monotonic() - t0
            if elapsed > 0:
                _speed_factor = analyze_sec / elapsed

        # Stage 4: Statistics
        self._send_event("progress", stage="stats",
                         message="Computing statistics...")

        st = compute_stats(S, "Short-term")
        mo = compute_stats(M, "Momentary")
        silence_pct = float(np.sum(S < -40) / len(S) * 100)

        result = {
            "meta": {
                "version": __version__,
                "analyzed_at": datetime.now(timezone.utc).isoformat(),
                "source_url": url,
            },
            "title": title,
            "summary": {
                "duration_sec": round(float(t[-1]), 1),
                "frames": len(t),
                "integrated": summary_raw.get("integrated"),
                "true_peak": summary_raw.get("true_peak"),
                "lra": summary_raw.get("lra"),
                "short_term": {
                    "median": round(st["median"], 1),
                    "mean": round(st["mean"], 1),
                    "p10": round(st["p10"], 1),
                    "p90": round(st["p90"], 1),
                },
                "momentary": {
                    "median": round(mo["median"], 1),
                    "mean": round(mo["mean"], 1),
                    "p10": round(mo["p10"], 1),
                    "p90": round(mo["p90"], 1),
                },
                "silence_pct": round(silence_pct, 1),
            },
            "series": {
                "t": [round(float(v), 2) for v in t],
                "S": [round(float(v), 1) for v in S],
                "M": [round(float(v), 1) for v in M],
            },
        }
        _cache_put(url, duration_min, result)
        self._send_event("result", data=result)

    def _handle_save(self):
        body = self._read_json_body()
        data = body.get("data")
        filename = body.get("filename", "loudness_result.json")
        source_url = body.get("source_url")

        if not data:
            self._json_error(400, "Missing 'data' field")
            return

        try:
            result = _window.create_file_dialog(
                webview.SAVE_DIALOG,
                save_filename=filename,
                file_types=("JSON Files (*.json)",),
            )
        except Exception:
            result = None

        save_path = self._dialog_path(result)
        if not save_path:
            self._json_response(200, {"saved": False})
            return

        try:
            cache = _cache_file(source_url, None) if source_url else None
            if cache:
                shutil.copy2(cache, save_path)
            else:
                Path(save_path).write_text(
                    json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
                )
        except OSError as e:
            self._json_error(500, f"Failed to write file: {e}")
            return
        self._json_response(200, {"saved": True, "path": save_path})

    def _handle_save_image(self):
        body = self._read_json_body()
        data_url = body.get("dataUrl", "")
        filename = body.get("filename", "loudness_result.png")

        if not data_url or not data_url.startswith("data:image/png;base64,"):
            self._json_error(400, "Missing or invalid 'dataUrl' field")
            return

        try:
            result = _window.create_file_dialog(
                webview.SAVE_DIALOG,
                save_filename=filename,
                file_types=("PNG Images (*.png)",),
            )
        except Exception:
            result = None

        save_path = self._dialog_path(result)
        if not save_path:
            self._json_response(200, {"saved": False})
            return
        try:
            png_data = base64.b64decode(data_url.split(",", 1)[1])
            Path(save_path).write_bytes(png_data)
        except (OSError, ValueError) as e:
            self._json_error(500, f"Failed to write image: {e}")
            return
        self._json_response(200, {"saved": True, "path": save_path})

    def _handle_load(self):
        try:
            result = _window.create_file_dialog(
                webview.OPEN_DIALOG,
                file_types=("JSON Files (*.json)",),
            )
        except Exception:
            result = None

        file_path = self._dialog_path(result)
        if not file_path:
            self._json_response(200, {"loaded": False})
            return
        try:
            text = Path(file_path).read_text(encoding="utf-8")
            data = json.loads(text)
        except (OSError, json.JSONDecodeError) as e:
            self._json_error(400, f"Failed to read file: {e}")
            return

        if "summary" not in data or "series" not in data:
            self._json_error(400, "Invalid loudness JSON: missing summary or series")
            return

        # Cache loaded data for reuse
        src = data.get("meta", {}).get("source_url")
        if src:
            _cache_put(src, None, data)

        self._json_response(200, {"loaded": True, "data": data})

    def _json_response(self, status, obj):
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(obj, ensure_ascii=False).encode("utf-8"))

    def _json_error(self, status, message):
        self._json_response(status, {"error": message})

    def _send_event(self, event_type, **kwargs):
        line = json.dumps({"type": event_type, **kwargs}, ensure_ascii=False)
        try:
            self.wfile.write((line + "\n").encode("utf-8"))
            self.wfile.flush()
        except (BrokenPipeError, ConnectionAbortedError, ConnectionResetError, OSError):
            raise _ClientDisconnected()

    def log_message(self, format, *args):
        pass  # suppress access logs


_BG_LIGHT = "#fafafa"
_BG_DARK = "#1a1a2e"


from desktop_app_common.platform import IS_WINDOWS, IS_MAC  # noqa: E402
from desktop_app_common.theme import is_dark_mode  # noqa: E402


def _read_theme_from_leveldb(ls_dir: Path, storage_key: str) -> str | None:
    """Scan a Chromium LevelDB directory for a localStorage key value."""
    try:
        if not ls_dir.is_dir():
            return None
        for ldb in sorted(ls_dir.glob("*.log"), reverse=True):
            raw = ldb.read_bytes()
            idx = raw.find(storage_key.encode())
            if idx == -1:
                continue
            tail = raw[idx + len(storage_key):idx + len(storage_key) + 40]
            if b"dark" in tail:
                return "dark"
            if b"light" in tail:
                return "light"
    except Exception:
        pass
    return None


def _resolve_background_color(storage_key: str) -> str:
    """Resolve the pywebview initial background color from the theme setting."""
    mode: str | None = None
    if IS_WINDOWS:
        profile = Path(os.environ.get("LOCALAPPDATA", "")) / "pywebview" / "Default"
        mode = _read_theme_from_leveldb(profile / "Local Storage" / "leveldb", storage_key)
    elif IS_MAC:
        home = Path.home()
        for base in (
            home / "Library/WebKit/org.python.python/WebsiteData/LocalStorage",
            home / "Library/Application Support/pywebview/WebsiteData/LocalStorage",
        ):
            mode = _read_theme_from_leveldb(base, storage_key)
            if mode:
                break
    if mode is None:
        return _BG_DARK if is_dark_mode() else _BG_LIGHT
    return _BG_DARK if mode == "dark" else _BG_LIGHT


def main():
    # When frozen, add bundled binaries (ffmpeg, ffprobe, yt-dlp) to PATH
    if getattr(sys, "frozen", False):
        bin_dir = str(Path(sys._MEIPASS) / "bin")
        os.environ["PATH"] = bin_dir + os.pathsep + os.environ.get("PATH", "")

    server = HTTPServer(("127.0.0.1", 0), AnalyzeHandler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    global _window
    bg = _resolve_background_color("loudness-theme")
    _window = webview.create_window(
        "Loudness Analyzer (BS.1770 / EBU R128)",
        url=f"http://127.0.0.1:{port}/index.html",
        width=1100,
        height=800,
        background_color=bg,
    )
    webview.start()
    server.shutdown()


if __name__ == "__main__":
    main()
