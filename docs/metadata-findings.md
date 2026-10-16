# 実機で確認した前提（画像メタデータと ComfyUI の実態）

- 調査日: 2026-10-13 以降のセッション
- 調査方法: 読み取りのみ。PNG のチャンクを Python 3.12 で直接パース、ComfyUI の REST を実測、
  ディスク上のファイル一覧を確認。
- この文書は設計の根拠。**「確認済み」と「未確認」を区別して書く。** 推測で埋めない。

実機環境:

| 項目 | 実測値 |
| --- | --- |
| ComfyUI | `C:\ai\ComfyUI_windows_portable\ComfyUI`、**127.0.0.1:8188 で稼働中** |
| ComfyUI 版 | 0.39.2 / frontend 1.53.10 / 同梱 Python 3.13.14 |
| ComfyUI の ONNX | `onnxruntime-gpu 1.30.0`（providers: Tensorrt / CUDA / CPU） |
| GPU | RTX 3090 24GB + RTX 3060 12GB（ドライバ 610.88） |
| ComfyUI の出力 | `ComfyUI\output`（直下に 1,028 枚 / 1.14GB） |
| 実データ規模 | `ComfyUI\output` 1,028 枚、`backend-comfyui-anima\realcheck\out` 3,999 枚、`illust-authoring\.store` 1,204 枚 |
| Ollama | **127.0.0.1:11434 で稼働中** |
| ツール側 Python | `Python312` は pillow のみ。`uv 0.12.19` あり、PyPI から解決可 |

---

## 1. PNG に埋まるメタデータは「誰が実行したか」で変わる

**確認済み。** PNG のテキストチャンクを実測した結果、2 種類ある。

| 実行経路 | `prompt`（API 形式） | `workflow`（UI 形式 v0.4） |
| --- | --- | --- |
| ComfyUI の画面から実行 | あり | **あり**（完全な UI グラフ） |
| API 投入（`POST /prompt`。E9 バックエンド・probe・アプリ） | あり | **なし** |

- `illust-packs/backend-comfyui-anima` の `comfy.py` は `POST /prompt {"prompt": graph, "client_id": ...}` のみを送る
  （`extra_data.workflow` を送らない）ため、API 生成の画像に `workflow` は付かない。
- 確認した実例:
  - UI 実行: `ComfyUI\output\ComfyUI\Anima\20261013\11*_00001_.png` は `prompt` と `workflow` の 2 チャンク。
  - API 生成: `ComfyUI\output\naedoko_0040*.png` は `prompt` のみ（`anima-turbo-v1.1` + `qwen_3_06b_base`）。
- いずれも **iTXt / zTXt は無く tEXt のみ**。チャンクは IHDR / IDAT / IEND + tEXt。

`prompt`（API 形式）から直接読めるもの:

- `class_type` ごとの `inputs`。ノードキーは `"1"`〜`"N"`。
- モデル名（`UNETLoader.unet_name`）、CLIP（`CLIPLoader.clip_name`）、VAE（`VAELoader.vae_name`）、
  LoRA（`LoraLoaderModelOnly.lora_name`）、`KSampler` の `seed` / `steps` / `cfg` / `sampler_name` / `scheduler` / `denoise`、
  `EmptyLatentImage` の `width` / `height`、`SaveImage.filename_prefix`。
- `CLIPTextEncode.inputs.text` が**リテラルなら**その文字列（英文プロンプト）。
- `PrimitiveStringMultiline.value` が**リテラルなら**その文字列（日本語原文）。

`prompt` から読め**ない**もの（重要）:

- リンクで渡っている値は入っていない。`CLIPTextEncode.text` が `["9", 0]` のようなリンク参照のとき、
  その最終テキストは PNG から復元できない。
- **`TextGenerate` の出力（英訳結果）は実行時の値であり、PNG に残らない。**

---

## 2. 「日本語 → 英訳」の実装（ja2en）

**確認済み。**

- ユーザーの言う「TextGenerator」に当たるノードは、**ComfyUI 本体同梱の `TextGenerate`**
  （`comfy_extras/nodes_textgen.py`、`io.ComfyNode`、`node_id="TextGenerate"`、`system_prompt` 入力あり）。
  `custom_nodes` 配下に `TextGenerator` / `TextGenerate` の文字列は **0 件**。特定パッケージのカスタムノードではない。
- 経路: 日本語 → `TextGenerate`（翻訳の決まりは本文ではなく **`system_prompt`**）→ `StringConcatenate`（品質語を前置）
  → `CLIPTextEncode`。
- 実ワークフロー `realcheck\workflows\ja2en_sysprompt_api.json` の `class_type` は 15 種:
  `UNETLoader` / `CLIPLoader`×2 / `VAELoader` / `PrimitiveStringMultiline`×2 / `TextGenerate` / `PreviewAny` /
  `StringConcatenate` / `CLIPTextEncode`×2 / `EmptyLatentImage` / `KSampler` / `VAEDecode` / `SaveImage`。
- 使うモデル: 画像 `anima-turbo-v1.1.safetensors`、TE `qwen_3_06b_base.safetensors`、VAE `qwen_image_vae.safetensors`、
  LLM `qwen3vl_8b_int8_convrot.safetensors`（断りにくい版 `qwen3VL8BHereticINT8W4A8_int8.safetensors`）。
- `system_prompt` の規則: 英語のみ・CJK 禁止／細部と順を保つ・足さない／特徴と動作を正しい人に結び付ける／
  日本固有語はローマ字（yukata, kotatsu, seiza）／left・right は人物の画面位置／出力はプロンプトのみ。
- `backend-comfyui-anima` の README は ja2en を**「システムには組み込まない」実証**と明記している（600 行目以降）。
  日本語のまま渡すと Anima の TE は日本語を読めず破綻が増える、という実測が根拠。

### 英訳は PNG から復元できない（設計上の最重要点）

**確認済み。** ja2en で作られた 6 枚（`output\ComfyUI\Anima\20261013\*`）を実測:

- 復元できる: **日本語原文**（`prompt` の node7 `PrimitiveStringMultiline.value`、`workflow` にも同値）、
  seed・steps・cfg・sampler・scheduler・denoise・解像度・モデル名・LoRA 名・VAE 名。
- **復元できない: 英訳結果。** `TextGenerate` の出力は実行時値で、`CLIPTextEncode.text` も
  `StringConcatenate.string_b` もリンク参照（リテラル文字列が無い）。
- **sidecar も無い**（同ディレクトリは PNG 6 枚のみ）。
- `GET /history` には `PreviewAny` の `text`（LLM 出力）が入るが、**メモリ上のみ**。稼働中のサーバの 419 件に
  該当 6 枚は **0 件**で、既存画像の英訳は PNG からも history からも**復元不能**。
- sidecar が存在したのは `realcheck\out\llm-translate-*\` の `texts.md` / `texts.json` / `counts.txt` のみ
  （ja・tags・en・llm-expand・llm-faithful と seed / 秒 / 語数を記録）。

→ **帰結**: 「生成に用いた日本語」は常に PNG から取れる。「英訳された結果」は
(a) 生成時に捕まえて sidecar に残す、(b) 後から再翻訳する、のどちらかしかない。
**(b) は「そのとき使われた訳」ではなく再生成である。** 設計では両者を別の `en_source` として区別し、
再生成には画面で印を付ける（`docs/design.md` §7）。

---

## 3. ワークフローへのリンク

**確認済み（取得経路）／未確認（ディープリンク）。**

- 保存済みワークフローは `ComfyUI\user\default\workflows\` の 19 ファイル:
  `dog.json` / `ja2en_4b_int8.json` / `ja2en_first_4b_int8.json` / `ja2en_sysprompt_workflow.json` /
  `NoctQ_V4.json` / `pack-CUT01-ja.json`〜`pack-CUT12-ja.json` / `sample.json` / `sample2.json` / `sample2 (Copy).json`。
- 取得 API（実測 200）: `GET /api/userdata?dir=workflows&recurse=true&split=false&full_info=true`、
  `GET /api/userdata/workflows%2F<name>.json`。
- **URL で特定ワークフローを開くパラメータは無い。** `?workflow=` は実装されていない
  （`PRESERVED_QUERY_NAMESPACES` に WORKFLOW 名前空間が無い）。`?template=<id>` は**存在する**が、
  開けるのは同梱テンプレート（`/templates/<id>.json`）かカスタムノードの `example_workflows` だけで、
  `user\default\workflows\` のファイルには使えない。
  → **利用者のワークフローを URL で開く手段は無い。**
  なお `GET /userdata/{file}` は `Content-Disposition: attachment` を返すため、URL を開いてもロードされない。
- **API 形式 JSON はフロントエンドが自分で読める（当初の推定は誤り）。**
  `app.ts` の `handleFile` が `isApiJson()` で判定し、`loadApiJson()` が API → UI の変換
  （`LiteGraph.createNode` → ウィジェット復元 → `rootGraph.arrange()`）を行う。D&D と「Open」ボタンが同じ経路。
  判定は全エントリが `class_type: string` と `inputs: object` を持つことが条件。
- 確実な経路は 3 つ: (a) `user\default\workflows` に置いてサイドバーから選ぶ（**UI 形式のみ**。
  API 形式を置いても `loadGraphData` 経路では開けない）、
  (b) JSON をキャンバスへドラッグ&ドロップ（**UI 形式でも API 形式でもよい**）、
  (c) API で取得して `/prompt` に投入する（＝再生成）。
- 書き込み経路: `POST /api/userdata/{file}`（body は生バイト列、`overwrite=false` で既存があれば 409、
  `mkstemp` + `os.replace` の原子的置換）。
- 前例: `realcheck\workflows\make_ja2en_workflow.py` が **UI 形式 v0.4 を生成**している
  （API 形式 → UI 形式の変換を自前で行いたい場合の参考。ただし通常は不要）。

> 詳細な引用（ソースマップの TypeScript 原文つき）は
> [`comfyui-reproduction-findings.md`](comfyui-reproduction-findings.md) §1〜§4 にある。

→ **帰結**: 画像に `workflow` があればそれを `.json` に書き出して D&D させるのが最も確実。
`prompt` しか無い画像は UI 形式へ変換してから渡す。URL 一発で開く案は**前提にしない**。

---

## 4. Danbooru タガー（WD14）

**確認済み。**

- 実在する ONNX モデル:
  - `custom_nodes\ComfyUI-WD14-Tagger\models\wd-eva02-large-tagger-v3.onnx`（1,260,435,999 B）+ `.csv`（308,468 B）
  - 同 `wd-v1-4-convnextv2-tagger-v2.onnx`（388,479,878 B）+ `.csv`
  - `C:\ai\kohya_ss\wd14_tagger_model\SmilingWolf_wd-eva02-large-tagger-v3\model.onnx` ほか
    （**ファイル名が `<model>.onnx` でないため IllustTagger からは見つからない**）
  - ComfyUI の `models\onnx` は**空**、`models\wd14_tagger` は無い、`extra_model_paths.yaml` も無い。
- ノードは 2 種:
  - `IllustTagger`（`custom_nodes\illust_tagger` は `backend-comfyui-anima\comfy_nodes\illust_tagger` へのジャンクション）。
    INPUT `image / model(既定 wd-eva02-large-tagger-v3) / threshold 0.2 / character_threshold 0.85`。
    RETURN `("STRING",)`、`OUTPUT_IS_LIST=True`、`ui.scores` に `[[tag, score], ...]` の JSON（確からしい順）。
    モデルごとにセッションを保持。
  - `WD14Tagger|pysssss`。INPUT `image / model / threshold 0.35 / character_threshold 0.85 / replace_underscore /
    trailing_comma / exclude_tags`、RETURN `("STRING",)`（**スコア無し、毎回モデル再読込**）。
- 速さ（README の実測値、RTX 3090。**未再計測**）: IllustTagger は初回 3.6 秒 / 以後 0.5 秒、4 枚で 2.1 秒。
  WD14 ノード 2 段は CPU 約 8 秒・GPU 4.4 秒。
- タガーの限界（README 実測）: 人数・性別 63/64、向き 50/51、距離は腿までが弱い、**手の破綻の語は出ない**、
  `straight-on` は語として出ない。
- スコア付きで返るので閾値は呼ぶ側で決められる。CSV にカテゴリ列があるため
  general / artist / copyright / character / meta の区別が可能。

→ **帰結**: 内蔵実行（onnxruntime-gpu + 同じ `.onnx` を直接使う）が可能。モデルの実体は
`ComfyUI-WD14-Tagger\models\` にあり、ファイル名は `<model>.onnx` / `<model>.csv`。**設定で明示パスを指せるようにする**
（kohya 側の `model.onnx` 命名差を吸収するため）。

---

## 5. 参考にした既存実装（連携はしない）

別プロジェクト `illust-authoring` を**読み取り専用で**調べた。調べたのは**設計の判断材料**としてであり、
**このツールは同プロジェクトとコードもデータも連携しない**（呼び出し・取込・書き戻しのいずれもしない。
今後の予定も無い）。以下は「その観察から何を決めたか」だけを残す。

**確認済み**（読み取りのみ。このツールの設計は以下の観察だけを材料にしている）。

- 選別の印は**条件 ID → `"yes"`/`"no"` の ○/×** で、**数値の rating / score を持たない**（点数制を明示的に却下していた）。
  → **このツールも点数制を採らない**根拠の 1 つ。判断は条件ごとの ○/× と理由で残す（`docs/design.md` §9.2）。
- 判断が**メモリ内だけ**に入り、再起動で消える実装があった。
  → **判断は必ず永続化する**（`decision` 台帳に追記のみ。`docs/design.md` §5）。
- 画像を絶対パス（`artifact.ref`）で参照し、一覧・レビューの API 群を持っていた。
  → 「画像は場所ではなく内容で同定する」という**このツール側のデータモデルの判断**
    （[`duplicates-deletion-backup.md`](duplicates-deletion-backup.md) §1）を自分の言葉で固める材料にした。
    パスは従属、正体は `sha256`。
- API に **CORS ミドルウェアが無く**、別オリジンのブラウザからは呼べない構成だった。
  → このツールも**ブラウザから他ツールを直接叩く構成を避ける**（そもそも他ツールを呼ばない）。
- 候補の状態を `candidate | draft | final | rejected | reference` のように**多数の値を 1 つの列**で持っていた。
  → このツールの外部契約は、**レビュー状態を `kept` / `rejected` / `unreviewed` の 3 値**に絞り、
    判定（verdict）を `keep` / `reject` / `clear` の**別の値**にする
    （[`review-export.example.json`](review-export.example.json) と `docs/design.md` §6.2）。

> 上記は**このツールの設計判断**である。同プロジェクトの規約に合わせる必要は無く、
> 名前・スキーマ・値を揃える義務も無い（連携しないため）。

→ **帰結**: このツールは `illust-authoring` の HTTP API もデータ置き場も**使わない**。
接続先・取込・書き戻しの設計は行わない。

---

## 6. 未確認・要確認の項目

| # | 項目 | 状態 |
| --- | --- | --- |
| 1 | ComfyUI の URL で名前付きワークフローを開く方法 | **確認済み（無い）**。`?workflow=` 未実装。`?template=` は同梱テンプレート専用。→ §3 |
| 2 | IllustTagger の速度（0.5 秒/枚） | README の記載。**このセッションでは未再計測** |
| 3 | `/history` の保持件数と消える条件 | 419 件を確認。`MAXIMUM_HISTORY_SIZE` で切られる。**再起動で消える**（メモリのみ） |
| 4 | `POST /api/userdata/{file}` でワークフローを書き込めるか | **確認済み（書ける）**。ルート定義を確認。body は生バイト、`overwrite=false` で 409。**実際の書き込みは未実施** |
| 5 | JPEG / WebP 出力時のメタデータ | ComfyUI は既定 PNG。JPEG では tEXt が無く**グラフは残らない**見込み（未検証） |
| 6 | 別ツールのデータ置き場（`.store` など）を直接読む場合の整合性 | **対象外**。このツールは他ツールと連携しない（§5） |
| 7 | 実ブラウザでの D&D / Open の動作 | ソースコード（ソースマップの TypeScript）での確認のみ。目視は未実施 |
| 8 | 4 GB 超のモデルファイルの SHA-256 | 未計算（この設計では既定で取らない。`workflow-reproduction.md` §4.6） |
| 9 | `comfyui-anima-incontext` / `illust_tagger` の版 | **識別子が存在しない**（`pyproject.toml` も `__version__` も無い）。`__init__.py` の size/mtime で代用する |

---

## 7. 実測した性能（設計の数値根拠）

読み取りのみで計測。`ComfyUI\output` の 1,028 枚（1.14 GB）を使用。

| 項目 | 実測値 | 1 万枚の見込み | 計測条件 |
| --- | --- | --- | --- |
| PNG のチャンク走査 | **24,719 枚/秒** | **0.4 秒** | 256 KiB の読み取り上限 |
| 同（8 MiB 上限） | 9,726 枚/秒 | 1.0 秒 | 上限を広げても実用上同じ |
| メタデータの位置 | **先頭 22,178 バイト以内**（最大） | — | 全 1,028 枚で `prompt` を取得 |
| `workflow` を持つ割合 | **175 / 1,028 枚（17%）** | — | UI 起点の実行のみ |
| SHA-256 | **399 MB/s**（300 枚・410 MB を 1.03 秒で計測。291 枚/秒） | **28 秒**（1 万枚を 1.11 MB/枚 = **11.1 GB** として） | Python、1 MB ずつの読み |
| サムネイル生成（WebP 256px） | **36 枚/秒** | **4.7 分** | Pillow、1 スレッド |
| モデルファイルの総量 | `diffusion_models` 24.0 GB / `text_encoders` 27.6 GB / `loras` 1.7 GB | 53 GB で約 2 分（399 MB/s） | `/experiment/models/{folder}` とディスクの実測 |

**注意（実装時に踏んだ罠）**: PNG のチャンクは `長さ(4) + 種別(4) + データ(n) + CRC(4)` なので
**`12 + n` バイト進む**。CRC の 4 バイトを飛ばし忘れると 2 つ目以降のチャンクが全部ずれ、
`prompt` を 1 件も拾えなくなる（このセッションで実際に踏んだ）。
