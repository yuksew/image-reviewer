"""使い捨て: 実データの複製を作る（`mode=ro` の `backup()` ＋ `copy2` ＋ パスの貼り替え）。

使い方: .venv\\Scripts\\python.exe -X utf8 .tmp-tray-recheck\\mk_replica.py <work の絶対パス>

`.tmp-tray-audit/mk_replica.py` と同じ `probe_deletions_advance.make_replica` を使うが、
置き場が `.tmp-tray-recheck` でも通るようにした物（あちらは `.tmp-tray-audit` だけを受け付ける）。
**作ったあと、全パス列が複製の外を指していないことを自分で確かめる。**
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, r"C:\work\image-reviwer\tools")
import probe_deletions_advance as p  # noqa: E402

work = Path(sys.argv[1]).resolve()
assert work.is_absolute() and ".tmp-tray-recheck" in str(work), work
if (work / "data" / "db.sqlite3").exists():
    print("もう在る:", work / "data")
    raise SystemExit(0)
got = p.make_replica(work, Path(r"C:\work\image-reviwer\.data"))
print(got)
con = sqlite3.connect(f"file:{(work / 'data' / 'db.sqlite3').as_posix()}?mode=ro", uri=True)
bad = 0
n = 0
for t, cols in (("root", ("path", "display_path")), ("asset_location", ("path", "display_path")),
                ("deletion_log", ("path", "from_path", "to_path", "hold_path")),
                ("location_history", ("path", "to_path"))):
    have = {r[1] for r in con.execute(f"PRAGMA table_info({t})")}
    for c in cols:
        if c not in have:
            continue
        for (v,) in con.execute(f"select {c} from {t} where {c} is not null"):
            n += 1
            if str(work).lower() not in str(v).lower():
                bad += 1
                print("外:", t, c, v)
print("path values", n, "outside", bad)
print("asset", con.execute("select count(*) from asset").fetchone()[0],
      "deletion_log", con.execute("select count(*) from deletion_log").fetchone()[0])
con.close()

