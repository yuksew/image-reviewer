> **廃止（2026-10-17。利用者の判断）**: この段は**削除しました**。理由と控えは [`p7-decision.md`](p7-decision.md) を見てください（①PNG を ComfyUI にドラッグすればワークフローが戻るので記録は重複 ②ja2en の英訳も実行すれば取り直せる）。**記録として残しています。**

# P7-0 監査報告（v6 の表と契約）— 実行込み

- 日付: 2026-10-16（JST 17:52〜18:10）
- 指示書: `docs/p7-audit-brief-p7-0.md`。実装の記録: `docs/p7-0-implementation.md`（204 行）。
- 対象（コミット `5a20b27`、17:51:58）: `src/image_reviewer/db.py`（574 行、17:38:34。`SCHEMA_VERSION = 6`・`V6_RECIPE_DDL`・`_migrate_v6`）、
  `schemas/recipe-manifest.schema.json`（111 行、17:38:55。新規）、`tests/test_db.py`（+337/-7、17:43:11）、`tests/test_manifest.py`（292 行。新規）、
  `tools/check_contract_p7.py`（270 行。新規）、`README.md`・`.gitignore`。監査中に対象の mtime は変わっていない。
- 設計の版: `docs/p7-design.md` **982 行、17:33:12**（点検の反映後。コミット `3b1ebe4`）。§2.1 が 6 表・10 索引。
- 環境: `uv run --no-sync`。実データ `.data` は `mode=ro` と `backup()` の複製だけ。複製は `.tmp-audit-redo/p70/`（`paths/`・`cons/`・`gui/`）。
  サーバは複製 `gui/` で **8791**（PID 15748。終了後に `netstat` で 0 本を確認）。ComfyUI は触っていない（今回は要らなかった）。
- 触っていないもの: `src/`・`tools/`・`tests/`・`apps/`・`schemas/`・`.data/`（`db.sqlite3` 1,003,520 B・10-15 14:29:51、`-wal` 543,872 B・10-16 15:08:35 のまま）・`.backup/`。
  コミットしていない（`git status` は本報告だけが untracked）。
- 回帰: **pytest 309 passed**（13.19 s）、**gui_smoke 129 ok**、**gui_layout 6 画面（比較・要求・まとまり・注記＋タグ・語の一覧・ジョブ）すべて ok**（3 窓）。

## 判定: **合格**（申し送り 5 件のうち **2 件は持ち越さず P7-0 で決める**ことを条件に）

P7-0 の約束（機能を足さない・v6 の 6 表と 10 索引・契約の新設・`review.json` 不変・移行が何度でも安全）は**すべて実行で裏が取れた**。
設計 §2.1 の DDL と `db.py` の DDL は**コメントを除くと文が 16 本とも同一**。4 つの道（新規・v1・v3 の控え・v5 の実データ複製）が
**`sqlite_master` 全体で同一の v6** になり、263 枚と判断 3 件は無傷。制約は 1 つずつ入れて確かめた（A-2 の 3 点を含む）。
実装者の壊し方 12 通りは私の環境でも 12/12 で狙ったテストが落ちた（M7 の直し、M5 / M8 の壊し方とも効いている）。

**最も重大な 3 件**

1. **F-1 外部キーと CASCADE に テストが無い。** 私が足した壊し方 8 通りのうち **5 通りをテストが捕まえない**: `recipe_export.attempt_id` の
   `ON DELETE CASCADE` を外す（X1）、`recipe_export_attempt.recipe_id` の `REFERENCES` を外す（X2）、`recipe_export_result.export_id` の `REFERENCES` を外す（X4）、
   `ix_export_attempt` を外す（X3）、契約の `seeds[].seed` に `integer` を許す（X6）。どれも **30/30・17/17 で緑のまま**。DDL の約束のうち 3 本（束→ファイルの連鎖削除・束→記録・結果→ファイルの参照）が守られていない。
   P7-1 の最初に 3 件（`constraints.py` の手順そのまま）を足す。
2. **C-1 申し送り 1 と 4 は持ち越せない。** SQLite は `ALTER TABLE` で **`CHECK` を足せず、外部キーの `ON DELETE` も変えられない**（表の作り直しが要る）。
   利用者のサーバを次に立て直した時点で `.data` は v6 になるので、**v6 の表が空のいま**（P7-0）が唯一の安い機会。`graph_kind` / `captured_source` の `CHECK` と
   `recipe_export_result.export_id` の `ON DELETE` を**いま決めて入れる**（値は設計で既に決まっている。G-1 / G-2）。実装の記録 §4-5 の「`ALTER` を見る形」は `CHECK` には当てはまらない。
3. **E-1 設計の字が DDL と食い違う 2 か所。** `marker_skip_reason` は DDL の `'前提1'`（空白なし）が正だが、§0.7・§1.2 線 5・§5.1 は「前提 1」（空白あり）。
   実行で **空白ありは `CHECK` で落ちる**。また §2.2 と §8.1-29 は **`ix_export_recipe`** を挙げるが、その索引は無い（`ix_attempt_recipe` に改名済み）。
   §0.1 / §9 の「5 表」も §2.1 の 6 表に直す。

---

## A. 直っていない／設計の約束が成り立たない

- 無し。点検 A-2 の 3 点（`marker` NULL 可＋`CHECK`、束の表と `client_token`、`COALESCE(seed,'')` の式の索引）は**実行で成り立つ**（C-0）。

## B. 重大

- 無し。

## C. 中程度

### C-0 確かめた結果、問題なし（1 行ずつ。実行したもの）

- **移行の 4 つの道が同じ**（`.tmp-audit-redo/p70/paths.py`）: 新規 / v1 の DDL → `migrate()` / `.backup/pre-p4-20261016-093705`（v3・263・3）の複製 / `.data`（v5・263・3）の複製。
  4 つとも **v6・`integrity` ok・FK 違反 0**。v6 の 16 オブジェクト（6 表・10 索引）の `sql` が**新規と完全一致**、**他の全オブジェクトも差 0**。v3・v5 の道で **263 枚・判断 3 件が保たれる**。
- **3 回呼び**: v5 複製で `migrate()` を 3 回 → 6 / 6 / 6、**`sqlite_master` 全体が不変**。
- **`_top_up_v6` が無い判断**: 妥当。v6 は新表だけで `ALTER` が無い。早期 return 側の `_top_up_v5` は v6 の DB でも冪等（上の 3 回呼びで確認）。
- **設計 §2.1 と `db.py` の 1 対 1**（`ddl_diff.py`）: コメントと空白を落として **16 文とも同一**。実装者の `p7_0_columns.py`（欄の並びと NOT NULL）も同じ結論。
- **制約**（`constraints.py`。v5 複製を v6 に上げた DB、`PRAGMA foreign_keys = 1`）: 同じ画像の 2 記録 → `ux_recipe_source` で落ちる／同じ `client_token` の 2 記録 → `ux_recipe_token`／
  同じ token の 2 束 → `ux_attempt_token`、NULL は何本でも／**同じ束・同じ seed → `ux_export_attempt_seed`、seed NULL の 2 本目も落ちる、seed `''` も NULL と衝突する**／
  印と理由の**両方・どちらも無し → `CHECK`**／`'前提 1'`（空白） → `CHECK`／`recipe_id` が無い束 → FK／同じ結果画像の 2 行 → `ux_result_asset`、`result_asset_id` NULL は何行でも。
- **`ON DELETE` が実際に効く**: 記録のある画像の削除 → **FK で落ちる（RESTRICT）**／プリセットと結果が指す画像の削除 → **両方 `NULL` になって行は残る（SET NULL）**／
  束のある記録の削除 → 落ちる／束の削除 → **`recipe_export` が消える（CASCADE）**。ただし結果の行があると束は消せない（申し送り 1。C-1）。
- **索引が引かれる**（`EXPLAIN QUERY PLAN`、12 本）: 10 索引すべて意図した問い合わせで使われる。`COALESCE(seed,'') = ?` は式の索引、`seed = ?` は `ix_export_attempt` に落ちる（実装者の申し送りどおり）。
- **契約**（本物の `jsonschema` 4.26.0）: `check_contract_p7.py` が **22 行すべて OK**（スキーマが draft 2020-12 として正しい・見本が通る・seed 無しの束も通る・壊した 10 通りが落ちる・v6・`review.json` に `recipes` / `presets` が出ない・既存契約を通る）。
  `notes` は型つき（`status` enum・`reasons` 配列・`inspected` boolean・`instruction`）、`mode` enum、`export_hashes` の値 `^sha256:`、`seeds[].seed` と `source.seed` は文字列。
- **`review.json` を本物のサーバで**（`get_check.py`。複製に `recipe_record` / `preset` / 束 / ファイル / 結果を 1 行ずつ入れてから 8791 を起動）: `GET /api/export/review.json`（と `?scope=all`）は 148,387 B、
  上位の鍵は `abi` / `assets` / `generated_at` / `generator` / `groups` / `reason_codes` / `requests` / `schema` / `scope` だけ。**文書のどこにも `recipes` / `presets` / `recipe_hash` / `attempt_id` が無い**。`review-export` の契約を通る（`Asset` も `additionalProperties: false`）。
- **`GET` が書かない**: 13 本の `GET`（`health` / `stats` / `assets` / `assets/{id}` / `graph` / `tags` / `annotations` / `groups` / `tags?known=all` / `jobs` / `review.json` ×2）の前後で、
  複製フォルダの**全ファイルの size と mtime**と **`recipe_*` / `preset` / `watcher_state` / `decision` / `review_group` の行数**が同一。
- **壊すと落ちる 12 通り**（`.tmp-audit-redo/mutation_run.py` を私が実行）: **12/12** で狙ったテストが落ちた。M7（`status` の `CHECK`）は `test_recipe_vocabularies_are_constrained` だけが落ちる＝画像を分けた直しが効いている。
  M5 / M8 は `test_export_attempt_token_is_unique_and_the_indexes_are_used` が落ちる（M5 は一意性、**M8 は `EXPLAIN` の行**で捕まる）。実行後に `schemas/` は元に戻っている（`git status` 空）。
- **`gui_layout` の `--screen tags`**: 実装者の手順（複製に語 4 つと語釈）を自分の複製で再現して ok（`rows=3`、`語彙あり`）。
- **`TEXT PRIMARY KEY` が NULL を受ける**（実装者の記録 §4-8）: 実測で `recipe_record.id = NULL` が入った。既存の表と同じ前提（サービス層の `db.ulid()`）で、P7-0 で直す物ではない。

### C-1 申し送り 5 件の判定（指示書 2-6）

| # | 申し送り | 判定 | 根拠 |
| --- | --- | --- | --- |
| 1 | `recipe_export_result.export_id` に `ON DELETE` が無い | **持ち越さない。いま決める** | FK の `ON DELETE` は `ALTER` で変えられず**表の作り直し**になる。いまは全表が空。実測: 結果のある束は `FOREIGN KEY constraint failed` で消せない（束→ファイルは CASCADE なのに、ファイル→結果で止まる＝中途半端）。推奨は **`ON DELETE CASCADE`**（束を消すなら結果も消える。G-1） |
| 2 | `export_hashes` の seed 無しの鍵（`""`） | 持ち越してよい（P7-2） | 契約は鍵の形を縛っていない。推奨は **`"noseed"`**（`expected_prefix` の `…/noseed` とファイル名 `noseed.json` と同じ字。`""` は人が読めない。G-3） |
| 3 | `preset` に `client_token` が無い | 持ち越してよい（P7-1 / P7-4） | 列の追加は `ALTER TABLE ADD COLUMN` で足せる（v7 か `_top_up`）。ただし**いま足す方が安い**（1 行） |
| 4 | `graph_kind` / `captured_source` に `CHECK` が無い | **持ち越さない。いま決める** | **`CHECK` は `ALTER` で足せない**（記録 §4-5「`ALTER` を見る形」は誤り）。値は設計で決まっている: `graph_kind IN ('api', 'api+ui')`（§2.1 の注・`provenance()` の `graph_format`）、`captured_source IN ('comfyui_history', 'sidecar', 'textgenerate', 'manual')`。**G-2** |
| 5 | §0.1 / §9 の「5 表」と §2.1 の「6 表」 | **§2.1 を正とした判断は妥当**。持ち越してよい（文書の直し） | 6 表目（`recipe_export_attempt`）は点検 A-2b で足したもので、§0.1 / §9 の一覧が追従していないだけ。E-1 |

- 同じ理由で、**`verdict` と `verdict_actor` の対**（合否を入れたら誰が、も必ず入る）を `CHECK ((verdict IS NULL) = (verdict_actor IS NULL))` で縛るなら**いま**。実測: `verdict='same'`・`verdict_actor=NULL` が入る。P7-3 のサービス層で揃えるなら不要（G-2 に含める）。

### C-2 `ix_export_attempt` は `ux_export_attempt_seed` と重なる（設計 §2.1 もそう書いているので、設計側の直し）

- 実測: `ix_export_attempt` を落としても `WHERE attempt_id = ?` は **`ux_export_attempt_seed`（先頭列が `attempt_id`）で引かれる**。P5 の監査 D1 と同じ型（「`ix_comparison_a` は主キーの前置と重なるので作らない」）。
  索引 1 本ぶん書き込みが増えるだけなので中程度。**設計 §2.1 / §2.2 から外し、`db.py` も合わせる**（表は空なので `DROP INDEX` で済む。P7-1 で）。

### C-3 契約の縛りが片寄っている（`contract_extra.py`。本物の `jsonschema`。実装者の 10 通りの外）

| 文書 | 結果 | 判定 |
| --- | --- | --- |
| `recipe_hash` が `sha256:` で始まらない | **通る** | `export_hashes` の値は `^sha256:` で縛るのに `recipe_hash` は自由。**揃える**（1 行） |
| `generated_at` が無い | 通る | `required` に無い。manifest に時刻が無いと「いつの束か」が分からない。**`required` に足す**のを勧める |
| `marker_skipped` が無い | 通る | `required` に無い。「付けたなら null」と「書き忘れ」を区別できない。**`required` に足す** |
| `export_hashes: {}` | 通る | `seeds` は `minItems: 1` なのに鍵→鍵の表は空でよい。`minProperties: 1` を |
| `expected_prefix: "whatever"` | 通る | 申し送り 4（印の形を縛らない）。P7-2 で `^repro-[a-z0-9]{8,}/(seed-[0-9]+|noseed)$` を足すか決める |
| `notes.reasons: ["banana"]` | 通る | 実装者の決定 2（enum にしない）。下の「自分で決めた点」参照 |
| `seeds[].seed: 1`（数値）、`source.seed: 123`、`attempt_id` 大文字、`abi: "1"` | **落ちる** | 期待どおり |
| `seeds` に同じ seed の 2 件、`source.size: -1`、`file: ""` | 通る | 軽微（D） |

### C-4 `watcher_state` と `preset` の約束のうち、テストが見ているのは一部

- `watcher_state.enabled` の既定 0 はテストが捕まえる（私の X5 で落ちた）。`baseline_create_time` が **INTEGER（ms）** であることと `name` が主キーであることは見ていない（軽微。P7-3 で監視を作るときに足す）。

## D. 軽微

- D-1 `contract_extra.py` の結果に「`marker_skipped: 前提2` なのに `expected_prefix` に印」が通る: 契約は横の整合を見ない（`jsonschema` では書きにくい）。P7-2 の書き手が守る。
- D-2 `tests/test_manifest.py` の自前検査は `$ref` を 1 段しか解かず `enum` に `null` を含む形（`marker_skipped`）を扱っているが、本物の `jsonschema` と同じ結果だった（12 通り）。二段構え（本物は `check_contract_p7.py`）は P6-0 と同じで妥当。
- D-3 `check_contract_p7.py` は `.tmp-p7-0/contract` を**残す**（私の実行でも残った）。`.gitignore` 済み。実行のたびに消して作り直すので溜まらない。
- D-4 README の文書表に P6 / P4 の行が無い（実装者の記録 §4-7。既存の穴）。P7 の行は足されている。
- D-5 実装者の記録 §2 の `uv run --no-project --with jsonschema` と指示書 §0 の `--no-sync --with jsonschema` はどちらでも通った（私は `--no-sync` で実行）。
- D-6 `recipe_record.id` などの `TEXT PRIMARY KEY` は NULL を受ける（C-0 の最後）。P7-1 のサービス層が `db.ulid()` を必ず入れる。

## E. 設計とのずれ（実装が決めた所を含む）

| # | 設計 | 実装 | 判定 |
| --- | --- | --- | --- |
| E-1 | §0.7・§1.2 線 5・§5.1「前提 1」（空白あり） | DDL と契約は `'前提1'` | **実装（DDL）が正**。設計の 3 か所を直す。空白ありは `CHECK` で落ちる（実測） |
| E-2 | §2.2・§8.1-29 の `ix_export_recipe` | `ix_attempt_recipe` | 設計の名残り。直す |
| E-3 | §0.1・§9「5 表」 | 6 表 | 設計の一覧を直す（C-1 の 5） |
| E-4 | §6.1 `attempt_id: {"type": "string"}` | `pattern ^[a-z0-9]{8,}$` | 実装者の決定 1。**妥当**（§0.7 / 点検 D-12 と一致。契約で 6 文字を落とす） |
| E-5 | §6.1 `notes.reasons` は `items: string` | enum にしない | 実装者の決定 2。**条件付き**: 語彙は 11 語で固定（§4.5）なので enum にできる。いまは書き手が無いので保留でよいが、**P7-2 で書き手ができたら enum にする**（でたらめが通るのを C-3 で確認） |
| E-6 | — | `_top_up_v6` を作らない | 実装者の決定 4。**妥当**（4 つの道が同一。C-0） |
| E-7 | `design.md` §5.5 `watcher_state`（`enabled INTEGER`、`updated_at` / `baseline_create_time` 無し） | `NOT NULL DEFAULT 0` ＋ 2 列 | P7 の設計 §0.15-10 のとおり。`design.md` への反映は全段の後（§12-7） |
| E-8 | §2.1 の `ix_export_attempt` | そのまま作った | 設計どおりだが重複（C-2）。設計側を直す |

## F. テストで守れないもの

| テスト（壊し方） | 判定 | 根拠と直し方 |
| --- | --- | --- |
| **X1** `recipe_export.attempt_id` の `ON DELETE CASCADE` を外す | **落ちない**（30 passed） | 束を消す試験が無い。`constraints.py` の「束 a3 を消す → e8 が消える」を `test_db.py` に |
| **X2** `recipe_export_attempt.recipe_id` の `REFERENCES` を外す | **落ちない** | 記録の無い束・束のある記録の削除、どちらも試していない。「`recipe_id='nope'` の束 → FK」「束のある記録の削除 → FK」を足す |
| **X4** `recipe_export_result.export_id` の `REFERENCES` を外す | **落ちない** | 「`export_id='nope'` の結果 → FK」を足す。C-1 の 1 で `ON DELETE` を決めたらその試験も |
| **X3** `ix_export_attempt` を外す | 落ちない | 重複索引なので落ちなくてよい（C-2 で外す側） |
| **X6** 契約の `seeds[].seed` に `integer` を許す | 落ちない（17 passed） | `test_the_contract_rejects_broken_manifests` に「`seeds[].seed` が数値」を足す（`source.seed` も）。点検 B-6 の論点 |
| X5 `watcher_state.enabled` の既定を 1 に | 落ちる | 期待どおり |
| X7 `source.required` を空に | 落ちる | 期待どおり |
| X8 `export_hashes` の `pattern` を外す | 落ちる | 期待どおり |
| M1〜M12（実装者） | すべて落ちる | 12/12。M7・M5・M8 の直しは効いている |
| `test_migrate_v6_creates_the_recipe_tables` の「3 回呼んでも同じ」 | 表の**名前**しか比べていない | `sqlite_master` の `sql` まで比べる（`paths.py` の形）。いまは通るが、索引だけ消える壊し方を見逃す |

## G. 依頼者への質問（推奨つき。待たずに推奨で進めてよい）

| # | 論点 | 選択肢 | 推奨 |
| --- | --- | --- | --- |
| G-1 | `recipe_export_result.export_id` の `ON DELETE`（C-1 の 1） | (a) `CASCADE`（束を消すと結果も消える）/ (b) RESTRICT（結果があると束は消せない）/ (c) `SET NULL`（結果が宙に浮く） | **(a)**。束→ファイルが CASCADE なのでそれと揃える。P8 が「束を消す」口を作るときに迷わない。**P7-0 で入れる**（表が空のいま） |
| G-2 | `graph_kind` / `captured_source` の `CHECK`（C-1 の 4）と `verdict` / `verdict_actor` の対 | (a) 3 つとも P7-0 で入れる / (b) サービス層だけで守る | **(a)**。家風「`CHECK` を使う」と、`ALTER` で後から足せない事実から。値: `graph_kind IN ('api','api+ui')`、`captured_source IN ('comfyui_history','sidecar','textgenerate','manual')`、`CHECK ((verdict IS NULL) = (verdict_actor IS NULL))` |
| G-3 | seed 無しの `export_hashes` の鍵（申し送り 2） | (a) `"noseed"` / (b) `""` | **(a)**。`expected_prefix` とファイル名と同じ字 |
| G-4 | `ix_export_attempt`（C-2） | (a) 設計と DDL から外す / (b) 残す | **(a)**。P5 の D1 と同じ |
| G-5 | 契約の `required` に `generated_at` と `marker_skipped` を足す（C-3） | (a) 足す / (b) 任意のまま | **(a)**。P7-2 の書き手は必ず両方書くので失う物が無い |

## H. 確かめられなかったこと・注記・後始末

**確かめていない**

- ComfyUI は触っていない（P7-0 に ComfyUI の要素が無い）。
- 性能は測っていない（表と索引だけ。v6 の移行は複製 1.1 MB で体感 0 秒。数値は P7-1 以降）。
- `watcher_state` の列の型（`baseline_create_time INTEGER`）の試験は無い（C-4）。P7-3 で。
- 利用者のサーバ（8790）が次に立ち上がるときの実データの移行は、**複製で同じ道**（v5 → v6）を通して確かめただけ。本体は v5 のまま。

**紛らわしい出力の注記**

- `contract_extra.out.txt` の日本語は cp932 の化け（`PYTHONUTF8` を付け忘れた）。結果は `jsonschema` の英語の文で読める（C-3 の表に写した）。
- `constraints.out.txt` の `'�O��1'` は `'前提1'` の化け（同上）。
- サーバの background task は `taskkill` で止めたので「exit code 1」と出るが、クラッシュではない（起動後に 13 本の `GET` と 6 画面に応えている）。
- `layout.out.txt` の「まとまり」の `POST=1` は検査が意図的に押した判断の 1 回（`GET` の無副作用の比較はその**前**に取った）。

**実行したコマンドと結果（再現手順）**

```powershell
cd C:\work\image-reviwer; $env:UV_CACHE_DIR = "C:\work\image-reviwer\.uv-cache"; $env:PYTHONUTF8 = "1"
uv run --no-sync pytest -q                                               # 309 passed, 1 warning in 13.19s
node tools/gui_smoke.mjs                                                 # すべて ok（ok の行 129）
uv run --no-sync --with jsonschema python tools/check_contract_p7.py     # jsonschema 4.26.0 / 22 行すべて OK
.venv\Scripts\python.exe .tmp-audit-redo\p7_0_migrate_real.py            # v5 複製 → v6（263・3・integrity ok・3 回で 6）、v3 控え → v6、.data は size/mtime 同じ
.venv\Scripts\python.exe .tmp-audit-redo\mutation_run.py                 # 12 通り中 12 通りで狙ったテストが落ちた
.venv\Scripts\python.exe .tmp-audit-redo\p70\paths.py                    # 4 つの道の sqlite_master が同一、3 回呼びで不変
.venv\Scripts\python.exe .tmp-audit-redo\p70\ddl_diff.py                 # 設計 §2.1 と V6_RECIPE_DDL: 16 文とも同一
.venv\Scripts\python.exe .tmp-audit-redo\p70\constraints.py              # 制約・ON DELETE・EXPLAIN 12 本（C-0）
uv run --no-sync --with jsonschema python .tmp-audit-redo\p70\contract_extra.py   # 17 通り（C-3）
# 追加の壊し方 8 通り（PYTHONPATH=.tmp-audit-redo\p70、-p mutate_extra、P7X_MUTATION=X1..X8）→ X1/X2/X3/X4/X6 は緑のまま（F）
.venv\Scripts\python.exe .tmp-audit-redo\p70\gui_setup.py; .venv\Scripts\python.exe .tmp-audit-redo\p70\gui_tags.py   # 複製（v6）＋まとまり＋語 4 つ
# 複製に recipe_record / preset / 束 / ファイル / 結果を 1 行ずつ入れてから
$env:IMAGE_REVIEWER_DATA = "C:\work\image-reviwer\.tmp-audit-redo\p70\gui"; uv run --no-sync image-reviewer serve --port 8791
.venv\Scripts\python.exe .tmp-audit-redo\p70\get_check.py                # 13 本の GET 前後でファイルと行数が同一、review.json に recipes/presets 無し、契約を通る
node tools/gui_layout.mjs --base http://127.0.0.1:8791 --count 8 / --screen requests / group --group 01M51YQHN7857A24MTW48H5AEW / asset --ids 01M4Z0KJS58V2SAJBGTG1TRFK5 / tags / jobs   # 6 画面すべて ok
taskkill /PID 15748 /F /T                                                # netstat で 8791 の LISTENING 0 本
```

**後始末**

- 残した物: `.tmp-audit-redo/p70/`（8 MB。複製 3 つ・スクリプト 8 本・出力）、`.tmp-p7-0/contract`（`check_contract_p7.py` の捨て場所。`.gitignore` 済み）。実装者の `.tmp-audit-redo/p7-0-*` と `mutation_run.py` 等は触っていない。消してよい。
- 消した物: 無し。サーバ 8791 は停止。
- `.data/` の mtime・size は不変。`src/` / `schemas/` / `tests/` に監査中の変更は無い（`git status` は本報告だけ）。

---

## 最も重大な 3 件（再掲）

1. **F-1** 外部キーと CASCADE の 3 本（束→ファイルの CASCADE、束→記録、結果→ファイル）にテストが無く、外しても 30/30 で緑。P7-1 の最初に足す。
2. **C-1** 申し送り 1（`export_id` の `ON DELETE`）と 4（`graph_kind` / `captured_source` の `CHECK`）は `ALTER` で後から足せないので、表が空の **P7-0 で決めて入れる**（G-1 / G-2）。
3. **E-1〜E-3** 設計の字の直し: `前提1`（空白なし）、`ix_export_recipe` → `ix_attempt_recipe`、「5 表」→ 6 表。
