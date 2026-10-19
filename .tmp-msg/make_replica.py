"""`gui_layout` 用の複製を作る（**実データは `mode=ro` で開くだけ。1 バイトも書かない**）。

使い捨て（`.tmp-msg/`）。DB は `sqlite3.backup()`（WAL の未畳み込み分も入る）、
画像はコピーしない（複製の DB は実データの画像を**読むだけ**）。`thumbs` / `sidecar` /
`export` / `store.json` は読むだけの派生物なので、複製に写して速くする。
"""

import shutil
import sqlite3
from pathlib import Path

REAL = Path(r"C:\work\image-reviwer\.data")
OUT = Path(r"C:\work\image-reviwer\.tmp-msg\replica")

OUT.mkdir(parents=True, exist_ok=True)
src = sqlite3.connect(f"file:{REAL / 'db.sqlite3'}?mode=ro", uri=True)
dst = sqlite3.connect(OUT / "db.sqlite3")
try:
    src.backup(dst)
    for table in ("asset", "asset_location", "deletion_log", "root", "tag"):
        print(table, dst.execute(f"SELECT count(*) FROM {table}").fetchone()[0])
finally:
    dst.close()
    src.close()

for name in ("thumbs", "sidecar", "export"):
    if (REAL / name).is_dir():
        shutil.copytree(REAL / name, OUT / name, dirs_exist_ok=True)
for name in ("store.json",):
    if (REAL / name).is_file():
        shutil.copy2(REAL / name, OUT / name)
print("複製:", OUT)
