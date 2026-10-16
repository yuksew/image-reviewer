# P7-1 の実装の記録（記録と判定。R12 の前半）

- 日付: 2026-10-16。設計: `docs/p7-design.md` §0.5〜§0.7・§0.10・§3.1〜§3.2・§4.1・§8.1（P7-1 の担当）
- 触ったファイル（**`db.py` と `schemas/` は触っていない**。別のエージェントが P7-0 の監査の指摘を直している）

| ファイル | 行 | 何 |
| --- | --- | --- |
| **`src/image_reviewer/recipe.py`** | **642（新規）** | 再現キー（純関数）・`record_json`・環境の写し・宣言との突き合わせ・判定・`RecipeService` |
| **`src/image_reviewer/api/recipes.py`** | **43（新規）** | `GET/POST /api/assets/{id}/recipe`・`GET /api/recipes` |
| `src/image_reviewer/api/__init__.py` | +5 | `recipes_of(request)` |
| `src/image_reviewer/app.py` | +6 | サービスの生成・`app.state.recipes`・`include_router` |
| **`tests/test_recipe.py`** | **430（新規）** | **23 件**（§8.1 の 1〜4・11・14・15・27〜29・31〜33） |
| **`tools/probe_p7.py`** | **205（新規）** | `--judge`（複製で 263 枚）・`--http`（口から 5 枚） |

## 実行した結果

| 確かめたこと | 結果 |
| --- | --- |
| `uv run --no-sync pytest -q` | **340 passed**（317 → +23） |
| `node tools/gui_smoke.mjs` | **すべて ok**（129 件） |
| `tools/probe_p7.py --judge --keep`（**実データの複製 263 枚**） | **`exact` 182 / `approx` 1 / `impossible` 80**。理由は `missing` 80・`text_not_captured` 1。グラフを書いたのは **183 枚**。**1 枚あたり 中央 1.1 ms・平均 2.1 ms・最悪 146 ms**（宣言の取得込み） |
| `tools/probe_p7.py --http --keep`（口から 5 枚） | `POST` 200/201 → `GET` 200。**記録が読める** |
| 実データ `.data/` | **263 枚・判断 3 件のまま**（下の申し送り 1 を見ること） |

### 判定の数の読み方（**設計の期待値と 1 枚違う**）

- `impossible` **80** = **グラフの無い画像**（JPEG など。`missing`）。
- `approx` **1** = **ja2en の 1 枚**（`01M4Z0KJSS8EXT49JGAZMZGTFJ`）。`CLIPTextEncode` はあるが
  **文字列が分からない**（`StringConcatenate` → `TextGenerate` のリンク参照）ので `text_not_captured`。
  **これは正しい**（英訳は PNG に残らない＝記録の存在理由。§0.9 の監視で捕まえる）。
- `exact` **182** = 残り。**`final_prompt` が `None` でも `CLIPTextEncode` を持たない upscale の 3 枚は `exact`**
  （テキストを使わないグラフは「欠けていない」。§0.6 の決めのとおり）。

→ 設計（点検 A-3）の「`exact` 183 / `approx` 0 / `impossible` 80」は、**ja2en の 1 枚が
`text_not_captured` で `approx` に残る**ことを見落としていた。**正は 182 / 1 / 80**（設計の文面を直す必要がある）。

## 設計からずれた所・自分で決めた所

1. **`reasons` の形を 1 つに揃えた**（`GET` と `POST`、書き込みと再送で同じ）。
   `reasons` は**語（`kind`）の配列**（§3.2 の応答例と同じ）、詳しい説明は **`reason_details`** に分けた。
   揃えないと、再送の応答だけが `{"kind","detail"}` の配列になり、**同じ口が 2 つの形**を返すことになる。
2. **`canonical_graph` は `inputs` と `links` を必ず持つ**（空でもキーを出す）。鍵の材料が**いつも同じ形**になり、
   人が読んだときも差分が取りやすい。
3. **コンボの判定は「最初の要素が配列のとき」だけ**選択肢とみなす（`[["a","b"], {…}]`）。
   前は `["STRING", {…}]` まで選択肢とみなし、**リテラルの文字列が「選択肢に無い」と誤判定**された
   （テストを書いていて踏んだ）。新しい `["COMBO", {"options": […]}]` も受ける。
4. **`node_missing` は「宣言を引いたが無かった」＝値が `None` のとき**。`collect_env` は到達した
   `class_type` を必ず入れるので、`None` は「ComfyUI が知らないノード」を意味する。
5. **`declaration_notes` は展開できない `COMFY_DYNAMIC*` を `notes` に出す**（検査の対象外）。
   入れ子のキー（`sampling_mode.temperature`）が**親の宣言から展開できる**ときだけ照合する。

## 申し送り

1. **実データ `.data` は既に `v6`**（P7-0 の実装者が複製で確かめた後、私が `create_app()` を
   リポジトリ直下で動かしたときに既定の `.data` を開き、**v5 → v6 の移行が走った**）。
   **263 枚・判断 3 件は無傷**。**利用者のアプリ（8790）は P7 より前のコードのまま動いている**ので、
   再起動すると P7 の口が載る（`recipe_record` などは既にある）。
2. **`GET /api/recipes/{id}/graph` と `POST …/check`・`…/export`・`presets`・監視は P7-2 以降**（設計 §9）。
3. **`recipe_export_result.export_id` に `ON DELETE` が無い**（P7-0 からの申し送り）。P7-2 で結果を書くときに決める。
4. **`graph_source` は `png` しか出ない**（`/history` からの捕獲は P3）。語彙には `history` / `sidecar` を残した。
5. **宣言の取得は 1 枚あたり十数回**（`/object_info/{class_type}`）。`probe_p7.py` では probe を使い回したが、
   **口は 1 回ごとに作る**ので、263 枚を HTTP で流すと `/object_info` を 3,000 回引く。
   遅ければ P7-2 で**短い寿命のキャッシュ**（例: 60 秒）を入れる。
