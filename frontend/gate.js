/**
 * EBU R128 gating applied to the Momentary series.
 *
 * BS.1770 counts a 400 ms block toward Integrated only when it clears the
 * absolute gate (-70 LUFS) and the relative gate (mean loudness of the
 * absolute-gated blocks, minus 10 LU).  Schema 2 results carry ffmpeg's own
 * relative gate as summary.gate_threshold; schema 1 results do not, so it is
 * recomputed from series.M -- which reproduces ffmpeg's Integrated within
 * 0.05 LU on every saved result.
 */

var GATE_ABSOLUTE = -70;
var GATE_RELATIVE_OFFSET = -10;
// BS.1770 momentary window.  ffmpeg emits a frame every 100 ms, so the frames
// before the first complete window carry its silence floor (-120.7) with no
// measurement behind them.  They are not gating blocks: counting them as
// silence inflates both the silence share and the denominator -- on a 36 s
// clip the three of them are the entire reported silence.
var GATE_BLOCK_SEC = 0.4;

// Per-block gate state, also used as the drawing priority (higher wins when
// several blocks land in the same pixel column).
var GATE_COUNTED = 0;
var GATE_BELOW = 1;
var GATE_SILENT = 2;

/** Index of the first frame with a complete momentary window behind it. */
function _firstGatedIndex(t) {
  if (!t || t.length === 0) return 0;
  // Half a frame of tolerance: ffmpeg's t is 0.399977 for the 400 ms mark, and
  // the saved series rounds it to 0.4.
  var frame = t.length > 1 ? t[1] - t[0] : 0;
  var full = t[0] + GATE_BLOCK_SEC - frame * 1.5;
  var i = 0;
  while (i < t.length && t[i] < full) i++;
  return i;
}

/** Mean loudness of the absolute-gated blocks, minus 10 LU. */
function _relativeGate(M, start) {
  var sum = 0, n = 0;
  for (var i = start; i < M.length; i++) {
    var v = M[i];
    if (v == null || !isFinite(v) || v <= GATE_ABSOLUTE) continue;
    sum += Math.pow(10, v / 10);
    n++;
  }
  return n === 0 ? null : 10 * Math.log10(sum / n) + GATE_RELATIVE_OFFSET;
}

/**
 * @param M         Momentary series (LUFS per 400 ms block).
 * @param t         Frame times, used to skip ffmpeg's warm-up frames.
 * @param threshold summary.gate_threshold when the result carries one;
 *                  anything else falls back to recomputing it from M.
 */
function computeGate(M, t, threshold) {
  if (!M || M.length === 0) return null;

  var start = _firstGatedIndex(t);
  if (start >= M.length) return null;

  var thr = (typeof threshold === "number" && isFinite(threshold))
    ? threshold : _relativeGate(M, start);
  if (thr === null) return null;

  // Indexed like the series so the lane can address it directly.  The warm-up
  // frames keep GATE_COUNTED, which draws nothing: there is no gating decision
  // to show, and it has to stay the lowest value so it can never outrank a real
  // state in a pixel column they share.
  var state = new Uint8Array(M.length);
  var counted = 0, silent = 0;
  for (var j = start; j < M.length; j++) {
    var m = M[j];
    if (m == null || !isFinite(m) || m <= GATE_ABSOLUTE) {
      state[j] = GATE_SILENT;
      silent++;
    } else if (m <= thr) {
      state[j] = GATE_BELOW;
    } else {
      state[j] = GATE_COUNTED;
      counted++;
    }
  }

  var total = M.length - start;
  // No block clears the absolute gate: there is no Integrated to explain.
  if (silent === total) return null;

  return {
    threshold: thr,
    state: state,
    total: total,
    counted: counted,
    silent: silent,
    below: total - counted - silent,
    countedPct: counted / total * 100,
    silentPct: silent / total * 100,
    belowPct: (total - counted - silent) / total * 100,
  };
}
