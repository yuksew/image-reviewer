import sqlite3
con = sqlite3.connect("file:C:/work/image-reviwer/.tmp-p8-5-entries/srv/db.sqlite3?mode=ro", uri=True)
cur = con.cursor()
for t in ("tag", "asset_tag", "tag_gloss", "duplicate_exclusion", "pending_delete_preview", "job"):
    print(t, cur.execute(f"select count(*) from {t}").fetchone()[0])
con.close()
