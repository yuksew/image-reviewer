> **廃止（2026-10-17。利用者の判断）**: この段は**削除しました**。理由と控えは [`p7-decision.md`](p7-decision.md) を見てください（①PNG を ComfyUI にドラッグすればワークフローが戻るので記録は重複 ②ja2en の英訳も実行すれば取り直せる）。**記録として残しています。**

# P7-0 実装報告（表と契約。**機能は足さない**）

対象: [`docs/p7-design.md`](p7-design.md) §0.1（P7-0 の行）・§0.3・§2.1・§2.2・§6.1・§6.2・§8.1（24〜26・29・34〜36・
41〜43）・§1.2 の 10
点検: [`docs/p7-review-report.md`](p7-review-report.md)（A-2・B-3-1・B-5・C-1〜C-4・D-12・G-3〜G-5）・
[`docs/p7-review-triage.md`](p7-review-triage.md)（**すべて採用**）
監査に渡すもの: この文書＋下の「実行したコマンドと結果」＋ `tools/check_contract_p7.py` ＋
`.tmp-audit-redo/mutate_p7.py` / `mutation_run.py`（**壊すと落ちる 12 通り**）

---

## 1. 作ったもの（行数は PowerShell で数えた実数）

| ファイル | 行 | 何 |
| --- | --- | --- |
| `src/image_reviewer/db.py` | 574（**+140 / -2**） | `SCHEMA_VERSION = 6`、`V6_RECIPE_DDL`（**6 表・10 索引**）、`_migrate_v6()`、`migrate()` の `if current < 6`、docstring（v6 の節） |
| `schemas/recipe-manifest.schema.json` | 111 | **新規**。書き出しの束の契約（§6.1。draft 2020-12・`abi: 0.1`（文字列）・`additionalProperties: false`） |
| `tests/test_db.py` | 791（**+337 / -7**） | **v6 の 7 件**（関数は 23 → 30。移行・1 枚 1 記録・印か理由か・seed 無しの一意・束の再送と索引・削除との関係・語彙）。v5 のテストの版の数字を `db.SCHEMA_VERSION` に直した |
| `tests/test_manifest.py` | 272 | **新規**。17 件（6 関数。契約の形・通る／壊れた物が落ちる 12 通り・`review.json` に足していない・`Reproduction` は既にある） |
| `tools/check_contract_p7.py` | 257 | **新規**。**本物の `jsonschema`**（見本が通る・壊した 10 通りが落ちる・seed 無しも通る・`review.json` に条件が出ない・DB が v6） |
| `README.md` | +12 / -3 | 状態（P7-0 まで・テスト 309 件）・文書表 6 行・`check_contract_p7.py` の行 |
| `.gitignore` | +1 | `.tmp-p7-0/`（`check_contract_p7.py` の捨て場所） |

### v6 で足した 6 表と 10 索引（設計 §2.1 との対応）

| 表 | 何 | 設計の指摘 |
| --- | --- | --- |
| `recipe_record` | 元画像 1 枚の条件の写し。**画像 1 枚に 1 記録**（`ux_recipe_source`） | C-1 / G-5、A-3（`reasons` は記録時の 7 語だけ） |
| `recipe_export_attempt` | **書き出しの束**（manifest・検査・`seed_node`・`client_token` の置き場） | **A-2b**（前の版は束の表が無かった） |
| `recipe_export` | 束の中の 1 ファイル＝1 seed。`marker` は **NULL 可**＋`CHECK` で片方だけ | **A-2a**、A-2c（`COALESCE(seed,'')` の式の索引） |
| `recipe_export_result` | 結果 1 枚。`result_asset_id` は `ON DELETE SET NULL`、合否は上書き | C-3 / G-3、C-4 / G-2 |
| `preset` | 名前を付けた条件。`source_asset_id` は `ON DELETE SET NULL` | C-3 / G-3 |
| `watcher_state` | 監視の既読位置。基準は `baseline_create_time`（ms）、`enabled` は既定 0 | **B-3-1**、E-10（`design.md` の DDL に `updated_at` が無い） |

索引: `ux_recipe_source` / `ux_recipe_token` / `ix_recipe_created` / `ux_attempt_token` /
`ix_attempt_recipe` / `ux_export_attempt_seed`（**式の索引**）/ `ix_export_attempt` / `ix_result_export` /
`ux_result_asset` / `ix_preset_created`。

- **`ALTER TABLE` は使っていない**（新しい表だけ）。だから **`_top_up_v6` は作らない**（v5 は「版を上げずに
  3 列足した」ので `_top_up_v5` が要った）。これは `db.py` の v6 の節と `migrate()` の早期 return の
  コメントに書いた（**監査が見る所**）。
- `design.md` §5.5 の `watcher_state` の DDL との差（`NOT NULL DEFAULT 0` / `baseline_create_time` /
  `updated_at`）は §0.15-10 のとおり。**本文への反映は全段の後**（§12-7）。

---

## 2. 実行したコマンドと結果

```
$env:UV_CACHE_DIR = "C:\work\image-reviwer\.uv-cache"
uv run --no-sync pytest -q                     -> 309 passed（P4 の 285 + 新規 24）
node tools/gui_smoke.mjs                       -> 129 ok（不変）
node tools/gui_layout.mjs --base http://127.0.0.1:8791 --count 8         -> すべて ok（3 窓 × 3 状態）
node tools/gui_layout.mjs --base http://127.0.0.1:8791 --screen requests -> すべて ok
node tools/gui_layout.mjs --base http://127.0.0.1:8791 --screen group --group <id> -> すべて ok
node tools/gui_layout.mjs --base http://127.0.0.1:8791 --screen asset --ids <id>   -> すべて ok
node tools/gui_layout.mjs --base http://127.0.0.1:8791 --screen tags     -> すべて ok（下の但し書き）
node tools/gui_layout.mjs --base http://127.0.0.1:8791 --screen jobs     -> すべて ok
uv run --no-project --with jsonschema python tools/check_contract_p7.py  -> jsonschema 4.26.0 / すべて OK（22 行）
```

- `gui_layout` のサーバは**実データの複製**（`sqlite3` の `backup()` で作り、`open_db` が v6 に上げたもの）を
  8791 で立てた。まとまりは複製に 1 つ作った（`01M51Y57R1815BCRW3EHEC4JGC`）。
- **`--screen tags` は実データ（`tag` 0 件）では NG になる**（「語の行が出る」の検査。P7-0 の変更とは
  無関係）。複製に語 4 つ（英語＋日本語の 2 行）を入れてから回した。手順は
  `.tmp-audit-redo/p7_0_gui_setup.py` / `p7_0_gui_tags.py` に残してある。
- 実データ `.data` は**読むだけ**。前後で `size = 1003520` と `mtime` が**同一**（下の表）。

### 実データと v3 の控えからの移行（`.tmp-audit-redo/p7_0_migrate_real.py`。実行した生の出力）

| 何 | 前 | `migrate()` 1 回の後 |
| --- | --- | --- |
| 実データ `.data` の**複製**（`backup()` で作る） | v5・19 表・`asset` 263・`decision` 3 | **v6・25 表・263・3**（保たれた）・`integrity` は `quick_check: ok` / `foreign_key_violations: 0`・**3 回呼んでも 6** |
| `.backup/pre-p4-20261016-093705`（**v3**）の複製 | v3・12 表・263・3 | **v6・25 表・263・3**（1 回で）・`integrity` 綺麗 |
| 実データ `.data` 本体（再確認） | v5・19 表 | **v5 のまま**（`size` も `mtime` も同じ） |

### 「壊すと落ちる」12 通り（`.tmp-audit-redo/mutation_run.py`）

`P7_MUTATION` で 1 つだけ壊して pytest を回し、**狙ったテストが落ちる**ことを確かめた（12/12）。

| 壊した所 | 落ちたテスト |
| --- | --- |
| M1 `ux_recipe_source` を外す | `test_recipe_record_is_one_per_asset_and_the_token_is_reusable`（＋索引を見る 1 件） |
| M2 式の索引を `(attempt_id, seed)` に戻す | `test_recipe_export_without_a_seed_is_still_unique` |
| M3 印と理由の `CHECK` を `CHECK (1)` にする | `test_recipe_export_needs_exactly_one_of_marker_or_skip_reason` |
| M4 `ON DELETE SET NULL` を外す | `test_deleting_an_asset_keeps_presets_and_results_but_not_records` |
| M5 `ux_attempt_token` を外す | `test_export_attempt_token_is_unique_and_the_indexes_are_used` |
| M6 `_migrate_v6` を呼ばない | `test_migrate_v6_creates_the_recipe_tables`（＋v6 を使う 6 件） |
| M7 `status` の `CHECK` を `CHECK (1)` にする | `test_recipe_vocabularies_are_constrained` |
| M8 `ux_result_asset` を外す | `test_export_attempt_token_is_unique_and_the_indexes_are_used` |
| M9 契約の `seeds.minItems` を 0 にする | `test_the_contract_rejects_broken_manifests[seeds が空]`（＋契約の形） |
| M10 `attempt_id` の `pattern` を外す | `[attempt_id が 6 文字]` |
| M11 `notes.status` の `enum` を外す | `[でたらめな status]` |
| M12 `additionalProperties` を緩める | `[契約に無い鍵（recipes）]`（＋契約の形） |

> 1 回目の実行で **M7 が落ちなかった**（悪い行を同じ画像に続けて入れたので、`status` の `CHECK` ではなく
> `ux_recipe_source` で先に落ちていた＝**壊しても落ちないテスト**）。画像を 1 行ずつ分けて直した（`test_db.py`
> の docstring に理由を書いた）。M5 / M8 は壊し方の文字列が合っておらず、**壊せていなかった**（プラグインが
> 例外で止まっていた）。どちらも直して 12/12 にした。

### 索引が本当に引かれるか（`EXPLAIN QUERY PLAN`。実測）

```
recipe_record WHERE source_asset_id = ?           -> ux_recipe_source
recipe_record WHERE client_token = ?              -> ux_recipe_token
recipe_record ORDER BY created_at DESC, id DESC   -> ix_recipe_created
recipe_export_attempt WHERE recipe_id = ?         -> ix_attempt_recipe
recipe_export_attempt WHERE client_token = ?      -> ux_attempt_token
recipe_export WHERE attempt_id = ? AND COALESCE(seed,'') = ? -> ux_export_attempt_seed
recipe_export WHERE attempt_id = ? AND seed = ?   -> ix_export_attempt（**式の索引に当たらない**）
recipe_export_result WHERE export_id = ?          -> ix_result_export
recipe_export_result WHERE export_id = ? AND result_asset_id = ? -> ux_result_asset
preset ORDER BY created_at DESC, id DESC          -> ix_preset_created
```

**P7-2 へ**: 「同じ束に同じ seed を 2 回」を引くときは `COALESCE(seed,'') = ?` の形にする
（`seed = ?` だと式の索引に当たらない。一意性そのものは `INSERT` の時に索引が守る）。

### 6 表の欄と制約が設計 §2.1 と 1 対 1 か（`.tmp-audit-redo/p7_0_columns.py`）

できた DB に `PRAGMA table_info` を当て、**設計 §2.1 の DDL から写した欄の並び**（順序も）と突き合わせた。

| 表 | 欄 | 結果 |
| --- | --- | --- |
| `recipe_record` | 18 | 一致 |
| `recipe_export_attempt` | 10 | 一致 |
| `recipe_export` | 8 | 一致 |
| `recipe_export_result` | 17 | 一致 |
| `preset` | 7 | 一致 |
| `watcher_state` | 6 | 一致 |

`CHECK` の数も設計どおり（`recipe_record` 4・`recipe_export` 2・`recipe_export_result` 3・
`preset` 1・`recipe_export_attempt` 1）で、`ON DELETE SET NULL` は
`recipe_export_result.result_asset_id` と `preset.source_asset_id` の 2 か所だけ。

---

## 3. 自分で決めた点（設計に書いていない／設計と違う）

1. **`attempt_id` に `"pattern": "^[a-z0-9]{8,}$"` を契約に入れた。** §6.1 の抜粋は `{"type": "string"}` だけ
   だが、同じ設計の §0.7 / D-12 が「**8 文字以上の `[a-z0-9]`**」と決めている。**契約でも守らせる**方が
   よい（6 文字の `r7k2m4` が manifest に出たら落ちる）。**設計に無い追加なので申告する**。
2. **`notes.reasons` は `{"type": "string"}` のまま**（11 語の `enum` にしていない）。manifest は**記録時の
   7 語と書き出し時の 3 語の両方**を出す（§0.6）ので、enum にすると片方を書き漏らした時に落ちる。
   語彙を守るのは `status`（3 語）と `mode` の側。
3. **`marker_skip_reason` の字は `'前提1'`（空白なし）。** 設計 §0.7 の本文は「前提 1」と空白つきで書くが、
   §2.1 の DDL と `CHECK` の値は `'前提1'`。**DDL を正**とした（画面と表で同じ字を使う。§11 の用語も
   空白なし）。
4. `schema` の説明文は**日本語**（既存の `review-export` / `annotation-export` と同じ）。
5. `tests/test_manifest.py` は **`jsonschema` を依存に足さない小さな自前検査**（P6-0 の F7 と同じ二段構え。
   本物は `tools/check_contract_p7.py`）。
6. `check_contract_p7.py` の捨て場所は `.tmp-p7-0/contract`（**`.gitignore` に足した**。P6 の
   `.tmp-p6-1a/` と同じ扱い）。**実在する `manifest.json` があればそれも検証する**（P7-2 以降、この道具が
   そのまま実物の検査になる）。
7. `tests/test_db.py` の v5 のテストが `== 5` を直に書いていたので `db.SCHEMA_VERSION` に直した
   （**P5-3・P4-0 の時に決めた「版の数字を主張し続けない」流儀**。`== 5` のままだと v6 で落ちる）。

---

## 4. 見つけた設計の穴（**P7-1 / P7-2 で決めるもの**。勝手に直していない）

1. **`recipe_export_result.export_id` に `ON DELETE` が無い**（§2.1 のまま）。束（attempt）を消すと
   `recipe_export` は `CASCADE` で消えるが、**結果の行が FK で止める**（`FOREIGN KEY constraint failed`）。
   P7 では束を消さない（manifest の無いフォルダを一覧に出さないだけ）ので実害は無いが、**削除を足す段で
   決める**（P8 の申し送り）。
2. **`export_hashes` の鍵に seed が無いときの形が無い。** §6.1 は「seed（10 進の文字列）→ 鍵」としか
   書かないが、`seeds[].seed` は `null` を取り得る（G-4 の seed 無しの束）のに **JSON の鍵は `null` に
   できない**。`check_contract_p7.py` の見本では **`""`**（空文字）を使っている（契約は鍵の形を縛って
   いないので、`""` でも `"noseed"` でも通る）。**P7-2 で決めて §6.1 に 1 行足す**。
3. **`preset` に `client_token` が無い**（§4.10 の DDL のまま）。プリセット作成の再送で同名が 2 つできる
   （同名を許す方針なので実害は小さいが、「再送で増えない」規律からは外れる）。
4. **印の字の形（`repro-<attempt_id>/seed-<seed>`）を契約が縛っていない。** `expected_prefix` の説明に
   書いてあるだけ。P7-2 が書く時に、契約に `pattern` を足すか決める（足すなら点検 D-12 と揃える）。
5. **`graph_kind` / `captured_source` に `CHECK` が無い**（設計の DDL のまま）。P7-1 が値を決めたら
   `CHECK` を足すか決める（**足すなら v7 ではなく「新しい表なので v6 のまま」にはできない**ので、
   P7-1 の中で `ALTER` を見る形になる）。
6. **実データ `.data` はまだ v5。** 利用者のサーバ（8790）は**古いコードを読み込んだまま動いている**ので
   v5 のまま動く。**次に上げ直した時に v6 へ 1 回で移行する**（複製で同じ道を通して確かめてある）。
   私（実装者）は `.data` を触っていない。
7. **P6 と P4 の文書が `README.md` の文書表に無い**（P6・P4 の段で足し忘れている。**既存の穴**。
   P7-0 では P7 の行だけ足した）。
8. **`TEXT PRIMARY KEY` は NULL を受け付ける**（実測: `watcher_state(name)` に NULL が入り、
   `preset.id` にも入った）。SQLite は `INTEGER PRIMARY KEY` / `WITHOUT ROWID` / `STRICT` 以外の
   主キーに NULL を許す。**既存の表も同じ**（`asset.id` にも NULL が入ることを実測した）ので、
   **P7-0 で形を変えていない**（設計 §2.1 の DDL のまま）。値を入れるのはサービス層（`db.ulid()`）で、
   P4 までの表と同じ前提。**表の作り直し（`STRICT` 化）は P7 の対象外**。
9. **設計 §0.1 / §9 の P7-0 の行は「5 表」と書くが、§2.1 の DDL は 6 表**（点検 A-2b で足した
   `recipe_export_attempt` が一覧に反映されていない）。**§2.1 を正として 6 表を作った**（この文書の §1 の表）。
   設計の一覧を直すのは全段の後の `design.md` 反映の時でよい。

---

## 5. 申し送り（P7-1 へ）

- **v6 の 6 表はまだ 1 行も入っていない**（記録を作るのは P7-1）。`db.py` は表と索引だけ。
- `ux_recipe_source` が「画像 1 枚に 1 記録」を守る。**`mode` を変えた 2 回目は 200 で既存を返す**（§8.1 の 43）。
  記録の口を作る時、`INSERT` の前に `source_asset_id` で引く（索引は上の形で当たる）。
- `reasons` に入れてよいのは**記録時の 7 語だけ**（`missing` / `text_not_captured` / `node_missing` /
  `unresolved` / `version_differs` / `hash_mismatch` / `gpu_differs`）。`text_pinned` などを入れる場所は
  `recipe_export_attempt.checked_json`（**§8.1 の 32 のテストが P7-1 の担当**）。
- `record_json` / `env_snapshot` / `checked_json` は **TEXT（JSON の文字列）**。`NOT NULL` は
  `record_json` と `env_snapshot` だけ（`checked_json` は検査前は NULL）。
- 監査に渡す物: この文書・`tools/check_contract_p7.py`・`.tmp-audit-redo/mutate_p7.py`（壊し方）と
  `mutation_run.py`（12 通りを回す）・`p7_0_migrate_real.py`（実データの複製と v3 の控えからの移行）。
