"""どのパスが無いのかを見る（読むだけ）。"""
import sqlite3
from pathlib import Path

P = "C:/work/image-reviwer/.data/db.sqlite3"
con = sqlite3.connect(f"file:{P}?mode=ro", uri=True)
cur = con.cursor()
rows = cur.execute(
    "select l.path, l.display_path, l.size, a.deleted_at,"
    " (select count(*) from deletion_log d where d.asset_id = l.asset_id) as dels"
    " from asset_location l join asset a on a.id = l.asset_id order by l.path").fetchall()
gone = [r for r in rows if not Path(r[0]).exists()]
here = [r for r in rows if Path(r[0]).exists()]
print("無い:", len(gone), "ある:", len(here))
for r in gone[:4]:
    print("  無:", r[0], "|", r[1], "| deleted_at=", r[3], "| 台帳=", r[4])
for r in here[:4]:
    print("  有:", r[0], "| deleted_at=", r[3], "| 台帳=", r[4])
print("無い物のうち deleted_at がある:", sum(1 for r in gone if r[3]))
print("ある物のうち deleted_at がある:", sum(1 for r in here if r[3]))
print("無い物のうち台帳にある:", sum(1 for r in gone if r[4]))
print("ある物のうち台帳にある:", sum(1 for r in here if r[4]))
base = Path("C:/ai/comfyui_windows_portable/comfyui/output/comfyui/anima/20261010")
print("置き場 1 は存在する:", base.exists())
print("置き場 2 は存在する:", Path("C:/work/illust-authoring/.store/anima-dev").exists())
con.close()
