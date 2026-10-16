# .agents/skills/<name>/ を原本にして、Claude Code が読む .claude/skills/<name> をジャンクションで指す。
# 使い方（リポジトリの根で）: powershell -ExecutionPolicy Bypass -File .agents\link-skills.ps1
# 何度打っても同じ結果になる。新しい skill を .agents/skills/ に足したら、これをもう一度打つだけ。
# 根拠: docs/skills-layout.md
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$src = Join-Path $root ".agents\skills"
$dst = Join-Path $root ".claude\skills"
New-Item -ItemType Directory -Force $dst | Out-Null
foreach ($dir in Get-ChildItem -Directory $src) {
    $link = Join-Path $dst $dir.Name
    if (Test-Path $link) {
        $item = Get-Item $link -Force
        if ($item.LinkType -eq "Junction" -and ($item.Target -replace '\\$','') -ieq ($dir.FullName -replace '\\$','')) {
            Write-Host "ok     $($dir.Name)"
            continue
        }
        Write-Host "replace $($dir.Name)（ジャンクションでない、または向き先が違う）"
        if ($item.LinkType) { cmd /c rmdir "$link" } else { Remove-Item -Recurse -Force $link }
    }
    cmd /c mklink /J "$link" "$($dir.FullName)" | Out-Null
    Write-Host "linked $($dir.Name) -> .agents\skills\$($dir.Name)"
}
# 原本に無いジャンクションは消す（名前を変えたときの残骸）
foreach ($item in Get-ChildItem -Force $dst | Where-Object { $_.LinkType -eq "Junction" }) {
    if (-not (Test-Path (Join-Path $src $item.Name))) {
        cmd /c rmdir "$($item.FullName)"
        Write-Host "removed $($item.Name)（原本が無い）"
    }
}
