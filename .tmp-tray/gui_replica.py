"""gui_layout を回すための複製を作る（**実データは読むだけ**）。

- DB は `sqlite3.Connection.backup()` で作る（WAL を畳む。`cp` だと判断が抜ける）
- `sidecar/` / `export/` / `thumbs/` は写す（小さく、あると速い）
- **画像は写さない**（行が指しているパスをサーバが読むだけ。1 枚も動かさない）

使い方: .venv\\Scripts\\python.exe -X utf8 .tmp-tray\\gui_replica.py <複製のフォルダ>
"""
from __future__ import annotations

import shutil
import sqlite3
import sys
from pathlib import Path

REAL = Path(r"C:\work\image-reviwer\.data")
SMALL = ["sidecar", "export", "thumbs"]


def main() -> int:
    out = Path(sys.argv[1]).resolve()
    if REAL.resolve() in out.parents or out == REAL.resolve():
        print("断ります: 複製の場所が実データの中です", file=sys.stderr)
        return 2
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    src = sqlite3.connect(f"file:{REAL / 'db.sqlite3'}?mode=ro", uri=True)
    dst = sqlite3.connect(str(out / "db.sqlite3"))
    src.backup(dst)
    dst.close()
    src.close()
    for name in SMALL:
        got = REAL / name
        if got.is_dir():
            shutil.copytree(got, out / name)
    print(f"できた: {out}")
    con = sqlite3.connect(f"file:{out / 'db.sqlite3'}?mode=ro", uri=True)
    for table in ["asset", "asset_location", "decision", "deletion_log"]:
        print(" ", table, con.execute(f"select count(*) from {table}").fetchone()[0])
    print("  生きている枚:",
          con.execute("select count(*) from asset where deleted_at is null").fetchone()[0])
    con.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
