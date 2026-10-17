# P8-4（バックアップと復元）の実装の指示書

あなたはこのプロジェクトの実装者（DeepSeek 側）です。**P8-4** を実装してください。**利用者が「取っていない（不安）」と言っている所**です（P8 の設計 §0.14 Q3）。

## 最初に読むもの
1. **`C:\Users\yukse\.agents\skills\image-reviewer-dev\SKILL.md`**（**必ず読む**）と **`image-reviewer-audit`**（監査の見方）
2. **`docs/p8-design.md`（997 行）** — **§0.12（バックアップ）/ §0.1（P8-4 の行）/ §0.3 / §0.6（安全規則）/ §0.13 / §0.14（Q3・Q6）/ §0.16 / §0.18 / §2.1 / §3.3（口）/ §6（契約）/ §7 / §8.1（P8-4 の担当）/ §8.4（F7）/ §9 の P8-4 の行**
3. **`docs/p8-2-audit-report.md` の B-3**（**壊れた DB の実測**: 先頭 4KB を潰すと開けない・**2 ページ目を潰すと `quick_check` が例外**・300 ページ目は `ok`）と `docs/duplicates-deletion-backup.md`（元ネタ）
4. 既存のコード: `src/image_reviewer/cli.py`（**`backup` / `restore` / `rebuild-metadata` を作る**）・`store.py`（**`quick_check` の呼び方**）・`db.py`・`capture.py`（**sidecar**）・`png_meta.py`・`schemas/backup-manifest.schema.json`（**P8-0 で作った契約**）・`tools/check_contract_p8.py`

## 実装する物

### 1. バックアップ（§0.12・利用者の回答 Q6）
- **置き場**: 既定は **`%USERPROFILE%\image-reviewer-backups\`**（**`<data>` の外**）。**設定で別ドライブも指定できる**
  （設計 §3.3 の口。**`backup_dir` を変える口**）。
- **日次**: **30 秒周期のタイマーで「今日まだ取っていなければ取る」**（**起動時だけにしない**＝立てっぱなしのアプリでも取れる。
  **点検 B2**）。**「いま取る」は必ず新しく取る**（同じ日でも朝の物を返さない）。
- **何を取るか**: `db.sqlite3`（**`sqlite3` の `backup()` で WAL を畳んで**）・**`export/`**・**`sidecar/`**・**`settings`**（**`manifest.json` は `schemas/backup-manifest.schema.json` を通す**）。
  **画像そのものは取らない**（設計の判断）＝**どこに何があるか（`asset_location` のパス）と sidecar / PNG で組み直せる**。
- **増分**: **前回と同じ物はコピーしない**（ハッシュで見る）。**保持は N 世代**（設計の数）。
- **失敗したら**: **`last_error` に残して画面に出す**（**黙って失敗しない**）。

### 2. 復元と組み直し（§0.12）
- **`restore`**: **バックアップから DB を戻す**（**元の DB は退避してから**。**戻す前に `quick_check`**）。
- **`rebuild-metadata`**: **PNG と sidecar から来歴を組み直す**（**P8-4 の最後**。実データの sidecar は 1 件しかないので**合成で試す**）。
- **壊れた DB の扱い（F7）**: **`quick_check` が例外を投げたら「壊れている」に数える**（行を返さない）。
  **先頭 4KB が壊れていると開けない**（その場合は別の道＝バックアップから戻す案内）。**読み取り専用で起動する道**も用意する（設計 §10 の「先に潰す」）。

### 3. 口と CLI（§3.3）
- **`POST /api/backup`**（**人だけ**。「いま取る」）・**`GET /api/backup`**（**状態と一覧**。**`GET` は 1 バイトも書かない**）・
  **`POST /api/roots/{id}/allow-stage3`**（**G-3 で P8-4 に回された口**。**人だけ**。`root.allow_stage3` を立てる）。
- **CLI**: **`backup`** / **`restore`** / **`rebuild-metadata`**（**設計の引数**）。
- **作らない物（G-8）**: **`deletions.json` の契約**・**`POST /api/backup/restore`**（**CLI が主**）。

### 4. テスト（**§8.1 の P8-4 の担当＋§8.4 の F7 と P8-4 の分**。**「壊すと落ちる」形**）
- **`quick_check` が例外を投げる DB**（**2 ページ目を 0 で潰す**）を**壊れていると判定**できるか
- **先頭 4KB を潰した DB** の扱い（**開けない**ことと、そのときの案内）
- **日次がタイマーで回る**（**同じ日は 1 回**・**「いま取る」は必ず新しく**）／**失敗を `last_error` に残す**
- **`backup()` で WAL を畳む**（**判断 3 件が抜けない**＝P4-0 の D-1 の教訓）／**`manifest` が契約を通る**（**本物の `jsonschema`**）
- **`restore`**（元の DB を退避・**戻す前に `quick_check`**）／**`rebuild-metadata`**（**合成の PNG と sidecar から**）
- **`GET` が書かない**（**全ファイルと全表**）・**403 / 422**

## 鉄則
- **実データ `.data/` は `mode=ro` のみ**。**画像を 1 枚も動かさない**。**壊す試験は必ず複製で**（DB と画像の両方）。
  **複製にサーバを立てるときは必ず `IMAGE_REVIEWER_DATA=<複製>`**。**`.backup/` を消さない**。
  **バックアップの置き場も実データの外**（`%USERPROFILE%` の下。**実データの隣に作らない**）。
- **利用者のアプリ（8790）を止めない**。**`ComfyUI` に触らない**。
- **`uv run` は `--no-sync`**（`$env:UV_CACHE_DIR = "C:\work\image-reviwer\.uv-cache"` を最初に）。
- **既存のテストを壊さない**（いま **408 件**）。`gui_smoke`（207）・`gui_layout`（8 画面）も緑のまま。
- **`git` のコミットはしない**。**README と `docs/design.md` は触らない**。
- **PowerShell の `Get-Content|Set-Content` を使わない**（cp932 で壊れる）。
- **画面は作らない**（P8-5。**口と CLI まで**）。記録は **`docs/p8-4-implementation.md`** に。

## 返すもの（最終応答）
1. 触ったファイルと行数
2. `pytest`（件数・複数回）・`gui_smoke`・`gui_layout`
3. **壊れた DB の 3 つの形**（先頭 4KB・2 ページ目・300 ページ目）の扱いの結果
4. **バックアップの結果**（**日次がタイマーで回る**・**「いま取る」が必ず新しい**・**WAL を畳む**・**manifest が契約を通る**・**失敗を残す**）
5. **`restore` と `rebuild-metadata`** の結果（**合成で**）
6. **`allow-stage3` の口**の結果／**実データが無傷**であること
7. 設計からずれた所／自分で決めた所（1 行ずつ理由）と、気づいた設計の穴
