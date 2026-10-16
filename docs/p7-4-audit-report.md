# P7-4（条件の記録の画面 2 つ）監査報告 — 実行込み

- 日付: 2026-10-17（01:48〜02:15 JST）／指示書: `docs/p7-audit-brief-p7-4.md`／実装の記録: `docs/p7-4-implementation.md`／P7-3 の再確認は **`docs/p7-3-audit-recheck.md`** に分けた
- 対象（commit **e777628** ＋ **80f3eaa**。作業木はこの 2 つと同じ。`git status` は指示書だけ）: `apps/gui/recipe.js`（**288 行**、01:03）・`recipelist.js`（106 行、01:04）・`app.js`（480 行、01:06）・`index.html`（01:44）・`styles.css`（01:45）・`jobs.js`（監視の 1 行、80f3eaa）・
  `src/image_reviewer/recipe.py`（876 行、01:42）・`api/recipes.py`（01:04）・`db.py`（`_top_up_v6`、01:00）・`recipe_export.py`（01:03）・`watcher.py`（849 行、01:43）・`tools/gui_smoke.mjs`（990 行、01:45）・`tools/gui_layout.mjs`（776 行、01:09）・`tests/test_db.py`（00:57）・`tests/test_watcher.py`（01:43）
- 設計: `docs/p7-design.md` 1,050 行（01:47。§0.18 / §5）、`docs/frontend-design.md` 886 行（01:44。§4.7〜§4.12 / §6 / §11.9）
- 環境: 実データ `.data`（v6・263 枚・判断 3 件・`recipe_record` 0・`watcher_state` 0・根 2。**`fetched` 列は既に入っている**＝利用者のアプリが新コードで再起動したときに `_top_up_v6` が当たった）は `mode=ro` だけ。複製は `backup()` で `.tmp-audit-redo/p74/data-http`（**8791**）。
  本物の Chrome は `.tmp-audit-redo/p74/cdp.mjs`（headless、CDP）と `tools/gui_layout.mjs`。ComfyUI（8188）へは監視の `GET` だけ（`POST /prompt` は 0）。利用者のアプリ（8790、PID 5564、新コード）は触っていない。
- 触っていないもの: `.data`（`db.sqlite3` 10-15 14:29:51・`-wal` 10-17 01:00:59 のまま。行数不変）、`src/`・`apps/`・`tools/`（壊し方は `.tmp-audit-redo/p74/mut/` の**写し**で行った）。

## 判定: **直してから次へ**

**2 画面は本物の Chrome に在る**: 判定の印（完全 / 近似 / 再現できない）・記録時の理由の日本語・束とファイルと印・結果の行と合否の 4 ボタン・3 窓とも横のはみ出し 0・`<script>` を含む `note` を入れても `script` 要素 0。
記録時の 7 語だけが画面に出る。往復（記録 → 検査 → 書き出し → 一覧 → 手で紐付け → 合否は human だけ・上書き・記録は不変）は口で通った。
2 画面と `#/recipes` の絞り込みを開く前後で**複製の全ファイルと 7 表の指紋が同一**（`f1a95e4f2bf8042e` → 同じ）。`?status=` の語彙外は 422。`fetched` は `/view` の取り込みで 1（P7-3 の再確認 (i)）。
pytest **397 × 3**・gui_smoke（`ok` 151 行。指示書の 142 より多いが全部 ok）・gui_layout **8 画面**すべて緑。gui_smoke は壊し方 5 通りをすべて捕まえる。

落ちているのは、指示書 (1) と (5) が名指しした**画面の入口と操作**で、P4-3 と P6 で踏んだ穴と同じ型。

### 最も重大な 3 件

| # | 何 | 再現と値 | 場所 |
| --- | --- | --- | --- |
| **A-1** | **`#/jobs` の「見る / 止める」が押しても動かない**（`POST /api/watcher/start` が **403**。画面には何も出ない） | 本物の Chrome で `#/jobs` を開き「見る」を押す → `fetch` を包んで観測: `POST /api/watcher/start → 403`、行は「止まっています」のまま、サーバの `enabled=false`（`chrome.out.txt`） | `apps/gui/jobs.js` の `toggleWatch()` が **`X-Image-Reviewer-Actor` を送らない**（`recipe.js:136` の `post()` は送る）。ヘッダ無しは `agent` 扱いで `require_human` が 403。`gui_smoke` は HTML だけ、`gui_layout --screen jobs` は押さないので**どちらも捕まえない** |
| **A-2** | **拡大の画面の入口「条件の記録」がスクロール無しでは見えない**（指示書 (1)。P4-3 の穴） | `#/asset/<id>` を 1400×900 / 1200×800 / 1920×1080 で開く → `.rc-link` の `top` は **1250 / 1270 / 1250 px**、見える高さは 900 / 800 / 1080。右の `#detail`（`clientHeight 795`・`scrollHeight 1388`）の**最下部**にあり、上に注記の箱 168 px・タグ 178 px・**来歴の表 380 px** が乗る（`chrome.out.txt` / `shot-zoom-1400x900.png`） | `app.js` が「来歴の下」に置いた（§0.18）。来歴は画面の一番下。**画像のすぐ下**（タグの `tgTop=575` は見えている）か上の帯に移す。`gui_layout --screen asset` は `tgTop` を測るが入口は測らない |
| **A-3** | **書き出し時の 3 語（`text_pinned` / `llm_nondeterministic` / `manual_step`）が画面に一度も出ない** | ja2en の記録を `rerun_graph` で書き出す → 口の `checked.reasons=['llm_nondeterministic']`。その束を画面で見ると**理由は無い**（`exportReasonWordsOnScreen: []`。3 窓とも）。`EXPORT_REASON_LABEL` は定義だけで `exportReasonText()` は**未使用**、`attemptHtml()` は `checked` を読まない | `recipe.js:160-176`。設計 §4.8「L2 のときは訳が変わりうる理由を 1 行」「L1 の再現キーは変わる（`text_pinned`）」。「混ぜていない」は**出していないから**成り立っている |

---

## A. 直っていない／設計の約束が成り立たない（必ず直す）

### A-1 `#/jobs` の見る / 止めるが 403

- 再現: `node .tmp-audit-redo/p74/cdp.mjs http://127.0.0.1:8791/#/jobs .tmp-audit-redo/p74/page_jobs.js`（`callsAfterClick` に `POST /api/watcher/start 403`）。
- 直し方: `toggleWatch()` に `'X-Image-Reviewer-Actor': 'human'` を付け、失敗したら 1 行で知らせる（§7 の楽観的更新と同じ）。テスト: `gui_smoke` で `toggleWatch` 相当の `fetch` の `headers` を見る、`gui_layout --screen jobs` で押して `enabled` が変わることを見る（押した後に `stop` を打つ）。

### A-2 入口がスクロールしないと見えない

- 再現: `page_zoom.js` / `page_zoom2.js`。`visibleWithoutScroll: false`（3 窓）。
- 直し方: `app.js` の `prov-recipe` を画像の直下（注記の箱の上）か、拡大の上の帯（`topbar`）に移す。`gui_layout --screen asset` に `rcTop` と `rcVisible` を足す。

### A-3 書き出し時の 3 語を出さない

- 再現: `http_roundtrip.out.txt`（`prep.out.txt`）の ja2en の 3 束と `chrome.out.txt`（ja2en の画面）。
- 直し方: `attemptHtml()` で `item.checked.reasons` のうち **3 語だけ**を `EXPORT_REASON_LABEL` で出す（記録時の語は出さない。下の E-2 を先に）。`gui_smoke` の `EXPORTS` に `checked: {reasons: ['llm_nondeterministic']}` を入れて文言を固定する。

## B. 重大

### B-1 結果の行に**指標が出ない**・**メモが打てない**（設計 §4.10 / §4.11）

- 画面の結果の行: `hasMetrics: false`（`ssim` / `pHash` / 変化した画素 / 平均差が無い）、`noteInput: false`。合否の口は `note` を受けるが画面に入力が無く、**押すたびに `note=None` で上書き**（P7-3 の C-2 と合わせて、画面からはメモを残せない）。
- 直し方: 行に 4 指標（単位つき。閾値は出さない）と `メモ` の入力を足し、ボタンで `{verdict, note}` を送る。

### B-2 口の `checked.reasons` が**記録時の語と書き出し時の語を 1 つの配列に混ぜる**（P7-2 由来）

- ja2en を `pin_text` / `manual_text` で書き出すと `checked.reasons=['text_not_captured']`（記録時の語）、`rerun_graph` で `['llm_nondeterministic']`（書き出し時の語）。設計 §0.6 は書き出し時の `checked_json` に **3 語**。画面で分けるには口が分けて返す必要がある（`reasons` と `record_reasons`、または `kind` に印）。A-3 の前提。

## C. 中程度

- **C-1** `#/asset/<id>/recipe` に **「フォルダを開く」「manifest を読む」「JSON を保存」が無い**（§4.9・§5.1。利用者の出口は D&D なのに、フォルダの場所を画面に出さない）。`export_dir` / `manifest_path` は口から来ている（`http_roundtrip.out.txt`）。
- **C-2** レベルの選択が `?level=` に出ない・「L1 が既定で、`final_prompt` が無いときは L2 に落ちたことを出す」が無い（§4.8 / §5.1）。`mode` の `select` は在る（3 語）。
- **C-3** 結果の行に**サムネ**が無く「結果を開く」の文字リンクだけ（§4.10）。`#/recipes` の行にも**サムネと書き出しの回数**が無い（§5.2）。
- **C-4** 「印を付けられません」のときの選択（**書き出しを止める / `SaveImage` を足す / 印なしで書き出す**）が無い（§5.1・§6）。`checkHtml` は理由を出すだけで、`書き出す` はそのまま印なしで通る。
- **C-5** P7-3 の再確認で**直っていない 4 件**（sidecar の置き場・根の追加の通知・紐付けの seed・`note` の消失）と `texts` の二重カウント（`docs/p7-3-audit-recheck.md`）。

## D. 軽微

- **D-1** 「グラフを見る」は `/api/assets/{id}/graph?format=api`（200）。設計 §3.1 の `GET /api/recipes/{id}/graph` は **404**（P7-2 が asset 側に作った）。設計を実装に合わせる。
- **D-2** `POST /api/recipes/{id}/check` は `actor` を読まない（`robot` でも 200）。設計 §3.1 で `check` は画面・エージェントが呼ぶ読みなので害は無いが、指示書 (6) の「語彙外は 422」からは外れる。`export` / `results` / `verdict` / `watcher/start|stop` は `robot` 422・`agent` 403 を確認。
- **D-3** `#/recipes` の判定の切り替えはボタンの**循環**（すべて → 完全 → 近似 → 再現できない）。4 択を直接選べない。
- **D-4** 「記録の一覧へ」「← 拡大」は `topbar` に在るが、`#/recipes` から 1 枚へは行だけ（設計 §5.2 どおり）。
- **D-5** 確かめた結果、問題なし: 3 窓で `overflow 0` / `pageOverflow 0`、`scripts 0`（`note` に `<script>alert(1)</script><b>bold</b>` を入れて**文字のまま**、`b` 要素 0）／判定の印 `完全` / `近似`（理由「英文が画像に残っていない」）/ `再現できない`（「画像に条件が残っていない」）／束に `印あり`・ファイル数・`repro-<id>/seed-<n>`／結果の印「手で紐付け」「参照」「鍵が違う」／合否 4 ボタン × 結果の数／
  `GET` の指紋同一（2 画面・3 窓・`#/recipes` の絞り込み 2 回。ファイル 0・7 表 0）／`#/recipes` の絞り込みが `#/recipes?status=exact` → `?status=approx` に変わり `GET /api/recipes?limit=50&status=…` を 1 回ずつ／「次の 50 件」は 8 件では出ない（`next_cursor` 無し）／
  往復: 記録 201 `exact` → 検査 200 `marker_ok` → 書き出し 201（2 seed・印）→ 一覧 200（束 2・`results`）→ 紐付け 201 `manual` → 合否 agent 403・human 200・上書き → `GET /api/assets/{id}/recipe` のバイト一致／`?status=nope` 422・`limit=abc` 422・`cursor=bad` 422／
  `_top_up_v6`: P7-3 の複製（`fetched` 無しの v6）に列が入っている（`data-oldv6`）。`/view` の取り込みで `fetched=1`（P7-3 の再確認 (i)）／`#/jobs` の 1 行の表示と `GET /api/watcher` が書かないこと／8790（利用者）の `GET /api/watcher` 200。

## E. 設計とのずれ

| # | 何 | 設計 | 実装 | 判定 |
| --- | --- | --- | --- | --- |
| E-1 | 入口の位置 | §5.1「上部に固定」、指示書「画像のすぐ下」 | 来歴の下（画面の最下部） | 今直す（A-2） |
| E-2 | 書き出し時の理由の表示 | §4.8 / §4.9 | 無い | 今直す（A-3。口は B-2） |
| E-3 | 結果の指標・メモ・サムネ | §4.10 / §4.11 | 無い | 指標とメモは今直す（B-1）、サムネは持ち越してよい |
| E-4 | フォルダを開く / manifest | §4.9 / §5.1 | 無い | 持ち越してよいが、`export_dir` の**文字列**だけは出す（C-1） |
| E-5 | レベル `?level=`・L2 への落ち方 | §4.8 / §5.1 | `mode` の select | 持ち越してよい（C-2） |
| E-6 | 印を付けられないときの選択 | §5.1 / §6 | 理由を出すだけ | 持ち越してよい（C-4） |
| E-7 | プリセットの一覧 | §5.2 / §4.12（P7 の範囲） | 無い（口も無い） | **妥当**（口が無い物の画面は作れない）。ただし**黙って落とさず §9 に「P7-5 か P8」と書く**（G-4） |
| E-8 | `GET /api/recipes/{id}/graph` | §3.1 | `/api/assets/{id}/graph` | 設計を直す（D-1） |
| E-9 | `#/recipes` のサムネ・書き出し回数 | §5.2 | 無い | 持ち越してよい |

実装者が自分で決めた 6 点: (1) `?status=` を足した → 妥当（422 も確認）。(2) `_doc_of` が `graph_source` を返す → 妥当。(3) 経路の順序 → 妥当（`#/asset/<id>/recipe` が勝つのを確認）。(4) 次の 50 件は足す → 妥当（8 件では未検証）。(5) `recipeLinkHtml(id, null)` は状態を読まない → 妥当だが **A-2 の位置が問題**。(6) 合否のボタンは常に 4 つ → 妥当。
残した所: `#/jobs` の 1 行 → 入ったが A-1。プリセット → E-7。

## F. テストで守れないもの

| 検査 | 結果 |
| --- | --- |
| `gui_smoke`（写しで壊す。`.tmp-audit-redo/p74/mut/`） | M1 `esc` を素通し → **1 件 NG**／M2 記録時の語に `text_pinned` を混ぜる → **2 件 NG**／M3 合否のボタンを 2 つ → **1 件 NG**／M4 開くときに `POST` → **1 件 NG**／M5 `fetched` の印を消す → **1 件 NG**。**5/5 捕まえる** |
| `gui_layout --screen recipe` | 印・束・結果・ボタン 4・`script` 0・はみ出し 0 を測る。**押さない**ので A-1 型は捕まえない。`markTop=54` は「判定の印の位置」で、**入口の位置は測らない**（A-2） |
| `gui_layout --screen asset` | `tgTop` / `tgVisible` は測るが `.rc-link` は測らない → **A-2 を捕まえない** |
| `gui_layout --screen jobs` | 行の有無だけ。**「見る」を押さない** → **A-1 を捕まえない** |
| `gui_smoke` の「混ぜない」 | `REASON_LABEL` と `EXPORT_REASON_LABEL` の**キーの重なり**を見るだけ。**画面に 3 語が出るか**は見ない → A-3 を捕まえない |
| pytest | 397 × 3 で揺れ無し。`test_the_fetched_column_is_topped_up_on_an_older_v6_database` は列の有無だけで `CHECK` の有無は見ない（再確認 G-5） |

## G. 依頼者への質問（推奨つき。待たずに推奨で進める）

| # | 論点 | 選択肢 | 推奨 |
| --- | --- | --- | --- |
| G-1 | 入口の置き場 | (a) 画像の直下（注記の箱の上）に 1 行 (b) 拡大の `topbar` に「条件の記録」ボタン (c) 来歴の下のまま＋来歴を畳む | **(a)**。タグの `tgTop=575` が 3 窓で見えている実績の位置 |
| G-2 | 書き出し時の理由の口の形（B-2） | (a) `checked.reasons` は 3 語だけにし、記録時の再評価は `checked.record_reasons` に分ける (b) `kind` ごとに `scope` を付ける | **(a)**。画面は配列をそのまま日本語にできる |
| G-3 | 合否のメモ | (a) 行に入力を置き `{verdict, note}` を送る。`note` 無しの上書きは前の `note` を保つ（P7-3 C-2） (b) メモは P8 | **(a)**。失敗（`failed`）の一言を残す場所が無い |
| G-4 | プリセットの画面と口 | (a) §9 に P7-5（`POST /api/recipes/{id}/presets` ＋ `#/recipes` の下半分）を足す (b) P8 へ | **(a)**。§4.12 の中身は小さい |
| G-5 | 指標の表示 | (a) 4 指標を単位つきで並べる（閾値なし） (b) `same_hash` / `seed_changed` の印だけ | **(a)**。§4.10 の約束で、値は口に在る |
| G-6 | P7-3 の直っていない 4 件 | (a) P7-4 の直しと一緒に入れる (b) 持ち越しと §9 に書く | **(a)**。sidecar の置き場と根の通知は P8（後始末）の前提になる |

## H. 確かめられなかったこと・証拠の注記・後始末

確かめていないこと:
- 「上部に固定」（§5.1）は、束が少なく画面が縦に溢れないので**固定かどうか判定できない**（`docHeight == innerHeight`）。
- 「次の 50 件」は記録 8 件なので出ない（P4-3 の頁送りの罠は口の keyset で確認済み）。
- `--screen recipe` の「印なし」の束は実データに無い（`gui_smoke` の偽データで文言は確認）。
- 本物の生成（線 9）は禁止のため未実施。

紛らわしい出力・罠:
- **`cdp.mjs` を Python の `subprocess` から起動すると headless Chrome が立たない**（`devtools が立たない` × 10）。bash から直接 `node` を呼ぶと動く（sandbox の差）。`CDP_PORT` / `CDP_PROFILE` を run ごとに変え、終わりに `taskkill /T` で木ごと止める形にした（`.tmp-audit-redo/p74/cdp.mjs`）。
- ページの 404 は `favicon.ico`（20 回）と私の `GET /api/recipes/{id}/graph` の探り 1 回。
- `gui_smoke` の `ok` は 151 行（指示書 142・記録 142+13+4）。数え方の差で、NG は 0。
- `recheck_watch.out.txt` の (a) `rows=20` は私の画像の色が 20 周期で同じ中身になった（sha256 が同じ → 既存の asset）ため。中身を変えた `recheck_a1_a3.out.txt` が正。

回帰: pytest **397 × 3**・gui_smoke すべて ok（151）・gui_layout 8 画面すべて ok（`layout.out.txt`）・実データ `.data` 無傷（`recipe_record` 0・`watcher_state` 0・mtime 不変）。

後始末: 止めた: 8791（`data-http`）、headless Chrome（`remote-debugging-port=93xx` の物だけ）。残した: `.tmp-audit-redo/p74/`（複製 `data-http` / `data-oldv6`・`svc/`・`mut/`・`chrome-profiles/`・`shot-*.png`・`*.out.txt`）。利用者の ComfyUI の `output/` には書いていない。

実行したコマンド（`cd C:\work\image-reviwer`、`$env:UV_CACHE_DIR`、`PYTHONUTF8=1`）:

```
uv run --no-sync pytest -q（× 3）／ node tools/gui_smoke.mjs
python .tmp-audit-redo/p71/copy_real.py .tmp-audit-redo/p74/data-http → IMAGE_REVIEWER_DATA=… uv run --no-sync image-reviewer serve --port 8791
python .tmp-audit-redo/p74/http_roundtrip.py 8791 ／ prep（note に script・ja2en を 3 mode で書き出し）／ watch_http（start → root・attach seed）
MSYS_NO_PATHCONV=1 CDP_PORT=934x CDP_PROFILE=… VIEW=1400,900 node .tmp-audit-redo/p74/cdp.mjs http://127.0.0.1:8791/#/asset/<id>/recipe .tmp-audit-redo/p74/page_recipe.js   # page_zoom / page_zoom2 / page_recipes / page_jobs も同じ形。前後に fp.py で指紋
MSYS_NO_PATHCONV=1 node tools/gui_layout.mjs --base http://127.0.0.1:8791 --count 8 / --screen requests / group / asset / tags / jobs / recipe --ids <id> / recipes
cd .tmp-audit-redo/p74/mut && node tools/gui_smoke.mjs（recipe.js を 5 通りに書き換えた写し）
```

## 最も重大な 3 件（再掲）

1. **A-1** `#/jobs` の「見る / 止める」が 403 で動かない（`jobs.js` の `toggleWatch` が actor ヘッダを送らない）。画面に知らせも無い。
2. **A-2** 拡大の入口「条件の記録」が 3 窓とも `top 1250 px` で、スクロール無しでは見えない（来歴の下＝画面の最下部）。
3. **A-3** 書き出し時の 3 語が画面に一度も出ない（`EXPORT_REASON_LABEL` は未使用。口の `checked.reasons` は記録時の語と混ざる）。
