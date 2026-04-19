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
    for (let j = lo; j <= hi; j++) { if (arr[j] != null && Number.isFinite(arr[j])) { sum += arr[j]; count++; } }
    out[i] = count > 0 ? sum / count : null;
  }
  return out;
}

function renderTimeline(container, t, S, integrated) {
  const tMin = t.map(v => v / 60);
  const sSmooth = movingAvg(S, 60);
  const th = getTheme();
  const hasIntegrated = integrated != null;

  const i = window.i18n.t.bind(window.i18n);
  const series = [
    { label: i("chart.tl_time") },
    {
      label: i("chart.tl_s_raw"),
      stroke: th.accentStroke,
      fill: th.accentFill,
      width: 0.5,
    },
    {
      label: i("chart.tl_avg"),
      stroke: th.accent,
      width: 2,
    },
  ];
  if (hasIntegrated) {
    series.push({
      label: i("chart.tl_integrated", { val: integrated.toFixed(1) }),
      stroke: th.accent,
      width: 1.2,
      value: () => integrated.toFixed(1),
    });
  }
  series.push({
    label: i("chart.tl_target"),
    stroke: th.green,
    width: 1,
    dash: [10, 5],
    value: () => "-23.0",
  });

  const opts = {
    width: container.clientWidth,
    height: 350,
    scales: {
      x: { time: false },
      y: {
        range: (self, dataMin, dataMax) => {
          var lo = dataMin != null ? dataMin : -55;
          var hi = dataMax != null ? dataMax : -5;
          if (integrated != null) {
            lo = Math.min(lo, integrated);
            hi = Math.max(hi, integrated);
          }
          lo = Math.min(lo, -23);
          hi = Math.max(hi, -23);
          return [Math.floor(lo - 3), Math.ceil(hi + 3)];
        },
      },
    },
    axes: [
      {
        label: i("chart.tl_time"),
        stroke: th.fg,
        grid: { stroke: th.gridStroke },
        ticks: { stroke: th.gridStroke },
      },
      {
        label: i("chart.tl_y_label"),
        stroke: th.fg,
        grid: { stroke: th.gridStroke },
        ticks: { stroke: th.gridStroke },
      },
    ],
    series,
  };

  const targetLine = new Float64Array(t.length).fill(-23);
  const data = [tMin, S, sSmooth];
  if (hasIntegrated) {
    data.push(new Float64Array(t.length).fill(integrated));
  }
  data.push(targetLine);

  return new uPlot(opts, data, container);
}
