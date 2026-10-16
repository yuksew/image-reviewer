"""比較の基本（P5-2）のテスト。

設計: docs/p5-design.md §0.1（P5-2）・§0.6（点検 C5）・§0.8（C10・D5）・§6.1、
      docs/comparison.md §3.1（表）・§3.2（正規化。**点検 G5 で重みを外した**）

`tmp_path` は `tests/conftest.py` が用意する。`Store` は必ず閉じる（`tests/.tmp` の後始末）。
"""

from __future__ import annotations

import json
import random
import sqlite3
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from image_reviewer import compare
from image_reviewer.review import ReviewError
from image_reviewer.store import Store

REPO = Path(__file__).resolve().parents[1]
REAL_DB = REPO / ".data" / "db.sqlite3"

# ---- 道具 ----


def make_meta(**kw) -> dict:
    """`png_meta.analyze_graph()` が返す形の来歴（既定は 2 枚で同じになる値）。"""
    meta = {
        "model": "anima-turbo-v1.1.safetensors", "clip": "clip_l.safetensors",
        "vae": "vae.safetensors", "llm": None, "loras": [],
        "sampler": "euler", "scheduler": "normal", "steps": 10, "cfg": 1.0, "denoise": 1.0,
        "seed": "338134650120909", "width": 512, "height": 512,
        "positive_literal": "1girl, solo", "negative_literal": None,
        "final_prompt": "1girl, solo", "final_prompt_source": "png_literal",
        "ja_text": None, "ja_source": None, "textgen_params": None, "has_textgen": False,
        "init_image": None, "node_types": {"KSampler": 1, "SaveImage": 1},
        "unresolved": [], "primary_ksampler": "5",
    }
    meta.update(kw)
    return meta


def add_asset(store: Store, sha: str, name: str = "a.png", *, meta: dict | None = None,
              width: int = 512, height: int = 512) -> str:
    asset_id, _ = store.register(
        sha256=sha, path=str(store.data_dir.parent / "images" / name), size=100, mtime_ns=1,
        width=width, height=height, fmt="png", meta=meta, note=None)
    return asset_id


def row_of(document: dict, key: str) -> dict:
    """`changed` と `same` の両方から 1 行を引く（どちらに入ったかも見たいとき）。"""
    for row in document["diff"]["changed"] + document["diff"]["same"]:
        if row["key"] == key:
            return row
    raise AssertionError(f"差分表に {key} が無い")


def changed_keys(document: dict) -> list[str]:
    return [row["key"] for row in document["diff"]["changed"]]


def same_keys(document: dict) -> list[str]:
    return [row["key"] for row in document["diff"]["same"]]


def status_of(func, *args, **kw) -> int:
    with pytest.raises(ReviewError) as got:
        func(*args, **kw)
    return got.value.status


@pytest.fixture
def env(tmp_path):
    store = Store(tmp_path / "data")
    try:
        yield SimpleNamespace(store=store, tmp_path=tmp_path)
    finally:
        store.close()


@pytest.fixture
def app_client(tmp_path, monkeypatch):
    """`TestClient` つきの app。**`Store` を閉じる**（`tests/.tmp` の後始末のため）。"""
    monkeypatch.setenv("IMAGE_REVIEWER_DATA", str(tmp_path / "data"))
    from fastapi.testclient import TestClient

    from image_reviewer.app import create_app

    app = create_app()
    try:
        with TestClient(app, base_url="http://127.0.0.1") as client:
            yield client, app
    finally:
        app.state.store.close()


# ---- 1. seed だけが違う 2 枚 ----


def test_two_images_differing_only_by_seed(env):
    a = add_asset(env.store, "a" * 64, meta=make_meta())
    b = add_asset(env.store, "b" * 64, "b.png", meta=make_meta(seed="998211003"))

    document = compare.compare_assets(env.store, [a, b])

    assert changed_keys(document) == ["seed"], f"違う行が seed だけになっていない: {changed_keys(document)}"
    assert row_of(document, "seed")["values"] == ["338134650120909", "998211003"]
    assert row_of(document, "seed")["cells"] == ["same", "changed"]
    # 既定は入力順の先頭が基準（§6.1）
    assert document["base"] == a
    # 同じ行には他の鍵が畳まれている
    for key in ("model", "loras", "clip", "llm", "vae", "sampler", "scheduler", "steps",
                "cfg", "denoise", "width", "height", "final_prompt", "negative_literal",
                "init_image", "node_types", "textgen_params", "final_prompt_source"):
        assert key in same_keys(document), f"{key} が同じ行に入っていない"


# ---- 2. 正規化（段 1）と重み（段 2。点検 G5）----


def test_normalization_makes_case_underscore_and_trailing_comma_the_same(env):
    """段 1: 大小文字・`_` と空白・末尾のカンマ・空白は「同じ」。"""
    a = add_asset(env.store, "a" * 64, meta=make_meta(final_prompt="1girl, long_hair, solo,"))
    b = add_asset(env.store, "b" * 64, "b.png",
                  meta=make_meta(final_prompt="  1GIRL,  long hair ,  SOLO  "))

    document = compare.compare_assets(env.store, [a, b])

    assert row_of(document, "final_prompt")["state"] == "same"
    assert "final_prompt" in same_keys(document)
    assert document["diff"]["prompt_diff"]["normalized_equal"] is True


def test_a_weight_difference_is_reweighted_not_same(env):
    """点検 G5: `(word:1.2)` と `word` は「同じ」ではない。**重み変更**として出す。

    正規化から「重みの表記を同一視する」を外したので、ここは `same` にならない。
    """
    a = add_asset(env.store, "a" * 64, meta=make_meta(final_prompt="1girl, (solo:1.2)"))
    b = add_asset(env.store, "b" * 64, "b.png", meta=make_meta(final_prompt="1girl, solo"))

    document = compare.compare_assets(env.store, [a, b])

    row = row_of(document, "final_prompt")
    assert row["state"] == "reweighted", f"重みの違いが {row['state']} になっている"
    assert "final_prompt" in changed_keys(document)
    assert row["cells"] == ["same", "reweighted"]
    detail = document["diff"]["prompt_diff"]
    assert detail["reweighted"] is True and detail["normalized_equal"] is False
    words = detail["per_asset"][b]
    assert words[1]["t"] == "solo" and words[1]["w"] == "1.0" and words[1]["base_w"] == "1.2"


def test_an_emphasis_depth_difference_is_reweighted(env):
    """`((word))` の段数も重み（`comparison.md` §3.2。G5 で「同じ」から外れた）。"""
    a = add_asset(env.store, "a" * 64, meta=make_meta(final_prompt="((solo))"))
    b = add_asset(env.store, "b" * 64, "b.png", meta=make_meta(final_prompt="solo"))
    document = compare.compare_assets(env.store, [a, b])
    assert row_of(document, "final_prompt")["state"] == "reweighted"


# ---- 3. 語順（点検 C10）----


def test_a_word_order_difference_is_moved_not_added_and_removed(env):
    """点検 C10: 順番だけの違いは `moved`。追加＋削除に割らない。"""
    a = add_asset(env.store, "a" * 64, meta=make_meta(final_prompt="1girl, solo, chibi"))
    b = add_asset(env.store, "b" * 64, "b.png", meta=make_meta(final_prompt="chibi, 1girl, solo"))

    document = compare.compare_assets(env.store, [a, b])

    detail = document["diff"]["prompt_diff"]
    assert detail["base"] == a
    states = [entry["state"] for entry in detail["per_asset"][b]]
    assert states == ["moved", "same", "same"], states
    assert "added" not in states and "removed" not in states, "移動が追加＋削除に割れている"
    assert detail["words_equal"] is False and detail["normalized_equal"] is False
    # union の見方でも「移動」として出る（§6.1 の tokens）
    tokens = {entry["t"]: entry["state"] for entry in detail["tokens"]}
    assert tokens["chibi"] == "moved" and tokens["1girl"] == "same"


def test_an_added_word_is_added_and_a_removed_word_is_removed(env):
    a = add_asset(env.store, "a" * 64, meta=make_meta(final_prompt="1girl, solo"))
    b = add_asset(env.store, "b" * 64, "b.png", meta=make_meta(final_prompt="1girl, solo, chibi"))

    document = compare.compare_assets(env.store, [a, b])

    detail = document["diff"]["prompt_diff"]
    assert [entry["state"] for entry in detail["per_asset"][b]] == ["same", "same", "added"]
    assert {entry["t"]: entry["state"] for entry in detail["tokens"]}["chibi"] == "added"


# ---- 4. 基準（点検 C10）と並び（§6.1）----


def test_prompt_diff_base_follows_the_query_and_defaults_to_the_first_id(env):
    a = add_asset(env.store, "a" * 64, meta=make_meta(final_prompt="1girl, solo"))
    b = add_asset(env.store, "b" * 64, "b.png", meta=make_meta(final_prompt="1girl, chibi"))

    first = compare.compare_assets(env.store, [a, b])
    assert first["base"] == a
    assert first["diff"]["prompt_diff"]["base"] == a
    assert first["diff"]["ja_diff"]["base"] == a
    # 基準の列は全部 same、他の列は**その列の語**を基準から見た状態で並べる
    assert [entry["state"] for entry in first["diff"]["prompt_diff"]["per_asset"][a]] == ["same", "same"]
    assert [entry["t"] for entry in first["diff"]["prompt_diff"]["per_asset"][b]] == ["1girl", "chibi"]
    assert [entry["state"] for entry in first["diff"]["prompt_diff"]["per_asset"][b]] == ["same", "added"]

    second = compare.compare_assets(env.store, [a, b], base=b)
    assert second["base"] == b
    assert second["diff"]["prompt_diff"]["base"] == b
    assert second["diff"]["ja_diff"]["base"] == b
    assert [entry["state"] for entry in second["diff"]["prompt_diff"]["per_asset"][b]] == ["same", "same"]
    assert [entry["t"] for entry in second["diff"]["prompt_diff"]["per_asset"][a]] == ["1girl", "solo"]
    assert [entry["state"] for entry in second["diff"]["prompt_diff"]["per_asset"][a]] == ["same", "added"]
    # どの列が違うかも基準に従う
    assert row_of(second, "final_prompt")["cells"] == ["changed", "same"]


def test_the_base_must_be_one_of_the_ids(env):
    a = add_asset(env.store, "a" * 64, meta=make_meta())
    b = add_asset(env.store, "b" * 64, "b.png", meta=make_meta())
    assert status_of(compare.compare_assets, env.store, [a, b], base="nope") == 422


def test_changed_rows_come_first_and_same_rows_are_collapsed(env):
    a = add_asset(env.store, "a" * 64, meta=make_meta(steps=10))
    b = add_asset(env.store, "b" * 64, "b.png", meta=make_meta(steps=20))

    document = compare.compare_assets(env.store, [a, b])

    assert changed_keys(document) == ["steps"]
    assert "steps" not in same_keys(document)
    # 鍵の並びは `COMPARE_KEYS` の順で、`changed` のほうが先に返る
    keys = document["diff"]["keys"]
    assert keys.index("steps") < keys.index("cfg")
    assert row_of(document, "steps")["values"] == ["10", "20"]
    assert row_of(document, "steps")["kind"] == "num"


# ---- 5. 点検 C5 の鍵 ----


def test_the_c5_keys_are_diffed(env):
    """点検 C5: `negative_literal` / `init_image` / `textgen_params` / `node_types` /
    `final_prompt_source` を差分の鍵に足す。少なくとも 2 つは実際に差が出る形で見る。"""
    a = add_asset(env.store, "a" * 64, meta=make_meta(
        negative_literal="lowres, bad hands", init_image="ref.png",
        textgen_params={"max_length": 512, "seed": 1, "temperature": 0.7},
        node_types={"KSampler": 1, "TextGenerate": 1, "SaveImage": 1},
        final_prompt_source="reconstructed"))
    b = add_asset(env.store, "b" * 64, "b.png", meta=make_meta(
        negative_literal="lowres", init_image=None,
        textgen_params={"max_length": 256, "seed": 2, "temperature": 0.7},
        node_types={"KSampler": 1, "SaveImage": 1},
        final_prompt_source="png_literal"))

    document = compare.compare_assets(env.store, [a, b])

    for key in ("negative_literal", "init_image", "textgen_params", "node_types",
                "final_prompt_source"):
        assert key in document["diff"]["keys"], f"{key} が鍵の一覧に無い（点検 C5）"
        assert key in changed_keys(document), f"{key} が違う行に入っていない"

    # 実際に差が出ているもの（4 つが `changed`、値の無い側は `only_in_some`）
    assert row_of(document, "negative_literal")["state"] == "changed"
    assert row_of(document, "negative_literal")["values"] == ["lowres, bad hands", "lowres"]
    assert row_of(document, "init_image")["state"] == "only_in_some"
    assert row_of(document, "init_image")["values"] == ["ref.png", None]
    # `textgen_params` は 1 本の正規化した行にする
    assert row_of(document, "textgen_params")["values"] == [
        "max_length=512, seed=1, temperature=0.7", "max_length=256, seed=2, temperature=0.7"]
    # `node_types` は集合の差で見る（共通部分に無い型だけを出す）
    nodes = row_of(document, "node_types")
    assert nodes["state"] == "changed"
    assert nodes["only_in"][a] == ["TextGenerate"] and nodes["only_in"][b] == []
    # `final_prompt_source` も同じ
    assert row_of(document, "final_prompt_source")["values"] == ["reconstructed", "png_literal"]


def test_clip_skip_is_not_a_key(env):
    """設計 §0.6: `clip_skip` は `png_meta.py` が読んでいないので鍵に入れない。"""
    assert "clip_skip" not in compare.KEY_BY_NAME


def test_the_g4_keys_are_diffed(env):
    """監査 G4（実行込みのやり直し）: `textgen_system_prompt` と `en_source` を鍵に足す。

    この 2 つは**訳し直しの条件そのもの**（指示文と、英訳の出所）。表に出さないと
    「なぜ訳が変わったか」を追えない。`analyze_graph()` が既に返している値なので
    「発明」にはならない（前回の G4 の推奨どおり）。
    """
    a = add_asset(env.store, "a" * 64, meta=make_meta(
        textgen_system_prompt="Translate to English.", en_source="comfyui_history"))
    b = add_asset(env.store, "b" * 64, "b.png", meta=make_meta(
        textgen_system_prompt="Translate briefly.", en_source=None))

    document = compare.compare_assets(env.store, [a, b])

    for key in ("textgen_system_prompt", "en_source"):
        assert key in document["diff"]["keys"], f"{key} が鍵の一覧に無い（監査 G4）"
        assert key in changed_keys(document), f"{key} が違う行に入っていない（監査 G4）"
    assert row_of(document, "textgen_system_prompt")["values"] == [
        "Translate to English.", "Translate briefly."]
    assert row_of(document, "en_source")["state"] == "only_in_some"
    assert row_of(document, "en_source")["values"] == ["comfyui_history", None]


# ---- 6. 画素数は実体から（点検 C5。img2img では EmptyLatentImage が無い）----


def test_size_comes_from_the_asset_even_without_empty_latent_image(env):
    """点検 C5: `analyze_graph()` の `width` / `height` は `EmptyLatentImage` から取るので
    img2img では `null`。差分は**実体の画素数**（`asset.width` / `asset.height`）で見る。"""
    a = add_asset(env.store, "a" * 64, width=768, height=1024,
                  meta=make_meta(width=None, height=None, init_image="ref.png"))
    b = add_asset(env.store, "b" * 64, "b.png", width=512, height=512,
                  meta=make_meta(width=None, height=None))

    document = compare.compare_assets(env.store, [a, b])

    assert row_of(document, "width")["values"] == ["768", "512"]
    assert row_of(document, "height")["values"] == ["1024", "512"]
    assert row_of(document, "width")["state"] == "changed"
    assert document["items"][0]["provenance"]["width"] == 768

    # 来歴の画素数と実体が食い違うときは**実体**が正（C5）
    c = add_asset(env.store, "c" * 64, "c.png", width=768, height=1024,
                  meta=make_meta(width=1024, height=1024))
    other = compare.compare_assets(env.store, [c, b])
    assert row_of(other, "width")["values"] == ["768", "512"]


# ---- 7. タグは null、pHash は計算しない（点検 D5。P5-3 の範囲を混ぜない）----


def test_tags_is_null_and_phash_comes_from_the_asset(env):
    """点検 D5: `tags` は `null`（「未計算」と「無い」を区別する。P4 で埋まる）。

    P5-3: `phash` / `dhash` は `asset` の列を**そのまま写す**（計算はサムネイルを作る
    復号と同じ 1 回。`tests/test_p5_3.py` が見る）。この 2 枚は**実体のファイルが無い**
    （`add_asset` はパスを作るだけ）ので `null` のまま。
    **監査 B1** 以降、実体がある枚は `compare_assets()` が文書を組む前に埋める
    （`tests/test_p5_3.py` の `test_the_first_compare_document_fills_...`）。
    """
    a = add_asset(env.store, "a" * 64, meta=make_meta())
    b = add_asset(env.store, "b" * 64, "b.png", meta=make_meta())

    document = compare.compare_assets(env.store, [a, b])

    for item in document["items"]:
        assert item["tags"] is None, "「未計算」と「無い」を区別する（点検 D5）"
        assert item["phash"] is None and item["dhash"] is None, "未計算の枚は null"
        assert item["thumb"].endswith("/thumb?size=1024")
        assert item["thumb_small"].endswith("/thumb?size=256")


def test_an_image_without_provenance_is_only_in_some(env):
    """来歴が無い枚（`meta` が null）を混ぜると、鍵は `only_in_some` になる。"""
    a = add_asset(env.store, "a" * 64, meta=make_meta())
    b = add_asset(env.store, "b" * 64, "b.png", meta=None)

    document = compare.compare_assets(env.store, [a, b])

    assert row_of(document, "model")["state"] == "only_in_some"
    assert row_of(document, "model")["values"] == ["anima-turbo-v1.1.safetensors", None]
    assert row_of(document, "model")["cells"] == ["same", "missing"]


# ---- 8. 日本語原文（文単位 → 文字単位。`comparison.md` §3.2）----


def test_ja_diff_is_sentence_level_then_character_level(env):
    a = add_asset(env.store, "a" * 64, meta=make_meta(ja_text="1girl。空の背景。"))
    b = add_asset(env.store, "b" * 64, "b.png", meta=make_meta(ja_text="1girl。海の背景。"))

    document = compare.compare_assets(env.store, [a, b])

    ja = document["diff"]["ja_diff"]
    assert ja["base"] == a and ja["normalized_equal"] is False
    sentences = ja["per_asset"][b]["sentences"]
    assert [s["state"] for s in sentences] == ["same", "added"]
    chars = ja["per_asset"][b]["chars"]
    assert "".join(c["t"] for c in chars if c["state"] == "added") == "海"
    assert "".join(c["t"] for c in chars if c["state"] == "removed") == "空"
    # 表の行も違う行に入る
    assert row_of(document, "ja_text")["state"] == "changed"


# ---- 9. 入力の検査 ----


def test_fewer_than_two_ids_and_duplicates_are_422(env):
    a = add_asset(env.store, "a" * 64, meta=make_meta())
    assert status_of(compare.compare_assets, env.store, []) == 422
    assert status_of(compare.compare_assets, env.store, [a]) == 422
    assert status_of(compare.compare_assets, env.store, [a, a]) == 422
    with pytest.raises(ReviewError) as got:
        compare.compare_assets(env.store, [a, a])
    assert got.value.details["duplicate"] == [a]


def test_an_unknown_id_is_404(env):
    a = add_asset(env.store, "a" * 64, meta=make_meta())
    assert status_of(compare.compare_assets, env.store, [a, "nope"]) == 404
    with pytest.raises(ReviewError) as got:
        compare.compare_assets(env.store, ["nope", a])
    assert got.value.details["asset_id"] == "nope"


def test_more_than_eight_ids_is_422_with_a_reason(env):
    """8 枚は**比較の画面の上限**（まとまりの上限ではない。点検 B6/G8）。理由を付けて断る。"""
    assert compare.MAX_COMPARE_IDS == 8
    with pytest.raises(ReviewError) as got:
        compare.check_ids([f"{i:026d}" for i in range(9)])
    assert got.value.status == 422
    assert "8 枚" in got.value.detail
    assert got.value.details["max"] == 8 and got.value.details["got"] == 9
    assert compare.check_ids([f"{i:026d}" for i in range(8)])     # 8 枚は通る


def test_parse_ids_param_tolerates_a_trailing_comma(env):
    assert compare.parse_ids_param("a,b,c") == ["a", "b", "c"]
    assert compare.parse_ids_param("a,b,") == ["a", "b"]
    assert compare.parse_ids_param(" a , b ") == ["a", "b"]
    assert compare.parse_ids_param(None) == []
    assert status_of(compare.parse_ids_param, "a,,b") == 422


# ---- 10. API（まとまり無しでも引ける。点検 C9）----


def test_compare_without_a_group(app_client):
    client, app = app_client
    a = add_asset(app.state.store, "a" * 64, meta=make_meta())
    b = add_asset(app.state.store, "b" * 64, "b.png", meta=make_meta(seed="42"))

    got = client.get("/api/compare", params={"ids": f"{a},{b}"})

    assert got.status_code == 200, got.text
    document = got.json()
    assert "group" not in document, "まとまりが無い比較に group を足している"
    assert document["ids"] == [a, b] and document["base"] == a
    assert [row["key"] for row in document["diff"]["changed"]] == ["seed"]


def test_group_compare_adds_the_group(app_client):
    client, app = app_client
    a = add_asset(app.state.store, "a" * 64, meta=make_meta())
    b = add_asset(app.state.store, "b" * 64, "b.png", meta=make_meta(seed="42"))
    created = client.post("/api/groups", json={"title": "候補", "kind": "manual",
                                              "asset_ids": [a, b], "policy": "pick_one"})
    group_id = created.json()["id"]

    got = client.get(f"/api/groups/{group_id}/compare")

    assert got.status_code == 200, got.text
    document = got.json()
    assert document["group"]["id"] == group_id
    assert document["group"]["policy"] == "pick_one" and document["group"]["state"] == "open"
    assert document["group"]["item_count"] == 2
    assert document["ids"] == [a, b]
    assert [row["key"] for row in document["diff"]["changed"]] == ["seed"]
    # 基準は `?base=` で選べる
    other = client.get(f"/api/groups/{group_id}/compare", params={"base": b})
    assert other.json()["base"] == b
    # まとまりの外の id は断る
    assert client.get(f"/api/groups/{group_id}/compare",
                      params={"ids": f"{a},nope"}).status_code == 422
    assert client.get("/api/groups/nope/compare").status_code == 404


def test_the_api_returns_404_and_422(app_client):
    client, app = app_client
    a = add_asset(app.state.store, "a" * 64, meta=make_meta())
    assert client.get("/api/compare", params={"ids": a}).status_code == 422
    assert client.get("/api/compare", params={"ids": f"{a},{a}"}).status_code == 422
    assert client.get("/api/compare", params={"ids": f"{a},nope"}).status_code == 404
    assert client.get("/api/compare").status_code == 422
    assert client.get("/api/compare", params={"ids": f"{a},{a}", "base": "x"}).status_code == 422


def test_the_compare_endpoints_are_guarded(app_client):
    """守りは `app.py` の middleware がアプリ全体に掛けるので、新しい口にも効く（点検 C15）。"""
    client, app = app_client
    a = add_asset(app.state.store, "a" * 64, meta=make_meta())
    b = add_asset(app.state.store, "b" * 64, "b.png", meta=make_meta(seed="42"))
    group_id = client.post("/api/groups", json={"asset_ids": [a, b]}).json()["id"]
    for path in ("/api/compare", f"/api/groups/{group_id}/compare"):
        got = client.get(path, params={"ids": f"{a},{b}"}, headers={"host": "evil.example"})
        assert got.status_code == 403, path
        # POST は経路が無いが、middleware が先に弾く（Origin と Content-Type をここで見る）
        assert client.post(path, json={}, headers={"origin": "http://evil.example"}
                           ).status_code == 403, path
        assert client.post(path, content=b"{}",
                           headers={"content-type": "text/plain"}).status_code == 403, path
    # 正しい要求は通る（守りが強すぎない）
    assert client.get("/api/compare", params={"ids": f"{a},{b}"}).status_code == 200
    assert client.get(f"/api/groups/{group_id}/compare").status_code == 200


# ---- 11. 実データでの点検（読み取りだけ。任意だが価値がある）----


def test_real_assets_show_the_captured_translation_as_a_difference():
    """263 枚の実データ（`.data/db.sqlite3`）を**読み取り専用**で開き、英訳を持つ 1 枚を
    英訳を持たない 1 枚と比べる。`en_text` の行が「違う行」に出ることを確かめる。

    この DB は消してはいけないので、`sqlite3` を `mode=ro` で開く（`Store` は使わない）。
    """
    if not REAL_DB.exists():
        pytest.skip(f"実データが無い: {REAL_DB}")
    con = sqlite3.connect(f"file:{REAL_DB.as_posix()}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    try:
        rows = con.execute("SELECT asset_id, meta_json FROM asset_meta").fetchall()
        translated = other = None
        for got in rows:
            try:
                meta = json.loads(got["meta_json"])
            except ValueError:
                continue
            if not isinstance(meta, dict) or not meta:
                continue
            if meta.get("en_text") and translated is None:
                translated = (got["asset_id"], meta)
            elif not meta.get("en_text") and other is None:
                other = (got["asset_id"], meta)
        if translated is None or other is None:
            pytest.skip("英訳を持つ枚と持たない枚の組が実データに無い")

        def item(pair) -> dict:
            asset_id, meta = pair
            size = con.execute("SELECT width, height, review_state FROM asset WHERE id = ?",
                               (asset_id,)).fetchone()
            return compare.asset_item({"id": asset_id, "meta": meta,
                                       "width": size["width"], "height": size["height"],
                                       "review_state": size["review_state"]})

        document = compare.build_document([item(translated), item(other)])
    finally:
        con.close()

    assert "en_text" in changed_keys(document), "英訳の行が違う行に出ていない"
    assert row_of(document, "en_text")["state"] in ("changed", "only_in_some")
    assert document["items"][0]["prompts"]["en_text"] == translated[1]["en_text"]
    assert document["items"][1]["prompts"]["en_text"] is None
    # 実データでも差分表が作れる（例外を投げない）
    assert document["diff"]["keys"][:3] == ["model", "loras", "clip"]


def real_assets(path: Path, limit: int | None = None) -> list[tuple[dict, dict]]:
    """実データ（`.data/db.sqlite3`）を**読み取り専用**で読み、(asset, meta) を返す。

    `Store` は使わない（書き込みの錠も取らない）。DB は消してはいけない。
    """
    con = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    try:
        sql = ("SELECT a.id, a.width, a.height, a.review_state, m.meta_json FROM asset a"
               " LEFT JOIN asset_meta m ON m.asset_id = a.id ORDER BY a.id")
        if limit:
            sql += f" LIMIT {int(limit)}"
        out = []
        for r in con.execute(sql).fetchall():
            try:
                meta = json.loads(r["meta_json"]) if r["meta_json"] else None
            except ValueError:
                meta = None
            out.append(({"id": r["id"], "meta": meta if isinstance(meta, dict) else None,
                         "width": r["width"], "height": r["height"],
                         "review_state": r["review_state"]}, meta))
        return out
    finally:
        con.close()


def test_real_assets_do_not_report_a_missing_final_prompt_as_same():
    """監査 B2: 263 枚の実データを**読み取り専用**（`mode=ro`）で読み、
    `final_prompt` の行が「分からない」を「同じ」と言わないことを確かめる。

    実データで確かめること:
    1. 最終プロンプトを持たない枚（来歴なし 80 枚＋来歴はあるが正側の文字が無い 3 枚）が
       ある。その 2 枚を比べると、以前は `same`、いまは `unknown`（**同じではない**）。
    2. 捕獲できた 1 枚と持たない枚を比べると `incomplete`（捕獲した側の訳文が「追加」に
       ならない）。
    3. `ja_text` が違う組では `final_prompt` の行が `same` に潰れていない。
    4. 捕獲できた値は捨てない（`final_prompt` に訳文が入っている）。
    """
    if not REAL_DB.exists():
        pytest.skip(f"実データが無い: {REAL_DB}")
    rows = real_assets(REAL_DB)
    assert len(rows) >= 263, f"実データの枚数が変わった: {len(rows)}"
    items = [compare.asset_item(asset) for asset, _ in rows]
    unknown = [item for item in items if item["prompts"]["final_prompt_unknown"]]
    assert unknown, "最終プロンプトが分からない枚が実データに無い（前提が変わった）"

    def state_of(pair: list[dict]) -> dict:
        document = compare.build_document(pair)
        return row_of(document, "final_prompt")

    # 1. 分からない 2 枚は `same` ではない
    two = state_of(unknown[:2])
    assert two["state"] == "unknown", two["state"]
    assert two["unknown"] == [unknown[0]["asset_id"], unknown[1]["asset_id"]]
    assert two["values"] == [None, None]

    # 4. 捕獲できた枚の値は捨てない（実データで英訳を持つのは 1 枚）
    captured = [item for item in items if item["prompts"]["en_text"]]
    assert captured, "実データで英訳を持つ枚が無い（前提が変わった）"
    got = captured[0]["prompts"]["final_prompt"]
    assert got and captured[0]["prompts"]["en_text"][:10] in got

    # 2. 捕獲できた 1 枚 vs 分からない 1 枚は `incomplete`
    one = state_of([captured[0], unknown[0]])
    assert one["state"] == "incomplete", one["state"]
    assert one["unknown"] == [unknown[0]["asset_id"]]
    assert one["values"] == [got, None]

    # 3. `ja_text` が違う組（実データでは捕獲した 1 枚 vs それ以外）で `same` に潰れていない
    pairs = 0
    for item in items:
        if item["prompts"]["ja_text"] == captured[0]["prompts"]["ja_text"]:
            continue
        row = state_of([captured[0], item])
        assert row["state"] != "same", f"ja_text が違うのに same: {item['asset_id']}"
        pairs += 1
        if pairs >= 40:
            break
    assert pairs >= 1, "ja_text が違う組を 1 つも見ていない"


# ---- 12. 性能（設計 §8 の 30ms。監査 B1）----


def shuffled_and_appended(env, words: int) -> tuple[list[str], list[str]]:
    """8 枚ぶんの資産を作る（語を並べ替えた組と、1 語ずつ足した組）。"""
    base = [f"tag{k}" for k in range(words)]
    shuffled, appended = [], []
    for i in range(compare.MAX_COMPARE_IDS):
        w = list(base)
        random.Random(i).shuffle(w)
        sha = f"{words:04d}{i}".ljust(64, "0")
        shuffled.append(add_asset(env.store, sha, f"s{words}-{i}.png",
                                  meta=make_meta(seed=str(i), final_prompt=", ".join(w))))
        appended.append(add_asset(env.store, sha[::-1], f"a{words}-{i}.png",
                                  meta=make_meta(seed=str(i),
                                                 final_prompt=", ".join(base + [f"extra{i}"]))))
    return shuffled, appended


def test_the_word_union_does_not_rerun_the_lcs_per_word(env, monkeypatch):
    """監査 B1: 語の union は `diff_sequence`（LCS）を**画像ごとに 1 回**しか呼ばない。

    以前は `_union_tokens` が基準の語ごとに全画像ぶん呼び直していたので、呼び出し回数は
    「語数 × 画像数」に比例した（60 語 × 8 枚で 400 回以上）。ここは**語数に依らない**ことを
    固定する（時間より壊れにくい）。
    """
    real = compare.diff_sequence
    calls: list[tuple[int, int]] = []

    def counting(base_keys, item_keys):
        calls.append((len(base_keys), len(item_keys)))
        return real(base_keys, item_keys)

    monkeypatch.setattr(compare, "diff_sequence", counting)
    counts = {}
    for words in (6, 60, 200):
        ids = shuffled_and_appended(env, words)[1]        # 「1 語ずつ追加」の 8 枚
        calls.clear()
        document = compare.compare_assets(env.store, ids)
        counts[words] = len(calls)
        assert row_of(document, "final_prompt")["state"] == "changed"
    # 基準以外の 7 枚ぶんだけ（画像数にだけ比例する）
    assert counts == {6: compare.MAX_COMPARE_IDS - 1, 60: compare.MAX_COMPARE_IDS - 1,
                      200: compare.MAX_COMPARE_IDS - 1}, counts


def test_a_long_prompt_over_eight_images_stays_inside_the_budget(env):
    """設計 §8: 差分表（8 枚）は 30ms 以内。ここは**緩い**壁時計の見張り（壊れにくさを優先）。

    監査 B1 の修正前は 200 語で 275ms 前後（この機械）だった。呼び出し回数は上のテストが
    守るので、ここは桁が戻ったら落ちる程度の上限にする。
    """
    ids = shuffled_and_appended(env, 200)[0]
    started = time.perf_counter()
    compare.compare_assets(env.store, ids)
    spent_ms = (time.perf_counter() - started) * 1000
    assert spent_ms < 500, f"8 枚 × 200 語で {spent_ms:.1f}ms（30ms の目標から遠い）"

    ids60 = shuffled_and_appended(env, 60)[1]
    started = time.perf_counter()
    compare.compare_assets(env.store, ids60)
    spent60 = (time.perf_counter() - started) * 1000
    assert spent60 < 100, f"8 枚 × 60 語で {spent60:.1f}ms"


def test_a_very_long_prompt_skips_the_word_diff(env):
    """監査 B1 の提案: 1 画像 2,000 語を超えたら語の差分を省く（行の生の文字列は残る）。"""
    words = compare.MAX_PROMPT_WORDS + 1
    ids = shuffled_and_appended(env, words)[1]
    document = compare.compare_assets(env.store, ids)
    detail = document["diff"]["prompt_diff"]
    assert detail["too_long"] is True
    assert detail["tokens"] == [] and detail["normalized_equal"] is False
    assert row_of(document, "final_prompt")["state"] == "changed"


# ---- 13. 分からない最終プロンプト（監査 B2）----


def uncaptured(**kw) -> dict:
    """英訳を捕獲していない再構成（`analyze_graph` が返す形）の来歴。

    `final_prompt=None` / `final_prompt_source="reconstructed"` / `concat_prefix=...`。
    """
    meta = make_meta(final_prompt=None, final_prompt_source="reconstructed",
                     concat_prefix="(masterpiece, best quality), safe,",
                     has_textgen=True, textgen_params={"max_length": 512})
    meta.update(kw)
    return meta


def test_two_uncaptured_prompts_with_different_japanese_are_not_same(env):
    """監査 B2: 訳が未捕獲の 2 枚は、日本語原文が違っても `final_prompt` が「同じ」にならない。

    以前は前置語だけが値になり、日本語が違っても `same` と出ていた（実データでは英訳を持つ
    枚が 263 枚中 1 枚なので、ほぼ全部の組がこれに当たる）。
    """
    a = add_asset(env.store, "a" * 64, meta=uncaptured(ja_text="1girl。空の背景。"))
    b = add_asset(env.store, "b" * 64, "b.png", meta=uncaptured(ja_text="1girl。海の背景。"))

    document = compare.compare_assets(env.store, [a, b])

    row = row_of(document, "final_prompt")
    assert row["state"] == "unknown", f"分からないのに {row['state']} と言っている"
    assert row["state"] != "same"
    assert row["values"] == [None, None], "前置語を最終プロンプトの値にしている"
    assert row["cells"] == ["unknown", "unknown"]
    assert row["unknown"] == [a, b], "どの画像が分からないかを言っていない"
    assert row["known_prefix"] == {a: "(masterpiece, best quality), safe,",
                                   b: "(masterpiece, best quality), safe,"}
    # 分からない行も既定で見える（`changed` 側に返る）
    assert "final_prompt" in changed_keys(document)
    # 日本語原文の違いは別の行で見える
    assert row_of(document, "ja_text")["state"] == "changed"


def test_a_captured_prompt_still_diffs_when_every_image_has_one(env):
    """監査 B2: 全部の枚に値があるときは、これまでどおり比較する（`unknown` にしない）。"""
    a = add_asset(env.store, "a" * 64, meta=make_meta(final_prompt="1girl, solo"))
    b = add_asset(env.store, "b" * 64, "b.png", meta=make_meta(final_prompt="1girl, chibi"))

    document = compare.compare_assets(env.store, [a, b])

    row = row_of(document, "final_prompt")
    assert row["state"] == "changed"
    assert row["values"] == ["1girl, solo", "1girl, chibi"]
    assert row["cells"] == ["same", "changed"]
    assert "unknown" not in row
    detail = document["diff"]["prompt_diff"]
    assert [entry["state"] for entry in detail["per_asset"][b]] == ["same", "added"]
    assert "unknown" not in detail


def test_one_captured_and_one_uncaptured_is_incomplete_not_added(env):
    """監査 B2: 捕獲した 1 枚と捕獲していない 1 枚は `incomplete`。

    以前は捕獲した側の訳文がまるごと「追加」と出た（`per_asset` が `added` だらけ）。
    分からない枚を「持っていない」と数えないので、union に `added` は出ない。
    """
    captured = "(masterpiece, best quality), safe,\n\n1girl. solo. chibi."
    a = add_asset(env.store, "a" * 64,
                  meta=uncaptured(final_prompt=captured, en_text="1girl. solo. chibi.",
                                  final_prompt_source="reconstructed"))
    b = add_asset(env.store, "b" * 64, "b.png", meta=uncaptured())

    document = compare.compare_assets(env.store, [a, b])

    row = row_of(document, "final_prompt")
    assert row["state"] == "incomplete", f"分からない枚があるのに {row['state']}"
    assert row["unknown"] == [b]
    assert row["values"] == [captured, None]
    assert row["cells"] == ["same", "unknown"]
    assert row["known_prefix"] == {b: "(masterpiece, best quality), safe,"}

    detail = document["diff"]["prompt_diff"]
    assert detail["unknown"] == [b]
    assert detail["per_asset"][b] == [], "分からない枚を語の差分にしている"
    states = [token["state"] for token in detail["tokens"]]
    assert "added" not in states, f"分からない枚のせいで追加に見えている: {states}"
    assert detail["normalized_equal"] is False and detail["reweighted"] is False
    # 分からない枚は `assets` にも入れない（「持っていない」ではない）
    assert all(b not in token["assets"] for token in detail["tokens"])


def test_an_unknown_base_does_not_turn_the_other_words_into_added(env):
    """監査 B2: 基準が分からないとき、分かっている枚の語を「追加」と言わない。

    捕獲した 1 枚と比べて訳文がまるごと「追加」に見えた形は、**基準が分からない枚**の
    ときに裏返しでも起きる（捕獲した側が `added` だらけになる）。基準が分からなければ
    比べない、が答え。
    """
    captured = "(masterpiece), safe,\n\n1girl. solo. chibi."
    a = add_asset(env.store, "a" * 64, meta=uncaptured())            # 基準（分からない）
    b = add_asset(env.store, "b" * 64, "b.png",
                  meta=uncaptured(final_prompt=captured, en_text="1girl. solo. chibi."))

    document = compare.compare_assets(env.store, [a, b])

    row = row_of(document, "final_prompt")
    assert row["state"] == "incomplete" and row["unknown"] == [a]
    detail = document["diff"]["prompt_diff"]
    assert detail["base"] == a and detail["unknown"] == [a]
    assert detail["per_asset"][a] == []
    assert {entry["state"] for entry in detail["per_asset"][b]} == {"unknown"}
    assert [entry["t"] for entry in detail["per_asset"][b]][0] == "(masterpiece)"
    assert {token["state"] for token in detail["tokens"]} == {"unknown"}
    assert detail["normalized_equal"] is False and detail["reweighted"] is False


def test_an_image_without_any_prompt_is_unknown_not_same(env):
    """監査 B2: そもそも最終プロンプトが無い枚も「同じ」と言わない（来歴なしの 2 枚）。"""
    a = add_asset(env.store, "a" * 64, meta=None)
    b = add_asset(env.store, "b" * 64, "b.png", meta=None)

    document = compare.compare_assets(env.store, [a, b])

    row = row_of(document, "final_prompt")
    assert row["state"] == "unknown" and row["values"] == [None, None]
    assert row["cells"] == ["unknown", "unknown"] and "known_prefix" not in row
    # 来歴そのものの行は今までどおり（この修正は `final_prompt` の行だけ）
    assert row_of(document, "model")["state"] == "same"
