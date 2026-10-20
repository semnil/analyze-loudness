"""Run frontend UI tests in a headless Chromium browser via Playwright.

Starts a local HTTP server to serve the test HTML, then uses Playwright
to open the page and read test results from window._testResult.
"""

import threading
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent

try:
    from playwright.sync_api import sync_playwright
    _HAS_PLAYWRIGHT = True
except ImportError:
    _HAS_PLAYWRIGHT = False


@pytest.fixture(scope="module")
def _test_server():
    """Serve the project root so test_ui.html can load frontend/ files."""
    handler_cls = type(
        "_H", (SimpleHTTPRequestHandler,),
        {
            "__init__": lambda self, *a, **kw: SimpleHTTPRequestHandler.__init__(
                self, *a, directory=str(_PROJECT_ROOT), **kw),
            "log_message": lambda self, *a: None,
        },
    )
    server = HTTPServer(("127.0.0.1", 0), handler_cls)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield port
    server.shutdown()


@pytest.mark.skipif(not _HAS_PLAYWRIGHT, reason="playwright not installed")
def test_frontend_ui(_test_server):
    """Execute frontend tests in a headless Chromium browser."""
    port = _test_server
    url = f"http://127.0.0.1:{port}/tests/frontend/test_ui.html"

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        console_msgs = []
        page.on("console", lambda msg: console_msgs.append(msg.text))

        page.goto(url, wait_until="domcontentloaded")
        page.wait_for_function("window._testResult !== undefined", timeout=10000)

        result = page.evaluate("window._testResult")
        dom_text = page.evaluate("document.getElementById('test-output').innerText")
        browser.close()

    assert result, "window._testResult was not set by the test runner"
    total = result["passed"] + result["failed"]

    assert total > 0, "No tests were executed"
    if result["failed"] > 0:
        fail_lines = [ln for ln in dom_text.split("\n") if "FAIL" in ln]
        pytest.fail(
            f"{result['failed']}/{total} frontend tests failed:\n"
            + "\n".join(fail_lines)
        )
    print(f"\nFrontend tests: {result['passed']}/{total} passed")


def _app_server(gui_module_name):
    """Serve the real index.html, style.css and common.css through the app's handler."""
    import importlib
    import sys
    from http.server import ThreadingHTTPServer
    from unittest.mock import MagicMock
    saved = sys.modules.get("webview")
    sys.modules["webview"] = MagicMock()
    try:
        gui_mod = importlib.import_module(gui_module_name)
    finally:
        if saved is None:
            del sys.modules["webview"]
        else:
            sys.modules["webview"] = saved

    class _Server(ThreadingHTTPServer):
        request_queue_size = 64

    server = _Server(("127.0.0.1", 0), gui_mod.AnalyzeHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


@pytest.mark.skipif(not _HAS_PLAYWRIGHT, reason="playwright not installed")
def test_theme_and_submit_labels_follow_the_state_after_load_and_language_switch():
    """main.js alone writes the theme button's accessible name and the submit
    button's text, so the translation pass of i18n.js at DOMContentLoaded and on
    a language switch does not replace them."""
    server = _app_server("analyze_loudness.gui")
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            page = browser.new_page(locale="ja-JP")
            page.goto(f"http://127.0.0.1:{server.server_address[1]}/index.html")
            page.wait_for_load_state("networkidle")
            theme_state = "window.i18n.t('theme.aria_state.' + _themeMode)"
            assert page.evaluate("window.i18n.lang()") == "ja"
            assert page.get_attribute("#theme-toggle", "aria-label") == page.evaluate(theme_state)
            assert page.inner_text("#submit-btn") == page.evaluate("window.i18n.t('btn.analyze')")
            page.click("#lang-toggle")
            assert page.evaluate("window.i18n.lang()") == "en"
            assert page.get_attribute("#theme-toggle", "aria-label") == page.evaluate(theme_state)
            assert page.inner_text("#submit-btn") == page.evaluate("window.i18n.t('btn.analyze')")
            browser.close()
    finally:
        server.shutdown()
        server.server_close()


@pytest.mark.skipif(not _HAS_PLAYWRIGHT, reason="playwright not installed")
def test_running_analysis_keeps_its_cancel_button_across_a_language_switch():
    server = _app_server("analyze_loudness.gui")
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            page = browser.new_page(locale="en-US")
            held = []
            page.route("**/analyze", lambda route: held.append(route))
            page.goto(f"http://127.0.0.1:{server.server_address[1]}/index.html")
            page.wait_for_load_state("networkidle")
            try:
                page.fill("#url-input", "x.wav")
                page.click("#submit-btn")
                page.wait_for_function("_isBusy")
                page.click("#lang-toggle")
                assert page.evaluate("window.i18n.lang()") == "ja"
                assert page.evaluate("_isBusy") is True
                assert page.inner_text("#submit-btn") == page.evaluate("window.i18n.t('btn.cancel')")
                assert page.get_attribute("#submit-btn", "aria-label") == page.evaluate("window.i18n.t('btn.cancel.aria')")
            finally:
                for route in held:
                    route.abort()
            browser.close()
    finally:
        server.shutdown()
        server.server_close()


@pytest.mark.skipif(not _HAS_PLAYWRIGHT, reason="playwright not installed")
def test_opening_a_json_file_keeps_its_loading_button_across_a_language_switch():
    server = _app_server("analyze_loudness.gui")
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            page = browser.new_page(locale="en-US")
            held = []
            page.route("**/load", lambda route: held.append(route))
            page.goto(f"http://127.0.0.1:{server.server_address[1]}/index.html")
            page.wait_for_load_state("networkidle")
            try:
                page.click("#load-btn")
                page.wait_for_function("_isBusy")
                page.click("#lang-toggle")
                assert page.evaluate("window.i18n.lang()") == "ja"
                assert page.inner_text("#submit-btn") == page.evaluate("window.i18n.t('btn.loading')")
                assert page.get_attribute("#submit-btn", "aria-label") is None
                assert page.is_disabled("#submit-btn")
            finally:
                for route in held:
                    route.abort()
            browser.close()
    finally:
        server.shutdown()
        server.server_close()


_RESOLVE_VAR_JS = """(name) => {
  const probe = document.createElement("div");
  probe.style.background = "var(" + name + ")";
  document.body.appendChild(probe);
  const value = getComputedStyle(probe).backgroundColor;
  probe.remove();
  return value;
}"""


@pytest.mark.skipif(not _HAS_PLAYWRIGHT, reason="playwright not installed")
@pytest.mark.parametrize("scheme", ["light", "dark"])
def test_interactive_states_follow_stylesheet_order(scheme):
    """Rules in common.css load before style.css; the states they style still win."""
    server = _app_server("analyze_loudness.gui")
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(color_scheme=scheme, reduced_motion="reduce")
            page.goto(f"http://127.0.0.1:{server.server_address[1]}/index.html")
            page.wait_for_load_state("networkidle")
            btn_bg = "getComputedStyle(document.getElementById('submit-btn')).backgroundColor"

            page.evaluate("document.getElementById('submit-btn').classList.add('cancelling')")
            page.hover("#submit-btn")
            assert page.evaluate(btn_bg) == page.evaluate(_RESOLVE_VAR_JS, "--danger-hover")

            page.mouse.move(0, 0)
            page.evaluate("document.activeElement && document.activeElement.blur()")
            for _ in range(10):
                page.keyboard.press("Tab")
                if page.evaluate("document.activeElement && document.activeElement.id") == "url-input":
                    break
            outline = page.evaluate(
                "(() => { const s = getComputedStyle(document.getElementById('url-input'));"
                " return [s.outlineStyle, s.outlineWidth]; })()")
            assert outline == ["solid", "2px"]
            browser.close()
    finally:
        server.shutdown()
        server.server_close()


@pytest.mark.skipif(not _HAS_PLAYWRIGHT, reason="playwright not installed")
def test_outside_press_keeps_escape_in_the_settings_dialog():
    """A real press outside the settings dialog does not move focus: Escape
    after it still reaches the dialog while a check holds the dialog open, and
    focus returns to the settings button when the press closes the dialog."""
    import sys
    server = _app_server("analyze_loudness.gui")
    gui = sys.modules["analyze_loudness.gui"]
    release = threading.Event()
    saved = (gui._updater.status, gui._updater.check)
    gui._updater.status = lambda: {"current": "1.4.1", "supported": True, "launch_check": False}
    gui._updater.check = lambda: release.wait(10) and None
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1100, "height": 800})
            gui._ui_settings.update({"lang": "en"})
            page.goto(f"http://127.0.0.1:{server.server_address[1]}/index.html")
            page.evaluate("window.analyzeUpdate.ready")
            page.evaluate("window.cancelled = false; activeAbort = { abort: () => { window.cancelled = true; } };")
            page.focus("#settings-toggle")
            page.keyboard.press("Enter")
            page.focus("#settings-update-now")
            page.keyboard.press("Enter")
            page.wait_for_function("document.getElementById('settings-update-now').disabled")
            page.mouse.click(5, 5)
            page.keyboard.press("Escape")
            assert page.evaluate("window.cancelled") is False
            assert page.is_visible(".settings-box")
            release.set()
            page.wait_for_function("!document.getElementById('settings-update-now').disabled")
            page.mouse.click(5, 5)
            assert not page.is_visible(".settings-box")
            assert page.evaluate("document.activeElement.id") == "settings-toggle"
            browser.close()
    finally:
        release.set()
        gui._updater.status, gui._updater.check = saved
        server.shutdown()
        server.server_close()


@pytest.mark.skipif(not _HAS_PLAYWRIGHT, reason="playwright not installed")
def test_theme_and_language_carry_over_to_a_new_page():
    """The theme and the language picked on one page are what the next page,
    with empty webview storage, starts with, and the window color follows."""
    import json
    import sys
    import time
    from analyze_common.ui_settings import BG_DARK
    server = _app_server("analyze_loudness.gui")
    gui = sys.modules["analyze_loudness.gui"]
    url = f"http://127.0.0.1:{server.server_address[1]}/index.html"

    def stored():
        try:
            return json.loads(gui._settings.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return {}

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            first = browser.new_context(color_scheme="light", locale="en-US").new_page()
            first.goto(url)
            first.wait_for_load_state("networkidle")
            first.click("#theme-toggle")
            first.click("#theme-toggle")
            first.click("#lang-toggle")
            deadline = time.monotonic() + 10
            while stored() != {"theme": "dark", "lang": "ja"} and time.monotonic() < deadline:
                time.sleep(0.05)
            assert stored() == {"theme": "dark", "lang": "ja"}

            second = browser.new_context(color_scheme="light", locale="en-US").new_page()
            # The first data-theme the page sets: the one painted before main.js runs.
            second.add_init_script(
                "new MutationObserver(function (records, observer) {"
                " window.firstTheme = document.documentElement.getAttribute('data-theme');"
                " observer.disconnect(); }).observe(document, {attributes: true, subtree: true, attributeFilter: ['data-theme']});")
            second.goto(url)
            second.wait_for_load_state("networkidle")
            assert second.evaluate("window.firstTheme") == "dark"
            assert second.evaluate("document.documentElement.getAttribute('data-theme')") == "dark"
            assert second.evaluate("document.documentElement.lang") == "ja"
            assert second.evaluate("window.i18n.lang()") == "ja"
            assert second.evaluate("localStorage.length") == 0
            assert gui._ui_settings.background_color() == BG_DARK
            browser.close()
    finally:
        server.shutdown()
        server.server_close()
