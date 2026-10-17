# P8-3 監査報告（重複と削除の画面。`#/duplicates`・`#/pending-deletes`）— 実行込み

- 日付: 2026-10-18（JST 04:30〜05:30）
- 指示書: `docs/p8-3-implementation-brief.md`（55 行）。実装の記録: `docs/p8-3-implementation.md`（183 行。決めた点 16・申し送り 6・設計の穴 5）。再確認の仕分け: `docs/p8-2-audit-recheck-triage.md`（38 行）。
- 対象（コミット `1da1a08`、04:25:26 JST。15 ファイル +2467/-21）: `apps/gui/duplicates.js`（446 行。新規）、`apps/gui/pending.js`（495 行。新規）、`apps/gui/app.js`（+49。道 2 つ）、`apps/gui/badge.js`（+36。上部バーの入口）、`apps/gui/index.html`（+57）、`apps/gui/styles.css`（+162）、
  `src/image_reviewer/deletions.py`（+87/-9。D-1・D-2）、`tests/test_deletions.py`（+90・3 件）、`tools/gui_smoke.mjs`（+390・76 件）、`tools/gui_layout.mjs`（+362。`--screen duplicates` / `--screen pending`）、`docs/frontend-design.md`（+36）、`docs/p8-design.md`（+1/-1。E-3）。
  監査中の `git status` は本報告だけが untracked。
- 設計の版: `docs/p8-design.md` 997 行・`docs/frontend-design.md` 925 行。
- 環境: `uv run --no-sync`。実データ `.data` は `mode=ro` と `backup()` の複製だけ。**画像は 1 枚も動かしていない**（複製は `shutil.copy2` で読むだけ）。複製は `.tmp-audit-redo/p8-3-audit/`（`srv/`・`srv-lib/` 13 枚＝距離 ≤6 の先頭 5 群・スクリプト 9 本・出力）。
  サーバは複製で **8791**（`IMAGE_REVIEWER_DATA` を付けて起動し、終了後に待ち受け 0 本）。**8790 は止めていない**（PID 19392・`started_at 2026-10-17T18:30:13Z`＝P8-2 の直し（`99c5b2e`）のコード。送ったのは `GET` だけ）。ComfyUI は触っていない。
- 実データ: 監査の最初と最後に `mode=ro` で読み直して **v6・23 表・263 枚・判断 3 件・`deleted_at` 0・台帳 0・要求 0・凍結 0・除外 0・まとまり 0**、画像 263 枚の署名 **`fa99ca126c393d5a`・合計 292,561,491 B**（前回と同じ）。`db.sqlite3` 00:07・`-wal` 02:01 のまま。コミットしていない。
- 回帰: **pytest 403 passed × 3 回**（19.35 / 19.35 / 19.31 s）、**gui_smoke 205 ok / NG 0**、**gui_layout 8 画面すべて ok（各 3 窓）**。ただし新しい 2 画面は**前提の行（理由が `<script>` の除外・段 3 の保留）が複製に在るときだけ ok** で、素の複製では 3 窓とも NG（D-6）。

## 判定: **合格（条件つき）**

2 画面は本物の Chrome に在り、**押して動く**。複製 8791 で私が本当に押した流れ（`click_flow.mjs`。POST は飲まず本物。裏側は API とファイルで確認）: **計算する**（未計算 2 枚 → 202 の job → `unhashed 0`・群 20 → 21）→ **まとまりにする**（`kind duplicates`・2 枚のまとまりが API に在る）→ **別物として確定**（除外 1・群 20）→ **解除**（除外 0・群 21）→ 群 0 の 2 枚だけ選んで**削除へ回す**（`#/pending-deletes?ids=`。重複の画面は何も書かない）→ **段 1**（凍結 2 件・台帳 stage 1・一覧 263 → 261・ファイルは動かない）→ **段 2**（ゴミ箱 2 件・元の場所に無い・画面のゴミ箱 2 行 → **戻す** ×2 で 0 件・ファイルが戻る）→ **段 3**（「最後の 1 つが 2 枚」「これも消す」。印なしで押すと止まり台帳 0・印を付けて保留 2 件・画面に「あと 4:59」×2・上部バーに「最近の削除 2 ・ あと 5:00」）→ **取り消す**（元の場所に戻り保留 1）→ 元の場所を埋めて**取り消す**（409 の文・API は `stuck`）→ 再読込 → **別名で戻す**（`.1.png` に戻り、置いたファイルは無傷）→ 段 3 → **いま消す**（確認 1 回・保留の実体が消え `purged`・上部バーの入口が消える）。全部 200 で裏側と一致。除外の理由 `<script>alert(1)</script>` は文字のまま（`script` 要素 0）。
実装者が写真で見つけた穴（GET で人と名乗らないと `undoable` が偽）は直っている（`pending.js` の `asHuman()`。本物のサーバで人の削除に「取り消す」が出る）。D-1 / D-2 / E-3 は**壊すと落ちる**（Y1〜Y3 の 3 通りとも狙った試験が落ちる）。GET は 1 バイトも書かない（画面を 12 秒開いたまま＝上部バーの 5 秒周期と毎秒の見た目の書き換えを含めて、全表の中身の sha256 と全ファイルが同じ）。

条件は 2 つ。(1) **削除の入口が重複の画面にしか無い**（C-1）。ライブラリ・拡大・まとまりのどこからも任意の画像を段 1〜3 に掛けられない（設計 §5「入口 `#/asset/<id>`」・§11「削除の入口」）。(2) **段 1 で外した行は「最近の削除」に出ず、画面からは戻せない**（C-2）。段 1 は画面で実行できるのに、戻すのは API だけ。もう 1 つ小さいが押して分かった物: (3) **409 `target_exists` の直後に「別名で戻す」のボタンが出ない**（C-3。文は「『別名で戻す』で戻せます」と言うのに、再読込するまでボタンが無い）。

**最も重大な 3 件**

1. **C-1 削除の入口が重複の画面にしか無い。** `#/duplicates` の「選んだ N 枚を削除へ回す」→ `#/pending-deletes?ids=` だけが削除の確認への道。ライブラリの下部バーは「比較を開く」だけ（`index.html:60-67`）、`#/asset/<id>` にも無い。設計 §5 の「入口」行（`p8-design.md` L695）は「`#/asset/<id>` に段 1〜3 の削除（画像のすぐ下）」、`frontend-design.md` §11 L850 は「まとまり・フォルダ・検索結果の下部バー、および手で選んだとき」。P8-3 の指示書は「選んだ物を削除へ回す」としか書いていないので実装者の判断は指示書どおりだが、**利用者が「失敗した大量生成をまとめて消す」（専門 §3.1）をこの画面でできない**。推奨 G-1。
2. **C-2 段 1 の行は画面から戻せない。** `GET /api/pending-deletes` は段 3 だけを返し（`deletions.py` `pending()`）、画面もそれしか出さない（`pending.js:110-131`・`runningHtml`）。段 1 を画面で実行した直後（`click_flow` S5: 台帳 2 行・一覧 263 → 261）、「取り消せる削除はありません。」と出て取り消すボタンは 0。`undo` は段 1〜3 に効く（再確認 E-3）のに、押し先が無い。`frontend-design.md` §4.6 L426「1 行 = `deletion_log` の 1 行」とも違う。推奨 G-2。
3. **C-3 409 の直後に「別名で戻す」が出ない。** `pending.js:370-390`（`undo()`）は失敗したとき `render()` だけで `load()` を呼ばないので、行は `pending` のまま（`undoable` の「取り消す」だけ）で、文「元の場所に既にファイルがあります。「別名で戻す」で戻せます。」の押し先が無い。`click_flow` S8: 直後は `.pd-ascopy` 0 → `再読込` の後に 1。利用者は文を読んで探す。失敗の道でも `await load()` する（1 行）。

---

## A. 直っていない／設計の約束が成り立たない

- 無し。

## B. 重大

- 無し。

## C. 中程度

### C-0 確かめた結果、問題なし（1 行ずつ。実行したもの）

- **2 画面が本物の Chrome に在る**: `gui_layout --screen duplicates` 3 窓 ok（群 20 / API 20・枚 54・おすすめの印 20・しきい値 3・はみ出し 0/0・入口（まとまりにする）が見える・押すと `POST /api/groups` 1 回・除外 1 回・除外の理由は文字のまま `script=0`）。`--screen pending` 3 窓 ok（行 1・残り「あと 5:00」・段の印「1 印→2 ゴミ箱→3 実削除」・はみ出し 0/0・上部バー「最近の削除 1 ・ あと 5:00」・押すと取り消しの POST 1 回）。`--screen pending --ids a,b` 3 窓 ok（削除の確認が見える・凍結の POST 1・一覧 2・消す用意の POST 1・`confirm: true`）。既存 6 画面も各 3 窓 ok。
- **押して動く**（上の判定の流れ。`click_flow.out.txt`）。
- **実装者が写真で見つけた穴**: `pending.js` の `asHuman()` が `GET /api/pending-deletes` と `/api/trash` に `X-Image-Reviewer-Actor: human` を付ける。本物のサーバで人の段 3 に「取り消す」が 2 つ出た（S7）。`gui_smoke` に検査あり。
- **D-1 / D-2 / E-3**: `deletions.py` の `_drop_request`（`NOT EXISTS (SELECT 1 FROM deletion_log WHERE request_id = ?)`）・`_original_state`（`missing` / `same` / `different`）・`_restore` と `_recover_missing_hold` の `different` → `stuck`。壊し試験 Y1〜Y3 で 3 / 3 落ちる。E-3 は `p8-design.md` §3.2 L593 に入った。
- **GET は 1 バイトも書かない**: 段 3 を 1 件作り（残り 300）、ライブラリを 6 秒・最近の削除を 6.5 秒開いたまま（上部バーの 5 秒周期の `GET /api/pending-deletes` と毎秒の見た目の書き換えを含む）→ 前後で全表の中身の sha256 `cd83c834c53fda89` と全ファイル `9e5f5a8353b2bdf5` が同じ。画面の残り時間は毎秒減るが API は 300 のまま（S7）。
- **文言**: `frontend-design.md` §6 の P8-3 の行と画面を突き合わせ（完全重複の 1 行・未計算・まとまり・別物・段の名前・最後の 1 つ・入口・段の印・誰が・戻せない・拾い物・いま消す・ゴミ箱）。ずれは D-1〜D-5。「取り消す」は削除の取り消しにだけ（§6 L735）。
- **決めた点と未実装**: 下の E。
- **回帰**: pytest 403 × 3・gui_smoke 205・gui_layout 8 画面（前提つき）・実データの署名と削除 0 件は上のとおり。

### C-1 削除の入口が重複の画面にしか無い（最も重大の 1）

- 場所: `apps/gui/index.html:60-67`（下部バー）・`apps/gui/app.js:399-418`（道は 2 つ）・`apps/gui/duplicates.js` `toDelete()`（`#/pending-deletes?ids=` へ渡すだけ）。設計 `p8-design.md` §5 L682・`frontend-design.md` §11 L850・§6 L686-688（削除の確認の文言は「3 枚を完全に消します…」＝一括の選択から）。
- 判定: 指示書の範囲内だが、設計の入口 2 つ（拡大の「画像のすぐ下」・一覧の選択から）が無い。P8-5「画面の仕上げ」に回すなら、§9 の P8-3 の行にそう書く。

### C-2 段 1 の行は「最近の削除」に出ず、画面から戻せない（最も重大の 2）

- 場所: `apps/gui/pending.js:110-131`（`rowHtml`。段 3 の行だけ）・`:242-255`（`load()` は `pending` と `trash` だけ）。`GET /api/deletions`（台帳）は画面が読まない。
- 再現: `click_flow` S5。段 1 の 2 枚を画面で実行 → 台帳 2 行（stage 1）・`GET /api/assets` 263 → 261 → 画面は「取り消せる削除はありません。」・`取り消す` 0。実装者の記録の設計の穴 1（段 1 → 段 2 の導線が無い）と同根。
- 推奨 G-2: 「最近の削除」に段 1・2 の行も出す（`GET /api/deletions?limit=` を読み、段 1 は「戻す」、段 2 はゴミ箱の行と同じ「戻す」）。残り時間は段 3 だけ。

### C-3 409 の直後に「別名で戻す」のボタンが出ない（最も重大の 3）

- 場所: `apps/gui/pending.js:370-390`（`undo()` の失敗の道は `render()` だけ）・`:110-131`（`rowHtml` は `state === 'stuck'` のときだけ「別名で戻す」を出す）。設計 `frontend-design.md` §6 L704「戻せませんでした。…」＋「別名で戻す」「いま消す」・`p8-design.md` §0.6-4「止めて尋ねる（`as_copy` で送り直す）」。
- 再現（`click_flow` S8。本物のサーバ）: 段 3 の後に元の場所へ別のファイルを置いて「取り消す」→ 文は出る・API の `state` は `stuck` → **`.pd-ascopy` は 0** → 「再読込」→ 1 → 押すと `.1.png` に戻る。
- 推奨: 失敗したら `await load()`（成功の道と同じ）。

## D. 軽微

- **D-1 括弧書きが画面の文言に多い。** `index.html:193-198`（`dup-help` に 3 つ）・`:222-227`（`pd-help` に 2 つ）・`pending.js:235`（凡例「カタログから外すだけ（容量は空きません）」）・`:206`・`:377`・`:384`・`:418`・`duplicates.js:136`・`:202`・`:274`。本物の画面で数えると `#duplicates` に 4 個・`#pending` に 3 個。`frontend-design.md` の「括弧を使わない」は**語釈の行の規則**（§2.3 L104・§4.13 L618-619）で、§6 の表自身も括弧を使っている（L686「ComfyUI につながりません（127.0.0.1:8188）」）ので違反ではない。ただし実装者が §6 に足した行（L692）は「括弧書きを使わない」と書き、`gui_smoke` はその 1 行だけを見る（`gui_smoke.mjs:1067`）。規則をどちらかに揃える。
- **D-2 固定の数と名前が画面の文言に埋まっている。** `duplicates.js:136`「絵を読んで指紋を作ります（**263 枚で 2.6 秒**。画面は止まりません）」は実データの数で、別の置き場では嘘になる。`pending.js:207`「この置き場は別のツール **illust-authoring** の管理下です」は段 3 の凍結なら**どの置き場でも**出る（複製の `srv-lib` でも出た。`click_flow` S7）。`root.display_path` か `not_allowed` から組み立てる。
- **D-3 「戻せませんでした」の理由が 1 種類。** `pending.js:115-118` は `stuck` の全行に「保留していたファイルが見つかりません。」を出すが、`target_exists`（元の場所が埋まっている。保留は在る）でも同じ文になる。API の `state` に理由が無い（`deletions.py` `_state_of`）。`stuck_reason`（`target_exists` / `move_failed` / `different` / `missing`）を API に足して文を分ける。
- **D-4 まとまりの題名に括弧と数**（`duplicates.js:274`「重複の候補（距離 0・2 枚）」）。まとまりレビューの見出しに出る。§6 の「中黒で繋いだメタ情報」は使わない語。
- **D-5 「最後の 1 つ」の文言のずれ。** `frontend-design.md` L699「最後の 1 つです。ほかに実体がありません。」に対し `pending.js:209`「最後の 1 つが N 枚あります。ほかに実体がありません。」。意味は後者が正しい（枚数が要る）ので文言表を直す。
- **D-6 `gui_layout` の 2 画面は前提の行が複製に無いと NG。** `--screen duplicates` は**理由が `<script>alert(1)</script>` の除外が 1 件在る**ことを要求し（`gui_layout.mjs:374-388`・`:731-735`）、`--screen pending` は**段 3 の保留が 1 件以上**（`:803`「入口が見える（先頭の行）」）。素の複製では 3 窓とも NG（`layout.out.txt`）。実装者は `make_views.py` で前提を作って ok にしている。前提を `--screen` の中で作れない以上、無いときは「前提が無い」と注意を出して ok 扱いにするか、README に前提を書く。
- **D-7 8790 は P8-3 の裏側ではない。** 利用者のアプリは 03:30 起動（`99c5b2e`）のままで、静的ファイル（`apps/gui`）だけが新しい。画面は動くが D-1・D-2 の直しは載っていない（失敗の道だけなので実害は無い）。次の再起動で揃う。
- **D-8 `GET` の読みは `badge.js` だけ人と名乗らない**（`fetchDeletes`。`undoable` は使わないので害は無い）。
- **D-9 ゴミ箱の行は「取り消す」ではなく「戻す」**（`pending.js` `trashHtml`）。§11 L865 どおりだが、§6 L735「『取り消す』は削除の取り消しにだけ」と並ぶと、段 2 の取り消しを「戻す」と呼ぶ理由が文言表に無い。1 行足す。
- **D-10 凍結の失効（10 分）の画面は作り物でしか見ていない**（`gui_smoke`。本物で 10 分待つ試験は無い）。`preview.expired` の分岐は読みでは正しい。

## E. 設計とのずれ（実装が決めた所を含む）

実装者の「決めた点」16 行の判定: 1（削除の確認を `#/pending-deletes` の中に）妥当。2（凍結の一覧は押した後）妥当。3（段を変えたら凍結を捨てる）妥当・実機で確認。4・5・6・7 妥当。8（GET でも人と名乗る）妥当（設計の穴 3 として `frontend-design.md` §10 に 1 行足すべき）。9（現地時刻）妥当。10（凡例に印なし）妥当。11（esc）妥当・実機で確認。12（URL に持つ）妥当。13・14・15 妥当（15 は pyc の罠の記録として良い）。16（D-8 の巻き取りも `_drop_request` 経由で、台帳が参照していれば 409）妥当。

- **E-1 §5「入口 `#/asset/<id>`」と §11「削除の入口」が無い**（C-1）。
- **E-2 §4.6「1 行 = `deletion_log` の 1 行」に対し、画面は段 3 だけ**（C-2）。
- **E-3 §5（Q8）「印が無い置き場では段 3 のボタンを出さない」は未実装**（申し送り 2。段 3 のラジオは常に出て、凍結の `not_allowed_count` を 1 行で出す）。`allow-stage3` の口が P8-4 なので、いまは妥当。
- **E-4 §5「ゴミ箱 `#/trash`」は作らず `#/pending-deletes` の中**（申し送り 6）。`frontend-design.md` §3 の画面一覧には元から無いので妥当。§5 の表を直す。
- **E-5 §4.6 の入口 (c) トレイは無い**（申し送り 1。常駐の実装が無い）。妥当。
- **E-6 走査中の表示（再確認 D-3）は無い**（申し送り 3）。`scan` が job を持たないので妥当。
- **E-7 §5「削除は色で警告しない」**: `.pd-warn`・`.dup-cmsg`・残り時間は `--warn`（琥珀）、失敗の文は `--drop`（赤）。多用ではない。妥当。
- **E-8 `frontend-design.md` §4.6 L431-434 を §0.6-3 に合わせて直した**（起動時に消さない）。妥当。

## F. テストで守れないもの

- **壊し試験**（`mutate_p83.py`。plugin でソースは触らない）: Y1（D-1 の元の形）→ `test_a_failure_after_the_move_keeps_the_original_error` が落ちる。Y2（D-2 で中身を見ない）→ 2 件落ちる。Y3（窓切れの道だけ）→ 1 件落ちる。**3 / 3**。実装者の 4 通りと一致。
- `gui_smoke` の 76 件は**作り物の応答**で押す（本物の委譲の聞き手）。本物の HTTP で押すのは `gui_layout` の 2 画面（POST は飲む）と私の `click_flow`（POST も本物）。**段 1 の行が画面に出ない**（C-2）ことを見る試験は無い。
- `gui_layout --screen pending` は**段のラジオを押さない**（既定の段 1 だけ）。段 2・3 の確認（`これも消す`・illust-authoring の 1 行）は `gui_smoke` の作り物だけ。
- D-1〜D-5 の文言は試験で固定されていない（`gui_smoke` は `dup-exact` の 1 行だけ括弧を見る）。

## G. 依頼者への質問（推奨つき。待たずに推奨で進めてよい）

- **G-1 削除の入口**（C-1）。推奨: ライブラリの下部バーに「選んだ N 枚を削除へ回す」（`#/pending-deletes?ids=` へ渡すだけ。重複の画面と同じ部品）と、`#/asset/<id>` の画像のすぐ下に「この 1 枚を削除へ回す」。段の選択と確認は今のまま `#/pending-deletes` に集める。P8-5 で可。
- **G-2 段 1・2 の行を「最近の削除」に出す**（C-2）。推奨: `GET /api/deletions?limit=50` を読み、`state` が `hidden` / `trashed` の行を段 3 の下に「戻す」つきで出す（残り時間は段 3 だけ）。
- **G-3 `stuck` の理由**（D-3）。推奨: API の `_log_doc` に `stuck_reason` を足し、文を 3 つに分ける。
- **G-4 固定の文言**（D-2）。推奨: 「263 枚で 2.6 秒」を消すか `hashed` の数から組む。illust-authoring は `root.display_path` と `allow_stage3` から組む（印の無い置き場だけ出す）。
- **G-5 括弧の規則**（D-1）。推奨: `frontend-design.md` §6 の末尾に「括弧は語釈の行に使わない。説明文の補足には使ってよい」と 1 行書き、L692 の「括弧書きを使わない」を消す。
- **G-6 `gui_layout` の前提**（D-6）。推奨: 前提が無いときは NG にせず「前提が無い（除外 0 / 保留 0）」と注意して終える。

## H. 確かめられなかったこと・注記・後始末

- 凍結の失効（10 分）とゴミ箱の掃除の画面は本物では見ていない（`gui_smoke` の作り物だけ）。
- **`click_flow.out.txt` の `[NG]` 3 行は私の脚本の条件の組み方**: S4・S5 は先に中断した試行が残した台帳 2 行（段 1 を戻した物）を `count === 0` と決め打ちしたため（段 1 の実行そのものは 263 → 261 で通っている）。S10 は除外の POST の応答を読む条件が合わなかったが、**同じ除外を `gui_layout --screen duplicates` が理由は文字のまま・`script` 0 で確認**した（API にも `<script>alert(1)</script>` が理由として在る）。
- 「esc」は**エスケープ**（`<script>` が文字のまま）として見た。**キーボードの Escape** は 2 画面に `keydown` の聞き手が無い（`grep` で 0）ので試験していない。
- トレイ・走査中の表示は実装が無いので見ていない。
- **複製の罠**: 複製の DB は複製していない 250 枚の登録が**実ファイル**を指したままで、`#/duplicates` の「削除へ回す」は**既定で全群が選ばれる**（写真で 48 枚）。私は複製で実ファイルの登録を参照切れにしてから押した（`prep_srv.py`）。最初の試行では私の脚本のチェック外しが再描画で 1 枚しか効かず、段 1（印だけ。ファイルは動かない）が 56 枚に掛かった（複製の DB だけ。実データと実ファイルは無傷＝署名一致）。
- `sandbox` では `UPDATE … WHERE … NOT LIKE` の一時 b-tree が `%TEMP%` に作れず `unable to open database file` になる（`PRAGMA temp_store = MEMORY` で回避。前からの罠）。
- 実行したコマンド（`$env:UV_CACHE_DIR = "C:\work\image-reviwer\.uv-cache"`、`cd C:\work\image-reviwer`）:
  - `uv run --no-sync pytest -q -p no:cacheprovider` ×3・`node tools/gui_smoke.mjs`
  - `P8X=Y1|Y2|Y3 uv run --no-sync pytest -q -p mutate_p83 tests/test_deletions.py`（`PYTHONPATH` に plugin）
  - `uv run --no-sync python -X utf8 .tmp-audit-redo\p8-3-audit\replica3.py` → `prep_srv.py`（実ファイルの登録を参照切れ・未計算 2 枚）→ `IMAGE_REVIEWER_DATA=<srv> uv run --no-sync image-reviewer serve --port 8791`
  - `node .tmp-audit-redo\p8-3-audit\click_flow.mjs flow`（本物の Chrome で押す。POST も本物）→ `make_pending.py` → `snap.py` → `click_flow.mjs idle`（12 秒）→ `snap.py`
  - `node tools/gui_layout.mjs --base http://127.0.0.1:8791 --count 8 | --screen requests | group | asset | tags | jobs | duplicates | pending | pending --ids a,b`
- 一時物: `.tmp-audit-redo/p8-3-audit/`（複製 `srv/`・`srv-lib/`・スクリプト `replica3.py prep_srv.py click_flow.mjs debug_stage.mjs make_pending.py snap.py mutate_p83.py srv_run3.sh srv_run3b.sh`・出力）。消して構わない。

## 最も重大な 3 件（再掲）

1. **C-1** 削除の入口が重複の画面にしか無い（設計 §5 の `#/asset/<id>`・§11 の下部バーが無い）。
2. **C-2** 段 1 で外した行は「最近の削除」に出ず、画面からは戻せない。
3. **C-3** 409 `target_exists` の直後に「別名で戻す」のボタンが出ない（再読込まで）。失敗の道でも `load()` する。
