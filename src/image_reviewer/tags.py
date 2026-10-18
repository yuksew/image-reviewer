"""タグの読み書き（P4-1）。**契約の形を作る所と、人が付け外しする所。**

設計: docs/p4-design.md §3.4（取得）・§3.5〜§3.6・§4.3（出所）・§0.10（並びと丸め）・§0.14（Q3）

- **同じ語を出所ごとに 1 行**返す（`asset_tag` の主キーが `(asset_id, tag_id, source)`。§2.4）
- **並びは決定的**（§0.10）: `category`（**character 4 → general 0 → その他**）→ `score` の降順（NULL は最後）
  → `name` の昇順
- **手動の付け外しは `human` だけ**（§0.14 Q3）。検査は 1 か所（`require_human`）に置き、
  **後でエージェントにも許せる形**にする（`source='manual'` と `actor` は別の欄なので意味が壊れない）
- **点数は丸めない**（受け取った値をそのまま。§0.10）
"""

from __future__ import annotations

from typing import Any, Iterable, Sequence

from . import db
from .review import ReviewError

#: 契約の `Tag` に出す欄（`gloss` / `gloss_edited` は P4-2 で埋まる。**欄はもう返す**）
def contract_keys() -> tuple[str, ...]:
    return ("name", "category", "category_name", "score", "known", "source", "sources",
            "model", "actor", "tagged_at", "gloss", "gloss_edited")


def require_human(actor: str) -> None:
    """手動の付け外しは人だけ（§3.1・§0.14 Q3）。

    **1 か所に置く**: エージェントにも許すと決めたら、ここを外すだけで済む
    （`source='manual'` の行に `actor` が入っているので、後から見分けられる）。
    """
    if actor != "human":
        raise ReviewError(403, "タグの付け外しは人だけができます（エージェントは要求に書いてください）",
                          details={"actor": actor})


#: `category` の並び（**キャラ → 一般 → その他**。§0.10。CSV に artist / copyright が無い版がある）
_CATEGORY_RANK = "CASE t.category WHEN 4 THEN 0 WHEN 0 THEN 1 ELSE 2 END"


def tag_docs(con, asset_id: str) -> list[dict]:
    """1 枚のタグ（**契約の形**。§3.4）。**読むだけ**。"""
    rows = con.execute(
        f"SELECT t.id AS tag_id, t.name, t.category, t.category_name, t.known,"
        f" a.source, a.score, a.model, a.actor, a.tagged_at,"
        f" g.ja AS gloss, g.edited AS gloss_edited"
        f" FROM asset_tag a JOIN tag t ON t.id = a.tag_id"
        f" LEFT JOIN tag_gloss g ON g.tag_id = t.id"
        f" WHERE a.asset_id = ?"
        f" ORDER BY {_CATEGORY_RANK},"
        f" CASE WHEN a.score IS NULL THEN 1 ELSE 0 END, a.score DESC, t.name, a.source",
        (asset_id,)).fetchall()
    out: list[dict] = []
    by_name: dict[str, dict] = {}
    for row in rows:
        item = {
            # **`tag_id` を返す**（P4-3 の監査 A-2）: 画面が語を選んで「訳す」を押すとき、
            # 名前から `Number()` していたので **`NaN` → `tag_ids: []` → 422** になっていた。
            # 契約（`review.json` の `Tag`）には足さない（**API の応答だけ**）
            "tag_id": row["tag_id"],
            "name": row["name"],
            "category": row["category"],
            "category_name": row["category_name"],
            "score": row["score"],
            "known": bool(row["known"]),
            "source": row["source"],
            "sources": [row["source"]],
            "model": row["model"],
            "actor": row["actor"],
            "tagged_at": row["tagged_at"],
            "gloss": row["gloss"],
            "gloss_edited": bool(row["gloss_edited"]) if row["gloss_edited"] is not None else None,
        }
        # 同じ語が複数の出所にあるときは 1 行にまとめ、`sources` に全部入れる（§2.4）
        first = by_name.get(row["name"])
        if first is None:
            by_name[row["name"]] = item
            out.append(item)
        else:
            first["sources"].append(row["source"])
            # **`actor` を落とさない**（P4-1 の監査 C-5）。同じ語に `wd14` があると、並びの都合で
            # 先に来る `wd14` の行（`actor` は NULL）の値だけが残り、**誰が付けたかが消えていた**。
            # 出所ごとの `actor` は `sources` と 1 対 1 ではないので、**最初の非 NULL** を残す
            # （手動の行は必ず `actor` を持つ。契約に欄を足すかは親の判断待ち）
            if first.get("actor") is None and row["actor"] is not None:
                first["actor"] = row["actor"]
            if not first.get("gloss") and row["gloss"]:
                first["gloss"] = row["gloss"]
    return out


def load_csv(con):
    """語彙（CSV）を読む。**読めなければ `None`**（P4-1 の監査 C-4 で使う）。"""
    from . import tagger

    try:
        settings = tagger.settings_of(con)
        path = tagger.find_csv(settings.get("csv_path"))
        return tagger.read_csv(path) if path is not None else None
    except Exception:                                    # noqa: BLE001  語彙が無くても付け外しは動く
        return None


def ensure_tag(con, name: str | None, *, csv=None):
    """語の行を確保する（P4-1 の監査 C-4）。

    以前は `tag` 表にある語しか付けられず、**CSV の語彙にある語でも 404** だった
    （実測: `tail` → 404。文言は「語彙にありません」だが実際は「表に無い」）。
    人が**語彙にある語を新しく付けられる**ように、無ければ行を作る（`known=1` を導出値で入れる）。
    **語彙にも無い語は作らない**（勝手に語彙を増やさない。`design.md` §16.1 と同じ趣旨）。
    """
    from .tagger import normalize_name

    key = normalize_name(name or "")
    if not key:
        return None
    row = con.execute("SELECT * FROM tag WHERE name = ?", (key,)).fetchone()
    if row is not None:
        return row
    if csv is None or not csv.known(key):
        return None
    category, category_name = csv.category_of(key)
    con.execute(
        "INSERT INTO tag(name, category, category_name, known) VALUES (?,?,?,1)"
        " ON CONFLICT(name) DO UPDATE SET known = max(tag.known, excluded.known),"
        " category = COALESCE(tag.category, excluded.category),"
        " category_name = COALESCE(tag.category_name, excluded.category_name)",
        (key, category, category_name))
    return con.execute("SELECT * FROM tag WHERE name = ?", (key,)).fetchone()


def list_tags(con, *, q: str | None = None, category: int | None = None,
              source: str | None = None, known: str = "1", limit: int = 200,
              cursor: str | None = None) -> dict:
    """語の一覧（`GET /api/tags`。§3.6 の隣）。

    - **既定は `known='1'` だけ**（点検 §I-2）。実データでは件数の上位 4 語が全部 `known=0` の品質語
      （`masterpiece` / `best_quality` / `safe` / `score_7`）で、**上位 50 のうち 25 語が `known=0`**。
      絞らないと語の一覧が品質語で埋まる。`known=0` / `known=all` で切り替えられる
    - `q` は**前方一致**（`LIKE 'q%'`。§3.6）。件数（使用数）の多い順 → `name`
    - **頁送りは並びと同じ鍵**（`uses DESC, name ASC`）で行う（P4-3 の再確認 B-1）。前の版は
      **`name` だけ**を鍵にしていたので、2 頁目が「`name` が cursor より後の語を使用数順に 200 語」になり、
      **1 頁目と 183 語が重複**して続きに届かなかった（実測: 1+2 頁で 630 語のうち 413 語に届かない）。
      `cursor` は `uses|name` の形（`|` は語に現れない）。**`total` は cursor を含めない**（絞り込み全体の数）
    """
    if known not in ("0", "1", "all"):
        raise ReviewError(422, "known は 1 | 0 | all です", details={"known": "1 | 0 | all"})
    where = ["1 = 1"]
    args: list[Any] = []
    if known != "all":
        where.append("t.known = ?")
        args.append(int(known))
    if q:
        where.append("t.name LIKE ?")
        args.append(str(q).lower().replace(" ", "_") + "%")
    if category is not None:
        where.append("t.category = ?")
        args.append(int(category))
    if source:
        where.append("EXISTS (SELECT 1 FROM asset_tag a2 WHERE a2.tag_id = t.id AND a2.source = ?)")
        args.append(source)
    size = max(1, min(int(limit or 200), 1000))
    # --- 頁送り（`uses|name`。**並びと同じ鍵**）---
    after: tuple[int, str] | None = None
    if cursor:
        pair = str(cursor).split("|", 1)
        if len(pair) != 2 or not pair[0].lstrip("-").isdigit():
            raise ReviewError(422, "cursor が不正です", details={"cursor": str(cursor)})
        after = (int(pair[0]), pair[1])
    tail = ""
    tail_args: list[Any] = []
    if after is not None:
        tail = " WHERE uses < ? OR (uses = ? AND name > ?)"
        tail_args = [after[0], after[0], after[1]]
    rows = con.execute(
        f"SELECT * FROM ("
        f" SELECT t.id, t.name, t.category, t.category_name, t.known,"
        f"  (SELECT count(*) FROM asset_tag a WHERE a.tag_id = t.id) AS uses,"
        f"  (SELECT count(DISTINCT a.asset_id) FROM asset_tag a WHERE a.tag_id = t.id) AS assets,"
        f"  g.ja AS gloss, g.edited AS gloss_edited"
        f"  FROM tag t LEFT JOIN tag_gloss g ON g.tag_id = t.id"
        f"  WHERE {' AND '.join(where)}"
        f"){tail}"
        f" ORDER BY uses DESC, name LIMIT ?",
        [*args, *tail_args, size]).fetchall()
    items = [{
        "tag_id": row["id"], "name": row["name"], "category": row["category"],
        "category_name": row["category_name"], "known": bool(row["known"]),
        "uses": int(row["uses"]), "assets": int(row["assets"]),
        "gloss": row["gloss"],
        "gloss_edited": bool(row["gloss_edited"]) if row["gloss_edited"] is not None else None,
    } for row in rows]
    # **`total` は絞り込み全体の数**（cursor で減らさない。P4-3 の再確認 B-1）
    total = con.execute(
        f"SELECT count(*) AS n FROM tag t WHERE {' AND '.join(where)}", args).fetchone()["n"]
    counts = {"known": con.execute("SELECT count(*) AS n FROM tag WHERE known = 1").fetchone()["n"],
              "unknown": con.execute("SELECT count(*) AS n FROM tag WHERE known = 0").fetchone()["n"]}
    return {"items": items, "total": int(total), "counts": counts,
            "next_cursor": f"{items[-1]['uses']}|{items[-1]['name']}" if len(items) == size else None}


def resolve_tag(con, *, name: str | None = None, tag_id: int | None = None):
    """語の行を引く（名前か id）。無ければ `None`。"""
    if tag_id is not None:
        return con.execute("SELECT * FROM tag WHERE id = ?", (int(tag_id),)).fetchone()
    if name:
        from .tagger import normalize_name

        return con.execute("SELECT * FROM tag WHERE name = ?",
                           (normalize_name(name),)).fetchone()
    return None


def add_manual(con, asset_id: str, tag_row, actor: str) -> bool:
    """人が 1 語を付ける（§3.1）。**冪等**（同じ語を 2 回でも行は 1 つ）。付いたら `True`。"""
    got = con.execute(
        "INSERT INTO asset_tag(asset_id, tag_id, score, source, model, actor, tagged_at)"
        " VALUES (?,?,NULL,'manual',NULL,?,?)"
        " ON CONFLICT(asset_id, tag_id, source) DO NOTHING",
        (asset_id, int(tag_row["id"]), actor, db.stamp()))
    return bool(got.rowcount)


def remove_manual(con, asset_id: str, tag_row) -> bool:
    """人が付けた 1 語を外す（**`manual` の行だけ**。§3.1）。2 回目は `False`（呼ぶ側が 404 にする）。"""
    got = con.execute(
        "DELETE FROM asset_tag WHERE asset_id = ? AND tag_id = ? AND source = 'manual'",
        (asset_id, int(tag_row["id"])))
    return bool(got.rowcount)
