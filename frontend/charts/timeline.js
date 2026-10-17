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
var GATE_LANE_STACK_GAP = 3; // between stacked lanes (comparison)

// uPlot axis defaults the lane has to make room in: values are drawn at
// plotBottom + ticks.size + gap, inside a gutter of a fixed `size` (the axis
// label gets its own labelSize on top).
var UPLOT_TICK_SIZE = 10;
var UPLOT_AXIS_GAP = 5;
var UPLOT_X_AXIS_SIZE = 50;

// Push the axis values below the lane, then widen the gutter and the chart by
// the same amount so the plot area keeps the height it has without a lane.
function _gateAxisGapFor(lanes) {
  return GATE_LANE_TOP_GAP + lanes * GATE_LANE_H + (lanes - 1) * GATE_LANE_STACK_GAP +
    GATE_LANE_BOT_GAP - UPLOT_TICK_SIZE;
}
function _gateExtraFor(lanes) { return _gateAxisGapFor(lanes) - UPLOT_AXIS_GAP; }
var _gateAxisGap = _gateAxisGapFor(1);
var _gateExtra = _gateExtraFor(1);

/**
 * Draw gate lanes in the space reserved below the plot, one per entry of
 * `lanes` ({gate, label}), stacked top-down.  Each device pixel column takes
 * the highest state of the blocks that land in it, so a column holding both
 * counted and excluded blocks reads as excluded.  A lane whose gate is null
 * shows only its track.
 */
function gateLanePlugin(lanes) {
  return {
    hooks: {
      draw: function (u) {
        var ctx = u.ctx;
        var bb = u.bbox;
        // uPlot draws in device pixels; derive the ratio it actually used
        // rather than devicePixelRatio, which can drift from it.
        var r = u.ctx.canvas.width / u.width;
        var laneH = GATE_LANE_H * r;
        var w = Math.round(bb.width);
        if (w <= 0) return;

        var th = getTheme();
        var xs = u.data[0];
        var idxs = u.series[0].idxs || [0, xs.length - 1];
        ctx.save();
        ctx.font = (10 * r) + "px 'Segoe UI', 'Meiryo', sans-serif";
        ctx.textAlign = "right";
        ctx.textBaseline = "middle";

        for (var k = 0; k < lanes.length; k++) {
          var gate = lanes[k].gate;
          var laneTop = bb.top + bb.height +
            (GATE_LANE_TOP_GAP + k * (GATE_LANE_H + GATE_LANE_STACK_GAP)) * r;

          ctx.fillStyle = th.gateTrack;
          ctx.fillRect(bb.left, laneTop, bb.width, laneH);

          if (gate) {
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
          }

          ctx.fillStyle = th.fgMuted;
          ctx.fillText(lanes[k].label, bb.left - GATE_LANE_LABEL_GAP * r, laneTop + laneH / 2);
        }

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
  if (laneOn) opts.plugins = [gateLanePlugin([{ gate: gate, label: i("gate.lane_label") }])];

  const targetLine = new Float64Array(t.length).fill(-23);
  const data = [tMin, S, sSmooth];
  if (hasIntegrated) {
    data.push(new Float64Array(t.length).fill(integrated));
  }
  data.push(targetLine);

  return new uPlot(opts, data, container);
}

// Room right of the plot for the track numbers at each line's end.
var CMP_END_LABEL_PAD = 22;

/** Track number at the last drawn point of each line, in the line's colour. */
function trackEndLabelPlugin(tracks) {
  return {
    hooks: {
      draw: function (u) {
        var ctx = u.ctx;
        var r = u.ctx.canvas.width / u.width;
        var idxs = u.series[0].idxs || [0, u.data[0].length - 1];
        ctx.save();
        ctx.font = "bold " + (12 * r) + "px 'Segoe UI', 'Meiryo', sans-serif";
        ctx.textAlign = "left";
        ctx.textBaseline = "middle";
        for (var k = 0; k < tracks.length; k++) {
          var ys = u.data[k + 1];
          var j = idxs[1];
          while (j >= idxs[0] && (ys[j] == null || !isFinite(ys[j]))) j--;
          if (j < idxs[0]) continue;
          var x = u.valToPos(u.data[0][j], "x", true);
          var y = u.valToPos(ys[j], "y", true);
          ctx.fillStyle = tracks[k].color;
          ctx.fillText(String(tracks[k].n), x + 4 * r, y);
        }
        ctx.restore();
      },
    },
  };
}

/**
 * Comparison timeline: one 60 s moving-average Short-term line per track on a
 * shared time axis, the -23 LUFS target, and one gate lane per track.
 * @param tracks [{n, S, gate, color}] -- all S arrays share `t`.
 */
function renderCompareTimeline(container, t, tracks) {
  const tMin = t.map(v => v / 60);
  const th = getTheme();
  const i = window.i18n.t.bind(window.i18n);

  const series = [{ label: i("chart.tl_time") }];
  const data = [tMin];
  for (const tr of tracks) {
    series.push({ label: i("chart.cmp_track", { n: tr.n }), stroke: tr.color, width: 2 });
    data.push(movingAvg(tr.S, 60));
  }
  series.push({
    label: i("chart.tl_target"),
    stroke: th.green,
    width: 1,
    dash: [10, 5],
    value: () => "-23.0",
  });
  data.push(new Float64Array(t.length).fill(-23));

  const laneOn = tracks.some(tr => tr.gate != null);
  const lanes = tracks.length;
  const opts = {
    width: container.clientWidth,
    height: TL_HEIGHT + (laneOn ? _gateExtraFor(lanes) : 0),
    padding: [null, CMP_END_LABEL_PAD, null, null],
    scales: {
      x: { time: false },
      y: {
        range: (self, dataMin, dataMax) => {
          var lo = dataMin != null ? Math.max(dataMin, -70) : -55;
          var hi = dataMax != null ? dataMax : -5;
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
        gap: laneOn ? _gateAxisGapFor(lanes) : UPLOT_AXIS_GAP,
        size: UPLOT_X_AXIS_SIZE + (laneOn ? _gateExtraFor(lanes) : 0),
      },
      {
        label: i("chart.tl_y_label"),
        stroke: th.fg,
        grid: { stroke: th.gridStroke },
        ticks: { stroke: th.gridStroke },
      },
    ],
    series,
    plugins: [trackEndLabelPlugin(tracks)],
  };
  if (laneOn) {
    opts.plugins.push(gateLanePlugin(tracks.map(tr => ({
      gate: tr.gate, label: i("gate.lane_label_n", { n: tr.n }),
    }))));
  }
  return new uPlot(opts, data, container);
}
