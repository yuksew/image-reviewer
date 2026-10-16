"""書き出しの口（P5-1）。

設計: docs/p5-design.md §3.4・§0.3（B1・B2・G11）

- **`POST` の `scope=all` だけが `<data>/export/review.json` を書く**（手動の口）。
  監査 C8/G2（実行込みのやり直し）で、**`GET` は返すだけ**にした（読み出しに副作用を
  持たせない。プリフェッチやリンクのプレビューで勝手に書かれない）
- `scope=group:{id}` と `scope=asset:{id}` は**書かない**。文書を返すだけ
  （`asset:` は読み取り専用。点検 G11）
- 判断のたびの `<data>/export/groups/<id>.json` は `ReviewService` → `ExportService` が書く
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Body, Request
from fastapi.responses import FileResponse, JSONResponse

from ..export import parse_scope
from . import export_of

router = APIRouter(prefix="/api/export", tags=["export"])

# <repo>/schemas/review-export.schema.json（api/export.py から 3 つ上）
SCHEMA_PATH = Path(__file__).resolve().parents[3] / "schemas" / "review-export.schema.json"


def _export(request: Request, payload: dict, *, write: bool) -> JSONResponse:
    exporter = export_of(request)
    scope = payload.get("scope") or "all"
    kind, _target = parse_scope(scope)          # 不正な scope は 422
    options = {
        "include_paths": bool(payload.get("include_paths")),
        "include_tags": bool(payload.get("include_tags")),
        "include_prompts": bool(payload.get("include_prompts")),
        # P6（点検 A3）: 差し替えで閉じたまとまりを `groups[]` に出すか（既定は出さない）
        "include_superseded": bool(payload.get("include_superseded")),
    }
    doc = exporter.build(scope, **options)
    if write and kind == "all":
        exporter.write_all(doc=doc)             # 手動の全件だけがファイルを書く（POST）
    return JSONResponse(doc)


@router.get("/review.json")
def get_review(request: Request, scope: str = "all", include_paths: bool = False,
               include_tags: bool = False, include_prompts: bool = False,
               include_superseded: bool = False):
    """**読むだけ**（ファイルを書かない。監査 C8/G2）。書かせたいときは `POST`。"""
    return _export(request, {"scope": scope, "include_paths": include_paths,
                             "include_tags": include_tags,
                             "include_prompts": include_prompts,
                             "include_superseded": include_superseded}, write=False)


@router.post("/review.json")
def post_review(request: Request, payload: dict = Body(default={})):
    """組み立てて返し、`scope=all` なら**ファイルにも書く**（手動の書き出し）。"""
    return _export(request, payload or {}, write=True)


@router.get("/review.schema.json")
def get_schema():
    """契約そのもの。他ツールが版を確かめられるように配る。"""
    return FileResponse(SCHEMA_PATH, media_type="application/json")
