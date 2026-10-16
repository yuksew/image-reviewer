# P6-0（表と契約）の監査報告

- 監査した版: 2026-10-16 の作業ツリー（`db.py` 04:23、`schemas/review-export.schema.json` 04:24、`export.py` / `annotation-export.schema.json` 04:25、`api/export.py` 04:26、`tests/test_db.py` 04:27、`tests/test_export.py` 04:29）。設計は `p6-design.md`（04:16、点検の反映後）。
- **実行できたかどうか: 全部実行できた**（コマンド約 12。ソースは編集せず、実データは `mode=ro`、一時物は `.tmp-audit-redo/p6/`、サーバは `data-p52`（v4 済み）で 8791）:
  - `uv run pytest -q` ×2 → **182 passed, 1 warning**（8.2 / 8.1 s）、`tests/.tmp` 0 → 0 → 0。`node tools/gui_smoke.mjs` → **51 ok**。`node tools/gui_layout.mjs --count 8`（新設の `--count` で API から拾う）→ **すべて ok**（1920×1080 の 3 状態。`--ids` 8 枚でも ok）。プロファイルの残骸 **0**（前回 C2 は直っている）。
  - **移行**: `data-p5`（**v3 の実データのコピー**。263 枚 / まとまり 8 / 判断 87 / 場所 265 / 理由 13）を複製して `db.migrate()` → `user_version` **3 → 4**、**全表の件数が無傷**、`integrity()` が `quick_check ok / foreign_key_violations 0`。もう 2 回呼んでも**列と索引が同じ**。**v1 の DDL → 1 回で v4**、**新規作成（v0 → v4）**の 3 経路で `review_request` / `annotation` / `review_group` / `asset` / `comparison_cache` の**列の並びと索引の集合が完全一致**。
  - **制約**（新規 v4 の DB に直接 INSERT）: `annotation` の 12 形、`review_request` の 9 形、`UPDATE → INSERT` と `INSERT → UPDATE` の順、`EXPLAIN QUERY PLAN` 4 本、**別接続 × 8 スレッド × `BEGIN IMMEDIATE`** の同時投入。
  - **契約**（本物の `jsonschema`、Draft 2020-12）: 2 つの契約の `check_schema`、サーバが返した `scope=all` / `group:` / `asset:` の 3 文書を**新契約**と、**足した 3 つの property を外して復元した旧契約**の両方で検証、P5 時点の 3 文書（`fix2-*.json`）を新契約で検証、`annotation-export` の実例 2 つ（`GET` 形・`POST` 形）、領域なしの注記、片方だけ null、`x=1.5`。
  - **`requests: []` と除外**（HTTP）: `superseded_by` を直接 UPDATE したまとまり S を作り、`GET` の 4 つの `scope`、`include_superseded=1` / `=true`、`POST` の既定と `include_superseded: true`、`GET` が `review.json` を書かないこと、`POST` が書くこと、S の枚に判断を入れて `write_group` が今までどおりファイルを書くこと、決定性、`GET /api/groups` の挙動。
- 総合判定: **使える（条件つき）。** 移行・制約・索引・契約は設計どおりで、実行で裏が取れた。残るのは **(1) 契約に足した `Group.superseded_by` を `review.json` が一度も出さない**（名指しの `scope=group:` でもファイルでも印が消え、読む側は差し替えで閉じたまとまりを普通の `open` と区別できない）、**(2) `GET /api/groups` が `superseded_by` を返さず既定から外しもしない**（設計 §0.3 の「一覧の既定から外す」の半分。P6-1 の宿題として記録）、の 2 点。P6-0 の「機能を足さない」範囲としては、(1) は `_group_doc` に 1 行足すだけなので P6-0 のうちに直すのがよい。

---

## A. 直っていない（必ず直す）

**無し。** 指示書の 1〜6 で「直っていない」ものは無かった。

---

## B. 直っているが別の問題が残る（重大）

| # | 場所 | 問題 | 実行したコマンド / 再現手順 | 提案 |
| --- | --- | --- | --- | --- |
| **B1** | `src/image_reviewer/export.py` `_group_doc`（`superseded_by` を出していない。`grep superseded` は `build()` / `_build_locked()` の 3 か所だけ）、`schemas/review-export.schema.json` `Group.superseded_by`（足した）、`p6-design.md` §6.1「`Group` に `superseded_by` を足す」 | **契約に足した `superseded_by` が、文書に一度も出ない。** 既定で外すのは `scope=all` の `groups[]` だけで、**名指しの `scope=group:<S>`、`scope=asset:`（その画像を含むまとまり）、`include_superseded=1`、そして判断のたびに書く `groups/<S>.json`** はどれも S を**普通の `open` なまとまり**として出す（`superseded_by` 鍵が無い）。設計 §0.3 が確定した「置き換わる」の意味（要求と、まだ決めていないまとまりが置き換わる）は、ファイルを読む側からは見えない。契約の `description` は「入っているまとまりは既定の書き出しに出さない」と書くが、**出したときに印が無い**のは契約の意図と違う | **再現した。** S（`superseded_by='r-new'`）に対して `GET scope=group:S` → `groups[0]` に `superseded_by` 鍵**無し**。`scope=asset:<S の枚>` → S が出て鍵無し。`include_superseded=1` → 14 件に S が出て鍵無し。S の枚に `keep` → 3 秒後の `groups/<S>.json` は `state: open`、`superseded_by` 無し。旧契約（`superseded_by` を外した）でも 3 文書が通る＝**出していない証拠** | `_group_doc` に `"superseded_by": group["superseded_by"]` を 1 行（契約は `["string","null"]` なので null でも通る）。`test_superseded_groups_are_hidden_by_default` に「名指しと `include_superseded` では `superseded_by` が **`'r-new'`** で出る」を足す（いまは隠れることしか見ていない。§F-2） |

---

## C. 中程度

| # | 場所 | 問題 | 実行したコマンド / 再現手順 | 提案 |
| --- | --- | --- | --- | --- |
| **C1** | `src/image_reviewer/review.py` `list_groups` / `_group_state`、`api/groups.py`（`include_superseded` も `superseded_by` も無い。`grep` 0 件）、`p6-design.md` §0.3「`superseded_by` が入ったまとまりは一覧（`GET /api/groups`）の既定と `review.json` の既定から外す」 | **`GET /api/groups` は S を既定で出し、`superseded_by` も返さない。** `GET /api/groups/{S}` にも鍵が無い。設計 §0.3 の「一覧の既定から外す」の半分が未実装。P6-0 は「機能を足さない」段なので**P6-1 の宿題**として記録する（指示書 §2-8） | **再現した。** `GET /api/groups?limit=200` → S が `items` にあり、`superseded_by` 鍵無し。`GET /api/groups/{S}` → `<absent>` | P6-1 で `list_groups(include_superseded=False)` と `_group_state` に `superseded_by` を足す。差し替えを実装する `POST /api/review-requests` と同じ段で |
| **C2** | `db.py` `V4_REQUEST_DDL`（`annotation` の `x REAL, y REAL, w REAL, h REAL` に範囲の `CHECK` が無い）、契約（`x` 等は `number` のみ） | **座標の範囲（0〜1、`w > 0`）は DB でも契約でも縛っていない。** `x=1.5` と `w=0` の行が**入る**（実行で確認）。設計 §0.7 は「サービス層で 422」なので P6-2 の仕事だが、「語彙は DB でも守る」（§0.10）の方針と違い、**表だけが守りになる経路（直接 SQL・将来の取り込み）では通る** | `INSERT ... x=1.5` → OK、`w=0` → OK（`.tmp-audit-redo/p6` の実行） | `CHECK (x IS NULL OR (x BETWEEN 0 AND 1 AND y BETWEEN 0 AND 1 AND w > 0 AND h > 0 AND x + w <= 1 AND y + h <= 1))` を v4 のうちに足す（表を作り直さずに済む今が安い。足すなら v5 にせず**v4 の DDL を直して** `IF NOT EXISTS` の既存 DB に当たらないので、**既に v4 に上がった `data-p52` のような DB には効かない**ことを承知で） |

**確かめた結果、問題なし（実行）**:

- **移行**（§2-1）: 上の要約のとおり。`_migrate_v4` は `executescript(V4_REQUEST_DDL)`（すべて `IF NOT EXISTS`）＋ `PRAGMA table_info(review_group)` を見てから `ALTER TABLE ... ADD COLUMN superseded_by`（`db.py:372-382`）。3 経路の結果が一致し、3 回呼んでも同じ。**v3 の実データのコピーで 8 まとまり・263 枚・87 判断が無傷**（指示書の「12 のまとまり」は `data-p52` の数。`data-p5` は 8）。
- **`annotation` の `CHECK`**（§2-2 / §2-8）: 全部あり → OK、全部 NULL → OK、**`shape='rect'` で座標 NULL → 落ちる**（`AND (shape IS NOT NULL OR x IS NULL)` ではなく最初の `(shape IS NULL) = (x IS NULL)` で落ちる）、`shape` NULL で座標あり → 落ちる、`x` だけ NULL → 落ちる、`h` だけ NULL → 落ちる、`shape='circle'` → 落ちる、`actor='bot'` → 落ちる、無い `asset` / `group` への FK → 落ちる（`PRAGMA foreign_keys = ON`）。**SQLite の式として正しく、2 形だけを通す。** なお末尾の `(shape IS NOT NULL OR x IS NULL)` は前の 4 つの等式から導けるので冗長（害は無い）。
- **`review_request`**（§2-2）: `state='pending'` → 落ちる、`actor='bot'` → 落ちる、同じ `target_key` の 2 本目の `open` → **`UNIQUE constraint failed: review_request.target_key`**、`done` の同じ鍵 → 入る、**`target_key` NULL は 2 本入る**、同じ `client_token` の 2 本目 → 落ちる。索引 5 つ（`ix_request_state` / `ix_request_group` / `ux_request_target_open` / `ux_request_token` / 主キー）が v0 / v1 / v3 のどの経路でも同じ。
- **`UPDATE → INSERT` の順**（§2-8）: 古い `open` を `superseded` に**更新してから** INSERT → 通る。**INSERT を先にすると落ちる**（`UNIQUE constraint failed`）。設計 §0.3 に順序が明記されている（点検 C4 の反映）。`tests/test_db.py:291` も同じ順で書いてある。
- **同時投入**: 別接続 × 8 スレッド × `BEGIN IMMEDIATE`（UPDATE → INSERT）→ 8 本とも成功、**`open` 1 行・`superseded` 7 行**。
- **`EXPLAIN QUERY PLAN`**（§2-2）: `state='open' ORDER BY created_at DESC` → `ix_request_state`、`group_id AND state` → `ix_request_group`、`target_key AND state='open'` → `ux_request_target_open`、`annotation ... asset_id ORDER BY created_at` → `ix_annotation_asset`。
- **契約**（§2-3）: 両契約とも `check_schema` OK。サーバの 3 文書が**新契約で OK**。**旧契約（`target_key` / `actor` / `superseded_by` を外した形）でも OK**＝既存の読み手を壊していない（B1 のとおり、壊さない理由は「出していないから」でもある）。P5 時点の 3 文書も新契約で OK。`annotation-export` の実例（`crops: null` の `GET` 形、`crops` 配列の `POST` 形、領域なしの注記）が OK。2 つの契約の `Annotation` は **説明文を除いて完全一致**（違うのは `shape` の `description` だけ。`tests/test_export.py:884` が同じ比較をしている）。
- **`requests: []`**（§2-4）: `scope=all` / `group:` / `asset:` とも `"requests": []`。`review.json`（POST）にも `groups/<id>.json` にも入る。
- **除外**（§2-4）: `scope=all` の既定で S が**出ない**、`include_superseded=1` / `=true` で出る（13 → 14）、**名指し `scope=group:S` では返る**、`POST` の既定でも出ず、`include_superseded: true` で出る。`GET` は `review.json` を**書かない**（mtime 不変）、`POST` は書く。`write_group`（判断のたびのファイル）は今までどおり書かれる（S の枚に `keep` → 3 秒後にファイルの `review_state: kept`）。
- **決定性**: `scope=all` を 1.1 秒おきに 2 回 → `generated_at` を除いて同一。
- **回帰**（§2-6）: 182 / 51 / `gui_layout` ok。`gui_layout.mjs` は `used=0.5 見出し可視=42%` という前回の指摘（舞台の空き・見出し）を**出力に出すようになった**が合否には入れていない（P6 の範囲外。前回 C1 の宿題のまま）。

---

## D. 軽微

| # | 場所 | 問題 | 提案 |
| --- | --- | --- | --- |
| D1 | `db.py` `V4_REQUEST_DDL` の `annotation` の `CHECK` 最後の項 `(shape IS NOT NULL OR x IS NULL)` | 前の 4 つの等式で `shape` と `x` の NULL 性は既に同じなので、この項は常に真（冗長）。消しても挙動は変わらない | 消すか「読み手のための注記」と書く |
| D2 | `schemas/annotation-export.schema.json` の `Annotation.shape.description`（「座標が全部 null のときは null」）と `review-export` の同じ欄（「rect=矩形、ellipse=楕円。」） | 写しの `description` だけ違う。テストは説明文を除いて比べるので落ちないが、「同じ形を写す」と言いながら文が違う | 両方に同じ文を |
| D3 | `review_request.conditions` / `wants`（TEXT。JSON 配列） | DB は文字列なので `'[]'` と `NULL` の 2 つの「無い」が作れる。契約は配列必須（点検 D1）。P6-1 で `NULL` → `[]` に寄せる規則が要る | P6-1 の実装メモに |
| D4 | `review_group.superseded_by TEXT`（FK 無し） | 新しい要求の id を入れるが `review_request(id)` への参照制約が無い（`review_request.superseded_by` も同じ）。消えない表なので実害は無い | 注記だけ |

---

## E. 設計とのずれ

| 項目 | 状態 |
| --- | --- |
| §2.1 の DDL（`review_request` / `annotation` / 索引 / `ALTER TABLE review_group`） | **一致**（文面どおり。`CHECK` の式も同じ） |
| §6.1「`Group` に `superseded_by` を足す」 | **契約には足したが、文書に出していない**（B1） |
| §0.3 / §6.1「一覧（`GET /api/groups`）の既定から外す」 | **未実装**（C1。P6-1 の宿題） |
| §6.1「`scope=group:<id>` の名指しでは返す」 | **一致**（返る。印は無い） |
| §6.1「`requests` は `required` に入れない」「P6-0 では空」 | **一致** |
| §6.2 `annotation-export`（`abi` は文字列、`Annotation` は写し、`Crop` に `left` / `top`） | **一致**（点検 D2 の反映を確認） |
| §0.7 の座標の範囲 | **DB では縛らない**（C2。設計はサービス層としているので「ずれ」ではなく、方針 §0.10 との整合の話） |
| 設計が黙っているのに実装が決めたこと | `include_superseded` を **`GET` の query と `POST` の body の両方**で受ける（§6.1 は `POST` の `include_superseded: true` と `GET /api/groups` の `?include_superseded=1` を書くが、`GET /api/export/review.json?include_superseded=1` は書いていない）。妥当（読むだけ）。`_referenced_reason_ids()` が `requests[]` の中の `reason_code_id`（P6-1 で `response` に入る）も拾う形になっている（鍵名で拾う）。妥当 |

---

## F. テストが守っていないもの

| # | テスト | 何を主張しているか | 実際に守っているか | 直し方 |
| --- | --- | --- | --- | --- |
| **F1** | `tests/test_db.py:235` `test_migrate_v4_creates_the_request_and_annotation_tables` | v1 → v4 を 1 回で、2 回目も安全、FK 無傷 | **守っている。** `_migrate_v4` を消せば表が無く落ちる。`ALTER` を無条件にすれば 2 回目で `duplicate column` で落ちる。**v3 → v4 と新規作成との一致**は見ていない（今回私が実行で確認） | 「`open_db` の新規と v1→v4 で `table_info` が同じ」を 1 行 |
| **F2** | `tests/test_export.py:861` `test_superseded_groups_are_hidden_by_default` | 既定で隠れ、`include_superseded` と名指しで出る | **半分。** 隠れることは守る（除外の 1 行を消せば落ちる）。**出たときに `superseded_by` が入ること**を見ていないので、B1（鍵を出していない）が**緑のまま** | `named["groups"][0]["superseded_by"] == "r-new"` を足す |
| **F3** | `tests/test_export.py:848` `test_the_document_carries_an_empty_requests_array` | `requests: []` | **守っている。** 鍵を消せば `KeyError` で落ちる。`scope=group:` / `asset:` は見ていないが、同じ `doc` の 1 行なので実害は無い | — |
| **F4** | `tests/test_export.py:884` `test_the_two_contracts_define_the_same_annotation_shape` | 2 契約の `Annotation` が同じ形 | **守っている。** 片方に欄を足す／enum を変えると落ちる（説明文は除く） | — |
| **F5** | `tests/test_db.py:260` `test_annotation_coordinates_are_all_or_nothing` | 2 形だけ | **守っている。** `CHECK` を消せば `pytest.raises` が落ちる。見ていない形（`x` だけ NULL、`shape='circle'`）は今回私が実行で確認 | `x` だけ NULL を 1 つ足す |
| **F6** | `tests/test_db.py:291` `test_the_open_request_index_is_partial_and_ordered` | 部分索引・順序・NULL 鍵・`EXPLAIN` | **守っている。** 索引を外せば `IntegrityError` が出ず落ちる。`EXPLAIN` も見る（設計 §8.1-22） | — |
| **F7** | （無い） | 設計 §8.1-20「本物の `jsonschema` で検証」 | **無い。** `check_contract()` は自前の小さな検査（P5 の F7 と同じ）。今回私が `uv run --no-project --with jsonschema` で実行した | `tools/validate_export.py` を置き、P6-1 の監査でも回す |
| **F8** | （無い） | `GET /api/export/review.json?include_superseded=1` と `POST` の両方で効く（HTTP） | **無い**（`build()` の引数だけ）。今回私が実行で確認 | `test_export_endpoint_shape_with_a_client` に 2 行 |

---

## G. 依頼者への質問（朝に読むので、推奨つきで）

| # | 論点 | 選択肢 | 推奨 |
| --- | --- | --- | --- |
| **G1**（B1） | `superseded_by` を文書に出すのを P6-0 で直すか、P6-1（差し替えの実装）と一緒にするか | (i) いま 1 行足して P6-0 の監査を閉じる ／ (ii) P6-1 で | **(i)**。契約に足した欄が一度も出ない状態で段を閉じると、「契約と文書が一致している」という P6-0 の線が嘘になる |
| **G2**（C2） | 座標の範囲を DB の `CHECK` でも縛るか | (i) 縛る（v4 の DDL を直す。既に v4 の DB には効かない） ／ (ii) サービス層だけ（設計どおり） | **(i)**。`data-p52` 以外に v4 の DB はまだ無い（実データは v3）ので、今なら安い。§0.10「語彙は DB でも守る」と揃う |
| **G3**（D1） | `CHECK` の冗長な項を消すか | (i) 消す ／ (ii) 残す | (ii) でもよい。消すなら F5 のテストで守られている |

---

## H. 確かめられなかったこと

| 項目 | 状態 | 理由 |
| --- | --- | --- |
| 実データ `.data/`（v3）そのものの移行 | **コピーで確認**（`data-p5` 由来。`.data` は `mode=ro` で `user_version=3`、まとまり 0 を確認） | 実データは触らない約束 |
| `ON DELETE CASCADE`（`annotation.asset_id`）の実動作 | **実行していない** | `asset` を消す口が無い（P8）。`PRAGMA foreign_keys = ON` が掛かることは `db.py:89` で確認 |
| `gui_layout.mjs` の 1400×900 / 1200×800 | **`--count 8` の既定が 1920×1080 だけだった** | 前回の 3 窓は `--ids` のときの既定。`--count` 経路でも 3 窓を回すかは道具の仕様（P6 の範囲外） |

---

## 最も重大な 3 件

### 1. 契約に足した `Group.superseded_by` を、文書が一度も出さない（B1）

除外は `scope=all` の既定にだけ効き、名指しの `scope=group:`、`scope=asset:`、`include_superseded=1`、判断のたびの `groups/<id>.json` は、差し替えで閉じたまとまりを**普通の `open`** として出す。旧契約（欄を外した形）でも文書が通ることが、出していない証拠になった。`_group_doc` に 1 行足し、テストに「出たときは `'r-new'`」を足せば P6-0 の線（契約と文書の一致）が本当になる。

### 2. `GET /api/groups` が差し替えで閉じたまとまりを既定で出し、印も返さない（C1。P6-1 の宿題）

設計 §0.3 は「一覧の既定からも外す」と言うが、`list_groups` / `_group_state` は `superseded_by` を知らない。P6-0 は表と契約の段なので直っていなくてよいが、P6-1 で差し替えを実装するときに**同じ段で**入れないと、画面の一覧に閉じたまとまりが残る。

### 3. 座標の範囲は DB で縛っていない（C2）

`x=1.5` と `w=0` の行が入る。設計は 422 をサービス層に置くので P6-2 で守られるが、§0.10 の「語彙は DB でも守る」と違い、直接 SQL や将来の取り込みでは通る。v4 の DB がまだ `data-p52` しか無い今なら `CHECK` を 1 行足すだけで済む。
