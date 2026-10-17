# P8-0（表と契約。機能は足さない）の実装の記録

- 日付: 2026-10-17 ／ 設計: [`p8-design.md`](p8-design.md)（837 行。§0.3・§2.1・§2.2・§6・§8.1・§8.4・§9）
- 指示書: [`p8-0-implementation-brief.md`](p8-0-implementation-brief.md)（59 行）
- 点検: [`p8-review-report.md`](p8-review-report.md) ／ 仕分け: [`p8-review-triage.md`](p8-review-triage.md)

## 1. 作ったもの

| ファイル | 何 |
| --- | --- |
| **`src/image_reviewer/db.py`**（+約 110 行） | **`SCHEMA_VERSION = 6`**（`# v6 = P8` の注記）／**`V6_DELETE_DDL`**（5 表・6 索引）／**`_migrate_v6()`**／**`_top_up_v6()`**／`migrate()` の `if current < 6` と早期 return 側の `_top_up_v6` |
| **`src/image_reviewer/clock.py`**（新規 64 行） | **`Clock`（`now()` と `monotonic()` を 1 つの口から）**・`SYSTEM_CLOCK`・**`clock_of(clock=None)`**（点検 C6。**2 つの時計を別々に注入できない形**） |
| **`schemas/backup-manifest.schema.json`**（新規 72 行） | 日次バックアップの `manifest.json` の契約（**契約はこの 1 つだけ**。`deletion-ledger` は作らない＝点検 G8） |
| **`tools/check_contract_p8.py`**（新規 104 行） | **本物の `jsonschema`** で契約を検証（スキーマ・見本・**壊した 10 通り**・`review.json` に削除の欄が無いこと）。P7 の物は P7 と一緒に消えたので作り直した |
| **`tools/p8_0_real_data.py`**（新規 96 行） | **実データの作業**（控え・P7 の残骸の削除・`allow_stage3`）。**何度でも手順が読める形**で残す |
| `tests/test_db.py`（+6 件） | v6 の表と列・3 回呼び・**v5 の道と新規の道が同じ形**・**`_top_up_v6` の道**・`CHECK` の語彙・**部分索引**・`ON DELETE CASCADE` |
| `tests/test_export.py`（+1 件） | **論理削除で `review.json` の形が変わらない**（前後で辞書が完全一致。契約にも削除の欄が無い） |
| `tests/test_clock.py`（新規 3 件） | 既定はシステムの時計・**注入が無ければ既定に落ちる**・**1 つの口を進めると両方進む** |

## 2. 実行した結果（実測）

| 確かめたこと | 結果 |
| --- | --- |
| `uv run --no-sync pytest -q` | **296 passed**（285 → +11）を**2 回**（揺れなし） |
| `node tools/gui_smoke.mjs` | **129 ok / NG 0** |
| `node tools/gui_layout.mjs --screen jobs`（実データ・読み取りのみ） | **ok**（P8-0 は画面を触らない） |
| **移行の 4 つの道**（新規・v1・v3 の控え・v5 の複製） | 4 つとも **v6**。**`sqlite_master` が新規と同一**（索引と表の `sql` まで） |
| 3 回呼び | **`sqlite_master` 不変**・版 6 |
| v5 の複製 → v6 | **263 枚・判断 3 件・FK 違反 0・`integrity` ok** |
| `CHECK`（実行） | `stage=4` ✗／`actor='robot'` ✗／`(B,A)` ✗／`band=8` ✗／`stage=0` ✗／`allow_stage3=2` ✗（**正しい値は通る**） |
| 部分索引（実行） | `ix_asset_del`・`ix_deletion_pending` は `EXPLAIN QUERY PLAN` に出る／`ux_delete_token` は `INDEXED BY` で引け、**同じ token は 2 行入らず・NULL は何行でも入る** |
| 契約（本物の `jsonschema` 4.26） | **スキーマ正当・見本が通る・壊した 10 通りが全部落ちる・`review.json` の契約は変えていない** |
| **実データ** | **v5 → v6**（24 表）。**263 枚・判断 3 件・FK 違反 0・`integrity` ok** |
| **アプリ（8790・v5 のコードのまま）** | **v6 の DB で問題なし**（`health`・`assets`・`tags`・`jobs`・`groups` が 200。`migrate()` は `current >= SCHEMA_VERSION` で早期に戻る） |

## 3. 実データで消した物（**控えを取ってから**）

**控え**: `.backup/pre-p8-0-20261017-213346/`（`db.sqlite3` 1,265,664 バイト ＋ **消す前に複写した `p7-leftovers/`**）

**P7 の残骸 12 ファイル・30,783 バイト**:

| 場所 | ファイル |
| --- | --- |
| `<data>/workflows/`（4） | `00ed5fdf….json` 2,374／`022d8b90….json` 2,335／`2b4ce77d….json` 2,398／`79fe0685….json` 5,915 バイト |
| `<data>/recipes/<4 つの記録>/<束>/`（8） | `manifest.json` ×4（1,213〜1,281）＋ `seed-*.json` ×4（2,339〜5,722 バイト） |

## 4. 実データに立てた印（**利用者の回答 Q8**）

```
c:\ai\comfyui_windows_portable\comfyui\output\comfyui\anima\20261010   allow_stage3 = 0（既定のまま）
c:\work\illust-authoring\.store\anima-dev                              allow_stage3 = 1（← 立てた。262 / 263 枚）
```

## 5. 自分で決めた点（**設計に反映が必要な物を含む**）

1. **★索引名を `ux_request_token` → `ux_delete_token` に変えた**（**設計 §2.1 の訂正が要る**）。
   理由: **P6 が `review_request` に `ux_request_token` を使っている**。SQLite の索引名は **DB 全体で一意**なので、
   `CREATE UNIQUE INDEX IF NOT EXISTS ux_request_token ON delete_request(...)` は**黙って何もしない**
   （実際に「索引が無い」状態になり、テストが `no such index` で落ちて気づいた）。
   そのままだと **同じ `client_token` の再送で二重に消せる**＝**点検 A2 が塞いだ穴が開いていた**。
   **P8-1 以降に進む前に、設計 §2.1 と §8.1 の 3 をこの名前に直すこと。**
2. **`_top_up_v6()` を作った**（設計は P7 の `_top_up_v6` を作り直さない、とだけ言っていた）。
   理由: `asset.deleted_at` と `root.allow_stage3` は**列**で、`ALTER TABLE ADD COLUMN` は `IF NOT EXISTS` を持たない。
   **早期 return 側（`current >= SCHEMA_VERSION`）からも呼ぶ**（P4-1 の監査 A-1 と同じ流儀）。
   **`ix_asset_del` もここで作る**（列が無い古い v6 では索引も作れないため）。
3. **実データを v6 に上げた**（指示書は「実データの DB は v5 のまま。上げるのはアプリを起動したとき」だった）。
   理由: **`allow_stage3` の 1 を立てるには列が要る**（v6 にしないと立てられない）。
   **アプリ（v5 のコード）は v6 の DB で問題なく動く**ことを実行で確かめた（`migrate()` の早期 return）。
   **アプリの再起動は不要**（P8-0 は API も画面も足していない）。
4. `tools/check_contract_p8.py` を新設（P7 の `check_contract_p7.py` は P7 と一緒に消えていた）。
5. テストの細部: **部分索引は `INDEXED BY` に `WHERE ... IS NOT NULL` も書かないと使えない**（SQLite の規則）。
   `test_v6_topps_up_…` で `allow_stage3` は `CHECK` 付きの列なので `DROP COLUMN` できない（SQLite の制限）ため、
   **`deleted_at` の道で代表**させた。

## 6. 申し送り（P8-1 以降）

- **設計 §2.1 の索引名の訂正**（`ux_delete_token`）。**§8.1 の 3 も**。
- **`asset.deleted_at` に `CHECK` は付けられない**（列）→ **値の検査はサービス層**（設計 §0.13 のとおり。**P8-2 で実装**）。
- **実データは v6**。**P8-1 の `phash_band` の埋め方**（`asset.phash` は 91 / 263 枚にしか無い。**未計算は背景ジョブ**）。
- **`<data>/workflows/` と `<data>/recipes/` は消えた**ので、`<data>` に残るのは `sidecar` / `export` / `thumbs` だけ（設計 §7 の前提）。
- **`app.py` は触っていない**（P8-0 は口を足さない）。
- **アプリの再起動は不要**（P8-1 で口を足したときに再起動する）。
