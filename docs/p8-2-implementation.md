# P8-2 の実装の記録（削除と取り消し。合格の線 4〜7）

- 日付: 2026-10-18。設計: `docs/p8-design.md`（**855 行**。§0.1 の P8-2 の行・§0.3・§0.6（規則 1〜5）・
  §0.7・§0.13・§0.14（Q1〜Q8）・§0.16・§0.17・§2.1・§3.2〜§3.4・§4・§7・§8.1・§8.4・§9）
- 指示書: `docs/p8-2-implementation-brief.md`（68 行）
- 前段: P8-0 の表と列（v6）・P8-1 の重複（`duplicates.py` の形に倣った）
- **利用者の実データのファイルを動かす・消す機能**なので、**すべての試験は複製で**行った
  （`sqlite3` の `backup()` ＋ **画像も `shutil.copy2` で複製**してから、複製の DB の登録を
  複製先へ向け直す）。実データは `mode=ro` でしか開いていない。

## 作ったもの

| ファイル | 行 | 何 |
| --- | --- | --- |
| **`src/image_reviewer/deletions.py`** | **新規 1120** | 段 1〜3（`delete`）・凍結と実行（`bulk_preview` / `bulk_delete`）・取り消し（`undo` / `trash_restore` / `purge_now`）・読み（`pending` / `ledger` / `trash` / `preview_of`）・**30 秒周期のタイマー**（`start` / `tick` / `_purge_expired`）・安全規則（`move_no_clobber` / `_require_file` / `_require_last_copy` / `_require_stage3_root` / `_destination` の `st_dev` 判定） |
| **`src/image_reviewer/api/deletions.py`** | **新規 169** | 11 の口（設計 §3.2 ＋ §5 の「いま消す」＋ 凍結の読み）。確認の欄は文字列でも安全側（`_flag`） |
| `src/image_reviewer/api/__init__.py` | +5（102 行） | `deletions_of()` |
| `src/image_reviewer/app.py` | +26（361 行） | `DeletionService` の生成・`app.state.deletions`・`include_router`・**`lifespan` でタイマーを張る／止める**・**`GET /api/assets` の `include_deleted`**（既定は段 1〜3 を出さない） |
| `src/image_reviewer/store.py` | +2/−1（523 行） | `_asset_dict` の `deleted_at` が **`None` 固定だった**のを実の値に（§0.15-3 の残り） |
| `src/image_reviewer/db.py` | +27（752 行） | `pending_delete_preview` に `executed_at` / `result_json` / `request_id`、`delete_request` に `payload_json`（**`V6_DELETE_DDL` と `_top_up_v6` の両方**。実データは既に v6 なので `PRAGMA table_info` を見てから `ALTER`） |
| **`tests/test_deletions.py`** | **新規 1039・42 件** | 段 1〜3・窓（時計を注入）・起動時に消さない・取り消し（上書きしない）・`last_copy`・`allow_stage3`・別ボリューム（`st_dev` を注入）・中身の変化・凍結・失効・上限 200・`client_token`（再送・同時）・`GET` が書かない・403 / 422・**規則の限界（同じ大きさの差し替え）** |
| `tools/probe_p8.py` | +461（658 行） | **`--delete`**（線 5〜8 を**実データの複製＋複製した画像**で、**HTTP（`TestClient`）で**通す）＋ `--duplicates` / `--all` の切り替え・作業場の後始末 |

- **触っていない物**: `README.md` / `docs/design.md` / 契約（`schemas/`）/ GUI（`apps/gui`）/ ComfyUI /
  `.data/`（読み取りのみ）/ `db.py` の既存の表（**足しただけ**）。`git` のコミットもしない。

## 実行した結果

### 三点セット（**すべて緑**）

| 確認 | 結果 |
| --- | --- |
| `uv run --no-sync pytest -q` | **367 passed**（325 → +42）。**3 回続けて 367**（揺れなし） |
| `node tools/gui_smoke.mjs` | **すべて ok**（129 件） |
| `node tools/gui_layout.mjs`（複製にサーバを 8791 で立てて） | **6 画面すべて ok**（比較・要求・まとまり・注記・語の一覧・ジョブ） |

- `--screen tags` は**複製の `tag` が 0 行だと NG**（「語の行が出る」）。実データはタガーを回していないので
  0 行。**複製にだけ語を 5 つ入れて**（`.tmp-audit-redo/p8_2_gui_replica.py`）緑を確認した。**実データは 1 行も書いていない**。
- `--screen group` は実データの `review_group` が 0 行なので、複製に `probe-group`（3 枚）を作って通した。

### 合格の線 4〜7（`uv run --no-sync python tools/probe_p8.py --delete`。実データの複製 263 枚＋複製した画像 13 枚）

| 線 | 結果 |
| --- | --- |
| **5a 段 1** | 200 / 一覧 **263 → 262** / `?include_deleted=1` で **263** / **ファイルは元のまま** / 判断は残る |
| **5b 段 2** | 200 / `<data>/trash/20261017/c7/…png` へ移動 / `POST /api/trash/restore` 200 で**元へ戻る** |
| **5c 段 3** | 200 / `<data>/pending-delete/<id>/…png` / `GET /api/pending-deletes` に **`remaining_sec` 300** / **`asset_location` の行は在り `missing_at` が立つ**（点検 A3） |
| **6a すぐ戻す** | 200 / 元のパスへ戻り、保留領域から消える |
| **6b 上書きしない** | 別のファイルを置いて `undo` → **409 `target_exists`** / **元のファイルのバイト列は無傷** / 保留に残る / 人だけ `as_copy: true` で **`…<名前>.1.png`** に戻る |
| **7a 窓は単調時計** | 壁時計 +3600 → **300 のまま** / 単調時計 +299 → **1** |
| **7b 起動し直しても消えない** | 新しい `DeletionService` を作っても保留領域は残る（1 秒） |
| **7c 期限切れで消える** | 1 周期目は**消さない** / 2 周期目で消える / `hold_path` は「(削除済み)」/ 台帳の行は残る |
| **8a 凍結どおり** | preview 4 枚 → 1 件差し替え → 実行 **deleted 3 / skipped `['changed']`** / 差し替えた 1 件は残る / **凍結後に増えた枚も残る** |
| **8b 失効** | 10 分後に実行 → **409 `preview_expired`** / **1 枚も消えない** |
| **安全 `last_copy`** | 409 `last_copy` / ファイルは残る / 台帳にも要求にも行を作らない |
| **安全 上限** | 201 件の凍結を直に入れて実行 → **422 `too_many`** / **1 枚も消さない**（台帳 8 → 8 行） |
| **安全 `allow_stage3`** | 印の無い root で段 3 → **409 `stage_not_allowed`** / **段 1 は 200** |
| **安全 別ボリューム** | `st_dev` を注入 → 段 2・段 3 とも **409 `cross_volume`** / ファイルは残る / **コピーもしない** |
| **家風 `GET` は書かない** | 全表の行数＋ファイルの size / mtime が前後で同じ |
| **家風 403 / 422** | `Host: evil` 403 / `Content-Type: text/plain` 403 / `actor: robot` 422 / `stage: 4` 422 |
| **実データが無傷** | 263 枚 / 判断 3 件 / 台帳 0 行 / **画像の署名（size・mtime_ns）が同じ** |

### 実データが無傷であること（私の作業の間）

```
db.sqlite3:     1544192 バイト / mtime 2026-10-18 00:07:26（**私の最初のコマンドより前。作業中は不変**）
db.sqlite3-wal: 4190072 バイト / mtime 2026-10-18 00:07:26
asset 263 / deleted_at あり 0 / asset_location 263（missing_at あり 0）/ decision 3
deletion_log 0 / delete_request 0 / pending_delete_preview 0 / duplicate_exclusion 0
画像: 登録 263 か所 / 実体が無い 0 か所
画像の署名: sha256 fa99ca126c393d5a… / 合計 292561491 バイト（263 枚）
root: illust-authoring allow_stage3=1 / ComfyUI の置き場 0
```

- **親が 2026-10-18 02:01 に利用者のアプリ（8790）を再起動して P8-2 を載せた**。その再起動で
  `_top_up_v6` が**実データにも新しい列を足した**（`pending_delete_preview` に
  `executed_at` / `result_json` / `request_id`、`delete_request` に `payload_json`。WAL に入るので
  `db.sqlite3` の size / mtime は変わらない）。**これが「古い v6 の実データでも一括削除が動く」ことの
  実機での確認**になった（`GET /api/health` は `ok`・v6・263 枚・判断 3 件・台帳 0 のまま）。
- `.data` の pHash は**私の作業の前（00:07）に既に 263 枚・帯 4208 行**だった（P8-1 の記録の「91 枚」から、
  利用者のアプリのサムネイル生成で増えた分）。**私は `.data` に 1 バイトも書いていない**（`mode=ro` だけ）。

### 実機（uvicorn を 8791 で直起動・複製）での往復

`POST /api/locations/delete`（段 3）→ `GET /api/pending-deletes` → **35 秒待つ** → もう一度 `GET` → `undo`:

```
段 3: remaining=300
35 秒後: remaining=277   ← 実際に存在した 23 秒だけ引かれた（周期またぎの引きすぎが無い）
さらに 32 秒後: remaining=247
取り消し: restored=True 元に戻った=True
```

- **タイマーは `lifespan` で張る**ので、uvicorn で起動した本物のサーバでも 30 秒周期が回ることを確認した。
- 直す前は同じ手順で **35 秒に 60 秒**引かれていた（下の「自分で決めた点 7」）。**これは実機で見つけた**。

### 「壊すと落ちる」（`.tmp-audit-redo/p8_2_mutants.py` で 10 通り・**すべて落ちた**）

| 壊し方 | 落ちたテスト（実測） |
| --- | --- |
| `os.rename` → **`os.replace`** | `test_move_no_clobber_refuses_to_overwrite`・`test_undo_never_overwrites_a_file_that_appeared_meanwhile`（**2 failed**） |
| 窓を**壁時計**で数える（`purge_at <= now` で 0） | `test_the_window_moves_with_the_monotonic_clock_only` |
| **凍結を外す**（実行時に `scope` を評価し直す） | `test_the_preview_freezes_the_list_and_only_that_list_is_deleted` |
| **起動直後の 1 回でも消す**（1 周期待たない） | `test_the_start_does_not_delete_anything_and_the_first_tick_waits` |
| **`last_copy` を見ない** | `test_the_last_copy_needs_a_heavy_confirmation`（＋一括側は別の検査なので通る＝下の注記） |
| **`root.allow_stage3` を無視** | `test_stage3_needs_the_flag_on_the_root`・`test_a_root_outside_every_root_is_not_allowed`（**2 failed**） |
| 上限を**部分適用**にする（200 枚だけ消す） | `test_the_agent_limit_is_two_hundred_and_nothing_is_deleted` |
| **`normalize_path` を `str(path)`** に替える | `test_the_target_must_be_registered_and_matched_exactly` |
| **`(size, mtime_ns)` の再照合を外す** | `test_a_changed_file_is_not_deleted`・`test_the_execute_skips_the_changed_item_and_deletes_the_rest`（**2 failed**） |
| **v6 の列を足さない**（`_top_up_v6`） | `test_the_v6_columns_are_topped_up_on_an_old_database` |

- 注記: 「`last_copy` を見ない」は**一括の検査が別の関数**（`_count_last_copies` ＋ `bulk_delete` の判定）なので、
  単発を壊した場合は一括のテストが通る。**狙った 1 件は落ちている**。
- 最初の版では「凍結を外す」が**落ちなかった**（凍結した `scope` が `assets` で、実行時に引き直しても
  同じ 5 枚になったため）。**フォルダで選ぶ形にテストを直して**初めて落ちるようになった（家風の「壊すと落ちる」の確認が
  テスト自体の穴を見つけた例）。

## 自分で決めた点（1 行ずつ理由）

1. **`pending_delete_preview` に `executed_at` / `result_json` / `request_id`、`delete_request` に
   `payload_json` を足した**（`_top_up_v6` で `PRAGMA table_info` を見てから `ALTER`）。設計 §0.16 A2・§4.3 が
   「実行後も行を消さず、それらを持たせる」と言うのに **§2.1 の DDL に列が無い**（設計の穴 1）。実データは
   既に v6 なので、列を足す道が要る（**足さないと一括削除が `no such column` で丸ごと落ちる**）。
2. **失効した凍結を自動で消さない**（§2.1 / §4.3 の「起動時と 1 時間ごとに掃除」を採らない）。消すと
   線 8 の「10 分後に実行 → **409 `preview_expired`**」が **404 になって「何も消さない」を確かめられなくなる**。
   1 件 1 行なので害が小さい（**掃除するなら失効から 1 日ほど経ってから**という形にしてもよい）。
3. **一括では、印の無い置き場・別ボリューム・中身の変化を `skipped` にして残りを消す**（単発は 409）。
   専門 §3.2 の 2「1 件の食い違いで一括全体を止めない」に合わせた。**「1 枚も消さない」は
   単発・上限・`last_copy`・失効の 4 つで守る**（一括の途中で止める方が危ない）。
4. **`POST /api/deletions/{id}/purge`（「いま消す」）を足した**。§5 の画面は「戻せませんでした」の行に
   「いま消す」を出すのに、**§3.2 の口の表にその口が無い**（設計の穴 3）。専門 §3.4 も
   「利用者が明示的に『消す』を選ぶまでこのツールはこのファイルに触らない」と言うので押し先が要る。
   **人だけ・`confirm: true` 必須**。
5. **`undo` は段 1・2・3 のどれにも効く**（段 1 は印を外すだけ・段 2 はゴミ箱から戻す）。
   専門 §3.1 が段 1 を「いつでも戻せる」と言い、段 2 の復帰と同じ操作なので 1 本にまとめた
   （`POST /api/trash/restore` は**人だけ**の別名）。
6. **`target_exists` のときも `purge_at` を NULL にする**（§0.6-4 の「失敗したら NULL」を当てた）。
   **尋ねている間に窓が切れて黙って消える**のを防ぐ。行は「戻せませんでした」（`state: "stuck"`）に出る。
7. **窓の引き方を「その行が生まれてからの経過」で上限付きにした**。§0.6-2 の「前回からの経過を引く」を
   そのまま実装すると、**消した直後の周期で最大 30 秒ぶん多く**引かれ、**実機で 35 秒に 60 秒**減った
   （「あと 5:00」が数秒で 4:30 になる）。このプロセスが作った行だけ生まれてからの経過で上限を付ける
   （再起動をまたいだ行は設計どおり）。**窓が延びる側には倒れない**。
8. **どの root にも入っていない場所は段 3 を許さない**（印が無いのと同じ扱い）。§0.6-6 は
   「印が無い root」しか書いていないが、**「どの root の管理下でもない」はもっと弱い根拠**なので安全側。
9. **`as_copy` で戻したら `asset_location` の `path` / `display_path` を新しい名前に付け替える**。
   §3.2 は「別名で戻す」しか言わないが、付け替えないと**登録が実体を指さない**（`missing` のまま）。
   別名は**ファイルと DB の両方**で空いている物を選ぶ（`path` は主キーなので DB も見る）。
10. **`client_token` は要求の単位**（`delete_request`）。`payload_json` を足して、**同じ token で違う内容**が
    来たら **409 `client_token_conflict`**（P6 と同じ流儀）。操作は**サービスの中で錠で直列化**するので、
    同じ token の同時要求は「新規 1・写し 1」になる（§8.4 F10）。
11. **口の名前は設計（`/api/pending-deletes`）と指示書（`/api/deletions/trash`・`/api/deletions/{id}/undo`）の
    両方**を同じ処理に結んだ（**どちらでも同じ物が返る**）。設計の名前を正としつつ、指示書の検査も通る。
12. **`POST /api/locations/delete` は `asset_id` が無くてもパスだけで当たる**（あるときは一致を要求）。
    パスが鍵（`asset_location.path`）なので、無いことを理由に断る必要が無い。
13. **確認の欄（`confirm` / `confirm_last_copy` / `as_copy`）は文字列でも安全側**（`"false"` を真にしない）。
    `bool("false")` は **True** なので、そのまま使うと確認を飛ばせる。
14. **`scope` に同じ `asset_id` が 2 回来ても 1 件**に畳む（同じファイルを 2 回消しにいかない）。
15. **`query` の絞り込みは `GET /api/assets` の意味に合わせた部分集合**（`q` / `state` / `tag` / `known`）。
    `provenance` は未対応（語彙外は 422 `bad_scope`）。**画面が使う形が決まったら P8-5 で揃える**。
16. **`GET /api/assets` に `include_deleted` を足した**（§4.1 の「`?include_deleted=1` で出る」）。
    `store._asset_dict` の `deleted_at` が `None` 固定だったので実の値を返すようにした（§0.15-3 の残り 2 か所）。
17. **`GET /api/deletions` の `limit` は既定 100・1〜1000**（設計に数が無い）。範囲外は 422。
18. **`GET /api/deletions/previews/{id}`**（凍結した一覧の読み）を足した。**実行時に評価し直さない**ことを
    画面と監査が確かめられる（実行後は `result_json` も返る）。

## 申し送り

1. **`POST /api/roots/{id}/allow-stage3`（段 3 の印を付ける口）は作っていない**（§3.3 の表にあるが
   P8-2 の指示書の口の一覧に無い）。**新しい置き場に印を付ける手段が API に無い**ので、P8-5 の設定の画面までに要る。
2. **走査中の削除を止める `scan_running`（§3.4）は実装していない**。`scan` は同期の口で `job` に行を作らないので、
   **「走査中」を判定する材料が無い**（設計の穴 5）。`scan` を job にするか `Store` に印を置くのが要る。
3. **人がエージェントの削除を戻せない**（`not_yours` を「人を含む」の字義どおりにした。§3.4・§5）。
   「エージェントが消した物に人が気づいて戻す」導線（Q2 の帰結 e）と噛み合わないので、
   **P8-5 の画面と合わせて利用者に聞きたい**（規則を 1 行変えれば人も戻せる）。
4. **`purge_at` は目安**で、実際に消えるのは周期の粒度ぶん遅れる（最大 30 秒）。
   引きすぎ（早く消える側）は直した。
5. **ゴミ箱の自動掃除（Q7「知らせるだけ」）は未実装**（通知の画面が P8-5）。
6. **実機の別ボリューム（D:）は確かめられなかった**: この環境は `D:\` への書き込みが **WinError 5** で
   拒まれる（設計 §10-6 の宿題のまま）。`st_dev` が C: と D: で違うこと（`2215286401518734889` /
   `10252108428756268205`）は読み取りで確認済み。**注入した `st_dev` では段 2・3 とも 409 になる**。
7. **一括の再照合の性能は未計測**（§7 の「1,000 件で 1 秒以内」）。実測は probe の 4〜5 件（1 件あたり
   `os.stat` 1 回＋数クエリ）。**1,000 件の複製を作るのは P8-5 の画面ができてから**でよいと思う。
8. **`§8.4 F7`（2 ページ目を潰した `quick_check`）は P8-4 の担当**なので、この段では作っていない
   （`GET /api/health/db` が P8-4）。
9. **`docs/p8-design.md` の §2.1 の DDL と §4.3 の文が食い違ったまま**（下の設計の穴 1・2）。
   **P8 の完了時に `design.md` を直すとき一緒に直す**のがよい。
10. 残した物（`.tmp-audit-redo/`）: `p8gui/`（gui_layout 用の複製＋複製した画像・thumbs）、
    `p8_2_mutants.py`（壊すと落ちるの脚本）、`p8_2_gui_replica.py` / `p8_2_http_prep.py` /
    `p8_2_real_check.py` / `p8_2_inspect.py`（使い捨て）。**`tools/probe_p8.py` の作業場（`p8probe/`）は
    実行のたびに自分で消す**（`--keep` で残る）。

## 設計の穴（気づいた物）

1. **§2.1 の `pending_delete_preview` の DDL に `executed_at` / `result_json` / `request_id` が無い**のに、
   §0.16 A2 と §4.3 は「実行後も行を消さず、それらを持たせる」と言う。**同じ節の中で食い違っている。**
   → 列を足して §4.3 に寄せた。**§2.1 の DDL を直すべき。**
2. **§2.1 の「`pending_delete_preview` は実行後に消す（`DELETE`）」と §4.3 の「実行しても行は消さない」が矛盾**。
   → §4.3 が正（**線 8 の再送と失効の 409 の両立**に要る。消すと `preview_expired` が 404 になる）。
3. **§5 の「いま消す」に対応する口が §3.2 の表に無い。** → `/api/deletions/{id}/purge` を足した。
   **§3.2 に 1 行要る**（人だけ・`confirm` 必須）。
4. **§3.4 の `not_yours`（「人を含む」）と Q2 の帰結 e（人が気づいて戻す導線）が両立しない。**
   人がエージェントの削除を戻せないので、**取り消しの窓を人だけが使えない場合がある**。
5. **§3.4 の `scan_running` を出す材料が無い**（`scan` が `job` を持たない同期の口）。
6. **§0.15-3 の「`deleted_at` は実装と実データに無い」は 3 か所あった**（DB の列・`store._asset_dict` の
   `None` 固定・`app.py` の絞り込み）。P8-0 が DB を、P8-2 が残り 2 か所を直した。
7. **§0.6-2 の「前回からの経過を引く」は、消した直後の行に余計に引く**（実測: 35 秒で 60 秒）。
   **「その行が生まれてからの経過」で上限を付ける**のが正しい。窓の意味（アプリが動いていた時間）は変わらない。
8. **線 5 は段 2 を「`<data>/trash/<日付>/…` に移り、元の場所へ戻せる」と言うが、P8-2 の指示書の口の一覧に
   戻す口が無い**（設計 §3.2 には `POST /api/trash/restore` がある）。線が「戻せる」を要求するので作った。
9. **§3.3（バックアップの節）に `POST /api/roots/{id}/allow-stage3` が入っている**が、これは削除（段 3）の
   統制なので、**§3.2 に置く方が読み手に親切**。
10. **「最後の 1 つ」の数え方は 1 枚ずつでは足りない**: 同じ画像の生きた場所が 2 つとも凍結に入っていると、
    1 枚ずつ見ると「最後の 1 つ」に見えないが、**内容は失われる**。→ `_count_last_copies` は**束で数える**
    （実装でそうした。§3.2 の `last_copies` の定義に注記が要る）。
