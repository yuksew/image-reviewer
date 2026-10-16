"""エージェントからの要求（P6-1a）。

設計: docs/p6-design.md §0.2・§0.3・§0.4・§0.9・§3.1〜§3.5・§4.1・§6.1・§8.1

守ること（どれも点検の指摘が理由）:
- **投げてすぐ返る**（§3.2。人が判断するまで待たない）。閉じるのは `decide` と**同じ取引**（§0.4）
- **一度閉じたら開かない**。`reopen` は要求の状態を戻さない（§0.4）
- **`client_token` の照合は、差し替え（UPDATE）より前**に行う（点検 B4）。後にすると、
  同じ要求の再送で**自分自身を `superseded` にして**行が増え、手元の `request_id` が死ぬ
- 差し替えるのは **`open` だけ**（`done` / `declined` / `superseded` は履歴。§0.3）
- 差し替えは **先に UPDATE（古い方）→ 後に INSERT（新しい方）**の順（§0.3。
  逆だと部分索引 `ux_request_target_open` で落ちる）
- まとまりを閉じる（`review_group.superseded_by`）のは **判断が 1 つも無いとき**だけ（§0.3 / 点検 A3）
- **`GET` は書かない**（§0.6）。読み出しは `store.locked()`（取引を開かない錠）の下で行う
- 応答（`response`）は**閉じた時点の写し**。`annotations` だけは読むときに導出する（§0.2）
- `conditions` / `wants` は**無ければ `[]`**（`null` にしない。契約が `type: array`。点検 D1）
"""

from __future__ import annotations

import base64
import binascii
import json
import re
import sqlite3
from typing import Any, Sequence

from . import db
from .review import POLICIES, ReviewError, ReviewService
from .store import Store

# 入力の上限（設計 §3.2 の表 + 同じ形の欄は同じ規則にする）
MAX_ASK = 2000                  # `ask` / `ai_note`（note と同じ長さ。§3.2）
MAX_CONDITIONS = 50             # `conditions` / `wants`（51 件以上は 422。§3.2）
MAX_TEXT = 200                  # `target_key` / `origin`（点検 D4）
MAX_DECLINE_NOTE = 2000         # 断る理由（§3.5）
MAX_TOKEN = 200                 # `client_token`
DEFAULT_LIMIT = 50
MAX_LIMIT = 200

STATES = ("open", "done", "declined", "superseded")
# `db.ulid()` の形（Cronford の base32・26 文字）。**知らない値の振り分け**にだけ使う:
# この形なら `unknown_asset_ids`、それ以外は `unknown_paths`（設計 §3.2 の表）
_ULID = re.compile(r"[0-9A-HJKMNP-TV-Z]{26}")


def _dump(value: Any) -> str:
    """保存する JSON。**鍵の順を固定**する（決定性。点検 F11 / §8.1 の 31）。"""
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _load_list(text: str | None) -> list:
    if not text:
        return []
    try:
        got = json.loads(text)
    except ValueError:                                   # 壊れた行は空にする（読めなくしない）
        return []
    return got if isinstance(got, list) else []


def annotations_of_group(con: sqlite3.Connection, group_id: str | None) -> list[str]:
    """そのまとまりの注記の id（古い順）。

    **保存値ではなく読むときに導出する**（§0.2 / 点検 B3）。判断の後に付いた印も入るので、
    読む側は「答えは不変」と決め打ちしない（契約の `ReviewRequestResponse.annotations`）。
    P6-2 で注記の口が入る前でも、この関数は表を素直に引く（行が無ければ `[]`）。
    """
    if not group_id:
        return []
    return [r["id"] for r in con.execute(
        "SELECT id FROM annotation WHERE group_id = ? ORDER BY created_at, id", (group_id,))]


def doc_of(con: sqlite3.Connection, row: sqlite3.Row) -> dict:
    """1 件を契約（`ReviewRequest`）の形にする。**API と書き出しで同じ形**（§3.3）。"""
    stored = json.loads(row["response"]) if row["response"] else None
    response = None
    if stored is not None:
        # **保存した写し**に、読むときに導出する `annotations` だけを足す（§0.2 / §3.4）。
        # 鍵の順は設計 §3.4 の例のまま（決定性）
        response = {
            "selected_asset_ids": list(stored.get("selected_asset_ids") or []),
            "reason_code_id": stored.get("reason_code_id"),
            "reason_label": stored.get("reason_label"),
            "note": stored.get("note"),
            "annotations": annotations_of_group(con, row["group_id"]),
        }
    pick, note = row["ai_pick_asset_id"], row["ai_note"]
    # P6-1b の監査（申し送り 1）: 「AI の推し: N 番」を 1 回の取得で出せるように、
    # **対象の中の何番目か**（1 始まり。まとまりの並び＝`position` 順）を添える。
    # 対象の外・対象が分からないときは `None`（画面は番号を出さない）
    pick_index = None
    if pick:
        ids = [r["asset_id"] for r in con.execute(
            "SELECT asset_id FROM group_item WHERE group_id = ? ORDER BY position, asset_id",
            (row["group_id"],))]
        if pick in ids:
            pick_index = ids.index(pick) + 1
    return {
        "id": row["id"],
        "group_id": row["group_id"],
        "state": row["state"],
        "target_key": row["target_key"],
        "actor": row["actor"],
        "ask": row["ask"],
        "conditions": _load_list(row["conditions"]),
        "origin": row["origin"],
        "wants": _load_list(row["wants"]),
        "ai": {"pick_asset_id": pick, "note": note, "pick_index": pick_index}
              if (pick or note) else None,
        "created_at": row["created_at"],
        "closed_at": row["closed_at"],
        "closed_by": row["closed_by"],
        "decline_note": row["decline_note"],
        "superseded_by": row["superseded_by"],
        "response": response,
    }


def request_docs(con: sqlite3.Connection, kind: str, target: str | None) -> list[dict]:
    """`review.json` の `requests[]`（§6.1）。**`scope` に応じて絞る**。

    - `all`: 全部（`superseded` も含む。履歴を消さない）
    - `group:<id>`: そのまとまりの要求だけ
    - `asset:<id>`: その画像を含むまとまりの要求だけ

    並びは **`created_at DESC, id DESC`** に固定する（2 回出して同一。§6.1）。
    """
    order = " ORDER BY created_at DESC, id DESC"
    if kind == "group":
        rows = con.execute("SELECT * FROM review_request WHERE group_id = ?" + order,
                           (target,)).fetchall()
    elif kind == "asset":
        rows = con.execute(
            "SELECT * FROM review_request WHERE group_id IN"
            " (SELECT group_id FROM group_item WHERE asset_id = ?)" + order, (target,)).fetchall()
    else:
        rows = con.execute("SELECT * FROM review_request" + order).fetchall()
    return [doc_of(con, row) for row in rows]


# ---- `decide` と同じ取引で呼ぶ（§0.4）----


def close_open_requests(con: sqlite3.Connection, group_id: str, response: dict,
                        closed_at: str, closed_by: str = "human") -> list[str]:
    """そのまとまりの `open` な要求を `done` にする。**呼ぶ側の取引の中で**使う（§0.4）。

    `response` は閉じた時点の写し（`reason_label` もそのときのマスタ。§0.2）。
    返すのは閉じた要求の id（判断の応答の `closed_request_ids`）。
    """
    rows = con.execute(
        "SELECT id FROM review_request WHERE group_id = ? AND state = 'open'"
        " ORDER BY created_at, id", (group_id,)).fetchall()
    if not rows:
        return []
    payload = _dump(response)
    for row in rows:
        con.execute(
            "UPDATE review_request SET state = 'done', closed_at = ?, closed_by = ?,"
            " response = ? WHERE id = ? AND state = 'open'",
            (closed_at, closed_by, payload, row["id"]))
    return [row["id"] for row in rows]


def closed_request_ids_for_group(con: sqlite3.Connection, group_id: str) -> list[str]:
    """いまの判断が閉じた要求（判断の応答 `closed_request_ids`）。

    通常は `close_open_requests()` が返した一覧をそのまま使う（別の判断の分と混ざらない）。
    ここは**再送（`client_token` の一致）**の経路だけが使う近似で、`closed_at` が
    いまの `decided_at` と同じ要求を拾う。`db.now()` は秒までなので、**同じ秒に
    reopen → 再 decide** すると 1 つ前の判断が閉じた要求を拾いうる（履歴は壊さない）。
    """
    row = con.execute("SELECT decided_at FROM review_group WHERE id = ?", (group_id,)).fetchone()
    if row is None or not row["decided_at"]:
        return []
    return [r["id"] for r in con.execute(
        "SELECT id FROM review_request WHERE group_id = ? AND state = 'done' AND closed_at = ?"
        " ORDER BY created_at, id", (group_id, row["decided_at"]))]


class ReviewRequestService:
    """要求の受付・差し替え・一覧・取得・断る（§3.2〜§3.5）。

    `decide` で閉じるのは `ReviewService` の側（同じ取引にするため）で、ここは
    「閉じる」処理を関数として渡す。**依存は一方向**（`review_requests` → `review`）。
    """

    def __init__(self, store: Store, review: ReviewService) -> None:
        self.store = store
        self.review = review

    # ---- 受付（§3.2）----

    def create(self, *, asset_ids: Sequence[str] | None = None, group_id: str | None = None,
               target_key: str | None = None, policy: str | None = None,
               ask: str | None = None, conditions: Sequence[str] | None = None,
               origin: str | None = None, wants: Sequence[str] | None = None,
               ai_pick_asset_id: str | None = None, ai_note: str | None = None,
               client_token: str | None = None, actor: str = "agent") -> dict:
        """要求を 1 件受ける。**要求 1 行＋まとまり 1 行**を同じ取引で書く（§4.1）。

        検査の順序（§3.2。点検 B4）: **対象を引く → `client_token` の照合 → 業務の検査 →
        差し替え → INSERT**。`client_token` の照合を差し替えより前に置くのは、再送で
        **自分自身を差し替えない**ため。`done` / `declined` の再送も 200 で返す。

        `policy` は **`None` なら既定（`pick_one`）**。`group_id` を指名したときは
        まとまりの設定が正で、**違う値を送ったら 422**（P6-1a の監査。黙って捨てない）。
        """
        fields: dict[str, str] = {}
        given_policy = policy
        policy = policy or "pick_one"
        if policy not in POLICIES:
            raise ReviewError(422, "policy が不正です",
                              details={"policy": "pick_one | pick_many | all_reject_only"})
        ask = self._text(ask, "ask", MAX_ASK, fields)
        origin = self._text(origin, "origin", MAX_TEXT, fields)
        target_key = self._text(target_key, "target_key", MAX_TEXT, fields)
        ai_note = self._text(ai_note, "ai_note", MAX_ASK, fields)
        conditions = self._text_list(conditions, "conditions", MAX_CONDITIONS, fields)
        wants = self._text_list(wants, "wants", MAX_CONDITIONS, fields)
        client_token = self._text(client_token, "client_token", MAX_TOKEN, fields)
        if ai_pick_asset_id is not None and not isinstance(ai_pick_asset_id, str):
            fields["ai_pick_asset_id"] = "文字列です"
        if asset_ids is not None and not isinstance(asset_ids, (list, tuple)):
            fields["asset_ids"] = "配列です"
        if fields:
            raise ReviewError(422, "入力を直してください", details={"fields": fields})
        given = [a for a in (asset_ids or []) if a not in (None, "")]
        if bool(given) == bool(group_id):
            # 両方ある / どちらも無い（設計 §3.2 の表）
            raise ReviewError(422, "どちらか一方が要ります",
                              details={"fields": {"asset_ids": "どちらか一方が要ります"}})

        payload = {"policy": policy, "target_key": target_key, "ask": ask,
                   "conditions": conditions, "origin": origin, "wants": wants,
                   "ai_pick_asset_id": ai_pick_asset_id or None, "ai_note": ai_note}
        dirty: list[str] = []
        with self.store.transaction() as con:
            group = None
            if group_id:
                group = con.execute("SELECT * FROM review_group WHERE id = ?",
                                    (group_id,)).fetchone()
                if group is None:
                    raise ReviewError(404, "まとまりがありません", details={"group_id": group_id})
                ids = [r["asset_id"] for r in con.execute(
                    "SELECT asset_id FROM group_item WHERE group_id = ? ORDER BY position, asset_id",
                    (group_id,))]
            else:
                ids = self._resolve_assets(con, given)

            # `group_id` で受けたときは `policy` を書かない（まとまりの設定が正）。再送の比較も
            # まとまりの値で行う（`_payload_of` と同じ値にする）
            payload["policy"] = group["policy"] if group is not None else policy
            # 点検 B4: **差し替えより前に**照合する。ここで返れば 1 行も増えない
            replay = self._replay(con, client_token, {**payload, "targets": sorted(ids)})
            if replay is not None:
                return replay

            if group is not None and group["state"] == "decided":
                # 点検 C2: 受けると「永久に open」の要求ができる（decide は decided に 409）
                raise ReviewError(422, "決定済みのまとまりには要求できません。reopen してから",
                                  details={"group_id": group_id})
            if group is not None and given_policy is not None and policy != group["policy"]:
                # P6-1a の監査（設計の穴 5）: `group_id` を指名したときは**まとまりの設定が正**。
                # 黙って捨てると、エージェントは自分の指定が効いたと思い込む。違えば 422 で伝える
                raise ReviewError(422, "指名したまとまりの policy と違います",
                                  details={"policy": group["policy"],
                                           "requested": policy})
            if ai_pick_asset_id and ai_pick_asset_id not in ids:
                raise ReviewError(422, "対象の画像ではありません",
                                  details={"ai_pick_asset_id": ai_pick_asset_id})

            request_id = db.ulid()
            created_at = db.now()
            superseded: str | None = None
            old = None
            if target_key:
                old = con.execute(
                    "SELECT * FROM review_request WHERE target_key = ? AND state = 'open'",
                    (target_key,)).fetchone()
            if group is None:
                # `title` は `ask` から取る（200 文字まで。長いときは入れない）。
                # 設計に指定が無い欄なので、**切り詰めずに落とす**（嘘の題にしない）
                title = ask if ask and len(ask) <= MAX_TEXT else None
                gid = self.review._insert_group(con, title=title, kind="request", asset_ids=ids,
                                                policy=policy, source="request",
                                                source_ref=request_id)
                dirty.append(gid)
            else:
                gid = group_id
                # 点検 B1（P6-1a の監査 A1/B1）: **既存のまとまりを指名したときも**、そのファイルの
                # `requests[]` を書き直す対象にする（新しい要求が載らないと、ファイルと API が食い違う）
                dirty.append(gid)
            if old is not None:
                # **先に UPDATE、後に INSERT**（§0.3）。順序を逆にすると部分索引
                # `ux_request_target_open` で落ちる（`open` が 2 本になる瞬間ができる）
                con.execute("UPDATE review_request SET state = 'superseded', superseded_by = ?"
                            " WHERE id = ? AND state = 'open'", (request_id, old["id"]))
                superseded = old["id"]
                old_group = old["group_id"]
                if old_group and old_group != gid and self._no_decisions(con, old_group):
                    # 判断が 1 つも無い古いまとまりだけ閉じる（§0.3 / 点検 A3）。
                    # `changed_at` も動かす（書き出しの印。§0.3 B1）
                    con.execute("UPDATE review_group SET superseded_by = ?, changed_at = ?"
                                " WHERE id = ?", (request_id, db.stamp(), old_group))
                    dirty.append(old_group)
            con.execute(
                "INSERT INTO review_request(id, group_id, target_key, state, ask, conditions,"
                " origin, wants, ai_pick_asset_id, ai_note, actor, created_at, client_token)"
                " VALUES (?,?,?,'open',?,?,?,?,?,?,?,?,?)",
                (request_id, gid, target_key, ask, _dump(conditions) if conditions else None,
                 origin, _dump(wants) if wants else None, ai_pick_asset_id or None, ai_note,
                 actor, created_at, client_token))
        self.review.notify_export(dirty)
        result = {"request_id": request_id, "group_id": gid, "state": "open", "replayed": False}
        if superseded:
            result["superseded_request_id"] = superseded
        return result

    # ---- 一覧（§3.3）----

    def list(self, *, state: str | None = "open", target_key: str | None = None,
             group_id: str | None = None, limit: int = DEFAULT_LIMIT, cursor: str | None = None,
             count_only: bool = False) -> dict:
        """新しい順（`created_at DESC, id DESC` のキーセット）。**書かない**（§0.6）。

        `group_id` で**まとまりの要求だけ**に絞れる（P6-1b の監査・申し送り 3。まとまりレビューの
        画面が「open を 200 件取って突き合わせる」のをやめられる）。
        """
        state = state or "open"
        if state not in STATES + ("all",):
            raise ReviewError(422, "state は open / done / declined / superseded / all のいずれかです",
                              details={"state": state})
        limit = max(1, min(int(limit or DEFAULT_LIMIT), MAX_LIMIT))
        after = self._parse_cursor(cursor)
        where, args = " WHERE 1 = 1", []
        if state != "all":
            where += " AND state = ?"
            args.append(state)
        if target_key:
            where += " AND target_key = ?"
            args.append(target_key)
        if group_id:
            where += " AND group_id = ?"
            args.append(group_id)
        if after is not None:
            where += " AND (created_at < ? OR (created_at = ? AND id < ?))"
            args += [after[0], after[0], after[1]]
        with self.store.locked() as con:
            # バーの件数とタブのタイトルが使う（§5.4）。**絞り込みに関係なく open の数**
            counts = {"open": con.execute(
                "SELECT count(*) AS n FROM review_request WHERE state = 'open'").fetchone()["n"]}
            if count_only:
                return {"items": [], "next_cursor": None, "counts": counts}
            rows = con.execute("SELECT * FROM review_request" + where
                               + " ORDER BY created_at DESC, id DESC LIMIT ?",
                               [*args, limit + 1]).fetchall()
            more = len(rows) > limit
            rows = rows[:limit]
            items = [doc_of(con, row) for row in rows]
        return {"items": items, "next_cursor": self._cursor_of(rows[-1]) if (more and rows) else None,
                "counts": counts}

    def get(self, request_id: str) -> dict:
        """1 件（エージェントのポーリング。§3.4）。**書かない**。"""
        with self.store.locked() as con:
            row = con.execute("SELECT * FROM review_request WHERE id = ?",
                              (request_id,)).fetchone()
            if row is None:
                raise ReviewError(404, "要求がありません", details={"request_id": request_id})
            return doc_of(con, row)

    # ---- 断る（§3.5）----

    def decline(self, request_id: str, note: Any, actor: str = "agent") -> dict:
        """人が断る。**理由が要る**。同じ理由の再送は 200（点検 B5。`client_token` は取らない）。"""
        if actor != "human":
            raise ReviewError(403, "要求を断れるのは人だけです", details={"actor": actor})
        if not isinstance(note, str) or not note.strip():
            raise ReviewError(422, "断る理由が要ります", details={"fields": {"note": "断る理由が要ります"}})
        if len(note) > MAX_DECLINE_NOTE:
            raise ReviewError(422, f"断る理由は {MAX_DECLINE_NOTE} 文字までです",
                              details={"fields": {"note": f"{MAX_DECLINE_NOTE} 文字までです"}})
        with self.store.transaction() as con:
            row = con.execute("SELECT * FROM review_request WHERE id = ?",
                              (request_id,)).fetchone()
            if row is None:
                raise ReviewError(404, "要求がありません", details={"request_id": request_id})
            if row["state"] == "declined" and row["decline_note"] == note:
                return {"id": request_id, "state": "declined", "decline_note": note}
            if row["state"] != "open":
                raise ReviewError(409, "開いている要求ではありません", code="request_not_open",
                                  details={"state": row["state"]})
            con.execute("UPDATE review_request SET state = 'declined', closed_at = ?,"
                        " closed_by = ?, decline_note = ? WHERE id = ?",
                        (db.now(), actor, note, request_id))
            group_id = row["group_id"]
        # まとまりの書き出し（`requests[]`）を更新する。判断ではないので `changed_at` は触らない
        self.review.notify_export([group_id])
        return {"id": request_id, "state": "declined", "decline_note": note}

    # ---- 中: 検証と道具 ----

    def _resolve_assets(self, con: sqlite3.Connection, given: Sequence[str]) -> list[str]:
        """`asset_ids` を解決する。**id でもパスでも**受ける（§0.10 / 点検 C1）。

        パスは `store.location_of()` を通す（`normalize_path()` で大小文字・区切りを揃える。
        点検 I1）。知らない値は**形で振り分ける**（26 文字の ULID 形 → `unknown_asset_ids`、
        それ以外 → `unknown_paths`）。同じ画像に 2 通りの書き方が来たら 1 つに畳む。
        """
        ids: list[str] = []
        unknown_ids: list[str] = []
        unknown_paths: list[str] = []
        for raw in given:
            if not isinstance(raw, str) or not raw:
                raise ReviewError(422, "asset_ids は文字列の配列です",
                                  details={"fields": {"asset_ids": repr(raw)}})
            found = raw if con.execute("SELECT 1 FROM asset WHERE id = ?",
                                       (raw,)).fetchone() is not None else None
            if found is None:
                loc = self.store.location_of(raw)
                found = loc["asset_id"] if loc is not None else None
            if found is None:
                (unknown_ids if _ULID.fullmatch(raw) else unknown_paths).append(raw)
            elif found not in ids:
                ids.append(found)
        if unknown_ids or unknown_paths:
            details: dict = {}
            if unknown_ids:
                details["unknown_asset_ids"] = unknown_ids
            if unknown_paths:
                details["unknown_paths"] = unknown_paths
            raise ReviewError(422, "知らない画像があります", details=details)
        return ids

    def _replay(self, con: sqlite3.Connection, client_token: str | None, payload: dict) -> dict | None:
        """同じ `client_token` の再送（§0.9）。

        中身は**対象の集合**（`targets`）と自由文で比べる。`asset_ids` を id で送った場合と
        パスで送った場合、`group_id` で送った場合が同じ対象なら同じ再送として扱う
        （`group_item` から引くので、どちらの書き方でも同じ集合になる）。
        """
        if not client_token:
            return None
        row = con.execute("SELECT * FROM review_request WHERE client_token = ?",
                          (client_token,)).fetchone()
        if row is None:
            return None
        if _dump(self._payload_of(con, row)) != _dump(payload):
            raise ReviewError(409, "同じ client_token で違う内容が来ました",
                              code="client_token_conflict",
                              details={"client_token": client_token})
        return {"request_id": row["id"], "group_id": row["group_id"], "state": row["state"],
                "replayed": True}

    @staticmethod
    def _payload_of(con: sqlite3.Connection, row: sqlite3.Row) -> dict:
        """保存した行から、再送の比較に使う中身を作る（書き込みと 1 対 1）。"""
        ids = [r["asset_id"] for r in con.execute(
            "SELECT asset_id FROM group_item WHERE group_id = ? ORDER BY position, asset_id",
            (row["group_id"],))]
        # `policy` はまとまりの列（要求の行には無い）。`group_id` で受けた要求は
        # **まとまりの `policy` をそのまま使う**ので、送った `policy` は効かない
        got = con.execute("SELECT policy FROM review_group WHERE id = ?",
                          (row["group_id"],)).fetchone()
        return {"policy": got["policy"] if got is not None else None,
                "target_key": row["target_key"], "ask": row["ask"],
                "conditions": _load_list(row["conditions"]), "origin": row["origin"],
                "wants": _load_list(row["wants"]),
                "ai_pick_asset_id": row["ai_pick_asset_id"], "ai_note": row["ai_note"],
                "targets": sorted(ids)}

    def _no_decisions(self, con: sqlite3.Connection, group_id: str) -> bool:
        """そのまとまりに**このレビューの判断**が 1 つも無い（P6-1a の監査 B2）。

        以前は「所属する画像が判断済みか」まで見ていたので、**別のまとまりや 1 枚の判断で
        決まっている画像**があると「判断が無い」と言えず、差し替えで閉じるべき古いまとまりが
        既定の一覧に残った（点検 A3 の趣旨が崩れる）。ここは **`decision.group_id` が
        このまとまりを指す行**だけを見る（＝このまとまりをレビューした記録）。
        """
        got = con.execute(
            "SELECT 1 FROM decision WHERE group_id = ? LIMIT 1", (group_id,)).fetchone()
        return got is None

    @staticmethod
    def _text(value: Any, name: str, limit: int, fields: dict[str, str]) -> str | None:
        """自由文の欄。**上限を超えたら 422**（設計 §3.2。空文字は `None` にする）。"""
        if value is None:
            return None
        if not isinstance(value, str):
            fields[name] = "文字列です"
            return None
        if len(value) > limit:
            fields[name] = f"{limit} 文字までです（{len(value)} 文字）"
            return None
        return value or None

    @staticmethod
    def _text_list(value: Any, name: str, limit: int, fields: dict[str, str]) -> list[str]:
        """文字列の配列。**語彙は検査しない**（エージェントの拡張を弾かない。§0.10）。"""
        if value is None:
            return []
        if not isinstance(value, (list, tuple)):
            fields[name] = "配列です"
            return []
        if len(value) > limit:
            fields[name] = f"{limit} 件までです（{len(value)} 件）"
            return []
        out = []
        for item in value:
            if not isinstance(item, str):
                fields[name] = "文字列の配列です"
                return []
            out.append(item)
        return out

    @staticmethod
    def _cursor_of(row: sqlite3.Row) -> str:
        """カーソルは `created_at|id` を base64 した**不透明な文字列**（中身を仕様にしない。§3.3）。"""
        raw = f"{row['created_at']}|{row['id']}".encode("utf-8")
        return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")

    @staticmethod
    def _parse_cursor(cursor: Any) -> tuple[str, str] | None:
        if not cursor:
            return None
        if not isinstance(cursor, str):
            raise ReviewError(422, "cursor が不正です", details={"cursor": repr(cursor)})
        try:
            raw = base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4)).decode("utf-8")
        except (binascii.Error, UnicodeDecodeError, ValueError):
            raise ReviewError(422, "cursor が不正です", details={"cursor": cursor}) from None
        created_at, _, request_id = raw.partition("|")
        if not created_at or not request_id:
            raise ReviewError(422, "cursor が不正です", details={"cursor": cursor})
        return created_at, request_id


__all__ = ["ReviewRequestService", "annotations_of_group", "close_open_requests",
           "closed_request_ids_for_group", "doc_of", "request_docs"]
