# P8-5 監査報告（仕上げの画面と文言。`#/settings`・上部バーの知らせ・段 3 の印・走査中）— 実行込み

- 日付: 2026-10-18（JST 10:10〜11:20）
- 根拠: `docs/p8-design.md` §9 の P8-5 の行・§0.21（8 行）・§5・§3.4、`docs/frontend-design.md` §3・§4.5.1（新設）・§4.6・§6・§10・§11、`docs/p8-4-audit-recheck.md` の B-1'（`last_error` を上部バーに）。実装の記録: `docs/p8-5-implementation.md`（185 行。決めた点 10・申し送り 6・設計の穴 4）。
- 対象（コミット `3f75484`、`1d4616c` から 17 ファイル +2171/-49）: `apps/gui/settings.js`（308 行。新規）、`badge.js`（+93）、`pending.js`（+103）、`app.js`（+27）、`index.html`（+38）、`styles.css`（+81）、`src/image_reviewer/app.py`（`GET /api/scan`）、`deletions.py`（`scan_state()`・`scan_guard()` の印）、`tests/test_scan_state.py`（218 行・5 件）、`tools/gui_smoke.mjs`（291 件）、`tools/gui_layout.mjs`（`--screen settings` 新設・library / pending に P8-5 の検査）、`tools/gui_layout_seed.py`（`--stage3` / `--no-stage3` / `--backup-error` / `--backup-dir`）、`docs/frontend-design.md`・`docs/p8-design.md`。監査の最初の `git status` は本報告だけが untracked。**終わりの時点では実装者の次の作業が作業木に入っていた**（`README.md`・`docs/design.md`・`docs/handoff.md`・`db.py`・`store.py` の変更と `relink.py` / `api/relink.py` の新規）。P8-5 の対象（`apps/gui`・`tools/gui_*`・`app.py`・`deletions.py`）は HEAD のまま。
- 環境: `uv run --no-sync`。実データ `.data` は `mode=ro` と `backup()` の複製だけ。**画像は 1 枚も動かしていない**（複製 `gui-lib/` 13 枚に `copy2`。走査の試験は複製の DB に対して行い、実ファイルは読むだけ）。複製は `.tmp-audit-redo/p8-4-audit/gui`（`replica_gui4.py` で作り直す）、脚本と出力は `.tmp-audit-redo/p8-5-audit/`。バックアップの置き場は `.tmp-audit-redo/p8-5-audit/backups/`（`%USERPROFILE%` の下には作っていない）。
  複製のサーバは **8793 / 8794**（`IMAGE_REVIEWER_DATA` を付け、置き場は複製の `settings` で。止める前に `/api/health` の `data_dir` を確かめた）。**8790 は止めていない**（PID 54920・08:38 起動＝P8-4 までの裏側。送ったのは GET と静的ファイルだけ。書く口は押していない）。8791〜8795 の他の担当のサーバには触っていない。ComfyUI は触っていない。コミットしていない。
- 実データ: 最初と最後に `mode=ro` で **v6・24 表・263 枚・判断 3 件・`deleted_at` 0・台帳 0**、画像 263 枚の署名 **`fa99ca126c393d5a`・292,561,491 B**（前回と同じ）。`.backup/` は最初 8 フォルダ、終わりには 9（監査の間に実装者の次の作業が 1 つ足した。私は触っていない）。`%USERPROFILE%\image-reviewer-backups` は無いまま。終わりの `netstat` は 8790 だけ（8793 / 8794 は止めた）。
- 回帰: **pytest 477 passed ×3**（37.1 / 37.4 / 35.2 s。2 回目と 3 回目は実装者の次の作業（`relink.py`・`db.py`・`store.py`）が作業木に入った後で、数は 477 のまま）、**gui_smoke すべて ok（291 ok / NG 0）**、**gui_layout 11 本**: 10 本 ok、**`--screen asset` は印の無い置き場の枚では 3 窓とも NG**（C-2。印を付けると ok＝`layout7.out.txt`）。

## 判定: **合格（条件つき）**

依頼の 4 点は本物の Chrome（headless。POST も本物）で押して確かめた（`p85_click.mjs`。`run6.out.txt`・`good2.out.txt`）。**(1)** 置き場をファイルにした複製で、上部バーに「バックアップに失敗しています」が出て（top 41 px・幅 157 px）、押すと `#/settings` に行き「最後の失敗（…）: バックアップの置き場がフォルダではありません」がスクロール無しで見える（A1）。**実機 8790 でも同じ**（GET だけ）: 「バックアップに失敗しています」→ 押すと設定で「最後の失敗（2026-10-18 08:38）: [WinError 5] アクセスが拒否されました。: 'C:\Users\yukse\image-reviewer-backups'」の全文、置き場 2 つに **印なし / 印あり**、走査中の印は出ない（裏側が古く `GET /api/scan` が 404 でも画面は壊れない。R1 / R2）。**印の無い置き場**（複製の `gui-lib` の印を外した形）では `#/pending-deletes?ids=` の段が **1・2 だけ**で「この置き場には段 3 の印がありません。段 1・2 だけ選べます。印は設定で付けられます。設定を開く」が出る（B1）。設定で**印を付ける**と `POST /api/roots/{id}/allow-stage3` が **1 回**・`allow: true`・`X-Image-Reviewer-Actor: human`・「この置き場で段 3 を許します。」・印あり、その後は段 **1・2・3** が出て段 3 の凍結に前置きは出ない（B2 / B3）。**印を外す**と 1 回・`allow: false`・「この置き場の印を外しました。」→ 段 3 が消える（B4）。**走査中の 1 行**: `GET /api/scan` の応答だけ差し替えると「最近の削除」に「走査中です。終わるまで削除と取り消しは待ちます。」が見え（top 44 px）、上部バーに「走査中です」が出て、差し替えをやめると 5 秒周期で両方消える（B7 / B7b）。本物の走査（`POST /api/scan`。複製の root 3 つ）の最中に `GET /api/scan` を 60 ms 刻みで叩くと **78 ms 後に `scanning: true`**、応答は最大 2 ms（待たされない）、終われば `false` で `scans` が 1 増える（B8）。**(2)** 「いま取る」は POST 1 回（失敗する置き場では「バックアップの置き場がフォルダではありません」の 1 行、取れる置き場では「いま取りました」で控えが 1 → 2）、「置き場を変える」は PATCH 1 回で API に反映（A2 / A3 / B5 / B6）。**二度押し**（押すたびに要素を引き直す＝人の二度押し）: 「いま取る」1 回・「保存する」1 回。**ただし印のボタンは 2 回**（A4。C-1）。**(3)** 置き場がファイルの形で `last_error` が立った後、ライブラリ 6 秒 → 設定 6 秒 → 最近の削除 6 秒（上部バーの 5 秒周期を 3 周以上含む）で、全表の中身の sha256 `fd3c293b000d14b8`（5049 行）と `<data>`＋置き場の全ファイル（304 件）が前後で同じ（idle）。**(4)** `GET /api/scan` は錠を取らない: 別のスレッドが `DeletionService._lock` を握っていても `scan_state()` は 0.0 ms で返る（L2）。本物の走査の最中の `GET /api/scan` も最大 2 ms（B8）。走査の印は錠を取る**前**に立つので、錠待ちの間も「走査中」になる（L3。D-4）。 **(5)** `gui_smoke` 291 は壊した 12 通りのうち 11 通りで落ちる（F）。`gui_layout`（settings / library / pending --ids の 3 本）は 12 通り中 7 通りを落とし、`gui_smoke` と合わせると **12 通り中 11 通り**が落ちる（落ちないのは「控えを読めません」の文だけ。F）。**(6)** 文言は `frontend-design.md` §4.5.1・§6 の P8-5 の行とおおむね一致するが、設定の 2 か所（「取り直す」/「いま取る」、「今日の分は取れています。」/ API の `next_run_note`）がずれ、読み取り専用の案内の `reason` の語彙が API と合わない（D-1〜D-3）。**(7)** pytest 477 ×3、実データ無傷、削除 0 件のまま。

条件は 2 つ。**C-1 印の付け外しが二度押しで 2 回 POST される**（`setAllow` だけ `busy` を使わない。依頼の (2) の裏返し）。**C-2 `gui_layout --screen asset` が「段が 3 つ」を前提にしていて、印の無い置き場の枚では必ず NG**（P8-5 が自分で入れた「印が無ければ段 3 を出さない」と噛み合っていない。実装者は印を立てた複製で回したので気づいていない）。もう 1 つ中程度: **C-3 版が新しい DB（`read_only` だが `GET /api/backup` は 200）では、設定の「いま取る」「保存する」が押せるまま**（§6「書き込みのボタンは押せなくする」）。

**最も重大な 3 件**

1. **C-1 「段 3 を許す」印のボタンは二度押しで 2 回 POST される。** `apps/gui/settings.js` `setAllow()`（L246-268）は `takeNow()` / `saveDir()` と違って `state.busy = true; render()` をしないので、1 回目の応答が返るまでボタンが生きている。再現（A4。複製 8793・本物の POST）: `.st-allow` を引き直して 2 回 `click()` → `POST /api/roots/…/allow-stage3` が **2 回**（どちらも `allow: true`）。同じ向きなので壊れはしないが、「印は利用者の明示の意思表示」（Q8）の口を 2 回叩く形で、`gui_layout --screen settings` の「印の POST=1」は 1 回押しか見ていない。推奨 G-1: `setAllow` も `busy` で押せなくする（`takeNow` と同じ形）。
2. **C-2 `gui_layout --screen asset` は印の無い置き場の枚で 3 窓とも NG。** `tools/gui_layout.mjs:453`（`PRESS_ASSET_DELETE`）が `document.querySelectorAll('#pd-confirm .pd-stage').length === 3` を「削除の確認が出る」の条件にしている。P8-5 で印の無い置き場は段 1・2 だけになったので、`--ids` に印の無い枚を渡すと必ず「削除の確認が出る」で落ちる（`layout6.out.txt`: 1400×900 / 1200×800 / 1920×1080 とも NG）。印を立てると ok（`layout7.out.txt`）。記録 §2 の 11 本は `--stage3` を立てた複製で回していて、この穴が見えていない。推奨 G-2: `.pd-stage` は 2 以上（か API の印と突き合わせ）にし、「印が無ければ 2 つ」を別の行で確かめる。
3. **C-3 版が新しい DB では設定の書き込みボタンが押せるまま。** `GET /api/backup` が 200 で `read_only: true` を返す形（`version_ahead` / `pre_migrate_backup_failed`）では `settings.js` `backupHtml()` が `readOnlyHtml()` ではなく通常の欄を描き、「読み取り専用で開いています。」の 1 行を足すだけで `.st-now` と `.st-save` が有効のまま（`ro6.out.txt` の ahead: `buttons: ["いま取る", "保存する"]`・`readonlyBox: false`・`reason` の 1 行も `guidance` も無い）。`frontend-design.md` §6「設定: 読み取り専用のとき … **書き込みのボタンは押せなくする**」と違う。503 の形（2 ページ目・先頭 4 KB）では `readOnlyHtml()` が出てボタンは無い（正しい）。推奨 G-3: `got.read_only` でも `readOnlyHtml()` の道へ（`reason` は `GET /api/health/db` から引く）。

---

## A. 直っていない／設計の約束が成り立たない

- 無し。

## B. 重大

- 無し。

## C. 中程度

### C-0 確かめた結果、問題なし（1 行ずつ。実行したもの）

- **上部バーの失敗の印**（A1・R1）: 文言「バックアップに失敗しています」、`title` に理由の頭、押すと `#/settings`、全文が `.st-failed` に見える（top 41 px / 670）。実機 8790 でも同じ。失敗が無いときは隠れる（`gui_smoke` 17）。
- **読み取り専用の印**（`ro6.out.txt`）: ahead / head4k / page2 の 3 形とも上部バーは「読み取り専用です」。503 の 2 形では設定が `readOnlyHtml()`（案内の全文・`restore` の 1 行・ボタン無し・`brief` は「読み取り専用」）。
- **印の無い置き場では段 3 が出ない・印のある置き場では出る**（B1〜B4。本物の POST）。前置き「印が付いていません」は印のある置き場では出ない（B3）。
- **印の付け外し**は 1 回押しで POST 1 回・向きが合う・人と名乗る（B2 / B4）。`gui_layout --screen settings` も同じ（`layout7.out.txt`）。
- **「いま取る」「置き場を変える」**は 1 回だけ POST / PATCH（A2 / A3 / B5 / B6。二度押しも 1 回）。断られた理由（422 の `detail`）が 1 行で出る。
- **走査中**: 画面の 1 行と上部バーの印（差し替えで出る・消える。B7 / B7b）、本物の走査中の `GET /api/scan`（B8）。本物の走査は複製（既に登録済みの 3 root）で **0.16 秒**で終わるので、上部バーの 5 秒周期では拾えない（B10 は空振り。見せ方は B7 で確認）。ライブラリ側で `scan_state()` は錠を取らない（L1〜L4）。走査が終わると `scans` が増え `scanning` が消える。
- **GET は書かない**（idle）: 上部バーの 5 秒周期（`/api/review-requests`・`/api/jobs`・`/api/pending-deletes`・`/api/backup`・`/api/scan`）と `#/settings`（`/api/backup`・`/api/roots`）・`#/pending-deletes`（`/api/assets?limit=2000`・`/api/scan`）を 18 秒開いて、全表の中身の sha256 と全ファイルが同じ。`tests/test_scan_state.py::test_the_scan_state_is_read_only` も中身の sha256 で見る。
- **`GET /api/scan` の口**（B9）: `robot` は 422、ヘッダ無しは 200（`agent` 扱い）、`{scanning, started_at, elapsed_sec, scans, note}`。
- **文言**（`frontend-design.md` §4.5.1 / §6 と突き合わせ）: 上部バーの 3 語・「走査中です。終わるまで削除と取り消しは待ちます。」・「この置き場には段 3 の印がありません。段 1・2 だけ選べます。印は設定で付けられます。」＋「設定を開く」・「印あり / 印なし」・「この置き場で段 3 を許す / 印を外す」・「この置き場で段 3 を許します。/ この置き場の印を外しました。」・「最後の失敗（…）:」・「置き場を作れないときは、書き込める場所に変えてください。」・「まだ取っていません。」・「最後に取ったのは … です。」・`target_exists` の「「別名で戻す」で戻せます。」（G12 で `gui_smoke` が守る）は一致。ずれは D-1〜D-3。
- **括弧の規則**: §6 末尾の 1 か所のまま。新しい文言の括弧（「最後の失敗（…）:」「（直近 7 個を残します）」「段 3（実ファイルの削除）」）は説明の補足で規則の範囲内。
- **トレイ**: `frontend-design.md` §3・§4.5・§4.6・§11 と `p8-design.md` §5 から入口としては消え、残る記述は「作らない」「常駐を作る段で戻す」の説明だけ（`grep` 7 か所）。§11 L940「通知の音」の行に「トレイのアイコンで示す」が残る（D-7）。
- **決めた点 10**: 1（口 1 つ）妥当。2（錠を取らない）妥当・実測。3（要る物だけ）妥当。4（`daily` / `manual` だけ）妥当・`gui_smoke` 19。5（選んだ枚のパスから）妥当だが D-5。6（5 秒ごと）妥当。7（`target_exists` の文）妥当・G12。8（`--screen settings`）妥当。9（応答の差し替え）妥当・本物は B8 / B10 で見た。10（期待値は API から）妥当。
- **設計の穴 4**: 1（タイマーを止めてから測る）正しい。2（認可の非対称）正しい・B9。3（一覧にあるのに無い画面）正しい。4（規則が 2 か所）正しい・`gui_layout` が突き合わせる（ただし C-2 の形で片方が古い）。
- **実機 8790**: 画面は P8-5、裏側は P8-4 まで（`GET /api/scan` 404）。`#stat-scan` は隠れたまま、設定の `roots` は出る（`GET /api/roots` は P8-4 の口）。B-1' はいま画面から見える（「バックアップに失敗しています」）。**日次はまだ 0 個**（`count 0`。立て直しは利用者の操作）。

### C-1 印のボタンは二度押しで 2 回 POST（最も重大の 1）

- 場所: `apps/gui/settings.js:246-268`（`setAllow`）、`:269-278`（`onClick`）。`takeNow` / `saveDir` は `state.busy = true; render();` で `.st-now` / `.st-save` を `disabled` にしてから `fetch`。
- 再現: `run6.out.txt` の A4（`allow posts=2`）。
- 推奨: G-1。

### C-2 `gui_layout --screen asset` は印の無い置き場で必ず NG（最も重大の 2）

- 場所: `tools/gui_layout.mjs:451-453`（`confirmShown` の条件 `.pd-stage` が 3）。P8-5 の `pending.js:339-341`（`offered = allowed ? [1,2,3] : [1,2]`）。
- 再現: `layout6.out.txt` L23-27（印なし → 3 窓 NG「削除の確認が出る」）、`layout7.out.txt`（印あり → ok）。
- 判定: 検査の側の穴。**P8-5 の出し分けを足した側が、P8-3 の検査の前提を直していない**。`gui_layout_seed.py --stage3` を立てて回す手順だと見えない。
- 推奨: G-2。

### C-3 版が新しい DB で設定の書き込みボタンが押せるまま（最も重大の 3）

- 場所: `apps/gui/settings.js:100-103`（`if (state.status === 503) return readOnlyHtml();` だけで分岐。`got.read_only` は 1 行の注意に落ちる）・`:71-78`（`readOnlyHtml` の `reason` の表）。
- 再現: `ro6.out.txt` の `ahead`（`apiStatus 200`・`read_only true`・`buttons: ["いま取る","保存する"]`）。押せば 503 `read_only` が返るので壊れはしないが、§6 の約束と違い、`guidance`（新しいアプリで開く / 戻す）も出ない。
- 推奨: G-3。

## D. 軽微

- **D-1 「取り直す」と「いま取る」。** `frontend-design.md` §6 L765 はボタンを `取り直す` と書くが、`settings.js:124` と `index.html`・`gui_smoke`・`gui_layout` は「いま取る」。`KIND_TEXT.manual` も「いま取る」。実装の語で統一して文言表を直す（「いま取る」の方が §3.3 の語と揃う）。
- **D-2 「今日の分」の文。** §6 L765 は「今日の分は取れています。」/「今日の分はまだです。」。実装は API の `next_run_note` をそのまま出すので**括弧が 2 つ並ぶ**。実機 8790 の設定の実物（`run6.out.txt` の R）: 「今日の分はまだです（30 秒ごとに見ています）（次は 2026-10-18 09:53）」。文言表に合わせて画面側で組むか、API の `today_done` から短い文を作る。
- **D-3 読み取り専用の `reason` の語彙が API と合わない。** `settings.js:71-77` の表は `ahead` / `unopenable` / `pre_topup_backup_failed` を持つが、API（`inspect_db`）は `version_ahead` / `unreadable` を返し、`pre_topup_backup_failed` は存在しない（控えが取れなくても開く）。`ro6.out.txt` の head4k は「DB に書き込めない状態です。」（汎用）になり、`guidance` の方が正しい説明をしている。`malformed` だけが当たる。
- **D-4 走査の印は錠を取る前に立つ。** `deletions.py` `scan_guard()` は `_scan_started_*` を立ててから `with self._lock` に入るので、削除の取引が長いときは**走査がまだ始まっていないのに「走査中です」**になる（L3。実測 `scanning=True`・`started? False`）。害は小さい（待たされている理由としては正しい）が、`elapsed_sec` は「待ち時間込み」になる。文言表の「走査中」の定義を「走査の順番待ちを含む」と書くか、錠を取った後に立てる。
- **D-5 段 3 の出し分けのために `GET /api/assets?limit=2000&sort=path` を毎回引く。** `pending.js` `stage3For()`。263 枚では 1 回 ~数十 KB だが、2000 枚を超える置き場では `ids` が見つからず `known: false`（「置き場を確かめられない」）になり、段 3 が出なくなる。`GET /api/assets/{id}` を枚数分、か `ids=` で絞る口に。
- **D-6 `gui_smoke` は「控えを読めません」を見ていない。** `st-snap-bad` の文言を消しても 291 件が緑（G11）。manifest の無い控えが混ざる形（P8-4 の D-6 の `prunable`）を画面で確かめる行を 1 つ。
- **D-7 `frontend-design.md` §11 L940「通知の音」の行に「トレイのアイコンで示す」が残る。** トレイを外した §3・§4.5・§4.6・§11 の他の行と食い違う。
- **D-8 走査の最中の上部バーの印は `gui_layout` では「隠れている」しか見ない**（library の L1425-1426）。出る方は `gui_smoke`（作り物）と、`--screen pending` の差し替えだけ。本物で出るかは私の B10 で見た。
- **D-9 `#/settings` の「保存する」は入力の値をそのまま送る**（`wantedDir` は `trim` だけ）。相対パスなどは API が 422 で返し、文はそのまま出る（A2 の形）。問題ではないが、`placeholder` に「絶対パス」と 1 語。

## E. 設計とのずれ（実装が決めた所を含む）

- **E-1 §6「書き込みのボタンは押せなくする」が `read_only`（200）の形で成り立たない**（C-3）。
- **E-2 §6 の設定の文言 2 か所が実装と違う**（D-1・D-2）。
- **E-3 §9 の P8-5 の行「重複の整理・最近の削除の常設・ゴミ箱・バックアップの状態・設定・トレイ」のうちトレイは作らない**（§0.21-4。妥当。常駐の実装が無い）。§9 の行自身はまだ「トレイ」を含む（§0.21 と §9 の表の 1 行が食い違う）。
- **E-4 §3.4「`scan_running` は作らない」のまま `GET /api/scan` を足した**（§0.21-3）。409 は返さない形は変えていないので妥当。
- **E-5 `frontend-design.md` §4.5.1 の 6 つの順**（要求 → タグ付け中 → 最近の削除 → バックアップ失敗 → 読み取り専用 → 走査中）: `index.html` の上部バーの順と一致（`stat-backup` → `stat-scan` → 設定）。

## F. テストで守れないもの

- **壊し試験（画面）**: `apps/gui` と `tools/gui_smoke.mjs` を `.tmp-audit-redo/p8-5-audit/mut/<G>/` に写して 1 か所ずつ壊し（`mut_gui.py`。12 通り）、`gui_smoke` と、壊した GUI を複製のデータで配る `mut_server.py`（8794）に対する `gui_layout --screen settings / library / pending --ids`（3 本）を回した。
  - `gui_smoke`: **12 通り中 11 通りで落ちる**（`mut6.smoke.txt`）。G1 失敗の印を出さない → 「失敗していることを上部バーに出す」。G2 `allow` の向きを逆に → 「allow: true を送る」。G3 常に段 3 を出す → 「印の無い置き場では段 3 を出さない」。G4 走査中の 1 行を消す → 「最近の削除にも走査中を出す」。G5 失敗の全文を出さない → 「最後の失敗を全文で出す」。G6 「いま取る」を 2 回叩く → 「1 回だけ叩く: 2 回」。G7 走査中の印を出さない → 「走査中を出す」。G8 `stage3Allowed` を常に真 → 5 件。G9 人と名乗らない → 「人だけの口に名乗る」。G10 読み取り専用を出さない → 「読み取り専用は別の語で出す」。G12 `target_exists` の文を戻す → 「target_exists の文を直した」。**G11（「控えを読めません」を消す）だけ緑**（D-6）。
  - `gui_layout`（`mut6.out.txt`。各 3 窓）: G1 → library 3 件 NG（失敗の印）。G2 → settings 3 件 NG（`allow` の向き）。G3・G8 → pending --ids 3 件 NG（段 3 の出し分けを API と突き合わせ）。G4 → pending --ids 3 件 NG（走査中の 1 行。settings にも 1 件出たが中身は取っていない）。G6 → settings 3 件 NG（「いま取る」の POST=2）。G9 → settings 3 件 NG（人と名乗る）。**落ちない 5 つ**: G5（失敗の全文を出さない）は一括の実行では settings ok＝その時のサーバのログに失敗の行が無く `last_error` が空で、`want.failed` が偽になり全文の検査が飛んでいた（原因は切り分けていない）。**`last_error` が在る形で取り直すと 3 件 NG**（「最後の失敗を全文で出す」「失敗がスクロール無しで見える」）＝検査自体は効く。G7（走査中の印を出さない）は `gui_layout` が「隠れている」しか見ないので落ちない（D-8。`gui_smoke` が落とす）。G10（読み取り専用を出さない）は 3 本とも読み取り専用でない形で回るので落ちない（`gui_smoke` が落とす）。G11 はどちらも落とさない（D-6）。G12（`target_exists` の文）は 3 本の画面に出ないので落ちない（`gui_smoke` が落とす）。G8 の library の 1 本は私の環境で `gui_layout` が 4 分応答せず（Chrome 1 本が残ったまま）、止めて次へ進めた（結果は空欄）。
- **二度押し**は `gui_smoke`（G6 で「いま取る」だけ）も `gui_layout`（1 回押し）も印のボタンでは見ていない（C-1）。
- **読み取り専用（200 の形）の設定の見せ方**は `gui_smoke` も `gui_layout`（503 の形＝`readonly`）も見ていない（C-3）。
- **本物の走査中の表示**は `gui_layout` が「応答の差し替え」で見る（記録 §3-9）。本物は `--screen pending` の probe（`GET /api/scan` が真を返すか）だけで、画面に出るかは私の B10 で見た。
- `tests/test_scan_state.py` の 5 件は口と `scan_state()` を守る。D-4（錠を取る前に立つ）を狙う試験は無い。

## G. 依頼者への質問（推奨つき。待たずに推奨で進めてよい）

- **G-1 印のボタンの二度押し**（C-1）。推奨: `setAllow` の先頭で `state.busy = true; render();`（`takeNow` と同じ形）。`gui_smoke` に「2 回押しても 1 回」を 1 行（G6 と同じ型）。
- **G-2 `gui_layout --screen asset`**（C-2）。推奨: `PRESS_ASSET_DELETE` の条件を `.pd-stage` が 2 以上に緩め、「印が無ければ 2・あれば 3」は API（`GET /api/roots` と枚のパス）と突き合わせる（`--screen pending --ids` が既にそうしている）。記録 §2 の手順に「`--no-stage3` でも 11 本を回す」を足す。
- **G-3 読み取り専用（200）の設定**（C-3）。推奨: `backupHtml()` の分岐を `state.status === 503 || got.read_only` にし、`reason` は `GET /api/health/db`（`mode` / `reason` / `guidance`）から引く。`reason` の表は API の語彙（`malformed` / `unreadable` / `unopenable` / `version_ahead` / `pre_migrate_backup_failed`）に揃える（D-3）。
- **G-4 文言表との 2 か所のずれ**（D-1・D-2）。推奨: 文言表を「いま取る」に、「今日の分」は画面で `today_done` から「今日の分は取れています。」/「今日の分はまだです。」を組む（API の `next_run_note` は出さない）。
- **G-5 §9 と §11 L940 のトレイ**（E-3・D-7）。推奨: §9 の P8-5 の行から「トレイ」を外し、L940 の「トレイのアイコンで示す」を「上部バーで示す」に。
- **G-6 走査の印の立て方**（D-4）。推奨: 文言表に「走査中には順番待ちを含む」と 1 行書く（変えない）か、錠を取った後に立てる。

## H. 確かめられなかったこと・注記・後始末

- **走査の本物**: 複製の `root` には実データの置き場 2 つ（`illust-authoring` 262 枚・ComfyUI の出力 181 ファイル 306 MB）と `gui-lib` が入っているので、`POST /api/scan` は実ファイルを**読んで**複製の DB に登録する（実ファイルは変えない。署名で確認）。
- **二度押しの再現は `click()` の 2 連打**（押すたびに要素を引き直す）。本物のマウスの二度押し（`Input.dispatchMouseEvent`）ではないが、2 回目の `click()` が `disabled` の要素では効かないので「人の二度押し」と同じ道。
- **私の脚本の側**: 1 回目の `good` の走査の検査（B7 / B8）は、私が `location.reload()` で `fetch` の差し替えを消してしまい NG と例外になった（`run6.out.txt`）。差し替えを残す形（hash で道を出入り）に直して `good2` で取り直した。また `bad` の二度押しで複製の `backup_dir` を `gui-dbl` に変えてしまい、その後の `gui_layout` 11 本では `last_error` が無い形で回った（library / settings は「注意」で ok）。失敗がある形は `layout7.out.txt` で取り直した（library / settings / asset / pending --ids とも ok）。
- **報告を書き終える直前に `apps/gui/settings.js` が作業木で変わった**（実装者の次の作業）。本報告の引用と行番号は**コミット `3f75484` の物**。
- 実機 8790 では GET と静的ファイルだけ（上部バーと設定の入口を押した。書く口は押していない）。日次が取れていないこと（B-1'）は変わっていない。
- 実行したコマンド（`$env:UV_CACHE_DIR = "C:\work\image-reviwer\.uv-cache"`、`cd C:\work\image-reviwer`）:
  - `uv run --no-sync pytest -q -p no:cacheprovider` ×3・`node tools/gui_smoke.mjs`・`uv run --no-sync python -X utf8 .tmp-audit-redo\p8-4-audit\real_sig.py`（前後）
  - `uv run --no-sync python -X utf8 .tmp-audit-redo\p8-5-audit\checks6.py`（L1〜L4）
  - `bash .tmp-audit-redo/p8-5-audit/run6.sh`（複製 → `prep6.py bad` → 8793 → `p85_click.mjs idle / bad` → `gui_layout_seed.py --pending` → `gui_layout` 11 本 → `prep6.py good` → `p85_click.mjs good` → 8790 に `p85_click.mjs real`）
  - `bash run_layout2.sh`（印あり＋失敗ありで library / settings / asset / pending --ids）・`bash run_ro6.sh`（ahead / head4k / page2 で `#/settings`）・`bash run_good2.sh`（走査の B7〜B10）
  - `.venv\Scripts\python.exe -X utf8 .tmp-audit-redo\p8-5-audit\mut_gui.py` → 各 `node mut/<G>/tools/gui_smoke.mjs`・`bash run_mut6.sh`（`mut_server.py` 8794 → `gui_layout` 3 本 ×12）
- 一時物: `.tmp-audit-redo/p8-5-audit/`（脚本 `prep6.py p85_click.mjs run6.sh run_layout2.sh run_ro6.sh ro_check.mjs run_good2.sh checks6.py mut_gui.py mut_server.py run_mut6.sh`、`mut/`（壊した GUI 12 組）、`backups/`、`not-a-dir`、出力 `run6.out.txt layout6.out.txt layout7.out.txt ro6.out.txt good2.out.txt mut6.smoke.txt mut6.out.txt checks6.out.txt smoke.out.txt pytest*.out.txt real_sig.*.txt`）と `.tmp-audit-redo/p8-4-audit/gui`・`gui-lib`・`srv`（作り直した複製）。消して構わない。

## 最も重大な 3 件（再掲）

1. **C-1** 「段 3 を許す」印のボタンは二度押しで 2 回 POST される（`setAllow` だけ `busy` を使わない）。
2. **C-2** `gui_layout --screen asset` は「段が 3 つ」を前提にしていて、印の無い置き場の枚では必ず NG（P8-5 の出し分けと噛み合っていない）。
3. **C-3** 版が新しい DB（`read_only` で 200）では設定の「いま取る」「保存する」が押せるまま・`reason` の案内も出ない（§6 と違う）。
