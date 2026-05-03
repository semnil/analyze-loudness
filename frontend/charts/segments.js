/**
 * 5-minute segment bar chart with P10-P90 error bars on Canvas.
 */

function renderSegments(canvas, t, S, integrated, silenceThreshold) {
  silenceThreshold = silenceThreshold ?? -60;
  const segSec = 5 * 60;
  const segments = [];
  const maxT = t[t.length - 1];

  for (let start = 0; start < maxT; start += segSec) {
    const end = start + segSec;
    const vals = [];
    for (let i = 0; i < t.length; i++) {
      if (t[i] >= start && t[i] < end && S[i] > silenceThreshold) {
        vals.push(S[i]);
      }
    }
    if (vals.length > 0) {
      vals.sort((a, b) => a - b);
      const n = vals.length;
      segments.push({
        label: `${Math.floor(start / 60)}-${Math.floor(end / 60)}`,
        mean: vals.reduce((a, b) => a + b, 0) / n,
        p10: vals[Math.max(0, Math.floor(n * 0.10))],
        p90: vals[Math.min(n - 1, Math.floor(n * 0.90))],
      });
    } else {
      segments.push({
        label: `${Math.floor(start / 60)}-${Math.floor(end / 60)}`,
        mean: null, p10: null, p90: null,
      });
    }
  }

  const th = getTheme();
  const ctx = canvas.getContext("2d");
  const dpr = window.devicePixelRatio || 1;
  const w = canvas.clientWidth;
  const h = canvas.clientHeight || 200;
  canvas.width = w * dpr;
  canvas.height = h * dpr;
  ctx.scale(dpr, dpr);

  const pad = { top: 12, right: 20, bottom: 40, left: 70 };
  const pw = w - pad.left - pad.right;
  const ph = h - pad.top - pad.bottom;

  ctx.clearRect(0, 0, w, h);

  // y scale: find range
  const allVals = segments.filter(s => s.mean != null);
  if (allVals.length === 0) {
    ctx.fillStyle = th.fgMuted;
    ctx.font = "13px 'Segoe UI', 'Meiryo', sans-serif";
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";
    ctx.fillText(window.i18n.t("chart.no_data_silence"), w / 2, h / 2);
    return;
  }
  const yMin = Math.min(...allVals.map(s => s.p10)) - 2;
  const yMax = Math.max(...allVals.map(s => s.p90)) + 2;
  const yRange = yMax - yMin || 1;

  // Y axis ticks (5 LU steps)
  var yTickStart = Math.ceil(yMin / 5) * 5;
  ctx.fillStyle = th.fgMuted;
  ctx.strokeStyle = th.border || th.fgMuted;
  ctx.lineWidth = 0.5;
  ctx.font = "10px 'Segoe UI', 'Meiryo', sans-serif";
  ctx.textAlign = "right";
  ctx.textBaseline = "middle";
  for (var yv = yTickStart; yv <= yMax; yv += 5) {
    var yy = pad.top + ph - ((yv - yMin) / yRange) * ph;
    ctx.fillText(yv + " LUFS", pad.left - 6, yy);
    ctx.beginPath();
    ctx.moveTo(pad.left, yy);
    ctx.lineTo(pad.left + pw, yy);
    ctx.stroke();
  }
  ctx.textBaseline = "alphabetic";

  const barW = (pw / segments.length) * 0.6;

  for (let i = 0; i < segments.length; i++) {
    const s = segments[i];
    const cx = pad.left + (i + 0.5) * (pw / segments.length);

    if (s.mean != null) {
      // bar
      const barH = ((s.mean - yMin) / yRange) * ph;
      ctx.fillStyle = th.barFill;
      ctx.fillRect(cx - barW / 2, pad.top + ph - barH, barW, barH);

      // error bar
      const y10 = pad.top + ph - ((s.p10 - yMin) / yRange) * ph;
      const y90 = pad.top + ph - ((s.p90 - yMin) / yRange) * ph;
      ctx.strokeStyle = th.fgMuted;
      ctx.lineWidth = 1.5;
      ctx.beginPath();
      ctx.moveTo(cx, y10);
      ctx.lineTo(cx, y90);
      ctx.moveTo(cx - 4, y10);
      ctx.lineTo(cx + 4, y10);
      ctx.moveTo(cx - 4, y90);
      ctx.lineTo(cx + 4, y90);
      ctx.stroke();
    }

    // x label
    ctx.fillStyle = th.fgMuted;
    ctx.font = "10px 'Segoe UI', 'Meiryo', sans-serif";
    ctx.textAlign = "center";
    ctx.fillText(s.label, cx, pad.top + ph + 16);
  }

  // integrated line
  if (integrated != null) {
    const iy = pad.top + ph - ((integrated - yMin) / yRange) * ph;
    ctx.strokeStyle = th.accent;
    ctx.lineWidth = 1;
    ctx.setLineDash([4, 4]);
    ctx.beginPath();
    ctx.moveTo(pad.left, iy);
    ctx.lineTo(pad.left + pw, iy);
    ctx.stroke();
    ctx.setLineDash([]);
  }

  // axis label
  ctx.fillStyle = th.fg;
  ctx.font = "12px 'Segoe UI', 'Meiryo', sans-serif";
  ctx.textAlign = "center";
  ctx.fillText(window.i18n.t("chart.seg_axis"), w / 2, h - 4);
}
