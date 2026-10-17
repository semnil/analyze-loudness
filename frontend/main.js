let activeUPlots = [];
// {canvas, label} per chart, in page order; label is baked into the PNG export.
let chartCanvasRefs = [];
let lastRenderedData = null;
let lastCompareStats = null;
let lastGate = null;
let activeAbort = null;

// Mirror of MIN_TRACKS / MAX_TRACKS in src/analyze_loudness/compare.py.
const MIN_TRACKS = 2;
const MAX_TRACKS = 6;
// Mirror of _MAX_UPLOAD in src/analyze_loudness/gui.py.
const MAX_UPLOAD_BYTES = 500 * 1024 * 1024;
// Queued comparison tracks: {kind: "url" | "file", label, data?} or {kind: "json", label, data}.
// A track with data is compared as-is; a URL or file track without data is analysed.
let compareQueue = [];

const form = document.getElementById("analyze-form");
const urlInput = document.getElementById("url-input");
const submitBtn = document.getElementById("submit-btn");
const browseBtn = document.getElementById("browse-btn");
const addBtn = document.getElementById("add-btn");
const loadBtn = document.getElementById("load-btn");
const clearBtn = document.getElementById("clear-btn");
const trackList = document.getElementById("track-list");
const compareBar = document.getElementById("compare-bar");
const statusEl = document.getElementById("status");
const resultsEl = document.getElementById("results");

// Theme: "light" | "dark" | "auto" (follows system)
// 24x24 outline icons drawn with currentColor: sun / crescent moon / half-filled circle.
const _THEME_ICON_SHAPES = {
  light: [
    ["circle", { cx: 12, cy: 12, r: 4 }],
    ["path", { d: "M12 2v2M12 20v2M2 12h2M20 12h2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4" }],
  ],
  dark: [
    ["path", { d: "M20 14.5A8 8 0 1 1 9.5 4a6.5 6.5 0 0 0 10.5 10.5z" }],
  ],
  auto: [
    ["circle", { cx: 12, cy: 12, r: 8 }],
    ["path", { d: "M12 4a8 8 0 0 1 0 16z", fill: "currentColor" }],
  ],
};

// Warning triangle for status messages, same drawing conventions as the theme icons.
const _WARNING_ICON_SHAPES = [
  ["path", { d: "M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z" }],
  ["path", { d: "M12 9v4M12 17h.01" }],
];

function _createThemeIcon(mode) {
  return _createIcon(_THEME_ICON_SHAPES[mode], 18);
}

function _createIcon(shapes, size) {
  const ns = "http://www.w3.org/2000/svg";
  const svg = document.createElementNS(ns, "svg");
  svg.setAttribute("viewBox", "0 0 24 24");
  svg.setAttribute("width", String(size));
  svg.setAttribute("height", String(size));
  svg.setAttribute("fill", "none");
  svg.setAttribute("stroke", "currentColor");
  svg.setAttribute("stroke-width", "2");
  svg.setAttribute("stroke-linecap", "round");
  svg.setAttribute("stroke-linejoin", "round");
  svg.setAttribute("aria-hidden", "true");
  svg.setAttribute("focusable", "false");
  for (const [tag, attrs] of shapes) {
    const el = document.createElementNS(ns, tag);
    for (const k of Object.keys(attrs)) el.setAttribute(k, attrs[k]);
    svg.appendChild(el);
  }
  return svg;
}

function _systemDark() {
  return window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches;
}

let _themeMode = "auto";

function _applyTheme() {
  const resolved = _themeMode === "auto" ? (_systemDark() ? "dark" : "light") : _themeMode;
  document.documentElement.setAttribute("data-theme", resolved);
  const btn = document.getElementById("theme-toggle");
  btn.textContent = "";
  btn.appendChild(_createThemeIcon(_themeMode));
  btn.title = window.i18n.t("theme.title." + _themeMode);
  btn.setAttribute("aria-label", window.i18n.t("theme.aria_state." + _themeMode));
}

function _setThemeMode(mode) {
  _themeMode = mode;
  localStorage.setItem("loudness-theme", mode);
  const wasDark = isDark();
  _applyTheme();
  _renderQueue();
  if (isDark() !== wasDark && lastRenderedData) _reRenderCharts();
}

// Init theme
(function() {
  const saved = localStorage.getItem("loudness-theme");
  _themeMode = (saved === "light" || saved === "dark") ? saved : "auto";
  _applyTheme();
})();

// Cycle: light -> dark -> auto -> light
document.getElementById("theme-toggle").addEventListener("click", function() {
  const next = { light: "dark", dark: "auto", auto: "light" };
  _setThemeMode(next[_themeMode]);
});

// Language toggle (EN <-> JA)
function _applyLangButton() {
  const btn = document.getElementById("lang-toggle");
  if (!btn) return;
  const cur = window.i18n.lang();
  btn.textContent = window.i18n.t("lang.label." + cur);
  btn.title = window.i18n.t("lang.title." + cur);
}
_applyLangButton();
document.getElementById("lang-toggle").addEventListener("click", function () {
  const next = window.i18n.lang() === "ja" ? "en" : "ja";
  window.i18n.setLang(next);
});
function _applyDropText() {
  document.body.setAttribute("data-drop-text", window.i18n.t("drop.overlay"));
}
_applyDropText();

window.i18n.onChange(function () {
  _applyLangButton();
  _applyDropText();
  _applyTheme();
  _renderQueue();
  if (lastRenderedData) rerender();
});

// Follow system changes when in auto mode
if (window.matchMedia) {
  window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", function() {
    if (_themeMode === "auto") {
      const wasDark = isDark();
      _applyTheme();
      _renderQueue();
      if (isDark() !== wasDark && lastRenderedData) _reRenderCharts();
    }
  });
}

var _resizeTimer = null;
window.addEventListener("resize", function () {
  if (!lastRenderedData) return;
  clearTimeout(_resizeTimer);
  _resizeTimer = setTimeout(rerender, 200);
});

function clearResults() {
  activeUPlots.forEach(u => u.destroy());
  activeUPlots = [];
  chartCanvasRefs = [];
  resultsEl.className = "";
  resultsEl.innerHTML = "";
}

function safeName(title) {
  return (title || "untitled").replace(/[\x00-\x1f\\/:*?"<>|]/g, "_").slice(0, 80);
}

let _isBusy = false;

function _submitLabel() {
  return window.i18n.t(compareQueue.length > 0 ? "btn.compare" : "btn.analyze");
}

function _setBusy(busy, cancelable = true) {
  _isBusy = busy;
  loadBtn.disabled = busy;
  browseBtn.disabled = busy;
  addBtn.disabled = busy;
  clearBtn.disabled = busy;
  if (busy) {
    if (cancelable) {
      submitBtn.textContent = window.i18n.t("btn.cancel");
      submitBtn.classList.add("cancelling");
      submitBtn.disabled = false;
      submitBtn.setAttribute("aria-label", window.i18n.t("btn.cancel.aria"));
    } else {
      submitBtn.textContent = window.i18n.t("btn.loading");
      submitBtn.classList.remove("cancelling");
      submitBtn.disabled = true;
      submitBtn.removeAttribute("aria-label");
    }
    form.setAttribute("aria-busy", "true");
    statusEl.classList.add("loading");
  } else {
    submitBtn.textContent = _submitLabel();
    submitBtn.classList.remove("cancelling");
    submitBtn.disabled = false;
    submitBtn.removeAttribute("aria-label");
    form.removeAttribute("aria-busy");
    statusEl.classList.remove("loading");
    activeAbort = null;
  }
  _renderQueue();
}

function _cancelActive() {
  if (activeAbort) activeAbort.abort();
}

function _setStatusNormal() {
  // Keep the .loading modifier so the spinner persists across status updates.
  statusEl.classList.remove("error");
  statusEl.setAttribute("role", "status");
  statusEl.setAttribute("aria-live", "polite");
}

document.addEventListener("keydown", (e) => {
  if (e.isComposing || e.keyCode === 229) return;
  if (e.key === "Escape" && activeAbort) {
    e.preventDefault();
    _cancelActive();
    return;
  }
  if (e.key === "Escape" && _tipEl) _hideTip();
});

// Tooltip system -- positions dynamically to stay within viewport.
var _TIP_KEYS = {
  "table.duration": "tip.duration",
  "table.integrated": "tip.integrated",
  "table.true_peak": "tip.true_peak",
  "table.lra": "tip.lra",
  "table.sterm_median": "tip.sterm_median",
  "table.sterm_p10p90": "tip.sterm_p10p90",
  "table.mom_median": "tip.mom_median",
  "table.mom_p10p90": "tip.mom_p10p90",
  "table.silence": "tip.silence",
  "table.integrated_full": "tip.integrated_full",
  "table.true_peak_full": "tip.true_peak_full",
  "table.lra_full": "tip.lra_full",
  "chart.timeline_title": "tip.chart_timeline",
  "chart.histogram": "tip.chart_histogram",
  "chart.segments": "tip.chart_segments",
};

function _tipFor(key) {
  var tipKey = _TIP_KEYS[key];
  return tipKey ? () => window.i18n.t(tipKey) : undefined;
}

var _tipEl = null;
var _tipTimer = null;
var _tipAnchor = null;
var _tipSeq = 0;

function _showTip(anchor, text) {
  _hideTip();
  _tipAnchor = anchor;
  _tipTimer = setTimeout(() => {
    _tipEl = document.createElement("div");
    _tipEl.className = "tip-popup";
    _tipEl.setAttribute("role", "tooltip");
    _tipEl.id = anchor.getAttribute("aria-describedby") || ("tip-" + (++_tipSeq));
    anchor.setAttribute("aria-describedby", _tipEl.id);
    _tipEl.textContent = text;
    document.body.appendChild(_tipEl);
    var r = anchor.getBoundingClientRect();
    var tw = 300, th = _tipEl.offsetHeight;
    var left = r.left + r.width / 2 - tw / 2;
    var top = r.bottom + 6;
    if (left < 4) left = 4;
    if (left + tw > window.innerWidth - 4) left = window.innerWidth - tw - 4;
    if (top + th > window.innerHeight - 4) top = r.top - th - 6;
    _tipEl.style.left = left + "px";
    _tipEl.style.top = top + "px";
  }, 200);
}

function _hideTip() {
  clearTimeout(_tipTimer);
  if (_tipAnchor) _tipAnchor.removeAttribute("aria-describedby");
  _tipAnchor = null;
  if (_tipEl) { _tipEl.remove(); _tipEl = null; }
}

function _addTip(cell, textOrFn) {
  cell.className = (cell.className ? cell.className + " " : "") + "has-tip";
  cell.tabIndex = 0;
  var resolve = typeof textOrFn === "function" ? textOrFn : () => textOrFn;
  cell.addEventListener("mouseenter", () => _showTip(cell, resolve()));
  cell.addEventListener("mouseleave", _hideTip);
  cell.addEventListener("focus", () => _showTip(cell, resolve()));
  cell.addEventListener("blur", _hideTip);
}

function _buildSummaryTable(ariaKey, headerKeys, valueStrings) {
  const table = document.createElement("table");
  table.className = "summary-table";
  table.setAttribute("aria-label", window.i18n.t(ariaKey));
  const thead = document.createElement("thead");
  const headerRow = document.createElement("tr");
  for (const key of headerKeys) {
    const th = document.createElement("th");
    th.setAttribute("scope", "col");
    th.textContent = window.i18n.t(key);
    const tip = _tipFor(key);
    if (tip) _addTip(th, tip);
    headerRow.appendChild(th);
  }
  thead.appendChild(headerRow);
  table.appendChild(thead);
  const tbody = document.createElement("tbody");
  const valueRow = document.createElement("tr");
  for (const v of valueStrings) {
    const td = document.createElement("td");
    if (v instanceof Node) td.appendChild(v);
    else td.textContent = v;
    valueRow.appendChild(td);
  }
  tbody.appendChild(valueRow);
  table.appendChild(tbody);
  return table;
}

function _naCell(title) {
  const span = document.createElement("span");
  span.title = title;
  span.textContent = "\u2014";
  return span;
}

// Build a status message whose countdown portion is aria-hidden so the
// polite live region doesn't re-announce every second.
function _setStatusWithCountdown(message, countdownText) {
  _setStatusNormal();
  statusEl.textContent = "";
  const msgSpan = document.createElement("span");
  msgSpan.textContent = message + " ";
  statusEl.appendChild(msgSpan);
  const countdown = document.createElement("span");
  countdown.className = "countdown";
  countdown.setAttribute("aria-hidden", "true");
  countdown.textContent = countdownText;
  statusEl.appendChild(countdown);
  return countdown;
}

form.addEventListener("submit", async (e) => {
  e.preventDefault();
  if (_isBusy) { _cancelActive(); return; }
  if (compareQueue.length > 0) { await _runCompare(); return; }
  const url = urlInput.value.trim();
  if (!url) return;

  statusEl.textContent = window.i18n.t("status.starting");
  _setStatusNormal();
  _setBusy(true);
  clearResults();

  activeAbort = new AbortController();
  let endedAbnormally = false;
  try {
    const resp = await fetch(window.location.origin + "/analyze", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ url }),
      signal: activeAbort.signal,
    });

    if (!resp.ok) {
      const err = await resp.json().catch(() => ({}));
      throw new Error(err.error || `HTTP ${resp.status}`);
    }

    const data = await readNdjsonStream(resp, activeAbort.signal);
    statusEl.textContent = "";
    render(data);
    resultsEl.focus({ preventScroll: true });
  } catch (err) {
    endedAbnormally = true;
    if (err.name === "AbortError") {
      _setStatusNormal();
      statusEl.textContent = window.i18n.t("status.cancelled");
    } else {
      showError(err.message);
    }
  } finally {
    _setBusy(false);
    if (endedAbnormally) urlInput.focus();
  }
});

loadBtn.addEventListener("click", async () => {
  if (_isBusy) return;
  _setBusy(true, false);
  _setStatusNormal();
  statusEl.textContent = window.i18n.t("status.opening_file");

  let endedAbnormally = false;
  const loadAbort = new AbortController();
  const loadTimer = setTimeout(function () { loadAbort.abort(); }, 120000);
  try {
    const resp = await fetch(window.location.origin + "/load", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: "{}",
      signal: loadAbort.signal,
    });
    if (!resp.ok) {
      endedAbnormally = true;
      const errBody = await resp.json().catch(function () { return {}; });
      showError(errBody.error || window.i18n.t("err.load_failed_http") + resp.status);
      return;
    }
    const result = await resp.json();

    if (result.error) {
      endedAbnormally = true;
      showError(result.error);
      return;
    }
    if (!result.loaded) {
      statusEl.textContent = "";
      return;
    }

    if (result.data.compare) {
      if (compareQueue.length > 0) {
        endedAbnormally = true;
        showError(window.i18n.t("err.compare_queue_busy"));
        return;
      }
      clearResults();
      statusEl.textContent = "";
      renderCompare(result.data, result.stats);
      return;
    }
    if (compareQueue.length > 0) {
      if (!_queueTrack({ kind: "json", label: result.data.title || window.i18n.t("summary.untitled"),
                         data: result.data })) {
        endedAbnormally = true;
        return;
      }
      statusEl.textContent = "";
      return;
    }

    clearResults();
    statusEl.textContent = "";
    var src = result.data.meta && result.data.meta.source_url;
    if (src) urlInput.value = src;
    render(result.data);
  } catch (err) {
    endedAbnormally = true;
    if (err.name === "AbortError") {
      showError(window.i18n.t("err.dialog_timeout"));
    } else {
      showError(err.message);
    }
  } finally {
    clearTimeout(loadTimer);
    _setBusy(false);
    if (endedAbnormally) loadBtn.focus();
  }
});

// ------ Comparison queue ------

// Adds a track to the queue; shows the error and returns false when full.
function _queueTrack(item) {
  if (compareQueue.length >= MAX_TRACKS) {
    showError(window.i18n.t("err.max_tracks", { max: MAX_TRACKS }));
    return false;
  }
  compareQueue.push(item);
  _renderQueue();
  return true;
}

// Mirror of the /analyze check in src/analyze_loudness/gui.py: anything
// scheme-like must be http(s); everything else is a local path.
// UNC and device paths (two leading slashes or backslashes) are "network"
// and refused, as is_network_path in src/analyze_loudness/download.py.
function _sourceKind(source) {
  if (/^https?:\/\//i.test(source)) return "url";
  if (source.indexOf("://") !== -1 || /^javascript:/i.test(source)) return null;
  if (/^[\\/]{2}/.test(source)) return "network";
  return "file";
}

// Moves a non-empty URL field into the queue.  Returns false (with the error
// shown) on a non-http(s) scheme or a full queue; an empty field is a no-op.
function _queueUrlInput() {
  const source = urlInput.value.trim();
  if (!source) return true;
  const kind = _sourceKind(source);
  if (!kind || kind === "network") {
    showError(window.i18n.t(kind ? "err.network_path" : "err.url_scheme"));
    return false;
  }
  // The source of the single result on screen queues that result itself:
  // the server's URL cache keeps only the latest result loaded for a URL.
  const shown = lastRenderedData && !lastRenderedData.compare && lastRenderedData.meta &&
    lastRenderedData.meta.source_url === source ? lastRenderedData : undefined;
  if (!_queueTrack({ kind, label: source, data: shown })) return false;
  urlInput.value = "";
  return true;
}

addBtn.addEventListener("click", () => {
  if (_isBusy) return;
  if (!urlInput.value.trim()) { urlInput.focus(); return; }
  _setStatusNormal();
  statusEl.textContent = "";
  if (_queueUrlInput()) urlInput.focus();
});

clearBtn.addEventListener("click", () => {
  if (_isBusy) return;
  compareQueue = [];
  _renderQueue();
  urlInput.focus();
});

browseBtn.addEventListener("click", async () => {
  if (_isBusy) return;
  try {
    const resp = await fetch(window.location.origin + "/browse", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: "{}",
    });
    const result = await resp.json().catch(() => ({}));
    if (!resp.ok) {
      showError(result.error || `HTTP ${resp.status}`);
      return;
    }
    if (result.selected) {
      urlInput.value = result.path;
      urlInput.focus();
    }
  } catch (err) {
    showError(err.message);
  }
});

// Drag & drop: capture phase on window, so the WebView never navigates to
// the dropped file.  One file with an empty queue goes into the field;
// otherwise every dropped file joins the queue.
window.addEventListener("dragover", (e) => {
  e.preventDefault();
  e.stopImmediatePropagation();
  e.dataTransfer.dropEffect = "copy";
  document.body.classList.add("drag-over");
}, true);

window.addEventListener("dragenter", (e) => {
  e.preventDefault();
  e.stopImmediatePropagation();
}, true);

window.addEventListener("dragleave", (e) => {
  if (!e.relatedTarget) document.body.classList.remove("drag-over");
}, true);

window.addEventListener("drop", async (e) => {
  e.preventDefault();
  e.stopImmediatePropagation();
  document.body.classList.remove("drag-over");
  if (_isBusy) return;
  const files = Array.from(e.dataTransfer.files);
  if (!files.length) return;
  const toField = files.length === 1 && compareQueue.length === 0;

  for (const file of files) {
    if (file.size > MAX_UPLOAD_BYTES) {
      showError(window.i18n.t("err.file_too_large"));
      continue;
    }
    _setStatusNormal();
    statusEl.textContent = window.i18n.t("status.uploading") + file.name;
    try {
      const resp = await fetch(window.location.origin + "/upload", {
        method: "POST",
        headers: {
          "Content-Type": "application/octet-stream",
          "X-Filename": encodeURIComponent(file.name),
        },
        body: file,
      });
      const result = await resp.json().catch(() => ({}));
      if (!resp.ok || !result.uploaded) {
        showError(result.error || `HTTP ${resp.status}`);
        continue;
      }
      if (toField) {
        urlInput.value = result.path;
        urlInput.focus();
      } else if (!_queueTrack({ kind: "file", label: result.path })) {
        break;
      }
      statusEl.textContent = window.i18n.t("status.file_loaded") + file.name;
    } catch (err) {
      showError(err.message);
    }
  }
}, true);

function _moveTrack(from, to) {
  const item = compareQueue[from];
  compareQueue[from] = compareQueue[to];
  compareQueue[to] = item;
  _renderQueue();
}

function _trackButton(cls, text, ariaKey, n, onClick) {
  const btn = document.createElement("button");
  btn.type = "button";
  btn.className = "track-btn " + cls;
  btn.textContent = text;
  btn.setAttribute("aria-label", window.i18n.t(ariaKey, { n }));
  btn.disabled = _isBusy;
  btn.addEventListener("click", onClick);
  return btn;
}

// Up/down arrows keep their slot at the ends so rows stay aligned.
function _placeholder(btn) {
  btn.classList.add("placeholder");
  btn.disabled = true;
  btn.setAttribute("aria-hidden", "true");
  btn.tabIndex = -1;
  return btn;
}

function _renderQueue() {
  trackList.textContent = "";
  const colors = getTheme().trackColors;
  compareQueue.forEach(function (item, k) {
    const n = k + 1;
    const row = document.createElement("div");
    row.className = "track-item";
    row.setAttribute("role", "listitem");

    const swatch = document.createElement("span");
    swatch.className = "track-swatch";
    swatch.setAttribute("aria-hidden", "true");
    swatch.style.background = colors[k];
    row.appendChild(swatch);

    const num = document.createElement("span");
    num.className = "track-num";
    num.textContent = String(n);
    row.appendChild(num);

    const tag = document.createElement("span");
    tag.className = "track-tag";
    tag.textContent = window.i18n.t("track.tag_" + item.kind);
    row.appendChild(tag);

    const label = document.createElement("span");
    label.className = "track-label";
    label.textContent = item.label;
    label.title = item.label;
    row.appendChild(label);

    const up = _trackButton("", "↑", "track.move_up", n, () => _moveTrack(k, k - 1));
    row.appendChild(k === 0 ? _placeholder(up) : up);
    const down = _trackButton("", "↓", "track.move_down", n, () => _moveTrack(k, k + 1));
    row.appendChild(k === compareQueue.length - 1 ? _placeholder(down) : down);
    row.appendChild(_trackButton("remove", "×", "track.remove", n, () => {
      compareQueue.splice(k, 1);
      _renderQueue();
    }));
    trackList.appendChild(row);
  });
  compareBar.hidden = compareQueue.length === 0;
  // With tracks queued an empty field is a valid Compare.
  urlInput.required = compareQueue.length === 0;
  if (!_isBusy) submitBtn.textContent = _submitLabel();
}

async function _runCompare() {
  _setStatusNormal();
  statusEl.textContent = "";
  if (!_queueUrlInput()) return;
  if (compareQueue.length < MIN_TRACKS) {
    showError(window.i18n.t("err.compare_min"));
    return;
  }
  const items = compareQueue.slice();
  statusEl.textContent = window.i18n.t("status.starting");
  _setBusy(true);
  clearResults();

  activeAbort = new AbortController();
  const signal = activeAbort.signal;
  let endedAbnormally = false;
  try {
    const tracks = [];
    for (let k = 0; k < items.length; k++) {
      const item = items[k];
      if (item.data) { tracks.push(item.data); continue; }
      const prefix = window.i18n.t("status.track_prefix", { i: k + 1, n: items.length });
      statusEl.textContent = prefix + window.i18n.t("status.starting");
      try {
        const resp = await fetch(window.location.origin + "/analyze", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ url: item.label }),
          signal,
        });
        if (!resp.ok) {
          const err = await resp.json().catch(() => ({}));
          throw new Error(err.error || `HTTP ${resp.status}`);
        }
        tracks.push(await readNdjsonStream(resp, signal, prefix));
      } catch (err) {
        if (err.name === "AbortError") throw err;
        throw new Error(window.i18n.t("err.track_failed", { i: k + 1, msg: err.message }));
      }
    }

    statusEl.textContent = window.i18n.t("status.comparing");
    const resp = await fetch(window.location.origin + "/compare", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ tracks }),
      signal,
    });
    const body = await resp.json().catch(() => ({}));
    if (!resp.ok) throw new Error(body.error || `HTTP ${resp.status}`);
    statusEl.textContent = "";
    renderCompare(body.data, body.stats);
    resultsEl.focus({ preventScroll: true });
  } catch (err) {
    endedAbnormally = true;
    if (err.name === "AbortError") {
      _setStatusNormal();
      statusEl.textContent = window.i18n.t("status.cancelled");
    } else {
      showError(err.message);
    }
  } finally {
    _setBusy(false);
    if (endedAbnormally) urlInput.focus();
  }
}

// `prefix` leads every status line (comparison: which track is running).
async function readNdjsonStream(resp, signal, prefix = "") {
  const reader = resp.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let result = null;
  let countdownTimer = null;

  if (signal) {
    signal.addEventListener("abort", () => reader.cancel(), { once: true });
  }

  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });

      const lines = buffer.split("\n");
      buffer = lines.pop();

      for (const line of lines) {
        if (!line.trim()) continue;
        let event;
        try {
          event = JSON.parse(line);
        } catch (parseErr) {
          console.warn("Skipping malformed NDJSON line:", line, parseErr);
          continue;
        }

        if (event.type === "progress") {
          if (countdownTimer) clearInterval(countdownTimer);

          if (event.estimate_sec != null) {
            let remaining = event.estimate_sec;
            const durationMin = (event.duration_sec / 60).toFixed(1);
            const reducedMotion = window.matchMedia &&
              window.matchMedia("(prefers-reduced-motion: reduce)").matches;
            const tick = reducedMotion ? 5000 : 1000;
            const step = reducedMotion ? 5 : 1;
            const minUnit = window.i18n.t("summary.min");
            const cdParams = { duration: durationMin, unit: minUnit };
            const countdown = _setStatusWithCountdown(
              prefix + event.message, window.i18n.t("status.countdown", { ...cdParams, remaining }));
            countdownTimer = setInterval(() => {
              remaining -= step;
              if (remaining > 0) {
                countdown.textContent =
                  " " + window.i18n.t("status.countdown", { ...cdParams, remaining });
              } else {
                countdown.textContent = window.i18n.t("status.finishing_up");
                clearInterval(countdownTimer);
                countdownTimer = null;
              }
            }, tick);
          } else {
            statusEl.textContent = prefix + event.message;
          }
        } else if (event.type === "warning") {
          statusEl.textContent = "";
          const warnIcon = _createIcon(_WARNING_ICON_SHAPES, 16);
          warnIcon.setAttribute("class", "inline-icon");
          statusEl.appendChild(warnIcon);
          statusEl.appendChild(document.createTextNode(prefix + event.message));
        } else if (event.type === "result") {
          result = event.data;
        } else if (event.type === "error") {
          throw new Error(event.error);
        }
      }
    }
  } catch (err) {
    if (err.name === "AbortError" || (signal && signal.aborted)) {
      throw new DOMException("Aborted", "AbortError");
    }
    throw err;
  } finally {
    if (countdownTimer) clearInterval(countdownTimer);
  }

  if (!result) throw new Error(window.i18n.t("err.no_result"));
  return result;
}

function rerender() {
  if (!lastRenderedData) return;
  clearResults();
  if (lastRenderedData.compare) renderCompare(lastRenderedData, lastCompareStats);
  else render(lastRenderedData);
}

function _appendSaveButtons(row, data) {
  for (const [key, save] of [["btn.save_json", saveResult], ["btn.save_image", saveImage]]) {
    const btn = document.createElement("button");
    btn.className = "save-btn";
    btn.textContent = window.i18n.t(key);
    btn.addEventListener("click", async () => {
      btn.disabled = true;
      try {
        await save(data);
      } finally {
        btn.disabled = false;
      }
    });
    row.appendChild(btn);
  }
}

function render(data) {
  lastRenderedData = data;
  resultsEl.className = "visible";
  chartCanvasRefs = [];

  const { title, summary, series, meta } = data;
  const st = summary.short_term || {};
  const mo = summary.momentary || {};

  const titleRow = document.createElement("div");
  titleRow.className = "title-row";

  const titleEl = document.createElement("h2");
  titleEl.className = "video-title";
  titleEl.textContent = title || window.i18n.t("summary.untitled");
  titleRow.appendChild(titleEl);

  _appendSaveButtons(titleRow, data);
  resultsEl.appendChild(titleRow);

  if (meta) {
    const metaEl = document.createElement("div");
    metaEl.className = "meta-info";
    let hasContent = false;
    if (meta.analyzed_at) {
      const d = new Date(meta.analyzed_at);
      const text = isNaN(d) ? (meta.analyzed_at || "\u2014") : d.toLocaleString();
      metaEl.appendChild(document.createTextNode(text));
      hasContent = true;
    }
    if (meta.source_url) {
      if (hasContent) metaEl.appendChild(document.createTextNode(" | "));
      metaEl.appendChild(_sourceUrlNode(meta.source_url));
      hasContent = true;
    }
    resultsEl.appendChild(metaEl);
  }

  const tpeakNa = window.i18n.t("summary.true_peak_na");
  const minUnit = window.i18n.t("summary.min");
  const framesUnit = window.i18n.t("summary.frames");
  const summaryTable = _buildSummaryTable(
    "summary.aria.loudness",
    ["table.duration", "table.integrated", "table.true_peak", "table.lra"],
    [
      fmt(summary.duration_sec / 60, 1) + " " + minUnit + " (" + fmt(summary.frames, 0) + " " + framesUnit + ")",
      fmt(summary.integrated, 1) + " LUFS",
      summary.true_peak != null
        ? fmt(summary.true_peak, 1, true) + " dBFS"
        : _naCell(tpeakNa),
      fmt(summary.lra, 1) + " LU",
    ]
  );
  resultsEl.appendChild(summaryTable);

  const distTable = _buildSummaryTable(
    "summary.aria.distribution",
    ["table.sterm_median", "table.sterm_p10p90", "table.mom_median", "table.mom_p10p90"],
    [
      fmt(st.median, 1) + " LUFS",
      fmt(st.p10, 1) + " / " + fmt(st.p90, 1) + " LUFS",
      fmt(mo.median, 1) + " LUFS",
      fmt(mo.p10, 1) + " / " + fmt(mo.p90, 1) + " LUFS",
    ]
  );
  const silenceRow = document.createElement("tr");
  silenceRow.className = "silence-row";
  const silenceTh = document.createElement("th");
  silenceTh.setAttribute("scope", "row");
  silenceTh.setAttribute("colspan", "3");
  silenceTh.textContent = window.i18n.t("table.silence");
  const silenceTip = _tipFor("table.silence");
  if (silenceTip) _addTip(silenceTh, silenceTip);
  silenceRow.appendChild(silenceTh);
  const silenceTd = document.createElement("td");
  silenceTd.textContent = fmt(summary.silence_pct, 1) + "%";
  silenceRow.appendChild(silenceTd);
  distTable.querySelector("tbody").appendChild(silenceRow);
  resultsEl.appendChild(distTable);

  _renderCharts(data);
}

function _renderCharts(data) {
  const { summary, series } = data;
  const st = summary.short_term || {};
  const mo = summary.momentary || {};
  // A loaded JSON is user-supplied: only gate when M lines up with the time
  // axis, otherwise the lane would map states onto the wrong instants.
  lastGate = (series.M && series.t && series.M.length === series.t.length)
    ? computeGate(series.M, series.t, summary.gate_threshold) : null;

  const timeHeading = document.createElement("h3");
  timeHeading.className = "chart-title";
  timeHeading.setAttribute("data-chart-block", "1");
  timeHeading.textContent = window.i18n.t("chart.timeline_title");
  const timeTip = _tipFor("chart.timeline_title");
  if (timeTip) _addTip(timeHeading, timeTip);
  resultsEl.appendChild(timeHeading);
  const timeDiv = document.createElement("div");
  timeDiv.className = lastGate ? "chart-row has-gate" : "chart-row";
  timeDiv.setAttribute("data-chart-block", "1");
  timeDiv.setAttribute("role", "img");
  timeDiv.setAttribute("aria-label", _timelineAriaLabel(summary, series, st));
  resultsEl.appendChild(timeDiv);
  const uplot = renderTimeline(timeDiv, series.t, series.S, summary.integrated, lastGate);
  activeUPlots.push(uplot);
  if (uplot.ctx) chartCanvasRefs.push({ canvas: uplot.ctx.canvas, label: timeHeading.textContent });
  if (lastGate) resultsEl.appendChild(_buildGateCaption(lastGate));

  const histRow = document.createElement("div");
  histRow.className = "chart-pair";
  histRow.setAttribute("data-chart-block", "1");

  // role="img" belongs on the canvas itself (as in analyze-spectrum), not on the
  // column: ARIA marks the children of an image presentational, so a heading
  // nested inside it -- and the tooltip description it carries -- can be dropped
  // from the accessibility tree.
  const histTip = _tipFor("chart.histogram");

  const histS = document.createElement("div");
  const histSTitle = document.createElement("h3");
  histSTitle.className = "chart-title";
  histSTitle.textContent = window.i18n.t("chart.hist_title", { label: window.i18n.t("chart.label_short_term") });
  if (histTip) _addTip(histSTitle, histTip);
  histS.appendChild(histSTitle);
  const canvasS = document.createElement("canvas");
  canvasS.className = "histogram-canvas";
  canvasS.setAttribute("role", "img");
  canvasS.setAttribute("aria-label", _histogramAriaLabel(window.i18n.t("chart.label_short_term"), st));
  histS.appendChild(canvasS);
  histRow.appendChild(histS);

  const histM = document.createElement("div");
  const histMTitle = document.createElement("h3");
  histMTitle.className = "chart-title";
  histMTitle.textContent = window.i18n.t("chart.hist_title", { label: window.i18n.t("chart.label_momentary") });
  if (histTip) _addTip(histMTitle, histTip);
  histM.appendChild(histMTitle);
  const canvasM = document.createElement("canvas");
  canvasM.className = "histogram-canvas";
  canvasM.setAttribute("role", "img");
  canvasM.setAttribute("aria-label", _histogramAriaLabel(window.i18n.t("chart.label_momentary"), mo));
  histM.appendChild(canvasM);
  histRow.appendChild(histM);

  resultsEl.appendChild(histRow);
  renderHistogram(canvasS, series.S, window.i18n.t("chart.label_short_term"), summary.integrated);
  renderHistogram(canvasM, series.M, window.i18n.t("chart.label_momentary"), summary.integrated);
  chartCanvasRefs.push({ canvas: canvasS, label: histSTitle.textContent },
                      { canvas: canvasM, label: histMTitle.textContent });

  const segHeading = document.createElement("h3");
  segHeading.className = "chart-title";
  segHeading.setAttribute("data-chart-block", "1");
  segHeading.textContent = window.i18n.t("chart.seg_title");
  const segTip = _tipFor("chart.segments");
  if (segTip) _addTip(segHeading, segTip);
  resultsEl.appendChild(segHeading);
  const segDiv = document.createElement("div");
  segDiv.className = "chart-row";
  segDiv.setAttribute("data-chart-block", "1");
  segDiv.setAttribute("role", "img");
  segDiv.setAttribute("aria-label", _segmentsAriaLabel(summary));
  const segCanvas = document.createElement("canvas");
  segCanvas.className = "segments-canvas";
  segDiv.appendChild(segCanvas);
  resultsEl.appendChild(segDiv);
  renderSegments(segCanvas, series.t, series.S, summary.integrated);
  chartCanvasRefs.push({ canvas: segCanvas, label: segHeading.textContent });
}

function _reRenderCharts() {
  if (!lastRenderedData) return;
  activeUPlots.forEach(u => u.destroy());
  activeUPlots = [];
  chartCanvasRefs = [];
  resultsEl.querySelectorAll("[data-chart-block]").forEach(n => n.remove());
  if (lastRenderedData.compare) {
    // Track swatches outside the chart blocks (table headings) take the new colours.
    const colors = getTheme().trackColors;
    resultsEl.querySelectorAll(".track-swatch[data-track]").forEach(function (swatch) {
      swatch.style.background = colors[Number(swatch.dataset.track)];
    });
    _renderCompareCharts(lastRenderedData, lastCompareStats);
  } else {
    _renderCharts(lastRenderedData);
  }
}

// Reading row under the timeline: what the GATE lane adds up to, plus the key
// to its colors.  The lane itself carries no text.
function _buildGateCaption(gate) {
  const row = document.createElement("div");
  row.className = "gate-caption";
  row.setAttribute("data-chart-block", "1");

  const facts = document.createElement("p");
  const pct = document.createElement("strong");
  pct.className = "gate-pct";
  pct.textContent = fmt(gate.countedPct, 1) + "%";
  facts.appendChild(pct);
  facts.appendChild(document.createTextNode(
    " " + window.i18n.t("gate.counted_of_timeline") + " \u00b7 " +
    window.i18n.t("gate.excluded_detail", {
      below: fmt(gate.belowPct, 1),
      threshold: fmt(gate.threshold, 1),
      silent: fmt(gate.silentPct, 1),
    })));
  row.appendChild(facts);
  row.appendChild(_buildGateLegend());
  return row;
}

function _buildGateLegend() {
  const legend = document.createElement("p");
  legend.className = "gate-legend";
  for (const [cls, key] of [["counted", "gate.counted"],
                            ["out", "gate.out"],
                            ["silent", "gate.silence"]]) {
    const item = document.createElement("span");
    item.className = "gate-key";
    const swatch = document.createElement("span");
    swatch.className = "gate-swatch " + cls;
    swatch.setAttribute("aria-hidden", "true");
    item.appendChild(swatch);
    item.appendChild(document.createTextNode(window.i18n.t(key)));
    legend.appendChild(item);
  }
  return legend;
}

// ------ Comparison view ------

// Stats are per track over the cut range (server-computed); whole-track
// figures come from each track's own summary.
function renderCompare(doc, stats) {
  lastRenderedData = doc;
  lastCompareStats = stats || [];
  lastGate = null;
  resultsEl.className = "visible";
  chartCanvasRefs = [];
  const tracks = doc.compare.tracks;

  const titleRow = document.createElement("div");
  titleRow.className = "title-row";
  const titleEl = document.createElement("h2");
  titleEl.className = "video-title";
  titleEl.textContent = window.i18n.t("compare.title", { n: tracks.length });
  titleRow.appendChild(titleEl);
  _appendSaveButtons(titleRow, doc);
  resultsEl.appendChild(titleRow);

  const scope = document.createElement("p");
  scope.className = "compare-scope";
  scope.textContent = window.i18n.t("compare.scope", { mins: fmt(doc.compare.truncate_sec / 60, 1) });
  resultsEl.appendChild(scope);

  resultsEl.appendChild(_buildCompareTable(tracks, lastCompareStats));
  _renderCompareCharts(doc, lastCompareStats);
}

function _trackHeading(tag, cls, k, text) {
  const el = document.createElement(tag);
  el.className = cls;
  const swatch = document.createElement("span");
  swatch.className = "track-swatch";
  swatch.setAttribute("aria-hidden", "true");
  swatch.dataset.track = String(k);
  swatch.style.background = getTheme().trackColors[k];
  el.appendChild(swatch);
  el.appendChild(document.createTextNode(text));
  return el;
}

function _buildCompareTable(tracks, stats) {
  const t = window.i18n.t;
  const minUnit = t("summary.min");
  const framesUnit = t("summary.frames");
  const rows = [
    ["table.duration", (track, st) =>
      fmt(st.duration_sec / 60, 1) + " " + minUnit + " (" + fmt(st.frames, 0) + " " + framesUnit + ")"],
    ["table.integrated", (track, st) => fmt(st.integrated, 1) + " LUFS"],
    ["table.integrated_full", (track) => fmt(track.summary.integrated, 1) + " LUFS"],
    ["table.true_peak_full", (track) => track.summary.true_peak != null
      ? fmt(track.summary.true_peak, 1, true) + " dBFS" : _naCell(t("summary.true_peak_na"))],
    ["table.lra_full", (track) => fmt(track.summary.lra, 1) + " LU"],
    ["table.sterm_median", (track, st) => fmt((st.short_term || {}).median, 1) + " LUFS"],
    ["table.sterm_p10p90", (track, st) =>
      fmt((st.short_term || {}).p10, 1) + " / " + fmt((st.short_term || {}).p90, 1) + " LUFS"],
    ["table.mom_median", (track, st) => fmt((st.momentary || {}).median, 1) + " LUFS"],
    ["table.mom_p10p90", (track, st) =>
      fmt((st.momentary || {}).p10, 1) + " / " + fmt((st.momentary || {}).p90, 1) + " LUFS"],
    ["table.silence", (track, st) => fmt(st.silence_pct, 1) + "%"],
  ];

  const table = document.createElement("table");
  table.className = "summary-table compare-table";
  table.setAttribute("aria-label", t("summary.aria.compare"));
  const thead = document.createElement("thead");
  const headRow = document.createElement("tr");
  const corner = document.createElement("th");
  corner.setAttribute("scope", "col");
  corner.textContent = t("table.track");
  headRow.appendChild(corner);
  tracks.forEach(function (track, k) {
    const name = track.title || t("summary.untitled");
    const th = _trackHeading("th", "track-head", k, (k + 1) + ": " + name);
    th.setAttribute("scope", "col");
    th.title = name;
    headRow.appendChild(th);
  });
  thead.appendChild(headRow);
  table.appendChild(thead);

  const tbody = document.createElement("tbody");
  for (const [key, cell] of rows) {
    const row = document.createElement("tr");
    const th = document.createElement("th");
    th.setAttribute("scope", "row");
    th.textContent = t(key);
    const tip = _tipFor(key);
    if (tip) _addTip(th, tip);
    row.appendChild(th);
    tracks.forEach(function (track, k) {
      const td = document.createElement("td");
      const v = cell(track, stats[k] || {});
      if (v instanceof Node) td.appendChild(v);
      else td.textContent = v;
      row.appendChild(td);
    });
    tbody.appendChild(row);
  }
  table.appendChild(tbody);
  return table;
}

function _renderCompareCharts(doc, stats) {
  const t = window.i18n.t;
  const tracks = doc.compare.tracks;
  const colors = getTheme().trackColors;
  const mins = fmt(doc.compare.truncate_sec / 60, 1);
  // The relative gate is recomputed on the cut range: each track's
  // summary.gate_threshold belongs to its whole length.
  const items = tracks.map(function (track, k) {
    const s = track.series;
    return {
      n: k + 1,
      color: colors[k],
      S: s.S,
      M: s.M,
      gate: (s.M && s.t && s.M.length === s.t.length) ? computeGate(s.M, s.t, null) : null,
    };
  });

  const timeHeading = document.createElement("h3");
  timeHeading.className = "chart-title";
  timeHeading.setAttribute("data-chart-block", "1");
  timeHeading.textContent = t("chart.timeline_title");
  const timeTip = _tipFor("chart.timeline_title");
  if (timeTip) _addTip(timeHeading, timeTip);
  resultsEl.appendChild(timeHeading);
  const anyGate = items.some(it => it.gate != null);
  const timeDiv = document.createElement("div");
  timeDiv.className = anyGate ? "chart-row has-gate" : "chart-row";
  timeDiv.setAttribute("data-chart-block", "1");
  timeDiv.setAttribute("role", "img");
  timeDiv.setAttribute("aria-label", t("aria.compare_timeline", { count: tracks.length, mins }));
  resultsEl.appendChild(timeDiv);
  const uplot = renderCompareTimeline(timeDiv, tracks[0].series.t, items);
  activeUPlots.push(uplot);
  if (uplot.ctx) chartCanvasRefs.push({ canvas: uplot.ctx.canvas, label: timeHeading.textContent });

  if (anyGate) {
    const caption = document.createElement("div");
    caption.className = "gate-caption";
    caption.setAttribute("data-chart-block", "1");
    const facts = document.createElement("p");
    facts.className = "gate-compare-facts";
    for (const it of items) {
      if (!it.gate) continue;
      const line = document.createElement("span");
      line.textContent = t("gate.compare_counted", { n: it.n, counted: fmt(it.gate.countedPct, 1) });
      facts.appendChild(line);
    }
    caption.appendChild(facts);
    caption.appendChild(_buildGateLegend());
    resultsEl.appendChild(caption);
  }

  const histRow = document.createElement("div");
  histRow.className = "chart-pair";
  histRow.setAttribute("data-chart-block", "1");
  resultsEl.appendChild(histRow);
  const histTip = _tipFor("chart.histogram");
  // Both columns go in before drawing: each canvas takes its size from the
  // laid-out row.
  const hists = [["chart.label_short_term", "S"], ["chart.label_momentary", "M"]].map(function ([labelKey, field]) {
    const kind = t(labelKey);
    const col = document.createElement("div");
    const title = document.createElement("h3");
    title.className = "chart-title";
    title.textContent = t("chart.hist_title", { label: kind });
    if (histTip) _addTip(title, histTip);
    col.appendChild(title);
    const canvas = document.createElement("canvas");
    canvas.className = "histogram-canvas";
    canvas.setAttribute("role", "img");
    canvas.setAttribute("aria-label", t("aria.compare_histogram", { kind, count: tracks.length }));
    col.appendChild(canvas);
    histRow.appendChild(col);
    return { kind, field, canvas, label: title.textContent };
  });
  for (const h of hists) {
    renderHistogramCompare(h.canvas, items.map(it => ({ n: it.n, color: it.color, values: it[h.field] })), h.kind);
    chartCanvasRefs.push({ canvas: h.canvas, label: h.label });
  }

  const segHeading = document.createElement("h3");
  segHeading.className = "chart-title";
  segHeading.setAttribute("data-chart-block", "1");
  segHeading.textContent = t("chart.seg_title");
  const segTip = _tipFor("chart.segments");
  if (segTip) _addTip(segHeading, segTip);
  resultsEl.appendChild(segHeading);
  tracks.forEach(function (track, k) {
    const st = stats[k] || {};
    const name = track.title || t("summary.untitled");
    const head = _trackHeading("h4", "compare-seg-title", k, t("chart.compare_seg_title", { n: k + 1, title: name }));
    head.setAttribute("data-chart-block", "1");
    resultsEl.appendChild(head);
    const segDiv = document.createElement("div");
    segDiv.className = "chart-row";
    segDiv.setAttribute("data-chart-block", "1");
    segDiv.setAttribute("role", "img");
    segDiv.setAttribute("aria-label", t("aria.compare_segments", {
      n: k + 1,
      integrated: st.integrated != null ? fmt(st.integrated, 1) + " LUFS" : "unavailable",
    }));
    const canvas = document.createElement("canvas");
    canvas.className = "segments-canvas";
    segDiv.appendChild(canvas);
    resultsEl.appendChild(segDiv);
    renderSegments(canvas, track.series.t, track.series.S, st.integrated, undefined, colors[k]);
    chartCanvasRefs.push({ canvas, label: head.textContent });
  });
}

function _timelineAriaLabel(summary, series, st) {
  let label = window.i18n.t("aria.timeline", {
    mins: fmt(summary.duration_sec / 60, 1),
    integrated: summary.integrated != null ? fmt(summary.integrated, 1) + " LUFS" : "unavailable",
    lo: fmt(st.p10, 1),
    hi: fmt(st.p90, 1),
  });
  if (lastGate) {
    label += " " + window.i18n.t("aria.gate_lane", {
      counted: fmt(lastGate.countedPct, 1),
      below: fmt(lastGate.belowPct, 1),
      threshold: fmt(lastGate.threshold, 1),
      silent: fmt(lastGate.silentPct, 1),
    });
  }
  return label;
}

function _histogramAriaLabel(kind, stats) {
  return window.i18n.t("aria.histogram", {
    kind,
    median: fmt(stats.median, 1),
    p10: fmt(stats.p10, 1),
    p90: fmt(stats.p90, 1),
  });
}

function _segmentsAriaLabel(summary) {
  return window.i18n.t("aria.segments", {
    integrated: summary.integrated != null ? fmt(summary.integrated, 1) + " LUFS" : "unavailable",
    lra: fmt(summary.lra, 1),
  });
}

function fmt(val, decimals, showSign) {
  if (val == null || !isFinite(val)) return "?";
  const s = val.toFixed(decimals);
  return showSign && val > 0 ? `+${s}` : s;
}

function _sourceUrlNode(url) {
  // Only http(s) URLs become clickable links; anything else is plain text
  // to avoid javascript: / data: injection in the WebView.
  try {
    const parsed = new URL(url);
    if (parsed.protocol === "http:" || parsed.protocol === "https:") {
      const a = document.createElement("a");
      a.href = parsed.href;
      a.target = "_blank";
      a.rel = "noopener noreferrer";
      a.textContent = url;
      return a;
    }
  } catch (_) {
    // fall through to text node
  }
  return document.createTextNode(url);
}

function _exportStem(data) {
  return data.compare
    ? `loudness_compare_${data.compare.tracks.length}tracks`
    : `loudness_${safeName(data.title)}`;
}

async function saveResult(data) {
  const filename = `${_exportStem(data)}.json`;
  try {
    const resp = await fetch(window.location.origin + "/save", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ data, filename }),
    });
    if (!resp.ok) {
      showError(window.i18n.t("err.save_failed_http") + resp.status);
      return;
    }
    const result = await resp.json();
    if (result.saved) {
      _setStatusNormal();
      statusEl.textContent = window.i18n.t("status.saved") + result.path;
    } else if (result.error) {
      showError(window.i18n.t("err.save_failed") + result.error);
    }
  } catch (err) {
    showError(window.i18n.t("err.save_failed") + err.message);
  }
}

// Header text of the PNG export for a single result: [left, right] pairs.
function _singleImageText(data) {
  const { title, summary } = data;
  const st = summary.short_term || {};
  const mo = summary.momentary || {};
  const tImg = window.i18n.t;
  const mi = tImg("summary.min");
  const fr = tImg("summary.frames");
  return {
    title: title || tImg("summary.untitled"),
    lines: [
      [`${tImg("table.duration")}: ${fmt(summary.duration_sec / 60, 1)} ${mi} (${summary.frames} ${fr})`,
       `${tImg("table.integrated")}: ${fmt(summary.integrated, 1)} LUFS`],
      [`${tImg("table.true_peak")}: ${summary.true_peak != null ? fmt(summary.true_peak, 1, true) + " dBFS" : "?"}`,
       `${tImg("table.lra")}: ${fmt(summary.lra, 1)} LU`],
      [`${tImg("table.sterm_median")}: ${fmt(st.median, 1)} LUFS`,
       `${tImg("table.mom_median")}: ${fmt(mo.median, 1)} LUFS`],
      [`${tImg("table.sterm_p10p90")}: ${fmt(st.p10, 1)} / ${fmt(st.p90, 1)} LUFS`,
       `${tImg("table.mom_p10p90")}: ${fmt(mo.p10, 1)} / ${fmt(mo.p90, 1)} LUFS`],
      [`${tImg("table.silence")}: ${fmt(summary.silence_pct, 1)}%`,
       lastGate ? `${tImg("gate.counted")}: ${fmt(lastGate.countedPct, 1)}% (${tImg("gate.out")} ${fmt(lastGate.belowPct, 1)}% @ ${fmt(lastGate.threshold, 1)} LUFS)` : ""],
    ],
  };
}

// Header text of the PNG export for a comparison: the scope, then one line
// per track (cut-range figures left, whole-track figures right).
function _compareImageText(doc) {
  const tImg = window.i18n.t;
  const tracks = doc.compare.tracks;
  const stats = lastCompareStats || [];
  const lines = [[tImg("compare.scope", { mins: fmt(doc.compare.truncate_sec / 60, 1) }), ""]];
  tracks.forEach(function (track, k) {
    const st = stats[k] || {};
    const summary = track.summary || {};
    const name = track.title || tImg("summary.untitled");
    lines.push([
      `${k + 1}: ${name.length > 40 ? name.slice(0, 39) + "\u2026" : name}`,
      `${tImg("table.integrated")} ${fmt(st.integrated, 1)} LUFS ` +
      `(${tImg("compare.full_value", { val: fmt(summary.integrated, 1) })}) · ` +
      `${tImg("table.true_peak_full")} ${fmt(summary.true_peak, 1, true)} · ${tImg("table.lra_full")} ${fmt(summary.lra, 1)}`,
    ]);
  });
  return { title: tImg("compare.title", { n: tracks.length }), lines };
}

function captureImage(data) {
  const text = data.compare ? _compareImageText(data) : _singleImageText(data);

  const dpr = window.devicePixelRatio || 1;
  const SCALE = 2;
  const W = 1100;
  const PAD = 24;
  const LINE = 20;
  let totalH = PAD;

  // Header: title + summary text block
  totalH += 32; // title
  totalH += LINE * (text.lines.length + 2) + 12; // summary lines + spacing

  // Chart titles are baked into the composite PNG only.  The HTML uses
  // .chart-title above each canvas; the canvas bitmap itself has no text, so
  // we redraw it here.
  const chartSizes = [];
  for (const ref of chartCanvasRefs) {
    const c = ref.canvas;
    if (!c || !c.width) continue;
    const h = c.height / dpr;
    const w = c.width / dpr;
    const label = ref.label || null;
    chartSizes.push({ canvas: c, w, h, label });
    if (label) totalH += 22;
    totalH += h + 16;
  }
  if (chartSizes.length === 0) {
    showError(window.i18n.t("err.charts_not_ready"));
    return null;
  }
  totalH += PAD;

  const th = getTheme();

  const comp = document.createElement("canvas");
  comp.width = W * SCALE;
  comp.height = totalH * SCALE;
  const ctx = comp.getContext("2d");
  ctx.scale(SCALE, SCALE);

  // Background
  ctx.fillStyle = th.surface;
  ctx.fillRect(0, 0, W, totalH);

  let y = PAD;

  // Title
  ctx.fillStyle = th.titleColor;
  ctx.font = "bold 18px 'Segoe UI', 'Meiryo', sans-serif";
  ctx.textAlign = "center";
  var displayTitle = text.title;
  var maxTitleW = W - PAD * 2;
  while (ctx.measureText(displayTitle).width > maxTitleW && displayTitle.length > 4) {
    displayTitle = displayTitle.slice(0, -4) + "\u2026";
  }
  ctx.fillText(displayTitle, W / 2, y + 18);
  y += 32;

  // Summary text
  ctx.fillStyle = th.fg;
  ctx.font = "13px 'Segoe UI', 'Meiryo', sans-serif";
  ctx.textAlign = "left";
  const col1 = PAD, col2 = W / 2 + PAD;

  for (const [left, right] of text.lines) {
    y += LINE;
    ctx.fillText(left, col1, y);
    if (right) ctx.fillText(right, col2, y);
  }
  y += 12;

  // Separator
  ctx.strokeStyle = th.separator;
  ctx.lineWidth = 1;
  ctx.beginPath();
  ctx.moveTo(PAD, y);
  ctx.lineTo(W - PAD, y);
  ctx.stroke();
  y += 8;

  // Draw chart canvases
  for (const { canvas, w, h, label } of chartSizes) {
    if (label) {
      ctx.fillStyle = th.fg;
      ctx.font = "bold 13px 'Segoe UI', 'Meiryo', sans-serif";
      ctx.textAlign = "center";
      ctx.fillText(label, W / 2, y + 14);
      y += 22;
    }
    const drawW = Math.min(w, W - PAD * 2);
    const drawH = h * (drawW / w);
    const x = (W - drawW) / 2;
    ctx.drawImage(canvas, x, y, drawW, drawH);
    y += drawH + 16;
  }

  return comp.toDataURL("image/png");
}

async function saveImage(data) {
  const filename = `${_exportStem(data)}.png`;
  try {
    const dataUrl = captureImage(data);
    if (!dataUrl) return;
    _setStatusNormal();
    statusEl.textContent = window.i18n.t("status.generating_image");
    const resp = await fetch(window.location.origin + "/save-image", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ dataUrl, filename }),
    });
    if (!resp.ok) {
      showError(window.i18n.t("err.save_failed_http") + resp.status);
      return;
    }
    const result = await resp.json();
    if (result.saved) {
      _setStatusNormal();
      statusEl.textContent = window.i18n.t("status.saved") + result.path;
    } else if (result.error) {
      showError(window.i18n.t("err.save_failed") + result.error);
    } else {
      statusEl.textContent = "";
    }
  } catch (err) {
    showError(window.i18n.t("err.save_failed") + err.message);
  }
}

function showError(message) {
  statusEl.setAttribute("role", "alert");
  statusEl.setAttribute("aria-live", "assertive");
  statusEl.classList.remove("loading");
  statusEl.classList.add("error");
  statusEl.textContent = "";
  const icon = document.createElement("span");
  icon.className = "error-icon";
  icon.setAttribute("aria-hidden", "true");
  icon.appendChild(_createIcon(_WARNING_ICON_SHAPES, 16));
  statusEl.appendChild(icon);
  const text = document.createElement("span");
  text.className = "error-text";
  text.textContent = window.i18n.t("err.prefix") + message;
  statusEl.appendChild(text);
  if (navigator.clipboard) {
    const btn = document.createElement("button");
    btn.className = "copy-btn";
    btn.textContent = window.i18n.t("btn.copy");
    btn.addEventListener("click", () => {
      navigator.clipboard.writeText(message).then(() => {
        btn.textContent = window.i18n.t("btn.copied");
        setTimeout(() => { btn.textContent = window.i18n.t("btn.copy"); }, 1500);
      }).catch(() => {
        btn.textContent = window.i18n.t("btn.copy_failed");
        setTimeout(() => { btn.textContent = window.i18n.t("btn.copy"); }, 1500);
      });
    });
    statusEl.appendChild(btn);
  }
}
