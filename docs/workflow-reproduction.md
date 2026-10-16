# ワークフローの再現の設計

画像を「もう一度作れる」ようにするには何が必要か、を詰める。
実機で確かめた事実は [`comfyui-reproduction-findings.md`](comfyui-reproduction-findings.md)（ComfyUI 側、836 行）と
[`metadata-findings.md`](metadata-findings.md)（PNG 側）にある。この文書はその上での設計。

- 版: 0.2（実装前。**生成の実行はしない**方針に決まった版）
- 関連: [`design.md`](design.md) §7（来歴）、[`comparison.md`](comparison.md) §4（指標を共有）
- このツールの仕事: **記録・再利用・書き出し**。条件を残し、一覧し、コピーし、ComfyUI で開き、
  seed 違いのグラフを書き出し、名前を付けて保存する。**画像の生成は実行しない**（§6-1）。

---

## 1. 「再現」を 3 つに分ける

**これを混ぜると設計が壊れる。** 3 つは別の技術問題で、できることも失敗の仕方も違う。

| # | 何を再現するか | 出力 | 難しい所 |
| --- | --- | --- | --- |
| **① ワークフローを開く** | 人が見て直せるグラフ | ComfyUI のキャンバス | UI 形式のグラフが残っていないことがある |
| **② 同じ条件を記録し、作り直せる形で渡す** | グラフ JSON・プリセット | ファイルと画面 | 条件の記録漏れ、LLM の非決定性、モデルの差し替え |
| **③ 出てきた絵が当時と一致するか確かめる** | 合否と指標 | 数値と人の判断 | 「条件が同一」と「画素が同一」は別物 |

**② で画像の生成はしない。** このツールは**画像を作るために** ComfyUI の `/prompt` を投げない。
作るのは**投入できる形**（グラフ JSON、seed 違いの束、名前を付けた条件）までで、
**最後に投入するのは利用者**。だから「生成の進捗を追う」「生成の結果を API の応答で受け取る」
という工程はこの設計に無い（監視（§5）は、利用者が回した結果を**後から拾う**ためのもの）。

> **用語の注意（点検で指摘された衝突）**: 「実行しない」は**画像の生成**を指す。
> **タグ付け**（`IllustTagger`）と**訳し直し**（`TextGenerate`）には `/prompt` を使う。
> 正確な区別は [`design.md`](design.md) §6.3.2 にある。

**③ の定義を先に固定する。** **「完全」＝ 条件が同一であって、画素が同一ではない。**

- 条件が同一 ＝ 「完全」。画素が違っても「完全」になり得る（GPU の浮動小数点やカーネルの差で画素は変わる）。
- 画素がどれだけ違うかは**測って添える**（SSIM・pHash 距離・変化した画素の割合・平均絶対差）。
- **合否は人が付ける。** 閾値をコードに埋めない。
- 画像の判断の語は **キープ / ボツ**（状態は `kept` / `rejected`、台帳の verdict は `keep` / `reject` / `clear`）。
  再現の合否（`same` / `close` / `different` / `failed`）とは別物なので混ぜない（§4.8）。

> **参考にした既存実装（連携はしない）**
> この設計を詰める過程で、別プロジェクト `illust-authoring` の記録再生の実装
> （正規化した部分集合から作るキー、`exact | approx | impossible` ＋ 理由の形、
> `changed_fraction` / `mean_abs` という指標名）を読んで参考にした。
> **このツールは同プロジェクトと連携しない。** API を呼ばず、ストアも読まない。スキーマ・用語・規約も
> 合わせない（判断の語はこのツールの **キープ / ボツ**）。以下の設計はすべて、このツール単独で成立する形にしてある。

---

## 2. 実機で分かったこと（設計を決めた 8 点）

詳細な引用は [`comfyui-reproduction-findings.md`](comfyui-reproduction-findings.md)。

1. **API 形式 JSON は ComfyUI が自分で読める。** `app.ts` の `handleFile` が
   `isApiJson()` で判定し、`loadApiJson()` が API → UI の変換（`LiteGraph.createNode` → ウィジェット復元 →
   `rootGraph.arrange()`）を行う。ドラッグ&ドロップでも「Open」ボタンでも同じ経路。
   → **自前で UI 形式へ変換する必要はない。**（当初の設計はここを誤っていた）
   ただし判定は `Object.values(data).every(v => v.class_type)` なので、
   **全エントリが `class_type: string` と `inputs: object` を持つ**必要がある。
2. **UI 形式のグラフは UI 起点の実行にしか無い。** 実測 419 件の履歴のうち
   `extra_pnginfo` を持つのは **150 件**（API 起点の 269 件には無い）。
   位置・グループ・リンクまで完全に戻せるのはこの 150 件だけ。
3. **`GET /api/jobs/{prompt_id}` が 1 リクエストで全部返す。** しかも **`job id == prompt_id`**。
   返るもの: `workflow.prompt`（API グラフ）、`workflow.extra_data.extra_pnginfo.workflow`（UI グラフ）、
   `outputs`、`execution_status`、`preview_output`。→ 監視の主経路にする。
4. **`/history` の形は素直ではない。** entry のキーは `prompt` / `outputs` / `status` / `meta` の 4 つで、
   **`extra_data` は独立キーではなく `prompt` のタプル要素（`prompt[3]`）**。
   `prompt[2]` が API グラフ、`prompt[4]` が実行対象ノードの一覧。
5. **サーバ側に seed の上書き API は無い。** `control_after_generate` は `INPUT_TYPES` の宣言だけで、
   実際の増減はフロントエンドが行う。→ **再現ツールがグラフ JSON を自分で書き換える**。
6. **モデルのハッシュは ComfyUI が記録も公開もしない。**
   `GET /experiment/models/{folder}` が `name` / `pathIndex` / `size` / `modified` / `created` を返すので、
   **`(name, size, mtime)` でピン留め**するのが現実的。フルハッシュは自前で計算することになる。
   なお `unet` と `clip` は `diffusion_models` / `text_encoders` に統合され、旧名では 404。
7. **カスタムノードの版は取れるものと取れないものがある。**
   `GET /api/customnode/installed` が git のコミット（またはバージョン）を返すが、
   **`comfyui-anima-incontext` と `illust_tagger` は追跡外で、版の識別子が存在しない**
   （`pyproject.toml` も `__version__` も無い）。→ 版が分からないことを**記録に残す**。
8. **`?template=` はあるが使えない。** 開けるのは同梱テンプレート（`/templates/<id>.json`）か
   カスタムノードの `example_workflows` だけ。**`user/default/workflows/` のファイルを URL で開く手段は無い**
   （`?workflow=` は未実装、`PRESERVED_QUERY_NAMESPACES` に WORKFLOW 名前空間が無い）。
   加えて `GET /userdata/{file}` は `Content-Disposition: attachment` を返すため、URL を開いてもロードされない。

### 2.1 そして、いちばん効く事実（PNG 側）

**ja2en の英訳結果は、どこにも残っていない。**
`TextGenerate` の出力は実行時の値で、`CLIPTextEncode.text` も `StringConcatenate.string_b` もリンク参照。
`/history` には `PreviewAny` の `text` として入るが**メモリ上のみ**で、既存 6 枚は既に消えていた
（`metadata-findings.md` §2）。→ **§5 の設計はここから逆算して決まる。**

---

## 3. ① ワークフローを開く

### 3.1 経路の優先順

| 優先 | 条件 | やること | 得られるもの |
| --- | --- | --- | --- |
| **A** | UI 形式のグラフがある（UI 起点の実行、または PNG の `workflow` チャンク） | そのまま `.json` に書き出してドラッグ&ドロップさせる | 位置・グループ・リンクまで完全 |
| **B** | API 形式しか無い | API 形式のまま `.json` に書き出してドラッグ&ドロップさせる | グラフは完全。**配置は自動**（`arrange()`） |
| **C** | 何度も開く / 一覧から選びたい | `POST /api/userdata/workflows%2F<名前>.json` で ComfyUI に置く | サイドバーに出る。**UI 形式のみ**（後述） |
| **D** | どれも無い（JPEG 等） | 「来歴なし」と出す。生成パラメータの表だけ出す | — |

**A と B の判定は PNG のチャンクで足りる。** 実測で 1,028 枚中 175 枚が `workflow`（UI 形式）を持っていた。

### 3.2 C の落とし穴（実装時に踏みやすい）

**API 形式の JSON を `user/default/workflows/` に置いても、サイドバーからは正しく開かない。**
サイドバーは `workflowService.openWorkflow` → `app.loadGraphData()` の経路で、**UI 形式を前提**にしている。
`loadGraphData` はオブジェクトなら既定グラフに差し替えないため、空のグラフになる。

→ **C を使うのは「UI 形式があるとき」だけ**にする（＝ A が可能なとき）。API 形式しか無いときは B（D&D）を案内する。

また上書きが既定なので、**`overwrite=false` を必ず付ける**。利用者の既存ワークフローを壊さない。
衝突したら「既にある」と伝えて名前を変えさせる（409 が返る）。

### 3.3 画面の出し方

詳細画面に出すもの:

```
[ComfyUI を開く]  [JSON を保存してドラッグ&ドロップ]  [ComfyUI に置く]
形式: UI 形式（位置まで復元） / API 形式（配置は自動）
グラフ: あり（API 形式）   prompt_id: 62aa51ae-...
```

- **URL 一発で開く方法が無いことを隠さない。** 「開く URL は ComfyUI に無いので、
  保存した JSON をキャンバスへドロップしてください」と 1 行で書く。
- `graph.install`（C）は失敗しても `JSON を保存`（A/B）で目的を果たせるようにする（fail-soft）。

---

## 4. ② 同じ条件を記録し、作り直せる形で渡す

記録した条件から利用者が実際に使える形は 4 つ。**この 4 つが設計の対象**で、どれも生成はしない。

| # | 使い方 | 出すもの | 生成 |
| --- | --- | --- | --- |
| **1** | プロンプト・パラメータを**コピー** | クリップボード / 表 | しない |
| **2** | **ComfyUI で開く** | グラフ JSON（§3） | しない（利用者が開く） |
| **3** | **seed を変えて回す** | seed 違いのグラフ JSON の束 ＋ manifest（§4.7.2） | しない（利用者が投入する） |
| **4** | 名前を付けて**保存（プリセット）** | `preset` の行（§4.10） | しない |

「1 回だけ作り直す」も「後からキープした条件を使う」も、この 4 つの組み合わせで足りる。
**エージェントに条件を渡す API や、条件で画像を自動で集める仕組みは作らない**（§6-10）。

### 4.1 何を固定すればよいか（取得元つき）

「PNG から取れる」が最も移植性が高い（画像 1 枚で完結する）。取れないものは監視で捕まえる。

| 項目 | PNG から | ComfyUI API から | 備考 |
| --- | --- | --- | --- |
| API 形式グラフ（全体） | **○** `prompt` チャンク | ○ `/api/jobs/{id}` の `workflow.prompt` | これが再現の本体 |
| UI 形式グラフ | **△** `workflow` チャンクがあるときだけ（実測 17%） | **△** UI 起点の実行だけ（実測 36%） | 人が開いて直すときに効く |
| 画像モデル / LoRA / VAE / CLIP・TE | ○ ファイル名 | ○ | **名前だけ**（§4.6） |
| sampler / scheduler / steps / cfg / denoise / seed / 解像度 | ○ | ○ | `KSampler` と `EmptyLatentImage` |
| 最終プロンプト（英文） | **△** リテラルのときだけ | **△** `CLIPTextEncode.text` がリテラルのときだけ | ja2en ではリンク参照なので**取れない** |
| 日本語原文 | **○** `PrimitiveStringMultiline.value` | ○ | 常に取れる。再現の手掛かりになる |
| **英訳（`TextGenerate` の出力）** | **×** | **×**（`/history` に一瞬だけ） | **監視で捕まえるしかない**（§5） |
| `TextGenerate` の全パラメータ | ○ ノードの `inputs` | ○ | `temperature` / `top_k` / `top_p` / `min_p` / `repetition_penalty` / `presence_penalty` / `seed` / `thinking` / `use_default_template` / `mtp` / `max_length` |
| 翻訳の `system_prompt` | ○ | ○ | 前段の `PrimitiveStringMultiline` を辿る |
| モデルの同一性 | **×** | **△** `/experiment/models/{folder}` の `size` / `modified` | ハッシュは存在しない |
| カスタムノードの版 | **×** | **△** `/api/customnode/installed` | 2 つは版が無い（§2-7） |
| ComfyUI 本体の版 | **×** | **○** `/system_stats` | `comfyui_version` / frontend / pytorch |
| GPU / dtype | **×** | **△** `/system_stats` の `cuda` | bf16 の選択が結果に効く（§4.4） |

→ **PNG 1 枚では完全な再現記録にならない。** 監視（§5）で環境の写しを添えて初めて揃う。
揃わない場合は「近似」として、**何が足りないかを画面に出す**（黙って書き出さない）。

### 4.2 再現の 3 レベル（書き出すグラフの作り方）

**どのレベルで書き出すかを、記録ごとに決める。** ここが「作り直したときに絵が変わるか」を左右する。

| レベル | 名前 | 書き出すグラフ | 決定的か |
| --- | --- | --- | --- |
| **L1** | **最終プロンプトを確定**（既定） | 実際に `CLIPTextEncode` へ渡った文字列（`final_prompt`）を**リテラル**として入れ、翻訳の枝（`TextGenerate` → `StringConcatenate`）を外したグラフ | **はい。** LLM の非決定性が入らない |
| **L2** | グラフごと | 元のグラフのまま（`TextGenerate` も走る） | **いいえ。** §4.4 の理由で訳が変わりうる |
| **L3** | 人は訳を貼る | 訳を入れる場所を空にしたグラフ。利用者が英文を入れて回す | はい（L1 と同じ） |

**既定は L1。** 当時使われた文字列が分かっているときだけ使える（§5 の監視で捕獲したとき、
PNG にリテラルがあったとき、利用者が貼ったとき）。分からない画像は L2 に落ちるが、
**落ちたことを画面に出す**（「当時の訳が残っていないため、訳し直して生成されます。結果が変わる可能性があります」）。

L1 が優れている理由: ja2en の経路では**英訳の揺れが絵の揺れに直結する**。
日本語は同一でも、訳が 1 語違えば絵は別物になる。L1 はその揺れを消せる唯一の方法である。

> **点検で 2 点を正した（重要）。**
> 1. **入れるのは「捕獲値」ではなく「最終プロンプト」。** 捕獲できるのは `TextGenerate` の出力で、
>    ja2en の経路ではその後 `StringConcatenate` が品質語を前置する（実測:
>    `string_a = "(masterpiece, best quality, good quality, score_9), safe,"`、`delimiter = "\n\n"`）。
>    捕獲値をそのまま入れると**品質語が落ちる**。`string_a + delimiter + 捕獲値` を
>    **再構成**して `final_prompt` とし、それを入れる（§4.7・§5）。
> 2. **L1 は「同じ条件」ではない。** 翻訳の枝を外すので**再現キーは必ず変わる**（ノードが 1 つ減る）。
>    したがって L1 の書き出しは判定上 `exact` ではなく **`approx` ＋ 理由 `text_pinned`** とし、
>    **結果を測って人に合否を求める**（§4.5・§4.8）。記録のキー（元）と書き出しのキー（変えた後）は
>    **別々に持ち、差の理由を残す**（`recipe_export.recipe_hash`。§4.9）。

どのレベルで書き出したかは記録に残す（`mode` = `'pin_text'` / `'rerun_graph'` / `'manual_text'`。§4.9）。

### 4.3 再現キー（生成に寄与する部分グラフの hash）

**このツール独自の定義。** 「同じ条件か」を機械的に比べるための 1 つの文字列（`recipe_hash`）。

- 対象: **API 形式グラフのうち、生成に寄与するノード部分グラフ**。
  保存・出力ノード（`SaveImage` など）から**遡って到達できるノード**だけを取る。各ノードの `class_type`、
  リテラルの `inputs`（リンクは含めない）、およびリンクの結線（どのノードの何番目の出力がどこへ入るか）。
- 除外するもの:
  - **書き出しにしか効かない値**（`SaveImage.filename_prefix`、`PreviewAny` など）。
    **§4.7.1 の「印」をここに入れるため、この除外は必須。** 保存先を変えただけで再現キーが変わると、
    無意味に「別物」と判定されてしまう。
  - `_meta`（`title` などの見た目）。
  - カタログ・判断・時刻・ファイルパス・グループ所属（**キープ / ボツを変えても再現キーは変わらない**）。
- 含めるもの: モデル名（＋分かるなら size/mtime）、LoRA と重み、VAE、CLIP/TE、`sampler` / `scheduler` /
  `steps` / `cfg` / **`denoise`** / `seed` / 解像度、リテラルのプロンプト、
  `TextGenerate` の全パラメータ、`init_image` のハッシュと `strength`、制御入力の種別と `payload_hash` と重み。

  > **`denoise` は必ず入れる。** パラメータ表では省略されがちだが、「どこまで作り直すか」を決める値なので、
  > 抜けると別の絵を「同じ条件」と呼んでしまう。

- 正規化: キー昇順・空白なしの JSON にして SHA-256、`sha256:` を付ける。
- 使い方: **記録 → 書き出し → 結果** の 3 か所でキーを比べる。
  - 書き出しのキー（§4.9 の `recipe_export.recipe_hash`）が記録と同じなら、当時の条件のまま。
    違う場合は**差分を出す**（「seed だけ違う」など）。
  - **結果の画像のキー**（PNG の `prompt` チャンクから同じ手順で計算）が**書き出しのキーと一致すれば
    「条件は同一」**と言える。**印はキーに入らないので、印を付けてもこの一致は壊れない。**
  - ファイル名が同じで中身が変わったモデルは、この hash では捕まらない（§4.6）。

### 4.4 なぜ「グラフごと」（L2）が決定的でないか

`TextGenerate` の実装（`comfy_extras/nodes_textgen.py` と `comfy/text_encoders/qwen35.py`）を読んだ結果:

- 生成器は**固定されている**: `torch.Generator(device=...).manual_seed(sampling["seed"])`。
  MTP を使わない経路も `manual_seed(seed)`。→ 「乱数だから毎回違う」わけではない。
- しかし **`mtp` の値を変えると、同じ seed でも出力が変わる**。
  ノードのツールチップが明記している:
  「Sampled output stays correctly distributed but differs from non-MTP output for the same seed」。
  しかも `mtp` の既定は `"auto"`（`fixed_depth=None` → 内部で深さを決める）なので、
  **保存されたグラフに `mtp` が入っていないと再現できない**。
- **dtype が device 依存**: `dt = torch.bfloat16 if comfy.model_management.should_use_bf16(device) else torch.float32`。
  GPU が変われば（あるいは起動オプションが変われば）訳が変わりうる。
- `thinking` を on にすると `<think>...</think>` を挟んでから答える。
  on/off が変われば当然変わる（実測した画像の 1 つは `thinking: true`）。
- 加えて、bf16 の行列積など**カーネルの非決定性**で、条件が完全に同一でも
  確率サンプリングの結果が変わる可能性は残る。

→ **L2 は「条件を揃えても訳が変わりうる」**。だから L1（テキスト固定）を既定にする。
L2 で書き出すときは、記録に `mtp` / `thinking` / `use_default_template` / dtype / GPU を含め、
**結果を必ず測って人に出す**。

### 4.5 判定（完全 / 近似 / 不可）と理由

**書き出す前に**、この記録がどこまで作り直せるかを判定して出す。
形は `status` ＋ `reasons[{item_id, kind}]`（画面にもエージェントにも読める）。

| `status` | 意味 |
| --- | --- |
| `exact` | 生成に渡る条件がすべて揃っていて、記録と一致している（そのまま書き出せる） |
| `approx` | 書き出せるが、条件の一部が不明・不一致（**何が**を理由に出す） |
| `impossible` | 書き出せない（グラフが無い、必要なノード・モデルが今の環境に無い） |

`reasons[].kind`:

| `kind` | 意味 |
| --- | --- |
| `missing` | グラフが無い（JPEG など） |
| `unresolved` | グラフが参照するモデル・ノードが今の環境に無い、または**入力の名前が今の版の宣言に無い**（§4.7 手順 4） |
| `node_missing` | カスタムノードが入っていない（`/object_info` で確認） |
| `version_differs` | ComfyUI 本体・カスタムノードの版が違う |
| `hash_mismatch` | モデル/LoRA の同一性が確認できない（**名前だけ**） |
| `measured_differs` | 実測値が記録と違う（steps などが後から変わった） |
| `text_not_captured` | **当時の最終プロンプトが残っていない**（ja2en の画像で最も多い） |
| `text_pinned` | **L1 で書き出す**（最終プロンプトを確定し、翻訳の枝を外した）。**再現キーが元と変わる**（§4.2） |
| `llm_nondeterministic` | L2 で書き出す（訳が変わりうる） |
| `gpu_differs` | GPU・dtype が違う |
| `manual_step` | 手作業の後処理を通っている |

画面には「近似」の理由を**具体的に**出す:

```
再現: 近似
  ・英訳が残っていないため、訳し直して生成されます（結果が変わる可能性があります）
  ・LoRA の同一性は名前のみ（サイズ・更新時刻が一致しません）
  ・ComfyUI の版が違います（記録 0.39.2 → 現在 0.39.2 / ノード 1 件が不明）
```

### 4.6 モデル・ノードの同一性（ここが最も弱い）

- **名前は記録できるが、中身は保証できない。** 同じファイル名で LoRA を学習し直せば、
  グラフは同じでも絵は別物になる。ComfyUI はハッシュを持たない（§2-6）。
- 対策: `(名前, size, mtime)` を記録し、**書き出すときに照合する**。
  一致しなければ `hash_mismatch`（近似の理由）にする。
- フルハッシュを取るかは費用の問題。実測したモデルは 4〜9 GB 級が並ぶ
  （`diffusion_models` 計 24.0 GB、`text_encoders` 計 27.6 GB、`loras` 計 1.7 GB）。
  内容ハッシュは 399 MB/s なので 53 GB で約 2 分。**背景ジョブで 1 回計算して保存する**のが現実的。
  → 既定は `(名前, size, mtime)`、任意で「ハッシュを取る」を押せるようにする（§8-1）。
- カスタムノードは `/api/customnode/installed` を環境の写しとして保存する。
  `comfyui-anima-incontext` と `illust_tagger` は**版が存在しない**ので、
  `__init__.py` の size と mtime を代替の識別子として記録し、「版不明」と印を付ける。

### 4.7 書き出しの手順（検査してから、印を付けて出す）

```
1. 記録から API 形式グラフを取り出す（PNG の prompt チャンク / sidecar / /api/jobs）
2. L1 なら: TextGenerate ノードを外し、CLIPTextEncode.text を捕獲した英文（リテラル）に置き換える
   L2 なら: グラフはそのまま。L3 なら: CLIPTextEncode.text を空にして利用者に委ねる
3. seed を書き換える（seed 違いを出すときだけ。§4.7.2）。サーバ側に上書き API が無いので自分で JSON を直す
4. ★ 書き出す前の検査（これを飛ばさない。**在り処ではなく、そのノードが受け付ける値そのもので見る**）
   - /object_info を 1 回引き、グラフの全 class_type が今の環境に存在するか確かめる（/object_info/{class_type}）
   - 無いノードがあれば「不可（node_missing）」として理由を出し、書き出さない
   - モデル/LoRA/VAE は、同じ /object_info/{class_type} の combo 値（input.required / input.optional に
     並ぶファイル一覧 = そのノードが実際に受け付ける名前）に含まれるかで確かめる。無ければ「不可（unresolved）」
     → 入力名→フォルダの対応表（unet_name → diffusion_models など）を自前で持たずに済む
   - 同じ pass で、グラフの各ノードの inputs のキーが、そのノードが宣言する input.required /
     input.optional のキーに含まれるか確かめる。含まれないキーがあれば「不可（unresolved）」とし、
     キー名を理由に出す（版の差が原因と分かるときは version_differs も添える）
     → 入力の名前は版で変わる（実測: TextGenerate の sampling_mode.temperature のような入れ子名）。
       これを見ないと、検査を通ったグラフが投入時に落ちる
   - (名前, size, mtime) の照合（§4.6）はこれとは別に行う。combo 値には size / mtime が無いので、
     分かるフォルダだけ /experiment/models/{folder} を併用する
   → ComfyUI に「検証だけする口」は無い（validate_prompt は実行部の内部関数で、HTTP の経路に無い）。
     投入は利用者が行うので（§6-1）、この 3 つで足りる範囲に留める
   → 「今の環境では開けないグラフ」を渡さない。開いてから気付く手間と、
     原因の分からないエラーを防ぐ。実行のためではなく、書き出しの品質を守るための検査
5. 保存ノードの filename_prefix に印（marker）を入れる（**§4.7.1 の前提を満たすときだけ**）。
   満たさないときは印を付けずに書き出し、紐付けを matched_by='conditions' の経路に落とす
6. グラフ JSON を <data>/exports/<recipe_id>/<attempt_id>/ に書く
7. manifest.json を同じフォルダに書く（§4.7.3）
8. 画面に「このフォルダの JSON を ComfyUI のキャンバスへドロップして Queue」と出す。
   印つきなので、出てきた画像は監視が自動でこの書き出しに紐付ける（§5）
```

**関所を先に置く**のは、`impossible` と分かっているグラフを渡しても利用者が ComfyUI で失敗するだけだから
（無駄と混乱を防ぐ）。

> **点検で見つかった誤り（検査の方法）**: 以前は「モデル/LoRA/VAE が `/experiment/models/{folder}` にあるか」と
> だけ書いていた。これは `unet_name` → `diffusion_models` のような**入力名→フォルダの対応表を自前で持つ**前提で、
> カスタムのローダーでは対応が分からない。また、ノードが存在するかしか見ておらず、**入力キー名の版差**を見ていなかった
> （例: `TextGenerate` の `sampling_mode.temperature`）。検査は `/object_info/{class_type}` の combo 値と
> 入力キー集合で行う形に変えた。**ComfyUI に検証だけの口は無い**（`validate_prompt` は実行部の内部関数）。

#### 4.7.1 印（marker）: どの書き出しかを、出てきた画像の名前に残す

**目的**: 利用者が自分で回した結果を、監視が**どの書き出しのものか**自動で判別できるようにする。
投入は利用者が行うので、こちらは `prompt_id` を知らない。だから**グラフ側に出所を書いておく**。

- **この設計で使う印**: 保存ノード（`class_type` が `SaveImage`）の
  `filename_prefix` を **`repro-<attempt_id>/seed-<seed>`** にする。
  - `attempt_id` は書き出しごとに発行する短い id（例 `r7k2m4`）。同じ記録から何度書き出しても衝突しない。
  - 同じ書き出しから seed 違いを N 枚出すときは **`attempt_id` を共有**し、`seed-<seed>` で区別する。
    → 「同じ書き出しの何枚目か」が名前だけで分かる。
  - **保存ノードが複数あるときは、`type='output'` を出す保存ノードすべてに同じ印を入れる。**
    1 つだけにすると、印の無いノードから出た画像は紐付かない（§8-3）。

**印を付けてよい前提。** 印の方式は、次のことが成り立つときだけ安全である。**1 つでも外れたら印を付けない。**

| # | 前提 | 外れたときに起きること | 落とし方 |
| --- | --- | --- | --- |
| **1** | 保存ノードの `filename_prefix` が**リテラル**（`inputs.filename_prefix` が文字列。`[<node_id>, <slot>]` ならリンク） | リンクを値に置き換えると**結線が消える**。再現キー（§4.3）は結線を含むので、印を付けただけで「条件が変わった」ことになる | **印を付けない。** 書き出しはそのまま行い、紐付けは `matched_by='conditions'` の経路に落とす（下の表） |
| **2** | **`type='output'` を出す保存ノードがある**（`SaveImage`）。`type` は保存ノードの出力の型で、`PreviewImage` は `'temp'` | `PreviewImage` しか無いワークフローでは、出力が一時フォルダに行って消える。印を付けても結果が残らない | 画面に「**印を付けられません**」と出して止め、利用者に選ばせる: **`SaveImage` を足して書き出す**（グラフに 1 ノード足したことを理由に残す）か、**印なしで書き出す**（紐付けは `conditions`）か |
| **3** | 保存ノードが 1 つ、または複数でも**すべて** `filename_prefix` を持つ | 印を入れられないノードが残ると、その出力は紐付かない | 複数なら**すべてに同じ印**。`filename_prefix` を持たない保存ノードがあれば、その出力は `conditions` で拾う |

- 前提が外れて印を付けなかった書き出しは、下の表の「印が無く、手動でも指定されない」の行に落ちる。
  **どの前提が外れたかは書き出しの記録に残す**（後から「なぜ紐付かなかったか」を辿れるように）。
- `temp` の画像がいつ消えるか（ComfyUI の再起動時か、掃除の周期か）は**未確認**。

> **点検で見つかった誤り（前提の欠落）**: 以前は「保存ノード（`SaveImage`。無ければ `filename_prefix` を持つ
> 保存ノード）の `filename_prefix` を印にする」と書くだけで、**前提が 1 つも書かれていなかった**。
> 前提の外で印を付けると、結線が消えるか、印が付かないか、出力が消える。ここに前提と落とし方を明記した。

- **なぜファイル名で足りるか**: ComfyUI の `filename_prefix` は `subfolder` を含む出力パスに使われるので、
  できる PNG の名前は `<output>/repro-<attempt_id>/seed-<seed>_00001_.png` のようになる。
  監視は `GET /api/jobs/{prompt_id}` の **`outputs[].images[].filename`（と `subfolder`）**を読むだけでよい。
  PNG を開き直さなくても、**どの書き出しかが分かる**。
- **なぜ `filename_prefix` が安全な場所か**: **前提（上）を満たすときだけ**、`filename_prefix` は保存先を決めるだけの
  **書き込み専用の値**で、絵の中身に影響しない。そして**再現キー（§4.3）から除外してある**。したがって
  **印を付けてもキーは変わらない**＝「条件は同じで、印だけ違う」と言い切れる。
  もし印をキーに入れていたら、書き出しのたびに「条件が変わった」と誤判定するところだった。
  **リンクだったときにリテラルへ置き換えると、この前提が崩れて結線が消える**（＝前提 1 の落とし方を使う）。
- **保険**: PNG の `prompt` チャンクにも `SaveImage.filename_prefix` はそのまま入る（この項目が PNG から
  読めることは実測済み）。→ **利用者がファイル名を変えても、PNG を読み直せば印は残っている**。
  （API 形式を読み込んだフロントエンドが `filename_prefix` の値を保持することは `loadApiJson` の
  ウィジェット復元から期待できるが、**実機では未確認**。）
- **印が無いとき・効かないとき**の落とし方（この順に試す）:

  | 状況 | 紐付け方 | `matched_by` |
  | --- | --- | --- |
  | 名前（または PNG の `prompt`）に印がある | 自動で紐付ける | `'marker'` |
  | 利用者が改名・移動した、別の経路で作った | **手動で紐付ける**（画面で結果を選ぶ） | `'manual'` |
  | 印が無く、手動でも指定されない | **条件で候補を出す**: モデル ＋ リテラルのプロンプト文 ＋ 解像度が一致する未紐付けの画像を候補にして、人が選ぶ（**seed は無視する**） | `'conditions'` |

  **前提が外れて印を付けなかった書き出しは、必ず 3 行目に落ちる。** 印が付かなかった理由（前提 1 / 2 / 3 のどれか）は
  書き出しの記録に残し、画面にも 1 行で出す（「印を付けられません」＝前提 2 のとき）。

#### 4.7.2 seed 違いの書き出し

**サーバ側に seed を上書きする API は無い**（§2-5）。`control_after_generate` は `INPUT_TYPES` の宣言だけで、
実際の increment / randomize はフロントエンドが行う。→ **seed を変えて回すには、こちらでグラフ JSON を
書き換えて N ファイル出すしかない。** これが「seed を変えて回す」の実装。

- **書き換えるのは、保存ノードからグラフを遡って最初に到達する `KSampler` 1 つだけ。**
  `inputs.seed` を書き換えたグラフを **seed の数だけ**書く。
  - 遡る起点は `type='output'` の保存ノード（§4.7.1 の前提 2 と同じ）。到達した最初の `KSampler` だけを対象にし、
    **他にも `KSampler` があるときは画面に「揃えられません」と出す**（黙って全部を書き換えない）。
  - 理由: 二段構成（hires fix・2 パス）のワークフローでは、2 つ目の sampler の seed まで変えると
    「seed 以外は同じ」が成り立たず、絵が別物になる。印も `seed-<seed>` が一意でなくなり、結果の紐付けが曖昧になる。
  - 他の `KSampler` は**そのままの値**で残す。画面には「どのノードの seed が揃わないか」を書く。
- 置き場: `<data>/exports/<recipe_id>/<attempt_id>/seed-<seed>.json`（利用者が見て分かる名前にする）。
- 印は seed ごとに変える（`repro-<attempt_id>/seed-<seed>`）ので、**どの seed の結果かが名前で分かる**。
- manifest に「seed → グラフのファイル名 → 期待される出力ファイル名」を並べる（§4.7.3）。
- **注意**: API 形式には `control_after_generate` が入らない。フロントエンドで読み込んだときに
  その設定がどう復元されるかは**未確認**。もし「randomize」になっていれば、書いた seed が実行時に変わる。
  → 対策は 2 つ:
  1. manifest と画面に「**seed の欄は触らず、`control_after_generate` は `fixed` のまま Queue**」と書く。
  2. 監視で取り込んだ PNG の `prompt` チャンクの `KSampler.seed` を読み、**書き出しの seed と違えば
     「seed が変わっています」と出す**（黙って別人の結果として記録しない）。

> **点検で見つかった誤り（複数の `KSampler`）**: 以前は「`KSampler`（複数あれば**全部**）の `inputs.seed` を
> 書き換える」としていた。二段構成では 2 つ目の seed も変わり、「seed 以外は同じ」と言えなくなる。
> 対象を**保存ノードから遡って最初に到達する 1 つ**に限り、他があるときは黙って書き換えずに
> 「揃えられません」と出す形に直した。

#### 4.7.3 manifest（この束は何か）

`manifest.json` を書き出しフォルダに置く。人が読み、機械も読める。

| キー | 内容 |
| --- | --- |
| `attempt_id` / `recipe_id` | どの書き出しか |
| `recipe_hash` | 記録の再現キー（§4.3） |
| `export_hashes` | seed ごとの書き出しグラフの再現キー（seed 以外が同じなら、記録との差は seed だけ） |
| `seeds` | 各グラフのファイル名と seed、**期待される出力ファイル名**（`repro-<attempt_id>/seed-<seed>...`） |
| `output_dir` | ComfyUI の出力先（設定値。分からなければ `null`） |
| `notes` | 検査の結果（`status` と `reasons`）と、利用者への手順 1 行 |

**出力ファイル名は前方一致（`repro-<attempt_id>/seed-<seed>`）で見る。** 連番の桁数や接尾辞は
ComfyUI の実装依存なので、**完全一致を期待値にしない**（版が上がっても壊れない）。

### 4.8 ③ 出てきた絵が当時と一致するか確かめる

指標は [`comparison.md`](comparison.md) §4 の実装を**そのまま共有する**（別実装を持たない）。

| 指標 | 意味 | 出所 |
| --- | --- | --- |
| `same_hash` | バイトまで同じか | 内容ハッシュの比較 |
| `ssim` | 見た目の一致度 | 256px へ縮小して計算 |
| `phash_distance` | 構図の近さ | 64bit ハミング距離 |
| `changed_fraction` | 差が大きい画素の割合（**0〜1**） | [`comparison.md`](comparison.md) §4 が定義の正 |
| `mean_abs` | 平均絶対差（**0〜255**） | 同上 |

> **点検で見つかった誤り**: この表は以前「差分（8 を超えた画素の割合）」とだけ書いており、
> `comparison.md` §2.3 の「変化した画素の割合（3 倍に増幅）」と食い違っていた。
> **定義の正を `comparison.md` §4 の 1 か所**に決め、ここは参照するだけにした。
> 正しい定義は「**絶対差が 8 を超えた画素の割合（0〜1）**。256px 長辺へ縮小したグレースケール同士で計算し、
> 閾値 8 は**増幅前**の差に当てる」「`mean_abs` は**増幅前**の平均絶対差（0〜255）」。
> 赤く重ねるときの 3 倍増幅は**表示だけ**で指標には影響しない。

- 比べる 2 枚は、**書き出し（§4.7）と、利用者が回して出てきた結果**（§5 が監視で拾うか、人が登録する）。
- **人の合否を台帳に載せる。** `verdict` は `same` / `close` / `different` / `failed` ＋ メモ。
  これは「当時の絵と一致するか」の判断で、画像の **キープ / ボツ**（`kept` / `rejected`）とは別に付く。
- 元の記録は**書き換えない**。結果は別の `asset`、別の `recipe_export_result` として残す。
  出てきた画像そのものにキープ / ボツを付けたければ、通常の画像と同じく `decision` 台帳に載る
  （verdict は `keep` / `reject` / `clear`）。

### 4.9 記録のスキーマ

```sql
-- 再現の記録（元画像 1 枚に対して 1 つ。条件の写し。生成はしない）
CREATE TABLE recipe_record (
  id              TEXT PRIMARY KEY,
  source_asset_id TEXT NOT NULL REFERENCES asset(id),
  mode            TEXT NOT NULL,      -- 'pin_text'(L1) | 'rerun_graph'(L2) | 'manual_text'(L3)（§4.2）
  recipe_hash     TEXT NOT NULL,      -- §4.3 の再現キー（当時の seed を含む）
  graph_path      TEXT,               -- <data>/workflows/<sha256>.json（API 形式）
  graph_kind      TEXT,               -- 'ui' | 'api'
  record_json     TEXT NOT NULL,      -- §4.1 の全項目（取れなかった項目は null で明示）
  final_prompt    TEXT,               -- 実際に CLIPTextEncode へ渡った文字列（§5 の 3 手順で再構成）
  final_prompt_source TEXT,           -- 'png_literal' | 'reconstructed' | 'manual'
  captured_text   TEXT,               -- 捕獲した TextGenerate の出力（品質語を前置する前）
  captured_source TEXT,               -- 'comfyui_history' | 'sidecar' | 'textgenerate' | 'manual'
  text_probe      TEXT,               -- 由来が TextGenerate に辿れないテキスト出力（en_text にしない）
  env_snapshot    TEXT NOT NULL,      -- ComfyUI 版・ノード版・GPU・dtype・/object_info の要約
  status          TEXT NOT NULL,      -- 'exact' | 'approx' | 'impossible'（§4.5）
  reasons         TEXT,               -- §4.5 の kind の配列（L1 なら 'text_pinned' を含む）
  created_at      TEXT NOT NULL,
  actor           TEXT NOT NULL
);

-- 書き出し（1 回ごと。元の記録は書き換えない。seed 違いは seed ごとに 1 行）
CREATE TABLE recipe_export (
  id            TEXT PRIMARY KEY,
  recipe_id     TEXT NOT NULL REFERENCES recipe_record(id),
  attempt_id    TEXT NOT NULL,        -- 印に使う短い id。同じ束のグラフは共有する（§4.7.1）
  seed          TEXT,                 -- 10 進の文字列（符号なし 64bit は SQLite の符号付き INTEGER に入らない）
  recipe_hash   TEXT NOT NULL,        -- 書き出したグラフの再現キー（seed を変えたときだけ記録と違う）
  graph_path    TEXT NOT NULL,        -- 書き出したグラフ JSON（印つき）
  marker        TEXT NOT NULL,        -- 'repro-<attempt_id>/seed-<seed>'
  export_dir    TEXT NOT NULL,        -- 利用者が D&D するフォルダ
  manifest_path TEXT,
  created_at    TEXT NOT NULL
);

-- 結果（監視で入るか、人が登録する。1 回の書き出しに複数枚あり得る）
CREATE TABLE recipe_export_result (
  id              TEXT PRIMARY KEY,
  export_id       TEXT NOT NULL REFERENCES recipe_export(id),
  prompt_id       TEXT,               -- 監視が見つけた job id（= prompt_id）。NULL = 手動登録
  result_asset_id TEXT REFERENCES asset(id),   -- 出てきた画像（別の asset）
  matched_by      TEXT NOT NULL,      -- 'marker' | 'manual' | 'conditions'（§4.7.1）
  result_hash     TEXT,               -- 結果 PNG の prompt チャンクから計算した再現キー（§4.3）
  same_hash       INTEGER NOT NULL DEFAULT 0,
  ssim REAL, phash_distance INTEGER, changed_fraction REAL, mean_abs REAL,
  verdict         TEXT,               -- 人の合否: 'same'|'close'|'different'|'failed'（§4.8）
  note            TEXT,
  created_at      TEXT NOT NULL
);

-- 名前を付けた条件（プリセット。§4.10）
CREATE TABLE preset (
  id              TEXT PRIMARY KEY,
  name            TEXT NOT NULL,
  note            TEXT,
  source_asset_id TEXT REFERENCES asset(id),   -- 元にした画像（無ければ null）
  record_json     TEXT NOT NULL,      -- プロンプト・パラメータ（コピーして使う値そのもの）
  created_at      TEXT NOT NULL
);
```

- `record_json` には**取れなかった項目も `null` として書く**。「記録が無い」と「取れなかった」を区別するため。
- `recipe_export_result` は**監視（§5）が作る**。API の応答から作るのではない（このツールは投入しないため）。
- `prompt_id` は**主たる紐付けではない**。監視が見つけた実行を指す任意の記録としてだけ持つ。
  紐付けの主役は `recipe_export.marker` と `recipe_export_result.matched_by`。

### 4.10 プリセット（名前を付けた条件）

**使い道は、いまのところ「人が参照して使う」だけ。** それ以上は作らない。

- できること: **名前を付けて保存**し、**一覧して参照**し、**プロンプトとパラメータをコピー**する。
  保存するのは画像 1 枚の条件（`record_json` ＋ 元画像への参照 ＋ メモ）。
- **やらないこと**（§6-10）: 他のカットへの適用、エージェント向けのプリセット API、
  プリセットを条件にしたスマートフォルダ。必要になったら、そのときに設計する。
- 画面: 画像の詳細と一覧の両方から「この条件に名前を付ける」を出す。プリセット一覧には
  名前・メモ・元画像・作成日時を出し、行ごとに「コピー」を置く（**適用ボタンは置かない**）。

---

## 5. 監視（英訳の捕獲と、結果の紐付け）

監視には 2 つの仕事がある。**(a) 実行の瞬間にしか無い値を捕まえる**（英訳。§2.1）と、
**(b) 利用者が回した結果を、書き出しに紐付ける**（§4.7.1 の印）。

§2.1 のとおり、英訳は**実行の瞬間にしか存在しない**。`/history` はメモリ上のみ（実測 419 件）で、
再起動で消える。したがって:

- 監視を有効にすると **2 秒ごと**に `GET /api/jobs?limit=N` を見る（または `/history`）。
- 新しい `prompt_id` を見つけたら **`GET /api/jobs/{prompt_id}` を 1 回叩く**。
  これで API グラフ・UI グラフ・`outputs`・`execution_status` が揃う（§2-3）。
- **テキスト出力の捕獲は、次の 3 手順を守る**（点検で見つかった誤りを反映。実測で確定した形。
  詳細は [`design.md`](design.md) §7.3.1）:

  1. **`outputs[node].text` はリスト。** 実測は `{"11": {"text": ["..."]}}`（要素 1 つ）。先頭を取る。
  2. **グラフで由来を確かめる。** 実測した実行では `node 11 = PreviewAny` の `inputs.source = ["9", 0]`、
     `node 9 = TextGenerate` だった。**由来が `TextGenerate` に辿れるときだけ** `en_text` として採用する。
     辿れないテキスト出力は `text_probe` に残し、**`en_text` にしない**（番号ではなく**結線**で判定する）。
  3. **捕獲値は最終プロンプトではない。** 実際に `CLIPTextEncode` へ渡ったのは
     `string_a + delimiter + 捕獲値`。**再構成**して `final_prompt`（`final_prompt_source='reconstructed'`）
     として別に持つ。実測例は `string_a = "(masterpiece, best quality, good quality, score_9), safe,"`、
     `delimiter = "\n\n"`。**L1 で入れるのはこの `final_prompt`**（§4.2）。
- `outputs[node].images[]` の `filename` / `subfolder` / `type` から実ファイルを特定し、
  **監視を手で開始している間だけ**、未登録なら `asset` として登録する（ハッシュは内容で決まるので、二重登録にならない）。
  起動時の救済（下の「取りこぼしの救済」）はここを通らない＝**新しい画像は登録しない**。
- **紐付け（§4.7.1）**: `filename`（と `subfolder`）に `repro-<attempt_id>` があれば、その `recipe_export` に
  自動で紐付けて `recipe_export_result` を作る（`matched_by='marker'`）。無ければ紐付けず、候補として残す。
- 紐付けたら、その画像の PNG `prompt` チャンクから**再現キー（§4.3）を計算**し、書き出しのキーと比べる。
  併せて `KSampler.seed` を読み、書き出しの seed と違えば「seed が変わっています」と出す（§4.7.2）。
- 環境の写し（`/system_stats`、`/api/customnode/installed`、モデルの `size`/`mtime`）も同じときに取る。
- 全部を `<data>/sidecar/<sha256>.json` に書く（**DB を作り直しても来歴が残る**。
  `duplicates-deletion-backup.md` §5.1 で「PNG から取り直せない唯一のもの」と位置づけた）。
- **取りこぼしの救済（起動時に 1 回）**: `GET /history` を全部走査するが、**値を埋めるのは既に登録済みの画像だけ**。
  `asset_location` に登録されたパスと出力（`filename` / `subfolder`）を突き合わせ、一致した画像の
  `en_text` / `final_prompt` / `prompt_id` を埋める。**新しい `asset` は登録しない。**
  同じ名前のファイルが複数の実行にあるときは、取り違えるより**埋めない**（プロトタイプと同じ）。
  新規登録を伴う取り込みは、監視を**手で開始している間だけ**行う（§5.1・§6-11）。
  既に `/history` から消えていれば救えない（それが L2/L3 になる理由）。
  **ComfyUI につながらないときは黙って飛ばす**（起動のたびに「つながりません」の帯を出さない）。
  > **点検で見つかった誤り**: 以前は「起動時に `GET /history` を 1 回全部走査し、未登録なら `asset` として
  > 登録する」としていた。決定「監視は必要なときだけ手で開始」の外で画像を自動的に取り込むことになり、
  > ComfyUI が止まっていれば起動のたびにエラーの帯が出ていた。プロトタイプの `capture_history`
  > （`src/image_reviewer/capture.py`）は既に「登録済みで `en_text` が空の画像だけを埋める」振る舞いなので、
  > 設計を実装に合わせた。

> **点検で誤りを正した記録**: 別の点検者が「捕獲値は翻訳ではなく VLM の画像説明だから捕獲は使えない」と
> 指摘したが、**実機で確かめた結果それは誤り**だった。日本語原文（実測例:「背景に催眠にかかっていることを
> 示すハートのエフェクトがある。女の子は四つん這いになっている…」）が情景説明なので、
> その訳である英文も説明文の形になるだけである。ただし**リストであること**と
> **最終プロンプトではないこと**の指摘は正しく、上の 1 と 3 に反映した。
- **紐付け（§4.7.1）**: `filename`（と `subfolder`）に `repro-<attempt_id>` があれば、その `recipe_export` に
  自動で紐付けて `recipe_export_result` を作る（`matched_by='marker'`）。無ければ紐付けず、候補として残す。
- 紐付けたら、その画像の PNG `prompt` チャンクから**再現キー（§4.3）を計算**し、書き出しのキーと比べる。
  併せて `KSampler.seed` を読み、書き出しの seed と違えば「seed が変わっています」と出す（§4.7.2）。
- 環境の写し（`/system_stats`、`/api/customnode/installed`、モデルの `size`/`mtime`）も同じときに取る。
- 全部を `<data>/sidecar/<sha256>.json` に書く（**DB を作り直しても来歴が残る**。
  `duplicates-deletion-backup.md` §5.1 で「PNG から取り直せない唯一のもの」と位置づけた）。
- **取りこぼしの救済（起動時に 1 回）**: `GET /history` を全部走査するが、**値を埋めるのは既に登録済みの画像だけ**。
  `asset_location` に登録されたパスと出力（`filename` / `subfolder`）を突き合わせ、一致した画像の
  `en_text` / `final_prompt` / `prompt_id` を埋める。**新しい `asset` は登録しない。**
  同じ名前のファイルが複数の実行にあるときは、取り違えるより**埋めない**（プロトタイプと同じ）。
  新規登録を伴う取り込みは、監視を**手で開始している間だけ**行う（§5.1・§6-11）。
  既に `/history` から消えていれば救えない（それが L2/L3 になる理由）。
  **ComfyUI につながらないときは黙って飛ばす**（起動のたびに「つながりません」の帯を出さない）。
  > **点検で見つかった誤り**: 以前は「起動時に `GET /history` を 1 回全部走査し、未登録なら `asset` として
  > 登録する」としていた。決定「監視は必要なときだけ手で開始」の外で画像を自動的に取り込むことになり、
  > ComfyUI が止まっていれば起動のたびにエラーの帯が出ていた。プロトタイプの `capture_history`
  > （`src/image_reviewer/capture.py`）は既に「登録済みで `en_text` が空の画像だけを埋める」振る舞いなので、
  > 設計を実装に合わせた。

**アプリ側の変更を要求しない**のがこの方式の利点。利用者がどの経路で投入しても
（ComfyUI の画面からでも、別の生成アプリからでも）、`/history` に入る実行は同じように拾える。

### 5.1 取りこぼしを減らす（相手側に頼らずに）

**他のアプリに sidecar を書かせる案は無い。** 連携しないと決めたので（`design.md` §18）、
相手側の変更を前提にした確実化はできない。そこで**このツールの中で**取りこぼしを減らす:

| 手段 | 内容 |
| --- | --- |
| 監視を回す時間を短くする | 生成を回す前に開始し、終わって取り込めたのを確かめてから止める（利用者の回答: 必要なときだけ手で開始） |
| `GET /history` の救済走査 | 監視の開始時と、`/history` が空に近づいたときに全部走査する（§5）。**起動時の 1 回は既に登録済みの画像の値を埋めるだけ**で、新しい画像は登録しない（登録は監視の実行中だけ） |
| 画面に「取りこぼしの疑い」を出す | 監視を止めている間の時間帯と、`output_dir` に新しいファイルが増えているのに未登録のとき、1 行で知らせる |
| 手で入れる経路を必ず残す | ドラッグ&ドロップとフォルダ走査。**訳は失われるが、絵と来歴（PNG から読める分）は残る** |
| 訳が無い画像の明示 | `text_not_captured` を理由として出し、画面から訳を入れて L3 に進める（§8-5） |

- 監視を常駐させない方針（利用者の回答）なので、**「監視を止めている間の生成は訳を失う」**ことを
  画面と設定に明記する。これは仕様として受け入れる（あとから訳し直せる。§4.2）。
- **監視を止めている間に `output_dir` へ増えた画像は、こちらから登録しない。** 画面に「取りこぼしの疑い」を
  1 行で出すだけ（上の表）にして、取り込みは**監視の実行中**と、利用者が明示した D&D・フォルダ走査に限る（§6-11）。
- ComfyUI 側の保持件数を増やす設定があるなら併せて案内する（**未確認**）。

---

## 6. やらないと決めること

1. **画像の生成を実行しない。** 画像を作るために `/prompt` を投げない。投入するのは利用者で、
   このツールは「投入できる形」と「出てきた結果の記録」だけを扱う（§1・§4）。
   **ただしタグ付けと訳し直しには `/prompt` を使う**（画像を作るのではない。
   [`design.md`](design.md) §6.3.2 の表で明確にした）。
2. **画素一致を目標にしない。** 「完全」＝ 条件が同一。画素の一致は測って添えるだけ（§1）。
3. **ComfyUI の実行キャッシュや内部状態に踏み込まない。** 公開 API だけを使う。
4. **モデルを自動でダウンロードしない。** 数 GB を勝手に取らない。
   「この名前のモデルが必要です」と出して、利用者に任せる。
5. **再現の結果で元の記録を書き換えない。** 別レコード・別 asset として残す（§4.8）。
6. **`?template=` や `?workflow=` に頼らない。** 存在しないか、対象が違う（§2-8）。
7. **API 形式の JSON を `user/default/workflows/` に置かない。** 開けない（§3.2）。
8. **閾値をコードに埋めない。** 合否は人が付ける（§1）。
9. **`illust-authoring` の API を呼ばない・ストアを読まない。** 連携しない（§1 の注記）。
   判断の語もこのツールのもの（**キープ / ボツ**）を使う。
10. **プリセットを他のカットへ適用しない。** エージェント向けのプリセット API も、
    プリセット由来のスマートフォルダも作らない。人が参照してコピーするだけ（§4.10）。
11. **監視を開始していない間に、新しい画像をカタログへ自動で登録しない。** 監視は「必要なときだけ手で開始」する
    （決定）。起動時の救済は**既に登録済みの画像の値を埋めるだけ**で、取り込みは監視の実行中と、
    利用者が明示した D&D・フォルダ走査だけにする（§5・§5.1）。

---

## 7. 工程への反映

`design.md` §14 の工程に含める（P3 の一部と P7）。内訳:

| 順 | 内容 | 完了条件 |
| --- | --- | --- |
| 3-1 | PNG の `prompt` / `workflow` 解析、来歴の表示、日本語原文 | 画面に来歴と日本語が出る |
| 3-2 | グラフの書き出し（UI / API 形式）と D&D 案内、`POST /api/userdata` への設置 | UI 実行画像のワークフローを開ける（**R4a**） |
| 3-3 | 訳し直し（**`TextGenerate` の再実行のみ**）と出所の区別 | 英訳が出て「訳し直し」が区別して出る |
| 3-4 | 監視（`/api/jobs` のスナップショット、sidecar、`/history` の救済）と**捕獲の 3 手順**（リスト・グラフでの由来確認・`final_prompt` の再構成） | `/history` に残っている既存の実行を使って、**既に登録済みの画像に**訳と `final_prompt` が正しく入る（**新しい画像が登録されないこと**も確かめる） |
| 7-1 | 再現キー、判定（完全/近似/不可）、書き出し前の検査、印つきの書き出し、seed 違いの書き出し | 判定と理由が出て、**前提（§4.7.1）を満たすワークフローでは**印つきのグラフを書き出せる。満たさないときは「印を付けられません」と理由が出る |
| 7-2 | 監視での結果取り込み（印との照合）、比較、合否の記録 | 書き出したグラフで作った画像が記録に紐付き、**合否が消えない形で**残る |

- 3-4 は 3-3 より先に置く（**今後の画像を守る方が、過去を訳し直すより価値が高い**）。
- 7-2 の順は **書き出し（印つき） → 利用者が投入 → 監視で結果を取り込み → 比較 → 人が合否**。
  **生成は含まない**（利用者が ComfyUI に投入する。§6-1）。
- **Ollama は工程に入れない**（利用者の回答で今回使わない）。
- 監視の確認は `/history` に残っている実行で行う（新規に生成しないと確かめられない項目は、
  利用者に 1 回生成を頼んで確かめる。`design.md` §14 P3 に同じ但し書きがある）。

---

## 8. 決めていないこと

1. **モデルのフルハッシュを取るタイミング。** 既定は `(名前, size, mtime)`（§4.6）。フルハッシュは
   任意で取れるようにするが、いつ取るか（登録のとき / 初めて書き出すとき / 手動のときだけ）は決めていない。
   53 GB で約 2 分かかるので、走査のたびには取らない。
2. **印（marker）の形式をどこまで厳密にするか。** 今の案は `repro-<attempt_id>/seed-<seed>` という
   文字列を `filename_prefix` に置くだけ（§4.7.1）。人が消せる・書き換えられる場所なので、
   どこまでを「印あり」と認めるか（前方一致でよいか、PNG の `prompt` チャンクの値まで確かめるか）を決めていない。
   **（印を付けてよい前提と、外れたときの落とし方は §4.7.1 で決めた。ここに残るのは「印あり」の認定の厳しさだけ。）**
3. **結果が複数枚出たときの扱い。** 1 回の書き出しから `SaveImage` が複数枚出す場合や、
   `KSampler` が複数あって枚数が増える場合に、全部を 1 つの `recipe_export` にぶら下げるか、
   枚ごとに分けるか。比較と合否をどこまでまとめるかも併せて決める。
   **（複数の保存ノードには同じ印を入れることと、seed を書き換えるのは保存ノードから遡って最初の `KSampler` 1 つ
   であることは §4.7.1・§4.7.2 で決めた。ここに残るのは、出た複数枚を 1 つの `recipe_export` にまとめるかどうか。）**
4. **手作業の後処理を通った画像の扱い。** 生成後にレタッチ・切り抜き・別形式保存をした画像は、
   条件が同一でも画素が別物になる（`manual_step`）。これを「結果」として受け取るか、
   別の画像として扱って紐付けを切るか。手作業の有無を人が申告するのか、自動では分からない。
5. **`text_not_captured` の画像を、どう扱うのが親切か。** 画面で訳を入れて L3 に誘導するのが本筋だが、
   「まとめて訳し直す」も選べるようにするか。
