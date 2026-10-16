# P7-2 の実装の記録（書き出し。R12 の中盤）

- 日付: 2026-10-16。設計: `docs/p7-design.md` §0.4・§0.7・§0.8・§0.9・§0.10・§3.3・§6.1・§8.1（16・17・22・23）・§9
- 指示書: `docs/p7-2-implementation-brief.md`。P7-1 の記録: `docs/p7-1-implementation.md`

| ファイル | 行 | 何 |
| --- | --- | --- |
| **`src/image_reviewer/recipe_export.py`** | **662（新規）** | 書き出しの本体（検査・印・`mode` の 3 つ・seed・manifest・`RecipeExportService`） |
| `src/image_reviewer/api/recipes.py` | 77（+31） | `POST /api/recipes/{id}/check`・`GET …/exports`・`POST …/export` |
| `src/image_reviewer/api/__init__.py` / `app.py` | +5 / +4 | `recipe_exports_of()`・サービスの生成と `app.state.recipe_exports`・`include_router` |
| **`tests/test_recipe_export.py`** | **362（新規）** | **20 件**（§8.1 の 16・17・22・23 と、印の前提・原子性・`GET` が書かない・口の守り） |
| `tools/probe_p7.py` | 305（+101） | **`--export`**（複製の 1 枚から seed 2 つを書き出す） |
| `tools/check_contract_p7.py` | 280（+10） | **`--data` を丸ごと消すのをやめた**（下記「自分で決めた点」5） |

**`db.py` と `schemas/` は 1 バイトも触っていません。**

## 実行した結果

| 確かめたこと | 結果 |
| --- | --- |
| `uv run --no-sync pytest -q` | **360 passed**（340 → **+20**） |
| `node tools/gui_smoke.mjs` | **すべて ok**（129 件） |
| `tools/probe_p7.py --export --keep --data .tmp-audit-redo/p72/export/data` | **`['manifest.json', 'seed-1.json', 'seed-2.json']`**。印 `repro-aazsb9m9/seed-1` が**グラフの中にも入っている**。**書き出しの前後で `recipe_hash` が同一**（`sha256:085a042c…`）＝印で鍵が変わらない。seed ノード `7`・理由 `[]` |
| `tools/check_contract_p7.py --data <その複製>`（**本物の jsonschema 4.26.0**） | **実在する manifest 1 件が契約を通る**（NG 0）。`review.json` に `recipes` / `presets` が出ない・既存契約を通る・v6・索引 9 本も OK |
| 実データ `.data/` | **v6 のまま・263 枚・判断 3 件**。`recipe_record` / `recipe_export_attempt` は **0 行**（probe は複製で動いた）。**mtime 不変** |
| **同時投入**（同じ `client_token` で 8 本。P7-1 の監査 A-3 と同じ型を自分で試した） | **8 本とも成功**・**同じ `attempt_id`**（`3jveywpa`）・**束の行 1・ファイルの行 1**。守りを入れる前は 7 本が `IntegrityError` → 500 になる型 |

- テストの内訳（20 件）: 鍵と印（2）・seed の文字列と 2^64 の折り返し・`attempt_id` の長さ（3）・
  前提 1／前提 2／前提 3＋動的コンボ（3）・置き場と manifest の形（1）・`mode` の 3 つと記録の不変（1）・
  `client_token` の再送と 409（2）・`KSampler` 無し（1）・`impossible` の関所（1）・繋がらないとき（1）・
  原子性（1）・`mode` の写し（1）・`GET` が書かない（1）・口の守り（1）・小道具（2）。

## 自分で決めた点（申し送りつき）

1. **`marker=false` は 422**。`marker_skip_reason` の語彙は **前提 1〜3 だけ**（DDL の `CHECK`）で、
   「人が印を省いた」状態を表す語が無い。**印を省く道は前提が外れたときだけ**にした（表の `CHECK` と食い違わない）。
   設計 §3.3 の本文は `marker: true` の例だけなので、**この解釈を設計に 1 行足すとよい**。
2. **manifest は契約の形に厳密に合わせた**。最初は `marker` / `graphs` / `seed_node` / `other_ksamplers` /
   `status` / `reasons` / `expected_prefix` を**上に**置いていたが、契約が `additionalProperties: false` なので
   **`check_contract_p7.py` が NG を出した**（実行で踏んだ）。1 ファイル 1 件は **`seeds[]`**、
   判定と理由・検査の有無・手順は **`notes`**、印を省いた理由は **`marker_skipped`** に入れた。
   `other_ksamplers` は `notes.instruction` の文に織り込んだ（契約に置き場が無いため）。
3. **印は `recipe_export` の行（ファイル 1 件ごと）に持つ**。`recipe_export_attempt` には `marker` の列が無く、
   `recipe_export` 側に **`CHECK ((marker IS NULL) <> (marker_skip_reason IS NULL))`** があるため
   （段ごとにファイルごとの印を書く）。束の側には `marker_skip_reason` を残した。
4. **`first_ksampler` は「保存ノードに近い方」**（幅優先）。残りは `other_ksamplers` として manifest の手順文に出る。
5. **`check_contract_p7.py --data` が中身を丸ごと消していた**のを直した（`--fresh` のときだけ消す）。
   **実際にこれで probe の書き出しを消した**（原因を突き止めるまで「一時物が誰かに消された」と誤解した）。
   既定の下見の置き場は `.tmp-p7-0/contract` で、**書き出しの置き場とは別**にするのが安全。
6. **宣言のキャッシュは正規化した形で持つ**。生の `/object_info` の応答を入れていたので、**2 回目の呼び出しで
   `KeyError: 'required'`** になった（テストで踏んだ）。60 秒の寿命は §0.8 のとおり。
7. **probe は「保存ノードのある本物のグラフ」を持つ記録を選ぶ**。契約の検査が入れた見本の行（`rec1`）を拾うと、
   グラフのファイルが無いので前提 1 で印なしになる（**その道も動くことは確かめられた**）。
   `KSampler` の無いグラフでは `422 no_sampler` を受けて **seed 無し 1 ファイル**に落とす。
8. **同時に同じ `client_token` で来たら 500 にしない**（P7-1 の監査 **A-3** と同じ型）。
   錠の外で ComfyUI を待ってから書くので、窓の間に入った 2 本目が `ux_attempt_token` に当たる。
   `IntegrityError` を受けて**先に入った束を返す**（`replayed`）。**8 本同時で 8 本とも成功・同じ `attempt_id`** を実行で確認。
9. **消えたグラフは `_load` が PNG から作り直して書く**（設計 §0.4）。**P7-1 の監査 A-4 は
   `RecipeService.get()` が消えた絶対パスを返す件**なので、**`recipe.py` 側の直しは P7-1 の担当**（私は触っていない）。

## 申し送り

1. **設計 §1.2 の線 2 の数**は、P7-1 の実測（**`exact` 182 / `approx` 1 / `impossible` 80**）が正で、
   設計の文面（183 / 0 / 80）は**ja2en の 1 枚が `text_not_captured` で `approx` に残る**ことを見落としている
   （P7-1 の記録 §「判定の数の読み方」）。**設計の文面を直す必要がある**（P7-2 では触っていない）。
2. **`comfyui.output_dir` はまだ設定に無い**（`settings` の行が無い）。P7-3 の監視が結果の実体を拾うのに要る
   （点検 G-1）。**manifest の `output_dir` は設定があるときだけ入る**。
3. **`recipe_export_result` は P7-3**（監視と合否）。P7-2 では 1 行も書いていない。
4. **`review.json` は変えていない**（P7-0 のテストで固定済み）。
5. 一時物: `.tmp-audit-redo/p72/export/data`（263 枚の複製＋書き出し 1 件＋契約の検査の見本行）を残置。
   **消してもよい**（作り直しは `tools/probe_p7.py --export --keep --data <そこ>`）。
