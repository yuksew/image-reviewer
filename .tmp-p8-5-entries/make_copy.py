"""実データの複製を作る（**`backup()` で WAL を畳んでから**。実データは 1 バイトも書かない）。

- DB: `sqlite3.Connection.backup()`（`cp` だと `-wal` の未畳み込み分＝判断が抜ける）
- 画像の実体は**複製しない**（サムネイルと sidecar / export だけ）。置き場は実データのまま読むだけ
"""
import shutil
import sqlite3
from pathlib import Path

SRC = Path("C:/work/image-reviwer/.data")
DST = Path("C:/work/image-reviwer/.tmp-p8-5-entries/srv")
if DST.exists():
    shutil.rmtree(DST)
DST.mkdir(parents=True)

src = sqlite3.connect(f"file:{SRC.as_posix()}/db.sqlite3?mode=ro", uri=True)
dst = sqlite3.connect(str(DST / "db.sqlite3"))
src.backup(dst)
dst.close()
src.close()

for name in ("export", "sidecar", "thumbs"):
    shutil.copytree(SRC / name, DST / name)
for name in ("store.json",):
    shutil.copy2(SRC / name, DST / name)

con = sqlite3.connect(str(DST / "db.sqlite3"))
cur = con.cursor()
print("複製:", DST)
print("assets:", cur.execute("select count(*) from asset").fetchone()[0])
print("deletion_log:", cur.execute("select count(*) from deletion_log").fetchone()[0])
print("judgements:", cur.execute("select count(*) from decision").fetchone()[0])
print("-wal は無い:", not (DST / "db.sqlite3-wal").exists())
con.close()
