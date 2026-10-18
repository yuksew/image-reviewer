"""重複の検出と整理（P8-1）のテスト。

設計: `docs/p8-design.md` §0.5（pHash は `GET` では計算しない）・§0.9（代表の推薦）・
      §0.10（除外と解除）・§3.1（口）・§8.1 / §8.4（壊すと落ちる）

**何を壊すと落ちるか**を各テストの docstring に書いてある（家風）。
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from image_reviewer import db
from image_reviewer.compare import hash_distance
from image_reviewer.duplicates import (BAND_GUARANTEE, BANDS, DuplicatesService, bands_of,
                                       candidate_pairs, near_groups, representative)
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


def test_bands_split_a_phash_into_sixteen_hex_digits():
    """壊すと落ちる: `BANDS` を 16 以外にする・`BAND_HEX` を 1 以外にする。

    **（P8-1 の監査 B-1）8 本 × 8bit から 16 本 × 4bit に変えた。** 旧版は「1 本は必ず一致する」
    の保証が距離 7 までで、`max_distance` を 64 まで受ける口と両立しなかった。
    """
    got = bands_of("0123456789abcdef")
    assert got == [(0, "0"), (1, "1"), (2, "2"), (3, "3"), (4, "4"), (5, "5"), (6, "6"), (7, "7"),
                   (8, "8"), (9, "9"), (10, "a"), (11, "b"), (12, "c"), (13, "d"), (14, "e"),
                   (15, "f")]
    assert len(got) == BANDS == 16
    assert BAND_GUARANTEE == 15, "帯の保証（鳩の巣）は BANDS - 1"
    # **大文字でも同じ帯**（別の帯にすると同じ絵が候補に上がらない）
    assert bands_of("0123456789ABCDEF") == got
    with pytest.raises(ValueError):
        bands_of("0123")


def test_the_band_index_never_misses_a_near_pair(store: Store, tmp_path: Path):
    """壊すと落ちる: 帯を 1 本だけ見る（`a.band = b.band` を外す）と**取りこぼす**。

    ハミング距離が `d` なら**少なくとも 1 本の帯は完全に一致する**（`d < 16`。鳩の巣）。だから
    「同じ `(band, value)` を持つ組」だけを候補にしても、**距離 15 以下の組は必ず含まれる**。
    ここでは**それぞれ違う帯のビットを 1 つだけ反転**した 15 枚を作り（距離は 2 ずつ）、
    総当たりと集合が一致することを見る。
    """
    base = 0b1010101010101010101010101010101010101010101010101010101010101010
    values: dict[str, str] = {}
    for i in range(15):
        name = f"a{i}"
        values[name] = f"{base ^ (1 << (63 - 4 * i)):016x}"
        asset_id = add_asset(store, make_png(tmp_path / "images" / f"{name}.png", seed=i),
                             name=name)
        put_phash(store, asset_id, values[name])
        values[name] = asset_id          # 以降は asset_id で扱う
    by_id = {v: k for k, v in values.items()}
    phash_of = {asset_id: f"{base ^ (1 << (63 - 4 * i)):016x}"
                for i, asset_id in enumerate(values.values())}
    got = {tuple(sorted((a, b))) for a, b, _ in candidate_pairs(store.con, 6)}
    ids = sorted(phash_of)
    want = {(a, b) for i, a in enumerate(ids) for b in ids[i + 1:]
            if (hash_distance(phash_of[a], phash_of[b]) or 99) <= 6}
    assert want, f"試験の前提が壊れている（距離 6 以下の組が 1 つも無い）: {by_id}"
    assert want <= got, f"帯が取りこぼした: {sorted(want - got)}"


def test_distances_above_the_band_guarantee_fall_back_to_brute_force(store: Store, tmp_path: Path):
    """壊すと落ちる: **16 以上で帯に頼る**（＝総当たりに落とさない）と取りこぼす。

    4bit × 16 本で「1 本は必ず一致する」のは距離 15 まで。**16 以上は帯で絞れない**ので、
    `candidate_pairs` は**総当たりに落ちる**（監査 B-1。263 枚で 20 ms）。
    距離 16 の 2 枚を入れ、`candidate_pairs(16)` が**その組を返す**ことを見る。
    """
    a = add_asset(store, make_png(tmp_path / "images" / "a.png", seed=1), name="a")
    b = add_asset(store, make_png(tmp_path / "images" / "b.png", seed=2), name="b")
    pa = int("f0f0f0f0f0f0f0f0", 16)
    # **16 本の帯それぞれで 1 ビットずつ**反転する（距離 16。**どの帯も一致しない**ので、
    # 帯の索引では絶対に候補にならない＝「保証の外」が効いていることが分かる）
    mask = sum(1 << (63 - 4 * i) for i in range(16))
    pb = pa ^ mask
    assert (pa ^ pb).bit_count() == 16, "試験の前提（距離 16）"
    put_phash(store, a, f"{pa:016x}")
    put_phash(store, b, f"{pb:016x}")
    # 帯（16 未満）では候補に入らない＝帯だけでは取りこぼす
    assert (min(a, b), max(a, b)) not in {(x, y) for x, y, _ in candidate_pairs(store.con, 15)}
    # **16 以上は総当たりに落ちる**ので取れる（監査 B-1）
    pairs = candidate_pairs(store.con, 16)
    assert (min(a, b), max(a, b)) in {(x, y) for x, y, _ in pairs}, \
        "距離 16 で帯に頼って取りこぼした（監査 B-1）"


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
    assert representative(members) == ("b", "人がキープにしたもの")


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
    assert representative(members) == ("new", "いちばん新しい（同じ寸法の作り直しは最終版を残す）")


def test_the_representative_is_deterministic():
    """壊すと落ちる: `id` の昇順を外すと、同じ入力でも答えが変わりうる。"""
    members = [member("b"), member("a")]
    assert representative(members)[0] == "a"
    assert representative(list(reversed(members)))[0] == "a"


def test_the_representative_never_recommends_a_rejected_one():
    """壊すと落ちる: `reject` を最下位にしないと、**人が「要らない」と言った物が推薦になる**
    （監査 D-3 / G-4）。"""
    members = [member("bad", width=4096, height=4096, size=99999, verdict="reject"),
               member("ok", width=64, height=64, size=10)]
    got = representative(members)
    assert got[0] == "ok", f"ボツにした枚を推薦した: {got}"
    assert got[1] == "人がボツにしていないもの", got


def test_the_reason_is_the_deciding_rule_not_the_first_difference():
    """壊すと落ちる: 理由を「群の中で最初に違う属性」にすると、**決め手と違うことを言う**（監査 D-2）。

    `A(100px, 10B)・B(100px, 20B)・C(50px, 30B)` は **B** が選ばれる（画素数で勝った）。
    理由は「画素数がいちばん多い」ではなく、**上位 2 枚（B と A）を分けた規則＝「ファイルがいちばん大きい」**。
    """
    members = [member("a", width=100, height=100, size=10),
               member("b", width=100, height=100, size=20),
               member("c", width=50, height=50, size=30)]
    assert representative(members) == ("b", "ファイルがいちばん大きい")


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


def test_cancel_stops_the_hash_job_through_the_database(store: Store, tmp_path: Path, monkeypatch):
    """壊すと落ちる: 中断の印を**自前の集合**に持つ（DB を見ない）と、**外から止められない**。

    （P8-1 の監査 C-1）`POST /api/jobs/{id}/cancel` は `JobService` が受けるので、
    ハッシュのジョブ（`DuplicatesService`）が**自分の集合だけ**を見ていると止まらない
    （実測: cancel → 200 `running` → 1 秒後 `done 263 / 263`）。印を `job` 表に置いたので、
    **どちらのサービスから立てても効く**。
    """
    import image_reviewer.compare as compare
    for i in range(5):
        add_asset(store, make_png(tmp_path / "images" / f"{i}.png", seed=i))
    real = compare.hash_file

    def slow(path):                               # 1 枚ごとに間を空けて、中断の窓を作る
        time.sleep(0.05)
        return real(path)

    monkeypatch.setattr(compare, "hash_file", slow)
    svc = DuplicatesService(store, recover=False)
    started = svc.start_compute()
    svc.cancel(started["job_id"])
    job = svc.wait(started["job_id"], timeout=60)
    assert job["state"] == "cancelled", job
    done = store.con.execute("SELECT progress_done FROM job WHERE id = ?",
                             (started["job_id"],)).fetchone()["progress_done"]
    assert done < 5, f"中断したのに全部計算した（{done} 枚）"


def test_cancel_from_the_jobs_endpoint_stops_the_hash_job(client, monkeypatch):
    """壊すと落ちる: 印を DB に置かないと、**`#/jobs` の中断ボタンが効かない**（監査 C-1）。

    `POST /api/jobs/{id}/cancel`（`JobService`）→ ハッシュの job が `cancelled` で終わる。
    """
    import image_reviewer.compare as compare
    real = compare.hash_file
    monkeypatch.setattr(compare, "hash_file", lambda path: (time.sleep(0.05), real(path))[1])
    # 5 枚登録する（口からではなく DB に直接。口は `compute` だけを試す）
    data = Path(__import__("os").environ["IMAGE_REVIEWER_DATA"])
    store = Store(data)
    try:
        for i in range(5):
            add_asset(store, make_png(data / "images" / f"{i}.png", seed=i))
    finally:
        store.close()
    got = client.post("/api/duplicates/compute", headers=HUMAN)
    assert got.status_code == 202, got.text
    job_id = got.json()["job_id"]
    assert client.post(f"/api/jobs/{job_id}/cancel", headers=HUMAN).status_code == 200
    for _ in range(200):                          # 1 枚 0.05 秒 × 5 枚＝最大 0.25 秒
        body = client.get(f"/api/jobs/{job_id}", headers=HUMAN).json()
        if body["state"] in ("done", "failed", "cancelled"):
            break
        time.sleep(0.02)
    assert body["state"] == "cancelled", body


def test_the_get_endpoints_do_not_write(store: Store, tmp_path: Path):
    """壊すと落ちる: `near` の中で pHash を計算する・`dhash` を書き換える・`job` を足す（家風）。

    **（P8-1 の監査 F-1）行数だけでなく「中身」も見る。** 前の版は `phash_band` と `asset` の
    **行数**しか比べていなかったので、**`asset.dhash` の書き換え**や **`job` の 1 行追加**を
    見逃した（監査の N10b が緑のまま通った）。ここでは**全表の行数と、pHash / dHash の値、
    実ファイルの size と mtime** を前後で比べる。
    """
    a = add_asset(store, make_png(tmp_path / "images" / "a.png", seed=1))
    b = add_asset(store, make_png(tmp_path / "images" / "b.png", seed=1))
    put_phash(store, a, "0000000000000000", dhash="1111111111111111")
    put_phash(store, b, "0000000000000000", dhash="2222222222222222")

    def snapshot() -> tuple:
        tables = sorted(row[0] for row in store.con.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
            " AND name NOT LIKE 'sqlite_%'"))
        counts = tuple((t, store.con.execute(f"SELECT count(*) AS n FROM {t}").fetchone()["n"])
                       for t in tables)
        hashes = tuple(store.con.execute(
            "SELECT id, phash, dhash FROM asset ORDER BY id").fetchall())
        files = tuple(sorted((p.name, p.stat().st_size, p.stat().st_mtime_ns)
                             for p in (tmp_path / "images").glob("*.png")))
        return counts, tuple(tuple(h) for h in hashes), files

    before = snapshot()
    svc = DuplicatesService(store, recover=False)
    svc.near(max_distance=6)
    svc.exact()
    svc.exclusions()
    svc.get(_job_id_of(store)) if _job_id_of(store) else None
    assert snapshot() == before, "GET が書いている（行数・pHash / dHash・ファイルのどれかが変わった）"


def _job_id_of(store: Store) -> str | None:
    row = store.con.execute("SELECT id FROM job LIMIT 1").fetchone()
    return row["id"] if row else None


def test_compute_includes_the_assets_that_only_lack_bands(store: Store, tmp_path: Path):
    """壊すと落ちる: 対象から「帯の無い枚」を外すと、**pHash がある 91 枚が一生群に出ない**。

    （P8-1 の監査 F-2 / N17）実データは **91 / 263 枚**に pHash だけが入っていて帯が無い
    （P5-3 が pHash を入れたが帯は P8-1 で足した）。この道を塞ぐと**その 91 枚が永久に
    候補にならない**ので、`start_compute` の対象に入れる（復号せず帯だけ書く）。
    """
    a = add_asset(store, make_png(tmp_path / "images" / "a.png", seed=1))
    put_phash(store, a, "0123456789abcdef")
    with store.transaction() as con:                # 帯だけ消す（pHash は残す）
        con.execute("DELETE FROM phash_band WHERE asset_id = ?", (a,))
    svc = DuplicatesService(store, recover=False)
    started = svc.start_compute()
    assert started["total"] == 1, "帯の無い枚が対象から外れている（監査 F-2）"
    job = svc.wait(started["job_id"], timeout=60)
    assert job["state"] == "done"
    assert store.con.execute("SELECT count(*) AS n FROM phash_band").fetchone()["n"] == BANDS


def test_one_broken_file_does_not_stop_the_job(store: Store, tmp_path: Path):
    """壊すと落ちる: 1 枚の失敗で job 全体を `failed` にすると、**残りが計算されない**。

    （P8-1 の監査 F / N27）実体の無い枚（登録後にファイルが消えた）を混ぜても、`done` で
    続き、失敗は `job_item` に 1 件残る（設計「1 枚の失敗で全体を止めない」）。
    """
    good = [add_asset(store, make_png(tmp_path / "images" / f"{i}.png", seed=i)) for i in range(2)]
    gone = add_asset(store, make_png(tmp_path / "images" / "gone.png", seed=9))
    (tmp_path / "images" / "gone.png").unlink()
    svc = DuplicatesService(store, recover=False)
    started = svc.start_compute()
    job = svc.wait(started["job_id"], timeout=60)
    assert job["state"] == "done", job
    assert job["counts"]["failed"] == 1, job
    hashed = store.con.execute("SELECT count(*) AS n FROM asset WHERE phash IS NOT NULL"
                               " AND phash <> ''").fetchone()["n"]
    assert hashed == 2, f"失敗の後ろの枚が計算されていない: {hashed}"
    assert store.con.execute("SELECT count(*) AS n FROM job_item WHERE job_id = ?",
                             (started["job_id"],)).fetchone()["n"] == 1


def test_a_stale_running_hash_job_is_marked_failed_on_the_next_start(store: Store, tmp_path: Path):
    """壊すと落ちる: `recover_stale` を無効にすると、**前のプロセスの job が running のまま**残り、
    `start_compute` が 409 で永久に詰まる（監査 F / N14）。"""
    with store.transaction() as con:
        con.execute("INSERT INTO job(id, kind, state, created_at) VALUES ('old', 'hash', 'running', 't')")
    DuplicatesService(store)                     # recover=True（既定）
    row = store.con.execute("SELECT state, message FROM job WHERE id = 'old'").fetchone()
    assert row["state"] == "failed", row
    assert "終了" in (row["message"] or ""), row


def test_near_respects_the_limit(store: Store, tmp_path: Path):
    """壊すと落ちる: `limit` を無視すると、**画面が要求した数より多く返す**（監査 F / N20）。"""
    for i in range(4):                            # 距離 0 の 4 枚＝1 群、別の 2 枚＝もう 1 群
        add_asset(store, make_png(tmp_path / "images" / f"same{i}.png", seed=1),
                  name=f"same{i}.png")
    for i in range(2):
        add_asset(store, make_png(tmp_path / "images" / f"other{i}.png", seed=2),
                  name=f"other{i}.png")
    ids = [row["id"] for row in store.con.execute("SELECT id FROM asset ORDER BY id")]
    for asset_id in ids[:4]:
        put_phash(store, asset_id, "0000000000000000")
    for asset_id in ids[4:]:
        put_phash(store, asset_id, "ffffffffffffffff")
    got = near_groups(store.con, max_distance=6)
    assert got["total_groups"] == 2, got["total_groups"]
    assert len(near_groups(store.con, max_distance=6, limit=1)["groups"]) == 1
    with pytest.raises(ReviewError) as err:      # **（監査 D-4）負や 0 は黙って 1 にしない**
        near_groups(store.con, max_distance=6, limit=0)
    assert err.value.status == 422


def test_a_deleted_asset_leaves_the_groups_and_the_pairs(store: Store, tmp_path: Path):
    """壊すと落ちる: 候補（`candidate_pairs`）で `deleted_at` を絞らないと、
    **`hashed` の数と群の中身が食い違う**（監査 C-4）。"""
    a = add_asset(store, make_png(tmp_path / "images" / "a.png", seed=1), name="a")
    b = add_asset(store, make_png(tmp_path / "images" / "b.png", seed=1), name="b")
    put_phash(store, a, "0000000000000000")
    put_phash(store, b, "0000000000000000")
    assert near_groups(store.con, max_distance=6)["total_images"] == 2
    with store.transaction() as con:             # 段 1（論理削除）
        con.execute("UPDATE asset SET deleted_at = 't' WHERE id = ?", (b,))
    got = near_groups(store.con, max_distance=6)
    assert got["hashed"] == 1, got["hashed"]
    assert got["groups"] == [], "消した枚が群に残っている（監査 C-4）"
    assert candidate_pairs(store.con, 6) == [], "消した枚が候補に残っている（監査 C-4）"


def test_an_exclusion_twice_is_fine_and_records_the_actor(store: Store, tmp_path: Path):
    """壊すと落ちる: 2 回目の除外で落ちる（`INSERT` に替える）・`actor` を記録しない（監査 F）。

    （N21 / N30）同じ組を 2 回除外しても 200 で通り（`INSERT OR REPLACE`。履歴は要らない＝§0.10）、
    記録した人は `human` のまま残る。
    """
    a = add_asset(store, make_png(tmp_path / "images" / "a.png", seed=1), name="a")
    b = add_asset(store, make_png(tmp_path / "images" / "b.png", seed=2), name="b")
    svc = DuplicatesService(store, recover=False)
    svc.exclude(a_id=a, b_id=b, reason="別物", actor="human")
    again = svc.exclude(a_id=a, b_id=b, reason="やっぱり別物", actor="human")   # 落ちない
    assert again["excluded"] is True
    items = svc.exclusions()["items"]
    assert len(items) == 1 and items[0]["actor"] == "human", items
    # **エージェントが除外したら `agent` が残る**（actor は自己申告でも記録は残す）
    svc.exclude(a_id=a, b_id=b, actor="agent")
    assert svc.exclusions()["items"][0]["actor"] == "agent"


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
    assert {r["value"] for r in rows} == {"f"}
