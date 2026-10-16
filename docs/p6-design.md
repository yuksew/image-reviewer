# P6 の設計（要求と注記）

- 対象: `C:\work\image-reviwer`（Python + FastAPI + SQLite + numpy + 素の JS の GUI）
- 位置づけ: [`design.md`](design.md) §14 の **P6（要求と注記）**の設計。**この段の正はこの文書**で、
  本文と食い違うときは **§0 が正**。
- 前提: **P5（判断と比較）は完了**（`p5-design.md` と 3 回の監査＋実行込みのやり直し）。
  この段はその上に足す（判断の道筋は変えない）。
- 言語: 日本語。要件は [`design.md`](design.md) §1 の **R10**（要求）と **R11**（注記）。

---

## 0. 拘束力のある差分（この段で決めたこと）

`design.md` の本文と食い違う点、および本文が黙っている点。**実装はここに従う。**

### 0.1 段の分け方と合格の線

| 段 | 内容 | 合格の線 |
| --- | --- | --- |
| **P6-0** | **機能を足さない。** `review_request` / `annotation` の表（v4）、`client_token` の重複検査、契約の更新、`GET` は書かない原則の適用 | 既存のテストが緑のまま。v3 → v4 の移行が**何度でも安全**（`migrate()` を 3 回呼んで同じ） |
| **P6-1** | 要求の受付・上書き・一覧・取得・閉じる（判断で自動）・断る、**要求の一覧画面**、AI の下書きの表示、件数（バーとタブ） | §1 の合格の線 1・2（**R10**） |
| **P6-2** | `annotation`（矩形・楕円）、座標 JSON の書き出し、切り出し画像の書き出し、拡大画面の注記 | §1 の合格の線 3（**R11**） |

- **合格の線は P6-2 まで**。`design.md` §14 の P6 の完了条件が **R10 と R11 の両方**を含むため、
  P5 のように「後半を合格の線から外す」ことはしない。
- **Fable の監査は段ごと**に頼む（3 回）。各段で「実行して確かめた記録」を出す。

### 0.2 要求の応答は**閉じた時点の写し**を保存する（本文は「結果が入っている」としか書いていない）

`design.md` §5.6 の `review_request` に **`response TEXT`（JSON）** を足す。中身は
契約の `ReviewRequestResponse`（`selected_asset_ids` / `reason_code_id` / `reason_label` /
`note` / `annotations`）。

- **理由**: まとまりは `reopen` できる。応答を毎回まとまりの現在値から導出すると、
  **閉じた後に reopen された瞬間、エージェントが受け取った答えが黙って変わる**。
  P5 で「`reason_label` は書き出し時点のマスタ」と決めたのと同じ問題である
  （`p5-design.md` §0.3 C9）。
- したがって **閉じる判断と同じ取引**で `state='done'` / `closed_at` / `closed_by` / `response` を書く。
  `GET /api/review-requests/{id}` は**保存した `response` をそのまま返す**。
- **ただし `annotations` だけは保存せず、読むときに導出する**（点検 B3 / G2）。注記は
  **判断の後に付く**（§1.1 の図のとおり、印は拡大で付ける）。写しにすると、人が「決めてから
  拡大で印を付ける」と、`wants: ["annotations"]` の答えが**永久に空**になる。エージェントは
  `state` が `open` でなくなった時点でポーリングをやめる（§3.4）ので、後から増える性質の欄を
  写しに向けてはいけない。
  - 導出の規則: **`annotation.group_id = <その要求の group_id>` の行の id を `created_at, id` の順**で
    並べた配列。実体は入れない（契約は id と実体の両方を受ける。§6.1）。
  - `selected_asset_ids` / `reason_code_id` / `reason_label` / `note` は**閉じた時点の写し**のまま
    （`reopen` で変わらない。上の理由）。
  - 契約の `ReviewRequestResponse.annotations` に「**後から増えることがある**」と 1 行書く（§6.1）。

### 0.3 上書き（`superseded`）の範囲を狭くする

`design.md` §9.6 は「同じ `target_key` の**未対応**があれば差し替える」と書く。これを次に確定する。

- 差し替えるのは **`state='open'` の行だけ**。`done` / `declined` / `superseded` は**触らない**（履歴）。
- `target_key` が NULL の要求は**上書きしない**（別の要求として積む）。
- 同じ `target_key` の `open` が**同時に 2 本**入った場合は、**新しい 1 本だけを `open`** にし、
  他は `superseded` にする（一意性の回復）。判定と更新は**同じ取引**で行い、
  `CREATE UNIQUE INDEX ... WHERE state='open' AND target_key IS NOT NULL` で**二重 open を DB でも防ぐ**。
- `superseded_by` には**新しい要求の id** を入れる。`superseded` の行は一覧の既定に出さない（§5.1）。
- **順序**: 古い `open` を `superseded` に**更新してから**新しい行を挿入する（点検 C4）。
  逆にすると部分 UNIQUE 索引 `ux_request_target_open` に当たって
  `UNIQUE constraint failed: review_request.target_key` で落ちる（点検の実行で確認。
  UPDATE → INSERT なら 8 本同時でも通る）。判定と更新は**同じ取引**の中で行う（§8.1-3）。
- **古い要求が作ったまとまりの扱い**（点検 A3 / G6）: 要求は必ずまとまりを作る（§0.4）ので、
  差し替えるたびに**誰にも紐づかない `open` なまとまり**が増えてしまう。そこで:
  - 差し替えのとき、**古いまとまりに判断（`decision`）が 1 つも無ければ**、そのまとまりの
    `superseded_by` に**新しい要求の id** を入れる（`review_group` に足す列。§2.1）。
    **判断があるときは触らない**（履歴。消さない）。
  - `superseded_by` が入ったまとまりは、**一覧（`GET /api/groups`）の既定と `review.json` の
    `groups[]` の既定から外す**。`?include_superseded=1` / `include_superseded: true` で出せる。
  - これは `design.md` §9.6 の「**画像の差し替え**（同じ `target_key` で投げ直せば一覧も置き換わる）」の
    「置き換わる」の意味を確定するもの: **要求と、まだ何も決めていないまとまりが置き換わり、
    決めた記録は残る**。

### 0.4 「判断で閉じる」の実装位置

`POST /api/groups/{id}/decide` の**同じ取引**の中で、そのまとまりを対象にした `open` な要求を閉じる。

- 対象の引き方: `review_request.group_id = <decided group>` かつ `state='open'`。
- `reopen` では**要求を開き直さない**（一度答えたら終わり。もう一度求めるなら、エージェントが
  新しい要求を投げる）。理由: 開き直すと「同じ要求に 2 つの答え」ができ、どちらが答えか決まらない。
- まとまりを**作らずに**要求を受ける道は作らない（要求は必ずまとまりを作る。`design.md` §9.6 の
  「別の画面を作らない」を守るため）。

### 0.5 契約（他ツールが読む形）

| 何を | どこに | 理由 |
| --- | --- | --- |
| 要求（`requests[]`）と、その応答の id 一覧 | **既存の** [`../schemas/review-export.schema.json`](../schemas/review-export.schema.json)（`requests` は**任意**のまま。既に `ReviewRequest` / `ReviewRequestResponse` の定義がある） | 決定と要求は**同じレビューの記録**で、他ツールは 1 ファイルで読みたい。`abi` は上げない（**列は足すが、既存の必須は変えない**） |
| 注記の座標 JSON | **新規** `schemas/annotation-export.schema.json` | 1 枚に対して**多数の図形**が入り、寿命も読む相手も違う（エージェントが「どこが変か」を機械で読む）。`review.json` に入れると、全件書き出しが図形の数だけ膨らむ（1 万枚 × 数十図形） |
| 切り出し画像 | JSON ではない（**PNG のファイル**）。`<data>/annotations/<asset_id>/` に置く | 座標だけでは「どこの絵か」が人に伝わらない。ファイル名と対応は §6.3 |

- **`policy` は契約に入れない。** 契約の `ReviewRequest` にも `design.md` の表にも無い。
  `policy` は**要求が作るまとまり**（`review_group.policy`）が持つ。
- **契約に足す欄（点検 C1 / A3。`abi` は上げない）**: どちらも**足すだけ**で、既存の必須も型も変えない。
  - `ReviewRequest` に **`target_key`（null 可）** と **`actor`**（`human` / `agent`）。
    エージェントは `target_key` で自分の要求を識別する（§11）ので、`GET /api/review-requests` の一覧に
    無いと `request_id` を控えておくしかない。`target_key` での絞り込みも足す（§3.3）。
  - `Group` に **`superseded_by`**（差し替えで閉じたまとまりの印。§0.3 A3）。
- **注意**: 契約は `additionalProperties: false` なので、**この契約を読む側は、鍵が増えた版の
  ファイルで落ちる**（点検の実行で確認）。それでも `abi` を上げないのは、**既存の必須・型を
  変えない**ため（読む側が `requests` や新しい鍵を無視できる作りなら影響しない）。
  実装時に `$comment` へ**足した日付**を書く。
- `abi` を上げない理由: 要求と注記は**足すだけ**で、既存の `groups` / `assets` / `reason_codes` の
  必須も型も変えない。読む側は `requests` を知らなくても今までどおり読める（契約の `required` に入れない）。

### 0.6 `GET` は書かない（P5 の監査 C8/G2 を P6 にも適用する）

`design.md` §6.1 は `GET /api/assets/{id}/annotations/export?format=json|crops` と書くが、**分ける**。

| 口 | する |
| --- | --- |
| `GET /api/assets/{id}/annotations/export?format=json` | 座標と文の JSON を**返すだけ** |
| `POST /api/assets/{id}/annotations/export` | `format='crops'` のときだけ**切り出しを書く**（`<data>/annotations/<asset_id>/`） |
| `GET /api/annotations/{id}/crop` | 切り出しを**その場で作って返す**（ディスクに書かない）。画面とエージェントが 1 枚だけ見たいとき |

- 理由: P5 で `GET` がファイルを書いていて問題になった（読み出しに副作用を持たせない）。
  **`GET` は状態を変えない**を、この段の新しい口すべてに適用する。
- 切り出しの**ファイル**が要るのは「他の道具に渡す」ときだけなので、それを `POST` に寄せる。

### 0.7 注記の座標と切り出しの規則（本文は「囲んだ範囲ちょうど」としか書いていない）

- 座標は **0〜1 の割合**。`x` / `y` は**左上**、`w` / `h` は幅と高さ。**丸めない**（`REAL` にそのまま）。
- **領域なしの注記（画像 1 枚へのメモ）を許す**（点検 A1 / G4）。`shape` / `x` / `y` / `w` / `h` を
  **NULL 可**にし、**「全部 NULL」か「全部あり」の 2 形だけ**を許す（表の `CHECK`。§2.1）。
  - **「まとまり全体へのメモ」は P6 では作らない**（§1.3）。まとまり全体のメモは
    `review_group.note`（P5 の `decide` の `note`）が既にある。
  - `POST /api/assets/{id}/annotations` は**座標が無ければ「画像 1 枚へのメモ」として受ける**
    （**422 にしない**）。`body` も座標も無い（何も書いていない）ときだけ 422。
  - **切り出しは領域なしでは 422**（切る範囲が無い。§3.6）。
  - `design.md` は **§5.6 の DDL が `x REAL NOT NULL`、§9.7 が「領域なしの注記も同じ表で扱う」**と
    **本文の中で食い違っている**。この設計は §9.7 を採る。**`design.md` は後で直す**（この文書では触らない）。
- 検証: `0 <= x <= 1`、`0 <= y <= 1`、`0 < w`、`0 < h`、`x + w <= 1 + 1e-9`、`y + h <= 1 + 1e-9`。
  外れたら **422**（`details.fields` に欄と理由）。`1e-9` の余裕は `0.1 + 0.2 <= 0.3` が偽になる類の
  値のため（点検 B1。0.001 刻みの全組では誤判定 0 だったが、1 行で済む保険を置く）。
- 切り出しは**元画像の画素**で。**先に 6 桁へ丸めてから** `floor` / `ceil` する（点検 B1）:
  `left = floor(round(x * W, 6))`、`top = floor(round(y * H, 6))`、
  `right = ceil(round((x + w) * W, 6))`、`bottom = ceil(round((y + h) * H, 6))`。
  それぞれ `0..W` / `0..H` にクランプし、**幅と高さが 1 画素以上**になるようにする。
  - **`left` は `W - 1` まで、`top` は `H - 1` までに抑える**（P6-2 の監査 上位 1）。
    `x` が右端ぎりぎり（`x = 1 - 1e-12`, `w = 1e-12`。**画面で右端までドラッグすると `x + w = 1`
    ちょうどになる**）だと `floor(round(x * W, 6)) = W` になり、`right = min(W, left + 1)` でも
    `right == left` のまま潰れて**幅 0 の画像**を作り、`GET /crop` と `POST export` が
    `PIL.Image … cannot write empty image` で **500** になっていた。`left <= W - 1` なら
    `right = left + 1 <= W` で必ず 1 画素が残る（`top` / `bottom` も同じ）。
    作成（`POST`）は 422 にしない: 右端のドラッグで普通に起きる形なので、**1 画素に丸める**。
  - **なぜ丸めるか**: `x + w` を浮動小数で足してから掛けると、整数になるはずの値が
    `374.00000000000006` のようになり `ceil` が 1 画素余計に返す。幅 **1360**（実データに 1 枚ある）で
    0.001 刻みの **3,170 組**が該当した（1024 / 2048 / 1536 / 768 / 96 は 0 組＝2 の冪と 1000 の約数では
    起きないので、幅を変えないと見つからない。点検の実行）。
  - **楕円も `x` / `y` / `w` / `h` の外接矩形で切る**（点検 D3。「囲んだ範囲ちょうど」は矩形にしか
    意味が無い）。マスクは掛けない。
- **拡大縮小しない・余白を付けない・回転しない。** 出力は **PNG**（無劣化。JPEG にしない）。
  入力が JPEG でも切り出しは PNG にする（判定に使う絵を劣化させない）。
  **圧縮率は `compress_level=1`**（点検 B2 / G7）: 無劣化のまま速い（1024² 全面 66 → **21 ms**、
  2048² 全面 320 → **93 ms**。ファイルは約 1.5 倍。実測は §7）。
- どの実体から切るかは **`compare.py:1101` の `_primary_path()` と同じ規則**
  （`missing_at` が無い場所を優先し、`is_primary` → `path` の順）。実体が無ければ **409**
  （`details.asset_id`。`422` ではない: 要求の形は正しく、いま切れないだけ）。
- ファイル名は `<asset_id>__<annotation_id>.png`（`_safe_name()` を通す）。
  **同じ図形を 2 回書き出しても同じ名前**（上書き。増えない）。
- **注記を消したら、その切り出しの PNG も消す**（点検 G3）。`<data>/annotations/` は
  **キャッシュ**であって記録ではない（§0.8）。残すと、フォルダを読むエージェントが
  **存在しない注記の切り出し**を拾い、座標 JSON と食い違う。他の道具に渡した後の写しは
  渡した側が持つ。消せなかったときは警告だけ出して続ける（消えなくても害は小さい）。

### 0.8 原子性（P5 の `.tmp` の教訓）

切り出しの書き出しは **一時ファイル → `os.replace`**、`os.replace` が失敗したら
**一時ファイルを消してから**投げ直す（`export.py` の `_atomic_write` と同じ形）。
`<data>/annotations/<asset_id>/` の `*.tmp` は**起動時に掃除**する。

- 失わないもの: 座標と文（DB にある）。切り出しは**いつでも作り直せる**（保存はキャッシュ）。
- したがって「書き出しに失敗したらどうするか」は**再試行**でよい（P5 の判断の書き出しのように
  「印を付けて次回に回す」必要は無い。**失うと困るのは図形の座標だけ**で、それは DB にある）。

### 0.9 `client_token` の再送（P5 の確定を踏襲する）

`post` の要求と注記に `client_token` を持たせる。**同じ中身の再送は 200 で既存を返す**（行を増やさない）。
**中身が違う再送は 409 `client_token_conflict`**（P5 と同じ。`p5-design.md` §3.1）。

- **`superseded` フラグは付けない**（P5 の判断と違い、要求には `state` が既に `superseded` を持つ。
  二重に言わない）。
- 再送で返すのは**いまの行**（`state` が進んでいれば進んだ値。例: 再送の間に判断されて `done`）。
- **鍵を持つのは「行を作る口」だけ**（点検 B5）: `POST /api/review-requests` と
  `POST /api/assets/{id}/annotations`。`review_request.client_token` は**作成の鍵**で、
  **1 行に 1 つ**しか入らない（`ux_request_token`）。だから:
  - **`POST .../decline` は `client_token` を取らない**。状態機械が冪等性を与える
    （**同じ `note` で既に `declined` なら 200**、**違う `note` なら 409 `request_not_open`**。§3.5）。
  - **`POST .../annotations/export` も取らない**。同じ名前に上書きするので元々冪等（§0.7）。
  - （残したいなら `decline_client_token` のような**別の列**が要る。P6 では作らない。）

### 0.10 その他、本文が黙っているので決めたこと

| 論点 | 決め | 理由 |
| --- | --- | --- |
| `asset_ids` に**パス**を渡せる | **既存の `store.normalize_path()` を通して** `asset_location.path` と一致で引く（`os.path.normcase(os.path.realpath(str(path)))`。登録時と同じ鍵。点検 C3）。見つからなければ **422** `details.unknown_paths` | `design.md` §9.6 が「パスでも登録済み ID でも受ける」と書いている。**規則を発明しない**——`store.py:39` に登録と参照で同じ鍵を作る関数が既にあり、`Store.location_by_path()`（`store.py:128`）がそれで引いている。別の規則（`casefold` だけ等）にすると、同じファイルを別の表記で渡したときに 422 になりうる |
| `policy` の既定 | `pick_one`（`POST /api/groups` と同じ） | 既存の口と揃える |
| `wants` の未知の語 | **無視する**（422 にしない） | エージェント側の拡張を弾かない。契約は文字列の配列 |
| 注記を付けられる人 | `human` も `agent` も可（`actor` はヘッダから）。**判断だけが `human` 限定** | `design.md` §9.5 が禁じているのは判断。注記は台帳の意味を変えない |
| `annotation` の編集・削除 | `PATCH`（メモだけ）と `DELETE` を許す。**履歴は残さない** | `annotation` は台帳ではない（`decision` と違う）。消えたことを記録する要件が無い |
| 表の制約 | 語彙の欄には **`CHECK` を使う**（既存の表と同じ。`db.py` は `kind` / `policy` / `state` / `actor` / `verdict` など 11 か所で使っている）。状態の遷移の規則（どの状態からどこへ行けるか）は**サービス層で見る** | 語彙は DB でも守る（既存の書き方）。遷移は表に書けないので Python 側 |
| 一覧の `cursor` | **キーセット**（`created_at` と `id` を不透明な文字列にして返す。`next_cursor`） | P5 の台帳は `OFFSET` のまま（監査 D4）。**新しく作る口は最初からキーセット**にする。`created_at` は秒（`db.now()`）だが **`id` は ULID でミリ秒順**なので、`created_at DESC, id DESC` と「新しい順」が一致する（点検 D6。`seq` の列は要らない） |
| `conditions` / `wants` が無いとき | **`[]` を返す**（`null` にしない） | 契約は `type: array` で `null` を受けない（点検 D1。実行で確認） |
| `target_key` / `origin` の長さ | **200 文字まで**（超えたら 422） | `ask` 2000 / `conditions` 50 件と揃える（点検 D4） |
| `DELETE /api/annotations/{id}` の 2 回目 | **404** `details: {"annotation_id": "..."}` | 消えていることを黙って成功にしない（点検 D5） |
| `PATCH` / `DELETE /api/annotations/{id}` の `actor` | **自分の `actor` の注記だけ**（`human` は両方、`agent` は `agent` の注記だけ）。違えば **403** | 人の印をエージェントが消せるのは `design.md` §9.5 の「人が確定する」に反する（点検 C7） |
| 画面の更新 | 画面を開いている間だけ **5 秒ごとに `GET /api/review-requests?state=open`** を叩く（件数・タブのタイトル）。**SSE は作らない** | P5 と同じ（`p5-design.md` §0.1）。音は使わない（`design.md` §16.1） |
| 監査の資料 | 各段で「実行したコマンドと結果」を報告に残す | 実行込みのやり直し（`p5-audit-redo.md`）で、読んだだけの監査が何も守らないと分かった |

### 0.11 利用者の確認待ち（**いまは推奨どおりで進める。朝に覆せる**）

点検（`docs/p6-review-report.md`）の A1〜A3 と G1〜G7 は「利用者が決めること」として上がっている。
**依頼者は就寝中**なので、**推奨どおりで設計を確定し、実装を進める**。覆す場合の影響を「戻し方」に書く。

| # | 論点 | いまの決定（推奨） | 元の選択肢 | 覆すときの戻し方 |
| --- | --- | --- | --- | --- |
| **G4**（A1） | 領域なしの注記をどこまで作るか | **座標 NULL 可で「画像 1 枚へのメモ」まで**。まとまり全体へのメモは P6 では作らない（`review_group.note` がある） | (i) 画像 1 枚まで ／ (ii) `asset_id` も NULL 可でまとまり全体まで ／ (iii) 作らない | (ii) にするなら `asset_id` を NULL 可にし、`group_id` 必須の `CHECK` を 1 本足す（v5 ではなく P6-0 のうちに足せる）。(iii) なら `CHECK` と §1.3 の 1 行を消す |
| **G5**（A2） | まとまりレビュー画面を P6 で作るか | **作る**（`#/group/<id>` の最小形。P6-1 を **P6-1a（API）/ P6-1b（画面）** に割る） | (i) P6-1 に入れて段を割る ／ (ii) 線 2 を API で満たすことにして画面は後段 | (ii) にするなら §1.2 の線 2 を「API で判断して閉じる」に弱め、§9 の P6-1b を落とす |
| **G6**（A3） | 差し替えで残る古いまとまり | **判断が無ければ `superseded_by` を付けて既定から外す**（判断があれば残す） | (i) 印を付けて外す ／ (ii) 残す | (ii) にするなら `review_group.superseded_by` の列と §0.3 の 3 行を消す（列を足さないだけ） |
| **G1** | 切り出しの書き出しを `GET` で受けるか | **`GET` は `format=json` だけ。`crops` は 422 で `POST` を案内** | (i) 422 で案内 ／ (ii) `GET` でも書く ／ (iii) その場で返すだけ | (ii) なら §3.6 の 422 を外す（P5 の「`GET` は書かない」から外れる）。(iii) なら `POST` の書き出しを消し、`GET /api/annotations/{id}/crop` だけにする |
| **G2**（B3） | 要求の応答を保存するか導出するか | **`selected_asset_ids` / `reason_*` / `note` は保存、`annotations` だけ導出** | (i) 保存 ／ (ii) 毎回導出 | (i) だけにするなら §0.2 の導出の 3 行を消す（判断の後に付けた印が答えに入らなくなる） |
| **G3** | 注記を消したとき切り出しの PNG も消すか | **一緒に消す**（キャッシュなので残さない） | (i) 残す ／ (ii) 一緒に消す ／ (iii) 消す＋一括削除 | (i) にするなら §0.7 の最終項と §6.3 の 1 行を戻す |
| **G7**（B2） | 切り出しの PNG の圧縮率 | **`compress_level=1`**（無劣化のまま 3 倍速い） | (i) 既定 ／ (ii) `compress_level=1` | (i) にするなら §0.7 と §7 の数値を既定の実測（1024² 全面 66 ms）に戻す |

- **上の 7 件は「実装を止める」種類ではない**（どれも 1〜3 行で戻せる）。だから先へ進める。
- **点検の A / B / C / D / F はすべて反映済み**（この節以外は反映の印 `（点検 …）` を付けてある）。

---

## 1. 何を作るか（範囲）と合格の線

### 1.1 作るもの

```
エージェント ──POST /api/review-requests──▶ 要求（まとまりを作る）
                                              │
人 ──要求の一覧（#/requests）──▶ 開いて決める ──▶ まとまりレビュー（#/group/<id>）
                                              │  判断（keep / reject ＋ 理由）
                                              ▼
                                    要求は done になり、応答（選ばれた枚・理由・注記）が残る
エージェント ──GET /api/review-requests/{id}──▶ 応答を読む

人 ──拡大（#/asset/<id>）──▶ 印（矩形・楕円）＋メモ ──▶ 座標 JSON / 切り出し画像
```

- 要求は**必ずまとまりを作る**（`design.md` §9.6）。ただし **P5 はまとまりを「決める」画面を作っていない**
  （`apps/gui/index.html:13` に「キープ / ボツ…はまだ入っていません」と書いてある。`app.js` の経路は
  `#/compare` だけ）。したがって **`#/group/<id>` の最小形は P6-1b で作る**（点検 A2 / G5。§5.1）。
  `design.md` の「別の画面を作らない」は「**要求専用の**レビュー画面を作らない（既存のまとまりレビューの流れに乗る）」
  という意味で読む。
- 注記は**判断の理由の代わりではない**（`design.md` §9.7）。理由は §9.2 のマスタから選ぶ。

### 1.2 合格の線（**実行して確かめられる形**）

| # | 線 | 確かめ方（そのまま打てる形） | 合否 |
| --- | --- | --- | --- |
| **1** | エージェントが要求を投げ、**投げてすぐ返る** | `POST /api/review-requests` を 8 枚で 30 回。応答が **p95 150ms 以内**、かつ**すべて `state: "open"` で返る**（判断を待たない） | 30/30 が 150ms 以内。1 件でも `done` で返ったら**落ち** |
| **2** | 要求の一覧から開いて判断し、**判断で閉じる** | 一覧（`GET ?state=open`）→ **`#/group/<id>`（まとまりレビューの画面。P6-1b で作る）**で「この 1 枚に決める」を押す → `POST /api/groups/{id}/decide` → `GET /api/review-requests/{id}` が **`state:"done"`** で、`response.selected_asset_ids` が選んだ 1 枚と一致。**その後 `reopen` しても `response` は変わらない**（`annotations` を除いて比較。§0.2） | 2 つの GET の中身を突き合わせて一致。`reopen` の前後で `response` が**バイト一致**（`annotations` を除く） |
| **3** | 印を囲んでメモを付け、**座標と切り出しを書き出せる** | 1024×1024 と 2048×1536 の絵で `POST /annotations {x:0.25,y:0.5,w:0.25,h:0.25}` → `GET .../export?format=json` が**同じ値**を返す → `POST .../export {format:"crops"}` の PNG が **`ceil(0.5W)-floor(0.25W)` × `ceil(0.75H)-floor(0.5H)`** 画素 | 2 つの大きさで式どおり。座標は**丸めずに往復**（`0.25` が `0.25` のまま） |

- **測れない条件は書かない。** 上の 3 つは数値と手順が決まっている。
- **線 2 は P6-1b（まとまりレビューの画面）で満たす**（点検 A2）。線 1 は P6-1a、線 3 は P6-2（§9）。
- 「気づけるか」（バーの件数・タブのタイトル）は**目視**なので合格の線に数えない（§5.4 に手順だけ置く）。
- §7 の性能目標のうち**未計測のもの**は、P6-1 / P6-2 の各段で**測って記録する**（P5 の P9 と同じ扱い。
  測っていない数値を「達成」と書かない）。

### 1.3 この段で**作らない**もの

- SSE（`GET /api/events`）。画面は 5 秒のポーリング（§0.10）。
- 要求の**編集**（投げ直しは新しい要求。画像の差し替えは `target_key` で上書き）。
- 要求の**既読**の記録（`open` とそれ以外だけ）。**「あとで」は何も書かない**（§5.1 / 点検 C6）。
- **まとまり全体へのメモ**（`annotation` の `asset_id` も NULL にする形）。**画像 1 枚へのメモ（領域なし）は作る**
  （点検 A1 / G4。§0.7）。まとまり全体のメモは `review_group.note`（P5 の `decide` の `note`）が既にある。
- 注記の**自由曲線・回転・複数領域にまたがる 1 つのメモ**（`design.md` §16.1）。
- 切り出しの**一括 zip**、注記の**他の画像へのコピー**。
- エージェントが**判断を書く**道（`design.md` §9.5。P6 でも 403 のまま）。

---

## 2. データモデル

### 2.1 表（`design.md` §5.6 に対する差分）

`design.md` の DDL をそのまま作り、**次の 4 点だけ足す**。**v4** として `db.py` に足す
（`SCHEMA_VERSION = 3` → `4`。`migrate()` は前へだけ進み、何度呼んでも安全）。

```sql
CREATE TABLE IF NOT EXISTS review_request (
  id            TEXT PRIMARY KEY,
  group_id      TEXT NOT NULL REFERENCES review_group(id),
  target_key    TEXT,
  state         TEXT NOT NULL
                CHECK (state IN ('open', 'done', 'declined', 'superseded')),  -- ★CHECK
  ask           TEXT,
  conditions    TEXT,            -- JSON 配列（自由文）
  origin        TEXT,
  wants         TEXT,            -- JSON 配列
  ai_pick_asset_id TEXT,
  ai_note       TEXT,
  actor         TEXT NOT NULL CHECK (actor IN ('human', 'agent')),             -- ★CHECK
  created_at    TEXT NOT NULL,
  closed_at     TEXT, closed_by TEXT,
  decline_note  TEXT,
  superseded_by TEXT,
  response      TEXT,            -- ★追加: 閉じた時点の応答（JSON。§0.2）
  client_token  TEXT             -- ★追加: 再送の鍵（§0.9）
);
CREATE INDEX IF NOT EXISTS ix_request_state ON review_request(state, created_at DESC);
CREATE INDEX IF NOT EXISTS ix_request_group ON review_request(group_id, state);
CREATE UNIQUE INDEX IF NOT EXISTS ux_request_target_open
  ON review_request(target_key) WHERE state = 'open' AND target_key IS NOT NULL;  -- ★追加（§0.3）
CREATE UNIQUE INDEX IF NOT EXISTS ux_request_token
  ON review_request(client_token) WHERE client_token IS NOT NULL;                 -- ★追加（§0.9）

CREATE TABLE IF NOT EXISTS annotation (
  id         TEXT PRIMARY KEY,
  asset_id   TEXT NOT NULL REFERENCES asset(id) ON DELETE CASCADE,
  shape      TEXT CHECK (shape IN ('rect', 'ellipse')),   -- ★NULL 可（点検 A1）
  x REAL, y REAL, w REAL, h REAL,                         -- ★NULL 可（0..1。点検 A1）
  body       TEXT,
  actor      TEXT NOT NULL CHECK (actor IN ('human', 'agent')),                -- ★CHECK
  created_at TEXT NOT NULL,
  group_id   TEXT REFERENCES review_group(id),
  client_token TEXT,             -- ★追加: 再送の鍵（§0.9。行を作る口だけが持つ）
  -- ★追加（点検 A1）: 「全部 NULL（画像 1 枚へのメモ）」か「全部あり（矩形・楕円）」の 2 形だけ
  CHECK ((shape IS NULL) = (x IS NULL)
         AND (x IS NULL) = (y IS NULL)
         AND (y IS NULL) = (w IS NULL)
         AND (w IS NULL) = (h IS NULL)
         AND (shape IS NOT NULL OR x IS NULL))
);
CREATE INDEX IF NOT EXISTS ix_annotation_asset ON annotation(asset_id, created_at);
CREATE UNIQUE INDEX IF NOT EXISTS ux_annotation_token
  ON annotation(client_token) WHERE client_token IS NOT NULL;                     -- ★追加（§0.9）

-- ★追加（点検 A3 / G6）: 差し替えで閉じた**まとまり**の印（判断が無いときだけ入れる）。
-- `review_group.state` の `CHECK` は 'open' | 'decided' なので状態を増やさず、列で表す。
-- `ALTER TABLE` は `IF NOT EXISTS` を持たないので、**列を見てから足す**（v2 / v3 と同じ）
ALTER TABLE review_group ADD COLUMN superseded_by TEXT;
```

- `ux_request_target_open` は **`open` のときだけ効く部分索引**。P5 の実行込み監査で
  `client_token` の部分索引が使えることを実測済み（`p5-design.md` §0.7 F1。`sqlite_version 3.53.1`）。
  **同じ形が使えるかを P6-0 で実測する**（§10-2）。
- 状態の語は `CHECK` で縛る（§0.10）。**遷移の規則はサービス層で見る**（表に書けない）。
- **`annotation` の座標は NULL 可**（点検 A1）。`CHECK` は「全部 NULL」か「全部あり」の 2 形だけを許す
  （片方だけ NULL の行を作らせない）。`asset_id` は `NOT NULL` のまま（**まとまり全体へのメモ**は
  P6 では作らない。§1.3）。
- **`design.md` §5.6 の DDL との差**: あちらは `x REAL NOT NULL` で、**同じ文書の §9.7
  「領域なしの注記も同じ表で扱う」と食い違っている**（点検 E）。この設計は §9.7 を採り、
  `design.md` は後で直す（§0.7）。
- 要求が作るまとまりは **`kind='request'` / `source='request'` / `source_ref=<request_id>`**
  （`create_group()` が既に受ける引数。`db.py` の `review_group.kind` の `CHECK` に `'request'` がある）。
- **`review_group.superseded_by`**（点検 A3 / G6）: 差し替えで閉じたまとまりの印。**判断が 1 つも無い
  まとまりにだけ**入れる（§0.3）。一覧と `review.json` の既定から外すための列で、`state` は増やさない。

### 2.2 現在値の写しは作らない

`review_request` / `annotation` に**写し（マテリアライズ）を作らない**。理由:

- 要求の状態は**要求自身の列**が正（写す先が無い）。
- 注記は追記と削除だけで、**他の表から導出しない**。
- P5 の写し（`asset.review_state`）は「台帳から導けるのに速さのために持つ」ものだった。
  要求と注記にはその必要が無い（件数が桁違いに少ない）。

### 2.3 索引の意図

| 索引 | 何を速くするか |
| --- | --- |
| `ix_request_state` | 一覧の既定（`state='open'` を新しい順）とバーの件数 |
| `ix_request_group` | 判断のときに「このまとまりの open な要求」を引く（§0.4） |
| `ux_request_target_open` | 上書きの一意性（同時 2 本でも `open` は 1 つ） |
| `ix_annotation_asset` | 1 枚の注記一覧（拡大画面）と書き出し |
| `ux_*_token` | 再送で行を増やさない（P5 と同じ） |

---

## 3. API（`design.md` §6.1 の該当行を、ここで確定する）

**すべて既存の middleware の下に入る**（`app.py` の `local_only`）。つまり
`GET`/`HEAD`/`OPTIONS` は **`Host` の許可リストだけ**、`POST`/`PATCH`/`DELETE` は加えて
**`Origin` の同一性**と **`Content-Type: application/json`** を要求する（`design.md` §6.3.1）。

### 3.1 誰が呼ぶか・書くか

| 口 | 誰が呼ぶか | 書くか | 備考 |
| --- | --- | --- | --- |
| `POST /api/review-requests` | **エージェント**（人が試すこともある） | **書く**（要求 1 行＋まとまり 1 行） | `actor` は自己申告（ヘッダ）。**`human` を要求しない** |
| `GET /api/review-requests` | 画面・エージェント | 書かない | 既定 `state=open`、キーセット |
| `GET /api/review-requests/{id}` | **エージェント**（ポーリング） | 書かない | `response` は保存した写し（§0.2） |
| `POST /api/review-requests/{id}/decline` | **人**（画面） | 書く（`state='declined'`） | **`human` 以外 403**。理由（`note`）必須 |
| `GET /api/assets/{id}/annotations` | 画面・エージェント | 書かない | 古い順 |
| `POST /api/assets/{id}/annotations` | 画面（人）・エージェント | 書く | `actor` はヘッダ |
| `PATCH /api/annotations/{id}` | 画面 | 書く（`body` だけ） | 他の欄は 422 |
| `DELETE /api/annotations/{id}` | 画面 | 書く（行を消す） | 200（本文に消した id） |
| `GET /api/assets/{id}/annotations/export` | 画面・エージェント | **書かない** | `format=json` だけ |
| `POST /api/assets/{id}/annotations/export` | 画面・エージェント | **書く**（切り出しの PNG） | `format='crops'` |
| `GET /api/annotations/{id}/crop` | 画面・エージェント | **書かない**（その場で作って返す） | `image/png` |

- **`PUT` は使わない。** 全部を置き換える操作が無い（`PATCH` はメモだけ）。
- **`GET` は状態を変えない**（§0.6）。書き出しの副作用は `POST` にだけ持たせる。

### 3.2 `POST /api/review-requests`

```jsonc
{
  "asset_ids": ["01M4...", "D:\\ComfyUI\\output\\x.png"],  // 登録済み ID でもパスでも
  "group_id": null,            // 既存のまとまりを対象にする場合はその id（asset_ids と排他）
  "target_key": "cut-20261011-031201",   // 任意。同じ鍵の open を差し替える（§0.3）
  "policy": "pick_one",        // pick_one | pick_many | all_reject_only（既定 pick_one）
  "ask": "この 8 枚から 1 枚選んでほしい",
  "conditions": ["左手の形", "背景の窓の位置"],
  "origin": "作品A / カット03",
  "wants": ["selected_ids", "reason", "annotations"],
  "ai_pick_asset_id": "01M4...",
  "ai_note": "手が素直で窓の位置も合っている",
  "client_token": "8b1c..."     // 任意。再送の鍵（§0.9）
}
→ 201 {"request_id": "...", "group_id": "...", "state": "open", "replayed": false}
```

| 条件 | 応答 |
| --- | --- |
| `asset_ids` と `group_id` の**両方**がある / **どちらも無い** | **422** `details: {"fields": {"asset_ids": "どちらか一方が要ります"}}` |
| `asset_ids` に**存在しない ID** | **422** `details: {"unknown_asset_ids": ["..."]}` |
| `asset_ids` に**登録が無いパス** | **422** `details: {"unknown_paths": ["D:\\..."]}` |
| **同じ `target_key` の `open` がある** | **201**（新しい要求）＋ 古い方が `superseded`（`superseded_by` に新しい id）。応答の `superseded_request_id` に古い id |
| `policy` が語彙の外 | **422** `details: {"policy": "pick_one | pick_many | all_reject_only"}` |
| `ask` が 2001 文字以上 / `conditions` が 51 件以上 | **422** `details: {"fields": {...}}` |
| `ai_pick_asset_id` が対象の外 | **422** `details: {"ai_pick_asset_id": "対象の画像ではありません"}` |
| 同じ `client_token` の再送（中身が同じ） | **200** 既存の `request_id` を返す（`replayed: true`。行を増やさない） |
| 同じ `client_token` で**中身が違う** | **409** `code: "client_token_conflict"` |
| `group_id` が無い | **404** `details: {"group_id": "..."}` |
| `group_id` のまとまりが **`decided`** | **422** `details: {"group_id": "決定済みのまとまりには要求できません。reopen してから"}`（点検 C2。`decide` は `decided` に 409 なので、そのまま受けると**永久に `open` の要求**ができる） |
| `target_key` / `origin` が 200 文字超 | **422** `details: {"fields": {...}}`（点検 D4） |

- **検査の順序**（点検 B4。**P6-1a の監査で実装に合わせて直した**）:
  **①対象を引く（`group_id` の存在・`asset_ids` の解決）→ ②`client_token` の照合 → ③業務の検査
  （`decided` の 422・`ai_pick` の 422・`policy` の不一致 422）→ ④差し替え → ⑤`INSERT`。**
  照合は**書き込みより前**にあり、一致すれば `target_key` を見ない。逆にすると、同じ要求の再送
  （同じ `client_token`・同じ `target_key`）で**自分自身を `superseded` にして新しい行を作る**
  （行が増え、エージェントの手元の `request_id` が `superseded` になる）。
  - 対象を**先に**引くのは、再送の中身を「解決した対象の集合」で比べるため（ID 送り・パス送り・
    `group_id` 送りを同じ再送として扱える）と、**`decide` / `decline` の後の再送も 200** にするため
    （業務の検査を照合より前に置くと、応答が届かなかったエージェントの再送が 422 になる）。
  - **対象が消えている再送**（`group_id` が無い・パスが登録から外れた）は、照合の前に **404 / 422**
    になる（再送でも「いまの状態」が引けないため。監査で確認済み）。
  - `group_id` を指名したときの `policy` は**まとまりの設定が正**。**違う値を送ったら 422**
    （黙って捨てない。P6-1a の監査で確定）。

- `ask` / `conditions` / `origin` は**エージェントの自由文**。**画面にそのまま出す**（`esc()` する）。
- `ai_pick_asset_id` は**判断を書かない**（`design.md` §9.5）。`review_request` の列にだけ入る。
- **投げてすぐ返る**（判断を待たない）。応答は `state: "open"`。

### 3.3 `GET /api/review-requests`

```
GET /api/review-requests?state=open&limit=50&cursor=<不透明>
→ {"items": [ReviewRequest...], "next_cursor": "..." | null, "counts": {"open": 3}}
```

- `state` は `open` | `done` | `declined` | `superseded` | `all`（既定 `open`）。
- 並びは **`created_at DESC, id DESC`**（キーセット）。`cursor` は `created_at|id` を base64 した
  **不透明な文字列**（中身を仕様にしない）。`id` は ULID でミリ秒順なので、秒の `created_at` と同じ順に
  なる（点検 D6。`seq` の列は要らない）。
- **`target_key` で絞れる**（`&target_key=cut-20261011-031201`。点検 C1）。エージェントが
  `request_id` を控えていなくても自分の要求を引けるようにする。
- `counts.open` は**バーの件数**と**タブのタイトル**が使う（§5.4）。
  **一覧を返さず件数だけ**が要るときは `&count_only=1`（任意。1,000 件のときに毎回一覧を返さない。
  点検 D7）。
- **`requests[]` の形は契約と同じ**（`schemas/review-export.schema.json` の `ReviewRequest`）。
  API と契約で**別の形を作らない**（写し間違いの元）。

### 3.4 `GET /api/review-requests/{id}`

```jsonc
{
  "id": "...", "group_id": "...", "state": "done",
  "ask": "...", "conditions": [...], "origin": "...", "wants": [...],
  "ai": {"pick_asset_id": "...", "note": "..."},
  "created_at": "...", "closed_at": "...", "closed_by": "human",
  "decline_note": null, "superseded_by": null,
  "response": {
    "selected_asset_ids": ["..."],
    "reason_code_id": "rc.keep.favorite", "reason_label": "気に入った",
    "note": null,
    "annotations": ["01M4..."]
  }
}
```

- `state='open'` のとき `response` は **null**（契約の `ReviewRequestResponse` が `["object","null"]`）。
- `response` は**保存した写し**。`reason_label` も**閉じた時点のマスタ**（§0.2）。
  **ただし `annotations` だけは読むときに導出**する（判断の後に付いた印も入る。§0.2 / 点検 B3）。
- **`conditions` / `wants` は無ければ `[]`**（`null` にしない。点検 D1。契約が `type: array` で
  `null` を受けない）。
- エージェントはこれを**ポーリング**する（`state` が `open` でなくなるまで）。
  **`Retry-After` は付けない**（ローカルの道具なので作法を持ち込まない）。

### 3.5 `POST /api/review-requests/{id}/decline`

```jsonc
{"note": "この 8 枚はもう別のカットで使った"}
→ 200 {"id": "...", "state": "declined", "decline_note": "..."}
```

| 条件 | 応答 |
| --- | --- |
| `actor` が `human` 以外 | **403** `{"detail": "要求を断れるのは人だけです", "details": {"actor": "agent"}}` |
| `note` が空 / 2001 文字以上 | **422** `details: {"fields": {"note": "断る理由が要ります"}}` |
| `state` が `open` 以外（**違う `note`**） | **409** `code: "request_not_open"` `details: {"state": "done"}` |
| **既に `declined` で、同じ `note`** | **200**（**同じ結果を返す**。点検 B5: 状態機械が冪等性を与えるので `client_token` は要らない） |

- **`client_token` を取らない**（点検 B5）。理由は §0.9: `review_request.client_token` は**作成の鍵**で、
  1 行に 1 つしか入らない。断りは「同じ `note` なら 200／違うなら 409」で冪等にする。

### 3.6 注記の口

```
GET    /api/assets/{id}/annotations
       → {"items": [Annotation...]}                     # 古い順（created_at, id）
POST   /api/assets/{id}/annotations
       {shape?:'rect'|'ellipse', x?,y?,w?,h?, body?, group_id?, client_token?}
       → 201 {"annotation": {...}}
       # 座標が**無ければ「画像 1 枚へのメモ」**として受ける（422 にしない。点検 A1）
PATCH  /api/annotations/{id}   {body}                   → 200 {"annotation": {...}}
DELETE /api/annotations/{id}                            → 200 {"deleted": "<id>"}
GET    /api/assets/{id}/annotations/export?format=json  → {"asset_id":..., "image":{"width":W,"height":H},
                                                            "annotations":[Annotation...]}   # 書かない
POST   /api/assets/{id}/annotations/export
       {format:'crops', annotation_ids?: [...]}
       → 200 契約（`schemas/annotation-export.schema.json`）の文書そのもの。
         `crops` は `[{"annotation_id":..., "path":"annotations/<id>/<id>__<aid>.png",
                       "left":L, "top":T, "width":W_c, "height":H_c, "bytes":N}]`
         （**P6-2 の監査 E-1**: 前の版は `{"files": [...]}` という別の形を書いていたが、
           実装は契約の文書をそのまま返す。1 つの形で済むのでこれを正とする）
       # `client_token` は取らない（同じ名前に上書きするので元々冪等。点検 B5）
GET    /api/annotations/{id}/crop                       → image/png（その場で作る。書かない）
```

| 条件 | 応答 |
| --- | --- |
| `shape` が語彙の外 | **422** `details: {"shape": "rect か ellipse"}` |
| **座標が一部だけある**（`x` はあるが `w` が無い等） | **422** `details: {"fields": {...}}`（§2.1 の `CHECK` と同じ規則。点検 A1） |
| `x`/`y`/`w`/`h` が非数・範囲外（§0.7） | **422** `details: {"fields": {"x": "0〜1 の実数です", ...}}` |
| **座標も `body` も無い**（何も書いていない） | **422** `details: {"fields": {"body": "メモか印のどちらかが要ります"}}` |
| **切り出しで領域なしの注記**（P6-2 の監査 上位 2 で**決定を変更**） | `annotation_ids` を**指定しない**（画像全体の書き出し）: メモは**黙って飛ばして**残りを書く（**422 にしない**。`crops` は書けた分だけ。飛ばしたことは件数で分かる）。`annotation_ids` で**名指し**した: **422** `details: {"annotation_id": "<その注記の id>"}`（名指しは「これを切って」の要求なので黙って飛ばさない）。**以前は 1 件でも混ざると全体 422** で、画面の「切り出しを書き出す」がメモ 1 件で止まっていた |
| `GET /api/annotations/{id}/crop` が領域なしの注記 | **422** `details: {"annotation_id": "<その注記の id>"}`（点検 A1。**監査 287 行**: 以前は id ではなく文言が入っていた） |
| `asset_id` が無い | **404** `details: {"asset_id": "..."}` |
| `group_id` が無い / その画像が属さない | **422** `details: {"group_id": "この画像のまとまりではありません"}` |
| `body` が 2001 文字以上 | **422** `details: {"fields": {"body": "..."}}` |
| `PATCH` に `body` 以外の欄 | **422** `details: {"unknown": ["shape"]}` |
| `PATCH` / `DELETE` で**自分の `actor` でない注記** | **403** `{"detail": "他の人が付けた印は変えられません", "details": {"actor": "agent", "annotation_actor": "human"}}`（点検 C7） |
| `DELETE` の 2 回目（既に消えている） | **404** `details: {"annotation_id": "..."}`（点検 D5） |
| 実体が無い（切り出し・crop） | **409** `code: "asset_file_missing"` `details: {"asset_id": "..."}` |
| `annotation_ids` に他の画像の注記 | **422** `details: {"extra": ["01M4..."]}` |
| 同じ `client_token` の再送（`POST` のみ） | **200**（既存を返す） |

- `POST .../export` は**書く**（§0.6）。`GET .../export?format=json` は**書かない**。
- **`format=crops` を `GET` で受けても書かない**（`422` で `POST` を案内する:
  `details: {"format": "切り出しの書き出しは POST を使ってください"}`）。P5 の「GET が書く」を
  仕様として持ち込まないため、**あえて 422 にする**。

### 3.7 判断の口（既存。P6 で足すのは「要求を閉じる」だけ）

```
POST /api/groups/{id}/decide   # 既存（p5-design.md §3.2）
```

- 同じ取引で **open な要求を `done`** にする（§0.4）。応答に **`closed_request_ids`** を足す
  （既存の `reopened_group_ids` と同じ並び）。
- `actor` が `human` 以外は**今までどおり 403**（文言は既存のまま:
  `{"detail": "判断は人が付けます", "details": {"actor": "agent"}}`）。
- `GET /api/reviews`（台帳）と `review.json` の形は**変えない**（`closed_request_ids` は
  判断の応答だけに足す）。

---

## 4. 状態と遷移

### 4.1 `review_request.state`

| 現在 | 出来事 | 次 | 同じ取引で書くもの |
| --- | --- | --- | --- |
| （無し） | `POST /api/review-requests` | **open** | 要求 1 行＋まとまり 1 行（`kind='request'`, `source='request'`, `source_ref=<request_id>`） |
| **open** | 同じ `target_key` の新しい要求 | **superseded** | `superseded_by` = 新しい id（**先に UPDATE してから**新しい行を INSERT。§0.3）＋ **古いまとまりに判断が無ければ** `review_group.superseded_by` = 新しい要求の id（点検 A3 / G6） |
| **open** | まとまりを `decide` | **done** | `closed_at` / `closed_by` / **`response`**（§0.2） |
| **open** | `decline`（理由必須） | **declined** | `closed_at` / `closed_by` / `decline_note` |
| **open** | まとまりが `reopen` | open のまま | **何もしない**（§0.4） |
| done / declined / superseded | 何か | **変わらない** | 履歴。新しい要求は**新しい行** |

- **一度閉じたら開かない。** `reopen` はまとまりの状態を戻すだけで、要求には触らない。
- **`response` は上書きしない**（閉じた時に 1 度だけ書く）。ただし `annotations` は読むときに導出（§0.2）。
- `superseded` の要求に `closed_at` は入れない（閉じたのではなく**差し替わった**）。
  `superseded_by` だけを入れる。
- **まとまり側**: 差し替えで古いまとまりを閉じるのは、**判断（`decision`）が 1 つも無いときだけ**。
  判断があるときは残す（履歴。点検 A3）。閉じたまとまりは `GET /api/groups` の既定と
  `review.json` の `groups[]` の既定から外れる（`?include_superseded=1` で出る）。

### 4.2 `annotation`

| 現在 | 出来事 | 次 |
| --- | --- | --- |
| （無し） | `POST /api/assets/{id}/annotations`（**座標あり**） | 行が増える（矩形・楕円） |
| （無し） | `POST /api/assets/{id}/annotations`（**座標なし・`body` あり**） | 行が増える（**画像 1 枚へのメモ**。点検 A1） |
| ある | `PATCH {body}` | `body` が変わる（他は変わらない） |
| ある | `DELETE` | 行が消える＋**切り出しの PNG も消す**（点検 G3） |
| ある | 画像が消えた（`asset` の削除） | `ON DELETE CASCADE` で消える（切り出しは残る。手で消す） |

- 注記に**状態は無い**（下書きと確定の区別をしない）。判断の理由の代わりではない（`design.md` §9.7）。
- **領域なしの注記**（`shape` / `x` / `y` / `w` / `h` が全部 NULL）は**画像 1 枚へのメモ**。
  **その 1 枚の切り出し**（`GET /api/annotations/{id}/crop`）はできない（422）。
  **画像全体の書き出しでは黙って飛ばす**（P6-2 の監査 上位 2。§3.6 の表を見る）。
  **まとまり全体へのメモは作らない**（§1.3）。
- `PATCH` / `DELETE` は**自分の `actor` の注記だけ**（点検 C7）。

---

## 5. 画面（詳細は [`frontend-design.md`](frontend-design.md)。ここは挙動だけ）

### 5.1 要求の一覧（`#/requests`。**画面一覧の 5 番。新しい画面を作らない**）

- 既定は **`open` だけ**、**新しい順**。`state` は URL に持つ（`#/requests?state=all`）。
- 1 件は**カード**（`frontend-design.md` §4.4 の形）。出すもの:
  `ask`（見出し）／`conditions`（「見てほしいこと」）／`origin`（小さく）／
  **AI の推しと理由**（`ai.pick_asset_id` のサムネと `ai_note`）／依頼からの経過（`3 分前`）／
  枚数／ボタン **「開いて決める」「あとで」「断る」**。
- **「開いて決める」** → `#/group/<group_id>`。**この画面は P5 には無い**（`apps/gui/index.html:13`。
  P5 が作ったのは一覧・拡大・比較だけ）。**P6-1b で最小形を作る**（点検 A2 / G5。次節）。
- **「あとで」** → 何も書かない（画面の並びを変えない。既読の概念を作らない。§1.3 / 点検 C6）。
- **「断る」** → その場で理由の入力を出す。空なら送れない。送ると `state='declined'` になり、
  カードは一覧から消える（`state=all` では出る）。
- **AI の推しは自動でキープにしない。** 人が決めるまで `reviewed` にならない（§9.5）。
- 空のとき: 「エージェントからの要求はありません。要求が来るとここに出ます。」（`--accent` を付けない）。
- **画面を奪わない。** 要求が来ても画面を切り替えない（件数とタブのタイトルだけ）。

### 5.1b まとまりレビュー（`#/group/<id>`。**P6-1b で作る**）

**P5 では作っていない画面**（`apps/gui/index.html:13` に「キープ / ボツ…はまだ入っていません」とある）。
しかし合格の線 2「要求の一覧から**開いて判断し**、判断で閉じる」は、これが無いと
**API を `curl` で叩くしかない**（点検 A2 / G5）。そこで **P6-1b で最小形**を作る。

- 形は [`frontend-design.md`](frontend-design.md) §4.1 の図に合わせる（新しい設計を発明しない）。
- 出すもの: **フィルムストリップ（全枚。枚数の上限なし）**／**選択中の 1 枚を大きく**／
  **理由の選択（2 つに分ける。下記）**／**「この 1 枚に決める」**（`policy='pick_one'` のとき）／
  **「全部ボツ」**（理由必須）／**「選んだ 1 枚を拡大で開く」**。
- **理由は 2 つ**（P6-1b の監査 B1。**キープの理由が要求の答えになる**）:
  **「ボツの理由」**（`applies_to=reject`。ボツにする枚に**必須**）と
  **「キープの理由（任意）」**（`applies_to=keep`）。`decide` は「1 枚に決めたときは**その枚の
  キープ理由**をまとまりの理由として写す」ので、**これを入れないと要求の
  `response.reason_code_id` / `reason_label` が常に `null`** になり、エージェントが
  `wants: ["reason"]` で求めても答えられない。選ばなくても決められる（任意）。
- 選択中の 1 枚の下に**来歴の 1 行**（`モデル · seed · steps · cfg`。監査 C3。`GET /api/assets/{id}` を
  **選択が変わったときだけ 1 枚ぶん**引く）。
- **`policy='all_reject_only'` では「この 1 枚に決める」を無効**（監査 C6。押すと API が 422 を返す）。
  **判断の語は日本語**（`決定済み（1 枚に決めた）` / `決定済み（全部ボツ）`。監査 C5）。
- **注記の入口をここに置く**（点検 C5。前回の点検 C13 の未解決点）: 「選んだ 1 枚を拡大で開く」で
  `#/asset/<id>` へ移り、そこで印を付ける。**「印を付けてから決める」**を動線として書く
  （判断の後に付けた印は `response.annotations` に反映される〔§0.2〕が、**先に付ける方が意図が伝わる**）。
- 押すと `POST /api/groups/{id}/decide`（**既存。P5 で実装済み**）。応答の `closed_request_ids` を見て
  「要求を閉じました」を出す。**マウスだけで完結**（キーは補助）。
- 要求から来ていないまとまり（`kind='manual'`）でも同じ画面を使う（要求専用にしない。§1.1）。
- **大きく作らない**: 比較（`#/compare`）・絞り込み・タグは P6 では足さない（必要になった段で）。

### 5.2 要求の詳細（一覧の中で開く）

- カードを押すと**その場で開く**（`#/requests?open=<request_id>`。別画面を作らない）。
- 出すもの: `ask` / `conditions` / `origin` / `wants` / `ai` / `group_id`（まとまりへのリンク）/
  閉じた後は `response`（選ばれた枚・理由・注記）と `closed_at` / `closed_by`。
- `declined` は `decline_note` を出す（誰が何と言ったか）。
- `superseded` は `superseded_by` の要求へリンクする（`state=all` のときだけ出る）。

### 5.3 注記（拡大 `#/asset/<id>`）

- 既存の設計（`frontend-design.md` §4.3）のとおり:
  `注記` を押すと描ける。ドラッグで矩形、`Shift` + ドラッグで楕円。
  描いた直後にメモの入力を出す。右の列に一覧、押すとその領域へ寄る。消せる。
- **キー**: `n` で注記の切替（`frontend-design.md` §6 の予約語と衝突しないことを実装前に確かめる）、
  `Esc` で描くのをやめる、`Delete` で選択中の注記を消す。**マウスだけで完結する**（キーは補助）。
- 書き出しの入口を 2 つ置く: **「座標をコピー」**（JSON をクリップボードへ）と
  **「切り出しを書き出す」**（`POST .../export {format:'crops'}`）。
- 空のとき: 「まだ印はありません。ドラッグで囲むと印を付けられます。」
- **絵を隠さない**: `--accent` の細い実線。半透明の塗りは使わない（§4.3）。

### 5.4 件数と知らせ方

- 上部バーに `要求 3`（`--accent`。0 なら出さない）。押すと `#/requests`。
- **タブのタイトル**を `(3) image-reviewer` にする（画面を開いている間、5 秒ごとの取得で更新）。
- **音は使わない**（`design.md` §16.1）。トレイのアイコンは P0 の実装のまま（P6 では触らない）。
- 手で確かめる手順（合格の線には数えない）: 要求を投げた状態で画面を開き、
  バーの件数とタブのタイトルを目で見る。要求を断ると 1 つ減る。

### 5.5 `frontend-design.md` に足すべき箇所（**実装の前に足す**）

| 箇所 | 足すもの |
| --- | --- |
| §3 画面の一覧 | **3 番（まとまりレビュー `#/group/<id>`）を P6-1b で実体化する**（設計には既にあるが、画面が無い。点検 A2）。5 番の `#/requests` はそのまま使う。注記は 2 番の拡大の中 |
| §4.1 まとまりレビュー | **注記の入口**（「選んだ 1 枚を拡大で開く」）と「印を付けてから決める」の 1 行（点検 C5。前回の点検 C13 の未解決点） |
| §6 文言（語の統一） | **「あとで」に統一**（まとまりレビューの「保留」は使わない）。判断の取り消しは**「判断を消す」**、削除の取り消しだけ**「取り消す」**（点検 C6） |
| §4.4 要求のカード | 「あとで」「断る（理由必須）」の状態、`declined` / `superseded` の見え方、詳細を開いた形 |
| §4.3 注記 | 「座標をコピー」「切り出しを書き出す」の 2 つのボタンと、切り出しの結果の出し方 |
| §6 文言 | §6.1 の文言を追加（下の表） |
| §7 状態 | 要求一覧の読込・空・失敗、注記の「実体が無い（409）」の見せ方 |
| §11 画面ごとの細部 | 下の「実装者が迷う点」を先に決めておく |

**足す文言（§6 にそのまま入れる）**

| 場所 | 文 |
| --- | --- |
| 要求の一覧の空 | 「エージェントからの要求はありません。要求が来るとここに出ます。」 |
| 要求のカード（AI の推し） | 「AI の推し: 3 番」「これは下書きです。決めるのは人です。」 |
| 要求の断り | 「断る理由を書いてください。エージェントはこれを読んで次の手を決めます。」（既存 §6 と同じ文） |
| 要求が差し替わった | 「同じ対象の新しい要求で差し替わりました。前の要求はここに残っています。」 |
| 要求が閉じた後 | 「この要求は閉じました（3 番に決めました）。エージェントがここを読みます。」 |
| 注記の空 | 「まだ印はありません。ドラッグで囲むと印を付けられます。」 |
| 切り出しを書き出した後 | 「切り出しを 2 枚書き出しました（`annotations/01M4.../`）。」 |
| 実体が無い | 「実体が見つからないので切り出せません。場所を指定してつなぎ直せます。」 |
| まとまりレビュー（判断を消す） | 「**判断を消す**」（`clear`。§11。**「取り消す」は使わない**。点検 C6） |
| まとまりレビュー（何も決めずに戻る） | 「**あとで**」（まとまりレビューでも同じ語。**「保留」は使わない**。点検 C6） |
| 注記（領域なし） | 「印を付けずにメモだけ残せます」（§0.7。点検 A1） |

**§11 に足す決定（実装者が迷う点）**

| 論点 | 決め |
| --- | --- |
| 要求の一覧の既定 | `open` だけ、新しい順。`state=all` で履歴も出る |
| 「あとで」の意味 | 何も書かない（既読を作らない）。カードは開いたまま。**まとまりレビューでも同じ語を使う**（「保留」は使わない。点検 C6） |
| 判断の取り消しの語 | **「判断を消す」**。**「取り消す」は削除の取り消しにだけ**使う（点検 C6） |
| まとまりレビューの画面 | P6-1b で作る（フィルムストリップ＋理由＋「この 1 枚に決める」「全部ボツ」＋「選んだ 1 枚を拡大で開く」。§5.1b） |
| 領域なしの注記 | 座標を省いて `body` だけ送る。画面では「メモだけ残す」で入る（§0.7 / 点検 A1） |
| 断るの入力 | カードの中で 1 行の入力と「断る」。空なら押せない |
| AI の推しの印 | タイルの左上に `AI` の小さな印。**色は `--accent` の文字だけ**（塗らない） |
| 注記の描き始め | 画像の上でドラッグ。`Shift` を押しながらで楕円。`Esc` でやめる |
| 注記の最小の大きさ | 4 px 未満のドラッグは**捨てる**（誤クリックで 1 画素の印を作らない） |
| 切り出しの保存先 | `<data>/annotations/<asset_id>/`。パスは応答で**相対**で返す（絶対パスを出さない） |
| 座標のコピー | その画像の注記を全部含む JSON（`annotation-export.schema.json` の形） |

---

## 6. 契約

### 6.1 `review.json` に足すもの

- `requests[]` は**既存の契約に既にある**（`schemas/review-export.schema.json:64`）。P6 では
  **実際に埋める**。`build()` が `scope` に応じて入れる:
  - `scope=all`: **全部**の要求（`superseded` も含む。履歴を消さない）。
  - `scope=group:<id>`: そのまとまりの要求だけ。
  - `scope=asset:<id>`: その画像を含むまとまりの要求だけ。
  - **`requests` は `required` に入れない**（決定だけの書き出しも同じ契約で通る。既存の判断のまま）。
- **`abi` は上げない**（§0.5）。上げるのは「既存の必須や型が変わったとき」だけ。
- **`response.annotations` は保存値ではなく、書き出しの時点で導出**する（§0.2 / 点検 B3）。
  契約の `ReviewRequestResponse.annotations` に「**後から増えることがある**」と 1 行書く
  （判断の後に付けた印も入る。読む側が「答えは不変」と決め打ちしないように）。
- **`groups[]` は `superseded_by` が入ったまとまりを既定で出さない**（点検 A3 / G6）。
  出すのは `include_superseded: true` のときだけ（`GET /api/groups` の `?include_superseded=1` と揃える）。
- 契約の `ReviewRequest` に **`target_key` / `actor`**、`Group` に **`superseded_by`** を足す（§0.5 / 点検 C1・A3）。
- 決定性: `generated_at` を除いて 2 回出して同一（`requests` の並びは `created_at DESC, id DESC` に固定）。

### 6.2 `schemas/annotation-export.schema.json`（新規）

```jsonc
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "urn:image-reviewer:schema:annotation-export",
  "type": "object",
  "required": ["schema", "asset_id", "image", "annotations"],
  "properties": {
    "schema": {"const": "urn:image-reviewer:schema:annotation-export"},
    "abi": {"type": "string", "pattern": "^[0-9]+\\.[0-9]+$"},
    "generated_at": {"$ref": "#/$defs/Timestamp"},
    "asset_id": {"type": "string"},
    "image": {"type": "object", "required": ["width", "height"],
              "properties": {"width": {"type": "integer"}, "height": {"type": "integer"}}},
    "annotations": {"type": "array", "items": {"$ref": "#/$defs/Annotation"}},
    "crops": {"type": ["array", "null"], "items": {"$ref": "#/$defs/Crop"}}
  },
  "$defs": {
    "Timestamp": {"type": "string", "pattern": "^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(\\.[0-9]+)?Z$"},
    "Annotation": { /* review-export.schema.json の Annotation と同じ形（id / shape / x / y / w / h / body / actor / created_at / group_id） */ },
    "Crop": {"type": "object", "required": ["annotation_id", "path", "width", "height", "bytes"],
             "properties": {"annotation_id": {"type": "string"},
                            "path": {"type": "string", "description": "データ置き場からの相対パス。絶対パスは出さない。"},
                            "left": {"type": "integer"}, "top": {"type": "integer"},
                            "width": {"type": "integer"}, "height": {"type": "integer"},
                            "bytes": {"type": "integer"}}}
  }
}
```

- **`Annotation` の定義は既存契約と同じ形**にする（2 か所で別々に育てない。P5-2 の教訓:
  「同じ語を 2 つの表に書かない」）。実装では既存の `$defs` を**参照**できないので、
  **同じ形を写し、テストで両方を突き合わせる**（`test_annotation_export_contract`）。
- **絶対パスを出さない**（`include_paths` と同じ方針。`review.json` が既定で `path_map: null` なのと揃える）。
- `crops` は座標 JSON の書き出し（`GET`）では `null`、切り出しの書き出し（`POST`）の応答では配列。

### 6.3 ファイルの置き場と命名

```
<data>/annotations/<asset_id>/<asset_id>__<annotation_id>.png
```

- **1 図形 1 ファイル**。同じ図形を書き直すと**同じ名前**（増えない）。
- **図形を消したら、その切り出しも消す**（点検 G3）。`<data>/annotations/` は**キャッシュ**であって
  記録ではない（§0.8）。残すと、フォルダを読むエージェントが**存在しない注記の切り出し**を拾い、
  座標 JSON と食い違う。消せなかったときは `log.warning` を出して続ける（消えなくても害は小さい）。
- `*.tmp` が残っていたら**起動時に掃除**する（`ExportService.clean_stale_tmp()` と同じ形。
  P5 の監査 C1 の教訓）。

---

## 7. 性能と規模（この段で守る数値）

| 何 | 目標 | 根拠・測り方 |
| --- | --- | --- |
| `POST /api/review-requests`（8 枚） | **p95 150 ms 以内**（30 回） | 判断を待たない。書くのは要求 1 行＋まとまり 1 行＋枚の行。P5 の実測で `POST /api/reviews` は**中央値 3.0 ms**（`p5-audit-redo.md`）なので、余裕を見て 150 ms を線にする。**P6-1 で実測して記録する** |
| `GET /api/review-requests?state=open`（1,000 件） | **20 ms 以内** | `ix_request_state` で引く。**未計測**（P6-1 で 1,000 件を作って測る） |
| `POST .../annotations/export {format:'crops'}` | **切り出しの画素数に比例**: **100 万画素あたり約 70 ms**（`compress_level=1` のとき約 25 ms）＋ 復号 1 回 | **実測**（点検 B2 / G7。実データ・PIL・読み取り専用）: 1024² の復号 **8.7 ms**、保存は 256² **3.1 ms** / 512² **15.3 ms** / **1024²（全面）66.0 ms**。2048² の復号 **36.5 ms**、切り出し 1024² **65 ms** / **2048²（全面）320 ms**。**`compress_level=1` なら 1024² 全面 21 ms / 2048² 全面 93 ms**（無劣化のまま。ファイルは約 1.5 倍）。**図形が大きいと符号化が支配**（前の版の「復号が支配」は小さな囲みの話）。**P6-2 で測り直して記録する** |
| `GET /api/annotations/{id}/crop`（1 枚） | 上と同じ（保存しないので少し速い見込み。**未計測**） | 同じ復号＋符号化。**P6-2 で実測** |
| 注記の数 | 1 枚に **100 個**まで実用 | 一覧は `ix_annotation_asset`。100 個で 1 画面に収まらないときは**折り返してスクロール**（仮想化はしない） |
| 要求の数 | 1,000 件で一覧が実用 | 既定は `open` だけなので、実際に出るのは数十件の見込み |

- **未計測の目標は「未計測」と書く。** 実測したらこの表を書き換える（P9 で全部を裏づける。
  `design.md` §14 P9）。

**P6-1a の実測（2026-10-16。`tools/probe_p6_1a.py`。**測り方を併記する**）**

| 何 | keep-alive | 毎回つなぎ直す（`--fresh`） |
| --- | --- | --- |
| `POST /api/review-requests`（8 枚・30 回） | **p95 1.5 ms**（実装者の計測）／**16.2 ms**（監査の測り直し。1,000 まとまりの書き出しと重なった状態） | — |
| `GET /api/review-requests?state=open`（1,000〜1,040 件） | **p95 2.8 ms**（実装者）／**8.5 ms**（監査） | **p95 28.5 ms**（線 20 を超える） |
| `GET .../count_only=1` | p95 7.0 ms | p95 27.1 ms |
| `GET .../limit=200` | p95 10.7 ms | p95 33.4 ms |

- **線（p95 150 ms / 20 ms）は keep-alive の値で判定する。** 毎回つなぎ直す測り方では
  **接続の設立（Windows の 127.0.0.1 でも 20 ms 前後）**が乗るので、`--fresh` では線を外す
  （`tools/probe_p6_1a.py` がそのように作ってある）。**測り方を書かずに数値だけ残さない**
  （P5 の「実測の出所」の教訓）。

---

## 8. テスト方針（**何を壊すと落ちるか**）

P5 の監査で「**何も守っていないテスト**」が見つかった（`p5-audit-redo.md` F1、`p5-2-audit-redo.md` F1、
`p5-fix-audit-report.md` F2）。**この段では、テストを書いた時点で「何を壊すと落ちるか」を言える形にする。**

### 8.1 pytest（`tests/test_requests.py` / `tests/test_annotations.py` / `tests/test_db.py` に足す）

| # | 壊すと落ちるもの | 何を確かめるか | なぜ要るか |
| --- | --- | --- | --- |
| 1 | `ux_request_target_open` を外す / 上書きの条件を `state` で絞らない | 同じ `target_key` で 2 回投げると、**古い方が `superseded`**、新しい方が `open`、`superseded_by` が新しい id | `design.md` §9.6 の核 |
| 2 | 上書きの条件から `state='open'` を外す | `done` / `declined` の要求は**触られない**（履歴が残る） | §0.3 |
| 3 | **上書きの判定と更新を別の取引に分ける**（`BEGIN IMMEDIATE` をやめるのでは**落ちない**。同一プロセスの `Store._lock` で直列化されるため。点検 C9 / F1） | **8 本同時**に同じ `target_key` で投げて、`open` が**1 つだけ**・他は `superseded`（判定と更新が同じ取引なら、同一プロセスでもこの形で落ちる） | 「同時に 2 本来たとき」を**実行**で確かめる（P5 の `client_token` の 8 本同時と同じ手口。点検は**別接続 × 8** で `open` 1 行・`superseded` 7 行・`superseded_by` が 1 本に繋がることを実測済み） |
| 4 | 応答を保存せず毎回導出するように変える（**`annotations` を除いて**比較） | `decide` → `GET` の `response` を取り、`reopen` → もう一度 `GET` して**バイト一致**（`annotations` は判断の後に増えるので除く。点検 B3 / F2） | §0.2（P5 の「当時の値」の教訓） |
| 5 | 判断で閉じる処理を消す | `decide` の後に要求が `done` になり、`response.selected_asset_ids` が選んだ枚と一致。応答に `closed_request_ids` が入る | 合格の線 2 |
| 6 | `reopen` で要求を開き直すように変える | `reopen` の後も `state='done'` のまま | §0.4 |
| 7 | 断りの理由の検査を外す | 空の `note` で **422**、理由つきで `declined` になり `decline_note` が残る | `design.md` §9.6 |
| 8 | `human` の検査を外す | `POST /api/review-requests` は `agent` で **201**（通る）、`decline` は `agent` で **403**、`decide` は `agent` で **403** | 「判断は人だけ」を**口ごとに**確かめる |
| 9 | パスの解決を外す | 登録済みのパスで要求を作れる（ID と同じまとまりになる）。未登録のパスは **422 `details.unknown_paths`** | §0.10 |
| 10 | `wants` の未知語で 422 を返すように変える | 未知の語を入れても **201**（無視される） | §0.10（エージェントの拡張を弾かない） |
| 11 | 座標の検証を外す | `x=1.0`（境界）は通り、`x+w=1.0000001` は **422**、`w=0` は **422** | §0.7 |
| 12 | 座標を丸めるように変える | `0.123456789` を保存 → `GET` で**同じ値**（`REAL` の往復） | 合格の線 3 |
| 13 | 切り出しの式を変える（`floor` を `round` にする、**`round(…, 6)` を外す**等） | 1024² の `{x:0.25,y:0.5,w:0.25,h:0.25}` で **256 × 256 画素**、2048×1536 で **512 × 384 画素**、**1360² の `{x:0, w:0.275}` で 374 画素**（丸めを外すと 375 になる。点検 B1 / F3。1024 / 2048 / 1536 では**見つからない**幅） | 合格の線 3・点検 B1。**幅が 2 の冪でも 1000 の約数でもない**絵を 1 つ入れる |
| 14 | クランプを外す | `{x:0.999,y:0.999,w:0.001,h:0.001}`（1024² で 1.024 画素）が**1 画素以上**の PNG になる | §0.7 |
| 15 | PNG ではなく JPEG で書くように変える | 出力が PNG（`PIL.Image.format` が `PNG`） | §0.7（無劣化） |
| 16 | `os.replace` の失敗で一時ファイルを消す処理を外す | `os.replace` を `PermissionError` にして書き出し → `*.tmp` が **0 個**、座標 JSON は無事 | P5 の C1（`p5-fix-audit-report.md`） |
| 17 | `GET .../export?format=json` がファイルを書くように変える | ディレクトリの `mtime` と中身が変わらない | §0.6（P5 の C8/G2） |
| 18 | `GET .../export` で `format=crops` を許すように変える | **422** で `POST` を案内する | §0.6 |
| 19 | 実体が無いときの 409 を 500 に変える | 実体を消した画像で `POST .../export` → **409 `asset_file_missing`** | 切り出しの失敗の型 |
| 20 | 契約から `response` を外す / 形を変える | 本物の `jsonschema`（`uv run --no-project --with jsonschema`）で `requests[]` と `annotation-export` を検証 | P5 の F7 の教訓（テストが無かった） |
| 21 | `requests` の並びを不定にする | `scope=all` を 2 回出して `generated_at` を除いて**完全一致**（要求を 3 件作った状態） | 決定性（`design.md` §3.4） |
| 22 | 索引を外す | `EXPLAIN QUERY PLAN` に `ix_request_state` が出る | P5 の D1 の教訓（部分索引を実際に使う） |
| 23 | 移行の手当てを壊す | **v1 の DDL から 1 回で v4** に上がる（`PRAGMA user_version` が 4、列が揃う）。**3 回呼んでも同じ**（`DDL` → `user_version = 1` から始める。P5-3 の C6 の fixture を繰り返さない。点検 F12） | P5-3 の C6 |
| 24 | 新しい口を `include_router` から外す／別の `app` に載せる | `POST /api/review-requests` / `.../decline` / `.../annotations` / `.../export` に **`Host: evil`** と **`Content-Type: text/plain`** で **403**（点検 C8 / F8。P5 の `test_new_post_endpoints_are_guarded` と同じ形） | 守りは middleware 任せなので、載せ忘れを検出できない |
| 25 | `client_token` の照合を `target_key` の後ろに回す | **同じ `client_token`・同じ `target_key` で 2 回投げる → 行は 1 つ・`superseded` は 0**（点検 B4 / F5。順序を逆にすると自分自身を差し替える） | §3.2 の「検査の順序」 |
| 26 | `group_id` の `decided` 検査を外す | `decided` なまとまりへの要求が **422**（点検 C2 / F6） | 受けると**永久に `open`** の要求ができる |
| 27 | 古いまとまりを閉じる処理を外す | 差し替えで、**判断が無い古いまとまりに `superseded_by` が入り**、`GET /api/groups` の既定と `review.json` の `groups[]` から**消える**。**判断があるまとまりは残る**（点検 A3 / F7） | §0.3（古いまとまりが増え続ける） |
| 28 | `PATCH` / `DELETE` の `actor` 検査を外す | `agent` が `human` の注記を消せない（**403**）。自分の注記は消せる（点検 C7 / F9） | 人の印をエージェントが消せてしまう |
| 29 | 領域なしの受付を外す／`CHECK` を外す | 座標なし・`body` ありで **201**（領域なしの注記）。**片方だけ NULL** の行は作れない（`CHECK`）。切り出しは **422**（点検 A1 / F10） | `design.md` §9.7 の決定 |
| 30 | 切り出しの後始末を外す | 注記を消すと**その切り出しの PNG も消える**（点検 G3） | キャッシュに消えた図形の絵を残さない |
| 31 | `response` の JSON をそのまま（文字列で）書き出す | `requests[].response` が**オブジェクト**として出る（`json.loads` してから埋め直す。**キーの順を固定**。点検 F11） | 決定性（`generated_at` を除いて同一） |

- **実データ依存のテストを書かない。** 実データに無い経路を「実データで」と名付けたテストが
  P5-2 で見つかった（`:561`）。**作り物で試し、名前も作り物に合わせる。**

### 8.2 `tools/gui_smoke.mjs`（軽い DOM。CSS を持たない）

| # | 壊すと落ちるもの | 何を確かめるか |
| --- | --- | --- |
| 1 | バーの件数を出す条件 | 要求 3 件で `要求 3` が出る／0 件で出ない（`--accent` の文字） |
| 2 | タブのタイトルの組み立て | `(3) image-reviewer` になる／0 件で `image-reviewer` |
| 3 | カードの描画 | `ask` / `conditions` / `AI の推し: 3 番` / `ai_note` が出る。`esc()` が効く（`<script>` を入れて**生のまま出ない**） |
| 4 | 「断る」の入力の検査 | 空のまま押しても送らない（`fetch` が呼ばれない）／理由を入れると `POST .../decline` を 1 回だけ叩く |
| 5 | 空の状態の文言 | 「エージェントからの要求はありません。…」が出る |
| 6 | 注記の描き始め | 4 px 未満のドラッグで**注記を作らない**／それ以上で `POST /annotations` を 1 回叩く |

### 8.3 `tools/gui_layout.mjs`（本物の Chrome。3 窓 × 3 状態）

| # | 壊すと落ちるもの | 何を確かめるか |
| --- | --- | --- |
| 1 | 要求のカードの幅 | 3 窓（1400×900 / 1200×800 / 1920×1080）で**カードが横に溢れない**（`outside=0` 相当） |
| 2 | 注記の一覧 | 注記 20 個のとき、右の列が**舞台の外に出ない**。画像の枠が `object-fit: contain` のまま |
| 3 | 印の重なり | 注記を 5 個描いたとき、`--accent` の線が**画像の外に出ない**（座標 0〜1 の枠内） |

- **計測式を足す設計**（点検 F13）: いまの `MEASURE` は「外に出ない」「タイル幅＝枠」しか見ない
  （`p5-fix2-audit-report.md` C1）。要求のカードと注記の一覧を見るには、
  **カードの `right <= 舞台の right`** と**注記の一覧の `bottom`** を `MEASURE` に足す
  （`tools/gui_layout.mjs` を P6-1b / P6-2 で拡張する）。

- **`gui_smoke.mjs` は CSS を持たないので、見た目の崩れは見えない**（P5 の B1 がこれで漏れた）。
  見た目の崩れは `gui_layout.mjs` で見る。

---

## 9. 工程（小段と、Fable に監査させる単位）

| 段 | 作るもの | 合格の線 | 監査に渡すもの |
| --- | --- | --- | --- |
| **P6-0** | v4 の移行（2 つの表＋`review_group.superseded_by`）、`client_token` の重複検査、`GET` は書かない原則、契約 2 つ（`requests` を**空配列でも出す**＋`annotation-export`） | 既存の **176 件**が緑。新しいテスト（§8.1 の 20〜23）が緑。**`requests: []` が出て契約を通る**（要求を作る口は P6-1 なので、この段では空が正しい。点検 D8）。**索引が使われる**（`EXPLAIN QUERY PLAN`） | 指示書＋「実行したコマンドと結果」（`pytest`・`EXPLAIN`・`jsonschema`・v1→v4 の移行・`CHECK` の効き） |
| **P6-1a** | 要求の**受付・上書き・一覧・取得・閉じる（判断で自動）・断る**の API、件数（`counts`） | §1.2 の **1**（**p95 150 ms** を実測して記録）。**1,000 件 20 ms** も実測 | 同＋HTTP の計測（`fix_api.py` 相当） |
| **P6-1b** | **画面**: `#/requests`（カード・詳細・断る）、**`#/group/<id>` のまとまりレビュー最小形**（§5.1b）、バーの件数とタブのタイトル | §1.2 の **2**（**人が画面から決めて閉じる**） | 同＋ブラウザの計測（`page_requests.js` 相当）と画面写真 |
| **P6-2** | 注記（矩形・楕円・**領域なしのメモ**）、座標 JSON、切り出し（`compress_level=1`）、拡大画面の注記 | §1.2 の **3**。**§7 の画素数比例**を実測して記録（1024² 全面・2048² 全面・1360²・1 画素の境界） | 同＋切り出しの画素数の表（1024² / 2048×1536 / 1360² / 1 画素）と `annotation-export` の契約検証 |

- **各段で `docs/p6-audit-brief.md` を書き直してから渡す**（P5 と同じ形。実行してよいこと、
  確かめてほしいことを明記）。**監査は実行込みで**（`--allowedTools` に実行を入れる。
  `design.md` §19.5 の申し送り）。
- **段の順序**: P6-0 → P6-1a → P6-1b → P6-2。P6-0 を通さずに P6-1a を始めない（表と契約が土台）。
  **P6-1b は P6-1a の後**（API が無いと画面が作れない）。

---

## 10. 未確認とリスク（**推測で埋めない**）

| # | 未確認のこと | どうするか |
| --- | --- | --- |
| 1 | **UNC のパス**（`\\server\share\...`）を `normalize_path()`（`os.path.realpath`）がどう扱うか | 規則そのものは**既存の関数を使う**と決めた（§0.10 / 点検 C3。`store.py:39`。登録時と同じ鍵なので、ID で引いた場合と必ず一致する）。**残る未確認は UNC とネットワークドライブだけ**。P6-0 のテストで、実データのパス（`C:\work\illust-authoring\.store\...`）と**登録済みの別表記**（大小文字・`/`）で同じ `asset` に当たることを確かめる。**UNC は実データに無いので「未確認」のまま残す** |
| 2 | **`ux_request_target_open`（部分 UNIQUE 索引）が `open` の一意性を守るか** | P5 で `client_token` の部分索引は実測済み（`p5-design.md` §0.7 F1）だが、**`state` を条件にした部分索引は試していない**。P6-0 で 2 本同時に投げて確かめる |
| 3 | **切り出しの速度**（1024² 30 ms / 2048² 80 ms） | 復号の実測（12.0 / 39.7 ms）からの**見積り**。P6-2 で測る。**測るまで「達成」と書かない** |
| 4 | **`GET /api/review-requests` の 1,000 件** | 未計測。P6-1 で 1,000 件を作って測る |
| 5 | **タブのタイトルの更新**は画面を開いている間だけ | SSE を作らないため（§1.3）。**閉じている間に要求が来ても気づかない**（利用者の回答は「バーとタブ」なので、割り切りとして記録する） |
| 6 | **`design.md` §16.2-11（`Host` / `Origin` の許可リストをポート変更時にどう持つか）** | P6 では既存の middleware のままで、**ポートは変えない**。変える段（P9）で決める |
| 7 | **注記のメモの検索性** | P6 では検索しない（`body` は表示だけ）。全文検索は P9 以降 |
| 8 | **`review.json` に注記の実体を入れるか** | 入れない（§0.5。id だけ）。**入れたくなったら `abi` を上げる**判断が要る（1 万枚 × 数十図形で膨らむ） |
| 9 | **`request` を対象にした `scope=request:<id>`**（`design.md` §6.1 の一覧に語がある） | P6 では**作らない**（`scope=group:<id>` で足りる）。作るなら §6.1 の改訂とセット |
| 10 | **要求の枚数の上限** | `design.md` §9.3 が「上限は無い」と決めているので、P6 でも**上限を設けない**。ただし 1 要求 200 枚のような使い方をされたときの `POST` の時間は**未計測**（§1.2 の線は 8 枚で測る。200 枚は P6-1a で 1 回だけ測って記録する） |
| 11 | **古いまとまりが `review_group.superseded_by` で閉じた後、そのまとまりのファイル（`export/groups/<id>.json`）をどうするか**（点検 A3 の帰結） | P6-1a で「既定から外す」だけにする（**ファイルは消さない**。他ツールが読んでいるかもしれない）。消すなら別の段（P9 の掃除）で決める |
| 12 | **まとまりレビュー画面（P6-1b）の作り込みの程度** | 最小形（フィルムストリップ＋理由＋2 つの決定ボタン＋拡大への入口）に絞る。比較・絞り込み・タグは足さない（必要になった段で）。**画面の実装が大きくなりすぎないよう、P6-1b の着手時に `frontend-design.md` §4.1 の図と突き合わせる** |

---

## 11. 用語（この段で増えるもの）

| 語 | 意味 |
| --- | --- |
| **要求（review request）** | エージェントが「これを見て決めて」と出すもの。投げてすぐ返り、**判断で閉じる**。必ずまとまりを作る |
| **`target_key`** | エージェントが付ける任意の鍵（例 `cut-20261011-031201`）。**同じ鍵の `open` は差し替える** |
| **応答（response）** | 閉じた時点の答え（選ばれた枚・理由・メモ・注記の id）。**閉じた時に 1 度だけ書き、以後変えない** |
| **下書き（AI の推し）** | `ai_pick_asset_id` と `ai_note`。**判断ではない**。人が決めるまで未判断のまま |
| **断る（decline）** | 人が要求を閉じること。**理由が要る**（エージェントが次の手を決める） |
| **差し替え（superseded）** | 同じ `target_key` の新しい要求で古い `open` を閉じること。**履歴は消さない** |
| **注記（annotation）** | 画像の上の矩形・楕円とメモ。座標は **0〜1 の割合**。判断の理由の代わりではない |
| **切り出し（crop）** | 注記が囲んだ範囲**ちょうど**の PNG。拡大縮小も余白も付けない。**いつでも作り直せるキャッシュ** |
| **座標 JSON** | 注記の座標と文。契約は `schemas/annotation-export.schema.json` |
| **領域なしの注記** | 座標（`shape` / `x` / `y` / `w` / `h`）を持たない注記。**画像 1 枚へのメモ**（点検 A1 / G4）。切り出しはできない |
| **「あとで」** | 何も決めずに画面を離れること。**まとまりレビューでも同じ語**を使う（「保留」は使わない。点検 C6） |
| **「判断を消す」** | 付けた判断の取り消し（`clear`）。**「取り消す」は削除の取り消しにだけ**使う（点検 C6） |
| **差し替えで閉じたまとまり** | 同じ `target_key` の新しい要求で置き換わり、**判断が 1 つも無い**ため既定の一覧から外れたまとまり（`review_group.superseded_by`。点検 A3 / G6） |

---

## 12. 確かめてほしい点（レビュアー向け）

**1 回目の点検は終わった**（`docs/p6-review-report.md`。A1〜A3 / B1〜B5 / C1〜C9 / D1〜D8 / F1〜F13 と
G1〜G7。**すべて本設計に反映済み**で、反映した箇所には `（点検 …）` の印を付けてある）。
**利用者の確認待ちは §0.11 に集約**した（いまは推奨どおりで進める）。以下は**次の点検（P6-0 の監査）**で
見てほしい点として残す。

1. **§0 の差分が `design.md` と衝突していないか。** とくに 0.2（応答を保存する）、0.4（reopen で
   開き直さない）、0.6（`GET` で `format=crops` を **422** にする）。
2. **合格の線が「実行して確かめられる形」になっているか。** §1.2 の 3 つで足りるか、
   §7 の未計測の数値を「目標」として置いたままでよいか（P5 の P9 と同じ扱いにした）。
3. **§8 の「壊すと落ちるか」が本当に落ちるか。** 特に 4（応答が変わらない）・12（座標の往復）・
   13（切り出しの式）・17（`GET` が書かない）は、**実装を戻せば落ちる**形になっているか。
4. **「実装者が気づいていない前提」が残っていないか。** §10 に 10 件挙げたが、抜けは無いか。
   （P5 では「`export/groups` に `.tmp` が溜まる」「`tabular-nums` が効かない」「初回描画で
   8 枚が 3 行に溢れる」が**実装者の盲点**だった）
5. **`schemas/` を 2 つに分けた判断**（§0.5）が妥当か。`review.json` に注記の実体を入れないこと
   （§10-8）で、他ツールが困らないか。
6. **画面を増やしていないか。** `#/requests` と `#/asset/<id>` だけで足りるか
   （`frontend-design.md` §3 の一覧に無い画面を作っていないか）。
