# プロトタイプの記録（第 1 版・閲覧と来歴の表示まで）

利用者の回答「実装前にプロトタイプを 1 つ作って判断」に対する成果物。
**合格の線は「来歴が実データで読めること」**（利用者の回答）。

- 起動: `uv run image-reviewer serve --port 8790` → http://127.0.0.1:8790
- 走査: `uv run image-reviewer scan --root <フォルダ>`
- テスト: `uv run pytest -q`（9 件）
- 保存: `.data/store.json`（設計では後に SQLite。§「設計との差」参照）

---

## 1. 入っているもの（範囲どおり）

| 機能 | 状態 |
| --- | --- |
| フォルダの走査（内容ハッシュで登録。同じ絵は 1 つにまとまる） | ○ |
| サムネイル（256px / 1024px、WebP。一度作ったら再利用） | ○ |
| 一覧（フィルム状に隙間なく並べる。遅延読み込み） | ○ |
| 詳細（生成の来歴。モデル・CLIP・VAE・LoRA・seed・steps・cfg・denoise・sampler・scheduler・大きさ・ノード構成） | ○ |
| PNG から **日本語原文** を取る（グラフの結線を辿る） | ○ |
| PNG の**リテラルな最終プロンプト**を取る | ○ |
| **当時の英訳を捕獲する**（`/history` を 1 回走査。監視の代わり）＋ 最終プロンプトの再構成 | ○（手動・1 回だけ。監視は未実装） |
| **タグ**（最終プロンプトの語を 2 行で表示。日本語の語釈は未取得の旨を出す） | ○（語釈は未実装） |
| **ワークフローの書き出し**（API 形式。UI 実行の画像は UI 形式も） | ○（実データで 200 を確認） |
| 来歴が無い画像の扱い（80 枚が該当。「prompt チャンクが無い」と出す） | ○ |
| Host / Origin / Content-Type の検査（設計 §6.3.1） | ○ |
| 密度（密 / 普 / 疎）とテーマ（表 / 暗幕）の切替 | ○ |
| 絞り込み（すべて / 来歴あり / 来歴なし / 種別 / モデル） | ○ |

## 2. 入っていないもの（範囲外。設計にはある）

- **キープ / ボツ**と理由（判断の台帳）
- **まとまりのレビュー**、比較、重複の整理、削除
- **エージェントからの要求**（`review_request`）
- **注記**（矩形・楕円）
- **タグ付け**（WD14）と**日本語の語釈**（`TextGenerate`）
- **監視**（ComfyUI の `/api/jobs` を見て英訳を捕獲する仕組み）
- **条件の記録と再利用**（`recipe_*` / `preset` / 印つきの書き出し）
- 検索、スマートフォルダ、バックアップ、トレイ、ショートカット起動

---

## 3. 実データで確かめたこと（証拠）

### 3.1 走査（`C:\work\illust-authoring\.store\anima-dev`）

```
走査: 見た 262 / 画像 262 / 新規 262 / 既知 0 / 入れ替わり 0 / 画像でない 0
来歴あり 182 / 参照切れにした 0        所要 1.8 秒
```

- **262 枚のうち `prompt` チャンクを持つのは 182 枚**（69%）。残り 80 枚は生成条件が残っていない
  （後処理の出力など）。→ **「来歴なし」の表示を実データで試せた**のは収穫。
- モデルの内訳: `anima-turbo-v1.1` 149 / `anima-aesthetic-v1.1` 29 / `waiANIMA_v10Base10` 1
- **UI 形式（`workflow` チャンク）を持つ画像は 0 枚**。すべて API 生成のため、
  一覧の「UI 形式を保存」は常に「持っていない」と返る（設計どおりの分岐）。
- 実測 1.8 秒 / 262 枚（278 MB）＝ **約 154 MB/s**。ハッシュの実測 399 MB/s より遅いのは、
  同じパスで PNG 解析も同時に走らせているため（1 枚あたり 6.9 ms）。

### 3.2 来歴の中身（HTTP 経由で取得した実データ）

```
file      : 05de74b387c0050f.png
model     : anima-aesthetic-v1.1.safetensors   clip: qwen_3_06b_base.safetensors   vae: qwen_image_vae.safetensors
seed/steps: 3 / 30   cfg 4.5   er_sde/simple   denoise 0.4
positive  : masterpiece, best quality, safe, 1girl, 1boy, (from behind:1.5), facing away, …（206 語）
final_prompt_source: png_literal
node_types: UNETLoader, CLIPLoader, VAELoader, CLIPTextEncode×2, EmptyLatentImage, KSampler,
            VAEDecode, SaveImage, LoadImage, ImageScale, VAEEncode
```

- `LoadImage` / `ImageScale` / `VAEEncode` が入っているので、この 1 枚は **img2img 系**の出力だと
  グラフから分かる。`denoise 0.4` もそれと整合する。**来歴が読めている証拠**。

### 3.3 ja2en（日本語 → 英訳）の経路 — 見本画像が消えていたので `/history` で確かめた

`output\ComfyUI\Anima\20261013` の 6 枚は**既に削除されており**、`ComfyUI\output` 全体を探しても
`TextGenerate` を含む PNG は **0 件**だった。そこで `/history` に残っていた当時の実行で確かめた
（`tools/verify_against_history.py`。読み取りのみ、ComfyUI に何も投げない）。

```
ja2en の実行を 3 件調べ、3 件で訳の捕獲と最終プロンプトの再構成まで到達した。
```

1 件目の実際の値:

| 項目 | 値 |
| --- | --- |
| モデル / LoRA | `anima-turbo-v1.1` / `BuAnime_NSFW_Style_Anima_BuAnimeV2` |
| seed / steps / cfg | `338134650120909` / 10 / 1.0、`er_sde` / `beta`、denoise 1.0 |
| 大きさ | 768 × 1360 |
| 日本語原文 | グラフの `PrimitiveStringMultiline` から取得（結線を辿った） |
| TextGenerate | `temperature=0.7` `seed=20261010` `mtp=auto` `thinking=False` |
| 訳の出口 | `StringConcatenate.string_b` と `PreviewAny.source`（**結線で特定**） |
| 捕獲した訳 | `outputs["11"].text[0]`（**リストの先頭**）2478 文字 |
| 最終プロンプト | `"(masterpiece, best quality, good quality, score_9), safe," + "\n\n" + 捕獲値` = 2537 文字 |

**これで設計の要（R4b と L1）が実データで通ることが示せた。** とくに:

- `outputs[].text` は**リスト**（実測どおり）
- 訳は**グラフの結線で特定**できる（ノード番号ではない）
- **捕獲値は最終プロンプトではない**（品質語が前置される）。固定するなら再構成が必要

### 3.4 新しい ja2en の画像を、生成の瞬間から捕獲する（初めて通しで通った）

利用者が ComfyUI で**日本語プロンプトの画像を実際に出力した**（`ComfyUI\Anima\20261010\132800_00001_.png`、
1360×1360、9:09 作成）。それを使って通しで確かめた。

| 段 | 結果 |
| --- | --- |
| 走査 | 1 枚を新規登録（`prompt` と **`workflow`** の両方を持つ。**プロトタイプ初の UI 実行**） |
| 日本語原文 | 取れた（`ja_source: png_primitive`）: `1girl. solo. chibi. safe.` ＋ 「背景にハートのエフェクトがある…」 |
| PNG の最終プロンプト | **無い**（`final_prompt_source: None`）。設計の核心どおり |
| `/history` の照合 | 出力ファイル名で実行を特定（`prompt_id 064994ca-…`）。`TextGenerate` はノード 9 |
| 訳の出口 | `10 StringConcatenate.string_b` と `11 PreviewAny.source`（**結線で特定**） |
| 訳の捕獲 | `outputs["11"].text` は**リスト**、先頭が 392 文字の英訳 |
| 最終プロンプト | 再構成 451 文字 = `"(masterpiece, best quality, good quality, score_9), safe," + "\n\n" + 捕獲値` |
| UI 形式のグラフ | **200 で取れる**（11,349 bytes）。API 形式は 4,064 bytes |

→ **R4b（日本語と英訳）と R4a（ワークフロー）が、実在する 1 枚で端から端まで通った。**

**分かった運用上の事実**: 走査済み 263 枚のうち、訳が未取得で `/history` から捕獲できたのは**この 1 枚だけ**。
残り **182 枚は当時の実行が `/history` から消えている**（メモリ上のみのため）ので、捕獲では埋まらない。
→ 埋める手段は**訳し直し（§7.3.2）か手入力だけ**。監視（P3）を入れる前の画像はこうなる、という実例。

### 3.5 API と守り

| 確かめたこと | 結果 |
| --- | --- |
| `/api/health` `/api/stats` `/api/assets` `/api/assets/{id}` | 200（来歴の中身まで返る） |
| `/api/assets/{id}/thumb?size=256` | 200 `image/webp` 15.9 KB、`Cache-Control: public, max-age=31536000, immutable` |
| `/api/assets/{id}/thumb?size=1024` | 200 126 KB |
| `/api/assets/{id}/graph?format=api` | 200、`Content-Disposition: attachment` |
| `/`（同一オリジン配信） | 200（`app.js` / `styles.css` も配信） |
| `Host: evil.example` | **403** |
| `Origin: http://evil.example` を付けた POST | **403** |
| `Content-Type: text/plain` の POST | **403** |

---

## 4. 設計との差（プロトタイプとして意図的に省いた / 変えた点）

| 設計 | プロトタイプ | 理由 |
| --- | --- | --- |
| SQLite（WAL） | `store.json` 1 ファイル | 利用者の回答（まず JSON）。262 枚では十分 |
| `asset.id` は ULID、`sha256` は別 | **`id` = `sha256`** | 内容が正体であることが一番分かりやすい。DB へ移すときに分ける |
| 仮想スクロール | 全件を DOM に置く（`loading="lazy"`） | 262 枚では不要。1 万枚では必要（設計どおり実装する） |
| 前面は素の TypeScript + Vite | **素の JS（ビルド無し）** | プロトタイプの目的は来歴の確認。ビルドを挟まない方が速く回せる |
| pHash / 重複検出 | 未実装 | 範囲外 |
| 行間 16px のフィルム | 1px の継ぎ目で全面を接（行間なし） | 見た目は実物のベタ焼きに近い。設計の行間は仮想化と一緒に入れる |
| 設定は DB | 起動引数と環境変数 | 範囲外 |

## 5. 途中で見つけて直した自分の不具合（テストに残した）

1. **`mark_missing` が別のルートの画像まで参照切れにした。** 2 つ目のフォルダを走査しただけで
   1 つ目の 262 枚が全部「参照切れ」になった。→ 走査したフォルダの下だけを見るよう修正
   （`test_scan_only_marks_missing_inside_scanned_roots`）。
2. **置き換えが `created` に計上されていた。** 同じパスの中身が変わると新規扱いになり、
   「入れ替わり」が 0 のままだった。→ 判定の順序を修正（`test_path_content_change_creates_history_row`）。
3. **pytest の既定の一時フォルダがこの環境の制限に当たった**（`%TEMP%` と拡張パス `\\?\` での削除）。
   → `tests/conftest.py` に自前の `tmp_path` を置き、`-p no:tmpdir` で既定を切った。

## 5b. Fable の点検（2 回目）で見つかって直したもの

点検の仕分けは [`review-triage-fable.md`](review-triage-fable.md)。実装側で直したのは:

| 点検 | 内容 |
| --- | --- |
| **B5** | 一覧のサムネイルが `cover` で縦長画像の上下 44% を切っていた（手・足・背景の窓＝ボツ理由のある場所）。→ **高さを密度で固定し、幅を絵の縦横比から決める**（切らない） |
| **I1** | パスの正規化が無く、小文字で走査し直すと**全ファイルが再登録**された。→ `normcase(realpath)` を鍵に統一。区切り文字の単位で比較 |
| **I2** | `seed` などが結線のとき `str(["20", 0])` が値になっていた。→ 結線を辿って `Primitive*` の値を解決 |
| **I5** | **sidecar を書いていなかった**（唯一 PNG から取り直せない英訳が `store.json` だけにあった）。→ `<data>/sidecar/<sha256>.json` に原子的に書く |
| **I3** | `clip` が「最初の `CLIPLoader`」、`llm` 未抽出、正負を「空文字か」で判定。→ 正側が参照するものを使い、正負は結線で決める |
| **I13** | LoRA の**重み**が入らず、`LoraLoader` を無視し、複数 `KSampler` が上書き。→ 重み付きの構造に、両方の型、主のサンプラを 1 つに |
| **I4** | 壊れたチャンクを黙って捨て、権限エラーを「PNG ではない」と報告。→ 理由を残し、`zTXt`/`iTXt` も復号 |
| **I6** | 同名ファイルを名前だけで照合。→ `subfolder` を突き合わせ、曖昧なら埋めない |
| **I9** | 来歴なしを薄く見せていた（設計に無い。ボツと混ざる）。→ やめて `--warn` の印に |
| **I14** | テスト名が「`IDAT` の後」なのに、Pillow は前に書くので一度も通っていなかった。→ 手で組んだバイト列で本当に後ろに置いた |
| **I16** | サムネイルの一時ファイル名が固定で競合。→ `mkstemp` |
| **I19** | 1 枚につき `open` が 3 回。→ 1 回に |
| **B8** | 契約の `Provenance.seed` が数値で、JS では 2^53 超が丸まる。→ 文字列に |

→ テストは **9 件から 21 件**に増えた（`uv run pytest -q` で 21 passed）。

## 6. 片付けが残ったもの（利用者にお願いしたいこと）

pytest の設定を直す**前**の失敗した実行が、ワークスペース直下に 3 つのフォルダを残した:

```
C:\work\image-reviwer\.pytest-tmp
C:\work\image-reviwer\pytest-cache-files-f8265pg4
C:\work\image-reviwer\pytest-cache-files-nhtcmj89
```

**エージェントからは一覧も削除もできない**（`WinError 5`）。調べた結果:

- ファイル権限の修復スクリプトの判定は **`NOT_THIS_CLASS`**（＝権限の問題ではない）。
  ワークスペースの権限は正常で、**非制限の走査では 538 個すべて読めた**（`unreadable: 0`）。
- つまり**制限された実行からだけ**見えない。原因はこの 3 つの作り方（スキャン中に作られた）で、
  いまのセッションの制限では触れない、というもの。

→ **利用者側で削除をお願いしたい**（エクスプローラーか、通常のターミナルで）:

```powershell
Remove-Item 'C:\work\image-reviwer\.pytest-tmp','C:\work\image-reviwer\pytest-cache-files-*' -Recurse -Force
```

`.gitignore` には入れてあるので、残っていても後の git には入らない。
テストは設定を直したので**以後はこの残骸を作らない**（`tests/conftest.py` が自前の一時フォルダを使う）。

## 7. 次にやること（このプロトタイプを使って判断したいこと）

1. **触ってみて、この見た目と操作で「次に判断するもの」をさばけそうか**（走査 → 一覧 → 来歴）。
2. 一覧にタグを出さない判断（利用者の指定）が、実際の探索で困らないか。
3. 密度（密 / 普 / 疎）とテーマの既定はこれでよいか。
4. 来歴の見せ方（表の項目・順序）で足りないものはないか。
5. そのうえで **P1（登録と表示）→ P5（判断と比較）** の順に本実装へ進む。
