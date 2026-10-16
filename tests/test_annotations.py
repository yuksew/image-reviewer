"""画像の上の印（注記。P6-2）のテスト。

設計: docs/p6-design.md §0.6〜§0.9・§3.6・§4.2・§6.2・§6.3・§7
テスト方針: §8.1 の表（**何を壊すと落ちるか**）。各テストの docstring に表と同じ番号を書く。

`tmp_path` は `tests/conftest.py` が用意する（実データは使わない。§8 の末尾）。
"""

from __future__ import annotations

import os
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

from image_reviewer.annotations import AnnotationService, crop_box
from image_reviewer.review import ReviewError
from image_reviewer.store import Store

# ---- 道具 ----


def make_image(path: Path, size: tuple[int, int]) -> Path:
    """切り出しの対象になる本物の PNG を作る（合成。実データは使わない）。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", size, (200, 120, 90)).save(path)
    return path


def add_asset(store: Store, sha: str, name: str = "a.png", *, size: tuple[int, int] = (16, 16),
              make_file: bool = True) -> str:
    """1 枚登録する。`make_file=True` なら実体（PNG）も作る。"""
    path = store.data_dir.parent / "images" / name
    if make_file:
        make_image(path, size)
    asset_id, _ = store.register(sha256=sha, path=str(path), size=100, mtime_ns=1,
                                 width=size[0], height=size[1], fmt="png", meta=None, note=None)
    return asset_id


def error_of(func, *args, **kw) -> ReviewError:
    with pytest.raises(ReviewError) as got:
        func(*args, **kw)
    return got.value


def snapshot(root: Path) -> set[str]:
    """ファイルの一覧（`GET` が書かないことの検査）。"""
    return {str(p.relative_to(root)) for p in root.rglob("*") if p.is_file()}


@pytest.fixture
def env(tmp_path):
    store = Store(tmp_path / "data")
    service = AnnotationService(store)
    try:
        yield SimpleNamespace(store=store, annotations=service, tmp_path=tmp_path)
    finally:
        store.close()


# ---- 座標（§8.1 の 11・12・29）----


def test_coordinates_are_validated_and_roundtrip(env):
    """§8.1-11 / 12 を壊すと落ちる: 範囲の検査と、丸めない往復。

    `x=1.0` は境界として通り、`x + w > 1` と `w=0` は 422。`0.123456789` は**丸めずに**戻る。
    """
    asset = add_asset(env.store, "a" * 64)
    got = env.annotations.create(asset, shape="rect", x=0.123456789, y=0.0, w=0.5, h=0.25,
                                 body="左手")
    assert got["x"] == 0.123456789, "座標を丸めた（§8.1-12）"
    assert env.annotations.get(got["id"])["x"] == 0.123456789

    # 境界（x=1.0 は「幅 0」なので w は 0 より大きくできない → 通るのは x=0.5, w=0.5）
    edge = env.annotations.create(asset, shape="rect", x=0.5, y=0.5, w=0.5, h=0.5)
    assert edge["x"] + edge["w"] == 1.0

    bad = error_of(env.annotations.create, asset, shape="rect", x=0.5, y=0.0, w=0.5000001, h=0.1)
    assert bad.status == 422 and "w" in bad.details["fields"]
    bad = error_of(env.annotations.create, asset, shape="rect", x=0.1, y=0.0, w=0, h=0.1)
    assert bad.status == 422 and "w" in bad.details["fields"]
    bad = error_of(env.annotations.create, asset, shape="rect", x=1.5, y=0.0, w=0.1, h=0.1)
    assert bad.status == 422 and "x" in bad.details["fields"]


def test_partial_coordinates_are_rejected(env):
    """§8.1-29（点検 A1）: 座標は**4 つそろえる**か、**全部無い**か。片方だけは 422。"""
    asset = add_asset(env.store, "a" * 64)
    bad = error_of(env.annotations.create, asset, x=0.1, y=0.2, w=0.3)
    assert bad.status == 422 and "h" in bad.details["fields"]


def test_a_regionless_memo_is_allowed_but_cannot_be_cropped(env):
    """§8.1-29（点検 A1 / G4）: 座標なし＋`body` ありは**画像 1 枚へのメモ**として通る。

    座標も `body` も無いときだけ 422。切り出しは **422**（切る範囲が無い）。
    **P6-2 の監査 上位 2 で変わった所**: 画像全体の書き出し（`annotation_ids` なし）は
    **メモを黙って飛ばす**（422 にしない。メモが 1 件あるだけで導線が止まっていた）。
    名指し（`annotation_ids`）なら **422** で、`details.annotation_id` に**その id**。
    """
    asset = add_asset(env.store, "a" * 64)
    memo = env.annotations.create(asset, body="この 1 枚は没。理由は首の線")
    assert memo["shape"] is None and memo["x"] is None and memo["body"]

    bad = error_of(env.annotations.create, asset)
    assert bad.status == 422 and "body" in bad.details["fields"]

    # 1 枚だけの切り出しは 422（`details` は**その注記の id**。監査 287 行）
    bad = error_of(env.annotations.crop_png, asset, memo["id"])
    assert bad.status == 422 and bad.details["annotation_id"] == memo["id"]

    # 画像全体の書き出し: メモは飛ばす（**422 にしない**）
    doc = env.annotations.export_doc(asset, with_crops=True)
    assert doc["crops"] == [], "メモしか無い画像の書き出しは空配列（監査 上位 2）"

    # 名指しなら 422（黙って飛ばさない）
    bad = error_of(env.annotations.export_doc, asset, annotation_ids=[memo["id"]],
                   with_crops=True)
    assert bad.status == 422 and bad.details["annotation_id"] == memo["id"]


def test_an_annotation_at_the_right_edge_still_crops_at_least_one_pixel(env):
    """監査 上位 1: 右端・下端ぎりぎりの注記でも **500 にしない**（必ず 1 画素以上）。

    `x = 1 - 1e-12, w = 1e-12`（`x + w = 1`）は `floor(round(x*W, 6))` が `W` を返すので、
    以前は `left == right == W` に潰れて**幅 0 の画像**を作り、Pillow が
    `cannot write empty image` で 500 になっていた。**画面で右端・下端までドラッグすると
    この形の注記が作られうる**（`Math.min(1 - x, …)` で `x + w = 1` ちょうどになる）。
    """
    # 直に式でも確かめる（`left` は `W - 1` まで）
    assert crop_box(1 - 1e-12, 1 - 1e-12, 1e-12, 1e-12, 1024, 1024) == (1023, 1023, 1024, 1024)
    assert crop_box(0.5, 0.5, 1e-10, 1e-10, 1024, 1024) == (512, 512, 513, 513)

    asset = add_asset(env.store, "a" * 64, size=(64, 64))
    tight = env.annotations.create(asset, shape="rect", x=1 - 1e-12, y=1 - 1e-12,
                                   w=1e-12, h=1e-12)
    png = env.annotations.crop_png(asset, tight["id"])       # 以前はここで 500
    with Image.open(BytesIO(png)) as image:
        assert (image.width, image.height) == (1, 1), "1 画素以上になっていない（監査 上位 1）"

    doc = env.annotations.export_doc(asset, with_crops=True)  # 以前はここも 500
    assert [(c["width"], c["height"]) for c in doc["crops"]] == [(1, 1)]


def test_a_memo_does_not_stop_the_crops_of_the_rectangles(env):
    """監査 上位 2 / §D の決定 3: **メモが混ざっても、画像全体の書き出しは止まらない**。

    メモ 1 件＋矩形 1 件で、`crops` は**矩形の分だけ**返る（飛ばしたことは件数で分かる）。
    """
    asset = add_asset(env.store, "a" * 64, size=(64, 64))
    env.annotations.create(asset, body="メモ（切れない）")
    rect = env.annotations.create(asset, shape="rect", x=0.25, y=0.25, w=0.5, h=0.5)

    doc = env.annotations.export_doc(asset, with_crops=True)
    assert [c["annotation_id"] for c in doc["crops"]] == [rect["id"]], \
        "メモが混ざると書き出しが止まった（監査 上位 2）"
    assert doc["crops"][0]["width"] == 32 and doc["crops"][0]["height"] == 32
    # 名指しで矩形だけを指定しても通る（以前から）
    only = env.annotations.export_doc(asset, annotation_ids=[rect["id"]], with_crops=True)
    assert [c["annotation_id"] for c in only["crops"]] == [rect["id"]]


# ---- 切り出し（§8.1 の 13・14・15）----


def test_crop_box_rounds_before_floor_and_ceil():
    """§8.1-13 / 14（点検 B1）: **6 桁へ丸めてから** `floor` / `ceil`。1 画素はみ出さない。

    1024² の `{0.25, 0.5, 0.25, 0.25}` → 256×256、2048×1536 で 512×384、
    **1360² の `{x:0, w:0.275}` → 374**（丸めを外すと 375。1024 / 2048 / 1536 では起きない幅）。
    クランプで 1 画素以上。
    """
    assert crop_box(0.25, 0.5, 0.25, 0.25, 1024, 1024) == (256, 512, 512, 768)
    left, top, right, bottom = crop_box(0.25, 0.5, 0.25, 0.25, 2048, 1536)
    assert (right - left, bottom - top) == (512, 384)
    left, top, right, bottom = crop_box(0.0, 0.0, 0.275, 0.1, 1360, 1360)
    assert right - left == 374, "丸めを外すと 375 になる（点検 B1）"
    left, top, right, bottom = crop_box(0.999, 0.999, 0.001, 0.001, 1024, 1024)
    assert right - left >= 1 and bottom - top >= 1, "クランプで 1 画素以上（§8.1-14）"


def test_crop_is_png_with_the_expected_pixels(env):
    """§8.1-15 を壊すと落ちる: 出力は **PNG**（無劣化）で、式どおりの画素数。"""
    asset = add_asset(env.store, "b" * 64, "big.png", size=(1360, 1360))
    note = env.annotations.create(asset, shape="ellipse", x=0.0, y=0.0, w=0.275, h=0.1,
                                  body="ここ")
    png = env.annotations.crop_png(asset, note["id"])
    with Image.open(BytesIO(png)) as image:
        assert image.format == "PNG", "JPEG で書いた（§8.1-15）"
        assert image.size == (374, 136)

    doc = env.annotations.export_doc(asset, with_crops=True)
    assert doc["image"] == {"width": 1360, "height": 1360}
    crop = doc["crops"][0]
    assert (crop["width"], crop["height"]) == (374, 136)
    assert crop["annotation_id"] == note["id"]
    assert Path(env.store.data_dir, *crop["path"].split("/")).exists(), "切り出しが無い"
    with Image.open(Path(env.store.data_dir, *crop["path"].split("/"))) as image:
        assert image.size == (374, 136)


def test_a_failed_replace_does_not_leave_a_tmp_file(env, monkeypatch):
    """§8.1-16 を壊すと落ちる（P5 の C1 の教訓）: 失敗した一時ファイルを残さない。"""
    asset = add_asset(env.store, "c" * 64, "c.png", size=(64, 64))
    env.annotations.create(asset, shape="rect", x=0.0, y=0.0, w=1.0, h=1.0, body="全面")

    def failing(src, dst):
        raise PermissionError("他の道具がファイルを開いている")

    monkeypatch.setattr(os, "replace", failing)
    with pytest.raises(PermissionError):
        env.annotations.export_doc(asset, with_crops=True)
    leftovers = list((env.store.data_dir / "annotations").rglob("*.tmp"))
    assert leftovers == [], f"失敗した一時ファイルが残った（§8.1-16）: {leftovers}"
    # 座標は無事（DB にある。§0.8）
    assert len(env.annotations.list_for_asset(asset)) == 1


def test_stale_tmp_files_are_cleaned_at_startup(env):
    """§0.8: 起動時の掃除（`clean_stale_tmp()`）が残骸を消す。"""
    asset = add_asset(env.store, "d" * 64)
    directory = env.annotations.dir_for(asset)
    directory.mkdir(parents=True, exist_ok=True)
    stale = directory / "x.png.999.888.tmp"
    stale.write_bytes(b"x")
    assert env.annotations.clean_stale_tmp() == 1
    assert not stale.exists()


# ---- 実体が無い（§8.1-19）----


def test_a_missing_file_is_409_not_500(env):
    """§8.1-19 を壊すと落ちる: 実体が無いときは **409 `asset_file_missing`**（422 ではない）。"""
    asset = add_asset(env.store, "e" * 64, "gone.png", make_file=False)
    note = env.annotations.create(asset, shape="rect", x=0.0, y=0.0, w=0.5, h=0.5, body="x")
    bad = error_of(env.annotations.crop_png, asset, note["id"])
    assert bad.status == 409 and bad.code == "asset_file_missing"
    bad = error_of(env.annotations.export_doc, asset, with_crops=True)
    assert bad.status == 409


# ---- 自分の注記だけ（§8.1-28）・削除で切り出しも消える（§8.1-30）----


def test_patch_and_delete_only_touch_your_own_annotations(env):
    """§8.1-28 を壊すと落ちる（点検 C7）: `agent` は `human` の印を消せない・変えられない。"""
    asset = add_asset(env.store, "f" * 64)
    human = env.annotations.create(asset, shape="rect", x=0.1, y=0.1, w=0.2, h=0.2,
                                   body="人の印", actor="human")
    agent = env.annotations.create(asset, shape="rect", x=0.4, y=0.4, w=0.2, h=0.2,
                                   body="エージェントの印", actor="agent")

    bad = error_of(env.annotations.delete, human["id"], actor="agent")
    assert bad.status == 403 and bad.details["annotation_actor"] == "human"
    bad = error_of(env.annotations.patch, human["id"], "書き換え", actor="agent")
    assert bad.status == 403

    assert env.annotations.patch(agent["id"], "直した", actor="agent")["body"] == "直した"
    assert env.annotations.delete(agent["id"], actor="agent") == agent["id"]
    # 2 回目は 404（点検 D5）
    assert error_of(env.annotations.delete, agent["id"], actor="agent").status == 404
    # 人の印は残っている
    assert [a["id"] for a in env.annotations.list_for_asset(asset)] == [human["id"]]


def test_deleting_an_annotation_removes_its_crop(env):
    """§8.1-30 を壊すと落ちる（点検 G3）: 消したら切り出しの PNG も消える（キャッシュ）。"""
    asset = add_asset(env.store, "g" * 64, "g.png", size=(64, 64))
    note = env.annotations.create(asset, shape="rect", x=0.0, y=0.0, w=0.5, h=0.5, body="x")
    env.annotations.export_doc(asset, with_crops=True)
    path = env.annotations.crop_path(asset, note["id"])
    assert path.exists()

    env.annotations.delete(note["id"], actor="agent")
    assert not path.exists(), "切り出しが残った（点検 G3）"


# ---- 再送（§0.9）----


def test_the_same_client_token_returns_the_same_row(env):
    """§0.9: 同じ `client_token`・同じ中身は 200 で既存を返す。違う中身は 409。"""
    asset = add_asset(env.store, "h" * 64)
    first = env.annotations.create(asset, shape="rect", x=0.1, y=0.1, w=0.2, h=0.2,
                                   body="x", client_token="tok-1")
    again = env.annotations.create(asset, shape="rect", x=0.1, y=0.1, w=0.2, h=0.2,
                                   body="x", client_token="tok-1")
    assert again["id"] == first["id"] and again.get("replayed") is True
    assert len(env.annotations.list_for_asset(asset)) == 1

    bad = error_of(env.annotations.create, asset, shape="rect", x=0.1, y=0.1, w=0.2, h=0.2,
                   body="違う", client_token="tok-1")
    assert bad.status == 409 and bad.code == "client_token_conflict"


# ---- まとまりとの関係（§3.6）----


def test_a_group_id_must_be_a_group_the_image_belongs_to(env):
    """§3.6: その画像が属さないまとまりを渡したら 422（`details.group_id`）。"""
    asset = add_asset(env.store, "i" * 64)
    bad = error_of(env.annotations.create, asset, shape="rect", x=0.1, y=0.1, w=0.2, h=0.2,
                   body="x", group_id="no-such-group")
    assert bad.status == 422 and "group_id" in bad.details


# ---- HTTP（§8.1 の 17・18・24 と、書き出しの形）----


def test_the_http_endpoints_do_not_write_on_get_and_guard_posts(tmp_path, monkeypatch):
    """§8.1-17 / 18 / 24 を壊すと落ちる。

    - `GET .../export?format=json` は**ファイルを書かない**（一覧が変わらない）
    - `GET .../export?format=crops` は **422** で `POST` を案内する
    - 新しい `POST` は `Host: evil` / `Content-Type: text/plain` で **403**（middleware）
    """
    monkeypatch.setenv("IMAGE_REVIEWER_DATA", str(tmp_path / "data"))
    from fastapi.testclient import TestClient

    from image_reviewer.app import create_app

    app = create_app()
    human = {"X-Image-Reviewer-Actor": "human"}
    with TestClient(app, base_url="http://127.0.0.1") as client:
        asset = add_asset(app.state.store, "j" * 64, "j.png", size=(64, 64))
        made = client.post(f"/api/assets/{asset}/annotations",
                           json={"shape": "rect", "x": 0.0, "y": 0.0, "w": 0.5, "h": 0.5,
                                 "body": "x"}, headers=human)
        assert made.status_code == 201, made.text
        note_id = made.json()["annotation"]["id"]

        before = snapshot(tmp_path / "data")
        got = client.get(f"/api/assets/{asset}/annotations/export", params={"format": "json"})
        assert got.status_code == 200
        assert got.json()["crops"] is None
        assert snapshot(tmp_path / "data") == before, "GET がファイルを書いた（§8.1-17）"
        assert got.json()["image"] == {"width": 64, "height": 64}

        bad = client.get(f"/api/assets/{asset}/annotations/export", params={"format": "crops"})
        assert bad.status_code == 422 and "format" in bad.json()["details"]

        posted = client.post(f"/api/assets/{asset}/annotations/export", json={"format": "crops"},
                             headers=human)
        assert posted.status_code == 200
        assert posted.json()["crops"][0]["annotation_id"] == note_id

        # 1 枚だけその場で作って返す（書かない）
        single = client.get(f"/api/annotations/{note_id}/crop")
        assert single.status_code == 200 and single.headers["content-type"] == "image/png"

        # 守り（載せ忘れると素通りする。§8.1-24）
        for path, body in ((f"/api/assets/{asset}/annotations", {}),
                           (f"/api/assets/{asset}/annotations/export", {"format": "crops"})):
            evil = client.post(path, json=body, headers={"Host": "evil.example"})
            assert evil.status_code == 403, f"{path} が Host で弾かれない"
            plain = client.post(path, json=body, headers={"Content-Type": "text/plain"})
            assert plain.status_code == 403, f"{path} が Content-Type で弾かれない"
        patched = client.patch(f"/api/annotations/{note_id}", json={"body": "y"},
                               headers={"Content-Type": "text/plain"})
        assert patched.status_code == 403
        deleted = client.delete(f"/api/annotations/{note_id}", headers={"Host": "evil.example"})
        assert deleted.status_code == 403


def test_the_export_document_matches_the_contract_shape(tmp_path, monkeypatch):
    """§6.2: 書き出しの文書が契約（`annotation-export`）の形をしている（写し間違いを落とす）。"""
    monkeypatch.setenv("IMAGE_REVIEWER_DATA", str(tmp_path / "data"))
    from fastapi.testclient import TestClient

    from image_reviewer.app import create_app

    app = create_app()
    human = {"X-Image-Reviewer-Actor": "human"}
    with TestClient(app, base_url="http://127.0.0.1") as client:
        asset = add_asset(app.state.store, "k" * 64, "k.png", size=(64, 64))
        client.post(f"/api/assets/{asset}/annotations",
                    json={"shape": "rect", "x": 0.1, "y": 0.2, "w": 0.3, "h": 0.4, "body": "x"},
                    headers=human)
        doc = client.get(f"/api/assets/{asset}/annotations/export").json()
        assert doc["schema"] == "urn:image-reviewer:schema:annotation-export"
        assert doc["abi"] == "0.1"
        assert set(doc) == {"schema", "abi", "generated_at", "asset_id", "image", "annotations",
                            "crops"}
        note = doc["annotations"][0]
        assert set(note) == {"id", "asset_id", "shape", "x", "y", "w", "h", "body", "actor",
                             "created_at", "group_id"}
        assert note["actor"] == "human"
