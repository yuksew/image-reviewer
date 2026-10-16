> **廃止（2026-10-17。利用者の判断）**: この段は**削除しました**。理由と控えは [`p7-decision.md`](p7-decision.md) を見てください（①PNG を ComfyUI にドラッグすればワークフローが戻るので記録は重複 ②ja2en の英訳も実行すれば取り直せる）。**記録として残しています。**

# P7-4（画面）の実装の指示書

あなたはこのプロジェクトの実装者（DeepSeek 側）です。**P7-4（画面。P7 の最後の小段）**を実装してください。

## 最初に読むもの
1. **`C:\Users\yukse\.agents\skills\image-reviewer-dev\SKILL.md`**（**必ず読む**）
2. `docs/p7-design.md` — **§0.13（画面）/ §5（画面の設計。§5.1〜§5.5）/ §3 の口の一覧 / §4（状態）/ §6（契約）/ §9 の P7-4 の行**
3. **`docs/frontend-design.md`** — **§4.7〜§4.12（条件の記録の画面。P7 の設計と一緒に書いてある）**・§2.3（書体）・§3（画面の一覧）・§6（文言）・§11（細部）
4. `docs/p7-3-implementation.md`（**監視と結果の口**）・`docs/p7-2-implementation.md`（**書き出しの口**）
5. 既存の画面: `apps/gui/recipes*`（無ければ `apps/gui/` の既存の画面の作り方。`tags.js` / `taglist.js` / `jobs.js` / `requests.js` / `annotations.js`）/ `apps/gui/app.js`（経路）/ `tools/gui_smoke.mjs` / `tools/gui_layout.mjs`

## 作るもの（P7-4。**これで P7 の機能は全部入る**）
1. **最初に 1 列だけ足す**（点検 G-1 / P7-3 の申し送り 2）:
   **`recipe_export_result` に `fetched INTEGER NOT NULL DEFAULT 0`**（`/view` で取り込んだか）。
   **表はまだ空**なので **v7 を作らず v6 の DDL を直す**（P7-0 の C-1 と同じ判断）。
   `db.py` の `V6_RECIPE_DDL` と設計 §2.1 を直し、**既に v6 の DB にも列が入る**ようにする
   （**`PRAGMA table_info` を見てから `ALTER TABLE ADD COLUMN`**＝`_top_up_v6` を新設。家風の「列を見てから足す」）。
   `watcher.py` が `/view` で取り込んだときに **`fetched=1`** を立てる。**テスト**（列がある・既定 0・取り込みで 1・既存の v6 の DB にも入る）。
2. **画面 2 つ**（設計 §5 と `frontend-design.md` §4.7〜§4.12 のとおり）:
   - **`#/asset/<id>/recipe`**（1 枚の条件の記録。§5.1〜§5.3）: **記録する**（`mode` の選択）・**判定と理由**（`exact` / `approx` / `impossible` ＋ 理由。
     **記録時の 7 語**と**書き出し時の 3 語**を混ぜない）・**グラフの確認**・**書き出す前の検査**（`POST …/check` の結果）・
     **書き出し**（seed・`count`・`mode`・印の有無。**前提が外れたら印なしで理由が出る**）・**書き出した物の一覧**（`GET …/exports`）・
     **結果の画像と合否**（1 枚ずつ。**上書き**）・**手で紐付ける口**。
   - **`#/recipes`**（一覧。§5.4）: **要約だけ**（`env` / `record` は 1 枚の口）・判定で絞る・枚数。
   - **`#/jobs` に監視の状態を 1 行**（`GET /api/watcher`。**開始 / 停止は人だけ**）。
   - **`#/asset/<id>` の来歴の近くに「条件」への入口**（1 行）。
3. **文言は `frontend-design.md` §6 に足してから実装する**（P4-3 と同じ順序。**先に文書**）。
   **括弧書きを語釈以外に使わない**・**画面の語は 1 つ**（家風）。
4. **`tools/gui_smoke.mjs` に検査を足す**（§8.2 の P7-4 の担当）と、
   **`tools/gui_layout.mjs` に `--screen recipe`（`#/asset/<id>/recipe`）と `--screen recipes`** を足す
   （**本物の Chrome** で、**はみ出し 0**・**判定の印**・**結果の合否**・**スクロール無しで見えるか**）。
5. **実物で確かめる**（**利用者の 8790 は再起動しない**。**複製**にサーバを立てて `--base` を向ける）:
   - **記録 → 判定 → 検査 → 書き出し → 一覧 → 合否**の往復（**偽の ComfyUI** か、**記録だけ本物**）。
   - **エスケープ**: 語釈や理由に `<script>` を入れても**文字のまま**（`script` 要素 0）。
   - **`GET` が書かない**（画面を開くだけで行が増えない）。

## 守ること
- **`uv run` は `--no-sync`**（利用者のアプリが 8790 で `.venv` の exe を握っている）。`$env:UV_CACHE_DIR = "C:\work\image-reviwer\.uv-cache"`。
- **既存のテストを壊さない**（いま **392 件**）。`gui_smoke`（129）と `gui_layout`（6 画面）も緑のまま。
- **実データ `.data/` は `mode=ro` のみ**（v6・263 枚・判断 3 件・`recipe_record` 0 行）。壊す試験は複製（`sqlite3` の `backup()`）。**`.backup/` は消さない**。
- **`schemas/review-export.schema.json` は触らない**（`recipe-manifest` も変えない）。
- **`git` のコミットはしない**（**前の段で指示違反があったので強く言います**。親がまとめてコミットします）。
- **README は触らない**（親が最後に直す）。記録は **`docs/p7-4-implementation.md`** に。
- **ComfyUI に `POST /prompt` しない**（画像の生成は禁止。`GET` はよい）。

## 返すもの（最終応答）
1. 触ったファイルと行数
2. `pytest`（件数）・`gui_smoke`・`gui_layout`（**新しい 2 画面を含む 8 画面**）の結果
3. **`fetched` 列**を足した結果（v6 の DDL・`_top_up_v6`・既存の v6 の DB で列が入ること・`/view` の取り込みで 1）
4. **実物での往復**（記録 → 判定 → 検査 → 書き出し → 一覧 → 合否）と **esc** と **`GET` が書かない**の結果
5. 設計からずれた所／自分で決めた所（1 行ずつ理由）と、気づいた設計の穴
