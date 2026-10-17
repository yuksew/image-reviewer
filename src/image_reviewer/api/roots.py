"""置き場（`root`）の口（P8-4。設計 §3.3・Q8・点検 B7・G-3）。

- `GET  /api/roots` — 登録した置き場と**「段 3 を許す印」**の一覧（**読むだけ**）
- `POST /api/roots/{id}/allow-stage3` — その印を立てる／外す（**人だけ**）

`{id}` は `root.path`（**正規化した鍵**）か、登録した表示のパス。印は**利用者の明示の
意思表示**として扱い、**印の無い置き場では段 3（実ファイルの削除）ができない**
（`409 stage_not_allowed`。既定は印なし＝安全側）。

**（G-3）この口は P8-4 に回された**（P8-2 の監査 E-5）。`scan` で新しく増えた置き場は
**印なしで入る**ので、増えた置き場で段 3 を使いたいときはここで印を立てる。
"""

from __future__ import annotations

from fastapi import APIRouter, Body, Request

from ..review import ReviewError
from . import actor_of, deletions_of, require_human

router = APIRouter(prefix="/api", tags=["roots"])


def _flag(value) -> bool:
    """本文の真偽（**`"false"` を真にしない**。`api/deletions.py` と同じ規則）。"""
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "yes", "on")
    return value is True or value == 1


@router.get("/roots")
def roots_list(request: Request):
    """登録した置き場の一覧（`id` は正規化した鍵。`allow_stage3` つき）。**読むだけ**。"""
    actor = actor_of(request)
    return {"roots": deletions_of(request).roots(actor=actor)}


@router.post("/roots/{root_id:path}/allow-stage3")
def roots_allow_stage3(request: Request, root_id: str, body: dict = Body(...)):
    """その置き場で**段 3 を許す印**を立てる（`{allow: true}`。**人だけ**。Q8）。

    `allow` が本文に無ければ **422**（既定で立てない。**安全側**）。
    """
    require_human(actor_of(request), what="段 3 を許す印")
    got = body or {}
    if "allow" not in got:
        raise ReviewError(422, "allow がありません（true で許す・false で外す）",
                          code="bad_allow", details={"keys": sorted(got)})
    return deletions_of(request).set_allow_stage3(
        root_id, allow=_flag(got.get("allow")), actor="human")
