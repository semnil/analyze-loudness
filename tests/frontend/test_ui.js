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
  compareQueue = [];
  _setBusy(false);
}

// Mock fetch — returns queued responses
var _fetchQueue = [];
var _fetchLog = [];  // every URL the page fetched, mocked or not
var _origFetch = window.fetch;

function mockFetch(responseFn) {
  _fetchQueue.push(responseFn);
}

window.fetch = function(url, opts) {
  _fetchLog.push(url);
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
    // The first three frames are ffmpeg's warm-up (no complete 400 ms window
    // yet); the gate only sees the five that follow.
    series: {
      t: [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8],
      S: [-120.7, -120.7, -120.7, -20, -21, -22, -20, -21],
      M: [-120.7, -120.7, -120.7, -21, -22, -23, -21, -22],
    },
    meta: {
      version: "1.0.0",
      analyzed_at: "2026-01-01T00:00:00Z",
      source_url: sourceUrl || "https://www.youtube.com/watch?v=test",
    },
  };
}

// Two cut tracks; summary.gate_threshold (-99) is a whole-length value that
// must not drive the gate over the cut range.
function fakeCompare() {
  var a = fakeResult("https://www.youtube.com/watch?v=a");
  var b = fakeResult("https://www.youtube.com/watch?v=b");
  a.summary.gate_threshold = -99;
  b.summary.gate_threshold = -99;
  return {
    meta: { schema_version: 3, version: "1.0.0", analyzed_at: "2026-01-01T00:00:00Z" },
    compare: { truncate_sec: 0.8, tracks: [a, b] },
  };
}

function fakeStats() {
  var st = {
    duration_sec: 0.8, frames: 8, integrated: -21.5,
    short_term: { median: -21, p10: -22, p90: -20 },
    momentary: { median: -22, p10: -23, p90: -21 },
    silence_pct: 0,
  };
  return [st, st];
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
  suite("NDJSON stream: abort");
  // ================================================

  var unhandledReasons = [];
  function onUnhandled(e) { unhandledReasons.push(e.reason); e.preventDefault(); }
  window.addEventListener("unhandledrejection", onUnhandled);
  var rejectRead = null;
  var abortedStream = {
    body: {
      getReader: function() {
        return {
          read: function() { return new Promise(function(resolve, reject) { rejectRead = reject; }); },
          cancel: function() {
            rejectRead(new DOMException("Fetch is aborted", "AbortError"));
            return Promise.reject(new DOMException("Fetch is aborted", "AbortError"));
          },
        };
      },
    },
  };
  var streamAbort = new AbortController();
  var reading = readNdjsonStream(abortedStream, streamAbort.signal).catch(function(e) { return e; });
  streamAbort.abort();
  var readError = await reading;
  await new Promise(function(r) { setTimeout(r, 50); });
  window.removeEventListener("unhandledrejection", onUnhandled);
  assertEqual(readError.name, "AbortError", "An aborted stream ends in AbortError");
  assertEqual(unhandledReasons.length, 0, "Cancelling the aborted stream leaves no unhandled rejection");

  var closedRead = null;
  var closingStream = {
    body: {
      getReader: function() {
        return {
          read: function() { return new Promise(function(resolve) { closedRead = resolve; }); },
          cancel: function() { closedRead({ done: true, value: undefined }); return Promise.resolve(); },
        };
      },
    },
  };
  var closingAbort = new AbortController();
  var closing = readNdjsonStream(closingStream, closingAbort.signal).catch(function(e) { return e; });
  closingAbort.abort();
  var closingError = await closing;
  assertEqual(closingError.name, "AbortError", "A stream that the cancel ends as done still ends in AbortError");

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
  suite("Gate caption accompanies the timeline");
  // ================================================

  var caption = resultsEl.querySelector(".gate-caption");
  assert(caption !== null, "Gate caption rendered under the timeline");
  assertEqual(caption.getAttribute("data-chart-block"), "1",
    "Gate caption is torn down with the charts on theme/lang change");
  assertEqual(caption.querySelector(".gate-pct").textContent, "100.0%",
    "Counted share shown for an all-counted sample");
  assertEqual(caption.querySelectorAll(".gate-swatch").length, 3,
    "Legend has counted / gated out / silence swatches");
  assert(resultsEl.querySelector(".chart-row.has-gate") !== null,
    "Timeline row is flagged so the caption sits tight under the chart");
  assert(resultsEl.querySelector(".chart-row").getAttribute("aria-label")
    .indexOf("Gate lane") !== -1, "Timeline aria-label describes the gate lane");

  // ================================================
  suite("computeGate: BS.1770 absolute + relative gating");
  // ================================================

  assertEqual(computeGate([]), null, "Empty series yields no gate");
  assertEqual(computeGate([-80, -90]), null, "All-silent series yields no gate");

  // Four blocks at -20 LUFS: relative threshold lands 10 LU below them.
  var flat = computeGate([-20, -20, -20, -20]);
  assert(Math.abs(flat.threshold - -30) < 1e-9, "Relative gate is mean - 10 LU");
  assertEqual(flat.counted, 4, "Blocks above the relative gate are counted");
  assertEqual(flat.silent, 0, "No silent blocks in a flat series");

  // -100 clears neither gate; -45 clears the absolute gate but not the relative one.
  var mixed = computeGate([-20, -20, -45, -100]);
  assertEqual(mixed.silent, 1, "Blocks at or below -70 LUFS count as silence");
  assertEqual(mixed.counted, 2, "Blocks above the relative gate stay counted");
  assertEqual(mixed.below, 1, "Blocks between the two gates are below gate");
  assertEqual(mixed.total, 4, "Every block lands in exactly one state");
  assertEqual(mixed.countedPct, 50, "Counted share is reported as a percentage");

  var nulls = computeGate([-20, -20, null]);
  assertEqual(nulls.silent, 1, "Null blocks (non-finite in ffmpeg output) count as silence");

  // ================================================
  suite("computeGate: schema 2 threshold replaces the recompute");
  // ================================================

  var blocks = [-20, -20, -25, -100];
  var derived = computeGate(blocks);
  var supplied = computeGate(blocks, null, -22);
  assert(Math.abs(derived.threshold - -31.1) < 0.1, "Schema 1 path derives the gate from M");
  assertEqual(supplied.threshold, -22, "Schema 2 path uses the stored threshold verbatim");
  assertEqual(derived.counted, 3, "Derived gate keeps the -25 block");
  assertEqual(supplied.counted, 2, "A -22 gate drops the -25 block");
  assertEqual(computeGate(blocks, null, null).threshold, derived.threshold,
    "null threshold (non-finite in ffmpeg output) falls back to M");
  assertEqual(computeGate(blocks, null, undefined).threshold, derived.threshold,
    "Absent threshold (schema 1) falls back to M");
  assertEqual(computeGate(blocks, null, "-22").threshold, derived.threshold,
    "Non-numeric threshold falls back to M");
  assertEqual(computeGate([-80, -90], null, -50), null,
    "All-silent series stays ungated even with a stored threshold");

  // ================================================
  suite("computeGate: ffmpeg's warm-up frames are not gating blocks");
  // ================================================

  // 0.5 s tone -- ffmpeg emits three frames at its silence floor before the
  // first complete 400 ms window exists.
  var warm = computeGate([-120.7, -120.7, -120.7, -21.8, -21.8],
                         [0.1, 0.2, 0.3, 0.4, 0.5]);
  assertEqual(warm.total, 2, "Only the frames with a complete window are gated");
  assertEqual(warm.silent, 0, "Warm-up frames are not silence");
  assertEqual(warm.counted, 2, "Both complete blocks clear the gate");
  assertEqual(warm.countedPct, 100, "A steady tone reads as 100% counted");
  assertEqual(warm.state.length, 5, "state stays aligned with the series");
  assertEqual(warm.state[0], GATE_COUNTED, "Warm-up frames draw nothing in the lane");

  var realSilence = computeGate([-120.7, -120.7, -120.7, -21.8, -120.7],
                                [0.1, 0.2, 0.3, 0.4, 0.5]);
  assertEqual(realSilence.silent, 1, "Silence past the warm-up still counts as silence");
  assertEqual(realSilence.total, 2, "...without changing the denominator");

  assertEqual(computeGate([-20, -20, -20, -20]).total, 4,
    "No time axis -> nothing is skipped");
  assertEqual(computeGate([-120.7, -120.7, -120.7], [0.1, 0.2, 0.3]), null,
    "A clip shorter than the momentary window has no gating blocks");

  resetState();
  var v2 = fakeResult();
  v2.summary.gate_threshold = -22.5;
  render(v2);
  assert(resultsEl.querySelector(".gate-caption").textContent.indexOf("-22.5 LUFS") !== -1,
    "Caption reports the stored threshold for a schema 2 result");

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
  window.analyzeSettings.saved = [];
  assertEqual(document.documentElement.getAttribute("data-theme"), "light", "Theme starts light");
  var themeBtn = document.getElementById("theme-toggle");
  assert(themeBtn.querySelector("svg") !== null, "Light icon is an SVG");
  assertEqual(themeBtn.textContent, "", "Light icon has no text glyph");
  themeBtn.click();
  assertEqual(document.documentElement.getAttribute("data-theme"), "dark", "Toggle goes to dark");
  assert(themeBtn.querySelector("svg") !== null, "Dark icon is an SVG");
  assertEqual(themeBtn.textContent, "", "Dark icon has no text glyph");
  themeBtn.click();
  // Auto resolves to light or dark depending on host environment
  var autoTheme = document.documentElement.getAttribute("data-theme");
  assert(autoTheme === "light" || autoTheme === "dark", "Auto resolves to light or dark");
  assert(themeBtn.querySelector("svg") !== null, "Auto icon is an SVG");
  assertEqual(themeBtn.textContent, "", "Auto icon has no text glyph");
  assertEqual(JSON.stringify(window.analyzeSettings.saved), JSON.stringify([["theme", "dark"], ["theme", "auto"]]),
              "Each theme click saves the new theme through the app");
  _setThemeMode("light");

  // ================================================
  suite("A theme save that fails is reported");
  // ================================================

  resetState();
  window.analyzeSettings.failWith = "Permission denied";
  themeBtn.click();
  await new Promise(function(r) { setTimeout(r, 20); });
  assertEqual(document.documentElement.getAttribute("data-theme"), "dark", "The picked theme stays in effect");
  assert(statusEl.classList.contains("error"), "The failed save is shown as an error");
  assert(statusEl.textContent.indexOf("The setting could not be saved: Permission denied") !== -1, "The error names the cause");
  window.analyzeSettings.failWith = null;
  _setThemeMode("light");
  resetState();

  // ================================================
  suite("Lang toggle EN <-> JA saves through the app");
  // ================================================

  resetState();
  window.i18n.setLang("en");
  window.analyzeSettings.saved = [];
  assertEqual(window.i18n.lang(), "en", "Lang starts en");
  document.getElementById("lang-toggle").click();
  assertEqual(window.i18n.lang(), "ja", "Lang toggled to ja");
  document.getElementById("lang-toggle").click();
  assertEqual(window.i18n.lang(), "en", "Lang toggled back to en");
  assertEqual(JSON.stringify(window.analyzeSettings.saved), JSON.stringify([["lang", "ja"], ["lang", "en"]]),
              "Each language click saves the new language through the app");

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
    "gate.lane_label", "gate.counted", "gate.out", "gate.silence",
    "gate.counted_of_timeline", "gate.excluded_detail", "aria.gate_lane",
    "btn.add", "btn.compare", "btn.clear", "track.move_up", "track.move_down", "track.remove",
    "err.max_tracks", "err.compare_min", "err.compare_queue_busy", "err.url_scheme",
    "compare.title", "compare.scope", "table.integrated_full", "table.true_peak_full",
    "table.lra_full", "tip.integrated_full", "tip.true_peak_full", "tip.lra_full",
    "gate.lane_label_n", "gate.compare_counted", "btn.browse", "drop.overlay", "track.tag_file",
    "status.uploading", "status.file_loaded", "chart.compare_track", "chart.compare_seg_title",
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
  suite("Comparison queue: Add Track / Clear All");
  // ================================================

  var addBtn = document.getElementById("add-btn");
  var clearBtn = document.getElementById("clear-btn");
  var compareBar = document.getElementById("compare-bar");
  var trackListEl = document.getElementById("track-list");

  resetState();
  urlInput.value = "https://www.youtube.com/watch?v=a";
  addBtn.click();
  assertEqual(compareQueue.length, 1, "Add Track queues the URL");
  assertEqual(urlInput.value, "", "URL field cleared after queuing");
  assertEqual(trackListEl.querySelectorAll(".track-item").length, 1, "One queue row rendered");
  assertEqual(compareBar.hidden, false, "Clear All bar shown with a queued track");
  assertEqual(submitBtn.textContent, "Compare", "Submit reads Compare with tracks queued");
  assertEqual(urlInput.required, false, "URL field not required while tracks are queued");

  urlInput.value = "ftp://example.com/x";
  addBtn.click();
  assertEqual(compareQueue.length, 1, "Non-http(s) URL is not queued");
  assert(statusEl.classList.contains("error"), "Non-http(s) URL shows an error");

  clearBtn.click();
  assertEqual(compareQueue.length, 0, "Clear All empties the queue");
  assertEqual(compareBar.hidden, true, "Clear All bar hidden when empty");
  assertEqual(submitBtn.textContent, "Analyze", "Submit reads Analyze again");
  assertEqual(urlInput.required, true, "URL field required again");

  // ================================================
  suite("Comparison queue: cap, reorder, remove");
  // ================================================

  resetState();
  for (var q = 0; q < MAX_TRACKS; q++) {
    urlInput.value = "https://www.youtube.com/watch?v=" + q;
    addBtn.click();
  }
  assertEqual(compareQueue.length, MAX_TRACKS, "Queue fills to MAX_TRACKS");
  urlInput.value = "https://www.youtube.com/watch?v=extra";
  addBtn.click();
  assertEqual(compareQueue.length, MAX_TRACKS, "Add beyond MAX_TRACKS is refused");
  assert(statusEl.textContent.indexOf(String(MAX_TRACKS)) !== -1, "Cap error names the limit");
  assertEqual(urlInput.value, "https://www.youtube.com/watch?v=extra", "Refused URL stays in the field");

  var rows = trackListEl.querySelectorAll(".track-item");
  var firstUp = rows[0].querySelectorAll(".track-btn")[0];
  assert(firstUp.classList.contains("placeholder") && firstUp.disabled, "First row has no move-up");
  rows[0].querySelectorAll(".track-btn")[1].click();  // move track 1 down
  assertEqual(compareQueue[0].label, "https://www.youtube.com/watch?v=1", "Move down swaps rows 1 and 2");
  assertEqual(compareQueue[1].label, "https://www.youtube.com/watch?v=0", "Moved track is now second");
  trackListEl.querySelectorAll(".track-item")[0].querySelector(".track-btn.remove").click();
  assertEqual(compareQueue.length, MAX_TRACKS - 1, "Remove drops one track");
  assertEqual(compareQueue[0].label, "https://www.youtube.com/watch?v=0", "Remove took the first row");
  assertEqual(trackListEl.querySelector(".track-btn.remove").getAttribute("aria-label"),
              "Remove track 1", "Remove button names its track number");

  // ================================================
  suite("Compare needs two tracks");
  // ================================================

  resetState();
  urlInput.value = "https://www.youtube.com/watch?v=a";
  addBtn.click();
  document.getElementById("analyze-form").dispatchEvent(new Event("submit"));
  await new Promise(function(r) { setTimeout(r, 50); });
  assertEqual(_isBusy, false, "One queued track does not start a comparison");
  assert(statusEl.classList.contains("error"), "Comparison with one track shows an error");

  // ================================================
  suite("Load JSON while tracks are queued");
  // ================================================

  resetState();
  urlInput.value = "https://www.youtube.com/watch?v=a";
  addBtn.click();
  mockFetch(function() { return makeJsonResponse({ loaded: true, data: fakeResult() }); });
  loadBtn.click();
  await new Promise(function(r) { setTimeout(r, 100); });
  assertEqual(compareQueue.length, 2, "A single result joins the queue");
  assertEqual(compareQueue[1].kind, "json", "Loaded result is queued as JSON");
  assert(!resultsEl.classList.contains("visible"), "Loaded result is not rendered on its own");

  mockFetch(function() {
    return makeJsonResponse({ loaded: true, data: fakeCompare(), stats: fakeStats() });
  });
  loadBtn.click();
  await new Promise(function(r) { setTimeout(r, 100); });
  assertEqual(compareQueue.length, 2, "A comparison JSON is not queued");
  assert(statusEl.classList.contains("error"), "Comparison JSON with a non-empty queue is refused");
  assert(resultsEl.querySelector(".compare-table") === null, "Refused comparison is not rendered");

  // ================================================
  suite("Load comparison JSON with an empty queue");
  // ================================================

  resetState();
  var captured = null;
  var origCmpTimeline = window.renderCompareTimeline;
  window.renderCompareTimeline = function(c, t, items) { captured = items; return { destroy: function(){}, ctx: null }; };
  mockFetch(function() {
    return makeJsonResponse({ loaded: true, data: fakeCompare(), stats: fakeStats() });
  });
  loadBtn.click();
  await new Promise(function(r) { setTimeout(r, 100); });
  assert(resultsEl.querySelector(".compare-table") !== null, "Comparison table rendered");
  assertEqual(resultsEl.querySelectorAll(".compare-table thead th").length, 3, "One column per track plus the row header");
  assertEqual(resultsEl.querySelectorAll(".compare-seg-title").length, 2, "One segment chart per track");
  assert(captured !== null && captured.length === 2, "Timeline receives both tracks");
  // fakeCompare stores a whole-length gate_threshold of -99 that does not
  // belong to the cut range; the relative gate must come from the series.
  assert(captured[0].gate !== null && Math.abs(captured[0].gate.threshold - (-99)) > 1,
         "Gate threshold is recomputed on the cut range, not taken from summary");
  window.renderCompareTimeline = origCmpTimeline;

  // Theme switch: table swatches follow the new palette.
  var origGetTheme = window.getTheme;
  window.getTheme = function() {
    var th = origGetTheme();
    th.trackColors = ["#000001", "#000002", "#000003", "#000004", "#000005", "#000006"];
    return th;
  };
  _reRenderCharts();
  var headSwatch = resultsEl.querySelector(".compare-table thead .track-swatch");
  assertEqual(headSwatch.style.background, "rgb(0, 0, 1)",
              "Table swatch recoloured on chart re-render");
  window.getTheme = origGetTheme;

  // ================================================
  suite("Compare runs /analyze per URL track, then /compare");
  // ================================================

  resetState();
  urlInput.value = "https://www.youtube.com/watch?v=a";
  addBtn.click();
  compareQueue.push({ kind: "json", label: "Loaded", data: fakeResult("https://example.com/b") });
  _renderQueue();
  var compareBody = null;
  mockFetch(function(url) {
    return makeNdjsonResponse([{ type: "result", data: fakeResult("https://www.youtube.com/watch?v=a") }]);
  });
  mockFetch(function(url, opts) {
    compareBody = JSON.parse(opts.body);
    return makeJsonResponse({ data: fakeCompare(), stats: fakeStats() });
  });
  document.getElementById("analyze-form").dispatchEvent(new Event("submit"));
  await new Promise(function(r) { setTimeout(r, 300); });
  assert(compareBody !== null, "/compare was called");
  assertEqual(compareBody && compareBody.tracks.length, 2, "/compare receives both tracks");
  assertEqual(compareBody && compareBody.tracks[1].meta.source_url, "https://example.com/b",
              "Queued JSON is sent as-is in queue order");
  assert(resultsEl.querySelector(".compare-table") !== null, "Comparison rendered after /compare");
  assertEqual(compareQueue.length, 2, "Queue is kept after a comparison");
  assertEqual(_isBusy, false, "Not busy after the comparison");


  // ================================================
  suite("+ Add Track keeps the displayed result, not just its URL");
  // ================================================

  // Two saved results with the same source_url: the URL cache only holds
  // the last one loaded, so the first must travel as data.
  resetState();
  var savedA = fakeResult("https://www.youtube.com/watch?v=same");
  savedA.title = "Saved A";
  var savedB = fakeResult("https://www.youtube.com/watch?v=same");
  savedB.title = "Saved B";
  mockFetch(function() { return makeJsonResponse({ loaded: true, data: savedA }); });
  loadBtn.click();
  await new Promise(function(r) { setTimeout(r, 100); });
  assertEqual(urlInput.value, "https://www.youtube.com/watch?v=same", "Loaded result restores its URL");
  addBtn.click();
  assert(compareQueue[0] && compareQueue[0].data && compareQueue[0].data.title === "Saved A",
         "Queued track carries the displayed result");
  mockFetch(function() { return makeJsonResponse({ loaded: true, data: savedB }); });
  loadBtn.click();
  await new Promise(function(r) { setTimeout(r, 100); });
  var sentTitles = null;
  mockFetch(function(url, opts) {
    sentTitles = JSON.parse(opts.body).tracks.map(function(tr) { return tr.title; });
    return makeJsonResponse({ data: fakeCompare(), stats: fakeStats() });
  });
  document.getElementById("analyze-form").dispatchEvent(new Event("submit"));
  await new Promise(function(r) { setTimeout(r, 200); });
  assertEqual(JSON.stringify(sentTitles), JSON.stringify(["Saved A", "Saved B"]),
              "/compare receives A then B, without re-analysing the URL");

  // A different URL in the field is queued as a URL to analyse.
  resetState();
  render(savedA);
  urlInput.value = "https://www.youtube.com/watch?v=other";
  addBtn.click();
  assertEqual(compareQueue[0].data, undefined, "A URL other than the displayed result is queued without data");

  // ================================================
  suite("Local files: source kinds and the queue");
  // ================================================

  assertEqual(_sourceKind("https://www.youtube.com/watch?v=a"), "url", "http(s) is a URL");
  assertEqual(_sourceKind("/Users/me/a.wav"), "file", "Absolute path is a file");
  assertEqual(_sourceKind("C:\\music\\a.wav"), "file", "Windows path is a file");
  assertEqual(_sourceKind("file:///tmp/a.wav"), null, "file:// is refused");
  assertEqual(_sourceKind("javascript:alert(1)"), null, "javascript: is refused");
  assertEqual(_sourceKind("\\\\host\\share\\a.wav"), "network", "UNC path is a network path");
  assertEqual(_sourceKind("//host/share/a.wav"), "network", "//host path is a network path");
  assertEqual(_sourceKind("\\??\\UNC\\host\\share\\a.wav"), "network", "NT namespace path is a network path");
  assertEqual(_sourceKind("/??/UNC/host/share/a.wav"), "network", "NT namespace path with slashes is a network path");
  assertEqual(_sourceKind("\\.\\??\\UNC\\host\\share\\a.wav"), "network", "NT namespace path after a . segment is a network path");
  assertEqual(_sourceKind("\\dir\\..\\??\\UNC\\host\\share\\a.wav"), "network", "NT namespace path after a .. segment is a network path");
  assertEqual(_sourceKind("\\Users\\me\\a.wav"), "file", "Rooted Windows path is a file");
  assertEqual(_sourceKind("C:\\dir\\..\\??\\a.wav"), "file", "?? under a drive is a file");

  resetState();
  urlInput.value = "/Users/me/a.wav";
  addBtn.click();
  assertEqual(compareQueue.length, 1, "Local path is queued");
  assertEqual(compareQueue[0].kind, "file", "Local path is queued as a file");
  assertEqual(trackListEl.querySelector(".track-tag").textContent, "FILE", "File rows carry the FILE tag");
  urlInput.value = "file:///tmp/a.wav";
  addBtn.click();
  assertEqual(compareQueue.length, 1, "file:// is not queued");
  urlInput.value = "\\\\host\\share\\a.wav";
  addBtn.click();
  assertEqual(compareQueue.length, 1, "A typed UNC path is not queued");
  assert(statusEl.textContent.indexOf("UNC") !== -1, "The network path error names UNC paths");

  // ================================================
  suite("Browse fills the field");
  // ================================================

  resetState();
  mockFetch(function(url) {
    assert(url.indexOf("/browse") !== -1, "Browse posts to /browse");
    return makeJsonResponse({ selected: true, path: "/music/b.flac" });
  });
  document.getElementById("browse-btn").click();
  await new Promise(function(r) { setTimeout(r, 50); });
  assertEqual(urlInput.value, "/music/b.flac", "Chosen path lands in the field");

  // ================================================
  suite("Drop: one file fills the field, a queue takes every file");
  // ================================================

  function dropFiles(names) {
    var dt = new DataTransfer();
    names.forEach(function(n) { dt.items.add(new File(["x"], n)); });
    window.dispatchEvent(new DragEvent("drop", { dataTransfer: dt, bubbles: true, cancelable: true }));
  }

  resetState();
  var uploadNames = [];
  mockFetch(function(url, opts) {
    uploadNames.push(decodeURIComponent(opts.headers["X-Filename"]));
    return makeJsonResponse({ uploaded: true, path: "/tmp/up/c.wav" });
  });
  dropFiles(["c.wav"]);
  await new Promise(function(r) { setTimeout(r, 100); });
  assertEqual(uploadNames[0], "c.wav", "Dropped file is uploaded with its name");
  assertEqual(urlInput.value, "/tmp/up/c.wav", "Single drop with an empty queue fills the field");
  assertEqual(compareQueue.length, 0, "Single drop does not queue");

  resetState();
  mockFetch(function() { return makeJsonResponse({ uploaded: true, path: "/tmp/up/d.wav" }); });
  mockFetch(function() { return makeJsonResponse({ uploaded: true, path: "/tmp/up/e.wav" }); });
  dropFiles(["d.wav", "e.wav"]);
  await new Promise(function(r) { setTimeout(r, 150); });
  assertEqual(compareQueue.length, 2, "Several dropped files join the queue");
  assertEqual(compareQueue[1].label, "/tmp/up/e.wav", "Queued in drop order");
  assertEqual(compareQueue[0].kind, "file", "Dropped files are file tracks");

  resetState();
  mockFetch(function() { return makeJsonResponse({ error: "Unsupported file type: .txt" }, 400); });
  dropFiles(["notes.txt"]);
  await new Promise(function(r) { setTimeout(r, 100); });
  assert(statusEl.textContent.indexOf(".txt") !== -1, "Upload error is shown");
  assertEqual(urlInput.value, "", "Rejected drop leaves the field empty");

  // ================================================
  suite("Update: settings button and dialog");
  // ================================================

  await window.analyzeUpdate.ready;
  var settingsButton = document.getElementById("settings-toggle");
  var toolbarNode = document.querySelector(".toolbar");
  assert(settingsButton !== null, "Settings button exists");
  assertEqual(settingsButton.parentElement, toolbarNode, "Settings button sits in the toolbar");
  assertEqual(toolbarNode.lastElementChild, settingsButton, "Settings button comes after the theme toggle");
  assertEqual(settingsButton.getAttribute("aria-label"), "Settings", "Settings button is labelled");
  assertEqual(settingsButton.getAttribute("aria-haspopup"), "dialog", "Settings button announces a dialog");
  assert(settingsButton.querySelector("svg") !== null, "Settings button draws an SVG icon");

  function settingsBox() { return document.querySelector(".settings-box"); }
  function settingsOpen() { return !document.querySelector(".settings-scrim").hidden; }
  function escapeOn(target) {
    target.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true, cancelable: true }));
  }

  settingsButton.focus();
  settingsButton.click();
  assert(settingsOpen(), "Clicking the button opens the dialog");
  assertEqual(settingsBox().getAttribute("role"), "dialog", "Dialog role");
  assertEqual(settingsBox().getAttribute("aria-modal"), "true", "Dialog is modal");
  assertEqual(document.getElementById("settings-version").textContent, "Loudness Analyzer 1.4.1",
              "Version row names the app and the running version");
  assertEqual(document.getElementById("settings-update-launch").checked, false, "Launch check shows the setting /update/status reported");
  assertEqual(document.getElementById("settings-update-now").disabled, false, "Check now enabled in the installed app");
  assert(settingsBox().querySelector(".settings-tag") === null, "No installed-only tag in the installed app");
  assertEqual(document.activeElement, settingsBox().querySelector(".settings-close"), "Focus moves to Close");
  assert(document.querySelector("main").inert, "Page behind the dialog is inert");

  var savedSettings = [];
  function mockSave(answer, status) {
    mockFetch(function (url, init) {
      savedSettings.push([url, JSON.parse(init.body)]);
      return makeJsonResponse(answer, status);
    });
  }
  mockSave({ launch_check: true });
  document.getElementById("settings-update-launch").click();
  await new Promise(function (r) { setTimeout(r, 20); });
  assertEqual(JSON.stringify(savedSettings[0]), JSON.stringify(["/update/settings", { launch_check: true }]),
              "Turning the launch check on saves it through /update/settings");
  mockSave({ launch_check: false });
  document.getElementById("settings-update-launch").click();
  await new Promise(function (r) { setTimeout(r, 20); });
  assertEqual(JSON.stringify(savedSettings[1]), JSON.stringify(["/update/settings", { launch_check: false }]),
              "Turning it off saves false");
  assertEqual(document.getElementById("settings-update-launch").checked, false, "The toggle shows off");
  mockSave({ error: "The setting could not be saved: [Errno 13] Permission denied" }, 500);
  document.getElementById("settings-update-launch").click();
  await new Promise(function (r) { setTimeout(r, 20); });
  assertEqual(document.getElementById("settings-update-launch").checked, false, "A failed save puts the toggle back");
  assertEqual(document.getElementById("settings-update-note").textContent, "The setting could not be saved.",
              "A failed save is reported in the dialog");
  assert(document.getElementById("settings-update-note").classList.contains("warn"), "The failed save is a warning");

  // A save in flight holds the toggle; the server's answer decides what it shows.
  var pendingSave = null;
  savedSettings = [];
  _fetchLog = [];
  mockFetch(function (url, init) {
    savedSettings.push([url, JSON.parse(init.body)]);
    pendingSave = {};
    pendingSave.promise = new Promise(function (r) { pendingSave.resolve = r; });
    return pendingSave.promise;
  });
  document.getElementById("settings-update-launch").click();
  assertEqual(document.getElementById("settings-update-launch").disabled, true, "The toggle is disabled while its save is in flight");
  document.getElementById("settings-update-launch").click();
  await new Promise(function (r) { setTimeout(r, 20); });
  assertEqual(_fetchLog.filter(function (u) { return u === "/update/settings"; }).length, 1,
              "A click during a save sends no second request");
  pendingSave.resolve(makeJsonResponse({ launch_check: true }));
  await new Promise(function (r) { setTimeout(r, 20); });
  assertEqual(document.getElementById("settings-update-launch").disabled, false, "The toggle is usable again after the save");
  assertEqual(document.getElementById("settings-update-launch").checked, true, "The toggle shows the saved value");
  assertEqual(document.activeElement, document.getElementById("settings-update-launch"), "Focus stays on the toggle after the save");

  mockSave({ launch_check: true });
  document.getElementById("settings-update-launch").click();
  await new Promise(function (r) { setTimeout(r, 20); });
  assertEqual(JSON.stringify(savedSettings[1]), JSON.stringify(["/update/settings", { launch_check: false }]), "Turning it off asks for false");
  assertEqual(document.getElementById("settings-update-launch").checked, true, "The toggle shows what the server saved, not the click");
  window.analyzeUpdate.close();
  settingsButton.click();
  assertEqual(document.getElementById("settings-update-launch").checked, true, "Reopening shows the saved value");
  mockSave({ launch_check: false });
  document.getElementById("settings-update-launch").click();
  await new Promise(function (r) { setTimeout(r, 20); });
  assertEqual(document.getElementById("settings-update-launch").checked, false, "Back off for the rest of the suite");

  var nodes = Array.prototype.filter.call(settingsBox().querySelectorAll("button, input"), function (n) { return !n.disabled; });
  nodes[nodes.length - 1].focus();
  settingsBox().dispatchEvent(new KeyboardEvent("keydown", { key: "Tab", bubbles: true, cancelable: true }));
  assertEqual(document.activeElement, nodes[0], "Tab from the last control wraps to the first");
  nodes[0].focus();
  settingsBox().dispatchEvent(new KeyboardEvent("keydown", { key: "Tab", shiftKey: true, bubbles: true, cancelable: true }));
  assertEqual(document.activeElement, nodes[nodes.length - 1], "Shift+Tab from the first wraps to the last");

  var aborted = false;
  activeAbort = { abort: function () { aborted = true; } };
  escapeOn(document.activeElement);
  assert(!settingsOpen(), "Escape closes the dialog");
  assertEqual(aborted, false, "Escape in the dialog does not cancel the analysis");
  activeAbort = null;
  assertEqual(document.activeElement, settingsButton, "Focus returns to the settings button");
  assert(!document.querySelector("main").inert, "Page is interactive again");

  window.i18n.setLang("ja");
  assertEqual(settingsButton.getAttribute("aria-label"), "設定", "Button label follows the language");
  settingsButton.click();
  assertEqual(document.getElementById("settings-title").textContent, "設定", "Dialog title in Japanese");
  assertEqual(document.getElementById("settings-update-now").textContent, "今すぐ確認", "Check now in Japanese");
  window.i18n.setLang("en");
  assertEqual(document.getElementById("settings-title").textContent, "Settings", "Open dialog redraws on a language switch");
  window.analyzeUpdate.close();

  // ================================================
  suite("Update: outside the installed app");
  // ================================================

  _fetchLog = [];
  mockFetch(function () { return makeJsonResponse({ current: "1.4.1", supported: false, launch_check: true }); });
  await window.analyzeUpdate._boot();
  assertEqual(_fetchLog.join(","), "/update/status", "No launch check outside the installed app");
  settingsButton.click();
  assertEqual(document.getElementById("settings-update-now").disabled, true, "Check now disabled");
  assertEqual(document.getElementById("settings-update-launch").disabled, true, "Launch toggle disabled");
  assert(settingsBox().querySelector(".settings-tag") !== null, "Installed-only tag shown");
  window.analyzeUpdate.close();
  mockFetch(function () { return makeJsonResponse({ current: "1.4.1", supported: true, launch_check: false }); });
  await window.analyzeUpdate._boot();

  // ------ helpers for the check flows ------
  var updateCalls = [];
  function mockUpdate(handler) {
    mockFetch(function (url, init) {
      updateCalls.push({ url: url, body: init && init.body ? JSON.parse(init.body) : null });
      return handler(url, init);
    });
  }
  function deferred() {
    var d = {};
    d.promise = new Promise(function (resolve) { d.resolve = resolve; });
    return d;
  }
  var confirmCalls = [];
  var confirmAnswer = false;
  var savedConfirm = window.confirm;
  window.confirm = function (msg) { confirmCalls.push(msg); return confirmAnswer; };
  function tick(ms) { return new Promise(function (r) { setTimeout(r, ms || 0); }); }
  function note() { return document.getElementById("settings-update-note"); }

  // ================================================
  suite("Update: Check now");
  // ================================================

  resetState();
  updateCalls = [];
  var flight = deferred();
  mockUpdate(function () { return flight.promise; });
  settingsButton.click();
  document.getElementById("settings-update-now").click();
  await tick();
  assertEqual(note().textContent, "Checking…", "Note says Checking while in flight");
  assertEqual(settingsBox().querySelector(".settings-close").disabled, true, "Close disabled while checking");
  assertEqual(document.getElementById("settings-update-now").disabled, true, "Check now disabled while checking");
  escapeOn(settingsBox());
  assert(settingsOpen(), "Escape cannot close while checking");
  document.querySelector(".settings-scrim").dispatchEvent(new MouseEvent("mousedown", { bubbles: true }));
  assert(settingsOpen(), "Outside press cannot close while checking");
  flight.resolve(makeJsonResponse({ available: false }));
  await tick(20);
  assertEqual(updateCalls[0].url, "/update/check", "Check now posts /update/check");
  assertEqual(note().textContent, "Already up to date.", "Up to date is reported inline");
  assertEqual(settingsBox().querySelector(".settings-close").disabled, false, "Close enabled after the check");
  assertEqual(document.activeElement, document.getElementById("settings-update-now"), "Focus goes back to Check now");

  mockUpdate(function () { return makeJsonResponse({ error: "HTTP 404 from https://github.com/semnil/analyze-loudness/releases/download/v1.4.1/latest.json" }, 502); });
  document.getElementById("settings-update-now").click();
  await tick(20);
  assertEqual(note().textContent, "Update check failed.", "Failure is reported inline");
  assert(note().classList.contains("warn"), "Failure note is a warning");

  confirmCalls = [];
  confirmAnswer = false;
  mockUpdate(function () { return makeJsonResponse({ available: true, version: "9.9.9" }); });
  document.getElementById("settings-update-now").click();
  await tick(20);
  assertEqual(confirmCalls.length, 1, "An available update is confirmed");
  assert(confirmCalls[0].indexOf("Version 9.9.9 is available. Update now?") === 0, "Confirm names the version");
  assert(confirmCalls[0].indexOf("not saved") !== -1, "Confirm says unsaved results are cleared");
  assertEqual(note().textContent, "Version 9.9.9 is available.", "Declined update stays named in the note");
  assert(settingsOpen(), "Declining keeps the dialog open");

  confirmCalls = [];
  _setBusy(true);
  mockUpdate(function () { return makeJsonResponse({ available: true, version: "9.9.9" }); });
  document.getElementById("settings-update-now").click();
  await tick(20);
  assertEqual(confirmCalls.length, 0, "No confirm while an analysis runs");
  assert(note().textContent.indexOf("analysis is running") !== -1, "Busy is reported inline");
  _setBusy(false);
  window.analyzeUpdate.close();

  // ================================================
  suite("Update: accepted install");
  // ================================================

  resetState();
  updateCalls = [];
  confirmCalls = [];
  confirmAnswer = true;
  var install = deferred();
  mockUpdate(function () { return makeJsonResponse({ available: true, version: "9.9.9" }); });
  mockUpdate(function () { return install.promise; });
  settingsButton.focus();
  settingsButton.click();
  document.getElementById("settings-update-now").click();
  await tick(50);
  assert(!settingsOpen(), "Accepting closes the dialog");
  assertEqual(updateCalls[1].url, "/update/install", "Accepting posts /update/install");
  assertEqual(updateCalls[1].body.version, "9.9.9", "The install names the confirmed version");
  assertEqual(statusEl.textContent, "Downloading update… the app will restart", "Download status shown");
  assertEqual(_isBusy, true, "The app is busy while downloading");
  assertEqual(submitBtn.disabled, true, "Analyze cannot start during the download");
  assertEqual(document.activeElement, settingsButton, "Focus stays on the settings button during the download");
  assertEqual(settingsButton.getAttribute("aria-disabled"), "true", "The settings button is marked unavailable during the download");
  settingsButton.click();
  assert(!settingsOpen(), "Settings cannot open during the download");
  install.resolve(makeJsonResponse({ error: "The downloaded update does not match its signature" }, 500));
  await tick(20);
  assertEqual(_isBusy, false, "A failed install releases the app");
  assertEqual(settingsButton.getAttribute("aria-disabled"), null, "The settings button is available again after a failure");
  settingsButton.click();
  assert(settingsOpen(), "Settings opens again after a failure");
  window.analyzeUpdate.close();
  assert(statusEl.classList.contains("error"), "Failure shown as an error");
  assert(statusEl.textContent.indexOf("could not be downloaded and installed: The downloaded update does not match its signature") !== -1,
         "Failure names the cause");

  resetState();
  mockUpdate(function () { return makeJsonResponse({ available: true, version: "9.9.9" }); });
  mockUpdate(function () { return makeJsonResponse({ installed: true, restart_error: "Resource busy" }); });
  await window.analyzeUpdate.checkForUpdates();
  await tick(20);
  assert(statusEl.textContent.indexOf("installed, but the app could not restart (Resource busy)") !== -1,
         "An installed update that did not restart says so");
  assertEqual(_isBusy, false, "The app is usable after a failed restart");
  settingsButton.click();
  assert(!settingsOpen(), "No second install after the bundle was replaced");
  settingsButton.removeAttribute("aria-disabled");

  // ================================================
  suite("Update: launch check and shared flight");
  // ================================================

  resetState();
  updateCalls = [];
  confirmCalls = [];
  confirmAnswer = false;
  mockFetch(function () { return makeJsonResponse({ current: "1.4.1", supported: true, launch_check: true }); });
  mockUpdate(function () { return makeJsonResponse({ available: true, version: "9.9.9" }); });
  await window.analyzeUpdate._boot();
  assertEqual(updateCalls.length, 1, "Launch check runs when on");
  assertEqual(confirmCalls.length, 1, "Launch check confirms an available update");
  assertEqual(statusEl.textContent, "", "A declined launch check leaves the status line alone");

  updateCalls = [];
  mockFetch(function () { return makeJsonResponse({ current: "1.4.1", supported: true, launch_check: true }); });
  mockUpdate(function () { return makeJsonResponse({ error: "offline" }, 502); });
  await window.analyzeUpdate._boot();
  assertEqual(updateCalls.length, 1, "Launch check ran");
  assertEqual(statusEl.textContent, "", "A failed launch check stays silent");

  _fetchLog = [];
  mockFetch(function () { return makeJsonResponse({ current: "1.4.1", supported: true, launch_check: false }); });
  await window.analyzeUpdate._boot();
  assertEqual(_fetchLog.join(","), "/update/status", "No launch check when off");

  updateCalls = [];
  mockFetch(function () { return makeJsonResponse({ current: "1.4.1", supported: true }); });
  mockUpdate(function () { return makeJsonResponse({ available: false }); });
  await window.analyzeUpdate._boot();
  assertEqual(updateCalls.length, 1, "Launch check is on when the status does not name the setting");

  updateCalls = [];
  confirmCalls = [];
  var shared = deferred();
  mockUpdate(function () { return shared.promise; });
  var first = window.analyzeUpdate.checkForUpdates();
  var second = window.analyzeUpdate.checkForUpdates();
  shared.resolve(makeJsonResponse({ available: true, version: "9.9.9" }));
  var outcomes = await Promise.all([first, second]);
  assertEqual(updateCalls.length, 1, "Overlapping checks send one request");
  assertEqual(confirmCalls.length, 1, "Overlapping checks show one confirm");
  assertEqual(outcomes[1].kind, "declined", "Both callers get the outcome");

  // ================================================
  suite("Update: keys while the dialog waits on the server");
  // ================================================

  // Keys go to document.activeElement, as a key press does; the page's own
  // Escape handler cancels a running analysis.
  resetState();
  var escapeAborted = false;
  activeAbort = { abort: function () { escapeAborted = true; } };
  var pendingCheck = deferred();
  mockUpdate(function () { return pendingCheck.promise; });
  settingsButton.click();
  document.getElementById("settings-update-now").focus();
  document.getElementById("settings-update-now").click();
  await tick(50);
  assert(settingsBox().contains(document.activeElement), "Focus stays in the dialog while checking");
  escapeOn(document.activeElement);
  assertEqual(escapeAborted, false, "Escape while checking does not cancel the analysis");
  assert(settingsOpen(), "Escape while checking leaves the dialog open");
  pendingCheck.resolve(makeJsonResponse({ available: false }));
  await tick(20);
  assertEqual(document.activeElement, document.getElementById("settings-update-now"), "Focus returns to Check now after the check");

  escapeAborted = false;
  var pendingSave = deferred();
  mockFetch(function () { return pendingSave.promise; });
  document.getElementById("settings-update-launch").focus();
  document.getElementById("settings-update-launch").click();
  await tick(50);
  assertEqual(document.activeElement, settingsBox(), "Focus moves to the dialog while saving");
  escapeOn(document.activeElement);
  assertEqual(escapeAborted, false, "Escape while saving does not cancel the analysis");
  assert(!settingsOpen(), "Escape while saving closes the dialog");
  pendingSave.resolve(makeJsonResponse({ launch_check: false }));
  await tick(20);

  settingsButton.click();
  settingsBox().focus();
  assertEqual(document.activeElement, settingsBox(), "The dialog itself can hold focus");
  settingsBox().dispatchEvent(new KeyboardEvent("keydown", { key: "Tab", shiftKey: true, bubbles: true, cancelable: true }));
  assertEqual(document.activeElement, settingsBox().querySelector(".settings-close"), "Shift+Tab from the dialog goes to the last control");
  settingsBox().focus();
  settingsBox().dispatchEvent(new KeyboardEvent("keydown", { key: "Tab", bubbles: true, cancelable: true }));
  assertEqual(document.activeElement, document.getElementById("settings-update-launch"), "Tab from the dialog goes to the first control");
  window.analyzeUpdate.close();

  escapeAborted = false;
  var pendingStatus = deferred();
  mockFetch(function () { return pendingStatus.promise; });
  var booting = window.analyzeUpdate._boot();
  settingsButton.click();
  pendingStatus.resolve(makeJsonResponse({ current: "1.4.1", supported: true, launch_check: false }));
  await booting;
  assertEqual(document.activeElement, settingsBox().querySelector(".settings-close"), "Focus stays on Close when /update/status redraws the dialog");
  escapeOn(document.activeElement);
  assertEqual(escapeAborted, false, "Escape after the redraw does not cancel the analysis");
  assert(!settingsOpen(), "Escape after the redraw closes the dialog");
  activeAbort = null;

  window.confirm = savedConfirm;
  resetState();

  // ================================================
  suite("UI sources and status icons contain no emoji");
  // ================================================

  var _PICTO = /\p{Extended_Pictographic}/u;
  function _decodeJsEscapes(src) {
    return src
      .replace(/\\u\{([0-9a-fA-F]+)\}/g, function(_, h) { return String.fromCodePoint(parseInt(h, 16)); })
      .replace(/\\u([0-9a-fA-F]{4})/g, function(_, h) { return String.fromCharCode(parseInt(h, 16)); })
      .replace(/&#x([0-9a-fA-F]+);/g, function(_, h) { return String.fromCodePoint(parseInt(h, 16)); });
  }
  for (var _src of ["index.html", "i18n.js", "main.js", "theme.js", "gate.js", "charts/timeline.js", "charts/histogram.js", "charts/segments.js"]) {
    var _resp = await _origFetch.call(window, "../../frontend/" + _src);
    var _text = await _resp.text();
    assert(_resp.ok && _text.length > 100, _src + " fetched for the emoji scan");
    var _hit = _decodeJsEscapes(_text).match(_PICTO);
    assert(_hit === null, _src + " has no emoji" + (_hit ? " (found U+" + _hit[0].codePointAt(0).toString(16).toUpperCase() + ")" : ""));
  }
  var _updateResponse = await _origFetch.call(window, "../../vendor/py-analyze-common/src/analyze_common/web/update.js");
  var _updateText = await _updateResponse.text();
  assert(_updateResponse.ok && _updateText.length > 100, "update.js fetched for the emoji scan");
  assert(!_PICTO.test(_decodeJsEscapes(_updateText)), "update.js has no emoji");
  resetState();
  showError("boom");
  assert(statusEl.querySelector(".error-icon svg") !== null, "Error icon is an SVG");
  assert(!_PICTO.test(statusEl.textContent), "Error status text has no emoji");
  statusEl.textContent = "";
  statusEl.className = "";

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
