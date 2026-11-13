# Architecture

> 日本語版は [architecture.ja.md](architecture.ja.md) を参照してください.

## Overview

analyze-loudness analyzes the audio loudness of YouTube videos and local audio files in compliance with ITU-R BS.1770 (the International Telecommunication Union's loudness measurement recommendation, BS.1770 below) and EBU R128 (the European Broadcasting Union's loudness recommendation).
It can run locally as a command-line interface (CLI) tool, and is also provided as a Windows / macOS graphical user interface (GUI) application (pywebview).

The GUI's page talks to a local Hypertext Transfer Protocol (HTTP) server, which streams its progress and result as newline-delimited JavaScript Object Notation (JSON) lines (NDJSON). The audio of a Uniform Resource Locator (URL) comes from yt-dlp's Python application programming interface (API).

```mermaid
graph LR
    A["pywebview<br>(WebView2 / WebKit)"] -->|"HTTP<br>127.0.0.1:random"| B["Local HTTP server<br>(src/analyze_loudness/gui.py)"]
    B -->|"POST /analyze<br>NDJSON stream"| C["Analysis pipeline"]
    C --> D["yt_dlp.YoutubeDL API<br>(audio download)"]
    C --> E["ffmpeg<br>(ebur128 analysis)"]
    E --> F["stderr parse"]
    F --> G["JSON result"]
    G --> A
```

## Modules

### CLI tool (`src/analyze_loudness/`)

| Module | Responsibility |
|--------|---------------|
| `src/analyze_loudness/cli.py` | argparse + orchestration, static-ffmpeg PATH setup |
| `src/analyze_loudness/download.py` | Resolving a source (`resolve_source`: `download_audio()` for a URL, the path as is for a local file), refusing network paths (`is_network_path`), the extensions the GUI accepts (`AUDIO_EXTENSIONS`), ffprobe duration (`probe_duration`). Re-exports `download_audio()` (download + title retrieval with the `yt_dlp.YoutubeDL` Python API), `compute_middle()`, `is_url()` and `sanitize_filename()` from `vendor/py-analyze-common/src/analyze_common/download.py` |
| `src/analyze_loudness/analysis.py` | ffmpeg ebur128 stderr parsing, numpy-based statistics |
| `src/analyze_loudness/plot.py` | matplotlib 4-row figure generation (summary table, timeline, histograms, segments); comparison figure (`plot_compare`) |
| `src/analyze_loudness/compare.py` | Building (`build_result`) and validating (`validate_single`) single-result JSON, building (`build_compare`) and validating (`validate_compare`) comparison JSON, statistics over the truncated range (`truncated_stats`) |

### GUI application (`src/analyze_loudness/gui.py`)

| Component | Responsibility |
|-----------|---------------|
| `AnalyzeHandler` | Extends py-analyze-common's `GuiHandler` (`vendor/py-analyze-common/src/analyze_common/server.py`), which serves the frontend and the `/common/*` files, checks the Host and the Content-Type, and handles `/browse`, `/save-image`, `/settings` and `/update/*`. Gives it this app's state (`updater()`, `ui_settings()`, `window()`, `dialog_lock()`, `exit_for_update()`) |
| `do_POST()` | Routing of `/analyze`, `/compare`, `/save`, `/load`, `/upload` and `GuiHandler`'s endpoints (`_shared_handlers()`). Host check (`_check_host`) and Content-Type check (`_check_content_type`) |
| `_handle_upload()` | Saves a dropped file to the temporary directory `_upload_dir` |
| `_run_analysis()` | NDJSON stream of the cached result when there is one, otherwise of download, probe, ebur128 (timed), stats and result |
| `_handle_save()` | JSON save (native file dialog) |
| `_handle_compare()` | Receives 2-6 single results and returns the comparison JSON and the statistics over the truncated range |
| `_handle_load()` | JSON loading + validation (native file dialog). Returns comparison JSON with the statistics attached, and does not put it in the cache |
| `_exit_now()` | Exit after a macOS update has swapped the bundle. Runs the atexit cleanup, then `os._exit(0)` |
| `_speed_factor` | Runtime-calibrated speed factor. Computes the next estimated time from the analysis time |
| `main()` | Sets the Windows AppUserModelID (`set_app_user_model_id`, reflected in the taskbar icon) + holds the Windows mutex (`hold_instance_mutex`) + starts the `_HTTPServer` (a `ThreadingHTTPServer`, 127.0.0.1:0) + shows the pywebview window |
| `UPDATE_CONFIG` (`src/analyze_loudness/update.py`) | This app's identity for auto-update: product name, repository, public key, temporary directory prefix, mutex name |

### Frontend (`frontend/`)

| File | Responsibility |
|------|---------------|
| `frontend/index.html` | Single-page application (SPA) entry point, local vendor files |
| `frontend/main.js` | Fetch orchestration, NDJSON progress parsing, Document Object Model (DOM) rendering, save/load/image capture, theme toggle, language toggle, cancel (AbortController), attaching tooltips with `_addTip`, the comparison queue (`compareQueue`) and comparison display (`renderCompare`) |
| `frontend/theme.js` | `isDark()`, `getTheme()`: theme detection + chart color provider (includes the 6 comparison track colors `trackColors`) |
| `frontend/i18n.js` | en / ja DICT, which py-analyze-common's `/common/i18n.js` turns into `window.i18n.t / setLang / onChange / applyStatic`. `/common/boot.js` then sets the theme and the language on `<html>` before the Cascading Style Sheets (CSS) paint, and `/common/ui.js` (icons, the theme toggle's drawing, the queue's rows, the result title row, tooltips, button widths, the drop overlay's text, the error line) loads before `frontend/main.js` |
| `frontend/gate.js` | `computeGate()`: rebuilds the BS.1770 absolute / relative gates from `series.M` |
| `frontend/charts/timeline.js` | uPlot time series (60-frame moving average, GATE lane, theme-aware). `renderCompareTimeline` for comparison (a line and GATE band per track, the track number at the right end of the line) |
| `frontend/charts/histogram.js` | Canvas density histogram (theme-aware, the title is on the HyperText Markup Language (HTML) side). `renderHistogramCompare` for comparison (an outline per track, the track number at the mode bin) |
| `frontend/charts/segments.js` | Canvas 5-min segment bar chart (theme-aware, the title is on the HTML side). In comparison, `frontend/main.js` passes the track color and draws one chart per track |
| `frontend/style.css` | CSS variables + `[data-theme="dark"]` rules, purple accent (#9C27B0) |
| `frontend/vendor/` | uPlot.iife.min.js, uPlot.min.css (bundled) |

### Shared utilities (`src/analyze_loudness/__init__.py`)

| Function | Responsibility |
|----------|---------------|
| (on import) | Adds `vendor/py-analyze-common/src` to `sys.path` |
| `_ffmpeg_kwargs()` | py-analyze-common's `ffmpeg_kwargs()`. Adds `LC_ALL=C` and `LANG=C` to the per-operating-system (per-OS) subprocess arguments (which hide the console window in Windows frozen mode) |
| `_json_safe()` | py-analyze-common's `json_safe()`. Recursively replaces NaN / Infinity with None |
| `_find_executable()` | py-analyze-common's `find_executable()`. Absolute path of a program found in the absolute entries of PATH, or None |

## Directory layout

```mermaid
graph LR
    root["analyze-loudness/"]
    root --> wf[".github/workflows/"]
    wf --> wf_ci["ci.yaml<br>PR / push<br>runs pytest with the coverage of the Python package and of frontend/*.js and uploads both to Codecov<br>caches the apt package files and the Playwright browsers, saved only by the runs that are not PRs"]
    wf --> wf_rel["release.yaml<br>v* tag / workflow_dispatch on a tag"]
    wf --> wf_tag["tag-release.yml<br>after a successful CI run of a push to master, or by a workflow_dispatch given a commit: when it is a version bump, tags that commit and starts release.yaml"]
    wf --> wf_ffw["ffmpeg-watch.yml<br>daily, detects a new ffmpeg on osxexperts.net, opens the pin update and version bump PRs<br>with a GitHub App's token and merges them without review<br>when detect cannot connect, dispatches itself to run detect again on another runner, up to 3 attempts"]
    wf --> wf_chk["workflow-checks.yml<br>on every PR, checks the rules for SHA pinning of uses: and for same-repository references"]
    wf --> wf_chkt["workflow-checks-test.yml<br>runs the check's fixture tests, the tests of dependabot-auto-merge.yml's trigger, conditions and auto-merge decision,<br>the tests of tag-release.yml's tagging step and the tests of ffmpeg-watch.yml's land step and retry of detect"]
    wf --> wf_dam["dependabot-auto-merge.yml<br>on a Dependabot PR that is one commit at the head, written by Dependabot alone, committed by GitHub (web-flow) and with a verified signature, schedules an auto-merge for an update of the Python dependencies (uv) or of the submodule,<br>and for a semver patch or minor update of a GitHub Action. Required check auto-merge"]
    root --> ght[".github/tests/"]
    ght --> ght_sh["workflow-checks-test.sh<br>test that runs workflow-checks.yml with a fake gh and a fixture git tree"]
    ght --> ght_am["dependabot-auto-merge-test.sh<br>test that dependabot-auto-merge.yml runs on every PR, with only its steps limited to Dependabot PRs,<br>and of which updates and commits (their authors, how many, whether the last is the head, who committed it, whether its signature is verified)<br>its step schedules or turns off an auto-merge for, with a fake gh"]
    ght --> ght_tag["tag-release-test.sh<br>test that runs tag-release.yml's checks and tagging step with a fake gh and a fixture repository"]
    ght --> ght_land["ffmpeg-watch-land-test.sh<br>test that runs ffmpeg-watch.yml's land step with a fake gh that answers by the token of each call and a fixture repository,<br>its detect step with a fake CLI, and the dispatch of the next attempt of detect"]
    root --> r_dep[".github/dependabot.yml<br>version updates every day at 00:00 JST of the GitHub Actions, the py-analyze-common submodule<br>(without Dependabot's default three-day cooldown) and the Python dependencies (uv;<br>yt-dlp and yt-dlp-ejs in one pull request, pyobjc-core and pyobjc-framework-* in another)"]
    root --> r_claude["AGENTS.md"]
    root --> r_readme["README.md"]
    root --> r_readme_ja["README.ja.md"]
    root --> r_pyproj["pyproject.toml<br>CLI tool (pip install -e #quot;.[dev]#quot;)"]
    root --> req["requirements/<br>release.txt, release-build.txt, sign-manifest.txt: the hash-pinned packages the release jobs install,<br>generated by uv from pyproject.toml and the .in files (Pinned release dependencies)"]
    root --> src["src/analyze_loudness/"]
    src --> src_init["__init__.py<br>sys.path injection of vendor, SCHEMA_VERSION"]
    src --> src_main["__main__.py"]
    src --> src_cli["cli.py<br>argparse + main orchestration (CLI)"]
    src --> src_gui["gui.py<br>pywebview + local HTTP server (GUI)"]
    src --> src_dl["download.py<br>yt_dlp.YoutubeDL API, resolving local files (resolve_source), ffprobe duration"]
    src --> src_ana["analysis.py<br>ebur128 stderr parsing, compute_stats"]
    src --> src_cmp["compare.py<br>building and validating single / comparison JSON, statistics of the truncated range"]
    src --> src_upd["update.py<br>auto-update identity (UPDATE_CONFIG: product name, repository, public key, mutex name)"]
    src --> src_plot["plot.py<br>matplotlib figure generation (CLI only)"]
    root --> fe["frontend/"]
    fe --> fe_idx["index.html"]
    fe --> fe_main["main.js<br>fetch + NDJSON progress + DOM rendering + theme toggle"]
    fe --> fe_theme["theme.js<br>getTheme(): chart color provider (light / dark)"]
    fe --> fe_gate["gate.js<br>computeGate(): BS.1770 gating rebuilt from series.M"]
    fe --> fe_i18n["i18n.js<br>the en/ja DICT, which py-analyze-common's /common/i18n.js turns into window.i18n (t / setLang / onChange)"]
    fe --> ch["charts/"]
    ch --> ch_tl["timeline.js<br>uPlot wrapper (theme-aware, GATE lane plugin)"]
    ch --> ch_hist["histogram.js<br>Canvas histogram (theme-aware, no internal title)"]
    ch --> ch_seg["segments.js<br>Canvas segment bars (theme-aware, no internal title)"]
    fe --> fe_css["style.css<br>CSS variables + [data-theme=#quot;dark#quot;] rules"]
    fe --> fe_vendor["vendor/<br>uPlot (bundled)"]
    root --> t["tests/"]
    t --> t_init["__init__.py"]
    t --> t_conf["conftest.py<br>also points py-analyze-common's analyze_common.testing at this repository and package"]
    t --> t_ana["test_analysis.py"]
    t --> t_flow["test_analysis_flow.py<br>analysis, streaming and cache contracts through the GUI's HTTP endpoint"]
    t --> t_cmp["test_compare.py"]
    t --> t_cli["test_cli.py"]
    t --> t_clis["test_cli_single.py<br>single-source CLI analysis with real local audio and its output figure"]
    t --> t_dl["test_download.py"]
    t --> t_gui["test_gui.py"]
    t --> t_plot["test_plot.py"]
    t --> t_pkg["test_package.py<br>the vendor/py-analyze-common entry that the package puts on sys.path once"]
    t --> t_upd["test_update.py<br>UPDATE_CONFIG and the installer.iss / spec / release.yaml that match it"]
    t --> t_ffb["test_ffmpeg_binary.py<br>reads the ffmpeg / ffprobe on PATH with the app's parsers<br>(EXPECT_FFMPEG_DIR points at the bundled binaries)"]
    t --> t_rwf["test_release_workflow.py<br>release.yaml runs test_ffmpeg_binary.py on the ffmpeg / ffprobe inside the distributables;<br>only create-release can write and it runs no Python; the job holding UPDATE_SIGNING_KEY has a read-only token<br>and installs only the hash-pinned yt-dlp; the Developer ID identity is imported right before codesign<br>and deleted when codesign ends; the release jobs install packages only from requirements/*.txt<br>and build tools only after a SHA256 check; requirements/release.txt satisfies pyproject.toml<br>and every requirements/*.txt resolves, with its own pins as constraints, to exactly the packages it pins<br>under the same environment markers (runs py-analyze-common's analyze_common.testing.release_workflow)"]
    t --> t_font["test_chart_font.py<br>no script names a font of its own (runs analyze_common.testing.chart_font)"]
    t --> t_ejs["test_yt_dlp_ejs.py<br>the installed yt-dlp-ejs has the version (major.minor) and script hashes the installed yt-dlp accepts<br>(runs analyze_common.testing.yt_dlp_ejs)"]
    t --> t_tpl["test_third_party_licenses.py<br>the GPL full texts THIRD_PARTY_LICENSES.txt points at, and the spec / installer.iss that bundle them<br>(runs analyze_common.testing.third_party_licenses)"]
    t --> t_fe["test_frontend.py<br>Playwright headless Chromium runner"]
    t --> t_chart["test_chart_rendering.py<br>renders the real chart scripts and exports their pixels in Chromium"]
    t --> t_static["test_static_server.py<br>initial assets are served during bounded connection bursts"]
    t --> t_jsc["js_coverage.py<br>with --js-coverage, the V8 coverage of frontend/*.js that the Playwright tests run, written as LCOV<br>(the same file as analyze-spectrum's)"]
    t --> t_jsct["test_js_coverage.py<br>js_coverage.py: matching V8 ranges to lines, and the LCOV it writes<br>(the same file as analyze-spectrum's)"]
    t --> tf["frontend/"]
    tf --> tf_html["test_ui.html<br>test harness page (DOM + stubs)"]
    tf --> tf_js["test_ui.js<br>browser-based UI state tests"]
    root --> docs["docs/"]
    docs --> docs_arch["architecture.md"]
    docs --> docs_arch_ja["architecture.ja.md"]
    docs --> docs_dec["decisions/<br>closed decisions: what was chosen and what was rejected;<br>each record is an English .md and a Japanese .ja.md"]
    docs_dec --> docs_dec_cmp["comparison-mode.md, comparison-mode.ja.md<br>the comparison mode"]
    docs_dec --> docs_dec_lfi["local-file-input.md, local-file-input.ja.md<br>local audio files as input"]
    docs --> docs_shot["screenshot.png"]
    root --> vend["vendor/py-analyze-common/<br>git submodule (used through sys.path injection)"]
    root --> r_build["build.py<br>Build script: py-analyze-common's analyze_common.build with this app's names<br>(asset download + PyInstaller + Inno Setup / DMG)"]
    root --> r_spec["analyze-loudness.spec<br>PyInstaller spec"]
    root --> r_iss["installer.iss<br>Inno Setup script"]
    root --> r_lic["THIRD_PARTY_LICENSES.txt<br>Bundled license file"]
    root --> r_gpl["licenses/<br>Full texts of GPL v2 / v3 (pointed at by the FFmpeg section of THIRD_PARTY_LICENSES.txt;<br>the spec bundles them at the same level)"]
    root --> ba_pin["build_assets/ffmpeg.json<br>series of the bundled ffmpeg / ffprobe, and URL / SHA256 of the macOS build"]
    root --> ba_sum["build_assets/checksums.json<br>version and SHA256 of the bundled uPlot files"]
    root --> ba_icon["build_assets/icon_draft.svg<br>the source of icon.ico / icon.png / icon.iconset (PYTHONPATH=vendor/py-analyze-common/src python -m analyze_common.icons build_assets)"]
    root --> ba["build_assets/bin/<br>ffmpeg, ffprobe, deno (not tracked by git)"]
```

## Data flow

### CLI

A single source ends in console output and a Portable Network Graphics (PNG) figure.

```mermaid
graph LR
    A["URL or local file"] --> B["resolve_source()<br>yt_dlp.YoutubeDL (opus extract) for a URL"]
    B --> C{"--duration<br>given?"}
    C -->|Yes| D["probe_duration() with ffprobe<br>compute_middle()"]
    C -->|No| E["ffmpeg -af ebur128<br>(stderr parse)"]
    D --> E
    E --> F["compute_stats<br>(numpy)"]
    F --> G["console output +<br>matplotlib PNG"]
```

### GUI

```mermaid
graph TD
    A["POST /analyze<br>{url, duration?}"] --> L{"_cache_get()<br>cached?"}
    L -->|Yes| I["NDJSON result event<br>(meta + title + summary + series)"]
    L -->|No| B["resolve_source()<br>download_audio() with yt_dlp.YoutubeDL for a URL"]
    B --> C["probe_duration()<br>ffprobe"]
    C --> D{"duration<br>specified?"}
    D -->|Yes| E["compute_middle()"]
    D -->|No| F["run_ebur128()<br>ffmpeg -af ebur128"]
    E --> F
    F -->|"time.monotonic()"| G["_speed_factor update"]
    G --> H["build_result()<br>compute_stats() with numpy, then _cache_put()"]
    H --> I
    I --> J["Browser rendering<br>uPlot + Canvas"]
    J --> K["Save JSON / Save Image / Load JSON"]
```

### Comparison mode

2-6 results are overlaid from the start, and all tracks are truncated to the length of the shortest track for comparison.

- **Input**: pressing the submit button moves the input field's source into the queue (a source the queue already holds stays in the field). One row is a single analysis (a JSON row is shown without one), and the row keeps its result. Two or more rows are a comparison, and the button reads Compare while the queue and the field hold two or more sources.
  The queue also takes URLs and local file paths with `+ Add Track`, dropped files (one file dropped on an empty queue goes into the input field instead), and saved single JSON with Load JSON while the queue is not empty (that request carries `{"queue": true}`, and the server does not cache the result for its URL: the row holds it).
  The queue and a source in the input field that the queue does not hold count together toward `MAX_TRACKS`: a track past it is refused with the limit error, and a drop stops at that file.
  In a comparison, rows without a result are analyzed in order with `/analyze`, and all tracks are sent to `/compare`.
  `+ Add Track`, removing a row, Load JSON and a dropped file that joins the queue drop the results on screen when tracks stay in the queue, Clear All drops them too, and moving a row reorders a comparison on screen.
  When a single result is displayed and the input field equals its `source_url`, `+ Add Track` gives the row the displayed result itself
  (the `/load` cache holds only the last loaded result per URL, so looking it up again by URL could swap in a different result).
  The CLI takes 2-6 positional arguments, and reads local paths ending in `.json` as saved single JSON.
  Comparison does not accept `--duration`.
- **Truncation**: `common_frames()` in `src/analyze_loudness/compare.py` counts, for each track, the frames up to the last time of the shortest track (+ half a frame),
  and cuts the `series` of all tracks at the minimum of those counts. All tracks have the same number of frames, so
  the timeline shares a single time axis.
- **Statistics are computed in one place, in Python**. The Integrated, the Short-term (S) / Momentary (M) median and 10th / 90th percentiles (P10 / P90), and the silence ratio over the truncated range are
  computed by `truncated_stats()` in `src/analyze_loudness/compare.py` from the saved series, and attached as `stats` to the `/compare` and `/load` responses.
  They are not saved in the comparison JSON. True Peak and loudness range (LRA) either cannot be computed from the series (True Peak) or are not guaranteed to equal ffmpeg's value
  (LRA), so each track's full-length value is shown, marked explicitly as "(full)".
- **The Integrated over the truncated range recomputes the relative gate over the truncated range**. The full-length `summary.gate_threshold`
  is not used. With ffmpeg 9.0.2, the value recomputed from the first T seconds of the full-length series M was checked against
  ffmpeg's Integrated measured on the same audio with `-t T` (`lavfi.r128.I` of `ebur128=metadata=1`, 3 decimal places);
  across 4 audio files (33 seconds to 144.5 minutes) × T = 20 / 37.3 / 60 / 300 / 1800 / 3600 seconds, in the 17 cases shorter than the audio
  the difference was at most 0.014 loudness units (LU). Reusing the full-length `gate_threshold` deviates by up to 2.92 LU.
  The t / M / S measured with `-t T` match the leading frames of the full length (difference 0).
  The frontend GATE band also recomputes the relative gate with `computeGate(M, t, null)`.
- **Comparison JSON** (schema 3): `{"meta": {...}, "compare": {"truncate_sec": T, "tracks": [single result, ...]}}`.
  Each track's `summary` holds the full-length values, and its `series` the truncated range. There is no `summary` / `series` at the top level, so
  versions up to schema 2 refuse to load it with "missing summary or series". Loading branches on the presence of `compare`.
  Loading a comparison JSON while the queue is not empty is refused.
- **Size limits**: the `/compare` request body is up to 64 MiB (`_MAX_BODY`). Writing out the 9 saved single JSON files
  (43,092-116,299 frames) without separators gives 18.2-18.5 bytes per frame, so up to 6 tracks × 1010 minutes each
  can be sent. The GUI and the CLI save comparison JSON with indentation, and a comparison JSON of 3 tracks and 12,123 frames is
  56.4 bytes per frame. So that a 6 × 1010-minute comparison saved at that size can still be opened, the `/load` limit
  (`_MAX_LOAD_BYTES`) is set to 210 MiB.
- **Telling tracks apart**: the colors are `trackColors` in `frontend/theme.js` (6 colors each for light / dark; the contrast ratio against the chart background is
  at least 3.05). So as not to rely on color alone, the track number is drawn at the right end of the timeline line, at the mode bin of the histogram, on the GATE band label,
  and in the segment heading. The CLI figure uses the 6 light colors (`TRACK_COLORS` in `src/analyze_loudness/plot.py`).

## Typical timings (10 minutes of audio)

| Stage                     | Time    |
|---------------------------|---------|
| Audio DL with yt_dlp API  | 3-8 s   |
| ffmpeg ebur128            | ~11 s   |
| stderr parse + JSON       | <1 s    |
| **Total**                 | **~20 s** |

## GUI

### Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/analyze` | POST | Downloads audio from a URL, or uses a local file as is, and runs the EBU R128 analysis. NDJSON stream response |
| `/save` | POST | Saves the analysis result JSON with a native file dialog |
| `/save-image` | POST | Saves the chart composite PNG (base64) with a native dialog |
| `/compare` | POST | Returns the comparison JSON of 2-6 single results truncated to the shortest track, and the statistics of the truncated range (`stats`) |
| `/load` | POST | Picks a JSON with a native dialog and visualizes the result again. Adds `stats` to a comparison JSON and does not put it in the single-result cache. A single result loaded with `{"queue": true}`, which the page sends while the queue holds tracks, is not put in the cache either: it joins the queue with its data, or the page refuses it at the limit |
| `/browse` | POST | Picks a local audio file with a native dialog and returns its path |
| `/upload` | POST | Places a dropped file (the body as is, the name in `X-Filename`) in a temporary directory and returns its path. Limit 500 MB; extensions per `AUDIO_EXTENSIONS` in `src/analyze_loudness/download.py` |
| `/common/settings.js` | GET | Returns py-analyze-common's `settings.js` preceded by the theme and language saved in the settings file (`window.analyzeSettingsStored`). Reads the settings file on every load (`Cache-Control: no-store`) |
| `/settings` | POST | Saves exactly one of `{"theme": ...}` or `{"lang": ...}` to the app's settings file and returns `{"theme", "lang"}` after saving. Anything else is 400; 500 when it cannot be written |
| `/update/status` | POST | Returns the running version (`current`), whether the build can apply updates (`supported`) and the "Check at launch" setting (`launch_check`) |
| `/update/settings` | POST | Saves `{"launch_check": bool}` to the app's settings file and returns the value after saving. Non-bool is 400; 500 when it cannot be written |
| `/update/check` | POST | Checks `latest.json` of the latest Release; `{"available": true, "version"}` when there is a newer version, otherwise `{"available": false}`. Failure is 502 |
| `/update/install` | POST | Fetches, verifies the signature of and applies `{"version"}` (only the version the preceding check reported is accepted), returns `{"restarting": true}` and ends the app. Failure is 500. When macOS cannot restart after the swap, returns `{"installed": true, "restart_error"}` and keeps running |

POST is accepted only when the Content-Type is `application/json` (`application/octet-stream` for `/upload`); anything else is 415. `/analyze`, `/compare`, `/save`, `/save-image` and `/load` answer a body that is not JSON with 400 (`Invalid JSON body`). The Host and Content-Type checks, `/browse`, `/save-image`, `/settings`, `/update/*` and the `/common/*` files come from py-analyze-common's `GuiHandler` (`analyze_common/server.py`), which `AnalyzeHandler` extends with this app's state (`updater()`, `ui_settings()`, `window()`, `dialog_lock()`, `exit_for_update()`).

### Communication model

The GUI `/analyze` endpoint streams its response as `application/x-ndjson`:

```
{"type":"progress","stage":"download","message":"Downloading audio..."}
{"type":"progress","stage":"download","message":"Downloaded: Video Title"}
{"type":"progress","stage":"analyze","message":"Running EBU R128 analysis...","estimate_sec":12,"duration_sec":600}
{"type":"progress","stage":"stats","message":"Computing statistics..."}
{"type":"result","data":{...}}
```

Input validation failures (invalid type/range of URL/duration) are returned as HTTP 400 + JSON.
Errors that occur in the later download and analysis phases are returned as **HTTP 200 + NDJSON `{"type":"error","error":"..."}`**.
This is a design contract that follows from the HTTP status being unchangeable after the response headers are sent; the client judges success or failure by the NDJSON `type` field, not only by the HTTP status.
`Content-Length` / `Transfer-Encoding: chunked` are not set, and the frame boundary is fixed by `Connection: close`.

Warning event (sent when ffmpeg exits non-zero; shown in the status area, and processing continues with what was parsed from stderr):
```json
{"type":"warning","message":"ffmpeg exited with code 1"}
```

Result event:
```json
{
  "type": "result",
  "data": {
    "meta": {
      "schema_version": 3,
      "version": "1.0.0",
      "analyzed_at": "2026-04-03T12:34:56+00:00",
      "source_url": "https://www.youtube.com/watch?v=..."
    },
    "title": "Video Title",
    "summary": {
      "duration_sec": 600, "frames": 5999,
      "integrated": -18.1, "true_peak": 0.8, "lra": 9.3,
      "gate_threshold": -28.5,
      "short_term": { "median": -19.4, "mean": -20.5, "p10": -24.1, "p90": -15.4 },
      "momentary": { "median": -20.8, "mean": -21.3, "p10": -26.9, "p90": -14.4 },
      "silence_pct": 1.0
    },
    "series": { "t": [...], "S": [...], "M": [...] }
  }
}
```

### Cancel

During analysis the Analyze button changes to Cancel (red). `AbortController.signal` is passed to `fetch()` and to `readNdjsonStream()`,
which cancels the `ReadableStream` reader, and stream reading is interrupted on cancel.
`_setBusy()` sets the `_isBusy` flag and disables the Load JSON, Browse, `+ Add Track` and Clear All buttons, preventing double execution.

### Theme

Themes are switched with CSS variables (`--bg`, `--text`, `--accent` etc. The shared ones are in `vendor/py-analyze-common/src/analyze_common/web/common.css`) + `[data-theme="dark"]`.
`getTheme()` in `frontend/theme.js` returns the color palette used when drawing charts.
A fixed top-right pill button (a Scalable Vector Graphics (SVG) sun / crescent moon / half-filled circle) cycles light, dark and auto.
`auto` follows the OS `prefers-color-scheme`, and reflects changes in real time through the `matchMedia` `change` event.
The choice is saved to `theme` in the app's settings file (`settings.json`) through `/settings`, and `/common/settings.js` passes it to the page on the next launch
(the reason the webview's localStorage does not survive to the next launch is the same as for the storage location of "Check at launch"). The window background color is also decided from the same value, and on macOS that color is shown until the page is drawn (`show_window_color_until_paint()`. It removes the white that WKWebView draws until its first paint). The language is also kept in `lang` of the same file.
The theme toggle's drawing and the shared CSS variables are in py-analyze-common, which analyze-spectrum uses too.

### Auto-update

How an update runs, what is verified and how each OS applies it are in [py-analyze-common's auto-update document](https://github.com/semnil/py-analyze-common/blob/main/docs/auto-update.md). What this repository owns is `UPDATE_CONFIG` in `src/analyze_loudness/update.py`, and the exit handling (`_exit_now()`) in `src/analyze_loudness/gui.py`.

## Charts

### GATE lane

Integrated aggregates only the 400 ms blocks that pass the BS.1770 absolute gate (-70 loudness units relative to full scale, LUFS) and relative gate (the mean of the blocks that passed the absolute gate -10 LU).
A 12 px high GATE band in the timeline's x-axis gutter (between the plot area and the tick labels) shows this selection,
with excluded blocks in amber (at or below the relative gate) / slate (at or below the absolute gate).

- **Exclude ffmpeg's 3 warm-up frames**. Frames are output every 100 ms, but the Momentary window is 400 ms,
  so at t = 0.1 / 0.2 / 0.3 the window is not filled and the value is the silence floor -120.7. These are not gated blocks, so
  `_firstGatedIndex()` determines the start from `series.t` and also removes them from the denominator of the statistics.
  Measured: the 0.91% silence of a 36-second clip was entirely these frames (0.00% with them excluded).
- **The relative gate uses `summary.gate_threshold` (schema 2), and is recomputed from `series.M` when it is absent**
  (`computeGate(M, t, threshold)` in `frontend/gate.js`). Saved JSON from schema 1 goes through the fallback path.
  The recomputed Integrated matches the saved value within 0.05 LU for all 13 saved JSON files.
  For the longest file (116,299 blocks), `computeGate` went from 1.03 ms to 0.25 ms.
  ffmpeg's values are rounded to 1 decimal place, so the results of the 2 paths do not match exactly; only the decision for blocks that land exactly on the threshold
  changes (measured maximum 303 / 95,957 blocks = 0.3 points of included ratio).
- **The plot area is unchanged**. The x-axis `gap` / `size` and the chart height are widened by the same 11 px each to make room for the band, so
  the plot's bounding box stays 2160x540 device px with or without the band (measured).
- **When a single pixel column mixes included and excluded blocks, it is drawn as excluded**.
  Because of this rounding, on long recordings the painted area of the band exceeds the actual excluded ratio (on real files of 61-193 minutes,
  excluded 10-25% against band paint 27-80%). Drag-zooming the x axis reduces the number of blocks per column, and
  the band converges to the actual excluded ranges.
- The numeric summary (included ratio / excluded ratio / threshold) is placed in `.gate-caption` directly below the chart,
  and is burned into the composite PNG as one line of the summary text.

## Tests

### Frontend UI tests

`tests/frontend/test_ui.html` + `tests/frontend/test_ui.js` run through `tests/test_frontend.py` (Playwright + headless Chromium). They check `fmt`, `_setBusy`, `_addTip`, the theme/lang toggles, the fetch mock paths of /analyze + /load, coverage of the dictionary keys and more. The harness runs with normal and delayed update-check JSON replies; its accepted-install case waits for the install request before inspecting it. `test_frontend.py` also checks percent-encoded non-ASCII upload filenames through the application page. Static and application-page servers share the request queue size; `test_static_server.py` serves the HTML first, then checks script response bodies in bounded connection bursts, holding the first accept until its burst has connected. `tests/frontend/test_ui.html` places a stub of `window.analyzeSettings` (language en, theme light; saves are recorded instead of sent) before `frontend/i18n.js`, to decide the language and to check saving. `_isolated_settings` in `tests/conftest.py` points each test's app settings file at a temporary folder.

### JavaScript coverage

With `--js-coverage=PATH`, `tests/js_coverage.py` starts V8's precise coverage on every Chromium page the tests open, before the page loads anything, and takes it before each navigation the test starts (`goto`, `reload`, `go_back`, `go_forward`), which leaves the scripts of the document behind, and when the page, its context or its browser is closed; each take adds the counts since the previous one. It counts the scripts of `frontend/` outside `frontend/vendor/`, served either from the project root (`/frontend/main.js`, `tests/frontend/test_ui.html`) or by the app's handler (`/main.js`), and writes every one of them to PATH as LCOV, a script no test loaded with zero hits. A line's hit count is the count of the innermost V8 range that contains all of its code, summed over pages; blank lines and lines that start a comment are not counted. It fails the test whose page ran a script of another length than the file on disk. py-analyze-common's scripts (`/common/*.js`) are not counted.

## Build & distribution

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
python build.py --installer  # + Inno Setup installer (Windows) / DMG (macOS)
```

Build pipeline:
1. `build.py` (py-analyze-common's `analyze_common.build` with this app's names) downloads ffmpeg, ffprobe, deno and uPlot unless `--skip-download` is given, and checks uPlot against `build_assets/checksums.json` (yt-dlp is a Python dependency)
2. PyInstaller (`analyze-loudness.spec`): bundles Python + dependencies + frontend + binaries
3. Inno Setup (`installer.iss`): Windows installer with license display. Includes `vendor/py-analyze-common/installer/auto_update.iss`, and `build.py` passes `/DMyAppMutex=`. On macOS, `build.py --installer` makes the DMG with create-dmg
4. `.github/workflows/release.yaml`: puts `latest.json`, which signs the SHA-256 of the installer and the DMG, on the Release ([Auto-update](#auto-update)). Its jobs install Python packages only from the hash-pinned `requirements/*.txt`, and Inno Setup / create-dmg only after a SHA-256 check ("Pinned release dependencies" in `AGENTS.md`)

### Bundled assets (`build_assets/bin/`)

The ffmpeg builds carry the GNU General Public License (GPL).

| Binary | Source | License |
|--------|--------|---------|
| deno.exe | GitHub Releases (latest) | MIT |
| ffmpeg.exe | BtbN/FFmpeg-Builds (the gpl build of the `build_assets/ffmpeg.json` series in latest) | GPL-3.0+ |
| ffprobe.exe | BtbN/FFmpeg-Builds (the gpl build of the `build_assets/ffmpeg.json` series in latest) | GPL-3.0+ |
| deno (macOS) | GitHub Releases (latest, aarch64) | MIT |
| ffmpeg / ffprobe (macOS) | osxexperts.net (arm64, pinned by the URL and SHA-256 in `build_assets/ffmpeg.json`) | GPL-2.0+ |

## Accessibility

### `prefers-reduced-motion`

CSS animation / transition are disabled all at once with `@media (prefers-reduced-motion: reduce)` (in `vendor/py-analyze-common/src/analyze_common/web/common.css`).

Chart drawing (uPlot, Canvas histogram, Canvas segments) has no animation processing,
and everything is drawn immediately, so no individual handling is needed. uPlot's cursor tracking is a real-time response to user operation, and
does not fall under the animation that Web Content Accessibility Guidelines (WCAG) 2.3.3 covers.

The countdown display changes its update interval from
1 second to 5 seconds with `matchMedia("(prefers-reduced-motion: reduce)")` (`frontend/main.js`).

### Placement of the charts' `role="img"`

Each chart has a `role="img"` node whose `aria-label` holds a description that includes the statistics.
The histograms attach it to the canvas itself. The timeline attaches it to the container div, because uPlot generates the DOM inside it,
and the segments chart attaches it to the div that holds its canvas.

The title `<h3 class="chart-title">` is always placed **outside** this node.
Accessible Rich Internet Applications (ARIA) treats descendants of `role="img"` as presentational, so placing it inside creates engines in which
the title and the `aria-describedby` (tooltip text) set by `_showTip()`
do not reach assistive technology.

## Design decisions

### ebur128 stderr parsing (no raw audio decode)

ffmpeg's ebur128 filter outputs per-frame loudness values to stderr.
Decoding 50 minutes of audio to Waveform Audio File Format (WAV) requires more than 4GB of memory, so
only the stderr text is processed, keeping memory consumption to a few MB.

### Local HTTP server + pywebview

pywebview uses the OS's native WebView (Windows: WebView2 / macOS: WebKit),
which keeps the bundle size small.
`_HTTPServer` (py-analyze-common's `GuiServer`, a `ThreadingHTTPServer`) is started on a random port (port 0) on 127.0.0.1,
and serves the frontend from the same origin.

### Runtime-calibrated time estimation

`_speed_factor` is updated from the measured analysis time, improving the accuracy of later estimates.
The initial value is 55.0 (about 55 times real-time speed). After each analysis completes, the sample `analyze_sec / elapsed` is blended in as an exponential moving average with weight 0.3, and a sample outside 5-500 is ignored.

### yt-dlp Python API (not a bundled binary)

The `yt_dlp.YoutubeDL` class is called directly as a Python library, and opus is extracted with the `FFmpegExtractAudio` postprocessor. The return value of `extract_info(download=True)` includes the title, so parallel execution is not needed.

Avoiding a bundled binary (`yt-dlp_macos` etc.) avoids at its root the Team ID mismatch problem that occurs during codesign re-signing for macOS (the Python.framework inside a onefile binary cannot be re-signed and is rejected by the hardened runtime). The same approach is used on Windows / Linux as well.

### Middle extraction

With `--duration`, only the middle portion of a long video is analyzed. It is cut out directly during the ebur128 analysis with
`ffmpeg -ss <start> -t <duration>`.

Only the CLI exposes this feature, through the `--duration` option. The GUI does not implement an equivalent input UI (it always analyzes the full length). The policy is that the GUI favors a simple workflow that only takes a URL or a local file path, and leaves uses that need partial extraction to the CLI.

### Conditional static-ffmpeg (CLI only)

In the CLI, `static-ffmpeg` is not used if ffmpeg is installed on the system.
It is detected with py-analyze-common's `find_executable("ffmpeg")` (the absolute entries of PATH only; the same lookup that starts ffmpeg), and `static_ffmpeg.add_paths()` is called only when it is absent.

### Windows subprocess console hiding

In PyInstaller frozen mode, `subprocess.STARTUPINFO` + `STARTF_USESHOWWINDOW` hide
the console windows of the ffmpeg / ffprobe the app starts. yt-dlp runs as a Python API, and its own `Popen` (`yt_dlp/utils/_utils.py`) sets `STARTF_USESHOWWINDOW` on Windows for the ffmpeg / ffprobe / deno it starts.

## Constants

| Constant | Value | Location | Description |
|----------|-------|----------|-------------|
| `SCHEMA_VERSION` | 3 | `src/analyze_loudness/__init__.py` | Schema version of the result JSON (2 = `summary.gate_threshold` added, 3 = comparison JSON added) |
| `MIN_TRACKS` / `MAX_TRACKS` | 2 / 6 | `src/analyze_loudness/compare.py`, `frontend/main.js` | Number of tracks that can be compared |
| `SILENCE_THRESHOLD` | -60 LUFS | `src/analyze_loudness/analysis.py` | Stats exclude frames <= this |
| `GATE_ABSOLUTE` | -70 LUFS | `frontend/gate.js`, `src/analyze_loudness/compare.py` | BS.1770 absolute gate |
| `GATE_BLOCK_SEC` | 0.4 s | `frontend/gate.js`, `src/analyze_loudness/compare.py` | Momentary window length. Used to detect the warm-up frames |
| `SHORT_TERM_WINDOW_SEC` | 3.0 s | `src/analyze_loudness/analysis.py` | Short-term window length. Used to detect the warm-up for the silence ratio |
| `SILENCE_PCT_THRESHOLD` | -40 LUFS | `src/analyze_loudness/analysis.py` | Threshold for the silence ratio |
| `GATE_RELATIVE_OFFSET` | -10 LU | `frontend/gate.js`, `src/analyze_loudness/compare.py` | BS.1770 relative gate (offset from the mean of the passing blocks) |
| `GATE_LANE_H` | 12 px | `frontend/charts/timeline.js` | Height of the GATE band |
| `_speed_factor` | 55.0 (initial) | `src/analyze_loudness/gui.py` | Runtime-calibrated analysis speed |
| Segment size | 5 min | `src/analyze_loudness/plot.py`, `frontend/charts/segments.js` | Bar chart segment width |
| Moving average window | 60 samples | `src/analyze_loudness/plot.py` (of the downsampled series), `frontend/charts/timeline.js` (60 frames) | Timeline smoothing window |
| Downsample target | ~3000 points | `src/analyze_loudness/plot.py` | Plot responsiveness |
| Default theme | "auto" | `frontend/main.js` | Follows OS prefers-color-scheme |
| Theme setting key | "theme" | `vendor/py-analyze-common/src/analyze_common/ui_settings.py` | Key in settings.json (light/dark/auto) |
| Language setting key | "lang" | `vendor/py-analyze-common/src/analyze_common/ui_settings.py` | Key in settings.json (en/ja) |
