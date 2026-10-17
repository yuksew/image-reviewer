# P8-0 の監査の仕分け（条件 3 件をどう直したか）

- 監査: [`p8-0-audit-report.md`](p8-0-audit-report.md)（**判定: 合格（条件つき）**。条件は 3 つ）
- 直したのは P8-1 の最初（この段の担当）。**すべて実行で「壊すと落ちる」を確かめた。**

| # | 条件 | どう直したか | 壊すと落ちる（自分で確認） |
| --- | --- | --- | --- |
| **F-1** | `band` の `CHECK` のテストが**空振り**（`asset_id = 'a'` が存在しないので **FK が先に落ちる**）。`delete_request` の `stage` / `actor`・`duplicate_exclusion` と `pending_delete_preview` の `actor` も未試験 | `tests/test_db.py` の `test_v6_check_constraints_reject_the_wrong_vocabulary` を書き直し、**実在の `asset`（'a1'）を入れてから** `phash_band` に入れる形に。**未試験だった 4 つの `CHECK` も同じテストで見る**（`delete_request` の `stage` / `actor`・`duplicate_exclusion` の `actor`・`pending_delete_preview` の `actor`） | `band … CHECK (band BETWEEN 0 AND 7)` の字を外す → **1 failed**（前は緑だった） |
| **C-1** | **P7 が `user_version = 6` を付けた DB**（控え `.backup/pre-p7-*`）は `migrate()` の**早期 return** に当たり、**P8 の 5 表を一生持たない**（版は 6 と答えるので気づきにくい） | `db._top_up_v6` の**先頭で `V6_DELETE_DDL` を流す**（全部 `IF NOT EXISTS` なので冪等。`_migrate_v6` と二重でも同じ）。**`tests/test_db.py` に `test_v6_tables_are_added_to_a_p7_style_v6_database`** を足し、「版だけ 6 で 5 表が無い DB」を合成して `migrate()` で表が入る・**2 回呼んでも増えない**ことを固定 | `_top_up_v6` の `con.executescript(V6_DELETE_DDL)` の行を消す → **1 failed** |
| **F-2** | `deletion_log.request_id` の FK・`phash_band` の主キー・**平の索引 4 本**にテストが無い（v5 の道と新規の道の `sqlite_master` を比べるだけでは、**両方から同じ物を落とすと気づけない**） | `tests/test_db.py` に `test_v6_foreign_keys_and_indexes_are_declared` を足した。**知らない `request_id` は FK で落ちる**・**参照のある `delete_request` は消せない**・**同じ `(asset_id, band)` を 2 行入れられない**・**平の索引 4 本を `INDEXED BY` で引く**（索引が無ければ SQLite がエラーにする＝存在と使えることの両方） | `ix_phash_band` の `CREATE INDEX` を消す → **1 failed** |

- **テストは 296 → 298 passed**（P8-0 の時点）→ **P8-1 の実装で 314 passed**。
- **設計の訂正は無し**（監査の条件はどれも「テストと早期 return の穴」で、設計の記述は正しかった）。
