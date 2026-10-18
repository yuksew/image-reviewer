"""参照切れの再リンク（P8-6。設計 `docs/p8-design.md` §0.11・§1.2 の線 9・§3.2・§3.4）。

**アプリの外でファイルを動かすと参照が切れる**（`missing_at` が立つ）。同じ絵を新しい場所に
結び付け直すのがこのサービスで、**判断・タグ・来歴は `asset` の側にあるので触らない**
（場所だけを繋ぎ直す）。

決めたこと（設計が正。破ったら壊れる物の順に書く）:

1. **中身を確かめてから繋ぐ**（設計 §0.11・§3.4・§8.1 の 22）。照合は **`sha256` の完全一致**
   だけ。**`size` / `mtime_ns` は見ない**（移動で mtime は変わる）。**pHash でも代用しない**
   （知覚ハッシュは「似た別の絵」を同じと見なすので、**利用者の「同じ絵かどうか」を守れない**）。
   合わなければ **409 `hash_mismatch`**。
2. **`asset_location.path` は上書きせず、その行を付け替える**（`missing_at` を NULL に戻す）。
   行を消して入れ直すと `is_primary` と「いつから見ているか」が失われる。
3. **既にそのパスが別の `asset` に登録されていれば 409 `path_taken`**（**二重登録しない**。
   `asset_location.path` は主キーなので、そのまま入れると `IntegrityError`＝500 になる）。
   **同じ `asset` に既に生きて登録されていれば 409 `already_registered`**（する事が無い）。
   **元のパスにそのまま戻ってきた**ときだけは例外で、`missing_at` を戻すだけ（履歴は増やさない）。
4. **`location_history` に 1 行**（`path` = 移動元・`to_path` = 移動先・`reason='relinked'`・
   `actor`）。**列は P8-6 で足した**（設計 §0.11 が言う「入れ替わった」「繋ぎ直した」を
   区別する列が無かった。`db.TOP_UP_COLUMNS` が既存の DB にも当てる）。
5. **人だけ**（設計 §3.2。検査は `api.require_human` の 1 か所。エージェントは 403 `human_only`）。
   `location_history.actor` に**誰が繋いだか**を残す。
6. **消しに行かない・動かさない。** ここは**登録を直すだけ**で、ファイルには 1 バイトも書かない
   （`unlink` / `rename` を呼ばない）。読むのは `sha256` の計算と、`nearby` の走査だけ。
7. **`GET` は 1 バイトも書かない**（`missing()` は読むだけ。設計 §0.13）。
8. **黙って捨てない**: `nearby` は探した数・候補・読めなかった物・打ち切ったらその数も返す。
"""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path

from . import db
from .deletions import DeletionService          # `asset.deleted_at` の規則を 1 か所に保つ
from .review import ReviewError
from .scan import iter_images                   # 走査と同じ「画像だけ」の歩き方を使う
from .store import is_under, normalize_path

log = logging.getLogger(__name__)

#: 口が受ける `mode`（設計 §3.2 の `mode:'nearby'|'exact'`）
MODES = ("exact", "nearby")
#: `location_history.reason` の語彙（`db.py` の `CHECK` と同じ）。**再リンクの印**
REASON_RELINKED = "relinked"
#: 入れ替わりの印（`store.register()` が書く。**古い行は NULL**）
REASON_REPLACED = "replaced"
#: `GET /api/locations/missing` の既定と上限（**数を黙って捨てない**ので `unlisted` を返す）
DEFAULT_MISSING_LIMIT = 500
MAX_MISSING_LIMIT = 5000
#: `nearby` で中身を確かめる候補の上限（**同じ名前が大量にある置き場**で固まらないように）
NEARBY_CANDIDATE_LIMIT = 200
#: `sha256` を読む塊（`scan.py` と同じ 1 MiB）
READ_BLOCK = 1 << 20


# ---- 道具（テストが差し替えられる形にする）----


def sha256_of(path) -> str:
    """ファイルの中身の `sha256`（**これが「同じ絵かどうか」の唯一の判定**）。

    `scan.py` の `_read_head_hash_chunks` と同じ読み方（1 MiB ずつ）。向こうは先頭バイトと
    マジックナンバーも一緒に取るが、ここは**中身の照合だけ**なので分けてある。
    """
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(READ_BLOCK), b""):
            digest.update(block)
    return digest.hexdigest()


def _actor_of(actor) -> str:
    """`actor` の語彙を検査する（**語彙外は 422**。`CHECK` に当てて 500 にしない。家風）。"""
    if actor not in ("human", "agent"):
        raise ReviewError(422, "actor は human / agent のいずれかです", code="bad_actor",
                          details={"actor": actor})
    return str(actor)


def _mode_of(mode) -> str:
    """`mode` の語彙を検査する（**語彙外は 422**）。既定は `exact`（人がパスを指定する形）。"""
    got = "exact" if mode is None or str(mode).strip() == "" else str(mode).strip()
    if got not in MODES:
        raise ReviewError(422, "mode は exact / nearby のいずれかです", code="bad_mode",
                          details={"mode": mode, "modes": list(MODES)})
    return got


def file_name_of(display_path) -> str:
    """その場所のファイル名（`nearby` が同じ名前を探すのに使う）。**大小文字は畳む**。"""
    return Path(str(display_path)).name.casefold()


class RelinkService:
    """参照切れの一覧と、繋ぎ直し（§0.11・§3.2）。

    書き込みは 1 取引（`asset_location` の 1 行と `location_history` の 1 行）。
    **ファイル操作は 1 つも無い**ので、削除のような「動かしてから台帳」の順序の問題は無い。
    """

    def __init__(self, store):
        self.store = store

    # ---- 読む（`GET` は 1 バイトも書かない）----

    def missing(self, *, limit: int = DEFAULT_MISSING_LIMIT, include_deleted: bool = False,
                actor: str = "human") -> dict:
        """**参照切れの一覧**（設計 §3.2。`missing_at` が立っている `asset_location`）。

        - **消した物は既定で出さない。** 段 2・3 の削除も `missing_at` を立てる（§4.1）ので、
          そのまま出すと「参照切れ」と「アプリから消した物」が混ざる。**数は `excluded_deleted`
          で返す**（黙って捨てない）。`include_deleted=1` で全部出す
        - `roots` はその場所を含む**登録した置き場**（`nearby` が探す範囲。画面の案内にも使える）
        - **`limit` を超えた分は `unlisted` に数える**（一覧は切っても数は切らない）
        """
        _actor_of(actor)
        limit = _limit_of(limit)
        with self.store.locked() as con:
            rows = con.execute(
                "SELECT l.path, l.display_path, l.asset_id, l.size, l.mtime_ns, l.is_primary,"
                " l.missing_at, l.last_seen_at, a.sha256, a.deleted_at, a.review_state,"
                " (SELECT count(*) FROM asset_location x"
                "   WHERE x.asset_id = l.asset_id AND x.missing_at IS NULL) AS live_locations,"
                " (SELECT d.id FROM deletion_log d"
                "   WHERE d.path = l.path AND d.restored_at IS NULL AND d.stage IN (2, 3)"
                "   ORDER BY d.at DESC, d.id DESC LIMIT 1) AS active_deletion_id,"
                " EXISTS (SELECT 1 FROM asset_meta m WHERE m.asset_id = l.asset_id) AS has_meta"
                " FROM asset_location l JOIN asset a ON a.id = l.asset_id"
                " WHERE l.missing_at IS NOT NULL"
                " ORDER BY l.missing_at DESC, l.display_path"
            ).fetchall()
            roots = [r["display_path"] for r in
                     con.execute("SELECT display_path FROM root ORDER BY display_path")]
        items: list[dict] = []
        excluded = 0
        for row in rows:
            deleted = bool(row["deleted_at"])
            if deleted and not include_deleted:
                excluded += 1
                continue
            items.append({
                "asset_id": row["asset_id"],
                "key": row["path"],
                "path": row["display_path"],
                "display_path": row["display_path"],
                "size": row["size"],
                "mtime_ns": row["mtime_ns"],
                "missing_at": row["missing_at"],
                "last_seen_at": row["last_seen_at"],
                "is_primary": bool(row["is_primary"]),
                "sha256": row["sha256"],
                "review_state": row["review_state"],
                "has_provenance": bool(row["has_meta"]),
                # **消した物**（段 1〜3）と、**削除の途中**（段 2・3 の生きた台帳）は別の欄
                "deleted": deleted,
                "active_deletion_id": row["active_deletion_id"],
                "other_live_locations": int(row["live_locations"]),
                "roots": [r for r in roots if is_under(row["display_path"], r)],
            })
        total = len(items)
        page = items[:limit]
        return {
            "total": total,
            "count": len(page),
            "unlisted": total - len(page),
            "excluded_deleted": excluded,
            "include_deleted": bool(include_deleted),
            "limit": limit,
            "items": page,
            # **辿り方**を応答に書く（画面が無いので、口だけで使えるように）
            "hint": ("POST /api/locations/relink {asset_id, path, mode:'exact'} で繋ぎ直せます"
                     "（中身の sha256 が一致するときだけ）"),
        }

    # ---- 書く（人だけ。検査は `api.require_human`）----

    def relink(self, *, asset_id: str, path: str | None = None, mode: str = "exact",
               from_path: str | None = None, actor: str = "human") -> dict:
        """参照切れの 1 か所を新しいパスに繋ぎ直す（設計 §3.2 の `POST /api/locations/relink`）。

        - `mode='exact'`（既定）: **`path` は新しいファイル**。中身を確かめて繋ぐ
        - `mode='nearby'`: **`path` は探すフォルダ**（省略すると、その場所が入っている
          登録済みの置き場を**同じファイル名**で探す）。設計 §0.11 の「近くを探す」
        - `from_path` は**どの参照切れか**を指定する（1 枚が 2 か所以上で切れているとき）。

        **ファイルは動かさない・消さない。** 登録（`asset_location`）と履歴だけを直す。
        """
        actor = _actor_of(actor)
        mode = _mode_of(mode)
        aid = str(asset_id or "").strip()
        if not aid:
            raise ReviewError(422, "asset_id が要ります", code="bad_request",
                              details={"asset_id": asset_id})
        given = str(path or "").strip()
        if mode == "exact" and not given:
            raise ReviewError(422, "path が要ります（繋ぎ直す先のファイル）", code="bad_path",
                              details={"path": path, "mode": mode})

        target, roots = self._target_of(aid, from_path=from_path)
        self._refuse_if_deleting(target)

        # --- 新しいパスを決める（exact はその 1 つ・nearby は同じ名前を探す）---
        searched = None
        candidates: list[str] = []
        unreadable: list[str] = []
        truncated = False
        if mode == "exact":
            chosen = Path(given)
            if chosen.is_dir():
                raise ReviewError(422, "ファイルを指定してください（フォルダは指定できません）",
                                  code="bad_path", details={"path": given, "mode": mode})
            if not chosen.is_file():
                raise ReviewError(404, "指定したファイルがありません", code="not_found",
                                  details={"path": given, "mode": mode})
            others: list[Path] = []
        else:
            chosen, others, searched, candidates, unreadable, truncated = \
                self._search_nearby(target, given, roots)

        new_display = str(chosen)
        new_key = normalize_path(chosen)
        self._refuse_if_registered(aid, target, new_key)

        got = self._sha256_or_error(chosen)
        if got != (target["sha256"] or "").lower():
            raise ReviewError(409, "中身が違います（同じ絵ではありません）",
                              code="hash_mismatch",
                              details={"path": new_display, "mode": mode,
                                       "expected": target["sha256"], "actual": got,
                                       "candidates": [str(p) for p in others]})
        at = db.now()
        info = chosen.stat()
        moved = new_key != target["path"]
        with self.store.transaction() as con:
            history_id = None
            if moved:
                cur = con.execute(
                    "INSERT INTO location_history(asset_id, path, size, mtime_ns,"
                    " replaced_by_asset_id, replaced_at, to_path, reason, actor)"
                    " VALUES (?,?,?,?,NULL,?,?,?,?)",
                    (target["asset_id"], target["display_path"], target["size"],
                     target["mtime_ns"], at, new_display, REASON_RELINKED, actor))
                history_id = int(cur.lastrowid)
                done = con.execute(
                    "UPDATE asset_location SET path = ?, display_path = ?, size = ?, mtime_ns = ?,"
                    " missing_at = NULL, last_seen_at = ? WHERE path = ? AND asset_id = ?",
                    (new_key, new_display, int(info.st_size), int(info.st_mtime_ns), at,
                     target["path"], target["asset_id"]))
            else:
                # **元の場所に戻ってきた**（同じ鍵）。動いていないので履歴は増やさない
                done = con.execute(
                    "UPDATE asset_location SET display_path = ?, size = ?, mtime_ns = ?,"
                    " missing_at = NULL, last_seen_at = ? WHERE path = ? AND asset_id = ?",
                    (new_display, int(info.st_size), int(info.st_mtime_ns), at,
                     target["path"], target["asset_id"]))
            if int(done.rowcount or 0) != 1:
                # 取引の中で行が消えていた（同時の削除など）。**中途半端に進めない**
                raise ReviewError(409, "その場所の登録が変わりました（やり直してください）",
                                  code="not_registered", details={"path": target["path"]})
            # **`asset.deleted_at` の規則は 1 か所**（`deletions._sync_hidden`）。生きている場所が
            # 戻れば一覧にも戻る（段 1 で外したままなら、その印はそのまま残る）
            DeletionService._sync_hidden(con, target["asset_id"], at)
            kept = self._kept(con, target["asset_id"])
            left = con.execute(
                "SELECT count(*) AS n FROM asset_location"
                " WHERE asset_id = ? AND missing_at IS NOT NULL",
                (target["asset_id"],)).fetchone()["n"]
        out = {
            "relinked": True,
            "moved": moved,
            "asset_id": target["asset_id"],
            "sha256": target["sha256"],
            "from_key": target["path"],
            "from_path": target["display_path"],
            "to_key": new_key,
            "to_path": new_display,
            "mode": mode,
            "actor": actor,
            "at": at,
            "size": int(info.st_size),
            "mtime_ns": int(info.st_mtime_ns),
            "history_id": history_id,
            "missing_left": int(left),
            "kept": kept,
        }
        if mode == "nearby":
            out.update({"searched": searched, "candidates": candidates,
                        "unreadable": unreadable, "candidates_truncated": truncated})
            if others:
                # 同じ中身が他にもあった（**選ばなかった物も出す**。黙って捨てない）
                out["also_found"] = [str(p) for p in others]
        return out

    # ---- 中 ----

    def _target_of(self, asset_id: str, *, from_path: str | None) -> tuple[dict, list[str]]:
        """参照切れの 1 行を決める（**`from_path` が無くて 2 か所以上なら 409 `ambiguous`**）。"""
        with self.store.locked() as con:
            asset = con.execute("SELECT id, sha256 FROM asset WHERE id = ?",
                                (asset_id,)).fetchone()
            if asset is None:
                raise ReviewError(404, "その画像は登録されていません", code="not_found",
                                  details={"asset_id": asset_id})
            rows = con.execute(
                "SELECT path, display_path, asset_id, size, mtime_ns, missing_at, sha256"
                " FROM asset_location l JOIN asset a ON a.id = l.asset_id"
                " WHERE l.asset_id = ? AND l.missing_at IS NOT NULL"
                " ORDER BY l.display_path", (asset_id,)).fetchall()
            roots = [r["display_path"] for r in
                     con.execute("SELECT display_path FROM root ORDER BY display_path")]
        if not rows:
            raise ReviewError(409, "この画像に参照切れの場所はありません", code="not_missing",
                              details={"asset_id": asset_id})
        if from_path:
            key = normalize_path(from_path)
            for row in rows:
                if row["path"] == key:
                    return dict(row), roots
            raise ReviewError(409, "その場所は参照切れとして登録されていません",
                              code="not_registered",
                              details={"path": key, "missing": [r["display_path"] for r in rows]})
        if len(rows) > 1:
            raise ReviewError(409, "参照切れが 2 か所以上あります（from_path で指定してください）",
                              code="ambiguous",
                              details={"missing": [{"path": r["display_path"], "key": r["path"]}
                                                   for r in rows]})
        return dict(rows[0]), roots

    def _refuse_if_deleting(self, target: dict) -> None:
        """**削除の途中（段 2・3）の場所は繋がない**（消した物を勝手に戻さない）。

        段 2・3 は `missing_at` を立てる（§4.1）ので、そのままでは「参照切れ」と見分けが付かない。
        ここで断り、**「最近の削除」から戻す道**を案内する（`details.undo` に口を入れる）。
        """
        with self.store.locked() as con:
            row = con.execute(
                "SELECT id, stage FROM deletion_log"
                " WHERE path = ? AND restored_at IS NULL AND stage IN (2, 3)"
                " ORDER BY at DESC, id DESC LIMIT 1", (target["path"],)).fetchone()
        if row is not None:
            raise ReviewError(
                409, "この場所は削除の途中です（先に「最近の削除」から戻してください）",
                code="deleted",
                details={"path": target["display_path"], "deletion_id": row["id"],
                         "stage": int(row["stage"]),
                         "undo": f"/api/pending-deletes/{row['id']}/undo"})

    def _refuse_if_registered(self, asset_id: str, target: dict, new_key: str) -> None:
        """**二重登録しない**（§3.2）。主キーに当てて 500 にしない。

        - 別の `asset` のパス → **409 `path_taken`**
        - 同じ `asset` の**別の生きた場所** → **409 `already_registered`**（する事が無い）
        - **移り先が元のパスと同じ**（元の場所に戻ってきた）→ 通す（`missing_at` を戻すだけ）
        """
        if new_key == target["path"]:
            return
        with self.store.locked() as con:
            row = con.execute("SELECT asset_id, missing_at FROM asset_location WHERE path = ?",
                              (new_key,)).fetchone()
        if row is None:
            return
        if row["asset_id"] == asset_id:
            raise ReviewError(409, "その場所は既にこの画像に登録されています",
                              code="already_registered",
                              details={"path": new_key, "asset_id": asset_id})
        raise ReviewError(409, "その場所は別の画像に登録されています（二重登録しません）",
                          code="path_taken",
                          details={"path": new_key, "asset_id": row["asset_id"]})

    def _sha256_or_error(self, path: Path) -> str:
        """中身の `sha256`。**読めなければ繋がない**（409 `unreadable`。500 にしない）。"""
        try:
            return sha256_of(path)
        except OSError as exc:
            raise ReviewError(409, "ファイルを読めないので繋ぎ直せません", code="unreadable",
                              details={"path": str(path), "error": str(exc)}) from exc

    def _search_nearby(self, target: dict, given: str, roots: list[str],
                       ) -> tuple[Path, list[Path], int, list[str], list[str], bool]:
        """**同じファイル名を探し、ハッシュが一致する物だけ**を候補にする（設計 §0.11）。

        - `given` があればそのフォルダ（ファイルを渡されたらその親）
        - 無ければ**その場所が入っている登録済みの置き場**（`roots`）。**無ければ 422 `bad_scope`**
          （ディスク全体を勝手に歩かない）
        - 候補は `NEARBY_CANDIDATE_LIMIT` まで（**打ち切ったら数を返す**）
        """
        name = file_name_of(target["display_path"])
        folders: list[Path] = []
        if given:
            picked = Path(given)
            if picked.is_file():
                picked = picked.parent
            if not picked.is_dir():
                raise ReviewError(404, "探すフォルダがありません", code="not_found",
                                  details={"path": given, "mode": "nearby"})
            folders = [picked]
        else:
            folders = [Path(r) for r in roots if is_under(target["display_path"], r)]
            if not folders:
                raise ReviewError(
                    422, "この場所は登録した置き場の下にないので、探すフォルダを指定してください",
                    code="bad_scope",
                    details={"path": target["display_path"], "roots": roots, "mode": "nearby"})
        found: list[Path] = []
        for folder in folders:
            for path in iter_images(folder):                 # 走査と同じ「画像だけ」の規則
                if Path(path).name.casefold() == name:
                    found.append(Path(path))
        # **決定的に**（同じ入力なら同じ答え。大小文字を畳んでから並べる）
        found = sorted({str(p) for p in found}, key=lambda s: (s.casefold(), s))
        truncated = len(found) > NEARBY_CANDIDATE_LIMIT
        found = found[:NEARBY_CANDIDATE_LIMIT]
        matches: list[Path] = []
        unreadable: list[str] = []
        for raw in found:
            try:
                if sha256_of(raw) == (target["sha256"] or "").lower():
                    matches.append(Path(raw))
            except OSError:
                unreadable.append(raw)
        if not matches:
            if not found:
                raise ReviewError(404, "同じ名前のファイルが見つかりません", code="not_found",
                                  details={"mode": "nearby", "name": name,
                                           "folders": [str(f) for f in folders], "searched": 0})
            raise ReviewError(
                409, "同じ名前はありましたが中身が違います（同じ絵ではありません）",
                code="hash_mismatch",
                details={"mode": "nearby", "name": name, "expected": target["sha256"],
                         "candidates": found, "unreadable": unreadable})
        return matches[0], matches[1:], len(found), found, unreadable, truncated

    @staticmethod
    def _kept(con, asset_id: str) -> dict:
        """**判断・タグ・来歴を保ったまま**であることを応答で見せる（消していない証拠）。"""
        return {
            "decisions": int(con.execute(
                "SELECT count(*) AS n FROM decision WHERE subject_type = 'asset'"
                "   AND subject_id = ?", (asset_id,)).fetchone()["n"]),
            "tags": int(con.execute(
                "SELECT count(*) AS n FROM asset_tag WHERE asset_id = ?",
                (asset_id,)).fetchone()["n"]),
            "locations": int(con.execute(
                "SELECT count(*) AS n FROM asset_location WHERE asset_id = ?",
                (asset_id,)).fetchone()["n"]),
            "has_provenance": bool(con.execute(
                "SELECT 1 FROM asset_meta WHERE asset_id = ?", (asset_id,)).fetchone()),
        }


def _limit_of(limit) -> int:
    """`limit` の語彙（**0 以上 `MAX_MISSING_LIMIT` 以下**。語彙外は 422）。

    **真偽値と小数は通さない**（`int(True)` は 1、`int(2.9)` は 2 になる。家風 D-6 と同じ）。
    """
    if isinstance(limit, bool):
        got = -1
    elif isinstance(limit, float) and not float(limit).is_integer():
        got = -1
    else:
        try:
            got = int(limit)
        except (TypeError, ValueError):
            got = -1
    if not (0 <= got <= MAX_MISSING_LIMIT):
        raise ReviewError(422, f"limit は 0〜{MAX_MISSING_LIMIT} の整数です",
                          details={"limit": limit, "max": MAX_MISSING_LIMIT})
    return got
