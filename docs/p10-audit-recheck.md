# P10 再確認 — 実行込み（監査の指摘 A-1〜A-3・B・C・D の修正）

- 日付: 2026-10-19 15:27〜15:48（JST）
- 指示書: Orca 経由の依頼（dsh / DeepSeek、15:27 受領）。仕分け `docs/p10-audit-triage.md`、記録 `docs/deletions-advance.md` §7、設計 `docs/design.md` §5.8・§6.1・§16.7（8〜18 行目）
- 前の報告: `docs/p10-audit-report.md`（判定「直してから次へ」）。**この報告は再確認だけ**。前の報告は書き換えていない
- 対象（行数・mtime・sha256 は開始と終了で同じ）: `src/image_reviewer/deletions.py`（2390 行、15:10:53）、`scan.py`（+26）、`store.py`（+5）、`api/deletions.py`（253、14:51:55）、`apps/gui/pending.js`（1132、14:50:05）、`tools/gui_smoke.mjs`（2377）、`tools/gui_layout.mjs`（2013、14:52:08）、`tests/test_deletions_advance.py`（965 行、34 件、15:05:28）、`tests/test_deletions.py`（+21）。コミット `884ba4b`（作業ツリーは docs だけ差分）
- 環境: 複製 4 つ（`rcA`〜`rcD`。`mk_replica.py`＝`backup()`＋`copy2`＋パスの貼り替え。全パス列 1,114 値が外を指さないことを確かめた）。複製サーバ **8812（rcA）・8813（rcC）**。`IMAGE_REVIEWER_DATA` と `IMAGE_REVIEWER_BACKUP_DIR` は複製の中。**実装者の 8811 は立っていなかった**（触っていない）
- 触っていないもの: 実データ（`mode=ro` のみ。`db.sqlite3`・`-wal` の mtime とサイズ、`data_version 2`、画像 318 ファイルの署名、`.backup/daily` 3 世代が**前の監査の終了時と同じ**。`-shm` の mtime だけ読み取りで動く）、`src/`、`apps/`、`tests/`、`tools/`、既存の docs。**8790 は今回も接続拒否で、立てても止めてもいない**。git のコミット無し

## 判定: 合格

A は無し、B は無し。**前回の A-1〜A-3・B-1・B-2・C-1・C-3・D-1〜D-3 は塞がったことを複製で確かめた**（§E-0）。残るのは C 1 件（API 直打ちの道）と E 1 件（記録の道具のずれ）、軽微なテストの穴 2 つ。

**最も重大な 3 件**:

1. **（C-1）走査が「参照切れ」にした後に片付けた行を、ファイルを戻して走査の前に API の `undo` で開き直すと、200 `restored` が返るのに `deleted_at` は立ったまま**（`asset_location.missing_at` が立ったままなので `should_hide()` が「生きている場所 0」と読む）。走査すれば戻る。**画面にはこの道が無い**（閉じた行は「最近の削除」に出ず `undoable: false`。画面の道は走査だけで、そちらは直っている）。記録 §7-3 と `design.md` §16.7-11 ③の「走査の前でも `undo` が開き直す」は `missing_at` が無い形でしか成り立たない。直し方は 1 行（§C-1）
2. **（E-4）実装者の道具 `tools/probe_deletions_advance.py` は直していないので、直した実装に対して 14 件のうち 5 件 NG を返す**（線 1 が古い `asset_id` の行を先頭に取って 409 `different_file`、線 5 が 187 を期待）。記録 §4「動かし方」がこの道具を指したまま。道具を A-1 の後の形（193/1）に合わせるか、記録から外す
3. **（F）テストの穴が 2 つ残る（軽微）**: `_row_image_is_back()` が枚の同一性を見なくても落ちない（M18）、`_mark_recovered()` の A-2 の道にテストが無い（M21。手では確かめた）

**A-1〜A-3・B-1・B-2・C-3・D-1〜D-3 は複製で塞がったことを確かめた**（§A〜§E-0）。回帰: pytest **554 passed × 3**、gui_smoke **406 ok / NG 0**、gui_layout **11 本 × 4 幅 ok**（§H）、壊し試験 §F。

---

## E-0. 線（前回の §E-0 に、今回の修正の線を足した）

| # | 線 | 確かめ方・値 | 結果 |
| --- | --- | --- | --- |
| 1 | **A-1**: 古い `asset_id` の 6 行の advance | 複製 rcA（8812）: 6 行とも `POST /api/deletions/{id}/advance {stage:2}` → **409 `different_file`**、`details.ledger.size` 1,487,627 / 1,487,570 / 1,698,221 / 1,763,619 / 1,626,604 / 1,557,089 と `now.size` 1,829,828 / 1,880,986 / 1,819,719 / 1,811,130 / 1,872,627 / 1,779,251。**Y 6 枚の `(size, mtime_ns)` は前後で同じ**、Y の `deleted_at` は NULL、文に「片付ける」。6 行の後で台帳・署名 268 件・`data_version` が同じ。まとめて（6 件）も `count 0 / skipped 6（different_file）` | **ok** |
| 2 | **C-1**: 194 件を 1 回で片付ける | rcA: **片付け 193・断り 1**（43 ms）。断られた 1 件は `01M58PFWJP8Z4R77GW96FY6RQM`（`fa690e934ddd56a5.png`。**台帳の枚と登録の枚が同じで、ファイルが在る唯一の行**）、理由 `file_found`。6 行（古い `asset_id`）は閉じた。署名同じ・`asset.deleted_at` 461 件同じ・`asset_location` 同じ。Y 6 枚は見えたまま | **ok**（193/1。**残る 1 件の理由は「本当にその画像が在る」**） |
| 3 | **A-2**: 戻した後に Y が戻る | rcD（プロセス内）: 台帳だけ段 2・ファイルは元の場所・Y に印が立った形 → `trash_restore` → `recovered: true`・**Y の `deleted_at` NULL**・X は隠れたまま。advance 自体は A-1 で 409 になるので、A-2 の道は `_mark_recovered` の形で確かめた | **ok** |
| 4a | **全体の数（A-3 の規則の変更が他の枚を動かさないか）** | rcE（プロセス内、素の複製）: `close_many(194)` → 193 / 1 → 隠れ **194・見える 267** のまま → `scan()`（`known 268`）→ 隠れ **194・見える 267** のまま、Y 6 枚は `deleted_at` NULL、「最近の削除」1 行。**閉じた 193 行の枚は実体が無いので走査後も隠れたまま（幽霊は戻らない）**、生きている段 1 の 1 行も隠れたまま | **ok** |
| 4 | **A-3（走査）** | rcA: 段 1 で外す（新しい行＝閉じた行は `_live_stage1` に数えない） → ファイルを外へ → `close` 200 → `undo` 409 `already_closed`（文に「走査」の案内）→ ファイルを戻す → `POST /api/scan` → **`missing_at` NULL・`deleted_at` NULL**（`GET /api/assets/{id}` で確認）。閉じた行は閉じたまま・「最近の削除」に出ない | **ok** |
| 5 | **A-3 (b)（走査の前の undo。API だけの道）** | rcA（`missing_at` が立っていない形）: `close` → ファイルを戻す → `undo` → **200 `restored`・`closed_at` が外れ・`deleted_at` NULL**／別の大きさのファイルを置いた形 → **409 `already_closed`**（開き直さない）／rcB（**`missing_at` が立っている形**＝実データの 187 行の形）: `undo` → 200 `restored` だが **`deleted_at` は立ったまま**（§C-1）。走査すれば NULL | **条件付き**（C-1） |
| 6 | **幽霊を戻さない** | rcA: 実体が無い閉じた行の `undo` → 409 `already_closed`。別の画像が在る閉じた行（古い `asset_id`）の `undo` → 409（Y を X として戻さない）。rcB: 走査しても X（場所 0）は隠れたまま・Y は見える | **ok** |
| 7 | **B-1** | rcC（8813、本物の Chrome headless、`cdp_double.mjs`）: 1 行の「アプリのゴミ箱へ移す」を 2 連打 → **POST 1 回**・文「1 件をアプリのゴミ箱へ移しました。」／「全部選ぶ → 選んだ 193 件をまとめてアプリのゴミ箱へ移す」を 2 連打 → **POST 1 回**（ids 193）・文「0 件を…移しました。193 件は移しませんでした（ファイルがありません、別の画像があります）。」（直前に 1 件移した後なので 0 が正）／「選んだ 194 件をまとめて片付ける」を 2 連打 → **POST 1 回・確認 1 回**・文「193 件を片付けました。1 件は片付けませんでした（ファイルがまだあります）。」。帯は 1 件も選んでいないとき「選んだ行はありません」 | **ok** |
| 8 | **B-2** | rcA: `delete_request` 32 → advance_many（全部断り）で 33（`kind advance_many`・`count 6`）→ close_many で 34（`kind close_many`・`count 194`・`stage 1`・`result_json` に `file_found`）→ 再送で 35 → 単発 close（replayed）で 36（`kind close`）→ 単発 advance で +1。断った単発の advance は残らない | **ok** |
| 9 | **C-3** | rcB: 段 3 の行（保留に実体）の `close` → 409 `file_found`。保留を外から消した後の `close` → 200・`purge_at`/`remaining_sec` NULL・`tick()` の `decremented` 0・`state closed`・pending に出ない | **ok** |
| 10 | **D-1** | rcA: 再送は `count 193 / replayed_count 193 / skipped 1`。rcB: 3 件 → `replayed_count 0` → 再送 `3` | **ok** |
| 11 | 失敗の道（再） | rcB: `move_failed` / `cross_volume` / `target_exists` → 409・段 1・ファイルそのまま・`trash/` 空・`delete_request` に残らない | **ok** |
| 12 | GET は書かない（再） | rcA: 5 本の前後で署名・`data_version`・台帳 8 列が同じ | **ok** |
| 13 | TOP_UP（再） | rcA〜rcD の起動で `pre-topup-*` が 1 つずつ・列 2 つ | **ok** |

## A. 直っていない（必ず直す）

なし。

## B. 重大

なし。

## C. 中程度

### C-1. 走査が「参照切れ」にした後に片付けた行は、走査の前の `undo` で「戻した」と返るのに一覧に戻らない

- 再現（rcB、`.tmp-audit-redo/p10-audit/inproc2.py` §B）: 同じ `asset_id` の段 1 の行のファイルを外へ → `scan()`（`missing: 1`＝`missing_at` が立つ）→ `close` 200 → ファイルを戻す → `undo` → **200 `restored: true`・`closed_at` NULL・`restored_at` 立つ**、しかし **`asset.deleted_at` = 2026-10-18T23:45:29Z のまま・`missing_at` = 2026-10-19T06:35:14Z のまま**。その後 `scan()` で `deleted_at` NULL・`missing_at` NULL
- 原因: `_restore()` の段 1 の道は `asset_location` を触らない（`if stage != 1 and loc is not None:` の中だけ `missing_at = NULL`）。`_row_image_is_back()` はファイルの存在と大きさを見るが `missing_at` は見ない。`should_hide()` は `live == 0`（`missing_at` が立っている）で真
- 届く道: **API だけ**（`POST /api/deletions/{id}/undo`）。閉じた行は `pending()` から外れ、`_log_doc` の `undoable` は `hidden / trashed / pending / stuck` だけなので、画面に「戻す」は出ない。利用者の道は「ファイルを戻して走査」で、そちらは正しく一覧に戻る（§E-0 の 4）。実データの 187 行は `missing_at` が立っているので、API を直に叩く人だけがこの形に当たる
- 直し方（1 行）: `_restore()` で `_reopen_closed_row()` を通った段 1 の行は、`loc["missing_at"]` が立っていれば `UPDATE asset_location SET missing_at = NULL, last_seen_at = ? WHERE path = ?` を同じ取引で行う（`_row_image_is_back()` が実体の一致を見た後なので安全）。テスト: 「走査で参照切れにした後に片付け、ファイルを戻し、走査の前に `undo` → `deleted_at` NULL」
- 記録 §7-3「走査の前でも `undo` が開き直す」と `design.md` §16.7-11 の③は、`missing_at` が立っていない形（実装者のテストの形）でだけ成り立つ


## D. 軽微

- D-1. `_files_of_row()` は台帳の `size` が NULL の行を「この行のファイルは無い」と読む（記録どおりの決め。実データの 194 行は全部 `size` あり）。古い行を片付けるときの安全側は「在るかもしれないので断る」だが、`size` 無しの行は P8 以降の台帳には無い。**変更なし**でよい
- D-2. `_request_stage_for()`: 片付けの対象が段 1 だけなら `stage 1`（確かめた）。混ざれば 1 と決めてある
- D-3. 404/405 の両方を許す検査（確かめた: `PYTHONPATH` の複製で `apps/gui` を置かなくても素で落ちない。§F の素の実行）
- D-4. 「選んだ行はありません」（本物の Chrome で読んだ。§H）
- D-5. `--screen tags` は `gui_layout_seed.py --tags` の後で ok（前提。記録どおり）

## E. 設計とのずれ

- E-1. `design.md` §16.7 の 11 行目③「走査の前でも `undo` が開き直して戻す」は、C-1 の形（`missing_at` が立っている行）では「開き直すが一覧には戻らない」。直したら③に「`missing_at` も戻す」を足す
- E-2. 実装者が決めた点の判定（今回）: `different_file` を `missing_file` と分けた（**妥当**。文は次の一手を案内する）／`close` の「この行の画像」の読み（**妥当**。`to_path`/`hold_path` は大きさを見ない＝自分の置き場は在れば断る、も妥当）／`replayed_count` を `count` に含めたまま分ける（**妥当**。既存の契約を変えない）／`_request_stage_for` の「混ざれば 1」（**妥当**）／閉じた段 3 の行の `purge_at` NULL（**妥当**）
- E-3. 記録 §7-6「実データの帰結は 193 件を片付け・1 件を移す」は**確かめた**（残る 1 件は `fa690e934ddd56a5.png`）
- E-4. **`tools/probe_deletions_advance.py` は直していない**（sha256 が前回と同じ、10:37:17）。直した実装に対して回すと（`--port 8800 --work <複製>`、15:42）**14 件のうち 5 件 NG**: 線 1「ファイルがある → アプリのゴミ箱へ移る」が `live[0]`（並びの先頭＝古い `asset_id` の行）で **409 `different_file`**、線 2 は飛ばし、線 5 が「片付けた 192・断った 2」（187 を期待）、線 6 `closed=192`、線 8 一覧 1 件。**実装の欠陥ではなく道具の期待が古い**。記録 §4「動かし方」と仕分け §6 の「14 件の線と合わせて再実行した」はこの道具のままでは成り立たない。道具を「古い `asset_id` の 6 行は 409、同じ枚の 1 行を移す、193/1」に直すか、記録から外す
- E-5. `/api/assets` の既定は 100 件（`total 267`）。「一覧に戻った」を API で見るときは `GET /api/assets/{id}` の `deleted_at`。確認の作法であって欠陥ではない（§H）

## F. 壊し試験（監査側）

数え方は前回と同じ（ソースは触らず `src/image_reviewer` と `apps/gui` を `.tmp-audit-redo/p10-audit/mut2/` に複製して 1 か所壊し、`PYTHONPATH` で前に置いて `tests/test_deletions_advance.py tests/test_deletions.py tests/test_relink.py tests/test_scan_state.py` を回す。**素の実行で落ちたテストを差し引き、新しく FAILED が 1 つ以上なら「落ちた」**。終了コードは見ない）。素: **153 passed・0 failed**（`apps/gui` を置いたので D-3 の 405 は出ない）。JS 素: **406 ok / NG 0**。実装者の 21 通りを私の印で置き直し（M1〜M16）、5 通り足した（M17〜M21）。JS は 6 通り。**26 通りのうち 22 が落ち、4 が落ちない**（`mutate2.log`）。

| # | 壊した所 | 落ちたテスト | 判定 |
| --- | --- | --- | --- |
| M1 | A-1 台帳の行が指す物かの照合を外す | `test_advance_refuses_a_ledger_row_whose_image_is_replaced` ほか 1 | 落ちた |
| M2 | A-1/C-1 `_files_of_row` が別の画像を数える | **落ちない** | **等価**（実装者の #2 と同じ。M3 の守りが効く） |
| M3 | A-1/C-1 `_files_of_row` の大きさの照合を外す | **落ちない** | **等価**（M2 の守りが効く） |
| M2+M3 | 両方外す（別に回した） | `test_advance_refuses_a_ledger_row_whose_image_is_replaced`（1 failed / 115 passed） | **落ちた**＝実装者の #4 と一致。2 つは互いの保険 |
| M5 | A-2 戻すときにいまの登録の印を引き直さない | `test_restore_clears_the_mark_of_the_asset_registered_now` | 落ちた（前回の穴 A1 が埋まった） |
| M6 | A-3 走査で印を引き直さない | `test_a_closed_row_opens_again_when_the_file_comes_back` | 落ちた |
| M7 | A-3 `should_hide` が閉じた行を数える | 同上 | 落ちた |
| M8 | A-3 `_live_stage1` が閉じた行を数える | 同上 | 落ちた |
| M9 | A-3 ファイルが戻っても開き直さない | `…_when_the_file_is_back_before_the_scan` | 落ちた |
| M10 | 一時置き場を見ない（前回の穴 A3） | `test_close_refuses_a_file_that_is_in_the_hold` | 落ちた（穴が埋まった） |
| M11 | 閉じた行の advance を断らない（前回の穴 A14） | `test_a_closed_row_with_the_file_back_is_not_advanced` | 落ちた（穴が埋まった） |
| M12 | C-3 タイマーから外さない | `test_close_takes_a_stage3_row_out_of_the_timer` | 落ちた |
| M13〜M15 | B-2 まとめて／単発の片付け／段 | `test_many_records_the_request_and_counts_the_replays` | 落ちた |
| M16 | D-1 `replayed_count` | 同上 | 落ちた |
| M17 | `_row_image_is_back` が大きさを見ない | `test_a_closed_row_cannot_be_restored` | 落ちた |
| M18 | `_row_image_is_back` が枚の同一性を見ない | **落ちない** | **テストの穴（軽微）**。台帳の枚と違う枚が同じ大きさで登録されている形の `undo` を見るテストが無い。M17 の大きさの照合がほぼ同じ形を止めるので実害は小さい |
| M19 | 走査の「隠れているのにファイルが在る」の道を外す | `…_when_the_file_comes_back` | 落ちた |
| M20 | `different_file` の文から「片付ける」の案内を消す | M1 と同じ 2 件 | 落ちた |
| M21 | `_mark_recovered` が台帳の枚だけ同期 | **落ちない** | **テストの穴（軽微）**。A-2 の二重の守りのうち `_mark_recovered` の道（台帳を書いた後・動かす前に落ちた行を戻す）はテストが無い。rcD で手で確かめて Y の印が外れることは見た（§E-0 の 3） |
| J1〜J3 | B-1 の `busy` を 3 つの関数から外す | gui_smoke NG 1 / 3 / 2 | 落ちた |
| J4 | D-2「選んだ 0 件」と書く | NG 1 | 落ちた |
| J5 | D-1 既に片付いていた数を言わない | NG 1 | 落ちた |
| J6 | `busy` を `await` の後に立てる | — | **無効**（私の変異が構文を壊して node が落ちた。数えない） |

**実装者の数え方について**: 記録の「21 通り＋2 つは等価変異（両方外すと落ちる）」は私の印でも同じ結論（M2・M3 が落ちず、M2+M3 で落ちる）。前回の F の穴 5 つ（A1 の形・A3・A14・二度押し・台帳の `size`）は**すべて落ちるようになった**。残る穴は M18・M21 の 2 つ（軽微）と、§C-1 の形（`missing_at` が立っている行の走査前の `undo`）。

## G. 依頼者への質問（推奨つき。待たずに進めた）

| # | 論点 | 選択肢 | 推奨 |
| --- | --- | --- | --- |
| G-1 | C-1 を直すか | (a) `_restore()` の開き直しで `missing_at` も戻す（1 行＋テスト 1 件）／(b) API の文言で「走査してください」と案内するだけ／(c) 利用者の再起動の後に回す | **(a)**。API だけの道だが「`restored: true` なのに隠れたまま」は規則の矛盾で、1 行で直る。再起動の前でも後でもよい |
| G-3 | 実装者の probe（E-4） | (a) A-1 の後の形に直す（6 行は 409・1 行を移す・193/1）／(b) 記録から外し、監査の `lines_http2.py` を線にする | **(a)**。記録の「動かし方」が指す道具が緑であるべき |
| G-2 | 利用者の押す順 | (a) 再起動 → 走査 → 「まとめて片付ける」（193/1）→ 1 件を「移す」／(b) 走査を挟まない | **(a)**。走査で `missing_at` が揃うので、片付けの判定が実データの形で確定する |

## H. 確かめられなかったこと・証拠・後始末

- **回帰**: `uv run --no-sync pytest -q` **554 passed × 3**（63 s / 39 s / 40 s。前回不安定だった `test_the_stuck_reason_says_why_it_could_not_go_back` は 3 回とも通った＝C-2 の修正）。`node tools/gui_smoke.mjs` **406 ok / NG 0**（BOM を外して数えた）。`gui_layout` **11 本 × 4 幅すべて ok**（rcC、`gui_layout_seed.py --tags` を当ててから。`--screen pending --ids` は 13:41 の `gui_layout.mjs` で 4 幅 ok）。実装者の `probe_deletions_advance.py` は 8800 で回した（**5 件 NG**＝E-4。道具の期待が古い）
- **自分の数え方の誤り**（実装の欠陥ではない。§C-2）: HTTP の線の「一覧に見える」を `GET /api/assets` の先頭 100 件で判定したため 3 本が NG に見えた。DB と `GET /api/assets/{id}` の `deleted_at` で取り直し、rcD で `advance → undo` を再実行して `deleted_at` NULL・`missing_at` NULL を確かめた（`lines_http2.log` の NG 3 行はこれ）。壊し試験 J6 は私の変異が構文を壊した（無効）
- **8790** は 15:27・15:40 とも接続拒否（立てていない・止めていない）。**8811**（実装者の複製サーバ）は立っていなかった。**8797** も無し
- **実データ**: 前の監査の終了時（13:45）の署名と同じ（`.data` の DB 以外 675 ファイル、`db.sqlite3` 3,301,376 B / `-wal` 4,190,072 B の mtime、`data_version 2`、画像 318 ファイル、`.backup/daily` 3 世代）。`-shm` の mtime だけ読み取りで動く。**列はまだ無い**（16 列）
- **後始末**: 複製サーバ 8812（PID 24532、rcA）・8813（PID 26296、rcC）は 15:40:47 に `/api/health` の `data_dir` を確かめてから止めた（`netstat` に 88xx の LISTEN 無し）。残した物: `.tmp-audit-redo/p10-audit/rcA`〜`rcD`・`mut2/`・`lines_http2.py`・`inproc2.py`・`mutate2.py`・`cdp_double.mjs`・ログ（前回の複製 A〜D・C2 も残っている。合わせて約 3 GB）。`%USERPROFILE%` の下には何も作っていない
- Orca の知らせ: `p10-recheck-start` = msg_465a35978df2（15:27）、`p10-recheck-done` = msg_8b12b193fef2（15:48）。送り先 run_5bdd431bf57b
- **引用した場所**（15:4x、`grep -n`）: `deletions.py` `should_hide` 325 / `sync_hidden` 345 / `_live_stage1` 933 / `close` 1261 / `_run_many` 1310 / `_request_stage_for` 1364 / `_advance_one` 1394 / `_require_file_for_advance` 1451 / `_close_one` 1501 / `_files_of_row` 1561 / `_restore` 1703 / `_mark_recovered` 1798 / `_sync_hidden_with_location` 1828 / `_row_image_is_back` 1845 / `_reopen_closed_row` 1873、`scan.py` 65・90・96・144・160、`pending.js` `advance` / `closeRow` / `runBatch` の `busy`
- 実行したコマンド:

```powershell
$env:UV_CACHE_DIR = "C:\work\image-reviwer\.uv-cache"; $env:PYTHONUTF8 = "1"
uv run --no-sync pytest -q                                                   # 554 passed × 3
node tools/gui_smoke.mjs                                                     # 406 ok
.venv\Scripts\python.exe .tmp-audit-redo\p10-audit\mk_replica.py <絶対パス>   # rcA〜rcD
.venv\Scripts\python.exe -m uvicorn image_reviewer.app:app --port 8812       # IMAGE_REVIEWER_DATA / IMAGE_REVIEWER_BACKUP_DIR = rcA
.venv\Scripts\python.exe -I .tmp-audit-redo\p10-audit\lines_http2.py 8812    # 37 検査（NG 3 = 私の 100 件の見落とし）
.venv\Scripts\python.exe .tmp-audit-redo\p10-audit\inproc2.py <rcB>\data     # 20 検査（NG 1 = C-1）
node tools/gui_layout.mjs --base http://127.0.0.1:8813 ...（11 本）           # すべて ok
node .tmp-audit-redo\p10-audit\cdp_double.mjs --base http://127.0.0.1:8813   # B-1: 3 通りとも POST 1 回
.venv\Scripts\python.exe .tmp-audit-redo\p10-audit\mutate2.py                # 22 落ちた / 4 落ちない（M2・M3 等価、M18・M21 軽微な穴）
```
