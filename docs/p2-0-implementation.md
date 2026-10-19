# P2-0（スキーマ v7 = 取り込みとカタログ）の実装の記録

- 日付: 2026-10-20 ／ **P2（取り込みとカタログ）の最初の小段**。**画面は作らない・口も作らない**（表と列だけ）
- 設計: `docs/design.md` **§5.3**（`folder` / `folder_member`）・**§6.1**（カタログの口）・
  **§10.1〜§10.2**（仮想フォルダとスマートフォルダ）・**§5.1**（取り込み元の `source` / `source_url` /
  `ref_tags`）・**§14**（P2 の行）・**§16.x**（過去の決定）
  - **`docs/p2-design.md` は無い**（P2 の設計書はまだ書かれていない）。したがって**本文の `design.md` が正**。
- 前例: `docs/p8-design.md` §2.1（DDL の書き方）・`docs/p8-0-implementation.md`（P8-0 のやり方）・
  `src/image_reviewer/db.py` の v6 までの移行・`tests/test_db.py`
- 環境: `$env:UV_CACHE_DIR = "C:\work\image-reviwer\.uv-cache"`、`uv run` はすべて `--no-sync`。
  実データ `.data` は **`mode=ro` だけ**。移行と壊す試験は**複製**（`sqlite3` の `backup()`）。
  **`IMAGE_REVIEWER_DATA` を付けずにアプリを起動していない**（`create_app()` が断るので起動できない）。

---

## 0. 先に読むべき結論（**指示書のスケッチと設計が食い違った 4 点**）

指示書（P2-0 の依頼）には `folder_item` / `smart_folder` / `name`（一意）/ `note` / `sort_key` /
`asset.source_ref` と書いてあったが、**`design.md` の字と食い違う**。指示書自身が
「設計 §5.3 の字に従う」「設計に欄があるならその形で」と言っているので、**設計を採った**。

| # | 指示書のスケッチ | 設計の字（採った） | 根拠 |
| --- | --- | --- | --- |
| 1 | 表 `folder_item` | **`folder_member`**（`folder_id` / `asset_id` / `position` / `added_at`。主キー `(folder_id, asset_id)`） | `design.md` §5.3・§10.1 |
| 2 | 表 `smart_folder`（`query_json`） | **別表を作らない。`folder.kind='smart'` の行**で、条件は `folder.smart_query`（JSON） | §5.3・§10.2（`kind='manual'\|'smart'`） |
| 3 | `folder.name` は一意・`note`・`sort_key` | **`name` に UNIQUE は無い**・`note` / `sort_key` は無い（並びは `position`）。**階層 `parent_id`** がある | §5.3・§6.1・§10.1 |
| 4 | 取り込み元 `asset.source_ref` | **`asset` に `source_ref` は無い**（`source_ref` は `review_group` の列で、要求 ID などの意味）。**設計の取り込み元は `asset.source`（`scan\|drop\|clipboard\|url\|watch`）と `asset.source_url`、`ref_tags`**。**取り込みの履歴の表は設計に無いので作らない** | §5.1・§5.2（`review_group.source_ref`） |

**この 4 点を「設計の穴」ではなく「指示書のスケッチの方が古い」として処理した。** 設計の方を変える必要は
生じていない（P2-1 の口 `POST /api/folders {parent_id, name, kind}` はこの形でそのまま作れる）。
**ただし 1 つだけ設計の穴が在った**（§7-1）: §6.1 が「既定は論理削除（`folder.deleted_at`）」と決めているのに、
§5.3 の DDL にその列が無い。**列を足した。**

---

## 1. v7 の DDL（表・索引・外部キー）

`src/image_reviewer/db.py` の `V7_CATALOG_DDL`（新規 DB も v6 からの移行も**同じ DDL**を通る）:

```sql
-- 仮想フォルダ（設計 §5.3）。実ファイルは動かさない（§10.1）。kind='smart' は条件で貯まる
CREATE TABLE IF NOT EXISTS folder (
  id              TEXT PRIMARY KEY,                          -- ULID
  parent_id       TEXT REFERENCES folder(id) ON DELETE CASCADE,   -- NULL = 根
  name            TEXT NOT NULL,                             -- **一意ではない**（親が違えば同名可）
  kind            TEXT NOT NULL CHECK (kind IN ('manual', 'smart')),
  smart_query     TEXT,                                      -- kind='smart' の条件（JSON。§10.2）
  position        INTEGER NOT NULL DEFAULT 0,                -- 同じ親の中の並び
  count_cache     INTEGER,                                   -- 中の枚数（概算のキャッシュ。§10.2）
  count_cached_at TEXT,
  created_at      TEXT NOT NULL,
  deleted_at      TEXT                                       -- ★ §5.3 に無い。§6.1 の論理削除（設計の穴）
);
CREATE INDEX IF NOT EXISTS ix_folder_parent ON folder(parent_id, position);

-- 多対多（設計 §5.3・§10.1）。同じ画像を複数のフォルダに置ける。主キーは 2 つ
CREATE TABLE IF NOT EXISTS folder_member (
  folder_id TEXT NOT NULL REFERENCES folder(id) ON DELETE CASCADE,
  asset_id  TEXT NOT NULL REFERENCES asset(id) ON DELETE CASCADE,
  position  INTEGER NOT NULL DEFAULT 0,                      -- フォルダの中の並び
  added_at  TEXT NOT NULL,
  PRIMARY KEY (folder_id, asset_id)
);
CREATE INDEX IF NOT EXISTS ix_folder_member_asset ON folder_member(asset_id);
```

`asset` に足す列（`V7_ASSET_COLUMNS`。`ALTER TABLE` は `PRAGMA table_info` を見てから）:

```sql
ALTER TABLE asset ADD COLUMN source TEXT NOT NULL DEFAULT 'scan'
  CHECK (source IN ('scan', 'drop', 'clipboard', 'url', 'watch'));   -- §5.1
ALTER TABLE asset ADD COLUMN source_url TEXT;                        -- §5.1（URL から取り込んだ出所）
ALTER TABLE asset ADD COLUMN ref_tags TEXT;                          -- §5.1（「何の参考か」の JSON 配列）
```

### 設計 §5.3 との対応

| 設計 §5.3 の字 | 実装 | 備考 |
| --- | --- | --- |
| `folder(id, parent_id, name, kind, smart_query, position, count_cache, count_cached_at, created_at)` | 同じ 9 列＋**`deleted_at`** | `kind` に `CHECK ('manual','smart')` を足した（家風「語彙は表でも守る」） |
| `CREATE INDEX ix_folder_parent ON folder(parent_id, position)` | 同じ | 名前・表・列まで同じ |
| `folder_member(folder_id, asset_id, position, added_at)`、主キー `(folder_id, asset_id)` | 同じ | 外部キーは**両方 `ON DELETE CASCADE`**（設計の字） |
| `CREATE INDEX ix_folder_member_asset ON folder_member(asset_id)` | 同じ | `INDEXED BY` で引けることを試験で固定 |
| `folder.parent_id REFERENCES folder(id) ON DELETE CASCADE` | 同じ | 親を消すと**子フォルダも中身も**消える（試験あり） |

**索引名は DB 全体で一意**（P8-0 の監査 C-0 の型）。`ix_folder_parent` / `ix_folder_member_asset` は
既存の 27 本と衝突しない。**`IF NOT EXISTS` が黙って無効にならないよう、移行の後に
`_check_v7_shape()` が「表の列」と「索引の `tbl_name`」を確かめ、違えば `RuntimeError` で落とす**
（P8-0 の `ux_request_token` と同じ穴を最初から塞ぐ）。**指示書の `smart_folder(name)` の索引は
設計に表が無いので作っていない**（名前でフォルダを引く口が設計に無い。`GET /api/folders` は木を全部返す）。

### `deleted_at` と `folder_member` の関係（設計の決め）

- `folder_member` が消えるのは **`folder` / `asset` の行を物理で消したとき**だけ（`ON DELETE CASCADE`）。
- **`asset.deleted_at`（段 1 の論理削除）では `folder_member` の行を消さない**（設計 §5.3 の CASCADE は
  物理削除の話）。論理削除した枚をカタログに出さないのは**読む側**（`deleted_at IS NULL`）の仕事（P2-1）。
- **`folder.deleted_at`（§6.1）も行を消さない**。木を引くときに `deleted_at IS NULL` で外す。
  実削除は `purge:true` のときだけ `DELETE FROM folder`（→ 下位と中身に CASCADE）。

---

## 2. 移行（v6 → v7）

### 2.1 道すじ

`db.SCHEMA_VERSION = 7`。`migrate()` に `if current < 7: _migrate_v7(con)` を足しただけ。
`_migrate_v7()` は **`V7_CATALOG_DDL` → `asset` の 3 列（列を見てから）→ `_check_v7_shape()`** の順。

**同じ 6 を名乗る P7 の DB の手当て**（既存の P8-0 の監査 C-1）を 1 行足した:

```python
if current < 6:
    _migrate_v6(con)
elif current == 6:
    # 版だけ 6 を名乗る DB（P7 の v6。控えの .backup/pre-p7-* が該当）は current < 6 を通らない。
    # v7 に上げるこの道でも P8 の表・列を補う（ここを外すと deletion_log を一生持たない）
    _migrate_v6(con)
if current < 7:
    _migrate_v7(con)
```

**早期 return 側（`current >= 7`）には v7 の手当てを足していない。** v7 は**版を上げて**足すので、
`user_version = 7` を名乗る DB に v7 の表が無い形は作れない（途中で落ちた DB は版が 6 のままで、
次の起動でもう一度 `_migrate_v7` を通る。P8-0 の `_top_up_v6` は **P7 が同じ 6 を名乗って別の表を
作った**事故の手当てで、v7 にはその事情が無い）。

### 2.2 控えを取ってから上げる（既存の P8-4 の道がそのまま効く）

**新しい仕組みは作っていない**（既に在る）。`app.create_app()` と `cli._store()` が
`inspect_db()` で版を見て、`db.SCHEMA_VERSION` より古ければ **`backup.backup_before_migrate()`** を呼び、
**取れなければ読み取り専用で起動して版を上げない**（`reason = pre_migrate_backup_failed`）。

- 控えの場所: **`<backup_dir>/pre-migrate-<YYYYMMDD>-<HHMMSS>/`**（`db.sqlite3` ＋ `manifest.json`）。
  **`<data>` の外**（`check_backup_dir` が中を断る）。**掃除の対象にしない**（`prune_snapshots` が残す）。
- 実データの `settings.backup_dir` は **`C:\work\image-reviwer\.backup\daily`** なので、利用者が
  アプリを立ち上げ直したときは **`.backup/daily/pre-migrate-<日時>/`** に取られてから v7 になる
  （**私は今は取っていない**。`.data` を read-write で開く道を通さないため。**再起動のときが正しい道**）。
- **複製で同じ道を通して実測**: `.tmp-p2-0/gui-data`（実データの複製）を 8791 で起動 →
  `.tmp-p2-0/gui-backups/pre-migrate-20261020-041657/db.sqlite3`（**v6**）＋ `manifest.json` ができ、
  その後に v7。`health/db` は `schema_version=7, expected_version=7, quick_check=ok`。

### 2.3 冪等

`migrate()` を 3 回呼んで、**`sqlite_master`（表と索引の `sql` まで）と全表の中身が変わらない**ことを
試験で固定（`test_the_v7_migration_is_idempotent`）。`executescript` は暗黙 COMMIT するが、
DDL はすべて `IF NOT EXISTS`＋列は `table_info` を見てからなので、途中で落ちてもやり直せる。

---

## 3. 作ったもの（ファイルと行数）

| ファイル | 行数 | 何 |
| --- | --- | --- |
| `src/image_reviewer/db.py` | **+149 / −4** | `SCHEMA_VERSION = 7`（注記）／`V7_CATALOG_DDL`／`V7_ASSET_COLUMNS`／`V7_COLUMNS`／`V7_INDEXES`／`_migrate_v7()`／`_check_v7_shape()`／`migrate()` の `current < 7` と `elif current == 6` の手当て／モジュール docstring と `open_db` の注記（v7） |
| `tests/test_p2_0.py` | **新規 602** | 14 件（下の表）。v6 の合成 DB を**手順どおり**作って移行する |
| `tests/test_db.py` | **+6 / −6** | v6 の試験の版の直書き `== 6` を `== db.SCHEMA_VERSION` に（このファイル自身の約束「版の数字そのものは `SCHEMA_VERSION` と比べる」に戻した） |
| `tests/test_deletions.py` | **+6 / −6** | `migrate(con) == 6` を `== db.SCHEMA_VERSION` に（早期 return の道は v7 でも同じ）。docstring の `current >= 6` を `current >= SCHEMA_VERSION` に |
| `docs/p2-0-implementation.md` | 新規 | これ |

テスト（`tests/test_p2_0.py`。それぞれ docstring に「何を壊すと落ちるか」を書いた）:

| 試験 | 何を見るか |
| --- | --- |
| `test_v7_adds_the_catalog_tables_columns_and_indexes` | 表・列・索引（**索引は `tbl_name` まで**）・版 7 |
| `test_the_catalog_shape_is_the_design_not_the_sketch` | **`folder_item` / `smart_folder` を作らない**・階層と `kind='smart'`・**名前は一意でない** |
| `test_v7_check_constraints_reject_the_wrong_vocabulary` | `asset.source` の既定 `'scan'`・5 語だけ・`folder.kind` は 2 語だけ |
| `test_the_catalog_foreign_keys_are_declared_as_cascades` | `folder_member` の 2 本と `folder.parent_id` が CASCADE |
| `test_deleting_a_folder_or_an_asset_takes_its_members` | **外部キーが本当に効く**（親削除→子と中身・画像削除→中身）。**論理削除では残る** |
| `test_the_folder_member_key_rejects_bad_rows` | 主キー（二重）・知らない folder / asset を入れられない |
| `test_v6_to_v7_keeps_every_row_and_value` | **行数と値が変わらない**（増えた列は `source='scan'`・他 NULL・帯 32 本のまま） |
| `test_a_v6_database_becomes_the_same_v7_shape_as_a_fresh_one` | v6 から上げた形と新規の形が**同じ**（`sqlite_master`） |
| `test_the_v7_migration_is_idempotent` | 3 回で形も中身も不変 |
| `test_a_squatted_index_name_is_refused_loudly` | 同名の索引が他の表に居たら**落ちる**（版は 6 のまま） |
| `test_a_squatted_catalog_table_is_refused_loudly` | 別の形の `folder` が居たら**落ちる**（版は 6 のまま） |
| `test_the_pre_migrate_backup_is_a_v6_copy_before_the_version_moves` | 控えが **v6**・manifest・`prune(keep=0)` で残る・その後に v7 |
| `test_the_version_does_not_move_when_the_backup_fails` | **差し替え**で控えを落とす → 読み取り専用・**版 6**・**v7 の表 0** |
| `test_get_endpoints_write_nothing_on_a_v7_database` | 既存の GET 26 本で**ファイルの中身と全表の中身が不変**・`/api/folders` は **404** |

---

## 4. 実行した結果（実測）

| 確かめたこと | 結果 |
| --- | --- |
| `uv run --no-sync pytest -q`（変更前） | **577 passed**（指示書の数と一致） |
| `uv run --no-sync pytest -q`（変更後） | **591 passed・0 failed**（577 ＋ 新規 14）。**2 回とも緑** |
| `node tools/gui_smoke.mjs` | **406 ok / NG 0**（変更前と同じ。P2-0 は画面を触らない） |
| `node tools/gui_layout.mjs`（複製サーバ 8791・11 本 × 4 幅） | **52 ok / NG 0・11 本とも exit 0**（比較は 3 窓 × 4 で 12 行） |
| **実データの複製 → v7**（`.tmp-p2-0/verify_real_copy.py`） | **31/31 ok**。v6 の行数（asset 463・decision 3・deletion_log 194・phash_band 7408 ほか 23 表）と**値がすべて同じ**・`source` は 463 行とも `'scan'`・帯の並びの sha も同じ |
| **控え**（同上） | `.tmp-p2-0/backups-real/pre-migrate-20261020-041558/`。中身は **v6**・**463 枚**・`manifest.json` の `counts.assets=463` / `decisions=3`（実データの複製）。**GUI 複製の起動**（`create_app` の道）でも `.tmp-p2-0/gui-backups/pre-migrate-20261020-041657/`（`counts.assets=463`）が取られた |
| **冪等**（同上） | 2 回目・3 回目で `sqlite_master`（78 件）も全表の中身（25 表）も不変 |
| **外部キー**（同上） | 親フォルダ削除 → 子 0・中身 0／画像（物理）削除 → 中身 0／`foreign_key_check` 空・`quick_check ok` |
| **控えが取れないと上げない**（同上・別の複製） | `create_app()` を差し替え → `mode=read_only` / `reason=pre_migrate_backup_failed`・**版 6**・`folder`/`folder_member` **0** |
| **壊すと落ちる**（`.tmp-p2-0/mutants/run_mutations.py`） | **10/10 通りで落ちた**（下の表） |
| **実データ** | **v6 のまま**・`quick_check ok`・**463 枚**・**片付け済み 194**（`deleted_at` 194・`closed_at` 194）・判断 3・`phash_band` 7408・**`folder` の表は無い**・`db.sqlite3` の **sha256 `caf7c642…`・4,083,712 バイト・mtime 不変**・`.backup` は **12 フォルダのまま**（`pre-migrate` も増えていない） |

### 壊すと落ちる（10 通り）

| # | 壊した物 | 落ちた試験の数 |
| --- | --- | --- |
| M1 | `_migrate_v7` から `executescript(V7_CATALOG_DDL)` を外す | 13 failed |
| M2 | `ix_folder_member_asset` を `ix_folder_member` に改名 | 13 failed（**ガードが落とす**） |
| M3 | `folder_member.asset_id` の `ON DELETE CASCADE` を外す | 2 failed |
| M4 | `folder_member.asset_id` の `REFERENCES` を丸ごと外す | 3 failed |
| M5 | `folder.deleted_at` を落とす | 13 failed |
| M6 | `asset.source` の列を足さない | 3 failed |
| M7 | **ガードも外したうえで** `ix_folder_parent` を `ix_folder_parents` に改名 | 3 failed（**テストだけで捕まえる**） |
| M8 | `folder.kind` の `CHECK` を外す | 1 failed |
| M9 | `folder.parent_id` の CASCADE を外す | 2 failed |
| M10 | `asset.source` の既定を `'watch'` にする | 2 failed |

（`_check_v7_shape` を外すと M2 はガードで落ちなくなるが、M7 のとおり**形の試験**が名前を見ているので
それでも落ちる。**ガードとテストの二重**にしてある。）

---

## 5. 自分で決めた点

1. **表の名前と形は設計 §5.3 の字**（`folder` / `folder_member`）。指示書の `folder_item` / `smart_folder` は
   作らない。**スマートフォルダは `folder.kind='smart'` の行**。§0 の表のとおり。
2. **`folder.deleted_at` を足した**（設計の穴。§6.1 が要求）。型は `TEXT`（NULL = 生きている。`asset` と同じ）。
3. **`folder.name` に UNIQUE を付けない。** 設計 §5.3 は一意を要求していない（階層があり、別の親の同名は普通）。
   一意が要るなら **P2-1 でサービス層（同じ親の中で一意）**にする。`UNIQUE(parent_id, name)` は
   **根（`parent_id IS NULL`）の重複を SQLite が許す**ので、そのままでは一意にならない（NULL の罠）。
4. **`asset.source` / `source_url` / `ref_tags` を足した**（設計 §5.1 の取り込み元）。`source` は
   `NOT NULL DEFAULT 'scan'` ＋ 5 語の `CHECK`。**実データの 463 枚はすべて走査で入った**ので `'scan'` が正しく、
   `asset_meta.source` も全行 `'scan'` だった（実測）。**`source_ref` は `asset` に無い**（`review_group` の列）。
5. **取り込みの履歴の表は作らない**（設計に無い）。`asset.source`・`asset.source_url`・
   `location_history` がその記録。
6. **索引の「黙って無効」を移行時に落とす**（`_check_v7_shape`）。P8-0 の監査 C-0 と同じ穴を塞ぐ。
   `RuntimeError` にするのは、呼び手（`create_app` / `cli`）が**起動を止める**ため（版は 7 にしない）。
7. **早期 return 側に v7 の top-up を足さない**（§2.1 の理由）。**`current == 6` の P7 の手当ては足した**。
8. **v6 の合成 DB をテストに使う**（実データをテストに持ち込まない。設計の「テスト方針」）。
   実データの複製での確認は `.tmp-p2-0/verify_real_copy.py`（**31 項目**）に分けた。
9. **既存テストの版の直書き 3 か所（test_db 2 か所・test_deletions 4 行）を `db.SCHEMA_VERSION` に直した。**
   直さないと `591 passed` にならない（`== 6` が `migrate()` の戻り 7 と食い違う）。**意味は変えていない**
   （「版が上がった」「早期 return の道」という主張はそのまま）。
10. **`GET /api/folders` は 404 のまま**（P2-0 は口を足さない）。試験で「まだ無い」ことを固定した。

---

## 6. 設計の穴（見つけた順）

1. **`folder.deleted_at` が §5.3 の DDL に無いのに、§6.1 が「既定は論理削除（`deleted_at`）」と決めている。**
   → 列を足した。**P2-1 はこの列を使う**。`purge:true` の物理削除は `DELETE FROM folder`（CASCADE）。
2. **`folder.name` の一意性が設計に書かれていない。** §6.1 の `POST /api/folders` は名前を受けるが、
   同じ親に同名を作れる。**利用者の「フォルダ名を打ち込ませて削除を確認する」（§6.1）は、同名が在ると
   確認にならない**。→ **P2-1 で「同じ親の中で一意」をサービス層に置く**ことを勧める（表の制約にしない。
   根の NULL のため。§5 の 3）。
3. **`folder_member` の `position` を並べ替える口が §6.1 に無い**（`PATCH /api/folders/{id}` はフォルダ自身の
   `position` だけ）。点検（`review-report-deepseek.md` C12）で「`PATCH /api/folders/{id}/members {asset_ids}`
   を足す」と決まっているが、**`design.md` §6.1 の口の一覧には反映されていない**。→ P2-1 で口を足すときに
   §6.1 も直す（列は `position` で足りる）。
4. **`folder.count_cache` の無効化の規則が設計に無い**（§10.2 は「走査・タグ付け・判断のあとに無効化」と
   書くだけで、`folder_member` の追加・削除・並べ替えのときと言っていない）。→ P2-1 で
   `folder_member` の書き込みでも無効化する（または件数は都度数える）。
5. **`smart_query` の検証が表に無い**（JSON の形はサービス層。設計 §10.2 の「使えるフィールドは固定の列挙」）。
   → P2-1 で `smart_query` を**フィールドの列挙で検査**し、生の SQL を受け付けない。

---

## 7. 申し送り（P2-1 以降）

1. **`store._asset_dict` の `source` を `asset.source` に寄せる。** いまは `asset_meta.source`（全行 `'scan'`）を
   「出所」として返しており、`asset_meta.source` にも `'scan'` が入る。**P2-1 で 4 経路（走査 / D&D /
   クリップボード / URL）を作るとき、`register()` の `source` 引数を `asset.source` に書き、
   `_asset_dict` は `asset.source` を返す**（`asset_meta.source` は来歴の出所として残すか、別名にする）。
   **両方 `'scan'` なので、いま既存の API の出力は変わらない**（P2-0 で store.py は触っていない）。
2. **口を作る**（§6.1 の 8 本）: `GET /api/folders`（木）/ `POST` / `PATCH` / `DELETE`（`dry_run` と
   `confirm:'<名前>'`、既定は論理削除）/ `POST|DELETE /api/folders/{id}/members` /
   `GET /api/folders/{id}/assets`。**`GET` は 1 バイトも書かない**・**`Host` / `Content-Type` / `actor` の
   3 点を既存の 1 か所で**通す（家風）。
3. **スマートフォルダ**は `POST /api/folders {kind:'smart', smart_query}` で作る（別表は無い）。
   **`smart_query` のフィールドの列挙**（§10.2 の 13 個）を検査する。
4. **論理削除したフォルダ・論理削除した画像**を一覧から外す（`deleted_at IS NULL`）。`GET /api/folders` の木・
   `GET /api/folders/{id}/assets`・`folder_member` の追加の 3 か所。
5. **画面は P2-2 以降**（`frontend-design.md` に先に足す。家風「文言は正を先に直す」）。
6. **`README.md` のテスト数を 577 → 591 に直し、文書表に本記録の行を足した**（2026-10-20）。
   **`design.md` §16.x への反映は段の終わり（監査の後）に 1 回**（§1・§5.3 の `deleted_at`・
   §6.1 の口の追加分）。
7. **実データの v7 化は利用者の再起動のとき**（本記録の時点では v6 のまま）。再起動のときに
   **`.backup/daily/pre-migrate-<日時>/`** が取られてから v7 になる。**取れなければ読み取り専用で起動して
   版は 6 のまま**（`health/db` が 503 で案内する）。**その控えを掃除しない**（既存の `prune` が残す）。
8. **作業上の注意（自分向け）**: 途中で `tests/test_deletions.py` の 4 行を直すのに
   `Get-Content | Set-Content` を使ってしまい（家風で禁止）、**BOM が付いた**。`git checkout` で戻して
   `edit` でやり直し、**いまのファイルに BOM は無い**（`db.py` も含め、触ったファイルはすべて LF・BOM 無し）。
   以後は `edit` / `write` だけを使う。
9. **`.tmp-p2-0/` に残した物**（使い捨て。`.tmp-*/` は gitignore 済み）:
   `verify_real_copy.py`（実データ複製の 31 項目）・`data-real-v7/`・`data-real-fail/`・`backups-real/`・
   `mutants/`（10 通り）・`gui-data/`（複製）・`gui-backups/`・`gui_layout.out.txt`・`final_real_check.py`・
   `inspect_real.py`・`make_gui_replica.py`・`pick_ids.py`。**実データの画像は 1 枚も動かしていない。**

---

## 8. 実行したコマンド（再現手順）

```powershell
cd C:\work\image-reviwer
$env:UV_CACHE_DIR = "C:\work\image-reviwer\.uv-cache"

# 1. 実データを読むだけ（v6 の確認）
uv run --no-sync python -X utf8 .tmp-p2-0/inspect_real.py
uv run --no-sync python -X utf8 .tmp-p2-0/final_real_check.py

# 2. 試験（591 件）
uv run --no-sync pytest -q
uv run --no-sync pytest tests/test_p2_0.py -q

# 3. 実データの複製で移行（v6 → v7・31 項目。**実データは mode=ro**）
uv run --no-sync python -X utf8 .tmp-p2-0/verify_real_copy.py

# 4. 壊すと落ちる（10 通り。写しを PYTHONPATH で前に置く）
uv run --no-sync python -X utf8 .tmp-p2-0/mutants/run_mutations.py

# 5. 画面の軽い検査
node tools/gui_smoke.mjs

# 6. 画面の計測（**複製**を作って 8791 で立てる。8790 は利用者）
uv run --no-sync python -X utf8 .tmp-p2-0/make_gui_replica.py
uv run --no-sync python -X utf8 tools/gui_layout_seed.py --data C:\work\image-reviwer\.tmp-p2-0\gui-data `
    --tags --exclusion --pending --stage3 --backup-error `
    --backup-dir C:\work\image-reviwer\.tmp-p2-0\gui-backups
$env:IMAGE_REVIEWER_DATA = "C:\work\image-reviwer\.tmp-p2-0\gui-data"
$env:IMAGE_REVIEWER_BACKUP_DIR = "C:\work\image-reviwer\.tmp-p2-0\gui-backups"
.\.venv\Scripts\python.exe -X utf8 -m image_reviewer.cli serve --port 8791
# 別の端末で（id は .tmp-p2-0/pick_ids.py が API と複製から取る）
node tools/gui_layout.mjs --base http://127.0.0.1:8791 --count 8
node tools/gui_layout.mjs --base http://127.0.0.1:8791 --screen requests
node tools/gui_layout.mjs --base http://127.0.0.1:8791 --screen group --group 01M58PERHX9ZTVS1XVDA82YZQ2
node tools/gui_layout.mjs --base http://127.0.0.1:8791 --screen asset --ids 01M4Z0KJR69CW8RA2R5Q9ZXHHW
node tools/gui_layout.mjs --base http://127.0.0.1:8791 --screen tags
node tools/gui_layout.mjs --base http://127.0.0.1:8791 --screen jobs
node tools/gui_layout.mjs --base http://127.0.0.1:8791 --screen duplicates
node tools/gui_layout.mjs --base http://127.0.0.1:8791 --screen pending
node tools/gui_layout.mjs --base http://127.0.0.1:8791 --screen pending --ids 01M4Z0KJR787Z98AWBH9GEN0D9,01M4Z0KJR78B8SV0JQS9C4XCPH
node tools/gui_layout.mjs --base http://127.0.0.1:8791 --screen library
node tools/gui_layout.mjs --base http://127.0.0.1:8791 --screen settings
# 終わったら 8791 の PID（health の pid）だけを止める。8790 は止めない
```
