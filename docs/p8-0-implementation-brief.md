# P8-0（表と契約。機能を足さない）の実装の指示書

あなたはこのプロジェクトの実装者（DeepSeek 側）です。**P8-0** を実装してください。**機能は足しません**（表・契約・移行・掃除だけ）。

## 最初に読むもの
1. **`C:\Users\yukse\.agents\skills\image-reviewer-dev\SKILL.md`**（**必ず読む**）
2. **`docs/p8-design.md`（837 行）** — **§0 が拘束力のある差分**。とくに **§0.1（段の分け方。P8-0 の行）/ §0.3（v6 で足す物）/ §2.1（DDL。**4 表＋2 列**）/
   §0.6・§0.7（安全規則） / §0.14（利用者の回答 Q1〜Q8）/ §0.16（点検で確定したこと）/ §2.3 / §3.3（`root` の印）/ §6（契約）/ §8.1（P8-0 のテスト）/ §9（P8-0 の行）**
3. `docs/p8-review-report.md`（点検）と `docs/p8-review-triage.md`（仕分け）
4. 既存のコード: **`src/image_reviewer/db.py`**（**v5 までの移行の書き方**。`SCHEMA_VERSION` / `_migrate_vN` / `PRAGMA table_info` を見てから `ALTER`）・
   `tests/test_db.py`（**v5 のテストの形**）・`store.py`（`normalize_path` / `is_under`）・`export.py`

## やること（**設計 §9 の P8-0 の行＋仕分けの「次に P8-0 で実装する物」10 項目**）
1. **`SCHEMA_VERSION = 6`** と **`_migrate_v6()`**（**v5 から 1 回で**・**3 回呼んでも同じ**・**v1 / v3 / v5 の道が同じ `sqlite_master` になる**）。
   **既存の版の移行は触らない**（`SCHEMA_VERSION = 6   # v6 = P8` の注記。**P7 の v6 はもう無い**ことを 1 行）。
2. **`asset.deleted_at`**（列）＋**部分索引 `ix_asset_del`**。
3. **`root.allow_stage3`**（`INTEGER NOT NULL DEFAULT 0 CHECK (allow_stage3 IN (0,1))`。**`PRAGMA table_info` を見てから `ALTER`**＝冪等）。
4. **4 表**: `deletion_log` / **`delete_request`**（`client_token` は**要求の単位**で部分 UNIQUE） / `duplicate_exclusion`（**`CHECK (a_id < b_id)`**） /
   `phash_band` / `pending_delete_preview`（**`items_json` に `path`（正規化した鍵）と `display_path` の両方**）。
   **`CHECK` は `ALTER` で足せない**ので**新表に最初から**。**部分索引**（`WHERE ... IS NOT NULL`）。
5. **契約 `schemas/backup-manifest.schema.json`**（**設計 §6.1 のとおり**。**`deletion-ledger` は作らない**＝**契約は 1 つ**）。
6. **`review.json` を変えない**ことを**テストで固定**（`tests/test_export.py`。**`deleted_at` を足しても `review.json` の形は変えない**）。
7. **`Clock` の土台**（`now()` と `monotonic()` を**1 つの口**から。**テストから注入できる**形。`getattr(clock, ...)` で既定）。
8. **P7 の残骸の掃除**（**実データ**）: `<data>/workflows/` の **4 ファイル**と `<data>/recipes/` の **4 フォルダ**。
   **控えを取ってから**（`sqlite3` の `backup()` ではないので、**ファイルを `.backup/pre-p8-0-<日時>/` に複写**してから）消し、
   **消した一覧（パスとサイズ）を報告に書く**。**実データの DB は触らない**（P8-0 の移行は**アプリを起動したとき**に走る。
   **ただし `root.allow_stage3` の 1 は P8-0 で立てる**——**利用者の回答 Q8**）。
9. **実データの `illust-authoring` の置き場に `allow_stage3 = 1` を立てる**（**利用者の決定 Q8**。**控えを取ってから**。
   **どの行を立てたかを報告に書く**。**263 枚のうち 262 枚がそこにある**）。
10. **テスト**（**§8.1 の P8-0 の担当**＋**§8.4 の F のうち P8-0 の分**）: 移行の 4 つの道・3 回呼び・`CHECK` が効く（`stage=4` / `(B,A)` / `allow_stage3` の語彙外）・
    部分索引が引かれる（`EXPLAIN QUERY PLAN`）・`review.json` 不変・`Clock` の注入。**「壊すと落ちる」形**（**壊して落ちるのを見てから戻す**）。

## 手順（**この順で**）
1. **控え**: 実データの DB を `.backup/pre-p8-0-<YYYYMMDD-HHMMSS>/db.sqlite3` に `backup()` で（**WAL を畳む**）。
   **P7 の残骸のファイルは別の控え**（`.backup/pre-p8-0-<日時>/p7-leftovers/`）。
2. `db.py` の移行と表（**コード**）
3. 契約（`schemas/`）
4. テスト
5. **検証**: `pytest`（**全件緑**・複数回）／`gui_smoke`／`gui_layout`（**6 画面**）／**v5 の複製で v6 に上がる**（263 枚・判断 3 件・`integrity` ok・FK 違反 0）／
   **`review.json` が変わらない**／**実データは v5 のまま**（**P8-0 では実データの DB を上げない**。**上げるのは `allow_stage3` の 1 だけ**）
6. **実データの掃除**（P7 の残骸）と **`allow_stage3`**（**控えを取ってから**）
7. **アプリは再起動しない**（親がやる）

## 守ること
- **`uv run` は `--no-sync`**。`$env:UV_CACHE_DIR = "C:\work\image-reviwer\.uv-cache"`。
- **実データ `.data/` は `mode=ro` のみ**（**書いてよいのは「P7 の残骸の削除」と「`allow_stage3 = 1`」だけ**。**どちらも控えを取ってから**）。
- **ComfyUI は触らない**（この段は使わない）。
- **`git` のコミットはしない**（親がやります）。**README と `docs/design.md` は触らない**（**`docs/p8-0-implementation.md` は新規で作る**）。
- **設計に無い仕様を発明しない**（必要なら報告に書く）。

## 返すもの（最終応答）
1. 触ったファイルと行数
2. `pytest`（件数。**複数回**）・`gui_smoke`・`gui_layout` の結果
3. **移行の 4 つの道**（新規・v1・v3・v5 の複製）が**同じ `sqlite_master`** になる結果と、263 枚・判断 3 件・FK 違反 0
4. **`CHECK` と部分索引が効く**こと（実行した結果）
5. **消した P7 の残骸の一覧**（パスとサイズ）と**控えの場所**
6. **`allow_stage3` を立てた行**（置き場のパス）と控えの場所
7. 契約（`backup-manifest`）を**本物の `jsonschema`** で通した結果
8. 設計からずれた所／自分で決めた所（1 行ずつ理由）と、気づいた設計の穴
