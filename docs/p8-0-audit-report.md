# P8-0 監査報告（v6 の表と契約）— 実行込み

- 日付: 2026-10-17（JST 21:40〜22:05）
- 指示書: `docs/p8-audit-brief-p8-0.md`。実装の記録: `docs/p8-0-implementation.md`（82 行）。
- 対象（コミット `35bfc44`、21:35:32。11 ファイル +877/-4）: `src/image_reviewer/db.py`（685 行。`SCHEMA_VERSION = 6`・`V6_DELETE_DDL`・`_migrate_v6`・`_top_up_v6`）、
  `src/image_reviewer/clock.py`（59 行。新規）、`schemas/backup-manifest.schema.json`（64 行。新規）、`tools/check_contract_p8.py`（98 行。新規）、
  `tools/p8_0_real_data.py`（95 行。新規）、`tests/test_db.py`（+184）、`tests/test_export.py`（+42）、`tests/test_clock.py`（59 行。新規）、`docs/p8-design.md`（+3/-3）。
  監査中に対象の `git status` は空のまま（本報告だけが untracked）。
- 設計の版: `docs/p8-design.md` **837 行**（コミット `60599aa` → `35bfc44` で索引名の 3 行だけ変更）。§2.1 が 5 表・6 索引＋ `asset.deleted_at`。
- 環境: `uv run --no-sync`。SQLite **3.53.1**・Python 3.14.7・`jsonschema` **4.26.0**。実データ `.data` は `mode=ro` と `backup()` の複製だけ。
  複製は `.tmp-audit-redo/p8-0-audit/`（`paths/`・`gui/`・スクリプト 8 本・出力）。サーバは複製 `gui/` で **8791**（PID 41244。終了後に `netstat` で 0 本を確認）。
  **8790 は止めていない**（PID 27608、10-16 18:29 起動のまま。監査の前後で `health` 200）。ComfyUI は触っていない。
- 触っていないもの: `src/`・`tools/`・`tests/`・`schemas/`・`docs/`（本報告以外）・`.backup/`・`.data/`（`db.sqlite3` 1,265,664 B・03:24:06、`-wal` 251,352 B・21:33:46、`sidecar` / `export` / `thumbs` の mtime も監査の前後で同じ）。コミットしていない。
- 数え方の注記: 実データの `sqlite_master` で `type='table'` は **24 行**（実装者の「24 表」）。うち 1 行は `sqlite_sequence` なので**利用者の表は 23**。本報告は 23 を使う。
- 回帰: **pytest 296 passed × 3 回**（13.39 / 13.29 / 13.49 s。揺れなし）、**gui_smoke 129 ok / NG 0**、**gui_layout 6 画面すべて ok**（比較・要求・まとまり・注記＋タグ・語の一覧・ジョブ。各 3 窓）。

## 判定: **合格（条件つき）**

P8-0 の約束（機能を足さない・5 表と 6 索引・2 列・契約 1 つ・`review.json` 不変・移行が何度でも安全・実データの掃除と印）は**すべて実行で裏が取れた**。
設計 §2.1 の 12 文は**正規化すると全部 `db.py` にある**（5 表とも列の名前・順・制約が 1 対 1）。4 つの道（新規・v1・v3 の控え・v5 の控え）と実データ（v6）の複製が
**`sqlite_master` 全体で同一**になり、3 回呼びで不変、263 枚と判断 3 件は無傷。索引名の罠（`ux_request_token`）は**本物**で、名前を戻すと同じ token が 2 行入った（C-0）。
実データの作業は報告どおり（12 ファイル・30,783 B が控えにあり、画像 263 枚は size と mtime が DB と一致）。

条件は 3 つ。(1) **`band` の `CHECK` のテストが空振り**（外しても緑。FK が先に落ちている）＋ `delete_request` / `duplicate_exclusion` / `pending_delete_preview` の `CHECK` が未試験（F-1）。
(2) **P7 が `user_version = 6` を付けた DB は P8 の表を一生持たない**（早期 return の `_top_up_v6` は列しか補わない。`.backup/pre-p7-*` の 3 つが該当。C-1）。
(3) `deletion_log.request_id` の FK・`phash_band` の主キー・平の索引 4 本にテストが無い（F-2）。どれも P8-1 の最初に小さく足せる。

**最も重大な 3 件**

1. **F-1 `CHECK (band BETWEEN 0 AND 7)` を外しても 65/65 で緑。** `tests/test_db.py:676` は `asset_id = 'a'`（存在しない）で入れているので、`PRAGMA foreign_keys = ON` の下では **FK が先に落ちて `IntegrityError` になる**＝`CHECK` の有無と無関係に通る。
   私の `constraints.py`（実在の `asset_id`）では `CHECK constraint failed: band BETWEEN 0 AND 7` が出るので制約そのものは効いている。**テストだけが守っていない**。同じテストは `delete_request` の `stage` / `actor`、`duplicate_exclusion` と `pending_delete_preview` の `actor` も見ていない（M1b / M4b / M4c が緑）。
   実装の記録 §2「`CHECK` 6 種が全部落ちる」は**実行の結果としては正しいが、テストの範囲ではない**。
2. **C-1 P7 の v6 からの道が穴。** `.backup/pre-p7-check-20261017-023602` / `pre-p7-removal-20261017-030324` / `pre-p7-removal2-20261017-032405` は **`user_version = 6`・24 表（`recipe_*` 6 表）**のまま。
   その複製で `migrate()` → 早期 return → `_top_up_v6` が `deleted_at` / `allow_stage3` / `ix_asset_del` は補うが、**P8 の 5 表と 6 索引は作られない**（新規との差 37 件。`paths.py` の `[p7-v6]`）。
   版は 6 と答えるので `health` も通り、**P8-1 以降で `no such table: deletion_log` になる**。設計 §0.3 L65「番号は空いている」は**控えには当てはまらない**。
   直し方は 1 行: `_top_up_v6` の先頭で `con.executescript(V6_DELETE_DDL)`（全部 `IF NOT EXISTS` なので冪等。`_migrate_v6` と二重でも害が無い）。P8-4 の `restore` が「版 6 なら受け入れる」作りになる前に。
3. **F-2 DDL の約束のうち 3 種にテストが無い。** `deletion_log.request_id REFERENCES delete_request(id)`（`db.py:528`）を外す（M14）・`phash_band` の `PRIMARY KEY (asset_id, band)`（`db.py:552`）を外す（M19）・
   `ix_deletion_asset` / `ix_deletion_request` / `ix_phash_band` / `ix_preview_expiry` を 1 本ずつ外す（M18a〜d）は**すべて 65/65 で緑**。`_dump` を比べるテストは **v5 の道と新規の道が同じ壊れた DDL** から作られるので索引の欠落を捕まえない。
   P7-0 の F-1 と同じ型。`constraints.py` の 3 行（`request_id='nope'` → FK／参照のある要求の削除 → FK／`PRAGMA index_list` に 6 本）を `test_db.py` に写せば済む。

---

## A. 直っていない／設計の約束が成り立たない

- 無し。点検 A1（`kind` の語彙）・A2（`client_token` は要求の単位）・A3（`asset_location` を消さない）は P8-1 / P8-2 の範囲。A2 の表（`delete_request`）は**この段で正しく入った**（C-0）。

## B. 重大

- 無し。C-1 は実データには当たらない（実データは v5 から正しく上がっている）ので C に置く。

## C. 中程度

### C-0 確かめた結果、問題なし（1 行ずつ。実行したもの）

- **移行の 4 つの道＋実データ**（`paths.py`）: 新規 / `DDL` → `user_version = 1` → `migrate()` / `.backup/pre-p4-20261016-093705`（v3・263・3）の複製 / `.backup/pre-p8-0-20261017-213346`（v5・263・3）の複製 / `.data`（v6）の複製。
  5 つとも **v6・23 表・`integrity` ok・FK 違反 0**、**`sqlite_master` 全体（`sql` まで）が新規と差 0**。v3・v5・実データの道で 263 枚・判断 3 件が保たれる。
- **3 回呼び**: 5 つの道すべてで `migrate()` × 3 → 6 / 6 / 6、その後 2 回呼んでも `sqlite_master` 不変。
- **`_top_up_v6` が早期 return 側から呼ばれる**（`db.py:244`）: v6 の複製で `ix_asset_del` と `deleted_at` を落としてから `migrate()` → 版 6 のまま列と索引が戻り、**新規と同一**。外すと `test_v6_topps_up_…` が落ちる（M7）。
- **設計 §2.1 と `db.py` の 1 対 1**（`ddl_diff.py`）: コメントと空白を落とすと設計の 12 文は**すべて実装にある**。5 表とも列の並びと制約が同一（`delete_request` 7・`deletion_log` 15・`duplicate_exclusion` 7・`phash_band` 4・`pending_delete_preview` 9 項目）。実装にだけある 2 文（`ix_asset_del` の `CREATE INDEX`・`root` の `ALTER`）は §0.3 / §9 に書かれている物（E-3）。
- **`CHECK`（実在の行で実行。`constraints.py`）**: `deletion_log` の `stage=4` / `actor='robot'`、`delete_request` の `stage=4` / `actor='robot'`、`duplicate_exclusion` の `(B,A)` / `(A,A)` / `actor='robot'`、`phash_band` の `band=8` / `band=-1`、
  `pending_delete_preview` の `stage=0` / `actor='robot'`、`root.allow_stage3=2`（`CHECK`）/ `NULL`（`NOT NULL`）**の 13 通りが全部落ち**、正しい値 5 通りは通る。
- **`ux_delete_token` が本当に効く**: `tok1` の 2 行目 → `UNIQUE constraint failed: delete_request.client_token`。**NULL は 3 行入る**。`EXPLAIN` で `client_token = ?` だけでも `USING INDEX ux_delete_token`。
- **`IF NOT EXISTS` の罠は本物**（`paths/trap`）: 新規 v6 で `ux_delete_token` を落とし `CREATE UNIQUE INDEX IF NOT EXISTS ux_request_token ON delete_request(...)` → **エラー無し・`PRAGMA index_list(delete_request)` は空**・**同じ token が 2 行入った**。名前を戻す壊し方（M3b）はテストが捕まえる（`INDEXED BY` が `no such index`）。
- **FK と CASCADE が実際に効く**: `request_id='nope'` → FK で落ちる／参照のある `delete_request` の削除 → FK で落ちる（既定の RESTRICT）／`asset` を消すと `phash_band` の 2 本が消える（CASCADE。実データの複製でも新規でも）。
- **索引が引かれる**（`EXPLAIN QUERY PLAN`、9 本）: `ix_asset_del`（`IS NOT NULL` と `= ?` の両方）・`ix_deletion_pending`・`ix_deletion_asset`・`ix_deletion_request`・`ux_delete_token`・`ix_phash_band`・`ix_preview_expiry` がすべて意図した問い合わせで `USING INDEX`。
- **`asset.deleted_at` / `root.allow_stage3`**: 列として入っている（`PRAGMA table_info`）。`deleted_at` に `CHECK` が無いことは設計 §0.3 L67・§2.1 L392-393 と `db.py:638` が明記し、`'banana'` が入る（実測。値の検査はサービス層＝申し送り）。
  実データ（`mode=ro`）: `c:\work\illust-authoring\.store\anima-dev` が **1**、`c:\ai\comfyui_windows_portable\comfyui\output\comfyui\anima\20261010` が **0**。262 / 1 枚の内訳も DB で確認。
- **`review.json` を本物のサーバで**（`get_check_p8.py`。複製 `gui/` を 8791 で）: 先頭の資産 1 枚に `deleted_at` を立てる前後で **`review.json?scope=all`（148,387 B・263 枚）が `generated_at` を除いて完全一致**、文書中に `delet` を含む鍵は **0**、`review-export` の契約を**通る**（`jsonschema` 4.26.0）。消した資産も 263 枚の中に残る（§6.3）。
- **`GET` が書かない**: 12 本の `GET`（`health` / `stats` / `assets` / `assets/{id}` / `graph` / `tags` / `annotations` / `groups` / `tags?known=all` / `jobs` / `review.json` × 2）の前後で、複製フォルダの**全ファイルの size と mtime**と **v6 の 5 表・`decision` / `review_group` / `asset` / `asset_location` の行数**が同一。
- **契約**（`tools/check_contract_p8.py`）: **13 行すべて OK**（スキーマが draft 2020-12 として正しい・見本が通る・壊した 10 通りが落ちる・`review-export` に削除の欄が無い）。`schemas/` は 3 ファイルで **`deletion-ledger` は無い**。私の追加 12 通り（C-3）も妥当。
- **`Clock`**: `clock_of(None)` / `clock_of()` は `SYSTEM_CLOCK`、偽の時計を渡せばそれが返る（`tests/test_clock.py:41`）。`now()` は `db.now()` と同じ形の UTC 文字列、`monotonic()` は `time.monotonic()`。**ただし `src/` で `clock_of` を呼ぶのは `clock.py` 自身だけ**（P8-0 は口を足さないので妥当。注入が本当に効くかは P8-2 のサービスで決まる）。
- **実データの作業**（指示書 §2-8）: `.backup/pre-p8-0-20261017-213346/` に `db.sqlite3` 1,265,664 B（**v5**・18 表・263・3）と `p7-leftovers/` **12 ファイル・30,783 B**（`workflows/` 4: 2,374 / 2,335 / 2,398 / 5,915、`recipes/` 4 フォルダ × `manifest.json` 1,213 / 1,213 / 1,213 / 1,281 ＋ `seed-*.json` 2,378 / 2,339 / 2,402 / 5,722。記録 §3 と一致）。
  `.data/` に `workflows/` と `recipes/` は**無く**、`sidecar` 1・`export` 1・`thumbs` 297 ファイルが残る。`asset_meta.meta_json` に `workflows` / `recipes` を含む行 0、`sidecar` の JSON にも `workflow` 0。**画像 263 枚は全部ディスクにあり、263 / 263 で size と `mtime_ns` が `asset_location` と一致**、`missing_at` 0。
- **アプリ（8790）が v6 で動く**: `health` / `stats`（263 枚・`missing` 0）が 200。v5 のコードのまま v6 の DB（`current >= SCHEMA_VERSION` の早期 return）。
- **壊すと落ちる**（`mutate_p8.py` を `-p` で読み込み、ソースは触らない。31 通り）: **18 通りで狙ったテストが落ちた**（M1 / M2 / M3 / M3b / M4 / M6 / M7 / M8 / M8b / M9 / M9b / M11 / M12 / M15 / M17 / M18e / M20 / M21）。残り 13 通りは F。

### C-1 P7 が付けた `user_version = 6` の DB は P8 の表を持たない（最も重大の 2）

- 場所: `db.py:238-245`（早期 return）・`db.py:629-647`（`_top_up_v6` は列と `ix_asset_del` だけ）。設計 §0.3 L65「番号は空いている」。
- 再現: `.backup/pre-p7-removal2-20261017-032405/db.sqlite3` を `backup()` で複製 → `migrate()` × 3 → 6 / 6 / 6、`integrity` ok、FK 0、**P8 の物は `ix_asset_del` だけ**。`delete_request` / `deletion_log` / `duplicate_exclusion` / `phash_band` / `pending_delete_preview` と索引 5 本（＋自動索引 5）が無く、`recipe_*` 6 表と索引 10 本が残る。
- 影響: 利用者の控えから戻した瞬間に起きる（`.backup/` に 3 つ）。P8-4 の `restore` が「版を見て拒む」作りになっても **6 = 6 で通る**。
- 直し方: `_top_up_v6` の先頭に `con.executescript(V6_DELETE_DDL)`（`executescript` は暗黙 COMMIT なので `migrate()` と同じ流儀で呼ぶ）。これで「版 6 だが P8 の表が無い」DB も 1 回で正しい形になる。`recipe_*` 6 表は残るが害は無い（§0.3 に「P7 の控えから戻した場合は `recipe_*` が残る」と 1 行）。テストは「`user_version = 6` を先に付けた v5 の DB」で書ける（`PRAGMA user_version = 6` → `migrate()` → 5 表がある）。

### C-2 `GET /api/assets/{id}` の `deleted_at` は常に `None`（P8-2 への申し送り）

- 場所: `src/image_reviewer/store.py:465`（P5-0 の `f2a0412`。「JSON 版の形を保つための置き場」として `"deleted_at": None` を固定）。
- 再現（`get_check_p8.py`）: 複製で 1 枚に `deleted_at` を立てた後も `GET /api/assets/{id}` は `deleted_at: null`、`GET /api/assets?limit=300` にも出る。
- P8-0 の欠陥ではない（口を足していない。`review.json` は別の道で `deleted_at` を読まないので §6.1 は守られている）。**P8-2 で `row["deleted_at"]` に替えないと API が嘘をつく**。§8.1-25（一覧の既定で出さない）の実装のときに一緒に。

### C-3 契約で縛っていない物（本物の `jsonschema`。実装者の 10 通りの外に 12 通り）

| 文書 | 結果 | 判定 |
| --- | --- | --- |
| `includes.db: false` | **通る** | スキーマの説明は「`db` は必須（これが無いと復元できない）」。`const: true` にする（1 行） |
| `db_bytes: 0` | 通る | 0 バイトの DB は無い。`minimum: 1` でよい（軽微） |
| `counts.assets: 1.0` | 通る | JSON Schema の規則どおり（1.0 は integer）。欠陥ではない |
| `app_version` 空・`data_dir` 空・`includes.library` 欠け・`includes` / `counts` に知らない欄・`db_sha256` 大文字・`created_at` に小数秒 / `+09:00`・`abi` 数値 | **落ちる** | 期待どおり |

### C-4 `Clock` のテストは製品より道具を見ている

- `tests/test_clock.py:53` `test_the_fake_clock_moves_both_times_together` は**テストの中の `FakeClock`** を進めて `FakeClock` を検査している（製品の `Clock` / `clock_of` を通らない）。しかも `FakeClock.advance(sec=…, mono=…)` は**壁と単調を別々に進められる**ので、`clock.py` の docstring「2 つを別々に注入できる形にしない」を**テストの道具が破っている**。
- `Clock.monotonic` を `time.time` に替える（M16）と緑のまま（`tests/test_clock.py:31` は float と非減少しか見ない）。P8-2 で窓を作るときに「壁時計を 1 時間戻しても `remaining_sec` が変わらない」を書けば自然に埋まる。いまは軽い。

## D. 軽微

- D-1 申し送り 5「部分索引は `INDEXED BY` に `WHERE … IS NOT NULL` も書かないと使えない」は **SQLite 3.53.1 では誤り**。`… INDEXED BY ux_delete_token WHERE client_token = 'tok'` だけで通った（`=` が `IS NOT NULL` を含意する）。害は無い（書いても同じ計画）。
- D-2 申し送り 5「`allow_stage3` は `CHECK` 付きなので `DROP COLUMN` できない」も**誤り**。`ALTER TABLE root DROP COLUMN allow_stage3` は通った（列自身の `CHECK` は列と一緒に落ちる。落とせないのは**他の列を指す** `CHECK`）。よって `test_v6_topps_up_…` は `allow_stage3` の道も直接書ける（いまは M21 を `test_v6_adds_…` が捕まえるので穴ではない）。
- D-3 `tests/test_db.py:599` の「3 回呼び」は `DDL` の後に `user_version = 4` を付けて始めるので **v4 → v6 の道**。v1 → v6 は私の `paths.py` でしか通していない（結果は同一）。docstring の「v5 から 1 回で」（L580）も実際は新規の道。
- D-4 `tools/p8_0_real_data.py` は一度きりの作業なのに `tools/` にコミットされ、`C:\work\image-reviwer\...` の絶対パスを 3 つ埋め込む。再実行すると控えのフォルダが増え `allow_stage3` を立て直す（害は無い）。`.tmp-audit-redo/` か記録の中の手順に置く方が家風。
- D-5 実データの v6 は **WAL（251,352 B）に乗ったまま**（`db.sqlite3` 本体は 03:24 のまま）。アプリが握っているので正常。次の checkpoint で本体に入る。控え `pre-p8-0` は v5 なので、やり直しが要れば同じ道を通れる。
- D-6 `phash_band.value` は「16 進 2 文字（小文字）」と DDL のコメントにあるが縛りは無い（`'zz'` / `'FF'` が入る）。`delete_request.count` / `pending_delete_preview.count, bytes` / `deletion_log.remaining_sec, size` に負が入る。P8-1 / P8-2 のサービス層で守る（表に `CHECK` を足すなら**いま**。表は空）。
- D-7 `deletion_log.id` などの `TEXT PRIMARY KEY` は NULL を受ける（既存の表と同じ前提。`db.ulid()`）。
- D-8 実装の記録 §2「24 表」は `sqlite_sequence` 込み（利用者の表は 23）。
- D-9 `GET /api/requests` は 404（正しい道は `/api/review-requests` で 200）。P7-0 の監査スクリプトから写した列挙の名残りで、P8-0 とは無関係。

## E. 設計とのずれ（実装が決めた所を含む）

| # | 設計 | 実装 | 判定 |
| --- | --- | --- | --- |
| E-1 | §2.1 L425 `ux_request_token` → `ux_delete_token`（実装者が直した） | `ux_delete_token`（`db.py:513`） | **実装が正**。罠は実測で本物（C-0）。ただし置換が **§2.2 L481 と §8.1 の 3 行目 L680 にコメントごと流れ込み**、本文の中に「`ux_delete_token   -- **索引名は DB 全体で一意**（…＝穴が開く)`」が残っている。2 行を `ux_delete_token` だけに直す |
| E-2 | §0.3 L49「**4 表**を新設」・§0.1 L22 の P8-0 の行（4 表の列挙に `delete_request` が無い）・§9 L741「4 表」 | 5 表 | P7-0 の E-3 と同じ型。点検 A2 で足した `delete_request` が一覧に追従していない。3 か所を「5 表」に |
| E-3 | §2.1 に `ix_asset_del` の `CREATE INDEX` が無い（§0.3 / §9 に名前だけ）。`root` の `ALTER` は §0.3 だけ | `db.py:642`・`:646` | 実装は §0.3 / §9 のとおり。§2.1 に 2 文を足して「DDL は §2.1 が正」を保つ |
| E-4 | §0.3 L65「P7 の `_top_up_v6` は無い。作り直さない」 | `_top_up_v6` を作った（決定 2） | **妥当**（列は `ALTER` で足すので冪等性が要る。M7 / M17 / M21 で守られている）。設計の 1 行を「`_top_up_v6` は列（と `ix_asset_del`）を補う」に。C-1 の 1 行も足す |
| E-5 | 指示書 §手順-5「実データは v5 のまま」と §やること-9「`allow_stage3` の 1 は P8-0 で立てる」 | 実データを v6 に上げた（決定 3） | **妥当**（列が無ければ立てられない。指示書が自己矛盾）。アプリが v5 のコードで v6 の DB を読んでも問題ないことは私も確認（C-0） |
| E-6 | §2.1 の並び（`deletion_log` → `delete_request`） | `delete_request` → `deletion_log` | SQLite は `REFERENCES` の先が後でも作れるので意味の差は無い。実装の並び（参照先が先）の方が読みやすい。どちらかに揃える（軽微） |
| E-7 | — | `tools/check_contract_p8.py` を新設（決定 4） | 妥当。P7 の物は P7 と一緒に消えている（`git log` で確認） |
| E-8 | — | 申し送り 5 の 2 つの理由（決定 5） | **理由が誤り**（D-1・D-2）。結論（`IS NOT NULL` を書く・`deleted_at` で代表）は害が無い |

## F. テストで守れないもの（`mutate_p8.py`。31 通り、ソースは触らず `-p` で差し替え）

| 壊し方 | 判定 | 根拠と直し方 |
| --- | --- | --- |
| **M5** `CHECK (band BETWEEN 0 AND 7)` を外す | **落ちない**（65 passed） | **F-1**。`tests/test_db.py:676` の `asset_id='a'` は存在しないので FK が先に落ちる。実在の `asset` を 1 行入れてから `band=8` を試す |
| **M1b** `delete_request` の `stage` の `CHECK` だけ外す | 落ちない | `delete_request` に語彙外を入れる試験が無い |
| **M4b** `delete_request` の `actor` の `CHECK` だけ外す | 落ちない | 同上 |
| **M4c** `duplicate_exclusion` と `pending_delete_preview` の `actor` の `CHECK` を外す | 落ちない | `actor='robot'` は `deletion_log` でしか試していない。4 表 × 2 語彙を表で回す 1 テストに |
| **M14** `deletion_log.request_id` の `REFERENCES` を外す | 落ちない | **F-2**。`request_id='nope'` → FK／参照のある要求の削除 → FK を足す |
| **M19** `phash_band` の `PRIMARY KEY (asset_id, band)` を外す | 落ちない | 同じ `(asset_id, band)` の 2 行目が落ちる試験を足す（P8-1 の埋め直しで必ず踏む） |
| **M18a〜d** `ix_deletion_asset` / `ix_deletion_request` / `ix_phash_band` / `ix_preview_expiry` を 1 本ずつ外す | 落ちない | `_dump` の比較は両方の道が同じ DDL から作られるので捕まえない。`sqlite_master` の索引名 6 本を**定数と**比べる 1 テスト（P7-0 の F の最後と同じ指摘） |
| **M16** `Clock.monotonic` を `time.time` にする | 落ちない | C-4。P8-2 で窓のテストを書くときに埋まる |
| M10 `ux_delete_token` の `WHERE` を外す（全体の UNIQUE） | 落ちない | SQLite は全体の UNIQUE でも NULL を区別するので**挙動が同じ**（等価変異）。穴ではない |
| M13 `ix_deletion_pending` の `WHERE stage = 3` を外す | 落ちない | 全体の索引でも `EXPLAIN` に出る（等価に近い）。部分索引であることを見るなら `PRAGMA index_list` の `partial` 列 |
| M1 / M2 / M4 / M6（`stage` 全部・`a_id < b_id`・`actor` 全部・`allow_stage3`） | 落ちる | `test_v6_check_constraints_reject_the_wrong_vocabulary` |
| M3 / M3b / M12 / M18e（`ux_delete_token` を外す・名前を `ux_request_token` に戻す・`ix_asset_del` の `WHERE`・`ix_deletion_pending` そのもの） | 落ちる | `test_v6_partial_indexes_are_used`（M3b は `INDEXED BY` の `no such index`） |
| M7 / M11 / M17 / M21（早期 return から `_top_up_v6` を外す・`ix_asset_del` を作らない・`deleted_at` を足さない・`allow_stage3` を足さない） | 落ちる | `test_v6_topps_up_…` / `test_v6_adds_…` |
| M8 / M8b（`review.json` に `deleted_at` を足す・段 1 の資産を外す） | 落ちる | M8 は 12 件（契約の `additionalProperties: false` でも落ちる）、M8b は `test_review_json_does_not_carry_deletion_fields` だけ |
| M9 / M9b / M15 / M20（CASCADE を外す・`REFERENCES` を外す・`clock_of` の既定を外す・`pending_delete_preview` の表を消す） | 落ちる | 期待どおり |

## G. 依頼者への質問（推奨つき。待たずに推奨で進めてよい）

| # | 論点 | 選択肢 | 推奨 |
| --- | --- | --- | --- |
| G-1 | C-1 の直し方 | (a) `_top_up_v6` で `V6_DELETE_DDL` も当てる / (b) P7 の控え 3 つを「v6 と名乗るが P7」と知った上で放置し、P8-4 の `restore` で `recipe_record` の有無を見て拒む | **(a)**。1 行で、テストも 1 本。(b) は復元の口に P7 の知識を残す |
| G-2 | D-6 の負の数と `phash_band.value` の形を表で縛るか | (a) いま `CHECK (count >= 0)` 等を足す（表は空） / (b) サービス層だけ | **(a)**。家風（語彙は表でも守る）と「`CHECK` は `ALTER` で足せない」から、**表が空の P8-0 が唯一の安い機会**（P7-0 の C-1 と同じ理屈）。`value` は `CHECK (length(value) = 2 AND value = lower(value))` 程度 |
| G-3 | 契約 `includes.db` | (a) `const: true` / (b) boolean のまま | **(a)**。説明と一致させる |
| G-4 | `tools/p8_0_real_data.py` の置き場（D-4） | (a) `.tmp-audit-redo/` に移して記録 §3 に手順を残す / (b) `tools/` のまま | **(a)**。一度きりの物を道具箱に置かない |
| G-5 | 設計の字の直し（E-1〜E-4）をいつやるか | (a) P8-1 の設計反映と一緒 / (b) いま | **(b)**。E-1 は本文が壊れている（読めない）ので早い方がよい |

## H. 確かめられなかったこと・注記・後始末

**確かめていない**

- ComfyUI は触っていない（P8-0 に要素が無い）。
- 性能は測っていない（表と索引だけ。v5 → v6 の移行は複製 1.2 MB で体感 0 秒）。
- `restore` の CLI は無い（P8-4）ので、C-1 の「控えから戻す」は `backup()` で複製して `migrate()` を呼ぶ形で再現した。
- `Clock` を注入する**サービス**がまだ無いので、注入が「効く」ことは `clock_of` の返り値でしか確かめられない（C-0）。
- 利用者のアプリ（8790）が次に立ち上がるときの道は、実データ（v6）の複製で `migrate()` が早期 return して不変になることで代えた。

**紛らわしい出力の注記**

- `constraints.out.txt` / `ddl_diff.out.txt` の日本語は cp932 の化け（`python -I` が `PYTHONUTF8` を無視した）。結果は英語の `IntegrityError` の文で読める（C-0 の表に写した）。
- `mutations.out.txt` の M7 / M11 / M17 / M21 の行頭に test のコメント行が混ざっているのは `grep` の拾いすぎ。判定は末尾の `N failed, M passed`。
- サーバ 8791 は `taskkill` で止めたので `server.log` の末尾は途切れているが、クラッシュではない（12 本の `GET` と 6 画面に応えた後）。

**実行したコマンドと結果（再現手順）**

```powershell
cd C:\work\image-reviwer; $env:UV_CACHE_DIR = "C:\work\image-reviwer\.uv-cache"; $env:PYTHONUTF8 = "1"
uv run --no-sync pytest -q                                               # 296 passed × 3（13.39 / 13.29 / 13.49 s）
node tools/gui_smoke.mjs                                                 # すべて ok（ok の行 129）
uv run --no-sync --with jsonschema python tools/check_contract_p8.py     # jsonschema 4.26.0 / 13 行すべて OK
.venv\Scripts\python.exe -X utf8 .tmp-audit-redo\p8-0-audit\ro_check.py  # 実データ mode=ro: v6・23 表・263・3・FK 0・quick/integrity ok・allow_stage3 1/0・画像 263/263 一致
.venv\Scripts\python.exe -X utf8 .tmp-audit-redo\p8-0-audit\paths.py     # 新規 / v1 / v3 / v5 / 実データ v6: sqlite_master 同一・3 回不変／P7 の v6: P8 の表が無い（C-1）／top-up・DROP COLUMN
.venv\Scripts\python.exe -X utf8 .tmp-audit-redo\p8-0-audit\constraints.py   # CHECK 13 通り・ux_delete_token・FK・CASCADE・EXPLAIN 9 本・IF NOT EXISTS の罠
.venv\Scripts\python.exe -X utf8 .tmp-audit-redo\p8-0-audit\ddl_diff.py      # 設計 §2.1 の 12 文はすべて実装にある。5 表の列が 1 対 1
bash .tmp-audit-redo\p8-0-audit\mut_run.sh                                   # 31 通り（PYTHONPATH=.tmp-audit-redo\p8-0-audit、-p mutate_p8、P8X=M1..M21）→ 18 落ちる・13 緑（F）
.venv\Scripts\python.exe -X utf8 .tmp-audit-redo\p8-0-audit\gui_setup.py     # 複製 gui/（backup() + sidecar/export/thumbs）＋ まとまり 1 ＋ 語 4
$env:IMAGE_REVIEWER_DATA = "C:\work\image-reviwer\.tmp-audit-redo\p8-0-audit\gui"; uv run --no-sync image-reviewer serve --port 8791
uv run --no-sync --with jsonschema python -X utf8 .tmp-audit-redo\p8-0-audit\get_check_p8.py   # GET 12 本で不変・deleted_at 前後で review.json 一致・契約 OK・/api/assets/{id} は deleted_at: null（C-2）
node tools/gui_layout.mjs --base http://127.0.0.1:8791 --count 8 / --screen requests / group --group 01M54YAFNX8V6VMY5PKAVC8ZXF / asset --ids 01M4Z0KJS58V2SAJBGTG1TRFK5 / tags / jobs   # 6 画面すべて ok
taskkill /PID 41244 /F /T                                                # netstat で 8791 の LISTENING 0 本。8790 は health 200 のまま
```

**後始末**

- 残した物: `.tmp-audit-redo/p8-0-audit/`（複製 `paths/` 8 つ・`gui/`・スクリプト 8 本・出力 7 本。約 12 MB）。実装者の `.tmp-audit-redo/p80/` は触っていない。消してよい。
- 消した物: 無し。サーバ 8791 は停止。
- `.data/` の size と mtime は不変（上の一覧）。`src/` / `schemas/` / `tests/` / `tools/` / `docs/` に監査中の変更は無い（`git status` は本報告だけ）。

---

## 最も重大な 3 件（再掲）

1. **F-1** `band` の `CHECK` のテストは存在しない `asset_id` で FK が先に落ちているので、`CHECK` を外しても緑。`delete_request` / `duplicate_exclusion` / `pending_delete_preview` の `CHECK` も未試験。実在の行で 4 表 × 語彙を回す。
2. **C-1** P7 が `user_version = 6` を付けた控え（`.backup/pre-p7-*` の 3 つ）から戻すと P8 の 5 表が一生作られない。`_top_up_v6` で `V6_DELETE_DDL` も当てる（1 行）。
3. **F-2** `deletion_log.request_id` の FK・`phash_band` の主キー・平の索引 4 本にテストが無く、外しても緑。`constraints.py` の 3 行を写す。
