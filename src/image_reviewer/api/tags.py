"""タグとジョブの口（P4-1）。

設計: docs/p4-design.md §3.1（誰が呼ぶか）・§3.2（受付）・§3.3（進行）・§3.4（取得）・§3.6（絞り込み）

- **`GET` は書かない**（§0.10）。訳すのは P4-2 の `POST /api/tags/gloss` だけ
- **手動の付け外しは `human` だけ**（403。§0.14 Q3）。検査は `tags.require_human` の 1 か所
- `POST /api/assets/tag` は**投げてすぐ返る**（202。実行は背景。§3.2）
"""

from __future__ import annotations

from fastapi import APIRouter, Body, Request
from fastapi.responses import JSONResponse

from . import actor_of, gloss_of, jobs_of, store_of
from .. import gloss, tags
from ..review import ReviewError

router = APIRouter(prefix="/api", tags=["tags"])


# ---- 1 枚のタグ（§3.4）----


@router.get("/assets/{asset_id}/tags")
def get_asset_tags(request: Request, asset_id: str):
    """1 枚のタグ（**契約の形**）＋ §3.4 の `glosses` / `pending_gloss` / `counts`。

    **訳さない**（§0.10。訳すのは `POST /api/tags/gloss`）。
    """
    with store_of(request).locked() as con:
        if con.execute("SELECT 1 FROM asset WHERE id = ?", (asset_id,)).fetchone() is None:
            raise ReviewError(404, "画像がありません", details={"asset_id": asset_id})
        items = tags.tag_docs(con, asset_id)
        return {"asset_id": asset_id, "items": items, **gloss.block_for(con, items)}


@router.post("/assets/{asset_id}/tags")
def add_asset_tag(request: Request, asset_id: str, payload: dict = Body(default={})):
    """人が 1 語付ける（**冪等**）。`human` 以外 403。"""
    actor = actor_of(request)
    tags.require_human(actor)
    with store_of(request).transaction() as con:
        if con.execute("SELECT 1 FROM asset WHERE id = ?", (asset_id,)).fetchone() is None:
            raise ReviewError(404, "画像がありません", details={"asset_id": asset_id})
        row = tags.resolve_tag(con, name=payload.get("name"), tag_id=payload.get("tag_id"))
        if row is None:
            # **語彙（CSV）にある語なら、行を作ってから付ける**（P4-1 の監査 C-4。
            # 以前は `tag` 表にある語しか付けられず、語彙にある語でも 404 だった）
            row = tags.ensure_tag(con, payload.get("name"), csv=tags.load_csv(con))
        if row is None:
            raise ReviewError(404, "その語は語彙（Danbooru の語）にありません",
                              details={"name": payload.get("name"), "tag_id": payload.get("tag_id")})
        added = tags.add_manual(con, asset_id, row, actor)
        items = tags.tag_docs(con, asset_id)
    return {"asset_id": asset_id, "added": added, "tag_id": int(row["id"]), "items": items}


@router.delete("/assets/{asset_id}/tags/{tag_id}")
def remove_asset_tag(request: Request, asset_id: str, tag_id: int):
    """人が付けた語を外す（**`manual` の行だけ**）。2 回目は 404。`human` 以外 403。"""
    actor = actor_of(request)
    tags.require_human(actor)
    with store_of(request).transaction() as con:
        row = tags.resolve_tag(con, tag_id=tag_id)
        if row is None:
            raise ReviewError(404, "その語はありません", details={"tag_id": tag_id})
        if not tags.remove_manual(con, asset_id, row):
            raise ReviewError(404, "その語はこの画像に付いていません（人が付けた分だけ外せます）",
                              details={"asset_id": asset_id, "tag_id": tag_id})
        items = tags.tag_docs(con, asset_id)
    return {"asset_id": asset_id, "removed": True, "tag_id": int(tag_id), "items": items}


# ---- 語の一覧（§3.6 の隣。既定は `known=1` だけ。点検 §I-2）----


@router.get("/tags")
def list_tags(request: Request, q: str | None = None, category: int | None = None,
              source: str | None = None, known: str = "1", limit: int = 200,
              cursor: str | None = None):
    """語の一覧（使用数の多い順）。**既定は語彙にある語だけ**（`known=1|0|all`）。"""
    with store_of(request).locked() as con:
        return tags.list_tags(con, q=q, category=category, source=source, known=known,
                              limit=limit, cursor=cursor)


# ---- 語釈（§3.5。P4-2）----
#
# **`GET` は 1 バイトも書かない**（§0.10）。訳すのは `POST /api/tags/gloss` だけ。
# 人が直すのは `POST /api/tags/{tag_id}/gloss`（**`human` だけ**）。
# リテラルの道（`/tags/gloss`）を先に宣言する（`{tag_id}` と紛れないように）。


@router.post("/tags/gloss")
def translate_glosses(request: Request, payload: dict = Body(default={})):
    """**訳す**（模型を回す。§3.5）。

    既定は「語釈の無い語だけ」。既にある語は `skipped` で**模型を回さない**（点検 B-3）。
    `force=true` でも **`edited=1` は上書きしない**。
    """
    return gloss_of(request).translate(
        tag_ids=payload.get("tag_ids"),
        limit=payload.get("limit"),
        force=bool(payload.get("force")))


@router.get("/tags/gloss/pending")
def list_pending_gloss(request: Request, limit: int = 100):
    """語釈の無い語を**数えるだけ**（§3.5）。**訳さない**。"""
    with store_of(request).locked() as con:
        return gloss.pending(con, limit=limit)


@router.get("/tags/{tag_id}/gloss")
def get_gloss(request: Request, tag_id: int):
    """1 語の語釈（無ければ `ja: null`）。**訳さない**（§0.10）。"""
    with store_of(request).locked() as con:
        return gloss.lookup(con, tag_id)


@router.post("/tags/{tag_id}/gloss")
def set_gloss(request: Request, tag_id: int, payload: dict = Body(default={})):
    """**人が日本語訳を書く / 直す**（`source='manual'`・`edited=1`。§3.5・§4.2）。

    `human` 以外 403（検査は `tags.require_human` の 1 か所）。
    """
    actor = actor_of(request)
    tags.require_human(actor)
    ja = payload.get("ja")
    if not isinstance(ja, str) or not ja.strip():
        # **（D-2）** 画面に出うる文なので「日本語訳」を使う
        raise ReviewError(422, "ja（日本語訳）が要ります", details={"ja": "1 文字以上"})
    if len(ja) > gloss.MAX_JA:
        raise ReviewError(422, f"ja は {gloss.MAX_JA} 文字までです",
                          details={"ja": f"{gloss.MAX_JA} 文字まで", "length": len(ja)})
    with store_of(request).transaction() as con:
        row = tags.resolve_tag(con, tag_id=tag_id)
        if row is None:
            raise ReviewError(404, "その語はありません", details={"tag_id": tag_id})
        return gloss.set_manual(con, row, ja.strip())


# ---- タグ付けの受付と進行（§3.2〜§3.3）----


@router.post("/assets/tag")
def start_tagging(request: Request, payload: dict = Body(default={})):
    """背景ジョブを始める（**202**。投げてすぐ返る）。"""
    got = jobs_of(request).start_tag(
        asset_ids=payload.get("asset_ids"),
        engine=payload.get("engine") or "auto",
        model=payload.get("model"),
        threshold=payload.get("threshold"),
        character_threshold=payload.get("character_threshold"),
        sources=payload.get("sources"),
        limit=payload.get("limit") or 0,
        force=bool(payload.get("force")))
    # 対象が 0 枚のときは job を作らない（§3.2）。そのときは 200 で返す
    status = 202 if got.get("job_id") else 200
    return JSONResponse(got, status_code=status)


@router.get("/jobs")
def list_jobs(request: Request, limit: int = 50):
    return jobs_of(request).list(limit=limit)


@router.get("/jobs/{job_id}")
def get_job(request: Request, job_id: str):
    return jobs_of(request).get(job_id)


@router.get("/jobs/{job_id}/items")
def list_job_items(request: Request, job_id: str, state: str | None = None, limit: int = 200):
    """job の 1 件ずつの結果（§3.3。**失敗の全部はここで読む**。`items_failed` は先頭 20 件だけ）。"""
    jobs = jobs_of(request)
    jobs.get(job_id)                                   # 無ければ 404
    with store_of(request).locked() as con:
        where, args = "WHERE job_id = ?", [job_id]
        if state:
            where += " AND state = ?"
            args.append(state)
        rows = con.execute(f"SELECT ref, state, error FROM job_item {where}"
                           f" ORDER BY ref LIMIT ?", [*args, max(1, min(int(limit or 200), 1000))]
                           ).fetchall()
        return {"job_id": job_id, "items": [{"ref": row["ref"], "state": row["state"],
                                             "error": row["error"]} for row in rows]}


@router.post("/jobs/{job_id}/cancel")
def cancel_job(request: Request, job_id: str):
    return jobs_of(request).cancel(job_id)
