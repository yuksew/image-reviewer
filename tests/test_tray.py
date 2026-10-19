"""トレイ（タスクトレイ常駐）の**契約**のテスト。

トレイそのものは PowerShell（`tools/tray.ps1`）で、**サーバを立てて動かす検査**は
`tools/tray_selftest.ps1`（自動）と `tools/tray_drive.ps1`（実メニューを押す）が受け持つ。
ここは**道具だてが揃っているか・家風を破っていないか**を、ファイルを読むだけで見る
（遅くしない・サーバを立てない・実データに触らない）。

壊すと落ちる物:

- `.cmd` から `-ExecutionPolicy Bypass` を外す → **この環境では .ps1 が素で実行できず、
  ショートカットが無言で何も起きなくなる**（実測。`docs/tray.md`）
- `.ps1` の BOM を外す → Windows PowerShell 5.1 が cp932 として読み、日本語の文字列が
  壊れて構文エラーになる（実測。`tools/tray.ps1` を `edit` で書き換えると BOM が落ちる）
- トレイのログを `<data>` の中や `%USERPROFILE%` の下へ移す → **実データを汚す**・
  この環境では書けない
- 「ポート 8790 を止める」道を足す → **利用者のサーバを巻き込む**
- 文書から「トレイは作った」を消す／古い「常駐の実装が無い」を戻す → 利用者に
  「無い物が有る」「有る物が無い」と読ませる（P8-5 が直した型）
"""

from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
TOOLS = REPO / "tools"

#: 生きている文書（**履歴の文書は対象外**。当時の記録はそのまま残す）
LIVING_DOCS = [
    REPO / "README.md",
    REPO / "docs" / "frontend-design.md",
    REPO / "docs" / "design.md",
    REPO / "docs" / "handoff.md",
    REPO / "docs" / "tray.md",
]


def read(path: Path) -> str:
    """UTF-8 として読む（BOM は落とす）。"""
    return path.read_text(encoding="utf-8-sig")


# ---- 1. 道具だてが揃っている ----


def test_the_tray_tools_are_in_place():
    """**トレイの 4 つが揃っている**（入口・本体・自動の検査・押す手順）。

    壊すと落ちる: どれかを消す（利用者の入口が無くなる／検査が回せなくなる）。
    """
    for name in ["image-reviewer-tray.cmd", "start-image-reviewer.cmd",
                 "start-image-reviewer-console.cmd"]:
        assert (REPO / name).is_file(), f"{name} が無い"
    for name in ["tray.ps1", "tray_selftest.ps1", "tray_drive.ps1"]:
        assert (TOOLS / name).is_file(), f"tools/{name} が無い"
    assert (REPO / "docs" / "tray.md").is_file(), "docs/tray.md が無い"


def test_the_powershell_scripts_are_utf8_with_bom():
    """**`.ps1` は UTF-8 の BOM 付きで保存する**（Windows PowerShell 5.1 の読み方）。

    壊すと落ちる: BOM を外す。5.1 は BOM の無い `.ps1` を **cp932 として読む**ので、
    日本語の文字列が壊れて**構文エラーになる**（実測: `edit` で書き換えた直後に踏んだ）。
    テキストの中身が UTF-8 であること（日本語が読めること）も一緒に見る。
    """
    for name in ["tray.ps1", "tray_selftest.ps1", "tray_drive.ps1"]:
        raw = (TOOLS / name).read_bytes()
        assert raw[:3] == b"\xef\xbb\xbf", f"tools/{name} に BOM が無い"
        text = raw.decode("utf-8-sig")
        assert text.startswith("#Requires -Version 5.1") or text.startswith("# "), name
        assert "function " in text, f"{name} に関数が無い（読めていない）"
        assert "駆動" in text or "トレイ" in text or "検査" in text, f"{name} の日本語が読めない"


def test_the_cmd_entries_pass_the_execution_policy():
    """**`.cmd` は `-ExecutionPolicy Bypass` を付ける**（この環境では必須）。

    壊すと落ちる: 外すと `powershell -File tools\\tray.ps1` が
    「not digitally signed」で断られ、**ダブルクリックしても何も起きない**
    （実測: RemoteSigned でも Unrestricted でも断られ、Bypass だけが通った）。
    """
    tray_cmd = read(REPO / "image-reviewer-tray.cmd")
    assert "-ExecutionPolicy Bypass" in tray_cmd
    assert r"tools\tray.ps1" in tray_cmd
    assert "-Port 8790" in tray_cmd
    assert "UV_CACHE_DIR" in tray_cmd, "uv のキャッシュをリポジトリへ向けていない"


def test_the_default_entry_starts_the_tray_and_the_console_one_stays():
    """**既定はトレイ。コンソールの起動も残す**（利用者の環境を勝手に変えない）。

    壊すと落ちる: `start-image-reviewer.cmd`（デスクトップのショートカットの的）から
    トレイを外す／コンソールの道を消す。
    """
    default_cmd = read(REPO / "start-image-reviewer.cmd")
    assert "image-reviewer-tray.cmd" in default_cmd, "既定がトレイを呼んでいない"
    console_cmd = read(REPO / "start-image-reviewer-console.cmd")
    assert "uv run --no-sync image-reviewer serve --port 8790" in console_cmd
    assert "http://127.0.0.1:8790" in console_cmd, "ブラウザを開く行が消えている"
    assert "pause" in console_cmd, "窓が閉じる前に止まる行が消えている"


# ---- 2. 依存と書き込み先 ----


def test_the_tray_adds_no_dependency_and_no_binary():
    """**新しい依存を足さない**（PowerShell と .NET の `NotifyIcon` だけで足りる）。

    壊すと落ちる: `pystray` / `PyInstaller` を頼る（`pyproject.toml` と `uv.lock` が増え、
    利用者の環境で `uv sync` が要る）。トレイのアイコンも**ファイルを増やさず**描く。
    """
    tray = read(TOOLS / "tray.ps1")
    assert "System.Windows.Forms.NotifyIcon" in tray
    assert "System.Drawing" in tray, "アイコンをその場で描いていない"
    # 実際に使うのは .NET（`Add-Type`）。**外の道具を呼んでいない**（呼び出しの行で見る）
    assert "Add-Type -AssemblyName System.Windows.Forms" in tray
    assert "Add-Type -AssemblyName System.Drawing" in tray
    for bad in ["pip install", "python -m pystray", "PyInstaller.exe"]:
        assert bad not in tray, f"{bad} を呼んでいる"
    pyproject = read(REPO / "pyproject.toml").lower()
    assert "pystray" not in pyproject, "pyproject.toml に依存が足されている"
    assert "pyinstaller" not in pyproject, "pyproject.toml に依存が足されている"


def test_the_tray_writes_only_under_the_repository():
    """**書き込みは `<リポジトリ>\\.tray\\` だけ**（`.data` と `%USERPROFILE%` は触らない）。

    壊すと落ちる: ログを `<data>` の中へ移す（**実データを汚す**）／
    `%USERPROFILE%` の下へ作る（**この環境ではアプリのプロセスが書けない**＝既知の罠）。
    """
    tray = read(TOOLS / "tray.ps1")
    assert "$script:LogDir = Join-Path $script:RepoRoot '.tray'" in tray
    assert "USERPROFILE" not in tray, "%USERPROFILE% の下に書こうとしている"
    # トレイは DB を直に開かない（読むのは HTTP だけ）。書き込みはログの 1 本だけ
    assert "sqlite" not in tray
    assert "Set-Content" not in tray and "Add-Content" not in tray
    assert "AppendAllText" in tray
    # データ置き場は**表示にだけ**使う（書き込みの経路を作らない）
    assert "health.data_dir" in tray


def test_the_tray_always_names_the_data_dir_it_opens():
    """**子に渡す `IMAGE_REVIEWER_DATA` は必ずこの道具が明示する**（監査 A-1 の①）。

    壊すと落ちる: `Remove-Item Env:IMAGE_REVIEWER_DATA` で「既定に任せる」道を戻す
    （`cli serve` が既定の `.data` を開くので、**検査の事故がそのまま実データに届く**）。
    併せて、**試験用の引数（`-DefineOnly`・`-DriveScript`・`-StatusAutoCloseMs`）**では
    **空の置き場と実データを断る**ことを見る（**再確認 B-1**: 駆動も同じ断りを通す）。
    **相対パスは子と同じ基準（リポジトリ）で解く**ことも見る（**再確認 C-1**）。
    """
    tray = read(TOOLS / "tray.ps1")
    assert "Remove-Item Env:IMAGE_REVIEWER_DATA" not in tray, "既定に任せる道が残っている"
    assert "$env:IMAGE_REVIEWER_DATA = $where" in tray, "子に置き場を明示していない"
    assert "function Get-EffectiveDataDir" in tray
    assert "function Test-RealDataDir" in tray
    # `-DefineOnly` で読み込まれたら、空も実データも断る（1 プロセスも起動しない）
    assert "$script:DefineOnly = [bool]$DefineOnly" in tray
    assert "実データ（{0}）を開こうとしています" in tray
    assert "既定の .data を開く道を通しません" in tray
    # **（再確認 B-1）駆動も断る**: 試験用の引数をまとめた 1 つの印で見る
    assert "$script:TestArgs = [bool](" in tray, "試験用の引数の印が無い"
    assert "$script:TestArgs -or" in tray or "($script:DefineOnly -or $script:TestArgs)" in tray, \
        "`-DriveScript` が断りの条件に入っていない（駆動はトレイを丸ごと起こす）"
    assert "試験用の起動を断ります" in tray, "入口で断る行が無い"
    # **（再確認 C-1）相対パスを子と同じ基準で解く**
    assert "function Resolve-DataDirPath" in tray
    assert "Resolve-DataDirPath -Path $DataDir" in tray, "渡された置き場を絶対パスにしていない"
    assert "[System.IO.Path]::IsPathRooted($Path)" in tray
    # 前の 1 世代のログを残し、ポートごとに分ける（監査 D-6・D-8）
    assert "Move-TrayLogAside" in tray
    assert "Get-ServerLogPaths" in tray


def test_the_tray_stops_only_its_own_child():
    """**止めるのは自分の子の木の中だけ**（監査 A-2）。親子関係で確かめる。

    壊すと落ちる: `Wait-ServerUp` が「`app` が image-reviewer」だけで受け取る／
    `Get-OwnServerPids` が同一性と親子を見ない（**起動の競合で他人のサーバを `/F` で止める**）。
    """
    tray = read(TOOLS / "tray.ps1")
    assert "function Get-ProcessParentId" in tray
    assert "function Test-DescendantOf" in tray
    assert "Test-DescendantOf -ProcessId ([int]$st.pid) -AncestorId ([int]$Proc.Id)" in tray
    assert "Test-DescendantOf -ProcessId ([int]$st.pid) -AncestorId ([int]$State.Proc.Id)" in tray
    assert "-Proc $proc" in tray, "起動の待ちに自分の子を渡していない"
    assert "if ($Proc.HasExited) { return $null }" in tray, "子が落ちても待ち続ける（監査 B-1）"
    assert "state = 'stranger'" in tray, "自分の子でない相手を attach に落としていない"
    # 死んだ PID は撃たない（監査 C-3）
    assert "if (-not $State.Proc.HasExited) { $pids += [int]$State.Proc.Id }" in tray


def test_the_selftest_never_opens_the_real_data():
    """**自己検査は、置き場を明示せずにサーバを 1 つも起動しない**（監査 A-1）。

    壊すと落ちる: §10 の「他人のサーバ」を環境変数なしで起こす（ポートが埋まっていると
    §2 が `attach` になり、**既定の `.data` を開く**＝実際に起きた事故）。

    **（再確認 A-1・C-2）**「使う 4 つのポートを 4 つとも見る」形と、**後始末がこの検査の子だけを
    止める**形が残っているかも見る。静的な検査だけでは**振る舞い**を守れないので、
    `tests/test_tray_ports.py` が本物の検査を子で回して確かめる（監査 F の指摘）。
    """
    selftest = read(TOOLS / "tray_selftest.ps1")
    # ① 置き場をこの検査が自分で立てる（親からの引き継ぎに頼らない）
    assert "$env:IMAGE_REVIEWER_DATA = $Replica" in selftest
    # ② 使うポートが空いていなければ、1 つも起動せずに止まる
    assert "使う 4 つのポートは空いている" in selftest
    assert "exit 2" in selftest
    # **（再確認 A-1）カンマは `+` より強い**ので、括弧の無い `@($Port, $Port + 1, …)` は
    # 7 要素になり **8795 しか見ない**（実測 count=7）。括弧付きの形だけを許す。
    # **コメントは見ない**（何が起きるかを説明するために、悪い形を引用している）。
    # ブロックコメント `<# … #>` と行コメント `#` を落としてから見る。
    stripped = re.sub(r"<#.*?#>", "", selftest, flags=re.S)
    code = "\n".join(ln for ln in stripped.splitlines() if not ln.lstrip().startswith("#"))
    assert "@($Port, ($Port + 1), ($Port + 2), ($Port + 3))" in code
    assert "@($Port, $Port + 1" not in code, "括弧の無い形（7 要素になる）が戻っている"
    # **（再確認 C-2）後始末は、この検査が起こした物（Register-OwnProcess）の木だけ**。
    # ポートを数えて `--port <Port>` の python を止める形は、同じポートの他人を巻き込む。
    assert "function Register-OwnProcess" in selftest
    assert "function Stop-OurProcesses" in selftest
    assert selftest.count("Stop-OurProcesses") >= 3, "trap・§2・まとめで後始末を通していない"
    assert "foreach ($p in @($Port" not in code, "ポートを数えて止める後始末が戻っている"
    # ③ §2 が自分で起動しなかったら、そこで止める（以降の検査を進めない）
    assert "'自分で起動した（own）' ($init.result -eq 'own')" in selftest
    # ④ 実データを指したら起動しない（本物の .data では試さず、見本を向けて確かめる）
    assert "実データ（既定の置き場）を指したら起動しない" in selftest
    assert "pretend-real-data" in selftest, "本物の .data で断りを試そうとしている"
    # ⑤ 子が落ちたら待たない・競合では他人を持たない・メニューの終了の道も見る
    assert "90 秒も待たない" in selftest
    assert "競合では他人の pid を持たない" in selftest
    assert "メニューの終了の道でも本体が消えた" in selftest
    # **（再確認 R1・R2・R3・R8・R11）** 直した所の周りの道も見る（監査 F の「13 通りが落ちない」）
    for name in ["他人が立った形を見つける", "バックアップの失敗を知らせる",
                 "見切りは 2 秒", "残りの口を打たない", "持っていた子は片付ける",
                 "他人が立った形では再起動しない"]:
        assert name in selftest, f"「{name}」の検査が無い（監査 F の穴）"


def test_the_tray_docs_record_the_real_data_accident():
    """**実データに起きたことを、事実のまま書いてある**（監査 A-1・G-4）。

    壊すと落ちる: 「実データは無傷」を戻す（**列が 2 つ足りて控えが無い**という事実を隠す）。
    利用者に「何も起きていない」と読ませない（P8-4・P8-6 と同じ型の事故）。
    """
    tray_doc = read(REPO / "docs" / "tray.md")
    assert "実データは無傷" not in tray_doc, "tray.md に古い「無傷」が残っている"
    assert "closed_at" in tray_doc and "close_reason" in tray_doc
    assert "控え" in tray_doc
    handoff = read(REPO / "docs" / "handoff.md")
    assert "closed_at` / `close_reason` の列はまだ無い" not in handoff
    assert "2026-10-19 16:48" in handoff, "事故の時刻が記録に無い"


# ---- 3. 家風（止める・文言） ----


def test_the_tray_stops_only_what_it_started():
    """**止めるのは自分が起動した物だけ。** ポートから相手を探す道を作らない。

    壊すと落ちる: ポート番号で相手を探して止める実装にする（利用者が自分で立ち上げた
    8790 のサーバを、トレイが巻き込んで止める）。`tools/tray_selftest.ps1` の検査 9・10 が
    実物でこれを見る（この検査は**その前提がコードに残っているか**を見る）。
    """
    tray = read(TOOLS / "tray.ps1")
    assert "Get-OwnServerPids" in tray
    assert "taskkill" in tray
    assert "/T /F" in tray, "木ごと止めていない（踏み台が残る）"
    for bad in ["Get-NetTCPConnection", "netstat", "Stop-Process -Name"]:
        assert bad not in tray, f"{bad} で相手を探している（ポートから止める道）"
    assert "ServerPid" in tray, "本体の pid を持っていない（shim の子を見落とす）"

def test_the_menu_labels_follow_the_wording_rules():
    """**メニューの文言が `frontend-design.md` §6.1 に従っている。**

    壊すと落ちる: 半角の中点 `·` や `—` を使う／「用意」「準備」を使う／
    ボタンを名詞にして「何が起きるか」を言わなくする。
    """
    tray = read(TOOLS / "tray.ps1")
    labels = re.findall(r"Items\.Add\('([^']*)'\)", tray)
    assert labels[:5] == ["ブラウザで開く", "最近の削除を開く", "状態を見る",
                          "再起動する", "終了する（サーバも止める）"], labels
    joined = "".join(labels)
    assert "\u00b7" not in joined, "半角の中点を使っている"
    assert "\u2014" not in joined, "ダッシュで繋いでいる"
    assert "用意" not in joined and "準備" not in joined
    assert "トレイを閉じる（サーバは止めない）" in tray, "添付のときの語が無い"


def test_the_status_text_always_shows_a_backup_failure():
    """**バックアップの失敗は必ず出す**（家風「黙って失敗しない」）。

    壊すと落ちる: `New-StatusText` から失敗の行を消す（`tools/tray_selftest.ps1` の検査 5 が
    実物で見る。ここは**その行が実装に残っているか**を見る）。
    """
    tray = read(TOOLS / "tray.ps1")
    assert "バックアップに失敗しています" in tray
    assert "$Snapshot.backup_failed" in tray
    assert "$Snapshot.backup.last_error" in tray, "失敗の全文を出していない"


# ---- 4. 検査の道具そのもの ----


def test_the_selftest_refuses_the_users_port():
    """**自動の検査は 8790 を使わない**（利用者のサーバを巻き込まない）。

    壊すと落ちる: 既定のポートを 8790 にする（検査が利用者のサーバを止めたり、
    「既に動いている」を見て素通りしたりする）。
    """
    selftest = read(TOOLS / "tray_selftest.ps1")
    assert "[int]$Port = 8795" in selftest
    assert "8790 は利用者のサーバのポート" in selftest, "8790 を断る行が無い"
    drive = read(TOOLS / "tray_drive.ps1")
    assert "function Invoke-TrayDrive" in drive
    assert "PerformClick()" in drive, "実物のメニューを押していない"
    assert "$DriveScript" in read(TOOLS / "tray.ps1"), "押す手順を読む口が無い"


def test_the_living_docs_say_the_tray_is_there():
    """**生きている文書に「トレイは作った」が書いてある**（正を先に）。

    壊すと落ちる: 古い「常駐の実装がリポジトリに無い」を戻す。
    利用者に「無い物が有る」と読ませない（P8-5 が直した型。`docs/p8-5-implementation.md`）。
    """
    for path in LIVING_DOCS:
        text = read(path)
        assert "常駐の実装がリポジトリに無い" not in text, f"{path.name} に古い 1 行が残っている"
    assert "tools/tray.ps1" in read(REPO / "docs" / "tray.md")
    assert "image-reviewer-tray.cmd" in read(REPO / "README.md")
    assert "tools/tray.ps1" in read(REPO / "docs" / "design.md")
    assert "tools/tray.ps1" in read(REPO / "docs" / "frontend-design.md")
