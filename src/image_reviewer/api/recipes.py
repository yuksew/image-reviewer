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
from . import actor_of, recipe_exports_of, recipes_of, watcher_of

router = APIRouter(prefix="/api", tags=["recipes"])


@router.get("/assets/{asset_id}/recipe")
def get_recipe(request: Request, asset_id: str):
    """1 枚の記録（無ければ 404）。**書かない**。"""
    return recipes_of(request).get(asset_id)


@router.get("/recipes")
def list_recipes(request: Request, limit: int = 50, cursor: str | None = None,
                 status: str | None = None):
    """記録の一覧（キーセット）。**書かない**。`status` で判定を絞れる（P7-4）。"""
    return recipes_of(request).list(limit=limit, cursor=cursor, status=status)


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


# ---- P7-2: 書き出し ----


@router.post("/recipes/{recipe_id}/check")
def check_recipe(request: Request, recipe_id: str):
    """**書き出す前の検査**（§0.8）。**1 バイトも書かない**（ComfyUI に聞くだけ）。"""
    return recipe_exports_of(request).check(recipe_id)


@router.get("/recipes/{recipe_id}/exports")
def list_exports(request: Request, recipe_id: str):
    """書き出しの一覧（束ごと）。**書かない**。"""
    return recipe_exports_of(request).exports(recipe_id)


@router.post("/recipes/{recipe_id}/export")
def export_recipe(request: Request, recipe_id: str, payload: dict = Body(default={})):
    """書き出す（**人だけ**）。201 = 新しい束、200 = `client_token` の再送（**同じ `attempt_id`**）。"""
    actor = actor_of(request)
    require_human(actor)                              # `agent` は 403（§0.10）
    got = recipe_exports_of(request).export(
        recipe_id,
        mode=payload.get("mode"),
        seeds=payload.get("seeds"),
        count=payload.get("count"),
        marker=bool(payload.get("marker", True)),
        actor=actor,
        client_token=payload.get("client_token"))
    return JSONResponse(got, status_code=200 if got.get("replayed") else 201)


# ---- P7-3: 手で紐付ける口と合否 ----


@router.post("/recipes/{recipe_id}/exports/{attempt_id}/results")
def attach_result(request: Request, recipe_id: str, attempt_id: str, payload: dict = Body(default={})):
    """印が無い結果を**人が紐付ける**（§3.6。**人だけ**）。200 = 既にある／再送。"""
    actor = actor_of(request)
    require_human(actor)                              # `agent` は 403（§0.10）
    got = watcher_of(request).attach(
        recipe_id, attempt_id, str(payload.get("result_asset_id") or ""),
        actor=actor, client_token=payload.get("client_token"))
    return JSONResponse(got, status_code=200 if got.get("replayed") else 201)


@router.post("/recipes/{recipe_id}/exports/{attempt_id}/results/{result_id}/verdict")
def set_verdict(request: Request, recipe_id: str, attempt_id: str, result_id: str,
                payload: dict = Body(default={})):
    """合否を記録する（§3.6。**人だけ**・**上書き**＋`verdict_at` / `verdict_actor`）。"""
    actor = actor_of(request)
    require_human(actor)
    return watcher_of(request).set_verdict(
        recipe_id, attempt_id, result_id, str(payload.get("verdict") or ""),
        note=payload.get("note"), actor=actor)
