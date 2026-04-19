let activeUPlots = [];
let chartCanvasRefs = [];
let lastRenderedData = null;
let activeAbort = null;

const form = document.getElementById("analyze-form");
const urlInput = document.getElementById("url-input");
const submitBtn = document.getElementById("submit-btn");
const loadBtn = document.getElementById("load-btn");
const statusEl = document.getElementById("status");
const resultsEl = document.getElementById("results");

// Theme: "light" | "dark" | "auto" (follows system)
const _THEME_ICONS = { light: "\u2600\uFE0F", dark: "\u263E\uFE0F", auto: "\u25D0\uFE0F" };

function _systemDark() {
  return window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches;
}

let _themeMode = "auto";

function _applyTheme() {
  const resolved = _themeMode === "auto" ? (_systemDark() ? "dark" : "light") : _themeMode;
  document.documentElement.setAttribute("data-theme", resolved);
  const btn = document.getElementById("theme-toggle");
  btn.textContent = "";
  const icon = document.createElement("span");
  icon.setAttribute("aria-hidden", "true");
  icon.textContent = _THEME_ICONS[_themeMode];
  btn.appendChild(icon);
  btn.title = window.i18n.t("theme.title." + _themeMode);
  btn.setAttribute("aria-label", window.i18n.t("theme.aria_state." + _themeMode));
}

function _setThemeMode(mode) {
  _themeMode = mode;
  localStorage.setItem("loudness-theme", mode);
  const wasDark = isDark();
  _applyTheme();
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
window.i18n.onChange(function () {
  _applyLangButton();
  _applyTheme();
  if (lastRenderedData) rerender();
});

// Follow system changes when in auto mode
if (window.matchMedia) {
  window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", function() {
    if (_themeMode === "auto") {
      const wasDark = isDark();
      _applyTheme();
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

function _setBusy(busy, cancelable = true) {
  _isBusy = busy;
  loadBtn.disabled = busy;
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
    submitBtn.textContent = window.i18n.t("btn.analyze");
    submitBtn.classList.remove("cancelling");
    submitBtn.disabled = false;
    submitBtn.removeAttribute("aria-label");
    form.removeAttribute("aria-busy");
    statusEl.classList.remove("loading");
    activeAbort = null;
  }
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
  }
});

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
    resultsEl.scrollIntoView({ behavior: "smooth", block: "start" });
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
  try {
    const resp = await fetch(window.location.origin + "/load", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: "{}",
    });
    if (!resp.ok) {
      endedAbnormally = true;
      showError(window.i18n.t("err.load_failed_http") + resp.status);
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

    clearResults();
    statusEl.textContent = "";
    var src = result.data.meta && result.data.meta.source_url;
    if (src) urlInput.value = src;
    render(result.data);
  } catch (err) {
    endedAbnormally = true;
    showError(err.message);
  } finally {
    _setBusy(false);
    if (endedAbnormally) loadBtn.focus();
  }
});

async function readNdjsonStream(resp, signal) {
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
              event.message, window.i18n.t("status.countdown", { ...cdParams, remaining }));
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
            statusEl.textContent = event.message;
          }
        } else if (event.type === "warning") {
          statusEl.textContent = "\u26a0 " + event.message;
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
  render(lastRenderedData);
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

  const saveBtn = document.createElement("button");
  saveBtn.className = "save-btn";
  saveBtn.textContent = window.i18n.t("btn.save_json");
  saveBtn.addEventListener("click", async () => {
    saveBtn.disabled = true;
    try {
      await saveResult(data);
    } finally {
      saveBtn.disabled = false;
    }
  });
  titleRow.appendChild(saveBtn);

  const saveImgBtn = document.createElement("button");
  saveImgBtn.className = "save-btn";
  saveImgBtn.textContent = window.i18n.t("btn.save_image");
  saveImgBtn.addEventListener("click", async () => {
    saveImgBtn.disabled = true;
    try {
      await saveImage(data);
    } finally {
      saveImgBtn.disabled = false;
    }
  });
  titleRow.appendChild(saveImgBtn);

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

  const timeHeading = document.createElement("h3");
  timeHeading.className = "chart-title";
  timeHeading.setAttribute("data-chart-block", "1");
  timeHeading.textContent = window.i18n.t("chart.timeline_title");
  resultsEl.appendChild(timeHeading);
  const timeDiv = document.createElement("div");
  timeDiv.className = "chart-row";
  timeDiv.setAttribute("data-chart-block", "1");
  timeDiv.setAttribute("role", "img");
  timeDiv.setAttribute("aria-label", _timelineAriaLabel(summary, series, st));
  resultsEl.appendChild(timeDiv);
  const uplot = renderTimeline(timeDiv, series.t, series.S, summary.integrated);
  activeUPlots.push(uplot);
  if (uplot.ctx) chartCanvasRefs.push(uplot.ctx.canvas);

  const histHeading = document.createElement("h3");
  histHeading.className = "visually-hidden";
  histHeading.setAttribute("data-chart-block", "1");
  histHeading.textContent = window.i18n.t("chart.histograms_heading");
  resultsEl.appendChild(histHeading);
  const histRow = document.createElement("div");
  histRow.className = "chart-pair";
  histRow.setAttribute("data-chart-block", "1");

  const histS = document.createElement("div");
  histS.setAttribute("role", "img");
  histS.setAttribute("aria-label", _histogramAriaLabel(window.i18n.t("chart.label_short_term"), st));
  const canvasS = document.createElement("canvas");
  canvasS.className = "histogram-canvas";
  histS.appendChild(canvasS);
  histRow.appendChild(histS);

  const histM = document.createElement("div");
  histM.setAttribute("role", "img");
  histM.setAttribute("aria-label", _histogramAriaLabel(window.i18n.t("chart.label_momentary"), mo));
  const canvasM = document.createElement("canvas");
  canvasM.className = "histogram-canvas";
  histM.appendChild(canvasM);
  histRow.appendChild(histM);

  resultsEl.appendChild(histRow);
  renderHistogram(canvasS, series.S, window.i18n.t("chart.label_short_term"), summary.integrated);
  renderHistogram(canvasM, series.M, window.i18n.t("chart.label_momentary"), summary.integrated);
  chartCanvasRefs.push(canvasS, canvasM);

  const segHeading = document.createElement("h3");
  segHeading.className = "visually-hidden";
  segHeading.setAttribute("data-chart-block", "1");
  segHeading.textContent = window.i18n.t("chart.segments_heading");
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
  chartCanvasRefs.push(segCanvas);
}

function _reRenderCharts() {
  if (!lastRenderedData) return;
  activeUPlots.forEach(u => u.destroy());
  activeUPlots = [];
  chartCanvasRefs = [];
  resultsEl.querySelectorAll("[data-chart-block]").forEach(n => n.remove());
  _renderCharts(lastRenderedData);
}

function _timelineAriaLabel(summary, series, st) {
  return window.i18n.t("aria.timeline", {
    mins: fmt(summary.duration_sec / 60, 1),
    integrated: summary.integrated != null ? fmt(summary.integrated, 1) + " LUFS" : "unavailable",
    lo: fmt(st.p10, 1),
    hi: fmt(st.p90, 1),
  });
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

async function saveResult(data) {
  const filename = `loudness_${safeName(data.title)}.json`;
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

function captureImage(data) {
  const { title, summary } = data;
  const st = summary.short_term || {};
  const mo = summary.momentary || {};

  const dpr = window.devicePixelRatio || 1;
  const SCALE = 2;
  const W = 1100;
  const PAD = 24;
  const LINE = 20;
  let totalH = PAD;

  // Header: title + summary text block
  totalH += 32; // title
  totalH += LINE * 7 + 12; // summary lines + spacing

  // Chart titles baked into the composite PNG only.  The HTML uses .chart-title
  // above each canvas; the canvas bitmap itself has no text, so we redraw it here.
  const chartTitles = [window.i18n.t("chart.timeline_title"), null, null, null];

  // Chart heights (in CSS pixels)
  const chartSizes = [];
  for (let ci = 0; ci < chartCanvasRefs.length; ci++) {
    const c = chartCanvasRefs[ci];
    if (!c || !c.width) continue;
    const h = c.height / dpr;
    const w = c.width / dpr;
    const label = chartTitles[ci] || null;
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
  var displayTitle = title || window.i18n.t("summary.untitled");
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

  const tImg = window.i18n.t;
  const mi = tImg("summary.min");
  const fr = tImg("summary.frames");
  const lines = [
    [`${tImg("table.duration")}: ${fmt(summary.duration_sec / 60, 1)} ${mi} (${summary.frames} ${fr})`,
     `${tImg("table.integrated")}: ${fmt(summary.integrated, 1)} LUFS`],
    [`${tImg("table.true_peak")}: ${summary.true_peak != null ? fmt(summary.true_peak, 1, true) + " dBFS" : "?"}`,
     `${tImg("table.lra")}: ${fmt(summary.lra, 1)} LU`],
    [`${tImg("table.sterm_median")}: ${fmt(st.median, 1)} LUFS`,
     `${tImg("table.mom_median")}: ${fmt(mo.median, 1)} LUFS`],
    [`${tImg("table.sterm_p10p90")}: ${fmt(st.p10, 1)} / ${fmt(st.p90, 1)} LUFS`,
     `${tImg("table.mom_p10p90")}: ${fmt(mo.p10, 1)} / ${fmt(mo.p90, 1)} LUFS`],
    [`${tImg("table.silence")}: ${fmt(summary.silence_pct, 1)}%`, ""],
  ];

  for (const [left, right] of lines) {
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
  const filename = `loudness_${safeName(data.title)}.png`;
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
  icon.textContent = "\u26A0";
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
