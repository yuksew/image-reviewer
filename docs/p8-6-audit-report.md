# P8-6 監査報告（参照切れの再リンク＝線 9。`GET /api/locations/missing`・`POST /api/locations/relink`・`create_app()` の硬化）— 実行込み

- 日付: 2026-10-18（JST 10:50〜11:50）
- 根拠: `docs/p8-design.md` §0.11・§1.2 の線 9・§3.2（口の表の `POST /api/locations/relink`）・§3.4・§8.1 の 22、`docs/duplicates-deletion-backup.md` §4（P8-6 で書き足した注記を含む）。実装の記録: `docs/p8-6-relink.md`（236 行。設計の穴 6・決めた点 12・事故 1・申し送り 6）。
- 対象（コミット `d52a945`。`3f75484` から 23 ファイル +3087/-240 のうち P8-6 の分）: `src/image_reviewer/relink.py`（485 行。新規）、`api/relink.py`（61 行。新規）、`api/__init__.py`（`relink_of`）、`app.py`（配線・**`create_app()` の硬化**・`DATA_ENV` / `DEFAULT_DATA_DIR`）、`cli.py`（`serve_data_dir()`）、`db.py`（`location_history` の `to_path` / `reason` / `actor`。DDL と `TOP_UP_COLUMNS`）、`store.py`（`register()` が `reason='replaced'`・`location_history()` が 3 列返す）、`tests/test_relink.py`（741 行・26 件）、`tests/test_data_dir_guard.py`（125 行・4 件）、`tools/probe_p8.py --relink`。監査中の `git status` は本報告だけが untracked（他の担当の編集は無かった）。
- 環境: `uv run --no-sync`。実データ `.data` は `mode=ro` と `backup()` の複製だけ。**画像は 1 枚も動かしていない**（最後の署名で確認。ただし **H の事故 1 件**: 私の脚本が実データの画像 1 枚を `shutil.move` しようとして sandbox に止められ、写しが 1 つできた。元は無傷）。複製は `.tmp-audit-redo/p8-4-audit/gui`（`replica_gui4.py`＝`backup()`＋13 枚を `gui-lib/` に `copy2`）、脚本と出力は `.tmp-audit-redo/p8-6-audit/`。置き場は `.tmp-audit-redo/p8-6-audit/backups/`（`%USERPROFILE%` の下には作っていない）。
  複製のサーバは **8793**（`IMAGE_REVIEWER_DATA` つき。止める前に `/api/health` の `data_dir` を確かめた）。**8790 は止めていない**（PID 39508・10:48 起動＝P8-6 入り。`GET /api/locations/missing` が 200 で `total 0`。送ったのは GET だけ）。8791〜8795 の他の担当のサーバは居なかった。ComfyUI は触っていない。コミットしていない。
- 実データ: 最初と最後に `mode=ro` で **v6・24 表・263 枚・判断 3 件・`missing_at` 0・台帳 0・`location_history` 0 行**、画像 263 枚の署名 **`fa99ca126c393d5a`・292,561,491 B**（前回と同じ）。`location_history` には実装者の事故で足された 3 列が在り（`missing_top_ups` は空）、`.backup/` は 9 フォルダ（`pre-p8-6-20261018-100443` が実装者の控え。消していない）。
- 回帰: **pytest 507 passed ×3**（36.7 / 36.7 / 36.5 s）、**gui_smoke すべて ok（310 ok / NG 0）**、**gui_layout 11 本すべて ok（各 3 窓）**、`check_contract_p8.py` は前のまま。

## 判定: **合格（条件つき）**

**線 9 を私の手で通した**（複製 8793・本物の HTTP。`relink_check.py` R1〜R17・`relink_check2.py`）: 複製の画像 X（判断 1 件・語 1 つ・来歴あり）を `gui-lib/` から走査外の `moved/` へ動かし → `POST /api/scan {roots:[gui-lib]}` で `missing 1`・`GET /api/locations/missing` に `roots` つきで出る（R1）→ `POST /api/locations/relink {asset_id, path, mode:'exact'}` で **200 `moved: true`**・`missing_at` が NULL・`display_path` が新しい場所・同じ `asset`（`sha256` 同じ）（R6）→ **判断 1・タグ 1・来歴（`meta_json`）・`review_state kept` が DB でも API でも場所以外は同じ**（R7）→ **`location_history` に 1 行**（`path`=移動元・`to_path`=移動先・`reason relinked`・`actor human`・`replaced_by_asset_id` NULL。R8）→ 一覧から消え（R10）、`gui-lib/`・`moved/`・`moved2/` の全ファイルの署名は **relink の前後で同じ**（R9＝アプリはファイルを動かさない。`relink.py` に `rename` / `replace` / `unlink` / `shutil` の呼び出しは無く、import は `hashlib` と `scan.iter_images` だけ）。**照合は `sha256` だけ**: 同じ絵の末尾に 1 バイト足した写し（pHash なら同じ絵）は `exact` も `nearby` も **409 `hash_mismatch`**（`expected` / `actual` つき。R3）。`compare.hash_file` / pHash の参照は無い。**二重登録しない**: 別の `asset` の生きたパス → 409 `path_taken`（`details.asset_id`）、同じ `asset` の生きた場所 → 409 `already_registered`、段 2 で消した物 → 409 `deleted`（`details.undo` に口）、参照切れが無い → 409 `not_missing`、2 か所 → 409 `ambiguous`（`from_path` で通る）。**500 は 0 本**（R4・R11〜R15・R17）。**`create_app()` の硬化**: `IMAGE_REVIEWER_DATA` を外した別プロセスで `create_app()`・`m.app`・`from image_reviewer.app import app` の 3 つとも `RuntimeError`（文言に `IMAGE_REVIEWER_DATA=<複製>`）で止まり、**`.data` の全ファイル（`db.sqlite3`・`-wal`・`-shm`・`store.json` ×2）の大きさと mtime が前後で同じ**。複製を指せば開く。`cli.serve_data_dir()` は env が無ければ既定の `.data` を立てて返す（アプリは作らない）。8790 は `cli serve` から立ち、`data_dir` は `.data`（今までどおり）。**人だけ**（エージェント 403 `human_only`・`robot` 422・`Host: evil` 403・`text/plain` 403）、**GET は書かない**（一覧の 5 変種を叩いて全表の中身の sha256 と全ファイルが同じ。R16）、`limit 5001` / `include_deleted 2` は 422。壊し試験は実装者の 7 通り＋私の 8 通りで **15 通り中 13 通り**が落ちる（F）。

条件は 1 つ。**C-1 同じ場所にファイルが戻ってきても、走査では参照切れが消えない。** `scan.py:75-78` は「既知のパスで `size` と `mtime_ns` が同じ」なら登録を触らずに `known` と数えるだけで、`missing_at` を戻さない（`store.register()` の `missing_at = NULL` に届かない。R12a）。移動は mtime を変えないので、**いったん別の場所へ動かして戻した枚は、走査を何度回しても「参照切れ」のまま**で、人が `POST /api/locations/relink` を**同じパスに**打つ（`moved: false`。R12b）か、ファイルを触って mtime を変えるしかない。P8-6 の口が無かった時代からの穴だが、**線 9 の「走査 → `missing_at`」の裏返し（戻ってきたら走査で戻る）が成り立たない**。推奨 G-1。ほかに中程度 2 件: **C-2 `nearby` の `path` 省略は「登録した置き場ぜんぶ」を歩く**（実データでは ComfyUI の出力 181 ファイル 306 MB の root も含む。名前で絞るので `sha256` を読むのは同名の候補だけだが、`iter_images` の歩き自体に時間が掛かる形。H）、**C-3 `_refuse_if_registered` が取引の外**（同時に同じパスへ 2 本来ると `asset_location.path` の主キーで `IntegrityError`。実測では P8-4 の `sqlite_error_handler` がそれを拾って **503 `db_error`「DB が壊れているので読めません。バックアップから戻してください」** を返す＝壊れていないのに復元を勧める）。

**最も重大な 3 件**

1. **C-1 元の場所に戻ってきたファイルを走査が生き返らせない。** 再現（`relink_check2.py` R12a。複製）: X を `moved/` へ → 走査 → `missing_at` 立つ → **同じパスへ戻す** → 走査 → `scan.known` に数えられ **`missing_at` はそのまま**（`2026-10-18T01:56:38Z`）。`store.register()` には `missing_at = NULL` が在る（`store.py:349-353`）が、`scan.py:76` の早道（`size` / `mtime_ns` が同じなら `register` を呼ばない）がそれを飛ばす。`relink` を同じ鍵に打つと戻る（R12b: 200 `moved: false`・履歴は増えない）ので P8-6 の口で救えるが、**利用者は「元に戻したのに参照切れのまま」を見て、何を押せばよいか分からない**（画面は無い）。推奨 G-1: 早道の中で `known["missing_at"]` が立っていれば `missing_at = NULL, last_seen_at` を書く（1 文）。試験は「動かして戻して走査 → 参照切れ 0」。
2. **C-2 `nearby` の `path` 省略は登録した置き場ぜんぶを歩く。** `relink.py` `_search_nearby`（`folders = [Path(r) for r in roots]`）。設計 §0.11 の「同じルート内」を「置き場ぜんぶ」に広げた決めた点（記録 §4.1-3）は、走査済みの置き場では空振りになる理由も含めて妥当だが、**歩く範囲が利用者の全置き場**になる（実データなら `illust-authoring` 262 枚と ComfyUI 出力 181 ファイル＝306 MB。名前の照合は `os.walk` だけなので数秒、`sha256` は同名の候補だけ）。1 万枚級では `POST` が待たされる（記録 §7 も未計測）。推奨 G-2: `nearby` は既定で**その参照切れを含む置き場**（`missing` 応答の `roots`）から歩き、見つからなければ残りへ、と 2 段にする。または `candidates_truncated` と同じ形で `folders` を返しているので、画面では「探す範囲」を見せる。
3. **C-3 二重登録の検査が取引の外。** `relink.py` `_refuse_if_registered`（`store.locked()` で読む）→ `_sha256_or_error`（ファイルを読む。長い）→ `store.transaction()` で `UPDATE`。この間に別の要求が同じパスを登録すると `UPDATE asset_location SET path = ?` が主キーに当たる。**実測**（検査を外した写し `mut/M3` で、別の `asset` の生きたパスへ `relink`）: `IntegrityError` は P8-4 の `sqlite_error_handler`（`sqlite3.DatabaseError` の子）に拾われ、**503 `db_error`「DB が壊れているので読めません。バックアップから戻してください」**（直後の `GET /api/health/db` は 200 `ok`）。500 ではないが、**壊れていない DB で復元を勧める文**が出る（§3.2「主キーに当てて 500 にしない」の趣旨にも、P8-4 の handler の守備範囲にも合わない。D-8）。人だけの口で同時は稀だが、`nearby` が `sha256` を 200 候補まで読む間は窓が広い。推奨 G-3: `UPDATE` の直前（取引の中）でもう一度 `SELECT asset_id FROM asset_location WHERE path = ?` を見て 409 `path_taken` にする（1 文）。

---

## A. 直っていない／設計の約束が成り立たない

- 無し。

## B. 重大

- 無し。

## C. 中程度

### C-0 確かめた結果、問題なし（1 行ずつ。実行したもの）

- **線 9**（R1・R6〜R10）: 上の判定の段落。`kept` の応答（`decisions 1 / tags 1 / locations 1 / has_provenance true`）と DB の直読みが一致。
- **`sha256` だけ**（R3）: 1 バイト違いの写しは `exact` / `nearby` とも 409 `hash_mismatch`。`relink.py` の import は `hashlib`・`db`・`deletions`・`review`・`scan.iter_images`・`store`（`compare` 無し）。
- **ファイルを動かさない**（R9）: `gui-lib` 13＋`moved`・`moved2` の 15 ファイルの `(path, size, mtime_ns)` が relink の前後で同じ。`grep` で `rename` / `replace` / `unlink` / `shutil` 0 件。
- **二重登録しない**（R4・R12c・R13・R15・R11）: `path_taken`・`already_registered`・`ambiguous`（`from_path` で通る）・`deleted`（`details.undo` に `/api/pending-deletes/<id>/undo`）・`not_missing`。全部 409。段 2 で消した物は `GET /api/locations/missing` の既定から外れて `excluded_deleted 1`、`include_deleted=1` で出る。
- **硬化**（別プロセス ×3・複製で開く・`serve_data_dir()`。`tests/test_data_dir_guard.py` の 4 件も緑）。`.data` の 5 ファイルの `(size, mtime_ns)` が前後で同じ。
- **口**（R2・R5・R16）: 403 / 422 / 404 の形。`GET` はエージェントも読める。`GET` は書かない。
- **`nearby`**（R14・relink_check2 R14）: 置き場に同じ名前が無ければ 404 `not_found`（`details.folders` に歩いた置き場）、フォルダを指せば `searched 1`・`candidates`・`folders` つきで 200。候補の `sha256` は同名の物だけ読む（コード）。
- **元の場所に戻ってきた**（R12b）: 同じ鍵へ `relink` → 200 `moved: false`・履歴は増えない（決めた点 3）。
- **`location_history` の 3 列**: 実データに既に在る（実装者の事故）。`missing_top_ups` は空なので次の起動で `pre-topup-*` は取られない。古い v6（`.backup/pre-p8-2-restart`）を開く道は P8-4 の再確認 R4 で見た形と同じ（`TOP_UP_COLUMNS`）。
- **8790**: P8-6 入り（`GET /api/locations/missing` 200・`total 0`）。実データは `missing_at` 0 なので一覧は空。
- **決めた点 12**: 1（`sha256` だけ）妥当・実測。2（行を付け替える）妥当・`is_primary` は触らない（R6 の行は 1 本のまま）。3（戻ってきたら履歴なし）妥当・R12b。4（`_sync_hidden`）妥当だが試験が無い（F）。5（語彙 422）妥当・R5。6（GET は両方読める）妥当。7（決定的・`also_found`）妥当。8・9（`reason='replaced'`・3 列返す）妥当。10・11 妥当。12（硬化）妥当・実測。
- **設計の穴 6**: 1（列が無い）正しい。2（`nearby` の `path` の意味）正しい・文書化済み。3（同じルート内は空振り）**正しいが C-2 の裏返し**。4（削除も `missing_at`）正しい・`excluded_deleted` で見える。5（`other_live_locations`）正しい。6（自動を作らない）妥当（専門 §4「勝手に繋がない」）。

### C-1 元の場所に戻ってきたファイルを走査が生き返らせない（最も重大の 1）

- 場所: `src/image_reviewer/scan.py:75-78`（`known` の早道）・`store.py:349-353`（`register()` の `missing_at = NULL`。早道では呼ばれない）。設計 `duplicates-deletion-backup.md` §4 の表「走査で見つからない → `missing_at` を立てる」の裏（見つかれば外す）が本文に無い。
- 再現: `relink_check2.py` R12a（複製）。`shutil.move` で `gui-lib` の外へ → 走査 → 参照切れ → `shutil.move` で元のパスへ → 走査（`scan.known` 1）→ `missing_at` が残る。
- 推奨: G-1。

### C-2 `nearby` の省略形は置き場ぜんぶを歩く（最も重大の 2）

- 場所: `relink.py` `_search_nearby`（`folders = [Path(r) for r in roots]`・`iter_images(folder)`）。記録 §4.1-3。
- 判定: 線 9 の「近くを探す」は通る（R14）。範囲が広いのは安全側（見つからないより見つかる）だが、応答時間と「どこを探したか」の見え方の問題。応答に `folders` と `searched` が在るので、画面側で見せられる。
- 推奨: G-2。

### C-3 二重登録の検査が取引の外（最も重大の 3）

- 場所: `relink.py` `relink()`（`_refuse_if_registered` → `_sha256_or_error` → `transaction()`）。
- 判定: 同時の 2 本そのものは作っていないが、**窓の中で起きることは検査を外した写しで実測**（上の 503 `db_error`）。P8-2 の監査 F10（同じ token で 2 本同時）と同じ型の試験で固定できる。
- 推奨: G-3。

## D. 軽微

- **D-1 走査の印は錠を取る前に立つ**（P8-5 の D-4 と同じ。`relink` は錠を取らないので無関係）。
- **D-2 `GET /api/locations/missing` の各項目に `roots` を `is_under` で付けるが、`nearby` の省略形が歩くのは全置き場**（C-2）。応答の `roots` と実際に歩く範囲が違うので、`hint` の文に「置き場ぜんぶを探す」と 1 語。
- **D-3 `exact` の新しいパスは置き場の外でもよい**（`is_under` の検査は無い）。設計は黙っている。段 3 は `root.allow_stage3` で縛るので、置き場の外に繋いだ枚は段 3 ができない（安全側）。1 行書いておく。
- **D-4 `_target_of` は `asset` が無いと 404、参照切れが無いと 409 `not_missing`、`from_path` が合わないと 409 `not_registered`**。`not_registered` は削除の語（§3.4）と同じ `code` で意味が少し違う（「参照切れとして登録されていない」）。`details.missing` に候補が入るので実害は無い。
- **D-5 `tests/test_relink.py` の壊し試験の写しが `apps/gui` を持たないと `test_the_gui_is_served_even_when_the_db_cannot_be_opened` が落ちる**（`GUI_DIR` が `__file__` 起点。私の壊し方の副作用。F）。
- **D-6 記録 §2「`gui_smoke` 291 ok / 3 NG（他の担当の編集中）」は、監査の時点では 310 ok / NG 0**（P8-5 の直しが入ってから数が増えた）。記録の数は作業の途中の物。
- **D-8 `sqlite_error_handler` の守備範囲が広い。** P8-4 で足した handler は `sqlite3.DatabaseError` を全部 503「DB が壊れているので読めません。バックアップから戻してください」に写す。`IntegrityError`（主キー・`CHECK`）や `OperationalError`（`database is locked`）もその子なので、**壊れていない DB の競合や語彙の穴まで「壊れている」と言う**（C-3 の実測）。`DatabaseError` のうち `malformed` / `not a database` だけに絞るか、`IntegrityError` と `OperationalError` を別の 409 / 503 に分ける。
- **D-7 `cli` の `backup` / `scan` / `rebuild-metadata` は env 無しで既定の `.data` を開く**（`_store()` → `data_dir()`）。利用者の道具なので正しいが、硬化は `create_app()` だけで、**エージェントが `uv run image-reviewer scan` を複製に向けずに打てば実データを書く**。README に「複製で試すときは `IMAGE_REVIEWER_DATA` を付ける」の 1 行。

## E. 設計とのずれ（実装が決めた所を含む）

- **E-1 §0.11「同じルート内をファイル名で探す」→ 実装は「置き場ぜんぶ（＋指定フォルダ）」**（穴 3・C-2）。専門 §4 に注記済み。`p8-design.md` §0.11 の本文はまだ「同じルート内」。
- **E-2 §0.11 の 3 つ目「自動（走査のたびに繋ぐ）」は作らない**（穴 6）。専門 §4 に理由つきで注記済み。`p8-design.md` §0.11 と §9 の P8-3 の行はまだ「走査での自動つなぎ」を含む。
- **E-3 §3.2 の口の表は `{asset_id, path, mode}` の 3 つ。実装は `from_path` を足した**（2 か所以上の参照切れ用。妥当。`design.md` §6.1 には載っている）。
- **E-4 `location_history` に 3 列を足した**（穴 1）。版は上げず `TOP_UP_COLUMNS`（P8-4 の `pre-topup-*` の道）。`design.md` §5.1 に載っている。
- **E-5 §1.2 の線 9「走査 → `missing_at` が立つ。近くを探すで見つかり…」**は通る。**「戻ってきたら走査で戻る」は線に無い**（C-1。線 9 の裏返しとして足すべき）。
- **E-6 専門 §4 の表「走査で見つからない → `missing_at`」の裏が本文に無い**（C-1）。

## F. テストで守れないもの

- **壊し試験**（`mut86.py`。`src/image_reviewer` を `mut/<M>/image_reviewer` に写して 1 か所ずつ壊し、`PYTHONPATH` で影にして `pytest tests/test_relink.py tests/test_backup.py tests/test_deletions.py`。影が効いていることは `image_reviewer.__file__` で確認。ソースは触らない）: **15 通り中 13 通りで狙った試験が落ちる**。M1 `sha256` の照合を外す → `test_the_content_is_compared_by_sha256`。M2 `missing_at = NULL` を抜く → `test_exact_relink_connects…`＋1。M3 `_refuse_if_registered` を外す → 二重登録の 3 件（`IntegrityError`）。M4 `reason` を `replaced` に → `test_the_relink_is_recorded_in_location_history`。M5 `require_human` を外す → `test_the_endpoint_is_human_only`。M6 一覧が `missing_at` を書く → `test_the_missing_list_writes_nothing`＋2。M7 `TOP_UP_COLUMNS` の列名を変える → `test_an_old_database_gets_the_history_columns`。M8 `_refuse_if_deleting` を外す → `test_a_deleting_location_cannot_be_relinked`。M10 `from_path` を無視 → `test_two_missing_locations_need_from_path`。M11 `moved` を常に真 → `test_a_file_that_came_back_just_clears_missing_at`。M13 `mode` の語彙を通す → `test_the_body_vocabulary_is_checked`。M14 `sha256` を `size` の一致に替える → `test_the_content_is_compared_by_sha256`（別の絵の大きさが違ったため。同じ大きさの別の絵でも落ちるかは試験が保証していない）。M15 `limit` の真偽値を通す → `test_the_limit_vocabulary_is_checked`。**落ちない 2 つ**: **M9 `_sync_hidden` を呼ばない**（決めた点 4「段 1 で外したままなら戻さない・生きた場所が戻れば一覧に戻る」を見る試験が無い）、**M12 `nearby` の候補の並びを集合のまま**（`test_nearby_is_deterministic_and_reports_the_others` は 2 候補で、集合の順がたまたま同じ）。
- **実装者の 7 通り**（記録 §3）とは M1〜M7 が同じ壊し方。全部落ちる。`create_app()` の env 検査は壊さなかった（実装者の判断と同じ: 壊すと子プロセスが実データを開く）。
- **C-1（戻ってきた枚）を見る試験は無い**（`test_a_file_that_came_back_just_clears_missing_at` は `relink` を打つ形で、走査だけで戻ることは見ていない）。**C-3（同時の 2 本）の試験も無い**。
- `tools/probe_p8.py --relink` の 16 行は私の R1〜R17 とほぼ同じ観点で、`nearby` の省略形（置き場ぜんぶ）と `ambiguous`・`deleted` は probe に無い（私の R13・R15 で見た）。

## G. 依頼者への質問（推奨つき。待たずに推奨で進めてよい）

- **G-1 戻ってきた枚**（C-1）。推奨: `scan.py` の早道（`known` で `size` / `mtime_ns` が同じ）に `if known["missing_at"]: UPDATE asset_location SET missing_at = NULL, last_seen_at = ? WHERE path = ?` を足す。試験「動かして戻して走査 → `missing_at` 0・履歴 0」。線 9 の確かめ方にも「戻せば走査で戻る」を 1 行。
- **G-2 `nearby` の範囲**（C-2）。推奨: 省略形は「その参照切れを含む置き場 → 残りの置き場」の 2 段。`hint` に「探す範囲」を書く。
- **G-3 取引の中で再検査**（C-3）。推奨: `UPDATE` の直前に `SELECT asset_id FROM asset_location WHERE path = ?`。`threading.Barrier` で 2 本同時の試験（P8-2 の F10 の型）。
- **G-4 `_sync_hidden` の試験**（F の M9）。推奨: 段 1 で外した枚を参照切れにして `relink` → `deleted_at` が残る／外していない枚 → 一覧に戻る、の 2 件。
- **G-5 文書**: `p8-design.md` §0.11 の「同じルート内」と「自動」を実装に合わせる（§9 の P8-3 の行も）。

## H. 確かめられなかったこと・注記・後始末

- **事故（私の脚本。実データは無傷）**: 1 回目の `relink_check.py` は、`gui_layout --screen pending` が**本物の走査**（`POST /api/scan`。P8-5 で足した probe）を複製に打ったあとに走り、その走査が**複製の DB に実データの置き場（`illust-authoring`・ComfyUI 出力）を生きた場所として登録し直していた**。私の脚本は `asset_location` の先頭の行（表示パス順＝実データのパス）を選んで `shutil.move` し、**実データの画像 `illust-authoring\.store\anima-dev\images\8b30cdad25def83d.png` を `moved/` へ動かそうとした**。`os.rename` が sandbox に拒まれ、`shutil.move` の後半（`copy2` → `unlink`）で `unlink` が WinError 5 で止まり、**元のファイルは 1 バイトも変わらず**（直後と最後の署名 `fa99ca126c393d5a`・263 枚・292,561,491 B）、`moved/` に写しが 1 つできた（消した）。P8-5 の実装者の申告（WinError 5）と同じ型。以後は **`gui-lib` の下の生きた行だけを選び、動かす直前に `startswith(gui-lib)` を確かめる**（`mine()` / `safe_move()`）形にし、複製の `root` から実データの置き場を消してから取り直した（`run7b.sh`・`run7c.sh`）。**sandbox が無ければ実データの画像が動いていた**＝監査の脚本でも「動かす前に置き場を確かめる」が要る（記録に残す）。
- 1 回目の R12 と R14 の `[NG]`（`run7b.out.txt`）は私の順序の誤り（手で立てた `missing_at` が走査が生き返らせた行にも掛かった・`set_roots` は**足すだけ**で前の置き場を落とさないので `moved` が root に残った）。R12b/R12c/R14 は `relink_check2.py` で取り直した。**R12a はその取り直しで見つかった C-1**。
- 同時の 2 本（C-3）は作っていない（コードの読み）。別ボリュームは無い（実装者の H と同じ）。1 万枚の `nearby` の時間は未計測。
- 壊し試験の写し（`mut/<M>/image_reviewer`）は `apps/gui` を持たないので、`test_the_gui_is_served_even_when_the_db_cannot_be_opened` が毎回 1 件余計に落ちる（D-5。狙った試験と別に数えた）。
- 実行したコマンド（`$env:UV_CACHE_DIR = "C:\work\image-reviwer\.uv-cache"`、`cd C:\work\image-reviwer`）:
  - `uv run --no-sync pytest -q -p no:cacheprovider` ×3・`node tools/gui_smoke.mjs`・`uv run --no-sync python -X utf8 .tmp-audit-redo\p8-4-audit\real_sig.py`（前・事故の直後・後）
  - `bash .tmp-audit-redo/p8-6-audit/run7.sh`（複製 → `gui_layout_seed.py --pending` → 8793 → `gui_layout` 11 本 → `relink_check.py`）・`bash run7b.sh`（複製を作り直し、`root` を `gui-lib` だけにして `relink_check.py`）・`bash run7c.sh`（`relink_check2.py`）
  - `.venv\Scripts\python.exe -X utf8 .tmp-audit-redo\p8-6-audit\mut86.py`（M1〜M15）
  - 硬化: `.venv\Scripts\python.exe -X utf8 -c "import image_reviewer.app as m; m.create_app()"` ほか 3 本を `IMAGE_REVIEWER_DATA` 無しの別プロセスで（`.data` の署名を前後で）
- 一時物: `.tmp-audit-redo/p8-6-audit/`（`relink_check.py relink_check2.py run7.sh run7b.sh run7c.sh mut86.py`、`moved/ moved2/ w-open/ mut/`、出力 `run7*.out.txt layout7.out.txt relink_check*.out.txt mut86*.txt smoke.out.txt pytest*.out.txt real_sig.*.txt`）と `.tmp-audit-redo/p8-4-audit/gui`・`gui-lib`（作り直した複製）。消して構わない。

## 最も重大な 3 件（再掲）

1. **C-1** 元の場所に戻ってきたファイルを走査が生き返らせない（`scan.py` の `known` の早道が `missing_at` を戻さない）。`relink` を同じパスに打てば戻る。
2. **C-2** `nearby` の `path` 省略は登録した置き場ぜんぶを歩く（応答時間と「どこを探したか」）。
3. **C-3** 二重登録の検査が取引の外で、同時の 2 本なら主キーに当たり、P8-4 の handler が 503「DB が壊れているので読めません。バックアップから戻してください」を返す（壊れていないのに復元を勧める。実測）。
