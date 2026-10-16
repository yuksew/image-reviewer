"""判断の書き込み（P5-1）— 1 枚の判断とまとまりの決定の**唯一の道**。

設計: docs/p5-design.md §0.2（A2）・§0.4（B4・G7・G9）・§0.8（C11・C12）・§2.1・§3.1・§3.2・§4

守ること（どれも点検の指摘が理由）:
- **actor は `human` だけ**（点検 A2/A5）。actor の出どころ（ヘッダ）は API 層が決め、
  ここは「`human` 以外は 403」を最後の砦として必ず見る
- `asset.review_state` の書き手は**ここだけ**。写しは**同じトランザクション**で更新する（§2.1）
- 台帳は**追記のみ**。取り消しも `clear` の追記で表す。順序は `seq`（**`created_at` で選ばない**。点検 C11）
- `supersedes` は「同じ subject の直前の行」を自動で入れる（点検 C11）
- `reject` には理由が要る。存在・`active`・`applies_to` まで見る（点検 C12）
- `client_token` の再送は**行を増やさず既存を返す**。中身が違えば 409（点検 D3）
- `decided` に戻すのは**結論が変わるときだけ**（点検 B4/G9）。理由だけの変更は `decided` のまま。
  食い違いの判定は**4 つの経路**（監査 A2。設計 §0.4）: `selected` を `reject` /
  `pick_one` の `not_selected` を `keep` / `all_rejected` で 1 枚 `keep` / `selected` を `clear`
- `reopen` は**枚ごとの判断を消さない**（`clear` を書き足さない。点検 G7）
- **影響したまとまり（判断を書いた全画像が属するまとまりの和集合）の `changed_at` を、
  判断と**同じ取引**で更新する**（監査 A1。設計 §0.3 B1・B2）。書き出しの印をメモリ
  (`ExportService._pending`) だけに置くと、遅延中に落ちた時点でその判断は永久に漏れる
- 書き出しは**トランザクションの外**で遅延させる（§4。判断を 100ms 以内に返すため）
"""

from __future__ import annotations

import logging
import sqlite3
from typing import Any, Iterable, Sequence

from . import db, reasons
from .store import Store

log = logging.getLogger(__name__)

MAX_NOTE = 2000
# 監査 B1: `reconcile()` の WARNING に併記する行数の上限（263 枚を 1 行のログにしない）
MAX_LOGGED_FIXES = 20
VERDICTS = ("keep", "reject", "clear")
STATE_FOR = {"keep": "kept", "reject": "rejected", "clear": "unreviewed"}
POLICIES = ("pick_one", "pick_many", "all_reject_only")


def affected_group_ids(con: sqlite3.Connection, asset_ids: Iterable[str],
                       group_ids: Iterable[str] = ()) -> list[str]:
    """点検 B2・監査 A1: 判断を書いた**全画像**の `group_item` を引いた `group_id` の和集合。

    「影響したまとまり」の定義はここ 1 か所（点検 D5）。`ReviewService` と `ExportService` が
    同じ関数を使う。
    """
    out = set(group_ids)
    for asset_id in asset_ids:
        for got in con.execute("SELECT group_id FROM group_item WHERE asset_id = ?", (asset_id,)):
            out.add(got["group_id"])
    return sorted(out)


def _fmt_state(asset_id: str, state: tuple) -> str:
    """監査 B1: WARNING に出す 1 行（直す前 / 直した後）。"""
    return (f"{asset_id}: review_state={state[0]!r} reason={state[1]!r}"
            f" reviewed_at={state[2]!r} reviewed_by={state[3]!r}")


class ReviewError(Exception):
    """判断の規則違反。`status` は API がそのまま返す HTTP の番号。

    API 層はこの例外を 1 つのハンドラで受ける（規則を 2 か所に書かない）。
    """

    def __init__(self, status: int, detail: str, *, code: str | None = None,
                 details: dict | None = None):
        super().__init__(detail)
        self.status = status
        self.detail = detail
        self.code = code
        self.details = details or {}


class ReviewService:
    """判断の書き込み。`ReviewService(store)` で作る（起動時に写しを組み直す）。"""

    def __init__(self, store: Store, *, exporter=None, reconcile_on_start: bool = True):
        self.store = store
        # 書き出しの遅延（点検 D10）。渡されていなければ何もしない
        self.exporter = exporter
        reasons.seed(store.con)          # builtin は起動のたびに埋める（消えていても戻る）
        if reconcile_on_start:
            self.reconcile()

    # ---- 1 枚の判断（§3.1）----

    def apply_asset(self, subject_id: str, verdict: str | None, reason_code_id: str | None = None,
                    note: str | None = None, actor: str = "agent",
                    client_token: str | None = None) -> dict:
        """1 枚にキープ / ボツ / 取り消しを付ける。**台帳 → 写し → 印**を 1 取引で進める。"""
        self._require_human(actor)                                   # 点検 A2/A5
        if verdict not in VERDICTS:
            raise ReviewError(422, "verdict は keep / reject / clear のいずれかです")
        note = self._check_note(note)
        with self.store.transaction() as con:
            if con.execute("SELECT 1 FROM asset WHERE id = ?", (subject_id,)).fetchone() is None:
                raise ReviewError(404, "asset がありません", details={"asset_id": subject_id})
            reason_id = self._require_reason(con, verdict, reason_code_id,
                                            required=(verdict == "reject"))
            replay = self._replay_asset(con, client_token,
                                        self._asset_payload(subject_id, verdict, reason_id, note))
            if replay is not None:                                   # 点検 D3（行を増やさない）
                result = self._asset_result(con, subject_id, replay["decision_id"], [])
                if replay["superseded"]:                             # 監査 C6
                    result["superseded"] = True
            else:
                # 結論が変わるときだけ decided を open に戻す（点検 B4/G9）
                reopened = self._conflict_groups(con, subject_id, verdict)
                if reopened:
                    group_id = group_decision = None
                else:
                    # 理由・メモだけの変更は、前の行の group_decision を引き継ぐ（点検 B4）
                    group_id, group_decision = self._inherit_slot(con, subject_id, verdict)
                prev = self._latest_asset_decision(con, subject_id)
                decision_id = self._insert(
                    con, subject_type="asset", subject_id=subject_id, verdict=verdict,
                    reason_code_id=reason_id, note=note, actor=actor, group_id=group_id,
                    group_decision=group_decision, supersedes=prev["id"] if prev else None,
                    client_token=client_token)
                self._materialize_asset(con, subject_id)
                # 監査 A1: この枚が属する**全部**のまとまりに書き出しの印を付ける（設計 §0.3 B1・B2）。
                # メモリの `_pending` だけでは、遅延中に落ちた時点でその判断は漏れる
                self._touch_groups(con, self._affected_groups(con, [subject_id]))
                result = self._asset_result(con, subject_id, decision_id, reopened)
        self._notify(result)                                             # 取引の外（§4）
        return result

    # ---- まとまりの決定（§3.2）----

    def apply_group(self, group_id: str, items: Sequence[dict],
                    group_reason_code_id: str | None = None, note: str | None = None,
                    actor: str = "agent", client_token: str | None = None) -> dict:
        """まとまりを決める。**1 取引**で N 枚の判断＋1 件のまとまりの判断＋写しを書く。"""
        self._require_human(actor)
        note = self._check_note(note)
        with self.store.transaction() as con:
            group = con.execute("SELECT * FROM review_group WHERE id = ?", (group_id,)).fetchone()
            if group is None:
                raise ReviewError(404, "まとまりがありません", details={"group_id": group_id})
            members = [r["asset_id"] for r in con.execute(
                "SELECT asset_id FROM group_item WHERE group_id = ? ORDER BY position, asset_id",
                (group_id,))]
            checked = self._check_items(con, items, members)
            greason = self._validate_group_reason(con, group, checked, group_reason_code_id)
            replay = self._replay_group(
                con, client_token,
                self._group_payload(group_id, checked, greason, note))
            if replay is not None:
                result = self._group_result(con, group_id, replay["decision_id"], [])
                # P6-1a の監査 B3: 再送では**閉じた要求を出さない**。通常経路は UPDATE の戻り値で
                # 正確に取れるが、再送は「いまの状態」を返すだけなので `decided_at` と `closed_at` の
                # 一致で引く近似になり、同じ秒に reopen → 再 decide すると 1 つ前を拾いうる。
                # 再送で閉じた事実は無い（すでに閉じている）ので空にして、嘘を出さない
                result["closed_request_ids"] = []
                if replay["superseded"]:                             # 監査 C6
                    result["superseded"] = True
            else:
                if group["state"] == "decided":                      # 点検 C3
                    raise ReviewError(409, "決定済みのまとまりです（先に reopen してください）",
                                      code="group_decided", details={"group_id": group_id})
                result = self._decide_group(con, group, checked, greason, note, actor,
                                            client_token)
        self._notify(result)
        return result

    # ---- 取り消し（reopen。§3.2）----

    def reopen(self, group_id: str, actor: str = "agent") -> dict:
        """`decided` を `open` に戻す。**枚ごとの判断は消さない**（点検 G7）。"""
        self._require_human(actor)
        with self.store.transaction() as con:
            if con.execute("SELECT 1 FROM review_group WHERE id = ?", (group_id,)).fetchone() is None:
                raise ReviewError(404, "まとまりがありません", details={"group_id": group_id})
            self._reopen_row(con, group_id)
            result = self._group_result(con, group_id, None, [])
        self._notify(result)
        return result

    # ---- `apply()` の入口（設計 §4 の形。API はこちらを使う）----

    def apply(self, *, subject_type: str = "asset", subject_id: str | None = None,
              verdict: str | None = None, reason_code_id: str | None = None,
              note: str | None = None, actor: str = "agent", client_token: str | None = None,
              items: Sequence[dict] | None = None,
              group_reason_code_id: str | None = None) -> dict:
        if subject_type == "asset":
            if not subject_id:
                raise ReviewError(422, "subject_id が要ります")
            return self.apply_asset(subject_id, verdict, reason_code_id, note, actor, client_token)
        if subject_type == "group":
            if not subject_id:
                raise ReviewError(422, "subject_id（まとまりの id）が要ります")
            return self.apply_group(subject_id, items or [], group_reason_code_id, note, actor,
                                    client_token)
        raise ReviewError(422, "subject_type は asset だけです（まとまりは decide を使ってください）")

    # ---- 現在値の組み直し（§2.1）----

    def reconcile(self) -> int:
        """台帳から `asset.review_state` を組み直す。直した行数を返し、**必ずログに出す**。

        写しは**導出できる**ので、壊れても失われない（点検 B5-(a) の JSON ストアでは
        これができなかった）。まとまりの側は組み直さない: `reopen` は台帳に行を書かないので、
        `decision` から `state` を導くと **reopen を打ち消してしまう**（点検 G7）。

        **直した行があるときは WARNING にし、直す前の値を併記する**（監査 B1）。
        台帳に行が無い写し（`migrate-from-json` の旧経路）が黙って消えると、
        「判断は失わない」という約束が INFO 1 行で破られる。
        """
        fixed = 0
        changes: list[tuple[str, tuple, tuple]] = []
        with self.store.transaction() as con:
            rows = con.execute(
                "SELECT id, review_state, review_reason_code_id, reviewed_at, reviewed_by"
                " FROM asset ORDER BY id").fetchall()
            for got in rows:
                want = self._expected_state(con, got["id"])
                have = (got["review_state"], got["review_reason_code_id"], got["reviewed_at"],
                        got["reviewed_by"])
                if have != want:
                    con.execute(
                        "UPDATE asset SET review_state = ?, review_reason_code_id = ?,"
                        " reviewed_at = ?, reviewed_by = ? WHERE id = ?", (*want, got["id"]))
                    fixed += 1
                    if len(changes) < MAX_LOGGED_FIXES:
                        changes.append((got["id"], have, want))
        if fixed:
            log.warning(
                "現在値の写しを台帳から組み直しました: %d 行（監査 B1）。"
                " 直す前: %s / 直した後: %s%s",
                fixed,
                [_fmt_state(cid, have) for cid, have, _want in changes],
                [_fmt_state(cid, want) for cid, _have, want in changes],
                "" if fixed == len(changes) else f"（先頭 {len(changes)} 行だけ表示）")
        else:
            log.info("現在値の写しを台帳から組み直しました: 0 行（点検 C11・B5）")
        return fixed

    # ---- まとまりを作る・引く（§3.2。点検 C2・D11）----

    def create_group(self, *, title: str | None = None, kind: str = "manual",
                     asset_ids: Sequence[str] = (), policy: str = "pick_one",
                     source: str = "manual", source_ref: str | None = None) -> dict:
        """まとまりを作る。**枚数の上限は無い**（点検 B6/G8）。

        `policy` を受ける口が無いと `pick_many` の経路が死ぬ（点検 C2）。
        `source` は既定 `manual`（人が選んで作ったまとまり）で、**契約の enum だけ**を受ける
        （点検 C5。外から来た値が契約の検証を落とさないように）。
        `asset_ids` は空にしない（点検 D8。0 枚のまとまりは `all_rejected` で決定できてしまう）。
        """
        if kind not in ("manual", "request", "duplicates", "batch"):
            raise ReviewError(422, f"kind が不正です: {kind!r}")
        if policy not in POLICIES:
            raise ReviewError(422, f"policy が不正です: {policy!r}")
        # 契約 `Group.source` の enum（点検 C5。DB の CHECK は P5-2 で足す）
        if source not in ("manual", "comfyui", "watcher", "request"):
            raise ReviewError(422, f"source が不正です: {source!r}")
        if title is not None:
            if not isinstance(title, str):
                raise ReviewError(422, "title は文字列です")
            if len(title) > 200:                                       # 点検 D11
                raise ReviewError(422, "title は 200 文字までです")
            title = title or None
        # 点検 D9: 文字列を `list()` に渡すと 1 文字ずつに割れる（`missing` が読めない形になる）
        if not isinstance(asset_ids, (list, tuple)):
            raise ReviewError(422, "asset_ids は配列です")
        ids = list(asset_ids or [])
        if not ids:
            raise ReviewError(422, "asset_ids が空です（0 枚のまとまりは作れません）")   # 点検 D8
        if len(set(ids)) != len(ids):
            raise ReviewError(422, "asset_ids に同じ id が 2 回あります")
        group_id = db.ulid()
        with self.store.transaction() as con:
            unknown = [a for a in ids if con.execute(
                "SELECT 1 FROM asset WHERE id = ?", (a,)).fetchone() is None]
            if unknown:
                raise ReviewError(422, "知らない asset_id があります", details={"missing": unknown})
            self._insert_group(con, group_id=group_id, title=title, kind=kind, asset_ids=ids,
                               policy=policy, source=source, source_ref=source_ref)
            result = self._group_state(con, group_id)
        # メンバーの変更も `changed_at` を動かす（点検 B1）。印は `INSERT` で DB に入っている
        # ので（監査 A1）、ここはプロセスの遅延書き出しを起こすだけ。`_group_state` は
        # 「影響したまとまり」を持たない（API の応答の形）ので、自分を渡す
        self._notify({"affected_group_ids": [group_id]})
        return result

    def _insert_group(self, con: sqlite3.Connection, *, title: str | None, kind: str,
                      asset_ids: Sequence[str], policy: str, source: str,
                      source_ref: str | None = None, group_id: str | None = None) -> str:
        """`review_group` と `group_item` を**呼ぶ側の取引の中で**書く。

        要求（P6-1a）は「要求 1 行＋まとまり 1 行」を同じ取引で書く（設計 §4.1）ので、
        ここを `ReviewService` と `ReviewRequestService` で共有する（SQL を 2 か所に書かない）。
        """
        group_id = group_id or db.ulid()
        con.execute(
            "INSERT INTO review_group(id, title, kind, source, source_ref, policy, state,"
            " created_at, changed_at) VALUES (?,?,?,?,?,?,'open',?,?)",
            (group_id, title, kind, source, source_ref, policy, db.now(), db.stamp()))
        for position, asset_id in enumerate(asset_ids):
            con.execute("INSERT INTO group_item(group_id, asset_id, position) VALUES (?,?,?)",
                        (group_id, asset_id, position))
        return group_id

    def group_state(self, group_id: str) -> dict:
        """まとまり＋項目＋各枚の現在値（`GET /api/groups/{id}`）。"""
        with self.store.transaction() as con:
            return self._group_state(con, group_id)

    def list_groups(self, *, state: str | None = None, limit: int = 50,
                    cursor: int = 0, include_superseded: bool = False) -> dict:
        """一覧。**軽い要約**（項目の中身は `group_state` で引く）。

        `include_superseded`（点検 A3）: 要求の差し替えで閉じたまとまり
        （`superseded_by` が入っている行）は**既定で出さない**。`?include_superseded=1` で出す。
        """
        if state and state not in ("open", "decided"):
            raise ReviewError(422, "state は open / decided のいずれかです")
        where = " WHERE 1 = 1"
        args: list = []
        if state:
            where += " AND g.state = ?"
            args.append(state)
        if not include_superseded:      # 点検 A3: 差し替えで閉じたまとまりは既定で外す
            where += " AND g.superseded_by IS NULL"
        summary = ("SELECT g.*,"
                   " (SELECT count(*) FROM group_item i WHERE i.group_id = g.id) AS item_count,"
                   " (SELECT count(*) FROM group_item i JOIN asset a ON a.id = i.asset_id"
                   "    WHERE i.group_id = g.id AND a.review_state = 'kept') AS kept_count"
                   " FROM review_group g")
        with self.store.transaction() as con:
            total = con.execute(f"SELECT count(*) AS n FROM review_group g{where}",
                                args).fetchone()["n"]
            rows = con.execute(summary + where + " ORDER BY g.created_at DESC, g.id DESC"
                               " LIMIT ? OFFSET ?",
                               [*args, max(0, int(limit)), max(0, int(cursor))]).fetchall()
            labels = {r["id"]: r["label"] for r in reasons.list_all(con, include_inactive=True)}
        items = [{
            "id": r["id"], "title": r["title"], "kind": r["kind"], "source": r["source"],
            "source_ref": r["source_ref"], "policy": r["policy"], "state": r["state"],
            "decision": r["decision"] if r["state"] == "decided" else None,
            "reason_code_id": r["reason_code_id"],
            "reason_label": labels.get(r["reason_code_id"] or ""),
            "note": r["note"], "created_at": r["created_at"], "decided_at": r["decided_at"],
            "decided_by": r["decided_by"], "changed_at": r["changed_at"],
            "exported_at": r["exported_at"], "item_count": r["item_count"],
            "kept_count": r["kept_count"],
            # 差し替えで閉じた印（契約 `Group.superseded_by`。点検 A3）
            "superseded_by": r["superseded_by"],
        } for r in rows]
        nxt = cursor + limit if cursor + limit < total else None
        return {"total": total, "cursor": cursor, "limit": limit, "next_cursor": nxt,
                "items": items}

    # ---- 台帳の読み出し（`GET /api/reviews`）----

    def list_decisions(self, *, asset: str | None = None, group: str | None = None,
                       limit: int = 100, cursor: int = 0) -> dict:
        where = " WHERE 1 = 1"
        args: list = []
        if asset:
            where += " AND subject_type = 'asset' AND subject_id = ?"
            args.append(asset)
        if group:
            where += " AND group_id = ?"
            args.append(group)
        with self.store.transaction() as con:
            total = con.execute(f"SELECT count(*) AS n FROM decision{where}", args).fetchone()["n"]
            rows = con.execute("SELECT * FROM decision" + where + " ORDER BY seq DESC LIMIT ? OFFSET ?",
                               [*args, max(0, int(limit)), max(0, int(cursor))]).fetchall()
            labels = {r["id"]: r["label"] for r in reasons.list_all(con, include_inactive=True)}
        items = [{
            "id": r["id"], "seq": r["seq"], "subject_type": r["subject_type"],
            "subject_id": r["subject_id"], "group_id": r["group_id"], "verdict": r["verdict"],
            "reason_code_id": r["reason_code_id"],
            "reason_label": labels.get(r["reason_code_id"] or ""),
            "note": r["note"], "actor": r["actor"], "group_decision": r["group_decision"],
            "supersedes": r["supersedes"], "created_at": r["created_at"],
            # 点検 D6: 再送用の鍵（`client_token`）は読み出しに載せない
        } for r in rows]
        nxt = cursor + limit if cursor + limit < total else None
        return {"total": total, "cursor": cursor, "limit": limit, "next_cursor": nxt,
                "items": items}

    # ---- 理由マスタ（§3.3）----

    def add_reason_code(self, label: str, applies_to: str) -> dict:
        if not isinstance(label, str) or not label.strip():
            raise ReviewError(422, "label が要ります")
        if len(label) > 200:
            raise ReviewError(422, "label は 200 文字までです")
        if applies_to not in reasons.APPLIES_TO:
            raise ReviewError(422, "applies_to は keep / reject / both のいずれかです")
        reason_id = f"rc.user.{db.ulid()}"
        with self.store.transaction() as con:
            con.execute(
                "INSERT INTO reason_code(id, label, applies_to, position, builtin, active)"
                " VALUES (?,?,?,?,0,1)",
                (reason_id, label.strip(), applies_to, reasons.next_position(con)))
            return dict(reasons.row(con, reason_id))

    def patch_reason_code(self, reason_code_id: str, fields: dict) -> dict:
        """`label` / `position` / `active` は誰でも変えられる。`applies_to` は builtin では変えない（点検 D9）。"""
        allowed = {"label", "applies_to", "position", "active"}
        unknown = [k for k in fields if k not in allowed]
        if unknown:
            raise ReviewError(422, f"変えられない欄です: {unknown}")
        touched: list[str] = []
        with self.store.transaction() as con:
            got = reasons.row(con, reason_code_id)
            if got is None:
                raise ReviewError(404, "理由がありません", details={"reason_code_id": reason_code_id})
            assigns: list[str] = []
            args: list = []
            if "label" in fields and fields["label"] is not None:
                label = fields["label"]
                if not isinstance(label, str) or not label.strip():
                    raise ReviewError(422, "label が空です")
                assigns += ["label = ?"]
                args.append(label.strip())
            if "applies_to" in fields and fields["applies_to"] is not None:
                value = fields["applies_to"]
                if value not in reasons.APPLIES_TO:
                    raise ReviewError(422, "applies_to は keep / reject / both のいずれかです")
                if got["builtin"] and value != got["applies_to"]:
                    # builtin の意味を変えると、過去の判断の表示と食い違う（点検 D9）
                    raise ReviewError(422, "builtin の applies_to は変えられません")
                assigns += ["applies_to = ?"]
                args.append(value)
            if "position" in fields and fields["position"] is not None:
                assigns += ["position = ?"]
                args.append(int(fields["position"]))
            if "active" in fields and fields["active"] is not None:
                assigns += ["active = ?"]
                args.append(1 if fields["active"] else 0)
            if assigns:
                con.execute(f"UPDATE reason_code SET {', '.join(assigns)} WHERE id = ?",
                            (*args, reason_code_id))
            # 監査 C9: 改名は契約ファイルの `reason_label` を変える（点検 G8「書き出し時点の
            # マスタ」）。印を付けないと、次に誰かがそのまとまりに触るまで**旧名のまま**
            # 残る（実行での再現: 改名後 3 秒待っても `changed_at` 不変）。
            if assigns and "label" in fields and fields["label"] is not None:
                touched = self._groups_using_reason(con, reason_code_id)
                self._touch_groups(con, touched)
            row = dict(reasons.row(con, reason_code_id))
        self._notify({"affected_group_ids": touched})   # 取引の外で書き出しを予約（§4）
        return row

    def _groups_using_reason(self, con: sqlite3.Connection, reason_code_id: str) -> list[str]:
        """その理由を参照しているまとまり（監査 C9）。

        `groups/<id>.json` は**まとまりの結論の理由**と**属する枚の現在値の理由**の
        両方の `reason_label` を書く（`export.py:381` / `:398` / `:421`）ので、
        どちらの参照も拾う。
        """
        rows = con.execute(
            "SELECT id FROM review_group WHERE reason_code_id = ?"
            " UNION"
            " SELECT gi.group_id FROM group_item gi JOIN asset a ON a.id = gi.asset_id"
            "  WHERE a.review_reason_code_id = ?",
            (reason_code_id, reason_code_id)).fetchall()
        return sorted({r[0] for r in rows})

    # ---- 中: まとまりの決定 ----

    def _decide_group(self, con: sqlite3.Connection, group: sqlite3.Row, items: list[dict],
                      greason: str | None, note: str | None, actor: str,
                      client_token: str | None) -> dict:
        # 輸入を関数の中に置く（`review_requests` がこのモジュールを輸入するため。
        # どちらも 1 度だけ読み込まれ、以後は辞書引き）
        from . import review_requests

        now = db.now()
        keep = [i for i in items if i["verdict"] == "keep"]
        decision = "selected" if keep else "all_rejected"          # まとまりの結論
        # 枚ごとの判断（N 件）→ まとまりの判断（1 件）。同じ取引（§3.2）
        for item in items:
            slot = ("selected" if item["verdict"] == "keep"
                    else ("not_selected" if decision == "selected" else "all_rejected"))
            prev = self._latest_asset_decision(con, item["asset_id"])
            self._insert(con, subject_type="asset", subject_id=item["asset_id"],
                         verdict=item["verdict"], reason_code_id=item["reason_code_id"],
                         note=item["note"], actor=actor, group_id=group["id"],
                         group_decision=slot, supersedes=prev["id"] if prev else None,
                         created_at=now)
            self._materialize_asset(con, item["asset_id"])
        # 点検 C7: まとまりの行も同じ subject の**直前の行**を指す（reopen → 再 decide で鎖が切れない）
        prev_group = con.execute(
            "SELECT id FROM decision WHERE subject_type = 'group' AND subject_id = ?"
            " ORDER BY seq DESC LIMIT 1", (group["id"],)).fetchone()
        group_decision_id = self._insert(
            con, subject_type="group", subject_id=group["id"],
            verdict="keep" if keep else "reject", reason_code_id=greason, note=note,
            actor=actor, group_id=group["id"], group_decision=decision,
            supersedes=prev_group["id"] if prev_group else None,
            client_token=client_token, created_at=now)
        # まとまりの現在値（契約と 1 対 1。点検 C2）
        stamp = db.stamp()
        con.execute(
            "UPDATE review_group SET state = 'decided', decided_at = ?, decided_by = ?,"
            " reason_code_id = ?, decision = ?, note = ?, changed_at = ? WHERE id = ?",
            (now, actor, greason, decision, note, stamp, group["id"]))
        # 他の decided なまとまりと結論が食い違えば open に戻す（点検 B4/G9）
        reopened: list[str] = []
        for item in items:
            for gid in self._conflict_groups(con, item["asset_id"], item["verdict"]):
                if gid not in reopened:
                    reopened.append(gid)
        # P6（§0.4 / §3.7）: **同じ取引**で、このまとまりの `open` な要求を `done` にする。
        # 応答（`response`）は**閉じた時点の写し**（`reason_label` も今のマスタ。§0.2）。
        # `annotations` は入れない（読むときに導出する。§3.4）
        closed = review_requests.close_open_requests(
            con, group["id"],
            {"selected_asset_ids": [i["asset_id"] for i in keep],
             "reason_code_id": greason, "reason_label": reasons.label_of(con, greason),
             "note": note},
            now, closed_by=actor)
        # 監査 A1: 判断を書いた**全画像**が属するまとまり（自分と、同じ画像を共有する他の
        # まとまり）の印を、同じ取引の 1 つの時刻に揃える（設計 §0.3 B1・B2）
        self._touch_groups(
            con, self._affected_groups(con, [i["asset_id"] for i in items], [group["id"]]),
            stamp=stamp)
        return self._group_result(con, group["id"], group_decision_id, reopened,
                                  closed_requests=closed)

    # ---- 中: 検証 ----

    def _require_human(self, actor: str) -> None:
        """点検 A2/A5: `human` 以外は書けない。ヘッダが無ければ API が `agent` にする。"""
        if actor != "human":
            raise ReviewError(403, "判断は人が付けます", details={"actor": actor})

    def _check_note(self, note: Any) -> str | None:
        if note is None:
            return None
        if not isinstance(note, str):
            raise ReviewError(422, "note は文字列です")
        if len(note) > MAX_NOTE:
            raise ReviewError(422, f"note は {MAX_NOTE} 文字までです", details={"length": len(note)})
        return note or None

    def _require_reason(self, con: sqlite3.Connection, verdict: str,
                        reason_code_id: Any, *, required: bool = False) -> str | None:
        """理由の妥当性。**存在・active・applies_to** を見る（点検 C12）。"""
        if verdict == "clear":
            return None                       # 理由は無視して NULL に戻す（§3.1）
        rid: str | None = reason_code_id if isinstance(reason_code_id, str) else None
        rid = (rid or "").strip() or None
        if rid is None:
            if required:
                raise ReviewError(422, "ボツには理由が要ります")
            return None
        got = reasons.row(con, rid)
        if got is None:
            raise ReviewError(422, "理由がありません（reason_code_id が未知）",
                              details={"reason_code_id": rid})
        if not got["active"]:
            raise ReviewError(422, "理由が使えません（active=0）", details={"reason_code_id": rid})
        if not reasons.matches_applies_to(got["applies_to"], verdict):
            raise ReviewError(422, "理由が判断と合いません（applies_to）",
                              details={"reason_code_id": rid, "applies_to": got["applies_to"],
                                       "verdict": verdict})
        return rid

    def _check_items(self, con: sqlite3.Connection, items: Any,
                     members: list[str]) -> list[dict]:
        """枚ごとの判断。**過不足の検査**と**枚ごとの理由**が要る（§3.2）。"""
        if not isinstance(items, (list, tuple)):
            raise ReviewError(422, "items は配列です")
        seen: set[str] = set()
        out: list[dict] = []
        for raw in items:
            if not isinstance(raw, dict):
                raise ReviewError(422, "items の各項目はオブジェクトです")
            asset_id = raw.get("asset_id")
            if not asset_id:
                raise ReviewError(422, "items[].asset_id が要ります")
            if asset_id in seen:                                   # 点検 C15
                raise ReviewError(422, "items に同じ asset_id が 2 回あります",
                                  details={"duplicate": asset_id})
            seen.add(asset_id)
            verdict = raw.get("verdict")
            if verdict not in ("keep", "reject"):
                raise ReviewError(422, "items[].verdict は keep / reject のいずれかです",
                                  details={"asset_id": asset_id, "verdict": verdict})
            out.append({
                "asset_id": asset_id,
                "verdict": verdict,
                # 枚ごとに理由が要る（ボツは必須。点検 C12 も同じ口で見る）
                "reason_code_id": self._require_reason(
                    con, verdict, raw.get("reason_code_id"), required=(verdict == "reject")),
                "note": self._check_note(raw.get("note")),
            })
        known = set(members)
        missing = [a for a in members if a not in seen]
        extra = [i["asset_id"] for i in out if i["asset_id"] not in known]
        if missing or extra:
            raise ReviewError(422, "items がまとまりの全枚を過不足なく覆っていません",
                              details={"missing": missing, "extra": extra})
        return out

    def _validate_group_reason(self, con: sqlite3.Connection, group: sqlite3.Row,
                               items: list[dict], group_reason_code_id: Any) -> str | None:
        """policy の検査と、まとまり全体の理由（§3.2）。"""
        keep = [i for i in items if i["verdict"] == "keep"]
        if group["policy"] == "pick_one" and len(keep) > 1:
            raise ReviewError(422, "pick_one でキープできるのは 1 枚だけです",
                              details={"keep": [i["asset_id"] for i in keep]})
        if group["policy"] == "all_reject_only" and keep:
            raise ReviewError(422, "all_reject_only ではキープできません",
                              details={"keep": [i["asset_id"] for i in keep]})
        if not keep:
            # 全部ボツはまとまりの理由が必須（§3.2）。既定の理由は作らない（点検 G4）
            if not group_reason_code_id:
                raise ReviewError(422, "全部ボツにはまとまりの理由が要ります")
            return self._require_reason(con, "reject", group_reason_code_id, required=True)
        if group_reason_code_id:
            return self._require_reason(con, "keep", group_reason_code_id)
        # 1 枚に決めたときは、その枚のキープ理由をまとまりの理由として写す
        # （契約の実例 docs/review-export.example.json の Group.reason_code_id と同じ形）
        return keep[0]["reason_code_id"] if len(keep) == 1 else None

    # ---- 中: client_token（点検 D3・監査 C6）----

    def _replay_asset(self, con: sqlite3.Connection, client_token: str | None,
                      payload: dict) -> dict | None:
        """同じ `client_token` の再送を 200 で返す（設計 §3.1）。

        監査 C6（実行込みのやり直し）: 以前は「**その判断が今も最新**」でないと 409 に
        していたため、再送の間に同じ枚へ別の判断が入っただけで（別のタブ・エージェント）
        再送が失敗し、しかも「中身が違う」と同じコードで返っていた。設計の約束は
        「同じ `client_token` の再送 → **200**（既存を返す）」なので、**中身が同じなら
        200** に戻し、**その後に新しい判断が入っている**ことは `superseded` で伝える。
        中身が違う再送（トークンの取り違え）は今までどおり 409。
        """
        got = self._token_row(con, client_token, payload)
        if got is None:
            return None
        if self._row_payload(got) != payload:
            raise ReviewError(409, "同じ client_token で違う内容が来ました",
                              code="client_token_conflict")
        latest = self._latest_asset_decision(con, payload["subject_id"])
        return {"decision_id": got["id"],
                "superseded": latest is None or latest["id"] != got["id"]}

    def _replay_group(self, con: sqlite3.Connection, client_token: str | None,
                      payload: dict) -> dict | None:
        """まとまりの再送。1 枚と同じ規則（設計 §3.2・監査 C6）。"""
        got = self._token_row(con, client_token, payload)
        if got is None:
            return None
        if self._group_payload_from_ledger(con, got) != payload:
            raise ReviewError(409, "同じ client_token で違う内容が来ました",
                              code="client_token_conflict")
        latest = con.execute(
            "SELECT id FROM decision WHERE subject_type = 'group' AND subject_id = ?"
            " ORDER BY seq DESC LIMIT 1", (payload["subject_id"],)).fetchone()
        state = con.execute("SELECT state FROM review_group WHERE id = ?",
                            (payload["subject_id"],)).fetchone()
        superseded = (latest is None or latest["id"] != got["id"]
                      or state is None or state["state"] != "decided")
        return {"decision_id": got["id"], "superseded": superseded}

    def _token_row(self, con: sqlite3.Connection, client_token: str | None,
                   payload: dict) -> sqlite3.Row | None:
        if not client_token:
            return None
        got = con.execute("SELECT * FROM decision WHERE client_token = ?",
                          (client_token,)).fetchone()
        if got is None:
            return None
        if got["subject_type"] != payload["subject_type"] or got["subject_id"] != payload["subject_id"]:
            raise ReviewError(409, "同じ client_token で違う対象が来ました",
                              code="client_token_conflict")
        return got

    @staticmethod
    def _asset_payload(subject_id: str, verdict: str, reason_code_id: str | None,
                       note: str | None) -> dict:
        return {"subject_type": "asset", "subject_id": subject_id, "verdict": verdict,
                "reason_code_id": reason_code_id or None, "note": note or None}

    @staticmethod
    def _row_payload(row: sqlite3.Row) -> dict:
        return {"subject_type": row["subject_type"], "subject_id": row["subject_id"],
                "verdict": row["verdict"], "reason_code_id": row["reason_code_id"] or None,
                "note": row["note"] or None}

    @staticmethod
    def _group_payload(group_id: str, items: list[dict], greason: str | None,
                       note: str | None) -> dict:
        keep = [i for i in items if i["verdict"] == "keep"]
        return {
            "subject_type": "group", "subject_id": group_id,
            "verdict": "keep" if keep else "reject", "reason_code_id": greason or None,
            "note": note or None,
            "items": [{"asset_id": i["asset_id"], "verdict": i["verdict"],
                       "reason_code_id": i["reason_code_id"] or None, "note": i["note"] or None}
                      for i in sorted(items, key=lambda i: i["asset_id"])],
        }

    def _group_payload_from_ledger(self, con: sqlite3.Connection,
                                   group_row: sqlite3.Row) -> dict:
        """送り直された `client_token` の中身を**台帳から**組み立て直して比べる。

        まとまりの判断 1 行は「どの枚をどうしたか」を持たないので、
        **その行より前で、そのまとまりに付いた各枚の最新行**が、そのとき書いた枚ごとの判断。
        """
        group_id = group_row["subject_id"]
        members = [r["asset_id"] for r in con.execute(
            "SELECT asset_id FROM group_item WHERE group_id = ? ORDER BY position, asset_id",
            (group_id,))]
        items = []
        for asset_id in members:
            got = con.execute(
                "SELECT verdict, reason_code_id, note FROM decision"
                " WHERE subject_type = 'asset' AND subject_id = ? AND group_id = ? AND seq < ?"
                " AND group_decision IS NOT NULL ORDER BY seq DESC LIMIT 1",
                (asset_id, group_id, group_row["seq"])).fetchone()
            items.append({"asset_id": asset_id,
                          "verdict": got["verdict"] if got else None,
                          "reason_code_id": (got["reason_code_id"] if got else None) or None,
                          "note": (got["note"] if got else None) or None})
        return {"subject_type": "group", "subject_id": group_id,
                "verdict": group_row["verdict"], "reason_code_id": group_row["reason_code_id"] or None,
                "note": group_row["note"] or None,
                "items": sorted(items, key=lambda i: i["asset_id"])}

    # ---- 中: 台帳・写し・open 戻し ----

    def _insert(self, con: sqlite3.Connection, *, subject_type: str, subject_id: str,
                verdict: str, reason_code_id: str | None = None, note: str | None = None,
                actor: str = "human", group_id: str | None = None,
                group_decision: str | None = None, supersedes: str | None = None,
                client_token: str | None = None, created_at: str | None = None) -> str:
        """台帳に 1 行足す。`seq` は**挿入順**（点検 C11）。"""
        decision_id = db.ulid()
        con.execute(
            "INSERT INTO decision(id, seq, subject_type, subject_id, group_id, verdict,"
            " reason_code_id, note, actor, group_decision, supersedes, client_token, created_at)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (decision_id, db.next_seq(con), subject_type, subject_id, group_id, verdict,
             reason_code_id, note, actor, group_decision, supersedes, client_token,
             created_at or db.now()))
        return decision_id

    def _latest_asset_decision(self, con: sqlite3.Connection,
                               asset_id: str) -> sqlite3.Row | None:
        """「最後の判断」は `seq` で選ぶ。**`created_at` では選ばない**（点検 C11）。"""
        return con.execute(
            "SELECT * FROM decision WHERE subject_type = 'asset' AND subject_id = ?"
            " ORDER BY seq DESC LIMIT 1", (asset_id,)).fetchone()

    def _expected_state(self, con: sqlite3.Connection, asset_id: str) -> tuple:
        got = self._latest_asset_decision(con, asset_id)
        if got is None or got["verdict"] == "clear":
            return ("unreviewed", None, None, None)
        return (STATE_FOR[got["verdict"]], got["reason_code_id"], got["created_at"], got["actor"])

    def _materialize_asset(self, con: sqlite3.Connection, asset_id: str) -> None:
        """現在値の写し。**同じトランザクション**で更新する（§2.1）。"""
        con.execute(
            "UPDATE asset SET review_state = ?, review_reason_code_id = ?, reviewed_at = ?,"
            " reviewed_by = ? WHERE id = ?", (*self._expected_state(con, asset_id), asset_id))

    def _slot_for(self, con: sqlite3.Connection, asset_id: str,
                  group_id: str) -> str | None:
        """そのまとまりの中での、その枚の位置づけ（枚ごとの判断の最新行から）。"""
        got = con.execute(
            "SELECT group_decision FROM decision WHERE subject_type = 'asset'"
            " AND subject_id = ? AND group_id = ? AND group_decision IS NOT NULL"
            " ORDER BY seq DESC LIMIT 1", (asset_id, group_id)).fetchone()
        return got["group_decision"] if got else None

    @staticmethod
    def _contradicts(verdict: str, slot: str | None, policy: str) -> bool:
        """点検 B4/G9・監査 A2: **結論が変わるときだけ** open に戻す。

        「結論が変わる」4 つの経路（設計 §0.4。監査 A2 で 2 つ足した）:
        - `selected` の枚を `reject`（選んだ枚がボツになる）
        - `pick_one` で `not_selected` の枚を `keep`（選ばれる枚が入れ替わる）
        - `all_rejected` のまとまりで 1 枚を `keep`（**監査 A2-a**。
          これが無いと契約が `decision: all_rejected` と `verdict: keep` を同時に出す）
        - `selected` の枚を `clear`（**監査 A2-b**。`pick_many` で選ばれた枚が 0 になる場合も
          ここに含む。これが無いと `selected_asset_ids: [a]` と `review_state: unreviewed` が同居する）
        """
        if verdict == "clear":
            return slot == "selected"
        if slot == "selected" and verdict == "reject":
            return True
        if slot == "all_rejected" and verdict == "keep":
            return True
        if slot == "not_selected" and verdict == "keep" and policy == "pick_one":
            return True
        return False

    def _conflict_groups(self, con: sqlite3.Connection, asset_id: str,
                         verdict: str) -> list[str]:
        """その枚が属する `decided` なまとまりのうち、結論と食い違うものだけを open に戻す。"""
        reopened: list[str] = []
        rows = con.execute(
            "SELECT g.id AS id, g.policy AS policy FROM group_item gi"
            " JOIN review_group g ON g.id = gi.group_id"
            " WHERE gi.asset_id = ? AND g.state = 'decided' ORDER BY g.id", (asset_id,)).fetchall()
        for got in rows:
            if self._contradicts(verdict, self._slot_for(con, asset_id, got["id"]), got["policy"]):
                self._reopen_row(con, got["id"])
                reopened.append(got["id"])
        return reopened

    def _inherit_slot(self, con: sqlite3.Connection, asset_id: str,
                      verdict: str) -> tuple[str | None, str | None]:
        """理由だけの変更のとき、前の行の `group_decision` を引き継ぐ（点検 B4）。

        `decided` のままのまとまりで、結論と食い違わないときだけ引き継ぐ。
        """
        got = con.execute(
            "SELECT d.group_id AS group_id, d.group_decision AS group_decision,"
            " g.state AS state, g.policy AS policy FROM decision d"
            " JOIN review_group g ON g.id = d.group_id"
            " WHERE d.subject_type = 'asset' AND d.subject_id = ? AND d.group_decision IS NOT NULL"
            " ORDER BY d.seq DESC LIMIT 1", (asset_id,)).fetchone()
        if got is None or got["state"] != "decided":
            return None, None
        if self._contradicts(verdict, got["group_decision"], got["policy"]):
            return None, None
        return got["group_id"], got["group_decision"]

    def _reopen_row(self, con: sqlite3.Connection, group_id: str) -> None:
        """`open` に戻す。**`clear` の行は書かない**（枚ごとの判断を残す。点検 G7）。"""
        con.execute(
            "UPDATE review_group SET state = 'open', decided_at = NULL, decided_by = NULL,"
            " reason_code_id = NULL, decision = NULL, note = NULL, changed_at = ? WHERE id = ?",
            (db.stamp(), group_id))

    def _affected_groups(self, con: sqlite3.Connection, asset_ids: Iterable[str],
                         group_ids: Iterable[str] = ()) -> list[str]:
        """点検 B2: 判断を書いた**全画像**の `group_item` を引いた `group_id` の和集合。

        定義は `affected_group_ids()` に 1 つだけ置く（点検 D5。`ExportService` も同じ関数を使う）。
        """
        return affected_group_ids(con, asset_ids, group_ids)

    def _touch_groups(self, con: sqlite3.Connection, group_ids: Iterable[str],
                      stamp: str | None = None) -> None:
        """監査 A1: 影響したまとまりの `changed_at` を**同じ取引**で動かす（設計 §0.3 B1・B2）。

        `changed_at` は `db.stamp()`（マイクロ秒）。秒までだと、同じ秒に続けた判断が
        `changed_at > exported_at` を満たさず取りこぼされる（点検 B1-(b)）。
        """
        now = stamp or db.stamp()
        for group_id in group_ids:
            con.execute("UPDATE review_group SET changed_at = ? WHERE id = ?", (now, group_id))

    # ---- 中: 応答（現在値をそのまま返す。§3.1）----

    def _asset_state(self, con: sqlite3.Connection, asset_id: str) -> dict:
        row = con.execute(
            "SELECT id, review_state, review_reason_code_id, reviewed_at, reviewed_by"
            " FROM asset WHERE id = ?", (asset_id,)).fetchone()
        latest = self._latest_asset_decision(con, asset_id)
        return {
            "id": asset_id,
            "asset_id": asset_id,
            "review_state": row["review_state"] if row else "unreviewed",
            "verdict": None if latest is None or latest["verdict"] == "clear" else latest["verdict"],
            "reason_code_id": row["review_reason_code_id"] if row else None,
            "reason_label": reasons.label_of(con, row["review_reason_code_id"] if row else None),
            "note": latest["note"] if latest is not None else None,
            "decided_at": row["reviewed_at"] if row else None,
            "decided_by": row["reviewed_by"] if row else None,
        }

    def _asset_result(self, con: sqlite3.Connection, asset_id: str, decision_id: str | None,
                      reopened: list[str]) -> dict:
        return {
            "decision_id": decision_id,
            "asset": self._asset_state(con, asset_id),
            "reopened_group_ids": list(reopened),
            "affected_group_ids": self._affected_groups(con, [asset_id]),
        }

    def _group_result(self, con: sqlite3.Connection, group_id: str, decision_id: str | None,
                      reopened: list[str], closed_requests: list[str] | None = None) -> dict:
        from . import review_requests      # 循環を避けて関数の中で輸入（上と同じ理由）

        group = self._group_state(con, group_id)
        return {
            "decision_id": decision_id,
            "group": group,
            "items": group["items"],
            "reopened_group_ids": list(reopened),
            # P6（§3.7）: この判断で閉じた要求。再送の経路だけは `decided_at` から引く近似
            # （`close_open_requests()` の戻り値を使う通常の経路が正）
            "closed_request_ids": (list(closed_requests) if closed_requests is not None
                                   else review_requests.closed_request_ids_for_group(con, group_id)),
            "affected_group_ids": self._affected_groups(
                con, [i["asset_id"] for i in group["items"]], [group_id]),
        }

    def _group_state(self, con: sqlite3.Connection, group_id: str) -> dict:
        got = con.execute("SELECT * FROM review_group WHERE id = ?", (group_id,)).fetchone()
        if got is None:
            raise ReviewError(404, "まとまりがありません", details={"group_id": group_id})
        rows = con.execute(
            "SELECT asset_id, position FROM group_item WHERE group_id = ?"
            " ORDER BY position, asset_id", (group_id,)).fetchall()
        items = []
        selected = []
        for row in rows:
            state = self._asset_state(con, row["asset_id"])
            slot = self._slot_for(con, row["asset_id"], group_id)
            if slot == "selected":
                selected.append(row["asset_id"])
            items.append({**state, "position": row["position"], "group_decision": slot})
        decided = got["state"] == "decided"
        return {
            "id": got["id"], "title": got["title"], "kind": got["kind"],
            "source": got["source"], "source_ref": got["source_ref"], "policy": got["policy"],
            "state": got["state"],
            # open なら結論は無い（点検 B3）
            "decision": got["decision"] if decided else None,
            "selected_asset_ids": selected if decided else [],
            "reason_code_id": got["reason_code_id"],
            "reason_label": reasons.label_of(con, got["reason_code_id"]),
            "note": got["note"],
            "created_at": got["created_at"], "decided_at": got["decided_at"],
            "decided_by": got["decided_by"], "changed_at": got["changed_at"],
            "exported_at": got["exported_at"],
            # P6（点検 A3）: 要求の差し替えで閉じたまとまりの印（契約 `Group.superseded_by`）
            "superseded_by": got["superseded_by"],
            "items": items,
        }

    # ---- 中: 書き出しの遅延 ----

    def notify_export(self, group_ids: Iterable[str]) -> None:
        """書き出しの印を付ける（**取引の外**で呼ぶ）。

        要求の口（P6-1a）が使う。要求の作成・差し替え・断りは `decision` を書かないので
        `changed_at` が動かないが、`requests[]` はまとまりのファイルにも出る（設計 §6.1）
        ので、そのまとまりの書き出しを起こす必要がある。
        """
        self._notify({"affected_group_ids": list(group_ids)})

    def _notify(self, result: dict) -> None:
        if self.exporter is not None:
            self.exporter.mark(group_ids=result.get("affected_group_ids") or [])
