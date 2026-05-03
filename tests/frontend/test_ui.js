/**
 * Frontend UI tests for analyze-loudness.
 *
 * Runs in the browser (test_ui.html) or headless via Deno/Playwright.
 * Tests UI state management by mocking fetch() and verifying DOM state.
 */

var _passed = 0;
var _failed = 0;
var _output = document.getElementById("test-output");

function _log(cls, text) {
  var el = document.createElement("div");
  el.className = cls;
  el.textContent = text;
  _output.appendChild(el);
}

function suite(name) { _log("suite", "--- " + name + " ---"); }

function assert(condition, msg) {
  if (condition) {
    _passed++;
    _log("pass", "  PASS: " + msg);
  } else {
    _failed++;
    _log("fail", "  FAIL: " + msg);
  }
}

function assertEqual(actual, expected, msg) {
  if (actual === expected) {
    _passed++;
    _log("pass", "  PASS: " + msg);
  } else {
    _failed++;
    _log("fail", "  FAIL: " + msg + " (got " + JSON.stringify(actual) + ", expected " + JSON.stringify(expected) + ")");
  }
}

// ------ Helpers ------

function resetState() {
  document.getElementById("url-input").value = "";
  document.getElementById("status").textContent = "";
  document.getElementById("status").className = "";
  document.getElementById("results").innerHTML = "";
  document.getElementById("results").className = "";
  _setBusy(false);
}

// Mock fetch — returns queued responses
var _fetchQueue = [];
var _origFetch = window.fetch;

function mockFetch(responseFn) {
  _fetchQueue.push(responseFn);
}

window.fetch = function(url, opts) {
  if (_fetchQueue.length > 0) {
    var fn = _fetchQueue.shift();
    return Promise.resolve(fn(url, opts));
  }
  return Promise.resolve(new Response("{}", { status: 200 }));
};

function makeJsonResponse(obj, status) {
  return new Response(JSON.stringify(obj), {
    status: status || 200,
    headers: { "Content-Type": "application/json" },
  });
}

function makeNdjsonResponse(events) {
  var body = events.map(function(e) { return JSON.stringify(e); }).join("\n") + "\n";
  var stream = new ReadableStream({
    start: function(controller) {
      controller.enqueue(new TextEncoder().encode(body));
      controller.close();
    },
  });
  return new Response(stream, {
    status: 200,
    headers: { "Content-Type": "application/x-ndjson" },
  });
}

function fakeResult(sourceUrl) {
  return {
    title: "Test Video",
    summary: {
      duration_sec: 600, frames: 5999,
      integrated: -18.1, true_peak: 0.8, lra: 9.3,
      short_term: { median: -19.4, mean: -20.5, p10: -24.1, p90: -15.4 },
      momentary: { median: -20.8, mean: -21.3, p10: -26.9, p90: -14.4 },
      silence_pct: 1.0,
    },
    series: { t: [0, 0.1, 0.2], S: [-20, -21, -22], M: [-21, -22, -23] },
    meta: {
      version: "1.0.0",
      analyzed_at: "2026-01-01T00:00:00Z",
      source_url: sourceUrl || "https://www.youtube.com/watch?v=test",
    },
  };
}

// ------ Tests ------

(async function runTests() {
  var urlInput = document.getElementById("url-input");
  var submitBtn = document.getElementById("submit-btn");
  var loadBtn = document.getElementById("load-btn");
  var statusEl = document.getElementById("status");
  var resultsEl = document.getElementById("results");

  // ================================================
  suite("fmt(): null / non-finite values render as ?");
  // ================================================

  assertEqual(fmt(null, 1), "?", "null -> ?");
  assertEqual(fmt(undefined, 1), "?", "undefined -> ?");
  assertEqual(fmt(NaN, 1), "?", "NaN -> ?");
  assertEqual(fmt(Infinity, 1), "?", "Infinity -> ?");
  assertEqual(fmt(-Infinity, 1), "?", "-Infinity -> ?");
  assertEqual(fmt(0, 1), "0.0", "0 -> 0.0");
  assertEqual(fmt(1.234, 1), "1.2", "1.234 -> 1.2");
  assertEqual(fmt(1.234, 2), "1.23", "1.234 with 2 decimals");
  assertEqual(fmt(1.5, 1, true), "+1.5", "showSign positive -> +1.5");
  assertEqual(fmt(-1.5, 1, true), "-1.5", "showSign negative keeps -");
  assertEqual(fmt(0, 1, true), "0.0", "showSign zero -> no sign");

  // ================================================
  suite("_setBusy: cancellable state");
  // ================================================

  resetState();
  _setBusy(true);
  assertEqual(_isBusy, true, "_isBusy true after _setBusy(true)");
  assertEqual(submitBtn.textContent, "Cancel", "Submit shows Cancel");
  assert(submitBtn.classList.contains("cancelling"), "Submit has cancelling class");
  assertEqual(submitBtn.disabled, false, "Submit enabled (cancellable)");
  assertEqual(loadBtn.disabled, true, "Load disabled when busy");

  _setBusy(false);
  assertEqual(_isBusy, false, "_isBusy false after _setBusy(false)");
  assertEqual(submitBtn.textContent, "Analyze", "Submit shows Analyze again");
  assert(!submitBtn.classList.contains("cancelling"), "Submit no longer cancelling");
  assertEqual(loadBtn.disabled, false, "Load re-enabled");

  // ================================================
  suite("_setBusy: non-cancellable (loading) state");
  // ================================================

  resetState();
  _setBusy(true, false);
  assertEqual(submitBtn.textContent, "Loading", "Submit shows Loading");
  assertEqual(submitBtn.disabled, true, "Submit disabled (non-cancellable)");
  assert(!submitBtn.classList.contains("cancelling"), "No cancelling class for loading");
  _setBusy(false);

  // ================================================
  suite("Submit empty URL is a no-op");
  // ================================================

  resetState();
  urlInput.value = "";
  document.getElementById("analyze-form").dispatchEvent(new Event("submit"));
  await new Promise(function(r) { setTimeout(r, 50); });
  assertEqual(_isBusy, false, "Empty submit does not enter busy state");
  assertEqual(statusEl.textContent, "", "No status text on empty submit");

  // ================================================
  suite("Submit URL renders result");
  // ================================================

  resetState();
  urlInput.value = "https://www.youtube.com/watch?v=test";
  mockFetch(function(url) {
    if (url.indexOf("/analyze") !== -1) {
      return makeNdjsonResponse([{ type: "result", data: fakeResult() }]);
    }
    return makeJsonResponse({});
  });
  document.getElementById("analyze-form").dispatchEvent(new Event("submit"));
  await new Promise(function(r) { setTimeout(r, 300); });
  assert(resultsEl.classList.contains("visible"), "Results made visible after analysis");
  assert(resultsEl.querySelector(".video-title") !== null, "Video title rendered");
  assertEqual(_isBusy, false, "Not busy after analysis completes");

  // ================================================
  suite("Submit failure (non-OK response) shows error");
  // ================================================

  resetState();
  urlInput.value = "https://www.youtube.com/watch?v=fail";
  mockFetch(function() {
    return makeJsonResponse({ error: "boom" }, 500);
  });
  document.getElementById("analyze-form").dispatchEvent(new Event("submit"));
  await new Promise(function(r) { setTimeout(r, 200); });
  assert(statusEl.classList.contains("error"), "Status flagged as error");
  assert(statusEl.textContent.indexOf("boom") !== -1, "Server error message surfaced");
  assertEqual(_isBusy, false, "Not busy after failure");

  // ================================================
  suite("Load JSON: loaded:false leaves URL untouched");
  // ================================================

  resetState();
  urlInput.value = "keep_me.mp4";
  mockFetch(function() {
    return makeJsonResponse({ loaded: false });
  });
  loadBtn.click();
  await new Promise(function(r) { setTimeout(r, 200); });
  assertEqual(urlInput.value, "keep_me.mp4", "URL preserved when dialog cancelled");
  assertEqual(_isBusy, false, "Not busy after cancelled dialog");

  // ================================================
  suite("Load JSON: loaded:true sets urlInput from meta.source_url");
  // ================================================

  resetState();
  mockFetch(function() {
    return makeJsonResponse({
      loaded: true,
      data: fakeResult("https://www.youtube.com/watch?v=loaded"),
    });
  });
  loadBtn.click();
  await new Promise(function(r) { setTimeout(r, 300); });
  assertEqual(urlInput.value, "https://www.youtube.com/watch?v=loaded", "urlInput populated from loaded meta");
  assert(resultsEl.classList.contains("visible"), "Loaded data rendered");

  // ================================================
  suite("Load JSON: server error surfaces error message");
  // ================================================

  resetState();
  mockFetch(function() {
    return makeJsonResponse({ error: "permission denied" }, 500);
  });
  loadBtn.click();
  await new Promise(function(r) { setTimeout(r, 200); });
  assert(statusEl.classList.contains("error"), "Status flagged as error on load failure");
  assert(statusEl.textContent.indexOf("permission denied") !== -1, "Load error message surfaced");

  // ================================================
  suite("Theme toggle cycles light -> dark -> auto");
  // ================================================

  resetState();
  _setThemeMode("light");
  assertEqual(document.documentElement.getAttribute("data-theme"), "light", "Theme starts light");
  document.getElementById("theme-toggle").click();
  assertEqual(document.documentElement.getAttribute("data-theme"), "dark", "Toggle goes to dark");
  document.getElementById("theme-toggle").click();
  // Auto resolves to light or dark depending on host environment
  var autoTheme = document.documentElement.getAttribute("data-theme");
  assert(autoTheme === "light" || autoTheme === "dark", "Auto resolves to light or dark");
  _setThemeMode("light");

  // ================================================
  suite("Lang toggle EN <-> JA persists in localStorage");
  // ================================================

  resetState();
  window.i18n.setLang("en");
  assertEqual(window.i18n.lang(), "en", "Lang starts en");
  document.getElementById("lang-toggle").click();
  assertEqual(window.i18n.lang(), "ja", "Lang toggled to ja");
  assertEqual(localStorage.getItem("loudness-lang"), "ja", "ja persisted in localStorage");
  document.getElementById("lang-toggle").click();
  assertEqual(window.i18n.lang(), "en", "Lang toggled back to en");
  assertEqual(localStorage.getItem("loudness-lang"), "en", "en persisted in localStorage");

  // ================================================
  suite("Lang dict completeness for required keys");
  // ================================================

  var requiredKeys = [
    "btn.analyze", "btn.cancel", "btn.loading", "btn.load_json",
    "err.no_result", "err.dialog_timeout", "err.stream_interrupted", "err.file_too_large",
    "err.charts_not_ready", "err.save_failed",
    "lang.title.en", "lang.title.ja",
    "tip.duration", "tip.integrated", "tip.chart_timeline",
    "tip.chart_histogram", "tip.chart_segments",
    "chart.timeline_title", "chart.hist_title", "chart.seg_title",
    "chart.no_data_silence",
  ];
  window.i18n.setLang("en");
  for (var i = 0; i < requiredKeys.length; i++) {
    var k = requiredKeys[i];
    assert(window.i18n.t(k) !== k, "EN dict has key " + k);
  }
  window.i18n.setLang("ja");
  for (var j = 0; j < requiredKeys.length; j++) {
    var kj = requiredKeys[j];
    assert(window.i18n.t(kj) !== kj, "JA dict has key " + kj);
  }
  // Verify lang.title.ja is actually translated (not English fallback)
  window.i18n.setLang("ja");
  var jaTitleJa = window.i18n.t("lang.title.ja");
  assert(jaTitleJa.indexOf("言語") !== -1 || jaTitleJa.indexOf("日本語") !== -1,
    "lang.title.ja in JA dict is Japanese text");
  window.i18n.setLang("en");

  // ================================================
  suite("_addTip / _hideTip lifecycle");
  // ================================================

  resetState();
  var anchor = document.createElement("span");
  anchor.textContent = "anchor";
  document.body.appendChild(anchor);
  _addTip(anchor, "tip body");
  assert(anchor.classList.contains("has-tip"), "Anchor gains has-tip class");
  assertEqual(anchor.tabIndex, 0, "Anchor is keyboard reachable (tabIndex 0)");
  // Trigger focus -> tip appears after debounce
  anchor.dispatchEvent(new FocusEvent("focus"));
  await new Promise(function(r) { setTimeout(r, 250); });
  assert(document.querySelector(".tip-popup") !== null, "Tip popup appears on focus");
  assert(anchor.hasAttribute("aria-describedby"), "aria-describedby links anchor to tip");
  _hideTip();
  assert(document.querySelector(".tip-popup") === null, "Tip popup removed after _hideTip");
  assert(!anchor.hasAttribute("aria-describedby"), "aria-describedby cleared after hide");
  document.body.removeChild(anchor);

  // ================================================
  suite("_addTip accepts a function for lazy evaluation");
  // ================================================

  var anchor2 = document.createElement("span");
  document.body.appendChild(anchor2);
  var calls = 0;
  _addTip(anchor2, function() { calls++; return "lazy-" + calls; });
  anchor2.dispatchEvent(new FocusEvent("focus"));
  await new Promise(function(r) { setTimeout(r, 250); });
  var tipEl = document.querySelector(".tip-popup");
  assert(tipEl !== null, "Lazy tip rendered");
  assertEqual(tipEl.textContent, "lazy-1", "Lazy tip text uses function result");
  _hideTip();
  document.body.removeChild(anchor2);

  // ================================================
  // Summary
  // ================================================

  var summaryEl = document.getElementById("summary");
  var total = _passed + _failed;
  summaryEl.textContent = total + " tests: " + _passed + " passed, " + _failed + " failed";
  summaryEl.className = _failed > 0 ? "fail" : "pass";

  if (typeof Deno !== "undefined") {
    Deno.exit(_failed > 0 ? 1 : 0);
  }
  window._testResult = { passed: _passed, failed: _failed };
})();
