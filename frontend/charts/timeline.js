/**
 * Short-term loudness timeline using uPlot.
 * Renders raw S data as a filled area and 60-frame moving average as a bold line.
 */

function movingAvg(arr, w) {
  const out = new Float64Array(arr.length);
  const half = Math.floor(w / 2);
  for (let i = 0; i < arr.length; i++) {
    let sum = 0, count = 0;
    const lo = Math.max(0, i - half);
    const hi = Math.min(arr.length - 1, i + half);
    for (let j = lo; j <= hi; j++) { sum += arr[j]; count++; }
    out[i] = sum / count;
  }
  return out;
}

function renderTimeline(container, t, S, integrated) {
  const tMin = t.map(v => v / 60);
  const sSmooth = movingAvg(S, 60);
  const th = getTheme();

  const opts = {
    width: container.clientWidth,
    height: 350,
    title: "Short-term Loudness (3s window)",
    scales: {
      x: { time: false },
      y: { range: [-55, -5] },
    },
    axes: [
      {
        label: "Time (min)",
        stroke: th.fg,
        grid: { stroke: th.gridStroke },
        ticks: { stroke: th.gridStroke },
      },
      {
        label: "Short-term LUFS",
        stroke: th.fg,
        grid: { stroke: th.gridStroke },
        ticks: { stroke: th.gridStroke },
      },
    ],
    series: [
      {},
      {
        label: "S raw",
        stroke: th.accentStroke,
        fill: th.accentFill,
        width: 0.5,
      },
      {
        label: "60s avg",
        stroke: th.accent,
        width: 2,
      },
      {
        label: `I: ${integrated?.toFixed(1) ?? "?"} LUFS`,
        stroke: th.accent,
        width: 1.2,
        dash: [6, 4],
        value: () => integrated?.toFixed(1) ?? "",
      },
      {
        label: "Target -23",
        stroke: th.green,
        width: 1,
        dash: [4, 4],
        value: () => "-23.0",
      },
    ],
  };

  const intLine = new Float64Array(t.length).fill(integrated ?? -23);
  const targetLine = new Float64Array(t.length).fill(-23);

  return new uPlot(opts, [tMin, S, sSmooth, intLine, targetLine], container);
}
