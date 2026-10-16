"""条件の記録の口（P7-1）。

設計: `docs/p7-design.md` §3.1（誰が呼ぶか・書くか）・§3.2（記録する）

- `GET` は**1 バイトも書かない**（§0.10）
- `POST` は**人だけ**（`human` 以外 403。判断と同じ規律）
- `client_token` の再送は **200 で既存**（同じ画像の再送は行を増やさない）
- 既存の middleware の下（`Host` / `Origin` / `Content-Type`）
"""

from __future__ import annotations

from fastapi import APIRouter, Body, Request
from fastapi.responses import JSONResponse

from ..tags import require_human                      # 人の検査は 1 か所（§0.10。P4 と同じ）
from . import actor_of, recipes_of

router = APIRouter(prefix="/api", tags=["recipes"])


@router.get("/assets/{asset_id}/recipe")
def get_recipe(request: Request, asset_id: str):
    """1 枚の記録（無ければ 404）。**書かない**。"""
    return recipes_of(request).get(asset_id)


@router.get("/recipes")
def list_recipes(request: Request, limit: int = 50, cursor: str | None = None):
    """記録の一覧（キーセット）。**書かない**。"""
    return recipes_of(request).list(limit=limit, cursor=cursor)


@router.post("/assets/{asset_id}/recipe")
def record_recipe(request: Request, asset_id: str, payload: dict = Body(default={})):
    """記録する（**人だけ**）。201 = 新しい記録、200 = 再送／既に記録がある。"""
    actor = actor_of(request)
    require_human(actor)                              # `agent` は 403（§0.10）
    got = recipes_of(request).record(
        asset_id,
        mode=payload.get("mode") or "pin_text",
        text=payload.get("text"),
        actor=actor,
        client_token=payload.get("client_token"))
    # 201 = 新しい記録、200 = 再送（`replayed`）または既存（同じ画像に 1 記録）
    return JSONResponse(got, status_code=200 if got.get("replayed") else 201)
