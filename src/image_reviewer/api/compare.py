"""比較の口（P5-2 / P5-3）。

設計: docs/p5-design.md §3.2（`/api/groups/{id}/compare`）・§6.1（差分表）・§6.2（指標）、
      docs/comparison.md §3.1・§2.3（ヒートマップ）・§4（指標の定義）

- `GET /api/compare?ids=a,b,c&base=<asset_id>` — **まとまりが無くても引ける**（点検 C9。
  複数選択から比較に入る道。まとまりがまだ無いことがある）
- `GET /api/groups/{id}/compare` — 同じ文書に `group` を足したもの
- `POST /api/compare/pair {a_id, b_id, force?}` — **1 組の指標**（`comparison.md` §4）と
  差分ヒートマップ（P5-3。設計 §6.2 の「単発にも引ける」）
- `POST /api/groups/{id}/compare/pair` — 同じものの**まとまりつき**（所属を検査する）
- 計算は `compare.py` だけが行う（設計 §10-4。画面は描くだけ）
- 守り（Host / Origin / Content-Type）は `app.py` の middleware がアプリ全体に掛ける。
  `pair` は POST だが**状態を変えない**（読んで計算して返すだけ）ので、
  `X-Image-Reviewer-Actor` は要らない（判断の口ではない）
"""

from __future__ import annotations

from fastapi import APIRouter, Body, Request

from .. import compare
from ..review import ReviewError
from . import review_of, store_of

router = APIRouter(prefix="/api", tags=["compare"])


@router.get("/compare")
def compare_assets(request: Request, ids: str | None = None, base: str | None = None):
    """複数選択の比較。**まとまりは要らない**（点検 C9）。"""
    return compare.compare_assets(store_of(request), compare.parse_ids_param(ids), base=base)


@router.get("/groups/{group_id}/compare")
def compare_group(request: Request, group_id: str, ids: str | None = None,
                  base: str | None = None):
    """まとまりの比較。`group` を足して返す（`p5-design.md` §3.2）。

    まとまりが 8 枚を超えるときは `ids=` で 8 枚までを指定する（画面の上限）。
    """
    group = review_of(request).group_state(group_id)          # 無ければ 404
    members = [item["asset_id"] for item in group["items"]]
    chosen = compare.parse_ids_param(ids) or members
    outside = [asset_id for asset_id in chosen if asset_id not in set(members)]
    if outside:
        raise ReviewError(422, "ids にこのまとまりに無い画像があります",
                          details={"extra": outside, "group_id": group_id})
    document = compare.compare_assets(store_of(request), chosen, base=base)
    return {"group": compare.group_head(group), **document}


def _pair_args(payload: dict) -> tuple[str, str, bool]:
    """本文から `a_id` / `b_id` / `force` を取る。無ければ 422（`pair` の 2 口で同じ規則）。"""
    a_id = str(payload.get("a_id") or "").strip()
    b_id = str(payload.get("b_id") or "").strip()
    if not a_id or not b_id:
        raise ReviewError(422, "本文に a_id と b_id が要ります", details={"a_id": a_id,
                                                                       "b_id": b_id})
    # JSON の `true` / `"true"` / `1` のどれでも受ける（画面は `true` を送る）
    force = payload.get("force")
    return a_id, b_id, force is True or str(force).lower() in ("true", "1", "yes")


@router.post("/compare/pair")
def compare_pair(request: Request, payload: dict = Body(default={})):
    """1 組の指標と差分ヒートマップ（設計 §6.2。P5-3）。

    **保存はしない**（ヒートマップは要求のたびに作る）。指標だけ `comparison_cache` に残る。
    """
    a_id, b_id, force = _pair_args(payload)
    return compare.pair_report(store_of(request), a_id, b_id, force=force)


@router.post("/groups/{group_id}/compare/pair")
def compare_group_pair(request: Request, group_id: str, payload: dict = Body(default={})):
    """まとまりの中の 1 組。**まとまりに無い id は 422**（`/compare` と同じ規則）。"""
    group = review_of(request).group_state(group_id)          # 無ければ 404
    members = {item["asset_id"] for item in group["items"]}
    a_id, b_id, force = _pair_args(payload)
    outside = [asset_id for asset_id in (a_id, b_id) if asset_id not in members]
    if outside:
        raise ReviewError(422, "このまとまりに無い画像があります",
                          details={"extra": outside, "group_id": group_id})
    return compare.pair_report(store_of(request), a_id, b_id, force=force)
