# image-reviewer

ローカルの画像を **登録 → カタログで見る → タグと生成の来歴を見る → まとまりごとに比べて
キープ / ボツを決める** ツール。`127.0.0.1` で動く Web アプリ。

**他のツールとは連携しない**（コードもデータも語彙も合わせない）。接続先は ComfyUI だけ。

> **現在のフォルダ名は `C:\work\image-reviwer`（`reviewer` ではなく `reviwer`）。**
> `image-reviewer` に改名する方針は決まっているが、**このセッションからは改名できない**
> （書き込み権限がこのパスに固定されているため、`C:\work\image-reviewer` の作成が拒否される）。
> 手順は [`docs/design.md`](docs/design.md) §16.2 の 1 を参照。文書内の名前は既に `image-reviewer` にしてある。

- 状態: **P5（判断と比較）・P6（要求と注記）・P4（タグと語釈）・P8（重複・削除・バックアップ）・
  P8-6（参照切れの再リンク）が動く。テスト 507 件**（`uv run --no-sync pytest -q` を自分で 2 回回して実測。
  `gui_smoke` **310 検査**（2 回とも ok / NG 0）・
  `gui_layout` **10 画面＋`pending --ids`** もすべて ok）。各段は
  設計 → Fable の点検 → 小段ごとの実装 → **Fable が実行込みで監査** → 指摘の反映、で進めている
  （P8 は [`docs/p8-design.md`](docs/p8-design.md) とその点検・監査
  （`docs/p8-review-report.md` / `docs/p8-*-audit-report.md`）、
  段の全体は [`docs/handoff.md`](docs/handoff.md)**）。
- **P8 の小段（P8-0〜P8-5）は全部通り、監査はどれも「合格（条件つき）」**（P8-3 の再確認は「合格（条件なし）」）。
  **P8-5（設定と文言の仕上げ）の条件 3 件だけは未反映**——「段 3 を許す」印のボタンが二度押しで 2 回 POST される・
  `gui_layout --screen asset` が印の無い置き場で必ず NG・版が新しい DB で設定の書き込みボタンが押せるまま
  （[`docs/p8-5-audit-report.md`](docs/p8-5-audit-report.md)。直し方は [`docs/handoff.md`](docs/handoff.md) §3 の 0）。
- **参照切れの再リンク（P8 の合格の線 9）は P8-6 で作った**（2026-10-18。P8 の途中で P8-3 が「重複と削除の
  画面」の段に置き換わり、線 9 だけが残っていた）。`POST /api/locations/relink`（**人だけ**）と
  `GET /api/locations/missing`（**読むだけ**）の 2 つの口で、**中身の `sha256` が一致したときだけ繋ぐ**
  （**pHash は使わない**）。**画面は無い（口だけ）**。`docs/p8-6-relink.md`。
- **条件の記録（P7。R12）は作ったが廃止した**（2026-10-17、利用者の判断。PNG を ComfyUI にドラッグすればワークフローが戻るので記録は重複で、
  ja2en の英訳ももう一度実行すれば取れるため。消した物と控えは [`docs/p7-decision.md`](docs/p7-decision.md)、記録は `docs/p7-*.md` に残す）。
- 進め方: **DeepSeek が設計書を書く → Claude Code の Fable が点検 → DeepSeek が実装 → Fable が監査**

## 動かす（プロトタイプ）

```powershell
# 起動: デスクトップの `image-reviewer.lnk`（または `start-image-reviewer.cmd`）をダブルクリック
#      （UV_CACHE_DIR を設定し、3 秒後に http://127.0.0.1:8790 を開く。トレイは無い）
$env:UV_CACHE_DIR = "$PWD\.uv-cache"
uv sync
uv sync --extra tagger                      # 内蔵タガー（onnxruntime。任意。入れると `auto` が内蔵を選ぶ）
uv run image-reviewer scan --root 'C:\work\illust-authoring\.store\anima-dev'
uv run image-reviewer serve --port 8790     # → http://127.0.0.1:8790
uv run --no-sync pytest -q                  # 507 件
node tools/gui_smoke.mjs                    # 画面の組み立て（CSS を持たない軽い DOM で。310 検査）
# 画面の計測（本物の Chrome）は**複製で立てたサーバ**へ。実データの 8790 では回さない（§「gui_layout は…」）
node tools/gui_layout.mjs --base http://127.0.0.1:8791 --count 8          # 比較（3 窓）
node tools/gui_layout.mjs --base http://127.0.0.1:8791 --screen requests  # 要求の一覧
node tools/gui_layout.mjs --base http://127.0.0.1:8791 --screen group --group <id>   # まとまりレビュー
node tools/gui_layout.mjs --base http://127.0.0.1:8791 --screen asset --ids <id>     # 注記とタグ
node tools/gui_layout.mjs --base http://127.0.0.1:8791 --screen tags       # 語の一覧
node tools/gui_layout.mjs --base http://127.0.0.1:8791 --screen jobs       # ジョブの進行
node tools/gui_layout.mjs --base http://127.0.0.1:8791 --screen duplicates # 重複の整理（P8）
node tools/gui_layout.mjs --base http://127.0.0.1:8791 --screen pending    # 最近の削除（P8）
node tools/gui_layout.mjs --base http://127.0.0.1:8791 --screen pending --ids <id>,<id>  # 削除の確認つき（P8）
node tools/gui_layout.mjs --base http://127.0.0.1:8791 --screen library    # 下部バーの削除の入口（P8）
node tools/gui_layout.mjs --base http://127.0.0.1:8791 --screen settings   # 設定（バックアップと段 3 の印。P8）
uv run python tools/probe_p4.py --engine comfyui   # タグ付けの線 1・2・7（実機）
uv run python tools/probe_p4.py --gloss            # 語釈の線 4・5・6（実機）
uv run python tools/probe_p8.py --duplicates       # 重複の検出（P8 の線 2〜4。総当たりと突き合わせる）
uv run python tools/probe_p8.py --delete           # 削除の 3 段階と 5 分の取り消し（線 5〜8）
uv run python tools/probe_p8.py --backup           # 日次バックアップと健全性（線 10・12）
uv run python tools/probe_p8.py --restore          # 復元と組み直し（線 11）
uv run python tools/probe_p8.py --relink           # 参照切れの再リンク（P8-6 の線 9）
uv run python tools/probe_p8.py --all              # 全部（自分で立てたサーバと一時の置き場を使い、後始末する）
uv run image-reviewer backup --out <dir>           # いま 1 回取る（--include-library で画像の実体も）
uv run image-reviewer restore <dir>                # 戻す（先に manifest の db_sha256 を照合。--force で進む）
uv run image-reviewer rebuild-metadata             # PNG と sidecar から来歴を組み直す
```

- **`gui_layout` はサーバを立ててから回す**（**実データでは回さない**。複製に `IMAGE_REVIEWER_DATA=<複製>` を付けて
  8791 などで立てる）。**検査が要る前提の行**（語・除外の理由・段 3 の保留・バックアップの失敗）は
  `uv run --no-sync python -X utf8 tools/gui_layout_seed.py --data <複製> --tags --exclusion --pending --stage3 --backup-error --backup-dir <複製の外>`
  が**複製の中に**作る（**実データは断る**）。
- **`--screen asset` は「段が 3 つ」を前提にしている。** 段 3 の印が無い置き場の枚を渡すと**必ず NG** になるので、
  `--stage3` を立てた複製で回す（**印なしの形は未対応**。P8-5 の監査 C-2。直し方は `docs/handoff.md` §3 の 0）。

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
**重複の整理**（`#/duplicates`。pHash の距離 **≤ 6 を既定**に ≤ 3 / ≤ 6 / ≤ 10 を切り替え。
**代表の推薦**と理由・「別物として確定」と**解除**・まとまりにする・削除へ回す）、
**削除と取り消し**（`#/pending-deletes`。**段 1 印 / 段 2 ゴミ箱 / 段 3 実削除**の 3 段階。**実削除は 5 分以内なら戻せる**。
一括削除は**凍結 → 実行**。**誰が消したか**を残し、**エージェントも消せるが 1 回 200 枚まで**）、
**バックアップと復元**（`#/settings` と上部バーの 1 行。日次スナップショット・7 世代・
`backup` / `restore` / `rebuild-metadata`）、
**参照切れの再リンク**（**口だけ**。`POST /api/locations/relink` は**人だけ**で、
**中身の `sha256` が一致したときだけ繋ぐ**。`GET /api/locations/missing` で一覧が引ける）**まで**。

- **バックアップは `<data>` の外（既定 `%USERPROFILE%\image-reviewer-backups`）に日次で取る。**
- **この環境では置き場を `C:\work\image-reviwer\.backup\daily\` に設定しています**（2026-10-18・利用者の決定）。既定の `%USERPROFILE%\image-reviewer-backups` は**アプリのプロセスから作れなかった**（`WinError 5`。同じ持ち主のシェルからは作れた＝原因は未特定）。`#/settings` の「置き場を変える」で戻せます。**同じドライブなので、ドライブが壊れた場合は両方失います**
  `<data>` ごと消しても、そこから戻せる（`image-reviewer restore <dir>`。`<data>` の中は置き場にできない）。
  取れなかったときは**上部バーと `#/settings` に失敗の全文**が出る（黙って失敗しない）。
- **未実装**: **P9（仕上げ。未計測の性能の実測と exe 化の判断）**・**トレイ（タスクトレイ常駐。
  常駐の実装がリポジトリに無い）**・**P2（カタログ。仮想フォルダ・スマートフォルダ・
  ドラッグ&ドロップ / クリップボード / URL の取込）**・**P3 の残り（`userdata` への設置・
  タグの統合と改名・本格的な検索・グラフの ComfyUI への設置）**・**プリセットの画面**・
  **参照切れの再リンクの画面（口だけは P8-6 で作った。`POST /api/locations/relink`・
  `GET /api/locations/missing`。`docs/p8-6-relink.md`）**・
  **`--include-library` の所要時間（未計測。実データなら 292 MB）**。
- 記録は [`docs/prototype-notes.md`](docs/prototype-notes.md)。実データで確かめた結果もそこにある。

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
| [`docs/p7-decision.md`](docs/p7-decision.md) | **P7（条件の記録。R12）を作って消した記録**（2026-10-17、利用者の判断。何を作ったか・なぜ消したか・消した物・控え・戻し方） | §16.5 |
| [`docs/p7-design.md`](docs/p7-design.md) | **廃止**。P7（条件の記録。R12）の設計（段の分け方・拘束力のある差分・合格の線 10 本・P3 との依存の扱い） | §16.5 |
| [`docs/p7-review-brief.md`](docs/p7-review-brief.md) | P7 の点検の指示書 | — |
| [`docs/p7-review-report.md`](docs/p7-review-report.md) | P7 の設計の点検報告（**判定: 直してから実装**。A 3 / B 6 / C 9 / D 12 / E 11 / F / G 7） | — |
| [`docs/p7-review-triage.md`](docs/p7-review-triage.md) | P7 の指摘の仕分け（**すべて採用**。利用者に新しく聞くことは無い） | — |
| [`docs/p7-0-implementation.md`](docs/p7-0-implementation.md) | **P7-0 の実装の記録**（v6 の 6 表・`recipe-manifest` の契約・`review.json` を変えないことの固定） | — |
| [`docs/p8-design.md`](docs/p8-design.md) | **P8（重複・削除・バックアップ）の設計**（**§0 が拘束力のある差分**・合格の線 13 本・v6 の表・口・画面・契約・性能・何を壊すと落ちるか 92 行・工程） | §12 |
| [`docs/p8-review-brief.md`](docs/p8-review-brief.md) | P8 の点検の指示書 | — |
| [`docs/p8-review-report.md`](docs/p8-review-report.md) | P8 の設計の点検報告（**実測で裏を取った 15 問**。上書き・帯・壊れた DB の形） | — |
| [`docs/p8-review-triage.md`](docs/p8-review-triage.md) | P8 の指摘の仕分け（**全部採用**。実データの数え直しつき） | — |
| [`docs/p8-0-implementation.md`](docs/p8-0-implementation.md) | **P8-0 の実装の記録**（v6 の表と `backup-manifest` の契約。機能は足さない） | — |
| [`docs/p8-1-implementation.md`](docs/p8-1-implementation.md) | **P8-1 の実装の記録**（pHash の背景ジョブ・帯・完全重複と準重複・代表の推薦・除外と解除） | — |
| [`docs/p8-2-implementation.md`](docs/p8-2-implementation.md) · [`docs/p8-3-implementation.md`](docs/p8-3-implementation.md) · [`docs/p8-4-implementation.md`](docs/p8-4-implementation.md) · [`docs/p8-5-implementation.md`](docs/p8-5-implementation.md) | **P8-2〜P8-5 の実装の記録**（削除の 3 段階と凍結 / 重複と削除の画面 / バックアップと復元 / 設定と文言の仕上げ） | — |
| [`docs/p8-6-relink.md`](docs/p8-6-relink.md) | **P8-6（参照切れの再リンク）の実装の記録**（`POST /api/locations/relink` と `GET /api/locations/missing`・`location_history` の 3 列・`create_app()` の硬化・**事故 3 件目**・設計の穴 6 件・申し送り） | — |
| [`docs/p8-audit-brief-p8-0.md`](docs/p8-audit-brief-p8-0.md)（1・2・4 も同形） | P8 の監査の指示書 | — |
| [`docs/p8-0-audit-report.md`](docs/p8-0-audit-report.md) · [`docs/p8-1-audit-report.md`](docs/p8-1-audit-report.md) · [`docs/p8-2-audit-report.md`](docs/p8-2-audit-report.md) · [`docs/p8-3-audit-report.md`](docs/p8-3-audit-report.md) · [`docs/p8-4-audit-report.md`](docs/p8-4-audit-report.md) · [`docs/p8-5-audit-report.md`](docs/p8-5-audit-report.md) | **P8 の監査報告**（**実行込み**。判定はどれも「合格（条件つき）」→ 指摘は全部反映。**P8-5 の条件 3 件だけ未反映**） | — |
| [`docs/p8-2-audit-recheck.md`](docs/p8-2-audit-recheck.md) · [`docs/p8-3-audit-recheck.md`](docs/p8-3-audit-recheck.md) · [`docs/p8-4-audit-recheck.md`](docs/p8-4-audit-recheck.md) | 監査の**再確認**（直した物が実行で直っているか。P8-3 は「合格（条件なし）」） | — |
| [`docs/p8-0-audit-triage.md`](docs/p8-0-audit-triage.md) · [`docs/p8-1-audit-triage.md`](docs/p8-1-audit-triage.md) · [`docs/p8-2-audit-triage.md`](docs/p8-2-audit-triage.md) · [`docs/p8-3-audit-triage.md`](docs/p8-3-audit-triage.md) · [`docs/p8-4-audit-triage.md`](docs/p8-4-audit-triage.md) · [`docs/p8-2-audit-recheck-triage.md`](docs/p8-2-audit-recheck-triage.md) | 監査の指摘の仕分け（1 行ずつ理由つき） | — |
| [`docs/p8-3-band-miss.md`](docs/p8-3-band-miss.md) | **帯の取りこぼしの調査**（8bit × 8 本 → **4bit × 16 本**に作り直した根拠。距離 0〜64 の総当たりとの一致） | — |
| [`schemas/backup-manifest.schema.json`](schemas/backup-manifest.schema.json) | **日次スナップショットの `manifest.json` の契約**（`restore` が復元の前に読む。`abi: 0.1`） | — |

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
| 重複を整理する | 内容ハッシュ（完全重複）と知覚ハッシュ（準重複。**距離 ≤ 6 が既定**）。**代表は推薦するだけ**で自動では外さない。「**別物として確定**」は後から解除できる |
| 本当に消す（3 段階） | **段 1 印 → 段 2 ゴミ箱 → 段 3 実削除**。実削除は**5 分間取り消せる**（元の場所が埋まっていても**上書きしない**）。一括は**凍結 → 実行**（凍結した一覧だけを消す）。**エージェントも消せる**（1 回 200 枚まで・**誰が消したか**を残す） |
| 取っておく（バックアップ） | `<data>` の外へ**日次**（変わらないファイルは `os.link` で共有＝増分・**7 世代**）。`backup` / `restore` / `rebuild-metadata`。**壊れた写しは採用しない**（写しを開いて `quick_check` → `integrity_check`） |
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

**P8 で測った物**（設計 [`docs/design.md`](docs/design.md) §12.3）: pHash の全件計算 **14.8 ms/枚**（復号込み。
1 万枚で約 2.5 分）／準重複の検出（263 枚）**帯の候補づくり 46〜52 ms**（**距離 0〜64 のすべてで総当たりと一致・
取りこぼし 0**）／段 3 の移動（`os.rename`）は**大きさに依らず 0.24 ms**（1 GB の疎ファイル）／
日次バックアップ **37 ms**（実データ 1.0 MB・5 回の中央値）／復元 **11 ms**（263 枚・判断 3 件）。
**1 万枚と `--include-library`（292 MB）は未計測。**

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
# 起動: デスクトップの `image-reviewer.lnk`（または `start-image-reviewer.cmd`）をダブルクリック
#      （UV_CACHE_DIR を設定し、3 秒後に http://127.0.0.1:8790 を開く。トレイは無い）
$env:UV_CACHE_DIR = "$PWD\.uv-cache"
uv sync
uv run image-reviewer serve --port 8790
```

## 次にすること

**P8（重複・削除・バックアップ）は完了**（2026-10-18）。P8-0（v6 の表と契約）/ P8-1（重複の検出と整理）/
P8-2（削除の 3 段階と 5 分の取り消し）/ P8-3（重複と削除の画面）/ P8-4（バックアップと復元）/
P8-5（設定と文言の仕上げ）の **6 小段**で、**合格の線に数えるのは P8-1〜P8-4**（P8-0 は機能を足さない段、
P8-5 は画面の仕上げ）。各段を Fable が**実行込みで監査**し、指摘は全部反映した
（設計 [`docs/p8-design.md`](docs/p8-design.md)、点検 [`docs/p8-review-report.md`](docs/p8-review-report.md)、
監査 [`docs/p8-0-audit-report.md`](docs/p8-0-audit-report.md) 〜 [`docs/p8-4-audit-report.md`](docs/p8-4-audit-report.md)
と再確認 `docs/p8-*-audit-recheck.md`）。**実データは v6・263 枚・判断 3 件・削除 0 件**。
**P8-5 のあとに、残っていた合格の線 9（参照切れの再リンク）を P8-6 として作った**（2026-10-18。
[`docs/p8-6-relink.md`](docs/p8-6-relink.md)。**口は 2 つで、画面は無い**）。

1. **次は P9（仕上げ）。** 未計測の性能を実測して [`docs/design.md`](docs/design.md) §12.1 の「目標」の行を
   裏づける（1024px サムネイル・一覧 API・グリッドの表示速度・**`--include-library` の所要時間**）。
   テストの締めと **exe 化の判断**も P9（同 §14）。
2. **P8 で「この段では作らない」と決めたまま残っているもの**:
   - **参照切れの再リンクの画面**（**口は P8-6 で作った**＝`POST /api/locations/relink` は**人だけ**、
     `GET /api/locations/missing` は**読むだけ**。**中身の `sha256` が一致したときだけ繋ぐ**。
     **画面は無い**ので `GET /api/locations/missing` の `hint` に従って口で使う。
     `docs/p8-6-relink.md`）。
   - **SSE（`GET /api/events`）は無い。** 画面は判断の応答（`reopened_group_ids` など）で組み直す。
   - **日次の全件書き出しと件数索引（`index.json`）は未着手。** 全件が出るのは手動の
     `POST /api/export/review.json` だけ（`GET` は返すだけで書かない）。
   - **色ヒストグラム距離は未実装**（[`docs/comparison.md`](docs/comparison.md) §4）。
   - **`asset.phash` / `dhash` に版が無い。** 縮小の仕方や入力を変えたときは `NULL` に戻す手当てが要る。
3. **利用者に確かめてほしいこと（バックアップ）**: いまの 8790 は**エージェントの sandbox の中で立っている**ため、
   既定の `%USERPROFILE%\image-reviewer-backups` に書けず、**日次が 0 個**である（`GET /api/backup` の
   `last_error` に `WinError 5` が出ている。P8-4 の再確認 B-1'）。**利用者が自分の端末（sandbox の外）で
   8790 を立て直す**と取れるようになる（`count` が 1 以上になったことを 1 度確かめる）。
