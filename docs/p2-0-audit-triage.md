# P2-0（スキーマ v7）の監査の指摘の仕分け（2026-10-20）

- 監査: [`p2-0-audit-report.md`](p2-0-audit-report.md) — **判定: 条件つきで使える**。条件は
  **B-1（形のガード）**・**B-2（期待値が実装の側にある）**、ほかに **C-1**（`-shm` で揺れる試験）と
  **C-2 / C-3 / D / E / G**。
- 直した人: DeepSeek（dsh）。**監査の推奨はすべて採用**（ただし**この小段で直す物**と
  **P2-1 / v8 へ送る物**を分けた。見送った物は §5 に理由と行き先を書いた）。
- **正とした文書**: 監査の「直し方（推奨）」・`docs/design.md` §5.1 / §5.3 / §6.1 / §16.9・
  `docs/p2-0-implementation.md`。**依頼（この修正）の指示**: 「2 件とも**期待値が実装の側にある**型の穴」
  （B-1・B-2）＋ **`tools/gui_layout.mjs` の `pickable`**（前の監査の B-2 / G-4(b)）。
- **触っていない物**: **実データ `.data/`**（`mode=ro` の読みだけ。**v6 のまま**・`asset` 463 行・
  `deleted_at` 194・`deletion_log` 194 は全部片付け済み）・**画像（1 枚も動かしていない）**・
  **`.backup/` の 12 個**・**8790（GET も打っていない）**・`git`（**コミットしていない**）・
  **他の担当の `.tmp-p2-0/`**（D-6。§5）。
- 環境: 複製はすべて `C:\work\image-reviwer\.tmp-p2-0-fix\` の下に絶対パスで作った。
  **`IMAGE_REVIEWER_DATA` を付けずにサーバ・アプリを起こしていない**（`create_app()` が断る）。
  **壊し試験の子には `IMAGE_REVIEWER_DATA=.tmp-p2-0-fix\safety-net` を渡した**（安全網）。
  複製サーバは **8791**、**壊し試験の写しのサーバは 8792**。Chrome は `gui_layout` だけ（CDP 9334）。

## 0. 直したこと（結論）

| 指摘 | 何が穴だったか | 直した物 | 実測 |
| --- | --- | --- | --- |
| **B-1** | `_check_v7_shape` が**列の名前と索引の `tbl_name` しか見ない**。同じ列名で CASCADE も CHECK も無い `folder` と `ix_folder_parent ON folder(name)` を先に置くと **v7 になった** | **形で見る**ガード（`PRAGMA table_info` の型・NOT NULL・既定・主キー／`foreign_key_list` の CASCADE／`index_info` の列／`sqlite_master.sql` の CHECK＋**SAVEPOINT で不正な `kind` を試す**）。落ちる文に**何が違うか**を書く | 実データの複製で **偽の v7 2 通りとも `RuntimeError`・版は 6 のまま**（§3-2） |
| **B-2** | 形の試験が**期待値を `db.V7_INDEXES` / `V7_COLUMNS` から作る**。X5・X11・X12・X16・X18・X20 の 6 通りが全 591 件を通った | 期待値を**試験の中にリテラルで書く**（表・列の形・索引の名前と列・FK・既定） | **6 通り × 2 変種（DDL だけ／ガードも騙す）＝12 通りが全部落ちた**（§3-3。**生き残り 0**） |
| **C-1** | `_files` が `db.sqlite3-shm` の中身まで比べ、40 回に 1 回落ちる | `-shm` を数えない（`test_data_dir_guard.py` と同じ） | 1 行。`-wal` は残す（書いた証拠） |
| **追加** | `gui_layout` の `pickable` を**画面のボタンの数**から作り、段 1 の行のボタンが消えても 4 幅 ok | 期待値を **`GET /api/pending-deletes` の `stage` と `closeable`**（＋`GET /api/trash`）から作る（G-4(b)） | **G2（移すを消す）・G4（2 つとも消す）で 4 幅とも NG**（§3-4） |

**判定（直した後）: 監査の条件（B-1・B-2）は満たした。** 実データは v6 のままで、利用者が
8790 を立ち上げ直したときに控え（`pre-migrate-*`）を取ってから v7 になる道は変えていない
（`app_gate.py` の `ok` で**実データの複製が v6 → v7 に上がり、463 行が変わらない**ことを再確認）。

---

## 1. 指摘ごとの 1 行

| # | 指摘（監査） | どうした | どこ |
| --- | --- | --- | --- |
| **B-1** | ガードは**名前しか見ない**。`squat2`（同じ列名・CASCADE / CHECK 無しの `folder` ＋ `ix_folder_parent ON folder(name)`）が v7 になる | **採用（推奨どおり・形で見る）**。`V7_TABLE_SHAPE`（型・`NOT NULL`・既定・主キーの位置）・`V7_FOREIGN_KEYS`（`from → table(to) ON DELETE`）・`V7_INDEXES`（名前・表・**列の並び**）・`V7_CHECK_SQL`（`sqlite_master.sql` を空白を詰めて比べる）を足し、`_check_v7_shape` が全部見る。**語彙は文と振る舞いの両方**（`SAVEPOINT` で `kind='robot'` を入れて拒否されるか。**必ず `ROLLBACK TO`**）。落ちる文は「**v7 の索引 ix_folder_parent の列が parent_id,position でない（いま name）**」のように**何が違うか**を書く | `db.py` `V7_TABLE_SHAPE` / `V7_FOREIGN_KEYS` / `V7_INDEXES` / `V7_CHECK_SQL` / `_schema_sql()` / `_check_v7_shape()` |
| **B-1（試験）** | 監査の `squat2` を捕まえる試験が無い（列名だけの試験は通る） | **試験 3 本を足した**: ①CASCADE の無い `folder` ②同じ表・同じ名前で**列が違う索引** ③`kind` の `CHECK` が無い `folder`。どれも**ガードが名前だけを見る形に戻すと落ちる**（§3-3 の b 変種と同じ道） | `tests/test_p2_0.py` `test_a_catalog_table_without_cascades_is_refused_loudly` / `test_a_catalog_table_with_the_wrong_index_columns_is_refused_loudly` / `test_a_catalog_table_without_the_kind_check_is_refused_loudly` |
| **B-2** | X5・X11・X12・X16・X18・X20 の 6 通りが生き残る。根は試験が**期待値を `db.V7_*` から作る**こと | **採用（推奨どおり・リテラル）**。`test_v7_adds_the_catalog_tables_columns_and_indexes` に **`folder` / `folder_member` の全列の (型, NOT NULL, 既定, 主キー)** と **`asset.source`**、**2 本の索引の (表, 列の並び)** をリテラルで書いた。`test_the_catalog_foreign_keys_are_declared_as_cascades` も **`(from, 参照する表, 参照する列, ON DELETE)` のリテラル**にした。**`db.V7_*` を読む行は試験から消した**（grep 0） | `tests/test_p2_0.py` |
| **C-1** | `test_get_endpoints_write_nothing_on_a_v7_database` が `-shm` で 40 回に 1 回落ちる | **採用**。`_files()` が `db.sqlite3-shm` を数えない（**`-wal` は残す**。中身が変われば書いた証拠）。理由を docstring に書いた | `tests/test_p2_0.py` `_files` |
| **C-2** | 名前の取り合いで `create_app()` が例外のまま抜け、**版 6 だが v7 の物が半分ある** DB と控えが積もる | **持ち越し（P2-1 の頭。§5-1）**。いまの実データと `.backup` の 14 個に `ix_folder_*` は無く、起きない。**大声で止まる**点は変えない。`inspect_db` に `mode=ro` の形の検査を足して `schema_conflict` で読み取り専用に上げる案は §5-1 に書いた | — |
| **C-3** | P7 の控えの `preset` / `watcher_state` が v7 で残る（段をまたぐ穴） | **採用（v8 への申し送り）**。設計 §16.9 に「その版で足すときに B-1 の形の検査を通す。`current == 6` の道で 0 行なら落としてよい」と書いた | `docs/design.md` §16.9 |
| **D-1** | `elif current == 6` は正しいが記録の理由が強すぎる | **変更なし**（`elif` は残す。記録 §2.1 の「一生持たない」は「**最初の 1 回の起動が壊れる**」と読み替える。試験は既にある） | `docs/p2-0-implementation.md` §9 |
| **D-2** | 記録の「既存の 27 本」は **26 本** | **記録を正した**（26 本。v7 の新規で 28 本。衝突は無い） | `docs/p2-0-implementation.md` §9 |
| **D-3** | `pre-migrate-*/manifest.json` に前後の版が無い | **変更なし**（P2-0 の変更ではない。版は控えの DB の `user_version` で読める。P8-4 以来の形） | — |
| **D-4** | 実装者の壊し試験の数え方（巻き添えの 13 failed を欠陥の証拠に数えていた） | **採用（数え方を変えた）**。この修正の壊し試験は **①変異が 1 回だけ当たったことを機械で確かめる ②どの写しの `db.py` を読んだかを毎回出す**（`MODULE …\mut\src\…`）。**生き残り 0** | `.tmp-p2-0-fix/mutate.py`（再現手順 §3-3） |
| **D-5** | `asset.source` の既定 `'scan'` は `ALTER` の都合。書き忘れは黙って `'scan'` | **設計に反映**（§5.1 を `DEFAULT 'scan'` ＋ `CHECK` に直した）。**P2-1 の各経路で値を確かめる**申し送りはそのまま | `docs/design.md` §5.1 |
| **D-6** | 実装者の `.tmp-p2-0/` に**実データの複製**が残っている（消すのを勧める） | **私は消していない**（他の担当の一時物を、依頼の範囲外で消さない。§5-2）。**残っている物の名前をここに書く**（`gui-data`・`data-real-v7`・`data-real-fail`・`backups-real`・`gui-backups`）。**早めに消すこと** | — |
| **E-1** | §5.3 の DDL に `folder.deleted_at` が無いのに §6.1 が論理削除を要求 | **採用（実装が正しい）**。**§5.3 に `deleted_at` を足した** | `docs/design.md` §5.3 |
| **E-2** | §5.3 は `kind` の語彙が注記だけ | **採用（実装が正しい）**。**`CHECK (kind IN ('manual','smart'))` を §5.3 に書いた** | 同上 |
| **E-3** | §5.1 は `source` に既定なし | **採用（実装が正しい）**。`DEFAULT 'scan'` ＋ 5 語の `CHECK` に直した（`ALTER` のため。実データ 463 枚はすべて走査） | `docs/design.md` §5.1 |
| **E-4** | §5.1 の注記「`kind='url'` のときの出所」が誤り（`kind` に `'url'` は無い） | **採用**。`source='url'` に直した | 同上 |
| **E-5** | 指示書のスケッチと設計の字（`folder_member` など 4 点） | **変更なし**（設計の字が正しい。実装のまま） | — |
| **E-6** | §10.2 のフィールド名と列名の対応表が無い | **持ち越し（P2-1。§5-3）**。設計 §16.9 に「P2-1 で対応表を書く」と残した | `docs/design.md` §16.9 |
| **G-1** | v7 の形を変えられるのは利用者の再起動まで。**(a) B-1・B-2・G-2 を直してから再起動** | **採用（a）**。B-1・B-2 は**この修正で直した**。G-2 は**P2-1 の頭で足す**（§5-4。実データはまだ v6 なので、再起動前に足せる） | この文書・§16.9 |
| **G-2** | 同じ親の中の名前の一意はサービス層か表か → **(b) 表の部分一意索引** | **採用（b）を P2-1 で**。`ux_folder_name ON folder(coalesce(parent_id, ''), name) WHERE deleted_at IS NULL`。**P2-0 の v7 の形は変えない**（この修正で形をガードと試験で固定したので、索引を足すときは DDL・ガード・試験を同じ回に直す）。§16.9 に残した | `docs/design.md` §16.9 |
| **G-3** | `folder.deleted_at` は残す | **採用**（E-1）。§5.3 に反映 | `docs/design.md` §5.3 |
| **G-4** | 論理削除のフォルダを木から外す引き方は `ix_folder_parent` のまま | **採用（変更なし）** | — |
| **G-5** | P7 の控えの `preset` / `watcher_state` は v8 で形を検査 | **採用（v8）**（C-3 と同じ） | `docs/design.md` §16.9 |
| **F（壊し試験）** | 監査の 20 通りのうち 6 通りが生き残った | **採用（B-2 で全部落ちる形にした）**。§3-3 の 12 通り（6 通り × 2）で**生き残り 0**。**変異の当たり回数と読んだモジュールのパスを毎回出した** | この文書 §3-3 |
| **追加（前の監査 B-2 / G-4(b)）** | `gui_layout` の `pickable` を画面のボタンから作るので、**段 1 の行のボタンが消えても 4 幅 ok** | **採用（G-4(b)）**。期待値を **API**（`stage===1` と `closeable`。ゴミ箱は `GET /api/trash`）から作る。**門も期待値も API**（画面のボタンが 0 でも門が開く）。`段 1 の印` と API を突き合わせる検査も残した | `tools/gui_layout.mjs` `expectedPicksOf()` |

---

## 2. 作った物・触った物（行数）

行数は `read_bytes().count(b"\n")`（最終形）。「+ / −」は `git diff --numstat`。

| ファイル | 行数 | + / − | 何をしたか |
| --- | --- | --- | --- |
| `src/image_reviewer/db.py` | 1050 → **1174** | +144 / −20 | **B-1**: `V7_TABLE_SHAPE`（型・NOT NULL・既定・主キー）・`V7_FOREIGN_KEYS`・`V7_INDEXES`（名前・表・列）・`V7_CHECK_SQL`・`_schema_sql()`・`_check_v7_shape()` の書き直し（**形・CASCADE・索引の列・CHECK・SAVEPOINT の振る舞い**）。`V7_COLUMNS` は `V7_TABLE_SHAPE` に統合 |
| `tests/test_p2_0.py` | 602 → **737** | +157 / −22 | **B-2**: 期待値のリテラル化（列の形・索引の列・FK）。**B-1 の試験 3 本**を追加。**C-1**: `_files` が `-shm` を数えない。**14 → 17 件** |
| `tools/gui_layout.mjs` | 2034 → **2087** | +67 / −14 | **追加**: `expectedPicksOf()`（API から `advances` / `closeRowsNotStage1` / `trashCloses` / `closes` / `picks`）。門と等号の期待値を API に。要約行に API の期待値を出す |
| `docs/p2-0-audit-triage.md` | **新規（この文書）** | — | 指摘ごとの 1 行・実行した結果・見送り |
| `docs/design.md` | 2375 → **2408** | +37 / −4 | §5.1（`source` の既定と `CHECK`・`source_url` の注記）・§5.3（`deleted_at`・`kind` の `CHECK`・形のガードの 2 段落）・**§16.9（P2-0 で確定したこと）** |
| `docs/p2-0-implementation.md` | 339 → **377** | +38 / −0 | **§9「監査の指摘を直した」**（B-1・B-2・C-1 の要約、**記録の 2 つの誤り**（`INDEXED BY` と「27 本」）の訂正、D-1 の読み替え、D-6 の残骸） |
| `README.md` | 413 → **417** | +9 / −5 | 数を実測へ（**597 件・415 検査**）。`pickable` を API に変えた 1 段。P2-0 の監査の仕分けを文書表に足した |

**触っていない物**: `apps/gui/*`（画面のコードは 1 行も変えていない。壊し試験は**写し**を別の
サーバで立てて行った。§3-4）・`src/image_reviewer/` の `db.py` 以外・`schemas/`・`pyproject.toml`・
`uv.lock`・`.data/`・`.backup/`・他人の `.tmp-*`。

---

## 3. 実行したコマンドと結果

`$env:UV_CACHE_DIR = "C:\work\image-reviwer\.uv-cache"`、`uv run` はすべて `--no-sync`。
`cd C:\work\image-reviwer`。

### 3-1 三点セット

| 何を | 結果 |
| --- | --- |
| `uv run --no-sync pytest -q`（変更前） | **594 passed**（監査の後の作業ツリー。`test_p2_0` は 14 件） |
| `uv run --no-sync pytest -q`（変更後） | **597 passed・0 failed**（＋3。`tests/test_p2_0.py -q` は **17 passed**） |
| `node tools/gui_smoke.mjs` | **415 ok / NG 0** |
| `gui_layout` 11 本 × 4 幅（複製サーバ 8791。§3-4） | **52 ok / NG 0・11 本とも exit 0**（比較は 3 窓 × 4 ＝ 12 行） |

### 3-2 B-1: 偽の v7 をガードが落とすか（**実データの複製**で `create_app()`）

実データは `mode=ro` で読み、`sqlite3.Connection.backup()` で複製（`.tmp-p2-0-fix/gate-*`）を作り、
**複製にだけ**偽の `folder` を置いて、**別プロセス**で `create_app()` を呼んだ
（`.tmp-p2-0-fix/app_gate.py`）。実データには 1 バイトも書いていない。

| 複製に置いた物 | `create_app()` | 版（前 → 後） | 落ちる文（そのまま） |
| --- | --- | --- | --- |
| 何も置かない（対照） | **開いた**（`mode=ok`） | 6 → **7** | — （`asset` **463 行のまま**。`quick_check ok`） |
| **同じ列名・`NOT NULL` はあるが CASCADE も CHECK も無い `folder`** ＋ `ix_folder_parent ON folder(name)`（監査の `squat2`） | **`RuntimeError`**（exit 3） | **6 のまま** | `v7 の外部キー folder.parent_id → folder(id) がありません（設計 §5.3 の \`ON DELETE CASCADE\` が効きません）` |
| **正しい形の `folder`**（CASCADE・CHECK・NOT NULL あり）だが **`ix_folder_parent ON folder(name)`** | **`RuntimeError`**（exit 3） | **6 のまま** | `v7 の索引 ix_folder_parent の列が parent_id,position でない（いま name）` |

- 前の版は 1 行目が **`schema_version=7`・`mode=ok` で開いてしまった**（監査 B-1 の `squat2`）。
  いまは**同じ入力で止まる**。**版は 6 のまま**（次の起動でやり直せる）。
- 2 行目は**監査が名指しした文**（「索引 ix_folder_parent の列が parent_id,position でない（いま name）」）
  と同文になった。**何が違うかが読める**。
- **名前の取り合い（監査 C-2）の振る舞いは変えていない**（同じく例外で止まる。版 6 のまま
  `folder_member` と `asset` の 3 列は先に確定する。**C-2 は持ち越し**＝§5-1）。

### 3-3 B-2: 監査が生かした 6 通りを、いまの試験は落とすか

`.tmp-p2-0-fix/mutate.py`。`src` の写しを `mut/src` に置き、`sys.path` の先頭から読み
（毎回 `MODULE …\mut\src\image_reviewer\__init__.py` を出して**写しを読んだ証拠**にした）、
**変異が 1 回だけ当たったこと**を機械で確かめてから `tests/test_p2_0.py` を丸ごと回した。
**2 変種ずつ**作った: **`a`＝DDL だけ**（監査が実際に作った変異。**ガード**が落とすか）／
**`b`＝DDL とガードの期待値（`V7_*`）の両方**（**ガードを騙す**。**試験**が落とすか）。

| 変異 | a: DDL だけ | b: ガードも騙す |
| --- | --- | --- |
| X5 `ix_folder_member_asset` を `folder_id` に | **14 failed・1 error**（ガード: `v7 の索引 ix_folder_member_asset の列が asset_id でない（いま folder_id）`） | **1 failed**（`test_v7_adds_…`。`ix_folder_member_asset の列が folder_id でない（期待 asset_id）`） |
| X11 `ix_folder_parent` を 1 列に | **14 failed・1 error**（ガード: `… の列が parent_id,position でない（いま parent_id）`） | **2 failed**（形の試験・**索引の列の試験**） |
| X12 `folder_member.added_at` の NOT NULL を外す | **16 failed・1 error**（ガード: `v7 の表 folder_member.added_at の形が違います: \`NOT NULL\` がありません`） | **1 failed** |
| X16 `folder_member.position` の NOT NULL を外す | **16 failed・1 error**（ガード: `… folder_member.position …`） | **1 failed** |
| X18 `folder.name` の NOT NULL を外す | **13 failed・1 error**（ガード: `… folder.name …`） | **4 failed** |
| X20 `ix_folder_member_asset` を DDL とガードの両方から消す | **14 failed・1 error**（ガード: `v7 の索引 ix_folder_member_asset を folder_member に作れませんでした（同じ名前が どこにも無い にあります）`） | **1 failed**（形の試験: `ix_folder_member_asset が無い（索引を DDL から外すと気づかない）`） |
| 対照 X0（変異なし） | **17 passed** | — |

**生き残り: なし。** 前の版で 0 failed だった 6 通りが、**どちらの変種でも落ちる**。
**試験は `db.V7_*` から期待値を作らない**（`tests/test_p2_0.py` に `db.V7_*` が出るのは**docstring の
2 か所だけ**で、期待値は関数の中のリテラル。`INDEXED BY` も 0 件）。

### 3-4 `gui_layout` の `pickable`（前の監査の B-2 / G-4(b)）

実データの複製（`.tmp-p2-0-fix/gl/data`。`backup()`・`asset` 463 行・**画像は写さず実データを
読むだけ**）に、`gui_layout_seed.py --tags --exclusion --stage3 --backup-error` と、
**段 1 の台帳 1 行**・**段 3 の台帳 1 行**（保留の実体は複製）を入れた。複製サーバは 8791
（`health/db`: v7・`quick_check ok`・FK 違反 0）。

| 何を | 結果 |
| --- | --- |
| 11 本 × 4 幅（変更後の `tools/gui_layout.mjs`） | **52 ok / NG 0・11 本とも exit 0** |
| `--screen pending`（1 幅ずつ見た中身） | **4 幅 ok**。`移す=1 片付け=1(0) チェック=1(期待 1) 選べる(API)=移す 1／片付け 0／ゴミ箱 0` |
| `--screen pending --ids`（段 1・2・3 を押す） | **4 幅 ok**（3 段とも「消す内容を確かめる」→実行 → 結果の 1 行） |
| **G2**（写しの `apps/gui/pending.js` から段 1 の「アプリのゴミ箱へ移す」を消す） | **4 幅とも NG**（`段 1 の行に「アプリのゴミ箱へ移す」（0/1。API の段 1）`）。exit 1 |
| **G4**（段 1 の行のボタンを 2 つとも消す） | **4 幅とも NG**（上の 1 件＋`一覧の行に「片付ける」（0/1。API の closeable）`）。`--ids` でも **4 幅 NG** |

- 写しは `mutgui/`（`src` と `apps/gui`）に作り、**`/api/health` の `gui_dir` が写しを指す**ことを
  確かめてから回した（`gui_dir=C:\work\image-reviwer\.tmp-p2-0-fix\mutgui\apps\gui`）。
  サーバは 8792。**`apps/gui` の本物は 1 行も変えていない**。
- **前の版の検査は G2・G4 を ok にしていた**（監査の実測）。いまは**期待値も門も API** なので、
  ボタンが 0 になると**門が閉じずに等号で落ちる**。

### 3-5 実データ（前後の署名）

`.tmp-p2-0-fix/sig.py`（`mode=ro`）を**変更の前と後**に回し、JSON を比べた。

- **全部同じ**（`identical: True`・差分の鍵 0）: `user_version` **6**・`quick_check ok`・`asset` **463**・
  `deleted_at` **194**・`deletion_log` **194（開いている行 0／閉じた行 194）**・`decision` 3・
  `phash_band` 7408・`folder` の表**無し**・`asset` の列は **v7 の 3 列が無い**・`db.sqlite3` の
  **sha256 と mtime と大きさ**・`.data` のファイル 679 個（名前・大きさ・mtime）・**`.backup` の 12 個**。
- **画像は 1 枚も動いていない（終わってから数え直した）**: 生きている登録 **263 件の `display_path` が
  すべて `is_file()`**（**消えた物 0**）。複製の `gui_layout` は実データの画像を**読んだだけ**で、
  段 2・3 の POST は `gui_layout` が差し替えた `fetch` が飲むので、**サーバは 1 件も消していない・
  動かしていない**（複製の台帳も**種まきの 2 行だけ**）。
- **8790 には GET も打っていない**（利用者のアプリは最後まで動いていた。`Get-NetTCPConnection` で
  8790 = pid 3636 のまま）。

### 3-6 後始末

- 複製サーバ: **8791・8792 を自分で止めた**（`/api/health` の `data_dir` が
  `.tmp-p2-0-fix\gl\...` であることを確かめてから **health の `pid`** を `taskkill /T`）。
  いま 8791〜8792 に何も居ない。**8790 は止めていない**（利用者の物）。
- **消した物（実データの写しを残さない）**: `.tmp-p2-0-fix/` のうち **DB の写し 12 個**と
  一時フォルダ（`gl/`・`gate-ok` / `gate-cascade` / `gate-index` / `gate-backups`・`mut/`・`mutgui/`・
  `fresh/`・`tmp/`）。**76.7 MB → 0.33 MB**。**実データ（画像と DB）の写しは 1 つも残していない**
  （監査 D-6 と同じ理由＝前回 `bfcc7b5` で写しが履歴に入った。**この修正では自分が作った写しだけ消した**）。
- **残した物**（`.tmp-p2-0-fix/`・gitignore 済み・0.33 MB）: スクリプト（`mutate.py`・`app_gate.py`・
  `make_gl_replica.py`・`make_mutgui.py`・`probe_shape.py`・`sig.py`・`check_images.py`・`inventory.py`・
  `linecounts.py`・`run_gl.ps1`・`show_mutations.py`）と、**結果の JSON**（`mutations.json` 12 通り・
  `app_gate.json` 3 通り・`sig-before.json` / `sig-after.json`）と、**`logs/`**（`gui_layout` 11 本の
  ログと壊し試験のサーバのログ）。**どれも再現手順はこの文書に書いた**。

---

## 4. 設計に反映したこと

| どこ | 何 |
| --- | --- |
| `docs/design.md` **§5.1** | `source` を `NOT NULL DEFAULT 'scan'` ＋ 5 語の `CHECK` に。`source_url` の注記を `source='url'` に（E-3・E-4） |
| `docs/design.md` **§5.3** | `deleted_at TEXT`（E-1）・`CHECK (kind IN ('manual','smart'))`（E-2）・**移行のあとに形（NOT NULL・既定・CASCADE・索引の列・CHECK）まで見る**（B-1）・**試験の期待値はリテラル**（B-2）の 2 段落 |
| `docs/design.md` **§16.9（新規）** | P2-0 で確定したこと（形のガード・期待値のリテラル・`-shm`・§5.1/§5.3 の反映・**G-2 は P2-1 で部分一意索引**・**C-2 は P2-1 の頭**・**C-3/G-5 は v8**・実データは v6 のまま） |
| `README.md` | **597 件・415 検査**（実測）・文書表に本 triage |
| `docs/p2-0-implementation.md` §9 | 監査で直した物の要約と、**記録の誤り 2 つの訂正**（「`INDEXED BY` で固定」は試験に無い／「既存の 27 本」は 26 本） |

---

## 5. 見送った物と理由（行き先つき）

1. **C-2（名前の取り合いで半端な DB が残る）は P2-1 の頭。** 直すには `inspect_db`（`mode=ro`）に
   `ix_folder_*` の名前の取り合いを足し、`create_app()` が `mode=read_only` / `reason=schema_conflict` で
   起動して案内する形が要る。**いまの実データと控え 14 個には `ix_folder_*` が無い**（監査の実測）ので
   起きない。**「大声で止まる」は変えない**（静かに進むより良い）。半端な DB を残す点は、
   取引で囲めない `executescript` の性質なので、次に触るときに `inspect_db` 側で先に見る。
2. **D-6（`.tmp-p2-0/` の実データの複製）は消していない。** 他の担当（P2-0 の実装者）の一時物で、
   この修正の依頼の範囲外。**並行作業のファイルを消さない**（家風）。残っている物を §1 の D-6 に
   名前で書いた。**実データの複製なので早めに消すこと**（`gui-data`・`data-real-v7`・`data-real-fail`・
   `backups-real`・`gui-backups`）。
3. **E-6（§10.2 のフィールドと列の対応表）は P2-1。** `smart_query` のフィールドの列挙と一緒に書く
   （§16.9 に残した）。
4. **G-2（同じ親の中の名前の一意）は P2-1 の頭で表に置く**（推奨 (b)）。**P2-0 の v7 の形はこの修正で
   変えない**——B-1 のガードと B-2 の試験が形を固定したので、索引を足すときは **`V7_CATALOG_DDL`・
   ガード・試験・`docs/design.md` §5.3 を同じ回に**直す。**実データはまだ v6 なので、利用者の再起動の
   前なら v7 の形として足せる**（後なら top-up か v8）。
5. **C-3 / G-5（P7 の控えの `preset` / `watcher_state`）は v8。** その版で足すときに B-1 の形の検査を通す。
   `current == 6` の道で **0 行なら落としてよい**（失う物が無い）。
6. **D-3（manifest に前後の版が無い）は P2-0 の変更ではない。** 控えの DB の `user_version` で読める。
7. **D-1（`elif current == 6` の理由）は文言だけ。** 記録 §9 に「**最初の 1 回の起動が壊れる**」と
   書き直した（`elif` は残す）。
