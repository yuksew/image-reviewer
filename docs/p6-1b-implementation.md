# P6-1b 実装報告（要求まわりの画面）

対象: `docs/p6-design.md` §5.1（要求の一覧）・§5.1b（まとまりレビューの最小形）・§5.2（詳細）・
§5.4（件数と知らせ方）・§5.5（`frontend-design.md` に足すもの）・§8.2 / §8.3（テスト）・§1.2 の合格の線 2
点検: `docs/p6-review-report.md`（A2 / A3 / C5 / C6 / C8 / C9）・`docs/p6-review-triage.md`（推奨どおりで確定）
前段: `docs/p6-1a-implementation.md`（要求の API。画面はここから）

---

## 1. 作ったもの

| ファイル | 行 | 何 |
| --- | --- | --- |
| `apps/gui/requests.js` | 271 | **新規**。`#/requests`（カード・詳細・断る・タブ・空の状態・AI の推しの番号） |
| `apps/gui/group.js` | 244 | **新規**。`#/group/<id>`（フィルムストリップ・選択中の 1 枚・理由・決める／全部ボツ／あとで／拡大で開く） |
| `apps/gui/badge.js` | 63 | **新規**。上部バーの `要求 N` とタブのタイトル `(N) image-reviewer`（開いている間だけ 5 秒ごと） |
| `apps/gui/index.html` | +58 | `#requests` / `#group` の器、`#stat-requests`（バーの件数）、`<title>`、プロトタイプの但し書きを更新 |
| `apps/gui/styles.css` | +86 | 2 画面の見た目（面は `--surface` / `--seam`、影・角丸なし。§2.5） |
| `apps/gui/app.js` | +42 | 経路 `#/requests` / `#/group/<id>` / `#/asset/<id>`（拡大）と配線 |
| `docs/frontend-design.md` | +52 | §5.5 の指示どおり**実装の前に**足した（§3 画面一覧・§4.4 カード・§2.4 まとまりレビュー・§6 文言・§7 状態・§11 決定） |
| `tools/gui_smoke.mjs` | +96 | §8.2 の 1〜5 と、まとまりレビューの payload の検査（**19 件追加**） |
| `tools/gui_layout.mjs` | +48 | `--screen requests`（3 窓でカードが横に溢れない。§8.3-1） |

**`src/` と `schemas/` は 1 バイトも触っていません**（P6-1a を Fable が監査中なので、API に足りない物は §4 に書く）。
P6-1a の監査は `docs/p6-1a-audit-report.md` / `docs/p6-1a-audit-triage.md` に出ています（§4 の指摘と重なる点は、
そちらの判断を優先してください）。

---

## 2. 実行したコマンドと結果

```
$env:UV_CACHE_DIR = "C:\work\image-reviwer\.uv-cache"
uv run pytest -q                                        -> 208 passed（画面は pytest の対象外。既存は緑のまま）
node tools/gui_smoke.mjs                                -> 73 ok / 0 NG（既存 51 ＋ P6-1b 22）
node tools/gui_layout.mjs --base http://127.0.0.1:8791 --count 8
                                                        -> すべて ok（比較。回帰なし）
node tools/gui_layout.mjs --base http://127.0.0.1:8791 --screen requests
                                                        -> すべて ok（1400x900 / 1200x800 / 1920x1080 で
                                                           cards=12 overflow=0 maxRight<=list.right）
```

**実機（データのコピー `data-p52`、ポート 8791）で通した「合格の線 2」**（設計 §1.2 の 2）:

1. `POST /api/review-requests` で 4 枚の要求を作る（`ai_pick_asset_id` は 3 番目）
2. ブラウザで `#/requests` を開く → カードに `ask` / `conditions` / `origin` /
   **「AI の推し: 3 番」**（サムネつき）/ `ai_note` / 「未対応」が出る（画面写真 `shot-p6-1b-requests.png`）
3. 「開いて決める」→ `#/group/<id>`（画面写真 `shot-p6-1b-group.png`。見出しに「エージェントの要求 ・
   AI の推し: 3 番」、フィルムストリップ 4 枚、AI の推しに `--warn` の印）
4. 3 番を選ぶ → 理由を選ぶ（`rc.reject.people`）→ **「この 1 枚に決める」**
5. 結果（ブラウザから観測）:
   - 画面: 「**要求を閉じました（3 番に決めました）。エージェントがここを読みます。**」
   - API: そのまとまりの `open` は **0 件**、要求の `state` は **`done`**、
     `response.selected_asset_ids` は**選んだ 3 番の 1 枚**
6. 「選んだ 1 枚を拡大で開く」→ `#/asset/<id>` に移り、ライブラリの詳細（来歴つき）が開く
   （**注記の入口**。点検 C5。注記そのものは P6-2）

画面写真: `.tmp-audit-redo/shot-p6-1b-requests.png` / `shot-p6-1b-group.png`

---

## 3. 途中で見つけて直した自分の間違い（実機で踏んだ）

| # | 何 | どう直した |
| --- | --- | --- |
| 1 | `cardHtml()` が `.req-card` の**入れ物ごと**返していたので、`render()` の入れ物と入れ子になり、`querySelectorAll('.req-card')` が **2 倍（24 枚）**返り、CSS も二重に当たっていた | `cardHtml()` は**中身だけ**返し、入れ物は `render()` が作る（`gui_layout.mjs` の計測が 24 を報告して気づいた） |
| 2 | `wireGroup()` で `const decide = $('group-decide')` が**関数 `decide` を隠し**、押すと `decide is not a function` | ボタン側を `decideBtn` に改名（コメントに理由を書いた） |
| 3 | `load()` が重なると、古い方の `finally` が後から描いて**カードが二重**になりうる | **世代番号**を入れて、古い load の描画を捨てる |

> 1 と 2 は `gui_smoke.mjs` では見つからず、**本物のブラウザ**（`gui_layout.mjs` と CDP の計測）で出ました。
> 「軽い DOM の身代わりでは見えない」という P5 の教訓どおりです。

---

## 4. API に足りないと思ったもの（**直していません**。監査の判断を仰ぎます）

1. **一覧 API が対象の並びを返さない** → カードの「AI の推し: N 番」を出すために、
   画面が `GET /api/groups/{id}` を**カードごとに**引いています（`MAX_INDEX_FETCH = 20` 件まで）。
   50 件の一覧では 20 回の追加取得になります。`ReviewRequest.ai.pick_index` か、
   一覧の応答に対象の `asset_ids` を足せば 1 回で済みます（**設計 §5.1 は番号を出せと言っている**）。
2. **`GET /api/groups/{id}` が来歴を返さない** → まとまりレビューの 1 行（図では `seed / steps / cfg`）が
   出せず、**「4 番 ・ キープ」**（番号・状態・理由）までにしています。
3. **`GET /api/review-requests` にまとまりの絞り込みが無い** → まとまりレビューが
   「開いている要求を 200 件取って `group_id` で突き合わせる」形になっています（`?group_id=` が欲しい）。
4. `counts` が `open` だけなので、`state=all` のときの**総数**が画面に出せません（§5.2 の詳細で使う想定）。

---

## 5. 設計からずれた所／自分で決めた所

| 論点 | 決め | 理由 |
| --- | --- | --- |
| 「AI の推し: N 番」の出し方 | 先頭 20 件だけ `GET /api/groups/{id}` を引いて番号を出す（それ以降はサムネだけ） | §4-1。一覧の応答だけでは番号が分からない。既定 50 件を全部引くと重い |
| まとまりレビューの 1 行 | 「N 番 ・ 状態（理由）」 | §4-2。来歴が API に無い |
| 「あとで」（まとまりレビュー） | `#/requests` へ戻る（**何も書かない**） | §5.1 の「あとで」は「画面の並びを変えない」。まとまりレビューからは一覧へ戻すのが自然（点検 C6 の語の統一は守っている） |
| 判断後の導線 | 自動で画面を移さず、**1 行で知らせて**「← 要求」で戻れるようにした | 設計の穴 (2)（P6-1a が挙げた）。利用者が結果を読めるように |
| 一覧のタブ | 「未対応」「すべて」の 2 つを出し、`state` を URL に持つ | §5.1 の `#/requests?state=all` |
| 詳細の開き方 | カードを押すと**その場で開く**（`?open=<id>`） | §5.2 |
| 件数のポーリング | `count_only=1` を 5 秒ごと（`wireBadge()`。**画面を開いている間だけ**） | §5.4 / §0.10。テストがタイマーを残さないよう、`wireBadge()` を呼んだときだけ始まる形にした |
| タブのタイトル | `<title>` を `image-reviewer` に変更（`(N) ` を前置） | §5.4。以前は「（プロトタイプ）」付きだった |
| 上部バーの件数 | `<a href="#/requests">` にした（押すと一覧へ） | §5.4「押すと `#/requests`」 |

---

## 6. 未実装のまま残した所

- **注記そのもの**（矩形・楕円・領域なしのメモ、座標 JSON、切り出し）→ P6-2。入口（`#/asset/<id>`）だけ置いた
- §8.2 の 6（注記の描き始め）と §8.3 の 2・3（注記の一覧・印の重なり）→ P6-2
- まとまりレビューの比較（`#/compare` への導線）・絞り込み・タグ → 設計どおり**この段では作らない**
- `README.md` のテスト数（208）と機能一覧 → 親が最後にまとめて直す
