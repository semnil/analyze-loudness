"""GUI application: pywebview window + local HTTP server for analysis."""

import atexit
import base64
import glob
import json
import math
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import traceback
from collections import OrderedDict
from datetime import datetime, timezone
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import numpy as np
import webview

from analyze_loudness import SCHEMA_VERSION, __version__, _json_safe
from analyze_loudness.analysis import run_ebur128, compute_stats
from analyze_loudness.download import (
    download_audio, probe_duration, compute_middle, sanitize_filename,
)


def _get_base_dir() -> Path:
    """Return the base directory for bundled resources."""
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS)
    return Path(__file__).resolve().parent.parent.parent


FRONTEND_DIR = _get_base_dir() / "frontend"
_ICON_PATH = _get_base_dir() / "build_assets" / "icon.ico"

# Calibrated ebur128 speed factor (updated at runtime)
# EMA smoothing + clamp to protect against outlier measurements.
_speed_factor = 55.0
_speed_lock = threading.Lock()
_SPEED_MIN = 5.0
_SPEED_MAX = 500.0
_SPEED_EMA_ALPHA = 0.3

# pywebview window reference (set in main())
_window = None

# Analysis result cache — avoids re-analysis for same URL + duration
_cache_dir = tempfile.mkdtemp(prefix="loudness_cache_")
atexit.register(shutil.rmtree, _cache_dir, True)


_ORPHAN_TEMPDIR_MIN_AGE_SEC = 3600  # 1 hour


def _cleanup_orphan_tempdirs() -> None:
    """Remove loudness_* temp directories left by a previous hard-killed run.

    TemporaryDirectory('s with' block cleans up on normal exit, but if the
    webview window is force-closed while a worker is inside ebur128 the
    directory can survive across sessions.  Sweep them once at shutdown.

    Only directories older than ``_ORPHAN_TEMPDIR_MIN_AGE_SEC`` are removed so
    that tempdirs belonging to another concurrently running instance are not
    deleted when this process exits.
    """
    pattern = os.path.join(tempfile.gettempdir(), "loudness_*")
    now = time.time()
    for path in glob.glob(pattern):
        if path == _cache_dir:
            continue
        try:
            if os.path.islink(path) or not os.path.isdir(path):
                continue
            if now - os.path.getmtime(path) <= _ORPHAN_TEMPDIR_MIN_AGE_SEC:
                continue
            shutil.rmtree(path, ignore_errors=True)
        except OSError:
            pass


atexit.register(_cleanup_orphan_tempdirs)
_CACHE_MAX_ENTRIES = 10
_result_cache: "OrderedDict[tuple, str]" = OrderedDict()  # (url, duration) -> json path
# In-memory map for externally loaded JSON.  Kept separate from _result_cache
# so /load payloads never touch _cache_dir on disk.
_loaded_cache_data: "OrderedDict[tuple, dict]" = OrderedDict()
_cache_lock = threading.Lock()
_dialog_lock = threading.Lock()


def _cache_file(url: str, duration: float | None) -> str | None:
    with _cache_lock:
        path = _result_cache.get((url, duration))
        if path:
            _result_cache.move_to_end((url, duration))
    return path if path and os.path.exists(path) else None


def _cache_get(url: str, duration: float | None) -> dict | None:
    key = (url, duration)
    with _cache_lock:
        data = _loaded_cache_data.get(key)
        if data is not None:
            _loaded_cache_data.move_to_end(key)
            return data
    path = _cache_file(url, duration)
    if path:
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            return None
        with _cache_lock:
            if key not in _result_cache:
                return None
        return data
    return None


_cache_seq = 0


def _cache_put(url: str, duration: float | None, result_dict: dict) -> str:
    global _cache_seq
    key = (url, duration)
    evicted: list[str] = []
    with _cache_lock:
        # Drop any previously /load-populated entry for this key so the
        # freshly computed /analyze result is not shadowed by stale data.
        _loaded_cache_data.pop(key, None)
        existing = _result_cache.get(key)
        if existing is not None:
            evicted.append(existing)
        _cache_seq += 1
        fname = f"cache_{_cache_seq:04d}.json"
        path = os.path.join(_cache_dir, fname)
        _result_cache[key] = path
        _result_cache.move_to_end(key)
        while len(_result_cache) > _CACHE_MAX_ENTRIES:
            _, old_path = _result_cache.popitem(last=False)
            evicted.append(old_path)
    Path(path).write_text(
        json.dumps(result_dict, indent=2, ensure_ascii=False, allow_nan=False),
        encoding="utf-8",
    )
    for old_path in evicted:
        try:
            os.unlink(old_path)
        except OSError:
            pass
    return path


class _ClientDisconnected(Exception):
    """Raised when the client aborts the NDJSON stream."""


class AnalyzeHandler(SimpleHTTPRequestHandler):
    """Serves frontend files and handles /analyze POST requests."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(FRONTEND_DIR), **kwargs)

    _MAX_BODY_BYTES = 64 * 1024 * 1024  # 64 MiB: large enough for full-resolution image payload
    _MAX_LOAD_BYTES = 50 * 1024 * 1024  # 50 MB cap for /load JSON files
    _ALLOWED_HOSTS = ("127.0.0.1", "localhost")

    def _check_host(self) -> bool:
        """Reject requests whose Host header is not a loopback literal.

        Defends against DNS rebinding: a malicious page could ask the browser
        to resolve an attacker-controlled name to 127.0.0.1 and talk to this
        server. Rejecting non-loopback Host literals blocks that.
        """
        host = self.headers.get("Host", "")
        host_name = host.split(":", 1)[0] if host else ""
        if host_name not in self._ALLOWED_HOSTS:
            self.send_error(403, "Forbidden: invalid Host")
            return False
        return True

    def _read_json_body(self) -> dict:
        try:
            length = int(self.headers.get("Content-Length", 0))
        except (ValueError, TypeError):
            return {}
        if length <= 0:
            return {}
        if length > self._MAX_BODY_BYTES:
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

    def do_GET(self):
        if not self._check_host():
            return
        super().do_GET()

    def do_POST(self):
        if not self._check_host():
            return
        if self.path in ("/save", "/save-image", "/load"):
            try:
                if self.path == "/save":
                    self._handle_save()
                elif self.path == "/save-image":
                    self._handle_save_image()
                else:
                    self._handle_load()
            except Exception:
                traceback.print_exc()
                try:
                    self._json_error(500, "Internal server error")
                except Exception:
                    traceback.print_exc()
            return
        if self.path != "/analyze":
            self.send_error(404)
            return

        body = self._read_json_body()
        url = body.get("url", "")
        duration = body.get("duration")

        if not isinstance(url, str) or not url.strip():
            self._json_error(400, "Missing or invalid 'url' field")
            return
        url = url.strip()
        if not (url.startswith("http://") or url.startswith("https://")):
            self._json_error(400, "'url' must use http or https scheme")
            return

        if duration is not None:
            if isinstance(duration, bool):
                self._json_error(400, "'duration' must be a number")
                return
            try:
                duration = float(duration)
            except (ValueError, TypeError):
                self._json_error(400, "'duration' must be a number")
                return
            if not math.isfinite(duration):
                self._json_error(400, "'duration' must be a finite number")
                return
            if duration <= 0:
                self._json_error(400, "'duration' must be a positive number")
                return
            if duration > 240:
                self._json_error(400, "'duration' must be <= 240 minutes")
                return

        # Stream NDJSON progress + final result.
        # No Content-Length / Transfer-Encoding: chunked, so require close
        # to make message framing unambiguous.
        self.close_connection = True
        self.send_response(200)
        self.send_header("Content-Type", "application/x-ndjson")
        self.send_header("Connection", "close")
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
        except subprocess.CalledProcessError as e:
            # Do not leak full ffmpeg/ffprobe stderr (may contain local paths
            # or long stack traces).  Keep only the last 200 bytes and drop
            # the raw argv so credentials embedded in URLs never surface.
            stderr_tail = ""
            if e.stderr:
                tail = e.stderr[-200:]
                if isinstance(tail, bytes):
                    tail = tail.decode("utf-8", errors="replace")
                stderr_tail = tail.strip()
            msg = "External tool failed during analysis"
            if stderr_tail:
                msg = f"{msg}: {stderr_tail}"
            try:
                self._send_event("error", error=msg)
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
            with _speed_lock:
                speed = _speed_factor
            estimate_sec = max(1, round(analyze_sec / speed))
            self._send_event("progress", stage="analyze",
                             message="Running EBU R128 analysis...",
                             estimate_sec=estimate_sec,
                             duration_sec=round(analyze_sec))

            # Stage 3: Analysis (with timing for calibration)
            t0 = time.monotonic()
            t, M, S, summary_raw = run_ebur128(src, ss=ss, duration=dur)
            for w in summary_raw.pop("warnings", []):
                self._send_event("warning", message=w)
            elapsed = time.monotonic() - t0
            if elapsed > 0 and analyze_sec > 0:
                sample = analyze_sec / elapsed
                if math.isfinite(sample) and _SPEED_MIN <= sample <= _SPEED_MAX:
                    with _speed_lock:
                        _speed_factor = (
                            _SPEED_EMA_ALPHA * sample
                            + (1.0 - _SPEED_EMA_ALPHA) * _speed_factor
                        )

        # Stage 4: Statistics
        self._send_event("progress", stage="stats",
                         message="Computing statistics...")

        st = compute_stats(S, "Short-term")
        mo = compute_stats(M, "Momentary")
        # Treat NaN/-inf frames as silence as well (np.isnan(NaN) or S < -40).
        silent_mask = np.isnan(S) | (S < -40)
        silence_pct = float(np.sum(silent_mask) / len(S) * 100) if len(S) else 0.0

        def _round1(v):
            return round(v, 1) if v is not None else None

        result = {
            "meta": {
                "schema_version": SCHEMA_VERSION,
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
                    "median": _round1(st["median"]),
                    "mean": _round1(st["mean"]),
                    "p10": _round1(st["p10"]),
                    "p90": _round1(st["p90"]),
                },
                "momentary": {
                    "median": _round1(mo["median"]),
                    "mean": _round1(mo["mean"]),
                    "p10": _round1(mo["p10"]),
                    "p90": _round1(mo["p90"]),
                },
                "silence_pct": round(silence_pct, 1),
            },
            "series": {
                "t": [round(float(v), 2) for v in t],
                "S": [round(float(v), 1) for v in S],
                "M": [round(float(v), 1) for v in M],
            },
        }
        result = _json_safe(result)
        _cache_put(url, duration_min, result)
        self._send_event("result", data=result)

    def _handle_save(self):
        body = self._read_json_body()
        filename = sanitize_filename(body.get("filename", "loudness_result.json"))

        if "data" not in body:
            self._json_error(400, "Missing 'data' field")
            return
        data = body.get("data")

        if not _dialog_lock.acquire(blocking=False):
            self._json_error(409, "A dialog is already open")
            return
        try:
            result = _window.create_file_dialog(
                webview.SAVE_DIALOG,
                save_filename=filename,
                file_types=("JSON Files (*.json)",),
            )
        except Exception as e:
            traceback.print_exc()
            self._json_error(500, f"File dialog error: {e}")
            return
        finally:
            _dialog_lock.release()

        save_path = self._dialog_path(result)
        if not save_path:
            self._json_response(200, {"saved": False})
            return

        try:
            Path(save_path).write_text(
                json.dumps(_json_safe(data), indent=2, ensure_ascii=False,
                           allow_nan=False),
                encoding="utf-8",
            )
        except OSError as e:
            self._json_error(500, f"Failed to write file: {e}")
            return
        self._json_response(200, {"saved": True, "path": save_path})

    def _handle_save_image(self):
        body = self._read_json_body()
        data_url = body.get("dataUrl", "")
        filename = sanitize_filename(body.get("filename", "loudness_result.png"))

        if not data_url or not data_url.startswith("data:image/png;base64,"):
            self._json_error(400, "Missing or invalid 'dataUrl' field")
            return

        if not _dialog_lock.acquire(blocking=False):
            self._json_error(409, "A dialog is already open")
            return
        try:
            result = _window.create_file_dialog(
                webview.SAVE_DIALOG,
                save_filename=filename,
                file_types=("PNG Images (*.png)",),
            )
        except Exception as e:
            traceback.print_exc()
            self._json_error(500, f"File dialog error: {e}")
            return
        finally:
            _dialog_lock.release()

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
        if not _dialog_lock.acquire(blocking=False):
            self._json_error(409, "A dialog is already open")
            return
        try:
            result = _window.create_file_dialog(
                webview.OPEN_DIALOG,
                file_types=("JSON Files (*.json)",),
            )
        except Exception as e:
            traceback.print_exc()
            self._json_error(500, f"File dialog error: {e}")
            return
        finally:
            _dialog_lock.release()

        file_path = self._dialog_path(result)
        if not file_path:
            self._json_response(200, {"loaded": False})
            return
        try:
            size = os.path.getsize(file_path)
        except OSError as e:
            self._json_error(400, f"Failed to read file: {e}")
            return
        if size > self._MAX_LOAD_BYTES:
            self._json_error(
                400,
                f"JSON file exceeds {self._MAX_LOAD_BYTES // (1024 * 1024)} MB",
            )
            return
        try:
            text = Path(file_path).read_text(encoding="utf-8")
            data = json.loads(text)
        except (OSError, json.JSONDecodeError) as e:
            self._json_error(400, f"Failed to read file: {e}")
            return

        if not isinstance(data, dict):
            self._json_error(400, "Invalid loudness JSON: expected an object")
            return
        if "summary" not in data or "series" not in data:
            self._json_error(400, "Invalid loudness JSON: missing summary or series")
            return
        series = data["series"]
        if not isinstance(series, dict) or not all(
            isinstance(series.get(k), list) for k in ("t", "S", "M")
        ):
            self._json_error(400, "Invalid loudness JSON: series must contain t, S, M arrays")
            return
        if not (len(series["t"]) == len(series["S"]) == len(series["M"])):
            self._json_error(400, "Invalid loudness JSON: series t/S/M length mismatch")
            return

        # Reject meta.schema_version values that are not plain ints (bool is
        # rejected explicitly because isinstance(True, int) is True).  Absent
        # field is allowed for pre-schema JSON.
        meta = data.get("meta")
        if isinstance(meta, dict) and "schema_version" in meta:
            sv = meta["schema_version"]
            if not isinstance(sv, int) or isinstance(sv, bool):
                self._json_error(400, "Invalid loudness JSON: meta.schema_version must be an integer")
                return

        # Cache loaded data for reuse (only when source_url is a usable string key)
        src = meta.get("source_url") if isinstance(meta, dict) else None
        if isinstance(src, str) and src:
            self._cache_loaded(src, data)

        self._json_response(200, {"loaded": True, "data": data})

    @staticmethod
    def _cache_loaded(url: str, data: dict) -> None:
        """Keep externally loaded JSON in memory only.

        External JSON from /load is retained in an in-memory LRU map so the
        UI can restore it within the session, but is NOT written to
        _cache_dir — we do not want to persist user-supplied payloads
        (which may be large or out-of-spec) across app restarts or pollute
        disk as the user browses files.
        """
        key = (url, None)
        with _cache_lock:
            _loaded_cache_data[key] = data
            _loaded_cache_data.move_to_end(key)
            while len(_loaded_cache_data) > _CACHE_MAX_ENTRIES:
                _loaded_cache_data.popitem(last=False)

    def _json_response(self, status, obj):
        # Sanitize on retry so a NaN/Inf hiding in externally-loaded JSON does
        # not crash mid-response and surface in WebKit as a bare "Load failed"
        # with no diagnostics.  The traceback is kept in stderr for debugging.
        try:
            body = json.dumps(obj, ensure_ascii=False, allow_nan=False).encode("utf-8")
        except (ValueError, TypeError):
            traceback.print_exc()
            body = json.dumps(
                _json_safe(obj), ensure_ascii=False, allow_nan=False
            ).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        # wfile (SocketIO, wbufsize=0) delegates to socket.send() which may
        # perform a partial write when body exceeds SO_SNDBUF (~128 KB).
        # sendall() loops internally until every byte is delivered.
        self.request.sendall(body)

    def _json_error(self, status, message):
        self._json_response(status, {"error": message})

    def _send_event(self, event_type, **kwargs):
        payload = _json_safe({"type": event_type, **kwargs})
        line = json.dumps(payload, ensure_ascii=False, allow_nan=False)
        try:
            self.request.sendall((line + "\n").encode("utf-8"))
        except (BrokenPipeError, ConnectionAbortedError, ConnectionResetError, OSError):
            # Client aborted mid-stream.  Emit the underlying traceback so
            # a root cause is visible in stderr even though the event can no
            # longer reach the frontend.
            traceback.print_exc()
            raise _ClientDisconnected()

    def log_message(self, format, *args):
        pass  # suppress access logs


_BG_LIGHT = "#fafafa"
_BG_DARK = "#1a1a2e"


from analyze_common.platform import IS_WINDOWS, IS_MAC  # noqa: E402
from analyze_common.theme import is_dark_mode  # noqa: E402


def _read_theme_from_leveldb(ls_dir: Path, storage_key: str) -> str | None:
    """Scan a Chromium LevelDB directory for a localStorage key value."""
    try:
        if not ls_dir.is_dir():
            return None
        candidates = list(ls_dir.glob("*.log")) + list(ls_dir.glob("*.ldb"))
        for ldb in sorted(candidates, key=lambda p: p.stat().st_mtime, reverse=True):
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
    # When frozen, add bundled binaries (ffmpeg, ffprobe, deno) to PATH
    if getattr(sys, "frozen", False):
        bin_dir = str(Path(sys._MEIPASS) / "bin")
        os.environ["PATH"] = bin_dir + os.pathsep + os.environ.get("PATH", "")

    server = ThreadingHTTPServer(("127.0.0.1", 0), AnalyzeHandler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    global _window
    bg = _resolve_background_color("loudness-theme")
    icon = str(_ICON_PATH) if _ICON_PATH.exists() else None
    _window = webview.create_window(
        "Loudness Analyzer (BS.1770 / EBU R128)",
        url=f"http://127.0.0.1:{port}/index.html",
        width=1100,
        height=800,
        background_color=bg,
    )
    webview.start(icon=icon)
    server.shutdown()


if __name__ == "__main__":
    main()
