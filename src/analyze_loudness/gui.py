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
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import webview

from analyze_loudness import _json_safe
from analyze_loudness.analysis import run_ebur128
from analyze_loudness.compare import (
    build_compare, build_result, is_compare, truncated_stats,
    validate_compare, validate_single, validate_tracks,
)
from analyze_loudness.download import (
    AUDIO_EXTENSIONS, compute_middle, is_network_path, is_url, local_path, probe_duration,
    resolve_source, sanitize_filename,
)
from analyze_loudness.update import UPDATE_CONFIG
from analyze_common.settings import SETTINGS_NAME, SettingsStore, settings_dir
from analyze_common.ui_settings import UiSettings, show_window_color_until_paint
from analyze_common.update import UpdateError, Updater, hold_instance_mutex
from analyze_common.web import COMMON_CSS, UPDATE_JS


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

# Files dropped on the window (/upload) live here for the session.
_upload_dir = tempfile.mkdtemp(prefix="loudness_upload_")
atexit.register(shutil.rmtree, _upload_dir, True)


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
        if path in (_cache_dir, _upload_dir):
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

# One store, so the update settings and the theme / language share its lock.
_settings = SettingsStore(settings_dir(UPDATE_CONFIG.product) / SETTINGS_NAME)
_updater = Updater(UPDATE_CONFIG, _settings)
_ui_settings = UiSettings(_settings)


def _exit_now() -> None:
    """End the process at once, without the interpreter's shutdown, after
    doing the atexit work here.  Called once a macOS update has replaced the
    bundle on disk, from which nothing more is imported."""
    shutil.rmtree(_cache_dir, True)
    shutil.rmtree(_upload_dir, True)
    _cleanup_orphan_tempdirs()
    os._exit(0)


_CACHE_MAX_ENTRIES = 10
_result_cache: "OrderedDict[tuple, str]" = OrderedDict()  # (url, duration) -> json path
# In-memory map for externally loaded JSON.  Kept separate from _result_cache
# so /load payloads never touch _cache_dir on disk.
_loaded_cache_data: "OrderedDict[tuple, dict]" = OrderedDict()
_cache_lock = threading.Lock()
_dialog_lock = threading.Lock()


def _cache_key(source: str, duration: float | None) -> tuple:
    """URL + duration; a local file adds its modification time, so an edited
    file is analysed again."""
    if is_url(source):
        return (source, duration)
    try:
        return (source, duration, os.path.getmtime(source))
    except OSError:
        return (source, duration, None)


def _cache_file(url: str, duration: float | None) -> str | None:
    key = _cache_key(url, duration)
    with _cache_lock:
        path = _result_cache.get(key)
        if path:
            _result_cache.move_to_end(key)
    return path if path and os.path.exists(path) else None


def _cache_get(url: str, duration: float | None) -> dict | None:
    key = _cache_key(url, duration)
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
    key = _cache_key(url, duration)
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


def _compare_stats(doc: dict) -> list[dict]:
    return _json_safe([truncated_stats(track) for track in doc["compare"]["tracks"]])


class _ClientDisconnected(Exception):
    """Raised when the client aborts the NDJSON stream."""


class AnalyzeHandler(SimpleHTTPRequestHandler):
    """Serves frontend files and handles /analyze POST requests."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(FRONTEND_DIR), **kwargs)

    _MAX_BODY_BYTES = 64 * 1024 * 1024  # 64 MiB: large enough for full-resolution image payload
    # /load cap: room for a saved comparison of MAX_TRACKS tracks at the
    # longest length a /compare request body can carry.
    _MAX_LOAD_BYTES = 210 * 1024 * 1024
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

    # analyze_common's shared assets, which live outside FRONTEND_DIR.
    _COMMON_FILES = {
        "/common/common.css": (COMMON_CSS, "text/css; charset=utf-8"),
        "/common/update.js": (UPDATE_JS, "text/javascript; charset=utf-8"),
    }

    def do_GET(self):
        if not self._check_host():
            return
        path = self.path.split("?", 1)[0]
        if path == "/common/settings.js":
            self._send_settings_script()
            return
        common = self._COMMON_FILES.get(path)
        if common:
            self._send_common(*common)
            return
        super().do_GET()

    def _check_content_type(self) -> bool:
        """Accept only the Content-Type the frontend sends.  Browsers send
        cross-origin requests with these types only after a CORS preflight,
        which this server never answers."""
        expected = "application/octet-stream" if self.path == "/upload" else "application/json"
        content_type = self.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
        if content_type != expected:
            self._json_error(415, f"Content-Type must be {expected}")
            return False
        return True

    def _send_common(self, path, content_type):
        try:
            body = path.read_bytes()
        except OSError:
            self.send_error(404)
            return
        self._send_asset(body, content_type)

    def _send_settings_script(self):
        """The shared settings.js with the stored theme and language, read anew
        for every page load."""
        try:
            body = _ui_settings.script()
        except OSError:
            self.send_error(404)
            return
        self._send_asset(body, "text/javascript; charset=utf-8", no_store=True)

    def _send_asset(self, body: bytes, content_type: str, no_store: bool = False):
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        if no_store:
            self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        if not self._check_host():
            return
        if not self._check_content_type():
            return
        handlers = {
            "/save": self._handle_save,
            "/save-image": self._handle_save_image,
            "/load": self._handle_load,
            "/compare": self._handle_compare,
            "/browse": self._handle_browse,
            "/upload": self._handle_upload,
            "/settings": self._handle_settings,
            "/update/status": self._handle_update_status,
            "/update/settings": self._handle_update_settings,
            "/update/check": self._handle_update_check,
            "/update/install": self._handle_update_install,
        }
        if self.path in handlers:
            try:
                handlers[self.path]()
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
        # Anything scheme-like must be http(s); everything else is a local path.
        if "://" in url or url.lower().startswith("javascript:"):
            if not is_url(url):
                self._json_error(400, "'url' must use http or https scheme, or be a local file path")
                return
        elif is_network_path(url):
            self._json_error(400, "Network (UNC) paths are not accepted; copy the file to this computer")
            return
        else:
            url = local_path(url)
            if not os.path.isfile(url):
                self._json_error(400, f"File not found: {url}")
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
            src, title = resolve_source(url, workdir)
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

        result = build_result(t, M, S, summary_raw, title, url)
        _cache_put(url, duration_min, result)
        self._send_event("result", data=result)

    def _handle_compare(self):
        try:
            length = int(self.headers.get("Content-Length", 0))
        except (ValueError, TypeError):
            length = 0
        if length > self._MAX_BODY_BYTES:
            self._json_error(413, f"Comparison request exceeds {self._MAX_BODY_BYTES // (1024 * 1024)} MiB")
            return
        tracks = self._read_json_body().get("tracks")
        err = validate_tracks(tracks)
        if err:
            self._json_error(400, f"Invalid 'tracks': {err}")
            return
        doc = build_compare(tracks)
        self._json_response(200, {"data": doc, "stats": _compare_stats(doc)})

    _AUDIO_TYPES = (
        "Audio Video Files (" + ";".join("*" + extension for extension in AUDIO_EXTENSIONS) + ")",
    )

    def _handle_browse(self):
        if not _dialog_lock.acquire(blocking=False):
            self._json_error(409, "A dialog is already open")
            return
        try:
            result = _window.create_file_dialog(
                webview.OPEN_DIALOG,
                file_types=self._AUDIO_TYPES,
            )
        except Exception as e:
            traceback.print_exc()
            self._json_error(500, f"File dialog error: {e}")
            return
        finally:
            _dialog_lock.release()

        file_path = self._dialog_path(result)
        if not file_path:
            self._json_response(200, {"selected": False})
            return
        self._json_response(200, {"selected": True, "path": file_path})

    _MAX_UPLOAD = 500 * 1024 * 1024  # 500 MB

    def _handle_upload(self):
        """Store a dropped file (raw body, name in X-Filename) in _upload_dir."""
        try:
            length = int(self.headers.get("Content-Length", 0))
        except (ValueError, TypeError):
            self._json_error(400, "Invalid Content-Length")
            return
        if length <= 0:
            self._json_error(400, "Empty file")
            return
        if length > self._MAX_UPLOAD:
            self._json_error(413, "File too large (max 500 MB)")
            return

        from urllib.parse import unquote
        name = sanitize_filename(unquote(self.headers.get("X-Filename", "dropped_file")))
        extension = os.path.splitext(name)[1].lower()
        if extension not in AUDIO_EXTENSIONS:
            self._json_error(400, f"Unsupported file type: {extension or '(none)'}")
            return

        dest = os.path.join(_upload_dir, name)
        if os.path.commonpath([_upload_dir, os.path.abspath(dest)]) != _upload_dir:
            self._json_error(400, "Invalid filename")
            return
        stem, suffix = os.path.splitext(name)
        index = 1
        while os.path.exists(dest):
            dest = os.path.join(_upload_dir, f"{stem}_{index}{suffix}")
            index += 1

        remaining = length
        try:
            with open(dest, "wb") as f:
                while remaining > 0:
                    chunk = self.rfile.read(min(remaining, 65536))
                    if not chunk:
                        break
                    f.write(chunk)
                    remaining -= len(chunk)
        except (OSError, ValueError):
            self._discard(dest)
            self._json_error(400, "Invalid filename")
            return
        if remaining > 0:
            self._discard(dest)
            self._json_error(400, "Incomplete upload")
            return
        self._json_response(200, {"uploaded": True, "path": dest})

    @staticmethod
    def _discard(path: str) -> None:
        try:
            os.unlink(path)
        except OSError:
            pass

    def _handle_settings(self):
        """Store the theme or the language in the app's settings file."""
        try:
            values = _ui_settings.update(self._read_json_body())
        except ValueError as e:
            self._json_error(400, str(e))
            return
        except OSError as e:
            self._json_error(500, str(e))
            return
        self._json_response(200, values)

    def _handle_update_status(self):
        self._json_response(200, _updater.status())

    def _handle_update_settings(self):
        """Store the "Check at launch" setting in the app's settings file."""
        launch_check = self._read_json_body().get("launch_check")
        if not isinstance(launch_check, bool):
            self._json_error(400, "Missing or invalid 'launch_check' field")
            return
        try:
            _updater.set_launch_check(launch_check)
        except UpdateError as e:
            self._json_error(500, str(e))
            return
        self._json_response(200, {"launch_check": _updater.launch_check()})

    def _handle_update_check(self):
        try:
            version = _updater.check()
        except UpdateError as e:
            self._json_error(502, str(e))
            return
        if version is None:
            self._json_response(200, {"available": False})
        else:
            self._json_response(200, {"available": True, "version": version})

    def _handle_update_install(self):
        """Download, verify and hand off the update; the app then exits."""
        version = self._read_json_body().get("version")
        if not isinstance(version, str) or not version:
            self._json_error(400, "Missing or invalid 'version' field")
            return
        try:
            handoff = _updater.install(version)
        except UpdateError as e:
            self._json_error(500, str(e))
            return
        if handoff.exit_mode is None:
            self._json_response(200, {"installed": True, "restart_error": handoff.restart_error})
            return
        self._json_response(200, {"restarting": True})
        if handoff.exit_mode == "immediate":
            _exit_now()
        elif _window is not None:
            _window.destroy()

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

        # A comparison's tracks carry cut series, so they never enter the
        # single-result cache.
        if is_compare(data):
            err = validate_compare(data)
            if err:
                self._json_error(400, err)
                return
            self._json_response(200, {"loaded": True, "data": data,
                                      "stats": _compare_stats(data)})
            return

        err = validate_single(data)
        if err:
            self._json_error(400, err)
            return

        # Cache loaded data for reuse.  Only URL sources: a local file's cache
        # key carries its modification time, which a saved result does not.
        meta = data.get("meta")
        src = meta.get("source_url") if isinstance(meta, dict) else None
        if isinstance(src, str) and is_url(src):
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


def _set_application_user_model_id():
    """Set Windows AppUserModelID so the taskbar shows the application icon."""
    if sys.platform == "win32":
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
            "com.semnil.loudness-analyzer"
        )


class _HTTPServer(ThreadingHTTPServer):
    """Loopback server whose listen backlog holds the burst of connections a
    webview opens while loading the page and its scripts in parallel."""

    request_queue_size = 64


def main():
    _set_application_user_model_id()
    hold_instance_mutex(UPDATE_CONFIG.mutex_name)
    # When frozen, add bundled binaries (ffmpeg, ffprobe, deno) to PATH
    if getattr(sys, "frozen", False):
        bin_dir = str(Path(sys._MEIPASS) / "bin")
        os.environ["PATH"] = bin_dir + os.pathsep + os.environ.get("PATH", "")

    server = _HTTPServer(("127.0.0.1", 0), AnalyzeHandler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    global _window
    bg = _ui_settings.background_color()
    # The window icon is Windows-only; on macOS the Dock icon comes from the
    # .app bundle, so passing it here would override the bundle icon.
    icon = str(_ICON_PATH) if (sys.platform == "win32" and _ICON_PATH.exists()) else None
    _window = webview.create_window(
        "Loudness Analyzer (BS.1770 / EBU R128)",
        url=f"http://127.0.0.1:{port}/index.html",
        width=1100,
        height=800,
        background_color=bg,
    )
    show_window_color_until_paint(_window)
    webview.start(icon=icon)
    server.shutdown()


if __name__ == "__main__":
    main()
