# P8-3 の監査の指摘の仕分け（**2026-10-18。判定は「合格（条件つき）」→ 全部反映**）

- 監査: [`p8-3-audit-report.md`](p8-3-audit-report.md)（129 行。判定 合格（条件つき）・C-1〜C-3 と D-1〜D-10・E-1〜E-8・F・G-1〜G-6）。
- **触ったファイルと行数**（`git diff --stat`。**コミットはしていない**）:

  | ファイル | 行数（増減） | 何をした |
  | --- | --- | --- |
  | `apps/gui/pending.js` | +137/-… （495 → 550 行） | 段 1〜3・「戻す」・`stuck_reason` 4 通り・C-3 の `load()`・`deleteHref`／入口の配線・段 3 の前置きを置き場から |
  | `apps/gui/duplicates.js` | +58/-… （446 → 448 行） | 既定は 1 枚も選ばない・「全部選ぶ／全部外す」・題名・固定文言・行き先を 1 か所へ |
  | `apps/gui/app.js` | +18/-1 | 拡大の削除の入口（画像のすぐ下）・下部バーの配線 |
  | `apps/gui/group.js` | +18 | まとまりの削除の入口 |
  | `apps/gui/index.html` | +9/-2 | 下部バーのボタン・まとまりのボタン・help の 1 行 |
  | `apps/gui/styles.css` | +16 | `.del-entry` |
  | `src/image_reviewer/deletions.py` | +65/-… | `pending()` が段 1〜3・並び・`undoable`・`stuck_reason`・`STUCK_REASONS` |
  | `src/image_reviewer/db.py` | +14 | `deletion_log.stuck_reason`（DDL と `_top_up_v6`） |
  | `src/image_reviewer/api/deletions.py` | +10/-… | docstring（段 1〜3・`stuck_reason`） |
  | `tests/test_deletions.py` | +184 | 新しい 4 件（段 1〜3・並び・理由 4 通り・列のトップアップ） |
  | `tools/gui_smoke.mjs` | +160/-… （207 → **232 件**） | 押す検査（下部バー・まとまり・段 1 の戻す・409 の直後の別名・既定 0 枚） |
  | `tools/gui_layout.mjs` | +217/-… | `delTop`/`delVisible`＋押す検査・**`--screen library` 新設**・既定 0 枚・D-6 の手当て・`about:blank` の挟み方 |
  | `tools/gui_layout_seed.py` | **新規 144 行** | 複製に前提を用意する（**実データは断る**） |
  | `docs/frontend-design.md` | +49/-… | §4.6・§6（文言と括弧の規則）・§11 |
  | `docs/p8-design.md` | +61/-… | §0.13・**§0.19（この監査の確定）**・§2.1・§3.2・§4.1・§5・§8.1 |
  | `docs/p8-3-audit-triage.md` | **新規**（この文書） | 指摘ごとに 1 行 |

  （合計 **14 ファイル +942/-86** と新規 2 ファイル。`README.md` と `docs/design.md` は触っていない）
- 実行した確認（**複製**。`.tmp-audit-redo/p83-fix/`。サーバは **8795**＝8791 は別のエージェント（P8-4 の監査）が使用中だった）:
  `pytest -q` **457 passed × 4 回**（26.7 / 28.5 / 26.4 / 26.7 s）、`node tools/gui_smoke.mjs` **232 ok / NG 0**、
  `node tools/gui_layout.mjs` の **9 画面すべて ok（各 3 窓）**＋`--screen pending --ids` も ok、
  `node .tmp-audit-redo/p83-fix/click_flow.mjs http://127.0.0.1:8795`（**本物の Chrome で C-1〜C-3 を押す**）
  **16 検査すべて ok**。
- **実データ `.data` は `mode=ro` と `backup()` と `copy2` だけ**。画像は 1 枚も動かしていない（下の署名）。
  利用者のアプリ（**8790**）は止めていない（`netstat` で最後まで `LISTENING` を確認）。ComfyUI は触っていない。

## 指摘ごとに 1 行

| # | 指摘（監査） | どうした | どこ |
| --- | --- | --- | --- |
| **C-1** | 削除の入口が重複の画面にしか無い（設計 §5「入口 `#/asset/<id>`」・§11 の下部バーが無い）。推奨 G-1 | **採用。入口を 3 つ足した**: 拡大の**画像のすぐ下**（「この 1 枚を削除へ回す」）・**ライブラリの下部バー**（「選んだ N 枚を削除へ回す」）・**まとまりレビューの下部**。どれも `#/pending-deletes?ids=` へ渡すだけ。行き先は `pending.js` の `deleteHref()` **1 か所** | `app.js`・`index.html`・`group.js`・`styles.css`・`pending.js`・`frontend-design.md` §6・§11・`p8-design.md` §5 |
| **C-1 の検査** | 「入口がスクロール無しで見えるか」と「押して `#/pending-deletes?ids=` へ行くか」 | **`gui_layout --screen asset` に `delTop`/`delVisible`（`tgTop` と同じ形）＋押す検査**、**`--screen library` を新設**（下部バー）。`gui_smoke` に下部バー・まとまり・行き先の**押す検査** | `tools/gui_layout.mjs`・`tools/gui_smoke.mjs` |
| **C-2** | 段 1 の行が「最近の削除」に出ず、画面から戻せない（§4.6「1 行 = `deletion_log` の 1 行」と違う）。推奨 G-2 | **採用。`pending()` が段 1〜3 を返す**（実体を消した行・戻した行は返さない）。段 1・2 は「**戻す**」・残り時間は `—`、段 3 の窓は「取り消す」。**段 2 は「ゴミ箱」の欄にだけ**出す（同じ行を 2 度出さない）。**並びは残り時間の短い順**（§11。窓の無い行は新しい順） | `deletions.py` `pending()` / `_log_doc()`・`pending.js` `rowHtml()` / `runningHtml()`・`frontend-design.md` §4.6・§6・§11・`p8-design.md` §3.2・§4.1・§5 |
| **C-3** | 409 `target_exists` の直後に「別名で戻す」が出ない（再読込まで押せない） | **採用。失敗の道でも `await load()`**（`undo`。同じ考え方で `trash_restore`・`purge` の失敗も読み直す） | `pending.js` `undo()` |
| **D-1** | 括弧書きが画面の文言に多い（規則が §2.3 と §6 の 1 行に割れている） | **採用（G-5 の形で）**: 規則を `frontend-design.md` §6 の末尾に 1 か所だけ書き（**語釈の行だけの規則**）、§6 の「完全重複」の行から「括弧書きを使わない」を消した。**その 1 行だけを見る `gui_smoke` の検査は外した**（規則が消えたため） | `frontend-design.md` §6・`tools/gui_smoke.mjs` |
| **D-2** | 固定の数と名前が文言に埋まっている（「263 枚で 2.6 秒」「illust-authoring」） | **採用（G-4）**: 秒数と枚数を消し（「絵を読んで指紋を作ります。画面は止まりません。」）、段 3 の前置きは **`GET /api/roots` の印の無い置き場の実パス**から組む（印がある置き場では出さない） | `duplicates.js`・`pending.js`・`frontend-design.md` §6 |
| **D-3** | 「戻せませんでした」の理由が 1 種類（`target_exists` でも「見つかりません」） | **採用（G-3）**: `deletion_log.stuck_reason` を足し（**版は上げず `_top_up_v6` で ALTER**）、API が返し、画面は **4 通り**に分ける | `db.py`・`deletions.py`・`pending.js`・`p8-design.md` §2.1・§3.2・§5 |
| **D-4** | まとまりの題名に括弧と数（「重複の候補（距離 0・2 枚）」） | **採用**: 「重複の候補: 距離 0 の 2 枚」に直した（括弧と中黒を使わない） | `duplicates.js` `makeGroup()`・`frontend-design.md` §6 |
| **D-5** | 「最後の 1 つ」の文言が §6 と実装でずれている（枚数が要る） | **採用**: 文言表を「最後の 1 つが 3 枚あります。ほかに実体がありません。」に直した（実装が正） | `frontend-design.md` §6 |
| **D-6** | 新しい 2 画面の `gui_layout` が**手で作った前提の行**に依存（素の複製では 3 窓とも NG）。推奨 G-6 | **採用＋恒久策**: `tools/gui_layout_seed.py` を足した（**複製の中に**語・除外の理由・段 3 の保留を作る。**実データは断る**）。前提が無いときは **NG にせず空の表示を見る**（`--screen duplicates` は「別物として確定した組はありません」、`--screen pending` は入口が出ないこと・`--screen tags` は語の行） | `tools/gui_layout_seed.py`（新規）・`tools/gui_layout.mjs`・`p8-design.md` §0.13・§8.4 |
| **D-7** | 8790（利用者のアプリ）は P8-3 の裏側ではない（静的ファイルだけ新しい） | **対応不要**（直しは失敗の道なので実害なし）。**画面は新しい API を必須にしない**ようにした（`/api/roots` が 404 でも止まらない・`stuck_reason` が無ければ `missing` と同じ文言）＝ **古いサーバ＋新しい画面でも壊れない** | `pending.js` `load()`・`stuckText()` |
| **D-8** | `GET` の読みは `badge.js` だけ人と名乗らない | **残した**（`undoable` を使わないので害が無い。変えると 5 秒ごとのヘッダが増えるだけで、監査も「害は無い」と書いている） | — |
| **D-9** | ゴミ箱の行が「取り消す」ではなく「戻す」である理由が文言表に無い | **採用**: §4.6 と §6 に「**窓が無い戻しは「戻す」**（「取り消す」は 5 分の窓の間だけの語）」を書いた | `frontend-design.md` §4.6・§6 |
| **D-10** | 凍結の失効（10 分）の画面を本物で見ていない | **残した**（`gui_smoke` の作り物で分岐は固定してある。**10 分待つ試験は入れていない**） | — |
| **E-1** | §5「入口 `#/asset/<id>`」と §11「削除の入口」が無い | **採用**（C-1 と同じ）。§5 の「入口」行に 3 つを明記 | `p8-design.md` §5 |
| **E-2** | §4.6「1 行 = `deletion_log` の 1 行」に対し画面は段 3 だけ | **採用**（C-2 と同じ）。§4.6 に段ごとの見せ方を明記 | `frontend-design.md` §4.6・`p8-design.md` §4.1 |
| **E-3** | §5（Q8）「印が無い置き場では段 3 のボタンを出さない」は未実装（P8-4 の口が要る） | **残した**（監査も「いまは妥当」）。§5 は「印が無い置き場では**前置きを出す**」に直し、**印を付ける口は P8-4** のまま | `p8-design.md` §5 |
| **E-4** | §5「ゴミ箱 `#/trash`」は作らず `#/pending-deletes` の中 | **採用**: §5 の表から別画面を外し、ゴミ箱は「最近の削除」の中と書き直した（§11 と同じ） | `p8-design.md` §5 |
| **E-5** | §4.6 の入口 (c) トレイは無い（常駐の実装が無い） | **残した**（監査も妥当。§11 に「いまは (a) と (b) の 2 つ」と既に書いてある） | — |
| **E-6** | 走査中の表示は無い（`scan` が job を持たない） | **残した**（監査も妥当） | — |
| **E-7** | §5「削除は色で警告しない」 | **確かめた結果、問題なし**（琥珀と赤の使い方が §2.2 の意味の色の範囲） | — |
| **E-8** | §4.6「起動後に窓が切れた分を消す」を §0.6-3 に合わせて直した | **そのまま**（直っている） | — |
| **F** | 壊し試験 3/3 が落ちる・`gui_smoke` の 76 件は作り物・段 1 の行が出ないことを見る試験が無い | **採用**: 段 1 の行・並び・`stuck_reason` 4 通り・列のトップアップの**4 件を `pytest` に足した**（§8.1 の 68〜71）。`gui_smoke` は **232 件**に増えた | `tests/test_deletions.py`・`p8-design.md` §8.1 |
| **G-1** | 削除の入口（推奨: 下部バー＋拡大の画像のすぐ下） | **採用**（C-1） | 上と同じ |
| **G-2** | 段 1・2 の行を「最近の削除」に出す（推奨: `GET /api/deletions` を読む） | **採用（形は変えた）**: サービス側の `pending()` が段 1〜3 を返す形にした（監査の推奨は「画面が台帳を読む」だったが、**同じ口で段が揃う**方が画面の分岐が 1 つで済む） | `deletions.py` |
| **G-3** | `stuck_reason` を API に足して文を分ける | **採用**（D-3） | 上と同じ |
| **G-4** | 固定の文言を実際の値／一般の言い方に | **採用**（D-2） | 上と同じ |
| **G-5** | 括弧の規則を §6 に 1 行書いて L692 を消す | **採用**（D-1） | 上と同じ |
| **G-6** | `gui_layout` の前提が無いときは NG にせず注意して終える | **採用＋`tools/gui_layout_seed.py`**（D-6） | 上と同じ |
| **監査の注意（[5]）** | 複製で「削除へ回す」を押したら**既定で全群が選ばれ**、段 1 が 56 枚に掛かった | **採用（親の追加指示）**: `#/duplicates` の**既定は 1 枚も選ばない**。「全部選ぶ」／「全部外す」を置き、**人が押したときだけ**選ぶ。`gui_smoke` に「開いた直後は 0 枚」の検査、`gui_layout` に「既定 0 枚＋全部選ぶがある」の検査を足した | `duplicates.js`・`tools/gui_smoke.mjs`・`tools/gui_layout.mjs`・`frontend-design.md` §6・§11・`p8-design.md` §0.13・§5 |

## 決めたこと（監査の推奨と違う所）

1. **段 2 の行は「取り消せる削除」の一覧に出さない**（すぐ下の「ゴミ箱」の欄に日付ごとに出る）。同じ 1 行に
   「戻す」が 2 つ並ぶのを避けるため。**画面全体では 1 行 = 1 回**（§4.6 の趣旨は満たす）。監査 G-2 は
   「段 2 はゴミ箱の行と同じ『戻す』」と書いていたので、**語と効きは揃えている**。
2. **`pending()` が段 1〜3 を返す**（監査の推奨は画面が `GET /api/deletions` を読む形）。口を 1 つにすると
   `window_sec` と `found`（拾い物）が同じ応答で揃う。
3. **別名で戻した後の名前は `<名前>.<連番>.<拡張子>` の「空いている最初の番号」**（`.1` とは限らない）。
   検査は `/\.\d+\.[^.\\]+$/` で見る（前の検査が残した `.1.png` があると `.2` になる）。
4. **`--screen tags` は `--tags` の前提が要る**（実データは語 0 件）。`gui_layout_seed.py --tags` で用意する。

## 残した所（理由）

| # | 残した物 | 理由 |
| --- | --- | --- |
| D-8 | `badge.js` の `GET` が人と名乗らない | `undoable` を使わないので害が無い（監査も同旨）。直すと 5 秒ごとのヘッダが増えるだけ |
| D-10 | 凍結の失効（10 分）を本物で見る試験 | 10 分待つ試験は入れない方針（`gui_smoke` の作り物で分岐は固定）。**P8-5 の仕上げで見る候補** |
| E-3 | 印が無い置き場で段 3 のボタンを出さない | `POST /api/roots/{id}/allow-stage3` が P8-4。**いまは前置きを出す**（印の無い置き場の実パスつき） |
| E-5 | トレイの「最近の削除を開く」 | 常駐（トレイ）の実装が無い。§11 に「いまは (a) と (b) の 2 つ」と明記済み |
| E-6 | 走査中の表示 | `scan` が job を持たない（P8-4 の範囲） |
| — | 8790 の再起動 | **利用者のアプリは止めない**（親の指示）。直しは静的ファイルなので、**次に起動したときに揃う**（D-7） |

## 実行したコマンド（そのまま打てる形）

```powershell
$env:UV_CACHE_DIR = "C:\work\image-reviwer\.uv-cache"
cd C:\work\image-reviwer
uv run --no-sync pytest -q -p no:cacheprovider                        # 457 passed（×4 回）
node tools/gui_smoke.mjs                                             # 232 ok / NG 0
uv run --no-sync python -X utf8 .tmp-audit-redo\p83-fix\make_replica.py
$env:IMAGE_REVIEWER_DATA = "C:\work\image-reviwer\.tmp-audit-redo\p83-fix\srv"
.\.venv\Scripts\python.exe -m image_reviewer.cli serve --port 8795   # 8791 は別のエージェントが使用中
uv run --no-sync python -X utf8 tools\gui_layout_seed.py --data .tmp-audit-redo\p83-fix\srv --tags --exclusion --pending
node tools/gui_layout.mjs --base http://127.0.0.1:8795 --count 8                # 比較
node tools/gui_layout.mjs --base http://127.0.0.1:8795 --screen requests
node tools/gui_layout.mjs --base http://127.0.0.1:8795 --screen group --group <id>
node tools/gui_layout.mjs --base http://127.0.0.1:8795 --screen asset --ids <1 枚>
node tools/gui_layout.mjs --base http://127.0.0.1:8795 --screen tags
node tools/gui_layout.mjs --base http://127.0.0.1:8795 --screen jobs
node tools/gui_layout.mjs --base http://127.0.0.1:8795 --screen duplicates
node tools/gui_layout.mjs --base http://127.0.0.1:8795 --screen pending
node tools/gui_layout.mjs --base http://127.0.0.1:8795 --screen pending --ids <a>,<b>
node tools/gui_layout.mjs --base http://127.0.0.1:8795 --screen library
node .tmp-audit-redo\p83-fix\click_flow.mjs http://127.0.0.1:8795    # 本物の Chrome で C-1〜C-3 を押す
uv run --no-sync python -X utf8 .tmp-audit-redo\p83-fix\snap.py after # 実データの署名
```

## 実データ（前後で同じ）

| 何 | 前（作業の最初） | 後（作業の最後） |
| --- | --- | --- |
| `asset` | 263 | 263 |
| `decision` | 3 | 3 |
| `deletion_log` | 0 | 0 |
| `asset.deleted_at` | 0 | 0 |
| 画像 263 枚の署名（パス・大きさ・mtime_ns） | `2959334944f6a8d2`（292,561,491 B） | 同じ |
| `.data` のファイル署名（307 ファイル） | `445312613a04805b` | 同じ |

- **監査の時点（04:30〜05:30）から実データが 2 つ増えている**（`duplicate_exclusion` 1 行＝
  `at 2026-10-17T20:19:38Z`・`review_group` 1 行）。**私の作業ではない**（`mode=ro` と複製しか使っていない）。
  利用者のアプリ（8790）は P8-3 の**静的ファイルだけ新しく**読むので、利用者が画面から
  「別物として確定」を押すと**実データに書かれる**（D-7 の別の現れ方）。**消さずにそのまま残した**（利用者の判断）。

## 後始末（残した物・消した物）

- **消した物**: 複製の画像（`srv-lib` 292 MB）と複製の DB（`srv`）。**`make_replica.py` で 30 秒で作り直せる**
  （手順は下のコマンド）。検証用のサーバ（8795）は止め、`netstat` で待ち受け 0 本を確認した。
- **残した物**: `.tmp-audit-redo/p83-fix/`（`make_replica.py`・`clean_seed.py`・`snap.py`・`debug.mjs`・
  `click_flow.mjs`・`click_flow.out.txt`・`layout.out.txt`・`snap-before/after/final.json`・`peek.py`）。
  **消して構わない**（再現手順はこの文書に書いてある）。`%TEMP%\gui-layout-*` / `gui-click-*` は
  `gui_layout` / `click_flow` が残す Chrome のプロファイル（前から同じ。`docs/p5-fix2-audit-report.md`）。
- **私が踏んだ穴（記録）**: 実装中に `app.js` のテンプレート文字列へ**バッククォートを 1 つ**混ぜた所、
  `gui_smoke` は緑のまま **`gui_layout --screen library` だけが落ちた**（`frames=0`）。`gui_smoke` は
  `app.js` を読み込まないので、**この検査が無いと「画面が真っ白」を見逃す**（足した検査がすぐ働いた）。
  同じ形の穴を `gui_layout.mjs` の中でも踏んだ（テンプレート文字列の中のバッククォート。`node --check` で検出）。
- **行末と BOM を揃えた（自分の後始末）**: 直した `src/image_reviewer/{db,deletions}.py` と
  `api/deletions.py` の行末が **CRLF** になっていた（リポジトリは LF）ので LF に戻し、`Set-Content` で
  付いてしまった **BOM** を `docs/p8-design.md` から外した（どちらも**中身は同じ**。行末を戻した後に
  `pytest 457 passed` ともう一度確認）。**この 2 つ以外の書き換えは無い**（`git diff --stat` は 14 ファイル +942/-86）。
