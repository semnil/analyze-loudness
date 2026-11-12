# Local file input decisions

> For the English version, see [local-file-input.md](local-file-input.md).

ローカルの音声ファイルの分析について、閉じた判断の記録。ローカルファイルの今の扱いは `CLAUDE.md` の「Local files」の節にある。この文書には、何を選んだかと、却下した案を残す。どの決定も semnil/analyze-loudness#66 (2026-10-17 にマージ) のときのもの。

## Inputs

- **決定**: ローカルファイルは 3 つの方法で渡せる。入力欄に打ち込んだパス、Browse ボタンのファイルダイアログ、ドラッグ & ドロップ。analyze-spectrum と同じ組み合わせにする。
- **却下した案**: ドラッグ & ドロップを入れない案。

## Saved JSON keeps the full path

- **決定**: 保存する JSON は、ローカルファイルの絶対パスを `meta.source_url` に持つ。
- **却下した案**: ファイル名だけを保存する案。音源を書かない案。

## UNC and device paths are refused before resolution

- **決定**: スラッシュかバックスラッシュ 2 つで始まるパス (UNC パスとデバイスパス) は、パスを解決する前、ファイルがあるかを調べる前に断る。断るのは `/analyze`、CLI、ページの待ち行列。NT 名前空間のパスは semnil/analyze-loudness#83 で断る対象に加わった。
- **理由**: 保存済みの JSON は `meta.source_url` にこの形のパスを持ちうる。Load JSON はその値を入力欄に戻す。コードは、Windows ではこの形のパスを解決するか開くと、パスが名指すホストへ接続する、という前提に立つ (`src/analyze_loudness/download.py` の `is_network_path`)。
- **却下した案**: Load JSON が http(s) でない `source_url` を入力欄に戻すのをやめるだけにする案。この形のパスを受け付けて、文書に書く案。
