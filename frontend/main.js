let activeUPlots = [];
let chartCanvasRefs = [];

const form = document.getElementById("analyze-form");
const urlInput = document.getElementById("url-input");
const submitBtn = document.getElementById("submit-btn");
const loadBtn = document.getElementById("load-btn");
const statusEl = document.getElementById("status");
const resultsEl = document.getElementById("results");

function clearResults() {
  activeUPlots.forEach(u => u.destroy());
  activeUPlots = [];
  chartCanvasRefs = [];
  resultsEl.className = "";
  resultsEl.innerHTML = "";
}

function safeName(title) {
  return (title || "untitled").replace(/[\\/:*?"<>|]/g, "_").slice(0, 80);
}

form.addEventListener("submit", async (e) => {
  e.preventDefault();
  const url = urlInput.value.trim();
  if (!url) return;

  statusEl.textContent = "Starting...";
  statusEl.className = "";
  submitBtn.disabled = true;
  clearResults();

  try {
    const resp = await fetch(window.location.origin + "/analyze", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ url }),
    });

    if (!resp.ok) {
      const err = await resp.json().catch(() => ({}));
      throw new Error(err.error || `HTTP ${resp.status}`);
    }

    const data = await readNdjsonStream(resp);
    statusEl.textContent = "";
    render(data);
  } catch (err) {
    showError(err.message);
  } finally {
    submitBtn.disabled = false;
  }
});

loadBtn.addEventListener("click", async () => {
  loadBtn.disabled = true;
  statusEl.textContent = "Opening file...";
  statusEl.className = "";

  try {
    const resp = await fetch(window.location.origin + "/load", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: "{}",
    });
    const result = await resp.json();

    if (result.error) {
      showError(result.error);
      return;
    }
    if (!result.loaded) {
      statusEl.textContent = "";
      return;
    }

    clearResults();
    statusEl.textContent = "";
    render(result.data);
  } catch (err) {
    showError(err.message);
  } finally {
    loadBtn.disabled = false;
  }
});

async function readNdjsonStream(resp) {
  const reader = resp.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let result = null;
  let countdownTimer = null;

  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });

      const lines = buffer.split("\n");
      buffer = lines.pop();

      for (const line of lines) {
        if (!line.trim()) continue;
        const event = JSON.parse(line);

        if (event.type === "progress") {
          if (countdownTimer) clearInterval(countdownTimer);

          if (event.estimate_sec != null) {
            let remaining = event.estimate_sec;
            const durationMin = (event.duration_sec / 60).toFixed(1);
            statusEl.textContent =
              `${event.message} (${durationMin} min, ~${remaining}s remaining)`;
            countdownTimer = setInterval(() => {
              remaining--;
              if (remaining > 0) {
                statusEl.textContent =
                  `${event.message} (${durationMin} min, ~${remaining}s remaining)`;
              } else {
                statusEl.textContent = `${event.message} (finishing up...)`;
                clearInterval(countdownTimer);
                countdownTimer = null;
              }
            }, 1000);
          } else {
            statusEl.textContent = event.message;
          }
        } else if (event.type === "result") {
          result = event.data;
        } else if (event.type === "error") {
          throw new Error(event.error);
        }
      }
    }
  } finally {
    if (countdownTimer) clearInterval(countdownTimer);
  }

  if (!result) throw new Error("No result received from server");
  return result;
}

function render(data) {
  resultsEl.className = "visible";
  chartCanvasRefs = [];

  const { title, summary, series, meta } = data;
  const st = summary.short_term || {};
  const mo = summary.momentary || {};

  const titleRow = document.createElement("div");
  titleRow.className = "title-row";

  const titleEl = document.createElement("div");
  titleEl.className = "video-title";
  titleEl.textContent = title || "Untitled";
  titleRow.appendChild(titleEl);

  const saveBtn = document.createElement("button");
  saveBtn.className = "save-btn";
  saveBtn.textContent = "Save JSON";
  saveBtn.addEventListener("click", () => saveResult(data));
  titleRow.appendChild(saveBtn);

  const saveImgBtn = document.createElement("button");
  saveImgBtn.className = "save-btn";
  saveImgBtn.textContent = "Save Image";
  saveImgBtn.addEventListener("click", () => saveImage(data));
  titleRow.appendChild(saveImgBtn);

  resultsEl.appendChild(titleRow);

  if (meta) {
    const metaEl = document.createElement("div");
    metaEl.className = "meta-info";
    const parts = [];
    if (meta.analyzed_at) {
      const d = new Date(meta.analyzed_at);
      parts.push(d.toLocaleString());
    }
    if (meta.source_url) parts.push(meta.source_url);
    metaEl.textContent = parts.join(" | ");
    resultsEl.appendChild(metaEl);
  }

  const table = document.createElement("table");
  table.className = "summary-table";
  table.innerHTML = `
    <tr>
      <th>Duration</th><th>Integrated</th><th>True Peak</th><th>LRA</th>
    </tr>
    <tr>
      <td>${fmt(summary.duration_sec / 60, 1)} min (${summary.frames} frames)</td>
      <td>${fmt(summary.integrated, 1)} LUFS</td>
      <td>${summary.true_peak != null ? fmt(summary.true_peak, 1, true) + " dBFS" : "?"}</td>
      <td>${fmt(summary.lra, 1)} LU</td>
    </tr>
    <tr>
      <th>S-term Median</th><th>S-term P10/P90</th>
      <th>Mom. Median</th><th>Mom. P10/P90</th>
    </tr>
    <tr>
      <td>${fmt(st.median, 1)} LUFS</td>
      <td>${fmt(st.p10, 1)} / ${fmt(st.p90, 1)} LUFS</td>
      <td>${fmt(mo.median, 1)} LUFS</td>
      <td>${fmt(mo.p10, 1)} / ${fmt(mo.p90, 1)} LUFS</td>
    </tr>
    <tr><td colspan="4" style="text-align:right;color:#888;font-size:12px">
      Silence (S &lt; -40 LUFS): ${fmt(summary.silence_pct, 1)}%
    </td></tr>
  `;
  resultsEl.appendChild(table);

  const timeDiv = document.createElement("div");
  timeDiv.className = "chart-row";
  resultsEl.appendChild(timeDiv);
  const uplot = renderTimeline(timeDiv, series.t, series.S, summary.integrated);
  activeUPlots.push(uplot);
  if (uplot.ctx) chartCanvasRefs.push(uplot.ctx.canvas);

  const histRow = document.createElement("div");
  histRow.className = "chart-pair";

  const histS = document.createElement("div");
  const canvasS = document.createElement("canvas");
  canvasS.style.height = "250px";
  histS.appendChild(canvasS);
  histRow.appendChild(histS);

  const histM = document.createElement("div");
  const canvasM = document.createElement("canvas");
  canvasM.style.height = "250px";
  histM.appendChild(canvasM);
  histRow.appendChild(histM);

  resultsEl.appendChild(histRow);
  renderHistogram(canvasS, series.S, "Short-term", summary.integrated);
  renderHistogram(canvasM, series.M, "Momentary", summary.integrated);
  chartCanvasRefs.push(canvasS, canvasM);

  const segDiv = document.createElement("div");
  segDiv.className = "chart-row";
  const segCanvas = document.createElement("canvas");
  segCanvas.style.height = "200px";
  segDiv.appendChild(segCanvas);
  resultsEl.appendChild(segDiv);
  renderSegments(segCanvas, series.t, series.S, summary.integrated);
  chartCanvasRefs.push(segCanvas);
}

function fmt(val, decimals, showSign) {
  if (val == null) return "?";
  const s = val.toFixed(decimals);
  return showSign && val > 0 ? `+${s}` : s;
}

async function saveResult(data) {
  const filename = `loudness_${safeName(data.title)}.json`;
  try {
    const resp = await fetch(window.location.origin + "/save", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ data, filename }),
    });
    const result = await resp.json();
    if (result.saved) {
      statusEl.textContent = `Saved: ${result.path}`;
      statusEl.className = "";
    } else if (result.error) {
      showError(`Save failed: ${result.error}`);
    }
  } catch (err) {
    showError(`Save failed: ${err.message}`);
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

  // Chart heights (in CSS pixels)
  const chartSizes = [];
  for (const c of chartCanvasRefs) {
    if (!c || !c.width) continue;
    const h = c.height / dpr;
    const w = c.width / dpr;
    chartSizes.push({ canvas: c, w, h });
    totalH += h + 16;
  }
  totalH += PAD;

  const comp = document.createElement("canvas");
  comp.width = W * SCALE;
  comp.height = totalH * SCALE;
  const ctx = comp.getContext("2d");
  ctx.scale(SCALE, SCALE);

  // White background
  ctx.fillStyle = "#fff";
  ctx.fillRect(0, 0, W, totalH);

  let y = PAD;

  // Title
  ctx.fillStyle = "#4A148C";
  ctx.font = "bold 18px 'Segoe UI', 'Meiryo', sans-serif";
  ctx.textAlign = "center";
  ctx.fillText(title || "Untitled", W / 2, y + 18);
  y += 32;

  // Summary text
  ctx.fillStyle = "#333";
  ctx.font = "13px 'Segoe UI', 'Meiryo', sans-serif";
  ctx.textAlign = "left";
  const col1 = PAD, col2 = W / 2 + PAD;

  const lines = [
    [`Duration: ${fmt(summary.duration_sec / 60, 1)} min (${summary.frames} frames)`,
     `Integrated: ${fmt(summary.integrated, 1)} LUFS`],
    [`True Peak: ${summary.true_peak != null ? fmt(summary.true_peak, 1, true) + " dBFS" : "?"}`,
     `LRA: ${fmt(summary.lra, 1)} LU`],
    [`S-term Median: ${fmt(st.median, 1)} LUFS`,
     `Mom. Median: ${fmt(mo.median, 1)} LUFS`],
    [`S-term P10/P90: ${fmt(st.p10, 1)} / ${fmt(st.p90, 1)} LUFS`,
     `Mom. P10/P90: ${fmt(mo.p10, 1)} / ${fmt(mo.p90, 1)} LUFS`],
    [`Silence (S < -40 LUFS): ${fmt(summary.silence_pct, 1)}%`, ""],
  ];

  for (const [left, right] of lines) {
    y += LINE;
    ctx.fillText(left, col1, y);
    if (right) ctx.fillText(right, col2, y);
  }
  y += 12;

  // Separator
  ctx.strokeStyle = "#E1BEE7";
  ctx.lineWidth = 1;
  ctx.beginPath();
  ctx.moveTo(PAD, y);
  ctx.lineTo(W - PAD, y);
  ctx.stroke();
  y += 8;

  // Draw chart canvases
  for (const { canvas, w, h } of chartSizes) {
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
    statusEl.textContent = "Generating image...";
    statusEl.className = "";
    const dataUrl = captureImage(data);
    const resp = await fetch(window.location.origin + "/save-image", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ dataUrl, filename }),
    });
    const result = await resp.json();
    if (result.saved) {
      statusEl.textContent = `Saved: ${result.path}`;
      statusEl.className = "";
    } else if (result.error) {
      showError(`Save failed: ${result.error}`);
    } else {
      statusEl.textContent = "";
    }
  } catch (err) {
    showError(`Save failed: ${err.message}`);
  }
}

function showError(message) {
  statusEl.className = "error";
  statusEl.innerHTML = "";
  const text = document.createElement("span");
  text.textContent = `Error: ${message}`;
  statusEl.appendChild(text);
  const btn = document.createElement("button");
  btn.className = "copy-btn";
  btn.textContent = "Copy";
  btn.addEventListener("click", () => {
    navigator.clipboard.writeText(message).then(() => {
      btn.textContent = "Copied";
      setTimeout(() => { btn.textContent = "Copy"; }, 1500);
    });
  });
  statusEl.appendChild(btn);
}
