# Comparison mode decisions

> For the English version, see [comparison-mode.md](comparison-mode.md).

比較モードについて、閉じた判断の記録。比較モードの今の動きは [`docs/architecture.ja.md`](../architecture.ja.md) の「比較モード」の節にある。この文書には、何を選んだかと、却下した案を残す。どの決定も semnil/analyze-loudness#65 (2026-10-17 にマージ) のときのもの。

## Up to six tracks and mixed inputs

- **決定**: 比較は 2〜6 トラックを受け付け、1 つの比較の中に URL と保存済みの単体 JSON を混ぜられる。ローカルの音声ファイルは semnil/analyze-loudness#66 で加わった。
- **却下した案**: 2 トラックだけの A/B 比較。URL だけ。保存済みの JSON だけ。

## Tracks of different lengths are cut to the shortest

- **決定**: どのトラックも一番短いトラックの長さで切り、統計もチャートと同じ切った範囲を対象にする。True Peak と LRA は各トラックの全長の値のままにし、「(full)」と付けて表示する。この 2 つを計算し直さない理由は `docs/architecture.ja.md` の「比較モード」の節にある。
- **却下した案**: 先頭をそろえて、末尾を長さの違うままにする案。各トラックの長さの百分率を時間軸にする案。チャートだけを切る案。

## Track colors and the cue that is not a color

- **決定**: トラックの色 (`frontend/theme.js` の `trackColors`) は、CIEDE2000 の色差を探索して、ほかの制約を付けずに見つけた配色にする。色だけに頼らないよう、タイムラインの線、ヒストグラムの山、GATE のレーン、見出しにトラック番号を描く。
- **却下した案**:
  - 当時の analyze-spectrum のトラックの配色。ライトのテーマではオレンジのチャート背景に対するコントラスト比が 2.7:1 で、ダークのテーマでは緑が -23 LUFS の目標線と同じ色だった。
  - 色相を対にした配色。色差が小さかった。
  - 色でない手がかりとして、トラックごとに破線の模様を変える案。凡例だけにする案。

## Queue UI

- **決定**: 比較するトラックは待ち行列に集める。形は analyze-spectrum の待ち行列と同じにする。
- **却下した案**: 結果の側にトレイを置き、「+ Add to Comparison」のボタンで足す案。
- **経緯**: 入力欄の音源が待ち行列へ移る流れは semnil/analyze-loudness#170 で変わった。今の流れは `docs/architecture.ja.md` の「比較モード」の節にある。

## Comparison JSON

- **決定**: 比較 JSON (schema 3) は、各トラックの切った系列だけを持つ。待ち行列にトラックがある間は、比較 JSON の読み込みを断る。
- **却下した案**: 読み込んだ比較のトラックで待ち行列を置き換える案。待ち行列の後ろに足す案。

## CLI

- **決定**: 音源は位置引数で渡す。2 個以上なら比較になり、`.json` で終わるローカルパスは保存済みの単体の結果として読む。比較では `--duration` を断る。

## /load limit

- **決定**: `/load` の上限を 50 MB から 210 MB に上げた。保存した 6 トラック × 各 1010 分の比較を開き直せるようにするため。値は `src/analyze_loudness/gui.py` の `_MAX_LOAD_BYTES` (今は 210 MiB) で、もとにした大きさは `docs/architecture.ja.md` の「比較モード」の節の「サイズの上限」にある。
- **却下した案**: 比較 JSON を詰めた形で保存する案。上限を文書に書くだけにする案。
