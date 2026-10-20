# P2-1（仮想フォルダ）監査報告 — 実行込み

- 日付: 2026-10-20（10:00〜11:10 ごろ）／監査者: Opus 5.5（Fable の後任）
- 依頼: Orca（dsh・run_5bdd431bf57b）「P2-1（仮想フォルダ）の監査」。開始の知らせ msg_d61d881e47c5
- 対象: **HEAD 259bd4a**（`P2-1: 仮想フォルダ`）。監査の間、作業ツリーは clean のまま・HEAD も動かなかった（最後に `git status` と `git log -1` で確かめた）。
  壊し試験と画面は `git archive 259bd4a` の全体の写し（`.tmp-p2-1-audit/head/`）で回した（前回の教訓: 作業ツリーは別の担当が書き換えうる）
- 記録: `docs/p2-1-implementation.md`（441 行）。設計: `docs/design.md` §5.3・§6.1（722〜735 行）・§10.1〜§10.3・§16.9
- 環境: `uv run --no-sync` 相当（`.venv\Scripts\python.exe`）、`UV_CACHE_DIR=C:\work\image-reviwer\.uv-cache`。
  **親に安全網** `IMAGE_REVIEWER_DATA=.tmp-p2-1-audit\safety-net`（最後に 0 ファイル）。複製は全部**絶対パス**で作り、**パスを複製の中へ貼り替えた**。
  サーバは自分の複製だけを **8793**（HEAD の写し）で立てた。Chrome の CDP は **9344**
- 触っていないもの: **8790（利用者・pid 3636）には GET も打っていない・止めていない**。実データ `.data` は `mode=ro` だけ。`src/`・`tests/`・`apps/` は 1 行も変えていない。git のコミットはしていない

## 判定: **条件つきで使える**

データの安全（R2 の線）・名前の一意（表の索引）・形のガード・C-2 の大半・`GET` の無書き込みは、**実データの複製と合成 DB の両方で成り立った**。
ただし **利用者が 8790 を再起動してフォルダを使い始める前に**、下の B-1〜B-3 を直すこと（どれも小さい）。

### 最も重大な 3 件

1. **（B-1）「論理削除」が分類（`folder_member`）を物理で消す。戻せない。** `folders.py:497` が隠すたびに中身の行を `DELETE` する。
   複製で「B（子 C を持つ）を消す」→ `folder` の行は `deleted_at` 付きで残るが **`folder_member` は 3 → 0**。
   理由として書かれた「同じ名前を作り直すと前の所属が生き返る」は**成り立たない**（作り直したフォルダは新しい ULID なので、古い行は付かない）。
   設計 §6.1 が論理削除を既定にした理由は「**仮想フォルダは再生成できない分類**」で、その分類だけが消えている。
   試験 `test_deleting_a_folder_keeps_its_images`（`tests/test_p2_1.py:203`）は**消えることを固定している**（変異 S1「中身を残す」で落ちる）。
2. **（B-2）本物の Chrome で、「入れました」「画像は消えていません」の 1 行が出ない。** 押すと `location.hash` を変え（`apps/gui/folders.js:428`・`:455`）、
   `hashchange` で走る `showFolders()` が `state.msg = ''`（`:558`）で**同じミリ秒のうちに消す**（観測: `268:1 枚をフォルダ「参考」に入れました。` → `268:`）。
   `gui_smoke` 482 ok と `gui_layout` 56 ok は、偽の DOM／`fetch` の差し替えなのでこれを見ない（small-changes A-1 と同じ型）。
   加えて、**子を持つフォルダを消す確認文が子のことを言わない**（「『2026-10 生成』を消します。…画像は消えません。」→ 実際は子 2 個も消える）。
   画面は `dry_run` を一度も呼ばない（設計 §6.1 の `dry_run` は「子の数・影響」を返すための口）。
3. **（B-3）壊しても落ちない経路が 12 通り（等価 1 通りを除く）。全試験 622 でも生き残る。** 重いもの: **S8「外す」がフォルダの中身を全部外す**・
   **S12 実削除（`purge`）は名前の確認無しで通る**・**S24 `dry_run` が書く**・S11 確認の名前を大小文字を無視して比べる・S9 / S10 並びと改ページ。
   dsh の 12 通りは私の手でも同じ結果（11 落ちる・M4 生き残り）だが、**M1 / M2 / M3 / M5 は「ガードが起動を止めて全試験がエラー」の巻き添え**で、
   M5 は「M4 ＋索引」ではなく索引だけを外している（ラベルと中身が違う）。

---

## A. 直っていない／設計の約束が成り立たない（必ず直す）

なし（データの安全・名前の一意・書き込みの人だけ・`GET` の無書き込みは成り立った。下の D-1〜D-6）。

## B. 重大

### B-1 論理削除が分類を消す（戻せない）

- 場所: `src/image_reviewer/folders.py:497`（`DELETE FROM folder_member WHERE folder_id IN (…)`）、同 `:14` の説明、`docs/p2-1-implementation.md` §1「論理削除の決め」
- 再現（実データの複製 `rc/r2`、`r2_real.log`）: A・B を作り、同じ 1 枚を両方に入れ、B の下に C を作って 2 枚入れる → `DELETE /api/folders/B {confirm:'B'}` →
  `folder` は `[["B",1],["C",1]]`（`deleted_at` 付きで残る）、**`folder_member` は B・C ぶん 0**。画像（`asset`・`asset_location` の全列）は前後で同一。
- なぜ重いか: 利用者が失うのは画像ではなく「どの画像をどこに入れたか」で、これは設計 §6.1 が「再生成できない分類」と呼ぶ物そのもの。
  「戻す」の口（設計の穴 3）を後で作っても、**それまでに消したフォルダの中身は戻せない**。実データはまだ v6（フォルダ 0）なので、**いま直せば失う物は無い**。
- 直し方: 論理削除では `folder_member` を消さない（読む側は既に `folder.deleted_at IS NULL` の木からしか辿らない。`add_members` も `_row` で隠れたフォルダを 404 にする）。
  `purge` のときだけ消える（CASCADE）。試験 `test_deleting_a_folder_keeps_its_images` の「0 行」を「行は残る・木と件数には出ない」に直す。

### B-2 押した後の 1 行が本物の画面に出ない／子も消えることを言わない

- 場所: `apps/gui/folders.js:428`（`deleteFolder` の `location.hash = '#/folders'`）・`:455`（`addTo`）・`:558`（`showFolders` の `state.msg = ''`）・`:126`（`deleteAskText`）
- 再現（`.tmp-p2-1-audit/realclick.mjs`。複製サーバ 8793・本物の Chrome・**`fetch` は飲まずに素通しで数えるだけ**・1024×700 と 1920×1080）:
  - ライブラリで 1 枚を Ctrl+クリック → 「選んだ 1 枚をフォルダに入れる…」→「参考」の「ここに入れる」→ **API で 0 → 1 枚**（入った）。`#fl-msg` は `""`。
    `MutationObserver` の記録: `["268:1 枚をフォルダ「参考」に入れました。","268:"]`
  - 「2026-10 生成」（子 2 個）を選んで「フォルダを消す…」→ 確認文は **子に触れない** → 名前を打ち切ると押せる → 押すと **API で親と子の両方が木から消える**。
    `#fl-msg` は `""`（記録 `["265:フォルダ「2026-10 生成」を消しました。画像は消えていません。","265:"]`）
  - 「外す」（hash を変えない道）は 1 行が残る（`1 枚をこのフォルダから外しました。画像は消していません。`）。
- 直し方: `showFolders` で `state.msg` を消すのは「別の画面から来たとき」だけにする（または hash を変えた側が `showFolders` を経由しない）。
  確認文は `DELETE ?dry_run=true` の `folders` / `names` を読んで「下のフォルダ N 個も一緒に消えます」と言う（設計 §6.1・点検 C11）。
  `gui_layout` の `PRESS_FOLDERS` に「入れた／消した後に `#fl-msg` が残る」を足す（`fetch` を飲む検査では hash が変わらないので、**素通しで押す 1 本**が要る）。

### B-3 壊しても落ちない経路（12 通り）

`.tmp-p2-1-audit/mut.py`（HEAD の写しの `src` を丸ごと写し、1 か所だけ変えて `PYTHONPATH` の先頭へ。**写しを読んだことを毎回確かめた**）。
P2-1 に関わる 4 ファイル（141 件）で 42 通り → 生き残った 13 通り（うち等価 1）を**全試験（622 件）**でも回して、やはり全部生き残った（素の写しの基準と同じ 5 件だけ落ちる。変異の写しは `src` を repo の外へ置くので、場所に依る落ちが 5 件になる。素の `git archive` の写しでは 2 件＝D-12）。
表は F に。重いものだけ:

| 変異 | 何が起きるか | なぜ落ちないか |
| --- | --- | --- |
| S8 「外す」で `asset_ids` を見ずにフォルダの中身を全部消す | **1 枚外すつもりで全部外れる** | `test_removing_from_a_folder_…`（`:168`）はフォルダに 1 枚しか入れていない |
| S12 `purge:true` なら確認の名前を見ない | **実削除が無確認で通る** | `test_purge_…`（`:412`）は正しい名前しか送らない |
| S24 `dry_run` の道で 1 行書く | 「何も消さない」が書く | `dry_run` の前後で行もファイルも比べていない（`GET` の試験は `DELETE ?dry_run` を含まない） |
| S11 確認の名前を大小文字を無視して比べる | `abc` で `ABC` が消える | 違う名前の例が `b`／欠落だけ（`Cat`/`cat` は別のフォルダになれるので区別が要る） |
| S9 `sort=added` を古い順に／S10 `next_cursor` を 1 つ先まで | 並びと改ページが壊れる | `test_the_folder_assets_list_sorts_and_pages`（`:497`）が並びの向きと最後のページを見ていない |

---

## C. 中程度

### C-1 `gui_layout` は「フォルダ 0 個」で NG になる（利用者の再起動直後の状態）

- 場所: `tools/gui_layout.mjs:1042`（空の案内を `#fl-items` で探すが、木が空のとき案内は `#fl-tree` に出る）・`:2113`（ライブラリの入口の検査が `rows > 0` を要求）・`:2161`（案内が `manage_folders.py` を名指しするが、repo に無い）
- 再現: 実データの複製を `gui_layout_seed.py`（dsh と同じ旗）で整え、フォルダ 0 のまま `--screen folders` と `--screen library` → **両方 4 幅とも NG**（`← 空の案内`・`← フォルダの画面に木が出る`）。
  フォルダを API で 5 個作ってから回すと 12 本 × 4 幅で **56 ok / NG 0**。
- 画面そのものは正しい（本物の Chrome で 0 個のとき `#fl-tree` に「フォルダがまだありません。上の入力に名前を入れて「作る」を押すと、ここに並びます。」が出る）。**道具の誤り**。
  dsh の 48 ok は手で入れた 4 個（id `root1` など）の複製でしか通らず、その作り方が repo に無い（再現できない）。
- 直し方: 空の案内は `#fl-tree .fl-note` で読む・ライブラリの入口は「0 個なら空の案内が出る」でも通す・前提のフォルダを作る道具を `tools/` に置く（`gui_layout_seed.py --folders`）。

### C-2 名前の取り合いは塞がったが、「形は正しいが中身が重複」の DB は起動で落ちる

- 再現（`.tmp-p2-1-audit/gate.py`。実データの複製に前提の SQL を足して `create_app`）:

| 複製に置いた物 | 結果 | `db.sqlite3` の sha256 | 控え |
| --- | --- | --- | --- |
| 何も（v6） | `ok`・版 7・`ux_folder_name` あり。2 回目の起動で控えは増えない | （上がる） | `pre-migrate` 1 個 |
| `ix_folder_parent ON asset(...)` | **`read_only` / `schema_conflict`**・版 6 | **同じ**（空の `-wal` が出来るだけ） | 0 |
| `ux_folder_name` を別の表に | 同上 | 同じ | 0 |
| `deleted_at` の無い `folder` | 同上 | 同じ | 0 |
| 正しい表＋`ux_folder_name ON folder(parent_id,name)` | 同上 | 同じ | 0 |
| `asset.source` が `CHECK` 無しで在る | 同上 | 同じ | 0 |
| **正しい形の `folder` に根の同名 2 行** | **`create_app` が `IntegrityError` で落ちる**・版 6 のまま **`asset.source` 等 3 列だけ足された** | 変わる | **起動ごとに 1 個増える** |
| P2-0 の頃の v7（索引なし）＋根の同名 2 行 | 起動が `IntegrityError` で落ちる（早期 return の `_top_up_v7`） | 変わらない | 0 |

- 最後の 2 行は、P2-0 の C-2 で残る「半端な v6」か、P2-0 の頃の v7 にしか起きない（P2-0 には作る口が無いので、利用者の手では作れない）。**実データと控え 12 個には `folder` が無いので起きない**。
- 直し方: `v7_conflicts` に「根・同じ親の同名が既に在る」を足す（`SELECT … GROUP BY coalesce(parent_id,''), name HAVING count(*) > 1`。読むだけ）。

### C-3 `schema_conflict` のとき、何が取り合っているかが人に見えない／`GET /api/folders` が 500

- `inspect_db` は `conflicts` を集めるが、`GET /api/health/db`（`src/image_reviewer/api/backup.py:58〜`）も起動のログ（`app.py:97`）も**それを出さない**。
  案内は「その名前の物を退けてから」と言うのに、**どの名前かが分からない**（実測: `health.conflicts` は `null`）。
- 同じ状態で `GET /api/folders` は **500**（`folder` が無い・列が違う）。書き込みは 503 `read_only` で止まる。読み取りの口も 503 か 200 の空に。

### C-4 `purge` の真偽を文字列で受ける

- `src/image_reviewer/api/folders.py:72` `purge=bool(body.get("purge"))`。**`{"confirm":"E","purge":"false"}` で実削除になった**（`r2_real.log` の `purge:'false' string` → `"purged": true`）。
  画面は真偽値を送るので画面からは起きないが、エージェント以外の道具や手打ちの `curl` で起きる。`purge is True` だけを実削除にし、他の型は 422。

### C-5 見た目が同じ名前を同じ親に 2 つ作れる

- 合成と複製の両方で、同じ親に次の組が**両方 200**: `ガ`（NFC）と `ガ`（NFD）・`Z` と `Z\u200b`（幅 0 の空白）・`D` と `D\x7f`（DEL）・`L\u2028x`（行区切り）。
  `_clean_name`（`folders.py:85`・`:92`）は `strip()` と `ord < 32` だけを見る。全角空白・NBSP は `strip()` で落ちる（確かめた）。
- 大文字小文字（`Cat` と `cat`）・全角英字（`ＡＢＣ`）も別の名前（**決めごと**。G-3）。
- 直し方: `unicodedata.normalize('NFC', …)` と、カテゴリ `Cc` / `Cf` / `Zl` / `Zp` を拒む（表の索引は触らずに済む）。

---

## D. 軽微（「確かめた結果、問題なし」は 1 行）

- **D-1 R2 の線（実データの複製で HTTP の道）: 問題なし。** 1 枚を A・B に入れて両方の中身に出る・`folder_member` 2 行／A から外すと A 0・B 1・`/api/assets` に残る／
  B（子 C つき）を消す・実削除（`purge`）の全部の後で **`asset` と `asset_location` の全列が前後で同一**（sha の一致）／複製の中へ写した実ファイル 3 枚の
  **size・mtime_ns・sha256 が同一**。最後に版 7・`foreign_key_check` 0・`quick_check ok`・`asset.source` は 463 行とも `scan`。
- **D-2 `ux_folder_name` は一意（抜け道なし）。** 表に直に書いても: 根どうし・同じ親は `UNIQUE constraint failed: index 'ux_folder_name'`、別の親は通る、
  論理削除した後の同名は通る（3 つ目の論理削除も通る）、`parent_id=''`（空文字）は根と衝突して拒まれる、`1`（整数）と `'1'` は拒まれる。
  **論理削除を戻すとき、同名の生きたフォルダが在ると `IntegrityError`**（将来の「戻す」の口は 422 に写す必要がある＝設計の穴 3 への申し送り）。
  `BLOB` の名前は文字列と別扱い（表に直に書く道だけ。口は文字列しか受けない）。
- **D-3 ガードは式索引を形で見ている。** v7 の DB の `ux_folder_name` を 9 通りに差し替えて `_check_v7_shape`: `ON folder(parent_id,name)`・部分条件なし・UNIQUE なし・
  `COLLATE NOCASE`・`ifnull`・列の順の入れ替え・別の表・`WHERE NULL IS deleted_at` は**全部拒む**、空白と大文字だけ違う正しい文は通る。
  （`ifnull` と `NULL IS deleted_at` は意味が同じなので**誤検知**だが、安全側。）変異 Y1（文の比較を外す）・Y3（式索引の検査を全部外す）は試験で落ちる。
  Y2（`cid < 0` の検査を外す）は落ちない＝**等価**（文の比較が同じ物を先に見る）。
- **D-4 循環・403・422: 問題なし。** 自分・子・孫を親に → 422 `folder_cycle`。無い親 → 422 `parent_missing`。エージェントで書く 5 口と `DELETE ?dry_run` → 403 `human_only`、ヘッダ無し → 403、
  `robot` → 422。片付け済み・知らない画像 → 422 `asset_missing`、**生きた 1 枚と混ぜても 1 枚も入らない**（全か無か）。`sort=x`・`cursor=abc` → 422。`limit=-5` は 1 に丸めて 200。
- **D-5 `GET` は 1 バイトも書かない（ファイルも全表も）: 問題なし。** 複製で `GET /api/folders`・中身 3 通り・無い id・隠れたフォルダ・`health/db`・`/api/assets` を人とエージェントで 2 回ずつ →
  `<data>` 全ファイル（`-wal` 含む・`-shm` 除く）の size/mtime/sha と全表の中身が同一。`test_p2_1.py` と `test_p2_0.py` を 15 回続けて回して **15/15 緑**（揺れなし。P2-0 の C-1 の `-shm` は直っている）。
- **D-6 実データ: v6 のまま無傷。** 前後で `user_version 6`・`quick_check ok`・表 23 の行数と中身の hash・`sqlite_master` の hash・`db.sqlite3` の sha256 `caf7c642e1cb12b2…`・
  `.data` の 5 ファイルの size と mtime（`-wal` を含む）・ルートの画像 424 個の size/mtime・`.backup` 12 個が**すべて同じ**。`folder` 表 0・`asset.source` 列なし。
- **D-7 移動で 32 段を越えられる。** 31 段目の下へ 3 段の枝を移すと 34 段（`folders.py:416` は親の深さしか見ない）。作る口は 33 段目を 422 にする。数字は自分で決めた上限なので軽微。変異 S17 / S18 は試験で落ちない。
- **D-8 見出しの「画像 N 枚」が重複を数える。** 同じ 1 枚を 2 つのフォルダに入れると「フォルダ 5 個、画像 4 枚」（実際は 3 枚。`folders.js:37` の `briefText` が各フォルダの件数を足す）。
  多対多の画面で「画像 N 枚」と言うなら異なる枚数を、足すなら「入れた数 N」に。
- **D-9 数の書き方。** 記録の「gui_layout 12 本 × 4 幅 = 48 ok」は、比較の 12 行（3 窓 × 4）を入れると **56**（私の実測 56 ok）。dsh の M5 は記録では「M4 ＋索引も外す」だが、
  スクリプトは索引だけを外す（M1 と同じ）。M7 を落とすのは記録の「R2 の線 3」ではなく `test_the_files_do_not_move_when_folders_change`。
- **D-10 P2-0 の頃の v7 には控え無しで索引を足す。** 早期 return の `_top_up_v7` は版を上げないので `pre-migrate` を取らない（合成の `v7_p20_clean` で sha が変わり、控え 0）。
  `_top_up_v5` / `_top_up_v6` と同じ流儀で、索引 1 本なので軽微。実データ（v6）は `_migrate_v7` の道で控えを取ってから上がる（実測）。
- **D-11 性能の主張は再現した。** 合成（画像 1 万・フォルダ 1,000・所属 1 万）で `folders.tree()` 中央値 **6.26 ms**（記録 6.46）、中身 200 枚 0.09 ms。
  1 万枚のフォルダで `sort=name` の `OFFSET 9800` は 13.6 ms（`asset_location` を入れていないので下限の目安）。
- **D-12 pytest。** 作業ツリー **622 passed を 2 回**。HEAD の写しは 615 passed・5 skipped・2 failed（`test_pytest_does_not_use_a_data_dir_it_inherited` は親の安全網の env を見て落ちる＝意図どおり、
  `test_the_selftest_refuses_when_any_of_the_four_ports_is_taken` は写しの場所に依る。P2-0 の監査と同じ 2 件）。`gui_smoke` は写しと作業ツリーで **482 ok / NG 0**。

## E. 設計とのずれ（設計が黙っているのに実装が決めた所も）

| # | ずれ | 判定 |
| --- | --- | --- |
| E-1 | 論理削除で `folder_member` を消す（B-1） | **変更を勧める** |
| E-2 | 設計 §6.1 の `GET /api/assets ?folder=` を作っていない。**知らないクエリは黙って無視される**ので、`?folder=X` は**全部の画像**を返す（`app.py:345` の `list_assets` に `folder` が無い）。中身は `GET /api/folders/{id}/assets` で取れる | **条件付き**: 作るか、§6.1 から外して `?folder=` を 422 に |
| E-3 | 設計 §6.1 の `dry_run` は「影響を返す」口だが、画面は使わない（B-2） | 変更を勧める |
| E-4 | 改ページが `OFFSET`（設計 §10.3 はキーセット）。記録の穴 1 | 持ち越してよい（1 万枚で 13.6 ms） |
| E-5 | `smart_query` の検証だけ・条件の計算なし・中身に注記 | 妥当（黙って空にしない。画面の文も確かめた） |
| E-6 | 名前の上限 120・32 段・1 回 1,000 枚 | 妥当（D-7 の移動だけ穴） |
| E-7 | 件数は毎回数える（`count_cache` を使わない） | 妥当（D-11 で再現） |
| E-8 | `store._asset_dict` の `source` を `asset.source` へ（P2-0 の申し送り） | 妥当（変異 P1〜P3 も落ちる） |

**記録の「設計の穴 5 件」への判定:**

1. キーセットと食い違う改ページ → **持ち越してよい**（E-4）。P2-2 で設計か実装のどちらかに揃える。
2. `smart_query` の対応表 → **持ち越してよい**。ただし `source`（`asset.source` か `asset_meta.source` か）と `meta.*`（`meta_json` の中）を、条件を計算する段の**前に**設計へ。
3. 「戻す」の口が無い → **今直す（データの側だけ）**。口は持ち越してよいが、B-1 のとおり所属を残しておかないと、後で作っても戻せない。戻すときの同名衝突（D-2）は 422 に。
4. 中身の並べ替えの口が無い → 持ち越してよい。
5. `asset_meta.source` の意味 → **今直す（1 行）**。§5.1 / §5.2 に「`asset.source` = 取り込みの経路、`asset_meta.source` = 来歴を取った経路」と書く。

## F. テストで守れないもの

自前 42 通り（`.tmp-p2-1-audit/mut.py`）＋ dsh の 12 通り（`mut_dsh.py`。dsh の置き換えをそのまま HEAD の写しへ）。「落ちた」は素の写しの基準（1 件。写しの場所に依る `test_the_gui_is_served_even_when_the_db_cannot_be_opened`）を除いて数えた。

| 変異 | 判定 | 根拠と直し方 |
| --- | --- | --- |
| Y1 ガードの文の比較を外す | 落ちた | `test_the_guard_refuses_a_missing_or_wrong_unique_index` |
| Y2 `cid < 0` の検査を外す | **生き残り（等価）** | 文の比較が同じ物を先に見る |
| Y3 式索引の検査を全部外す | 落ちた | 同上 |
| Y4 索引と期待値の両方を `(parent_id,name)` に | 落ちた（93 failed・40 errors） | 大半は巻き添え（`cid` の検査がガードを止める）。リテラルの試験も落ちる |
| Y5 索引と期待値の両方から部分条件を外す | 落ちた（3 件） | `test_deleted_folders_…`（名前を作り直せない）・リテラルの 2 件。**期待値が実装から来ていない**ことの確認になった |
| Y6 早期 return の `_top_up_v7` を外す | **生き残り（穴）** | P2-0 の頃の v7 を開く試験が無い。合成で「版 7・索引なし」を起動して索引ができるかを見る |
| Y7 `inspect_db` が `v7_conflicts` を呼ばない | 落ちた | C-2 の 2 件 |
| Y8 索引の取り合いを見ない | 落ちた | `test_a_taken_index_name_…` |
| S1 論理削除で中身を残す | 落ちた | **試験が「消す」を固定している**（B-1。直すなら試験も） |
| S2 論理削除で子を隠さない | 落ちた | |
| S3 循環を子だけ見る／S4 自分だけ見る | 落ちた | |
| S5 木の件数に片付け済みを数える／S6 中身の総数に数える | 落ちた | |
| S7 片付け済みを入れられる | 落ちた | |
| **S8 「外す」が中身を全部外す** | **生き残り（穴）** | 2 枚入れて 1 枚外し、もう 1 枚が残るかを見る |
| **S9 `sort=added` を古い順に** | **生き残り（穴）** | 時刻の違う 2 枚で順を見る |
| **S10 `next_cursor` を 1 つ先まで出す** | **生き残り（穴）** | 最後のページで `next_cursor is None` を見る |
| **S11 確認の名前を大小文字無視** | **生き残り（穴）** | `ABC` を `abc` で消せないことを見る |
| **S12 `purge` なら確認を飛ばす** | **生き残り（穴）** | `purge:true` で名前無し・違う名前が 422 を見る |
| S13 名前を `strip` しない | 落ちた | |
| S14 制御文字の検査を外す | **生き残り（穴）** | 改行入りの名前が 422 を見る（C-5 の文字種も足す） |
| S15 名前の上限を外す | 落ちた | |
| S16 隠れた親の下に作れる | 落ちた | |
| S17 移動の深さを見ない／S18 作るときの深さを見ない | **生き残り（穴）** | 33 段目が 422 を見る（D-7 の移動も） |
| S19 条件の `field` を見ない | 落ちた | |
| S20 `manual` に戻しても条件を残す | **生き残り（穴）** | `PATCH {kind:'manual'}` の後 `smart_query is None` |
| S21 負の `position` を通す | 落ちた | |
| S22 スマートの注記を出さない | 落ちた | |
| S23 隠れたフォルダの中身を返す | 落ちた | |
| **S24 `dry_run` の道で書く** | **生き残り（穴）** | `dry_run` の前後でファイルと全表を比べる（`GET` の試験と同じ物差し） |
| S25 一意を親を無視して見る | 落ちた | |
| S26 `limit` を丸めない | **生き残り（穴）** | `limit=5000` で 1,000 件に丸まるかを見る |
| A1〜A4 書く 4 口から `require_human` を外す | 落ちた | |
| A5 `dry_run` を無視する | 落ちた | |
| P1 `register` が `source` を捨てる／P2 `ref_tags` を常に空に／P3 `source_url` を常に `None` に | 落ちた | |
| dsh M1〜M3・M5 | 落ちた（3 failed＋21〜44 errors） | **巻き添え**: ガードが `create_app` を止め、フィクスチャで全部エラー。数え方は「ガードが落ちる」1 件と見るべき |
| dsh M4 | 生き残り（等価） | dsh の判定どおり。索引が同じ 422 にする |
| dsh M6〜M12 | 落ちた（各 1 件） | M7 を落とすのは `test_the_files_do_not_move_when_folders_change`（D-9） |

**画面の検査が見ないもの:** `gui_smoke`（偽の DOM）と `gui_layout`（`fetch` を飲む）は、hash を変えた後に `showFolders` が 1 行を消すことを見ない（B-2）。
`gui_layout` の空の状態の検査は場所を間違えていて、0 個では NG になる（C-1）。

## G. 依頼者への質問（待たずに推奨どおりで進めてよい）

| 論点 | 選択肢 | 推奨 |
| --- | --- | --- |
| G-1 論理削除で所属を残すか（B-1） | (a) 残す（`purge` のときだけ消える） (b) 今のまま消す | **(a)**。実データはフォルダ 0 なので、**利用者の再起動の前でも後でも**直せる（表の形は変わらない）。ただし**使い始める前**に |
| G-2 子を持つフォルダの削除の確認 | (a) `dry_run` を読んで「下のフォルダ N 個も消えます」と言う (b) 子を持つフォルダは消せない（先に子を消させる） | **(a)**。設計 §6.1 の `dry_run` の目的どおり |
| G-3 名前の同一視 | (a) NFC にそろえ、見えない文字を拒む・大小文字は区別する (b) 大小文字も同一視（`lower()` の式索引） (c) 今のまま | **(a)**。索引は変えずに済む。大小文字の区別は Windows のフォルダと違うが、仮想フォルダなので区別してよい |
| G-4 `GET /api/assets?folder=` | (a) 作る（`folder_member` で絞る） (b) 設計から外し、知らない `folder` を 422 | **(a)** を P2-2 で。それまでは (b) の 422 だけ先に（黙って全件を返さない） |
| G-5 C-2 の「中身が重複」 | (a) `v7_conflicts` に同名の検査を足す (b) 起こり得ないとして記録だけ | **(a)**（読むだけの 1 文。起動で落ちて控えが増え続ける形を残さない） |

## H. 確かめられなかったこと・注記・後始末

- **確かめていない**: 8790（利用者）での画面（触らない約束）。実データが v7 に上がった後の挙動は、**実データの複製**を `create_app` に通した結果（版 7・`pre-migrate` 1 個・
  2 回目の起動で増えない・`ux_folder_name` あり）で代えた。同時に 2 プロセスで同名を作る競合は、サービスの検査を外して索引に当てる形で確かめた（422 `folder_name_taken`。500 にならない）。
- **注記**:
  - 複製の `delete_request.result_json` と `pending_delete_preview` の JSON に、実データのパスが**文字列の中**に残っていた（`\\` で書かれた物。私の貼り替えは素の文字列だけ）。
    これらは閉じた台帳で、起動もフォルダの口も読まない。最後の実データの署名（D-6）で、実ファイルが 1 つも変わっていないことを確かめた。
  - `gate.py` の「db bytes same: False」は、読み取り専用で開いたときに**空の `-wal`**（sha `e3b0c442…`）ができたことだけで、`db.sqlite3` の sha は同じ（表 C-2 はそれを書いた）。
  - `r2_real.log` の `"bad sort / cursor / limit"` の 3 つ目は `limit=-5` が 1 に丸められて 200（誤りではない）。
- **後始末**: 自分のサーバ（8793）は毎回 `/api/health` の `data_dir` が `.tmp-p2-1-audit\gl\` で pid が一致することを確かめてから止めた（最後 pid 36316）。8790 は pid 3636 のまま。
  8791〜8799・9344 は空き。**実データの写し（`rc/` の 9 個・`gl/`・`idx/` の合成・変異の写し `mut/`・`mutd/`・`tmp/`）は全部消した。**
  残した物（`.tmp-p2-1-audit/`。gitignore 済み）: スクリプト（`sig.py`・`idx_probe.py`・`depth.py`・`rc_make.py`・`r2_real.py`・`r2_child.py`・`gate.py`・`mk_replica.py`・`pick.py`・
  `gl.ps1`（BOM）・`realclick.mjs`・`mut.py`・`mut_dsh.py`・`perf.py`・`pt.sh`）とログ、`head/`（259bd4a の `git archive`。コードだけ）、`sig-before.json` / `sig-after.json`（パスと数の一覧。画像は無い）。
- **実行したコマンドと結果（要約）**:

```text
python sig.py sig-before.json / sig-after.json      → 同一（D-6）
python idx_probe.py                                 → D-2・D-3・C-5（合成）
python depth.py                                     → 34 段（D-7）
python r2_real.py                                   → R2 の線・一意・循環・403/422・GET 無書き込み（D-1・D-4・D-5・C-4）
python gate.py <ok|sq_idx|sq_ux_other|sq_folder_nodel|sq_ux_plain|sq_dupes|sq_source_nocheck|v7_p20_clean|v7_p20_dupes> 2   → C-2・C-3・D-10
powershell -ExecutionPolicy Bypass -File gl.ps1 -Phase empty        → folders / library が 0 個で NG（C-1）
powershell … gl.ps1 -Phase seedfolders ; -Phase all                 → 12 本 × 4 幅 56 ok / NG 0
powershell … gl.ps1 -Phase realclick ; -Phase realclick-1920        → 各 3 NG（B-2）
python mut.py ; python mut.py <基準＋生き残り 13> --full ; python mut_dsh.py  → F
pytest -q（作業ツリー 2 回）                         → 622 passed ×2
pytest -q（HEAD の写し）                             → 615 passed・5 skipped・2 failed（環境）
pytest tests/test_p2_1.py tests/test_p2_0.py ×15     → 42 passed ×15
node tools/gui_smoke.mjs（写し・作業ツリー）          → 482 ok / NG 0
python perf.py                                      → tree 6.26 ms（D-11）
```

### 最も重大な 3 件（再掲）

1. **B-1** 論理削除が `folder_member` を物理で消す（分類が戻せない。理由の「生き返る」は成り立たない。試験が消すことを固定）。
2. **B-2** 本物の Chrome で、入れた／消した後の 1 行が同じミリ秒で消える（`showFolders` の `state.msg = ''`）。子を持つフォルダの確認文が子のことを言わない（`dry_run` を使わない）。
3. **B-3** 壊しても落ちない 12 通り（S8「外す」が全部外す・S12 `purge` が無確認・S24 `dry_run` が書く・S11・S9/S10 ほか）。dsh の 12 通りのうち 4 通りはガードの巻き添えで落ちている。
