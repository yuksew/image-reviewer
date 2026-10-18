"""実データを**読むだけ**で数える（`mode=ro`。1 バイトも書かない）。"""
import sqlite3

P = "C:/work/image-reviwer/.data/db.sqlite3"
con = sqlite3.connect(f"file:{P}?mode=ro", uri=True)
cur = con.cursor()

print("tables:", sorted(r[0] for r in cur.execute(
    "select name from sqlite_master where type='table'").fetchall()))
for table in ("asset", "asset_location", "deletion_log"):
    cols = [r[1] for r in cur.execute(f"pragma table_info({table})").fetchall()]
    print(f"{table} rows:", cur.execute(f"select count(*) from {table}").fetchone()[0])
    print(f"{table} columns:", cols)

print("asset.deleted_at not null:", cur.execute(
    "select count(*) from asset where deleted_at is not null").fetchone()[0])
print("asset_location.missing_at not null:", cur.execute(
    "select count(*) from asset_location where missing_at is not null").fetchone()[0])
print("deletion_log by stage:", cur.execute(
    "select stage, count(*) from deletion_log group by stage").fetchall())
print("deletion_log restored_at null:", cur.execute(
    "select count(*) from deletion_log where restored_at is null").fetchone()[0])
print("deletion_log sample (stage 1):", cur.execute(
    "select id, asset_id, stage, restored_at, hold_path, at from deletion_log"
    " where stage = 1 limit 3").fetchall())
con.close()
