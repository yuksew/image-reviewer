# P8-4（バックアップと復元）の実装の記録

- 日付: 2026-10-18（JST 06:25〜07:20）
- 指示書: [`p8-4-implementation-brief.md`](p8-4-implementation-brief.md)（61 行）
- 正: [`p8-design.md`](p8-design.md) §0.12・§0.13・§0.16（B2・B3）・§0.18・§1.2（線 10〜12）・
  §3.3・§6.2・§7・§8.1（23・24）・§8.4（F7）・§10-12/§10-13・§9 の P8-4 の行、
  [`duplicates-deletion-backup.md`](duplicates-deletion-backup.md) §5（元ネタ）
- 触った物（行数は実測。`git diff --stat` も添えた）: 下の「1. 作ったもの」
- **実データ `.data/` は `mode=ro` でしか開いていない**（複製は `sqlite3` の `backup()`）。
  **画像は 1 枚も動かしていない・消していない**（§8 の署名で確認）。**`.backup/` は消していない**。
  **バックアップの置き場は `%USERPROFILE%` の下**（実データの隣に作っていない）。
  **`git` のコミットはしていない**。**`README.md` と `docs/design.md` は触っていない**（`git status` で確認）。
- 環境: `$env:UV_CACHE_DIR = "C:\work\image-reviwer\.uv-cache"`、`uv run --no-sync`、
  複製のサーバは `IMAGE_REVIEWER_DATA=<複製>` を付けて **8791**（利用者の 8790 は止めていない・触っていない）

---

## 1. 作ったもの（ファイルと行数）

| ファイル | 行数 | 何をしたか |
| --- | --- | --- |
| `src/image_reviewer/backup.py` | **1276（新規）** | 置き場の解決（環境変数 → 設定 → 既定）・`snapshot`（online backup API ＋ `sidecar` / `export` / `settings.json` / `library`）・増分（sha256 ＋ `os.link`）・`manifest`（契約を自分でも検査）・日次の 30 秒タイマー・`last_error`・一覧・保持 7 世代・`inspect_db`（壊れた DB の 3 つの形）・`restore`（退避 → `quick_check` → 置換 → `integrity_check` → 元に戻す）・`rebuild_metadata`・`backup_before_migrate`・`backup_dir` の設定 |
| `src/image_reviewer/api/backup.py` | **130（新規）** | `POST /api/backup`（人だけ）・`GET /api/backup`・`GET /api/health/db`（503＋案内）・`GET` / `PATCH /api/settings` |
| `src/image_reviewer/api/roots.py` | **50（新規）** | `GET /api/roots`・`POST /api/roots/{id}/allow-stage3`（人だけ。**G-3 で P8-4 に回された口**） |
| `src/image_reviewer/app.py` | 452（+105/-2） | 起動の前に `inspect_db`（**壊れていれば読み取り専用で開く**）・版を上げる前の控え・`_db_gate`（**壊れた DB で書き込ませない**。守りの**後ろ**で見る）・バックアップのタイマー・サムネイルを読み取り専用で作らない・ルーター 2 本 |
| `src/image_reviewer/cli.py` | 513（+164/-3） | `backup` / `restore` / `rebuild-metadata`・`_store()` の健全性の門と**版を上げる前の控え**・`ReviewError` を終了コード 2 で返す |
| `src/image_reviewer/db.py` | 804（+68/-8） | `quick_check()`（**例外も「壊れている」に数える**）・`integrity()` を壊れた DB でも落ちない形に・`open_db(read_only=True)` は移行しない・`connect(read_only=True)` はフォルダを作らない |
| `src/image_reviewer/store.py` | 541（+24/-4） | **`Store(read_only=True)` の道**（設計 §10-12）・読み取り専用の `transaction()` は **503 `read_only`** |
| `src/image_reviewer/review.py` | 956（+9/-4） | 読み取り専用では builtin の投入と `reconcile()` を走らせない（起動が落ちないように） |
| `src/image_reviewer/compare.py` | 1580（+10） | 読み取り専用では pHash / dHash を計算しない（書けないのに計算しない） |
| `src/image_reviewer/deletions.py` | 1663（+49） | `roots()`（一覧）と `set_allow_stage3()`（**印を立てる／外す**。人だけ） |
| `src/image_reviewer/api/__init__.py` | 107（+5） | `backup_of(request)` |
| `tests/test_backup.py` | **1366（新規・45 本）** | §4 の表（壊れた DB 3 形・タイマー・「いま取る」・WAL・契約・増分・保持・`last_error`・復元・組み直し・`GET` が書かない・403/422・CLI・版を上げる前の控え・**掴まれた DB の 409**） |
| `tests/conftest.py` | 121（+21） | **バックアップの置き場をテストの中へ**（向けないと**利用者のホーム**にスナップショットを作り、保持 7 世代で**本物の控えを消す**） |
| `tools/probe_p8.py` | 1058（+333） | `--backup` / `--restore`（実データの複製で線 10〜12・壊れた DB の 3 形・`<data>` を消して戻す） |
| `tools/check_contract_p8.py` | 158（+80/-22） | **実際に `backup()` が書いた manifest** を本物の `jsonschema` で通す（見本だけでなく実物） |
| `docs/p8-4-implementation.md` | これ | 記録 |

一時物（消してよい）: `.tmp-audit-redo/p8-4/`（`measure_broken.py`・`synthetic_check.py`・
`smoke_backup.py`・`smoke_http.py`・`gui_setup.py`・`count_tests.py`・`gui/`（複製・画像 12 枚・
画面検査の下ごしらえ）・`contract/`・`probe-all.log`・`gui-serve*.log`）、`.tmp-audit-redo/p8probe/`
（probe が自分で消す。`--keep` で残る）。

---

## 2. 実行したコマンドと結果

```
$env:UV_CACHE_DIR = "C:\work\image-reviwer\.uv-cache"（毎回）
uv run --no-sync pytest -q                            → **453 passed**（26.21 s。ほかに 451 passed = 25.70 / 25.93 s、
                                                        449 passed = 24.99 / 25.21 s。**合計 5 回**）
node tools/gui_smoke.mjs                              → すべて ok（**207 件**。前と同じ）
node tools/gui_layout.mjs --base http://127.0.0.1:8791 --count 8                   → すべて ok（3 窓）
node tools/gui_layout.mjs --base http://127.0.0.1:8791 --screen requests           → すべて ok
node tools/gui_layout.mjs --base http://127.0.0.1:8791 --screen tags               → すべて ok
node tools/gui_layout.mjs --base http://127.0.0.1:8791 --screen jobs               → すべて ok
node tools/gui_layout.mjs --base http://127.0.0.1:8791 --screen group --group <id> → すべて ok
node tools/gui_layout.mjs --base http://127.0.0.1:8791 --screen asset --ids <id>   → すべて ok
node tools/gui_layout.mjs --base http://127.0.0.1:8791 --screen duplicates         → すべて ok
node tools/gui_layout.mjs --base http://127.0.0.1:8791 --screen pending            → すべて ok
uv run --no-sync python tools/probe_p8.py --all        → **すべて OK**（exit 0。P8-1・P8-2・P8-4 の 4 節）
uv run --no-sync python tools/probe_p8.py --backup --restore → すべて OK（exit 0）
uv run --no-sync --with jsonschema python tools/check_contract_p8.py → 全 OK（exit 0。実物の manifest も）
```

- **pytest は 408 → 453 件**（足したのは P8-4 の 45 本）。**既存は 1 件も落ちていない**。
- **`gui_layout` は 8 画面すべて ok（各 3 窓）**。**`gui_smoke` は 207 件のまま**（P8-4 は画面を作らない）。
- **`--all` は P8-1（帯と総当たりが距離 0〜64 の全部で一致・取りこぼし 0）と P8-2（線 5〜8）も緑**
  （`backup.py` が `db.py` / `store.py` / `app.py` に触ったので、回帰はここで見ている）。

### 複製のサーバ（8791）での画面検査

```
.venv\Scripts\python.exe -X utf8 .tmp-audit-redo\p8-4\gui_setup.py     # 複製（DB は backup()・画像は copy2 12 枚）
（IMAGE_REVIEWER_DATA=<複製> IMAGE_REVIEWER_BACKUP_DIR=<複製の外> を付けて 8791 で uvicorn を起動）
node tools/gui_layout.mjs …（8 画面）
（終わったら 8791 を taskkill。**利用者の 8790 は動いたまま**）
```

- 実データは **語 0 行・削除 0 行・除外の理由が空**なので、`--screen tags` / `--screen pending` /
  `--screen duplicates` は**そのままでは「行が出る」を見られない**（P8-3 も同じ理由で複製に
  下ごしらえをしていた）。**複製の中だけ**に語 20・段 3 の保留 2 件・除外の理由
  （`gui_layout` が期待する `<script>alert(1)</script>`）を入れて 8 画面を回した。
  **画面そのものは P8-4 で変えていない**（下ごしらえは検査の入力）。

---

## 3. 壊れた DB の 3 つの形（**実データの複製で実測**）

`uv run --no-sync python tools/probe_p8.py --backup` の出力（実データの複製を 1 ページずつ 0 で潰した）:

| 形 | `PRAGMA quick_check` | `inspect_db` の判定 | 起動したとき | 案内 |
| --- | --- | --- | --- | --- |
| **先頭 4 KB**（0〜4095） | **例外** `file is not a database` | `unusable` / `unreadable` | **起動する**。健康の口以外は**全部 503**（読み取りも通らない） | 復元の案内（`image-reviewer restore …`） |
| **2 ページ目**（4096〜8191） | **例外** `database disk image is malformed` | `read_only` / `malformed` | **起動する**。読みは生かす（263 枚が見える）・**書き込みの口は 503** | 同上 |
| **300 ページ目**（1228800〜） | **例外ではなくエラー行 2 行**（`*** in database main *** Tree 283 page 301: btreeInitPage() returns error code 11` と `wrong # of entries in index sqlite_autoindex_phash_band_1`） | `read_only` / `malformed` | 2 ページ目と同じ | 同上 |

- **設計 §10-12 の「300 ページ目なら `quick_check` は `ok`」は、いまの実データでは成り立たない。**
  点検が測ったときは無かった **P8-1 の `phash_band` の索引**（`sqlite_autoindex_phash_band_1`）が
  そのページに載っているためで、**「例外だけを壊れているに数える」と、この形を健全と誤判定する**。
  だから `db.quick_check()` は **`ok` 1 行でなければ壊れている**にした（例外も行も同じ扱い）。
- **先頭 4 KB は「読み取り専用で起動」では済まない**（どの SQL も投げる）ので、`unusable` を分け、
  **健康の口以外を全部 503** にした（`Store` は接続だけ作れて、触ると `sqlite3.DatabaseError`）。
- **書き込みの門は middleware の 1 か所**（`app.py` の `_db_gate`）。守り（Host / Origin /
  Content-Type）の**後ろ**で見るので、`Host: evil` は壊れた DB でも **403 のまま**（逆順だと
  403 が 503 に化ける。テストで固定）。

---

## 4. 合格の線（設計 §1.2 の 10〜12）の結果

| # | 線 | 結果（実データの複製・合成の DB） |
| --- | --- | --- |
| **10** | 日次バックアップ | `<backup_dir>/<YYYYMMDD>/` に `db.sqlite3`・`sidecar/`・`export/`・`manifest.json`（＋ `settings.json`）。**自動は同じ日なら増えない**。**「いま取る」は必ず新しく取る**（`20261018` → `20261018-070318`）。`manifest.json` は**本物の `jsonschema`** を通る |
| **10（WAL）** | `backup()` で WAL を畳む | 実データの複製（WAL 4 MB）で **263 枚・判断 3 件**が写しに入る。**素の `copy2(db.sqlite3)` では判断が 0 件**（テストで固定） |
| **10（増分・保持）** | 前と同じ物はコピーしない・直近 7 個 | 2 回目は **共有 3 / 写した 0**（`os.link`。同じ inode）。9 個取ると **7 個**が残り、人が置いたフォルダは消えない |
| **11** | `<data>` を消しても戻せる | 複製の `<data>` を**丸ごと消して** `restore` → **263 枚・判断 3 件**・`integrity_check ok`・`sidecar` 1 ファイルが戻る。`rebuild-metadata` で**実データの英訳**（`1girl. solo. chibi. safe`）が sidecar から戻る |
| **12** | 壊れた DB で書き込まない | §3 の表。**`quick_check` の結果が出る**（例外でも 500 にならない）・**書き込みの口が 503** |
| **12（版）** | 版が新しい・上げる前 | 版が新しい → **読み取り専用で起動**（拒否しない）。版を上げる前に **`pre-migrate-*` の控え**を取り、**取れなければ版を上げない**（読み取り専用で案内） |
| **口** | `POST` / `GET /api/backup`・`GET /api/health/db`・`PATCH /api/settings`・`POST /api/roots/{id}/allow-stage3` | 人だけ 403 `human_only`（読むのはエージェントも可）・`Host: evil` / `text/plain` は 403・`<data>` の中は 422 `bad_backup_dir`・`allow` の欠落は 422・知らない置き場は 404。**`GET` は全ファイルと全表で 1 バイトも書かない** |
| **性能** | 日次 5 秒以内・復元 10 秒以内（設計 §7 の未計測） | **未計測**（この段では測っていない。実データの複製は 1.5 MB で、probe は体感 1 秒未満だが**値を書かない**） |

---

## 5. 自分で決めた点（1 行ずつ理由）

1. **`settings.json` をスナップショットに入れた**（人が読める設定の控え）。指示書は「`settings` を取る」と言うが、
   **契約 `backup-manifest` の `includes` は 4 つの欄（`db` / `sidecar` / `export` / `library`）で固定**
   （`additionalProperties: false`）なので、manifest には宣言できない。設定そのものは DB にも入っている。
2. **増分は「同じボリュームなら `os.link`、駄目なら写す」**。「コピーしない」を満たしつつ、
   **各スナップショットが単体で戻せる**（前のスナップショットを消してもリンクが中身を保つ）。
3. **写しの DB は `PRAGMA journal_mode = DELETE` に戻す**（＋ `-wal` / `-shm` を消す）。
   online backup は元の WAL の印ごと写すので、そのままだと写しの隣に `-wal` が生えた（probe で実測）。
   **戻すときに `-wal` を別扱いしなくて済む**ように 1 ファイルで完結させた。
4. **`pre-migrate-*`（版を上げる前の控え）は掃除の対象にしない。** 版が上がるのは稀で、
   1 つ 1 つが「その版の最後の姿」。**一覧には出す**（`kind: "pre-migrate"`）。
5. **`GET /api/health/db` は「読み取り専用で起動している」なら 503**（壊れている・版が新しい・
   控えが取れない）。DB そのものが綺麗でも**このアプリは書き込めない**ので、番号で示す
   （本文に `read_only` / `mode` / `guidance` が入っているので画面はそのまま案内できる）。
6. **`restore --force` の意味を「manifest が読めない・写しの DB が `quick_check` に通らない」を
   承知の上で進む**に決めた（危ない側を既定にしない）。`integrity_check` は `--force` でも外さない
   （通らなければ**元に戻す**）。
7. **`restore` の退避先は `<backup_dir>/pre-restore-<日時>/`**（**`<data>` の外**）。
   設計は「先に自動バックアップ」とだけ書いている。`<data>` の中に置くと `<data>` を消した話と論理が閉じない。
8. **日付（`<YYYYMMDD>`）は現地（JST）**。ゴミ箱の日付と同じ規則（D-3）。`created_at` は UTC。
9. **`_db_gate` は `local_only` の middleware の中**（別の middleware にすると順序が逆になり、
   壊れた DB のときだけ 403 が 503 に化ける）。
10. **読み取り専用ではサムネイルを作らない**（`<data>` に書き足さない）。既にある物は返す。
11. **読み取り専用では pHash / dHash を計算しない**（書けないのに計算しても捨てるだけ。
    `attempt to write a readonly database` を 500 にしない）。
12. **`app_version` は `__version__`（`0.0.1-proto`）**。契約は `minLength: 1` なので形は自由。
13. **`POST /api/backup` の `out`（置き場の一時指定）を受ける**。設計 §3.3 の本文にある。
    **`<data>` の中は 422** で断る。
14. **一覧の各スナップショットに `kind`（`daily` / `manual` / `pre-migrate`）を足した**。
    契約は無い（口の応答）ので足せる。画面（P8-5）が「いま取る」と日次を区別できる。
15. **テストの置き場は `tests/.tmp/_backups`**（`conftest.py` の autouse）。向けないと、
    `TestClient` を使うテストのたびに**利用者のホーム**へスナップショットを作り、
    **保持 7 世代の掃除で本物の控えを消す**（実行の終わりに消す）。
16. **CLI は `ReviewError` を終了コード 2 と 1 行の stderr で返す**（スタックトレースを出さない）。
17. **`rebuild-metadata` は「空いている欄だけ」埋める**（`None` / `""` / `[]` / `{}` は空）。
    **DB にある値は上書きしない**（正は DB、sidecar は組み直しの種。専門 §5.6）。
18. **`include_library` の復元は「記録した場所に無いときだけ」**（**在る物には触らない**。
    画像は利用者の資産）。
19. **`allow-stage3` の `{id}` は `root.path`（正規化した鍵）か、登録した表示のパス**。
    `GET /api/roots` の `id` をそのまま渡せる。
20. **`POST /api/roots/{root_id:path}/allow-stage3` はパス全体を受ける**（`/` を含む鍵なので）。
21. **増分の相手は日次と「いま取る」だけ**（`pre-migrate-*` は DB しか持たないので、
    相手にすると `sidecar` / `export` の共有が効かない）。
22. **`restore` で `<data>/db.sqlite3` を置き換えられないときは 409 `restore_failed`**
    （「アプリを止めてから戻してください」の 1 行）。**500 にしない**（アプリが動いていると
    Windows は置き換えさせない。人が読める理由を返す）。
23. **`inspect_db` の案内に出す置き場は設定も見る**（環境変数 → 設定 → 既定）。
    `create_app` が既定を決め打ちすると、`D:\backups` を設定している人の控えが
    知らない場所に落ちる（`backup_before_migrate` も同じ順で決める）。

---

## 6. 申し送り

1. **`POST /api/backup/restore` は作っていない**（設計 §0.15 の 15・点検 G8 のとおり。**復元は CLI**）。
   `deletions.json` の契約も作っていない。
2. **画面（P8-5）に渡す形**: `GET /api/backup` が `backup_dir` / `snapshots`（`kind` つき）/
   `last_at` / `next_run_at` / `next_run_note` / `today_done` / `last_error` / `last_error_at` /
   `read_only` を返す。`GET /api/health/db` は 200/503 と `guidance` を返す。
   **「いま取る」は `POST /api/backup`**（人だけ）。置き場の変更は `PATCH /api/settings`。
   **`frontend-design.md` に先に文言を足す**のは P8-5 の約束（§5）。
3. **`last_error` は次の成功で消える**（「最後の失敗」だけを残す）。画面は
   `last_error_at` と一緒に出すのがよい。
4. **環境変数 `IMAGE_REVIEWER_BACKUP_DIR` は設定より優先**（専門 §5.2 の 1）。
    そのため env を立てたまま `PATCH /api/settings` しても `backup_dir` は変わらない
    （`backup_dir_source: "env"` を見れば分かる）。実機の運用では env を使っていないので既定は設定。
5. **`rebuild-metadata` に「上書きする」道は無い**。sidecar の値が DB と食い違っても DB を採る
   （専門 §5.6）。食い違いを見つけて出す仕組みは**未実装**（専門 §5.6 の「未確認」のまま）。
6. **`restore` は `sidecar/` と `export/` を上書きで戻す**（スナップショットが正）。
   新しい側の値を守りたい場合は、戻す前に `<data>` を退避すること（`pre-restore-*` は DB だけ）。
7. **実データは語 0 行・削除 0 行・除外の理由が空**（2026-10-18 時点）。P8-3 の記録にある
   「語 155 行」は**そのときの複製**の話で、実データには入っていない。
8. **監査への手順**:
   ```
   uv run --no-sync pytest -q
   node tools/gui_smoke.mjs
   uv run --no-sync python tools/probe_p8.py --all        # 実データは mode=ro のみ・複製で
   uv run --no-sync --with jsonschema python tools/check_contract_p8.py
   .venv\Scripts\python.exe -X utf8 .tmp-audit-redo\p8-4\gui_setup.py   # 画面検査の複製
   ```
   **`probe_p8.py` は自分の作業場（`.tmp-audit-redo/p8probe`）を消す**（`--keep` で残す）。
9. **`tests/conftest.py` に autouse の env を足した**。既存のテストには影響しない（408 件がそのまま緑）。

---

## 7. 設計の穴（気づいた点）

1. **`PATCH /api/settings` は存在しなかった。** 設計 §3.3 と §0.15 の 14 は「**既存の口**に
   `backup_dir` を足す」と書いているが、実装には設定の口が 1 つも無かった。
   → P8-4 で `GET` / `PATCH /api/settings` を作った（`backup_dir` だけ）。
2. **`GET /api/roots` が無い。** `POST /api/roots/{id}/allow-stage3` の `{id}` を人が知る道が
   無かった（`root` の主キーは正規化したパスなので画面に出せない）。→ 一覧の口を足した。
3. **§10-12 の「300 ページ目なら `quick_check` は `ok`」は成り立たない**（§3）。
   P8-1 の `phash_band` の索引が載ったためで、**「例外だけを壊れているに数える」設計だと
   この形を健全と誤判定する**。→ 行が `ok` 1 行でなければ壊れている、に変えた。
4. **§1.2 の線 10 と §3.3 で「いま取る」のフォルダ名が食い違う。**
   線 10 は「`<YYYYMMDD>/` を一時に作って `os.replace` で差し替え」、§3.3 は
   「`<YYYYMMDD>-<HHMMSS>/`」。**§3.3（新しい方）を採った**（差し替えではなく**必ず新しい
   フォルダ**。朝の物を返さないのが点検 B2 の要求）。原子性は一時フォルダ → `os.replace` で守っている。
5. **契約の `includes` に `settings` の欄が無い**（指示書は「`settings` を取る」と言う）。
   → `settings.json` は入れるが manifest では宣言できない（§5 の 1）。
6. **§0.12-6 の「版を上げる前に自動バックアップ」は §8.1 のテスト表にも §8.4 にも無い。**
   → 実装した（`pre-migrate-*`。取れなければ版を上げない）＋テスト 2 本。
7. **`restore` の退避先が設計に無い**（専門 §5.3 は「先に自動バックアップを取ってから置き換える」
   とだけ）。→ `<backup_dir>/pre-restore-<日時>/` に決めた。
8. **`restore` が `sidecar/` / `export/` を上書きで戻すことは設計が黙っている**
   （専門 §5.3 は「それも `<data>` へ戻す」だけ）。→ 上書き（スナップショットが正）と決め、
   申し送り 6 に書いた。
9. **読み取り専用の理由が 3 つある**（壊れている・版が新しい・控えが取れない）のに、
   設計 §3.4 のエラーの表は `503 read_only` を 1 行しか持たない。→ `mode` と `reason` を
   応答に足して区別できるようにした。
10. **`GET /api/health/db` の番号が設計に無い**（§3.3 は「結果を返す」だけ）。
    → **読み取り専用なら 503**（§5 の 5）と決めた。

---

## 8. 実データが無傷であること（証拠）

```
probe_p8.py --all の前後: 263 枚 / 判断 3 件 / 削除の台帳 0 行 / 画像の署名（size と mtime の合計）同じ
.data: db.sqlite3 1544192 バイト（2026/10/18 0:07:26 のまま）・db.sqlite3-wal 4190072（5:19:38 のまま）
       sidecar/（2026/10/15 10:05:00）・export/（2026/10/18 5:19:05）・thumbs/（2026/10/15 8:58:22）
.backup/: 7 フォルダ（pre-p4 / pre-p7×3 / pre-p8-0 / pre-p8-1 / pre-p8-2）**1 つも消していない**
%USERPROFILE%\image-reviewer-backups: **作られていない**（テストは tests/.tmp/_backups へ向けた）
8790（利用者のアプリ）: 動いたまま（止めていない）。8791 の複製サーバは検査の後に止めた
```

- **1 件の事故と、その後の手当て（申告）**: 画面検査の下ごしらえで、最初の版が
  **複製の外の実データの画像を `shutil.move` しようとして `WinError 5` で失敗した**
  （`C:\ai\ComfyUI_windows_portable\...\132800_00001_.png`）。`os.rename` が失敗した後に
  `copy2` が走って**複製側に写しが 1 つできた**が、**元のファイルは 1 バイトも変わっていない**
  （1487627 バイト・mtime 2026/10/15 9:09:06 のまま。`Test-Path` と `Get-Item` で確認）。
  以後は `gui_setup.py` で**`lib` の下だけを選び、動かす直前に `startswith(lib)` を再確認**する
  二重の守りを入れた。写しは次の `gui_setup.py`（作業場の作り直し）で消えている。

---

## 9. 追記（2026-10-18 08:30。**P8-4 の監査の指摘を直した後**）

**この記録の本文は直していない**（そのとき何をしたかの記録なので）。**本文と今の実装が違う所**だけここに書く
（指摘ごとの仕分けは [`p8-4-audit-triage.md`](p8-4-audit-triage.md)）。

| # | 本文の記述 | いまの実装（監査の直し） |
| --- | --- | --- |
| §5-7 | 退避先は「`<backup_dir>/pre-restore-<日時>/`」 | **`backup_dir` を渡したときはそこ、渡さなければスナップショットの隣**（CLI は渡さない＝USB の写しから戻すと退避も USB。監査 D-3。**記録に合わせず、実装に記録を合わせた**） |
| §5-22 | 「`restore` で置き換えられないときは 409」 | **順序を「一時名へ `copy2` → `os.replace` → `-wal` / `-shm` を消す」に直した**（前は `unlink` が先で、掴まれていると**トレースバックで落ちていた**。監査 C-2） |
| §3 の「4 つ」 | スナップショットに出来る物 | **5 つ**（`settings.json` を含む。監査 D-9） |
| §4 の線 10 | `integrity_check` は「未実装」 | **写しを作り終えた後に `quick_check` → `integrity_check`**（通らなければ採用しない。監査 B-1） |
| §1 の `backup.py` 1276 行 | — | **1578 行**（+302。検査・`pre-topup-*`・sha256 の照合・順序の直し・D の 13 件） |
| §4 の線 10〜12 | — | **線 10/11/12 の合否は変わらない**。足したのは「壊れた物を採用しない」の検査（[`p8-design.md`](p8-design.md) §8.1 の 72〜87） |

- 実行した確認: `pytest -q` **472 passed × 3 回**・`node tools/gui_smoke.mjs` **232 ok / NG 0**・
  `node tools/gui_layout.mjs` の **9 画面すべて ok**・壊し試験 **18/18 が落ちる**・
  `import image_reviewer.app` が実データを触らないこと（`.data` の mtime と大きさが前後で同じ）。
- **G-9**: `.backup/pre-p8-4-20261017-232148/`（263 枚・判断 3 件・`integrity_check ok`）を取った。
  **実データには触っていない**（`mode=ro` と `backup()` だけ）。
