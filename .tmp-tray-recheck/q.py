import sqlite3
c = sqlite3.connect('file:C:/work/image-reviwer/.data/db.sqlite3?mode=ro', uri=True)
print(len(c.execute('pragma table_info(deletion_log)').fetchall()), c.execute('select count(*) from deletion_log where closed_at is not null').fetchone())
print([t for (t,) in c.execute("select name from sqlite_master where sql like '%missing_at%'")])
