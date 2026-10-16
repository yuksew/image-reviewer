# P4-3（タグの画面）監査報告 — 実行込み

- 日付: 2026-10-16（11:35〜12:10）。監査者: Fable（Claude Code）
- 指示書: `docs/p4-audit-brief-p4-3.md`（11:15）。実装の記録: `docs/p4-3-implementation.md`（11:30）
- 対象: `apps/gui/tags.js`（11:16）/ `taglist.js`（11:29）/ `jobs.js`（11:17）/ `badge.js`（11:19）/ `app.js`（11:19）/ `index.html`（11:18）/ `styles.css`（11:20）、`tools/gui_smoke.mjs`（11:24）/ `gui_layout.mjs`（11:26）/ `gui_shot.mjs`（11:28）、`docs/frontend-design.md` §4.13（11:21）。設計: `docs/p4-design.md` §5.1〜§5.5 / §8.2 / §8.3
- 環境: 利用者のサーバ（8790）が `.venv` を握っているので **`uv run --no-sync` と `.venv\Scripts\python.exe`**。実データ `.data/` は `mode=ro` と **`backup()`** だけ（mtime は 10-15 のまま）。複製 `.tmp-audit-redo/p43/srv`（起動で v5。IllustTagger で 3 枚にタグ付け → 画像 A に `rem_(re:zero)` を手で付け、画像 B に CSV の一般語 236 語を `wd14` で入れ、1 語に `<script>` の語釈、実体の無い asset を 1 つ）をポート 8791 で。画面は **Chrome headless（CDP、1400×900）**で、`fetch` を差し替えて回数・本文・ヘッダを数えた（`.tmp-audit-redo/p43/cdp.mjs`、`page_view.js` / `page_asset.js` / `page_all.js` / `page_tags.js` / `page_jobs.js` / `page_badge.js` と各 `.out.json`、画面写真 6 枚）。ComfyUI には**タグ付けと訳だけ**投げた。ソースと既存の文書は編集していない。監査のサーバは停止済み。

---

## 判定: **直してから P4 を閉じる。**

**線 3 は私の手で通った**（2 行 1 組・語釈の行に括弧なし・`rem_(re:zero)` はそのまま）。出所の印・スコア 3 桁・見出し・`語彙外`・「外す」は `手` だけ・「語を足す」・「訳す」の往復・`esc`・2 秒ポーリングの停止・バーの知らせ・回帰（pytest 282 / gui_smoke 122 / gui_layout）はすべて実行で裏が取れた。
しかし**実装者が「実物で未確認」と申告した 4 点のうち 2 点が Chrome で壊れていた**。どちらも設計が名指す機能なので A。

**最も重大な 3 件**
1. **`#/jobs` は失敗した項目と「もう一度」を永遠に出せない**（§A-1）。画面は `GET /api/jobs?limit=50` だけを読むが、一覧の口は P4-1 で **`failed_limit=0`**（`items_failed` が常に `[]`）。実体の無い 1 枚のジョブは「失敗」「1 枚も処理できませんでした」とだけ出て、失敗の理由も「もう一度」の押し場も無い（単体の `GET /api/jobs/{id}` と `/items?state=failed` には入っている）。
2. **`#/tags` の右の詳細の「訳す」は必ず 422**（§A-2）。`taglist.js:118` が `translateNames([item.name])` と**名前**を渡し、`Number("black_hair")` が `NaN` で落ちて **`{"tag_ids": []}`** を送る（Chrome で捕捉。`server.log` に 422）。`item.tag_id` の 1 語の直し。
3. **完了したジョブの「1 枚 X 秒」が時間とともに増え続ける**（§B-1）。`pace()` が状態を問わず `now - started_at` を `done` で割る。1.3 秒で終わった 3 枚のジョブが「1 枚 1 分 20 秒」→ 4 秒後「1 分 22 秒」。

---

## A. 直っていない／設計の約束が成り立たない（必ず直す）

### A-1. `#/jobs` に失敗した項目と「もう一度」が出ない（`apps/gui/jobs.js:85-94` / `:56-63`、`src/image_reviewer/jobs.py` `list()` の `failed_limit=0`）
- 再現（`page_jobs.out.json` §failed）: 実体の無い asset だけのジョブ → `POST 202` → 行は **`失敗 / 1 / 1 / 1 枚も処理できませんでした`**。`.jb-failed` 無し・`.jb-fail` 0 件・**`.jb-again` 無し**（`html` を報告に保存）。`counts` の行（付いた・飛ばした・失敗）も **`tagged || skipped` が偽なので出ない**。
- API の突き合わせ: `GET /api/jobs?limit=50` の同じ job は `items_failed: []`・`counts.failed: 1`。`GET /api/jobs/{id}` は `items_failed: [{ref: 01AUDITNOFILE…, error: FileNotFoundError …}]`、`GET /api/jobs/{id}/items?state=failed` も 1 件。**画面が読む口だけが空**。
- 直し方（どちらか）: (a) `JobService.list()` を `failed_limit=20` にする（設計 §3.3「`items_failed` は先頭 20 件」は一覧にも当てはめる）。(b) 画面が `counts.failed > 0` の行で `/items?state=failed` を引く（`loadItems` は既にある）。`counts` の行は `failed` もあるときに出す。
- 実装者の決定 3（「もう一度」＝失敗した `ref` だけの新しいジョブ）は**妥当**だが、押せる場所が無い。

### A-2. `#/tags` の詳細の「訳す」が常に 422（`apps/gui/taglist.js:116-121` → `:124-129`）
- 再現（`page_tags.out.json` §detailTranslate）: `black_hair`（`tag_id 67`）を選んで「訳す」→ 送った本文 **`{"tag_ids":[],"limit":20}`** → 422（画面の `tl-msg` は空のまま。`server.log` に `POST /api/tags/gloss 422` が 1 件）。
- 原因: `translate.addEventListener` が `translateNames([item.name])` を呼び、`translateNames` が `names.map(Number).filter(isFinite)` で名前を落とす。「訳す（20 語まで）」側は `tag_id` を渡しているので動く（§D-9）。
- 直し方: `translateNames([item.tag_id])`。`gui_smoke` に「詳細の訳すが `tag_ids` に数を入れる」を 1 行。

## B. 重大

### B-1. 完了したジョブの 1 枚あたりの時間が増え続ける（`apps/gui/jobs.js:27-36` `pace()`）
- 再現（`page_jobs.out.json` §doneRowPace）: 完了の行の `1 枚 1 分 20 秒` が 4.5 秒後に `1 分 22 秒`。その job は `started_at 02:49:10.05`・`finished_at 02:49:11.35`・3 枚（実際は 0.4 s/枚）。画面写真 `shot-p4-3-tags.png`（`#/jobs`）にも「1 枚 1 分 47 秒」。
- 原因: `perItem = (now - started) / done` を状態を問わず使う。2 秒ごとに描き直すので増え続ける。
- 直し方: `finished_at` があれば `finished_at - started_at` を使う。`gui_smoke` の 8（ジョブの進行）に「完了の行は `finished_at` で計算する」を足す（いまの検査は実行中の行だけ）。

### B-2. `#/tags` の「保存しました」「N 語を訳しました」が一瞬で消える（`apps/gui/taglist.js:102-114` / `:124-143`）
- 再現（`page_tags.out.json` §save / §translate20）: 保存 → `POST /api/tags/67/gloss {"ja":"監査の語釈 <b>太字</b>"}`（`human`）→ 一覧に語釈と `直した` が出る（**保存は成功**）が、`tl-msg` は **空**。「訳す（20 語まで）」も 20 語を訳した（`tag_gloss` が増えた）が `tl-msg` は空。
- 原因: `msg(...)` の直後の `await load()` が詳細（`#tags-detail`）を `innerHTML` で作り直すので、`tl-msg` ごと消える。
- 直し方: `load()` の後にメッセージを入れる（`tags.js` の `wirePanel` はそうしている）か、メッセージの置き場を詳細の外に。

## C. 中程度

### C-1. タグ欄の入口が来歴の下 1,635 px（`apps/gui/app.js:260`）
- `page_asset.out.json` §mount: `#tg-panel` は `#detail` の先頭から **1,635 px**（1400×900）、**スクロール無しでは見えない**。P6-2 の注記の箱は同じ指摘で 2,665 → 341 px に上げた（`gui_layout --screen asset` の `boxTop=341px` は**注記の箱**の値で、タグ欄は測っていない）。
- 直し方: タグ欄を注記の箱の直後（来歴の前）に。`gui_layout --screen asset` に `tgTop` を足す。

### C-2. `#/tags` は 200 語で打ち切り（`apps/gui/taglist.js:73` `limit: '200'`）
- 実データの複製で `200 / 291 語`（`known=all` では `200 / 315`）。`GET /api/tags` の `next_cursor` は返っているが画面は使わない。91 語は検索でしか届かない。設計 §10-11「上位 200 語を出し、検索で残りに届く」の字面どおりではあるが、頭の表示が「200 / 291」なので利用者は「続き」を探す。「次の 200 語」を 1 つ足すか、§4.13 に「上位 200 語まで。残りは検索」と書く。

### C-3. 5 秒より短いジョブは「終わりました」が出ない（`apps/gui/badge.js:56-67`）
- `page_badge.out.json`: 25 枚（9.8 秒）→ `タグ付け中 5 / 25` → `19 / 25` → **`タグ付けが終わりました（25 枚）`**（12.8 秒）。`page_jobs.out.json` §badge: 3 枚（約 1.3 秒）→ **`seen: []`**（バーは何も出さない）。
- 原因: `running` を一度見た job だけ `done` で知らせる（5 秒周期の間に始まって終わると見えない）。
- 直し方: 前回のポーリング以降に `finished_at` が入った `done` も知らせる（`lastStates` に無い job で `finished_at` が最近なら出す）。小さいジョブ（画面の「語を足す」の後の 1 枚など）はこれに当たる。

### C-4. 「その他」の見出し（`apps/gui/tags.js:83`）
- `category` が `null` の語（PNG の自然文の断片、`語彙外`）は **「その他」** の見出しに入る（実物: `キャラ / 一般 / その他`）。設計 §5.1 と `frontend-design.md` §4.13 の見出しは `キャラ → 作品 → 作者 → 一般` だけで「その他」が無い。見せ方は妥当（語彙外を一般に混ぜない）なので、§4.13 に 1 行足す。

## D. 軽微（確かめた結果、問題なし）

1. **線 3**（`page_asset.out.json` §line3、`shot-p4-3-asset-scrolled.png`）: 61 行すべてに `.en` と `.ja` の 2 行、`.ja` は `.en` の下、**語釈の行に `(` `)` を含むものは 0**（訳した後も 0。`page_all.out.json`）、`rem_(re:zero)` は**そのまま**、`.ja` の書体は BIZ UDPMincho。
2. **並びと見出し**: `キャラ → 一般 → その他`、空の見出し無し、一般の中はスコア降順。**スコアはタガーの行だけ・3 桁**（`0.997 / 0.988 …`）。`1girl` は `タガー / 手 / PNG` の**印 3 つ**。`語彙外` は `best_quality / front-facing_angle / …`（PNG の断片）。**「外す」は `手` の行だけ**（`rem_(re:zero)` と `1girl`）。**「訳す」は語釈の無い行だけ**。欄の下に「タガーは下ごしらえです。…訳は自動です。直せます。」の 1 行。`tg-brief` は `PNG 19 ・ タガー 42 ・ 手 2 ・ 語釈待ち 60 語`。
3. **「訳す」1 語**（本物の模型）: `POST /api/tags/gloss {"tag_ids":[115],"limit":20}`、**`X-Image-Reviewer-Actor: human`**、語釈 `リム` が行に出て「1 語を訳しました。」。
4. **「訳す（20 語まで）」**（`page_all.out.json`）: `POST` 1 回・`tag_ids` 20・**語釈待ち 39 → 19**・4.6 秒・「20 語を訳しました。」。翻訳後も語釈の行に括弧 0。
5. **「語を足す」**: 空で「足す」→ POST 0 回。`long` と打つ → `GET /api/tags?q=long&limit=8` → `datalist` に候補 2（先頭 `long_hair`）。`long_hair` で「足す」→ `POST /api/assets/{A}/tags {"name":"long_hair"}`（`human`）→ 「足しました。」→ 行に `手` の印と「外す」、入力は空に。**「外す」** → `DELETE /api/assets/{A}/tags/68`（`human`）→ 「外しました。」→ 行が消える（`wd14` にも無い語だったので）。
6. **`esc()` が実物で効く**: 語釈 `<script>window.__xss=1</script><img src=x onerror=…>` を保存した語 → 拡大の欄で `script` 要素 0・`img` 0・`window.__xss` 未定義・**文字としてそのまま**（`literal: 1`）。`#/tags` の一覧でも同じ（`<b>太字</b>` も文字のまま）。
7. **`GET` は書かない**（`page_view.js`）: `#/asset/A → #/tags → #/jobs → #/tags?known=all` を開いて何も押さない → `fetch` 10 回すべて `GET`、`tag_gloss` 1 → 1・`asset_tag` 391 → 391・`job` 1 → 1。
8. **人為の操作のヘッダ**: 訳す・足す・外す・保存（語釈）はすべて `human`。「タグ付けを始める」「中断」「もう一度」はヘッダ無し（= `agent`）だが、その 3 つの口は `human` を要求しないので問題なし。
9. **`#/tags`**（`page_tags.out.json`、`shot-view-tags.png`）: 既定 `GET /api/tags?known=1&limit=200`、200 行、`語彙外` の印 0、**件数順**（`1girl 7 枚 / 1boy 5 枚 / …`）。「表示」を押す → `#/tags?known=0` で 24 行すべて `語彙外`（`best_quality / masterpiece / safe`）→ `known=all` 315 語 → `known=1` に戻る。検索 `bl` → `GET …&q=bl` → 13 行すべて `bl` で始まる。語を選ぶと右に詳細（名前・枚数・カテゴリ・textarea・保存・訳す）。「訳す（20 語まで）」→ `POST` 1 回・`tag_ids` 20・`human`（語釈は入った。B-2 のとおり文言は消える）。**一括タグ付け**: `枚数 2` → `POST /api/assets/tag {"engine":"auto","limit":2,"force":false}` → `#/jobs` へ移り、バーに `タグ付け中 0 / 2`。
10. **`#/jobs`**（`page_jobs.out.json`、`shot-p4-3-jobs.png`）: 41 枚（実体の無い 1 枚込み）を投げる → **`実行中 / 6 / 41 / 1 枚 0.4 秒 ・ 残り 約 16.0 秒 / 帯 15% / 中断ボタン`**、行に `on`、見出し `1 件が進行中`、バー `タグ付け中 4 / 41`。**中断** → `POST /api/jobs/{id}/cancel` → `中断 / 9 / 41 / 付いた 9 ・ 飛ばした 0 ・ 失敗 0 / 中断しました（付いた語は残ります）`、中断ボタンは消える。**待っています（2 枚）** は `queued` の行の `message` として出る（`STATE_LABEL` は `待ち`。§E-1）。
11. **ポーリング**: `#/jobs` で 6 秒に **`GET /api/jobs?limit=50` が 3 回**（2 秒周期）、`#/tags` に移って 6 秒 → **0 回**。バー（`?limit=5`）は 5 秒周期で続く。`<audio>` 要素は 0（音は使わない）。
12. **`gui_layout`**（3 窓）: `--screen asset`（画像 B、**247 行・236 語が `wd14`**）→ `rows=247 overflow=0 高さの差=2px 印=262 script=0` ok。`--screen tags` → `rows=200 listOverflow=0 pageOverflow=0 detail=true` ok。`--screen jobs` → `rows=4 listOverflow=0 wideTop=1400/1200/1920` ok。回帰: `--count 8`・`--screen requests`・`--screen group` ok。画像 A は `高さの差=42px` で NG（§F-1。検査の作りの問題）。
13. **回帰**: `uv run --no-sync pytest -q` → **282 passed**。`node tools/gui_smoke.mjs` → **122 ok**。P5 / P6 / P4-1 / P4-2 の口（要求・注記・jobs・export）は上の操作の中で 200。実データの mtime 不変。
14. 実装者の決定 1（`frontend-design.md` §4.13。§4.5 は既に「件数と通知」）: 妥当。決定 2（名前 → `tag_id` の地図を `GET /api/tags?known=all&limit=1000` で 1 回）: 取り付け時の `fetch` は 4 回（asset・annotations・tags 一覧・tags）で実測どおり。**API の穴の回避策として妥当**。語が 1,000 を超えると「訳す」が黙って 0 回になる（`idOf` が `null`）ので、`items` に `tag_id` を足す提案（§E-4）に賛成。決定 4（完了の知らせ 60 秒）: 妥当（設計は黙っている）。決定 5（`CATEGORY_LABEL` を 1 か所）: 妥当。決定 6（`gui_shot.mjs`）: 妥当。**Git Bash から `--hash "#/asset/…"` を渡すと MSYS がパスに変換する**（`#C:/Program Files/Git/asset/…` になった）ので、`MSYS_NO_PATHCONV=1` を付ける注意を書く。
15. `gloss.py` / `tagger.py` が 11:25 に変わっている（P4-2 の監査 B-1 の直し。`OSError` を待ち直す）。P4-3 の範囲外だが回帰の 282 に含まれる。

## E. 設計とのずれ

1. **`queued` の文言**: `frontend-design.md` §4.13 / 設計 §5.3 の「待っています」は `job.message`（サーバ）が出し、画面の状態の印は **`待ち`**（`STATE_LABEL`）。画面写真では両方が並ぶ（`実行中 … 待っています（2 枚）`）。1 語にする（印を「待っています」にするか、印は `待ち` と §6 に書く）。
2. **「その他」の見出し**（C-4）: §4.13 に無い。
3. **200 語の打ち切り**（C-2）: §5.2 に「上位 200 語」が無い（§10-11 にはある）。
4. **API への提案 1（`items` に `tag_id`）**: **賛成**。契約（`review.json`）は触らず API の応答だけに足す。`tags.py` の `tag_docs` に 1 行。**提案 2（`_tag_docs` 1 枚 1 クエリ）**: P4-0 の監査 C-3 で「持ち越してよい」と判定済み（263 枚 123 ms、10,000 枚で約 4 秒）。**提案 3（並行作業の注意）**: `tests/test_gloss.py`（11:27）と `gloss.py` / `tagger.py`（11:25）が P4-3 の最中に変わったのは P4-2 の直し。監査の報告に版を書く慣例で足りる。
5. **A-1 は設計 §3.3 の読み方の差**: 「`items_failed` は先頭 20 件だけ返す（全部は `/items`）」を P4-1 が一覧では 0 件にした。設計に「一覧でも先頭 20 件」と書く。

## F. テストで守れないもの

| 観点 | 判定 | 根拠と直し方 |
| --- | --- | --- |
| `#/jobs` の失敗した項目と「もう一度」（A-1） | **守れない** | `gui_smoke` は `jobHtml` に `items_failed` を**手で渡して**描画を見る。画面が読む口（一覧）に `items_failed` が無いことは軽い DOM では見えない。`gui_layout --screen jobs` に「`counts.failed > 0` の行に `.jb-again` がある」を足す |
| 詳細の「訳す」（A-2） | **守れない** | `gui_smoke` は `tags.js` の「訳す」だけ（`taglist.js` は読み込むだけ）。`taglist` の詳細の「訳す」が送る `tag_ids` を検査する |
| 完了の行の 1 枚あたり（B-1） | **守れない** | `gui_smoke` の 8 は `now` を固定して実行中の行を見る。完了の行で `now` を進めても値が変わらないことを足す |
| `#/tags` のメッセージ（B-2） | **守れない** | 軽い DOM の検査が無い |
| 行の高さが揃う（§8.3-3） | **検査が壊れやすい** | 画像 A は語釈 1 つが 3 行に折り返して `高さの差=42px` で NG、画像 B（247 行・短い語釈）は 2 px で ok。**長い語釈は折り返すのが正しい**ので、「`.en` の高さが揃う」か「語釈の行数を除いた差」を測る |
| タグ欄の位置（C-1） | **測っていない** | `--screen asset` の `boxTop` は注記の箱。タグ欄の `top` を足す |
| 線 3・印・スコア・外す・訳す・esc・2 秒ポーリングの開始と停止 | 落ちる形 | `gui_smoke` の 31 件と `gui_layout --screen asset` の `script=0`（実物で確認） |
| 「語を足す」（§8.2-5） | 軽い DOM には無い（申告どおり） | 実物では通った（§D-5）。`gui_layout --screen asset` で「空で押して POST 0・語を入れて POST 1」を足せる |

## G. 依頼者への質問（推奨つき）

| # | 論点 | 選択肢 | 推奨 |
| --- | --- | --- | --- |
| G-1 | A-1 の直し場所 | (a) **一覧の口も `items_failed` 先頭 20 件**（`JobService.list(failed_limit=20)`）／(b) 画面が `/items` を引く | **(a)**。設計 §3.3 の字面に合い、画面の変更が要らない。50 件 × 20 行で十分軽い |
| G-2 | `#/tags` の 200 語（C-2） | (a) **「次の 200 語」を足す**（`next_cursor` を使う）／(b) §4.13 に「上位 200 語。残りは検索」と書く | **(a)**。`next_cursor` は既に返っている |
| G-3 | 短いジョブの知らせ（C-3） | (a) **前回の周期以降に `finished_at` が入った `done` も知らせる**／(b) 5 秒未満は出さないと書く | **(a)**。「語を足す」のあとの小さなジョブが黙って終わるのは §5.5 の趣旨に反する |
| G-4 | `items` に `tag_id`（E-4） | (a) **足す**／(b) 名前→id の地図のまま | **(a)**。語が 1,000 を超えた環境で「訳す」が黙って 0 回になる |
| G-5 | `queued` の印（E-1） | (a) **`待っています`** に揃える／(b) `待ち` のまま §6 に書く | **(a)**。設計と画面の語を 1 つに |

## H. 確かめられなかったこと

- 「終わりました」が **60 秒で消える**こと（出るのは確認した。消えるのは `badge.js` の `DONE_NOTICE_MS` を読んだ判断）。
- `#/jobs` の「もう一度」の往復（A-1 でボタンが出ないため。API で同じ本文を投げれば新しい job になることは P4-1 で確認済み）。
- 1,000 語を超える環境での「訳す」（`idOf` が `null` で 0 回になる経路）。
- `frontend-design.md` §6 / §11 に足した文言の全部（§4.13 と画面の突き合わせだけ）。
- 証拠の注記: `page_asset.out.json` の `translateAll`（`1 語` / `語釈待ち 59`）は**往復が終わる前に取った値**で、正しい値は `page_all.out.json`（20 → 19、4.6 秒）。最初に撮った `shot-p4-3-asset-scrolled.png` は Git Bash が `#/asset/…` をパスに変換してライブラリを写していた（`MSYS_NO_PATHCONV=1` で撮り直した）。`shot-p4-3-tags.png` は `page_tags` の最後が `#/jobs` なのでジョブの画面。`#/tags` の写真は `shot-view-tags.png`。`page_jobs` の 1 回目は「もう一度」で落ちたが中断（9/41）まで動いた。報告は 2 回目の値。
- 後始末: サーバ 8791 停止。`.tmp-audit-redo/p43/` を残した（`srv/` に語釈 63 行・job 8 件・要求 1 つ、画面写真 6 枚）。`.data/` の mtime は 10-15。`src/` `apps/` の最新は `taglist.js` 11:29（実装者）。ComfyUI の `temp/image-reviewer/` は 128 枚。

### 実行したコマンドと結果（主なもの）

```
uv run --no-sync pytest -q                                      → 282 passed
node tools/gui_smoke.mjs                                        → 122 ok
.venv\Scripts\python.exe .tmp-audit-redo/p43/prep.py            → 3 枚にタグ付け、rem_(re:zero) を手で、script の語釈、B に 236 語、実体の無い asset
node cdp.mjs … page_view.js                                     → GET 10 回・書き込み 0（tag_gloss 1→1、asset_tag 391→391）
node cdp.mjs … page_asset.js / page_all.js                      → 線 3、印、スコア、語彙外、外す、訳す 1 語（human）、訳す 20 語（39→19）、語を足す、esc
node cdp.mjs … page_tags.js                                     → 既定 known=1、切替、検索、詳細の訳すが tag_ids [] で 422、保存、20 語、一括タグ付け → #/jobs
node cdp.mjs … page_jobs.js（2 回目）                           → 実行中 6/41、中断 9/41、失敗の行に項目も「もう一度」も無い、2 秒 ×3 / 離れて 0
node cdp.mjs … page_badge.js                                    → 25 枚で「タグ付け中」→「終わりました（25 枚）」、3 枚では出ない
GET /api/jobs vs /api/jobs/{id} vs /items                       → 一覧だけ items_failed が []
node tools/gui_layout.mjs --screen asset（A: NG 42px / B: ok 247 行）/ tags / jobs / --count 8 / requests / group
MSYS_NO_PATHCONV=1 node tools/gui_shot.mjs --hash "#/asset/<A>" --scroll "#tg-panel"
```
