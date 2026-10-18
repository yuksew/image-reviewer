# P8-4 の直しの再確認（バックアップと復元。B-1・C-1〜C-3・D 13 件・G 9 件）— 実行込み

- 日付: 2026-10-18（JST 08:40〜09:40）
- 元の監査: `docs/p8-4-audit-report.md`（合格（条件つき）。条件は B-1）。仕分け: `docs/p8-4-audit-triage.md`（新規 15 件＋書き換え 1 件の試験、18/18 の壊し試験、実データの前後の表）。
- 対象（コミット `1005ad7`・`1d4616c`。`7c32465` からの差分 30 ファイル +3048/-303、うち P8-4 の直しは 13 ファイル +1398/-227）: `src/image_reviewer/backup.py`（1578 行。`check_snapshot_db`・`_refuse_if_broken`・`_mark_broken`・`check_backup_target`・`replace_dir`・`backup_before_shape_change`・`_write_db_only`・`_clear_error_if_fixed`・`restore` の順序と sha256）、`db.py`（`TOP_UP_COLUMNS`・`missing_top_ups`）、`store.py`（開く前の `pre-topup-*`）、`review.py`（読む 3 本を `locked()`）、`app.py`（`_db_gate` は `/api/` だけ・`sqlite_error_handler`・`__getattr__` で `app` を遅延）、`api/__init__.py`、`api/backup.py`（錠の下・`?full=0`）、`cli.py`（`--factory`・sha256 の 1 行・退避先）、`tests/test_backup.py`（60 件）、`tests/conftest.py`（収集の前に env）、`tools/probe_p8.py`、`docs/p8-design.md`（§0.20）。
- 環境: `uv run --no-sync`。実データ `.data` は `mode=ro` だけ（複製は `backup()`）。**画像は 1 枚も動かしていない**。複製と置き場は `.tmp-audit-redo/p8-recheck/`（`w/`・`backups/`）と P8-4 の `.tmp-audit-redo/p8-4-audit/srv`（`prep_srv4.py` で作り直す）。バックアップの置き場は前回と同じく **repo 内**（sandbox が `%USERPROFILE%` の下に書かせない。H）。
  複製のサーバは **8793**（`IMAGE_REVIEWER_DATA` と `IMAGE_REVIEWER_BACKUP_DIR` を付けて。止める前に `/api/health` の `data_dir` が自分の複製かを確かめる形。8791 / 8795 の他の担当のサーバには触っていない）。**8790 は止めていない**（PID 54920・08:38:25 起動＝直した P8-4 のコード）。ComfyUI は触っていない。コミットしていない。
- 実データ: 最初と最後に `mode=ro` で **v6・24 表・263 枚・判断 3 件・`deleted_at` 0・台帳 0**、画像 263 枚の署名 **`fa99ca126c393d5a`・292,561,491 B**（前回と同じ）。`db.sqlite3` 00:07 のまま。`.backup/` は **8 フォルダ**（G-9 の `pre-p8-4-20261017-232148` が増えた。消していない）。`%USERPROFILE%\image-reviewer-backups` は**無い**（下の B-1 を見よ）。
- 回帰: **pytest 472 passed ×3**（32.4 / 32.3 / 32.3 s）、**gui_smoke すべて ok（232 ok / NG 0）**、**gui_layout 10 本すべて ok（8 画面＋`pending --ids`＋library。各 3 窓）**、`check_contract_p8.py` は前回のまま（OK 24）。壊し試験 **30 通り中 29 通りで狙ったテストが落ちる**（残り 1 つは私の plugin が届かない形。F）。

## 判定: **合格（条件つき）。条件は実機の B-1'（8790 が日次を 1 つ取れたことを `GET /api/backup` の `count` で確かめる）**

コードの直しは全部、実行で直っている（下）。条件は運用の側: 立て直した 8790 が sandbox の中に居て、既定の置き場に書けず、控えが 0 個のまま。

直しは全部、実行で確かめた。**B-1**: 健全な日次を 7 日分取ってから走ったまま 300 ページ目を潰し（ページキャッシュは `shrink_memory`＋`cache_size=1` で捨てる）、7 日分 `tick` → 1 回目は `failed`（`DB が壊れています（quick_check: *** in database main ***…）`）、以後は `read_only`、**写しは 1 つも採用されず健全な 7 世代がそのまま**、`last_error` に残り、`store.read_only` が立って書き込みは 503、一時フォルダは残らない（R1）。写しだけの検査も `quick_check → integrity_check` の 2 段で、300 ページ目を潰した写しは落ちる（R1e/f）。**C-1**: 1 バイト変えた写しは 409 `bad_backup`（`expected` / `actual` つき）で `<data>` は変わらず、`--force` では進んで結果に `sha256.ok=False`、CLI は違えば終了 2 の 1 行・合えば「sha256 一致」と退避先の 1 行（R2）。**C-2**: 複製のサーバ（8793）が DB を掴んだまま CLI の `restore` → **終了 2・stderr 1 行「DB を置き換えられません（アプリを止めてから戻してください）: [WinError 5] …」**・トレースバック無し・`<data>` の全表 sha256 と全ファイルが前後で同じ・WAL は残る・`.tmp-restore-db-*` も残らない（S6）。ライブラリでも、別の接続が掴んでいるときは `os.replace` で 409 になり **`unlink` の文（「古い WAL を消せません」）には行かない**（R11）。**C-3**: 2 ページ目・300 ページ目・版 7・控え失敗の各形で `GET /api/groups` と `/api/reviews` が 200、2 ページ目の形で台帳 3 本（`/api/pending-deletes`・`/api/deletions`・`/api/deletions/trash`）は **503 `read_only`・`details.reason: malformed`**（500 は 0 本。S5）。**G-8**: `IMAGE_REVIEWER_DATA` を外して `import image_reviewer.app` → `'app' in vars(m)` は `False`、**実データの全ファイル（`db.sqlite3`・`-wal`・`-shm`・`store.json` ×2）の大きさと mtime が前後で同じ**、`%USERPROFILE%` の置き場も作られない（R9。複製で `m.app` を触ったときだけ `create_app` が走る）。**G-9**: `.backup/pre-p8-4-20261017-232148/` は manifest の sha256 と実物が一致・263 枚・判断 3 件・`integrity_check ok`・契約に合う（R10）。D は下の C-0。

**ただし実機で 1 件（B-1'）**: 直した P8-4 のコードで立て直した 8790 の `GET /api/backup` が **`last_error: [WinError 5] アクセスが拒否されました: 'C:\Users\yukse\image-reviewer-backups'`・`count 0`・`today_done false`** を返している（08:38:25 に起動してから `ticks` 5 で全部失敗）。8790 の親は **dsh（DeepSeek）の PowerShell → node**（`Get-CimInstance` の親の鎖）＝**エージェントの sandbox の中で立っている**ので、私の環境と同じく `%USERPROFILE%` の下に書けない。**実装者の仕分けは「私の環境でも同じ（sandbox）」と書きながら、立て直した 8790 がその環境であることに結び付けていない。** 利用者の困りごと「取っていない（不安）」は、**いまの実機では直っていない**（D-10 の「立て直した瞬間に日次が出来る」は起きていない）。推奨 G-1。

**最も重大な 3 件**

1. **B-1' 実機の 8790 は日次を 1 つも取れていない。** `GET /api/backup`（8790）: `backup_dir` は設定の `C:\Users\yukse\image-reviewer-backups`、`last_error` は `WinError 5`、`last_error_at 2026-10-17T23:38:25Z`（起動の瞬間）、`ticks 5`、`snapshots []`。原因は sandbox（8790 は dsh の子プロセス）。コードの誤りではなく**運用の形**だが、失敗を `last_error` に残す直し（D-4）が働いているおかげで**番号で見える**。推奨: (a) 利用者が自分の端末（sandbox の外）で `uv run --no-sync image-reviewer serve --port 8790` を立てる、または (b) `PATCH /api/settings` で sandbox が書ける置き場（`<data>` の外・`.backup/` の隣など。`C:\work` 直下も sandbox は書けない＝私の実測）に向ける。(b) は「実データの隣」になるので、設計 §0.12-2 の趣旨（`<data>` を失っても残る）に照らすと (a) が本筋。P8-5 の画面は `last_error` を**上部バーで**出すこと。
2. （無し。B-1・C-1〜C-3 は直っている）
3. （無し）

---

## A. 直っていない

- 無し。

## B. 重大

### B-1' 実機の 8790 は日次を取れていない（sandbox の中で立っているため）

- 場所: 8790 の `GET /api/backup`（`last_error` / `snapshots` / `ticks`。監査の終わり 09:35 の時点で `ticks 38`・`count 0`・`last_error_at` は起動の瞬間のまま＝D-4 の直しが効いている）。親プロセスの鎖: `python.exe(54920) ← python.exe ← image-reviewer.exe ← uv.exe ← powershell.exe(-NonInteractive) ← node.exe（@deepseek-ai/dsh）`。設定 `settings.backup_dir = C:\Users\yukse\image-reviewer-backups`（`_seed_settings` の既定）。
- 実測: 私の sandbox から `%USERPROFILE%` の直下・`Documents`・`AppData\Local`・`Downloads`・`.claude`・`C:\work` 直下の 7 か所で `mkdir` が WinError 5（前回の H と今回の `checks5` の前）。8790 も同じ結果を `last_error` に残している。
- 判定: **直しは正しく動いている（失敗が見える）が、利用者の控えは 0 個**。D-10「立て直した瞬間に日次が出来る」は実機では起きていない。推奨 G-1。

## C. 中程度

### C-0 確かめた結果、直っている（指摘ごとに 1 行。実行したもの）

- **B-1**（写しの検査・7 世代・read_only）: R1a〜f（`checks5.py`）。`tick` の 1 回目 `failed`、以後 `read_only`、7 世代とも健全なまま、`last_error`、`store.read_only`、`transaction()` 503、`.tmp-*` 無し。
- **C-1**（sha256）: R2a〜e。409 `bad_backup`・`details.expected ≠ actual`・`<data>` 不変・`--force` で採用した DB の sha が `actual` と一致・CLI の 1 行。
- **C-2**（掴まれた `restore`）: S6a〜c（8793 を立てたまま）・R11（別の接続で掴む）。409 の 1 行・`unlink` に行かない・`<data>` 不変・一時ファイル無し。
- **C-3**（読み取り専用の読み）: S5c/S5g（page2 / page300 / ahead / oldbad）。`/api/groups` `/api/reviews` 200、台帳 3 本は 503 `read_only`・`malformed`、500 は 0 本。
- **D-1**（GUI）: S5d。先頭 4 KB の形でも `/` と `/app.js` は 200、API は 503。
- **D-2**（`pre-topup-*`）: R4a〜f。足りない列が 5 つある v6（`.backup/pre-p8-2-restart` の DB）を `Store` で開くと `pre-topup-20261018-084455/`（manifest・263 枚・判断 3 件・**ALTER 前の形**）を取ってから `ALTER`、2 回目は取らない、`prune(keep=0)` でも残る、置き場がファイルなら**開いた上で** `last_error`「表の形を変える前の控えを取れませんでした」。実データは `missing_top_ups` が空（次の起動で取られない）。
- **D-3**（退避先）: R2e の CLI の 1 行「元の DB を退避しました: …（バックアップのフォルダの隣。…）」。
- **D-4**（同じ失敗は書かない）: R5a（3 周期で `last_error_at` が最初の時刻のまま）・S4f（サーバで 31 秒後も同じ）。8790 でも `ticks 5` で `last_error_at` は起動の瞬間 1 つ。
- **D-5**（直れば消す）: R5c（`already` の `tick` で消え、`.tmp-write-probe-*` が残らない）・R5d（書けないうちは消さない）・S4g（サーバで `today_done` のまま消える）。
- **D-6**（`prunable`・`out`）: R5e（manifest 付き True・無い日付名 False）・R5f（`out` に 9 個取っても消えない）・S2（`pruned: []`）。
- **D-7**（錠と `?full=0`）: S5。`full=1` は `integrity_check ok`、`full=0` は `None`＋注記、`full=x` は 422 `bad_full`。錠の下で回すことはコードで確認（`api/backup.py` `with store.locked()`）。
- **D-8**（WAL チェックポイント）: 実装しない判断は妥当（終了時は SQLite が畳む。日次で畳むと「WAL にしか無い行」の検査の前提が壊れる）。設計の文を直した側で問題なし。
- **D-9**（5 つ）: 設計 §1.2 線 10・§0.12-1 を 5 つに直してある。
- **D-10**: 下の B-1'（**実機では日次が出来ていない**）。
- **D-11**（形の検査）: R5g/h（相対・無いドライブ・ファイルは 422）・S2b（`POST /api/backup` の `out`）・S4b〜d（`PATCH`）。
- **D-12**（`state()` の錠）: R5i（`_lock` を 1.5 秒握ったまま `state()` が 1 ms で返る）。
- **D-13 / G-8**（import）: R9a/b。`cmd_serve` は `--factory`（コード）。`conftest.py` の `pytest_configure` が `setdefault` で向ける（コード）。
- **G-9**: R10a/b。
- **E-1〜E-7**: 設計 `p8-design.md` §0.20・§0.12・§1.2・§3.3・§3.4・§6.2・§8.1（72〜87）を読み、実装と合う。
- **F**: 新規 15 件＋書き換え 1 件（`test_a_broken_source_does_not_replace_the_seven_healthy_snapshots`・`test_restore_refuses_a_snapshot_whose_bytes_changed`・`test_a_locked_db_is_reported_not_crashed`（本物の錠）・`test_the_stale_wal_is_removed_only_after_the_db_is_in_place`・`test_the_read_endpoints_still_read_when_the_db_is_broken`・`test_a_broken_ledger_page_says_503_not_500`・`test_the_gui_is_served_even_when_the_db_cannot_be_opened`・`test_the_health_endpoint_can_skip_the_integrity_check`・`test_the_out_dir_is_not_pruned_and_says_why`・`test_the_backup_dir_shape_is_checked_on_the_spot`・`test_the_shape_change_takes_a_pre_topup_backup`・`test_importing_the_app_module_does_not_open_the_data_dir`・`test_the_state_does_not_wait_for_a_running_snapshot`・`test_the_same_failure_is_not_written_again`・`test_a_stale_error_is_cleared_when_the_dir_is_writable_again`・`test_a_snapshot_whose_copy_is_broken_is_not_adopted`）。`test_get_endpoints_write_nothing` は中身の sha256 で比べる形。壊し試験は下の F。
- **GET は書かない**（再確認）: S3b。openapi の GET 全部＋資産・サムネイル・GUI の 29 本を 2 回、タイマー 1 周期を挟んで、全表の中身の sha256 `b5da4f9d92eda6dc`（5029 行）と `<data>`＋置き場の全ファイル（315 件）が同じ。
- **性能**（再確認）: 日次 1 回は写しの検査（`quick_check`＋`integrity_check`）が増えたが、複製のサーバで起動直後 0.0 秒に出来ている。

### C-1〜C-3

- 無し（直っている）。

## D. 軽微

- **D-1 走ったまま壊れた 1 回目の `tick` が、記録に 2 回行って 2 回目で落ちる。** `_refuse_if_broken` → `_mark_broken`（記録 → `read_only`）→ `raise` → `tick` の `except` → `_failed` → `_record_error` → `transaction()` が 503 → `log.exception("バックアップの失敗を記録できませんでした（DB にも書けません）")`。記録は 1 回目で済んでいるので害は無いが、ログにトレースバックが 1 つ出る（R1 の実行で確認）。`_failed` で `self.store.read_only` なら記録を飛ばす。
- **D-2 2 ページ目を潰した形では `GET /api/backup` も 503。** `state()` が `settings` を読み、そのページが壊れているので `sqlite_error_handler` が 503 `read_only` に写す（S5 の page2 の一覧: `/api/backup` 503）。画面（P8-5）は「バックアップの状態が読めない」も読み取り専用の案内として扱うこと。
- **D-3 `PATCH /api/settings` にファイルの**下**を指す置き場を渡すと 200**（`<file>\sub`。S4e）。作れないので次の周期で `last_error` になる（前と同じ道）。`check_backup_target` は「存在するのにフォルダでない」しか見ない。親を辿って最初に存在する物がファイルなら 422 に。
- **D-4 `replace_dir` の再試行は 5 回 × 50 ms。** ウイルス対策の掴みは秒単位のこともある。`PermissionError` が続いたときの文言（`last_error`）に「置き場のフォルダを別のプロセスが掴んでいる」と書く。
- **D-5 `pre-topup-*` の控えは `GET /api/backup` の一覧に `kind: pre-topup` で出るが、`last_at` の計算には含まれる**（`snaps[0]` が pre-topup なら `last_at` はその時刻。コード読み `backup.py` `state()`。実行では見ていない）。日次の「最後に取った時刻」として画面に出すなら `daily` / `manual` だけで引く。
- **D-6 `.backup/pre-p8-4-*` に `README.txt` がある。** `restore` は余分なファイルを無視するので害は無いが、`list_snapshots` の形（`db.sqlite3`＋`manifest.json`）と違う物を `.backup/` に置く流儀は 1 行書いておく。

## E. 設計とのずれ

- 無し。§0.20 に今回の確定が入り、§0.12-5 は「写しを開いて `quick_check` → `integrity_check`」、§0.12-6 は「読み取り専用で起動して案内」に直っている。

## F. テストで守れないもの

- **壊し試験**（`mutate_p85.py`。前回の 17 通り＋M18〜M30 の 13 通り。plugin でソースは触らない）: **29 / 30**。M18 写しの検査をいつも ok に → `test_a_snapshot_whose_copy_is_broken_is_not_adopted`＋7 世代の試験が落ちる。M19 sha256 の照合を外す（`force` と同じ）→ `test_restore_refuses_a_snapshot_whose_bytes_changed` ほか。M20 走ったまま壊れた入口を外す → 7 世代の試験（`results[0]["error"]`）。M21 門が GUI も止める → `test_the_gui_is_served_even_when_the_db_cannot_be_opened`。M22 `-wal` を先に `unlink` → `test_the_stale_wal_is_removed_only_after_the_db_is_in_place`。M23 形の検査を外す → `test_the_backup_dir_shape_is_checked_on_the_spot`。M24 同じ文言でも書き直す → `test_the_same_failure_is_not_written_again`。M25 直っても消さない → `test_a_stale_error_is_cleared_when_the_dir_is_writable_again`。M26 `out` でも掃除 → `test_the_out_dir_is_not_pruned_and_says_why`。M27 `pre-topup` を取らない → `test_the_shape_change_takes_a_pre_topup_backup`。M28 壊れたページの handler を外す → `test_a_broken_ledger_page_says_503_not_500`＋1。M30 `list_groups` を `transaction()` に戻す → `test_the_read_endpoints_still_read_when_the_db_is_broken`。前回の M1〜M17 も全部落ちる（M7 は新しい 7 世代の試験でも落ちる）。**M29（import で `app` を作る元の形）だけ 60 passed**: `test_importing_the_app_module_does_not_open_the_data_dir` は**別プロセス**（`subprocess` で `python -c`）で import を見るので、同じプロセスの plugin では壊せない。等価変異ではなく私の壊し方が届かないだけで、G-8 そのものは R9 で実機を見た。
- 守れていない物: (a) B-1' は運用（どのプロセスが 8790 を立てるか）なので試験では守れない。(b) D-1（二重の記録）を見る試験は無い。(c) `replace_dir` の再試行は試験で固定されていない（`PermissionError` を 1 回だけ投げる `os.replace` を差して固定できる）。

## G. 依頼者への質問（推奨つき。待たずに推奨で進めてよい）

- **G-1 実機の日次**（B-1'）。推奨: 利用者が sandbox の外（自分の端末）で 8790 を立て直す。それまでの間は `PATCH /api/settings {"backup_dir": "<sandbox が書ける <data> の外>"}` で凌ぐ（例: `C:\work\image-reviwer\.backup\daily`。`.backup/` は既に控えの置き場なので趣旨に合う）。どちらにしても **`GET /api/backup` の `count` が 1 以上になったことを 1 度確かめる**。
- **G-2 D-1 の二重の記録**。推奨: `_failed` の先頭で `if self.store.read_only: return {...}`。
- **G-3 D-3 の「ファイルの下」**。推奨: `check_backup_target` で `path` の祖先のうち最初に存在する物が `is_dir()` でなければ 422。
- **G-4 画面（P8-5）**。推奨: `last_error` を上部バーに出す（B-1' のような失敗を利用者が見える形に）。`GET /api/backup` が 503 のときも同じ場所に「読み取り専用」と出す。

## H. 確かめられなかったこと・注記・後始末

- **置き場**: 前回と同じく sandbox が `%USERPROFILE%` の下に書かせないので、バックアップの置き場は repo 内 `.tmp-audit-redo/p8-recheck/backups/`。既定の置き場は作られていない（8790 からも作れていない＝B-1'）。
- **走ったまま壊れた DB の read_only への切り替えを、本物のサーバで見ていない**（ライブラリの R1 だけ）。サーバの接続は DB を丸ごとキャッシュしているので、外から潰しても `tick` の `quick_check` には見えない。ライブラリでは `shrink_memory` でキャッシュを捨てて再現した。
- `--include-library`（292 MB）の所要と、`replace_dir` の再試行が実際に効く形は見ていない。
- 8791 / 8795 は他の担当（P8-3 の直し）のサーバなので触っていない。私のサーバは 8793 だけ（`/api/health` の `data_dir` を確かめてから止めた）。
- 1 回目の `checks5.py` の NG 2 件（R1a・R2c）と R2 の例外は私の脚本の側（以後の `tick` は `failed` ではなく `read_only` が正しい、1 バイトの差し替えがページの余白に当たった、`sqlite3.connect` を閉じずに `os.replace` が掴まれた）。直して 0 NG（`checks5.run1.out.txt` に 1 回目を残した）。
- 実行したコマンド（`$env:UV_CACHE_DIR = "C:\work\image-reviwer\.uv-cache"`、`cd C:\work\image-reviwer`）:
  - `uv run --no-sync pytest -q -p no:cacheprovider` ×3・`node tools/gui_smoke.mjs`
  - `uv run --no-sync python -X utf8 .tmp-audit-redo\p8-4-audit\real_sig.py`（前後）・`uv run --no-sync python -X utf8 .tmp-audit-redo\p8-recheck\checks5.py`（R1〜R11）
  - `bash .tmp-audit-redo/p8-recheck/run_mutants5.sh`（M1〜M30）
  - `bash .tmp-audit-redo/p8-recheck/srv_run5.sh normal settings page2 head4k page300 ahead oldbad`（8793。`prep_srv4.py` → `server_check5.py`）
  - `curl http://127.0.0.1:8790/api/backup`（実機。GET だけ）・`Get-CimInstance Win32_Process`（8790 の親の鎖）
- 一時物: `.tmp-audit-redo/p8-recheck/`（`checks5.py clock/replica は p8-4-audit の物を使う`・`mutate_p85.py run_mutants5.sh server_check5.py srv_run5.sh recheck_click.mjs gui_run5.sh`、複製 `w/`、置き場 `backups/`、出力 `checks5*.out.txt mutants5.out.txt server5.out.txt server_check-*.log layout5.out.txt click5.out.txt smoke.out.txt pytest*.out.txt real_sig.*.txt`）と `.tmp-audit-redo/p8-4-audit/srv`・`gui`・`gui-lib`（作り直した複製）。消して構わない。

## 最も重大な 3 件（再掲）

1. **B-1'** 実機の 8790 は sandbox の中で立っていて、既定の置き場に書けず日次が 0 個（`last_error` に出ている）。利用者が自分で立て直すか、置き場を変える。
2. （無し）
3. （無し）
