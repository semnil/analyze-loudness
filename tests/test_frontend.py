"""Run frontend UI tests in a headless Chromium browser via Playwright.

Starts a local HTTP server to serve the test HTML, then uses Playwright
to open the page and read test results from window._testResult.
"""

import threading
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
from urllib.parse import unquote

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_REQUEST_QUEUE_SIZE = 64

try:
    from playwright.sync_api import expect, sync_playwright
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
    class _Server(HTTPServer):
        request_queue_size = _REQUEST_QUEUE_SIZE

    server = _Server(("127.0.0.1", 0), handler_cls)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield port
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


@pytest.mark.skipif(not _HAS_PLAYWRIGHT, reason="playwright not installed")
@pytest.mark.parametrize("slow_update_reply", [False, True])
def test_frontend_ui(_test_server, slow_update_reply):
    """Execute frontend tests in a headless Chromium browser."""
    port = _test_server
    url = f"http://127.0.0.1:{port}/tests/frontend/test_ui.html"

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        if slow_update_reply:
            page.add_init_script("""window.delayedUpdateReply = false;
                const parse = Response.prototype.json;
                Response.prototype.json = async function(...args) {
                    const data = await parse.apply(this, args);
                    const suites = document.querySelectorAll('#test-output .suite');
                    const suite = suites.length && suites[suites.length - 1].textContent;
                    if (!window.delayedUpdateReply && suite && suite.includes('Update: accepted install') && data.available) {
                        window.delayedUpdateReply = true;
                        await new Promise(resolve => setTimeout(resolve, 250));
                    }
                    return data;
                };""")

        console_msgs = []
        page.on("console", lambda msg: console_msgs.append(msg.text))

        page.goto(url, wait_until="domcontentloaded")
        page.wait_for_function("window._testResult !== undefined", timeout=10000)

        result = page.evaluate("window._testResult")
        dom_text = page.evaluate("document.getElementById('test-output').innerText")
        if slow_update_reply:
            assert page.evaluate("window.delayedUpdateReply") is True
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
        request_queue_size = _REQUEST_QUEUE_SIZE

    server = _Server(("127.0.0.1", 0), gui_mod.AnalyzeHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


@pytest.mark.skipif(not _HAS_PLAYWRIGHT, reason="playwright not installed")
def test_file_drop_sends_a_non_ascii_name_percent_encoded(monkeypatch):
    import sys

    server = _app_server("analyze_loudness.gui")
    gui = sys.modules["analyze_loudness.gui"]
    monkeypatch.setattr(gui._updater, "status", lambda: {"supported": False, "launch_check": False})
    requests = []

    def upload(route):
        name = route.request.headers["x-filename"]
        requests.append(name)
        route.fulfill(json={"uploaded": True, "path": "/uploaded/" + unquote(name)})

    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            try:
                page = browser.new_page(locale="en-US")
                page.route("**/upload", upload)
                page.goto(f"http://127.0.0.1:{server.server_port}/index.html")
                page.evaluate("window.analyzeUpdate.ready")
                page.evaluate("""() => {
                    const data = new DataTransfer();
                    data.items.add(new File(['audio'], '日本語 track.wav', {type: 'audio/wav'}));
                    window.dispatchEvent(new DragEvent('drop', {dataTransfer: data}));
                }""")
                expect(page.locator("#url-input")).to_have_value("/uploaded/日本語 track.wav")
                assert requests == ["%E6%97%A5%E6%9C%AC%E8%AA%9E%20track.wav"]
            finally:
                browser.close()
    finally:
        server.shutdown()
        server.server_close()


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
            page.wait_for_function("!_isBusy")
            assert "Failed to fetch" in page.inner_text("#status.error")
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
            page.wait_for_function("!_isBusy")
            assert "Failed to fetch" in page.inner_text("#status.error")
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


_ROLE_FACES = {
    "browse-btn": "--neutral-bg",
    "clear-btn": "--neutral-bg",
    "add-btn": "--add-bg",
    "submit-btn": "--primary-bg",
    "load-btn": "--load-bg",
}
_BACKGROUND_JS = "(id) => getComputedStyle(document.getElementById(id)).backgroundColor"


def _luminance(css_rgb):
    def channel(v):
        v /= 255
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
    r, g, b = (int(v) for v in css_rgb[css_rgb.index("(") + 1:css_rgb.index(")")].split(",")[:3])
    return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b)


@pytest.mark.skipif(not _HAS_PLAYWRIGHT, reason="playwright not installed")
@pytest.mark.parametrize("scheme", ["light", "dark"])
def test_buttons_show_the_face_of_their_role(scheme):
    """The input bar and compare bar buttons take their role's face from
    common.css, Analyze and Add Track have a face no other button has, hover
    lightens a face in the dark theme, and Browse and Load JSON carry an icon."""
    server = _app_server("analyze_loudness.gui")
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(color_scheme=scheme, reduced_motion="reduce")
            page.goto(f"http://127.0.0.1:{server.server_address[1]}/index.html")
            page.wait_for_load_state("networkidle")
            for source in ("https://example.com/a", "/music/b.wav"):
                page.fill("#url-input", source)
                page.click("#add-btn")
            page.mouse.move(0, 0)
            faces = {}
            for button, var in _ROLE_FACES.items():
                face = page.evaluate(_BACKGROUND_JS, button)
                assert face != "rgba(0, 0, 0, 0)", button
                assert face == page.evaluate(_RESOLVE_VAR_JS, var), button
                faces[button] = face
            for button in ("submit-btn", "add-btn"):
                assert list(faces.values()).count(faces[button]) == 1, button
            for button, face in faces.items():
                page.hover("#" + button)
                hovered = page.evaluate(_BACKGROUND_JS, button)
                assert hovered != face, button
                if scheme == "dark":
                    assert _luminance(hovered) > _luminance(face), button
                page.mouse.move(0, 0)
            assert page.locator("#browse-btn > svg.inline-icon").count() == 1
            assert page.locator("#load-btn > svg.inline-icon").count() == 1
            browser.close()
    finally:
        server.shutdown()
        server.server_close()


_OVERFLOW_JS = """() => {
  const bar = document.getElementById("analyze-form").getBoundingClientRect();
  let worst = -Infinity;
  for (const el of document.querySelectorAll("#analyze-form > button, #analyze-form > input")) {
    const range = document.createRange();
    range.selectNodeContents(el);
    const right = Math.max(el.getBoundingClientRect().right, range.getBoundingClientRect().right);
    worst = Math.max(worst, right - Math.min(bar.right, window.innerWidth));
  }
  return worst;
}"""


def test_style_css_defines_the_same_variables_for_both_themes():
    """A variable that only one theme of style.css defines leaves the other
    theme on the value of common.css, or on none."""
    import re
    css = (_PROJECT_ROOT / "frontend" / "style.css").read_text(encoding="utf-8")
    root = re.search(r":root\s*\{([^}]*)\}", css).group(1)
    dark = re.search(r'\[data-theme="dark"\]\s*\{([^}]*)\}', css).group(1)
    names = lambda body: sorted(re.findall(r"(--[\w-]+)\s*:", body))
    assert names(root) == names(dark)
    assert "--result-title-fg" in names(root)


_RESULT_ROW_JS = """() => {
  const row = document.querySelector("#results .title-row");
  const title = row.firstElementChild;
  const saves = Array.from(row.querySelectorAll(".save-btn"));
  const box = (el) => el.getBoundingClientRect();
  const shape = (el) => { const s = getComputedStyle(el);
    return [s.minHeight, s.paddingTop, s.paddingRight, s.borderTopLeftRadius, s.fontSize]; };
  return {
    title: [title.tagName, title.className],
    titleLeft: box(title).left - box(row).left,
    savesRight: box(row).right - box(saves[saves.length - 1]).right,
    saveShapes: saves.map(shape),
    copyShape: shape(document.querySelector("#status .copy-btn")),
    barShape: shape(document.getElementById("clear-btn")),
  };
}"""
_TITLE_ROW_FITS_JS = """() => {
  const row = document.querySelector("#results .title-row");
  const title = row.querySelector(".result-title");
  return row.scrollWidth <= row.clientWidth && title.scrollWidth <= title.clientWidth;
}"""
_FACE_JS = """(sel) => { const s = getComputedStyle(document.querySelector(sel)); return [s.backgroundColor, s.color]; }"""
_RENDER_RESULT_JS = ("render({title: 'Test Video', summary: {duration_sec: 600, frames: 5999, integrated: -18.1, "
                     "true_peak: 0.8, lra: 9.3, short_term: {median: -19.4, mean: -20.5, p10: -24.1, p90: -15.4}, "
                     "momentary: {median: -20.8, mean: -21.3, p10: -26.9, p90: -14.4}, silence_pct: 1.0}, "
                     "series: {t: [0.1, 0.2, 0.3], S: [-20, -21, -22], M: [-21, -22, -23]}, "
                     "meta: {version: '1.0.0', analyzed_at: '2026-01-01T00:00:00Z', source_url: 'https://example.com/a'}})")


def _contrast(a, b):
    hi, lo = sorted((_luminance(a), _luminance(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


@pytest.mark.skipif(not _HAS_PLAYWRIGHT, reason="playwright not installed")
@pytest.mark.parametrize("scheme", ["light", "dark"])
def test_result_title_and_buttons_take_the_common_look(scheme):
    """The result title is an h2 on the left with the save buttons on the
    right; the save buttons wear the primary face and, like Copy in an error
    line, the shape of the compare bar's buttons; Copy's label keeps 4.5:1
    with and without hover (common.css)."""
    server = _app_server("analyze_loudness.gui")
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(color_scheme=scheme, reduced_motion="reduce")
            page.add_init_script("Object.defineProperty(navigator, 'clipboard', "
                                 "{value: {writeText: () => Promise.resolve()}, configurable: true})")
            page.goto(f"http://127.0.0.1:{server.server_address[1]}/index.html")
            page.wait_for_load_state("networkidle")
            page.evaluate(_RENDER_RESULT_JS)
            page.evaluate("showError('HTTP Error 403: Forbidden')")
            page.mouse.move(0, 0)
            row = page.evaluate(_RESULT_ROW_JS)
            assert row["title"] == ["H2", "result-title"]
            assert abs(row["titleLeft"]) < 1
            title = page.evaluate(_FACE_JS, "#results .result-title")[1]
            assert _contrast(title, page.evaluate("getComputedStyle(document.body).backgroundColor")) >= 4.5
            link = page.evaluate(_FACE_JS, "#results .meta-info a")[1]
            assert _contrast(link, page.evaluate("getComputedStyle(document.body).backgroundColor")) >= 4.5
            assert abs(row["savesRight"]) < 1
            for shape in row["saveShapes"] + [row["copyShape"]]:
                assert shape == row["barShape"]
            save = page.evaluate(_FACE_JS, ".save-btn")
            assert save[0] == page.evaluate(_RESOLVE_VAR_JS, "--primary-bg")
            page.hover(".save-btn")
            assert page.evaluate(_FACE_JS, ".save-btn")[0] == page.evaluate(_RESOLVE_VAR_JS, "--primary-bg-hover")
            page.mouse.move(0, 0)
            copy = page.evaluate(_FACE_JS, ".copy-btn")
            page.hover(".copy-btn")
            hovered = page.evaluate(_FACE_JS, ".copy-btn")
            assert hovered[0] != copy[0]
            for face in (copy, hovered):
                assert _contrast(*face) >= 4.5, face
            page.evaluate("document.querySelector('#results .result-title').textContent = "
                          "'https://example.com/' + 'a'.repeat(200)")
            page.set_viewport_size({"width": 480, "height": 700})
            assert page.evaluate(_TITLE_ROW_FITS_JS)
            browser.close()
    finally:
        server.shutdown()
        server.server_close()


@pytest.mark.skipif(not _HAS_PLAYWRIGHT, reason="playwright not installed")
@pytest.mark.parametrize("button", [0, 1], ids=["save_json", "save_image"])
@pytest.mark.parametrize("before", ["saved", "error"])
def test_cancelling_a_save_empties_the_status_line(button, before):
    """A cancelled file dialog leaves an empty status line that is not an error,
    whatever the line said before; an error reply still shows the error."""
    server = _app_server("analyze_loudness.gui")
    reply = {"saved": True, "path": "/saved/result"}
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(reduced_motion="reduce")
            for path in ("/save", "/save-image"):
                page.route("**" + path, lambda route: route.fulfill(json=reply))
            page.goto(f"http://127.0.0.1:{server.server_address[1]}/index.html")
            page.wait_for_load_state("networkidle")
            page.evaluate(_RENDER_RESULT_JS)
            save = page.locator(".save-btn").nth(button)
            status = page.locator("#status")
            if before == "saved":
                save.click()
                expect(status).to_contain_text("/saved/result")
            else:
                page.evaluate("showError('HTTP Error 403: Forbidden')")
                expect(status.locator(".copy-btn")).to_have_count(1)
            reply.clear()
            reply["saved"] = False
            save.click()
            expect(status).to_have_text("")
            expect(status).to_have_attribute("role", "status")
            assert not page.evaluate("document.getElementById('status').classList.contains('error')")
            reply["error"] = "disk full"
            save.click()
            expect(status).to_contain_text("disk full")
            expect(status).to_have_attribute("role", "alert")
            browser.close()
    finally:
        server.shutdown()
        server.server_close()


@pytest.mark.skipif(not _HAS_PLAYWRIGHT, reason="playwright not installed")
@pytest.mark.parametrize("save", ["saveResult", "saveImage"])
@pytest.mark.parametrize("write,line,error", [
    ("_setUpdateLock(true); statusEl.textContent = 'Downloading';", "Downloading", False),
    ("showError('Settings could not be saved');", "Settings could not be saved", True),
], ids=["update", "error"])
def test_cancelling_a_save_keeps_a_line_written_after_it_began(save, write, line, error):
    """When another line reaches the status while a save's file dialog is open,
    cancelling the dialog leaves that line; an error stays an error."""
    server = _app_server("analyze_loudness.gui")
    held = []
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(reduced_motion="reduce")
            for path in ("/save", "/save-image"):
                page.route("**" + path, lambda route: held.append(route))
            page.goto(f"http://127.0.0.1:{server.server_address[1]}/index.html")
            page.wait_for_load_state("networkidle")
            page.evaluate(_RENDER_RESULT_JS)
            with page.expect_request(lambda request: "/save" in request.url):
                page.evaluate("(name) => { window.running = window[name](lastRenderedData); }", save)
            page.evaluate(write)
            held[0].fulfill(json={"saved": False})
            page.evaluate("window.running")
            status = page.locator("#status")
            expect(status).to_contain_text(line)
            if error:
                expect(status).to_have_attribute("role", "alert")
                expect(status.locator(".copy-btn")).to_have_count(1)
            browser.close()
    finally:
        server.shutdown()
        server.server_close()


@pytest.mark.skipif(not _HAS_PLAYWRIGHT, reason="playwright not installed")
def test_input_bar_controls_stay_inside_the_window_around_the_wrap_width():
    """With two queued tracks, no input bar control or label runs past the bar
    or the window at the widths around where the bar wraps (common.css)."""
    server = _app_server("analyze_loudness.gui")
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1100, "height": 700})
            page.goto(f"http://127.0.0.1:{server.server_address[1]}/index.html")
            page.wait_for_load_state("networkidle")
            for source in ("https://example.com/a", "/music/b.wav"):
                page.fill("#url-input", source)
                page.click("#add-btn")
            for width in (660, 700, 740, 780, 820, 860, 900, 901, 1100):
                page.set_viewport_size({"width": width, "height": 700})
                assert page.evaluate(_OVERFLOW_JS) <= 0.5, width
            browser.close()
    finally:
        server.shutdown()
        server.server_close()


_FOCUSED_ROW_BUTTON_JS = """() => {
  const button = document.activeElement;
  const row = button && button.closest(".track-item");
  return row ? [Array.from(row.parentNode.children).indexOf(row), button.dataset.action] : null;
}"""


@pytest.mark.skipif(not _HAS_PLAYWRIGHT, reason="playwright not installed")
def test_queue_focus_keeps_its_place_across_redraws():
    """A focused queue row button keeps the focus at its place when the rows
    are redrawn on a system color scheme change under the auto theme, a
    language switch and a remove; after a move it follows its track, and at
    the top or the bottom the row itself takes it."""
    server = _app_server("analyze_loudness.gui")
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(color_scheme="light")
            page.goto(f"http://127.0.0.1:{server.server_address[1]}/index.html")
            page.wait_for_load_state("networkidle")
            for source in ("/music/a.wav", "/music/b.wav", "/music/c.wav", "/music/d.wav"):
                page.fill("#url-input", source)
                page.click("#add-btn")
            queue = lambda: [s.rsplit("/", 1)[1][0] for s in page.evaluate("compareQueue.map(q => q.label)")]
            page.locator(".track-item").nth(3).locator('[data-action="up"]').focus()
            page.emulate_media(color_scheme="dark")
            page.wait_for_function("document.documentElement.getAttribute('data-theme') === 'dark'")
            assert page.evaluate(_FOCUSED_ROW_BUTTON_JS) == [3, "up"]
            page.evaluate("window.i18n.setLang('ja')")
            assert page.evaluate(_FOCUSED_ROW_BUTTON_JS) == [3, "up"]
            for expected_queue, expected_focus in ((list("abdc"), [2, "up"]), (list("adbc"), [1, "up"]),
                                                   (list("dabc"), [0, None]), (list("dabc"), [0, None])):
                page.keyboard.press("Enter")
                assert queue() == expected_queue
                assert page.evaluate(_FOCUSED_ROW_BUTTON_JS) == expected_focus
            page.evaluate("window.i18n.setLang('en')")
            assert page.evaluate(_FOCUSED_ROW_BUTTON_JS) == [0, None]
            page.locator(".track-item").nth(2).locator('[data-action="down"]').focus()
            page.keyboard.press("Space")
            assert queue() == list("dacb")
            assert page.evaluate(_FOCUSED_ROW_BUTTON_JS) == [3, None]
            page.locator(".track-item").nth(3).locator('[data-action="remove"]').focus()
            page.keyboard.press("Enter")
            assert queue() == list("dac")
            assert page.evaluate(_FOCUSED_ROW_BUTTON_JS) == [2, "remove"]
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
@pytest.mark.parametrize("result", ["single", "compare"])
def test_saving_is_locked_while_an_update_installs(result):
    """An accepted update stops the input field and the save buttons, those
    redrawn meanwhile and one whose save was already running, until the install
    fails."""
    from analyze_loudness.compare import build_compare, truncated_stats
    from tests.test_chart_rendering import track
    data = track(-20, "First")
    stats = None
    if result == "compare":
        data = build_compare([data, track(-30, "Second")])
        stats = [truncated_stats(item) for item in data["compare"]["tracks"]]
    server = _app_server("analyze_loudness.gui")
    held = {}
    saves = []
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1100, "height": 800}, locale="en-US")
            page.on("dialog", lambda dialog: dialog.accept())
            page.on("request", lambda r: saves.append(r.url) if "/save" in r.url else None)
            page.route("**/update/status", lambda route: route.fulfill(
                json={"current": "1.0.0", "supported": True, "launch_check": False}))
            page.route("**/update/check", lambda route: route.fulfill(json={"available": True, "version": "9.9.9"}))
            page.route("**/update/install", lambda route: held.update(install=route))
            page.route("**/save", lambda route: held.update(save=route))
            page.route("**/save-image", lambda route: route.fulfill(json={"saved": False}))
            page.goto(f"http://127.0.0.1:{server.server_address[1]}/index.html")
            page.evaluate("window.analyzeUpdate.ready")
            page.evaluate("({data, stats}) => { if (stats) renderCompare(data, stats); else render(data); }",
                          {"data": data, "stats": stats})
            buttons = page.locator(".save-btn")
            buttons.nth(0).click()
            page.wait_for_function("document.querySelector('.save-btn').disabled")
            assert len(saves) == 1
            page.click("#settings-toggle")
            page.click("#settings-update-now")
            expect(page.locator("#status")).to_contain_text("Downloading update")
            expect(page.locator("#submit-btn")).to_be_disabled()
            expect(page.locator("#url-input")).to_be_disabled()
            assert held.get("install") is not None
            expect(buttons.nth(1)).to_be_disabled()
            buttons.nth(1).click(force=True)
            held["save"].fulfill(json={"saved": True, "path": "/saved/result"})
            expect(page.locator("#status")).to_contain_text("/saved/result")
            expect(buttons.nth(0)).to_be_disabled()
            page.evaluate("window.i18n.setLang('ja')")
            assert page.locator(".save-btn").count() == 2
            assert page.eval_on_selector_all(".save-btn", "bs => bs.every(b => b.disabled)")
            held["install"].fulfill(status=500, json={"error": "bad signature"})
            page.wait_for_selector("#status.error")
            assert page.eval_on_selector_all(".save-btn", "bs => bs.every(b => !b.disabled)")
            expect(page.locator("#url-input")).to_be_enabled()
            assert len(saves) == 1
            with page.expect_response("**/save-image"):
                buttons.nth(1).click()
            assert len(saves) == 2
            browser.close()
    finally:
        server.shutdown()
        server.server_close()


@pytest.mark.skipif(not _HAS_PLAYWRIGHT, reason="playwright not installed")
def test_a_running_save_keeps_its_button_off_until_it_ends():
    """When an update fails while a save runs, the button of that save stays off
    until the save ends, also across a redraw, and the other button comes back."""
    from tests.test_chart_rendering import track
    server = _app_server("analyze_loudness.gui")
    held = {}
    saves = []
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1100, "height": 800}, locale="en-US")
            page.on("dialog", lambda dialog: dialog.accept())
            page.on("request", lambda r: saves.append(r.url) if r.url.endswith("/save") else None)
            page.route("**/update/status", lambda route: route.fulfill(
                json={"current": "1.0.0", "supported": True, "launch_check": False}))
            page.route("**/update/check", lambda route: route.fulfill(json={"available": True, "version": "9.9.9"}))
            page.route("**/update/install", lambda route: held.update(install=route))
            page.route("**/save", lambda route: held.update(save=route))
            page.goto(f"http://127.0.0.1:{server.server_address[1]}/index.html")
            page.evaluate("window.analyzeUpdate.ready")
            page.evaluate("data => render(data)", track(-20, "First"))
            buttons = page.locator(".save-btn")
            buttons.nth(0).click()
            expect(buttons.nth(0)).to_be_disabled()
            page.click("#settings-toggle")
            page.click("#settings-update-now")
            expect(page.locator("#status")).to_contain_text("Downloading update")
            assert held.get("install") is not None
            held["install"].fulfill(status=500, json={"error": "bad signature"})
            page.wait_for_selector("#status.error")
            expect(buttons.nth(1)).to_be_enabled()
            expect(buttons.nth(0)).to_be_disabled()
            page.evaluate("window.i18n.setLang('ja')")
            expect(buttons.nth(0)).to_be_disabled()
            expect(buttons.nth(1)).to_be_enabled()
            buttons.nth(0).click(force=True)
            assert len(saves) == 1
            held["save"].fulfill(json={"saved": True, "path": "/saved/result"})
            expect(page.locator("#status")).to_contain_text("/saved/result")
            expect(buttons.nth(0)).to_be_enabled()
            browser.close()
    finally:
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
