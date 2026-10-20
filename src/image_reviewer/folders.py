"""仮想フォルダ（カタログ）のサービス（P2-1）。

設計: `docs/design.md` **§5.3**（表 `folder` / `folder_member`）・**§6.1**（口 8 本）・
**§10.1**（多対多。**実ファイルは動かさない**）・**§10.2**（スマートフォルダ）・
**§16.9**（P2-0 の決定。**G-2 (b) 同じ親の中で名前は一意**・**C-2 名前の取り合い**）。

決めたこと（記録は `docs/p2-1-implementation.md`）:

- **1 枚は複数のフォルダに入れる**（`folder_member` の多対多。§10.1）。**画像の行は 1 つも消さない・
  実ファイルは 1 バイトも動かさない**。外すのは `folder_member` の 1 行だけ。
- **同じ親の中で名前は一意**（`ux_folder_name` の部分一意索引）。**別の親の下の同名は通る**。
  表の索引は最後の砦で、**読める文にするのはここ**（422 `folder_name_taken`）。
- **フォルダの削除は既定で論理削除**（`folder.deleted_at`。§6.1）。**子も一緒に**隠す（親だけ隠すと
  木から子が消えて見えなくなる）。**`folder_member` は 1 行も消さない**（`deleted_at` の印だけ）。
  **消えるのは `purge` のときだけ**（CASCADE）。隠したフォルダの中身は木にも件数にも中身にも出ないが、
  **行は残る**ので、戻せば見える——仮想フォルダは**再生成できない分類**なので、消したら戻せない形に
  しない（P2-1 の監査 B-1。前は隠すたびに `DELETE` していて、所属が永久に消えていた）。
  **画像は 1 枚も消さない**（`asset` も `asset_location` も触らない）。実削除は `purge=true` のときだけ。
- **`deleted_at IS NOT NULL` の画像はカタログに出さない**（片付け済みの枚を出さない）。
- **件数は毎回数える**（`count_cache` は使わない）。**正しさ優先**——`count_cache` の無効化の規則が
  設計に無く（§10.2 は「走査・タグ付け・判断のあと」しか言わない）、`folder_member` の増減で
  いつ無効にするかが決まっていない。**`GET` は 1 バイトも書かない**（家風）ので、`GET` で
  キャッシュを埋めることもできない。件数は `folder_member` × `asset` の `count(*)` で、
  実データ（463 枚）の規模では 1 ミリ秒未満（記録に実測を書く）。
- **スマートフォルダは作れる・条件は検証する**が、**条件での絞り込みはまだ計算しない**（P2-2 以降）。
  中身は手で入れた `folder_member`（普通は空）。`GET /api/folders/{id}/assets` が
  `smart: true` と 1 行の注記を返す（**黙って空にしない**）。
- **並びは `position` の昇順、同じなら名前**（§5.3 の `position`）。
"""

from __future__ import annotations

import json
import sqlite3
import unicodedata

from . import db
from .review import ReviewError
from .store import Store

#: フォルダの種別（`folder.kind` の `CHECK` と同じ語彙。§5.3）
KINDS = ("manual", "smart")

#: 名前の上限。**設計に数字が無い**ので決めた（画面の 1 行に入る長さ。`docs/p2-1-implementation.md`）
MAX_NAME = 120

#: 1 回の口で受ける枚数の上限（`deletions` の 200 件と同じ流儀で、重すぎる要求を断る）
MAX_MEMBERS = 1000

#: `GET /api/folders/{id}/assets` の並び
SORTS = ("position", "added", "name")

#: §10.2 の `smart_query` で使えるフィールド（**列挙**。生の SQL は受けない）。
#: **P2-1 では検証だけ**（条件での絞り込みは P2-2 以降。§10.2）
SMART_FIELDS = ("tag", "folder", "review_state", "reason_code", "source",
                "meta.model", "meta.seed", "meta.steps", "meta.cfg",
                "width", "height", "added_at", "seen_at")

#: `smart_query` の条件 1 つに使える演算（`not` は別の欄）
SMART_OPS = ("has", "in", "eq", "gte", "lte")


# ---- 小さな道具 ----


def _now() -> str:
    return db.now()


def _row(con: sqlite3.Connection, folder_id: str, *, allow_deleted: bool = False):
    """1 行。無い（か、隠れている）なら **404**。

    `allow_deleted` は「隠れている物も見る」道（今は無い。将来の「戻す」用に残す）。
    """
    row = con.execute("SELECT * FROM folder WHERE id = ?", (folder_id,)).fetchone()
    if row is None:
        raise ReviewError(404, "フォルダがありません", details={"folder_id": folder_id})
    if not allow_deleted and row["deleted_at"] is not None:
        raise ReviewError(404, "フォルダがありません（削除しました）",
                          details={"folder_id": folder_id})
    return row


def _clean_name(value) -> str:
    """名前を整える。**空・長すぎ・制御文字・見えない文字は 422**（画面の 1 行に入らない名前を作らせない）。

    正規化は **NFC**（P2-1 の監査 C-5・G-3 (a)）。`ガ`（NFC）と `ガ`（NFD）が**別の名前として
    同じ親に 2 つ並ぶ**のを防ぐ（見た目が同じで区別できない）。**大文字小文字は区別する**
    （`Cat` と `cat` は別。Windows のフォルダと違うが、仮想フォルダなので区別してよい）。
    見えない文字は `unicodedata.category` で拒む（`Cc` 制御・`Cf` 書式・`Zl`/`Zp` 行区切り。
    幅 0 の空白・DEL・行区切りで「同じに見える別名」を作らせない）。
    """
    if not isinstance(value, str):
        raise ReviewError(422, "name は文字列で指定してください",
                          details={"name": "1〜" + str(MAX_NAME) + " 文字"})
    name = unicodedata.normalize("NFC", value.strip())
    if not name:
        raise ReviewError(422, "フォルダ名を入れてください",
                          details={"name": "1〜" + str(MAX_NAME) + " 文字"})
    if len(name) > MAX_NAME:
        raise ReviewError(422, f"フォルダ名は {MAX_NAME} 文字までです",
                          details={"name": f"{MAX_NAME} 文字まで", "length": len(name)})
    if any(unicodedata.category(ch) in ("Cc", "Cf", "Zl", "Zp") for ch in name):
        raise ReviewError(422, "フォルダ名に改行や見えない文字は使えません",
                          details={"name": "制御文字・見えない文字を使わない"})
    return name


def _assert_unique(con: sqlite3.Connection, parent_id: str | None, name: str,
                   *, exclude: str | None = None) -> None:
    """**同じ親の中で名前は一意**（§16.9 の G-2 (b)）。**別の親なら同名でよい**。

    根（`parent_id IS NULL`）も 1 つの親として数える（`ux_folder_name` の `coalesce` と同じ）。
    `exclude` は「名前を変えない更新」で自分を除くため。
    """
    sql = ("SELECT id FROM folder WHERE deleted_at IS NULL AND name = ?"
           " AND coalesce(parent_id, '') = coalesce(?, '')")
    args: list = [name, parent_id]
    if exclude is not None:
        sql += " AND id <> ?"
        args.append(exclude)
    if con.execute(sql, args).fetchone() is not None:
        raise ReviewError(422, f"同じ親の下に「{name}」があります（別の名前を付けてください）",
                          code="folder_name_taken",
                          details={"name": name, "parent_id": parent_id})


def _subtree(con: sqlite3.Connection, folder_id: str) -> list[str]:
    """そのフォルダと**生きている子孫**の id（深さ優先の前順）。**読むだけ**。"""
    rows = con.execute(
        "WITH RECURSIVE sub(id) AS ("
        "  SELECT id FROM folder WHERE id = ? AND deleted_at IS NULL"
        "  UNION ALL"
        "  SELECT f.id FROM folder f JOIN sub ON f.parent_id = sub.id"
        "  WHERE f.deleted_at IS NULL)"
        " SELECT id FROM sub", (folder_id,)).fetchall()
    return [row["id"] for row in rows]


def _depth_of(con: sqlite3.Connection, parent_id: str | None) -> int:
    """親の深さ（根は 0）。**循環していても止まる**ように 64 回で打ち切る。"""
    depth = 0
    seen: set[str] = set()
    current = parent_id
    while current is not None and depth < 64:
        if current in seen:                      # 壊れた DB でも無限に回らない
            raise ReviewError(422, "フォルダの親が循環しています",
                              code="folder_cycle", details={"parent_id": parent_id})
        seen.add(current)
        row = con.execute("SELECT parent_id FROM folder WHERE id = ?", (current,)).fetchone()
        if row is None:
            break
        current = row["parent_id"]
        depth += 1
    return depth


def _height_of(con: sqlite3.Connection, folder_id: str) -> int:
    """そのフォルダから下の**最大の段数**（自分だけなら 1）。**循環していても止まる**（64 で打ち切る）。

    「移す」は**枝ごと**動くので、親の深さだけでは足りない（P2-1 の監査 D-7。31 段目の下へ
    3 段の枝を移すと 34 段になった）。
    """
    row = con.execute(
        "WITH RECURSIVE sub(id, depth) AS ("
        "  SELECT id, 1 FROM folder WHERE id = ?"
        "  UNION ALL"
        "  SELECT f.id, sub.depth + 1 FROM folder f JOIN sub ON f.parent_id = sub.id"
        "  WHERE sub.depth < 64)"
        " SELECT max(depth) AS n FROM sub", (folder_id,)).fetchone()
    return int(row["n"] or 1)


def _parent_or_422(con: sqlite3.Connection, parent_id) -> str | None:
    """親の検査（**存在しない親・隠れた親は 422**。`null` は根）。"""
    if parent_id is None or parent_id == "":
        return None
    if not isinstance(parent_id, str):
        raise ReviewError(422, "parent_id は文字列か null です",
                          details={"parent_id": "フォルダの id か null"})
    row = con.execute("SELECT id, deleted_at FROM folder WHERE id = ?", (parent_id,)).fetchone()
    if row is None or row["deleted_at"] is not None:
        raise ReviewError(422, "親のフォルダがありません（消したフォルダの下には作れません）",
                          code="parent_missing", details={"parent_id": parent_id})
    return parent_id


def _next_position(con: sqlite3.Connection, parent_id: str | None) -> int:
    row = con.execute(
        "SELECT COALESCE(MAX(position), -1) + 1 AS n FROM folder"
        " WHERE deleted_at IS NULL AND coalesce(parent_id, '') = coalesce(?, '')",
        (parent_id,)).fetchone()
    return int(row["n"])


def _smart_query_of(con: sqlite3.Connection, kind: str, raw) -> str | None:
    """`smart_query` を**列挙で検査**して JSON の文字列にする（生の SQL は受け付けない。§10.2）。

    `kind='manual'` なら `None`（条件を持たせない）。`kind='smart'` なら**必須**。
    形は `{"all": [{"field","op","value","not"?}, ...]}`。**P2-1 では検証だけ**で、
    条件での絞り込みはまだ計算しない（`docs/p2-1-implementation.md` の申し送り）。
    """
    if kind != "smart":
        if raw not in (None, "", {}):
            raise ReviewError(422, "条件（smart_query）はスマートフォルダだけに付けられます",
                              code="smart_query_not_allowed")
        return None
    if raw is None:
        raise ReviewError(422, "スマートフォルダには条件（smart_query）が要ります",
                          code="smart_query_required")
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except ValueError as exc:
            raise ReviewError(422, "条件（smart_query）が JSON として読めません",
                              code="smart_query_bad", details={"error": str(exc)}) from exc
    if not isinstance(raw, dict):
        raise ReviewError(422, "条件（smart_query）はオブジェクトです", code="smart_query_bad")
    extra = set(raw) - {"all"}
    if extra:
        raise ReviewError(422, "条件（smart_query）に知らない欄があります",
                          code="smart_query_bad", details={"unknown": sorted(extra)})
    items = raw.get("all")
    if not isinstance(items, list) or not items:
        raise ReviewError(422, "条件（smart_query）の all は 1 つ以上の配列です",
                          code="smart_query_bad")
    checked: list[dict] = []
    for at, item in enumerate(items, start=1):
        if not isinstance(item, dict):
            raise ReviewError(422, f"条件の {at} 番目がオブジェクトではありません",
                              code="smart_query_bad", details={"at": at})
        field = item.get("field")
        if field not in SMART_FIELDS:
            raise ReviewError(422, f"条件の {at} 番目の field が語彙の外です",
                              code="smart_query_bad",
                              details={"at": at, "field": field,
                                       "allowed": list(SMART_FIELDS)})
        op = item.get("op")
        if op not in SMART_OPS:
            raise ReviewError(422, f"条件の {at} 番目の op が語彙の外です",
                              code="smart_query_bad",
                              details={"at": at, "op": op, "allowed": list(SMART_OPS)})
        if "value" not in item:
            raise ReviewError(422, f"条件の {at} 番目に value がありません",
                              code="smart_query_bad", details={"at": at})
        clean = {"field": field, "op": op, "value": item.get("value")}
        if item.get("not") is not None:
            if not isinstance(item["not"], bool):
                raise ReviewError(422, f"条件の {at} 番目の not は真偽値です",
                                  code="smart_query_bad", details={"at": at})
            clean["not"] = item["not"]
        checked.append(clean)
    return json.dumps({"all": checked}, ensure_ascii=False)


def _folder_dict(row, *, count: int, children: list[dict] | None = None) -> dict:
    """1 つのフォルダの形（木の節と単体で同じ欄）。"""
    out = {
        "id": row["id"],
        "parent_id": row["parent_id"],
        "name": row["name"],
        "kind": row["kind"],
        "smart_query": row["smart_query"],
        "position": row["position"],
        "created_at": row["created_at"],
        #: **生きた画像の枚数**（`deleted_at IS NULL` だけ。片付け済みは数えない）
        "count": count,
    }
    if children is not None:
        out["children"] = children
    return out


def _count_of(con: sqlite3.Connection, folder_id: str) -> int:
    """そのフォルダの**生きた画像の枚数**（毎回数える。`count_cache` は使わない）。

    **親（フォルダ）が生きている行だけ**を数える（隠したフォルダの `folder_member` は残るので、
    ここで `folder.deleted_at IS NULL` を見ないと、隠したはずの所属を数えてしまう。監査 B-1）。
    """
    row = con.execute(
        "SELECT count(*) AS n FROM folder_member m"
        " JOIN folder f ON f.id = m.folder_id AND f.deleted_at IS NULL"
        " JOIN asset a ON a.id = m.asset_id"
        " WHERE m.folder_id = ? AND a.deleted_at IS NULL", (folder_id,)).fetchone()
    return int(row["n"])


# ---- 読む（`GET` は 1 バイトも書かない）----


def tree(con: sqlite3.Connection) -> dict:
    """**木の形**（§6.1）。`kind` と**生きた画像の枚数**つき。**書かない**。

    並びは `position`、同じなら名前。隠れたフォルダ（`deleted_at`）と、その子孫は出さない。
    **件数も生きたフォルダの行だけ**を数える（隠したフォルダの `folder_member` は残る。監査 B-1）。
    """
    rows = con.execute(
        "SELECT * FROM folder WHERE deleted_at IS NULL"
        " ORDER BY coalesce(parent_id, ''), position, name, id").fetchall()
    counts = {row["folder_id"]: int(row["n"]) for row in con.execute(
        "SELECT m.folder_id, count(*) AS n FROM folder_member m"
        " JOIN folder f ON f.id = m.folder_id AND f.deleted_at IS NULL"
        " JOIN asset a ON a.id = m.asset_id WHERE a.deleted_at IS NULL"
        " GROUP BY m.folder_id")}
    nodes: dict[str, dict] = {}
    for row in rows:
        nodes[row["id"]] = _folder_dict(row, count=counts.get(row["id"], 0), children=[])
    items: list[dict] = []
    for row in rows:
        node = nodes[row["id"]]
        parent = nodes.get(row["parent_id"]) if row["parent_id"] else None
        if parent is None:
            items.append(node)                   # 根（親が隠れている子も根として出す）
        else:
            parent["children"].append(node)
    return {"items": items, "total": len(rows),
            "counts_note": "枚数は今の登録から数えています（片付け済みの画像は数えません）"}


def assets(con: sqlite3.Connection, folder_id: str, *, cursor: int = 0, limit: int = 200,
           sort: str = "position") -> dict:
    """**中身の一覧**（§6.1）。**生きた画像だけ**。**書かない**。

    `sort` は `position`（既定。`folder_member.position`）/ `added`（`added_at` の新しい順）/
    `name`（表示パス）。**`cursor` は先頭からの件数**（`GET /api/assets` と同じ流儀）。
    設計 §10.3 はキーセット改ページと言うが、**この段は既存の一覧に揃えた**（申し送り）。
    """
    row = _row(con, folder_id)
    if sort not in SORTS:
        raise ReviewError(422, f"sort は {' / '.join(SORTS)} のいずれかです",
                          details={"sort": sort})
    limit = max(1, min(int(limit or 200), 1000))
    cursor = max(0, int(cursor or 0))
    order = {
        "position": "m.position, m.added_at, a.id",
        "added": "m.added_at DESC, a.id",
        "name": "path, a.id",
    }[sort]
    base = (
        "SELECT a.id, a.sha256, a.kind, a.width, a.height, a.format, a.review_state,"
        " a.deleted_at, m.position, m.added_at,"
        " (SELECT l.display_path FROM asset_location l WHERE l.asset_id = a.id"
        "  ORDER BY l.is_primary DESC, l.display_path LIMIT 1) AS path,"
        " (SELECT l.size FROM asset_location l WHERE l.asset_id = a.id"
        "  ORDER BY l.is_primary DESC, l.display_path LIMIT 1) AS size,"
        " (SELECT count(*) FROM asset_meta x WHERE x.asset_id = a.id) AS has_meta,"
        " (SELECT x.meta_json FROM asset_meta x WHERE x.asset_id = a.id) AS meta_json"
        " FROM folder_member m"
        " JOIN folder f ON f.id = m.folder_id AND f.deleted_at IS NULL"
        " JOIN asset a ON a.id = m.asset_id"
        " WHERE m.folder_id = ? AND a.deleted_at IS NULL")
    total = con.execute(
        "SELECT count(*) AS n FROM folder_member m"
        " JOIN folder f ON f.id = m.folder_id AND f.deleted_at IS NULL"
        " JOIN asset a ON a.id = m.asset_id"
        " WHERE m.folder_id = ? AND a.deleted_at IS NULL", (folder_id,)).fetchone()["n"]
    rows = con.execute(f"{base} ORDER BY {order} LIMIT ? OFFSET ?",
                       (folder_id, limit, cursor)).fetchall()
    items = []
    for got in rows:
        meta = None
        if got["meta_json"]:
            try:
                parsed = json.loads(got["meta_json"])
                meta = parsed if isinstance(parsed, dict) else None
            except ValueError:
                meta = None
        items.append({
            "id": got["id"], "sha256": got["sha256"], "kind": got["kind"],
            "width": got["width"], "height": got["height"], "format": got["format"],
            "review_state": got["review_state"],
            "has_provenance": bool(got["has_meta"]),
            "model": (meta or {}).get("model"),
            "seed": (meta or {}).get("seed"),
            "path": got["path"], "size": got["size"],
            #: フォルダの中での並びと、入れた時刻（画面が「並べ替え」に使う）
            "position": got["position"], "added_at": got["added_at"],
        })
    out = {
        "folder": _folder_dict(row, count=total),
        "total": int(total), "cursor": cursor, "limit": limit,
        "next_cursor": cursor + limit if cursor + limit < int(total) else None,
        "items": items,
    }
    if row["kind"] == "smart":
        # **黙って空にしない**（条件での絞り込みはまだ計算しない＝P2-2 以降）
        out["smart"] = True
        out["note"] = ("スマートフォルダの条件はまだ使えません。"
                       "この段では、手で入れた画像だけが出ます。")
    return out


# ---- 書く ----


def create(con: sqlite3.Connection, *, parent_id=None, name, kind: str = "manual",
           smart_query=None) -> dict:
    """フォルダを作る（§6.1 の `POST /api/folders {parent_id, name, kind}`）。"""
    if kind not in KINDS:
        raise ReviewError(422, "kind は manual / smart のいずれかです",
                          details={"kind": kind, "allowed": list(KINDS)})
    clean = _clean_name(name)
    parent = _parent_or_422(con, parent_id)
    if _depth_of(con, parent) >= 32:
        raise ReviewError(422, "フォルダの階層が深すぎます（32 段まで）",
                          code="folder_too_deep", details={"parent_id": parent})
    _assert_unique(con, parent, clean)
    query = _smart_query_of(con, kind, smart_query)
    folder_id = db.ulid()
    now = _now()
    try:
        con.execute(
            "INSERT INTO folder(id, parent_id, name, kind, smart_query, position,"
            " count_cache, count_cached_at, created_at, deleted_at)"
            " VALUES (?,?,?,?,?,?,NULL,NULL,?,NULL)",
            (folder_id, parent, clean, kind, query, _next_position(con, parent), now))
    except sqlite3.IntegrityError as exc:         # 別プロセスと競ったとき（索引が最後の砦）
        if "ux_folder_name" in str(exc):
            raise ReviewError(422, f"同じ親の下に「{clean}」があります（別の名前を付けてください）",
                              code="folder_name_taken",
                              details={"name": clean, "parent_id": parent}) from exc
        raise
    row = _row(con, folder_id)
    return {"created": True, **_folder_dict(row, count=0)}


def update(con: sqlite3.Connection, folder_id: str, payload: dict) -> dict:
    """名前・親・並び・条件を変える（§6.1 の `PATCH /api/folders/{id}`）。**渡された欄だけ**。"""
    row = _row(con, folder_id)
    if not isinstance(payload, dict):
        raise ReviewError(422, "本文はオブジェクトです")
    unknown = set(payload) - {"name", "parent_id", "position", "smart_query", "kind"}
    if unknown:
        raise ReviewError(422, "知らない欄があります",
                          details={"unknown": sorted(unknown)})
    name = row["name"]
    parent = row["parent_id"]
    query = row["smart_query"]
    kind = row["kind"]
    if "kind" in payload:
        if payload["kind"] not in KINDS:
            raise ReviewError(422, "kind は manual / smart のいずれかです",
                              details={"kind": payload["kind"], "allowed": list(KINDS)})
        kind = payload["kind"]
    if "name" in payload:
        name = _clean_name(payload["name"])
    if "parent_id" in payload:
        parent = _parent_or_422(con, payload["parent_id"])
        if parent == folder_id:
            raise ReviewError(422, "自分自身を親にはできません",
                              code="folder_cycle", details={"parent_id": parent})
        if parent is not None and parent in _subtree(con, folder_id):
            raise ReviewError(422, "子孫のフォルダを親にはできません（循環します）",
                              code="folder_cycle", details={"parent_id": parent})
        if _depth_of(con, parent) + _height_of(con, folder_id) > 32:
            # **枝の高さも数える**（親の深さだけ見ると、31 段目の下へ 3 段の枝を移せて 34 段になる。
            # P2-1 の監査 D-7）。1 枚だけの移動では前と同じ判定（height = 1）
            raise ReviewError(422, "フォルダの階層が深すぎます（32 段まで）",
                              code="folder_too_deep", details={"parent_id": parent})
    if "smart_query" in payload:
        query = _smart_query_of(con, kind, payload["smart_query"])
    elif kind == "smart" and query is None:
        raise ReviewError(422, "スマートフォルダには条件（smart_query）が要ります",
                          code="smart_query_required")
    elif kind == "manual" and query is not None:
        query = None                               # manual に戻したら条件は落とす
    if (name, parent) != (row["name"], row["parent_id"]):
        _assert_unique(con, parent, name, exclude=folder_id)
    position = row["position"]
    if "position" in payload:
        try:
            position = int(payload["position"])
        except (TypeError, ValueError) as exc:
            raise ReviewError(422, "position は 0 以上の整数です",
                              details={"position": payload["position"]}) from exc
        if position < 0:
            raise ReviewError(422, "position は 0 以上の整数です",
                              details={"position": position})
    try:
        con.execute(
            "UPDATE folder SET name = ?, parent_id = ?, kind = ?, smart_query = ?,"
            " position = ? WHERE id = ?",
            (name, parent, kind, query, position, folder_id))
    except sqlite3.IntegrityError as exc:
        if "ux_folder_name" in str(exc):
            raise ReviewError(422, f"同じ親の下に「{name}」があります（別の名前を付けてください）",
                              code="folder_name_taken",
                              details={"name": name, "parent_id": parent}) from exc
        raise
    return {"updated": True, **_folder_dict(_row(con, folder_id),
                                            count=_count_of(con, folder_id))}


def delete(con: sqlite3.Connection, folder_id: str, *, dry_run: bool = False,
           confirm: str | None = None, purge: bool = False) -> dict:
    """フォルダを消す（§6.1）。**既定は論理削除**（`deleted_at`）。**画像は 1 枚も消さない**。

    - `dry_run=true`: **何も消さずに**、消えるフォルダの数と中の枚数を返す
    - 実行には **`confirm` にフォルダ名**が要る（仮想フォルダは作り直せない分類なので、
      無警告で消さない。点検 C11）
    - `purge=true`: 実削除（`DELETE FROM folder`。`ON DELETE CASCADE` で下位と中身も消える）。
      **それでも `asset` は消えない**（`folder_member` だけ）

    隠すときは**子孫も一緒に隠す**（親だけ隠すと、木から子が見えなくなる）。
    **`folder_member` の行は消さない**（消えるのは `purge` のときだけ）。隠したフォルダの中身は
    木にも件数にも `GET .../assets` にも出ないが、**行は残る**ので、戻せば見える。
    前はここで `DELETE FROM folder_member` していたため、**「隠す」で分類が永久に消えていた**
    （P2-1 の監査 B-1。仮想フォルダは再生成できない分類。§6.1）。
    """
    if not isinstance(purge, bool):
        # **文字列の "false" を真にしない**（前は `bool("false")` が True で**実削除**になった。
        # 監査 C-4。`purge: true` の真偽値だけを実削除にし、他の型は 422）
        raise ReviewError(422, "purge は true / false で指定してください",
                          details={"purge": "true か false"})
    row = _row(con, folder_id)
    ids = _subtree(con, folder_id)
    marks = ",".join("?" * len(ids))
    members = con.execute(
        f"SELECT count(*) AS n FROM folder_member WHERE folder_id IN ({marks})",
        ids).fetchone()["n"]
    live_members = con.execute(
        f"SELECT count(*) AS n FROM folder_member m JOIN asset a ON a.id = m.asset_id"
        f" WHERE m.folder_id IN ({marks}) AND a.deleted_at IS NULL", ids).fetchone()["n"]
    if dry_run:
        return {
            "dry_run": True, "folder": _folder_dict(row, count=_count_of(con, folder_id)),
            #: 消える（隠れる）フォルダの数（自分を含む）
            "folders": len(ids),
            #: 中身の枚数（生きた画像だけ。合計には片付け済みの行も含む）
            "members": int(live_members), "member_rows": int(members),
            "purge": bool(purge), "assets_deleted": 0,
            "names": [r["name"] for r in con.execute(
                f"SELECT name FROM folder WHERE id IN ({marks}) ORDER BY name", ids)],
        }
    if confirm is None or str(confirm).strip() != row["name"]:
        raise ReviewError(422, "フォルダ名を打ち込んでください（消す前に確かめます）",
                          code="confirm_required",
                          details={"confirm": "フォルダの名前", "name": row["name"]})
    now = _now()
    if purge:
        # **消えるのはここだけ**。`folder_member` は CASCADE で一緒に消える（画像は消えない）
        con.execute("DELETE FROM folder WHERE id = ?", (folder_id,))
        return {"deleted": True, "purged": True, "folder_id": folder_id,
                "folders": len(ids), "members": int(members), "assets_deleted": 0}
    con.execute(f"UPDATE folder SET deleted_at = ? WHERE id IN ({marks}) AND deleted_at IS NULL",
                [now, *ids])
    # **`folder_member` は触らない**（隠すだけ。戻せば見える。監査 B-1）
    return {"deleted": True, "purged": False, "soft": True, "folder_id": folder_id,
            "folders": len(ids), "members": int(members), "assets_deleted": 0}


def _check_ids(asset_ids) -> list[str]:
    """`asset_ids` の形（文字列の配列・上限つき）。**重複は 1 つに**。"""
    if not isinstance(asset_ids, list) or not asset_ids:
        raise ReviewError(422, "asset_ids に画像の id を 1 つ以上入れてください",
                          details={"asset_ids": "1 件以上"})
    ids: list[str] = []
    for value in asset_ids:
        if not isinstance(value, str) or not value.strip():
            raise ReviewError(422, "asset_ids は画像の id の配列です",
                              details={"asset_ids": value})
        if value not in ids:
            ids.append(value)
    if len(ids) > MAX_MEMBERS:
        raise ReviewError(422, f"一度に入れられるのは {MAX_MEMBERS} 枚までです",
                          details={"asset_ids": f"{MAX_MEMBERS} 枚まで", "count": len(ids)})
    return ids


def _live_assets(con: sqlite3.Connection, ids: list[str]) -> list[str]:
    """**生きた画像だけ**を通す（知らない id・片付け済みは 422。黙って落とさない）。"""
    marks = ",".join("?" * len(ids))
    rows = con.execute(f"SELECT id FROM asset WHERE id IN ({marks}) AND deleted_at IS NULL",
                       ids).fetchall()
    found = {row["id"] for row in rows}
    missing = [value for value in ids if value not in found]
    if missing:
        raise ReviewError(422, "その画像はありません（片付け済みの画像は入れられません）",
                          code="asset_missing", details={"missing": missing})
    return ids


def add_members(con: sqlite3.Connection, folder_id: str, asset_ids) -> dict:
    """**入れる**（§6.1 の `POST /api/folders/{id}/members`）。**何度送っても同じ**（家風）。"""
    _row(con, folder_id)
    ids = _live_assets(con, _check_ids(asset_ids))
    have = {row["asset_id"] for row in con.execute(
        "SELECT asset_id FROM folder_member WHERE folder_id = ?", (folder_id,))}
    next_position = con.execute(
        "SELECT COALESCE(MAX(position), -1) + 1 AS n FROM folder_member WHERE folder_id = ?",
        (folder_id,)).fetchone()["n"]
    now = _now()
    added: list[str] = []
    already: list[str] = []
    for asset_id in ids:
        if asset_id in have or asset_id in added:
            already.append(asset_id)
            continue
        con.execute("INSERT INTO folder_member(folder_id, asset_id, position, added_at)"
                    " VALUES (?,?,?,?)", (folder_id, asset_id, next_position, now))
        next_position += 1
        added.append(asset_id)
    return {"folder_id": folder_id, "added": added, "already": already,
            "count": _count_of(con, folder_id)}


def remove_members(con: sqlite3.Connection, folder_id: str, asset_ids) -> dict:
    """**外す**（§6.1 の `DELETE /api/folders/{id}/members`）。**画像は消さない**。

    入っていない id は `not_member` で返す（**黙って捨てない**）。`folder_member` の行だけ消す。
    """
    row = _row(con, folder_id)
    if row["kind"] == "smart":
        pass                                       # スマートでも手で外せる（中身は同じ表）
    ids = _check_ids(asset_ids)
    marks = ",".join("?" * len(ids))
    have = {got["asset_id"] for got in con.execute(
        f"SELECT asset_id FROM folder_member WHERE folder_id = ? AND asset_id IN ({marks})",
        (folder_id, *ids))}
    removed = [value for value in ids if value in have]
    if removed:
        con.execute(f"DELETE FROM folder_member WHERE folder_id = ? AND asset_id IN"
                    f" ({','.join('?' * len(removed))})", (folder_id, *removed))
    return {"folder_id": folder_id, "removed": removed,
            "not_member": [value for value in ids if value not in have],
            "count": _count_of(con, folder_id)}


# ---- 口（`api/folders.py`）が使う包み ----


class FolderService:
    """`Store` を握って、上の関数を取引の中で呼ぶだけ（口は薄く。家風）。

    **読む口は `locked()`**（取引を開かない）、**書く口は `transaction()`**（1 つにまとめる）。
    """

    def __init__(self, store: Store):
        self.store = store

    def tree(self) -> dict:
        with self.store.locked() as con:
            return tree(con)

    def assets(self, folder_id: str, **kw) -> dict:
        with self.store.locked() as con:
            return assets(con, folder_id, **kw)

    def create(self, **kw) -> dict:
        with self.store.transaction() as con:
            return create(con, **kw)

    def update(self, folder_id: str, payload: dict) -> dict:
        with self.store.transaction() as con:
            return update(con, folder_id, payload)

    def delete(self, folder_id: str, **kw) -> dict:
        if kw.get("dry_run"):
            with self.store.locked() as con:        # **読み取り専用の道**（何も書かない）
                return delete(con, folder_id, **kw)
        with self.store.transaction() as con:
            return delete(con, folder_id, **kw)

    def add_members(self, folder_id: str, asset_ids) -> dict:
        with self.store.transaction() as con:
            return add_members(con, folder_id, asset_ids)

    def remove_members(self, folder_id: str, asset_ids) -> dict:
        with self.store.transaction() as con:
            return remove_members(con, folder_id, asset_ids)
