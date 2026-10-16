> **廃止（2026-10-17。利用者の判断）**: この段は**削除しました**。理由と控えは [`p7-decision.md`](p7-decision.md) を見てください（①PNG を ComfyUI にドラッグすればワークフローが戻るので記録は重複 ②ja2en の英訳も実行すれば取り直せる）。**記録として残しています。**

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
- **含める**: `class_type`・リテラルの `inputs`・**結線**（どのノードの何番目かの出力がどこへ）・モデル名・LoRA と重み・
  VAE・CLIP/TE・sampler/scheduler/steps/cfg/**denoise**/seed/解像度・リテラルのプロンプト・
  `TextGenerate` の全パラメータ・`init_image` のハッシュと `strength`。
  **（点検 A-3）鍵は「グラフだけの純関数」にする。** 前の版は「モデル名（＋`(size, mtime)` が分かれば添える）」と
  していたが、**環境依存の値を鍵に混ぜると、結果の PNG から計算した鍵（§0.9）が書き出しの鍵と絶対に一致しなくなる**
  （`size` / `mtime` はファイルを置き直せば変わる）。`(size, mtime)` は **`env_snapshot` と `hash_mismatch` の材料**に
  留める（鍵には入れない）。
- 正規化: **キー昇順・空白なしの JSON → SHA-256 → `sha256:` を付ける**。
- **（点検 A-3）L1（`pin_text`）で鍵が変わるのは `TextGenerate` を持つグラフだけ。** 実測（`hash_proto.py`）では
  **L1 変換で鍵が変わるのは 183 枚中 1 枚**で、残り 182 枚は L1 でも鍵が同じ（`TextGenerate` を含まないため）。
  したがって **「L1 はキーが必ず変わる」は誤り**。L1 の書き出しは、**`TextGenerate` を含むグラフだけ**が
  **`approx` ＋ 理由 `text_pinned`** になり、それ以外は `exact` のまま。
  **記録の鍵と書き出しの鍵は別々に持つ**（`recipe_export.recipe_hash`。§3.3）。

### 0.6 判定（`exact` / `approx` / `impossible`）と理由の語彙

`workflow-reproduction.md` §4.5 の表を**そのまま**使う（`status` 3 語 ＋ `reasons[].kind` 11 語）。
この段で足すのは 1 つだけ:

- **`graph_source`**（`record_json` の中。`'png'` | `'history'` | `'sidecar'`）。本文は「取れなかった項目は null」と
  書くだけなので、**どこから取れたか**を残す（後から「なぜこれは近似なのか」を辿れるように）。
  **（点検 C-8）P7 では `graph_source='png'` しか出ない**（`/history` から捕獲する経路は P3 の仕事）。
  `'history'` / `'sidecar'` は**語彙に残す**（P3 で使う）。

**（点検 A-3）記録時の判定と書き出し時の判定を分ける。** 前の版は 11 語を 1 か所で扱っていたので、
線 2 の内訳と線 4 の鍵の一致が**設計のままでは評価できなかった**（`text_pinned` を記録時に付けると、
L1 既定の記録が全部 `approx` になり `exact` が常に 0 になる。§3.2 の例は `text_not_captured` と
`text_pinned` が同時に出ていて、§4.2 の「L1 は `final_prompt` が分かるときだけ」とも矛盾していた）。

| いつ | 出す理由（`reasons[].kind`） | どこに残すか |
| --- | --- | --- |
| **記録した時点**（`status` を決める） | **`missing` / `text_not_captured` / `node_missing` / `unresolved` / `version_differs` / `hash_mismatch` / `gpu_differs`** の 7 つ**だけ** | `recipe_record.status` / `reasons_json` |
| **書き出す時点**（mode を選んだ後） | **`text_pinned` / `llm_nondeterministic` / `manual_step`**（mode に依存する 3 つ） | `recipe_export_attempt.checked_json`（と応答の `reasons`） |

- **`text_not_captured` は「到達部分グラフに `CLIPTextEncode` があるのに文字列が分からないとき」だけ**付ける。
  **テキストを使わないグラフは「欠けていない」**（前の版はこれを区別していなかった）。
  - **（P7-1 の監査 B-2）「分かっている」の定義を足す**: `text` が**リテラル**、または**結線先をたどって
    文字列に行き着く**（`resolve_input`）なら**分かっている**。`png_meta` の `final_prompt` は
    **主の `KSampler` の正側から**しか埋まらないので、`SamplerCustomAdvanced` のような経路
    （`KSampler` が無い）では `final_prompt` が `None` でも**文字列は分かっている**。
    前の版はそれでも付けていた（実装: `text_unknown()`）。
- **（P7-1 の監査 A-2）選択肢に無いモデル / LoRA / VAE は `fatal` の印で `impossible` にする。**
  **語彙（7 語）は増やさない**。`reasons[].fatal=true` を `reason_details` に足し、`judge` がそれを見る
  （`_is_model_input()`＝`*_name` の入力か `Loader` を含む class）。
- **（P7-1 の監査 A-1）ComfyUI に繋がらないとき**は **`system_stats` で打ち切る**。
  **全 `class_type` の `/object_info` を引かない**（引くと閉じたポートへの接続 1.8 秒 × 11〜17 回で
  **1 枚 20〜32 秒**かかり、しかも「引けなかった `None`」を「引いたが無かった」と読んで
  **`node_missing` を並べて `impossible` にしていた**）。`declarations=None`（**未検査**）のまま
  **`node_missing` / `unresolved` を足さない**。**`None`（引けなかった）と `{}`（引いたが無かった）を区別**する
  （`{}` は `node_missing`＝`impossible`、`None` は「検査していない」＋`notes`）。
  **`inspected=false` は行に残す**（下の B-3）。
- `status` の決め方（**記録した時点**。書き出しの口でもう一度評価する）:
  `impossible` ⊃ {グラフが無い, 必須のノード/モデルが今の環境に無い} / `approx` ⊃ {記録時の理由が 1 つ以上ある} /
  `exact` ⊃ {記録時の理由が 0 件}。
- **`unresolved` の重さ（点検 A-1 / G-7）**: **モデル / LoRA / VAE が combo に無い → `impossible`**、
  **入力キーの差（入れ子の展開でも説明できない物） → `approx` ＋ キー名**。
  （`workflow-reproduction.md` §4.7 手順 4 の「不可」と、`frontend-design.md` §4.7 の「近似」で
  **文書間で食い違っていた**ので、ここで 1 つに決める。）

### 0.7 印（marker）の前提と「印あり」の認定（本文の §4.7.1 を確定する）

- **前提 3 つ**（§4.7.1 の表）を**そのまま**実装し、1 つでも外れたら**印を付けない**。外れた理由
  （`前提1` / `前提2` / `前提3`。**空白なしが正**。DDL の `CHECK` は空白ありを弾く）は**束の表**に残す（**（点検 A-2a）`recipe_export.marker` は NULL 可**にして、
  `marker` と `marker_skip_reason` の**片方だけが入る**ことを `CHECK` で守る）。
- **`attempt_id` は 8 文字以上の `[a-z0-9]`**（点検 D-12）。前の版は 6 文字（例 `r7k2m4`）で、
  **`subfolder` の部分一致が他人の名前に当たり得た**（`repro-r7k2m4` と `repro-r7k2m40`）。**正確な一致を主**にする。
- **「印あり」の認定（本文 §8-2 の未決定）**: **（点検 B-4）Windows の `subfolder` はバックスラッシュ**で返る
  （実測: `filename_prefix = "ComfyUI/Anima/20261010/132800"` → `subfolder = "ComfyUI\\Anima\\20261010"`）。
  したがって照合は **`subfolder.replace("\\", "/") + "/" + filename` の形に寄せてから前方一致**する。
  `capture.py:48` は逆に `/` → `\\` に寄せているので、**どちらかに統一する**（P7 では
  **比較の直前に `/` へ寄せる**で揃える）。
  - `repro-<attempt_id>/` の**フォルダが書き出しごとに増える**（利用者の出力フォルダに `repro-*` が並ぶ）。
    **これは受け入れる**（manifest と画面に 1 行出す）。
  - **`subfolder` が `repro-<attempt_id>` と正確に一致**すれば `matched_by='marker'`。
    加えて **PNG の `prompt` チャンクの `SaveImage.filename_prefix` が `repro-<attempt_id>/seed-<seed>` で
    始まれば**、ファイル名を変えられていても `marker` と認める（本文の「保険」を採用。実測で
    `filename_prefix` は `prompt` にリテラルとして残る＝E-6）。
  - 連番の桁数・接尾辞は**期待値にしない**（前方一致。§4.7.3）。**seed 無しの束は `repro-<attempt_id>/noseed`**（§0.12 / G-4）。
- **実データでの裏取り**: 263 枚のうち **183 枚が前提 3 つを満たす**（`SaveImage` が 1 個・
  `filename_prefix` は全部リテラル）。**80 枚は `prompt` チャンクが無い PNG**（点検 D-1。**実データに JPEG は無い**）。
- **（点検 D-2）172 枚の `filename_prefix` は `__OUTPUT_PREFIX__`**（別ツールが差し込む置き札）。
  印なしで書き出すと**この名前で保存される**ので、**manifest の `notes` と画面に 1 行**出す。

### 0.8 書き出す前の検査（本文 §4.7 手順 4 をそのまま。**点検 A-1 / B-2 で形を確定**）

**（点検 B-2）`/object_info` は「使った `class_type` だけ」を引く。全体は引かない。**
実測: 全体は **2,394,596 バイト・1,212 ノードで 0.41〜0.91 秒**（`json.loads` に 12〜17 ms）。
一方 **`/object_info/{class_type}` は 0.7〜3.0 KB・0 ms**（`KSampler` 3,011 B、`TextGenerate` 2,685 B）。
グラフの異なり `class_type` は実データで **10 前後**（ノード数 10〜19 が 183 枚中 24 枚、10 未満が 159 枚）。
→ **≤ 20 回・合計数十 KB・数 ms**。**class_type ごとに 60 秒キャッシュ**し、**`check` の応答にキャッシュの有無を出す**。

検査は 3 つ:
① 全 `class_type` が在るか ② モデル/LoRA/VAE がそのノードの combo 値に含まれるか
③ 各ノードの `inputs` のキーが `input.required` / `input.optional` のキーに含まれるか。

**（点検 A-1）③ は「動的コンボ（`COMFY_DYNAMICCOMBO_V3`）の入れ子」を展開してから照合する。**
実測: 実データで `TextGenerate` を持つ唯一の 1 枚（ja2en の経路）が、前の版の規則どおりだと
**`unresolved`（宣言に無いキー）**になった。落ちていたキーは
`TextGenerate.sampling_mode.temperature` / `…top_k` / `…top_p` / `…min_p` / `…repetition_penalty` /
`…seed` / `…presence_penalty` の 7 つで、**`sampling_mode` の宣言が
`["COMFY_DYNAMICCOMBO_V3", {"options": [{"key": "on", "inputs": {"required": {"temperature": …}}}, {"key": "off", …}]}]`
という形**をしている（ComfyUI はこのグラフを実際に実行しているので、**検査の方が間違っていた**）。
- **展開の規則**: `inputs[<name>]` の値（例 `"on"`）に対応する `options[].key` の
  `inputs.required` / `inputs.optional` を **`<name>.<key>`** の形で宣言に足す。`"off"` なら入れ子は無い。
- **`COMFY_DYNAMIC` で始まる型で展開できないものは「検査の対象外」**にし、**`check.notes` に出す**
  （**黙って `unresolved` にしない**）。
- **`unresolved` の重さ**は §0.6 のとおり（モデルが combo に無い → `impossible`／キーの差 → `approx` ＋ キー名）。

- **ComfyUI につながらないときは `impossible` にしない**（書き出しはできる）。**検査をスキップして
  `check.inspected=false` を返し、画面に「今の環境では確かめられませんでした」と出す**（黙って通さない・黙って止めない）。
  このときも **`status` は記録時の判定のまま**（`unresolved` を勝手に足さない）。

### 0.9 監視の最小形（P7-3。本文 §5 の部分集合を、P7 の範囲として確定する）

| 何 | 決め |
| --- | --- |
| 起動 | **人が明示的に開始/停止**（`POST /api/watcher/start` / `/stop`。**常駐しない**。本文 §5.1・§6-11） |
| 接続先 | **（点検 C-6）設定 `comfyui.url`（既定 `http://127.0.0.1:8188`）**に寄せ、`POST /api/watcher/start {base_url?}` でも受ける。**設定は `start` のたびに読む**（P4-2 の監査 C-1: 設定をプロセスで 1 回しか読まず、試験で差し替えられなかった） |
| 間隔 | **2 秒**。ポーリングは **ComfyUI の** `GET /api/jobs?limit=50&offset=0&status=completed`（**新しい順**。`create_time` は ms） |
| 既読の基準 | **（点検 B-3-1）`watcher_state.baseline_create_time`（ms）**にする（`last_prompt_id` は UUID で**順序が無い**ので基準に使えない。表示用に残す）。**同じ ms に 2 件入る**ことがあるので、**処理済み id の集合**（プロセス内。数百件）で重複を弾く |
| 進めない条件 | **（点検 B-3-2）`pending` / `in_progress` の job を既読にしない。** `?status=completed` で引き、`failed` / `cancelled` は別に引いて**既読にだけ**する。基準を進めるのは**それより古い未完了が無いとき**だけ |
| 拾う単位 | **（点検 B-3-4）一覧だけで多くが分かる**: 各行に `outputs_count` / `previewable_outputs_count`、画像の job には `preview_output {filename, subfolder, type, nodeId, mediaType}` が入る（実測）。**タグ付けの job は `outputs_count: 0`** なので**詳細を取らずに弾ける**。「2 段」はそのままだが、**2 段目の回数は画像の job の数**で済む（731 件中 **427**） |
| キャッシュの見分け | **（点検 B-3-3）`execution_cached` は 731 件すべてに出る**（当たらない job は `nodes: []`）。「出たらキャッシュ」ではなく、**「保存ノードの id が `execution_cached.nodes` に含まれるとき＝新しい画像は出ていない」**と定義する |
| 対象の絞り込み | **画像を出す job だけ**を扱う（`outputs_count > 0` かつ `images` を持つ） |
| 取り込むもの | ① `TextGenerate` の出力（**由来を結線で確かめる**。§5 の 3 手順。`capture.py` の実装を使う）② `final_prompt` の**再構成** ③ 環境の写し（`/system_stats`・`/api/customnode/installed`・モデルの `size`/`mtime`）④ sidecar |
| 新しい画像の実体 | **（点検 B-1 / G-1-(a)）設定 `comfyui.output_dir`** を使う。既定は **`/internal/folder_paths` から推定**（この環境では `checkpoints[1]` の親＝`C:\ai\ComfyUI_windows_portable\ComfyUI\output` が当たる）し、**実在するときだけ**採用する。**監視の開始時に、その場所を登録ルート（`root` 表）に足す**（**1 回だけ利用者に確認**。出力先は普通は登録ルートの外にあるため。§19.3-10 の「ルート外を触らない」との関係）。**推定が当たらなければ `GET /view?filename=&subfolder=&type=output` でバイト列を取り寄せ、`<data>/results/<sha256>.png` に取り込む**（複製）に落ち、**画面に 1 行出す**（どちらの道を通ったかを黙っていない） |
| 取り込む単位 | **（点検 C-1 / G-5-(a)）画像 1 枚に 1 記録** |
| 印の照合 | §0.7 の規則（`subfolder` の正確な一致＋PNG の `prompt` の保険）で `matched_by='marker'` として `recipe_export_result` を作る。印が無ければ**作らない**（画面で手で紐付ける） |
| 指標 | 紐付けた結果の PNG から**再現キーを計算**して書き出しの鍵と比べ、`comparison.py` の指標（`ssim` / `phash_distance` / `changed_fraction` / `mean_abs`）を**同じ実装で**入れる（`comparison.md` §4 が定義の正） |
| seed の確認 | 結果の PNG の `KSampler.seed` を読み、書き出しの seed と違えば `seed_changed` として出す（§4.7.2 の 2 の対策。`seed_node` を使う＝点検 C-2） |
| 失敗の扱い | ComfyUI につながらない・job の詳細が取れない → **その回を飛ばして次の周期で再試行**（既読にしない）。`watcher_state` にエラーを残さない（帯を出さない） |
| 生成 | **しない**（§6-1）。この段でも `/prompt` に**画像生成のグラフを投げない** |

### 0.9.1 （P7-3 の監査 A-1〜A-3 で確定）監視の決まり 3 つ

- **取り込みは古い順**。**詳細が取れなかった job の先へは進めない**（`stopped`）。**20 枚の上限に当たった周期は基準を上げない**
  （残りは次の周期。処理済みは `_seen` が弾く）。`failed` / `cancelled` は**既読にだけ**して**基準を進めるのには使わない**。
- **起動時に `watcher_state.enabled = 0` に戻す**（§4.3。プロセスが変わればスレッドは居ないので、行だけが「動いている」と嘘をつく）。
- **英訳の捕獲は `RecipeService.capture_text()`** が行う（`graph_path` のファイルからグラフを読み、`capture.text_output_for` で
  取り、`final_prompt` を組み直し、**`judge` を通し直して `approx` → `exact` に上げる**）。**入れる先は「元画像」の記録**で、
  結果の画像ではない（印 → 束 → `recipe_record.source_asset_id` を引く）。

## 0.10 `GET` は書かない・`actor`・`client_token`・原子性（前の段の教訓を最初から入れる）

| 論点 | 決め | 根拠 |
| --- | --- | --- |
| `GET` の副作用 | **`GET` は 1 バイトも書かない。** 記録を作るのは `POST /api/assets/{id}/recipe`、書き出すのは `POST .../export`、紐付けるのは `POST`。**グラフの作り直し（`graph_path` が無いとき）だけは例外**にしたいが、**書き込みを伴うので `GET` では作り直さず**、**無ければ `graph_path: null` として出し、記録の口（`POST`）で作り直す** | P5 の監査 C8/G2、P6 の §0.6、P4 の §0.10 |
| `actor` | **記録・書き出し・紐付け・合否は人だけ**（`human` 以外 403。`require_human()` を再利用）。**監視の開始/停止も人だけ**（GPU とディスクを使う） | P4 の §0.14 Q3（検査は 1 か所）、P6 の §3.1 |
| `client_token` | **記録の口に付ける**（再送で行を増やさない。**（点検 C-1 / G-5）記録は「画像 1 枚に 1 つ」**なので、同じ `source_asset_id` の再送は **200 で既存を返す**。同じ `client_token` で**別の画像**なら **409**）。**書き出しの口にも付ける**（**（点検 A-2b）束の表 `recipe_export_attempt.client_token` に UNIQUE** を置き、同じ `client_token` の再送は**同じ `attempt_id`** を返す） | P6 の §0.9。`attempt_id` は元々「書き出しごとに発行する短い id」なので、再送で増やさない方が良い |
| 原子性 | 書き出しは**フォルダを丸ごと**作る（**（点検 D-7）`<data>/recipes/<recipe_id>/<attempt_id>/`** に `seed-*.json` と `manifest.json`。前の版の `<data>/exports/…` は P5 の `<data>/export/` と紛らわしい）。**一時ファイル → `os.replace`**。途中で落ちたら**その attempt のフォルダは不完全**なので、`manifest.json` が無いフォルダは**一覧に出さない** | P5・P6 の `.tmp` の教訓（`export.py` の `_atomic_write`） |
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
| **seed の型** | **（点検 B-6 で変更）API でも 10 進の文字列**（`seeds:["1","2"]`）で受けて返す。保存も文字列。**`seed + k` は `(seed + k) mod 2^64`** | 前の版は「JSON では数値」としていたが、**同じ値を 2 つの型で持つ**と、画面（素の JS）が `JSON.parse` した瞬間に**2^53 超で丸める**危険が残る（`KSampler.seed` の宣言は `max: 18446744073709551615`）。実データは最大 50 bit だが API 起点のグラフは超え得る。**型を 1 つに揃える**。`+k` は `2^64-1` 付近で ComfyUI の検証に落ちるので**剰余を取る** |
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
| **書き出しのフォルダ名** | **（点検 D-7）`<data>/recipes/<recipe_id>/<attempt_id>/`**（本文 §4.7 手順 6 のとおり。P5 の `<data>/export/`（単数）と紛らわしくない形に変えた）。`recipe_id` は ULID なので人が読めない → **manifest と画面に元画像・条件の要約を出す** | 人がフォルダを開く前提（D&D する）なので、中身で分かるようにする |
| **`GET /api/recipes/{id}/graph` でグラフが残っていないとき**（点検 D-4） | **422** `details: {graph: "残っていない"}`（`impossible` で `graph_path` が NULL のとき） | 空を返すと画面が「空のグラフ」を出す |
| **グラフの根（点検 D-5）** | **`SaveImage` / `PreviewImage` だけ**（`png_meta.reachable_from_outputs()` の `SAVE_TYPES` は定義だけで未使用） | 実データには `SaveAnimatedWEBP` 等だけのグラフは無い。**あると「全ノード」に落ちる**ので §0.5 に明記 |
| **監視の接続先（点検 C-6）** | 設定 **`comfyui.url`（既定 `http://127.0.0.1:8188`）**に寄せ、`POST /api/watcher/start {base_url?}` でも受ける | タガー（`tagger.comfyui`）・`capture`・`gloss` で**別々**になっていたので 1 つに寄せる（線 6 の偽サーバもここに向ける） |
| **結果の画像の置き場（点検 B-1 / G-1）** | 設定 **`comfyui.output_dir`**（既定は `/internal/folder_paths` から推定し、**実在するときだけ**）。当たらなければ `GET /view` で **`<data>/results/<sha256>.png`** に取り込む | ComfyUI に**実体のパスを教える口が無い**（`/internal/folder_paths` に `output` が無い）。§0.9 の表に詳しく |

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

- **（点検）G-1〜G-7 も推奨どおりで確定**（点検の G は「待たずに推奨で進めてよい」とされた）。
  要点: **G-1** 結果の実体は設定 `comfyui.output_dir`（推定＋実在確認。当たらなければ `GET /view` で取り込む）／
  **G-2** 合否は上書き＋`verdict_at` / `verdict_actor`（「消えない」＝「再読込で失われない」）／
  **G-3** `preset` と `result` は `SET NULL`・`recipe_record` は RESTRICT（P8 に申し送り）／
  **G-4** `KSampler` の無いグラフは `seeds` / `count` 明示で 422 `no_sampler`、無指定なら seed 無し 1 ファイル（印 `…/noseed`）／
  **G-5** 記録は**画像 1 枚に 1 つ**／**G-6** 線 9 は**任意の確認**に格下げし、**門は線 6（本物の PNG で）**／
  **G-7** `unresolved` は「モデルが combo に無い → `impossible`」「キーの差 → `approx` ＋ キー名」。
  **詳細と反映先は [`p7-review-triage.md`](p7-review-triage.md)。**

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
| **9**（点検 E-3） | `design.md` §6.1 に**無い** | **`GET /api/watcher`・`POST /api/watcher/start` / `/stop`・`POST …/exports/{attempt_id}/results`** を足す（前の版は `results` だけを挙げていた） | 追加（§3.1） |
| **10**（点検 E-10） | `design.md` §5.5 の `watcher_state` は `enabled INTEGER` | **`NOT NULL DEFAULT 0` ＋ `baseline_create_time` ＋ `updated_at`** | 追加（§2.1） |
| **11**（点検 E-7） | `workflow-reproduction.md` §4.7 手順 4 は `unresolved` = **不可（書き出さない）**、`frontend-design.md` §4.7 は**近似** | **モデルが combo に無い → `impossible`／キーの差 → `approx`** に決める（§0.6） | 文書間の食い違いを決着 |
| **12**（点検 E-2） | `design.md:698-699` の `POST /api/presets {name, note?, source_asset_id?}` | **`POST /api/recipes/{id}/presets {name, note?}`**（記録から写す）。**`design.md` を直す側**（§12-7 に挙げる） | 口の場所と引数が違う |
| **13**（点検 E-11 / B-1） | `design.md` §19.3-10「登録ルート外を触らない」 | **監視の開始時に出力先を登録ルートに足す**（1 回だけ利用者に確認）。当たらなければ `<data>/results/` に取り込む | 出力先は普通ルートの外にある |
| **14**（点検 D-9） | `workflow-reproduction.md` §5 の段落が**同じ文面で 2 回**入っている | P7 の対象外。**§12-7 の書き換え一覧に足す** | 本文の重複 |

---

## 1. 何を作るか（範囲）と合格の線

### 1.1 作るもの

```
人 ── #/asset/<id>/recipe ──▶ 記録（recipe_record）＋判定（exact / approx / impossible ＋理由）
                              │  L1 / L2 / L3 を選ぶ
                              ▼
                    書き出し前の検査（/object_info）── impossible なら止める
                              ▼
                    印つきのグラフを書き出す（<data>/recipes/…、seed 違いは N ファイル＋manifest）
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
| **1** | **条件が記録され、判定と理由が出る** | 実データの複製で `POST /api/assets/{id}/recipe` を **グラフありの 1 枚**と**グラフ無しの 1 枚**（`prompt` チャンクの無い PNG。**（点検 D-1）実データ 263 枚は全部 PNG で、JPEG は無い**ので、JPEG は合成で試す）に打つ → `GET /api/assets/{id}/recipe` が `status` と `reasons` を返す。グラフ無しは **`impossible` ＋ `missing`** | 2 枚とも 200。グラフ無しが `impossible`、グラフありが `exact` か `approx`（`reasons` の中身が §0.6 の**記録時の 7 語**） |
| **2** | **実データ 263 枚で判定が付く**（**（点検 A-3）数を書く**） | `tools/probe_p7.py --judge` が 263 枚に記録を作り、`{exact, approx, impossible}` の内訳を出す | **この環境・この版で `exact` 182 / `approx` 1 / `impossible` 80**（`impossible` は `prompt` チャンクの無い 80 枚）。**（P7-1 の実測で確定。点検の「183 / 0 / 80」は誤り）** `approx` の 1 枚は **ja2en の画像**で、`CLIPTextEncode` はあるのに**文字列が分からない**（`StringConcatenate` → `TextGenerate` のリンク参照。**英訳は PNG に残らない**）ため `text_not_captured` が付く——**これは規則どおりで正しく、この記録の存在理由そのもの**（監視で英訳を捕まえて `exact` に上がる）。**環境が変わったときは「`impossible` ≥ 80、超えた分の理由は `node_missing` か `unresolved`」**と読み替える |
| **3** | **印つきのグラフを書き出せる** | グラフありの 1 枚で `POST /api/recipes/{id}/export {seeds:["1","2"], marker:true}` → **`<data>/recipes/<recipe_id>/<attempt_id>/seed-1.json`** と `seed-2.json` と `manifest.json` ができ、各グラフの `SaveImage.filename_prefix` が **`repro-<attempt_id>/seed-<seed>`** | 3 ファイル。印が 2 つとも入る。**`manifest.json` が `schemas/recipe-manifest.schema.json` を本物の `jsonschema` で通る** |
| **4** | **印を付けても再現キーが変わらない**（**（点検 A-3）mode を明記する**） | **`mode=rerun_graph` で seed を固定して**書き出し、記録のグラフと書き出したグラフから `recipe_hash` を計算して比べる。**`mode=pin_text` では `TextGenerate` を持つグラフだけ**が変わる（実測: 183 枚中 **1 枚**）ことも見る | **`rerun_graph` なら鍵が記録と一致（183/183 相当）**。`pin_text` で変わったぶんの理由が **`text_pinned`** になっている |
| **5** | **前提が外れたら印を付けずに理由を出す** | `filename_prefix` がリンクのグラフ・`SaveImage` が無いグラフ・`filename_prefix` を持たない保存ノードがあるグラフを**合成で作って**書き出す（`tools/probe_p7.py --marker-preconditions`） | 3 つとも**印なし**で書き出され、`marker_skip_reason` が **`前提1` / `前提2` / `前提3`**（**空白なし。DDL の `CHECK` が正**。点検 E-1）を指す。**画面に 1 行出る** |
| **6** | **書き出した印から結果が紐付く**（**（点検 G-6-(a)）これが合格の門**） | `tools/probe_p7.py --watch` が**偽の ComfyUI**（`/api/jobs` と `/api/jobs/{id}` を返す小さな HTTP サーバ）を立て、**印つきの出力を持つ job** を流す → 監視が拾い、`recipe_export_result` が `matched_by='marker'` で 1 行できる。**その `outputs` が指す実ファイル（合成 PNG。`prompt` に印つきの `filename_prefix`）を `comfyui.output_dir` に置き**、**登録・鍵・指標・`seed_changed` まで通す**。**印の無い job では作られない** | 2 ケースとも期待どおり。**タグ付けの job（`outputs_count: 0`）は詳細を取らずに弾かれる**。**`in_progress` を 1 件混ぜても既読が進まない** |
| **7** | **人が合否を記録でき、消えない** | `POST /api/recipes/{id}/exports/{attempt_id}/results/{result_id}/verdict {verdict:'close', note:'…'}` → `GET /api/recipes/{id}/exports` に残る。**元の `recipe_record` は変わらない**（前後で `GET /api/assets/{id}/recipe` を突き合わせ） | 合否が残る。記録の `recipe_hash` / `record_json` が**バイト一致** |
| **8** | **画面が 2 つ動く** | `#/asset/<id>/recipe`（判定・理由・レベル・書き出しの束・結果・合否）と `#/recipes`（一覧・プリセット・コピー）を **3 窓（1400×900 / 1200×800 / 1920×1080）**で開き、`gui_layout.mjs --screen recipe` / `--screen recipes` が `overflow=0` | 3 窓とも ok。**適用ボタンが無い**（`gui_smoke` で固定） |
| **9** | **実データの 1 枚で通しで動く**（**（点検 G-6-(a)）任意の確認に格下げ**） | 実データの複製で 1 枚を書き出し → 利用者が ComfyUI にドロップして **1 回 Queue** → 監視が結果を拾い、指標と合否の行が出る | **任意**（利用者に 1 回頼む。**門ではない**。§7 の但し書き。生成はこのツールがしない）。**利用者が 1 回回したら §J として結果を追記する** |
| **10** | **回帰と `GET` の無副作用** | `uv run --no-sync pytest -q`（**285 件＋新規**）・`gui_smoke`・`gui_layout` の**既存 6 画面**。`GET` の前後で `recipe_*` の行数と **`<data>/recipes/`** のファイル一覧が変わらない | すべて緑。`GET` で 1 バイトも書かない |

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
| 監視の口 | `GET /api/jobs?limit=N` → `{jobs, pagination:{offset, limit, total:731, has_more}}`。**（点検 E-1）一覧にある欄（実測）**: `id` / `status` / `create_time` / `execution_*` / `outputs_count` / **`priority`** / **`previewable_outputs_count`**、画像の job には **`preview_output {filename, subfolder, type, nodeId, mediaType}`** / `workflow_id`。`GET /api/jobs/{id}` が **`workflow.prompt`（API グラフ）・`outputs`・`execution_status`** を返す（`extra_data` は `client_id` / `comfy_usage_source` / `create_time` / `extra_pnginfo`。**UI 起点なら `extra_pnginfo` がある**）。**`?status=completed` が効く**（実測。点検 B-3-2） |
| 監視の落とし穴 | `/api/jobs` には**タグ付けの job も並ぶ**（`outputs` が `{"2": {"tags": [...]}}`。実測）。**画像を出す job だけ**を扱う必要がある |
| `/history` の形 | entry のキーは `prompt` / `outputs` / `status` / `meta`。`prompt` は**5 要素のリスト**（`[2]` = API グラフ・`[3]` = extra_data・`[4]` = 実行対象ノード）＝ 本文 §2-4 のとおり |
| 環境の写しの口 | `/system_stats`・`/object_info`・`/api/customnode/installed`・`/experiment/models/{diffusion_models,loras}`（`name` / `pathIndex` / `size` / `modified` / `created`）は**すべて 200** |
| **`userdata` への設置** | `POST /api/userdata/workflows%2F<名前>.json` → **200**（一覧に出る）。`DELETE` 同じ道 → **204**（消える）。**探り 1 件を置いて消した**（利用者のワークフローは触っていない）。→ §3.1 C の経路は**生きている**（P3 で使える） |
| `execution_cached` | `/api/jobs/{id}` の `execution_status.messages` に `execution_cached` が出る（**同じグラフの再投入は実行されない**）。**（点検 B-3-3）ただし 731 件すべてに出る**（当たらない job は `nodes: []`）ので、**「保存ノードの id が `execution_cached.nodes` に含まれるとき＝新しい画像は出ていない」**と定義する（§0.9） |
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
  graph_kind      TEXT,                   -- 'ui' | 'api'（（点検 D-3）`provenance()` の `graph_format` をそのまま入れる。
                                          --  1 列に 2 値は入らないので「api+ui なら 'ui' も残る」は誤り）
  record_json     TEXT NOT NULL,          -- §4.1 の全項目（取れなかった項目は null で明示）
  final_prompt    TEXT,
  final_prompt_source TEXT CHECK (final_prompt_source IN ('png_literal', 'reconstructed', 'manual')),
  captured_text   TEXT,
  captured_source TEXT,                   -- 'comfyui_history' | 'sidecar' | 'textgenerate' | 'manual'
  text_probe      TEXT,
  env_snapshot    TEXT NOT NULL,          -- ComfyUI 版・ノード版・GPU・dtype・使ったノードの宣言・モデルの size/mtime
  status          TEXT NOT NULL CHECK (status IN ('exact', 'approx', 'impossible')),
  reasons         TEXT,                   -- ★（点検 A-3）**記録時の 7 語だけ**（text_pinned など mode 依存は書き出し時へ）
  actor           TEXT NOT NULL CHECK (actor IN ('human', 'agent')),
  client_token    TEXT,                   -- ★追加: 再送の鍵（同じ画像の再送で行を増やさない）
  created_at      TEXT NOT NULL
);
-- ★（点検 C-1 / G-5）**画像 1 枚に 1 記録**（mode は「既定＝画面の初期値」であって、行を分ける軸ではない）
CREATE UNIQUE INDEX IF NOT EXISTS ux_recipe_source ON recipe_record(source_asset_id);
CREATE UNIQUE INDEX IF NOT EXISTS ux_recipe_token ON recipe_record(client_token) WHERE client_token IS NOT NULL;
CREATE INDEX IF NOT EXISTS ix_recipe_created ON recipe_record(created_at DESC, id DESC);

-- ★（点検 A-2b）**書き出しの束（試行）**。1 回の書き出しの単位。
-- manifest・印の理由・検査の結果・seed_node（C-2）・client_token（再送の冪等性）をここに 1 行で持つ
CREATE TABLE IF NOT EXISTS recipe_export_attempt (
  attempt_id    TEXT PRIMARY KEY,         -- 印に使う短い id。**8 文字以上の [a-z0-9]**（D-12）
  recipe_id     TEXT NOT NULL REFERENCES recipe_record(id),
  mode          TEXT NOT NULL CHECK (mode IN ('pin_text', 'rerun_graph', 'manual_text')),
  client_token  TEXT,                     -- ★再送の鍵（同じ token の再送は**同じ attempt_id** を返す）
  marker_skip_reason TEXT CHECK (marker_skip_reason IN ('前提1', '前提2', '前提3')),
  checked_json  TEXT,                     -- 書き出す前の検査の結果（status / reasons / inspected / notes）
  manifest_path TEXT,
  export_dir    TEXT NOT NULL,            -- <data>/recipes/<recipe_id>/<attempt_id>/
  seed_node     TEXT,                     -- ★（点検 C-2）どのノードの seed を書き換えたか
  created_at    TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_attempt_token
  ON recipe_export_attempt(client_token) WHERE client_token IS NOT NULL;
CREATE INDEX IF NOT EXISTS ix_attempt_recipe ON recipe_export_attempt(recipe_id, created_at DESC);

-- 書き出しの中の 1 ファイル（seed 違いは seed ごとに 1 行）
CREATE TABLE IF NOT EXISTS recipe_export (
  id            TEXT PRIMARY KEY,
  attempt_id    TEXT NOT NULL REFERENCES recipe_export_attempt(attempt_id) ON DELETE CASCADE,
  seed          TEXT,                     -- 10 進の文字列（符号なし 64bit は SQLite の符号付き INTEGER に入らない）
                                          -- seed 無し（KSampler の無いグラフ）は NULL（印は …/noseed。G-4）
  recipe_hash   TEXT NOT NULL,            -- 書き出したグラフの再現キー（seed を変えたときだけ記録と違う）
  graph_path    TEXT NOT NULL,
  marker        TEXT,                     -- ★（点検 A-2a）**NULL 可**。'repro-<attempt_id>/seed-<seed>'
  marker_skip_reason TEXT CHECK (marker_skip_reason IN ('前提1', '前提2', '前提3')),
  created_at    TEXT NOT NULL,
  -- ★（点検 A-2a）**印か理由の片方だけ**が入る
  CHECK ((marker IS NULL) <> (marker_skip_reason IS NULL))
);
-- ★（点検 A-2c）**seed が NULL でも一意**にする（前の版は `(attempt_id, seed)` で、NULL のとき UNIQUE が効かず
-- 同じ束に 2 行入った。実測で確認）。**式の索引**で NULL を '' に寄せる
CREATE UNIQUE INDEX IF NOT EXISTS ux_export_attempt_seed
  ON recipe_export(attempt_id, COALESCE(seed, ''));
-- **`ix_export_attempt` は作らない**（点検 C-2 / G-4。主キーの前置と重なる）

-- 結果（監視で入るか、人が登録する。1 回の書き出しに複数枚あり得る）
CREATE TABLE IF NOT EXISTS recipe_export_result (
  id              TEXT PRIMARY KEY,
  export_id       TEXT NOT NULL REFERENCES recipe_export(id),
  prompt_id       TEXT,                   -- 監視が見つけた job id（= prompt_id）。NULL = 手動登録
  result_asset_id TEXT REFERENCES asset(id) ON DELETE SET NULL,   -- ★（点検 C-3 / G-3）画像を消しても結果は残す
  matched_by      TEXT NOT NULL CHECK (matched_by IN ('marker', 'manual', 'conditions')),
  result_hash     TEXT,                   -- 結果 PNG の prompt チャンクから計算した再現キー（§4.3）
  same_hash       INTEGER NOT NULL DEFAULT 0,
  ssim REAL, phash_distance INTEGER, changed_fraction REAL, mean_abs REAL,
  seed_changed    INTEGER NOT NULL DEFAULT 0,   -- ★追加: 結果の seed が書き出しと違う（§4.7.2 の 2）
  verdict         TEXT CHECK (verdict IN ('same', 'close', 'different', 'failed')),
  verdict_at      TEXT,                   -- ★（点検 C-4 / G-2）いつ
  verdict_actor   TEXT CHECK (verdict_actor IN ('human', 'agent')),   -- ★誰が（上書き。履歴は持たない）
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
  source_asset_id TEXT REFERENCES asset(id) ON DELETE SET NULL,   -- ★（点検 C-3 / G-3）
  record_json     TEXT NOT NULL,
  actor           TEXT NOT NULL CHECK (actor IN ('human', 'agent')),   -- ★追加
  created_at      TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_preset_created ON preset(created_at DESC, id DESC);

-- 監視の既読位置（`design.md` §5.5 の DDL。**現物に無いので P7 で作る**）
CREATE TABLE IF NOT EXISTS watcher_state (
  name           TEXT PRIMARY KEY,        -- 'comfyui'（将来の監視を増やせるように名前で持つ）
  last_prompt_id TEXT,                    -- 最後に処理した job id（**表示用**。UUID なので順序の基準には使わない）
  baseline_create_time INTEGER,           -- ★（点検 B-3-1）既読の基準。**ms**（一覧の create_time）
  last_polled_at TEXT,
  enabled        INTEGER NOT NULL DEFAULT 0,
  updated_at     TEXT                     -- ★追加: いつ触ったか（`design.md` の DDL に無い）
);
```

- **`CHECK` を使う**（既存の書き方。`db.py` は 11 か所で使っている）。
- **`ALTER TABLE` は使わない**（新しい表だけなので `CREATE TABLE IF NOT EXISTS` で足りる）。
- ★印が**本文に無い追加**（§0.12・§0.15 に対応）。**足すだけで、本文の必須は変えない**。
- **（点検 C-3 / G-3）削除との関係**: `preset.source_asset_id` と `recipe_export_result.result_asset_id` は
  **`ON DELETE SET NULL`**（画像が消えても条件と結果は残す）。**`recipe_record.source_asset_id` は既定（RESTRICT）のまま**にして、
  **P8（重複・削除）の設計に「記録のある画像の削除は、記録ごと消すか断るか」を申し送る**（1 行）。
  前の版は何も書いておらず、**実測で `FOREIGN KEY constraint failed` になった**。

### 2.2 索引の意図

| 索引 | 何を速くするか |
| --- | --- |
| `ux_recipe_source` | 「この画像の記録」を 1 回で引く（**（点検 C-1 / G-5）画像 1 枚に 1 記録**） |
| `ux_recipe_token` | 記録の再送で行を増やさない（P6 と同じ部分索引） |
| `ux_attempt_token` | **（点検 A-2b）書き出しの再送**で束を増やさない（同じ `client_token` は同じ `attempt_id`） |
| `ux_export_attempt_seed` | 同じ `attempt_id` の同じ seed を 2 回作らせない（**再送の冪等性**。**（点検 A-2c）`COALESCE(seed,'')` の式の索引**なので seed 無しでも効く） |
| `ux_result_asset` | 同じ結果画像を同じ書き出しに 2 回入れない |
| `ix_recipe_created` / `ix_attempt_recipe` / `ix_result_export` / `ix_preset_created` | 一覧（新しい順）と、束・書き出し・結果の展開 |

- **（点検 C-0）`EXPLAIN QUERY PLAN` で 6 つの問い合わせが意図した索引を使うことを実測済み**
  （`ux_recipe_source` / `ux_recipe_token` / `ix_recipe_created` / `ix_attempt_recipe` / `ix_result_export` /
  `ux_export_attempt_seed`）。束の表を足したので、**`ix_attempt_recipe` / `ux_attempt_token` も §8.1 の 22 で見る**。

### 2.3 グラフの置き場（§0.4 の決め）

- `<data>/workflows/<sha256>.json`（**画像の内容ハッシュ**が名前。同じ画像なら同じファイル）。
- **（点検 D-7）`<data>/recipes/<recipe_id>/<attempt_id>/seed-<seed>.json`**（**書き出し**。印つき）。
  **seed 無しの束は `noseed.json`**（G-4）。
- **`<data>/recipes/<recipe_id>/<attempt_id>/manifest.json`**（§4.7.3。**契約は `schemas/recipe-manifest.schema.json`**）。
- **P5 の `<data>/export/review.json`（単数）と紛らわしくない**ように、**P7 は `<data>/recipes/` を使う**
  （前の版の `<data>/exports/` は単数と並んで読み分けにくかった）。
- **監視が取り寄せた結果の控え**は **`<data>/results/<sha256>.png`**（`comfyui.output_dir` が当たらないときだけ。§0.9）。

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
| `POST /api/recipes/{id}/check` | 画面・エージェント | **書かない**（検査だけ。§4.7 手順 4） | `{mode?}` → `{status, reasons, inspected, notes, object_info_age_ms}`。**（点検 B-2）`/object_info/{class_type}` を使った `class_type` の数だけ引く**（キャッシュの有無を `object_info_age_ms` で出す） |
| `POST /api/recipes/{id}/export` | **人** | 書く（**束 1 行＋`recipe_export` N 行**＋グラフ N ファイル＋manifest） | `{mode?, seeds?\|count?, marker?, client_token?}`。**`seeds` は文字列の配列**（`["1","2"]`。点検 B-6）。**`human` 以外 403**。**（点検 A-2b）`client_token` の再送は同じ `attempt_id` を返す** |
| `GET /api/recipes/{id}/exports` | 画面・エージェント | 書かない | **束（`recipe_export_attempt`）と、その中の書き出し・結果**を返す（1 回で両方。画面が 1 往復で描けるように） |
| `POST /api/recipes/{id}/exports/{attempt_id}/results` | **人** | 書く（`recipe_export_result` 1 行・`matched_by='manual'`） | `{result_asset_id}`。**印が無い結果を人が紐付ける口**（本文 §4.7.1 の表） |
| `POST /api/recipes/{id}/exports/{attempt_id}/results/{result_id}/verdict` | **人** | 書く（`verdict` / `note`） | §4.8。**消えない形で残す** |
| `POST /api/recipes/{id}/presets` | **人** | 書く（`preset` 1 行） | `{name, note?}`。`record_json` は記録から写す |
| `GET /api/presets` | 画面 | 書かない | 一覧（`created_at DESC`） |
| `GET /api/presets/{id}/record` | 画面 | 書かない | **人が読める要約**（§0.12） |
| `GET /api/watcher` | 画面 | 書かない | `{enabled, last_prompt_id, baseline_create_time, last_polled_at, last_error}` |
| `POST /api/watcher/start` / `/stop` | **人** | 書く（`watcher_state`） | **（点検 C-6）`{base_url?}` を受ける**（既定は設定 `comfyui.url`。**設定は `start` のたびに読む**）。**`human` 以外 403**。既に同じ状態なら 200（冪等） |

- **（点検 D-11）`Host` / `Content-Type` の 403 を確かめる `POST` は 7 本**: `POST /api/assets/{id}/recipe`・
  `POST /api/recipes/{id}/check`・`POST /api/recipes/{id}/export`・`POST …/results`・`POST …/verdict`・
  `POST /api/recipes/{id}/presets`・`POST /api/watcher/start`（`/stop` も同じ middleware の下）。
- **（点検 E-2）`POST /api/recipes/{id}/presets` の形は `design.md:698-699` の `POST /api/presets {name, note?, source_asset_id?}` と違う**
  （P7 は「記録から写す」ので `source_asset_id` を受けない）。**`design.md` を直す側**として §0.15 / §12-7 に挙げる。

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
→ 201 {"attempt_id": "r7k2m4", "export_dir": "<data>/recipes/<recipe_id>/r7k2m4",
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
| 付いた | `verdict` が入っている（**（点検 C-4 / G-2）`verdict_at` / `verdict_actor` も入る**） | 値を出し、**変えられる**（上書き。**履歴は持たない**＝`recipe_export_result` は台帳ではない） |

- **（点検 C-4 / G-2）「消えない」の定義**: **「再起動・再読込で失われない」**（上書きはする）。
  いつ・誰がを `verdict_at` / `verdict_actor` に残す（前の版は上書きだけと書いていて、
  `design.md:1449` の「消えない形で」・`frontend-design.md` §4.11 の「記録は消えない形で残る」と
  読み合わせて**意味が曖昧だった**）。

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
- **印を付けられなかったとき**は「印を付けられません」＋理由（`前提1` / `前提2` / `前提3`。**字は空白なし**）を 1 行で出し、
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
| §6 文言 | 「印を付けられません（理由: …）」「**1 ファイルにつき Queue は 1 回**。2 回目を押す前に `control_after_generate` を `fixed` にする（`before` なら 1 回目から変わる）」「結果が出たら監視が拾います」「合否は当時の絵と一致するかです（キープ / ボツとは別）」「保存先の名前は `__OUTPUT_PREFIX__` のままです」「出力フォルダに `repro-*` のフォルダが増えます」 |
| §11 細部 | 監視のポーリング（2 秒。**画面を閉じても回る**）、`#/recipes` の並び、コピーの文面 |

---

## 6. 契約

### 6.1 `schemas/recipe-manifest.schema.json`（新規）

```jsonc
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "urn:image-reviewer:schema:recipe-manifest",
  "type": "object", "additionalProperties": false,
  "required": ["schema", "abi", "attempt_id", "recipe_id", "recipe_hash", "mode", "export_hashes", "seeds", "source", "notes"],
  "properties": {
    "schema": {"const": "urn:image-reviewer:schema:recipe-manifest"},
    "abi": {"type": "string", "pattern": "^[0-9]+\\.[0-9]+$"},
    "generated_at": {"$ref": "#/$defs/Timestamp"},
    "attempt_id": {"type": "string"},
    "recipe_id": {"type": "string"},
    "mode": {"type": "string", "enum": ["pin_text", "rerun_graph", "manual_text"],   // ★（点検 B-5）
             "description": "この束を書き出したレベル"},
    "recipe_hash": {"type": "string", "description": "記録の再現キー（sha256:…）"},
    "export_hashes": {"type": "object", "description": "**seed（10 進の文字列）または `noseed`**（seed 無しの束。点検 G-3）→ 書き出したグラフの再現キー",
                      "additionalProperties": {"type": "string", "pattern": "^sha256:"}},   // ★（点検 B-5）
    "marker_skipped": {"type": ["string", "null"], "enum": ["前提1", "前提2", "前提3", null],   // ★（点検 B-5）
                       "description": "印を付けなかった理由（付けたなら null）"},
    "source": {"type": "object", "additionalProperties": false,   // ★（点検 B-5）元画像と条件の要約
               "required": ["asset_id", "sha256", "filename", "model", "seed", "size"],
               "properties": {"asset_id": {"type": "string"}, "sha256": {"type": "string"},
                              "filename": {"type": "string"},
                              "model": {"type": ["string", "null"]},
                              "seed": {"type": ["string", "null"]},   // 文字列（点検 B-6）
                              "size": {"type": ["integer", "null"]}}},
    "seeds": {"type": "array", "minItems": 1, "items": {      // ★（点検 B-5）seed 無しの束は seeds: [{"seed": null, …}]
      "type": "object", "additionalProperties": false,
      "required": ["seed", "file", "expected_prefix"],
      "properties": {"seed": {"type": ["string", "null"]}, "file": {"type": "string"},
                     "expected_prefix": {"type": "string", "description": "前方一致で見る（連番の桁数は実装依存）"}}}},
    "output_dir": {"type": ["string", "null"], "description": "ComfyUI の出力先（分からなければ null）"},
    "notes": {"type": "object", "additionalProperties": false,   // ★（点検 B-5）型つきにする
              "required": ["status", "reasons", "inspected", "instruction"],
              "properties": {"status": {"type": "string", "enum": ["exact", "approx", "impossible"]},
                             "reasons": {"type": "array", "items": {"type": "string"}},
                             "inspected": {"type": "boolean"},
                             "instruction": {"type": "string", "description": "利用者への手順 1 行"}}}
  },
  "$defs": {"Timestamp": {"type": "string", "pattern": "^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(\\.[0-9]+)?Z$"}}
}
```

- **`abi` は文字列**（`annotation-export` と同じ。点検 D2 の型に揃える）。
- **`seeds[].expected_prefix` は前方一致**であることを説明に書く（完全一致を期待値にしない。§4.7.3）。
- **（点検 B-5）`notes` を型つきにした**（前の版は「説明」だけで型が無く、§0.12「manifest に元画像・条件の要約を出す」・
  §3.3「manifest に `status` / `reasons` を入れる」・§4.7.3「`notes` に検査の結果」を**どれも守れなかった**。
  実測: `additionalProperties: false` なので `mode` を足すと落ち、逆に `notes` にでたらめな `status` を入れても通った）。
  **`mode` / `marker_skipped` / `source`（要約）**も足した。`export_hashes` の値は **`sha256:` で縛る**。
  **seed 無しの束（G-4）は `seeds` に `{"seed": null, …}` を 1 件入れる**（`minItems: 1`）。

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
| `POST /api/assets/{id}/recipe` | **p95 300 ms 以内**（20 回。グラフありの 1 枚） | PNG の先頭を読む（`png_meta` は `cap` バイトだけ）＋ **（点検 B-2）`/object_info/{class_type}` を使った `class_type` の数だけ**引く（全体は引かない）。**見込みは数 ms**（`/object_info/{ct}` は 0.7〜3.0 KB・**0 ms** 実測。グラフの異なり `class_type` は **10 前後**）。**P7-1 で測って記録する** |
| `POST /api/recipes/{id}/check` | **p95 50 ms 以内**（**（点検 B-2）目標を書き直した**。前の版の「初回 500 ms」は全体の `/object_info` を引く前提で、実測 0.41〜0.91 秒では出なかった） | `/object_info/{class_type}` を ≤ 20 回（合計数十 KB・数 ms）＋ class_type ごとに **60 秒キャッシュ**。**P7-2 で測って記録する** |
| `POST /api/recipes/{id}/export`（8 seed・印つき） | **p95 1 秒以内** | グラフの JSON を 8 回書くだけ（生成はしない）。**未計測**（P7-2 で測る） |
| 監視 1 周期（新規 0 件のとき） | **50 ms 以内**（**ComfyUI の** `/api/jobs?limit=50&status=completed` 1 回。**実測: 中央 4.5 ms**） | **（点検 B-2 / E-8）実測済み**（一覧は中央 4.5 ms、`/api/jobs/{id}` の詳細は 1.4 ms） |
| 監視 1 周期（新規 1 件・画像 1 枚） | **2 秒以内**（次の周期に間に合う。詳細 ＋ PNG の登録 ＋ 指標） | 画像 1 枚の登録は P1 の走査と同じ（ハッシュ＋サムネ）。**未計測** |
| 再現キーの計算（1 グラフ） | **10 ms 以内**（200 ノード程度） | 純関数（JSON の正規化＋SHA-256）。**（点検 B-2 / E-8）実測: 平均 0.03 ms / グラフ**（`hash_proto.py`。183 枚で distinct 183・mean 0.03 ms） |
| `/object_info` の取得費（参考） | — | **（点検 B-2 / E-8）実測**: 全体は **2,394,596 バイト・1,212 ノードで 0.41〜0.91 秒**（keep-alive でも 0.41〜0.44 秒）、`json.loads` に 12〜17 ms。**`/object_info/{class_type}` は 0.7〜3.0 KB・0 ms** |
| 表の行数 | 記録は**画像 1 枚に 1 つ**（263 枚で 263 行）。書き出しは**その N 倍** | 結果は**書き出した分だけ**（人が回した分） |
| 書き出しのファイル数 | 1 回の書き出しで **seed の数＋1**（manifest） | 64 枚上限なら 65 ファイル |

- **未計測の数値は「未計測」と書き、測ったらこの表を書き換える**（P9 で全部を裏づける）。
  **（点検 B-2 / E-8）未計測だった 3 行は本点検の実測で埋まった**（`/object_info` 全体・一覧・詳細・鍵）。
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
`recipe_*` の行数と `<data>/recipes/` のファイル一覧が**変わらない** | §0.10（P5 の C8/G2） |
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
| 29 | 索引を外す | `EXPLAIN QUERY PLAN` に `ux_recipe_source` と `ix_attempt_recipe` が出る | P5 の D1 の教訓 |
| 30 | 結果の seed の確認を外す | 結果の PNG の `KSampler.seed` が書き出しと違うとき `seed_changed=1` | §4.7.2 の 2 |

- **実データ依存のテストを書かない。** 合成の PNG（Pillow で作り `prompt` チャンクを入れる）と、
  **`/api/jobs` の偽サーバ**（`tests/` の中の小さなスレッド）で回す。
- **`/object_info` はフィクスチャ**（テストで ComfyUI を叩かない。**実機は `probe_p7.py`**）。

**（点検 F）点検で「守れない」と判定された物への手当て**（§8.1 の表に足す）:

| # | 壊すと落ちるもの | 何を確かめるか |
| --- | --- | --- |
| **31** | 動的コンボの展開（A-1） | `TextGenerate` 入りの**合成グラフ**と、実物から写した `/object_info`（`KSampler` / `SaveImage` / `TextGenerate` / `CLIPTextEncode` / `UNETLoader` の 5 ノード分）で、**`TextGenerate.sampling_mode.temperature` が `unresolved` を出さない**。**展開を外すと落ちる**。別に「本当に無いキー（`KSampler.foo`）は `unresolved`」も置く |
| **32** | 記録時と書き出し時の理由の分離（A-3） | 記録の `reasons` に **`text_pinned` / `llm_nondeterministic` / `manual_step` が出ない**（書き出しの `checked_json` にだけ出る）。**`text_not_captured` と `text_pinned` が同時に出ない**（L1 は `final_prompt` が分かるときだけ）。`CLIPTextEncode` を持たないグラフに **`text_not_captured` が付かない** |
| **33** | 鍵はグラフだけの純関数（A-3） | 同じグラフで **`(size, mtime)` を変えても鍵が変わらない**（`os.utime` で変えて確かめる） |
| **34** | seed 無しでも一意（A-2c） | 同じ `attempt_id` で **seed 無しの書き出しを 2 回** → **1 行**（`COALESCE(seed,'')` の索引を外すと 2 行になる） |
| **35** | 印と理由は片方だけ（A-2a） | `marker` と `marker_skip_reason` の**両方**／**どちらも無い**を入れると落ちる（`CHECK`） |
| **36** | 書き出しの再送（A-2b） | 同じ `client_token` で 2 回書き出す → **同じ `attempt_id`**・**束は 1 行**・ファイルも増えない |
| **37** | `GET /api/recipes` の頁送り（C-7） | **2 頁の重複ゼロ・合計が `limit=1000` と一致**（P4-3 の再確認で `GET /api/tags` が踏んだ罠） |
| **38** | 一覧の `outputs_count: 0` で弾く（B-3-4） | 偽サーバが `outputs_count: 0` の job（タグ付け）を返すとき、**詳細を取らず**既読だけ進む |
| **39** | `in_progress` を既読にしない（B-3-2） | 偽サーバに **`in_progress` の job を 1 件混ぜ**、**基準が進まない**こと |
| **40** | 線 6 を本物の PNG で（F の追加・G-6） | 偽サーバの `outputs` が指す**実ファイル**（合成 PNG。`prompt` に印つきの `filename_prefix`）を `comfyui.output_dir` に置き、**登録・鍵・指標・`seed_changed`** まで通す |
| **41** | manifest の型（B-5） | 本物の `jsonschema` で `notes` の `status` にでたらめを入れると**落ちる**。`mode` / `marker_skipped` / `source` が**通る**。`export_hashes` の値が `sha256:` でないと落ちる |
| **42** | 削除との関係（C-3） | `preset.source_asset_id` / `recipe_export_result.result_asset_id` の画像を消しても**行が残る**（`SET NULL`）。`recipe_record.source_asset_id` の画像は**消せない**（RESTRICT） |
| **43** | 記録は画像 1 枚に 1 つ（C-1） | 同じ画像に `mode` を変えて 2 回記録 → **1 行**（2 回目は 200 で既存を返す） |

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
| **P7-0** | v6 の移行（**6 表**。`recipe_export_attempt` を足したので 5 → 6。点検 E-3）・`recipe-manifest` 契約・`review.json` を変えないことのテスト | 既存が緑。v1/v5 → v6・3 回呼び | 表と契約（P6-0・P4-0 と同じ） |
| **P7-1** | `recipe_hash`（純関数）・`record_json`・`env_snapshot`・判定・グラフの置き場・記録の口 | 線 1・2 | 記録と判定（**再現キーの除外**が主眼） |
| **P7-2** | 検査・L1/L2/L3・印・seed 違い・manifest | 線 3・4・5 | 書き出し（**印の前提**と**検査**） |
| **P7-3** | 監視の最小形・印の照合・指標・sidecar・合否 | 線 6・7 | 監視と紐付け（**画像を出さない job** と**再起動**） |
| **P7-4** | 画面 2 つ（`#/asset/<id>/recipe`・`#/recipes`）・`frontend-design.md` の追記 | 線 8・10 | 画面（**実物の Chrome**。軽い DOM では見えない穴） |

- **P7-0 は機能を足さない**（表と契約だけ）。**P5・P6・P4 と同じ形**。
- 各段で **`pytest`・`gui_smoke`・`gui_layout`（既存 6 画面＋新しい 2 画面）を緑に保つ**。
- **`design.md` 本体への反映は全段の後**に 1 回（§12 の一覧）。

---

### 0.18 P7-4（画面）で決めたこと

- **`recipe_export_result.fetched` を足した**（`GET /view` で `<data>/results/` に取り込んだか）。
  表は空だったので **v7 は作らず v6 の DDL を直し**、**既に v6 の DB には `_top_up_v6` が
  `PRAGMA table_info` を見て `ALTER TABLE ADD COLUMN`** する（P7-0 の C-1 / G-2 と同じ判断）。
  `GET …/exports` と `watcher.results()` が **`fetched` を返す**（画面が「取り込み / 参照」を出す）。
- **`GET /api/recipes` に `?status=` を足した**（画面 §5.4 の「判定で絞る」）。語彙は
  `exact` / `approx` / `impossible` だけで、外れたら **422**（`CHECK` に当てて 500 にしない）。
- **理由の語は画面でも混ぜない**（記録時 7 語 / 書き出し時 3 語。監査 A-3 の帰結）。
- **`#/asset/<id>/recipe` は `#/asset/<id>` より先に判定する**（ルータの順序。後ろだと拡大が勝つ）。
- **来歴のすぐ下に「条件の記録」への 1 行**を出す（P6-2 の注記と同じ位置の考え方）。

## 10. 未確認とリスク（**推測で埋めない**）

| # | 未確認・リスク | どう扱うか |
| --- | --- | --- |
| 1 | **`/object_info` の大きさと取得時間**（検査の費用） | **未計測**。P7-2 で測って §7 に書く。60 秒キャッシュを入れる |
| 2 | **`control_after_generate` の復元**（**（点検 B-6 / E-5）実行で分かった**。前の版は「未確認」で止めていた） | **分かった**: frontend 1.53.10 は INT ウィジェットで名前が `seed` / `noise_seed` か `control_after_generate` が真なら **`addValueControlWidget(…, 'randomize')`** を付ける（宣言が文字列のときだけその値）。`KSampler.seed` の宣言は `true` なので**読み込み直後は `randomize`**。`Comfy.WidgetControlMode` の既定は **`after`**。→ **1 回目の Queue は書いた seed で走り、Queue の後で seed が変わる**。したがって**「`fixed` のまま Queue」は誤り**で、**「1 ファイルにつき Queue は 1 回。2 回目を押す前に `fixed` にする（`before` なら 1 回目から変わる）」**が正しい。**対策 2（結果の seed を読んで違えば出す）はそのまま要る** |
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

**（点検の結果）この 7 問は Fable の点検で**実行込みで**答えが出た**（`p7-review-report.md` の §I と A〜H）。
**指摘はすべて反映済み**（`p7-review-triage.md` に 1 行ずつ）。とくに:
- **1（P3 との依存）** は妥当とされた（監視の最小形を P7 に置く）。
- **2（鍵）** は試作（`hash_proto.py`）で**印を入れても 183/183 で不変**・**L1 で変わるのは 1/183** と分かり、
  **鍵は「グラフだけの純関数」**に直した（A-3）。
- **3（印の認定）** は **Windows の `subfolder` がバックスラッシュ**である実測に合わせて書き直し、
  **`attempt_id` を 8 文字以上**にした（B-4・D-12）。
- **4（監視）** は**既読の基準を `create_time` に**変え、**`execution_cached` の見分けを定義**した（B-3）。
- **5（テスト）** は §8.1 に **31〜43** を足した（F）。
- **6（気づいていない前提）** は点検が **A-1（動的コンボ）・B-1（出力の実体パス）・B-2（`/object_info` の費用）** を
  見つけた（いずれも反映済み）。
- **7（`design.md` の書き換え）** に **E の 11 件**を足した（§0.15 の 9〜14 と §12-7 の一覧）。

### 0.16 P7-0 の監査で確定したこと（2026-10-16。**推奨どおり**）

| # | 論点 | 決定 | 反映先 |
| --- | --- | --- | --- |
| **G-1** | `recipe_export_result.export_id` の `ON DELETE` | **`CASCADE`**（束を消すと結果も消える。束 → ファイルの `CASCADE` と揃える） | §2.1 |
| **G-2** | 語彙の `CHECK` 3 本 | **`graph_kind IN ('api','api+ui')`**・**`captured_source IN ('comfyui_history','sidecar','textgenerate','manual')`**・**`CHECK ((verdict IS NULL) = (verdict_actor IS NULL))`**（合否と人は対） | §2.1（**表が空のうちに入れる**。`ALTER` では後から足せない） |
| **G-3** | seed 無しの `export_hashes` の鍵 | **`"noseed"`**（`expected_prefix` とファイル名と同じ字） | §6.1 |
| **G-4** | `ix_export_attempt` | **作らない**（主キーの前置と重なる。P5 の D1 と同じ判断） | §2.2・§8.1-29 |
| **G-5** | 契約の `required` | **`generated_at` と `marker_skipped` を足す**（書き手は必ず両方書く） | §6.1 |
| **E-1** | `marker_skip_reason` の字 | **`'前提1'`（空白なし）が正**。設計の本文もこの字に揃えた（空白ありは `CHECK` で落ちる） | §0.7・§5.1・§8.1-7 |
| **E-2 / E-3** | 索引の名と表の数 | **`ix_attempt_recipe`**（`ix_export_recipe` は名残り）／**6 表**（`recipe_export_attempt` を足した） | §2.2・§8.1-29・§0.1・§9 |

### 0.17 P7-1 の監査で確定したこと（2026-10-16。**推奨どおり**）

監査の判定は「**直してから次へ**」。理由は「落ちているのは**端の経路**（ComfyUI 不通・選択肢に無いモデル・
同時投入・消えたグラフ）で、うち 2 つは指示書が名指しした観点の設計の約束」。**すべて直した**
（`tests/test_recipe.py` に 9 件のテストを足して **369 passed**）。

| # | 論点 | 決定 | 反映先 |
| --- | --- | --- | --- |
| **A-1 / G-1-(a)** | ComfyUI に繋がらないとき | **グラフだけで判定**し、**`system_stats` で打ち切る**（1 枚 20〜32 秒 → 1 往復）。**`node_missing` / `unresolved` を足さない**。**`inspected=false` を残す**。**`None`（引けなかった）と `{}`（引いたが無かった）を区別** | §0.6・§3.2（`collect_env` / `declaration_notes`） |
| **A-2 / G-2-(a)** | 選択肢に無いモデル / LoRA / VAE | **`reason_details[].fatal=true`** を足し、**`judge` が `impossible`** にする（**7 語は増やさない**） | §0.6（`_is_model_input()`） |
| **A-3 / G-4-(a)** | 同じ画像への同時 `POST` | **`INSERT … ON CONFLICT DO NOTHING` → 再 `SELECT` → 200**（錠を外部の往復まで広げない）。**1 本が新規・他は 200**で行は 1 | §0.10・§3.2 |
| **A-4** | 消えたグラフのファイル | **`GET` は `null`**（`graph_path` は**実体があるときだけ**返す）、**`POST` が PNG から作り直す** | §0.4・§0.10 |
| **B-1 / G-3-(a)** | グラフのファイル名 | **画像の内容ハッシュ**（`<data>/workflows/<画像の sha256>.json`）。`recipe_hash` を名前にすると、**同じ鍵で印だけ違う 2 枚目が 1 枚目を書き換える** | §2.3（`_asset_digest()`） |
| **B-2** | `text_not_captured` の条件 | **「文字列が分からない」ときだけ**（リテラル・結線先で解決できるなら**分かっている**） | §0.6（`text_unknown()`） |
| **B-3** | `inspected` と `notes` | **`record_json` に残す**（応答だけにすると `GET` で「確かめた `exact`」と区別できない）。**グラフ無しのときに「繋がらなかった」と出さない** | §3.2・§4.1 |
| **C-2** | `pin_text` の再送 | **`pin_text` でも貼られた英文を `final_prompt` に残す**（出所は `manual`）。同じ `client_token` の再送は **200** | §3.2（`record_doc()`） |
| **C-3** | `graph_kind` | **`record_json.graph_format` を書く**（`prompt` と `workflow` の両方がある PNG は **`api+ui`**。前の版は常に `api`） | §2.1（`CHECK` が生きる） |
| **G-5-(b)** | グラフ無しの `recipe_hash` | **空の SHA-256 のまま**（表は触らない）。**等価判定は `graph_path IS NOT NULL` を条件**にする。`check` / `export` は `status='impossible'` で止まるので実害は小さい | §0.5・§5.1 |
| **G-6-(a)** | `GET /api/recipes` | **要約だけ**（`record` / `env` は 1 枚の口）。一覧が重くならない | §3.6 |
| **C-1（持ち越し）** | 1 枚あたりの ComfyUI の `GET` | **目標（p95 300 ms）内**（実測: 口から 中央 128.7 ms・p95 196.4 ms・`/object_info/{ct}` 1,534 本）。`class_type` ごとの**短いキャッシュ（60 秒）**は**P7-2 以降**に回す | §7・§10 |
### 0.19 P7 を閉じる時の修正で確定したこと（2026-10-17。**P7-4 の監査と P7-3 の再確認**）

**P7-4 の監査（A-1〜A-3 / B-1 / C-1 / C-2 / C-4）**:

- **監視の「見る / 止める」は `actor` をヘッダで送る**（送らないと口が `agent` と見なして **403**。
  画面は無言で終わっていた）。**押した結果は 1 行で出す**。**検査は「実際に押す」**（`gui_layout --screen jobs`）。
- **拡大の「条件の記録」の入口は画像のすぐ下**（前は来歴の下で **top 1,250 px**。1,400×900 でも
  1,920×1,080 でも**スクロールしないと見えなかった**）。**`rcTop` / `rcVisible` を毎回測る**（今は 535 px）。
- **書き出し時の 3 語（`text_pinned` / `llm_nondeterministic` / `manual_step`）を束の欄に出す**。
  **口も混ぜない**: `checked.reasons` は**書き出し時の 3 語だけ**、記録時の語（`text_not_captured` など）は
  **`checked.notes`** に入れる（前の版は 1 つの配列に混ぜていた）。
- **結果の行に指標**（`same_hash` / `seed_changed` / `SSIM` / `pHash 距離` / 変化した画素 / 平均差）と
  **メモの入力**（**触ったときだけ送る**＝前のメモを消さない）。
- **manifest を開く口**（`GET /api/recipes/{id}/exports/{attempt_id}/manifest`。**書かない**）。
- **`?level=l1|l2|l3`** を読み、**L1 で英文が残っていなければ L2（`rerun_graph`）に落として 1 行出す**。
- **印を付けられないときは選べる**（**印なしで書き出す / やめる**。既定は「印なしで書き出す」）。

**P7-3 の再確認（B-1 / B-2 / C-1 / C-2 / G-5 / `texts` の二重計上）**:

- **sidecar は `<data>/sidecar`**（`capture.write_sidecar` と同じ形＝`<sha256>.json`・`schema` / `abi` /
  `captured_at` / `meta`）。**利用者の ComfyUI の出力フォルダには書かない**。
- **出力フォルダを黙って登録ルートに足さない**（実測 729 枚）。`GET /api/watcher` が **`needs_root`** を返し、
  **画面の「出力先を登録に足す」を人が押したときだけ**足す（`POST /api/watcher/add-root`）。
- **手で紐付ける口は `seed` を選べる**（省略したときだけ最小の seed）。
- **`note` を送らなかったら前のメモを消さない**（空文字を送れば消せる）。
- **`_top_up_v6` の `ADD COLUMN` にも `CHECK (fetched IN (0, 1))`** を付ける（**同じ v6 で形を 2 つ作らない**）。
- **英訳を数えるのは `_capture_texts()` だけ**（`text_captured`＝「PNG にグラフがある」で足すと二重計上）。
