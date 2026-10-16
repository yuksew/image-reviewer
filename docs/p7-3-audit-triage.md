> **廃止（2026-10-17。利用者の判断）**: この段は**削除しました**。理由と控えは [`p7-decision.md`](p7-decision.md) を見てください（①PNG を ComfyUI にドラッグすればワークフローが戻るので記録は重複 ②ja2en の英訳も実行すれば取り直せる）。**記録として残しています。**

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
| **B / C / D / E / F** | 監査の各項目 | **B-1〜B-3・C-1〜C-3 と D / E / F の一部は 2026-10-17 に直した**（下の「再確認のあと」）。**前の版のこの行は「G の推奨どおりに直した」と書いていたが、再確認で B-1 / B-2 / C-1 / C-2 / G-5 は実行で否定された**（`docs/p7-3-audit-recheck.md`。**直っていない物を直したと書かない**） |

## 再確認のあと（2026-10-17。**未着手だった 4 件＋新しい 1 件**）

**再確認（`docs/p7-3-audit-recheck.md`）で「A-1〜A-3 は直った。B-1 / B-2 / C-1 / C-2 / G-5 は直っていない」と
判定された**ので、そこを直しました。**前の版の「直した」は A-1〜A-3 と `#/jobs` の 1 行だけが正しく、
B / C は誇張でした**（この節が正）。

| # | 指摘 | どう直したか |
| --- | --- | --- |
| **B-1** | **sidecar を利用者の ComfyUI の出力フォルダ**に `<name>.result.json` で書いていた（`<data>/sidecar` の既存の形と別） | **`capture.write_sidecar()` を使う**（`<data>/sidecar/<sha256>.json`・`schema` / `abi` / `captured_at` / `meta` の**同じ形**）。**結果の隣には書かない**。テストを `<data>/sidecar` を見る形に直し、**「利用者のフォルダに書いたら落ちる」**ようにした |
| **B-2** | **出力フォルダ（実測 729 枚）を黙って登録ルートに足す** | **`start()` では足さない**。`status()` が **`needs_root`** を返し、**画面が「出力先を登録に足す」を出す**（`POST /api/watcher/add-root`。**人だけ**）。**2 回目は増えない**。テスト 1 件 |
| **C-1** | 手で紐付ける口が**最小 seed の書き出しに固定** | **`attach(..., seed=...)`** と **口の `seed`** を足し、`_export_of(seed=...)` を**式の索引（`COALESCE(seed,'')`）で引く**。画面に **seed の入力**。テスト（`seed='2'` で seed 2 の行に付く） |
| **C-2** | **`note` 無しの合否で前のメモが消える** | **送られなかったら触らない**（`note` のキーが無ければ `UPDATE` に含めない）。**空文字を送れば消せる**。テスト 2 件（消えない・消せる） |
| **G-5** | **`_top_up_v6` の `ADD COLUMN` に `CHECK` が無く、同じ v6 で形が 2 つ** | **`CHECK (fetched IN (0, 1))` を付けた**（SQLite の `ADD COLUMN` は列の制約として `CHECK` を受け付ける）。テスト（古い形の表に当てて `sqlite_master` に `CHECK` が入り、**5 を入れると落ちる**） |
| **新 C-R1** | **`texts` の二重計上**（英訳 1 件で 2） | **英訳を数えるのは `_capture_texts()` だけ**にした（`_register_result` の `text_captured`＝「PNG にグラフがある」で足すのをやめた）。テスト（捕獲 1・登録 1 で `texts=1`） |

**あわせて**（P7-4 の監査 A-1〜A-3 / B-1 / C-1 / C-2 / C-4）:
`jobs.js` が **actor を送る**（押すと 200。`gui_layout --screen jobs` が**実際に押して** 200 と向きを見る）／
拡大の「条件の記録」の入口を**画像のすぐ下**へ（`gui_layout --screen asset` が **`rcTop` / `rcVisible`** を毎回見る。
前は 1,250 px・今は 535 px）／`attemptHtml` が **`checked.reasons` の 3 語**を出す（実機で「模型の出力は再現しない」）／
結果の行に**4 指標とメモの入力**、束に **manifest を開く口**（口も足した）／**`?level=`** と **L1→L2 の落ち方**／
**印を付けられないときの選択**（印なしで書き出す／やめる）。

## 直す途中で踏んだこと（記録）

1. **結果の画像 id を記録に渡していた**（記録は**元画像**に 1 つ）。→ 印 → 束 → `recipe_record.source_asset_id` を引く形に直した。
2. **`asset_location.path` は正規化した鍵**（`normalize_path`）。生の `str(path)` で引くと **Windows のドライブの大小文字で当たらない**（`C:\` と `c:\`）。→ 正規化してから引く。
3. **グラフは `record_json` ではなくファイル**（`graph_path`）にある。→ ファイルから読み戻す形にした。
4. **テストのグラフに `PreviewAny` が無かった**（実物の ja2en にはある）。英訳は**その出力にしか出ない**ので、テストにも繋いだ。
