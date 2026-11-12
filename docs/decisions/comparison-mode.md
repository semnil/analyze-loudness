# Comparison mode decisions

> 日本語版は [comparison-mode.ja.md](comparison-mode.ja.md) を参照してください.

Closed decisions about the comparison mode. How the mode works today is in the "Comparison mode" section of [`docs/architecture.md`](../architecture.md); this file keeps what was chosen and what was rejected. The decisions were made for semnil/analyze-loudness#65 (merged on 2026-10-17).

## Up to six tracks and mixed inputs

- **Decision**: a comparison takes two to six tracks, and one comparison can mix URLs and saved single-result JSON. Local audio files joined them with semnil/analyze-loudness#66.
- **Rejected alternatives**: an A/B comparison of two tracks only; URLs only; saved JSON only.

## Tracks of different lengths are cut to the shortest

- **Decision**: every track is cut to the length of the shortest track, and the statistics cover the same cut range as the charts. True Peak and LRA stay the values of each whole track and are labelled "(full)"; why these two are not recomputed is in the "Comparison mode" section of `docs/architecture.md`.
- **Rejected alternatives**: aligning the starts and leaving the ends at different lengths; a time axis in percent of each track's length; cutting only the charts.

## Track colors and the cue that is not a color

- **Decision**: the track colors (`trackColors` in `frontend/theme.js`) are the palette that a search over CIEDE2000 color differences found with no further constraint. So that color is not the only cue, the track number is drawn on the timeline lines, at the histogram peaks, on the GATE lanes and in the headings.
- **Rejected alternatives**:
  - analyze-spectrum's track palette as it was then: in the light theme its orange had a contrast ratio of 2.7:1 against the chart background, and in the dark theme its green was the same color as the -23 LUFS target line.
  - A palette of paired hues: its color differences were smaller.
  - For the cue that is not a color: a dash pattern for each track; the legend alone.

## Queue UI

- **Decision**: the tracks of a comparison are collected in a queue, in the same form as analyze-spectrum's queue.
- **Rejected alternative**: a tray on the result with an "+ Add to Comparison" button.
- **History**: how a source moves from the input field into the queue changed with semnil/analyze-loudness#170. The current flow is in the "Comparison mode" section of `docs/architecture.md`.

## Comparison JSON

- **Decision**: a comparison JSON (schema 3) holds only the cut series of each track. Loading a comparison JSON is refused while the queue holds tracks.
- **Rejected alternatives**: replacing the queue with the tracks of the loaded comparison; appending them to the queue.

## CLI

- **Decision**: the sources are positional arguments. Two or more make a comparison, a local path ending in `.json` is read as a saved single result, and a comparison refuses `--duration`.

## /load limit

- **Decision**: the limit of `/load` was raised from 50 MB to 210 MB, so that a saved comparison of 6 tracks of 1010 minutes each can be opened again. The value is `_MAX_LOAD_BYTES` in `src/analyze_loudness/gui.py` (210 MiB today), and the sizes it was derived from are under "Size limits" in the "Comparison mode" section of `docs/architecture.md`.
- **Rejected alternatives**: saving the comparison JSON in a compact form; only documenting the limit.
