# P7-1（記録と判定。R12 の前半）監査報告 — 実行込み

- 日付: 2026-10-16（23:42〜翌 00:10 JST）／指示書: `docs/p7-audit-brief-p7-1.md`／実装の記録: `docs/p7-1-implementation.md`
- 対象（commit **127f7c8**）: `src/image_reviewer/recipe.py`（**648 行**、23:34:20）・`src/image_reviewer/api/recipes.py`（46 行、23:16:27）・
  `api/__init__.py`（23:17:00）・`app.py`（23:18:08）・`tests/test_recipe.py`（**447 行・23 件**、23:32:21）・`tools/probe_p7.py`（204 行、23:33:58）
- 設計: `docs/p7-design.md` **993 行**（23:37:34。線 2 の数を 182 / 1 / 80 に直した版）
- **監査中に実装者が P7-2 に着手した**（未コミット）: `api/recipes.py` 23:46:15・`api/__init__.py` 23:45:55・`app.py` 23:45:34・
  `recipe_export.py`（新規、23:51）・`tests/test_recipe_export.py`（新規、23:52）・`docs/p7-2-implementation-brief.md`・
  `tools/probe_p7.py`（23:58:12。`--judge` は私が 23:44 に 23:33 版で回した。差分は P7-2 の `export_of` の追加）・`tools/check_contract_p7.py`（23:57）。
  `git diff` で見ると **P7-1 の 3 つの口（`get_recipe` / `list_recipes` / `record_recipe`）は 1 行も変わっていない**（P7-2 の口が足されただけ）。
  **`recipe.py` と `tests/test_recipe.py` は 127f7c8 のまま**。8791 のサーバ（23:46 頃起動）は足された版を読み込んでいた
  （`GET /api/recipes/x/exports` が `記録がありません` の 404 を返す）が、本報告の対象は P7-1 の口と `recipe.py` に限る。
  **`recipe_export.py` は監査していない**。pytest 340 は 23:43（着手前の木）で回した。
- 環境: 実データ `.data`（**v6・263 枚・判断 3 件・`recipe_record` 0 行・`workflows/` 無し**）は `mode=ro` だけ。複製は
  `sqlite3` の `backup()` で 5 つ（`.tmp-audit-redo/p71/{data-http（8791）, data-svc, data-direct（8792）, data-down, judge/data}`）。
  ComfyUI 0.39.2（8188）へは **GET だけ**（監査中 2,980 本以上。POST は 0。中継 `proxy.py`（8189）は GET 以外を 405 で止める）。
  利用者のアプリ（8790、PID 48228）は触っていない。
- 触っていないもの: `.data`（`db.sqlite3` 10-15 14:29:51・`-wal` 10-16 **23:18:34**＝監査前。実装者の申し送り 1 の v6 移行の時刻）、`src/`（自分の変更なし）、`.backup/`。

## 判定: **直してから次へ**

鍵（純関数）・記録時の 7 語・グラフの置き場・`GET` の無副作用・頁送り・`/object_info` の引き方・線 1・線 2・回帰は**すべて通った**。
落ちているのは**端の経路**（ComfyUI 不通・選択肢に無いモデル・同時投入・消えたグラフ）で、うち 2 つは指示書 §2 が名指しした観点（(3) と (5)）の設計の約束なので合格にしない。

### 最も重大な 3 件

| # | 何 | 再現と値 | 場所 |
| --- | --- | --- | --- |
| **A-1** | **ComfyUI に繋がらないと、グラフのある画像が全部 `impossible`（`node_missing` × ノード数）になり、1 枚 20〜32 秒かかる** | 複製の `settings.comfyui.url` を `http://127.0.0.1:1` にして `RecipeService.record()` を 4 枚 → `status=impossible`、`reasons=['node_missing'×9〜16]`、**20,353 / 26,314 / 20,269 / 32,419 ms**。行にもそのまま残る。設計 §0.8「**繋がらないときは `impossible` にしない**」・§3.2「取れなければ `null`」に反する | `recipe.py:251-262`（`system_stats` が落ちた後も全 `class_type` を引き続ける）・`:260`（引けなかった `None` と「引いたが無かった」`{}` を同じ `None` にする）・`:373-377`（`None` → `node_missing`） |
| **A-2** | **モデル / LoRA / VAE が選択肢に無くても `approx`**（設計 §0.6 は `impossible`。指示書 (3)） | 実データの 1 枚の `unet_name` を `no-such-model.safetensors` にして本物の宣言で判定 → `status=approx`、`reasons=[('unresolved','UNETLoader.unet_name=…（選択肢に無い）')]`。`unresolved` は `FATAL_REASONS` に無い | `recipe.py:51`・`:403-408`・`:447-448`。テスト `test_a_model_missing_from_the_combo_is_impossible` は **`status` を見ていない**（名前が嘘） |
| **A-3** | **同じ画像に同時に 8 本 `POST` すると 7 本が 500**（`client_token` を揃えても同じ） | 8791 にスレッド 8 本で `POST /api/assets/{id}/recipe` → `[201, 500×7]`、行は 1。ログは `sqlite3.IntegrityError: UNIQUE constraint failed: recipe_record.source_asset_id`（7 回）と `…client_token`（7 回）。`recipe.py:569` | `recipe.py:547-550`（錠の中で既存を見る）→ 錠を離して ComfyUI に聞く（`:555-559`）→ `:568-577` で INSERT。**窓の間に入った 2 本目が索引に当たる**（罠 2） |

次点 **A-4**: **消えたグラフを作り直さない**（§0.4 / §0.10「無ければ `graph_path: null`、`POST` で作り直す」）。`workflows/<hash>.json` を消す → `GET` は**消えた絶対パスをそのまま返し**、`POST` は 200 `replayed` で**ファイルを作らない**。

---

## A. 直っていない／設計の約束が成り立たない（必ず直す）

### A-1 ComfyUI 不通で全部 `impossible`・1 枚 20〜32 秒

- 再現: `python .tmp-audit-redo/p71/copy_real.py .tmp-audit-redo/p71/data-down http://127.0.0.1:1` → 上の `down.out.txt` の手順（`RecipeService(Store(data-down)).record(id)`）。
  結果（`.tmp-audit-redo/p71/down.out.txt`）: `exact` だった 3 枚が `impossible`、ja2en の 1 枚は `text_not_captured` ＋ `node_missing` × 16。
  `notes=['ComfyUI に繋がらなかったので宣言は確かめていない']` と `node_missing` が**同時に出る**（矛盾）。
- 原因: `collect_env()` は `system_stats()` が `None` でも `installed_nodes()` と全 `class_type` の `object_info()` を引き続け（`recipe.py:251-261`）、
  `_get()` の例外→`None`（`:214-218`）と `/object_info/NoSuchNode` の `{}`（実測。`:260` で `.get(class_type)` → `None`）を**同じ `None`** にして
  `declarations` に入れる。`declaration_notes()` は `None` を「引いたが無かった」（`:374-377`）と読むので全ノードが `node_missing`。
  実装の記録の「自分で決めた 4（`node_missing` は値が `None` のとき）」が**この前提を壊している**。
- 時間: `ComfyProbe` の `timeout=5.0` で、閉じた port への接続に約 1.8 秒ずつ（11〜17 回）。**錠は握っていない**（別スレッドの `store.locked()` は 0 ms × 5。`lock_wait.out.txt`）ので他の API は止まらないが、**`POST` の呼び手は 20〜32 秒待つ**。
- 直し方: `system_stats` が取れなければ**そこで打ち切って `declarations=None`**（`declaration_notes` は既に `None` を「検査していない」として扱う `:366-367`）。
  `object_info` の「引けなかった」は `None`、「引いたが無かった」は `{}` のまま区別する。`inspected=false` を**行に残す**（B-3）。
  テスト: `FakeProbe(stats=False)` が**定義されているのに使われていない**（`tests/test_recipe.py:134`）。

### A-2 選択肢に無いモデルが `approx`

- 再現: `.tmp-audit-redo/p71/judge_proxy.py` の (b)。本物の `/object_info/UNETLoader` の選択肢に無い名前で `status=approx`。
- 設計 §0.6「**モデル / LoRA / VAE が combo に無い → `impossible`**」、§0.8 も同じ。実装は `unresolved` の `detail` 文字列に「選択肢に無い」と書くだけで `status` には効かない（`recipe.py:447` は `kind` しか見ない）。
- 直し方: `_reason()` に `fatal` の印を持たせる（`{"kind":"unresolved","detail":…,"fatal":true}`）か、`declaration_notes` が重い側を別の `kind` で返し `judge` で致命に数える。7 語の語彙は変えずに済む前者を勧める（G-2）。
  テストは `status` を見る形に（F-2）。

### A-3 同じ画像への同時 `POST` が 500

- 再現: `.tmp-audit-redo/p71/http_checks.py` の「同時 8 本」。`server.log` に `Traceback` 14 本。
- 設計 §0.10「画像 1 枚に 1 記録」は**索引だけ**で守られていて、2 本目が `IntegrityError` → 500。P6 の罠（`UPDATE → INSERT の順`、`docs/p6-1a-audit-report.md` §2-2）と同じ型。
- 直し方: `INSERT … ON CONFLICT(source_asset_id) DO NOTHING` の後に `SELECT` し直して 200 で既存を返す（`client_token` の索引も同じ）。
  `save_graph` は先に済んでいるので捨てても害は無い（同名同内容）。テスト: 同一プロセスの 2 スレッド（`threading.Barrier`）で再現できる。

### A-4 消えたグラフを `GET` が `null` にせず、`POST` が作り直さない

- 再現: `http_checks.py` の「graph_path のファイルを消したら」。`GET` → `graph_path` は**存在しないパス**（`exists: False`）、`POST` → `200 replayed=True`、`file recreated: False`。
- 設計 §0.4「失っても記録は壊れない（指すファイルが無ければその場で作り直す）」、§0.10「無ければ `graph_path: null` として出し、記録の口（`POST`）で作り直す」。
  `recipe.py` の冒頭の docstring も同じ約束を書いている。`_doc_of()`（`:495-521`）は `row["graph_path"]` を返すだけ、`record()` は既存があると `:549-550` で即返す。
- 直し方: `_doc_of` で `Path(graph_path).exists()` を見て `null` にする（`GET` は書かない）。`record()` の既存返しの前に「ファイルが無ければ PNG から `save_graph`」（`POST` だけが書く）。

## B. 重大

### B-1 グラフのファイル名が `recipe_hash` なので、**同じ鍵で印だけ違う 2 枚目が 1 枚目のファイルを黙って書き換える**

- 再現（`.tmp-audit-redo/p71/atomic.out.txt`）: `filename_prefix` だけ違う 2 グラフ（鍵は同じ）を `save_graph` → 同じファイル。**中身は 2 枚目の prefix（b）**になり、1 枚目の記録の `graph_path` が指す内容が変わる。
- 設計 §2.3 は「`<data>/workflows/<sha256>.json`（**画像の内容ハッシュ**が名前。同じ画像なら同じファイル）」、§0.4 は「同じ画像から何度作っても同じファイル」。実装は `recipe_hash`（`recipe.py:111-113`）。
  鍵から除いた `filename_prefix` / `_meta`（実データ 173 枚にノード直下の `_meta` がある）はファイルには残るので、**名前と中身の対応が 1 対 1 でない**。
- 実データでは 183 枚の鍵がすべて異なるので今は起きないが、同じ条件で印違いを書き出す P7-2 の前提そのもの。G-3 に選択肢。

### B-2 `CLIPTextEncode` の文字列がリテラルで分かっていても、`KSampler` が無いと `text_not_captured` が付く

- 再現（`judge_proxy.py` の (f)）: `CLIPTextEncode(text="1girl, literal text")` → `SamplerCustomAdvanced` → `SaveImage` の合成グラフ → `final_prompt=None`、`status=approx`、`reasons=['text_not_captured']`。
- `judge()` は `has_text_encoder(graph) and not doc["final_prompt"]`（`recipe.py:441`）で付けるが、`final_prompt` は `analyze_graph` が**主の `KSampler` の正側から**しか埋めない（`png_meta.py:254-283`）。
  §0.6「**文字列が分からないとき**だけ」と違う。実データ 183 枚は全部 `KSampler` 経路なので今は出ないが、`SamplerCustomAdvanced` は Flux 系の標準。
- 直し方: 到達する `CLIPTextEncode` の `text` が**全部リテラルか結線先で解決できる**なら付けない（`resolve_input` で足りる）。

### B-3 `inspected` と `notes` が**行に残らない**（201 の応答にだけ出て、`GET` では消える）

- `record()` は `verdict["inspected"]` / `["notes"]` を応答に入れるだけで（`recipe.py:578-584`）、`record_json` にも `env_snapshot` にも書かない。
  A-1 を直して「繋がらなかったので確かめていない」を `exact` に残すと、**後から `GET` で「確かめた `exact`」と区別できない**。展開できない動的コンボの note も同じ。
- 併せて: **グラフ無しの `POST` が、ComfyUI が動いているのに** `notes=['宣言が取れていないので入力キーは検査していない', 'ComfyUI に繋がらなかったので宣言は確かめていない']` を返す
  （`collect_env` が `graph is None` で早期に `inspected=False` を返すため。`http_checks.out.txt` 線 1 の 2 枚目）。画面に出すと嘘になる。
- 直し方: `record_json` に `inspected` と `notes` を入れる（契約は P7 内なので変えられる）。グラフ無しは `inspected` を `null`（対象外）に。

## C. 中程度

### C-1 1 回の `POST` が ComfyUI へ **16 本（最大 22 本）の `GET`**、1 枚 115〜130 ms。目標（§7 p95 300 ms）は守れているが、実装者の「中央 1.1 ms」は probe を使い回した値

| 測り方 | 中央 | p95 | 最大 | 根拠 |
| --- | --- | --- | --- | --- |
| `probe_p7.py --judge`（probe 使い回し。実装者と同じ） | 1.2 ms | — | 101 ms | `judge.out.txt` |
| サービス直（1 枚ごとに `ComfyProbe`。口と同じ。ComfyUI 直） | 116.7 ms | 231.6 ms | 266.1 ms | `direct_timing.out.txt`（60 枚） |
| **口から（8792、ComfyUI 直、毎回接続、40 枚）** | **128.7 ms** | **196.4 ms** | 209.8 ms | `http_direct_timing.out.txt` |
| 口から（keep-alive、20 枚） | 114.9 ms | 160.9 ms | 184.8 ms | 同上 |
| 口から（8791、**中継 8189 経由**、40 枚） | 172.8 ms | 317.2 ms | 550.2 ms | `http_checks.out.txt`（中継の往復分が乗る） |
| グラフ無し 20 枚（口から） | 1.6 ms | — | 15.7 ms | 同上 |

- 内訳（1 枚）: PNG 読み 0.2 ms・鍵 0.05 ms・**`collect_env` 99.6 ms**。中継のログ（`judge_proxy.out.txt`）: 263 枚で **2,980 GET・4.1 MB**。
  内訳 `/system_stats` 183・`/api/customnode/installed` 183・**`/object_info/{ct}` 1,534（一括 `/object_info` は 0）**・`/experiment/models/*` 6 × 180（`clip` は 404）。
- **指示書 (4) の「一括を引いていないか」は OK**。申し送り 5（口が 1 回ごとに probe を作る）は目標内なので**持ち越してよい**が、A-1 の打ち切りと一緒に `class_type` ごとの短いキャッシュ（§0.8 の 60 秒）を入れるのが自然。

### C-2 `pin_text` に `text` を添えて `client_token` で再送すると 409

- 再現: `POST {mode:'pin_text', text:'ignored text', client_token:'tok-a5'}` → 201、同じ物を再送 → **409 `client_token_conflict`**（`http_checks.out.txt`）。
- `_replay()` は保存側の `text` を `final_prompt_source=='manual'` のときだけ埋める（`recipe.py:597-598`）ので、`pin_text` で無視した `text` が比較で食い違う。
  直し: 比較の前に `text` を `mode=='manual_text'` のときだけ残す（`record()` の `:537` と同じ正規化）。

### C-3 `graph_kind` が常に `'api'`（`api+ui` の 1 枚も）

- 判定の複製で `graph_kind` は `None` 80・`'api'` 183。`api+ui` の 1 枚（`01M4Z0KJSS8EXT49JGAZMZGTFJ`＝`approx` の画像）も `'api'`、`record_json.graph_format` は `'api+ui'`。
  `recipe.py:575`（`"api" if graph else None`）。P7-0 で `CHECK (graph_kind IN ('api','api+ui'))` を入れた意味が無い。直し: `prov["graph_format"]` を書く。

### C-4 `env_snapshot` が 1 行 **中央 10 KB・最大 69 KB**（263 枚で 3.3 MB）、`GET /api/recipes?limit=100` が **912 KB**（`limit=200` で 2.9 MB・0.18 s）

- 宣言（`KSampler` 3 KB など）が**記録ごとに重複**して入る。一覧は `env` と `record` を全行に付けて返す（`_doc_of`）。263 枚なら耐えるが、画面（P7-4）の一覧が毎回 1 MB になる。
  推奨: 一覧は要約（`recipe_id` / `asset_id` / `status` / `reasons` / `recipe_hash` / `created_at`）、`env` は `GET /api/assets/{id}/recipe` だけ。宣言は `(class_type, comfyui_version)` で 1 回だけ持つかハッシュで参照。

### C-5 グラフ無しの 80 行が同じ `recipe_hash`（`sha256:e3b0c4…`＝空文字の SHA-256）

- `recipe.py:564`。鍵は NOT NULL なので何か入れる必要はあるが、「同じ鍵＝同じ条件」で一覧や束ねを作ると 80 枚が 1 つの条件に見える。`NULL` にするか `graph_path IS NULL` を鍵の等価判定から外す決めを G-5 に。

### C-6 設計 §3.2 と §0.8 が食い違う（繋がらないとき `unresolved` を足すか）

- §3.2 の末尾「取れなければ `null` にして、`reasons` に `unresolved` を足す」、§0.8「このときも `status` は記録時の判定のまま（`unresolved` を勝手に足さない）」。実装は **note だけ**（§0.8 側）。
  実装の選択は妥当だが、設計の文面を §0.8 に揃える（E-3）。

## D. 軽微

- **D-1** `env_snapshot.frontend_version` が常に `null`。`/system_stats` のキーは `required_frontend_version`（`recipe.py:245` は `frontend_version` を読む）。`cuda` は `cuda_version` が無いので装置名（`cuda:0 NVIDIA GeForce RTX 3060 : cudaMallocAsync`）が入る。
- **D-2** 起動時に `workflows/*.tmp` を掃除しない（§0.4「起動時に `*.tmp` を掃除」）。`export.py` / `annotations.py` の `clean_stale_tmp` は自分のフォルダだけ。失敗時にその場で消すこと（`atomic.out.txt`: `os.replace` が `PermissionError` でも tmp 0）は確かめた。
- **D-3** `1.0` と `1` で鍵が変わる（実データ 150 枚で `cfg` を int にすると別の鍵）。PNG も `/history` も Python の JSON なので今は一致するが、正規化で数値型を揃えるかは決めておく（D のまま）。
- **D-4** `require_human()` の 403 の文言が「タグの付け外しは人だけができます」（`tags.py:33`）。記録の口でそのまま出る。
- **D-5** 201 と 200 で応答の形が違う（201: 11 キーの短い形、200: `GET` の全項目 ＋ `replayed`）。§3.2 の例は 201 の形だけ。画面は両方を読む必要がある。
- **D-6** `tests/test_recipe.py:215,221` の `get_recipe_hash_for_test` は存在しない属性への分岐（死んだ行）。
- **D-7** `_node_order()`（`recipe.py:60-62`）は鍵に効かない（`json.dumps(sort_keys=True)` が文字列順に並べ直す）。害は無い。
- **D-8** 動的コンボの選択値が結線（`sampling_mode` がリンク）だと入れ子キーが全部 `unresolved` になる（`:387`）。実データには無い。
- **D-9** 確かめた結果、問題なし: 記録時の `reasons` は 7 語だけ（263 行で `missing` 80・`text_not_captured` 1、他 0。`X16` で `text_pinned` を足すと 3 テストが落ちる）／
  `_meta` はノード直下でも `inputs` でも鍵に効かない（183/183）／キー順・ノード順をかき混ぜても同じ鍵（183/183）／結線の入れ替えで鍵が変わる（183/183）／
  到達しないノードを足しても変わらない（183/183）／**印を変えても同じ鍵 183/183**／**seed を変えると変わる 180/180**（残り 3 枚は upscale で seed 無し。点検の実測と一致）／
  鍵は 183 枚で distinct 183・0.026 ms／材料に `mtime` / `comfyui_version` / `cuda` / `probed_at` は無い／`actor` はヘッダだけ（`robot` は 422、無しは `agent` → 403）／
  `Host: evil` 403・`text/plain` 403・`agent` 403／`mode` 外 422・`manual_text` 空 422・知らない画像 404・本文が配列 422／
  `client_token` 再送 200 同じ `recipe_id`・行 +0／同じトークンで別画像 409／同じ画像に別 `mode` → 200 `replayed`・行 1／`manual_text` は `final_prompt_source='manual'`／
  **`GET` 13 本の前後で複製の全ファイル（size / mtime）と全表の行数が同一**／`GET /api/recipes` 3 頁（limit=100）で 263・重複 0／
  `GET /api/recipes?cursor=bad` 422・`limit=abc` 422／`record_json` は取れなかった項目を `null` で持ち `missing_fields` に名指し（グラフ無し 24 項目）／`graph_source` は `png` か `null` だけ／
  本物の ja2en グラフ＋本物の宣言で `unresolved` 0（`judge_proxy.py` (e)）／`sampling_mode='off'` にすると入れ子 7 キーが `unresolved`（設計どおり）／
  `/object_info/NoSuchNode` は `{}` → `node_missing` → `impossible`（(c)）／ComfyUI 不通中も `store.locked()` は待たない（0 ms × 5）。

## E. 設計とのずれ（設計が黙っているのに実装が決めた所も）

| # | 何 | 設計 | 実装 | 判定 |
| --- | --- | --- | --- | --- |
| E-1 | グラフのファイル名 | §2.3「画像の内容ハッシュ」 | `recipe_hash` | **変更を勧める**（B-1。G-3） |
| E-2 | `graph_kind` | DDL `CHECK IN ('api','api+ui')` | 常に `'api'` | 今直す（C-3） |
| E-3 | 繋がらないときの `reasons` | §3.2 は `unresolved` を足す、§0.8 は足さない | note だけ | 実装は妥当。**設計 §3.2 を §0.8 に揃える** |
| E-4 | `graph_path` の作り直し | §0.4 / §0.10 | しない | 今直す（A-4） |
| E-5 | `workflows/*.tmp` の起動時掃除 | §0.4 | 無い | 軽微（D-2） |
| E-6 | 線 2 の数 | 点検は 183 / 0 / 80 | **182 / 1 / 80** | **実装者が正しい**。ja2en の 1 枚は `CLIPTextEncode` があるのに文字列が PNG に無いので `text_not_captured` が規則どおり付く。点検 A-3 で私が書いた「直せば 183 / 0 / 80」は誤りだった |
| E-7 | `/experiment/models/clip` | — | 404 を `[]` 扱い | 妥当（`text_encoders` で見つかる。180 枚で `models` が埋まった） |

実装者が自分で決めた 5 点（記録の 1〜5）:

| # | 決めたこと | 判定 | 根拠 |
| --- | --- | --- | --- |
| 1 | `reasons` を語の配列に統一、説明は `reason_details` | **条件付き** | `GET` と `POST` で同じ形になったのは確認した。ただし 201 と 200 の**全体の形**は違う（D-5）し、**両方の形を比べるテストが無い**（F） |
| 2 | `canonical_graph` は `inputs` と `links` を必ず持つ | 妥当 | テスト `test_canonical_graph_keeps_literals_and_links_apart` が守る（X5 で落ちる） |
| 3 | 選択肢は「最初の要素が配列」か `["COMBO", {options}]` だけ | 妥当 | 本物の `/object_info` は `[["a","b"], {…}]` 形、`["STRING", {…}]` を選択肢にする壊し方（X2）は 5 テストで落ちる |
| 4 | `node_missing` は宣言が `None` のとき | **変更を勧める** | A-1。「引けなかった」と「引いたが無かった」を分けないと不通が `impossible` になる |
| 5 | 展開できない `COMFY_DYNAMIC*` は notes に | 妥当（ただし B-3） | テストあり（X1 で落ちる）。notes が行に残らない |

申し送り 4 件（記録の 1〜5）:

| # | 申し送り | 判定 |
| --- | --- | --- |
| 1 | `.data` が既に v6 | 事実として確認（263 枚・判断 3 件・`recipe_record` 0 行）。**実データに `create_app()` を当てた経緯は記録どおり書き残す**（`-wal` 23:18:34） |
| 2 | `…/graph`・`check`・`export`・presets・監視は P7-2 以降 | 持ち越してよい（P7-2 に着手済み） |
| 3 | `recipe_export_result.export_id` の `ON DELETE` | P7-0 の監査 C-1 のとおり**表が空のうちに決める**（ALTER では足せない） |
| 4 | `graph_source` は `png` のみ | 妥当（263 行で `png` 183・`null` 80） |
| 5 | 口が 1 回ごとに `ComfyProbe` を作る（263 枚で 3,000 回） | **持ち越してよい**（C-1: 口から p95 196 ms で §7 内）。A-1 と一緒に打ち切りとキャッシュを入れる |

## F. テストで守れないもの

実装者の 23 件は全部緑。壊し方 15 通り（`.tmp-audit-redo/p71/mutate_extra.py`、`mutations.out.txt`）:

| 壊し方 | 落ちたテスト | 判定 |
| --- | --- | --- |
| X1 動的コンボの展開を外す（`a.b` をそのまま宣言に探す） | 5 件（`test_dynamic_combo_nested_keys_are_expanded` ほか） | **守れている**（指示書 (3)） |
| X2 `["STRING", {…}]` を選択肢とみなす | 5 件 | 守れている（**専用のテストは無い**が実物形の宣言で落ちる） |
| X3 `filename_prefix` を鍵に入れる | 2 件 | 守れている |
| X4 `_meta` を鍵に入れる | **0 件** | テスト無し。ただしノード直下の `_meta` は `inputs` に来ないので構造上効かない（実測 183/183）。低 |
| X5 結線をリテラルに混ぜる | 1 件 | 守れている |
| X6 `has_text_encoder` を常に真 | 1 件 | 守れている |
| X7 動的コンボの選ばれた選択肢を無視（全選択肢のキーを許す） | **0 件** | テスト無し（`off` で入れ子が `unresolved` になることを 1 件） |
| X9 `_replay` を外す | 1 件（`IntegrityError` で落ちる。409 のテスト） | 守れている（落ち方は例外） |
| X10 `GET` が同じ内容でファイルを書き直す | **0 件** | `test_reading_never_writes` は**名前の一覧だけ**比べる。size / mtime も比べる |
| X11 鍵に時刻を混ぜる | 2 件 | 守れている（§8.1 の 33） |
| X12 `record_json` の `null` 項目を落とす | **0 件** | 指示書 (7)「取れなかった項目は `null` で明示」にテスト無し |
| X15 原子的でない書き込み | **0 件** | 一時ファイル → `os.replace` にテスト無し（失敗で tmp を残さないことも） |
| X16 記録時に `text_pinned` を足す | 3 件 | 守れている |
| X17 既存の返しを外す | 2 件 | 守れている |

テストが無い経路（壊し方の前に、そもそも検査が無い）:

| # | 経路 | 根拠 |
| --- | --- | --- |
| F-1 | **ComfyUI 不通**（A-1） | `FakeProbe(stats=False)` は定義だけ（`tests/test_recipe.py:134`）。使うテストが無い |
| F-2 | **選択肢に無いモデル → `status`**（A-2） | `test_a_model_missing_from_the_combo_is_impossible` は `kind` と `detail` だけ |
| F-3 | **同時投入**（A-3） | 無し |
| F-4 | **消えたグラフ**（A-4） | 無し |
| F-5 | `pin_text` ＋ `text` ＋ token の再送（C-2） | 無し |
| F-6 | `GET` と `POST` の `reasons` の形の一致（穴 1） | `test_graph_without_a_prompt_chunk…` は `POST` の形と `GET` の `status` だけ |

実装者が見つけた 4 件の穴とテストの対応: (1) `reasons` の形 → **無い**（F-6）／(2) コンボの誤判定 → 専用は無いが X2 で 5 件落ちる／(3) `canonical_graph` の形 → `test_canonical_graph_keeps_literals_and_links_apart`／(4) `node_missing` の意味 → `test_a_missing_node_is_impossible`（ただしその意味づけが A-1 の原因）。

## G. 依頼者への質問（推奨つき。待たずに推奨で進める）

| # | 論点 | 選択肢 | 推奨 |
| --- | --- | --- | --- |
| G-1 | ComfyUI 不通のときの記録 | (a) グラフだけで判定し `inspected=false` を行に残す（`node_missing` / `unresolved` を足さない） (b) `unresolved` を 1 つ足して `approx` (c) 記録を拒む（503） | **(a)**。§0.8 の文面どおり。`system_stats` が落ちたら打ち切り（1 枚 20 秒を 2 秒以下に）。§3.2 の「`unresolved` を足す」は消す |
| G-2 | 選択肢に無いモデルの致命の伝え方 | (a) `reason_details[].fatal=true` を足し `judge` が見る (b) 新しい語 `model_missing` を 8 語目に足す (c) `node_missing` に寄せる | **(a)**。§0.6 の 7 語を守れる。画面は `detail` を出すだけ |
| G-3 | グラフのファイル名 | (a) 画像の sha256（§2.3 の文面。1 枚 1 ファイル、印違いで上書きしない） (b) `recipe_hash` のまま、中身を鍵の材料（`canonical_graph`）にする (c) 今のまま | **(a)**。「PNG から作り直せる」と素直に対応し、P7-2 の書き出しは別フォルダ（`recipes/`）なので衝突しない。同じ条件の画像が 2 枚ならファイルも 2 つ（数 KB） |
| G-4 | 同時投入の扱い | (a) `ON CONFLICT DO NOTHING` → 再 `SELECT` → 200 (b) 錠を ComfyUI の往復まで広げる | **(a)**。(b) は P4-1 の B-1（取引の中で外部を待つ）に逆戻り |
| G-5 | グラフ無しの `recipe_hash` | (a) `NULL` 可にする（DDL 変更） (b) 空の SHA-256 のまま、等価判定は `graph_path IS NOT NULL` を条件にする | **(b)**。表は触らず、P7-2 の `check` / `export` が `status='impossible'` で止めるので実害は小さい |
| G-6 | 一覧 `GET /api/recipes` の重さ | (a) 要約だけ返す（`env` / `record` は 1 枚の口） (b) `?fields=` で選ぶ (c) このまま | **(a)**。P7-4 の画面は一覧に `env` を要らない |
| G-7 | P7-2 に着手済みだが A-1〜A-4 を先に入れるか | (a) A-1〜A-4 と C-2 / C-3 を P7-1 の直しとして先に入れ、再確認してから P7-2 を続ける (b) P7-2 の中で直す | **(a)**。どれも `recipe.py` の局所で、P7-2 の `check` / `export` が同じ `judge` / `collect_env` を使うので先に直す方が手戻りが少ない |

## H. 確かめられなかったこと・証拠の注記・後始末

確かめていないこと:
- `/history` からの捕獲（P3）・`sidecar` 経路（P7 では `png` だけ）。
- ComfyUI が「本当に知らないノード」は合成（`class_type` を `NoSuchNodeXYZ` に書き換え）で試した。実在のカスタムノードを抜いて試してはいない。
- `os.replace` の失敗は「目的のパスをディレクトリにする」で起こした（Windows で他の道具がファイルを開いている状態は作っていない）。
- `recipe_export.py` と `tests/test_recipe_export.py`（P7-2 の作業中。対象外）。
- 性能は 1 本ずつ直列。並列の負荷は測っていない。

紛らわしい出力:
- `hash_purity.out.txt` の `'size' in payload: True` は `EmptyLatentImage.batch_size` のキー名（環境の値ではない）。
- `down.out.txt` の末尾 `status counts: [<sqlite3.Row …>]` は自分の表示の雑さ。`data-down` には 4 行書いた。
- `layout.out.txt` の `--screen jobs` の 1 回目は `connect ECONNREFUSED 127.0.0.1:9334`（Chrome の CDP の port）。再実行で `すべて ok`。`--count 8` の 1 回目は自分の `head -8` で末尾を切った（2 回目で `すべて ok`）。
- `tests/.tmp/14c56522d783` と、途中で見えて消えた `tmp3housq01` / `tmpe1ifj8xe` は実装者の試験の残骸（自分の物ではない）。

回帰:
- `uv run --no-sync pytest -q` → **340 passed**（23:43、commit 127f7c8 の木）。`node tools/gui_smoke.mjs` → **すべて ok**（129）。
- `gui_layout` 6 画面（8791。`GET` の無副作用の**後**に実行。group と tag は複製に自分で入れた）: `--count 8` / `requests` / `group` / `asset` / `tags` / `jobs` すべて ok。
- 実データ: `.data/db.sqlite3` 10-15 14:29:51・`-wal` 10-16 23:18:34（監査前）のまま。`recipe_record` 0 行・`workflows/` 無し。`src/` に自分の変更なし（`git status` の変更は実装者の P7-2）。

後始末:
- 止めた: 8791（`data-http`）・8792（`data-direct`）のサーバ、中継 8189。
- 残した: `.tmp-audit-redo/p71/`（複製 5 つ・各 `workflows/` 183 ファイル・スクリプト・`*.out.txt`・`proxy.log` 353 KB・`server.log`）。実装者の `.tmp-audit-redo/p7/judge/` も触っていない。

実行したコマンド（`cd C:\work\image-reviwer`、`$env:UV_CACHE_DIR` 設定済み、`PYTHONUTF8=1`）:

```
uv run --no-sync pytest -q                                   # 340 passed
node tools/gui_smoke.mjs                                     # すべて ok（129）
uv run --no-sync python tools/probe_p7.py --judge --keep --data .tmp-audit-redo/p71/judge/data   # 182 / 1 / 80
python .tmp-audit-redo/p71/copy_real.py .tmp-audit-redo/p71/data-http http://127.0.0.1:8189      # backup() の複製（settings.comfyui.url を中継へ）
python .tmp-audit-redo/p71/proxy.py 8189 .tmp-audit-redo/p71/proxy.log                            # GET だけ通す中継
python .tmp-audit-redo/p71/hash_purity.py                    # 183 グラフの純関数性
python .tmp-audit-redo/p71/judge_proxy.py .tmp-audit-redo/p71/data-svc .tmp-audit-redo/p71/proxy.log   # 2,980 GET・(a)〜(f)
PYTHONPATH=.tmp-audit-redo/p71 P71_MUTATION=X1_no_dynamic_expansion python -m pytest -q --tb=no -rf -p mutate_extra tests/test_recipe.py   # 壊し方（X1〜X17）
IMAGE_REVIEWER_DATA=.tmp-audit-redo/p71/data-http uv run --no-sync image-reviewer serve --port 8791
python .tmp-audit-redo/p71/http_checks.py                    # 線 1・守り・token・同時 8 本・無副作用・頁送り・graph_path
python .tmp-audit-redo/p71/copy_real.py .tmp-audit-redo/p71/data-down http://127.0.0.1:1 → down.out.txt / lock_wait.out.txt
IMAGE_REVIEWER_DATA=.tmp-audit-redo/p71/data-direct uv run --no-sync image-reviewer serve --port 8792 → http_direct_timing.out.txt
MSYS_NO_PATHCONV=1 node tools/gui_layout.mjs --base http://127.0.0.1:8791 --count 8 / --screen requests / --screen group --group 01M52K5WHJ9PPRN5MX86X09BNR / --screen asset --ids 01M4Z0KJS58V2SAJBGTG1TRFK5 / --screen tags / --screen jobs
```

## 最も重大な 3 件（再掲）

1. **A-1** ComfyUI 不通でグラフのある画像が全部 `impossible`（`node_missing` × N）、1 枚 20〜32 秒。`recipe.py:251-262` で打ち切り、`None` と `{}` を分ける。テスト無し。
2. **A-2** 選択肢に無いモデルが `approx`（§0.6 は `impossible`）。`recipe.py:447` は `kind` しか見ない。テストは `status` を見ていない。
3. **A-3** 同じ画像への同時 `POST` 8 本で 7 本が 500（`UNIQUE` に当たる）。`ON CONFLICT DO NOTHING` → 再 `SELECT` → 200。

次点 **A-4** 消えたグラフを `GET` が `null` にせず `POST` が作り直さない（§0.4 / §0.10 の約束）。
