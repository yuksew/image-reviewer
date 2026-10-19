# 使い捨て: 「ブラウザで開く」を**実際に**押す（本物のブラウザが開くかを見る）。
# `tools\tray_drive.ps1` と違い、-NoBrowser を付けずに走らせる。
function Invoke-TrayDrive {
    param([Parameter(Mandatory)][hashtable]$Ctx)
    Write-TrayLog '[駆動] 「ブラウザで開く」を実際に押します（本物のブラウザが開く）'
    $Ctx.Menu.Items.Find('mi-open', $false)[0].PerformClick()
    Start-Sleep -Seconds 4
    Write-TrayLog '[駆動] 「終了する」を押します'
    $Ctx.Menu.Items.Find('mi-exit', $false)[0].PerformClick()
}
