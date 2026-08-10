/**
 * Short-term loudness timeline using uPlot.
 * Renders raw S data as a filled area and 60-frame moving average as a bold line.
 * When gate data is available a GATE lane sits in the x-axis gutter, directly
 * under the plot, marking the blocks that did not count toward Integrated.
 */

var TL_HEIGHT = 350;
var GATE_LANE_H = 12;      // lane height, CSS px
var GATE_LANE_TOP_GAP = 6; // plot bottom -> lane top
var GATE_LANE_BOT_GAP = 8; // lane bottom -> x-axis values
var GATE_LANE_LABEL_GAP = 6; // lane left edge -> "GATE" label

// uPlot axis defaults the lane has to make room in: values are drawn at
// plotBottom + ticks.size + gap, inside a gutter of a fixed `size` (the axis
// label gets its own labelSize on top).
var UPLOT_TICK_SIZE = 10;
var UPLOT_AXIS_GAP = 5;
var UPLOT_X_AXIS_SIZE = 50;

// Push the axis values below the lane, then widen the gutter and the chart by
// the same amount so the plot area keeps the height it has without a lane.
var _gateAxisGap = GATE_LANE_TOP_GAP + GATE_LANE_H + GATE_LANE_BOT_GAP - UPLOT_TICK_SIZE;
var _gateExtra = _gateAxisGap - UPLOT_AXIS_GAP;

/**
 * Draw the gate lane in the space reserved below the plot.  Each device pixel
 * column takes the highest state of the blocks that land in it, so a column
 * holding both counted and excluded blocks reads as excluded.
 */
function gateLanePlugin(gate) {
  return {
    hooks: {
      draw: function (u) {
        var ctx = u.ctx;
        var bb = u.bbox;
        // uPlot draws in device pixels; derive the ratio it actually used
        // rather than devicePixelRatio, which can drift from it.
        var r = u.ctx.canvas.width / u.width;
        var laneTop = bb.top + bb.height + GATE_LANE_TOP_GAP * r;
        var laneH = GATE_LANE_H * r;
        var w = Math.round(bb.width);
        if (w <= 0) return;

        var th = getTheme();
        ctx.save();

        ctx.fillStyle = th.gateTrack;
        ctx.fillRect(bb.left, laneTop, bb.width, laneH);

        var xs = u.data[0];
        var idxs = u.series[0].idxs || [0, xs.length - 1];
        var cols = new Uint8Array(w);
        for (var i = idxs[0]; i <= idxs[1]; i++) {
          var s = gate.state[i];
          if (s === GATE_COUNTED) continue;
          // A block spans up to the next sample; keep at least one column so
          // sub-pixel blocks stay visible at full-length zoom.
          var from = Math.floor(u.valToPos(xs[i], "x", true) - bb.left);
          var to = i + 1 < xs.length
            ? Math.ceil(u.valToPos(xs[i + 1], "x", true) - bb.left) - 1
            : from;
          if (to < from) to = from;
          if (from < 0) from = 0;
          if (to >= w) to = w - 1;
          for (var c = from; c <= to; c++) {
            if (s > cols[c]) cols[c] = s;
          }
        }

        var x = 0;
        while (x < w) {
          var v = cols[x];
          if (v === GATE_COUNTED) { x++; continue; }
          var start = x;
          while (x < w && cols[x] === v) x++;
          ctx.fillStyle = v === GATE_SILENT ? th.gateSilent : th.gateOut;
          ctx.fillRect(bb.left + start, laneTop, x - start, laneH);
        }

        ctx.fillStyle = th.fgMuted;
        ctx.font = (10 * r) + "px 'Segoe UI', 'Meiryo', sans-serif";
        ctx.textAlign = "right";
        ctx.textBaseline = "middle";
        ctx.fillText(window.i18n.t("gate.lane_label"),
                     bb.left - GATE_LANE_LABEL_GAP * r, laneTop + laneH / 2);

        ctx.restore();
      },
    },
  };
}

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

function renderTimeline(container, t, S, integrated, gate) {
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

  const laneOn = gate != null;
  const opts = {
    width: container.clientWidth,
    height: TL_HEIGHT + (laneOn ? _gateExtra : 0),
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
        gap: laneOn ? _gateAxisGap : UPLOT_AXIS_GAP,
        size: UPLOT_X_AXIS_SIZE + (laneOn ? _gateExtra : 0),
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
  if (laneOn) opts.plugins = [gateLanePlugin(gate)];

  const targetLine = new Float64Array(t.length).fill(-23);
  const data = [tMin, S, sSmooth];
  if (hasIntegrated) {
    data.push(new Float64Array(t.length).fill(integrated));
  }
  data.push(targetLine);

  return new uPlot(opts, data, container);
}
