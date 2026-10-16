# P7-3 監査の再確認（A-1〜A-3 の修正と、仕分けの主張の再現）

- 日付: 2026-10-17（01:50〜02:10 JST）／元の報告: `docs/p7-3-audit-report.md`／仕分け: `docs/p7-3-audit-triage.md`／修正の commit: **80f3eaa**
- 対象: `src/image_reviewer/watcher.py`（**849 行**、01:43）・`recipe.py`（876 行、01:42）・`app.py`（01:33）・`tests/test_watcher.py`（+4 件、01:43）・`apps/gui/jobs.js`（監視の 1 行）
- 方法: 元の報告の自前の検査（`.tmp-audit-redo/p73/watch_checks.py`）をそのまま再実行し、A-1 と A-3 は条件を厳しくした物（`.tmp-audit-redo/p74/recheck_a1_a3.out.txt`）を足した。再起動は別の `Store` を開き直して確かめた（`recheck_restart.out.txt`）。

## 判定: **A-1〜A-3 は直った**。**B-1 / B-2 / C-1 / C-2 は直っていない**（仕分けは「G の推奨どおりに直した」と書くが、実行で変わっていない）

| # | 元の指摘 | 再確認 | 結果 |
| --- | --- | --- | --- |
| **A-1** | 既読が未処理の job を追い越す | 新しい job **25 件**（画像の中身を全部変えた） → 周期ごとの登録 **[20, 5, 0]**、**行 25**、`_seen` 25。1 周期目の直後は**基準が開始時のまま**（20 枚の上限で上げない）、**古い順**（`j0` を先に処理、`j24` は未処理）。古い job の詳細だけ落とす → 1 周期目 0、**2 周期目で 2 件とも拾う** | **直った** |
| **A-2** | 再起動で `GET /api/watcher` が 500、`enabled` が 1 のまま | 行を `enabled=1` にして別の `Store` で `ComfyWatcher` を作り直す → `status()` が **200 相当で返る**（`output_dir` は設定から）。`mark_stopped_on_boot()` で **0 に戻る**（`app.py:86-` の lifespan から呼ばれる）。`poll_once()` は `{'skipped': 'stopped'}`。8790 の利用者のアプリ（新コードで再起動済み）でも `GET /api/watcher` は **200** | **直った** |
| **A-3** | 英訳の捕獲が無い | ja2en の形（元のグラフ ＋ `PreviewAny`、書き出しは `pin_text`）で job の `outputs["11"]["text"]` に英訳 → 記録が **`approx` → `exact`**、`final_prompt='(masterpiece, best quality), safe,\n\na girl …'`（前置きを戻して再構成）、`final_prompt_source=reconstructed`、`captured_source=comfyui_history`、`record_json` に `captured_text` / `prompt_id` / `captured_from_node`。画像の無い job では 0 | **直った** |
| **B-1** | sidecar を利用者の ComfyUI の出力フォルダに `<name>.result.json` で書く | `watcher.py:678-697` は**そのまま**（`path.with_suffix(".result.json")`）。`capture.write_sidecar` は使っていない | **直っていない** |
| **B-2** | 出力フォルダを黙って登録ルートに足す | 8791 で `POST /api/watcher/start` → `root` が **2 → 3**。応答に `root_added` は**無い** | **直っていない** |
| **C-1** | 手で紐付ける口が最小 seed の export に固定 | `{"result_asset_id": …, "seed": "2"}` を送っても **seed 1 の export** に付く（`attach()` に `seed` 引数が無い） | **直っていない** |
| **C-2** | `note` 無しの合否で前の `note` が消える | `close/近い` → `different/違う` → `same`（note 無し）で **`note=None`**（`watcher.py:741-742`） | **直っていない** |
| G-5 | `_top_up_v6` の `ADD COLUMN` に `CHECK` が無い | P7-3 の複製（`fetched` 無しの v6）は `_top_up_v6` で列が入った（実データも同じ道で入っている）が、**`sqlite_master` に `fetched IN (0, 1)` が無い**＝新規の v6 と形が 2 つ | **直っていない**（列は入る） |
| `#/jobs` の 1 行 | — | 本物の Chrome で「監視 止まっています 結果 0 / 英訳 0 ・ 設定の場所: …」と **「見る」**が出る。**ただし押すと 403**（P7-4 の報告 A-1） | 表示は在る。**動かない** |

## 新しく見つけたこと

- **C-R1 `texts` が二重に数えられる。** 英訳 1 件の捕獲で周期の `texts=2`（`recheck_a1_a3.out.txt`）。`_take_images()` の古い数え方（`watcher.py:441-442`。`text_captured`＝「PNG にグラフがある」）が残ったまま、新しい `_capture_texts()` の戻り値を足している（`:445`）。`#/jobs` の「英訳 N」が 2 倍になる。古い 2 行を消す。
- **D-R1** 後から来た別の job の英訳で `final_prompt` が**上書き**される（同じ記録に 2 回目の捕獲）。最新を正とするなら仕様だが、記録に残すなら書いておく。
- **D-R2** 再起動後、**同じ ms の 2 件目**の job は拾われない（`>` の境界。元の報告 H。実装者の決定 1 どおりの限界）。
- 仕分けの「**B / C / D / E / F は G の推奨どおりに直した**」は、上の 5 項目については**実行で否定**された。直したのは A-1〜A-3 と `#/jobs` の 1 行だけ。持ち越すなら持ち越しと書く（P7-4 の報告 G-6）。

## 実行したコマンド

```
python .tmp-audit-redo/p73/watch_checks.py              → .tmp-audit-redo/p74/recheck_watch.out.txt（(a)〜(i) の再実行）
python（recheck_a1_a3）                                  → .tmp-audit-redo/p74/recheck_a1_a3.out.txt（25 件・上限・古い順・英訳）
python（recheck_restart）                                → .tmp-audit-redo/p74/recheck_restart.out.txt
python .tmp-audit-redo/p74/http_roundtrip.py 8791 ／ watch_http（start → root・attach seed）→ http_roundtrip.out.txt / watch_http.out.txt
node .tmp-audit-redo/p74/cdp.mjs http://127.0.0.1:8791/#/jobs page_jobs.js   → chrome.out.txt（見る を押す）
```
