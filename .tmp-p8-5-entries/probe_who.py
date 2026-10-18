"""台帳の actor / reason / request_id と、関連の表を見る（読むだけ）。"""
import sqlite3

P = "C:/work/image-reviwer/.data/db.sqlite3"
con = sqlite3.connect(f"file:{P}?mode=ro", uri=True)
cur = con.cursor()
print("actor 別:", cur.execute(
    "select actor, count(*) from deletion_log group by actor").fetchall())
print("reason 別:", cur.execute(
    "select reason, count(*) from deletion_log group by reason").fetchall())
print("request_id 別:", cur.execute(
    "select request_id, count(*) from deletion_log group by request_id").fetchall())
print("delete_request:", cur.execute("select count(*) from delete_request").fetchone()[0])
print("delete_request の列:", [r[1] for r in cur.execute(
    "pragma table_info(delete_request)").fetchall()])
print("delete_request の中身:", cur.execute(
    "select * from delete_request order by rowid desc limit 5").fetchall())
print("pending_delete_preview:", cur.execute(
    "select count(*) from pending_delete_preview").fetchone()[0])
print("asset.deleted_at の分布:", cur.execute(
    "select substr(deleted_at, 1, 16) as t, count(*) from asset"
    " where deleted_at is not null group by t order by t").fetchall())
con.close()
