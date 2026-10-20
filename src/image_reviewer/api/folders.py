"""仮想フォルダ（カタログ）の口（P2-1）。

設計: `docs/design.md` **§6.1**（カタログの 8 本）・**§10.1**（多対多。実ファイルは動かさない）・
       **§5.3**（表）・**§16.9**（P2-0 の決定）

- `GET    /api/folders` — **木**（`kind` と生きた画像の枚数つき）。**書かない**
- `POST   /api/folders` — 作る（`{parent_id, name, kind, smart_query?}`）
- `PATCH  /api/folders/{id}` — 名前・親・並び・条件（渡された欄だけ）
- `DELETE /api/folders/{id}?dry_run=true` — 何が消えるかを返すだけ
- `DELETE /api/folders/{id}` — 消す（**フォルダ名の confirm が要る**。既定は論理削除。
  `purge:true` で実削除）。**画像は 1 枚も消さない**
- `POST   /api/folders/{id}/members` — 入れる（`{asset_ids}[]`）
- `DELETE /api/folders/{id}/members` — 外す（`{asset_ids}[]`。**画像は消さない**）
- `GET    /api/folders/{id}/assets` — 中身の一覧（**生きた画像だけ**）

家風:

- **`GET` は 1 バイトも書かない**（数えるのは読むだけ。`GET` で `count_cache` を埋めない）
- **書く口は人だけ**（`require_human` の 1 か所。エージェントは **403 `human_only`**）
- **語彙の外・存在しない親・循環する親・同じ親の同名は 422**（500 にしない）
- `actor` の検査は `actor_of()` の 1 か所（`human` / `agent` 以外は 422）
"""

from __future__ import annotations

from fastapi import APIRouter, Body, Request

from . import actor_of, folders_of, require_human

router = APIRouter(prefix="/api", tags=["folders"])


@router.get("/folders")
def list_folders(request: Request):
    """**木の形**（§6.1）。`kind` と**生きた画像の枚数**つき。**書かない**。"""
    actor_of(request)                          # 語彙の検査（他の口と同じ流儀）
    return folders_of(request).tree()


@router.post("/folders")
def create_folder(request: Request, payload: dict = Body(default={})):
    """フォルダを作る。**人だけ**（§6.1）。同じ親の同名は 422。"""
    require_human(actor_of(request))
    return folders_of(request).create(
        parent_id=payload.get("parent_id"),
        name=payload.get("name"),
        kind=payload.get("kind") or "manual",
        smart_query=payload.get("smart_query"),
    )


@router.patch("/folders/{folder_id}")
def update_folder(request: Request, folder_id: str, payload: dict = Body(default={})):
    """名前・親・並び・条件を変える。**人だけ**。循環する親は 422。"""
    require_human(actor_of(request))
    return folders_of(request).update(folder_id, payload)


@router.delete("/folders/{folder_id}")
def delete_folder(request: Request, folder_id: str, dry_run: bool = False,
                  payload: dict | None = Body(default=None)):
    """フォルダを消す（**人だけ**）。**既定は論理削除**。`dry_run=true` は何も消さない。

    **`DELETE` に本文を持たせる**のは §6.1 の字（`{confirm:'<フォルダ名>'}`）に従うため。
    `confirm` が名前と違えば **422 `confirm_required`**（仮想フォルダは作り直せない分類なので、
    無警告で消さない。点検 C11）。`purge:true` は実削除（**画像は消えない**）。
    **`purge` は真偽値だけ**（文字列の `"false"` を真にしない。P2-1 の監査 C-4）。
    **論理削除は `folder_member` を消さない**（消えるのは `purge` のときだけ。同 B-1）。
    """
    require_human(actor_of(request))
    body = payload or {}
    return folders_of(request).delete(
        folder_id, dry_run=bool(dry_run), confirm=body.get("confirm"),
        purge=body.get("purge", False))


@router.post("/folders/{folder_id}/members")
def add_members(request: Request, folder_id: str, payload: dict = Body(default={})):
    """**入れる**（`{asset_ids:[]}`）。**人だけ**。何度送っても同じ（家風）。"""
    require_human(actor_of(request))
    return folders_of(request).add_members(folder_id, payload.get("asset_ids"))


@router.delete("/folders/{folder_id}/members")
def remove_members(request: Request, folder_id: str, payload: dict | None = Body(default=None)):
    """**外す**（`{asset_ids:[]}`）。**人だけ**。**画像は消さない**（`folder_member` の行だけ）。"""
    require_human(actor_of(request))
    return folders_of(request).remove_members(folder_id, (payload or {}).get("asset_ids"))


@router.get("/folders/{folder_id}/assets")
def list_folder_assets(request: Request, folder_id: str, cursor: int = 0, limit: int = 200,
                       sort: str = "position"):
    """**中身の一覧**（§6.1）。**片付け済みの画像は出さない**。**書かない**。"""
    actor_of(request)
    return folders_of(request).assets(folder_id, cursor=cursor, limit=limit, sort=sort)
