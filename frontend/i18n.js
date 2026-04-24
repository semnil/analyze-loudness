// Two-language (en / ja) UI translation.  Default follows navigator.language
// ("ja*" -> ja, otherwise en); the user's choice is persisted in localStorage.
//
// Static markup uses data-i18n* attributes and is translated on DOMContentLoaded.
// Dynamic strings created in main.js call window.i18n.t(key) directly.
(function () {
  const STORAGE_KEY = "loudness-lang";

  const DICT = {
    en: {
      "app.title": "Loudness Analyzer (BS.1770 / EBU R128)",
      "form.aria": "Analyze audio source",
      "url.label": "YouTube URL",
      "url.placeholder": "YouTube URL",
      "btn.analyze": "Analyze",
      "btn.cancel": "Cancel",
      "btn.loading": "Loading",
      "btn.load_json": "\u{1F4C4} Load JSON",
      "btn.load_json.aria": "Load saved JSON result",
      "btn.cancel.aria": "Cancel analysis in progress",
      "btn.save_json": "Save JSON",
      "btn.save_image": "Save Image",
      "btn.copy": "Copy",
      "btn.copied": "Copied",
      "btn.copy_failed": "Copy failed",
      "status.starting": "Starting...",
      "status.opening_file": "Opening file...",
      "status.cancelled": "Cancelled.",
      "status.generating_image": "Generating image...",
      "status.saved": "Saved: ",
      "status.countdown": "({duration} {unit}, ~{remaining}s remaining)",
      "status.finishing_up": " (finishing up...)",
      "err.prefix": "Error: ",
      "err.no_result": "No result received from server",
      "err.charts_not_ready": "Charts are not ready. Run analysis first.",
      "err.save_failed": "Save failed: ",
      "err.load_failed_http": "Load failed: HTTP ",
      "err.dialog_timeout": "The file dialog did not respond. Please try again.",
      "err.save_failed_http": "Save failed: HTTP ",
      "summary.untitled": "Untitled",
      "summary.aria.loudness": "Loudness summary",
      "summary.aria.distribution": "Short-term / Momentary distribution",
      "summary.true_peak_na": "True peak measurement unavailable",
      "summary.frames": "frames",
      "summary.min": "min",
      "table.duration": "Duration",
      "table.integrated": "Integrated",
      "table.true_peak": "True Peak",
      "table.lra": "LRA",
      "table.sterm_median": "S-term Median",
      "table.sterm_p10p90": "S-term P10/P90",
      "table.mom_median": "Mom. Median",
      "table.mom_p10p90": "Mom. P10/P90",
      "table.silence": "Silence (S < -40 LUFS)",
      "chart.timeline_title": "Short-term Loudness (3s window)",
      "chart.histograms_heading": "Histograms",
      "chart.segments_heading": "Segments",
      "chart.hist_axis": "{label} Loudness (LUFS)",
      "chart.hist_title": "{label} Distribution",
      "chart.hist_integrated": "Integrated: {val}",
      "chart.hist_median": "Median: {val}",
      "chart.no_data_silence": "No data above silence threshold",
      "chart.seg_title": "5-Minute Segment Average (error bars: P10-P90)",
      "chart.seg_axis": "Time Segment (min)",
      "chart.tl_time": "Time (min)",
      "chart.tl_s_raw": "S raw",
      "chart.tl_avg": "60s avg",
      "chart.tl_integrated": "I: {val} LUFS",
      "chart.tl_target": "Target -23",
      "chart.tl_y_label": "Short-term LUFS",
      "chart.label_short_term": "Short-term",
      "chart.label_momentary": "Momentary",
      "aria.timeline": "Short-term loudness timeline over {mins} minutes. Integrated {integrated}. Short-term P10 {lo} LUFS, P90 {hi} LUFS.",
      "aria.histogram": "{kind} loudness histogram. Median {median} LUFS, P10 {p10}, P90 {p90}.",
      "aria.segments": "5-minute segment loudness bars relative to integrated {integrated}. LRA {lra} LU.",
      "theme.aria_toggle": "Toggle color theme",
      "theme.title.light": "Light (click: Dark)",
      "theme.title.dark": "Dark (click: Auto)",
      "theme.title.auto": "Auto (click: Light)",
      "theme.aria_state.light": "Theme: light. Click to switch.",
      "theme.aria_state.dark": "Theme: dark. Click to switch.",
      "theme.aria_state.auto": "Theme: auto. Click to switch.",
      "lang.aria_toggle": "Switch language",
      "lang.title.en": "Language: English (click: 日本語)",
      "lang.title.ja": "Language: 日本語 (click: English)",
      "lang.label.en": "EN",
      "lang.label.ja": "JA",
    },
    ja: {
      "app.title": "Loudness Analyzer (BS.1770 / EBU R128)",
      "form.aria": "音声ソースを分析",
      "url.label": "YouTube URL",
      "url.placeholder": "YouTube URL",
      "btn.analyze": "分析",
      "btn.cancel": "キャンセル",
      "btn.loading": "読込中",
      "btn.load_json": "\u{1F4C4} JSON を開く",
      "btn.load_json.aria": "保存済み JSON 結果を読み込む",
      "btn.cancel.aria": "分析をキャンセル",
      "btn.save_json": "JSON を保存",
      "btn.save_image": "画像を保存",
      "btn.copy": "コピー",
      "btn.copied": "コピー完了",
      "btn.copy_failed": "コピー失敗",
      "status.starting": "開始しています...",
      "status.opening_file": "ファイルを開いています...",
      "status.cancelled": "キャンセルされました。",
      "status.generating_image": "画像を生成しています...",
      "status.saved": "保存しました: ",
      "status.countdown": "({duration} {unit}, 残り約 {remaining} 秒)",
      "status.finishing_up": " (仕上げ中...)",
      "err.prefix": "エラー: ",
      "err.no_result": "サーバーから結果を受信できませんでした",
      "err.charts_not_ready": "チャートが未準備です。先に分析を実行してください。",
      "err.save_failed": "保存に失敗しました: ",
      "err.load_failed_http": "読込に失敗しました: HTTP ",
      "err.dialog_timeout": "ファイルダイアログが応答しませんでした。もう一度お試しください。",
      "err.save_failed_http": "保存に失敗しました: HTTP ",
      "summary.untitled": "無題",
      "summary.aria.loudness": "ラウドネス概要",
      "summary.aria.distribution": "Short-term / Momentary 分布",
      "summary.true_peak_na": "True Peak 測定値は利用できません",
      "summary.frames": "フレーム",
      "summary.min": "分",
      "table.duration": "長さ",
      "table.integrated": "Integrated",
      "table.true_peak": "True Peak",
      "table.lra": "LRA",
      "table.sterm_median": "S-term 中央値",
      "table.sterm_p10p90": "S-term P10/P90",
      "table.mom_median": "Mom. 中央値",
      "table.mom_p10p90": "Mom. P10/P90",
      "table.silence": "無音率 (S < -40 LUFS)",
      "chart.timeline_title": "Short-term Loudness (3s window)",
      "chart.histograms_heading": "Histograms",
      "chart.segments_heading": "Segments",
      "chart.hist_axis": "{label} Loudness (LUFS)",
      "chart.hist_title": "{label} Distribution",
      "chart.hist_integrated": "Integrated: {val}",
      "chart.hist_median": "Median: {val}",
      "chart.no_data_silence": "無音閾値を超えるデータがありません",
      "chart.seg_title": "5-Minute Segment Average (error bars: P10-P90)",
      "chart.seg_axis": "Time Segment (min)",
      "chart.tl_time": "Time (min)",
      "chart.tl_s_raw": "S raw",
      "chart.tl_avg": "60s avg",
      "chart.tl_integrated": "I: {val} LUFS",
      "chart.tl_target": "Target -23",
      "chart.tl_y_label": "Short-term LUFS",
      "chart.label_short_term": "Short-term",
      "chart.label_momentary": "Momentary",
      "aria.timeline": "Short-term loudness timeline over {mins} minutes. Integrated {integrated}. Short-term P10 {lo} LUFS, P90 {hi} LUFS.",
      "aria.histogram": "{kind} loudness histogram. Median {median} LUFS, P10 {p10}, P90 {p90}.",
      "aria.segments": "5-minute segment loudness bars relative to integrated {integrated}. LRA {lra} LU.",
      "theme.aria_toggle": "配色テーマを切り替え",
      "theme.title.light": "ライト (クリックでダーク)",
      "theme.title.dark": "ダーク (クリックで自動)",
      "theme.title.auto": "自動 (クリックでライト)",
      "theme.aria_state.light": "テーマ: ライト。クリックで切替。",
      "theme.aria_state.dark": "テーマ: ダーク。クリックで切替。",
      "theme.aria_state.auto": "テーマ: 自動。クリックで切替。",
      "lang.aria_toggle": "言語を切り替え",
      "lang.title.en": "Language: English (click: 日本語)",
      "lang.title.ja": "言語: 日本語 (クリックで English)",
      "lang.label.en": "EN",
      "lang.label.ja": "JA",
    },
  };

  function systemLang() {
    const l = (navigator.language || "en").toLowerCase();
    return l.startsWith("ja") ? "ja" : "en";
  }

  let current;
  try {
    const saved = localStorage.getItem(STORAGE_KEY);
    current = saved === "ja" || saved === "en" ? saved : systemLang();
  } catch (_) {
    current = systemLang();
  }

  function t(key, params) {
    const d = DICT[current] || DICT.en;
    let s;
    if (Object.prototype.hasOwnProperty.call(d, key)) s = d[key];
    else if (Object.prototype.hasOwnProperty.call(DICT.en, key)) s = DICT.en[key];
    else return key;
    if (params) {
      for (const k in params) {
        s = s.replace(new RegExp("\\{" + k + "\\}", "g"), params[k]);
      }
    }
    return s;
  }

  function applyStatic() {
    document.documentElement.setAttribute("lang", current);
    document.querySelectorAll("[data-i18n]").forEach((n) => {
      n.textContent = t(n.getAttribute("data-i18n"));
    });
    document.querySelectorAll("[data-i18n-title]").forEach((n) => {
      n.title = t(n.getAttribute("data-i18n-title"));
    });
    document.querySelectorAll("[data-i18n-placeholder]").forEach((n) => {
      n.placeholder = t(n.getAttribute("data-i18n-placeholder"));
    });
    document.querySelectorAll("[data-i18n-aria-label]").forEach((n) => {
      n.setAttribute("aria-label", t(n.getAttribute("data-i18n-aria-label")));
    });
    const titleEl = document.querySelector("title");
    if (titleEl && titleEl.getAttribute("data-i18n")) {
      titleEl.textContent = t(titleEl.getAttribute("data-i18n"));
    }
  }

  const listeners = [];

  window.i18n = {
    t: t,
    lang: function () { return current; },
    setLang: function (lang) {
      if (lang !== "ja" && lang !== "en") return;
      current = lang;
      try { localStorage.setItem(STORAGE_KEY, lang); } catch (_) {}
      applyStatic();
      listeners.forEach((fn) => { try { fn(lang); } catch (_) {} });
    },
    onChange: function (fn) { listeners.push(fn); },
    applyStatic: applyStatic,
  };

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", applyStatic);
  } else {
    applyStatic();
  }
})();
