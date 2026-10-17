# P8-3（重複と削除の画面）の実装の記録

- 日付: 2026-10-18（JST 03:45〜05:10）
- 指示書: [`p8-3-implementation-brief.md`](p8-3-implementation-brief.md)（55 行）
- 正: [`p8-design.md`](p8-design.md) §0.13 / §0.14 / §3.1〜§3.4 / §4.1〜§4.3 / §5、[`frontend-design.md`](frontend-design.md) §3・§4.6・§6・§11
- 触った物（行数は実測）: 下の「1. 作ったもの」。**`README.md` と `docs/design.md` は触っていない**。
- 実データ: `.data/` は **`mode=ro` でしか開いていない**（複製は `sqlite3` の `backup()`）。**画像は 1 枚も動かしていない・消していない**（§6 の署名で確認）。`git` のコミットはしていない。

---

## 1. 作ったもの（ファイルと行数）

| ファイル | 行数 | 何をしたか |
| --- | --- | --- |
| `src/image_reviewer/deletions.py` | 1614（+87/-9） | **D-1**（`_drop_request` を「台帳が参照していなければ消す」に。`_replay` の D-8 の巻き取りも同じ関数を通す）・**D-2**（`_original_state` を新設して `missing`/`same`/`different` に分け、`different` は `stuck` にして「戻した」ことにしない。使わなくなった `_original_exists` は消した＝**デッドコードを残さない**） |
| `tests/test_deletions.py` | 1907（+90） | D-1・D-2 の試験 3 本（**どれも「壊すと落ちる」形**） |
| `apps/gui/duplicates.js` | **446（新規）** | `#/duplicates`。群の一覧（距離の小さい順）・しきい値 ≤3/≤6/≤10・おすすめと理由・残す 1 枚の選択・まとまりにする・別物として確定と解除・未計算と「計算する」（背景ジョブの進行と中断）・削除へ回す |
| `apps/gui/pending.js` | **495（新規）** | `#/pending-deletes`。削除の確認（段 1/2/3・凍結した一覧・`frees`・最後の 1 つ）・3 段階の進行・残り時間（毎秒は見た目だけ）・取り消す／別名で戻す／いま消す・戻せませんでした・拾い物・ゴミ箱と復帰・誰が消したか |
| `apps/gui/index.html` | 277（+57） | 2 画面の器と、上部バーの入口 `#stat-deletes`（`最近の削除 3 ・ あと 3:12`） |
| `apps/gui/app.js` | 494（+49） | 道（`#/duplicates` / `#/pending-deletes`）と配線、`← 一覧` |
| `apps/gui/badge.js` | 177（+36） | 上部バーの「最近の削除」（5 秒ごと。**読むだけ**。取り消せる削除が 0 なら出さない） |
| `apps/gui/styles.css` | 808（+162） | 2 画面の見た目（**影・角丸・カードを使わない**。既存のトークンだけ） |
| `tools/gui_smoke.mjs` | 1292（+390） | **押す検査** 76 件（本物の委譲の聞き手を叩く。`fetch` は飲む） |
| `tools/gui_layout.mjs` | 1032（+362） | `--screen duplicates` / `--screen pending`（本物の Chrome・3 窓・**押して POST の回数を見る**） |
| `docs/frontend-design.md` | 925（+36） | **先に文言**（§6 に 20 行・§11 に 11 行）＋ §4.6 の「起動後に窓が切れた分を消す」を §0.6-3 に合わせて直した（点検 B5） |
| `docs/p8-design.md` | 997（+1/-1） | **E-3**（§3.2 の `undo` の行に「段 1〜3 の全部に効く（段 2 は `trash/restore` と同じ道）」＋ D-2 の 409 を 1 行） |
| `docs/p8-2-audit-recheck-triage.md` | **37（新規）** | 再確認の軽微 2 件＋設計 1 行の仕分け（全部採用） |

一時物（消してよい）: `.tmp-audit-redo/p8-3/`（`setup_copy.py` 119 行・`roundtrip.py` 376 行・`make_views.py` 96 行・`real_state.py`・`counts.py`・複製 `srv/`・画像の複製 `lib/` 11 枚・`srv-out.log`・`regression.log`）、`.tmp-audit-redo/p8-3-fix/`（`mutants.py`）、`.tmp-audit-redo/shots-p8-3/`（画面写真 4 枚）。

## 2. 実行したコマンドと結果

```
$env:UV_CACHE_DIR = "C:\work\image-reviwer\.uv-cache"（毎回）
uv run --no-sync pytest -q -p no:cacheprovider     → 403 passed（19.62 s / 19.46 s。**2 回**）
node tools/gui_smoke.mjs                            → すべて ok（**205 件**。前は 129 件）
node tools/gui_layout.mjs --base http://127.0.0.1:8791 --count 8                    → すべて ok（3 窓）
node tools/gui_layout.mjs --base http://127.0.0.1:8791 --screen requests            → すべて ok
node tools/gui_layout.mjs --base http://127.0.0.1:8791 --screen tags                → すべて ok（rows=155）
node tools/gui_layout.mjs --base http://127.0.0.1:8791 --screen jobs                → すべて ok
node tools/gui_layout.mjs --base http://127.0.0.1:8791 --screen group --group <id>  → すべて ok
node tools/gui_layout.mjs --base http://127.0.0.1:8791 --screen asset --ids <id>    → すべて ok
node tools/gui_layout.mjs --base http://127.0.0.1:8791 --screen duplicates          → すべて ok（3 窓）
node tools/gui_layout.mjs --base http://127.0.0.1:8791 --screen pending [--ids a,b] → すべて ok（3 窓）
```

- **pytest は 400 → 403 件**（足したのは D-1・D-2 の 3 本）。**既存は 1 件も落ちていない**。
- **`gui_layout` は 6 画面 → 8 画面**（`duplicates` と `pending` を足した）。**8 画面すべて ok・各 3 窓**。
- `gui_smoke` は 129 → 205 件。落ちた検査は無し。
- **8 画面は 2 回回した**（`regression.log` は最初、`regression2.log` は**デッドコード（`_original_exists`）を
  消した後**。どちらも 8 画面すべて ok。pytest 403・`gui_smoke` 205 もその後で回し直した）。

### 実物の往復（複製のサーバで）

```
.venv\Scripts\python.exe -X utf8 .tmp-audit-redo\p8-3\setup_copy.py      # 複製（DB は backup()・画像は copy2）
（IMAGE_REVIEWER_DATA=<複製> を付けて 8791 で uvicorn を起動）
.venv\Scripts\python.exe -X utf8 .tmp-audit-redo\p8-3\roundtrip.py       → **41 項目 ok / 0 項目 NG**
```

`roundtrip.py` が HTTP で通した線（抜粋）:

| 線 | 結果 |
| --- | --- |
| 健康（**複製に立っているか**。`data_dir` を突き合わせる） | 200・`srv` を指す |
| 重複を見る（`GET /api/duplicates/near`） | 200・**21 群**・並びは距離の小さい順 `[0,2,2,2,2]`・`unhashed 0` |
| 選ぶ（`POST /api/groups` `kind='duplicates'`） | 200・id が返る |
| 除外と解除（`POST /api/duplicates/exclude` → `remove`） | 200 / 200 |
| 背景ジョブ（`POST /api/duplicates/compute` `force`） | **202** → `GET /api/jobs/{id}` が `done`（263 / 263 枚） |
| 段 1（`POST /api/locations/delete`） | 200・**ファイルは動かない**・`frees.bytes 0`・`undo` で戻る |
| 段 2（凍結 → `bulk-delete`） | 200・ゴミ箱へ（`20261018`）・`POST /api/trash/restore` で戻る |
| 段 3 → **取り消す** | 200・`remaining_sec 300` → `undo` 200・`missing_at` が消える |
| 段 3 → 埋まっていれば**止めて尋ねる** → **別名で戻す** | 409 `target_exists` → `as_copy: true` で 200（`…175.1.png`） |
| 段 3 → **いま消す**（`POST /api/deletions/{id}/purge`） | 200・保留の実体が消える・一覧から外れる |
| **D-2 の実物**（保留が外から消え、元の場所に別の物） | `undo` が **409 `restore_failed`**・`stuck` のまま |
| 拾い物（`found_count`） | 1 |
| **`GET` が書かない**（複製の全ファイルと全表・`remaining_sec` も見る） | 前後で同じ（`4d8e0d…` / `a16e0a…`） |
| `GET` は残り時間を減らさない（2 秒あけて 2 回） | 300 → 300 |
| **実データが無傷**（`.data` の DB・画像の `(size, mtime_ns)` の署名） | 前後で同じ（`24962e…`） |

### D-1 / D-2 / E-3 を直した結果（**壊すと落ちる**）

`.venv\Scripts\python.exe -X utf8 .tmp-audit-redo\p8-3-fix\mutants.py` → **4 通り中 4 通りが落ちた**（前後で
`deletions.py` の sha256 が一致＝**`df48b46d8c8c1bd4`**。デッドコードを消す前は `4e51d91aaf910090` で、
どちらでも 4 / 4 が落ちる）:

| 壊し方 | 落ちる試験 |
| --- | --- |
| D-1: 台帳が参照していても消す（元の形） | `test_a_failure_after_the_move_keeps_the_original_error`（上がる例外が `IntegrityError` になり、`RuntimeError` が隠れる） |
| D-2: 中身を見ない（元の形） | `test_a_different_file_at_the_original_place_is_not_recovered` |
| D-2: 窓切れの道だけ中身を見ない | 同上 |
| D-2: 取り消しの道だけ中身を見ない | `test_undo_refuses_when_the_original_place_holds_another_file` |

- **E-3**: `docs/p8-design.md` §3.2 の `undo` の行に 1 行足した（**エージェントが自分の段 2 を `undo` で戻せる**＝
  `trash/restore` と同じ道。あちらは人だけ）。実装は変えていない（HTTP で 200 を確認済み＝再確認 E-3 の再現）。
- **仕分け**: [`p8-2-audit-recheck-triage.md`](p8-2-audit-recheck-triage.md)（**3 件とも採用**。D-3 の走査中の表示は下の「設計の穴」へ）。

## 3. 画面（何をどこに置いたか）

| 画面 | URL | 中身 |
| --- | --- | --- |
| 重複の整理 | `#/duplicates?max=6` | 完全重複の 1 行・未計算と「計算する」・候補の数・群（距離・おすすめと理由・サムネイル・寸法/サイズ/日時・パス・キープ/ボツの印）・残す 1 枚（ラジオ）・まとまりに入れる枚（チェック）・まとまりにする・別物として確定・除外の一覧と解除・下部バー（選択 N 枚を削除へ回す） |
| 最近の削除 | `#/pending-deletes` | 削除の確認（`?ids=` のときだけ）・凡例（1 印 → 2 ゴミ箱 → 3 実削除）・取り消せる削除の行（残り時間・段の印・パス・サイズ・誰が・`取り消す`／`別名で戻す`／`いま消す`）・戻せませんでしたの理由・拾い物・ゴミ箱（日付ごと・`戻す`） |
| 入口 | `#/jobs` の隣（上部バー） | `#stat-deletes` = `最近の削除 3 ・ あと 3:12`（**取り消せる削除が 0 なら出さない**）。押すと `#/pending-deletes` |

- 削除の確認は**モーダルではなく画面の中の段**（§5。P6-2 の教訓）。段の既定は **1**（いきなり実削除にしない）。
- `#/duplicates` からは**消さない**。`#/pending-deletes?ids=...` へ**渡すだけ**（段の選択と確認はあちら）。

## 4. 自分で決めた点（1 行ずつ理由）

1. **削除の確認を `#/pending-deletes` の中に置いた**（§5 は「一覧の選択から」としか書いていない）。指示書の「下の 3 へ渡す」をそのまま実装した形。
2. **凍結した一覧（パスとサイズ）は「消す物を確かめる」を押した後に出す**。`preview` が凍結した一覧そのものを返すので、押す前に出すには枚ごとの `GET` が要る（N 回の照会を避けた）。押す前はサムネイルと枚数だけ。
3. **段を変えたら凍結を捨てる**（§0.7 の「実行時に `scope` を評価し直さない」を守るため。段が違う凍結を使い回さない）。
4. **「最後の 1 つ」の重い確認は段 3 のときだけ**（§8.1 の 43。API と同じ規則）。
5. **`client_token` は押すたびに `crypto.randomUUID()`**（§0.13。二重に消さない）。
6. **「いま消す」は `window.confirm` を 1 回**（§5 の「確認必須」）。**人だけ**（403 は画面にも出る）。
7. **残り時間は毎秒「見た目だけ」書き換える**（`data-remain` の文字だけ。`GET` は書かない。§0.13）。
8. **`GET /api/pending-deletes` に人だと名乗るヘッダを付けた**（**画面の写真で見つけた穴**。`actor_of()` は
   ヘッダが無ければ `agent` を返すので、名乗らないと**人が消した物でも `undoable: false`** が返り、
   「取り消す」が消えていた。`gui_smoke` に「名乗っているか」の検査を足した）。
9. **台帳の `at` は現地の時刻で出す**（`fmtWhen`。サーバは UTC で持っているので、そのまま出すと
   利用者の時計と 9 時間ずれて見える。ゴミ箱の日付は既に JST）。
10. **凡例の段には印を付けない**（`stageStrip(null)`。行と見分けが付かなくなる。写真で気づいた）。
11. **除外の一覧の理由は文字として出す**（`esc`。実物で `<script>alert(1)</script>` を入れて `script=0` を確認）。
12. **しきい値の切り替えは URL に持つ**（`#/duplicates?max=6`。§11。戻る・再読込に耐える）。
13. **`gui_layout` の押す検査は「押すのと測るのを同じ評価の中で」**（描き直しと競合して除外の一覧を
    取りこぼした。押してから別の評価で測ると 0 行に見えることがあった）。
14. **`--screen pending` は `--ids` を渡すと削除の確認も押す**（凍結の応答は作り物を返すので**サーバに凍結は作られない**）。
15. **`mutants.py` は毎回 `deletions.*.pyc` を消してから回す**（CPython の無効化は「mtime（秒）＋大きさ」なので、
    同じ秒に書いた**大きさの同じ**別の壊し方で古い pyc が使われ、**嘘の「通ってしまった」**が出た）。
16. **`_replay` の D-8 の巻き取りも `_drop_request` を通し、台帳が参照していて消せないときは 409 `client_token_in_progress`**。
    黙って再送を通すと**二重に消す**ため（外部キーで 500 にしない）。

## 5. 申し送り

1. **トレイの入口（§4.6 の (c)）は作っていない。** このリポジトリに**常駐（タスクトレイ）の実装が無い**
   （`tray` を探しても 0 件。`image-reviewer.exe serve` はブラウザで開くだけ）。いまの入口は
   **(a) 画面**と **(b) 上部バー**の 2 つで、**`#/jobs` の隣に 4 つ目は作っていない**（点検 B5）。
   `frontend-design.md` §11 にその 1 行を足した。常駐を作る段で (c) を足すこと。
2. **`allow_stage3` の印を付ける口（`POST /api/roots/{id}/allow-stage3`）は P8-4 のまま**（設計 §3.3 の E-5）。
   画面は**印の無い置き場では段 3 を出さない**ようにしていない（`bulk_preview` の `not_allowed_count` を
   1 行で出すだけ）。**段 3 を選べるかどうかは置き場ごとに違う**ので、段 3 を選んだときに
   `not_allowed` を強調する形にした（P8-4 で口ができたら「この置き場に印を付ける」を足す）。
3. **走査中の表示（G-3）は入れられなかった。** 走査中かどうかを外から見る材料が無い（`POST /api/scan` は job を持たず、
   `scan_guard` は錠なので**待つだけ**）。§3.4 の字義どおり「押した要求が待つ」ままにしてある。
   画面に出すには `scan` の job 化が要る（P8-4 以降）。
4. **`--screen tags` は実データ（`tag=0`）では 0 行で NG になる。** これは P8-3 と無関係の**前からの物**で、
   複製で小さなタグ付け（4 枚）を回して `rows=155` にしてから回した（**実データの語は 0 のまま**）。
   実データで回す人への申し送り。
5. **実データの pHash は 263 / 263 枚そろっている**（設計 §7 の「未計算 172 枚」はもう古い）。
   だから「まだ計算していない枚が N 枚あります」は**実データでは出ない**（0 枚のときは出さない）。
   未計算の見た目は `gui_smoke` の作り物（`unhashed: 2`）で守っている。
6. **`frontend-design.md` §3 の画面一覧に `#/trash` は無い**が、`p8-design.md` §5 の表には「ゴミ箱／`#/trash`」がある。
   指示書（ゴミ箱の一覧と復帰は `#/pending-deletes` に置く）に従ったので、**`#/trash` という画面は作っていない**
   （口 `GET /api/trash` はそのまま）。§5 の表の直しを P8 の終わりに。

## 6. 設計の穴（気づいた点）

1. **段 1 の次に同じ枚で段 2 はできない**（段 1 は `asset.deleted_at` を立てるので、凍結の対象
   `_resolve_scope` から外れる）。§4.1 の表は「1 つの場所の状態」なので正しいが、**画面の「3 段階の進行」は
   枚ごとに別の道を通る**（1 枚が 1 → 2 → 3 と進むのではない）。利用者が「段 1 の枚を段 2 へ」と思ったとき、
   一覧（`include_deleted`）から拾い直す必要がある。**段 2 へ進める導線が無い**のは穴。
2. **`unhashed` は「`phash` が無い枚」だけを数えている**（帯が無い枚は数えない。`start_compute` の対象は帯の無い枚も入る）。
   実データでは差が出ないが、帯だけ欠けた DB では「計算する」が出ないのに計算対象がある、という形になりうる。
3. **`GET /api/pending-deletes` は `undoable`/`mine` を「読んだ人」で決める**のに、**画面が名乗らないと
   エージェント扱い**になる（今回の穴 8）。API の既定（無ければ `agent`）は判断の口には正しいが、
   **読むだけの口では「人かどうか」で見え方が変わる**ので、画面側の作法（GET でも名乗る）を
   どこかに書いておくほうがよい（`frontend-design.md` §10 の実装の約束に 1 行）。
4. **`found`（拾い物）は `pending` を取るたびに `rglob` する**（P8-2 の D-4）。行が増えると `GET` が重くなる。
5. **段 2 の行は「取り消す」では戻せない**（`undo` は段 1〜3 に効くが、`pending`（段 3 の一覧）には出ないので
   ゴミ箱の「戻す」から入る）。§3.2 の `undo` の行に「段 2 も」と書いたが、**画面の導線はゴミ箱側**にある。

## 7. 後始末

- 残した物: `.tmp-audit-redo/p8-3/`（複製 `srv/`・画像の複製 `lib/` 11 枚・スクリプト 5 本・ログ）と
  `.tmp-audit-redo/p8-3-fix/mutants.py`、`.tmp-audit-redo/shots-p8-3/`（写真 4 枚）。**消してよい**。
  複製のサーバは **8791**（`IMAGE_REVIEWER_DATA` を付けて起動。**止めたことを netstat で確認**）。
- **8790（利用者のアプリ）は止めていない・触っていない**。ComfyUI も触っていない。`.backup/` は消していない。
- 作業の途中で `git status` に**空の一時ファイル 2 つ**（`tmps_tc7_u8`・`tmpuve78iq9`。untracked）が現れたが、
  確かめたときには**既に無かった**（`uv` か pytest の一時物。**私は消していない**。0 バイトだったことは確認した）。
- 写真（`.tmp-audit-redo/shots-p8-3/`）: `01-duplicates.png`（重複の候補 ≤ 6）・`02-pending.png`（取り消す・
  戻せませんでした・拾い物・ゴミ箱）・`03-pending-confirm.png`（削除の確認・段の選択）・`04-library-entry.png`
  （上部バーの入口）。**P8-4 の監査で使う。**
