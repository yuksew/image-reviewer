# P7（条件の記録）の削除の指示書

あなたはこのプロジェクトの実装者（DeepSeek 側）です。**利用者の判断で P7（条件の記録。R12）を削除**します。
**理由**: ①「前に作った絵をもう一回作る」ときは **PNG を ComfyUI にドラッグすればワークフローが戻る**ので、記録は重複。
② ja2en の英訳が PNG に残らない件も、**もう一度ワークフローを実行すれば取れる**ので困らない。
→ **表・API・画面・テスト・契約を全部消す**（**表は空なので安全**）。

## 消す物（**全部**）

### 1. サーバ側
- **ファイルごと消す**: `src/image_reviewer/recipe.py`・`recipe_export.py`・`watcher.py`・`api/recipes.py`・`api/watcher.py`
- `src/image_reviewer/app.py`: レシピと監視の**サービスの生成・`app.state`・`include_router`・起動時の `mark_stopped_on_boot()`** を外す
- `src/image_reviewer/api/__init__.py`: `recipe_exports_of()` などの配線を外す
- `src/image_reviewer/db.py`: **`SCHEMA_VERSION` を 5 に戻し**、`V6_RECIPE_DDL`・`_migrate_v6`・`_top_up_v6`・`migrate()` の `if current < 6` を消す
  （**他の版の移行は触らない**。**「v6 はもう無い」とコメントを残す**）
- `schemas/recipe-manifest.schema.json` を消す（**`review-export.schema.json` は触らない**）

### 2. 画面
- **ファイルごと消す**: `apps/gui/recipe.js`・`apps/gui/recipelist.js`
- `apps/gui/app.js`: `#/asset/<id>/recipe` と `#/recipes` の経路、**来歴の下に足した「条件の記録」1 行**を外す
- `apps/gui/jobs.js`: **監視の 1 行（`watcherHtml()` と見る/止める・`watchRequest()`）**を外す
- `apps/gui/index.html` / `apps/gui/styles.css`: P7 で足した器と見た目を外す（**他の画面の物は触らない**）

### 3. 道具とテスト
- **ファイルごと消す**: `tools/probe_p7.py`・`tools/check_contract_p7.py`・`tests/test_recipe.py`・`tests/test_recipe_export.py`・
  `tests/test_watcher.py`・`tests/test_watcher_api.py`・`tests/test_manifest.py`
- `tests/test_db.py`: **v6 のテスト（`recipe_*` / `preset` / `watcher_state` の表・索引・制約・`_top_up_v6`）を消す**。
  **`SCHEMA_VERSION` を 5 に戻したことに合わせる**（`== db.SCHEMA_VERSION` の形はそのまま）。**v5 までのテストは残す**
- `tools/gui_smoke.mjs` / `tools/gui_layout.mjs`: **P7 の検査と `--screen recipe` / `--screen recipes`** を外す
  （**`rcTop` / `rcVisible` も**。**他の画面の検査は触らない**）

### 4. 文書
- **`docs/p7-*.md` は消さない**（設計・監査・仕分けの記録）。ただし**それぞれの先頭に次の 1 行を足す**:
  `> **廃止（2026-10-17。利用者の判断）**: 「前に作った絵をもう一回作る」ときは **PNG を ComfyUI にドラッグすればワークフローが戻る**ので
  > 記録は重複で、ja2en の英訳も**もう一度実行すれば取れる**ため、**この機能は削除した**。以下の記録は歴史として残す。`
- **`docs/p7-decision.md` を新規に作る**（1 ページ）: **何を作ったか**（1 段落）・**なぜ消したか**（上の 2 つ）・
  **消した物の一覧**・**残した物**（文書・git の履歴）・**もし将来また欲しくなったら**（`git log` の該当コミット・表は空だったので作り直しは容易）
- **`docs/design.md`**: **§14 の P7 の行**を「**廃止（2026-10-17。利用者の判断）**」に直し、**§16.5 を「P7（条件の記録）— 廃止」**に書き換える
  （**何を作って、なぜ消したかを 5 行程度**）。**要件対応表の R12 を「見送り（廃止）」**にする
- **`README.md`**: 状態・機能の一覧・走らせ方から **P7 を外す**（**テストの件数と `gui_smoke` の件数は自分で回して実測**。
  `gui_layout` は **6 画面**に戻る）。**「条件の記録は作ったが廃止した」を 1 行**（理由つき）
- **`docs/handoff.md`**: **P7 の行を「廃止」**に。**次の段は P8**（重複・削除・バックアップ）のまま。
  **罠のカタログは残す**（他でも効く: `/object_info` は `/{class_type}`・`ALTER` で `CHECK` は足せない など）

## 手順（**この順で**）
1. **控えを取る**（`sqlite3` の `backup()` で `.data` を `.backup/pre-p7-removal-<YYYYMMDD-HHMMSS>/` に。**WAL を畳む**）
2. **アプリを止める**（8790 のプロセス。**利用者のアプリなので、止めてよい**——再起動は親がやる）
3. コードとテストを消す
4. **実データから v6 の 6 表を落とす**（`recipe_record` / `recipe_export_attempt` / `recipe_export` / `recipe_export_result` / `preset` / `watcher_state`。
   **行数が 0 であることを確かめてから**。`PRAGMA foreign_keys = 0` は**使わない**——依存の向きを確かめて順に落とす）。
   **`user_version` は 6 のままでよい**（`SCHEMA_VERSION = 5` なので移行は走らない。**変えるなら理由を報告に**）
5. **検証**: `uv run --no-sync pytest -q`（**全件緑**。**P7 のテストを消した分だけ減る**）／`node tools/gui_smoke.mjs`／
   `node tools/gui_layout.mjs`（**6 画面**）／`GET /api/health`・`/api/assets`・`/api/tags`・`/api/jobs` が 200／
   **`/api/recipes` と `/api/watcher` が 404**／**実データ 263 枚・判断 3 件が無傷**・`integrity_check` ok・FK 違反 0
6. **app の再起動はしない**（親がやる）

## 守ること
- **`uv run` は `--no-sync`**。`$env:UV_CACHE_DIR = "C:\work\image-reviwer\.uv-cache"`。
- **`git` のコミットはしない**（親がやります。**削除は `git rm` でなく普通にファイルを消してよい**——親が `git add -A` で拾います）。
- **`docs/p7-1-line8` など他の段の文書は触らない**（`p7-*` だけ）。
- **利用者の ComfyUI には触らない**（`GET` もしなくてよい）。
- **消し残しを残さない**: `grep -r "recipe\|watcher" src/ apps/ tests/ tools/ schemas/` で**参照が残っていない**ことを確かめる
  （**`docs/` と `README.md` の歴史の記述は残ってよい**）。

## 返すもの（最終応答）
1. 消したファイルの一覧と、残したファイル（理由つき）
2. **実データから落とした表と、控えの場所**
3. `pytest`（件数）・`gui_smoke`（件数）・`gui_layout`（画面数）の実測
4. **`/api/recipes` と `/api/watcher` が 404**・**他の口が 200** の結果
5. **実データの状態**（263 枚・判断 3 件・integrity ok・FK 違反 0）
6. **消し残しの確認**（`grep` の結果）
7. 気づいたこと（あれば）
