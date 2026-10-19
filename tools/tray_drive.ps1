#Requires -Version 5.1
<#
.SYNOPSIS
    **人がメニューを押す代わり**に、実物のトレイ（アイコンとメニュー）を順に押す手順。

.DESCRIPTION
    `tools\tray.ps1 -DriveScript tools\tray_drive.ps1` で読み込まれ、`Invoke-TrayDrive` が
    呼ばれる。**本物の `ContextMenuStrip` の項目を `PerformClick()` で押す**ので、
    人が押したときと同じ道（`Invoke-TrayMenuAction`）を通る。押した結果は
    `<リポジトリ>\.tray\tray.log` に残る（これが「手で確かめた記録」の実体）。

    押す順:
    1. 何も無い状態の見え方（ツールチップ・アイコン・メニュー）
    2. **要求を 1 件投げて、5 秒の見張りが拾うか**（`POST /api/review-requests`）
    3. 「状態を見る」（窓。`-StatusAutoCloseMs` で自動で閉じる）
    4. 「最近の削除を開く」
    5. 「ブラウザで開く」と、ダブルクリックと同じ道
    6. 「再起動する」
    7. 「終了する（サーバも止める）」

.NOTES
    - ブラウザを実際に開くかは `tools\tray.ps1 -NoBrowser` に従う（ログには URL が残る）。
    - **利用者の 8790 では使わない**（`-Port 8795` など、自分が立てたサーバに付ける）。
    - 手順の途中で落ちたときは、**トレイが自分で終わる**（`Exit-Tray` を通る。試験で
      止まらないトレイとサーバを残さないため）。理由は `.tray\tray.log` に出る。
    - **要求の `conditions` / `wants` は配列**（契約が `type: array`。文字列で送ると 422。実測）。
#>

function Write-TrayLook {
    <# いま人に見えている物（ツールチップ・アイコンの形・メニューの語）をログに残す。 #>
    param([Parameter(Mandatory)][hashtable]$Ctx, [Parameter(Mandatory)][string]$When)
    $icon = '-'
    if ($null -ne $Ctx.Icon -and $null -ne $Ctx.Icon.Icon) { $icon = [string]$Ctx.Icon.Icon.Handle }
    $tip = '-'
    if ($null -ne $Ctx.Icon) { $tip = [string]$Ctx.Icon.Text }
    $labels = @()
    foreach ($it in $Ctx.Menu.Items) { if ($it.Text) { $labels += $it.Text } }
    $enabled = @()
    foreach ($it in $Ctx.Menu.Items) { if ($it.Text) { $enabled += ('{0}={1}' -f $it.Name, $(if ($it.Enabled) { '押せる' } else { '押せない' })) } }
    Write-TrayLog ('[{0}] ツールチップ「{1}」 アイコン={2}' -f $When, $tip, $icon)
    Write-TrayLog ('[{0}] メニュー: {1}' -f $When, ($labels -join ' / '))
    Write-TrayLog ('[{0}] 押せる・押せない: {1}' -f $When, ($enabled -join ' '))
}

function Send-TrayDriveRequest {
    <# エージェントの真似をして要求を 1 件投げる（`POST /api/review-requests`）。**証拠を作るため**。 #>
    param([Parameter(Mandatory)][int]$Port, [Parameter(Mandatory)][string]$AssetId)
    $url = 'http://127.0.0.1:{0}/api/review-requests' -f $Port
    $body = @{
        asset_ids = @($AssetId)
        ask = '駆動の検査: この 1 枚を見てください'
        conditions = @('なし')
        origin = 'tray_drive'
        # **契約が `type: array`**（`wants` / `conditions`）。文字列で送ると 422 になる（実測）
        wants = @('keep_or_reject')
    } | ConvertTo-Json -Depth 4
    $bytes = [System.Text.Encoding]::UTF8.GetBytes($body)
    $req = [System.Net.HttpWebRequest]::Create($url)
    $req.Method = 'POST'
    $req.ContentType = 'application/json'
    $req.Timeout = 5000
    $req.ReadWriteTimeout = 5000
    $req.Proxy = $null
    $req.Headers.Add('X-Image-Reviewer-Actor', 'agent')
    $req.ContentLength = $bytes.Length
    $stream = $req.GetRequestStream()
    $stream.Write($bytes, 0, $bytes.Length)
    $stream.Close()
    # **断られても本文を読む**（番号だけでは何を直せばよいか分からない）。
    # **失敗しても駆動は止めない**（押す手順の残りは進める）
    $res = $null
    try {
        $res = $req.GetResponse()
    } catch [System.Net.WebException] {
        $res = $_.Exception.Response
        if ($null -eq $res) {
            Write-TrayLog ('[駆動] 要求を投げられませんでした: ' + $_.Exception.Message)
            return 0
        }
    }
    $status = [int]$res.StatusCode
    $text = (New-Object System.IO.StreamReader($res.GetResponseStream(), [System.Text.Encoding]::UTF8)).ReadToEnd()
    $res.Close()
    Write-TrayLog ('[駆動] 要求を投げました（HTTP {0}）: {1}' -f $status, $text)
    return $status
}

function Invoke-TrayDrive {
    <# 押す手順の本体。**1 つずつ、実物のメニューを押す。** #>
    param([Parameter(Mandatory)][hashtable]$Ctx)
    $menu = $Ctx.Menu
    Write-TrayLog '==== 駆動（人が押す代わり）を始めます ===='

    # 1. 何も無い状態
    Write-TrayLook -Ctx $Ctx -When '1. 起動直後'

    # 2. 要求を 1 件投げて、5 秒の見張りが拾うか見る
    $assets = Invoke-Api -Port $Ctx.State.Port -Path '/api/assets?limit=1'
    $assetId = ''
    if ($assets.ok -and $null -ne $assets.body -and $assets.body.items.Count -gt 0) {
        $assetId = [string]$assets.body.items[0].id
    }
    Write-TrayLog ('[駆動] 対象の 1 枚: {0}' -f $assetId)
    if ($assetId) {
        Send-TrayDriveRequest -Port $Ctx.State.Port -AssetId $assetId | Out-Null
        Write-TrayLog '[駆動] 5 秒の見張りが拾うのを待ちます（6 秒 + DoEvents）'
        Start-Sleep -Seconds 6
        # **UI スレッドが眠っている間、見張りの刻みは動けない**（メッセージが溜まるだけ）。
        # `DoEvents` で溜まった分を処理させて、「見張りが拾った」ことを見る（実測で必要だった）
        [System.Windows.Forms.Application]::DoEvents()
        Start-Sleep -Milliseconds 400
        [System.Windows.Forms.Application]::DoEvents()
        Write-TrayLook -Ctx $Ctx -When '2. 要求の後'
    } else {
        Write-TrayLog '[駆動] 1 枚も無いので、要求を投げる所は飛ばします'
    }

    # 3. 状態を見る（実物の窓。試験なので自動で閉じる）
    Write-TrayLog '[駆動] 「状態を見る」を押します'
    $menu.Items.Find('mi-status', $false)[0].PerformClick()
    Write-TrayLook -Ctx $Ctx -When '3. 状態を見た後'

    # 4. 最近の削除を開く
    Write-TrayLog '[駆動] 「最近の削除を開く」を押します'
    $menu.Items.Find('mi-deletes', $false)[0].PerformClick()

    # 5. ブラウザで開く（+ アイコンのダブルクリックと同じ道）
    Write-TrayLog '[駆動] 「ブラウザで開く」を押します'
    $menu.Items.Find('mi-open', $false)[0].PerformClick()
    Write-TrayLog '[駆動] ダブルクリックと同じ道を呼びます'
    Invoke-TrayMenuAction -Name 'open'

    # 6. 再起動する
    $before = $Ctx.State.ServerPid
    Write-TrayLog ('[駆動] 「再起動する」を押します（いまの本体 pid {0}）' -f $before)
    $menu.Items.Find('mi-restart', $false)[0].PerformClick()
    Write-TrayLog ('[駆動] 再起動の後: 本体 pid {0}（前は {1}）' -f $Ctx.State.ServerPid, $before)
    Write-TrayLook -Ctx $Ctx -When '6. 再起動の後'

    # 7. 終了する（サーバも止める）
    Write-TrayLog '[駆動] 「終了する」を押します'
    $menu.Items.Find('mi-exit', $false)[0].PerformClick()
    Write-TrayLog '==== 駆動を終わりました（ここから先はログに出ない）===='
}
