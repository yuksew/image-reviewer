# P8-2 の監査の仕分け（Fable の監査 → どう直したか）

- 監査報告: [`p8-2-audit-report.md`](p8-2-audit-report.md)（**判定: 合格（条件つき）**。**A は無し**。**B 3 / C 6 / D 17 / E 11 / F 8（穴） / G 7**）。
- 立場: **推奨（G-1〜G-7）はすべて採用**。**利用者の決定（C-1: 人は誰の削除でも戻せる）**も反映した。
- 触った物: `src/image_reviewer/deletions.py`（**1120 → 1557 行**）・`src/image_reviewer/api/deletions.py`（169 → **172 行**）・
  `src/image_reviewer/app.py`（361 → **365 行**。`do_scan` が錠を取る）・`src/image_reviewer/cli.py`（**+8 行**。`scan` が同じ錠を取る）・
  `tests/test_deletions.py`（1039 → **1817 行・42 → 75 件**）。設計は `docs/p8-design.md` に反映（§0.6・§0.7・§0.13・§0.14・§0.18・§3.2〜§3.4・§4・§8.1）。
  **`README.md` と `docs/design.md` は触っていない**（G-3 の 1 行は親がやる）。
- **テストは 367 → 400 passed**（+33。**3 回続けて 400**）。`gui_smoke` **129 ok**・`gui_layout` **6 画面 ok**（複製に 8791 でサーバ）。
- **実データ `.data/` は無傷**（`mode=ro`・`backup()`・`copy2` だけ。263 枚 / 判断 3 件 / **登録と実ファイルの `(size, mtime_ns)` が全枚一致**）。

| # | 指摘 | どう直したか |
| --- | --- | --- |
| **B-1**（G-4） | `os.rename` の後・台帳の前で落ちると**迷子**（一覧には「在る」と出続ける） | **台帳の 1 行を先に書いてから動かす。動かせなければ行を消す**（`_drop_log`。作った空の入れ物も `<data>` の手前まで片づける）。**この順で増える道**も塞いだ: 保留の実体が無い行は (a) 元の場所にファイルが在れば**戻したことにする**（削除は起きていない。1 バイトも触らない）、(b) どちらにも無ければ**後始末を完了する**（前の周期が途中で落ちた形）。**起動時に台帳に無い `pending-delete/` の中身を「拾い物」**として警告に出し、`GET /api/pending-deletes` の `found` にも出す（**消しも動かしもしない**） |
| **B-2** | 取り消しが `move_failed` で失敗した行は `purge_at` が残り、**窓が尽きると黙って消える** | `except ReviewError` の条件を **`("target_exists", "move_failed")`** に（専門 §3.4 の字義どおり）。`as_copy` の別名選びの 409 も同じ道に入れた（`destination` の計算を `try` の中へ）。**どちらも `purge_at` を NULL に**して `state: "stuck"` に残す |
| **B-3** | `tick` / `_purge_expired` が錠を取らず、**窓の最後の周期の `undo` と競合して登録が消える** | **`tick` の本体と `_purge_expired` を `self._lock` で包んだ**（二重に取ってあるので片方だけ外しても守れる）。**加えて**、消す直前に行をもう一度読み、取引の中でも `UPDATE … WHERE restored_at IS NULL` の `rowcount` を見る（**ファイルを消した後に登録だけ残る／戻したのに消える**の両方を止める） |
| **C-0** | 確かめた結果、問題なし（線 4〜7・GET・窓・凍結・安全・性能） | 変更なし（**直した後も `probe_p8.py --delete` の 18 項目が全部 OK**） |
| **C-1**（G-1・**利用者の決定**） | 人がエージェントの削除を戻せないのに「いま消す」はできる（Q2 の帰結 e と噛み合わない） | **人は誰の削除でも戻せる**（`check_owner = actor != "human"`）。**エージェントは自分の分だけ**（403 `not_yours`）。`undoable` は**人なら常に真**（`mine` は残す＝画面は「誰が」を出せる）。**設計 §3.4 の「（人を含む）」を外し、§0.14 の帰結 e に 1 行足した** |
| **C-2**（G-6） | 読み取り専用のファイルは実削除できず**毎周期やり直す**／「いま消す」が 500 | **`unlink` の前に `S_IWRITE` を立てる**（`_make_writable`。**自分の保留領域の中だけ**。外せなくても進む）。**`purge_now` の `OSError` は 409 `purge_failed`**、「保留に実体が無い」は 409 `not_in_hold`（元の場所に在るのに「消した」と言わない） |
| **C-3**（G-7） | `asset.deleted_at` は資産の単位、削除は場所の単位（複製が生きているのに一覧から消える） | **`_sync_hidden` を「いまの状態から引き直す」1 か所にまとめた**: **生きている `asset_location` が 0** か、**生きた段 1 の行がある**ときだけ立て、どちらでもなければ外す（`_hide_asset` は廃止）。段 1 も**同じ場所の 2 回目は行を増やさない**（D-12 も同時に直った） |
| **C-4** | 段 1・2 の一括でも `last_copies > 0` なら `confirm_last_copy` が要る（実データは全枚が最後の 1 つ＝毎回重い確認） | **段 3 のときだけ要求する**（`stage == 3 and last_copies and not confirm_last_copy`）。`last_copies` は preview が引き続き**情報として**返す（画面が「内容が失われる枚」を出せる） |
| **C-5** | 凍結した `(size, mtime_ns)` は実行時に比べられない | **凍結した値と DB の行の両方**を比べる（`_require_file(frozen=…)`。一括は凍結の 1 件を渡す）。食い違えば **409 / `skipped: changed`** |
| **C-6**（G-2） | `scan_running` は実装不能ではなく錠で守れる | **`DeletionService.scan_guard()`** を足し、**`app.do_scan` と `cli.cmd_scan` が同じ錠を取る**（**走査中は削除・取り消しが待つ**）。走査の最後の `mark_missing` が戻したばかりの枚を参照切れにする逆向きの事故も止まる。**待つだけで 409 は返さない**（§3.4 にそう書いた） |
| **D-1** | `_remove_hold` に**保留領域そのもの**を渡すと丸ごと消す（`is_under` は root 自身も True） | **深さ 1（`<削除ID>/`）と 2（その中のファイル）だけ**を許す（`os.path.relpath` で見る。`.`, それ以外は断る） |
| **D-2** | 段 3 の preview が印の無い置き場を数えない（実行で初めて `stage_not_allowed`） | preview が **`not_allowed` / `not_allowed_count`** を返す（`root.allow_stage3` を 1 回だけ読む） |
| **D-3** | ゴミ箱の日付が UTC（JST 02:30 の削除が `trash/20261017/`） | **現地（JST）の日付**に（`jst_day()`。JST は夏時間が無いので固定 +9 時間）。probe の実測も `trash\20261018\…` になった |
| **D-4** | 台帳の `display_path` が正規化した鍵（小文字） | **`asset_location.display_path` を引く**（読む 3 か所の SQL を `LEFT JOIN` に。行が消えていれば鍵しか無いので鍵を出す） |
| **D-5** | `GET /api/deletions/previews/{id}` が `actor` を見ない（`robot` で 200） | **`_actor_of` を通す**（語彙外は 422） |
| **D-6** | `stage: true` が段 1 として通る（`3.9` も 3） | **真偽値を先に断り、小数は整数でなければ 422**（`bad_stage`）。`"3"` のような整数の文字列は今までどおり通す |
| **D-7** | 断った後に空のフォルダが残る（`mkdir` が `same_volume` の前） | **ボリュームの判定を先に**し、断ったら**作った入れ物を空なら片づける**（`_prune_empty`。`<data>` は消さない） |
| **D-8** | 落ちた要求の行で同じ token が永久に `in_progress` | **`result_json` が無いまま `STALE_REQUEST_SEC`（600 秒）より古い行は捨てて再送を許す**（`self._lock` の中では「進行中」は同時に居ない。新しい物は今までどおり 409） |
| **D-9** | 段 3 の preview の `frees.at` が凍結の失効時刻 | **実行前は `null`**（いつ空くかは実行してから決まる）。文は「5 分の窓が過ぎた時点で空きます」のまま |
| **D-10**（G-5） | `PREVIEW_KEEP_SEC` が未使用（失効した凍結が永久に残る） | **タイマーが掃除する**（`_sweep_previews`: **未実行で `expires_at` が 1 日過ぎた行だけ**）。**失効後すぐは消さない**ので線 8 の 409 は守られる。実行済みは残す（`result_json` を返すため） |
| **D-11** | `int(delta)` の切り捨てで窓が周期ごとに最大 1 秒延びる | **端数を次の周期に繰り越す**（`self._last_tick += charge`） |
| **D-12** | 段 1 を 2 回 → 1 回戻しても隠れたまま | **同じ場所の段 1 は 1 行**（2 回目は `replayed: true` で同じ `deletion_id`。C-3 の `_sync_hidden` と合わせて直った） |
| **D-13** | `path` が空だと 409 `not_registered` | **422 `bad_path`**（入力の不足は入力の誤り。語彙外は 422 に揃えた） |
| **D-14** | `folder` の `scope` に置き場の制限が無い（`C:\` で全部凍結に入る） | **登録した `root` の下だけ**を許す（外は 422 `bad_scope`。preview が現実的な歯止めになる） |
| **D-15** | 線の番号（指示書は 4〜7・設計と probe は 5〜8） | **probe の表示は設計の番号（5〜8）のまま**にし、**この仕分けと §0.18 に「指示書 4〜7 ＝ 設計 5〜8」と 1 行**書いた（番号は変えない） |
| **D-16** | 設計 §0.6-1 が `os.replace`・§0.13 L221 も `os.replace`（実装は `os.rename`） | **設計を `os.rename` に直した**（§0.6-1・§0.13。**実装が安全側**なので実装は変えない） |
| **D-17** | テストの `client` fixture が 30 秒周期のタイマーを張る／HTTP の GET-無書き込みが `remaining_sec` 無しでしか見ていない | fixture は **`start()` を呼んだまま周期を 1 時間**にし（本番と同じ道を通す）、**`remaining_sec` の在る状態で口から GET を叩く**テストを足した |
| **E-1〜E-11** | 設計とのずれ（`target_exists` だけ・順序・`not_yours`・`scan_running`・`allow-stage3`・`os.replace`・失効の掃除・凍結の再照合・ゴミ箱の復帰・`deleted_at` の単位・`last_copies`） | **E-1〜E-4・E-6〜E-11 は本文を直した**（§0.6・§0.7・§0.13・§0.14・§3.2〜§3.4・§4.1・§4.3）。**E-5（`allow-stage3` の口）は P8-4 の表のまま**（G-3。**scan で増えた root は印なしになる**旨を §3.3 に 1 行足した） |
| **F（8 つの穴）** | stuck の行の自動削除・上限・束の `last_copies`・同じ id の畳み・`as_copy` の DB 側の衝突・`_flag`・undo の錠・**`start()` で消さない** | **8 つとも試験を足した**（`test_a_stuck_row_is_never_purged_automatically`・`test_the_window_is_charged_by_the_shorter_elapsed_time`・`test_the_last_copies_are_counted_as_a_bundle`・`test_the_same_asset_id_twice_in_the_scope_is_one_item`・`test_as_copy_avoids_names_that_the_catalog_already_uses`・`test_the_confirmation_flags_do_not_accept_the_string_false`・`test_undo_waits_for_the_service_lock`・`test_start_does_not_delete_and_the_first_tick_after_it_waits`）。**B-1〜B-3・C-2〜C-5 の試験も足した**（25 件） |
| **G-1〜G-7** | 直し方の選択 | **すべて推奨どおり**。G-1（人は誰の削除でも）・G-2（錠）・G-3（口は P8-4 のまま＋§3.3 に 1 行）・G-4（順序＋拾い物）・G-5（1 日で掃除）・G-6（`S_IWRITE` と 409）・G-7（`deleted_at` の単位） |

## 「壊すと落ちる」の確認（**自分で壊して落ちるのを見てから戻した**）

- `.tmp-audit-redo/p8-2-fix/mutants.py` が **`src/image_reviewer` の写しを作り、写しの中だけを壊して**
  `PYTHONPATH` で先に読ませて `tests/test_deletions.py` を回す（**実物は毎回 sha256 で不変を確認**）。
- **36 通り中 34 通りが落ちる**。落ちなかった 2 つは **B-3 の錠を片方だけ外した物**（`tick` か `_purge_expired` の
  どちらか）で、**もう片方の錠が守る**ため（**両方外す B-3c は落ちる**＝二重に取ってあるのが効いている）。
- 主な物: B-1（順序を逆にする → 1 件）・B-1（行を消さない → 1 件）・B-1（移動前の後始末をしない → 1 件）・
  B-2（`move_failed` を外す → 1 件）・B-3c（両方の錠を外す → 1 件）・C-1〜C-5・D-1〜D-14・F-1〜F-8・G-4/G-5
  （**それぞれ狙った試験が落ちる**）。

## 実測（直した後）

- **`probe_p8.py --delete`**（実データの複製 263 枚＋複製した画像 13 枚・HTTP）: **18 項目すべて OK**。
  ゴミ箱は **`trash\20261018\c7\…`（JST）**になり、段 3 の `remaining_sec` 300・`frees` の文・
  失効 409・`last_copy` 409・上限 422（台帳 8 → 8）・印なし 409・`cross_volume` 409 は今までどおり。
- **本物のサーバ（8791・複製 20 枚・窓 40 秒。`IMAGE_REVIEWER_DATA` を付けて起動）**:
  - **B-1/G-4**: 起動前に `pending-delete/orphan-dir/lost-pickup.png` を置く → 起動のログに
    「保留領域に台帳の無いファイルが 1 件あります（拾い物。消しません）」・`GET /api/pending-deletes` の
    `found_count` が 1・**ファイルは消えていない**。
  - **B-2**: 段 3 → 元のフォルダを消す → `undo` は **409 `move_failed`**・`purge_at` は **NULL** →
    **窓を 0 にして 70 秒（2 周期）待っても実体が残る**（`hold_path` も「(削除済み)」にならない）→
    人が「いま消す」で 200。
  - **B-3**: 窓 40 秒の**期限 6 秒前**に `undo` → **200・ファイルは元の場所・`asset_location` は 1 行・
    `restored_at` が立つ** → 窓が尽きた後の周期をまたいでも**登録が消えない**。
  - **C-1**: エージェントの段 3 を人が `undo` して **200**（`mine: false` / `undoable: true`）。
    **エージェントが人の削除を戻すと 403 `not_yours`**。
  - **C-3**: 場所を 2 つにして片方を段 3 → **一覧に出たまま**（`deleted_at` は NULL）。
  - **D-3**: ゴミ箱が **`20261018`（JST）**。**D-4**: 台帳の `display_path` が登録の表記。
  - **D-5/D-6/D-13**: 凍結の GET は `robot` で 422・`stage: true` は 422 `bad_stage`・空の `path` は 422 `bad_path`。
  - 終了後に **8791 の待ち受けは 0 本**・**8790（利用者のアプリ）は `health` ok・pid 22132・`started_at 2026-10-17T17:01:43Z` のまま**。
- **三点セット**: `pytest -q` **400 passed × 3 回**（19.3 / 19.2 / 19.1 秒）・`gui_smoke` **129 ok**・
  `gui_layout` **6 画面すべて ok**（比較・要求・まとまり・注記＋タグ・語の一覧・ジョブ。複製 8791）。
- **実データ `.data/`**: v6・**263 枚**・判断 **3 件**・`deleted_at` 0・`missing_at` 0・台帳 0・要求 0・凍結 0・
  `phash_band` 4208・root の印（`illust-authoring` = 1）はそのまま。**登録と実ファイルの `(size, mtime_ns)` が
  263 枚とも一致**（＝この段の間に 1 枚も動かしていない・書き換えていない）。`db.sqlite3` は
  **1,544,192 B / 00:07:26**、`-wal` は **4,190,072 B / 02:01:43**（**監査の記録と同じ**＝私の作業では 1 バイトも書いていない）。
- **`.backup/` は 7 つともそのまま**（消していない）。

## 申し送り

1. **README の 1 行（G-3）は親がやる**: `scan` で新しい root が増えると**印なし**（段 3 は不可）で入る。
   `POST /api/roots/{id}/allow-stage3` は **P8-4** のまま。
2. **`os.replace` の字（D-16）**は設計を直したが、**§0.6-4 の「`os.rename`」と §0.13 の「`os.rename`」で揃っている**ことを
   `grep` で確認した（`os.replace` は §0.13 の「原子性」（sidecar・スナップショットの話）にだけ残る）。
3. **`purge_at` は目安**のまま（実削除は周期の粒度。最大 30 秒遅れる）。
4. この段の一時物: `.tmp-audit-redo/p8-2-fix/`（写し `mutsrc/`・複製 `srv/` `srv-lib/`・
   スクリプト `mutants.py restore.py debug_b3.py b3_probe.py make_srv.py http_fix.py real_check.py sig_search.py`・
   出力 `mutations.out.txt http_fix.out.txt real_check.out.txt server.log probe_delete.out.txt`）と
   `.tmp-audit-redo/p8probe/`。**消して構わない**（`tests/.tmp` の溜まっていた 76 個も掃除した）。
