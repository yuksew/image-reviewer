# P8-2 監査報告（削除と取り消し。合格の線 4〜7）— 実行込み

- 日付: 2026-10-18（JST 02:10〜02:45）
- 指示書: `docs/p8-audit-brief-p8-2.md`。実装の記録: `docs/p8-2-implementation.md`（194 行。自分で決めた点 18・設計の穴 10・申し送り 10）。実装の指示書: `docs/p8-2-implementation-brief.md`（68 行）。
- 対象（コミット `39e8459`、01:56:59 JST。10 ファイル +3135/-26）: `src/image_reviewer/deletions.py`（1120 行。新規）、`src/image_reviewer/api/deletions.py`（169 行・11 の口。新規）、
  `src/image_reviewer/app.py`（+42/-16。`lifespan` でタイマー・`include_deleted`）、`src/image_reviewer/db.py`（+29。`pending_delete_preview` の 3 列と `delete_request.payload_json` を DDL と `_top_up_v6` の両方に）、
  `src/image_reviewer/store.py`（+4/-1。`deleted_at` を実の値に）、`src/image_reviewer/api/__init__.py`（+5）、`tests/test_deletions.py`（1038 行・42 件。新規）、`tools/probe_p8.py`（+492。`--delete`）。
  監査中に対象の `git status` は空のまま（本報告だけが untracked。`git diff --stat HEAD -- src tests tools` は空）。
- 設計の版: `docs/p8-design.md` 855 行（P8-1 の仕分けを反映した版。P8-2 で変更なし）。元ネタ: `docs/duplicates-deletion-backup.md`（専門文書。§3.1〜§3.5）。
- 環境: `uv run --no-sync`。SQLite 3.53.1・Python 3.14.7。実データ `.data` は `mode=ro` と `backup()` の複製だけ。**画像は 1 枚も動かしていない**（複製は `shutil.copy2` で読むだけ）。
  複製は `.tmp-audit-redo/p8-2-audit/`（`chk/`・`chk2/`・`srv/`・`perf/` とそれぞれの `*-lib/`。スクリプト 8 本・出力 10 本）と、`probe_p8.py --delete --keep` が残した `.tmp-audit-redo/p8probe/delete-*`。
  サーバは複製 `srv/` で **8791**（**`IMAGE_REVIEWER_DATA` を付けて起動**。3 回起動を試み、上がった 2 回はどちらも止めた（1 回は POSIX のパスのまま渡して上がらなかった）。終了後に `netstat` で 0 本）。**8790 は止めていない**（監査の前後で `health` 200・PID 22132・`started_at 2026-10-17T17:01:43Z` のまま。送ったのは `GET /api/health` だけ）。ComfyUI は触っていない。
- 触っていないもの: `src/`・`tools/`・`tests/`・`schemas/`・`docs/`（本報告以外）・`.backup/`・`.data/`（`db.sqlite3` 1,544,192 B・00:07、`-wal` 4,190,072 B・02:01 のまま。
  監査の最初と最後に `mode=ro` で読み直して **v6・23 表・263 枚・判断 3 件・`deleted_at` 0・台帳 0・要求 0・凍結 0・`missing_at` 0・pHash 263・帯 4208**、画像 263 枚の署名（size・mtime_ns）**`fa99ca126c393d5a`・合計 292,561,491 B** で一致）。コミットしていない。
- 回帰: **pytest 367 passed × 3 回**（17.25 / 19.10 / 18.98 s。揺れなし）、**gui_smoke 129 ok / NG 0**、**gui_layout 6 画面すべて ok（各 3 窓）**（複製 8791。比較・要求・まとまり・注記＋タグ・語の一覧・ジョブ）。

## 判定: **合格（条件つき）**

線 4〜7（指示書の番号。設計 §1.2 では線 5〜8）は**私の手で通った**。`probe_p8.py --delete` を複製で回して **18 項目すべて OK**（段 1 → 一覧 263 → 262・`include_deleted` で 263・段 2 → `trash/20261017/c7/…` → `trash/restore` で戻る・段 3 → 保留領域・`remaining_sec 300`・`missing_at` が立って行は在る・すぐ戻す 200・別のファイルを置いて 409 `target_exists` で元のバイト列は無傷・`as_copy` で `.1.png`・壁 +3600 で 300 のまま・単調 +299 で 1・起動し直しても在る・1 周期目は残し 2 周期目で消える・凍結 4 枚 → 差し替え 1 件 `skipped` 3 件削除・失効で 409 `preview_expired`・`last_copy` 409・201 件は 422 で台帳 8 → 8・印の無い root で 409 `stage_not_allowed`・`st_dev` 注入で 409 `cross_volume`・GET は書かない・403 / 422）。
本物のサーバ（8791・複製・窓 40 秒）でも **起動直後と 1 周期目は期限切れの保留を消さず 2 周期目で消え、段 3 の残り時間は実時間で減って窓の後に実削除され、途中の undo は戻る**（`timer_check.py`。起動 +0.0 秒・+36 秒で期限切れの保留が在り、+66 秒で消えて `hold_path` が『(削除済み)』。段 3（窓 40 秒）は +36 秒で残り 11 秒、+66 秒で実削除済み）。`os.rename` は 1 か所（`move_no_clobber`）で、`os.replace` に替えると 3 件落ちる。壊し試験は実装者の 10 通りが**全部落ちる**（C-0）。

条件は 3 つで、いずれも**失敗の道**にある。(1) **`os.rename` の後・台帳の 1 行の前で落ちると、ファイルは移ったのに台帳にも要求にも残らず、登録は「在る」のまま**（B-1）。(2) **取り消しが `target_exists` 以外で失敗した行は `purge_at` が NULL にならず、窓が切れると黙って消える**（専門 §3.4 は「失敗したときはどちらも NULL」。B-2）。(3) **タイマーの実削除が錠を取らないので、窓の最後の瞬間の undo と競合すると、戻したファイルの登録が消える**（B-3）。3 つとも直し方は小さい（G-4・B-2・B-3 に書いた）。

**最も重大な 3 件**

1. **B-1 `rename` と台帳の間で落ちると迷子になる。** `_perform`（`deletions.py:442-444`）は `move_no_clobber` → 取引の順で、取引が失敗すると（`database is locked`・`IntegrityError`・プロセスの停止）ファイルは `trash/` か `pending-delete/<id>/` に移ったまま、`deletion_log` も `delete_request` も残らない（要求は `_drop_request` で消える）。`asset_location.missing_at` も NULL のままなので、一覧には「在る」と出続け、`pending` / `trash` / `ledger` のどこにも出ない。一括では同じ失敗が `skipped: failed` と**穏当に**返るが、ファイルは既に移っている（`checks.py` K3）。「どこへ行ったか必ず追える」がこの段の価値なので、**台帳の行を先に書いてから動かし、動かせなければ行を消す**順に。
2. **B-2 取り消しが `move_failed` で失敗した行は、窓が切れると黙って消える。** `_restore`（`:756`）は `target_exists` のときだけ `_mark_unrestorable` を呼ぶ。元のフォルダが無くなった・別のプロセスが掴んでいる（`WinError 32`）などの `OSError` は 409 `move_failed` で返るが `purge_at` は残り、`state` は `pending` のまま、残り時間が尽きると `_purge_expired` が消す（`checks.py` K15）。専門 §3.4 は「**取り消し自体が失敗したとき（`os.replace` の失敗、別名での復帰の失敗のどちらも）** … `purge_at` を NULL にして自動削除の対象から完全に外す」。`except ReviewError` の条件を `code in ("target_exists", "move_failed")` にするだけ（X30 の形で試験は緑のまま）。
3. **B-3 タイマーの実削除と undo が競合すると、戻したファイルの登録が消える。** `tick` / `_purge_expired`（`:233-295`）は `self._lock` を取らない（`undo` / `purge_now` は取る）。`_purge_expired` が行を SELECT した後・`_remove_hold` の前に undo が完走すると（`_remove_hold` は無い物を消しても例外にしない）、その後の取引が `DELETE FROM asset_location` と `hold_path = '(削除済み)'` を実行する。結果: **ファイルは元の場所に在る・`asset_location` の行は無い・台帳は `restored_at` も立っていて `hold_path` は『削除済み』**（`checks.py` K2。`_remove_hold` を Event で止めて決定的に再現）。窓は 1 回の周期の粒度なので起きうる。`tick` を `with self._lock:` で包む（X31 の形で試験は緑のまま）。

---

## A. 直っていない／設計の約束が成り立たない

- 無し。線 4〜7 は通り、設計 §0.6 の規則 1〜6 は正常系では守られている。

## B. 重大

### B-1 `os.rename` の後・台帳の前で落ちると迷子（最も重大の 1）

- 場所: `deletions.py:413-464`（`_perform`。`:442` で `move_no_clobber`、`:443-449` で取引）・`:574-655`（`bulk_delete`。`except Exception` で `skipped: failed`）。設計 §0.13 L221「ファイル操作は取引の外。取引は台帳の 1 行だけ」（順序は書いていない）・§4.1 L570-580。
- 再現（`uv run --no-sync python -X utf8 .tmp-audit-redo\p8-2-audit\checks.py` の K3。`_write_log` を例外にして「取引が失敗した」形）:
  - 段 2: `RuntimeError`・元の場所に無い・`trash/20261017/..` に在る・`deletion_log` 0 行・`delete_request` の行も消えた・`asset_location.missing_at = NULL`（生きている扱い）・`asset.deleted_at = NULL`。
  - 段 3: 同様に `pending-delete/<id>/` に在り、`pending()` 0 件・`trash()` 0 件。
  - 一括（2 件のうち 2 件目で失敗）: `deleted 1 / skipped [failed]` と 200 で返るが、2 件目のファイルはゴミ箱に移っている。
- 影響: 「在る」と出るのに開けない（走査するまで `missing_at` も立たない）。保留領域に落ちた物は誰も拾わない（`_purge_expired` は台帳の行だけを見る）。
- 推奨: 台帳の 1 行（`hold_path` / `to_path` 込み）を**先に**書き、`os.rename` が失敗したら行を消す（`_drop_request` と同じ形）。これなら落ちても「保留に在る」が台帳に残る。G-4。

### B-2 `move_failed` の行は `purge_at` が残り、窓が切れると黙って消える（最も重大の 2）

- 場所: `deletions.py:716-780`（`_restore`。`:753-758` の `except ReviewError` が `target_exists` だけ）・`:108-125`（`move_no_clobber`。`OSError` → 409 `move_failed`）・`:806`（`_mark_unrestorable`）。専門文書 §3.4「取り消し自体が失敗したとき（`os.replace` の失敗、別名での復帰の失敗の**どちらも**）… `purge_at` を `NULL`。黙って再試行しない」・設計 §0.6-4 L122「失敗したら `purge_at` を `NULL` にして自動削除から外す」・§4.1 L580。
- 再現（`checks.py` K15）: サブフォルダの 1 枚を段 3 → そのフォルダを消す → `undo` → **409 `move_failed`・`purge_at` はそのまま・`pending` の `state` は `pending`** → `remaining_sec` を 0 にして 2 周期 → **保留のファイルが消えた**。
- 影響: 利用者は「戻せませんでした」を見た（409）のに、画面は「あと N 分」のままで、窓が尽きると実体が消える。専門 §3.4 の「利用者が明示的に『消す』を選ぶまで触らない」と反対。
- 推奨: `exc.code in ("target_exists", "move_failed")` で `_mark_unrestorable`。`as_copy` の失敗（`_free_db_name` が 409 を投げる）も同じ。壊し方 X30 は「直した形」で、42 件は緑のまま。

### B-3 タイマーの実削除と `undo` の競合で登録が消える（最も重大の 3）

- 場所: `deletions.py:233-295`（`tick` / `_purge_expired`。`self._lock` を取らない）・`:297-316`（`_remove_hold`。無ければ何もしない）・`:657-668`（`undo` は `with self._lock`）・`:681`（`purge_now` も錠あり）。設計 §8.4 F10「同時」は `client_token` だけ。
- 再現（`checks.py` K2。`_remove_hold` を `threading.Event` で止め、その間に `undo`）: `undo` 200・ファイルは元の場所 → 錠を解く → **`asset_location` 0 行・`hold_path = '(削除済み)'`・`restored_at` あり・`deleted_at = NULL`**。台帳の `state` は `restored`（`restored_at` が先に見られる）。
- 影響: バイト列は失われない（ファイルは元の場所）が、登録が消えて「無い物」になる。走査すれば同じ `sha256` で戻るが、`location_history` には残らない。窓の最後の周期で「戻す」を押した人が踏む。
- 推奨: `tick` の本体を `with self._lock:` で包む（X31 で試験は緑）。`_purge_expired` の行ごとに `restored_at IS NULL` を取引の中でもう一度確かめる（`UPDATE … WHERE restored_at IS NULL` の `rowcount` を見る）形も要る。

## C. 中程度

### C-0 確かめた結果、問題なし（1 行ずつ。実行したもの）

- **線 4〜7（`probe_p8.py --delete --keep`。複製 `.tmp-audit-redo/p8probe/delete-data` ＋ 画像 13 枚の複製）**: 18 項目すべて OK（上の判定に列挙）。0.8 秒。`[--] 実機の D:` は `WinError 5`（実装者と同じ）。
- **本物のサーバ（8791・複製 `srv/`・20 枚・`undo_window_sec = 40`）**: `stale-at-boot2`（`remaining_sec 0`・`purge_at` 過去・保留のファイルあり）を直に入れてから起動 → **起動 +0.0 秒で在る・+36 秒（1 周期目の後）で在る・+66 秒（2 周期目の後）で消えて `hold_path = '(削除済み)'`**。起動 +0.1 秒に段 3 を 2 件（`remaining_sec 40`）→ +36 秒で残り **11**（引かれたのは 29 秒 ≤ 経過 36 秒。引きすぎ無し）→ +66 秒で `pending` から消えて実削除済み。本物の uvicorn のタイマー（`lifespan`）で 30 秒周期が回っている。窓の途中の undo は 2 件目で測る予定だったが、1 件目の行が +66 秒で既に消えていて検査の式が落ちた（`40 - None`）ので、本物のサーバでの段 3 の undo は probe（`TestClient`）とテストの結果に拠る。なお 1 回目の起動は私の検査の開始が遅れ、期限切れの行が 2 周期目で正当に消えた後だった（誤検出。起動直後の測定は 2 回目）
- **守り（8791。`http_check.py`）**: `Host: evil` 403・`Origin: http://evil` 403・`text/plain` 403・`actor: robot` 422・`stage: 4` 422 `bad_stage`・`stage: "x"` 422・`DELETE /api/locations/delete` 405・`limit=0` / `limit=abc` 422・`include_deleted=x` 422・`scope.kind: zzz` 422 `bad_scope`・`state: weird` 422・`purge` 不明 404・エージェントの `purge` / `trash/restore` 403 `human_only`・`undo` 不明 404・本文空 422。
- **GET は 1 バイトも書かない（8791。10 本の GET を 152 ms で）**: **全表の中身の sha256**（行数ではない）・複製の全ファイルの size / mtime（`db.sqlite3`・`-wal` を含む）・画像 20 枚の size / mtime が**前後で同じ**（`pending-deletes` ×2・`deletions` ×2・`deletions/trash`・`trash`・`previews/{id}`・`assets` ×2・`assets/{id}`）。
- **`os.rename`**: `deletions.py` で `os.replace` が出るのは docstring とコメントの 3 行だけで、呼び出しは `move_no_clobber` の `os.rename`（`:118`）の 1 か所（`grep -n 'os\.replace\|os\.rename'`）。`os.replace` に替える壊し方 M1 で **3 件落ちる**（`test_move_no_clobber_refuses_to_overwrite`・`test_undo_never_overwrites…`・`test_the_purge_endpoint_finishes_a_stuck_row`）。`target_exists` のとき元のファイルのバイト列は無傷・保留に残る（probe 線 6b・K1）。
- **5 分の窓**: 壁 +3600 で 300 のまま・単調 +299 で 1（probe 7a）。起動時に消さない・1 周期目も消さない・2 周期目で消える（probe 7c・8791 の実機）。**`purge_at IS NULL` の行は 25 周期（750 秒）回しても `remaining_sec` 300 のまま・ファイルも在る・`state = stuck`・`purge_now` で消せる**（K1。実装者の試験に無かった）。
- **凍結**: 凍結後に足した枚は消えない（probe 8a・テスト）。失効 10 分で 409 `preview_expired`・1 枚も消えない（probe 8b）。同じ凍結の 2 度目は `replayed: true`（8791）。
- **安全**: `last_copy` 409 で台帳にも要求にも行を作らない（probe・テスト）。エージェント 201 枚は 422 `too_many` で台帳 8 → 8（probe。凍結を直に入れて実行の段でも）。印の無い root は段 3 が 409・段 1 は 200（probe）。どの root にも入らない場所も 409（テスト）。`st_dev` 注入で段 2・3 とも 409 `cross_volume`・ファイルは残り・コピーも無い（probe・テスト）。`undo` は自分の分だけ（エージェントの段 3 を人が `undo` → 403 `not_yours`。8791）。`as_copy` はエージェント 403 `human_only`（テスト・8791）。`confirm: "false"` → 422 `confirm_required`・`confirm_last_copy: "false"` → 409 `last_copy`（8791。決定 13 の HTTP 確認）。
- **束の `last_copies`**: 同じ画像の 2 か所が両方凍結に入ると 2 と数える（K18。設計の穴 10）。`assets` の scope は代表の 1 か所だけ（K19）。
- **決定 7（生まれてからの経過で上限）**: 前回の周期から 35 秒・生まれてから 10 秒 → 290（設計の字義なら 265）。再起動をまたいだ行は前回からの経過をそのまま引く（260 → 160）（K4）。
- **`include_deleted`**: 既定で段 1 を出さず `=1` で出る（probe 線 5a: 263 → 262・`=1` で 263。8791 では先の検査で隠した枚が残っていて 258 / 263 の差 5＝隠した枚の数）。段 1 の枚は `/api/duplicates/near` に出ない（P8-1 の C-4 の直しが効いている）。
- **v6 の列**: `_top_up_v6` が `executed_at` / `result_json` / `request_id` / `payload_json` を足す（テスト。M10 で 11 件落ちる）。実データには 02:01 の再起動で**利用者のアプリが**足した（記録どおり。`PRAGMA table_info` で確認）。
- **性能（設計 §7 L681「1,000 件で 1 秒以内」。未計測だった）**: 合成 1,000 枚（`perf1k.py`）で preview `assets` 19 ms・`folder` 101 ms・`query` 10 ms、実行は段 1 0.19 s・段 2 0.66 s・**段 3 1.00 s**（1.0 ms/件。`os.stat`＋`rename`＋取引 1 本）、undo ×1,000 は 0.5 s、台帳 3,000 行の GET 3 本 7 ms。
- **実データ**: 複製の root の印は `illust-authoring = 1`・ComfyUI の置き場 = 0（P8-0 で付けた物）。実データは**場所が 2 つある画像 0・読み取り専用の属性のファイル 0・全 263 枚が `<data>` と同じボリューム**（`st_dev` 一致）。

### C-1 人がエージェントの段 3 を戻せないのに「いま消す」はできる（Q2 の帰結 e と噛み合わない）

- 場所: `deletions.py:716-727`（`_restore` の `check_owner`）・`:681-713`（`purge_now` は所有者を見ない）・`:1062-1078`（`undoable = … and mine`）。設計 §3.4 L557「他人（人を含む）… 403 `not_yours`」・§0.14 L252・§5 L604「自分の削除だけ『戻す』が押せる」。一方で Q2 の帰結 (e) L248「エージェントが消した直後に**人が気づける**ように」。
- 実測（8791）: エージェントの段 3 → 人の `pending-deletes` で `undoable: false`・人の `undo` 403 `not_yours`・**人の `purge` 200（消えた）**。段 2 は `undo` だと 403 で `trash/restore` だと 200（`check_owner=False`）。
- 判定: 実装は設計の字義どおりだが、**人が気づいても戻せず、消すことだけできる**のは Q2 (e) の目的（人の安全網）と逆。設計 §0.14 の「他人（人を含む）の削除を戻せると事故」はエージェントが人の削除を戻す向きの話で、人を縛る根拠は書かれていない。推奨は G-1（人は全部戻せる・エージェントは自分の分だけ。`check_owner = actor != "human"` の 1 行）。

### C-2 読み取り専用のファイルは段 3 の実削除ができず、毎周期やり直し続ける／「いま消す」は 500

- 場所: `deletions.py:267-295`（`_purge_expired`。`OSError` は `log.warning` して次の周期）・`:297-316`（`_remove_hold`。`unlink`）・`:681-713`（`purge_now` は `OSError` を受けない）。
- 再現（K7）: 段 3 → 保留のファイルに `S_IREAD` → 2 周期 → `purged 0`・`state = pending`・ファイルは在る。30 秒ごとに `WinError 5` の警告が出続ける。`purge_now` → `PermissionError`（口なら 500）。
- 影響: 実データは読み取り専用 0 枚なので今は踏まない。他のツールが付けた属性（配布物・バックアップからの復元）で踏む。推奨: `unlink` の前に `os.chmod(path, S_IWRITE)`（自分の保留領域の中だけ）、`purge_now` は `OSError` を 409 に写す。

### C-3 `asset.deleted_at` は資産の単位、削除は場所の単位

- 場所: `deletions.py:860-878`（`_hide_asset` / `_sync_hidden`）・`app.py:221-233`（`include_deleted`）。設計 §4.1 L570-580 は「1 つの `asset_location` について」の表なのに `asset.deleted_at` を立てる。
- 再現（K5）: 場所が 2 つある画像の片方を段 3（`last_copy` ではない）→ `deleted_at` が立ち、生きている複製があるのに一覧から消える。実削除の後も立ったまま。
- 影響: 実データは場所が 2 つある画像が 0 枚なので今は出ない。再リンク（P8-3）や取込で 2 か所になると出る。推奨: `_sync_hidden` の条件を「生きている場所が 0 か」にする（G-7）。

### C-4 段 1・段 2 の一括でも `last_copies > 0` なら `confirm_last_copy` が要る（単発の段 1・2 は要らない）

- 場所: `deletions.py:616-620`（`bulk_delete`。段を見ない）・`:1035-1052`（`_count_last_copies`）・`:430-433`（単発は段 3 だけ `_require_last_copy`）。設計 §3.2 L526「`last_copies > 0` なら要る」・§3.4 L555「最後の 1 つを**段 3 で**」。
- 実測（8791）: 段 1 の凍結 1 枚を実行 → 409 `last_copy`。実データは全枚が最後の 1 つなので、**画面の一括は段 1（印だけ）でも必ず重い確認**になる。推奨: 段 3 のときだけ要求する（単発と揃える）。

### C-5 凍結した `(size, mtime_ns)` は実行時に比べられない

- 場所: `deletions.py:629-633`（`_target` → `_perform` → `_require_file` が DB の行と実ファイルを比べる）・`:1054-1060`（`_item_doc` は `size` / `mtime_ns` を凍結に入れる）。設計 §0.7 L143「実行の直前に 1 件ずつ `(size, mtime_ns)` を再照合」・実装の指示書 §2「凍結した一覧だけ」。
- 再現（K16）: 凍結の `size = 1 / mtime_ns = 1` に書き換えても、DB の行が実ファイルと合えば消える。走査が同じ内容の `touch` を取り込んだ後なら、凍結時と `mtime_ns` が違う枚も消える。
- 判定: 走査は中身が変わると**新しい `asset` に載せ替える**（`store.register`）ので `asset_id` が合わず `not_registered` で止まる。中身が同じ `touch` だけが通るので実害は小さいが、「凍結した一覧」の値を使わないなら入れる意味が無い。凍結の値も比べる（どちらかが違えば `changed`）のが設計の字義。

### C-6 `scan_running`（§3.4）は実装不能ではなく、錠で守れる

- 場所: `app.py:337-341`（`do_scan` は同期・錠なし）・`scan.py:53-125`（`mark_missing` は `seen_keys` に無い行を参照切れにする）。設計 §3.4 L559。
- 判定: `scan` が job を持たないのは事実だが、「走査中は消さない」は `do_scan` が `deletions._lock` を取る（または `Store` に `scanning` の印）だけで満たせる。逆向きの事故もある: 走査が歩き終えた後に `undo` で戻った枚は `seen_keys` に無く、走査の最後の `mark_missing` で参照切れになる。推奨 G-2。

## D. 軽微

- **D-1 `_remove_hold` に保留領域そのものを渡すと丸ごと消す**（`deletions.py:306`。`is_under(root, root)` は True・`is_dir()` なら `rmtree`）。K8: 他の保留 2 件のファイルごと消え、その後の `undo` は 409 `restore_failed`。台帳の `hold_path` を書き換える経路が要るので事故ではないが、「最後の砦」なら `hold_path == root` と `is_dir()` を断る。
- **D-2 段 3 の preview は印の無い置き場を数えない**（`:543-572`）。K17: 2 枚「消える」と出て実行で 1 枚 `stage_not_allowed`。`last_copies` と同じように `not_allowed` を返す。
- **D-3 ゴミ箱の日付は UTC**（`:474` `self.clock.now()[:10]`）。JST 02:30 の削除が `trash/20261017/`。probe の実行でも `20261017`。画面に出すなら現地日付。
- **D-4 台帳の `display_path` が正規化した鍵**（`:1068` `"display_path": row["path"]`）。`c:\work\…\01m4z0kj-….png`（小文字）で、登録の表記と違う。凍結の `items` は両方持っている（点検 D6）ので、台帳も `asset_location.display_path` を引く。
- **D-5 `GET /api/deletions/previews/{id}` は `actor` を見ない**（`api/deletions.py:116`）。`robot` で 200（他の口は 422）。
- **D-6 `stage: true` が段 1 として通る**（`:158-167`。`int(True) = 1`）。`3.9` も 3。8791 で 200・`stage 1`。`isinstance(stage, bool)` を先に断る。
- **D-7 断った後に空のフォルダが残る**（`:479` の `mkdir` が `same_volume` の前）。K13: `cross_volume` 409 の後に `pending-delete/<id>/`（空）。段 2 は `trash/<日付>/<sha2>/`。
- **D-8 `client_token` の要求の行が `result_json` 無しで残ると、同じ token は永久に 409 `client_token_in_progress`**（`:912-934`）。K14。プロセスが落ちた場合に起きる（起動時に `result_json IS NULL` の古い行を落とすか、`at` が古ければ再送を許す）。
- **D-9 段 3 の preview の `frees.at` が凍結の失効時刻**（`:571` `at=expires_at`）。「5 分の窓が過ぎた時点で空きます」の時刻として 10 分後が出る。実行前は未定なので `null` が正直。
- **D-10 `PREVIEW_KEEP_SEC = 86400`（`:65`）は未使用**。決定 2 の「掃除するなら 1 日後」の置き場だけある。
- **D-11 `int(delta)` の切り捨てで窓が周期ごとに最大 1 秒延びる**（`:257`・`:264`）。K4: 30.9 秒の周期で 30 しか引かない。記録の「窓が延びる側には倒れない」は決定 7 の上限の話で、切り捨ては延びる側。害は無い（1 周期 1 秒未満）。
- **D-12 段 1 を 2 回 → 1 回戻しても隠れたまま**（K21。`_sync_hidden` が生きた行を数える）。画面で「戻した」のに出てこない形になる。
- **D-13 `path` が空だと 409 `not_registered`**（K22・8791 の本文空は 422 `bad_stage` が先）。入力の欠落は 422 が揃う。
- **D-14 `folder` の scope は置き場の制限が無い**（K23: `C:\` で生きている全枚 261 件が凍結に入る）。人なら上限なし。エージェントは 200 で止まるが、**単発の `POST /api/locations/delete` を 1,000 回呼ぶ上限は無い**（§0.13 L219「1 回の要求で」の字義どおり）。
- **D-15 線の番号**: 指示書は「線 4〜7」、設計 §1.2 と probe は「線 5〜8」（線 4 は P8-1 の除外と解除）。本報告は指示書の番号で書き、probe の表示は 5〜8。
- **D-16 設計 §0.6-1 L109 は「`os.replace` で移す」、§0.6-4 L116 は「`os.rename`」**。実装は両方 `os.rename`（安全側）。§0.6-1 と §0.13 L221 の `os.replace` を直す。
- **D-17 `tests/test_deletions.py` の `client` fixture は `lifespan` でタイマーを 30 秒周期で張る**（daemon）。テストは数秒で終わるので揺れないが、`test_get_never_writes` はサービス直呼びで時計を注入しており、HTTP 側の GET-無書き込みは `remaining_sec` の無い状態でしか見ていない。

## E. 設計とのずれ（実装が決めた所を含む）

実装者の「自分で決めた点」18 行の判定:

| # | 決めたこと | 判定 |
| --- | --- | --- |
| 1 | `pending_delete_preview` に 3 列・`delete_request.payload_json`（DDL と `_top_up_v6`） | 妥当。§2.1 L470-483 の DDL を直す（設計の穴 1・2）。M10 で 11 件落ちる |
| 2 | 失効した凍結を自動で消さない（§4.3 L595 と違う） | 妥当。線 8 の 409 を守る方が大事。`PREVIEW_KEEP_SEC` が未使用（D-10）。G-5 |
| 3 | 一括では印なし・別ボリューム・中身の変化を `skipped` にして残りを消す | 妥当（§3.2 の 2）。preview が印なしを数えない（D-2） |
| 4 | `POST /api/deletions/{id}/purge` を足した | 妥当（§5 L604 の「いま消す」の押し先）。**所有者を見ない**（C-1）・`OSError` が 500（C-2）。§3.2 に 1 行要る |
| 5 | `undo` は段 1〜3 に効く・`trash/restore` は人だけの別名 | **ずれ**。エージェントは自分の段 2 を `undo` で戻せる（K12）ので「ゴミ箱からの復帰は人だけ」（§3.2 L530）が別名で空く。害は小さい（戻す向き）が、`undo` を段 3 に限るか、段 2 の `undo` にも `human` を掛ける |
| 6 | `target_exists` でも `purge_at` を NULL | 妥当（§0.6-4）。**`move_failed` が抜けている**（B-2） |
| 7 | 窓の引き方を「生まれてからの経過」で上限 | 妥当（実機で 35 秒に 60 秒は本当に起きる形）。**試験が無い**（X2 緑。F）。§0.6-2 L111 を直す |
| 8 | どの root にも入らない場所は段 3 を許さない | 妥当（安全側）。テストあり |
| 9 | `as_copy` で `asset_location` を付け替える | 妥当。DB 側の衝突の試験が無い（X5 緑） |
| 10 | `client_token` は要求の単位・`payload_json` で `client_token_conflict` | 妥当（§0.16 A2・P6 と同じ）。落ちた要求の行が永久に `in_progress`（D-8） |
| 11 | 設計と指示書の両方の名前を同じ処理に | 妥当 |
| 12 | `asset_id` 無しでもパスで当たる | 妥当（鍵は `path`） |
| 13 | 確認の欄は文字列でも安全側（`_flag`） | 妥当。8791 で確認。単体の試験は無い（X6 緑） |
| 14 | 同じ `asset_id` は 1 件に畳む | 妥当。試験は無い（X4 緑） |
| 15 | `query` は `q` / `state` / `tag` / `known` の部分集合 | 妥当（P8-5 で揃える） |
| 16 | `GET /api/assets` に `include_deleted`・`store` の `deleted_at` を実の値に | 妥当（§4.1 L576・§8.1 の 25）。資産の単位の穴は C-3 |
| 17 | `GET /api/deletions` の `limit` 1〜1000 | 妥当 |
| 18 | `GET /api/deletions/previews/{id}` | 妥当。`actor` を見ない（D-5） |

申し送りの判定: 1（`allow-stage3` の口が無い）は §3.3 L541 が P8-4 の表に置いているので **P8-4 まで許せる**（G-3）。2（`scan_running` 実装不能）は**錠で満たせる**（C-6・G-2）。3（人がエージェントの削除を戻せない）は **Q2 (e) と噛み合わない**（C-1・G-1）。4（`purge_at` は目安）は妥当。5（ゴミ箱の掃除は未実装）は Q7 どおり。6（D: は `WinError 5`）は私も同じ。7（1,000 件の性能）は C-0 で実測した（段 3 で 1.00 s）。8・9・10 は妥当。

設計の穴 10 行の判定: 1・2（§2.1 と §4.3 の食い違い）・3（「いま消す」の口）・5（`scan_running`）・6（`deleted_at` 3 か所）・7（§0.6-2 の引きすぎ）・8（戻す口）・9（§3.3 の置き場）・10（束の `last_copies`）は本当。4（`not_yours` と Q2 e）は本当で、解は G-1。

そのほかのずれ:

- **E-1 専門 §3.4「失敗したらどちらも NULL」→ `target_exists` だけ**（B-2）。
- **E-2 §0.13 L221「取引は台帳の 1 行」の順序が書かれておらず、実装は移動 → 台帳**（B-1）。
- **E-3 §3.4 L557 `not_yours` の「人を含む」と §0.14 (e)**（C-1）。
- **E-4 §3.4 L559 `scan_running` 未実装**（C-6）。
- **E-5 §3.3 L541 `allow-stage3` の口 無し**（申し送り 1。P8-4 の表にある）。
- **E-6 §0.6-1 L109 `os.replace` → 実装は `os.rename`**（D-16。安全側）。
- **E-7 §4.3 L595 失効した行の掃除 無し**（決定 2）。
- **E-8 §0.7 L143 の再照合が凍結の値を使わない**（C-5）。
- **E-9 §3.2 L530 ゴミ箱の復帰は人だけ → `undo` の別名でエージェントも**（決定 5）。
- **E-10 §4.1 の表は場所の単位、`deleted_at` は資産の単位**（C-3）。
- **E-11 §3.2 L526 の `last_copies` が段 1・2 の一括にも効く**（C-4）。

## F. テストで守れないもの（`mutate_p82.py`。24 通り、ソースは触らず `-p` で差し替え。`tests/test_deletions.py` ＋ `tests/test_db.py` 74 件）

| # | 壊し方 | 結果 |
| --- | --- | --- |
| M1 | `os.rename` → `os.replace` | **落ちる**（3 件） |
| M2 | 窓を壁時計で数える（`purge_at <= now` で 0） | **落ちる**（2 件） |
| M3 | 凍結を外す（実行時に `scope` を評価し直す） | **落ちる**（2 件。フォルダの試験＋上限） |
| M4 | 起動直後の 1 回でも消す | **落ちる**（1 件） |
| M5 | `last_copy` を見ない（単発） | **落ちる**（1 件） |
| M6 | `allow_stage3` を無視 | **落ちる**（2 件） |
| M7 | 上限を部分適用 | **落ちる**（1 件） |
| M8 | `normalize_path` → `str` | **落ちる**（26 件。鍵が全部外れる） |
| M9 | `(size, mtime_ns)` の再照合を外す | **落ちる**（2 件） |
| M10 | v6 の列を足さない | **落ちる**（11 件） |
| X1 | `purge_at IS NULL`（stuck）の行も自動で消す | **緑**（F-1） |
| X2 | 決定 7 の上限を外す（設計の字義） | **緑**（F-2） |
| X3 | `last_copies` を束でなく 1 枚ずつ | **緑**（F-3） |
| X4 | `assets` の同じ id を畳まない | **緑**（F-4） |
| X5 | `as_copy` の別名を DB を見ずに選ぶ | **緑**（F-5） |
| X6 | `_flag` を `bool()` に | **緑**（F-6。HTTP の試験が文字列を送らない） |
| X7 | `same_volume` を常に True | 落ちる（1 件） |
| X8 | `undo` の錠を外す | **緑**（F-7。同時の試験は `delete` だけ） |
| X11 | `target_exists` で `purge_at` を NULL にしない | 落ちる（2 件） |
| X15 | `client_token` の再送を見ない | 落ちる（2 件） |
| X25 | `start()` で期限切れを消す（起動時に消す） | **緑**（F-8。「起動時に消さない」の試験は `DeletionService()` を作るだけで `start()` を呼ばない） |
| X28 | 実行の段のエージェント上限を外す | 落ちる（1 件） |
| X30 | （直し方）`move_failed` でも `purge_at` を NULL | 緑（直しても壊れない） |
| X31 | （直し方）`tick` が `self._lock` を取る | 緑（直しても壊れない） |

試験の無い振る舞い（上の緑 8 つに加えて）: **B-1**（移動の後の取引の失敗）・**B-2**（`move_failed` の行）・**B-3**（undo とタイマーの競合）・C-2（読み取り専用）・C-3（場所が 2 つ）・C-4（段 1 の一括の `last_copy`）・D-5・D-6。「凍結を外すテストが最初は穴を隠していた」という申告は本当で、いまの M3 はフォルダの形で落ちる。

## G. 依頼者への質問（推奨つき。待たずに推奨で進めてよい）

- **G-1 人がエージェントの削除を戻せるか**（申し送り 3・C-1）。推奨: **人は誰の削除でも戻せる・エージェントは自分の分だけ**（`_restore` の `check_owner` を `actor != "human"` に）。`purge_now` も同じ向きに揃え、`undoable` は人なら常に真。設計 §3.4 L557 の「（人を含む）」を外し、§0.14 (f) に 1 行足す。
- **G-2 `scan_running` の代わり**（申し送り 2・C-6）。推奨: `do_scan` と CLI の `scan` が **`DeletionService._lock` を取る**（走査中は削除・取り消しが待つ）。job 化は要らない。
- **G-3 `allow-stage3` の口**（申し送り 1）。推奨: P8-4 の表のまま。ただし `scan` で新しい root が増えたとき印なしになることを README に 1 行（実データは `illust-authoring` に印あり）。
- **G-4 迷子を無くす順序**（B-1）。推奨: 台帳の行（`hold_path` / `to_path` 込み・`restored_at NULL`）を先に書き、`os.rename` が失敗したら行を消す。起動時に `pending-delete/` の中で台帳に無いフォルダがあれば「拾い物」として `GET /api/pending-deletes` に出す（消さない）。
- **G-5 失効した凍結の掃除**（決定 2）。推奨: `PREVIEW_KEEP_SEC`（1 日）を使い、タイマーで `expires_at < now - 1 日` かつ未実行の行だけ消す。線 8 の 409 は 10 分〜1 日の間は守られる。
- **G-6 読み取り専用のファイル**（C-2）。推奨: 保留領域の中だけ `unlink` の前に `S_IWRITE` を付ける。`purge_now` の `OSError` は 409 `purge_failed`。
- **G-7 `deleted_at` の単位**（C-3）。推奨: `_sync_hidden` を「生きている `asset_location` が 0 で、かつ生きた削除の行がある」で立てる。再リンク（P8-3）の前に決める。

## H. 確かめられなかったこと・注記・後始末

- **実機の別ボリューム（D:）**: `D:\` への書き込みが `WinError 5`（実装者と同じ）。`st_dev` の注入だけ。なお Windows の `os.rename`（`MoveFileExW` を `MOVEFILE_COPY_ALLOWED` 無しで呼ぶ）は別ボリュームへは失敗するはずで、`same_volume` の検査が無くても `move_failed` で止まりコピーにはならないと読めるが、**この環境では確かめられない**（書けるボリュームが C: だけ）。
- **本物のサーバで壁時計を進める**ことはできない（`FakeClock` の試験と probe で確認）。
- **走査との同時実行**は再現していない（C-6 は読みと `mark_missing` の仕組みから）。
- **8790 のタイマー**: 実データに段 3 の行が 0 なので `tick` は何も書かない。監査の前後で `.data/db.sqlite3-wal` の mtime は 02:01 のまま（起動時の `_top_up_v6` の列追加が最後の書き込み）。
- **実データの列追加は利用者のアプリが 02:01 に行った**（`pending_delete_preview` 12 列・`delete_request` 8 列を `PRAGMA table_info` で確認）。記録どおりで、私は書いていない。
- **実装者の `.tmp-audit-redo/p8_2_mutants.py` は `src/` を書き換えて戻す形**（ハッシュで戻りを確かめている）。8790 は `.exe` から読んだ後なので影響は無かったが、`--reload` で動くサーバがあれば再起動する。私は `-p` の plugin で代えた。
- **実行したコマンド**（`$env:UV_CACHE_DIR = "C:\work\image-reviwer\.uv-cache"`、`cd C:\work\image-reviwer`）:
  - `uv run --no-sync python -X utf8 tools/probe_p8.py --delete --keep`（線 4〜7。複製は `.tmp-audit-redo/p8probe/delete-*`）
  - `uv run --no-sync python -X utf8 .tmp-audit-redo\p8-2-audit\checks.py`（K1〜K23。複製 `chk/`・`chk2/`）
  - `bash .tmp-audit-redo/p8-2-audit/mut_run.sh`（24 通り。`PYTHONPATH` に plugin、`P8X=<名前> uv run --no-sync pytest -q -p mutate_p82 tests/test_deletions.py tests/test_db.py`）
  - `uv run --no-sync python -X utf8 .tmp-audit-redo\p8-2-audit\replica.py`（複製 `srv/` 20 枚＋まとまり＋語 5 つ）→ `IMAGE_REVIEWER_DATA=<srv> uv run --no-sync image-reviewer serve --port 8791` → `timer_check.py` → `http_check.py` → `node tools/gui_layout.mjs --base http://127.0.0.1:8791 …`（6 画面）→ 停止（`srv_run.sh`）
  - `uv run --no-sync python -X utf8 .tmp-audit-redo\p8-2-audit\perf1k.py`（1,000 枚）
  - `uv run --no-sync pytest -q -p no:cacheprovider` ×3・`node tools/gui_smoke.mjs`
- 一時物: `.tmp-audit-redo/p8-2-audit/`（複製 `chk/ chk-lib/ chk2/ chk2-lib/ chk-noflag/ srv/ srv-lib/ srv-noflag/ perf/ perf-lib/`・スクリプト `replica.py checks.py mutate_p82.py mut_run.sh http_check.py timer_check.py srv_run.sh perf1k.py`・出力 `probe.out.txt checks.out.txt mutations.out.txt http_check.out.txt http_check2.out.txt timer_check.out.txt layout.out.txt smoke.out.txt pytest.out.txt perf1k.out.txt server*.log`）と `.tmp-audit-redo/p8probe/delete-*`。消して構わない。

## 最も重大な 3 件（再掲）

1. **B-1** `os.rename` の後・台帳の 1 行の前で落ちると、ファイルは移ったまま台帳にも要求にも残らず、登録は「在る」のまま（一括は `skipped: failed` で穏当に返る）。台帳を先に書く順に。
2. **B-2** 取り消しが `move_failed` で失敗した行は `purge_at` が残り、`state: pending` のまま窓が切れると黙って消える。専門 §3.4 は「失敗したときはどちらも NULL」。条件を 1 つ足す。
3. **B-3** `tick` / `_purge_expired` が錠を取らず、窓の最後の周期の `undo` と競合すると、戻したファイルの `asset_location` が消え台帳は『削除済み』になる。`tick` を `self._lock` で包む。
