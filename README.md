# image-reviewer

ローカルの画像を登録し、カタログで見て、タグと生成の来歴を読み、まとまりごとに比べて
キープ / ボツを決めるツール。`127.0.0.1` で動く Web アプリ。

**他のツールとは連携しない**（コードもデータも語彙も合わせない）。接続先は ComfyUI だけ。

> **現在のフォルダ名は `C:\work\image-reviwer`（`reviewer` ではなく `reviwer`）。**
> `image-reviewer` に改名する方針は決まっているが、**作業中の環境からは改名できない**
> （書き込み権限がこのパスに固定されているため、`C:\work\image-reviewer` の作成が拒否される）。
> 手順は [`docs/design.md`](docs/design.md) §16.2 の 1 を参照。文書内の名前は既に `image-reviewer` にしてある。

- 状態: **P5（判断と比較）・P6（要求と注記）・P4（タグと語釈）・P8（重複・削除・バックアップ）・
  P8-6（参照切れの再リンク）・P9（仕上げ）・P10（段 1 の行を後から進める・実体が無い行を片付ける）まで動く。
  入口は 3 つ**（画面・上部バー・**タスクトレイ常駐**＝[`docs/tray.md`](docs/tray.md)。2026-10-19 に作った）。
- **`docs/design.md` §12.1 の性能の目標は全部実測で埋めた**（未計測 0）。届かなかったのは一覧 API の
  1 行だけで、理由と必要な条件は [`docs/design.md`](docs/design.md) §12.1 と
  [`docs/p9-implementation.md`](docs/p9-implementation.md) にある。
- **テスト 565 件**（`uv run --no-sync pytest -q` を自分で回して実測。**565 passed・0 failed**、39.6 秒。
  **トレイの契約 11 件**が入った数）。
  **並行して誰かが実データを `mode=ro` で読んでいると `test_data_dir_guard.py` の 1 件が落ちうる**
  （署名に使う `db.sqlite3-shm` の `mtime_ns` が動くため。**中身は変わっていない**。`docs/handoff.md` §6）。
- **`gui_smoke` 406 検査**（ok / NG 0。**自分で回して実測**）。
- **`gui_layout` 10 画面 × 4 幅**（`VIEWPORTS` は 1400・1024・1200・1920。＋`pending --ids` の 11 本目）を
  **複製で回して実測**（2026-10-19）。**`--screen tags` は語が 0 件だと必ず NG** なので
  `gui_layout_seed.py --tags` を当てた複製で回す。
  **2026-10-19 の実測（トレイの段）**: **9 本は 4 幅とも ok**（36 検査）。**`--screen pending` と
  `--screen pending --ids` の 2 本だけが 4 幅とも NG**（**理由はどちらも同じ 1 つ**）。
  `tools/gui_layout.mjs:1389` の「**まとめてのチェック**」は「全部選ぶ」で**一覧の全部の行**が
  選ばれることを期待するが、`apps/gui/pending.js:387` の `canPick()` は**段 1 と `closeable` の行だけ**を
  選べる形にしてある（P10。**段 3 の窓の行は「取り消す」だけ**＝選べないのが正しい）。
  複製に段 3 の行が 1 つでも混ざると 4 幅とも落ちる（実測: `チェック=194` / `rows=195`）。
  **この 2 ファイルはトレイの段で触っていない**（`git status` で無変更）ので、**複製の形が同じなら
  前から同じ**。直すなら検査の側（`got.picks < got.rows` を `canPick` に合わせる）。
- **P8 の小段（P8-0〜P8-5）は全部通り、監査はどれも「合格（条件つき）」**（P8-3 の再確認は「合格（条件なし）」）。
  **P8-5 の条件 3 件も 2026-10-18 に直した**（[`docs/p8-5-audit-triage.md`](docs/p8-5-audit-triage.md)——
  印のボタンの二度押し・`gui_layout --screen asset` の段の期待値を API から組む形・読み取り専用の DB で
  書き込むボタンを置かない。**段 3 の許可が無い置き場の枚で 4 幅とも ok を 2026-10-19 に実測**）。
- **参照切れの再リンク（P8 の合格の線 9）は P8-6 で作った**（2026-10-18）。P8 の途中で P8-3 が「重複と削除の
  画面」の段に置き換わり、線 9 だけが残っていた。`POST /api/locations/relink`（**人だけ**）と
  `GET /api/locations/missing`（**読むだけ**）の 2 つの口で、**中身の `sha256` が一致したときだけ繋ぐ**
  （**pHash は使わない**）。**画面は無い（口だけ）**。`docs/p8-6-relink.md`。
- **条件の記録（P7。R12）は作ったが廃止した**（2026-10-17、利用者の判断。PNG を ComfyUI にドラッグすれば
  ワークフローが戻るので記録は重複で、ja2en の英訳ももう一度実行すれば取れるため。消した物と控えは
  [`docs/p7-decision.md`](docs/p7-decision.md)、記録は `docs/p7-*.md` に残す）。
- 進め方: **DeepSeek が設計書を書く → Claude Code の Fable が点検 → DeepSeek が実装 → Fable が監査**。

## 動かす（プロトタイプ）

**起動は 3 つ**（どれも `UV_CACHE_DIR` を自分で設定する。**先に `uv sync` を 1 回**）。

| 起動 | 何が起きるか |
| --- | --- |
| **デスクトップの `image-reviewer.lnk`**（中身は `start-image-reviewer.cmd`） | **トレイ（タスクトレイ常駐）**で立ち上がる。右下にアイコンが出て、ブラウザが開く |
| `image-reviewer-tray.cmd` をダブルクリック | 上と同じ（**トレイの実体**はこれ） |
| `start-image-reviewer-console.cmd` | **いままでどおりコンソール付き**。黒い窓にログが出て、窓を閉じるとサーバも止まる |

**トレイの使い方**（詳しくは [`docs/tray.md`](docs/tray.md)）: アイコンを**ダブルクリックするとブラウザが開く**。
右クリックのメニューは **「ブラウザで開く」「最近の削除を開く」「状態を見る」「再起動する」
「終了する（サーバも止める）」**。**終了すると、トレイが起動したサーバも止まる**（**既に動いていた
サーバに繋いだときは止めない**——メニューの語が「トレイを閉じる（サーバは止めない）」に変わる）。
ツールチップに状態が出る（`image-reviewer（稼働中）、要求 3、最近の削除 12`）。要求が来たときと
**バックアップに失敗したとき**はバルーンで知らせる。記録は `<リポジトリ>\.tray\tray.log`。

- **ショートカットの向き先を変える手順**（任意。**既定はもうトレイなので、そのままでよい**）:
  デスクトップの `image-reviewer.lnk` を右クリック → プロパティ → **リンク先を
  `<リポジトリ>\start-image-reviewer.cmd` にする**（古いショートカットが `uv run … serve` を
  直接呼んでいる場合だけ効く）。

```powershell
# 手で起動するとき（開発。トレイを使わない）
$env:UV_CACHE_DIR = "$PWD\.uv-cache"
uv sync
uv sync --extra tagger                      # 内蔵タガー（onnxruntime。任意。入れると `auto` が内蔵を選ぶ）
uv run image-reviewer scan --root 'C:\work\illust-authoring\.store\anima-dev'
uv run image-reviewer serve --port 8790     # → http://127.0.0.1:8790
uv run --no-sync pytest -q                  # 565 件（2026-10-19 に実測）
node tools/gui_smoke.mjs                    # 画面の組み立て（CSS を持たない軽い DOM で。406 検査）
# **トレイの検査**（別のポートと、合成した複製だけで回す。**8790 は使わない**）
powershell -NoProfile -ExecutionPolicy Bypass -File tools\tray_selftest.ps1 -Port 8795   # 55 検査
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
node tools/gui_layout.mjs --base http://127.0.0.1:8791 --screen settings   # 設定（バックアップと段 3 の許可。P8）
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
- **`--screen asset` は「段が 3 つ」を前提にしている。** 段 3 の許可が無い置き場の枚を渡すと**必ず NG** になるので、
  `--stage3` を立てた複製で回す（**許可なしの形は未対応**。P8-5 の監査 C-2。直し方は `docs/handoff.md` §3 の 0）。
- **`--screen pending --ids` には「生きている枚」を渡す。** 段 1〜3 で外した枚（`asset.deleted_at`）を渡すと、
  画面は `GET /api/assets` からその枚のパスを引けず、段 3 の 1 行が
  **「置き場を確かめられないので段 3 は出していません」**（＝正しい動作）になって、
  「段 3 の許可がありません」を見る検査が NG になる（**P9 で実際に踏んだ**）。
- **`--screen tags` は語が 0 件だと必ず NG になる**（実データの `tag` / `asset_tag` は **0 件**）。
  `gui_layout_seed.py --tags` を**複製に**当ててから回す（**P9 の監査の直しで実際に踏んだ**。
  `tag=0` の複製では 3 窓とも `rows=0 ← 語の行が出る` で落ちる）。
- **`--screen pending` は本物の走査（`POST /api/scan`）を 1 回打つ**（`REAL_SCAN_PROBE`）。
  複製の DB に、置き場にある未登録の画像が入る（**画像のファイルは動かない**。行が増えるだけ）。
  実データには向けない（**必ず複製**）。
- **CLI（`backup` / `scan` / `rebuild-metadata`）は `IMAGE_REVIEWER_DATA` が無ければ実データ `.data` を直接開く**
  （利用者の道具なので正しい入口である）。**壊す試験や計測をするときは、必ず複製を作って
  `IMAGE_REVIEWER_DATA=<複製>` を付ける**（画像を動かす試験は特に）。`serve` も同じ env で複製へ向けられる。

- **`uv sync` はサーバを止めてから打つ。** 動かしたままだと `os error 32`（使用中のファイルを置き換えられない）
  で失敗する。
- **止めた直後に `export/groups/*.json` を読むなら 1 秒待つ。** `uv run` 経由で `serve` を止めると
  `uv` が先に終わり、python（uvicorn）の `lifespan` の書き出しがその後に走る（監査 D3）。
  待ちたくないときは `uv run python -m image_reviewer.cli serve --port 8790` で上げる。

入っている物:

- **閲覧と来歴の表示**（カタログの一覧と 1 枚の詳細）。
- **判断**（キープ / ボツ。まとまりごとの決定と理由まで）。
- **比較**（並べる / 来歴の差分表 / 同期ズーム / 差分ヒートマップ / 似ている順）。
- **エージェントからの要求**（受付・一覧・断る・判断で閉じる）。
- **注記**（矩形・楕円・画像 1 枚へのメモ・座標 JSON・切り出し PNG）。
- **タグ**（内蔵タガーと ComfyUI 経由。出どころつき・手で足す / 外す・`#/tags` の一覧と検索・`#/jobs` の進行）。
- **日本語訳**（見えている語だけ訳す・人が直せる・**人が直した日本語訳は訳し直しで上書きしない**。
  画面の語は「日本語訳」。「語釈」は内部の語＝`docs/design.md` §17）。
- **重複の整理**（`#/duplicates`。pHash の距離 **≤ 6 を既定**に ≤ 3 / ≤ 6 / ≤ 10 を切り替え。
  **残す 1 枚の推薦**と理由・「別物として確定」と**解除する**・まとまりにする・削除する…）。
- **削除と取り消し**（`#/pending-deletes`。**段 1 カタログから外す / 段 2 アプリのゴミ箱 / 段 3 ファイルを消す**の 3 段階。
  **ファイルを消した後も 5 分以内なら戻せる**。一括削除は**凍結 → 実行**。**誰が消したか**を残し、
  **エージェントも消せるが 1 回 200 枚まで**）。
- **外した後の後始末（P10）**: **一度カタログから外した物を、後からアプリのゴミ箱へ移せます。実体が無い物は片付けられます**
  （`#/pending-deletes` の段 1 の行に「アプリのゴミ箱へ移す」と「ファイルが無いので片付ける」、段 2 の行にも
  「ファイルが無いので片付ける」。まとめて選べる。**1 回 200 件まで**。**片付けてもファイルは 1 つも消さない・動かさない**。
  **片付けた後は戻せない**＝`docs/deletions-advance.md`）。
- **バックアップと復元**（`#/settings` と上部バーの 1 行。日次バックアップ・7 世代・
  `backup` / `restore` / `rebuild-metadata`）。
- **タスクトレイ常駐**（`image-reviewer-tray.cmd` → `tools/tray.ps1`。**2026-10-19 に作った**。
  **新しい依存を足していない**＝Windows の PowerShell と .NET の `NotifyIcon` だけ）。
  **アイコンのダブルクリックで開く**。右クリックのメニューは「ブラウザで開く」「最近の削除を開く」
  「状態を見る」「再起動する」「終了する（サーバも止める）」。**既に動いているサーバがあれば
  二重に起動せずそれに繋ぐ**（そのときは止めない）。アイコンの形は**要求あり / 取り消せる削除あり /
  両方 / なし**の 4 通りで、**バックアップに失敗している間は枠が赤**。詳しくは
  [`docs/tray.md`](docs/tray.md)。
- **参照切れの再リンク**（**口だけ**。`POST /api/locations/relink` は**人だけ**で、
  **中身の `sha256` が一致したときだけ繋ぐ**。`GET /api/locations/missing` で一覧が引ける）。

- **バックアップは `<data>` の外（既定 `%USERPROFILE%\image-reviewer-backups`）に日次で取る。**
- **この環境では保存先を `C:\work\image-reviwer\.backup\daily\` に設定してある**（2026-10-18・利用者の決定）。
  既定の `%USERPROFILE%\image-reviewer-backups` は**アプリのプロセスから作れなかった**（`WinError 5`。
  同じ持ち主のシェルからは作れた＝原因は未特定）。`#/settings` の「保存先を変える」で戻せる。
  **同じドライブなので、ドライブが壊れた場合は両方失う。**
  `<data>` ごと消しても、そこから戻せる（`image-reviewer restore <dir>`。`<data>` の中は保存先にできない）。
  取れなかったときは**上部バーと `#/settings` に失敗の全文**が出る（黙って失敗しない）。
- **未実装**:
  - **P2（カタログ。仮想フォルダ・スマートフォルダ・ドラッグ&ドロップ / クリップボード / URL の取込）**。
  - **P3 の残り**（`userdata` への設置・タグの統合と改名・本格的な検索・グラフの ComfyUI への設置）。
  - **プリセットの画面**。
  - **参照切れの再リンクの画面**（口だけは P8-6 で作った。`POST /api/locations/relink`・
    `GET /api/locations/missing`。`docs/p8-6-relink.md`）。
  - **一覧 API のキーセット改ページ**（P9 の実測で p95 244.7 ms。目標 20 ms に届いていない。
    1 万枚が現実になるまで困らないので、入れる段を別に立てる。`docs/design.md` §12.1）。
  - **一覧の仮想グリッドとページ送り**（いまは `limit=2000` で 1 回引いて全部描く。1 万枚では
    2000 枚で切れるので「先頭 2000 枚を表示」と出している）。
  - **段 1 の行から段 3 へ直行する道**（**P10 では作らないと決めた**。段 3 は置き場ごとの許可
    （`root.allow_stage3`。Q8 の利用者の意思表示）と凍結が要る既存の道のまま。`docs/design.md` §16.7）。
  - **実データの `deletion_log.closed_at` / `close_reason`**（**P10 の列は実データにまだ無い**。
    `TOP_UP_COLUMNS` なので、**利用者がアプリを立ち上げ直した時点**で `pre-topup-<日時>/` の控えが付いてから
    足される。**それまでは「ファイルが無いので片付ける」も「アプリのゴミ箱へ移す」も押せない**——
    新しい口は**再起動後**に使える）。
- **exe 化（PyInstaller）は「今は作らない」**（P9 の推奨）。**作れることは実測した**
  （PyInstaller 6.22.3 が Python 3.14 で動き、`--onedir` が 23.7 秒で 131.9 MB。
  起動は 0.53 秒で、いまの `uv` 経由（1.05 秒）より速い）が、**`apps/gui` の解決が 1 か所足りず
  画面が出ない**（`gui_present: false`）。**配布しないなら要らない**。必要な作業の一覧は
  [`docs/p9-implementation.md`](docs/p9-implementation.md) §6。
- 記録は [`docs/prototype-notes.md`](docs/prototype-notes.md)。実データで確かめた結果もそこにある。

## 文書

| ファイル | 中身 | 点検の観点 |
| --- | --- | --- |
| [`docs/design.md`](docs/design.md) | 全体・バックエンド設計（要件対応表・アーキテクチャ・データモデル・API・性能・工程・リスク・用語） | §19 |
| [`docs/frontend-design.md`](docs/frontend-design.md) | 画面の設計（デザインプラン・色・書体・配置・部品・文言・アクセシビリティ） | §12 |
| [`docs/comparison.md`](docs/comparison.md) | 比較の設計（見た目・来歴・機械の指標、位置合わせ） | — |
| [`docs/workflow-reproduction.md`](docs/workflow-reproduction.md) | 生成の条件の記録と再利用（**実行はしない**）、印による結果の紐付け | — |
| [`docs/duplicates-deletion-backup.md`](docs/duplicates-deletion-backup.md) | 重複・削除（**5 分の取り消し**）・バックアップ | — |
| [`docs/tray.md`](docs/tray.md) | **タスクトレイ常駐**（作った物・使い方・自動で確かめた結果・手で確かめた結果・設計の穴） | — |
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
| [`docs/p8-2-implementation.md`](docs/p8-2-implementation.md)、[`docs/p8-3-implementation.md`](docs/p8-3-implementation.md)、[`docs/p8-4-implementation.md`](docs/p8-4-implementation.md)、[`docs/p8-5-implementation.md`](docs/p8-5-implementation.md) | **P8-2〜P8-5 の実装の記録**（削除の 3 段階と凍結 / 重複と削除の画面 / バックアップと復元 / 設定と文言の仕上げ） | — |
| [`docs/p8-6-relink.md`](docs/p8-6-relink.md) | **P8-6（参照切れの再リンク）の実装の記録**（`POST /api/locations/relink` と `GET /api/locations/missing`・`location_history` の 3 列・`create_app()` の硬化・**事故 3 件目**・設計の穴 6 件・申し送り） | — |
| [`docs/p8-audit-brief-p8-0.md`](docs/p8-audit-brief-p8-0.md)（1・2・4 も同形） | P8 の監査の指示書 | — |
| [`docs/p8-0-audit-report.md`](docs/p8-0-audit-report.md)、[`docs/p8-1-audit-report.md`](docs/p8-1-audit-report.md)、[`docs/p8-2-audit-report.md`](docs/p8-2-audit-report.md)、[`docs/p8-3-audit-report.md`](docs/p8-3-audit-report.md)、[`docs/p8-4-audit-report.md`](docs/p8-4-audit-report.md)、[`docs/p8-5-audit-report.md`](docs/p8-5-audit-report.md) | **P8 の監査報告**（**実行込み**。判定はどれも「合格（条件つき）」→ 指摘は全部反映済み。**P8-5 の条件 3 件も 2026-10-18 に反映**） | — |
| [`docs/p8-2-audit-recheck.md`](docs/p8-2-audit-recheck.md)、[`docs/p8-3-audit-recheck.md`](docs/p8-3-audit-recheck.md)、[`docs/p8-4-audit-recheck.md`](docs/p8-4-audit-recheck.md) | 監査の**再確認**（直した物が実行で直っているか。P8-3 は「合格（条件なし）」） | — |
| [`docs/p8-0-audit-triage.md`](docs/p8-0-audit-triage.md)、[`docs/p8-1-audit-triage.md`](docs/p8-1-audit-triage.md)、[`docs/p8-2-audit-triage.md`](docs/p8-2-audit-triage.md)、[`docs/p8-3-audit-triage.md`](docs/p8-3-audit-triage.md)、[`docs/p8-4-audit-triage.md`](docs/p8-4-audit-triage.md)、[`docs/p8-2-audit-recheck-triage.md`](docs/p8-2-audit-recheck-triage.md) | 監査の指摘の仕分け（1 行ずつ理由つき） | — |
| [`docs/p8-3-band-miss.md`](docs/p8-3-band-miss.md) | **帯の取りこぼしの調査**（8bit × 8 本 → **4bit × 16 本**に作り直した根拠。距離 0〜64 の総当たりとの一致） | — |
| [`docs/p9-implementation.md`](docs/p9-implementation.md)、[`docs/p9-audit-report.md`](docs/p9-audit-report.md)、[`docs/p9-audit-triage.md`](docs/p9-audit-triage.md) | **P9 の記録**（§12.1 の実測・exe 化の判断）と、その**監査報告**（C-1〜C-3・D 10 件・G 6 件）と**仕分け**（指摘ごとに 1 行。C-1 は新しい読み取り専用の接続で `quick_check`） | — |
| [`docs/wording-audit-report.md`](docs/wording-audit-report.md)、[`docs/wording-fix.md`](docs/wording-fix.md) | **ワーディング監査**（利用者に見える日本語 約 1,200 行を 1 行ずつ見た報告。判定は「自然」で、原因は中国語ではなく**癖 3 つ**）と、その**修正の記録**（規則 3 つ・直した 141 件・食い違い 24 行の裁定・用語の対応表・残した物） | — |
| [`docs/deletions-advance.md`](docs/deletions-advance.md) | **P10 の実装の記録**（段 1 の行を後からアプリのゴミ箱へ移す・実体が無い行を片付ける。口 4 つ・決めた 8 点・**設計の穴 4 件**・複製で通した線 14 件・壊し試験 13 件）＋**§7 に監査の指摘で直した所** | — |
| [`docs/p10-audit-report.md`](docs/p10-audit-report.md)、[`docs/p10-audit-triage.md`](docs/p10-audit-triage.md) | **P10 の監査報告**（**実行込み**。判定は**「直してから次へ」**。**A-1 は利用者のファイルを壊し得る穴**——古い `asset_id` の 6 行の advance が**別の画像をゴミ箱へ移していた**。A-2・A-3・B 2 件・C 3 件・D 12 件・**壊し試験 32 通りで 28 が落ち、落ちない 4 のうち 3 がテストの穴**）と、その**仕分け**（**指摘ごとに 1 行**。推奨はすべて採用・A-1〜A-3 は複製で再現して直した） | §6.1, §16.7 |
| [`docs/duplicates-keep-button.md`](docs/duplicates-keep-button.md) | **重複の整理の「残す 1 枚以外を削除する…」**（利用者の要望の追い足し。ラジオに「残す」の語・群ごとのボタン・**渡す直前に `keep` を除く**二重の守り・本物の Chrome 25 検査） | — |
| [`docs/japanese-ui-audit-report.md`](docs/japanese-ui-audit-report.md)、[`docs/japanese-ui-fix.md`](docs/japanese-ui-fix.md) | **日本語 UI の監査**（「日本語のシステムとして自然か」の軸。判定は**「一部に不揃い」**で、規約 A〜F・違反 A16/B11/C30/D17/E11/F9・用語 27 語の判定・質問 G-1〜G-10）と、その**修正の記録**（**§6.1 を規約 A〜F＝通し番号 1〜6 に振り直した**・分類ごとの件数・直す前→後・残した物と理由・1024×700 の検査を足した話） | §6.1, §17 |
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
| 本当に消す（3 段階） | **段 1 カタログから外す → 段 2 ゴミ箱 → 段 3 実体を消す**。実体を消した後も**5 分間取り消せる**（元の場所が埋まっていても**上書きしない**）。一括は**凍結 → 実行**（凍結した一覧だけを消す）。**エージェントも消せる**（1 回 200 枚まで・**誰が消したか**を残す） |
| 取っておく（バックアップ） | `<data>` の外へ**日次**（変わらないファイルは `os.link` で共有＝増分・**7 世代**）。`backup` / `restore` / `rebuild-metadata`。**壊れた写しは採用しない**（写しを開いて `quick_check` → `integrity_check`） |
| 速く動く | 実測に基づく目標値（下記） |

## 実機で確かめたこと

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

→ メタデータ抽出は性能上の問題にならない。**本当に時間がかかるのはハッシュとサムネイル**で、
どちらも目標に収まる。

**P8 で測った物**（設計 [`docs/design.md`](docs/design.md) §12.3）: pHash の全件計算 **14.8 ms/枚**（復号込み。
1 万枚で約 2.5 分）／準重複の検出（263 枚）**帯の候補づくり 46〜52 ms**（**距離 0〜64 のすべてで総当たりと一致・
取りこぼし 0**）／段 3 の移動（`os.rename`）は**大きさに依らず 0.24 ms**（1 GB の疎ファイル）／
日次バックアップ **37 ms**（実データ 1.0 MB・5 回の中央値）／復元 **11 ms**（263 枚・判断 3 件）。
**1 万枚と `--include-library`（292 MB）は未計測。**

## 技術

**いま入っているもの**: Python 3.12 以上（実測 3.14.7）/ uv / FastAPI / uvicorn / SQLite(WAL) / Pillow / numpy
（依存は `fastapi` / `uvicorn` / `pillow` / `numpy`。テストの `httpx` は dev だけ）。
前面は**素の JavaScript**（`apps/gui/*.js`。フレームワークなし）。
既定ポート **8790**。アプリの置き場は `<リポジトリ>/.data`。

**目標（未着手）**: `onnxruntime-gpu`（内蔵タガー）、前面の **TypeScript + Vite**（開発サーバは **5273**）。
（**タスクトレイ常駐は 2026-10-19 に作った**＝[`docs/tray.md`](docs/tray.md)。**`pystray` は使っていない**
——PowerShell と .NET の `NotifyIcon` で足りた。）

## 開発メモ

この環境のサンドボックス下では uv の既定キャッシュに書けないため、`UV_CACHE_DIR` をリポジトリ内へ向ける。

```powershell
# 起動: デスクトップの `image-reviewer.lnk`（または `start-image-reviewer.cmd`）をダブルクリック
#      （**トレイ（タスクトレイ常駐）**で立ち上がり、ブラウザが開く。止めるときはトレイの「終了する」）
$env:UV_CACHE_DIR = "$PWD\.uv-cache"
uv sync
uv run image-reviewer serve --port 8790
```

## 次にすること

**P9（仕上げ）は完了**（2026-10-18。[`docs/p9-implementation.md`](docs/p9-implementation.md)）。
**P10（段 1 の行を後から進める・実体が無い行を片付ける）も完了**（2026-10-19。
[`docs/deletions-advance.md`](docs/deletions-advance.md)）。**利用者の要望**（一度カタログから外した物を
ゴミ箱へ／実体が無い物を片付ける）で、**段 1 が行き止まりだった**のを塞いだ。
**P10 の監査も受けて、指摘は全部直した**（2026-10-19。[`docs/p10-audit-report.md`](docs/p10-audit-report.md)
＝判定**「直してから次へ」**、[`docs/p10-audit-triage.md`](docs/p10-audit-triage.md)）——**A-1 は利用者の
ファイルを壊し得る穴**だった（**古い `asset_id` の 6 行**に「アプリのゴミ箱へ移す」を打つと、**いま同じ
場所に登録されている別の画像 Y のファイルを移して、Y を一覧から消していた**。台帳の `size` と
**いま登録している枚**を照合して **409 `different_file`** で断る形にした）。**A-2**（戻しても Y の
`deleted_at` が立ったまま＝実体があるのに永久に消える）と **A-3**（片付けた行はファイルが戻っても
二度とカタログに戻せない）も直した（**走査が印を引き直す**・実体が在れば `undo` が**開き直す**）。
**実データは 461 行（生きた 267 枚）・段 1 の生きた行 194・うち実体が在るのは 7 行**（187 行が実体なし、
**7 行のうち 6 行は「別の画像が在る」形**）で、**利用者がアプリを立ち上げ直して「まとめて片付ける」を
押す番**（`pre-topup-<日時>/` の控えが付いてから列が足される。**押すと 193 件が閉じ、1 件だけ断られる**
——その 1 件は「アプリのゴミ箱へ移す」で進める。**別の画像 6 枚は 1 枚も動かない**）。
**P9 の監査（[`docs/p9-audit-report.md`](docs/p9-audit-report.md)。判定「合格（条件つき）」）の
指摘も全部直した**（2026-10-19。[`docs/p9-audit-triage.md`](docs/p9-audit-triage.md)）——
**C-1**（走ったまま壊れた DB の入口が、**書き込んだ接続のページキャッシュ**越しに見ていて
小さい DB では見落としていた → **新しい読み取り専用の接続**で `quick_check`）・
**C-2**（画面の「枚」が 262 と 455 で食い違っていた → **生きた枚**に統一）・
**C-3**（「同時 8 本」は実装に無い見込み・`state=kept` は 0 件への絞り込みだった）。
**`docs/design.md` §12.1 の「目標」の行は全部実測で埋まった**（未計測 0）。
新しく作った道具は `tools/make_synthetic_db.py`（1 万枚の合成 DB）と `tools/probe_p9.py`（サーバ内の計測）。
**この段で見つけて直した物**（P8-6 の申し送りと、計測の途中で見つかった物）:

1. `PRAGMA temp_store = MEMORY` が実装に無く、**1 万枚の一覧が 500 になっていた**ので入れた。
2. `PRAGMA cache_size = -65536` は**入れなかった**（**実利が無い**。監査 C-1 で理由を書き直した——
   「安全のため」では**なかった**。既定でも小さい DB の壊れは見落としていた）。
3. `sqlite_error_handler` が**壊れていない DB に「バックアップから戻してください」と言っていた**（語彙を分けた）。
4. 一覧が `limit=2000` で切れるのに**上部が全枚数と言っていた**ので「先頭 2000 枚を表示」と出した。

**届かなかったのは一覧 API の 1 行だけ**（p95 244.7 ms / 目標 20 ms。**目標は下げていない**）。

1. **次にやるなら**（**どれも利用者の判断**）:
   - **「ファイルが無いので片付ける」をトレイからも使えるようにするか**（**トレイそのものは
     2026-10-19 に作った**＝[`docs/tray.md`](docs/tray.md)。いまトレイにあるのは「ブラウザで開く」
     「最近の削除を開く」「状態を見る」「再起動する」「終了する」の 5 つで、片付けは**画面だけ**）。
   - **参照切れの再リンクの画面**（**口は P8-6 で作った**＝`POST /api/locations/relink` は**人だけ**、
     `GET /api/locations/missing` は**読むだけ**。**中身の `sha256` が一致したときだけ繋ぐ**。
     **画面は無い**ので `GET /api/locations/missing` の `hint` に従って口で使う。
     `docs/p8-6-relink.md`）。
   - **一覧 API のキーセット改ページ**（§12.1 の「届かなかった 1 行」。`total` の意味と絞り込みが
     変わるので、テストと画面の前提を一緒に直す段として立てる）。
   - **`--include-library` を日次に載せるか**（日次が 201 ms → 2.4 秒になる。1 万枚なら 1.4 分）。
   - **exe 化**（今は作らない、が推奨。作るなら `apps/gui` の解決＋静的ファイルの同梱が要る）。
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
- **バックアップは取れている（2026-10-19 に確かめた）。** 置き場は `.backup\daily\` で、そこに **3 世代**ある
  （`20261018` / `20261018-171143` / **`20261019`**。最新は 2026-10-19 00:00:15 に取れている）。
  `GET /api/backup` の `count` が 1 以上になることを確かめてある。
  **以前ここに書いていた「日次が 0 個である（`WinError 5`）」は古い事実**（P8-4 の再確認 B-1' の時点の話）。
  利用者が自分の端末から 8790 を立て直した後、**日次が取れていることを確かめた**。
