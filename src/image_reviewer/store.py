"""SQLite のストア（P5-0）。JSON 版と**同じ名前・同じ形**のまま、置き場を DB にする。

設計: docs/p5-design.md §0.1（P5-0）・§0.8、docs/design.md §5.1・§5.4

守ること:
- **行を書くのであって、ファイル全体を置き換えない。** `cli scan` はサーバとは別プロセスで
  走る。JSON 版の `save()`（全体を `os.replace`）は、その間に付いた判断を消していた（点検 B5）
- `asset.id` は **ULID**。内容の正体は `sha256` の別列（点検 I17・C13）
- `asset_location.path` は**正規化した鍵**、表示は `display_path`（点検 I1）
- `register()` は 1 呼び出し = 1 トランザクション。半端な行を外に出さない
- 接続は 1 本を `RLock` で直列化し、`check_same_thread=False` で開く。FastAPI の同期
  エンドポイントはスレッドプールで走るので、これが無いと落ちる（点検 F6）

JSON 版と違う点で、**呼び出し側が知るべきこと**:
- `store.data` は無い。根は `roots()`、履歴は `location_history()`
- `asset()` が返す `meta` は**写し**。書き換えても保存されないので `set_meta()` を呼ぶ
  （JSON 版は同じ dict を握っていたので `save()` で書けた。`capture.py` が該当する）
- `asset["id"]` は ULID なので、**内容で引きたいときは `sha256`**を使う
- `asset["size"]` は列ではなく**代表の場所から導く**（`db.py` の `asset` に列が無い）
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from . import db

log = logging.getLogger(__name__)

SCHEMA_VERSION = db.SCHEMA_VERSION

REVIEW_STATES = ("unreviewed", "kept", "rejected")


def normalize_path(path) -> str:
    """パスの鍵。大小文字・区切り・ジャンクションを揃える（点検 I1）。

    これをしないと、利用者が 2 回目に小文字のドライブ名で走査しただけで
    全ファイルが「新しい場所」として再登録される。
    """
    return os.path.normcase(os.path.realpath(str(path)))


def is_under(path: str, root: str) -> bool:
    """区切り文字の単位で「下にあるか」を判定する（`C:\\img` と `C:\\img2` を混同しない）。"""
    p, r = normalize_path(path), normalize_path(root).rstrip("\\/")
    return p == r or p.startswith(r + os.sep)


class Store:
    """SQLite のストア。`Store(data_dir)` で開き、`close()` か `with` で閉じる。

    **（P8-4）`read_only=True` の道**（設計 §0.12-5・§10-12）。DB が壊れているか、
    DB の版がバイナリより新しいときに、**書き込まずに起動する**ために使う。
    このとき `migrate()` は走らせない（読み取り専用の接続では書けずに落ちる）。
    書き込みの口は `app.py` の middleware が 503 で止める（家風「検査は 1 か所」）。
    """

    def __init__(self, data_dir: str | Path, *, read_only: bool = False):
        self.data_dir = Path(data_dir)
        #: **読み取り専用で開いているか**（`GET /api/health/db` と middleware が見る）
        self.read_only = bool(read_only)
        #: **（P8-4 の監査 D-2 / G-5）** 版を上げずに表の形を変える前に取った控え
        self.shape_backup: dict | None = None
        self._shape_backup_error: str | None = None
        # スレッドプールから同じ接続を使うための錠（点検 F6）。入れ子で取るので RLock
        self._lock = threading.RLock()
        self._closed = False
        if not self.read_only:
            # **版を上げずに表の形を変える前に控えを取る**（`_top_up_v6` の `ALTER`）。
            # 実データで `deletion_log.stuck_reason` が控え無しに足された（監査の事故 2 件目）。
            # **控えが取れなくても開く**（足すだけの `ALTER` なので、開けなくする方が害が大きい）。
            # 取れなかったことは `settings` の `backup.last_error` に残す（黙って形を変えない）。
            from .backup import backup_before_shape_change      # 循環 import を避けて局所で

            try:
                self.shape_backup = backup_before_shape_change(self.data_dir)
            except Exception as exc:                            # noqa: BLE001
                self._shape_backup_error = f"表の形を変える前の控えを取れませんでした: {exc}"
        self._con = db.open_db(self.data_dir, read_only=self.read_only,
                               check_same_thread=False)
        if self._shape_backup_error:
            self._record_shape_backup_error(self._shape_backup_error)

    # ---- 寿命 ----

    @property
    def con(self) -> sqlite3.Connection:
        """生の接続。直接 SQL を書くとき（取り込みと P5-1 の台帳）に使う。"""
        return self._con

    def _record_shape_backup_error(self, message: str) -> None:
        """**控え無しで表の形を変えた**ことを残す（P8-4 の監査 D-2 / G-5）。

        ここは `Store` が開いた直後なので、`transaction()` を通さず**生の 1 文**で書く
        （`settings` は `migrate()` が作っている）。書けなくても開けていることは止めない。
        """
        from .backup import SETTING_LAST_ERROR, SETTING_LAST_ERROR_AT

        try:
            with self._lock:
                for key, value in ((SETTING_LAST_ERROR, message),
                                   (SETTING_LAST_ERROR_AT, db.now())):
                    self._con.execute(
                        "INSERT INTO settings(key, value) VALUES (?, ?)"
                        " ON CONFLICT(key) DO UPDATE SET value = excluded.value", (key, value))
        except sqlite3.Error:
            log.warning("表の形を変える前の控えの失敗を記録できませんでした: %s", message)
        else:
            log.warning("%s", message)

    def close(self) -> None:
        """閉じる。**2 回呼んでも安全**（`with` を抜けた後に呼ぶ経路があるため）。"""
        with self._lock:
            if self._closed:
                return
            self._con.close()
            self._closed = True

    def __enter__(self) -> "Store":
        return self

    def __exit__(self, *exc) -> bool:
        self.close()
        return False

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        """書き込みを 1 トランザクションにまとめる（`db.py` は autocommit）。

        入れ子では外側に乗る（`register()` の中から `set_meta()` を呼んでも壊れない）。
        トランザクションの間は錠を握るので、別スレッドの文が混ざらない。

        **（P8-4）読み取り専用で開いているときは 503 `read_only`。** 素の
        `attempt to write a readonly database`（OperationalError）は口ごとに 500 になって
        しまうので、**書き込みを止めていることを番号で返す**（設計 §3.4）。
        """
        if self.read_only:
            from .review import ReviewError          # 循環 import を避けて局所で

            raise ReviewError(503, "DB が壊れているので書き込めません（バックアップから戻してください）",
                              code="read_only")
        with self._lock:
            if self._con.in_transaction:
                yield self._con
                return
            self._con.execute("BEGIN IMMEDIATE")
            try:
                yield self._con
            except BaseException:
                self._con.execute("ROLLBACK")
                raise
            self._con.execute("COMMIT")

    @contextmanager
    def locked(self) -> Iterator[sqlite3.Connection]:
        """読み出しを錠の下で行う（監査 B3）。**取引は開かない**。

        書き込みは `transaction()` が錠を握ったまま `BEGIN IMMEDIATE` 〜 `COMMIT`（または
        `ROLLBACK`）を進める。ここで同じ錠を取れば、**取引の途中の（まだコミットされていない）
        行**を読むことがない。取引を開かないので、読みのためだけに書き手を待たせない。
        """
        with self._lock:
            yield self._con

    def save(self) -> None:
        """互換のための名前。**開いている取引を閉じるだけ**（`db.py` は autocommit）。

        JSON 版の「全体を書き直す」は戻さない。それが判断を消す経路そのものだった（点検 B5）。
        """
        with self._lock:
            if self._con.in_transaction:
                self._con.execute("COMMIT")

    # ---- 参照 ----

    def location_of(self, path: str) -> dict | None:
        """場所の行。`path` は**正規化した鍵**（表示用は `display_path`）。

        `sha256` も返す。`scan.py` は「同じパスの中身が入れ替わったか」を
        `known["asset_id"] != sha` で見ていたが、`asset_id` が ULID になったので
        内容そのものを返して比べさせる（点検 I17 の帰結）。
        """
        key = normalize_path(path)
        row = self._fetchone(
            "SELECT l.path, l.display_path, l.asset_id, l.size, l.mtime_ns, l.is_primary,"
            " l.missing_at, l.last_seen_at, a.sha256"
            " FROM asset_location l JOIN asset a ON a.id = l.asset_id WHERE l.path = ?",
            (key,),
        )
        return dict(row) if row is not None else None

    def asset(self, asset_id: str) -> dict | None:
        """1 枚。**形は JSON 版のまま**（`app.py` と `capture.py` が読む）。"""
        row = self._fetchone("SELECT * FROM asset WHERE id = ?", (asset_id,))
        if row is None:
            return None
        return self._asset_dict(row, self._locations(asset_id), self._meta_row(asset_id))

    def assets(self) -> list[dict]:
        """全部。**表示用のパスの順**（`app.py` の一覧がそのまま使える）。"""
        with self._lock:
            rows = self._con.execute("SELECT * FROM asset").fetchall()
            locs: dict[str, list[dict]] = {}
            for r in self._con.execute(
                "SELECT * FROM asset_location ORDER BY is_primary DESC, display_path"
            ):
                locs.setdefault(r["asset_id"], []).append(_location_dict(r))
            metas = {r["asset_id"]: r for r in self._con.execute("SELECT * FROM asset_meta")}
        out = [self._asset_dict(r, locs.get(r["id"], []), metas.get(r["id"])) for r in rows]
        # 代表の場所（無ければ空文字）で並べる。同じなら id で決める（順序を安定させる）
        out.sort(key=lambda a: (_display_key(a), a["id"]))
        return out

    def stats(self) -> dict:
        """件数。**鍵は JSON 版と同じ**（`app.py` の `/api/stats` が読む）。"""
        with self._lock:
            n_assets = self._con.execute("SELECT count(*) AS n FROM asset").fetchone()["n"]
            n_locations = self._con.execute(
                "SELECT count(*) AS n FROM asset_location").fetchone()["n"]
            rows = self._con.execute("SELECT meta_json FROM asset_meta").fetchall()
            missing = self._con.execute(
                "SELECT count(*) AS n FROM asset a WHERE NOT EXISTS ("
                "  SELECT 1 FROM asset_location l"
                "  WHERE l.asset_id = a.id AND l.missing_at IS NULL)"
            ).fetchone()["n"]
        metas = [_parse_meta(r["meta_json"]) for r in rows]
        with_prov = sum(1 for m in metas if m)
        return {
            "assets": n_assets,
            "locations": n_locations,
            "with_provenance": with_prov,
            "without_provenance": n_assets - with_prov,
            "by_model": _count(metas, lambda m: (m or {}).get("model")),
            # JSON 版と同じ規則: **生きた場所が 1 つも無い**枚を数える
            # （場所が 0 行の枚もここに入る。`all([])` が True だったのと同じ）
            "missing": missing,
        }

    def location_history(self) -> list[dict]:
        """パスの中身が入れ替わった履歴（`store.data["location_history"]` の代わり）。"""
        with self._lock:
            rows = self._con.execute(
                "SELECT id, asset_id, path, size, mtime_ns, replaced_by_asset_id, replaced_at"
                " FROM location_history ORDER BY id"
            ).fetchall()
        return [dict(r) for r in rows]

    def roots(self) -> list[str]:
        """走査した根（**表示用のパス**）。JSON 版の `store.data["roots"]` の代わり。

        鍵（`root.path`）ではなく表示用を返す。`app.py` と `cli.py` はそのまま
        `scan()` へ渡し、`scan.py` が `str(Path(r))` に直して使う。
        """
        with self._lock:
            rows = self._con.execute(
                "SELECT display_path FROM root ORDER BY display_path").fetchall()
        return [r["display_path"] for r in rows]

    # ---- 更新 ----

    def register(
        self,
        *,
        sha256: str,
        path: str,
        size: int,
        mtime_ns: int,
        width: int | None,
        height: int | None,
        fmt: str,
        meta: dict | None,
        note: str | None,
        source: str = "scan",
        kind: str | None = None,
        kind_source: str | None = None,
    ) -> tuple[str, bool]:
        """(asset_id, created) を返す。同じパスの中身が変わっていたら載せ替える。

        **1 トランザクション**で、asset / asset_meta / asset_location /
        location_history のどこまで進んでも半端な状態を外に出さない。
        """
        key = normalize_path(path)
        display = str(Path(path))
        now = db.now()
        with self.transaction():
            current = self._con.execute(
                "SELECT asset_id FROM asset_location WHERE path = ?", (key,)).fetchone()
            old_id = current["asset_id"] if current is not None else None

            row = self._con.execute("SELECT id FROM asset WHERE sha256 = ?", (sha256,)).fetchone()
            created = row is None
            if created:
                asset_id = db.ulid()
                self._con.execute(
                    "INSERT INTO asset(id, sha256, kind, kind_source, width, height, format,"
                    " first_seen_at, last_seen_at) VALUES (?,?,?,?,?,?,?,?,?)",
                    (
                        asset_id,
                        sha256,
                        # 種別の規則は走査側が決める（点検 C2）。既定は JSON 版と同じ
                        kind or ("generated" if meta else "photo"),
                        kind_source or "auto",
                        width,
                        height,
                        fmt,
                        now,
                        now,
                    ),
                )
                self._write_meta(asset_id, meta, note, source, now)
            else:
                asset_id = row["id"]
                self._con.execute("UPDATE asset SET last_seen_at = ? WHERE id = ?", (now, asset_id))
                if self._con.execute(
                    "SELECT 1 FROM asset_meta WHERE asset_id = ?", (asset_id,)
                ).fetchone() is None:
                    self._write_meta(asset_id, meta, note, source, now)
                # 既にある来歴は**上書きしない**。捕獲した英訳（PNG から取り直せない値）が
                # 走査のたびに消えるのを防ぐ（点検 I5。JSON 版も同じだった）

            if old_id is not None and old_id != asset_id:
                # 中身が入れ替わった: 古い場所を外し、履歴に残す（design.md §5.1）
                old = self._con.execute(
                    "SELECT display_path, size, mtime_ns FROM asset_location WHERE path = ?",
                    (key,),
                ).fetchone()
                self._con.execute(
                    "INSERT INTO location_history(asset_id, path, size, mtime_ns,"
                    " replaced_by_asset_id, replaced_at) VALUES (?,?,?,?,?,?)",
                    (old_id, old["display_path"], old["size"], old["mtime_ns"], asset_id, now),
                )
                self._con.execute("DELETE FROM asset_location WHERE path = ?", (key,))

            if old_id == asset_id and current is not None:
                self._con.execute(
                    "UPDATE asset_location SET display_path = ?, size = ?, mtime_ns = ?,"
                    " missing_at = NULL, last_seen_at = ? WHERE path = ?",
                    (display, size, mtime_ns, now, key),
                )
            else:
                others = self._con.execute(
                    "SELECT count(*) AS n FROM asset_location WHERE asset_id = ?", (asset_id,)
                ).fetchone()["n"]
                self._con.execute(
                    "INSERT INTO asset_location(path, display_path, asset_id, size, mtime_ns,"
                    " is_primary, missing_at, last_seen_at) VALUES (?,?,?,?,?,?,NULL,?)",
                    (key, display, asset_id, size, mtime_ns, 1 if others == 0 else 0, now),
                )
        return asset_id, created

    def mark_missing(self, seen_keys: set[str], roots: list[str]) -> int:
        """走査したフォルダの下で見つからなかった場所だけを「参照切れ」にする。

        - 別のフォルダを走査しただけで、前に登録した画像を参照切れにしてはいけない
          （プロトタイプで実際に踏んだ不具合）
        - 判定は正規化した鍵と、区切り文字の単位で行う（点検 I1）
        """
        n = 0
        now = db.now()
        with self.transaction():
            rows = self._con.execute(
                "SELECT path, display_path FROM asset_location WHERE missing_at IS NULL"
            ).fetchall()
            for row in rows:
                if not any(is_under(row["display_path"], r) for r in roots):
                    continue
                if row["path"] in seen_keys:
                    continue
                self._con.execute(
                    "UPDATE asset_location SET missing_at = ? WHERE path = ?", (now, row["path"])
                )
                n += 1
        return n

    def set_roots(self, roots: list[str]) -> None:
        """根を足す。**前に入れた根は落とさない**（別のフォルダを走査しても消えない）。"""
        now = db.now()
        with self.transaction():
            for r in roots:
                display = str(Path(r))
                # 大文字小文字だけ違う再指定では、後の表示に合わせる（鍵は同じ）。
                # `added_at` は最初に入れたときのまま残す
                self._con.execute(
                    "INSERT INTO root(path, display_path, added_at) VALUES (?,?,?)"
                    " ON CONFLICT(path) DO UPDATE SET display_path = excluded.display_path",
                    (normalize_path(r), display, now),
                )

    def set_meta(self, asset_id: str, meta: dict, *, note: str | None = None,
                 source: str | None = None) -> None:
        """来歴を書き戻す。`asset()` が返す `meta` は写しなので、**これを呼ばないと消える**。

        `capture.py` は捕獲した英訳を `meta` に足す（PNG から取り直せない唯一の値。点検 I5）。
        JSON 版は同じ dict を握っていたので `save()` で書けたが、行を書く形では写しを返す。
        """
        now = db.now()
        with self.transaction():
            if self._con.execute(
                "SELECT 1 FROM asset WHERE id = ?", (asset_id,)
            ).fetchone() is None:
                raise KeyError(f"asset が無い: {asset_id}")
            if self._con.execute(
                "SELECT 1 FROM asset_meta WHERE asset_id = ?", (asset_id,)
            ).fetchone() is None:
                self._write_meta(asset_id, meta, note, source or "scan", now)
                return
            self._con.execute(
                "UPDATE asset_meta SET meta_json = ?, extracted_at = ? WHERE asset_id = ?",
                (json.dumps(meta, ensure_ascii=False), now, asset_id),
            )
            if note is not None:
                self._con.execute(
                    "UPDATE asset_meta SET note = ? WHERE asset_id = ?", (note, asset_id))
            if source is not None:
                self._con.execute(
                    "UPDATE asset_meta SET source = ? WHERE asset_id = ?", (source, asset_id))

    def set_hashes(self, asset_id: str, phash: str, dhash: str) -> None:
        """pHash / dHash を書く（P5-3）。**16 進 16 文字の小文字**だけを受ける。

        計算は `compare.py` がサムネイルを作る復号と同じ 1 回で行う（**実測 F5**:
        pHash の 11.88 ms/枚 のうち 11.35 ms が復号なので、復号を 2 回にすると費用が倍）。
        `asset()` は写しを返すので、書くにはこの口が要る。
        """
        for name, value in (("phash", phash), ("dhash", dhash)):
            if not isinstance(value, str) or len(value) != 16 or set(value) - set("0123456789abcdef"):
                raise ValueError(f"{name} は 16 進 16 文字の小文字: {value!r}")
        with self.transaction():
            if self._con.execute(
                "SELECT 1 FROM asset WHERE id = ?", (asset_id,)
            ).fetchone() is None:
                raise KeyError(f"asset が無い: {asset_id}")
            self._con.execute("UPDATE asset SET phash = ?, dhash = ? WHERE id = ?",
                              (phash, dhash, asset_id))
            # **（P8-1。設計 §0.5）帯も一緒に入れ直す。** 帯は「近い pHash を引く」ための索引で、
            # `asset.phash` と食い違うと**嘘の候補**（または取りこぼし）になる。
            # 書き手を 1 つにして、pHash を書く所は必ず帯も書く（`write_bands` が DELETE → INSERT）。
            from .duplicates import write_bands
            write_bands(self._con, asset_id, phash)

    def set_review_state(self, asset_id: str, state: str, reason_code_id: str | None = None,
                         actor: str = "human", at: str | None = None) -> None:
        """`asset.review_state` を**台帳を伴わずに**書く（休眠。点検 C4）。

        P5-1 で写しの書き手は `ReviewService`（`apply_asset` / `reconcile`）になった。
        **ここで書いた写しは、次の `ReviewService()` の `reconcile()` で消える**ので、
        アプリからは呼ばない（残っているのはテストとプロトタイプの互換のため）。

        JSON 版は `asset["review_state"] = ...; save()` と直接書けたが、写しを書き戻す形は
        台帳と現在値がずれる。`unreviewed` に戻すときは理由と日時も NULL にする
        （p5-design.md §2.1 の写しの規則）。
        """
        if state not in REVIEW_STATES:
            raise ValueError(f"review_state は {REVIEW_STATES} のいずれか: {state!r}")
        now = at or db.now()
        with self.transaction():
            if self._con.execute(
                "SELECT 1 FROM asset WHERE id = ?", (asset_id,)
            ).fetchone() is None:
                raise KeyError(f"asset が無い: {asset_id}")
            if state == "unreviewed":
                self._con.execute(
                    "UPDATE asset SET review_state = 'unreviewed', review_reason_code_id = NULL,"
                    " reviewed_at = NULL, reviewed_by = NULL WHERE id = ?",
                    (asset_id,),
                )
            else:
                self._con.execute(
                    "UPDATE asset SET review_state = ?, review_reason_code_id = ?,"
                    " reviewed_at = ?, reviewed_by = ? WHERE id = ?",
                    # 画面が "" を送ってきても FK で落ちないように NULL へ寄せる
                    (state, reason_code_id or None, now, actor, asset_id),
                )

    # ---- 中 ----

    def _fetchone(self, sql: str, args: tuple):
        with self._lock:
            return self._con.execute(sql, args).fetchone()

    def _write_meta(self, asset_id: str, meta: dict | None, note: str | None,
                    source: str, now: str) -> None:
        self._con.execute(
            "INSERT INTO asset_meta(asset_id, meta_json, note, source, extracted_at)"
            " VALUES (?,?,?,?,?)",
            (asset_id, json.dumps(meta, ensure_ascii=False), note, source, now),
        )

    def _locations(self, asset_id: str) -> list[dict]:
        with self._lock:
            rows = self._con.execute(
                "SELECT * FROM asset_location WHERE asset_id = ?"
                " ORDER BY is_primary DESC, display_path", (asset_id,)
            ).fetchall()
        return [_location_dict(r) for r in rows]

    def _meta_row(self, asset_id: str):
        return self._fetchone("SELECT * FROM asset_meta WHERE asset_id = ?", (asset_id,))

    @staticmethod
    def _asset_dict(row, locations: list[dict], meta_row) -> dict:
        meta = _parse_meta(meta_row["meta_json"]) if meta_row is not None else None
        note = meta_row["note"] if meta_row is not None else None
        source = meta_row["source"] if meta_row is not None else "scan"
        return {
            "id": row["id"],
            "sha256": row["sha256"],
            # 内容の大きさは列に無い（`db.py` の asset は場所ごとに持つ）。代表の場所から導く
            "size": locations[0]["size"] if locations else None,
            "kind": row["kind"],
            "kind_source": row["kind_source"],
            "width": row["width"],
            "height": row["height"],
            "format": row["format"],
            "source": source,
            # ここから下は JSON 版の形を保つための置き場。P5-0 では持たない列
            "source_url": None,
            "ref_tags": [],
            # P8-2（段 1 の論理削除。v6 の列）。**行は消さない**ので、ここは印をそのまま返す
            # （一覧の既定から外すのは `app.py` の側。`review.json` は外さない＝§6.3）
            "deleted_at": (row["deleted_at"] if "deleted_at" in row.keys() else None),
            "review_state": row["review_state"],
            "review_reason_code_id": row["review_reason_code_id"],
            "review_reason_id": row["review_reason_code_id"],  # 旧名（JSON 版の呼び名）
            "reviewed_at": row["reviewed_at"],
            "reviewed_by": row["reviewed_by"],
            # P5-3（v3 の列）。64bit を **16 進 16 文字の小文字**で持つ
            # （符号なし 64bit は SQLite の符号付き INTEGER に入らない）。未計算は `None`
            "phash": row["phash"],
            "dhash": row["dhash"],
            "first_seen_at": row["first_seen_at"],
            "last_seen_at": row["last_seen_at"],
            "meta": meta,
            "meta_note": note,
            "locations": locations,
        }


def _location_dict(row) -> dict:
    return {
        "key": row["path"],            # 正規化した鍵（照合に使う）
        "path": row["display_path"],   # 表示用。app.py と capture.py はこれを開く
        "display_path": row["display_path"],
        "size": row["size"],
        "mtime_ns": row["mtime_ns"],
        "is_primary": bool(row["is_primary"]),
        "missing_at": row["missing_at"],
        "last_seen_at": row["last_seen_at"],
    }


def _display_key(asset: dict) -> str:
    return asset["locations"][0]["path"].casefold() if asset["locations"] else ""


def _parse_meta(raw: str | None) -> dict | None:
    if not raw:
        return None
    try:
        parsed = json.loads(raw)
    except ValueError:
        return None
    return parsed if isinstance(parsed, dict) else None


def _count(items: list, key) -> dict:
    out: dict[str, int] = {}
    for item in items:
        k = key(item)
        if k:
            out[k] = out.get(k, 0) + 1
    return dict(sorted(out.items(), key=lambda kv: -kv[1]))
