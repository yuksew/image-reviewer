# ASCII only (no BOM needed): ensure UTF-8 BOM and parse-check a PowerShell script.
param(
    [Parameter(Mandatory)][string]$Path,
    [switch]$Check  # parse only
)
$full = (Resolve-Path -LiteralPath $Path).Path
if (-not $Check) {
    $text = [System.IO.File]::ReadAllText($full, (New-Object System.Text.UTF8Encoding($false)))
    [System.IO.File]::WriteAllText($full, $text, (New-Object System.Text.UTF8Encoding($true)))
}
$bytes = [System.IO.File]::ReadAllBytes($full)
$bom = 'no-bom'
if ($bytes.Length -ge 3 -and $bytes[0] -eq 0xEF -and $bytes[1] -eq 0xBB -and $bytes[2] -eq 0xBF) { $bom = 'bom' }
$errs = $null
$tokens = $null
$null = [System.Management.Automation.Language.Parser]::ParseFile($full, [ref]$tokens, [ref]$errs)
Write-Output ("{0}  {1}  lines={2}  bytes={3}" -f $full, $bom, ([System.IO.File]::ReadAllLines($full)).Count, $bytes.Length)
if ($errs -and $errs.Count -gt 0) {
    Write-Output ("PARSE ERRORS: {0}" -f $errs.Count)
    foreach ($e in $errs) { Write-Output ("  line {0}: {1}" -f $e.Extent.StartLineNumber, $e.Message) }
    exit 1
}
Write-Output 'parse ok'
exit 0
