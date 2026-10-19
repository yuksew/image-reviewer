"""`Test-PidAlive` の引数名を `-ProcessId` に直す。

`$Pid` は PowerShell の**読み取り専用の自動変数**（`$PID`）と同じ名前で、引数に取ると
「Cannot overwrite variable Pid because it is read-only or constant」で落ちる（実際に踏んだ）。
"""
import pathlib

p = pathlib.Path(r"C:\work\image-reviwer\tools\tray_selftest.ps1")
t = p.read_text(encoding="utf-8")
pairs = [
    ("    param([int]$Pid)\n    if ($Pid -le 0) { return $false }\n    return $null -ne (Get-Process -Id $Pid -ErrorAction SilentlyContinue)",
     "    param([int]$ProcessId)\n    if ($ProcessId -le 0) { return $false }\n    return $null -ne (Get-Process -Id $ProcessId -ErrorAction SilentlyContinue)"),
]
for old, new in pairs:
    if old not in t:
        raise SystemExit("見つからない: " + old[:60])
    t = t.replace(old, new)
n = t.count("-Pid ")
t = t.replace("-Pid ", "-ProcessId ")
p.write_text(t, encoding="utf-8")
print("param を直し、呼び出し", n, "か所を -ProcessId にした")
