"""**0 件の複製**を作る（`deletion_log` を空にする。実データは触らない）。

- `srv`（193 行の段 1 + 段 3 の 1 行）を丸ごと写してから、**複製の中だけ**で台帳を空にする
- `asset.deleted_at` も NULL に戻す（「1 件も消していない」状態にする）
"""
import shutil
import sqlite3
from pathlib import Path

SRC = Path("C:/work/image-reviwer/.tmp-p8-5-entries/srv")
DST = Path("C:/work/image-reviwer/.tmp-p8-5-entries/srv-zero")
if DST.exists():
    shutil.rmtree(DST)
shutil.copytree(SRC, DST)

con = sqlite3.connect(str(DST / "db.sqlite3"))
cur = con.cursor()
print("前: deletion_log =", cur.execute("select count(*) from deletion_log").fetchone()[0])
cur.execute("DELETE FROM deletion_log")
cur.execute("UPDATE asset SET deleted_at = NULL WHERE deleted_at IS NOT NULL")
con.commit()
print("後: deletion_log =", cur.execute("select count(*) from deletion_log").fetchone()[0])
print("後: asset.deleted_at が立っている枚 =",
      cur.execute("select count(*) from asset where deleted_at is not null").fetchone()[0])
con.close()
print("複製:", DST)
