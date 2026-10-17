"""`gui_layout.mjs` の**前提の行**を、複製の中に自分で用意する（P8-3 の監査 D-6）。

なぜ要るか（監査 D-6）:
    `--screen tags` は**語の行**、`--screen duplicates` は**理由が `<script>…` の除外**、
    `--screen pending` は**段 3 の保留**が無いと NG になっていた。素の複製では 3 窓とも落ち、
    「実装者が手で作った前提」が検査の前提になっていた（＝複製を作り直すたびに落ちる）。
    ここで**複製の中に**その行を作れるようにする（実装者も監査も同じ手順を使える）。

**実データには絶対に書かない**（`--data` が `C:\\work\\image-reviwer\\.data` なら断る）。
**画像を動かさない**（段 3 の保留は**複製**を作って置く。元の場所のファイルは触らない）。

使い方:
    uv run --no-sync python -X utf8 tools/gui_layout_seed.py --data <複製のフォルダ> --tags
    uv run --no-sync python -X utf8 tools/gui_layout_seed.py --data <複製のフォルダ> \\
        --tags --exclusion --pending

`--tags`      語を 3 つ（語釈つき 2 つ）と、最初の 2 枚への結び付けを入れる（`#/tags` 用）
`--exclusion` いちばん近い群の 2 枚に、理由が `<script>alert(1)</script>` の除外を入れる
`--pending`   1 枚を段 3 の保留にする（**保留の実体は複製**。残り時間 300 秒）
"""

from __future__ import annotations

import argparse
import shutil
import sqlite3
import sys
import time
from pathlib import Path

#: **触ってはいけない置き場**（実データ）
REAL_DATA = Path(r"C:\work\image-reviwer\.data")
HOLD_DIR = "pending-delete"


def guard(data: Path) -> Path:
    """実データ（と、その親）を断る（**書き込む前に**）。"""
    got = data.resolve()
    if got == REAL_DATA.resolve() or REAL_DATA.resolve() in got.parents:
        print(f"断ります: {got} は実データ（{REAL_DATA}）の中です。"
              "複製のフォルダを --data に渡してください（監査 §0）", file=sys.stderr)
        raise SystemExit(2)
    if not (got / "db.sqlite3").exists():
        print(f"断ります: {got / 'db.sqlite3'} がありません", file=sys.stderr)
        raise SystemExit(2)
    return got


def connect(data: Path) -> sqlite3.Connection:
    con = sqlite3.connect(data / "db.sqlite3")
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    return con


def seed_tags(con: sqlite3.Connection) -> None:
    """語と語釈（`#/tags` の行が出るように）。**最初の 2 枚**に結び付ける。"""
    assets = [row["id"] for row in con.execute("SELECT id FROM asset ORDER BY id LIMIT 2")]
    if not assets:
        print("注意: 画像が 0 枚なので語は入れません")
        return
    words = [("1girl", 0, "女の子 1 人", "textgenerate"), ("long_hair", 0, "長い髪", "textgenerate"),
             ("solo", 4, None, None)]
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    for name, category, ja, source in words:
        con.execute("INSERT OR IGNORE INTO tag(name, category, category_name, known)"
                    " VALUES (?,?,?,1)", (name, category, "general"))
        tag_id = con.execute("SELECT id FROM tag WHERE name = ?", (name,)).fetchone()["id"]
        if ja:
            con.execute("INSERT OR REPLACE INTO tag_gloss(tag_id, ja, source, engine, edited,"
                        " created_at, updated_at) VALUES (?,?,?,'seed',0,?,?)",
                        (tag_id, ja, source, now, now))
        for asset_id in assets:
            con.execute("INSERT OR REPLACE INTO asset_tag(asset_id, tag_id, score, source, model,"
                        " actor, tagged_at) VALUES (?,?,?,?,NULL,'human',?)",
                        (asset_id, tag_id, 0.9, "manual", now))
    print(f"語: {len(words)} 語を入れ、{len(assets)} 枚に結び付けた")


def seed_exclusion(con: sqlite3.Connection) -> None:
    """いちばん近い群の 2 枚に、**理由が `<script>alert(1)</script>` の除外**を入れる。

    `--screen duplicates` は「除外の理由を**文字として**出す」ことを見る（§8.2-7）。
    **サーバが動いていると `Store` が書けない**（`database is locked`）ので、そのときは
    台帳の `phash` から 2 枚を選ぶ（**画面の検査には十分**。複製なので害が無い）。
    """
    pair = None
    try:
        from image_reviewer.duplicates import DuplicatesService
        from image_reviewer.store import Store

        data = Path(con.execute("PRAGMA database_list").fetchone()[2]).parent
        store = Store(data)
        try:
            got = DuplicatesService(store).near(max_distance=6)
            for group in got.get("groups", []):
                ids = [item["id"] for item in group.get("items", [])]
                if len(ids) >= 2:
                    pair = sorted(ids[:2])
                    break
        finally:
            store.close()                                  # **接続を残さない**
    except Exception as exc:                               # 表が古い・錠・phash が無い等
        print(f"注意: 群を引けませんでした（{exc}）。phash のある 2 枚で代用します")
    if pair is None:
        pair = sorted(row["id"] for row in con.execute(
            "SELECT id FROM asset WHERE phash IS NOT NULL ORDER BY id LIMIT 2"))
    if len(pair) < 2:
        print("注意: 2 枚そろわないので除外は入れません")
        return
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    con.execute("INSERT OR REPLACE INTO duplicate_exclusion(a_id, b_id, reason, actor, at)"
                " VALUES (?,?,?, 'human', ?)",
                (pair[0], pair[1], "<script>alert(1)</script>", now))
    print(f"除外: {pair[0][:8]} / {pair[1][:8]} を「別物として確定」にした（理由は script タグ）")


def seed_pending(con: sqlite3.Connection, data: Path) -> None:
    """1 枚を**段 3 の保留**にする（**保留の実体は複製**。元の場所のファイルは触らない）。

    台帳の行だけを入れ、**ファイルは動かさない**（`_state_of` は `purge_at` が入っていれば
    `pending` を返すので、画面は残り時間つきの行として出す）。
    """
    row = con.execute("SELECT l.asset_id, l.path, l.display_path, l.size FROM asset_location l"
                      " WHERE l.missing_at IS NULL ORDER BY l.path LIMIT 1").fetchone()
    if row is None:
        print("注意: 登録が 0 件なので保留は入れません")
        return
    src = Path(row["display_path"] or row["path"])
    deletion_id = f"seed-{int(time.time())}"
    hold = data / HOLD_DIR / deletion_id
    hold.mkdir(parents=True, exist_ok=True)
    target = hold / src.name
    if src.exists():
        shutil.copy2(src, target)                          # **複製**（元のファイルは動かさない）
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    con.execute(
        "INSERT OR REPLACE INTO deletion_log(id, asset_id, path, stage, from_path, to_path,"
        " hold_path, remaining_sec, purge_at, size, reason, actor, at)"
        " VALUES (?,?,?,3,?,NULL,?,300,?,?, '画面の検査の前提', 'human', ?)",
        (deletion_id, row["asset_id"], row["path"], str(src), str(target),
         time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() + 300)),
         int(row["size"] or 0), now))
    print(f"保留: {deletion_id} を段 3 にした（残り 300 秒。実体は {target}）")


def main() -> None:
    parser = argparse.ArgumentParser(description="gui_layout の前提を複製に用意する（P8-3 の監査 D-6）")
    parser.add_argument("--data", required=True, help="複製のフォルダ（実データは断る）")
    parser.add_argument("--tags", action="store_true", help="語と語釈（--screen tags 用）")
    parser.add_argument("--exclusion", action="store_true", help="script タグの理由の除外")
    parser.add_argument("--pending", action="store_true", help="段 3 の保留（--screen pending 用）")
    args = parser.parse_args()
    data = guard(Path(args.data))
    con = connect(data)
    try:
        if args.tags:
            seed_tags(con)
        if args.exclusion:
            seed_exclusion(con)
        if args.pending:
            seed_pending(con, data)
        con.commit()
        print(f"入れた: {data}")
    finally:
        con.close()


if __name__ == "__main__":
    main()
