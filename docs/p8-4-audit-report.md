# P8-4 監査報告（バックアップと復元。日次・増分・`restore`・`rebuild-metadata`・壊れた DB）— 実行込み

- 日付: 2026-10-18（JST 07:10〜08:10）
- 指示書: `docs/p8-audit-brief-p8-4.md`（67 行）。実装の指示書: `docs/p8-4-implementation-brief.md`（61 行）。実装の記録: `docs/p8-4-implementation.md`（259 行。決めた点 **23**・設計の穴 **10**・申告 1。監査の指示書は「9 点と 7 件」と書くが記録の数はこれ）。
- 対象（コミット `7c32465`、17 ファイル +3973/-37）: `src/image_reviewer/backup.py`（1276 行。新規）、`api/backup.py`（130。新規）、`api/roots.py`（50。新規）、`cli.py`（+164）、`db.py`（+68）、`store.py`（+24）、`app.py`（+105）、`review.py` / `compare.py` / `deletions.py`（読み取り専用の道）、`tests/test_backup.py`（1366 行・45 件）、`tests/conftest.py`（+21）、`tools/probe_p8.py`（+333）、`tools/check_contract_p8.py`（+80）。
  **監査中の作業木は HEAD（`caa2f68`）と違う**: P8-3 の直しが並行で入り、`apps/gui/*`・`tools/gui_layout.mjs`・`tools/gui_smoke.mjs`・`api/deletions.py`・`deletions.py`・`tests/test_deletions.py` と、**P8-4 の対象でもある `db.py`**（`deletion_log.stuck_reason` の列と `_top_up_v6` の `ALTER`）が未コミットで変わっている。P8-4 のファイル（`backup.py`・`api/backup.py`・`api/roots.py`・`cli.py`・`store.py`）は HEAD のまま。
- 設計の版: `docs/p8-design.md` 997 行・`docs/duplicates-deletion-backup.md`（専門）§5。
- 環境: `uv run --no-sync`。実データ `.data` は `mode=ro` と `backup()`（WAL の形を見る 1 本だけ `copy2` で 3 ファイルを写した）の複製だけ。**画像は 1 枚も動かしていない**（`rebuild-metadata` は PNG を読むだけ）。複製は `.tmp-audit-redo/p8-4-audit/`（`w/k*`・`srv/`・`gui/`・`gui-lib/` 13 枚）。
  **バックアップの置き場は `.tmp-audit-redo/p8-4-audit/backups/`**（`<data>` の外・隣でもない）。指示書の「`%USERPROFILE%` の下」は **sandbox が `%USERPROFILE%` 直下・`Documents`・`AppData\Local`・`Downloads` のどこにもフォルダを作らせない**（6 か所で WinError 5）ため守れなかった（H）。**既定の `%USERPROFILE%\image-reviewer-backups` は監査の前後とも無い。**
  複製のサーバは **8793 / 8794**（`IMAGE_REVIEWER_DATA` と `IMAGE_REVIEWER_BACKUP_DIR` を付けて起動。終了後に待ち受け 0 本）。**8790 は止めていない**（PID 32592・06:22:50 起動＝P8-3 の直しの前のコード。`GET /api/backup` は 404＝P8-4 の裏側はまだ載っていない）。ComfyUI は触っていない。
  **事故 1 件（H）**: 最初に 8791 で立てようとして bind に失敗し、その 8791 に居た**実装者の複製サーバ（PID 22132・`data_dir .tmp-audit-redo/p83-fix/srv`）を私の脚本が止めた**（07:36:24）。利用者の 8790 ではない。以後はポートを変え、止める前に `/api/health` の `data_dir` が自分の複製かを確かめる形にした。
- 実データ: 監査の最初と最後に `mode=ro` で読み直して **v6・24 表（`sqlite_sequence` 込み）・263 枚・判断 3 件・`deleted_at` 0・台帳 0**、画像 263 枚の署名 **`fa99ca126c393d5a`・合計 292,561,491 B**（P8-3 と同じ）。`db.sqlite3` 00:07 のまま。`.backup/` は 7 フォルダのまま。コミットしていない。
  **ただし事故 2 件目（H）**: `-wal` の mtime が 05:19 → **07:34:34** に変わり、`deletion_log` に **`stuck_reason` の列が足されている**（作業木の `db.py` の `_top_up_v6`。行は 1 行も変わらず、07:26 の複製と全表の中身・索引・`user_version` が同じ）。07:34 は私の壊し試験の中で、plugin（M10 / M16 / M17）が `pytest_configure` で `image_reviewer.app` を import し、`app.py:452` の `app = create_app()` が **`IMAGE_REVIEWER_DATA` 未設定のまま実データを書込み可で開いた**ため（通常のテストは `monkeypatch.setenv` の後に関数の中で import するので、素の `pytest -q` では起きない）。つまり D-2 の「版を上げない形の変更に控えが無い」が、**実データで、私の手で、起きた**。`export/`（05:19）・`sidecar/`（10-15 10:05）・`thumbs/`（10-15 08:58・159 項目）は変わっていない。
- 回帰: **pytest 453 → 457 → 457 passed**（26.5 / 27.3 / 26.4 s）（1 回目は HEAD の 453、2 回目から作業木に P8-3 の直しのテスト 4 本が増えた）、**gui_smoke すべて ok（ok 229 行・NG 0）**、**gui_layout 8 画面すべて ok（`--count 8`・requests・group・asset・tags・jobs・duplicates・pending・`pending --ids` の 9 本。各 3 窓）**（複製 `gui/`＋`gui-lib/` 13 枚に語 5・まとまり 1・理由が `<script>` の除外 1・段 3 の保留 1 を入れて。作業木の `gui_layout.mjs`＝P8-3 の直し版で測った。複製のサーバの起動で置き場 `backups/gui/20261018/` が出来た＝日次が本物の起動でも走る）、`check_contract_p8.py` OK 24 / NG 0、`probe_p8.py` は実装者の記録のまま（私は自分の脚本で同じ線を引いた）。

## 判定: **合格（条件つき）**

合格の線 10・11・12 は実データの複製で通る。**線 10**: 起動の直後（0.0 秒）に `<backup_dir>/20261018/` が出来、30 秒後の周期では増えず（`ticks` 1→2・`skipped=already`）、「いま取る」は同じ秒でも `20261018-074032` → `-074032-1` と必ず新しい。**WAL を畳む**: 実データと同じ形（`db.sqlite3` 1.5 MB＋`-wal` 4 MB を `copy2` した複製）で `backup()` の写しは 263 枚・判断 3 件・まとまり 1。素の `copy2`（主ファイルだけ）では `review_group` 0 / `group_item` 0 / `duplicate_exclusion` 0 / `phash_band` 3872（畳めば 1 / 2 / 1 / 4208）が抜ける（**判断 3 件は主ファイルに既に在る**。実装者の「copy2 で判断 0 件」は合成の DB のテストの話で、いまの実データでは成り立たない）。manifest は**本物の `jsonschema`** で 29 個（日次・いま取る・pre-migrate）全部通り、`db_sha256` / `db_bytes` は実物と一致。**線 11**: 複製の `<data>` を丸ごと消して `restore` → 263 枚・判断 3 件・`integrity_check ok`・sidecar 1・export 2 が戻り、`Store` で開けて v6。`rebuild-metadata` で sidecar の英訳（`1girl. solo. chibi. safe. …`）が空欄に戻り、DB の値（`model=db-value`）は上書きされず、PNG から `seed` / `steps` が埋まる。**線 12**: 自分で作った 3 つの形（先頭 4 KB・2 ページ目・300 ページ目）で `inspect_db` が `unusable/unreadable`・`read_only/malformed`・`read_only/malformed`（300 ページ目は例外ではなく行 2 本）、複製のサーバで起動し、`health/db` 503＋案内、`POST` は 503 `read_only`、`Host: evil` は 403 のまま、タイマーは張られず置き場に何も出来ない。版が新しい（7）DB は拒否せず読み取り専用（版はそのまま）。版が古い（5）DB は `pre-migrate-*` を取ってから 6 に上げ、控えの置き場が `<data>` の中なら上げずに読み取り専用（版 5 のまま）。**GET は 1 バイトも書かない**（openapi の GET 全部＋資産・サムネイル・GUI の 28 本。タイマー 1 周期を挟んで全表の中身の sha256 と全ファイルが同じ）。壊し試験は **17 通り中 17 通り**で狙ったテストが落ちる（F）。

条件は 1 つ、**B-1 日次が写しの健全性を見ない**。設計 §0.12-5 と専門 §5.5 は「日次で `integrity_check`。通らなければ利用者に知らせ、古いスナップショットを残す」と書くが、`_write_snapshot` は元も写しも検査せず、`prune` も止めない。壊れた DB（300 ページ目）を走ったまま 7 日分写すと、**健全な 7 世代が壊れた 7 世代に全部置き換わり、`last_error` は None** のまま（K9）。ほかに **C-1 `restore` が manifest の `db_sha256` を読まない**（中身を変えた写しが `quick_check` も `integrity_check` も通って黙って採用される）、**C-2 アプリが DB を掴んでいる間の `restore` は 409 の 1 行ではなくトレースバックで落ちる**（`-wal` の `unlink` が `copy2` より先。決めた点 22 とテストの主張と逆）。

**最も重大な 3 件**

1. **B-1 日次スナップショットが健全性を検査せず、壊れた写しで 7 世代を押し出す。** `backup.py:790-853`（`_write_snapshot`）は `con.backup()` → `journal_mode=DELETE` → sidecar/export → manifest で、`quick_check` も `integrity_check` も無い。`snapshot()`（`:741-777`）は成功したら無条件に `prune_snapshots` を呼ぶ。設計 §0.12-5「日次で `integrity_check`」・専門 §5.5「失敗したら利用者に知らせ、`<backup_dir>/` の古いスナップショットを残す」が未実装。再現（`checks4.py K9`、実データの複製）: 健全な日次を 7 日分 → 走ったまま 300 ページ目を 0 で潰す → 7 日分 `tick` → 7 回とも `taken`（写しは `database disk image is malformed`）・`last_error=None` → 残る 7 個は全部壊れており、壊す前の 7 個は消えた。**条件**: 走っている接続は自分のページキャッシュ（既定 2 MB。この DB 1.5 MB は丸ごと載る）越しに読むので、外から潰したページは**キャッシュが捨てられるまで見えない**（私は `PRAGMA shrink_memory` と `cache_size=1` で捨てた）。実データの大きさでは「再起動して `inspect_db` が止める」方が先に来ることが多いが、ライブラリが増えてキャッシュに載らなくなれば、この道がそのまま起きる。推奨 G-1。
2. **C-1 `restore` が manifest の `db_sha256` を使わない。** `backup.py:970-1078`。契約（§6.2）は `db_sha256` を「控えた DB の中身のハッシュ」として必須にし、`_write_snapshot` は書くが、`restore` は `read_manifest` で形だけ確かめて `quick_check` → `integrity_check` に進む。再現（K10k）: 写しの `db.sqlite3` の `settings.backup_dir` の末尾 1 バイトを変える → manifest の sha と実物の sha が食い違う → `restore` は `before ok / after ok` で通り、戻った DB の値は変えた方。`quick_check` / `integrity_check` は構造しか見ないので、**中身だけ変わった写し（ビット化け・別の写しとの混同）を見つける手段が契約にあるのに使っていない**。推奨: 手順 2 の前に `sha256_file(src_db)` と比べ、違えば 409 `bad_backup`（`--force` で進む）。
3. **C-2 アプリが DB を掴んでいる間の `restore` は 409 ではなくトレースバックで落ちる。** `backup.py:1027-1037`: 退避の後、`-wal` / `-shm` を `unlink()`（`:1029`）してから `copy2`（`:1032`）で、`OSError` を 409 `restore_failed`「アプリを止めてから戻してください」に写すのは **`copy2` だけ**。Windows では SQLite が `-wal` を `FILE_SHARE_DELETE` 無しで開いているので、**先に `unlink` が `WinError 32` で落ちる**。再現（`s6_run.sh`。複製を 8794 で立てたまま CLI の `restore`）: `exit=1`・stderr はトレースバック（`PermissionError: [WinError 32] … db.sqlite3-wal`）・「止めて」の 1 行は出ない。`<data>` は変わらず（全表の sha256・ファイルの一覧が同じ）、`pre-restore-*` の退避は出来ている。決めた点 22「500 にしない。人が読める理由を返す」と `test_a_locked_db_is_reported_not_crashed`（`copy2` だけを失敗させる）は、**実機で失敗する所（`unlink`）を見ていない**。もう 1 つ: この順序は「`unlink` が通って `copy2` が落ちる」と `<data>` の WAL だけが消える（退避からしか戻せない）。推奨: 写しを一時名に `copy2` → `os.replace` → その後に `-wal` / `-shm` を消す。テストは `unlink` を失敗させる。

---

## A. 直っていない／設計の約束が成り立たない

- 無し（P8-4 は新規の段。P8-3 の G-3 の口 `allow-stage3` は在り、立てて外せる・エージェント 403・`allow` 無し 422・無い置き場 404・表示パスでも引ける）。

## B. 重大

### B-1 日次が写しの健全性を見ず、壊れた写しで 7 世代を押し出す（最も重大の 1）

- 場所: `backup.py:790-853`（`_write_snapshot`）・`:741-777`（`snapshot()` → `prune_snapshots`）・`:706-730`（`tick`）。設計 `p8-design.md` §0.12-5（L247-248）・専門 `duplicates-deletion-backup.md` §5.5（L517-523）。
- 再現と結果: 上の 1。`checks4.out.txt` の K9a / K9b。
- 判定: 設計が書いている検査が無い。保持 7 世代は「壊れた物を 7 個残す」になり得る。**壊し試験の観点では、日次の検査が無いことを落とすテストが無い**（F）。
- 推奨（G-1）: 写しを作った直後に `check_db_file(db_out, full=True)`（復元の後と同じ物差し）。通らなければ一時フォルダを捨て、`last_error` に残し、`prune` を呼ばない。元の接続の `quick_check` も先に見てよいが、キャッシュ越しなので写しの検査の方が確実。

## C. 中程度

### C-0 確かめた結果、問題なし（1 行ずつ。実行したもの）

- **線 10 日次とタイマー**（`server_check4.py normal` S1a/S1b、`checks4.py K3`）: 起動直後 0.0 秒で `20261018/`、`today_done=True`、`next_run_at` は JST の翌 0 時（`T15:00:00Z`）、今日まだなら `+30 秒`。FakeClock で同じ日の `tick` ×3 は 1 つ、日が変わると取る。
- **「いま取る」**（S2a、K3b）: `<YYYYMMDD>-<HHMMSS>`、同じ秒は `-1`。`include_library: "false"` は偽（文字列を真にしない）。
- **WAL を畳む**（K1。実データと同じ 3 ファイルの素の写しで）: 上の判定の段落。写しは 1 ファイル（`journal_mode=delete`・`-wal` / `-shm` 無し）。manifest の sha256 / bytes が実物と一致。`settings.json` に 8 件。
- **manifest の契約**（本物の `jsonschema`）: 私の複製で取った 29 個が全部通る。`check_contract_p8.py` OK 24 / NG 0（実物の manifest も）。
- **増分**（K4a-c、S2a）: 2 回目は `linked=3 copied=0`、`st_ino` が同じ。中身が変わると写し、古いスナップショットの中身は変わらない。前を消しても後は読める。
- **保持 7 世代**（K4d-f）: 9 日で 7 個。`my-notes`・`pre-restore-*`・`pre-migrate-*`・manifest の無い日付名は残る。
- **置き場**（K6a、S2b、S4g-j）: `<data>` の中・`<data>` そのもの・`<data>` を含む親・大小文字違いの `<data>` は 422 `bad_backup_dir`（PATCH・POST の `out`・CLI の `--out`）。env → settings → 既定の順（K6g/i、S2d/e）。
- **失敗が `last_error` に残る**（K6c/e、S4c-f。複製のサーバで PATCH を**ファイル**に向けて 29 秒後に `GET /api/backup` に出た）。「いま取る」が通れば消える。
- **壊れた DB の 3 つの形**（K8a/b、サーバ page2 / head4k / page300）: 上の判定の段落。先頭 4 KB は健康の口以外が全部 503（読みも）。2 ページ目・300 ページ目は `GET /api/assets` 200・`POST` 503 `read_only`・`GET /api/backup` 200（`read_only: true`・`running: false`）。
- **版**（K8c-i、サーバ ahead / old / oldbad）: 版が新しい（7）は `read_only/version_ahead` で読める・版はそのまま。版が古い（5）は起動で `pre-migrate-20261018-073817/`（DB だけ・manifest あり・`kind: pre-migrate`）を取ってから v6。控えの置き場が `<data>` の中なら `pre_migrate_backup_failed` で読み取り専用・版は 5 のまま（サーバ oldbad: `health/db` 503・`quick_check ok`・`v=5`・読み 200・書き 503・置き場に何も出来ない）。`pre-migrate-*` は `prune(keep=0)` でも消えない。
- **restore**（K10a-j、`cli` は実装者のテストで）: 退避（判断 4 件の方）→ `quick_check` → 置換 → `integrity_check` → sidecar / export。`<data>` を丸ごと消して 263 / 3 / sidecar 1 / export 2。2 ページ目を潰した写しは 409 `bad_backup`、`--force` でも `integrity_check` で止まって**元に戻る**（判断 3 件・`quick_check ok`）。300 ページ目を潰した写し（行で返る形）も 409。manifest 無しは 409 `bad_manifest`（`--force` で進む）。無いフォルダは 422。
- **rebuild-metadata**（K12。複製の DB・実ファイルの PNG は読むだけ）: 上の判定の段落。2 回目は何も変えない。80 枚は `prompt` チャンクが無い（`no_source`）。
- **口**（S2b/d/f/g、S4j、S5e）: 人だけ 403 `human_only`（`POST /api/backup`・`PATCH /api/settings`・`allow-stage3`）、`robot` は 422、`Host: evil` / `text/plain` は 403（壊れた DB でも 503 より先）。読むのはエージェントも可。
- **GET は書かない**（S3a/b）: 28 本の GET を 2 回、間にタイマーの周期（`ticks` 1→2）を挟んで、全表の中身の sha256 `49979d9c20f9135e`（5029 行）と `<data>`＋置き場の全ファイル `3c094969dafc5eb4`（327 件）が同じ。
- **申告 1 件の裏取り**: `C:\ai\ComfyUI_windows_portable\ComfyUI\output\ComfyUI\Anima\20261010\132800_00001_.png` は **1,487,627 B・2026-10-15 09:09:06.709 のまま**、263 枚の署名 `fa99ca126c393d5a` も P8-3 の監査と同じ。申告どおり無傷。
- **性能**（設計 §7 の未計測。実データの複製・温まった状態・5 回の中央値）: 日次 1 回 **37 ms**（35〜46。2 回目以降は増分）、`restore` **11 ms**（11〜13）、`state()`（`GET /api/backup` 相当。5 個の一覧） 7 ms。目標（5 秒・10 秒）に対して 2 桁余裕。

### C-1 `restore` が manifest の `db_sha256` を使わない（最も重大の 2）

- 場所: `backup.py:970-1078`。契約 `schemas/backup-manifest.schema.json` の `db_sha256`（必須・「控えた DB の中身のハッシュ」）。
- 再現: `checks4.py K10k`。上の 2。
- 推奨: `before = check_db_file(src_db)` の前に `"sha256:" + sha256_file(src_db) == manifest["db_sha256"]` を見る。食い違いは 409 `bad_backup`（`details.expected` / `actual`）、`--force` で進む。CLI の表示にも「sha256 一致」を 1 行。

### C-2 アプリが掴んでいる間の `restore` はトレースバック（最も重大の 3）

- 場所: `backup.py:1027-1037`。テスト `tests/test_backup.py::test_a_locked_db_is_reported_not_crashed`（`shutil.copy2` だけを失敗させる）。決めた点 22。
- 再現: `.tmp-audit-redo/p8-4-audit/s6_run.sh`（複製を 8794 で立てたまま `IMAGE_REVIEWER_DATA=<複製> uv run --no-sync image-reviewer restore <いま取る>`）→ `s6_restore.err.txt` の末尾 `PermissionError: [WinError 32] … db.sqlite3-wal`、`exit=1`。`s6_sig.txt`: `<data>` の全表 `782c427d3551e73b`・ファイル `72923700cba58b9d` が前後で同じ、サーバは 263 枚を返し続ける、`pre-restore-20261018-074237/` は出来ている。
- 推奨: 順序を「一時名へ `copy2` → `os.replace(tmp, db.sqlite3)` → `-wal` / `-shm` を消す」に。`os.replace` も掴まれていれば `PermissionError` なので、そこを 409 に写す。`unlink` の `OSError` も同じ 409 に。テストは `Path.unlink` を失敗させる物を 1 本足す。

### C-3 読み取り専用で起動したとき「読みは生かす」が部分的

- 場所: `review.py:339`（`list_groups`）・`:375`（`list_decisions`）が**読むのに `store.transaction()`** を使う → 読み取り専用では `GET /api/groups` と `GET /api/reviews` が **503 `read_only`**（サーバ page2 / page300 / ahead の S5f。26 本中 2 本）。2 ページ目を潰した形では `GET /api/pending-deletes`・`/api/deletions`・`/api/deletions/trash` が **500**（素の `sqlite3.DatabaseError: database disk image is malformed`。そのページに台帳の表が載っている）。
- 判定: `transaction()` で読むのは P5 からの形で P8-4 の責任ではないが、P8-4 の「読み取り専用で起動」はこれに当たる。まとまりの一覧と判断の台帳が見えないと、復元の前に「何が残っているか」を画面で確かめられない。500 は `_db_gate` の後ろで起きるので番号で分からない。
- 推奨（G-3）: 読みの 2 本は `store.locked()` に替える（`BEGIN IMMEDIATE` は要らない）。読み取り専用のときに `sqlite3.DatabaseError` を 503 `read_only`（`details.reason: malformed`）に写す handler を `review_error_handler` の隣に 1 つ。

## D. 軽微

- **D-1 先頭 4 KB の形では GUI そのものが 503。** `app.py:177-200`（`_db_gate`）は `/api/health` と `/api/health/db` 以外を全部止めるので、`/`（`StaticFiles`）も 503 の JSON になる（サーバ head4k S5d）。案内（`guidance`）は curl かログでしか読めない。P8-5 の「バックアップの状態」画面を出すなら `/` と静的ファイルは通す。
- **D-2 版が同じでも `_top_up_v6` は表の形を変えるが、控えは取らない。** `backup_before_migrate` は `current >= expected` で `None`（`backup.py:376`）。**実際に起きた**: 並行で入った `deletion_log.stuck_reason` の `ALTER`（作業木の `db.py`、07:19 更新）が、07:34 に実データへ**控え無しで**掛かった（上の事故 2 件目。8790 の立て直しを待たずに、`image_reviewer.app` を import しただけの別プロセスから）。版を上げないまま形を変える流儀（P8-1 の帯・P8-3 の列）とこの約束は噛み合っていない。
- **D-13 `image_reviewer.app` の import が実データを書込み可で開く。** `app.py:452` の `app = create_app()` は import の時点で `data_dir()`（既定 `.data`）を `Store` で開き、`migrate()`・`_top_up_v6`・`reasons.seed`・`flush_dirty()` まで走らせる。`uvicorn` の都合だが、pytest の収集・plugin・`python -c` のどれでも `IMAGE_REVIEWER_DATA` を忘れた瞬間に実データに触る（`tests/conftest.py` の `_close_prototype_app` はその接続を閉じるためにある）。P8-4 が「書く前に健全性を見る・控えを取る」を足した今、この入口だけが素通りする。推奨 G-8。
- **D-3 退避先の記録と実装のずれ。** 記録 §5-7 は「`<backup_dir>/pre-restore-<日時>/`」と書くが、`restore` は `backup_dir` 無指定なら **スナップショットの親**（`backup.py:1016`）に置き、CLI は `backup_dir` を渡さない（K10b）。USB の写しから戻すと退避は USB に出来る。どちらでもよいが、記録と CLI の案内を実装に合わせる。
- **D-4 失敗が続く間、30 秒ごとに `settings` を書き直す。** `_record_error` が `last_error_at` を毎周期更新する（K6d）。WAL に 1 行ずつ積む。同じ文言なら書かない、か「初回の時刻」と「最後の時刻」を分ける。
- **D-5 置き場を直しても `last_error` が残る。** `tick` の `already` の道は `_clear_error` を呼ばないので、今日の分が既に在る日は次の成功（翌日か「いま取る」）まで古い失敗が画面に出続ける（K6f、S4e）。`already` でも置き場が書けることを確かめて消すか、`last_error_at` と一緒に出して画面で判断させる。
- **D-6 一覧と掃除の対象が違う。** `list_snapshots` は名前だけで拾う（manifest の無い `20200101/` も `daily`・`ok: false` で出る）が、`prune` は manifest 付きだけを消す（K4d/e）。逆に、人が別の所から写した「自分の形」の `20200102/`（manifest 付き）は消される（K4f）。`--out` / `out` で指定した一時の置き場でも 7 世代の掃除が走る（`backup.py:771`）。
- **D-7 `GET /api/health/db` は `store.con` を `locked()` 無しで触り、毎回 `integrity_check` を回す**（`api/backup.py:68, 93`）。監査 B3「読みも錠の下で」の流儀と違う。1 万枚では GET 1 回が秒単位になる。
- **D-8 専門 §5.5 の「WAL のチェックポイントは終了時と日次で」は未実装。** `con.backup()` は元の WAL を畳まないので、実データの `-wal` 4 MB はそのまま。害は無いが設計の文を直すか実装する。
- **D-9 線 10 の「4 つできる」は 5 つ**（`settings.json`）。実装者も書いている。`manifest.includes` には宣言できない（契約 `additionalProperties: false`）。
- **D-10 実データの `settings.backup_dir` は既に `C:\Users\yukse\image-reviewer-backups`**（`_seed_settings` の種）。8790 を P8-4 のコードで立て直した瞬間に、その置き場に `20261018/` が出来る（意図どおりだが、利用者に 1 行知らせる）。
- **D-11 `PATCH /api/settings` は存在や絶対パスを検査しない。** 相対パス・無いドライブ・ファイルを指す値も 200（K6b、S4c）。失敗は次の周期で `last_error` に出るので致命ではないが、PATCH の応答で「作れない」を 422 で返す方が親切。
- **D-12 `BackupService._lock` を握ったまま sidecar / export / library を写す。** `--include-library`（実データなら 292 MB）の間 `GET /api/backup` が待たされる。

## E. 設計とのずれ（実装が決めた所を含む）

実装者の「決めた点」23 行の判定: 1（`settings.json`）妥当（D-9）。2（`os.link`）妥当・実測で同じ inode。3（`journal_mode=DELETE`）妥当・壊すと落ちる（M13）。4（`pre-migrate` は掃除しない）妥当。5（`health/db` は読み取り専用なら 503）妥当（本文に `mode` / `reason` がある）。6（`--force` の意味）妥当。7（退避先）**記録と実装がずれる**（D-3）。8（JST）妥当。9（`_db_gate` の位置）妥当・実機で 403 が先。10・11（読み取り専用でサムネイル / pHash を作らない）妥当。12（`app_version`）妥当。13（`out`）妥当（D-6 の掃除に注意）。14（`kind`）妥当。15（テストの置き場）妥当・必要。16（終了コード 2）**掴まれた DB では成り立たない**（C-2）。17（空いている欄だけ）妥当・実測。18（`include_library` の復元は無いときだけ）妥当。19・20（`{id}` の受け方）妥当・表示パスで引けた。21（増分の相手）妥当。22（409 `restore_failed`）**実機では落ちる**（C-2）。23（案内の置き場）妥当。

設計の穴 10 件の判定: 1（`PATCH /api/settings` が無かった）正しい。2（`GET /api/roots`）正しい・必要。3（300 ページ目は `ok` でない）**正しい**（私の複製でも行 2 本。設計 §10-12 の文を直す）。4（名前の食い違い）§3.3 を採って妥当。5（契約の `includes`）正しい。6（§0.12-6 がテスト表に無い）正しい・2 本足した。7（退避先）D-3。8（sidecar / export の上書き）妥当・申し送り 6 に書いた。9（`read_only` の理由 3 つ）妥当。10（`health/db` の番号）妥当。

- **E-1 §0.12-5「日次で `integrity_check`」が無い**（B-1）。
- **E-2 §0.12-6「DB の版 > バイナリなら起動を拒否」は §10-13 のとおり「読み取り専用で起動」に変えてある**（実測 K8c/d・サーバ ahead）。§0.12-6 の本文がまだ「拒否」なので直す。
- **E-3 専門 §5.3「既存の DB があるときは先に自動バックアップ」の形**: 実装は `copy2` で 3 ファイルを退避する（online backup ではない）。アプリが止まっていれば WAL も一緒なので中身は揃う。走っていれば C-2 で止まる。
- **E-4 専門 §5.5 の WAL チェックポイント**（D-8）。
- **E-5 §3.3「`PATCH /api/settings`（既存の口に足す）」**: 口は無かったので新設（穴 1）。妥当。
- **E-6 §3.4 の表に `503 read_only` は 1 行**: 実装は `mode` / `reason` を足した（穴 9）。表に 1 行足す。
- **E-7 線 10「`<YYYYMMDD>/` を一時に作って `os.replace` で差し替え」は「いま取る」の説明として古い**: 実装は `<YYYYMMDD>-<HHMMSS>/`（§3.3）。線 10 の文を直す。

## F. テストで守れないもの

- **壊し試験**（`mutate_p84.py`。plugin でソースは触らない。`PYTHONPATH` に置いて `P8X=M<n> uv run --no-sync pytest -q -p mutate_p84 tests/test_backup.py`）: **17 / 17** で狙ったテストが落ちる。M1 `copy2` で写す（WAL）→ `test_the_snapshot_folds_the_wal…`＋1。M2 `already` を見ない → 線 23。M3 復元後の `integrity_check` を外す → 線 24。M4 `quick_check` の例外を受けない → F7。M5 掃除が名前と manifest を見ない → 7 世代。M6 「いま取る」も日次の名前 → CLI。M7 `last_error` を書かない。M8 退避しない。M9 置き場の検査を外す。M10 `_db_gate` を外す。M11 `require_human` を外す。M12 増分を外す。M13 `journal_mode` を戻さない（写しの隣に `-wal` / `-shm` が生える。実測で確認）。M14 `rebuild-metadata` が上書き。M15 読み取り専用の `transaction` が 503 を返さない。M16 控えの失敗を握りつぶす。M17 版の先行を見ない。**M1 と M13 は私の plugin の書き方が最初は間違っていて**（`sqlite3.Connection` の属性は差し替えられない）、直してから数えた。
- **守れていない物**: (a) 日次の健全性の検査が無いこと（B-1）を落とすテストは無い。(b) `restore` が `db_sha256` を見ないこと（C-1）。(c) 掴まれた DB での `restore` はテストが `copy2` だけを失敗させ、実機で落ちる `unlink` を見ない（C-2）。(d) 読み取り専用で `GET /api/groups` / `/api/reviews` が 503 になること（C-3。`test_a_broken_db_starts…` は `GET /api/assets` と `/api/backup` しか見ない）。(e) 「GET が書かない」のテスト（`test_get_endpoints_write_nothing`）は**行数**と size/mtime を比べる（P8-1 の監査と同じ穴。中身の sha256 で比べる）。
- `probe_p8.py --backup` の「線 10b 判断が抜けない（WAL 4 MB を畳む）」は `backup()` の複製で測るので、WAL の分が畳まれているのは複製を作った時点。素の `copy2` との差を実データの形で見るには、3 ファイルを `copy2` した複製（私の K1）が要る。

## G. 依頼者への質問（推奨つき。待たずに推奨で進めてよい）

- **G-1 日次の健全性**（B-1）。推奨: 写しに `check_db_file(full=True)`、落ちたら一時フォルダを捨てて `last_error`、`prune` を呼ばない。元の接続にも `quick_check` を掛けて、落ちたら `read_only` に切り替える（走ったまま壊れたときの入口）。§8.1 に「写しの `integrity_check` を外すと落ちる」を 1 行。
- **G-2 `db_sha256` の照合**（C-1）。推奨: `restore` の手順 2 の前に比べる。`--force` で進む。
- **G-3 読み取り専用の読み**（C-3）。推奨: `list_groups` / `list_decisions` を `locked()` に。`DatabaseError` を 503 に写す handler。
- **G-4 `restore` の順序**（C-2）。推奨: `copy2` → 一時名 → `os.replace` → `-wal` / `-shm` の削除。全部の `OSError` を 409。
- **G-5 版を上げない形の変更の控え**（D-2）。推奨: `_top_up_v6` が `ALTER` を打つ前にも `pre-migrate-*`（名前は `pre-topup-*`）を取る。または形を変えるときは版を上げる。
- **G-6 GUI を 503 にしない**（D-1）。推奨: `_db_gate` で `/api/` 以外は通す。
- **G-7 `last_error` の扱い**（D-4 / D-5）。推奨: 同じ文言なら書き直さない。置き場が変わったら `already` でも `_clear_error`。
- **G-8 import 時の `create_app()`**（D-13）。推奨: `app.py` の `app` を遅延（`uvicorn` には factory `image_reviewer.app:create_app` を `--factory` で渡す）にし、pytest の `conftest.py` で `IMAGE_REVIEWER_DATA` をセッションの最初に `tests/.tmp` へ向ける。これで「`IMAGE_REVIEWER_DATA` を忘れると実データが壊れる」の入口が 1 つ減る。
- **G-9 実データの `stuck_reason` の列**（事故 2 件目）。推奨: 消さなくてよい（作業木の DDL と同じ形で、次の 8790 の立て直しで同じ結果になる）。ただし `.backup/pre-p8-4-…` を `backup()` で 1 つ取ってから 8790 を立て直す。

## H. 確かめられなかったこと・注記・後始末

- **置き場の指示を守れなかった**: sandbox が `%USERPROFILE%` の下（直下・`Documents`・`AppData\Local`・`AppData\Local\Temp\claude`・`.claude`・`Downloads`）のどこにもフォルダを作らせない（WinError 5。`checks4.py` の最初の実行で 7 件が落ちた）。バックアップの置き場は **`.tmp-audit-redo/p8-4-audit/backups/`**（repo の中・`<data>` の外）に変えた。`check_backup_dir` が断るのは `<data>` の中と親だけなので試験の意味は変わらない。既定の `%USERPROFILE%\image-reviewer-backups` は作られていない。
- **事故 2 件目（実データの形が変わった）**: 監査の終わりの読み直しで `-wal` の mtime が 07:34:34 になり、`deletion_log.stuck_reason` の列が実データに在った。07:26 の複製（`backup()`）と全表の中身・索引・版を突き合わせて**違いはこの列だけ**（行は 0 行差）。原因は上の D-13: 私の `mutate_p84.py`（M10 / M16 / M17）が `pytest_configure` で `from image_reviewer import app` を書き、その import が `create_app()` を `IMAGE_REVIEWER_DATA` 無しで走らせた（M17 の実行が 07:34。テスト本体は `setenv` の後に関数の中で import するので、素の `pytest -q` や `probe_p8.py` の `fresh_app` では起きない＝私の plugin の書き方の誤り）。**画像・判断・台帳・`export/`・`sidecar/`・`thumbs/` は無傷**。`.backup/` にも控えは取っていない（取れる手は `mode=ro` からの `backup()` だけで、P8-4 の `backup_before_migrate` は版が同じなので動かない＝D-2）。
- **事故 1 件目（実装者の複製サーバを止めた）**: 07:36:24、私の `srv_run4.sh` が 8791 で bind に失敗した後、`/api/health` が返した PID（**22132。実装者の複製 `.tmp-audit-redo/p83-fix/srv`**）を `Stop-Process` した。実装者は 07:37:33 に 8795 で立て直している。8790（PID 32592）には触っていない。以後は 8793 / 8794 を使い、止める前に `data_dir` が `p8-4-audit` の下かを確かめる（違えば止めない）。
- 1 回目の `checks4.py` の K1a・K3a・K3c・K4d・K9・K10k の NG は私の脚本の誤り（JST の日付境界で 5 時間進めると翌日、`sqlite3.Connection` の属性は差し替えられない、1 バイトの差し替えが別の `human` に当たった、キャッシュ越しの読み）で、直して 0 NG（`checks4.run1.out.txt` に 1 回目を残した）。
- **走ったまま壊れる道（B-1）はキャッシュを人為的に捨てて再現した**。実データの大きさ（1.5 MB）では、走っている接続は壊れたページを見ないまま健全な写しを取り続け、再起動で `inspect_db` が止める。10 k 枚級ではキャッシュに載らない。
- **出力に残る `[NG]` 行は私の脚本の条件の組み方**: `server4.out.txt` の `normal S6a / S6b` は、署名に置き場（`pre-restore-*` が出来る側）まで含めていたため（`<data>` だけで取り直した `s6_sig.txt` が正。C-2 の根拠はそちら）。読み取り専用の各形の `S5d` は `/gui/app.js` が静的ファイルの実際の道ではない（`/` 200 が本当の検査）。`S5f` は 503 も「500 以上」に数えた（本当の 500 は 2 ページ目の形の台帳 3 本だけ＝C-3）。`server4.run1.out.txt` は 1 回目（8791 の衝突と脚本の例外）。
- 監査中の `git status` の untracked は本報告のほか、実装者の `docs/p8-3-audit-triage.md` と `tools/gui_layout_seed.py`（P8-3 の直し）。
- 「同じ日に 2 回取らない」の**本物の日付境界**（JST 0 時）は FakeClock で見た。本物のタイマーは 30 秒周期 1 回（`ticks` 1→2・増えない）。
- `--include-library` の実データ級（292 MB）は時間を測っていない（複製 13 枚の `gui/` でも回していない。実装者のテストが合成で見ている）。
- `gui_layout` は作業木（P8-3 の直し）の版で測った。P8-4 は画面を変えないので、ここの ok は「P8-4 が既存の画面を壊していない」の意味だけ。`--screen requests` は「open な要求が 0 件」の注意つきで ok。
- pytest の数が 453 → 457 と動いたのは、監査の間に実装者が `tests/test_deletions.py` に 4 本足したため（P8-3 の直し。作業木）。P8-4 の 45 本は 3 回とも緑。
- 実行したコマンド（`$env:UV_CACHE_DIR = "C:\work\image-reviwer\.uv-cache"`、`cd C:\work\image-reviwer`）:
  - `uv run --no-sync pytest -q -p no:cacheprovider` ×3・`node tools/gui_smoke.mjs`・`uv run --no-sync --with jsonschema python tools/check_contract_p8.py`
  - `uv run --no-sync python -X utf8 .tmp-audit-redo\p8-4-audit\real_sig.py`（前後）・`replica4.py data wal`・`P84_OUT=<repo>/.tmp-audit-redo/p8-4-audit/backups uv run --no-sync python -X utf8 checks4.py`（K1〜K14）
  - `bash .tmp-audit-redo/p8-4-audit/run_mutants.sh`（M1〜M17）
  - `bash .tmp-audit-redo/p8-4-audit/srv_run4.sh normal settings page2 head4k page300 ahead old oldbad`（8793。`prep_srv4.py` → `server_check4.py`）・`bash s6_run.sh`（8794）・`bash gui_run4.sh`（8793。`replica_gui4.py` → `gui_layout` 8 画面）
- 一時物: `.tmp-audit-redo/p8-4-audit/`（複製 `data/`・`wal/`・`w/`・`srv/`・`gui/`・`gui-lib/`、置き場 `backups/`、脚本 `replica4.py clock4.py checks4.py mutate_p84.py run_mutants.sh prep_srv4.py server_check4.py srv_run4.sh s6_run.sh snap4.py replica_gui4.py gui_run4.sh real_sig.py`、出力 `checks4.out.txt checks4.run1.out.txt mutants.out.txt server4.out.txt server4.run1.out.txt server_check-*.log s6_*.txt layout4.out.txt smoke.out.txt pytest*.out.txt manifest.real.json real_sig.*.txt`）。消して構わない。

## 最も重大な 3 件（再掲）

1. **B-1** 日次スナップショットが写しの健全性を検査せず（設計 §0.12-5・専門 §5.5）、壊れた写しで 7 世代を押し出す。`last_error` も出ない。
2. **C-1** `restore` が manifest の `db_sha256` を読まない。中身だけ変わった写しが黙って採用される。
3. **C-2** アプリが掴んでいる間の `restore` は `-wal` の `unlink` で先に落ち、409 の 1 行ではなくトレースバック。テストは `copy2` しか失敗させていない。
