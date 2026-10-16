# P6 設計の点検の仕分け（Fable の点検 → どう直したか）

- 点検報告: [`p6-review-report.md`](p6-review-report.md)（総合判定 **直してから実装**。A 3 / B 5 / C 9 / D 8 / F 13）
- この仕分けの立場: **推奨はすべて採用**した（P5 の 2 回目の点検と同じ扱い。
  [`review-triage-fable.md`](review-triage-fable.md) は「すべて推奨どおりで確定」だった）。
  ただし **利用者の判断が要る 3 件（A1・A2・A3）と G1〜G7 は「推奨どおりで進める（朝に覆せる）」**として
  [`p6-morning-report.md`](p6-morning-report.md) に集めてある。
- 反映先: すべて [`p6-design.md`](p6-design.md)。**`design.md` 側の直し**（§5.6 の DDL・§6.1 の `format=crops`・
  §9.6 の「置き換わる」の意味）は、P6 の実装が落ち着いてから 1 回で直す（点検 E の指示）。

## A. 必ず直す

| # | 指摘（要約） | どうするか |
| --- | --- | --- |
| **A1** | 「領域なしの注記（まとまり全体へのメモ）」が DDL の `NOT NULL` と検証で入れられない（`design.md` §9.7 の覆せない決定に反する。契約は null 可） | **採用（G4-(i)）**。`shape` / `x` / `y` / `w` / `h` を **NULL 可**にし、「全部 NULL（画像 1 枚へのメモ）」と「全部あり」の 2 形だけを `CHECK` で許す。`asset_id` は `NOT NULL` のまま。**「まとまり全体へのメモ」は P6 では作らない**と §1.3 に明記（その用途は `review_group.note` が既にある）。切り出しは領域なしなら **422**。**`design.md` §5.6 と §9.7 の食い違いも §0 に記録**し、`design.md` は後で直す |
| **A2** | 「開いて決める」の先の「既存のまとまりレビュー `#/group/<id>`」が **P5 の実装に無い**（`index.html:13`）。合格の線 2 が画面から満たせない | **採用（G5-(i)）**。`#/group/<id>` の**最小形**を P6 に入れ、**P6-1a（API）/ P6-1b（画面）** に割る。画面はフィルムストリップ＋理由＋「この 1 枚に決める」「全部ボツ」＋**選択中の 1 枚を拡大で開く**（C5 の注記の入口）。§5.1 の「既存の」を削除 |
| **A3** | `target_key` で差し替えたとき、**古い要求が作った `open` なまとまりが残り続ける**（誰も閉じられない。`design.md` §19.2-6 に未回答） | **採用（G6-(i)）**。`review_group` に **`superseded_by TEXT`** を足し（v4）、差し替え時に**古いまとまりに判断が 1 つも無ければ**印を付けて、**一覧と `review.json` の既定から外す**（`?include_superseded=1` で出せる）。判断があるときは消さない（履歴）。契約の `Group` に `superseded_by` を足す（§0.5 の「足すだけ」方針） |

## B. 重大

| # | 指摘（要約） | どうするか |
| --- | --- | --- |
| **B1** | `ceil((x + w) * W)` が浮動小数で **1 画素はみ出す**（幅 1360 で 0.001 刻み 3,170 組。1024 / 2048 は 0 組なのでテスト 13 では見えない） | **採用**。`floor(round(x*W, 6))` / `ceil(round((x+w)*W, 6))` に直す。**1360² の例**（`x=0, w=0.275` → 374 画素）を §8.1-13 に足す。`x + w <= 1` の検証は `<= 1 + 1e-9` |
| **B2** | PNG の符号化が**囲みの画素数に比例**し、1024² 全面 66 ms・2048² 全面 320 ms（目標 30 / 80 の 2〜4 倍） | **採用（G7-(ii)）**。`compress_level=1`（無劣化のまま。1024² 全面 21 ms / 2048² 全面 93 ms）。§7 の目標を**画素数比例**（100 万画素あたり約 70 ms）に書き直し、実測表を載せる |
| **B3** | `response.annotations` を判断時の写しにすると、**判断後に付けた印が永久に入らない**（エージェントは `open` でなくなるとポーリングをやめる） | **採用（G2 の混合）**。`response` は保存するが、**`annotations` だけ読むときに導出**（`annotation.group_id = request.group_id` を `created_at` 順）。契約に「増えることがある」を 1 行。§8.1-4 のバイト一致テストは **`annotations` を除いて比較** |
| **B4** | **`client_token` と `target_key` の検査順が未定**。`target_key` を先に見ると、同じ要求の再送が**自分を `superseded` にして行を増やす** | **採用**。§3.2 に「**`client_token` の照合を最初に行い、一致すれば `target_key` を見ない**」。§8.1 に「同じ `client_token` と同じ `target_key` で 2 回 → 行は 1 つ・`superseded` は 0」 |
| **B5** | **`decline` と `export` の `client_token` の置き場が無い**（`review_request.client_token` は作成用の列。`export` は行が無い） | **採用**。両方から `client_token` を**外す**。`decline` は状態機械で冪等（同じ `note` で既に `declined` なら 200、違う `note` なら 409 `request_not_open`）。`export` は同名に上書きするので元々冪等 |

## C. 中程度（すべて採用）

| # | どうするか |
| --- | --- |
| **C1** | 契約の `ReviewRequest` に **`target_key`（null 可）と `actor`** を足す（§0.5 の「足すだけ・`abi` は上げない」方針に沿う）。`GET /api/review-requests?target_key=` の絞り込みを足す |
| **C2** | `group_id` が **`decided` のまとまり**への要求は **422**（「`reopen` してから」）。§3.2 の表と §8.1 に |
| **C3** | パスの解決は **`store.normalize_path()`**（`os.path.normcase(os.path.realpath(...))`）を使う。**設計が発明した規則を捨てる**。§10-1 の未確認は「UNC の `realpath`」だけ残す |
| **C4** | §0.3 に「古い `open` を `superseded` に**更新してから**新しい行を挿入する（逆だと部分 UNIQUE 索引で落ちる）」を 1 行（実行で確認済み） |
| **C5** | §5.1（まとまりレビュー）に**注記の入口**を入れる（選択中の 1 枚を拡大で開く）。前回の点検 C13 を解いたと書く |
| **C6** | 語を 1 つにする: **「あとで」＝判断を書かない**（まとまりレビューの「保留」は使わない）。判断の取り消しは**「判断を消す」**、削除の取り消しだけ「取り消す」。§5.5 と §11 に |
| **C7** | `PATCH` / `DELETE /api/annotations/{id}` は**自分の `actor` の注記だけ**（`agent` は `agent` の注記のみ。違えば 403） |
| **C8** | §8.1 に「新しい `POST`（`review-requests` / `decline` / `annotations` / `export`）で `Host: evil` と `Content-Type: text/plain` が 403」 |
| **C9** | §8.1-3 の「壊すと落ちる」を「**上書きの判定と更新を別の取引に分ける**」に直す（同一プロセスでも落ちる形に） |

## D. 軽微（すべて採用）

`conditions` は無ければ `[]`（D1）／`annotation-export` の `abi` は**文字列**（D2）／**楕円は外接矩形で切る**（D3）／
`target_key` / `origin` は 200 文字（D4）／`DELETE` の 2 回目は **404**（D5）／`cursor` の理由を 1 行（D6。
`created_at DESC, id DESC` と「新しい順」が一致するのは `id` が ULID でミリ秒順だから）／`?count_only=1` は任意で言及（D7）／
P6-0 の線は「**`requests: []` が出て契約を通る**」に（D8）

## F. テストで守れないもの（すべて反映）

- **F1**（3 の壊し方）→ C9 と同じ。**F2** → `annotations` を除いた比較。**F3** → 1360² を追加。
- **F5〜F10（無いテスト）** → 足す: `client_token`＋`target_key` の再送／`decided` なまとまり／古いまとまりの扱い／
  新しい口の 403／`PATCH`・`DELETE` の `actor`／領域なしの注記（受付・一覧・`export`・切り出しの 422）。
- **F11** → `response` の JSON は `json.loads` して埋め直す（キーの順を固定）。
- **F13** → `gui_layout.mjs` の計測式に「カードの `right <= 舞台の right`」「注記の一覧の `bottom`」を足す設計を §8.3 に。

## E. `design.md` 側の直し（P6 の実装後に 1 回で）

| 直す所 | 内容 |
| --- | --- |
| `design.md` §5.6（`annotation` の DDL） | `shape` / `x` / `y` / `w` / `h` を NULL 可に（§9.7 の「領域なし」と揃える。本文の中で食い違っている） |
| `design.md` §6.1 | `GET .../annotations/export?format=json\|crops` → **`format=crops` は `POST`** に直す |
| `design.md` §9.6 | 「同じ `target_key` で投げ直せば**画像の一覧も置き換わる**」→ **新しいまとまりを作り、古いまとまりは印を付けて既定から外す**（A3） |
| `design.md` §16.2 | 決定の追記（3 つの選択の結果、`compress_level=1`、`superseded_by` など） |

## 利用者（人間）の確認待ち

**A1・A2・A3 と G1〜G7 は、推奨どおりで設計に入れた。** 朝に覆す場合は
[`p6-morning-report.md`](p6-morning-report.md) の表を見て指示してほしい（設計と実装を直す）。
