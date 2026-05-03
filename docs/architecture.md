# Architecture Design Document

## Overview

analyze-loudness は YouTube 動画の音声ラウドネスを BS.1770 / EBU R128 準拠で分析するツール。
CLI ツールとしてローカル実行可能であり、Windows GUI アプリケーション (pywebview) としても提供する。

## System Architecture

```mermaid
graph LR
    A["pywebview<br/>(WebView2)"] -->|"HTTP<br/>127.0.0.1:random"| B["Local HTTP Server<br/>(gui.py)"]
    B -->|"POST /analyze<br/>NDJSON stream"| C["Analysis Pipeline"]
    C --> D["yt_dlp.YoutubeDL API<br/>(audio download)"]
    C --> E["ffmpeg<br/>(ebur128 analysis)"]
    E --> F["stderr parse"]
    F --> G["JSON result"]
    G --> A
```

## Components

### CLI Tool (`src/analyze_loudness/`)

| Module | Responsibility |
|--------|---------------|
| `cli.py` | argparse + orchestration, static-ffmpeg PATH setup |
| `download.py` | `yt_dlp.YoutubeDL` Python API でダウンロード + タイトル取得, ffprobe duration, filename sanitization |
| `analysis.py` | ffmpeg ebur128 stderr parsing, numpy-based statistics |
| `plot.py` | matplotlib 4-row figure generation (timeline, histograms, segments) |

### GUI Application (`src/analyze_loudness/gui.py`)

| Component | Responsibility |
|-----------|---------------|
| `AnalyzeHandler` | `SimpleHTTPRequestHandler` 継承。frontend 配信 + POST エンドポイント処理 |
| `do_POST()` | `/analyze`, `/save`, `/save-image`, `/load` のルーティング |
| `_run_analysis()` | download -> probe -> ebur128 (計時) -> stats -> result の NDJSON ストリーム |
| `_handle_save()` | JSON 保存 (ネイティブファイルダイアログ) |
| `_handle_save_image()` | base64 PNG → バイナリ保存 (ネイティブファイルダイアログ) |
| `_handle_load()` | JSON 読み込み + バリデーション (ネイティブファイルダイアログ) |
| `_speed_factor` | runtime-calibrated 速度係数。分析時間から次回の推定時間を算出 |
| `_set_application_user_model_id()` | Windows AppUserModelID 設定 (タスクバーアイコン反映) |
| `main()` | HTTPServer (127.0.0.1:0) 起動 + pywebview ウインドウ表示 |

### Frontend (`frontend/`)

| File | Responsibility |
|------|---------------|
| `index.html` | SPA entry point, local vendor files |
| `main.js` | Fetch orchestration, NDJSON progress parsing, DOM rendering, save/load/image capture, theme toggle, language toggle, cancel (AbortController), `_addTip` ツールチップ |
| `theme.js` | `isDark()`, `getTheme()` — theme detection + chart color provider |
| `i18n.js` | en / ja DICT + `window.i18n.t / setLang / onChange / applyStatic` |
| `charts/timeline.js` | uPlot time series (60-frame moving average, theme-aware) |
| `charts/histogram.js` | Canvas density histogram (theme-aware, タイトルは HTML 側) |
| `charts/segments.js` | Canvas 5-min segment bar chart (theme-aware, タイトルは HTML 側) |
| `style.css` | CSS variables + `[data-theme="dark"]` rules, purple accent (#9C27B0) |
| `vendor/` | uPlot.iife.min.js, uPlot.min.css (bundled) |

### Shared Utilities (`src/analyze_loudness/__init__.py`)

| Function | Responsibility |
|----------|---------------|
| `_subprocess_kwargs()` | Windows frozen mode で subprocess のコンソールウインドウを非表示にする |

## Data Flow

### CLI

```mermaid
graph LR
    A["URL"] --> B["yt_dlp.YoutubeDL<br/>(opus extract)"]
    B --> C["ffprobe<br/>duration"]
    C --> D["ffmpeg -af ebur128<br/>(stderr parse)"]
    D --> E["compute_stats<br/>(numpy)"]
    E --> F["console output +<br/>matplotlib PNG"]
```

### GUI

```mermaid
graph TD
    A["POST /analyze<br/>{url, duration?}"] --> B["download_audio()<br/>yt_dlp.YoutubeDL"]
    B --> C["probe_duration()<br/>ffprobe"]
    C --> D{"duration<br/>specified?"}
    D -->|Yes| E["compute_middle()"]
    D -->|No| F["run_ebur128()<br/>ffmpeg -af ebur128"]
    E --> F
    F -->|"time.monotonic()"| G["_speed_factor update"]
    G --> H["compute_stats()<br/>numpy"]
    H --> I["NDJSON result event<br/>(meta + summary + series)"]
    I --> J["Browser rendering<br/>uPlot + Canvas"]
    J --> K["Save JSON / Save Image / Load JSON"]
```

### NDJSON Progress Stream

GUI の `/analyze` エンドポイントは `application/x-ndjson` でストリーミング応答する:

```
{"type":"progress","stage":"download","message":"Downloading audio..."}
{"type":"progress","stage":"download","message":"Downloaded: Video Title"}
{"type":"progress","stage":"analyze","message":"Running EBU R128 analysis...","estimate_sec":12,"duration_sec":600}
{"type":"progress","stage":"stats","message":"Computing statistics..."}
{"type":"result","data":{...}}
```

入力 validation 失敗 (URL/duration の型/範囲不正) は HTTP 400 + JSON で返す。
それ以降のダウンロード・解析フェーズで発生したエラーは **HTTP 200 + NDJSON `{"type":"error","error":"..."}`** として返る。
応答ヘッダ送信後に HTTP ステータスを変更できないための設計上の契約であり、クライアントは HTTP ステータスだけでなく NDJSON の `type` フィールドで成否を判定する。
`Content-Length` / `Transfer-Encoding: chunked` は付与せず、フレーム境界は `Connection: close` で確定させる。

## Key Design Decisions

### 1. ebur128 stderr parsing (not WAV decoding)

ffmpeg の ebur128 フィルタは stderr にフレーム毎のラウドネス値を出力する。
50分の音声を WAV デコードすると 4GB 超のメモリが必要になるため、
stderr テキストのみを処理し、メモリ消費を数MB に抑えている。

### 2. Local HTTP server + pywebview

pywebview は OS のネイティブ WebView (Windows: WebView2) を使用し、
バンドルサイズを小さく保てる。
`HTTPServer` を 127.0.0.1 のランダムポート (port 0) で起動し、
same-origin で frontend を配信する。

### 3. Runtime-calibrated time estimation

`_speed_factor` を分析の実測時間から更新し、次回以降の推定精度を向上。
初期値は 55.0 (実時間の約 55 倍速) で、各分析完了後に `analyze_sec / elapsed` で更新。

### 4. yt-dlp Python API (not bundled binary)

`yt_dlp.YoutubeDL` クラスを Python ライブラリとして直接呼び出し、`FFmpegExtractAudio` postprocessor で opus 抽出。`extract_info(download=True)` の戻り値にタイトルが含まれるため、並行実行が不要。

バイナリ同梱 (`yt-dlp_macos` など) を避けることで、macOS 向けの codesign 再署名時に発生する Team ID 不一致問題 (onefile バイナリ内部の Python.framework が再署名できず hardened runtime で拒否される) を根本的に回避している。Windows / Linux でも同方式で統一。

### 5. Middle extraction

長時間動画は中盤のみを分析する。`ffmpeg -ss <start> -t <duration>` で
ebur128 分析時に直接切り出し。

CLI のみが `--duration` オプションでこの機能を公開する。GUI にはこれに相当する入力 UI を実装しない (常に全尺を分析)。GUI は URL のみを受け取るシンプルなワークフローを優先し、部分抽出が必要な用途は CLI に委ねる方針。

### 6. Conditional static-ffmpeg (CLI only)

CLI ではシステムに ffmpeg がインストールされていれば `static-ffmpeg` を使わない。
`shutil.which("ffmpeg")` で検出し、不在時のみ `static_ffmpeg.add_paths()` を呼ぶ。

### 7. uPlot ダークモードと CSS `!important`

uPlot は凡例・タイトルの `color` をインラインスタイルで設定するため、CSS から上書くには
`!important` が必要。JS で DOM を直接操作する方法もあるが、テーマ切替のたびに uPlot 内部 DOM を
走査する必要があり、バージョンアップ時の破綻リスクは CSS `!important` と同等かそれ以上。
uPlot のインラインスタイル上書きは `!important` の正当なユースケースであり、現状維持とする。

### 8. Dark mode (light / dark / auto)

CSS 変数 (`--bg`, `--fg`, `--accent` 等) + `[data-theme="dark"]` でテーマを切り替え。
`theme.js` の `getTheme()` がチャート描画時のカラーパレットを返す。
fixed top-right pill ボタン (☾/☀/◐) で light → dark → auto をサイクル。
`auto` は OS の `prefers-color-scheme` に追従し、`matchMedia` の `change` イベントでリアルタイム反映。
選択は `localStorage("loudness-theme")` に永続化。UI は analyze-spectrum プロジェクトと統一。

### 9. Analysis cancel (AbortController)

分析中に Analyze ボタンが Cancel に変化 (赤色)。`AbortController.signal` を `fetch()` と
NDJSON `ReadableStream.getReader()` に渡し、キャンセル時にストリーム読み取りを中断。
`_isBusy` フラグで Load ボタンを無効化し、二重実行を防止。

### 10. Windows subprocess console hiding

PyInstaller frozen mode では `subprocess.STARTUPINFO` + `STARTF_USESHOWWINDOW` で
ffmpeg / ffprobe のコンソールウインドウを非表示にする。yt-dlp は Python API として動作するため subprocess 起動しない。

## Accessibility (prefers-reduced-motion)

`@media (prefers-reduced-motion: reduce)` で CSS animation / transition を一括無効化している。

チャート描画 (uPlot, Canvas histogram, Canvas segments) についてはアニメーション処理を持たず、
全て即時描画のため個別対応は不要。uPlot のカーソル追従はユーザー操作に対するリアルタイム応答であり、
WCAG 2.3.3 が対象とするアニメーションには該当しない。

カウントダウン表示は `matchMedia("(prefers-reduced-motion: reduce)")` で更新間隔を
1 秒 → 5 秒に変更済み (main.js)。

## Build & Distribution

### CLI

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
analyze-loudness "https://www.youtube.com/watch?v=XXXXX"
```

### GUI (PyInstaller + Inno Setup)

```bash
python build.py              # download assets + PyInstaller bundle
python build.py --installer  # + Inno Setup installer
```

Build pipeline:
1. `build.py --skip-download` or auto-download: ffmpeg, ffprobe, deno, uPlot (yt-dlp は Python 依存)
2. PyInstaller (`analyze-loudness.spec`): bundles Python + dependencies + frontend + binaries
3. Inno Setup (`installer.iss`): Windows installer with license display

### Bundled Assets (`build_assets/bin/`)

| Binary | Source | License |
|--------|--------|---------|
| deno.exe | GitHub Releases (latest) | MIT |
| ffmpeg.exe | BtbN/FFmpeg-Builds (latest) | GPL-2.0+ |
| ffprobe.exe | BtbN/FFmpeg-Builds (latest) | GPL-2.0+ |

## Constants

| Constant | Value | Location | Description |
|----------|-------|----------|-------------|
| SILENCE_THRESHOLD | -60 LUFS | analysis.py | Stats exclude frames <= this |
| _speed_factor | 55.0 (initial) | gui.py | Runtime-calibrated analysis speed |
| Segment size | 5 min | plot.py, segments.js | Bar chart segment width |
| Moving average window | 60 frames | plot.py, timeline.js | Timeline smoothing window |
| Downsample target | ~3000 points | plot.py | Plot responsiveness |
| Default theme | "auto" | main.js | OS prefers-color-scheme 追従 |
| Theme storage key | "loudness-theme" | main.js | localStorage persistence key |
| Language storage key | "loudness-lang" | i18n.js | localStorage persistence key (en/ja) |
