# P8-3 の直しの再確認（重複と削除の画面。C-1〜C-3・既定 0 枚・G-3〜G-6・D-6）— 実行込み

- 日付: 2026-10-18（JST 08:40〜09:40）
- 元の監査: `docs/p8-3-audit-report.md`（合格（条件つき）。C-1〜C-3）。仕分け: `docs/p8-3-audit-triage.md`（14 ファイル +942/-86 と新規 2・`gui_smoke` 232・`gui_layout` 9 画面・本物の Chrome で 16 検査）。
- 対象（コミット `755316f`。`apps/gui/pending.js`（550 行）・`duplicates.js`・`app.js`・`group.js`・`index.html`・`styles.css`、`src/image_reviewer/deletions.py`（`pending()` が段 1〜3・`stuck_reason`・`STUCK_REASONS`）、`db.py`（`deletion_log.stuck_reason`）、`api/deletions.py`、`tests/test_deletions.py`（+4 件）、`tools/gui_smoke.mjs`（232 件）、`tools/gui_layout.mjs`（`--screen library` 新設・`delTop` / `delVisible`・既定 0 枚）、`tools/gui_layout_seed.py`（新規）、`docs/frontend-design.md`・`docs/p8-design.md` §0.19）。
- 環境: `uv run --no-sync`。実データ `.data` は `mode=ro` と `backup()` の複製だけ。**画像は 1 枚も動かしていない**（複製 `gui-lib/` 13 枚＝距離 ≤6 の先頭 5 群を `copy2`。段 2・3 はその 13 枚にだけ掛け、実ファイルを指す 250 行の登録は複製側で参照切れにしてから押した。前回の罠の手当て）。複製のサーバは **8793**（`IMAGE_REVIEWER_DATA`・`IMAGE_REVIEWER_BACKUP_DIR` つき。止める前に `data_dir` を確かめた）。**8790 は止めていない**（PID 54920・08:38 起動＝直したコード）。ComfyUI は触っていない。コミットしていない。
- 実データ: 最初と最後に `mode=ro` で **263 枚・判断 3 件・`deleted_at` 0・台帳 0**、画像 263 枚の署名 **`fa99ca126c393d5a`**（前回と同じ）。
- 回帰: **pytest 472 passed ×3**、**gui_smoke すべて ok（232 ok / NG 0）**、**gui_layout 10 本すべて ok（`--count 8`・requests・group・asset・tags・jobs・duplicates・pending・`pending --ids`・library。各 3 窓）**。

## 判定: **合格（条件なし）**

本物の Chrome（headless。POST も本物。`.tmp-audit-redo/p8-recheck/recheck_click.mjs`）で押した結果（`click5.out.txt`。T1〜T7 ok）:

- **C-1 入口 3 つ**: ライブラリで Ctrl＋クリック 2 枚 → 下部バーが「選んだ 0 枚」→「選んだ 2 枚を削除へ回す」（top 643 / 670 でスクロール無し）→ 押すと `#/pending-deletes?ids=` に 2 枚（T1）。拡大 `#/asset/<id>` の「この 1 枚を削除へ回す」は画像の下（top 628 / 670・`scrollY 0`）で、押すと `ids=` その 1 枚（T2）。まとまり `#/group/audit-group` の「選んだ 1 枚を削除へ回す」が押せて `ids=` 1 枚（T3）。行き先は `pending.js` の `deleteHref()` 1 か所（T7: `deleteHref(['a','b']) === '#/pending-deletes?ids=a,b'`）。`gui_layout --screen asset` は `delTop` / `delVisible`＋押す検査、`--screen library` は下部バーの押す検査で 3 窓とも ok。
- **C-2 段 1 の行**: 段 1（既定の段）を画面で実行 → 「最近の削除」に `pd-hidden` の行が出て、ボタンは「戻す」・残り時間は `—`・API も `stage 1 / state hidden / undoable true`（T5a。`deleted_at` が立つ）→ 「戻す」で行が消え、`deleted_at` が外れて一覧に戻る（T5b）。段 3 の行（`pd-pending`「取り消す」「あと 3:58」）が先に並ぶ（§11 の並び）。
- **C-3 409 の直後**: 段 3 → 元の場所を別のファイルで埋める → 「取り消す」→ **再読込せずに**（`window.__marker` が残る）行が `pd-stuck` になり「別名で戻す」が出て、文は「戻せませんでした。元の場所に既にファイルがあります。「別名で戻す」か「いま消す」を選べます。」、API の `stuck_reason` は `target_exists`（T6a）→ 「別名で戻す」で `<名前>.1.png` に戻り、置いたファイルは無傷（1,274,153 B のまま。T6b）。
- **既定で 1 枚も選ばない**: `#/duplicates` を開いた直後は 55 枚中 0 枚・「削除へ回す」は disabled・「全部選ぶ」で 55・「全部外す」で 0（T4）。`gui_layout --screen duplicates` も「既定 0 枚＋全部選ぶがある」を見て ok。
- **G-3 `stuck_reason` 4 通り**: `pending.js` の `STUCK_TEXT` は `target_exists` / `move_failed` / `different` / `missing` の 4 語で、`null` は `missing` と同じ文言（T7）。API は `deletion_log.stuck_reason` を返す（T6a）。`deletions.py` の `stuck_reason_of()` が語彙を守り、`db.py` の `TOP_UP_COLUMNS` で古い v6 にも列が足される（P8-4 の再確認 R4 で ALTER を実測）。
- **G-4 固定文言**: `duplicates.js` は「絵を読んで指紋を作ります。画面は止まりません。」（「263 枚で 2.6 秒」は無い。T4 の `text263 false`）。段 3 の前置きは `GET /api/roots` の印の無い置き場から組む（`stage3NoticeHtml`）。印のある置き場（複製の `gui-lib`）では出ない（T8 の `warns` は「最後の 1 つ」だけ）。`pending.js` / `duplicates.js` に `illust-authoring` の文字列は無い（`grep`）。
- **G-5 括弧の規則**: `frontend-design.md` §6 末尾（L770-772）に 1 か所「括弧書きを使わないのは語釈の行だけ。説明文の補足には括弧を使ってよい」。L692 の「括弧書きを使わない」は消え、`gui_smoke` の括弧の検査は語釈の行（§8.2-1）だけ。
- **D-6 `gui_layout_seed.py`**: `--data .data`・`--data .data/`・`--data C:/work/image-reviwer/.DATA` の 3 通りとも「断ります: … は実データ（…）の中です」で終了 2、実データの署名は変わらない。複製には `--pending` で段 3 の保留 1 件（実体は複製の `pending-delete/` に写し）を作れた。前提が無いときの `gui_layout` は NG にしない（`gui_layout.mjs` L829-839）。
- **D-2 / D-4 / D-5 / D-9**: 文言表（`frontend-design.md` §6 L705「重複の候補: 距離 3 の 2 枚」・L715「最後の 1 つが 3 枚あります。」・L727「窓の無い戻しは『戻す』」）と実装（`duplicates.js:312`・`pending.js:308`）が合う。
- **D-7**: 8790 は直したコードで立て直されている（`/api/health` の `started_at 2026-10-17T23:38:25Z`、`/api/backup` が 200）。
- **F**: `tests/test_deletions.py` の 4 件（段 1〜3 の一覧・並び・理由 4 通り・列のトップアップ）が在り、pytest は 472。

## A. 直っていない

- 無し。

## B. 重大

- 無し。

## C. 中程度

- 無し。

## D. 軽微

- **D-1 「別名で戻す」の文に「いま消す」が並ぶ。** T6a の文「「別名で戻す」か「いま消す」を選べます。」は、元の場所が埋まっているだけの行に「いま消す」を同じ重さで並べる。`frontend-design.md` §6 L704 の形どおりだが、`target_exists` では「別名で戻す」を先に、「いま消す」は二の次に見せる方が安全側（文言表の問題。実装の誤りではない）。
- **D-2 段 2 の行は「取り消せる削除」の一覧には出ず「ゴミ箱」の欄だけ**（実装者の決めたこと 1）。§4.6 L431 に書いてあり妥当。画面全体で 1 行 = 1 回は保たれている。
- **D-3 `gui_layout --screen requests` は「open な要求が 0 件」の注意つきで ok。** 前提は `gui_layout_seed.py` に無い（要求は P6 の範囲）。足すなら `--request`。

## E. 設計とのずれ

- 無し。§0.19・§5・§4.1 と `frontend-design.md` §4.6・§6・§11 が実装と合う。

## F. テストで守れないもの

- 本物の Chrome で押したのは私の `recheck_click.mjs`（7 検査）と `gui_layout`（10 本）。`gui_smoke` 232 件は作り物の応答。`move_failed` / `different` / `missing` の 3 通りの文言は `STUCK_TEXT` の表で見ただけで、本物のサーバでその状態を作って見てはいない（`target_exists` だけ本物）。
- 凍結の失効（10 分）の画面は前回と同じく本物では見ていない。

## G. 依頼者への質問（推奨つき）

- **G-1 D-1 の文言**。推奨: `target_exists` の行は「元の場所に既にファイルがあります。「別名で戻す」で戻せます。」とし、「いま消す」はボタンだけにする（文言表 §6 L704 を直す）。

## H. 確かめられなかったこと・注記・後始末

- **T8 の `[NG]` は私の検査の条件**: `document.body.textContent` 全体に `illust-authoring` が含まれるかを見たが、それは複製 DB の `root`（`c:\work\illust-authoring\…` が実データの置き場として登録されている）に由来する**データの文字**で、固定文言ではない。同じ画面で文字ノードだけを辿り直した `t8_probe.mjs` は 0 件（表示されている要素には無い）。`pending.js` / `duplicates.js` に文字列として無いことは `grep` で確認。
- `gui_layout --screen tags` は複製に語 5 を私の `replica_gui4.py` で入れた物で通した（`gui_layout_seed.py --tags` は使っていない。`--pending` だけ使った）。
- 実行したコマンド（`$env:UV_CACHE_DIR = "C:\work\image-reviwer\.uv-cache"`、`cd C:\work\image-reviwer`）:
  - `uv run --no-sync pytest -q -p no:cacheprovider` ×3・`node tools/gui_smoke.mjs`
  - `uv run --no-sync python -X utf8 tools/gui_layout_seed.py --data .data --tags --exclusion --pending`（断られる。exit 2）
  - `bash .tmp-audit-redo/p8-recheck/gui_run5.sh`（`replica_gui4.py` → `gui_layout_seed.py --data <複製> --pending` → 8793 → `gui_layout` 10 本 → `recheck_click.mjs`）
  - `node .tmp-audit-redo/p8-recheck/t8_probe.mjs http://127.0.0.1:8793 <id>`
- 一時物: `.tmp-audit-redo/p8-recheck/`（`recheck_click.mjs`・`t8_probe.mjs`・`gui_run5.sh`・`click5.out.txt`・`layout5.out.txt`・`seed5.out.txt`・`replica_gui5.out.txt`）と `.tmp-audit-redo/p8-4-audit/gui`・`gui-lib`（複製）。消して構わない。
