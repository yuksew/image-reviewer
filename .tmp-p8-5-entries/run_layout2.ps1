# seed の後で、入口に関わる画面を回す（複製 8797）
$env:UV_CACHE_DIR = "C:\work\image-reviwer\.uv-cache"
$log = "C:\work\image-reviwer\.tmp-p8-5-entries\layout2.out.txt"
$base = "http://127.0.0.1:8797"
"" | Out-File -Encoding utf8 $log
$screens = @(
  @("library", @("--screen", "library")),
  @("pending", @("--screen", "pending")),
  @("tags", @("--screen", "tags")),
  @("settings", @("--screen", "settings")),
  @("duplicates", @("--screen", "duplicates"))
)
foreach ($s in $screens) {
  $name = $s[0]; $a = $s[1]
  "`n===== $name =====" | Out-File -Encoding utf8 -Append $log
  $out = & node C:\work\image-reviwer\tools\gui_layout.mjs --base $base @a 2>&1
  $code = $LASTEXITCODE
  $out | Out-File -Encoding utf8 -Append $log
  "exit=$code" | Out-File -Encoding utf8 -Append $log
}
"`n===== 終わり =====" | Out-File -Encoding utf8 -Append $log
