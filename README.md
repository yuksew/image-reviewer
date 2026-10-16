# image-reviewer

ローカルの画像を **登録 → カタログで見る → タグと生成の来歴を見る → まとまりごとに比べて
キープ / ボツを決める** ツール。`127.0.0.1` で動く Web アプリ。

**他のツールとは連携しない**（コードもデータも語彙も合わせない）。接続先は ComfyUI だけ。

> **現在のフォルダ名は `C:\work\image-reviwer`（`reviewer` ではなく `reviwer`）。**
> `image-reviewer` に改名する方針は決まっているが、**このセッションからは改名できない**
> （書き込み権限がこのパスに固定されているため、`C:\work\image-reviewer` の作成が拒否される）。
> 手順は [`docs/design.md`](docs/design.md) §16.2 の 1 を参照。文書内の名前は既に `image-reviewer` にしてある。

- 状態: **P5（判断と比較）・P6（要求と注記）・P4（タグと語釈）・P7（条件の記録）が動く。テスト 403 件。** 各段は
  設計 → Fable の点検 → 小段ごとの実装 → **Fable が実行込みで監査** → 指摘の反映、で進めている
  （P6 は [`docs/p6-morning-report.md`](docs/p6-morning-report.md)、P4 は [`docs/p4-design.md`](docs/p4-design.md) と
  その監査・仕分け（`docs/p4-*-audit-report.md` / `docs/p4-*-audit-triage.md`）、
  **P7 は [`docs/p7-design.md`](docs/p7-design.md) と段ごとの記録（`docs/p7-*-implementation.md` / `docs/p7-*-audit-report.md`）、
  段の全体は [`docs/handoff.md`](docs/handoff.md)**）。
- 進め方: **DeepSeek が設計書を書く → Claude Code の Fable が点検 → DeepSeek が実装 → Fable が監査**

## 動かす（プロトタイプ）

```powershell
$env:UV_CACHE_DIR = "$PWD\.uv-cache"
uv sync
uv sync --extra tagger                      # 内蔵タガー（onnxruntime。任意。入れると `auto` が内蔵を選ぶ）
uv run image-reviewer scan --root 'C:\work\illust-authoring\.store\anima-dev'
uv run image-reviewer serve --port 8790     # → http://127.0.0.1:8790
uv run pytest -q                            # 403 件（P7 まで）
node tools/gui_smoke.mjs                    # 画面の組み立て（CSS を持たない軽い DOM で。164 検査）
node tools/gui_layout.mjs --base http://127.0.0.1:8790 --count 8          # 比較（3 窓）
node tools/gui_layout.mjs --base http://127.0.0.1:8790 --screen requests  # 要求の一覧
node tools/gui_layout.mjs --base http://127.0.0.1:8790 --screen group --group <id>   # まとまりレビュー
node tools/gui_layout.mjs --base http://127.0.0.1:8790 --screen asset --ids <id>     # 注記とタグ
node tools/gui_layout.mjs --base http://127.0.0.1:8790 --screen tags       # 語の一覧
node tools/gui_layout.mjs --base http://127.0.0.1:8790 --screen jobs       # ジョブの進行と監視
node tools/gui_layout.mjs --base http://127.0.0.1:8790 --screen recipe --ids <id>  # 条件の記録（P7-4）
node tools/gui_layout.mjs --base http://127.0.0.1:8790 --screen recipes      # 記録の一覧（P7-4）
uv run --no-sync --with jsonschema python tools/check_contract_p7.py  # P7 の契約（manifest・review.json・v6）
uv run python tools/probe_p4.py --engine comfyui   # タグ付けの線 1・2・7（実機）
uv run python tools/probe_p4.py --gloss            # 語釈の線 4・5・6（実機）
uv run python tools/probe_p7.py --judge            # 条件の記録の線 2（複製 263 枚で exact/approx/impossible）
uv run python tools/probe_p7.py --export           # 書き出しの線 3・4・5（印つき・manifest）
uv run python tools/probe_p7.py --watch            # **線 6（合格の門）** 偽の ComfyUI で結果の紐付け
```

- **`uv sync` はサーバを止めてから打つ。** 動かしたままだと `os error 32`（使用中のファイルを置き換えられない）
  で失敗する。
- **止めた直後に `export/groups/*.json` を読むなら 1 秒待つ。** `uv run` 経由で `serve` を止めると
  `uv` が先に終わり、python（uvicorn）の `lifespan` の書き出しがその後に走る（監査 D3）。
  待ちたくないときは `uv run python -m image_reviewer.cli serve --port 8790` で上げる。

入っているのは**閲覧と来歴の表示、判断（キープ / ボツ。まとまりごとの決定と理由まで）、比較（並べる /
来歴の差分表 / 同期ズーム / 差分ヒートマップ / 似ている順）、エージェントからの要求（受付・一覧・
断る・判断で閉じる）、注記（矩形・楕円・画像 1 枚へのメモ・座標 JSON・切り出し PNG）、
タグ（内蔵タガーと ComfyUI 経由。出所つき・手で足す/外す・`#/tags` の一覧と検索・`#/jobs` の進行）、
日本語の語釈（見えている語だけ訳す・人が直せる・`edited` を守る）、
**条件の記録（生成の条件を記録して再現キーを持つ・判定（完全 / 近似 / 不可）と理由・書き出す前の検査・
印つきのグラフの書き出し・seed 違い・`#/asset/<id>/recipe` と `#/recipes` の画面）と、
監視での結果の取り込み（印から結果の画像を紐付け・指標・人が合否を記録）**まで**
（**P8（重複・削除・5 分の取り消し・バックアップ）と P9（仕上げ）は未着手**。
**タグの統合・改名、本格的な検索、プリセットの画面、`userdata` への設置（P3）も未実装**）。
記録は [`docs/prototype-notes.md`](docs/prototype-notes.md)。実データで確かめた結果もそこにある。

## 文書

| ファイル | 中身 | 点検の観点 |
| --- | --- | --- |
| [`docs/design.md`](docs/design.md) | 全体・バックエンド設計（要件対応表・アーキテクチャ・データモデル・API・性能・工程・リスク・用語） | §19 |
| [`docs/frontend-design.md`](docs/frontend-design.md) | 画面の設計（デザインプラン・色・書体・配置・部品・文言・アクセシビリティ） | §12 |
| [`docs/comparison.md`](docs/comparison.md) | 比較の設計（見た目・来歴・機械の指標、位置合わせ） | — |
| [`docs/workflow-reproduction.md`](docs/workflow-reproduction.md) | 生成の条件の記録と再利用（**実行はしない**）、印による結果の紐付け | — |
| [`docs/duplicates-deletion-backup.md`](docs/duplicates-deletion-backup.md) | 重複・削除（**5 分の取り消し**）・バックアップ | — |
| [`docs/metadata-findings.md`](docs/metadata-findings.md) | 実機で確認した前提（PNG / JPEG・タガー）＋ 実測した性能 | — |
| [`docs/comfyui-reproduction-findings.md`](docs/comfyui-reproduction-findings.md) | ComfyUI の再現経路の詳細調査（ソース引用つき・836 行） | — |
| [`schemas/review-export.schema.json`](schemas/review-export.schema.json) | 他ツールが読む外部契約（draft 2020-12、`abi: 0.1`） | — |
| [`docs/review-export.example.json`](docs/review-export.example.json) | 契約の実例（スキーマ検証済み） | — |
| [`docs/review-brief.md`](docs/review-brief.md) | **点検の指示書**（レビュアーに渡すもの） | — |
| [`docs/review-report-deepseek.md`](docs/review-report-deepseek.md) | 点検 1 回目の報告（別系統のモデル） | — |
| [`docs/review-triage.md`](docs/review-triage.md) | 1 回目の指摘の仕分けと、実機で確かめ直した記録 | — |
| [`docs/review-report.md`](docs/review-report.md) | **点検 2 回目の報告（Claude Code / Fable）。最重要 3 件を含む** | — |
| [`docs/review-triage-fable.md`](docs/review-triage-fable.md) | 2 回目の仕分け。**決まった 11 件**と優先順 | — |
| [`docs/review-triage-review1.md`](docs/review-triage-review1.md) | 1 回目の未仕分け約 40 件の仕分け（2 回目が指摘した穴を埋める） | — |
| [`docs/review-run-note.md`](docs/review-run-note.md) | Claude Code（Fable）の実行記録（1 回目未完走・2 回目成功） | — |
| [`docs/prototype-notes.md`](docs/prototype-notes.md) | **プロトタイプの記録**（範囲・実データでの証拠・設計との差・直した不具合） | — |
| [`docs/p5-design.md`](docs/p5-design.md) | **P5（判断と比較）の設計**（段の分け方・決定の反映・実装前の実測） | §11 |
| [`docs/p5-review-brief.md`](docs/p5-review-brief.md) | P5 の点検の指示書 | — |
| [`docs/p5-review-report.md`](docs/p5-review-report.md) | P5 の設計の点検報告（A2 / B5 / C16 / D / E / F） | — |
| [`docs/p5-review-triage.md`](docs/p5-review-triage.md) | P5 の指摘の仕分け | — |
| [`docs/p5-audit-brief.md`](docs/p5-audit-brief.md) | P5-0 / P5-1 の監査の指示書 | — |
| [`docs/p5-audit-report.md`](docs/p5-audit-report.md) | P5-0 / P5-1 の監査報告 | — |
| [`docs/p5-audit-run-note.md`](docs/p5-audit-run-note.md) | その監査の実行記録（1 回目は OAuth の期限切れで起動できず、再認証のうえやり直した） | — |
| [`docs/p5-2-audit-brief.md`](docs/p5-2-audit-brief.md) | P5-2（比較の基本）の監査の指示書 | — |
| [`docs/p5-2-audit-report.md`](docs/p5-2-audit-report.md) | P5-2 の監査報告 | — |
| [`docs/p5-3-audit-brief.md`](docs/p5-3-audit-brief.md) | P5-3（差分ヒートマップ・似ている順・pHash）の監査の指示書 | — |
| [`docs/p5-3-audit-report.md`](docs/p5-3-audit-report.md) | P5-3 の監査報告 | — |
| [`docs/p7-design.md`](docs/p7-design.md) | **P7（条件の記録。R12）の設計**（段の分け方・拘束力のある差分・合格の線 10 本・P3 との依存の扱い） | §12 |
| [`docs/p7-review-brief.md`](docs/p7-review-brief.md) | P7 の点検の指示書 | — |
| [`docs/p7-review-report.md`](docs/p7-review-report.md) | P7 の設計の点検報告（**判定: 直してから実装**。A 3 / B 6 / C 9 / D 12 / E 11 / F / G 7） | — |
| [`docs/p7-review-triage.md`](docs/p7-review-triage.md) | P7 の指摘の仕分け（**すべて採用**。利用者に新しく聞くことは無い） | — |
| [`docs/p7-0-implementation.md`](docs/p7-0-implementation.md) | **P7-0 の実装の記録**（v6 の 6 表・`recipe-manifest` の契約・`review.json` を変えないことの固定） | — |
| [`schemas/recipe-manifest.schema.json`](schemas/recipe-manifest.schema.json) | 書き出しの束の契約（draft 2020-12、`abi: 0.1`。§6.1） | — |

- P5 の点検・監査の**生ログ（`docs/p5-review-run.jsonl` / `p5-audit-run.jsonl` / `p5-2-audit-run.jsonl` /
  `p5-3-audit-run.jsonl`。計 約 11.7 MB）は文書表に数えない**。本文は各 `*-report.md` と `*-run-note.md`
  にある（`*-run.jsonl` は**いまも作業ツリーに残っている**——前の回の生ログは残っていないので、要らなければ削除する）。

## 何を解決するか

| したいこと | この設計での答え |
| --- | --- |
| 画像を登録して見る | 参照（コピーしない）が既定、取込も選べる。**内容（`sha256`）を正体**にし、場所は従属させる |
| 画像を取り込む | フォルダ走査 / ドラッグ&ドロップ / クリップボード / 画像 URL。書き出し・改名・メタデータ埋め込みは対象外 |
| カタログで見る。独自のフォルダ分け | 仮想フォルダ（**1 枚が複数所属可**）＋条件で貯まるスマートフォルダ |
| 生成物 / 参考資料 / 写真を分ける | 種別を自動判定し、人が直せる。参考資料には出所 URL と「何の参考か」を任意で付けられる |
| Danbooru タグを見る | 出所つき（PNG / タガー / 手）。**日本語の語釈を 2 行目**に（括弧書きは使わない）。詳細と拡大だけに表示 |
| 生成のワークフローを見る | グラフを書き出して ComfyUI へドラッグ&ドロップ（**API 形式のままでも読める**） |
| 日本語と英訳を見る | 日本語は PNG から取得。英訳は**当時の訳**と**訳し直した訳**を区別して表示 |
| キープ / ボツと理由を付ける | 追記のみの判断台帳 ＋ 編集できる理由マスタ。段階評価（星）は入れない |
| まとまりから 1 枚選ぶ / 全部ボツ | まとまりレビュー画面。落とした枚にも**その枚自身の理由**が付く |
| 複数を比べる | 並べる / 来歴の差分表 / 差分ヒートマップ / 同期ズーム / 似ている順。点滅・スワイプ・重ねるは後から |
| 画像の上に印を付ける | 矩形と楕円。座標は 0〜1。座標 JSON と、囲んだ範囲ちょうどの切り出しを書き出せる |
| エージェントにレビューを頼まれる | `POST /api/review-requests`。投げてすぐ返り、エージェントはポーリングで結果を得る。AI の下書きと人の判断を両方残す |
| うまくいった条件を使い回す | 記録・コピー・ComfyUI で開く・**seed 違いのグラフ書き出し**・名前を付けて保存。**実行はしない** |
| 他のツールから結果を読む | REST `GET /api/export/review.json` ＋ `<data>/export/review.json`（版付き契約） |
| タグの無い画像にタグを付ける | **この環境の既定は ComfyUI の `IllustTagger`**（`settings` の `tagger.engine=comfyui`・`tagger.node=illust`。0.27 秒/枚）。内蔵 WD14（`onnxruntime-gpu`、`tagger.engine=auto` で内蔵優先）も選べる（**いまは CPU 版しか入っていないので 1.30 秒/枚**） |
| 重複を整理して本当に消す | 内容ハッシュと知覚ハッシュ。実削除は**5 分間取り消せる** |
| 速く動く | 実測に基づく目標値（下記） |

## 設計を決めた実機の事実

1. **英訳結果は PNG に残らない。** ComfyUI の `TextGenerate`（利用者の言う「TextGenerator」の実体。
   本体同梱の `comfy_extras/nodes_textgen.py`）の出力は実行時の値で、`/history` にもメモリ上しか残らない。
   → **生成の瞬間を監視して捕まえる**。書き出すグラフでは捕獲した英文を固定する（L1）のが唯一確実な方法。
2. **API 形式のグラフは ComfyUI が自分で読める**（`loadApiJson` が API → UI 変換を実装）。
   当初「変換が必要」と考えていたのは誤りで、訂正済み。
   位置まで復元できるのは UI 形式を持つ画像だけ（実測 1,028 枚中 175 枚）。
3. **利用者のワークフローを URL で開く手段は無い。** `?workflow=` は未実装、`?template=` は同梱テンプレート専用。
4. **`GET /api/jobs/{prompt_id}` が 1 リクエストで全部返す**（API グラフ・UI グラフ・出力・状態）。
   しかも `job id == prompt_id`。→ 監視の主経路。
5. **モデルのハッシュは ComfyUI が持たない。** `(名前, size, mtime)` でピン留めするのが現実的。
6. **タグは PNG に無い。** タガーを都度呼ぶ（`IllustTagger` はスコア付きで返す）。
7. **メタデータはファイル先頭 22KB 以内にある。** 部分読みで足りる。

## 実測した性能（`ComfyUI\output` の 1,028 枚で計測）

| 項目 | 実測 | 1 万枚の見込み |
| --- | --- | --- |
| PNG のメタデータ抽出（256 KiB 上限） | 24,719 枚/秒 | **0.4 秒** |
| SHA-256 | 399 MB/s（300 枚で計測） | **28 秒**（11.1 GB = 1.11 MB/枚） |
| サムネイル生成（WebP 256px、1 スレッド） | 36 枚/秒 | 4.6 分 |

→ メタデータ抽出は性能上の問題にならない。**ハッシュとサムネイルが実費**で、どちらも目標に収まる。

## 技術

**いま入っているもの**: Python 3.12 以上（実測 3.14.7）/ uv / FastAPI / uvicorn / SQLite(WAL) / Pillow / numpy
（依存は `fastapi` / `uvicorn` / `pillow` / `numpy`。テストの `httpx` は dev だけ）。
前面は**素の JavaScript**（`apps/gui/*.js`。フレームワークなし）。
既定ポート **8790**。データ置き場は `<リポジトリ>/.data`。

**目標（未着手）**: `onnxruntime-gpu`（内蔵タガー）、`pystray` と**タスクトレイ常駐**、
ショートカット起動、前面の **TypeScript + Vite**（開発サーバは **5273**）。

## 開発メモ

この環境のサンドボックス下では uv の既定キャッシュに書けないため、`UV_CACHE_DIR` をリポジトリ内へ向ける。

```powershell
$env:UV_CACHE_DIR = "$PWD\.uv-cache"
uv sync
uv run image-reviewer serve --port 8790
```

## 次にすること

**P5（判断と比較）は完了。** P5-0（SQLite 化）/ P5-1（判断と書き出し）/ P5-2（比較の基本）/
P5-3（差分ヒートマップ・似ている順・pHash）の **4 段で、各段を Fable が監査**した
（設計の点検は [`docs/p5-review-report.md`](docs/p5-review-report.md)、指摘の仕分けは
[`docs/p5-review-triage.md`](docs/p5-review-triage.md)、監査は
[`docs/p5-audit-report.md`](docs/p5-audit-report.md)・[`docs/p5-2-audit-report.md`](docs/p5-2-audit-report.md)・
[`docs/p5-3-audit-report.md`](docs/p5-3-audit-report.md)）。監査の指摘は反映済み。

1. **次は P6（要求と注記）。** 順序は **P1 → P2 → P3 → P5 → P6 → P4 → P7 → P8 → P9**
   （点検 G11 で確定。[`docs/design.md`](docs/design.md) §14）。P6 の完了条件は
   「エージェントが要求を投げ、投げてすぐ返る」「要求の一覧から開いて判断し、判断で閉じる」
   「印を囲んでメモを付け、座標と切り出しを書き出せる」（同 §14。R10 / R11）。
2. **P5 で「この段では作らない」と決めたまま残っているもの**（意図どおり。着手は P6 以降）:
   - SSE（`GET /api/events`）は無い。画面は判断の応答（`reopened_group_ids` など）で組み直す
     （[`docs/p5-design.md`](docs/p5-design.md) §0.1）。
   - 日次の全件書き出しと件数索引（`index.json`）は未着手（同 §0.1）。全件が出るのは手動の
     `POST /api/export/review.json` だけ（`GET` は返すだけで書かない。監査 C8/G2）。
   - 差分ヒートマップの「派生関係」の条件は、その関係を持つ列ができる **P7 まで外す**（同 §0.5 G6）。
   - 色ヒストグラム距離は未実装（[`docs/comparison.md`](docs/comparison.md) §4）。
3. **残っている確認**（P5 の作りは動くが、確かめた記録がまだ無いもの）:
   - **pHash の全件計算（1,000 枚）の実測**（[`docs/p5-design.md`](docs/p5-design.md) §8 / 点検 E5）。
     記録があるのは 1 枚あたりの実測だけである（同 §0.7）。
   - **`asset.phash` / `dhash` に版が無い**（監査 C1）。縮小の仕方や入力を変えたときに古い値と混ざるので、
     `ALGO_VERSION` を上げるときは `NULL` に戻す手当てが要る。
   - **画面の見え方は `node tools/gui_smoke.mjs` では見えない**（CSS を持たない）。ブラウザで確かめる:
     `hidden` と `display: flex` の関係（監査 A1。空の帯が常に出ないか）と、並び順を変えたあとの `1`〜`8`
     （監査 C2。キーもタイルも**表示の順**で数える。以前はキーだけが `doc.items` の順だった）。
   - 点検・監査の Claude Code は**実行できていない回がある**（`EPERM: uv_spawn`。
     [`docs/p5-3-audit-report.md`](docs/p5-3-audit-report.md) の冒頭）。**2026-10-16 の実行込みの
     やり直し**で大半は実行で裏を取った（[`docs/p5-audit-redo.md`](docs/p5-audit-redo.md) ほか）。
     いま実行で裏を取ってあるのは `uv run pytest -q`（176 件）と
     `node tools/gui_smoke.mjs`（51 ok / 0 NG）、`node tools/gui_layout.mjs`（3 窓 × 3 状態）である。
