# Local file input decisions

> 日本語版は [local-file-input.ja.md](local-file-input.ja.md) を参照してください.

Closed decisions about analyzing local audio files. How local files are handled today is in the "Local files" section of `AGENTS.md`; this file keeps what was chosen and what was rejected. The decisions were made for semnil/analyze-loudness#66 (merged on 2026-10-17).

## Inputs

- **Decision**: a local file can be given in three ways: a path typed into the input field, the file dialog of the Browse button, and drag and drop. This is the same set as analyze-spectrum's.
- **Rejected alternative**: leaving out drag and drop.

## Saved JSON keeps the full path

- **Decision**: the saved JSON keeps the absolute path of a local file in `meta.source_url`.
- **Rejected alternatives**: saving only the file name; leaving the source out.

## UNC and device paths are refused before resolution

- **Decision**: a path that starts with two slashes or backslashes (a UNC path or a device path) is refused before it is resolved or checked for existence, by `/analyze`, by the CLI and by the queue of the page. semnil/analyze-loudness#83 added the NT namespace paths to the refused ones.
- **Reason**: a saved JSON can carry such a path in `meta.source_url`, and Load JSON puts that value back into the input field. The code assumes that, on Windows, resolving or opening such a path connects to the host the path names (`is_network_path` in `src/analyze_loudness/download.py`).
- **Rejected alternatives**: only stopping Load JSON from putting a `source_url` that is not http(s) back into the field; accepting such paths and documenting it.
