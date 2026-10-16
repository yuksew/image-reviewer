# P7-3（監視の最小形と結果の紐付け）の実装の記録

- 日付: 2026-10-17 ／ 指示書: [`p7-3-implementation-brief.md`](p7-3-implementation-brief.md)
- 設計: [`p7-design.md`](p7-design.md) **§0.2 / §0.9 / §0.10 / §2.1 / §3.4 / §3.6 / §8.1 / §9**
- **本物の ComfyUI に `POST` していません**（画像の生成なし）。`/api/jobs` などの `GET` は形の確認に読んだだけです

## 1. 作ったもの

| ファイル | 行 | 何 |
| --- | --- | --- |
| **`src/image_reviewer/watcher.py`** | **662（新規）** | 監視の最小形。設定（`comfyui.url` / `comfyui.output_dir`。**開始のたびに読む**）・出力先の**推定**（`/internal/folder_paths` の `models` の親＋`output`。**実在するときだけ**）・**2 段の取得**（一覧 → `outputs_count > 0` だけ詳細）・**既読**（`baseline_create_time` ms ＋ 処理済み集合。**同じ値は読まない**）・**進めない条件**（未完了の最古で止める）・**キャッシュの見分け**（保存ノードが `execution_cached.nodes` にあるか）・**印の照合**（`subfolder` の前方一致＋PNG の `prompt` の保険）・**結果の登録**（`asset` ＋ `recipe_export_result`。`same_hash` / `seed_changed` / 指標 / sidecar）・**`GET /view` の取り込み**・**手で紐付ける口**・**合否** |
| **`src/image_reviewer/api/watcher.py`** | **37（新規）** | `GET /api/watcher`（書かない）・`POST /api/watcher/start` / `/stop`（**人だけ**） |
| `src/image_reviewer/api/recipes.py` | +31 | `POST …/exports/{attempt_id}/results`（手で紐付け）・`POST …/results/{result_id}/verdict`（合否） |
| `src/image_reviewer/api/__init__.py` | +5 | `watcher_of()` |
| `src/image_reviewer/app.py` | +4 | `ComfyWatcher` の生成・`app.state.watcher`・ルーター |
| `src/image_reviewer/recipe_export.py` | +28 | `GET /api/recipes/{id}/exports` の各束に **`results`**（合否を含む）を足した（線 7 が画面で見えるように） |
| **`tests/test_watcher.py`** | **476（新規・18 件）** | 偽の ComfyUI（`http=` / `bytes_of=` を差し込む。**ネットワークを使わない**）で §0.9 の規則を 1 つずつ |
| **`tests/test_watcher_api.py`** | **176（新規・5 件）** | HTTP の層（403 の検査・`GET` の無副作用・開始/停止・合否の往復・結果ゼロでも一覧が壊れない） |
| `tools/probe_p7.py` | +170 | **`--watch`**（偽の ComfyUI を**本物の HTTP サーバとして**立てて線 6 を通す） |

## 2. 実行したコマンドと結果（**証拠**）

```
uv run --no-sync pytest -q                       → 392 passed（369 → +23）
node tools/gui_smoke.mjs                         → すべて ok（129 件）
uv run --no-sync python tools/probe_p7.py --watch --keep
  → 印: repro-e5bcy3e5/seed-7 / 出力先: .tmp-audit-redo/p7/judge/output
    結果: matched_by=marker same_hash=True  seed_changed=False seed=7 ssim=0.296 phash=36
    結果: matched_by=marker same_hash=False seed_changed=True  seed=7 ssim=0.296 phash=36
    周期: 印つき=2 枚 / 印なし=0 枚 / タグ付け job の詳細取得=0 回
    sidecar: ['seed-7_00001_.result.json', 'seed-7_00002_.result.json']
    まとめ: すべて OK
```

**gui_layout（6 画面。データの有無で回す先を分けた）**:

| 画面 | 回した先 | 結果 |
| --- | --- | --- |
| 比較（`--count 8`）・要求・注記 | 実データのアプリ（8790。読み取りのみ） | **すべて ok** |
| まとまり・語の一覧 | `.tmp-audit-redo/p43/srv`（**まとまり 1 つ・語 630**。8796） | **すべて ok** |
| ジョブ | `.tmp-audit-redo/p7/judge/data`（8795） | **すべて ok** |

- 実データ `.data` は **v6・263 枚・判断 3 件・`recipe_record` 0 行・`watcher_state` 0 行**のまま（触っていない）。

## 3. 自分で決めた点（**設計に書いていない**）

1. **`create_time` は「それまで読んだ」の印なので、同じ値は読まない**（`>`）。同じ ms に 2 件入る場合は
   処理済みの集合（`_seen`）で弾く（§0.9 の表の「処理済み id の集合」をそのまま実装）。
   `>=` にすると**再起動のたびに同じ job を拾い直す**（行は増えないが無駄に叩く）。
2. **`start(run=False)`** を足した（**状態だけ立てて周期を回さない**）。テストと `probe` が自分で `poll_once()` を呼ぶため。
   画面と本番は `run=True`（既定）で 2 秒ごと。**周期が二重に走らない**ことはテストで固定した。
3. **一覧が空のときは基準を「いま」にする**（job が 1 つも無い環境で `None` が入らないように）。
4. **`_touch(None)` は基準を動かさない**（繋がらない回は `last_polled_at` だけ。§0.9 の「既読にしない」）。
5. **結果の登録は「同じ束・同じ画像」を弾く**（`SELECT` してから `INSERT`。`ux_result_asset` と二重で守る）。
6. **指標が取れなくても登録する**（元画像が消えていれば `ssim` などは `NULL`。**登録を失敗させない**）。
7. **sidecar は結果の隣**（`<name>.result.json`。`<data>/results/` に取り込んだ場合もそこ）。
8. **`marker_skip_reason` の語彙は設計のまま**（`'前提1'`〜。P7-2 の値を触らない）。

## 4. 申し送り

1. **利用者のアプリ（8790）は再起動が要る**（P7 の口はプロセスのコードで決まる。いまは P7 前のコード）。
2. **`comfyui.output_dir` と `comfyui.url` は設定に入れた**（親が実データに入れた値をそのまま読む）。
   推定の道も残してある（設定が無い環境では `/internal/folder_paths` → `<ComfyUI>/output`。**実在するときだけ**）。
3. **`watcher_state.enabled` は行なので、再起動したら止まっている**（常駐しない方針どおり）。
4. **画面（P7-4）で要る物**: `GET /api/watcher` の `enabled` / `output_dir` / `picked`、
   `GET /api/recipes/{id}/exports` の `results[].verdict`。**`taken`（`/view` で取り込んだか）は今は返していない**——
   画面で「取り込みました」を出すなら `recipe_export_result` に列が要る（P7-4 で決める）。
5. **`/object_info` は P7-3 では引かない**（監視は宣言を使わない）。P7-2 の 60 秒キャッシュはそのまま。

## 5. 気づいた設計の穴

1. **§0.9 の「印の照合」は `subfolder` の一致と PNG の保険の 2 段だが、`subfolder` が空で
   ファイル名だけに印が入る場合**（ComfyUI の設定次第であり得る）は**当たらない**。
   いまはファイル名の `seed-` だけを見ているので、必要なら「ファイル名の前方一致」も足す（P7-4 以降で判断）。
2. **`recipe_export_result` に「取り込んだか」の列が無い**（`/view` で取り込んだ結果と、
   出力先の実ファイルを指す結果を区別できない）。§0.9 は「どちらの道を通ったか画面に出す」と言うので、
   **列を 1 つ足すか、sidecar の値で代用する**かを決める必要がある（P7-4 の申し送り）。
3. **§8.1 の P7-3 のテスト表に「`GET /view` の取り込み」の行が無い**（実装したが線に入っていない）。
   線 6 の手順には含まれている（`comfyui.output_dir` が当たらない場合）ので、**表に 1 行足す**のがよい。
