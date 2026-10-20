"""P2-1（仮想フォルダ＝カタログ）の試験。

設計: `docs/design.md` **§5.3**（表）・**§6.1**（口 8 本）・**§10.1**（多対多。**実ファイルは
動かさない**）・**§10.2**（スマートフォルダ）・**§14**（P2 の行）・**§16.9**（P2-0 の決定。
**G-2 (b)** 同じ親の中で名前は一意＝部分一意索引／**C-2** 名前の取り合いを書く前に見る）。

**合格の線（R2）を、壊すと落ちる形で固定する**:

- 1 枚を 2 つのフォルダに入れられる（多対多）
- 外しても画像は消えない（`folder_member` の 1 行だけ）
- フォルダを消しても画像は消えない（`asset` / `asset_location` は 1 行も変えない）
- **実ファイルは 1 バイトも動かない**（前後で署名：大きさ・mtime・sha256）
- 同じ親の同名は 422・別の親なら同名可・循環する親は 422
- `GET` は 1 バイトも書かない（ファイルと全表の中身を前後で比べる）
- 403（エージェント）・422（語彙外・存在しない親・同じ親の同名・循環）

**期待値はこの試験にリテラルで書く**（`db.V7_*` / `folders.*` から作らない。P2-0 の監査 B-2）。
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import unicodedata
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from image_reviewer import backup, db
from image_reviewer.store import Store

HUMAN = {"X-Image-Reviewer-Actor": "human"}

#: v7 の**式索引**の期待値（リテラル。空白を詰めて小文字にした `sqlite_master.sql`）
WANT_INDEX_SQL = (
    "createuniqueindexux_folder_nameonfolder(coalesce(parent_id,''),name)"
    "wheredeleted_atisnull")


# ---- 下ごしらえ ----


def _make_png(path: Path, color=(11, 22, 33)) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (16, 16), color).save(path)
    return path


def _register(store: Store, path: Path, *, source: str = "scan") -> str:
    blob = path.read_bytes()
    asset_id, _ = store.register(
        sha256=hashlib.sha256(blob).hexdigest(), path=str(path), size=len(blob),
        mtime_ns=path.stat().st_mtime_ns, width=16, height=16, fmt="png",
        meta=None, note=None, source=source)
    return asset_id


def _files(root: Path) -> dict:
    """ファイルの**中身まで**（`GET` が 1 バイトも書かないこと／実ファイルが動かないこと）。

    **`db.sqlite3-shm` は数えない**（P2-0 の監査 C-1。WAL の索引で、読み手が読み手の印を
    書き換える）。`-wal` は残す（中身が変われば書いた証拠）。
    """
    out = {}
    for path in sorted(Path(root).rglob("*")):
        if path.is_file() and path.name != "db.sqlite3-shm":
            got = path.stat()
            out[str(path.relative_to(root))] = (
                got.st_size, got.st_mtime_ns, hashlib.sha256(path.read_bytes()).hexdigest())
    return out


def _image_signature(paths) -> dict:
    """**実ファイルの署名**（大きさ・mtime・sha256）。1 バイトも動いていないことの物差し。"""
    out = {}
    for path in sorted(Path(p) for p in paths):
        got = path.stat()
        out[str(path)] = (got.st_size, got.st_mtime_ns,
                          hashlib.sha256(path.read_bytes()).hexdigest())
    return out


def _tables(con: sqlite3.Connection) -> list[str]:
    return [row[0] for row in con.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY name")]


def _rows_digest(con: sqlite3.Connection) -> dict:
    return {table: [tuple(row) for row in con.execute(f"SELECT * FROM {table}")]
            for table in _tables(con)}


@pytest.fixture
def env(tmp_path, monkeypatch):
    """3 枚の実ファイル＋複製の DB＋本物のアプリ（`create_app` の道）。"""
    from image_reviewer.app import create_app

    data = tmp_path / "data"
    images = tmp_path / "images"
    images.mkdir(parents=True, exist_ok=True)
    store = Store(data)
    ids = {}
    try:
        for at, name in enumerate(("a", "b", "c")):
            path = _make_png(images / f"{name}.png", (10 + at * 30, 20, 30))
            ids[name] = _register(store, path, source="drop" if name == "c" else "scan")
    finally:
        store.close()
    monkeypatch.setenv("IMAGE_REVIEWER_DATA", str(data))
    monkeypatch.setenv("IMAGE_REVIEWER_BACKUP_DIR", str(tmp_path / "backups"))
    app = create_app()
    app.state.backup.interval = 3600.0           # 周期が来ないようにする（テストを速く保つ）
    with TestClient(app, base_url="http://127.0.0.1") as client:
        # 起動の直後に日次バックアップが 1 回走る（`settings` に時刻を書く）。**先に書かせてから**測る
        assert client.post("/api/backup", headers=HUMAN, json={}).status_code < 500
        yield SimpleNamespace(client=client, app=app, data=data, images=images,
                              ids=ids, tmp_path=tmp_path)


def _new(client, name: str, *, parent_id=None, kind: str = "manual", headers=HUMAN):
    body = {"name": name, "kind": kind}
    if parent_id is not None:
        body["parent_id"] = parent_id
    return client.post("/api/folders", json=body, headers=headers)


# ---- 1. R2 の線: 多対多・画像が消えない・実ファイルが動かない ----


def test_the_same_image_can_be_in_two_folders(env):
    """**R2 の線 1**（設計 §10.1）: 1 枚を 2 つのフォルダに入れられる。

    壊すと落ちる: `folder_member` を 1 枚 1 行に制限する／2 つ目の追加を「既にある」と断る／
    `GET /api/folders/{id}/assets` が片方しか見ない。
    """
    client = env.client
    first = _new(client, "2026-10 生成").json()["id"]
    second = _new(client, "気に入った構図").json()["id"]
    asset = env.ids["a"]

    got = client.post(f"/api/folders/{first}/members", json={"asset_ids": [asset]}, headers=HUMAN)
    assert got.status_code == 200, got.text
    assert got.json()["added"] == [asset]
    again = client.post(f"/api/folders/{second}/members", json={"asset_ids": [asset]},
                        headers=HUMAN)
    assert again.status_code == 200, again.text
    assert again.json()["added"] == [asset], "2 つ目のフォルダにも入れられる"

    for folder in (first, second):
        body = client.get(f"/api/folders/{folder}/assets").json()
        assert body["total"] == 1, body
        assert [item["id"] for item in body["items"]] == [asset]
        assert body["items"][0]["review_state"] == "unreviewed"
        assert body["items"][0]["path"].endswith("a.png")

    # 木の件数（生きた画像の枚数。§6.1）
    tree = client.get("/api/folders").json()
    assert tree["total"] == 2
    assert sorted(item["count"] for item in tree["items"]) == [1, 1]
    # `folder_member` は 2 行（同じ画像が 2 つのフォルダに所属）
    with env.app.state.store.locked() as con:
        assert con.execute("SELECT count(*) FROM folder_member").fetchone()[0] == 2


def test_removing_from_a_folder_keeps_the_image_and_the_other_folder(env):
    """**R2 の線 2**: 外しても画像は消えない（`folder_member` の 1 行だけ）。

    壊すと落ちる: 外す口が `asset` を消す／`asset_location` を消す／他のフォルダの所属まで消す。
    """
    client = env.client
    first = _new(client, "A").json()["id"]
    second = _new(client, "B").json()["id"]
    asset = env.ids["b"]
    for folder in (first, second):
        assert client.post(f"/api/folders/{folder}/members", json={"asset_ids": [asset]},
                           headers=HUMAN).status_code == 200
    before = _image_signature(env.images.glob("*.png"))
    with env.app.state.store.locked() as con:
        assets_before = con.execute("SELECT count(*) FROM asset").fetchone()[0]
        locations_before = con.execute("SELECT count(*) FROM asset_location").fetchone()[0]

    got = client.request("DELETE", f"/api/folders/{first}/members",
                         json={"asset_ids": [asset]}, headers=HUMAN)
    assert got.status_code == 200, got.text
    assert got.json()["removed"] == [asset]
    assert got.json()["not_member"] == []
    assert got.json()["count"] == 0

    assert client.get(f"/api/folders/{first}/assets").json()["total"] == 0
    assert client.get(f"/api/folders/{second}/assets").json()["total"] == 1, "他のフォルダからは消さない"
    with env.app.state.store.locked() as con:
        assert con.execute("SELECT count(*) FROM asset").fetchone()[0] == assets_before
        assert con.execute("SELECT count(*) FROM asset_location").fetchone()[0] == locations_before
    # 一覧にも出たまま
    listed = [item["id"] for item in client.get("/api/assets?limit=100").json()["items"]]
    assert asset in listed
    assert _image_signature(env.images.glob("*.png")) == before, "実ファイルが動いた"


def test_deleting_a_folder_keeps_its_images(env):
    """**R2 の線 3**: フォルダを消しても画像は消えない（既定は論理削除。§6.1）。

    **論理削除は `folder_member` の行も消さない**（消えるのは `purge` のときだけ。監査 B-1。
    行が残るので、戻せば中身が見える）。

    壊すと落ちる: 削除が `asset` を消す（外部キーの CASCADE を `asset` 側から発火させる）／
    中身を消すときに `asset_location` を消す／`purge` でも画像を消す／
    **論理削除で `folder_member` を `DELETE` する**（B-1。戻しても中身が空になる）。
    """
    client = env.client
    folder = _new(client, "消すフォルダ").json()["id"]
    child = _new(client, "子", parent_id=folder).json()["id"]
    for target in (folder, child):
        for name in ("a", "b"):
            assert client.post(f"/api/folders/{target}/members",
                               json={"asset_ids": [env.ids[name]]},
                               headers=HUMAN).status_code == 200
    before = _image_signature(env.images.glob("*.png"))
    with env.app.state.store.locked() as con:
        asset_ids_before = [row[0] for row in con.execute("SELECT id FROM asset ORDER BY id")]
        location_rows_before = [tuple(row) for row in con.execute(
            "SELECT * FROM asset_location ORDER BY path")]

    got = client.request("DELETE", f"/api/folders/{folder}",
                         json={"confirm": "消すフォルダ"}, headers=HUMAN)
    assert got.status_code == 200, got.text
    body = got.json()
    assert (body["deleted"], body["purged"], body["folders"]) == (True, False, 2)
    assert body["assets_deleted"] == 0

    # 木からは消える（子も一緒に隠れる）
    assert client.get("/api/folders").json()["items"] == []
    # 画像は 1 枚も消えない・場所も 1 行も変わらない
    with env.app.state.store.locked() as con:
        assert [row[0] for row in con.execute("SELECT id FROM asset ORDER BY id")] \
            == asset_ids_before
        assert [tuple(row) for row in con.execute(
            "SELECT * FROM asset_location ORDER BY path")] == location_rows_before
        # **`folder_member` の行は残る**（2 フォルダ × 2 枚 = 4 行。監査 B-1）
        assert con.execute("SELECT count(*) FROM folder_member").fetchone()[0] == 4
        # 隠れたフォルダの行は `deleted_at` が付いている（物理で消していない）
        assert con.execute("SELECT count(*) FROM folder WHERE deleted_at IS NOT NULL"
                           ).fetchone()[0] == 2
    listed = [item["id"] for item in client.get("/api/assets?limit=100").json()["items"]]
    for name in ("a", "b"):
        assert env.ids[name] in listed
    assert _image_signature(env.images.glob("*.png")) == before, "実ファイルが動いた"


def test_a_soft_deleted_folder_comes_back_with_its_members(env):
    """**B-1**: 論理削除で隠した中身は**行として残り**、戻すと見える（仮想フォルダは再生成できない分類）。

    隠している間は、木・件数・`GET /api/folders/{id}/assets` の**どこにも出ない**こと。
    戻す口はまだ無い（設計の穴 3）ので、ここでは DB を直接戻して「データが残っている」ことを見る。
    同じ 1 枚を共有する別のフォルダの件数が、隠したフォルダの行で**水増しされない**ことも見る。

    壊すと落ちる: 論理削除で `folder_member` を消す（戻しても空）／
    隠したフォルダの所属を他のフォルダの件数に数える（読む側の `folder.deleted_at` の検査を外す）／
    隠したフォルダの中身を `GET .../assets` が返す。
    """
    client = env.client
    parent = _new(client, "隠す親").json()["id"]
    child = _new(client, "隠す子", parent_id=parent).json()["id"]
    other = _new(client, "残すフォルダ").json()["id"]
    assert client.post(f"/api/folders/{parent}/members",
                       json={"asset_ids": [env.ids["a"], env.ids["b"]]},
                       headers=HUMAN).status_code == 200
    assert client.post(f"/api/folders/{child}/members",
                       json={"asset_ids": [env.ids["c"]]}, headers=HUMAN).status_code == 200
    assert client.post(f"/api/folders/{other}/members",
                       json={"asset_ids": [env.ids["a"]]}, headers=HUMAN).status_code == 200
    before = _image_signature(env.images.glob("*.png"))

    assert client.request("DELETE", f"/api/folders/{parent}", json={"confirm": "隠す親"},
                          headers=HUMAN).status_code == 200
    # 隠れている間はどこにも出ない
    tree = client.get("/api/folders").json()
    assert [item["name"] for item in tree["items"]] == ["残すフォルダ"]
    assert tree["items"][0]["count"] == 1, "隠したフォルダの行を他のフォルダの件数に数えた"
    assert client.get(f"/api/folders/{parent}/assets").status_code == 404
    assert client.get(f"/api/folders/{child}/assets").status_code == 404
    assert client.get(f"/api/folders/{other}/assets").json()["total"] == 1
    # **行は残っている**（親 2 + 子 1 + 残す 1 = 4 行）
    with env.app.state.store.locked() as con:
        rows = [tuple(row) for row in con.execute(
            "SELECT folder_id, asset_id FROM folder_member ORDER BY folder_id, asset_id")]
        assert len(rows) == 4, rows

    # **戻す**（まだ口が無いので DB を直接。データが残っていることの確認）
    with env.app.state.store.transaction() as con:
        con.execute("UPDATE folder SET deleted_at = NULL WHERE id IN (?, ?)", (parent, child))
        assert con.execute("SELECT count(*) FROM folder_member").fetchone()[0] == 4
    tree = client.get("/api/folders").json()
    assert sorted(item["name"] for item in tree["items"]) == ["残すフォルダ", "隠す親"]
    restored = [item for item in tree["items"] if item["id"] == parent][0]
    assert restored["count"] == 2, "戻したのに中身の件数が 0（論理削除で行を消していた）"
    assert [row["id"] for row in restored["children"]] == [child]
    assert restored["children"][0]["count"] == 1
    got = client.get(f"/api/folders/{parent}/assets?sort=position").json()
    assert got["total"] == 2
    assert [item["id"] for item in got["items"]] == [env.ids["a"], env.ids["b"]]
    assert client.get(f"/api/folders/{child}/assets").json()["items"][0]["id"] == env.ids["c"]
    assert _image_signature(env.images.glob("*.png")) == before, "実ファイルが動いた"


def test_only_purge_removes_the_membership_rows(env):
    """**B-1**: `folder_member` の行が消えるのは **`purge` のときだけ**。他のフォルダの行は残る。

    論理削除 → 戻す → `purge` の順に通す（隠したフォルダは `_row` が 404 なので、
    実削除の口は**生きているフォルダにだけ**打てる。隠したまま実削除する口はまだ無い）。

    壊すと落ちる: 論理削除で `folder_member` を消す／`purge` で行を残す（外部キーの CASCADE が
    効いていない）／`purge` で他のフォルダの行まで消す／`purge` が画像を消す。
    """
    client = env.client
    hide = _new(client, "実削除する").json()["id"]
    keep = _new(client, "残す").json()["id"]
    assert client.post(f"/api/folders/{hide}/members",
                       json={"asset_ids": [env.ids["a"], env.ids["b"]]},
                       headers=HUMAN).status_code == 200
    assert client.post(f"/api/folders/{keep}/members", json={"asset_ids": [env.ids["a"]]},
                       headers=HUMAN).status_code == 200
    before = _image_signature(env.images.glob("*.png"))
    with env.app.state.store.locked() as con:
        assets_before = [tuple(row) for row in con.execute("SELECT * FROM asset ORDER BY id")]

    # 論理削除：行は残る（3 行）
    assert client.request("DELETE", f"/api/folders/{hide}", json={"confirm": "実削除する"},
                          headers=HUMAN).json()["purged"] is False
    with env.app.state.store.locked() as con:
        assert con.execute("SELECT count(*) FROM folder_member").fetchone()[0] == 3

    # 戻す（まだ口が無いので DB を直接）
    with env.app.state.store.transaction() as con:
        con.execute("UPDATE folder SET deleted_at = NULL WHERE id = ?", (hide,))

    # 実削除：隠したフォルダの行だけが消える（残す側の 1 行は残る）
    got = client.request("DELETE", f"/api/folders/{hide}",
                         json={"confirm": "実削除する", "purge": True}, headers=HUMAN)
    assert got.status_code == 200, got.text
    assert got.json()["purged"] is True and got.json()["assets_deleted"] == 0
    with env.app.state.store.locked() as con:
        assert con.execute("SELECT count(*) FROM folder").fetchone()[0] == 1
        rows = [tuple(row) for row in con.execute(
            "SELECT folder_id, asset_id FROM folder_member")]
        assert rows == [(keep, env.ids["a"])], rows
        assert [tuple(row) for row in con.execute("SELECT * FROM asset ORDER BY id")] \
            == assets_before
    assert client.get(f"/api/folders/{keep}/assets").json()["total"] == 1
    assert _image_signature(env.images.glob("*.png")) == before, "purge で実ファイルが動いた"


def test_the_files_do_not_move_when_folders_change(env):
    """**R2 の線 4**: **実ファイルは 1 バイトも動かない**（前後で署名）。

    作る・入れる・外す・名前を変える・親を変える・消す（論理削除と実削除）の**全部**を通した
    前後で、画像の署名（大きさ・mtime・sha256）と `asset_location` が変わらないこと。
    """
    client = env.client
    images = sorted(env.images.glob("*.png"))
    before = _image_signature(images)
    with env.app.state.store.locked() as con:
        locations_before = [tuple(row) for row in con.execute(
            "SELECT * FROM asset_location ORDER BY path")]

    parent = _new(client, "親").json()["id"]
    child = _new(client, "子", parent_id=parent).json()["id"]
    ids = [env.ids["a"], env.ids["b"], env.ids["c"]]
    assert client.post(f"/api/folders/{child}/members", json={"asset_ids": ids},
                       headers=HUMAN).status_code == 200
    assert client.post(f"/api/folders/{parent}/members", json={"asset_ids": ids[:1]},
                       headers=HUMAN).status_code == 200
    assert client.request("DELETE", f"/api/folders/{parent}/members",
                          json={"asset_ids": ids[:1]}, headers=HUMAN).status_code == 200
    assert client.patch(f"/api/folders/{child}", json={"name": "子（名前を変えた）"},
                        headers=HUMAN).status_code == 200
    assert client.patch(f"/api/folders/{child}", json={"parent_id": None, "position": 5},
                        headers=HUMAN).status_code == 200
    assert client.request("DELETE", f"/api/folders/{parent}",
                          json={"confirm": "親"}, headers=HUMAN).status_code == 200
    assert client.request("DELETE", f"/api/folders/{child}",
                          json={"confirm": "子（名前を変えた）", "purge": True},
                          headers=HUMAN).status_code == 200

    assert _image_signature(images) == before, "フォルダの操作で実ファイルが動いた"
    with env.app.state.store.locked() as con:
        assert [tuple(row) for row in con.execute(
            "SELECT * FROM asset_location ORDER BY path")] == locations_before


# ---- 2. 名前の一意（同じ親だけ）・親の検査 ----


def test_two_folders_under_the_same_parent_cannot_share_a_name(env):
    """**同じ親の中で同名は 422・別の親なら同名可**（設計 §16.9 の G-2 (b)）。

    壊すと落ちる: 一意の索引を外す（表が重複を受ける）／サービス層の検査を外す（422 が 200 に）／
    `coalesce(parent_id, '')` をやめる（**根の同名が通る**＝NULL の罠）。
    """
    client = env.client
    root = _new(client, "根")
    assert root.status_code == 200, root.text
    # 根の下の同名（`parent_id` が NULL どうし）→ **422**
    dup = _new(client, "根")
    assert dup.status_code == 422, dup.text
    assert dup.json()["code"] == "folder_name_taken"

    # 別の親の下なら同名でよい
    left = _new(client, "左").json()["id"]
    right = _new(client, "右").json()["id"]
    assert _new(client, "同じ名前", parent_id=left).status_code == 200
    assert _new(client, "同じ名前", parent_id=right).status_code == 200
    # 同じ親の下の 2 つ目は 422
    assert _new(client, "同じ名前", parent_id=left).status_code == 422

    # 名前を変えるときも同じ規則（自分は除く）
    other = _new(client, "別名", parent_id=left).json()["id"]
    got = client.patch(f"/api/folders/{other}", json={"name": "同じ名前"}, headers=HUMAN)
    assert got.status_code == 422 and got.json()["code"] == "folder_name_taken"
    # 自分自身の名前（変えない）は通る
    assert client.patch(f"/api/folders/{other}", json={"name": "別名"},
                        headers=HUMAN).status_code == 200


def test_a_folder_cannot_be_moved_under_its_own_child(env):
    """**循環する親は 422**（設計 §6.1 の `PATCH {parent_id}`）。

    壊すと落ちる: 循環の検査を外す（木が無限に回る／子が根として出る）。
    """
    client = env.client
    top = _new(client, "一番上").json()["id"]
    middle = _new(client, "中", parent_id=top).json()["id"]
    bottom = _new(client, "下", parent_id=middle).json()["id"]

    got = client.patch(f"/api/folders/{top}", json={"parent_id": bottom}, headers=HUMAN)
    assert got.status_code == 422, got.text
    assert got.json()["code"] == "folder_cycle"
    again = client.patch(f"/api/folders/{middle}", json={"parent_id": middle}, headers=HUMAN)
    assert again.status_code == 422 and again.json()["code"] == "folder_cycle"
    # 親を自分自身にはできない（`parent_id` を自分にする）
    self_parent = client.patch(f"/api/folders/{top}", json={"parent_id": top}, headers=HUMAN)
    assert self_parent.status_code == 422

    # 循環していない移動は通る（下を一番上へ）
    moved = client.patch(f"/api/folders/{bottom}", json={"parent_id": top}, headers=HUMAN)
    assert moved.status_code == 200, moved.text
    tree = client.get("/api/folders").json()
    assert tree["total"] == 3
    # 根は 1 つだけ（循環していれば根が 0 になるか 2 つになる）
    assert len(tree["items"]) == 1 and tree["items"][0]["id"] == top
    assert sorted(child["id"] for child in tree["items"][0]["children"]) == sorted([middle, bottom])


def test_a_folder_needs_an_existing_live_parent(env):
    """**存在しない親・消した親は 422**（500 にしない）。親を消すと子も隠れる。

    壊すと落ちる: `parent_id` を検査せずに入れる（外部キー違反で 500）／
    隠した親の下に作れてしまう（木から見えなくなる）。
    """
    client = env.client
    got = _new(client, "迷子", parent_id="01MISSING")
    assert got.status_code == 422, got.text
    assert got.json()["code"] == "parent_missing"

    parent = _new(client, "親").json()["id"]
    assert _new(client, "子", parent_id=parent).status_code == 200
    assert client.request("DELETE", f"/api/folders/{parent}", json={"confirm": "親"},
                          headers=HUMAN).status_code == 200
    # 隠れた親の下には作れない
    assert _new(client, "孫", parent_id=parent).status_code == 422
    # `null` は根（通る）
    assert client.patch(f"/api/folders/{parent}", json={}, headers=HUMAN).status_code == 404


def test_deleted_folders_leave_the_tree_and_their_names_can_be_reused(env):
    """論理削除は木から外し、**名前は作り直せる**（部分索引 `WHERE deleted_at IS NULL`）。

    壊すと落ちる: 論理削除で木から外さない／部分条件を外す（消した名前で作り直せない）。
    """
    client = env.client
    folder = _new(client, "作り直す").json()["id"]
    assert _new(client, "作り直す").status_code == 422
    assert client.request("DELETE", f"/api/folders/{folder}", json={"confirm": "作り直す"},
                          headers=HUMAN).status_code == 200
    assert client.get("/api/folders").json()["total"] == 0
    again = _new(client, "作り直す")
    assert again.status_code == 200, again.text
    # 消したフォルダの id を指す口は 404
    assert client.get(f"/api/folders/{folder}/assets").status_code == 404


# ---- 3. 消す前の確認・dry_run・purge ----


def test_a_folder_delete_needs_the_name_to_be_confirmed(env):
    """**名前を打ち込ませて確認する**（§6.1。仮想フォルダは作り直せない分類）。

    壊すと落ちる: `confirm` を見ない（無警告で消える）／`dry_run` が消してしまう。
    """
    client = env.client
    folder = _new(client, "確認が要る").json()["id"]
    assert client.post(f"/api/folders/{folder}/members", json={"asset_ids": [env.ids["a"]]},
                       headers=HUMAN).status_code == 200

    dry = client.delete(f"/api/folders/{folder}?dry_run=true", headers=HUMAN)
    assert dry.status_code == 200, dry.text
    body = dry.json()
    assert body["dry_run"] is True
    assert body["folders"] == 1 and body["members"] == 1 and body["assets_deleted"] == 0
    assert client.get("/api/folders").json()["total"] == 1, "dry_run が消した"

    missing = client.delete(f"/api/folders/{folder}", headers=HUMAN)
    assert missing.status_code == 422 and missing.json()["code"] == "confirm_required"
    wrong = client.request("DELETE", f"/api/folders/{folder}",
                           json={"confirm": "違う名前"}, headers=HUMAN)
    assert wrong.status_code == 422 and wrong.json()["code"] == "confirm_required"
    assert client.get("/api/folders").json()["total"] == 1, "確認が違うのに消した"


def test_purge_removes_the_rows_but_never_the_images(env):
    """`purge:true` は実削除（`DELETE FROM folder`。CASCADE は `folder_member` まで）。

    壊すと落ちる: `purge` が画像を消す／`folder` の行を残す／子フォルダを残す。
    """
    client = env.client
    top = _new(client, "実削除").json()["id"]
    child = _new(client, "子", parent_id=top).json()["id"]
    assert client.post(f"/api/folders/{child}/members", json={"asset_ids": [env.ids["a"]]},
                       headers=HUMAN).status_code == 200
    before = _image_signature(env.images.glob("*.png"))

    got = client.request("DELETE", f"/api/folders/{top}",
                         json={"confirm": "実削除", "purge": True}, headers=HUMAN)
    assert got.status_code == 200, got.text
    assert got.json()["purged"] is True and got.json()["assets_deleted"] == 0
    with env.app.state.store.locked() as con:
        assert con.execute("SELECT count(*) FROM folder").fetchone()[0] == 0
        assert con.execute("SELECT count(*) FROM folder_member").fetchone()[0] == 0
        assert con.execute("SELECT count(*) FROM asset").fetchone()[0] == 3
    assert _image_signature(env.images.glob("*.png")) == before


# ---- 4. 片付け済みの画像は出さない ----


def test_deleted_images_are_hidden_from_folders_and_counts(env):
    """**`deleted_at IS NULL` の画像だけ**を出す（設計 §5.3 の注記。P2-0 の申し送り 4）。

    壊すと落ちる: 論理削除した画像を中身の一覧・件数に出す（片付け済みの枚がカタログに残る）。
    """
    client = env.client
    folder = _new(client, "片付け").json()["id"]
    assert client.post(f"/api/folders/{folder}/members",
                       json={"asset_ids": [env.ids["a"], env.ids["b"]]},
                       headers=HUMAN).status_code == 200
    assert client.get(f"/api/folders/{folder}/assets").json()["total"] == 2
    with env.app.state.store.transaction() as con:
        con.execute("UPDATE asset SET deleted_at = '2026-10-20T00:00:00Z' WHERE id = ?",
                    (env.ids["a"],))
    got = client.get(f"/api/folders/{folder}/assets").json()
    assert got["total"] == 1 and [item["id"] for item in got["items"]] == [env.ids["b"]]
    tree = client.get("/api/folders").json()
    assert tree["items"][0]["count"] == 1, "件数に片付け済みの画像を数えた"


# ---- 5. 入れる・外すの細部 ----


def test_adding_members_is_idempotent_and_rejects_unknown_assets(env):
    """**何度送っても同じ**（家風）。知らない id・片付け済みは **422**（黙って落とさない）。

    壊すと落ちる: 2 回目で 409/500 になる／知らない id を黙って捨てる。
    """
    client = env.client
    folder = _new(client, "冪等").json()["id"]
    asset = env.ids["a"]
    first = client.post(f"/api/folders/{folder}/members", json={"asset_ids": [asset]},
                        headers=HUMAN)
    second = client.post(f"/api/folders/{folder}/members", json={"asset_ids": [asset]},
                         headers=HUMAN)
    assert (first.status_code, second.status_code) == (200, 200), second.text
    assert first.json()["added"] == [asset] and second.json()["added"] == []
    assert second.json()["already"] == [asset]
    assert second.json()["count"] == 1

    bad = client.post(f"/api/folders/{folder}/members", json={"asset_ids": ["01MISSING"]},
                      headers=HUMAN)
    assert bad.status_code == 422 and bad.json()["code"] == "asset_missing"
    empty = client.post(f"/api/folders/{folder}/members", json={"asset_ids": []}, headers=HUMAN)
    assert empty.status_code == 422

    with env.app.state.store.transaction() as con:
        con.execute("UPDATE asset SET deleted_at = 't' WHERE id = ?", (env.ids["b"],))
    gone = client.post(f"/api/folders/{folder}/members", json={"asset_ids": [env.ids["b"]]},
                       headers=HUMAN)
    assert gone.status_code == 422, "片付け済みの画像を入れた"

    # 入っていない id を外すのは `not_member`（黙って捨てない・422 にしない）
    removed = client.request("DELETE", f"/api/folders/{folder}/members",
                             json={"asset_ids": [env.ids["c"]]}, headers=HUMAN)
    assert removed.status_code == 200
    assert removed.json()["removed"] == [] and removed.json()["not_member"] == [env.ids["c"]]


def test_the_folder_assets_list_sorts_and_pages(env):
    """中身の一覧の並び（`position` / `added` / `name`）と `next_cursor`。

    壊すと落ちる: `sort` を無視する（常に同じ順）／`next_cursor` を返さない／
    `sort` の語彙を検査しない（422 でなく 500）。
    """
    client = env.client
    folder = _new(client, "並び").json()["id"]
    order = [env.ids["c"], env.ids["a"], env.ids["b"]]
    assert client.post(f"/api/folders/{folder}/members", json={"asset_ids": order},
                       headers=HUMAN).status_code == 200
    by_position = client.get(f"/api/folders/{folder}/assets?sort=position").json()
    assert [item["id"] for item in by_position["items"]] == order
    assert [item["position"] for item in by_position["items"]] == [0, 1, 2]
    by_name = client.get(f"/api/folders/{folder}/assets?sort=name").json()
    assert [Path(item["path"]).name for item in by_name["items"]] == ["a.png", "b.png", "c.png"]
    page = client.get(f"/api/folders/{folder}/assets?limit=2").json()
    assert page["total"] == 3 and page["next_cursor"] == 2
    rest = client.get(f"/api/folders/{folder}/assets?limit=2&cursor={page['next_cursor']}").json()
    assert [item["id"] for item in rest["items"]] == order[2:] and rest["next_cursor"] is None
    bad = client.get(f"/api/folders/{folder}/assets?sort=robot")
    assert bad.status_code == 422


# ---- 6. 語彙・人だけ・守り ----


def test_the_folder_vocabulary_is_checked_with_422(env):
    """**語彙の外は 422**（500 にしない。家風「語彙は口で検査する」）。

    壊すと落ちる: `kind` をそのまま INSERT する（表の `CHECK` で 500）／名前の長さ・空を見ない。
    """
    client = env.client
    bad_kind = client.post("/api/folders", json={"name": "x", "kind": "robot"}, headers=HUMAN)
    assert bad_kind.status_code == 422, bad_kind.text
    assert "manual" in bad_kind.json()["details"]["allowed"]
    assert client.post("/api/folders", json={"name": "   "}, headers=HUMAN).status_code == 422
    too_long = client.post("/api/folders", json={"name": "あ" * 121}, headers=HUMAN)
    assert too_long.status_code == 422
    folder = _new(client, "語彙").json()["id"]
    assert client.patch(f"/api/folders/{folder}", json={"position": -1},
                        headers=HUMAN).status_code == 422
    assert client.patch(f"/api/folders/{folder}", json={"robot": 1},
                        headers=HUMAN).status_code == 422
    # actor の語彙（`human` / `agent` 以外は 422。P6-1a の監査 A1）
    robot = client.get("/api/folders", headers={"X-Image-Reviewer-Actor": "robot"})
    assert robot.status_code == 422


def test_only_a_human_can_write_the_catalog(env):
    """**403（エージェント）**: 書く口は人だけ。読む口はエージェントも読める。

    壊すと落ちる: `require_human` を外す（エージェントがフォルダを作れる／消せる）。
    """
    client = env.client
    folder = _new(client, "人だけ").json()["id"]
    agent = {"X-Image-Reviewer-Actor": "agent"}
    for method, path, body in (
        ("POST", "/api/folders", {"name": "x"}),
        ("PATCH", f"/api/folders/{folder}", {"name": "y"}),
        ("DELETE", f"/api/folders/{folder}", {"confirm": "人だけ"}),
        ("POST", f"/api/folders/{folder}/members", {"asset_ids": [env.ids["a"]]}),
        ("DELETE", f"/api/folders/{folder}/members", {"asset_ids": [env.ids["a"]]}),
    ):
        got = client.request(method, path, json=body, headers=agent)
        assert got.status_code == 403, f"{method} {path}: {got.status_code} {got.text[:120]}"
        assert got.json()["code"] == "human_only"
        # ヘッダが無い（＝エージェント扱い）も 403
        assert client.request(method, path, json=body).status_code == 403
    # 読む口は 200
    assert client.get("/api/folders").status_code == 200
    assert client.get(f"/api/folders/{folder}/assets").status_code == 200
    assert client.get("/api/folders").json()["total"] == 1, "403 の要求が書いてしまった"


def test_the_new_endpoints_are_guarded(env):
    """**`Host: evil` と `Content-Type: text/plain` は 403**（`app.py` の middleware）。

    壊すと落ちる: ルーターを `app.py` に載せ忘れる（守りが掛からない）。
    """
    client = env.client
    assert client.post("/api/folders", json={"name": "x"},
                       headers={**HUMAN, "Host": "evil.example"}).status_code == 403
    assert client.post("/api/folders", content=b'{"name": "x"}',
                       headers={**HUMAN, "Content-Type": "text/plain"}).status_code == 403


def test_a_smart_folder_needs_a_query_from_the_vocabulary(env):
    """スマートフォルダは**条件の列挙**で検査する（§10.2。生の SQL は受けない）。

    壊すと落ちる: `smart_query` をそのまま保存する（任意の SQL を受ける）／
    フィールドの列挙を検査しない（422 でなく保存）。
    """
    client = env.client
    no_query = client.post("/api/folders", json={"name": "賢い", "kind": "smart"},
                           headers=HUMAN)
    assert no_query.status_code == 422 and no_query.json()["code"] == "smart_query_required"
    bad_field = client.post("/api/folders", json={
        "name": "賢い", "kind": "smart",
        "smart_query": {"all": [{"field": "sql", "op": "has", "value": "1=1"}]}},
        headers=HUMAN)
    assert bad_field.status_code == 422 and bad_field.json()["code"] == "smart_query_bad"
    bad_op = client.post("/api/folders", json={
        "name": "賢い", "kind": "smart",
        "smart_query": {"all": [{"field": "tag", "op": "drop table", "value": "x"}]}},
        headers=HUMAN)
    assert bad_op.status_code == 422
    good = client.post("/api/folders", json={
        "name": "1girl だけ", "kind": "smart",
        "smart_query": {"all": [{"field": "tag", "op": "has", "value": "1girl"},
                                {"field": "review_state", "op": "in", "value": ["unreviewed"]}]}},
        headers=HUMAN)
    assert good.status_code == 200, good.text
    body = good.json()
    assert body["kind"] == "smart"
    assert json.loads(body["smart_query"])["all"][0] == {
        "field": "tag", "op": "has", "value": "1girl"}
    listed = client.get(f"/api/folders/{body['id']}/assets").json()
    assert listed["smart"] is True and "まだ使えません" in listed["note"], listed
    # manual に条件は付けられない
    manual = client.post("/api/folders", json={
        "name": "手で", "kind": "manual",
        "smart_query": {"all": [{"field": "tag", "op": "has", "value": "x"}]}}, headers=HUMAN)
    assert manual.status_code == 422


# ---- 7. GET は 1 バイトも書かない ----


def test_get_folders_writes_nothing(env):
    """**`GET` は 1 バイトも書かない**（家風）。**ファイルの中身と全表の中身**を前後で比べる。

    壊すと落ちる: `GET` で `count_cache` を埋める／`GET` で `smart_query` を解決して
    どこかに書き込む／`GET` で `added_at` を更新する。
    """
    client = env.client
    folder = _new(client, "読むだけ").json()["id"]
    assert client.post(f"/api/folders/{folder}/members",
                       json={"asset_ids": [env.ids["a"], env.ids["b"]]},
                       headers=HUMAN).status_code == 200
    before_files = _files(env.data)
    with env.app.state.store.locked() as con:
        before_rows = _rows_digest(con)
    for path in ("/api/folders", f"/api/folders/{folder}/assets",
                 f"/api/folders/{folder}/assets?sort=added&limit=1",
                 f"/api/folders/{folder}/assets?cursor=1", "/api/assets?limit=100",
                 "/api/stats"):
        resp = client.get(path, headers=HUMAN)
        assert resp.status_code == 200, f"{path}: {resp.status_code} {resp.text[:200]}"
    with env.app.state.store.locked() as con:
        assert _rows_digest(con) == before_rows, "GET が行の中身を変えた"
    assert _files(env.data) == before_files, "GET がファイルの中身を変えた"


# ---- 8. v7 に足した形（部分一意索引）----


def test_the_v7_unique_index_is_the_partial_expression_shape(tmp_path: Path):
    """**v7 に足した形**: `ux_folder_name` は `folder` の**式索引＋部分索引**。

    期待値は**リテラル**（`db.V7_EXPRESSION_INDEXES` から作らない）。見るもの:

    - 索引名と表（**索引名は DB 全体で一意**。他の表に同名があると黙って効かない）
    - `sqlite_master.sql` を空白を詰めた物が、**`coalesce(parent_id, '')` と
      `WHERE deleted_at IS NULL` と `UNIQUE`** を含む（列の並びもこの 1 本で決まる）
    - `PRAGMA index_info` に**式の列**（`cid = -2`）がある（`ON folder(parent_id, name)` でない）
    - **根（`parent_id` が NULL）どうしでも重複を拒む**（NULL の罠）
    - **論理削除した行は対象外**（同じ名前を作り直せる）

    壊すと落ちる: 索引を `ON folder(parent_id, name)` にする／`WHERE deleted_at IS NULL` を外す／
    `coalesce` をやめる／索引を消す。
    """
    con = db.open_db(tmp_path)
    try:
        row = con.execute("SELECT tbl_name, sql FROM sqlite_master WHERE type = 'index'"
                          " AND name = 'ux_folder_name'").fetchone()
        assert row is not None, "ux_folder_name が無い（式索引を DDL から外すと気づかない）"
        assert row[0] == "folder", f"ux_folder_name が folder の索引ではない: {row[0]}"
        got_sql = "".join(str(row[1] or "").split()).lower()
        assert got_sql == WANT_INDEX_SQL, got_sql
        assert "wheredeleted_atisnull" in got_sql, "部分索引でない（消した名前で作り直せない）"
        cids = [info[1] for info in con.execute("PRAGMA index_info(ux_folder_name)")]
        assert any(int(cid) < 0 for cid in cids), f"式索引でない（親が NULL の同名が通る）: {cids}"

        con.execute("INSERT INTO folder(id, parent_id, name, kind, created_at)"
                    " VALUES ('r1', NULL, '根', 'manual', 't')")
        # **根どうしの同名**（`UNIQUE(parent_id, name)` なら通ってしまう形）
        with pytest.raises(sqlite3.IntegrityError):
            con.execute("INSERT INTO folder(id, parent_id, name, kind, created_at)"
                        " VALUES ('r2', NULL, '根', 'manual', 't')")
        con.execute("INSERT INTO folder(id, parent_id, name, kind, created_at)"
                    " VALUES ('c1', 'r1', '子', 'manual', 't')")
        with pytest.raises(sqlite3.IntegrityError):
            con.execute("INSERT INTO folder(id, parent_id, name, kind, created_at)"
                        " VALUES ('c2', 'r1', '子', 'manual', 't')")
        # 別の親なら同じ名前でよい
        con.execute("INSERT INTO folder(id, parent_id, name, kind, created_at)"
                    " VALUES ('c3', 'c1', '子', 'manual', 't')")
        # 論理削除した行は対象外（名前を作り直せる）
        con.execute("UPDATE folder SET deleted_at = 't' WHERE id = 'r1'")
        con.execute("INSERT INTO folder(id, parent_id, name, kind, created_at)"
                    " VALUES ('r3', NULL, '根', 'manual', 't')")
    finally:
        con.close()


def test_the_guard_refuses_a_missing_or_wrong_unique_index(tmp_path: Path):
    """**形のガード**（`db._check_v7_shape`）が、索引の**無い・形の違う** v7 を落とす。

    壊すと落ちる: `_check_v7_shape` から `V7_EXPRESSION_INDEXES` の検査を外す
    （`ON folder(parent_id, name)` のまま「版は 7・根の同名が通る」DB ができる）。
    """
    # ① 索引を `ON folder(parent_id, name)`（部分でも式でもない）に差し替える
    con = db.open_db(tmp_path)
    try:
        con.execute("DROP INDEX ux_folder_name")
        con.execute("CREATE UNIQUE INDEX ux_folder_name ON folder(parent_id, name)")
        with pytest.raises(RuntimeError) as got:
            db._check_v7_shape(con)
        assert "ux_folder_name" in str(got.value), str(got.value)
    finally:
        con.close()

    # ② 索引を消す
    second = tmp_path / "second"
    con = db.open_db(second)
    try:
        con.execute("DROP INDEX ux_folder_name")
        with pytest.raises(RuntimeError) as got:
            db._check_v7_shape(con)
        assert "ux_folder_name" in str(got.value)
    finally:
        con.close()

    # ③ 部分条件だけを外す（式は同じ。**消した名前で作り直せなくなる**）
    third = tmp_path / "third"
    con = db.open_db(third)
    try:
        con.execute("DROP INDEX ux_folder_name")
        con.execute("CREATE UNIQUE INDEX ux_folder_name"
                    " ON folder(coalesce(parent_id, ''), name)")
        with pytest.raises(RuntimeError) as got:
            db._check_v7_shape(con)
        assert "deleted_at" in str(got.value), str(got.value)
    finally:
        con.close()


# ---- 9. 名前の取り合いを、書く前に見る（P2-0 の監査 C-2）----


def _make_v6(data: Path) -> None:
    """**v6 の DB** を手順どおりに作る（`db.open_db` を使うと v7 まで上がるので使わない）。"""
    data.mkdir(parents=True, exist_ok=True)
    con = db.connect(data)
    try:
        con.executescript(db.DDL)
        db._migrate_v2(con)
        db._migrate_v3(con)
        db._migrate_v4(con)
        db._migrate_v5(con)
        db._migrate_v6(con)
        con.execute("PRAGMA user_version = 6")
        con.execute("INSERT INTO asset(id, sha256, kind, first_seen_at, last_seen_at)"
                    " VALUES ('a1', ?, 'generated', 't', 't')", ("a" * 64,))
    finally:
        con.close()


def test_a_clean_v6_database_is_not_a_conflict(tmp_path: Path):
    """**誤検知しない**: きれいな v6（`asset` にまだ `source` が無い）は `ok`。

    壊すと落ちる: 「v7 の列が足りない」を違反に数える（実データの v6 が全部読み取り専用になる）。
    """
    data = tmp_path / "data"
    _make_v6(data)
    got = backup.inspect_db(data)
    assert got["mode"] == "ok" and got["reason"] == "ok", got
    assert got["schema_version"] == 6 and got["conflicts"] in (None, [])


def test_a_taken_index_name_is_refused_before_a_byte_is_written(tmp_path: Path):
    """**C-2**: v7 の名前を他の表が使っていたら、**書く前に**読み取り専用で起動する。

    壊すと落ちる: `inspect_db` の `v7_conflicts` を外す（移行が途中まで進み、版 6 のまま
    v7 の物が半分在る DB と控えが残る＝P2-0 の監査 C-2 の再現）。
    """
    data = tmp_path / "data"
    _make_v6(data)
    con = sqlite3.connect(data / "db.sqlite3")
    try:
        con.execute("CREATE TABLE other(x TEXT)")
        # **索引名は DB 全体で一意**（`CREATE INDEX IF NOT EXISTS` は同名が他の表にあると黙る）
        con.execute("CREATE INDEX ix_folder_parent ON other(x)")
        con.execute("PRAGMA user_version = 6")
        con.commit()
    finally:
        con.close()
    before = hashlib.sha256((data / "db.sqlite3").read_bytes()).hexdigest()

    got = backup.inspect_db(data)
    assert got["mode"] == "read_only", got
    assert got["reason"] == "schema_conflict", got
    assert got["read_only"] is True and got["guidance"], got
    assert any("ix_folder_parent" in line for line in got["conflicts"]), got["conflicts"]
    # **1 バイトも書いていない**（版も形もそのまま）
    assert hashlib.sha256((data / "db.sqlite3").read_bytes()).hexdigest() == before
    con = sqlite3.connect(data / "db.sqlite3")
    try:
        assert con.execute("PRAGMA user_version").fetchone()[0] == 6
        assert con.execute("SELECT count(*) FROM sqlite_master WHERE name = 'folder'"
                           ).fetchone()[0] == 0
    finally:
        con.close()


def test_a_squatted_folder_table_is_refused_before_a_byte_is_written(tmp_path: Path):
    """同じ親の同名を守れない形（`deleted_at` の無い `folder`）も**先に**断る。

    壊すと落ちる: `v7_conflicts` が「在るのに列が足りない表」を見ない（`ux_folder_name` を
    作るときに `no such column: deleted_at` で落ち、半端な DB が残る）。
    """
    data = tmp_path / "data"
    _make_v6(data)
    con = sqlite3.connect(data / "db.sqlite3")
    try:
        con.execute("CREATE TABLE folder(id TEXT PRIMARY KEY, parent_id TEXT, name TEXT NOT NULL,"
                    " kind TEXT NOT NULL, smart_query TEXT, position INTEGER NOT NULL DEFAULT 0,"
                    " count_cache INTEGER, count_cached_at TEXT, created_at TEXT NOT NULL)")
        con.commit()
    finally:
        con.close()
    got = backup.inspect_db(data)
    assert got["mode"] == "read_only" and got["reason"] == "schema_conflict", got
    assert any("deleted_at" in line for line in got["conflicts"]), got["conflicts"]


# ---- 10. P2-0 の申し送り: 出所は `asset.source` ----


def test_the_asset_source_comes_from_the_asset_row(env):
    """**出所は `asset.source`**（v7 の列。P2-0 の申し送り 1）。

    `asset_meta.source`（来歴を取った経路）ではなく、**取り込みの出所**を返す。
    `source_url` / `ref_tags` も列から読む（前は `None` / `[]` の置き場だった）。

    壊すと落ちる: `_asset_dict` が `asset_meta.source` を返す（4 経路が全部 `scan` に見える）／
    `register(source=...)` が `asset.source` に書かない。
    """
    client = env.client
    # `c` は source='drop' で登録した（`store.register` の道）
    got = client.get(f"/api/assets/{env.ids['c']}").json()
    assert got["source"] == "drop", got["source"]
    with env.app.state.store.transaction() as con:
        con.execute("UPDATE asset SET source = 'url', source_url = ?, ref_tags = ?"
                    " WHERE id = ?",
                    ("https://example.com/a.png", json.dumps(["pose"], ensure_ascii=False),
                     env.ids["c"]))
        # `asset_meta.source` は別の意味（来歴の経路）。**ここを変えても `source` は変わらない**
        con.execute("UPDATE asset_meta SET source = 'workflow_node' WHERE asset_id = ?",
                    (env.ids["c"],))
    got = client.get(f"/api/assets/{env.ids['c']}").json()
    assert got["source"] == "url"
    assert got["source_url"] == "https://example.com/a.png"
    assert got["ref_tags"] == ["pose"]
    # 一覧（`GET /api/assets`）の 1 行は `source` を出さない（既存の形を変えない）
    listed = client.get("/api/assets?limit=100").json()["items"]
    assert all("source" not in item for item in listed)


def test_register_refuses_an_unknown_source(tmp_path: Path):
    """語彙の外の `source` は **`ValueError`**（表の `CHECK` に当てて 500 にしない）。

    壊すと落ちる: 検査を外す（`sqlite3.IntegrityError` が上に抜ける）。
    """
    store = Store(tmp_path / "data")
    try:
        with pytest.raises(ValueError):
            store.register(sha256="a" * 64, path=str(tmp_path / "x.png"), size=1, mtime_ns=1,
                           width=1, height=1, fmt="png", meta=None, note=None, source="ftp")
    finally:
        store.close()


# ---- 11. 監査 B-3: 変異 12 通りを落とす（期待値はここにリテラルで書く）----
#
# 監査 `docs/p2-1-audit-report.md` の F で「全試験 622 でも生き残った」12 通り
# （S8・S9・S10・S11・S12・S14・S17・S18・S20・S24・S26・Y6。等価の Y2 を除く）を、
# **1 通りにつき 1 つ以上の試験**で落とす。**期待値は実装から取らない**（数も順も 422 も
# ここに書いた字）。壊し方は `.tmp-p2-1-fix/mut.py`（自分で作って全部落ちることを確かめた）。


def test_removing_one_image_keeps_the_other_images_in_the_folder(env):
    """**S8**: 「外す」は**送った 1 枚だけ**を外す（フォルダの中身を全部外さない）。

    監査の S8 は「`asset_ids` を見ずにフォルダの中身を全部消す」で、既存の試験は
    **1 枚しか入れていなかった**ので生き残った。

    壊すと落ちる: 外す口が `asset_ids` を見ずに `DELETE FROM folder_member WHERE folder_id = ?`
    にする（1 枚外すつもりで全部外れる）。
    """
    client = env.client
    folder = _new(client, "2 枚のうち 1 枚").json()["id"]
    assert client.post(f"/api/folders/{folder}/members",
                       json={"asset_ids": [env.ids["a"], env.ids["b"]]},
                       headers=HUMAN).status_code == 200
    got = client.request("DELETE", f"/api/folders/{folder}/members",
                         json={"asset_ids": [env.ids["a"]]}, headers=HUMAN)
    assert got.status_code == 200, got.text
    assert got.json()["removed"] == [env.ids["a"]]
    assert got.json()["count"] == 1
    with env.app.state.store.locked() as con:
        rows = [tuple(row) for row in con.execute(
            "SELECT folder_id, asset_id FROM folder_member")]
    assert rows == [(folder, env.ids["b"])], rows
    body = client.get(f"/api/folders/{folder}/assets").json()
    assert body["total"] == 1 and [item["id"] for item in body["items"]] == [env.ids["b"]]
    # 外した側の画像も消えない（一覧に出たまま）
    assert env.ids["a"] in [item["id"] for item in
                            client.get("/api/assets?limit=100").json()["items"]]


def test_the_folder_assets_list_sort_added_is_newest_first(env):
    """**S9**: `sort=added` は **`added_at` の新しい順**（古い順にしない）。

    入れた時刻を**リテラルで**入れて、並びそのものを期待値にする（同じ秒だと順が決まらない）。

    壊すと落ちる: `sort=added` の `ORDER BY m.added_at DESC` を `ASC` にする（古い順になる）。
    """
    client = env.client
    folder = _new(client, "入れた順").json()["id"]
    order = [env.ids["a"], env.ids["b"], env.ids["c"]]
    assert client.post(f"/api/folders/{folder}/members", json={"asset_ids": order},
                       headers=HUMAN).status_code == 200
    with env.app.state.store.transaction() as con:
        for asset_id, when in ((env.ids["a"], "2026-03-01T00:00:00Z"),
                               (env.ids["b"], "2026-01-01T00:00:00Z"),
                               (env.ids["c"], "2026-02-01T00:00:00Z")):
            con.execute("UPDATE folder_member SET added_at = ? WHERE folder_id = ? AND asset_id = ?",
                        (when, folder, asset_id))
    body = client.get(f"/api/folders/{folder}/assets?sort=added").json()
    assert [item["added_at"] for item in body["items"]] == [
        "2026-03-01T00:00:00Z", "2026-02-01T00:00:00Z", "2026-01-01T00:00:00Z"]
    assert [item["id"] for item in body["items"]] == [env.ids["a"], env.ids["c"], env.ids["b"]]


def test_the_last_page_has_no_next_cursor(env):
    """**S10**: 最後のページ（`cursor + limit == total`）の `next_cursor` は **`None`**。

    監査の S10 は「`next_cursor` を 1 つ先まで出す（`<=`）」。既存の試験は
    **total が limit で割り切れない**（3 枚・limit 2）形だけだったので生き残った。

    壊すと落ちる: `cursor + limit < total` を `<=` にする（最後のページに空の次ページが付く）／
    `next_cursor` を常に返す。
    """
    client = env.client
    folder = _new(client, "改ページ").json()["id"]
    assert client.post(f"/api/folders/{folder}/members",
                       json={"asset_ids": [env.ids["a"], env.ids["b"], env.ids["c"]]},
                       headers=HUMAN).status_code == 200
    # 3 枚を 3 枚で引く＝最後のページ（ちょうど割り切れる）
    full = client.get(f"/api/folders/{folder}/assets?limit=3").json()
    assert full["total"] == 3 and len(full["items"]) == 3
    assert full["next_cursor"] is None, "最後のページに next_cursor を出した"
    # 途中のページは次の位置を返す（1 枚目 → 1）
    first = client.get(f"/api/folders/{folder}/assets?limit=1").json()
    assert first["next_cursor"] == 1
    # 2 枚目から 2 枚＝最後のページ（1 + 2 == 3）
    tail = client.get(f"/api/folders/{folder}/assets?limit=2&cursor=1").json()
    assert tail["next_cursor"] is None
    # 3 枚目（最後の 1 枚）も None
    last = client.get(f"/api/folders/{folder}/assets?limit=1&cursor=2").json()
    assert last["next_cursor"] is None


def test_the_confirm_name_is_compared_exactly(env):
    """**S11**: 確認の名前は**大小文字を区別して**比べる（`abc` で `ABC` を消さない）。

    壊すと落ちる: 比べる前に `lower()` / `casefold()` を通す（違う名前で消える）。
    """
    client = env.client
    folder = _new(client, "ABC").json()["id"]
    wrong = client.request("DELETE", f"/api/folders/{folder}", json={"confirm": "abc"},
                           headers=HUMAN)
    assert wrong.status_code == 422, wrong.text
    assert wrong.json()["code"] == "confirm_required"
    # 実削除でも同じ（`purge` は確認を飛ばさない）
    wrong_purge = client.request("DELETE", f"/api/folders/{folder}",
                                 json={"confirm": "abc", "purge": True}, headers=HUMAN)
    assert wrong_purge.status_code == 422
    assert client.get("/api/folders").json()["total"] == 1, "違う名前で消した"
    ok = client.request("DELETE", f"/api/folders/{folder}", json={"confirm": "ABC"},
                        headers=HUMAN)
    assert ok.status_code == 200, ok.text


def test_purge_still_needs_the_confirmed_name(env):
    """**S12**: `purge:true` でも**名前の確認は要る**（実削除を無確認で通さない）。

    監査の S12 は「`purge:true` なら `confirm` を見ない」。既存の試験は正しい名前しか
    送っていなかった。**C-4**（`purge:"false"` の文字列）もここで固定する。

    壊すと落ちる: `purge` のときに `confirm` の検査を飛ばす（無確認で実削除）／
    `purge` を `bool()` で受ける（`"false"` が真になって実削除）。
    """
    client = env.client
    folder = _new(client, "実削除の確認").json()["id"]
    assert client.post(f"/api/folders/{folder}/members", json={"asset_ids": [env.ids["a"]]},
                       headers=HUMAN).status_code == 200
    for body in ({"purge": True}, {"purge": True, "confirm": "違う名前"},
                 {"confirm": "実削除の確認", "purge": "false"}):
        got = client.request("DELETE", f"/api/folders/{folder}", json=body, headers=HUMAN)
        assert got.status_code == 422, f"{body}: {got.status_code} {got.text[:120]}"
    assert client.get("/api/folders").json()["total"] == 1, "確認していないのに実削除した"
    with env.app.state.store.locked() as con:
        assert con.execute("SELECT count(*) FROM folder_member").fetchone()[0] == 1
    ok = client.request("DELETE", f"/api/folders/{folder}",
                        json={"confirm": "実削除の確認", "purge": True}, headers=HUMAN)
    assert ok.status_code == 200, ok.text
    assert ok.json()["purged"] is True
    with env.app.state.store.locked() as con:
        assert con.execute("SELECT count(*) FROM folder").fetchone()[0] == 0
        assert con.execute("SELECT count(*) FROM folder_member").fetchone()[0] == 0
        assert con.execute("SELECT count(*) FROM asset").fetchone()[0] == 3


def test_folder_names_refuse_control_and_invisible_characters(env):
    """**S14 / C-5**: 改行・制御文字・**見えない文字**は 422。見た目が同じ名前は NFC にそろえる。

    壊すと落ちる: `unicodedata` の分類（`Cc` / `Cf` / `Zl` / `Zp`）の検査を外す（改行入りの名前が
    通る）／NFC にそろえない（`ガ` と `ガ`（NFD）が同じ親に 2 つ並ぶ）。
    """
    client = env.client
    bad = ["改行\n入り", "制御\x01文字", "幅 0\u200b文字", "行区切り\u2028x", "先頭\ufeff"]
    for name in bad:
        got = _new(client, name)
        assert got.status_code == 422, f"{name!r}: {got.status_code} {got.text[:120]}"
    assert client.get("/api/folders").json()["total"] == 0, "見えない文字の名前が通った"
    # **NFC**: 同じに見える名前は 1 つだけ（2 つ目は同じ親の同名として 422）
    nfc = unicodedata.normalize("NFC", "ガ")
    nfd = unicodedata.normalize("NFD", "ガ")
    assert nfc != nfd, "試験の前提: NFC と NFD は別の文字列"
    assert _new(client, nfc).status_code == 200
    dup = _new(client, nfd)
    assert dup.status_code == 422, dup.text
    assert dup.json()["code"] == "folder_name_taken"
    assert client.get("/api/folders").json()["items"][0]["name"] == nfc


def _chain(client, depth: int) -> list[str]:
    """根から `depth` 段の鎖を作る（作れなくなったらその時点で止めて返す）。"""
    ids: list[str] = []
    parent = None
    for at in range(depth):
        got = _new(client, f"段 {at}", parent_id=parent)
        if got.status_code != 200:
            break
        parent = got.json()["id"]
        ids.append(parent)
    return ids


def test_a_folder_cannot_be_created_too_deep(env):
    """**S18**: 33 段目は作れない（上限は 32 段。根を 1 段目と数える）。

    壊すと落ちる: `create()` の `_depth_of(...) >= 32` を外す（33 段目が 200 でできる）。
    """
    client = env.client
    ids = _chain(client, 32)
    assert len(ids) == 32, f"32 段作れなかった（上限の判定が違う）: {len(ids)}"
    deep = _new(client, "33 段目", parent_id=ids[-1])
    assert deep.status_code == 422, deep.text
    assert deep.json()["code"] == "folder_too_deep"


def test_a_folder_cannot_be_moved_below_the_depth_limit(env):
    """**S17**: 深すぎる親の下へは**移せない**（`PATCH {parent_id}` の深さの検査）。

    壊すと落ちる: `update()` の `_depth_of(...) >= 32` を外す（32 段目の下へ移せて 33 段になる）。
    """
    client = env.client
    ids = _chain(client, 32)
    assert len(ids) == 32
    # 鎖の外にあるフォルダを、一番深いフォルダの下へ移す（循環ではない。深さだけが問題）
    loose = _new(client, "移す枝").json()["id"]
    moved = client.patch(f"/api/folders/{loose}", json={"parent_id": ids[-1]}, headers=HUMAN)
    assert moved.status_code == 422, moved.text
    assert moved.json()["code"] == "folder_too_deep"
    assert client.get("/api/folders").json()["total"] == 33
    # 深さの範囲内の移動は通る（検査が全部を止めていない）
    assert client.patch(f"/api/folders/{ids[1]}", json={"parent_id": ids[0]},
                        headers=HUMAN).status_code == 200


def test_a_deep_branch_cannot_be_moved_below_the_depth_limit(env):
    """**D-7**: 移すのは**枝ごと**なので、親の深さだけでなく**枝の高さ**も数える。

    監査の D-7（「31 段目の下へ 3 段の枝を移すと 34 段」）を、上限の 32 段で止める。
    壊すと落ちる: 移動の深さの検査で `_height_of()` を足さない（枝ごと移すと 33 段以上になる）。
    """
    client = env.client
    chain = _chain(client, 31)                  # 根を 1 段目として 31 個
    assert len(chain) == 31
    top = _new(client, "枝の上").json()["id"]
    leaf = _new(client, "枝の下", parent_id=top).json()["id"]
    assert leaf
    got = client.patch(f"/api/folders/{top}", json={"parent_id": chain[-1]}, headers=HUMAN)
    assert got.status_code == 422, got.text
    assert got.json()["code"] == "folder_too_deep"
    assert client.get("/api/folders").json()["total"] == 33
    # 1 段手前（30 段目）の下なら、枝 2 段でちょうど 32 段目まで。通る
    ok = client.patch(f"/api/folders/{top}", json={"parent_id": chain[-2]}, headers=HUMAN)
    assert ok.status_code == 200, ok.text


def test_switching_a_smart_folder_to_manual_drops_the_query(env):
    """**S20**: `kind` を `manual` に戻したら `smart_query` も落とす（条件が残らない）。

    壊すと落ちる: `manual` に戻しても条件を残す（「manual なのに条件がある」行ができる）／
    `kind='smart'` に戻すときに条件を要求しない。
    """
    client = env.client
    got = client.post("/api/folders", json={
        "name": "賢い", "kind": "smart",
        "smart_query": {"all": [{"field": "tag", "op": "has", "value": "1girl"}]}}, headers=HUMAN)
    assert got.status_code == 200, got.text
    folder = got.json()["id"]
    assert got.json()["smart_query"] is not None
    manual = client.patch(f"/api/folders/{folder}", json={"kind": "manual"}, headers=HUMAN)
    assert manual.status_code == 200, manual.text
    assert manual.json()["kind"] == "manual"
    assert manual.json()["smart_query"] is None, "manual に戻したのに条件が残った"
    listed = client.get(f"/api/folders/{folder}/assets").json()
    assert "smart" not in listed and "note" not in listed
    # 戻すときは条件が要る（条件なしで smart にはできない）
    assert client.patch(f"/api/folders/{folder}", json={"kind": "smart"},
                        headers=HUMAN).status_code == 422


def test_dry_run_writes_nothing(env):
    """**S24**: `DELETE ?dry_run=true` は**行もファイルも 1 バイトも書かない**。

    監査の S24 は「`dry_run` の道で 1 行書く」。`GET` の試験は `dry_run` の道を含まないので
    生き残った。ここでは `GET` と同じ物差し（`_files` と全表の中身）で比べる。

    壊すと落ちる: `dry_run` の道で `count_cache` を書く／`position` を直す／何かを INSERT する。
    """
    client = env.client
    folder = _new(client, "乾いた道").json()["id"]
    assert client.post(f"/api/folders/{folder}/members",
                       json={"asset_ids": [env.ids["a"], env.ids["b"]]},
                       headers=HUMAN).status_code == 200
    before_files = _files(env.data)
    with env.app.state.store.locked() as con:
        before_rows = _rows_digest(con)
    for _ in range(2):
        got = client.delete(f"/api/folders/{folder}?dry_run=true", headers=HUMAN)
        assert got.status_code == 200, got.text
        assert got.json()["dry_run"] is True and got.json()["folders"] == 1
        assert got.json()["members"] == 2
    with env.app.state.store.locked() as con:
        assert _rows_digest(con) == before_rows, "dry_run が行を書いた"
    assert _files(env.data) == before_files, "dry_run がファイルを書いた"


def test_the_folder_assets_limit_is_clamped(env):
    """**S26**: `limit` は 1〜1,000 に丸める（5,000 をそのまま使わない）。

    壊すと落ちる: `min(int(limit), 1000)` の丸めを外す（`limit=5000` が 5000 で返る）。
    """
    client = env.client
    folder = _new(client, "丸める").json()["id"]
    assert client.post(f"/api/folders/{folder}/members", json={"asset_ids": [env.ids["a"]]},
                       headers=HUMAN).status_code == 200
    assert client.get(f"/api/folders/{folder}/assets?limit=5000").json()["limit"] == 1000
    assert client.get(f"/api/folders/{folder}/assets?limit=-5").json()["limit"] == 1
    assert client.get(f"/api/folders/{folder}/assets?limit=0").json()["limit"] == 200
    assert client.get(f"/api/folders/{folder}/assets?limit=2").json()["limit"] == 2


def test_listing_all_assets_with_a_folder_is_refused(env):
    """**E-2 / G-4**: `GET /api/assets?folder=` は**黙って全件を返さない**（422。P2-2 で実装）。

    §6.1 は `?folder=` を書いているが、P2-1 の中身の口は `GET /api/folders/{id}/assets`。
    知らないクエリを黙って無視すると、**絞れていない全件**を「フォルダの中身」と読み違える。

    壊すと落ちる: `folder` を受け取って無視する（200 で全部を返す）。
    """
    client = env.client
    folder = _new(client, "絞りの口").json()["id"]
    got = client.get(f"/api/assets?folder={folder}")
    assert got.status_code == 422, f"{got.status_code} {got.text[:200]}"
    assert got.json()["code"] == "folder_filter_not_implemented"
    assert client.get("/api/assets?limit=100").status_code == 200, "folder を付けなければ今までどおり"
    # 中身はフォルダの口で取れる（案内どおり）
    assert client.get(f"/api/folders/{folder}/assets").status_code == 200


def test_a_v7_database_without_the_unique_index_is_repaired(tmp_path: Path):
    """**Y6**: P2-0 の頃の v7（`ux_folder_name` が無い）を開くと、**早期 return でも索引を補う**。

    監査の Y6 は `migrate()` の早期 return 側の `_top_up_v7` を外す変異。P2-0 の頃の v7 を開く
    試験が無かったので生き残った。**P2-0 のコードで先に v7 になった DB** が、名前一意の索引を
    持たないまま走ると「一意はサービス層だけ」になる。

    壊すと落ちる: 早期 return の `_top_up_v7(con)` を外す（索引が無いまま返る）。
    """
    con = db.open_db(tmp_path)
    try:
        con.execute("DROP INDEX ux_folder_name")
        assert con.execute("SELECT 1 FROM sqlite_master WHERE name = 'ux_folder_name'"
                           ).fetchone() is None
        con.execute("PRAGMA user_version = 7")
    finally:
        con.close()
    again = db.open_db(tmp_path)
    try:
        row = again.execute("SELECT tbl_name, sql FROM sqlite_master WHERE type = 'index'"
                            " AND name = 'ux_folder_name'").fetchone()
        assert row is not None, "P2-0 の頃の v7 に索引を補わない（早期 return の _top_up_v7 が無い）"
        assert row[0] == "folder"
        got_sql = "".join(str(row[1] or "").split()).lower()
        assert got_sql == WANT_INDEX_SQL, got_sql
        assert again.execute("PRAGMA user_version").fetchone()[0] == 7
    finally:
        again.close()
