# P7 の設計（条件の記録。R12）

- 対象: `C:\work\image-reviwer`（Python + FastAPI + SQLite + numpy + Pillow + 素の JS の GUI）
- 位置づけ: [`design.md`](design.md) §14 の **P7（条件の記録）**の設計。**この段の正はこの文書**で、
  本文と食い違うときは **§0 が正**。
- 前提: **P5（判断と比較）・P6（要求と注記）・P4（タグと語釈）は完了**（`db.py` は `SCHEMA_VERSION = 5`）。
  専門の設計は [`workflow-reproduction.md`](workflow-reproduction.md)（**§4.3 再現キー・§4.5 判定・§4.7.1 印・
  §4.7.2 seed 違い・§4.9 表・§4.10 プリセット・§5 監視**が正）。
- 言語: 日本語。要件は [`design.md`](design.md) §1 の **R12**（`design.md:39`）。

---

## 0. 拘束力のある差分（この段で決めたこと）

`design.md` の本文と食い違う点、および本文が黙っている点。**実装はここに従う。**

### 0.1 段の分け方と合格の線

| 段 | 内容 | 合格の線 |
| --- | --- | --- |
| **P7-0** | **機能を足さない。** v6 の移行（`recipe_record` / `recipe_export` / `recipe_export_result` / `preset` / `watcher_state`）、
`schemas/recipe-manifest.schema.json` の新設、`review.json` は**変えない**ことの確認 | 既存のテストが緑のまま。**v5 の DB から 1 回で v6** に上がり、**何度呼んでも同じ**。v3 の実データからも 1 回で v6 |
| **P7-1** | **記録と判定**（`recipe_hash`・`record_json`・`env_snapshot`・`status` と `reasons`・グラフの置き場）、`GET/POST /api/assets/{id}/recipe`、`GET /api/recipes` | §1.2 の線 1・2（**R12 の前半**） |
| **P7-2** | **書き出し**（L1/L2/L3・書き出す前の検査・印・seed 違い・manifest）、`POST /api/recipes/{id}/check` / `/export`、`GET /api/recipes/{id}/exports` | §1.2 の線 3・4・5 |
| **P7-3** | **監視の最小形と結果の紐付け**（`/api/jobs` → `/api/jobs/{id}`・印の照合・`matched_by`・指標・環境の写し・sidecar）、合否の記録 | §1.2 の線 6・7（**R12 の後半**） |
| **P7-4** | **画面**（`#/asset/<id>/recipe` と `#/recipes`。`frontend-design.md` §4.7〜§4.12 のとおり） | §1.2 の線 8 と、`gui_smoke` / `gui_layout` の合格 |

- **合格の線は P7-4 まで**。`design.md:1449` の完了条件が「条件が記録され、判定と理由が出る」「印つきのグラフを
  書き出せる」「**書き出した印から結果の画像が紐付き**、人が合否を記録できる」の 3 つを含むため、
  P5 のように後半を外さない。
- **Fable の監査は段ごと**に頼む（5 回）。各段で「実行して確かめた記録」を出す。

### 0.2 **P3 との依存をどう扱うか（この段でいちばん重い決定）**

**現物で確かめたこと**（§1.3 に実行と結果）: **P2（取り込みとカタログ）と P3（メタデータ）は未完了**で、
とくに **P3 の「グラフの書き出しと ComfyUI への設置」（3-2）と「ComfyUI 監視」（3-4）が無い**。
一方 **P3 の一部は既にある**: `png_meta.py` の `provenance()` / `analyze_graph()`（グラフ解析・`final_prompt`・
`primary_ksampler`・`graph_format`）と、`capture.py` の `capture_history()`（`/history` の走査・
**テキスト出力の由来判定**・`final_prompt` の再構成・sidecar 書き出し。`POST /api/capture` から呼べる）。

| 案 | 内容 | 判定 |
| --- | --- | --- |
| **(a)** | **P7 に監視の最小形も入れる**（`/api/jobs` → `/api/jobs/{id}` の 2 秒ポーリング・印の照合・結果の登録・合否）。P3 には `userdata` への設置・`#/ingest`・起動時の救済走査を残す | **採用（推奨）** |
| (b) | 監視は P3 に残し、P7 は「印つきの書き出し」＋「手で貼る/API で受ける」まで | 却下 |
| (c) | 先に P3 をやる | 却下 |

**採用の理由**:
1. **R12 の完了条件が監視に依存している。** 「書き出した印から結果の画像が紐付く」は、印の経路
   （`matched_by='marker'`）でしか満たせない。英訳は**実行の瞬間にしか存在しない**
   （`workflow-reproduction.md` §2.1）ので、`/history` を後から見るだけでは取りこぼす。
2. **材料はもう在る。** 難しい部分（由来判定・`final_prompt` の再構成・sidecar・グラフ解析）は `capture.py` と
   `png_meta.py` に実装済み。監視は**薄い層**（2 秒ごとに一覧 → 新しい id を 1 件ずつ詳細取得）で足りる。
   詳細の形は**実行で確認済み**（§1.3）。
3. **P3 の残りは P7 の完了条件に入っていない。** `userdata` への設置（`#/asset/<id>` の「ComfyUI で開く」）・
   `#/ingest`・起動時の救済走査は P3 の担当のまま残す。P7 は **API 形式の JSON をフォルダに書いて
   ドラッグ&ドロップを案内するところまで**（`workflow-reproduction.md` §4.7 手順 8 がそう書いている）。
   `POST /api/userdata/workflows%2F<名前>.json` が**生きていることは実行で確認した**（§1.3）ので、P3 で 1 機能として足せる。
4. **「監視は必要なときだけ手で開始」**（`workflow-reproduction.md` §5.1・§6-11）を守る。常駐させない・
   開始中だけ新しい画像を登録する、は P3 の本来の姿と同じなので、P7 で作った監視を P3 が拡張できる。

> **P3 に残すもの（P7 では作らない）**: `POST /api/userdata` への設置と「ComfyUI で開く」導線、
> `#/ingest`（走査の設定と進行）、起動時の `/history` 救済走査（既に登録済みの画像の値だけを埋める）、
> 訳し直し（`TextGenerate` の再実行）。

### 0.3 表は **v6** で足す（現物に 5 つの表が無い）

- 現物の `db.py:33` は **`SCHEMA_VERSION = 5`**。表は 19 個（`settings` / `root` / `reason_code` / `review_group` /
  `asset` / `asset_location` / `asset_meta` / `location_history` / `group_item` / `decision` / `comparison_cache` /
  `review_request` / `annotation` / `tag` / `asset_tag` / `tag_gloss` / `job` / `job_item` ＋ `sqlite_sequence`）。
  **`recipe_record` / `recipe_export` / `recipe_export_result` / `preset` / `watcher_state` は 1 つも無い**（実測）。
- **`watcher_state` は `design.md` §5.5 に DDL があるが、現物には無い**（P1 のプロトタイプで使っていない）。
  **P7 で作る**（監視の既読位置。P3 が拡張しても同じ表を使う）。
- `preset` は `design.md:521-529` に DDL がある（**本文が正**）。§4.10 の定義と一致することを確かめた。
- 実データ `.data` はいま **v5**（263 枚・判断 3 件）。**v3 の控え**（`.backup/pre-p4-20261016-093705`）からも
  1 回の `migrate()` で v6 に上がることをテストで固定する（P6-0・P4-0 の監査と同じ観点）。

### 0.4 グラフの実体をどこに置くか（本文は `graph_path` としか書いていない）

`recipe_record.graph_path` は `<data>/workflows/<sha256>.json`（`workflow-reproduction.md` §4.9）。
**現物には `<data>/workflows/` が無く、グラフはどこにも保存されていない**（`asset_meta.meta_json` には
解析結果だけが入り、**グラフそのものは入っていない**。実測: `meta_json` のキーに `graph` は無い）。

決め:
- **記録を作るときに PNG の `prompt` チャンクから読み、`<data>/workflows/<sha256>.json` に書く**（原子性は
  `export.py` の `_atomic_write` と同じ形。一時ファイル → `os.replace`。起動時に `*.tmp` を掃除）。
- **同じ画像から何度作っても同じファイル**（`sha256` が名前なので増えない）。**PNG から作り直せる**ので、
  失っても記録は壊れない（`graph_path` が指すファイルが無ければ**その場で作り直す**）。
- `/history` から捕獲したグラフ（PNG に `prompt` が無い画像）も**同じ場所に書く**。この場合
  `record_json.graph_source = 'history'` として出所を残す（本文は「取れなかった項目は null で明示」とだけ書く）。
- **JPEG などグラフが無い画像**は `graph_path = null`・`status = 'impossible'`・`reasons = ['missing']`。

### 0.5 再現キー（`recipe_hash`）は `workflow-reproduction.md` §4.3 をそのまま実装する

**発明しない。** 決めたことの要約（実装は §4.3 が正）:
- 対象は **API 形式グラフの生成に寄与する部分グラフ**（`SaveImage` / `PreviewImage` から**遡って到達できるノード**。
  `png_meta.reachable_from_outputs()` が既にある）。
- **除外**: `filename_prefix`（**印を入れても鍵が変わらないため。必須**）・`_meta`・保存/プレビューだけに効く入力・
  カタログ/判断/時刻/パス/まとまり所属。
- **含める**: `class_type`・リテラルの `inputs`・**結線**（どのノードの何番目の出力がどこへ）・モデル名
  （＋`(size, mtime)` が分かれば添える）・LoRA と重み・VAE・CLIP/TE・sampler/scheduler/steps/cfg/**denoise**/seed/解像度・
  リテラルのプロンプト・`TextGenerate` の全パラメータ・`init_image` のハッシュと `strength`。
- 正規化: **キー昇順・空白なしの JSON → SHA-256 → `sha256:` を付ける**。
- **L1 はキーが必ず変わる**（翻訳の枝を外すため）。だから L1 の書き出しは `exact` ではなく
  **`approx` ＋ 理由 `text_pinned`** とし、**記録の鍵と書き出しの鍵を別々に持つ**（`recipe_export.recipe_hash`）。

### 0.6 判定（`exact` / `approx` / `impossible`）と理由の語彙

`workflow-reproduction.md` §4.5 の表を**そのまま**使う（`status` 3 語 ＋ `reasons[].kind` 11 語）。
この段で足すのは 1 つだけ:

- **`graph_source`**（`record_json` の中。`'png'` | `'history'` | `'sidecar'`）。本文は「取れなかった項目は null」と
  書くだけなので、**どこから取れたか**を残す（後から「なぜこれは近似なのか」を辿れるように）。

`status` の決め方（**書き出す前**ではなく**記録した時点**で出す。書き出しの口でもう一度評価する）:
`impossible` ⊃ {グラフが無い, 必須のノード/モデルが今の環境に無い} / `approx` ⊃ {理由が 1 つ以上ある} /
`exact` ⊃ {理由が 0 件}。

### 0.7 印（marker）の前提と「印あり」の認定（本文の §4.7.1 を確定する）

- **前提 3 つ**（§4.7.1 の表）を**そのまま**実装し、1 つでも外れたら**印を付けない**。外れた理由
  （`前提 1` / `前提 2` / `前提 3`）は `recipe_export` に残す（本文は「記録に残す」とだけ書く。
  **列を足す**: `marker_skip_reason TEXT`）。
- **「印あり」の認定（本文 §8-2 の未決定）**: **前方一致で認める**。
  `outputs[].images[].filename` または `subfolder` に **`repro-<attempt_id>`** を含めば `matched_by='marker'`。
  加えて **PNG の `prompt` チャンクの `SaveImage.filename_prefix` が `repro-<attempt_id>/seed-<seed>` で
  始まれば**、ファイル名を変えられていても `marker` と認める（本文の「保険」を採用）。
  連番の桁数・接尾辞は**期待値にしない**（前方一致。§4.7.3）。
- **実データでの裏取り**: 263 枚のうち **183 枚が前提 3 つを満たす**（`SaveImage` が 1 個・
  `filename_prefix` は全部リテラル）。**80 枚はグラフが無い**（JPEG など）ので印を付けられない。§1.3 に実測。

### 0.8 書き出す前の検査（本文 §4.7 手順 4 をそのまま）

`GET /object_info` を 1 回引き、**① 全 `class_type` が在るか ② モデル/LoRA/VAE がそのノードの combo 値に
含まれるか ③ 各ノードの `inputs` のキーが `input.required` / `input.optional` のキーに含まれるか**を見る。
（**入力名→フォルダの対応表を自前で持たない**ため。本文の「点検で見つかった誤り」を反映した形。）
- **`/object_info` の取得は 1 回だけ**（グラフの全ノードで引かない）。**結果は 60 秒キャッシュ**してよい
  （同じ書き出しを連続で検査するとき）。**キャッシュの有無を `check` の応答に出す**（測り方の透明性）。
- **ComfyUI につながらないときは `impossible` にしない**（書き出しはできる）。`status='approx'` ＋
  `reasons=['unresolved']`？**いや、繋がらないのは「今の環境で開けるか」が分からないだけ**なので、
  **検査をスキップして `check.inspected=false` を返し、画面に「今の環境では確かめられませんでした」と出す**
  （黙って通さない・黙って止めない）。

### 0.9 監視の最小形（P7-3。本文 §5 の部分集合を、P7 の範囲として確定する）

| 何 | 決め |
| --- | --- |
| 起動 | **人が明示的に開始/停止**（`POST /api/watcher/start` / `/stop`。**常駐しない**。本文 §5.1・§6-11） |
| 間隔 | **2 秒**（本文 §5）。ポーリングは `GET /api/jobs?limit=50&offset=0`（**新しい順**） |
| 拾う単位 | 一覧に**新しい `id`** があれば `GET /api/jobs/{id}` を 1 回（本文 §2-3 の主経路。**実行で形を確認した**） |
| 開始時の基準 | **開始した時点の最新を基準**にして、**過去は遡らない**（過去の救済は P3 の仕事。§0.2）。`watcher_state.last_prompt_id` に最後に処理した id を入れる |
| 対象の絞り込み | **画像を出す job だけ**を扱う（`outputs` に `images` を持つノードがある）。**タグ付けと語釈の job も `/api/jobs` に並ぶ**のを実測で確認した（§1.3）ので、`outputs` の形で弾く。弾いた job も**既読にはする**（毎回見直さない） |
| 取り込むもの | ① `TextGenerate` の出力（**由来を結線で確かめる**。§5 の 3 手順。`capture.py` の実装を使う）② `final_prompt` の**再構成** ③ 環境の写し（`/system_stats`・`/api/customnode/installed`・モデルの `size`/`mtime`）④ sidecar |
| 新しい画像 | **監視中だけ** `asset` として登録する（本文 §5・§6-11）。ハッシュは内容なので二重登録にならない |
| 印の照合 | `outputs[].images[]` の `filename` / `subfolder` を見て `matched_by='marker'` で `recipe_export_result` を作る。印が無ければ**作らない**（候補として残す＝画面で手で紐付ける） |
| 指標 | 紐付けた結果の PNG から**再現キーを計算**して書き出しの鍵と比べ、`comparison.py` の指標（`ssim` / `phash_distance` / `changed_fraction` / `mean_abs`）を**同じ実装で**入れる（`comparison.md` §4 が定義の正） |
| seed の確認 | 結果の PNG の `KSampler.seed` を読み、書き出しの seed と違えば `seed_changed` として出す（§4.7.2 の 2 の対策） |
| 失敗の扱い | ComfyUI につながらない・job の詳細が取れない → **その回を飛ばして次の周期で再試行**（既読にしない）。`watcher_state` にエラーを残さない（帯を出さない） |
| 生成 | **しない**（§6-1）。この段でも `/prompt` に**画像生成のグラフを投げない** |

### 0.10 `GET` は書かない・`actor`・`client_token`・原子性（前の段の教訓を最初から入れる）

| 論点 | 決め | 根拠 |
| --- | --- | --- |
| `GET` の副作用 | **`GET` は 1 バイトも書かない。** 記録を作るのは `POST /api/assets/{id}/recipe`、書き出すのは `POST .../export`、紐付けるのは `POST`。**グラフの作り直し（`graph_path` が無いとき）だけは例外**にしたいが、**書き込みを伴うので `GET` では作り直さず**、**無ければ `graph_path: null` として出し、記録の口（`POST`）で作り直す** | P5 の監査 C8/G2、P6 の §0.6、P4 の §0.10 |
| `actor` | **記録・書き出し・紐付け・合否は人だけ**（`human` 以外 403。`require_human()` を再利用）。**監視の開始/停止も人だけ**（GPU とディスクを使う） | P4 の §0.14 Q3（検査は 1 か所）、P6 の §3.1 |
| `client_token` | **記録の口に付ける**（再送で行を増やさない。同じ `source_asset_id` ＋ 同じ `mode` なら 200 で既存を返す）。**書き出しの口にも付ける**（`attempt_id` を鍵にする＝同じ `client_token` の再送は**同じ `attempt_id`** を返す） | P6 の §0.9。`attempt_id` は元々「書き出しごとに発行する短い id」なので、再送で増やさない方が良い |
| 原子性 | 書き出しは**フォルダを丸ごと**作る（`<data>/exports/<recipe_id>/<attempt_id>/` に `seed-*.json` と `manifest.json`）。**一時ファイル → `os.replace`**。途中で落ちたら**その attempt のフォルダは不完全**なので、`manifest.json` が無いフォルダは**一覧に出さない** | P5・P6 の `.tmp` の教訓（`export.py` の `_atomic_write`） |
| 外部を待たない | `/object_info`・`/api/jobs`・`/history` の取得は **`store.transaction()` の外**。書くのは短い取引だけ | P4-1 の監査 B-1（模型を取引の中で待って全 API が止まった） |

### 0.11 契約（他ツールが読む形）

| 何を | どこに | 理由 |
| --- | --- | --- |
| **書き出しの `manifest.json`** | **新規** `schemas/recipe-manifest.schema.json` | 書き出しの束は**人にも機械にも読ませたい**唯一の成果物（`attempt_id`・`recipe_hash`・`export_hashes`・`seeds`・`output_dir`・`notes`）。`abi` は `"0.1"`（文字列。`annotation-export` と同じ形） |
| `review.json` | **変えない**（`recipes` も `presets` も足さない） | `review.json` は**判断の記録**（P5 の契約）。条件の記録は判断ではない。§18 の「他のツールと連携しない」からも、条件を他ツールに読ませる要件が無い |
| sidecar（`<data>/sidecar/<sha256>.json`） | **形は変えない。** 監視が書く欄（`en_text` / `final_prompt` / `prompt_id` / 環境の写し）は既にある | `duplicates-deletion-backup.md` §5.1 が「PNG から取り直せない唯一のもの」と位置づけている。既存の読み手（`capture.py`）を壊さない |

### 0.12 その他、本文が黙っているので決めたこと

| 論点 | 決め | 理由 |
| --- | --- | --- |
| **同じ記録から L1 と L2 を試せるか** | **`POST /api/recipes/{id}/export` に `mode` を任意で受け、`recipe_export` にも `mode` を写す**（記録の `mode` は変えない） | 本文 §4.2 は「記録ごとに決める」と読めるが、`frontend-design.md` の画面 12 は `?level=l1` を URL に持つ（＝切り替えて試す想定）。**両方を残す**のが実装の意図に合う。**本文に無い列なので差分** |
| **`count` と `seeds` の両方** | `seeds` があればそれを使い、`count` は無視（**両方指定は 422**） | 本文 §6.1 は `{seeds:[] \| count:8}` と書く（選択）。曖昧さを消す |
| **seed の型** | **10 進の文字列**で `recipe_export.seed` に入れる（符号なし 64bit が SQLite の INTEGER に入らない）。JSON では**数値**で出す | 本文 §4.9 がそう書いている。API の入出力は数値（`seeds:[1,2]`）で、保存だけ文字列 |
| **`GET /api/recipes` の並び** | `created_at DESC, id DESC`（キーセット。`cursor` は `created_at\|id`） | P6 の台帳の並びと同じ。**決定的**（2 回出して同一） |
| **`#/recipes` の並び** | 既定は `created_at DESC`。`?sort=uses`（書き出しの回数）も受ける | `frontend-design.md` の `#/recipes?sort=` に合わせる |
| **プリセットの「コピー」** | `record_json` の**人が読める要約**（モデル・sampler・steps・cfg・denoise・seed・解像度・プロンプト）を組み立てて返す。`GET /api/presets/{id}/record` がそれ | 本文 §4.10「プロンプトとパラメータをコピー」。**適用はしない**（§6-10） |
| **`env_snapshot` の中身** | `comfyui_version`・frontend・pytorch・`cuda`（`/system_stats`）／カスタムノードの版（`/api/customnode/installed`。**版が無いものは `__init__.py` の size と mtime**＋「版不明」）／`/object_info` から**使ったノードの宣言だけ**を抜いた写し／モデルの `(name, size, mtime)` | 本文 §4.6。**全部を保存すると大きい**ので、`/object_info` は**使ったノードだけ** |
| **モデルのフルハッシュ（本文 §8-1）** | **P7 では作らない**（既定は `(名前, size, mtime)`。`hash_mismatch` を理由に出す） | 53 GB で約 2 分（本文 §4.6）。**要るなら後段**（P8 以降）で「まとめて取る」ジョブにする |
| **結果が複数枚（本文 §8-3）** | **1 つの `recipe_export` に複数の `recipe_export_result`** をぶら下げる（`recipe_export` は**グラフ 1 つ＝seed 1 つ**なので、そこから N 枚出れば N 行）。合否は**1 枚ずつ**付ける | 表の形（`recipe_export_result` が N 行）が既にそうなっている。**まとめて合否**は画面の便利機能として P7-4 で足してよい（記録は 1 枚ずつ） |
| **手作業の後処理（本文 §8-4）** | **受け取る**。ただし `manual_step` を理由として出し、`matched_by` は `'manual'`（人が選んだ）にする | 「自動で分からない」ので、**人が選んだという事実**を残すのが正しい |
| **`text_not_captured` の画像（本文 §8-5）** | 画面に「訳が残っていない」と出し、**L3（人が訳を貼る）**へ誘導する。**まとめて訳し直す**は P7 では作らない（見えている語だけ訳す P4-2 の方針と混ざるため） | P4-2 の §0.9（見えた語だけ訳す）と衝突しない形 |
| **監視の口の権限** | `POST /api/watcher/start` / `/stop` は `human` だけ。**状態は `GET /api/watcher`**（書かない） | 判断と同じ規律（§0.10） |
| **`GET /api/recipes/{id}/graph?format=ui\|api`** | `ui` は**PNG の `workflow` チャンクがあるときだけ**返す（無ければ **422** で「UI 形式が残っていない」）。`api` は常に返す | 実データで **UI 形式を持つのは 183 枚中 1 枚**（実測）。**無いのに空を返さない** |
| **書き出しのフォルダ名** | `<data>/exports/<recipe_id>/<attempt_id>/`（本文 §4.7 手順 6 のとおり）。`recipe_id` は ULID なので人が読めない → **manifest と画面に元画像・条件の要約を出す** | 人がフォルダを開く前提（D&D する）なので、中身で分かるようにする |

### 0.13 画面（新しい画面を 2 つ作る。`frontend-design.md` に先に足す）

- **12. 条件と書き出し `#/asset/<id>/recipe`**（拡大から入る）: 判定と理由（§4.7）・レベルの選択（§4.8）・
  書き出しの束（§4.9）・結果の行（§4.10）・合否の入力（§4.11）。
- **13. 記録した条件とプリセット `#/recipes?sort=`**: 条件の一覧とプリセットの一覧（§4.12）。**適用ボタンは置かない**。
- **画面を増やさない**。`#/ingest`（取り込み）は P3、`#/duplicates` は P8。
- **`frontend-design.md` は既に §4.7〜§4.12 を持っている**（実測）。P7 の実装者が足すのは
  **§3 の画面一覧の 12・13 に「P7 で作った」**、**§4.13 の後に「書き出しの束のフォルダの見せ方」**、
  **§6 の文言**（「印を付けられません」「seed の欄は触らずに Queue」など）、**§11 の細部**（ポーリング間隔、
  候補の出し方）だけ。

### 0.14 利用者の回答（**2026-10-16 に確定**。**すべて推奨どおり**）

| # | 論点 | 決定 | 補足 |
| --- | --- | --- | --- |
| **Q1** | 監視を P7 に入れるか（P3 との依存） | **(a) 監視の最小形も P7 に入れる** | R12 の完了条件（印から結果が紐付く）が監視に依存する。材料（`capture.py` / `png_meta.py`）は既にある（§0.2）。**P3 には `userdata` 設置・`#/ingest`・起動時の救済走査・訳し直しを残す** |
| **Q2** | 印ありの認定の厳しさ（本文 §8-2） | **(a) 前方一致＋PNG の `prompt` チャンクの保険** | 連番の桁数は ComfyUI の実装依存（§4.7.3）。ファイル名を変えられても PNG を見れば分かる |
| **Q3** | `userdata` への設置（ComfyUI のサイドバーに置く） | **(a) P7 では作らない**（P3 で） | 口は生きている（実行で確認済み）が、**利用者の既存ワークフローを触る**ので、P3 の取り込みの画面と一緒に決める。P7 は**API 形式 JSON を書いてドラッグ&ドロップを案内**するところまで |
| **Q4** | モデルのフルハッシュを取るか（本文 §8-1） | **(a) P7 では取らない**（`(名前, size, mtime)` だけ） | 既定は軽く、必要になったら後段でジョブにする |
| **Q5** | 複数枚出た結果の合否 | **(a) 1 枚ずつ付ける** | 記録は 1 枚ずつ。まとめるのは画面の便利機能として後で |
| **Q6** | 手作業の後処理を通った画像（本文 §8-4） | **(a) 結果として受け取る**（`manual_step` を理由に出す・`matched_by='manual'`） | 人が選んだという事実を残すのが正しい |

### 0.15 「本文と食い違う点」の一覧（まとめ）

| # | 本文 | この設計 | 種類 |
| --- | --- | --- | --- |
| 1 | `design.md:1449` の P7 に「監視での結果取り込み」が入る（P3 の 3-4 と重なる） | **監視の最小形を P7 に置き、P3 は設置・`#/ingest`・救済走査に絞る** | 範囲の重なりを解消（§0.2） |
| 2 | `design.md:555-558` の表は `recipe_*` / `preset` を「専門文書が定義」とする | そのとおり。**P7 で v6 として作る**（`watcher_state` も足す） | 本文どおり＋1 表 |
| 3 | `workflow-reproduction.md` §4.9 の DDL に `mode` が `recipe_record` にだけある | **`recipe_export.mode` と `marker_skip_reason` を足す** | 追加（§0.12） |
| 4 | 本文 §6.1 の `POST /api/recipes/{id}/export {seeds \| count, marker}` | **`mode` と `client_token` を足す** | 追加（§0.12・§0.10） |
| 5 | 本文は「手で紐付ける」と言うが口が無い | **`POST /api/recipes/{id}/exports/{attempt_id}/results` を足す**（`matched_by='manual'`） | 追加（本文の画面仕様を満たすため） |
| 6 | 本文 §5 の監視は `GET /api/jobs?limit=N` とだけ書く | **一覧 → 詳細の 2 段**（一覧に `workflow` が無いのを実測）＋**画像を出す job だけ** | 具体化（§0.9） |
| 7 | `design.md` §5.5 の `watcher_state` に DDL がある | 現物に無いので**P7 で作る** | 実装（§0.3） |
| 8 | `design.md:1756` の未回答（`filename_prefix` を鍵から除く筋） | **§4.3 の除外をそのまま実装**し、テストで「印を付けても鍵が変わらない」を固定 | 決着（§0.5） |

---

## 1. 何を作るか（範囲）と合格の線

### 1.1 作るもの

```
人 ── #/asset/<id>/recipe ──▶ 記録（recipe_record）＋判定（exact / approx / impossible ＋理由）
                              │  L1 / L2 / L3 を選ぶ
                              ▼
                    書き出し前の検査（/object_info）── impossible なら止める
                              ▼
                    印つきのグラフを書き出す（<data>/exports/…、seed 違いは N ファイル＋manifest）
                              ▼
人 ── ComfyUI のキャンバスへドロップ ──▶ 生成（**このツールはしない**）
                              ▼
監視（2 秒）── /api/jobs → /api/jobs/{id} ──▶ 印で照合 ──▶ 結果（recipe_export_result）
                              ▼
                    指標（再現キー・ssim・pHash・差分）＋ 人の合否（same / close / different / failed）
人 ── プリセット（名前を付けた条件）──▶ 参照とコピー（適用はしない）
```

- **生成はしない**（`workflow-reproduction.md` §6-1）。`/prompt` に投げるのは**タグ付けと訳だけ**（既存）。
- **元の記録は書き換えない**。結果は別の `asset`・別の行として残す（§4.8）。

### 1.2 合格の線（**実行して確かめられる形**）

| # | 線 | 確かめ方（そのまま打てる形） | 合否 |
| --- | --- | --- | --- |
| **1** | **条件が記録され、判定と理由が出る** | 実データの複製で `POST /api/assets/{id}/recipe` を **グラフありの 1 枚**と**グラフ無しの 1 枚（JPEG）**に打つ → `GET /api/assets/{id}/recipe` が `status` と `reasons` を返す。グラフ無しは **`impossible` ＋ `missing`** | 2 枚とも 200。グラフ無しが `impossible`、グラフありが `exact` か `approx`（`reasons` の中身が §4.5 の語彙） |
| **2** | **実データ 263 枚で判定が付く** | `tools/probe_p7.py --judge` が 263 枚に記録を作り、`{exact, approx, impossible}` の内訳を出す | **`impossible` = グラフ無しの枚数**（実測 80）と一致。`exact + approx = 183`（実測。§1.3） |
| **3** | **印つきのグラフを書き出せる** | グラフありの 1 枚で `POST /api/recipes/{id}/export {seeds:[1,2], marker:true}` → `<data>/exports/<recipe_id>/<attempt_id>/seed-1.json` と `seed-2.json` と `manifest.json` ができ、各グラフの `SaveImage.filename_prefix` が **`repro-<attempt_id>/seed-<seed>`** | 3 ファイル。印が 2 つとも入る。**`manifest.json` が `schemas/recipe-manifest.schema.json` を本物の `jsonschema` で通る** |
| **4** | **印を付けても再現キーが変わらない** | 書き出した 2 つのグラフと記録のグラフから `recipe_hash` を計算し、**`seed` 以外の差だけ**であることを確かめる（seed を揃えて書き出せば**鍵が一致**） | seed を固定して書き出したとき **鍵が記録と一致**。`seed-1` と `seed-2` の差は**鍵の差が seed の 1 か所だけ** |
| **5** | **前提が外れたら印を付けずに理由を出す** | `filename_prefix` がリンクのグラフ・`SaveImage` が無いグラフ・`filename_prefix` を持たない保存ノードがあるグラフを**合成で作って**書き出す（`tools/probe_p7.py --marker-preconditions`） | 3 つとも**印なし**で書き出され、`marker_skip_reason` が `前提 1` / `前提 2` / `前提 3` を指す。**画面に 1 行出る** |
| **6** | **書き出した印から結果が紐付く** | `tools/probe_p7.py --watch` が**偽の ComfyUI**（`/api/jobs` と `/api/jobs/{id}` を返す小さな HTTP サーバ）を立て、**印つきの出力を持つ job** を流す → 監視が拾い、`recipe_export_result` が `matched_by='marker'` で 1 行できる。**印の無い job では作られない** | 2 ケースとも期待どおり。**タグ付けの job（`outputs` が `tags`）は弾かれる** |
| **7** | **人が合否を記録でき、消えない** | `POST /api/recipes/{id}/exports/{attempt_id}/results/{result_id}/verdict {verdict:'close', note:'…'}` → `GET /api/recipes/{id}/exports` に残る。**元の `recipe_record` は変わらない**（前後で `GET /api/assets/{id}/recipe` を突き合わせ） | 合否が残る。記録の `recipe_hash` / `record_json` が**バイト一致** |
| **8** | **画面が 2 つ動く** | `#/asset/<id>/recipe`（判定・理由・レベル・書き出しの束・結果・合否）と `#/recipes`（一覧・プリセット・コピー）を **3 窓（1400×900 / 1200×800 / 1920×1080）**で開き、`gui_layout.mjs --screen recipe` / `--screen recipes` が `overflow=0` | 3 窓とも ok。**適用ボタンが無い**（`gui_smoke` で固定） |
| **9** | **実データの 1 枚で通しで動く**（人が 1 回だけ生成する） | 実データの複製で 1 枚を書き出し → **利用者が ComfyUI にドロップして 1 回 Queue** → 監視が結果を拾い、指標と合否の行が出る | **利用者に 1 回頼んで確かめる**（`workflow-reproduction.md` §7 の但し書き。生成はこのツールがしない） |
| **10** | **回帰と `GET` の無副作用** | `uv run --no-sync pytest -q`（**285 件＋新規**）・`gui_smoke`・`gui_layout` の**既存 6 画面**。`GET` の前後で `recipe_*` の行数と `<data>/exports/` のファイル一覧が変わらない | すべて緑。`GET` で 1 バイトも書かない |

- **測れない条件は書かない。** 9 は「利用者に頼む」ことを条件に含めて書いてある。
- **性能は §7**。未計測は「未計測」と書き、**どの段で測るか**を決める。

### 1.3 現物で確かめたこと（この設計の前提。**実行した**）

| 確かめたこと | 結果 |
| --- | --- |
| `db.py` の版と表 | **`SCHEMA_VERSION = 5`**。`recipe_record` / `recipe_export` / `recipe_export_result` / `preset` / `watcher_state` は**無い**（19 表） |
| 実データ | `.data` は **v5**・**263 枚**・判断 3 件。`<data>/workflows/` は**無い**。`exports/` は P5 の `review.json` 用だけ |
| `asset_meta.meta_json` のキー | `model` / `sampler` / `scheduler` / `steps` / `cfg` / `denoise` / `seed` / `width` / `height` / `loras` / `final_prompt` / `final_prompt_source` / `ja_text` / `primary_ksampler` / `textgen_params` / `unresolved` / `node_types` など 31 キー。**`graph` は入っていない**（グラフの実体はどこにも無い） |
| グラフの解析 | `png_meta.provenance()` が `{graph_format, graph, info}` を返す（`analyze_graph` が `final_prompt`・`primary_ksampler`・`reachable_from_outputs` を実装済み）。**P7 はこれをそのまま使う** |
| **印の前提（実データ 263 枚）** | **グラフあり 183 枚**（`api` 182・**`api+ui` 1**）、グラフ無し 80 枚。**183 枚すべてで前提 1〜3 を満たす**（`SaveImage` は 1 個・`filename_prefix` は**全部リテラル**） |
| 監視の口 | `GET /api/jobs?limit=N` → `{jobs, pagination:{offset, limit, total:731, has_more}}`。**一覧に `workflow` は無い**（`id` / `status` / `create_time` / `execution_*` / `outputs_count` だけ）。`GET /api/jobs/{id}` が **`workflow.prompt`（API グラフ）・`outputs`・`execution_status`** を返す（`extra_data` は `client_id` / `create_time` の 2 つ。API 起点なので `extra_pnginfo` は無い） |
| 監視の落とし穴 | `/api/jobs` には**タグ付けの job も並ぶ**（`outputs` が `{"2": {"tags": [...]}}`。実測）。**画像を出す job だけ**を扱う必要がある |
| `/history` の形 | entry のキーは `prompt` / `outputs` / `status` / `meta`。`prompt` は**5 要素のリスト**（`[2]` = API グラフ・`[3]` = extra_data・`[4]` = 実行対象ノード）＝ 本文 §2-4 のとおり |
| 環境の写しの口 | `/system_stats`・`/object_info`・`/api/customnode/installed`・`/experiment/models/{diffusion_models,loras}`（`name` / `pathIndex` / `size` / `modified` / `created`）は**すべて 200** |
| **`userdata` への設置** | `POST /api/userdata/workflows%2F<名前>.json` → **200**（一覧に出る）。`DELETE` 同じ道 → **204**（消える）。**探り 1 件を置いて消した**（利用者のワークフローは触っていない）。→ §3.1 C の経路は**生きている**（P3 で使える） |
| `execution_cached` | `/api/jobs/{id}` の `execution_status.messages` に `execution_cached` が出る（**同じグラフの再投入は実行されない**）。→ 監視は「実行された」と「キャッシュに当たった」を区別できる |
| P5 の資産 | `stores` の `transaction()`（RLock）・`db.ulid()` / `db.now()` / `db.stamp()`・`export.py` の `_atomic_write` と `clean_stale_tmp`・`require_human()`・`ReviewError`・`api/__init__.py` の `actor_of` |

---

## 2. データモデル

### 2.1 表（v6。`workflow-reproduction.md` §4.9・§4.10 に**足すだけ**）

```sql
-- 再現の記録（元画像 1 枚に対して 1 つ。条件の写し。**生成はしない**）
CREATE TABLE IF NOT EXISTS recipe_record (
  id              TEXT PRIMARY KEY,
  source_asset_id TEXT NOT NULL REFERENCES asset(id),
  mode            TEXT NOT NULL CHECK (mode IN ('pin_text', 'rerun_graph', 'manual_text')),
  recipe_hash     TEXT NOT NULL,          -- §4.3 の再現キー（当時の seed を含む）
  graph_path      TEXT,                   -- <data>/workflows/<sha256>.json（API 形式）。無い画像は NULL
  graph_kind      TEXT,                   -- 'ui' | 'api'（PNG が持っていた形。api+ui なら 'ui' も残る）
  record_json     TEXT NOT NULL,          -- §4.1 の全項目（取れなかった項目は null で明示）
  final_prompt    TEXT,
  final_prompt_source TEXT CHECK (final_prompt_source IN ('png_literal', 'reconstructed', 'manual')),
  captured_text   TEXT,
  captured_source TEXT,                   -- 'comfyui_history' | 'sidecar' | 'textgenerate' | 'manual'
  text_probe      TEXT,
  env_snapshot    TEXT NOT NULL,          -- ComfyUI 版・ノード版・GPU・dtype・使ったノードの宣言・モデルの size/mtime
  status          TEXT NOT NULL CHECK (status IN ('exact', 'approx', 'impossible')),
  reasons         TEXT,                   -- §4.5 の kind の配列（L1 なら 'text_pinned' を含む）
  actor           TEXT NOT NULL CHECK (actor IN ('human', 'agent')),
  client_token    TEXT,                   -- ★追加: 再送の鍵（同じ画像＋同じ mode の再送で行を増やさない）
  created_at      TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_recipe_source ON recipe_record(source_asset_id, mode);
CREATE UNIQUE INDEX IF NOT EXISTS ux_recipe_token ON recipe_record(client_token) WHERE client_token IS NOT NULL;
CREATE INDEX IF NOT EXISTS ix_recipe_created ON recipe_record(created_at DESC, id DESC);

-- 書き出し（1 回ごと。元の記録は書き換えない。seed 違いは seed ごとに 1 行）
CREATE TABLE IF NOT EXISTS recipe_export (
  id            TEXT PRIMARY KEY,
  recipe_id     TEXT NOT NULL REFERENCES recipe_record(id),
  attempt_id    TEXT NOT NULL,            -- 印に使う短い id。同じ束のグラフは共有する（§4.7.1）
  mode          TEXT NOT NULL CHECK (mode IN ('pin_text', 'rerun_graph', 'manual_text')),  -- ★追加（§0.12）
  seed          TEXT,                     -- 10 進の文字列（符号なし 64bit は SQLite の符号付き INTEGER に入らない）
  recipe_hash   TEXT NOT NULL,            -- 書き出したグラフの再現キー（seed を変えたときだけ記録と違う）
  graph_path    TEXT NOT NULL,
  marker        TEXT NOT NULL,            -- 'repro-<attempt_id>/seed-<seed>'
  marker_skip_reason TEXT,                -- ★追加: 印を付けなかった理由（'前提1'|'前提2'|'前提3'）。付けたときは NULL
  export_dir    TEXT NOT NULL,
  manifest_path TEXT,
  checked_json  TEXT,                     -- ★追加: 書き出す前の検査の結果（status と reasons。画面と監査の証拠）
  created_at    TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_export_attempt_seed ON recipe_export(attempt_id, seed);
CREATE INDEX IF NOT EXISTS ix_export_recipe ON recipe_export(recipe_id, created_at DESC);

-- 結果（監視で入るか、人が登録する。1 回の書き出しに複数枚あり得る）
CREATE TABLE IF NOT EXISTS recipe_export_result (
  id              TEXT PRIMARY KEY,
  export_id       TEXT NOT NULL REFERENCES recipe_export(id),
  prompt_id       TEXT,                   -- 監視が見つけた job id（= prompt_id）。NULL = 手動登録
  result_asset_id TEXT REFERENCES asset(id),
  matched_by      TEXT NOT NULL CHECK (matched_by IN ('marker', 'manual', 'conditions')),
  result_hash     TEXT,                   -- 結果 PNG の prompt チャンクから計算した再現キー（§4.3）
  same_hash       INTEGER NOT NULL DEFAULT 0,
  ssim REAL, phash_distance INTEGER, changed_fraction REAL, mean_abs REAL,
  seed_changed    INTEGER NOT NULL DEFAULT 0,   -- ★追加: 結果の seed が書き出しと違う（§4.7.2 の 2）
  verdict         TEXT CHECK (verdict IN ('same', 'close', 'different', 'failed')),
  note            TEXT,
  created_at      TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_result_export ON recipe_export_result(export_id, created_at);
CREATE UNIQUE INDEX IF NOT EXISTS ux_result_asset ON recipe_export_result(export_id, result_asset_id);

-- 名前を付けた条件（プリセット。§4.10）
CREATE TABLE IF NOT EXISTS preset (
  id              TEXT PRIMARY KEY,
  name            TEXT NOT NULL,
  note            TEXT,
  source_asset_id TEXT REFERENCES asset(id),
  record_json     TEXT NOT NULL,
  actor           TEXT NOT NULL CHECK (actor IN ('human', 'agent')),   -- ★追加
  created_at      TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_preset_created ON preset(created_at DESC, id DESC);

-- 監視の既読位置（`design.md` §5.5 の DDL。**現物に無いので P7 で作る**）
CREATE TABLE IF NOT EXISTS watcher_state (
  name           TEXT PRIMARY KEY,        -- 'comfyui'（将来の監視を増やせるように名前で持つ）
  last_prompt_id TEXT,                    -- 最後に処理した job id
  last_polled_at TEXT,
  enabled        INTEGER NOT NULL DEFAULT 0,
  updated_at     TEXT                     -- ★追加: いつ触ったか（`design.md` の DDL に無い）
);
```

- **`CHECK` を使う**（既存の書き方。`db.py` は 11 か所で使っている）。
- **`ALTER TABLE` は使わない**（新しい表だけなので `CREATE TABLE IF NOT EXISTS` で足りる）。
- ★印が**本文に無い追加**（§0.12・§0.15 に対応）。**足すだけで、本文の必須は変えない**。

### 2.2 索引の意図

| 索引 | 何を速くするか |
| --- | --- |
| `ux_recipe_source` | 「この画像の記録」を 1 回で引く（**同じ画像に同じ mode の記録を 2 つ作らせない**） |
| `ux_recipe_token` | 記録の再送で行を増やさない（P6 と同じ部分索引） |
| `ux_export_attempt_seed` | 同じ `attempt_id` の同じ seed を 2 回作らせない（**再送の冪等性**） |
| `ux_result_asset` | 同じ結果画像を同じ書き出しに 2 回入れない |
| `ix_recipe_created` / `ix_export_recipe` / `ix_result_export` / `ix_preset_created` | 一覧（新しい順）と、書き出し・結果の展開 |
| `ix_export_recipe` は `(recipe_id, created_at DESC)` | 1 つの記録の書き出しをまとめて引く |

### 2.3 グラフの置き場（§0.4 の決め）

- `<data>/workflows/<sha256>.json`（**画像の内容ハッシュ**が名前。同じ画像なら同じファイル）。
- `<data>/exports/<recipe_id>/<attempt_id>/seed-<seed>.json`（**書き出し**。印つき）。
- `<data>/exports/<recipe_id>/<attempt_id>/manifest.json`（§4.7.3。**契約は `schemas/recipe-manifest.schema.json`**）。
- **`<data>/exports/` は P5 が既に使っている**（`review.json` の全件は `<data>/export/review.json`）。
  **`export`（単数、P5）と `exports`（複数、P7）が並ぶ**ので、README と画面に 1 行書いて混同を避ける（**差分**）。

### 2.4 sidecar との関係

- sidecar（`<data>/sidecar/<sha256>.json`）は**既存の形のまま**。監視が書く欄（`en_text` / `final_prompt` /
  `prompt_id` / 環境の写し）は既にある（`capture.py` の `write_sidecar`）。
- **`recipe_record` は sidecar から復元できる**（`graph_path` は PNG から作り直せる）。**控えとしての sidecar の役割を
  変えない**（`duplicates-deletion-backup.md` §5.1）。

---

## 3. API（`design.md` §6.1 の該当行を、ここで確定する）

**すべて既存の middleware の下**（`app.py` の `local_only`）。`POST` は `Origin` の同一性と
`Content-Type: application/json` を要求する。

### 3.1 誰が呼ぶか・書くか

| 口 | 誰が呼ぶか | 書くか | 備考 |
| --- | --- | --- | --- |
| `GET /api/assets/{id}/recipe` | 画面・エージェント | 書かない | 記録＋判定。**無ければ 404**（`details.asset_id`） |
| `POST /api/assets/{id}/recipe` | **人** | 書く（記録 1 行＋グラフ 1 ファイル） | `{mode, text?, client_token?}`。**`human` 以外 403** |
| `GET /api/recipes` | 画面・エージェント | 書かない | キーセット（`created_at DESC, id DESC`） |
| `GET /api/recipes/{id}/graph` | 画面・エージェント | 書かない | `?format=ui\|api`。**UI が無ければ 422** |
| `POST /api/recipes/{id}/check` | 画面・エージェント | **書かない**（検査だけ。§4.7 手順 4） | `{mode?}` → `{status, reasons, inspected, object_info_age_ms}` |
| `POST /api/recipes/{id}/export` | **人** | 書く（`recipe_export` N 行＋グラフ N ファイル＋manifest） | `{mode?, seeds?\|count?, marker?, client_token?}`。**`human` 以外 403** |
| `GET /api/recipes/{id}/exports` | 画面・エージェント | 書かない | 書き出しと結果（**1 回で両方**返す。画面が 1 往復で描けるように） |
| `POST /api/recipes/{id}/exports/{attempt_id}/results` | **人** | 書く（`recipe_export_result` 1 行・`matched_by='manual'`） | `{result_asset_id}`。**印が無い結果を人が紐付ける口**（本文 §4.7.1 の表） |
| `POST /api/recipes/{id}/exports/{attempt_id}/results/{result_id}/verdict` | **人** | 書く（`verdict` / `note`） | §4.8。**消えない形で残す** |
| `POST /api/recipes/{id}/presets` | **人** | 書く（`preset` 1 行） | `{name, note?}`。`record_json` は記録から写す |
| `GET /api/presets` | 画面 | 書かない | 一覧（`created_at DESC`） |
| `GET /api/presets/{id}/record` | 画面 | 書かない | **人が読める要約**（§0.12） |
| `GET /api/watcher` | 画面 | 書かない | `{enabled, last_prompt_id, last_polled_at, last_error}` |
| `POST /api/watcher/start` / `/stop` | **人** | 書く（`watcher_state`） | **`human` 以外 403**。既に同じ状態なら 200（冪等） |

- **`PUT` は使わない。** 全部を置き換える操作が無い（`verdict` と `preset` の名前は `PATCH` で足すかは
  P7-4 で決める。**いまは `POST` だけ**）。
- **`GET` は状態を変えない**（§0.10）。

### 3.2 `POST /api/assets/{id}/recipe`（記録する）

```jsonc
{
  "mode": "pin_text",          // pin_text(L1) | rerun_graph(L2) | manual_text(L3)。既定 pin_text
  "text": null,                // manual_text のときだけ。利用者が貼った英文
  "client_token": "8b1c…"      // 任意。同じ画像＋同じ mode の再送で行を増やさない
}
→ 201 {"recipe_id": "01M…", "status": "approx", "reasons": ["text_not_captured", "text_pinned"],
        "graph_source": "png", "recipe_hash": "sha256:…", "replayed": false}
```

| 条件 | 応答 |
| --- | --- |
| 画像が無い | **404** `details: {"asset_id": "…"}` |
| `mode` が語彙の外 | **422** `details: {"mode": "pin_text \| rerun_graph \| manual_text"}` |
| `mode='manual_text'` なのに `text` が空 | **422** `details: {"text": "英文が要ります"}` |
| **グラフが無い（JPEG など）** | **201**。`status='impossible'`・`reasons=['missing']`・`graph_path=null`（**記録は作る**。後から PNG を差し替えても同じ記録で判定し直せる） |
| 既に記録がある（同じ `source_asset_id` ＋ 同じ `mode`） | **200** 既存を返す（`replayed: true`。`ux_recipe_source`） |
| 同じ `client_token` で**中身が違う** | **409** `code: "client_token_conflict"` |
| L1 なのに `final_prompt` が無い | **201**。`status='approx'`・`reasons` に `text_not_captured`（**L2 へ落とすのは画面の判断**。記録は L1 のまま残す） |

- **`record_json` は §4.1 の全項目**を入れる。**取れなかった項目も `null` で書く**（「記録が無い」と
  「取れなかった」を区別する）。**`graph_source` を足す**（`'png'` / `'history'` / `'sidecar'`）。
- 記録の時点で**環境の写しを取る**（`/system_stats`・`/api/customnode/installed`・`/object_info` の
  **使ったノードの宣言だけ**・モデルの `(name, size, mtime)`）。**取れなければ `null` にして、
  `reasons` に `unresolved` を足す**（繋がらないことを理由に記録を失敗させない）。

### 3.3 `POST /api/recipes/{id}/export`（書き出す）

```jsonc
{"mode": null, "seeds": [1, 2], "marker": true, "client_token": "…"}
→ 201 {"attempt_id": "r7k2m4", "export_dir": "<data>/exports/<recipe_id>/r7k2m4",
        "files": ["seed-1.json", "seed-2.json", "manifest.json"],
        "marker": "repro-r7k2m4/seed-1", "marker_skipped": null,
        "status": "approx", "reasons": ["text_pinned"], "seed_node": "3", "other_ksamplers": ["7"]}
```

| 条件 | 応答 |
| --- | --- |
| 記録が無い | **404** |
| 検査が `impossible` | **409** `code: "recipe_impossible"` `details: {reasons}`（**書き出さない**。§4.7 の関所） |
| `seeds` と `count` の両方 | **422** `details: {"seeds": "seeds か count のどちらかです"}` |
| `seeds` が 65 件以上 / `count` が 1〜64 の外 | **422**（**上限を決める**。1 回の書き出しは 64 枚まで） |
| 2 つ目の `KSampler` がある | **201**。`other_ksamplers` に列挙し、**seed は最初の 1 つだけ**書き換える（§4.7.2）。画面に「揃えられません」 |
| 印の前提が外れる | **201**。`marker_skipped` に `前提1`/`前提2`/`前提3`。**印なしで書き出す** |
| 同じ `client_token` の再送 | **200**。**同じ `attempt_id`** を返す（行もファイルも増やさない） |
| ComfyUI につながらない | **201**（検査をスキップ。`checked_json.inspected=false`。**書き出しはできる**） |

- **`seeds` を省略したときは `count` 枚**（既定 8）。seed は**当時の seed を起点に 1 ずつ**（`seed, seed+1, …`）。
  当時の seed が分からなければ**ランダムを人が決める**（`crypto` を使わず `random` でよい。**記録に残す**）。
- **書き換えるのは保存ノードから遡って最初の `KSampler` ただ 1 つ**（§4.7.2）。
- **manifest を書く**（§4.7.3 のキー＋ `status`/`reasons`）。**`schema` と `abi` を入れる**。

### 3.4 監視（`/api/watcher`）

```jsonc
GET  /api/watcher → {"enabled": true, "last_prompt_id": "744e…", "last_polled_at": "…", "last_error": null,
                     "picked": {"results": 2, "texts": 1, "skipped_jobs": 41}}
POST /api/watcher/start → 200 {"enabled": true, "baseline_prompt_id": "744e…"}   // 開始時の最新を基準にする
POST /api/watcher/stop  → 200 {"enabled": false}
```

- **`enabled` はプロセスの状態ではなく `watcher_state` の行**（再起動したら**止まっている**。
  常駐させない方針なので、勝手に再開しない）。
- **間隔は 2 秒**。**画面を開いていなくても回る**（人が開始したときだけ）。
- **job の処理は 1 件ずつ**。`GET /api/jobs/{id}` が失敗したら**既読にせず次の周期で再試行**。

### 3.5 契約（`review.json` は変えない）

- **`schemas/recipe-manifest.schema.json`（新規）**が唯一の新しい契約。`abi` は `"0.1"`。
- **`review.json` は触らない**（§0.11）。テストで「`recipe_*` の欄が `review.json` に**出ていない**」を固定する
  （P6-0 の監査 B1 の逆の型: **足していないことを確かめる**）。

---

## 4. 状態と遷移

### 4.1 `recipe_record.status`

```
（記録が無い） ──POST /api/assets/{id}/recipe──▶ exact | approx | impossible
                                                   │
                     書き出しの検査（POST …/check・…/export）で再評価 ──▶ impossible なら書き出さない
```

- **`status` は記録時に決まる**。書き出しの検査で `impossible` になったら、**記録は書き換えず**、
  書き出しの応答にその理由を出す（**記録は当時の事実**。今の環境の話は `checked_json` に残す）。
- `mode` は記録に持つが、**書き出しの口で上書きできる**（`recipe_export.mode` に写す。§0.12）。

### 4.2 `recipe_export_result.verdict`

| 状態 | 見分け方 | 画面 |
| --- | --- | --- |
| 合否が無い | `verdict IS NULL` | 「合否を付ける」（4 つのボタン） |
| 付いた | `verdict` が入っている | 値を出し、**変えられる**（上書き。履歴は残さない＝`recipe_export_result` は台帳ではない） |

- **`same` / `close` / `different` / `failed`** は**再現の合否**。画像の**キープ / ボツ**（`decision` 台帳）とは別
  （`workflow-reproduction.md` §4.8）。**混ぜない**（画面でも別の行に出す）。
- 結果の画像そのものにキープ / ボツを付けたければ、**通常の画像として** `decision` に入る（同じ画像を開いて付ける）。

### 4.3 監視の状態

```
停止（enabled=0） ──start──▶ 監視中（enabled=1。last_prompt_id が進む） ──stop──▶ 停止
                                  │
                          プロセスが落ちた → 再起動後は**停止のまま**（enabled=1 でも自動では回さない）
```

- **再起動後に自動で再開しない**。`enabled=1` のまま残っていても、**画面には「止まっています」と出す**
  （勝手に ComfyUI を叩き続けない）。**起動時に `enabled` を 0 に戻す**（`_top_up` と同じ流儀で `migrate()` の外・
  `app.py` の起動時に 1 行）。**P7-3 で実装**。

---

## 5. 画面（詳細は [`frontend-design.md`](frontend-design.md)。ここは挙動だけ）

### 5.1 `#/asset/<id>/recipe`（拡大から入る）

- 判定と理由（§4.7）を**上部に固定**（スクロールしても見える。P6-2・P4-3 で「入口が見えない」を 2 回踏んだ）。
- レベルの選択（§4.8）: L1 / L2 / L3。**L1 が既定**。`?level=l1` を URL に持つ。
  - L1 で `final_prompt` が無いときは「当時の訳が残っていない」と出し、**L2 か L3 を勧める**。
- 書き出しの束（§4.9）: `attempt_id`・印・フォルダ・manifest・seed の一覧。**「JSON を保存」と「フォルダを開く」**。
- 結果の行（§4.10）: サムネ・紐付けの根拠（`marker` / `manual` / `conditions`）・指標・`seed_changed` の印。
- 合否の入力（§4.11）: 4 つのボタン＋メモ。**押したら残る**（消えない）。
- **印を付けられなかったとき**は「印を付けられません」＋理由（前提 1/2/3）を 1 行で出し、
  **「印なしで書き出す」**を選ばせる（§4.7.1 の落とし方）。

### 5.2 `#/recipes?sort=`（記録した条件とプリセット）

- 条件の一覧（元画像のサムネ・判定・`created_at`・書き出しの回数）。**判定の理由を 1 行**。
- プリセットの一覧（名前・メモ・元画像・作成日時）。**行ごとに「コピー」**。**適用ボタンは置かない**（§6-10）。
- **`#/recipes` から書き出しはしない**（開いて元画像の画面へ行く。**画面をまたいで操作を増やさない**）。

### 5.3 `frontend-design.md` に足すもの（**実装の前に足す**）

| 足す所 | 内容 |
| --- | --- |
| §3 画面の一覧 | 12・13 に「**P7 で作った**」 |
| §4.9 の後 | **書き出しのフォルダの見せ方**（フォルダ名が ULID なので、manifest の要約を画面に出す） |
| §6 文言 | 「印を付けられません（理由: …）」「seed の欄は触らず、`control_after_generate` は `fixed` のまま Queue」「結果が出たら監視が拾います」「合否は当時の絵と一致するかです（キープ / ボツとは別）」 |
| §11 細部 | 監視のポーリング（2 秒。**画面を閉じても回る**）、`#/recipes` の並び、コピーの文面 |

---

## 6. 契約

### 6.1 `schemas/recipe-manifest.schema.json`（新規）

```jsonc
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "urn:image-reviewer:schema:recipe-manifest",
  "type": "object", "additionalProperties": false,
  "required": ["schema", "abi", "attempt_id", "recipe_id", "recipe_hash", "export_hashes", "seeds", "notes"],
  "properties": {
    "schema": {"const": "urn:image-reviewer:schema:recipe-manifest"},
    "abi": {"type": "string", "pattern": "^[0-9]+\\.[0-9]+$"},
    "generated_at": {"$ref": "#/$defs/Timestamp"},
    "attempt_id": {"type": "string"},
    "recipe_id": {"type": "string"},
    "recipe_hash": {"type": "string", "description": "記録の再現キー（sha256:…）"},
    "export_hashes": {"type": "object", "description": "seed（10 進の文字列）→ 書き出したグラフの再現キー"},
    "seeds": {"type": "array", "items": {
      "type": "object", "additionalProperties": false,
      "required": ["seed", "file", "expected_prefix"],
      "properties": {"seed": {"type": "string"}, "file": {"type": "string"},
                     "expected_prefix": {"type": "string", "description": "前方一致で見る（連番の桁数は実装依存）"}}}},
    "output_dir": {"type": ["string", "null"], "description": "ComfyUI の出力先（分からなければ null）"},
    "notes": {"type": "object", "description": "検査の結果（status / reasons / inspected）と利用者への手順 1 行"}
  },
  "$defs": {"Timestamp": {"type": "string", "pattern": "^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(\\.[0-9]+)?Z$"}}
}
```

- **`abi` は文字列**（`annotation-export` と同じ。点検 D2 の型に揃える）。
- **`seeds[].expected_prefix` は前方一致**であることを説明に書く（完全一致を期待値にしない。§4.7.3）。

### 6.2 `review.json` は変えない

- `recipes[]` も `presets[]` も**足さない**。**テストで「出ていない」を固定**する。
- 理由: `review.json` は判断の記録。条件は判断ではない（§0.11）。

### 6.3 sidecar は形を変えない

- 監視が書く欄は既にある（`en_text` / `final_prompt` / `prompt_id` / `captured_from_node` / 環境の写し）。
- **`recipes` を sidecar に足さない**（sidecar は「PNG から取り直せないもの」の置き場。条件は PNG から取れる）。

---

## 7. 性能と規模（この段で守る数値）

| 何 | 目標 | 根拠・測り方 |
| --- | --- | --- |
| `POST /api/assets/{id}/recipe` | **p95 300 ms 以内**（20 回。グラフありの 1 枚） | PNG の先頭を読む（`png_meta` は `cap` バイトだけ）＋ `/object_info` の**使ったノードだけ**の抽出。**未計測**（P7-1 で測る） |
| `POST /api/recipes/{id}/check` | **p95 500 ms 以内**（`/object_info` の取得込み。2 回目はキャッシュで **50 ms 以内**） | `/object_info` は大きい（実測: 何 KB か**未計測**。P7-2 で測る） |
| `POST /api/recipes/{id}/export`（8 seed・印つき） | **p95 1 秒以内** | グラフの JSON を 8 回書くだけ（生成はしない）。**未計測**（P7-2 で測る） |
| 監視 1 周期（新規 0 件のとき） | **50 ms 以内**（`/api/jobs?limit=50` 1 回） | **未計測**（P7-3 で測る） |
| 監視 1 周期（新規 1 件・画像 1 枚） | **2 秒以内**（次の周期に間に合う。`/api/jobs/{id}` ＋ PNG の登録 ＋ 指標） | 画像 1 枚の登録は P1 の走査と同じ（ハッシュ＋サムネ）。**未計測** |
| 再現キーの計算（1 グラフ） | **10 ms 以内**（200 ノード程度） | 純関数（JSON の正規化＋SHA-256）。**未計測**（P7-1 で測る） |
| 表の行数 | 記録は**画像 1 枚に 1 つ**（263 枚で 263 行）。書き出しは**その N 倍**（1 万枚で 1 万行＋書き出し） | 結果は**書き出した分だけ**（人が回した分） |
| 書き出しのファイル数 | 1 回の書き出しで **seed の数＋1**（manifest） | 64 枚上限なら 65 ファイル |

- **未計測の数値は「未計測」と書き、測ったらこの表を書き換える**（P9 で全部を裏づける）。
- **測り方を書く**（keep-alive か毎回接続か、何回の中央値か）。

---

## 8. テスト方針（**何を壊すと落ちるか**）

### 8.1 pytest（`tests/test_recipes.py` / `tests/test_manifest.py` / `tests/test_watcher.py` / `tests/test_db.py`）

| # | 壊すと落ちるもの | 何を確かめるか | なぜ要るか |
| --- | --- | --- | --- |
| 1 | `recipe_hash` から `filename_prefix` の除外を外す | **印を付けても記録の鍵と一致**する（seed を固定して書き出し、両方の鍵を比べる） | §4.3・§0.5。ここを外すと**書き出すたびに「別物」**になる |
| 2 | `denoise` を鍵から外す | `denoise` だけ違う 2 つのグラフで**鍵が違う** | §4.3 の「必ず入れる」。抜けると別の絵を「同じ条件」と呼ぶ |
| 3 | 結線を鍵から外す | 同じノード構成で**結線だけ違う**グラフの鍵が違う | §4.3（結線は条件の一部） |
| 4 | 判定の理由の語彙を変える | `graph 無し` → `impossible` ＋ `missing`／`final_prompt` 無し → `approx` ＋ `text_not_captured`／L1 → `reasons` に `text_pinned` | §4.5 |
| 5 | L1 の書き出しで翻訳の枝を外さない | 書き出したグラフに **`TextGenerate` が無く**、`CLIPTextEncode.text` が**リテラル**（`final_prompt` と一致） | §4.2 |
| 6 | L1 の「品質語の前置」を落とす | `final_prompt` が **`string_a + delimiter + 捕獲値`** になっている（実データの 1 例と突き合わせ） | §4.2 の注記（捕獲値をそのまま入れると品質語が落ちる） |
| 7 | 印の前提 1 を無視する | `filename_prefix` が**リンク**のグラフで**印を付けない**（`marker_skip_reason='前提1'`） | §4.7.1。付けると**結線が消えて鍵が変わる** |
| 8 | 印の前提 2 を無視する | `SaveImage` が無い（`PreviewImage` だけ）グラフで**印を付けない**（`前提2`） | §4.7.1 |
| 9 | 印の前提 3 を無視する | 複数の保存ノードの**片方だけに印**を付けない（全部に入れる／付けない） | §4.7.1 |
| 10 | 複数の `KSampler` を全部書き換える | 2 つあるとき **1 つだけ**書き換え、`other_ksamplers` に列挙する | §4.7.2 |
| 11 | 書き出す前の検査を外す | 存在しない `class_type` のグラフ → **409 `recipe_impossible`** で**書き出さない**（`node_missing`） | §4.7 手順 4 |
| 12 | 入力キーの版差の検査を外す | ノードが宣言していない `inputs` のキーがあるグラフ → **`unresolved`** | §4.7 の「点検で見つかった誤り」 |
| 13 | 検査で**入力名→フォルダの対応表**を持つ実装にする | カスタムのローダーでも**combo 値**で判定できる（対応表が無くても動く） | 同上 |
| 14 | `GET` が書くように変える | `GET /api/assets/{id}/recipe`・`GET /api/recipes/{id}/exports`・`GET /api/watcher` の前後で
`recipe_*` の行数と `<data>/exports/` のファイル一覧が**変わらない** | §0.10（P5 の C8/G2） |
| 15 | 記録の再送で行を増やす | 同じ `client_token` の 2 回目が **200 で同じ `recipe_id`**（行は 1 つ） | §0.10 |
| 16 | 書き出しの再送でファイルを増やす | 同じ `client_token` の 2 回目が **200 で同じ `attempt_id`**（ファイルも行も増えない） | §0.10 |
| 17 | 合否が記録を書き換える | 合否の前後で `GET /api/assets/{id}/recipe` の `recipe_hash` / `record_json` が**バイト一致** | §4.8（元の記録は書き換えない） |
| 18 | 監視が**画像を出さない job** を拾う | `outputs` が `tags` の job（タグ付け）では `recipe_export_result` を作らない | §0.9（実測で `/api/jobs` に混ざる） |
| 19 | 監視が印の無い job を紐付ける | 印の無い出力では `marker` で作らず、**候補として残す** | §4.7.1 |
| 20 | 監視の既読が進まない | 同じ job を 2 周期で 2 回処理しない（**結果が増えない**）。失敗した job は**既読にしない**（次の周期で再試行） | §0.9 |
| 21 | 監視を再起動で自動再開する | プロセスを立て直すと `enabled` が **0 に戻る**（勝手に ComfyUI を叩かない） | §4.3 |
| 22 | `mode` の上書きを無視する | `POST …/export {mode:'rerun_graph'}` で `recipe_export.mode` が `rerun_graph` になり、**記録の `mode` は変わらない** | §0.12 |
| 23 | 検査が繋がらないときに止める | ComfyUI 不通で `check.inspected=false` を返し、**書き出しはできる**（201） | §0.8 |
| 24 | 移行の手当てを壊す | **v1 の DDL から 1 回で v6**・**v5 から v6**・**3 回呼んでも同じ**。`integrity()` が綺麗 | P6-0・P4-0 の監査と同じ観点 |
| 25 | `review.json` に `recipes` を足す | `include_paths` などの既存の文書に **`recipe` の鍵が出ない**（本物の `jsonschema` で通る） | §6.2（**足していないことを固定**） |
| 26 | manifest の形を変える | 書き出した `manifest.json` が **`schemas/recipe-manifest.schema.json` を本物の `jsonschema` で通る**（`seeds[].expected_prefix` を含む） | §6.1。P6-0 の監査 B1 の型（足した欄は実際に出す） |
| 27 | 新しい `POST` の守りを外す | `POST /api/assets/{id}/recipe`・`/check`・`/export`・`/verdict`・`/watcher/start` に
**`Host: evil` と `Content-Type: text/plain` で 403** | P6 の点検 C8（口を足すたびに書く） |
| 28 | `actor` の検査を外す | 記録・書き出し・紐付け・合否・監視の開始が **`agent` で 403**、`GET` は 200 | §0.10（判断と同じ規律） |
| 29 | 索引を外す | `EXPLAIN QUERY PLAN` に `ux_recipe_source` と `ix_export_recipe` が出る | P5 の D1 の教訓 |
| 30 | 結果の seed の確認を外す | 結果の PNG の `KSampler.seed` が書き出しと違うとき `seed_changed=1` | §4.7.2 の 2 |

- **実データ依存のテストを書かない。** 合成の PNG（Pillow で作り `prompt` チャンクを入れる）と、
  **`/api/jobs` の偽サーバ**（`tests/` の中の小さなスレッド）で回す。
- **`/object_info` はフィクスチャ**（テストで ComfyUI を叩かない。**実機は `probe_p7.py`**）。

### 8.2 `tools/gui_smoke.mjs`（軽い DOM。CSS を持たない）

| # | 壊すと落ちるもの | 何を確かめるか |
| --- | --- | --- |
| 1 | 判定と理由の描画 | `impossible` / `approx` / `exact` の 3 つが別の見た目で出て、**理由が箇条書き**で出る |
| 2 | レベルの選択 | L1 が既定。`?level=l2` で L2 が選ばれる。**L1 で `final_prompt` が無いときの案内**が出る |
| 3 | 印を付けられない案内 | `marker_skipped` があるとき「印を付けられません（前提2）」が出て、**「印なしで書き出す」**が押せる |
| 4 | 書き出しの束 | `attempt_id`・印・フォルダ・seed の一覧・manifest のリンクが出る |
| 5 | 結果の行 | `matched_by` が `marker` / `manual` / `conditions` で**別の文言**。`seed_changed` の印が出る |
| 6 | 合否の入力 | 4 つのボタンで `POST …/verdict` が **1 回**。**押さなければ 0 回** |
| 7 | プリセット | 作成で `POST` が 1 回。**「適用」ボタンが存在しない**（`querySelector('.apply') === null`） |
| 8 | エスケープ | メモ・プリセット名・理由に `<script>` を入れても**生のまま出ない**（`esc()`） |
| 9 | 監視の表示 | `GET /api/watcher` の `enabled` で「監視中 / 止まっています」が出る。開始/停止で 1 回ずつ叩く |

### 8.3 `tools/gui_layout.mjs`（本物の Chrome。`--screen recipe` / `--screen recipes` を新設）

| # | 壊すと落ちるもの | 何を確かめるか |
| --- | --- | --- |
| 1 | 判定と理由が上に固定されているか | 3 窓で**スクロールせずに見える**（`verdictTop < 600px`。P6-2・P4-3 と同じ観点） |
| 2 | 書き出しの束の横幅 | 3 窓で `listOverflow=0`。**seed が 64 個**でも**縦に伸びるだけ**（折り返す） |
| 3 | 結果の行 | **結果 20 行**で縦に伸びるだけ。指標の数字が**折り返さない** |
| 4 | `#/recipes` | 3 窓で `overflow=0`。**記録 200 件**でも崩れない |

### 8.4 `tools/probe_p7.py`（実機。合否を出す）

- `--judge`: 実データの**複製**で 263 枚に記録を作り、`{exact, approx, impossible}` の内訳と**理由の分布**を出す
  （線 2）。**実データは `mode=ro`**（複製は `backup()`）。
- `--marker-preconditions`: **合成の 3 グラフ**（リンク・`SaveImage` 無し・prefix 無しの保存ノード）で
  **印を付けない**ことを出す（線 5）。
- `--watch`: **偽の ComfyUI**（`/api/jobs` と `/api/jobs/{id}` を返す）を立てて、
  ① 印つきの結果 → `marker` で 1 行 ② タグ付けの job → **行ができない** ③ 印の無い job → **行ができない**（線 6）。
- `--export`: 実データの 1 枚で書き出し、**ファイル一覧と印**を出す（線 3・4）。`manifest` を `jsonschema` で検証。
- **自分の置き場は自分で消す**（`--keep` で残す）。`probe_p6_1a.py` が 90 MB 残した前例がある。

---

## 9. 工程（小段と、Fable に監査させる単位）

| 段 | 内容 | 合格の線 | 監査の単位 |
| --- | --- | --- | --- |
| **P7-0** | v6 の移行（5 表）・`recipe-manifest` 契約・`review.json` を変えないことのテスト | 既存が緑。v1/v5 → v6・3 回呼び | 表と契約（P6-0・P4-0 と同じ） |
| **P7-1** | `recipe_hash`（純関数）・`record_json`・`env_snapshot`・判定・グラフの置き場・記録の口 | 線 1・2 | 記録と判定（**再現キーの除外**が主眼） |
| **P7-2** | 検査・L1/L2/L3・印・seed 違い・manifest | 線 3・4・5 | 書き出し（**印の前提**と**検査**） |
| **P7-3** | 監視の最小形・印の照合・指標・sidecar・合否 | 線 6・7 | 監視と紐付け（**画像を出さない job** と**再起動**） |
| **P7-4** | 画面 2 つ（`#/asset/<id>/recipe`・`#/recipes`）・`frontend-design.md` の追記 | 線 8・10 | 画面（**実物の Chrome**。軽い DOM では見えない穴） |

- **P7-0 は機能を足さない**（表と契約だけ）。**P5・P6・P4 と同じ形**。
- 各段で **`pytest`・`gui_smoke`・`gui_layout`（既存 6 画面＋新しい 2 画面）を緑に保つ**。
- **`design.md` 本体への反映は全段の後**に 1 回（§12 の一覧）。

---

## 10. 未確認とリスク（**推測で埋めない**）

| # | 未確認・リスク | どう扱うか |
| --- | --- | --- |
| 1 | **`/object_info` の大きさと取得時間**（検査の費用） | **未計測**。P7-2 で測って §7 に書く。60 秒キャッシュを入れる |
| 2 | **`control_after_generate` が API 形式に無い**（フロントで読み込んだときの復元が不明。§4.7.2 の注意） | **未確認**。manifest と画面に「seed の欄は触らず `fixed` のまま Queue」と出す。**結果の seed を読んで違えば出す**（対策 2） |
| 3 | **`temp` の画像がいつ消えるか**（`PreviewImage` の出力） | **未確認**。`type='output'` の保存ノードが無いときは**印を付けずに止める**（前提 2） |
| 4 | **`/history` の保持件数**（取りこぼしの窓） | **未確認**。監視を回している間は捕まる。**止めている間の生成は訳を失う**（仕様として受け入れる。§5.1） |
| 5 | **UI 形式のグラフが実データにほとんど無い**（183 枚中 **1 枚**。実測） | **設計に反映済み**: 「開く」は API 形式の D&D が主（`arrange()` で配置は自動）。UI 形式が無いときは **422 で「残っていない」**と出す（§0.12） |
| 6 | **`seed + 1` の並びが「意図した比較」になるか**（利用者の好みの問題） | 画面で**起点と刻みを選べる**ようにするかは P7-4 で判断（**いまは起点＋1 ずつ**） |
| 7 | **GPU が変わったときの訳の差**（`bf16` の選択。§4.4） | `env_snapshot` に `cuda` と dtype を残し、`gpu_differs` を理由に出す。**P7 では測らない** |
| 8 | **手作業の後処理を通った画像**（§8-4） | `manual_step` を理由に出す。**自動では分からない**（人が `matched_by='manual'` で紐付ける） |
| 9 | **`/api/jobs` の 731 件**（一覧の取得費用） | 一覧は `limit=50` ＋ 既読の id で切る。**全件は取らない**。開始時に 1 回 `total` を見るだけ |
| 10 | **監視中に新しい画像を登録する**（P1 の走査と同じ費用） | 1 枚ずつ（ハッシュ＋サムネ）。**大量に流れたときの上限**を決めていない（1 周期で **20 枚まで**にして、残りは次の周期。**差分**） |
| 11 | **`recipe_hash` の互換**（グラフの形が同じでも、別の ComfyUI の版で `inputs` が増えると鍵が変わる） | **仕様**（条件が変われば別物）。`version_differs` を理由に出す |
| 12 | **`preset` の名前の重複** | 同じ名前を許す（**人が見分けられればよい**。§4.10）。画面で作成日時を出す |
| 13 | **`#/recipes` から書き出せない**（画面をまたぐ） | 仕様（§5.2）。**元画像の画面で書き出す**（誤操作を減らす） |
| 14 | **実データで 1 回も生成していない**（線 9） | **利用者に 1 回頼む**（`workflow-reproduction.md` §7 の但し書き）。**それ以外の線は複製と偽サーバで確かめる** |
| 15 | **`userdata` への設置は P7 で作らない**（P3） | 実行で口が生きていることは確認済み（§1.3）。**D&D の案内で目的は果たせる**（fail-soft） |

---

## 11. 用語（この段で増えるもの）

| 語 | 意味 |
| --- | --- |
| **記録（recipe_record）** | 1 枚の画像の生成条件の写し。**生成はしない**。判定（`status`）と理由を持つ |
| **書き出し（recipe_export）** | 記録から作った**投入できるグラフ**（1 グラフ＝1 seed）。印と manifest を持つ |
| **結果（recipe_export_result）** | 利用者が回して出てきた画像。紐付けの根拠（`matched_by`）と指標と人の合否 |
| **再現キー（`recipe_hash`）** | 生成に寄与する部分グラフの hash。**印を付けても変わらない**（`filename_prefix` を除くため） |
| **判定（`status`）** | `exact` / `approx` / `impossible`。**画素の一致ではない**（条件の一致） |
| **理由（`reasons[].kind`）** | 近似・不可の内訳（`missing` / `text_not_captured` / `text_pinned` / `node_missing` / …） |
| **L1 / L2 / L3** | 書き出すグラフの作り方（`mode`）。L1＝英文を確定、L2＝グラフごと、L3＝人が訳を貼る |
| **印（marker）** | `filename_prefix` に入れる `repro-<attempt_id>/seed-<seed>`。結果を書き出しに紐付ける |
| **attempt_id** | 書き出しの束の短い id（`r7k2m4`）。seed 違いは共有する |
| **紐付け（`matched_by`）** | `marker`（自動）/ `manual`（人が選んだ）/ `conditions`（条件で候補） |
| **合否（`verdict`）** | `same` / `close` / `different` / `failed`。**キープ / ボツとは別** |
| **監視（watcher）** | `/api/jobs` を 2 秒ごとに見て、結果の取り込みと英訳の捕獲をする。**手で開始/停止** |
| **環境の写し（`env_snapshot`）** | ComfyUI の版・ノードの版・GPU・dtype・使ったノードの宣言・モデルの `(name, size, mtime)` |

---

## 12. 確かめてほしい点（レビュアー向け）

1. **§0.2 の P3 との依存の扱い**（監視の最小形を P7 に入れる）が妥当か。**P3 に残したもの**の線引きは正しいか。
2. **§0.5 の再現キー**が `workflow-reproduction.md` §4.3 の除外・包含を**そのまま**実装しているか。
   とくに **`filename_prefix` の除外**（印を付けても鍵が変わらない）と **`denoise` の包含**。
3. **§0.7 の印の前提と認定**。前提 1〜3 の判定が実装できる形か。**「印あり」の認定（前方一致＋PNG の保険）**で
   誤って紐付く危険は無いか。
4. **§0.9 の監視の最小形**が `workflow-reproduction.md` §5・§5.1・§6-11 と食い違っていないか。
   **開始時に過去を遡らない**判断は妥当か（救済走査は P3）。
5. **§8.1 の「壊すと落ちる」が本当に落ちるか。** とくに 1（印と鍵）・7〜9（印の前提）・11〜13（検査）・
   18〜20（監視）・25（`review.json` に足していない）・26（manifest の契約）。
6. **「実装者が気づいていない前提」が残っていないか。** P5〜P4 では「`GET` がファイルを書く」「部分索引」
   「浮動小数の境界」「キャッシュに当たった計測」「取引の中で外部を待つ」「契約に足した欄を出さない」が盲点だった。
   P7 では **`filename_prefix` のリンク**・**複数の `KSampler`**・**画像を出さない job**・
   **`control_after_generate` の復元**が同じ型の罠である。§10 の 15 件で足りるか。
7. **`design.md` を書き換えるべき箇所**: §6.1 の API 一覧（`mode`・`client_token`・手動紐付け・監視の口）／
   §5.5 の `watcher_state`（`updated_at` を足す）／`workflow-reproduction.md` §4.9 の DDL（`mode`・
   `marker_skip_reason`・`checked_json`・`seed_changed`・`actor`）／§14 の P7 の行（**監視の分担**）。
   **この一覧で足りるか。**
