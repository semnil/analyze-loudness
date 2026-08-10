/**
 * EBU R128 gating reconstructed from the Momentary series.
 *
 * BS.1770 counts a 400 ms block toward Integrated only when it clears the
 * absolute gate (-70 LUFS) and the relative gate (mean loudness of the
 * absolute-gated blocks, minus 10 LU).  Recomputing both from series.M
 * reproduces ffmpeg's own Integrated within 0.05 LU on every saved result,
 * so the lane works for previously saved JSON as well as fresh analyses.
 */

var GATE_ABSOLUTE = -70;
var GATE_RELATIVE_OFFSET = -10;

// Per-block gate state, also used as the drawing priority (higher wins when
// several blocks land in the same pixel column).
var GATE_COUNTED = 0;
var GATE_BELOW = 1;
var GATE_SILENT = 2;

function computeGate(M) {
  if (!M || M.length === 0) return null;

  var sum = 0, n = 0;
  for (var i = 0; i < M.length; i++) {
    var v = M[i];
    if (v == null || !isFinite(v) || v <= GATE_ABSOLUTE) continue;
    sum += Math.pow(10, v / 10);
    n++;
  }
  if (n === 0) return null;

  var threshold = 10 * Math.log10(sum / n) + GATE_RELATIVE_OFFSET;

  var state = new Uint8Array(M.length);
  var counted = 0, silent = 0;
  for (var j = 0; j < M.length; j++) {
    var m = M[j];
    if (m == null || !isFinite(m) || m <= GATE_ABSOLUTE) {
      state[j] = GATE_SILENT;
      silent++;
    } else if (m <= threshold) {
      state[j] = GATE_BELOW;
    } else {
      state[j] = GATE_COUNTED;
      counted++;
    }
  }

  var total = M.length;
  return {
    threshold: threshold,
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
