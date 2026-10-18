"""参照切れの再リンク（P8-6）のテスト。

設計: `docs/p8-design.md` §0.11（中身を確かめてから繋ぐ）・§1.2 の線 9・§3.2（口）・
      §3.4（エラーの形）・§4.1（状態）・§8.1（壊すと落ちる）

**何を壊すと落ちるか**を各テストの docstring に書いてある（家風）。
**実データは触らない**（すべて `tmp_path` の中）。**画像は動かさない**（登録を直すだけ）。
"""

from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from image_reviewer import db, relink
from image_reviewer.relink import (MAX_MISSING_LIMIT, NEARBY_CANDIDATE_LIMIT, RelinkService,
                                   sha256_of)
from image_reviewer.review import ReviewError
from image_reviewer.scan import scan
from image_reviewer.store import Store, normalize_path

HUMAN = {"X-Image-Reviewer-Actor": "human"}
AGENT = {"X-Image-Reviewer-Actor": "agent"}


# ---- 道具 ----


def make_png(path: Path, *, seed: int = 0, size: tuple[int, int] = (16, 16)) -> Path:
    """合成の PNG（`seed` で中身を変える）。`test_deletions.py` と同じ形。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    w, h = size
    im = Image.new("RGB", (w, h))
    px = im.load()
    for y in range(h):
        for x in range(w):
            px[x, y] = ((x * 7 + y * 3 + seed * 29) % 256, (x * 5 + seed * 11) % 256,
                        (y * 9 + seed * 17) % 256)
    im.save(path)
    return path


def sha_of(path: Path) -> str:
    """**本物の中身の** `sha256`（`asset.sha256` はこれと一致していなければならない）。"""
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def register(store: Store, path: Path) -> str:
    """実体のあるファイルを 1 枚登録する（`sha256` は**本物の中身**から計算する）。"""
    st = path.stat()
    asset_id, _ = store.register(
        sha256=sha_of(path), path=str(path), size=st.st_size, mtime_ns=st.st_mtime_ns,
        width=16, height=16, fmt="png", meta=None, note=None)
    return asset_id


def put_decision(store: Store, asset_id: str, *, verdict: str = "keep") -> str:
    """判断を 1 件入れる（`ReviewService` が書く形と同じ: **台帳 → 写し**）。"""
    decision_id = db.ulid()
    now = db.now()
    with store.transaction() as con:
        seq = con.execute("SELECT COALESCE(max(seq), 0) + 1 AS n FROM decision").fetchone()["n"]
        con.execute(
            "INSERT INTO decision(id, seq, subject_type, subject_id, verdict, actor, created_at)"
            " VALUES (?,?, 'asset', ?, ?, 'human', ?)", (decision_id, seq, asset_id, verdict, now))
        con.execute("UPDATE asset SET review_state = 'kept', reviewed_at = ?,"
                    " reviewed_by = 'human' WHERE id = ?", (now, asset_id))
    return decision_id


def put_tag(store: Store, asset_id: str, name: str = "1girl") -> None:
    """語を 1 つ付ける（`tag` と `asset_tag` に 1 行ずつ）。"""
    with store.transaction() as con:
        con.execute("INSERT INTO tag(name, known) VALUES (?, 1)"
                    " ON CONFLICT(name) DO UPDATE SET known = 1", (name,))
        tag_id = con.execute("SELECT id FROM tag WHERE name = ?", (name,)).fetchone()["id"]
        con.execute("INSERT INTO asset_tag(asset_id, tag_id, source, actor, tagged_at)"
                    " VALUES (?,?, 'manual', 'human', ?)", (asset_id, tag_id, db.now()))


def rows_of_table(store: Store, table: str) -> list[tuple]:
    """その表の中身（**順序込み**。P4-0 の教訓「並びそのものを期待値にする」）。"""
    with store.locked() as con:
        return [tuple(r) for r in con.execute(f"SELECT * FROM {table} ORDER BY rowid")]


def location_row(store: Store, asset_id: str) -> dict:
    with store.locked() as con:
        row = con.execute("SELECT * FROM asset_location WHERE asset_id = ?",
                          (asset_id,)).fetchone()
    return dict(row) if row is not None else {}


def missing_keys(store: Store) -> set[str]:
    """**参照切れの行の鍵**（登録したままの古いパス）。"""
    with store.locked() as con:
        return {r["path"] for r in con.execute(
            "SELECT path FROM asset_location WHERE missing_at IS NOT NULL")}


def move(src: Path, to: Path) -> Path:
    """**アプリの外で動かす**（`shutil.move` は親が無いと落ちるので作る）。"""
    to = Path(to)
    to.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(src), str(to))
    return to


class World:
    """1 枚を登録し、**アプリの外で動かして参照切れにする**（線 9 の手順そのもの）。"""

    def __init__(self, tmp_path: Path):
        self.tmp = tmp_path
        self.store = Store(tmp_path / "data")
        self.root = tmp_path / "library"
        self.root.mkdir(parents=True, exist_ok=True)
        self.src = make_png(self.root / "a.png", seed=1)
        scan(self.store, [str(self.root)])
        self.asset_id = self.store.location_of(self.src)["asset_id"]
        self.sha = sha_of(self.src)

    def close(self) -> None:
        self.store.close()

    def move_away(self, to: Path, *, new_name: str | None = None) -> Path:
        """動かして走査する（**これで `missing_at` が立つ**。設計 §1.2 の線 9 の前半）。"""
        to = Path(to)
        if new_name:
            to = to.parent / new_name
        move(self.src, to)
        stats = scan(self.store, [str(self.root)])
        assert stats["missing"] == 1, stats
        return to

    def add_root(self, folder: Path) -> Path:
        """**走査しない置き場**を登録する（その中のファイルは**まだ登録されていない**）。"""
        folder.mkdir(parents=True, exist_ok=True)
        self.store.set_roots([str(folder)])
        return folder

    def relink(self, **kwargs) -> dict:
        return RelinkService(self.store).relink(asset_id=self.asset_id, **kwargs)


@pytest.fixture
def world(tmp_path: Path):
    got = World(tmp_path)
    try:
        yield got
    finally:
        got.close()


@pytest.fixture
def app_env(tmp_path: Path, monkeypatch):
    """本物の口（`TestClient`）と、その `Store`。**データはテストの中**（家風）。"""
    monkeypatch.setenv("IMAGE_REVIEWER_DATA", str(tmp_path / "app-data"))
    from image_reviewer.app import create_app

    app = create_app()
    app.state.deletions.interval = 3600.0          # 窓のタイマーを止める（D-17 と同じ）
    with TestClient(app, base_url="http://127.0.0.1") as client:
        yield client, app, app.state.store, tmp_path


# ---- 1. 線 9（繋がる・中身が違えば断る）----


def test_exact_relink_connects_the_new_path_and_keeps_the_asset(world: World):
    """**線 9 の合格**（設計 §1.2）。移した先を指定すると、同じ `asset` のまま繋がる。

    壊すと落ちる: 行を消して入れ直す（`is_primary` と最初に見た時刻が消える）、
    `missing_at` を戻し忘れる、`location_history` を書かない、`asset` を作り直す。
    """
    put_decision(world.store, world.asset_id)
    put_tag(world.store, world.asset_id)
    before_decisions = rows_of_table(world.store, "decision")
    before_tags = rows_of_table(world.store, "asset_tag")
    moved = world.move_away(world.tmp / "elsewhere" / "renamed.png")
    old_display = str(world.src)

    got = world.relink(path=str(moved), mode="exact")

    row = location_row(world.store, world.asset_id)
    assert got["relinked"] is True and got["moved"] is True
    assert row["path"] == normalize_path(moved) and row["display_path"] == str(moved)
    assert row["missing_at"] is None and row["size"] == moved.stat().st_size
    assert got["missing_left"] == 0
    # **判断・タグ・来歴は 1 行も変わっていない**（触るのは場所と履歴だけ）
    assert rows_of_table(world.store, "decision") == before_decisions
    assert rows_of_table(world.store, "asset_tag") == before_tags
    assert got["kept"] == {"decisions": 1, "tags": 1, "locations": 1, "has_provenance": False}
    # **場所の行は増えない**（付け替え。同じ画像の場所が 2 つになったら間違い）
    with world.store.locked() as con:
        assert con.execute("SELECT count(*) AS n FROM asset_location WHERE asset_id = ?",
                           (world.asset_id,)).fetchone()["n"] == 1
    # **ファイルは動かしていない**（新しい場所に在る・古い場所には無い）
    assert moved.is_file() and not world.src.exists()
    assert sha_of(moved) == world.sha


def test_the_relink_is_recorded_in_location_history(world: World):
    """**`location_history` に 1 行**（移動元 → 移動先・理由・人。設計 §0.11）。

    壊すと落ちる: `to_path` / `reason` / `actor` を書かない（P8-6 で足した列。設計には
    「入れ替わった」「繋ぎ直した」を区別する列が無かった）、`replaced_by_asset_id` に
    自分を入れる（入れ替わりと区別できなくなる）。
    """
    moved = world.move_away(world.tmp / "elsewhere" / "renamed.png")
    old_display = str(world.src)
    world.relink(path=str(moved), mode="exact")

    history = world.store.location_history()
    assert len(history) == 1, history
    row = history[0]
    assert row["asset_id"] == world.asset_id
    assert row["path"] == old_display
    assert row["to_path"] == str(moved)
    assert row["reason"] == "relinked"
    assert row["actor"] == "human"
    assert row["replaced_by_asset_id"] is None
    assert row["replaced_at"]


def test_the_content_is_compared_by_sha256(world: World):
    """**中身が違えば繋がない**（409 `hash_mismatch`。設計 §0.11・§8.1 の 22）。

    壊すと落ちる: `sha256` の照合を外す（知覚ハッシュや `size` で代用する）と、
    **別の絵が同じ `asset` に繋がる**（判断と来歴が別の絵に付く）。
    """
    other = make_png(world.tmp / "other" / "renamed.png", seed=99)   # 名前だけ同じ別の絵
    moved = world.move_away(world.tmp / "elsewhere" / "renamed.png")
    with pytest.raises(ReviewError) as got:
        world.relink(path=str(other), mode="exact")
    assert got.value.status == 409 and got.value.code == "hash_mismatch"
    assert got.value.details["actual"] == sha_of(other)
    # **1 バイトも変わっていない**（missing_at も履歴もそのまま）
    assert missing_keys(world.store) == {normalize_path(world.src)}
    assert world.store.location_history() == []


def test_the_same_name_with_another_content_is_refused_in_nearby(world: World):
    """`nearby` も**中身で断る**（同じ名前の別の絵しか無いときは 409）。

    壊すと落ちる: 名前が一致しただけで繋ぐ（**別の絵が繋がる**）。
    """
    found = world.add_root(world.tmp / "elsewhere")
    make_png(found / "a.png", seed=42)                               # 同じ名前の別の絵
    moved = world.move_away(world.tmp / "lost" / "a.png")            # 元の名前を残して退避
    with pytest.raises(ReviewError) as got:
        world.relink(mode="nearby", path=str(found))
    assert got.value.status == 409 and got.value.code == "hash_mismatch"
    assert got.value.details["candidates"] == [str(found / "a.png")]
    assert missing_keys(world.store) == {normalize_path(world.src)}


# ---- 2. 二重登録しない ----


def test_a_path_registered_to_another_asset_is_refused(world: World):
    """**既に別の `asset` に登録されているパスは 409 `path_taken`**（二重登録しない）。

    壊すと落ちる: 主キーに当てて 500（`IntegrityError`）にする、または入れ替えて
    **別の画像の登録を奪う**（`asset_location.path` は主キー）。
    """
    other = make_png(world.root / "b.png", seed=7)
    other_id = register(world.store, other)
    world.move_away(world.tmp / "elsewhere" / "a.png")
    with pytest.raises(ReviewError) as got:
        world.relink(path=str(other), mode="exact")
    assert got.value.status == 409 and got.value.code == "path_taken"
    assert got.value.details["asset_id"] == other_id
    # **両方とも元のまま**（b の登録も、a の参照切れも）
    assert world.store.location_of(other)["asset_id"] == other_id
    assert missing_keys(world.store) == {normalize_path(world.src)}


def test_a_path_already_registered_to_the_same_asset_is_refused(world: World):
    """**同じ `asset` の別の生きた場所**は 409 `already_registered`（する事が無い）。

    壊すと落ちる: 同じ画像の場所を 2 つにする（主キーに当たって 500 になるか、
    場所の数が増える）。
    """
    copy = move(world.src, world.tmp / "elsewhere" / "a.png")
    register(world.store, copy)                       # 同じ内容 → 同じ asset に 2 つ目の場所
    shutil.copy2(copy, world.src)                     # 元の場所にも同じ物を戻して走査する
    scan(world.store, [str(world.root)])
    move(world.src, world.tmp / "lost" / "a.png")
    scan(world.store, [str(world.root)])              # 元の場所だけが参照切れになる
    assert missing_keys(world.store) == {normalize_path(world.src)}
    with pytest.raises(ReviewError) as got:
        world.relink(path=str(copy), mode="exact")
    assert got.value.status == 409 and got.value.code == "already_registered"
    assert len(world.store.asset(world.asset_id)["locations"]) == 2


# ---- 3. 近くを探す（nearby）----


def test_nearby_finds_the_file_with_the_same_name_in_a_registered_root(world: World):
    """**登録した置き場を同じファイル名で探し、ハッシュが一致すれば繋ぐ**（設計 §0.11）。

    ここは「**まだ走査していない置き場**へ動いた」場合（走査は知らないパスの画像を
    その場で登録するので、走査済みの置き場の中で動いた物は既に繋がっている）。

    壊すと落ちる: 名前で絞らずに**置き場の画像を全部ハッシュする**（遅い）、
    置き場の外まで歩く、探したフォルダを返さない。
    """
    other = world.add_root(world.tmp / "elsewhere")     # 走査していない置き場
    moved = world.move_away(other / "sub" / "a.png")
    got = world.relink(mode="nearby")
    assert got["relinked"] is True and got["mode"] == "nearby"
    assert got["to_path"] == str(moved)
    assert got["searched"] >= 1 and got["candidates"] == [str(moved)]
    assert sorted(got["folders"]) == sorted([str(world.root), str(other)])
    assert got["unreadable"] == [] and got["candidates_truncated"] is False
    assert location_row(world.store, world.asset_id)["path"] == normalize_path(moved)


def test_nearby_can_be_pointed_at_a_folder(world: World):
    """**人が探すフォルダを指定できる**（置き場の外でも、読むだけなら歩いてよい）。

    壊すと落ちる: 置き場の下しか許さない（外へ動いたファイルを繋げない）。
    """
    outside = world.tmp / "moved-here"
    moved = world.move_away(outside / "a.png")
    got = world.relink(mode="nearby", path=str(outside))
    assert got["to_path"] == str(moved)
    assert got["folders"] == [str(outside)]


def test_nearby_accepts_a_file_and_uses_its_folder(world: World):
    """**ファイルを渡されたらその親を探す**（画面がファイル選択の値をそのまま渡せる）。

    壊すと落ちる: ファイルを渡すと 404 にする（画面が 2 通りの値を組み分ける必要が出る）。
    """
    outside = world.tmp / "moved-here"
    moved = world.move_away(outside / "a.png")
    got = world.relink(mode="nearby", path=str(moved))
    assert got["to_path"] == str(moved)
    assert got["folders"] == [str(outside)]


def test_nearby_is_deterministic_and_reports_the_others(world: World):
    """同じ中身が 2 つ見つかったら**決定的に 1 つ**を選び、**選ばなかった物も返す**。

    壊すと落ちる: 並べずに選ぶ（同じ入力で答えが変わる）、`also_found` を出さない
    （**黙って捨てない**の家風）。
    """
    other = world.add_root(world.tmp / "elsewhere")
    moved = move(world.src, other / "b" / "a.png")
    scan(world.store, [str(world.root)])                 # 元の置き場を走査 → 参照切れ
    second_copy = other / "a" / "a.png"
    second_copy.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(moved, second_copy)
    got = world.relink(mode="nearby")
    first = str(other / "a" / "a.png")
    second = str(other / "b" / "a.png")
    assert got["to_path"] == first, "大小文字を畳んだ順で先の物を選ぶ"
    assert got["also_found"] == [second]
    assert got["candidates"] == [first, second]


def test_nearby_refuses_when_there_is_no_root_to_search(tmp_path: Path):
    """置き場が 1 つも無ければ、**探すフォルダを要求する**（422 `bad_scope`）。

    壊すと落ちる: 置き場が無いのに**ディスク全体を歩く**（勝手に外まで探しに行く）。
    ここは `World` を使わない（`World` は走査で置き場を 1 つ登録するため）。
    """
    store = Store(tmp_path / "data")
    try:
        outside = tmp_path / "outside"
        outside.mkdir(parents=True, exist_ok=True)
        lone = make_png(outside / "lonely.png", seed=3)
        lone_id = register(store, lone)               # 走査していない＝置き場も無い
        assert store.roots() == []
        move(lone, outside / "lonely.png.bak")
        store.mark_missing(set(), [str(outside)])     # 走査の代わりに印だけ立てる
        assert missing_keys(store) == {normalize_path(lone)}
        with pytest.raises(ReviewError) as got:
            RelinkService(store).relink(asset_id=lone_id, mode="nearby")
        assert got.value.status == 422 and got.value.code == "bad_scope"
        # **フォルダを渡せば探す**（人が指定する形）
        shutil.move(str(outside / "lonely.png.bak"), str(outside / "lonely.png"))
        found = RelinkService(store).relink(asset_id=lone_id, mode="nearby", path=str(outside))
        assert found["to_path"] == str(outside / "lonely.png")
    finally:
        store.close()


def test_nearby_says_not_found_when_the_name_is_absent(world: World):
    """同じ名前が 1 つも無ければ **404 `not_found`**（中身違いの 409 と分ける）。

    壊すと落ちる: 「見つからない」と「中身が違う」を同じ番号にする（人は次に何をすべきか
    分からなくなる）。
    """
    world.move_away(world.tmp / "elsewhere" / "renamed.png")
    with pytest.raises(ReviewError) as got:
        world.relink(mode="nearby")
    assert got.value.status == 404 and got.value.code == "not_found"
    assert got.value.details["searched"] == 0


def test_a_file_moved_inside_a_scanned_root_is_already_linked_by_the_scan(world: World):
    """**走査済みの置き場の中で動いた物は、走査が既に繋いでいる**（専門 §4 の表）。

    同じ `asset` に場所が 2 つ（生きている新しい場所＋参照切れの古い場所）になり、
    `nearby` は **409 `already_registered`** で断る（**3 つ目の場所を作らない**）。

    壊すと落ちる: 二重登録の検査を外す（場所が 3 つになる）、走査の `register` を
    変える（別の `asset` が 2 つできる）。
    """
    moved = world.move_away(world.root / "sub" / "a.png")   # 同じ置き場の中
    live = [l for l in world.store.asset(world.asset_id)["locations"] if not l["missing_at"]]
    assert [l["path"] for l in live] == [str(moved)], "走査が新しい場所を登録していない"
    with pytest.raises(ReviewError) as got:
        world.relink(mode="nearby")
    assert got.value.status == 409 and got.value.code == "already_registered"
    assert len(world.store.asset(world.asset_id)["locations"]) == 2


# ---- 4. 元の場所に戻ってきた（履歴を増やさない）----


def test_a_file_that_came_back_just_clears_missing_at(world: World):
    """**元のパスに戻ってきた**ときは履歴を増やさず `missing_at` を戻すだけ。

    壊すと落ちる: `path` が同じでも「別の画像に登録済み」として 409 にする（戻せない）、
    移動していないのに履歴を 1 行足す（履歴が嘘になる）。
    """
    moved = world.move_away(world.tmp / "elsewhere" / "a.png")
    shutil.move(str(moved), str(world.src))            # アプリの外で元に戻した
    got = world.relink(path=str(world.src), mode="exact")
    assert got["relinked"] is True and got["moved"] is False
    assert got["history_id"] is None
    assert location_row(world.store, world.asset_id)["missing_at"] is None
    assert world.store.location_history() == []


# ---- 5. 人だけ・守り ----


def test_the_endpoint_is_human_only(app_env):
    """**人だけ**（設計 §3.2）。エージェントは **403 `human_only`**（1 バイトも書かない）。

    壊すと落ちる: `require_human` を外す（エージェントが登録を書き換えられる）。
    """
    client, app, store, tmp = app_env
    root = tmp / "library"
    src = make_png(root / "a.png", seed=1)
    scan(store, [str(root)])
    asset_id = store.location_of(src)["asset_id"]
    moved = move(src, tmp / "elsewhere" / "a.png")
    scan(store, [str(root)])
    body = {"asset_id": asset_id, "path": str(moved), "mode": "exact"}
    got = client.post("/api/locations/relink", headers=AGENT, json=body)
    assert got.status_code == 403 and got.json()["code"] == "human_only"
    assert missing_keys(store) == {normalize_path(src)}
    # **読むのは人もエージェントも可**
    assert client.get("/api/locations/missing", headers=AGENT).status_code == 200
    # 人が押せば通る
    ok = client.post("/api/locations/relink", headers=HUMAN, json=body)
    assert ok.status_code == 200 and ok.json()["actor"] == "human"


def test_the_endpoints_are_guarded(app_env):
    """**`Host: evil` と `Content-Type: text/plain` は 403**（P6 の監査 C8 の流儀）。

    壊すと落ちる: `app.include_router` を外すと、守り（middleware）が掛からない。
    """
    client, _app, _store, _tmp = app_env
    body = {"asset_id": "x", "path": "y", "mode": "exact"}
    assert client.post("/api/locations/relink", headers={**HUMAN, "Host": "evil"},
                       json=body).status_code == 403
    assert client.post("/api/locations/relink",
                       headers={**HUMAN, "Content-Type": "text/plain"},
                       content=json.dumps(body)).status_code == 403
    # 語彙の外の actor は 422（他の口と同じ検査を 1 か所で通す）
    robot = {"X-Image-Reviewer-Actor": "robot"}
    assert client.post("/api/locations/relink", headers=robot, json=body).status_code == 422
    assert client.get("/api/locations/missing", headers=robot).status_code == 422
    assert client.get("/api/locations/missing?include_deleted=2", headers=HUMAN).status_code == 422
    assert client.get(f"/api/locations/missing?limit={MAX_MISSING_LIMIT + 1}",
                      headers=HUMAN).status_code == 422


def test_the_body_vocabulary_is_checked(app_env):
    """**入力の誤りは 422**（設計 §3.4: `bad_path` / `bad_stage` と同じ流儀）。

    壊すと落ちる: `mode` の語彙を見ない（`mode='nearby'` のつもりが `exact` として走る）、
    空の `path` を 409 にする（「登録が無い」と区別できない）。
    """
    client, _app, _store, _tmp = app_env
    assert client.post("/api/locations/relink", headers=HUMAN, json={}).status_code == 422
    got = client.post("/api/locations/relink", headers=HUMAN,
                      json={"asset_id": "x", "path": "", "mode": "exact"})
    assert got.status_code == 422 and got.json()["code"] == "bad_path"
    got = client.post("/api/locations/relink", headers=HUMAN,
                      json={"asset_id": "x", "path": "p", "mode": "auto"})
    assert got.status_code == 422 and got.json()["code"] == "bad_mode"
    # 存在しない asset は 404、生きている場所は 409 `not_missing`
    assert client.post("/api/locations/relink", headers=HUMAN,
                       json={"asset_id": "none", "path": "p"}).status_code == 404


def test_a_live_location_cannot_be_relinked(world: World):
    """**生きている場所は繋ぎ直せない**（409 `not_missing`。設計 §4.1 の状態）。

    壊すと落ちる: 存在するだけで通す（参照切れでない物の場所を書き換える）。
    """
    with pytest.raises(ReviewError) as got:
        world.relink(path=str(world.src), mode="exact")
    assert got.value.status == 409 and got.value.code == "not_missing"


def test_a_deleting_location_cannot_be_relinked(app_env):
    """**削除の途中（段 3）の場所は繋がない**（409 `deleted`。設計 §4.1）。

    壊すと落ちる: 段 3 も `missing_at` を立てるので、そのまま通すと**保留領域のファイルを
    見失ったまま登録だけ戻る**（「最近の削除」から戻せなくなる）。
    """
    client, app, store, tmp = app_env
    root = tmp / "library"
    src = make_png(root / "a.png", seed=1)
    scan(store, [str(root)])
    asset_id = store.location_of(src)["asset_id"]
    with store.transaction() as con:                 # 段 3 の印（既定は印なし）
        con.execute("UPDATE root SET allow_stage3 = 1 WHERE path = ?", (normalize_path(root),))
    got = client.post("/api/locations/delete", headers=HUMAN,
                      json={"asset_id": asset_id, "path": str(src), "stage": 3,
                            "confirm_last_copy": True})
    assert got.status_code == 200, got.text
    refused = client.post("/api/locations/relink", headers=HUMAN,
                          json={"asset_id": asset_id, "path": str(src), "mode": "exact"})
    assert refused.status_code == 409 and refused.json()["code"] == "deleted"
    assert refused.json()["details"]["deletion_id"] == got.json()["deletion_id"]


def test_two_missing_locations_need_from_path(app_env):
    """**1 枚が 2 か所で切れている**ときは `from_path` で指定する（409 `ambiguous`）。

    壊すと落ちる: 並びの先頭を勝手に選ぶ（**人が選んでいない場所を繋ぐ**）。
    """
    client, app, store, tmp = app_env
    root = tmp / "library"
    first = make_png(root / "a.png", seed=1)
    scan(store, [str(root)])
    asset_id = store.location_of(first)["asset_id"]
    second = tmp / "other" / "a.png"
    second.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(first, second)
    register(store, second)
    scan(store, [str(tmp / "other")])
    move(first, tmp / "lost1" / "a.png")
    move(second, tmp / "lost2" / "a.png")
    scan(store, [str(root), str(tmp / "other")])
    assert len(missing_keys(store)) == 2

    no_hint = client.post("/api/locations/relink", headers=HUMAN,
                          json={"asset_id": asset_id, "path": str(tmp / "lost1" / "a.png")})
    assert no_hint.status_code == 409 and no_hint.json()["code"] == "ambiguous"
    ok = client.post("/api/locations/relink", headers=HUMAN,
                     json={"asset_id": asset_id, "path": str(tmp / "lost1" / "a.png"),
                           "from_path": str(first)})
    assert ok.status_code == 200, ok.text
    assert len(missing_keys(store)) == 1


# ---- 6. 参照切れの一覧（GET は書かない）----


def test_the_missing_list_shows_where_and_why(app_env):
    """**参照切れの一覧**（`GET /api/locations/missing`）。置き場と、消した物の数を返す。

    壊すと落ちる: 段 2・3 で消した物を「参照切れ」と一緒に出す（利用者が消した物を
    探し始める）、外した数を出さない（黙って捨てる）。
    """
    client, app, store, tmp = app_env
    root = tmp / "library"
    src = make_png(root / "a.png", seed=1)
    other = make_png(root / "b.png", seed=2)
    scan(store, [str(root)])
    asset_id = store.location_of(src)["asset_id"]
    other_id = store.location_of(other)["asset_id"]
    moved = move(src, tmp / "elsewhere" / "a.png")
    scan(store, [str(root)])

    body = client.get("/api/locations/missing", headers=HUMAN).json()
    assert body["total"] == 1 and body["count"] == 1 and body["unlisted"] == 0
    item = body["items"][0]
    # **鍵は登録したままの古いパス**（動いた先はまだ知らない。そこを `to_path` で繋ぐ）
    assert item["asset_id"] == asset_id and item["key"] == normalize_path(src)
    assert item["path"] == str(src)                   # 登録した表記（display_path）
    assert item["sha256"] == sha_of(moved)
    assert item["missing_at"] and item["deleted"] is False
    assert item["other_live_locations"] == 0
    assert item["roots"] == [str(root)] and item["active_deletion_id"] is None
    assert "relink" in body["hint"]

    # **段 3 で消した物は既定で出さない**（削除も `missing_at` を立てるので区別が要る）
    with store.transaction() as con:
        con.execute("UPDATE root SET allow_stage3 = 1 WHERE path = ?", (normalize_path(root),))
    deleted = client.post("/api/locations/delete", headers=HUMAN,
                          json={"asset_id": other_id, "path": str(other), "stage": 3,
                                "confirm_last_copy": True})
    assert deleted.status_code == 200, deleted.text
    after = client.get("/api/locations/missing", headers=HUMAN).json()
    assert after["total"] == 1 and after["excluded_deleted"] == 1
    with_deleted = client.get("/api/locations/missing?include_deleted=1", headers=HUMAN).json()
    assert with_deleted["total"] == 2
    gone = [i for i in with_deleted["items"] if i["asset_id"] == other_id][0]
    assert gone["deleted"] is True and gone["active_deletion_id"] == deleted.json()["deletion_id"]
    # `limit` は数を切っても**数は切らない**（`unlisted` に出す）
    limited = client.get("/api/locations/missing?include_deleted=1&limit=0", headers=HUMAN).json()
    assert limited["count"] == 0 and limited["total"] == 2 and limited["unlisted"] == 2


def test_the_missing_list_writes_nothing(app_env):
    """**`GET` は 1 バイトも書かない**（家風。設計 §0.13）。

    壊すと落ちる: 一覧を見るたびに「見た時刻」を書く・`missing_at` を触る・
    ハッシュを計算して `asset` に残す（`GET` が書くと WAL が膨らみ、監査で必ず見つかる）。
    """
    client, app, store, tmp = app_env
    root = tmp / "library"
    src = make_png(root / "a.png", seed=1)
    scan(store, [str(root)])
    move(src, tmp / "elsewhere" / "a.png")
    scan(store, [str(root)])

    def snapshot() -> tuple:
        with store.locked() as con:
            tables = [r["name"] for r in con.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY name")]
            rows = tuple((t, tuple(tuple(r) for r in con.execute(f"SELECT * FROM {t}")))
                         for t in tables)
        files = tuple(sorted((str(p.relative_to(store.data_dir)), p.stat().st_size,
                              p.stat().st_mtime_ns) for p in store.data_dir.rglob("*")
                             if p.is_file()))
        return rows, files

    before = snapshot()
    assert client.get("/api/locations/missing", headers=HUMAN).status_code == 200
    assert client.get("/api/locations/missing?include_deleted=1", headers=HUMAN).status_code == 200
    assert snapshot() == before, "GET /api/locations/missing が書いている"


# ---- 7. 移行（古い v6 に列を足す）----


def test_an_old_database_gets_the_history_columns(tmp_path: Path):
    """**版を上げずに足した 3 列を、古い v6 の DB にも当てる**（家風「列を見てから `ALTER`」）。

    壊すと落ちる: `TOP_UP_COLUMNS` に足さない（実データで
    **`no such column: to_path` ＝ 再リンクが 500 になる**）。控え（`pre-topup-*`）は
    `Store` が開く前に `missing_top_ups()` を見て取る（別のテストが見ている）。
    """
    data = tmp_path / "old"
    data.mkdir(parents=True, exist_ok=True)
    con = db.open_db(data)
    try:
        # 「3 列が無い v6」を合成する（`CHECK` 付きの列は `DROP COLUMN` できないので作り直す）
        con.execute("DROP TABLE location_history")
        con.execute("CREATE TABLE location_history ("
                    " id INTEGER PRIMARY KEY AUTOINCREMENT, asset_id TEXT NOT NULL,"
                    " path TEXT NOT NULL, size INTEGER, mtime_ns INTEGER,"
                    " replaced_by_asset_id TEXT, replaced_at TEXT NOT NULL)")
        con.execute("PRAGMA user_version = 6")
        assert "location_history.to_path" in db.missing_top_ups(con)
        assert "location_history.reason" in db.missing_top_ups(con)
        assert "location_history.actor" in db.missing_top_ups(con)
        assert db.migrate(con) == db.SCHEMA_VERSION
        cols = {r["name"] for r in con.execute("PRAGMA table_info(location_history)")}
        assert {"to_path", "reason", "actor"} <= cols
        # **語彙は表でも守る**（`CHECK`。新しい列には付けられる。P7 の `fetched` と同じ）
        con.execute("INSERT INTO asset(id, sha256, kind, first_seen_at, last_seen_at)"
                    " VALUES ('a1', ?, 'generated', 't', 't')", ("a" * 64,))
        with pytest.raises(sqlite3.IntegrityError):
            con.execute("INSERT INTO location_history(asset_id, path, replaced_at, reason)"
                        " VALUES ('a1', 'p', 't', 'moved')")
        con.execute("INSERT INTO location_history(asset_id, path, replaced_at, reason, actor)"
                    " VALUES ('a1', 'p', 't', 'relinked', 'human')")
        assert db.migrate(con) == db.SCHEMA_VERSION      # 何度呼んでも同じ
    finally:
        con.close()


# ---- 8. 道具 ----


def test_sha256_of_reads_the_whole_file(tmp_path: Path):
    """`sha256_of` は**全体**を読む（1 MiB の塊を跨いでも正しい）。

    壊すと落ちる: 先頭の塊だけで計算する（**大きい画像で中身の照合が嘘になる**）。
    """
    big = tmp_path / "big.png"
    body = bytes(range(256)) * (5000 + 7)             # 1 MiB を跨ぐ
    big.write_bytes(body)
    assert sha256_of(big) == hashlib.sha256(body).hexdigest()


def test_the_limit_vocabulary_is_checked():
    """`limit` は 0〜上限の整数だけ（**真偽値と小数は通さない**。D-6 と同じ流儀）。"""
    assert relink._limit_of(0) == 0 and relink._limit_of(MAX_MISSING_LIMIT) == MAX_MISSING_LIMIT
    for bad in (-1, MAX_MISSING_LIMIT + 1, True, 2.5, "x", None):
        with pytest.raises(ReviewError):
            relink._limit_of(bad)


def test_nearby_candidates_are_capped(tmp_path: Path, monkeypatch):
    """同じ名前が大量にあるときは**上限で打ち切って、打ち切ったことを返す**。

    壊すと落ちる: 上限を外す（1 万枚の置き場で `nearby` が固まる）。
    """
    world = World(tmp_path)
    try:
        monkeypatch.setattr(relink, "NEARBY_CANDIDATE_LIMIT", 2)
        other = world.add_root(world.tmp / "elsewhere")
        for i in range(4):
            copy = other / f"sub{i}" / "a.png"
            copy.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(world.src, copy)
        moved = world.move_away(world.tmp / "lost" / "a.png")   # 元の名前は残さない
        got = world.relink(mode="nearby")
        assert got["candidates_truncated"] is True
        assert got["searched"] == 2 and len(got["candidates"]) == 2
        assert got["to_path"] == str(other / "sub0" / "a.png")
        assert moved.is_file()                        # 元のファイルもそのまま
    finally:
        world.close()
