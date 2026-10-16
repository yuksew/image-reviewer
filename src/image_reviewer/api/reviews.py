"""判断と理由マスタの口（P5-1）。

設計: docs/p5-design.md §3.1（1 枚の判断）・§3.3（理由マスタ）
"""

from __future__ import annotations

from fastapi import APIRouter, Body, Request

from .. import reasons
from ..review import ReviewError
from . import actor_of, review_of

router = APIRouter(prefix="/api", tags=["reviews"])


@router.post("/reviews")
def post_review(request: Request, payload: dict = Body(default={})):
    """1 枚の判断。**本文の `actor` は無視する**（点検 A2。ヘッダだけを見る）。"""
    review = review_of(request)
    subject_type = payload.get("subject_type") or "asset"
    if subject_type != "asset":
        # まとまりは decide を使う（§3.1）
        raise ReviewError(422, "まとまりは /api/groups/{id}/decide を使ってください")
    subject_id = payload.get("subject_id")
    if not subject_id:
        raise ReviewError(422, "subject_id が要ります")
    return review.apply_asset(
        subject_id=subject_id,
        verdict=payload.get("verdict"),
        reason_code_id=payload.get("reason_code_id"),
        note=payload.get("note"),
        actor=actor_of(request),
        client_token=payload.get("client_token"),
    )


@router.get("/reviews")
def list_reviews(request: Request, asset: str | None = None, group: str | None = None,
                 limit: int = 100, cursor: int = 0):
    """台帳（追記のみ）を新しい順に返す。"""
    return review_of(request).list_decisions(asset=asset, group=group, limit=limit, cursor=cursor)


@router.get("/reason-codes")
def list_reason_codes(request: Request, applies_to: str | None = None,
                      include_inactive: bool = False):
    if applies_to and applies_to not in reasons.APPLIES_TO:
        raise ReviewError(422, "applies_to は keep / reject / both のいずれかです")
    return {"items": reasons.list_all(review_of(request).store.con, applies_to=applies_to,
                                      include_inactive=include_inactive)}


@router.post("/reason-codes")
def create_reason_code(request: Request, payload: dict = Body(default={})):
    return review_of(request).add_reason_code(payload.get("label") or "",
                                              payload.get("applies_to") or "")


@router.patch("/reason-codes/{reason_code_id}")
def patch_reason_code(request: Request, reason_code_id: str, payload: dict = Body(default={})):
    return review_of(request).patch_reason_code(reason_code_id, payload or {})
