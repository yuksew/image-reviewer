"""P8-0 の実データの作業（**控えを取ってから**）。

1. 控え: `.backup/pre-p8-0-<日時>/db.sqlite3`（`backup()` で WAL を畳む）
2. P7 の残骸を控えに複写してから消す（`<data>/workflows/` の中身・`<data>/recipes/` のフォルダ）
3. 実データを v6 に上げて、`illust-authoring` の置き場に `allow_stage3 = 1` を立てる
   （**利用者の回答 Q8**。262 / 263 枚がそこにある）

**アプリ（8790）は止めない**。加算的な変更だけで、v5 のコードでも v6 の DB はそのまま動く
（`migrate()` は `current >= SCHEMA_VERSION` で早期に戻る）。
"""

from __future__ import annotations

import datetime
import pathlib
import shutil
import sqlite3
import sys

sys.path.insert(0, r"C:\work\image-reviwer\src")
from image_reviewer import db

DATA = pathlib.Path(r"C:\work\image-reviwer\.data")
BACKUP_ROOT = pathlib.Path(r"C:\work\image-reviwer\.backup")
STAMP = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
BAK = BACKUP_ROOT / f"pre-p8-0-{STAMP}"


def main() -> int:
    BAK.mkdir(parents=True, exist_ok=True)
    print("控え:", BAK)

    # 1) DB の控え（WAL を畳む）
    src = sqlite3.connect(f"file:{DATA / 'db.sqlite3'}?mode=ro", uri=True)
    dst = sqlite3.connect(str(BAK / "db.sqlite3"))
    with dst:
        src.backup(dst)
    dst.close()
    src.close()
    print("  DB の控え:", (BAK / "db.sqlite3").stat().st_size, "バイト")

    # 2) P7 の残骸（**控えに複写してから消す**）
    left = BAK / "p7-leftovers"
    removed: list[tuple[str, int]] = []
    for name in ("workflows", "recipes"):
        target = DATA / name
        if not target.exists():
            continue
        for path in sorted(target.rglob("*")):
            if path.is_file():
                rel = path.relative_to(DATA)
                copy = left / rel
                copy.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(path, copy)
                removed.append((str(rel), path.stat().st_size))
        shutil.rmtree(target)
        print(f"  {name}/ を消した（控え: {left / name}）")
    for rel, size in removed:
        print(f"    消した: {rel}  {size} バイト")
    print(f"  合わせて {len(removed)} ファイル・{sum(s for _, s in removed)} バイト")

    # 3) 実データを v6 にして、印を立てる
    con = db.connect(DATA)
    try:
        before = con.execute("PRAGMA user_version").fetchone()[0]
        got = db.migrate(con)
        cols = {r["name"] for r in con.execute("PRAGMA table_info(root)")}
        if "allow_stage3" not in cols:                    # 念のため（v6 なら在る）
            raise SystemExit("allow_stage3 が無い（移行が効いていない）")
        roots = con.execute("SELECT path, display_path, allow_stage3 FROM root ORDER BY path").fetchall()
        print(f"  版: {before} → {got}")
        print("  置き場:")
        for row in roots:
            print(f"    {row['path']}  allow_stage3={row['allow_stage3']}")
        target = [r for r in roots if "illust-authoring" in (r["path"] or "").lower()]
        if len(target) != 1:
            raise SystemExit(f"illust-authoring の置き場が 1 つに定まらない: {[r['path'] for r in target]}")
        with con:
            con.execute("UPDATE root SET allow_stage3 = 1 WHERE path = ?", (target[0]["path"],))
        after = con.execute("SELECT allow_stage3 FROM root WHERE path = ?",
                            (target[0]["path"],)).fetchone()[0]
        print(f"  印を立てた: {target[0]['path']} → allow_stage3={after}")
        print("  他の置き場は既定のまま（0）:",
              [r["allow_stage3"] for r in roots if r["path"] != target[0]["path"]])
        print("  資産:", con.execute("SELECT count(*) FROM asset").fetchone()[0],
              "/ 判断:", con.execute("SELECT count(*) FROM decision").fetchone()[0],
              "/ FK 違反:", len(con.execute("PRAGMA foreign_key_check").fetchall()),
              "/ integrity:", con.execute("PRAGMA integrity_check").fetchone()[0])
    finally:
        con.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
