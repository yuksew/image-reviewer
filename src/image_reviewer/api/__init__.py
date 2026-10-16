"""P5-1 のルーター（`app.py` の閉包から出す。点検 C13）。

設計: docs/p5-design.md §3・§9

- `store` は `app.state` から取る（閉包で掴まない）
- **actor はヘッダ `X-Image-Reviewer-Actor` だけから取る。本文の `actor` は見ない。**
  無ければ `agent` として扱い、`ReviewService` が 403 にする（点検 A2）
- `ReviewError` は 1 つのハンドラで HTTP に写す（規則を 2 か所に書かない）
"""

from __future__ import annotations

from fastapi import Request
from fastapi.responses import JSONResponse

from ..annotations import AnnotationService
from ..export import ExportService
from ..review import ReviewError, ReviewService
from ..review_requests import ReviewRequestService
from ..store import Store

ACTOR_HEADER = "X-Image-Reviewer-Actor"


def review_of(request: Request) -> ReviewService:
    return request.app.state.review


def requests_of(request: Request) -> ReviewRequestService:
    """要求の口（P6-1a）。`app.state` から取る（閉包で掴まない）。"""
    return request.app.state.requests


def store_of(request: Request) -> Store:
    """比較（P5-2）が使う。読み出しだけ（書き込みは `ReviewService` を通す）。"""
    return request.app.state.store


def export_of(request: Request) -> ExportService:
    return request.app.state.export


def annotations_of(request: Request) -> AnnotationService:
    """注記の口（P6-2）。`app.state` から取る（閉包で掴まない）。"""
    return request.app.state.annotations


def jobs_of(request: Request):
    """タグ付けの背景ジョブ（P4-1）。`app.state` から取る（閉包で掴まない）。"""
    return request.app.state.jobs


def gloss_of(request: Request):
    """語釈（P4-2）。`app.state` から取る（閉包で掴まない）。"""
    return request.app.state.gloss


def recipes_of(request: Request):
    """条件の記録（P7-1）。`app.state` から取る（閉包で掴まない）。"""
    return request.app.state.recipes


def recipe_exports_of(request: Request):
    """書き出し（P7-2）。`app.state` から取る（閉包で掴まない）。"""
    return request.app.state.recipe_exports


def actor_of(request: Request) -> str:
    """点検 A2: actor は**ヘッダだけ**から取る。無ければ `agent`（＝判断は 403）。

    P6-1a の監査 A1: `human` / `agent` 以外は **422**。以前はそのまま `review_request.actor` /
    `annotation.actor` に入り、表の `CHECK` に当たって **500**（ログに `IntegrityError`）になっていた。
    """
    got = (request.headers.get(ACTOR_HEADER) or "").strip()
    if not got:
        return "agent"
    if got not in ("human", "agent"):
        raise ReviewError(422, "actor は human / agent のいずれかです", details={"actor": got})
    return got


def review_error_handler(request: Request, exc: ReviewError) -> JSONResponse:
    """`ReviewError` → JSON。`details` と `code` を落とさない（`missing` / `extra` / `group_decided`）。"""
    body: dict = {"detail": exc.detail}
    if exc.code:
        body["code"] = exc.code
    if exc.details:
        body["details"] = exc.details
    return JSONResponse(body, status_code=exc.status)
