"""バックアップと復元（P8-4）のテスト。

設計: `docs/p8-design.md` §0.12（バックアップと復元）・§0.16 B2/B3・§3.3（口）・
      §6.2（契約）・§8.1 の 23・24・§8.4 F7・§10-12/§10-13（壊れた DB と版）

**何を壊すと落ちるか**を各テストの docstring に書いてある（家風）。
**壊す試験は複製で**（`tmp_path` の中だけ。実データには触らない）。
**時計は注入する**（`Clock` を 1 つだけ。`time.monotonic()` を直接呼ばない）。
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image, PngImagePlugin

from image_reviewer import backup, cli, db
from image_reviewer.backup import (KEEP_SNAPSHOTS, BackupService, check_db_file, inspect_db,
                                   rebuild_metadata, restore)
from image_reviewer.review import ReviewError
from image_reviewer.store import Store, normalize_path

HUMAN = {"X-Image-Reviewer-Actor": "human"}
AGENT = {"X-Image-Reviewer-Actor": "agent"}

PAGE = 4096


# ---- 道具 ----


class FakeClock:
    """テスト用の時計（**壁と単調の両方を 1 つの口から進める**。`test_clock.py` と同じ形）。"""

    def __init__(self, *, wall: float = 1_700_000_000.0, mono: float = 1000.0):
        self._wall = wall
        self._mono = mono

    def now(self) -> str:
        return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(self._wall))

    def monotonic(self) -> float:
        return self._mono

    def advance(self, *, sec: float = 0.0, mono: float = 0.0) -> None:
        self._wall += sec
        self._mono += mono


def make_png(path: Path, *, seed: int = 0, prompt: dict | None = None) -> Path:
    """合成の PNG（`seed` で中身を変える。`prompt` を渡すと生成の来歴を埋め込む）。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    w = h = 16
    im = Image.new("RGB", (w, h))
    px = im.load()
    for y in range(h):
        for x in range(w):
            px[x, y] = ((x * 7 + y * 3 + seed * 29) % 256, (x * 5 + seed * 11) % 256,
                        (y * 9 + seed * 17) % 256)
    if prompt is None:
        im.save(path)
    else:
        info = PngImagePlugin.PngInfo()
        info.add_text("prompt", json.dumps(prompt))
        im.save(path, pnginfo=info)
    return path


def comfy_graph(*, seed: int = 123, steps: int = 20, sampler: str = "euler",
                positive: str = "1girl") -> dict:
    """ComfyUI の API 形式のグラフ（`png_meta.analyze_graph` が読む最小の形）。"""
    return {
        "1": {"class_type": "CheckpointLoaderSimple",
              "inputs": {"ckpt_name": "anima.safetensors"}},
        "2": {"class_type": "CLIPTextEncode", "inputs": {"text": positive, "clip": ["1", 1]}},
        "3": {"class_type": "CLIPTextEncode", "inputs": {"text": "bad", "clip": ["1", 1]}},
        "4": {"class_type": "EmptyLatentImage",
              "inputs": {"width": 512, "height": 512, "batch_size": 1}},
        "5": {"class_type": "KSampler",
              "inputs": {"seed": seed, "steps": steps, "cfg": 7.0, "sampler_name": sampler,
                         "scheduler": "normal", "denoise": 1.0, "model": ["1", 0],
                         "positive": ["2", 0], "negative": ["3", 0], "latent_image": ["4", 0]}},
        "6": {"class_type": "VAEDecode", "inputs": {"samples": ["5", 0], "vae": ["1", 2]}},
        "7": {"class_type": "SaveImage",
              "inputs": {"filename_prefix": "x", "images": ["6", 0]}},
    }


def add_asset(store: Store, path: Path, *, name: str | None = None, meta: dict | None = None) -> str:
    """実体のあるファイルを 1 枚登録する。"""
    key = name or str(path)
    digest = hashlib.sha256(f"{key}".encode("utf-8")).hexdigest()
    asset_id, _ = store.register(
        sha256=digest, path=str(path), size=path.stat().st_size,
        mtime_ns=path.stat().st_mtime_ns, width=16, height=16, fmt="png",
        meta=meta, note=None)
    return asset_id


def add_decision(store: Store, asset_id: str, *, verdict: str = "keep") -> None:
    with store.transaction() as con:
        con.execute(
            "INSERT INTO decision(id, seq, subject_type, subject_id, verdict, actor,"
            " created_at) VALUES (?,?,?,?,?,?,?)",
            (db.ulid(), db.next_seq(con), "asset", asset_id, verdict, "human", db.now()))


def zero_page(path: Path, page: int) -> None:
    """**ページを 0 で潰す**（壊れた DB を作る。実データでは絶対にやらない）。"""
    start = page * PAGE
    with open(path, "r+b") as fh:
        fh.seek(start)
        fh.write(b"\x00" * PAGE)


def write_sidecar(data_dir: Path, sha256: str, **extra) -> Path:
    out = Path(data_dir) / "sidecar" / f"{sha256}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"schema": "urn:image-reviewer:sidecar", "abi": "0.1",
                               "sha256": sha256, **extra}, ensure_ascii=False),
                   encoding="utf-8")
    return out


def rows_of(store: Store) -> dict:
    """**全表の行数**（`GET` が書かないことの検査に使う）。"""
    with store.locked() as con:
        names = [r["name"] for r in con.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY name")]
        return {name: con.execute(f"SELECT count(*) AS n FROM {name}").fetchone()["n"]
                for name in names}


def files_of(root: Path) -> dict:
    """**ファイルの一覧（名前・大きさ・mtime）**（`GET` が書かないことの検査に使う）。"""
    out = {}
    for path in sorted(Path(root).rglob("*")):
        if path.is_file():
            got = path.stat()
            out[str(path.relative_to(root))] = (got.st_size, got.st_mtime_ns)
    return out


def app_client(monkeypatch, data_dir: Path, backup_dir: Path):
    """`<data>` とバックアップの置き場を**テストの中**に向けたアプリを作る。"""
    monkeypatch.setenv("IMAGE_REVIEWER_DATA", str(data_dir))
    monkeypatch.setenv("IMAGE_REVIEWER_BACKUP_DIR", str(backup_dir))
    from image_reviewer.app import create_app
    app = create_app()
    # テストの間に勝手に周期が来ないようにする（`start()` は本番と同じ道を通す）
    app.state.backup.interval = 3600.0
    return app


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def store(tmp_path: Path):
    got = Store(tmp_path / "data")
    try:
        yield got
    finally:
        got.close()


@pytest.fixture
def backups(tmp_path: Path) -> Path:
    return tmp_path / "backups"


@pytest.fixture
def svc(store: Store, clock: FakeClock, backups: Path):
    return BackupService(store, clock=clock, backup_dir=backups)


# ---- 1. 健全性（壊れた DB の 3 つの形。設計 §0.16 B3・§10-12・§10-13）----


def test_a_healthy_db_is_ok_and_the_fresh_dir_is_ok(tmp_path):
    """壊すと落ちる: `inspect_db` が `quick_check` を見なくなると、壊れた DB でも `ok` になる。

    正常な DB と、まだ DB が無いフォルダの両方が `ok`（新規は migrate が作る）。
    """
    fresh = tmp_path / "fresh"
    fresh.mkdir()
    got = inspect_db(fresh)
    assert got["mode"] == "ok" and got["reason"] == "fresh"
    assert got["read_only"] is False and got["guidance"] is None

    data = tmp_path / "data"
    store = Store(data)
    try:
        add_asset(store, make_png(data / "a.png"))
    finally:
        store.close()
    got = inspect_db(data)
    assert got["mode"] == "ok" and got["quick_check_ok"] is True
    assert got["schema_version"] == db.SCHEMA_VERSION
    assert got["read_only"] is False


def test_the_second_page_zeroed_is_broken_and_read_only(tmp_path):
    """**2 ページ目を 0 で潰した DB**（線 12 の形。点検 B3）。

    壊すと落ちる: `quick_check` の例外を捕まえない（`fetchone()[0]` を直に呼ぶ）と、
    ここで `sqlite3.DatabaseError` が上がって「壊れている」と判定できない。
    読み取りは通るので `read_only`（**書き込みの口を 503 にする**側）。
    """
    data = tmp_path / "data"
    store = Store(data)
    try:
        add_asset(store, make_png(data / "a.png"))
    finally:
        store.close()
    zero_page(data / "db.sqlite3", 1)                 # 2 ページ目（0 始まりで 1）

    got = inspect_db(data)
    assert got["mode"] == "read_only" and got["reason"] == "malformed"
    assert got["quick_check_ok"] is False
    assert "malformed" in (got["quick_check"] or "") or got["quick_check"]
    assert got["read_only"] is True
    assert "restore" in (got["guidance"] or "")       # 復元を案内する

    # 読み取りは通る（何が残っているかを見せて復元へ導く）
    ro = Store(data, read_only=True)
    try:
        assert len(ro.assets()) == 1
        with pytest.raises(ReviewError) as got_exc:
            with ro.transaction():
                pass
        assert got_exc.value.status == 503 and got_exc.value.code == "read_only"
    finally:
        ro.close()


def test_the_first_4k_zeroed_cannot_be_opened(tmp_path):
    """**先頭 4 KB を 0 で潰した DB**（開けない形。設計 §10-12）。

    壊すと落ちる: 「開けない」と「壊れているが読める」を同じ扱いにすると、
    読み取りの口まで 503 にしたつもりで 500 になる（`Store` が最初の SQL で投げる）。
    """
    data = tmp_path / "data"
    store = Store(data)
    try:
        add_asset(store, make_png(data / "a.png"))
    finally:
        store.close()
    zero_page(data / "db.sqlite3", 0)

    got = inspect_db(data)
    assert got["mode"] == "unusable" and got["reason"] == "unreadable"
    assert got["quick_check_ok"] is False
    assert "restore" in (got["guidance"] or "")

    # 接続そのものは張れる（SQLite は遅延して開く）が、**どの SQL も投げる**
    ro = Store(data, read_only=True)
    try:
        with pytest.raises(sqlite3.DatabaseError):
            ro.assets()
    finally:
        ro.close()

    # `check_db_file` も同じ判定（復元の前に見る物差し）
    assert check_db_file(data / "db.sqlite3")["ok"] is False


def test_the_300th_page_zeroed_is_also_counted_as_broken(tmp_path):
    """**300 ページ目を 0 で潰した DB**（設計 §10-12 は「`ok` になる」と書いていた形）。

    実測では壊れ方によって**例外**（`database disk image is malformed`）と
    **エラー行**（`*** in database main ***`）の 2 通りがある（実データの複製は行、
    合成のこの DB は例外）。壊すと落ちる: **例外だけ**を「壊れている」に数えると、
    行が返る形を健全と誤判定する（`docs/p8-4-implementation.md` §3 に両方の実測）。
    """
    data = tmp_path / "data"
    store = Store(data)
    try:
        blob = json.dumps({"text": "x" * 900})
        with store.transaction() as con:
            for i in range(1500):                     # 300 ページより大きくする
                con.execute(
                    "INSERT INTO asset(id, sha256, kind, kind_source, width, height, format,"
                    " first_seen_at, last_seen_at) VALUES (?,?,?,?,?,?,?,?,?)",
                    (f"A{i:06d}", f"{i:064x}", "generated", "auto", 16, 16, "png", "t", "t"))
                con.execute(
                    "INSERT INTO asset_meta(asset_id, meta_json, source, extracted_at)"
                    " VALUES (?,?,?,?)", (f"A{i:06d}", blob, "png", "t"))
    finally:
        store.close()
    assert (data / "db.sqlite3").stat().st_size > 301 * PAGE
    zero_page(data / "db.sqlite3", 300)

    got = inspect_db(data)
    assert got["quick_check_ok"] is False
    assert got["mode"] == "read_only"
    assert got["quick_check_rows"] or got["error"], "理由が残っていない"


def test_the_version_ahead_db_starts_read_only(tmp_path):
    """**DB の版がバイナリより新しい**（設計 §10-13）。拒否ではなく読み取り専用で起動する。

    壊すと落ちる: 版を `migrate()` の早期 return に任せると、新しい DB に古いコードが
    **書き込んで**しまう（P7 の廃止直後に実際に起きた）。
    """
    data = tmp_path / "data"
    store = Store(data)
    try:
        add_asset(store, make_png(data / "a.png"))
    finally:
        store.close()
    con = sqlite3.connect(str(data / "db.sqlite3"))
    con.execute(f"PRAGMA user_version = {db.SCHEMA_VERSION + 1}")
    con.close()

    got = inspect_db(data)
    assert got["mode"] == "read_only" and got["reason"] == "version_ahead"
    assert got["schema_version"] == db.SCHEMA_VERSION + 1
    assert "新しい" in (got["guidance"] or "")


def test_the_version_is_raised_only_after_a_backup(tmp_path, monkeypatch):
    """**版を上げる前に控えを取る**（設計 §0.12-6・専門 §5.4）。

    壊すと落ちる: 控えを取らずに `migrate()` を走らせると、版を上げた後の姿しか残らず、
    **上げて壊れたときに戻せない**。
    """
    data = tmp_path / "data"
    backups = tmp_path / "backups"
    store = Store(data)
    try:
        add_asset(store, make_png(data / "a.png"))
    finally:
        store.close()
    con = sqlite3.connect(str(data / "db.sqlite3"))
    con.execute(f"PRAGMA user_version = {db.SCHEMA_VERSION - 1}")   # 1 つ古い版にする
    con.close()

    app = app_client(monkeypatch, data, backups)
    with TestClient(app, base_url="http://127.0.0.1") as client:
        assert client.get("/api/health/db", headers=HUMAN).json()["schema_version"] \
            == db.SCHEMA_VERSION                                     # 上げてある
        state = client.get("/api/backup", headers=HUMAN).json()
        kinds = [s["kind"] for s in state["snapshots"]]
        assert "pre-migrate" in kinds, kinds
        pre = [s for s in state["snapshots"] if s["kind"] == "pre-migrate"][0]
        assert pre["counts"]["assets"] == 1
        assert Path(pre["dir"]).name.startswith(backup.PRE_MIGRATE_PREFIX)
        assert (Path(pre["dir"]) / "manifest.json").is_file()
    # **掃除の対象にしない**（版が上がる前の姿は残す）
    backup.prune_snapshots(backups, keep=0)
    assert any(s["kind"] == "pre-migrate" for s in backup.list_snapshots(backups))


def test_a_failed_pre_migrate_backup_does_not_raise_the_version(tmp_path, monkeypatch):
    """**控えが取れないなら版を上げない**（読み取り専用で起動して案内する。§0.12-6）。

    壊すと落ちる: 控えの失敗を握りつぶして `migrate()` を走らせると、
    **戻せないまま版が上がる**。
    """
    data = tmp_path / "data"
    store = Store(data)
    try:
        add_asset(store, make_png(data / "a.png"))
    finally:
        store.close()
    con = sqlite3.connect(str(data / "db.sqlite3"))
    con.execute(f"PRAGMA user_version = {db.SCHEMA_VERSION - 1}")
    con.close()
    # 置き場を**ファイル**にする（フォルダが作れない＝控えが取れない）
    blocked = tmp_path / "not-a-dir"
    blocked.write_text("x", encoding="utf-8")

    app = app_client(monkeypatch, data, blocked)
    with TestClient(app, base_url="http://127.0.0.1") as client:
        health = client.get("/api/health/db", headers=HUMAN)
        assert health.status_code == 503
        assert health.json()["read_only"] is True
        assert client.post("/api/backup", headers=HUMAN, json={}).status_code == 503
    con = sqlite3.connect(str(data / "db.sqlite3"))
    try:
        assert con.execute("PRAGMA user_version").fetchone()[0] == db.SCHEMA_VERSION - 1
    finally:
        con.close()


def test_a_broken_db_starts_and_the_write_endpoints_say_503(tmp_path, monkeypatch):
    """**壊れた DB でもアプリは起動し、書き込みの口は 503**（設計 §1.2 の線 12）。

    壊すと落ちる: middleware の門を外すと、壊れた DB に `POST` が通って傷が広がる
    （`GET` は生かす＝何が残っているかを見せる）。
    """
    data = tmp_path / "data"
    store = Store(data)
    try:
        add_asset(store, make_png(data / "a.png"))
    finally:
        store.close()
    zero_page(data / "db.sqlite3", 1)

    app = app_client(monkeypatch, data, tmp_path / "backups")
    with TestClient(app, base_url="http://127.0.0.1") as client:
        health = client.get("/api/health/db", headers=HUMAN)
        assert health.status_code == 503
        body = health.json()
        assert body["ok"] is False and body["read_only"] is True
        assert body["quick_check_ok"] is False
        assert "restore" in (body["guidance"] or "")
        assert client.get("/api/health", headers=HUMAN).status_code == 200
        assert client.get("/api/assets", headers=HUMAN).status_code == 200     # 読める
        assert client.get("/api/backup", headers=HUMAN).status_code == 200
        for resp in (client.post("/api/backup", headers=HUMAN, json={}),
                     client.post("/api/scan", headers=HUMAN, json={}),
                     client.patch("/api/settings", headers=HUMAN,
                                  json={"backup_dir": str(tmp_path / "b")})):
            assert resp.status_code == 503, resp.text
            assert resp.json()["code"] == "read_only"
        # 守り（Host / Content-Type）は 503 より先に効く（順序を逆にすると 403 が消える）
        assert client.post("/api/backup", headers={**HUMAN, "Host": "evil"},
                           json={}).status_code == 403


def test_an_unopenable_db_says_503_for_every_other_endpoint(tmp_path, monkeypatch):
    """**先頭 4 KB を潰した DB**: 健康の口以外は 503（読み取りも通らない）。

    壊すと落ちる: 「読める壊れ方」と同じ扱いにすると、`GET /api/assets` が 500 になる。
    """
    data = tmp_path / "data"
    store = Store(data)
    try:
        add_asset(store, make_png(data / "a.png"))
    finally:
        store.close()
    zero_page(data / "db.sqlite3", 0)

    app = app_client(monkeypatch, data, tmp_path / "backups")
    with TestClient(app, base_url="http://127.0.0.1") as client:
        assert client.get("/api/health", headers=HUMAN).status_code == 200
        health = client.get("/api/health/db", headers=HUMAN)
        assert health.status_code == 503
        assert health.json()["mode"] == "unusable"
        for resp in (client.get("/api/assets", headers=HUMAN),
                     client.get("/api/backup", headers=HUMAN),
                     client.get("/api/stats", headers=HUMAN)):
            assert resp.status_code == 503, resp.text
            assert resp.json()["code"] == "read_only"


def test_the_health_endpoint_reports_integrity_and_read_only(tmp_path, monkeypatch):
    """`GET /api/health/db` が `quick_check` / `integrity_check` と**読み取り専用か**を返す。"""
    data = tmp_path / "data"
    store = Store(data)
    try:
        add_asset(store, make_png(data / "a.png"))
    finally:
        store.close()
    app = app_client(monkeypatch, data, tmp_path / "backups")
    with TestClient(app, base_url="http://127.0.0.1") as client:
        got = client.get("/api/health/db", headers=HUMAN)
        assert got.status_code == 200
        body = got.json()
        assert body["quick_check"] == "ok" and body["integrity_check"] == "ok"
        assert body["read_only"] is False and body["mode"] == "ok"
        assert body["foreign_key_violations"] == 0
        assert body["schema_version"] == db.SCHEMA_VERSION
        assert body["expected_version"] == db.SCHEMA_VERSION
        assert body["guidance"] is None


def test_quick_check_counts_an_exception_as_broken(tmp_path):
    """壊すと落ちる: `db.quick_check` の `try/except` を外すと、壊れた DB で例外が上がる。"""
    data = tmp_path / "data"
    store = Store(data)
    try:
        add_asset(store, make_png(data / "a.png"))
    finally:
        store.close()
    zero_page(data / "db.sqlite3", 1)
    con = sqlite3.connect(f"file:{(data / 'db.sqlite3').as_posix()}?mode=ro", uri=True)
    try:
        got = db.quick_check(con)
        assert got["ok"] is False and got["error"]      # 例外の文言が残る
        assert got["detail"] == got["error"]
        info = db.integrity(con)                        # 落ちない（線 12 は「結果が出る」）
        assert info["quick_check_ok"] is False
        assert info["schema_version"] == db.SCHEMA_VERSION
    finally:
        con.close()


# ---- 2. バックアップ（日次・「いま取る」・増分・保持・WAL・契約）----


def test_the_daily_snapshot_is_taken_once_a_day(store, clock, backups, svc):
    """**同じ日は 1 回**（設計 §0.12-1・§8.1 の 23）。

    壊すと落ちる: 「今日のフォルダがあるか」を見ないと、周期ごとにフォルダが増える。
    """
    add_asset(store, make_png(store.data_dir / "a.png"))
    first = svc.tick()
    assert first["skipped"] is None and first["taken"]["name"] == backup.local_day(clock.now())
    again = svc.tick()
    assert again["skipped"] == "already" and again["taken"] is None
    clock.advance(sec=3600)                             # 同じ日の中
    assert svc.tick()["skipped"] == "already"
    assert len(backup.list_snapshots(backups)) == 1
    clock.advance(sec=86400)                            # 日が変わる
    assert svc.tick()["taken"] is not None
    assert len(backup.list_snapshots(backups)) == 2


def test_the_timer_takes_today_snapshot_without_being_asked(store, clock, backups):
    """**起動時だけでなくタイマーで回る**（点検 B2。設計 §0.16 B2）。

    壊すと落ちる: `start()` を「張るだけ」にすると、立てっぱなしのアプリで 1 日取れない。
    """
    add_asset(store, make_png(store.data_dir / "a.png"))
    svc = BackupService(store, clock=clock, backup_dir=backups, interval=0.05)
    svc.start()
    try:
        deadline = time.time() + 5.0
        while time.time() < deadline and not backup.list_snapshots(backups):
            time.sleep(0.02)
        got = backup.list_snapshots(backups)
        assert [s["name"] for s in got] == [backup.local_day(clock.now())]
        time.sleep(0.25)                                # 何周期回っても増えない
        assert len(backup.list_snapshots(backups)) == 1
    finally:
        svc.stop()


def test_now_always_takes_a_new_snapshot(store, clock, backups, svc):
    """**「いま取る」は必ず新しく取る**（同じ日でも。点検 B2・§8.1 の 23）。

    壊すと落ちる: 手動も日次と同じ名前（`<YYYYMMDD>`）にすると、2 回目が「同じ日だから」
    で**朝の物を返す**（利用者が「いま取った」と思った物が新しい保証が無い）。
    """
    add_asset(store, make_png(store.data_dir / "a.png"))
    assert svc.tick()["skipped"] is None                # 自動の分
    first = svc.snapshot(manual=True)
    second = svc.snapshot(manual=True)                  # 同じ秒でも別のフォルダ
    assert first["name"] != second["name"]
    assert "-" in first["name"] and "-" in second["name"]
    names = [s["name"] for s in backup.list_snapshots(backups)]
    assert len(names) == 3
    clock.advance(sec=61)
    third = svc.snapshot(manual=True)
    assert third["name"] != second["name"]
    assert Path(third["dir"]).name == third["name"]


def test_the_snapshot_folds_the_wal_so_decisions_are_not_lost(store, tmp_path, svc):
    """**`backup()` で WAL を畳む**（判断が抜けない。P4-0 の監査 D-1 の教訓）。

    壊すと落ちる: `sqlite3.Connection.backup()` を `shutil.copy2(db.sqlite3)` に替えると、
    `-wal` にしか無い判断が** 0 件**になる（実データの WAL は 4 MB あった）。
    """
    ids = [add_asset(store, make_png(tmp_path / f"a{i}.png", seed=i)) for i in range(3)]
    for asset_id in ids:
        add_decision(store, asset_id)
    got = svc.snapshot(manual=False)
    snap_db = Path(got["dir"]) / "db.sqlite3"
    assert backup.counts_of(snap_db)["decisions"] == 3
    assert got["manifest"]["counts"]["decisions"] == 3
    assert got["manifest"]["counts"]["assets"] == 3

    plain = tmp_path / "plain.sqlite3"
    shutil.copy2(store.data_dir / "db.sqlite3", plain)   # WAL を畳まない素のコピー
    assert backup.counts_of(plain)["decisions"] < 3, "前提: 判断はまだ WAL にある"


def test_the_snapshot_holds_what_the_design_says(store, tmp_path, svc):
    """`db.sqlite3`・`sidecar/`・`export/`・`settings.json`・`manifest.json` が入る。

    **画像とサムネイルは入らない**（参照モードでは画像は利用者の資産。設計 §0.12-1）。
    """
    add_asset(store, make_png(store.data_dir / "a.png"))
    write_sidecar(store.data_dir, "a" * 64, en_text="a girl")
    (store.data_dir / "export").mkdir(parents=True, exist_ok=True)
    (store.data_dir / "export" / "review.json").write_text("{}", encoding="utf-8")
    (store.data_dir / "thumbs" / "aa").mkdir(parents=True, exist_ok=True)
    (store.data_dir / "thumbs" / "aa" / "x.webp").write_bytes(b"thumb")

    got = svc.snapshot(manual=False)
    root = Path(got["dir"])
    assert (root / "db.sqlite3").is_file()
    assert (root / "manifest.json").is_file()
    assert (root / "settings.json").is_file()
    assert (root / "sidecar" / f"{'a' * 64}.json").is_file()
    assert (root / "export" / "review.json").is_file()
    assert not (root / "thumbs").exists()
    assert not (root / "library").exists()
    # **写しは 1 ファイルで完結する**（`-wal` / `-shm` を隣に作らない。§0.12-5）
    assert not (root / "db.sqlite3-wal").exists()
    assert not (root / "db.sqlite3-shm").exists()
    assert got["manifest"]["includes"] == {"db": True, "sidecar": True, "export": True,
                                           "library": False}
    settings = json.loads((root / "settings.json").read_text(encoding="utf-8"))
    assert settings["settings"]["backup_dir"]                  # 設定の控えが入っている


def test_the_manifest_passes_the_contract(store, tmp_path, svc):
    """**manifest が契約（`schemas/backup-manifest.schema.json`）を通る**（§6.2）。

    本物の `jsonschema` での検証は `tools/check_contract_p8.py`（実際に取った manifest を
    通す）。ここは**同じ欄・同じ形**を写した自前の検査と、値の裏取りをする。
    壊すと落ちる: `validate_manifest` を外すと、契約違反の manifest を書いてから気づく。
    """
    add_asset(store, make_png(store.data_dir / "a.png"))
    got = svc.snapshot(manual=False)
    manifest = got["manifest"]
    backup.validate_manifest(manifest)                  # 自分でも守る
    assert manifest["schema"] == "urn:image-reviewer:backup-manifest"
    assert manifest["abi"] == "0.1"
    assert manifest["app_version"]
    assert manifest["created_at"].endswith("Z")
    assert set(manifest["counts"]) == {"assets", "decisions", "groups", "annotations", "tags"}
    db_file = Path(got["dir"]) / "db.sqlite3"
    assert manifest["db_bytes"] == db_file.stat().st_size
    assert manifest["db_sha256"] == "sha256:" + backup.sha256_file(db_file)

    # 壊した物が落ちる（1 つずつ）
    for mutate in (lambda m: m.update(schema="urn:other"),
                   lambda m: m.update(abi="0.2"),
                   lambda m: m.update(created_at="2026/10/18 03:00"),
                   lambda m: m["counts"].pop("tags"),
                   lambda m: m["counts"].update(assets=-1),
                   lambda m: m.update(db_sha256="a" * 64),
                   lambda m: m["includes"].pop("db"),
                   lambda m: m.update(unknown=True),
                   lambda m: m.update(db_bytes="1")):
        broken = json.loads(json.dumps(manifest))
        mutate(broken)
        with pytest.raises(ReviewError) as got_exc:
            backup.validate_manifest(broken)
        assert got_exc.value.code == "bad_manifest"

    # 読む側も同じ検査を通る（壊れた manifest は復元の前に断る）
    (Path(got["dir"]) / "manifest.json").write_text(json.dumps({"schema": "urn:other"}),
                                                    encoding="utf-8")
    with pytest.raises(ReviewError) as got_exc:
        backup.read_manifest(Path(got["dir"]) / "manifest.json")
    assert got_exc.value.code == "bad_manifest"


def test_the_incremental_copy_does_not_copy_the_same_file_again(store, clock, backups, svc):
    """**前回と同じ物はコピーしない**（ハッシュで見る。設計 §0.12 の増分）。

    壊すと落ちる: 毎回写すと `linked` が 0 になり、**中身が同じでも容量が増え続ける**。
    """
    add_asset(store, make_png(store.data_dir / "a.png"))
    write_sidecar(store.data_dir, "b" * 64, en_text="x")
    first = svc.snapshot(manual=False)
    clock.advance(sec=61)
    second = svc.snapshot(manual=False)
    assert second["files"]["linked"] >= 1
    assert second["files"]["copied"] == 0
    a = Path(first["dir"]) / "sidecar" / f"{'b' * 64}.json"
    b = Path(second["dir"]) / "sidecar" / f"{'b' * 64}.json"
    assert a.read_bytes() == b.read_bytes()
    assert a.stat().st_ino == b.stat().st_ino            # **同じ中身を共有している**

    # 中身が変われば写す（リンクは張らない）
    (store.data_dir / "sidecar" / f"{'b' * 64}.json").write_text('{"en_text": "y"}',
                                                                encoding="utf-8")
    clock.advance(sec=61)
    third = svc.snapshot(manual=False)
    assert third["files"]["copied"] >= 1
    assert third["files"]["linked"] == 0


def test_only_the_last_seven_snapshots_are_kept(store, clock, backups, svc):
    """**直近 7 個を残す**（設計 §0.12-3）。**利用者が置いた物は消さない。**

    壊すと落ちる: 掃除を外すと無限に増える。名前で選ばずに消すと、置き場にある
    別のフォルダ（人が置いた物・`pre-restore-*`）まで消える。
    """
    add_asset(store, make_png(store.data_dir / "a.png"))
    keep_me = backups / "my-notes"
    keep_me.mkdir(parents=True)
    (keep_me / "manifest.json").write_text("{}", encoding="utf-8")
    for _ in range(KEEP_SNAPSHOTS + 2):
        assert svc.tick()["taken"] is not None
        clock.advance(sec=86400)
    names = [s["name"] for s in backup.list_snapshots(backups)]
    assert len(names) == KEEP_SNAPSHOTS
    assert keep_me.is_dir() and (keep_me / "manifest.json").is_file()
    assert not (backups / backup.local_day("2026-01-01T00:00:00Z")).exists()


def test_the_failure_is_kept_in_last_error(store, clock, backups):
    """**失敗したら `last_error` に残す**（黙って失敗しない。設計 §0.12 の 6）。

    壊すと落ちる: 例外を握りつぶすと、画面には「最後に取った時刻」だけが残り、
    **取れていないことに気づけない**。
    """
    add_asset(store, make_png(store.data_dir / "a.png"))
    bad = BackupService(store, clock=clock, backup_dir=store.data_dir / "inside")
    got = bad.tick()
    assert got["skipped"] == "failed" and got["error"]
    state = bad.state()
    assert state["last_error"] == got["error"]
    assert state["last_error_at"] == clock.now()
    assert state["count"] == 0
    # 直ったら消える（最後の失敗だけを残す）
    good = BackupService(store, clock=clock, backup_dir=backups)
    assert good.snapshot(manual=False)["name"]
    assert good.state()["last_error"] is None


def test_include_library_copies_the_images(store, tmp_path, svc):
    """`--include-library` のときだけ画像の実体を控える（既定は取らない。専門 §5.2 の 2）。"""
    path = make_png(tmp_path / "lib" / "a.png")
    add_asset(store, path)
    plain = svc.snapshot(manual=False)
    assert not (Path(plain["dir"]) / "library").exists()
    assert plain["manifest"]["includes"]["library"] is False

    got = svc.snapshot(manual=True, include_library=True)
    assert got["manifest"]["includes"]["library"] is True
    assert got["library"]["files"] == 1
    sha = store.assets()[0]["sha256"]
    assert list((Path(got["dir"]) / "library" / sha[:2]).glob(f"{sha}.*"))


def test_the_backup_dir_cannot_be_inside_the_data_dir(store, tmp_path, svc):
    """**`<data>` の中は断る**（専門 §5.1 の注記。指示書の鉄則）。

    壊すと落ちる: `<data>` を消したときに備える対策を `<data>` の中に置くと論理が閉じない。
    """
    add_asset(store, make_png(store.data_dir / "a.png"))
    with pytest.raises(ReviewError) as got:
        svc.snapshot(manual=True, out=store.data_dir / "backups")
    assert got.value.status == 422 and got.value.code == "bad_backup_dir"
    with pytest.raises(ReviewError):
        backup.check_backup_dir(store.data_dir, store.data_dir)


def test_the_backup_dir_comes_from_env_settings_or_the_default(store, monkeypatch, tmp_path):
    """置き場は **環境変数 → 設定 → 既定**の順（専門 §5.2 の 1）。既定は `<data>` の外。

    **注意**: `_seed_settings` が `backup_dir` を既定の値で先に入れるので、ふつうは
    出所が `settings` と出る（値は既定と同じ）。`default` は設定の行が無いときだけ。
    """
    monkeypatch.delenv("IMAGE_REVIEWER_BACKUP_DIR", raising=False)   # 既定を見るため
    svc = BackupService(store)
    assert svc.backup_dir() == backup.default_backup_dir()
    assert svc.backup_dir_source() == "settings"        # 種として同じ値が入っている
    assert not str(svc.backup_dir()).startswith(str(store.data_dir))

    with store.transaction() as con:
        con.execute("DELETE FROM settings WHERE key = 'backup_dir'")
    assert svc.backup_dir() == backup.default_backup_dir()
    assert svc.backup_dir_source() == "default"

    with store.transaction() as con:
        con.execute("INSERT INTO settings(key, value) VALUES ('backup_dir', ?)"
                    " ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                    (str(tmp_path / "from-settings"),))
    assert svc.backup_dir() == tmp_path / "from-settings"
    assert svc.backup_dir_source() == "settings"
    monkeypatch.setenv("IMAGE_REVIEWER_BACKUP_DIR", str(tmp_path / "from-env"))
    assert svc.backup_dir() == tmp_path / "from-env"
    assert svc.backup_dir_source() == "env"


def test_the_state_lists_the_snapshots_and_the_next_run(store, clock, backups, svc):
    """`GET /api/backup` の材料（置き場・一覧・最後・次・失敗）。**読むだけ**。"""
    add_asset(store, make_png(store.data_dir / "a.png"))
    empty = svc.state()
    assert empty["count"] == 0 and empty["last"] is None and empty["today_done"] is False
    assert empty["next_run_note"].startswith("今日の分はまだです")
    svc.tick()
    got = svc.state()
    assert got["count"] == 1 and got["today_done"] is True
    assert got["last"]["name"] == backup.local_day(clock.now())
    assert got["last_at"] == got["last"]["created_at"]
    assert got["next_run_at"] == backup.next_local_midnight(clock.now())
    assert got["read_only"] is False


# ---- 3. 復元（元の DB を退避・戻す前の quick_check・通らなければ戻す）----


def _library_with_history(tmp_path: Path) -> Path:
    """判断つきの DB を 1 つ作る（復元の試験の下ごしらえ）。"""
    data = tmp_path / "data"
    store = Store(data)
    try:
        asset_id = add_asset(store, make_png(data / "a.png"))
        add_decision(store, asset_id)
        write_sidecar(data, store.asset(asset_id)["sha256"], en_text="a girl")
    finally:
        store.close()
    return data


def test_restore_sets_the_old_db_aside_and_checks_before_adopting(tmp_path, clock, backups):
    """**元の DB を退避してから**戻し、**戻す前に `quick_check`**・戻した後に
    `integrity_check`（設計 §0.12-4・§8.1 の 24）。

    壊すと落ちる: 退避を外すと、戻した後に「元の DB はどうだったか」を確かめられない。
    """
    data = _library_with_history(tmp_path)
    store = Store(data)
    try:
        svc = BackupService(store, clock=clock, backup_dir=backups)
        snap = svc.snapshot(manual=False)
        # スナップショットの後に増やす（戻したら消える物）
        add_asset(store, make_png(data / "later.png"), name="later")
    finally:
        store.close()

    got = restore(data, Path(snap["dir"]), clock=clock, backup_dir=backups)
    assert got["manifest"]["counts"]["assets"] == 1
    assert got["before"]["ok"] is True and got["after"]["ok"] is True
    assert got["setaside"] and Path(got["setaside"]).is_dir()
    assert (Path(got["setaside"]) / "db.sqlite3").is_file()
    assert got["counts"]["decisions"] == 1

    back = Store(data)
    try:
        assert back.stats()["assets"] == 1                      # 増えた分は消えている
        assert back.con.execute("SELECT count(*) AS n FROM decision").fetchone()["n"] == 1
    finally:
        back.close()
    # 退避した DB には**増えた分が残っている**（戻す前の状態そのもの）
    old = sqlite3.connect(str(Path(got["setaside"]) / "db.sqlite3"))
    try:
        assert old.execute("SELECT count(*) FROM asset").fetchone()[0] == 2
    finally:
        old.close()
    # 写しはそのまま残る（復元は写しを動かさない）
    assert (Path(snap["dir"]) / "db.sqlite3").is_file()
    # sidecar も戻っている
    assert got["copied"]["sidecar"]["files"] == 1
    assert list((data / "sidecar").glob("*.json"))


def test_restore_refuses_a_broken_snapshot_and_puts_the_original_back(tmp_path, clock, backups):
    """**壊れた写しは採用しない**（§8.1 の 24）。`--force` で進めても、通らなければ元に戻す。

    壊すと落ちる: `integrity_check` を外すと、壊れた DB を採用して**元の DB も上書き**する。
    """
    data = _library_with_history(tmp_path)
    store = Store(data)
    try:
        svc = BackupService(store, clock=clock, backup_dir=backups)
        snap = svc.snapshot(manual=False)
    finally:
        store.close()
    zero_page(Path(snap["dir"]) / "db.sqlite3", 1)

    with pytest.raises(ReviewError) as got:
        restore(data, Path(snap["dir"]), clock=clock, backup_dir=backups)
    assert got.value.status == 409 and got.value.code == "bad_backup"

    # `--force` で進めると、置き換えた後に integrity_check が落ちて**元に戻る**
    with pytest.raises(ReviewError) as got:
        restore(data, Path(snap["dir"]), force=True, clock=clock, backup_dir=backups)
    assert got.value.code == "restore_failed"
    after = Store(data)
    try:
        assert after.stats()["assets"] == 1                     # 元の DB のまま
        assert after.con.execute("SELECT count(*) AS n FROM decision").fetchone()["n"] == 1
        assert check_db_file(data / "db.sqlite3")["ok"] is True
    finally:
        after.close()


def test_restore_needs_a_manifest(tmp_path, clock, backups):
    """`manifest.json` が無ければ断る（`--force` でだけ進む）。版と件数を先に見せるため。"""
    data = _library_with_history(tmp_path)
    store = Store(data)
    try:
        svc = BackupService(store, clock=clock, backup_dir=backups)
        snap = svc.snapshot(manual=False)
    finally:
        store.close()
    (Path(snap["dir"]) / "manifest.json").unlink()
    with pytest.raises(ReviewError) as got:
        restore(data, Path(snap["dir"]), clock=clock, backup_dir=backups)
    assert got.value.status == 409 and got.value.code == "bad_manifest"
    forced = restore(data, Path(snap["dir"]), force=True, clock=clock, backup_dir=backups)
    assert forced["manifest"] is None and forced["manifest_error"]
    assert forced["counts"]["assets"] == 1


def test_restore_puts_back_a_deleted_data_dir(tmp_path, clock, backups):
    """**`<data>` を消しても戻せる**（設計 §1.2 の線 11 の芯）。

    DB も sidecar も export も消えた状態から、スナップショットだけで戻す。
    """
    data = _library_with_history(tmp_path)
    store = Store(data)
    try:
        svc = BackupService(store, clock=clock, backup_dir=backups)
        snap = svc.snapshot(manual=False)
    finally:
        store.close()
    shutil.rmtree(data)
    assert not data.exists()

    got = restore(data, Path(snap["dir"]), clock=clock, backup_dir=backups)
    assert got["setaside"] is None                          # 元の DB が無いので退避もしない
    assert got["after"]["ok"] is True
    back = Store(data)
    try:
        assert back.stats()["assets"] == 1
        assert back.con.execute("SELECT count(*) AS n FROM decision").fetchone()["n"] == 1
    finally:
        back.close()
    assert list((data / "sidecar").glob("*.json"))


def test_the_pre_migrate_backup_honours_the_settings_dir(tmp_path, monkeypatch):
    """版を上げる前の控えも**設定の置き場**へ取る（環境変数 → 設定 → 既定）。

    壊すと落ちる: `create_app` が既定の置き場を決め打ちすると、`D:\\backups` を設定して
    いる人の控えが**知らない場所**（ホーム）に落ちる。
    """
    monkeypatch.delenv("IMAGE_REVIEWER_BACKUP_DIR", raising=False)
    data = tmp_path / "data"
    store = Store(data)
    try:
        add_asset(store, make_png(data / "a.png"))
    finally:
        store.close()
    con = sqlite3.connect(str(data / "db.sqlite3"))
    con.execute(f"PRAGMA user_version = {db.SCHEMA_VERSION - 1}")
    con.close()
    from_settings = tmp_path / "from-settings"
    con = sqlite3.connect(str(data / "db.sqlite3"))
    with con:
        con.execute("INSERT INTO settings(key, value) VALUES ('backup_dir', ?)"
                    " ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                    (str(from_settings),))
    con.close()

    app = app_client(monkeypatch, data, from_settings)
    with TestClient(app, base_url="http://127.0.0.1") as client:
        assert client.get("/api/health/db", headers=HUMAN).json()["schema_version"] \
            == db.SCHEMA_VERSION
    assert any(s["kind"] == "pre-migrate" for s in backup.list_snapshots(from_settings)), \
        "設定の置き場に控えが無い"
    assert backup.inspect_db(data)["mode"] == "ok"


def test_a_locked_db_is_reported_not_crashed(tmp_path, clock, backups, monkeypatch):
    """**アプリが動いていて置き換えられない**ときは 409 の 1 行（500 にしない）。

    壊すと落ちる: `OSError` を写さないと、`restore` がスタックトレースで死ぬ
    （人が「戻せなかった理由」を読めない）。
    """
    data = _library_with_history(tmp_path)
    store = Store(data)
    try:
        svc = BackupService(store, clock=clock, backup_dir=backups)
        snap = svc.snapshot(manual=False)
    finally:
        store.close()

    real_copy2 = shutil.copy2

    def locked(src, dst, *args, **kwargs):
        # **`<data>/db.sqlite3` を置き換える所だけ**失敗させる（退避は通す）
        if Path(dst) == data / "db.sqlite3":
            raise PermissionError(13, "アクセスが拒否されました（別のプロセスが掴んでいる）")
        return real_copy2(src, dst, *args, **kwargs)

    monkeypatch.setattr(backup.shutil, "copy2", locked)
    with pytest.raises(ReviewError) as got:
        restore(data, Path(snap["dir"]), clock=clock, backup_dir=backups)
    assert got.value.status == 409 and got.value.code == "restore_failed"
    assert "止めて" in got.value.detail
    # 退避は取れている（戻せなかっただけ）
    assert got.value.details["data_dir"] == str(data)


def test_restore_refuses_a_missing_folder(tmp_path, clock, backups):
    """無いフォルダを指定されたら 422（409 ではない。**入力の誤り**）。"""
    with pytest.raises(ReviewError) as got:
        restore(tmp_path / "data", tmp_path / "nowhere", clock=clock, backup_dir=backups)
    assert got.value.status == 422 and got.value.code == "no_snapshot"


# ---- 4. 来歴の組み直し（PNG と sidecar から。設計 §0.12-4・§10-9）----


def test_rebuild_metadata_fills_from_the_sidecar(tmp_path):
    """**sidecar から英訳が戻る**（PNG から取り直せない唯一のもの。専門 §5.1）。

    壊すと落ちる: sidecar を読まないと、DB を失ったときに英訳が永久に戻らない。
    """
    data = tmp_path / "data"
    store = Store(data)
    try:
        asset_id = add_asset(store, make_png(data / "a.png"))
        sha = store.asset(asset_id)["sha256"]
        write_sidecar(data, sha, en_text="a girl", final_prompt="1girl, a girl",
                      llm="ja2en", ja_text="女の子", meta={"model": "from-sidecar"})
        with store.transaction() as con:
            con.execute("UPDATE asset_meta SET meta_json = '{}' WHERE asset_id = ?", (asset_id,))
        got = rebuild_metadata(store)
        assert got["assets"] == 1 and got["updated"] == 1 and got["sidecars"] == 1
        assert got["from_sidecar"] == 1
        meta = store.asset(asset_id)["meta"]
        assert meta["en_text"] == "a girl"
        assert meta["final_prompt"] == "1girl, a girl"
        assert meta["ja_text"] == "女の子"
        assert meta["en_engine"] == "ja2en"
        assert meta["en_source"] == "sidecar" and meta["en_is_rederived"] == 1
        # 2 回目は何もしない（何度呼んでも同じ）
        again = rebuild_metadata(store)
        assert again["updated"] == 0 and again["unchanged"] == 1
    finally:
        store.close()


def test_rebuild_metadata_reads_the_png(tmp_path):
    """**PNG の `prompt` チャンクから**生成条件を組み直す（設計 §0.12-4）。"""
    data = tmp_path / "data"
    store = Store(data)
    try:
        path = make_png(data / "gen.png", prompt=comfy_graph(seed=777, steps=28,
                                                            sampler="dpmpp_2m"))
        asset_id = add_asset(store, path)
        with store.transaction() as con:
            con.execute("UPDATE asset_meta SET meta_json = '{}' WHERE asset_id = ?", (asset_id,))
        got = rebuild_metadata(store)
        assert got["from_png"] == 1 and got["updated"] == 1
        meta = store.asset(asset_id)["meta"]
        assert str(meta["seed"]) == "777"
        assert int(meta["steps"]) == 28
        assert meta["sampler"] == "dpmpp_2m"
    finally:
        store.close()


def test_rebuild_metadata_does_not_overwrite_the_db(tmp_path):
    """**DB にある値は上書きしない**（正は DB、sidecar は組み直しの種。専門 §5.6）。

    壊すと落ちる: 上書きすると、人が直した値や捕獲済みの英訳が**古い sidecar で戻る**。
    """
    data = tmp_path / "data"
    store = Store(data)
    try:
        path = make_png(data / "gen.png", prompt=comfy_graph(seed=777))
        asset_id = add_asset(store, path, meta={"model": "db-value", "seed": "keep-me"})
        sha = store.asset(asset_id)["sha256"]
        write_sidecar(data, sha, en_text="sidecar-text", meta={"model": "sidecar-value"})
        got = rebuild_metadata(store)
        meta = store.asset(asset_id)["meta"]
        assert meta["model"] == "db-value"                  # 上書きしない
        assert meta["seed"] == "keep-me"
        assert meta["en_text"] == "sidecar-text"            # 空いていた所だけ埋まる
        assert got["from_sidecar"] == 1
    finally:
        store.close()


def test_rebuild_metadata_counts_the_missing_files(tmp_path):
    """実体が無い枚は**数えて出す**（黙って捨てない。家風）。"""
    data = tmp_path / "data"
    store = Store(data)
    try:
        path = make_png(data / "gone.png")
        asset_id = add_asset(store, path)
        with store.transaction() as con:
            con.execute("UPDATE asset_meta SET meta_json = '{}' WHERE asset_id = ?", (asset_id,))
        path.unlink()
        got = rebuild_metadata(store)
        assert got["missing_files"] == 1
        assert got["updated"] == 0 and got["unchanged"] == 1
    finally:
        store.close()


def test_rebuild_metadata_does_not_write_in_read_only_mode(tmp_path):
    """**読み取り専用では書かない**（壊れた DB を「読み取り専用で起動」する道。§10-12）。"""
    data = tmp_path / "data"
    store = Store(data)
    try:
        asset_id = add_asset(store, make_png(data / "a.png"))
        write_sidecar(data, store.asset(asset_id)["sha256"], en_text="a girl")
    finally:
        store.close()
    ro = Store(data, read_only=True)
    try:
        with pytest.raises(ReviewError) as got:
            rebuild_metadata(ro)
        assert got.value.code == "read_only" and got.value.status == 503
    finally:
        ro.close()


# ---- 5. 口（`GET` は書かない・403 / 422）----


def test_the_backup_endpoints_work_over_http(tmp_path, monkeypatch):
    """口の往復（`POST /api/backup` → `GET /api/backup` → `GET /api/health/db`）。"""
    data = tmp_path / "data"
    store = Store(data)
    try:
        add_asset(store, make_png(data / "a.png"))
        add_decision(store, store.assets()[0]["id"])
    finally:
        store.close()
    app = app_client(monkeypatch, data, tmp_path / "backups")
    with TestClient(app, base_url="http://127.0.0.1") as client:
        made = client.post("/api/backup", headers=HUMAN, json={"include_library": False})
        assert made.status_code == 200, made.text
        body = made.json()
        assert body["manifest"]["counts"]["decisions"] == 1
        assert body["manifest"]["counts"]["assets"] == 1
        assert Path(body["dir"]).is_dir()

        state = client.get("/api/backup", headers=HUMAN).json()
        assert state["count"] >= 1
        assert state["backup_dir"] == str(tmp_path / "backups")
        assert state["backup_dir_source"] == "env"
        assert state["last_at"]
        assert state["last_error"] is None
        assert any(s["name"] == body["name"] for s in state["snapshots"])

        health = client.get("/api/health/db", headers=HUMAN)
        assert health.status_code == 200 and health.json()["quick_check"] == "ok"

        settings = client.get("/api/settings", headers=HUMAN).json()
        assert settings["backup_dir"] == str(tmp_path / "backups")
        changed = client.patch("/api/settings", headers=HUMAN,
                               json={"backup_dir": str(tmp_path / "elsewhere")})
        assert changed.status_code == 200, changed.text
        assert client.get("/api/backup", headers=HUMAN).json()["backup_dir"] \
            == str(tmp_path / "backups")                    # 環境変数が優先（§5.2 の 1）


def test_get_endpoints_write_nothing(tmp_path, monkeypatch):
    """**`GET` は 1 バイトも書かない**（家風。設計 §0.13）。

    壊すと落ちる: `GET /api/backup` が「最後に取った時刻」を書きに行く、
    `GET /api/health/db` が検査の結果を残す、といった実装はここで落ちる
    （**全ファイルの大きさと mtime、全表の行数**を前後で比べる）。
    """
    data = tmp_path / "data"
    backup_root = tmp_path / "backups"
    store = Store(data)
    try:
        add_asset(store, make_png(data / "a.png"))
        write_sidecar(data, "c" * 64, en_text="x")
    finally:
        store.close()
    app = app_client(monkeypatch, data, backup_root)
    with TestClient(app, base_url="http://127.0.0.1") as client:
        client.post("/api/backup", headers=HUMAN, json={})      # 1 つ作ってから測る
        probe = Store(data)
        try:
            before_rows = rows_of(probe)
        finally:
            probe.close()
        before_files = files_of(data)
        before_backups = files_of(backup_root)

        for path in ("/api/health", "/api/health/db", "/api/backup", "/api/settings",
                     "/api/roots", "/api/assets", "/api/stats", "/api/pending-deletes",
                     "/api/trash", "/api/deletions", "/api/duplicates/near",
                     "/api/duplicates/exact", "/api/tags"):
            resp = client.get(path, headers=HUMAN)
            assert resp.status_code < 500, f"{path}: {resp.status_code} {resp.text[:200]}"

        probe = Store(data)
        try:
            assert rows_of(probe) == before_rows
        finally:
            probe.close()
        assert files_of(data) == before_files
        assert files_of(backup_root) == before_backups


def test_the_new_endpoints_are_guarded(tmp_path, monkeypatch):
    """**`Host: evil` と `Content-Type: text/plain` は 403**（P6 の監査 C8 の流儀）。

    壊すと落ちる: ルーターを載せ忘れる（`app.include_router` を外す）と、守りが効かない。
    """
    app = app_client(monkeypatch, tmp_path / "data", tmp_path / "backups")
    with TestClient(app, base_url="http://127.0.0.1") as client:
        writes = (("post", "/api/backup", {}),
                  ("patch", "/api/settings", {"backup_dir": str(tmp_path / "x")}),
                  ("post", "/api/roots/some/allow-stage3", {"allow": True}))
        for method, path, payload in writes:
            call = getattr(client, method)
            assert call(path, headers={**HUMAN, "Host": "evil"}, json=payload).status_code == 403
            assert call(path, headers={**HUMAN, "Content-Type": "text/plain"},
                        content=b"{}").status_code == 403
        # 語彙の外の actor は 422（他の口と同じ検査を 1 か所で通す）
        assert client.get("/api/backup",
                          headers={"X-Image-Reviewer-Actor": "robot"}).status_code == 422
        assert client.post("/api/backup", headers={"X-Image-Reviewer-Actor": "robot"},
                           json={}).status_code == 422


def test_the_new_endpoints_are_human_only(tmp_path, monkeypatch):
    """**バックアップ・設定・印は人だけ**（403 `human_only`）。**読むのはエージェントも可**。

    壊すと落ちる: `require_human` を外すと、エージェントが勝手に置き場を変えられる。
    """
    app = app_client(monkeypatch, tmp_path / "data", tmp_path / "backups")
    with TestClient(app, base_url="http://127.0.0.1") as client:
        for method, path, payload in (("post", "/api/backup", {}),
                                      ("patch", "/api/settings",
                                       {"backup_dir": str(tmp_path / "x")}),
                                      ("post", "/api/roots/x/allow-stage3", {"allow": True})):
            resp = getattr(client, method)(path, headers=AGENT, json=payload)
            assert resp.status_code == 403, resp.text
            assert resp.json()["code"] == "human_only"
        assert client.get("/api/backup", headers=AGENT).status_code == 200
        assert client.get("/api/roots", headers=AGENT).status_code == 200
        assert client.get("/api/settings", headers=AGENT).status_code == 200
        assert client.get("/api/health/db", headers=AGENT).status_code == 200


def test_the_input_errors_are_422(tmp_path, monkeypatch):
    """入力の誤りは **422**（`<data>` の中・空・欄が無い・知らない置き場は 404）。"""
    data = tmp_path / "data"
    store = Store(data)
    try:
        store.set_roots([str(data)])
    finally:
        store.close()
    app = app_client(monkeypatch, data, tmp_path / "backups")
    with TestClient(app, base_url="http://127.0.0.1") as client:
        inside = client.patch("/api/settings", headers=HUMAN,
                              json={"backup_dir": str(data / "backups")})
        assert inside.status_code == 422 and inside.json()["code"] == "bad_backup_dir"
        assert client.patch("/api/settings", headers=HUMAN,
                            json={"backup_dir": "   "}).status_code == 422
        assert client.patch("/api/settings", headers=HUMAN, json={}).status_code == 422
        out_inside = client.post("/api/backup", headers=HUMAN,
                                 json={"out": str(data / "b")})
        assert out_inside.status_code == 422
        assert out_inside.json()["code"] == "bad_backup_dir"
        assert client.post("/api/roots/nope/allow-stage3", headers=HUMAN,
                           json={"allow": True}).status_code == 404
        assert client.post("/api/roots/x/allow-stage3", headers=HUMAN,
                           json={}).status_code == 422
        # `"false"` は真にしない（確認の欄は安全側に倒す。監査 X6 の流儀）
        got = client.post(f"/api/roots/{normalize_path(data)}/allow-stage3", headers=HUMAN,
                          json={"allow": "false"})
        assert got.status_code == 200 and got.json()["allow_stage3"] is False


def test_allow_stage3_marks_the_root(tmp_path, monkeypatch):
    """`POST /api/roots/{id}/allow-stage3` が `root.allow_stage3` を立てる（Q8・G-3）。

    壊すと落ちる: 印を立てられないと、実データの置き場（別のツールの管理下）で
    **段 3 が永久にできない**（`409 stage_not_allowed` のまま）。
    """
    data = tmp_path / "data"
    library = tmp_path / "library"
    library.mkdir()
    store = Store(data)
    try:
        store.set_roots([str(library)])
        assert store.con.execute("SELECT allow_stage3 FROM root").fetchone()["allow_stage3"] == 0
    finally:
        store.close()
    app = app_client(monkeypatch, data, tmp_path / "backups")
    with TestClient(app, base_url="http://127.0.0.1") as client:
        listed = client.get("/api/roots", headers=HUMAN).json()["roots"]
        assert len(listed) == 1 and listed[0]["allow_stage3"] is False
        root_id = listed[0]["id"]
        assert root_id == normalize_path(library)

        marked = client.post(f"/api/roots/{root_id}/allow-stage3", headers=HUMAN,
                             json={"allow": True})
        assert marked.status_code == 200 and marked.json()["allow_stage3"] is True
        listed = client.get("/api/roots", headers=HUMAN).json()["roots"]
        assert listed[0]["allow_stage3"] is True
        check = Store(data)
        try:
            assert check.con.execute("SELECT allow_stage3 FROM root").fetchone()[
                "allow_stage3"] == 1
        finally:
            check.close()

        # 表示のパスでも引ける（`{id}` は鍵か表示のパス）
        off = client.post(f"/api/roots/{str(library).replace(chr(92), '/')}/allow-stage3",
                          headers=HUMAN, json={"allow": False})
        assert off.status_code == 200 and off.json()["allow_stage3"] is False


# ---- 6. CLI（`backup` / `restore` / `rebuild-metadata`）----


def test_the_cli_takes_a_backup_and_restores_it(tmp_path, monkeypatch, capsys):
    """CLI の 3 つ（設計 §0.12-4）。**`--out` で置き場を指定できる**（`<data>` の外）。"""
    data = _library_with_history(tmp_path)
    out = tmp_path / "cli-backups"
    monkeypatch.setenv("IMAGE_REVIEWER_DATA", str(data))
    monkeypatch.setenv("IMAGE_REVIEWER_BACKUP_DIR", str(tmp_path / "env-backups"))

    assert cli.main(["backup", "--out", str(out)]) == 0
    printed = capsys.readouterr().out
    assert "バックアップ" in printed and str(out) in printed
    snaps = backup.list_snapshots(out)
    assert len(snaps) == 1 and snaps[0]["manual"] is True
    assert snaps[0]["counts"]["assets"] == 1

    # 消してから戻す
    shutil.rmtree(data)
    assert cli.main(["restore", snaps[0]["dir"]]) == 0
    printed = capsys.readouterr().out
    assert "戻しました" in printed
    back = Store(data)
    try:
        assert back.stats()["assets"] == 1
    finally:
        back.close()

    # 組み直し（sidecar から英訳が戻る）
    store = Store(data)
    try:
        with store.transaction() as con:
            con.execute("UPDATE asset_meta SET meta_json = '{}'")
    finally:
        store.close()
    assert cli.main(["rebuild-metadata"]) == 0
    printed = capsys.readouterr().out
    assert "組み直し" in printed
    store = Store(data)
    try:
        assert store.assets()[0]["meta"]["en_text"] == "a girl"
    finally:
        store.close()


def test_the_cli_refuses_a_backup_inside_the_data_dir(tmp_path, monkeypatch, capsys):
    """CLI でも `<data>` の中は断る（**終了コード 2**。黙って書かない）。"""
    data = _library_with_history(tmp_path)
    monkeypatch.setenv("IMAGE_REVIEWER_DATA", str(data))
    assert cli.main(["backup", "--out", str(data / "backups")]) == 2
    assert "外" in capsys.readouterr().err
    assert not (data / "backups").exists()


def test_the_cli_restore_refuses_a_bad_snapshot(tmp_path, monkeypatch, capsys):
    """壊れた写しは CLI でも断る（終了コード 2。`--force` は明示のときだけ）。"""
    data = _library_with_history(tmp_path)
    out = tmp_path / "cli-backups"
    monkeypatch.setenv("IMAGE_REVIEWER_DATA", str(data))
    monkeypatch.setenv("IMAGE_REVIEWER_BACKUP_DIR", str(tmp_path / "env-backups"))
    assert cli.main(["backup", "--out", str(out)]) == 0
    snap = backup.list_snapshots(out)[0]
    zero_page(Path(snap["dir"]) / "db.sqlite3", 1)
    assert cli.main(["restore", snap["dir"]]) == 2
    assert "壊れています" in capsys.readouterr().err
