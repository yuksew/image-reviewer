# P7-3（監視の最小形と結果の紐付け）の実装の指示書

あなたはこのプロジェクトの実装者（DeepSeek 側）です。**P7-3（R12 の後半。合格の門＝線 6）**を実装してください。

## 最初に読むもの
1. **`C:\Users\yukse\.agents\skills\image-reviewer-dev\SKILL.md`**（**必ず読む**）
2. `docs/p7-design.md` — **§0 が拘束力のある差分**。とくに **§0.2（監視の最小形）/ §0.9（監視と取り込み。印の照合・`matched_by`・既読）/ §0.10（`GET` は書かない・`actor`）/
   §0.11（契約）/ §2.1（`watcher_state` / `recipe_export_result`）/ §3.6〜§3.8（監視と結果の口）/ §4（状態）/ §5（画面は P7-4）/ §7（性能）/ §8.1（テストのうち P7-3 の担当）/ §9 の P7-3 の行 / §0.17（P7-1 の監査で確定したこと）**
3. `docs/p7-review-report.md`（点検の **B-1（結果の実体パス＝`comfyui.output_dir`。G-1-(a)）/ B-3（`/api/jobs` の使い方）/ B-4（`subfolder` はバックスラッシュ）**
   と `docs/p7-1-audit-report.md`（**P7-1 の教訓**）
4. `docs/p7-1-implementation.md` / `docs/p7-2-implementation.md`（**もう在る物**: `recipe.py`（`recipe_hash` / `judge` / `collect_env`）・`recipe_export.py`（検査・印・manifest））
5. 既存のコード: `capture.py`（`/history` の走査と**由来の判定**）、`png_meta.py`、`jobs.py`（**1 本のワーカー・取引の外で外部を待つ**）、`store.py`、`api/*.py`

## 作るもの（P7-3。**画面は作らない**）
1. **監視の最小形**（`watcher.py` を新設するか `recipe.py` に足す）
   - **必要なときだけ手で開始**（`POST /api/watcher/start`）・`POST /api/watcher/stop`・`GET /api/watcher`（**状態を返すだけ**）。**常駐しない**。
   - **2 秒ごと**に **`GET /api/jobs?limit=N`**（一覧）→ **画像を出す job だけ**を選ぶ（**`outputs_count` と `preview_output` でタグ付け job を詳細を取らずに弾く**。
     点検 B-3）→ 選んだ物だけ **`GET /api/jobs/{id}`**（**`workflow.prompt` / `outputs` / `execution_status`**）。
   - **既読は `create_time` 基準**（`watcher_state.baseline_create_time` に ms で持ち、**処理済みの集合**と併用）。**`in_progress` は既読にしない**。
   - **`execution_cached` の見分け**: **保存ノードが `cached` に含まれるか**で「実行された」を判定（実測: `execution_cached` は全 job に出て `nodes` が空）。
   - **1 周期で登録する枚数の上限は 20**（設計の決定）。
2. **印の照合と結果の登録**（§0.9）
   - **`filename_prefix` の前方一致**で `recipe_export` の印に当てる（**`subfolder` はバックスラッシュ**で来る。点検 B-4）。
     **前方一致で見つからないときは PNG の `prompt` チャンクを見る**（保険。利用者の回答 Q2）。
   - **結果の実体パス**: 設定 **`comfyui.output_dir`**（**無ければ `/internal/folder_paths` から推定し、実在するときだけ使う**）。
     **監視の開始時に、その場所を登録ルートに足す**（**1 回だけ利用者に確認する形**。§0.9）。
     推定が当たらなければ **`GET /view` で `<data>/results/` に取り込む**（複製）に落ち、**画面に 1 行出す**。
   - **`recipe_export_result` に 1 行**（`matched_by` = `marker` / `manual` / `prefix`）。**同じ結果画像を 2 度登録しない**（`ux_result_asset`）。
   - **指標**: 結果の PNG から `recipe_hash` を計算して**記録の鍵と比べる**。`seed` を読んで **`seed_changed`** を立てる。**`hash_mismatch`** を理由に出す。
   - **手で紐付ける口**: **`POST /api/recipes/{id}/exports/{attempt_id}/results`**（本文は設計 §3.7 のとおり）。
   - **合否**: **`POST /api/recipes/{id}/exports/{attempt_id}/results/{result_id}/verdict {verdict, note}`**（**`human` だけ**。**上書き＋`verdict_at` / `verdict_actor`**）。
3. **sidecar**（§0.9 / `capture.py` に倣う）: 結果の PNG の隣に**人が読める JSON**（`<data>/results/` に取り込んだ場合はそこに）。
4. **API**: §3.6〜§3.8 の口を `api/recipes.py` に足す。**`GET` は 1 バイトも書かない**（**監視の `GET` も**）。
   **`POST` は `actor` をヘッダから**。**`Host: evil` / `Content-Type: text/plain` で 403**。
5. **テスト**（`tests/test_watcher.py` を新規。**偽の ComfyUI**（小さな HTTP サーバ）で回す。**本物の ComfyUI は使わない**）:
   - **印つきの出力を持つ job** → `matched_by='marker'` で 1 行できる／**印の無い job では作られない**
   - **タグ付けの job（`outputs_count: 0`）は詳細を取らずに弾かれる**（**`GET /api/jobs/{id}` を呼ばない**ことを固定）
   - **`in_progress` を混ぜても既読が進まない**・**`create_time` の境界**・**再起動しても二度登録しない**（`watcher_state`）
   - **`GET /api/watcher` と監視の 1 周期がファイルを書かない**（`GET` は書かない）
   - **合否**: `human` だけ・上書き・`verdict_at` / `verdict_actor` が入る・**元の `recipe_record` が変わらない**
   - **`seed_changed`** と **`hash_mismatch`** の判定
6. **`tools/probe_p7.py --watch`**（足す）: **偽の ComfyUI** を立てて**線 6 を通す**（§1.2 の線 6 の手順そのまま。
   合成 PNG を `comfyui.output_dir` に置き、**登録・鍵・指標・`seed_changed` まで通す**）。

## 守ること
- **`uv run` は `--no-sync`**（利用者のアプリが 8790 で `.venv` の exe を握っている）。`$env:UV_CACHE_DIR = "C:\work\image-reviwer\.uv-cache"`。
- **既存のテストを壊さない**（いま **369 件**）。`node tools/gui_smoke.mjs`（129）も緑のまま。
- **実データ `.data/` は `mode=ro` のみ**（v6・`recipe_record` 0 行）。**`.backup/` は消さない**。
- **`db.py` と `schemas/` は触らない**（表も契約ももう在る）。
- **本物の ComfyUI に `POST` しない**（画像の生成はしない）。`/api/jobs` などの **`GET` は読んでよい**。
- **`git` のコミットはしない**。**README は触らない**。記録は **`docs/p7-3-implementation.md`** に。
- 設計に無い仕様を発明しない（決めたら**設計にも書く**）。

## 返すもの（最終応答）
1. 触ったファイルと行数
2. `pytest`（件数）・`gui_smoke` の結果
3. **`tools/probe_p7.py --watch` の結果**（**線 6**。印つき／印なしの 2 ケース・タグ付け job の除外・`in_progress` の扱い・登録・鍵・指標・`seed_changed`）
4. **実データの複製で**、監視が**実データの `recipe_record` を増やさない**こと（`--judge` の後始末）
5. 設計からずれた所／自分で決めた所（1 行ずつ理由）と、気づいた設計の穴
