# P2-0（スキーマ v7）監査報告 — 実行込み

- 日付: 2026-10-20（04:26〜） ／ 監査: Opus 5.5 ／ 依頼: Orca（dsh、run_5bdd431bf57b）
- 対象: コミット **876a3b0**（`src/image_reviewer/db.py` 61,880 B・03:55:11、`tests/test_p2_0.py` 602 行・04:13:19、
  `tests/test_db.py`・`tests/test_deletions.py` の版の直書き 12 行）。記録 `docs/p2-0-implementation.md`（339 行・04:22:46）
- 設計の版: `docs/design.md` 2,375 行・01:05:46（§5.1・§5.3・§6.1・§10.1〜§10.2・§14）
- **作業ツリーは監査の途中で動いた**（別の担当の ① の直し: `deletions.py`・`pending.js`・`test_deletions.py`・
  `test_deletions_advance.py`・`gui_smoke.mjs`・`frontend-design.md`。pytest 591→594、gui_smoke 406→415）。
  **`db.py` と `test_p2_0.py` は 876a3b0 と同じ**（`git diff 876a3b0 --quiet` で確認）。壊し試験と gui_layout は
  **876a3b0 を `git archive` で写した `.tmp-p2-0-audit/head/`** で回した（動く作業ツリーに引きずられないため）。
- 環境: 複製はすべて `C:\work\image-reviwer\.tmp-p2-0-audit\` の下に絶対パスで作り、パスを複製の中へ貼り替えた。
  親の環境に安全網 `IMAGE_REVIEWER_DATA=.tmp-p2-0-audit\safety-net`。複製サーバは 8793（CDP は 9344）。
- 触っていないもの: 実データ `.data`（`mode=ro` で読むだけ・**v6 のまま**）、`.backup` の 12 個（ファイルで写して写しを移行）、
  画像（実データの置き場は読むだけ）、8790（GET も打っていない）、ソース、git。

## 判定: **条件つきで使える**

**移行そのものは正しい。** 自分で作った実データの複製（`backup()`）を v7 に上げて、**23 表すべての列・行・値が同じ**、
`asset` 463 行は**全部 `source='scan'`・`source_url`/`ref_tags` は NULL**、`quick_check`/`integrity_check` ok、
FK 違反 0、3 回呼んで形も中身も不変（22/22）。`.backup` の **14 個の DB**（P7 の 3 個を含む）も全部 v7 の形になる。
起動の道では**控え（v6・463 枚・判断 3）を取ってから**上げ、控えが取れない 2 通り（置き場が `<data>` の中・置き場がファイル）は
**本物の断り**で版 6 のまま・v7 の物 0。**利用者が 8790 を立ち上げ直して v7 に上げてよい。**

**条件（P2-1 がこの形の上に作り始める前に直す）**: 依頼の (4)(7) が名指しした「ガード」と「壊すと落ちる」に穴がある。

### 最も重大な 3 件

1. **（B-1）ガードは「名前」しか見ていない。** `_check_v7_shape` は列の名前と索引の `tbl_name` だけを見る。
   **同じ列名で CASCADE も CHECK も無い `folder` と、`ix_folder_parent ON folder(name)` を先に置いた v6** を起動すると、
   ガードを通って **v7 になる**（`PRAGMA foreign_key_list(folder)` が空・索引の列は `name`）。docstring の
   「狙った形で在ることを確かめる」は成り立たない。（実データ・控え 14 個には `folder` が無いので、いま起きることはない。）
2. **（B-2）「壊すと落ちる」の外側に 6 通りの生き残り。** 876a3b0 の写しで、**どれも全 591 件を通る**:
   `ix_folder_member_asset` を `folder_id` に向ける（X5）／`ix_folder_parent` を 1 列にする（X11）／
   `added_at`・`position`・`name` の `NOT NULL` を外す（X12・X16・X18）／**索引を DDL と `V7_INDEXES` の両方から消す（X20）**。
   X20 が通るのは、形の試験が**期待値を検査対象の `db.V7_INDEXES` から作る**から（前回の `pickable` と同じ型）。
   記録 §1 の「`INDEXED BY` で引けることを試験で固定」は**試験に `INDEXED BY` が 1 か所も無い**（誤り）。
3. **（C-1）新しい試験 `test_get_endpoints_write_nothing_on_a_v7_database` がときどき落ちる。** 40 回中 1 回、
   3 ファイルの流れでは素の写しの 16 回中 1 回。差は **`db.sqlite3-shm` の中身だけ**（大きさも mtime も同じ）。`-shm` は読み手が
   書き換える共有メモリで、**この家では `tests/test_data_dir_guard.py:33` が既に外している**。「591 を 2 回とも緑」は
   ほかの担当にとって安定した関門ではない。直しは `_files` で `-shm` を外す 1 行。

---

## A. 直っていない／設計の約束が成り立たない

なし。v7 の表・列・索引・外部キーは設計 §5.3 / §5.1 と同じ形で入り（`folder.deleted_at` と `kind` の `CHECK` は足した分。E-1・E-2）、
実データの複製は値を 1 つも変えずに上がった。

## B. 重大

### B-1 ガードは名前しか見ない（依頼の (4)）

- 場所: `src/image_reviewer/db.py` の `_check_v7_shape`（「`for table, columns in V7_COLUMNS.items()`」と
  「`SELECT tbl_name FROM sqlite_master WHERE type = 'index'`」の 2 段だけ）。
- 再現（`.tmp-p2-0-audit/app_gate.py squat2`）: 実データの複製（v6）に
  `CREATE TABLE folder(id TEXT PRIMARY KEY, parent_id TEXT, name TEXT NOT NULL, kind TEXT NOT NULL, smart_query TEXT, position INTEGER NOT NULL DEFAULT 0, count_cache INTEGER, count_cached_at TEXT, created_at TEXT NOT NULL, deleted_at TEXT); CREATE INDEX ix_folder_parent ON folder(name);`
  を入れてから `create_app()`。
- 結果: `health/db` 200・`schema_version=7`・`mode=ok`。`PRAGMA foreign_key_list(folder)` は `[]`、
  `PRAGMA index_info(ix_folder_parent)` は `[(0, 2, 'name')]`。**親を消しても子が残る・`kind` に何でも入る v7** ができる。
- 同じ穴が DDL 側の変異でも見える: X5（`ix_folder_member_asset ON folder_member(folder_id)`）と X11（`ON folder(parent_id)`）は
  ガードも試験も通る（F）。
- 効き目のある場面: いまは無い（実データと `.backup` の 14 個に `folder` は無い。下の C-3 のとおり P7 は別の表を残している）。
  **ただし依頼が名指しした「ガードが効くか」の答えは「名前の取り合いにだけ効く」。**
- 直し方（推奨）: `table_info` の `type`・`notnull`・`dflt_value`・`pk`、`foreign_key_list` の `(from, table, to, on_delete)`、
  `index_info` の列を**リテラルの期待値**と比べる。または `sqlite_master.sql` を空白を詰めて DDL の文と比べる
  （新規の DB も移行の DB も同じ `V7_CATALOG_DDL` を通るので、文は一致する。実測: 複製と新規で `ix_folder_*` の `sql` は同じ）。

### B-2 壊しても落ちない 6 通り（依頼の (7)）

- 876a3b0 の写し（`head/`）の `db.py` を 1 か所ずつ壊し、`PYTHONPATH` で前に置いて回した（`.tmp-p2-0-audit/mut.py`）。
  3 ファイル（`test_p2_0`・`test_db`・`test_deletions`、132 件）で通った 6 通りは、**全体（591 件）でも何も変わらない**
  （素の写しで落ちる 32 件＝`apps/gui` の無い写しの都合と、名前まで同じ集合。X5・X12・X20 で集合を比べ、X11・X16・X18 は件数が同じ）。
- 判定（等価変異か穴か）: **6 通りとも穴**。設計 §5.3 は `name TEXT NOT NULL`・`position INTEGER NOT NULL DEFAULT 0`・
  `added_at TEXT NOT NULL`・`ix_folder_member_asset ON folder_member(asset_id)`・`ix_folder_parent ON folder(parent_id, position)`
  と字で決めている。X20 は「索引が無い v7」を通す。
- 根: `test_v7_adds_the_catalog_tables_columns_and_indexes` が**索引の一覧を `db.V7_INDEXES` から読む**（期待値が検査対象と一緒に動く）。
  列の検査は名前の有無だけで、`notnull` や索引の列を見ない。
- 記録との食い違い: §1 の表「`INDEXED BY` で引けることを試験で固定」——`tests/test_p2_0.py` に `INDEXED`・`index_info`・
  `EXPLAIN` は 1 つも無い。「名前・表・列まで同じ」の「列」は試験されていない。
- 直し方: 期待値を試験の中にリテラルで書く（2 本の索引の名前・表・列、`folder` / `folder_member` の `table_info` の
  `notnull`・`dflt_value`、`foreign_key_list`）。B-1 のガードと同じ表を 2 か所に書くことになるが、**片方は検査対象・片方は期待値**なので
  それでよい（同じ物を参照すると X20 が通る）。

## C. 中程度

### C-1 `test_get_endpoints_write_nothing_on_a_v7_database` が `-shm` で揺れる

- 場所: `tests/test_p2_0.py` の `_files`（`for path in sorted(Path(root).rglob("*"))` で `db.sqlite3-shm` も中身まで比べる）。
- 再現: `head/` で同じ試験を 40 回 → **1 回落ちた**。差は `{'db.sqlite3-shm': (32768, 1792438690942184300, '1f8a…')} != {… '17d7…'}`
  （大きさ・mtime 同じ、中身だけ違う）。3 ファイル（132 件）の流れでは素の写し（`X0-none`）の 16 回中 1 回。
- `-shm` は WAL の索引（読み手の印を含む）で、`GET` が DB を「書いた」証拠にはならない。**`tests/test_data_dir_guard.py:33` が
  「`-shm` だけは mtime を数えない」と既に書いている**（家の知識が新しい試験に入っていない）。
- 直し方: `_files` で `-shm` を外す（`-wal` は残してよい。中身が変われば書いた証拠）。

### C-2 ガードが落ちたときの起動（依頼の (4) の続き）

- 再現（`app_gate.py squat 2`）: v6 の複製に `CREATE INDEX ix_folder_parent ON asset(first_seen_at)` を置いて 2 回起動。
- 結果: `create_app()` は `RuntimeError('v7 の索引 ix_folder_parent を folder に作れませんでした（同じ名前が asset にあります）')` で
  **例外のまま抜ける**（読み取り専用の道に入らない）。DB は**版 6 のまま、`folder`・`folder_member`・`asset` の 3 列は入った**
  （`executescript` と `ALTER` は先に確定する）。**起動のたびに `pre-migrate-*` が 1 つ増える**（2 回で 2 個。掃除しない控え）。
- 害: 大声で止まる点は狙いどおり。ただ「版 6 だが v7 の物がある」半端な DB が残り、控えが積もる。
- 直し方（推奨）: 名前の取り合いは**控えを取る前に `mode=ro` で見られる**（`sqlite_master` を引くだけ）。`inspect_db` に足して
  `mode=read_only`・`reason=schema_conflict` で起動し、案内を出す。いまの実データには起きない（明示の索引 26 本に `ix_folder_*` は無い）。

### C-3 P7 の控えに `preset` と `watcher_state` が残っている（段をまたぐ穴。v8 への申し送り）

- `.backup/pre-p7-*` の 3 個を写して v7 に上げると、**P7 が作った `preset`（`actor` 列つき・`ON DELETE SET NULL`）と
  `watcher_state`（`baseline_create_time`・`updated_at` つき）がそのまま残る**（どちらも 0 行）。
- 設計 §5.6 の `preset`（`actor` 無し）と §5.5 の `watcher_state`（4 列）とは**形が違う**。P3 が `CREATE TABLE IF NOT EXISTS preset` を
  足すと、**P7 の控えを戻した DB では P7 の形のまま黙る**（P8-0 の C-1・本件の B-1 と同じ型）。
- 直し方: その版で足すときに B-1 の形の検査を通す。P7 の 0 行の表は `current == 6` の道で落としてよい（失う物が無い）。

## D. 軽微（と、確かめた結果問題なし）

- D-1 **`elif current == 6` は正しいが、記録の理由が強すぎる。** 外すと P7 の控えは 1 回目の移行で `deletion_log` などを持たない
  v7 になる（`mig_backups.py --no-elif`）。しかし**2 回目の `migrate()`（次の起動）で早期 return 側の `_top_up_v6` が補う**
  （`elif2.py`: 1 回目 `False`・2 回目 `True`、`missing_top_ups` も空に）。「一生持たない」ではなく「**最初の 1 回の起動が壊れる**」。
  `elif` は残すべき（その 1 回を壊さない）。捕まえるのは `test_db.py` の `test_v6_tables_are_added_to_a_p7_style_v6_database`
  （`test_p2_0` は 14 件とも通る）。
- D-2 記録の「既存の 27 本」は **26 本**（実データ v6 の明示の索引。v7 の新規で 28 本）。衝突は無い。
- D-3 `pre-migrate-*/manifest.json` に**移行前後の版が書かれない**（`_write_db_only` は `extra={"from_version", "to_version"}` を
  戻り値にだけ入れる）。版は控えの DB の `user_version` で読めるので実害は無い。P8-4 以来の形で P2-0 の変更ではない。
- D-4 実装者の壊し試験の数え方: M1・M2・M5 の「13 failed」は、**`test_p2_0` の 14 件のほぼ全部が、ガードの `RuntimeError` で巻き添え
  で落ちた数**（自分でも 13 failed・1 error を再現）。その試験が狙いの欠陥を見ているかは別。M5 はガードの一覧（`V7_COLUMNS`）も
  直すと 2 件しか落ちない（X14）。また実装者の `run_mutations.py` は `IMAGE_REVIEWER_DATA` を**外して**回す（安全網なし。
  conftest が上書きするので実害は無い）。
- D-5 `asset.source` は `NOT NULL DEFAULT 'scan'`（設計 §5.1 は既定なし）。`ALTER` には既定が要るので仕方ないが、
  **P2-1 で D&D・クリップボード・URL の道が `source` を書き忘れると黙って `'scan'` になる**。各経路の試験で値を確かめる（申し送り）。
- D-6 実装者の一時物 `.tmp-p2-0/` に**実データの複製**（`gui-data` 28 MB・`data-real-v7`・`data-real-fail`・`backups-real`・
  `gui-backups`）が残っている。gitignore 済みだが、前回 `bfcc7b5` で写しが公開履歴に入った経緯があるので消すのを勧める。
- 問題なし（実測）:
  - 移行: 22/22（`mig_real.py`）。`asset` の列は末尾に 3 つ足され、古い列の値は 463 行とも同じ。**ALTER で付けた `CHECK` も `NOT NULL` も効く**
    （`source='ftp'`・`NULL` は `IntegrityError`）。SQLite 3.53.1。
  - `.backup` の 14 個（daily 4・pre-p4（v3）・pre-p7 3・pre-p8-0（v5）・pre-p8-1/2/4/6・pre-tray-fix）: すべて v7・足りない表と列 0・
    `quick_check ok`・FK 違反 0・`asset.source` は全部 `scan`。行数の変化は pre-p8-1 の `phash_band` 0→1456 だけ（`_top_up_v6` の帯の埋め直し。v7 と無関係）。
  - 外部キー（v7 にした複製で、取引を巻き戻して）: 3 段の木に 3 枚ずつ → 根の物理削除で子・孫・中身 0／画像の物理削除で 2 つのフォルダから
    その 1 枚だけ消える／フォルダ・画像の論理削除では行が残る／知らない親・知らない画像・二重・`kind='smart2'` は断る（16/16、`fk_real.py`）。
  - 現行のコードに `asset` を物理で消す・`INSERT OR REPLACE INTO asset` する所は無い（CASCADE はいまは効く場面が無い）。
  - 書き出し（`review.json`）は欄を名指しで作るので、`asset` の列が増えても形は変わらない（`export.py` の `_asset_doc`）。
  - `/api/folders` は 404（口はまだ無い）。

## E. 設計とのずれ

| # | 設計 | 実装 | 判定 |
| --- | --- | --- | --- |
| E-1 | §5.3 の DDL に `folder.deleted_at` が無い／§6.1 は「既定は論理削除（`deleted_at`）、実削除は `purge:true`」 | 列を足した | **実装が正しい。** §6.1 は振る舞いを決めていて、列が無いとその振る舞いが作れない。§5.3 の DDL が書き漏れ。段の終わりに §5.3 を直す |
| E-2 | §5.3 は `kind TEXT NOT NULL -- 'manual' \| 'smart'`（注記だけ） | `CHECK (kind IN ('manual','smart'))` | 妥当（家風「語彙は表でも守る」） |
| E-3 | §5.1 は `source TEXT NOT NULL`（既定なし） | `NOT NULL DEFAULT 'scan'` | 妥当（`ALTER` の都合）。D-5 の申し送り付き |
| E-4 | §5.1 の注記「`source_url` — `kind='url'` のときの出所」 | — | 設計の誤記。`kind` に `'url'` は無い。`source='url'` のこと。§5.1 を直す |
| E-5 | 指示書のスケッチ（`folder_item`・`smart_folder`・`name` 一意・`asset.source_ref`） | 設計の字（`folder_member`・`kind='smart'`・一意なし・`asset.source`） | 妥当。4 点とも設計の字が正しい（`source_ref` は `review_group` の列） |
| E-6 | §10.2 のフィールド `added_at` / `seen_at` / `reason_code` / `source` | 列は `first_seen_at` / `last_seen_at` / `review_reason_code_id` / `asset.source`（`asset_meta.source` ではない） | P2-1 で対応表を書く（申し送り 3） |

**申し送り（依頼の (9)）の判定:**

| # | 記録の申し送り | 判定 |
| --- | --- | --- |
| 1 | `store._asset_dict` の `source` を `asset.source` に寄せる | **持ち越してよい**（いま値は同じ）。**`source_url: None`・`ref_tags: []` の決め打ちも同時に列から読む**（記録に無い。§6.1 の `PATCH /api/assets/{id} {kind?, source_url?, ref_tags?}` がこの列を書く） |
| 2 | 口 8 本（§6.1） | 持ち越してよい。**`PATCH` は `UPDATE` で書く**（`INSERT OR REPLACE INTO folder` は CASCADE で中身を消す。実測 2→0。この家は `phash_band`・`job_item`・`duplicate_exclusion` で `OR REPLACE` を使う癖がある）。並べ替えの口（記録 §6-3）も足す |
| 3 | `smart_query` のフィールドの列挙 | 持ち越してよい。E-6 の対応表と、**`folder` の条件がスマートフォルダ自身や循環を指す場合**の扱いを決める |
| 4 | `deleted_at IS NULL` を 3 か所 | 持ち越してよい。**論理削除した親の下の子**も隠す（子の `deleted_at` は NULL のまま。サービスが同じ取引で子孫に印を付けるか、読む側が祖先を辿る） |
| 5 | 同じ親の中で一意はサービス層 | **変更を勧める**（G-2。表で守れる） |
| — | 表が許してしまう形 | 親の循環（P→Q→P）・`kind='smart'` に `folder_member`・`kind='manual'` に `smart_query`（JSON でない文字列も）を表は受ける（実測）。P2-1 のサービスで断る |

## F. テストで守れないもの（壊し試験）

876a3b0 の写し、`test_p2_0`・`test_db`・`test_deletions`（132 件）。素の写し（X0）は 132 passed（16 回中 1 回 C-1 で 1 failed）。

| 変異 | 落ちた数 | 落とした試験 | 判定 |
| --- | --- | --- | --- |
| M1 DDL を流さない | 47 failed・197 errors | ガードの `RuntimeError` で全部 | 落ちる（巻き添え。`test_p2_0` だけなら 13＋1） |
| M2 `ix_folder_member` に改名 | 同上 | ガード | 落ちる（ガードが捕まえる） |
| M3 `asset_id` の CASCADE を外す | 2 | 宣言の試験・削除の試験 | 落ちる |
| M4 `asset_id` の FK を外す | 3 | | 落ちる |
| M5 `deleted_at` を落とす | 47・197 | ガード | 落ちる（ガードだけ。X14 参照） |
| M6 `source` を足さない | 3 | | 落ちる |
| M7 ガードを外して `ix_folder_parents` | 3 | 形の試験・取り合いの 2 件 | 落ちる |
| M8 `kind` の CHECK を外す | 1 | | 落ちる |
| M9 `parent_id` の CASCADE を外す | 2 | | 落ちる |
| M10 既定を `'watch'` | 2 | | 落ちる |
| X1 `elif current == 6` を外す | 1 | `test_db` の P7 の試験（`test_p2_0` は 14 通る） | 落ちる |
| X2 ガードが `tbl_name` を見ない | 1 | 索引の取り合い | 落ちる |
| X3 `folder_id` の CASCADE を外す | 2 | | 落ちる |
| X4 主キーを外す | 1 | | 落ちる |
| **X5 `ix_folder_member_asset` を `folder_id` に** | **0** | — | **穴**（B-2） |
| X6 `source` の CHECK を外す | 1 | | 落ちる |
| X7 / X8 `source_url` / `ref_tags` を足さない | 2 / 2 | | 落ちる |
| X9 v7 を `current < 6` の道にだけ置く | 4 | | 落ちる |
| X10 `parent_id` を `SET NULL` に | 2 | | 落ちる |
| **X11 `ix_folder_parent` を 1 列に** | **0** | — | **穴** |
| **X12 `added_at` の NOT NULL を外す** | **0** | — | **穴** |
| X13 ガードの例外を握りつぶす | 2 | 取り合いの 2 件 | 落ちる |
| X14 `deleted_at` を DDL とガードの一覧の両方から | 2 | 形の試験・表の取り合い | 落ちる |
| X15 ガードを外して `ix_folder_member` に改名 | 3 | | 落ちる |
| **X16 `position` の NOT NULL・既定を外す** | **0** | — | **穴** |
| X17 `ALTER` を列を見ずに毎回 | 3 | 取り合いの 2 件（再試行で `duplicate column`）・P7 | 落ちる |
| **X18 `name` の NOT NULL を外す** | **0** | — | **穴** |
| X19 ガードを外す | 2（＋C-1 の揺れ 1） | 取り合いの 2 件 | 落ちる |
| **X20 `ix_folder_member_asset` を DDL と `V7_INDEXES` から消す** | **0** | — | **穴**（期待値が検査対象から来る） |

実装者の 10 通りは 10/10 で落ちた（主張どおり）。**自前の 20 通りのうち 6 通りが生き残った**。

## G. 依頼者への質問

| # | 論点 | 選択肢 | 推奨 |
| --- | --- | --- | --- |
| G-1 | **v7 の形を変えられるのは、利用者が 8790 を立ち上げ直すまで。** 立ち上げ直すと実データは v7 になり、以後 v7 の DDL を変えても早期 return で届かない（top-up か v8 が要る） | (a) B-1・B-2・G-2 を直してから利用者に再起動を頼む (b) いまの形で再起動し、後の変更は top-up で足す | **(a)**。直しは小さい（ガードと試験と索引 1 本）。B-2 の試験の直しは形を変えないので (b) でも可だが、G-2 を採るなら (a) |
| G-2 | 同じ親の中で名前を一意にする場所 | (a) サービス層（記録の案） (b) 表の部分一意索引 `CREATE UNIQUE INDEX ux_folder_name ON folder(coalesce(parent_id, ''), name) WHERE deleted_at IS NULL` | **(b)**。実測: 根の重複も同じ親の重複も断り、別の親の同名と論理削除後の再利用は通す（SQLite 3.53.1）。記録の「NULL の罠」は `coalesce` で避けられる。サービス層だけだと同時の 2 本の `POST` で抜ける。大文字小文字を同じとみなすなら `name COLLATE NOCASE` も |
| G-3 | `folder.deleted_at`（依頼の (2)） | (a) 列を残す (b) 物理削除だけにする | **(a)**（E-1）。§5.3 を直す。論理削除した親の子をどう隠すかを P2-1 で決める（申し送り 4） |
| G-4 | 論理削除のフォルダを木から外す引き方 | (a) `ix_folder_parent` のまま（`deleted_at IS NULL` は表を見る） (b) 部分索引を足す | **(a)**。フォルダは数百で済む。`ix_asset_del` のような部分索引は件数が増えてから |
| G-5 | P7 の控えの `preset` / `watcher_state`（C-3） | (a) v8 で形を検査 (b) `current == 6` の道で 0 行なら落とす | **(a)＋(b)**。その版を作るとき |

## H. 確かめられなかったこと・証拠の注記・後始末

- **確かめていないこと**: 本物の 8790 での再起動（利用者がする）。ACL で書けない置き場での控えの失敗（2 通りの本物の断りで代えた）。
  `cli.py` の `_store()` の道は読んだだけ（`create_app` と同じ `backup_before_migrate` を呼ぶ）。
- **証拠の注記**:
  - 作業ツリーの pytest: 1 回目 **591 passed**（04:3x）・2 回目 **594 passed**（別の担当が 3 件足した後）。
    876a3b0 の写しでは **584 passed・2 failed・5 skipped を 2 回**。2 failed（`test_pytest_does_not_use_a_data_dir_it_inherited`・
    `test_the_selftest_refuses_when_any_of_the_four_ports_is_taken`）は**写しの置き場の都合**（本物の repo の場所と `.venv` を前提にする試験）で、v7 と無関係。
  - gui_smoke: 876a3b0 の写しで **406 ok・NG 0**（作業ツリーは 415 ok）。
  - gui_layout: 876a3b0 の写し・v7 にした複製（`gl/`、画像 374 枚を `copy2`、パス 1,117 個すべて複製の中）を 8793 で。
    **52 ok・NG 0**（下の「gui_layout」）。**1 回目の走りで `asset` が止まり、`pending-ids` が NG 4 だった**のは**私の id の選び方**
    （API の先頭の行を取り、場所の無い枚を選んだ）。その node（pid 24404、コマンド行を確かめてから）を `Stop-Process` で止めた。
    また**別の担当の Chrome が同じ 9334 で立っていた**（`.tmp-msg2` の profile）ので、2 回目は `--port 9344` にした。
  - `seed: 最後の失敗を入れた: [WinError 5] … C:\Users\<利用者>\image-reviewer-ba…` は `gui_layout_seed.py` が入れる**文字列**で、
    `%USERPROFILE%` の下には何も作られていない（確認済み）。
- **実行したコマンドと結果**（`.tmp-p2-0-audit/`）:
  - `sig.py sig-before.json` → v6・ok・23 表・置き場のファイル 424・控え 12
  - `mig_real.py` → 22/22 ／ `fk_real.py` → 16/16 ／ `mig_backups.py` → 14 個とも v7 ／ `mig_backups.py --no-elif`・`elif2.py` → D-1
  - `app_gate.py ok|inside|file|squat 2|squat2 2` → 判定・B-1・C-2
  - `mut.py`（876a3b0 の写し）→ F ／ `mut.py … --full --all` → 生き残りは全体でも同じ
  - `gl.ps1`・`gl2.ps1`（PowerShell から直に、`-ExecutionPolicy Bypass`、BOM 付き）→ gui_layout
- **実データ**: 前後で変化なし（後始末の節）。

### gui_layout

- 1 回目の起動（複製は v6）で `pre-migrate-20261020-045648`（複製の `bk` の中）が取られてから v7（`health/db`: 7/7・`quick_check ok`）。
  止めて `gui_layout_seed.py --tags --exclusion --pending --stage3 --backup-error`（実装者と同じ）→ 立て直して 11 本 × 4 幅。
- 2 回目の走り（id は「生きていてファイルがある枚」から。実装者と同じ `01M4Z0KJR69CW8RA2R5Q9ZXHHW` ほか、CDP 9344）:
  **compare 12・requests・group・asset・tags・jobs・duplicates・pending・pending-ids・library・settings 各 4 ＝ 52 ok・NG 0、11 本とも exit 0**。

### 後始末

- **実データ**: 前後の署名（`sig-before.json` / `sig-after.json`）が**全部同じ**——`user_version` 6・`quick_check ok`・23 表の行数と中身の
  sha・`sqlite_master` の sha・`.data` のファイルの大きさと mtime（`-wal` も）・置き場の画像 424 個の名前・大きさ・mtime・`.backup` の 12 個の名前。
  画像は 1 枚も動いていない。8790 には何も打っていない。安全網 `safety-net` は 0 ファイル。
  （注: 実データの置き場 `Anima\20261010` には監査中に ComfyUI が新しい画像を書いていた（03:29〜03:42 の 113 個）。監査の前からある物で、前後で増減なし。）
- 複製サーバ: 8793 を 3 回立てて、毎回 `health` の `data_dir` と pid を確かめてから `taskkill`。いまは 8791〜8799 と 9344 に何も居ない。
  他人の物（8790・別の担当の Chrome 9334）には触っていない。止めたのは自分の node 1 本（H の注記）。
- **消した物**（実データの写しは残していない。前回の `bfcc7b5` の教訓）: `gl/`（画像 374 枚の写しと DB）・`c1/`・`bk/`（控え 14 個の写し）・
  `gate/`・`elif2/`・`fresh/`・`tmp/`（Chrome の profile）・`safety-net/`。
- **残した物**（`.tmp-p2-0-audit/`、77 MB・コードとログだけ）: 自前のスクリプト（`sig.py`・`mig_real.py`・`fk_real.py`・`mig_backups.py`・
  `elif2.py`・`app_gate.py`・`mut.py`・`mk_replica.py`・`pick.py`・`gl.ps1`・`gl2.ps1`）、876a3b0 の写し `head/`、変異の写し `mut/`、
  ログ（`mut-*.txt`・`gl*-*.log`・`flaky-*.txt`・`g1-fail-23.txt`）、署名 2 つ（置き場のファイル名の一覧を含む）。

---

## 最も重大な 3 件（再掲）

1. **（B-1）ガードは名前しか見ない。** 同じ列名で CASCADE も CHECK も無い `folder` と、列の違う `ix_folder_parent` を置いた v6 が
   ガードを通って v7 になる（`foreign_key_list(folder)` が空）。依頼 (4) の答えは「名前の取り合いにだけ効く」。
2. **（B-2）6 通りの変異が全 591 件を通る**（索引の列・`NOT NULL` 3 つ・索引を DDL と `V7_INDEXES` の両方から消す）。形の試験が
   期待値を `db.V7_INDEXES` から作る。記録の「`INDEXED BY` で固定」は試験に無い。
3. **（C-1）新しい GET の試験が `-shm` で 40 回に 1 回落ちる。** `test_data_dir_guard.py:33` と同じく `-shm` を外す 1 行。
