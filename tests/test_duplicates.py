"""重複の検出と整理（P8-1）のテスト。

設計: `docs/p8-design.md` §0.5（pHash は `GET` では計算しない）・§0.9（代表の推薦）・
      §0.10（除外と解除）・§3.1（口）・§8.1 / §8.4（壊すと落ちる）

**何を壊すと落ちるか**を各テストの docstring に書いてある（家風）。
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from image_reviewer import db
from image_reviewer.compare import hash_distance
from image_reviewer.duplicates import (BANDS, DuplicatesService, bands_of, candidate_pairs,
                                       near_groups, representative)
from image_reviewer.review import ReviewError
from image_reviewer.store import Store

# ---- 道具 ----


def make_png(path: Path, *, seed: int = 0, size: tuple[int, int] = (64, 64)) -> Path:
    """合成の PNG（`seed` で中身を変える。**同じ seed なら同じ絵**）。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    w, h = size
    im = Image.new("RGB", (w, h))
    px = im.load()
    for y in range(h):
        for x in range(w):
            px[x, y] = ((x * 7 + y * 3 + seed * 29) % 256,
                        (x * 5 + seed * 11) % 256,
                        (y * 9 + seed * 17) % 256)
    im.save(path)
    return path


def add_asset(store: Store, path: Path, *, name: str | None = None, width: int | None = None,
              height: int | None = None, mtime_ns: int | None = None) -> str:
    """実体のあるファイルを 1 枚登録する（`path` は実在するので pHash を計算できる）。"""
    key = name or path.name
    digest = hashlib.sha256(f"{key}:{path}".encode("utf-8")).hexdigest()
    asset_id, _ = store.register(
        sha256=digest, path=str(path), size=path.stat().st_size,
        mtime_ns=mtime_ns if mtime_ns is not None else path.stat().st_mtime_ns,
        width=width or 64, height=height or 64, fmt="png", meta=None, note=None)
    return asset_id


def put_phash(store: Store, asset_id: str, phash: str, dhash: str = "0" * 16) -> None:
    """pHash を直に入れる（**帯も一緒に入る**＝`store.set_hashes` の道を通す）。"""
    store.set_hashes(asset_id, phash, dhash)


@pytest.fixture
def store(tmp_path: Path):
    got = Store(tmp_path / "data")
    try:
        yield got
    finally:
        got.close()


# ---- 帯（§0.5）----


def test_bands_split_a_phash_into_eight_hex_pairs():
    """壊すと落ちる: `BANDS` を 8 以外にする・`BAND_HEX` を 2 以外にする。"""
    got = bands_of("0123456789abcdef")
    assert got == [(0, "01"), (1, "23"), (2, "45"), (3, "67"),
                   (4, "89"), (5, "ab"), (6, "cd"), (7, "ef")]
    assert len(got) == BANDS
    # **大文字でも同じ帯**（別の帯にすると同じ絵が候補に上がらない）
    assert bands_of("0123456789ABCDEF") == got
    with pytest.raises(ValueError):
        bands_of("0123")


def test_the_band_index_never_misses_a_near_pair(store: Store, tmp_path: Path):
    """壊すと落ちる: 帯を 1 本だけ見る（`a.band = b.band` を外す）と**取りこぼす**。

    ハミング距離が `d` なら**少なくとも 1 本の帯は完全に一致する**（`d < 8`）。だから
    「同じ `(band, value)` を持つ組」だけを候補にしても、**距離 6 以下の組は必ず含まれる**。
    ここでは**距離 1〜6 の組を意図的に作り**、総当たりと集合が一致することを見る。
    """
    # **それぞれ違う帯のビットを 1 つだけ反転**した 7 枚を作る（距離は 2 ずつ）。
    # **帯 0 だけを見る実装だと、帯 0 を反転した枚の組を取りこぼす**ので、
    # 「1 本でも一致すれば候補に入れる」ことが試験される（`ON a.band = b.band` を
    # 固定の帯にすると落ちる）。
    base = 0b1010101010101010101010101010101010101010101010101010101010101010
    values: dict[str, str] = {}
    for i in range(7):
        name = f"a{i}"
        values[name] = f"{base ^ (1 << (63 - 8 * i)):016x}"
        asset_id = add_asset(store, make_png(tmp_path / "images" / f"{name}.png", seed=i),
                             name=name)
        put_phash(store, asset_id, values[name])
        values[name] = asset_id          # 以降は asset_id で扱う
    by_id = {v: k for k, v in values.items()}
    phash_of = {asset_id: f"{base ^ (1 << (63 - 8 * i)):016x}"
                for i, asset_id in enumerate(values.values())}
    got = {tuple(sorted((a, b))) for a, b, _ in candidate_pairs(store.con, 6)}
    ids = sorted(phash_of)
    want = {(a, b) for i, a in enumerate(ids) for b in ids[i + 1:]
            if (hash_distance(phash_of[a], phash_of[b]) or 99) <= 6}
    assert want, f"試験の前提が壊れている（距離 6 以下の組が 1 つも無い）: {by_id}"
    assert want <= got, f"帯が取りこぼした: {sorted(want - got)}"


# ---- 代表の推薦（§0.9）----


def member(asset_id: str, **kw) -> dict:
    row = {"id": asset_id, "width": 64, "height": 64, "size": 100, "mtime_ns": 1,
           "verdict": None}
    row.update(kw)
    return row


def test_the_representative_prefers_the_one_a_human_kept():
    """壊すと落ちる: 規則 1（人がキープ）を外すと、画素数の多い方が選ばれる。"""
    members = [member("a", width=1024, height=1024, size=5000),
               member("b", width=64, height=64, size=10, verdict="keep")]
    assert representative(members) == ("b", "人がキープと言った物")


def test_the_representative_prefers_the_biggest_picture():
    """壊すと落ちる: 画素数の比較を外すと、**リサイズ違いで小さい方が残る**。"""
    members = [member("small", width=512, height=512, size=999),
               member("big", width=1024, height=1024, size=10)]
    assert representative(members)[0] == "big"


def test_the_representative_prefers_the_newer_one_when_sizes_match():
    """壊すと落ちる: 規則 4 を `mtime_ns` の**古い方**にすると、作り直しの前の版が残る。

    **同じ寸法の作り直し**（実データの 19 群）では、**新しい方が「最終版」**（点検 C2・G3）。
    """
    members = [member("old", mtime_ns=100), member("new", mtime_ns=200)]
    assert representative(members) == ("new", "新しい方（同じ寸法の作り直しは最終版を残す）")


def test_the_representative_is_deterministic():
    """壊すと落ちる: `id` の昇順を外すと、同じ入力でも答えが変わりうる。"""
    members = [member("b"), member("a")]
    assert representative(members)[0] == "a"
    assert representative(list(reversed(members)))[0] == "a"


# ---- 群（§3.1 の `near`）----


def test_near_groups_orders_by_certainty_and_reports_unhashed(store: Store, tmp_path: Path):
    """壊すと落ちる: 並びを「群の大きさ順」にすると、**確実な物から出なくなる**（§0.16）。

    距離 0 の 2 枚組と、距離 6 の 3 枚組を作る。**確実な（距離の小さい）方が先**に出るはず。
    """
    ids = {}
    for name, seed in (("a1", 1), ("a2", 1), ("b1", 2), ("b2", 2), ("b3", 3)):
        path = make_png(tmp_path / "images" / f"{name}.png", seed=seed)
        ids[name] = add_asset(store, path)
    # a1 と a2 は同じ pHash（距離 0）。b の 3 枚は 1 ビットずつ違い（鎖で距離 1 ずつ）
    put_phash(store, ids["a1"], "0000000000000000")
    put_phash(store, ids["a2"], "0000000000000000")
    put_phash(store, ids["b1"], "ffffffffffffffff")
    put_phash(store, ids["b2"], "fffffffffffffffe")
    put_phash(store, ids["b3"], "fffffffffffffffc")
    # 未計算を 1 枚混ぜる（`unhashed` に出る）
    path = make_png(tmp_path / "images" / "c1.png", seed=9)
    add_asset(store, path)
    got = near_groups(store.con, max_distance=6)
    assert got["unhashed"] == 1, "未計算の枚数を返していない"
    assert got["hashed"] == 5
    assert got["total_groups"] == 2
    first, second = got["groups"]
    assert first["max_distance_within"] == 0 and first["count"] == 2
    assert second["max_distance_within"] == 2 and second["count"] == 3
    assert first["suggested_id"] in (ids["a1"], ids["a2"])
    assert first["reason"]


def test_near_groups_respects_the_max_distance(store: Store, tmp_path: Path):
    """壊すと落ちる: `max_distance` を無視する（常に 6 で出す）と、≤3 の線が通らない。"""
    for name, phash in (("a", "0000000000000000"), ("b", "0000000000000007")):
        path = make_png(tmp_path / "images" / f"{name}.png", seed=1)
        put_phash(store, add_asset(store, path), phash)
    assert hash_distance("0000000000000000", "0000000000000007") == 3
    assert near_groups(store.con, max_distance=3)["total_groups"] == 1
    assert near_groups(store.con, max_distance=2)["total_groups"] == 0


# ---- 除外（§0.10）----


def test_an_exclusion_hides_a_pair_and_can_be_removed(store: Store, tmp_path: Path):
    """壊すと落ちる: 除外を候補から外さない・解除の口を無くす（専門 §3.1 の点検 C10）。"""
    a = add_asset(store, make_png(tmp_path / "images" / "a.png", seed=1))
    b = add_asset(store, make_png(tmp_path / "images" / "b.png", seed=1))
    put_phash(store, a, "0000000000000000")
    put_phash(store, b, "0000000000000000")
    svc = DuplicatesService(store, recover=False)
    assert svc.near(max_distance=6)["total_groups"] == 1
    svc.exclude(a_id=b, b_id=a, reason="別物", actor="human")          # **逆順で渡す**
    row = store.con.execute("SELECT a_id, b_id FROM duplicate_exclusion").fetchone()
    assert (row["a_id"], row["b_id"]) == tuple(sorted([a, b])), "正規化していない（CHECK が守る）"
    assert svc.near(max_distance=6)["total_groups"] == 0
    assert svc.exclusions()["count"] == 1
    svc.remove_exclusion(a_id=a, b_id=b)
    assert svc.near(max_distance=6)["total_groups"] == 1
    with pytest.raises(ReviewError) as got:
        svc.remove_exclusion(a_id=a, b_id=b)
    assert got.value.status == 404


# ---- pHash の計算（§0.5。`GET` では計算しない）----


def test_the_compute_job_fills_missing_hashes_and_bands(store: Store, tmp_path: Path):
    """壊すと落ちる: 帯を書かない・`phash` を書かないと、群が出ない。"""
    ids = [add_asset(store, make_png(tmp_path / "images" / f"{i}.png", seed=i)) for i in range(3)]
    assert store.con.execute("SELECT count(*) AS n FROM phash_band").fetchone()["n"] == 0
    svc = DuplicatesService(store, recover=False)
    started = svc.start_compute()
    assert started["total"] == 3
    job = svc.wait(started["job_id"], timeout=60)
    assert job["state"] == "done", job
    rows = store.con.execute("SELECT id, phash FROM asset").fetchall()
    assert all(r["phash"] for r in rows), "pHash が入っていない"
    assert store.con.execute("SELECT count(*) AS n FROM phash_band").fetchone()["n"] == 3 * BANDS
    # **2 回目は何もしない**（計算済みは対象外）
    again = svc.start_compute()
    assert again["total"] == 0


def test_a_second_compute_is_refused_while_one_runs(store: Store, tmp_path: Path):
    """壊すと落ちる: `queued` / `running` を見ないと、**2 本のジョブが同じ枚を計算する**。"""
    for i in range(2):
        add_asset(store, make_png(tmp_path / "images" / f"{i}.png", seed=i))
    with store.transaction() as con:
        con.execute("INSERT INTO job(id, kind, state, created_at) "
                    "VALUES ('busy', 'hash', 'running', 't')")
    svc = DuplicatesService(store, recover=False)
    with pytest.raises(ReviewError) as got:
        svc.start_compute()
    assert got.value.status == 409


def test_the_get_endpoints_do_not_write(store: Store, tmp_path: Path):
    """壊すと落ちる: `near` の中で pHash を計算する（家風: `GET` は 1 バイトも書かない）。"""
    a = add_asset(store, make_png(tmp_path / "images" / "a.png", seed=1))
    b = add_asset(store, make_png(tmp_path / "images" / "b.png", seed=1))
    put_phash(store, a, "0000000000000000")
    put_phash(store, b, "0000000000000000")
    before = (store.con.execute("SELECT count(*) AS n FROM phash_band").fetchone()["n"],
              store.con.execute("SELECT count(*) AS n FROM asset").fetchone()["n"])
    svc = DuplicatesService(store, recover=False)
    svc.near(max_distance=6)
    svc.exact()
    svc.exclusions()
    after = (store.con.execute("SELECT count(*) AS n FROM phash_band").fetchone()["n"],
             store.con.execute("SELECT count(*) AS n FROM asset").fetchone()["n"])
    assert before == after, "GET が書いている"


# ---- 口（§3.1）----


@pytest.fixture
def client(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("IMAGE_REVIEWER_DATA", str(tmp_path / "app"))
    from image_reviewer.app import create_app
    app = create_app()
    with TestClient(app, base_url="http://127.0.0.1") as got:
        yield got


HUMAN = {"X-Image-Reviewer-Actor": "human"}


def test_the_duplicate_endpoints_shape(client):
    """口の形（`exact` は空でも 1 行の説明を返す。§0.4）。"""
    got = client.get("/api/duplicates/exact", headers=HUMAN)
    assert got.status_code == 200 and got.json()["count"] == 0
    assert "完全に同じファイルはありません" in got.json()["message"]
    near = client.get("/api/duplicates/near", headers=HUMAN).json()
    assert near["max_distance"] == 6 and near["groups"] == [] and near["unhashed"] == 0
    assert client.get("/api/duplicates/exclusions", headers=HUMAN).json()["count"] == 0


def test_the_compute_endpoint_is_202_and_human_only(client):
    """壊すと落ちる: `require_human` を外すと**エージェントが計算を投げられる**。"""
    got = client.post("/api/duplicates/compute", json={}, headers=HUMAN)
    assert got.status_code == 202, got.text
    assert "job_id" in got.json()
    again = client.post("/api/duplicates/compute", json={},
                        headers={"X-Image-Reviewer-Actor": "agent"})
    assert again.status_code == 403 and again.json()["code"] == "human_only"


def test_the_new_duplicate_endpoints_are_guarded(client):
    """家風: 新しい口は `Host` / `Content-Type` / 語彙で守る（403 / 422）。"""
    assert client.post("/api/duplicates/exclude", json={"a_id": "x", "b_id": "y"},
                       headers={"Host": "evil", **HUMAN}).status_code == 403
    assert client.post("/api/duplicates/exclude",
                       content=json.dumps({"a_id": "x", "b_id": "y"}),
                       headers={"Content-Type": "text/plain", **HUMAN}).status_code == 403
    assert client.post("/api/duplicates/exclude", json={"a_id": "x", "b_id": "y"},
                       headers={"X-Image-Reviewer-Actor": "robot"}).status_code == 422
    assert client.get("/api/duplicates/near?max_distance=99", headers=HUMAN).status_code == 422
    # **除外は人だけ**（エージェントは 403）
    assert client.post("/api/duplicates/exclude", json={"a_id": "x", "b_id": "y"},
                       headers={"X-Image-Reviewer-Actor": "agent"}).status_code == 403


def test_the_store_writes_bands_whenever_it_writes_a_phash(store: Store, tmp_path: Path):
    """壊すと落ちる: `store.set_hashes` から帯の書き込みを外すと、**pHash と帯が食い違う**。

    食い違うと「近いのに候補に出ない」（取りこぼし）が起きる。**書き手を 1 つにする**（§0.5）。
    """
    asset_id = add_asset(store, make_png(tmp_path / "images" / "a.png", seed=1))
    put_phash(store, asset_id, "0123456789abcdef")
    rows = store.con.execute("SELECT band, value FROM phash_band WHERE asset_id = ?"
                             " ORDER BY band", (asset_id,)).fetchall()
    assert [(r["band"], r["value"]) for r in rows] == bands_of("0123456789abcdef")
    # 上書きすると**古い帯が残らない**
    put_phash(store, asset_id, "ffffffffffffffff")
    rows = store.con.execute("SELECT value FROM phash_band WHERE asset_id = ?",
                             (asset_id,)).fetchall()
    assert {r["value"] for r in rows} == {"ff"}
