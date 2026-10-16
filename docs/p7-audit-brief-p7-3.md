# 監査の指示書（P7-3: 監視の最小形と結果の紐付け。**合格の門＝線 6**）

あなたは**実装の監査者**です。**P7-3（R12 の後半）**を監査してください。**この段の線 6 が P7 全体の合格の門**です。

- 対象: `C:\work\image-reviwer` ／ 出力: **`docs/p7-3-audit-report.md` を新規に書くだけ** ／ 言語: 日本語 ／ **実行してよい**

## 0. 環境（**利用者のアプリが 8790 で動いています。止めないでください**）

```powershell
cd C:\work\image-reviwer
$env:UV_CACHE_DIR = "C:\work\image-reviwer\.uv-cache"      # 必須
uv run --no-sync pytest -q                                  # ★ --no-sync。いま 392 件
node tools/gui_smoke.mjs                                    # 129 件
uv run --no-sync python tools/probe_p7.py --watch           # 線 6（偽の ComfyUI を立てる）
```

- **実データ `.data/` は `mode=ro` のみ**（v6・263 枚・判断 3 件・**`recipe_record` 0 行**・`watcher_state` 0 行）。
  壊す試験は複製（**`sqlite3` の `backup()` で WAL を畳む**）。**`.backup/` は消さない**。
- **ComfyUI は生きています**（127.0.0.1:8188・0.39.2・RTX 3060）。**`GET` だけ**（`/api/jobs`・`/history`・`/object_info/{class_type}`・
  `/internal/folder_paths`・`/system_stats`）。**画像は生成しない**（`POST /prompt` は禁止）。
- 一時物は `.tmp-audit-redo/`。**ソースは編集しない**。**`git` のコミットもしない**。
- `.data` の設定に **`comfyui.output_dir = C:\ai\ComfyUI_windows_portable\ComfyUI\output`** と `comfyui.url` を入れてあります（実装が読む想定）。

## 1. P7-3 で入ったもの

- 設計: `docs/p7-design.md` **§0.2 / §0.9（監視と取り込み）/ §0.10 / §3.6〜§3.8 / §2.1 / §4 / §7 / §8.1（P7-3 の担当）/ §9**
- 実装の記録: [`p7-3-implementation.md`](p7-3-implementation.md)（**自分で決めた 8 点・申し送り 5 件・設計の穴 3 件**）
- 主なファイル: `src/image_reviewer/watcher.py`（**新規 662 行**）・`src/image_reviewer/api/watcher.py`（新規）・
  `src/image_reviewer/api/recipes.py`（results と verdict の口）・`recipe_export.py`（`exports` に `results`）・
  `tests/test_watcher.py`（18 件）・`tests/test_watcher_api.py`（5 件）・`tools/probe_p7.py --watch`

## 2. 確かめてほしいこと（**線 6 が主**）

1. **線 6 をあなたの手で**（§1.2）: `tools/probe_p7.py --watch` を回し、**印つきの job から `recipe_export_result` が 1 行できる**こと、
   **`matched_by='marker'`**、**`seed_changed` の検出**、**印の無い job では作られない**こと、
   **タグ付けの job（`outputs_count: 0`）で `GET /api/jobs/{id}` を呼ばない**こと（**実装の記録の主張を自分で再現する**）。
   **偽の ComfyUI ではなく、本物の `/api/jobs` の形**と突き合わせる（**一覧に `workflow` が無い**・`create_time` が ms）。
2. **監視の規律**: **必要なときだけ手で開始**（常駐しない）／**2 秒**／**既読は `create_time` 基準＋処理済み集合**／
   **`in_progress` を既読にしない**／**繋がらない周期で基準を動かさない**（実装者が直した穴。**本当に直っているか**）／
   **再起動しても二度登録しない**（`watcher_state`。**境界の `>` と `>=`** を自分で叩く）／**1 周期 20 枚の上限**。
3. **`execution_cached` の見分け**: 「保存ノードが `cached` に含まれるか」。**本物の `/api/jobs/{id}` の `execution_status.messages`** で
   形を確かめ、**偽の応答だけで済ませていないか**を見る。
4. **印の照合**: **`subfolder` の前方一致**（**Windows のバックスラッシュ**）＋**PNG の `prompt` の保険**。
   **実装者が挙げた設計の穴 1**（ファイル名だけに印が入る設定だと当たらない）が**実害として出るか**を判定する。
5. **結果の登録**: **`asset` に登録**されるか（**既にある画像と同じ sha256 のとき**は？）／**`GET /view` の取り込み**（推定が外れたとき）／
   **sidecar** の中身／**指標**（`same_hash` / `seed_changed` / `hash_mismatch` / SSIM と pHash）／**`ux_result_asset` で二度登録しない**。
6. **`GET` は 1 バイトも書かない**（**監視の 1 周期も**）。**新しい `POST` は `Host: evil` / `Content-Type: text/plain` で 403**、
   **`actor` の語彙は 422**、**合否は `human` だけ**（`agent` は 403）、**上書き＋`verdict_at` / `verdict_actor`**、
   **元の `recipe_record` が変わらない**。
7. **テストが本当に落ちるか**（23 件）。**壊すと落ちる**形か。**揺れない**か（**この段で実装者が書いた同時投入のテストは
   私が決定的な形に直した**（`tests/test_recipe.py`。前の版は 2 本のスレッドのタイミング任せで 10 回中 2 回落ちた）。
   **他のテストにも揺れが無いか**、`pytest` を**複数回**回して見る）。
8. **回帰**: `pytest` **392**（**複数回**）・`gui_smoke` **129**・`gui_layout`（**6 画面**）が緑か。
   **実データ `.data` の `recipe_record` / `watcher_state` が 0 行のまま**か。
9. **実装者が自分で決めた 8 点**と**申し送り 5 件**、**設計の穴 3 件**を判定する（とくに
   **`recipe_export_result` に「`/view` で取り込んだか」の列が無い**——**P7-4 の頭で `fetched INTEGER` を 1 列足す**方針でよいか）。
10. **設計とのずれ**: 実装が `docs/p7-design.md` と違う所。**設計が黙っているのに実装が決めた**所。

## 3. 報告の形式

`docs/p7-3-audit-report.md` に、これまでと同じ形（A 直っていない / B 重大 / C 中程度 / D 軽微 /
E 設計とのずれ / F テストが守っていないもの / G 依頼者への質問（推奨つき）/ H 確かめられなかったこと）。
各項目に**場所**と**実行したコマンド / 再現手順**。最後に**最も重大な 3 件**。

## 4. 往復

```powershell
orca orchestration send --to run:run_5bdd431bf57b --type status --subject p7-3-audit-done `
  --body (Get-Content -Raw $env:TEMP\p7-3-audit.txt) --json
```

- subject は `p7-3-audit-start` / `-mid` / `-done`。待たずに続けて `G` に推奨つきで書いてください。
