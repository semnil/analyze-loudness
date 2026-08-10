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

// Per-block gate state, also used as the drawing priority (higher wins when
// several blocks land in the same pixel column).
var GATE_COUNTED = 0;
var GATE_BELOW = 1;
var GATE_SILENT = 2;

/** Mean loudness of the absolute-gated blocks, minus 10 LU. */
function _relativeGate(M) {
  var sum = 0, n = 0;
  for (var i = 0; i < M.length; i++) {
    var v = M[i];
    if (v == null || !isFinite(v) || v <= GATE_ABSOLUTE) continue;
    sum += Math.pow(10, v / 10);
    n++;
  }
  return n === 0 ? null : 10 * Math.log10(sum / n) + GATE_RELATIVE_OFFSET;
}

/**
 * @param M         Momentary series (LUFS per 400 ms block).
 * @param threshold summary.gate_threshold when the result carries one;
 *                  anything else falls back to recomputing it from M.
 */
function computeGate(M, threshold) {
  if (!M || M.length === 0) return null;

  var thr = (typeof threshold === "number" && isFinite(threshold))
    ? threshold : _relativeGate(M);
  if (thr === null) return null;

  var state = new Uint8Array(M.length);
  var counted = 0, silent = 0;
  for (var j = 0; j < M.length; j++) {
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
  // No block clears the absolute gate: there is no Integrated to explain.
  if (silent === M.length) return null;

  var total = M.length;
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
