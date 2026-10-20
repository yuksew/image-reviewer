# P2-1（仮想フォルダ）の実装の記録

- 日付: 2026-10-20 ／ **P2（取り込みとカタログ）の 2 番目の小段**
- 設計: `docs/design.md` **§5.3**（`folder` / `folder_member`）・**§6.1**（カタログの口）・
  **§10.1**（多対多。**実ファイルは動かさない**）・**§10.2**（スマートフォルダ）・**§14**（P2 の行）・
  **§16.9**（P2-0 の決定。**G-2 (b)** 同じ親の中で名前は一意／**C-2** 名前の取り合い）。
  画面は **`docs/frontend-design.md`**（§3 の 14・§4.5.1・§6.1・§11。**先に正を直してから実装した**）。
- 前例: `docs/p2-0-implementation.md`（v7 の作り方・形のガード・期待値のリテラル）、
  `docs/p2-0-audit-triage.md`（B-1・B-2・C-1・**C-2 は P2-1 の頭**・**G-2 は P2-1 で索引**）。
- 環境: `$env:UV_CACHE_DIR = "C:\work\image-reviwer\.uv-cache"`、`uv run` はすべて `--no-sync`。
  **実データ `.data` は `mode=ro` だけ**（署名を前後で取った）。サーバは**複製**を
  `IMAGE_REVIEWER_DATA` に付けて **8791** で立てた。**8790（利用者）は止めていない・GET も打っていない**。
  **`IMAGE_REVIEWER_DATA` を付けずにサーバ・アプリを起動していない**（`create_app()` が断る）。
  **`git` のコミットはしていない。**

---

## 0. 結論（口 8 本・R2 の線・実データ）

| 何 | 結果 |
| --- | --- |
| **口 8 本**（§6.1 の字） | **7 経路**で 8 つの働きを実装（`DELETE` の 2 行は**同じ経路**——`?dry_run=true` と本文の `confirm`。§1） |
| **R2 の線** | **1 枚を 2 つのフォルダに入れられる**・**外しても画像は消えない**・**フォルダを消しても画像は消えない**・**実ファイルは 1 バイトも動かない**（署名が同じ）。試験で固定（§5-1） |
| **同じ親の同名** | **422 `folder_name_taken`**（**表の部分一意索引**＋サービス層の 2 重） |
| **別の親の同名** | 通る（200） |
| **循環する親** | **422 `folder_cycle`** |
| **`GET` は書かない** | ファイルの中身と全表の中身が前後で同じ（§5-3） |
| **403 / 422** | 書く 5 つの口は**エージェント 403 `human_only`**。語彙外・存在しない親・同名・循環・確認の名前違いは **422** |
| **C-2（P2-0 の申し送り）** | `inspect_db` が **`mode=ro` で形を見て**、名前の取り合いがあれば **`schema_conflict` で読み取り専用**（**1 バイトも書かない**）。§2 |
| **P2-0 の申し送り（出所）** | `store._asset_dict` の `source` を **`asset.source`** に寄せた（`source_url` / `ref_tags` も列から） |
| **三点セット** | **pytest 622 passed**・**gui_smoke 482 ok / NG 0**・**gui_layout 12 本 × 4 幅 = 48 ok / NG 0** |
| **実データ** | **v6 のまま**・`asset` **463**・`deleted_at` **194**・`deletion_log` 194（閉じた 194）・`decision` 3・`phash_band` 7408・**`folder` の表は無い**・`db.sqlite3` の **sha256 `caf7c642…`・4,083,712 バイト・mtime 不変**・`.backup` は **12 個のまま** |

---

## 1. 口（8 本。§6.1 の字との対応）

| 設計 §6.1 の字 | 実装 | 何をする |
| --- | --- | --- |
| `GET /api/folders` | 同じ | **木**（`items[].children`）。`kind` と**生きた画像の枚数** `count` つき。**書かない** |
| `POST /api/folders {parent_id, name, kind}` | 同じ（`smart_query` も受ける） | 作る。**人だけ**。同じ親の同名は 422 |
| `PATCH /api/folders/{id} {name?, parent_id?, position?, smart_query?}` | 同じ（`kind` も） | 名前・親・並び・条件。**循環は 422** |
| `DELETE /api/folders/{id}?dry_run=true` | 同じ | **何も消さずに**、消えるフォルダ数・中の枚数・名前を返す |
| `DELETE /api/folders/{id} {confirm:'<名前>'}` | 同じ（`purge:true` で実削除） | **既定は論理削除**（子孫も隠す）。**画像は消さない** |
| `POST /api/folders/{id}/members {asset_ids:[]}` | 同じ | 入れる（**冪等**。既に入っていれば `already`） |
| `DELETE /api/folders/{id}/members {asset_ids:[]}` | 同じ | 外す（`folder_member` の行だけ。**画像は消さない**） |
| `GET /api/folders/{id}/assets ?cursor=&limit=&sort=` | 同じ | 中身（**生きた画像だけ**）。`sort=position|added|name` |

**7 経路で 8 つの働き**である理由: §6.1 は `DELETE /api/folders/{id}` を**2 行**（`dry_run` と
`confirm`）に分けて書いているが、**同じ経路**（クエリと本文で分かれる）。設計の字を変えずに
両方を実装した。**8 本に満たないから口を増やす必要は無い**——増やすと同じ働きに 2 つの口ができ、
「どちらが正か」が分からなくなる（家風「同じ物に 2 語を使わない」）。

- **403**: 書く 5 つの口（`POST` / `PATCH` / `DELETE` / `POST members` / `DELETE members`）は
  `require_human(actor_of(request))` の**1 か所**。`actor` は `human` / `agent` だけ（外は 422）。
- **422 の語彙**: `folder_name_taken`（同じ親の同名）・`parent_missing`（無い／隠れた親）・
  `folder_cycle`（自分・子孫を親に）・`confirm_required`（名前が違う）・`asset_missing`（無い／
  片付け済みの画像）・`smart_query_required` / `smart_query_bad`（条件の列挙）・
  `folder_too_deep`（32 段）。
- 守り（`Host` / `Origin` / `Content-Type`）は `app.py` の middleware が**アプリ全体**に掛ける。
  試験で `Host: evil` と `Content-Type: text/plain` が 403 になることを固定した。

### 論理削除の決め（設計が黙っている点）

- **子孫も一緒に隠す**（親だけ隠すと、木から子が見えなくなる）。
- ~~**隠したフォルダの `folder_member` は消す**~~ → **P2-1 の監査 B-1 で取り消した**（2026-10-20。
  [`p2-1-audit-triage.md`](p2-1-audit-triage.md) §1）。**隠すだけで、行は残る**——消えるのは
  `purge` のときだけ。取り消した理由: 前の理由「同じ名前を作り直すと前の所属が生き返る」は
  **成り立たない**（作り直したフォルダは**新しい ULID** なので、古い行は付かない）。そして
  設計 §6.1 が論理削除を既定にした理由は「**仮想フォルダは再生成できない分類**」なのに、
  その分類だけを物理で消していた（複製で `folder_member` 3 → 0 を実測）。
  **`asset` / `asset_location` は 1 行も触らない**（もとの決めのまま）。
- **`asset.deleted_at` の画像はカタログに出さない**（`GET /api/folders/{id}/assets` と件数の両方）。

---

## 2. v7 に足した形（**索引とガード**）

### 2.1 索引（`db.V7_UNIQUE_DDL`。**式索引＋部分索引**）

```sql
CREATE UNIQUE INDEX ux_folder_name
  ON folder(coalesce(parent_id, ''), name) WHERE deleted_at IS NULL;
```

- **`UNIQUE(parent_id, name)` では足りない**。SQLite の `UNIQUE` は **NULL を重複扱いしない**ので、
  **根（`parent_id IS NULL`）の同名が通る**（NULL の罠。P2-0 の §5-3 が指摘していた）。
  `coalesce(parent_id, '')` の**式索引**にした（`folder.id` は ULID なので空文字と衝突しない）。
- **`WHERE deleted_at IS NULL`（部分索引）**なので、**論理削除したフォルダの名前は作り直せる**。
- **表の DDL とは別に流す**（`_migrate_v7` が**表の形を先に確かめてから** `_top_up_v7()` で作る）。
  同じ `executescript` に入れると、**別の形の `folder` を先に置かれた DB** で
  `no such column: deleted_at` という**素の `OperationalError`** になり、何が違うか分からない
  （実際に P2-0 の試験 `test_a_squatted_catalog_table_is_refused_loudly` がそうなった）。
- **既に v7 に上がった DB にも当てる**（`migrate()` の早期 return 側の `_top_up_v7`。
  P2-0 のコードで先に v7 になった DB が索引を持たないまま走らないように。**何度呼んでも同じ**）。

### 2.2 ガード（`_check_v7_shape`。**形で見る**）

- `_v7_problems(con, require=…)` に**集める形**へ整理した（`_check_v7_shape` と `v7_conflicts` が
  **同じ物差し**を使う。2 か所に書かない）。
- **式索引は列名では見られない**（`PRAGMA index_info` は式の列を `None` で返す）。そこで
  **`sqlite_master.sql` を空白を詰めた物**を**リテラル**と比べる（列の並び・`coalesce`・
  `WHERE deleted_at IS NULL`・`UNIQUE` が 1 度に見える）。加えて **`cid = -2` の式の列**も見る
  （`ON folder(parent_id, name)` に化けると**根の同名が通る**）。
- `require=False`（移行の**前**）では「**無い**」を違反にしない。**`asset.source` の列と `CHECK` は
  「まだ無い」を違反にしない**（`V7_ASSET_COLUMNS` の `ALTER` が足す。v6 の実データが全部これ）。
  ここを間違えると**実データの v6 が全部読み取り専用になる**（試験 `test_a_clean_v6_database_is_not_a_conflict`）。
- 語彙の `CHECK` の**振る舞い**（`SAVEPOINT` で `kind='robot'` を入れる）は**書き込む接続でだけ**。
  読み取り専用では `v7_conflicts` が**文**だけを見る（1 行も入れない）。

### 2.3 C-2（名前の取り合い）の手当て

`backup.inspect_db()` が `PRAGMA user_version` を読んだ後に **`db.v7_conflicts(con)`**（読むだけ）を呼び、
**在るのに形が違う物**が 1 つでもあれば **`mode=read_only` / `reason=schema_conflict`** にして、
`guidance` と `conflicts`（食い違いの文の一覧）を返す。**`create_app()` は 1 バイトも書かずに
読み取り専用で起動**し、`_db_gate` が書き込みの口を 503 にする。

- **実測**: v6 の合成 DB に `CREATE INDEX ix_folder_parent ON other(x)`（**索引名は DB 全体で一意**）を
  置くと `mode=read_only` / `schema_conflict`・**`db.sqlite3` の sha256 が前後で同じ**・版は 6 のまま
  （`test_a_taken_index_name_is_refused_before_a_byte_is_written`）。
  同じ列名で `deleted_at` の無い `folder` を先に置いた形も同じ（`test_a_squatted_folder_table_…`）。
- **前は**: 移行が `V7_CATALOG_DDL` を流した後で落ちるので、**版 6 のまま `folder_member` と
  `asset` の 3 列だけ在る** DB が残った（`p2-0-audit-triage.md` §5-1 の C-2）。**いまは残らない。**

---

## 3. 画面（`#/folders`。**入口は上部バー**・**4 つ目のバッジは作らない**）

`docs/frontend-design.md` を**先に**直した（§3 の画面の一覧 14・§4.5.1 の常設の入口・§6.1 の文言 11 行・
§11 の 3 行）。実装は `apps/gui/folders.js`（新規 606 行）＋ `index.html` / `app.js` / `styles.css`。

- **入口**: 上部バーの右端（「重複の整理」と「設定」の間）に「**フォルダ**」。**出る条件は無い**。
  **バッジの列（要求・ジョブ・最近の削除）の 4 つ目は作らない**（点検 B5 の規則はそのまま。
  「4 つ目の入口を作らない」は**バッジの列**の話で、行き先の無い画面を増やさないためのもの）。
- **画面**: 左に**木**（名前・枚数・深さの余白）、右に**中身**（サムネイルと「外す」）。
  上に入力＋「作る」（**選んでいるフォルダの下**に作る。選んでいなければ一番上）。
  選んだフォルダの操作は「名前を変える」「フォルダを消す…」。
- **画像を入れるのはライブラリで選んでから**: 下部バーに「**選んだ N 枚をフォルダに入れる…**」
  （0 枚なら枚数を書かず押せない）→ `#/folders?add=<id,id>`。**`add=` がある間だけ**木の各行に
  「ここに入れる」を出す（**画面を 2 つ行き来させない**）。
- **消すのは名前を打ち込ませてから**（`confirm` と同じ語を画面でも使う）。打ち込むまで
  「このフォルダを消す」は押せない（**本物の Chrome で入力して確かめた**）。**画像は消えない**と文で言う。
- **スマートフォルダの中身は条件で計算しない**（この段は**作るだけ**）。中身には 1 行
  「スマートフォルダの条件はまだ使えません。…」を出す（**黙って空にしない**）。
- 文言は `frontend-design.md` §6.1 の 6 規約に合わせた（**中黒で文を繋がない**・英語の内部値を出さない・
  **「枚」は助数詞だけ**・ボタンは「何が起きるか」・1 文 40 字）。**上部の注意書きは 3 文に分けた**
  （「フォルダ」を足すと 1 文が 46 字になった。規則 5 の 40 字が正）。

---

## 4. 作った物（ファイルと行数）

行数は最終形（`read_text().splitlines()`）。「+ / −」は `git diff --numstat`（未追跡は新規）。

| ファイル | 行数 | + / − | 何をしたか |
| --- | --- | --- | --- |
| `src/image_reviewer/folders.py` | **620**（新規） | — | サービス（木・作る・変える・消す・入れる・外す・中身）。**同じ親の一意・循環・語彙・確認**の検査。`FolderService`（読む口は `locked()`、書く口は `transaction()`） |
| `src/image_reviewer/api/folders.py` | **94**（新規） | — | 口 7 経路（8 つの働き）。**人だけ**の検査は `require_human` の 1 か所 |
| `src/image_reviewer/db.py` | 1342 | **+218 / −50** | `V7_UNIQUE_DDL`（`ux_folder_name`）・`V7_EXPRESSION_INDEXES`・`_v7_problems()` / `v7_conflicts()` / `_top_up_v7()` / `db_ulid_seed()`・`_check_v7_shape` の書き直し・`migrate()` の早期 return に `_top_up_v7`・`_migrate_v7` の順序（**表の形を先に見る**） |
| `src/image_reviewer/backup.py` | 1675 | **+26 / −0** | `inspect_db` に `v7_conflicts`（**1 バイトも書かない**）→ `schema_conflict`・`guidance_for` にその案内・`conflicts` の欄 |
| `src/image_reviewer/store.py` | 659 | **+40 / −4** | `SOURCES`・`register()` が **`asset.source` を書く**（語彙外は `ValueError`）・`_asset_dict` の `source` を **`asset.source`** に・`source_url` / `ref_tags` を列から読む（`_parse_ref_tags`） |
| `src/image_reviewer/app.py` | 531 | **+9 / −0** | `FolderService` を `app.state.folders` に・ルーターを載せる |
| `src/image_reviewer/api/__init__.py` | 239 | **+5 / −0** | `folders_of()` |
| `apps/gui/folders.js` | **606**（新規） | — | 画面。純関数（木の平ら化・行・中身・文）と押したときの道（`gui_smoke` が固定） |
| `apps/gui/index.html` | 370 | **+40 / −1** | 上部バーの入口・下部バーの「フォルダに入れる…」・`#folders` の器・注意書きを 3 文に |
| `apps/gui/app.js` | 655 | **+33 / −1** | `#/folders` の道・`wireFolders()`・下部バーの入口 |
| `apps/gui/styles.css` | 1044 | **+96 / −0** | `.fl-*`（2 列・木・中身・確認） |
| `apps/gui/settings.js` | 368 | **+3 / −0** | 読み取り専用の理由に **`schema_conflict`** の 1 行（P2-0 の監査 C-2 の案内。§2-3） |
| `tools/gui_smoke.mjs` | 2718 | **+272 / −0** | **67 検査**（木の形・空の案内・文言・**押す検査**: 開く／行を選ぶ／入れる／外す／作る／変える／消す／スマートフォルダ／`busy`） |
| `tools/gui_layout.mjs` | 2447 | **+365 / −5** | `--screen folders`（**4 幅**）・ライブラリに**上部バーの「フォルダ」の入口**（見える・押す・**書かない**）・`MEASURE_FOLDERS` / `PRESS_FOLDERS` / `PRESS_FOLDERS_ADD`・**移動中の `documentElement` の null を飛ばす**（下の §7-8） |
| `tests/test_p2_1.py` | **878**（新規） | — | **25 件**（下の表） |
| `tests/test_p2_0.py` | 746 | **+15 / −6** | 名前の規則を「同じ親の中で一意」に（**P2-1 の決定**）・`GET /api/folders` の 404 固定を 200 に |
| `tests/test_backup.py` | 2164 | **+15 / −6** | 前提の作り方を**配置に依らない形**に（下の §7-8） |
| `docs/frontend-design.md` | 1207 | **+28 / −3** | §3（画面 14・入口）・§4.5.1（常設の入口 3 つ）・§6.1（文言 11 行・注意書き）・§11（3 行） |
| `docs/design.md` | 2419 | **+11 / −0** | §5.3 の DDL に `ux_folder_name` と、式索引を**形で見る**段落 |
| `README.md` | 421 | **+13 / −9** | テスト 622・`gui_smoke` 482・`gui_layout` 12 本・文書表に本記録・状態に P2-1・`--screen folders` |
| `docs/p2-1-implementation.md` | 新規 | — | これ |

### 試験（`tests/test_p2_1.py` 25 件。docstring に「何を壊すと落ちるか」を書いた）

| 試験 | 何を見るか |
| --- | --- |
| `test_the_same_image_can_be_in_two_folders` | **R2 の線 1**（多対多。`folder_member` が 2 行・両方の中身に出る） |
| `test_removing_from_a_folder_keeps_the_image_and_the_other_folder` | **R2 の線 2**（外すのは 1 行だけ。他のフォルダ・一覧・ファイルはそのまま） |
| `test_deleting_a_folder_keeps_its_images` | **R2 の線 3**（子孫も隠れる・`asset` と `asset_location` が 1 行も変わらない） |
| `test_the_files_do_not_move_when_folders_change` | **R2 の線 4**（作る〜実削除まで通して**署名が同じ**） |
| `test_two_folders_under_the_same_parent_cannot_share_a_name` | 同じ親 422（根どうしも）・別の親は 200・名前の変更でも同じ |
| `test_a_folder_cannot_be_moved_under_its_own_child` | 循環 422（子孫・自分）。循環しない移動は 200 で木が 1 本 |
| `test_a_folder_needs_an_existing_live_parent` | 無い親・隠れた親は 422（500 にしない） |
| `test_deleted_folders_leave_the_tree_and_their_names_can_be_reused` | 論理削除で木から外れ、**名前を作り直せる**（部分索引） |
| `test_a_folder_delete_needs_the_name_to_be_confirmed` | `dry_run` は消さない・`confirm` が無い/違うは 422 |
| `test_purge_removes_the_rows_but_never_the_images` | `purge` で `folder` / `folder_member` が 0・画像 3 枚は残る |
| `test_deleted_images_are_hidden_from_folders_and_counts` | `asset.deleted_at` の画像を中身・件数に出さない |
| `test_adding_members_is_idempotent_and_rejects_unknown_assets` | 冪等（2 回目は `already`）・知らない/片付け済みは 422・外すのは `not_member` |
| `test_the_folder_assets_list_sorts_and_pages` | 並び 3 通りと `next_cursor`・語彙外の `sort` は 422 |
| `test_the_folder_vocabulary_is_checked_with_422` | `kind`・空/長すぎる名前・負の `position`・知らない欄・`actor` の語彙 |
| `test_only_a_human_can_write_the_catalog` | 5 つの口が **403 `human_only`**（ヘッダ無しも）・読む口は 200・403 が書いていない |
| `test_the_new_endpoints_are_guarded` | `Host: evil` / `Content-Type: text/plain` が 403（middleware に載っている） |
| `test_a_smart_folder_needs_a_query_from_the_vocabulary` | 条件は列挙（生の SQL を受けない）・中身に注記 |
| `test_get_folders_writes_nothing` | **`GET` でファイルも全表も変わらない**（木・中身・ページ・`/api/assets`） |
| `test_the_v7_unique_index_is_the_partial_expression_shape` | **期待値リテラル**で `ux_folder_name` の形・根どうしの重複を拒む・論理削除は対象外 |
| `test_the_guard_refuses_a_missing_or_wrong_unique_index` | 索引が無い／`ON folder(parent_id, name)`／部分条件が無い、の 3 形で `RuntimeError` |
| `test_a_clean_v6_database_is_not_a_conflict` | **誤検知しない**（v6 は `ok`） |
| `test_a_taken_index_name_is_refused_before_a_byte_is_written` | **C-2**（`schema_conflict`・sha 不変・版 6 のまま） |
| `test_a_squatted_folder_table_is_refused_before_a_byte_is_written` | 同じ親の一意を守れない形も**先に**断る |
| `test_the_asset_source_comes_from_the_asset_row` | **P2-0 の申し送り**（`source` / `source_url` / `ref_tags` が `asset` の列から） |
| `test_register_refuses_an_unknown_source` | 語彙外の `source` は `ValueError`（`CHECK` で 500 にしない） |

---

## 5. 実行した結果（実測）

### 5-1 三点セット

| 何を | 結果 |
| --- | --- |
| `uv run --no-sync pytest -q`（変更前） | **597 passed**（P2-0 の記録の数と一致） |
| `uv run --no-sync pytest -q`（変更後） | **622 passed・0 failed**（597 ＋ 新規 25。**2 回とも緑**） |
| `node tools/gui_smoke.mjs` | **482 ok / NG 0**（415 ＋ 67） |
| `gui_layout` 12 本 × 4 幅（複製サーバ 8791） | **48 ok / NG 0・12 本とも exit 0**（比較は 3 窓 × 4 ＝ 12 行） |

**12 本**: `compare --count 8`・`requests`・`group --group <id>`・`asset --ids <id>`・`tags`・`jobs`・
`duplicates`・`pending`・`pending --ids`・`library`・`settings`・**`folders`（新）**。

### 5-2 **R2 の線**（設計 §14 の P2 の完了条件）を実機で

複製（実データの `backup()`）を 8791 で立て、**HTTP で**確かめた（`pytest` と同じ経路。§5-1 の
`test_the_same_image_...` が固定している）。

| # | 線 | 実測 |
| --- | --- | --- |
| 1 | **1 枚を 2 つのフォルダに入れられる** | 同じ 1 枚を A・B に入れ、両方の `GET /api/folders/{id}/assets` が 1 枚を返す。`folder_member` は 2 行 |
| 2 | **外しても画像は消えない** | 外すと A は 0 枚・B は 1 枚のまま。`asset` / `asset_location` の行数が同じ・一覧にも出たまま |
| 3 | **フォルダを消しても画像は消えない** | （子を持つ）フォルダを消すと木は 0・`folder_member` 0。`asset` の id の並びと `asset_location` の全列が**前後で同じ**（**この 2 つの値は B-1 の修正の前の実測**。いまは `folder_member` の行は**残る**——[`p2-1-audit-triage.md`](p2-1-audit-triage.md) §1） |
| 4 | **実ファイルは 1 バイトも動かない** | 作る→入れる→外す→名前/親を変える→論理削除→実削除の**全部の後**で、3 枚の **size・mtime_ns・sha256 が同じ** |

### 5-3 `GET` は 1 バイトも書かない

`GET /api/folders`・`GET /api/folders/{id}/assets`（`sort` と `cursor` を変えて 2 回）の前後で、
**`<data>` のファイルの中身（`db.sqlite3-shm` は除く）と全表の中身**が同じ
（`test_get_folders_writes_nothing`）。**件数は毎回数える**ので `count_cache` を埋める必要が無い。

### 5-4 C-2（実データの複製で `create_app` の道）

| 複製に置いた物 | `inspect_db` | 版 | 書いたか |
| --- | --- | --- | --- |
| 何も置かない（v6） | `ok` | 6 | — |
| `CREATE INDEX ix_folder_parent ON other(x)` | **`read_only` / `schema_conflict`** | **6 のまま** | **sha256 が同じ** |
| `deleted_at` の無い `folder`（同じ列名） | **`read_only` / `schema_conflict`** | **6 のまま** | **sha256 が同じ** |

### 5-5 実データ（前後の署名）

`mode=ro` だけで読んだ（`uv run --no-sync python -X utf8 .tmp-p2-1/sig_real.py`）。

- **`user_version` 6**・表 24・**`folder` / `folder_member` / `ux_folder_name` は 0 件**・
  **`asset.source` の列も無い**（v6）。
- `asset` **463**・`deleted_at` **194**・`deletion_log` 194（**閉じた 194**）・`decision` 3・
  `phash_band` 7408。
- `db.sqlite3` の **sha256 `caf7c642e1cb12b2…`・4,083,712 バイト・mtime_ns `1792420938977076500`**
  （P2-0 の記録と同じ）。
- `.data` のファイル **679**・`.backup` は **12 フォルダ**（`pre-migrate` は増えていない）。
- **画像は 1 枚も動いていない**: 生きている登録の `display_path` **268 件がすべて `is_file()`**
  （消えた物 0）。**8790 は pid 3636 のまま**（GET も打っていない・止めていない）。

---

## 6. 壊すと落ちる（**穴としての生き残り 0**。M4 は等価変異と判定）

### 6-1 Python（`src` の写しを `PYTHONPATH` の先頭に置き、`tests/test_p2_1.py` を丸ごと回す）

| # | 壊した物 | 結果 |
| --- | --- | --- |
| M1 | `V7_UNIQUE_DDL` を空に（索引を作らない） | **落ちた**（3 failed・44 errors。`_check_v7_shape` が「索引が無い」で止める） |
| M2 | `ON folder(parent_id, name)`（式索引をやめる） | **落ちた**（3 failed・21 errors。**根の同名が通る**） |
| M3 | `WHERE deleted_at IS NULL` を外す | **落ちた**（3 failed・21 errors） |
| M4 | **サービス層**の一意検査を外す（索引は残す） | **生き残った**——**等価変異**。索引が同じ `IntegrityError` を出し、`create()` の受け（`except sqlite3.IntegrityError`）が**同じ 422 `folder_name_taken`** にする（試験が見る `status` と `code` が同じ）。**M5 で両方外すと落ちる** |
| M5 | M4 ＋ 索引も外す | **落ちた**（3 failed・44 errors） |
| M6 | 循環の検査を外す | **落ちた**（1 failed） |
| M7 | 論理削除で `asset` も消す | **落ちた**（1 failed。R2 の線 3） |
| M8 | 片付け済みの画像を中身に出す | **落ちた**（1 failed） |
| M9 | `GET` が `count_cache` を書く | **落ちた**（1 failed） |
| M10 | 確認の名前を見ない | **落ちた**（1 failed） |
| M11 | `POST` から `require_human` を外す | **落ちた**（1 failed・403 が 200 に） |
| M12 | 出所を `asset_meta.source` に戻す | **落ちた**（1 failed） |

**毎回、写しを読んだことを出した**（`C:\work\image-reviwer\.tmp-p2-1\mut\src\image_reviewer\__init__.py`）。
**変異が 1 回だけ当たったこと**も機械で確かめた（当たらなければ「落ちた」に数えない）。

### 6-2 画面（GUI の写しで `gui_smoke`。**本物の `apps/gui` は 1 行も変えない**）

| # | 壊した物 | 結果 |
| --- | --- | --- |
| G1 | 「ここに入れる」を消す | **落ちた**（3 件 NG） |
| G2 | 名前を打ち込む前でも消す（確認を飛ばす） | **落ちた**（2 件 NG。**POST が 1 回出た**） |
| G3 | 外した後に「画像は消していません」を言わない | **落ちた**（1 件 NG） |
| G4 | 消した後に「画像は消えていません」を言わない | **落ちた**（2 件 NG） |
| G5 | スマートフォルダの注記を出さない | **落ちた**（1 件 NG） |

### 6-3 本物の Chrome（`gui_layout`。1024×700 で。**終わったら sha256 で戻した**）

| # | 壊した物 | 結果 |
| --- | --- | --- |
| L1 | 上部バーの「フォルダ」の入口を消す | **落ちた**（`← 上部バーに「フォルダ」の入口がある, 「フォルダ」を押せない`） |
| L2 | 名前を打ち込む前でも「このフォルダを消す」を押せる | **落ちた**（`← 名前を打ち込むまで消すボタンは押せない`。実測 `goDisabled:false`） |

**控えと戻し**: 変異の前に `apps/gui/index.html` / `folders.js` を控え、終わった後にコピーし直して
**sha256 が同じ**ことを確かめた（`58d33ad82ef7…` / `ce37ae5bbc52…`）。

---

## 7. 自分で決めた点

1. **口は 7 経路**（8 つの働き）。§6.1 の `DELETE` の 2 行は同じ経路（§1）。
2. ~~**論理削除は子孫も隠し、`folder_member` は消す**~~ → **P2-1 の監査 B-1 で「消さない」に直した**
   （§1 の「論理削除の決め」。行は残り、`purge` のときだけ消える）。**画像は触らない**。
   **「戻す」の口はこの段に無い**ので、隠した所属は戻さない（設計 §6.1 にも戻す口は無い）。
3. **件数は `count_cache` を使わず毎回数える**（**正しさ優先**）。設計 §10.2 は「走査・タグ付け・
   判断のあと」に無効化と言うが、**`folder_member` の増減のときにいつ無効にするかが決まっていない**。
   `GET` は書かないので `GET` で埋めることもできない。**実測**（合成 DB: 画像 10,000 枚・
   フォルダ 1,000・所属 10,000 行。**サービスの経路** `folders.tree()` を 5 回、中央値）:
   **6.46 ms**（6.30〜6.73）。1 万枚・1,000 フォルダなら画面の 1 回の読み込みで許せる
   （`GET /api/folders/{id}/assets` は 200 枚で 0.25 ms）。**キャッシュを足すのは、もっと大きな
   木が要るときでよい**（`count_cache` の列は残す）。
4. **名前の上限は 120 文字・階層は 32 段**（設計に数字が無い。画面の 1 行と暴走の防止）。
5. **スマートフォルダは「作れる・条件を検証する」まで**。**条件での絞り込みは計算しない**
   （P2-2 以降）。中身には**そう書いた 1 行**を出す（黙って空にしない）。条件の列挙は §10.2 の 13。
   **`meta.*` は列ではなく `asset_meta.meta_json` の中**なので、条件を計算する段で対応表が要る
   （P2-0 の申し送り E-6 を P2-2 に送る）。
6. **`GET /api/folders/{id}/assets` の改ページは `cursor`（先頭からの件数）**。設計 §10.3 は
   キーセットと言うが、**既存の `GET /api/assets` に揃えた**（画面は `limit=200` で 1 回引く）。
   フォルダの中身は数千枚までなので、この段では実害が無い。**キーセットは P2-2 の申し送り**。
7. **`folder.kind='smart'` にも手で画像を入れられる**（表は同じ）。`kind` を変えたときは
   `manual` に戻すと条件を落とす（条件が残ると「manual なのに条件がある」行ができる）。
8. **既存の 2 つの試験を直した**（P2-1 の決定に合わせる。意味は変えない）:
   - `tests/test_p2_0.py::test_the_catalog_shape_is_the_design_not_the_sketch` は
     **「名前は一意でない」を固定していた**。§16.9 の G-2 (b) で**同じ親の中で一意**に決まったので、
     **別の親の同名は通る**・**同じ親の同名は表が拒む**に直した。`GET /api/folders` の **404 固定**も
     200 に（P2-0 が「P2-1 で作る口」と書いていた物）。
   - `tests/test_backup.py::test_restore_refuses_a_snapshot_whose_bytes_changed` は
     **写しの末尾 1 バイトを反転**し、それが「構造として見ない場所」に在ることに依存していた。
     **v7 に索引を 1 本足しただけで前提の `integrity_check` が落ちた**（実際に踏んだ）ので、
     **設定の値を 1 つ書き換える**形に変えた（中身だけ変わった写し、という意図は同じ。配置に依らない）。
9. **`gui_layout` の `MEASURE_LIBRARY` / `MEASURE_FOLDERS` が `documentElement` の null で落ちる**のを
   直した（**移動の途中の実行文脈**で起きる。実測 2 回）。0 に落として計り続け、**その回だけ飛ばす**。
   これは**前からある壊れやすさ**（P2-1 の変更ではない）だが、**私の実行で踏んだ**ので直した。
10. **`db_ulid_seed()`** を足した（`_check_v7_shape` の probe の名前に時刻を混ぜる。一意索引ができて、
    前のプロセスの probe 行が残っていると「CHECK が拒んだ」と読み違えるため）。

---

## 8. 設計の穴・申し送り

### 8-1 設計の穴（見つけた順）

1. **§10.3 の「すべてキーセット改ページ」と既存の `GET /api/assets`（`cursor` は件数）が食い違う**。
   P2-1 は既存に合わせた（§7-6）。**設計か実装のどちらかを P2-2 で決める**。
2. **`smart_query` のフィールドと列の対応表が設計に無い**（P2-0 の E-6 が「P2-1 で書く」と
   していたが、**条件を計算しないので書いていない**）。`meta.model` / `meta.seed` は
   **`asset_meta.meta_json` の中**で、列ではない。**P2-2 で対応表を書く**。
3. **「フォルダを戻す」口が §6.1 に無い**（論理削除はするが、戻せない）。`#/pending-deletes` の
   「戻す」に相当する物がカタログには無い。**P2-2 の判断**。
4. **`folder_member.position` の並べ替えの口が §6.1 に無い**（P2-0 の §6-3 が「`PATCH
   /api/folders/{id}` はフォルダ自身の `position` だけ」と書いていた）。**P2-1 でも中身の並べ替えは
   できない**（入れた順のまま）。`PATCH .../members {asset_ids}` を足すかを決める。
5. **`asset_meta.source` の意味が設計に書かれていない**（`asset.source` と 2 つある）。P2-1 は
   `asset_meta.source` = 「来歴をどの経路で取ったか」として残し、`_asset_dict` は `asset.source` を
   返すようにした。**§5.1 / §5.2 に 1 行書く**。

### 8-2 申し送り（P2-2 以降）

1. **スマートフォルダの条件を計算する**（§10.2 の 13 の列挙。**対応表を先に設計へ**）。
2. **キーセット改ページ**（§7-6）。
3. **`folder_member` の並べ替え**（§6.1 に口を足す）。
4. **「フォルダを戻す」**（論理削除の取り消し）。
5. **P2 の残り**: 取り込みの 4 経路（D&D / クリップボード / URL / 監視）は `asset.source` の列が
   できたので、それぞれの口で `register(source=…)` を渡す（**P2-1 では `scan` と `drop` の道だけ**）。
6. **実データの v7 化は利用者の再起動のとき**（本記録の時点では v6 のまま）。再起動で
   `.backup/daily/pre-migrate-<日時>/` が取られてから v7 になり、**`ux_folder_name` もそのとき作られる**
   （P2-0 のコードで先に v7 になっていた場合は `_top_up_v7` が作る）。
7. **`.tmp-p2-1/` に残した物**（使い捨て。`.tmp-*/` は gitignore 済み）: スクリプト
   （`make_replica.py`・`mutate.py`・`mutate_gui.py`・`mutate_layout.py`・`sig_real.py`・`pick_ids.py`・
   `ids.py`・`smoke_api.py` ほか）と `logs*/`・`mut*.py`・控え（`.tmp-p2-1/backup/`）・
   **`gui-data/`（実データの複製）と `gui-backups/` は消した**（§10）。`mut/` と `mutgui/` も消した。

---

## 9. 実行したコマンド（再現手順）

```powershell
cd C:\work\image-reviwer
$env:UV_CACHE_DIR = "C:\work\image-reviwer\.uv-cache"

# 1. 三点セット
uv run --no-sync pytest -q                      # 622 passed
uv run --no-sync pytest tests/test_p2_1.py -q   # 25 passed
node tools/gui_smoke.mjs                        # 482 ok / NG 0

# 2. 複製（実データは mode=ro。画像は写さない）とフォルダの前提
uv run --no-sync python -X utf8 .tmp-p2-1/make_replica.py
uv run --no-sync python -X utf8 tools/gui_layout_seed.py `
    --data C:\work\image-reviwer\.tmp-p2-1\gui-data `
    --tags --exclusion --pending --stage3 --backup-error `
    --backup-dir C:\work\image-reviwer\.tmp-p2-1\gui-backups

# 3. サーバ（複製・8791。**8790 は利用者なので触らない**）
$env:IMAGE_REVIEWER_DATA = "C:\work\image-reviwer\.tmp-p2-1\gui-data"
$env:IMAGE_REVIEWER_BACKUP_DIR = "C:\work\image-reviwer\.tmp-p2-1\gui-backups"
.\.venv\Scripts\python.exe -X utf8 -m image_reviewer.cli serve --port 8791

# 4. 画面の計測（12 本 × 4 幅。id は複製の API から）
node tools/gui_layout.mjs --base http://127.0.0.1:8791 --count 8
node tools/gui_layout.mjs --base http://127.0.0.1:8791 --screen requests
node tools/gui_layout.mjs --base http://127.0.0.1:8791 --screen group --group <id>
node tools/gui_layout.mjs --base http://127.0.0.1:8791 --screen asset --ids <id>
node tools/gui_layout.mjs --base http://127.0.0.1:8791 --screen tags
node tools/gui_layout.mjs --base http://127.0.0.1:8791 --screen jobs
node tools/gui_layout.mjs --base http://127.0.0.1:8791 --screen duplicates
node tools/gui_layout.mjs --base http://127.0.0.1:8791 --screen pending
node tools/gui_layout.mjs --base http://127.0.0.1:8791 --screen pending --ids <id>,<id>
node tools/gui_layout.mjs --base http://127.0.0.1:8791 --screen library
node tools/gui_layout.mjs --base http://127.0.0.1:8791 --screen settings
node tools/gui_layout.mjs --base http://127.0.0.1:8791 --screen folders     # 新

# 5. 壊すと落ちる（写しを PYTHONPATH の先頭に。**変異が 1 回だけ当たったことを機械で確認**）
uv run --no-sync python -X utf8 .tmp-p2-1/mutate.py        # 12 通り（等価変異 1）
uv run --no-sync python -X utf8 .tmp-p2-1/mutate_gui.py    # 5 通り（画面の写し）
uv run --no-sync python -X utf8 .tmp-p2-1/mut_l1.py        # 本物の index.html を変異（控えから戻す）
# （L1 / L2 は node を**直接**起動する。Python の子プロセスから Chrome を起こすと
#   %TEMP% に書けず EPERM になる——この環境の罠）

# 6. 実データの署名（mode=ro だけ）
uv run --no-sync python -X utf8 .tmp-p2-1/sig_real.py
```

---

## 10. 後始末（**実データの写しを残さない**）

- **複製サーバ 8791 は自分で止めた**（`/api/health` の `data_dir` が `.tmp-p2-1\gui-data` であることを
  確かめてから **health の `pid`（14020）** を `taskkill /T`）。いま 8791 に何も居ない。
  **8790 は止めていない**（利用者の物。pid 3636 のまま）。
- **消した物**: `.tmp-p2-1/gui-data/`（実データの DB の複製・サムネイル・一時置き場）・
  `.tmp-p2-1/gui-backups/`（控え）・`.tmp-p2-1/mut/`・`.tmp-p2-1/mutgui/`・`.tmp-p2-1/tmp/`・
  `.tmp-p2-1/smoke-data/`（最初の API の煙試験）。**実データ（画像と DB）の写しは 1 つも残していない。**
- **残した物**（スクリプトと結果だけ。`.tmp-p2-1/` は gitignore 済み）: 上の再現手順の
  `*.py`・`backup/`（**画面のファイルの控えだけ**。実データではない）・`logs*/`。
- **`tests/.tmp` に残骸は無い**（`conftest.py` の見張りが 622 件の最後に確かめる）。
