# P7 設計の点検報告（条件の記録。R12）— 実行込み

- 日付: 2026-10-16（JST 16:52〜17:45）
- 指示書: `docs/p7-review-brief.md`
- 点検した版: `docs/p7-design.md` **806 行、mtime 2026-10-16 16:51:39**。突き合わせた本文: `docs/design.md`（1,777 行、15:08:52）、
  `docs/workflow-reproduction.md`（704 行）、`docs/frontend-design.md`（863 行）、`src/image_reviewer/db.py`（553 行、`SCHEMA_VERSION = 5` は 33 行目）、
  `png_meta.py`（369 行）、`capture.py`（185 行）。点検中にこれらの mtime は変わっていない。
- 実行できたか: **できた。** 実データは `mode=ro` と `backup()` の複製（`.tmp-audit-redo/p7/srv/db.sqlite3`）だけ。
  ComfyUI（127.0.0.1:8188、0.39.2、frontend 1.53.10）は **`/api/jobs`・`/history`・`/object_info`・`/system_stats`・
  `/api/customnode/installed`・`/experiment/models/*`・`/internal/folder_paths` の GET** と、**`userdata` に探り 1 件を置いて即消す**だけ。
  **画像は生成していない**（`/prompt` に何も投げていない）。**image-reviewer のサーバは立てていない**（設計の点検なので要らなかった）。
- 触っていないもの: `src/`・`tools/`・`tests/`・`apps/`・`schemas/`・`.data/`（`db.sqlite3` 10-15 14:29、`-wal` 10-16 15:08 のまま）・`.backup/`。
  コミットしていない（点検の途中で実装者が `ca006f8`（16:52:31）に設計書と指示書をコミットした。806 行で中身は同じ。本報告は untracked のまま）。
- 回帰の基準: `uv run --no-sync pytest -q` → **285 passed**（12.99 s）。`node tools/gui_smoke.mjs` → **129 件すべて ok**。
  `gui_layout` は**実行していない**（新しい画面がまだ無く、既存 6 画面は同日の P4-3 再確認で通している）。
- 自前のスクリプトと生の出力: `.tmp-audit-redo/p7/`（`count_real.py` / `history_scan.py` / `check_env.py` / `hash_proto.py` と各 `*.out.txt`、
  `object_info.json` 2.4 MB、`history.json` 4.9 MB、`ddl-trial.sqlite3`、`recipe-manifest.schema.json`）。**消されたら H の手順で作り直せる。**

## 総合判定: **直してから実装**

骨格（監視の最小形を P7 に入れる・`GET` は書かない・`review.json` を変えない・印は `filename_prefix`・再現キーから `filename_prefix` を除く）は
**実測で裏が取れた**。設計の主張のうち、**実データ 183 枚の印の前提**（§0.7）と**印を入れても鍵が変わらない**（§0.5）は
**183/183 で成り立つ**（試作の鍵で確かめた。C-0）。しかし次の 3 件は**設計のまま実装すると、利用者の本来の用途（ja2en の画像）が
書き出せない／線が評価できない／結果の画像を登録できない**ので、先に直す必要がある。

**最も重大な 3 件**

1. **A-1 書き出す前の検査 ③（入力キーが宣言に含まれるか）が、利用者の ja2en のグラフを `unresolved` で落とす。**
   `TextGenerate.sampling_mode` は `COMFY_DYNAMICCOMBO_V3` で、API グラフのキーは `sampling_mode.temperature` など **7 個の入れ子名**。
   `/object_info` の `input.required` のキーは `sampling_mode` だけ。実データで `TextGenerate` を持つ唯一の 1 枚が
   **検査 ③ で `unresolved`** になる（`check_env.py`: `per image {'ok': 182, 'unresolved:key': 1}`）。
   `workflow-reproduction.md` §4.7 手順 4 は「含まれないキーがあれば**不可（unresolved）**…書き出さない」なので、**L1 が要る画像ほど書き出せない**。
2. **A-3 「記録の判定」と「書き出しの判定」が混ざっていて、線 2 と線 4 が設計のまま評価できない。**
   §0.5 は「L1 はキーが必ず変わる」、§3.2 の例は L1 の記録に `text_pinned`、線 4 は「seed を固定して書き出したとき鍵が記録と一致」。
   試作の鍵では **L1 変換で鍵が変わるのは 183 枚中 1 枚**（`TextGenerate` を持つ 1 枚）で、**182 枚は L1 でも変わらない**。
   「必ず変わる」は実データでは 1/183 であり、`text_pinned` を**記録時**に付けると `exact` が 0 になって線 2 の内訳が意味を失う。
   **記録時の理由**と**書き出し時の理由**を分け、線 2 の期待値を**数で**書く（この環境で設計の規則どおりなら **exact 179・approx 4・impossible 80**。
   approx 4 の内訳は A-1 の 1 枚と、`KSampler` も `CLIPTextEncode` も無い upscale の 3 枚が「L1 なのに `final_prompt` が無い → `text_not_captured`」に落ちる分。
   A-1 を直し、`text_not_captured` を「到達部分グラフに `CLIPTextEncode` があるときだけ」にすれば **183・0・80**）。
3. **B-1 監視が拾った結果の画像を `asset` に登録する「実体のパス」を知る手段が設計に無い。**
   `GET /api/jobs/{id}` の `outputs[].images[]` は `filename` / `subfolder` / `type` だけ（実測）。`/internal/folder_paths` は 34 種の
   モデルフォルダを返すが **`output` も `temp` も無い**（実測）。`/system_stats` にも無い。**設定 `comfyui.output_dir`**（＋ `/view` で
   取り寄せる控え）を足し、**登録ルート外を触らない規則**（`design.md` §19.3-10）との関係を決める必要がある（G-1）。

**判定の根拠になった数字**（詳細は各節）

| 何 | 実測 |
| --- | --- |
| 実データ | 263 枚・全部 `.png`・v5・判断 3。**グラフあり 183**（`api` 182・`api+ui` 1）、**無し 80**（`prompt` チャンクが無い PNG。JPEG ではない） |
| 印の前提 | 183 枚すべて **`SaveImage` 1 個・`PreviewImage` 0・`filename_prefix` リテラル**。ただし値は **`__OUTPUT_PREFIX__` が 172**（別ツールの差し込み用の置き札）、`speed_bench` 7、`illust-authoring/upscale` 3、`ComfyUI/Anima/20261010/132800` 1 |
| KSampler | 到達できる `KSampler` 1 個が 180 枚、**0 個が 3 枚**（`upscale` の 3 枚。seed 無し）。2 個以上は 0。`KSamplerAdvanced` 等は 0 |
| TextGenerate | **1 枚だけ**（`final_prompt` は `reconstructed`）。179 枚は `png_literal`、3 枚は `None`（上の 3 枚） |
| 鍵の試作 | 印を入れても **183/183 不変**。seed を変えると 180/180 変わる。L1 変換で変わるのは **1/183**。異なり **183/183**。1 鍵 **0.03 ms** |
| 検査の試作 | ノード無し 0、combo 値に無いモデル 0、**宣言に無い入力キー 1 枚（`TextGenerate.sampling_mode.*` の 7 キー）** |
| `/object_info` | **1,212 ノード・2,394,596 バイト**。毎回接続 5 回 **439 / 413 / 422 / 429 / 910 ms**、keep-alive 5 回 **435 / 429 / 414 / 416 / 423 ms**、`json.loads` **12〜17 ms**。**`/object_info/{class_type}` は 0 ms・0.7〜3 KB** |
| ComfyUI の `/api/jobs` | `limit=50` を 10 回: **min 3.2 / 中央 4.5 / max 31.1 ms**。詳細 1 件 **1.4 ms**。全 731 件: 画像あり 427・画像なし 301・cancelled 2・failed 1。**新しい順**、`?status=completed` が効く、無い id は 404 |
| `/history` | 4,882,254 バイト・97 ms。731 件中 画像 427・タグ付け 38・テキスト出力 206・UI グラフ 161 |
| `execution_cached` | **731 件すべて**に出る（当たらないときは `nodes: []`）。`nodes` が空でないのは 480 件（うち画像あり 426）。**保存ノードが cached に入った job は 0**、同じファイル名が別 job に出た例も 0 |
| 印の実際の形 | `filename_prefix = "ComfyUI/Anima/20261010/132800"` → `subfolder = "ComfyUI\\Anima\\20261010"`（**バックスラッシュ**）、`filename = "132800_00018_.png"` |
| 環境の写しの口 | `/system_stats` 1 ms・1.1 KB、`/api/customnode/installed` 2 ms、`/experiment/models/loras` 1 ms、`diffusion_models` 1 ms |
| `userdata` | `POST …?overwrite=false` → **200**、同名を再度 → **409 "File already exists"**、一覧に出る、`DELETE` → **204**、消えた、`GET` → 404 |
| frontend 1.53.10 | `loadApiJson` はリテラルの入力を **`widget.value = 値`** で戻す（**`filename_prefix` は保持される**）。無い `class_type` は `has_errors` の仮ノード＋欠落の警告。`seed` の INT ウィジェットは **`control_after_generate` が `true`（文字列でない）なら `randomize`**。`Comfy.WidgetControlMode` の既定は **`after`** |
| DDL の試行 | §2.1 を複製に 2 回流して **24 表・`integrity_check` ok**。6 つの問い合わせが**意図した索引を使う**。**`seed` が NULL だと同じ `attempt_id` で 2 行入る**。**`marker` が NULL だと `NOT NULL` で落ちる**。記録のある `asset` の削除は **FK で落ちる** |
| manifest 契約 | `check_schema` ok。`expected_prefix` 欠け・`abi` 数値・`seed` 数値・余分な `mode` は**落ちる**。**`export_hashes: {"x": 123}`・`notes: {}`・`notes` にでたらめ・`seeds: []` は通る** |

---

## A. 設計の主張が成り立たない（必ず直す）

### A-1 書き出す前の検査 ③ が、動的コンボの入れ子名を「宣言に無いキー」と誤判定する（§0.8 ③、`workflow-reproduction.md` §4.7 手順 4・§4.5）

- **場所**: `p7-design.md` §0.8（「③ 各ノードの `inputs` のキーが `input.required` / `input.optional` のキーに含まれるか」）、§8.1-12、
  `workflow-reproduction.md` §4.7 手順 4（「含まれないキーがあれば『不可（unresolved）』…書き出さない」。**一方 `p7-design.md` §3.2 は「ComfyUI につながらない →
  `reasons` に `unresolved`」で `status` は `approx`、`frontend-design.md` §4.7 の表も `unresolved` を「置くと書き出せます」と近似の文言で出す**。
  `unresolved` が「不可」と「近似」の両方に置かれていて、§4.5 の `kind` の表は `status` との対応を書いていない）。
- **実測**（`.tmp-audit-redo/p7/check_env.py`。保存した `/object_info` と実データ 183 枚のグラフ）:
  ```
  per image {'ok': 182, 'unresolved:key': 1}
  undeclared input keys [('TextGenerate.sampling_mode.temperature', 1), ('…top_k', 1), ('…top_p', 1), ('…min_p', 1),
                         ('…repetition_penalty', 1), ('…seed', 1), ('…presence_penalty', 1)]
  TextGenerate required keys ['clip', 'prompt', 'max_length', 'sampling_mode']
  sampling_mode = ["COMFY_DYNAMICCOMBO_V3", {"options": [{"key": "on", "inputs": {"required": {"temperature": …, "top_k": …, "seed": …},
                                                                           "optional": {"presence_penalty": …}}}, {"key": "off", …}]}]
  ```
  実データで `TextGenerate` を持つ唯一の 1 枚（ja2en の経路。L1 の存在理由）が、**③ の規則どおりだと `unresolved`** になる。
  ComfyUI はこのグラフを実行しているので（この画像がそれ）、**検査の方が間違っている**。
- **直し方**: 宣言のキーを集めるとき **`COMFY_DYNAMICCOMBO_V3` を展開する**: `inputs[<name>]` の値（`"on"`）に対応する `options[].key` の
  `inputs.required / optional` を **`<name>.<key>`** の形で宣言に足す。`"off"` なら入れ子は無い。他にも `V3` の動的な型があり得るので、
  **型名が `COMFY_DYNAMIC` で始まる宣言は「展開できなければ検査の対象外（`notes` に出す）」**として、**黙って `unresolved` にしない**。
  §4.5 の `unresolved` は `approx`（書き出せる）か `impossible`（書き出さない）かを 1 つに決める（推奨は G-7: **モデルが combo に無い → `impossible`、
  キーの差 → `approx` ＋ キー名**。L1/L2 の書き出し自体は可能で、利用者が開いて直せる）。
- **テスト**（§8.1-12 に足す）: `TextGenerate` 入りのグラフ（`sampling_mode.temperature` を持つ）とそのフィクスチャの `/object_info` で
  **`unresolved` が出ない**こと。展開を外すと落ちる。

### A-2 §2.1 の DDL が §3.3 の約束と矛盾する 3 点（実行で確認）

`.tmp-audit-redo/p7/ddl-trial.sqlite3`（複製に §2.1 を 2 回流した）で:

| # | 矛盾 | 実測 | 直し方 |
| --- | --- | --- | --- |
| a | **`recipe_export.marker TEXT NOT NULL`** なのに、§0.7・§3.3 は「前提が外れたら**印なしで書き出す**（`marker_skipped` / `marker_skip_reason`）」 | `marker` に NULL を入れると **`NOT NULL constraint failed: recipe_export.marker`** | `marker TEXT`（NULL 可）＋ `CHECK ((marker IS NULL) <> (marker_skip_reason IS NULL))` |
| b | §0.10 は「書き出しの口にも `client_token` を付ける（同じ token の再送は同じ `attempt_id`）」、§8.1-16 もそれを固定するが、**`recipe_export` に `client_token` の列が無い** | DDL に無い（`recipe_record` にはある） | **束の表** `recipe_export_attempt(attempt_id PK, recipe_id, mode, client_token UNIQUE, marker_skip_reason, checked_json, manifest_path, export_dir, seed_node, created_at)` を 1 つ足し、seed 行（`recipe_export`）がそれを参照する。`attempt_id` が主キーになり、manifest・印の理由・検査の結果・`seed_node`（C-2）の置き場が 1 行で済む。列を足すだけなら `recipe_export.client_token` ＋ 部分 UNIQUE `(client_token, seed)` |
| c | `ux_export_attempt_seed(attempt_id, seed)` で「再送の冪等性」を約束するが、**`seed` が NULL（KSampler の無いグラフ。実データ 3 枚）だと UNIQUE が効かない** | 同じ `attempt_id`・`seed NULL` で **2 行入った** | `CREATE UNIQUE INDEX … ON recipe_export(attempt_id, COALESCE(seed, ''))`（式の索引）か、b の束の表で `attempt_id` を主キーにする |

### A-3 「記録時の判定」と「書き出し時の判定」の混同で、線 2・線 4・§8.1-1 が設計のまま評価できない

- **場所**: §0.5「L1 はキーが必ず変わる」「`approx` ＋ 理由 `text_pinned`」、§0.6「`status` の決め方（記録した時点で出す）」、§3.2 の応答例
  `"reasons": ["text_not_captured", "text_pinned"]`（L1 既定）、§1.2 線 2「`exact + approx = 183`」、線 4「seed を固定して書き出したとき鍵が記録と一致」、
  §8.1-1「印を付けても記録の鍵と一致」。
- **実測**（`.tmp-audit-redo/p7/hash_proto.py`。§4.3 をそのまま 30 行で試作: 保存ノードから遡れる部分グラフ、`SaveImage.filename_prefix` と
  `_meta` を除く、リテラルと結線を分けて記録、キー昇順・空白なし JSON → SHA-256）:
  ```
  {'marker_same': 183, 'l1_no_textgen(same)': 182, 'seed_changes_key': 180, 'l1_changed': 1}
  distinct keys 183 of 183; mean key time ms 0.03
  ```
  1. **印を入れても 183/183 で鍵は不変**（§0.5 の除外は正しい）。seed を変えると 180/180 で変わる（seed 無しの 3 枚は変わりようがない）。
  2. **L1 変換（`TextGenerate` → `StringConcatenate` を外し `CLIPTextEncode.text` をリテラルに）で鍵が変わるのは 1/183**。
     「L1 はキーが必ず変わる」は **`TextGenerate` を持つ画像だけ**の話で、実データの 182 枚では L1 でも鍵は同じ。
  3. したがって**線 4 は mode を書かないと評価できない**（L1 の 1 枚だけ不一致、L2 なら全部一致）。§8.1-1 も同じ。
  4. **`text_pinned` を記録時に付けると**（§3.2 の例）、L1 既定の記録は**全部 `approx`** になり、線 2 の「`exact + approx = 183`」は
     何も守らない（`exact` が常に 0）。また §3.2 の例の `text_not_captured` と `text_pinned` は**両立しない**（§4.2: L1 は `final_prompt` が
     分かるときだけ。分からなければ L2 に落ちる）。
- **直し方**:
  - **記録時の `status` / `reasons` は mode に依存させない**（`missing` / `text_not_captured` / `node_missing` / `unresolved` / `version_differs` /
    `hash_mismatch` / `gpu_differs` だけ）。**`text_pinned` / `llm_nondeterministic` / `manual_step` は書き出し時**（`checked_json` と束の表）。
  - 線 2 の合否を**数で**書く。設計の規則をそのまま当てると、この環境・この版では **`exact` 179 / `approx` 4 / `impossible` 80**
    （`approx` 4 ＝ A-1 の 1 枚 ＋ `final_prompt` が `None` の upscale 3 枚。`count_real.out.txt` の `final_prompt:None: 3`）。
    **`text_not_captured` は「到達部分グラフに `CLIPTextEncode` があるのに文字列が分からないとき」だけ付ける**と決め（テキストを使わないグラフは「欠けていない」）、
    A-1 を直せば **183 / 0 / 80**。環境が変われば `node_missing` 等で動くので「`impossible` ≥ 80、超えた分の理由は `node_missing` か `unresolved`」と書く。
  - 線 4 を **「`mode=rerun_graph` で seed を固定して書き出すと鍵が記録と一致（183/183）。`pin_text` では `TextGenerate` を持つグラフだけ変わり、
    その差の理由が `text_pinned`」** に書き直す。§8.1-1 も mode を書く。
  - **鍵は「グラフだけの純関数」と明記する。** §0.5 の「モデル名（＋`(size, mtime)` が分かれば添える）」は、鍵に環境依存の値を混ぜると
    **結果 PNG から計算した鍵（§0.9 の指標）が書き出しの鍵と絶対に一致しなくなる**。`(size, mtime)` は `env_snapshot` と `hash_mismatch` の材料に留める。

---

## B. 重大

### B-1 監視が拾った結果の画像を登録する「実体のパス」を知る手段が無い（§0.9「新しい画像」、§3.4）

- **実測**: `GET /api/jobs/{id}` の `outputs` は `{"17": {"images": [{"filename": "132800_00001_.png", "subfolder": "ComfyUI\\Anima\\20261010", "type": "output"}]}}`。
  `GET /internal/folder_paths` のキーは `checkpoints` … `vae_approx` の 34 種で **`output` / `temp` は無い**。`/system_stats` にも出力先は無い。
- `store.register()` は `path` / `size` / `mtime_ns` / `sha256` を要求する（`store.py:212`）。**ファイルを開けなければ登録も指標（ssim 等）も出せない。**
- **直し方（推奨は G-1）**: 設定 **`comfyui.output_dir`** を足す。既定値の候補は `/internal/folder_paths` の `checkpoints[1]` が
  `C:\ai\ComfyUI_windows_portable\ComfyUI\output\checkpoints` なので、その**親**を推定して**実在するときだけ**使う（実測でこの環境は当たる）。
  当たらなければ **`GET /view?filename=&subfolder=&type=output` でバイト列を取り寄せて `<data>/results/<sha256>.png` に置く**（控え。参照登録ではなく取込）。
  どちらにしても**登録ルート**（`root` 表）に出力先を足すかを決める（`mark_missing` がルート外の行をどう扱うかが絡む。`store.py:302`）。

### B-2 性能の目標 2 本が、測った値から見て設計のままでは出ない（§7、§0.8、§3.2）

| 口 | 目標 | 実測から見た見込み | 原因 |
| --- | --- | --- | --- |
| `POST /api/recipes/{id}/check` | p95 **500 ms**（初回） | **出ない**（`/object_info` の取得だけで 413〜910 ms。keep-alive でも 414〜435 ms） | §0.8「`/object_info` を 1 回引く（全ノードで引かない）」 |
| `POST /api/assets/{id}/recipe` | p95 **300 ms** | **出ない**（§3.2 が記録時に「`/object_info` の使ったノードの宣言だけ」を取るため同じ費用がかかる） | 同上 |

- **実測**: 全体は 2,394,596 バイト・1,212 ノード。**`/object_info/{class_type}` は 0 ms・0.7〜3 KB**（`KSampler` 3,011 B、`TextGenerate` 2,685 B）。
  グラフの異なり `class_type` は実データで 10 前後（ノード数 10〜19 が 183 枚中 24 枚、10 未満が 159 枚）。
- **直し方**: §0.8 を**逆**にする。**使った `class_type` だけ `/object_info/{class_type}` で引き**（≤ 20 回・合計数十 KB・数 ms）、
  **class_type ごとに 60 秒キャッシュ**。全体の `/object_info` は引かない。これで `check` は初回でも **p95 50 ms 級**になる見込み（見積り）。
  §7 の「未計測」3 行は本報告の数字で埋められる（`/object_info` 全体 2.39 MB・0.41〜0.91 s、`json.loads` 12〜17 ms、`/api/jobs?limit=50` 中央 4.5 ms、
  詳細 1.4 ms、鍵 0.03 ms/グラフ）。

### B-3 監視の既読の鍵と「実行された／キャッシュに当たった」の見分けが、実測の形と合わない（§0.9、§1.3、§3.4）

1. **`last_prompt_id` は UUID で順序が無い。** 一覧は `create_time`（ms）の新しい順（実測 `newest first True`）なので、
   **基準は `baseline_create_time`（ms）**にし、`watcher_state` にもそれを持つ（`last_prompt_id` は表示用に残してよい）。
   同じ ms に 2 件入ることがあるので、**処理済み id の集合**（プロセス内。開始からの件数は数百）で重複を弾く。
2. **`in_progress` / `pending` の job を既読にしない。** 一覧には実行中の job も並ぶ（この版の `status` は `pending` / `in_progress` / `completed` /
   `failed` / `cancelled`。実測で見えたのは後ろ 3 つ）。**`?status=completed`** で引き（効くことを実測）、`failed` / `cancelled` は
   別に引いて**既読にだけ**する。基準を進めるのは「それより古い未完了が無いとき」だけ。
3. **`execution_cached` は 731 件すべてに出る**（当たらない job は `nodes: []`）。「出たらキャッシュ」ではなく、
   **「保存ノードの id が `execution_cached.nodes` に含まれるとき＝新しい画像は出ていない」**と定義する。この履歴ではその job は 0 件、
   同じファイル名が別 job に出た例も 0 件だった（同じ画像の再投入が無かっただけ。P4 の点検では**出力ノード（タガー）がキャッシュに入った実例**があるので、規則は要る）。
   設計は「区別できる」で止まっているので、**規則を書く**。
4. **一覧だけで分かることが多い（E-1）。** 一覧の各行に `outputs_count` / `previewable_outputs_count` と、画像の job には
   `preview_output {filename, subfolder, type, nodeId, mediaType}` が入る（実測）。**タグ付けの job は `outputs_count: 0`** なので
   **詳細を取らずに弾ける**。詳細（`workflow.prompt`・`outputs` 全部）は **`outputs_count > 0` の job だけ** 1 回取る。「2 段」は正しいが、
   2 段目の回数は画像の job の数で済む（731 件中 427）。

### B-4 印の照合の「形」を、Windows の `subfolder` に合わせて書く（§0.7、§4.7.3）

- **実測**: `filename_prefix = "ComfyUI/Anima/20261010/132800"` の出力は `subfolder = "ComfyUI\\Anima\\20261010"`（**バックスラッシュ**）、
  `filename = "132800_00018_.png"`。したがって `repro-r7k2m4/seed-5` の印は **`subfolder = "repro-r7k2m4"`・`filename = "seed-5_00001_.png"`** になり、
  **`<output>/repro-r7k2m4/` というフォルダが書き出しごとに増える**（利用者の出力フォルダに `repro-*` が並ぶ。受け入れるなら manifest と画面に書く）。
- `expected_prefix`（`repro-<attempt_id>/seed-<seed>`）の**前方一致**は、`subfolder.replace("\\", "/") + "/" + filename` に対して行う、と書く。
  `capture.py` の `index_outputs` は逆に `/` → `\\` に寄せている（`capture.py:48`）ので、**どちらかに統一**する。
- 「`filename` または `subfolder` に `repro-<attempt_id>` を含めば」は実測の形で成り立つ（`subfolder` が一致）。PNG の `prompt` チャンクの保険も
  `SaveImage.filename_prefix` がリテラルで残るので成り立つ（`loadApiJson` が値を戻すことを frontend の実装で確認した。E-5）。

### B-5 新しい契約 `recipe-manifest` が、§0.12 で「manifest に出す」と約束した欄を**持てない**（§6.1）

- **実測**（本物の `jsonschema`、Draft 2020-12）: `additionalProperties: false` なので **`mode` を足すと落ちる**（「Additional properties are not allowed」）。
  一方 **`export_hashes: {"x": 123}`・`notes: {}`・`notes` にでたらめ（`status: "banana"`）・`seeds: []` は通る**。
- §0.12 の末尾は「`recipe_id` は ULID で読めない → **manifest と画面に元画像・条件の要約を出す**」、§3.3 は「manifest に `status` / `reasons` を入れる」、
  §4.7.3 は「`notes` に検査の結果」。**どれも契約に型が無い**ので、§8.1-26（契約で固定）は `status` / `reasons` / 要約を守らない。
- **直し方**: `notes` を型つきにする（`{status: enum, reasons: [string], inspected: boolean, instruction: string}`、`required`）。
  **`mode`・`marker_skipped`（`前提1|2|3|null`）・`source`（`{asset_id, sha256, filename, model, seed, size}` の要約）**を足す。
  `export_hashes` は `additionalProperties: {"type": "string", "pattern": "^sha256:"}`、`seeds` は `minItems: 1`（seed 無しの束は G-4 の決めに合わせる）。

### B-6 `seed` の扱い（§0.12「JSON では数値」、§3.3「`seed+1` ずつ」、§10-2）

- **実測**: 実データの seed は 180 件、**最大 50 bit**（733,495,470,076,873）、2^53 を超えるものは 0 → いまの JS の `Number` では壊れない。
  しかし `KSampler.seed` の宣言は `max: 18446744073709551615`（64 bit）で、**API 起点のグラフは 2^53 超があり得る**。manifest は文字列、API は数値、
  と**同じ値を 2 つの型で持つ**のは、画面（素の JS）が `JSON.parse` した瞬間に丸める危険を残す。**API でも文字列**（`seeds: ["1", "2"]`）に揃えるのを勧める。
- `seed+1` ずつ: 当時の seed が `2^64-1` 付近だと `max` を超えて ComfyUI の検証で落ちる。**`(seed + k) mod 2^64`** と書く（1 行）。
- **`control_after_generate` は解決できる（§10-2 は「未確認」で止まっている）。** frontend 1.53.10 の実装: INT ウィジェットで名前が `seed` / `noise_seed` か
  `control_after_generate` が真なら **`addValueControlWidget(…, 'randomize')`**（宣言が文字列のときだけその値）。`KSampler.seed` の宣言は `true` なので
  **読み込み直後は `randomize`**。`Comfy.WidgetControlMode` の既定は **`after`**。→ **1 回目の Queue は書いた seed で走り、Queue のあとで seed が変わる**。
  §5.3 の文言「`control_after_generate` は `fixed` のまま Queue」は**読み込んだ時点で `fixed` ではない**ので誤り。
  **「1 ファイルにつき Queue は 1 回。2 回目を押す前に `fixed` にする（`before` 設定なら 1 回目から変わる）」**に直す。対策 2（結果の seed を読む）はそのまま要る。

---

## C. 中程度

### C-0 確かめた結果、問題なし（1 行ずつ）

- §0.3「`recipe_*` / `preset` / `watcher_state` が現物に無い」: `sqlite_master` の表は 19（`sqlite_sequence` 込み）で **5 表とも無い**。`db.py:33` は `SCHEMA_VERSION = 5`。
- §0.3「v3 の控えから 1 回で v6」: `.backup/pre-p4-20261016-093705/db.sqlite3` は **`user_version = 3`** で存在する。
- §0.7「183 枚で前提 3 つを満たす」: **183/183**（`SaveImage` 1・`PreviewImage` 0・`filename_prefix` リテラル。リンク 0・欠け 0）。
- §0.5「印を入れても鍵が変わらない」: **183/183**（試作）。「`denoise` を含む」: 試作は `KSampler` のリテラル全部を入れるので含む。
- §1.3「`/api/jobs/{id}` が `workflow.prompt`・`outputs`・`execution_status` を返す」: 返す（`extra_data` は `client_id` / `comfy_usage_source` / `create_time` / `extra_pnginfo`。**UI 起点なら `extra_pnginfo` がある**）。
- §1.3「タグ付けの job も並ぶ」: 並ぶ（`outputs = {"2": {"tags": [...]}}`、`outputs_count: 0`）。
- §1.3「`userdata` の口が生きている」: 200 / 409 / 204 / 404 を実測。探りは消した。
- §0.11・§3.5「`review.json` を変えない」をテストで固定できるか: `schemas/review-export.schema.json` は **`additionalProperties: false`**、`properties` は `schema`〜`path_map` の 10 個。`recipes` を足せば本物の `jsonschema` で落ちる。
- §0.10「`actor` は `human` 以外 403」: `api/__init__.py:58 actor_of` が語彙外を 422、`tags.py:26 require_human` が 403。再利用できる。
- §0.10「外部を待たない」: `capture.py` は `/history` を取引の外で取る。`jobs.py` のワーカーは `threading.Thread(daemon=True)`（`jobs.py:195`）。同じ形で監視のスレッドを作れる。
- §2.2 の索引: 6 つの問い合わせが **全部意図した索引**（`ux_recipe_source` / `ux_recipe_token` / `ix_recipe_created` / `ix_export_recipe` / `ix_result_export` / `ux_export_attempt_seed`）を使う（`EXPLAIN QUERY PLAN`）。
- `foreign_keys = ON` は接続ごとに掛かる（`db.py:89`）。`REFERENCES` は飾りではない。
- §0.2「材料はもう在る」: `capture.py` が使う `store.assets()` / `set_meta()` / `save()` は SQLite 版の `Store` にある（`store.py:150/340/116`）。`POST /api/capture`（`app.py:306`）も生きている。
- §0.13「`frontend-design.md` は §4.7〜§4.12 を持っている」: 437〜610 行にある。§3 の 12・13 もある（288〜289 行）。
- `design.md` の行番号: `:39`（R12）・`:521-529`（`preset` の DDL は 522〜529。521 はコメント）・`:555-558`（`recipe_*` / `preset` の 4 行）・`:1449`（P7 の行）・`:1756`（19.4-12 の 2 行目）・§5.5 の `watcher_state`（451〜453）・§6.1 の R12 の口（685〜700）。**すべて合っている**。

### C-1 記録は「画像 1 枚に 1 つ」か「画像×mode に 1 つ」か（§2.1 `ux_recipe_source(source_asset_id, mode)`、§7「263 枚で 263 行」、§0.12 `mode` の上書き）

- DDL は画像ごとに最大 3 行（mode ごと）を許し、§7 は 1 枚 1 行で数え、§0.12 は書き出しの口で mode を上書きできる。**3 つが食い違う**。
  mode が書き出しで選べるなら、記録の mode は「既定のレベル」でしかなく、同じ画像に 3 行作る理由が無い（グラフも鍵も同じ）。
- **推奨**: `ux_recipe_source` を **`source_asset_id` だけ**にし、`recipe_record.mode` は「既定（画面の初期値）」と注記。§3.2 の「既に記録がある」は mode を見ない。G-5。

### C-2 `recipe_export` に「どのノードの seed を書き換えたか」が残らない（§3.3 の応答 `seed_node`、§0.9「seed の確認」）

- 結果の PNG の `KSampler.seed` を比べるとき、複数 `KSampler` のグラフでは**どのノードか**が要る。応答には `seed_node` があるが列が無い。
  実データに複数 `KSampler` は 0 だが、設計が二段構成を想定している以上、**`seed_node TEXT`** を足す（A-2b の束の表に置けばよい）。

### C-3 削除との関係（FK）が決まっていない（§2.1、P8 との依存）

- **実測**: 記録のある `asset` を消すと **`FOREIGN KEY constraint failed`**。`annotation` は `ON DELETE CASCADE`、`preset.source_asset_id` と
  `recipe_export_result.result_asset_id` は何も無い。P8（削除）が来たとき**設計の無い場所で落ちる**。
- **推奨（G-3）**: `preset.source_asset_id … ON DELETE SET NULL`、`recipe_export_result.result_asset_id … ON DELETE SET NULL`、
  `recipe_record.source_asset_id` は既定（RESTRICT）のままで、**P8 の設計に「記録のある画像の削除は記録ごと消すか断るか」を 1 行で申し送る**。

### C-4 合否の「消えない」と「上書き」（§4.2「上書き。履歴は残さない」、`design.md:1449`「消えない形で」、`frontend-design.md` §4.11「記録は消えない形で残る」）

- 上書きなら前の合否は消える。台帳にするほどではないが、**いつ・誰が**は残したい。**推奨（G-2）**: `verdict_at TEXT`・`verdict_actor TEXT` を足して上書き
  （履歴は持たない）。「消えない」＝「再起動や再読込で失われない」と定義し直す。

### C-5 `KSampler` の無いグラフ（実データ 3 枚）の書き出しが未定義（§3.3）

- `illust-authoring/upscale` の 3 枚は `KSampler` も seed も無い。`seeds` / `count` を受けたら **422 `no_sampler`**、何も指定しなければ
  **seed 無しの 1 ファイル**（`graph.json`、印は `repro-<attempt_id>/noseed`）を勧める（G-4）。A-2c の `COALESCE(seed, '')` と組で決める。

### C-6 監視の接続先が設定に無い（線 6 の偽サーバ、`probe_p7.py --watch`）

- `settings` の鍵は `backup_dir` / `export_delay_sec` / `next_after_decision` / `preview_ttl_sec` / `tagger.comfyui_temp` / `tagger.engine` / `tagger.node` /
  `undo_window_sec`。タガーは `tagger.comfyui`（既定 `http://127.0.0.1:8188`。`tagger.py:614`）、`capture` は `payload.base_url`、`gloss` は `DEFAULT_URL`。
  **監視の URL を `comfyui.url`（既定 8188）として 1 つに寄せ、`POST /api/watcher/start {base_url?}` でも受ける**と線 6 が書ける。
  **設定は `start` のたびに読む**（P4-2 の監査 C-1: `gloss.*` はプロセスで 1 回しか読まれず、試験で差し替えられなかった）。

### C-7 `GET /api/recipes` のキーセット（§0.12）に、P4-3 で踏んだ罠の試験を付ける

- `cursor = created_at|id` と `ORDER BY created_at DESC, id DESC` の対応は正しいが、P4-3 の再確認で **`GET /api/tags` の `cursor`（name）と並び（uses DESC）が
  食い違って 2 頁目が重複**した。§8.1 に **「2 頁の重複ゼロ・合計が `limit=1000` と一致」**を足す（F）。

### C-8 記録の口の `graph_source='history'` は P7 では作れない（§0.4、§0.6）

- P7 の記録は「PNG の `prompt` チャンクから読む」だけで、`/history` から捕獲する経路（P3 の救済走査）は P7 に無い。`'history'` / `'sidecar'` は
  **語彙に残してよいが、P7 では `'png'` しか出ない**と書く（線 1 の期待値に影響）。

---

## D. 軽微

- D-1 §0.7・§1.3・§3.2「80 枚はグラフが無い（**JPEG など**）」: 実データは **263 枚すべて `.png`**。80 枚は **`prompt` チャンクの無い PNG**。線 1 の「グラフ無しの 1 枚（JPEG）」は複製に JPEG を 1 枚足して試す（`tests/` は合成でよい）。
- D-2 §1.3「`filename_prefix` は全部リテラル」は正しいが、**172 枚は `__OUTPUT_PREFIX__`**（別ツールが差し込む置き札）。印なしで書き出すとこの名前で保存される。manifest の `notes` と画面に「保存先の名前は `__OUTPUT_PREFIX__` のままです」と 1 行。
- D-3 §2.1 `graph_kind` のコメント「`api+ui` なら `'ui'` も残る」: 1 列に 2 値は入らない。`provenance()` の `graph_format`（`'api'` | `'api+ui'`）をそのまま入れる。
- D-4 §3.1 `GET /api/recipes/{id}/graph?format=api` で `graph_path` が NULL（`impossible`）のときの応答が無い。**422 `details: {graph: "残っていない"}`** を勧める。
- D-5 `png_meta.reachable_from_outputs()` の根は `SaveImage` / `PreviewImage` だけ（`SAVE_TYPES` は定義だけで未使用）。`SaveAnimatedWEBP` 等だけのグラフは「全ノード」に落ちる。実データには無いので D。§0.5 に「根は `SaveImage` / `PreviewImage`」と明記。
- D-6 `/api/jobs` という名前が **image-reviewer 自身の口**（`design.md:587/615`、P4-3 の `#/jobs`）と**ComfyUI の口**の両方を指す。P7 の文書では「**ComfyUI の** `/api/jobs`」と毎回書く。
- D-7 §2.3「`export`（単数、P5）と `exports`（複数、P7）が並ぶ」: 実データの `.data/export/` を確認。混同を避けるなら **`<data>/recipes/<recipe_id>/<attempt_id>/`** の方が読みやすい（任意）。
- D-8 `watcher_state.enabled` は `design.md` §5.5 が `INTEGER`、P7 が `NOT NULL DEFAULT 0`。P7 の方が良い（`design.md` を直す側）。
- D-9 `workflow-reproduction.md` §5 の「紐付け（§4.7.1）…点検で見つかった誤り」の段落が**同じ文面で 2 回**入っている（565〜590 行付近）。P7 の対象外だが、§12-7 の書き換え一覧に足す。
- D-10 §3.2「同じ `client_token` で中身が違う → 409」: `recipe_record` の `client_token` は `(source_asset_id, mode)` と二重に一意なので、トークンが同じで画像が違う再送だけが 409 になる。期待どおりだが、テスト #15 に「同じ token・別の画像 → 409」を足す。
- D-11 §8.1-27 の `Host: evil` / `Content-Type: text/plain` で 403: `app.py:105 local_only` が既にある。新しい `POST` 5 本を列挙しているのは良い。`POST /api/recipes/{id}/presets` と `/results` も足す（7 本）。
- D-12 §12-3 の「誤って紐付く危険」: `attempt_id` が 6 文字（例 `r7k2m4`）だと `subfolder` の**部分一致**で他人の名前に当たり得る。**`subfolder` の正確な一致**を主にし、`attempt_id` は 8 文字以上の `[a-z0-9]` に。

---

## E. `design.md` / 本文とのずれ（§0.15 の一覧に無いもの）

| # | 本文 | `p7-design.md` | 種類 | 行 |
| --- | --- | --- | --- | --- |
| E-1 | — | §1.3「一覧は `id` / `status` / `create_time` / `execution_*` / `outputs_count` だけ」 | **実測と違う**: `priority` / `previewable_outputs_count` と、画像の job には `preview_output {filename, subfolder, type, nodeId, mediaType}` / `workflow_id` もある（B-3-4） | p7 §1.3 |
| E-2 | `design.md:698-699` `POST /api/presets {name, note?, source_asset_id?}` | §3.1 `POST /api/recipes/{id}/presets {name, note?}` | 口の場所と引数が違う。§0.15 に無い。P7 の形（記録から写す）の方が筋が通るので **`design.md` を直す** | p7 §3.1 |
| E-3 | `design.md` §6.1 に無い | `GET /api/watcher`、`POST /api/watcher/start` / `/stop`、`POST …/exports/{attempt_id}/results` | 追加の口。§0.15 #5 は `results` だけ。**watcher の 3 口も §0.15 に足す**（§12-7 には書いてある） | p7 §3.1・§3.4 |
| E-4 | `design.md:1449`「監視での結果取り込み」 | §0.2 (a) | 一致（§0.15 #1 で説明済み） | — |
| E-5 | `workflow-reproduction.md` §4.7.1「`loadApiJson` の復元は未確認」、§10-2「`control_after_generate` 未確認」 | 同じく未確認 | **確認できた**（B-6）: 値は戻る・既定は `randomize`・mode は `after` | p7 §10-2 |
| E-6 | `workflow-reproduction.md` §4.7.1「保険: PNG の `prompt` チャンク」 | §0.7 で採用 | 実測で成り立つ（`SaveImage.filename_prefix` は `prompt` に入る。実データで 183/183 読めた） | — |
| E-7 | `workflow-reproduction.md` §4.7 手順 4 `unresolved` = 不可（書き出さない） | §3.2 `unresolved` = `approx`（`frontend-design.md` §4.7 も近似の文言） | **`unresolved` の重さが文書間で違う**（A-1・G-7）。P7 で 1 つに決める | p7 §3.2 |
| E-8 | §7 の「未計測」3 行 | — | 本報告で計測済み（B-2 の表）。§7 を書き換えられる | p7 §7 |
| E-9 | §0.9「`execution_cached` の見分け」 | — | 「出る／出ない」では見分けられない（B-3-3） | p7 §0.9・§1.3 |
| E-10 | `design.md` §5.5 `watcher_state`（`enabled INTEGER`） | `NOT NULL DEFAULT 0` ＋ `updated_at` | 追加（§0.15 #7 に `updated_at` も書く） | — |
| E-11 | `design.md` §19.3-10「登録ルート外を触らない」 | §0.9「新しい画像を `asset` として登録」 | **出力先がルートでないときの扱いが無い**（B-1・G-1） | p7 §0.9 |

---

## F. テストで守れないもの（§8 の「壊すと落ちる」を読んだ結果）

| テスト | 判定 | 根拠と直し方 |
| --- | --- | --- |
| §8.1-1 印と鍵 | **mode を書かないと空振り** | L1 既定だと `TextGenerate` 入りのグラフで落ちる（意図した差）。`rerun_graph` で比べる、または「L1 変換後のグラフの鍵と比べる」と書く（A-3）。合成グラフは **`TextGenerate` 入り**を 1 つ含める（実データの 182/183 は無いので、無いグラフだけだと L1 の分岐を通らない） |
| §8.1-4 理由の語彙 | 記録時と書き出し時を分けないと `text_pinned` の置き場で矛盾する | A-3 のとおり分ける。`text_not_captured` と `text_pinned` が同時に出ないことも固定 |
| §8.1-11〜13 検査 | **12 が A-1 で誤って落ちる方向** | 12 を「動的コンボの入れ子名は宣言に含まれる」に書き直し、別に「本当に無いキー（`KSampler.foo`）は `unresolved`」を置く。フィクスチャの `/object_info` は **実物から `KSampler` / `SaveImage` / `TextGenerate` / `CLIPTextEncode` / `UNETLoader` の 5 ノード分を写す**（`/object_info/{ct}` で 0.7〜3 KB） |
| §8.1-14 `GET` が書かない | 守れる | 複製フォルダの一覧（名前・mtime・size）と `recipe_*` の行数を前後で比べる。`GET /api/recipes/{id}/graph` も入れる（D-4 の作り直し禁止） |
| §8.1-16 書き出しの再送 | **列が無いので書けない**（A-2b） | 束の表か `client_token` 列を足してから |
| §8.1-18 画像を出さない job | 守れる | 詳細を取らない設計（B-3-4）なら、**一覧の `outputs_count: 0` で弾く**ことを固定（偽サーバは `outputs_count` を返す） |
| §8.1-20 既読 | **UUID の `last_prompt_id` では書けない**（B-3-1） | `create_time` 基準＋処理済み集合。偽サーバに **`in_progress` の job を 1 件混ぜ**、既読が進まないことを固定 |
| §8.1-21 再起動 | 守れる | `Store` を閉じて開き直し、`enabled` が 0 |
| §8.1-24 移行 | 守れる | `tests/test_db.py:204/235` の形（v1 → 最新、3 回）に v6 を足す。**v5 の複製**（`.tmp-audit-redo/p7/srv`）と **v3 の控え**（`.backup/pre-p4-…`）でも通す |
| §8.1-25 `review.json` に足さない | 守れる | 契約が `additionalProperties: false` なので足すと落ちる。「`assets[]` の中に `recipe` を足す」も落ちるか（`Asset` の定義が `additionalProperties: false` か）を 1 行確かめる |
| §8.1-26 manifest | **`status` / `reasons` / 要約を守らない**（B-5） | `notes` を型つきに。`export_hashes` の値も `sha256:` で縛る |
| §8.1-30 seed の確認 | 守れる | 合成 PNG の `prompt` に別の seed を入れる。**`seed_node` が要る**（C-2） |
| 追加 | `GET /api/recipes` の 2 頁 | 重複ゼロ・合計一致（C-7） |
| 追加 | 線 6 を本物の PNG で | 偽サーバの `outputs` が指す **実ファイル**（合成 PNG。`prompt` に印つきの `filename_prefix`）を `comfyui.output_dir` に置き、**登録・鍵・指標・`seed_changed`** まで通す（B-1・線 9 の代わり。G-6） |
| 追加 | `COALESCE(seed,'')` の一意性 | 同じ `attempt_id`・seed 無しで 2 回書き出して 1 行（A-2c） |

---

## G. 依頼者への質問（推奨つき。**待たずに推奨で進めてよい**）

| # | 論点 | 選択肢 | 推奨 |
| --- | --- | --- | --- |
| G-1 | 結果の画像の**実体パス**（B-1） | (a) 設定 `comfyui.output_dir`（既定は `/internal/folder_paths` の `checkpoints[1]` の親を推定し、実在するときだけ）＋ 監視の開始時にその場所を**登録ルートに足す**（1 回だけ利用者に確認） / (b) `GET /view` で取り寄せて `<data>/results/` に**取込**（参照ではなく複製。ルートの問題は消えるが二重に持つ） / (c) 毎回利用者に聞く | **(a)**。当たらなければ (b) に落ちて画面に 1 行。この環境では (a) の推定が当たる（`C:\ai\ComfyUI_windows_portable\ComfyUI\output`） |
| G-2 | 合否の履歴（C-4） | (a) 上書き＋`verdict_at` / `verdict_actor` / (b) 台帳（`decision` と同じ形） | **(a)**。合否は 1 枚に 1 つで足りる。「消えない」は「再読込で失われない」と定義 |
| G-3 | 削除との関係（C-3） | (a) `preset` / `result` は `SET NULL`、`recipe_record` は RESTRICT で P8 に申し送る / (b) 全部 CASCADE / (c) 全部 RESTRICT | **(a)**。条件の記録は R12 の目的物なので元画像と一緒に黙って消さない |
| G-4 | `KSampler` の無いグラフ（C-5。実データ 3 枚） | (a) `seeds` / `count` は 422 `no_sampler`、無指定なら seed 無し 1 ファイル（印 `…/noseed`）/ (b) 書き出し自体を 409 | **(a)**。upscale のグラフも「同じ条件で開く」用途がある |
| G-5 | 記録の一意性（C-1） | (a) 画像 1 枚に 1 記録（mode は既定値）/ (b) 画像×mode | **(a)**。§7 の数え方・§0.12 の上書きと整合する |
| G-6 | 線 9（利用者の 1 回の生成） | (a) **任意の確認**に格下げし、合格の門は「線 6 を本物の PNG で」（F の追加）にする / (b) 線 9 を門のまま残す | **(a)**。frontend の復元（`filename_prefix`・seed の既定）と出力の形（`subfolder` 分割）は本報告で裏が取れたので、残る未知は「ComfyUI が実際に `repro-<id>/seed-<seed>_00001_.png` を書く」ことだけ。利用者が 1 回回したら §J として追記する |
| G-7 | `unresolved` の重さ（A-1・E-7） | (a) モデルが combo に無い → `impossible`、入力キーの差 → `approx`＋キー名 / (b) どちらも `impossible` / (c) どちらも `approx` | **(a)** |

---

## H. 確かめられなかったこと・注記・後始末

**確かめていない（実行していない）**

- `gui_layout.mjs`（新しい画面がまだ無い）。
- **画像の生成**（禁止）。したがって **線 9 と「ComfyUI が印どおりのフォルダに書く」**は未確認（過去の `/history` 157 件の `/` 入り prefix が `subfolder` に分かれる事実からの推定）。
- `POST /api/assets/{id}/recipe` 等の**実装の性能**（実装が無い）。B-2 は口の費用の実測からの見積り。
- `temp` の画像の寿命（§10-3）。
- `in_progress` / `pending` の job が一覧にどう出るか（点検中に実行中の job が無かった。ComfyUI 0.39 の `status` の語彙は実装の列挙からの推定）。
- frontend の seed の**上限の丸め**（2^50 でクランプする実装があると記憶しているが、本体の JS で定数が見つからなかった。B-6 は実データの最大 50 bit だけを根拠にしている）。
- `/internal/folder_paths` が将来 `output` を返すか（0.39.2 では返さない）。

**紛らわしい出力の注記**

- `count_real.out.txt` の `note:prompt �`…` の行は cp932 の表示化けで、中身は「prompt チャンクが無い（生成条件が残っていない画像）」80 件。
- `check_env.out.txt` の `combo�l�ɖ��� []` も同じ化け（「combo 値に無い []」）。
- `history_scan.py` の `cached_nonempty_with_images: 426` は「**上流が**キャッシュに当たった job」で、保存ノードは全件再実行されている（`jobs whose SaveImage node was cached: 0`）。

**実行したコマンドと結果（再現手順）**

```powershell
cd C:\work\image-reviwer; $env:UV_CACHE_DIR = "C:\work\image-reviwer\.uv-cache"
uv run --no-sync pytest -q                                  # 285 passed, 1 warning in 12.99s
node tools/gui_smoke.mjs                                    # すべて ok（ok の行 129）
# 複製（WAL を畳む）
.venv\Scripts\python.exe -c "import sqlite3; s=sqlite3.connect('file:.data/db.sqlite3?mode=ro',uri=True); d=sqlite3.connect('.tmp-audit-redo/p7/srv/db.sqlite3'); s.backup(d)"
.venv\Scripts\python.exe .tmp-audit-redo\p7\count_real.py   # 183 枚の前提 / KSampler / prefix の分布（上の表）
.venv\Scripts\python.exe .tmp-audit-redo\p7\hash_proto.py   # marker_same 183, l1_changed 1, seed_changes_key 180, distinct 183
curl -s -o .tmp-audit-redo\p7\object_info.json -w "%{size_download} %{time_total}" http://127.0.0.1:8188/object_info   # 2394596 0.52
curl -s -o .tmp-audit-redo\p7\history.json     -w "%{size_download} %{time_total}" http://127.0.0.1:8188/history       # 4882254 0.10
.venv\Scripts\python.exe .tmp-audit-redo\p7\check_env.py    # ok 182 / unresolved:key 1（TextGenerate.sampling_mode.*）
.venv\Scripts\python.exe .tmp-audit-redo\p7\history_scan.py # 731 件の内訳・execution_cached・subfolder の形
# ComfyUI の口の費用（毎回接続 / keep-alive）と全 731 件の分類は本文のインライン script（object_info 5 回・jobs 10 回・詳細 1 回）
# userdata の探り: POST /api/userdata/workflows%2Fimage-reviewer-probe-<ts>.json?overwrite=false → 200、再送 409、DELETE → 204、GET → 404
# DDL の試行: docs/p7-design.md §2.1 の sql ブロックを複製へ 2 回 executescript → 24 表・integrity ok・EXPLAIN 6 本・NULL seed 2 行・marker NULL は NOT NULL で失敗・asset 削除は FK で失敗
# 契約: §6.1 を .tmp-audit-redo\p7\recipe-manifest.schema.json に抜き、uv run --no-sync --with jsonschema で check_schema と 8 件の文書を検証
```

**後始末**

- 残した物: `.tmp-audit-redo/p7/`（複製 `srv/db.sqlite3` 1.1 MB、`ddl-trial.sqlite3` 1.2 MB、`object_info.json` 2.4 MB、`history.json` 4.9 MB、スクリプト 4 本と出力、契約 1 本）。消してよい。
- 消した物: ComfyUI の `userdata/workflows/image-reviewer-probe-1792137522.json`（置いて 1 秒以内に消し、`GET` が 404 になることを確認）。
- 立てていない物: image-reviewer のサーバ（ポート 8791 は使っていない）。ComfyUI の `temp/` にも何も足していない。
- `.data/` の mtime は不変（`db.sqlite3` 10-15 14:29:51、`-wal` 10-16 15:08:35）。`src/` に点検中の変更は無い（最新は `tagger.py` 13:45）。

---

## I. 指示書 §1 の 12 項目と設計 §12 の 7 問への答え（要約）

| 指示書 §1 | 答え |
| --- | --- |
| 1 §0 の差分（0.2 / 0.5 / 0.7 / 0.9 / 0.15） | 0.2 **妥当**（P3 に残す線引きも妥当。`capture.py` の材料は本当にある）。0.5 **妥当だが「必ず変わる」は 1/183**（A-3。線 2 の内訳は設計の規則どおりなら 179 / 4 / 80、直せば 183 / 0 / 80）、鍵は純関数に。0.7 **183/183 で成り立つ**（D-2 の置き札に注意）。0.9 **2 段は要るが一覧で絞れる**、既読の鍵と cached の規則を直す（B-3）。0.15 は E-1〜E-3・E-10 が抜けている |
| 2 合格の線 10 本 | 1・3・5・6・7・8・10 は**打てる形**。**2 と 4 は A-3 のとおり書き直し**。**9 は G-6（任意に格下げし、線 6 を本物の PNG で）** |
| 3 v6 の 5 表 | 索引は全部効く（実測）。**`marker NOT NULL`・`client_token` 列無し・NULL seed の一意性**を直す（A-2）。FK の `ON DELETE` を決める（C-3）。`updated_at` は妥当 |
| 4 13 の口 | `GET` は書かない設計で良い（D-4 の作り直し禁止を含め）。`actor` は人だけで妥当。`client_token` は書き出しに**列が無い**（A-2b）。監視の開始は `watcher_state` を書いてスレッドを起こすだけなので投げてすぐ返る |
| 5 §4 の状態 | `verdict` の上書きに `verdict_at` / `verdict_actor`（C-4）。`mode` の上書きは C-1 と組で。`matched_by` / `seed_changed` は妥当（`seed_node` を足す。C-2） |
| 6 契約 | `review.json` を変えない判断は**妥当**で、テストで固定できる（契約が `additionalProperties: false`）。`recipe-manifest` は **B-5** |
| 7 性能 | `/object_info` を計測した。**目標 2 本は設計のままでは出ない**（B-2）。`/object_info/{class_type}` に変えれば出る見込み |
| 8 テスト | F の表。1・12・16・20・26 が設計のままでは守らない |
| 9 気づいていない前提 | **動的コンボの入れ子名**（A-1）、**結果の実体パス**（B-1）、**`execution_cached` が全件に出る**（B-3）、**`subfolder` のバックスラッシュ**（B-4）、**`randomize` が既定**（B-6）、**`__OUTPUT_PREFIX__`**（D-2）、**KSampler 無し 3 枚**（C-5）。§10 の 15 件に無いのはこの 7 つ |
| 10 工程 | P7-0 は機能を足さない形で良い。**A-2 の DDL の直しは P7-0 に入れる**。P7-3 の監査の単位に「結果の実体パス」「`in_progress` を既読にしない」「保存ノードが cached の job」を足す |
| 11 Q1〜Q6 | 本文と食い違いなし（Q2 の保険は E-6 で裏取り。Q4 は A-3 の「鍵は純関数」と整合） |
| 12 §12 の 7 問 | 下の表 |

| 設計 §12 | 答え |
| --- | --- |
| 1 P3 との依存 | 妥当。線引きも妥当。ただし P7 の監視が「新しい画像を登録する」には B-1 が要る |
| 2 再現キー | 除外・包含は §4.3 どおりで、**試作で 183/183 印不変・180/180 seed 感応・異なり 183**。`(size, mtime)` は鍵に入れない（A-3） |
| 3 印の前提と認定 | 実装できる。誤って紐付く危険は D-12（`subfolder` の正確な一致を主に、`attempt_id` は 8 文字以上） |
| 4 監視の最小形 | §5・§5.1・§6-11 と食い違いなし。**開始時に遡らない**判断は妥当（救済は P3）。既読の鍵は `create_time` に（B-3） |
| 5 壊すと落ちるか | F の表 |
| 6 気づいていない前提 | 上の 9 |
| 7 `design.md` を書き換える箇所 | 一覧に **`POST /api/presets` の形（E-2）・watcher の 3 口（E-3）・§5.5 の `enabled NOT NULL DEFAULT 0`・束の表か `recipe_export.client_token` / `seed_node` / `marker` NULL 可・`workflow-reproduction.md` §4.5 と §4.7 の `unresolved` の統一・同 §5 の重複段落（D-9）**を足す |

---

## 最も重大な 3 件（再掲）

1. **A-1** 検査 ③ が `TextGenerate.sampling_mode.*`（`COMFY_DYNAMICCOMBO_V3` の入れ子名）を「宣言に無いキー」と誤判定し、利用者の ja2en の画像（実データで唯一の `TextGenerate` 入り）を `unresolved` で止める。動的コンボを展開する。
2. **A-3** 記録時と書き出し時の理由を分けていないため、線 2（内訳）と線 4（鍵の一致）が評価できない。L1 で鍵が変わるのは 183 枚中 1 枚。鍵はグラフだけの純関数に。
3. **B-1** 結果の画像の実体パスを知る口が ComfyUI に無い（`/internal/folder_paths` に `output` が無い）。設定 `comfyui.output_dir` と登録ルートの扱いを決める。

（A-2 の DDL 3 点は機械的だが**必ず直す**。B-2 の `/object_info` は `/{class_type}` に変えれば目標が出る見込み。）
