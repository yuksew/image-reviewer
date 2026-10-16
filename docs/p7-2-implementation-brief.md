# P7-2（書き出し）の実装の指示書

あなたはこのプロジェクトの実装者（DeepSeek 側）です。**P7-2（書き出し。R12 の中盤）**を実装してください。

## 最初に読むもの
1. **`C:\Users\yukse\.agents\skills\image-reviewer-dev\SKILL.md`**（**必ず読む**）
2. `docs/p7-design.md` — **§0 が拘束力のある差分**（点検の反映済み）。とくに
   **§0.1（P7-2 の行）/ §0.3（表。もう在る）/ §0.4（`mode` の写し方）/ §0.8（**書き出す前の検査**。点検 A-1 の動的コンボ展開を含む）/
   §0.9（**印の前提**・`marker_skip_reason` は `'前提1'`〜`'前提3'`・**空白なし**）/ §0.10（`GET` は書かない・`actor`・`client_token`・原子性）/
   §0.11（契約）/ §2.1（`recipe_export_attempt` の**束の表**と `recipe_export`）/ §3.3〜§3.5（`check` / `export` / `exports` の口）/
   §5.3（**`control_after_generate` の手順。点検 B-6 で「1 ファイル 1 回・2 回目の前に fixed」に直っている**）/ §6.1〜§6.2（manifest 契約）/
   §7（性能）/ §8.1（テストのうち P7-2 の担当）/ §9 の P7-2 の行**
3. `docs/p7-review-report.md`（点検。**B-2・B-4・B-5・B-6** が P7-2 に効く）と `docs/p7-1-implementation.md`（P7-1 の記録）
4. 既存のコード: `src/image_reviewer/recipe.py`（**P7-1 で作った。`recipe_hash` と `canonical_graph` を再利用する**）/
   `src/image_reviewer/api/recipes.py` / `png_meta.py` / `jobs.py`（**取引の外で外部を待つ**）/ `export.py`（**原子性の手本**）/
   `tests/test_recipe.py`（テストの書き方）

## 作るもの（P7-2。**監視と画面は作らない**）
1. **書き出しの本体**（`recipe.py` に足すか、新規 `recipe_export.py`。**`recipe.py` の `recipe_hash` / 判定の規則は変えない**）
   - **`mode` は 3 つ**: `pin_text`（既定）/ `rerun_graph` / `manual_text`（§0.4）。**`mode` は束（`recipe_export_attempt`）に写す**（記録の `mode` は変えない）。
   - **書き出す前の検査**（§0.8）: **① 保存ノードが 1 つ**・**② `filename_prefix` がリテラル**・**③ 入力キーが宣言に含まれる**
     （**動的コンボを展開してから照合**。展開できない `COMFY_DYNAMIC*` は対象外にして `notes`）。
     **検査の結果は `checked_json` に残す**。**`/object_info/{class_type}` だけ引く**（**2.39 MB の一括は引かない**。点検 B-2）。
   - **印（marker）**: `SaveImage.filename_prefix` を **`repro-<attempt_id>/seed-<seed>`** に（**`attempt_id` は 8 文字以上の `[a-z0-9]`**。
     点検 B-4: **`subfolder` は Windows でバックスラッシュ**になるので、印は **`output/repro-<id>/` のフォルダ**になる）。
     **前提が外れたら印を付けずに書き出し**、`marker_skip_reason` を `'前提1'` / `'前提2'` / `'前提3'`（**空白なし**）にする。
     **`marker` は NULL 可**（表の `CHECK` が「印か理由のどちらか一方」を守る）。
   - **seed 違い**: `seeds` は**文字列**。**seed は `(seed + k) mod 2^64`** の形で増やす（§0.9）。
     **`KSampler` の無いグラフ**（実データ 3 枚）: **`seeds` / `count` を明示したら 422 `no_sampler`**、無指定なら **seed 無しで 1 ファイル**（印は `…/noseed`）。
   - **置き場**（§6.2）: **`<data>/recipes/<recipe_id>/<attempt_id>/seed-<seed>.json`** と **`manifest.json`**。
     **原子的に書く**（一時ファイル → `os.replace`。失敗したら一時ファイルを消す）。
   - **`client_token` の再送は 200 で同じ `attempt_id`**（`ux_attempt_token`）。**取引の外で ComfyUI を待つ**（`/object_info` の取得）。
2. **manifest**（`schemas/recipe-manifest.schema.json` は**もう在る**。**点検 B-5 の反映済み**）:
   - **`export_hashes` の鍵**は **`"noseed"`**（seed が無いとき。§6.1）。**値は `^sha256:`**。
   - **`required` に `generated_at` と `marker_skipped`** が入っている（G-5）。
   - **書き出したグラフの `filename_prefix` を変えても `recipe_hash` は変わらない**（鍵から除外済み）。**その差を manifest に残す**。
3. **API**（`api/recipes.py` に足す）: **`POST /api/recipes/{id}/check`**（検査だけ。**書かない**）・
   **`POST /api/recipes/{id}/export`**（`seeds` / `count` / `mode` / `marker` / `client_token`）・**`GET /api/recipes/{id}/exports`**（§3.3〜§3.5）。
   **`GET` は 1 バイトも書かない**。**`POST` は `actor` をヘッダから**。**`Host: evil` / `Content-Type: text/plain` で 403**。
4. **テスト**（`tests/test_recipe_export.py` を新規。§8.1 のうち P7-2 の担当。**「壊すと落ちる」形**）:
   - **印を付けても `recipe_hash` が変わらない**・**seed を変えると変わる**
   - **前提 3 つを外したグラフを合成で作って**、**印なし＋`marker_skip_reason` が正しい**こと
   - **`COALESCE(seed,'')` の式の索引**が効くこと（**同じ束・同じ seed を 2 回作らない**）
   - **`client_token` の再送で `attempt_id` が同じ**・**行が増えない**
   - **`KSampler` 無し**: `seeds` を明示すると **422 `no_sampler`**、無指定なら 1 ファイル＋`noseed`
   - **原子性**: `os.replace` を落として `*.tmp` が残らない
   - **manifest が本物の `jsonschema` で通る**（`tools/check_contract_p7.py` に実例を足す）
5. **`tools/probe_p7.py --export`**（足す）: 実データの複製で**グラフありの 1 枚**から **seed 2 つ**を書き出し、
   **3 ファイル**（`seed-1.json` / `seed-2.json` / `manifest.json`）と**印**、**manifest が契約を通る**ことを出す（§1.2 の線 3・4・5）。

## 守ること
- **`uv run` は `--no-sync`**（利用者のアプリが 8790 で `.venv` の exe を握っている）。`$env:UV_CACHE_DIR = "C:\work\image-reviwer\.uv-cache"`。
- **既存のテストを壊さない**（いま **340 件**）。`node tools/gui_smoke.mjs`（129）も緑のまま。
- **実データ `.data/` は `mode=ro` のみ**（**すでに v6**・`recipe_record` は 0 行）。壊す試験は複製（`sqlite3` の `backup()` で WAL を畳む）。**`.backup/` は消さない**。
- **`db.py` と `schemas/review-export.schema.json` は触らない**（`recipe-manifest` を直す必要があれば**報告に書く**）。
- **`git` のコミットはしない**。**README は触らない**。記録は **`docs/p7-2-implementation.md`** に。
- **P7-1 の監査が並行で走っている**。`recipe.py` や `api/recipes.py` が**あなたの作業中に変わりうる**ので、**編集の前に必ず読み直す**。
- 設計に無い仕様を発明しない（決めたら**設計にも書く**）。

## 返すもの（最終応答）
1. 触ったファイルと行数
2. `pytest`（件数）・`gui_smoke` の結果
3. **`tools/probe_p7.py --export` の結果**（3 ファイル・印・manifest が契約を通る）
4. **実データの複製で v6 のまま**（`recipe_record` の行数が増えていない）ことを確かめた結果
5. 設計からずれた所／自分で決めた所（1 行ずつ理由）と、気づいた設計の穴
