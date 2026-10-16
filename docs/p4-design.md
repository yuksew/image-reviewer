# P4 の設計（タグと語釈）

- 対象: `C:\work\image-reviwer`（Python + FastAPI + SQLite + 素の JS の GUI）
- 位置づけ: [`design.md`](design.md) §14 の **P4（タグ）**の設計。**この段の正はこの文書**で、
  本文と食い違うときは **§0 が正**。
- 前提: **P5（判断と比較）と P6（要求と注記）は完了**（実装と 3 回の監査＋実行込みのやり直し）。
  この段はその上に足す（判断・要求・注記の道筋は変えない）。
- 要件: **R3**（Danbooru タグを表示。日本語の語釈を別に持つ）と **R7**（未タグ画像にタグ付け）。
- 言語: 日本語。**この文書に書いた数値は §12 の「未計測」を除いてすべて現物で測った**（測り方は §7 に書く）。

---

## 0. 拘束力のある差分（この段で決めたこと）

`design.md` の本文と食い違う点、および本文が黙っている点。**実装はここに従う。**

### 0.1 段の分け方と合格の線

| 段 | 内容 | 合格の線 |
| --- | --- | --- |
| **P4-0** | **機能を足さない。** v5 の移行（`tag` / `asset_tag` / `tag_gloss` / `job` / `job_item`）、契約（`Tag` に `gloss`）、`review.json` の `tags[]` を実際に埋める | 既存のテストが緑のまま。**v3 と v4 の DB から 1 回で v5** に上がり、**何度呼んでも同じ**。`tags` は空でも契約を通る |
| **P4-1** | **タガー**（内蔵と ComfyUI の 2 方式）、**背景ジョブ**（進行・中断・再開・失敗の記録）、タグの API（取得・手動の付け外し）、PNG の語の取り込み | §1.2 の線 1・2・7・8（**R3 の出所**と **R7**） |
| **P4-2** | **日本語の語釈**（見えた語だけ遅延で訳す、保存、人が直す、`edited=1` の保護） | §1.2 の線 3〜6（**R3 の語釈**） |
| **P4-3** | **画面**（拡大のタグ欄の 2 行表示、`#/tags`、`#/jobs` の最小形）、**タグでの絞り込み** | §1.2 の線 9 と、`gui_smoke` / `gui_layout` の合格 |

- **合格の線は P4-3 まで**。`design.md` §14 の P4 の完了条件が「タグが付く」「2 行で出る」「訳は見えた語だけ・保存して人が直せる」
  「**GPU の実測時間を計って記録する**」の 4 つを含むため、P5 のように後半を外さない。
- **Fable の監査は段ごと**に頼む（4 回）。各段で「実行して確かめた記録」を出す。

### 0.2 表は **v5** で作る（現物には無い）

- 現物の `src/image_reviewer/db.py:33` は **`SCHEMA_VERSION = 4`** で、表は
  `settings` / `root` / `reason_code` / `review_group` / `asset` / `asset_location` / `asset_meta` /
  `location_history` / `group_item` / `decision` / `comparison_cache` / `review_request` / `annotation` の 13 個。
  **`tag` / `asset_tag` / `tag_gloss` は 1 つも無い**（`design.md` §5.1・§5.6 に DDL だけがある）。
- したがって P4-0 で **v5** として足す。`design.md` の DDL をそのまま作り、§2.1 の差分だけ足す。
- 実データ `.data/db.sqlite3` は**いま `user_version = 3`**（263 枚）。サーバを次に起動したときに v4（P6）が当たり、
  P4 の実装後は v5 まで上がる。**v3 → v5 が 1 回の `migrate()` で通る**ことをテストで固定する（P6 の監査と同じ観点）。

### 0.3 `job` / `job_item` を**この段で初めて作る**（本文は前提のように書いている）

- `design.md` §5.5 に `job` / `job_item` の DDL があるが、**現物には表も実装も無い**（`grep -n "\bjob\b" src/image_reviewer/*.py` → 0 件）。
  走査（`scan.py`）もサムネイル（`thumbs.py`）も**同期**で走る。`#/jobs`（`frontend-design.md` §3 の 9 番）も無い。
- P4 は「1 万枚で 1.5 時間」（`design.md` §8.2）を扱うので、**ここで作る**。
  - **`job` の状態は `design.md` §5.5 の 5 語**（`queued` / `running` / `done` / `failed` / `cancelled`）。
  - **ワーカーは 1 本**（プロセス内の 1 スレッド）。`design.md` §8.2 の「GPU の同時実行は 1」をスレッド数で満たす。
  - **進みはポーリング**（`GET /api/jobs/{id}` を 2 秒ごと）。**SSE（`GET /api/events`）は作らない**（P6 と同じ判断。
    `design.md` §6.1 の `events` は未実装のまま）。
  - **中断**は画像 1 枚ごとに印を見る。**再開**は同じ `kind` をもう一度流せばよい（**既に付いた語は飛ばす**。§0.11）。
  - **失敗は 1 件ずつ `job_item` に残す**（`design.md` §5.5 の趣旨。まとめて握りつぶさない）。

### 0.4 実行方式は「**検出して決める**」（既定は本文どおり `builtin`）

`design.md` §8.2 は「内蔵（`builtin`）を既定、`comfyui` も可」。**この環境の現物**:

| 方式 | 現物 | 判定 |
| --- | --- | --- |
| `builtin` | **`onnxruntime` が入っていない**（`uv run python -c "import onnxruntime"` → 見つからない。`pyproject.toml` の依存は fastapi / uvicorn / pillow / numpy の **4 つ**（点検 D-12））。モデルは `C:\work\lora-studio\models\wd-eva02-large-tagger-v3\model.onnx`（1202 MB）＋ `selected_tags.csv`（10,861 行）に**kohya 命名**であって、自動探索では見つからない（`design.md` §8.2 の指摘どおり） | **今は使えない**（導入すれば使える） |
| `comfyui` | **ComfyUI 0.39.2 が動いている**（`GET http://127.0.0.1:8188/system_stats` → 200）。`WD14Tagger\|pysssss` と `IllustTagger` の両方があり、`wd-eva02-large-tagger-v3` を選べる。モデルは ComfyUI 側の `custom_nodes\ComfyUI-WD14-Tagger\models\` にある | **今すぐ使える** |
| `builtin`（ComfyUI 同梱の `python_embeded` で測った値） | `python_embeded` には **`onnxruntime-gpu 1.30.0`** があり、`CUDAExecutionProvider` が使える（実行で確認）。**RTX 3090 で 0.063 s/枚**（CPU は 0.75 s/枚） | **入れる価値がある**（P4-1。G-3） |

- 決め: **起動時と実行前に検出**し、`builtin` が使えれば `builtin`、使えなければ `comfyui`、**どちらも使えなければ
  job を開始せずに理由を 1 行で返す**（`design.md` §15 リスク 8 の fail-soft）。
  **利用者の指定（設定の `tagger.engine`）が最優先**で、`auto` のときだけこの順で選ぶ。
- `onnxruntime` は**任意依存**として入れる（`uv sync --extra tagger`。実装は P4-1。**この文書では入れない**）。
  **CPU でも動く**（`onnxruntime`）／GPU 版（`onnxruntime-gpu`）は CUDA を持ち込む。
- **（点検 B-2）`onnxruntime-gpu` は CUDA の DLL が無いと「黙って CPU に落ちる」。** 実行で確認:
  `InferenceSession(..., providers=['CUDAExecutionProvider','CPUExecutionProvider'])` を作っても
  **`get_providers()` は `['CPUExecutionProvider']` だけ**を返し、**例外は出ない**。先に `import torch` をすると
  `['CUDAExecutionProvider', 'CPUExecutionProvider']` になり **0.063 s/枚**（CPU は 0.75 s/枚。**12 倍**）。
  したがって:
  - `doctor`（または起動時のログ）には「GPU 版を入れた」ではなく **`session.get_providers()[0]` の実際の値**を出す
    （例:「内蔵タガー: 使えます（CUDAExecutionProvider）」「内蔵タガー: 使えます（CPU。CUDA の DLL が見つかりません）」）。
  - **CUDA / cuDNN の DLL を自分で用意する**（`onnxruntime-gpu` のホイールには入っていない）。**`uv sync --extra tagger`
    だけでは GPU にならない**。これを **P4-1 の作業に入れる**（G-3）。§10-2 にも未確認として残す。

### 0.5 ComfyUI 経由の作法（**実行して確かめた**）

**（点検 A-4 / G-2）既定のノードは `IllustTagger`。** 理由: **スコアが返り**（§B-1）、**別々の画像で 0.26〜0.31 s/枚**
（`WD14Tagger|pysssss` は **2.8〜3.4 s/枚**でスコアも返さない。§7 の実測表）。

- **`IllustTagger`**（既定）: 入力は `image` / `model`（文字列）/ `threshold` / `character_threshold`。
  出力は **`outputs[node]["scores"]` が「1 要素の配列」で、中身は `[["1girl", 0.9931], …]` の JSON 文字列**（実測）。
  **`json.loads` してから使う**。名前は**空白形**（`black hair`）なので、**`_` に直してから**保存する（§0.7）。
  **スコアは `round(p, 4)` の 4 桁**（ノードの中。`illust_tagger/__init__.py:96`）。**受け取った値をそのまま入れる**
  （§0.10 の「丸めない」は**ノードの外では守れない**）。
  同じ閾値で **`WD14Tagger` と語の集合は一致**（実測 66 = 66）。
- **`WD14Tagger|pysssss`（選択肢として残す。既定にはしない）**: 入力は `image` / `model` / `threshold` /
  `character_threshold` / `replace_underscore` / `trailing_comma` / `exclude_tags`（`/object_info` で確認）。
  - **`replace_underscore=false`** で呼ぶ（正規形 `long_hair` が返る。`true` だと `long hair` になり、
    CSV の語と一致しなくなる）。実測: `false` → `1girl, long_hair, breasts, looking_at_viewer, …`。
  - 出力は **`outputs[node]["tags"]` が「1 要素の配列」で、中身はカンマ区切りの 1 文字列**（実測。配列の要素ごとに
    1 語ではない）。**先頭要素を取り、`,` で割る**。
  - `trailing_comma=false`・`exclude_tags=""` で呼ぶ（空の語を作らない）。
  - **スコアを返さない**（`tags` の文字列だけ）。**このノードを選ぶと `asset_tag.score` は全部 `NULL` になる**（点検 B-1）。
  - **呼ばれるたびに 1.2 GB の ONNX を読み直す**（`wd14tagger.py:58` が毎回 `InferenceSession(...)` を作る。
    実測: session の作成 2.0〜2.3 s ＋ 推論 0.44 s ≒ **2.9 s/枚**）。**遅い理由はこれ**（§7）。
- **グラフには出力ノードが要る**（`TextGenerate` は `output_node: false`）。タガーは `output_node: true` なので
  そのままでよいが、`/history` を読む側は**ノード番号を決め打ちしない**（`scores` / `tags` を持つ出力を探す）。
- 投げ方は `POST /prompt`（`{"prompt": <API 形式のグラフ>, "client_id": <ULID>}`）→ `GET /history/{prompt_id}` を
  0.5 秒ごとに見る。**この段で初めて ComfyUI に「投げる」**（`capture.py` は読み取りだけだった）。
  `design.md` §6.3.2 の表（画像の生成はしない／タグ付けと訳はする）が根拠。

**（点検 A-2）実データの画像はそのままでは食わせられない。** `LoadImage` の `image` は **ComfyUI の `input/` の
一覧（COMBO、実測 2,233 件）**で、**絶対パスを受けるノードは `/object_info` に無い**（`path` / `url` / `file` を取る
Load 系は 0 件）。絶対パスを渡すと **400 `Prompt outputs failed validation`**（実行で確認）。実データ 263 枚のうち
ComfyUI の `output/` 配下は 1 枚・`input/` 配下は 0 枚なので、**`POST /prompt` だけでは 1 枚も付かない**。

したがって **ComfyUI 経由のときは複製を 1 枚作って渡す**（実行で通った手順）:

1. `POST /upload/image`（multipart。`type=temp`、`subfolder=image-reviewer`、`overwrite=true`）で複製を作る。
   実測 **907 KB が 6〜27 ms**。
2. `LoadImage` の `image` に **`image-reviewer/<name>.png [temp]`** を渡す（実測で通り、36 語が返った）。
3. **名前は `asset_id` にする**（同名の衝突を避ける。`[temp]` を付けた参照は ComfyUI が解決する）。
4. **付け終わったら消す**（**P4-1 の監査 C で確定**）。ComfyUI に消す口は無いので、
   **設定 `tagger.comfyui_temp`（ComfyUI の `temp` の絶対パス）を入れてあれば自分で消す**。
   監査の実測では、設定が無いまま走らせて **`temp/image-reviewer` に 53 枚 19 MB が残っていた**。
   消すのは 2 か所: **1 枚ごと**（`tag()` の `finally`）と**ジョブの終わり**（`cleanup()`＝取りこぼしの掃除）。
   **設定が無ければ消さない**（`temp` は再起動で消えるのに任せる＝G-6-(a)。`input/` に置くと
   10,000 枚で 10 GB 残る）。**「`temp` が再起動で消える」ことは未確認**のまま（§10-21）だが、
   設定を入れれば残らないので、この未確認は「消し忘れの保険」の話になった。
   ジョブは再開できる（§0.11）ので、途中で消えても付け直せる。
5. **`/history` の見張りは 0.05 秒ごと**（**P4-1 の監査 C-1 で確定**）。0.5 秒ごとだと 1 枚あたり
   **平均 0.45 秒の空き**が出て、API 経由で **0.72 秒/枚**だった（ノード単体は 0.26〜0.31 秒）。
   0.05 秒に詰めて **実測 0.51 秒/枚**（8 枚で 4.1 秒。`tools/probe_p4.py` が毎回出す）。
6. **同じ `asset_id` のまま中身が変わった場合**（パスの入れ替え）は、ComfyUI が `LoadImage` の出力を
   ファイルのハッシュで持つので**古い結果が返りうる**。`overwrite=true` で上げ直し、**中身が変わった画像は
   複製の名前を変える**（`<asset_id>-<sha256 の先頭 8 文字>`）ことで避ける。

- **内蔵を既定にできれば、この節の問題（複製・後始末・衝突・キャッシュ）は全部消える**（G-3）。§9 の順序も
  「内蔵を先に動かし、ComfyUI は `IllustTagger` で比べる」にしてある（点検 C-3）。

### 0.6 内蔵方式の前処理（**ノードの実装を読んで確定**。本文の「実測で確定」をここで埋める）

`C:\ai\ComfyUI_windows_portable\ComfyUI\custom_nodes\ComfyUI-WD14-Tagger\wd14tagger.py:50-107` を読んだ。
**内蔵でも同じ手順にする**（同じモデル・同じ CSV で同じ答えを出すため）:

1. `height = model.get_inputs()[0].shape[1]`（モデルから読む。決め打ちしない）。
2. 長い辺が `height` になるよう縮小（**`Image.LANCZOS`**）。
3. **白（255,255,255）の正方形**に中央寄せで貼る（余白は黒ではない）。
4. `np.array(...).astype(np.float32)` のまま（**0〜255。平均・標準偏差で正規化しない**）。
5. **RGB → BGR**（`image[:, :, ::-1]`）。バッチ次元を足す。
6. CSV を行順に読み、**`category == "0"` の最初の行**を `general_index`、**`category == "4"` の最初の行**を
   `character_index` とする（出力ベクトルの並びは CSV の行順）。
7. `general = result[general_index:character_index]` から `score > threshold`、`character = result[character_index:]` から
   `score > character_threshold`。**`all = character + general`**（キャラが先）。
8. **rating（category 9）は捨てる**（ノードも捨てている。`wd14tagger.py:96` はコメントアウトされている）。
9. 閾値の既定は **`0.35` / `0.85`**（ノードの既定と同じ。設定で変える）。

- **（点検 C-2）この前処理で内蔵の出力が ComfyUI の出力と語単位で一致することを実行で確かめた**:
  同じ画像で **66 語 = 66 語、差 0**（CPU・CUDA とも。`builtin_tag.py` / `builtin_tag_cuda.py`）。
  したがって **§1.2 の線 8 は内蔵側だけなら通る**（ComfyUI と比べるときは**エスケープを外して**比べる。C-3）。
- **前処理を 1 つでも変えると語が変わる**（同じ画像での実測。**実装で「ついで」に変えない**）:
  **RGB のまま**（BGR にしない）→ **62 語**（＋5 −9）／**0〜1 に正規化**（平均・標準偏差で割る）→ **9 語**（ほぼ全滅）。
  黒パッド（白でなく）はこの画像では差 0（余白が無い画像。**縦横比の違う画像では未確認**。§10）。
- 閾値のぎりぎりの語（実測）: `dress_shirt 0.3512`、`see-through_shirt 0.3532`。**比較は float32 の生の値で**（§0.10）。
- 位置の実測: `general_index=4`、`character_index=8110`（CSV は rating 4 行 → general 8,106 行 → character 2,751 行の
  順で、**カテゴリは連続**して切り替わりは 3 回）。§0.6-6 の「最初の行」の決め方で正しい。
  ただし**他のモデルの CSV で順が違う可能性**があるので、**「`category` が連続していない CSV は拒否する」**を
  §3.2 の検査と §10 に足す（点検 C-2）。

### 0.7 語の正規形とカテゴリ（本文は「Danbooru の正式名」としか書いていない）

- **`tag.name` は正規形（小文字・語間は `_`）**。`long_hair` / `looking_at_viewer`。表示でもこの形をそのまま出す
  （**画面で勝手に空白へ直さない**。Danbooru の正式名と一致させ、CSV との突き合わせを壊さない）。
- **（点検 A-1）取り込み時の正規化: 前後の空白を落とす → 空白を `_` に → 小文字に → `\(` `\)` のエスケープを外す。**
  **括弧とコロンは語の一部として残す**（`admiral_(kancolle)` / `rem_(re:zero)` / `2b_(nier:automata)` / `:d`）。
  - 理由（実行で確認）: `wd-eva02-large-tagger-v3.csv` の 10,861 行のうち **括弧を含む語 1,596**（一般 204 /
    **キャラ 1,392 = キャラ名 2,751 の 51%**）、**コロンを含む語 41**（`:d` `:o` `:3` …）。ノードは
    `wd14tagger.py:97` が `(` → `\(`、`)` → `\)` にエスケープして返す（実測: `admiral_\(kancolle\)` /
    `2b_\(nier:automata\)` / `rem_\(re:zero\)`）。**設計の前の版のように括弧を落とすと 1,619 語が別の文字列になり**
    （`admiral_\(kancolle\)` → `admiral_kancolle`）、**語彙に一致しないのでキャラ名が全部落ちる**（線 8 の集合比較も崩れる）。
  - **`[` `]` は落としてよい**（CSV に `[` を含む語は 0 件。実測）。
  - **重みの `:` は外す**（`:数字` の形。§0.8-2）。
  - 画面には **`rem_(re:zero)` とそのまま出る**（G-5 で了解済み。`design.md` §16.1 の「括弧書きは使わない」は
    **語釈の 2 行目に括弧書きを足さない**という意味で、**語そのものの括弧は消さない**。§5.1 に 1 行）。
- **カテゴリは CSV から引く**（`category` と `category_name`）。CSV が無ければ `null`。
  - **実測**: `selected_tags.csv` の 10,861 行の内訳は **category 0（general）8,106 / 4（character）2,751 / 9（rating）4**。
    **artist(1) と copyright(3) の行が無い**（eva02 v3 の CSV の性質）。したがって画面の並び
    「キャラ → 作品 → 一般」は、**この CSV では「キャラ → 一般」**になる。**画面の見出しは、語が無いカテゴリを出さない**
    （空の見出しを作らない）。
- `trailing_comma` や `exclude_tags` は**使わない**（語を落とす判断は画面と設定でやる。§0.8 の「既知語のみ」と同じ考え）。

### 0.8 PNG の語（`source='png'`）は `final_prompt` から**決定的に**切り出す

- 出所の 1 つ目（`design.md` §8.1）は「PNG のプロンプトから語を切り出したもの」。**現物の持ち場**は
  `asset_meta.meta_json` の **`final_prompt`**（`capture.py:153` が再構成して入れる。**`final_prompt` が空でないのは
  180 枚**（点検 D-2。`meta_json` が dict なのは 183 枚、`"null"` の行は 80 枚）。
  例（実データ）:
  `masterpiece, best quality, score_7, safe, 1girl, 1boy, (three quarter view:1.5), upper body, simple background,
  white background, smartphone, looking at phone, looking to the side. First girl: black hair, long hair, red eyes, …`
- **そのまま割ると語にならない**（`looking at phone` のような句や、`First girl: black hair` のような自然文が混ざる）。
  決め（**点検 B-4 / G-4-(b) を反映**）:
  1. `final_prompt` を **`,` と `.` で割る**（`.` でも割るのは、実データが
     `looking to the side. First girl: black hair, …` の形で、**`.` の後ろに語が続く**ため）。
  2. 各断片から **`First girl:` / `Second boy:` のような前置き**（`^(first|second|third|…)\s+\w+:`）を外し、
     **外側の 1 組の重み `( … :1.5)` と `:数字` だけ**を外し（`(three quarter view:1.5)` → `three quarter view`）、
     `\` を外し、前後の空白を落とす。**内側の括弧は語の一部なので触らない**（§0.7 / 点検 A-1）。
  3. 正規形（§0.7）に直す。
  4. **断片を正規形に直したものを全部 `tag` に採る**（`source='png'`）。**語彙（CSV）にあるかどうかは
     `tag.known` で持つ**（利用者の回答 Q1。2026-10-16）:
     - `known=1`: CSV の語彙にある語（WD14 が付ける語と同じ綴り）。
     - `known=0`: 語彙に無い語（PNG の自然文から来た断片など）。
     - **画面と API は `known` を返す**。既定の表示は**両方**出す（`known=0` には印を付ける）。
       **タグ検索（`?tag=`）は既定で `known=1` だけに当てる**（自然文の断片で検索が汚れないように。
       `?tag=…&known=0` で明示すれば語彙外も引ける）。
     - 理由: 「PNG に書いてあった語を失いたくない」（利用者の回答）。元の文は `final_prompt` にも残るが、
       **語として引ける**ことに意味がある。
  5. **採った数と、語彙外だった数を job の結果に残す**（黙って捨てない。
     例: 「PNG の語: 42 語を採用（うち語彙外 11 語）」）。
  6. **語の長さの上限と空の断片**（点検 §I）: **空の断片は入れない**。**64 字を超える断片は入れずに数える**
     （実データに **252 字の文がそのまま 1 語になる**例があった。`,` と `.` で割っても文が残る）。
     上限は設定にして、job の結果に「長すぎて入れなかった数」を出す。
- **CSV が無い環境**では `known` を全部 0 にする（語彙の判定ができないだけで、**語は入れる**）。結果に 1 行で出す。
- **（点検 B-4）採用率の実測**（実データ、`final_prompt` のある 180 枚。`norm_check.py`）:
  断片 **4,964 → 採用 2,259（46%）／落ちる 2,705（54%）**（1 枚あたり採用 12.6・落ちる 15.0）。
  **`.` でも割り、`First girl:` の前置きを外すと 49%** になる（`black hair` などが拾える。G-4-(b)）。
  落ちる断片の上位は `masterpiece`(180) / `best_quality`(180) / `safe`(180) / `score_7`(170) /
  **`three_quarter_view`(68。語彙に無い)** / `adult_woman`(60) で、**品質語と自然文が大半**——
  「語彙にあるかどうかを `known` で持つ」という判断（Q1）はこの実測に合う。
  **設計の例に `three quarter view` を使わない**（語彙に無いので `known=false` になる。例は `looking_at_phone`＝語彙にある）。
- この切り出しは **GPU を使わない**（決定的）。タグ付けジョブの一部として走らせる（§3.2）。

### 0.9 語釈（`gloss`）の作法（**実行して分かったことを入れる**）

- 訳すのは **ComfyUI の `TextGenerate`**（`design.md` §8.4・§16.1）。**この環境で動くことを確かめた**（§7 の実測）。
  呼び方（実データの `textgen_params` と同じ形。**平坦なドット付きの鍵**で渡す）:

  | 入力 | 値 | 出所 |
  | --- | --- | --- |
  | `clip` | `CLIPLoader(clip_name=<設定の LLM>, type='qwen_image')` の出力 | 実データの `llm` は `qwen3vl_8b_int8_convrot.safetensors` |
  | `prompt` | **`1. 1girl` の形で番号を振って 1 行ずつ並べたもの**（§の下。点検 A-3 / G-1-(b)） | この段で決めた形 |
  | `max_length` | `512`（20 語で足りた。実測。**40 語でも足りた**） | 実データの `textgen_params` と同じ |
  | `sampling_mode` | **`"off"`**（G-7。**2 回同じ出力**を実測で確認。温度 0.7 だと訳が揺れ、人が直した語釈との差分が分からなくなる） | 実データは `"on"` だが、この段では**決定的**にする |
  | `thinking` / `use_default_template` / `mtp` | `false` / `true` / `"auto"` | 同上 |
  | `system_prompt` | **設定ファイルの文面**（コードに埋めない。`design.md` §7.3.2 と同じ規律） | この段で初期値を置く |
  | 出力 | **`PreviewAny` などの出力ノードを 1 つ繋ぐ**（`TextGenerate` は `output_node: false`） | 実測（繋がないと `prompt_no_outputs` で 400） |

- **（点検 A-3 / G-1-(b)）語との対応は「番号」で取る。** 前の版は「1 語 1 行・同じ順」で頼んで**位置**で対応させる
  設計だったが、**実行で成り立たないことが分かった**（`gloss_probe*.py`。`qwen3vl_8b_int8_convrot`）:

  | 頼み方 | 語数 | 返った行数 | 内容 |
  | --- | --- | --- | --- |
  | 位置（1 語 1 行） | 20 | 20 / **0** / 20 / 18 / 19 | 行数が合っても**対応が合わない**（`1girl → 男の子`）。英語のままの行、先頭 2 語が抜ける回、空文字の回 |
  | 位置（`sampling off`） | 20 | 18（2 回とも同じ） | 先頭 2 語が抜ける |
  | 1 語ずつ | 1 | 1 / 1 / **0** | `1girl` は**英語のまま**、`long_hair` は `長髪`、`looking_at_viewer` は**空** |
  | **番号付き（`1. 1girl`）** | 20 | **20/20 番号が取れ、全部日本語** | 4 回とも 20/20（`1girl → 1人娘 / 1人少女`）。**2 回同じ出力**（`sampling off`） |

  したがって次のように決める:
  1. **頼み方は `1. 1girl`（番号＋`.`＋空白＋語）**。`system_prompt` には「**1 行 1 語・同じ番号を付けて・訳だけを返す**」
     と書く（文面は設定に置く。§の表の `system_prompt`）。
  2. 返った本文を行に分け、**`^(\d+)[.)]\s*(.+)$` で番号を取る**。番号で語に対応させる（**位置に依存しない**）。
  3. **保存するのは「番号が取れた」かつ「本文が ASCII だけではない」行だけ**。英語のままの行（`1girl`）と空行は
     **保存しない**（「訳せませんでした」に入れる）。
  4. **取れなかった番号だけを 1 語ずつ訳し直す**（1 語ずつの経路は残す。ただし成功の条件は「行数 1」ではなく
     **「番号が取れて日本語が返った」**）。それでも駄目な語は**保存しない**（`tag_gloss` に行を作らない）。
  5. **部分的に当てはめてよい**（番号で対応するので、抜けた語があっても他の語の対応は壊れない。
     前の版の「部分的に当てはめない」は**位置対応だから必要だった規則**で、いまは要らない）。
  6. **空行は読み飛ばす**（実測で `胸\n\n見る` のように行間に空行が入る）。**番号の重複**（同じ番号が 2 回）は
     **その番号を捨てる**（どちらが正か決められない）。
- **まとめて訳す単位は最大 20 語**（実測: **番号付きで 20 語 4.6〜4.8 秒**。`sampling off` の初回は **10.1 秒**
  （模型の読み込み込み）。40 語でも 4.3 秒で 38/40 行が返ったので、**20 で始めて §10-4 で見直す**）。
- **`edited=1` の語は訳し直しで上書きしない**（`design.md` §8.4・§15 のリスク 15）。`source='manual'` の語釈も同じ。
- **見えた語だけ訳す**（画面に出ている語のうち、語釈が無いものだけ）。**先に全部は訳さない**
  （1 万枚で 40 万語になるため。`design.md` §8.4）。
- 語釈には**使った模型を残す**（`tag_gloss.engine`）。画面に「訳は自動」と出し、直す導線を必ず出す（`design.md` §15 のリスク 15）。

### 0.10 `GET` は書かない・`actor`・再送・決定性（前の段の教訓を最初から入れる）

| 論点 | 決め | 根拠 |
| --- | --- | --- |
| `GET` の副作用 | **`GET` は 1 バイトも書かない。** 語釈を取るのは `GET`、**訳すのは `POST`**。`GET /api/tags/gloss/pending` は**数えるだけ** | P5 の監査 C8/G2、P6 の §0.6。読み出しで模型を走らせない |
| 手動の付け外しの `actor` | **`human` だけ**（`POST` / `DELETE /api/assets/{id}/tags` は `human` 以外 **403**）。`source='manual'` は「**利用者が付けたもの**」だから（`design.md` §8.1） | 判断と同じ規律。エージェントは要求（R10）で求める |
| 再送（`client_token`） | **使わない。** `asset_tag` の主キーが `(asset_id, tag_id, source)` なので、**同じ語を 2 回足しても行は 1 つ**（`INSERT OR IGNORE` 相当）。語釈も `tag_id` が主キー | P5/P6 の `client_token` は「行が増える口」のためだった。ここは**口が冪等** |
| **語釈の口の冪等性**（点検 B-3） | **既定は「語釈の無い語だけ訳す」**（`force=false` のとき `tag_gloss` に行がある語は**模型を回さず `skipped`**）。2 回押しても 2 回目は**呼び出し 0 回**になるので `client_token` 無しで足りる | `POST /api/tags/gloss` は**模型を回すので冪等ではない**（2.5〜10 秒）。画面の二度押し・再送で同じ語を 2 回訳さない |
| 決定性 | タグの並びは **`category`（4 → 0 → その他）→ `score` の降順（`NULL` は最後）→ `name` の昇順**。同じ入力なら同じ並び（`review.json` を 2 回出して一致）。**`score` を返さない方式（`WD14Tagger`・内蔵）では全語が名前順**になる（点検 B-1 / F） | P6 §6.1 と同じ |
| 数値の丸め（点検 B-1） | **受け取った値をそのまま入れる**（こちらでは丸めない）。閾値との比較は**そのままの値**で行い、**表示は小数 3 桁**。**`IllustTagger` は `round(p, 4)` の 4 桁で返す**（ノードの中。`illust_tagger/__init__.py:96`）ので、**「`REAL` の生の値」はノード経由では守れない**。内蔵方式でも**この段ではスコアを保存しない**（語名だけ。生の float32 は持っているが、表示と並びには要らない） | P6 の点検 B1（`round` を挟むと境界が変わる）と同種の落とし穴を避ける。§4.3・§7 に「方式ごとにスコアが入るか」を明記 |
| 原子性 | 語・語釈・job は**すべて DB の行**（ファイルを書かない）。したがって一時ファイルも `os.replace` も要らない。**切り出しや書き出しのような失敗経路が無い** | `annotations.py` の切り出しとは性質が違う |

### 0.11 再開と「付いている語を飛ばす」

- 同じ画像に `source='wd14'` の行が**同じ `model` で既にあれば飛ばす**（`design.md` §8.2）。
  `params` の `force: true` で無視して付け直す（**古い行は消してから入れる**＝同じ語が二重にならない）。
- **`source='png'` は毎回やり直す**（GPU を使わず、`final_prompt` が変われば語も変わるのが正しい）。
- 中断した job の続きは、**同じ params でもう一度流す**だけ（既に付いた分を飛ばすので、実質の再開になる）。

### 0.12 契約（他ツールが読む形）

| 何を | どこに | 理由 |
| --- | --- | --- |
| タグ（`assets[].tags[]`） | **既存の** [`../schemas/review-export.schema.json`](../schemas/review-export.schema.json)（`Tag` は既にある。`include_tags=true` のときだけ出す。**`abi` は上げない**） | P4 で**実際に埋める**（いまは `export.py:481-483` が `doc["tags"] = []` の仮置き） |
| **語釈** | 同じ `Tag` に **`gloss`（`ja`）と `gloss_edited`** を**足す**（任意。既存の必須は変えない） | 語釈は R3 の答えの半分で、他ツールも「英語＋日本語」で読みたい。**足すだけ**なので古い読み手は壊れない |
| `Tag.source` に `manual` | 既にある 3 値（`png` / `wd14` / `manual`）を使う | `design.md` §8.1 |

- **`tag_gloss` の実体を `review.json` に二重に持たない**（`tags[]` の中に 1 語 1 行で入る）。
- P6 と同じく、**`additionalProperties: false` の契約に欄を足す**ので、**足した欄を実際に出す**ことをテストで固定する
  （P6-0 の監査 B1「契約に足したのに一度も出さない」の再発防止）。

### 0.13 画面（新しい画面を 2 つ作る。`frontend-design.md` に先に足す）

- **タグは詳細と拡大だけに出す**（利用者の指定。一覧には出さない）。**2 行**（1 行目 英語 / 2 行目 日本語の語釈）。
  **括弧書きは使わない**。書体を変えて対にする（`frontend-design.md` §2.3 の BIZ UDPMincho）。
- `#/tags`（**8 番。未実装**）: 語の一覧・件数・訳の確認と修正・「訳す」・「一括タグ付け」への入口。
- `#/jobs`（**9 番。未実装**）: 走査・タグ付けの進行、中断、失敗の一覧と再試行。
- **`frontend-design.md` には「タグの部品」（§4.x）が無い**（表示の規則は §11 の表と §6 の文言に散っている）。
  **実装の前に** §4 に 1 節足す（P6 の §5.5 と同じ流儀）。足すもの: 部品の形（2 行 1 組）、印（PNG / タガー / 手）、
  並び、語釈の「訳す」の見た目、「訳は自動」の 1 行、空のときの文。
- **画面の更新はポーリング**（ジョブは 2 秒、語釈は押したときだけ）。音は使わない（`design.md` §16.1）。

### 0.14 利用者の回答（**2026-10-16 に確定**）

| # | 論点 | **決定** | 補足 |
| --- | --- | --- | --- |
| **Q1** | PNG の語を「CSV にある語だけ」にするか | **全部入れて `tag.known` の印を付ける**（推奨とは違う。§0.8 の 4 を書き換えた） | 検索は既定で `known=1` だけに当てる（`known=0` は明示したときだけ） |
| **Q2** | 表示の語 | **`long_hair` のまま**（Danbooru の正式名） | 画面の表示だけの話（保存は `_`） |
| **Q3** | 手動のタグ付けを `human` だけにするか | **いまは `human` だけ**（`source='manual'`）。**必要になったらエージェントにも許す** | 403 の検査は 1 か所（`_require_human`）に置き、**後で外せる形**にする。`source='manual'` と `actor` は別の欄なので、許すときに意味が壊れない |
| **Q4** | 内蔵タガー（`onnxruntime`）を P4 で入れるか | **入れる。ただし後回しでよい**（まず `comfyui` で線 1 を通し、**語が一致するのを確かめてから**既定にする） | §9 の P4-1 は `comfyui` だけで線 1・2・7・8 を通せる形にしてある |
| **Q5** | 語釈の模型 | **`qwen3vl_8b_int8_convrot.safetensors`**（実データで使っているもの） | 設定 `gloss.llm` で変えられる（1 行） |

**点検（Fable）の G-1〜G-9 も、すべて「推奨」で確定した**（利用者 2026-10-16。上の Q1〜Q5 は生きたまま。
**G-2 で ComfyUI の既定を `IllustTagger` にしても Q5 は変わらない**＝語釈の模型は別の話）:

| # | 論点 | **決定（推奨どおり）** | 反映先 |
| --- | --- | --- | --- |
| **G-1** | 語釈の頼み方 | **(b) 番号付きの行**で頼み、番号で対応する（位置対応はやめる。4 回とも 20/20） | §0.9, §1.2 の線 6, §8.1-9 |
| **G-2** | ComfyUI 経由の既定ノード | **(b) `IllustTagger`**（スコアが返り 0.26〜0.31 s/枚。`WD14Tagger` は 2.8〜3.4 s/枚でスコア無し） | §0.5, §4.3, §7 |
| **G-3** | 既定の方式 | **(a) `auto` で内蔵優先**のまま。ただし **CUDA の DLL の用意**を P4-1 の作業に入れる（入らなければ CPU 0.75 s/枚でも `WD14Tagger` より速い） | §0.4, §7, §9, §10-2 |
| **G-4** | PNG の語の切り方 | **(b) `,` と `.` で割り、`First girl:` の前置きを外す**（採用 46% → **49%**。キャラの特徴語が拾える） | §0.8 |
| **G-5** | 括弧の語 | **(b) 残す。`\(` のエスケープだけ外す**（画面に `rem_(re:zero)` と出ることを了解） | §0.7, §5.1 |
| **G-6** | 複製の置き場（ComfyUI 経由） | **(a) `temp`**（再起動で消える。ジョブは再開できるので付け直せる。10 GB を残さない） | §0.5, §10 |
| **G-7** | 語釈の `sampling` | **(b) `off`**（2 回同じ出力。訳の揺れで人が直した語釈との差が分からなくなるのを避ける） | §0.9, §7 |
| **G-8** | 機械の語を人が消せるか | **(a) `manual` だけ消せる＋`hidden` の印**（行は消さない）。**ただし P4 では作らず、要望が出てから** | §1.3, §4.3 |
| **G-9** | SSE を作らない | **(a) ポーリング 2 秒**（内蔵 GPU なら 2 秒で 30 枚進むので粒度も足りる） | §0.3, §5.5 |

### 0.15 監査で確定したこと（P4-0 / P4-1。**推奨はすべて採用**）

`docs/p4-0-audit-report.md` と `docs/p4-1-audit-report.md` の指摘を反映した結果、設計に足した規則。
仕分けは [`p4-review-triage.md`](p4-review-triage.md) の末尾にある。

| # | 決めたこと | どこ |
| --- | --- | --- |
| **A-1** | **v5 は版を上げずに列を足した**（`tag.known` / `asset_tag.actor` / `job.note`）。先に v5 になった DB のために、**`migrate()` の早期 return 側でも列を見て補う**（`_top_up_v5`）。`job_item.state` の語彙は `tagged` / `skipped` / `failed` で `CHECK`。**閉じる側（`_finish`）は `note` 列が無くても死なない**（死ぬと `job` が `running` のまま残り、次の `POST` が永久に 409） | §2.1, §4.1 |
| **B-1** | **模型の待ちを取引の中に入れない**。順序は「読む（錠だけ）→ **模型（錠の外）** → 書く（短い 1 取引）」。取引の中で待つと、その間**全部の API が待たされる**（実測: 模型 1.0 秒で `locked()` の待ち 801〜901 ms、別接続の `INSERT` 2,718 ms） | §0.3, §3.2 |
| **B-2** | **`queued` も「忙しい」**（`BUSY_STATES = ("queued", "running")`）。**検査と `INSERT` を同じ取引**で行う（分けると、ワーカーが `running` に上げるまでの窓で 2 本目が通り、**`running` が 2 つ並ぶ**）。方式の検出（`tagger.detect`）は錠の外 | §0.3, §3.2 |
| **B-3** | 内蔵の前処理の縮小は **`int()` の切り捨て**（ノード `wd14tagger.py:63` と同じ）。`round()` だと寸法が 1 px 違い、**語が 1〜2 語変わることがある**（768×1360 の 4 枚中 2 枚） | §0.6 |
| **C-1** | `/history` の見張りは **0.05 秒**ごと（実測 0.72 → **0.51 秒/枚**） | §0.5 |
| **C-2** | 対象の既定は **`wd14` を軸**（AND にしない） | §3.2 |
| **C-3** | `,` で先に割った残りは**括弧の数で始末する**（数が合えば語の一部として残す＝`admiral_(kancolle)`。全体を囲む組は外す＝`(bar)` → `bar`。先頭の余分な `(` は外して釣り合えば通す＝`(masterpiece` → `masterpiece`。それ以外は落とす） | §0.7, §0.8 |
| **C-4** | **語彙（CSV）にある語なら、まだ `tag` 表に無くても人が付けられる**（行を作ってから付ける。`known` は導出値。語彙にも無い語は作らない） | §3.1 |
| **C-5** | 同じ語を 1 行にまとめても **`actor` を落とさない**（最初の非 NULL を残す）。**契約に欄を足すかは未決**（親の判断待ち。いまは API の `actor` に入る） | §3.4 |
| **C** | 投げた複製は**設定 `tagger.comfyui_temp` があれば自分で消す**（1 枚ごと＋ジョブの終わり） | §0.5 |

---

## 1. 何を作るか（範囲）と合格の線

### 1.1 作るもの

```
画像 ─┬─ タガー（内蔵 onnxruntime / ComfyUI の WD14Tagger・IllustTagger） ──▶ asset_tag(source='wd14')
      └─ PNG の final_prompt から語を切り出す（GPU 不要） ────────────────▶ asset_tag(source='png')
人 ── 拡大のタグ欄 ──▶ 語を足す / 外す ─────────────────────────────────▶ asset_tag(source='manual')
                    └─ 語釈が無い語に「訳す」──▶ TextGenerate ──▶ tag_gloss（人が直せる。edited=1）

未タグの画像 ── 背景ジョブ（進行・中断・再開・失敗の記録） ──▶ #/jobs で見る
語で絞る ── ライブラリの `?tag=` ──▶ その語を持つ画像
```

- タグは**出所を混ぜない**（`design.md` §8.1）。同じ語が PNG にもタガーにもあれば**2 行**を持つ。
- **タガーは下ごしらえ**。機械の印で**自動でキープにしない**（`design.md` §8.3）。限界（手の破绽を読めない等）を画面に書く。

### 1.2 合格の線（**実行して確かめられる形**）

| # | 線 | 確かめ方（そのまま打てる形） | 合否 |
| --- | --- | --- | --- |
| **1** | 未タグ画像に**タグが付く** | 合成 8 枚（Pillow で作る）を登録 → `POST /api/assets/tag {engine:'comfyui', limit:8}` → `GET /api/jobs/{id}` が `done` → 8 枚すべてで `GET /api/assets/{id}/tags` の `source='wd14'` が **1 語以上** | 8/8 に 1 語以上。0 語の画像があれば**落ち** |
| **2** | **出所が混ざらない** | 同じ 1 枚に `POST /api/assets/{id}/tags {tags:[{name:'long_hair'}]}`（手動）→ `GET .../tags?source=wd14` と `?source=png` と `?source=manual` を別々に取る | 3 つの出所が別々に取れる。同じ語が PNG と WD14 の両方にあれば**2 行** |
| **3** | **2 行（英語 / 日本語）で出る** | `#/asset/<id>` を Chrome で開き、タグ欄の各行が「英語の行」＋「語釈の行」の 2 行であること。**語釈の行に括弧書きを足していない**（`gui_layout.mjs --screen asset`。**語そのものの括弧は残る**: `rem_(re:zero)`。点検 A-1 / G-5） | 2 行 1 組。**語釈の行に `（…）` が 0 個** |
| **4** | 訳は**見えた語だけ**・押したときだけ | 語釈の無い語に「訳す」が出る。押すと `POST /api/tags/gloss` が **1 回**、`tag_gloss` が増える。**押さなければ 1 行も増えない**（`GET` を何回叩いても） | 増える語数 = 押した語数。`GET` では 0 |
| **5** | 訳を**人が直せる**・直した語を守る | `POST /api/tags/{id}/gloss {ja:'…'}` → `GET` がその値・`edited: true` → `POST /api/tags/gloss {tag_ids:[…]}` を流す → **上書きされない** | 直した値が残る。`edited` が `false` に戻らない |
| **6** | **番号の無い行・英語のままの行を入れない**（点検 A-3 / G-1） | `tools/probe_p4.py` に **番号の無い行**・**番号の重複**・**英語のままの行**・**空の応答**を注入 → `tag_gloss` に**その語の行が入らない**（取れた番号の語だけ入る）。**1 語ずつの再送**は「番号が取れて日本語が返った」ときだけ成功とする | 注入した行が 1 つも入らない。取れた番号だけ入る |
| **7** | 手動の付け外しが**冪等**・`human` だけ | 同じ語を 2 回 `POST` → `asset_tag` は **1 行**。`DELETE` を 2 回 → 2 回目は **404**。`agent` で `POST` / `DELETE` → **403** | 行が増えない。403 と 404 |
| **8** | **内蔵と ComfyUI が同じ語を返す** | 同じ 8 枚を両方式で付け、`source='wd14'` の**語の集合**を比べる。**比べるときは `\(` `\)` のエスケープを外す**（点検 A-1 / C-3）。**差がある語を記録** | 8/8 で集合が一致（内蔵側だけなら**実行で確認済み**。点検 C-2）。差が出たら**理由を書いてから**先へ進む（§10-1） |
| **9** | **GPU の実測時間を記録** | §7 の表を実測で埋める（**測り方は「別々の画像を N 枚」**。**同じ画像の再投入は `execution_cached` に当たるので使わない**。点検 A-4 / C-1）。**測っていない欄は「未計測」のまま残す** | 表に「未計測」が残っていない（P4-3 の終わりに） |

- **測れない条件は書かない。** 上の 9 つは数値と手順が決まっている。
- **（点検 C-1）CPU の値を「桁違い」と書かない。** 実測では **CPU 0.75 s/枚**で、**ComfyUI の `WD14Tagger`（2.8〜3.4 s/枚）
  より速い**。「**内蔵 GPU は CPU の 12 倍（0.063 対 0.75）。1 万枚で約 2.1 時間**」と書く。
  **時間は「この環境（GPU あり）」の値として記録**し、CPU の値は別の行に書く（混ぜない）。

### 1.3 この段で**作らない**もの

- タグの**統合・改名**（`design.md` §16.1。語彙を勝手に書き換えない）。
- タグからの**自動のキープ**（機械の印は下書き。§8.3）。
- タグの**一括削除**・**語彙の編集**（`tag` の行そのものを消す口は作らない。使われなくなった語は残す）。
- **本格的な検索**（`design.md` §10.3 のフィールド検索・スマートフォルダはカタログの段）。
  P4 は `?tag=` の 1 つだけ足す。
- **SSE**（`GET /api/events`）。進行はポーリング（§0.3）。
- **IllustTagger のスコアを画面に出す**こと（保存はする。表示は P4-3 では出さない。§10-5）。
- 語釈の**一括の訳し直し**（`POST /api/tags/gloss` は「見えている語」にだけ使う）。

---

## 2. データモデル

### 2.1 表（`design.md` §5.1・§5.5・§5.6 に対する差分）

`design.md` の DDL をそのまま作り、**次の 4 点だけ足す**。**v5** として `db.py` に足す
（`SCHEMA_VERSION = 4` → `5`。`migrate()` は前へだけ進み、何度呼んでも安全）。

```sql
-- design.md §5.1 の 2 表（そのまま）＋ 正規形の一意性 ＋ **`known`（利用者の回答 Q1）**
CREATE TABLE IF NOT EXISTS tag (
  id INTEGER PRIMARY KEY,
  name TEXT NOT NULL UNIQUE,      -- 正規形（小文字・語間は _）。★この一意性が「同じ語を 1 行に」を守る
  category INTEGER,               -- WD14 CSV の category（0=general, 4=character。v3 の CSV に 1/3 は無い）
  category_name TEXT,
  known INTEGER NOT NULL DEFAULT 0 CHECK (known IN (0, 1))
                                  -- ★追加（利用者の回答 Q1 / 点検 §I）: タグの語彙（CSV 10,861 語）にある語か。
                                  -- **PNG の語は語彙に無くても入れる**ので、これで見分ける
                                  -- **導出値**（「`name` が語彙にあるか」）。書き込みは
                                  -- `INSERT ... ON CONFLICT(name) DO UPDATE SET known = max(known, excluded.known)`
                                  -- （`INSERT OR IGNORE` だと、CSV が無い環境や PNG の語が先に入ったときに
                                  -- `known=0`・`category=NULL` のまま残る。点検が実行で再現）。
                                  -- **ジョブの開始時に 1 回** `UPDATE tag SET known = (name IN 語彙)` で引き直す
                                  -- （3,154 行で 1 ms）
);
CREATE TABLE IF NOT EXISTS asset_tag (
  asset_id TEXT NOT NULL REFERENCES asset(id) ON DELETE CASCADE,
  tag_id   INTEGER NOT NULL REFERENCES tag(id),
  score    REAL,                  -- 確からしさ。**IllustTagger 経由だけ入る**（4 桁）。
                                  -- **WD14Tagger 経由は返さないので NULL**、**内蔵はこの段では入れない**（P4 の決定。§4.3）
  source   TEXT NOT NULL CHECK (source IN ('png', 'wd14', 'manual')),   -- ★CHECK（点検の型: 語彙は DB でも守る）
  model    TEXT,                  -- 付けたタガーのモデル名（source='wd14' のとき）。★飛ばす判定に使う
  actor    TEXT,                  -- ★追加（点検 §I）: 手動で付けた人（'human' / 'agent'）。タガーの行は NULL。
                                  -- **いまは human だけ**だが、後でエージェントにも許すときに移行が要らないように
  tagged_at TEXT NOT NULL,
  PRIMARY KEY (asset_id, tag_id, source)
);
CREATE INDEX IF NOT EXISTS ix_asset_tag_tag ON asset_tag(tag_id, asset_id);

-- design.md §5.6（そのまま）＋ 訳し直しの判定に使う列は既にある
CREATE TABLE IF NOT EXISTS tag_gloss (
  tag_id     INTEGER PRIMARY KEY REFERENCES tag(id) ON DELETE CASCADE,
  ja         TEXT NOT NULL,
  source     TEXT NOT NULL CHECK (source IN ('textgenerate', 'manual')),  -- ★CHECK
  engine     TEXT,
  edited     INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);

-- design.md §5.5（そのまま。**この段で初めて作る**）
CREATE TABLE IF NOT EXISTS job (
  id TEXT PRIMARY KEY,
  kind TEXT NOT NULL,             -- 'scan' | 'thumbnail' | 'tag' | 'extract' | 'hash' | 'export'
  state TEXT NOT NULL CHECK (state IN ('queued','running','done','failed','cancelled')),
  params TEXT, progress_done INTEGER DEFAULT 0, progress_total INTEGER,
  message TEXT, error TEXT,
  created_at TEXT NOT NULL, started_at TEXT, finished_at TEXT
);
CREATE INDEX IF NOT EXISTS ix_job_state ON job(state, created_at DESC);
CREATE TABLE IF NOT EXISTS job_item (
  job_id TEXT NOT NULL REFERENCES job(id) ON DELETE CASCADE,
  ref TEXT NOT NULL,
  -- **語彙は P4-1 で確定**（P4-0 の監査の申し送り）: `tagged` = 語を付けた /
  -- `skipped` = 既に付いていたので飛ばした / `failed` = 失敗した（`error` に理由）
  state TEXT NOT NULL CHECK (state IN ('tagged', 'skipped', 'failed')),
  error TEXT,
  PRIMARY KEY (job_id, ref)
);
CREATE INDEX IF NOT EXISTS ix_job_item_state ON job_item(job_id, state);
```

- **同じ語の大文字小文字を混ぜない**: `tag.name` の一意性は**大文字小文字を区別する**（SQLite の既定）。
  正規化（§0.7 で小文字に落とす）を**サービス層で必ず通す**（表の `COLLATE NOCASE` は使わない。
  `COLLATE` を後から変えるには表の作り直しが要るため、規則は 1 か所＝サービス層に置く）。
- `job.kind` に `'tag'` を使う。将来の走査ジョブもこの表に載る（P4 では走査は同期のままにする）。
- `job.state` と `asset_tag.source` は **`CHECK` で縛る**（P6 の §0.10 と同じ方針。遷移の規則だけサービス層）。
- **（点検 C-5）ワーカーは 1 枚ごとに 1 トランザクションで書く。** ワーカーは**自分の接続**を持ち（`db.py:89` の
  `PRAGMA foreign_keys=ON` と WAL は接続ごと）、FastAPI の同期ハンドラと**同じ SQLite ファイルに別スレッドから**
  書く。**66 行 × 10,000 枚を 1 トランザクションにしない**（相手を待たせない）。`busy_timeout` に当たる前提で書く。

### 2.2 索引の意図

| 索引 | 何を速くするか |
| --- | --- |
| `tag.name` の一意索引 | 語の取得（完全一致）と、同じ語の作り直しの防止 |
| `ix_asset_tag_tag` | 「この語を持つ画像」（タグ検索）と、語ごとの件数 |
| `asset_tag` の主キー | 「この画像のタグ」（`asset_id` が前置。拡大の画面） |
| `ix_job_state` | `#/jobs` の一覧（実行中を先に出す） |
| `ix_job_item_state` | 失敗した項目の取り出し |

- **`tag.name` の前方一致**（`LIKE 'long%'`）は `ix_asset_tag_tag` では速くならない。**語の一覧は 10,861 行**
  （CSV の語数）なので、前方一致は `tag` の全走査で足りる（実測は §7）。**FTS5 は使わない**（`design.md` §10.3 の
  メモ検索の話で、語には要らない）。

### 2.3 語の持ち方（正規形と、CSV との対応）

- `tag.name` は**正規形**（§0.7）。**CSV の語と 1 対 1**（`replace_underscore=false` で取れば CSV の `name` と同じ）。
- **CSV を持っていれば** `category` / `category_name` を埋める。持っていなければ `null`（画面はカテゴリの見出しを出さない）。
- **`tag` の行は消さない**（語彙の統合・改名を作らない方針の帰結。使われなくなった語は 0 件として残る）。
- 語の**表記を直す口は作らない**（`PATCH /api/tags/{id}` は作らない）。誤った語は**画像から外して**、正しい語を足す。

### 2.4 PNG の語と WD14 の語を**同じ語の行に集める**

- 「`1girl` が PNG にも WD14 にもある」とき、`tag` は **1 行**、`asset_tag` は **2 行**（`source` が違う）。
  これは `design.md` §8.1 の「同じ `tag` 行を共有し、`asset_tag` で出所ごとに行を持つ」のとおり。
- 画面では 1 語として出し、**出所の印を 2 つ**付ける（`PNG` と `タガー`）。**スコアはタガーの行のもの**を出す。

---

## 3. API（`design.md` §6.1 の該当行を、ここで確定する）

**すべて既存の middleware の下に入る**（`app.py:94-109` の `local_only`）。つまり `GET`/`HEAD`/`OPTIONS` は
`Host` の許可リストだけ、`POST`/`PATCH`/`DELETE` は加えて `Origin` の同一性と `Content-Type: application/json` を要求する。

### 3.1 誰が呼ぶか・書くか

| 口 | 誰が呼ぶか | 書くか | 備考 |
| --- | --- | --- | --- |
| `GET /api/assets/{id}/tags` | 画面・エージェント | 書かない | **`design.md` §6.1 に無い口**（本文は `POST`/`DELETE` だけ）。§0 の差分として足す |
| `POST /api/assets/{id}/tags` | **人**（画面） | 書く（`source='manual'`） | **`human` 以外 403**。冪等 |
| `DELETE /api/assets/{id}/tags/{tag_id}` | **人**（画面） | 書く（`source='manual'` の行だけ消す） | **`human` 以外 403**。2 回目は **404** |
| `GET /api/tags` | 画面・エージェント | 書かない | `?q=&category=&source=&known=&limit=&cursor=`。**`known` の既定は `1`**（点検 §I: 実データでは件数順の上位 4 語が全部 `known=0` の品質語で、上位 50 のうち 25 語が `known=0`。既定で絞らないと語の一覧が品質語で埋まる）。`known=1\|0\|all` の 3 値 |
| `POST /api/assets/tag` | 画面・CLI | 書く（job を 1 つ作る） | 実行は**背景**。すぐ job の id を返す |
| `GET /api/jobs` / `GET /api/jobs/{id}` | 画面 | 書かない | 進行のポーリング（2 秒） |
| `POST /api/jobs/{id}/cancel` | 画面 | 書く（印を立てる） | 画像 1 枚ごとに見る |
| `GET /api/tags/{tag_id}/gloss` | 画面・エージェント | 書かない | 無ければ `ja: null`（**訳さない**） |
| `POST /api/tags/{tag_id}/gloss` | **人**（画面） | 書く（`source='manual'`・`edited=1`） | **`human` 以外 403**。**`edited=1` と `source='manual'` を同時に立てる**（見分けは `edited` の 1 つ。§4.2 / 点検 C-6） |
| `POST /api/tags/gloss` | 画面 | 書く（`TextGenerate` を回す） | `{tag_ids:[], force?:false}`。**既定は「語釈の無い語だけ」訳す**（既にある語は `skipped`。点検 B-3）。**見えている語だけ** |
| `GET /api/tags/gloss/pending` | 画面 | 書かない | **数えるだけ**（`?limit=`） |
| `GET /api/assets?tag=<name>` | 画面 | 書かない | 既存の一覧に**絞り込みを 1 つ足す**（§0.11・§3.6）。**`known` も受ける**（既定 `1`。`known=1\|0\|all`。`?tag=` と同じ規則＝点検 §I-2 の趣旨を一覧側にも広げた） |

- **`PUT` は使わない**（全部を置き換える操作が無い）。
- **`GET` は状態を変えない**（§0.10）。**訳すのは `POST /api/tags/gloss` だけ。**

### 3.2 `POST /api/assets/tag`（背景ジョブを始める）

```jsonc
{
  "asset_ids": ["01M4...", "01M4..."],   // 省略時は「未タグの全部」（§の下）
  "engine": "auto",          // auto | builtin | comfyui（既定 auto。§0.4 の順で選ぶ）
  "model": null,             // 省略時は設定のモデル（既定 wd-eva02-large-tagger-v3）
  "threshold": 0.35,         // 省略時は設定（既定 0.35）
  "character_threshold": 0.85,
  "sources": ["png", "wd14"],// 何を付けるか。既定は両方。png だけなら GPU を使わない
  "limit": 0,                // 0 = 全部
  "force": false             // true なら既に付いた語も付け直す（§0.11）
}
→ 202 {"job_id": "01M4...", "total": 263, "engine": "comfyui"}
```

| 条件 | 応答 |
| --- | --- |
| 実行できるタガーが 1 つも無い | **409** `code: "tagger_unavailable"` `details: {"builtin": "onnxruntime がありません", "comfyui": "127.0.0.1:8188 につながりません"}`。**job を作らない** |
| 既に `running` の `tag` job がある | **409** `code: "job_running"` `details: {"job_id": "..."}`（ワーカーは 1 本） |
| `engine` が語彙の外 | **422** `details: {"engine": "auto | builtin | comfyui"}` |
| `threshold` / `character_threshold` が 0〜1 の外 | **422** `details: {"fields": {...}}` |
| `sources` が空・未知の語 | **422** `details: {"sources": "png | wd14"}` |
| `asset_ids` に知らない id | **422** `details: {"unknown_asset_ids": [...]}` |
| 対象が 0 枚 | **200** で `total: 0`（job を作らない。「付けるものがありません」） |
| **CSV の `category` が連続していない**（点検 C-2） | **409** `code: "tagger_csv_unsupported"` `details: {"csv": "<path>", "note": "category が連続していません"}`。**job を作らない**（`general_index` / `character_index` の決め方が成り立たない。§0.6-6） |

- **対象の既定**: `asset_ids` も `limit` も無いときは「**`sources` のうち `wd14` があれば `wd14`、
  無ければ `png`** の行が 1 つも無い画像」を `first_seen_at` の古い順に全部。
  **出所を 2 つ指定しても AND にしない**（P4-1 の監査 C-2: AND にすると「png も wd14 も無い画像」だけになり、
  **png だけ先に付いた画像が既定の走行から外れる**）。`wd14` は「タガーがまだ見ていない」ことの印なので、
  これを軸にする。`sources=["png"]` のときだけ `png` の有無で決める。
- **投げてすぐ返る**（応答は job の id。判断を待たない。P6 の要求と同じ形）。

### 3.3 `GET /api/jobs/{id}`（進行）

```jsonc
{
  "id": "01M4...", "kind": "tag", "state": "running",
  "params": {"engine": "comfyui", "model": "wd-eva02-large-tagger-v3", "threshold": 0.35,
             "character_threshold": 0.85, "sources": ["png", "wd14"]},
  "progress": {"done": 42, "total": 263},
  "message": "42 / 263（1 枚 0.41 秒。残り 1 分 31 秒）",
  "counts": {"tagged": 41, "skipped": 1, "failed": 0},
  "started_at": "2026-10-16T06:20:00Z", "finished_at": null,
  "items_failed": [{"ref": "01M4...", "error": "実体が見つかりません"}]
}
```

- `items_failed` は**先頭 20 件**だけ返す（全部は `GET /api/jobs/{id}/items?state=failed`）。
  **一覧（`GET /api/jobs`）も同じ 20 件を返す**（P4-3 の監査 A-1。画面は一覧だけを読むので、
  以前は**失敗の理由も「もう一度」の押し場も出せなかった**）。
- **`counts.skipped`** は「既に付いていて飛ばした枚数」（§0.11）。
- 残り時間は**実測の平均**から出す（測っていない方式では出さない。`null`）。

### 3.4 `GET /api/assets/{id}/tags`

```jsonc
{
  "asset_id": "01M4...",
  "items": [
    {"name": "long_hair", "tag_id": 12, "category": 0, "category_name": "general", "score": null, "known": true,
     "source": "png", "sources": ["png"], "model": null, "tagged_at": "..."},
    {"name": "1girl", "tag_id": 7, "category": 0, "category_name": "general", "score": 0.9931, "known": true,
     "source": "wd14", "sources": ["wd14"], "model": "wd-eva02-large-tagger-v3", "tagged_at": "..."},
    {"name": "looking_at_phone", "tag_id": 40, "category": 0, "category_name": "general", "score": null, "known": true,
     "source": "png", "sources": ["png"], "model": null, "tagged_at": "..."},   // ★正規形（_ 区切り）。語彙にある
    {"name": "first_girl:_black_hair", "tag_id": 41, "category": null, "category_name": null, "score": null, "known": false,
     "source": "png", "sources": ["png"], "model": null, "tagged_at": "..."},  // ★語彙外（点検 §I。自然文の断片）
    {"name": "1girl", "category": 0, "category_name": "general", "score": null, "known": true,
     "source": "manual", "sources": ["manual"], "model": null, "tagged_at": "..."}
  ],
  "glosses": {"1girl": {"ja": "女の子1人", "source": "textgenerate", "engine": "qwen3vl_8b_int8_convrot.safetensors", "edited": false}},
  "pending_gloss": ["long_hair"],
  "counts": {"png": 42, "wd14": 74, "manual": 1}
}
```

- **同じ語が複数行で返る**（出所ごと）。画面は 1 語にまとめる（§2.4）。`sources` は同じ語の出所をまとめた配列。
- **`tag_id` を返す**（P4-3 の監査 A-2）: 画面が語を選んで「訳す」を押すときに使う。以前は名前から
  `Number()` していたので **`NaN` → `tag_ids: []` → 必ず 422** になっていた。
  **契約（`review.json` の `Tag`）には足さない**（API の応答だけ。画面の都合で契約を太らせない）。
- `glosses` は**引くだけ**（無ければ `pending_gloss` に入る）。**訳さない**（§0.10）。
- **（P4-2 で実装）** `glosses` / `pending_gloss` / `counts` はこの形で入れた（P4-1 の監査 C-6 の宿題。
  `counts` は**出所ごとの数**＝`items[]` の `sources` を数える。`pending_gloss` は**語の名前の配列**）。
  語釈の有無の数が要るときは `len(pending_gloss)` を使う（別の欄は足していない）。
- 並びは §0.10 の規則（カテゴリ → スコアの降順 → 名前の昇順）。**同じ入力なら同じ並び**。

### 3.5 `POST /api/tags/gloss`（訳す）

```jsonc
{"tag_ids": [12, 40], "limit": 20, "force": false}
→ 200 {"translated": [{"tag_id": 12, "name": "long_hair", "ja": "長髪", "engine": "..."}],
       "skipped": [{"tag_id": 7, "name": "1girl", "reason": "既に語釈があります"}],
       "untranslated": [{"tag_id": 40, "name": "three quarter view", "reason": "番号が取れず、1 語ずつでも訳せませんでした"}],
       "calls": 21, "elapsed_ms": 3120}
```

| 条件 | 応答 |
| --- | --- |
| `tag_ids` が空 | **422** `details: {"tag_ids": "1 つ以上"}` |
| 語数が `limit` を超える | **422** `details: {"tag_ids": "20 語まで", "count": 42}`（**画面は 20 語ずつに割る**） |
| **既に語釈がある語が混ざっている（`force=false`。既定）** | **200**。その語は **`skipped`** に入れ、**模型を回さない**（点検 B-3。2 回押しても 2 回目は呼び出し 0 回） |
| `edited=1` の語が混ざっている（`force=true`） | **200**。その語は `skipped` に入れて**上書きしない**（人が直した語は守る。§0.9） |
| ComfyUI につながらない | **409** `code: "gloss_engine_unavailable"` `details: {"url": "http://127.0.0.1:8188"}` |
| **模型が番号の無い行・英語のままの行を返した** | **200**。**その語は保存しない**（`untranslated` に入れる。§0.9 の 2〜3。点検 A-3） |
| 1 語ずつでも訳せない（番号が取れない／日本語が返らない） | **200**。`untranslated` に入れる（**保存しない**） |
| **ComfyUI に繋がらない・投げられない**（P4-2 の監査 B-1 / E-3） | **502** `details: {"url": ..., "error": ...}` |
| **模型の読み込み中などで `/history` の通信が落ちる**（同 B-1） | **待ち直し**、`gloss.timeout` を越えたら **504**。**500 は返さない**（実測: 冷えた模型の初回に 4 回中 1 回 `WinError 10060`） |

- **「日本語が返った」の条件は「かな・漢字を 1 文字以上含む」**（P4-2 の監査 C-2 / G-3）。記号だけ（`……`）と
  絵文字＋英語（`👁️ girl`）は**保存しない**（模型が `👁️ = 視聴者を見つめる` を返した実例があるため）。
- **`gloss.*` の設定は訳すたびに読み直す**（同 C-1 / G-2。以前は再起動まで効かなかった）。
- **この口はエージェントも押せる**（同 C-3 / G-4。要求の流れで語釈を先に揃えたい場面があるため。
  **GPU を使う**ので、必要になったら `require_human` を 1 行で足せる形にしてある）。

- **`POST /api/tags/{tag_id}/gloss {ja}`** は人が直す口（`source='manual'`・`edited=1`・`engine` は触らない）。
- **`GET /api/tags/gloss/pending`** は「語釈の無い語」を**数えて**返す（`{"count": 128, "sample": [...]}`）。

**（P4-2 で実装したときの決定。設計が黙っていた所）**

| 論点 | 決め | 理由 |
| --- | --- | --- |
| 知らない `tag_id` | **404** `details: {"tag_id": …}` | 設計は黙っている。他の口（`DELETE /api/assets/{id}/tags/{tag_id}`）に揃えた |
| `tag_ids` の重複 | **黙って 1 つに畳む**（エラーにしない） | 冪等（同じ語を 2 度訳しても行は 1 つ） |
| `limit` | 既定 20・**上限 20**（`MAX_BATCH`）。`limit` で小さくできる | §0.9 の「まとめて訳す単位は最大 20 語」 |
| `tag_gloss.engine` に入れる値 | **使った模型の名前**（例 `qwen3vl_8b_int8_convrot.safetensors`） | §3.4 の例の形 |
| 人が既存の語釈を直したとき | **`edited=1` を立て、`source` は由来を保つ**（自動の訳を直したら `textgenerate` のまま）。**`engine` は触らない** | §4.2 の括弧書き（「『直したかどうか』の判定には `edited` だけを使う」）。画面の出し分けは `edited` だけを見るので食い違わない |
| 模型のエラー（502 / 504） | **そのまま返す**（部分保存はしない＝書くのは全部訳し終えてから 1 取引） | 書き込みを短い 1 取引にまとめる規律（P4-1 の監査 B-1） |
| `system_prompt` の初期値 | `src/image_reviewer/gloss.py` の `DEFAULT_SYSTEM_PROMPT`。**設定 `gloss.system_prompt` で差し替えられる** | §0.9 の表（文面は設定に置く） |

### 3.6 `GET /api/assets?tag=<name>`（絞り込み）

- **既存の一覧 API（`app.py:174-206`）に 1 つ足す**。現物は**メモリ上の一覧を Python で絞る**形
  （`limit` / `cursor` は**オフセット**、`sort` は `path` / `model`）。P4 ではこの形のまま:
  1. `tag` があるとき、**SQL で `asset_id` の集合**を引く（`asset_tag` → `tag.name` の完全一致）。
  2. その集合で一覧を絞る。
- **`design.md` §10.3 の本格的な検索（前方一致・フィールド検索・キーセット）はこの段では作らない**
  （一覧 API の作り直しはカタログの段。§1.3 に書いた）。
- **語の前方一致**が要るのは `#/tags` の検索だけなので、`GET /api/tags?q=` 側で `LIKE 'q%'` を使う。

---

## 4. 状態と遷移

### 4.1 `job.state`

```
queued ──▶ running ──▶ done
                 ├──▶ failed（開始できなかった / 全滅した）
                 └──▶ cancelled（印を見て止まった）
```

- **`queued` から `running` への移行はワーカーが取ったとき**（1 本しかないので競合しない）。
- **（点検 C-4）`queued` は「ワーカーが動けないとき」にだけ残る。** ワーカーが 1 本で「取ったら `running`」、
  2 つ目の `POST` は 409 `job_running`（§3.2）なので、**正常時は `queued` の行は一瞬しか存在しない**。
  したがって: **2 つ目の `POST` を 409 で断るのは `running` のときだけ**にし、**`queued` が残っている間は
  「順番待ち」として受け付けない**（1 本しかワーカーが無いので、`queued` のまま残るのは
  **タガーが使えない等でワーカーが起動していないとき**。そのときは `job` を作らずに 409 を返す。
  §3.2 の `tagger_unavailable` と同じ扱い）。**画面と `#/jobs` は `queued` を「待っています」と出す**
  （一瞬で消えるが、出たときに意味が通る語にする）。
- **`failed` は「1 枚も処理できなかった」ときだけ**（1 枚の失敗は `job_item` に残して続ける）。
- **`cancelled` でも、既に書いた行は消さない**（付いた語は正しい。もう一度流せば続きから）。
- **終わった job は消さない**（`#/jobs` の履歴）。

### 4.2 `tag_gloss` の状態

| 状態 | 見分け方 | 画面 |
| --- | --- | --- |
| 語釈が無い | `tag_gloss` に行が無い | 「日本語の語釈はまだありません。」＋「訳す」 |
| 自動の語釈 | `source='textgenerate'` | 「訳は自動です」の 1 行＋「直す」 |
| 人が直した語釈 | **`edited=1`**（`source` は見ない） | 「直した語釈です」＋「直す」。**訳し直しで上書きしない** |

- **（点検 C-6 / P4-2 の監査 E-1・G-1）「人が直した」の印は `edited=1` の 1 つにする。**
  `source` は「**その語釈がどこから来たか**」を表す**由来の欄**で、**「直したかどうか」の判定には使わない**。
  人が直す口（`POST /api/tags/{tag_id}/gloss`）の決まり:
  - 行が無ければ **`source='manual'`・`edited=1`・`engine=null`** で作る（人がゼロから書いた）。
  - 行があれば **`edited=1` だけを立て、`source` と `engine` はそのまま**（自動の訳を人が直したなら
    `textgenerate` のまま＝**その語釈がどこから来たか**が残る）。
  - **画面は `edited` だけを見る**（§3.4 の `gloss_edited`）。
  - 前の版は「`edited=1` と `source='manual'` を同時に立てる」とも書いていて**矛盾していた**ので、
    この 3 行に揃えた（点検の指摘。**実装はこの形になっている**）。

### 4.3 出所（`asset_tag.source`）

| 出所 | 入る道 | 消せるか |
| --- | --- | --- |
| `png` | タグ付けジョブ（`final_prompt` の切り出し） | 消せない（`DELETE` は `manual` だけを消す）。`force` で作り直す |
| `wd14` | タグ付けジョブ（タガー） | 同上 |
| `manual` | 画面（人が付ける / 外す） | **`DELETE` で消せる** |

- **`DELETE` は `manual` の行だけを消す**（機械の語を人が消したいときは…§10-6 に論点として残す。
  いまは「消せない」とし、画面には**外すボタンを出さない**）。
- **（点検 B-1）`score` が入るかは方式で違う**（`§0.10` の数値の丸めも参照）:

  | 方式 | `score` | 理由 |
  | --- | --- | --- |
  | **ComfyUI `IllustTagger`**（既定） | **入る**（`round(p, 4)` の 4 桁） | ノードが `scores` を JSON で返す |
  | ComfyUI `WD14Tagger\|pysssss` | **NULL** | `tags` の文字列しか返さない（点検 B-1） |
  | 内蔵（`builtin`） | **NULL**（この段の決定） | 生の float32 は持っているが、**表示と並びには名前で足りる**ので保存しない（入れたくなったら列は既にある） |
  | `png` / `manual` | NULL | スコアの概念が無い |

  - したがって**並びの規則（§0.10）は「`score` が NULL の語は名前の昇順で後ろ」**を含む形にする
    （既定の `IllustTagger` 以外では全語が NULL になるため。点検 F の 8.1-12 / 19）。

---

## 5. 画面（詳細は [`frontend-design.md`](frontend-design.md)。ここは挙動だけ）

### 5.1 拡大（`#/asset/<id>`）のタグ欄

- **2 行 1 組**（1 行目 英語 / 2 行目 日本語の語釈）。**語釈の行に括弧書きを足さない**（`design.md` §16.1 の
  「括弧書きは使わない」は**この意味**。**語そのものの括弧は消さない**: `rem_(re:zero)` はそのまま出る。
  点検 A-1 / G-5）。
- 並びは §0.10。**カテゴリの見出し**（キャラ → 一般。無いカテゴリは出さない）。
- 出所の印（`PNG` / `タガー` / `手`）を語の右に小さく。**スコアはタガーの行だけ**（小数 3 桁）。
- 語釈が無い語に「訳す」（12px）。**まとめて訳す**ボタン（見えている語のうち語釈が無いものを 20 語まで）。
- 「語を足す」: 1 行の入力。**候補を出す**（`GET /api/tags?q=` の前方一致。`tag` の全走査で足りる）。
- 「外す」は `manual` の行だけに出す（§4.3）。
- **タガーの限界の 1 行**を欄の下に出す（「タガーは下ごしらえです。手の破绽などは読めません。」）。

### 5.2 `#/tags`（8 番。**P4-3 で作る**）

- 語の一覧（名前・件数・語釈の有無・カテゴリ）。`?q=` の 1 行検索。**新しい順ではなく件数の多い順**。
- 語を選ぶと、その語の**語釈の確認と修正**（`POST /api/tags/{id}/gloss`）。
- 「訳す（20 語まで）」で**語釈の無い語**をまとめて訳す。
- **「一括タグ付け」の入口**（`#/jobs` に投げる。条件は `POST /api/assets/tag` の本文）。

### 5.3 `#/jobs`（9 番。**P4-3 で作る**）

- 走査・タグ付けの**進行**（`done / total`、1 枚あたりの実測、残り時間）。
- **中断**（`POST /api/jobs/{id}/cancel`）と、**失敗した項目の一覧**（先頭 20 件）＋「もう一度」。
- **2 秒ごとにポーリング**（画面を開いている間だけ）。終わった job は履歴として残す。

### 5.4 `frontend-design.md` に足すもの（**実装の前に足す**）

| 足す所 | 内容 |
| --- | --- |
| §3 画面の一覧 | 8 番（`#/tags`）と 9 番（`#/jobs`）に「**P4-3 で作る**」と書く（行は既にある。点検 D-10） |
| **§4.5 タグ（新設）** | 部品の形（2 行 1 組の組）、出所の印、スコアの桁、見出しの規則、「訳す」の見た目、「訳は自動」の 1 行、空の文（**`frontend-design.md` §4 にタグの節は無い**。点検 D-10） |
| §6 文言 | 「日本語の語釈はまだありません。」「訳は自動です。直せます。」「タガーは下ごしらえです。…」「タグ付け 42 / 263 枚」 |
| §11 細部 | 語の並び（カテゴリ → スコア → 名前）、`manual` の行だけ「外す」、候補の出し方、ジョブのポーリング間隔 |
| §2.3 書体 | 語釈の行は **BIZ UDPMincho**（点検 D-10 で既にあることを確認済み） |

### 5.5 知らせ方

- タグ付けが終わったら、**上部バーに 1 行**（「タグ付けが終わりました（263 枚）」）。音は使わない（`design.md` §16.1）。
- 進行中は `#/jobs` に行が 1 つあることをバーに出す（`#/jobs` に入らなくても気づける）。

### 5.6 P4-3 の実装で決めたこと（2026-10-16。**記録は [`p4-3-implementation.md`](p4-3-implementation.md)**）

- **`frontend-design.md` の節番号は §4.13**（§5.4 は「§4.5 タグ（新設）」と書いていたが、§4.5 は既に「件数と通知」。
  §4 の最後に足した）。
- **`GET /api/assets/{id}/tags` の `items` に `tag_id` が無い。** 訳す口と外す口は `tag_id` を要るので、画面は
  `GET /api/tags?known=all&limit=1000` を **1 回**引いて「名前 → id」の地図を作る。
  **申し送り**: `tag_docs` の辞書に `tag_id` を 1 行足す（契約の `Tag` ではなく **API の応答だけ**）か、
  `POST /api/tags/gloss` が名前も受けるようにする。
- **「もう一度」は新しいジョブ**（失敗した項目の `ref` ＝ `asset_id` を集めて `POST /api/assets/tag`）。
  同じジョブを再開する口は API に無い。
- **完了の知らせは 60 秒で消す**（設計は「1 行出す」だけ。消える時間は実装で決めた）。
- **カテゴリの呼び名は 1 か所**（`apps/gui/tags.js` の `CATEGORY_LABEL`）を、1 枚の欄と `#/tags` の両方で使う。
- **実物で確かめていないこと**: 「語を足す」の入力・**実物で**「訳す」を押した模型の往復・`#/jobs` の実行中／中断／失敗・
  200 語の画像（実データの最大は 47 語）。**エスケープは実物で確認済み**（語釈に `<script>` を入れて `script=0`）。

---

## 6. 契約

### 6.1 `review.json` に足すもの

- `assets[].tags[]` は**既にある**（`schemas/review-export.schema.json:243`）。`include_tags=true` のときだけ出す。
  **P4 で実際に埋める**（いまは `export.py:481-483` の `doc["tags"] = []` の仮置き）。
- `Tag` に **`gloss`（`ja`）と `gloss_edited`** を足す（任意。§0.12）。**足した欄は必ず出す**
- あわせて **`known`（真偽）** を足す（利用者の回答 Q1。**タグの語彙にある語か**）。
  `known=false` は PNG の自然文から来た語などで、**画面では印を付けて出す**・**検索の既定では当てない**
  （P6-0 の監査 B1 の再発防止。**テストで「出したときは値が入っている」を見る**）。
- 並びは §0.10 の規則に固定（**2 回出して `generated_at` を除いて一致**）。
- `include_tags` の既定は `false` のまま（`design.md` §9.4。全件が 100 MB 規模になるため）。

### 6.2 `abi` は上げない

- 足すのは `tags[]` の中の**任意の欄**（`gloss` / `gloss_edited`）と、**実際に埋まること**だけ。
  既存の必須も型も変えない。読む側は `tags` を知らなくても今までどおり読める。

---

## 7. 性能と規模（この段で守る数値）

**この環境（Windows / RTX 級 GPU / ComfyUI 0.39.2 が 127.0.0.1:8188 で稼働）で実測した。**
測り方: `POST /prompt` を投げて `/history/{id}` が返るまでの壁時計（`tools/probe_p4.py` に残す）。

| 何 | 実測 | 備考 |
| --- | --- | --- |
| ComfyUI 経由 `WD14Tagger\|pysssss`（**別々の画像**。1 枚目 = モデルの読み込み込み） | **3.37〜3.55 s** | 1202 MB の ONNX を読む |
| 同（**別々の画像の定常**） | **2.8〜3.1 s/枚**（実測 6 枚: 3.37 / 2.88 / 2.80 / 2.79 / 3.09 / 2.86） | **呼ばれるたびに `InferenceSession` を作り直す**（`wd14tagger.py:58`。session 作成 2.0〜2.3 s ＋ 推論 0.44 s）。**`design.md` §8.2 の 0.5 s/枚を満たさない** |
| 同（**同じ画像の再投入**） | **0.22 s** | **`execution_cached`**（実行していない。`/history` の `status.messages` に出る）。**前の版の「定常 0.40 s/枚」はこれ**（点検 A-4） |
| ComfyUI 経由 **`IllustTagger`**（別々の画像） | **0.26〜0.31 s/枚**（1 枚 0.55 s の揺れ） | スコア付き。**既定はこれ**（G-2） |
| **内蔵**（ComfyUI 同梱の `python_embeded`、`onnxruntime-gpu 1.30`、RTX 3090）: session 作成 / 1 枚目 / 定常 | 2.07 s / 0.44 s / **0.063 s/枚** | **`CUDAExecutionProvider` が使えた場合**（点検 B-2） |
| 内蔵 **CPU**（CUDA の DLL が読めず黙って落ちた回）: session 作成 / 定常 | 2.0〜2.3 s / **0.75 s/枚** | **`WD14Tagger`（2.8〜3.4 s/枚）より速い**（点検 C-1） |
| 語釈 `TextGenerate`（**3 語**を 1 回・モデルの読み込み込み） | **6.7〜9.0 s** | 8.7 GB の int8 を読む |
| 語釈 `TextGenerate`（**20 語**・**番号付き**・`sampling off`） | **4.6〜4.8 s**（初回 10.1 s） | **2 回同じ出力**（G-7）。**20/20 が返る** |
| 同（**40 語**・番号付き。重複なし） | **4.3 s**（38/40 行） | 上限の見直しは §10-4 |
| 語釈の 1 語あたり（1 語ずつの経路） | **0.30 s/語**（`long_hair` は成功、`1girl` は英語のまま、`looking_at_viewer` は空） | **番号が取れなかった語だけ**通る経路（§0.9） |
| `POST /upload/image`（907 KB） | **6〜27 ms** | 複製の作成（点検 A-2） |
| **内蔵（`onnxruntime`）を `uv` 側に入れた場合** | **未計測** | いまは `uv` の環境に `onnxruntime` が無い。**P4-1 で入れてから測る**（上の値は ComfyUI 同梱の Python で測ったもの） |

- **測り方**（点検 A-4 / C-1。**この節の数値はすべて「別々の画像を順に投げた」値**）:
  - **同じ画像を続けて投げない**（`execution_cached` に当たって 0.22 s になる）。
  - ComfyUI 経由は `POST /prompt` → `GET /history/{id}` を 0.5 秒ごと。**待ち行列が空のとき**に測る。
  - 内蔵は `python_embeded\python.exe` で session を作り、**別々の画像**を推論。
  - 語釈は同じ 20 語を 2 回投げて**同じ出力**を確かめる（`sampling off`）。
- **見積り**（実測から計算。**測っていない値は書かない**。画像の読み込みは除く）:
  - **10,000 枚**: 内蔵 GPU **約 11 分**（0.063 s/枚）／内蔵 CPU **約 2.1 時間**（0.75 s/枚）／
    **`IllustTagger` 約 45 分**（0.27 s/枚）／**`WD14Tagger` 約 8 時間**（2.9 s/枚）。
  - **`design.md` §8.2 の「0.5 秒/枚・1 万枚で 1.5 時間」を満たすのは内蔵（GPU）と `IllustTagger` だけ**
    （`WD14Tagger` は満たさない。§0.5 の既定を変えた理由）。
  - 語釈を **1 語も訳さない**状態から 1,000 語訳すと、20 語ずつで **50 回 × 約 4.7 秒 = 約 4 分**（初回の読み込み 10 秒を足す）。
- **行数の見積り**: 1 枚あたり `general 0.35` / `character 0.85` で **66 語**（実測: 1 枚の応答が **748 文字**の
  カンマ区切りで、`,` で割ると **66 語**。うちキャラ語が先に来る）。
  10,000 枚で `asset_tag` は**約 66 万行**。SQLite で扱える量（`ix_asset_tag_tag` は `(tag_id, asset_id)`）。
  `tag` の行は **CSV の語数（10,861）が上限**。

---

## 8. テスト方針（**何を壊すと落ちるか**）

P5・P6 の監査で「**何も守っていないテスト**」と「**契約に足したのに出していない**」が見つかった。
**この段では、テストを書いた時点で「何を壊すと落ちるか」を言える形にする。**

### 8.1 pytest（`tests/test_tags.py` / `tests/test_jobs.py` / `tests/test_gloss.py` / `tests/test_db.py` に足す）

| # | 壊すと落ちるもの | 何を確かめるか | なぜ要るか |
| --- | --- | --- | --- |
| 1 | `tag.name` の正規化を外す | `Long Hair` / `long  hair` / `long_hair` が**同じ 1 行**になる | §0.7 |
| 2 | `asset_tag` の主キーを外す | 同じ語を 2 回足しても**行は 1 つ**（`png` と `wd14` は別の行） | §0.10（冪等） |
| 3 | `source` の `CHECK` を外す | `source='x'` が **IntegrityError** | 語彙は DB でも守る |
| 4 | 飛ばす判定（`model` を見る）を外す | 同じモデルで 2 回流しても**行が増えない**。`force=true` で**付け直す**（古い行を消してから） | §0.11 |
| 5 | `human` の検査を外す | `POST` / `DELETE /api/assets/{id}/tags` が `agent` で **403**、`human` で 201 / 200 | §0.10 |
| 6 | `DELETE` の 2 回目を 200 に変える | 2 回目が **404** | P6 の点検 D5 と同じ型 |
| 7 | PNG の語で**語彙の判定（`known`）を外す** | `final_prompt` の断片が**全部タグに入る**（`known` が付く）。語彙にある語（`looking_at_phone`）は `known=true`、無い語（`First girl: black hair` の断片や**語彙に無い `three_quarter_view`**）は `known=false`。採用した数と語彙外の数が結果に出る。**検索の既定（`?tag=`）は `known=true` だけに当たる**（利用者の回答 Q1。**点検 B-4**: `three quarter view` は**語彙に無い**ので「出る語」の例に使わない） | §0.8 |
| 8 | **正規化で括弧を落とすように変える**（点検 A-1） | **`star_(symbol)` と `admiral_(kancolle)` と `:d` が壊れない**（括弧とコロンが残る）。`\(` `\)` のエスケープは外れる。**外側の重み `(three quarter view:1.5)` からは `three_quarter_view` が出る**（`:` と数字は残らない） | §0.7（前の版は**壊す方向に固定していた**） |
| 9 | 語釈の**番号での対応**を外す（位置で対応にする） | 模型の応答に**番号の無い行**・**番号の重複**・**英語のままの行**・**空の応答**を注入 → **それらの語は `tag_gloss` に入らない**（取れた番号の語だけ入る）。**部分的に当てはまってよい**（番号で対応するため。§0.9） | §0.9（実測で位置対応は崩れた。点検 A-3 / F） |
| 10 | `edited=1` の保護を外す | 人が直した語釈が `POST /api/tags/gloss` で**上書きされない** | `design.md` §15 のリスク 15 |
| 11 | `GET` が訳すように変える | `GET /api/assets/{id}/tags`・**`GET /api/tags/{tag_id}/gloss`**・`GET /api/tags/gloss/pending` の前後で **`tag_gloss` の行数が変わらない**（点検 F: `gloss` の口も対象に入れる） | §0.10（`GET` は書かない） |
| 12 | 並びの規則を外す | `GET /api/assets/{id}/tags` が 2 回とも**同じ並び**（カテゴリ → **`score` の降順（`NULL` は最後）** → 名前）。**`score` が全部 NULL の方式（`WD14Tagger`・内蔵）でも決まる**（点検 B-1 / F） | §0.10（決定性） |
| 13 | job の状態遷移を壊す | `queued → running → done`。中断で `cancelled`、既に書いた行は残る | §4.1 |
| 14 | 失敗を `job_item` に残す処理を外す | 実体の無い画像 1 枚を混ぜると、**その 1 件だけ** `failed` になり job は `done` | §0.3 |
| 15 | ワーカーを 2 本にする | 2 つ目の `POST /api/assets/tag` が **409 `job_running`** | §0.3（GPU は 1 本） |
| 16 | 実行できないときの 409 を外す | `onnxruntime` 無し・ComfyUI 停止で **409 `tagger_unavailable`**（job を作らない）。**ComfyUI を止めずに試すには設定の `url` を `127.0.0.1:1` にする**（点検 F） | §0.4（fail-soft） |
| 17 | 移行の手当てを壊す | **v1 の DDL から 1 回で v5** に上がる。**v4 の DB からも v5**。**さらに `.data` の写し（いま `user_version=3`）からも 1 回で v5**（`user_version` が 5、列と表が揃う）。**3 回呼んでも同じ**（点検 F） | P6-0 の監査と同じ観点 |
| 18 | 契約の `gloss` を出さない | **語釈を 1 語付けてから** `include_tags=true` の `scope=all` を出し、**その語の `gloss` が値を持つ**（語釈 0 件では `null` で通ってしまう。点検 B-5）。本物の `jsonschema` でも検証 | P6-0 の監査 B1 |
| 19 | `tags` の並びを不定にする | `scope=all` を 2 回出して `generated_at` を除いて**完全一致**（語を 20 個付けた状態。**`score` が NULL の語を含む**。点検 F） | `design.md` §3.4 |
| 20 | 絞り込みを外す | `GET /api/assets?tag=1girl` が**その語を持つ画像だけ**を返す（`source` を問わない） | §3.6 |
| 21 | 語数の上限を外す | 21 語を `POST /api/tags/gloss` に投げると **422**（20 語まで） | §0.9 |
| 22 | 索引を外す | `EXPLAIN QUERY PLAN` に `ix_asset_tag_tag` が出る | P5-3 の D1 の教訓 |
| 23 | **既に語釈がある語を訳し直すように変える**（点検 B-3） | `POST /api/tags/gloss` を 2 回叩くと、**2 回目は模型を回さない**（`skipped` に入り、`calls` が 0）。`force=true` なら回す（`edited=1` は上書きしない） | §0.10（語釈の口の冪等性） |
| 24 | **CSV の `category` の連続性の検査を外す**（点検 C-2） | `category` が連続していない CSV を渡すと **409 `tagger_csv_unsupported`**（job を作らない） | §0.6-6 / §3.2 |
| 25 | **`IllustTagger` のスコアを落とす**（点検 B-1） | `IllustTagger` 経由で付けると **`score` が入る**（4 桁）。**`WD14Tagger` 経由では `NULL`**（どちらも実行で確かめる。`WD14Tagger` は注入した応答でよい） | §4.3 |
| 26 | **手動の付け外しで `manual` 以外を消す** | `DELETE /api/assets/{id}/tags/{tag_id}` が **`source='manual'` の行だけ**を消す（`png` / `wd14` の行は残る） | §4.3 |

- **実データに依存するテストを書かない。** 合成画像（Pillow の PNG ＋ `prompt` チャンク）で試し、名前も作り物に合わせる。
- **模型を呼ぶテストは既定で走らせない**（ComfyUI が無い環境で赤くしない）。`@pytest.mark.comfyui` を付け、
  `-m "not comfyui"` で外せるようにする。**実機の確認は `tools/probe_p4.py` が担う**。

### 8.2 `tools/gui_smoke.mjs`（軽い DOM。CSS を持たない）

| # | 壊すと落ちるもの | 何を確かめるか |
| --- | --- | --- |
| 1 | タグの 2 行の組み立て | 1 語が「英語の行」＋「語釈の行」の 2 行で出る。**括弧が本文に無い** |
| 2 | 語釈が無いときの文と「訳す」 | 「日本語の語釈はまだありません。」＋「訳す」が出る／語釈があれば出ない |
| 3 | 出所の印 | `png` / `wd14` / `manual` の 3 種が別の印で出る（同じ語の 2 出所は印 2 つ） |
| 4 | 「訳す」の呼び出し | 押すと `POST /api/tags/gloss` が **1 回**（`tag_ids` が押した語だけ）。押さなければ 0 回 |
| 5 | 語を足す | 空のまま押しても送らない。語を入れると `POST /api/assets/{id}/tags` が 1 回 |
| 6 | 「外す」の出し分け | `manual` の行にだけ出る（`png` / `wd14` の行には出ない） |
| 7 | エスケープ | 語釈に `<script>` を入れても**生のまま出ない**（`esc()`） |
| 8 | ジョブの進行 | `#/jobs` が `done / total` と残り時間を出す。`state='cancelled'` の印が出る |

### 8.3 `tools/gui_layout.mjs`（本物の Chrome。`--screen asset` を拡張）

| # | 壊すと落ちるもの | 何を確かめるか |
| --- | --- | --- |
| 1 | タグ欄の横幅 | 3 窓（1400×900 / 1200×800 / 1920×1080）で**タグ欄が右の列から溢れない**（`listOverflow=0`） |
| 2 | 語数の多い画像 | 200 語のときも**縦に伸びるだけで横に溢れない**（折り返す。仮想化はしない） |
| 3 | 2 行 1 組の高さ | 100 語で**行の高さが揃っている**（1 行目と 2 行目の対応が目で追える。`rowGap` が一定） |
| 4 | `#/tags` / `#/jobs` | 3 窓で `overflow=0`。`#/jobs` の進行の行が**折り返して 2 行になっても崩れない** |

### 8.4 `tools/probe_p4.py`（実機。合否を出す）

- `--engine builtin|comfyui|both` で 8 枚を実際に付け、**§1.2 の線 1・8・9**（語数・両方式の一致・時間）を出す。
  **時間は「別々の画像」で測る**（同じ画像の再投入は `execution_cached` に当たる。点検 A-4）。
  線 8 の比較は**エスケープを外して**行う（点検 C-3）。
- `--gloss` で 20 語を訳し、**番号が取れたか**と所要を出す。**注入**で次の 4 つを試せる（点検 A-3 / F）:
  `--inject-short`（行が足りない）／`--inject-unnumbered`（番号の無い行）／`--inject-english`（英語のままの行）／
  `--inject-empty`（空の応答）。**どの注入でも `tag_gloss` に誤った行が入らない**ことを出す。
- ComfyUI 経由は**複製（`POST /upload/image`）を作ってから**投げ、**終わったら `temp` に残す**（G-6）。
- **`onnxruntime` が無い環境では `builtin` を「使えない」と出して飛ばす**（赤くしない）。

---

## 9. 工程（小段と、Fable に監査させる単位）

| 段 | 内容 | 合格の線 | 監査に渡す物 |
| --- | --- | --- | --- |
| **P4-0** | v5 の移行（5 表）、契約（`Tag.gloss`）、`review.json` の `tags[]` を埋める、語の正規化（純関数） | §8.1 の 3・17・18・19 が緑。既存の 224 件が緑 | 差分と `pytest` の結果 |
| **P4-1** | タガー 2 方式、ジョブ（進行・中断・失敗）、タグの API（取得・手動）、PNG の語。**CUDA の DLL の用意**（G-3 / 点検 B-2）もこの段の作業に入れる | §1.2 の線 1・2・7・8。§8.1 の 1・2・4〜8・12〜16・20・22〜26 | `probe_p4.py --engine both` の生の出力と時間（**別々の画像で**） |
| **P4-2** | 語釈（**番号付きで頼む**・番号で対応・1 語ずつへの落とし方・`edited` の保護・`sampling off`） | §1.2 の線 4〜6。§8.1 の 9〜11・21 | `probe_p4.py --gloss` の生の出力（**20/20 が返ったか**・注入 4 種の結果・時間） |
| **P4-3** | 画面（拡大のタグ欄・`#/tags`・`#/jobs`）、`?tag=`、`frontend-design.md` の追記 | §1.2 の線 3・9。§8.2 の 8 件・§8.3 の 4 件 | 3 窓の画面写真と `gui_layout` の出力 |

- **各段で `pytest` / `gui_smoke` / `gui_layout` を緑に保つ**（P5・P6 と同じ）。
- **（点検 C-3）実装の順は「内蔵を先に動かし、ComfyUI は `IllustTagger` で比べる」。** こうすると
  内蔵と ComfyUI の語の一致（線 8）を**複製の問題を避けて**確かめられる（内蔵は ComfyUI に画像を渡さない）。
- **P4-1 の内蔵方式は「ComfyUI と一致してから」既定にする**（§0.4・§1.2 の線 8）。
  一致しなければ**既定を `comfyui` にしたまま**内蔵を「実験的」と画面に書き、§10-1 に残して先へ進む。

---

## 10. 未確認とリスク（**推測で埋めない**）

| # | 未確認・リスク | どう扱うか |
| --- | --- | --- |
| 1 | **内蔵の前処理が ComfyUI と語単位で一致するか**（BGR・白パッド・0〜255・CSV の行順） | **実行で確かめた**（同じ画像で 66 = 66、差 0。点検 C-2）。残る未確認は **黒パッドの影響**（正方形の画像では差 0。**縦横比の違う画像では未確認**。点検 H）と、**他のモデルの CSV で `category` の順が違う場合**（→ 検査を足した。§3.2 / §8.1-24） |
| 2 | **`onnxruntime` の導入**（CUDA の持ち込み・サイズ） | 任意依存（§0.4）。**入らない環境でも P4 の線 1 は `comfyui` で満たせる**。`doctor` 相当に **`get_providers()` の実値**を出す（点検 B-2。**CUDA の DLL が無いと黙って CPU に落ちる**）。**CUDA / cuDNN の DLL を自分で用意する**のが P4-1 の作業（G-3） |
| 3 | **ComfyUI が落ちているとき** | `POST /api/assets/tag` は**接続を先に 1 回**確かめ、だめなら **409 `tagger_unavailable`**（263 件分の失敗を積まない）。実行中に落ちたら、その時点で `job.state='failed'`＋`error` に理由（**既に付いた語は残す**） |
| 4 | **語釈の行数が崩れる境目**（何語まで 1 回で頼めるか） | **番号付きなら 20 語で 20/20 が返る**（実測 4 回。40 語でも 38/40）。**P4-2 で 5 / 10 / 20 / 40 語を測って**上限を決める（測ってから決める）。**番号が取れなかった語は 1 語ずつに落ちる**（§0.9） |
| 5 | **`score` を返さない方式の扱い**（点検 B-1） | **`IllustTagger` は 4 桁で返す**（保存する）。**`WD14Tagger` と内蔵では `score` は NULL**（§4.3）。**画面には P4-3 では出さない**（どちらの方式のスコアか混ざるため）。出すなら印と一緒に、と決めてから |
| 6 | **機械の語を人が消せるようにするか** | いまは `manual` だけ消せる（§4.3）。「タガーが付けた誤りを消したい」要望が出たら、**`hidden` の印を足す**（行は消さない。履歴を失わない） |
| 7 | **`tag` の語彙が増え続ける**（未知の語・誤った語） | 語彙の統合・改名は作らない（`design.md` §16.1）。**語の一覧に件数**を出し、0 件の語が見えるようにする（人が判断できる） |
| 8 | **訳の質**（タグ用語として通る日本語か） | 「訳は自動」を画面に出し、必ず直せる導線を出す（`design.md` §15 のリスク 15）。`system_prompt` は**設定**にして、文面を直せば挙動を変えられるようにする |
| 9 | **`final_prompt` が無い画像**（JPEG・古い PNG・UI 実行の画像） | `source='png'` の語は付かない（`final_prompt` が無い）。**タガーの語だけ**が付く。これは正しい（PNG に語が残っていない） |
| 10 | **`asset_meta` の `meta_json` が `"null"` の行** | 実データにあった（**183 / 263 枚だけが読める JSON を持つ**）。読めない行は「メタが無い」として扱い、落ちない |
| 11 | **10,861 語の一覧の表示** | `#/tags` は件数の多い順に**上位 200 語**を出し、検索で残りに届く（全部を一度に描かない） |
| 12 | **ジョブの履歴が増える** | `#/jobs` は**新しい 50 件**だけ出す。古い job は消さない（表は小さい） |
| 13 | **`GET /api/assets` がメモリ上の一覧**（現物） | `?tag=` は SQL で `asset_id` を引いてから絞る（§3.6）。**一覧 API の作り直しはカタログの段**（§1.3） |
| 14 | **`review.json` に語を入れるとファイルが膨らむ** | `include_tags` の既定は `false` のまま（`design.md` §9.4）。**語を入れた全件は 100 MB 規模**になりうる |
| 15 | **P4 の前に P2 / P3 が未実装** | 画面は `#/asset/<id>`（ある）＋ `#/tags` / `#/jobs`（この段で作る）だけで足りる。`#/library` のタグ検索は `?tag=` の 1 つだけ足す（§3.6） |

**点検 H の「確かめられなかったこと」**（設計の段では実行できないもの。**P4 の各段で確かめる**）:

| # | 未確認 | どう扱うか |
| --- | --- | --- |
| 16 | **ジョブ・API・`GET` の副作用・`actor`・409・`client_token`**（点検指示書の 4・5） | **実装が無いので実行していない。** 設計の文面としては §0.10 の表で一貫している（`GET` は書かない・`human` だけ・`PUT` 無し）。**P4-1 / P4-2 の監査で実行して確かめる** |
| 17 | **`tools/probe_p4.py` / `tests/test_tags.py` 等** | 設計の段なので**存在しない**（P4-0 以降で作る） |
| 18 | **語釈の結果の文面依存** | 点検の値は**点検者が書いた `system_prompt` でのもの**。設計は文面を設定に逃がしているので、**文面と形式（番号付き）をセットで固定する**（§0.9。`system_prompt` の初期値をこの段で置く） |
| 19 | **複数フレーム（バッチ）** | ノードはバッチを受けるが、点検では 1 枚ずつしか投げていない。**P4-1 で 1 枚ずつ投げる実装にする**（バッチは使わない） |
| 20 | **GPU の同時実行**（ComfyUI が生成中のときのタグ付け） | 測っていない。**ワーカーは 1 本**なので、生成と重なると待つ（`design.md` §8.2 の「GPU の同時実行は 1」）。**待ち時間は保証しない**と画面に書く |
| 21 | **`POST /upload/image` で `temp` に置いた複製が再起動で消えるか**（点検 A-2 / G-6） | **未確認。** 消えなければ `temp` に溜まる。**P4-1 で確かめ、消えないなら「ジョブの開始時に `temp/image-reviewer/` を空にする」を足す**（消す口が無いので、自分で消すしかない） |
| 22 | **v3 → v5 の移行**（点検 H） | v5 の `migrate` が無いので実行していない。**`migrate()` の形（`db.py:226-248`。`current < N` を順に当てる）で通る**見込み。**§8.1-17 のテストで `.data` の写しから 1 回で v5 に上げて確かめる** |

---

## 11. 用語（この段で増えるもの）

| 語 | 意味 |
| --- | --- |
| **出所（source）** | その語がどこから来たか。`png`（生成に使った語）/ `wd14`（タガーが画像から読んだ語）/ `manual`（人が付けた語） |
| **正規形** | `tag.name` の形。小文字・語間は `_`。`long_hair` |
| **タガー** | 画像から Danbooru の語を推定するもの。内蔵（`onnxruntime`）と ComfyUI 経由の 2 方式 |
| **語釈（gloss）** | 語の日本語。`tag_gloss`。人が直せる（`edited=1`） |
| **訳す** | 語釈を作ること。**`POST` だけ**が行う（`GET` は訳さない） |
| **見えた語だけ訳す** | 画面に出ている語のうち語釈が無いものだけを訳す（先に全部は訳さない） |
| **ジョブ** | 時間のかかる処理の単位（`job`）。進行・中断・失敗の記録を持つ |
| **定常** | モデルの読み込みが済んだ後の 1 枚あたりの時間。**測り方は「別々の画像を順に投げる」**（同じ画像の再投入は `execution_cached` に当たるので**定常ではない**。点検 A-4） |

---

## 12. 確かめてほしい点（レビュアー向け）

> **この節は点検の前に書いたもの。点検（[`p4-review-report.md`](p4-review-report.md)）で A-1〜A-4 / B / C / D / E / F /
> G-1〜G-9 が出て、**すべて反映済み**（仕分けは [`p4-review-triage.md`](p4-review-triage.md)）。
> 以下は**次の点検（実装の監査）でもう一度見てほしい点**として残す。

1. **§0 の差分が `design.md` と衝突していないか。** とくに 0.3（`job` を P4 で作る）、0.4（検出して方式を決める。
   **`get_providers()` の実値**）、0.5（**既定は `IllustTagger`**・複製の作り方と後始末）、0.7（**括弧とコロンを残す**）、
   0.8（PNG の語は `known` を付けて全部入れる）、0.9（**番号付きで頼み、番号で対応**・`sampling off`）。
2. **合格の線が「実行して確かめられる形」になっているか。** §1.2 の 9 つで足りるか。
   **線 8（内蔵と ComfyUI の一致）が重すぎないか**（一致しなければ先へ進めない書き方になっている。§9 の逃げ道は妥当か）。
   **線 9 の測り方**（別々の画像。同じ画像の再投入は使わない）が守られているか。
3. **§8 の「壊すと落ちるか」が本当に落ちるか。** とくに **8（括弧を壊さない）**・**9（番号の無い行を入れない）**・
   11（`GET` が訳さない。**`GET /api/tags/{tag_id}/gloss` も対象**）・12 / 19（**`score` が NULL の並び**）・
   17（**v1 / v3 / v4 から v5**）・18（**語釈を 1 件入れてから** `gloss` を出す）・23〜26（新しく足した 4 件）。
4. **「実装者が気づいていない前提」が残っていないか。**
   （P6 では「`GET` がファイルを書く」「部分索引が使えるか」「境界の 1 画素」が盲点だった。
   P4 では **CSV の語名の括弧**・**ComfyUI への画像の渡し方**・**キャッシュに当たった時間**・
   **CUDA の DLL が無いと黙って CPU に落ちる**が同じ型の罠だった。§10 に 22 件挙げたが、抜けは無いか）
5. **`job` の設計**（1 本のワーカー・2 秒のポーリング・`cancelled` でも書いた行を残す・履歴を消さない・
   **`queued` が残るのはワーカーが動けないときだけ**）が、`design.md` §5.5 / §8.2 と食い違っていないか。
   **SSE を作らない**判断は妥当か。
6. **語を「消せない」判断**（§4.3・§10-6）。タガーの誤りを消したいという当然の要望に、
   `hidden` の印で答えるのが正しいか、それとも行を消す口を作るべきか（**P4 では作らない**と決めた。G-8）。
7. **`design.md` を書き換えるべき箇所**（この段の決定を本体に反映する。**点検 E の 10 件を足した**）:
   1. §5.1 の `tag` / `asset_tag` に `CHECK` と `model` の使い方（**`known` を足す**）。
   2. §5.5 の `job` を **P4 で作る**（`state` に `CHECK`）。
   3. §8.2 の「内蔵を既定」に**検出の順**と**方式ごとの実測値**を足し、「0.5 秒/枚・1 万枚 1.5 時間」を**方式ごと**に直す。
      さらに「`CUDAExecutionProvider` が使えなければ CPU へ落ちる」に「**落ちたことを画面に出す**」を足す。
   4. §8.2 の「前処理は実装時に実測して固定」を **§0.6 の 9 項目**で埋める（**実行で一致を確認済み**）。
   5. §8.4 に**語釈の頼み方（番号付き）と対応の取り方**、`sampling off` を足す。
   6. §6.3.2 / §8.2 に **ComfyUI 経由の画像の渡し方**（`POST /upload/image` → `[temp]`）と複製の後始末（G-6）を足す。
   7. §5.1 の `tag.category` のコメントに「**eva02 v3 の CSV は 0 と 4 と 9 だけ**」を添える。
   8. §3.6 の `?tag=` を §6.1 の `GET /api/assets` の引数に足す。
   9. §6.1 の `engine` に **`auto`** を足し、`GET /api/tags` に **`source` と `cursor`** を足す。
   10. `frontend-design.md` §3 の 8 番・9 番に「**P4-3 で作る**」と、**§4.5 タグ（新設）**を足す。
