"""再確認の壊し試験（監査側）。tools/tray.ps1 の写しを 1 か所ずつ壊し、tray_selftest.ps1 -TrayScript で回す。
本物の tools/ は触らない。写しの $script:RepoRoot だけリポジトリに固定する。
使い方: .venv\\Scripts\\python.exe -X utf8 .tmp-tray-recheck\\mut.py [名前 ...]
"""
from __future__ import annotations
import re, subprocess, sys
from pathlib import Path

REPO = Path(r"C:\work\image-reviwer")
SRC = REPO / "tools" / "tray.ps1"
SELFTEST = REPO / "tools" / "tray_selftest.ps1"
OUT = REPO / ".tmp-tray-recheck" / "mut"

# (名前, 壊す前, 壊した後, 全部置き換えるか)
M = [
    # --- 実装者の 13 のうち芯の 6 つを取り直す ---
    ("M-A1a", "    if ($DataDir) { return $DataDir }\n    if ($script:DefineOnly) {", "    if ($DataDir) { return $DataDir }\n    if ($false) {", False),
    ("M-A1c", "    $env:IMAGE_REVIEWER_DATA = $where\n", "    if (-not $env:IMAGE_REVIEWER_DATA) { $env:IMAGE_REVIEWER_DATA = $where }\n", False),
    ("M-A2a", "            if (Test-DescendantOf -ProcessId ([int]$st.pid) -AncestorId ([int]$Proc.Id)) { return $st }", "            if ($true) { return $st }", False),
    ("M-A2b", "            } elseif (Test-DescendantOf -ProcessId ([int]$st.pid) -AncestorId ([int]$State.Proc.Id)) {", "            } elseif ($true) {", False),
    ("M3", "    $targets = @(Get-OwnServerPids -State $State)", "    $portState = Get-ServerState -Port $State.Port\n    $targets = @()\n    if ($portState.state -eq 'ours' -and [int]$portState.pid -gt 0) { $targets += [int]$portState.pid }", False),
    ("M-B1", "            if ($Proc.HasExited) { return $null }", "            if ($false) { return $null }", False),
    # --- 監査側の変異 ---
    ("R1-C4", "    if ($State.Mode -eq 'own' -and [int]$State.ServerPid -gt 0 -and [int]$st.pid -ne [int]$State.ServerPid) {", "    if ($false) {", False),
    ("R2-C1", "        if ($snap.state -eq 'up' -and $snap.backup_failed -and ($null -eq $prev -or -not $prev.backup_failed)) {", "        if ($false) {", False),
    ("R3-C2", "-TimeoutSec 2", "-TimeoutSec 15", True),
    ("R3b-C2", "    if (-not $snap.unknown) {", "    if ($true) {", True),
    ("R4-C3", "        if (-not $State.Proc.HasExited) { $pids += [int]$State.Proc.Id }\n        else {", "        $pids += [int]$State.Proc.Id\n        if ($false) {", False),
    ("R5-D6", "    if (-not (Test-Path -LiteralPath $Path)) { return }\n    $prev = $Path -replace", "    return\n    $prev = $Path -replace", False),
    ("R6-D8", "    if ($Port -ne 8790) {", "    if ($false) {", False),
    ("R7-D7", "    $env:PYTHONUNBUFFERED = '1'", "    $env:PYTHONUNBUFFERED = $null", False),
    ("R8-init-cleanup", "            try { Stop-OwnServer -State $State | Out-Null } catch { }", "            ", False),
    ("R10-exit-foreign", "    if ($null -ne $Ctx.Snapshot -and $Ctx.Snapshot.ContainsKey('mode') -and [string]$Ctx.Snapshot.mode -eq 'attach') { $own = $false }", "", False),
    ("R11-restart-foreign", "    if ($Ctx.State.Mode -ne 'own' -or $foreign) {", "    if ($Ctx.State.Mode -ne 'own') {", False),
    ("R12-noProc", "    $up = Wait-ServerUp -Port $State.Port -Proc $proc -TimeoutSec $TimeoutSec", "    $up = Wait-ServerUp -Port $State.Port -TimeoutSec $TimeoutSec", False),
    ("R13-desc-true", "        if ($parent -eq $AncestorId) { return $true }", "        return $true", False),
    ("R14-real-false", "        return ($a -eq $b)", "        return $false", False),
    ("R16-balloon-all", "    $d3 = [int]$Snapshot.deletes_stage3", "    $d3 = [int]$Snapshot.deletes", False),
    ("R17-tip-unknown", "        if ($Snapshot.unknown) { $parts.Add('件数を確かめられません') }", "", False),
]

def make(name, old, new, allrep):
    d = OUT / name
    d.mkdir(parents=True, exist_ok=True)
    t = SRC.read_bytes().decode("utf-8-sig")
    if old not in t:
        raise SystemExit(f"{name}: not found {old[:60]!r}")
    t = t.replace(old, new) if allrep else t.replace(old, new, 1)
    root = "$script:RepoRoot = Split-Path -Parent $PSScriptRoot"
    assert root in t
    t = t.replace(root, "$script:RepoRoot = 'C:\\work\\image-reviwer'", 1)
    (d / "tray.ps1").write_bytes(("\ufeff" + t).encode("utf-8"))
    return d / "tray.ps1"

def kill_leftovers():
    s = ("Get-CimInstance Win32_Process -Filter \"Name = 'python.exe'\" | "
         "Where-Object { $_.CommandLine -match 'image_reviewer' -and $_.CommandLine -match '--port\\s+879[5-8](\\s|$)' } | "
         "ForEach-Object { & (Join-Path $env:SystemRoot 'System32\\taskkill.exe') /PID $_.ProcessId /T /F 2>&1 | Out-Null }")
    subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", s], capture_output=True, timeout=120)

def main():
    only = sys.argv[1:]
    rows = []
    for name, old, new, allrep in M:
        if only and name not in only:
            continue
        kill_leftovers()
        mt = make(name, old, new, allrep)
        op = OUT / name / "out.txt"
        with op.open("w", encoding="utf-8") as sink:
            p = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(SELFTEST),
                                "-Port", "8795", "-TrayScript", str(mt)], cwd=str(REPO), stdout=sink,
                               stderr=subprocess.STDOUT, timeout=400)
        out = op.read_text(encoding="utf-8", errors="replace")
        ngs = [l.strip() for l in out.splitlines() if l.strip().startswith("NG ")]
        summ = [l.strip() for l in out.splitlines() if re.match(r"^ok \d+ 件 / NG \d+ 件", l.strip())]
        rows.append((name, len(ngs), summ[0] if summ else "?", p.returncode))
        print(f"== {name}: NG {len(ngs)} / {summ[0] if summ else '?'} / exit {p.returncode}", flush=True)
        for ng in ngs[:6]:
            print("     " + ng, flush=True)
    kill_leftovers()
    print("\n---- まとめ ----")
    for r in rows:
        print(f"{r[0]:22s} NG={r[1]:3d}  {'落ちる' if r[1] else '**落ちない**'}  {r[2]}  exit={r[3]}")

if __name__ == "__main__":
    main()
