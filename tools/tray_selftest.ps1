#Requires -Version 5.1
<#
.SYNOPSIS
    トレイ（`tools\tray.ps1`）の**自動で確かめられる所**を、実物で確かめる。

.DESCRIPTION
    人がメニューを押す所（UI）は `tools\tray_drive.ps1` が受け持つ。ここは**ロジック**を見る:

    | # | 線 | 何を壊すと落ちるか |
    | --- | --- | --- |
    | 1 | 前提（8790 を触らない・複製を作る） | ポートの検査を外すと、利用者のサーバを巻き込む |
    | 2 | 起動（自分で起動する） | `Start-OwnServer` の待ちを外すと落ちる |
    | 3 | **二重起動しない**（既に動いていれば繋ぐ） | `Initialize-ServerState` の `attach` を外すと 2 つ目が上がる |
    | 4 | **別のアプリのポートでは起動しない** | `other` の判定を外すと他人のポートを掴もうとする |
    | 5 | 状態の本文（**バックアップの失敗を必ず出す**） | `backup_failed` の行を消すと落ちる |
    | 6 | ツールチップとアイコンの形（4 通りが別） | 形の出し分けを 1 つに潰すと落ちる |
    | 7 | メニューの文言（§6.1。中黒・終止形） | 文言を変えると落ちる |
    | 8 | 添付のときのメニュー（終了の語と再起動の可否） | `Update-TrayMenu` を外すと落ちる |
    | 9 | **終了は自分が起動した物だけ止める** | PID ではなくポートで止める実装にすると落ちる |
    | 10 | **終了は他人が起動した物を止めない** | 同上 |
    | 11 | 記録（`.tray` のログ） | 記録を外すと落ちる |

    **利用者の 8790 は使わない**（別のポートと、合成した複製だけで回す）。
    **実データ `.data` には 1 バイトも触らない**（`tools\make_synthetic_db.py` の複製を使う）。

.EXAMPLE
    powershell -NoProfile -ExecutionPolicy Bypass -File tools\tray_selftest.ps1 -Port 8795

.NOTES
    **`-ExecutionPolicy Bypass` が要る**（この環境では .ps1 が素では実行できない。`docs/tray.md`）。
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

# ---- 1. 前提 ----

Section '1. 前提'
if ($Port -eq 8790) {
    Write-Output 'NG   8790 は利用者のサーバのポート。別のポート（例 8795）を -Port で渡す。'
    exit 2
}
Check 'ポートは 8790 ではない' ($Port -ne 8790) ("Port=$Port")
if (-not (Test-Path -LiteralPath $tmp)) { New-Item -ItemType Directory -Force -Path $tmp | Out-Null }

# トレイの関数を読む（**同じ 1 か所**を使う。検査だけ別の道を通ると何も守れない）
# `-TrayScript` は**壊し試験**のため（写しを壊して、この検査が落ちることを見る）
Write-Output ('     対象: {0}' -f $TrayScript)
. $TrayScript -Port $Port -DefineOnly
Check 'トレイの関数が読めた' ([bool](Get-Command Initialize-ServerState -ErrorAction SilentlyContinue))

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

if (-not $Replica) { $Replica = Join-Path $tmp 'replica' }
if ($Replica -like '*\.data*' -or $Replica -like '*.data') {
    Write-Output ('NG   複製の場所が実データに見える: {0}' -f $Replica)
    exit 2
}
& $py -X utf8 (Join-Path $root 'tools\make_synthetic_db.py') --out $Replica --count 3 --force | Out-Null
Check '合成の複製ができた（実データは触らない）' (Test-Path -LiteralPath (Join-Path $Replica 'db.sqlite3')) $Replica

# 日次のバックアップは**複製の外**へ（既定の %USERPROFILE% はこの環境では作れない）
$backupDir = Join-Path $tmp 'backups'
if (-not (Test-Path -LiteralPath $backupDir)) { New-Item -ItemType Directory -Force -Path $backupDir | Out-Null }
$env:IMAGE_REVIEWER_BACKUP_DIR = $backupDir

# ---- 2. 起動 ----

Section '2. 起動（自分で起動する）'
$state = @{ Port = $Port; Mode = 'none'; Proc = $null; ServerPid = 0; StartedAt = $null; Snapshot = $null; Last = $null }
$init = Initialize-ServerState -State $state -DataDir $Replica
Check '自分で起動した（own）' ($init.result -eq 'own') ('result=' + $init.result)
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
Check 'データ置き場は複製を指している' ($null -ne $health -and ([string]$health.data_dir).TrimEnd('\') -eq $Replica.TrimEnd('\')) `
    ('health.data_dir=' + $(if ($health) { $health.data_dir } else { '-' }))
$firstChild = 0
if ($state.Proc) { $firstChild = $state.Proc.Id }
$firstServer = $state.ServerPid

# ---- 3. 二重起動しない ----

Section '3. 二重起動しない（既に動いていれば繋ぐ）'
$before = @(Get-Process -Name python -ErrorAction SilentlyContinue).Count
$state2 = @{ Port = $Port; Mode = 'none'; Proc = $null; ServerPid = 0; StartedAt = $null; Snapshot = $null; Last = $null }
$init2 = Initialize-ServerState -State $state2 -DataDir $Replica
$after = @(Get-Process -Name python -ErrorAction SilentlyContinue).Count
Check '2 回目は起動せずに繋ぐ（attach）' ($init2.result -eq 'attach') ('result=' + $init2.result)
Check 'python の数が増えていない' ($after -eq $before) ('before={0} after={1}' -f $before, $after)
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
Check '相手のプロセスを止めていない' (Test-PidAlive -ProcessId $other.Id)
try { & (Join-Path $env:SystemRoot 'System32\taskkill.exe') /PID $other.Id /T /F 2>&1 | Out-Null } catch { }
Start-Sleep -Milliseconds 500
Check '塞いだポートは自分で片付けた' (-not (Test-PidAlive -ProcessId $other.Id))

# ---- 5. 状態の本文 ----

Section '5. 状態の本文（バックアップの失敗を必ず出す）'
$snapUp = @{
    at = Get-Date; state = 'up'; mode = 'own'; port = $Port
    health = $health; backup_status = 200; requests = 3; deletes = 12; deletes_remain = 192
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
Check '停止中のときは理由と次の一手を出す' (($txtDown -match '停止中') -and ($txtDown -match '再起動する'))

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

# ---- 9. 終了は自分が起動した物だけ止める ----

Section '9. 終了は自分が起動した物だけ止める'
$stopped = Stop-OwnServer -State $state
Check '自分が起動したサーバは止まる' $stopped
Check '踏み台のプロセスが消えた' (-not (Test-PidAlive -ProcessId $firstChild))
Check '本体（/api/health が名乗った pid）も消えた' (-not (Test-PidAlive -ProcessId $firstServer)) ('本体=' + $firstServer)
$st = Get-ServerState -Port $Port
Check 'ポートが空いた（ours でない）' ($st.state -ne 'ours') ('state=' + $st.state)

# ---- 10. 他人が起動したサーバは止めない ----

Section '10. 他人が起動したサーバは止めない'
$stranger = Start-Process -FilePath $py -ArgumentList @('-m', 'image_reviewer.cli', 'serve', '--port', [string]($Port + 1)) `
    -WorkingDirectory $root -WindowStyle Hidden -PassThru `
    -RedirectStandardOutput (Join-Path $tmp 'stranger.out.log') -RedirectStandardError (Join-Path $tmp 'stranger.err.log')
$up = Wait-ServerUp -Port ($Port + 1) -TimeoutSec 60
Check '他人（この検査）が立てたサーバが上がった' ($null -ne $up)
$strangerPid = 0
if ($up) { $strangerPid = [int]$up.pid }
$attachState = @{ Port = $Port + 1; Mode = 'attach'; Proc = $null; ServerPid = 0; StartedAt = $null; Snapshot = $null; Last = $null }
$kept = Stop-OwnServer -State $attachState
Check '止める関数は true を返す（何もしない）' $kept
Check '他人のサーバは生きている' (Test-PidAlive -ProcessId $strangerPid)
$still = Invoke-Api -Port ($Port + 1) -Path '/api/health' -TimeoutSec 5
Check '他人のサーバは今も答えている（pid も同じ）' ($still.ok -and [int]$still.body.pid -eq $strangerPid) `
    ('pid=' + $(if ($still.ok) { $still.body.pid } else { '-' }) + ' want=' + $strangerPid)
Check '他人のサーバのログに「止めます」を書いていない' (-not ([System.IO.File]::ReadAllText($script:TrayLog, [System.Text.Encoding]::UTF8) -match ('サーバを止めます（pid {0}' -f $strangerPid)))
try { & (Join-Path $env:SystemRoot 'System32\taskkill.exe') /PID $stranger.Id /T /F 2>&1 | Out-Null } catch { }
if ($strangerPid -gt 0) { try { & (Join-Path $env:SystemRoot 'System32\taskkill.exe') /PID $strangerPid /T /F 2>&1 | Out-Null } catch { } }
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
