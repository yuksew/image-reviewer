> **廃止（2026-10-17。利用者の判断）**: この段は**削除しました**。理由と控えは [`p7-decision.md`](p7-decision.md) を見てください（①PNG を ComfyUI にドラッグすればワークフローが戻るので記録は重複 ②ja2en の英訳も実行すれば取り直せる）。**記録として残しています。**

# P7-0 の監査の仕分け（Fable の監査 → どう直したか）

- 監査報告: [`p7-0-audit-report.md`](p7-0-audit-report.md)（**判定: 合格**。申し送り 5 件のうち **2 件は P7-0 で決める**ことが条件）
- 立場: **推奨（G-1〜G-5）はすべて採用**。**表が空のうちに `CHECK` と `ON DELETE` を入れた**（SQLite は `ALTER` で `CHECK` を足せない）。
- 直したのは私（親）。

## 決定と反映（G-1〜G-5）

| # | 指摘 | どうしたか |
| --- | --- | --- |
| **G-1 / C-1-1** | `recipe_export_result.export_id` に `ON DELETE` が無い（束を消すと結果が FK で止まる） | **`CASCADE`** に（`db.py` の `V6_RECIPE_DDL`）。束 → ファイル → 結果の**連鎖**が効くことを実データの複製で確認 |
| **G-2 / C-1-4** | `graph_kind` / `captured_source` / `verdict` と `verdict_actor` の対が**サービス層だけ**の約束 | **`CHECK` を 3 本**足した（`graph_kind IN ('api','api+ui')`・`captured_source IN ('comfyui_history','sidecar','textgenerate','manual')`・`CHECK ((verdict IS NULL) = (verdict_actor IS NULL))`）。**v7 は作らず v6 の DDL を直した**（v6 の表は空・`.data` は v5 だったため） |
| **G-3** | seed 無しの `export_hashes` の鍵が設計に無い | **`"noseed"`** と決め、設計 §6.1 に書いた |
| **G-4 / C-2** | `ix_export_attempt` が主キーの前置と重複 | **DDL と設計から外した**（`ix_attempt_recipe` が同じ役目。P5 の D1 と同じ判断） |
| **G-5 / C-3** | 契約の `required` に `generated_at` と `marker_skipped` が無い | **足した**（`schemas/recipe-manifest.schema.json`）。契約そのものの形を見るテストの期待値も更新 |

## テストの穴（F-1。監査者が「壊しても落ちない」と見つけた 5 通り）

**5 通りすべてに「壊すと落ちる」テストを足し、自分で壊して 5/5 落ちることを確かめた**（`tests/test_db.py` に 6 件・`tests/test_manifest.py` に 2 例）：

| 壊し方 | 足したテスト | 壊したときの結果 |
| --- | --- | --- |
| **X1** `recipe_export.attempt_id` の `CASCADE` を外す | `test_deleting_an_attempt_cascades_to_files_and_results` | **落ちた** ✓ |
| **X2** `recipe_export_attempt.recipe_id` の `REFERENCES` を外す | `test_an_attempt_needs_a_real_recipe_and_a_record_with_attempts_cannot_go`（知らない `recipe_id` の束／束のある記録の削除） | **落ちた** ✓ |
| **X4** `recipe_export_result.export_id` の `REFERENCES` を外す | `test_a_result_needs_a_real_export` | **落ちた** ✓ |
| **X3** `ix_attempt_recipe` を外す | `test_the_attempt_recipe_index_is_used_and_the_duplicate_is_gone`（`EXPLAIN` ＋**重複索引が無い**ことも見る） | **落ちた** ✓ |
| **X6** 契約の `seeds[].seed` に `integer` を許す | `test_the_contract_rejects_broken_manifests` に「`seeds[].seed` が数値」「`source.seed` が数値」を追加 | **落ちた** ✓（13 passed が 1 failed に） |
| （監査 F の追記）「3 回呼んでも同じ」が**表の名前だけ** | `test_the_migration_run_twice_gives_the_same_sql_not_only_the_same_names`（`sqlite_master` の **`sql` まで**比べる＝索引だけ消える壊し方を見逃さない） | — |
| （G-2 の裏取り） | `test_the_new_vocabularies_and_the_verdict_pair_are_constrained`（語彙の外・合否だけ・人だけが落ちる） | — |

## E（設計の字のずれ）

| # | 直した所 |
| --- | --- |
| **E-1** | `marker_skip_reason` の字は **`'前提1'`（空白なし）が正**。設計 §0.7・§5.1 をこの字に揃え、「**空白ありは `CHECK` で落ちる**」と 1 行足した |
| **E-2** | `ix_export_recipe` → **`ix_attempt_recipe`**（§2.2・§8.1-29） |
| **E-3** | §0.1・§9 の「**5 表**」→「**6 表**」（`recipe_export_attempt` を足したため） |
| **G-3 / G-4 / G-5** | **§0.16「P7-0 の監査で確定したこと」**を新設して 7 行にまとめた |

## 確かめたこと（実行）

- `uv run --no-sync pytest -q` → **317 passed**（309 → +8）。`node tools/gui_smoke.mjs` → **すべて ok**
- **5 通りの壊し方** → **5/5 で狙ったテストが落ちた**（壊して戻す手順を自動化。`.tmp-p7-0/…` ではなく一時スクリプト）
- **実データの複製（v5）から v6**: `user_version 6`・**263 枚・判断 3 件・FK 違反 0**。
  **新しい `CHECK` 3 本**が `sqlite_master` にあること、**`export_id` の `CASCADE`** と
  **`ix_export_attempt` が無い**ことを確認。**束を消すとファイルと結果の行が消える**（連鎖）ことも確認
- `tests/.tmp` の**残骸 0**（前の実行が残した 10 個を消した。残骸があると `conftest` の後始末検査が連鎖して
  「5 failed / 14 errors」になるので、**残骸はその場で消す**こと）

## 1 つ分かったこと（報告に残す）

**実データ `.data` は既に v6 になっていた**（P7-0 の道具か、アプリの再起動で `migrate()` が走ったため）。
**加算的**（新しい 6 表を足しただけ）で、**263 枚・判断 3 件は無傷**、`foreign_key_violations = 0`。
`.data/db.sqlite3` の mtime が変わっていないのは、**変更が WAL にある**ため（WAL は 778 KB）。
