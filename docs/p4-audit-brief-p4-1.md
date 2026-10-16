# 監査の指示書（P4-1: タガーと背景ジョブ）

あなたは**実装の監査者**です。**P4-1（タガー・背景ジョブ・タグの API）**を監査してください。

- 対象: `C:\work\image-reviwer`
- あなたの出力: **`docs/p4-1-audit-report.md` を新規に書くだけ**
- 言語: 日本語。**実行してよい**（実行したコマンドと結果を報告に書く）

## 0. 環境（**注意: 利用者のサーバが動いています**）

- **`image-reviewer.exe serve --port 8790`（PID 35164、2026-10-15 19:26 起動）が動いていて `.venv` の exe を握っています。**
  そのため **`uv run` の再インストールが `os error 32` で落ちます**。`uv run --no-sync …` か
  **`.venv\Scripts\python.exe`** を使ってください（pytest は `uv run --no-sync pytest -q` で通ります）。
- **実データ `.data/` は `mode=ro` のみ**（**`user_version = 3`**・263 枚・判断 3 件。**まだ v5 に上がっていません**）。
  壊す試験はコピーで。コピーは **`sqlite3` の `backup()` API** で作る（**WAL を畳まないと判断が抜ける**。P4-0 の申し送り）。
- 一時物は `.tmp-audit-redo/`（**`data-p40`（v5・タグ 3 語）が残っています**。P4-1 の検証にも使えます）。
- **ソースは編集しない。**

## 1. P4-1 で入ったもの

| # | 入ったもの | 場所 |
| --- | --- | --- |
| 1 | **タガー**: 語の正規化（括弧とコロンは残す）／`png_words()`／`TagCsv`／`preprocess()`（§0.6 の 9 手順）／`BuiltinTagger`／`ComfyTagger`（**既定 `IllustTagger`**・`upload/image` で `temp` に複製）／`detect()`+`choose()` | `src/image_reviewer/tagger.py`（新規 531 行） |
| 2 | **背景ジョブ**: ワーカー 1 本・1 枚 1 取引・中断・失敗の記録・起動時の後始末・`known` の引き直し（§I-1）・`job.note` | `src/image_reviewer/jobs.py`（新規 391 行） |
| 3 | **タグのサービスと API**: 契約の形・決定的な並び・`require_human()`（1 か所）・`GET /api/tags`（既定 `known=1`）・`POST /api/assets/tag`（202）・`GET /api/jobs{,/id,/items}`・`cancel`・`?tag=&known=` | `src/image_reviewer/tags.py`・`src/image_reviewer/api/tags.py`（新規） |
| 4 | 変更: `db.py`（`CHECK (known IN (0,1))`・`asset_tag.actor`・`job.note`）／`app.py`／`api/__init__.py` | — |
| 5 | テストと道具: `tests/test_tags.py`（9 件）・`tests/test_jobs.py`（11 件）・`tools/probe_p4.py`（226 行） | — |

## 2. 確かめてほしいこと

1. **合格の線（§1.2 の 1・2・7）をあなたの手で**。`tools/probe_p4.py --engine comfyui` を自分で回し、
   値（8 枚に 7〜12 語・出所が混ざらない・2 回目の追加・403・404）を確かめる。
   **線 8（内蔵と ComfyUI の一致）は `onnxruntime` が無いので未達**（利用者の回答 Q4 で後回し）。
   `--engine both` が **409 `tagger_unavailable` を正直に返す**ことを確かめる。
2. **内蔵の前処理（§0.6）が実装どおりか**。**点検が「ComfyUI と 66/66 語一致」を確認した 9 手順**
   （白 255 の正方形パッド・LANCZOS・float32 の 0〜255・**RGB→BGR**・CSV の行順で general/character・閾値 0.35/0.85・
   rating は捨てる・`all = character + general`）と実装を突き合わせる。**`onnxruntime` を入れたときに
   すぐ線 8 を測れる形か**（入れられないなら**コードを読んで**判定し、その旨を書く）。
3. **語の正規化（§0.7 / 点検 A-1）**: `\(` `\)` のエスケープだけを外し、**括弧とコロンは残す**か。
   `rem_\(re:zero\)` → `rem_(re:zero)`／`:d` が壊れないか。**`png_words()` が `(…:1.5)` の小数を壊さないか**。
   **64 字の上限**と空の断片の除外（§0.8-6）。
4. **`known` の扱い（§I）**: 導出値か。**`INSERT OR IGNORE` ではなく `ON CONFLICT ... max()`** か。
   **ジョブ開始時の引き直し**があるか（CSV が無い環境・PNG が先の環境で `known=0` のままにならないか）。
   `CHECK (known IN (0,1))`。**`GET /api/tags` の既定が `known=1`** か（実データでは上位 4 語が全部 `known=0`）。
5. **`GET` に副作用が無いか**（§0.10）。**タグ付けは `POST` のときだけ**走るか。
   **手動の付け外しが `human` だけ**（403）で、**検査が 1 か所**か（後で外せる形）。
6. **ジョブの正しさ**: ワーカー 1 本（2 つ目の `POST` が 409 `job_running`）／中断が 1 枚ごと／
   失敗が 1 件ずつ `job_item` に残る／**1 枚 1 取引**（途中で落ちても既に付いた語が残る）／
   起動時に残った `running` の後始末。**`queued` のまま残る行が無いか**。
7. **ComfyUI 経由の作法**: `upload/image` で `temp` に複製し、**名前が `<asset_id>-<sha8>`** か
   （中身が変わったときにキャッシュを引かないか）。**ノード番号を決め打ちしていないか**（`scores` / `tags` を探す）。
   **既定が `IllustTagger`** か。**`WD14Tagger` を選んだときにスコアが NULL になる**ことを設計どおり扱っているか。
8. **契約と決定性**: `GET /api/assets/{id}/tags` が契約の形か（同じ語は 1 行・`sources` に全部）。
   並びが `category`（4 → 0 → 他）→ `score` 降順（NULL 最後）→ `name` で決定的か。
   `review.json` の `tags[]`（`include_tags=true`）が本物の `jsonschema` で通るか。
9. **性能**: §7 の値と突き合わせる（**別々の画像**で測る）。**1 万枚の見積り**。
   **`_tag_docs` の 1 枚 1 クエリ**（P4-0 の申し送り）が `include_tags=true` の全件で問題になるか。
10. **テストが本当に落ちるか**（設計 §8.1 の P4-1 の担当分）。**壊すと落ちる**形か。
11. **実装者が自分で決めた 6 点**（`_primary_path` に dict を渡す・CSV は方式によらず読む・`job.note` を足した・
    `GET /api/jobs/{id}/items` を足した・`?tag=` の既定 `known=1`・起動時に `running` を `failed` に）が妥当か。
12. **設計の穴 5 件**（`pyproject.toml` の任意依存が**利用者のサーバが動いているため入れられない**・
    `job.note` を設計に足すべき・`job_item` に時刻が無い・`?tag=` がメモリ上の一覧・`force` の消し方）を判定する。
13. **回帰**: `pytest` 251・`gui_smoke`・`gui_layout`（**4 画面**）が緑か。**`GET` が書かない**ままか。
    P5 / P6 の口と契約が変わっていないか。**実データ `.data/` の mtime が変わっていない**か。

## 3. 報告の形式

`docs/p4-1-audit-report.md` に、これまでと同じ形（A / B / C / D / E / F / G（推奨つき）/ H）。
各項目に**場所**と**実行したコマンド / 再現手順**。最後に**最も重大な 3 件**。

## 4. 往復

```powershell
orca orchestration send --to run:run_5bdd431bf57b --type status --subject p4-1-audit-done `
  --body (Get-Content -Raw $env:TEMP\p4-1-audit.txt) --json
```

- subject は `p4-1-audit-start` / `p4-1-audit-mid` / `p4-1-audit-done`。待たずに続けて `G` に書いてください。
