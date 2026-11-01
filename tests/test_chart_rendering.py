"""Render real chart scripts and export their pixels in Chromium."""

import base64
import struct

import numpy as np
import pytest

from analyze_loudness.compare import build_compare, build_result, truncated_stats
from tests.test_frontend import _HAS_PLAYWRIGHT, _app_server


def track(level, title):
    times = np.arange(1, 6002) * 0.1
    short = np.full(len(times), level, dtype=float)
    short[:29] = -120.7
    short[3000:6000] = -120.7
    momentary = short.copy()
    summary = {"integrated": level if level > -60 else None, "true_peak": -1, "lra": 4}
    return build_result(times, momentary, short, summary, title, "https://example.com/" + title)


@pytest.mark.skipif(not _HAS_PLAYWRIGHT, reason="playwright not installed")
@pytest.mark.parametrize("kind, theme", [("single", "light"), ("silent", "dark"), ("compare", "light"), ("compare", "dark")])
def test_real_charts_and_png_export(kind, theme, monkeypatch):
    from analyze_loudness import gui
    from playwright.sync_api import sync_playwright

    monkeypatch.setattr(gui._updater, "status", lambda: {"supported": False, "launch_check": False})
    data = track(-120.7 if kind == "silent" else -20, "A" * 200)
    stats = None
    if kind == "compare":
        data = build_compare([data, track(-30, "Second")])
        stats = [truncated_stats(item) for item in data["compare"]["tracks"]]
    server = _app_server("analyze_loudness.gui")
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            try:
                page = browser.new_page(viewport={"width": 1100, "height": 800}, device_scale_factor=2, locale="en-US")
                errors = []
                page.on("pageerror", lambda error: errors.append(str(error)))
                page.goto(f"http://127.0.0.1:{server.server_port}/index.html")
                page.evaluate("window.analyzeUpdate.ready")
                page.evaluate("mode => { window.i18n.setLang('en'); _setThemeMode(mode); }", theme)
                page.evaluate("({data, stats}) => { clearResults(); if (stats) renderCompare(data, stats); else render(data); }",
                              {"data": data, "stats": stats})
                page.evaluate("() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))")
                charts = page.evaluate("""() => chartCanvasRefs.map(ref => {
                    const canvas = ref.canvas;
                    const pixels = canvas.getContext('2d').getImageData(0, 0, canvas.width, canvas.height).data;
                    let ink = 0;
                    for (let i = 3; i < pixels.length; i += 4) if (pixels[i]) ink++;
                    return {width: canvas.width, height: canvas.height, ink};
                })""")
                assert len(charts) == (5 if kind == "compare" else 4)
                assert all(chart["width"] > 0 and chart["height"] > 0 and chart["ink"] > 0 for chart in charts)
                if kind != "silent":
                    assert page.evaluate(r"""() => {
                        const canvas = document.querySelector('.segments-canvas');
                        const ctx = canvas.getContext('2d');
                        const color = lastRenderedData.compare ? getTheme().trackColors[0] : getTheme().barFill;
                        const sample = document.createElement('canvas').getContext('2d');
                        sample.fillStyle = color;
                        sample.globalAlpha = lastRenderedData.compare ? 0.75 : 1;
                        sample.fillRect(0, 0, 1, 1);
                        const rgb = sample.getImageData(0, 0, 1, 1).data;
                        const pixels = ctx.getImageData(0, 0, canvas.width, canvas.height).data;
                        let bars = 0;
                        for (let i = 0; i < pixels.length; i += 4)
                            if (pixels[i] === rgb[0] && pixels[i+1] === rgb[1] && pixels[i+2] === rgb[2] && pixels[i+3]) bars++;
                        return bars;
                    }""") > 0
                exported = page.evaluate("""async data => {
                    const url = captureImage(data);
                    const image = new Image();
                    image.src = url;
                    await image.decode();
                    const canvas = document.createElement('canvas');
                    canvas.width = image.width; canvas.height = image.height;
                    const ctx = canvas.getContext('2d');
                    ctx.drawImage(image, 0, 0);
                    const colors = [getTheme().gateSilent, data.compare ? getTheme().trackColors[0] : getTheme().accent]
                        .map(color => color.slice(1).match(/../g).map(value => parseInt(value, 16)));
                    const pixels = ctx.getImageData(0, 480, canvas.width, canvas.height - 480).data;
                    let chartPixels = 0;
                    for (let i = 0; i < pixels.length; i += 4)
                        if (colors.some(color => color.every((value, channel) => pixels[i+channel] === value))) chartPixels++;
                    return {url, chartPixels};
                }""", data)
                assert exported["chartPixels"] > 0
                png = base64.b64decode(exported["url"].split(",", 1)[1])
                assert png[:8] == b"\x89PNG\r\n\x1a\n"
                width, height = struct.unpack(">II", png[16:24])
                assert width == 2200
                assert height > 1500
                assert errors == []
            finally:
                browser.close()
    finally:
        server.shutdown()
        server.server_close()
