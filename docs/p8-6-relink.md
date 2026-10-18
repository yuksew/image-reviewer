# P8-6（参照切れの再リンク）の実装

- 段: **P8-6**（`docs/p8-design.md` §0.1 の P8-3 で「画面」に置き換わって残っていた**線 9**）
- 日付: 2026-10-18（JST 10:00〜10:45）
- 正とした文書: [`p8-design.md`](p8-design.md) **§0.11**（中身を確かめてから繋ぐ）・**§1.2 の線 9**・
  **§3.2**（口）・**§3.4**（エラーの形）・**§4.1**（状態）・**§8.1 の 22**、
  [`design.md`](design.md) §5.1・§6.1（`POST /api/locations/relink` の字）、
  [`duplicates-deletion-backup.md`](duplicates-deletion-backup.md) §4（専門文書）
- 依頼: 「P8 の設計で唯一実装されずに残っていた物（線 9）を実装する」＋
  **追加指示**（親）: 「`create_app()` を、`cli serve` 以外は実データで開けない形にする」
  （事故 3 件目の再発防止。§5）

## 1. 作ったもの（ファイルと行数）

`git diff --numstat 3f75484`（P8-5 のコミット＝この作業の直前）より。
**私は `git` のコミットをしていない**（`tools/probe_p8.py` などの行数は作業木の値）。

| ファイル | 行数 | 何をしたか |
| --- | --- | --- |
| `src/image_reviewer/relink.py` | **485（新規）** | `RelinkService`（`missing()` と `relink()`）・`sha256_of()`・語彙の検査。**ファイルを 1 つも動かさない**（`unlink` / `rename` を呼ばない） |
| `src/image_reviewer/api/relink.py` | **61（新規）** | `POST /api/locations/relink`（**人だけ**）と `GET /api/locations/missing`（**読むだけ**） |
| `src/image_reviewer/api/__init__.py` | +5 | `relink_of(request)`（`app.state` から取る。閉包で掴まない） |
| `src/image_reviewer/app.py` | +32 / -1 | `RelinkService` の配線・router の登録・**`create_app()` の硬化**（§5。`DATA_ENV` / `DEFAULT_DATA_DIR`） |
| `src/image_reviewer/cli.py` | +24 | `serve_data_dir()` を足し、**`serve` が既定の `.data` を明示的に指してから**アプリを作る（利用者の起動は今までどおり） |
| `src/image_reviewer/db.py` | +23 / -2 | **`location_history` に `to_path` / `reason` / `actor`**（DDL と `TOP_UP_COLUMNS`。§4-1） |
| `src/image_reviewer/store.py` | +9 / -3 | `register()` が `reason='replaced'` を書く・`location_history()` が 3 列も返す |
| `tests/test_relink.py` | **741（新規）** | 26 件（**壊すと落ちる**形。§3） |
| `tests/test_data_dir_guard.py` | **125（新規）** | 4 件（硬化。**別プロセスで実データの署名を比べる**。§5） |
| `tests/test_backup.py` | +3 / -1 | `test_get_endpoints_write_nothing` に `/api/locations/missing` を足した（**`GET` は書かない**の検査を 1 本に集める） |
| `tools/probe_p8.py` | +185 / -1 | **`--relink`（線 9）** を足した（`--all` にも入る） |
| `docs/p8-6-relink.md` | **この文書** | 実装の記録（設計の穴・決めた点・事故・申し送り） |

**触っていない物**: `.data/`（**`mode=ro` と `stat` / `sha256` の読みだけ**）・画像・`README.md`・
`docs/design.md`・`docs/p8-design.md`（履歴）・`schemas/`（**契約は足していない**）・`ComfyUI`・8790。
`apps/gui/`（**画面は作らない**との指示。`tests/` の 2 本以外は GUI を触っていない）。

**使い捨て**（`.tmp-audit-redo/p8-6/`）: `probe_relink.py` は `tools/probe_p8.py --relink` に取り込んで消した。
残した物は `accident_backup.py`（事故の控え）・`mutants.py`（壊し試験）・`make_replica.py`・`count_lines.py`。

## 2. 実行したコマンドと結果

`$env:UV_CACHE_DIR = "C:\work\image-reviwer\.uv-cache"`、`cd C:\work\image-reviwer`。

| 何 | コマンド | 結果 |
| --- | --- | --- |
| **pytest** | `uv run --no-sync pytest -q -p no:cacheprovider`（全件 ×**3**） | **507 passed**（36.6〜37.2 秒）が 3 回連続で緑（P8-5 の 477 ＋ 新規 **30**） |
| **線 9（複製）** | `uv run --no-sync python -X utf8 tools/probe_p8.py --relink` | **16 行すべて OK**（§3） |
| **壊し試験** | `uv run --no-sync python -X utf8 .tmp-audit-redo/p8-6/mutants.py` | **7 通り中 7 通りが落ちた**（戻しの確認つき。§3） |
| **gui_smoke** | `node tools/gui_smoke.mjs`（作業木） | **291 ok / 3 NG**。**NG は他担当が編集中の `apps/gui/settings.js` と `tools/gui_smoke.mjs` による物**（下） |
| gui_smoke（HEAD の GUI） | `git archive HEAD apps/gui tools/gui_smoke.mjs` → 展開して `node …/gui_smoke.mjs` | **291 ok / NG 0（すべて ok）**。**私の変更（Python だけ）で壊れていない**証拠 |
| **gui_layout** | 複製（8791）で **11 本**（下） | **すべて ok**（各 3 窓） |
| 契約 | `uv run --no-sync --with jsonschema python -X utf8 tools/check_contract_p8.py` | **OK 24 / NG 0**（**契約は足していない**ので前のまま。「`review-export` の契約は変えていない」も OK） |
| 実データ | `uv run --no-sync python -X utf8 .tmp-audit-redo/p8-6/final_real_check.py` | **263 枚・`missing_at` 0 件・判断 3 件・`quick_check ok`**。画像 20 枚の署名は同じ（§5） |

### gui_layout の 11 本（複製 8791。各 3 窓）

```text
--count 8                                   比較（8 枚）
--screen requests                           要求の一覧
--screen group --group 01M55R95PD89SR1EVB0JT480G2   まとまりレビュー
--screen asset --ids 01M4Z0KJR69CW8RA2R5Q9ZXHHW    注記とタグ
--screen tags                               語の一覧
--screen jobs                               ジョブ
--screen duplicates                         重複の整理
--screen pending                            最近の削除
--screen pending --ids 01M4Z0KJR69CW8RA2R5Q9ZXHHW  最近の削除（削除の確認つき）
--screen library                            ライブラリ（下部バーの入口）
--screen settings                           設定
```

- 複製は `.tmp-audit-redo/p8-6/gui`（`sqlite3` の `backup()` で作る。**画像はコピーしない**＝
  `asset_location` が実データのパスを指しているので、そのまま読める。**1 枚も動かしていない**）。
  サーバは `IMAGE_REVIEWER_DATA=<複製>`・`IMAGE_REVIEWER_BACKUP_DIR=<複製の外>` で 8791 に立てた。
- 止める前に **`GET /api/health` の `data_dir` が複製であることを確かめてから** `Stop-Process` した
  （8790 は止めていない。**8791〜8795 は最初から誰も居らず、私が使ったのは 8791 だけ**）。
- 前提（語・除外の理由・段 3 の保留）は `tools/gui_layout_seed.py --data <複製> --tags --exclusion
  --pending --stage3` が**複製の中に**作った（**実データは断る**）。seed 無しで `--screen tags` を回すと
  `rows=0` で NG になる（P8-5 の D-6 と同じ。**前提が要る画面**）。
- **作業木の `gui_smoke` の 3 NG は私の変更ではない**（私は Python しか触っていない）:
  別の担当が `apps/gui/settings.js`・`apps/gui/pending.js`・`tools/gui_smoke.mjs` を**同時に編集中**で
  （`git status` に現れている）、その途中の 3 件（`今日の分は取れています。` / `いま取りました` /
  `DB の検査に通りませんでした。`）が NG になっている。**HEAD の GUI では 291 ok / NG 0**。
  **私はその 3 ファイルを触っていない**（衝突を避けるため、直しにも行っていない）。

## 3. 複製で通した結果（線 9）と「壊すと落ちる」

### `tools/probe_p8.py --relink`（実データの複製。`TestClient` で本物の HTTP）

実データは `mode=ro` で読み、**DB は `backup()`・画像も `copy2` して登録を向け直してから**動かす。

```text
[OK] 最初は参照切れ 0（実データと同じ）: total=0
[OK] 線 9 の前半（動かして走査 → missing_at が立つ）: scan missing=1 / 一覧 1 件
[OK] エージェントは 403 human_only
[OK] 中身が違えば 409 hash_mismatch
[OK] 既に別の画像に登録済みなら 409 path_taken
[OK] 線 9 の後半（人が繋ぎ直せる・同じ asset のまま）: 200 moved=True
[OK] missing_at が NULL に戻り、場所が新しいパスになる
[OK] 判断が保たれる（同じ asset・kept のまま）: kept={'decisions': 1, 'tags': 1, 'locations': 1, …}
[OK] タグが保たれる（語で引ける）: probe-relink の枚数 2 / kept.tags=1
[OK] location_history に 1 行（移動元 → 移動先・理由・人）: reason=relinked
[OK] 一覧から消える（参照切れ 0）
[OK] ファイルは動かしていない（新しい場所に在る・古い場所には無い）
[OK] nearby（同じ名前を置き場から探して繋ぐ）: 200 searched=1
[OK] GET /api/locations/missing は書かない
[OK] location_history に to_path / reason / actor が入っている
[OK] 実データが無傷（複製だけで試した）: 263 枚 / 判断 3 件 / 参照切れ 0 件
まとめ: すべて OK
```

- **成功**: `{asset_id, path, mode:'exact'}` → 200・`moved: true`・`missing_at` が NULL・
  同じ `asset`（`sha256` も判断もタグもそのまま）・`location_history` に 1 行。
- **ハッシュ違い 409**: `code: "hash_mismatch"`（`details.expected` / `actual`）。
- **登録済み 409**: 別の `asset` なら `path_taken`（`details.asset_id`）、同じ `asset` の生きた場所なら
  `already_registered`。**主キーに当てて 500 にしない。**
- **エージェント 403**: `human_only`。**登録は 1 バイトも変わらない**（`missing_at` が同じ）。
- **`GET` は書かない**: 全表の中身と `<data>` の全ファイルの `(size, mtime_ns)` を前後で比べた。

### 壊し試験（`.tmp-audit-redo/p8-6/mutants.py`。ソースを一時的に書き換え、**必ず戻す**）

| # | 壊した物 | 落ちた試験 |
| --- | --- | --- |
| 1 | **ハッシュの照合を外す**（`if False:`） | `test_the_content_is_compared_by_sha256`（＋ nearby の同名別内容） |
| 2 | **`missing_at` を戻し忘れる**（`UPDATE` から `missing_at = NULL` を抜く） | `test_exact_relink_connects_the_new_path_and_keeps_the_asset` ほか |
| 3 | **二重登録を許す**（`_refuse_if_registered` を消す） | `test_a_path_registered_to_another_asset_is_refused` / `…_same_asset_is_refused`（`IntegrityError` になる） |
| 4 | **`location_history` を書かない** | `test_the_relink_is_recorded_in_location_history` |
| 5 | **人だけの検査を外す**（`require_human` を消す） | `test_the_endpoint_is_human_only`（403 が 200 になる） |
| 6 | **`GET` が書く**（一覧で `asset_location` を書き換える） | `test_the_missing_list_writes_nothing` |
| 7 | **移行を外す**（`TOP_UP_COLUMNS` から 3 列を消す） | `test_an_old_database_gets_the_history_columns`（古い DB に列が入らない） |

**7/7 が落ち、7/7 とも元に戻った**（`finally` と読み直しで確認。`grep mutant src/` は 0 件）。

- **`create_app()` の env 検査は壊し試験に入れていない**。壊すと子プロセスが**実データを開いて
  しまう**（＝ P8-6 の事故そのもの）ので、試さない方が正しい（テスト 4 件は別プロセスで
  「例外になる」ことと「`.data` の署名が変わらない」ことを見ている）。

## 4. 設計からずれた所・自分で決めた所（1 行ずつ理由）

### 4.1 設計の穴（**設計が黙っていた／足りなかった**）

| # | 穴 | どうしたか |
| --- | --- | --- |
| **1** | **`location_history` に「入れ替わった」と「繋ぎ直した」を区別する列が無い**（§0.11 は「`location_history` に『入れ替わった』『繋ぎ直した』を残す」と言うが、列は `path` / `size` / `mtime_ns` / `replaced_by_asset_id` / `replaced_at` だけ） | **`to_path` / `reason` / `actor` を足した**（`db.py` の DDL と `TOP_UP_COLUMNS` の両方。**版は上げない**＝既存の DB には `Store` が開く前に `pre-topup-*` の控えを取ってから当たる。§5） |
| **2** | **`nearby` の `path` の意味が書いていない**（設計 §3.2 は `{asset_id, path, mode}` の 3 つだけ） | **`exact` は「新しいファイル」・`nearby` は「探すフォルダ（ファイルを渡したらその親）」**と決めた（`nearby` で `path` を省くと**登録した置き場ぜんぶ**を同じ名前で歩く） |
| **3** | **「同じルート内をファイル名で探す」は空振りになる**（走査は知らないパスの画像をその場で `register()` するので、走査した置き場の中で動いた物は**走査の時点で既に繋がっている**。専門 §4 の表のとおり） | **`nearby` の探索を「置き場ぜんぶ（＋指定フォルダ）」にした**（同じ置き場の中だけだと候補が 0 件になる）。**この挙動はテストで固定した**（`test_a_file_moved_inside_a_scanned_root_is_already_linked_by_the_scan`） |
| **4** | **段 2・3 の削除も `missing_at` を立てる**（§0.16 A3）ので、「参照切れ」と「アプリから消した物」が同じ印になる | `GET /api/locations/missing` は **`asset.deleted_at` が立っている物を既定で外し、`excluded_deleted` に数える**（`include_deleted=1` で出す）。**繋ぎ直しも 409 `deleted`** で断り、`undo` の口を案内する |
| **5** | **走査済みの置き場の中で動くと、同じ `asset` に「生きた行」と「参照切れの行」が 1 つずつできる**（一覧には参照切れとして出るが、実体は別の場所にある） | 一覧の各項目に **`other_live_locations`** を足した（画面が「別の場所に在ります」と出せる）。**行は消さない**（消すのは削除の道の仕事） |
| **6** | **「自動（走査のたびに繋ぐ）」は作っていない**（§0.11 の 3 つ目の手段） | **作らなかった**。理由: ①線 9 は「近くを探す」「場所を指定」の 2 つで通る ②走査は既に同じ `sha256` を同じ `asset` に登録するので、自動で繋ぐ余地は「走査していない置き場」だけ ③`duplicates-deletion-backup.md` §4 の「**勝手に繋がない**」に従う |

### 4.2 自分で決めた点（設計に無い）

1. **照合は `sha256` だけ**。`size` / `mtime_ns` は見ない（§0.11）。**pHash（`compare.hash_file`）は
   使わない**——知覚ハッシュは「似た別の絵」を同じと見なすので、**利用者の「同じ絵かどうか」を守れない**
   （§0.11・§3.4・§8.1 の 22 が `sha256` と言っている）。
2. **行を消さずに `asset_location.path` を付け替える**（`UPDATE`）。消して入れ直すと `is_primary` と
   「いつから見ているか」が失われる。`is_primary` は触らない。
3. **元のパスに戻ってきた**（同じ鍵）ときは `missing_at` を戻すだけで**履歴を増やさない**
   （`moved: false`）。動いていないのに履歴を書くと履歴が嘘になる。
4. **`asset.deleted_at` の引き直しは `DeletionService._sync_hidden()` を呼ぶ**（規則を 1 か所に保つ）。
   段 1 で外したままの画像は、繋ぎ直しても一覧には戻らない（利用者の意思を消さない）。
5. **口の語彙**: `mode` は `exact` / `nearby` だけ（外は 422 `bad_mode`）・`asset_id` の欠落は 422
   `bad_request`・`path` の欠落は 422 `bad_path`・`limit` は 0〜5000（真偽値と小数は通さない）。
6. **`GET /api/locations/missing` は人もエージェントも読める**（`GET` は書かない）。`count` と
   `total` と `unlisted` を返す（**数を黙って捨てない**）。既定 `limit` は 500。
7. **`nearby` は候補を決定的に選ぶ**（大小文字を畳んだパスの順）。**選ばなかった一致も `also_found`**
   で返し、読めなかった候補は `unreadable`、打ち切ったら `candidates_truncated`（上限 200）。
8. **`register()` が `reason='replaced'` を書くようにした**（新しい列の語彙を正直にする。
   古い行は `NULL`＝「列を足す前の入れ替わり」）。
9. **`store.location_history()` が 3 列も返す**（読む側が履歴を区別できる）。
10. **`tests/test_backup.py` の「`GET` は書かない」に `/api/locations/missing` を足した**
    （検査を 1 本に集める。P8-4 の監査 F(e) の形）。
11. **`tools/probe_p8.py` に `--relink` を足した**（線 9 の置き場。`--all` にも入る）。
12. **`create_app()` の硬化**（親の追加指示）: `IMAGE_REVIEWER_DATA` が無ければ**開く前に `RuntimeError`**。
    `data_dir()` の既定は残し、**`cli serve` が既定を明示的に指してから**アプリを作る（§5）。

## 5. 実データと、事故 3 件目（P8-6）・再発防止

### 事故（私のミス。**隠さずに記録する**）

- **2026-10-18 10:03 JST**、私が `IMAGE_REVIEWER_DATA` を付けずに
  `uv run --no-sync python -c "import image_reviewer.app as m; m.create_app()"` を実行し、
  **実データ `.data/db.sqlite3` を書き込み可で開いた**（`_top_up_v6` が走った）。
- 変わった物: ①**`location_history` に 3 列**（`to_path` / `reason` / `actor`）が控え無しで足された
  ②`settings` の `backup.last_error` / `last_error_at`（控えを作ろうとして `%USERPROFILE%` が
  sandbox に拒否された `WinError 5`。**利用者の画面には元から同じ失敗が出ていた物**で、
  文言に「表の形を変える前の控えを取れませんでした: 」の前置きが付き、時刻が 10:03 に更新された）。
- **行は 1 つも変わっていない**: 263 枚・`asset_location` 263 行・`missing_at` 0 件・判断 3 件・
  `deletion_log` 0 行・`user_version` 6。`.data` で変わったファイルは `db.sqlite3-wal` だけ。
- 後始末: **`sqlite3.Connection.backup()` で控えを取った** →
  **`.backup/pre-p8-6-20261018-100443/db.sqlite3`**（263 枚・判断 3 件・`quick_check ok`。
  手順は `.tmp-audit-redo/p8-6/accident_backup.py`）。**列は消していない**（P8-4 の監査 G-9 と同じ判断＝
  作業木の DDL と `TOP_UP_COLUMNS` が同じ形を期待しており、**消すのもまた控え無しの書き込み**になる）。
- **事故 3 件の型**（すべて同じ形である）:
  1. P8-4 の監査 G-8: **`import` で `create_app()` が走った**（モジュールの末尾。実データに `stuck_reason`）
  2. P8-4 の監査 G-9: **版を上げずに列を足す道に控えが無かった**（同じ列が控え無しで入った）
  3. **P8-6**: **検証スクリプトが `create_app()` を明示的に呼び、env を付け忘れた**

### 再発防止（この段の実装。親の追加指示）

- **`create_app()` は env が無ければ開かない**（`app.py`）:
  `RuntimeError("実データを開こうとしています。IMAGE_REVIEWER_DATA=<複製> を付けてください
  （アプリは `image-reviewer serve` から起動してください）")`。**判定は一番先頭**（`inspect_db` よりも前）なので
  **1 バイトも書かない**。
- **`cli serve` は今までどおり動く**（`cli.serve_data_dir()` が**既定の `.data` を明示的に指してから**
  `uvicorn.run(..., factory=True)` する）。`uvicorn image_reviewer.app:app` を env 無しで叩いても開かない。
- **テスト 4 件**（`tests/test_data_dir_guard.py`）:
  ①env 無しの `create_app()` は**別プロセス**で例外になり、**`.data` の全ファイルの大きさと mtime が
  変わらない**（遅延の `image_reviewer.app:app` の道も同じ）②複製を指せば開く
  ③`serve_data_dir()` が既定を指す（既に指してあればそのまま）④pytest の間は必ずテストの中を指している。
- 私の以後の運用: **実データを触り得るコマンドは必ず `IMAGE_REVIEWER_DATA=<複製>` か `mode=ro`**。
  `pytest` は `conftest.pytest_configure` が収集の前に向けるので安全（テスト ④が見張る）。

## 6. 申し送り（親が文書に反映する分）

1. **`docs/design.md` §6.1 の「まだ無い」3 行**（`POST /api/locations/relink`）を**実装済み**に。
   `GET /api/locations/missing` の行も足す（**読むだけ**。`limit` / `include_deleted` / `excluded_deleted`）。
2. **`location_history` の 3 列**（`to_path` / `reason` / `actor`）を §5.1 と §5.8 の表に。
   **`db.TOP_UP_COLUMNS` が正**（`pre-topup-*` の控えが付く）。
3. **事故 3 件目と硬化**: `create_app()` は `IMAGE_REVIEWER_DATA` が必須・`cli serve` が既定を明示。
   README の「動かす」は `image-reviewer serve` のままでよい（**env を手で付けるのは複製を立てるとき**）。
4. **`duplicates-deletion-backup.md` §4** の「自動」は**作っていない**（§4.1-6 の理由）。
5. `docs/p8-design.md` は**触っていない**（親の担当）。§0.11 に「`nearby` の `path` はフォルダ」の 1 行を
   足すなら、この文書の §4.1-2 が元。
6. **画面は作っていない**（指示どおり）。`GET /api/locations/missing` の応答の `hint` に
   `POST /api/locations/relink` の形を書いてあるので、口だけでも使える。

## 7. 確かめられなかったこと

- **`--no-hash` の未同定の扱い**（専門 §7-5。P8 では作らないと決めた物）は、再リンクでも触っていない。
- **別ボリュームの再リンク**は「ファイルを動かさない」ので、削除の `cross_volume` のような制約が無い
  （確かめる対象が無い）。**この機械に 2 つ目のボリュームが無い**ので、実際に別ドライブのファイルを
  繋ぐ試験は**実行していない**（`sha256` の照合しかしないので、理屈の上では同じ）。
- **1 万枚の置き場で `nearby` を回した時間は未計測**（この実データは 263 枚。`nearby` は
  ディレクトリを歩くだけで、ハッシュするのは**同じ名前の候補だけ**＝上限 200）。
- **実機 8790 は古い Python のまま**（`POST /api/locations/relink` は 404）。**利用者のアプリは止めていない**ので、
  新しい口が実機で動くのは**次に 8790 を立て直したとき**になる（画面が無いので実害は無い）。
