# Throwaway: run the 11 gui_layout checks against a replica server on 8791.
# ASCII only (no BOM needed). The replica is .tmp-tray\gui (built by gui_replica.py + gui_layout_seed.py).
$ErrorActionPreference = 'Continue'
$root = 'C:\work\image-reviwer'
$rep = Join-Path $root '.tmp-tray\gui'
$env:UV_CACHE_DIR = Join-Path $root '.uv-cache'
$env:IMAGE_REVIEWER_DATA = $rep
$env:IMAGE_REVIEWER_BACKUP_DIR = Join-Path $root '.tmp-tray\backups-gui'
$base = 'http://127.0.0.1:8791'
$log = Join-Path $root '.tmp-tray\gui-layout-server.log'

Write-Output '== start server on 8791 (replica) =='
$py = Join-Path $root '.venv\Scripts\python.exe'
$proc = Start-Process -FilePath $py -ArgumentList @('-m', 'image_reviewer.cli', 'serve', '--port', '8791') `
    -WorkingDirectory $root -WindowStyle Hidden -PassThru `
    -RedirectStandardOutput $log -RedirectStandardError (Join-Path $root '.tmp-tray\gui-layout-server.err.log')
$up = $false
foreach ($i in 1..60) {
    Start-Sleep -Milliseconds 500
    try {
        $h = Invoke-RestMethod -Uri "$base/api/health" -TimeoutSec 3
        if ($h.app -eq 'image-reviewer') { $up = $true; break }
    } catch { }
}
if (-not $up) { Write-Output 'NG server did not come up'; Get-Content $log -Encoding UTF8 -Tail 20; exit 1 }
Write-Output ("server up: pid " + $h.pid + " data=" + $h.data_dir)

# ids for the screens that need them
$assets = Invoke-RestMethod -Uri "$base/api/assets?limit=8" -Headers @{ 'X-Image-Reviewer-Actor' = 'human' } -TimeoutSec 20
$ids = @($assets.items | ForEach-Object { $_.id })
Write-Output ('assets: ' + ($ids -join ','))
$two = ($ids[0..1] -join ',')
$groups = Invoke-RestMethod -Uri "$base/api/groups" -Headers @{ 'X-Image-Reviewer-Actor' = 'human' } -TimeoutSec 20
$gid = ''
if ($groups.items -and $groups.items.Count -gt 0) { $gid = [string]$groups.items[0].id }
Write-Output ('group: ' + $gid)

$runs = @(
    @{ name = 'compare(count 8)'; args = @('--count', '8') },
    @{ name = 'requests'; args = @('--screen', 'requests') },
    @{ name = 'group'; args = @('--screen', 'group', '--group', $gid) },
    @{ name = 'asset'; args = @('--screen', 'asset', '--ids', $ids[0]) },
    @{ name = 'tags'; args = @('--screen', 'tags') },
    @{ name = 'jobs'; args = @('--screen', 'jobs') },
    @{ name = 'duplicates'; args = @('--screen', 'duplicates') },
    @{ name = 'pending'; args = @('--screen', 'pending') },
    @{ name = 'pending --ids'; args = @('--screen', 'pending', '--ids', $two) },
    @{ name = 'library'; args = @('--screen', 'library') },
    @{ name = 'settings'; args = @('--screen', 'settings') }
)
$summary = @()
foreach ($run in $runs) {
    $out = Join-Path $root ('.tmp-tray\gui-layout-' + ($run.name -replace '[^A-Za-z0-9]+', '-') + '.log')
    $all = @('--base', $base) + $run.args
    $p = Start-Process -FilePath 'node' -ArgumentList (@('tools/gui_layout.mjs') + $all) `
        -WorkingDirectory $root -WindowStyle Hidden -PassThru -Wait `
        -RedirectStandardOutput $out -RedirectStandardError ($out + '.err')
    $text = ''
    if (Test-Path $out) { $text = [System.IO.File]::ReadAllText($out, [System.Text.Encoding]::UTF8) }
    $ng = ([regex]::Matches($text, '(?m)^NG')).Count
    $ok = ([regex]::Matches($text, '(?m)^ok')).Count
    $summary += [pscustomobject]@{ screen = $run.name; exit = $p.ExitCode; ok = $ok; ng = $ng }
    Write-Output ('{0,-16} exit={1} ok={2} ng={3}' -f $run.name, $p.ExitCode, $ok, $ng)
    if ($ng -gt 0 -or $p.ExitCode -ne 0) {
        Get-Content $out -Encoding UTF8 | Select-String -Pattern '^NG' | Select-Object -First 4 | ForEach-Object { '    ' + $_.Line }
    }
}
Write-Output '== summary =='
$summary | Format-Table -AutoSize | Out-String | Write-Output
Write-Output ('total ok=' + ($summary | Measure-Object -Property ok -Sum).Sum + ' ng=' + ($summary | Measure-Object -Property ng -Sum).Sum)

Write-Output '== stop server =='
& (Join-Path $env:SystemRoot 'System32\taskkill.exe') /PID $proc.Id /T /F 2>&1 | Out-Null
Start-Sleep -Seconds 2
$still = $null -ne (Get-Process -Id $h.pid -ErrorAction SilentlyContinue)
Write-Output ('server gone: ' + (-not $still))
