"""削除の口（P8-2。設計 `docs/p8-design.md` §3.2〜§3.4）。

- `POST /api/locations/delete` — 1 件を段 1〜3 で消す（**`DELETE` に本文を持たせない**。§0.15 の 1）
- `POST /api/locations/bulk-delete/preview` — 対象を**凍結**する（§0.7）
- `POST /api/locations/bulk-delete` — **凍結した一覧だけ**を実行する
- `GET  /api/pending-deletes`（別名 `GET /api/deletions/trash`）— **最近の削除**（段 1〜3。残り時間つき）
- `POST /api/pending-deletes/{id}/undo`（別名 `POST /api/deletions/{id}/undo`）— 取り消す
- `GET  /api/deletions` — **最近の削除**（段 1〜3 の台帳）
- `GET  /api/trash` — ゴミ箱（段 2。日付ごと）／`POST /api/trash/restore` — ゴミ箱から戻す（**人だけ**）
- `GET  /api/deletions/previews/{id}` — 凍結した一覧（**実行時に評価し直さない**ことの確認）
- `POST /api/deletions/{id}/purge` — **「いま消す」**（保留領域のファイルを今すぐ消す。**人だけ**）
- `POST /api/deletions/{id}/advance` / `POST /api/deletions/advance` — **後から段 2 へ進める**
  （**人だけ**。P10。`docs/deletions-advance.md`）
- `POST /api/deletions/{id}/close` / `POST /api/deletions/close` — **実体が無い行を片付ける**
  （**人だけ**。P10。ファイルは 1 つも消さない・動かさない）

**削除は人もエージェントも可**（利用者の回答 Q2。`require_human` を掛けない）。
**人だけ**なのは `as_copy`（別名で戻す）・ゴミ箱からの復帰・「いま消す」・**後から段 2 へ進める**・
**片付ける**で、検査は `deletions.py` の中の 1 か所（`_require_human`）にある。

**`GET` は 1 バイトも書かない**（`remaining_sec` も減らさない。減らすのはタイマー）。
守り（Host / Origin / Content-Type）は `app.py` の middleware がアプリ全体に掛ける。
"""

from __future__ import annotations

from fastapi import APIRouter, Body, Request

from . import actor_of, deletions_of

router = APIRouter(prefix="/api", tags=["deletions"])


def _flag(value) -> bool:
    """本文の真偽（**`"false"` を真にしない**）。

    確認の欄（`confirm` / `confirm_last_copy` / `as_copy`）を**文字列で送られても**、
    安全側（＝確認が要る側）に倒す。素直な `bool("false")` は **True** になるので使わない。
    """
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "yes", "on")
    return value is True or value == 1


# ---- 1 件（段 1〜3）----


@router.post("/locations/delete")
def locations_delete(request: Request, body: dict = Body(...)):
    """1 件を段 1〜3 で消す。

    `{asset_id, path, stage, reason?, client_token?, confirm_last_copy?}`。
    **`client_token` の再送は 200 で前の結果**（`replayed: true`）。
    """
    got = body or {}
    return deletions_of(request).delete(
        asset_id=(str(got["asset_id"]) if got.get("asset_id") else None),
        path=str(got.get("path") or ""),
        stage=got.get("stage"),
        reason=(str(got["reason"]) if got.get("reason") is not None else None),
        client_token=(str(got["client_token"]) if got.get("client_token") else None),
        confirm_last_copy=_flag(got.get("confirm_last_copy")),
        actor=actor_of(request),
    )


# ---- 一括（凍結 → 実行）----


@router.post("/locations/bulk-delete/preview")
def locations_bulk_preview(request: Request, body: dict = Body(...)):
    """対象を**凍結**する（`{scope, stage}` → `{preview_id, items, count, bytes, frees, …}`）。

    **エージェントは 200 枚を超えたら 422 `too_many`**（人に上限は無い。点検 B1）。
    """
    got = body or {}
    return deletions_of(request).bulk_preview(
        scope=got.get("scope") or {}, stage=got.get("stage"), actor=actor_of(request))


@router.post("/locations/bulk-delete")
def locations_bulk_delete(request: Request, body: dict = Body(...)):
    """凍結した一覧を実行する（`{preview_id, confirm: true, client_token?, confirm_last_copy?}`）。"""
    got = body or {}
    return deletions_of(request).bulk_delete(
        preview_id=str(got.get("preview_id") or ""),
        confirm=_flag(got.get("confirm")),
        client_token=(str(got["client_token"]) if got.get("client_token") else None),
        confirm_last_copy=_flag(got.get("confirm_last_copy")),
        actor=actor_of(request),
    )


# ---- 読み（`GET` は書かない）----


@router.get("/pending-deletes")
def pending_deletes(request: Request):
    """**最近の削除**（段 1〜3。残り時間つき。**誰が消したか**も返す。§3.2）。**減らさない**。

    **（P8-3 の監査 C-2）段 1〜3 を返す**（`frontend-design.md` §4.6 の「1 行 = `deletion_log`
    の 1 行」）。段 1 で外しただけの行もここに出て、ここから戻せる。
    """
    return deletions_of(request).pending(actor=actor_of(request))


@router.get("/deletions/trash")
def deletions_trash(request: Request):
    """`GET /api/pending-deletes` と同じ物（**段 1〜3 と `remaining_sec`**）。

    設計 §3.2 は `/api/pending-deletes`、実装の指示書は `/api/deletions/trash` と書いている。
    **どちらでも同じ物が返る**ようにして、画面と監査の両方から使えるようにした。
    """
    return deletions_of(request).pending(actor=actor_of(request))


@router.get("/deletions")
def deletions_ledger(request: Request, limit: int = 100):
    """**最近の削除**（段 1〜3 の台帳。§3.2）。**消した行は残る**（判断より長く生きる）。"""
    return deletions_of(request).ledger(limit=limit, actor=actor_of(request))


@router.get("/deletions/previews/{preview_id}")
def deletions_preview(request: Request, preview_id: str):
    """凍結した一覧（**実行時に `scope` を評価し直さない**ことの確認に使う）。**読むだけ**。

    **（D-5）`actor` を見る**（語彙外は 422。他の口と同じ検査を通す）。
    """
    return deletions_of(request).preview_of(preview_id, actor=actor_of(request))


@router.get("/trash")
def trash_list(request: Request):
    """**ゴミ箱**（段 2。日付ごと。§3.2）。**メインの一覧とは別**。**自動では消さない**（Q7）。"""
    return deletions_of(request).trash(actor=actor_of(request))


# ---- 取り消し ----

# 設計 §3.2 の名前（`/api/pending-deletes/{id}/undo`）と、実装の指示書の名前
# （`/api/deletions/{id}/undo`）の**両方**を同じ処理に結ぶ（画面と監査の両方から使える）


@router.post("/pending-deletes/{deletion_id}/undo")
def pending_deletes_undo(request: Request, deletion_id: str,
                         body: dict | None = Body(default=None)):
    """取り消す（**上書きしない**。埋まっていれば 409 `target_exists` で止めて尋ねる）。

    **自分が消した物だけ**（他人の分は 403 `not_yours`）。**`as_copy` は人だけ**（403 `human_only`）。
    """
    got = body or {}
    return deletions_of(request).undo(
        deletion_id, as_copy=_flag(got.get("as_copy")), actor=actor_of(request))


@router.post("/deletions/{deletion_id}/undo")
def deletions_undo(request: Request, deletion_id: str, body: dict | None = Body(default=None)):
    """`POST /api/pending-deletes/{id}/undo` と同じ物（別名）。"""
    got = body or {}
    return deletions_of(request).undo(
        deletion_id, as_copy=_flag(got.get("as_copy")), actor=actor_of(request))


@router.post("/trash/restore")
def trash_restore(request: Request, body: dict = Body(...)):
    """**ゴミ箱から戻す**（`{deletion_id}`。**人だけ**）。**上書きしない**（409 `target_exists`）。"""
    got = body or {}
    return deletions_of(request).trash_restore(
        str(got.get("deletion_id") or ""), actor=actor_of(request))


@router.post("/deletions/{deletion_id}/purge")
def deletions_purge(request: Request, deletion_id: str, body: dict | None = Body(default=None)):
    """**「いま消す」**（保留領域のファイルを今すぐ消す。**人だけ**。§5 の「戻せませんでした」の導線）。

    **`confirm: true` が要る**。段 3 の 5 分の窓を待たずに消すので、押し間違いを防ぐ。
    """
    got = body or {}
    return deletions_of(request).purge_now(
        deletion_id, confirm=_flag(got.get("confirm")), actor=actor_of(request))


# ---- 後から段 2 へ進める・実体が無い行を片付ける（P10。利用者の要望）----
#
# 記録: `docs/deletions-advance.md`。**どちらも人だけ**（検査は `deletions.py` の `_require_human`
# の 1 か所）。**段 3 への直行は作らない**（段 2 まで＝`_advance_stage_of`）。
# **`GET` は 1 バイトも書かない**（どちらも `POST`）。
# まとめての上限は 1 回 200 件（`MAX_BATCH_PER_CALL`。超えたら **422 `too_many`** で 1 件も進めない）。


@router.post("/deletions/advance")
def deletions_advance_many(request: Request, body: dict = Body(...)):
    """**まとめて段 2 へ進める**（`{ids: [...], stage: 2}`。**人だけ**）。

    1 件ずつ同じ道（`_advance_one`）を通し、**断った 1 件は `skipped` に理由つきで残して
    残りを進める**（`{advanced, skipped, count, skipped_count, requested}`）。
    """
    got = body or {}
    return deletions_of(request).advance_many(
        got.get("ids"), stage=got.get("stage"), actor=actor_of(request))


@router.post("/deletions/{deletion_id}/advance")
def deletions_advance(request: Request, deletion_id: str, body: dict | None = Body(default=None)):
    """**カタログから外した行を、後からアプリのゴミ箱へ移す**（`{stage: 2}`。**人だけ**。P10）。

    - **その行が指すファイルが在るときだけ**。無ければ **409 `missing_file`**
      （「ファイルが無いので片付ける」を案内する）
    - **（P10 の監査 A-1）台帳の行が指す物かを見る**。走査が同じ場所を別の `asset` として
      登録し直すと台帳の `asset_id` は古くなる（実データの 6 行）。**別の画像のファイルを
      移さない**ように、台帳の `size` と「いまその場所を登録している枚」を照合し、合わなければ
      **409 `different_file`**（「ファイルが無いので片付ける」を案内する）
    - 移し方は**段 2 と同じ道**で `<data>/trash/<日付>/<ハッシュ>/` へ
      （**上書きしない**＝409 `target_exists`／別ボリュームは 409 `cross_volume`）
    - 既に段 2 以上なら **409 `already_stage2` / `already_stage3`**（**二重に移さない**）／
      片付けた行は **409 `already_closed`**
    - **段 3 へは直行しない**（`stage` は 2 だけ）
    """
    got = body or {}
    return deletions_of(request).advance(
        deletion_id, stage=got.get("stage"), actor=actor_of(request))


@router.post("/deletions/close")
def deletions_close_many(request: Request, body: dict = Body(...)):
    """**まとめて片付ける**（`{ids: [...], reason: "missing"}`。**人だけ**。P10）。

    実データの 194 行を 1 回で片付けるための口（利用者の要望）。**ファイルがまだ在る行は
    断って `skipped` に残す**（**生きているファイルを片付けない**）。
    """
    got = body or {}
    return deletions_of(request).close_many(
        got.get("ids"), reason=got.get("reason"), actor=actor_of(request))


@router.post("/deletions/{deletion_id}/close")
def deletions_close(request: Request, deletion_id: str, body: dict | None = Body(default=None)):
    """**実体が無い行を片付ける**（`{reason: "missing"}`。**人だけ**。P10）。

    **この行のファイルが、登録の場所・元の場所・アプリのゴミ箱・一時置き場のどこにも無いことを
    確かめてから**、その行を終わりにする（`closed_at` / `close_reason`）。1 つでも見つかったら
    **409 `file_found`**（**生きているファイルを片付けない**）。
    **（P10 の監査 A-1 / C-1）「在る」ではなく「この行の画像が在る」**を見る——台帳の `asset_id`
    が古く、同じ場所に**別の画像**が登録されていても、そのファイルは数えない（数えると
    **X の実体はどこにも無いのに片付けられない**）。**段 3 の行はタイマーからも外す**（監査 C-3）。

    **ファイルは 1 つも消さない・動かさない**（`files_touched: 0`）。**`asset.deleted_at` は
    そのまま**（カタログには戻さない）。**既に片付けている行は 200 で `replayed: true`**
    （二重に記録しない）。**誰が片付けたかは `delete_request` に残る**（監査 B-2）。
    """
    got = body or {}
    return deletions_of(request).close(
        deletion_id, reason=got.get("reason"), actor=actor_of(request))
