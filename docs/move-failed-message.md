# 移動できなかったときの案内（利用者の依頼）

> **一言**: 権限で断られた移動の文が**技術的な 1 行**（`ファイルを移動できません: [WinError 5] …: '元' -> '先'`）で、
> 利用者は**次に何をすればよいか分からなかった**。**通る道**（エクスプローラで消してから「ファイルが無いので片付ける」）を
> **2 文**で案内する。**`code` は `move_failed` のまま**（呼び出し側と検査を壊さない）。
>
> **前提（この環境の制約）**: **アプリのプロセス（`python.exe`）は `C:\work\image-reviwer` の外に書けない**
> （`os.rename` が `WinError 5`。**同じユーザーのシェルや cmd は書ける**＝ファイル権限ではなく環境がプロセスに掛けている制限。
> [`design.md`](design.md) §16.7 の末尾・[`../README.md`](../README.md) の「この環境の制約」）。
> そのため **`C:\work\illust-authoring\...` のファイルをアプリのゴミ箱へ移すと必ず失敗**する。
> **通る道**は「**利用者がエクスプローラで消してから「ファイルが無いので片付ける」**」——アプリは外に書かないので必ず通る。

## 1. 直す前 → 直した後

**直す前**（実物。段 2 の削除で、実データの置き場のファイルを移そうとした形）:

```
ファイルを移動できません: [WinError 5] アクセスが拒否されました。: 'C:\work\illust-authoring\.store\anima-dev\images\x.png' -> 'C:\work\image-reviwer\.data\trash\20261019\<id>\x.png'
```

- 何が起きたかは分かるが、**どうすればよいかが無い**。**両方のパス**が本文に出るので、画面では読めない 1 行になる。
- 画面はこの文字列を**そのまま**出す（`apps/gui/pending.js` は `body.detail` を表示する）。

**直した後**（実測。`deletions.move_failed_detail()` の戻り値）:

```
このファイルは移動できませんでした。ほかのフォルダにあるファイルは、エクスプローラで消してから「ファイルが無いので片付ける」を押してください。（詳細: [WinError 5] アクセスが拒否されました。）
```

- **2 文**（何が起きたか。＋どうすればよいか。規約 3）。**中黒で文を繋がない**（規約 1）。
- **「用意する」を使わない**（規約 3）。**ボタンの語は画面の実物**（「ファイルが無いので片付ける」）。
- **技術的な詳細は括弧の中**（規約 3「エラーは 2 文＋詳細」）。`（詳細: …）` は `winerror` と `strerror` だけ
  （Windows の ja は「アクセスが拒否されました。」で終わるので、括弧の外に「。」を足さない）。
- **パスは本文に出さない**——`details`（`from` / `to`）にだけ残す（開発者はそこを見る）。

**変えない物**: `code` = `move_failed` / HTTP 409 / `details.from` / `details.to` / 台帳を消す・ファイルを動かさない後始末（B-1）。

## 2. 決めたこと（4 点）

| # | 決めたこと | 理由 |
| --- | --- | --- |
| 1 | **パスで判定しない**（`C:\work\image-reviwer` の外かどうかを見ない） | **ワークスペースの中でも権限で断られる**ことがあり（読み取り専用・ACL・掴まれている）、そのときも**同じ案内が正しい**（利用者の指示） |
| 2 | **`PermissionError` だけでなく `OSError` 全部**で同じ案内 | **1 か所 1 文言**（断られた理由ごとに文を散らかさない）。`FileExistsError`（WinError 183）は今までどおり `target_exists` で別の文 |
| 3 | **1 か所**（`move_no_clobber` の `except OSError`）で作る | 段 2・段 2 へ進める・まとめて（削除と前進）・取り消しが**同じ関数**を通るので、文言が 1 つに揃う |
| 4 | **`details` に `error` を足さない** | 応答の形を変えない（足すのは文言だけ）。`str(exc)` の情報は `from` / `to` と詳細の行で足りる |
| 5 | **`hint` / `guidance` の欄は作らない** | `ReviewError` にはその欄が無い（`details` と `detail` だけ）。**案内は `detail` の 2 文目**に入れるのが規約 3 の形で、画面も `detail` だけを出す（応答の形を増やすと契約と検査が増える） |

## 3. 効く経路（4 つ＋同じ道を通る 1 つ）

| 経路 | 口 | 文がどこに出るか |
| --- | --- | --- |
| ① **段 2（削除）** | `POST /api/locations/delete`（`stage: 2`） | 409 の `detail` |
| ② **後から段 2 へ進める** | `POST /api/deletions/{id}/advance` | 409 の `detail` |
| ③ **まとめて削除** | `POST /api/locations/bulk-delete`（`stage: 2`） | 200 の `skipped[].message`（`reason: move_failed`） |
| ④ **まとめて進める** | `POST /api/deletions/advance` | 200 の `skipped[].message`（`reason: move_failed`） |
| （⑤ 同じ道）**取り消し** | `POST /api/pending-deletes/{id}/undo`・`POST /api/trash/restore` | 409 の `detail`（`move_failed`。**同じ 1 か所**を通るので同じ文になる。「残した物」§6-3） |

**画面は `body.detail` をそのまま出す**（`apps/gui/pending.js` の 3 か所——段 2 の実行・段 2 へ進める・
まとめての結果は `skipped[].message`）。**アプリ側（GUI）の文は 1 行も変えていない**。

## 4. 触ったファイル（行数）

```
 docs/frontend-design.md         |  1 +
 src/image_reviewer/deletions.py | 40 +++++++++++++++++-
 tests/test_deletions.py         | 91 +++++++++++++++++++++++++++++++++++++++-
 tests/test_deletions_advance.py | 93 +++++++++++++++++++++++++++++++++++++++++
 4 files changed, 223 insertions(+), 2 deletions(-)
```

| ファイル | 何を |
| --- | --- |
| `docs/frontend-design.md` §6（`:982` の 1 行） | **文言の正を先に**直した（家風）。「最近の削除: 移動できないとき」の行を足した（2 文・詳細は括弧・パスは出さない・4 経路とも同じ文） |
| `src/image_reviewer/deletions.py`（`:43`・`:114-122`・`:181-198`・`:220-222`） | 冒頭の規約に 16 を足し、`MOVE_FAILED_MESSAGE`（2 文）と `move_failed_detail()`（OS の言い方だけを括弧へ）を足し、`except OSError` を差し替えた |
| `tests/test_deletions.py`（`:40`・`:99`・`:1351-1353`・`:1375-1433`） | `MOVE_FAILED_TEXT`（**定数を読まず文をそのまま書く**）・`deny_moves()`（`os.rename` を `PermissionError(…, 5)` に差し替え）・**段 2 / まとめて / HTTP** の 3 本。偽物の試験の古い文も片付けた（`:1351-1353`） |
| `tests/test_deletions_advance.py`（`:35`・`:123`・`:430-476`・`:1013-1040`） | 同じ道具と、**後から進める / まとめて進める / HTTP** の 3 本 |

## 5. 検査

### 5.1 足した検査（6 本。**壊すと落ちる**形）

| ファイル | 試験 | 何を見るか |
| --- | --- | --- |
| `test_deletions.py` | `test_a_permission_error_names_the_way_that_works` | 段 2 のサービス直呼び。**文が 1 文字違っても落ちる**（定数を読まない）。**パスが本文に無い**・`details.from` は残る・`code` は `move_failed`・**ファイルは動かない**・**台帳の行も残らない**・`missing_at` を立てない |
| | `test_a_permission_error_in_the_bulk_keeps_the_message` | まとめて削除の `skipped[0]` が `reason: move_failed` ＋**同じ文**（件数だけ返して文を捨てたら落ちる） |
| | `test_a_permission_error_over_http_names_the_way_that_works` | `POST /api/locations/delete`（段 2）の **409 の本文**が同じ文（画面が読む物） |
| `test_deletions_advance.py` | `test_a_permission_error_when_advancing_names_the_way_that_works` | `advance` の本文・**段 1 に戻る**・ファイルは動かない |
| | `test_a_permission_error_in_advance_many_keeps_the_message` | `advance_many` の `skipped[].message` が 2 件とも同じ文 |
| | `test_the_advance_endpoints_name_the_way_that_works_when_the_move_is_denied` | 口 2 つ（1 件は 409 の `detail`・まとめては `skipped[].message`） |

### 5.2 壊すと落ちるの証拠（2 通り。**すぐ戻した**）

| 壊し方 | 結果 |
| --- | --- |
| `except OSError` を**直す前の形**（`f"ファイルを移動できません: {exc}"`）に戻す | 新しい 6 本が**全部落ちる**（`6 failed, 116 deselected`。差分に旧文と `'…\http-denied.png'` が出る） |
| 文はそのままで**括弧の中に `str(exc)`**（パス入り）を戻す | 同じ 6 本が**全部落ちる**（`6 failed`。`MOVE_FAILED_TEXT` と一致しない） |

戻した後は `deletions.py` の SHA256 が**変異の前と同じ**（`BA2B956E…F16D5A`）ことを確かめた。

### 5.3 三点セット（この環境で実行）

| 検査 | 結果 |
| --- | --- |
| `uv run --no-sync pytest -q` | **576 passed**（570 ＋ 新規 6）。`tests/test_deletions.py`＋`tests/test_deletions_advance.py` だけなら **122 passed** |
| `node tools/gui_smoke.mjs` | **406 ok / 0 ng**（exit 0。「すべて ok」） |
| `node tools/gui_layout.mjs`（11 本 × 4 幅＝1400×900 / 1024×700 / 1200×800 / 1920×1080） | **11 本とも exit 0・`^NG` の行 0**（compare 12 行、ほかは 4 行ずつ）。**複製**のサーバ（`:8791`）に対して。**POST は道具が差し替えた `fetch` が飲む**のでサーバのデータは書かない（`tools/gui_layout.mjs` 冒頭の注記） |

**`gui_smoke` / `gui_layout` にこの文を見ている検査は無かった**（`移動` / `move_failed` で grep して 0 件。
`gui_smoke` の `stuckText('move_failed')` は**取り消しの戻せない理由**（`元の場所へ移せませんでした。`）で、今回の文とは別）。
画面は `body.detail` をそのまま出すので、**文言はサーバ側の検査（pytest）で守る**。新しい GUI の検査は足していない。

### 5.4 `gui_layout` を回すための複製（手順）

```powershell
$env:UV_CACHE_DIR = "C:\work\image-reviwer\.uv-cache"
# 1. 複製（DB は sqlite3 の backup()。実データは mode=ro で開くだけ）
uv run --no-sync python -X utf8 .tmp-msg\make_replica.py
# 2. 検査の前提（語・除外・保留・段 3 の許可・バックアップの失敗）。実データは断る
uv run --no-sync python -X utf8 tools\gui_layout_seed.py --data C:\work\image-reviwer\.tmp-msg\replica `
  --tags --exclusion --pending --stage3 --backup-error --backup-dir C:\work\image-reviwer\.tmp-msg\backup-out
# 3. **「最近の削除」に選べる行を 1 つ**（§6-4。実データが全部片付け済みになったため）
uv run --no-sync python -X utf8 .tmp-msg\seed_extra.py
# 4. 別ポートで立てる（**必ず IMAGE_REVIEWER_DATA**）
$env:IMAGE_REVIEWER_DATA = "C:\work\image-reviwer\.tmp-msg\replica"
uv run --no-sync python -X utf8 -m image_reviewer.cli serve --port 8791
# 5. 11 本（`--ids` には**実体のある生きた枚**を渡す。§6-4）
powershell.exe -NoProfile -ExecutionPolicy Bypass -File C:\work\image-reviwer\.tmp-msg\run_gui_layout.ps1
```

`.tmp-msg/` の `make_replica.py` / `seed_extra.py` / `run_gui_layout.ps1` / `gui_layout.log` / `gui_smoke.log` を残した
（**複製そのものは 30 MB あるので消した**。上の手順で作り直せる）。

## 6. 残した物・申し送り

1. **2 文目が 53 字**（`frontend-design.md` §6.1 の規約 5「1 文は 40 字まで」を超える。1 文目は 18 字）。**利用者が指定した文**なので
   そのまま使った（ボタンの実物の語を入れると短くならない。短くする案でも 51 字）。**利用者の言葉を変えるので今回は触っていない**。
2. **`OSError` 全部に同じ案内**（§2-2）。`WinError 32`（別のプログラムが掴んでいる）では 2 文目がぴったりではない
   （その場合の案内は今回の範囲外）。**`PermissionError` に限る形にすると、掴まれているときだけ技術的な旧文が戻る**。
3. **取り消し（`undo` / `trash_restore`）の移動失敗も同じ文**になる（同じ `move_no_clobber` を通る）。取り消しの行は
   画面が「戻せませんでした。」＋理由（`stuck_reason`）も出すので、**「片付ける」を勧める 2 文目とは並ぶ**。
   **取り消し専用の文を作るなら `move_no_clobber` に文脈を渡す**ことになる（今回は「1 か所 1 文言」を優先）。
4. **`gui_layout --screen pending` の前提が実データの片付けで崩れていた**（今回わかった）。実データの `deletion_log` **194 行は
   すべて片付け済み**（`closed_at`。最後の 1 行は `2026-10-19T14:45:57Z` に**利用者の `close_many`** で閉じた。私の作業より前）で、
   **「最近の削除」に選べる行が 1 つも無い**と**まとめての帯が出ない**——道具は `rows > 0` で帯を期待するので **4 幅とも NG** になる。
   **検査の前提**として、複製に**ファイルが無い段 1 の行を 1 つ**足した（`seed_extra.py`。**存在しないパスを登録するだけで、
   ファイルは 1 つも作らない・動かさない**）。道具を直すなら「選べる行が 0 のときは帯を見ない」に変えるのが筋（**今回は道具を触っていない**）。
5. **`--screen pending --ids` に渡す枚**は **`path` があって実体がある生きた枚**にする。`GET /api/assets` の先頭には
   `path: null`・`location_count: 0` の枚が混ざり、渡すと段 3 の 1 行が「置き場を確かめられないので段 3 は出していません」に
   なって**「段 3 の許可がありません」の検査が NG** になる（[`../README.md`](../README.md) の既知の罠と同じ）。
6. **実データは無傷**: `asset` 463 行・`asset_location` 456 行・`deletion_log` 194 行（**片付け済み 194・開いている行 0**）・
   `root` 2 行。**画像は 1 枚も動かしていない**（`.data/trash` は空のまま。`C:\work\illust-authoring`（7,533 ファイル）と
   ComfyUI の出力で **23:50 以降に `LastWriteTime` が変わった物**を数えたら、**利用者の ComfyUI が生成した 3 枚だけ**だった——
   私の作業で 1 つも変わっていない。`.backup` の世代も消していない（`.backup/daily/20261020` は**利用者のアプリの日次**が
   00:00:15 に取った物）。私が書いたのは `.tmp-msg/`（複製）と `tests/.tmp/`（pytest）だけ。
