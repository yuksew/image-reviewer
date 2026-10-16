# 仕上げの指示書（P7 を `design.md` 本体と README に反映する）

あなたはこのプロジェクトの実装者（DeepSeek 側）です。**P7（条件の記録。R12）の決定を `docs/design.md` の本体に反映**し、
**`README.md` を現在の状態に直し**、**`docs/handoff.md` を P7 完了に更新**してください。**コードは触りません。**

## 読むもの
- `docs/p7-design.md`（**§0 が拘束力のある差分**。とくに §0.3（v6 の表）・§0.5（再現キー）・§0.6（判定）・§0.7（グラフの置き場）・
  §0.8（検査）・§0.9（監視と取り込み）・§0.10（規律）・§0.11（契約）・§0.16/§0.17（監査で確定したこと））
- `docs/p7-0-implementation.md` / `docs/p7-1-implementation.md` / `docs/p7-2-implementation.md` / `docs/p7-3-implementation.md` / `docs/p7-4-implementation.md`
- `docs/p7-0-audit-report.md` / `docs/p7-1-audit-report.md` / `docs/p7-3-audit-report.md` と各 `*-audit-triage.md`（**採用した指摘は設計に印を付けて書き戻す**）
- **`docs/design.md`**（本体。**§5.1（表の一覧）・§5.6（要求・注記・プリセット・語釈）・§6.1（API の一覧）・§8（タグ）・§14（段の表）・§16.x（段ごとの決定）**）
- `docs/handoff.md`（**いまの状態**。P4 完了＋P7 の進み）
- `README.md`（状態・動かす・機能の一覧・文書の表）
- `C:\Users\yukse\.agents\skills\image-reviewer-dev\SKILL.md`（家風）

## やること

### 1. `docs/design.md` 本体
- **§5.1 / §5.6 に v6 の 6 表**（`recipe_record` / `recipe_export_attempt` / `recipe_export` / `recipe_export_result` / `preset` / `watcher_state`）を、
  **本文の DDL の書き方**で足す（**設計 §2.1 が正**。`CHECK`・`ON DELETE`・**`fetched`** まで）。
  **「P7 で作った」**と 1 行。
- **§6.1 に P7 の口**（`GET/POST /api/assets/{id}/recipe`・`GET /api/recipes`・`POST /api/recipes/{id}/check`・`/export`・`GET …/exports`・
  `POST …/exports/{attempt_id}/results`・`…/results/{result_id}/verdict`・`GET/POST /api/watcher`・`POST /api/watcher/start|stop`）を足す。
- **§8 に条件の記録の節**（再現キーの作り方・判定 3 語と理由 11 語の**記録時 7 語／書き出し時 3 語**の分け方・
  印の前提 3 つと `repro-<attempt_id>/seed-<seed>`・**結果の紐付け**（`matched_by`）・**合否**）。
- **§14 の P7 の行に「済み」**を付け、**完了条件が実行で確かめられた**ことを 1 行（**線 6 が P7 全体の合格の門**）。
- **§16.x を新設**（`§16.5 P7（条件の記録）で決めたこと` など。**P6 の §16.4 と同じ形**で、v6 の表・API・契約・
  **監査で確定したこと**（A-1〜A-3・B・C の決着）を表に）。
- **契約**: `schemas/recipe-manifest.schema.json` を**契約の一覧**に足し、**`review.json` は変えていない**ことを明記。

### 2. `README.md`
- **状態**: 「P5・P6・P4・**P7（条件の記録）**が動く。**テスト 397 件**」（**実測の数**を使う。**自分で `pytest` を回して確かめる**）。
- **動かす**: `gui_smoke` の件数（**142**）と **`gui_layout` の 8 画面**（`--screen recipe --ids <id>` / `--screen recipes` を足す）。
  **`tools/probe_p7.py --judge` / `--export` / `--watch`** を足す。
- **機能の一覧**に条件の記録（**記録・判定・検査・印つきの書き出し・seed 違い・監視での結果の取り込み・合否**）を足し、
  **未実装**を直す（**P8（重複・削除・バックアップ）と P9（仕上げ）**、**P2（カタログ）・P3（監視の残り・`userdata` 設置）**、
  **プリセットの画面**）。
- **文書の表**に P7 の文書（`p7-design.md`・`p7-review-*.md`・`p7-*-implementation.md`・`p7-*-audit-*.md`・`p7-line8-note.md` は既にある）を足す。

### 3. `docs/handoff.md`
- **§1 の表**を P7 完了に（P7-0〜P7-4 の状態・監査・仕分け・**線 6 が門**）。
- **§3 の次の手順**を **P8（重複・削除・バックアップ）**に。
- **§5 の数字**（テスト 397・`gui_smoke` 142・`gui_layout` 8 画面）。
- **§6 の罠のカタログ**に P7 で踏んだ物を足す（**`/api/jobs` の一覧に `workflow` が無い**・**タグ付け job は `outputs_count: 0`**・
  **`execution_cached` は全 job に出て `nodes` が空**・**`subfolder` はバックスラッシュ**・**`/object_info` は 2.39 MB なので `/{class_type}`**・
  **`COMFY_DYNAMICCOMBO_V3` の入れ子**・**`ALTER` で `CHECK` を足せない**・**`seed` が NULL だと UNIQUE が効かない**・
  **`asset_location.path` は正規化した鍵**）。
- **§7 の未回答**を更新（**P7 で残した物**: プリセットの画面・`userdata` 設置（P3）・`class_type` のキャッシュ・
  **`onnxruntime-gpu` を入れたら `tagger.engine` を `auto` に戻す**）。

## 守ること
- **コードは触らない**（`src/` `apps/` `tests/` `tools/` `schemas/`）。**文書だけ**。
- **`uv run` は `--no-sync`**（数を確かめるとき）。**実データ `.data/` は `mode=ro` のみ**（**触らない**）。
- **`git` のコミットはしない**（親がまとめてやります）。
- **数を発明しない**（`pytest` / `gui_smoke` / `gui_layout` を**自分で回して**実測を書く）。
- **監査で「直した」と言われた物は、直った形で書く**（`docs/p7-*-audit-triage.md` と `docs/p7-3-audit-recheck.md` を見る）。

## 返すもの（最終応答）
1. 直した文書と行数
2. **自分で回した数**（`pytest` の件数・`gui_smoke` の件数・`gui_layout` の画面数）
3. `design.md` に足した節の一覧
4. README で直した所
5. handoff で直した所
6. 反映しきれなかった点（あれば）と理由
