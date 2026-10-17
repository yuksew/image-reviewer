# P8-2 監査の再確認（削除と取り消し。指摘 B-1〜B-3・C-1〜C-6・D・F・G の直し）— 実行込み

- 日付: 2026-10-18（JST 03:40〜04:10）
- 前回: `docs/p8-2-audit-report.md`（判定 合格（条件つき）。B 3 / C 6 / D 17 / E 11 / F 8 穴 / G 7）。仕分け: `docs/p8-2-audit-triage.md`（93 行）。設計: `docs/p8-design.md` 997 行（§0.18 新設。855 → 997）。
- 対象（コミット `99c5b2e`、03:30:01 JST。9 ファイル +1880/-173）: `src/image_reviewer/deletions.py`（1120 → 1557 行）、`src/image_reviewer/api/deletions.py`（+3。`preview_of` に actor）、`src/image_reviewer/app.py`（+4。`do_scan` が `scan_guard`）、`src/image_reviewer/cli.py`（+8。`scan` も同じ錠）、
  `tests/test_deletions.py`（42 → 75 件。+33）、`README.md`（+1）、`docs/`（triage・design・前回の報告）。`tools/probe_p8.py` は変更なし。監査中の `git status` は本報告だけが untracked。
- 環境: `uv run --no-sync`。実データ `.data` は `mode=ro` と `backup()` の複製だけ。**画像は 1 枚も動かしていない**。複製は `.tmp-audit-redo/p8-2-recheck/`（`chk/`・`chk-lib/`・スクリプト 4 本・出力）と `.tmp-audit-redo/p8-2-audit/srv/`（本物のサーバ用。作り直した）。
  サーバは複製で **8791**（`IMAGE_REVIEWER_DATA` を付けて起動し、終了後に待ち受け 0 本）。**8790 は止めていない**（利用者が 03:30 に修正後のコードで起動し直した物。PID 19392・`started_at 2026-10-17T18:30:13Z`。送ったのは `GET /api/health` だけ）。ComfyUI は触っていない。
- 実データ: 監査の最初と最後に `mode=ro` で読み直して **v6・23 表・263 枚・判断 3 件・`deleted_at` 0・`missing_at` 0・台帳 0・要求 0・凍結 0**、画像 263 枚の署名 **`fa99ca126c393d5a`・合計 292,561,491 B**（前回と同じ）。`db.sqlite3` 1,544,192 B・00:07、`-wal` 4,190,072 B・02:01 のまま（03:30 の再起動では `-shm` だけ触れている）。`.backup/` は 7 つのまま（今回の再起動の控えは無い）。コミットしていない。
- 回帰: **pytest 400 passed × 3 回**（19.26 / 19.21 / 19.10 s）、**gui_smoke 129 ok / NG 0**、**gui_layout 6 画面すべて ok（各 3 窓）**（複製 8791）。`probe_p8.py --delete` は複製で **18 項目すべて OK**（ゴミ箱が `trash\20261018\…`＝JST）。

## 判定: **合格**（条件なし。軽微 2 件は P8-3 以降で）

前回の 3 つの条件は**私の再現がどれも起きなくなった**。(B-1) 台帳の行が先に書かれ、移動の後で取引が落ちても行は在って `pending` に出て `undo` で戻る。移動の前に落ちた形の行は窓切れで「戻した」になり、ファイルも登録も触らない。台帳に無い保留の中身は `found` に出て `start()` でも消えない。(B-2) `move_failed` の行は `purge_at` が NULL になり、`state: stuck` で 3 周期回しても残り、本物のサーバで 2 周期またいでも残った。(B-3) `tick` / `_purge_expired` が錠を取り、実削除の直前で止めた間の `undo` は待たされ、実削除が先なら 409 `already_purged`・undo が先なら周期は何もしない（読み直し）。矛盾する状態は作れなかった。
C-1 は利用者の決定どおり（人は誰の削除でも戻せる・エージェントは自分の分だけ）で、HTTP の両方向で確かめた。C-2〜C-6・D-1〜D-17 も 1 つずつ再現して直っている。F の穴 8 つは試験が足され、`start()` を本当に呼ぶ形になっている。実装者の壊し方 36 通りを私も回して **34 通りが落ち、落ちない 2 つは錠が二重のため**（両方外す B-3c は落ちる）で妥当。「`src/` を壊して復旧した」は**本当に元に戻っている**（HEAD と改行以外で同一・壊し方 36 組の「元の文」が全部 1 回ずつ・「壊した文」は 0 回・`MUT:` の印 0）。

残った軽微 2 件（D）: 移動の後で落ちると `_drop_request` が台帳の外部キーに当たって `IntegrityError` が元の例外を隠す（行は正しく残る）。保留が外から消え元の場所に別のファイルが現れた形は「戻した」と記録される（`size` を比べない）。どちらも失敗の道の中の失敗で、データは失われない。

**最も重大な 3 件**（再確認の所見。いずれも軽微）

1. **D-1 移動の後で落ちると、`_drop_request` が外部キーに当たる。** `delete()`（`deletions.py:608-641`）は `BaseException` で `_drop_request(request_id)`（`:1289`）を呼ぶが、B-1 の順序で台帳の行は既に `request_id` を指して commit 済み（`deletion_log.request_id REFERENCES delete_request(id)`・`PRAGMA foreign_keys = ON`）。`DELETE FROM delete_request` が `IntegrityError: FOREIGN KEY constraint failed` になり、**元の例外が隠れて 500 の文面が外部キーになる**。台帳の行は残り（`pending` に出る・`undo` で戻る）、`delete_request` の行は `result_json` 無しで残る（同じ `client_token` の再送があれば 600 秒後に D-8 が巻き取る。token 無しなら残る＝害は無い）。`checks2.py` K3a。直し: `_drop_request` を「台帳が参照していなければ消す」にするか、`except sqlite3.IntegrityError: pass`。
2. **D-2 「戻したことにする」が中身を見ない。** `_recover_missing_hold`（`:449-478`）と `_restore` の `_mark_recovered`（`:1091-1096`・`:1133`）は「保留に無い・元の場所に在る」だけで `restored_at` を立てる。保留のファイルが外から消され、元の場所に**別のファイル**が置かれた形でも「戻した」になり、しかも `missing_at` は立ったまま（元の削除が完了していたので）。`checks2.py` K3c: `restored_at` あり・`missing_at` あり・登録の `size` 565,252 に対して実体は 12 B。直し: 元の場所の `(size, mtime_ns)` を登録の行と比べ、違えば `_mark_unrestorable`（stuck）にする。現実には「保留を手で消した」ときだけ起きる。
3. **D-3 走査の間、タイマーと削除の口が丸ごと待つ。** `scan_guard`（`:272`）は `tick` と同じ `RLock` なので、長い走査（数千枚）の間は `POST /api/locations/delete` と `undo` が応答せず、`tick` も止まる（止まった分は次の周期でまとめて引かれる＝窓の意味は保たれる）。263 枚の走査は 2 秒なので今は困らない。設計 §3.4 L631 に「待たせる」と書いてあるので字義どおりだが、P8-5 の画面は「走査中」を出す必要がある。

---

## A. 直っていない／設計の約束が成り立たない

- 無し。

## B. 重大

- 無し。前回の B-1〜B-3 は下の C-0 のとおり直っている。

## C. 中程度

### C-0 前回の指摘ごとの再現（1 行ずつ。実行したもの）

| 前回 | 直し（仕分け） | 私の再現（`checks2.py` / `server_check2.py` / 試験） | 判定 |
| --- | --- | --- | --- |
| **B-1** 迷子 | 台帳を先に書く・動かせなければ行を消す・移動前に落ちた行は戻したことにする・拾い物 | K3a: 移動の後の取引で落としても台帳の行あり・`pending` 1 件・`undo` 200 で元に戻る。K3b: 行だけ残した形は 2 周期で `restored_at` が立ちファイルも登録もそのまま／`undo` は 200 `recovered`／`purge_now` は 409 `not_in_hold`。拾い物: `pending()['found_count'] 1`・`start()` でも消えない。本物のサーバ: 起動時に拾い物 1 件が `found` に出て 66 秒後も在る。試験 `test_the_ledger_row_is_written_before_the_file_moves` ほか 4 本 | **直った**（D-1・D-2 の軽微あり） |
| **B-2** `move_failed` で黙って消える | `("target_exists", "move_failed")` で `_mark_unrestorable` | K15: 409 `move_failed`・`purge_at` NULL・`state: stuck`・3 周期後も実体あり・フォルダを戻して `undo` 200。本物のサーバ: 2 周期（66 秒）またいでも残り、人の `purge` で 200 | **直った** |
| **B-3** 競合で登録が消える | `tick` と `_purge_expired` が `self._lock`・消す直前の読み直し・`rowcount` | K2: `_remove_hold` を Event で止めた間の `undo` は 1 秒待っても戻らず、解くと 409 `already_purged`・ファイル無し・登録 0・台帳『削除済み』（矛盾なし）。K2b: 先に `undo` した行は次の周期で `purged 0`・登録 1。試験 `test_the_timer_and_undo_never_lose_the_registration` はどちらの順でも矛盾を断る形 | **直った** |
| **C-1** 人が戻せない | `check_owner = actor != "human"`・`undoable` は人なら真 | K12 と本物のサーバ: エージェントの段 3 を人が `undo` 200（`undoable true`・`mine false`）、人の段 3 をエージェントが `undo` 403 `not_yours`、自分の分は 200、人の `purge` 200 | **直った**（利用者の決定どおり） |
| **C-2** 読み取り専用 | `_make_writable`・`purge_now` の `OSError` は 409 | K7: `S_IREAD` でも 2 周期目で消える。`_remove_hold` を `PermissionError` にすると `purge_now` 409 `purge_failed`・行は pending のまま | **直った** |
| **C-3** `deleted_at` の単位 | `_should_hide`（生きている場所 0 か生きた段 1） | K5: 2 か所の片方を段 3 → `deleted_at` NULL・実削除後も NULL。最後の場所を段 2 → 立つ・戻す → 外れる | **直った** |
| **C-4** 段 1・2 の一括の `last_copy` | `stage == 3 and last_copies` | 段 1 の一括は確認なしで 200（エージェントでも）・段 3 は 409 `last_copy` | **直った** |
| **C-5** 凍結の値 | `_require_file(frozen=…)` | K16: 凍結後に `mtime` が変わり DB も追随した枚は `skipped: changed`・ファイルは残る | **直った** |
| **C-6** `scan_running` | `scan_guard()` を `do_scan`・`cli scan` に | `scan_guard` を握った間の `delete` は 1 秒待っても返らず、解くと 200（`app.py:344`・`cli.py:64`） | **直った**（D-3 の注記） |
| **D-1** `_remove_hold` の暴発 | 深さ 1・2 だけ | K8: 保留領域そのもの・深さ 3・外は `OSError`、他の保留は無傷 | 直った |
| **D-2** preview の `not_allowed` | `not_allowed` / `not_allowed_count` | K17: 印なし 1 枚を含む 2 枚の段 3 の preview で `not_allowed_count 1` | 直った |
| **D-3** ゴミ箱の UTC | `jst_day()` | K11: 17:30Z → `trash\20261018\…`。probe も `20261018` | 直った |
| **D-4** `display_path` | `LEFT JOIN asset_location` | K10: 台帳の `display_path` が登録の表記（大文字） | 直った |
| **D-5** previews の actor | `_actor_of` | 本物のサーバ: `robot` で 422 | 直った |
| **D-6** `stage: true` | 真偽値と非整数の小数を 422 | K6: `True`・`3.9`・`"x"`・`4` が 422、`"3"`・`2.0` は通る。本物のサーバ: `true` → 422 `bad_stage` | 直った |
| **D-7** 空フォルダ | 判定を先に・`_prune_empty` | K13: `cross_volume` 409 の後に新しいフォルダ無し | 直った |
| **D-8** 永久 `in_progress` | `STALE_REQUEST_SEC` 600 | K14: 700 秒前の落ちた要求は巻き取って 200、新しい物は 409 | 直った |
| **D-9** `frees.at` | 実行前は `null` | K9・本物のサーバ: `null` | 直った |
| **D-10** `PREVIEW_KEEP_SEC` | `_sweep_previews` | 失効 10 分は 409 `preview_expired` のまま、1 日後の周期で `previews_cleaned 5`・404 | 直った |
| **D-11** 切り捨て | 端数を繰り越す | 30.9 → 30 引き、次の 30.1 で 31 引く（270 → 239） | 直った |
| **D-12** 段 1 を 2 回 | 2 回目は `replayed` | K21: 同じ `deletion_id`・1 回の `undo` で出る | 直った |
| **D-13** 空の `path` | 422 `bad_path` | K22・本物のサーバ | 直った |
| **D-14** `folder` 無制限 | 登録した root の下だけ | K23: `C:\` は 422 `bad_scope`、置き場の下は通る | 直った |
| **D-15** 線の番号 | 文書に 1 行 | §0.18 冒頭「指示書の線 4〜7 ＝ 設計 §1.2 の線 5〜8」 | 直った |
| **D-16** `os.replace` の字 | 設計を `os.rename` に | §0.6-1 L109・§0.13 の表 | 直った |
| **D-17** fixture の周期 | `start()` のまま周期 1 時間・窓ありの GET 試験 | `tests/test_deletions.py:137-144`・`test_the_http_gets_never_write_with_a_live_window` | 直った |
| **E-1〜E-11** | E-5 以外は本文を直した | §0.6（規則 7〜9 追加）・§0.13・§0.14 (e-2)・§3.2〜§3.4・§4.1・§4.3・§8.1（37〜44・60〜67） | 妥当（E-5 は P8-4） |
| **F** 穴 8 つ | 試験 8 本 | `test_a_stuck_row_is_never_purged_automatically` ほか 7 本。**`start()` は本当に呼ぶ**（`test_start_does_not_delete_and_the_first_tick_after_it_waits`（`:1542`。L1552-1553 で `interval=3600` の `start()` を呼び、`stop()` で片づける）） | 埋まった |
| **G-1〜G-7** | すべて推奨どおり | 上の各行。G-3 の README の 1 行は入っている（`README.md:200`） | 妥当 |

### C-0b そのほか確かめたこと

- **`src/` の原状**（指示の 9）: `git diff HEAD -- src tests tools` は空。`deletions.py`・`api/deletions.py`・`app.py`・`db.py` は HEAD と**改行（CRLF）以外で同一**（`tr -d '\r'` して sha256 一致）。実装者の `mutants.py` の 36 通り（置き換え 38 組）について、HEAD の実物に「元の文」が**全部ちょうど 1 回**・「壊した文」が **0 回**・`MUT:` の印 0。壊れたまま残っていた控え `.tmp-audit-redo/p8-2-fix/mutated-backup/deletions.py` は HEAD と 1,633 行違い `MUT:` が 2 つ（＝復旧前の形）。`mutants.py` の `build()` はいま**写し（`mutsrc/`）を読んで写しに書く**形で、毎回実物の sha256 を確かめている。
- **壊し方 36 通りを私も回した**（`.venv\Scripts\python.exe .tmp-audit-redo\p8-2-fix\mutants.py`）: **34 / 36 が落ちる**。落ちない 2 つは実装者と同じ（B-3 `tick` の錠だけ外す・B-3b `_purge_expired` の錠だけ外す）。判定は 36 通りとも実装者の記録と一致。実行の前後で `src/` の sha256 は不変（`a6f3ca54bd852596`）。
- **GET は 1 バイトも書かない**: サービス直呼びで 4 本（`found` の走査を含む）、本物のサーバで 7 本（窓のある段 3・拾い物あり）の前後で**全表の中身の sha256 と全ファイル**が同じ。
- **本物のサーバの 30 秒周期**: 複製に `stale-at-boot3`（`remaining_sec 0`・`purge_at` 過去）と拾い物 `orphan-dir/lost-pickup.png` を置いて起動（`health` まで 0.5 秒）→ **起動 +0.0 秒で `found_count 1`・期限切れの保留あり・起動ログに「保留領域に台帳の無いファイルが 1 件あります（拾い物。消しません）」** → +36 秒（1 周期目の後）で両方在る → +66 秒で期限切れの保留は消え `hold_path = '(削除済み)'`、拾い物は在る。起動直後の段 3（窓 40 秒）は +66 秒で実削除済み。B-2 の `move_failed` の行は `purge_at NULL`・`remaining_sec 40` のまま 100 秒後も残り、人の `purge` で 200。`server_check2.py`
- **決定 7 の上限**（X2 の試験）: `test_the_window_is_charged_by_the_shorter_elapsed_time` が守る（私の X2 相当は実装者の F-2 で落ちる）。

## D. 軽微

- **D-1 移動の後で落ちると `_drop_request` が外部キーに当たり、元の例外が隠れる**（上の 1）。`deletions.py:628-633`（`except BaseException: self._drop_request`）・`:1289-1293`・`db.py:539`。再現 `checks2.py` K3a（`_sync_hidden` を例外にする＝2 つ目の取引が落ちる形）: 上がる例外は `IntegrityError: FOREIGN KEY constraint failed`、`result_json` 無しの要求の行 1。一括では `_drop_request` を呼ばないので `skipped: failed` に**元の例外**（`RuntimeError`）が入り、台帳の行も残る（実行して確認: 2 件中 2 件目を落として `deleted 1 / skipped failed`・台帳 2 行・ファイルはゴミ箱）。
- **D-2 「戻したことにする」が中身を見ない**（上の 2）。`deletions.py:440-478`・`:1091-1096`。K3c。
- **D-3 走査の間はタイマーと削除の口が待つ**（上の 3）。`deletions.py:272-283`・`app.py:344`。CLI の `scan` の錠は別プロセスなので効かない（実装者が注記。SQLite の取引が守る）。
- **D-4 `found_in_hold` は `GET /api/pending-deletes` のたびに保留領域を `rglob` する**（`:355-383`・`:537`）。保留が多いと GET が I/O を持つ。上限 200 件まで中身を返し、数は全部数える。害は無い。
- **D-5 再起動の控えが無い**: 02:01 の再起動は `.backup/pre-p8-2-restart-20261018-015658` があるが、03:30 の再起動（修正後のコード）には無い。`_top_up_v6` は今回は列を足していない（`PRAGMA table_info` で前回と同じ 12 列・8 列）ので実害は無い。
- **D-6 `docs/p8-2-implementation.md` は更新されていない**（決定 5・6 の記述が古いまま。仕分けと §0.18 が正）。P8 の完了時に揃える。

## E. 設計とのずれ

- **E-1** §0.6 の規則が 6 → 9 に増え、§0.13 に「実削除は錠の下」「迷子を作らない」、§0.14 に (e-2)、§3.4 に `move_failed` / `purge_failed` / `not_in_hold` / `bad_path`、§4.1 に「移動の前に落ちた」行、§4.3 に掃除の規則、§8.1 に 37〜44 と 59〜67 が入った。実装と一致する。
- **E-2** §3.4 L631「走査中は 409 を返さず待たせる」: 実装どおり（D-3 の注記）。
- **E-3** §3.2 `undo` の行（L593）は「人は誰の削除でも」になったが、**エージェントが自分の段 2 を `undo` で戻せる**（前回 E-9）は本文のどこにも書かれていない（`trash/restore` は人だけのまま）。実装は変えていない（本物のサーバで 200）。1 行足す。
- **E-4** 専門文書 `docs/duplicates-deletion-backup.md` §3.4 は `os.replace` のまま（設計は `os.rename` に直した）。元ネタなので直さなくてよいが、読む人が迷う。
- **E-5** `allow-stage3` の口は P8-4 のまま（G-3 の判断。README に 1 行あり）。

## F. テストで守れないもの

- 実装者の 36 通りは私の実行でも同じ結果（34 / 36 が落ちる）。落ちない 2 つ（B-3 の錠を片方だけ外す）は、もう片方の錠が守る形なので妥当（両方外す B-3c は落ちる）。
- 今回の所見 D-1・D-2 には試験が無い（D-1 は「移動の後の取引が落ちる」形、D-2 は「保留が外から消え元の場所が別物」の形）。

## G. 依頼者への質問（推奨つき）

- **G-1 D-1 の直し方**: `_drop_request` を `DELETE … WHERE id = ? AND result_json IS NULL AND NOT EXISTS (SELECT 1 FROM deletion_log WHERE request_id = ?)` にし、消せなければ残す（600 秒後に D-8 が巻き取る）。元の例外をそのまま上げる。
- **G-2 D-2 の直し方**: `_original_exists` で `(size, mtime_ns)` を登録の行と比べる。違えば `_mark_unrestorable`（stuck）にして「保留に無く、元の場所は別のファイルです」と出す。
- **G-3 走査中の表示**: P8-5 で「走査中（削除は待ちます）」を出すか、`do_scan` を背景にする（§3.4 の「待たせる」のまま）。
- **G-4 E-3 の 1 行**: §3.2 の `undo` の行に「段 1〜3 に効く（段 2 はゴミ箱からの復帰と同じ）」を足す。

## H. 確かめられなかったこと・注記・後始末

- 実機の別ボリューム（D:）は前回と同じく `WinError 5`。壁時計を進める試験は `FakeClock`（試験と probe）だけ。
- 本物のサーバでは「移動の後で落ちる」形は作れない（サービス直呼びで `_sync_hidden` を例外にした）。
- 8790 のタイマーは実データに段 3 の行が 0 なので書かない（`-wal` の mtime 02:01 のまま。03:30 の再起動は `-shm` だけ）。
- 実行したコマンド（`$env:UV_CACHE_DIR = "C:\work\image-reviwer\.uv-cache"`、`cd C:\work\image-reviwer`）:
  - `uv run --no-sync pytest -q -p no:cacheprovider` ×3・`node tools/gui_smoke.mjs`
  - `uv run --no-sync python -X utf8 tools/probe_p8.py --delete`
  - `uv run --no-sync python -X utf8 .tmp-audit-redo\p8-2-recheck\checks2.py`（K1〜K23 の当て直し＋ C-4・C-6・D-10・D-11・G-4）
  - `.venv\Scripts\python.exe -X utf8 .tmp-audit-redo\p8-2-fix\mutants.py`（実装者の 36 通り。前後で `src/` の sha256 を確認）
  - `bash .tmp-audit-redo/p8-2-recheck/srv_run2.sh`（複製 `srv/` に期限切れの行と拾い物を置いて 8791 を起動 → `server_check2.py` → `gui_layout` 6 画面 → 停止）
- 一時物: `.tmp-audit-redo/p8-2-recheck/`（`chk/`・`chk-lib/`・`chk-noflag/`・`checks2.py`・`server_check2.py`・`srv_run2.sh`・出力 8 本）と `.tmp-audit-redo/p8-2-audit/srv*`（作り直し）。消して構わない。

## 最も重大な 3 件（再掲。いずれも軽微）

1. **D-1** 移動の後で落ちると `_drop_request` が台帳の外部キーに当たって `IntegrityError` になり、元の例外が隠れる（行は正しく残り、`undo` で戻る）。
2. **D-2** 「戻したことにする」が元の場所の中身を見ないので、保留が外から消え別のファイルが置かれた形でも `restored_at` が立つ（`missing_at` は立ったまま）。
3. **D-3** 走査の間はタイマーと削除・取り消しの口が待つ（設計どおり。P8-5 で「走査中」を出す）。
