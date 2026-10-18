"""いまディスクにある 37 枚が、台帳（`deletion_log.size`）と同じ物かを調べる（読むだけ）。"""
import sqlite3
from pathlib import Path

P = "C:/work/image-reviwer/.data/db.sqlite3"
con = sqlite3.connect(f"file:{P}?mode=ro", uri=True)
cur = con.cursor()
rows = {r[0]: r[1] for r in cur.execute(
    "select path, size from deletion_log").fetchall()}
con.close()

folder = Path("C:/ai/ComfyUI_windows_portable/ComfyUI/output/ComfyUI/Anima/20261010")
files = sorted(folder.glob("*.png"))
print("いまディスクにある枚数:", len(files))
same = 0
diff = 0
notinledger = 0
for f in files:
    key = str(f).lower()
    size = rows.get(key)
    if size is None:
        notinledger += 1
        print("  台帳に無い:", f.name, f.stat().st_size)
    elif int(size) == f.stat().st_size:
        same += 1
    else:
        diff += 1
        print("  大きさが違う:", f.name, f.stat().st_size, "≠ 台帳", size)
print(f"台帳と同じ大きさ: {same} / 違う: {diff} / 台帳に無い: {notinledger}")
