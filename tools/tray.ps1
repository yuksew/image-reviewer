#Requires -Version 5.1
<#
.SYNOPSIS
    image-reviewer のトレイ（タスクトレイ常駐）。

.DESCRIPTION
    常駐の入口。**新しい依存を足さない**（Windows に元からある PowerShell と .NET の
    `System.Windows.Forms.NotifyIcon` だけで足りる。`pystray` も PyInstaller も要らない）。

    すること:

    1. `GET /api/health` で**既に動いているサーバを探す**（設計 `docs/design.md` §4.1）。
       応答が自分（`app: "image-reviewer"`）なら**二重に起動せず、それに繋ぐ**。
       別のアプリなら**起動しない**（相手を止めない・黙って別のポートへ移らない）。
    2. 誰も居なければ `image-reviewer serve --port <Port>` を**子プロセスとして**起動する。
       `.venv\Scripts\python.exe` があればそれで直に起動する（**1 プロセスで止められる**。
       `uv run` は uv → ランチャ → python の 3 段で、親を止めても python が残る。
       `README.md`「止めた直後に `export/groups/*.json` を読むなら 1 秒待つ」）。
    3. トレイにアイコンを出し、5 秒ごとに状態を見て、アイコンの形とツールチップを変える。
       **要求あり**（`--accent` の印）／**取り消せる削除あり**（`--warn` の印）／
       **両方**／**バックアップに失敗**（枠が `--drop`。**黙って失敗しない**）。
    4. メニューは 5 つ（**文言は `docs/frontend-design.md` §6.1 の規約に従う**）:
       「ブラウザで開く」「最近の削除を開く」「状態を見る」「再起動する」「終了する（サーバも止める）」。
       **アイコンのダブルクリックでも開く。**
    5. **終了では自分が起動したサーバだけを止める**（既に動いていたサーバは PID を知らないので
       触れない。ポート番号から相手を探して止める道は作らない）。

    記録は `<リポジトリ>\.tray\tray.log` と `server.log` / `server.err.log`
    （**`.data` には 1 バイトも書かない**）。

.PARAMETER Port
    サーバのポート（既定 8790）。

.PARAMETER DataDir
    子プロセスに渡す `IMAGE_REVIEWER_DATA`（試験で複製を指すため。既定は空＝実データ）。

.PARAMETER NoBrowser
    起動時にブラウザを開かない（試験と、手で開きたいとき用）。

.PARAMETER DriveScript
    **試験用。** 人がメニューを押す代わりに、指定した .ps1 を読み込んで実メニューを操作する
    （`tools\tray_drive.ps1`）。ダイアログは出さずログに書く。

.PARAMETER StatusAutoCloseMs
    **試験用。** 「状態を見る」の窓を自動で閉じるまでのミリ秒（0 なら人が閉じるまで開く）。

.PARAMETER DefineOnly
    **試験用。** 関数を定義するだけで、トレイを起動しない（`. .\tools\tray.ps1 -DefineOnly`）。

.EXAMPLE
    powershell -NoProfile -ExecutionPolicy Bypass -File tools\tray.ps1 -Port 8790

.NOTES
    設計: `docs/tray.md`、`docs/design.md` §4.1、`docs/frontend-design.md` §4.5・§4.6・§11。
#>
[CmdletBinding()]
param(
    [int]$Port = 8790,
    [string]$DataDir = '',
    [switch]$NoBrowser,
    [string]$DriveScript = '',
    [int]$StatusAutoCloseMs = 0,
    [int]$DriveDelayMs = 1200,
    [switch]$DefineOnly
)

Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing

# ---- 定数 ----

$script:AppName = 'image-reviewer'
$script:RepoRoot = Split-Path -Parent $PSScriptRoot
$script:LogDir = Join-Path $script:RepoRoot '.tray'
$script:TrayLog = Join-Path $script:LogDir 'tray.log'
$script:ServerLog = Join-Path $script:LogDir 'server.log'
$script:ServerErrLog = Join-Path $script:LogDir 'server.err.log'
$script:Utf8 = New-Object System.Text.UTF8Encoding($false)
$script:PollMs = 5000
#: サーバが落ちている間の周期。**この環境は「誰も居ないポートへの接続」に約 2 秒かかる**
#: （生の TcpClient で実測 2015〜2052 ms）。5 秒ごとに 2 秒固めるとメニューが重くなるので、
#: 落ちている間だけ延ばす（上がっているときは 5 秒のまま。`apps/gui/badge.js` と同じ周期）
$script:PollDownMs = 15000

#: 画面（`apps/gui/styles.css`）と同じ色を使う（暗い方を採る。タスクトレイでも読める明るさ）
$script:ColorAccent = [System.Drawing.Color]::FromArgb(255, 84, 182, 194)
$script:ColorWarn = [System.Drawing.Color]::FromArgb(255, 201, 160, 63)
$script:ColorDrop = [System.Drawing.Color]::FromArgb(255, 201, 112, 95)
$script:ColorBase = [System.Drawing.Color]::FromArgb(255, 71, 85, 105)
$script:ColorDown = [System.Drawing.Color]::FromArgb(255, 120, 126, 136)

$script:IconCache = @{}
$script:Ctx = $null
$script:StatusForm = $null

# ---- 記録 ----

function Write-TrayLog {
    <# `.tray\tray.log` に 1 行足す（**`.data` には書かない**）。 #>
    param([string]$Message)
    $line = '{0} {1}' -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $Message
    try {
        if (-not (Test-Path -LiteralPath $script:LogDir)) {
            New-Item -ItemType Directory -Force -Path $script:LogDir | Out-Null
        }
        [System.IO.File]::AppendAllText($script:TrayLog, $line + [Environment]::NewLine, $script:Utf8)
    } catch {
        # 記録できないことでトレイを止めない
    }
    if ($script:EchoLog) { Write-Output $line }
}

function Get-ServerLogTail {
    <# サーバが立ち上がらなかったときに、ログの末尾を 1 つの文字列で返す。 #>
    param([int]$Lines = 10)
    $got = New-Object System.Collections.Generic.List[string]
    foreach ($p in @($script:ServerErrLog, $script:ServerLog)) {
        if (Test-Path -LiteralPath $p) {
            try {
                $all = [System.IO.File]::ReadAllLines($p, [System.Text.Encoding]::UTF8)
                if ($all.Count -gt 0) {
                    $got.Add(('--- {0} ---' -f (Split-Path -Leaf $p)))
                    foreach ($l in ($all | Select-Object -Last $Lines)) { $got.Add($l) }
                }
            } catch { }
        }
    }
    if ($got.Count -eq 0) { return '（ログが空です）' }
    return ($got -join [Environment]::NewLine)
}

# ---- HTTP（読むだけ。`GET` は 1 バイトも書かない家風に合わせる）----

function Invoke-Api {
    <#
        `GET http://127.0.0.1:<Port><Path>` を 1 回打つ。

        **番号が 2xx でなくても本文を読む**（`GET /api/backup` は読み取り専用のとき 503 で
        本文に理由が入っている）。繋がらないときは `status = 0` と `error` を返す。
        **`X-Image-Reviewer-Actor: human` を付ける**（`frontend-design.md` §10。読むだけの口でも
        名乗らないと `actor_of()` が `agent` と見る）。
    #>
    param(
        [Parameter(Mandatory)][int]$Port,
        [Parameter(Mandatory)][string]$Path,
        [int]$TimeoutSec = 5
    )
    $url = 'http://127.0.0.1:{0}{1}' -f $Port, $Path
    $res = $null
    try {
        $req = [System.Net.HttpWebRequest]::Create($url)
        $req.Method = 'GET'
        $req.Timeout = $TimeoutSec * 1000
        $req.ReadWriteTimeout = $TimeoutSec * 1000
        $req.KeepAlive = $false
        $req.UserAgent = 'image-reviewer-tray'
        # **プロキシを通さない**（相手はいつも 127.0.0.1 なので要らない）。
        # 注: **この環境では「誰も居ないポートへの接続」そのものが約 2 秒かかる**
        # （生の `TcpClient` で実測 2015〜2052 ms。`Proxy` の有無とは別。生きているポートへは
        # 0 ms で繋がる）。だから待ちは 3 秒にしてある（`Get-ServerState`）。
        $req.Proxy = $null
        $req.Headers.Add('X-Image-Reviewer-Actor', 'human')
        $res = $req.GetResponse()
    } catch [System.Net.WebException] {
        $res = $_.Exception.Response
        if ($null -eq $res) {
            return @{ ok = $false; status = 0; body = $null; text = ''
                       error = [string]$_.Exception.Status; message = $_.Exception.Message }
        }
    } catch {
        return @{ ok = $false; status = 0; body = $null; text = ''
                   error = 'error'; message = $_.Exception.Message }
    }
    $status = 0
    $text = ''
    try {
        $status = [int]$res.StatusCode
        $reader = New-Object System.IO.StreamReader($res.GetResponseStream(), [System.Text.Encoding]::UTF8)
        $text = $reader.ReadToEnd()
        $reader.Close()
    } catch {
        $status = 0
    } finally {
        if ($null -ne $res) { $res.Close() }
    }
    $body = $null
    if ($text) {
        try { $body = $text | ConvertFrom-Json } catch { $body = $null }
    }
    return @{ ok = ($status -ge 200 -and $status -lt 300); status = $status; body = $body
              text = $text; error = ''; message = '' }
}

function Get-ServerState {
    <#
        `/api/health` で「誰か居るか」を確かめる（設計 §4.1。**ポートが使えるかでは判定しない**）。

        - `ours`   … 自分（`app: "image-reviewer"`）。**二重に起動しない**
        - `none`   … 繋がらない（接続拒否）＝自分が起動してよい
        - `other`  … 別のアプリが応答した／応答が返らない。**起動しない**（相手を止めない）
    #>
    param([Parameter(Mandatory)][int]$Port)
    $r = Invoke-Api -Port $Port -Path '/api/health' -TimeoutSec 3
    if ($r.status -gt 0 -and $r.ok -and $null -ne $r.body -and [string]$r.body.app -eq $script:AppName) {
        return @{ state = 'ours'; pid = [int]$r.body.pid; health = $r.body; note = '' }
    }
    if ($r.status -eq 0 -and ($r.error -eq 'ConnectFailure' -or $r.error -eq 'NameResolutionFailure')) {
        return @{ state = 'none'; pid = 0; health = $null; note = 'サーバが動いていません' }
    }
    if ($r.status -eq 0) {
        return @{ state = 'other'; pid = 0; health = $null
                  note = '応答がありません（時間切れ）。別のアプリが使っている可能性があります' }
    }
    return @{ state = 'other'; pid = 0; health = $null
              note = ('別のアプリが応答しました（HTTP {0}）' -f $r.status) }
}

function Wait-ServerUp {
    <# `ours` になるまで待つ（立ち上がらなければ `$null`）。 #>
    param([Parameter(Mandatory)][int]$Port, [int]$TimeoutSec = 90)
    $deadline = (Get-Date).AddSeconds($TimeoutSec)
    while ((Get-Date) -lt $deadline) {
        $st = Get-ServerState -Port $Port
        if ($st.state -eq 'ours') { return $st }
        Start-Sleep -Milliseconds 400
    }
    return $null
}

function Wait-ServerGone {
    <#
        **止めたはずの PID が全部消えて、ポートも `ours` でなくなる**まで待つ。

        **PID は 2 つ渡す**（実測）: `.venv\Scripts\python.exe` は uv の**踏み台**で、
        本物のサーバはその子（`/api/health` が名乗る `pid`）として走る。片方だけ見ると
        「止めたつもりで生きている」を見落とす。
    #>
    param(
        [Parameter(Mandatory)][int]$Port,
        [Parameter(Mandatory)][int[]]$Pids,
        [int]$TimeoutSec = 20
    )
    $deadline = (Get-Date).AddSeconds($TimeoutSec)
    while ((Get-Date) -lt $deadline) {
        $alive = @()
        foreach ($p in $Pids) {
            if ($null -ne (Get-Process -Id $p -ErrorAction SilentlyContinue)) { $alive += $p }
        }
        if ($alive.Count -eq 0) {
            $st = Get-ServerState -Port $Port
            if ($st.state -ne 'ours') { return $true }
        }
        Start-Sleep -Milliseconds 300
    }
    return $false
}

# ---- サーバの起動と停止 ----

function Resolve-ServerCommand {
    <#
        起動の仕方を決める。**止められる形を優先する。**

        1. `<リポジトリ>\.venv\Scripts\python.exe -m image_reviewer.cli serve`
           （**踏み台 + 本体の 2 プロセス**。実測: `.venv\Scripts\python.exe` は uv の小さな
           踏み台で、本物のサーバはその子。`taskkill /T` で木ごと止める）
        2. `uv run --no-sync image-reviewer serve`（venv が無いときの道。uv → ランチャ →
           python の 3 段なので、こちらも木ごと止める）
    #>
    param([Parameter(Mandatory)][int]$Port)
    $py = Join-Path $script:RepoRoot '.venv\Scripts\python.exe'
    if (Test-Path -LiteralPath $py) {
        return @{ exe = $py; args = @('-m', 'image_reviewer.cli', 'serve', '--port', [string]$Port)
                  note = '.venv の python で直に起動する（1 プロセス）' }
    }
    $uv = Get-Command uv -ErrorAction SilentlyContinue
    if ($null -ne $uv) {
        return @{ exe = $uv.Source
                  args = @('run', '--no-sync', 'image-reviewer', 'serve', '--port', [string]$Port)
                  note = 'uv 経由で起動する（venv が無いときの道）' }
    }
    return $null
}

function Start-OwnServer {
    <# サーバを子プロセスとして起動し、`/api/health` が返るまで待つ。 #>
    param(
        [Parameter(Mandatory)][hashtable]$State,
        [string]$DataDir = '',
        [int]$TimeoutSec = 90
    )
    $cmd = Resolve-ServerCommand -Port $State.Port
    if ($null -eq $cmd) {
        throw 'サーバを起動する道具が見つかりません（.venv\Scripts\python.exe も uv もありません）。README の「動かす」のとおり uv sync を先に打ってください。'
    }
    if (-not (Test-Path -LiteralPath $script:LogDir)) {
        New-Item -ItemType Directory -Force -Path $script:LogDir | Out-Null
    }
    # 子に渡す環境変数（PowerShell 5.1 の Start-Process には -Environment が無いので、
    # 自分の環境に置いてから起動する。子はそれを引き継ぐ）
    $env:UV_CACHE_DIR = Join-Path $script:RepoRoot '.uv-cache'
    if ($DataDir) {
        $env:IMAGE_REVIEWER_DATA = $DataDir
    } else {
        Remove-Item Env:IMAGE_REVIEWER_DATA -ErrorAction SilentlyContinue
    }
    Write-TrayLog ('サーバを起動します: {0} {1}（{2}）' -f $cmd.exe, ($cmd.args -join ' '), $cmd.note)
    $proc = Start-Process -FilePath $cmd.exe -ArgumentList $cmd.args `
        -WorkingDirectory $script:RepoRoot -WindowStyle Hidden `
        -RedirectStandardOutput $script:ServerLog -RedirectStandardError $script:ServerErrLog `
        -PassThru
    $State.Proc = $proc
    $State.Mode = 'own'
    $State.StartedAt = Get-Date
    $up = Wait-ServerUp -Port $State.Port -TimeoutSec $TimeoutSec
    if ($null -eq $up) {
        $tail = Get-ServerLogTail
        throw ('サーバが {0} 秒で立ち上がりませんでした。ログの末尾:{1}{2}' -f $TimeoutSec, [Environment]::NewLine, $tail)
    }
    # **PID は 2 つ持つ**（実測）: `Start-Process` が返すのは `.venv\Scripts\python.exe`
    # （uv の踏み台。47 KB の小さな exe）で、**本物のサーバはその子**。
    # 止めるのは踏み台の木ごと（`taskkill /T`）で、確かめるのは `/api/health` が名乗る `pid`。
    $State.ServerPid = [int]$up.pid
    Write-TrayLog ('サーバが立ち上がりました（踏み台 pid {0}、本体 pid {1}）' -f $proc.Id, $up.pid)
    return $up
}

function Get-OwnServerPids {
    <#
        **止めていい PID だけ**を集める（自分が起動した物）。

        - 踏み台（`Start-Process` が返した物）… そのまま
        - 本体（`/api/health` が名乗った `pid`）… **いまも同じ pid だと確かめてから**
          （PID は使い回されるので、確かめずに撃つと他人を巻き込む）
    #>
    param([Parameter(Mandatory)][hashtable]$State)
    $pids = @()
    if ($null -ne $State.Proc) { $pids += [int]$State.Proc.Id }
    if ($State.ContainsKey('ServerPid') -and [int]$State.ServerPid -gt 0) {
        $st = Get-ServerState -Port $State.Port
        if ($st.state -eq 'ours' -and [int]$st.pid -eq [int]$State.ServerPid) {
            $pids += [int]$State.ServerPid
        } elseif ($st.state -eq 'ours') {
            Write-TrayLog ('ポートのサーバは別のプロセスです（pid {0}。こちらは止めません）。' -f $st.pid)
        }
    }
    return $pids
}

function Stop-OwnServer {
    <#
        **自分が起動した物だけ**を止める（踏み台の木ごと + 確かめた本体）。

        既に動いていたサーバに繋いでいるときは `Mode = 'attach'` なので**何もしない**
        （PID を持っていない。**ポート番号から相手を探して止める道は作らない**）。
    #>
    param([Parameter(Mandatory)][hashtable]$State, [int]$TimeoutSec = 20)
    if ($State.Mode -ne 'own' -or ($null -eq $State.Proc -and -not $State.ServerPid)) {
        Write-TrayLog 'このトレイが起動したサーバではありません。止めません。'
        return $true
    }
    $targets = @(Get-OwnServerPids -State $State)
    if ($targets.Count -eq 0) {
        Write-TrayLog '止める相手は既に居ません（サーバは止まっています）。'
        $State.Proc = $null
        $State.ServerPid = 0
        $State.Mode = 'none'
        return $true
    }
    $taskkill = Join-Path $env:SystemRoot 'System32\taskkill.exe'
    foreach ($t in $targets) {
        Write-TrayLog ('サーバを止めます（pid {0}。木ごと）' -f $t)
        try {
            & $taskkill /PID $t /T /F 2>&1 | Out-Null
        } catch {
            Write-TrayLog ('止める命令で失敗しました: {0}' -f $_.Exception.Message)
        }
    }
    $gone = Wait-ServerGone -Port $State.Port -Pids $targets -TimeoutSec $TimeoutSec
    if ($gone) {
        Write-TrayLog 'サーバを止めました（ポートが空きました）。'
        $State.Proc = $null
        $State.ServerPid = 0
        $State.Mode = 'none'
    } else {
        Write-TrayLog ('サーバを止められませんでした（残り: {0}）。' -f ($targets -join ', '))
    }
    return $gone
}

# ---- 状態の読み取り ----

function Initialize-ServerState {
    <#
        **起動の判断（設計 §4.1）。** トレイの入口と自己検査（`tools\tray_selftest.ps1`）が
        同じこの 1 か所を通る（**検査だけ別の道を通ると、何も守れない**）。

        - `attach` … 既に動いている（`/api/health` が自分だと答えた）。**二重に起動しない。止めない**
        - `busy`   … 別のアプリが使っている／確かめられない。**起動しない**（相手を止めない）
        - `own`    … 自分で起動した
        - `failed` … 起動しようとして落ちた（`note` にログの末尾）
    #>
    param([Parameter(Mandatory)][hashtable]$State, [string]$DataDir = '')
    $probe = Get-ServerState -Port $State.Port
    if ($probe.state -eq 'other') {
        Write-TrayLog ('ポート {0} は別のアプリが使っています（{1}）。起動しません。' -f $State.Port, $probe.note)
        return @{ result = 'busy'; note = $probe.note }
    }
    if ($probe.state -eq 'ours') {
        $State.Mode = 'attach'
        $State.Proc = $null
        # **他人の PID は持たない**（持つと、いつか止めてしまう道ができる）
        $State.ServerPid = 0
        Write-TrayLog ('既に動いているサーバに繋ぎます（pid {0}）。このトレイは止めません。' -f $probe.pid)
        return @{ result = 'attach'; pid = $probe.pid }
    }
    Write-TrayLog 'サーバが居ません。自分で起動します。'
    try {
        $up = Start-OwnServer -State $State -DataDir $DataDir
    } catch {
        Write-TrayLog ('サーバを起動できませんでした: ' + $_.Exception.Message)
        return @{ result = 'failed'; note = $_.Exception.Message }
    }
    return @{ result = 'own'; pid = $up.pid }
}

function Format-Remain {
    <# 残り時間を `分:秒` にする（画面の「あと 3:12」と同じ形）。 #>
    param([Parameter(Mandatory)][int]$Sec)
    if ($Sec -lt 0) { $Sec = 0 }
    return ('{0}:{1:00}' -f [int][Math]::Floor($Sec / 60), ($Sec % 60))
}

function Format-When {
    <#
        時刻を**現地の `2026-10-19 16:48`** にする（`frontend-design.md` §6.1 の規約 1）。

        サーバは台帳の時刻を **ISO（`2026-10-19T07:48:56Z`）** で返すので、そのまま出すと
        画面（`apps/gui/pending.js` の `fmtWhen()`）と形が食い違う（**駆動の検査で実際に見つけた**）。
        読めない形は**そのまま返す**（黙って消さない）。
    #>
    param([string]$Iso)
    if (-not $Iso) { return '—' }
    $text = [string]$Iso
    if ($text -match 'Z$' -or $text -match '[+-]\d{2}:?\d{2}$') {
        $t = [datetime]::MinValue
        $styles = [System.Globalization.DateTimeStyles]::AdjustToUniversal -bor `
                  [System.Globalization.DateTimeStyles]::AssumeUniversal
        if ([datetime]::TryParse($text, [System.Globalization.CultureInfo]::InvariantCulture,
                                 $styles, [ref]$t)) {
            return $t.ToLocalTime().ToString('yyyy-MM-dd HH:mm')
        }
    }
    # 既に現地の形（`2026-10-19 02:31:59`）なら秒を落とすだけ
    if ($text -match '^\d{4}-\d{2}-\d{2} \d{2}:\d{2}') { return $text.Substring(0, 16) }
    return $text
}

function Get-TraySnapshot {
    <#
        いまの状態を 1 つの hashtable にまとめる（トレイのアイコン・ツールチップ・状態の窓・
        知らせは、すべてこれを見る）。**読むだけ**（`GET` しか打たない）。
    #>
    param([Parameter(Mandatory)][hashtable]$State)
    $snap = @{
        at = Get-Date
        state = 'down'          # up | down
        mode = $State.Mode      # own | attach | none
        port = $State.Port
        health = $null
        backup = $null
        backup_status = 0
        requests = -1
        deletes = -1
        deletes_remain = -1
        backup_failed = $false
        read_only = $false
        note = ''
    }
    $st = Get-ServerState -Port $State.Port
    if ($st.state -ne 'ours') {
        $snap.note = $st.note
        return $snap
    }
    $snap.state = 'up'
    $snap.health = $st.health

    $r1 = Invoke-Api -Port $State.Port -Path '/api/review-requests?state=open&count_only=1'
    if ($r1.ok -and $null -ne $r1.body -and $null -ne $r1.body.counts) {
        $snap.requests = [int]$r1.body.counts.open
    }
    $r2 = Invoke-Api -Port $State.Port -Path '/api/pending-deletes'
    if ($r2.ok -and $null -ne $r2.body) {
        $snap.deletes = [int]$r2.body.count
        $wins = @()
        foreach ($it in @($r2.body.items)) {
            if ($null -ne $it -and $null -ne $it.remaining_sec) { $wins += [int]$it.remaining_sec }
        }
        if ($wins.Count -gt 0) { $snap.deletes_remain = ($wins | Measure-Object -Minimum).Minimum }
    }
    $r3 = Invoke-Api -Port $State.Port -Path '/api/backup'
    $snap.backup_status = $r3.status
    if ($null -ne $r3.body) {
        $snap.backup = $r3.body
        if ([string]$r3.body.last_error) { $snap.backup_failed = $true }
        if ($r3.body.read_only -eq $true) { $snap.read_only = $true }
    }
    if ($r3.status -eq 503) {
        # 読み取り専用として出すのは `code` が無い / `read_only` / `db_error` のときだけ
        # （`busy` と `io_error` はもう一度で直る。`apps/gui/badge.js` と同じ規則）
        $code = ''
        if ($null -ne $r3.body -and $null -ne $r3.body.code) { $code = [string]$r3.body.code }
        if ($code -eq '' -or $code -eq 'read_only' -or $code -eq 'db_error') { $snap.read_only = $true }
    }
    if ([string]$r3.text -match '"last_error"\s*:\s*"([^"]+)"') { $snap.backup_failed = $true }
    return $snap
}

# ---- 見せ方（文言は `frontend-design.md` §6.1 の規約に従う）----

function Get-TrayTooltip {
    <#
        ツールチップ（`NotifyIcon.Text` は **63 字まで**）。

        「image-reviewer（稼働中）、要求 3、最近の削除 12」
        中黒「・」は名詞の対にだけ使う決まりなので、メタ情報は読点で繋ぐ（規約 1）。
    #>
    param([Parameter(Mandatory)][hashtable]$Snapshot)
    $head = 'image-reviewer（停止中）'
    if ($Snapshot.state -eq 'up') { $head = 'image-reviewer（稼働中）' }
    $parts = New-Object System.Collections.Generic.List[string]
    $parts.Add($head)
    if ($Snapshot.state -eq 'up') {
        if ($Snapshot.requests -gt 0) { $parts.Add(('要求 {0}' -f $Snapshot.requests)) }
        if ($Snapshot.deletes -gt 0) { $parts.Add(('最近の削除 {0}' -f $Snapshot.deletes)) }
        if ($Snapshot.backup_failed) { $parts.Add('バックアップに失敗しています') }
        if ($Snapshot.read_only) { $parts.Add('読み取り専用です') }
    }
    $text = ($parts -join '、')
    if ($text.Length -gt 63) { $text = $text.Substring(0, 62) + '…' }
    return $text
}

function New-StatusText {
    <#
        状態の窓とログに出す本文。**バックアップに失敗していれば必ず出す**（家風「黙って失敗しない」）。
        失敗の全文もここに出す（上部バーは 1 行だが、この窓は読むための場所）。
    #>
    param([Parameter(Mandatory)][hashtable]$Snapshot)
    $out = New-Object System.Collections.Generic.List[string]
    if ($Snapshot.state -ne 'up') {
        $out.Add('image-reviewer（停止中）')
        $out.Add('')
        $out.Add('サーバに繋がりません。')
        if ($Snapshot.mode -eq 'own') {
            $out.Add('トレイの「再起動する」で起動できます。')
        } else {
            $out.Add('このトレイは、既に動いていたサーバに繋いでいました。')
        }
        if ($Snapshot.note) { $out.Add(('（{0}）' -f $Snapshot.note)) }
        $out.Add('')
        $out.Add('この窓は読むだけです。操作はトレイのメニューから行います。')
        return ($out -join [Environment]::NewLine)
    }

    $ver = ''
    if ($null -ne $Snapshot.health -and $null -ne $Snapshot.health.version) {
        $ver = [string]$Snapshot.health.version
    }
    if ($ver) {
        $out.Add(('image-reviewer {0}（稼働中）' -f $ver))
    } else {
        $out.Add('image-reviewer（稼働中）')
    }
    $out.Add('')
    $out.Add(('アドレス: http://127.0.0.1:{0}' -f $Snapshot.port))
    if ($null -ne $Snapshot.health -and $Snapshot.health.data_dir) {
        $out.Add(('データ置き場: {0}' -f $Snapshot.health.data_dir))
    }
    $req = '—'
    if ($Snapshot.requests -ge 0) { $req = ('{0} 件' -f $Snapshot.requests) }
    $out.Add(('要求: {0}' -f $req))
    $del = '—'
    if ($Snapshot.deletes -ge 0) {
        $del = ('{0} 件' -f $Snapshot.deletes)
        if ($Snapshot.deletes_remain -ge 0) {
            $del = ('{0}（あと {1}）' -f $del, (Format-Remain -Sec $Snapshot.deletes_remain))
        }
    }
    $out.Add(('最近の削除: {0}' -f $del))

    if ($null -ne $Snapshot.backup) {
        $b = $Snapshot.backup
        $out.Add('')
        $out.Add(('バックアップの保存先: {0}' -f $b.backup_dir))
        if ($b.last_at) {
            $out.Add(('最後に取った時刻: {0}' -f (Format-When $b.last_at)))
        } else {
            $out.Add('最後に取った時刻: —')
        }
        # `next_run_note` はサーバが返す利用者向けの 1 行（「今日の分はまだです（30 秒ごとに
        # 見ています）」）。**そのまま出す**（「今日の分: 今日の分は…」と重ねない）
        if ($b.next_run_note) { $out.Add([string]$b.next_run_note) }
        if ($null -ne $b.count) { $out.Add(('取ってある世代: {0}' -f $b.count)) }
    }

    if ($Snapshot.backup_failed) {
        $out.Add('')
        $when = ''
        if ($null -ne $Snapshot.backup -and $Snapshot.backup.last_error_at) {
            $when = ('（{0}）' -f (Format-When $Snapshot.backup.last_error_at))
        }
        $out.Add('バックアップに失敗しています' + $when + '。')
        if ($null -ne $Snapshot.backup -and $Snapshot.backup.last_error) {
            $out.Add([string]$Snapshot.backup.last_error)
        } else {
            $out.Add('（理由は取れませんでした。GET /api/backup が 503 を返しています）')
        }
    }
    if ($Snapshot.read_only) {
        $out.Add('')
        $out.Add('読み取り専用です。')
        if ($null -ne $Snapshot.backup -and $Snapshot.backup.reason) {
            $out.Add([string]$Snapshot.backup.reason)
        }
    }
    if ($Snapshot.mode -ne 'own') {
        $out.Add('')
        $out.Add('このトレイは、既に動いているサーバに繋いでいます。')
        $out.Add('再起動と終了では、そのサーバを止めません。')
    }
    $out.Add('')
    $out.Add('この窓は読むだけです。操作はトレイのメニューから行います。')
    return ($out -join [Environment]::NewLine)
}

function New-TrayIcon {
    <#
        アイコンを 1 つ描く（**ファイルを増やさない**。`System.Drawing` でその場で描く）。

        枠の色 … ふつうは青灰。**バックアップに失敗／読み取り専用なら `--drop`（赤）**。
        右下の丸 … **要求あり**は `--accent`、**取り消せる削除あり**は `--warn`、
        **両方**なら枠を `--accent` にして丸は `--warn`（4 つの形が別々に見える）。
    #>
    param([Parameter(Mandatory)][string]$Key)
    $size = 32
    $bmp = New-Object System.Drawing.Bitmap($size, $size)
    $g = [System.Drawing.Graphics]::FromImage($bmp)
    $g.SmoothingMode = [System.Drawing.Drawing2D.SmoothingMode]::AntiAlias
    $g.Clear([System.Drawing.Color]::Transparent)

    $frame = $script:ColorBase
    if ($Key -like 'down*') { $frame = $script:ColorDown }
    if ($Key -like 'both*') { $frame = $script:ColorAccent }
    if ($Key -like '*bad') { $frame = $script:ColorDrop }

    $frameBrush = New-Object System.Drawing.SolidBrush($frame)
    $paperBrush = New-Object System.Drawing.SolidBrush([System.Drawing.Color]::FromArgb(255, 240, 240, 242))
    $g.FillRectangle($frameBrush, 2, 6, 28, 21)
    $g.FillRectangle($paperBrush, 6, 10, 20, 13)

    $badge = $null
    if ($Key -like 'request*' -or $Key -like 'both*') { $badge = $script:ColorAccent }
    if ($Key -like 'delete*' -or $Key -like 'both*') { $badge = $script:ColorWarn }
    if ($null -ne $badge) {
        $ringColor = [System.Drawing.Color]::FromArgb(255, 22, 23, 25)
        if ($Key -like 'both*') { $ringColor = [System.Drawing.Color]::FromArgb(255, 240, 240, 242) }
        $ring = New-Object System.Drawing.SolidBrush($ringColor)
        $dot = New-Object System.Drawing.SolidBrush($badge)
        $g.FillEllipse($ring, 15, 15, 17, 17)
        $g.FillEllipse($dot, 18, 18, 11, 11)
        $ring.Dispose()
        $dot.Dispose()
    }
    $frameBrush.Dispose()
    $paperBrush.Dispose()
    $g.Dispose()

    $hicon = $bmp.GetHicon()
    $icon = [System.Drawing.Icon]::FromHandle($hicon)
    # `$bmp` は `FromHandle` の元なので、生かしておく（捨てるとアイコンが壊れる）
    return @{ icon = $icon; bmp = $bmp }
}

function Get-StateIcon {
    <# いまの状態に合うアイコンを返す（同じ形は 1 回だけ描いて使い回す）。 #>
    param([Parameter(Mandatory)][hashtable]$Snapshot)
    $key = 'none'
    if ($Snapshot.requests -gt 0 -and $Snapshot.deletes -gt 0) { $key = 'both' }
    elseif ($Snapshot.requests -gt 0) { $key = 'request' }
    elseif ($Snapshot.deletes -gt 0) { $key = 'delete' }
    if ($Snapshot.backup_failed -or $Snapshot.read_only) { $key = $key + '-bad' }
    if ($Snapshot.state -ne 'up') { $key = 'down' }
    if (-not $script:IconCache.ContainsKey($key)) {
        $script:IconCache[$key] = New-TrayIcon -Key $key
    }
    return $script:IconCache[$key]
}

function Get-AppUrl {
    <# 画面の URL（既定の入口）。 #>
    param([Parameter(Mandatory)][int]$Port)
    return ('http://127.0.0.1:{0}/' -f $Port)
}

function Open-App {
    <# 既定のブラウザで開く（`-NoBrowser` のときはログに出すだけ。試験用）。 #>
    param([Parameter(Mandatory)][string]$Url)
    if ($script:NoBrowser) {
        Write-TrayLog ('（-NoBrowser なのでブラウザは開きません） {0}' -f $Url)
        return
    }
    Write-TrayLog ('ブラウザで開きます: {0}' -f $Url)
    Start-Process $Url | Out-Null
}

function Show-TrayDialog {
    <# 人に必ず見せる 1 枚（トレイの窓が無いときの失敗はここで出す。設計 §4.1「黙って死なない」）。 #>
    param([Parameter(Mandatory)][string]$Text, [string]$Title = 'image-reviewer')
    Write-TrayLog ('お知らせ: ' + ($Text -replace "`r?`n", ' / '))
    if ($script:DriveScript) {
        Write-TrayLog '（試験なのでダイアログは出しません）'
        return
    }
    [System.Windows.Forms.MessageBox]::Show($Text, $Title,
        [System.Windows.Forms.MessageBoxButtons]::OK,
        [System.Windows.Forms.MessageBoxIcon]::Warning) | Out-Null
}

function Show-TrayBalloon {
    <# バルーンで 1 つ知らせる（音は使わない。§4.5）。 #>
    param(
        [Parameter(Mandatory)][string]$Text,
        [string]$Title = 'image-reviewer',
        [string]$Kind = 'Info'
    )
    Write-TrayLog ('知らせ: ' + $Text)
    $ctx = $script:Ctx
    if ($null -eq $ctx -or $null -eq $ctx.Icon) { return }
    try {
        $ctx.Icon.BalloonTipTitle = $Title
        $ctx.Icon.BalloonTipText = $Text
        $ctx.Icon.BalloonTipIcon = [System.Windows.Forms.ToolTipIcon]::$Kind
        $ctx.Icon.ShowBalloonTip(10000)
    } catch {
        Write-TrayLog ('バルーンを出せませんでした: ' + $_.Exception.Message)
    }
}

function Show-StatusWindow {
    <#
        「状態を見る」の小さな窓（読むだけ）。
        **`-StatusAutoCloseMs` が 0 でなければ自動で閉じる**（試験で人が押さなくても進めるため）。
    #>
    param([Parameter(Mandatory)][hashtable]$Ctx)
    $snap = Get-TraySnapshot -State $Ctx.State
    $text = New-StatusText -Snapshot $snap
    Write-TrayLog ('状態の窓: ' + ($text -replace "`r?`n", ' / '))

    $form = New-Object System.Windows.Forms.Form
    $form.Text = 'image-reviewer の状態'
    $form.Size = New-Object System.Drawing.Size(620, 440)
    $form.StartPosition = 'CenterScreen'
    $form.MinimizeBox = $false
    $form.TopMost = $true

    $box = New-Object System.Windows.Forms.TextBox
    $box.Multiline = $true
    $box.ReadOnly = $true
    $box.WordWrap = $true
    $box.ScrollBars = 'Vertical'
    $box.Dock = 'Fill'
    $box.Text = $text

    $close = New-Object System.Windows.Forms.Button
    $close.Text = '閉じる'
    $close.Dock = 'Bottom'
    $close.Add_Click({ if ($null -ne $script:StatusForm) { $script:StatusForm.Close() } })

    $form.Controls.Add($box)
    $form.Controls.Add($close)
    $form.AcceptButton = $close
    $form.CancelButton = $close
    $script:StatusForm = $form

    if ($script:StatusAutoCloseMs -gt 0) {
        # **試験用**の自動閉じ。`$script:` に置くのは、イベントの中から関数の局所変数は
        # 見えないため（PowerShell の決まり）
        $script:StatusAutoTimer = New-Object System.Windows.Forms.Timer
        $script:StatusAutoTimer.Interval = $script:StatusAutoCloseMs
        $script:StatusAutoTimer.Add_Tick({
            $script:StatusAutoTimer.Stop()
            if ($null -ne $script:StatusForm) { $script:StatusForm.Close() }
        })
        $script:StatusAutoTimer.Start()
    }
    $form.ShowDialog() | Out-Null
    $form.Dispose()
    $script:StatusForm = $null
    return $text
}

# ---- メニューと操作 ----

function New-TrayMenu {
    <#
        メニュー（**文言は §6.1 の規約 3「押すと何かが起きるボタンは終止形」に合わせる**）。

        「ブラウザで開く」／「最近の削除を開く」／「状態を見る」／「再起動する」／
        「終了する（サーバも止める）」（既に動いていたサーバに繋いでいるときは
        「トレイを閉じる（サーバは止めない）」に変わり、「再起動する」は押せなくなる）。
    #>
    param([Parameter(Mandatory)][hashtable]$Ctx)
    $menu = New-Object System.Windows.Forms.ContextMenuStrip
    $menu.ShowImageMargin = $false

    $open = $menu.Items.Add('ブラウザで開く')
    $open.Name = 'mi-open'
    $open.Font = New-Object System.Drawing.Font($menu.Font, [System.Drawing.FontStyle]::Bold)
    $open.Add_Click({ Invoke-TrayMenuAction -Name 'open' })

    $del = $menu.Items.Add('最近の削除を開く')
    $del.Name = 'mi-deletes'
    $del.Add_Click({ Invoke-TrayMenuAction -Name 'deletes' })

    $menu.Items.Add((New-Object System.Windows.Forms.ToolStripSeparator)) | Out-Null

    $status = $menu.Items.Add('状態を見る')
    $status.Name = 'mi-status'
    $status.Add_Click({ Invoke-TrayMenuAction -Name 'status' })

    $restart = $menu.Items.Add('再起動する')
    $restart.Name = 'mi-restart'
    $restart.Add_Click({ Invoke-TrayMenuAction -Name 'restart' })

    $menu.Items.Add((New-Object System.Windows.Forms.ToolStripSeparator)) | Out-Null

    $exit = $menu.Items.Add('終了する（サーバも止める）')
    $exit.Name = 'mi-exit'
    $exit.Add_Click({ Invoke-TrayMenuAction -Name 'exit' })

    return $menu
}

function Update-TrayMenu {
    <# メニューの語と押せる・押せないを、いまの状態に合わせる（**押す前に何が起きるか分かる**ように）。 #>
    param([Parameter(Mandatory)][hashtable]$Ctx, [Parameter(Mandatory)][hashtable]$Snapshot)
    $exit = $Ctx.Menu.Items.Find('mi-exit', $false)
    if ($null -ne $exit -and $exit.Count -gt 0) {
        if ($Ctx.State.Mode -eq 'own') {
            $exit[0].Text = '終了する（サーバも止める）'
        } else {
            $exit[0].Text = 'トレイを閉じる（サーバは止めない）'
        }
    }
    $restart = $Ctx.Menu.Items.Find('mi-restart', $false)
    if ($null -ne $restart -and $restart.Count -gt 0) {
        if ($Ctx.State.Mode -ne 'own') {
            $restart[0].Text = '再起動する'
            $restart[0].Enabled = $false
            $restart[0].ToolTipText = '既に動いていたサーバなので、このトレイからは止められません。'
        } else {
            $restart[0].Enabled = $true
            $restart[0].ToolTipText = ''
            if ($Snapshot.state -eq 'up') { $restart[0].Text = '再起動する' } else { $restart[0].Text = '起動する' }
        }
    }
}

function Refresh-Tray {
    <# 状態を取り直して、アイコン・ツールチップ・メニューを合わせる。変わったときだけ知らせる。 #>
    param([Parameter(Mandatory)][hashtable]$Ctx, [switch]$Quiet)
    $snap = Get-TraySnapshot -State $Ctx.State
    $Ctx.Snapshot = $snap
    $prev = $Ctx.Last
    $Ctx.Last = @{
        state = $snap.state
        requests = $snap.requests
        deletes = $snap.deletes
        backup_failed = $snap.backup_failed
    }
    if ($null -ne $Ctx.Icon) {
        $Ctx.Icon.Icon = (Get-StateIcon -Snapshot $snap).icon
        $Ctx.Icon.Text = Get-TrayTooltip -Snapshot $snap
    }
    if ($null -ne $Ctx.Menu) { Update-TrayMenu -Ctx $Ctx -Snapshot $snap }
    if (-not $Quiet -and $null -ne $prev) { Send-TrayNotifications -Ctx $Ctx -Snapshot $snap -Prev $prev }
    return $snap
}

function Send-TrayNotifications {
    <# **変わったときに 1 つだけ**知らせる（バックアップの失敗を最優先。家風「黙って失敗しない」）。 #>
    param(
        [Parameter(Mandatory)][hashtable]$Ctx,
        [Parameter(Mandatory)][hashtable]$Snapshot,
        [Parameter(Mandatory)][hashtable]$Prev
    )
    if ($Snapshot.state -ne 'up') { return }
    if ($Snapshot.backup_failed -and -not $Prev.backup_failed) {
        Show-TrayBalloon -Kind 'Warning' -Text 'バックアップに失敗しています。詳しくは「状態を見る」に出ます。'
        return
    }
    if ($Snapshot.requests -gt $Prev.requests -and $Snapshot.requests -gt 0) {
        Show-TrayBalloon -Text ('エージェントから要求が来ました（{0} 件）。' -f $Snapshot.requests)
        return
    }
    if ($Snapshot.deletes -gt $Prev.deletes -and $Snapshot.deletes -gt 0) {
        Show-TrayBalloon -Text ('取り消せる削除があります（{0} 件）。「最近の削除を開く」から戻せます。' -f $Snapshot.deletes)
        return
    }
}

function Restart-Server {
    <# 「再起動する」／「起動する」。**自分が起動したサーバだけ**を止めてから起動し直す。 #>
    param([Parameter(Mandatory)][hashtable]$Ctx)
    if ($Ctx.State.Mode -ne 'own') {
        Show-TrayBalloon -Kind 'Warning' -Text 'このトレイは既に動いていたサーバに繋いでいます。再起動はできません。'
        return $false
    }
    Write-TrayLog '再起動します。'
    if (-not (Stop-OwnServer -State $Ctx.State)) {
        Show-TrayDialog -Text ('サーバを止められませんでした。タスクマネージャーで python を終わらせてから、もう一度試してください。')
        return $false
    }
    try {
        Start-OwnServer -State $Ctx.State -DataDir $script:DataDir | Out-Null
    } catch {
        Show-TrayDialog -Text ('サーバを起動できませんでした。' + [Environment]::NewLine + $_.Exception.Message)
        return $false
    }
    Refresh-Tray -Ctx $Ctx -Quiet | Out-Null
    Show-TrayBalloon -Text 'サーバを起動し直しました。'
    return $true
}

function Exit-Tray {
    <# 「終了する」／「トレイを閉じる」。**自分が起動したサーバだけ**を止める。 #>
    param([Parameter(Mandatory)][hashtable]$Ctx)
    $stopped = $true
    if ($Ctx.State.Mode -eq 'own') {
        $stopped = Stop-OwnServer -State $Ctx.State
    } else {
        Write-TrayLog 'このトレイはサーバを起動していません（既に動いていたサーバに繋いでいました）。止めません。'
    }
    if (-not $stopped) {
        Show-TrayDialog -Text 'サーバを止められませんでした。タスクマネージャーで python を終わらせてください。'
    }
    if ($null -ne $Ctx.Timer) { $Ctx.Timer.Stop() }
    if ($null -ne $Ctx.Icon) {
        $Ctx.Icon.Visible = $false
        $Ctx.Icon.Dispose()
    }
    Write-TrayLog 'トレイを終了します。'
    [System.Windows.Forms.Application]::ExitThread()
}

function Invoke-TrayMenuAction {
    <#
        メニューとダブルクリックの入口（**1 か所**）。
        人が押しても、試験が `PerformClick()` で押しても、ここを通る。
    #>
    param([Parameter(Mandatory)][string]$Name)
    $ctx = $script:Ctx
    if ($null -eq $ctx) { Write-TrayLog ('メニュー（{0}）が来ましたが、トレイがまだできていません。' -f $Name); return }
    try {
        switch ($Name) {
            'open'    { Open-App -Url (Get-AppUrl -Port $ctx.State.Port) }
            'deletes' { Open-App -Url ((Get-AppUrl -Port $ctx.State.Port) + '#/pending-deletes') }
            'status'  { Show-StatusWindow -Ctx $ctx | Out-Null }
            'restart' { Restart-Server -Ctx $ctx | Out-Null }
            'exit'    { Exit-Tray -Ctx $ctx }
            default   { Write-TrayLog ('知らないメニューです: {0}' -f $Name) }
        }
    } catch {
        Write-TrayLog ('メニューの「{0}」で失敗しました: {1}' -f $Name, $_.Exception.Message)
        Show-TrayDialog -Text ('操作に失敗しました。' + [Environment]::NewLine + $_.Exception.Message)
    }
}

# ---- 常駐 ----

function Start-Tray {
    <# アイコンを出してメッセージループに入る（**この関数は終了するまで返らない**）。 #>
    param([Parameter(Mandatory)][hashtable]$Ctx)
    [System.Windows.Forms.Application]::EnableVisualStyles()

    $icon = New-Object System.Windows.Forms.NotifyIcon
    $icon.Visible = $false
    $icon.ContextMenuStrip = $Ctx.Menu
    $icon.Add_DoubleClick({ Invoke-TrayMenuAction -Name 'open' })
    $Ctx.Icon = $icon
    $script:Ctx = $Ctx

    Refresh-Tray -Ctx $Ctx -Quiet | Out-Null
    $icon.Visible = $true

    if (-not $script:NoBrowser) { Open-App -Url (Get-AppUrl -Port $Ctx.State.Port) }

    $timer = New-Object System.Windows.Forms.Timer
    $timer.Interval = $script:PollMs
    $timer.Add_Tick({
        try {
            $snap = Refresh-Tray -Ctx $script:Ctx
            # 落ちている間は周期を延ばす（接続拒否に約 2 秒かかる環境で、5 秒ごとに固めない）
            if ($null -ne $script:Ctx -and $null -ne $script:Ctx.Timer) {
                $want = $script:PollMs
                if ($snap.state -ne 'up') { $want = $script:PollDownMs }
                if ($script:Ctx.Timer.Interval -ne $want) { $script:Ctx.Timer.Interval = $want }
            }
        } catch {
            Write-TrayLog ('定期の確認で失敗しました: ' + $_.Exception.Message)
        }
    })
    $timer.Start()
    $Ctx.Timer = $timer

    if ($script:DriveScript) {
        # **試験用**: 人がメニューを押す代わりに、実メニューを操作する手順を読む
        Write-TrayLog ('駆動用の手順を読みます: {0}' -f $script:DriveScript)
        $script:DriveTimer = New-Object System.Windows.Forms.Timer
        $script:DriveTimer.Interval = $script:DriveDelayMs
        $script:DriveTimer.Add_Tick({
            $script:DriveTimer.Stop()
            try {
                . $script:DriveScript
                if (Get-Command Invoke-TrayDrive -ErrorAction SilentlyContinue) {
                    Invoke-TrayDrive -Ctx $script:Ctx
                } else {
                    Write-TrayLog '駆動用の手順に Invoke-TrayDrive がありません。'
                }
            } catch {
                Write-TrayLog ('駆動用の手順で失敗しました: ' + $_.Exception.Message)
                # **試験でトレイを残さない**: 手順が落ちたら、終了の道（`Exit-Tray`）を通って自分で終わる
                # （人が見ていない検査で、止まらないトレイとサーバが居座らないように）
                Write-TrayLog '駆動が落ちたので、トレイを終わりにします。'
                Exit-Tray -Ctx $script:Ctx
            }
        })
        $script:DriveTimer.Start()
        $Ctx.Drive = $script:DriveTimer
    }

    [System.Windows.Forms.Application]::Run()

    if ($null -ne $Ctx.Timer) { $Ctx.Timer.Stop(); $Ctx.Timer.Dispose() }
    if ($null -ne $icon) { $icon.Visible = $false; $icon.Dispose() }
    foreach ($k in @($script:IconCache.Keys)) {
        try { $script:IconCache[$k].icon.Dispose(); $script:IconCache[$k].bmp.Dispose() } catch { }
    }
    Write-TrayLog 'トレイのループを抜けました。'
}

# ---- 入口 ----

if ($DefineOnly) { return }

$script:Port = $Port
$script:DataDir = $DataDir
$script:NoBrowser = [bool]$NoBrowser
$script:DriveScript = $DriveScript
$script:StatusAutoCloseMs = $StatusAutoCloseMs

if (-not (Test-Path -LiteralPath $script:LogDir)) {
    New-Item -ItemType Directory -Force -Path $script:LogDir | Out-Null
}
$where = ''
if ($DataDir) { $where = '、データ置き場 ' + $DataDir }
Write-TrayLog ('トレイを起動します（ポート {0}{1}）' -f $Port, $where)

# 1. トレイは 1 つだけ（2 回目はブラウザを開くだけ。設計 §4.1 の二重起動の考え方と同じ）
$mutex = New-Object System.Threading.Mutex($false, ('Local\image-reviewer-tray-{0}' -f $Port))
$owned = $false
try {
    $owned = $mutex.WaitOne(0)
} catch [System.Threading.AbandonedMutexException] {
    $owned = $true
}
if (-not $owned) {
    Write-TrayLog 'トレイは既に動いています。ブラウザだけ開きます。'
    Open-App -Url (Get-AppUrl -Port $Port)
    return
}

# 2. 既に居るかを確かめる（**ポートが使えるかでは判定しない**）
$state = @{ Port = $Port; Mode = 'none'; Proc = $null; ServerPid = 0; StartedAt = $null; Snapshot = $null; Last = $null }
$init = Initialize-ServerState -State $state -DataDir $DataDir
if ($init.result -eq 'busy') {
    Show-TrayDialog -Text ('ポート {0} は別のアプリが使っています。このトレイは起動できません。image-reviewer-tray.cmd の -Port を変えてください。' -f $Port)
    return
}
if ($init.result -eq 'failed') {
    Show-TrayDialog -Text ('サーバを起動できませんでした。' + [Environment]::NewLine + $init.note)
    return
}

$ctx = @{
    State = $state
    Menu = $null
    Icon = $null
    Timer = $null
    Snapshot = $null
    Last = $null
}
$ctx.Menu = New-TrayMenu -Ctx $ctx
$script:Ctx = $ctx
Start-Tray -Ctx $ctx
Write-TrayLog 'トレイを終わりました。'
