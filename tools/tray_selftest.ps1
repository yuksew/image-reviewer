#Requires -Version 5.1
<#
.SYNOPSIS
    トレイ（`tools\tray.ps1`）の**自動で確かめられる所**を、実物で確かめる。

.DESCRIPTION
    人がメニューを押す所（UI）は `tools\tray_drive.ps1` が受け持つ。ここは**ロジック**を見る:

    | # | 線 | 何を壊すと落ちるか |
    | --- | --- | --- |
    | 1 | 前提（8790 を触らない・**使うポートが空いている**・複製を作る） | 空きを見ないと、他人のサーバを巻き込む（監査 A-1） |
    | 1b | **錠**（`-DefineOnly` では空の置き場も実データも断る） | 断りを外すと、検査が**実データを開く**（監査 A-1） |
    | 2 | 起動（自分で起動する。**本体が自分の子の子孫**） | 親子を見ないと、他人の pid を自分の物にする（監査 A-2） |
    | 2b | **起動に失敗したら待たない** | 生死を見ないと 90 秒黙って待つ（監査 B-1） |
    | 2c | **本物の応答から読む**（バックアップの失敗・件数） | 手で作った snapshot だけ見ると、読む道が壊れても通る（監査 F-3・F-5） |
    | 3 | **二重起動しない**（既に動いていれば繋ぐ。**このポートの** python を数える） | `attach` を外すと 2 つ目が上がる（監査 F-6） |
    | 4 | **別のアプリのポートでは起動しない** | `other` の判定を外すと他人のポートを掴もうとする |
    | 5 | 状態の本文（**失敗を必ず出す**・確かめられなかった・止めない相手） | `backup_failed` の行を消すと落ちる |
    | 6 | ツールチップとアイコンの形（4 通りが別・**停止中は形が違う**・5 桁でも 63 字） | 形の出し分けを 1 つに潰すと落ちる（監査 B-2・F-2・F-9） |
    | 7 | メニューの文言（§6.1。中黒・終止形・開発の記法を出さない） | 文言を変えると落ちる（監査 D-3・D-4） |
    | 8 | 添付のときのメニュー（終了の語と再起動の可否。**他人が立った形も**） | `Update-TrayMenu` を外すと落ちる（監査 C-4） |
    | 9 | **終了は自分が起動した物だけ止める**（関数の道と、**メニューの終了の道**） | PID ではなくポートで止める実装にすると落ちる（監査 F-4） |
    | 10 | **他人が起動した物を止めない**（競合・自分のサーバが落ちた後） | 親子と同一性を確かめないと落ちる（監査 A-2・F-7） |
    | 11 | 記録（`.tray` のログ） | 記録を外すと落ちる |

    **利用者の 8790 は使わない**（別のポートと、合成した複製だけで回す）。
    **実データ `.data` には 1 バイトも触らない**（`tools\make_synthetic_db.py` の複製を使う）。
    **`IMAGE_REVIEWER_DATA` はこの検査が自分で立てる**（親から引き継いだ値に頼らない。監査 A-1）。

.EXAMPLE
    powershell -NoProfile -ExecutionPolicy Bypass -File tools\tray_selftest.ps1 -Port 8795

.NOTES
    **`-ExecutionPolicy Bypass` が要る**（この環境では .ps1 が素では実行できない。`docs/tray.md`）。
    **使う 4 つのポート（`-Port`〜`+3`）が空いていなければ、1 つも起動せずに exit 2** で止まる
    （監査 A-1: 途中で `attach` になって、環境変数の無いサーバを起こす道を塞ぐ）。
#>
[CmdletBinding()]
param(
    [int]$Port = 8795,
    [string]$Replica = '',
    [string]$TrayScript = '',
    [switch]$Keep
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$tmp = Join-Path $root '.tmp-tray'
$script:Ng = 0
$script:Ok = 0
if (-not $TrayScript) { $TrayScript = Join-Path $root 'tools\tray.ps1' }

function Check {
    param([string]$Name, [bool]$Good, [string]$Detail = '')
    if ($Good) {
        $script:Ok++
        Write-Output ('ok   {0}' -f $Name)
    } else {
        $script:Ng++
        Write-Output ('NG   {0}{1}' -f $Name, $(if ($Detail) { '  ← ' + $Detail } else { '' }))
    }
}

function Section {
    param([string]$Text)
    Write-Output ''
    Write-Output ('== {0}' -f $Text)
}

function Test-PidAlive {
    <#
        PID が生きているか。**0 と負を「生きている」と数えない**——
        `Get-Process -Id 0` は System Idle Process を返すので、素直に書くと
        「掴めていない」を「生きている」と読み違える（この検査を書いたときに実際に踏んだ）。
    #>
    param([int]$ProcessId)
    if ($ProcessId -le 0) { return $false }
    return $null -ne (Get-Process -Id $ProcessId -ErrorAction SilentlyContinue)
}

function Get-ServerProcessCount {
    <#
        **このポートのサーバの python を数える**（監査 F-6）。

        機械のすべての python を数えると、関係の無い物（常駐の別の python）で揺れる。
        `.venv\Scripts\python.exe` の踏み台も本体も `--port <Port>` を持つのとで両方数える。
    #>
    param([Parameter(Mandatory)][int]$Port)
    $n = 0
    try {
        $rows = Get-CimInstance -ClassName Win32_Process -Filter "Name = 'python.exe'" -ErrorAction Stop
        foreach ($r in @($rows)) {
            if ([string]$r.CommandLine -match ('--port\s+{0}(\s|$)' -f $Port)) { $n++ }
        }
    } catch { }
    return $n
}

function Stop-TestProcess {
    <# 検査が立てた物を片付ける（**この検査の PID だけ**）。 #>
    param([int]$ProcessId)
    if ($ProcessId -le 0) { return }
    try { & (Join-Path $env:SystemRoot 'System32\taskkill.exe') /PID $ProcessId /T /F 2>&1 | Out-Null } catch { }
}

trap {
    <#
        **検査そのものが落ちたときの後始末。** 途中で例外が出ても、この検査が立てたサーバ
        （`--port <Port>`〜`+3`）を残さない——残すと**出力のパイプを掴んだまま**になり、
        呼んだ側が戻らなくなる（この検査を書いたときに実際に踏んだ）。**他人のポートは触らない**。
    #>
    Write-Output ''
    Write-Output ('NG   検査そのものが落ちました: {0}' -f $_.Exception.Message)
    foreach ($p in @($Port, $Port + 1, $Port + 2, $Port + 3)) {
        try {
            $rows = Get-CimInstance -ClassName Win32_Process -Filter "Name = 'python.exe'" -ErrorAction Stop
            foreach ($r in @($rows)) {
                if ([string]$r.CommandLine -match ('--port\s+{0}(\s|$)' -f $p)) {
                    try { & (Join-Path $env:SystemRoot 'System32\taskkill.exe') /PID $r.ProcessId /T /F 2>&1 | Out-Null } catch { }
                }
            }
        } catch { }
    }
    exit 3
}

# ---- 1. 前提 ----

Section '1. 前提'
if ($Port -eq 8790) {
    Write-Output 'NG   8790 は利用者のサーバのポート。別のポート（例 8795）を -Port で渡す。'
    exit 2
}
Check 'ポートは 8790 ではない' ($Port -ne 8790) ("Port=$Port")
if (-not (Test-Path -LiteralPath $tmp)) { New-Item -ItemType Directory -Force -Path $tmp | Out-Null }
if (-not $Replica) { $Replica = Join-Path $tmp 'replica' }
if ($Replica -like '*\.data*' -or $Replica -like '*.data') {
    Write-Output ('NG   複製の場所が実データに見える: {0}' -f $Replica)
    exit 2
}

# トレイの関数を読む（**同じ 1 か所**を使う。検査だけ別の道を通ると何も守れない）
# `-TrayScript` は**壊し試験**のため（写しを壊して、この検査が落ちることを見る）
Write-Output ('     対象: {0}' -f $TrayScript)
. $TrayScript -Port $Port -DefineOnly
Check 'トレイの関数が読めた' ([bool](Get-Command Initialize-ServerState -ErrorAction SilentlyContinue))
Check '関数だけ読んだ（DefineOnly。サーバは起動していない）' ([bool]$script:DefineOnly)
# 本番の入口と同じようにポートを持たせる（`Get-ServerLogPaths` がポートごとの名前にする）
$script:Port = $Port

# **使う 4 つのポートが空いているか**を先に確かめる（監査 A-1 の②: 埋まっていたら始めない）
$busy = @()
foreach ($p in @($Port, $Port + 1, $Port + 2, $Port + 3)) {
    $probe = Get-ServerState -Port $p
    if ($probe.state -ne 'none') { $busy += ('{0}={1}' -f $p, $probe.state) }
}
if ($busy.Count -gt 0) {
    Write-Output ('NG   使うポートが空いていません: {0}' -f ($busy -join ', '))
    Write-Output '     空いているポートを -Port で渡してください（**埋まっていると attach になり、環境の無いサーバを起こしかねない**）。'
    exit 2
}
Check '使う 4 つのポートは空いている' ($busy.Count -eq 0) ($busy -join ', ')

# 記録は使い捨ての場所へ（製品の `.tray` を汚さない）
$script:LogDir = Join-Path $tmp 'log'
$script:TrayLog = Join-Path $script:LogDir 'tray-selftest.log'
$script:ServerLog = Join-Path $script:LogDir 'server-selftest.log'
$script:ServerErrLog = Join-Path $script:LogDir 'server-selftest.err.log'
if (-not (Test-Path -LiteralPath $script:LogDir)) { New-Item -ItemType Directory -Force -Path $script:LogDir | Out-Null }
if (Test-Path -LiteralPath $script:TrayLog) { Remove-Item -LiteralPath $script:TrayLog -Force }

$py = Join-Path $root '.venv\Scripts\python.exe'
Check '.venv の python がある' (Test-Path -LiteralPath $py) $py
$env:UV_CACHE_DIR = Join-Path $root '.uv-cache'

& $py -X utf8 (Join-Path $root 'tools\make_synthetic_db.py') --out $Replica --count 3 --force | Out-Null
Check '合成の複製ができた（実データは触らない）' (Test-Path -LiteralPath (Join-Path $Replica 'db.sqlite3')) $Replica
Check '複製は実データではない' (-not (Test-RealDataDir -Path $Replica))

# **この検査が使うすべての子に、置き場を明示して渡す**（監査 A-1 の①。
# 「親から引き継いだ値」に頼らない・「消して既定に任せる」道を作らない）
$env:IMAGE_REVIEWER_DATA = $Replica
# 日次のバックアップは**複製の外**へ。**わざと「フォルダでない物」を指す**——
# 起動の直後に日次が 1 回走って失敗するので、「本物の応答から失敗を読む」道（§2c）が通る
# （監査 F-3。既定の `%USERPROFILE%` はこの環境では作れない）
$backupDir = Join-Path $tmp 'backups'
$backupBlocked = Join-Path $tmp 'backups-not-a-dir.txt'
if (Test-Path -LiteralPath $backupDir) { Remove-Item -LiteralPath $backupDir -Recurse -Force -ErrorAction SilentlyContinue }
Set-Content -LiteralPath $backupBlocked -Value 'フォルダではない（日次をわざと失敗させる）' -Encoding utf8
$env:IMAGE_REVIEWER_BACKUP_DIR = $backupBlocked

# ---- 1b. 錠（監査 A-1）----

Section '1b. 錠（`-DefineOnly` では実データを開かない）'
try {
    $got = Get-EffectiveDataDir -DataDir ''
    Check '空のデータ置き場を断る' $false ('返ってきた: ' + $got)
} catch {
    Check '空のデータ置き場を断る' $true
}
# **本物の `.data` では絶対に試さない**（断りが壊れていたときに、この検査が実データを開いてしまう）。
# 「実データ」の見本を 1 つ作り、`$script:DefaultDataDir` をそこに向けて断りを見る
# （本物の `.data` を実データと見ることは、最後に `Test-RealDataDir` で別に確かめる）。
$pretendReal = Join-Path $tmp 'pretend-real-data'
& $py -X utf8 (Join-Path $root 'tools\make_synthetic_db.py') --out $pretendReal --count 1 --force | Out-Null
$savedDefaultDataDir = $script:DefaultDataDir
$script:DefaultDataDir = $pretendReal
$guard = @{ Port = $Port + 3; Mode = 'none'; Proc = $null; ServerPid = 0; StartedAt = $null; Snapshot = $null; Last = $null }
$guardText = ''
try {
    Start-OwnServer -State $guard -DataDir $pretendReal | Out-Null
    $guardText = '（起動してしまった）'
} catch {
    $guardText = $_.Exception.Message
}
$script:DefaultDataDir = $savedDefaultDataDir
Check '実データ（既定の置き場）を指したら起動しない' ($guardText -ne '' -and $guardText -ne '（起動してしまった）') $guardText
Check '断ったときは 1 プロセスも起動していない' ($null -eq $guard.Proc)
if ($null -ne $guard.Proc -or $guard.ServerPid -gt 0) {
    # **断りが壊れているとき（壊し試験）の後始末。** 残すとこの先の検査が「ポートが埋まっている」で
    # 落ちるので、**この検査が起こした物だけ**止める（利用者のポートは触らない）。
    Write-Output '     （断りが効かなかったので、起こしてしまったサーバを片付けます）'
    Stop-OwnServer -State $guard | Out-Null
}
Check '断ったときもポートは空いたまま' ((Get-ServerState -Port ($Port + 3)).state -eq 'none')
Check '本物の .data を実データと見る' (Test-RealDataDir -Path (Join-Path $root '.data'))
Check '表記ゆれでも実データと見る' (Test-RealDataDir -Path (Join-Path $root '.data\'))
Check '複製は実データと見ない' (-not (Test-RealDataDir -Path $Replica))

# ---- 2. 起動 ----

Section '2. 起動（自分で起動する）'
# **（監査 A-1 の①）親の環境をわざと別の複製に向けておく**——`Start-OwnServer` が
# `-DataDir` を**明示して子に渡す**ことを、「親の値に引きずられない」ことで確かめる
# （親の値をそのまま使う実装なら、開くのは decoy になる）。
$decoy = Join-Path $tmp 'decoy'
& $py -X utf8 (Join-Path $root 'tools\make_synthetic_db.py') --out $decoy --count 1 --force | Out-Null
$savedEnvData = $env:IMAGE_REVIEWER_DATA
$env:IMAGE_REVIEWER_DATA = $decoy
$state = @{ Port = $Port; Mode = 'none'; Proc = $null; ServerPid = 0; StartedAt = $null; Snapshot = $null; Last = $null }
try {
    $init = Initialize-ServerState -State $state -DataDir $Replica
} finally {
    $env:IMAGE_REVIEWER_DATA = $savedEnvData
}
Check '自分で起動した（own）' ($init.result -eq 'own') ('result=' + $init.result)
if ($init.result -ne 'own') {
    # **（監査 A-1 の③。fail-closed）自分で起動していないなら、ここで止める。**
    # `attach` のまま先へ進むと、**置き場を渡していないサーバを起こす**道が生まれる
    # （この事故がまさにそれだった）。**理由を出して、この検査が立てた物だけ片付けて終わる。**
    Write-Output ('NG   自分で起動できませんでした（result={0}）。ここで止めます——' -f $init.result)
    Write-Output '     このまま進むと、置き場を明示していないサーバを起こす道ができます（監査 A-1）。'
    foreach ($p in @($Port, $Port + 1, $Port + 2, $Port + 3)) {
        try {
            $rows = Get-CimInstance -ClassName Win32_Process -Filter "Name = 'python.exe'" -ErrorAction Stop
            foreach ($row in @($rows)) {
                if ([string]$row.CommandLine -match ('--port\s+{0}(\s|$)' -f $p)) {
                    try { & (Join-Path $env:SystemRoot 'System32\taskkill.exe') /PID $row.ProcessId /T /F 2>&1 | Out-Null } catch { }
                }
            }
        } catch { }
    }
    exit 2
}
$health = $null
if ($state.Proc) {
    $r = Invoke-Api -Port $Port -Path '/api/health' -TimeoutSec 5
    if ($r.ok) { $health = $r.body }
}
Check '/api/health が返る' ($null -ne $health)
Check 'app は image-reviewer' ($null -ne $health -and $health.app -eq 'image-reviewer')
Check '本体 pid は /api/health の名乗りと一致' ($null -ne $health -and $state.ServerPid -eq [int]$health.pid) `
    ('health.pid={0} state.ServerPid={1}' -f $(if ($health) { $health.pid } else { '-' }), $state.ServerPid)
Check '踏み台（Start-Process が返した物）も掴んでいる' ($null -ne $state.Proc)
Check '踏み台と本体は別のプロセス（実測どおり）' ($null -ne $health -and $state.Proc.Id -ne [int]$health.pid) `
    ('踏み台={0} 本体={1}' -f $(if ($state.Proc) { $state.Proc.Id } else { '-' }), $(if ($health) { $health.pid } else { '-' }))
Check 'データ置き場は複製を指している（親の環境に引きずられない）' ($null -ne $health -and ([string]$health.data_dir).TrimEnd('\') -eq $Replica.TrimEnd('\')) `
    ('health.data_dir=' + $(if ($health) { $health.data_dir } else { '-' }))
# **（監査 A-2）本体が自分の踏み台の子孫であること**——これが「自分の子だけ止める」の土台
Check '本体は自分の踏み台の子孫' ($null -ne $health -and (Test-DescendantOf -ProcessId ([int]$health.pid) -AncestorId ([int]$state.Proc.Id))) `
    ('踏み台={0} 本体={1}' -f $(if ($state.Proc) { $state.Proc.Id } else { '-' }), $(if ($health) { $health.pid } else { '-' }))
Check '無関係のプロセスは子孫と見ない' (-not (Test-DescendantOf -ProcessId ((Get-Process -Id $PID).Id) -AncestorId ([int]$state.Proc.Id)))
$firstChild = 0
if ($state.Proc) { $firstChild = $state.Proc.Id }
$firstServer = $state.ServerPid

# ---- 2b. 起動に失敗したら待たない（監査 B-1）----

Section '2b. 起動に失敗したら待たない'
$badDir = Join-Path $tmp 'not-a-dir.txt'
Set-Content -LiteralPath $badDir -Value 'ファイル（DB を開けない）' -Encoding utf8
$failState = @{ Port = $Port + 3; Mode = 'none'; Proc = $null; ServerPid = 0; StartedAt = $null; Snapshot = $null; Last = $null }
$failText = ''
$sw = [System.Diagnostics.Stopwatch]::StartNew()
try {
    Start-OwnServer -State $failState -DataDir $badDir -TimeoutSec 90 | Out-Null
    $failText = '（落ちなかった）'
} catch {
    $failText = $_.Exception.Message
}
$sw.Stop()
Check '起動できない置き場では落ちる' ($failText -ne '' -and $failText -ne '（落ちなかった）')
Check '90 秒も待たない（20 秒未満）' ($sw.Elapsed.TotalSeconds -lt 20) ('{0:N1} 秒' -f $sw.Elapsed.TotalSeconds)
Check '落ちた子は持っていない（PID 0）' ($failState.ServerPid -eq 0) ('ServerPid=' + $failState.ServerPid)
if ($null -ne $failState.Proc) { Stop-TestProcess -ProcessId $failState.Proc.Id }
Start-Sleep -Milliseconds 500
Check '失敗したポートは空いたまま' ((Get-ServerState -Port ($Port + 3)).state -eq 'none')

# ---- 2c. 本物の応答から読む（監査 F-3・F-5）----

Section '2c. 本物の応答から読む（手で作った snapshot ではなく）'
$live = Get-TraySnapshot -State $state
Check '本物の応答で state は up' ($live.state -eq 'up') ('state=' + $live.state)
Check '口は 2 秒で全部読めた（確かめられなかった、ではない）' (-not $live.unknown)
Check '本物の応答からバックアップの失敗を読む' ($live.backup_failed)
Check '本物の応答から要求の数を読む' ($live.requests -ge 0) ('requests=' + $live.requests)
Check '本物の応答から最近の削除の数を読む' ($live.deletes -ge 0) ('deletes=' + $live.deletes)
Check '本物の応答から段 3 の数も読む' ($live.deletes_stage3 -ge 0) ('deletes_stage3=' + $live.deletes_stage3)
Check '実物のツールチップに「バックアップに失敗しています」が出る' ((Get-TrayTooltip -Snapshot $live) -match 'バックアップに失敗しています')

# ---- 3. 二重起動しない ----

Section '3. 二重起動しない（既に動いていれば繋ぐ）'
$before = Get-ServerProcessCount -Port $Port
$state2 = @{ Port = $Port; Mode = 'none'; Proc = $null; ServerPid = 0; StartedAt = $null; Snapshot = $null; Last = $null }
$init2 = Initialize-ServerState -State $state2 -DataDir $Replica
$after = Get-ServerProcessCount -Port $Port
Check '2 回目は起動せずに繋ぐ（attach）' ($init2.result -eq 'attach') ('result=' + $init2.result)
Check 'このポートの python の数が増えていない' ($after -eq $before) ('before={0} after={1}' -f $before, $after)
Check '1 つ目の踏み台が生きている' (Test-PidAlive -ProcessId $firstChild)
Check '本体 pid は 1 つ目のまま' ($init2.pid -eq $firstServer) ('init2.pid={0} first={1}' -f $init2.pid, $firstServer)
Check '繋いだ側は PID を持たない（止める道が無い）' ($state2.ServerPid -eq 0 -and $null -eq $state2.Proc)

# ---- 4. 別のアプリのポート ----

Section '4. 別のアプリが使っているポートでは起動しない'
$other = Start-Process -FilePath $py -ArgumentList @('-m', 'http.server', [string]($Port + 2)) `
    -WorkingDirectory $tmp -WindowStyle Hidden -PassThru `
    -RedirectStandardOutput (Join-Path $tmp 'other.out.log') -RedirectStandardError (Join-Path $tmp 'other.err.log')
Start-Sleep -Milliseconds 1500
$probeOther = Get-ServerState -Port ($Port + 2)
Check 'HTTP 404 を返すサーバは other と見る' ($probeOther.state -eq 'other') ('state=' + $probeOther.state)
$state3 = @{ Port = $Port + 2; Mode = 'none'; Proc = $null; ServerPid = 0; StartedAt = $null; Snapshot = $null; Last = $null }
$init3 = Initialize-ServerState -State $state3 -DataDir $Replica
Check 'busy を返して起動しない' ($init3.result -eq 'busy') ('result=' + $init3.result)
Check 'busy の理由は http（答えが遅いだけではない）' ([string]$init3.reason -eq 'http') ('reason=' + $init3.reason)
Check '相手のプロセスを止めていない' (Test-PidAlive -ProcessId $other.Id)
Stop-TestProcess -ProcessId $other.Id
Start-Sleep -Milliseconds 500
Check '塞いだポートは自分で片付けた' (-not (Test-PidAlive -ProcessId $other.Id))

# ---- 5. 状態の本文 ----

Section '5. 状態の本文（バックアップの失敗を必ず出す）'
$snapUp = @{
    at = Get-Date; state = 'up'; mode = 'own'; port = $Port
    health = $health; backup_status = 200; requests = 3; deletes = 12; deletes_remain = 192
    deletes_stage3 = 1; unknown = $false; foreign = $false
    backup = [pscustomobject]@{
        backup_dir = $backupDir; last_at = '2026-10-19 02:31'
        next_run_note = '今日の分はまだです（30 秒ごとに見ています）'; count = 3
        last_error = 'DB がいま混んでいます（database is locked）'; last_error_at = '2026-10-19 03:00'
        read_only = $false; reason = $null
    }
    backup_failed = $true; read_only = $false; note = ''
}
$txt = New-StatusText -Snapshot $snapUp
Check '本文に「バックアップに失敗しています」がある' ($txt -match 'バックアップに失敗しています')
Check '本文に失敗の全文がある' ($txt -match 'database is locked')
Check '本文にアドレスがある' ($txt -match ('http://127\.0\.0\.1:{0}' -f $Port))
Check '本文に要求の件数がある' ($txt -match '要求: 3 件')
$snapOk = $snapUp.Clone()
$snapOk.backup_failed = $false
$snapOk.unknown = $false
$snapOk.backup = [pscustomobject]@{
    backup_dir = $backupDir; last_at = '2026-10-19 02:31'
    next_run_note = '今日の分はまだです（30 秒ごとに見ています）'; count = 3
    last_error = ''; last_error_at = ''; read_only = $false; reason = $null
}
$txtOk = New-StatusText -Snapshot $snapOk
Check '失敗していないときは出ない' (-not ($txtOk -match 'バックアップに失敗しています'))
$snapRo = $snapOk.Clone()
$snapRo.read_only = $true
$snapRo.backup = [pscustomobject]@{
    backup_dir = $backupDir; last_at = ''; next_run_note = ''; count = 0
    last_error = ''; last_error_at = ''; read_only = $true; reason = 'DB の版が新しいので読み取り専用で起動しています'
}
$txtRo = New-StatusText -Snapshot $snapRo
Check '読み取り専用のときは出す' ($txtRo -match '読み取り専用です')
$snapDown = $snapUp.Clone()
$snapDown.state = 'down'
$snapDown.note = 'サーバが動いていません'
$txtDown = New-StatusText -Snapshot $snapDown
# **（監査 D-1）** 落ちているときのメニューは「起動する」なので、本文もその語で言う
Check '停止中のときは理由と次の一手を出す（メニューの語と同じ「起動する」）' `
    (($txtDown -match '停止中') -and ($txtDown -match '「起動する」') -and -not ($txtDown -match '「再起動する」'))
# **（監査 C-2）** 確かめられなかった回は前の値に印を付ける
$snapUnknown = $snapOk.Clone()
$snapUnknown.unknown = $true
$txtUnknown = New-StatusText -Snapshot $snapUnknown
Check '確かめられなかったときは印を付けて出す' (($txtUnknown -match '要求: 3 件（確かめられませんでした）') -and ($txtUnknown -match '最近の削除: 12 件（あと 3:12）（確かめられませんでした）'))
# **（監査 C-4）** 自分のサーバが落ちて他人が立った形
$snapForeign = $snapOk.Clone()
$snapForeign.mode = 'attach'
$snapForeign.foreign = $true
$txtForeign = New-StatusText -Snapshot $snapForeign
Check '止めない相手のときはそう言う' (($txtForeign -match 'このトレイが起動したサーバではありません') -and ($txtForeign -match '止めません'))
# **（監査 D-2）** 口の名前と HTTP の番号を本文に出さない
$snapNoBody = $snapUp.Clone()
$snapNoBody.backup_status = 503
$snapNoBody.backup = $null
$txtNoBody = New-StatusText -Snapshot $snapNoBody
Check '理由が取れない失敗は「詳細: 503」と出す' (($txtNoBody -match '詳細: 503') -and -not ($txtNoBody -match 'GET /api/backup'))
# **（監査 B-2）** 自分が起動したサーバが落ちたら知らせる（バルーンは見えないのでログで見る）。
# `Show-TrayBalloon` はアイコンが無くても「知らせ: …」を `.tray\tray.log` に残す。
$notifyCtx = @{ State = $state; Menu = $null; Icon = $null; Timer = $null; Snapshot = $null; Last = $null }
$prevUp = @{ state = 'up'; mode = 'own'; requests = 0; deletes = 0; deletes_stage3 = 0; backup_failed = $false }
$downOwn = $snapOk.Clone()
$downOwn.state = 'down'
$downOwn.mode = 'own'
Send-TrayNotifications -Ctx $notifyCtx -Snapshot $downOwn -Prev $prevUp
$logNow = [System.IO.File]::ReadAllText($script:TrayLog, [System.Text.Encoding]::UTF8)
Check '自分が起動したサーバが落ちたら知らせる' ($logNow -match '知らせ: サーバが止まりました')
$attachDown = $snapOk.Clone()
$attachDown.state = 'down'
$attachDown.mode = 'attach'
$beforeCount = ([regex]::Matches($logNow, '知らせ: サーバが止まりました')).Count
Send-TrayNotifications -Ctx $notifyCtx -Snapshot $attachDown -Prev $prevUp
$logNow2 = [System.IO.File]::ReadAllText($script:TrayLog, [System.Text.Encoding]::UTF8)
Check '他人のサーバが落ちても知らせない（自分は止めていない）' `
    ((([regex]::Matches($logNow2, '知らせ: サーバが止まりました')).Count) -eq $beforeCount)

# ---- 6. ツールチップとアイコン ----

Section '6. ツールチップとアイコンの形'
$tips = @{}
$icons = @{}
$cases = @(
    @{ name = 'なし'; requests = 0; deletes = 0 },
    @{ name = '要求あり'; requests = 3; deletes = 0 },
    @{ name = '削除あり'; requests = 0; deletes = 12 },
    @{ name = '両方'; requests = 3; deletes = 12 }
)
foreach ($c in $cases) {
    $s = $snapOk.Clone()
    $s.requests = $c.requests
    $s.deletes = $c.deletes
    $s.deletes_remain = -1
    $s.deletes_stage3 = -1      # 段 3 の数が無い形（前の版の snapshot）は今までどおり全部で数える
    $tips[$c.name] = Get-TrayTooltip -Snapshot $s
    $icons[$c.name] = (Get-StateIcon -Snapshot $s).icon.Handle
}
Check 'ツールチップが 4 通りで別' (@($tips.Values | Select-Object -Unique).Count -eq 4) ($tips.Values -join ' / ')
Check 'ツールチップは 63 字以内' (@($tips.Values | Where-Object { $_.Length -gt 63 }).Count -eq 0)
Check 'ツールチップに中黒（・）を使っていない' (@($tips.Values | Where-Object { $_.Contains([char]0x00B7) }).Count -eq 0)
Check 'アイコンが 4 通りで別' (@($icons.Values | Select-Object -Unique).Count -eq 4) ($icons.Values -join ' / ')
$bad = $snapOk.Clone()
$bad.backup_failed = $true
Check 'バックアップの失敗でアイコンの形が変わる' ((Get-StateIcon -Snapshot $bad).icon.Handle -ne $icons['なし'])
# **（監査 F-2）** ツールチップにも失敗を出す（アイコンだけでは何が起きたか分からない）
Check 'ツールチップに「バックアップに失敗しています」が出る' ((Get-TrayTooltip -Snapshot $bad) -match 'バックアップに失敗しています')
# **（監査 F-9）** 5 桁の件数（64 字の上限に当たる形）でも切る
$big = $snapOk.Clone()
$big.requests = 99999
$big.deletes = 99999
$big.deletes_stage3 = 99999
$tipBig = Get-TrayTooltip -Snapshot $big
Check '5 桁の件数でも 63 字以内' ($tipBig.Length -le 63) ('{0} 字: {1}' -f $tipBig.Length, $tipBig)
# **（監査 B-2）** 停止中は形で分かる（16 px で「ふつう」と区別できない色だけ、にしない）。
# **真ん中の画素**を比べる——× が交わる所なので、**枠の色だけを変えた実装では通らない**。
$snapDownIcon = $snapOk.Clone()
$snapDownIcon.state = 'down'
$snapNoneIcon = $snapOk.Clone()
$snapNoneIcon.requests = 0
$snapNoneIcon.deletes = 0
$snapNoneIcon.deletes_stage3 = 0
$downShot = Get-StateIcon -Snapshot $snapDownIcon
$noneShot = Get-StateIcon -Snapshot $snapNoneIcon
$midDown = $downShot.bmp.GetPixel(16, 17)
$midNone = $noneShot.bmp.GetPixel(16, 17)
Check '停止中のアイコンは「ふつう」と別の形（真ん中に印がある）' `
    (($midDown.R -ne $midNone.R) -or ($midDown.G -ne $midNone.G) -or ($midDown.B -ne $midNone.B)) `
    ('down=({0},{1},{2}) なし=({3},{4},{5})' -f $midDown.R, $midDown.G, $midDown.B, $midNone.R, $midNone.G, $midNone.B)
# **（監査 G-1(b)）** 印が数えるのは段 3 の行だけ（段 1 の 194 行で常に点かない）
$stage1Only = $snapOk.Clone()
$stage1Only.requests = 0
$stage1Only.deletes = 194
$stage1Only.deletes_stage3 = 0
Check '段 1 だけの削除では印が点かない' ((Get-StateIcon -Snapshot $stage1Only).icon.Handle -eq $icons['なし']) `
    ('deletes=194 deletes_stage3=0')
$stage3 = $snapOk.Clone()
$stage3.requests = 0
$stage3.deletes = 194
$stage3.deletes_stage3 = 2
Check '段 3 の行があれば印が点く' ((Get-StateIcon -Snapshot $stage3).icon.Handle -ne $icons['なし'])

# ---- 7. メニューの文言 ----

Section '7. メニューの文言（frontend-design.md §6.1）'
$ctx = @{ State = $state; Menu = $null; Icon = $null; Timer = $null; Snapshot = $null; Last = $null }
$ctx.Menu = New-TrayMenu -Ctx $ctx
$labels = @()
foreach ($it in $ctx.Menu.Items) { if ($it.Text) { $labels += $it.Text } }
$want = @('ブラウザで開く', '最近の削除を開く', '状態を見る', '再起動する', '終了する（サーバも止める）')
Check 'メニューは 5 つ' ($labels.Count -eq 5) ($labels -join ' / ')
Check '文言が設計のとおり' ((($labels -join '|') -eq ($want -join '|'))) ($labels -join ' / ')
Check '半角の中点（·）を使っていない' (@($labels | Where-Object { $_.Contains([char]0x00B7) }).Count -eq 0)
Check 'ダッシュ（—）で繋いでいない' (@($labels | Where-Object { $_.Contains([char]0x2014) }).Count -eq 0)
Check '「用意」「準備」を使っていない' (@($labels | Where-Object { $_ -match '用意|準備' }).Count -eq 0)
Check '設計書の節番号・工程の番号を出していない' (@($labels | Where-Object { $_ -match '§|P[0-9]' }).Count -eq 0)
Check '入口は「名前: 値」の形を崩していない' (@($labels | Where-Object { $_ -match ':' }).Count -eq 0)
# **（監査 D-3・D-4）** 人に見せる文に開発の記法（口の名前・`-Port`・英語の山）を出さない
$failTextShown = Get-StartFailureText -Note 'Traceback (most recent call last): File "C:\x\db.py", line 891'
Check '起動失敗の文は 2 文 + 詳細（トレースバックは「詳細」に入れる）' `
    (($failTextShown -match '^サーバを起動できませんでした。') -and ($failTextShown -match '（詳細: ') -and -not ($failTextShown -match '(?m)^Traceback'))
Check '起動失敗の文は見るファイルを実際のパスで言う' ($failTextShown -match '(?m)^[A-Za-z]:\\.*server.*\.err\.log を見てください。')
Check '起動失敗の文に -Port や cmd の名前を出さない' (-not ($failTextShown -match '-Port|\.cmd'))

# ---- 8. 添付のときのメニュー ----

Section '8. 添付のときのメニュー（既に動いていたサーバ）'
$attach = @{ Port = $Port; Mode = 'attach'; Proc = $null; StartedAt = $null; Snapshot = $null; Last = $null }
Update-TrayMenu -Ctx @{ State = $attach; Menu = $ctx.Menu } -Snapshot $snapOk
$exitItem = $ctx.Menu.Items.Find('mi-exit', $false)[0]
$restartItem = $ctx.Menu.Items.Find('mi-restart', $false)[0]
Check '終了の語が「トレイを閉じる（サーバは止めない）」に変わる' ($exitItem.Text -eq 'トレイを閉じる（サーバは止めない）') $exitItem.Text
Check '再起動は押せない' (-not $restartItem.Enabled)
Check '押せない理由を書いてある' ([bool]$restartItem.ToolTipText)
Update-TrayMenu -Ctx @{ State = $state; Menu = $ctx.Menu } -Snapshot $snapOk
Check '自分のサーバのときは「終了する（サーバも止める）」に戻る' ($exitItem.Text -eq '終了する（サーバも止める）') $exitItem.Text
Check '自分のサーバのときは再起動が押せる' ($restartItem.Enabled)
# **（監査 C-4）** `State.Mode` は `own` のままで、ポートに他人が立った形
$snapForeignMenu = $snapOk.Clone()
$snapForeignMenu.mode = 'attach'
$snapForeignMenu.foreign = $true
Update-TrayMenu -Ctx @{ State = $state; Menu = $ctx.Menu } -Snapshot $snapForeignMenu
Check '他人が立った形では添付の語になる（止めると言わない）' `
    (($exitItem.Text -eq 'トレイを閉じる（サーバは止めない）') -and (-not $restartItem.Enabled))
Update-TrayMenu -Ctx @{ State = $state; Menu = $ctx.Menu } -Snapshot $snapOk

# ---- 9. 終了は自分が起動した物だけ止める ----

Section '9. 終了は自分が起動した物だけ止める'
$stopped = Stop-OwnServer -State $state
Check '自分が起動したサーバは止まる' $stopped
Check '踏み台のプロセスが消えた' (-not (Test-PidAlive -ProcessId $firstChild))
Check '本体（/api/health が名乗った pid）も消えた' (-not (Test-PidAlive -ProcessId $firstServer)) ('本体=' + $firstServer)
$st = Get-ServerState -Port $Port
Check 'ポートが空いた（ours でない）' ($st.state -ne 'ours') ('state=' + $st.state)
Check 'このポートの python は 0 になった' ((Get-ServerProcessCount -Port $Port) -eq 0) ('count=' + (Get-ServerProcessCount -Port $Port))

# ---- 9b. メニューの終了の道（監査 F-4）----

Section '9b. メニューの「終了する」でもサーバを止める'
$state9 = @{ Port = $Port; Mode = 'none'; Proc = $null; ServerPid = 0; StartedAt = $null; Snapshot = $null; Last = $null }
$up9 = $null
try { $up9 = Start-OwnServer -State $state9 -DataDir $Replica } catch { $up9 = $null }
Check '（9b の下ごしらえ）もう一度自分で起動できた' ($null -ne $up9 -and $state9.Mode -eq 'own')
$ctx9 = @{ State = $state9; Menu = $ctx.Menu; Icon = $null; Timer = $null; Snapshot = $null; Last = $null }
Exit-Tray -Ctx $ctx9
Start-Sleep -Milliseconds 500
Check 'メニューの終了の道でも本体が消えた' (-not (Test-PidAlive -ProcessId $state9.ServerPid)) ('本体=' + $state9.ServerPid)
Check 'メニューの終了の道でも踏み台が消えた' ($null -eq $state9.Proc -or -not (Test-PidAlive -ProcessId $state9.Proc.Id))
Check 'メニューの終了の道でもポートが空いた' ((Get-ServerState -Port $Port).state -ne 'ours')
Check 'ログに「トレイを終了します」が残った' `
    ([System.IO.File]::ReadAllText($script:TrayLog, [System.Text.Encoding]::UTF8) -match 'トレイを終了します')

# ---- 10. 他人が起動したサーバは止めない ----

Section '10. 他人が起動したサーバは止めない'
# **他人のサーバも、この検査が置き場を明示して起動する**（監査 A-1 の①。
# 「親の環境を引き継ぐ」に頼らない。引継ぎが空なら実データを開いてしまう道だった）
$env:IMAGE_REVIEWER_DATA = $Replica
$stranger = Start-Process -FilePath $py -ArgumentList @('-m', 'image_reviewer.cli', 'serve', '--port', [string]($Port + 1)) `
    -WorkingDirectory $root -WindowStyle Hidden -PassThru `
    -RedirectStandardOutput (Join-Path $tmp 'stranger.out.log') -RedirectStandardError (Join-Path $tmp 'stranger.err.log')
$up = Wait-ServerUp -Port ($Port + 1) -TimeoutSec 60
Check '他人（この検査）が立てたサーバが上がった' ($null -ne $up)
$strangerPid = 0
if ($up) { $strangerPid = [int]$up.pid }
$shStranger = Invoke-Api -Port ($Port + 1) -Path '/api/health' -TimeoutSec 5
Check '他人のサーバも複製を開いている（実データではない）' `
    ($shStranger.ok -and ([string]$shStranger.body.data_dir).TrimEnd('\') -eq $Replica.TrimEnd('\')) `
    ('data_dir=' + $(if ($shStranger.ok) { $shStranger.body.data_dir } else { '-' }))
$attachState = @{ Port = $Port + 1; Mode = 'attach'; Proc = $null; ServerPid = 0; StartedAt = $null; Snapshot = $null; Last = $null }
$kept = Stop-OwnServer -State $attachState
Check '止める関数は true を返す（何もしない）' $kept
Check '他人のサーバは生きている' (Test-PidAlive -ProcessId $strangerPid)
$still = Invoke-Api -Port ($Port + 1) -Path '/api/health' -TimeoutSec 5
Check '他人のサーバは今も答えている（pid も同じ）' ($still.ok -and [int]$still.body.pid -eq $strangerPid) `
    ('pid=' + $(if ($still.ok) { $still.body.pid } else { '-' }) + ' want=' + $strangerPid)
Check '他人のサーバのログに「止めます」を書いていない' (-not ([System.IO.File]::ReadAllText($script:TrayLog, [System.Text.Encoding]::UTF8) -match ('サーバを止めます（pid {0}' -f $strangerPid)))

# **（監査 F-7・C-4）自分のサーバが落ちて、他人が同じポートに立った形**
$fakeOwn = @{ Port = $Port + 1; Mode = 'own'; Proc = $null; ServerPid = $strangerPid; StartedAt = Get-Date; Snapshot = $null; Last = $null }
$fakePids = @(Get-OwnServerPids -State $fakeOwn)
Check '踏み台の記録が無ければ、他人の pid を止める対象にしない' ($fakePids.Count -eq 0) ($fakePids -join ', ')
Check 'その形では持っていた pid を手放す' ($fakeOwn.ServerPid -eq 0) ('ServerPid=' + $fakeOwn.ServerPid)
$keptFake = Stop-OwnServer -State $fakeOwn
Check 'その形でも他人は止めない' ($keptFake -and (Test-PidAlive -ProcessId $strangerPid))

# **（監査 A-2 の芯）起動の競合: 他人が先に掴んでいたポートで自分も起動しようとする**
$raceState = @{ Port = $Port + 1; Mode = 'none'; Proc = $null; ServerPid = 0; StartedAt = $null; Snapshot = $null; Last = $null }
$raceOutcome = ''
try {
    $raced = Start-OwnServer -State $raceState -DataDir $Replica -TimeoutSec 15
    $raceOutcome = 'result=' + $raced.state
} catch {
    $raceOutcome = 'throw'
}
Check '競合では他人の pid を持たない（ServerPid は 0）' ($raceState.ServerPid -eq 0) ('ServerPid={0} / {1}' -f $raceState.ServerPid, $raceOutcome)
Check '競合を「自分のサーバ」と報告しない' (($raceOutcome -eq 'throw') -or ($raceOutcome -eq 'result=stranger')) $raceOutcome
$keptRace = Stop-OwnServer -State $raceState
Start-Sleep -Milliseconds 500
Check '競合の後始末でも他人は生きている' (Test-PidAlive -ProcessId $strangerPid)
$still2 = Invoke-Api -Port ($Port + 1) -Path '/api/health' -TimeoutSec 5
Check '競合の後でも他人は答えている（pid も同じ）' ($still2.ok -and [int]$still2.body.pid -eq $strangerPid) `
    ('pid=' + $(if ($still2.ok) { $still2.body.pid } else { '-' }) + ' want=' + $strangerPid)

# **（監査 A-2 の芯）「自分が起動した子か」を親子で見ているか。**
# 生きているが**他人のサーバの祖先ではない**プロセスを 1 つ立てて、「自分の子」のふりをさせる
# （**ここが緩むと、他人のサーバを自分の物として止める**。落ちることを壊し試験で見る）
$sleepPy = Join-Path $tmp 'bystander.py'
Set-Content -LiteralPath $sleepPy -Value 'import time' -Encoding utf8
Add-Content -LiteralPath $sleepPy -Value 'time.sleep(180)' -Encoding utf8
$bystander = Start-Process -FilePath $py -ArgumentList @($sleepPy) `
    -WorkingDirectory $tmp -WindowStyle Hidden -PassThru `
    -RedirectStandardOutput (Join-Path $tmp 'bystander.out.log') -RedirectStandardError (Join-Path $tmp 'bystander.err.log')
Start-Sleep -Milliseconds 1200
Check '見本のプロセスは生きている' (Test-PidAlive -ProcessId $bystander.Id)
Check '見本は他人のサーバの祖先ではない' (-not (Test-DescendantOf -ProcessId $strangerPid -AncestorId ([int]$bystander.Id)))
$bystanderProc = $bystander
Check '見本のプロセスを掴んでいる' ($null -ne $bystanderProc -and -not $bystanderProc.HasExited)
$waitStranger = $null
try { $waitStranger = Wait-ServerUp -Port ($Port + 1) -Proc $bystanderProc -TimeoutSec 8 } catch { $waitStranger = $null }
Check '自分の子でないサーバは「自分の物」として受け取らない' ($null -ne $waitStranger -and [string]$waitStranger.state -eq 'stranger') `
    ('state=' + $(if ($waitStranger) { $waitStranger.state } else { 'null' }))
$fakeOwn2 = @{ Port = $Port + 1; Mode = 'own'; Proc = $bystanderProc; ServerPid = $strangerPid; StartedAt = Get-Date; Snapshot = $null; Last = $null }
$fakePids2 = @(Get-OwnServerPids -State $fakeOwn2)
Check '自分の子でない本体は止める対象に混ぜない' ($fakePids2 -notcontains $strangerPid) ('対象=' + ($fakePids2 -join ', ') + ' / 他人=' + $strangerPid)
Check 'その形でも持っていた pid を手放す' ($fakeOwn2.ServerPid -eq 0) ('ServerPid=' + $fakeOwn2.ServerPid)
$keptFake2 = Stop-OwnServer -State $fakeOwn2
# この形ではポートに**他人**が居るので「止めました（ポートが空きました）」にはならない。
# 見るのは 1 点だけ: **他人が生きていること**。
Check 'その形でも他人は止めない（生きている）' (Test-PidAlive -ProcessId $strangerPid) ('kept=' + $keptFake2)
Check 'その形でも他人の pid に「止めます」を書かない' `
    (-not ([System.IO.File]::ReadAllText($script:TrayLog, [System.Text.Encoding]::UTF8) -match ('サーバを止めます（pid {0}' -f $strangerPid)))
Stop-TestProcess -ProcessId $bystander.Id

Stop-TestProcess -ProcessId $stranger.Id
if ($strangerPid -gt 0) { Stop-TestProcess -ProcessId $strangerPid }
Start-Sleep -Milliseconds 500
Check '検査の後始末で他人のサーバを止めた' (-not (Test-PidAlive -ProcessId $strangerPid))

# ---- 11. 記録 ----

Section '11. 記録'
$logText = ''
if (Test-Path -LiteralPath $script:TrayLog) { $logText = [System.IO.File]::ReadAllText($script:TrayLog, [System.Text.Encoding]::UTF8) }
Check 'ログに残っている（起動・停止・判断）' (($logText -match 'サーバを起動します') -and ($logText -match 'サーバを止めます') -and ($logText -match '既に動いているサーバに繋ぎます'))

# ---- まとめ ----

Section 'まとめ'
Write-Output ('ok {0} 件 / NG {1} 件' -f $script:Ok, $script:Ng)
if (-not $Keep) {
    if (Test-Path -LiteralPath $Replica) { Remove-Item -LiteralPath $Replica -Recurse -Force -ErrorAction SilentlyContinue }
    Write-Output ('（複製を消しました: {0}。-Keep で残せます）' -f $Replica)
} else {
    Write-Output ('（複製を残しました: {0}）' -f $Replica)
}
if ($script:Ng -gt 0) { exit 1 }
exit 0
