"""参照切れの再リンクの口（P8-6。設計 `docs/p8-design.md` §3.2・§3.4・§1.2 の線 9）。

- `POST /api/locations/relink` — **人だけ**。参照切れを新しいパスに繋ぎ直す
  （`{asset_id, path, mode:'exact'|'nearby', from_path?}`。**中身の `sha256` が一致しなければ
  409 `hash_mismatch`**）
- `GET  /api/locations/missing` — **参照切れの一覧**（**読むだけ**。`limit` と
  `include_deleted`）

**検査は 1 か所**: 人が要ることは `require_human`（`api/__init__.py`）で見る（家風）。
`actor` の語彙は `actor_of` が 422 にする。守り（Host / Origin / Content-Type）は
`app.py` の middleware がアプリ全体に掛ける（`include_router` を忘れると効かないので
`tests/test_relink.py` で固定してある）。
"""

from __future__ import annotations

from fastapi import APIRouter, Body, Query, Request

from ..review import ReviewError
from . import actor_of, relink_of, require_human

router = APIRouter(prefix="/api", tags=["locations"])


@router.post("/locations/relink")
def locations_relink(request: Request, body: dict = Body(...)):
    """参照切れの 1 か所を新しいパスに繋ぎ直す（**人だけ**。設計 §3.2）。

    - `mode='exact'`（既定）: `path` は**新しいファイル**（中身を確かめてから繋ぐ）
    - `mode='nearby'`: `path` は**探すフォルダ**（省略すると、その場所が入っている
      登録済みの置き場を同じファイル名で探す）

    **人だけ**なので `require_human` を先に通す（エージェントは 403 `human_only`）。
    """
    actor = require_human(actor_of(request), what="参照切れの繋ぎ直し")
    got = body or {}
    return relink_of(request).relink(
        asset_id=str(got.get("asset_id") or ""),
        path=(str(got["path"]) if got.get("path") is not None else None),
        mode=got.get("mode"),
        from_path=(str(got["from_path"]) if got.get("from_path") is not None else None),
        actor=actor,
    )


@router.get("/locations/missing")
def locations_missing(
    request: Request,
    limit: int = Query(500, description="返す件数（既定 500・上限 5000）"),
    include_deleted: str = Query("0", description="1 でアプリから消した物も出す（P8-2 の段 1〜3）"),
):
    """**参照切れの一覧**（**`GET` は 1 バイトも書かない**）。**人もエージェントも読める**。

    段 2・3 の削除も `missing_at` を立てる（設計 §4.1）ので、既定では消した物を外し、
    **外した数を `excluded_deleted` で返す**（黙って捨てない）。語彙の外は 422。
    """
    actor_of(request)                     # 語彙の検査（他の口と同じ流儀）
    if include_deleted not in ("0", "1"):
        raise ReviewError(422, "include_deleted は 0 | 1 です",
                          details={"include_deleted": "0 | 1"})
    return relink_of(request).missing(limit=limit, include_deleted=include_deleted == "1")
