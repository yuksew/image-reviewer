# P8-2（削除と取り消し。合格の線 4〜7）の実装の指示書

あなたはこのプロジェクトの実装者（DeepSeek 側）です。**P8-2** を実装してください。

## 最初に読むもの
1. **`C:\Users\yukse\.agents\skills\image-reviewer-dev\SKILL.md`**（**必ず読む**）
2. **`docs/p8-design.md`** — **§0 が拘束力のある差分**。とくに **§0.1（P8-2 の行）/ §0.3（表）/ §0.6（3 段階と 5 分の窓。**規則 1〜5**）/ §0.7（凍結 → 実行）/ §0.11（再リンク）/ §0.13（規律）/ §0.14（利用者の回答 Q1〜Q8）/ §0.16 / §0.17（P8-1 の監査で確定したこと）/ §2.1（表）/ §3.2〜§3.4（口）/ §4（状態）/ §7 / §8.1（P8-2 の担当）/ §8.4（F）/ §9 の P8-2 の行**
3. `docs/p8-1-implementation.md`（**P8-1 の記録**。`duplicates.py` の形・`require_human`・`Clock` の使い方）と `docs/p8-1-audit-triage.md`（監査の指摘と直し方）
4. `docs/p8-0-audit-report.md`（**C-1: 版だけ 6 の DB に表を入れる**話）と `docs/duplicates-deletion-backup.md`（**元ネタ**）
5. 既存のコード: `src/image_reviewer/duplicates.py`（**P8-1 の形**）・`store.py`（`normalize_path` / `is_under` / `mark_location_missing`）・`jobs.py`（**1 本のワーカー・取引の外で外部を待つ**）・`clock.py`（**`now()` と `monotonic()`**）・`api/__init__.py`（`require_human`）・`api/duplicates.py`（口の形）

## 実装する物（**合格の線 4〜7**）

### 1. 3 段階の削除（§0.6 の規則 1〜5）
- **段 1（印）**: **`asset.deleted_at` を立てる**（**行は消さない**。`asset_location` も消さない＝**戻せる**）。
  **一覧からは消える**（既存の絞り込みと整合させる）。
- **段 2（ゴミ箱）**: **`os.rename` で保留領域へ移す**（**`os.replace` を使わない**＝既存を黙って上書きするため。P7 の実測）。
  **移動先に既にファイルがあれば `FileExistsError`（WinError 183）で止め、409 `target_exists`**。
  **別ボリューム（`st_dev` が違う）なら 409 `cross_volume`**（コピーもしない）。**`asset_location.missing_at` を立てる**（行は残す）。
- **段 3（実削除）**: **保留領域のファイルを消す**。**`root.allow_stage3 = 1` の置き場だけ許す**
  （**印が無ければ 409 `stage_not_allowed`**）。**実データは illust-authoring の置き場に印が立っている**（利用者の回答 Q8）。
- **5 分の窓（単調時計）**: **段 3 の実行は「凍結してから 5 分後」**。**窓の間は `remaining_sec` を返す**。
  **アプリが動いていた時間で数える**（壁時計では数えない）。**起動時に消さない**（**期限が切れていても、人が押すかタイマーが回るまで消さない**）。
- **取り消し（`undo`）**: **`os.rename` で元の場所へ戻す**。**元の場所に別のファイルがあれば 409 `target_exists`**
  （**`as_copy` は人だけ**。別名は `<名前>.<連番>.<拡張子>`）。**`deleted_at` を NULL に戻す**・**`missing_at` を戻す**。

### 2. 凍結 → 実行（§0.7）と安全（§0.6 の規則 1〜5）
- **`pending_delete_preview` に凍結**（**`items_json` に `path`（正規化した鍵）と `display_path` の両方**）。
  **実行は「凍結した一覧だけ」**（**その後の追加・変更を拾わない**）。
- **「最後の 1 つ」を消させない**: **`last_copy` を検出したら 409 `last_copy`**（**`confirm_last_copy` を要求**。**1 枚も消さない**）。
  **一括 preview は `last_copies: N` を返す**。
- **1 回の上限**: **エージェントは 200 枚**（**超えたら 422 `too_many` で 1 枚も消さない**＝**部分適用しない**）。**人は上限なし**。
- **`actor` を必ず記録**（`deletion_log` / `pending_delete_preview` / `delete_request`）。**`client_token` は要求の単位**（`delete_request`。**同じ token の再送は 200 で同じ結果**）。
- **`undo` はエージェントにも許す**（**自分が消した物だけ**。**他人の分は 403 `not_yours`**）。

### 3. 口（§3.2〜§3.4）
**`POST /api/locations/delete`**（本文付き。**`DELETE` に本文を持たせない**）・**`POST /api/locations/bulk-delete/preview`**・
**`POST /api/locations/bulk-delete`**・**`POST /api/deletions/{id}/undo`**・**`GET /api/deletions`**（最近の削除）・
**`GET /api/deletions/trash`**（保留と `remaining_sec`）。
**`GET` は 1 バイトも書かない**。**`Host: evil` / `Content-Type: text/plain` で 403**・**語彙外は 422**。

### 4. 期限切れの処理（タイマー）
- **30 秒周期**で**期限切れの保留を消す**（**`job` の仕組みを使うか、`app.py` の lifespan のタスク**。**設計の §0.6-3 と §4.3 に従う**）。
  **起動直後には消さない**（**1 周期待つ**）。**`purge_at` が NULL の物は消さない**。

### 5. テスト（**§8.1 の P8-2 の担当＋§8.4 の F の P8-2 の分**。**「壊すと落ちる」形**）
- **段 1 で行が残る**（戻せる）・**段 2 で `os.rename`**（**`os.replace` に変えると落ちる**）・**`target_exists`**・**`cross_volume`（`st_dev` を注入）**
- **5 分の窓**（**`Clock` を進めて決定的に**。**壁時計を進めても変わらない**）・**起動時に消さない**・**期限切れで消える**
- **凍結した一覧だけを消す**（**凍結後に足した枚が消えない**）・**`last_copy`**・**上限 200（部分適用しない）**・
  **`client_token` の再送**・**`undo`（自分だけ・`target_exists`・`as_copy` は人だけ）**・**`allow_stage3` が無い置き場**
- **`GET` が書かない**（**全表の行数とファイルの size / mtime**）・**403 / 422**

## 守ること
- **`uv run` は `--no-sync`**。`$env:UV_CACHE_DIR = "C:\work\image-reviwer\.uv-cache"`。
- **既存のテストを壊さない**（いま **325 件**）。`gui_smoke`（129）・`gui_layout`（6 画面）も緑のまま。
- **実データ `.data/` は `mode=ro` のみ**（v6・263 枚・判断 3 件）。**壊す試験は必ず複製で**（`sqlite3` の `backup()` ＋ **画像も複製**）。
  **実データの画像を 1 枚も動かさない・消さない**。複製にサーバを立てるときは **`IMAGE_REVIEWER_DATA=<複製>`** を必ず付ける。
- **`ComfyUI` は触らない**。**`git` のコミットはしない**。**README と `docs/design.md` は触らない**。
- **`db.py` の表はもう在る**（v6）。**列を足す必要が出たら `PRAGMA table_info` を見てから `ALTER`**（**`CHECK` は足せない**ことに注意）。
- 記録は **`docs/p8-2-implementation.md`** に（**自分で決めた点・申し送り・設計の穴**）。

## 返すもの（最終応答）
1. 触ったファイルと行数
2. `pytest`（件数・**複数回**）・`gui_smoke`・`gui_layout`
3. **線 4〜7 を実データの複製で通した結果**（**段 1 → 段 2 → 段 3**・**5 分の窓（`Clock` を進める）**・**戻す**・**`last_copy`**・**別ボリューム**・**上限**）
4. **「壊すと落ちる」を確かめた証拠**（`os.rename`→`os.replace`・窓を壁時計に・凍結を外す・`allow_stage3` を無視 など）
5. **実データが無傷**であること（263 枚・判断 3 件・画像の size / mtime が変わっていない）
6. 設計からずれた所／自分で決めた所（1 行ずつ理由）と、気づいた設計の穴
