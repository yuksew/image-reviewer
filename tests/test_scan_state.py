"""走査中の口（`GET /api/scan`。P8-5）のテスト。

設計: `docs/p8-design.md` §3.4（走査中は 409 を返さず待たせる）・§0.21（P8-5 で足した口）、
      `docs/frontend-design.md` §4.5.1（上部バーの「走査中です」）・§4.6（最近の削除の 1 行）

なぜ要るか（P8-3 の監査 E-6）:
    `POST /api/scan` は同期の口で **job を持たない**ので、画面に「走査中です」を出す材料が無かった。
    P8-5 で `DeletionService.scan_state()` と `GET /api/scan` を足した。

**何を壊すと落ちるか**を各テストの docstring に書いてある（家風）。
**`GET` は 1 バイトも書かない**（家風）ので、署名を前後で比べる試験を置く。
"""

from __future__ import annotations

import hashlib
import json
import threading
import time
from pathlib import Path

from fastapi.testclient import TestClient
from PIL import Image

from image_reviewer.deletions import DeletionService
from image_reviewer.store import Store

HUMAN = {"X-Image-Reviewer-Actor": "human"}


def make_png(path: Path, *, seed: int = 0) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    im = Image.new("RGB", (16, 16))
    px = im.load()
    for y in range(16):
        for x in range(16):
            px[x, y] = ((x * 7 + y * 3 + seed * 29) % 256, (x * 5 + seed * 11) % 256,
                        (y * 9 + seed * 17) % 256)
    im.save(path)
    return path


def add_asset(store: Store, path: Path) -> str:
    digest = hashlib.sha256(str(path).encode("utf-8")).hexdigest()
    asset_id, _ = store.register(
        sha256=digest, path=str(path), size=path.stat().st_size,
        mtime_ns=path.stat().st_mtime_ns, width=16, height=16, fmt="png",
        meta=None, note=None)
    return asset_id


def app_client(monkeypatch, data_dir: Path, backup_dir: Path):
    """`<data>` とバックアップの置き場を**テストの中**に向けたアプリを作る。"""
    monkeypatch.setenv("IMAGE_REVIEWER_DATA", str(data_dir))
    monkeypatch.setenv("IMAGE_REVIEWER_BACKUP_DIR", str(backup_dir))
    from image_reviewer.app import create_app
    app = create_app()
    app.state.backup.interval = 3600.0          # 周期が勝手に来ないように
    return app


def signature(root: Path) -> dict:
    """フォルダの中身の署名（名前・大きさ・**中身の sha256**）。"""
    out: dict[str, tuple[int, str]] = {}
    for path in sorted(root.rglob("*")):
        if path.is_file():
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            out[str(path.relative_to(root))] = (path.stat().st_size, digest)
    return out


def data_with_one_image(tmp_path: Path, monkeypatch) -> tuple[Path, Path]:
    data = tmp_path / "data"
    store = Store(data)
    try:
        add_asset(store, make_png(data / "a.png"))
    finally:
        store.close()
    backups = tmp_path / "backups"
    monkeypatch.setenv("IMAGE_REVIEWER_BACKUP_DIR", str(backups))
    return data, backups


# ---- 1. 読むだけの口 ----


def test_the_scan_state_is_read_only(tmp_path, monkeypatch):
    """**壊すと落ちる**: `GET /api/scan` が書くようになると（job の行・settings の印など）、
    走査中の判定を 5 秒ごとに見るだけで DB と WAL が膨らむ。

    `frontend-design.md` §4.5.1 の 6 つは**全部 `GET`**（家風「`GET` は 1 バイトも書かない」）。

    **背景のタイマーは先に止める。** 日次は**起動した直後に 1 回**動く（設計 §0.12-1）ので、
    止めないと「日次が `settings` と WAL を書いた分」が「`GET` が書いた分」と見分けられない
    （実測: この試験が 6 回に 1 回落ちた）。
    """
    data, backups = data_with_one_image(tmp_path, monkeypatch)
    app = app_client(monkeypatch, data, backups)
    with TestClient(app, base_url="http://127.0.0.1") as client:
        app.state.backup.stop()                 # 起動直後の日次が終わってから測る
        app.state.deletions.stop()
        before = signature(data)
        for _ in range(3):
            res = client.get("/api/scan", headers=HUMAN)
            assert res.status_code == 200, res.text
            body = res.json()
            assert body["scanning"] is False
            assert body["started_at"] is None and body["elapsed_sec"] is None
            assert body["note"] == "走査していません。"
            assert body["scans"] >= 0
        after = signature(data)
        assert before == after, "GET /api/scan がフォルダに何か書いた（1 バイトも書かない）"


def test_the_scan_state_checks_the_actor_vocabulary(tmp_path, monkeypatch):
    """**壊すと落ちる**: `actor_of()` を通さないと、語彙外の `actor` が素通りする
    （家風「ヘッダの語彙は口で検査する」。`CHECK` に当てて 500 にしない）。
    """
    data, backups = data_with_one_image(tmp_path, monkeypatch)
    app = app_client(monkeypatch, data, backups)
    with TestClient(app, base_url="http://127.0.0.1") as client:
        assert client.get("/api/scan", headers={"X-Image-Reviewer-Actor": "robot"}
                          ).status_code == 422
        assert client.get("/api/scan", headers=HUMAN).status_code == 200
        assert client.get("/api/scan", headers={"Host": "evil"}).status_code == 403


# ---- 2. 錠を取らずに答える（走査中でも待たない）----


def test_the_scan_state_answers_while_the_scan_holds_the_lock(tmp_path, monkeypatch):
    """**壊すと落ちる**: `scan_state()` が `self._lock` を取ると、走査が終わるまで
    `GET /api/scan` が待たされる（**走査中にだけ答えない口**になる。P8-5 の設計 §3.4）。

    `scan_guard()` が錠を握ったままでも、印は**錠の外から読める**ので即座に返る。
    """
    data, backups = data_with_one_image(tmp_path, monkeypatch)
    app = app_client(monkeypatch, data, backups)
    with TestClient(app, base_url="http://127.0.0.1") as client:
        svc: DeletionService = app.state.deletions
        entered, release = threading.Event(), threading.Event()

        def hold():
            with svc.scan_guard():
                entered.set()
                release.wait(timeout=10)

        walker = threading.Thread(target=hold)
        walker.start()
        try:
            assert entered.wait(timeout=10), "走査の錠を取れなかった"
            assert svc.scan_state()["scanning"] is True
            started = time.monotonic()
            res = client.get("/api/scan", headers=HUMAN)
            waited = time.monotonic() - started
            assert res.status_code == 200
            assert res.json()["scanning"] is True
            assert waited < 2.0, f"走査中に GET /api/scan が待たされた（{waited:.2f} 秒）"
            assert res.json()["elapsed_sec"] is not None
        finally:
            release.set()
            walker.join(timeout=10)
        assert svc.scan_state()["scanning"] is False


def test_a_real_scan_sets_and_clears_the_state(tmp_path, monkeypatch):
    """**壊すと落ちる**: `POST /api/scan` の道が `scan_guard()` を通らなくなると、
    画面の「走査中です」が 1 度も出ない（P8-3 の監査 E-6 が戻る）。

    `run_scan` を**遅い偽物**に差し替えて、走査の最中に `GET /api/scan` を読む。
    """
    import image_reviewer.app as app_module

    data, backups = data_with_one_image(tmp_path, monkeypatch)
    root = data / "lib"
    root.mkdir(exist_ok=True)
    make_png(root / "b.png", seed=3)
    entered = threading.Event()

    def slow_scan(store, roots, **kwargs):
        entered.set()
        time.sleep(0.6)
        return {"roots": roots, "seen": 1, "created": 0, "known": 0, "changed": 0,
                "images": 0, "not_image": 0, "errors": [], "with_provenance": 0, "missing": 0}

    monkeypatch.setattr(app_module, "run_scan", slow_scan)
    app = app_client(monkeypatch, data, backups)
    with TestClient(app, base_url="http://127.0.0.1") as client:
        out: list = []
        poster = threading.Thread(
            target=lambda: out.append(client.post("/api/scan", headers=HUMAN,
                                                  json={"roots": [str(root)]})))
        poster.start()
        assert entered.wait(timeout=10), "走査が始まらなかった"
        body = client.get("/api/scan", headers=HUMAN).json()
        assert body["scanning"] is True, "走査中なのに scanning が false"
        assert body["started_at"], "走査の開始時刻が無い"
        assert body["note"] == "走査中です。終わるまで削除と取り消しは待ちます。"
        poster.join(timeout=10)
        assert out and out[0].status_code == 200
        assert client.get("/api/scan", headers=HUMAN).json()["scanning"] is False


# ---- 3. 記録（JSON にして残す。監査が値を見る）----


def test_the_state_has_the_fields_the_screen_uses(tmp_path, monkeypatch):
    """画面が使う欄（`scanning` / `started_at` / `elapsed_sec` / `note`）が揃っていること。

    **壊すと落ちる**: 欄の名前を変えると、画面は「走査中です」を出せない（`pending.js` /
    `badge.js` が読む）。
    """
    data, backups = data_with_one_image(tmp_path, monkeypatch)
    app = app_client(monkeypatch, data, backups)
    with TestClient(app, base_url="http://127.0.0.1") as client:
        body = client.get("/api/scan", headers=HUMAN).json()
        assert set(body) >= {"scanning", "started_at", "elapsed_sec", "scans", "note"}
        json.dumps(body, ensure_ascii=False)                 # JSON にして返せる形
