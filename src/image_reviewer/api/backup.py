"""バックアップと健全性の口（P8-4。設計 `docs/p8-design.md` §3.3・§6.2）。

- `POST /api/backup` — **いま 1 回取る**（**人だけ**）。**同じ日でも必ず新しく取る**
- `GET  /api/backup` — 置き場・直近の一覧・最後に取った時刻・次に取る予定・**最後の失敗**
- `GET  /api/health/db` — `quick_check` / `integrity_check` と**読み取り専用かどうか**。
  **壊れているときは 503**（本文に復元の案内）
- `GET  /api/settings` / `PATCH /api/settings` — バックアップの置き場（**人だけ**が変えられる）

**`GET` は 1 バイトも書かない**（家風）。`POST /api/backup/restore` は**作らない**
（復元は CLI。点検 G8・§3.3）。守り（Host / Origin / Content-Type）は `app.py` の
middleware がアプリ全体に掛ける。
"""

from __future__ import annotations

from fastapi import APIRouter, Body, Request
from fastapi.responses import JSONResponse

from .. import db
from ..review import ReviewError
from . import actor_of, backup_of, require_human

router = APIRouter(prefix="/api", tags=["backup"])


def _flag(value) -> bool:
    """本文の真偽（**`"false"` を真にしない**。`api/deletions.py` と同じ規則）。"""
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "yes", "on")
    return value is True or value == 1


@router.post("/backup")
def backup_now(request: Request, body: dict | None = Body(default=None)):
    """**いま 1 回取る**（`{include_library: false, out?}`。**人だけ**）。

    **「いま取る」は必ず新しく取る**（`<YYYYMMDD>-<HHMMSS>/`。点検 B2）。自動の日次は
    同じ日なら増えない（`GET /api/backup` の `today_done`）。
    """
    require_human(actor_of(request), what="バックアップ")
    got = body or {}
    out = got.get("out")
    return backup_of(request).snapshot(
        manual=True,
        out=(str(out) if out else None),
        include_library=_flag(got.get("include_library")),
    )


@router.get("/backup")
def backup_state(request: Request):
    """置き場・直近の一覧・最後に取った時刻・**次に取る予定**・最後の失敗（§3.3）。**読むだけ**。"""
    actor_of(request)                       # 語彙の検査（D-5 と同じ流儀）
    return backup_of(request).state()


@router.get("/health/db")
def health_db(request: Request):
    """DB の健全性（§3.3）。**例外も「壊れている」に数える**（点検 B3）。

    - 通れば 200、壊れていれば **503**（本文に `guidance`＝復元の案内）
    - `read_only` が真なら**書き込みの口は 503**（middleware が止める）
    - `integrity_check` は `quick_check` が通ったときだけ回す（重い。設計 §0.12-5 は
      起動時 `quick_check`・日次と復元後 `integrity_check` と決めている）
    """
    store = request.app.state.store
    state = request.app.state.db_state
    got = db.quick_check(store.con)
    body: dict = {
        "ok": bool(got["ok"]),
        "quick_check": got["detail"],
        "quick_check_ok": bool(got["ok"]),
        "quick_check_error": got["error"],
        "quick_check_rows": got["rows"],
        "integrity_check": None,
        "integrity_check_note": None,
        "read_only": bool(store.read_only),
        "mode": state.get("mode"),
        "reason": state.get("reason"),
        "schema_version": state.get("schema_version"),
        "expected_version": state.get("expected_version"),
        "data_dir": str(store.data_dir),
        "guidance": state.get("guidance"),
        "checked_at": db.now(),
    }
    if got["ok"]:
        info = db.integrity(store.con)
        body["foreign_key_violations"] = info["foreign_key_violations"]
        body["journal_mode"] = info["journal_mode"]
        body["schema_version"] = info["schema_version"]
        try:
            rows = [str(row[0]) for row in
                    store.con.execute("PRAGMA integrity_check").fetchall()]
            body["integrity_check"] = rows[0] if rows else "(行が返らない)"
            if rows != ["ok"]:
                body["ok"] = False
                body["guidance"] = body["guidance"] or (
                    "DB の検査に通りませんでした。バックアップから戻すことを検討してください: "
                    "image-reviewer restore <バックアップのフォルダ>")
        except Exception as exc:                     # noqa: BLE001  結果は必ず返す
            body["ok"] = False
            body["integrity_check"] = f"例外: {exc}"
    else:
        body["integrity_check_note"] = "quick_check が通らないので integrity_check は回していません"
    # **読み取り専用で起動しているなら 503**（壊れている・版が新しい・版を上げる前の控えが
    # 取れない）。DB そのものが綺麗でも、**このアプリは書き込めない**ことを番号で示す
    # （本文に `read_only` / `mode` / `guidance` が入っているので、画面はそのまま案内できる）
    healthy = bool(body["ok"]) and not body["read_only"]
    return JSONResponse(body, status_code=200 if healthy else 503)


@router.get("/settings")
def settings_get(request: Request):
    """設定（いまは `backup_dir` だけ）。**読むだけ**。"""
    actor_of(request)
    return backup_of(request).settings()


@router.patch("/settings")
def settings_patch(request: Request, body: dict = Body(...)):
    """**バックアップの置き場を変える**（`{backup_dir}`。**人だけ**。設計 §3.3）。

    **`<data>` の中は断る**（`422 bad_backup_dir`。専門 §5.1 の注記）。
    """
    require_human(actor_of(request), what="設定の変更")
    got = body or {}
    if "backup_dir" not in got:
        raise ReviewError(422, "backup_dir がありません", code="bad_backup_dir",
                          details={"keys": sorted(got)})
    return backup_of(request).set_dir(got.get("backup_dir"), actor="human")
