# トレイ 再確認報告 — 実行込み（監査 `tray-audit-report.md` の直しを確かめる）

- 日付: 2026-10-19（21:43〜22:24）
- 依頼: Orca（dsh、run_5bdd431bf57b）「直したので再確認を。報告は `docs/tray-audit-recheck.md` に新規で」
- 途中の知らせ: `tray-recheck-mid`（msg_7743373e5df4、21:54。下の A-1 を先に送った）
- 対象（見た版。監査の最初と最後で mtime が変わっていないことを確かめた）:
  - `tools/tray.ps1` 71,802 B（21:33:17）／`tools/tray_selftest.ps1` 43,793 B（21:24:01）／`tools/tray_drive.ps1` 9,040 B（20:54:56）
  - `tests/test_tray.py` 16,677 B（21:14:04）／`tests/conftest.py` 8,481 B（20:47:32）／`tools/gui_layout.mjs`
  - 文書: `docs/tray-audit-triage.md`（21:27:29）・`docs/tray.md`（21:32:52）・`docs/design.md`（21:27:46。§4.1・§16.8）・`docs/handoff.md`・`README.md`
  - コミット `191382c`（「トレイの監査の指摘を反映」）
- 環境: 親のシェルに**安全網** `IMAGE_REVIEWER_DATA=.tmp-tray-recheck\safety-net` を置いて全部を回した（env を付け忘れた子が実データでなくここを開く。**最後まで 0 ファイル**）。
  ポートは 8795〜8798（自己検査）・8792（gui_layout）・8811（駆動の再現）・8821/8822（競合の再現）。**8790 は使っていない。**
- 触っていないもの: 実データ `.data/`（`mode=ro` でしか開いていない。前後の署名が一致＝H）・画像（1 枚も動かしていない）・`src/`・`tools/`・`tests/`（変異は写しで）・`.backup/`（12 個のまま）。git のコミットはしていない。

## 判定: 直してから次へ（直しは小さい。A-1 は 3 行）

**データの安全（A-1 の芯）は塞がった。** この版で `IMAGE_REVIEWER_DATA` を付けずにサーバを起こす経路は見つからなかった
（安全網に何も書かれず、前回の再現手順を回しても子はすべて置き場を明示されて起動した）。**A-2 も塞がった**
（前回の競合の再現 2 通りで、他人のサーバは生き残った）。しかし、依頼が名指しした
「**使う 4 ポートが埋まっていれば 1 つも起動せず exit 2**」が**実際には 8795 しか見ておらず**、その結果
**自己検査が他人の image-reviewer を止める**（A-2 と同じ型の事故を、検査の道具が起こす）。名指しの観点で欠陥が出たので合格にしない。

### 最も重大な 3 件

1. **（A-1）4 ポートの確認は 8795 しか見ていない。** `tools/tray_selftest.ps1` の 3 か所
   `foreach ($p in @($Port, $Port + 1, $Port + 2, $Port + 3))`（114・153・253 行）は、PowerShell では**カンマが `+` より先に結び付く**ので
   **7 要素 `8795,8795,1,8795,2,8795,3`** になる（実測 `count=7`）。空きの確認・`trap` の後始末・`own` でないときの後始末の
   **3 つとも 8796〜8798 を見ない**。**8796 に本物の image-reviewer（複製）を立てて自己検査を回すと、exit 2 にならず最後まで走り
   （ok 114 / NG 1）、§10 の後始末がそのサーバを止めた**（`occupant alive after selftest: False`）。
2. **（B-1）駆動（`-DriveScript`）は `-DefineOnly` ではないので、`-DataDir` を付け忘れると既定の `.data` を開く。**
   `tray.ps1` の冒頭・`design.md` §4.1 は「`-DefineOnly` で読み込んだとき（自己検査・**駆動**）は空を断る」と書くが、駆動はトレイを
   丸ごと起動する道で、断りが効かない。リポジトリの写し（`.tmp-tray-recheck\fakerepo`。その `.data` は合成）で実測:
   `-DriveScript` だけで起動 → `データ置き場 ...\fakerepo\.data` → `[recheck-drive] mode=own data_dir=...\fakerepo\.data`。
   本物の `tray_drive.ps1` は**要求を 1 件 `POST` する**ので、本物のリポジトリでこれをやると**実データに書く**。
3. **（F）直した所の周りは大半が壊しても落ちない。** 監査側の変異 16 通りのうち **13 通りが落ちない**（C-1・C-2 ×2・C-3・C-4・D-6・D-7・D-8・
   起動失敗の後始末・終了と再起動の「他人が立った形」・段 3 のバルーン・時間切れのツールチップ）。うち C-3（R4）は等価、残り 12 は**テストの穴**。
   実装者の 13 通りのうち芯の 6 つ（M-A1a・M-A1c・M-A2a・M-A2b・M3・M-B1）は**取り直して同じ件数で落ちた**。

## A. 直っていない／設計の約束が成り立たない（必ず直す）

### A-1. 「使う 4 ポートが埋まっていれば 1 つも起動せず exit 2」が成り立たない（8795 しか見ていない）

- 場所: `tools/tray_selftest.ps1:114`（`trap` の後始末）・`:153`（§1 の空きの確認）・`:253`（§2 が `own` でないときの後始末）。
  3 か所とも `@($Port, $Port + 1, $Port + 2, $Port + 3)`。
- 原因（実測）: `$Port=8795; @($Port, $Port + 1, $Port + 2, $Port + 3)` → `count=7 values=8795,8795,1,8795,2,8795,3`。
  PowerShell の単項でない `,` は `+` より強い。`($Port, $Port) + (1, $Port) + (2, $Port) + 3` と読まれる。
  §1 の出力が `使うポートが空いていません: 8795=ours, 8795=ours, 8795=ours, 8795=ours` と**同じポートを 4 回**出していたのが表の証拠。
- 再現（`.tmp-tray-recheck\selftest-occ-*.log`）:

  | 埋めたポート | 埋めた物 | exit | 結果 |
  | --- | --- | --- | --- |
  | 8795 | 偽の `/api/health`（`fake_health.py`） | **2** | 狙いどおり 1 つも起動しない |
  | 8796 | 偽の `/api/health` | **1** | 最後まで走り ok 114 / NG 1。**§10 の後始末が偽を止めた**（`fake_alive=False`） |
  | 8796 | **本物の `cli serve`（合成の複製）** | **1** | ok 114 / NG 1（「他人のサーバも複製を開いている ← data_dir=...\occ-real」）。**「検査の後始末で他人のサーバを止めた」が ok ＝その本物が死んだ** |
  | 8798 | 偽の `/api/health` | **1** | ok 112 / NG 3（§1b・§2b がそのポートで空振り）。偽は生き残った |

- なぜ他人が死ぬか: §10 は `Wait-ServerUp -Port ($Port + 1)` を **`-Proc` 無し**で呼び（身元を確かめない道）、ポートに居た他人の `pid` を
  `$strangerPid` にして、最後に `Stop-TestProcess -ProcessId $strangerPid` で `taskkill /T /F` する（`:577`・`:651`）。**トレイ本体で塞いだ A-2 の形が、
  検査の中に残っている。**
- **データは無事だった**: 4 通りとも、検査が起こした子はすべて `IMAGE_REVIEWER_DATA` を明示されていた（§10 の他人は `$Replica`）。
  安全網のフォルダは 0 ファイルのまま。**「env 無しで起動する経路 0」は成り立っている**（A-1 の芯）。
- 直し（推奨）: ① 3 か所を `@($Port, ($Port + 1), ($Port + 2), ($Port + 3))`（か `$Port..($Port + 3)`）に。
  ② §10 の他人は `Wait-ServerUp -Port ($Port + 1) -Proc $stranger` で受け、**子孫でなければ止めない**（後始末は `$stranger.Id` の木だけ）。
  ③ 振る舞いの検査を 1 本足す（F の表の最後）。

## B. 重大

### B-1. 駆動（`-DriveScript`）に断りが効かない — `-DataDir` を忘れると既定の `.data` を開く

- 場所: `tools/tray.ps1:209`（`Get-EffectiveDataDir` は `$script:DefineOnly` のときだけ断る）・`:440`・入口 `:1415〜1446`。
  文書: `tray.ps1:29`「`-DefineOnly` で読み込んだとき（自己検査・駆動）」、`design.md` §4.1 の「子に渡すデータ置き場（監査 A-1）」の行、`triage` A-1(d)。
- 実際: 駆動は `powershell -File tools\tray.ps1 ... -DriveScript tools\tray_drive.ps1` で**トレイを丸ごと起動**する（`tray.md` §3 の手順）。
  `-DefineOnly` は付かないので、`-DataDir` を落とすと**本番と同じ道**で `<リポジトリ>\.data` を明示して起動する。
- 再現（実データには触れずに）: `tools\tray.ps1` を `.tmp-tray-recheck\fakerepo\tools\` へ写し、`fakerepo\.venv` を本物の `.venv` への
  ジャンクションに、`fakerepo\.data` を合成 2 枚にして、親の env を安全網に向けたまま
  `tray.ps1 -Port 8811 -NoBrowser -DriveScript fakerepo\drive_probe.ps1`（`-DataDir` 無し）。`fakerepo\.tray\tray.log`:
  `サーバを起動します: ...（... データ置き場 C:\work\image-reviwer\.tmp-tray-recheck\fakerepo\.data）`／
  `[recheck-drive] mode=own data_dir=C:\work\image-reviwer\.tmp-tray-recheck\fakerepo\.data`。
  **写しの「既定の `.data`」＝本物のリポジトリなら実データ**。本物の `tray_drive.ps1` は `POST /api/review-requests` を 1 件打つので、**実データに要求が 1 行書かれる**。
- 同じ道: `-StatusAutoCloseMs`（試験用）も同様。`Restart-Server` は `$script:DataDir`（空）で起こし直すので、最初の起動と同じ置き場になる（ここは整合している）。
- 直し（推奨）: 入口で「**試験用の引数（`-DriveScript`・`-StatusAutoCloseMs`）があるのに `-DataDir` が空、または実データ**」なら起動せずに断る
  （`Get-EffectiveDataDir` の条件を `$script:DefineOnly -or $script:DriveScript` に広げる、が 1 行で済む）。文書の「駆動」も事実に合わせる。

## C. 中程度

### C-1. `Test-RealDataDir` は相対パスを**トレイのプロセスの現在地**で解くが、子は**リポジトリ**で解く

- `tray.ps1:190` は `[System.IO.Path]::GetFullPath($Path)`（＝ .NET のプロセスの現在地。PowerShell の `Set-Location` とは別）で比べ、
  子は `-WorkingDirectory $script:RepoRoot` で起動し、`app.data_dir()` は `Path(os.environ[...])`（相対なら子の現在地＝リポジトリ）を開く。
- 実測（`.tmp-tray-recheck\relpath.ps1` を現在地 `C:\` で起動。サーバは起動していない）: `.data` → `real=False`、`.\.data` → `real=False`。
  同じ `-DataDir .data` を `-DefineOnly` の写しから `Start-OwnServer` に渡すと、**断られずに子がリポジトリの `.data` を開く**（コードの読み。起動はしていない）。
  ほか `\\?\C:\work\image-reviwer\.data`・`\\localhost\C$\...\.data` も `real=False`（8.3 名 `C:\work\IMAGE-~1\DATA~1` は `True`）。
- 今の呼び手（自己検査の `-Replica` は `*.data` を別に断る・競合の再現は絶対パス）では踏まない。**直し**: `Get-EffectiveDataDir` で相対パスを
  `$script:RepoRoot` 基準の絶対パスに直してから比べ、子にも絶対パスを渡す。

### C-2. 自己検査が他人を止め得る道は §10 だけではない（`trap` と §2 の後始末）

- A-1 の直しで 3 か所のポートが正しくなると、今度は `trap`（`:114`）と §2 の後始末（`:253`）が「`--port 8796` を持つ python を**全部**」止める。
  §1 で空きを確かめた後に**他人が**そのポートで立てた物（並行の監査・別の自己検査）も巻き込む。**この検査が起こした PID（`$state.Proc`・`$stranger` など）
  の木だけ**を止める形にする方が A-2 の規律（迷ったら止めない）に合う。

## D. 軽微

- **D-1（文書と実装の食い違い）**: `tray.md` §4.0 C-6 は「既定の `.data` を指していたら**収集の前に止める**」、`conftest.py` は「**止めない**——大きく知らせて上書き」。どちらかに揃える（実装の方が安全なので文書を直す）。
- **D-2（推定を事実として書いている）**: `tray.md` §6 と `design.md` の追記は「控えは `.tmp-tray\backups` へ書かれ、その scratch を消したときに一緒に消えた」「原因はこの段の道具の穴」と**断定**している。前回の報告の A-1 は**推定**（同じ秒の一致から読んだ）で、`triage` §4 も「原因は推定のまま」と書いている。文書の 2 か所に「（推定）」を足す。
- **D-3**: `conftest.py` は `IMAGE_REVIEWER_BACKUP_DIR` を今も `setdefault`。親の値を引き継ぐ型は C-6 と同じ。ただし**親を `.tmp-tray-recheck\bk-net` に向けて 570 件を回しても、そこには何も作られなかった**（実測）ので、実害は確かめられない。揃えるなら上書きに。
- D（確かめた結果、問題なし）:
  - **A-2 の再現 2 通り**（前回の `race.ps1`。偽の `/api/health` を合図で立てる・本物の複製を合図で立てる）: どちらも `init.result=attach`・`ServerPid=0`・**他人は止めた後も生きている**・ログは「別の image-reviewer がポート … を掴みました」「止めません」。前回は 2 通りとも他人が死んだ。
  - **B-1 の即失敗**: 自己検査 §2b が「90 秒も待たない（20 秒未満）」で ok。壊す（M-B1）と 92.2 秒で落ちる。
  - **B-2 の × 印**: 停止中のアイコンの真ん中の画素が「ふつう」と違う（自己検査 §6）。
  - **C-6 の上書き**: 親を安全網に向けたまま pytest 570 件 → **安全網は 0 ファイル**（前回は `setdefault` で 1 件落ち、安全網に DB ができた）。
  - **F-8 の等号**: `gui_layout` の `pending` が `チェック=…(期待 …)` の等号で通る（下の H）。
  - **事後の控え** `.backup/pre-tray-fix-20261019-204253/`: `db.sqlite3` 3,960,832 B・sha256 `50F836CA…`・`deletion_log` 18 列・194 行・461 枚・`quick_check ok`（文書どおり）。
  - **実データ**: `deletion_log` 18 列・`closed_at` が入った行 0・461 枚・判断 3 件・段 1 の 194 行（依頼の前提どおり）。

## E. 設計とのずれ

- **E-1**: `design.md` §16.8 の「検査」の行は「**検査は使う 4 ポートが空いていなければ 1 つも起動せず exit 2**」、`tray.md` §5 の最後の行も同じ。**実装は 8795 だけ**（A-1）。
- **E-2**: `design.md` §4.1「子に渡すデータ置き場（監査 A-1）」の「`-DefineOnly` で読み込んだとき（**自己検査・駆動**）は…断る」は、**駆動には当たらない**（B-1）。
- **E-3**: 実装者が自分で決めた点の判定:
  - 本番は既定の `.data` を**明示して**渡す（E-4 の維持。`tray.md` §4 の穴 9）… **妥当**（消して任せる道は事故の型）。
  - `Exit-Tray` の `-DefineOnly` の seam … **妥当**（本番の道は変えていない。変異 M-F4 が落ちる）。
  - 印とバルーンは段 3 だけ（G-1(b)）… **妥当**。ただしバルーン側は壊しても落ちない（F）。
  - §10 を「偽ではなく本物の複製サーバ」で作った … **条件付き**。トレイ本体の A-2 は見られるが、**検査そのものが `-Proc` 無しで受けて止める**形になった（A-1）。

## F. テストで守れないもの

自己検査の壊し試験（`.tmp-tray-recheck\mut.py`。`tools/tray.ps1` の写しを 1 か所ずつ壊し `tray_selftest.ps1 -TrayScript <写し>` を丸ごと回す。本物は触らない）。

| 変異 | 壊した所 | 結果 | 判定 |
| --- | --- | --- | --- |
| M-A1a（実装者の取り直し） | 空の置き場の断りを外す | NG 1「空のデータ置き場を断る ← 返ってきた: C:\work\image-reviwer\.data」 | 落ちる（実装者と同じ） |
| M-A1c | 親の env を上書きしない | NG 4（decoy を開いた） | 落ちる（同じ） |
| M-A2a | `Wait-ServerUp` の親子確認を外す | NG 3（`result=ours`） | 落ちる（同じ） |
| M-A2b | `Get-OwnServerPids` の親子確認を外す | NG 4 | 落ちる（同じ） |
| M3 | ポートから相手を探して止める | NG 2 | 落ちる（同じ） |
| M-B1 | 子の生死を見ない | NG 1（92.2 秒） | 落ちる（同じ） |
| R12 | `Start-OwnServer` が `-Proc` を渡さない | NG 3 | 落ちる |
| R13 | `Test-DescendantOf` が常に真 | NG 9（**競合の後始末で他人が死んだ**も出る） | 落ちる |
| R14 | `Test-RealDataDir` が常に偽 | NG 4（見本の「実データ」で**起動してしまった**） | 落ちる |
| R1 | `Get-TraySnapshot` の「他人が立った」検出を外す（C-4） | **落ちない** | テストの穴（§5・§8 は手で作った snapshot だけ。本物の応答で `foreign` を作る検査が無い） |
| R2 | 起動直後の `-Quiet` でも失敗を知らせる行を外す（C-1） | **落ちない** | テストの穴（`Refresh-Tray -Quiet` を通る検査が無い） |
| R3 | 3 つの口の待ちを 2 秒 → 15 秒（C-2） | **落ちない** | テストの穴（遅いサーバの検査が無い。前回の `slow_api.py` の形を足す） |
| R3b | 1 つ落ちても残りを打つ（C-2） | **落ちない** | テストの穴（同上） |
| R4 | 死んだ踏み台にも `taskkill` を打つ（C-3） | **落ちない** | **等価**に近い（ハンドルを持っているので PID は再利用されず、撃っても空振り） |
| R5 | 前の 1 世代のログを残さない（D-6） | **落ちない** | テストの穴（小） |
| R6 | ログをポートごとに分けない（D-8） | **落ちない** | テストの穴（小。検査がログの場所を `$script:ServerLog` で上書きしている） |
| R7 | `PYTHONUNBUFFERED` を渡さない（D-7） | **落ちない** | テストの穴（小） |
| R8 | 起動に失敗した子を片付けない（`Initialize-ServerState`） | **落ちない** | テストの穴（§2b は `Start-OwnServer` を直に呼ぶので、`Initialize-ServerState` の後始末を通らない） |
| R10 | `Exit-Tray` が「他人が立った形」を見ない | **落ちない** | 安全は `Get-OwnServerPids` が守るので**止める相手は変わらない**。語と待ち時間だけ違う＝テストの穴（小） |
| R11 | `Restart-Server` が「他人が立った形」を見ない | **落ちない** | テストの穴（自己検査に再起動の道が 1 本も無い） |
| R16 | 削除のバルーンを全部の数で数える（G-1(b)） | **落ちない** | テストの穴（印は M-C5 が守るが、バルーンは守っていない） |
| R17 | ツールチップの「件数を確かめられません」を外す | **落ちない** | テストの穴（小） |

- **静的な検査の限界の実例**: `test_the_selftest_never_opens_the_real_data` は文字列「使う 4 つのポートは空いている」と「`exit 2`」があることを見て**通る**が、振る舞いは A-1 のとおり壊れている。**推奨**: pytest か自己検査の外側に「`$Port + 1` を偽の `/api/health` で埋めて `tray_selftest.ps1` を子で回し、**exit 2・`--port 879[5-8]` の image_reviewer が 0・偽が生きている**」を見る振る舞いの検査を 1 本（今回の再現そのもの。約 15 秒）。
- 数え方: 実装者は「13 通りすべて落ちる」。こちらで取り直した 6 通りは件数まで同じ。**ただし 13 通りは全部「直した所を外す」形で、直した所の周りの道（Quiet・遅い口・再起動・後始末）を壊す変異が無い**ので、「全部落ちる」は守れている範囲の広さを示さない。

## G. 依頼者への質問

| 論点 | 選択肢 | 推奨 |
| --- | --- | --- |
| G-1 A-1 の直し方 | (a) 3 か所の括弧だけ ／ (b) (a)＋§10 を `-Proc $stranger` で受けて子孫だけ止める ／ (c) (b)＋後始末をこの検査が起こした PID の木だけにする（C-2） | **(c)**。(a) だけだと、括弧を直した途端に `trap` と §2 の後始末が「そのポートの python を全部」止める形になる |
| G-2 駆動の断り（B-1） | (a) `-DriveScript`・`-StatusAutoCloseMs` があれば `-DataDir` 必須・実データは断る ／ (b) 文書だけ直す | **(a)**。1 行で済み、`tray_drive.ps1` は書く口を打つ |
| G-3 F の穴をどこまで埋めるか | (a) R1・R2・R3・R8・R11 の 5 つ（知らせと失敗の道）＋A-1 の振る舞いの検査 ／ (b) 全部 ／ (c) 今回は A・B だけ | **(a)**。R5〜R7・R17 は小さく、R4 は等価 |
| G-4 次の再確認の範囲 | (a) A-1・B-1 と足した検査だけ ／ (b) 全部をもう一度 | **(a)**。それ以外は今回の回帰で通っている |

## H. 確かめられなかったこと・証拠・後始末

- **人はマウスで押していない**（前回と同じ）。トレイの UI は今回は駆動の 1 回（`fakerepo` の起動と終了）しか動かしていない。`tray_drive.ps1` の通しは回していない（B-1 の再現は自前の `drive_probe.ps1`）。
- **C-1 の相対パスで本物の子を起こしてはいない**（起こすと実データを開くため。予測はコードの読み）。
- **A-1 の 16:48:56 の原因が推定のままである点は変わらない**（D-2）。

### 実行したコマンドと結果

| 何を | 結果 |
| --- | --- |
| 実データの署名（前） `.tmp-tray-audit\sig.py`（`mode=ro`） | `user_version 6`・461 枚・判断 3・段 1 の 194 行・`closed_at` 列あり・`-wal` 4,190,072 B / mtime 16:48:56（前回の事故の時刻のまま）・`.backup` 12 個・画像 268 枚 `images_hash 5fb3fe48…` |
| `pytest -q`（1 回目。親に安全網） | **570 passed**（41.7 s）。安全網 0 ファイル |
| `pytest -q`（2 回目。親に安全網＋`IMAGE_REVIEWER_BACKUP_DIR=bk-net`） | **570 passed**（59.6 s）。`bk-net` は作られない |
| `pytest -q`（3 回目。gui_layout の後） | **570 passed**（42.5 s） |
| `node tools/gui_smoke.mjs` | **406 ok / NG 0** |
| `tray_selftest.ps1 -Port 8795`（ポートが空いているとき） | **ok 115 / NG 0**・exit 0・66 s |
| 同（8795 / 8796 / 8796 本物 / 8798 を埋める） | exit 2 / 1 / 1 / 1（A-1 の表） |
| `.tmp-tray-audit\race.ps1 -Port 8821 -Mode fake`・`-Port 8822 -Mode real`（前回の A-2 の再現） | 2 通りとも `attach`・`ServerPid=0`・**他人は生存** |
| 壊し試験 `.tmp-tray-recheck\mut.py`（22 通り＋R4 の作り直し 1） | F の表。R4 の最初の版は自分の書き損じ（`else` が残って構文エラー＝exit 3）で、作り直して「落ちない」 |
| `gui_layout` 11 本 × 4 幅（複製 `.tmp-tray-recheck\rA`・8792。`run_gl.ps1` は実装者の物の写しでポートと置き場だけ変えた。PowerShell から直に。複製のパス 1,114 個はすべて複製の中） | **52 ok / NG 0**（compare 12・ほか 10 本 × 4）。`pending` は **rows=195（段 3 が 1 行）・`チェック=194(期待 194)`** が 4 幅とも＝**前回 NG だった形がそのまま等号で通る**（F-8 は直った） |
| 実データの署名（後） | 前と**一致**。違うのは `db.sqlite3-shm` の mtime だけ（`mode=ro` で開くと触られる。前回も同じ）。`db.sqlite3` 3,301,376 B・`-wal` 4,190,072 B / 16:48:56 は**そのまま**。`.backup` 12 個・画像 268 枚の署名も同じ |

- 証拠の注記: gui_layout の種まき（`gui_layout_seed.py`）が「群を引けませんでした（database is locked）。phash のある 2 枚で代用します」と出した。複製を開いているのは種まき自身だけの時刻で、**理由は確かめていない**（結果の 52 ok には響いていない）。

### 後始末

- 止めた物: 自己検査・変異・競合の再現・占有の再現・駆動の再現・gui_layout が起こした python は全部止めた（最後に `--port`・`fake_health`・`bystander` を持つ python が **0**、8790〜8899 に LISTENING **0** を確認）。
- 残した物（`.gitignore` に無いので注意）: `.tmp-tray-recheck/`（`mut.py`・`mut/<名前>/{tray.ps1,out.txt}`・`selftest-*.log`・`relpath.ps1`・`fakerepo/`（`.venv` のジャンクションは**外した**。B-1 の再現を再び回すなら作り直す）・`rA/`（実データの複製。画像 268 枚の写しを含む）・`occ-real/`・`sig-*.json`・`run_gl.ps1`・`mk_replica.py`）。
- 自己検査が使う `.tmp-tray/`（`replica` は検査が消す。`decoy`・`pretend-real-data`・`log` は残る）。
- `src/`・`tools/`・`tests/` の mtime は監査の最初と同じ（`tray.ps1` 21:33:17 ほか）。git のコミットはしていない。

---

### 最も重大な 3 件（再掲）

1. **A-1** `tray_selftest.ps1` の 4 ポートの確認（と 2 つの後始末）は `@($Port, $Port + 1, …)` が 7 要素 `8795,8795,1,8795,2,8795,3` になり **8795 しか見ない**。8796 に本物の image-reviewer を立てると exit 2 にならず、**§10 の後始末がそれを止めた**。データは無事（env 無しの起動は 0）。直しは括弧 3 か所＋§10 を `-Proc` 付きで受ける。
2. **B-1** `tray.ps1 -DriveScript` は `-DefineOnly` ではないので、`-DataDir` を忘れると既定の `.data` を開く（写しのリポジトリで実測）。`tray_drive.ps1` は `POST` するので実データに書く道。文書の「駆動も断る」は事実と違う。
3. **F** 監査側の変異 16 通りのうち 13 通りが落ちない（うち 1 つは等価。C-1・C-2・C-4・起動失敗の後始末・再起動・バルーンほか）。芯の 6 通り（A-1・A-2・B-1）は実装者と同じ件数で落ちる。
