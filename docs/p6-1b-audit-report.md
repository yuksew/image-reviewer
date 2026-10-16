# P6-1b（要求まわりの画面）の監査報告

- 監査した版: 2026-10-16 の作業ツリー（`apps/gui/requests.js` 05:07、`group.js` 05:10、`badge.js` / `index.html` / `styles.css` / `app.js`、`tools/gui_smoke.mjs` 05:01、`tools/gui_layout.mjs` 05:03、`docs/frontend-design.md`）。実装の記録は `p6-1b-implementation.md`（05:12）。**監査の途中（05:20 以降）に `src/image_reviewer/annotations.py` / `api/annotations.py` / `api/__init__.py` が増えた**（P6-2 の着手と見える）。P6-1b の対象ファイルはその後変わっていない。
- **実行できたかどうか: 全部実行できた**（コマンド約 12。ソースは編集せず、実データは `mode=ro`、一時物は `.tmp-audit-redo/p6/`。サーバは `data-p52` で 8791、Chrome headless は `.tmp-audit-redo/cdp.mjs` で駆動、1400×900）:
  - `uv run pytest -q` ×2 → **208 passed**、`tests/.tmp` 0 → 0 → 0。`node tools/gui_smoke.mjs` → **73 ok / 0 NG**。
  - `node tools/gui_layout.mjs --screen requests` → 3 窓とも **ok**（cards=4、overflow=0）。`--count 8` → ok（比較の回帰なし）。**`--screen group` は無い**（`--ids` を要求して終わる。`--help` も無い。指示書の記述と違う）。
  - **自前のブラウザ検査**（`page_req.js` / `page_group.js` / `page_poll.js`。`fetch` を差し替えて回数を数える）:
    - `#/requests`: カード 4 / API 4 / **入れ子 0**、`ask` / `conditions` / `origin` / 「AI の推し: 3 番」＋サムネ＋`ai_note`＋「これは下書きです」/ 経過「1 秒前」/ 「未対応」/ ボタン 3 つ。**`<script>` / `<img onerror>` / `"` / `&` / `<b>` を入れた要求**: `script` 要素 0、生のタグ無し、`window.__xss*` は**走らない**（画面写真 `shot-req.png` に文字として出ている）。カードを押すと詳細（5 行）。「あとで」→ `fetch` 0 回。「断る」→ フォームが出る → 空で送る → `POST` 0 回 → 理由を入れて送る → **`POST .../decline` 1 回**、カードが消え「3 件（未対応 3）」。「すべて」タブ → `?state=all`、31 枚、4 つの状態の語、断った理由。「開いて決める」→ `#/group/<id>`。
    - **合格の線 2**（`#/group/<id>`）: フィルムストリップ 4、見出し「4 枚 ・ 1 枚選ぶ ・ 未決定 ・ エージェントの要求 ・ AI の推し: 3 番」、3 番に `ai-pick`、選択中の 1 枚と「1 番 ・ 未判断」。3 番を押す → 「3 番 ・ 未判断」。理由なしで「この 1 枚に決める」→ 文言だけで **`POST` 0 回**。理由を選んで決める → **`POST /decide` 1 回**、「要求を閉じました（3 番に決めました）。エージェントがここを読みます。」、見出し「決定済み（selected）」、3 番が `kept`、ボタンが無効。**API: 要求は `done`、`response.selected_asset_ids` が 3 番の 1 枚と一致、`closed_by: human`。`reopen` → `state` は `done` のまま、`response` は `annotations` を除いて同一**。「選んだ 1 枚を拡大で開く」→ `#/asset/<id>` でライブラリの詳細（来歴つき）が開く。「あとで」→ `#/requests`、書き込み 0。
    - **件数とタブ**（ライブラリの画面で待つ）: 起動時 `(2) image-reviewer` / `要求 2`。11 秒で `count_only=1` が **2 回、間隔 4,999 ms**（`state=open&count_only=1` だけ）。`#/requests` に移っても続く（5.6 秒で 1 回）。open を全部断る → 次の周期で **`image-reviewer` / バー非表示**。`再読込` → 「エージェントからの要求はありません。要求が来るとここに出ます。」、カード 0、「0 件」。**Chrome を閉じた後 12 秒でサーバの `count_only` の件数は増えない**（9 → 9）。
  - `GET /api/export/review.json?scope=all` と `GET /api/review-requests` の後で `review.json` の mtime 不変。
- 総合判定: **条件つきで使える。** 合格の線 2 は**ブラウザで通る**。`esc()`、「あとで」「断る」の `fetch` の回数、ポーリングの周期と停止、タブのタイトルの戻り、拡大への入口、マウスだけの完結はすべて実行で確かめた。残るのは **(1) 「断る」の入力欄を押すとカードのクリックに伝わって再描画され、フォームが閉じる**（マウスだけでは理由を書けない）、**(2) 「この 1 枚に決める」で選んだ枚の理由を集めないので、`response.reason_code_id` が常に `null`**（`wants: ["reason"]` に答えられない）、**(3) 自分で見つけたバグ 3 件のうち、どれも「もう一度壊すと落ちる」検査が無い**、の 3 点。

---

## A. 直っていない（必ず直す）

| # | 場所 | 問題 | 実行したコマンド / 再現手順 | 提案 |
| --- | --- | --- | --- | --- |
| **A1** | `apps/gui/requests.js:188-191`（カード全体の `click` で `state.openId` を切り替えて `render()`）、`:159-168`（「断る」は `stopPropagation` する）、`:87-91`（`textarea.req-decline-note` には何も付いていない） | **「断る」の入力欄をマウスで押すと、カードのクリックに伝わって詳細の開閉 → `render()` → 全カードを作り直し → フォームは `hidden` に戻り、書きかけの理由も消える。** 「断る」ボタンだけが `stopPropagation` していて、`textarea` と「断る」（送信）以外の中身は伝わる。**マウスだけでは理由を書けない**（P5 の原則に反する）。`gui_smoke.mjs` は `note.value` を直接入れて `send.dispatch('click')` するので見えない | **再現した（Chrome）。** 「断る」→ `formShownAfterClick: true` → `textarea` を `click()` → **`formStillShownAfterTextareaClick: false`**。私の検査はそのあと `value` を直接入れて送ったので「1 回だけ叩く」は通ったが、人の操作では辿り着けない | `.req-decline-form` に `click` の `stopPropagation` を付ける（1 行）か、カードの開閉を見出し（`.req-head`）のクリックに限る。Chrome の検査に「`textarea` を押してもフォームが残る」を足す |

---

## B. 直っているが別の問題が残る（重大）

| # | 場所 | 問題 | 実行したコマンド / 再現手順 | 提案 |
| --- | --- | --- | --- | --- |
| **B1** | `apps/gui/group.js:16`（`REASONS = '/api/reason-codes?applies_to=reject'`）、`:187-192` `decideOnePayload`（選んだ枚は `verdict: keep` だけ。理由なし）、`:236-238`（`decide(..., null)`）、`src/image_reviewer/review.py` `_validate_group_reason`（`pick_one` の結論の理由は**キープした枚の理由**）、`p6-design.md` §5.1b「理由の選択（`reject` のとき必須）」 | **「この 1 枚に決める」でキープの理由を集めないので、要求の `response.reason_code_id` / `reason_label` が常に `null`。** エージェントが `wants: ["reason"]` と求めても答えが無い。設計 §5.1b が「`reject` のとき必須」としか書かなかったので画面はボツの理由だけを出し、P5 の `decide` は「1 枚に決めたときはその枚のキープ理由をまとまりの理由にする」ので、キープ理由が無い＝結論の理由が無い | **再現した（Chrome → API）。** 合格の線 2 の手順で決めた要求: `response: {selected_asset_ids: [3 番], reason_code_id: null, reason_label: null, note: null}`。`decide` の本文は `{items: [{keep}, {reject, rc.reject.people} ×3], group_reason_code_id: null}` | 理由の選択を 2 つに分ける: **「選んだ理由」**（`applies_to=keep`。任意）と**「ボツの理由」**（`applies_to=reject`。必須）。`decideOnePayload` の `keep` に `reason_code_id` を入れる。§5.1b に「キープの理由が要求の答えになる」と書く |
| **B2** | `p6-1b-implementation.md` §3（自分で見つけたバグ 3 件）、`tools/gui_smoke.mjs`、`tools/gui_layout.mjs:112-140`（`MEASURE_REQUESTS` は `cards` を数えるが**期待値と比べない**） | **3 件とも「もう一度壊すと落ちる」検査が無い。** (1) カードの入れ子: `gui_smoke` は `list.children.length === 2` を見るが、入れ子になっても `list.children` は 2 のまま（内側の `.req-card` は孫）。`gui_layout --screen requests` は `cards=N` を**印字するだけ**で、API の件数と比べないので 2 倍でも ok。(2) `decide` の名前隠し: `gui_smoke` は `decideOnePayload` / `allRejectPayload` の**関数だけ**を呼び、`wireGroup()` のボタンを押さない。Chrome の検査（`--screen group`）は**無い**。(3) `load()` の競合: どちらにも無い（世代番号を外しても落ちない） | 私の `page_req.js` は `cards.dom === api` と `nested === 0` を見て通った（**入れ子 0、4 = 4**）。`page_group.js` はボタンを押して `POST /decide` 1 回を見た。つまり**検査は書ける**が、`tools/` には無い | `gui_layout.mjs --screen requests` で **`cards === counts.open`（API を 1 回引く）と `.req-card .req-card` が 0** を合否に入れる。`--screen group --group <id>` を本当に作り、**決めるボタンを押して `POST /decide` が 1 回**飛ぶことを見る（`page_group.js` が雛形になる）。(3) は `showRequests` を 2 回連続で呼んでカードが 2 倍にならないことを `gui_smoke` に |

---

## C. 中程度

| # | 場所 | 問題 | 実行したコマンド / 再現手順 | 提案 |
| --- | --- | --- | --- | --- |
| **C1**（申し送り 1） | `apps/gui/requests.js:13, 198-210`（`MAX_INDEX_FETCH = 20`。カードごとに `GET /api/groups/{id}`） | **「AI の推し: N 番」のために一覧 1 回＋まとまり最大 20 回**。私の検査では一覧を 2 回開いて `GET /api/groups/{id}` が **30 回**。21 枚目からは番号が出ず**カードごとに見え方が違う**（上限の理由は利用者に見えない）。設計 §5.1 は番号を出せと言う | `page_req.js` の `calls.groupsFetches: 30` | **いま足す**: 契約の `ReviewRequest.ai` に **`pick_index`（整数・null 可）** を足し、サーバが一覧でも取得でも入れる（`group_item.position` を引くだけ。1 行の JOIN）。`additionalProperties: false` なので契約の変更になるが、P6-0 で `target_key` を足したのと同じ「足すだけ」。画面は `fillOrder` を消せる |
| **C2**（申し送り 3） | `apps/gui/group.js:17`（`?state=open&limit=200` を取って `group_id` で探す） | まとまりレビューを開くたびに **open 200 件を取る**（1,000 件のときは先頭 200 だけ。201 件目以降のまとまりは「エージェントの要求」の見出しが出ない）。`ix_request_group` は**既にある**（P6-0 で確認） | 読んだだけ（open が 200 を超える状態は作っていない） | **いま足す**: `GET /api/review-requests?group_id=<id>` の絞り込み（`list()` に `AND group_id = ?` の 2 行。索引あり）。画面は `?group_id=&state=open` の 1 本に |
| **C3**（申し送り 2） | `apps/gui/group.js:40-45`（「N 番 ・ 状態（理由）」）、`frontend-design.md` §2.4 の図（`seed / steps / cfg`） | 選択中の 1 枚の**来歴の 1 行**が無い。`GET /api/groups/{id}` に来歴は無いが、**`GET /api/assets/{id}` には `meta` がある**（P5 の口）。選択が変わるたびに 1 回引けば済む | 読んだだけ | **API は足さない。** 画面側で選択中の 1 枚だけ `GET /api/assets/{id}` を引き、`seed / steps / cfg / model` を 1 行出す（`compare.js` のキャプションと同じ作り） |
| **C4**（申し送り 4） | `counts` が `open` だけ | 「すべて」タブで総数が出ない | 読んだだけ | **足さない。** `next_cursor` の有無で「まだある」と出せば足りる。総数は `state=all` の `count(*)` で 1 行だが、画面が要るまで待つ |
| **C5** | `apps/gui/group.js:59`（`決定済み（${group.decision}）`） | 見出しに **`selected` / `all_rejected` の英語**がそのまま出る（画面は日本語。P5 の `stateLabel` のような写しが無い） | `page_group.js`: `brief: "4 枚 ・ 1 枚選ぶ ・ 決定済み（selected）"` | `{selected: '1 枚に決めた', all_rejected: '全部ボツ'}` |
| **C6** | `apps/gui/group.js:102-107`（`policy` を見ずに「この 1 枚に決める」を出す） | `policy` が `all_reject_only` のまとまりで「この 1 枚に決める」を押すと、API の 422（`all_reject_only ではキープできません`）がそのまま文言に出る。`pick_many` では 1 枚しか選べない（最小形として設計どおりだが、ボタンの文言は「1 枚」のまま） | 読んだだけ | `all_reject_only` では決めるボタンを無効に。`pick_many` は P6 では「1 枚」と明記（§5.1b） |

**確かめた結果、問題なし（実行）**:

- **`esc()`**（§2-2）: `ask` / `conditions` / `origin` / `ai_note` に `<script>` / `<img onerror>` / `"` / `&` を入れた要求で、`script` 要素 0、`innerHTML` に生のタグ無し、`window.__xss` は未定義。詳細の 5 行も同じ `esc()`（`requests.js:30-33, 105-110`）。
- **「あとで」「断る」**（§2-2）: `fetch` 0 回／空で 0 回・理由ありで 1 回（A1 の経路を除く）。
- **空の状態・0 件の戻り**（§2-2 / §2-3）: 文言どおり、`<title>` が `image-reviewer`、バー非表示。
- **ポーリング**（§2-3）: 5 秒周期、`count_only=1` だけ、Chrome を閉じると止まる（サーバの件数が増えない）。`wireBadge()` は `app.js:401` で起動時に 1 回だけ。**画面（経路）を移っても続く**のは設計どおり（§0.10「画面を開いている間」＝アプリを開いている間）。
- **まとまりレビュー**（§2-2）: フィルムストリップ・理由（`applies_to=reject` の 12 件＋空）・全部ボツ（理由が無いと文言だけで送らない。`group.js:243-249`）・「選んだ 1 枚を拡大で開く」→ `#/asset/<id>` → ライブラリの詳細（来歴つき）。**マウスだけで完結**（キーは無い）。
- **経路**（§2-4）: `#/requests` / `#/group/<id>` / `#/asset/<id>` / `#/compare` の 4 つ（`app.js:322-362`）。比較は `gui_layout --count 8` で ok、ライブラリの詳細は `#/asset/<id>` で開いた。
- **回帰**（§2-7）: 208 / 73 / `gui_layout` ok。`GET` は書かない（mtime 不変）。
- **実装者が決めた所**（§2-8）: 先頭 20 件だけ番号（C1 へ）／「N 番 ・ 状態」（C3 へ）／「あとで」は一覧へ戻る（**妥当**。書き込み 0 を確認）／判断後は 1 行で知らせて「← 要求」（**妥当**。線 2 の確認と一致）／タブ 2 つと `state` を URL に（**妥当**）／詳細はその場で開く（**妥当**）／`count_only=1` を 5 秒（**妥当**）／`<title>` を `image-reviewer` に（**妥当**）／バーの件数を `<a href="#/requests">`（**妥当**。`href` を確認）。

---

## D. 軽微

| # | 場所 | 問題 | 提案 |
| --- | --- | --- | --- |
| D1 | `tools/gui_layout.mjs` | `--help` が無い（`--ids（または --count）が要ります` で終わる）。指示書は「`--screen group --group <id>`（実装者が足した口。`--help` を見る）」と書くが、**その口は無い** | 作る（B2）か、指示書を直す |
| D2 | `apps/gui/requests.js:94-96` | 閉じた要求の文言「この要求は閉じました（N 枚に決めました）」は**枚数**で、`frontend-design.md` §6 の「（3 番に決めました）」（番号）と違う（カードには並びが無いので番号が出せない。C1 と同根） | C1 を直せば番号にできる |
| D3 | `apps/gui/group.js:170-174` | 判断後の「N 番に決めました」は `state.items` の並び（`position` 順）で数える。全部ボツのときは `at = 0` で「記録しました。」。設計の文言「要求を閉じました」は出る | — |
| D4 | `%TEMP%\gui-layout-*` | 6 個あった（P6-0 の監査では 0。私の 3 回分を含むかは未確認） | 再発なら `chrome.on('exit')` を待つ（前回 C2） |

---

## E. 設計とのずれ

| 項目 | 状態 |
| --- | --- |
| §5.1 カードの中身・ボタン・空の文言・画面を奪わない | **一致** |
| §5.1b フィルムストリップ・理由（reject 必須）・全部ボツ・拡大の入口・マウスだけ | **一致**。ただし**キープの理由**が設計にも画面にも無い（B1）。設計の穴 |
| §5.1b「AI の推しに印」「見出しに AI の推し: 3 番」 | **一致**（`ai-pick` の枠と見出し） |
| §5.2 詳細（`?open=`、`wants`、まとまりへのリンク、閉じた時刻） | **一致** |
| §5.4 件数・タイトル・5 秒・音なし | **一致** |
| §5.5 `frontend-design.md` への追記（§3 / §4.4 / §2.4 / §6 / §7 / §11） | **入っている**（「あとで」で統一、「保留」を使わない。点検 C6） |
| §8.2 の 1〜5 | **入っている**（smoke 22 件）。6（注記）は P6-2 |
| §8.3-1 カードが横に溢れない | **入っている**（`--screen requests`）。**件数の整合は見ない**（B2） |
| 申し送り 4 件 | C1〜C4 の判定（1・3 はいま足す、2・4 は足さない） |

---

## F. テストが守っていないもの

| # | 検査 | 何を主張しているか | 実際に守っているか | 直し方 |
| --- | --- | --- | --- | --- |
| **F1** | `gui_smoke.mjs`「カードを 2 枚描く」 | 入れ子にならない（バグ 1） | **守らない。** 入れ子でも `list.children` は 2 | `list.querySelectorAll('.req-card').length === 2` に（孫まで数える） |
| **F2** | `gui_layout.mjs --screen requests` | 溢れない | **溢れだけ。** `cards` を API と比べない（バグ 1 を通す） | B2 |
| **F3** | （無い） | `decide` ボタンが関数を呼ぶ（バグ 2） | **無い。** `gui_smoke` は payload の関数だけ | Chrome で決めるボタンを押す検査（`page_group.js` 相当） |
| **F4** | （無い） | `load()` の競合（バグ 3） | **無い** | `showRequests` を 2 回連続 → カードが 2 倍にならない |
| **F5** | `gui_smoke.mjs`「空のままでは断りを送らない」「1 回だけ叩く」 | 断りの `fetch` | **守っている**（`note.value` を直接入れる）。ただし **A1（`textarea` を押すとフォームが消える）は見えない** | Chrome で `textarea.click()` → フォームが残る |
| **F6** | `gui_smoke.mjs` の `esc` | 生の `<script>` が出ない | **守っている**（`&lt;script&gt;`）。実物でも確認 | — |
| **F7** | （無い） | ポーリングが 5 秒・`count_only` だけ・閉じると止まる | **無い**（`wireBadge({pollMs})` の口はある） | `pollMs: 10` で `fetch` の回数を数える 1 件 |

---

## G. 依頼者への質問（推奨つき。朝に読む）

| # | 論点 | 選択肢 | 推奨 |
| --- | --- | --- | --- |
| **G1**（B1） | キープの理由を画面で集めるか | (i) 「選んだ理由」（任意）と「ボツの理由」（必須）の 2 つ ／ (ii) 集めない（`response.reason` は常に null） | **(i)**。要求の `wants: ["reason"]` が意味を持たない (ii) は `design.md` §9.6 の「結果が入っている」に反する |
| **G2**（C1 / C2） | API に `ai.pick_index` と `?group_id=` を足すか（P6-2 の前） | (i) いま ／ (ii) P6-2 の後 | **(i)**。どちらも数行で索引もある。画面の回避（最大 20 回の追加取得、200 件の一覧取得）は上限の外で見え方が変わる |
| **G3**（B2） | バグ 3 件の守りをどこに置くか | (i) `gui_layout.mjs --screen requests/group` に件数と決めるボタン ／ (ii) `gui_smoke` だけ | **(i)**。1 と 2 は軽い DOM で見えないと実装者自身が書いている |
| **G4**（C6） | `pick_many` / `all_reject_only` のまとまりでの画面 | (i) P6 は `pick_one` だけ（文言で明記） ／ (ii) `pick_many` の複数選択を足す | **(i)**。最小形の範囲。`all_reject_only` ではボタンを無効に |

---

## H. 確かめられなかったこと

| 項目 | 状態 | 理由 |
| --- | --- | --- |
| open が 200 件を超えるときのまとまりレビューの見出し（C2） | **読んだだけ** | 200 件超の状態を作らなかった |
| `load()` の競合（バグ 3）の再現 | **未再現** | `route()` と `再読込` を同時に起こす手順を作らなかった。世代番号のコードは読んだ |
| 1200×800 / 1920×1080 でのまとまりレビューの見た目 | **未確認**（`--screen group` が無く、私の検査は 1400×900 だけ） | — |

---

## 最も重大な 3 件

### 1. 「断る」の入力欄を押すとフォームが消える（A1。**実行して分かった**）

カード全体のクリックで詳細を開閉して全カードを作り直す作りなので、`textarea` を押した瞬間にフォームが `hidden` に戻り、書きかけも消える。「断る」ボタンだけが伝播を止めていて、入力欄は止めていない。マウスだけでは理由を書けず、P5 からの原則に反する。`gui_smoke` は `value` を直接入れるので見えない。`stopPropagation` の 1 行で直る。

### 2. キープの理由を集めないので、要求の答えの理由が常に null（B1。**実行して分かった**）

合格の線 2 は通るが、閉じた要求の `response` は `reason_code_id: null / reason_label: null`。画面がボツの理由しか出さず、P5 の `decide` は「1 枚に決めたときはその枚のキープ理由がまとまりの理由」なので、理由が無いまま閉じる。設計 §5.1b の「`reject` のとき必須」が穴。「選んだ理由」の選択を足す。

### 3. 自分で見つけたバグ 3 件に、もう一度壊すと落ちる検査が無い（B2）

入れ子は `list.children` では見えず `gui_layout` は件数を比べない。`decide` の名前隠しは `gui_smoke` がボタンを押さないので見えず、Chrome の検査は無い。競合は誰も見ない。私の `page_req.js` / `page_group.js` は同じことを本物の Chrome で確かめたので、`tools/gui_layout.mjs` に件数の整合と「決めるボタンを押す」を入れれば守れる。
