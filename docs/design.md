# image-reviewer 設計（全体・バックエンド）

ローカルの画像を「登録 → カタログで見る → タグと生成の来歴を見る → まとまりごとに比べて**キープ / ボツ**を決める」ための
単独ツール。127.0.0.1 で動く Web アプリ。

- 版: 設計 0.1（実装前）
- **他のツールとは連携しない。** 過去に読んだ既存実装から学んだ点は §18 に分離した（コードもデータも語彙も合わせない）。
- 画面の設計は [`frontend-design.md`](frontend-design.md) にある（この文書は全体とバックエンドを兼ねる）。
- 設計の根拠になる実機の事実は [`metadata-findings.md`](metadata-findings.md)、
  ComfyUI の詳細は [`comfyui-reproduction-findings.md`](comfyui-reproduction-findings.md) にある。
  **確認済みと未確認を区別している。**
- 専門の設計: [`comparison.md`](comparison.md)（比較）、[`workflow-reproduction.md`](workflow-reproduction.md)（再現）、
  [`duplicates-deletion-backup.md`](duplicates-deletion-backup.md)（重複・削除・バックアップ）
- この文書は「決めたこと」と「決めていないこと」を分けて書く。決めていないことは §16 にまとめた。
- **レビューの対象**: Claude Code の Fable による点検を受け、その後 DeepSeek が実装する。
  点検してほしい点は §19 に列挙した。

---

## 1. 要件と、この設計での答え

| # | 要件 | この設計での答え | 節 |
| --- | --- | --- | --- |
| R1 | 単一の画像を登録・表示できる | `asset`（内容）＋ `asset_location`（場所）として登録。拡大ビュー | §5, §11 |
| R1b | 画像を取り込める | フォルダ走査 / ドラッグ&ドロップ / クリップボード / 画像 URL を貼る。**書き出し・改名・メタデータ埋め込みは対象外** | §5.1, §6.1 |
| R2 | カタログで見れる。独自のフォルダ分け構造 | 仮想フォルダ（1 枚が複数所属可）＋ スマートフォルダ（条件で自動）。実ファイルは動かさない | §10 |
| R3 | Danbooru タグを表示できる | `tag` / `asset_tag`。PNG の語と WD14 の語を**出所付き**で保持。**日本語の語釈**を別に持つ（§8.4） | §8, §5 |
| R4a | 生成のワークフローへのリンクを表示 | グラフを書き出して ComfyUI へドラッグ&ドロップ。**API 形式のままでも読める**（実機で確認） | §7.4 |
| R4b | 生成に用いた日本語と英訳を表示 | 日本語は PNG から常に取得。英訳は**出所を分けて**保持（生成時に捕獲 / 訳し直し / 手入力） | §7.2, §7.3 |
| R5a | **キープ / ボツ**を設定 | `decision` 台帳（追記のみ）＋ 現在値のマテリアライズ | §9 |
| R5b | 理由を設定 | `reason_code` マスタ（利用者が編集）＋ 自由メモ | §9.2 |
| R5c | 他ツールからレビュー結果を参照 | REST 読み取り API ＋ 版付き `review-export.json`（[`../schemas/review-export.schema.json`](../schemas/review-export.schema.json)） | §6.2, §9.4 |
| R6 | 複数画像のまとまりをレビュー単位に。1 枚選ぶ / 全部ボツ | `review_group` ＋ まとまりの判定。選ばれなかった枚にも理由が付く | §9.3 |
| R7 | Danbooru Tagger で未タグ画像にタグ付け | 内蔵 onnxruntime-gpu を既定。ComfyUI の `IllustTagger` も選択可 | §8 |
| R8 | 高速に動作 | サムネイル先読み、キーセット改ページ、仮想グリッド、PNG 部分読み、索引 | §12 |
| R9 | exe かローカルホストの Web アプリ | 127.0.0.1 の Web アプリ（同一オリジン配信）。ショートカットから起動し、タスクトレイに常駐 | §4 |
| **R10** | **エージェントがレビューを要求できる** | `review_request`。HTTP API で受け、投げてすぐ返る。人が判断すると閉じる。要求の一覧画面でさばく | §9.6 |
| **R11** | **画像の上に印を付けられる** | `annotation`。矩形と楕円。座標は 0〜1 の割合。座標 JSON と切り出し画像を書き出せる | §9.7 |
| **R12** | **うまくいった条件を残して再利用する** | **見送り（廃止。2026-10-17、利用者の判断）**。P7 で作ったが削除した。PNG を ComfyUI にドラッグすればワークフローが戻るので記録は重複、ja2en の英訳ももう一度実行すれば取れる | [`p7-decision.md`](p7-decision.md) |
| **R13** | **重複を整理し、本当に削除できる** | 内容ハッシュと知覚ハッシュで検出。削除は 3 段階、実削除は**5 分間取り消せる** | [`duplicates-deletion-backup.md`](duplicates-deletion-backup.md) |

補足: 要件の「画像を保存」は、**登録（参照を既定）＋ 必要なら取込（コピー）＋ 他所からの取り込み**とする。
書き出し・改名・メタデータの埋め込みは**今回の対象外**（利用者の回答）。

---

## 2. 設計を縛る前提（実機で判明した制約）

詳細と根拠は [`metadata-findings.md`](metadata-findings.md) と
[`comfyui-reproduction-findings.md`](comfyui-reproduction-findings.md)。設計に効く 7 点を挙げる。

1. **英訳結果は PNG に残らない。** `TextGenerate` の出力は実行時値。`/history` はメモリのみで、
   既存画像の英訳は復元不能。→ 生成時に捕まえる仕組み（監視）と、後からの再翻訳を**別物として**扱う。
2. **URL 一発でワークフローを開く手段は無い。** `?workflow=` は未実装、`?template=` は同梱テンプレート専用。
   → 書き出し＋D&D を主経路にする。
3. **API 形式 JSON は ComfyUI が自分で読める**（`loadApiJson` が API → UI 変換を実装）。
   → 自前で UI 形式へ変換する必要はない。** `workflow` チャンクは UI 実行の画像にしか無い**（実測 17%）ので、
   位置まで復元できるかは画像次第。
4. **英訳の再現は「テキストを固定する」のが唯一確実。** `TextGenerate` は seed で固定されているが、
   `mtp` の値で同じ seed でも出力が変わり、dtype は device 依存。→ 捕獲した英文を直接使う（L1）。
5. **モデルのハッシュは ComfyUI が持たない。** `(名前, size, mtime)` でピン留めする。
   同じ名前で中身が変わったモデルは区別できない（近似の理由として出す）。
6. **IllustTagger はスコア付きで返る**（`ui.scores` に `[[tag, score], ...]`）。→ 閾値は呼ぶ側で決められる。
7. **他のツールとは連携しない**と決めた（利用者の回答）。したがって接続先は **ComfyUI だけ**。
   別オリジンのブラウザアプリを作らないのは、**CORS を設定せずに済ませるため**でもある（同一オリジン配信。§3）。

---

## 3. 全体アーキテクチャ

```
                    ┌─────────────────────────────────────────────┐
 ブラウザ ──HTTP──▶ │  image-reviewer サーバ（Python 3.12 / FastAPI）│
 (同一オリジン)      │                                             │
                    │  API 層  ─ 検索・登録・判断・要求・書き出し    │
                    │     │                                        │
                    │  サービス層                                   │
                    │   ・カタログ（仮想フォルダ / スマート）        │
                    │   ・メタデータ（PNG 解析 / 来歴）              │
                    │   ・タグ（内蔵タガー / 日本語の語釈）          │
                    │   ・レビュー（台帳 / まとまり / 要求 / 注記）  │
                    │   ・ジョブ（走査 / ハッシュ / サムネ / 監視）  │
                    │     │                                        │
                    │  SQLite(WAL)  ＋  ファイル置き場              │
                    └───────┬─────────────────────────────────────┘
                            │ 読み書き（HTTP）
                            ▼
                    ComfyUI (127.0.0.1:8188)
                     ・/api/jobs（生成の瞬間の値を捕まえる＝英訳）
                     ・/api/userdata（ワークフローの取得と設置）
                     ・/object_info /experiment/models（あるか確かめる）
                     ・/prompt（タガーと訳し直しの実行）
```

- **単一プロセス**。SQLite は 1 書き手なので、重い処理（サムネイル生成・ハッシュ・タグ付け）は
  プロセス内のワーカースレッドに逃がし、HTTP を止めない。uvicorn のワーカーは 1。
- **同一オリジン配信**。フロントのビルド成果物をサーバが `/` に配信し、API は `/api`。
  これで CORS の設定が要らない（別オリジンのアプリを作らない理由）。
- **自分から出るのは、ComfyUI と「利用者が明示した URL の取得」だけ。**
  画像フォルダは読むが、他のツールの API や内部形式には依存しない。
  （点検 A1: 当初「接続先は ComfyUI だけ」と書いていたが、R1b の URL 取り込みと矛盾していた。
  他のツールを呼ばないことと、利用者が貼った URL を取りに行くことは別である。）
- **エージェントは API の客**として来る（`POST /api/review-requests`）。エージェント用の別口は作らない。
- **画像の生成は実行しない。** `/prompt` はタグ付けと訳し直しにだけ使う（正確な区別は §6.3.2）。
- **トレイ常駐**。`tools/tray.ps1`（PowerShell + .NET の `NotifyIcon`）がサーバの起動・停止・ブラウザを開く・要求と取り消せる削除があるとアイコンを変える、を持つ（§4.1）。

---

## 4. 技術選定

| 層 | 選定 | 理由 |
| --- | --- | --- |
| 言語 | Python 3.12 | 内蔵タガーが `onnxruntime-gpu` を必要とする。Pillow でサムネイル。環境に Python と uv がある |
| パッケージ管理 | uv（`pyproject.toml` + `uv.lock`） | 速く、`uv.lock` で固定できる。**注意: DSH の制限下では `UV_CACHE_DIR` をワークスペース内へ向ける必要がある**（既定の `%LOCALAPPDATA%\uv\cache` は書けない） |
| Web | FastAPI + uvicorn | OpenAPI が自動で出る。1 プロセスで画面も配信できる |
| DB | SQLite（stdlib `sqlite3`、WAL）。ORM なし | 数千〜1 万枚なら十分。手書き SQL でクエリを制御する。依存を増やさない |
| トレイ | **追加の依存なし**（Windows の PowerShell + .NET の `NotifyIcon`） | アイコンを出すだけ。要求があると形を変える（§4.1。**当初の `pystray` 案は採らなかった**＝2026-10-19） |
| 起動 | `.cmd` のショートカット | 利用者の回答（ショートカットをダブルクリック）。§4.1 |
| 画像 | Pillow（PNG と JPEG は標準で扱える） | 既に導入済み。HEIC / AVIF は今回の対象外 |
| タガー | `onnxruntime-gpu` + `numpy` | ComfyUI を止めずに動かせる。CPU へ落ちる経路も持つ |
| HTTP クライアント | `httpx` | ComfyUI の呼び出しと、利用者が貼った URL の取得（他のツールは呼ばない） |
| 前面 | TypeScript + Vite、**フレームワークなし**（素の DOM） | 仮想グリッドは自前で持つ。バンドルを軽く保ち、起動を速くする。設計は [`frontend-design.md`](frontend-design.md) |
| URL からの取り込み | `httpx`（標準の機能で足りる） | 画像 URL を貼って落とすだけ。ページの解析はしない |
| 対象外（当面） | React / Electron / Tauri / HEIC / AVI | 素の DOM で足りる。exe 化は必要になった時点で判断（§16） |

### 4.1 起動とトレイ（利用者の回答: ショートカットをダブルクリック、トレイに出す）

```text
start-image-reviewer.cmd             # デスクトップのショートカットの的（既定はトレイ）
  └ image-reviewer-tray.cmd
       └ powershell -ExecutionPolicy Bypass -File tools\tray.ps1 -Port 8790
            ├ GET /api/health で既に動いているサーバを探す（自分ならそれに繋ぐ）
            ├ 誰も居なければ .venv\Scripts\python.exe -m image_reviewer.cli serve --port 8790
            │    （**子プロセス**）を起動して、health が返るまで待つ
            ├ トレイ（NotifyIcon）を**メインスレッド**で動かす（5 秒ごとに状態を見る）
            └ 既定のブラウザで http://127.0.0.1:8790 を開く
```

**起動方式（2026-10-19 に作った。実装は [`tray.md`](tray.md)）:**

| 項目 | 決め |
| --- | --- |
| 常駐の実装 | **`tools/tray.ps1`**（Windows に元からある **PowerShell と .NET の `System.Windows.Forms.NotifyIcon`**）。**新しい依存を足さない**（`pystray` も PyInstaller も要らない） |
| ショートカットの実体 | **`.cmd`**（`image-reviewer-tray.cmd`）。`-WindowStyle Hidden` で PowerShell の窓を隠す（**一瞬だけ窓が出ることがある**＝既知の穴。`tray.md`） |
| サーバの持ち方 | **子プロセス**（プロセス内に uvicorn を抱えない）。だから**既に動いているサーバに繋ぐ**ことができる（抱えると二重起動しか選べない） |
| 起動の順序 | 「health を試す → 誰も居なければ起動 → **自分の子が** health を名乗るまで待つ → トレイを出す → ブラウザを開く」。**（監査 B-1）子が落ちていたらその場で失敗**（90 秒黙って待たない） |
| **受け取る pid（監査 A-2）** | **`/api/health` の `pid` が、自分の踏み台（`Start-Process` が返した物）の子孫であること**を `Win32_Process.ParentProcessId` をたどって確かめる。**違えば `attach` に落として PID を持たない**（起動の競合で**他人のサーバを自分の物にしない**）。**確かめられないときは止めない** |
| 停止 | **自分が起動した子だけを木ごと**止める（`taskkill /PID <自分が起動した PID> /T /F`）。**`.venv\Scripts\python.exe` は踏み台で、本体はその子**（実測）なので PID は 2 つ持つ。**ポート番号から相手を探して止める道は作らない**。**（監査 C-3）死んだ PID は撃たない**（ハンドルを持って再利用を防ぐ） |
| 起動の後に落ちたとき（監査 B-2） | **`own` で `up → down` になったらバルーンで知らせる**。**停止中のアイコンは形（×）で分かるようにする**（16 px では色だけでは区別できない）。§4.1 の「黙って死なない」は起動の失敗だけを見ていた |
| ログの残し方（監査 D-6・D-8） | `<リポジトリ>\.tray\` に `tray.log`・`server.log` / `server.err.log`（**前の 1 世代を `*.prev.log` に残す**）。**既定のポート以外は `server-<ポート>.log`**（2 つのトレイが同じファイルを取り合わない）。子には `PYTHONUNBUFFERED=1` |
| 失敗したとき | ログの末尾を**ダイアログとログの両方**に出す（黙って死なない。トレイの窓が無いときの失敗はここでしか見えない）。**本文は 2 文にして、英語のトレースバックは「（詳細: …）」に入れる**（監査 D-3） |
| **子に渡すデータ置き場（監査 A-1）** | **必ずこの道具が `IMAGE_REVIEWER_DATA` を明示して渡す**（親から引き継いだ値に頼らない・`Remove-Item` して既定に任せない）。**`-DefineOnly` で読み込んだとき（自己検査・駆動）は、空の `-DataDir` も実データの `.data` も断る**（1 プロセスも起動しない）。`cli serve` の `serve_data_dir()` が既定の `.data` を開く道を残したままにするため、**ここは道具の規律で塞ぐ** |
| 記録 | `<リポジトリ>\.tray\tray.log`・`server.log`・`server.err.log`。**`.data` には 1 バイトも書かない** |
| 二重起動 | 下の識別子の確認で判定する（**ポートが使えるかでは判定しない**）。**トレイ自身も `Mutex` で 1 つだけ**（2 回目はブラウザを開いて終わる） |

**起動時の識別と、ポートが埋まっているとき（点検 C21）:**

1. `GET http://127.0.0.1:8790/api/health` を試す。
2. **応答が自分（`{"app": "image-reviewer", "pid": …}`）なら**、二重に起動せず**既定のブラウザでそれを開く**。
3. **応答が別のアプリなら**（ポートは使われているが自分ではない）、
   「**ポート 8790 は別のアプリが使っています。`--port` で変えてください**」と出して**終了する**。
   相手のプロセスを止めない。黙って別のポートに移らない（利用者が開く URL が分からなくなる）。
4. 応答が無ければ自分が起動する。
5. `/api/health` の応答には **`{"ok": true, "app": "image-reviewer", "version": …, "pid": …, "started_at": …}`**
   を含める（識別のため）。

> **点検で見つかった誤り（旧 §4.1）**: 当初「**ポートが使えれば既存と見なす**」と書いていた。
> これだと**別のアプリが 8790 を使っているときに、自分の画面だと思ってブラウザを開く**。
> 識別子で確かめる形に直した（点検 C21）。
>
> **点検で見つかった誤り（旧 §4.1 の起動方式）**: 「`pythonw` 相当」とだけ書いて、
> **どこをメインスレッドにするか・どう止めるか・ショートカットの実体**を決めていなかった（点検 C20）。
>
> **（2026-10-19。作ったときに採らなかった案）** 旧 §4.1 の「`.vbs` → `pythonw.exe` →
> **同じプロセスの中に** uvicorn とトレイ」は**採らなかった**。理由は 2 つ:
> ①**新しい依存（`pystray`）を足さずに済む**（PowerShell と .NET で足りる）
> ②**サーバを子プロセスにすると「既に動いているサーバに繋ぐ」ができる**（同じプロセスに
> 抱えると、二重起動するか諦めるかの 2 択になる）。**黒い窓は `-WindowStyle Hidden` で隠す**
> （一瞬出ることがあるのは認めた穴）。

- トレイのメニュー: **「ブラウザで開く」「最近の削除を開く」「状態を見る」「再起動する」
  「終了する（サーバも止める）」**（2026-10-19。§6.1 の規約 3 に合わせて**終止形**。
  **既に動いていたサーバに繋いだときは「トレイを閉じる（サーバは止めない）」**に変わり、
  「再起動する」は押せない。**押す前に何が起きるか分かる**）。
  アイコンの形は、**未対応のレビュー要求**があるときと、**取り消せる削除**が残っているときで変える
  （件数は出さない。件数は画面とタブのタイトルに出す）。
  **ダブルクリックで開く。ツールチップは状態を 1 行で出す**（「image-reviewer（稼働中）、要求 3」。§6.1 の規約 1）。

> **点検で見つかった抜け**: 5 分の取り消しを設計しておきながら、**それを操作する場所**（常設の
> 「最近の削除」）とトレイの項目が無かった。5 分しかない窓が使えないので、§11 の画面一覧と
> [`frontend-design.md`](frontend-design.md) §3・§4・§11 に足した。

**`uv` の制限について**: この環境の DSH サンドボックス下では uv の既定キャッシュが書けないため、
開発中は `UV_CACHE_DIR=<リポジトリ>/.uv-cache` を設定する。`.gitignore` に入れる。

---

## 5. データモデル（SQLite）

設計の考え方:

- **実体（ファイル）と、見せ方（カタログ）と、判断（レビュー）を分ける。** 同じ画像を複数のフォルダに入れられ、
  判断は画像にもまとまりにも付く。
- **判断は追記のみの台帳（`decision`）** にし、現在値は `asset` 側にマテリアライズする。
  台帳があれば「いつ誰がなぜ変えたか」が残り、他ツールは現在値だけ読めばよい。
- **大きな JSON は DB に入れない。** PNG から取ったグラフは数 KB〜100KB あり、1 万枚では 1GB 規模になる。
  `<data>/workflows/<sha256>.json` に置き、DB には**要約とパスだけ**持つ。
- **画像の正体は内容ハッシュ**。パスは変わる（移動・改名）がハッシュは変わらない。参照切れの再リンクに使う。

### 5.1 実体と画像

```sql
-- 内容。ここが「画像 1 つ」の正体（同一性は内容ハッシュで決める。理由と根拠は duplicates-deletion-backup.md §1）
CREATE TABLE asset (
  id            TEXT PRIMARY KEY,        -- このツール内の ID（ULID）。内容に対して不変
  sha256        TEXT NOT NULL UNIQUE,    -- 内容ハッシュ（正体）
  size          INTEGER NOT NULL,
  width         INTEGER, height INTEGER, format TEXT,
  phash         TEXT,                    -- 64bit 知覚ハッシュを **16 進 16 文字**で持つ（理由は下）
  dhash         TEXT,                    -- 同上
  kind          TEXT NOT NULL DEFAULT 'generated',  -- 'generated'（自分の生成物）| 'reference'（参考資料）| 'photo'（写真・スクショ）
  source        TEXT NOT NULL,           -- 'scan' | 'drop' | 'clipboard' | 'url' | 'watch'
  source_url    TEXT,                    -- kind='url' のときの出所（reference でも使う）
  ref_tags      TEXT,                    -- 参考資料の「何の参考か」の自由記述（JSON 配列）
  review_state  TEXT NOT NULL DEFAULT 'unreviewed',  -- マテリアライズ: unreviewed|kept|rejected（画面は キープ/ボツ）
  review_reason_id TEXT,
  reviewed_at   TEXT, reviewed_by TEXT,
  deleted_at    TEXT,                    -- 論理削除（duplicates-deletion-backup.md §3）
  first_seen_at TEXT NOT NULL, last_seen_at TEXT NOT NULL
);
CREATE INDEX ix_asset_state ON asset(review_state, id);
CREATE INDEX ix_asset_kind  ON asset(kind, id);
CREATE INDEX ix_asset_seen  ON asset(last_seen_at DESC, id);
CREATE INDEX ix_asset_del   ON asset(deleted_at) WHERE deleted_at IS NOT NULL;

-- その内容が「どこにあるか」。1 つの内容に複数の場所があり得る
CREATE TABLE asset_location (
  asset_id   TEXT NOT NULL REFERENCES asset(id) ON DELETE CASCADE,
  path       TEXT NOT NULL,              -- 参照モードは絶対パス、取込モードは <data>/library からの相対
  kind       TEXT NOT NULL,              -- 'reference' | 'managed'
  size       INTEGER NOT NULL,           -- その場所の実測
  mtime_ns   INTEGER NOT NULL,
  is_primary INTEGER NOT NULL DEFAULT 0, -- 代表の場所（既定は最初に見つけたもの）
  missing_at TEXT,                       -- 見つからない（消さずに残す）。**走査で戻ってきたら外す**
                                         -- （P8-6 の監査 C-1。移動は mtime_ns を変えないので、
                                         --   走査の早道に落ちる。`asset.deleted_at` は触らない）
  last_seen_at TEXT NOT NULL,
  PRIMARY KEY (asset_id, path)
);
CREATE UNIQUE INDEX ux_loc_path ON asset_location(path);   -- 同じパスは 1 行
CREATE INDEX ix_loc_asset ON asset_location(asset_id, is_primary DESC);
CREATE INDEX ix_loc_missing ON asset_location(missing_at) WHERE missing_at IS NOT NULL;
```

**64bit の値は TEXT で持つ（点検で見つかった誤り）。** SQLite の `INTEGER` は**符号付き** 64bit で、
上限は 9,223,372,036,854,775,807。ところが知覚ハッシュは**符号なし** 64bit、seed は最大
`0xFFFFFFFFFFFFFFFF` = 18,446,744,073,709,551,615 で、そのままでは入らない。したがって:

| 値 | 持ち方 | 理由 |
| --- | --- | --- |
| `phash` / `dhash` | **TEXT（16 進 16 文字、小文字）** | 符号なし 64bit を正確に保つ。帯の一致は文字列一致で済む。ハミング距離は Python の多倍長整数に直して数える |
| `seed`（`asset_meta`） | **TEXT（10 進の文字列）** | 最上位ビットが立つ値を落とさない。等値比較と表示が主な用途 |
| `seed_sort`（`asset_meta`） | INTEGER（下位 63bit） | 「seed 順に並べる」ためだけに持つ。**厳密な順序が要る画面だけ**が使う（値は丸め得る） |

**パスの中身が変わったとき（点検で見つかった誤り）。** `asset_location` に `UNIQUE(path)` を置いているので、
「同じパスで中身が変わったら、新しい `asset` を作って同じパスに場所を足す」と**制約違反**になる。
正しい手順は:

1. **古い `asset` からその場所の行を消す**（パスを古い内容から外す）
2. その出来事を `location_history` に残す（このパスが以前は別の内容だったことを失わない）
3. そのうえで新しい `asset` にパスを付ける

古い `asset` は**消さない**。判断も他の場所もそのまま残す。生きた場所が 1 つも無くなったら、
「実体が無い内容」として残る（参照切れと同じ扱い。`duplicates-deletion-backup.md` §1.4・§4）。

**`location_history` の列（P8-6 で 3 列足した）。** `path` / `size` / `mtime_ns` / `replaced_by_asset_id` /
`replaced_at` に加えて、**`to_path`**（繋ぎ直した先のパス。**入れ替わりの行は `NULL`**）・
**`reason`**（`replaced`＝同じパスの中身が入れ替わった / `relinked`＝参照切れを繋ぎ直した）・
**`actor`**（繋ぎ直した人。`human` / `agent`。**走査の入れ替わりは `NULL`**）を持つ。
**版は上げていない**——`db.TOP_UP_COLUMNS` が既存の DB にも当てる（**変える前に `pre-topup-*` の控えを取る**。§5.8）。
古い行の `reason` は `NULL`＝「列を足す前の入れ替わり」を表す。

#### URL から取り込むときの上限（点検 A1）

利用者が貼った URL を取りに行くのは、このツールが自分から外へ出る唯一の経路（ComfyUI を除く）。
**取り込みは `POST /api/assets/from-url {url}` だけ**で、次を必ず掛ける:

| 項目 | 既定 | 理由 |
| --- | --- | --- |
| 方式 | **`http` と `https` だけ**。他は拒否 | `file:` などでローカルの任意ファイルを読ませない |
| リダイレクト | 最大 3 回。`http(s)` 以外への転送は拒否 | 転送で方式を変えさせない |
| タイムアウト | 接続 5 秒 / 全体 30 秒 | 固まらせない |
| 最大バイト数 | **50 MB**。超えたら中断して捨てる | 巨大なファイルでディスクを埋めない |
| 内容の確認 | **マジックナンバー**（PNG / JPEG / WebP）で確かめる。`Content-Type` は信用しない | 拡張子と中身の食い違い（§7.1 と同じ方針） |
| 保存先 | 取込モードと同じ `<data>/library`。**元の URL を `source_url` に残す** | 出所を失わない |
| 失敗時 | 1 行で理由を出す（つながらない / 大きすぎる / 画像ではない） | 黙って失敗させない |

`kind` は `photo` と推定し、`kind_source='auto:url'` を残す（人が直せる）。

- **正体は内容、場所は従属。** 同じ画像が 2 か所にあっても `asset` は 1 行で、`asset_location` が 2 行。
  ファイルを移動しても `sha256` は変わらないので、判断は切れない。
  同じ絵に 2 つの判断が付く事故も起きない（`duplicates-deletion-backup.md` §1.1）。
- `kind='reference'` は**コピーしない**。数 TB の既存資産をそのまま使う。
- `kind='managed'`（取込）は `<data>/library/<sha256[0:2]>/<sha256>.<ext>` に置く。**既定は参照**（利用者の選択）。
- 内容ハッシュは**走査の一部として計算する**。実測で SHA-256 は 399 MB/s（300 枚で計測）なので、
  1 万枚（1 枚 1.11 MB として **11.1 GB**）で約 28 秒。遅延させる理由がないため、初回から確定させる
  （`duplicates-deletion-backup.md` §1.2）。2 回目以降は（パス・サイズ・mtime）が変わったファイルだけ計算する。
- `--no-hash` を付けた下見走査では、`asset` を作らず**一覧の表示だけ**を行う（判断はできない）。

### 5.2 メタデータと来歴

```sql
-- asset と 1:1。PNG と ComfyUI から導いたもの
CREATE TABLE asset_meta (
  asset_id      TEXT PRIMARY KEY REFERENCES asset(id) ON DELETE CASCADE,
  graph_path    TEXT,      -- <data>/workflows/<sha256>.json（API 形式 or UI 形式）
  graph_kind    TEXT,      -- 'ui'（workflow チャンクあり） | 'api'（prompt のみ）
  prompt_id     TEXT,      -- ComfyUI の prompt_id（分かれば）
  model TEXT, loras TEXT, vae TEXT, sampler TEXT, scheduler TEXT,
  clip          TEXT,      -- テキストエンコーダ（例 qwen_3_06b_base.safetensors）。§4.1 of workflow-reproduction.md が必須にしている
  steps INTEGER, cfg REAL, denoise REAL,
  seed          TEXT,      -- 10 進の文字列（符号なし 64bit を落とさない。§5.1 の表）
  seed_sort     INTEGER,   -- 下位 63bit。「seed 順」の並べ替え専用
  llm           TEXT,      -- 訳に使った言語モデル（ja2en のとき）
  llm_params    TEXT,      -- TextGenerate の全パラメータ（JSON。temperature ほか。§4.1）
  positive_literal TEXT,   -- PNG にリテラルで入っていた最終プロンプト（英語）
  negative_literal TEXT,
  final_prompt  TEXT,      -- 実際に CLIPTextEncode へ渡った文字列
  final_prompt_source TEXT, -- 'png_literal' | 'reconstructed'（捕獲値＋前置語から組み直した） | 'manual'
  ja_text       TEXT,      -- 日本語原文
  ja_source     TEXT,      -- 'png_primitive' | 'workflow_node' | 'sidecar' | 'manual'
  en_text       TEXT,      -- 英訳（捕獲値。表示する値）
  en_source     TEXT,      -- 'png_literal' | 'comfyui_history' | 'sidecar' | 'textgenerate' | 'manual'
  en_is_rederived INTEGER NOT NULL DEFAULT 0,  -- 1 = 当時の訳ではなく訳し直したもの
  en_engine     TEXT,      -- 訳し直しに使った模型
  text_probe    TEXT,      -- 由来が TextGenerate に辿れないテキスト出力（JSON）。en_text にはしない
  extracted_at  TEXT NOT NULL
);

-- 画像に付いた語（出所つき）。**P4 で v5 として作った**（実装は `db.py` の `V5_TAG_DDL`。
-- 詳細と根拠は `docs/p4-design.md` §2.1。**語彙の CHECK と `known` は P4 の決定**）
CREATE TABLE tag (
  id INTEGER PRIMARY KEY,
  name TEXT NOT NULL UNIQUE,  -- 正規形（小文字・語間は `_`）。**括弧とコロンは語の一部**（`rem_(re:zero)`）
  category INTEGER CHECK (category IS NULL OR category IN (0, 4, 9)),
                              -- WD14 CSV の category。**eva02 v3 の CSV にあるのは 0（general）・4（character）・9（rating）だけ**
                              -- （artist(1) と copyright(3) の行が無い。実測）。9 は**捨てる**ので実質 0 と 4
  category_name TEXT,
  known INTEGER NOT NULL DEFAULT 0 CHECK (known IN (0, 1))
                              -- **語彙（CSV）にある語か**（P4 の決定 Q1）。**導出値**で、
                              -- 書き込みは `INSERT ... ON CONFLICT(name) DO UPDATE SET known = max(known, excluded.known)`、
                              -- ジョブの開始時に語彙から引き直す。PNG の自然文から来た語は 0
);
CREATE TABLE asset_tag (
  asset_id TEXT NOT NULL REFERENCES asset(id) ON DELETE CASCADE,
  tag_id   INTEGER NOT NULL REFERENCES tag(id),
  score    REAL,           -- 確からしさ。**IllustTagger 経由だけ入る**（WD14Tagger は返さないので NULL）
  source   TEXT NOT NULL CHECK (source IN ('png', 'wd14', 'manual')),   -- P4 で CHECK を足した
  model    TEXT,           -- 付けたタガーのモデル名（**「もう見た」の判定に使う**）
  actor    TEXT,           -- 手で付けた人（'human' / 'agent'）。タガーの行は NULL。**いまは human だけ**
  tagged_at TEXT NOT NULL,
  PRIMARY KEY (asset_id, tag_id, source)
);
CREATE INDEX ix_asset_tag_tag ON asset_tag(tag_id, asset_id);
```

### 5.3 カタログ（仮想フォルダ）

```sql
CREATE TABLE folder (
  id TEXT PRIMARY KEY,
  parent_id TEXT REFERENCES folder(id) ON DELETE CASCADE,  -- NULL = 根
  name TEXT NOT NULL,
  kind TEXT NOT NULL,       -- 'manual' | 'smart'
  smart_query TEXT,         -- kind='smart' のときの条件（JSON。§10.2）
  position INTEGER NOT NULL DEFAULT 0,
  count_cache INTEGER,      -- 中の枚数（概算のキャッシュ。§10.2）
  count_cached_at TEXT,
  created_at TEXT NOT NULL
);
CREATE INDEX ix_folder_parent ON folder(parent_id, position);

-- 多対多。同じ画像を複数のフォルダに置ける
CREATE TABLE folder_member (
  folder_id TEXT NOT NULL REFERENCES folder(id) ON DELETE CASCADE,
  asset_id  TEXT NOT NULL REFERENCES asset(id) ON DELETE CASCADE,
  position  INTEGER NOT NULL DEFAULT 0,
  added_at  TEXT NOT NULL,
  PRIMARY KEY (folder_id, asset_id)
);
CREATE INDEX ix_folder_member_asset ON folder_member(asset_id);
```

### 5.4 レビュー（まとまり・台帳・理由）

```sql
-- レビューの単位。複数画像のまとまり
CREATE TABLE review_group (
  id TEXT PRIMARY KEY,
  title TEXT,
  kind TEXT NOT NULL,       -- 'manual' | 'folder' | 'batch' | 'variation' | 'duplicate' | 'request'
  source TEXT NOT NULL,     -- 'manual' | 'comfyui' | 'watcher' | 'request'
  source_ref TEXT,          -- 取り込み元（生成の識別子、要求 ID など）
  policy TEXT NOT NULL,     -- 'pick_one' | 'pick_many' | 'all_reject_only'
  state TEXT NOT NULL,      -- 'open' | 'decided'
  created_at TEXT NOT NULL,
  decided_at TEXT, decided_by TEXT
);
CREATE TABLE group_item (
  group_id TEXT NOT NULL REFERENCES review_group(id) ON DELETE CASCADE,
  asset_id TEXT NOT NULL REFERENCES asset(id) ON DELETE CASCADE,
  position INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (group_id, asset_id)
);

-- 判断の台帳（追記のみ。消さない・書き換えない）
CREATE TABLE decision (
  id TEXT PRIMARY KEY,
  created_at TEXT NOT NULL,
  actor TEXT NOT NULL,              -- 'human' | 'agent'（自己申告。§9.5）
  subject_type TEXT NOT NULL,       -- 'asset' | 'group'
  subject_id TEXT NOT NULL,
  verdict TEXT NOT NULL,            -- 'keep' | 'reject' | 'clear'
  reason_code_id TEXT REFERENCES reason_code(id),
  note TEXT,
  group_id TEXT REFERENCES review_group(id),  -- どのまとまりの判断か
  group_decision TEXT,              -- 'selected' | 'not_selected' | 'all_rejected'
  supersedes TEXT REFERENCES decision(id)     -- 直前の判断（変更の連鎖）
);
CREATE INDEX ix_decision_subject ON decision(subject_type, subject_id, created_at DESC);
CREATE INDEX ix_decision_group   ON decision(group_id, created_at DESC);

-- 理由のマスタ（利用者が編集する）
CREATE TABLE reason_code (
  id TEXT PRIMARY KEY,
  label TEXT NOT NULL,
  applies_to TEXT NOT NULL,   -- 'keep' | 'reject' | 'both'
  position INTEGER NOT NULL DEFAULT 0,
  active INTEGER NOT NULL DEFAULT 1,
  builtin INTEGER NOT NULL DEFAULT 0
);
```

**グループ判定の意味**（R6）:

| policy | 操作 | 台帳に書かれるもの |
| --- | --- | --- |
| `pick_one` | 1 枚を選ぶ | 選んだ枚に `keep`（`group_decision='selected'`）。他の全枚に `reject`（`'not_selected'`）。まとまりは `decided` |
| `pick_one` | すべてボツ | 全枚に `reject`（`'all_rejected'`）。**理由は利用者が選ぶ**（既定の理由を 1 つ用意する） |
| `pick_many` | 複数選ぶ | 選んだ枚に `keep`、残りに `reject` |
| `all_reject_only` | ボツのみ | 全枚に `reject` |

「すべてボツ」でも**理由を必ず付ける**。これが R5b と R6 の交点で、
「なぜこのまとまりを丸ごと落としたか」が後から読める。

### 5.5 ジョブと監視

**`job` / `job_item` は P4-1 で作った**（実装は `db.py` の `V5_TAG_DDL`。**ワーカーは 1 本**・
**1 枚 1 取引**・中断は画像 1 枚ごと・失敗は 1 件ずつ `job_item` に残す。`docs/p4-design.md` §0.3・§4.1）。
`watcher_state` はまだ作っていない（監視は後の段）。

```sql
CREATE TABLE job (
  id TEXT PRIMARY KEY,
  kind TEXT NOT NULL,        -- 'scan' | 'thumbnail' | 'tag' | 'extract' | 'hash' | 'export'（いまは 'tag' だけ）
  state TEXT NOT NULL CHECK (state IN ('queued', 'running', 'done', 'failed', 'cancelled')),
  params TEXT, progress_done INTEGER DEFAULT 0, progress_total INTEGER,
  message TEXT, error TEXT,
  note TEXT,                 -- ★P4 で足した: 結果の 1 行（「PNG の語: 42 語を採用（うち語彙外 11 語）」など）
  created_at TEXT NOT NULL, started_at TEXT, finished_at TEXT
);
CREATE TABLE job_item (       -- 失敗した 1 件を残す（まとめて握りつぶさない）
  job_id TEXT NOT NULL REFERENCES job(id) ON DELETE CASCADE,
  ref TEXT NOT NULL,
  state TEXT NOT NULL CHECK (state IN ('tagged', 'skipped', 'failed')),   -- ★P4 で語彙を確定
  error TEXT,
  PRIMARY KEY (job_id, ref)
);
CREATE TABLE watcher_state (  -- ComfyUI 監視の既読位置（**未実装**）
  name TEXT PRIMARY KEY, last_prompt_id TEXT, last_polled_at TEXT, enabled INTEGER
);
```

**一覧の口（`GET /api/jobs`）も `items_failed` を先頭 20 件返す**（P4-3 の監査 A-1。画面が失敗の理由と
「もう一度」を出せるように。単体の口と `/items` は前から返していた）。

### 5.6 要求・注記・プリセット・語釈

```sql
-- エージェントからのレビュー要求（R10）。投げてすぐ返り、人が判断すると閉じる
-- **P6 で確定**: `response`（閉じた時点の写し）と `client_token`（再送の鍵）を足した。
-- 差し替えるのは **`state='open'` の行だけ**。実装は `db.py` の v4（`docs/p6-design.md` §2.1 が正）
CREATE TABLE review_request (
  id            TEXT PRIMARY KEY,
  group_id      TEXT NOT NULL REFERENCES review_group(id),  -- 対象のまとまり
  target_key    TEXT,            -- エージェントが付ける任意の鍵。同じ鍵の**未対応（open）**は差し替える（§9.6）
  state         TEXT NOT NULL,   -- 'open' | 'done' | 'declined' | 'superseded'
  ask           TEXT,            -- エージェントの用件（1 行）
  conditions    TEXT,            -- 「何をもって良いとするか」の一覧（JSON 配列。自由文）
  origin        TEXT,            -- '作品名 / カット名' など、どこから来たか（自由文）
  wants         TEXT,            -- 応答に求めるもの（JSON: selected_ids / reason / annotations など）
  ai_pick_asset_id TEXT,         -- AI の下書き判断（推した 1 枚）
  ai_note       TEXT,            -- AI の理由・コメント
  actor         TEXT NOT NULL,   -- 'agent' | 'human'（ヘッダの自己申告。判断は human だけ）
  created_at    TEXT NOT NULL,
  closed_at     TEXT, closed_by TEXT,
  decline_note  TEXT,            -- 断った理由（エージェントが次を決められるように）
  superseded_by TEXT,            -- 同じ対象の新しい要求で差し替えたとき
  response      TEXT,            -- **閉じた時点の応答**（JSON。reopen しても答えが変わらない。P6 の決定）
  client_token  TEXT             -- 再送の鍵（中身が同じなら 200 で既存を返す）
);
CREATE INDEX ix_request_state ON review_request(state, created_at DESC);
CREATE INDEX ix_request_group ON review_request(group_id, state);
-- **`open` のときだけ効く部分 UNIQUE 索引**（P6。`ix_request_target` を置き換える）。
-- 同じ鍵の `open` を 2 本作らせない。**先に古い方を `superseded` に UPDATE してから INSERT する**
CREATE UNIQUE INDEX ux_request_target_open
  ON review_request(target_key) WHERE state = 'open' AND target_key IS NOT NULL;
CREATE UNIQUE INDEX ux_request_token ON review_request(client_token) WHERE client_token IS NOT NULL;

-- 差し替えで閉じた**まとまり**の印（P6 の決定 A3 / G6）。**判断が 1 つも無いときだけ**入れる。
-- 入っているまとまりは一覧と review.json の既定から外す（`?include_superseded=1` で出す）
-- → review_group.superseded_by TEXT

-- AI の下書き判断は消さない（人が確定した後も両方残す。§9.5）
-- → review_request.ai_pick_asset_id / ai_note で持つ。
--   decision の actor='agent' は**今の実装では書かれない**（エージェントは判断を書けない。§9.5）。
--   契約の互換のため値としては残す。

-- 画像の上の印（R11）。座標は 0〜1 の割合
-- **P6 で確定**: 座標は **NULL 可**（「画像 1 枚へのメモ」を同じ表で扱う。§9.7 の決定に DDL を合わせた）。
-- 実装は `db.py` の v4（`review_request` / `annotation`）。CHECK と索引は `docs/p6-design.md` §2.1 が正
CREATE TABLE annotation (
  id         TEXT PRIMARY KEY,
  asset_id   TEXT NOT NULL REFERENCES asset(id) ON DELETE CASCADE,
  shape      TEXT,            -- 'rect' | 'ellipse' | NULL（座標が全部 NULL のときだけ）
  x REAL, y REAL, w REAL, h REAL,  -- 0..1。**全部 NULL（領域なし）か全部ありの 2 形だけ**
  body       TEXT,            -- メモ
  actor      TEXT NOT NULL,   -- 'human' | 'agent'
  created_at TEXT NOT NULL,
  group_id   TEXT REFERENCES review_group(id),  -- どのまとまりのレビューで付けたか（任意）
  client_token TEXT,          -- 再送の鍵（P5 / P6 と同じ。部分 UNIQUE 索引）
  CHECK ((shape IS NULL) = (x IS NULL) AND (x IS NULL) = (y IS NULL)
         AND (y IS NULL) = (w IS NULL) AND (w IS NULL) = (h IS NULL)),
  CHECK (x IS NULL OR (x >= 0 AND x <= 1 AND y >= 0 AND y <= 1
                       AND w > 0 AND h > 0 AND x + w <= 1 + 1e-9 AND y + h <= 1 + 1e-9))
);
CREATE INDEX ix_annotation_asset ON annotation(asset_id, created_at);
-- **まとまり全体へのメモは作らない**（P6 の決定 A1 / G4）。その用途は `review_group.note`（判断のメモ）にある

-- **（廃止。2026-10-17）** 名前を付けた条件（R12）。P7 で作ったが、利用者の判断で消した（§16.5）
CREATE TABLE preset (
  id              TEXT PRIMARY KEY,
  name            TEXT NOT NULL,
  note            TEXT,
  source_asset_id TEXT REFERENCES asset(id),   -- どの画像から取ったか（任意）
  record_json     TEXT NOT NULL,               -- 条件の写し（グラフと正規化した値）
  created_at      TEXT NOT NULL
);

-- Danbooru タグの日本語の語釈（R3）。人が直せる
CREATE TABLE tag_gloss (
  tag_id     INTEGER PRIMARY KEY REFERENCES tag(id) ON DELETE CASCADE,
  ja         TEXT NOT NULL,
  source     TEXT NOT NULL,   -- 'textgenerate' | 'manual'
  engine     TEXT,            -- 訳に使った模型の名前
  edited     INTEGER NOT NULL DEFAULT 0,  -- 人が直したか（1 なら訳し直しで上書きしない）
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
```

---

### 5.7 専門文書が定義する表（点検で見つかった抜け）

§5 は「全体で共有する表」を置く。**用途が 1 つの専門文書に閉じる表は、その文書が正**とする。
ここに一覧だけ置く（**定義を二重に書かない**。食い違いの元になるため）:

| 表 | 定義している文書 | 何のため |
| --- | --- | --- |
| `phash_band` | [`duplicates-deletion-backup.md`](duplicates-deletion-backup.md) §2.2（**形は P8 で作り直した。§5.8 が正**） | 準重複の候補を絞る（**4bit × 16 本**。**距離 ≤ 15 なら 1 本は必ず一致する**） |
| `duplicate_exclusion` | 同 §2.4 | 「別物として確定」した組（**§5.8**） |
| `deletion_log` | 同 §3.3 | 削除の段階・保留領域・取り消し・purge_at（**§5.8**） |
| `location_history` | 同 §1.4 | 同じパスの内容が入れ替わった事実 |
| `recipe_record` | [`workflow-reproduction.md`](workflow-reproduction.md) §4.9 | **（廃止。2026-10-17）** 生成条件の記録。P7 で作って消した（§16.5） |
| `recipe_export` | 同 §4.9 | **（廃止）** 書き出したグラフ（印・attempt_id・seed） |
| `recipe_export_result` | 同 §4.9 | **（廃止）** 出てきた画像と指標・人の合否 |
| `preset` | 同 §4.10 | **（廃止）** 名前を付けた条件 |

> **点検で見つかった誤り**: §5 にこれらが無いのに §14 の工程が前提にしていた。
> 表を**写す**のではなく**参照する**形にして直した（写すと必ず食い違う。実際に
> `asset` 表の写しが `kind` / `source_url` / `ref_tags` を落としていた）。

---

### 5.8 P8（重複・削除・バックアップ）で作った表（v6）

**P8 で作った。** `SCHEMA_VERSION = 6`（`_migrate_v6()`。P7 が使って v5 に戻した番号を、この段で使い直した）。
**DDL と列の意味の正は [`p8-design.md`](p8-design.md) §2.1**（ここには一覧だけ置く。§5.7 と同じ約束で**定義を二重に書かない**）:

| 表・列 | 何 | 備考 |
| --- | --- | --- |
| **`asset.deleted_at`**（列） | 論理削除（**段 1**）。**NULL = 生きている**。**行は消さない**（判断と来歴を残す） | §5.1 の `asset` に既に書いてあった物を実装した（**列なので `CHECK` は付けられない**＝値の検査はサービス層） |
| **`deletion_log`**（表） | 削除の台帳。段（1/2/3）・パス・`hold_path`・`remaining_sec`・`purge_at`・`restored_at`・`request_id`・`reason`・**`stuck_reason`**（戻せなかった理由。`target_exists` / `move_failed` / `different` / `missing`）・`actor`（`human` / `agent`） | **削除後も消さない**。`asset` に `REFERENCES` を張らない（台帳は画像より長く生きる） |
| **`delete_request`**（表） | **要求の単位**の `client_token` と `result_json`（同じ token の再送は前の結果を返す） | 一括は 1 要求で最大 200 行を書くので、`client_token` を**行に持たせると 2 行目で UNIQUE に当たる**（点検 A2） |
| **`duplicate_exclusion`**（表） | 「別物として確定」した組。`reason` / `actor` / `at` | `PRIMARY KEY (a_id, b_id)` ＋ **`CHECK (a_id < b_id)`**（`(A,B)` と `(B,A)` を別行にしない）。**解除できる** |
| **`phash_band`**（表） | 準重複の候補を絞る帯。`PRIMARY KEY (asset_id, band)` | **4bit × 16 本**（**`CHECK (band BETWEEN 0 AND 15)`**・`length(value) = 1`）。**書き手は `store.set_hashes` の 1 か所**。**距離 ≤ 15 の保証**（鳩の巣）・**16 以上は帯で絞らず総当たり** |
| **`pending_delete_preview`**（表） | 一括削除の**凍結**（`preview_id`・凍結した一覧・`expires_at`・`actor`） | **実行時に評価し直さない**。失効は既定 10 分。**実行後も行は消さない**（`result_json` を再送に返す） |
| **`root.allow_stage3`**（列） | その置き場で**実ファイルの削除（段 3）を許すか** | **既定は 0（許さない）**（利用者の回答 Q8。**別のツールの管理下を守るための印**）。実データは `illust-authoring` の置き場（262 / 263 枚）にだけ 1 が立っている |
| **`job.cancel_requested`**（列） | 背景ジョブの**中断の印** | `JobService` と `DuplicatesService` が**同じ列を見る**（前の版は各サービスが自分のメモリに印を持ち、`POST /api/jobs/{id}/cancel` で**ハッシュのジョブが止まらなかった**）。**再起動をまたいでも残る** |
| **`location_history` の `to_path` / `reason` / `actor`**（列。**P8-6 で足した**） | 履歴の 1 行を「入れ替わった」と「繋ぎ直した」に分ける。`reason` は `replaced` / `relinked`、`to_path` は繋ぎ直した先（入れ替わりは `NULL`）、`actor` は繋ぎ直した人（走査の入れ替わりは `NULL`） | **版は上げていない**（`db.TOP_UP_COLUMNS` が正。**古い行の `reason` は `NULL`**＝「列を足す前の入れ替わり」）。`register()` は `reason='replaced'` を書き、`RelinkService` は `reason='relinked'` を書く |
| **`deletion_log.closed_at` / `close_reason`**（列。**P10 で足した**） | **実体が無い行を終わりにした**時刻と理由（**P10**。[`deletions-advance.md`](deletions-advance.md)）。`close_reason` の語彙は **`missing` だけ**（`CHECK` にも入れた）。**片付けてもファイルは 1 つも消さない・動かさない**（`asset.deleted_at` もそのまま＝**カタログに戻さない**）。**段 3 の行は `purge_at` / `remaining_sec` も NULL にする**（タイマーから外す。**P10 の監査 C-3**） | **版は上げていない**（`db.TOP_UP_COLUMNS` が正）。**閉じた行は「最近の削除」から外れ、台帳 `GET /api/deletions` には残る**。**片付けた後は戻せない**（`undo` は 409 `already_closed`）。**（P10 の監査 A-3）ただしファイルが戻ってくれば戻せる**（走査が印を引き直す／実体が在れば `undo` が開き直す） |

- **版を上げずに形を足した物**（`deletion_log.stuck_reason`・**`deletion_log.closed_at` / `close_reason`**・
  **`location_history` の `to_path` / `reason` / `actor`**）は
  **`db.TOP_UP_COLUMNS` が正**（`_top_up_v6` と `missing_top_ups()` が同じ表を見る）。
  **変える前に `pre-topup-<日時>/` の控えを取る**（§0.12-6 と同じ規律）。
- **実データ `.data/` の `closed_at` / `close_reason` は、2026-10-19 16:48:56 に足された**——
  **利用者の起動ではなく、トレイの自己検査の穴（監査 A-1）**。`IMAGE_REVIEWER_DATA` を付けずに
  `cli serve` を起こす道があり、**既定の `.data` が開かれた**（**控え無し**・**行の中身の変化は 0**・
  `user_version` は 6 のまま）。**`pre-topup-<日時>/` の控えは残っていない**
  （自己検査が控えの置き場を `.tmp-tray\backups` に向けていて、その scratch を消したときに一緒に消えた）。
  事後の控えは `.backup/pre-tray-fix-20261019-204253/`。**列は戻していない**
  （利用者の次の起動でも足される物と同じ）。直しと再発防止は
  [`tray-audit-triage.md`](tray-audit-triage.md) A-1・[`tray.md`](tray.md) §4.0・§6。
  **規律**: **実データを開き得る道具は、子に `IMAGE_REVIEWER_DATA` を必ず明示する**——
  `create_app()` の env 検査は `cli serve`（`serve_data_dir()` が既定を明示する）を通るので、
  **ここは道具側で塞ぐしかない**。**控えの置き場も scratch にしない**（消える）。
- **`asset.deleted_at` は資産の単位・削除は場所の単位。** 印を立てるのは**生きている `asset_location` が 0** か
  **生きた段 1 の行がある**ときだけ（場所が 2 つある画像の片方を消しただけで一覧から消さない）。
  **（P10 の監査 A-3）片付けた行（`closed_at`）は数えない**——閉じた行は「終わった」ので隠す理由に
  ならない（実体が無い間は「生きている場所が 0」で隠れたままになる＝幽霊は戻らない）。
  規則は **`deletions.should_hide()` / `sync_hidden()` の 1 か所**で、**走査もそこを呼ぶ**
  （`relink.py` も同じ関数を呼ぶ）。
- **`delete_request` は「1 行 = 1 回の操作」**。**（P10 の監査 B-2）まとめて（`advance` / `close`）も
  1 回の呼び出しで 1 行**残す（`count` = requested、`result_json` に `skipped` も）。**断った要求は
  残さない**（`_drop_request`）。

---

## 6. API

### 6.1 内部 API（画面が使う。すべて `/api` 配下）

```text
GET    /api/health                -- {"ok":true,"app":"image-reviewer","version":…,"pid":…,"started_at":…}
                                  -- app と pid は「自分かどうか」の識別に使う（§4.1。点検 C21）
GET    /api/health/db             -- quick_check の結果と版

# 取り込み（R1b）
POST   /api/scan                  {roots:[], mode:'reference'|'import', recursive:true,
                                   no_hash:false, dry_run:false, mirror_folders:false}
                                  -- dry_run:true は**登録せず**、見つけた画像と「新規/既知/入れ替わり/来歴あり」
                                  -- の内訳をメモリ上で返す（点検 C7/G11。--no-hash はこれを出すだけ）
                                  -- mirror_folders:true は初回だけディスクの階層を仮想フォルダに写す（点検 C6）
                                  -- → {seen, images, not_image, created, known, changed, with_provenance,
                                  --     roots, items:[{path, size, mtime_ns, action}]}（dry_run のとき items を返す）
POST   /api/assets/register       {path, mode}            -- 単一登録（R1）
POST   /api/assets/from-url       {url}                   -- 画像 URL を落として登録
POST   /api/assets/from-clipboard                         -- クリップボードの画像を登録
                                                          --   （中身が URL で拡張子が画像なら from-url を試す）
GET    /api/jobs                  ?state=&kind=
GET    /api/jobs/{id}
POST   /api/jobs/{id}/cancel

# 一覧と検索（キーセット改ページ）
GET    /api/assets                ?folder=&tag=&known=&q=&state=&kind=&cursor=&limit=100&sort=added|seen|name
                                  -- `tag=` は P4 で足した（**既定は `known=1`** に当てる）
GET    /api/assets/{id}
GET    /api/assets/{id}/file                                  -- 原本
GET    /api/assets/{id}/thumb     ?size=256|1024              -- 生成済みサムネイル
GET    /api/assets/{id}/neighbors ?cursor=                     -- 前後の画像（ビューア用）
PATCH  /api/assets/{id}           {kind?, source_url?, ref_tags?}   -- 種別は自動判定を人が直せる

# メタデータと来歴
GET    /api/assets/{id}/metadata            -- §7 の要約（ja/en・タグ・生成パラメータ）
GET    /api/assets/{id}/graph               ?format=ui|api    -- グラフ JSON（ダウンロード）
POST   /api/assets/{id}/graph/install       -- ComfyUI の workflows へ置く（§7.4。overwrite しない）
POST   /api/assets/{id}/retranslate         {engine:'textgenerate', text?}  -- 訳し直し（出所を記録）
POST   /api/assets/{id}/extract             -- PNG / JPEG を読み直す

# タグ（**P4-1 / P4-2 で実装**。詳しくは `docs/p4-design.md` §3.1〜§3.6）
GET    /api/tags                  ?q=&category=&source=&known=&limit=&cursor=
                                  -- **`known` の既定は 1**（語彙にある語だけ）。`known=1|0|all`（P4 の決定 Q1）
GET    /api/assets/{id}/tags                 -- ★P4 で足した（本文に無かった）。契約の形＋`glosses` / `pending_gloss` / `counts`
POST   /api/assets/{id}/tags      {tags:[{name, category?, source:'manual'}]}   -- **human だけ**（403）
DELETE /api/assets/{id}/tags/{tag_id}                                        -- **manual の行だけ**。2 回目は 404
POST   /api/assets/tag            {asset_ids:[], model?, threshold?, engine:'auto'|'builtin'|'comfyui', sources?:[], force?}
                                  -- **投げてすぐ返る**（202。job の id）。`auto` は内蔵優先で検出（P4 の決定 G-3）
GET    /api/jobs                  ?limit=&state=        -- ★一覧も `items_failed` を先頭 20 件返す（P4-3 の監査 A-1）
GET    /api/jobs/{id}             /  /items ?state=     -- 進行・失敗の一覧
POST   /api/jobs/{id}/cancel                            -- 画像 1 枚ごとに印を見る
GET    /api/tags/{tag_id}/gloss                    -- 日本語の語釈（**訳さない**。無ければ `ja: null`）
POST   /api/tags/{tag_id}/gloss   {ja}             -- 人が直す（**`edited=1` を立て、`source` は由来を保つ**）
POST   /api/tags/gloss            {tag_ids:[], limit?, force?}   -- 訳す（`TextGenerate`。**20 語まで**・既定は語釈の無い語だけ）
GET    /api/tags/gloss/pending    ?limit=          -- まだ語釈が無い語（**数えるだけ**）

# カタログ
GET    /api/folders                                           -- 木
POST   /api/folders               {parent_id, name, kind}
PATCH  /api/folders/{id}          {name?, parent_id?, position?, smart_query?}
DELETE /api/folders/{id}          ?dry_run=true
                                  -- dry_run は「中の枚数・子の数・影響」を返すだけ（消さない）
DELETE /api/folders/{id}          {confirm:'<フォルダ名>'}
                                  -- **名前を打ち込ませて確認する**。仮想フォルダは再生成できない分類なので、
                                  -- 無警告で消さない（点検 C11）。既定は論理削除（`deleted_at`）で、
                                  -- 実削除は `purge:true` を明示したときだけ
POST   /api/folders/{id}/members  {asset_ids:[]}
DELETE /api/folders/{id}/members  {asset_ids:[]}
GET    /api/folders/{id}/assets   ?cursor=&limit=&sort=

# 判断（キープ / ボツ）
GET    /api/reason-codes
POST   /api/reason-codes          {label, applies_to}
PATCH  /api/reason-codes/{id}
POST   /api/reviews               {subject_type:'asset', subject_id, verdict:'keep'|'reject'|'clear',
                                   reason_code_id?, note?, actor?}
                                  -- 画像 1 枚のときだけ。まとまりは下の decide を使う（重複を避ける）
                                  -- **`human` 以外は 403**（エージェントは判断を書けない。§9.5）
GET    /api/reviews               ?asset=&group=&limit=      -- 台帳（履歴）
GET    /api/groups                ?state=
POST   /api/groups                {title?, kind, asset_ids:[]}
GET    /api/groups/{id}
POST   /api/groups/{id}/decide    {items:[{asset_id, verdict:'keep'|'reject', reason_code_id, note?}],
                                   group_reason_code_id?, note?}
                                  -- 枚ごとに理由を受ける（選ばれなかった枚にもその枚自身の理由が要る）
                                  -- **`human` 以外は 403**（同上）
POST   /api/groups/{id}/reopen
GET    /api/groups/{id}/compare   -- 比較の並び（画像 + タグ + 生成パラメータ + 差分）

# 外部参照（§6.2。他ツールが読む口）
GET    /api/export/review.json    ?scope=all|group:{id}|folder:{id}|request:{id}
                                  &include_paths=false&include_tags=false&include_prompts=false
                                  -- 返すだけ。**ファイルは書かない**（監査 C8/G2）
POST   /api/export/review.json    {scope, include_paths?, include_tags?, include_prompts?}
                                  -- いま書き出す（原子的に置換）。全件は手動と日次だけ（§6.2）
                                  -- **書くのはこの口の `scope=all` だけ**（監査 C8/G2）
GET    /api/export/review.schema.json

# エージェントからの要求（R10）
POST   /api/review-requests       {asset_ids:[] | group_id?, target_key?, policy?, ask?, conditions?[],
                                   origin?, wants?[], ai_pick_asset_id?, ai_note?}
                                  -- 同じ target_key の未対応があれば superseded にして差し替える（§9.6）
                                  -- target_key が無ければ上書きしない（別の要求として積む）
GET    /api/review-requests       ?state=open&cursor=&limit=
GET    /api/review-requests/{id}  -- 判断が出たら結果が入っている（エージェントはこれをポーリングする）
POST   /api/review-requests/{id}/decline  {note}   -- 断る（理由が要る）

# 注記（R11）
GET    /api/assets/{id}/annotations
POST   /api/assets/{id}/annotations   {shape?:'rect'|'ellipse', x?,y?,w?,h?, body?, group_id?, client_token?}
                                  -- **座標を省くと「画像 1 枚へのメモ」**（P6 の決定 A1）
PATCH  /api/annotations/{id}          {body?}   -- 自分の actor の注記だけ（点検 C7）
DELETE /api/annotations/{id}                    -- 同上。2 回目は 404。切り出しの PNG も消す（G3）
GET    /api/assets/{id}/annotations/export   ?format=json   -- **返すだけ**（P6 の決定 G1）
POST   /api/assets/{id}/annotations/export   {format:'crops'}  -- **書くのはこの口だけ**
                                  -- 座標と文の JSON、または囲んだ範囲ちょうどの切り出し画像
GET    /api/annotations/{id}/crop               -- その場で作って返す（ディスクに書かない）

# **（廃止。2026-10-17。利用者の判断）** 条件の記録と再利用（R12。実行はしない）
#   —— 以下の口は P7 で実装したが、削除した（理由は §16.5 と `p7-decision.md`）。**歴史として残す**
GET    /api/assets/{id}/recipe                -- 記録と判定（完全/近似/不可＋理由）
POST   /api/assets/{id}/recipe                {mode:'pin_text'|'rerun_graph'|'manual_text', text?}
GET    /api/recipes               ?cursor=&limit=
GET    /api/recipes/{id}/graph    ?format=ui|api
POST   /api/recipes/{id}/export   {seeds:[] | count:8, marker:true}
                                  -- seed を差し替えたグラフを書き出す（印つき。§4.7 of workflow-reproduction.md）
POST   /api/recipes/{id}/check    -- 書き出す前の検査（モデルとノードがあるか）
GET    /api/recipes/{id}/exports  -- 書き出しの一覧（attempt_id・marker・manifest）
POST   /api/recipes/{id}/exports/{attempt_id}/results/{result_id}/verdict
                                  {verdict:'same'|'close'|'different'|'failed', note?}
                                  -- 出てきた画像に対する人の合否（消えない形で残す）
GET    /api/presets
POST   /api/presets               {name, note?, source_asset_id?}
GET    /api/presets/{id}/record   -- 条件の写し（コピー用）

# 重複と削除（duplicates-deletion-backup.md。**P8 で実装**。決定は §16.6）
GET    /api/duplicates/exact      ?limit=
                                  -- 完全重複（同じ内容が 2 か所以上）。**この実データでは 0 群**なので
                                  -- count: 0 と message を返す（**空の一覧を黙って出さない**）
GET    /api/duplicates/near       ?max_distance=6&limit=
                                  -- 準重複（pHash のハミング距離 ≤ max_distance）。**計算はしない**
                                  -- （未計算は unhashed で返す。計算は下の POST）。各群に suggested_id と
                                  -- reason（**代表の推薦**。§0.9）・max_distance_within。**頁送りは無い**
POST   /api/duplicates/compute    {force?}                     -- 足りない pHash を計算する背景ジョブ（202）
POST   /api/duplicates/exclude    {a_id, b_id, reason?}        -- 「別物として確定」（(min,max) に正規化）
POST   /api/duplicates/exclude/remove {a_id, b_id}             -- **解除**（必須。点検 C10）
                                  -- **`DELETE` に本文を持たせない**ので、解除も `POST`（§0.15 の 1）
GET    /api/duplicates/exclusions ?limit=                      -- 確定した組の一覧（解除の画面が読む）
POST   /api/locations/delete      {asset_id, path, stage:1|2|3, reason?, client_token?, confirm_last_copy?}
                                  -- **`POST`**（`DELETE` に本文を持たせない。§0.15 の 1）。**段 1〜3**
                                  -- stage は **1 / 2 / 3 の整数だけ**（`true` や `3.9` は 422。丸めない）
                                  -- **最後の 1 つを段 3 で消すには `confirm_last_copy: true`**（無ければ 409 last_copy）
                                  -- `client_token` の再送は 200 で前の結果（**二重に消さない**）
POST   /api/locations/bulk-delete/preview
                                  {scope:{kind:'folder'|'group'|'query'|'assets', id?, query?, asset_ids?[]},
                                   stage:1|2|3}
                                  -- 対象を 1 回だけ解決して**凍結**する（点検 A6）
                                  -- → {preview_id, items:[{asset_id, path, display_path, size, mtime_ns}],
                                  --     count, bytes, frees:{bytes, at, note}, expires_at,
                                  --     last_copies, not_allowed}
                                  -- **エージェントは 200 枚を超えたら 422 too_many**（**1 枚も消さない**。人に上限は無い）
                                  -- `folder` は**登録した `root` の下だけ**（外は 422 bad_scope）
POST   /api/locations/bulk-delete {preview_id, confirm:true, client_token?, confirm_last_copy?}
                                  -- **凍結した一覧だけ**を消す。実行時に評価し直さない
                                  -- 1 件ずつ (size, mtime_ns) を**凍結した値と実ファイルの両方**と再照合し、
                                  -- 食い違いは skipped にして**その項目だけ飛ばす**（残りは消す）
                                  -- preview_id は既定 10 分で失効。失効したら**何も消さず 409 preview_expired**
GET    /api/pending-deletes       -- **最近の削除**（段 1〜3。残り時間・stuck_reason・**誰が消したか**）
                                  -- **残り時間を減らさない**（減らすのはタイマー）。拾い物は found で出す
POST   /api/pending-deletes/{id}/undo {as_copy?}
                                  -- **取り消す**（**上書きしない**。埋まっていれば 409 target_exists で**止めて尋ねる**）
                                  -- **人だけ**が `as_copy: true`（`<名前>.<連番>.<拡張子>` で戻す）
                                  -- **（P10 の監査 A-2）台帳の枚と、いまその場所に登録されている枚の
                                  -- 両方の `deleted_at` を引き直す**（片方だけだと、戻したのに実体の
                                  -- ある枚が一覧から永久に消える）
                                  -- **（P10 の監査 A-3）片付けた段 1 の行でも、実体が在り登録も生きて
                                  -- いれば開き直して戻せる**（ファイルが無い間は 409 `already_closed`）
POST   /api/deletions/{id}/undo   {as_copy?}                   -- 同じ道（段 1〜3 に効く）
GET    /api/deletions             ?limit=                      -- 削除の台帳（deletion_log）
GET    /api/deletions/trash       ?limit=                      -- ゴミ箱（段 2。日付は現地）
GET    /api/deletions/previews/{preview_id}                    -- 凍結の 1 件（失効しても 409 を返せるように残す）
GET    /api/trash                 ?limit=                      -- ゴミ箱の一覧（既存の名）
POST   /api/trash/restore         {deletion_id}                -- ゴミ箱から戻す（**人だけ**）
POST   /api/deletions/{id}/purge  {confirm:true}               -- **いま消す**（保留領域の実体を今すぐ消す。**人だけ**）
POST   /api/deletions/{id}/advance {stage:2}
                                   -- **段 1 の行を後からアプリのゴミ箱へ移す**（**P10 で実装**。正は
                                   -- [`deletions-advance.md`](deletions-advance.md)。決定は §16.7）。
                                   -- **人だけ**（エージェントは 403 `human_only`）。`stage` は **2 だけ**
                                   -- （`true`・`1`・`3` は 422 `bad_stage`。**段 3 への直行は作らない**＝
                                   -- 置き場ごとの許可（`root.allow_stage3`）と凍結が要る既存の道のまま）
                                   -- 動きは**既存の段 2 と同じ道**（`_destination()` ＋ `move_no_clobber()`＝
                                   -- `os.rename` で `<data>/trash/<日付>/<ハッシュ>/` へ）。**上書きしない**
                                   -- （埋まっていれば 409 `target_exists`／別ボリュームは 409 `cross_volume`）。
                                   -- **台帳を先に書いてから動かし**、動かせなければ `_unadvance()` で段 1 に戻す
                                   -- （**「戻す」がそのまま効く**）。**いま登録されている行**を引くので
                                   -- **古い `asset_id` の行でも進められる**（`_target_for_advance()`）。
                                   -- **（P10 の監査 A-1）台帳の行が指す物かを必ず照合する**——
                                   -- **台帳の `size`** と**いまその場所を登録している枚**の両方を見て、
                                   -- 合わなければ **409 `different_file`**（「消した画像はもうこの場所に
                                   -- 無く、別の画像があります」＋「ファイルが無いので片付ける」の案内）。
                                   -- 実データの 6 行がこの形で、**別の画像 Y のファイルを移して
                                   -- 一覧から消していた**（`(size, mtime_ns)` の照合だけでは足りない）。
                                   -- **（P10 の監査 A-2）「戻す」は台帳の枚と、いまその場所に登録されて
                                   -- いる枚の両方の `deleted_at` を引き直す**（片方だけだと、戻したのに
                                   -- 実体のある枚が一覧から永久に消える）
                                   -- エラー: 409 `missing_file`（その行のファイルが無い）/ `different_file`
                                   --   （別の画像が在る）/ `changed`（登録した時と中身が違う）/
                                   --   `already_stage2` / `already_stage3`（もう進んでいる）/
                                   --   `already_closed`（片付け済み）/ `target_exists` / `cross_volume` /
                                   --   `not_registered`
POST   /api/deletions/advance      {ids:[...], stage:2}
                                   -- まとめて段 2 へ（**1 件ずつ同じ道**）。**1 回の上限は 200 件**——
                                   -- 超えたら 422 `too_many` で**1 件も進めない**（**人にも同じ規則**。
                                   -- **画面は 200 件ずつに分けて送る**）。断った行は理由つきで返す（**黙って捨てない**）
POST   /api/deletions/{id}/close   {reason:"missing"}
                                   -- **実体が無い行を終わりにする**（**P10 で実装**。`closed_at` / `close_reason`）。
                                   -- **人だけ**。**この行のファイルが、登録の場所・元の場所・アプリの
                                   -- ゴミ箱・一時置き場のどこにも無い**ことを確かめてから閉じる
                                   -- （**ファイルは 1 つも消さない・動かさない**。`asset.deleted_at` は
                                   -- そのまま＝**カタログに戻さない**）。`reason` は **`missing` だけ**
                                   -- （`CLOSE_REASONS`。`CHECK` にも入れた）
                                   -- **（P10 の監査 A-1 / C-1）「在る」ではなく「この行の画像が在る」を見る**
                                   -- （登録の場所は `asset_location.asset_id` が台帳の枚と同じで、
                                   -- 大きさも台帳の `size` と一致するときだけ数える。`to_path` /
                                   -- `hold_path` は 1 回の削除に固有なので在れば数える）。**別の画像を
                                   -- 「まだ在る」と数えると、実体がどこにも無い行を片付けられない**
                                   -- **（P10 の監査 C-3）段 3 の行は `purge_at` / `remaining_sec` も
                                   -- NULL にする**（タイマーから外す。`stuck` と同じ扱い）
                                   -- **（P10 の監査 B-2）`delete_request` に 1 行残す**（`kind: "close"`。
                                   -- 誰がいつ終わりにしたか。`stage` は対象の段）
                                   -- エラー: 409 `file_found`（この行のファイルがまだ在る。**生きている
                                   --   ファイルを片付けない**）/ `already_closed`（**片付けた後の `undo` も
                                   --   ここで断る**＝実体の無い枚をカタログに戻して「参照切れ」を並べない。
                                   --   **（P10 の監査 A-3）ファイルが戻ってきていれば、段 1 の行は開き直して
                                   --   戻せる**＝「実体が在り、登録も生きていて、大きさも台帳と一致する」
                                   --   ときだけ）/ `not_registered`
POST   /api/deletions/close        {ids:[...], reason}
                                   -- まとめて片付ける（**1 回の上限は 200 件**。超えたら 422 `too_many` で
                                   -- 1 件も片付けない）。**その行のファイルがまだ在る行は `file_found` で
                                   -- 断り、断った数を返す**。**（P10 の監査 B-2）1 回の呼び出しを
                                   -- `delete_request` に 1 行残す**（`kind: "close_many"`）。**（D-1）
                                   -- 既に片付いていた行は `replayed_count` に分けて返す**
POST   /api/locations             {asset_id, path, kind}       -- 場所を足す（**まだ無い**）
GET    /api/locations/missing     ?limit=500&include_deleted=0|1
                                  -- **参照切れの一覧**（**読むだけ**。**P8-6 で実装**）。`missing_at` が
                                  -- 立っている場所を切れた順（新しい順）に返す。**段 2・3 の削除も
                                  -- `missing_at` を立てる**（§5.8）ので、既定では消した物を外し、
                                  -- **外した数を `excluded_deleted` に数える**（`include_deleted=1` で出す）
                                  -- → {total, count, unlisted, excluded_deleted, include_deleted, limit,
                                  --     items:[{asset_id, key, path, display_path, size, mtime_ns,
                                  --       missing_at, last_seen_at, is_primary, sha256, review_state,
                                  --       has_provenance, deleted, active_deletion_id,
                                  --       other_live_locations, roots}], hint}（`limit` は 0〜5000）
POST   /api/locations/relink      {asset_id, path, mode:'exact'|'nearby', from_path?}
                                  -- 参照切れのつなぎ直し（**P8-6 で実装**。`docs/p8-6-relink.md`）。
                                  -- **人だけ**（エージェントは 403 `human_only`）。**中身の `sha256` が
                                  -- 一致しなければ 409 `hash_mismatch`**（`size` / `mtime_ns` は見ない。
                                  -- **pHash は使わない**＝似た別の絵を同じと見なさない）
                                  -- `exact` は `path` が**新しいファイル**、`nearby` は `path` が
                                  -- **探すフォルダ**（省略すると**2 段**で探す——①**その参照切れを
                                  -- 含む置き場** ②見つからなければ**残りの置き場**。**見つかった段で
                                  -- 止める**ので、実データの ComfyUI 出力（306 MB）は 1 段目で
                                  -- 見つかったときには歩かない。**P8-6 の監査 C-2**）。
                                  -- **設計 §0.11 の「同じルート内をファイル名で探す」は
                                  -- 空振りになる**ので範囲を広げた（実装の記録 §4.1-3）
                                  -- **ファイルは 1 つも動かさない**（`asset_location` の 1 行を
                                  -- `UPDATE` し、`location_history` に 1 行残す。`is_primary` は触らない）
                                  -- **二重登録の見直しは取引の中でもう一度やる**（`sha256` を読む間に
                                  -- 別の要求が同じパスを登録すると主キーに当たり、**壊れていない DB に
                                  -- 「バックアップから戻してください」と言っていた**。P8-6 の監査 C-3）
                                  -- → {relinked, moved, asset_id, sha256, from_key, from_path, to_key,
                                  --     to_path, mode, actor, at, size, mtime_ns, history_id,
                                  --     missing_left, kept:{decisions, tags, locations, has_provenance}}
                                  -- `nearby` は**歩いた範囲を返す**: `folders`（歩いた順）/
                                  --   `folders_skipped` / `found_in`（`given` / `home` / `rest`）/
                                  --   `scope` / `searched` / `also_found` / `unreadable` /
                                  --   `candidates_truncated`（上限 200 は**段ごと**。**黙って捨てない**）
                                  -- エラー: 409 `hash_mismatch`（`exact` も `nearby` も）/ `path_taken` /
                                  --   `already_registered` / `deleted`（消した物は繋がない。`undo` を案内）/
                                  --   `ambiguous`（1 枚が 2 か所以上で切れているときは `from_path` が要る）/
                                  --   `unreadable` / `not_missing`（既に繋がっている）/ `not_registered`。
                                  --   404 `not_found`（指定したファイル・フォルダ・同じ名前が無い）。
                                  --   422 `bad_request` / `bad_path` / `bad_mode` / `bad_scope`
                                  --   （`nearby` で置き場が 1 つも無く `path` も省いたとき）

# 走査と置き場（P8）
GET    /api/scan                  -- 走査中かどうか（**読むだけ**。{scanning, started_at, elapsed_sec}）
                                  -- `scan_guard()` は削除と取り消しを**待たせる**（409 は返さない）
GET    /api/roots                 -- 登録した置き場（`id` は正規化した鍵）と **allow_stage3**。**読むだけ**
POST   /api/roots/{id}/allow-stage3 {allow:true|false}         -- **段 3 を許す印**（**人だけ**。Q8）
                                  -- **scan で新しく増えた置き場は印なし**で入る（段 1・2 まで）

# バックアップ（P8-4）
POST   /api/backup                {include_library:false, out?}
                                  -- **いま 1 回取る**（必ず新しく取る＝`<YYYYMMDD>-<HHMMSS>/`）。
                                  -- **画面のボタンの語は「取り直す」**（P8-5 で `frontend-design.md` §6 を正として統一した）。
                                  -- 自動の日次は同じ日なら取らない（30 秒ごとに「今日の分が無ければ取る」）
GET    /api/backup                -- 直近のスナップショット・最後に取った時刻・置き場・次の予定・`last_error`
GET    /api/health/db             ?full=0|1
                                  -- `quick_check` / `integrity_check` と**読み取り専用かどうか**
                                  -- （**例外も「壊れている」に数える**。既定は full=1）
POST   /api/backup/restore        {path, force:false}          -- **作らない**（**復元は CLI**。点検 G8）
GET    /api/settings              -- 設定。**いまの `PATCH` が受けるのは `backup_dir` だけ**
PATCH  /api/settings              {backup_dir}
                                  -- **人だけ**。**その場で形を見る**（相対パス・ファイル・無いドライブ・
                                  -- `<data>` の中は 422 bad_backup_dir）
                                  -- 既定は `<data>` の外（`%USERPROFILE%\image-reviewer-backups`。§15 リスク 11）
                                  -- ComfyUI・タガー・閾値・テーマなどの設定は DB に在るが、**変える口はまだ無い**

# ComfyUI の監視（生成の瞬間の値を捕まえる）
POST   /api/comfyui/watch         {enabled, base_url, output_dir}   -- 必要なときだけ手で開始
GET    /api/comfyui/status
POST   /api/comfyui/rescue-history                                  -- 今の /history から取りこぼしを拾う

# 進行（Server-Sent Events）— **まだ無い**（P5-0 / P5-1 / P5-2 では入れていない。点検 C16）
GET    /api/events                -- 走査・ハッシュ・サムネ・タグ付け・訳・監視の進み（未実装）
                                  -- いま画面は、判断の応答（`reopened_group_ids` など）を使って自分で組み直す
```

**自分から出るのは ComfyUI と、利用者が貼った URL の取得だけ。** 他のツールへ送る口も、
他のツールから構造を読む口も作らない（§18。点検 A1）。

**DB の例外の語彙（P8-6 の監査 D-8・P9 の監査 D-1 / D-2。`api/__init__.py` の 1 か所）**:
`sqlite3.DatabaseError` は `IntegrityError` / `OperationalError` の**親**なので、**例外のクラスでは
分けられない**。SQLite の**文言**で 4 つに分ける。

| 文言 | 番号 | `code` | 意味と案内 |
| --- | --- | --- | --- |
| `malformed` / `not a database` / `corrupt` / `encrypted` | 503 | `read_only`（読み取り専用で起動中）／`db_error` | **壊れている**。バックアップから戻す |
| `disk i/o error` | 503 ＋ `Retry-After: 5` | `io_error` | **一時的な読み書きの失敗**（USB の抜け・ウイルス対策の掴み）。**もう一度。復元は勧めない** |
| `database is locked` / `busy` | 503 ＋ `Retry-After: 1` | `busy` | **混んでいる**（`busy_timeout` 15 秒の後）。**もう一度** |
| それ以外（`unable to open database file` / `IntegrityError` など） | 500 | `sqlite_error` | **壊れているとは限らない**内部エラー。**復元を勧めない** |

**画面（上部バー）は `code` で見分ける**——`read_only` / `db_error`／`code` なし だけを
「読み取り専用です」にし、`io_error` / `busy` は「バックアップに失敗しています」に出す
（一時的な物を復元の話に写さない。`badge.js` の `isReadOnlyStatus()`）。

### 6.2 外部参照の契約（R5c）

他ツールが読む口は**2 つだけ**に絞る。どちらも同じ形。

1. `GET /api/export/review.json` — REST。クエリで範囲を絞れる。
2. `<data>/export/review.json` — 同じ内容をファイルにも書く（サーバを立てずに読める）。

契約は [`schemas/review-export.schema.json`](../schemas/review-export.schema.json) に JSON Schema（draft 2020-12）で固定する。

**P8 で足した契約は 1 つだけ**: [`schemas/backup-manifest.schema.json`](../schemas/backup-manifest.schema.json)
（日次スナップショットの `manifest.json`。版・作った時刻・件数・含めた範囲・DB の `sha256`。
**`restore`（CLI）が復元の前に自分で読む**。`abi` は `0.1` のまま＝足すだけ）。決定は §16.6。

**`review-export.schema.json`（`review.json`）は P8 で変えていない。** 段 1〜3 で外した資産も**判断つきで出し続ける**
（実体が無いことは既存の `missing` で表せるので欄が要らない）。**「足していない」ことはテストで固定してある**
（`p8-design.md` §6.1・§6.3）。**`deletion-ledger`（`deletions.json`）は作らない**
（人が読む台帳は `review.json` と `deletion_log` で足りる。点検 G8）。

外部契約として守る性質:

- **`schema` / `abi` を持つ。** 形を変えるときは `abi` を上げる。読む側は `abi` で分岐できる。
  `0.1` は設計段階（未実装）なので、実装までの変更では版を上げずに直す。
- **決定的に並ぶ。** キーも配列も安定した順に出す。他ツールがハッシュで差分を取れる。
  **決定性の確認は `generated_at` を除いて行う**（時刻を含めると必ず不一致になる。§14 のテスト方針）。
- **ID は安定。** `asset_id` はこのツール内で不変。取り込み元がある場合は `external_ref` に元の ID を残す。
- **`review_state` は 3 値**（`unreviewed` / `kept` / `rejected`。画面の言葉は 未判断 / キープ / ボツ）。
- **理由は `reason_code_id` と `label` の両方**を出す（ID は機械用、ラベルは人用）。
- **`note` は自由文**。無い場合は `null`（空文字にしない）。
- **パスは既定で出さない。** `include_paths=true` のときだけ `path_map` を付ける（他ツールが実ファイルを開く場合）。

**要求（R10）も契約に入れる（点検で見つかった不足）。** 任意の `requests` 配列として出す:

- `state`（`open` / `done` / `declined` / `superseded`）、`ask`、`conditions`、`origin`、`wants`
- `ai`（`pick_asset_id` / `note`）＝ AI の下書き判断
- `response`（`selected_asset_ids` / `reason_code_id` / `reason_label` / `note` / `annotations`）＝ 人の結論
- `created_at` / `closed_at` / `closed_by` / `decline_note` / `superseded_by`
- `target_key`（任意。同じ対象かをエージェントが決めるための鍵。§9.6）

**任意**にしてある（判断だけを読むツールが `requests` 無しでも読めるように）。
`GET /api/export/review.json?scope=request:<id>` で要求 1 件に絞れる。
エージェントは API をポーリングするのが主だが、**ファイルを読むだけでも要求の結果が分かる**ようになった。

**画像の種別（`kind`）も入れる（点検 G3 で確定）。** `generated` / `reference` / `photo` の 1 つの列挙。
エージェントが「自分の生成物だけ」を絞れる。後から足すと `abi` を上げる理由が増えるので、今のうちに入れる。

**大きさを抑える（点検 B4）。** 書き出しの契機と中身を次に絞る:

| 契機 | 範囲 | 中身 |
| --- | --- | --- |
| 判断のたび（既定 ON・遅延つき） | **その判断が影響したまとまりのファイルだけ**（`<data>/export/groups/<group_id>.json`） | 判断・理由・まとまりの結論 |
| 手動（`POST /api/export/review.json`） | 指定した範囲 | 指定による |
| 日次 | 全部（`<data>/export/review.json`、別に `<data>/export/index.json` の件数索引） | 判断・理由・まとまりの結論 |

- **`tags` と `prompts` は既定で出さない**（`include_tags` / `include_prompts`。既定 `false`）。
  1 万枚で 100 MB になり、判断のたびに書き直すと §12.1 の「判断の記録 100ms」が守れない。
  他ツールが要るときだけ明示的に頼む。
- 全件の書き出しは**判断のたびにはやらない**。`generated_at` を除いた決定性の確認は手動の書き出しで行う（§14）。

書き出しはどれも、`<data>/export/` 直下の**一時ファイル → `os.replace`** で原子的に置き換える
（読む側が壊れた JSON を見ない）。

### 6.3 ローカル限定の守りと、「実行しない」の意味

#### 6.3.1 認証は入れない。代わりに Host と Origin を検査する（点検で見つかった穴）

利用者の回答は「制限なし」（ローカル前提）。だが**認証が無いまま 127.0.0.1 に口を開けると、
ブラウザ経由で外部から叩ける**。DNS リバインディングを使えば、悪意あるページの JavaScript から
`http://127.0.0.1:8790/api/locations` に `DELETE`（段 3＝実削除）を投げられうる。
「ローカルだから安全」は成り立たない。**認証は入れないが、次は必ず入れる:**

1. **`Host` の検査**: `127.0.0.1:8790` と `localhost:8790` 以外を **403** で断る。
   これで DNS リバインディング（攻撃者のホスト名で解決させる）を弾ける。
2. **`Origin` の検査**: 付いている `Origin` が自分自身でなければ、**状態を変える要求を 403** で断る。
3. **`Content-Type: application/json` と独自ヘッダを要求する**（状態を変える要求）。
   `application/json` を跨オリジンで送るには事前確認（preflight）が要り、独自ヘッダも同じ。
   単純要求で送れる `text/plain` や form は**受け付けない**。
4. **`GET` は状態を変えない。** 削除・判断・走査の開始はすべて `POST` / `DELETE` にする
   （`GET` で消せる口を作らない）。
5. 画面（同一オリジン）は 2 と 3 を自然に満たす。エージェントは `Origin` を付けずに叩ける
   （`Host` と `Content-Type` は満たす）。

> **点検で見つかった穴**: 当初は「認証なし」だけを書いていた。上記 1〜4 を §6.3.1 として明記した。

#### 6.3.2 「生成を実行しない」の正確な意味

利用者の回答は「このツールは生成を実行しない」。これは**画像の生成**を指す。ComfyUI の `/prompt` は使う。

| 何を | 実行するか | 使う口 |
| --- | --- | --- |
| 画像の生成（txt2img / img2img / 差分） | **しない。** 書き出したグラフを利用者が自分で投入する | — |
| タグ付け | **する** | `/prompt`（`IllustTagger` または WD14 ノード） |
| 訳し直し（英訳・タグの語釈） | **する** | `/prompt`（`TextGenerate`） |
| 監視（生成の瞬間の値と結果の取り込み） | **する** | `/api/jobs`、`/history` |
| グラフの取得・設置・検査 | **する** | `/api/userdata`、`/object_info`、`/experiment/models` |

この区別を**文書でも言葉で明確にする**（点検で「実行しない」の記述と `/prompt` の記述が
正面衝突していると指摘された。意図は上表のとおりで、文言が足りていなかった）。

---

## 7. 画像メタデータ戦略

### 7.1 PNG の読み方（速く）

**ファイル全体を読まない。** PNG のシグネチャ → `IHDR` → チャンクを順に走査し、
`tEXt` / `zTXt` / `iTXt` を拾って `IEND` で止める。**上限 256 KiB** で打ち切る。
チャンクは `長さ(4) + 種別(4) + データ(n) + CRC(4)` = **`12 + n` バイト**進む（CRC を忘れると全部ずれる）。

**実測（`ComfyUI\output` の 1,028 枚、読み取りのみ）:**

| 項目 | 実測値 |
| --- | --- |
| メタデータが入っている位置 | **ファイル先頭 22,178 バイト以内**（最大値）。全 1,028 枚で `prompt` を取得できた |
| `workflow` を持つ画像 | 1,028 枚中 **175 枚**（UI から実行したもの。残りは API 生成） |
| 解析速度 | 256 KiB 上限で **24,719 枚/秒** → 1 万枚で **0.4 秒** |
| 同・8 MiB 上限 | 9,726 枚/秒 → 1 万枚で 1.0 秒 |

→ メタデータ抽出は**性能上の問題にならない**。上限は 256 KiB で十分（余裕を 10 倍見ている）。

- PNG: 上記のとおり。壊れたチャンク（長さが異常）に当たったら、そこで止めて
  「読めなかった」として記録する（黙って空にしない）。
- JPEG: EXIF を読む。tEXt 相当が無いため**グラフは残らない見込み**（未検証、`metadata-findings.md` §6）。
  取れた範囲だけ出し、「グラフは取得できません」と画面に出す。
- その他の形式: 寸法と形式だけ。

### 7.2 日本語原文（R4b の前半）

取得の優先順:

| 優先 | 取得元 | `ja_source` |
| --- | --- | --- |
| 1 | `prompt` の `PrimitiveStringMultiline.value` が**リテラル** | `png_primitive` |
| 2 | `workflow`（UI 形式）の該当ノードの `widgets_values` | `workflow_node` |
| 3 | sidecar（`texts.json` など。あれば） | `sidecar` |
| 4 | 画面からの手入力 | `manual` |

判定は「CJK 文字を含むか」だけでは行わない。`TextGenerate` ノードの存在、
および `PrimitiveStringMultiline` が `TextGenerate` の入力に繋がっている**グラフ上の関係**で見る。
（CJK の有無は補助。英語の原文を日本語欄に出さない。）

### 7.3 英訳（R4b の後半。ここが設計の要）

**英訳は 3 種類あり、混ぜてはいけない。** 画面でも区別して出す。

| 種別 | `en_source` | `en_is_rederived` | 意味 | 取得方法 |
| --- | --- | --- | --- | --- |
| 原文（リテラル） | `png_literal` | 0 | PNG にリテラルで入っていた最終プロンプト | `CLIPTextEncode.text` がリテラルのとき |
| **生成時に捕獲** | `comfyui_history` / `sidecar` | 0 | **そのとき実際に使われた訳** | 監視で `/history` の**テキスト出力**を捕まえる（§7.3.1） |
| 訳し直し | `textgenerate` | **1** | 後から訳したもの。**当時の訳ではない** | `TextGenerate` を再実行（§7.3.2） |
| 手入力 | `manual` | 0 | 利用者が入れた最終プロンプト | 画面 |

- 訳し直しの値には画面で**「訳し直し」バッジ**を出す。原文と同格に見せない。
- 訳し直しても `ja_text` は**上書きしない**。日本語原文は常に PNG の値が正。
- 利用者が訳を直せるようにし、その場合は `en_source='manual'` / `en_is_rederived=0` とする。

#### 7.3.1 生成時に捕まえる（今後の画像を救う）

**実機で確かめた形（2026-10-15 に実測して確定）:**

`GET /api/jobs/{prompt_id}`（または `/history/{prompt_id}`）の `outputs[node_id]` に
**`text` が入る**。ただし次の 3 点を守らないと間違える。

1. **`outputs[node].text` は文字列ではなくリスト。** 実測は `{"11": {"text": ["..."]}}`（要素 1 つ）。
   先頭を取る。複数あれば全部持つ。
2. **それが翻訳であることを、グラフで確かめる。** 実測した実行では
   `node 11 = PreviewAny` の `inputs.source = ["9", 0]`、`node 9 = TextGenerate` だった。
   この**由来が `TextGenerate` に辿れるときだけ** `en_text` として採用する。
   辿れないテキスト出力は `text_probe`（由来不明のテキスト出力）として別に残し、**`en_text` にしない**。
   ノードの並びは実行ごとに変わりうるので、**番号ではなくグラフの結線で判定する**。
3. **捕獲値は「最終プロンプト」ではない。** ja2en の経路は
   `TextGenerate` → `StringConcatenate`（品質語を前置）→ `CLIPTextEncode` なので、
   実際にモデルへ渡った文字列は `string_a + delimiter + 捕獲値`。
   これを**再構成**して `final_prompt`（`final_prompt_source='reconstructed'`）として別に持つ。
   捕獲値（`en_text`）と最終プロンプト（`final_prompt`）を混同しない。
   実測例では `string_a = "(masterpiece, best quality, good quality, score_9), safe,"`、
   `delimiter = "\n\n"` だった。

処理の流れ:

- 監視を有効にすると 2 秒ごとに `/api/jobs`（無ければ `/history`）を見る。新しい `prompt_id` があれば
  **`GET /api/jobs/{prompt_id}` を 1 回叩く**（API グラフ・UI グラフ・`outputs`・状態が 1 回で揃う）。
- `outputs[*].images[*]` の `filename` / `subfolder` / `type` から実体を特定し、未登録なら `asset` として登録する。
- 上記 1〜3 の手順で `en_text` と `final_prompt` を決めて保存する。
- 同じ内容を `<data>/sidecar/<sha256>.json` にも書く（DB を作り直しても来歴が残る。
  `duplicates-deletion-backup.md` §5.1 で「PNG から取り直せない唯一のもの」と位置づけている）。
- `prompt[3].extra_pnginfo.workflow` があれば UI 形式のグラフとして保存する。
- **逃した分の救済**: `POST /api/comfyui/rescue-history` で今の `/history` を走査する。
  ただし**既に登録済みの画像の値を埋めるだけ**で、**新しい画像は登録しない**（点検 A3 で確定）。
  利用者の回答は「監視は必要なときだけ手で開始」なので、起動のたびに勝手に取り込んではならない。
  新しい画像の登録は、監視を手で開始したときだけ行う。ComfyUI につながらないときは黙って飛ばす。
  （プロトタイプの `capture_history` は既にこの振る舞いになっている。設計を実装に合わせた。）

これは `POST /prompt` だけで生成された画像（UI 形式のグラフを PNG に持たないもの）でも効く。
**生成側のアプリに変更を要求しない**のが利点。

> **点検で誤りを正した記録**: 別の点検者が「捕獲値は翻訳ではなく VLM の画像説明だから捕獲は使えない」と
> 指摘したが、**実機で確かめた結果それは誤り**だった。日本語原文（例: 「背景に催眠のハートのエフェクト…」）が
> 情景説明なので、その訳である英文も説明文の形になるだけである。
> ただし**リストであること**と**最終プロンプトではないこと**の指摘は正しく、上の 1 と 3 に反映した。

#### 7.3.2 訳し直し（既存画像のため）

- **`TextGenerate` を再実行**する。これは ComfyUI の `/prompt` を使う（§6.1 の `retranslate`）。
  **画像の生成は実行しないが、訳し直しとタグ付けには ComfyUI を使う**（この区別は §6.3 に書く）。
- 同じ `system_prompt`・同じモデルを使うので当時の訳に最も近い。
  短文で約 1 秒、3 コマで 3.6〜4.2 秒（RTX 3090・8B int8 の実測。**未再計測**）。
- 翻訳の決まり（`system_prompt`）は**設定ファイルで持ち、コードに埋め込まない**。
  既定の文面は実機で使われていたものを初期値として置く。
- 使った模型を `en_engine` に必ず残す。
- **Ollama（127.0.0.1:11434）は今回使わない**（利用者の回答）。動いてはいるが実装しない。
  `en_source` に `ollama` を残すかどうかは未決（§16.2）。

### 7.4 ワークフローへのリンク（R4a）

> **実機で確認して当初案を訂正した（2026-10-14）。**
> ComfyUI のフロントエンドは **API 形式 JSON をそのまま読める**。
> `app.ts` の `handleFile` が `isApiJson()` で判定し、`loadApiJson()` が API → UI の変換
> （`LiteGraph.createNode` → ウィジェット復元 → `rootGraph.arrange()`）を行う。
> D&D でも「Open」ボタンでも同じ経路。→ **自前で UI 形式へ変換する必要はない。**
> 詳細は [`workflow-reproduction.md`](workflow-reproduction.md) §2・§3。

URL で名前付きワークフローを開く手段が無いため、次の順で提供する。

| 画像の状態 | 提供するもの |
| --- | --- |
| `workflow` チャンクあり（UI 実行。実測 1,028 枚中 175 枚） | `GET /api/assets/{id}/graph?format=ui` で**そのまま**ダウンロードして D&D。位置・グループまで復元される |
| `prompt` のみ（API 生成） | **API 形式のまま**ダウンロードして D&D。グラフは完全、**配置は自動**（`arrange()`） |
| 何度も開きたい | `POST /api/assets/{id}/graph/install` で `user\default\workflows\` に置く。**UI 形式のときだけ**（API 形式を置いてもサイドバーからは開けない）。`overwrite=false` で既存を壊さない |
| グラフが無い（JPEG 等） | 「来歴なし」。生成パラメータだけを表で出す |

- 画面には「ComfyUI を開く」（`http://127.0.0.1:8188` を開くだけ）、「JSON を保存」、「ComfyUI に置く」の 3 つを出す。
  D&D の手順も 1 行で添える（**開く URL が無いことを利用者に隠さない**）。
  `?template=` は存在するが同梱テンプレート専用で、利用者のワークフローには使えない。
- `graph.install` は `POST /api/userdata/{file}`（body は生バイト列、`overwrite=false` で 409）を使う。
  失敗しても「JSON を保存」で目的を果たせるようにする（fail-soft）。
- 再現（同じ条件で作り直す）は [`workflow-reproduction.md`](workflow-reproduction.md) で設計する。

---

## 8. タグ（R3 / R7）

### 8.1 出所を混ぜない

タグは出所つきで保持する（`asset_tag.source`）。

| 出所 | 意味 | 画面 |
| --- | --- | --- |
| `png` | PNG のプロンプトから語を切り出したもの | 生成に使った語として出す |
| `wd14` | タガーが画像から読んだもの | 確からしさ（`score`）付きで出す |
| `manual` | 利用者が付けたもの | 印を付けて出す |

**同じ `tag` 行を共有し、`asset_tag` で出所ごとに行を持つ。** 検索は「語がある」で効き、
画面では出所で分けて見せられる。

### 8.2 実行方式（利用者の選択: 内蔵を既定、ComfyUI も可）

| 方式 | 長所 | 短所 |
| --- | --- | --- |
| `builtin`（既定） | ComfyUI の起動が要らない。バッチが速い。モデルを自分で選べる | GPU を ComfyUI と共有する。`onnxruntime-gpu` の導入が要る |
| `comfyui` | 既に動いている環境なら追加導入なし。`IllustTagger` がスコア付きで返す | ComfyUI の起動が必須。生成中は VRAM が競合する |

- 内蔵方式は `ComfyUI-WD14-Tagger\models\<model>.onnx` / `<model>.csv` を読む。
  **設定で明示パスを指定できるようにする**（kohya 側は `model.onnx` という命名で、
  自動探索では見つからない。findings §4）。
- 前処理は WD14 の作法に従う。**P4 で確定した（9 手順。実行で ComfyUI と 66/66 語の一致を確認。
  `docs/p4-design.md` §0.6 が正）**: 長い辺を `model.get_inputs()[0].shape[1]` に合わせて縮小（**`int()`**。
  `round` だと縦長の画像で語が変わる）→ **白（255）で正方形にパディング** → `float32` の **0〜255** のまま
  → **RGB → BGR** → CSV の行順から `category == "0"` の最初の行を general、`"4"` の最初の行を character として切る
  → rating は捨てる → `all = character + general`。**1 つでも変えると語が変わる**（BGR にしないと 14 語ずれ、
  0〜1 に正規化するとほぼ全滅）。
- 閾値の既定は `general 0.35` / `character 0.85`（このツールの初期値。画面で変えられる）。
  `IllustTagger` の既定は 0.2 だが、**呼ぶ側で決められる**のが実測で分かっている。
- バッチは背景ジョブ（**P4-1 で実装。ワーカー 1 本**）。
  `CUDAExecutionProvider` が使えなければ `CPUExecutionProvider` へ落ちる。**黙って落ちる**ので、
  **実際に使われた provider を起動のログ（`doctor` 相当）に出す**（P4 の点検 B-2。GPU で 0.063 秒/枚、
  CPU で 0.75 秒/枚と 12 倍違う）。
- **速さの目安（P4 で測り直した。「同じ画像の再投入」は `execution_cached` に当たるので別々の画像で測る）**:
  **内蔵 GPU 0.063 秒/枚（1 万枚 約 11 分）**／内蔵 CPU 0.75 秒/枚（約 2.1 時間）／
  **ComfyUI の `IllustTagger` 0.27 秒/枚（約 45 分。スコアも返る）**／
  ComfyUI の `WD14Tagger` 2.8〜3.4 秒/枚（**約 8 時間。スコアを返さない**。呼ばれるたびに 1.2 GB を読む）。
  前の版の「0.5 秒/枚・1 万枚 1.5 時間」は**キャッシュに当たった値**だった（P4 の点検 A-4）。
  中断・再開できるようにする（`asset_tag` に既にある語は飛ばす、`job_item` に失敗を残す）。
- **ComfyUI 経由では画像を `POST /upload/image`（`type=temp`）で複製してから渡す**（`LoadImage` は
  `input/` の一覧しか受けない。P4 の点検 A-2）。名前は `<asset_id>-<sha256 の先頭 8>`（中身が変わったら
  名前も変える＝キャッシュ事故を避ける）。**付け終わったら消す**（設定 `tagger.comfyui_temp`）。
- **この環境の既定（利用者の決定 2026-10-16）**: **ComfyUI を優先する**。
  `settings` の `tagger.engine = comfyui`・`tagger.node = illust` を入れてある。
  理由: **内蔵は CPU 版しか入っていない**（`onnxruntime 1.31.0`。`providers` は CPU だけ）ので
  **1.30 秒/枚**、**ComfyUI の `IllustTagger` は 0.27 秒/枚**（実測）。1 万枚で 2.1 時間 対 45 分。
  **`onnxruntime-gpu` ＋ CUDA の DLL** を入れれば内蔵が最速（0.063 秒/枚・約 11 分）になるので、
  そのときは `tagger.engine` を `auto`（内蔵優先）に戻す。
  `auto` のままでも、内蔵が入っていれば内蔵が選ばれる（設計の既定は変えていない）。
  なお **`IllustTagger` と WD14 は別の模型**なので、**語の集合は完全には一致しない**
  （どの模型で付けたかは `asset_tag.model` に残る）。

### 8.3 タガーの限界を画面に書く

実測で分かっている弱点（findings §4）: 人数・性別は概ね当たるが、**距離は腿までが弱く、
手の破綻の語は出ず、`straight-on` は語として出ない**。
「タガーは下ごしらえで、最終判断は人」と画面に明記する。
機械が付けた印は**下書き**として扱い、自動でキープにはしない。

### 8.4 日本語の語釈（R3。利用者の「日本語で表すとどうなるか知りたい」への答え）

タグは英語（Danbooru の正式名）で持ち、**日本語の語釈を別に持つ**（`tag_gloss`）。

- 画面では **2 行**で出す（1 行目 英語 / 2 行目 日本語）。**括弧書きは使わない**（利用者の指定）。
  書体を変えて対にする（[`frontend-design.md`](frontend-design.md) §2.3）。
- 訳すのは **ComfyUI の `TextGenerate`**（利用者の回答）。訳し直しではなく**語釈**なので、
  当時の値との区別は要らない。
  - **P4-2 で確定した頼み方**: **`1. 1girl` の形で番号を振って 1 行ずつ**頼み、返った行を
    **`^(\d+)[.)]\s*(.+)$` で番号に対応**させる（**位置で対応させると崩れる**。実測で 6 回中 2 回しか
    行数が合わず、合った回も `1girl` が「男の子」になった）。**保存するのは「番号が取れた」かつ
    「かな・漢字を含む」行だけ**。取れなかった番号だけ 1 語ずつ訳し直す。
    **`sampling_mode` は `off`**（決定的。2 回同じ出力）。**まとめて頼むのは 20 語まで**。
    模型は `qwen3vl_8b_int8_convrot.safetensors`（`CLIPLoader(qwen_image)` → `TextGenerate` →
    **`PreviewAny` を繋ぐ**）。詳しくは `docs/p4-design.md` §0.9。
- **見えた語だけ訳す**（遅延）。タガーは 1 万枚で 40 万語程度になるため、先に全部は訳さない。
- 一度訳したら `tag_gloss` に保存して使い回す。**人が直せる**（`edited=1`）。
  `edited=1` の語は訳し直しで上書きしない。
- 訳の粒度は「タグ用語として通る日本語」（`1girl` → 「女の子1人」）。直訳調にしない。
  ただし**訳の質は模型任せ**なので、画面には「訳は自動」であることを示し、直せる導線を必ず出す。

---

## 9. レビュー（キープ / ボツ）

### 9.1 用語と粒度

| 語 | 意味 | DB / 契約の値 |
| --- | --- | --- |
| **キープ** | **気に入ったもの。** 作品で実際に使うかは別（利用者の回答） | `kept` / `keep` |
| **ボツ** | 落とす。理由を付ける | `rejected` / `reject` |
| 未判断 | まだ見ていない | `unreviewed` |
| 取り消し | 判断を外して未判断に戻す | `clear` |
| まとまり | レビューの単位。複数枚から 1 枚（または複数）を選ぶ、もしくは全部ボツ | `review_group` |
| 要求 | エージェントが「これを見て決めて」と出すもの（§9.6） | `review_request` |

- **判断は台帳に追記のみ**。現在値は `asset.review_state` にマテリアライズする（読み取りの高速化）。
- **軸は 1 つ**（キープ / ボツ）。「気に入った」と「作品で使う」を分ける 2 軸目は、
  必要になったら足す（利用者の回答: 今は 1 軸）。
- **数値の点数（星）は入れない**（利用者の回答）。段階が要るようになったら、
  `reason_code` の拡張として後から足せる形にしておく。

### 9.2 理由マスタ

利用者が編集できる。初期値は**利用者が選んだもの**をそのまま置く。

```text
キープ: 意図どおり / 気に入った / これで仕上げる
ボツ: 人数・人物が違う / 構図・アングルが違う / 意図・場面と違う /
      雰囲気・絵柄が違う / 服装・小物が違う / キャラが違う（別人化） /
      破綻（体・関節・結合） / 表情が違う / その他
```

- **「同じまとまりに良いものがある」は入れない。** 利用者が選ばなかったため。
  まとまりの中で選ばれなかった枚には、**その枚自身の理由**を付ける
  （「他の枚が良かったから」ではなく、その枚が何で落ちたかを書く）。
  どうしても一律で流したいときのために `pick_one` の既定理由を 1 つ用意するが、
  既定では**未選択にして理由を選ばせる**。
- `builtin=1` の行は消せない（`active=0` にはできる）。**語彙は利用者のもの**で、設計時に固定しない。

### 9.3 まとまりのレビュー（R6）

画面の詳細は [`frontend-design.md`](frontend-design.md) §4 と §11 にある。設計として決めること:

- **1 枚選ぶ仕事なので、選ばれた 1 枚を大きく出す**（フィルムストリップ＋大きな 1 枚）。
  等分に並べるのは比較の画面（§9.3.1）でやる。**同じことを 2 つの画面でやらない。**
- 枚数の**上限は置かない**（点検 B6/G8 で確定）。番号キーは「**いま見えている 8 枚**」に割り当て、
  9 枚以上あるときは `←` `→` で送って見えている範囲の番号を押す。
  当初「上限 8（番号キーと対応）」としていたが、番号キーは**補助**（利用者の回答）なので、
  補助の都合で要求の枚数を制限するのは筋が通らない。**要求は 12 枚でも 20 枚でも受け取れる**。
- 9 枚以上のときは、まとまりの中を**スクロールする 1 列**として出し、選択中が常に見えるようにする。
- 各枚の下に生成パラメータ（seed / steps / cfg / LoRA / モデル）を出す。
  「同じ seed で 1 枚だけ違う」を見つけられるようにする。
- 決定は 1 トランザクションで「台帳 → 現在値 → 書き出し（遅延）」まで進める。
- 全部ボツでも**理由を必ず付ける**。理由の選択を飛ばして決定できないようにする。

#### 9.3.1 比較（R6 の補助）

比較は [`comparison.md`](comparison.md) で設計する。要点:

- 使う見方は 5 つ（**並べる / 来歴の差分表 / 差分ヒートマップ / 同期ズーム・パン / 似ている順**）。
- 点滅・スワイプ・重ねるは**今回作らない**が、後から足せる拡張点を用意する（`comparison.md` §9）。
- **来歴の差分表を既定で出す。** 「何が違うか」を読むのが最も安く効く。

### 9.4 他ツールからの参照（R5c）

- 読み取りは §6.2 の 2 経路（REST / ファイル）。**書き込みの口は作らない**
  （他ツールが判断を書き換えると台帳が壊れる。エージェントも判断は書けない。§9.5）。
- 書き出しには**キープされた画像の一覧**と**まとまりごとの結論**が両方入る。
- `GET /api/export/review.json?scope=group:<id>` のように範囲を絞れる。
  全件（`scope=all`）は大きくなる（1 万枚・タグとプロンプト込みで 100 MB 規模）ので、
  **判断のたびに更新するのは影響したまとまりだけ**にし、全件は手動と日次にする（§6.2。点検 B4）。
  `tags` と `prompts` は既定で出さない。

### 9.5 誰の判断か、AI の下書き

- `actor` は `human` / `agent` の自己申告。ヘッダ `X-Image-Reviewer-Actor` を見る（無ければ `agent`）。
  **人の画面は必ず `human` を付ける。** 認証は無い（利用者の回答: 制限なし。ローカル前提）。
  「人が判断した」ことの強制は認証が入るまで完全ではない、と割り切る。
- **エージェントは判断を書けない（点検 A5 で確定）。** 判断を書く口（`POST /api/reviews`、
  `POST /api/groups/{id}/decide`）は **`human` 以外を 403** で断る。
  エージェントの入口は **`POST /api/review-requests` の `ai_pick_asset_id` / `ai_note` だけ**。
  理由: 台帳に書いた判断は現在値（`review_state`）に写るので、エージェントが `keep` を書いた瞬間に
  「キープ済み」になり、決定の「**自動でキープにしない**」「人が確定する」と正面から衝突する。
  他ツールが契約の `decided_by` を読んで「人が見ていない画像をキープ済み」と扱う事故も防ぐ。
- 未判断の画像にエージェントの推しを付けることは自由（`review_request` に残る）。
  人の判断と **両方を残す**（利用者の回答）。**AI の下書きは自動でキープにしない。**
  人が押すまでは未判断のままにする。
- **削除と取り消しは人とエージェントの両方**（**P8。利用者の回答 Q1・Q2**。§16.6）。**「判断（`decision`）は人だけ」は変えない**
  ——削除の台帳（`deletion_log`）は判断の台帳と**別物**である。
  - **`actor` を必ず残す**（`deletion_log.actor` に `human` / `agent`。**語彙外は 422**）し、**画面にも「誰が消したか」を出す**。
  - **窓（実削除の 5 分）は誰でも同じ**。**エージェントは 1 回の要求で 200 枚まで**
    （超えたら **422 `too_many` で 1 枚も消さない**＝部分適用しない。**人に上限は無い**。preview が件数と合計バイトを見せるのが守り）。
  - **取り消しもエージェントに許すが、自分が消した物だけ**（他人の分は **403 `not_yours`**）。
    **人は誰の削除でも戻せる**（導線を出しておいて戻せないのでは「人が気づいて戻す」が成り立たない）。
    **別名で戻す（`as_copy`）は人だけ**（**403 `human_only`**）。
  - **除外・ゴミ箱からの復元・バックアップ・設定は `human` だけ。** `require_human()` は**1 か所のまま**にして、
    **削除の 3 口と自分の分の `undo` だけ**を開ける（**後で「人だけ」に戻すのは 1 行**）。

### 9.6 エージェントからの要求（R10）

エージェントが「この画像群を見て、どれにするか決めて」と求める仕組み。

```
POST /api/review-requests
{
  "asset_ids": ["...", "..."],          -- 画像（パスでも登録済み ID でも受ける）
  "target_key": "cut-20261011-031201",  -- 任意。同じ鍵の未対応があれば差し替える（G2）
  "policy": "pick_one",                 -- 1 枚 / 複数 / 全部ボツのみ
  "ask": "この 8 枚から 1 枚選んでほしい",
  "conditions": ["左手の形", "背景の窓の位置"],   -- 何をもって良いとするか（自由文）
  "origin": "作品A / カット03",           -- どこから来たか（自由文）
  "wants": ["selected_ids", "reason", "annotations"],  -- 応答に求めるもの
  "ai_pick_asset_id": "...",            -- AI の下書き判断（任意）
  "ai_note": "手が素直で窓の位置も合っている"
}
→ 201 {"request_id": "...", "group_id": "..."}    -- 投げてすぐ返る
```

**枚数の上限は無い。** エージェントは 12 枚でも 20 枚でも渡せる（§9.3。点検 B6/G8）。

決めたこと（利用者の回答）:

| 論点 | 決め |
| --- | --- |
| 経路 | **HTTP API** だけ。エージェント用の別口（ファイル監視など）は作らない |
| 返り方 | **投げてすぐ返る**（判断を待たせない）。エージェントは `GET /api/review-requests/{id}` を**ポーリング**して結果を得る |
| 対象 | 画像の一覧、または既存のまとまり。`policy` で選び方を指定 |
| 上書き | **同じ `target_key` の未対応の要求があれば、それを `superseded` にして差し替える**（点検 G2 で確定）。`target_key` は**エージェントが付ける任意の文字列**（例 `cut-20261011-031201`）。**無ければ上書きしない**（別の要求として積む） |
| 画像の差し替え | 同じ `target_key` で投げ直すと、**新しいまとまりが作られ、古い要求と（判断がまだ無ければ）古いまとまりは `superseded` の印が付いて既定の一覧から外れる**（P6 で確定。`review_group.superseded_by` と `GET ?include_superseded=1`。**判断が付いた古いまとまりは履歴として残す**）。「置き換わる」の意味はこれで、**古いまとまりのファイルは消さない** |
| 見てほしい条件 | `conditions` に自由文で入る。画面では見出しとして出す |
| AI の下書き | `ai_pick_asset_id` と `ai_note`。画面では印と理由として出し、**人が確定する** |
| 気づき方 | 画面の上部バーの件数と、**タブのタイトル**（`(3) image-reviewer`）。音は使わない。トレイのアイコンも形が変わる |
| さばき方 | **要求の一覧画面**（`#/requests`）。1 件開くとまとまりレビューへ入る |
| 閉じ方 | 判断すると自動で閉じる。断るときは**理由が要る**（エージェントが次の手を決められるように） |
| 認証 | **付けない**（利用者の回答）。ローカル前提 |

- 要求は**まとまり（`review_group`）を作る**。つまり要求のレビューは §9.3 と同じ操作で行う
  （別の画面を作らない）。
- 要求が来ても**画面を奪わない**。件数と印で知らせ、利用者が開いたときにさばく。

### 9.7 画像の上の印（R11）

- **矩形と楕円**（利用者の回答）。自由曲線は作らない。
- 座標は **0〜1 の割合**で持つ（画像の大きさが変わっても使える）。`annotation` 表。
- 1 領域に 1 つのメモ。まとまり全体へのメモも、領域なしの注記として同じ表で扱う。
- 書き出し（利用者の回答: 両方）:
  1. **座標と文の JSON**（エージェントが読む）
  2. **囲んだ範囲ちょうどの切り出し画像**（余白を付けない）
- 人の注記とエージェントの注記を区別する（`actor`）。両方出す。
- 注記は**判断の理由の代わりではない**。ボツの理由は §9.2 の理由マスタから選ぶ
  （注記は「どこが」を指すための補助）。

---

## 10. カタログ（R2）

### 10.1 仮想フォルダ（利用者の選択）

- 入れ物は**階層のある仮想フォルダ**。実ファイルは動かさない（参照モードの場合）。
- **1 枚が複数のフォルダに入れる**（`folder_member` が多対多）。
  例: 「2026-10 生成」と「気に入った構図」の両方に置ける。
- `kind='manual'` は手で入れる。`kind='smart'` は条件で自動で貯まる。
- 走査で見つけたディスクの階層は、**初回に仮想フォルダとして取り込む**ことを選べる
  （`POST /api/scan {mirror_folders:true}`）。以後はディスクと独立に編集できる。
  これが「独自のフォルダ分け構造を持つ」の実装。

### 10.2 スマートフォルダ

`smart_query` は小さな JSON。**SQL を書かせない**（画面から作る）。

```json
{
  "all": [
    {"field": "tag", "op": "has", "value": "1girl"},
    {"field": "tag", "op": "has", "value": "solo", "not": true},
    {"field": "review_state", "op": "in", "value": ["unreviewed"]},
    {"field": "meta.model", "op": "eq", "value": "anima-turbo-v1.1.safetensors"},
    {"field": "meta.seed", "op": "eq", "value": "338134650120909"},
    {"field": "folder", "op": "in", "value": ["01J..."]},
    {"field": "added_at", "op": "gte", "value": "2026-10-01"}
  ]
}
```

- 使えるフィールドは固定の列挙（`tag` / `folder` / `review_state` / `reason_code` / `source` /
  `meta.model` / `meta.seed` / `meta.steps` / `meta.cfg` / `width` / `height` / `added_at` / `seen_at`）。
  画面の UI から選ばせ、**生の SQL や任意式は受け付けない**（安全と速度のため）。
- 件数はキャッシュする（フォルダ一覧に数えると重い）。`folder.count_cache` を持ち、
  走査・タグ付け・判断のあとに無効化する。

### 10.3 検索と並び

- 検索は 3 段: (1) タグ名（索引、前方一致と完全一致）、(2) ファイル名、(3) メモ（FTS5、任意）。
- 並び: 追加順 / 撮影・生成順（`mtime`）/ 名前 / 判断日時。**すべてキーセット改ページ**（`OFFSET` を使わない）。
- 一覧の各行に出すもの: サムネイル、判断の印、タグ数、破綻の印（あれば）、出所。
  ホバーで拡大プレビュー、選択で詳細。

---

## 11. 画面

**画面の設計は [`frontend-design.md`](frontend-design.md) にある。** ここには、どの画面が何を担うかだけを置く
（詳細・配色・書体・部品・文言はあちらが正）。

| 画面 | 役割 | 主な操作 | 詳細 |
| --- | --- | --- | --- |
| ライブラリ（主画面） | 集めて見る・探す・選ぶ | 入れ物の選択、検索、複数選択、まとまりを作る、走査 | `frontend-design.md` §2.4 |
| 拡大（ルーペ） | 1 枚を大きく見る。来歴とタグを並べる | キープ / ボツ、理由、タグの語釈、注記、グラフの書き出し（**条件の記録は廃止**） | 同 §4 |
| まとまりレビュー | キープする 1 枚を決める（R6） | 1 枚に決める / 全部ボツ / 保留 | 同 §2.4, §11 |
| 比較 | 2〜8 枚を比べる | 見方の切替、同期ズーム、並び替え、来歴の差分 | [`comparison.md`](comparison.md) |
| 要求の一覧 | エージェントの要求をさばく（R10） | 開いて決める / あとで / 断る | `frontend-design.md` §4.4 |
| 重複 | 完全重複と準重複の整理（**P8-3 で作った**） | 代表を選ぶ、別物として確定と解除、しきい値の切り替え、削除へ回す | [`duplicates-deletion-backup.md`](duplicates-deletion-backup.md)、`frontend-design.md` §6, §11 |
| **条件の記録と再利用**（**廃止（2026-10-17。利用者の判断）**） | 生成条件の記録、判定（完全/近似/不可）、印つきの書き出し、結果の照合、合否、プリセット（R12） | 書き出す、結果をひも付ける、合否を記録する、条件をコピーする | [`workflow-reproduction.md`](workflow-reproduction.md)、`frontend-design.md` §4.7 |
| **最近の削除** | **取り消せる削除**（残り時間つき）を常設で見せる。**ゴミ箱はこの画面の中**（別の `#/trash` は作らない） | 取り消す、別名で戻す、いま消す、待って消す | `frontend-design.md` §4.6 |
| 取り込み | 走査の設定、進行、失敗の一覧 | ルート追加、参照/取込、URL とクリップボード、走査の開始 | `frontend-design.md` §3 |
| タグ | 語の一覧、件数、日本語の語釈 | 一括タグ付け、語釈の確認と修正 | 同 §8.4 |
| ジョブ | 走査・ハッシュ・サムネ・タグ付け・訳・監視の進み | 中断、再開、失敗の再試行 | 同 §7 |
| 設定 | 接続（ComfyUI のみ）、タガー、閾値、**バックアップ**（最後に取った時刻・直近 7 個・**取り直す**・失敗の全文・置き場）、**置き場ごとの「段 3 を許す」印**、テーマ | 接続テスト、監視の開始/停止、バックアップを取る、置き場を変える、印の付け外し | 同 §5, §11 |

- 未判断を**既定の絞り込み**にする（開いた瞬間に「次に判断すべきもの」が出る）。
- 状態は URL に持たせる（`#/library?folder=...&state=unreviewed`）。戻る・再読込に耐える。
- **キー割り当ては画面をまたいで同じにする**（`1`〜`8` で選ぶ、`Enter` でキープ、`X` でボツ、`A` で全部ボツ）。
  ただしキーボードは**補助**（利用者の回答）。キーが無いとできない操作は作らない。
  [`comparison.md`](comparison.md) §6 が一覧の正。

---

## 12. 性能設計（R8）

### 12.1 目標値（受け入れ基準にする）

**この表は「実測」と「目標（未計測の見積り）」を分けて書く**（点検で「根拠のない置き数値は置かない」と
書きながら 14 行中 8 行に出所が無い、と指摘された）。「実測」列に値があるものだけが実測に基づく。
実測の出所は `metadata-findings.md` §7（`ComfyUI\output` の 1,028 枚）。

**（P9 で全部埋めた。2026-10-18）** 「未計測」はもう無い。**測り方と生の値は
[`p9-implementation.md`](p9-implementation.md)**（`tools/probe_p9.py` が**サーバ内**＝`TestClient` で測る。
合成 1 万枚の DB は `tools/make_synthetic_db.py` が作る）。**届かなかったのは一覧 API の 1 行だけ**で、
理由と必要な条件を下の「届かなかった 1 行」に書いた。

| 項目 | 目標 | 実測（出所） | 種別 |
| --- | --- | --- | --- |
| PNG のメタデータ抽出 1 万枚 | **2 秒以内** | 24,719 枚/秒 → 0.4 秒（1,028 枚で計測） | 実測から導出 |
| 内容ハッシュ 1 万枚 | **60 秒以内** | 399 MB/s（**300 枚・410 MB** で計測）→ 1 万枚 **11.1 GB** なら 28 秒 | 実測から導出 |
| 初回走査 1 万枚（ハッシュ＋登録） | **90 秒以内** | **合成 1 万枚の通しで 40.6 秒（書いた直後）／9.1 秒（温まった状態）**（**P9**。歩査・解析・登録。**96x96 の合成なのでハッシュはほぼ 0**。実画像 11.1 GB ならハッシュ 28 秒を足して **37〜69 秒**＝90 秒以内の見込み） | 実測＋目標 |
| 初回走査 1 万枚（`--no-hash`） | **30 秒以内** | **測る対象が無い——`--no-hash` が実装に無い**（`cli scan` にその口は無く、走査は常にハッシュを取る。§12.2 の「ハッシュは走査の中で計算する」が実装。**P9**） | 目標（**実装が無い**） |
| 2 回目以降の走査（差分なし） | **10 秒以内** | **2.6〜2.7 秒**（合成 1 万枚・3 回。`known=10000`・`created=0`。**P9**） | 実測 |
| サムネイル生成 1 万枚（256px） | **6 分以内** | 36 枚/秒（1 スレッド、256px のみ）→ 4.6 分。**P9: 実画像 29〜30 ms/枚（33 枚/秒）→ 4.9 分**（24 枚の中央値。P9 の再測で 29 ms/枚）。**並列は未実装**（P9 の監査 C-3）——`probe_p9.py --real` が**道具の中で** `ThreadPoolExecutor(min(8, cpu))` を回した**見込み**で 8 本なら 4 ms/枚 → 0.7 分 | 実測 |
| サムネイル生成 1 万枚（1024px） | **25 分以内（P9 で決めた。1 スレッド）** | **130 ms/枚 → 21.7 分**（実画像 1.15 MB・24 枚の中央値。P9 の再測。実装者の 128 ms/枚・監査の 131 ms/枚と同じ桁）。**並列は未実装**（P9 の監査 C-3）——同じく**道具の中の見込み**で 8 本なら 21 ms/枚 → 3.5 分。**実装にスレッドプールは無い**（§12.2 の min(8, cpu_count) は未実装。画面が 2000 枚のサムネイルを要求したときの並列は FastAPI の同期ハンドラのプール次第） | 実測 |
| グリッド初回表示 | 300ms 以内（100 枚、**同一 PC の Chrome、開発者ツールのフレーム時間で計測**） | **87 ms**（100 枚ちょうどの複製・本物の Chrome・1400x900。**最初のカードが出るまで**。全部そろうまで 104 ms・最初の画像 104 ms。299 枚なら 93 ms。**P9**） | 実測 |
| 追加ページ読み込み | 100ms 以内（100 枚、同上） | **測る対象が無い——「追加ページ」が実装に無い**（一覧は `GET /api/assets?limit=2000` を 1 回引いて全部描く。**キーセット改ページも仮想グリッドも無い**。§12.2 の「一覧」と「前面」）。**1 万枚では 2000 枚で切れる**（P9 で「先頭 2000 枚を表示」と出すようにした） | 目標（**実装が無い**） |
| 一覧 API の応答 | p95 20ms 以内（1 万枚の DB、サーバ内で計測） | **p95 244.7 ms（届かない）**（実装者。監査の再測 252.6・P9 の直しを入れた後の再測 260.6。同じ桁）。内訳: SQL 3 本 47.5 ms ＋ 1 万件の dict 組み立てと並べ替え（`store.assets()` 200 ms）＋ `_summary` 1 万件。**§12.2 のキーセット改ページが実装に無く、毎回**全部**を読んで Python で絞っている**（P9） | 実測（**目標に届かない**） |
| **`/api/stats`**（画面が読み込みのたびに一覧と一緒に呼ぶ。**P9 の監査 D-6 で足した**） | —（§12.1 に無かった） | **p95 134.6 ms**（合成 1 万枚。`meta_json` を 1 万回 `json.loads` する）／ **6.1 ms（監査・`TestClient`）・7.1 ms（P9 の再測・keep-alive の HTTP・実データ 455 枚）**。**一覧の段を立てるときに一緒に直す** | 実測 |
| 詳細表示（1024 サムネ） | 200ms 以内（生成済み） | **p95 2.6 ms**（合成 24 枚）／**p95 2.4 ms**（実画像。`FileResponse`。**P9**） | 実測 |
| 比較の 8 枚表示 | 400ms 以内（生成済み） | **p95 8.3 ms**（実データの複製の 8 枚。文書 6.6 ms ＋ 8 枚のサムネイル 8×2.0 ms。**P9**） | 実測 |
| タグ付け | 0.5 秒/枚（GPU、初回を除く） | **未再計測**（実機の記録値を目標として据える）。**P9 でも測っていない**——**ComfyUI に触らない**指示なので（いまの設定は ComfyUI の `IllustTagger` 0.27 秒/枚。`p4-line8-note.md`） | 実測（別環境） |
| pHash の全件計算 1 万枚 | **3 分以内** | **14.8 ms/枚（復号込み）→ 1 万枚で約 2.5 分**（実データ 263 枚の未計算 172 枚が 2.6 秒。**P8-1 の実測**。`comparison.md:283` の「復号＋両ハッシュで 14.1 ms/枚」と一致） | 実測から導出 |
| 日次バックアップ | 5 秒以内 | **201 ms**（実データの複製・DB 3.2 MB ＋ `sidecar` ＋ `export`。**P9 の実測**。P8-4 の 37 ms は DB 1.0 MB のときの値で、**段 1 の 193 行が入って 3.2 MB になった**。P9 の直しを入れた後の再測は **72.7 ms**＝温まった状態） | 実測 |
| 復元（`restore`） | 10 秒以内 | **11 ms**（11〜13。`<data>` を丸ごと消した状態から 263 枚・判断 3 件。**P8-4 の実測**） | 実測 |
| 判断の記録 | 100ms 以内（台帳＋現在値。書き出しは除く） | **p95 1.5 ms**（合成 1 万枚の DB に **1 枚ずつ別の枚**へ `POST /api/reviews`。**P9**。再測も p95 1.5 ms） | 実測 |
| **一括削除の再照合**（§12.3） | 1,000 件で 1 秒以内（`os.stat` 1 回/件） | **596 ms**（1,000 件。うち `os.stat` だけなら 13.8 ms。**P9**） | 実測 |
| **`--include-library`**（§12.3） | **5 分以内（P9 で決めた）** | **0.63〜2.40 秒 / 262 枚・291.1 MB**（**OS のファイルキャッシュで変わる**——実装者 **2.40 秒（132 MB/s）**・監査 **0.63 秒（516 MB/s）**・P9 の直しを入れた後の再測 **0.68 秒（427 MB/s）**。**両方書く**＝P9 の監査 D-5）。画像なしの日次は 72.7〜201 ms。1 万枚 11.1 GB なら **0.4〜1.4 分** | 実測 |
| **再リンクの `nearby`**（§12.3） | **3 秒以内（P9 で決めた）** | **39.2 ms（見つからない＝置き場 20 個を全部歩く）／44.6 ms（1 段目で見つかる）**（合成 1 万枚。**P9**） | 実測 |

**1 万枚の総量は 11.1 GB とする。** 実測した 1,028 枚は 1.14 GB（1.11 MB/枚）なので、
1 万枚で 11.1 GB。ハッシュの速度を測った 300 枚は 410 MB（1.37 MB/枚）で**全体より大きめ**なので、
その比率を 1 万枚へ外挿した 13.7 GB は**使わない**（点検で 24% の食い違いを指摘された）。
大きめの画像が増えれば増えるほど遅くなるため、**実装時に実データで測り直す**。

**届かなかった 1 行（一覧 API。P9）**: 目標 **p95 20 ms** に対して **244.7 ms**（12 倍。監査の再測 252.6・
P9 の直しを入れた後の再測 260.6。**画面が実際に引く `limit=2000` は 277.6〜305.7 ms**）。
**目標は下げない。** 理由は §12.2 の「一覧」が**実装に入っていない**こと——いまの `GET /api/assets` は
**毎回 `store.assets()` で 1 万件を読んで dict を組み、Python で絞って並べ替えてから 100 件を切る**
（`app.py` の `list_assets`）。**必要な条件**: ①キーセット改ページ（`WHERE (sort_key, id) < (?, ?)`。
`OFFSET` を使わない）②`total` を概算にする（`COUNT(*)` を毎回叩かない）③一覧で返す列を最小にする
（タグは別の口）。**この 3 つを入れる段を別に立てる**（P9 では入れていない——`total` の意味と
`q` / `tag` の絞り込みが変わるので、**513 件のテストと画面の前提を一緒に直す段**が要る）。
`/api/stats`（画面が同じ読み込みで呼ぶ。**P9 の監査 D-6**）も **p95 134.6 ms**（1 万枚）なので、
**一覧の段では 2 つ一緒に直す**。
**実データ 262 枚では p95 13.1〜14.3 ms**（`limit=1000`）なので、**1 万枚が現実になるまで困らない**。

### 12.2 効かせ方

**走査**

- `os.scandir` の再帰。`stat` は `scandir` の結果を使う（`stat` を別に呼ばない）。
- 500 行ずつのトランザクションで `INSERT ... ON CONFLICT(path) DO UPDATE`。
- 既存の場所は（`path`, `size`, `mtime_ns`）が同じなら**触らない**。違うものだけハッシュを計算し直す。
- 画像でないファイルは早期に除外（拡張子 → マジックナンバー）。
- **ハッシュは走査の中で計算する**（実測 34 秒 / 1 万枚。遅延させる理由がない）。
  ハッシュは読み取りだけなので**スレッドプールで並列化**できる（4〜8 本）。
- **PNG のメタデータ抽出と pHash は別ジョブ**に回す（走査は登録までを速く閉じる）。

**サムネイル**

- 一度作ったら作らない。`<data>/thumbs/<sha256[0:2]>/<sha256>_<size>.webp`。
- サイズは 2 種: `256`（グリッド）と `1024`（詳細）。元が小さければ拡大しない。
- WebP quality 82、メタデータ削除。Pillow は GIL を解放するので**スレッドプール**で並列化
  （CPU コア数まで。既定 `min(8, cpu_count)`）。
  **（P9 の監査 C-3）この並列化はまだ実装に入っていない**——`thumbs.ensure_thumb()` は 1 本ずつで、
  §12.1 の「同時 8 本なら 3.5 分」は**計測の道具（`probe_p9.py`）が自分で `ThreadPoolExecutor` を
  回した見込み**である。画面が 2000 枚のサムネイルを要求したときの並列は、**FastAPI の同期ハンドラの
  プール次第**（この設計の `min(8, cpu_count)` ではない）。実装する段を別に立てる。
- **必要な順に作る**。画面に見えている範囲を優先キューへ入れ、残りは背景で進める。
  走査直後に全部を作ろうとしない（1 万枚を待たせない）。
- 配信は `FileResponse` + `Cache-Control: public, max-age=31536000, immutable`（内容ハッシュ名なので安全）＋ ETag。

**DB**

```sql
PRAGMA journal_mode = WAL;
PRAGMA synchronous = NORMAL;
PRAGMA mmap_size = 268435456;
PRAGMA cache_size = -65536;
PRAGMA temp_store = MEMORY;
PRAGMA foreign_keys = ON;
```

**（P9 の実測で決めたこと）** `db.connect()` が掛けるのは **`temp_store = MEMORY` と
`mmap_size = 268435456`** の 2 つ（`journal_mode` / `synchronous` / `foreign_keys` は前から）。
**`cache_size = -65536` は入れなかった**——**理由は速さだけ**（1 万枚の SQL 3 本が 43.6 → 42.5 ms で
実利が無い。一覧の 244.7 ms は `store.assets()` の 1 万件の dict 組み立てが主因で、
ページキャッシュでは動かない）。

**（P9 の監査 C-1。ここに書いていた理由は誤りだった。）** 前は「64 MB のページキャッシュに DB 全体が
載ると、**走ったまま壊れた DB を live の接続の `quick_check` が見落とす**（既定の 2 MB なら
`database disk image is malformed` になる）」と書いていた。**既定でも見落とす。** 既定の 2 MB に
収まる大きさの DB（実測 **0.65 MB・250 行**）では、**書き込み用の接続が自分が書いたページを
ページキャッシュに持つ**ので、外から潰されたページを読み直さない（監査の実測: 4 つの pragma の
組み合わせ全部で見落とした。1500 行＝2.28 MB では既定でも見つかる＝テストが見ていたのは境界）。
**P8-4 の実測時の実データは 1.0 MB だったので、G-1 は初日から小さい DB に効いていなかった。**
いまは `backup._refuse_if_broken()` が**新しい読み取り専用の接続**で `quick_check` する
（監査の 28 通りすべてで見つかる）。**`cache_size` の値は安全の話ではない**
（`tests/test_db.py::test_the_temporary_btree_goes_to_memory` は既定のままであることだけを固定し、
壊れの検知は `tests/test_backup.py::test_a_page_in_the_writers_cache_is_still_noticed` が守る）。

**`temp_store = MEMORY` は P9 で足した**（§12.2 に最初から書いてあったのに実装に無かった）。
これが無いと `ORDER BY` が要る読みが**一時ファイルを作りに行き**、`%TEMP%` に書けない置き場では
**1 万枚の `GET /api/assets` が `unable to open database file` で 500 になる**（P9 の実測）。
`cache_size` と `mmap_size` は**ページの大きさを読む**ので**壊れた DB では投げる**——そこは最善努力にして、
「壊れた DB でも起動して 503 で案内する」道（§0.12-5）を塞がないようにしてある。

**一覧**

- キーセット改ページ。`WHERE (sort_key, id) < (?, ?)` の形。`OFFSET` は使わない。
- 一覧で返すのはサムネイル URL と最小限の列。タグは別 API（または先頭 N 語だけ）にして**行を軽くする**。
- 件数は概算を使う（`COUNT(*)` を毎回叩かない）。正確な数が要る画面だけ数える。
- **（P9）この 3 つはまだ実装に入っていない**（§12.1 の「届かなかった 1 行」を見る）。
  いまの実装は**毎回 1 万件を Python で組んで絞る**ので、p95 は 20 ms ではなく **244.7 ms**。

**前面**

- 仮想グリッド（見えている行だけ DOM に置く）。`IntersectionObserver` で遅延読み込み。
- 画像は `loading="lazy"`、`decoding="async"`、`width`/`height` を先に指定してガタつきを消す。
- 判断は**楽観的更新**（押した瞬間に印を変え、失敗したら戻す）。
- 進捗は SSE（`/api/events`）。1 秒ポーリングをやめる。
- **（P9）仮想グリッドもキーセット改ページもまだ実装に入っていない。** いまの一覧は
  **`GET /api/assets?limit=2000` を 1 回引いて全部を DOM に置く**（`limit=2000` は**上限が無いのではなく
  **2000 枚で切れる**）。**実測**: 100 枚で最初のカード 87 ms・299 枚で 93 ms・
  **1 万枚では 2000 枚だけ出て 532 ms**（DOM 12,259 ノード）。**切った枚数は上部に出す**
  （「10000 枚（先頭 2000 枚を表示）」。**数を黙って捨てない**）。

### 12.3 重複・削除・バックアップの性能（**P8 の実測**）

**測った物と未計測を分ける**（P4 の教訓）。出所は `p8-design.md` §7 と P8-1〜P8-4 の実装・監査の記録。

| 操作 | 実測 | 条件 |
| --- | --- | --- |
| pHash の全件計算（263 枚・未計算 172 枚） | **2.6 秒・14.8 ms/枚**（復号込み） | 実データ。**1 万枚で約 2.5 分**（§12.1 の「3 分以内」はここから） |
| 完全重複の検出 | **0.1 ms** | 実データ 263 枚（`GROUP BY` 1 本。**この実データでは 0 群**） |
| 準重複の検出（263 枚） | **帯の候補づくり 46〜52 ms**・（距離 ≥ 16 のとき）**総当たり 2〜8 ms** | `tools/probe_p8.py --duplicates`。**距離 0〜64 のすべてで総当たりと一致・取りこぼし 0** |
| 準重複の検出（1 万枚の合成） | **SQL の自己結合 7.56 秒・Python の辞書 1.13 秒・int の総当たり 7.8 秒**（≤ 6 で 67,705 組が一致） | **合成データ**（実データではない）。**いまの実装（帯ごとの照会）での 1 万枚は未計測**（1 万枚では帯の候補が数百万組になり、合成では測り切れなかった）。263 枚は 50 ms なので、**辞書方式に替えるかは 1 万枚が現実になってから決める** |
| 段 3 の移動（`os.rename`） | **1 GB の疎ファイルでも 0.24 ms**（密な 256 MB は 0.19 ms） | **ファイルの大きさに依らない**（名前の付け替え） |
| 一括削除の再照合 | **未計測** | 目標は 1,000 件で 1 秒以内（`os.stat` 1 回/件） |
| 日次バックアップ | **37 ms**（35〜46。5 回の中央値） | 実データの複製・温まった状態。DB 1.0 MB ＋ `sidecar` 1 ＋ `export` 1。**写しを開いて `quick_check` → `integrity_check` する分も含む** |
| 復元（`restore`） | **11 ms**（11〜13） | `<data>` を丸ごと消した状態から 263 枚・判断 3 件。**`db_sha256` の照合 1 回を含む** |
| `--include-library`（画像の実体も控える） | **未計測** | 実データなら 292 MB。**測り方から決める**（`p8-4-audit-triage.md` §H。P9 の候補） |

- **帯（`phash_band`）の保証は距離 15**。**16 以上は帯で絞らず総当たりに落とす**。
  **8bit × 8 本の前の版は距離 7 までしか保証が無く、≤ 12 で 3 組・≤ 16 で 72 組を取りこぼした**（P8-1 の監査 B-1。実測）。
- **候補の距離を取る前に、16 進の帯を `int(hex, 16)` にしておく**（文字列のまま `hash_distance` を回さない。**0.48 秒 → 0.19 秒**）。
- **計測は別々の入力で、測り方（何回の中央値か）を書く**（P4・P6 の教訓）。**キャッシュに当たった値を実測と呼ばない。**
- **（P9 の実測で埋めた 3 行）** **一括削除の再照合は 596 ms / 1,000 件**（目標 1 秒以内。うち `os.stat` は 13.8 ms）、
  **`--include-library` は 0.63〜2.40 秒 / 262 枚・291.1 MB**（**OS のファイルキャッシュで変わる**——
  実装者 2.40 秒＝132 MB/s・監査 0.63 秒＝516 MB/s・P9 の直しの後の再測 0.68 秒＝427 MB/s。
  **両方書く**＝P9 の監査 D-5。1 万枚 11.1 GB なら 0.4〜1.4 分。
  **画像なしの日次は 72.7〜201 ms**。P8-4 の 37 ms は DB が 1.0 MB だったときの値）、
  **再リンクの `nearby` は 39.2 ms（1 万枚・20 フォルダを全部歩く最悪の場合）／44.6 ms（1 段目で見つかる）**。
  **測り方**は [`p9-implementation.md`](p9-implementation.md)（`tools/probe_p9.py` の `--delete` / `--library` / `--relink`）。
- **（P9 の監査 D-5）`--include-library` は 1 つの数を「実測」と呼ばない。** OS のファイルキャッシュに
  当たると 4 倍違う（516 MB/s と 132 MB/s）。**冷えた状態／温まった状態の両方**を書く。

---

## 13. ディレクトリ構成

```
C:\work\image-reviewer\
  pyproject.toml            # uv。依存を固定
  uv.lock
  README.md
  .gitignore                # .uv-cache / .data / node_modules / dist
  .data\                    # 既定のデータ置き場（IMAGE_REVIEWER_DATA で変更可）
    db.sqlite3
    thumbs\<sha[0:2]>\<sha>_256.webp, _1024.webp
    library\<sha[0:2]>\<sha>.<ext>     # 取込モードの実体
    workflows\<sha>.json               # グラフ（API / UI 形式）
    sidecar\<sha>.json                 # 生成時に捕まえた来歴（英訳はここにしか残らない）
    trash\<YYYYMMDD>\...               # ゴミ箱（duplicates-deletion-backup.md §3.3）
    pending-delete\<削除ID>\...        # 実削除の前に 5 分だけ置く保留領域（同 §3.4）
    export\review.json                 # 外部参照用（原子的に置換。日次と手動）
    export\groups\<group_id>.json      # まとまり単位（判断のたびに更新するのはこれだけ。§6.2）
    export\index.json                  # 件数の索引
  （バックアップ）                      # **既定は <data> の外**（点検 B3）
                                       #   %USERPROFILE%\image-reviewer-backups\
                                       #   DB + sidecar\ + export\ を入れる。画像は任意
                                       #   IMAGE_REVIEWER_BACKUP_DIR で変更できる
  schemas\
    review-export.schema.json          # 外部契約（版付き）
  docs\
    design.md                          # 全体設計（この文書）
    metadata-findings.md               # 実機で確認した前提
    comparison.md                      # 比較の設計
    duplicates-deletion-backup.md      # 重複・削除・バックアップの設計
    workflow-reproduction.md           # ワークフローの再現の設計
    review-export.example.json         # 外部契約の実例
  src\image_reviewer\
    app.py            # FastAPI の組み立て、同一オリジン配信
    cli.py            # serve / scan / tag / hash / export / backup / restore / rebuild-metadata
    db.py             # 接続、pragma、マイグレーション、健全性
    models.py         # pydantic（API の入出力）
    tray.py           # タスクトレイ（**2026-10-19 に `tools\tray.ps1` として作った**。Python ではなく
                      #   Windows の PowerShell + .NET の `NotifyIcon`。§4.1・[`tray.md`](tray.md)）
    api\              # ルーター（assets / locations / folders / tags / reviews / groups / requests /
                      #          annotations / duplicates / export / comfyui / jobs / events）
                      #          **（廃止）** recipes / presets は P7 で作って消した（§16.5）
    services\
      catalog.py      # フォルダ、スマートフォルダ、検索
      assets.py       # 走査、登録、ハッシュ、取込（D&D / クリップボード / URL）、参照切れ
      metadata.py     # PNG と JPEG の解析、来歴
      translate.py    # 訳し直し（TextGenerate）、タグの日本語の語釈
      graph.py        # グラフの書き出し、ComfyUI への設置、印の付与、seed の差し替え（**未実装**）
      # **（廃止。2026-10-17）** recipe.py（記録・判定・検査・結果の照合）は P7 で作って消した（§16.5）
      compare.py      # 来歴の差分、pHash / SSIM / 色、差分ヒートマップ
      duplicates.py   # 完全重複・準重複、帯索引
      tags.py         # 内蔵 WD14 / ComfyUI 経由
      review.py       # 台帳、まとまり、現在値、要求
      annotate.py     # 矩形と楕円、座標 JSON と切り出し
      export.py       # review.json の書き出し
      thumbs.py       # サムネイル
      trash.py        # 削除の 3 段階、保留領域（5 分の取り消し）、復元
      backup.py       # 日次スナップショット、backup / restore
      jobs.py         # ジョブキュー、SSE
    integrations\
      comfyui.py      # /api/jobs /userdata /prompt /view /object_info /experiment/models /system_stats
  apps\gui\
    package.json  vite.config.ts  index.html
    src\  # ファイル構成は frontend-design.md §10 が正
  tests\
```

**ポート**: 既定 **8790**（ComfyUI 8188 と衝突しない）。
開発時の Vite は **5273** で `/api` を 8790 へ proxy。

---

## 14. 工程

各段は「動くもの＋テスト＋実データでの確認」で閉じる。**前の段が緑になってから次へ進む。**

| 段 | 内容 | 完了条件（受け入れ基準） |
| --- | --- | --- |
| **P0 基盤** | リポジトリ、uv、FastAPI 起動、SQLite とマイグレーション、`PRAGMA quick_check`、同一オリジン配信、`/api/health`、CLI `serve`、ショートカットとトレイ | `image-reviewer serve` が 8790 で上がる。ショートカットのダブルクリックでブラウザが開き、トレイにアイコンが出る |
| **P1 登録と表示** | 走査（参照/取込）、`asset` ＋ `asset_location`、ハッシュ、PNG / JPEG の部分読み、サムネイル、一覧と拡大、仮想グリッド | 実データ（`.store\anima-dev`）を走査して一覧が出る。グリッドが 60fps でスクロールする。1 枚を登録・表示できる（**R1**）。同じ絵を 2 か所に置いても 1 行になり、移動しても判断が切れない |
| **P2 取り込みとカタログ** | ドラッグ&ドロップ、クリップボード、URL からの取り込み、仮想フォルダ（多対多）、スマートフォルダ、検索・並び、種別（生成物 / 参考資料 / 写真） | 4 つの経路で取り込める（**R1b**）。1 枚を 2 つのフォルダに入れられる（**R2**）。**手元の 3,999 枚を走査して時間を実測し、1 万枚換算が 90 秒以内になる見込みを示す**（手元に 1 万枚が無いので、この形でしか確かめられない。**R8**） |
| **P3 メタデータ** | PNG の `prompt`/`workflow` 解析、日本語原文、英訳の出所管理、訳し直し、グラフの書き出しと ComfyUI への設置、ComfyUI 監視 | 日本語と英訳が画面に出る（**R4b**）。「訳し直し」が区別して出る。UI 実行画像のワークフローを開ける（**R4a**）。**監視は、`/history` に残っている既存の実行を使って、テキスト出力の由来判定と `final_prompt` の再構成まで確かめる**（新規生成が要る確認は利用者に頼む） |
| **P4 タグ** | 内蔵 WD14（onnxruntime-gpu）、ComfyUI 経由、バッチジョブ、タグ表示（カテゴリ・スコア・出所）、**日本語の語釈**、タグ検索 | 未タグ画像にタグが付く（**R3, R7**）。2 行（英語 / 日本語）で出る。訳は見えた語だけ、保存して人が直せる。**GPU の実測時間を計って記録する**（0.5 秒/枚 は未再計測なので目標として確かめる） |
| **P5-0 SQLite 化** | **機能を足さない。** 表の作成、`store.json` からの取り込み、`asset.id` の ULID 化、`review_group.changed_at` / `exported_at` の追加、**サーバ経由の走査**（別プロセスの `save()` をやめる） | 既存のテストが緑。`store.json` から取り込んだ 263 枚が同じ来歴で引ける。**`cli scan` がサーバの判断を消さない**ことをテストで示す |
| **P5-1 判断と書き出し** | `reason_code`、`decision` 台帳と現在値の写し、1 枚の判断、まとまりレビュー、`review.json` の書き出し（影響したまとまりだけ） | キープ / ボツと理由を付けられる（**R5a, R5b**）。まとまりから 1 枚選ぶ / 全部ボツができる（**R6**）。**枚ごとに理由が残る**（選ばれなかった枚にもその枚自身の理由）。**エージェントは判断を書けない（403）**（点検 A5）。他ツールが `review.json` で読める（**R5c**）。**判断のたびに書き直すのは影響したまとまりのファイルだけ**（点検 B4） |
| **P5-2 比較の基本** | 並べる、来歴の差分表、同期ズーム | 8 枚を来歴つきで比べ、**違う行だけ**が既定で見える |
| **P5-3 比較の重い見方** | 差分ヒートマップ、似ている順、`comparison_cache`、pHash/dHash の背景ジョブ | 近い組でヒートマップが出る／pHash の実測を記録する |
| **P6 要求と注記** | `review_request`（受付・上書き・一覧・閉じる・断る）、要求の一覧画面、AI の下書きの表示、`annotation`（矩形と楕円、座標 JSON と切り出し） | エージェントが要求を投げ、投げてすぐ返る（**R10**）。要求の一覧から開いて判断し、判断で閉じる。AI の推しと理由が両方残る。囲んでメモを付け、座標と切り出しを書き出せる（**R11**） |
| **P7 条件の記録**（**廃止（2026-10-17。利用者の判断）**） | 作って消した（v6 の 6 表・再現キー・判定・印つきの書き出し・監視での結果の紐付け・合否・画面 2 つ）。理由と消した物は [`p7-decision.md`](p7-decision.md) | 完了条件は無い（**R12 は見送り**）。設計と監査の記録は `docs/p7-*.md` に歴史として残す |
| **P8 重複・削除・バックアップ**（**済み。2026-10-18**） | 完全重複と準重複の検出、重複の整理、削除の 3 段階、**5 分の取り消し**、日次バックアップ、`backup` / `restore` / `rebuild-metadata`。**再リンク（合格の線 9）は P8-6 で作った**（下の 1 行） | 重複候補が出て代表を選べる。**実削除のあと 5 分以内なら取り消せ、元の場所に別のファイルがあっても上書きしない**。**参照切れは中身の `sha256` が一致したときだけ繋がる**。DB を消しても sidecar と PNG から来歴を組み直せる（[`duplicates-deletion-backup.md`](duplicates-deletion-backup.md)） |
| **P9 仕上げ**（**済み。2026-10-18**） | 性能調整（§12.2 の pragma を入れた・一覧の切った枚数を画面に出した）、**未計測の項目を実測**（1024px サムネ・一覧 API・グリッドの表示・`--include-library`・再リンクの `nearby`・判断の記録・一括削除の再照合）、テストの締め、exe 化の判断（**推奨は「今は作らない」**） | **§12.1 の「目標」の行がすべて実測で裏づけられた**（**未計測 0**。届かなかったのは一覧 API の 1 行だけで、理由と必要な条件を §12.1 に書いた）。`pytest` **518 件**（5 回とも緑）・`gui_smoke` **322 検査**・`gui_layout` **11 本**。記録は [`p9-implementation.md`](p9-implementation.md) |

**順序は点検 G11 で確定**: **P5（判断と比較）を先に**やる。判断がこの道具の主目的で、
来歴の表示はプロトタイプで既に足りているため。P4（タグ）は判断の材料として後から厚くする。
下の表は番号順だが、**着手は P1 → P2 → P3 → P5 → P6 → P4 → P7 → P8 → P9** とする
（**P7（条件の記録）は 2026-10-17 に廃止し、P8 は 2026-10-18 に、P9 も 2026-10-18 に完了した**。
**これで §14 の段は全部済み**——残りは §14 の外にある物（P2 / P3 の残り・exe 化・
一覧 API のキーセット改ページ・再リンクの画面）で、**どれも利用者の判断待ち**）。
**トレイ（常駐）は 2026-10-19 に作った**（[`tray.md`](tray.md)）。
**P8（重複と削除）を P5 より先にしない**（重複の整理がまとまりレビューを使うため）。
**P5 の前に A5（エージェントは判断を書けない）を実装する**（台帳の意味が変わるため）。

**P8 の合格の線は P8-1〜P8-4**（**P8-0 は機能を足さない**＝表と契約だけの段。**P8-5 は画面の仕上げなので数えない**＝P5-3 と同じ扱い）。
**再リンク（専門 §4 の「近くを探す・場所を指定」・合格の線 9）は P8-6 で作った**（2026-10-18。P8-3 は指示書の段で
「重複と削除の画面」に置き換わったので、**線 9 だけが残っていた**）。口は 2 つ——
`POST /api/locations/relink`（**人だけ**。`exact`＝新しいファイル / `nearby`＝探すフォルダ）と
`GET /api/locations/missing`（**読むだけ**）。**中身の `sha256` が一致したときだけ繋ぎ、pHash は使わない**。
**ファイルは 1 つも動かさない**（`asset_location` の 1 行を `UPDATE` し、`location_history` に 1 行残す）。
**画面は作っていない（口だけ）**（実装の記録は [`docs/p8-6-relink.md`](p8-6-relink.md)）。
**トレイ（常駐）は 2026-10-19 に作った**（`tools/tray.ps1`。§16.8。**この節の「無い」は
P8-6 の時点の話**）。

**P10（段 1 の行を後から進める・実体が無い行を片付ける）は 2026-10-19 に追加した**——利用者の要望
（**一度カタログから外した物をゴミ箱へ／実体が無い物を片付ける**）。**§14 の表の段ではない追加**（P8-6 と同じ扱い）で、
**段 1 が行き止まりだった**のを塞ぐ（`POST /api/deletions/{id}/advance`・`POST /api/deletions/advance`・
`POST /api/deletions/{id}/close`・`POST /api/deletions/close` の 4 つ。**人だけ**・**1 回 200 件**）。
決定は §16.7、実装の記録は [`deletions-advance.md`](deletions-advance.md)、画面の文言は
[`frontend-design.md`](frontend-design.md) §4.6・§6。

**P5 は 4 つに分ける**（P5-0 / P5-1 / P5-2 / P5-3。点検 G1・G2・G10。
中身と完了条件の正は [`p5-design.md`](p5-design.md) §0.1）。**合格の線は P5-2 まで**で、
**P5-3 は合格の線に数えない**（判断と差分表が主目的）。

### テスト方針

- `tests/` に pytest。**実データに依存しない**合成画像（Pillow で作った PNG＋`prompt` チャンク）で回す。
- PNG / JPEG の解析は**実物のチャンクを切り出したフィクスチャ**で確かめる
  （`prompt` のみ / `workflow` あり / グラフ無し / 壊れたチャンク）。
- 台帳は「追記のみ」「現在値が一致する」「再起動しても残る」を確かめる。
- まとまり判定は「選んだ枚が `keep`、他が `reject`、全員に理由が付く」「全部ボツで全員 `reject`」。
- 要求は「同じ `target_key` なら上書きされる（無ければ積まれる）」「判断で閉じる」「断るには理由が要る」。
- **エージェントは判断を書けない**: `POST /api/reviews` と `decide` が `actor='agent'` で **403** になること（点検 A5）。
- 注記は「0〜1 の座標が往復する」「切り出しが囲んだ範囲ちょうど」。
- 削除は「段 3 のあと 5 分以内なら戻る」「**アプリを閉じている間は時間が進まない**」
  「**`asset_location` に無いパスは触らない**（完全一致）」「`(size, mtime_ns)` が変わっていた項目だけ飛ばす」
  「元の場所が埋まっていたら**上書きせず 409 で止めて尋ねる**（別名は人だけが選ぶ）」「起動時に消さない」。
- 一括削除は「**preview で凍結した一覧だけ**を消す」「preview が失効したら何も消さず 409」。
- 書き出しは**スキーマ検証**（`schemas/review-export.schema.json` で `jsonschema` 検証）と**決定性**で確かめる。
  決定性は **`generated_at` を除いて** 2 回出して比べる（時刻を含めたまま比べると必ず落ちる。
  点検で見つかった誤り）。並び順（キー・配列）も同時に確かめる。
- 走査の**制約違反**を確かめる: 同じパスの中身を差し替えて再走査し、`UNIQUE(path)` に当たらず、
  `location_history` に 1 行残り、古い `asset` の判断が失われないこと（§5.1。点検で見つかった誤り）。
- **64bit の値**を確かめる: seed に `18446744073709551615`、pHash に `ffffffffffffffff` を入れ、
  往復して同じ値になること（§5.1 の表）。
- **帯索引**を確かめる: 距離 **0〜64 のすべて**で、帯が挙げた候補と**総当たり**が一致すること
  （**4bit × 16 本**。**距離 ≤ 15 は必ず候補に挙がる**。`p8-design.md` §2.1。前の版の 8bit × 8 本は
  **≤ 12 で 3 組・≤ 16 で 72 組を取りこぼした**＝P8-1 の監査 B-1 の実測）。
- **取り消しの上書き防止**を確かめる: 削除した場所に別のファイルを置いてから取り消しを試み、
  **上書きせず 409 `target_exists` で止まる**こと（**人だけ** `as_copy: true` で `<名前>.<連番>.<拡張子>` に戻せる。
  `os.rename` を `os.replace` に替えると**元の場所の別のファイルが壊れる**ので、この試験は決定的に落ちる）。
- **Host / Origin の検査**を確かめる: `Host: evil.example` と、他オリジンの `Origin` を付けた
  状態変更要求が 403 になること（§6.3.1）。
- 画面はヘッドレスで通し確認する（ブラウザが無ければ exit 77 で飛ばす）。

---

## 15. リスクと対策

| # | リスク | 対策 |
| --- | --- | --- |
| 1 | **既存画像の英訳が原文として出せない** | 出所を分けて保持し、訳し直しには画面で印を付ける。黙って原文のように見せない（§7.3） |
| 2 | ComfyUI の URL でワークフローを開けない | 書き出し＋D&D を主経路にする。`install` が失敗しても「JSON を保存」で目的を果たせるようにする（§7.4） |
| 3 | GPU の VRAM 競合（ComfyUI とタガー） | タガーの同時実行を 1 に絞り、セマフォで直列化する。GPU を選べる。CPU へ落ちる。生成中は譲る設定を持つ（§8.2）。**このツールは生成を実行しない**ので、競合するのはタガーと訳し直しだけ |
| 4 | 参照切れ（画像の移動・削除） | 内容を正体にして場所を従属させる。`missing_at` を立てて消さず、ハッシュで再リンクする。判断は内容に付くので失われない（`duplicates-deletion-backup.md` §1, §4）。**（P8・P8-6 の実績）`missing_at` の道と `location_history` は動いており、再リンクの口（`POST /api/locations/relink`）は P8-6 で作った**（**人だけ**・**`sha256` の一致が要る**・**pHash は使わない**。§14 の下） |
| 5 | **誤って消してしまう（戻せない）** | 実削除は確認 1 回のあと**保留領域へ移すだけ**にし、5 分間は取り消せる。触ってよいのは**登録済みの `asset_location` に実在するパスそのものだけ**（`normalize_path` の**完全一致**。点検 B1 で「登録ルートの外は触らない」から置き換えた。ルートを持つのはフォルダ走査だけで、D&D・URL・要求で登録した画像には適用できないため）。一括削除は**凍結した一覧だけ**を消し（点検 A6）、`(size, mtime_ns)` が変わっていた項目は**その項目だけ飛ばす**（`duplicates-deletion-backup.md` §3.2, §3.4, §3.5） |
| 6 | 1 万枚の `review.json` が大きい | 範囲指定と、まとまりごとのファイル書き出しを用意する（§9.4） |
| 7 | タガーの誤り（手の破綻を読めない等） | 限界を画面に書く。機械の印は下書きに留め、自動でキープにしない（§8.3） |
| 8 | `onnxruntime-gpu` の導入失敗 | 起動時に検出して `builtin` を無効化し、`comfyui` 方式を案内する（fail-soft） |
| 9 | uv / サンドボックスの制約 | `UV_CACHE_DIR` をリポジトリ内へ。README に書く（§4） |
| 10 | 拡張子と中身の食い違い | マジックナンバーを優先（§7.1） |
| 11 | **データ置き場を消したときの来歴消失** | `sidecar/` と `export/` は人間が読める JSON。**加えて日次のスナップショットに `sidecar/` と `export/` を含め、保存先を既定で `<data>` の外に置く**（点検 B3。捕獲した英訳は PNG から取り直せない唯一のものなので、守る物を守る場所の中に置かない）。**外のバックアップがあれば** PNG と sidecar から来歴を組み直せる（`duplicates-deletion-backup.md` §5.2） |
| 12 | **書き出したグラフでも訳が変わり、絵が別物になる** | 捕獲した英文を固定したグラフ（L1）を既定にして書き出す。L2 になる場合は画面で明示し、結果を測って人に合否を求める（`workflow-reproduction.md` §4.2, §4.8） |
| 13 | **同名で中身が変わったモデル / LoRA** | `(名前, size, mtime)` を照合し、不一致を「近似」の理由に出す。任意でフルハッシュ（`workflow-reproduction.md` §4.6） |
| 14 | エージェントの要求が溢れる（上書きで消える） | 同じ対象は上書きし、前のものは `superseded_by` で残す。要求の一覧は未対応を既定にし、古いものは折りたたむ（§9.6） |
| 15 | **日本語の語釈の質** | 「訳は自動」と画面に示し、必ず直せる導線を出す。直した語（`edited=1`）は訳し直しで上書きしない（§8.4） |
| 16 | 重複の誤検出（別の絵を同じと見なす） | 自動でまとめない・消さない。候補を出すだけ。しきい値は実データで調整する（`duplicates-deletion-backup.md` §2.4） |

---

## 16. 決めたこと・決めていないこと

### 16.1 決まったこと（利用者の回答、2026-10-14）

**作るもの**

- 独立した新ツール。**他のツールとは完全に切り離す**（コードもデータも語彙も規約も合わせない。将来も連携しない）
- ローカル Web アプリ（`127.0.0.1:8790`）。ショートカットで起動し、タスクトレイに常駐
- 前面は**素の TypeScript + Vite**（フレームワークなし）
- 名前は **`image-reviewer`**。想定規模は数千枚（〜1 万）
- データ置き場は**リポジトリ内の `.data`**。プロトタイプの保存はまず JSON、後に SQLite
- 進め方: **DeepSeek が設計書（バックエンド／フロントエンド）を書き → Claude Code の Fable が点検 →
  DeepSeek が実装 → Fable が監査**

**画像**

- 対象: **自分の生成物（Anima 他）／参考資料（他人の絵）／写真・スクリーンショット**
- 形式: **PNG と JPEG**
- 種別（生成物 / 参考資料 / 写真）は**自動で判定し、人が直せる**
- 参考資料には**出所 URL / 種別 / 何の参考かの自由記述**を持たせる（**省略可**）
- 取り込み: **フォルダ走査 / ドラッグ&ドロップ / クリップボード / 画像 URL を貼る**。
  クリップボードの中身が URL で拡張子が画像なら取り込みを試みる
- 「保存」に含めるのは**登録と取り込みまで**。書き出し・改名・メタデータの埋め込みは対象外
- 参照を既定、取込（コピー）も選べる

**見る・探す**

- カタログは**仮想の入れ物**（1 枚が複数所属可）＋ スマートフォルダ
- 画面は**日本語**、Danbooru タグは**英語**（＋日本語の語釈を 2 行目に。**括弧書きは使わない**）
- タグは**詳細と拡大だけ**に出す。語釈の訳は **ComfyUI の `TextGenerate`**、**見えた語だけ遅延**、
  保存して**人が直せる**
- グリッドの見た目は**切替できる**ようにする（密度とテーマ）
- タグの**統合・改名は作らない**。**画像への手動の付け外しはできる**（点検 G1 で確定。
  利用者の回答は「語の統合・改名を作らない」であって、画像に語を足すことまで否定していない。
  当初「表示と語釈だけ」と書いていたが、§6.1 の API と §8.1 の `manual` と矛盾していた）

**判断**

- 言葉は **キープ / ボツ**（契約は `kept` / `rejected`、`keep` / `reject` / `clear`）
- 「採用」＝**気に入ったもの**（作品で使うかは別）。軸は**今は 1 つ**
- 段階評価（星）は**入れない**
- 判断の単位は**1 枚ずつとまとまりの両方**を同じくらい使う
- ボツの理由の初期値は §9.2（利用者が選んだ 8 つ）
- キーボードは**補助**（あれば速い。必須にしない）
- 注記は**矩形と楕円**。座標は **0〜1 の割合**。書き出しは**座標 JSON** と**囲んだ範囲ちょうどの切り出し**
- 比較で作るのは **並べる / 来歴の差分表 / 差分ヒートマップ / 同期ズーム / 似ている順**。
  点滅・スワイプ・重ねるは**後から足せる**ようにする

**エージェント**

- 要求は **HTTP API**（`POST /api/review-requests`）。**投げてすぐ返る**（待たせない）
- エージェントは **API をポーリング**して結果を得る
- 要求に含める: 画像の一覧 / まとまりと選び方 / 見てほしい条件 / **AI の下書き判断** / どこから来たか /
  応答に求めるもの
- **同じ対象なら新しい要求で上書き**（**画像の差し替えも可**）
- AI の下書きと人の判断は**両方を残す**
- 気づき方は**画面の件数とタブのタイトル**。音は使わない。トレイのアイコンも変わる
- さばくのは**要求の一覧画面**
- 認証は**付けない**

**生成の条件**

- **このツールは生成を実行しない。** 記録と再利用（コピー / ComfyUI で開く / seed 違いの書き出し / プリセット）
- プリセットは**人間が参照できればよい**（他のカットへの適用やエージェント向け API は作らない）
- 訳し直しは **ComfyUI の `TextGenerate`**（Ollama は今回使わない）
- 監視は**必要なときだけ手で開始**。ただし**結果の取り込みに使う**ので、書き出しには**印**を付ける
- モデルの同一性は `(名前, size, mtime)`。**任意で押せる**ようにフルハッシュも取れるようにする

**消す**

- **本当にファイルを消したい場面がある**（ボツの完全削除 / 容量 / 失敗した大量生成 / 重複）
- 確認は**一覧を見せて 1 回だけ**。その代わり**削除後 5 分間は取り消せる**
- 一括削除の指定は**フォルダ・まとまり単位 / 検索結果・絞り込み単位 / 手で選んで一括**

### 16.2 決めていないこと

1. **フォルダ改名の実施。** 現在 `C:\work\image-reviwer`（`reviewer` ではなく `reviwer`）。
   このセッションからは**改名できない**（書き込み権限がこのパスに固定されているため、
   `C:\work\image-reviewer` の作成が拒否された）。手順:
   ① この設計の点検と修正を終える → ② 利用者がフォルダを改名 →
   ③ このセッションのワークスペースを `C:\work\image-reviewer` に切り替える。
   文書内の名前は既に `image-reviewer` / `image_reviewer` にしてある。
2. **モデルのフルハッシュを取るタイミング。** 既定は `(名前, size, mtime)`。53 GB で約 2 分
   （`workflow-reproduction.md` §4.6）。
3. **重複・準重複のしきい値。** 実データで決める（初期値 pHash ≤ 6 / SSIM ≥ 0.95）。
4. **保留領域の置き場所**（`<data>` が対象と別ボリュームのとき）。命名も含めて未確認
   （`duplicates-deletion-backup.md` §3.4）。
5. **英訳が残っていない画像（`text_not_captured`）の扱い。** 画面で訳を入れて L3 に誘導するのが本筋だが、
   「まとめて訳し直す」も選べるようにするか（`workflow-reproduction.md` §8）。
6. **印の形式をどこまで厳密にするか。** → **決めた（点検 B9）。** 前提（`filename_prefix` がリテラル・
   `type='output'` の保存ノードがある・複数の保存ノードには同じ印）を明記し、外れたときの落とし方を決めた
   （`workflow-reproduction.md` §4.7.1）。`temp` がいつ消えるかは**未確認**のまま。
7. **書き出しのグラフを ComfyUI が読み込んだとき、`filename_prefix` と `control_after_generate` が
   どう復元されるか**（未確認。`workflow-reproduction.md` §4.7.2）。実装時に実機で確かめる。
8. **タガーの実測速度を再計測するか。** 「0.5 秒/枚」はこのセッションでは再計測していない（§12.1）。
9. **`review.json` に要求の状態を含めるか。** → **決めた: 含める。**
   点検で「契約ファイルだけでは要求の結果が分からない」と指摘されたため、
   任意の `requests` 配列を契約に足した（`schemas/review-export.schema.json`。§6.2）。
   エージェントは API をポーリングするのが主だが、ファイルを読むだけでも分かるようになった。
10. **`review.json` に画像の種別を含めるか。** → **決めた: 含める（点検 G3）。**
    `generated` / `reference` / `photo` の 1 つの列挙。後から足すと `abi` を上げる理由が増えるため、今入れる（§6.2）。
10b. **クリップボードの経路。** ブラウザから読める場合（`navigator.clipboard`）は画面側で完結するが、
    サーバ側から Windows のクリップボードを読むには追加の依存（`pyperclip` 等）が要る。
    どちらで実装するか未定（`design.md` §6.1 の `assets/from-clipboard` の実体）。
    画面側が本筋（利用者が貼った内容をそのまま送る）。サーバ側は補助。
11. **Host / Origin の検査をどこまで厳しくするか。** 基本方針は §6.3.1（`Host` の許可リスト、
    `Origin` の同一性、`Content-Type` と独自ヘッダの要求）。ポートを変えたときの許可リストの持ち方を決める。
12. **1 万枚の目標をどう確かめるか。** 手元にあるのは最大 3,999 枚なので、
    「実測から 1 万枚換算の見込みを出す」形にした（§14 P2）。実データが増えたら測り直す。
13. **exe 化の要否。** まず Web アプリ。必要になったら Python を同梱して包む（Tauri / PyInstaller）。
14. **ゴミ箱（段 2）の自動掃除を既定で ON にするか。** 今は「通知のみ」を既定にしている。

### 16.3 2 回目の点検（Fable）で決まったこと

`docs/review-triage-fable.md` §4 の 11 件は**すべて推奨どおりで確定**した（利用者 2026-10-15）。
本文に反映済み:

| 論点 | 決定 | 反映先 |
| --- | --- | --- |
| 画像への手動タグ付け | **残す**（統合・改名だけを作らない） | §16.1 |
| 要求の「同じ対象」 | **`target_key`**（エージェントが付ける任意の文字列。無ければ上書きしない） | §9.6, §6.1 |
| 契約に画像の種別 | **入れる** | §6.2, 契約 |
| 5 分の窓の数え方 | **アプリが動いていた時間**（単調時計。閉じている間は減らさない） | `duplicates-deletion-backup.md` §3.4 |
| 「最後の 1 つ以外は段 2 まで」 | **逆向きだった。** 最後の 1 つは重い確認、他のコピーは軽い確認で段 3 可 | 同 §3.2 |
| サムネイルの形 | **高さを密度で固定し、幅を絵の縦横比から**（切らない） | `frontend-design.md` §4.1（実装も修正済み） |
| 判断のたびの書き出し | **まとまり単位のファイルだけ**。`tags`/`prompts` は既定で出さない | §6.2 |
| まとまりの枚数 | **上限を外す**。番号キーは見えている 8 枚に割り当て | §9.3 |
| エージェントが判断を書く | **書けない**（`human` 以外は 403）。入口は要求の `ai_pick` だけ | §9.5, §6.1 |
| プロトタイプを P1 の土台に | **する**（パスの正規化と結線の解決は先に直した） | `prototype-notes.md` §5b |
| 本実装の順序 | **P5（判断と比較）を先に**（決定 G11） | §14 |
15. **`en_source` に `ollama` を残すか。** 今回 Ollama は使わないと決めたので、
    使わない値を契約に残すかどうか（今は残っている）。

### 16.4 P6（要求と注記）で確定したこと

P6 の設計 [`p6-design.md`](p6-design.md) §0 が**拘束力のある差分**で、点検（[`p6-review-report.md`](p6-review-report.md)）と
3 段の監査（[`p6-0-audit-report.md`](p6-0-audit-report.md) / [`p6-1a-audit-report.md`](p6-1a-audit-report.md) /
[`p6-1b-audit-report.md`](p6-1b-audit-report.md) / [`p6-2-audit-report.md`](p6-2-audit-report.md)）を経て、
**利用者が 2026-10-16 にすべて推奨どおりで確定**した。本文（本設計書）に反映済み:

| 論点 | 決定 | 反映先 |
| --- | --- | --- |
| **領域なしの注記** | **座標を NULL 可**にし、「**画像 1 枚へのメモ**」まで作る。**まとまり全体へのメモは作らない**（`review_group.note` がある） | §5.6（`annotation` の DDL）, §9.7, §6.1 |
| **まとまりレビューの画面** | **P6 で作る**（`#/group/<id>` の最小形。P5 では一覧・拡大・比較だけだった） | §6.1, `frontend-design.md` §3 |
| **差し替えで残る古いまとまり** | **印を付けて既定から外す**（`review_group.superseded_by`。判断が無いときだけ。`?include_superseded=1` で出す） | §5.6, §9.6, §6.1 |
| **切り出しの書き出し** | **`POST` だけが書く**。`GET` は `format=json` のみ（`crops` を `GET` で来たら 422 で案内）。`GET /api/annotations/{id}/crop` はその場で作って返す | §6.1 |
| **要求の応答** | **閉じた時点の写しを `response` 列に保存**。ただし **`annotations` だけ読むときに導出**（判断後に付けた印も入る） | §5.6, §9.6 |
| **注記を消したとき** | **切り出しの PNG も消す**（切り出しは作り直せるキャッシュ） | §5.6, §9.7 |
| **切り出しの PNG** | **`compress_level=1`**（無劣化のまま。1024² 全面 66 → 21 ms） | §7 |
| **要求の一覧** | `ai.pick_index`（AI の推しが対象の何番目か。1 始まり）と `?group_id=` の絞り込みを足した | §6.1, 契約 |
| **メモしか無い画像の切り出し** | **200 で `crops: []`**（書けた分だけ返す。名指しで領域なしのときだけ 422） | §6.1 |

---

### 16.5 P7（条件の記録）— 廃止

P7（R12）は [`p7-design.md`](p7-design.md) に沿って P7-0〜P7-4 を作り、点検と 4 段の監査（P7-0 / P7-1 / P7-3 / P7-4）と再確認を経て
`pytest` 403 件・`gui_smoke` 164 検査・`gui_layout` 8 画面まで緑にしたが、**2026-10-17 に利用者の判断で削除した**。
理由は ①「前に作った絵をもう一回作る」ときは **PNG を ComfyUI にドラッグすればワークフローが戻る**ので記録は重複、
②ja2en の英訳が PNG に残らない件も**もう一度ワークフローを実行すれば取れる**、の 2 点。
表（v6 の 6 表）・API・画面 2 つ・テスト・契約（`recipe-manifest.schema.json`）を全部消し、`SCHEMA_VERSION` は **5** に戻した。
消した物と控えの場所は [`p7-decision.md`](p7-decision.md)、設計と監査の記録は `docs/p7-*.md` に歴史として残す（各ファイルの先頭に廃止の 1 行）。
**廃止後の数（実測）**: `pytest` **285 件**・`gui_smoke` **129 検査**・`gui_layout` **6 画面**。

---

### 16.6 P8（重複・削除・バックアップ）で確定したこと

P8 の設計 [`p8-design.md`](p8-design.md) §0 が**拘束力のある差分**で、点検
（[`p8-review-report.md`](p8-review-report.md) ＋ [`p8-review-triage.md`](p8-review-triage.md)）と
6 小段（P8-0〜P8-5）の実装と監査（[`p8-0-audit-report.md`](p8-0-audit-report.md) /
[`p8-1-audit-report.md`](p8-1-audit-report.md) / [`p8-2-audit-report.md`](p8-2-audit-report.md) ＋
[`p8-2-audit-recheck.md`](p8-2-audit-recheck.md) / [`p8-3-audit-report.md`](p8-3-audit-report.md) ＋
[`p8-3-audit-recheck.md`](p8-3-audit-recheck.md) / [`p8-4-audit-report.md`](p8-4-audit-report.md) ＋
[`p8-4-audit-recheck.md`](p8-4-audit-recheck.md) / [`p8-5-audit-report.md`](p8-5-audit-report.md)）を経て、
**利用者が Q1〜Q8 を確定**した。
**2026-10-18 に P8 完了**（**合格の線は P8-1〜P8-4**。P8-5 は画面の仕上げで数えない）。
**残っていた合格の線 9（参照切れの再リンク）は P8-6 として 2026-10-18 に実装した**
（実装の記録は [`p8-6-relink.md`](p8-6-relink.md)。**監査はこれから**）。
**本設計書への反映は §5.1・§5.8・§6.1・§14・§15・§16.6**（下表の後半 3 行）。
**監査の判定はどれも「合格（条件つき）」で、指摘は全部反映した**（P8-3 の再確認だけ「合格（条件なし）」）。
**P8-5 の条件 3 件も 2026-10-18 の仕分け（[`p8-5-audit-triage.md`](p8-5-audit-triage.md)）で反映した**——
印のボタンの二度押し（`setAllow` の `busy`）・読み取り専用の DB で書き込むボタンを置かない・
`gui_layout --screen asset` の段の期待値を API から組む（「段が 3 つ」を前提にしない）。
**（2026-10-19 に実測）段 3 の許可が無い置き場の枚で `--screen asset` が 4 幅とも ok**。
**前の版のこの段落は「未反映」と書いていたが、古い事実だった**（README と引継書も同じ日に直した）。
本文（本設計書）に反映済み:

| 論点 | 決定 | 反映先 |
| --- | --- | --- |
| **利用者の回答 Q1〜Q8**（2026-10-17） | **Q1 段 3 を許す**（アプリから実ファイルまで消せる）／**Q2 削除はエージェントにも許す**（**推奨の「人だけ」を利用者が覆した**）／**Q3 しきい値は ≤ 6 を既定**（画面で ≤ 3 / ≤ 6 / ≤ 10）／**Q4 代表の推薦の規則はこれでよい**（推薦するだけ・自動で外さない）／**Q5 同じ seed の群は重複として出さない**（別の一覧も作らない）／**Q6 置き場は `%USERPROFILE%\image-reviewer-backups`**（別ドライブも設定で指定可）／**Q7 保留領域は知らせるだけ**（黙って消さない）／**Q8 別のツールの管理下の置き場にも段 3 の印を付ける** | §6.1, §5.8, §9.5, §12.3 |
| **Q2 の帰結 a〜f** | **`actor` を必ず `deletion_log` に残す**（語彙外は 422）／**画面に「誰が消したか」を出す**／**5 分の窓は誰でも同じ**／**エージェントは 1 回 200 枚まで**（超えたら **422 `too_many` で 1 枚も消さない**。人に上限は無い）／**取り消しの導線を目立つ所に**（`#/pending-deletes` ＋ 上部バー。**トレイは P8-5 では作らず、2026-10-19 に作った**＝§16.8）／**取り消しもエージェントに許すが自分が消した物だけ**（**人は誰の削除でも戻せる**・`as_copy` は人だけ） | §9.5, §11, §6.1 |
| **削除の 3 段階** | **段 1 = カタログから外す**（`asset.deleted_at`。行は消さない）／**段 2 = ゴミ箱**（`<data>/trash/<日付>/`。日付は現地）／**段 3 = 実ファイルの削除**（`<data>/pending-delete/<id>/` へ移してから） | §5.8, §6.1 |
| **5 分の窓は単調時計で数える** | **`remaining_sec` を `time.monotonic` で減らす**（**壁時計では数えない**）。**スリープ・終了の間は進まない**。`purge_at` は画面に出す目安で、**自動削除の判定には使わない**。**起動時には絶対に消さない**（残り時間を引き継いで戻す）。**1 秒未満の端数は次の周期に繰り越す** | §6.1, §12.3 |
| **取り消しは `os.rename`**（**`os.replace` は既存を黙って上書きする**＝実測） | 埋まっていれば **`409 target_exists` で止めて尋ねる**（`FileExistsError`＝WinError 183。**`exists` の事前検査は要らない**）。**人だけ `as_copy: true`** で `<名前>.<連番>.<拡張子>`。**失敗したら `purge_at` を NULL に**して自動削除から外す | §6.1, §12.3 |
| **一括削除は凍結 → 実行** | **凍結した一覧だけを消す**（実行時に `scope` を評価し直さない）。実行の直前に **1 件ずつ `(size, mtime_ns)` を凍結の値と実ファイルの両方**と再照合し、食い違った項目だけ `skipped`。**失効（既定 10 分）したら 1 件も消さず 409** | §6.1, §5.8 |
| **「最後の 1 つ」は 409** | 段 3 で最後の 1 つを消すには **`confirm_last_copy: true`**（無ければ **409 `last_copy`。1 枚も消さない**）。**要るのは段 3 の一括だけ**（段 1・2 は内容が失われない） | §6.1 |
| **別ボリュームは 409** | 保留領域と対象が別ボリュームなら **409 `cross_volume`**（段 2 でも段 3 でも）。コピーになって待たされ、途中で失敗すると中途半端になるため**安全側に倒す**（画面にはエクスプローラで消す案内） | §6.1 |
| **段 3 の印（`root.allow_stage3`）** | **置き場ごとに「段 3 を許す」印**。**印が無い置き場は段 1・2 まで**（**409 `stage_not_allowed`**）。印は**利用者の明示の意思表示**（Q8）で、**画面（`#/settings`）から付け外しできる**（人だけ） | §5.8, §6.1, §11 |
| **既定は印なし** | **既定は 0**（安全側）。**走査で新しく増えた置き場も印なし**で入る。実データは `illust-authoring` の置き場（262 / 263 枚）にだけ 1 が立っている | §5.8, §6.1 |
| **重複は pHash ≤ 6・確実な順** | 準重複は**ハミング距離 ≤ 6 を既定**（画面で切り替え）。**並びは群の中の最大距離が小さい順**（確実な物から）。**代表は推薦するだけ**（人が選んだ物 → 画素数 → サイズ → `mtime_ns` → id の順。**自動では外さない**）。**完全重複はこの実データで 0 群**なので、空のときは「完全重複はありません」と 1 行出す | §6.1, §12.3 |
| **同じ seed の群は出さない** | `meta` の `seed` が同じ 19 群（最大 31 枚）は**別の絵**（点検の実測: 群の中の pHash 距離は中央値 28〜30）。**重複としても「同 seed」としても出さない**（Q5） | §6.1 |
| **帯の保証は距離 15** | `phash_band` は **4bit × 16 本**（前の版の 8bit × 8 本は**距離 7 までしか保証が無く、≤ 12 で 3 組・≤ 16 で 72 組を取りこぼした**＝実測）。**16 以上は帯で絞らず総当たり**に落とす | §5.8, §12.3 |
| **バックアップは `<data>` の外・日次・増分・7 世代** | 既定は **`%USERPROFILE%\image-reviewer-backups\<YYYYMMDD>\`**（`<data>` の中は 422。**`<data>` を消したときに備える物を `<data>` の中に置かない**）。**起動時と 30 秒ごとに「今日の分が無ければ取る」**（**「取り直す」は必ず新しく取る**）。**変わらないファイルは `os.link` で共有**（増分）。**直近 7 世代**を残し、**自分の名前で `manifest.json` を持つ物だけ**を掃除の対象にする | §6.1, §12.3 |
| **画面の語は「取り直す」に統一した**（**P8-5**） | ボタン・`KIND_TEXT.manual`・押した後の 1 行を **「取り直す」**に揃えた（**`frontend-design.md` §6 を正とした**。**P8-5 の監査 D-1 の推奨は逆に「いま取る」へ文言表を寄せることだったが、指示により画面の語を文言表へ寄せた**）。`gui_smoke` / `gui_layout` の検査も同じ語に直した。**`docs/p8-design.md`（履歴）と `backup.py` / `api/backup.py` の注記には「いま取る」が残る**（**注記の語は利用者に見えない**ので放置。§6.1 の口の説明に 1 行足した） | §6.1, §11, `frontend-design.md` §3・§6 |
| **壊れた写しは採用しない** | 日次は**写しを作り終えた後に、写しを開いて `quick_check` → `integrity_check`**。通らなければ**その世代を採用しない**（一時フォルダを捨て、`last_error` に残し、**古い世代を掃除しない**）。**元の接続の `quick_check` も見て、走ったまま壊れていれば読み取り専用に切り替える** | §6.1 |
| **`restore` は sha256 を照合** | **取り出す前に `manifest.db_sha256` を照合**（違えば **409 `bad_backup`**、`--force` で進む。CLI は 1 行で出す）。置き換えは**一時名に写して `os.replace` → その後に `-wal` / `-shm` を消す**。**掴まれていれば何も壊さずに 409 `restore_failed` の 1 行**（トレースバックを出さない） | §6.1 |
| **読み取り専用で起動する道** | 壊れた DB・**DB の版 > バイナリの版**・版を上げる前の控えが取れない、のいずれでも**起動を拒否しない**——**読み取り専用で起動して復元を案内**する。**読める口は読み**（壊れたページを触った口は **503 `read_only`**）、**書き込みの口は 503**。**画面そのもの（`/` と静的ファイル）は通す** | §6.1 |
| **`import` で `create_app()` を走らせない** | `import image_reviewer.app` で**実データを書き込み可で開かない**（遅延 `__getattr__`・`serve` は `--factory`・pytest は収集の前に `IMAGE_REVIEWER_DATA` をテストの中へ向ける）。**事故は実データで起きた**（版を上げずに `ALTER` した）ため、**版を上げない形の変更の前にも `pre-topup-*` の控えを取る** | §5.8 |
| **`create_app()` は env が無ければ開かない**（**P8-6。事故 3 件目**） | **`IMAGE_REVIEWER_DATA` が無ければ `create_app()` が開く前に `RuntimeError`**（**1 バイトも書かない**。判定は `inspect_db` よりも先頭）。**既定の `.data` を明示的に指すのは `cli serve`（`serve_data_dir()`）だけ**。**事故 3 件の型はすべて同じ**——「**明示的に呼ばれた `create_app()` が env 無しで既定の `.data` を書き込み可で開いた**」: ①`import` で走る ②検証スクリプトが明示的に呼ぶ ③検証サーバに env を付け忘れる。**3 つとも塞いだ**（`tests/test_data_dir_guard.py` の 4 件が別プロセスで「例外になり `.data` の署名が変わらない」ことを見る）。**実データに起きたこと**: `location_history` の 3 列と `settings.backup.last_error` が書き換わり（**行の変化は 0**。263 枚・判断 3 件のまま）、控えは `.backup/pre-p8-6-20261018-100443/` | §5.8, [`p8-6-relink.md`](p8-6-relink.md) §5 |
| **再リンクは P8-6 で作った**（2026-10-18。**合格の線 9**） | `POST /api/locations/relink`（**人だけ**。`mode:'exact'`＝新しいファイル / `'nearby'`＝探すフォルダ。`from_path` で 1 枚が 2 か所以上で切れているときを指定）と **`GET /api/locations/missing`**（**読むだけ**。既定で消した物を外し `excluded_deleted` に数える）。**照合は `sha256` だけ**（`size` / `mtime_ns` は見ない）——**pHash は使わない**（知覚ハッシュは「似た別の絵」を同じと見なすので、**利用者の「同じ絵かどうか」を守れない**）。**ファイルは 1 つも動かさない**（`asset_location` の 1 行を `UPDATE` し、`location_history` に 1 行残す。`is_primary` は触らない）。**（P8-6 の監査 C-2）`nearby` は 2 段**——①**その参照切れを含む置き場** ②見つからなければ**残りの置き場**。**見つかった段で止める**ので、実データの ComfyUI 出力（306 MB）は 1 段目で見つかれば歩かない。**歩いた範囲を返す**（`folders` / `folders_skipped` / `found_in` / `scope`。**黙って捨てない**）。**（C-1）走査で戻ってきたファイルは `missing_at` が外れる**（移動は `mtime_ns` を変えないので走査の早道に落ちる。`asset.deleted_at` は触らない＝**段 2・3 の削除の途中の枚を勝手に戻さない**）。**（C-3）二重登録の見直しは取引の中でもう一度**（規則は `_conflict_of` の 1 か所）。**「自動（走査のたびに繋ぐ）」は作らなかった**（「**勝手に繋がない**」の規律）。**画面は無い（口だけ）**。**トレイ（常駐）はこの段では作っていない**（2026-10-19 に別段で作った＝§16.8） | §5.8, §6.1, §14, [`p8-6-relink.md`](p8-6-relink.md), [`p8-6-audit-triage.md`](p8-6-audit-triage.md), [`duplicates-deletion-backup.md`](duplicates-deletion-backup.md) §4 |

**P8 完了時の数（実測）**: `pytest` **477 件**・`gui_smoke` **291 検査**・`gui_layout` **10 画面＋`pending --ids`**（11 本）
すべて ok。**実データは v6・263 枚・判断 3 件・削除 0 件**（利用者が押した「別物として確定」1 件と「まとまり」1 件は残っている）。
**この 11 本は段 3 の印を立てた複製で回した物**で、**印を外すと `--screen asset` が 3 窓とも NG になる**（`p8-5-audit-report.md` C-2）。

**P8-6（再リンク）を入れた後の数（実測。2026-10-18）**: `pytest` **507 件**（2 回回して 35.9 / 40.5 秒）・
`gui_smoke` **310 検査（2 回ともすべて ok・NG 0）**。**`gui_smoke` の件数は P8-5 の条件の直しが並行して入った時点の物**。
**実データは v6・263 枚・判断 3 件・`missing_at` 0 件**（P8-6 の作業で**行は 1 つも変わっていない**）。

---

### 16.7 P9（仕上げ）・P10（削除の後始末）で確定したこと（2026-10-18 / 2026-10-19）

**正は [`p9-implementation.md`](p9-implementation.md)**（測り方・生の値・届かない物・見送った物）。
ここには**設計として効く決定**だけを置く。**（P9 の監査）の印は、監査の指摘を直してから
`docs/p9-audit-triage.md` で書き戻した決定**。

| # | 決めたこと | 中身 | 根拠 |
| --- | --- | --- | --- |
| 1 | **`PRAGMA temp_store = MEMORY` を入れる** | §12.2 に最初から書いてあったのに実装に無かった。**1 万枚では `ORDER BY` が一時ファイルを作りに行き、`%TEMP%` に書けない置き場で `GET /api/assets` が 500 になる**（実測）。`mmap_size = 268435456` も入れた | §12.2, `db.py` |
| 2 | **`PRAGMA cache_size = -65536` は入れない**（**理由は速さだけ**） | §12.2 の 4 行のうち**これだけ入れなかった**。**実利が無い**（1 万枚の SQL 3 本が 43.6 → 42.5 ms。一覧の 244.7 ms は `store.assets()` の dict 組み立てが主因）。**（P9 の監査 C-1）前の理由「既定の 2 MB なら壊れを見つける」は誤りだった**——既定でも、キャッシュに収まる 0.65 MB の DB では書き込み用の接続が見落とす。いまは `_refuse_if_broken()` が**新しい読み取り専用の接続**で `quick_check` する | §12.2, `db.py`, `tests/test_backup.py` |
| 3 | **`sqlite_error_handler` の語彙を分ける**（P8-6 の監査 D-8。**P9 の監査 D-1 / D-2 で 3 分岐に**） | `sqlite3.DatabaseError` は `IntegrityError` / `OperationalError` の**親**なので、**壊れていない DB にも「バックアップから戻してください」と写していた**（実測: `unable to open database file` が `reason: malformed` の 503 になった）。**壊れている仲間**（`malformed` / `not a database` / `corrupt` / `encrypted`）だけ 503。**`disk i/o error` は 503 `io_error` ＋ `Retry-After`**（**復元を勧めない**。D-1 / G-6）、**`database is locked` は 503 `busy` ＋ `Retry-After`**（D-2）、**他は 500 `sqlite_error`**（文言に復元を出さない） | §6.1, `api/__init__.py` |
| 4 | **一覧で切った枚数を画面に出す** | 一覧は `limit=2000` で引くので、**1 万枚では 2000 枚で切れる**。実測で**上部が「10000 枚」と言いながら 2000 枚しか出していなかった**。`total > listed` のときだけ「10000 枚（先頭 2000 枚を表示）」と出す（**数を黙って捨てない**） | §12.2, `frontend-design.md` §6 |
| 4b | **（P9 の監査 C-2）画面に出す「枚」は 1 つの規則＝生きた枚** | 上部バー・左の「すべて」・下部バーの枚数を `GET /api/assets` の `total`（**段 1〜3 で外した枚を含まない**）に統一した。実データは `asset` 455 行のうち **193 行が段 1 で外れていて生きた 262 枚**で、直す前は**同じ画面に 262 と 455 が並んだ**。規則は `apps/gui/counts.js` の 1 か所（純粋関数）。**「すべて」の数を 455 に戻さない** | `frontend-design.md` §6, `apps/gui/counts.js`, `tools/gui_smoke.mjs` |
| 5 | **1024px サムネイルの目標を 25 分（1 スレッド）と決めた** | 実測 **130 ms/枚**（実画像 1.15 MB。実装者 128・監査 131・P9 の再測 130）→ **21.7 分**。**（P9 の監査 C-3）「同時 8 本なら 3.5 分」は実装の値ではない**——`probe_p9.py` が**道具の中で** `ThreadPoolExecutor` を回した見込みで、**§12.2 のスレッドプールは未実装**。§12.1 は「1 スレッド（実測）／並列は未実装（見込み）」と書き分けた | §12.1, §12.2 |
| 6 | **`--include-library` は 5 分以内・`nearby` は 3 秒以内** | **（P9 の監査 D-5）`--include-library` は 0.63〜2.40 秒 / 291.1 MB**——OS のファイルキャッシュで 4 倍違うので**両方書く**（実装者 2.40 秒＝132 MB/s・監査 0.63 秒＝516 MB/s・再測 0.68 秒＝427 MB/s）。`nearby` は 39〜45 ms（1 万枚） | §12.1, §12.3 |
| 7 | **一覧 API の p95 20 ms は届かない（下げない）** | 実測 **244.7 ms**（監査 252.6・再測 260.6。画面の `limit=2000` は 277.6〜305.7）。**`/api/stats` も p95 134.6 ms**（P9 の監査 D-6 で §12.1 に足した）。理由は **§12.2 のキーセット改ページ・概算の件数・最小の列が実装に無い**こと。**必要な条件を §12.1 に書いた**（入れる段を別に立てる。`total` の意味と絞り込みが変わるので、テストと画面の前提を一緒に直す） | §12.1, §12.2 |
| 8 | **exe 化は今は作らない（推奨）** | `--onedir` は**作れる**（PyInstaller 6.22.3 が Python 3.14 で動く。16.4〜23.7 秒・**138.3 MB（= 131.9 MiB）**・116 ファイル）。起動は **0.53 秒**（**冷えた 1 回目は 1.71 秒**。いまの `uv` 経由は 1.05 秒）。**（P9 の監査 D-7）単位と冷えた値を書き分けた。** しかし `apps/gui` の解決が 1 か所足りず、束ねた物は `gui_present: false`（画面が出ない）。配布しないなら**要らない**。必要になったときの作業一覧は `p9-implementation.md` §6 | §14, `p9-implementation.md` §6 |
| 9 | **768px の上部バーは見送る** | **溢れは 0**（`gui_layout --screen library` の `pageOverflow` と `topbarOverflow` が 0）なので**実害が無い**。**3 行に折り返す**見た目の問題で、直すには狭い窓の検査（`VIEWPORTS` は 1200 以上しか無い）から作る必要がある | `p9-implementation.md` §5 |
| 10 | **（P9 の監査 C-1）走ったまま壊れた DB の入口は「新しい読み取り専用の接続」で見る** | `BackupService._refuse_if_broken()` の `quick_check` を `quick_check_on_disk()`（`file:...?mode=ro` を**新しく 1 本開く**）に変えた。**書き込み用の接続は自分が書いたページをページキャッシュに持ち、外から潰されたページを読み直さない**——既定の 2 MB に収まる 0.65 MB の DB では**見落として控えを取り、`read_only` にならなかった**（監査の実測。28 通りすべてで新しい接続なら見つかる）。**「混んでいる」（`database is locked`）は `read_only` に切り替えない**（一時的な錠を永久の停止にしない） | `backup.py`, `tests/test_backup.py::test_a_page_in_the_writers_cache_is_still_noticed` |
| 11 | **（P9 の監査 C-3）`state=kept` の絞り込みは「正しい条件で測り直す」** | `make_synthetic_db.py` の `seed_rows()` が `asset.review_state` を直接 `UPDATE` していたので、起動時の `reconcile()`（**台帳が正**）が全部 `unreviewed` に戻し、`GET /api/assets?state=kept` は**0 件への絞り込み**を測っていた。判断を `ReviewService.apply_asset()` で**台帳に入れる**形に直し、`probe_p9.py` は**返った件数を出して 0 件なら落とす**（1 万枚で **1429 件**・p95 289.9 ms） | `tools/make_synthetic_db.py`, `tools/probe_p9.py`, §12.1 |
| 12 | **（P9 の監査 D-3）計測の道具はパスを絶対にしてから使う** | `probe_p9.py` の `--out` / `--synth` / `--replica` に相対パスを渡すと、`check_backup_dir()` の「絶対パスで指定してください」（422）で `--library` が落ち、**日次のタイマーも黙って失敗していた**（stderr だけ）。`Path(...).resolve()` を 3 か所に通した | `tools/probe_p9.py` |
| 13 | **（P9 の監査 G-5）日中に外した枚は「いま取る」でその日の控えに入れる** | 日次は**日付が変わったとき**に 1 回なので、日中（実データでは 20:04〜20:12 JST）に段 1 で外した 193 行は **00:00:15 JST の控えまでどの世代にも入っていなかった**。**段 1・段 3 の直後に 1 行だけ案内する**（「設定の『取り直す』で今すぐ取れます」）。**自動では取らない**（数百 MB を勝手に写さない）。段 2 では出さない | `apps/gui/pending.js`, `frontend-design.md` §6 |

- **（C-2。2026-10-19 の日本語 UI の監査の指摘）** 上の行が案内するボタンは**画面に無い「いま取る」だった**
  （P8-5 で画面の語を「取り直す」に統一した後も、この 1 行だけ古い語を案内していた）。
  **`pending.js` の 1 行と `frontend-design.md` §6 の行を「取り直す」に直した**（`docs/japanese-ui-fix.md`）。
  **`docs/p8-design.md`（履歴）と `backup.py` / `api/backup.py` の注記には「いま取る」が残る**（利用者に見えない）。
| 14 | **（P9 の監査 D-8）読み取り専用に切り替えた後は失敗を二重に記録しない** | `_mark_broken()` が記録済みなのに `_failed()` がもう一度 `_record_error()` を呼び、`transaction()` の 503 で**トレースバックがログに積まれていた**（実測）。`code == 'read_only'` の断りは記録しない | `backup.py` |

#### P10（段 1 の行を後から進める・実体が無い行を片付ける）で確定したこと（2026-10-19）

**正は [`deletions-advance.md`](deletions-advance.md)**（決めた点・設計の穴・複製で通した線 14 件）。
利用者の要望（**一度カタログから外した物をゴミ箱へ／実体が無い物を片付ける**）で、
**段 1 が行き止まりだった**のを塞いだ（段 1 の行は一覧から隠れて選び直せず、`#/pending-deletes` の各行にも
「戻す」しか無かった）。**口は 4 つで、足したのは `POST` だけ**（`GET` は 1 バイトも書かない）。
画面の文言は [`frontend-design.md`](frontend-design.md) §4.6・§6 を**先に直してから**実装した（家風）。

| # | 決めたこと | 中身 | 根拠 |
| --- | --- | --- | --- |
| 1 | **段 1 → 2 は後から進められる** | `POST /api/deletions/{id}/advance`（`{stage:2}`）と `POST /api/deletions/advance`（`{ids,stage:2}`）。**既存の段 2 と同じ道**（`_destination()` ＋ `move_no_clobber()`＝`os.rename` で `<data>/trash/<日付>/<ハッシュ>/` へ）で、**上書きしない**（409 `target_exists`／別ボリュームは 409 `cross_volume`）。**台帳を先に書いてから動かし**、動かせなければ `_unadvance()` で段 1 に戻す。**「戻す」がそのまま効く** | §6.1, `deletions.py` |
| 2 | **段 3 への直行は作らない** | まとめての口も含めて `stage` は **2 だけ**（他は 422 `bad_stage`）。段 3 は**置き場ごとの許可（`root.allow_stage3`。Q8 の利用者の意思表示）と凍結**が要る既存の道のままにする（許可を飛ばす近道を作らない） | §6.1, §16.6 |
| 3 | **片付けは「この行のファイルがどこにも無い」ことを確かめてから** | `POST /api/deletions/{id}/close`（`{reason:'missing'}`）と `POST /api/deletions/close`。**登録した場所・元の場所・アプリのゴミ箱・一時置き場のどこにも、その行のファイルが無い**ことを確かめてから `closed_at` / `close_reason` を書く。**ファイルは 1 つも消さない・動かさない**。`asset.deleted_at` はそのまま＝**カタログに戻さない**。**その行のファイル**がまだ在れば 409 `file_found`（**生きているファイルを片付けない**）。**閉じた行は「最近の削除」から外れ、台帳 `GET /api/deletions` には残る** | §5.8, §6.1 |
| 4 | **片付けた後の `undo` は 409**（**ファイルが戻っていれば開き直す**。監査 A-3） | 段 1 は**ファイルを見ない**ので、閉じた行の `undo` を通すと**実体の無い枚がカタログに戻り「参照切れ」が並ぶ**。`already_closed` で断る（**幽霊を戻さない**）。**（P10 の監査 A-3）ただし「ファイルが戻ってきた」行は戻せる**——①**走査**が `missing_at` を戻したときに `deleted_at` を引き直す（`should_hide()`。閉じた行は隠す理由に数えない）、②走査の前でも、**実体が在り登録も生きていて大きさも台帳と一致する**段 1 の行は `undo` が**開き直して**戻す。**ファイルが無い間は今までどおり 409** | §6.1, `scan.py` |
| 5 | **1 回 200 件（人にも同じ規則）** | `MAX_BATCH_PER_CALL = AGENT_MAX_BATCH`。超えたら **422 `too_many` で 1 件も進めない**（部分適用しない）。要望の「エージェントと同じ規則」は**値ではなく規則の形**と読んで、人にもそのまま当てた。**画面は 200 件ずつに分けて送る**（実データの 194 行は 1 回で収まる） | §6.1, `deletions-advance.md` §2-1 |
| 6 | **古い `asset_id` の行でも進められる（`_target_for_advance`）。ただし台帳の行が指す物かを照合する（監査 A-1）** | 台帳の `asset_id` は**走査で古くなる**（走査が同じ場所を別の `asset` として登録し直すため。実データの段 1 で**実体が在る 7 行のうち 6 行**がこの形）。`delete()` の `_target(asset_id, path)` は 409 `not_registered` を返して**永久に進めない**ので、`advance` は**いま登録されている行**を引く。**ただし「別のファイルを移さない」守りは `(size, mtime_ns)` の照合だけでは足りない**——その 6 行は**利用者が消した画像の実体がもう無く、同じ場所には別の画像 Y が登録されて一覧に見えている**ので、**台帳の `size`** と**いまその場所を登録している枚**を照合し、合わなければ **409 `different_file`**（「ファイルが無いので片付ける」を案内）。**`close` も「この行の画像が在るか」で見る**（別の画像を「まだ在る」と数えない） | `deletions.py`, `deletions-advance.md` §3-1・§7 |
| 7 | **画面の語は「ファイルが無いので片付ける」** | 要望の語は「実体が無いので片付ける」だが、`frontend-design.md` §6.1 の**規約 4 が「実体」→「ファイル」を決めている**（§17 の画面の語）。**要望の語のままにしていない唯一の点**（規則が正）。段 2 の行にも同じボタンを出す（ゴミ箱の中身をエクスプローラーで消したときの後始末） | `frontend-design.md` §4.6・§6, §17 |

#### P10 の監査（Fable、2026-10-19。**判定: 直してから次へ**）で確定したこと

**正は [`p10-audit-triage.md`](p10-audit-triage.md)**（指摘ごとの仕分け）と
[`p10-audit-report.md`](p10-audit-report.md)（実行込みの監査）。**推奨はすべて採用した。**
**A-1 は利用者のファイルを壊し得る穴**だった（下の 1 行目）。

| # | 決めたこと | 中身 | 根拠 |
| --- | --- | --- | --- |
| 8 | **（A-1）advance は台帳の行が指す物かを照合し、合わなければ 409 `different_file`** | 台帳の `size` と、**いまその場所を登録している枚**（`asset_location.asset_id`）の両方を見る。**別の画像 Y のファイルをゴミ箱へ移して Y を一覧から消していた**（実データの 6 行。`(size, mtime_ns)` の照合は現在の登録としか比べていなかった）。断りの文は「**消した画像はもうこの場所に無く、別の画像があります。「ファイルが無いので片付ける」で、この行を終わりにできます。**」＝**そのまま次の一手を案内する** | `deletions.py` `_require_file_for_advance()`, `p10-audit-report.md` A-1 |
| 9 | **（A-1 / C-1）`close` は「この行の画像が在るか」で見る** | 登録の場所と台帳の鍵は、**`asset_location.asset_id` が台帳の枚と同じ**で**大きさも台帳の `size` と一致する**ときだけ数える。`to_path` / `hold_path` は**1 回の削除に固有**なので在れば数える。**これで実データの 6 行が片付けられる**（別の画像で `file_found` にならない） | `deletions.py` `_files_of_row()`, `p10-audit-report.md` A-1・C-1 |
| 10 | **（A-2）「戻す」は台帳の枚と、いまその場所に登録されている枚の両方の印を引き直す** | `advance` / `delete` は**いまの登録**に `deleted_at` を立てるのに、`_restore()` は**台帳の枚 X だけ**を同期していた。**実体が戻り登録も生きているのに、Y がカタログから永久に消える**（`undo` は `already_restored`、走査は `missing_at` しか戻さない）。A-1 を直すとこの道は塞がるが、**二重の守り**として直した | `deletions.py` `_sync_hidden_with_location()`, `p10-audit-report.md` A-2 |
| 11 | **（A-3）片付けた行は、ファイルが戻れば戻せる** | ①`_should_hide()` と `_live_stage1()` で**閉じた行（`closed_at`）を隠す理由・生きた段 1 の行に数えない**（実体が無い間は `live == 0` で隠れたまま＝**幽霊は戻らない**）②**走査が印を戻したとき `deleted_at` を引き直す**（`scan.py` は `deletions.sync_hidden()` を呼ぶだけ。**規則は 1 か所**）③走査の前でも、実体が在り登録も生きている段 1 の行は `undo` が**開き直して**戻す。**実データを走査すれば 1 回で戻る** | `scan.py`, `deletions.py`, `p10-audit-report.md` A-3・G-2 |
| 12 | **（B-1）二度押しで POST を 2 回飛ばさない** | `advance` / `closeRow` / `runBatch` に `busy` が無く、**2 回目の応答が 1 回目の結果の文を上書き**していた（1 回の操作が成功しているのに「既にアプリのゴミ箱へ移しています」の赤／まとめては**6 枚動いたのに「0 件」**）。`await` の前に `busy` を立て、確認も 1 回だけにする。`gui_smoke` に**2 連打で POST 1 回**の検査を足した | `apps/gui/pending.js`, `p10-audit-report.md` B-1 |
| 13 | **（B-2）まとめて・`close` も `delete_request` に 1 行残す** | 記録の「`actor` は `delete_request` に残す」は**4 つの口のうち単発の `advance` だけ**だった（誰がいつ 187 行を終わりにしたかが台帳の `closed_at` にしか残らない）。**1 呼び出し 1 行**（`count` = requested、`result_json` に `skipped` も。`stage` は対象の段。片付けは段が無いので揃っていればその段）。**断った要求は残さない**（`advance` と同じ） | `deletions.py` `_run_many()` / `close()`, `p10-audit-report.md` B-2 |
| 14 | **（C-3）片付けた段 3 の行はタイマーからも外す** | `close` で `purge_at` / `remaining_sec` を NULL にする（`stuck` と同じ扱い）。残すと「閉じたのに窓が動いている」行になり、`tick()` が `decremented` に数え続ける。画面は段 3 に「片付ける」を出さないので API 直打ちの道 | `deletions.py` `_close_one()`, `p10-audit-report.md` C-3 |
| 15 | **（D-1・D-2）数を実際に起きたことに合わせる** | **D-1**: まとめての再送で**既に片付いていた行**は成功に数えたままだと「2 件を片付けました。」と嘘に見えるので、`replayed_count` を分けて返し「**2 件は既に片付けていました。**」と足す。**D-2**: 1 件も選んでいないときは「選んだ 0 件」ではなく「**選んだ行はありません**」（数ではなく状態を言う） | `deletions.py`, `apps/gui/pending.js`, `p10-audit-report.md` D-1・D-2 |
| 16 | **（D-3）口の有無の検査は 404 と 405 の両方を許す** | `GET /api/deletions/advance` の 404 は**GUI の静的マウント**が返していた（`apps/gui` が無いと 405）。**口そのものは `openapi()` の経路で見る**（`app.routes` は取り込んだルーターを畳まない） | `tests/test_deletions_advance.py`, `p10-audit-report.md` D-3 |
| 17 | **（C-2）不安定だった 1 件は別件として先に直した** | `test_the_stuck_reason_says_why_it_could_not_go_back` は**時計の刻み**（0.3 ms 後の書き直しが同じ `mtime_ns` に落ちる）が原因で、**実装は仕様どおり**だった（`(size, mtime_ns)` で見る＝§8.4 F4 の規則の限界）。テストの**前提**を `os.utime` で固定した（`docs/stuck-reason-fix.md`。`deletions.py` は 1 行も変えていない） | `tests/test_deletions.py`, `docs/stuck-reason-fix.md` |
| 18 | **（F）監査が見つけたテストの穴を埋めた** | ①段 3 の行（保留に実体）の `close` が 409 `file_found`（A3）②**ファイルが戻った閉じた行**の `advance` が 409 `already_closed`（A14）③**台帳の枚と現在の枚が違う**行の `advance` が 409 `different_file` で、`close` で終われる ④走査で一覧に戻る（A-3）⑤`undo` の開き直し ⑥二度押し（B-1。`gui_smoke`）。**どれも壊すと落ちる**ことを変異で確かめた | `tests/test_deletions_advance.py`, `tools/gui_smoke.mjs`, `p10-audit-report.md` F |

**実データの数（2026-10-19 の実測。`mode=ro` で読んだだけ）**: `asset` **461 行**（生きた **267 枚**）・
段 1 の生きた行 **194**・**実体が在るのは 7 行**（うち 6 行が上の古い `asset_id` の形＝**別の画像 Y が
見えている**。利用者が消した X の実体は無い）・実体が無いのは 187。**（P10 の監査 A-1 で直した後）**
まとめて片付けると **193 件が閉じ、1 件だけ 409 `file_found` で断られる**（その 1 件は
「アプリのゴミ箱へ移す」で進める。移した後も**アプリのゴミ箱に実体が在る間は片付けを断る**＝
ゴミ箱を空にするのは利用者）。**別の画像 Y は 1 枚も動かない**（advance は 6 行とも 409
`different_file` で断る）。**列 `closed_at` / `close_reason` は実データにまだ無い**（§5.8）。
押す前にこの内訳を画面で確かめられる形にしてある（「**193 件を片付けました。**」＋
「**1 件はファイルがまだあるので片付けませんでした。**」＝**数を黙って捨てない**）。

---

### 16.8 トレイ（タスクトレイ常駐）を作った（2026-10-19）

**正は [`tray.md`](tray.md)**（作った物・使い方・自動で確かめた結果・手で確かめた結果・設計の穴）。
P8-5 で「**常駐の実装が無いので作らない**」と決め（§16.6）、`frontend-design.md` §3・§4.5・
§4.6・§11 から入口を外していた。**利用者の「常駐して、タスクトレイから開けるように」で作った**（P11 相当。
§14 の表の段ではない追加＝P8-6・P10 と同じ扱い）。**アプリのコード（`src/`）は 1 行も変えていない**。

| 論点 | 決定 | 理由・根拠 |
| --- | --- | --- |
| 何で作るか | **`tools/tray.ps1`**（Windows の PowerShell + .NET の `System.Windows.Forms.NotifyIcon`） | **新しい依存を足さない**（`pystray` も PyInstaller も要らない）。§4 の依存表を直した |
| サーバの持ち方 | **子プロセス**（プロセス内に uvicorn を抱えない） | **既に動いているサーバに繋げる**（抱えると二重起動しか選べない）。§4.1 の旧案を覆した |
| 起動の判断 | `GET /api/health` の `app` が `image-reviewer` なら**繋ぐ**／別のアプリなら**起動しない**／応答が無ければ**起動する** | 点検 C21 の規則をそのまま使う（**ポートが使えるかでは判定しない**） |
| 止める | **自分が起動した子だけを木ごと**（`taskkill /PID <自分の子> /T /F`）。**PID は 2 つ持つ**（`.venv\Scripts\python.exe` は uv の**踏み台**で、本体はその子＝実測） | **ポート番号から相手を探して止める道を作らない**（利用者が自分で立ち上げた 8790 を巻き込まない） |
| メニュー | **「ブラウザで開く」「最近の削除を開く」「状態を見る」「再起動する」「終了する（サーバも止める）」**。添付のときは「トレイを閉じる（サーバは止めない）」＋再起動は押せない | `frontend-design.md` §6.1 の規約 3（**押すと何かが起きるボタンは終止形**）。`design.md` §4.1 の 3 つ（開く・最近の削除・停止）を含む |
| 気づき方 | アイコンの形 4 通り（要求あり／取り消せる削除あり／両方／なし）＋**バックアップに失敗している間は枠を `--drop`**＋**停止中は × の印**。ツールチップは `image-reviewer（稼働中）、要求 3、最近の削除 12`。変わったときだけバルーン（**自分が起動したサーバが落ちたときも**＝監査 B-2） | §4.1・`frontend-design.md` §4.5（**件数は出さない**）。**音は使わない**（§16.1） |
| **「取り消せる削除」の定義（監査 G-1(b)）** | **アイコンとバルーンが数えるのは段 3（5 分の窓がある行）だけ**。**ツールチップと状態の窓は全部の数**（段 1〜3） | 段 1 の行は片付けても消えないので、全部を数えると**実データの複製では印が常に点いた**（194 行が全部段 1）。「いま見て」の印に値するのは期限で消える物だけ |
| 状態の窓 | 「状態を見る」で**小さな窓**。`/api/health` と `/api/backup` の要点＋**バックアップの失敗は必ず全文つきで出す**。**確かめられなかった回は「（確かめられませんでした）」**。**止めない相手（他人が立った形）はそう言う**（監査 C-2・C-4） | 家風「**黙って失敗しない**」。上部バーは 1 行だが、この窓は読むための場所 |
| 記録 | `<リポジトリ>\.tray\tray.log`・`server.log`・`server.err.log`（**前の 1 世代は `*.prev.log`**。既定以外のポートは `server-<ポート>.log`） | **`.data` には 1 バイトも書かない**。`%USERPROFILE%` の下にも作らない（この環境では書けない＝§6 の罠） |
| 入口 | **既定の起動をトレイにする**（`start-image-reviewer.cmd` → `image-reviewer-tray.cmd`）。**コンソールの起動も残す**（`start-image-reviewer-console.cmd`）。**デスクトップのショートカットの向き先は変えない**（README に手順を 1 行） | 利用者の環境を勝手に変えない |
| 検査 | `tools/tray_selftest.ps1`（**115 検査**。起動・二重起動しない・別のアプリのポート・状態の本文・アイコン・文言・自分の物だけ止める・**競合・親子・メニューの終了の道**）と `tools/tray_drive.ps1`（**実メニューを `PerformClick()` で押す**。ダブルクリックは**実物のイベント**）、`tests/test_tray.py`（契約 **15 件**） | 家風「**壊すと落ちる**」。**変異 13 通りで全部落ちる**ことを実測（`tray.md` §2.2）。**検査は使う 4 ポートが空いていなければ 1 つも起動せず exit 2** |

**この段で分かった罠**（`tray.md` に全部書いた）:

1. **この環境では `.ps1` が素で実行できない**（`RemoteSigned` でも `Unrestricted` でも
   「not digitally signed」で断られ、**`-ExecutionPolicy Bypass` だけが通る**。実測 3 通り）。
   `.cmd` からは必ず `-ExecutionPolicy Bypass` を付ける。
2. **`.ps1` は UTF-8 の BOM 付きで保存する**（PowerShell 5.1 は BOM の無い `.ps1` を cp932 として読む。
   日本語の文字列が壊れて構文エラーになる）。**編集の道具で 1 行直すと BOM が落ちる**ので、
   書き換えたら必ず付け直す。
3. **`.venv\Scripts\python.exe` は踏み台**（47 KB）で、**本物のサーバはその子**。`Start-Process` が返す
   PID と `/api/health` が名乗る `pid` は**別物**（実測）。片方だけ見ると「止めたつもりで生きている」を見落とす。
   **親子は `Win32_Process.ParentProcessId` をたどって確かめる**（`uv run` はもう 1 段深い）。
4. **この環境では「誰も居ないポートへの接続」に約 2 秒かかる**（生の `TcpClient` で実測 2015〜2052 ms。
   生きているポートへは 0 ms）。待ち時間と見張りの周期をこれに合わせた。**1 周期の 4 つの口は 2 秒で見切る**
   （見切らないと、生きていて遅いサーバで 1 回の確認が 15 秒 UI を止めた＝監査 C-2）。
5. **`$Pid` という引数名は使えない**（`$PID` は読み取り専用の自動変数。束縛時に落ちる）。
6. **（監査 A-1）`create_app()` の env 検査は `cli serve` を通す**——`serve_data_dir()` が既定の `.data` を
   明示するので、**道具が `cli serve` を env 無しで起こすと実データを開く**。**実データに 2 列が入った**
   （`deletion_log.closed_at` / `close_reason`。控え無し・行の変化 0）。**道具は子に置き場を必ず明示する。**
7. **検査が途中で落ちると、子のサーバが出力のパイプを掴んだまま残る**（呼んだ側が戻らない）。
   自己検査の先頭に `trap` を置き、**この検査のサーバだけ**片付けて `exit 3`。

---

## 17. 用語

**「画面の語」の列が、画面に出る語の正**（**G-2**。`frontend-design.md` §6.1 の規約 4 が「§17 に載せ、
§5 の判定表で『通じない』の語は一般の語に置き換える」と定めている）。**左の列は設計とコードの語**（コメント・
docstring・API・文書の中で使ってよい）。**画面の語の列が「—」の行は、画面に出さない**。
**「通じない」と判定された 5 語は画面の語を一般語に変えた**（**G-3**。`docs/japanese-ui-audit-report.md` §5 の判定表の
27 語をここに載せた）: 「入れ物」→**絞り込み**、「語釈」→**日本語訳**、「捕獲」→**取り込む**、
「控え」→**バックアップ**、「実体」→**ファイル**。**「まとまり」「要求」「来歴」は残した**（設計の語として一貫し、
文脈があれば通じる。G-3）。

| 語 | 意味 | 画面の語（**正**） |
| --- | --- | --- |
| 画像（asset） | **内容（`sha256`）で同定される画像 1 つ。** 場所（`asset_location`）は従属し、複数あり得る | **画像**（「枚」は助数詞だけに使う。`frontend-design.md` §6.1 の規則 4） |
| **実体** | **その画像のディスク上のファイルそのもの。** 「実体を消す」＝ファイルを消す（段 3）。「実体がありません」＝カタログの行はあるがファイルが無い。**（ワーディング監査 G-5）前の版はこの語を asset の意味にしていて、画面と逆だったので直した** | **ファイル**（**D-5**。「実体 1.7 MB」→「ファイル 1.7 MB」、「段 3 は実体を消す」→「段 3 はファイルを消す」。「実体」は内部の語） |
| 場所（location） | その内容が実在するパス。参照モードと取込モードが同じ表に入る | **場所**（場所が無い枚は「見つかりません」） |
| 種別（kind） | 生成物（`generated`）/ 参考資料（`reference`）/ 写真・スクリーンショット（`photo`）。自動判定し、人が直せる | **生成物 / 参考資料 / 写真・スクリーンショット**（英語の値を出さない。**D-9** で「スクショ」をやめた） |
| カタログ | 仮想フォルダの木。実ファイルの場所とは独立 | **カタログ**（段 1 は「カタログから外す」） |
| スマートフォルダ | 条件で自動的に貯まる仮想フォルダ | —（画面に無い） |
| **キープ** | 気に入ったもの。作品で実際に使うかは別（`kept` / `keep`） | **キープ** |
| **ボツ** | 落とす。理由を付ける（`rejected` / `reject`） | **ボツ** |
| まとまり（review group） | レビューの単位。複数画像。1 枚選ぶ / 全部ボツを決める | **まとまり**（**G-3 で残した**。「グループ」にしない） |
| 判断（decision） | キープ / ボツ / 消す。台帳に追記のみで残る | **判断**（**画面の語は「判断を消す」**。「取り消す」は削除の取り消しにだけ使う） |
| 理由（reason code） | 判断に付ける理由。利用者が編集するマスタ | **理由** |
| **要求（review request）** | エージェントが「これを見て決めて」と出すもの。投げてすぐ返り、判断で閉じる | **要求**（**G-3 で残した**） |
| **注記（annotation）** | 画像の上の矩形・楕円とメモ。座標は 0〜1 の割合 | **注記** |
| 来歴（provenance） | 生成パラメータ、日本語原文、英訳、ワークフロー | **来歴**（**G-3 で残した**。初出は「生成の来歴（モデル・seed・プロンプト）」。**D-13**） |
| 訳し直しの英訳 | 後から訳した英訳。当時の訳ではない（画面で区別する） | **訳し直し**（**D-4**。取り込みの語は「訳を取り込む」） |
| **語釈（gloss）** | Danbooru タグの日本語。タグ用語として通る日本語 | **日本語訳**（**D-2**。「語釈なし」→「日本語訳なし」、「日本語の語釈はまだありません。」→「日本語訳はまだありません。」。**「語彙あり / 語彙外」→「Danbooru の語 / それ以外」**。内部の語は「語釈」） |
| 再現キー（`recipe_hash`） | **（廃止。2026-10-17）** 生成に寄与する部分グラフの hash | — |
| 完全 / 近似 / 不可 | **（廃止）** 書き出すときの判定。**完全＝条件が同一**であり、画素の一致ではない | — |
| L1 / L2 / L3 | **（廃止）** 書き出すグラフの作り方 | — |
| **印（marker）** | **（廃止。2026-10-17）** 書き出したグラフの `filename_prefix` に入れる識別子。**（ワーディング監査 §4）この語は 6 つの物を指していて分からないので、利用者に見える文では使わない。** 物ごとに語を分ける | **物ごとの語を使う**（**G-2 で書き直した**）: 段 3 を許すのは「**許可**」（`root.allow_stage3`）、画像の上の矩形・楕円は「**注記**」、段 1 は「**カタログから外す**」、タグの出どころは「**出どころ**」（PNG / タガー / 手）、代表の推薦は「**おすすめ**」、人が直した日本語訳は「**人が直した**」 |
| 監視（watcher） | ComfyUI の `/api/jobs` を見て、生成の瞬間の値（英訳）と結果を捕まえる仕組み | **監視**（**常駐は作っていない**。画面の文には出さず、訳は「訳を取り込む」で取る。**D-4**） |
| **保留領域（pending-delete）** | 実削除の前に 5 分間だけ置く場所。そこから戻せる | **一時置き場**（**D-7**。「保留領域に実体がありません」→「一時置き場にファイルがありません」。「保留」も使わない） |
| **段 1 / 2 / 3** | 削除の 3 段階（**カタログから外す / アプリのゴミ箱へ移す / ファイルを消す**）。この順に取り返しがつかない（§16.6） | **段 1 カタログから外す / 段 2 アプリのゴミ箱へ移す / 段 3 ファイルを消す**（「実削除」「完全に消す」「用意する」と呼ばない） |
| **窓** | 実削除のあと**取り消せる 5 分**。**アプリが動いていた時間**で数える（スリープ・終了の間は進まない。単調時計） | **あと 3:12**（残り時間。段 3 の行だけに出す） |
| **凍結（preview）** | 一括削除の対象を**1 回だけ解決して保存**した物（`pending_delete_preview`）。**実行時に評価し直さない** | **「消す内容を確かめる」**（確認した一覧） |
| **帯（`phash_band`）** | 64bit の pHash を **4bit × 16 本**に割った物。**距離 ≤ 15 なら必ず 1 本は一致する** | —（画面に無い） |
| **代表** | 重複の群で残す 1 枚。**推薦するだけ**（自動では外さない） | **残す 1 枚**（**D-8**。重複の整理の行のラジオの語） |
| **除外** | 「別物として確定」した組（`duplicate_exclusion`）。**解除できる** | **別物として確定**（解除は「解除する」） |
| sidecar | `<data>/sidecar/<sha256>.json`。**PNG から取り直せない来歴の唯一の置き場** | **バックアップのファイル（sidecar）**（**D-3**。「控え」と呼ばない） |
| **控え** | **（画面では使わない）** バックアップ 1 世代のこと。`backup.py` のフォルダ名と注記に残る | **バックアップ**（**D-3**。1 世代を数えるときは「世代」。「控えは日付が変わったときに取ります」→「バックアップは…」） |
| **入れ物** | **（画面では使わない）** ライブラリの左の列。中身は**絞り込み**（種別・来歴の軸）で、フォルダの木ではない | **絞り込み**（**D-1**） |
| **ゴミ箱** | 段 2 で移す先。**実装は `<data>` の中の置き場**で、**Windows のごみ箱には入らない** | **アプリのゴミ箱**（**G-4**。初出で「アプリの」と書く。OS のごみ箱と混同させない） |
| 置き場 | 登録したフォルダ（`root`）と、バックアップの保存先の**両方**に使っていた語 | **フォルダ**（登録したフォルダ。**D-6**）／**保存先**（バックアップ。**D-6**） |
| 走査 / 再走査 | フォルダを読んで登録すること（`scan`）。**画面に走査を始める入口は無い**（CLI の `scan --root`） | **走査**（「走査中です」「再走査する」。**残してよい**。**C-1** の空の案内はコマンドを出す） |
| **捕獲** | **（画面では使わない）** ComfyUI の `/history` から英訳を取ること | **取り込む**（**D-4**。「訳を捕獲」→「訳を取り込む」、「捕獲中…」→「取り込み中…」、「訳を捕獲していない」→「訳を取り込んでいない」） |
| 指紋（の計算） | pHash を作るジョブ（`hash`）。似た絵を探すための値 | **指紋の計算**（**D-8 は残した**。重複の整理の説明に「絵を読んで指紋を作ります」がある） |
| 台帳 | `deletion_log` など、消した物の記録 | **台帳**（**D-14 は保留**。文脈があれば通じる。「台帳に無いファイルが一時置き場に 1 件あります」） |
| 拾い物 | 台帳に無いファイルが一時置き場にあること | **台帳に無いファイル**（画面の文はこちら） |
| 参照切れ | カタログの行はあるがファイルが無いこと | **見つかりません**（一覧の行）／「ファイルが見つかりません: `<パス>`。判断は残っています。」 |
| 暗幕 / 表 | テーマの設計上の名前（`frontend-design.md` §2.2）。**題材（ベタ焼き）由来で初見では分からない** | **暗い / 明るい**（**C-12**。「テーマ: 暗い」／「テーマ: 明るい」） |
| 密 / 普 / 疎 | 一覧の行の高さ（140 / 200 / 300 px）。`frontend-design.md` §5 | **密 / 標準 / 疎**（**C-13**。「普」の 1 字は日本語の語として立たない） |
| 下ごしらえ | タガーの結果が下書きであること | **下書き**（**D-10**。「タガーの結果は下書きです」。「これは下書きです」と同じ語） |
| さばく | 要求を処理すること | **受ける**（**D-9**。「エージェントが投げた要求をここで受けます」） |

---

## 18. 参考にした既存実装（連携はしない）

この設計を書く前に、`C:\work` 配下の既存プロジェクト（イラスト制作のオーサリング基盤）を
**読み取り専用で調べた**。そこから学んだ考え方は使っているが、
**コード・データ・スキーマ・用語・規約のいずれも合わせない。今後も連携しない**（利用者の回答）。

| 学んだこと | この設計での扱い |
| --- | --- |
| 生成に渡る値だけを正規化して hash にする（再現キー） | 採用。ただし**対象はグラフ**で、独自に定義した（`workflow-reproduction.md` §4.3） |
| 再現の可否を「完全 / 近似 / 不可 ＋ 理由」の 3 値で出す | 採用。理由の語彙はこのツールで定義した（同 §4.5） |
| 再現の合否を人が付ける（閾値をコードに埋めない） | 採用（同 §4.8） |
| 合否がメモリ内だけで消える実装があった | **避けた。** 判断台帳（追記のみ）に載せて消えないようにした（§9.1） |
| 点数制ではなく条件ごとの ○ / × を採る判断 | 参考にした（このツールはキープ / ボツの 1 軸。§9.1） |
| 機械が読んだ印は下書きで、最後に人が見る | 採用（§8.3） |
| 削除の記録を残す | 採用。ただし**5 分の取り消し**という別の安全策を主にした（§16.1） |
| 画像を絶対パスで参照していた | **変えた。** 内容（`sha256`）を正体にして場所を従属させた（§5.1） |
| 語彙をコアに埋め込まない | 考え方として採用（理由マスタと訳の文面を外に出す。§9.2, §7.3.2） |

**接続先は ComfyUI と、利用者が貼った URL だけ。** 他のツールの API もストアも読まない
（`metadata-findings.md` §5。点検 A1 で「ComfyUI だけ」から直した）。

---

## 19. 確かめてほしい点（レビュアー向け）

この設計を点検するときに、次を見てほしい。**点検 → 修正 → 実装**の順で進める。

### 19.1 全体

1. **要件（§1）と設計の対応に漏れや過剰がないか。** 特に R10〜R13（要求・注記・条件の記録・重複と削除）は
   後から足した要件なので、他の節と矛盾していないか。
2. **「他のツールと連携しない」が守られているか。** 文中に連携を前提にした記述が残っていないか（§18）。
3. **工程（§14）の分け方。** P6（要求と注記）を P5 の直後に置く判断は妥当か。
   エージェントが使う機能なので早めに価値が出る、という理由。

### 19.2 データと API

4. **同一性の設計（§5.1）。** 内容（`sha256`）を正体にし、場所を従属させたこと。
   走査のたびにハッシュを計算する費用（実測 1 万枚で 34 秒）に見合うか。
5. **台帳（`decision`）＋現在値のマテリアライズ**という二重持ちが、矛盾を起こさないか。
6. **`review_request` の上書き**（同じ対象なら差し替え、`superseded_by` で残す）が、
   エージェントから見て分かりやすいか。**画像の差し替え**を許したことで曖昧になっていないか。
7. **API の一覧（§6.1）に足りない口、または重複した口がないか。**
8. **外部契約（§6.2）** が、他ツールにとって十分で、かつ余計なものを漏らしていないか。
   要求の状態と画像の種別を入れていない判断（§16.2 の 9・10）は妥当か。

### 19.3 安全

9. **削除の設計**（`duplicates-deletion-backup.md` §3）。確認 1 回 ＋ 5 分の取り消しで足りるか。
   保留領域の置き場所と、アプリが閉じている間に窓が切れたときの扱いは妥当か。
10. **登録ルート外を触らない**規則の実装可能性（正規化、ジャンクション、シンボリックリンク）。
11. **重複検出のしきい値**を実データで決める進め方。

### 19.4 生成の条件

12. **印（marker）の方式**（`filename_prefix` に `repro-<attempt_id>/seed-<seed>`）が本当に安全か。
    再現キーから `filename_prefix` を除外しているので鍵は変わらない、という筋が通っているか。
13. **書き出し前の検査**（モデルとノードの有無を確かめる）で足りるか。他に確かめるべきことはないか。
14. **L1 / L2 / L3 の使い分け**と、訳が変わることの画面での見せ方。

### 19.5 3 回目の点検への申し送り（2 回目の点検者の限界から）

2 回目の点検（Fable）は **`Read` しかできなかった**（この環境で `rg` の起動が拒否され、
`Glob`/`Grep` が使えなかった）。そのため:

- `pytest`、スキーマ検証、性能の再計測、ブラウザでの描画、ComfyUI への接続を**確かめていない**
- Windows の挙動（`os.walk` とジャンクション、`os.replace` と使用中のファイル、`realpath` の大文字小文字）は
  **記憶に基づく**
- 画面の見た目は**描画していない**（構造の話しかできていない）

→ 3 回目を頼むときは **`--allowedTools` に `Bash` を足して、実行して確かめてよいと伝える**。
とくに: `uv run pytest -q` を回すこと、`uv run image-reviewer scan` と `capture` を実データで回すこと、
`/api/*` を実際に叩くこと（サーバは `uv run image-reviewer serve` で上がる）。

### 19.6 画面の設計

15. 画面の設計は [`frontend-design.md`](frontend-design.md) §12 に別の点検項目を置いた。
    そちらも見てほしい（デザインプラン、色、書体、削除の取り消しの見せ方、条件の記録の画面）。

> **この環境の制約（2026-10-19 に確定）**: **アプリのプロセス（`python.exe`）は `C:\work\image-reviwer` の外に書けない**（`os.mkdir` が `WinError 5`。**同じユーザーのシェルや cmd の `mkdir` は書ける**＝**ファイル権限ではなく、環境がプロセスに掛けている制限**）。影響: ①**`<data>` の外にバックアップを置けない**（`settings.backup_dir` は `.backup\daily` のまま） ②**外部（`C:\work\illust-authoring` など）のファイルをゴミ箱へ移せない**（`os.rename` が拒否）→ **利用者がエクスプローラで消してから「ファイルが無いので片付ける」** ③**`%TEMP%` に一時ファイルを作れない** → `PRAGMA temp_store = MEMORY` が必須（P9 で 1 万枚の一覧が 500 になった原因）。**この 3 つは設計の前提を変える**ので、画面と文言はこの前提で書く。
