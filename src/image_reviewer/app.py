"""プロトタイプのサーバ（FastAPI）。

設計: docs/design.md §3（同一オリジン配信）、§6.1（API）、§6.3.1（Host / Origin の検査）
"""

from __future__ import annotations

import json
import logging
import os
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Body, FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import thumbs
from . import compare
from .annotations import AnnotationService
# 注意: `api/__init__.py` は `from __future__ import annotations` を持っているので、
# `from .api import annotations as ...` は**標準ライブラリの `__future__.annotations`**
# （`_Feature` オブジェクト）を拾ってしまう。**モジュールを名指しで**取る
from .api.annotations import router as annotations_router
from .api import compare as compare_api
from .api import deletions as deletions_api
from .api import duplicates as duplicates_api
from .api import export as export_api
from .api import groups as groups_api
from .api import requests as requests_api
from .api import reviews as reviews_api
from .api import tags as tags_api
from .api import review_error_handler
from .deletions import DeletionService
from .duplicates import DuplicatesService
from .export import ExportService
from .gloss import GlossService
from .jobs import JobService
from .review import ReviewError, ReviewService
from .review_requests import ReviewRequestService
from .scan import scan as run_scan
from .store import Store

log = logging.getLogger(__name__)

PKG_DIR = Path(__file__).resolve().parent
REPO_DIR = PKG_DIR.parents[1]
GUI_DIR = REPO_DIR / "apps" / "gui"
STARTED_AT = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
_STARTED_AT = STARTED_AT

ALLOWED_HOSTS = {"127.0.0.1", "localhost", "[::1]"}


def data_dir() -> Path:
    return Path(os.environ.get("IMAGE_REVIEWER_DATA", REPO_DIR / ".data"))


def create_app() -> FastAPI:
    # 判断と書き出し（P5-1）が同じ 1 本を使うための置き場（点検 C13）
    store = Store(data_dir())
    # 監査 A1: 起動時に拾うのは**DB の印**（`exported_at IS NULL OR changed_at > exported_at`）
    # だけにする。メモリの `_pending` は落ちると消えるので当てにしない。
    # 順序は「写しの組み直し（`ReviewService`）→ 書き出し」にする（点検 C3。
    # 壊れた写しを書き出してから直すと、直した内容が次の判断までファイルに出ない）
    exporter = ExportService(store, flush_on_start=False)
    review = ReviewService(store, exporter=exporter)
    # P6-1a: 要求の口（受付・一覧・取得・断る）。`decide` で閉じるのは `ReviewService` の側
    requests_svc = ReviewRequestService(store, review)
    # P6-2: 注記の口。切り出しは**キャッシュ**なので、過去に失敗して残った一時ファイルを
    # 起動時に片づける（§0.8。P5 の書き出しと同じ形）
    annotations_svc = AnnotationService(store)
    annotations_svc.clean_stale_tmp()
    # P4-1: タグ付けの背景ジョブ（**ワーカーは 1 本**）。起動時に、前のプロセスが落ちて
    # `running` のまま残った job を `failed` にする（残すと次の POST が 409 で塞がる。§4.1）
    jobs_svc = JobService(store)
    # P4-2: 語釈（日本語）。**模型は呼んだときだけ**回す（既定は「語釈の無い語だけ」）
    gloss_svc = GlossService(store)
    # P8-1: 重複の検出と整理。**pHash は `GET` では計算しない**（背景ジョブだけが計算する）。
    # 起動時に、前のプロセスが落ちて `running` のまま残ったハッシュの job を `failed` にする
    duplicates_svc = DuplicatesService(store)
    # P8-2: 削除の 3 段階と 5 分の窓。**起動時には消さない**（タイマーは `lifespan` で張る。
    # 起動の直後に消すと、再起動で取り消せなくなる。設計 §0.6-3）
    deletions_svc = DeletionService(store)
    exporter.flush_dirty()

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        """監査 A1: 終了時に溜まっている分を書き出す（`threading.Timer` は daemon なので、
        何もしないと最後の 2 秒の判断がファイルに出ないまま消える）。

        は**プロセスの状態ではなく DB の行**なので、落ちたまま（あるいは前回のまま）1 が残っていると、
        **誰も回していないのに「動いている」と画面に出る**（実際にはスレッドが居ない）。

        P8-2: ここで**削除のタイマー（30 秒周期）を張る**。**張った時点では何も消さない**
        （期限切れの片づけは 2 回目の周期から。設計 §0.6-3・§1.2 の線 7）。
        """
        deletions_svc.start()
        try:
            yield
        finally:
            # **タイマーを先に止める**（止めないと、閉じた接続に触って例外を出す）
            deletions_svc.stop()
            try:
                exporter.flush()
            except Exception:  # noqa: BLE001  終了を失敗で止めない（DB の印は次回が拾う）
                log.exception("終了時の書き出しに失敗しました（次の起動で拾います）")
            finally:
                exporter.close()
                # `create_app()` が作った `Store` もここで閉じる。閉じないと接続が残り、
                # Windows では（テストの後始末などが）`db.sqlite3` を消せない
                store.close()

    app = FastAPI(title="image-reviewer (prototype)", version="0.0.1-proto",
                  lifespan=lifespan)
    app.state.store = store
    app.state.export = exporter
    app.state.review = review
    app.state.requests = requests_svc
    app.state.annotations = annotations_svc
    app.state.jobs = jobs_svc
    app.state.gloss = gloss_svc
    app.state.duplicates = duplicates_svc
    app.state.deletions = deletions_svc
    app.add_exception_handler(ReviewError, review_error_handler)

    @app.middleware("http")
    async def local_only(request: Request, call_next):
        """ローカル限定の守り（design.md §6.3.1）。認証は入れない代わりにここで弾く。

        **アプリ全体に掛ける**ので、P5-1 で足した口（`/api/reviews` など）にも効く（点検 C15）。
        """
        host = (request.headers.get("host") or "").split(":")[0]
        if host not in ALLOWED_HOSTS:
            return JSONResponse({"detail": "host not allowed"}, status_code=403)
        if request.method not in ("GET", "HEAD", "OPTIONS"):
            origin = request.headers.get("origin")
            if origin and origin.split("//")[-1].split(":")[0] not in ALLOWED_HOSTS:
                return JSONResponse({"detail": "origin not allowed"}, status_code=403)
            if request.headers.get("content-type", "").split(";")[0] not in ("application/json", ""):
                return JSONResponse({"detail": "content-type must be application/json"}, status_code=403)
        return await call_next(request)

    app.include_router(reviews_api.router)
    app.include_router(groups_api.router)
    app.include_router(export_api.router)
    # P5-2: 比較（`/api/compare` と `/api/groups/{id}/compare`）。守りは上の middleware が掛かる
    app.include_router(compare_api.router)
    # P6-1a: 要求（`/api/review-requests`）。**載せ忘れると守りが効かない**ので §8.1 の 24 で見る
    app.include_router(requests_api.router)
    # P6-2: 注記（`/api/assets/{id}/annotations` と `/api/annotations/...`）。同じく守りは middleware
    app.include_router(annotations_router)
    app.include_router(tags_api.router)
    app.include_router(duplicates_api.router)
    # P8-2: 削除（`/api/locations/...` と `/api/pending-deletes`・`/api/deletions`・`/api/trash`）
    app.include_router(deletions_api.router)

    def _asset_or_404(asset_id: str) -> dict:
        asset = store.asset(asset_id)
        if asset is None:
            raise HTTPException(404, "asset not found")
        return asset

    def _primary_path(asset: dict) -> str | None:
        locs = [l for l in asset["locations"] if not l.get("missing_at")]
        if not locs:
            locs = asset["locations"]
        if not locs:
            return None
        locs.sort(key=lambda l: (not l.get("is_primary"), l["path"]))
        return locs[0]["path"]

    def _summary(asset: dict) -> dict:
        meta = asset.get("meta") or {}
        return {
            "id": asset["id"],
            "sha256": asset["sha256"],
            "size": asset["size"],
            "width": asset["width"],
            "height": asset["height"],
            "format": asset["format"],
            "kind": asset["kind"],
            "review_state": asset["review_state"],
            "has_provenance": bool(meta),
            "meta_note": asset.get("meta_note"),
            "model": meta.get("model"),
            "seed": meta.get("seed"),
            "steps": meta.get("steps"),
            "sampler": meta.get("sampler"),
            "has_textgen": bool(meta.get("has_textgen")),
            "ja_text": meta.get("ja_text"),
            "path": _primary_path(asset),
            "location_count": len(asset["locations"]),
            "missing": all(l.get("missing_at") for l in asset["locations"]) if asset["locations"] else True,
            # P8-2: 段 1〜3 で外した印（**一覧の既定から外す**ための欄。§4.1）
            "deleted_at": asset.get("deleted_at"),
        }

    # ---- API ----

    @app.get("/api/health")
    def health():
        # app と pid は「自分かどうか」の識別に使う（設計 §4.1。点検 C21）。
        # ポートが埋まっているときに自分か別のアプリかを区別できないと、他人の画面を開いてしまう。
        return {"ok": True, "app": "image-reviewer", "version": app.version, "pid": os.getpid(),
                "started_at": _STARTED_AT, "data_dir": str(data_dir()),
                "gui_dir": str(GUI_DIR), "gui_present": GUI_DIR.exists()}

    @app.get("/api/stats")
    def stats():
        return store.stats()

    @app.get("/api/assets")
    def list_assets(
        state: str | None = None,
        q: str | None = None,
        provenance: str | None = Query(None, description="with | without"),
        tag: str | None = Query(None, description="語で絞る（P4-1。§3.6）"),
        known: str = Query("1", description="1（語彙にある語・既定）| 0 | all"),
        include_deleted: str = Query("0", description="1 で段 1〜3 で外した画像も出す（P8-2）"),
        limit: int = 100,
        cursor: int = 0,
        sort: str = "path",
    ):
        items = [_summary(a) for a in store.assets()]
        # P8-2（設計 §4.1・§8.1 の 25）: **段 1〜3 で外した画像は既定で一覧に出さない**。
        # `include_deleted=1` のときだけ出す（外した物が消えないと段 1 の意味が無い）
        if include_deleted not in ("0", "1"):
            raise ReviewError(422, "include_deleted は 0 | 1 です",
                              details={"include_deleted": "0 | 1"})
        if include_deleted != "1":
            items = [i for i in items if not i["deleted_at"]]
        if state:
            items = [i for i in items if i["review_state"] == state]
        if provenance == "with":
            items = [i for i in items if i["has_provenance"]]
        elif provenance == "without":
            items = [i for i in items if not i["has_provenance"]]
        if tag:
            # P4-1（§3.6）: **SQL で `asset_id` の集合を引いてから**メモリの一覧を絞る。
            # 既定は `known=1` だけに当てる（点検 §I-2。PNG の自然文で検索が汚れないように）
            if known not in ("0", "1", "all"):
                raise ReviewError(422, "known は 1 | 0 | all です", details={"known": "1 | 0 | all"})
            name = tag.strip().lower().replace(" ", "_")
            sql = ("SELECT a.asset_id FROM asset_tag a JOIN tag t ON t.id = a.tag_id"
                   " WHERE t.name = ?")
            args: list = [name]
            if known != "all":
                sql += " AND t.known = ?"
                args.append(int(known))
            with store.locked() as con:
                hit = {row["asset_id"] for row in con.execute(sql, args)}
            items = [i for i in items if i["id"] in hit]
        if q:
            needle = q.lower()
            items = [
                i for i in items
                if needle in (i["path"] or "").lower()
                or needle in (i["model"] or "").lower()
                or needle in (i["ja_text"] or "").lower()
            ]
        if sort == "model":
            items.sort(key=lambda i: ((i["model"] or "~"), i["path"] or ""))
        else:
            items.sort(key=lambda i: (i["path"] or ""))
        total = len(items)
        page = items[cursor:cursor + limit]
        return {"total": total, "cursor": cursor, "limit": limit,
                "next_cursor": cursor + limit if cursor + limit < total else None,
                "items": page}

    @app.get("/api/assets/{asset_id}")
    def get_asset(asset_id: str):
        return _asset_or_404(asset_id)

    @app.get("/api/assets/{asset_id}/file")
    def get_file(asset_id: str):
        asset = _asset_or_404(asset_id)
        path = _primary_path(asset)
        if not path or not os.path.exists(path):
            raise HTTPException(404, "実体が見つかりません")
        return FileResponse(path, headers={"Cache-Control": "no-cache"})

    @app.get("/api/assets/{asset_id}/thumb")
    def get_thumb(asset_id: str, size: int = 256):
        asset = _asset_or_404(asset_id)
        path = _primary_path(asset)
        if not path or not os.path.exists(path):
            raise HTTPException(404, "実体が見つかりません")
        try:
            # P5-3（**実測 F5**）: pHash / dHash は**この復号と同じ 1 枚**から計算する
            # （11.88 ms/枚 のうち 11.35 ms が復号。設計 §6.2 の「走査の背景ジョブ」は
            #  この実測で取り消され、サムネイル生成と同じ道になった）
            out = thumbs.ensure_thumb(
                path, data_dir(), asset["sha256"], size,
                on_image=lambda im: compare.capture_hashes(store, asset_id, im))
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(500, f"サムネイルを作れません: {exc}") from exc
        # サムネイルが**既にあった**ときは上の復号が走らないので、ハッシュだけを埋める
        # （1 枚につき 1 回で終わる。2 回目からは `asset.phash` があるので復号しない）
        if asset.get("phash") is None or asset.get("dhash") is None:
            try:
                compare.ensure_hashes(store, asset_id, path)
            except Exception:  # noqa: BLE001  ハッシュが無くても絵は返す
                log.exception("pHash を計算できませんでした: %s", path)
        return FileResponse(out, media_type="image/webp",
                            headers={"Cache-Control": "public, max-age=31536000, immutable"})

    @app.get("/api/assets/{asset_id}/graph")
    def get_graph(asset_id: str, format: str = "api"):
        """グラフ JSON。実機で確かめたとおり、API 形式のまま D&D で ComfyUI が読める。"""
        asset = _asset_or_404(asset_id)
        path = _primary_path(asset)
        if not path:
            raise HTTPException(404, "実体が無い")
        from . import png_meta

        chunks = png_meta.read_png(path)
        if not chunks:
            raise HTTPException(404, "PNG として読めない")
        key = "prompt" if format == "api" else "workflow"
        if format == "ui":
            if "workflow" not in chunks["text"]:
                raise HTTPException(404, "UI 形式のグラフを持っていない（API 生成の画像）")
        raw = chunks["text"].get(key)
        if raw is None:
            raise HTTPException(404, "グラフが無い")
        try:
            payload = json.loads(raw.decode("utf-8", "replace"))
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(500, f"グラフを読めない: {exc}") from exc
        return JSONResponse(payload, headers={
            "Content-Disposition": f'attachment; filename="{asset_id[:12]}-{format}.json"'})

    @app.post("/api/scan")
    def do_scan(payload: dict = Body(default={})):
        roots = payload.get("roots") or store.roots() or []
        if not roots:
            raise HTTPException(400, "roots が空です")
        return run_scan(store, roots)

    @app.post("/api/capture")
    def do_capture(payload: dict = Body(default={})):
        """ComfyUI の /history から英訳を捕獲する（監視の代わりの 1 回走査）。"""
        from .capture import capture_history

        stats = capture_history(store, payload.get("base_url") or "http://127.0.0.1:8188")
        if stats.get("error"):
            raise HTTPException(502, stats["error"])
        return stats

    # ---- 画面（同一オリジン） ----

    if GUI_DIR.exists():
        app.mount("/", StaticFiles(directory=str(GUI_DIR), html=True), name="gui")

    return app


app = create_app()
