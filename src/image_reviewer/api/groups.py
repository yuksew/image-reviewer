"""まとまりの口（P5-1）。

設計: docs/p5-design.md §3.2（まとまりの判断）

- `POST /api/groups` は `policy`（既定 `pick_one`）を受け、`source='manual'` を書く（点検 C2）
- 枚数の上限は無い（点検 B6/G8）
- `decide` / `reopen` は **`human` 以外 403**（点検 A2/A5）
"""

from __future__ import annotations

from fastapi import APIRouter, Body, Request

from . import actor_of, review_of

router = APIRouter(prefix="/api", tags=["groups"])


@router.post("/groups")
def create_group(request: Request, payload: dict = Body(default={})):
    return review_of(request).create_group(
        title=payload.get("title"),
        kind=payload.get("kind") or "manual",
        asset_ids=payload.get("asset_ids") or [],
        policy=payload.get("policy") or "pick_one",
        source=payload.get("source") or "manual",
        source_ref=payload.get("source_ref"),
    )


@router.get("/groups")
def list_groups(request: Request, state: str | None = None, limit: int = 50, cursor: int = 0,
                include_superseded: bool = False):
    """既定では、要求の差し替えで閉じたまとまり（`superseded_by`）を出さない（P6 点検 A3）。"""
    return review_of(request).list_groups(state=state, limit=limit, cursor=cursor,
                                         include_superseded=include_superseded)


@router.get("/groups/{group_id}")
def get_group(request: Request, group_id: str):
    return review_of(request).group_state(group_id)


@router.post("/groups/{group_id}/decide")
def decide_group(request: Request, group_id: str, payload: dict = Body(default={})):
    """まとまりを決める。**1 トランザクション**（枚ごとの判断 → まとまりの判断 → 写し）。"""
    return review_of(request).apply_group(
        group_id=group_id,
        items=payload.get("items") or [],
        group_reason_code_id=payload.get("group_reason_code_id"),
        note=payload.get("note"),
        actor=actor_of(request),
        client_token=payload.get("client_token"),
    )


@router.post("/groups/{group_id}/reopen")
def reopen_group(request: Request, group_id: str, payload: dict = Body(default={})):
    """`open` に戻す。**枚ごとの判断は消さない**（点検 G7）。"""
    return review_of(request).reopen(group_id, actor_of(request))
