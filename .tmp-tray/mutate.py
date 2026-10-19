"""壊し試験: `tools/tray.ps1` の写しを 1 か所ずつ壊して `tools/_mutant.ps1` を作る。

**検査が「壊すと落ちる」ことを見るため**（家風: 自分のテストを信じない）。
`tools/_mutant.ps1` は同じフォルダに置く（`$PSScriptRoot` からリポジトリの根を出すため）。

使い方:
    python .tmp-tray/mutate.py M1        # tools/_mutant.ps1 を作る
    python .tmp-tray/mutate.py --list    # 一覧
"""
import pathlib
import sys

ROOT = pathlib.Path(r"C:\work\image-reviwer")
SRC = ROOT / "tools" / "tray.ps1"
OUT = ROOT / "tools" / "_mutant.ps1"

MUTS = {
    # 1. 既に動いていても繋がずに、もう 1 つ起動してしまう（二重起動）
    "M1": ("    if ($probe.state -eq 'ours') {",
           "    if ($false) {"),
    # 2. 別のアプリが使っているポートでも起動しようとする
    "M2": ("    if ($probe.state -eq 'other') {",
           "    if ($false) {"),
    # 3. 「自分が起動した物だけ止める」を壊し、ポートから相手を探して止める（危ない実装）
    "M3": ("""    if ($State.Mode -ne 'own' -or ($null -eq $State.Proc -and -not $State.ServerPid)) {
        Write-TrayLog 'このトレイが起動したサーバではありません。止めません。'
        return $true
    }
    $targets = @(Get-OwnServerPids -State $State)""",
           """    $st0 = Get-ServerState -Port $State.Port
    $targets = @()
    if ($st0.state -eq 'ours') { $targets += [int]$st0.pid }"""),
    # 4. バックアップの失敗を出さない（黙って失敗する）
    "M4": ("""    if ($Snapshot.backup_failed) {
        $out.Add('')""",
           """    if ($false) {
        $out.Add('')"""),
    # 5. アイコンの形を出し分けない
    "M5": ("    elseif ($Snapshot.requests -gt 0) { $key = 'request' }",
           "    elseif ($false) { $key = 'request' }"),
    # 6. メニューの文言を崩す
    "M6": ("$open = $menu.Items.Add('ブラウザで開く')",
           "$open = $menu.Items.Add('開く')"),
    # 7. ツールチップから「最近の削除」を落とす
    "M7": ("        if ($Snapshot.deletes -gt 0) { $parts.Add(('最近の削除 {0}' -f $Snapshot.deletes)) }",
           "        if ($false) { $parts.Add(('最近の削除 {0}' -f $Snapshot.deletes)) }"),
}


def main() -> int:
    if len(sys.argv) != 2 or sys.argv[1] in ("-h", "--help"):
        print(__doc__)
        return 0
    if sys.argv[1] == "--list":
        for k, (old, _new) in MUTS.items():
            print(k, "->", old.strip().splitlines()[0][:70])
        return 0
    key = sys.argv[1]
    if key not in MUTS:
        print("知らない変異:", key)
        return 2
    old, new = MUTS[key]
    text = SRC.read_text(encoding="utf-8-sig")
    if old not in text:
        print("見つからない（実装が変わった？）:", key)
        return 3
    text = text.replace(old, new, 1)
    OUT.write_text(text, encoding="utf-8-sig")
    print("作った:", OUT, "変異:", key)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
