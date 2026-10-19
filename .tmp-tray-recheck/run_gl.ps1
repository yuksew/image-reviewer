# 使い捨て: 実データの複製を作り、11 画面 × 4 幅の gui_layout を回す（8792。
# **8790 は使わない**。実データは `mode=ro` の `backup()` と `copy2` だけ）。
$ErrorActionPreference = 'Stop'
$root = 'C:\work\image-reviwer'
$work = Join-Path $root '.tmp-tray-recheck\rA'
$rep = Join-Path $work 'data'
$py = Join-Path $root '.venv\Scripts\python.exe'
$env:UV_CACHE_DIR = Join-Path $root '.uv-cache'
Set-Location $root

if (-not (Test-Path (Join-Path $rep 'db.sqlite3'))) {
    Write-Output '== 複製を作る（backup() + copy2 + パスの貼り替え） =='
    New-Item -ItemType Directory -Force -Path $work | Out-Null
    & $py -X utf8 (Join-Path $root '.tmp-tray-recheck\mk_replica.py') $work
    if (-not (Test-Path (Join-Path $rep 'db.sqlite3'))) { Write-Output 'NG 複製ができない'; exit 1 }
    Write-Output '== seed（tags / exclusion / pending） =='
    & $py -X utf8 (Join-Path $root 'tools\gui_layout_seed.py') --data $rep --tags --exclusion --pending
} else {
    Write-Output '== 複製はもうある（作り直さない） =='
}

$env:IMAGE_REVIEWER_DATA = $rep
$env:IMAGE_REVIEWER_BACKUP_DIR = Join-Path $root '.tmp-tray-recheck\bk-gui'

Write-Output '== 8792 にサーバを立てる（複製・実データではない） =='
$log = Join-Path $root '.tmp-tray-recheck\gl-server.log'
$proc = Start-Process -FilePath $py -ArgumentList @('-m', 'image_reviewer.cli', 'serve', '--port', '8792') `
    -WorkingDirectory $root -WindowStyle Hidden -PassThru `
    -RedirectStandardOutput $log -RedirectStandardError (Join-Path $root '.tmp-tray-recheck\gl-server.err.log')
$base = 'http://127.0.0.1:8792'
$h = $null
foreach ($i in 1..60) {
    Start-Sleep -Milliseconds 500
    try {
        $got = Invoke-RestMethod -Uri "$base/api/health" -TimeoutSec 3
        if ($got.app -eq 'image-reviewer') { $h = $got; break }
    } catch { }
}
if ($null -eq $h) { Write-Output 'NG サーバが上がらない'; Get-Content $log -Encoding UTF8 -Tail 20; exit 1 }
Write-Output ('server up: pid ' + $h.pid + ' data=' + $h.data_dir)
if ([string]$h.data_dir -notlike '*\.tmp-tray-recheck\rA\*') { Write-Output 'NG 実データを開いている'; exit 1 }

$assets = Invoke-RestMethod -Uri "$base/api/assets?limit=8" -Headers @{ 'X-Image-Reviewer-Actor' = 'human' } -TimeoutSec 30
$ids = @($assets.items | ForEach-Object { $_.id })
$two = ($ids[0..1] -join ',')
$groups = Invoke-RestMethod -Uri "$base/api/groups" -Headers @{ 'X-Image-Reviewer-Actor' = 'human' } -TimeoutSec 30
$gid = ''
if ($groups.items -and $groups.items.Count -gt 0) { $gid = [string]$groups.items[0].id }
Write-Output ('assets: ' + ($ids -join ',') + ' / group: ' + $gid)

$runs = @(
    @{ name = 'compare'; args = @('--count', '8') },
    @{ name = 'requests'; args = @('--screen', 'requests') },
    @{ name = 'group'; args = @('--screen', 'group', '--group', $gid) },
    @{ name = 'asset'; args = @('--screen', 'asset', '--ids', $ids[0]) },
    @{ name = 'tags'; args = @('--screen', 'tags') },
    @{ name = 'jobs'; args = @('--screen', 'jobs') },
    @{ name = 'duplicates'; args = @('--screen', 'duplicates') },
    @{ name = 'pending'; args = @('--screen', 'pending') },
    @{ name = 'pending-ids'; args = @('--screen', 'pending', '--ids', $two) },
    @{ name = 'library'; args = @('--screen', 'library') },
    @{ name = 'settings'; args = @('--screen', 'settings') }
)
$sumOk = 0; $sumNg = 0
foreach ($run in $runs) {
    $out = Join-Path $root ('.tmp-tray-recheck\gl-' + $run.name + '.log')
    $all = @('--base', $base) + $run.args
    $p = Start-Process -FilePath 'node' -ArgumentList (@('tools/gui_layout.mjs') + $all) `
        -WorkingDirectory $root -WindowStyle Hidden -PassThru -Wait `
        -RedirectStandardOutput $out -RedirectStandardError ($out + '.err')
    $text = ''
    if (Test-Path $out) { $text = [System.IO.File]::ReadAllText($out, [System.Text.Encoding]::UTF8) }
    $ng = ([regex]::Matches($text, '(?m)^NG')).Count
    $ok = ([regex]::Matches($text, '(?m)^ok')).Count
    $sumOk += $ok; $sumNg += $ng
    Write-Output ('{0,-14} exit={1} ok={2} ng={3}' -f $run.name, $p.ExitCode, $ok, $ng)
    if ($ng -gt 0 -or $p.ExitCode -ne 0) {
        Get-Content $out -Encoding UTF8 | Select-String -Pattern '^NG' | Select-Object -First 4 | ForEach-Object { '    ' + $_.Line }
    }
}
Write-Output ('== 合計 ok=' + $sumOk + ' ng=' + $sumNg + ' ==')

Write-Output '== サーバを止める =='
& (Join-Path $env:SystemRoot 'System32\taskkill.exe') /PID $proc.Id /T /F 2>&1 | Out-Null
Start-Sleep -Seconds 2
Write-Output ('server gone: ' + (-not ($null -ne (Get-Process -Id $h.pid -ErrorAction SilentlyContinue))))

