"""判断の理由マスタ（P5-1）。

設計: docs/p5-design.md §2.2・§3.3・§0.5（G4・G8）、docs/design.md §9.2

守ること:
- **builtin を id で決め打ちする**（`rc.keep.*` / `rc.reject.*`）。改名しても id は変えないので、
  過去の `decision.reason_code_id` が解決できなくならない
- 投入は**何度呼んでも安全**。`ON CONFLICT DO NOTHING` なので、利用者が付けた `label` を
  起動のたびに既定へ戻さない（表示はマスタを引く。点検 G8）
- **「まとまりごとボツ」用の既定理由は作らない**（点検 G4）。語彙は利用者のもので、
  「全部ボツ」は reject の一覧から選ばせる
- `applies_to` は `keep` / `reject` / `both`。判断の verdict と合わない理由は受け付けない（点検 C12）
"""

from __future__ import annotations

import sqlite3

# (id, label, applies_to)。**この並びが position**（0 から）。
# ボツの 8 つ＋「その他」は利用者の指定どおり（点検 G4。design.md §16.1 の 8 つと §9.2 の 9 つ）
BUILTINS: tuple[tuple[str, str, str], ...] = (
    ("rc.keep.as_intended", "意図どおり", "keep"),
    ("rc.keep.favorite", "気に入った", "keep"),
    ("rc.keep.finalize", "これで仕上げる", "keep"),
    ("rc.reject.people", "人数・人物が違う", "reject"),
    ("rc.reject.composition", "構図・アングルが違う", "reject"),
    ("rc.reject.intent", "意図・場面と違う", "reject"),
    ("rc.reject.mood", "雰囲気・絵柄が違う", "reject"),
    ("rc.reject.outfit", "服装・小物が違う", "reject"),
    ("rc.reject.character", "キャラが違う（別人化）", "reject"),
    ("rc.reject.breakdown", "破綻（体・関節・結合）", "reject"),
    ("rc.reject.expression", "表情が違う", "reject"),
    ("rc.reject.other", "その他", "reject"),
)

APPLIES_TO = ("keep", "reject", "both")

# 表示用の列（API と CLI が同じ順で返す）
COLUMNS = ("id", "label", "applies_to", "position", "builtin", "active")


def seed(con: sqlite3.Connection) -> int:
    """builtin を投入する。**既にある行は触らない**。入れた件数を返す。"""
    before = con.execute("SELECT count(*) AS n FROM reason_code").fetchone()["n"]
    con.executemany(
        "INSERT INTO reason_code(id, label, applies_to, position, builtin, active)"
        " VALUES (?,?,?,?,1,1) ON CONFLICT(id) DO NOTHING",
        [(rid, label, applies, i) for i, (rid, label, applies) in enumerate(BUILTINS)],
    )
    after = con.execute("SELECT count(*) AS n FROM reason_code").fetchone()["n"]
    return max(0, after - before)


def row(con: sqlite3.Connection, reason_code_id: str | None) -> sqlite3.Row | None:
    """1 件。無ければ None。"""
    if not reason_code_id:
        return None
    return con.execute(
        "SELECT id, label, applies_to, position, builtin, active FROM reason_code WHERE id = ?",
        (reason_code_id,),
    ).fetchone()


def label_of(con: sqlite3.Connection, reason_code_id: str | None) -> str | None:
    """表示用の label。**書き出し時点のマスタを引く**（点検 G8。焼き込まない）。"""
    got = row(con, reason_code_id)
    return got["label"] if got is not None else None


def matches_applies_to(applies_to: str, verdict: str) -> bool:
    """理由が verdict に使えるか（点検 C12）。`both` はどちらにも使える。"""
    return applies_to in (verdict, "both")


def list_all(con: sqlite3.Connection, *, applies_to: str | None = None,
             include_inactive: bool = False) -> list[dict]:
    """一覧。**position の順**（同じなら id）。`applies_to='keep'` は `both` も含める。"""
    sql = f"SELECT {', '.join(COLUMNS)} FROM reason_code WHERE 1 = 1"
    args: list = []
    if applies_to:
        sql += " AND applies_to IN (?, 'both')"
        args.append(applies_to)
    if not include_inactive:
        sql += " AND active = 1"
    sql += " ORDER BY position, id"
    return [dict(r) for r in con.execute(sql, args)]


def next_position(con: sqlite3.Connection) -> int:
    """利用者が足す理由の position（末尾）。"""
    return int(con.execute(
        "SELECT COALESCE(MAX(position), -1) + 1 AS n FROM reason_code").fetchone()["n"])
