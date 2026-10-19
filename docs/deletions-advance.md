# カタログから外した行を後から進める・実体が無い行を片付ける（P10）

利用者の要望（原文）:

> 「一度カタログから削除したものをゴミ箱に移す方法はない？」→（こちらの推奨に）「**作る**」

**段 1（カタログから外す）が行き止まりだった**のを塞ぐ。段 1 の行は一覧から隠れるので選び直せず、
`#/pending-deletes` の各行にも「戻す」しか無かった（`deletions.py` の `_target()` が段 1 の行に
段 2 を打つと **409 `not_registered`** を返し、段 1 の再送は **200 で `replayed: true`**＝何も起きない）。

設計の正は**この文書**（`docs/p8-design.md`・`docs/design.md` より先に読む）。画面の文言は
`docs/frontend-design.md` §4.6・§6 を**先に直してから**実装した（家風）。

---

## 1. 作った口と動き

| 口 | 本文 | 誰 | 動き |
| --- | --- | --- | --- |
| `POST /api/deletions/{id}/advance` | `{stage: 2}` | **人だけ** | 段 1 の行を**アプリのゴミ箱へ移す**（`to_path`・`stage = 2`・`missing_at`）。**「戻す」がそのまま効く** |
| `POST /api/deletions/advance` | `{ids: [...], stage: 2}` | **人だけ** | 1 件ずつ同じ道。**1 回の上限は 200 件**（超えたら 422 `too_many` で 1 件も進めない） |
| `POST /api/deletions/{id}/close` | `{reason: "missing"}` | **人だけ** | **実体が無い行を終わりにする**（`closed_at` / `close_reason`）。**ファイルは 1 つも消さない・動かさない** |
| `POST /api/deletions/close` | `{ids: [...], reason}` | **人だけ** | まとめて片付ける（1 回の上限 200 件）。**実体がまだ在る行は断る** |

- **段 3 への直行は作らない**（`stage` は 2 だけ＝`_advance_stage_of()` が 422 で落とす。段 3 は
  `root.allow_stage3` の許可と凍結が要る）。
- `advance` の動きは**既存の段 2 と同じ道**（`_destination()` ＋ `move_no_clobber()`＝`os.rename`。
  **上書きしない**＝409 `target_exists`／別ボリュームは 409 `cross_volume`）。**台帳を先に書いてから
  動かす**（B-1 と同じ）。動かせなければ `_unadvance()` で**段 1 に戻す**。
- `close` は **`asset_location`・`asset`・ファイルを 1 つも触らない**（`asset.deleted_at` はそのまま
  ＝**カタログに戻さない**）。閉じた行は「最近の削除」から外れ、**台帳 `GET /api/deletions` には残る**。
  **片付けた後は戻せない**（`undo` は 409 `already_closed`。段 1 はファイルを見ないので、通すと
  実体の無い枚がカタログに戻り「参照切れ」が並ぶ）。
- **語彙**: `reason` は `missing` だけ（`CLOSE_REASONS`。`CHECK` にも入れた）。`actor` は
  `delete_request` に残す（**台帳の `actor` は消した人なので上書きしない**＝1 行 = 1 回の削除の記録）。
- **`GET` は 1 バイトも書かない**（足したのは `POST` の 4 つだけ）。閉じた行は `pending()` / `trash()`
  から外す（読みの規則を 1 か所に）。

### 画面（`#/pending-deletes`）

- 段 1 の行: **「アプリのゴミ箱へ移す」**＋**「ファイルが無いので片付ける」**／段 2 の行（下の
  ゴミ箱の欄）: **「戻す」＋「ファイルが無いので片付ける」**／段 3 の行: 今までどおり。
- **まとめて**: 各行のチェック＋「**全部選ぶ**」＋「**選んだ N 件をまとめてアプリのゴミ箱へ移す**」
  「**選んだ N 件をまとめて片付ける**」（N は**その操作が効く行**で数える。0 なら枚数を書かない）。
  **200 件ずつ分けて送る**（サーバの上限と同じ規則。実データの 194 行は 1 回で収まる）。
- 結果の 1 行は「**N 件を片付けました。**」「**N 件をアプリのゴミ箱へ移しました。**」＋断りがあれば
  「**M 件は片付けませんでした（ファイルがまだあります）。**」（**数を黙って捨てない**）。
- 片付けは**戻せない**ので**押す前に 1 回確認する**（「この行を終わりにします。ファイルは消しません。
  元に戻せません。」）。「アプリのゴミ箱へ移す」は**確認を挟まない**（「戻す」で戻せる）。

---

## 2. 決めた点（設計が黙っていた所。ここが正）

1. **上限は「人も 1 回 200 件」**にした（`MAX_BATCH_PER_CALL = AGENT_MAX_BATCH`。超えたら
   422 `too_many` で**部分適用しない**）。要望の「1 回の上限はエージェント 200 と同じ規則」は
   *値*か*規則の形*か読めなかったので、**人が叩く口なので規則の形（超えたら 1 件も進めない）を
   そのまま人にも当て**、画面は 200 件ずつに分けて送る形にした（194 件は 1 回）。
2. **「実体」ではなく「ファイル」**を画面と文に使う（要望の「実体が無いので片付ける」は
   `frontend-design.md` §6.1 の規約 4 が「実体」→「ファイル」を決めているため）。
   ボタンは「**ファイルが無いので片付ける**」、断りの文も同じ語で案内する。
   要望の語のままにしていない**唯一の点**（規則が正。§6.1 を先に読んで決めた）。
3. **段 3 への直行は作らない**（要望どおり）。`stage` は 2 だけ。
4. **`close` は段を問わない**（API は段 1・2・3 のどれでも受ける。守りは「**どこにも実体が無い**」
   の確認）。**画面は段 1・2 の行にだけ出す**（要望どおり。段 3 は「いま消す」と「別名で戻す」の世界）。
5. **片付けた行は戻せない**（409 `already_closed`）。理由は本文書の冒頭（段 1 はファイルを見ない）。
6. **`advance` は台帳の `asset_id` を見ない**（下の「設計の穴 1」。**いま登録されている行**を引く）。
7. **`client_token` は付けない**（`advance` は行を増やさず、`close` は `closed_at` で冪等。
   再送は 200 で `replayed: true`）。`request_id` も上書きしない（台帳は元の削除の要求を指したまま）。
8. **`closed_at` と `close_reason` は版を上げずに足す**（`db.TOP_UP_COLUMNS`。`pre-topup-*` の控えが
   付く形＝`stuck_reason` と同じ）。`check` の語彙は `missing` だけ。

---

## 3. 設計の穴（実装中に見つけた。申し送り）

1. **台帳の `asset_id` は古くなる**（実データで 6 行）。`delete()` の `_target(asset_id, path)` は
   「その場所がいまもその枚の物か」を見るが、**走査が同じ場所を別の `asset` として登録し直す**
   ことがある（`store.register()` の「古い場所を外して履歴に残す」道）。実データの
   **実体が在る段 1 の 7 行のうち 6 行がこれ**で、古い `asset_id` を要求すると
   **409 `not_registered`（「その場所は登録されていません」）で永久に進めない**。
   → `advance` は `_target_for_advance()` で**いま登録されている行**を引く（**別のファイルを
   移さない**守りは `(size, mtime_ns)` の照合が持つ）。**`close` は元から `path` しか見ない**。
   **この 6 行の存在は要望の前提（「194 行は実体が無い」）と食い違う**——実体が在るのは 7 行で、
   そのうち 6 行がこの形。
2. **実データの 194 行は「187 行が実体なし・7 行が実体あり」**（`locations_missing` も 187）。
   要望の「194 件をまとめて片付ける」をそのまま押すと
   **「187 件を片付けました。7 件はファイルがまだあるので片付けませんでした。」**になる
   （**意図どおり**。生きているファイルを片付けない）。残る 7 行は
   「アプリのゴミ箱へ移す」で進められる（移した後もアプリのゴミ箱に実体が在る間は片付けを断る
   ＝**ゴミ箱を空にするのは利用者**）。
3. **アプリの再起動が要る**。列 `closed_at` / `close_reason` は `TOP_UP_COLUMNS` で足すので、
   **利用者がアプリを立ち上げ直した時点**で `pre-topup-<日時>` の控えが付いてから列が足される
   （実データは 2026-10-19 10:5x 時点で `closed_at` の列が無い＝**こちらでは 1 バイトも書いていない**）。
4. **`tools/gui_layout.mjs` の段 2 の期待値が古い**（**並行作業の文言の修正の途中**）。
   `pending.js` の `STAGE_LABEL[2]` は「アプリのゴミ箱へ移す」に変わったのに、`gui_layout` の
   `WANT_STAGE[2]` は「2 枚をゴミ箱へ移す」のままなので、**`--screen pending --ids` が 4 件 NG**
   になる（段 2 の実行のボタンと結果の 1 行）。**この行は触っていない**（同じ表の 1 行下を
   相手が編集しているため。`docs/frontend-design.md` §6 の表は「アプリのゴミ箱へ移す」が正）。
   → **文言の担当が直すべき 1 行**。

---

## 4. 検証（三点セット＋複製＋壊し試験）

| 何 | 結果 |
| --- | --- |
| `uv run --no-sync pytest -q` | **547 passed**（実装前 520 ＋ 新規 27。`tests/test_deletions_advance.py`） |
| `node tools/gui_smoke.mjs` | **395 ok**（実装前 365 ＋ 新規 30）・NG 0 |
| `node tools/gui_layout.mjs --base http://127.0.0.1:8796 --screen pending` | **4 窓すべて ok**（`移す=194 片付け=194(0) チェック=194 帯="全部選ぶ 選んだ 0 件 …"`・`overflow=0/0`） |
| `--screen` の他 | `library` / `jobs` / `duplicates` / `requests` / `settings` / `compare --count 8` / `group --group <id>` / `asset --ids <id>` すべて ok |
| `--screen pending --ids <id>,<id>` | **4 件 NG**。**上の「設計の穴 4」**（並行作業の期待値）だけ。段 1 のボタン・結果の 1 行は ok |
| `--screen tags` | **4 件 NG**（`tag` が実データに **0 件**なので語の行が出ない。**私の変更とは無関係**。実データで `tag` 0 行・`asset_tag` 0 行を確認） |
| 複製の実機（`tools/probe_deletions_advance.py`） | **14 件すべて ok**（下の表） |
| 壊し試験（`.tmp-audit-redo/break_tests.py`） | **13/13 が落ちた**（穴 0） |
| 壊し試験（gui_layout） | `bulkHtml()` を空にすると **4 件 NG**（`まとめての帯（）`ほか）＝証拠になる |
| 実データ | **前後で 1 つも変わっていない**（署名 `e9acdcb5…`・`asset` 461 行・段 1 の 194 行・画像 268 ファイル・302,067,405 B）。`.backup/daily` の 3 世代もそのまま |

### 複製で通した線（`tools/probe_deletions_advance.py --port 8796`）

複製は `sqlite3.Connection.backup()` ＋ `shutil.copy2`、**パスは複製の中へ貼り替える**
（貼り替えないと `os.rename` が**実データの画像を動かす**。`make_replica()` の最後で
「複製の外を指す行が 1 つも無い」ことを確かめてから進む）。サーバは
`IMAGE_REVIEWER_DATA=<複製>` と `IMAGE_REVIEWER_BACKUP_DIR=<複製の隣>`（**`%USERPROFILE%` には作らない**）。

```
ok  ファイルがある → アプリのゴミ箱へ移る: 200 to_path=…\data\trash\20261019\3e\…png 実体=True 元=False missing_at=True
ok  「戻す」で元の場所に戻る: 200 restored=True 元=True
ok  ファイルが無い → 409 missing_file: 409 code=missing_file
ok  まとめて片付ける（194 件を 1 回で）: 200 片付けた=187 断った=7（実体あり 7 と一致）
ok  断った理由は file_found（生きているファイルを片付けない）: ['already_restored', 'file_found']
ok  closed_at と close_reason が入る: closed=187（実体なし 187 と一致）
ok  片付けた行の asset.deleted_at はそのまま（カタログに戻さない）: 隠れたまま 187/187
ok  asset と asset_location の行は減らない: asset 461→461・登録 455→455
ok  片付けはファイルを 1 つも動かさない（署名）: 536 件のファイルが同じ
ok  二重に片付けても 200 で replayed（記録は 1 回）: 200 replayed=True
ok  片付けた行は「最近の削除」から外れ、台帳に残る: 一覧に残った=6（断った）台帳=194/194
ok  GET は 1 バイトも書かない: 署名 同じ・台帳の列 同じ
ok  エージェントは片付けられない（403 human_only）
ok  エージェントは段 2 へ進められない（403 human_only）
→ すべて ok（14 件）
```

**「194 件を 1 回で」の意味**（実データで確かめた数）: 段 1 の生きた行は 194 件で、
**実体が在るのは 7 件**。まとめて片付けると **187 件が閉じ、7 件は 409 `file_found` で断られる**
（**その 7 件こそ「アプリのゴミ箱へ移す」で進める行**）。

### 壊し試験（13 件。1 か所だけ壊して、狙った検査が**実際に落ちる**ことを見た）

実体の確認を外す／片付けの判定を外す／`missing_at` を立て忘れる／`closed_at` を書かない／
段 1 に戻し忘れる／上限を外す／片付けた行を一覧から外し忘れる／古い `asset_id` を要求する／
段 3 への直行を許す／まとめての帯を出さない／「アプリのゴミ箱へ移す」を出さない／
片付けの確認を外す／200 件ずつの分割を外す → **13/13 が落ちた**。

**自分の数え方を疑った 2 件**: 最初の実行で `-k missing_file` と `-k moved_the_file` が
**1 件も選ばず**（pytest は「1 件も無い」も終了コード 5 で返す）、**落ちていないのに「落ちた」と
数えていた**。綴り（テスト名）を直して回し直し、**13/13** になった
（`docs/handoff.md`「自分のテストを信じない」の実例）。

### 動かし方（そのまま打てる形）

```powershell
$env:UV_CACHE_DIR = "C:\work\image-reviwer\.uv-cache"
uv run --no-sync pytest -q                                             # 547
node tools/gui_smoke.mjs                                               # 395 ok
.venv\Scripts\python.exe tools\probe_deletions_advance.py --port 8796  # 複製で 14 件の線
.venv\Scripts\python.exe tools\probe_deletions_advance.py --serve --port 8796  # 複製サーバ（gui_layout 用）
node tools/gui_layout.mjs --base http://127.0.0.1:8796 --screen pending
.venv\Scripts\python.exe .tmp-audit-redo\break_tests.py                # 壊し試験 13 件
.venv\Scripts\python.exe .tmp-audit-redo\real_state.py                 # 実データの署名（読み取り専用）
```

**注意（この環境の約束事）**: `gui_layout`（Chrome を起こす）を **Python の `subprocess` から
呼ぶと `%TEMP%` に書けず `EPERM`（mkdtemp）**で落ちる。**PowerShell から直に**回す
（`docs/handoff.md`「sandbox の子プロセスは `%USERPROFILE%` の下に書けない」）。だから
gui_layout の壊し試験は `.tmp-audit-redo/mut_pending.py --on` → `node …` → `--off` の 3 段にした。

---

## 5. 触ったファイル（行数）

| ファイル | 行 | 内容 |
| --- | --- | --- |
| `src/image_reviewer/deletions.py` | +446 / -20（うち**文言の修正＝並行作業が約 21/14**） | `advance` / `advance_many` / `close` / `close_many` / `_advance_one` / `_close_one` / `_target_for_advance` / `_files_of_row` / `_unadvance` / `_require_file_for_advance` / `_run_many` / `_require_batch_size`、`CLOSE_REASONS` / `MAX_BATCH_PER_CALL`、`pending()` / `trash()` / `_restore()` / `_log_doc()` / `_state_of()` の追加 |
| `src/image_reviewer/api/deletions.py` | +70 / -2 | 口 4 つ（`advance` / `advance` まとめて / `close` / `close` まとめて）と docstring |
| `src/image_reviewer/db.py` | +14 / -0 | `deletion_log.closed_at` / `close_reason`（DDL と `TOP_UP_COLUMNS`。**版は上げない**） |
| `apps/gui/pending.js` | +374 / -79（うち**文言の修正＝並行作業が約 103/76**） | ボタン 2 つ・チェック・全部選ぶ・まとめて 2 つ・`advance` / `closeRow` / `runBatch` / `togglePick` / `pickAll`・`bulkHtml`・文言（`ADVANCE_LABEL` / `CLOSE_LABEL` / `SKIP_TEXT` / `advanceDoneText` / `closeDoneText` / `closeConfirmText`） |
| `apps/gui/index.html` | +6（私の分） | `#pd-bulk`（まとめての帯）を 1 つ足しただけ |
| `apps/gui/styles.css` | +22（私の分） | `.pd-bulk` / `.pd-all` / `.pd-pick` / `.pd-nopick` |
| `docs/frontend-design.md` | +62（私の分） | §4.6 に 5 項（後から段 2・片付け・まとめて）、§6 の表に 7 行（**先に直してから実装**） |
| `tools/gui_smoke.mjs` | +120（私の分） | P10 の検査 30 件（押す検査・分割・断りの数え方） |
| `tools/gui_layout.mjs` | +41（私の分） | `MEASURE_PENDING` に P10 の計測、pending の検査 10 件、表示に `移す=/片付け=/チェック=/帯=` |
| `tests/test_deletions_advance.py` | **677 行（新規）** | 27 件（advance 8・close 8・まとめて 5・読み 1・口 3＋…） |
| `tools/probe_deletions_advance.py` | **532 行（新規）** | 複製（`backup()` ＋ `copy2` ＋**パスの貼り替え**）と 14 件の線・`--serve` |
| `docs/deletions-advance.md` | 本文書 | 記録 |

**触っていない物**: `docs/design.md`・`README.md`・`docs/japanese-ui-fix.md`・CLI（**並行作業の担当**）。
`docs/design.md` §16/§17 への反映は**全段が終わってから 1 回で**行うのが家風なので、ここでは
書いていない（文言は `frontend-design.md` が正）。

---

## 6. 申し送り

1. **利用者のアプリは止めていない**（8790 は生きている）。新しい口は**再起動後**に使える
   （そのとき `pre-topup-*` の控えが付く）。実データは**読み取り専用でしか開いていない**。
2. **`tools/gui_layout.mjs` の `WANT_STAGE[2]`** は文言の担当が直す（設計の穴 4）。
3. **`--screen tags` の NG は前提（語 0 件）**。データを入れるか、検査の前提を書き換えるかは
   監査の判断。
4. 使い捨ては `.tmp-audit-redo/`（`advance-*` の複製・`break_tests.py`・`mut_pending.py`・
   `real_state.py`）。**他の担当の複製サーバ（8795）は止めていない**。自分の複製サーバ（8796）は
   用が済んだら止める（`probe_deletions_advance.py --serve` は Ctrl+C で止まる）。
5. **`gui_layout` は %TEMP% に 713 個の `gui-layout-*` を残していた**（昔の実行の蓄積）。
   掃除はしていない（他の担当の実行中かもしれない）。
