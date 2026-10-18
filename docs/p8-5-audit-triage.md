# P8-5 の監査の指摘の仕分け（**2026-10-18。条件 C-1〜C-3 と D-1〜D-9 を直した**）

- 監査: [`p8-5-audit-report.md`](p8-5-audit-report.md)（判定 **合格（条件つき）**。条件 **C-1・C-2・C-3**、軽微 **D-1〜D-9**、
  設計とのずれ **E-1〜E-5**、守れない物 **F**、質問 **G-1〜G-6**）。
- 担当の範囲（指示）: **`apps/gui/` と `tools/gui_*.mjs` だけ**。**`src/`・`tests/`・`README.md`・`docs/design.md`・
  `docs/p8-*.md`（歴史）・`docs/frontend-design.md` は触っていない**。**コミットしていない**。
  **文言の正は `frontend-design.md` §4.5.1・§6**（指示）。
- **触ったファイルと行数**（`git diff --numstat`。前 = HEAD `2e60b8f`）:

  | ファイル | 前 → 後 | 増減 | 何をした |
  | --- | --- | --- | --- |
  | `apps/gui/settings.js` | 308 → **347** | +59/−20 | **C-1**（`setAllow` も `busy`。印のボタンを押している間 `disabled`）・**C-3**（`read_only` なら 200 でも読み取り専用の案内・書き込むボタンを置かない。理由と案内は `GET /api/health/db?full=0`）・**D-1**・**D-2**・**D-3**・**D-9** |
  | `apps/gui/pending.js` | 699 → **725** | +28/−2 | **D-5**（一覧の上限 2000 枚を超える置き場では、選んだ枚を `GET /api/assets/<id>` で引く） |
  | `tools/gui_smoke.mjs` | 1746 → **1871** | +133/−8 | 検査 **291 → 310**（C-1 の二度押し・C-3 の 200 の読み取り専用・D-1〜D-3・D-5・D-6・D-9） |
  | `tools/gui_layout.mjs` | 1632 → **1698** | +92/−26 | **C-2**（`--screen asset` の段は API と突き合わせて 2 / 3）・**C-1**（二度押し）・設定の読み取り専用（200 の形・失敗の欄を出さない） |

  4 ファイル **+312/−56**。**新規はこの文書だけ**。
- 実行した確認（複製は `.tmp-audit-redo/p8-5-fix/`。サーバは **8796 / 8797**、CDP は 9371 / 9372。
  `IMAGE_REVIEWER_DATA` は必ず付けた。**8790 は止めていない**。ComfyUI は触っていない）:
  - `uv run --no-sync pytest -q -p no:cacheprovider` → **507 passed**（P8-6 の並行実装が入った作業木の数。私の担当は
    `apps/gui/` と `tools/gui_*.mjs` なので**この数は動かない**）
  - `node tools/gui_smoke.mjs` → **310 ok / NG 0**
  - `node tools/gui_layout.mjs` の **11 本 × 3 窓すべて ok**（**成功の形**と**失敗の形**（置き場がファイル）の両方）＋
    **印なし**の `--screen asset` / `--screen pending --ids`（段 **2** ＋「段 3 の印がありません」の 1 行）＋
    **版が新しい DB**（`user_version = 7`）の `--screen settings`（読み取り専用・書き込むボタンなし・`brief` も読み取り専用）
  - **本物の Chrome**（headless。POST は本物。`.tmp-audit-redo/p8-5-fix/fix_click.mjs`）: **印の二度押し → POST 1 回**
    （監査の A4 は 2 回）／対照（ゆっくり 2 回）は 2 回＝数え方は正常／「取り直す」1 回・控え +1／「保存する」PATCH 1 回／
    **本物のマウスの二度押し**（`Input.dispatchMouseEvent`。1 回目の応答を 900 ms 遅らせて**押している間に当てる**）も **1 回**
  - **壊し試験**: `gui_smoke` の写しを 9 通り壊して **9 / 9 が落ちる**（`mut_smoke.py`）。`gui_layout` の C-2 の検査を
    元の形（`.pd-stage === 3`）に戻すと **3 窓 NG**、C-3 の前の形（`backupHtml` が `status === 503` だけ）に戻すと
    **3 窓 NG**（`mut_server_fix.py` を 8798 で）
  - **実データ**: 前後で `mode=ro` の署名が同じ（**263 枚・判断 3 件・`deleted_at` 0・台帳 0・263 ファイル /
    292,561,491 B・署名 `fa99ca126c393d5a`**・`db.sqlite3` の大きさと mtime も同じ）。**画像は 1 枚も動かしていない**。
    `.backup/` は 9 フォルダ（9 つ目は **P8-6 の `pre-p8-6-20261018-100443`**。私は 1 つも作っていない）

## 指摘ごとに 1 行

| # | 指摘（監査） | どうした | どこ |
| --- | --- | --- | --- |
| **C-1** | 印のボタンは二度押しで **2 回 POST**（`setAllow` だけ `busy` を使わない） | **採用（G-1）**。`setAllow` の先頭で `state.busy = true; render();` し、`rootsHtml()` の印のボタンに `disabled` を付けた（**`takeNow` / `saveDir` と同じ形**）。本物の Chrome で **POST 1 回**（監査の A4 は 2 回）。`gui_smoke` に「押している間は押せない」「二度押しでも 1 回」、`gui_layout` に二度押しの検査（`allowBusy`）を足した | `settings.js` `setAllow` / `rootsHtml`、`gui_smoke` 21b、`gui_layout` `PRESS_SETTINGS` |
| **C-2** | `gui_layout --screen asset` は「段が 3 つ」前提で、**印の無い置き場の枚では必ず NG** | **採用（G-2）**。`.pd-stage` が **2 以上**を「削除の確認が出た」の条件にし、**段の数は API（`GET /api/roots` と枚のパス）から組んだ期待値**（印あり 3 / 印なし 2）と突き合わせる。印なしでは「段 3 の印がありません」の 1 行も見る。印なしの複製で 3 窓 ok（**元の条件に戻すと 3 窓 NG**） | `gui_layout.mjs` `PRESS_ASSET_DELETE` / `--screen asset` |
| **C-3** | 版が新しい DB（`read_only` だが `GET /api/backup` は 200）では「いま取る」「保存する」が押せるまま | **採用（G-3）**。`backupHtml()` は `state.status === 503 \|\| got.read_only` で `readOnlyHtml()` の道へ。**印のボタンも読み取り専用では押せなくする**（§6「書き込みのボタンは押せなくする」）。理由と案内は `GET /api/health/db?full=0` から引く（`GET /api/backup` の本文には `read_only` しか無い）。版が新しい複製で 3 窓 ok | `settings.js` `backupHtml` / `load` / `rootsHtml`、`gui_smoke` 25 / 25b、`gui_layout`（読み取り専用の枝） |
| **D-1** | 「取り直す」と「いま取る」 | **`frontend-design.md` を正として画面を「取り直す」に統一**（**監査の推奨とは逆の向き**。指示「`frontend-design.md` を正にして揃える」に従った）。ボタン・`KIND_TEXT.manual`・押した後の 1 行（「取り直しました」）を揃え、`gui_smoke` / `gui_layout` の検査も直した（申し送り 1） | `settings.js`、`gui_smoke`、`gui_layout` |
| **D-2** | 「今日の分」の文が API の `next_run_note` のままで**括弧が 2 つ並ぶ** | **採用（G-4）**。`today_done` から「今日の分は取れています。」/「今日の分はまだです。」を組む。**`next_run_note` と `next_run_at` は画面に出さない**（§6 の文言表に「次は…」の行が無い。申し送り 5） | `settings.js` `backupHtml`、`gui_smoke` 19 / 19b |
| **D-3** | 読み取り専用の `reason` の語彙が API と合わない（`ahead`・`pre_topup_backup_failed` は存在しない） | **採用（G-3）**。表を API の語彙（`malformed` / `unreadable` / `unopenable` / `version_ahead` / `pre_migrate_backup_failed`）にし、**案内は API の `guidance` をそのまま**出した（空なら 1 行を足さない） | `settings.js` `readOnlyHtml`、`gui_smoke` 25b / 25c |
| **D-4** | 走査の印は錠を取る**前**に立つ（`elapsed_sec` は待ち時間込み） | **直していない**（申し送り 2）。直す先は `src/image_reviewer/deletions.py`（**私の担当外**）か、文言表の定義に「順番待ちを含む」と 1 行。**いまの印の `title` は「順番に処理します」**なので後者が安い | — |
| **D-5** | 段 3 の出し分けで `GET /api/assets?limit=2000` を毎回引く（2000 枚を超えると `ids` が見つからず `known: false`） | **採用（一部）**。一覧に無い枚だけ `GET /api/assets/<id>` で引く（**足りない枚の数だけ**）。主のパスは `app.py` の `_primary_path` と同じ見方（1 枚の口の `locations` の形にも当たる）。**一覧を 1 回引く形はそのまま**（枚ごとに `GET` を並べる形には戻していない） | `pending.js` `stage3For` / `primaryPathOf`、`gui_smoke` 28b |
| **D-6** | `gui_smoke` は「控えを読めません」を見ていない（壊し試験 G11 だけ緑） | **採用**。読めない控え（`ok: false`）を 1 つ混ぜて「控えを読めません」を検査（**壊すと落ちる**） | `gui_smoke` 19c |
| **D-7** | `frontend-design.md` §11 L940 に「トレイのアイコンで示す」が残る | **直していない**（担当外。`frontend-design.md` は触らない指示）。文言表 1 行の直し | — |
| **D-8** | 走査中の上部バーの印は `gui_layout` では「隠れている」しか見ない | **足していない**（申し送り 3）。出る道は `gui_smoke`（作り物）と `--screen pending` の差し替え、本物は監査の B10 | — |
| **D-9** | 「保存する」は入力の値をそのまま送る（`placeholder` が無い） | **採用（1 語）**。`placeholder="絶対パス"` を付けた | `settings.js`、`gui_smoke` |
| **E-1** | §6「書き込みのボタンは押せなくする」が `read_only`（200）の形で成り立たない | **C-3 で直した**（読み取り専用の枝へ。印のボタンも押せない） | `settings.js` |
| **E-2** | §6 の設定の文言 2 か所が実装と違う | **D-1・D-2 で直した**（画面を文言表に合わせた） | `settings.js` |
| **E-3** | §9 の P8-5 の行に「トレイ」が残る（§0.21 と食い違い） | **そのまま**（判定のとおり妥当。文書 1 行は親の doc pass） | — |
| **E-4** | §3.4「`scan_running` は作らない」のまま `GET /api/scan` を足した | **そのまま**（409 を返さない形は変えていない） | — |
| **E-5** | §4.5.1 の 6 つの順と `index.html` の順 | **一致を確認**（`stat-backup` → `stat-scan` → 設定） | — |
| **F** | 二度押し・読み取り専用（200 の形）をツールが見ていない | **足した**（`gui_smoke` 310・`gui_layout` の二度押しと読み取り専用の枝） | `gui_smoke`、`gui_layout` |
| **G-1〜G-4** | 推奨 | **採用**（C-1・C-2・C-3・D-1/D-2 を上のとおり直した） | 上と同じ |
| **G-5** | §9 と §11 L940 のトレイ | **担当外**（文書だけ。申し送り 4） | — |
| **G-6** | 走査の印の立て方（D-4） | **保留**（申し送り 2） | — |

## 申し送り（親が決めること）

1. **D-1 の向き**: 指示どおり `frontend-design.md` を正として画面を「取り直す」にした。監査の推奨（G-4）は逆（文言表を
   「いま取る」に）。**同じ語が `frontend-design.md` §3 L282・`p8-design.md` §5・`design.md` §1351・
   `backup.py` / `api/backup.py` の注記に「いま取る」で残っている**ので、親の 1 回の doc pass で揃えるか、
   逆に戻すなら `settings.js` の 3 語（`KIND_TEXT.manual`・ボタン・「取り直しました」）と `gui_smoke` / `gui_layout` の検査 6 か所。
2. **D-4**: `deletions.py`（担当外）で錠の後に立てるか、文言表に「走査中には順番待ちを含む」と 1 行。
3. **D-8**: `--screen library` に走査中の差し替えを足すかは親の判断（いまは `gui_smoke` と `--screen pending` で見ている）。
4. **D-7・G-5・E-3**: 文書だけの直し（`frontend-design.md` §11 L940・§9 のトレイの 1 行）。
5. **画面から外した物**: `next_run_note`（D-2 で不要になった）と `next_run_at`（§6 の文言表に無い）。次の日次を画面に
   出したいなら、文言表に 1 行足してから戻す。
