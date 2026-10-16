"""監視の口（P7-3。設計 §3.4）。

- `GET /api/watcher` は**状態を返すだけ**（**1 バイトも書かない**）
- `POST /api/watcher/start` / `/stop` は**人だけ**（GPU とディスクを使う。§0.10）
- **常駐しない**: 開始したときだけ 2 秒ごとに回る。`enabled` は `watcher_state` の行
  （再起動したら止まっている）
"""

from __future__ import annotations

from fastapi import APIRouter, Body, Request

from ..tags import require_human                      # 人の検査は 1 か所（§0.10。P4 と同じ）
from . import actor_of, watcher_of

router = APIRouter(prefix="/api", tags=["watcher"])


@router.get("/watcher")
def get_watcher(request: Request):
    """監視の状態（**書かない**）。"""
    return watcher_of(request).status()


@router.post("/watcher/start")
def start_watcher(request: Request, payload: dict = Body(default={})):
    """監視を始める（**人だけ**）。`{base_url?}` を受ける（既定は設定 `comfyui.url`）。"""
    actor = actor_of(request)
    require_human(actor)
    return watcher_of(request).start(base_url=payload.get("base_url"), actor=actor)


@router.post("/watcher/stop")
def stop_watcher(request: Request):
    """監視を止める（**人だけ**）。**冪等**（既に止まっていても 200）。"""
    actor = actor_of(request)
    require_human(actor)
    return watcher_of(request).stop()
