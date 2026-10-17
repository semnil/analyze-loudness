/**
 * Loudness histogram on Canvas.
 * Bin width 0.5 LUFS, range -55 to -5, density normalized.
 */

var HIST_BIN_WIDTH = 0.5;
var HIST_LO = -55, HIST_HI = -5;
var HIST_BINS = Math.ceil((HIST_HI - HIST_LO) / HIST_BIN_WIDTH);

/** Density per 0.5 LUFS bin of `filtered` (already cut at the silence threshold). */
function _histDensity(filtered) {
  const counts = new Float64Array(HIST_BINS);
  for (const v of filtered) {
    const idx = Math.floor((v - HIST_LO) / HIST_BIN_WIDTH);
    if (idx >= 0 && idx < HIST_BINS) counts[idx]++;
  }
  const total = filtered.length * HIST_BIN_WIDTH;
  return Array.from(counts, c => c / total);
}

function renderHistogram(canvas, values, label, integrated, silenceThreshold) {
  silenceThreshold = silenceThreshold ?? -60;
  const filtered = values.filter(v => v > silenceThreshold);
  if (filtered.length === 0) {
    var ctx0 = canvas.getContext("2d");
    var th0 = getTheme();
    ctx0.clearRect(0, 0, canvas.width, canvas.height);
    ctx0.fillStyle = th0.fgMuted;
    ctx0.font = "13px 'Segoe UI', 'Meiryo', sans-serif";
    ctx0.textAlign = "center";
    ctx0.textBaseline = "middle";
    ctx0.fillText(window.i18n.t("chart.no_data_silence"), canvas.width / 2, canvas.height / 2);
    return;
  }

  const lo = HIST_LO, hi = HIST_HI;
  const nBins = HIST_BINS;
  const density = _histDensity(filtered);
  const maxDensity = Math.max(...density);

  const th = getTheme();
  const ctx = canvas.getContext("2d");
  const dpr = window.devicePixelRatio || 1;
  const w = canvas.clientWidth;
  const h = canvas.clientHeight || 250;
  canvas.width = w * dpr;
  canvas.height = h * dpr;
  ctx.scale(dpr, dpr);

  const pad = { top: 12, right: 20, bottom: 40, left: 50 };
  const pw = w - pad.left - pad.right;
  const ph = h - pad.top - pad.bottom;

  ctx.clearRect(0, 0, w, h);

  // bars
  ctx.fillStyle = th.barFill;
  for (let i = 0; i < nBins; i++) {
    if (density[i] === 0) continue;
    const x = pad.left + (i / nBins) * pw;
    const bw = pw / nBins;
    const bh = (density[i] / maxDensity) * ph;
    ctx.fillRect(x, pad.top + ph - bh, bw, bh);
  }

  // integrated line
  if (integrated != null) {
    const ix = pad.left + ((integrated - lo) / (hi - lo)) * pw;
    ctx.strokeStyle = th.accent;
    ctx.lineWidth = 2;
    ctx.beginPath();
    ctx.moveTo(ix, pad.top);
    ctx.lineTo(ix, pad.top + ph);
    ctx.stroke();
  }

  // median line
  const sorted = filtered.slice().sort((a, b) => a - b);
  const mid = Math.floor(sorted.length / 2);
  const median = sorted.length % 2 ? sorted[mid] : (sorted[mid - 1] + sorted[mid]) / 2;
  const mx = pad.left + ((median - lo) / (hi - lo)) * pw;
  ctx.strokeStyle = th.fgMuted;
  ctx.lineWidth = 1.5;
  ctx.setLineDash([4, 3]);
  ctx.beginPath();
  ctx.moveTo(mx, pad.top);
  ctx.lineTo(mx, pad.top + ph);
  ctx.stroke();
  ctx.setLineDash([]);

  // axes labels
  ctx.fillStyle = th.fg;
  ctx.font = "12px 'Segoe UI', 'Meiryo', sans-serif";
  ctx.textAlign = "center";
  ctx.fillText(window.i18n.t("chart.hist_axis", { label }), w / 2, h - 4);

  // x ticks
  ctx.font = "10px 'Segoe UI', 'Meiryo', sans-serif";
  ctx.fillStyle = th.fgMuted;
  for (let v = lo; v <= hi; v += 10) {
    const x = pad.left + ((v - lo) / (hi - lo)) * pw;
    ctx.fillText(v.toString(), x, pad.top + ph + 16);
  }

  // legend
  ctx.font = "10px 'Segoe UI', 'Meiryo', sans-serif";
  ctx.textAlign = "left";
  const legendX = w - pad.right - 110;
  let legendY = pad.top + 6;
  const sampleX1 = legendX;
  const sampleX2 = legendX + 18;
  const textX = sampleX2 + 6;

  if (integrated != null) {
    ctx.strokeStyle = th.accent;
    ctx.lineWidth = 2;
    ctx.beginPath();
    ctx.moveTo(sampleX1, legendY); ctx.lineTo(sampleX2, legendY); ctx.stroke();
    ctx.fillStyle = th.fg;
    ctx.textBaseline = "middle";
    ctx.fillText(window.i18n.t("chart.hist_integrated", { val: integrated.toFixed(1) }), textX, legendY);
    legendY += 14;
  }

  ctx.strokeStyle = th.fgMuted;
  ctx.lineWidth = 1.5;
  ctx.setLineDash([4, 3]);
  ctx.beginPath();
  ctx.moveTo(sampleX1, legendY); ctx.lineTo(sampleX2, legendY); ctx.stroke();
  ctx.setLineDash([]);
  ctx.fillStyle = th.fg;
  ctx.textBaseline = "middle";
  ctx.fillText(window.i18n.t("chart.hist_median", { val: median.toFixed(1) }), textX, legendY);
  ctx.textBaseline = "alphabetic";
}

/**
 * Comparison histogram: one density outline per track on shared axes, each
 * marked with its track number at its highest bin.
 * @param items [{n, values, color}]
 */
function renderHistogramCompare(canvas, items, label, silenceThreshold) {
  silenceThreshold = silenceThreshold ?? -60;
  const th = getTheme();
  const ctx = canvas.getContext("2d");
  const dpr = window.devicePixelRatio || 1;
  const w = canvas.clientWidth;
  const h = canvas.clientHeight || 250;
  canvas.width = w * dpr;
  canvas.height = h * dpr;
  ctx.scale(dpr, dpr);
  ctx.clearRect(0, 0, w, h);

  const curves = [];
  for (const it of items) {
    const filtered = it.values.filter(v => v > silenceThreshold);
    if (filtered.length === 0) continue;
    curves.push({ n: it.n, color: it.color, density: _histDensity(filtered) });
  }
  if (curves.length === 0) {
    ctx.fillStyle = th.fgMuted;
    ctx.font = "13px 'Segoe UI', 'Meiryo', sans-serif";
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";
    ctx.fillText(window.i18n.t("chart.no_data_silence"), w / 2, h / 2);
    return;
  }
  const maxDensity = Math.max(...curves.map(c => Math.max(...c.density)));

  const pad = { top: 18, right: 20, bottom: 40, left: 50 };
  const pw = w - pad.left - pad.right;
  const ph = h - pad.top - pad.bottom;
  const bw = pw / HIST_BINS;
  const yOf = d => pad.top + ph - (d / maxDensity) * ph;

  ctx.lineWidth = 1.6;
  for (const c of curves) {
    ctx.strokeStyle = c.color;
    ctx.beginPath();
    ctx.moveTo(pad.left, pad.top + ph);
    for (let i = 0; i < HIST_BINS; i++) {
      const x = pad.left + i * bw;
      ctx.lineTo(x, yOf(c.density[i]));
      ctx.lineTo(x + bw, yOf(c.density[i]));
    }
    ctx.lineTo(pad.left + pw, pad.top + ph);
    ctx.stroke();
  }

  ctx.font = "bold 12px 'Segoe UI', 'Meiryo', sans-serif";
  ctx.textAlign = "center";
  ctx.textBaseline = "bottom";
  for (const c of curves) {
    let peak = 0;
    for (let i = 1; i < HIST_BINS; i++) if (c.density[i] > c.density[peak]) peak = i;
    ctx.fillStyle = c.color;
    ctx.fillText(String(c.n), pad.left + (peak + 0.5) * bw, yOf(c.density[peak]) - 2);
  }

  ctx.textBaseline = "alphabetic";
  ctx.fillStyle = th.fg;
  ctx.font = "12px 'Segoe UI', 'Meiryo', sans-serif";
  ctx.fillText(window.i18n.t("chart.hist_axis", { label }), w / 2, h - 4);
  ctx.font = "10px 'Segoe UI', 'Meiryo', sans-serif";
  ctx.fillStyle = th.fgMuted;
  for (let v = HIST_LO; v <= HIST_HI; v += 10) {
    const x = pad.left + ((v - HIST_LO) / (HIST_HI - HIST_LO)) * pw;
    ctx.fillText(v.toString(), x, pad.top + ph + 16);
  }
}
