"""注記の口（P6-2。設計 §3.6）。

- **`GET` は書かない**（§0.6）。切り出しを**書く**のは `POST .../export {format:'crops'}` だけ
- `GET .../export` に `format=crops` が来たら **422 で `POST` を案内**する（P5 の「`GET` が書く」を持ち込まない）
- `GET /api/annotations/{id}/crop` は**その場で作って返す**（`image/png`。書かない）
- `PATCH` / `DELETE` は**自分の `actor` の注記だけ**（点検 C7。サービスが最後の砦）
"""

from __future__ import annotations

from fastapi import APIRouter, Body, Request
from fastapi.responses import JSONResponse, Response

from . import actor_of, annotations_of

router = APIRouter(prefix="/api", tags=["annotations"])


@router.get("/assets/{asset_id}/annotations")
def list_annotations(request: Request, asset_id: str):
    """その画像の注記（古い順。§3.6）。"""
    return {"items": annotations_of(request).list_for_asset(asset_id)}


@router.post("/assets/{asset_id}/annotations")
def create_annotation(request: Request, asset_id: str, payload: dict = Body(default={})):
    """印を付ける／画像 1 枚へのメモ（座標なし。点検 A1）。再送は 200（§0.9）。"""
    got = annotations_of(request).create(
        asset_id,
        shape=payload.get("shape"), x=payload.get("x"), y=payload.get("y"),
        w=payload.get("w"), h=payload.get("h"), body=payload.get("body"),
        group_id=payload.get("group_id"), client_token=payload.get("client_token"),
        actor=actor_of(request),
    )
    replayed = bool(got.pop("replayed", False))
    return JSONResponse({"annotation": got, "replayed": replayed},
                        status_code=200 if replayed else 201)


@router.patch("/annotations/{annotation_id}")
def patch_annotation(request: Request, annotation_id: str, payload: dict = Body(default={})):
    """**メモだけ**変える（他の欄は 422）。"""
    return {"annotation": annotations_of(request).patch(
        annotation_id, payload.get("body"), actor=actor_of(request))}


@router.delete("/annotations/{annotation_id}")
def delete_annotation(request: Request, annotation_id: str):
    """消す（切り出しの PNG も消える。点検 G3）。"""
    return {"deleted": annotations_of(request).delete(annotation_id, actor=actor_of(request))}


@router.get("/assets/{asset_id}/annotations/export")
def export_annotations(request: Request, asset_id: str, format: str = "json"):
    """座標と文の JSON を**返すだけ**（§0.6）。`format=crops` は `POST` に案内する。"""
    if format != "json":
        from ..review import ReviewError
        raise ReviewError(422, "切り出しの書き出しは POST を使ってください",
                          details={"format": "切り出しの書き出しは POST を使ってください"})
    return annotations_of(request).export_doc(asset_id)


@router.post("/assets/{asset_id}/annotations/export")
def export_crops(request: Request, asset_id: str, payload: dict = Body(default={})):
    """切り出しを**書く**（`format='crops'`。§3.6）。同じ名前に上書きするので鍵は取らない。"""
    fmt = payload.get("format") or "crops"
    if fmt != "crops":
        from ..review import ReviewError
        raise ReviewError(422, "format は crops です", details={"format": "crops だけです"})
    ids = payload.get("annotation_ids")
    return annotations_of(request).export_doc(
        asset_id, annotation_ids=ids if isinstance(ids, list) else None, with_crops=True)


@router.get("/annotations/{annotation_id}/crop")
def get_crop(request: Request, annotation_id: str):
    """1 枚の切り出しを**その場で作って返す**（書かない。§3.6）。"""
    service = annotations_of(request)
    doc = service.get(annotation_id)
    png = service.crop_png(doc["asset_id"], annotation_id)
    return Response(content=png, media_type="image/png")
