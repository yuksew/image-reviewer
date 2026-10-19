# 小さな変更 3 つの監査報告（実行込み）

- **日付**: 2026-10-20 01:28〜（JST）
- **依頼**: Orca（dsh、run_5bdd431bf57b）「最後の小さな変更 3 つの監査」。知らせ: 開始 msg_dcfb98e1defb・途中 msg_22adb4051e7d
- **対象（見た版）**:
  - ① `bfcc7b5`（記録 `docs/move-failed-message.md`）: `src/image_reviewer/deletions.py`（`MOVE_FAILED_MESSAGE`・`move_failed_detail()`・`move_no_clobber()`）と、テスト 6 本
  - ② `11a3f88`: `tools/gui_layout.mjs`（`--screen pending` の `pickable`）
  - ③ `67aa1b1`（記録 `docs/tray-recheck-triage.md`）: `tools/tray.ps1`・`tools/tray_selftest.ps1`・`tests/test_tray*.py`・`tests/conftest.py`・`docs/tray.md`・`docs/design.md`
  - 監査中に `git log` の先頭は `67aa1b1` のままで、作業ツリーは clean。
- **環境**:
  - 親のシェルに**安全網** `IMAGE_REVIEWER_DATA=.tmp-small-audit\safety-net` を置いた（最後まで 0 ファイル）。
  - ポートは 8793（合成データ m1）・8794（複製 r0/r1、gui_layout）・8795〜8798（自己検査）・8796〜8798（他人役）・8799（断りの試験。立たないことを確かめる先）。Chrome は 9334（gui_layout）と 9335（自前）。
  - **8790 には `GET /api/health` を始めと終わりに 1 回ずつ打った。止めていない。**
  - 一時物は `.tmp-small-audit/` に置いた。`TEMP` もここへ向けた（%USERPROFILE% の下にフォルダを作らないため）。
- **触っていないもの**:
  - 実データ `.data/` は `mode=ro` で読んだだけ。署名は前後で一致した（H）。
  - 画像は 1 枚も動かしていない。台帳 194 行・`.backup` 12 個もそのまま。
  - `src/`・`apps/`・`tools/`・`tests/` は 1 行も変えていない。変異はすべて写しで回した。
  - git: コミット・push・履歴の書き換えはしていない。

> **対象の外で、急ぐもの（途中の知らせ msg_22adb4051e7d で先に送った）**
>
> **公開リポジトリ `yuksew/image-reviewer`（`gh repo view` で `visibility: PUBLIC`）の履歴に、実データの複製が入って `origin/main` に push されている。**
>
> - `bfcc7b5`（この監査の対象①）が `.tmp-tray-recheck/` の 498 ファイルを巻き込んだ。中身は次のとおり。
>   - `rA/data/db.sqlite3` と `bk-gui/20261019/db.sqlite3`（**実データの DB の複製**）
>   - `rA/data/library/` の**画像 268 枚**（利用者の実画像の写し）と `thumbs` 120 枚
>   - これは**前回の監査で私が残した一時物**。`.gitignore` に無いことは前回の報告 H に書いたが、消しておくべきだった。
> - それより前の `.tmp-p8-5-entries/` も履歴にある（db 3 つ・画像 1,086）。
> - `a720124` / `ae574d0` で追跡は外れた。それでも `git log --all` で数えると、`.tmp-*` の 1,632 パス（画像 1,477・`db.sqlite3` 8）が履歴と GitHub に残っている。
> - 決めるのは利用者（G-1）。

## 判定: **直してから次へ**（③ は合格、② は条件つき、① は直す）

**最も重大な 3 件**

1. **① の案内は、画面の主な道に出ない。出る道でも「通る道」になっていない。**
   - 5 経路の API はすべて同じ文を返し、パスは本文に無い（ここは主張どおり）。
   - ところが本物の Chrome で押すと、**「削除の確認」で段 2 にした結果は「1 件は中身が変わっていたので消しませんでした。」**（嘘の理由。`pending.js:571` の固定文）。
   - **まとめて進める**は「2 件は移しませんでした（できませんでした）。」で、新しい文は**画面に 1 度も出ない**。
   - さらに**段 2 で直接消す道（①③）は台帳の行を消す**（`_drop_log`）。案内どおりエクスプローラで消しても、**押すべき「ファイルが無いので片付ける」の行が無い**（実測 `1_row_for_p1: []`）。
2. **① 取り消し（undo / trash/restore）でも同じ文が出て、従うと戻したいファイルが失われる。**
   - 実測: 元のフォルダに書けない状態で戻すと 409 になり、本文は「ほかのフォルダにあるファイルは、エクスプローラで消してから…」。
   - 案内どおり**ゴミ箱の中のファイルを消して**「片付ける」を押すと 200 `closed`。**`p5.png` はどこにも無くなった**。
   - このテキストを守る検査も無い（変異 D3 が落ちない）。
3. **② の `pickable` は、検査する対象のボタンから期待値を作っている。段 1 の行からボタンが消えても 4 幅 ok になる。**
   - 本物の画面の写し（`fr/apps/gui`）で段 1 の行の「アプリのゴミ箱へ移す」を消す（G2）か、両方のボタンを消す（G4）と、新しい `gui_layout` は **ok 4 / NG 0**。
   - 直す前の `gui_layout` は同じ壊しを **NG 4** で落としていた。**直しで検査が弱くなった。**

（③ のトレイは、前回の再現手順で **exit 2・7.1 秒・他人は同じ pid で生存** になった。8795〜8798 の 4 通りとも同じ。B-1・C-1・C-2 も実測で塞がった。回帰は pytest 577 ×2・gui_smoke 406・gui_layout 11 本 × 4 幅 52 ok・自己検査 133 ok。）

---

## A. 直っていない／設計の約束が成り立たない（必ず直す）

### A-1 ① 移動の失敗の案内が、画面の「削除の確認」（段 2）と「まとめて進める」に出ない。前者は嘘の理由を出す

- **場所**:
  - `apps/gui/pending.js:571` `confirmHtml()`: `${skipped} 件は中身が変わっていたので消しませんでした。` が**理由を見ずに固定**。
  - `apps/gui/pending.js:141-148` `skippedText()`: `SKIP_TEXT`（`:120-133`）に `move_failed` が無いので「できませんでした」。
  - 記録 `docs/move-failed-message.md` §3 は「まとめての結果は `skipped[].message`」と書くが、**画面は `message` を読んでいない**。
- **再現**（合成データ m1、8793。`.tmp-small-audit/gui_move.py` + `gui_move.mjs`。OS に断らせるのは icacls の deny で、`WinError 5`）:
  1. `#/pending-deletes?ids=<p3a>` → 段 2 → 「消す内容を確かめる」 → 「コピーの無い画像も消す」 → 実行。画面は次のとおり。
     ```
     0 枚をアプリのゴミ箱へ移しました。いつでも戻せます。
     1 件は中身が変わっていたので消しませんでした。
     ```
     API の応答は `skipped[0].reason = move_failed`・`message` = 新しい文。**中身は変わっていない**。
  2. 段 1 の行 2 つを「全部選ぶ」→「まとめてアプリのゴミ箱へ移す」。画面: `0 件をアプリのゴミ箱へ移しました。2 件は移しませんでした（できませんでした）。`
  3. 段 1 の行の「アプリのゴミ箱へ移す」（1 件）。画面には**新しい文がそのまま出た**（この道だけ届く）。
- **なぜ重い**:
  - GUI が段 2 で消す口は `POST /api/locations/bulk-delete` だけ（`pending.js:30,820`）。`/api/locations/delete` は画面から呼ばれない（`grep` で 0 件）。
  - つまり利用者が**ライブラリから選んで段 2 で消す主な道では、新しい案内は 1 度も見えない**。代わりに誤った理由が出る。
- **直し方**: `confirmHtml()` の固定文をやめ、`skippedText('delete', state.exec.skipped)` のように理由ごとに出す。`SKIP_TEXT` に `move_failed` を足し、`skipped[].message` を 1 件目だけでも出す。

### A-2 ① 段 2 で直接消す道（1 件の口・まとめて削除）では、案内の「ファイルが無いので片付ける」を押す行が無い

- **場所**: `deletions.py:948-951`。`move_no_clobber` が失敗すると `self._drop_log(...)` で**台帳の行を消す**（B-1 の規律で、これ自体は正しい）。
- **再現**（`.tmp-small-audit/move_paths.py`）:
  - 段 2 の 1 件の口で 409 になった後、`GET /api/pending-deletes` に p1 の行は**無い**（`1_row_for_p1: []`）。
  - 行が無いので「片付ける」のボタンも無い。案内どおりエクスプローラで消しても、**ライブラリの登録は参照切れのまま残り、終わらせる口が無い**。
- **通る道**: 「**段 1（カタログから外す）で消してから、エクスプローラで消し、「ファイルが無いので片付ける」**」。
  - 案内の 2 文目が通る道になっているのは、**段 1 の行がある経路（②④ 後から進める）だけ**。
  - 依頼の「この案内が通る道になっているか」への答えは、**①③ では「いいえ」**。
- **直し方**（G-2）:
  - (a) 経路ごとに 2 文目を変える。段 2 の削除では「「カタログから外す」で外してから、エクスプローラで消してください。」。`move_no_clobber` に文脈を渡すか、呼び出し側で `detail` を差し替える。
  - (b) 段 2 の削除が断られたら、自動で段 1 の行に落とす（設計の変更なので重い）。

## B. 重大

### B-1 ① 取り消しの失敗にも同じ案内が出て、従うと「戻したかったファイル」を消させる

- **場所**:
  - `deletions.py:1806-1813`（`undo`）と `trash_restore` は同じ `move_no_clobber` を通る。
  - 画面は `pending.js:859` / `:1042` で `body.detail` をそのまま出す。
- **再現**（`move_paths.py` の ⑤）:
  1. p5 を段 2 で消す。元のフォルダに `(WD,AD)` の deny を付ける。
  2. `POST /api/pending-deletes/{id}/undo` → 409 `move_failed`、本文は新しい案内。`trash/restore` も同じ。
  3. 案内どおりに**ゴミ箱の中のファイル**（`details.from`）を消し、`POST /api/deletions/{id}/close` → **200 `closed: true`**。
  4. `p5.png` は合成ツリーのどこにも無い（`5_file_anywhere: []`）。
- **補足**:
  - 消す前の close は 409 `file_found` で、`files_touched: 0`。ファイルを消すのは利用者の手だが、**消させたのはこの案内**。
  - 行の表示「戻せませんでした。元の場所へ移せませんでした。「別名で戻す」か「いま消す」を選べます。」とも食い違う。
  - 記録 §6-3 はこれを「並ぶ」とだけ書き、害を書いていない。
- **この環境で起きうるか**: 利用者のアプリは `C:\work\image-reviwer` の外に書けない（§16.7 の末尾）。だから**外のフォルダから段 2/3 にした行を戻すと、必ずこの道を通る**。
- **直し方**: 取り消しでは 2 文目を変える（例:「元のフォルダに書けません。エクスプローラでアプリのゴミ箱から元の場所へ移してください。」）。`move_no_clobber(src, dst, why="restore")` のように文脈を渡す。G-2 と同じ判断。

### B-2 ② 新しい `pickable` のせいで、段 1 の行のボタンが消えても `gui_layout` が通る

- **場所**: `tools/gui_layout.mjs:1387-1388`。`pickable = got.advances + got.closeRowsNotStage1 + got.trashCloses`。
  - どれも**画面のボタンの数**（`MEASURE_PENDING` の `.pd-advance` / `.pd-close`）。
  - 帯・チェックの等号・`段 1 の行に「アプリのゴミ箱へ移す」` の検査は、すべて `if (pickable > 0)` の中にある。
- **再現**（`.tmp-small-audit/gl_apply.py` + `gl_mut.ps1`。`fr/` は `src/` と `apps/gui/` の写し。サーバは `PYTHONPATH=fr\src` で、`/api/health` の `gui_dir` が `fr\apps\gui` を指すことを毎回確かめた）。複製 r1 は API で `stage1=1 closeable=1`。

  | 変異（`fr/apps/gui/pending.js`） | 新しい `gui_layout` | 直す前の `gui_layout` |
  | --- | --- | --- |
  | G0 そのまま | ok 4 / NG 0 | — |
  | **G1 帯を出さない**（依頼の壊し方） | **NG 4**（「まとめての帯」ほか） | — |
  | **G2 段 1 の行の「アプリのゴミ箱へ移す」を出さない** | **ok 4 / NG 0（落ちない）** | **NG 4**（`段 1 の行に「アプリのゴミ箱へ移す」（0/1）`・チェックの数） |
  | G3 チェックを 1 つも出さない | NG 4 | — |
  | **G4 段 1 の行のボタンを 2 つとも出さない** | **ok 4 / NG 0（落ちない）** | **NG 4** |

- **直し方**: 期待を画面から作らない。
  - (a) `stage1 > 0 || got.picks > 0 || pickable > 0` で門を開ける。`stage1` は `.pd-strip` の「段 1」から数え、ボタンに依らない。
  - (b) さらに良いのは、期待値を **API**（`GET /api/pending-deletes` の `stage === 1` と `closeable`）から作ること。`requests` の画面と同じ形になる。

## C. 中程度

### C-1 ① 取り消しの文を守る検査が無い

- 変異 D3（`undo` の `move_failed` だけ旧文に差し替える）で、`test_deletions.py`＋`test_deletions_advance.py` は **122 passed（落ちない）**。
- 記録 §3 の「⑤ 同じ道」は検査の外。B-1 を直すなら、ここに 1 本足す。

### C-2 ② 直しの理由の書き方が事実と少し違う

- コミット `11a3f88` のコメントと記録 §6-4 の説明: 「利用者の実データが全部片付けで、**行はあるが選べる行が無い**状態で 4 幅 NG」。
- 実測すると、**素の実データの複製は行が 0**（閉じた行は一覧に出ない）。**直す前の `gui_layout` でも 4 幅 ok** だった（r0、`gui_layout_old.mjs`）。
- **4 幅 NG になるのは `gui_layout_seed.py --pending` が段 3 の行を 1 つ足したとき**だった（行 1・選べる 0。直す前は NG 4、直した後は ok 4）。
- 直し自体は正しい（段 3 だけの画面に帯を出さないのが正）。ただ、**理由は「種まきの段 3 の行」**。

## D. 軽微

- **D-1 ③ `Test-RealDataDir` が別名の 3 つを実データと見ない**（`-DefineOnly` で関数だけを呼び、現在地 `C:\`）。
  - 実データと見ない: ジャンクション（`.tmp-small-audit\jdata` → `.data`）、`\\localhost\C$\work\image-reviwer\.data`、`\\?\C:\work\image-reviwer\.data`。
  - **8.3 名（`C:\work\IMAGE-~1\.data`）・大文字小文字・`/`・末尾 `\`・末尾 `\.`・`C:\` からの相対 `.data`・`..\image-reviwer\.data` は断る**。
  - どれもわざと打たないと起きないので軽微。直すなら、ファイルの同一性（ボリュームのシリアル番号＋ファイル ID）で比べる。
- **D-2 ③ 断った起動も、利用者の `.tray\tray.log` に 1 行ずつ書く**（入口の断りは `Write-TrayLog` の後）。私の 6 回の試験で 166 → 172 行。害は無いが、本番のログに試験の行が混ざる。
- **D-3 ① 語のゆれ**: 新しい文は「エクスプローラ」。既存の `file_found`（`deletions.py:1557`）と `frontend-design.md` §6 の隣の行は「**エクスプローラー**」。同じ画面に両方が出うる（B-1 の手順 3 の直前）。
- **D-4 ① 2 文目は 53 字**（規約 5 の 40 字を超える）。記録 §6-1 にあるとおり、利用者が指定した文。A-2・B-1 で文を変えるなら一緒に。
- **D-5 ③ triage と commit の数の食い違い**:
  - triage §3 は「いまの実データから作り直した複製では 48 ok / NG 4（`pending --ids`）」と書く。
  - コミット `67aa1b1` の本文は「gui_layout 11 本 x 4 幅 52 ok」。
  - 私の 11 本は **52 ok**（H）。食い違いは `--ids` に渡した枚の違いで説明がつく。どちらの数かを triage に 1 行で書けば足りる。
- 確かめた結果、問題なし:
  - ① 5 経路（段 2 の 1 件・後から進める 1 件・まとめて削除・まとめて進める・取り消しの 2 つの口）は**同じ文**。
  - ① 本文に `C:\` や `->` は無く、パスは `details.from` / `details.to` にだけある。`code` は `move_failed`。
  - ① `target_exists` は「移動先に既にファイルがあります（上書きしません）」で別の文のまま。
  - ① 失敗した移動でファイルは動かない（`1_exists_after: true`）。
  - ② r0（選べる行 0・行 0）は 4 幅 ok。r0 に段 3 を種まいた物（行 1・選べる 0）も 4 幅 ok。r1（段 1 を 1 つ）も 4 幅 ok で、帯の語の検査が効く（G1 で NG 4）。
  - ② **`apps/gui` は 3 つのコミット（`c322392..HEAD`）で差分 0**。
  - ③ 前回の D-1〜D-3（conftest の記述、事故の原因の「推定」、`IMAGE_REVIEWER_BACKUP_DIR` の上書き）は、`tray.md`・`design.md`・`conftest.py` で直っている。

## E. 設計とのずれ

- **E-1** `frontend-design.md` §6 の新しい行は「段 2・段 2 へ進める・まとめて（削除と前進の両方）・取り消しの**どこでも同じ文にする**」と書く。サーバはそうなっている（D の確認）。**画面はまとめての 2 つで文を出さない**（A-1）。設計の約束（「`detail` に入れれば画面が出す」）は、`skipped` の道では成り立たない。
- **E-2** 設計は「パスで判定しない」を理由に 1 文にしたが、**判定すべきはパスではなく経路**（削除・進める・戻す）だった。どの経路でも通る 1 文は無い（A-2・B-1）。
- **E-3** 実装者が自分で決めた点の判定:
  - ① `OSError` 全部に同じ案内: **条件付き**（経路で分けるなら、理由で分けなくてよい）。
  - ① `details` に `error` を足さない: **妥当**。
  - ② 「選べる行」で門を開ける: **変更を勧める**（B-2。門は API か段の語から）。
  - ③ 試験用の引数を `$script:TestArgs` に 1 つにまとめた: **妥当**。
  - ③ 後始末を `Register-OwnProcess` の木だけにした: **妥当**。

## F. テストで守れないもの

| テスト / 検査 | 判定 | 根拠と直し方 |
| --- | --- | --- |
| ① 新しい 6 本（`test_deletions*.py`） | **壊すと落ちる（主張どおり）** | 変異 D1（旧文に戻す）・D2（括弧にパスを戻す）で **6 failed / 116 passed**。D0 は 122 passed。`.tmp-small-audit/dmut.py`、`PYTHONPATH` で写しを前に置き、読んだモジュールのパスを毎回表示した |
| ① 取り消しの文 | **テストの穴** | D3 で 122 passed（C-1） |
| ① 画面がまとめての結果で `message` / 理由を出すか | **テストの穴** | `gui_smoke` / `gui_layout` に `move_failed` を見る検査が無い（記録 §5.3 も 0 件と書く）。A-1 は本物の Chrome でしか見えなかった |
| ② `gui_layout --screen pending` の帯 | 帯を消す壊し（G1）は落ちる | 依頼の壊し方は主張どおり |
| ② 段 1 の行のボタン | **テストの穴（この直しで開いた）** | G2・G4 が落ちない（B-2） |
| ③ 自己検査 133 | 主張どおり | 他人がいるとき 4 通りとも exit 2。trap の写しで exit 3・他人は生存・自分の子は 0 |
| ③ 前回の変異 16 通り | **回し直していない** | triage §2 の 8 通りの表を読んだ。M-A1'（他人のポート）と M-trap に当たる道は自分の手で実測した（H） |

## G. 依頼者への質問（推奨どおりで進めてよい）

| # | 論点 | 選択肢 | 推奨 |
| --- | --- | --- | --- |
| **G-1** | **公開リポジトリの履歴にある実データの複製**（冒頭の囲み） | (a) すぐリポジトリを**非公開**にする (b) `git filter-repo --path-glob '.tmp-*' --invert-paths` で履歴から消して force push（ハッシュが全部変わる。clone 済みの写しには残る） (c) 何もしない | **(a) を今すぐ、その後 (b)**。決めて打つのは利用者（私は git に触れていない）。手元の `.tmp-tray-recheck/rA`・`occ-real`・`bk-gui` も、もう要らないので消してよい（私の一時物） |
| **G-2** | ① 経路ごとに 2 文目を変えるか（A-2・B-1） | (a) 経路で 3 通り（段 2 の削除 =「カタログから外す」で外してから／進める = 今の文／取り消し = 手で元の場所へ移す） (b) 1 文のまま、取り消しだけ別 (c) 今のまま | **(a)**。`move_no_clobber` に `why` を渡して 1 か所で作る形は保てる |
| **G-3** | ① 画面のまとめての結果（A-1） | (a) `confirmHtml` の固定文をやめ、`skippedText` に寄せ、`SKIP_TEXT.move_failed` を足し、1 件目の `message` を出す (b) 理由だけ直す | **(a)**。`gui_smoke` に `skippedText('advance', [{reason:'move_failed', message:…}])` の 1 本を足す |
| **G-4** | ② 門の作り方（B-2） | (a) `stage1 > 0 || picks > 0 || pickable > 0` (b) API の `stage===1` と `closeable` から期待値を作る | **(b)**（`requests` と同じ形）。急ぐなら (a) |

## H. 確かめられなかったこと・証拠・後始末

**実行したコマンドと結果**

| 何を | 結果 |
| --- | --- |
| 実データの署名（`mode=ro`。`.tmp-small-audit/sig.py`） | 前: v6・asset 463・location 456・deletion_log 194（列 18・開いている行 0）・decision 3・root 2・`trash` 0・`.backup` 12。後: （下の「後始末」） |
| ① 5 経路＋`target_exists`（`move_paths.py`、合成 m1・8793・icacls の deny で `WinError 5`） | ① 409・② 409・③ 200 `skipped[].message`・④ 200 `skipped[].message` ×2・⑤ undo 409・⑤ trash/restore 409。**6 つとも同じ文で、パス無し**。⑥ `target_exists` は別文。案内どおりに進めると ⑤ でファイルが消える（B-1）。① の行は無い（A-2） |
| ① 画面（`gui_move.mjs`、本物の Chrome、9335） | ③「1 件は中身が変わっていたので消しませんでした。」・④「2 件は移しませんでした（できませんでした）。」・② 新しい文（A-1） |
| ① 変異（`dmut.py`） | D0 122 passed・D1 6 failed・D2 6 failed・**D3 122 passed** |
| ② r0（素の実データの複製・行 0）新旧 | 新 ok 4・**旧も ok 4** |
| ② r0＋`--pending`（段 3 の行 1） | **旧 NG 4**・新 ok 4（C-2） |
| ② r1（段 1 を 1 つ） | 新 ok 4（`チェック=1(期待 1)`・帯の語あり） |
| ② 変異 G0〜G4（新）と G2・G4（旧） | B-2 の表 |
| ③ 8796 / 8797 / 8798 に**他人の本物の `cli serve`**（合成の複製 `occ-real`）→ `tray_selftest.ps1 -Port 8795` | **3 通りとも exit 2・7.1 秒・「使うポートが空いていません: 879x=ours」・他人は同じ pid で生存**（36716 / 36028 / 29872） |
| ③ 8795 に他人 | **exit 2・7.1 秒・他人は同じ pid で生存**（10100）。**4 ポートとも同じ結果** |
| ③ B-1・C-1（`b1.ps1`、`-Port 8799`） | `-DriveScript` だけ・`-StatusAutoCloseMs` だけ・`C:\` から `-DataDir .data`・`..\image-reviwer\.data`・末尾 `\`・大文字: **6 つとも exit 2・0.2 秒・新しい python 0・8799 は立たない** |
| ③ C-1 の解決（`c1.ps1`、`-DefineOnly`、現在地 `C:\`） | `.tmp-small-audit\x` → `C:\work\image-reviwer\.tmp-small-audit\x`（リポジトリ基準）。別名は D-1 |
| ③ C-2（`c2.ps1`）: コマンド行に `--port 8796` / `--port 8797` を持つ他人の python を置く | **trap の写し**（`Refresh-Tray` で throw）: exit 3・ok 39 / NG 1・**他人 2 つとも生存・検査が残した python 0**。**普通の自己検査**: exit 0・**133 ok / NG 0**・他人は生存・残り 0 |
| pytest（親に安全網、`uv run --no-sync`） | **577 passed** ×2（51 秒） |
| `node tools/gui_smoke.mjs` | **406 ok / 0 NG** |
| `gui_layout` 11 本 × 4 幅（複製 r1＋`gui_layout_seed --tags --exclusion --pending`、8794、PowerShell から直に） | **52 ok / NG 0**（11 本とも exit 0）。`--ids` には `GET /api/assets?limit=40` のうち **`path` がある枚**の先頭 2 つを渡した。triage の「48 ok / NG 4（`pending --ids`）」は、`path: null` の枚を渡したときの結果と読める（記録 `move-failed-message.md` §6-5 と同じ罠）。D-5 の食い違いは、渡した枚の違いで説明がつく |

**証拠の注記**

- 私の進め方で 2 回つまずいた。どちらもデータには触れていない。
  - `gl_mut.py` を Python の子から回したら、Chrome が 9334 で上がらず `ECONNREFUSED` になった（依頼どおり PowerShell から直に回し直した）。
  - `Select-Object -First` が子の `run_gl.ps1` を途中で切り、その回の複製サーバ（r1、8794）が残った。`data_dir` が `.tmp-small-audit\r1` であることを確かめてから止めた。
- 変異の表の値は、その後に**1 つずつ回し直した値**。
- `m1` の icacls の deny は全部外した。残っている `Everyone:(I)(CI)(DENY)(DC)` は、リポジトリの根 `C:\work\image-reviwer` から継いだ物で、もとからある。

**後始末**

- **実データの署名（後）は前と完全に一致**した。件数・列・`deletion_log` の要約ハッシュ、`.data` 直下のファイルの size と mtime（`-wal` / `-shm` も含む）、`trash` 0、`.backup` 12。
- 8790 には始めと終わりに `GET /api/health` を 1 回ずつ打った（pid 3636 のまま。止めていない）。
- 安全網 `.tmp-small-audit\safety-net` は 0 ファイル。8791〜8799・9334・9335 は空き。`git status` は、この報告 1 つだけが未追跡。
- **消した物**（実データの写しを手元に残さない。G-1 の教訓）:
  - `.tmp-small-audit\r0`・`r1`（実データの複製、画像 288 枚の写し）、`fr`・`dmut`（ソースの写し）
  - **前回の私の一時物** `.tmp-tray-recheck\rA`（画像 268 枚の写し・DB の複製）と `bk-gui`
  - 消す前に、中にジャンクションが無いことを確かめた。ジャンクション `jdata` は `cmd /c rmdir` で外した。
- **残した物**（`.gitignore` 済みの `.tmp-small-audit/`）:
  - スクリプト: `sig.py`・`move_paths.py`・`gui_move.py`・`gui_move.mjs`・`gl_apply.py`・`gl_mut.ps1`・`run_gl.ps1`・`gl11.ps1`・`gui_layout_old.mjs`・`dmut.py`・`occ.ps1`・`b1.ps1`・`c1.ps1`・`c2.ps1`・`trapmut/tray.ps1`・`mk_replica.py`・`seed1.py`
  - 合成データ: `m1/`（画像 10 枚。合成）・`occ-real/`（合成）
  - ログ: `*.log`・`*.out`・`move_paths.json`・`sig-*.json`
- **回していない物**:
  - 前回の変異 16 通りの全部（F）
  - 本物の Chrome で取り消しのボタン（`.pd-undo`）を押すこと。画面が `body.detail` を出すことはコード（`pending.js:859`）で読んだだけ
  - 利用者の環境そのもの（アプリがワークスペースの外に書けない状態）での `WinError 5`。icacls の deny で同じ `WinError 5` を作った

---

**最も重大な 3 件（再掲）**

1. **① 新しい案内は、画面の主な道（「削除の確認」の段 2・まとめて進める）に出ない。** 前者は「中身が変わっていたので消しませんでした」という嘘の理由を出す。段 2 で直接消す道では、案内が名指しする「ファイルが無いので片付ける」の行そのものが無い（A-1・A-2）。
2. **① 取り消しの失敗にも同じ案内が出て、従うと戻したいファイルが消える。** ゴミ箱の中のファイルを消して「片付ける」が 200 で通った。検査も無い（B-1・C-1）。
3. **② `pickable` を画面のボタンから作るので、段 1 の行のボタンが消えても 4 幅 ok。** 直す前の検査はこれを落としていた（B-2）。

**対象の外で急ぐもの**: 公開リポジトリの履歴に、実データの DB の複製と実画像の写しがある（冒頭の囲み・G-1）。
