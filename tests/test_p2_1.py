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

    壊すと落ちる: 削除が `asset` を消す（外部キーの CASCADE を `asset` 側から発火させる）／
    中身を消すときに `asset_location` を消す／`purge` でも画像を消す。
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
        assert con.execute("SELECT count(*) FROM folder_member").fetchone()[0] == 0
    listed = [item["id"] for item in client.get("/api/assets?limit=100").json()["items"]]
    for name in ("a", "b"):
        assert env.ids[name] in listed
    assert _image_signature(env.images.glob("*.png")) == before, "実ファイルが動いた"


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
