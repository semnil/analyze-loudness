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
      "tip.duration": "Length of the analyzed audio. The 'frames' count is the number of 100 ms ebur128 frames produced by the measurement.",
      "tip.integrated": "Integrated loudness (LUFS) per ITU-R BS.1770 / EBU R128. Energy-weighted average loudness over the whole programme. Broadcast targets: -23 LUFS (EBU R128), -24 LUFS (ATSC A/85), -14 LUFS (streaming).",
      "tip.true_peak": "ITU-R BS.1770 True Peak (dBTP / dBFS). Detects inter-sample peaks via 4x oversampling. Values above 0 dBTP risk clipping on DA conversion or lossy re-encoding. N/A when no peak measurement is available.",
      "tip.lra": "Loudness Range (LU) per EBU Tech 3342. Statistical loudness span (P10-P95 of gated short-term frames). Larger = wider macro-dynamics. Music typically 6-12 LU; heavily compressed broadcast around 4-6 LU.",
      "tip.sterm_median": "Median of short-term loudness (3 s window) across the gated frames. A robust centre-of-distribution that is less sensitive to outliers than the mean.",
      "tip.sterm_p10p90": "10th and 90th percentile of the short-term (3 s) loudness distribution. The lower 10% / upper 10% boundary; the gap is a quick read on dynamic spread.",
      "tip.mom_median": "Median of momentary loudness (400 ms window). Captures shorter-term fluctuations than short-term and reflects the most recent perceived loudness.",
      "tip.mom_p10p90": "10th and 90th percentile of the momentary (400 ms) loudness distribution. Wider than the short-term P10/P90 because brief peaks and dips are not smoothed out.",
      "tip.silence": "Percentage of frames where short-term loudness falls below -40 LUFS. Approximate measure of silent or near-silent passages (gaps, fades, breaks).",
      "tip.chart_timeline": "Short-term loudness (3 s window) plotted over time. Overlays: raw S series, 60 s moving average, integrated loudness line, and the -23 LUFS broadcast target reference.",
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
      "tip.duration": "分析対象音声の長さ。frames は ebur128 が出力する 100 ms 単位のフレーム数。",
      "tip.integrated": "ITU-R BS.1770 / EBU R128 準拠の積分ラウドネス (LUFS)。番組全体のエネルギー重み付き平均ラウドネス。放送基準: EBU R128 = -23 LUFS、ATSC A/85 = -24 LUFS、ストリーミング = -14 LUFS 付近。",
      "tip.true_peak": "ITU-R BS.1770 準拠の True Peak (dBTP / dBFS)。4 倍オーバーサンプリングでサンプル間ピークを検出。0 dBTP を超えると DA 変換や非可逆再エンコード時にクリップが発生し得る。N/A は測定不可の場合。",
      "tip.lra": "EBU Tech 3342 準拠の Loudness Range (LU)。ゲート済み Short-term フレームの P10-P95 範囲で表すラウドネスの統計的な広がり。値が大きいほどマクロダイナミクスが広い。音楽は概ね 6-12 LU、強く圧縮された放送は 4-6 LU 付近。",
      "tip.sterm_median": "Short-term ラウドネス (3 秒窓) の中央値。外れ値の影響を受けにくい分布の代表値。",
      "tip.sterm_p10p90": "Short-term (3 秒窓) ラウドネス分布の 10 / 90 パーセンタイル。下位 10 % / 上位 10 % の境界で、両者の差はダイナミクスの広がりの目安となる。",
      "tip.mom_median": "Momentary ラウドネス (400 ms 窓) の中央値。Short-term より短期間の変動を捉え、より瞬間的な聴感ラウドネスを反映する。",
      "tip.mom_p10p90": "Momentary (400 ms 窓) ラウドネス分布の 10 / 90 パーセンタイル。短い窓のため平滑化が弱く、Short-term の P10/P90 より広めの値になりやすい。",
      "tip.silence": "Short-term ラウドネスが -40 LUFS を下回るフレームの割合。無音または準無音区間 (間・フェード・休止) の概算指標。",
      "tip.chart_timeline": "Short-term ラウドネス (3 秒窓) の時系列推移。S raw、60 秒移動平均、Integrated ライン、-23 LUFS の放送基準ターゲットを重ねて表示する。",
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
