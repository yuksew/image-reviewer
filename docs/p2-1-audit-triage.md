# P2-1（仮想フォルダ）監査の指摘の仕分け（2026-10-20）

- 監査: [`p2-1-audit-report.md`](p2-1-audit-report.md)（判定: **条件つきで使える**。A は無し・条件は **B-1〜B-3**）
- 実装の記録: [`p2-1-implementation.md`](p2-1-implementation.md)（**この仕分けが §1「論理削除の決め」を上書きする**）
- 設計への反映: `design.md` **§5.3**・**§6.1**・**§16.9**（「P2-1 の監査で確定したこと」）・`frontend-design.md` §11（フォルダ: 消す）
- 方針: **推奨はすべて採用**。**いま直す物**と**P2-2 へ送る物**を 1 行ずつ分けた。**変異の一覧（F）は 12 通り全部**を
  自分の手で作って落とした（§5）。**実データは `mode=ro` のまま・v6 のまま・画像は 0 枚も動かしていない**（§8）。
- 環境: `$env:UV_CACHE_DIR`、`uv run` は `--no-sync`、**`IMAGE_REVIEWER_DATA` を付けずにサーバ・アプリを起動しない**
  （親に安全網 `IMAGE_REVIEWER_DATA=.tmp-p2-1-fix\safety-net`）。複製は `sqlite3.backup()`＋`copy2`＋パス貼り替え
  （`tools/probe_deletions_advance.make_replica`）。サーバは複製だけを **8793**、Chrome の CDP は **9344**。
  **8790（利用者・pid 3636）は止めていない・GET も打っていない**。`git` のコミットはしていない。

---

## 1. B（重大）— 3 件とも直した

| # | 指摘 | どうした | 根拠（ファイル・試験） |
| --- | --- | --- | --- |
| **B-1** | **論理削除が `folder_member` を物理で消す**（`folders.py:497`）。戻しても中身が無い＝**分類が永久に消える** | **`DELETE FROM folder_member` を削除**（消えるのは `purge:true` の CASCADE のときだけ）。**読む 3 か所**（`tree()` の件数・`assets()` の行と `total`・`_count_of()`）に `JOIN folder f ON f.id = m.folder_id AND f.deleted_at IS NULL` を足し、**隠したフォルダの行はどこにも出さない**（`_row()` の 404 と二重）。行が残るので**戻せば見える**ことを DB を直接戻して確かめた | `src/image_reviewer/folders.py`（`delete()`・`tree()`・`assets()`・`_count_of()`）、`tests/test_p2_1.py` の **3 本**（`test_deleting_a_folder_keeps_its_images`・`test_a_soft_deleted_folder_comes_back_with_its_members`・`test_only_purge_removes_the_membership_rows`） |
| **B-2** | **押した後の 1 行が本物の Chrome で出ない**（`location.hash` → `hashchange` → `showFolders` の `state.msg=''` が同じミリ秒で消す） | `showFolders` が 1 行を消すのは**別の画面から来たときだけ**（`state.shown`。`hideFolders()` で false）。本物の Chrome で**すぐと 2 秒後**の両方、`MutationObserver` の記録（空文字の記録が無い）まで見た | `apps/gui/folders.js`、`.tmp-p2-1-fix/realclick.mjs`（**25 ok / NG 0**・1024×700 と 1920×1080） |
| **B-2** | **子を持つフォルダの確認文が子のことを言わない**（実測で子 2 個が一緒に消えた）。画面は `dry_run` を呼ばない | 確認の前に **`DELETE ?dry_run=true`** を読み、**「下のフォルダ 2 個（気に入った、背景の参考）も一緒に消えます。」**と言う（`folders` と `names` から。画面で数え直さない）。**`dry_run` が読めないときは確認を出さない**（子のことを言えない確認文を出さない）。文の正を `frontend-design.md` §11 に先に書いた | `apps/gui/folders.js`（`startDelete`・`deleteAskText`・`childFolders`・`namesNote`）、`docs/frontend-design.md` §11、`tools/gui_smoke.mjs`（6 検査） |
| **B-3** | **壊しても落ちない経路が 12 通り**（S8・S9・S10・S11・S12・S14・S17・S18・S20・S24・S26・Y6） | **1 通りにつき 1 本以上の試験**を足した（**期待値はリテラル**。31 段・1000・2 個・`None` など）。**自分で変異を作り 12/12 落ちる**ことを実測（§5） | `tests/test_p2_1.py`（12 本）、`.tmp-p2-1-fix/mut.py` |

**B-1 の前のコードを戻すと 3 本落ちる**（変異 `B1-old`。§5）。**利用者がフォルダを使い始める前に当てる**——
実データは v6・フォルダ 0 なので、この修正で失う物は無い。

## 2. C（中程度）

| # | 指摘 | どうした |
| --- | --- | --- |
| C-1 | `gui_layout` が「フォルダ 0 個」で NG（空の案内を `#fl-items` で探す・ライブラリの入口が `rows > 0` を要求・無い道具を名指し） | **送る（P2-2 か道具の手当て）**。**道具の誤り**で、画面は正しい（本物の Chrome で 0 個の `#fl-tree` に案内が出るのを確かめた）。**いまはフォルダを作った複製で 12 本 × 4 幅 56 ok**（§8） |
| C-2 | 「形は正しいが中身が重複」の DB は起動で落ちる（控えが増え続ける） | **送る**（`v7_conflicts` に「根・同じ親の同名が既に在る」を足す。読むだけの 1 文。**実データと控え 12 個には `folder` が無いので起きない**） |
| C-3 | `schema_conflict` のとき**何が取り合っているか人に見えない**・`GET /api/folders` が 500 | **送る**（`health` と起動のログに `conflicts` を出し、読みの口を 503 か空に）。**起きるのは「表を先に置かれた DB」だけ**で、P2-1 の修正では触らない |
| C-4 | `purge=bool(body.get("purge"))` で **`"false"` が実削除**になる（データが消える） | **直した。** `purge` は**真偽値だけ**を受け、他の型は 422。試験は `{"confirm": …, "purge": "false"}` が 422 で**消えない**ことを見る（変異 `C4-old` で落ちる） |
| C-5 | 見た目が同じ名前を同じ親に 2 つ作れる（NFD・幅 0・DEL・行区切り） | **直した。** 名前を **NFC** にそろえ、`Cc` / `Cf` / `Zl` / `Zp` は **422**。**大小文字は区別**（決めごと）。§5.3 に書いた（変異 `C5-old` で落ちる） |

## 3. D（軽微。「確かめた結果、問題なし」は 1 行）

| # | 指摘 | どうした |
| --- | --- | --- |
| D-1 | R2 の線（複製で HTTP の道）は問題なし | **確認だけ**（こちらの修正後の複製でも `folder_member` が残り、`asset` / `asset_location` と実ファイルの署名は変わらない） |
| D-2 | `ux_folder_name` は一意。**論理削除を戻すとき同名が在ると `IntegrityError`** | **記録だけ**（戻す口はまだ無い。**作るときは 422 に写す**。§16.9 の末尾に書いた） |
| D-3 | ガードは式索引を形で見ている（Y2 は等価） | **そのまま**（等価変異なので落とさない） |
| D-4 | 循環・403・422 は問題なし | **確認だけ** |
| D-5 | `GET` は 1 バイトも書かない | **確認だけ**（`dry_run` も**書かない**ことを B-3 の S24 で固定した） |
| D-6 | 実データは v6 のまま無傷 | **確認だけ**（修正の前後で署名が同じ。§8） |
| D-7 | 移動で 32 段を越えられる（親の深さしか見ない） | **直した。** `_depth_of(親) + _height_of(枝) > 32` で 422（1 枚の移動は前と同じ判定）。試験 1 本（変異 `D7-old` で落ちる） |
| D-8 | 見出しの「画像 N 枚」が重複を数える | **送る**（異なる枚数にするか「入れた数 N」に。P2-2） |
| D-9 | 数の書き方（56 は比較の 12 行を含む・dsh の M5 のラベル） | **記録に反映**（README の `gui_layout` を **56 ok** に直した） |
| D-10 | P2-0 の頃の v7 には控え無しで索引を足す | **送る**（`pre-topup` を取るかは v8 の話。**Y6 の試験は足した**） |
| D-11 | 性能の主張は再現した | **そのまま**（`count_cache` を使わない判断は変えない） |
| D-12 | pytest（作業ツリー 622・HEAD の写し 615） | **確認だけ**（修正後は **638 passed**。§8） |

## 4. E（設計とのずれ）

| # | 指摘 | どうした |
| --- | --- | --- |
| E-1 | 論理削除で `folder_member` を消す（B-1） | **直した**（§1） |
| E-2 | `GET /api/assets?folder=` が無く、**黙って全件を返す** | **直した（422 だけ先に）**。P2-2 で実装するまで `folder_filter_not_implemented` で断る（§6.1 に書いた） |
| E-3 | `dry_run` を画面が使わない（B-2） | **直した**（§1） |
| E-4 | 改ページが `OFFSET`（設計はキーセット） | **送る**（記録の穴 1。1 万枚で 13.6 ms） |
| E-5 | `smart_query` の検証だけ | **そのまま**（妥当。対応表は P2-2 で設計へ先に） |
| E-6 | 名前の上限 120・32 段・1 回 1,000 枚 | **そのまま**（D-7 の移動だけ直した） |
| E-7 | 件数は毎回数える | **そのまま**（妥当。D-11 で再現） |
| E-8 | `store._asset_dict` の `source` を `asset.source` へ | **そのまま**（妥当） |

**記録の「設計の穴 5 件」への判定**（監査の判定どおり）: 1（キーセット）＝**送る**・2（`smart_query` の対応表）＝
**送る（P2-2 で条件の計算の前に）**・3（**「戻す」の口が無い**）＝**データの側だけ今直した**（B-1。口は P2-2）・
4（中身の並べ替えの口）＝**送る**・5（`asset_meta.source` の意味）＝**送る（§5.1 / §5.2 の 1 行）**。

## 5. F（テストで守れないもの）— 12 通りを全部落とした

`.tmp-p2-1-fix/mut.py` が `src/image_reviewer` を丸ごと写し、**1 か所だけ**置き換えて
`PYTHONPATH` の先頭に置き、`tests/test_p2_1.py` を丸ごと回す。**置き換えが 1 回だけ当たったこと**と
**写しを読んだこと**（`image_reviewer.__file__`）を毎回確かめる。素の写しは **41 passed**（基準）。

| 変異 | 落とした試験 | 結果 |
| --- | --- | --- |
| S8 「外す」が `asset_ids` を見ずに全部外す | `test_removing_one_image_keeps_the_other_images_in_the_folder` | 落ちた |
| S9 `sort=added` を古い順に | `test_the_folder_assets_list_sort_added_is_newest_first` | 落ちた |
| S10 `next_cursor` を 1 つ先まで（`<=`） | `test_the_last_page_has_no_next_cursor` | 落ちた |
| S11 確認の名前を大小文字無視 | `test_the_confirm_name_is_compared_exactly` | 落ちた |
| S12 `purge` なら確認を飛ばす | `test_the_confirm_name_is_compared_exactly`・`test_purge_still_needs_the_confirmed_name` | 落ちた |
| S14 見えない文字の検査を外す | `test_folder_names_refuse_control_and_invisible_characters` | 落ちた |
| S17 移動の深さを見ない | `test_a_folder_cannot_be_moved_below_the_depth_limit`・`test_a_deep_branch_cannot_be_moved_below_the_depth_limit` | 落ちた |
| S18 作るときの深さを見ない | `test_a_folder_cannot_be_created_too_deep` | 落ちた |
| S20 `manual` に戻しても条件を残す | `test_switching_a_smart_folder_to_manual_drops_the_query` | 落ちた |
| S24 `dry_run` の道で 1 行書く | `test_dry_run_writes_nothing` | 落ちた |
| S26 `limit` を 1,000 に丸めない | `test_the_folder_assets_limit_is_clamped` | 落ちた |
| Y6 早期 return の `_top_up_v7` を外す | `test_a_v7_database_without_the_unique_index_is_repaired` | 落ちた |
| （参考）`B1-old` 論理削除で `folder_member` を DELETE（**前のコード**） | 3 本（B-1 の 3 本） | 落ちた |
| （参考）`C4-old` `purge` を `bool()` で受ける | `test_purge_still_needs_the_confirmed_name` | 落ちた |
| （参考）`C5-old` NFC にそろえない | `test_folder_names_refuse_control_and_invisible_characters` | 落ちた |
| （参考）`D7-old` 枝の高さを数えない（**前のコード**） | `test_a_deep_branch_cannot_be_moved_below_the_depth_limit` | 落ちた |

**結果: 12/12（監査の 12 通り）・17/17（この修正で戻した 4 通りを含む）。生き残り 0。**
等価変異（Y2 `cid < 0`・M4 サービス層の一意検査）は監査の判定どおり**落とさない**（索引と文の比較が同じ 422 にする）。

**画面の検査が見るようになったもの**: `gui_smoke` 6 検査（確認文の子の数と名前・`dry_run` を読む口・同名の子）と、
`gui_layout` の `PRESS_FOLDERS` が **`dry_run` を本物のサーバに通す**（前は `fetch` を飲んでいたので、
画面が `dry_run` を読むようになったことを見られなかった）。**`gui_layout` の `PRESS_FOLDERS_ADD` は
「入れた後の 1 行が残る」を本物の Chrome で見る**（hash を変えた後に `showFolders` が消していないか。
**前のコードに戻すと 4 幅とも NG**（実測 `入れた後の 1 行が残る（"" visible=true）`）→ 戻して 4 幅とも ok）。
**本物の Chrome の 25 検査**（`realclick.mjs`）が「1 行が残る（すぐ・2 秒後）」「確認文が子の数と名前を言う」
「消した後も 1 行が残る」を毎回見る。

## 6. G（依頼者への質問）— 推奨どおりで進めた

| 論点 | どうした |
| --- | --- |
| G-1 論理削除で所属を残すか | **(a)** 残す（`purge` のときだけ消える）。B-1 |
| G-2 子を持つフォルダの削除の確認 | **(a)** `dry_run` を読んで「下のフォルダ N 個（…）も一緒に消えます」。B-2 |
| G-3 名前の同一視 | **(a)** NFC・見えない文字を拒む・大小文字は区別。C-5 |
| G-4 `GET /api/assets?folder=` | **(a) は P2-2**。それまで **(b) の 422** だけ先に。E-2 |
| G-5 C-2 の「中身が重複」 | **(a) は P2-2**（`v7_conflicts` に同名の検査。読むだけ） |

## 7. H（確かめられなかったこと・注記）

- **確かめていない**: **8790（利用者）の画面**（触らない約束）。実データが v7 に上がった後の挙動は、
  **実データの複製**（`create_app` の道）で代えた（§8）。
- **B-1 の「戻す」は DB を直接戻して確かめた**（口が無いため）。**同名の生きたフォルダが在ると部分索引が
  `IntegrityError`** になるので、戻す口を作るときは 422 に写す（D-2）。
- **隠したフォルダを実削除する口は無い**（`_row()` が 404 にするので `purge` は**生きているフォルダにだけ**
  打てる）。これは**新しい穴として記録**する（B-1 の試験も「戻す → `purge`」の順にした）。**P2-2 で
  「戻す」と一緒に決める**。
- **`gui_layout` の空の状態（C-1）は直していない**ので、**フォルダ 0 個の複製では 2 画面が NG** になる
  （画面は正しい。§2）。

## 8. 三点セットと実データ（修正の後）

| 何を | 結果 |
| --- | --- |
| `uv run --no-sync pytest -q` | **638 passed・0 failed**（622 ＋ 16。P2-1 の試験は 25 → **41 本**） |
| `node tools/gui_smoke.mjs` | **488 ok / NG 0**（482 ＋ 6） |
| `gui_layout` 12 本 × 4 幅（複製 8793） | **56 ok / NG 0**（12 本とも exit 0。比較は 3 窓 × 4 ＝ 12 行） |
| 本物の Chrome（`realclick.mjs`） | **1024×700: 25 ok / NG 0**・**1920×1080: 25 ok / NG 0** |
| 変異（`mut.py`） | **12/12・17/17 落ちた**（§5） |
| 実データ（前後の署名） | **v6 のまま・`quick_check ok`・表 23・`asset` 463・`deleted_at` 194・`deletion_log` 194・`decision` 3・`phash_band` 7408・`folder` 無し・`db.sqlite3` の sha256 同じ・`.data` の 5 ファイルの size/mtime 同じ・ルートの画像 424 個の size/mtime 同じ・`.backup` 12 個のまま** |
| 複製の DB（B-1 の実機） | 3 回の Chrome の後: **生きているフォルダ 5・隠れた 15・`folder_member` 16 行（うち隠れたフォルダの 12 行）**。**隠しても行が残っている**（前のコードなら 0） |

## 9. 残した物・消した物（実行したコマンド）

- 残した物（`.tmp-p2-1-fix/`。gitignore 済み）: `mk_replica.py`・`pick.py`・`realclick.mjs`・`realclick.ps1`・
  `gl.ps1`・`mut.py`・`sig.py`・ログ・`sig-before.json` / `sig-after.json`（パスと数の一覧。画像は無い）。
- **消した物**: `.tmp-p2-1-fix/gl/`（**実データの複製**。DB・サムネイル・複製した画像）・`.tmp-p2-1-fix/mut/`（変異の写し）・
  `.tmp-p2-1-fix/tmp/`。**実データの写しは 1 つも残していない。**

```powershell
$env:UV_CACHE_DIR = "C:\work\image-reviwer\.uv-cache"
uv run --no-sync pytest -q                                   # 638 passed
node tools/gui_smoke.mjs                                     # 488 ok / NG 0
.\.venv\Scripts\python.exe -X utf8 .tmp-p2-1-fix\mk_replica.py
powershell -ExecutionPolicy Bypass -File .tmp-p2-1-fix\realclick.ps1 -Phase realclick      # 25 ok
powershell -ExecutionPolicy Bypass -File .tmp-p2-1-fix\realclick.ps1 -Phase realclick-1920 # 25 ok
.\.venv\Scripts\python.exe -X utf8 tools\gui_layout_seed.py --data …\.tmp-p2-1-fix\gl\data --tags --exclusion --pending --stage3 --backup-error --backup-dir …\.tmp-p2-1-fix\gl\bk
powershell -ExecutionPolicy Bypass -File .tmp-p2-1-fix\gl.ps1 -Phase all                   # 56 ok / NG 0
.\.venv\Scripts\python.exe -X utf8 .tmp-p2-1-fix\mut.py      # 12/12・17/17 落ちた
.\.venv\Scripts\python.exe -X utf8 .tmp-p2-1-fix\sig.py .tmp-p2-1-fix\sig-after.json       # 前と同じ
```
