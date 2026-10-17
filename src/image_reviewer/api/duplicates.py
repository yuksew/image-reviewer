"""重複の口（P8-1）。

設計: `docs/p8-design.md` §3.1（重複の 6 つの口）・§0.5（pHash は `GET` では計算しない）・
      §0.9（代表の推薦）・§0.10（除外と解除）

- `GET /api/duplicates/exact` — 完全重複（この環境では 0 群。**空のときは 1 行で説明する**）
- `POST /api/duplicates/compute` — **人だけ**。足りない pHash を計算する**背景ジョブ**（202）
- `GET /api/duplicates/near` — 準重複の群（`max_distance` 既定 6。**計算しない**。`unhashed` を返す）
- `POST /api/duplicates/exclude` — **人だけ**。「別物として確定」（解除できる）
- `POST /api/duplicates/exclude/remove` — **人だけ**。**解除**（`DELETE` に本文を持たせない。§0.15 の 1）
- `GET /api/duplicates/exclusions` — 除外の一覧（`GET` は書かない）

守り（Host / Origin / Content-Type）は `app.py` の middleware がアプリ全体に掛ける。
`actor` はヘッダ（`human` / `agent`）。**計算・除外は人だけ**（`require_human`）。
"""

from __future__ import annotations

from fastapi import APIRouter, Body, Request

from ..review import ReviewError
from . import actor_of, duplicates_of, require_human

router = APIRouter(prefix="/api", tags=["duplicates"])


@router.get("/duplicates/exact")
def duplicates_exact(request: Request):
    """完全重複（2 か所以上に登録されている画像）。**計算しない**。"""
    return duplicates_of(request).exact()


@router.get("/duplicates/near")
def duplicates_near(request: Request, max_distance: int = 6, limit: int | None = None):
    """準重複の群。**`GET` は 1 バイトも書かない**（pHash の計算は `POST …/compute`）。"""
    return duplicates_of(request).near(max_distance=max_distance, limit=limit)


@router.post("/duplicates/compute", status_code=202)
def duplicates_compute(request: Request, body: dict | None = Body(default=None)):
    """足りない pHash を計算する**背景ジョブ**を始める（**202** で job を返す）。

    **人だけ**（重い計算を投げる口なので）。`force: true` で全部やり直す。
    """
    require_human(actor_of(request))
    got = body or {}
    return duplicates_of(request).start_compute(force=bool(got.get("force")))


@router.post("/duplicates/exclude")
def duplicates_exclude(request: Request, body: dict = Body(...)):
    """「別物として確定」する（**人だけ**。**解除できる**）。"""
    actor = require_human(actor_of(request))
    return duplicates_of(request).exclude(
        a_id=str(body.get("a_id") or ""), b_id=str(body.get("b_id") or ""),
        reason=(str(body["reason"]) if body.get("reason") is not None else None), actor=actor)


@router.post("/duplicates/exclude/remove")
def duplicates_exclude_remove(request: Request, body: dict = Body(...)):
    """**除外の解除**（必須。専門 §3.1 の点検 C10）。**`DELETE` に本文を持たせない**。"""
    require_human(actor_of(request))
    return duplicates_of(request).remove_exclusion(
        a_id=str(body.get("a_id") or ""), b_id=str(body.get("b_id") or ""))


@router.get("/duplicates/exclusions")
def duplicates_exclusions(request: Request):
    """除外の一覧（**`GET` は書かない**）。"""
    return duplicates_of(request).exclusions()
