# gui_layout を複製（8797）で一通り回す。**実データの 8790 では回さない**
$env:UV_CACHE_DIR = "C:\work\image-reviwer\.uv-cache"
$log = "C:\work\image-reviwer\.tmp-p8-5-entries\layout.out.txt"
$base = "http://127.0.0.1:8797"
$group = "01M55R95PD89SR1EVB0JT480G2"
$asset = "01M4Z0KJR69CW8RA2R5Q9ZXHHW"
"" | Out-File -Encoding utf8 $log
$screens = @(
  @("library(768)", @("--screen", "library", "--viewport", "768x1360")),
  @("duplicates", @("--screen", "duplicates")),
  @("pending", @("--screen", "pending")),
  @("settings", @("--screen", "settings")),
  @("tags", @("--screen", "tags")),
  @("jobs", @("--screen", "jobs")),
  @("requests", @("--screen", "requests")),
  @("group", @("--screen", "group", "--group", $group)),
  @("asset", @("--screen", "asset", "--ids", $asset)),
  @("compare", @("--count", "8"))
)
foreach ($s in $screens) {
  $name = $s[0]; $args = $s[1]
  "`n===== $name =====" | Out-File -Encoding utf8 -Append $log
  $out = & node C:\work\image-reviwer\tools\gui_layout.mjs --base $base @args 2>&1
  $code = $LASTEXITCODE
  $out | Out-File -Encoding utf8 -Append $log
  "exit=$code" | Out-File -Encoding utf8 -Append $log
}
"`n===== 終わり =====" | Out-File -Encoding utf8 -Append $log
