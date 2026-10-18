# P9（仕上げ）の実装の記録 — **性能の目標を実測で埋めた**

- 段: **P9**（`docs/design.md` §14。**§12.1 の「目標」の行を実測で裏づける**）
- 日付: 2026-10-18（JST）
- 正とした文書: [`design.md`](design.md) **§12.1**（目標値）・**§12.2**（効かせ方）・**§12.3**（P8 の実測）・
  **§14**（P9 の行）、[`p9-implementation-brief.md`](p9-implementation-brief.md)（この段の指示書）、
  [`handoff.md`](handoff.md) §3-1（未計測の一覧）・§3-0（P8-5 の条件）・§6（罠）
- 依頼: ①**§12.1 の目標の行を実測で埋める**（数を発明しない・未計測は未計測と書く・**届かない物は理由つき**）
  ②申し送りの処理（`design.md` への P8-6 の反映・**D-8**・**D-7**・768px）
  ③テストの締め（`pytest` 5 回・`gui_smoke`・`gui_layout` 11 本・README と handoff の数）
  ④**exe 化の判断**（調査と推奨まで。実装はしない）
- **触っていない物**: **実データ `.data/`（`mode=ro` と `os.stat` の読みだけ）**・**画像（1 枚も動かしていない）**・
  `ComfyUI`・8790（利用者のアプリ。**一度も止めていない**）・`schemas/`（契約は足していない）・
  `apps/gui/` の見た目（**文言 1 行だけ**足した。§4）・`pyproject.toml` / `uv.lock`。**`git` のコミットはしていない**。

## 0. 結論（先に 3 行）

1. **§12.1 の「未計測」は 0 になった。** 届かなかったのは **一覧 API の 1 行だけ**——
   目標 **p95 20 ms** に対して**実測 244.7 ms**（12 倍）。**目標は下げていない**。理由は
   **§12.2 の「一覧」（キーセット改ページ・概算の件数・最小の列）が実装に入っていない**ことで、
   必要な条件を §12.1 に書いた（**入れる段を別に立てる**）。
2. **測る途中で不具合を 2 つ見つけて直した**: ①`PRAGMA temp_store = MEMORY` が実装に無く、
   **1 万枚の `GET /api/assets` が 500 になっていた**（`%TEMP%` に書けない置き場で一時ファイルを作れない）
   ②`sqlite_error_handler` が**壊れていない DB に「バックアップから戻してください」と言っていた**
   （P8-6 の監査 D-8。語彙を分けた）。**どちらも P9 の計測をしようとして初めて出た**。
3. **exe 化の推奨は「今は作らない」。** 作れることは実測した（PyInstaller 6.22.3 が Python 3.14 で動き、
   `--onedir` が 23.7 秒・131.9 MB・起動 0.53 秒）が、**画面が出ない**（`gui_present: false`。
   `apps/gui` の解決が 1 か所足りない）。**配布しないなら要らない。**

## 1. 作ったもの（ファイルと行数）

行数は `read_bytes().count(b"\n")`（最終形）。

| ファイル | 行数 | 何をしたか |
| --- | --- | --- |
| **`tools/make_synthetic_db.py`** | **新規 250** | **1 万枚の合成 DB を作る**。本物の PNG を 1 万枚書き（**先頭 24 枚だけ 1024x1024**、残りは 96x96）、**`scan.scan()` をそのまま通して登録する**（`INSERT` を直に書かない＝`(path, size, mtime_ns)` が本物と一致し、2 回目の走査が「差分なし」になる）。PNG には **ComfyUI の API 形式の `prompt`** が入っている（来歴が本物の道で入る）。判断とタグも少し入れる。**`--force` を付けないと作り直さない** |
| **`tools/probe_p9.py`** | **新規 770** | **§12.1 の計測**（`--list` / `--thumbs` / `--compare` / `--decide` / `--scan` / `--delete` / `--relink` / `--library` / `--real` / `--all`）。**サーバ内で測る**（`TestClient`＝ASGI 直叩き。**ネットワークを挟まない**）。土台（`/api/health`）の p95 も一緒に出す。**別々の入力**で測り、**何回の p95 / 中央値か**を出す |
| `src/image_reviewer/db.py` | 879 → **886** | **`PRAGMA temp_store = MEMORY` と `mmap_size`** を接続に掛ける（§12.2 に元から書いてあった物）。**`cache_size = -65536` は入れなかった**理由をその場に書いた（§3-2）。`cache_size` / `mmap_size` は**壊れた DB では投げる**ので最善努力 |
| `src/image_reviewer/api/__init__.py` | 142 → **186** | **D-8**: `sqlite_error_handler` の語彙を分けた。**壊れている仲間だけ 503**（`malformed` / `not a database` / `corrupt` / `encrypted` / `disk I/O error`）、**他は 500 `sqlite_error`**（復元を勧めない）。判定は `_is_corruption()` の 1 か所 |
| `apps/gui/app.js` | 535 → **548** | **一覧で切った枚数を上部に出す**（`limit=2000`）。`state.listed` / `state.total` を控え、`total > listed` のときだけ「10000 枚（先頭 2000 枚を表示）」（**数を黙って捨てない**） |
| `tests/test_db.py` | 876 → **909** | **1 件足した**: `test_the_temporary_btree_goes_to_memory`（`temp_store` / `mmap_size` を掛け、**`cache_size` は既定のまま**であることを固定する） |
| `tests/test_backup.py` | 1969 → **2042** | **4 件足した**: D-8 の 3 通り（`OperationalError` / `IntegrityError` / `database is locked` → **500 `sqlite_error`・復元の語を出さない**）と、**壊れている仲間は今までどおり 503**（直しで本物の壊れ方を落とさない） |
| `README.md` | 272 → **295** | 数を実測へ（**518 件**・**322 検査**・**11 本**）・P9 を済みに・**D-7 の 1 行**（CLI は実データを直接開く）・`--screen pending --ids` の前提・未実装の一覧を更新 |
| `docs/design.md` | 1998 → **2074** | **§12.1 を実測で埋めた**（未計測 0・届かなかった 1 行の理由と必要な条件）・**§12.2**（入れた pragma と入れなかった `cache_size`・一覧と仮想グリッドが未実装であること）・**§12.3**（3 行の実測）・**§14**（P9 済み）・**§16.7（新設）**（P9 の決定 9 件）・**P8-6 の申し送り**（C-1 の `missing_at`・C-2 の `nearby` 2 段と返す欄・C-3 の取引の中の見直し）・§6.1 |
| `docs/frontend-design.md` | 1019 → **1020** | 文言表に 1 行（**上部バーの枚数**。切れているときだけ「先頭 2000 枚を表示」） |
| `docs/handoff.md` | 515 → **618** | P9 完了に・§1 の表・§5 に P9 の実測値・§6 に P9 の罠 7 件・§7 の未回答（13 件）・§8 の地図 |
| `docs/p9-implementation.md` | **この文書（新規 422）** | 測り方・生の値・届かない物・推奨・見送った物 |
| `.tmp-audit-redo/p9/` | 使い捨て | `make_replica.py`（実データの複製と署名）・`check_real_last.py`（署名の前後比較）・`grid_timing.mjs`（Chrome でグリッドの表示）・`make_gui100.py`・`measure_start.py`・`dbg_*.py`・`exe/`（PyInstaller の試し）・`probe-*.txt`（生のログ）・`synth10k/`・`real/`・`gui/` |

**契約（`schemas/`）は 1 バイトも変えていない**（P9 は口を足していない。**足した口は無い**）。

## 2. §12.1 の実測値（本体）

**測り方**: `tools/probe_p9.py`。**サーバ内**（`TestClient`＝ASGI を直接叩く。**ネットワークを挟まない**）。
`p95` は **30 回**（走査だけは 3 回の実測＋初回）。**土台**（`GET /api/health`）の p95 は **1.1〜1.3 ms** なので、
下の値から枠の費用を引いても桁は変わらない。**合成 1 万枚**は
`tools/make_synthetic_db.py`（1 万 asset・1 万 location・1 万 meta・全部に来歴。DB 29.8 MB・画像 20.3 MB）。
**実データは複製**（`sqlite3` の `backup()`。455 asset・262 の生きた場所・実体 291.1 MB）。

| # | §12.1 の行 | 目標 | **実測** | 判定 | 測り方（条件） |
| --- | --- | --- | --- | --- | --- |
| 1 | 一覧 API の応答 | p95 20 ms（1 万枚・サーバ内） | **244.7 ms**（p50 224.7 / min 204.4） | **届かない**（§2.1） | `GET /api/assets`（既定 limit=100・sort=path）を 30 回。1 万枚の合成 DB。本文 51 KB |
| 1b | **`/api/stats`**（画面が一覧と一緒に毎回呼ぶ） | —（**§12.1 に無かった。監査 D-6**） | **p95 130.2 ms**（1 万枚）／6.1 ms（299 枚） | §12.1 に足した | 30 回。`meta_json` を 1 万回 `json.loads`。**P9 の再測は 134.6 ms**（下の「監査の直しの後」） |
| 2 | 詳細表示（1024 サムネ・生成済み） | 200 ms | **p95 2.6 ms**（合成）／**p95 2.4 ms**（実画像） | OK | 24 枚を順に。`FileResponse`。**初回生成は別**（#3） |
| 3 | サムネイル生成 1 万枚（1024px） | **25 分以内（P9 で決めた）** | **128 ms/枚 → 21.3 分**（1 スレッド）／**22 ms/枚 → 3.7 分**（同時 8 本＝**道具の中の見込み**。実装にスレッドプールは無い。**監査 C-3**） | OK | 実画像 24 枚（元 1.15 MB・出力 104 KB）の中央値。`cpu_count=16`・`min(8, cpu)`=8 本 |
| 4 | サムネイル生成 1 万枚（256px） | 6 分 | **30 ms/枚 → 4.9 分**（1 スレッド）／**4 ms/枚 → 0.7 分**（同時 8 本＝**同じく見込み**。**監査 C-3**） | OK | 同上（出力 14 KB）。§12.1 の「36 枚/秒」とほぼ一致 |
| 5 | 比較の 8 枚表示（生成済み） | 400 ms | **p95 8.3 ms**（実データ）／p95 4.2 ms（合成） | OK | `GET /api/compare?ids=`（8 枚）を 30 回。**画面 1 回ぶんは文書 6.6 ms ＋ 8 枚の 1024 サムネイル 8×2.0 ms = 22 ms** |
| 6 | グリッド初回表示 | 300 ms（100 枚・本物の Chrome） | **87 ms**（100 枚ちょうど）／93 ms（299 枚）／**532 ms（1 万枚→2000 枚）** | OK（100 枚） | 本物の Chrome（CDP）・1400x900。**最初のカードが出るまで**。全部そろうまで 104 ms・最初の画像 104 ms |
| 7 | 追加ページ読み込み | 100 ms（100 枚） | **測る対象が無い** | **実装が無い** | 一覧は `GET /api/assets?limit=2000` を **1 回**引いて全部描く（**改ページも仮想グリッドも無い**） |
| 8 | 2 回目以降の走査（差分なし） | 10 秒 | **2.62 / 2.66 / 2.70 秒** | OK | 合成 1 万枚。`known=10000`・`created=0`・`missing=0` |
| 9 | 初回走査 1 万枚（ハッシュ＋登録） | 90 秒 | **40.6 秒**（書いた直後）／**9.1 秒**（温まった状態） | OK（見込み） | 合成 1 万枚（**96x96 なのでハッシュはほぼ 0**）。実画像 11.1 GB なら **P1 の実測 399 MB/s → 28 秒**を足して **37〜69 秒** |
| 10 | 初回走査 1 万枚（`--no-hash`） | 30 秒 | **測る対象が無い** | **実装が無い** | `cli scan` に `--no-hash` は無い（走査は常にハッシュを取る。§12.2 の設計どおり） |
| 11 | 判断の記録 | 100 ms | **p95 1.5 ms**（p50 1.0） | OK | 合成 1 万枚の DB に **1 枚ずつ別の枚**へ `POST /api/reviews`（30 回） |
| 12 | 日次バックアップ | 5 秒 | **201 ms** | OK | 実データの複製（DB 3.2 MB ＋ sidecar ＋ export）。**P8-4 の 37 ms は DB 1.0 MB のとき**（段 1 の 193 行で 3.2 MB になった）。**P9 の直しの後の再測は 72.7 ms**（温まった状態） |
| 13 | 一括削除の再照合（§12.3） | 1,000 件で 1 秒 | **596 ms**（`deleted=1000`・`skipped=0`） | OK | 合成 1 万枚の複製で `bulk-delete/preview`（1,000 枚を名指し）→ `bulk-delete` 段 1。**`os.stat` だけなら 13.8 ms** |
| 14 | `--include-library`（§12.3） | **5 分以内（P9 で決めた）** | **2.40 秒 / 262 枚・291.1 MB**（画像なし 201 ms） | OK | 実データの複製。**132 MB/s** → 1 万枚 11.1 GB なら **1.4 分**。**（監査 D-5）OS のファイルキャッシュで 0.63 秒（516 MB/s）とも出る。両方書く**（P9 の再測 0.68 秒＝427 MB/s） |
| 15 | 再リンクの `nearby`（§12.3） | **3 秒以内（P9 で決めた）** | **39.2 ms**（見つからない＝20 フォルダを全部歩く）／**44.6 ms**（1 段目で見つかる） | OK | 合成 1 万枚の複製で 1 枚を外へ出して参照切れにし、`RelinkService.relink(mode='nearby')` |
| 16 | タグ付け | 0.5 秒/枚（GPU） | **未再計測**（据え置き） | 未計測（**意図的**） | **ComfyUI に触らない**指示のため測っていない。いまの設定は ComfyUI の `IllustTagger` **0.27 秒/枚**（P4-1 の実測） |
| 17 | PNG のメタデータ抽出・内容ハッシュ・pHash・復元 | — | 前の段の実測のまま（**P9 で測り直していない**） | 実測（P1 / P5-3 / P8-1 / P8-4） | §12.1 の表に「実測から導出」と出所が書いてある行 |

### 2.1 届かなかった 1 行（一覧 API）——**目標は下げない**

**実測 p95 244.7 ms**（目標 20 ms）。**どこに時間が行っているか**も測った:

| 何 | 実測 | 備考 |
| --- | --- | --- |
| `/api/assets`（口ぜんぶ。既定 limit=100） | **p95 244.7 ms** | 30 回。本文 51 KB |
| `store.assets()`（口の外。SQL 3 本＋1 万件の dict 組み立て＋並べ替え） | **p50 201.2 ms** | 一覧の下限 |
| うち SQL 3 本だけ（`fetchall` まで） | **p50 47.7 ms** | `SELECT * FROM asset` ＝ `SCAN asset`（1 万行） |
| 土台（`GET /api/health`） | p95 1.1 ms | 枠の費用は 1 ms 程度 |

**理由**: `app.py` の `list_assets` が**毎回 `store.assets()` で全件を読んで dict を組み、Python で
絞り・並べ替えてから 100 件を切る**。§12.2 の「一覧」が求めている
**①キーセット改ページ ②概算の件数 ③最小の列**が**実装に入っていない**。
`tag` の絞り込みも「SQL で `asset_id` の集合を引いてからメモリの一覧を絞る」形なので、同じ 200 ms が土台に乗る。

**必要な条件**（入れる段でやること）:
1. `WHERE (sort_key, id) < (?, ?)` のキーセット改ページ（`OFFSET` を使わない。`asset` に `(sort_key, id)` の索引）
2. `total` を**概算**にする（`COUNT(*)` を毎回叩かない。正確な数が要る画面だけ数える）
3. 一覧で返す列を最小にする（`_summary` を SQL で組む。タグは別の口）
4. **`total` の意味と `q` / `tag` の絞り込みが変わる**ので、**テストと画面の前提を一緒に直す**
   （`gui_smoke` の「件数」の検査・`gui_layout` の `rows=` の期待値・`#/library` の「先頭 N 枚」の表示）

**いま困らない根拠**: **実データ 262 枚では p95 14.3 ms**（`limit=1000`。§2.2）。
**1 万枚が現実になるまで困らない**ので、P9 では入れず**段を別に立てる**ことにした（指示書も
「**目標に届かない物は「届かない」と正直に書く**」と言っている）。

### 2.2 実データ（455 枚・生きた 262 枚）で測った物

| 何 | 実測 | 目標との関係 |
| --- | --- | --- |
| `GET /api/assets?limit=1000` | **p95 14.3 ms**（p50 12.6・1 回目 28.0） | §12.1 の目標は 1 万枚に対する物なので**参考**。**262 枚では 20 ms の内側** |
| `GET /api/compare?ids=`（8 枚） | **p95 7.5 ms** | 400 ms の内側 |
| 1024px サムネイル（生成済み） | **p95 2.4 ms** | 200 ms の内側 |
| 1024px サムネイル（初回生成） | **128 ms/枚**（min 91 / max 180） | — |
| 256px サムネイル（初回生成） | **30 ms/枚**（min 17.8 / max 61.0） | §12.1 の「36 枚/秒」（=27.8 ms/枚）と一致 |
| `--include-library` | **2.40 秒 / 291.1 MB** | 新しく決めた 5 分の内側 |

**注記（測っている物の限界）**: 合成の 1024x1024 は**平らな絵**（`compress_level=1` で 67 KB）なので
**復号が本物より速い**。だから 1024px の「同時 8 本」と「初回生成」は**実画像（1.15 MB）で測った値**を採った
（合成の 104 ms/枚は**下限**として扱う）。実データの 262 枚には**段 1 で外した 193 枚が含まれない**ので、
「実データ 455 枚」と書くときは**生きた 262 枚**の話である。

## 3. 見つけて直した物（計測の途中で出た）

### 3-1. **`PRAGMA temp_store = MEMORY` が実装に無く、1 万枚の一覧が 500 になっていた**

- **症状**（直す前の実測）: 合成 1 万枚の DB で `GET /api/assets` が

  ```json
  {"detail": "DB が壊れているので読めません。バックアップから戻してください",
   "code": "db_error",
   "details": {"reason": "malformed", "error": "unable to open database file", "mode": "ok"}}
  ```

  （**HTTP 503**。**DB は健全**で、`quick_check` も `ok`）
- **原因**: `store.assets()` の `SELECT * FROM asset_location ORDER BY is_primary DESC, display_path` が
  **一時 b-tree** を作り、それが**一時ファイル**（`%TEMP%`）に落ちる。**この環境は `%TEMP%` に書けない**
  （`docs/handoff.md` §6 の既知の罠）ので `unable to open database file`。
  1 万行ではメモリのバッファに収まらず必ず落ちる。**455 枚では起きない**（だから今まで見えていなかった）。
- **直し**: `db.connect()` に **`PRAGMA temp_store = MEMORY`** を足した（**§12.2 に最初から書いてあった**。
  `docs/handoff.md` §6 も「`PRAGMA temp_store = MEMORY` で回避」と書いていた）。
  `mmap_size = 268435456` も入れた。
- **確かめ**: 直した後の `GET /api/assets` は **200**（`total: 10000`）。
  `tests/test_db.py::test_the_temporary_btree_goes_to_memory` が**この 1 行を守る**。

### 3-2. **`PRAGMA cache_size = -65536` は入れなかった**（理由は**速さの実利が無い**こと）

§12.2 の「DB」の 4 行のうち **`cache_size = -65536`（64 MB）だけ入れなかった**。
入れてみたら、**走ったまま壊れた DB を live の接続の `quick_check` が見落とす**ようになった:

| 入れた pragma | live の接続の `quick_check`（300 ページ目を 0 で潰した 2.28 MB の DB） |
| --- | --- |
| 既定 ＋ `temp_store` ＋ `mmap_size`（**採った形**） | `ok: False`（`database disk image is malformed`） |
| ＋ `cache_size = -65536` | **`ok: True`**（64 MB に DB 全体が載り、壊れる前のページがそのまま返る） |
| `cache_size = -65536` だけ外す | `ok: False` |
| `mmap_size` だけ外す | `ok: True`（＝**`cache_size` が原因**） |

**（P9 の監査 C-1。ここに書いた理由は誤りだった。）** 上の表は「**既定の 2 MB なら見つける**」と
読めるが、それは **2.28 MB の DB＝既定をぎりぎり超える大きさ**だったからで、
**既定でも、キャッシュに収まる 0.65 MB（250 行）の DB では見落とす**（監査の実測。
書き込み用の接続は自分が書いたページをページキャッシュに持つので、外から潰されたページを
読み直さない。4 つの pragma の組み合わせ全部で見落とした）。**P8-4 の実測時の実データは
1.0 MB だったので、G-1 は初日から小さい DB に効いていなかった。**

**直し**: `_refuse_if_broken()` の `quick_check` を**新しい読み取り専用の接続**
（`quick_check_on_disk()`＝`file:...?mode=ro` を 1 本開く）に変えた（監査の 28 通りすべてで見つける）。
`tests/test_backup.py::test_a_page_in_the_writers_cache_is_still_noticed` が守る。
**`cache_size` を入れない理由は「速さの実利が無い」だけ**——`store.assets()` の 200 ms は
`cache_size` では解決しない（1 万件の dict 組み立てが主因）ので、64 MB にする意味が無い。

**副産物**: `cache_size` と `mmap_size` は**ページの大きさを読む**ので、**先頭 4 KB を潰した DB では
`DatabaseError: file is not a database` を投げる**。素直に書くと「壊れた DB でも起動して 503 で案内する」道
（§0.12-5）が**開けなくなる**。この 2 つは**最善努力**（`try` して警告ログ）にしてある。

### 3-3. **D-8（`sqlite_error_handler` の守備範囲）を直した**

- **症状**（3-1 の 503 がそのまま実例）: `unable to open database file`（`OperationalError`）にも
  **「DB が壊れている／バックアップから戻してください」**と答えていた。`sqlite3.DatabaseError` は
  `IntegrityError` と `OperationalError` の**親**なので、handler が**全部**受けていた。
- **直し**（`api/__init__.py`）: **壊れている仲間だけ 503**——
  `malformed` / `not a database` / `corrupt` / `encrypted` / `disk I/O error` を `CORRUPTION_WORDS` に置き、
  `_is_corruption()` の 1 か所で判定する。**それ以外は 500 `sqlite_error`** にして、
  文言を「DB の操作で内部エラーが起きました（**DB が壊れているとは限りません**）」に変えた
  （`details.kind` に例外のクラス名。**復元を勧めない**）。
- **確かめ**（`tests/test_backup.py` の 4 件）: `unable to open database file` /
  `UNIQUE constraint failed` / `database is locked` の 3 つが **500 で「バックアップ」の語を出さない**こと、
  潰したページは**今までどおり 503 `read_only` で「バックアップから戻してください」**が出ること。

### 3-4. **一覧が `limit=2000` で切れるのに、上部が全枚数と言っていた**

- グリッドの表示を測るために 1 万枚の合成 DB を開いたら、**カードは 2000 枚**しか出ていないのに
  上部は「**10000 枚**」と言っていた（`apps/gui/app.js` の `load()` が
  `GET /api/assets?limit=2000` の `items` だけを見て、`total` を捨てていた）。
  **家風「数を黙って捨てない」に反する**（利用者から見ると、無い 8000 枚を探すことになる）。
- **直し**: `state.listed` / `state.total` を控え、`total > listed` のときだけ
  **「10000 枚（先頭 2000 枚を表示）」**と出す（`total == listed` なら今までどおり「N 枚」）。
  ~~実データ（299 枚）では**文言が変わらない**~~ **（P9 の監査 C-2。この行は誤りだった）**——
  実データは `asset` **455 行**のうち **193 行が段 1 で外れていて生きた 262 枚**なので、
  ここで上部が「455 枚」から「**262 枚**」に変わり、**同じ画面の「すべて」(`#c-all`) は 455 のまま**だった。
- **確かめ**: 本物の Chrome で 3 つの DB を開いて実測（§2 の #6）。
  100 枚 →「100 枚」・299 枚 →「299 枚」・1 万枚 →「**10000 枚（先頭 2000 枚を表示）**」。
  `gui_smoke` 322 検査・`gui_layout` 11 本は緑のまま（`stat-brief` の文言を見ている検査は無い）。
- **（P9 の監査 C-2）画面の「枚」の規則を 1 つにした。** 上部バー・「すべて」・下部バーの枚数を
  **生きた枚**（`GET /api/assets` の `total`＝段 1〜3 で外した枚を含まない）に統一し、規則を
  `apps/gui/counts.js`（純粋関数）の 1 か所に置いた。**`stat-brief` の文言を見る検査を
  `gui_smoke` に足した**（下の「監査の直しの後」を見る）。
- ~~**自動の検査は付けていない**~~（当時の記録。**監査 C-2 で足した**）。

### 3-5. P8-6 の申し送り（`design.md` への反映）

`p8-6-audit-triage.md` の申し送り 1 を `docs/design.md` に入れた:
**C-1**（走査で戻ってきたファイルは `missing_at` が外れる。§5.1 の DDL スケッチと §16.6）・
**C-2**（`nearby` は 2 段で、`folders` / `folders_skipped` / `found_in` / `scope` を返す。§6.1 と §16.6）・
**C-3**（二重登録の見直しは取引の中でもう一度。§6.1）。**D-8 の直しも §16.7 に書いた**。

### 3-6. D-7（CLI は実データを直接開く）— **塞がず、README に 1 行**

`cli backup` / `scan` / `rebuild-metadata` は `IMAGE_REVIEWER_DATA` が無ければ**既定の `.data` を開く**。
**CLI は利用者の正当な入口**なので**塞がない**（`create_app()` の硬化は `serve` 以外の道を守る物で、
CLI は `serve_data_dir()` で明示的に指す）。**README の「動かす」の直後に 1 行**足した:
「**CLI は `IMAGE_REVIEWER_DATA` が無ければ実データ `.data` を直接開きます**（利用者の道具なので正しい入口です）。
**壊す試験や計測をしたいときは、必ず複製を作って env を付けてください**」。

### 3-7. 768px の上部バー — **P9 では見送った**

- **実測**: `gui_layout --screen library` の `pageOverflow` と `topbarOverflow` は
  **3 窓とも 0**（1200x800 / 1400x900 / 1920x1080）。**溢れていない**（切れていない）。
- **何が問題か**: 768px では**上部バーが 3 行に折り返す**（見た目の問題。`frontend-design.md` の
  「上部バーは 1 行」から外れる）。
- **見送った理由**: ①**実害が無い**（溢れ 0。押せる物は全部押せる）②直すには
  **狭い窓の検査から作る**必要がある（`gui_layout` の `VIEWPORTS` は 1200 以上しか無く、
  `--viewport 768x1360` は**一覧を絞るだけ**なので**何も見ずに「すべて ok」と出る**——
  P8-5 の追い込み §8 が既に記録している）③**CSS だけの変更**なので、狭い窓の検査を足す段と**一緒に**やる方が安全。
- **次にやる人へ**: `VIEWPORTS` に `[768, 1360]` を足す（か、`--viewport` を「一覧の追加」にする）→
  そのうえで `@media (max-width: 900px)` で上部バーの入りきらない物（`来歴` / `密度` / `テーマ` の 3 つ）を
  畳む、の 2 手。**先に `frontend-design.md` を直す**（家風）。

## 4. 自分で決めた点（設計が黙っていた所）

1. **1024px サムネイルの目標を「25 分以内（1 スレッド）」と決めた**（§12.1 は「未定（実装時に計測して決める）」）。
   実測 21.3 分に**余裕を 15% 乗せた**値。**同時 8 本なら 3.7 分**なので、実際の画面はこちらを使う。
2. **`--include-library` の目標を「5 分以内」・`nearby` を「3 秒以内」**と決めた（§12.1/§12.3 は「未定」）。
   実測 2.40 秒 / 39〜45 ms なので**どちらも桁で余裕がある**。
3. **`cache_size` を入れない**（§3-2）。設計の 4 行のうち 1 行を**意図的に採らなかった**唯一の箇所。
4. **`_is_corruption()` の語で分ける**（例外のクラスでは分けられない——「壊れている」も
   「一時ファイルが作れない」も `OperationalError` で来る。`quick_check` の判定と同じ流儀にした）。
5. **一覧の「切った枚数」は上部バーの既存の `#stat-brief` に出す**（**新しい要素を作らない**。
   `gui_smoke` の作り物の DOM に要素を足すと 322 検査に波及するため。文言は `frontend-design.md` §6 に置いた）。
6. **計測の土台（`/api/health` の p95）を毎回出す**（枠の費用を引いて読めるように。
   P6-1a の「keep-alive と毎回接続で桁が違う」の教訓）。
7. **初回生成と「生成済み」を分けるときは、サムネイルを消してから測る**（合成 DB と複製の中だけ）。
   消さないと `ensure_thumb()` が「在る」を返し、**測っている物が「配信」に変わる**（**実際に踏んだ**。
   `--keep` で残した前回の計測を拾って「初回生成 2 ms」と出た）。
8. **グリッドの「全部そろうまで」を自分で測る道具を書いた**（`gui_layout` の `--count` は
   **比較の画面**の枚数で、`MAX_COMPARE_IDS = 8` なので**大きくできない**。§12.1 の「100 枚」は
   `#/library` の話なので、Chrome を CDP で駆動する `.tmp-audit-redo/p9/grid_timing.mjs` を作った）。
   **道具は `tools/` に置いていない**（`gui_layout` に `--screen library` の計測として足すのが本筋だが、
   **前提（枚数を 100 枚ちょうどにする等）を作る手順ごと要る**ので、P9 では使い捨てにした。**申し送り 4**）。

## 5. 実行したコマンドと結果

`$env:UV_CACHE_DIR = "C:\work\image-reviwer\.uv-cache"`、`cd C:\work\image-reviwer`。
**`uv run` は全部 `--no-sync`**（利用者のサーバが `.venv` を握っているため）。

| 何 | コマンド | 結果 |
| --- | --- | --- |
| **合成 1 万枚** | `uv run --no-sync python -X utf8 tools/make_synthetic_db.py --out .tmp-audit-redo/p9/synth10k --count 10000 --big 24 --folders 20 --force` | 画像 1 万枚を **6.4 秒**で書き、**初回走査 40.6 秒**で登録。**asset 10000 / location 10000 / 全部に来歴**・DB 29.8 MB |
| **§12.1 の計測** | `uv run --no-sync python -X utf8 tools/probe_p9.py --all --replica .tmp-audit-redo/p9/real --runs 30 --keep` | §2 の表（生のログは `.tmp-audit-redo/p9/probe-all.txt` / `probe-rest*.txt`） |
| **グリッドの表示** | `node .tmp-audit-redo/p9/grid_timing.mjs --base http://127.0.0.1:8795`（100 枚は 8797・1 万枚は 8796） | 87 ms / 93 ms / 532 ms（§2 の #6） |
| **pytest** | `uv run --no-sync pytest -q` ×**5** | **518 passed**（1 回目 66.1 秒＝サーバと Chrome が同時に走っていた。**2〜5 回目は 37.5〜38.2 秒**）。**5 回とも同じ数**（揺れなし。**513 → 518**＝新規 5 件） |
| **gui_smoke** | `node tools/gui_smoke.mjs` | **322 ok / NG 0**（「すべて ok」） |
| **gui_layout** | 複製（8795）で **11 本**（10 画面＋`pending --ids`） | **11 本とも「すべて ok」**（`--screen pending --ids` は**生きている枚**を渡す。§5-1） |
| **実データの署名** | `uv run --no-sync python -X utf8 .tmp-audit-redo/p9/make_replica.py`（前）→ 最後にもう一度 | **前後で同じ**（§7） |
| **exe の試し** | `uv run --no-sync --with pyinstaller python -m PyInstaller …`（§6） | 23.7 秒でできた。**起動はするが画面が出ない**（`gui_present: false`） |

### 5-1. `gui_layout --screen pending --ids` が最初 NG になった（**前提の間違い。製品の不具合ではない**）

- 最初に**段 1 で外した枚**（`deleted_at` が立っている 193 枚の 1 つ）を `--ids` に渡したら、
  3 窓とも **NG**（`段 3 を出さない理由の 1 行`）。
- **理由**: 画面は段 3 の出し分けのために `GET /api/assets` からその枚のパスを引く。
  **外した枚は既定の一覧に出ない**のでパスが引けず、`stage3OfPaths()` が
  `known: false` → **「置き場を確かめられないので、段 3 は出していません」**を出す
  （`pending.js` の `stage3BlockedHtml()`。**これが正しい動作**）。
  `gui_layout` は「段 3 の印がありません」の語を見ているので NG になる。
- **直し**: **生きている枚**（`01M4Z0KJR69CW8RA2R5Q9ZXHHW`）を渡したら **3 窓とも ok**。
  **この前提を README に 1 行書いた**（同じ穴を踏まないように）。

## 6. exe 化の判断（**調査と推奨だけ。実装はしていない**）

### 6-1. いまの起動（実測）

```bat
@echo off
rem image-reviewer を起動してブラウザを開く（このファイルをダブルクリック）
cd /d "%~dp0"
set UV_CACHE_DIR=%~dp0.uv-cache
start "" cmd /c "timeout /t 3 >nul & start "" http://127.0.0.1:8790"
uv run --no-sync image-reviewer serve --port 8790
pause
```

- **段数**: `start-image-reviewer.cmd` → **uv** → ランチャ（`image-reviewer.exe`）→ **python**。
  **`uv` を止めても python が生き残る**（家風の罠。**P9 でも踏んだ**: 起動時間の計測で
  前のサーバの 200 を拾って「17 ms で上がった」と出た。**回ごとに別のポート**にして直した）。
- **起動時間**（複製を指して `serve`。**プロセスを上げてから `/api/health` が 200 になるまで**。
  **木ごと止めて**測り直した 3 回）:

  | 起動の仕方 | 1 回目 | 2 回目 | 3 回目 |
  | --- | --- | --- | --- |
  | `uv run --no-sync image-reviewer serve`（**いま**） | 1057 ms | 1049 ms | — |
  | 束ねた `image-reviewer.exe serve` | 529 ms | 525 ms | 532 ms |

  **（P9 の監査 D-7）冷えた 1 回目は 1706 ms**（監査の実測。`uv run` は 1055〜1059 ms と安定）。
  **温まった 3 回だけを「起動 0.53 秒」と呼ばない**——表に冷えた値を書き分けた。

- `uv run --no-sync python -c "pass"` は **53〜68 ms**、`.venv\Scripts\python.exe -c "pass"` は
  **35〜39 ms**（`uv` の段は **約 18 ms**）。
- `python -X importtime -c "import image_reviewer.app"` は **429 ms**（累積。`numpy` / `PIL` を含む）。

### 6-2. 配布物の大きさ（実測）

| 何 | 実測 |
| --- | --- |
| `.venv`（いまの開発環境ぜんぶ） | **128.4 MB / 3,250 ファイル** |
| うち `onnxruntime`（任意依存。`tagger` extra） | **41.7 MB** |
| うち `numpy` ＋ `numpy.libs` | **42.3 MB** |
| うち `PIL` | **15.3 MB** |
| うち `pydantic` ＋ `pydantic_core` | **9.2 MB** |
| **PyInstaller `--onedir` の生成物** | **138.3 MB（= 131.9 MiB）/ 116 ファイル**（`onnxruntime` 38 MB ＋ `numpy` 6.2〜26.3 MB ＋ `PIL` 10.7〜11 MB。**単位を混ぜていたので監査 D-7 で直した**） |

### 6-3. 実際に試した（**作れることは確かめた**）

```powershell
$env:UV_CACHE_DIR = "C:\work\image-reviwer\.uv-cache"
$env:PYINSTALLER_CONFIG_DIR = "C:\work\image-reviwer\.tmp-audit-redo\p9\exe\picache"   # %USERPROFILE% に書かせない
uv run --no-sync --with pyinstaller python -m PyInstaller --noconfirm --clean --onedir `
  --name image-reviewer --distpath …\dist --workpath …\build --specpath … `
  --add-data "C:\work\image-reviwer\apps\gui;apps/gui" --hidden-import image_reviewer.app `
  --hidden-import uvicorn.logging --hidden-import uvicorn.loops.auto `
  --hidden-import uvicorn.protocols.http.auto --hidden-import uvicorn.protocols.websockets.auto `
  --hidden-import uvicorn.lifespan.on --collect-submodules image_reviewer …\entry.py
```

- **PyInstaller 6.22.3 は Python 3.14.7 で動く**（`uv --with` が解決して入り、ビルドが通った）。
  **`pyproject.toml` / `uv.lock` は 1 バイトも変えていない**（`--with` は一時の層）。
- **ビルド 23.7 秒**。`--add-data` は**相対パスだと spec の場所から解決されて失敗する**（実際に踏んだ。
  **絶対パス**にしたら通った）。
- **起動して API は答えた**: `/api/health` 200・`/api/assets?limit=3` 200。
- **しかし `gui_present: false`** ——`app.py` の `GUI_DIR` は `REPO_DIR / "apps" / "gui"` を指すので、
  束ねた中では**画面（HTML / CSS / JS）が見つからない**。`--add-data` で `_internal/apps/gui` には
  入っているのに、**見に行く場所が違う**。
- **`%USERPROFILE%` に書かせない工夫が要る**: PyInstaller は既定で
  `%USERPROFILE%\AppData\Local\pyinstaller` にキャッシュを掘る（**1 回掘られた**）。
  `PYINSTALLER_CONFIG_DIR` を内向きにしてからは書いていない。

### 6-4. 推奨（**1 つ**）: **exe 化は今は作らない**

**理由**:
1. **配布しない。** これは**利用者 1 人のローカル道具**で、置き場は `C:\work\image-reviwer` に固定。
   いまの `start-image-reviewer.cmd`（`uv` 経由）で**起動は 1.05 秒**、`uv sync` は 1 回だけ。
   **exe にしても 0.53 秒になるだけ**（差は 0.5 秒）。
2. **大きさが変わらない**（`.venv` 128.4 MB → exe 131.9 MB）。`onnxruntime`（37.5 MB）が載るので、
   仮に `--exclude-module onnxruntime` で削っても**100 MB 級**のまま。
3. **まだ足りない物がある**（**実測**）: `apps/gui` の解決（1 か所）・同梱した静的ファイルのパス・
   `tagger` の任意依存をどう扱うか・`uvicorn` の worker と `--factory`・
   初回起動時の展開（`--onefile` なら毎回・`--onedir` なら 1 回）・
   **署名**（無いと SmartScreen が出る）。**やることは少なくない**。
4. **見返りが「配布」だけ**——配布しないなら**利用者に何も良くならない**。

**もし作るなら**（順番）: ①`GUI_DIR` を `sys._MEIPASS` でも解決する（`getattr(sys, "_MEIPASS", REPO_DIR)`）＋
テスト（束ねた物で `/` が 200 を返す）②`--exclude-module onnxruntime` を既定にし、使う人だけ extra で
③`--onedir` ＋ ショートカット（`--onefile` は起動のたびに展開して遅い）
④`--noconsole` は**使わない**（ログが見えなくなる。いまは `pause` で窓が残る形になっている）
⑤`start-image-reviewer.cmd` を exe に差し替え、**`uv` を入れていない PC でも動く**ことを確かめる。

## 7. 実データが無傷であること（`mode=ro` と `os.stat` の読みだけ）

`.tmp-audit-redo/p9/make_replica.py` の署名を**作業の最初と最後**に取った（`real-signature.json`）。

| 見た物 | 作業の前（20:39） | 作業の後 |
| --- | --- | --- |
| `asset` | **455** | **455** |
| `asset.deleted_at` が立っている枚 | **193** | **193** |
| `asset_location`（うち `missing_at`） | **455（0）** | **455（0）** |
| `deletion_log`（段 1 の行） | **193（193）** | **193（193）** |
| `delete_request` / `decision` | **30 / 3** | **30 / 3** |
| `user_version` / `quick_check` | **6 / ok** | **6 / ok** |
| 生きた場所（実体あり） | **262 / 262 枚・291.1 MB** | **同じ** |
| **画像の署名**（455 パスの `(path, size, mtime_ns)` の sha256） | **`d9604560e494c510`** | **同じ** |
| **`.data` の全ファイルの署名**（`(名前, size, mtime_ns)`） | **`ae60041b0b0b5365`** | **同じ** |

- **利用者の段 1 の 193 行は 1 行も触っていない**（`missing_at` は 0 のまま・`deleted_at` も 193 のまま）。
  **画像も 1 枚も動かしていない**（署名が同じ）。
- 実データを開いたのは **`mode=ro` の読みだけ**。計測はすべて**複製**で、
  サーバは **`IMAGE_REVIEWER_DATA=<複製>`** を付けて 8795 / 8796 / 8797 / 8798 に立てた
  （**止める前に `/api/health` の `data_dir` が複製であることを確かめた**）。
  **8790 は一度も止めていない**（`/api/health` も打っていない＝利用者のアプリには触っていない）。
  8791〜8798 で LISTEN していたのは**自分が立てた物だけ**だった（`netstat` で確認済み）。
- 書き込んだのは `.tmp-audit-redo/p9/` の下だけ。**`%USERPROFILE%` の下には作っていない**
  ——**例外が 1 つ**: PyInstaller が**自分のキャッシュ**（`%USERPROFILE%\AppData\Local\pyinstaller`）を
  1 回掘った（**道具の既定の癖**。以後は `PYINSTALLER_CONFIG_DIR` を内向きにしてからは書いていない）。
  **残した物**: `.tmp-audit-redo/p9/` の 71.2 MB（合成 1 万枚・実データの複製・gui の複製・
  生のログ・使い捨てのスクリプト。**監査が `probe_p9.py --all` を回し直せる**ようにしてある）。
  **消した物**: PyInstaller の `dist`（131.9 MB）と `build`（31.1 MB）・`backups-library`（284.2 MB）・
  各バックアップの置き場（60 MB）・`gui100`・`pragma` / `mmap` の試し（8.7 MB）。**合計 約 560 MB**。

## 8. 申し送り（次の人へ）

1. **一覧 API のキーセット改ページ**（§2.1）。**p95 244.7 ms が目標 20 ms に届いていない**唯一の行。
   `total` の意味と `q` / `tag` の絞り込みが変わるので、**テストと画面の前提を一緒に直す段**として立てること。
2. **一覧の仮想グリッドとページ送り**（§12.2 の「前面」）。いまは `limit=2000` で全部描く。
   P9 で**切った枚数を出す**ようにしたが、**2000 枚より先を見る道は無い**。
   **`gui_layout` の `VIEWPORTS` は 1200 以上しか無い**ので、狭い窓の検査と**セットで**入れるのが良い。
3. ~~**切った枚数の自動の検査が無い**~~（**P9 の監査 C-2 で足した**）。`gui_smoke` の
   `/api/assets` の stub に `total` を持たせ、`apps/gui/counts.js` の規則を 1 件固定した
   （実データの 455 と 262 が混ざらないこと）。
4. **グリッドの表示速度の計測を `tools/` に入れていない**（§4-8）。`gui_layout --screen library` に
   「最初のカードが出るまで」を足すのが本筋（**100 枚ちょうどの複製を作る手順ごと**）。
5. **768px の上部バーは見送った**（§3-7）。`VIEWPORTS` に `[768, 1360]` を足すのが先。
6. **`--no-hash` の走査は実装に無い**（§12.1 の行）。設計に残すなら実装する段を立てる。
7. **exe 化**: 推奨は「作らない」（§6-4）。作るなら `GUI_DIR` の解決（1 か所）から。
8. **`docs/p8-6-relink.md` の記述は P8-6 の監査で上書きされた**（`nearby` が 2 段になった）。
   **あの文書は歴史**なので直していない（正は `design.md` §6.1・§16.6 と `p8-6-audit-triage.md`）。
9. ~~**実機の日次バックアップはまだ取れていない**~~（**P9 の監査 D-4 で古いと分かった**）。
   8790 は **Explorer → `start-image-reviewer.cmd`** の系譜で動いていて（sandbox の子ではない）、
   利用者が置き場を `.backup/daily` に変えたので**日次は取れている**:
   **`20261018`（263 枚・17:12 JST）・`20261018-171143`（「いま取る」）・`20261019`（455 枚・00:00:15 JST）**。
   **`%USERPROFILE%\image-reviewer-backups` は無い**（既定の置き場が実機で使えない謎は未解決のまま）。
   **日中に外した枚がその日の控えに入る道**は G-5 として 1 行足した（`pending.js`。§16.7 の 13）。

## 9. 設計の穴（この段で分かったこと）

1. **§12.2 に書いてある pragma が実装に無かった**（`temp_store`）。**設計に書いてあるのに
   実装で落ちている物は、性能の計測をして初めて出る**（1 万枚を開くまで誰も気づかない）。
2. **§12.1 の「未計測」の行に、実装が存在しない物が 2 つ混ざっていた**（`--no-hash` の走査・
   追加ページ読み込み）。**「未計測」と「実装が無い」は別の物**——表の種別を分けるべきだった
   （P9 で「測る対象が無い」と書き分けた）。
3. **§12.1 の「グリッド初回表示 300ms 以内（100 枚）」が何を指すか書いていない**
   （DOM に全部載るまでか、最初のカードが見えるまでか、絵が出るまでか）。
   P9 では **①最初のカード ②全部そろうまで ③最初の画像**の 3 つを出して、
   **①で判定**した（利用者が見るのはまず ① なので）。**設計に 1 行書くべき**。
4. **画面の一覧に「切った」概念が無かった**（§3-4）。`limit` を書いた瞬間に
   **「全件」と「切った N 件」を区別して出す**のが要る（家風「数を黙って捨てない」の適用漏れ）。
5. **`docs/handoff.md` §6 の罠に「`PRAGMA temp_store = MEMORY` で回避」と書いてあったのに、
   実装に入っていなかった**（P9 で入れた）。**回避策が文書にだけ残っていた**型。

## 10. P9 の監査の直しの後（2026-10-19 の実測）

**正は [`p9-audit-triage.md`](p9-audit-triage.md)**（指摘ごとの 1 行）。ここには**この節で測り直した数**だけ置く。
**測り方**: `$env:UV_CACHE_DIR = "C:\work\image-reviwer\.uv-cache"`、`uv run --no-sync`。

| 何 | 実測 | 条件 |
| --- | --- | --- |
| **pytest** | **520 passed** × 4（40.0 / 38.9 / 38.8 / 41.8 秒） | 518 → 520（C-1 1 件・D-1/D-2 2 件、`database is locked` を 500 の試験から外した） |
| **gui_smoke** | **333 ok / NG 0**（**私の変更を入れた時点**） | 322 → 333（C-2 5・G-5 3・D-1/D-2 3）。※ その後に並行して入ったワーディング監査の差分で期待値が未更新（`p9-audit-triage.md` §5-6） |
| **gui_layout** | **11 本とも「すべて ok」** | 複製（8791）。**`--screen tags` は `gui_layout_seed.py --tags` を当ててから**（実データの `tag` は 0 件）。**`--screen pending` は本物の走査を 1 回打つ** |
| **`/api/stats`**（D-6） | **p95 134.6 ms**（合成 1 万枚・30 回）／**p95 7.1 ms**（実データ 455 枚・keep-alive 30 回） | 画面が一覧と一緒に毎回呼ぶ |
| **`GET /api/assets?state=kept`**（C-3②） | **1,429 件・p95 289.9 ms**（合成 1 万枚） | 判断を**台帳に**入れた合成（`decision` 2,209 件） |
| **一覧 API**（`limit=100`） | **p95 260.6 ms** | 合成 1 万枚。**目標 20 ms に届かないのは変わらない** |
| **1024px の初回生成** | **130 ms/枚 → 21.7 分**（24 枚の中央値） | 実データの複製（元 1.15 MB・出力 104 KB） |
| **256px の初回生成** | **29 ms/枚 → 4.9 分** | 同上（出力 14 KB） |
| **「同時 8 本」（道具の中）** | 1024px **21 ms/枚 → 3.5 分**／256px **4 ms/枚 → 0.7 分** | **`probe_p9.py` が自分で `ThreadPoolExecutor` を回した見込み**。**実装にスレッドプールは無い**（C-3①） |
| **比較の 8 枚** | **p95 7.5 ms** | 実データの複製 |
| **判断の記録** | **p95 1.5 ms**（`review_state=kept` と出る） | 合成 1 万枚に 1 枚ずつ別の枚（D-9 の名札も直した） |
| **`--include-library`** | **0.68 秒 / 262 枚・291.1 MB（427 MB/s）**。画像なしの日次 **72.7 ms** | 実データの複製。**0.63〜2.40 秒の幅は OS のファイルキャッシュ**（D-5） |
| **C-2 の画面（本物の Chrome）** | `#stat-brief` **262 枚**・`#c-all` **262**・下部バー **262 枚／来歴あり 182／来歴なし 80** | 実データの複製（`asset` 455 行・段 1 で 193 行・生きた 262 枚）。**455 は画面に出ない** |
| **C-1 の再現** | 直す前: 0.65 MB の DB で **`tick()` が控えを取り `read_only=False`**。直した後: **断る** | 既定の `cache_size=-2000`。2.28 MB では前から断る（テストが見ていたのは境界） |
| **実データ** | **455 枚・193 行・判断 3 件・`missing_at` 0・画像の署名 `0183d290a5f9cbd3`**（前後で同じ）・`.backup/daily` の **3 件はそのまま** | `mode=ro` と `os.stat` の読みだけ |
