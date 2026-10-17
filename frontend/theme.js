/** Shared theme helpers for chart rendering. */

function isDark() {
  return document.documentElement.getAttribute("data-theme") === "dark";
}

function getTheme() {
  const dark = isDark();
  return {
    dark,
    fg: dark ? "#e0e0e0" : "#333",
    fgMuted: dark ? "#aaa" : "#666",
    accent: dark ? "#CE93D8" : "#9C27B0",
    accentFill: dark ? "rgba(206,147,216,0.15)" : "rgba(156,39,176,0.08)",
    accentStroke: dark ? "rgba(206,147,216,0.4)" : "rgba(156,39,176,0.2)",
    barFill: dark ? "rgba(206,147,216,0.5)" : "rgba(156,39,176,0.6)",
    gridStroke: dark ? "rgba(255,255,255,0.1)" : "rgba(0,0,0,0.07)",
    surface: dark ? "#16213e" : "#fff",
    separator: dark ? "#4a3a5e" : "#E1BEE7",
    titleColor: dark ? "#E1BEE7" : "#4A148C",
    green: dark ? "#66BB6A" : "#4CAF50",
    // Gate lane: amber reads as "excluded" without colliding with the purple
    // accent (S raw / Integrated) or the green target line.
    gateTrack: dark ? "#232C4A" : "#E9EAEE",
    gateOut: dark ? "#E9A93C" : "#B26A00",
    gateSilent: dark ? "#C8D2E6" : "#33405A",
    // Comparison tracks in queue order.  The light set is mirrored by
    // TRACK_COLORS in src/analyze_loudness/plot.py.
    trackColors: dark
      ? ["#607D8B", "#FFF176", "#CC3311", "#CE93D8", "#8D6E63", "#7E57C2"]
      : ["#B71C1C", "#1A237E", "#CC79A7", "#7E57C2", "#006064", "#3E2723"],
  };
}
