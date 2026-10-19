function Invoke-TrayDrive {
    param([hashtable]$Ctx)
    $h = Invoke-Api -Port $Ctx.State.Port -Path '/api/health'
    Write-TrayLog ('[recheck-drive] mode={0} data_dir={1}' -f $Ctx.State.Mode, $h.body.data_dir)
    Exit-Tray -Ctx $Ctx
}
