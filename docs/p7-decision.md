# P7（条件の記録。R12）— 作って、消した記録（2026-10-17）

## 何を作ったか（1 段落）

`docs/p7-design.md`（**1,029 行**）に沿って **5 小段**を作りました。PNG のワークフローから**再現キー**（グラフだけの純関数）を作り、
**判定**（`exact` / `approx` / `impossible`）と理由を出し、**印つきのグラフ**（`repro-<attempt_id>/seed-<seed>`）を書き出して、
ComfyUI で回した**結果を監視で拾って自動で紐付け**（`matched_by`・指標・`seed_changed`）、**人が 1 枚ずつ合否**を残す。
**6 表**（`recipe_record` / `recipe_export_attempt` / `recipe_export` / `recipe_export_result` / `preset` / `watcher_state`）と
**契約** `schemas/recipe-manifest.schema.json`、**画面 2 つ**（`#/asset/<id>/recipe`・`#/recipes`）、`tools/probe_p7.py` を足しました。
**テスト 403 件・`gui_smoke` 164 検査・`gui_layout` 8 画面**まで緑にし、**Fable の実行込み監査を 4 回**（P7-0 / P7-1 / P7-3 / P7-4）受けました。

## なぜ消したか（**利用者の判断**）

1. **「前に作った絵をもう一回作る」ときは、PNG を ComfyUI にドラッグすればワークフローが戻る。**
   → 記録を作る手間が**重複**で、実際の作業では使わない。
2. **ja2en の英訳が PNG に残らない件も、もう一度ワークフローを実行すれば取れる。**
   → 「英訳を捕まえて記録を `exact` に上げる」という P7 の中心的な動機が、**利用者の運用では要らない**。

利用者の言葉（2026-10-17）: 「条件の記録、何する機能なのかイマイチわからなかったです」→ 説明のあと「**消してください**」。

## 消した物

| 種別 | 物 |
| --- | --- |
| サーバ | `src/image_reviewer/recipe.py`（764 行）・`recipe_export.py`（641）・`watcher.py`（948）・`api/recipes.py`・`api/watcher.py` |
| 画面 | `apps/gui/recipe.js`（362）・`recipelist.js`（102）と、`app.js` / `jobs.js` / `index.html` / `styles.css` の配線 |
| 道具 | `tools/probe_p7.py`・`tools/check_contract_p7.py` |
| テスト | `tests/test_recipe.py`・`test_recipe_export.py`・`test_watcher.py`・`test_watcher_api.py`・`test_manifest.py` |
| 契約 | `schemas/recipe-manifest.schema.json` |
| データ | **v6 の 6 表**（実データから `DROP TABLE`。**外から参照が無いことを確かめて**子から順に。`PRAGMA foreign_keys = 0` は使っていない）。`user_version` を **6 → 5** に戻した |
| 設定 | `comfyui.output_dir`・`comfyui.url`（P7 で入れた物。`tagger.*` は残した） |
| コード | `app.py`・`api/__init__.py`・`db.py`（**`SCHEMA_VERSION` を 5 に戻し**、`V6_RECIPE_DDL` / `_migrate_v6` / `_top_up_v6` / `if current < 6` を削除） |

**控え**: `.backup/pre-p7-removal-20261017-030324/db.sqlite3`（**v6 のまま**。6 表には `recipe_record` 4 行・
`recipe_export_attempt` 4 行・`recipe_export` 4 行が入っていた。戻したくなったらここから取れる）。

## 残した物（**消していない**）

- `docs/p7-design.md`・`docs/p7-review-*.md`・`docs/p7-*-implementation.md`・`docs/p7-*-audit-*.md`・`docs/p7-*-triage.md`・
  `docs/p7-line8-note.md`・`docs/p7-removal-brief.md`・この文書 — **先頭に「廃止」の 1 行を足しただけ**。
  **P7 で踏んだ罠**（`/api/jobs` の一覧に `workflow` が無い・`outputs_count: 0` でタグ付けを弾く・`execution_cached` は全 job に出て `nodes` が空・
  `subfolder` はバックスラッシュ・`/object_info` は 2.39 MB なので `/{class_type}`・`COMFY_DYNAMICCOMBO_V3` の入れ子・
  **`ALTER TABLE` で `CHECK` を足せない**・**`seed` が NULL だと UNIQUE が効かない**・`asset_location.path` は正規化した鍵）は
  **`docs/handoff.md` §6 に残した**（P8 以降で必ず効く）。
- `review.py` の `source` の語彙 `"watcher"` は **P3 由来**（グループの出所）なので残した。
- **P4 の線 8**（`docs/p7-line8-note.md`）は**別の段の記録**なのでそのまま。

## 将来また欲しくなったら

1. **まず確かめる**: 「PNG を ComfyUI にドラッグ」で足りないのは**どんな場面か**（例: 同じ条件で **seed だけ変えて 10 枚**、
   **条件で検索**したい、**モデルを差し替えて比べたい**）。**足りない場面が言葉にできないなら作らない**。
2. 作るなら **P7 の設計と実装がそのまま使える**（`docs/p7-design.md` と控えの DB。**監査で潰した穴も記録に残っている**）。
   **小さい方から**: 「印つきの書き出し」と「結果の紐付け」だけ（画面を伴わない、`POST` と一覧だけ）なら **P7-2 / P7-3 の半分**で足りる。
3. **今回の教訓**: **利用者が要らない物を作らない**。設計の前に「**それで何が楽になるか**」を**利用者の言葉**で確かめる
   （P7 は要件 R12 から機械的に作ったが、**利用者の運用では PNG のドラッグで足りていた**）。
