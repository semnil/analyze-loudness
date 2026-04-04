/**
 * Loudness histogram on Canvas.
 * Bin width 0.5 LUFS, range -55 to -5, density normalized.
 */

function renderHistogram(canvas, values, label, integrated, silenceThreshold) {
  silenceThreshold = silenceThreshold ?? -60;
  const filtered = values.filter(v => v > silenceThreshold);
  if (filtered.length === 0) return;

  const binWidth = 0.5;
  const lo = -55, hi = -5;
  const nBins = Math.ceil((hi - lo) / binWidth);
  const counts = new Float64Array(nBins);

  for (const v of filtered) {
    const idx = Math.floor((v - lo) / binWidth);
    if (idx >= 0 && idx < nBins) counts[idx]++;
  }

  // density normalization
  const total = filtered.length * binWidth;
  const density = Array.from(counts, c => c / total);
  const maxDensity = Math.max(...density);

  const th = getTheme();
  const ctx = canvas.getContext("2d");
  const dpr = window.devicePixelRatio || 1;
  const w = canvas.clientWidth;
  const h = canvas.clientHeight || 250;
  canvas.width = w * dpr;
  canvas.height = h * dpr;
  ctx.scale(dpr, dpr);

  const pad = { top: 30, right: 20, bottom: 40, left: 50 };
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
  const median = sorted[Math.floor(sorted.length / 2)];
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
  ctx.font = "12px sans-serif";
  ctx.textAlign = "center";
  ctx.fillText(`${label} Loudness (LUFS)`, w / 2, h - 4);

  // title
  ctx.font = "bold 13px sans-serif";
  ctx.fillText(`${label} Distribution`, w / 2, 16);

  // x ticks
  ctx.font = "10px sans-serif";
  ctx.fillStyle = th.fgMuted;
  for (let v = lo; v <= hi; v += 10) {
    const x = pad.left + ((v - lo) / (hi - lo)) * pw;
    ctx.fillText(v.toString(), x, pad.top + ph + 16);
  }

  // legend
  ctx.font = "10px sans-serif";
  ctx.fillStyle = th.fg;
  ctx.textAlign = "right";
  ctx.fillText(`Median: ${median.toFixed(1)}`, w - pad.right, pad.top + 14);
}
