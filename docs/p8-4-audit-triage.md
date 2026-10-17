# P8-4 の監査の指摘の仕分け（**2026-10-18。判定は「合格（条件つき）」→ 全部反映**）

- 監査: [`p8-4-audit-report.md`](p8-4-audit-report.md)（154 行。判定 **合格（条件つき）**・条件は **B-1** の 1 つ・
  **C-1〜C-3**・**D-1〜D-13**・**E-1〜E-7**・**F**・**G-1〜G-9**・H の注記 2 件）。
- **触ったファイルと行数**（`git diff --numstat`。**コミットはしていない**）:

  | ファイル | 行数（増減） | 何をした |
  | --- | --- | --- |
  | `src/image_reviewer/backup.py` | +408/-107（1276 → **1578 行**） | **写しの検査**（`check_snapshot_db`）・**sha256 の照合**・**`restore` の順序**・`pre-topup-*`（`backup_before_shape_change`・`_write_db_only`）・置き場の形の検査（`check_backup_target`）・`prunable`・同じ失敗を書かない・直れば消す・`state()` の錠を外す・`out` では掃除しない・`replace_dir`（Windows の一時的な掴み） |
  | `src/image_reviewer/db.py` | +62/-41（804 → **840 行**） | **`TOP_UP_COLUMNS` を 1 か所に**（`_top_up_v6` と `missing_top_ups()` が同じ物を見る） |
  | `src/image_reviewer/store.py` | +39（541 → **581 行**） | 開く前に **`backup_before_shape_change`**・控えが取れなければ `settings` の `backup.last_error` に残す |
  | `src/image_reviewer/review.py` | +12/-4 | **読む 3 本を `store.locked()`**（`group_state` / `list_groups` / `list_decisions`。C-3） |
  | `src/image_reviewer/app.py` | +28/-3 | **`_db_gate` は `/api/` の下だけ**（D-1）・**`sqlite3.DatabaseError` の handler**（C-3）・**`app` を遅延**（G-8） |
  | `src/image_reviewer/api/__init__.py` | +30 | **`sqlite_error_handler`**（壊れたページを触った読みは 503 `read_only`） |
  | `src/image_reviewer/api/backup.py` | +48/-38 | **錠の下で回す**＋**`?full=0`**（D-7） |
  | `src/image_reviewer/cli.py` | +24/-2 | `serve` は **`--factory`**（G-8）・`restore` が **sha256 の 1 行**と**退避先**を出す（C-1・D-3）・`backup` が**写しの検査**を出す |
  | `tests/test_backup.py` | +615/-14（1366 → **1968 行・60 件**） | **新規 15 件＋書き換え 1 件**（§8.1 の 72〜87 の元）＋`GET` が書かない検査を中身の `sha256` で見る形に（F(e)） |
  | `tests/conftest.py` | +17/-1 | 収集の前に **`IMAGE_REVIEWER_DATA` / `IMAGE_REVIEWER_BACKUP_DIR` をテストの中へ**（G-8） |
  | `tools/probe_p8.py` | +3/-3 | 線 10a の文言と検査を**5 つ**（`settings.json` 込み）に直した（D-9。**実装は前から 5 つ作っていた**） |
  | `docs/p8-design.md` | +89/-14 | **§0.20（この監査の確定）**・§0.12（1〜6）・§0.13・§1.2（線 10〜12）・§3.3・§3.4・§6.2・§7・§8.1（72〜87）・§10-0 の 12 |
  | `docs/p8-4-implementation.md` | +22 | **§9 の追記**（記録の本文は直さず、実装と違う所だけ） |
  | `docs/p8-4-audit-triage.md` | **新規**（この文書） | 指摘ごとに 1 行 |

  （**13 ファイル +1398/-227 と新規 1**（`git diff --numstat` の実測）。**`README.md` と `docs/design.md` は触っていない**。
  **`apps/gui/`・`api/deletions.py`・`deletions.py`・`tests/test_deletions.py` は P8-3 の直しが並行なので触っていない**）
- 実行した確認（**複製**。`.tmp-audit-redo/p84-fix/`。サーバは **8791**。`IMAGE_REVIEWER_DATA` は必ず付けた）:
  `pytest -q` **472 passed × 6 回**、`node tools/gui_smoke.mjs` **232 ok / NG 0**、
  `node tools/gui_layout.mjs` の **9 画面すべて ok（各 3 窓）**、
  **壊し試験 18/18 が落ちる**（`.tmp-audit-redo/p84-fix/mutants.py`）、
  `tools/probe_p8.py --backup --restore` **すべて OK**・`tools/check_contract_p8.py` **OK 24 / NG 0**、
  **立てたままのサーバへの `restore`**（`s6_run` の再現。409 の 1 行・`<data>` の署名が前後で同じ）、
  `import image_reviewer.app` が**実データを触らない**こと（`.data` の大きさと mtime が前後で同じ）。
- **実データ `.data` は `mode=ro` と `backup()` だけ**。**画像は 1 枚も動かしていない**（下の署名）。
  **`.backup/` は 1 つも消していない**（G-9 で 1 つ足した）。**利用者の 8790 は止めていない**（最後まで `LISTENING`）。

## 指摘ごとに 1 行

| # | 指摘（監査） | どうした | どこ |
| --- | --- | --- | --- |
| **B-1** | **日次が写しの健全性を検査せず、壊れた写しで健全な 7 世代を押し出す**（設計 §0.12-5・専門 §5.5 が未実装。`last_error` も出ない） | **採用（推奨 G-1 のとおり）**。`_write_snapshot` が**中身を作り終えた後**に `check_snapshot_db`（`quick_check` → `integrity_check`）を回し、通らなければ **409 `bad_snapshot`**。`snapshot()` は一時フォルダを捨て、**`prune` を呼ばず**、`_record_error` に残す。**元の接続の `quick_check` も見て、走ったまま壊れていれば `store.read_only` に切り替える**（書き込みが 503 になる） | `backup.py` `check_snapshot_db` / `_write_snapshot` / `snapshot` / `_refuse_if_broken` / `_mark_broken`・`p8-design.md` §0.12-5・§8.1（72・73） |
| **C-1** | **`restore` が manifest の `db_sha256` を読まない**（中身を 1 バイト変えた写しが黙って採用される） | **採用（G-2）**。`quick_check` の**前に** `sha256_file(src_db)` と比べ、違えば **409 `bad_backup`**（`details.expected` / `actual`）。**`--force` で進める**（結果の `sha256.ok` を CLI が 1 行で出す） | `backup.py` `restore`・`cli.py` `cmd_restore`・`p8-design.md` §0.12-4・§3.4・§8.1（76） |
| **C-2** | **アプリが掴んでいる間の `restore` がトレースバックで落ちる**（`-wal` の `unlink` が `copy2` より先。決めた点 22 とテストの主張と逆） | **採用（G-4）**。順序を「**写しを一時名に `copy2` → `os.replace` → その後に `-wal` / `-shm` を消す**」に直し、**全部の `OSError` を 409 `restore_failed`** に写す。**実機で確かめた**: 8791 を立てたまま CLI の `restore` → `exit=2`・「アプリを止めてから戻してください」の 1 行・**`<data>` の全表ハッシュと全ファイルハッシュが前後で同じ**（トレースバックは出ない） | `backup.py` `restore`・`tests/test_backup.py`（本物の錠の 2 件）・`p8-design.md` §0.12-4・§3.4・§8.1（77・78） |
| **C-3** | **読み取り専用で `GET /api/groups` / `/api/reviews` が 503・2 ページ目の形で台帳 3 本が 500** | **採用（G-3）**。**読む 3 本を `store.locked()`** に（`group_state` / `list_groups` / `list_decisions`）。**`sqlite3.DatabaseError` を 503 `read_only`（`details.reason: "malformed"`）に写す handler を 1 つ**足した（`review_error_handler` の隣） | `review.py`・`api/__init__.py` `sqlite_error_handler`・`app.py`・`p8-design.md` §3.4・§8.1（79・80） |
| **D-1** | 先頭 4 KB の形では **GUI そのものが 503**（案内は curl かログでしか読めない） | **採用（G-6）**。`_db_gate` は **`/api/` の下だけ**止める（`/` と静的ファイルは通す）。**`Host: evil` が 403 のまま**であることも変わらない | `app.py` `_db_gate`・`p8-design.md` §1.2 の線 12・§8.1（81） |
| **D-2** | **版が同じでも `_top_up_v6` は表の形を変えるが控えは取らない**（実データで実際に起きた） | **採用（G-5）**。**`pre-topup-<YYYYMMDD>-<HHMMSS>/` を `ALTER` の前に取る**（`Store` が開く前。`backup()`・`manifest.json` つき・**写しを開いて検査**）。**足す物の一覧は `db.TOP_UP_COLUMNS` が正**（2 か所に書かない）。**控えが取れなくても開く**（足すだけの `ALTER` なので開けなくする方が害が大きい）が、`settings` の `backup.last_error` に残す | `backup.py` `backup_before_shape_change` / `_write_db_only`・`db.py`・`store.py`・`p8-design.md` §0.12-6・§0.13・§8.1（85） |
| **D-3** | 退避先の記録と実装のずれ（`<backup_dir>` と書いてあるが、CLI ではスナップショットの隣） | **実装に記録を合わせた**（監査も「どちらでもよい」）。CLI の表示に「**バックアップのフォルダの隣**」と出す | `cli.py` `cmd_restore`・`backup.py` `restore` の docstring・`p8-4-implementation.md` §9 |
| **D-4** | 失敗が続く間、30 秒ごとに `settings` を書き直す | **採用（G-7）**。`_record_error` は**同じ文言なら書かない**（`last_error_at` は「最初に失敗した時刻」になる） | `backup.py` `_record_error`・`p8-design.md` §8.1（74） |
| **D-5** | 置き場を直しても `last_error` が残る（`already` の道で消さない） | **採用（G-7）**。`already` でも、**置き場に実際に書いてみて**書けるなら `_clear_error`（書けないうちは消さない） | `backup.py` `tick` / `_clear_error_if_fixed` / `_dir_is_writable`・`p8-design.md` §8.1（75） |
| **D-6** | 一覧と掃除の対象が違う・`--out` の一時の置き場でも掃除が走る | **採用**: `snapshot_info` に **`prunable`**（掃除の対象になる形か）を足し、**`out` を指定したときは掃除しない** | `backup.py` `snapshot_info` / `snapshot`・`p8-design.md` §0.12-2・§8.1（83） |
| **D-7** | `GET /api/health/db` が錠の外で `store.con` を触り、毎回 `integrity_check` | **採用**: **全部 `store.locked()` の下**で回し、**`?full=0`** で `integrity_check` を省ける（語彙外は 422。既定は今までどおり） | `api/backup.py` `health_db`・`p8-design.md` §3.3・§8.1（82） |
| **D-8** | 専門 §5.5 の「WAL のチェックポイントは終了時と日次で」が未実装 | **設計の文を直す方を採った**（**実装しない**。理由は下の「決めたこと」3） | `p8-design.md` §0.20 の D 行 |
| **D-9** | 線 10 の「4 つできる」は 5 つ（`settings.json`） | **採用**: 線 10 と §0.12-1 を**5 つ**に直した（契約の `includes` に欄が無いことも明記） | `p8-design.md` §1.2 の線 10・§0.12-1 |
| **D-10** | 実データの `settings.backup_dir` は既に `C:\Users\yukse\image-reviewer-backups` | **対応不要（利用者に 1 行知らせるだけ）**。**8790 を立て直した瞬間にそこへ `20261018/` が出来る**（意図どおり）。この文書と親への報告に書いた | この文書・報告 |
| **D-11** | `PATCH /api/settings` が存在や絶対パスを検査しない | **採用**: **相対パス・ファイル・無いドライブは 422 `bad_backup_dir`**（`check_backup_target`。`POST /api/backup` の `out` と CLI の `--out` も同じ道） | `backup.py` `check_backup_target` / `check_backup_dir`・`p8-design.md` §3.3・§8.1（84） |
| **D-12** | `BackupService._lock` を握ったまま sidecar / export / library を写す | **採用**: `state()` から `self._lock` を外した（書きかけの一時フォルダは名前的に一覧に出ず、差し替えは `os.replace` なので**出来上がった物だけが見える**） | `backup.py` `state`・`p8-design.md` §8.1（87） |
| **D-13** | `image_reviewer.app` の import が実データを書き込み可で開く | **採用（G-8）**。下の「G-8」の行 | `app.py`・`cli.py`・`tests/conftest.py` |
| **E-1** | §0.12-5「日次で `integrity_check`」が無い | **採用**（B-1）。§0.12-5 を「**写しを開いて `quick_check` → `integrity_check`**」に書き直した | `p8-design.md` §0.12-5 |
| **E-2** | §0.12-6 の「版 > バイナリなら起動を拒否」が本文に残っている（§10-13 は読み取り専用） | **採用**: §0.12-6 を「**読み取り専用で起動して案内**」に直した | `p8-design.md` §0.12-6 |
| **E-3** | 専門 §5.3 の「先に自動バックアップ」は `copy2` の退避（online backup ではない） | **実装のまま**（アプリが止まっていれば WAL も一緒。走っていれば C-2 で 409）。§0.12-4 に「一時名に写して `os.replace`」と書いた | `p8-design.md` §0.12-4 |
| **E-4** | 専門 §5.5 の WAL チェックポイント（D-8） | 設計の文を直す方を採った（下の「決めたこと」3） | `p8-design.md` §0.20 の D 行 |
| **E-5** | §3.3 の「`PATCH /api/settings`（既存の口に足す）」は口が無かったので新設 | **そのまま**（実装が正。§3.3 の表は「既存の口に `backup_dir` を足す」のまま。**口は P8-4 で作った**と記録にある） | — |
| **E-6** | §3.4 の表に `503 read_only` は 1 行（実装は `mode` / `reason` を足した） | **採用**: §3.4 に**壊れたページの読み（503 `read_only`・`reason: malformed`）**と **409 `bad_snapshot`**・**409 `bad_backup`（sha256）**・**409 `restore_failed`** の行を足した | `p8-design.md` §3.4 |
| **E-7** | 線 10 の「`<YYYYMMDD>/` を一時に作って `os.replace`」は「いま取る」の説明として古い | **採用**: 線 10 を `<YYYYMMDD>-<HHMMSS>/` に直した（線 10 の「4 つ」も 5 つに） | `p8-design.md` §1.2 の線 10 |
| **F** | 守れていない 5 つ（日次の検査・`db_sha256`・`unlink` の錠・読み取り専用の読み・`GET` が書かないの見方）＋壊し試験の穴 | **採用**: **14 件の試験を足した**（§8.1 の 72〜87）。`test_get_endpoints_write_nothing` は**全表と全ファイルの中身の `sha256`** でも比べる形にした。**壊し試験は 18 通り中 18 通りで落ちる** | `tests/test_backup.py`・`.tmp-audit-redo/p84-fix/mutants.py`・`p8-design.md` §8.1・§8.4 |
| **G-1** | 日次の健全性（推奨: 写しに `check_db_file(full=True)`・落ちたら捨てて `last_error`・`prune` を呼ばない・元の接続も見る） | **採用**（B-1 のとおり。**物差しは復元の後と同じ `check_snapshot_db`**） | 上と同じ |
| **G-2** | `db_sha256` の照合（推奨: 手順 2 の前に比べる・違えば 409・`--force` で進む） | **採用**（C-1 のとおり） | 上と同じ |
| **G-3** | 読み取り専用の読み（推奨: `locked()`・`DatabaseError` を 503 に写す handler） | **採用**（C-3 のとおり） | 上と同じ |
| **G-4** | `restore` の順序（推奨: 一時名 → `os.replace` → `-wal` / `-shm`・全部の `OSError` を 409） | **採用**（C-2 のとおり） | 上と同じ |
| **G-5** | 版を上げない形の変更の控え（推奨: `pre-topup-*` を `ALTER` の前に） | **採用**（D-2 のとおり。**名前は `pre-topup-*`**） | 上と同じ |
| **G-6** | GUI を 503 にしない（推奨: `_db_gate` で `/api/` 以外は通す） | **採用**（D-1 のとおり） | 上と同じ |
| **G-7** | `last_error` の扱い（推奨: 同じ文言なら書かない・置き場が変わったら `already` でも消す） | **採用**（D-4・D-5 のとおり） | 上と同じ |
| **G-8** | import 時の `create_app()`（推奨: `app` を遅延・`uvicorn` には factory・pytest は収集の前に `IMAGE_REVIEWER_DATA` を向ける） | **採用**: `app.py` の `app` を **PEP 562 の `__getattr__` で遅延**（`import image_reviewer.app` では何も開かない）。`cmd_serve` は **`--factory` で `create_app`** を渡す。`tests/conftest.py` の `pytest_configure` が **`setdefault` でテストの中へ向ける**。**実機で確かめた**: `IMAGE_REVIEWER_DATA` 無しで `import image_reviewer.app` → `.data` の大きさと mtime が前後で同じ・`%USERPROFILE%\image-reviewer-backups` も作られない | `app.py`・`cli.py`・`tests/conftest.py`・`p8-design.md` §0.12-6・§8.1（86） |
| **G-9** | 実データの `stuck_reason` の列（消さなくてよい。`pre-p8-4-*` を 1 つ取ってから 8790 を立て直す） | **採用**: **`.backup/pre-p8-4-20261017-232148/`** を `mode=ro` から `backup()` で取った（**263 枚・判断 3 件・`user_version` 6・1,576,960 B・`integrity_check ok`・`manifest.json` つき**）。**列は消していない**（作業木の DDL と同じ形） | `.backup/pre-p8-4-20261017-232148/`・`p8-4-audit-triage.md`（この文書） |
| **H（事故 1）** | 監査が 8791 に居た実装者の複製サーバを止めた | **こちらでは起きていない**。私が使ったのは **8791 の自分の複製のみ**（`/api/health` の `data_dir` を確かめてから止める運用）。**8790 は最後まで動かしたまま** | この文書の「実データ」 |
| **H（事故 2）** | 実データに `stuck_reason` の列が足された（D-13 のせい） | **原因を塞いだ**（G-8）。**列はそのまま**（G-9 の控えを取った） | `app.py`・`tests/conftest.py` |

## 決めたこと（監査の推奨と違う所・自分で決めた所）

1. **写しの検査は「中身を作り終えた後」に 1 回**（`_write_snapshot` の最後、`manifest` を書く前）。
   監査の「写した直後」を**スナップショット全体を作り終えた後**と読んだ（`sidecar` / `export` を写す前だと、
   その後に壊れた写しを採用してしまう。**検査は 1 か所・1 回**にして、`manifest` も検査済みの
   `db.sqlite3` から作る）。**通らなければ 409 `bad_snapshot`**（500 にしない。家風「人が読める理由を番号で」）。
2. **走ったまま壊れた DB は読み取り専用に切り替える**（G-1 の後半）。`tick` と `snapshot` の入口
   （`_refuse_if_broken`）で元の接続の `quick_check` を見る。**記録を先に書いてから**切り替える
   （`read_only` にすると `transaction()` が 503 になり、失敗を書けなくなる）。
3. **D-8（日次と終了時の WAL チェックポイント）は実装しない**。理由: (a) **終了時は SQLite が自分で畳む**
   （最後の接続が閉じるとき）、(b) 日次で畳むと `test_the_snapshot_folds_the_wal_so_decisions_are_not_lost`
   の前提（**素の `copy2` では判断が抜ける**＝WAL に判断がある）が壊れ、**その検査が守っている穴**
   （P4-0 の監査 D-1）を検証できなくなる、(c) 監査も「害は無い」と書いている。**専門 §5.5 の文を直す側**を採った。
4. **`pre-topup-*` が取れなくても `Store` は開く**（`pre-migrate-*` は今までどおり**取れなければ版を上げない**）。
   理由: `_top_up_v6` がやるのは**足すだけの `ALTER`** で、控えが無いことより**開けないこと**の方が害が大きい。
   代わりに `settings` の `backup.last_error` に残す（**黙って形を変えない**）。
5. **`replace_dir()` を足した**（一時フォルダの `os.replace` を `PermissionError` のときだけ数回試す）。
   理由: 壊し試験の**最初の全件実行で 1 回だけ** `WinError 5`（`.tmp-20231116` → `20231116`）で落ちた
   （同じテストは単独では 6 回とも緑）。**2.3 MB の写しを書いた直後**なので、ウイルス対策か索引が
   掴んでいる形。**黙って諦めず**、それでも通らなければ例外を上げる。
6. **`_dir_is_writable` は実際に小さな一時ファイルを書いてみる**（D-5 の 2 案のうち、
   「置き場が書けることを確かめて消す」を採った）。**書けないのに「直った」と消さない**。

## 残した所（理由）

| # | 残した物 | 理由 |
| --- | --- | --- |
| D-8 | 日次と終了時の WAL チェックポイント | 上の「決めたこと」3（**設計の文を直した**） |
| D-10 | 8790 の `backup_dir`（`C:\Users\yukse\image-reviewer-backups`） | 実装の変更ではない。**利用者のアプリを P8-4 のコードで立て直した瞬間に、そこへ日次が 1 つ出来る**（意図どおり）。**親への報告に 1 行で書いた** |
| D-12 の残り | `--include-library`（292 MB）の間、`store.locked()` は短時間だけ取る | 写しの DB を作る間だけ錠を取る（`state()` は待たない）。**292 MB の実測は監査もやっていない**（H） |
| H | `--include-library` の 292 MB の所要時間 | 実データの複製で測っていない（**測り方が要る**。P8-5 の仕上げの候補） |
| H | 置き場を `%USERPROFILE%` の下に作れない | **私の環境でも同じ**（sandbox）。バックアップの置き場は `.tmp-audit-redo/p84-fix/backups/` を使った（**`<data>` の外**・既定の置き場は作られていない） |

## 実行したコマンド（そのまま打てる形）

```powershell
$env:UV_CACHE_DIR = "C:\work\image-reviwer\.uv-cache"
cd C:\work\image-reviwer
uv run --no-sync pytest -q                                            # 472 passed（×6 回）
node tools/gui_smoke.mjs                                              # 232 ok / NG 0
uv run --no-sync python -X utf8 .tmp-audit-redo\p84-fix\real_sig.py   # 実データの署名（前後）
uv run --no-sync python -X utf8 .tmp-audit-redo\p84-fix\mutants.py    # 壊し試験 18/18
uv run --no-sync python -X utf8 .tmp-audit-redo\p84-fix\g9_backup.py  # G-9 の控え
uv run --no-sync python tools\probe_p8.py --backup --restore          # すべて OK（複製・作業場は自分で消す）
uv run --no-sync --with jsonschema python tools\check_contract_p8.py  # OK 24 / NG 0
uv run --no-sync python -X utf8 .tmp-audit-redo\p84-fix\gui_setup.py  # 画面検査の複製（DB と画像 263 枚）
$env:IMAGE_REVIEWER_DATA = "C:\work\image-reviwer\.tmp-audit-redo\p84-fix\gui"
$env:IMAGE_REVIEWER_BACKUP_DIR = "C:\work\image-reviwer\.tmp-audit-redo\p84-fix\backups"
.\.venv\Scripts\python.exe -X utf8 -m image_reviewer.cli serve --port 8791
uv run --no-sync python -X utf8 tools\gui_layout_seed.py --data .tmp-audit-redo\p84-fix\gui --tags
node tools/gui_layout.mjs --base http://127.0.0.1:8791 --count 8                        # 比較
node tools/gui_layout.mjs --base http://127.0.0.1:8791 --screen requests
node tools/gui_layout.mjs --base http://127.0.0.1:8791 --screen group --group <id>
node tools/gui_layout.mjs --base http://127.0.0.1:8791 --screen asset --ids <1 枚>
node tools/gui_layout.mjs --base http://127.0.0.1:8791 --screen tags
node tools/gui_layout.mjs --base http://127.0.0.1:8791 --screen jobs
node tools/gui_layout.mjs --base http://127.0.0.1:8791 --screen duplicates
node tools/gui_layout.mjs --base http://127.0.0.1:8791 --screen pending
node tools/gui_layout.mjs --base http://127.0.0.1:8791 --screen library
# C-2 の芯（**サーバを立てたまま** CLI の restore。409 の 1 行・<data> は変わらない）
.\.venv\Scripts\python.exe -X utf8 -m image_reviewer.cli restore <いま取った写し>
uv run --no-sync python -X utf8 .tmp-audit-redo\p84-fix\sig.py .tmp-audit-redo\p84-fix\gui
# G-8（**実データを触らない**ことの証拠）
Remove-Item Env:IMAGE_REVIEWER_DATA
.\.venv\Scripts\python.exe -X utf8 -c "import image_reviewer.app as m; print('app' in vars(m))"
```

## 実データ（前後で同じ）

| 何 | 前（作業の最初） | 後（作業の最後） |
| --- | --- | --- |
| `asset` | 263 | 263 |
| `decision` | 3 | 3 |
| `asset_location` | 263（実体が無い 0） | 263（実体が無い 0） |
| `asset.deleted_at` | 0 | 0 |
| `deletion_log` | 0 | 0 |
| 画像 263 枚の署名（`display_path`・`size`・`mtime_ns` の sha256。**私の物差し**） | `e0c72619666cde9d`（**292,561,491 B**） | 同じ |
| `db.sqlite3` | 1,544,192 B / mtime `639278464463391253` | 同じ |
| `db.sqlite3-wal` / `-shm` | 4,190,072 / 32,768 B・mtime 同じ | 同じ |
| `.data/sidecar`・`export`・`thumbs` の mtime | 同じ | 同じ |
| `.backup/` | 7 フォルダ | **8 フォルダ**（G-9 で `pre-p8-4-20261017-232148` を足した。**消していない**） |
| `%USERPROFILE%\image-reviewer-backups` | 無い | **無い** |
| 利用者の 8790 | `LISTENING`（PID 32592） | `LISTENING`（**止めていない**） |

- **監査の報告の署名 `fa99ca126c393d5a` と私の `e0c72619666cde9d` は物差しが違う**（同じ 263 枚・同じ
  292,561,491 B を指している）。**親の指示の `74410426eefb756f` は私の物差しでは再現できなかった**
  （sha1 / md5・並べ方・区切り・`stat` の mtime を試したが一致しない）。**中身の意味（263 枚・合計バイト・
  1 枚も動いていない）は一致している**ので、そう報告する。

## 後始末（残した物・消した物）

- **消した物**: 画面検査の複製の画像 **`gui-lib`（279 MB）** と、下ごしらえの実測に使った
  `probe/`・リポジトリ直下の `tmpyetigyhn` / `tmpyetigyhn-backups`（**自分が作った物だけ**。
  `gui_setup.py` で 30 秒で作り直せる）。
- **残した物**: `.tmp-audit-redo/p84-fix/`（`real_sig.py`・`probe_locks.py`・`probe_cache.py`・`mutants.py`・
  `mutants.out.txt`・`g9_backup.py`・`gui_setup.py`・`sig.py`・`to_lf.py`・`gui/`（複製の DB）・
  `backups/`（検査で取った写し）・`layout.out.txt`・`probe_p8*.out.txt`・`srv.*.txt`）。
  **消して構わない**（再現手順はこの文書にある）。
- **止めたサーバ**: **8791 の自分の複製だけ**（`/api/health` の `data_dir` が
  `.tmp-audit-redo\p84-fix\gui` であることを確かめてから止めた）。**8790 は止めていない**。
- **行末**: 触ったファイルのうち、P8-4 の作業木のまま **CRLF** だった 6 つ
  （`backup.py`・`store.py`・`review.py`・`app.py`・`api/__init__.py`・`api/backup.py`）を
  **LF に揃えた**（`.gitattributes` は `* text=auto eol=lf`。中身は変えていない。`pytest 472 passed` で再確認）。
  **BOM は元から付いていない**（`to_lf.py` が確認）。
