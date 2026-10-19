# P10 監査報告 — 実行込み（段 1 の行を後から進める・実体が無い行を片付ける）

- 日付: 2026-10-19 13:22〜13:58（JST）。監査者は引き継ぎ（前の監査者は Orca サーバの入れ替えでセッション終了）
- 指示書: Orca 経由の依頼（dsh / DeepSeek、2026-10-19 13:22 受領）。設計書 §1.2 の合格の線は P10 に無いので、**依頼の (1)〜(8) を自分で線にした**（§E-0 の表）
- 実装の記録: `docs/deletions-advance.md`（214 行、10:53:32）、`tools/probe_deletions_advance.py`（532 行、10:37:17）
- 対象（行数・mtime。監査の開始と終了で sha256 が同じことを確かめた）: `src/image_reviewer/deletions.py`（2168 行、10:48:43）、`src/image_reviewer/api/deletions.py`（244、10:16:14）、`src/image_reviewer/db.py`（905、10:11:07）、`apps/gui/pending.js`（1084、10:52:27）、`apps/gui/index.html`（331）、`apps/gui/styles.css`（948）、`tools/gui_smoke.mjs`（2289、10:26:25）、`tests/test_deletions_advance.py`（677、10:35:45）。**`tools/gui_layout.mjs` だけは監査中に並行の担当が直した**（10:59:02 → 13:41:08。`WANT_STAGE[2]` の 1 行。§D-9）
- 環境: `uv run --no-sync`（`UV_CACHE_DIR` はリポジトリの中）。複製は `tools/probe_deletions_advance.py` の `make_replica()`（`backup()` ＋ `copy2` ＋ パスの貼り替え）で 5 つ作り、**全パス列 1,114 値が複製の外を指していない**ことを自分で確かめてから使った（`.tmp-audit-redo/p10-audit/mk_replica.py`）。複製サーバは **8798（複製 A）・8799（複製 B）・8800（実装者の probe）**。`IMAGE_REVIEWER_DATA` と `IMAGE_REVIEWER_BACKUP_DIR` は複製の中。**8797 は他の担当の複製サーバ（`doc-p10-replica`）で、触っていない**
- **利用者のアプリ（8790）は、監査の開始時（13:22）から終了時まで接続拒否だった**（止めていないし、立ててもいない。§H）
- 触っていないもの: 実データ `.data/`（`mode=ro` でしか開いていない。画像 318 ファイル 303,256,170 B の署名、`db.sqlite3` と `-wal` の mtime・サイズ、`PRAGMA data_version = 2`、`.backup/daily` の 3 世代の署名が**開始時と同じ**。`-shm` の mtime だけ読み取り専用の接続で動く）、`src/`、`apps/`、`tests/`、`tools/`、既存の docs。git のコミットはしていない

## 判定: 直してから次へ

**最も重大な 3 件**（どれも複製で再現し、値を写した）:

1. **（A-1）古い `asset_id` の 6 行に「アプリのゴミ箱へ移す」を打つと、利用者が消した枚 X ではなく、いま同じ場所に登録されカタログに見えている別の枚 Y のファイルを動かす。** 照合は現在の登録の `(size, mtime_ns)` に対してだけで、台帳の `deletion_log.size`（1,487,627 など）と現在のファイル（1,829,828）は違う。再現: 複製 B で `POST /api/deletions/01M57AY0VA9TMBCHYAPH5599V4/advance {stage:2}` → 200、`asset_id` が Y（`01M58RMCQ09JV8H7S8NYPDRFAP`）、`GET /api/assets` から Y が消える。実データの実体あり 7 行のうち 6 行がこの形（画面の「全部選ぶ → まとめてアプリのゴミ箱へ移す」で 6 枚の見えている画像がゴミ箱へ行く）
2. **（A-2）その行を「戻す」と、ファイルは戻るが Y の `deleted_at` が立ったまま。** `_restore()` が同期するのは台帳の古い X（`deletions.py:1624`）で、Y は誰も引き直さない。Y は実体があり登録も生きているのに**カタログから永久に消える**（`undo` は `already_restored`、再走査は `deleted_at` を触らない）。複製 B（HTTP）と複製 C2（プロセス内）の両方で再現
3. **（A-3）片付けた行は、ファイルが戻ってきても二度とカタログに戻せない。** 段 1 の行を片付け（200）→ 利用者が Windows のごみ箱からファイルを戻す → 走査で登録は生き返る（`missing_at` NULL）が `deleted_at` は立ったまま → `undo` は 409 `already_closed`、**段 1 で消し直しても閉じた行の再送（`replayed: true`）になって `undo` は同じ 409**。記録の「ファイルを戻してから走査で登録し直すのが正しい道」は成り立たない（複製 D で再現）

ほかに B が 2 件（二度押しで POST が 2 回飛び、2 回目の応答が結果の文を上書きする／`delete_request` の記録が 4 つの口のうち 1 つだけ）、C が 3 件、D が 10 件。**回帰は緑**（pytest 547 ＝ ただし既存の `test_deletions.py` の 1 件が 3 回中 2 回落ちる・gui_smoke 395 ok・gui_layout 10 画面 × 4 幅 ok・実装者の probe 14/14・壊し試験 32 通りのうち 28 が落ち、落ちない 4 のうち 2 がテストの穴）。**実体なし 187 件の片付けそのもの（close）は安全**（ファイルを 1 つも動かさない・`deleted_at` そのまま・二重 1 行・閉じた後の undo 409）。

---

## E-0. 合格の線（§1.2 に無いので監査者が置いた。依頼の (1)〜(8) から）

| # | 線 | 確かめ方 | 結果 |
| --- | --- | --- | --- |
| 1 | advance: ファイルがある段 1 の行 → ゴミ箱へ移る → 「戻す」で戻る | 複製 B: `POST /api/deletions/{id}/advance` → `to_path` が `data\trash\20261019\fa\fa690e934ddd56a5.png`・元に無い・`(size, mtime_ns)` 同じ・`missing_at` 立つ → `POST /api/deletions/{id}/undo` → 元に在る・`missing_at` NULL・`deleted_at` NULL | **ok**（同じ `asset_id` の 1 行）。**古い `asset_id` の 6 行は A-1・A-2** |
| 2 | advance の 4 つの断り | 複製 C2（プロセス内で差し替え）: `move_no_clobber` が落ちる → 409 `move_failed`・段 1 に戻る・`to_path` NULL・署名同じ・空の `trash/` 無し／`st_dev_of` を別の値に → 409 `cross_volume`／`free_name` が埋まった場所を返す → 409 `target_exists`・既存のファイルの中身と mtime 同じ／複製 B: 実体なし → 409 `missing_file`（文に「ファイルが無いので片付ける」）／段 2 の行 → 409 `already_stage2`／閉じた行 → 409 `already_closed` | **ok** |
| 3 | 段 3 への直行は無い | `{stage: 3}` を単発・まとめての両方 → 422 `bad_stage`。`1` / 無し / `true` も 422 | **ok** |
| 4 | close の安全 | 複製 B: 194 件を 1 回で → 200・片付け 187・断り 7（理由は `file_found` だけ、61 ms）・前後で複製の全ファイル 268 件の署名同じ・`asset.deleted_at` 461 件すべて同じ・`asset` 461 / `asset_location` 455 行の値同じ・`closed_at`/`close_reason='missing'` が 187 行 | **ok** |
| 5 | 閉じた後 | 二重の close → 200 `replayed` で `closed_at` 同じ・行は 1 つ／`undo`・`pending-deletes/{id}/undo`・`trash/restore`・`advance` → 409 `already_closed`／`asset.deleted_at` そのまま・`restored_at` 無し／「最近の削除」から消え台帳に残る（`state: closed`、`closeable: false`、`undoable: false`） | **ok** |
| 6 | 上限 200 | 201 件 → 422 `too_many`（`limit: 200`）で台帳も署名も変わらない（close・advance の両方）。205 個の id（重複 5）→ 200 で `requested: 194`（重複を畳む） | **ok** |
| 7 | 断りを黙って捨てない | advance_many に実体なし 187 ＋ 無い id 7 → `skipped` に `missing_file` 187・`refused` 7、`count + skipped_count == requested` | **ok** |
| 8 | 人だけ・GET は書かない・403/422 | 4 つの口 × （agent 403 `human_only`・robot 422・ヘッダ無し 403・`Host: evil` 403・`text/plain` 403）／GET 9 本（`pending-deletes`・`trash`・`deletions`・`deletions/trash`・`scan`・`assets`・`stats`・`health`・`deletions/roots`=404）の前後で `PRAGMA data_version` 2→2・署名・台帳の 7 列が同じ／`GET /api/deletions/advance`・`/close` は 404 | **ok** |
| 9 | DB の変更 | 複製 A のサーバ起動で `pre-topup-20261019-133026/`（`db.sqlite3` ＋ `manifest.json`。`missing: deletion_log.closed_at, close_reason`）が付き、列が 2 つ足され、`missing_top_ups()` が空、`UPDATE … close_reason='x'` は `CHECK constraint failed`。`user_version` は 6 のまま。実データにはまだ列が無い（`PRAGMA table_info` 16 列） | **ok** |
| 10 | 回帰 | §H の表 | **緑**（既存の 1 件が不安定） |

---

## A. 直っていない／設計の約束が成り立たない（必ず直す）

### A-1. 古い `asset_id` の行の advance は「別のファイル」を移す（記録の「別のファイルを移さない守りは `(size, mtime_ns)` の照合が持つ」は成り立たない）

- 場所: `src/image_reviewer/deletions.py` `_target_for_advance()`（`asset_id` を見ずに現在の登録を引く）と `_require_file_for_advance()`（`int(target["size"]) != size or int(target["mtime_ns"]) != mtime_ns` ＝**現在の登録**と比べる）。**台帳の `deletion_log.size` とは比べない**
- 実データ（`mode=ro`）: 実体あり 7 行のうち 6 行（`01M57AY0VA9TMBCHYAPH5599V4` ほか、`132800_00001_.png`〜`_00006_.png`）は、台帳の `asset_id`（X）が `deleted_at` 2026-10-18T11:04:14Z で隠れ・場所 0、現在の登録（Y）は `deleted_at` NULL で**カタログに見えている**。`deletion_log.size` 1,487,627 / 1,763,619 / 1,626,604 / 1,487,570 / 1,698,221 / 1,557,089 に対し、現在のファイルは 1,829,828 / 1,811,130 / 1,872,627 / 1,880,986 / 1,819,719 / 1,779,251。`location_history` に X→Y の `replaced` が残っている（中身が入れ替わって走査が登録し直した形）
- 再現（複製 B、8799）: `POST /api/deletions/01M57AY0VA9TMBCHYAPH5599V4/advance {stage:2}` → **200**、`asset_id` = Y、`library\0\132800_00001_.png` が `data\trash\20261019\3e\` へ、`GET /api/assets` の一覧から Y が消える（`deleted_at` が立つ）
- 画面では: 194 行を「全部選ぶ → 選んだ 193 件をまとめてアプリのゴミ箱へ移す」で**見えている 6 枚がゴミ箱へ行く**（本物の Chrome で押して確認。§B-1 の試験の副産物）
- 直し方（推奨）: `_require_file_for_advance()` で**台帳の `size`**（と `location_history` の `mtime_ns`）とも照合し、違えば 409（`code: replaced`、文は「消した画像はもうこの場所に無く、別の画像があります」）。そのうえで **`close` がこの 6 行を片付けられる**ようにする（§A-3 と合わせて、`_files_of_row()` の「在る」を「**この行の画像**が在る」にする＝`size` が台帳と違うファイルは数えない）。利用者が見ている 194 行の帰結は「193 件を片付け・1 件を移す」になる
- テスト: `tests/test_deletions_advance.py` `test_advance_works_when_the_ledger_asset_id_is_stale` は**この挙動を正として固定している**（`out["asset_id"] == new_asset` を期待）。直すときはこのテストを「409 で断り、`close` で終われる」に書き換える

### A-2. 戻した後、いま登録されている枚 Y の `deleted_at` が立ったまま（実体があるのにカタログから永久に消える）

- 場所: `src/image_reviewer/deletions.py` `_restore()` の `self._sync_hidden(con, row["asset_id"], at)`（1624 行）。`row["asset_id"]` は台帳の古い X。advance は `_sync_hidden(con, target["asset_id"], at)`（Y）で立てるので、**立てる側と消す側で見る枚が違う**
- 再現（複製 B）: A-1 の advance の後 `POST /api/trash/restore {deletion_id}` → 200、ファイルは戻り `missing_at` NULL、**`asset.deleted_at` = 2026-10-19T04:36:46Z のまま**、`GET /api/assets` に Y が無い。複製 C2 のプロセス内でも同じ（`Y.deleted_at=2026-10-19T04:36:51Z`）
- その後の道: `undo` は 409 `already_restored`。走査は `asset.deleted_at` を触らない（`store.py:378`）。Y を見せる操作は無い
- 直し方: `_restore()` で**台帳の枚と現在の登録の枚の両方**に `_sync_hidden()` を掛ける（`loc["asset_id"]` が `row["asset_id"]` と違えばそちらも）。A-1 を「断る」に直しても独立に直す（段 2 で消した後に走査が入れ替えを拾う道が残るかは**推測**で、実行していない）
- テスト: 同じテストが `where(store, new_asset)["missing_at"] is None` までしか見ていない（**`deleted_at` を見ない**）。壊し試験 A1（§F）はこの穴を示した

### A-3. 片付けた行は、ファイルが戻っても戻せない（記録の「ファイルを戻してから走査で登録し直すのが正しい道」が成り立たない）

- 再現（複製 D、`.tmp-audit-redo/p10-audit/f2_closed_file_back.py`）: 同じ `asset_id` の段 1 の行（`fa690e934ddd56a5.png`）のファイルを外す → `close` 200 → ファイルを元の場所に戻す → `scan()`（`known: 268, changed: 0`）→ `asset_location.missing_at` NULL・`asset_id` 同じ → **`asset.deleted_at` = 2026-10-18T23:45:29Z のまま** → `undo` 409 `already_closed` → `svc.delete(stage=1)` は `_live_stage1()` が閉じた行を拾って **`replayed: True`（新しい行を作らない）** → `undo` 409 `already_closed`
- 原因: `_should_hide()`（1789 行）は `stage = 1 AND restored_at IS NULL` を数え **`closed_at` を見ない**／`_live_stage1()`（889 行）も `closed_at` を見ない／走査は `deleted_at` を引き直さない
- 直し方（推奨）: (a) `_live_stage1()` と `_should_hide()` で閉じた行を除く（閉じた行は「終わった」のだから隠す理由にならない。実体が無い間は `live == 0` で隠れたまま）、(b) 走査が `missing_at` を NULL に戻したとき、その枚の `deleted_at` を `_should_hide()` の規則で引き直す（`scan.py` の「印が立っていれば戻す」の隣）。これで A-2 の Y も走査 1 回で戻る
- 妥当性の注記: 「片付けた後は戻せない」は**実体が無い間**は正しい（幽霊を戻さない。確かめた）。実体が戻った後まで閉じたままなのは要望に無い帰結

## B. 重大

### B-1. 二度押しで POST が 2 回飛び、2 回目の応答が結果の文を上書きする（`advance` / `runBatch` / `closeRow` に `busy` が無い）

- 場所: `apps/gui/pending.js` `advance()`（889 行）・`closeRow()`（911 行）・`runBatch()`（935 行）。`state.busy` を立てるのは `exec()`（619 行）だけ
- 再現（本物の Chrome headless、複製 A、`.tmp-audit-redo/p10-audit/cdp_double.mjs`。`window.fetch` を差し替えて POST を数え、本物のサーバへ流す）:
  - 段 1 の行の「アプリのゴミ箱へ移す」を 2 連打 → **POST 2 回**。1 回目 200・2 回目 409 → 画面の文は「**既にアプリのゴミ箱へ移しています**」（赤）。利用者の 1 回の操作は成功しているのに失敗の文が出る
  - 「全部選ぶ → 選んだ 193 件をまとめてアプリのゴミ箱へ移す」を 2 連打 → **POST 2 回（ids 193 と 193）**。1 回目は 6 件を移し 187 件を断る、2 回目は 0 件・193 件を断る → 画面の文は **「0 件をアプリのゴミ箱へ移しました。193 件は移しませんでした（ファイルがありません、既にアプリのゴミ箱にあります）。」**＝**6 枚が動いたのに「0 件」と出る**
  - 「選んだ 194 件をまとめて片付ける」を 2 連打 → 確認 2 回・**POST 2 回**（2 回目は 187 件が `replayed` で成功に数えられるので文は「187 件を片付けました。7 件は…」で偶然同じ）
- 直し方: 3 つとも `if (state.busy) return null; state.busy = true; … finally { state.busy = false }`（`exec()` と同じ）。`gui_smoke` に「2 連打で POST 1 回」の検査を足す（罠 27。`docs/p8-5-audit-report.md` C-1 と同じ形）

### B-2. `delete_request` の記録は 4 つの口のうち単発の `advance` だけ（記録の「`actor` は `delete_request` に残す」は 1/4）

- 計測（複製 B）: `delete_request` 32 行 → advance_many（200 件）後 32 → close_many（194 件）後 32 → 単発 advance 後 35（断った単発は残さない＝正）
- 場所: `advance()`（1157 行）は `_open_request()` を呼ぶが、`advance_many()`・`close()`・`close_many()` は呼ばない
- 推奨: まとめては**1 回の呼び出しで 1 行**（`count` = requested、`result_json` に `skipped` も）、`close` も残す。誰がいつ 187 行を終わりにしたかが台帳の `closed_at` にしか残らない（`closed_by` も無い）のは、削除の記録の家風（1 行 = 1 回の操作）と合わない

## C. 中程度

### C-1. 古い `asset_id` の行は `close` もできない（A-1 と対）

- 複製 C2: 6 行のうち 1 つに `close` → 409 `file_found`（見つかった場所は Y のファイル）。X の実体はどこにも無いのに、別の画像で断る。利用者は 6 行を**移すことも片付けることもできない**（移すと A-1）。直し方は A-1 に書いた
- 実データで「194 件をまとめて片付ける」を押すと「187 件を片付けました。7 件は片付けませんでした（ファイルがまだあります）。」になる（実装者の記録どおり）。**その 7 件のうち 6 件は「まだある」のが別の画像**

### C-2. 既存のテスト `test_deletions.py::test_the_stuck_reason_says_why_it_could_not_go_back` が不安定（P10 の変更とは別）

- 全件 3 回のうち 2 回で落ち（`1 failed, 546 passed`）、単体でも 5 回中 2 回・6 回中 3 回落ちる。落ちるのは (3) の `assert svc.ledger(actor="human")["items"][0]["stuck_reason"] == "different"`（`tests/test_deletions.py` 531 行）。`clock.advance(sec=1)` で `at` は分けているが、`svc.tick()` の後の台帳の先頭が `different` の行でないことがある。原因は追っていない（P10 の範囲外）。**壊し試験の素の実行でも 1 回落ちたので、§F の数え方ではこの 1 件を外した**
- 推奨: 並びを `id` で引く（`[i for i in items if i["id"] == three["deletion_id"]]`）か、`tick()` の実削除で `at` が書き換わるなら期待を直す

### C-3. 閉じた段 3 の行をタイマーがまだ見る（API は段 3 の行も閉じられる）

- 複製 D（`f3_stage3_closed.py`）: 段 3 で保留 → 保留の実体を外から消す → `close` 200（`stage: 3`）→ `remaining_sec` を 0 に → `tick()` は `decremented: 1`・`purged: 0`、行は `purge_at` 残り・`hold_path` は無いファイルを指したまま・`state: closed`。「最近の削除」には出ない（閉じた行は外す）ので画面からは見えないが、台帳の行は「閉じたのに窓が動いている」形
- 推奨: `close` で `purge_at = NULL, remaining_sec = NULL` にする（`stuck` と同じ扱い＝タイマーから外す）。画面は段 3 に「片付ける」を出さないので実害は API 直打ちだけ

## D. 軽微（確かめた結果、問題なし も含む）

- D-1. `_run_many` は `replayed`（既に閉じた行）を `count` に数える。閉じた 2 行をまとめて再送すると `count: 2` → 画面は「2 件を片付けました。」（確かめた）。テスト `test_many_does_not_silently_drop_failures` がこれを正としている。文を「2 件は既に片付けていました」に分けるとよい
- D-2. まとめての帯の「選んだ 0 件」: 1 件も選んでいないとき `stat` に「選んだ 0 件」と出る（本物の Chrome で読んだ）。`bulkHtml()` のコメント「0 件と書かない」はボタンの語にだけ効いている。規約 3・C-22 に照らして「選んだ行はありません」にするか、0 のときは数を出さない
- D-3. `GET /api/deletions/advance` の 404 は GUI の静的マウントが返している。`PYTHONPATH` の複製（`apps/gui` が無い）で同じテストを回すと **405** になり `test_the_new_endpoints_are_guarded` が落ちる（§F の素の実行）。口の有無を見る検査としては `405` も許すか、`app.routes` を見る方が確か
- D-4. `advance` の `_unadvance()` は `from_path = NULL` に戻す。実データの段 1 の 194 行は元から `from_path` NULL なので、戻し先は正しい（確かめた）
- D-5. `KeyboardInterrupt`（`BaseException`）でも `_unadvance()` が走り段 1 に戻る（確かめた）。台帳だけ段 2・ファイルは元の場所の形（移動の前に落ちた）は「戻す」が `recovered: true` で拾う（確かめた）
- D-6. `cross_volume` の後に空の `trash/` を残さない・`target_exists` の後に既存のファイルの中身と mtime が同じ（確かめた）
- D-7. `close` は段 2 の行（ゴミ箱の実体を利用者が消した）でも 200 で、ゴミ箱の一覧から消え `stage` は 2 のまま、`restore` は 409 `already_closed`、Y の `deleted_at` は立ったまま（確かめた。意図どおり）
- D-8. `ids` の形: `[]`・`[""]`・`"d1"`・`null`・`5`・欠落 → 422 `bad_ids`。本文が JSON の文字列 → 422。`reason` 無し → 422 `bad_reason`。無い id の単発 → 404（確かめた）
- D-9. `tools/gui_layout.mjs` の `WANT_STAGE[2]`（記録の「設計の穴 4」）は**並行の担当が 13:41 に直した**（`'2 枚をアプリのゴミ箱へ移しました。'`）。直す前の版で `--screen pending --ids` は 4 幅とも「段 2 の結果の 1 行」だけ NG、直した版で 4 幅とも ok（複製 A、閉じた後の 0 行＋ゴミ箱 7 の状態で）
- D-10. `--screen tags` の 4 件 NG は前提（実データの `tag` 0 行・`asset_tag` 0 行を `mode=ro` で確認）。`tools/gui_layout_seed.py --tags` を複製 A に当てると 4 幅とも ok
- D-11. 閉じた行の `closeable: false`・`undoable: false`、`state: closed`、台帳 `total` 194（確かめた）
- D-12. 片付けの速さ: 194 件 1 回で 61 ms（HTTP、複製 B）、186 件 38 ms（プロセス内）。上限 200 で分けても画面の待ちにはならない

## E. 設計とのずれ（設計が黙っているのに実装が決めた所も）

- E-1. **§1.2 の合格の線が無い**。記録 §4 の 14 件の線を線として扱い、§E-0 に監査者の線を置いた。**記録の 14 件は advance+restore を `live[0]` に先に打つので、まとめての断りが `file_found` 6 ＋ `already_restored` 1 になる**（「194 件 → 187 片付け・7 断り（全部 `file_found`）」の形は、私の複製 B の線 4 で出した）
- E-2. 実装者が決めた点の判定:
  1. 「人も 1 回 200 件」— **妥当**。画面が 200 件ずつ分けるので利用者には見えない。API 直打ちの 422 は部分適用しないので安全側
  2. 「実体」→「ファイル」— **妥当**（§6.1 の規約が正）
  3. 段 3 への直行を作らない — **妥当**（確かめた: 422）
  4. `close` は段を問わない — **条件付き**（C-3: 段 3 の行はタイマーから外してから閉じる）
  5. 片付けた行は戻せない — **変更を勧める**（A-3: 実体が無い間は正しいが、戻った後の出口が要る）
  6. `advance` は台帳の `asset_id` を見ない — **変更を勧める**（A-1: 台帳の `size` と照合して断る。`close` で終われるようにする）
  7. `client_token` を付けない — **妥当**（`closed_at` で冪等、`advance` は `already_stage2` で止まる。確かめた）
  8. 版を上げず `TOP_UP_COLUMNS` — **妥当**（確かめた: 控え 1 つ・列 2 つ・`CHECK`・`missing_top_ups()` 空。複製 D は `Store()` を 2 回開いた（f2 と f3）が `backups/` の `pre-topup-*` は `pre-topup-20261019-133827` の 1 つだけ＝2 度目で控えは増えない）
- E-3. 記録の「設計の穴 1」の読み: 「6 行は古い `asset_id`」は正しいが、**「別のファイルを移さない守りは `(size, mtime_ns)` の照合が持つ」は誤り**（A-1）。「実体が在るのは 7 行」の 7 のうち 6 は**別の画像が在る**（利用者が消した画像の実体は無い）。要望の前提「194 行は実体が無い」とは **193 行が一致する**（1 行だけ本当に実体あり）
- E-4. 申し送り 3（`--screen tags`）は前提で、`gui_layout_seed.py --tags` で緑（D-10）。申し送り 2（`WANT_STAGE[2]`）は並行の担当が直した（D-9）

## F. テストで守れないもの（壊し試験）

数え方: **ソースは触らず** `src/image_reviewer` を `.tmp-audit-redo/p10-audit/mut/src/` に複製して 1 か所壊し、`PYTHONPATH` で前に置いて `tests/test_deletions_advance.py tests/test_deletions.py` を回す（`image_reviewer.__file__` が複製を指すことを最初に確かめた）。**落ちた** ＝ 素の実行で落ちなかったテストが 1 つ以上 FAILED（終了コード 5 の「0 件」と素から落ちる C-2・D-3 の 2 件を数えない）。JS は `apps/gui` と `tools/gui_smoke.mjs` を複製して壊し、そこで node を回す（NG が 1 つ以上）。実装者の `break_tests.py` は `src/` を直に書き換えて終了コードで数えるので使っていない。

素の実行: Python 108 件 passed（`apps/gui` も複製の隣に置いた 2 回目。1 回目は GUI が無く `test_the_new_endpoints_are_guarded` の 404 が 405 になって素から落ちた＝D-3）、JS 395 ok。**32 通りのうち 28 が落ち、4 は落ちない**（`.tmp-audit-redo/p10-audit/mutate.log`・`mutate-rerun.log`）。

| # | 壊す所 | 落ちたテスト（代表） | 判定 |
| --- | --- | --- | --- |
| I1 | 実体の確認を外す | `test_advance_refuses_when_the_file_is_gone` ほか 3 | 落ちた（実装者の 1） |
| I2 | 片付けの判定を外す | `test_close_refuses_while_the_file_is_still_there` ほか 3 | 落ちた |
| I3 | `missing_at` を立て忘れる | `test_advance_moves_the_file_into_the_trash_and_undo_brings_it_back` ほか 3 | 落ちた |
| I4 | `closed_at` を書かない | 12 件 | 落ちた |
| I5 | 段 1 に戻し忘れる | `test_advance_never_overwrites_an_existing_file` | 落ちた |
| I6 | 上限を外す | `test_many_over_the_limit_changes_nothing` | 落ちた |
| I7 | 閉じた行を「最近の削除」から外し忘れる | `test_a_closed_row_leaves_the_pending_list_and_stays_in_the_ledger` ほか 2 | 落ちた |
| I8 | 古い `asset_id` を要求する | `test_advance_works_when_the_ledger_asset_id_is_stale` | 落ちた（**ただしこのテストは A-1 の挙動を正としている**） |
| I9 | 段 3 への直行を許す | `test_advance_refuses_rows_that_are_already_past_stage_1` | 落ちた（422 が消えるだけで、`_advance_one` は常に段 2 に書くので段 3 へは行かない。検査の対象は語彙の検査） |
| A1 | `_restore()` の `_sync_hidden()` を外す | `test_deletions.py` の 7 件（undo で `deleted_at` が消える既存の検査） | 落ちた。**ただし「台帳の枚と現在の枚が違う」形（A-2）は 1 件も見ていない**（`_sync_hidden(X)` を `_sync_hidden(Y)` に替える変異なら落ちない）＝**テストの穴** |
| A2 | `_files_of_row()` から `to_path` を外す | `test_close_refuses_a_file_that_is_in_the_app_trash` | 落ちた |
| A3 | `_files_of_row()` から `hold_path` を外す | **落ちない** | **テストの穴**。段 3 の行（保留に実体）を `close` する検査が無い。複製 D で 409 `file_found` になることは確かめた（C-3） |
| A4 | `_files_of_row()` から `from_path` を外す | **落ちない** | **等価に近い**。`from_path` は段 2・3 で `path`（正規化した鍵）と同じ値、段 1 は NULL。`path` が先に見られるので実害は無い |
| A5 | `close_many` だけ人の検査を外す | `test_the_new_endpoints_are_guarded` | 落ちた（GUI を置いた 2 回目。1 回目は D-3 で隠れた） |
| A6 | `_restore()` の `closed_at` の守りを外す | `test_a_closed_row_cannot_be_restored` | 落ちた |
| A7 | advance の `(size, mtime)` の照合を外す | `test_advance_refuses_when_the_file_changed` | 落ちた（**現在の登録との照合**。台帳の `size` との照合は無い＝A-1） |
| A8 | `_run_many` が失敗を `skipped` に残さない | `test_many_does_not_silently_drop_failures` ほか 2 | 落ちた |
| A9 | `trash()` が閉じた行を出し続ける | `test_close_takes_the_row_out_of_the_trash_too` | 落ちた |
| A10 | `_ids_of` が重複を畳まない | 4 件 | 落ちた |
| A11 | 段 2 の行をもう一度移す | `test_advance_refuses_rows_that_are_already_past_stage_1` | 落ちた |
| A12 | 二重の close が `replayed` を返さず再び書く | `test_close_twice_records_once` ほか 2 | 落ちた |
| A13 | `closed_at` の UPDATE の `WHERE closed_at IS NULL` を外す | **落ちない** | **等価**。`_close_one()` は手前の `_closed_at(row)` で再送を返すので、この WHERE は錠の下では当たらない保険 |
| A14 | 閉じた行の advance の守りを外す | **落ちない** | **テストの穴（A-3 と対）**。閉じた行は実体が無いので `missing_file` で止まるが、**ファイルが戻った閉じた行**（A-3 の形）なら移してしまう。その形の検査が無い |
| A15 | `closeable` が閉じた行でも真 | `test_a_closed_row_leaves_the_pending_list_and_stays_in_the_ledger` | 落ちた |
| A16 | 台帳を書いた後に動かさない | 4 件 | 落ちた |
| J1 | まとめての帯を出さない | gui_smoke NG 4 | 落ちた（実装者の 10） |
| J2 | 段 1 の行に「アプリのゴミ箱へ移す」を出さない | NG 2 | 落ちた |
| J3 | 1 行の片付けの確認を外す | NG 2 | 落ちた |
| J4 | 200 件ずつの分割を外す | NG 2 | 落ちた |
| J5 | まとめての片付けの確認を外す | NG 1 | 落ちた |
| J6 | 断りの数を出さない | NG 1 | 落ちた |
| J7 | 断られた行を選択に残さない | NG 1 | 落ちた |

**実装者の数え方について**: `break_tests.py` は終了コード `!= 0` を「落ちた」とし、`-k` の綴り違い（終了コード 5）を一度「落ちた」に数えた（記録に申告あり）。直した後の 13/13 は私の 9 通り＋JS 4 通りと一致する。**私の 1 回目も素の実行で 1 件落ちていた**（D-3 の 404/405）ので、素から落ちるテストは差し引いて数え、GUI を置いて回し直した（A5 はその回で初めて落ちた）。

**テストで守れていない物（まとめ）**: (1) 台帳の枚と現在の枚が違う行の advance → restore で `deleted_at` が戻ること（A-2。A1 の変異では捕まらない形）(2) 段 3 の行（保留に実体）の `close` が 409 になること（A3）(3) 閉じた行にファイルが戻った形での `advance` / `undo` / 走査（A-3・A14）(4) 画面の二度押し（B-1。`gui_smoke` に「2 連打で POST 1 回」が無い）(5) 台帳の `size` と違うファイルを advance が断ること（A-1。いまはテストが逆を正としている）。

## G. 依頼者への質問（推奨つき。待たずに進めた）

| # | 論点 | 選択肢 | 推奨 |
| --- | --- | --- | --- |
| G-1 | 古い `asset_id` の 6 行をどう扱うか（A-1・C-1） | (a) advance は台帳の `size` と違えば 409 `replaced` で断り、`close` は「この行の画像が無い」として通す／(b) いまのまま Y を移す（A-2 を直す）／(c) 画面に「同じ場所に別の画像があります」と出して何もしない | **(a)**。利用者が消した画像の実体は無いので「片付ける」が意味に合う。画面の結果は「193 件を片付けました。1 件は…」になる |
| G-2 | 片付けた後にファイルが戻ったときの出口（A-3）と Y の幽霊（A-2） | (a) `_should_hide()` と `_live_stage1()` で閉じた行を除き、走査が `missing_at` を戻したとき `deleted_at` を引き直す／(b) 閉じた行の `undo` を「実体が登録と一致するときだけ」許す／(c) 出口を作らない（DB を直すしかない） | **(a)**。走査 1 回で両方が戻り、`undo` の規則を増やさない。(b) は追加で入れてもよい |
| G-3 | まとめて・`close` を `delete_request` に残すか（B-2） | (a) 1 呼び出し 1 行（`count` = requested、`result_json` に `skipped`）／(b) 単発の advance の記録も外して台帳だけにする | **(a)**。誰が 187 行を終わりにしたかが残る |
| G-4 | 閉じた段 3 の行（C-3） | (a) `close` で `purge_at`/`remaining_sec` を NULL に／(b) API も段 3 の行を 409 で断る | **(a)**。画面は段 3 に出していないので API の整合だけ |
| G-5 | 不安定なテスト（C-2） | (a) P10 の修正と一緒に直す／(b) 別の担当 | **(a)**。壊し試験の数え方に影響するので先に |

## H. 確かめられなかったこと・証拠の注記・後始末

- **利用者のアプリ 8790 は監査の間ずっと接続拒否**（13:22・13:45 の `curl /api/health` とも `Could not connect`。`netstat` に 8790 の LISTEN 無し）。依頼の「8790 で動いている」とは違う。止めていないし立ててもいない（立てると実データに `pre-topup-*` と `ALTER` が入るので）。**実データに列を足す起動の試験は複製 A・B・C・C2・D の 5 回で確かめ、実データでは未実行**
- **実データの `closed_at` 列が足される瞬間の控え**は複製で確かめた（`pre-topup-20261019-133026/` ほか）。実データで付く控えの名前は利用者の再起動の時刻になる
- **自分の数え方の誤り 2 件**（線の NG に出たが実装の欠陥ではない）: 複製 B の線「重複を畳めば 200 件」で、実体なしの行は 187 しか無いのに 193 を切り出して 200 と期待した（`requested: 194` は正しく重複を畳んだ結果）。複製 C の線「片付けた行にファイルが戻って走査」で、同じ `sha256` の画像（隠れている枚）を置いたため結果が混ざった → 複製 D で作り直した（A-3）
- **複製 C の 1 回目**は `st_dev_of` の差し替えが効かず（両方 `c:\` で同じ値）advance が通ってしまい、その後の線が崩れた → 複製 C2 で作り直した（§E-0 の線 2 は C2 の値）
- 実装者の `break_tests.py` と `mut_pending.py` は使っていない（`src/` を書き換えるため）。`.tmp-audit-redo/p10-audit/mutate.py` で同じ 9 通りと監査の 16 通りを複製で回した（§F）
- gui_smoke は **395 ok・NG 0・終了コード 0**（最初に 394 と数えたのは、ログの先頭行の BOM で `^ok` を 1 つ取りこぼしたため。壊し試験の素の実行で 395 を確かめた）
- `git status`: 並行の担当が `README.md`・`docs/design.md`・`docs/handoff.md`・`tests/test_data_dir_guard.py`・`tools/gui_layout.mjs` を編集中（私は触っていない）。リポジトリ直下に `tmp*` のフォルダが出ては消える（他の担当のテストの一時物と見た。触っていない）
- 後始末: 複製サーバ 8798（PID 6788、`data_dir` = 複製 A）・8799（PID 8564、複製 B）は報告を書き終えた 13:53:16 に `/api/health` の `data_dir` を確かめてから `taskkill` で止めた（`netstat` に 879x の LISTEN 無し）。8800 は probe が自分で止めた。**8797（他の担当の `doc-p10-replica`）は触っていない**。13:22 には `/api/health` が応えていたが、13:52 には接続拒否になっていた（私は止めていない。その担当が止めたと見た）。
- **この報告の下書き（壊し試験の表が空の 177 行版）が、並行の担当のコミット `9b66601`（13:49:03「テストの一時フォルダをプロセスごとに分ける」）に巻き込まれて HEAD に入っている**。私はコミットしていない。正はこの作業ツリーの版（§F を埋め、§H を足した 220 行前後）。リポジトリ直下の `tmp*` フォルダもそのコミットの変更（pytest の一時フォルダをプロセスごとに分ける）で出る物と分かった
- Orca の知らせ: `p10-audit-start` = msg_38bede447d56（13:22）、`p10-audit-mid` = msg_0ec8bd70a569（13:38。A-1・A-2 と 8790 の観察）、`p10-audit-done` = msg_1e8e4bd9c3ba（13:57）。送り先 run_5bdd431bf57b
- 引用した場所の再確認（13:53、`grep -nF`）: `deletions.py` 889 / 1157 / 1223 / 1238 / 1286 / 1333 / 1343 / 1370 / 1424 / 1544 / 1624 / 1710 / 1789 / 1362、`pending.js` 619 / 889 / 911 / 935、`tests/test_deletions.py` 531、`store.py` 378、`gui_layout.mjs` 1437 — すべて引用した文に当たった（ソースは 10:xx から変わっていない。sha256 で確認）。残した物: `.tmp-audit-redo/p10-audit/`（複製 A・B・C・C2・D と probe-impl、約 1.6 GB。スクリプトとログ）。`%USERPROFILE%` の下には何も作っていない。Chrome のプロファイルは `.tmp-audit-redo/p10-audit/chrome-profile/`
- 実行したコマンドと結果（再現手順）:

```powershell
$env:UV_CACHE_DIR = "C:\work\image-reviwer\.uv-cache"; $env:PYTHONUTF8 = "1"
uv run --no-sync pytest -q                                      # 3 回: 1 failed/546 passed, 1 failed/546 passed, 547 passed（落ちるのは C-2 の既存テスト）
node tools/gui_smoke.mjs                                        # 395 ok, NG 0, すべて ok
.venv\Scripts\python.exe .tmp-audit-redo\p10-audit\mk_replica.py <複製>   # backup()+copy2+貼り替え、全パス列 1,114 値が外を指さない
# 複製サーバ（env 必須）
$env:IMAGE_REVIEWER_DATA="<複製>\data"; $env:IMAGE_REVIEWER_BACKUP_DIR="<複製>\backups"
.venv\Scripts\python.exe -m uvicorn image_reviewer.app:app --host 127.0.0.1 --port 8798
node tools/gui_layout.mjs --base http://127.0.0.1:8798 --count 8 / --screen requests / group --group <id> / asset --ids <id> / tags / jobs / duplicates / pending / library / settings / pending --ids <2 枚>   # 11 本 × 4 幅。tags は seed --tags の後で ok、pending --ids は 13:41 の gui_layout.mjs で ok
.venv\Scripts\python.exe -I .tmp-audit-redo\p10-audit\lines_http.py 8799            # 75 検査（NG 3 = A-2 と自分の誤り 2）
.venv\Scripts\python.exe .tmp-audit-redo\p10-audit\lines_inproc.py <複製 C2>\data <複製 C2>\backups   # 34 検査（NG 2 = A-2 と自分の誤り 1）
.venv\Scripts\python.exe .tmp-audit-redo\p10-audit\f2_closed_file_back.py <複製 D>\data   # A-3
.venv\Scripts\python.exe .tmp-audit-redo\p10-audit\f3_stage3_closed.py <複製 D>\data      # C-3
node .tmp-audit-redo\p10-audit\cdp_double.mjs --base http://127.0.0.1:8798             # B-1（本物の Chrome）
.venv\Scripts\python.exe tools\probe_deletions_advance.py --port 8800 --work <複製>     # 実装者の 14 件: すべて ok
.venv\Scripts\python.exe .tmp-audit-redo\p10-audit\mutate.py                           # §F
.venv\Scripts\python.exe -I .tmp-audit-redo\p10-audit\baseline.py <json>               # 実データ・控え・ソースの署名（開始と終了で比較）
```

**最も重大な 3 件（再掲）**: (1) 古い `asset_id` の 6 行の advance が見えている別の枚 Y を動かす（A-1） (2) 戻しても Y の `deleted_at` が立ったままで永久に隠れる（A-2） (3) 片付けた行はファイルが戻っても戻せない（A-3）。
