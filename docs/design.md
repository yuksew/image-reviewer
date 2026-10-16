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
| **R12** | **うまくいった条件を残して再利用する** | `preset`（名前を付けた条件）と、seed 違いのグラフ書き出し。**ツールは生成を実行しない** | [`workflow-reproduction.md`](workflow-reproduction.md) |
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
- **トレイ常駐**。`tray.py` がサーバの起動・停止・ブラウザを開く・要求と取り消せる削除があるとアイコンを変える、を持つ（§4.1）。

---

## 4. 技術選定

| 層 | 選定 | 理由 |
| --- | --- | --- |
| 言語 | Python 3.12 | 内蔵タガーが `onnxruntime-gpu` を必要とする。Pillow でサムネイル。環境に Python と uv がある |
| パッケージ管理 | uv（`pyproject.toml` + `uv.lock`） | 速く、`uv.lock` で固定できる。**注意: DSH の制限下では `UV_CACHE_DIR` をワークスペース内へ向ける必要がある**（既定の `%LOCALAPPDATA%\uv\cache` は書けない） |
| Web | FastAPI + uvicorn | OpenAPI が自動で出る。1 プロセスで画面も配信できる |
| DB | SQLite（stdlib `sqlite3`、WAL）。ORM なし | 数千〜1 万枚なら十分。手書き SQL でクエリを制御する。依存を増やさない |
| トレイ | `pystray` + `Pillow` | アイコンを出すだけ。要求があると形を変える（§4.1） |
| 起動 | `.cmd` のショートカット | 利用者の回答（ショートカットをダブルクリック）。§4.1 |
| 画像 | Pillow（PNG と JPEG は標準で扱える） | 既に導入済み。HEIC / AVIF は今回の対象外 |
| タガー | `onnxruntime-gpu` + `numpy` | ComfyUI を止めずに動かせる。CPU へ落ちる経路も持つ |
| HTTP クライアント | `httpx` | ComfyUI の呼び出しと、利用者が貼った URL の取得（他のツールは呼ばない） |
| 前面 | TypeScript + Vite、**フレームワークなし**（素の DOM） | 仮想グリッドは自前で持つ。バンドルを軽く保ち、起動を速くする。設計は [`frontend-design.md`](frontend-design.md) |
| URL からの取り込み | `httpx`（標準の機能で足りる） | 画像 URL を貼って落とすだけ。ページの解析はしない |
| 対象外（当面） | React / Electron / Tauri / HEIC / AVI | 素の DOM で足りる。exe 化は必要になった時点で判断（§16） |

### 4.1 起動とトレイ（利用者の回答: ショートカットをダブルクリック、トレイに出す）

```text
image-reviewer.vbs                # デスクトップのショートカットの実体（黒い窓を出さない）
  └ pythonw.exe -m image_reviewer serve --port 8790
       ├ サーバを別スレッドで起動（uvicorn）
       ├ トレイをメインスレッドで動かす
       └ 起動を待ってから、既定のブラウザで http://127.0.0.1:8790 を開く
```

**起動方式を確定させる（点検 C20。P0 の完了条件がここに乗っている）:**

| 項目 | 決め |
| --- | --- |
| ショートカットの実体 | **`.vbs`**（`WScript.Shell.Run` で `pythonw.exe` を**窓なし**で起動）。`.cmd` は最小化しても一瞬窓が出るので補助に回す |
| 窓を出さない | `pythonw.exe`（`python.exe` ではない）。**ログは `<data>/logs/serve-YYYYMMDD.log` へ**（標準出力は捨てない） |
| スレッド | **トレイをメインスレッド**（Windows のメッセージループが要る）、**uvicorn を別スレッド**。順序は「uvicorn 起動 → 待つ → トレイ開始」 |
| 停止 | トレイの「停止」は `should_exit` フラグを立て、uvicorn に `should_exit=True` を渡して**同じプロセス内で畳む**（`sys.exit` を別スレッドから呼ばない） |
| 失敗したとき | ログの末尾を**ダイアログとログの両方**に出す（黙って死なない）。`pythonw` は例外が見えないため必須 |
| 二重起動 | 下の識別子の確認で判定する（**ポートが使えるかでは判定しない**） |

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

- トレイのメニュー: 「ブラウザで開く」「最近の削除を開く」「停止」。
  アイコンの形は、**未対応のレビュー要求**があるときと、**取り消せる削除**が残っているときで変える
  （件数は出さない。件数は画面とタブのタイトルに出す）。

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
  missing_at TEXT,                       -- 見つからない（消さずに残す）
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

-- 名前を付けた条件（R12）。人間が参照できればよい（適用やエージェント提供はしない）
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
| `phash_band` | [`duplicates-deletion-backup.md`](duplicates-deletion-backup.md) §2.2 | 準重複の候補を絞る（8bit × 8 本の帯） |
| `duplicate_exclusion` | 同 §2.4 | 「別物として確定」した組 |
| `deletion_log` | 同 §3.3 | 削除の段階・保留領域・取り消し・purge_at |
| `location_history` | 同 §1.4 | 同じパスの内容が入れ替わった事実 |
| `recipe_record` | [`workflow-reproduction.md`](workflow-reproduction.md) §4.9 | 生成条件の記録 |
| `recipe_export` | 同 §4.9 | 書き出したグラフ（印・attempt_id・seed） |
| `recipe_export_result` | 同 §4.9 | 出てきた画像と指標・人の合否 |
| `preset` | 同 §4.10 | 名前を付けた条件 |

> **点検で見つかった誤り**: §5 にこれらが無いのに §14 の工程が前提にしていた。
> 表を**写す**のではなく**参照する**形にして直した（写すと必ず食い違う。実際に
> `asset` 表の写しが `kind` / `source_url` / `ref_tags` を落としていた）。

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

# 条件の記録と再利用（R12。実行はしない）
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

# 重複と削除（duplicates-deletion-backup.md）
GET    /api/duplicates/exact      ?cursor=&limit=
GET    /api/duplicates/near       ?cursor=&limit=&max_distance=6
POST   /api/duplicates/exclude    {a_id, b_id, reason?}       -- PK は (min,max) に正規化して入れる
DELETE /api/duplicates/exclude    {a_id, b_id}
                                  -- **解除の口を用意する**（点検 C10。「別物として確定」を間違えたときに戻せないと、
                                  -- その組が二度と候補に出ない）。順序に依らず同じ行を指すよう (min,max) で正規化
POST   /api/locations             {asset_id, path, kind}       -- 場所を足す
DELETE /api/locations             {asset_id, path, stage:1|2|3}
                                  -- stage 3 は 5 分間取り消せる（保留領域へ移して後で消す）
POST   /api/locations/bulk-delete/preview
                                  {scope:{kind:'folder'|'group'|'query'|'assets', id?, query?, asset_ids?[]},
                                   stage:1|2|3}
                                  -- 対象を 1 回だけ解決して凍結する（点検 A6）
                                  -- → {preview_id, items:[{asset_id, path, size, mtime_ns}], count, bytes,
                                  --     frees:{bytes, at, note}, expires_at}
POST   /api/locations/bulk-delete {preview_id, confirm:true}
                                  -- 凍結した一覧だけを消す。実行時に評価し直さない
                                  -- 1 件ずつ (size, mtime_ns) を再照合し、食い違いは skipped にして
                                  -- **その項目だけ飛ばす**（残りは消す）
                                  -- preview_id は既定 10 分で失効。失効したら何も消さず 409 preview_expired
GET    /api/pending-deletes       -- 取り消せる削除の一覧（残り時間つき）
POST   /api/pending-deletes/{id}/undo
POST   /api/locations/relink      {asset_id, path}             -- 参照切れのつなぎ直し
GET    /api/trash                 ?cursor=
POST   /api/trash/restore         {deletion_id}

# バックアップ
POST   /api/backup                {include_library:false, out?}
POST   /api/backup/restore        {path, force:false}
GET    /api/settings
PATCH  /api/settings              {comfyui_url?, watch?, tagger?, translate?, data_dir?, backup_dir?,
                                   preview_ttl_sec?, undo_window_sec?, theme?, thresholds?}
                                  -- 設定は DB に持つ（ファイルを手で編集させない）
                                  -- backup_dir の既定は <data> の外（点検 B3。§15 リスク 11）
                                  -- preview_ttl_sec は一括削除の凍結の有効期限（既定 600。点検 A6）
                                  -- undo_window_sec は実削除の取り消しの窓（既定 300。アプリ稼働時間で数える）

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

### 6.2 外部参照の契約（R5c）

他ツールが読む口は**2 つだけ**に絞る。どちらも同じ形。

1. `GET /api/export/review.json` — REST。クエリで範囲を絞れる。
2. `<data>/export/review.json` — 同じ内容をファイルにも書く（サーバを立てずに読める）。

契約は [`schemas/review-export.schema.json`](../schemas/review-export.schema.json) に JSON Schema（draft 2020-12）で固定する。

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
| 拡大（ルーペ） | 1 枚を大きく見る。来歴とタグを並べる | キープ / ボツ、理由、タグの語釈、注記、グラフの書き出し、条件の記録 | 同 §4 |
| まとまりレビュー | キープする 1 枚を決める（R6） | 1 枚に決める / 全部ボツ / 保留 | 同 §2.4, §11 |
| 比較 | 2〜8 枚を比べる | 見方の切替、同期ズーム、並び替え、来歴の差分 | [`comparison.md`](comparison.md) |
| 要求の一覧 | エージェントの要求をさばく（R10） | 開いて決める / あとで / 断る | `frontend-design.md` §4.4 |
| 重複 | 完全重複と準重複の整理 | 代表を選ぶ、別物として確定、削除へ | [`duplicates-deletion-backup.md`](duplicates-deletion-backup.md) |
| **条件の記録と再利用** | 生成条件の記録、判定（完全/近似/不可）、印つきの書き出し、結果の照合、合否、プリセット（R12） | 書き出す、結果をひも付ける、合否を記録する、条件をコピーする | [`workflow-reproduction.md`](workflow-reproduction.md)、`frontend-design.md` §4.7 |
| **最近の削除** | **取り消せる削除**（残り時間つき）を常設で見せる | 取り消す、待って消す | `frontend-design.md` §4.6 |
| 取り込み | 走査の設定、進行、失敗の一覧 | ルート追加、参照/取込、URL とクリップボード、走査の開始 | `frontend-design.md` §3 |
| タグ | 語の一覧、件数、日本語の語釈 | 一括タグ付け、語釈の確認と修正 | 同 §8.4 |
| ジョブ | 走査・ハッシュ・サムネ・タグ付け・訳・監視の進み | 中断、再開、失敗の再試行 | 同 §7 |
| 設定 | 接続（ComfyUI のみ）、タガー、閾値、置き場、バックアップ、テーマ | 接続テスト、監視の開始/停止、バックアップと復元 | 同 §5, §11 |

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

| 項目 | 目標 | 実測（出所） | 種別 |
| --- | --- | --- | --- |
| PNG のメタデータ抽出 1 万枚 | **2 秒以内** | 24,719 枚/秒 → 0.4 秒（1,028 枚で計測） | 実測から導出 |
| 内容ハッシュ 1 万枚 | **60 秒以内** | 399 MB/s（**300 枚・410 MB** で計測）→ 1 万枚 **11.1 GB** なら 28 秒 | 実測から導出 |
| 初回走査 1 万枚（ハッシュ＋登録） | **90 秒以内** | ハッシュ 28 秒 ＋ 解析 0.4 秒 ＋ 歩査・DB（未計測） | 実測＋目標 |
| 初回走査 1 万枚（`--no-hash`） | **30 秒以内** | 解析 0.4 秒 ＋ 歩査・DB（**未計測**） | 目標 |
| 2 回目以降の走査（差分なし） | **10 秒以内** | **未計測** | 目標 |
| サムネイル生成 1 万枚（256px） | **6 分以内** | 36 枚/秒（1 スレッド、**256px のみ**）→ 4.6 分 | 実測から導出 |
| サムネイル生成 1 万枚（1024px） | **未定**（実装時に計測して決める） | **未計測** | 未計測 |
| グリッド初回表示 | 300ms 以内（100 枚、**同一 PC の Chrome、開発者ツールのフレーム時間で計測**） | **未計測** | 目標 |
| 追加ページ読み込み | 100ms 以内（100 枚、同上） | **未計測** | 目標 |
| 一覧 API の応答 | p95 20ms 以内（1 万枚の DB、サーバ内で計測） | **未計測** | 目標 |
| 詳細表示（1024 サムネ） | 200ms 以内（生成済み） | **未計測** | 目標 |
| 比較の 8 枚表示 | 400ms 以内（生成済み） | **未計測** | 目標 |
| タグ付け | 0.5 秒/枚（GPU、初回を除く） | **未再計測**（実機の記録値を目標として据える） | 実測（別環境） |
| pHash の全件計算 1 万枚 | 2 分以内 | **未計測**（8ms/枚 は見積り。`comparison.md` §4） | 見積り |
| 日次バックアップ | 5 秒以内 | **未計測** | 目標 |
| 判断の記録 | 100ms 以内（台帳＋現在値。書き出しは除く） | **未計測** | 目標 |

**1 万枚の総量は 11.1 GB とする。** 実測した 1,028 枚は 1.14 GB（1.11 MB/枚）なので、
1 万枚で 11.1 GB。ハッシュの速度を測った 300 枚は 410 MB（1.37 MB/枚）で**全体より大きめ**なので、
その比率を 1 万枚へ外挿した 13.7 GB は**使わない**（点検で 24% の食い違いを指摘された）。
大きめの画像が増えれば増えるほど遅くなるため、**実装時に実データで測り直す**。

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

**一覧**

- キーセット改ページ。`WHERE (sort_key, id) < (?, ?)` の形。`OFFSET` は使わない。
- 一覧で返すのはサムネイル URL と最小限の列。タグは別 API（または先頭 N 語だけ）にして**行を軽くする**。
- 件数は概算を使う（`COUNT(*)` を毎回叩かない）。正確な数が要る画面だけ数える。

**前面**

- 仮想グリッド（見えている行だけ DOM に置く）。`IntersectionObserver` で遅延読み込み。
- 画像は `loading="lazy"`、`decoding="async"`、`width`/`height` を先に指定してガタつきを消す。
- 判断は**楽観的更新**（押した瞬間に印を変え、失敗したら戻す）。
- 進捗は SSE（`/api/events`）。1 秒ポーリングをやめる。

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
    tray.py           # タスクトレイ（起動・停止・ブラウザ・要求があるとアイコンを変える）
    api\              # ルーター（assets / locations / folders / tags / reviews / groups / requests /
                      #          annotations / recipes / presets / duplicates / export / comfyui / jobs / events）
    services\
      catalog.py      # フォルダ、スマートフォルダ、検索
      assets.py       # 走査、登録、ハッシュ、取込（D&D / クリップボード / URL）、参照切れ
      metadata.py     # PNG と JPEG の解析、来歴
      translate.py    # 訳し直し（TextGenerate）、タグの日本語の語釈
      graph.py        # グラフの書き出し、ComfyUI への設置、印の付与、seed の差し替え
      recipe.py       # 記録、判定（完全/近似/不可）、書き出し前の検査、結果の照合
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
| **P7 条件の記録** | `recipe_record` / `recipe_export` / `recipe_export_result` / `preset`、再現キー、判定（完全/近似/不可）、書き出し前の検査、印つきの書き出し、seed 違いの書き出し、監視での結果取り込み、比較、合否の記録 | 条件が記録され、判定と理由が出る。印つきのグラフを書き出せる（**R12**）。**書き出した印から結果の画像が紐付き**、人が合否を記録できる（[`workflow-reproduction.md`](workflow-reproduction.md)） |
| **P8 重複・削除・バックアップ** | 完全重複と準重複の検出、重複の整理、削除の 3 段階、**5 分の取り消し**、再リンク、日次バックアップ、`backup` / `restore` | 重複候補が出て代表を選べる。**実削除のあと 5 分以内なら取り消せ、元の場所に別のファイルがあっても上書きしない**。DB を消しても sidecar と PNG から来歴を組み直せる（[`duplicates-deletion-backup.md`](duplicates-deletion-backup.md)） |
| **P9 仕上げ** | 性能調整、**未計測の項目（1024px サムネ、一覧 API、表示速度）を実測**、テストの締め、exe 化の判断 | **§12.1 の「目標」の行がすべて実測で裏づけられる**。全テスト green |

**順序は点検 G11 で確定**: **P5（判断と比較）を先に**やる。判断がこの道具の主目的で、
来歴の表示はプロトタイプで既に足りているため。P4（タグ）は判断の材料として後から厚くする。
下の表は番号順だが、**着手は P1 → P2 → P3 → P5 → P6 → P4 → P7 → P8 → P9** とする。
**P8（重複と削除）を P5 より先にしない**（重複の整理がまとまりレビューを使うため）。
**P5 の前に A5（エージェントは判断を書けない）を実装する**（台帳の意味が変わるため）。

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
  「元の場所が埋まっていたら**上書きせず別名で戻す**」「起動時に消さない」。
- 一括削除は「**preview で凍結した一覧だけ**を消す」「preview が失効したら何も消さず 409」。
- 書き出しは**スキーマ検証**（`schemas/review-export.schema.json` で `jsonschema` 検証）と**決定性**で確かめる。
  決定性は **`generated_at` を除いて** 2 回出して比べる（時刻を含めたまま比べると必ず落ちる。
  点検で見つかった誤り）。並び順（キー・配列）も同時に確かめる。
- 走査の**制約違反**を確かめる: 同じパスの中身を差し替えて再走査し、`UNIQUE(path)` に当たらず、
  `location_history` に 1 行残り、古い `asset` の判断が失われないこと（§5.1。点検で見つかった誤り）。
- **64bit の値**を確かめる: seed に `18446744073709551615`、pHash に `ffffffffffffffff` を入れ、
  往復して同じ値になること（§5.1 の表）。
- **帯索引**を確かめる: 距離 6 までの組を必ず候補に挙げ、距離 7 でも取りこぼさないこと
  （8bit × 8 本。`duplicates-deletion-backup.md` §2.2。点検で鳩の巣原理の誤りを指摘された）。
- **取り消しの上書き防止**を確かめる: 削除した場所に別のファイルを置いてから取り消しを試み、
  **上書きされずに別名で復元される**こと（`duplicates-deletion-backup.md` §3.4）。
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
| 4 | 参照切れ（画像の移動・削除） | 内容を正体にして場所を従属させる。`missing_at` を立てて消さず、ハッシュで再リンクする。判断は内容に付くので失われない（`duplicates-deletion-backup.md` §1, §4） |
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

## 17. 用語

| 語 | 意味 |
| --- | --- |
| 実体（asset） | **内容（`sha256`）で同定される画像 1 つ。** 場所（`asset_location`）は従属し、複数あり得る |
| 場所（location） | その内容が実在するパス。参照モードと取込モードが同じ表に入る |
| 種別（kind） | 生成物（`generated`）/ 参考資料（`reference`）/ 写真・スクショ（`photo`）。自動判定し、人が直せる |
| カタログ | 仮想フォルダの木。実ファイルの場所とは独立 |
| スマートフォルダ | 条件で自動的に貯まる仮想フォルダ |
| **キープ** | 気に入ったもの。作品で実際に使うかは別（`kept` / `keep`） |
| **ボツ** | 落とす。理由を付ける（`rejected` / `reject`） |
| まとまり（review group） | レビューの単位。複数画像。1 枚選ぶ / 全部ボツを決める |
| 判断（decision） | キープ / ボツ / 取り消し。台帳に追記のみで残る |
| 理由（reason code） | 判断に付ける理由。利用者が編集するマスタ |
| **要求（review request）** | エージェントが「これを見て決めて」と出すもの。投げてすぐ返り、判断で閉じる |
| **注記（annotation）** | 画像の上の矩形・楕円とメモ。座標は 0〜1 の割合 |
| 来歴（provenance） | 生成パラメータ、日本語原文、英訳、ワークフロー |
| 訳し直しの英訳 | 後から訳した英訳。当時の訳ではない（画面で区別する） |
| 語釈（gloss） | Danbooru タグの日本語。タグ用語として通る日本語 |
| 再現キー（`recipe_hash`） | 生成に寄与する部分グラフの hash。判断やカタログを変えても変わらない |
| 完全 / 近似 / 不可 | 書き出すときの判定。**完全＝条件が同一**であり、画素の一致ではない |
| L1 / L2 / L3 | 書き出すグラフの作り方。L1＝捕獲した英文を固定、L2＝グラフごと（訳が変わりうる）、L3＝人が訳を貼る |
| **印（marker）** | 書き出したグラフの `filename_prefix` に入れる識別子。できた画像を書き出しに結び付ける |
| 監視（watcher） | ComfyUI の `/api/jobs` を見て、生成の瞬間の値（英訳）と結果を捕まえる仕組み |
| 保留領域（pending-delete） | 実削除の前に 5 分間だけ置く場所。そこから戻せる |
| sidecar | `<data>/sidecar/<sha256>.json`。**PNG から取り直せない来歴の唯一の置き場** |

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
