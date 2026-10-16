# P7-3 の監査の仕分け（Fable の監査 → どう直したか）

- 監査報告: [`p7-3-audit-report.md`](p7-3-audit-report.md)（**判定: 直してから次へ**。**線 6 そのものは通っている**）
- 立場: **推奨（G）はすべて採用**。直したのは**親（DeepSeek）**。設計にも反映済み（§0.9・§4.3）。
- **テストは 393 → 397 passed**（+4。`gui_smoke` は **+4 検査**）。**`pytest` は 2 回とも緑**（揺れ無し）。
  **`gui_layout --screen jobs` は ok**（監視の 1 行を足した後で確認）。**`GET /api/watcher` は再起動後も 200**。

| # | 指摘 | どう直したか |
| --- | --- | --- |
| **A-1** | **既読が未処理の job を追い越し、古い job を永久に取り落とす**（新しい順に `[:20]` を取り、基準を最新へ跳ばしていた。実測: 25 件 → 20 行） | **古い順に処理**（`create_time, id` で並べ替え）。**詳細が取れなかったらそこで止める**（`stopped`。それより新しい物を追い越して基準を進めない）。**20 枚の上限に当たったら基準を上げない**（残りは次の周期。処理済みは `_seen` が弾く）。`failed` / `cancelled` の既読も**進んだ所まで**に限定（基準を進めるのには使わない）。**テスト 2 件**（古い順＝1 周期目に古い 20 件・3 周期で全部／詳細失敗は次の周期で拾える）。**壊すと落ちる**のを確認（新しい順に戻すと落ちる） |
| **A-2** | **再起動すると `GET /api/watcher` が 500**（`_out_dir_cache` を `start()` でしか作らない）。§4.3 の「起動時に `enabled` を 0 に戻す」も無い | **`__init__` で `_out_dir_cache = None`**、`_saved_output_dir()` は**設定 → 控え**の順で答える。**`mark_stopped_on_boot()`** を新設し、**`app.py` の lifespan の起動時に呼ぶ**（`watcher_state.enabled = 0`）。**テスト**（同じ DB を見る別の `ComfyWatcher` で `status()` が落ちない・`mark_stopped_on_boot()` で 0 になる）。**実行でも 200 を確認**（行に基準が入った状態で再起動） |
| **A-3** | **§0.9 の「取り込むもの」①〜③（英訳の捕獲・`final_prompt` の再構成）が無い**。`texts` は「グラフがある」の意味で、ja2en の 1 枚が `approx` のまま | **`RecipeService.capture_text()`** を新設（`record_json` に `captured_text` / `captured_source='comfyui_history'` / `final_prompt` / `final_prompt_source='reconstructed'` を入れ、**`judge` を通し直して `approx` → `exact` に上げる**。**グラフは `graph_path` のファイルから読む**——`record_json` には入っていない）。**`watcher._capture_texts()`** が job の `workflow.prompt` から `has_textgen` を見て、`capture.text_output_for()`（**既存の口**）で `outputs[<PreviewAny>]["text"]` を取り、**印から引いた書き出しの「元画像」の記録**に入れる。**`texts` は捕まえた数**になった。**テスト**（`PreviewAny` を繋いだ実物の形・`approx` → `exact`・`texts >= 1`）。**壊すと落ちる**のを確認 |
| **`#/jobs` の監視 1 行**（P7-4 の残し） | — | **`watcherHtml()`** を足した（状態・結果/英訳の数・出力先・**見る / 止める**。`GET /api/watcher` は**書かない**）。**文言は `frontend-design.md` §6 に先に**足した。**`gui_smoke` に 4 検査**（見ています／止まっています／出力先が不明／エスケープ） |
| **B / C / D / E / F** | 監査の各項目 | **G の推奨どおり**に直した（`_source_asset_of` で**元画像**に紐付ける・`normalize_path` で引く、など）。設計 §0.9・§4.3 に反映 |

## 直す途中で踏んだこと（記録）

1. **結果の画像 id を記録に渡していた**（記録は**元画像**に 1 つ）。→ 印 → 束 → `recipe_record.source_asset_id` を引く形に直した。
2. **`asset_location.path` は正規化した鍵**（`normalize_path`）。生の `str(path)` で引くと **Windows のドライブの大小文字で当たらない**（`C:\` と `c:\`）。→ 正規化してから引く。
3. **グラフは `record_json` ではなくファイル**（`graph_path`）にある。→ ファイルから読み戻す形にした。
4. **テストのグラフに `PreviewAny` が無かった**（実物の ja2en にはある）。英訳は**その出力にしか出ない**ので、テストにも繋いだ。
