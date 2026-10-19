# P10 の監査の仕分け（**直した**。2026-10-19）

- 監査: [`p10-audit-report.md`](p10-audit-report.md)（219 行。**判定: 直してから次へ**。**A-1〜A-3**／B 2 件／
  C 3 件／D 12 件／E-0 の合格の線 10 本／F 壊し試験 32 通り／G の質問 5 件）
- 指示: 依頼者の「**P10 の監査の指摘を直す。判定は『直してから次へ』（このプロジェクトで初めて）。
  **A-1 は利用者のファイルを壊し得る穴**。**推奨はすべて採用**」
- 直した人: DeepSeek（実装者）／**実装の記録は本文書**（正は [`design.md`](design.md) §6.1・§16.7 と
  [`deletions-advance.md`](deletions-advance.md) §7）
- **実データ `.data/` は `mode=ro` でしか開いていない。画像は 1 枚も動かしていない**（§検証-5）。
  壊す試験・複製の線は**すべて複製**（`sqlite3.backup()` ＋ `copy2` ＋ **パスの貼り替え**）で行った。
  **利用者のアプリ（8790）には触っていない**（listen していないので立ててもいない）
- 監査の道具・複製（`.tmp-audit-redo/p10-audit/`）とその報告は**書き換えていない**

---

## 0. 一行ずつの仕分け

| # | 監査の指摘（重大な順） | 判定 | 直した所 |
| --- | --- | --- | --- |
| A-1 | 古い `asset_id` の 6 行の advance が**別の画像 Y のファイルをゴミ箱へ移し、Y を一覧から消す** | **採用（最優先）** | `deletions.py` `_require_file_for_advance()`（台帳の `size` と**いま登録している枚**を照合 → 409 `different_file`）＋ `_files_of_row()`（`close` は「**この行の画像**が在るか」で見る） |
| A-2 | 「戻す」が**いまその場所に登録されている枚 Y** の `deleted_at` を引き直さない（実体があるのに永久に消える） | **採用** | `deletions.py` `_sync_hidden_with_location()`（`_restore` / `_mark_recovered` が**台帳の枚といまの登録の両方**を同期） |
| A-3 | 片付けた行は**ファイルが戻っても二度とカタログに戻せない** | **採用（監査の推奨 (a)＋(b)）** | `should_hide()` / `_live_stage1()` が**閉じた行を数えない**＋ `scan.py` が**印を引き直す**（`sync_hidden`）＋ 実体が在れば `undo` が**開き直す**（`_reopen_closed_row`） |
| B-1 | 二度押しで POST が 2 回飛び、**2 回目の応答が結果の文を上書き**する | **採用** | `apps/gui/pending.js` の `advance` / `closeRow` / `runBatch` に `busy`（**`await` の前に立てる**。確認も 1 回だけ）＋ `gui_smoke` に**2 連打で POST 1 回**の検査 11 件 |
| B-2 | `delete_request` の記録が**4 つの口のうち単発の `advance` だけ** | **採用（推奨 (a)）** | `deletions.py` `_run_many()`（まとめては 1 呼び出し 1 行・`count` = requested・`result_json` に `skipped`）＋ `close()`。`stage` は `_request_stage_for()`（片付けは段が無いので揃っていればその段）。**断った要求は残さない** |
| C-1 | 古い `asset_id` の行は `close` もできない（X の実体はどこにも無いのに、Y のファイルで `file_found`） | **採用** | A-1 と同じ（`_files_of_row()`）。**実データで 193 件が閉じ、1 件だけ断られる**ことを複製で確認（§検証-4） |
| C-2 | `test_the_stuck_reason_says_why_it_could_not_go_back` が不安定 | **採用（先に直した）** | **別件として既に直っている**（[`stuck-reason-fix.md`](stuck-reason-fix.md)。原因は**時計の刻み**で、実装は仕様どおり。テストの**前提**を `os.utime` で固定）。今回は**触っていない**（`git diff` に無い） |
| C-3 | 閉じた段 3 の行をタイマーがまだ見る | **採用（推奨 (a)）** | `deletions.py` `_close_one()` が `purge_at` / `remaining_sec` も NULL にする（`stuck` と同じ扱い） |
| D-1 | `_run_many` が `replayed` を `count` に数え、「2 件を片付けました」と出る | **採用** | `replayed_count` を分けて返し、画面は「**2 件は既に片付けていました。**」と足す（`closeDoneText(count, replayed)`） |
| D-2 | 1 件も選んでいないのに「選んだ 0 件」と出る | **採用** | `bulkHtml()` は「**選んだ行はありません**」（数ではなく状態を言う）＋ `gui_layout` に「`選んだ 0 件` と書かない」検査 |
| D-3 | `GET /api/deletions/advance` の 404 は GUI の静的マウント。GUI 無しだと 405 でテストが落ちる | **採用** | `tests/test_deletions_advance.py` は **404 か 405** を許し、**口そのものは `openapi()` の経路**で見る |
| D-4 | `_unadvance()` が `from_path = NULL` に戻す（実データの段 1 は元から NULL） | **変更なし**（確かめた結果、問題なし） | — |
| D-5 | `KeyboardInterrupt` でも段 1 に戻る／戻すが `recovered` で拾う | **変更なし** | — |
| D-6 | `cross_volume` の後に空の `trash/` を残さない・`target_exists` で既存を触らない | **変更なし** | — |
| D-7 | 段 2 の行の `close` は 200 で、ゴミ箱の一覧から消える | **変更なし**（`_files_of_row` の `to_path` の扱いは変えていない） | — |
| D-8 | `ids` の形・`reason` 無し・無い id の 404 | **変更なし** | — |
| D-9 | `tools/gui_layout.mjs` の `WANT_STAGE[2]` は**並行の担当が直した** | **変更なし**（今回も `--screen pending --ids` が 4 幅 ok） | — |
| D-10 | `--screen tags` の NG は前提（`tag` 0 行） | **変更なし**（`gui_layout_seed.py --tags` を当ててから 4 幅 ok を再確認） | — |
| D-11 | 閉じた行の `closeable: false` / `undoable: false` / `state: closed` | **変更なし** | — |
| D-12 | 片付けの速さ（194 件 61 ms） | **変更なし**（複製で 1 回のまとめてが 200 で返る） | — |
| E-1 | §1.2 の合格の線が無い（監査が §E-0 に 10 本置いた） | **採用**（記録として） | §E-0 の 10 本を**そのまま使い**、`deletions-advance.md` §4 の 14 件と合わせて**再実行した**（§検証-4）。**P10 の設計書は無い**（記録が正）ので、線は記録側に置いた |
| E-2 | 実装者が決めた 8 点の判定（1〜8） | **採用** | 1・2・3・7・8 は妥当（変更なし）。**4（close は段を問わない）は C-3 で条件を満たした**。**5（片付けた後は戻せない）は A-3 で出口を作った**。**6（`advance` は台帳の `asset_id` を見ない）は A-1 で照合を足した** |
| E-3 | 記録の「別のファイルを移さない守りは `(size, mtime_ns)` の照合が持つ」は**誤り** | **採用（記録を直した）** | [`deletions-advance.md`](deletions-advance.md) §7 に**誤りと正**を書いた（§3-1 の文は残す＝歴史） |
| E-4 | 申し送り 2・3（`WANT_STAGE[2]` / `--screen tags`） | **変更なし**（どちらも並行の担当と前提で解決済み） | — |
| F | **壊し試験 32 通りのうち落ちない 4 のうち 3 がテストの穴**（A1 の形・A3・A14）＋画面の二度押し・台帳の `size` の照合 | **採用（テストを足した）** | `tests/test_deletions_advance.py` に 7 件（A-1・A-2・A-3×2・A3・A14・B-2/D-1）＋ `gui_smoke` に 11 件。**壊すと落ちることを 23 通りの変異で確かめた**（§検証-6） |
| G-1 | 古い `asset_id` の 6 行は (a) 断って `close` で終われる形に | **推奨どおり (a)** | A-1・C-1 |
| G-2 | 片付けた後の出口は (a) 閉じた行を数えない＋走査が引き直す（(b) も追加可） | **推奨どおり (a)＋(b)** | A-3 |
| G-3 | まとめて・`close` も記録に残す（(a) 1 呼び出し 1 行） | **推奨どおり (a)** | B-2 |
| G-4 | 閉じた段 3 の行は (a) `purge_at`/`remaining_sec` を NULL に | **推奨どおり (a)** | C-3 |
| G-5 | 不安定なテストは (a) P10 の修正と一緒に直す | **既に直っていた**（別件として先に。C-2） | — |
| H | 確かめられなかったこと（8790 が接続拒否・実データに列を足す起動は複製で） | **変更なし** | 今回も**実データには列を足していない**（16 列のまま。§検証-5） |

**残した物（理由つき）**: 上の「変更なし」の 8 件（D-4〜D-8・D-11・D-12・E-4）。**どれも「確かめた結果、
問題なし」**か**前提**（並行の担当・データの前提）で、直す所が無い。
**唯一の見送り**: 監査 F の「テストの穴」のうち **`_restore()` の `from_path`（A4）** は
**等価に近い**（`from_path` は段 2・3 で `path` と同じ値・段 1 は NULL で、`path` を先に見るため実害が無い）と
監査自身が判定しているので、**検査を足していない**（足すなら「段 3 の `from_path` だけが在る形」を作る必要がある）。

---

## 1. A-1（**利用者のファイルを壊し得る穴**）

**直す前**: `_require_file_for_advance()` は**現在の登録の `(size, mtime_ns)`** としか比べておらず、
**台帳の `deletion_log.size`** も**台帳の枚と現在の枚の違い**も見ていなかった。実データの 6 行は
台帳の `size` 1,487,627〜1,763,619 に対し**現在のファイルは 1,779,251〜1,880,986**（別の画像 Y）で、
`asset_location.asset_id` も Y。**advance は Y のファイルをゴミ箱へ移し、Y を一覧から消していた**。

**直した後**（`_require_file_for_advance()`）:

1. ファイルが無ければ **409 `missing_file`**（「ファイルが無いので片付ける」を案内）＝今までどおり
2. **（新）台帳の `size` と、いまその場所を登録している枚（`asset_location.asset_id`）を照合**。
   合わなければ **409 `different_file`**（「**消した画像はもうこの場所に無く、別の画像があります。
   「ファイルが無いので片付ける」で、この行を終わりにできます**」）
3. 現在の登録の `(size, mtime_ns)` と違えば **409 `changed`**＝今までどおり

**`close` 側**（`_files_of_row()`）は「在る」ではなく「**この行の画像が在る**」を見る:

- **登録の場所・台帳の鍵・元の場所**は、**`asset_location.asset_id` が台帳の枚と同じ**で、
  **実体の大きさが台帳の `size` と一致する**ときだけ数える（`size` が NULL の古い行は数えない）
- **`to_path` / `hold_path`** は**1 回の削除に固有**の場所（このツールが自分で移した先）なので、
  **在れば数える**（自分の置き場にファイルが残っている間は片付けない）

**実データと同じ形での結果**（複製 45/45 ok。§検証-4）: 6 行とも **409 `different_file`**・
**Y のファイルは 6 枚とも同じ大きさ・同じ mtime**・**Y の `deleted_at` は NULL のまま**（一覧に見える）。
そのうえで **194 件をまとめて片付けると 193 件が閉じ、1 件だけ `file_found`**（その 1 件は「移す」で進む）。

## 2. A-2（戻したのに別の枚が永久に消える）

**直す前**: 印を**立てる**のは `advance` / `delete`（＝**いまの登録**）なのに、**消す**のは `_restore()`
（＝**台帳の枚 X だけ**）だった。実体は元の場所に戻り `missing_at` も NULL なのに、**Y の `deleted_at` が
立ったまま**＝Y はカタログから永久に消える（`undo` は `already_restored`、走査は `missing_at` しか戻さない）。

**直した後**: `_sync_hidden_with_location(con, row, loc, at=)` が**両方**を引き直す
（`_restore()` と `_mark_recovered()` の両方から呼ぶ）。**A-1 を直すとこの道は塞がるが、二重の守り**として残した。

## 3. A-3（片付けた行の出口）

**直す前**: `_should_hide()` と `_live_stage1()` が**閉じた行も数えて**いたので、①ファイルが戻っても
`deleted_at` が立ったまま（走査は `missing_at` しか戻さない）②段 1 で消し直しても `replayed: true` に
なって**同じ閉じた行**が返り、`undo` は 409 のまま。

**直した後**（監査の推奨 (a)＋(b)）:

1. **規則は 1 か所**（`deletions.should_hide()` / `sync_hidden()`。サービスの `_sync_hidden` /
   `_should_hide` は委譲）。**閉じた行（`closed_at`）は隠す理由に数えない**——実体が無い間は
   `live == 0` で隠れたまま＝**幽霊は戻らない**
2. **`scan.py` が印を引き直す**。拾うのは 2 つの形（①`missing_at` を戻した枚 ②**ファイルが在り登録も
   生きているのに隠れている枚**）。②は**段 1 がファイルを動かさない**ので必要（`missing_at` が
   立っていないことがある。監査の再現がこの形）。`store.location_of()` に `a.deleted_at` を 1 列足した
3. **走査の前でも `undo` が開き直す**（監査 G-2 の (b)）。条件は「**段 1**・**登録が生きていて台帳の枚と
   同じ**・**実体が在り大きさも台帳と一致**」の 3 つ。ファイルも登録も触らない（`closed_at` を外すだけ）

## 4. B・C・D

- **B-1**: 3 つの関数に `busy`。**`await` の前に立てる**ので 2 回目の押下はその場で止まる。
  `gui_smoke` に「2 連打で POST 1 回」（1 行の移す・まとめて移す・まとめて片付ける・1 行の片付け）と
  「確認も 1 回だけ」を足した（**11 件**）。
- **B-2**: `_run_many()` が `_open_request` → 1 件ずつ → `_close_request`（`count` = requested、
  `result_json` に `skipped` も）。`close()` も 1 行。**単発・まとめて・`close` の 4 口すべてで残る**。
  実データの複製で `kind: close_many` / `count: 194` / `stage: 1` / `result_json` に `file_found` を確認。
- **C-3**: `close` の UPDATE に `purge_at = NULL, remaining_sec = NULL` を足した。複製で
  段 3 の行を片付けた後 `tick()` の `decremented` が 0 になることを確認（pytest）。
- **D-1**: `replayed_count`（API）＋「N 件は既に片付けていました。」（画面）。**`count` の意味は変えていない**
  （既存のテスト `test_many_does_not_silently_drop_failures` が正としている）。
- **D-2**: 「選んだ行はありません」。`frontend-design.md` §6 と `gui_layout` の検査も合わせた。
- **D-3**: 404/405 の両方を許し、口の存在は `openapi()` の経路で見る。

## 5. 文言（**正を先に直してから実装**）

`docs/frontend-design.md` §4.6・§6 を先に直した（家風）。直した行:

| 何 | 直した文 |
| --- | --- |
| 段 1 の行のボタン（A-1） | 「**消した画像はもうこの場所に無く、別の画像があります。「ファイルが無いので片付ける」で、この行を終わりにできます。**」 |
| 片付けの断り（A-1/C-1） | 「**この行のファイル**がまだ在る」と読む（別の画像は数えない） |
| まとめての帯（D-2） | 「**選んだ行はありません**」（0 のとき数ではなく状態を言う） |
| 片付けた後（D-1） | 「**N 件を片付けました。**」＋「**M 件は既に片付けていました。**」 |
| 片付けた行（A-3） | 「**ファイルが戻ってくれば戻せる**」（走査で一覧に戻る・走査の前でも「戻す」で開き直せる） |

画面の語に**英語の内部値・`code`・「実体」・「用意」**を出していない（§6.1 の規約 1〜6）。
**新しい断り `different_file` の語は `SKIP_TEXT` に足した**（「別の画像があります」）。

## 6. 検証（すべて実行した値）

| 何 | 結果 |
| --- | --- |
| `uv run --no-sync pytest -q` | **554 passed × 3 回**（547 ＋ 新規 7。落ちていた 1 件は C-2 として先に直っている） |
| `node tools/gui_smoke.mjs` | **406 ok / NG 0**（395 ＋ 新規 11） |
| `gui_layout`（**複製のサーバ 8811**、\(10 画面＋削除の確認\) × 4 幅） | **すべて ok**（compare8 12・requests/group/asset/jobs/duplicates/pending/library/settings/pending-ids 各 4）。**`--screen tags` だけ 4 件 NG → `gui_layout_seed.py --tags` を当てて 4 幅 ok**（監査 D-10 の前提） |
| 複製のサーバで通した線（`.tmp-audit-redo/p10-fix/verify_http.py`） | **45 / 45 ok**（下の表） |
| 壊し試験（`.tmp-audit-redo/p10-fix/mutate_fix.py`） | **変異 21 通り（Python 16・JS 5）＋素の実行 2 つがすべて期待どおり**（下の表） |
| 実データ | **監査の baseline（13:45）と 1 つも変わっていない**（下の表） |

### 6-1. 複製で通した線（45 件。実データと同じ形）

| # | 線 | 値 |
| --- | --- | --- |
| 1 | 段 1 の生きた行・実体なし・**別の画像が在る**・その行の画像が在る | **194 / 187 / 6 / 1** |
| 2 | **古い `asset_id` の 6 行の advance** | **6 行とも 409 `different_file`**・断りの文に「片付ける」 |
| 3 | **Y のファイル** | **6 枚とも同じ大きさ・同じ mtime**（1 枚も動かない） |
| 4 | **Y の `deleted_at`** | **NULL のまま**（一覧に見えている） |
| 5 | まとめて片付ける（194 件を 1 回） | **193 件が閉じ・1 件だけ `file_found`**（6 行も閉じた＝C-1） |
| 6 | 片付けの副作用 | ファイルの署名が同じ・`asset` 461 / `asset_location` 455 のまま・**`asset.deleted_at` 461 件が全部同じ** |
| 7 | **B-2** | `delete_request` が +1（`kind: close_many`・`count: 194`・`stage: 1`・`result_json` に `file_found`） |
| 8 | **D-1** | 再送は `count: 193` / **`replayed_count: 193`** / `skipped_count: 1` |
| 9 | 残った 1 行の advance → undo | 200 → ゴミ箱へ移る → 200 で戻り、`deleted_at` が外れる |
| 10 | **A-3（走査）** | 段 1 で外す → ファイルを外へ → `close` 200 → **戻す → `POST /api/scan` → `deleted_at` NULL**（一覧に戻る） |
| 11 | **A-3 (b)（走査の前の undo）** | 200 で `restored: true`・`closed_at` が外れる・一覧に見える |
| 12 | **幽霊を戻さない** | 実体が無いまま `undo` → **409 `already_closed`** |
| 13 | **C-3** | 段 3 の行を片付けると `purge_at` / `remaining_sec` が NULL・台帳は `state: closed` |

複製は `mk_replica.py`（`backup()` ＋ `copy2` ＋ **パスの貼り替え**）で作った
（**1,114 のパス値が複製の外を指していない**ことを確かめてから使った）。
**相対パスで作ると台帳の鍵が相対のままになり `not_registered` になる**（最初に踏んだ。
**絶対パスで作る**こと——監査の記録には書かれていない罠なので申し送る）。

### 6-2. 壊し試験（**ソースは触らず**、`src/image_reviewer` の複製を `PYTHONPATH` で前に置く）

`image_reviewer.__file__` が複製を指すことを毎回確かめている。**素の実行（壊さない）は 34 passed**、
**JS の素の実行は 406 ok / NG 0**。**#2・#3 は「落ちないのが正」**と判定した（下の注記）。

| # | 壊した所 | 結果 |
| --- | --- | --- |
| 1 | A-1 台帳の行が指す物かの照合を外す | **落ちた** |
| 2 | A-1/C-1 `_files_of_row` が別の画像を数える | 落ちない（**もう一方の守りが効く**＝等価な変異） |
| 3 | A-1/C-1 `_files_of_row` の大きさの照合を外す | 落ちない（**同上**） |
| 4 | A-1/C-1 **2 つの守りを両方外す** | **落ちた**（＝テストは両方を見ている） |
| 5 | A-2 戻すときにいまの登録の印を引き直さない | **落ちた** |
| 6 | A-3 走査で印を引き直さない | **落ちた** |
| 7 | A-3 `_should_hide` が閉じた行を数える | **落ちた** |
| 8 | A-3 `_live_stage1` が閉じた行を数える | **落ちた** |
| 9 | A-3 ファイルが戻っても開き直さない | **落ちた** |
| 10 | F(A3) 一時置き場を見ない | **落ちた** |
| 11 | F(A14) 片付けた行の advance を断らない | **落ちた** |
| 12 | C-3 片付けた段 3 の行をタイマーから外さない | **落ちた** |
| 13 | B-2 まとめての要求を記録しない | **落ちた** |
| 14 | B-2 単発の片付けを記録しない | **落ちた** |
| 15 | B-2 要求の段をいつも 1 にする | **落ちた** |
| 16 | D-1 `replayed_count` を返さない | **落ちた** |
| 17 | （JS）B-1 1 行の「移す」の `busy` を外す | **落ちた**（POST 2 回） |
| 18 | （JS）B-1 まとめての `busy` を外す | **落ちた**（POST 2 回・確認 2 回） |
| 19 | （JS）B-1 1 行の「片付ける」の `busy` を外す | **落ちた**（POST 2 回・確認 2 回） |
| 20 | （JS）D-2「選んだ 0 件」と書く | **落ちた** |
| 21 | （JS）D-1 既に片付いていた数を言わない | **落ちた** |

**最初の 1 回で 2 件落ちなかった**（#2・#3）。**どちらも「もう一方の守り」が効くため**で、穴ではなかった
（**両方外すと落ちる**＝#4）。**この 2 件を「落ちた」と数えない**のが正しい数え方である
（監査 F が「落ちない変異は等価変異かテストの穴かを 1 つずつ判定する」と決めているのと同じ）。

### 6-3. 実データが無傷（監査の baseline と突き合わせ）

`.data` は `mode=ro`、画像は読むだけ。**監査の `baseline-end.json`（13:45）と 1 つも変わっていない**:

| 見た物 | 監査（13:45） | いま |
| --- | --- | --- |
| `.data` のファイル数 / 合計 / 署名（DB を除く） | 675 / 22,718,758 B / `8064f625…` | **同じ** |
| `db.sqlite3` / `-wal` の mtime・大きさ | 1792369374153323900 / 3301376・1792369846952189000 / 4190072 | **同じ**（`-shm` の mtime だけ動く＝読み取りの副作用） |
| `db` の中身 | `user_version 6`・`data_version 2`・`asset 461`・`decision 3`・`deletion_log 194`（**全部段 1**）・**列 16**（`closed_at` は無い）・`asset_location 455`・`missing 187`・`tag 0`・`asset_tag 0`・`delete_request 32` | **同じ** |
| 画像（2 つの置き場） | 318 ファイル / 303,256,170 B / `33b2c6e1…` | **同じ** |
| `.backup/daily` の 3 世代 | `20261018` / `20261018-171143` / `20261019` の署名 | **同じ** |

**実データには列を 1 つも足していない**（`closed_at` / `close_reason` はまだ無い＝**利用者がアプリを
立ち上げ直した時点**で `pre-topup-<日時>/` の控えが付いてから足される）。

---

## 7. 触ったファイル（行数。`git diff --numstat`）

| ファイル | +/- | 中身 |
| --- | --- | --- |
| `src/image_reviewer/deletions.py` | +289 / −67 | `should_hide()` / `sync_hidden()` を**モジュールの関数**に（走査から呼べるように）・A-1（`_require_file_for_advance` / `_files_of_row`）・A-2（`_sync_hidden_with_location`）・A-3（`_live_stage1` / `_restore` / `_reopen_closed_row` / `_row_image_is_back`）・B-2（`_run_many` / `close` / `_request_stage_for`）・C-3・D-1（`replayed_count`） |
| `src/image_reviewer/scan.py` | +26 / −1 | **ファイルが戻った枚の印を引き直す**（2 つの形を拾う。規則は `sync_hidden` の 1 か所） |
| `src/image_reviewer/store.py` | +5 / −1 | `location_of()` が `asset.deleted_at` も返す（1 列） |
| `src/image_reviewer/api/deletions.py` | +16 / −7 | 4 つの口の docstring（`different_file`・「この行のファイル」・C-3・B-2） |
| `apps/gui/pending.js` | +108 / −60 | B-1（`busy`）・D-1（`closeDoneText(count, replayed)`）・D-2（「選んだ行はありません」）・`SKIP_TEXT.different_file` |
| `tools/gui_smoke.mjs` | +88 / −0 | **2 連打で POST 1 回**（4 通り）・確認 1 回・D-1・D-2・`different_file` の語＝**11 件** |
| `tools/gui_layout.mjs` | +4 / −0 | 「`選んだ 0 件` と書かない」（D-2） |
| `tests/test_deletions_advance.py` | +308 / −20 | A-1（書き換え）・A-2・A-3×2・F の穴 2 件・B-2/D-1・C-3・D-3 |
| `docs/design.md` | +84 / −24 | §5.8・§6.1（`undo` / `advance` / `close`）・**§16.7 に「P10 の監査で確定したこと」11 行**・実データの数の訂正（187/7 → **193/1**） |
| `docs/frontend-design.md` | +17 / −6 | §4.6・§6（§5 の表。**先に直してから実装**） |
| `README.md` | +14 / −5 | 文書表 2 行（監査報告・仕分け）と「次にすること」の P10 の段落 |
| `docs/deletions-advance.md` | （追記） | **§7「監査の指摘で直したこと」**（§3-1 の誤りの訂正を含む） |
| `docs/p10-audit-triage.md` | 新規 | 本文書 |

**触っていない物**: `docs/p10-audit-report.md`（監査の報告。**書き換えていない**）・
`.tmp-audit-redo/p10-audit/`（監査の道具と複製）・`docs/stuck-reason-fix.md`・`tests/test_deletions.py`
（C-2 は既に直っていた）・`tools/probe_deletions_advance.py`・`src/image_reviewer/db.py`
（**版も表も変えていない**＝`closed_at` は P10 で足したまま）。**git のコミットはしていない。**

---

## 8. 申し送り

1. **利用者のアプリ（8790）は止まったまま**（今回も listen していない。**立てていない**）。
   新しい規則は**再起動後**に効く（`pre-topup-<日時>/` の控えが付いてから列が足される）。
   **押す順**: 「まとめて片付ける」→ **193 件が閉じ、1 件だけ断られる** → その 1 件を
   「アプリのゴミ箱へ移す」（**別の画像 6 枚は動かない**）。
2. **複製を相対パスで作ると `not_registered` になる**（`mk_replica.py` の `--work` は**絶対パス**で渡す。
   `normalize_path()` は `realpath` なので、DB に相対の鍵が入ると一致しない）。**最初に踏んだ罠**。
3. **`--screen tags` は `gui_layout_seed.py --data <複製>/data --tags` を先に当てる**
   （`--data` は **`db.sqlite3` のあるフォルダ**。`<複製>` を渡すと「db.sqlite3 がありません」で断られる）。
4. 残した物: `.tmp-audit-redo/p10-fix/`（複製 2 つ＝rep / rep2・`mut/`・検査と壊し試験のスクリプトとログ）。
   **複製サーバ（8811）は検証の最後に止める**（`/api/health` の `data_dir` を確かめてから）。
   `%USERPROFILE%` の下には何も作っていない。
5. **`docs/design.md` の §16.7 に行を 11 本足した**（監査の指摘は「設計に書き戻す」のが家風）。
   §6.1 の口の表も直した。**`p10-design.md` は無い**（`deletions-advance.md` が P10 の正）ので、
   合格の線は監査の §E-0 の 10 本を記録側に置いたままにした。
