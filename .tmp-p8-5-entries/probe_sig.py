"""実データの**署名**を取る（読むだけ）。画像は 1 枚も動かさない。"""
import sqlite3
import hashlib
from pathlib import Path

P = "C:/work/image-reviwer/.data/db.sqlite3"
con = sqlite3.connect(f"file:{P}?mode=ro", uri=True)
cur = con.cursor()

print("deletion_log at の分布:", cur.execute(
    "select substr(at, 1, 16) as t, count(*) from deletion_log group by t order by t").fetchall())
print("stage 1 で hold_path/to_path が付いた行:", cur.execute(
    "select count(*) from deletion_log where hold_path is not null or to_path is not null"
).fetchone()[0])
print("asset_location の合計バイト:", cur.execute(
    "select sum(size) from asset_location").fetchone()[0])
print("asset_location の missing_at:", cur.execute(
    "select count(*) from asset_location where missing_at is not null").fetchone()[0])
print("実体のある登録パス:", cur.execute("select count(*) from asset_location").fetchone()[0])
rows = cur.execute("select path, size from asset_location order by path").fetchall()
digest = hashlib.sha256()
for path, size in rows:
    digest.update(f"{path}\t{size}\n".encode("utf-8"))
print("asset_location の署名 (path+size):", digest.hexdigest()[:16])

missing = 0
for path, _ in rows:
    if not Path(path).exists():
        missing += 1
print("ディスクに無い登録パス:", missing)
print("画像の合計 (asset):", cur.execute("select count(*) from asset").fetchone()[0])
print("root:", cur.execute("select path, allow_stage3 from root").fetchall())
con.close()
