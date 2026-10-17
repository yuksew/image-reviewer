"""帯索引の取り落としの再発防止を、**実データと同じ形**で確かめる（P8-3 の取り落とし調査）。

`docs/p8-3-band-miss.md`。実データ（`.data`・v6・263 枚）で
`GET /api/duplicates/near?max_distance=6` が **20 群 / 55 枚**を返し、総当たりの **21 群 / 57 枚**
と食い違い、「帯の取りこぼし」に見えた。**原因は「別物として確定」の 1 行**だった——
帯は 4208 行が `asset.phash` と完全に一致し、**0〜15 のどの距離でも取りこぼし 0**、
4208 = 263 × 16 で欠けも無し（`docs/p8-3-band-miss.md` の表）。

だからここでは**実データと同じ 263 個の pHash**を合成の DB に入れ、

1. 帯の候補（`candidate_pairs`）が**総当たりと 1 組も違わない**（**0〜64 の全部**）
2. **API の群の数と枚数**が総当たりから出した数と一致する（≤0 / ≤3 / ≤6 / ≤10 / ≤15 / ≤16）
3. 除外が 1 組あるときは **`excluded_pairs` で数の辻褄が合う**
   （20 群 / 55 枚 = 総当たり 21 群 / 57 枚 − 除外 1 組。**実データで起きたことそのもの**）

を確かめる。**何を壊すと落ちるか**は各テストの docstring に書いてある（家風）。
"""

from __future__ import annotations

import hashlib
import os
import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from image_reviewer.duplicates import (BANDS, MAX_DISTANCE_LIMIT, candidate_pairs,
                                       near_groups)
from image_reviewer.store import Store

# ---- 実データの写し（`.data/db.sqlite3` を `mode=ro` で読んだだけ。2026-10-18）----

#: **実データの `asset.phash` を id 昇順に控えた 263 個**（画像も DB も動かしていない）。
#: ここに写すのは**形を固定するため**（実データが増えてもこの試験は動く）。
REAL_PHASHES: tuple[str, ...] = (
    "ea45a38e94a5ad96", "aced959143e0e647", "ab3db868b991c195", "ffa87dc154a48781",
    "af37f2305ccb7048", "bc43a6831369eace", "fbb1a8c4b4b2c3c2", "9bdc48b2edc4c346",
    "bc693db345135691", "8ebfe840c184c9df", "e929586651f57307", "fa20e1e10d8fcf98",
    "ce3949e3a487d392", "9e64d70eedf102c2", "ad6bd090963eb4c9", "cacfe8c0e183b11f",
    "d405e266ab7c91e9", "ab3db9e81170d6c1", "c916b4e9e0b4adc5", "b82f225b1169f1ec",
    "e3c2919e1af02bc7", "fbf4bac02da4a4c1", "aff1a496d4a690c3", "97dd5894a8dac742",
    "be308b22ed9919dc", "e2ad229e94db989c", "bfb8b0728960c3e9", "bc724cf240f6a21f",
    "fb9391321e6168e5", "8f37f2b21049f0cd", "97995ca0adc3ef02", "c868979163c3ea6e",
    "ad7cb1b1c6f060c3", "dc2283ecbb788ccc", "efb538c858b883d2", "fe20e1e10d8f8f98",
    "ad3c91963c2e3993", "bfbdf0305853e181", "97d918c05ac3e6c7", "b7d918b2aac25acc",
    "ba66e194c1b59792", "991dc58fea327684", "adbc86e3899293c3", "97d8188069cbef65",
    "8d9e96e189f283c6", "e36c999c3232999b", "b7d0d896f9c0cb06", "93e7af12b04b93c8",
    "bc328923edb918dc", "97d1b8d0c8c2cee9", "e36069c966c7c696", "97d858b6e8caca68",
    "9799388eabc3c646", "eca87dc4919585d3", "cb16b6e970648dc3", "adbcc6c3899293c3",
    "ec6ab91246e96e43", "b634199863c3cbcb", "d580d5aad7aaaa2a", "fa25a29339858f8d",
    "92d958d3adc4c74c", "9c75f1c6e99d2181", "ce3f5873378c9118", "dc2383ec9b699cc4",
    "eebd48c5a58cc585", "bed3c1334f2ce830", "fa20e1e10d8fcf98", "c917166969b06dcb",
    "e66593929a9369c9", "cb16164363b16fb1", "bc70e39f83494719", "f007e83b436bcd68",
    "cc6665501bf84779", "af9791c242f84ee1", "8f763c932350c9e9", "aced959157e04647",
    "ac3c91913e3e87c3", "cd2cbcdc66999292", "fc7f2346894c8d25", "fa36c981e4c78db0",
    "fa24a1d321a7879e", "be1994943e3a8f85", "be20e317414bd5d9", "b396cc2b902afa47",
    "bc43a68b1369e8ce", "bfb89072c8e0c379", "b331c62fcdc21d98", "e876bd0553cd6a42",
    "fa74a18355b486c7", "97dd18d8eec2c6c0", "ea3cb90747d96342", "bfb89072c8e0c379",
    "90536b3532d25dec", "ff753cc054d4e0c1", "bc328b23ed9918dc", "cecfde84f181a2c2",
    "e3a7960e0cf91987", "eb86919e1e7128c7", "abbdb4c94195e087", "eef438c1547c83c6",
    "eed1bae294aba0c4", "eeb9bbc4a614b2c0", "e876bd0553ad6a42", "e2e53494b68d9c9c",
    "8eabe8c1e583c3b2", "959d82d2e4339ccb", "ecfcb511c1c846c7", "eb34a0c1ad83c78f",
    "efa5843bd2d2e148", "ab8795e616b038b3", "e6b34918a63b9387", "eff2a4c014b1c2dd",
    "fdf639c014b3c2c1", "911482d3fc73d987", "f025ee62c9710dc7", "ccb909cda897b1d4",
    "bcb82d325017f4ae", "96379ab38dda6148", "bfb89072c8e0c379", "97d918a8edc7c780",
    "bf98f03389609b39", "9e33cb610ef91ac8", "97d91880dac3e6c7", "ec3c91963c3e3193",
    "eb36a9d934c3c584", "a9ec9593075364cb", "8fb7f2b23049f0c8", "bf1cc5c56b2a94c1",
    "ad763db9035047e4", "aa55d555d455d055", "cbfc94c10192b39f", "e661499933969e96",
    "dc6666d13be0cc19", "eeb5adc09caacac0", "e361cc98b296cecc", "eeb5a8c4d48eaac2",
    "bfc1e490c4c79393", "ec68b91256e96e43", "bc720cf241f6a21f", "db74e1c1d689c6a2",
    "92d95c8678c6c7c5", "eeb784c652ab1d90", "f007e83b416bcd6c", "ec9195b452c8add9",
    "bac5e495c0e3b2a3", "f007e83b416bcd6c", "827a7d559b4c0ec5", "cbbc94c10392fb87",
    "dfd49be484aa61c8", "cc79735284a1eb5c", "eeb4acc494b2c3c3", "985dd406e7b531c9",
    "b334cbcccc3370cc", "895e96e9c990c5cb", "ff72b1c056a2c784", "afe52e9dc084b591",
    "fa22a0d3ac8f8f98", "802a7f2a7f2a55aa", "fa64a98b3142cec7", "97dc58b6e8cac268",
    "cc3f6d60a18517da", "ce3841f3a687d392", "c96c95b163a0ea67", "b396cc3b902afa45",
    "90536b3532d25dec", "b33dce8321649b8e", "f007e83b416bcd6c", "8eabe8c1e583e1b2",
    "93d818aae9eec386", "be328b23edb910d8", "aa25bdc859d1c5d2", "efb4c0c437a60e5c",
    "db06b4e9e0a6a5c5", "c83f64d1b9269999", "bfdc18b608c2c27e", "99fe71e2064d462b",
    "9b9128f78c26553b", "edf2b5c058b2a2ca", "9d45b4bf65404727", "9e63dc6ce2fb20c0",
    "93bc7cca838189bd", "b30e0471fea4ae53", "dcb0684a96a5c7ce", "8e8ea89435f596d2",
    "9df331cc80acaac7", "8e10f5e25b09e9da", "bc388322cdb9b9d8", "fda0b8e5ae8586c4",
    "cbbc94c1c3927396", "99f6528e0f1b1674", "f0a5e83a416acd4f", "bbfc7cb090d4c2a2",
    "919387ce4d99c457", "fcb999f5b8948182", "97a028fd4683c776", "9bfff0b0c0c16790",
    "aaa3a871e971c355", "bbbac44ea91bc22c", "88dbd4a1fa1ca9a5", "fe3d5da384851392",
    "bda60069ec45d9ce", "b7d8185159c3e6c6", "d12d66da9c49a1bc", "86ac135ed5c1c4e7",
    "aefbe8c1a183c1b2", "bb2d2d445250cf6d", "9d8bc933565264b6", "89f8f4470b34cd47",
    "9fbff8b0c2c461c0", "a8a93b6663b1e255", "9f9ea005c8dec969", "a49d96bbd0d189d8",
    "88080ef77516f1f3", "b1b9bcb4578ce444", "b1bbe0c461b2c6d9", "9ace7ac842c4cdd9",
    "99dcc4c38b54cd59", "979c50f6e142c66d", "9fb915148de294d6", "bc725cf201e6a21f",
    "d68edbdb8161211e", "9c9b9674cab794c0", "89de3ea5c5611a8b", "bbfb81a097528c4d",
    "82afe5cfc871d818", "ec7ab91656c16643", "b8f884c4ea3dc137", "bb9eac858959c5c1",
    "bcb8e84367538547", "83a4ed73c850f173", "81938734dd19dd78", "9bbb255cccc35845",
    "aeb4f04543c186df", "9d9c94b38361a597", "aced959143e0e647", "9dcc50a0aaf4e36b",
    "bc0ba6831361f8de", "8fb7f2b21049f0c9", "d9b1cc8c35998fc8", "bfbdfcce84c24220",
    "8f3e808bc8ebdb81", "bda62250f7dc6143", "86a67c4e6b9986c5", "999b8484fee48753",
    "cbbc94c10392f397", "8e86dc4e3939c4d6", "e664c99db28b3c62", "8c899d569a95b356",
    "e6999923999a9966", "e8b79458d34dc919", "b3ccc9dbcb261c0c", "8e50f5e759498d8a",
    "b4562b0532f2ddac", "89fc44638b74c973", "b6ff49060b5f4988", "9ddf5c9941404bba",
    "9ebce0c12591c7c7", "8bbebc798c015395", "9c5362f85650e3ba", "e5e5e3e414a60ed1",
    "e639999accce892c", "e6798cce193199cc", "e6c69993cc8c9b2c",
)

#: 実データで観測した**総当たりの組数**（距離 → 組数）。同じ形なら同じ数になる
REAL_BRUTE = {0: 9, 3: 27, 6: 54, 10: 88, 15: 190, 16: 326, 32: 25132, 64: 34453}

#: 実データで「別物として確定」されていた 2 枚の pHash（**距離 4**。`duplicate_exclusion` の 1 行）
REAL_EXCLUDED_PHASHES = ("ce3949e3a487d392", "ce3841f3a687d392")

#: 除外なしのときに実データで観測した群の数と枚数（距離 → (群, 枚)）
REAL_GROUPS = {0: (5, 12), 3: (17, 39), 6: (21, 57), 10: (28, 87)}


# ---- 道具 ----


def _register(store: Store, index: int, phash: str) -> str:
    """1 枚を登録して pHash と帯を入れる（`store.set_hashes` の道を通す）。"""
    asset_id, _ = store.register(
        sha256=hashlib.sha256(f"real-shape-{index}".encode("utf-8")).hexdigest(),
        path=f"C:/made-up/real-shape-{index:03d}.png", size=100_000 + index,
        mtime_ns=1_700_000_000_000_000_000 + index, width=1024, height=1024,
        fmt="png", meta=None, note=None)
    store.set_hashes(asset_id, phash, "0" * 16)
    return asset_id


def _fill(store: Store) -> None:
    """**263 枚を 1 取引で**入れる（`register` も `set_hashes` も入れ子は外側に乗る）。"""
    assert len(REAL_PHASHES) == 263, f"実データの写しが 263 個でない: {len(REAL_PHASHES)}"
    with store.transaction():
        for index, phash in enumerate(REAL_PHASHES):
            _register(store, index, phash)


def _all_pairs(phash_by_id: dict[str, str]) -> list[tuple[str, str, int]]:
    """**全組のハミング距離**（帯を通さない物差し。34,453 組）。"""
    ids = sorted(phash_by_id)
    values = {i: int(phash_by_id[i], 16) for i in ids}
    return [(a, b, (values[a] ^ values[b]).bit_count())
            for i, a in enumerate(ids) for b in ids[i + 1:]]


def _groups_of(edges: set[tuple[str, str]]) -> tuple[int, int]:
    """組（辺）から**群の数と枚数**を出す（`near_groups` と同じ連結成分）。"""
    parent: dict[str, str] = {}

    def find(x: str) -> str:
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for a, b in edges:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra
    groups: dict[str, set[str]] = {}
    for a, b in edges:
        groups.setdefault(find(a), set()).update((a, b))
    return len(groups), sum(len(m) for m in groups.values())


def _rows_of(path: Path) -> dict[str, str]:
    """合成の DB から `id -> phash` を読む（**読むだけ**）。"""
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    try:
        return {r["id"]: r["phash"] for r in
                con.execute("SELECT id, phash FROM asset WHERE phash IS NOT NULL")}
    finally:
        con.close()


def _db_path() -> Path:
    return Path(os.environ["IMAGE_REVIEWER_DATA"]) / "db.sqlite3"


def _ids_with_phash(phash: str) -> list[str]:
    con = sqlite3.connect(f"file:{_db_path()}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    try:
        return [r["id"] for r in con.execute("SELECT id FROM asset WHERE phash = ?", (phash,))]
    finally:
        con.close()


@pytest.fixture
def real_store(tmp_path: Path):
    """**実データと同じ形**（263 枚・同じ pHash・帯 4208 行）の合成 DB。"""
    store = Store(tmp_path / "real263")
    try:
        _fill(store)
        yield store
    finally:
        store.close()


@pytest.fixture
def real_client(tmp_path: Path, monkeypatch):
    """同じ形の DB を立てたアプリ（**HTTP の口**で見る）。"""
    data = tmp_path / "app263"
    store = Store(data)
    try:
        _fill(store)
    finally:
        store.close()
    monkeypatch.setenv("IMAGE_REVIEWER_DATA", str(data))
    from image_reviewer.app import create_app
    with TestClient(create_app(), base_url="http://127.0.0.1") as got:
        yield got


HUMAN = {"X-Image-Reviewer-Actor": "human"}


# ---- 1. 帯 vs 総当たり（0〜64 の全部。関数の層）----


def test_the_band_candidates_equal_the_brute_force_at_every_distance(real_store: Store):
    """壊すと落ちる: `bands_of` の切り出しを 1 つずらす・帯の行を 1 本落とす・
    `candidate_pairs` の結合から `bb.value = ba.value` を外す（**取りこぼしが出る**）。

    **実データと同じ 263 個の pHash**で、**0〜64 の全部の距離**で集合が一致することを見る
    （P8-3 の調査。前は (0, 3, 6, 10, 15, 16, 32, 64) の 8 段だけだった）。
    """
    con = real_store.con
    phash_by_id = {r["id"]: r["phash"] for r in con.execute("SELECT id, phash FROM asset")}
    assert len(phash_by_id) == 263, "263 枚そろっていない"
    assert con.execute("SELECT count(*) AS n FROM phash_band").fetchone()["n"] == 263 * BANDS
    pairs = _all_pairs(phash_by_id)
    assert len(pairs) == 263 * 262 // 2 == 34_453
    # **実データで観測した組数と同じ**（形が同じであることの確認）
    for dist, n in REAL_BRUTE.items():
        assert sum(1 for _, _, d in pairs if d <= dist) == n, \
            f"距離 ≤{dist} の総当たりが実データと違う（写しが壊れている）"
    for dist in range(0, MAX_DISTANCE_LIMIT + 1):
        want = {(a, b) for a, b, d in pairs if d <= dist}
        got = {tuple(sorted((a, b))) for a, b, _ in candidate_pairs(con, dist)}
        assert got == want, (f"距離 ≤{dist} で帯の候補と総当たりが食い違う: "
                             f"取りこぼし {len(want - got)} / 余分 {len(got - want)}"
                             f"（例 {(sorted(want - got) or sorted(got - want))[:3]}）")


# ---- 2. API の群の数と枚数（総当たりから出した数と一致するか）----
def test_the_bands_look_at_all_sixty_four_bits(tmp_path: Path):
    """壊すと落ちる: 帯の切り出しが **64bit の一部しか見ていない**（前半 8 文字だけ見る・
    2 文字ずつ取る＝旧 8 本 × 8bit と同じ型の穴。P8-1 の監査 B-1 の親戚）。

    **実データの形だけではこの穴は捕まらない**（実測: 実データの距離 ≤15 の 190 組は**全部が
    前半 8 文字のどれかでも一致する**ので、前半だけ見ても取りこぼしが出ない）。だからここで
    **鳩の巣の境界**を 1 組だけ置く: 距離 15 で、**一致する帯が 15 本目だけ**の組
    （`0000000000000000` と `8888888888888880`。1 本ずつ 1 ビット反転 × 15 本）。
    64bit の全部を見ていれば ≤15 で見つかり、一部しか見ていなければ落ちる。
    """
    store = Store(tmp_path / "boundary")
    try:
        left, right = "0000000000000000", "8888888888888880"
        a = _register(store, 0, left)
        b = _register(store, 1, right)
        assert (int(left, 16) ^ int(right, 16)).bit_count() == 15, "前提（距離 15）"
        assert [i for i in range(16) if left[i] == right[i]] == [15], "前提（一致する帯は 15 本目だけ）"
        want = tuple(sorted((a, b)))
        got = {tuple(sorted((x, y))) for x, y, _ in candidate_pairs(store.con, 15)}
        assert want in got, \
            "帯 15 本目だけが一致する距離 15 の組を取りこぼした（64bit の一部しか見ていない）"
        # 距離 15 なので ≤14 では候補に入らない（境界が効いていること）
        assert want not in {tuple(sorted((x, y))) for x, y, _ in candidate_pairs(store.con, 14)}
        assert near_groups(store.con, max_distance=15)["total_groups"] == 1
        assert near_groups(store.con, max_distance=14)["total_groups"] == 0
    finally:
        store.close()




def test_the_api_group_counts_match_the_brute_force(real_client):
    """壊すと落ちる: 群の数を**固定の数字**で持つ（除外 1 組で嘘の NG になる。P8-3 の調査）・
    `near` が帯の候補でない物を数える。

    ≤0 / ≤3 / ≤6 / ≤10 は実データで観測した **5 群 12 枚 / 17 群 39 枚 / 21 群 57 枚 / 28 群 87 枚**
    （**除外なし**のとき）。API がそれを返し、**総当たりから出した数とも一致**することを見る。
    """
    phash_by_id = _rows_of(_db_path())
    pairs = _all_pairs(phash_by_id)
    for dist in (0, 3, 6, 10, 15, 16):
        got = real_client.get(f"/api/duplicates/near?max_distance={dist}", headers=HUMAN).json()
        edges = {(a, b) for a, b, d in pairs if d <= dist}
        want_g, want_i = _groups_of(edges)
        assert (got["total_groups"], got["total_images"]) == (want_g, want_i), \
            f"≤{dist}: API {got['total_groups']} 群 {got['total_images']} 枚 / 総当たり {want_g} 群 {want_i} 枚"
        # **数の辻褄**（帯の候補 + 除外 = その距離の総当たり）
        assert got["total_pairs"] + got["excluded_pairs"] == len(edges), \
            f"≤{dist}: {got['total_pairs']} + {got['excluded_pairs']} != {len(edges)}"
        assert got["excluded_pairs"] == 0, "除外は 1 つも入れていない"
    for dist, (want_g, want_i) in REAL_GROUPS.items():
        got = real_client.get(f"/api/duplicates/near?max_distance={dist}", headers=HUMAN).json()
        assert (got["total_groups"], got["total_images"]) == (want_g, want_i), \
            f"≤{dist}: 実データの {want_g} 群 {want_i} 枚 と違う"


# ---- 3. 実データで起きたこと（除外 1 組で群が 1 つ消える）----


def test_the_real_exclusion_explains_the_missing_group(real_client):
    """**実データで起きたことそのもの**（P8-3 の取り落とし調査）。

    実データの「別物として確定」1 行（距離 4 の 2 枚）を同じ形で入れると、≤6 は
    **20 群 / 55 枚**（総当たり 21 群 / 57 枚 − 除外 1 組）になる。**帯は 1 組も落としていない**
    （`total_pairs` + `excluded_pairs` = 総当たりの組数）。解除すると 21 群 / 57 枚に戻る。

    **壊すと落ちる**: `excluded_pairs` を返さない（数の辻褄が合わず「帯の取りこぼし」に見える）・
    除外を群から外さない（人の「別物」が候補に残る）。
    """
    before = real_client.get("/api/duplicates/near?max_distance=6", headers=HUMAN).json()
    assert (before["total_groups"], before["total_images"]) == (21, 57)
    assert (before["total_pairs"], before["excluded_pairs"]) == (54, 0)

    ids = [_ids_with_phash(p) for p in REAL_EXCLUDED_PHASHES]
    assert all(len(v) == 1 for v in ids), f"実データの 2 枚が合成に無い: {ids}"
    a, b = ids[0][0], ids[1][0]
    assert (int(REAL_EXCLUDED_PHASHES[0], 16) ^ int(REAL_EXCLUDED_PHASHES[1], 16)).bit_count() == 4

    posted = real_client.post("/api/duplicates/exclude", json={"a_id": a, "b_id": b},
                              headers=HUMAN)
    assert posted.status_code == 200, posted.text
    got = real_client.get("/api/duplicates/near?max_distance=6", headers=HUMAN).json()
    assert (got["total_groups"], got["total_images"]) == (20, 55), \
        "除外 1 組で 2 枚だけの群が丸ごと消える（実データと同じ）"
    assert (got["total_pairs"], got["excluded_pairs"]) == (53, 1)
    assert got["total_pairs"] + got["excluded_pairs"] == 54, "総当たりの 54 組に戻らない"
    got10 = real_client.get("/api/duplicates/near?max_distance=10", headers=HUMAN).json()
    assert (got10["total_groups"], got10["total_images"]) == (28, 86)
    assert got10["total_pairs"] + got10["excluded_pairs"] == 88

    # **解除すると戻る**
    assert real_client.post("/api/duplicates/exclude/remove", json={"a_id": a, "b_id": b},
                            headers=HUMAN).status_code == 200
    back = real_client.get("/api/duplicates/near?max_distance=6", headers=HUMAN).json()
    assert (back["total_groups"], back["total_images"]) == (21, 57)
    assert (back["total_pairs"], back["excluded_pairs"]) == (54, 0)


def test_the_excluded_count_only_counts_pairs_within_the_distance(tmp_path: Path):
    """壊すと落ちる: **距離を見ずに**除外を数える（`excluded_pairs` が常に除外の行数になる）。

    遠い組（距離 16）を除外しても、`≤6` の `excluded_pairs` は 0 のままでなければならない
    （0 にしないと `total_pairs + excluded_pairs` の辻褄が壊れる）。
    """
    store = Store(tmp_path / "two")
    try:
        a = _register(store, 0, "f0f0f0f0f0f0f0f0")
        far = int("f0f0f0f0f0f0f0f0", 16) ^ sum(1 << (63 - 4 * i) for i in range(16))
        b = _register(store, 1, f"{far:016x}")
        with store.transaction() as con:
            con.execute("INSERT INTO duplicate_exclusion(a_id, b_id, actor, at)"
                        " VALUES (?, ?, 'human', 't')", tuple(sorted((a, b))))
        near6 = near_groups(store.con, max_distance=6)
        assert (near6["total_pairs"], near6["excluded_pairs"]) == (0, 0), near6
        near16 = near_groups(store.con, max_distance=16)
        assert (near16["total_pairs"], near16["excluded_pairs"]) == (0, 1), near16
        assert near16["total_groups"] == 0
    finally:
        store.close()
