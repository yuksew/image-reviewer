"""自己検査の PID 判定を `Test-PidAlive` に寄せる（PID 0 を「生きている」と数えない）。

PowerShell にヒアドキュメントが無いので、置き換えは Python のファイルで行う。
"""
import pathlib

p = pathlib.Path(r"C:\work\image-reviwer\tools\tray_selftest.ps1")
t = p.read_text(encoding="utf-8")
pairs = [
    ("Check '1 つ目の踏み台が生きている' ($null -ne (Get-Process -Id $firstChild -ErrorAction SilentlyContinue))",
     "Check '1 つ目の踏み台が生きている' (Test-PidAlive -Pid $firstChild)"),
    ("Check '相手のプロセスを止めていない' ($null -ne (Get-Process -Id $other.Id -ErrorAction SilentlyContinue))",
     "Check '相手のプロセスを止めていない' (Test-PidAlive -Pid $other.Id)"),
    ("Check '塞いだポートは自分で片付けた' ($null -eq (Get-Process -Id $other.Id -ErrorAction SilentlyContinue))",
     "Check '塞いだポートは自分で片付けた' (-not (Test-PidAlive -Pid $other.Id))"),
    ("Check '踏み台のプロセスが消えた' ($null -eq (Get-Process -Id $firstChild -ErrorAction SilentlyContinue))",
     "Check '踏み台のプロセスが消えた' (-not (Test-PidAlive -Pid $firstChild))"),
    ("Check '本体（/api/health が名乗った pid）も消えた' ($null -eq (Get-Process -Id $firstServer -ErrorAction SilentlyContinue)) ('本体=' + $firstServer)",
     "Check '本体（/api/health が名乗った pid）も消えた' (-not (Test-PidAlive -Pid $firstServer)) ('本体=' + $firstServer)"),
    ("Check '他人のサーバは生きている' ($null -ne (Get-Process -Id $strangerPid -ErrorAction SilentlyContinue))",
     "Check '他人のサーバは生きている' (Test-PidAlive -Pid $strangerPid)"),
    ("Check '検査の後始末で他人のサーバを止めた' ($null -eq (Get-Process -Id $strangerPid -ErrorAction SilentlyContinue))",
     "Check '検査の後始末で他人のサーバを止めた' (-not (Test-PidAlive -Pid $strangerPid))"),
]
for old, new in pairs:
    if old not in t:
        raise SystemExit("見つからない: " + old[:70])
    t = t.replace(old, new)
p.write_text(t, encoding="utf-8")
print("置き換え", len(pairs), "か所")
