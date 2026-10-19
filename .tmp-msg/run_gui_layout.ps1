# gui_layout の 11 本を回す（**複製のサーバ 8791 に対して**。実データの 8790 は触らない）。
# 使い捨て（`.tmp-msg/`）。
$env:UV_CACHE_DIR = "C:\work\image-reviwer\.uv-cache"
$env:PYTHONIOENCODING = "utf-8"
$env:PYTHONUTF8 = "1"
$log = "C:\work\image-reviwer\.tmp-msg\gui_layout.log"
Remove-Item $log -ErrorAction SilentlyContinue
$base = "http://127.0.0.1:8791"
$A1 = "01M5AAS6ES9F2TBVFJFEF85JFR"
$A2 = "01M4Z0KJR69CW8RA2R5Q9ZXHHW"
$G1 = "01M58PERHX9ZTVS1XVDA82YZQ2"
$runs = @(
  @{ name = "compare";       args = @("--count", "8") },
  @{ name = "requests";      args = @("--screen", "requests") },
  @{ name = "group";         args = @("--screen", "group", "--group", $G1) },
  @{ name = "asset";         args = @("--screen", "asset", "--ids", $A1) },
  @{ name = "tags";          args = @("--screen", "tags") },
  @{ name = "jobs";          args = @("--screen", "jobs") },
  @{ name = "duplicates";    args = @("--screen", "duplicates") },
  @{ name = "pending";       args = @("--screen", "pending") },
  @{ name = "pending+ids";   args = @("--screen", "pending", "--ids", "$A1,$A2") },
  @{ name = "library";       args = @("--screen", "library") },
  @{ name = "settings";      args = @("--screen", "settings") }
)
foreach ($r in $runs) {
  $out = & node tools/gui_layout.mjs --base $base @($r.args) 2>&1
  $code = $LASTEXITCODE
  $okc = @($out | Where-Object { $_ -match '^ok ' }).Count
  $ngc = @($out | Where-Object { $_ -match 'NG' }).Count
  Add-Content -Path $log -Value ("=== " + $r.name + " exit=" + $code + " ok=" + $okc + " ng-lines=" + $ngc) -Encoding utf8
  Add-Content -Path $log -Value (($out | ForEach-Object { [string]$_ }) -join "`n") -Encoding utf8
  Write-Output ($r.name + " | exit=" + $code + " ok=" + $okc + " ng=" + $ngc + " | last: " + (($out | Select-Object -Last 1)))
  if ($code -ne 0) { Write-Output (($out | Select-Object -Last 25) -join "`n") }
}
