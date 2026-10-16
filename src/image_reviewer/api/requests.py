"""エージェントからの要求の口（P6-1a）。

設計: docs/p6-design.md §3.1（口の一覧）・§3.2（受付）・§3.3（一覧）・§3.4（取得）・§3.5（断る）

- `POST` は **`actor` を要求しない**（エージェントが投げる口。§3.1）
- `decline` は **`human` 以外 403**（サービスが最後の砦。§3.5）
- 作成の応答は **201**（再送は **200** で `replayed: true`）。番号が中身で変わるので
  `JSONResponse` を直に返す
- `GET` は**書かない**（§0.6）
"""

from __future__ import annotations

from fastapi import APIRouter, Body, Request
from fastapi.responses import JSONResponse

from . import actor_of, requests_of

router = APIRouter(prefix="/api/review-requests", tags=["requests"])


@router.post("")
def create_request(request: Request, payload: dict = Body(default={})):
    """要求を投げる。**投げてすぐ返る**（判断は待たない。§3.2）。"""
    got = requests_of(request).create(
        asset_ids=payload.get("asset_ids"),
        group_id=payload.get("group_id"),
        target_key=payload.get("target_key"),
        policy=payload.get("policy"),
        ask=payload.get("ask"),
        conditions=payload.get("conditions"),
        origin=payload.get("origin"),
        wants=payload.get("wants"),
        ai_pick_asset_id=payload.get("ai_pick_asset_id"),
        ai_note=payload.get("ai_note"),
        client_token=payload.get("client_token"),
        actor=actor_of(request),
    )
    # 201 = 新しい要求、200 = 同じ `client_token` の再送（§3.2。点検 B4）
    return JSONResponse(got, status_code=200 if got.get("replayed") else 201)


@router.get("")
def list_requests(request: Request, state: str = "open", target_key: str | None = None,
                  group_id: str | None = None, limit: int = 50, cursor: str | None = None,
                  count_only: bool = False):
    """既定は `open` だけ、新しい順（§3.3）。`cursor` は不透明な文字列。"""
    return requests_of(request).list(state=state, target_key=target_key, group_id=group_id,
                                     limit=limit, cursor=cursor, count_only=count_only)


@router.get("/{request_id}")
def get_request(request: Request, request_id: str):
    """1 件。エージェントはこれを見て `state` が `open` でなくなるまで待つ（§3.4）。"""
    return requests_of(request).get(request_id)


@router.post("/{request_id}/decline")
def decline_request(request: Request, request_id: str, payload: dict = Body(default={})):
    """人が断る。理由（`note`）が要る（§3.5）。"""
    return requests_of(request).decline(request_id, payload.get("note"), actor=actor_of(request))
