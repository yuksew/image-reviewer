"""書き出し（P7-2）のテスト。

設計: `docs/p7-design.md` §0.4（`mode` の写し方）・§0.7（印の前提 3 つ。`'前提1'`〜`'前提3'`）・
§0.8（書き出す前の検査。動的コンボの展開・繋がらないときに止めない）・§0.9（seed の増やし方）・
§0.10（`GET` は書かない・`actor`・`client_token`・原子性）・§3.3・§8.1（16・17・22・23）

方針: **ComfyUI も模型も呼ばない**（宣言は `test_recipe.FakeProbe` を差し込む）。
各テストの docstring に「**何を壊すと落ちるか**」を §8.1 の番号で書く。
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from image_reviewer import recipe_export
from image_reviewer.recipe import RecipeService, recipe_hash
from image_reviewer.recipe_export import (
    RecipeExportService,
    apply_export,
    attempt_dir,
    first_ksampler,
    marker_for,
    new_attempt_id,
    precheck,
    save_nodes,
    seeds_for,
)
from image_reviewer.review import ReviewError
from image_reviewer.store import Store
from test_recipe import DECLARATIONS, GRAPH, PLAIN_GRAPH, FakeProbe, add_asset, clone, make_png

# ---- 道具 ----


@pytest.fixture
def env(tmp_path):
    """Store ＋ 記録 ＋ 書き出し（偽の ComfyUI）。**実データも ComfyUI も使わない**。"""
    store = Store(tmp_path / "data")
    probe = FakeProbe()
    recipes = RecipeService(store, probe_factory=lambda settings: probe)
    exports = RecipeExportService(store, recipes, probe_factory=lambda settings: probe)
    try:
        yield SimpleNamespace(store=store, recipes=recipes, exports=exports, probe=probe,
                              tmp_path=tmp_path)
    finally:
        store.close()


def record_of(env, graph, *, name="a.png", sha="a" * 64, mode="pin_text", text=None):
    """1 枚登録して記録を作る（`recipe_id` を返す）。"""
    asset_id, _path = add_asset(env, graph, name=name, sha=sha)
    got = env.recipes.record(asset_id, mode=mode, text=text, actor="human")
    return got["recipe_id"], asset_id


def plain_without_sampler() -> dict:
    """`KSampler` の無いグラフ（実データに 3 枚ある形。§8.1 の P7-2）。"""
    graph = clone(PLAIN_GRAPH)
    graph.pop("15")
    graph["16"] = {"class_type": "VAEDecode", "inputs": {"samples": ["14", 0], "vae": ["2", 0]}}
    graph["17"] = {"class_type": "SaveImage", "inputs": {"filename_prefix": "x", "images": ["16", 0]}}
    graph["14"] = {"class_type": "EmptyLatentImage", "inputs": {"width": 64, "height": 64}}
    return graph


# ---- 純関数（鍵と印と seed）----


def test_the_marker_does_not_change_the_hash_but_the_seed_does():
    """**何を壊すと落ちるか**: 鍵から `filename_prefix` を除くのをやめる（§0.5。印を付けると鍵が変わる）。

    印（`filename_prefix`）を書き換えても鍵が変わらず、**seed を変えると変わる**こと。
    """
    base = apply_export(GRAPH, mode="rerun_graph", text=None, seed=None)[0]
    marked = clone(base)
    marked["17"]["inputs"]["filename_prefix"] = "repro-abcdefgh/seed-1"
    assert recipe_hash(marked) == recipe_hash(base), "印で鍵が変わった（`filename_prefix` の除外が効いていない）"
    other = apply_export(GRAPH, mode="rerun_graph", text=None, seed="999")[0]
    assert recipe_hash(other) != recipe_hash(base), "seed を変えても鍵が変わらない（`seed` が鍵に入っていない）"


def test_seeds_are_strings_and_wrap_at_64_bits():
    """**何を壊すと落ちるか**: seed を数値で返す・折り返しをやめる（§0.9。`(seed + k) mod 2^64`）。"""
    assert seeds_for("18446744073709551615", 3) == ["18446744073709551615", "0", "1"]
    assert all(isinstance(s, str) for s in seeds_for(1, 2)), "seed が文字列でない（契約は文字列）"


def test_the_marker_has_the_folder_and_the_noseed_form():
    """**何を壊すと落ちるか**: 印の形を変える（§0.7。`repro-<attempt_id>/seed-<seed>` と `…/noseed`）。"""
    assert marker_for("abcd1234", "7") == "repro-abcd1234/seed-7"
    assert marker_for("abcd1234", None) == "repro-abcd1234/noseed"


def test_the_attempt_id_is_long_enough_for_exact_matching():
    """**何を壊すと落ちるか**: `attempt_id` を短くする（点検 D-12。部分一致が他人の名前に当たる）。"""
    for _ in range(20):
        got = new_attempt_id()
        assert len(got) >= 8 and all(c.isdigit() or ("a" <= c <= "z") for c in got), got


# ---- 検査（印の前提）----


def test_a_graph_with_two_save_nodes_gets_no_marker():
    """**何を壊すと落ちるか**: 前提 1 の検査を外す（§0.7。保存ノードが 2 つだと印を付けられない）。"""
    graph = clone(GRAPH)
    graph["18"] = {"class_type": "SaveImage", "inputs": {"filename_prefix": "y", "images": ["16", 0]}}
    got = precheck(graph, None, inspected=False)
    assert got["marker_ok"] is False and got["marker_skip_reason"] == "前提1"


def test_a_linked_prefix_gets_no_marker():
    """**何を壊すと落ちるか**: 前提 2 の検査を外す（§0.7。`filename_prefix` が結線だと書き換えられない）。"""
    graph = clone(GRAPH)
    graph["7b"] = {"class_type": "PrimitiveStringMultiline", "inputs": {"value": "repro"}}
    graph["17"]["inputs"]["filename_prefix"] = ["7b", 0]
    got = precheck(graph, None, inspected=False)
    assert got["marker_ok"] is False and got["marker_skip_reason"] == "前提2"


def test_a_key_outside_the_declaration_is_prerequisite_three_but_the_dynamic_combo_is_not():
    """**何を壊すと落ちるか**: 前提 3 の検査を外す／動的コンボの展開をやめる（§0.8。点検 A-1）。

    - **ja2en の実物の形**（`TextGenerate` の入れ子 `sampling_mode.*`）は**展開されるので通る**
    - 宣言に無いキーを足すと **`前提3`** になる
    """
    ok = precheck(GRAPH, _decl_by_node(GRAPH), inspected=True)
    assert ok["marker_ok"] is True, f"動的コンボの入れ子で落ちた（点検 A-1）: {ok['unresolved']}"
    graph = clone(GRAPH)
    graph["15"]["inputs"]["seed_typo"] = 1
    got = precheck(graph, _decl_by_node(graph), inspected=True)
    assert got["marker_ok"] is False and got["marker_skip_reason"] == "前提3"
    assert any("seed_typo" in n for n in got["notes"]), "落ちたキーを notes に出していない"


def _decl_by_node(graph: dict) -> dict:
    """テスト用: ノード id → 宣言のキー（**本物の `_declarations` と同じ形**にする）。

    `RecipeExportService._declarations` を通すために、偽の probe を 1 つ作って呼ぶ。
    """
    store_env = SimpleNamespace()
    probe = FakeProbe()
    svc = RecipeExportService.__new__(RecipeExportService)
    svc._decl_cache = {}
    return svc._declarations(graph, probe)


# ---- 書き出し（サービス）----


def test_the_export_writes_one_file_per_seed_plus_a_manifest(env):
    """**何を壊すと落ちるか**: 置き場・ファイル名・manifest のどれかを変える（§3.3 / §6.1）。"""
    recipe_id, _asset = record_of(env, GRAPH)
    got = env.exports.export(recipe_id, seeds=["1", "2"], actor="human")
    out = Path(got["export_dir"])
    assert sorted(p.name for p in out.iterdir()) == ["manifest.json", "seed-1.json", "seed-2.json"]
    assert got["files"] == ["seed-1.json", "seed-2.json", "manifest.json"]
    assert got["marker"] == "repro-" + got["attempt_id"] + "/seed-1"
    manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["attempt_id"] == got["attempt_id"] and manifest["abi"] == "0.1"
    assert set(manifest["export_hashes"]) == {"1", "2"}
    assert all(v.startswith("sha256:") for v in manifest["export_hashes"].values())
    # **契約の形**（`additionalProperties: false` なので余分なキーを足すと落ちる。P7-2 で踏んだ）
    assert set(manifest) <= {"schema", "abi", "generated_at", "attempt_id", "recipe_id", "mode",
                             "recipe_hash", "export_hashes", "seeds", "marker_skipped", "source",
                             "notes", "output_dir"}, f"契約に無いキー: {sorted(manifest)}"
    assert [s["seed"] for s in manifest["seeds"]] == ["1", "2"]
    assert manifest["seeds"][0]["file"] == "seed-1.json"
    assert manifest["seeds"][0]["expected_prefix"] == got["marker"]
    assert manifest["notes"]["status"] == got["status"]
    assert manifest["notes"]["inspected"] is True
    assert manifest["notes"]["instruction"], "手順の 1 行が空"
    assert set(manifest["source"]) == {"asset_id", "sha256", "filename", "model", "seed", "size"}
    # **印が実際にグラフへ入っている**
    written = json.loads((out / "seed-1.json").read_text(encoding="utf-8"))
    assert written["17"]["inputs"]["filename_prefix"] == got["marker"]
    assert got["seed_node"] == "15"


def test_the_two_modes_keep_the_record_and_differ_in_the_files(env):
    """**何を壊すと落ちるか**: `mode` を記録に書き戻す／繋がりを外さない（§0.12 / §8.1-22）。

    **`TextGenerate` を含む graph**（ja2en の形）を、**貼る英文がある**状態で記録してから書き出す:
    - `rerun_graph`（L2）: そのまま（`TextGenerate` が残る）
    - `pin_text`（L1）: **繋がりを外して英文を貼る**（`TextGenerate` が消え、`text_pinned` が付く）
    - **記録の `recipe_hash` と `record_json` は前後で変わらない**
    """
    recipe_id, asset_id = record_of(env, GRAPH, mode="manual_text",
                                    text="1girl, classroom, window light")
    before = env.recipes.get(asset_id)
    one = env.exports.export(recipe_id, mode="rerun_graph", seeds=["5"], actor="human")
    two = env.exports.export(recipe_id, mode="pin_text", seeds=["5"], actor="human")
    after = env.recipes.get(asset_id)
    assert after["recipe_hash"] == before["recipe_hash"], "書き出しが記録の鍵を変えた"
    assert after["record"] == before["record"], "書き出しが記録を書き換えた"
    a = json.loads((Path(one["export_dir"]) / "seed-5.json").read_text(encoding="utf-8"))
    b = json.loads((Path(two["export_dir"]) / "seed-5.json").read_text(encoding="utf-8"))
    assert "9" in a, "rerun_graph がテキスト生成の鎖を消した（そのまま回すはず）"
    assert "9" not in b, "pin_text がテキスト生成の鎖を外していない"
    assert b["12"]["inputs"]["text"] == "1girl, classroom, window light", "pin_text が英文を貼っていない"
    assert "text_pinned" in two["reasons"], "pin_text の理由（text_pinned）が出ていない"
    assert "llm_nondeterministic" in one["reasons"], "rerun_graph の理由（llm_nondeterministic）が出ていない"


def test_the_same_client_token_returns_the_same_attempt_and_writes_nothing_new(env):
    """**何を壊すと落ちるか**: 再送で新しい束を作る（§0.10 / §8.1-16。行もファイルも増やさない）。"""
    recipe_id, _asset = record_of(env, GRAPH)
    first = env.exports.export(recipe_id, seeds=["1"], actor="human", client_token="tok-1")
    again = env.exports.export(recipe_id, seeds=["1"], actor="human", client_token="tok-1")
    assert again["replayed"] is True and again["attempt_id"] == first["attempt_id"]
    with env.store.locked() as con:
        attempts = con.execute("SELECT count(*) AS n FROM recipe_export_attempt").fetchone()["n"]
        files = con.execute("SELECT count(*) AS n FROM recipe_export").fetchone()["n"]
    assert (attempts, files) == (1, 1), "再送で行が増えた"
    out = Path(first["export_dir"])
    assert len(list(out.iterdir())) == 2, "再送でファイルが増えた"


def test_the_same_client_token_with_other_content_is_409(env):
    """**何を壊すと落ちるか**: 中身の照合を外す（§0.10。同じ token で違う物は 409）。"""
    recipe_id, _asset = record_of(env, GRAPH)
    env.exports.export(recipe_id, mode="pin_text", seeds=["1"], actor="human", client_token="tok-2")
    with pytest.raises(ReviewError) as got:
        env.exports.export(recipe_id, mode="rerun_graph", seeds=["1"], actor="human",
                           client_token="tok-2")
    assert got.value.status == 409 and got.value.code == "client_token_conflict"


def test_a_graph_without_a_sampler_refuses_seeds_and_writes_one_noseed_file(env):
    """**何を壊すと落ちるか**: `no_sampler` を返さない／`noseed` の道を消す（§3.3。実データに 3 枚）。"""
    recipe_id, _asset = record_of(env, plain_without_sampler(), name="n.png", sha="c" * 64)
    with pytest.raises(ReviewError) as got:
        env.exports.export(recipe_id, seeds=["1"], actor="human")
    assert got.value.status == 422 and got.value.code == "no_sampler"
    fine = env.exports.export(recipe_id, actor="human")
    assert fine["files"] == ["seed-noseed.json", "manifest.json"]
    assert fine["marker"] == "repro-" + fine["attempt_id"] + "/noseed"
    assert (Path(fine["export_dir"]) / "seed-noseed.json").exists()


def test_an_impossible_record_is_not_exported(env):
    """**何を壊すと落ちるか**: 関所（`impossible` は書き出さない）を外す（§3.3 / §4.7）。"""
    recipe_id, _asset = record_of(env, None, name="j.png", sha="d" * 64)   # グラフ無し＝impossible
    with pytest.raises(ReviewError) as got:
        env.exports.export(recipe_id, actor="human")
    assert got.value.status == 409 and got.value.code == "recipe_impossible"


def test_an_unreachable_comfyui_does_not_stop_the_export(env):
    """**何を壊すと落ちるか**: 繋がらないときに止める（§0.8 / §8.1-23。検査だけ飛ばして書き出す）。"""
    recipe_id, _asset = record_of(env, PLAIN_GRAPH, name="u.png", sha="e" * 64)
    blind = FakeProbe(stats=False)
    env.exports._probe_factory = lambda settings: blind
    checked = env.exports.check(recipe_id)
    assert checked["inspected"] is False
    got = env.exports.export(recipe_id, seeds=["3"], actor="human")
    assert got["inspected"] is False and got["files"][0] == "seed-3.json"


def test_an_atomic_write_failure_leaves_no_tmp_file(env, monkeypatch):
    """**何を壊すと落ちるか**: 一時ファイルの後始末を外す（§0.10。半端なファイルを残さない）。"""
    from image_reviewer import export as export_mod

    recipe_id, _asset = record_of(env, PLAIN_GRAPH, name="t.png", sha="f" * 64)

    def boom(_src, _dst):
        raise OSError("置き換えに失敗")

    monkeypatch.setattr(export_mod.os, "replace", boom)
    with pytest.raises(OSError):
        env.exports.export(recipe_id, seeds=["1"], actor="human")
    leftovers = list((Path(env.store.data_dir) / "recipes").rglob("*.tmp"))
    assert leftovers == [], f"一時ファイルが残った: {leftovers}"


def test_the_mode_defaults_to_the_record_and_can_be_overridden(env):
    """**何を壊すと落ちるか**: 書き出しの `mode` を記録から写さない（§0.4。束に写す）。"""
    recipe_id, _asset = record_of(env, PLAIN_GRAPH, name="m.png", sha="1" * 64)
    got = env.exports.export(recipe_id, mode="rerun_graph", seeds=["1"], actor="human")
    with env.store.locked() as con:
        row = con.execute("SELECT mode, seed_node FROM recipe_export_attempt WHERE attempt_id = ?",
                          (got["attempt_id"],)).fetchone()
        record_mode = con.execute("SELECT mode FROM recipe_record WHERE id = ?",
                                  (recipe_id,)).fetchone()["mode"]
    assert row["mode"] == "rerun_graph" and got["mode"] == "rerun_graph"
    assert record_mode == "pin_text", "記録の mode が書き換わった"


def test_the_exports_endpoint_reads_without_writing(env):
    """**何を壊すと落ちるか**: `GET` でファイルを書く（§0.10。家風「`GET` は 1 バイトも書かない」）。"""
    recipe_id, _asset = record_of(env, PLAIN_GRAPH, name="g.png", sha="2" * 64)
    got = env.exports.export(recipe_id, seeds=["1"], actor="human")
    out = Path(got["export_dir"])
    before = {p.name: (p.stat().st_size, p.stat().st_mtime_ns) for p in out.iterdir()}
    with env.store.locked() as con:
        rows = con.execute("SELECT count(*) AS n FROM recipe_export").fetchone()["n"]
    listed = env.exports.exports(recipe_id)
    assert listed["items"][0]["attempt_id"] == got["attempt_id"]
    assert listed["items"][0]["checked"]["marker_ok"] is True
    after = {p.name: (p.stat().st_size, p.stat().st_mtime_ns) for p in out.iterdir()}
    assert after == before, "`GET` がファイルを書いた"
    with env.store.locked() as con:
        assert con.execute("SELECT count(*) AS n FROM recipe_export").fetchone()["n"] == rows


def test_the_new_endpoints_are_guarded(tmp_path, monkeypatch):
    """**何を壊すと落ちるか**: 新しい `POST` に middleware の守りを付け忘れる（スキル §3）。

    `Host: evil` と `Content-Type: text/plain` は **403**（`POST` を足すたびに書く）。
    **`IMAGE_REVIEWER_DATA` を複製に向けてから** `create_app()` を呼ぶ（**実データを開かない**）。
    """
    from fastapi.testclient import TestClient

    from image_reviewer.app import create_app

    monkeypatch.setenv("IMAGE_REVIEWER_DATA", str(tmp_path / "data"))
    app = create_app()
    with TestClient(app) as client:
        for path in ("/api/recipes/01abc/check", "/api/recipes/01abc/export"):
            bad_host = client.post(path, json={}, headers={"Host": "evil.example"})
            assert bad_host.status_code == 403, f"{path} が Host で弾かれない"
            bad_type = client.post(path, content=b"x",
                                   headers={"Content-Type": "text/plain",
                                            "X-Image-Reviewer-Actor": "human"})
            assert bad_type.status_code == 403, f"{path} が Content-Type で弾かれない"
        # agent は 403（**人だけ**。§0.10）
        agent = client.post("/api/recipes/01abc/export", json={},
                            headers={"X-Image-Reviewer-Actor": "agent"})
        assert agent.status_code == 403


def test_the_small_helpers_agree_with_the_graph():
    """**何を壊すと落ちるか**: 保存ノードや `KSampler` の選び方を変える（§4.7.2。**最初の 1 つ**だけ）。"""
    assert save_nodes(GRAPH) == ["17"]
    node, others = first_ksampler(GRAPH, "17")
    assert node == "15" and others == []
    # **2 つ目の KSampler も到達できる**形（`ImageBatch` で 2 つの出力を混ぜる）
    two = clone(GRAPH)
    two["19"] = {"class_type": "KSampler", "inputs": {"seed": 1, "model": ["6", 0],
                                                      "positive": ["12", 0], "negative": ["13", 0],
                                                      "latent_image": ["14", 0], "steps": 1, "cfg": 1.0,
                                                      "sampler_name": "er_sde", "scheduler": "beta",
                                                      "denoise": 1.0}}
    two["18"] = {"class_type": "VAEDecode", "inputs": {"samples": ["19", 0], "vae": ["1", 0]}}
    two["20"] = {"class_type": "ImageBatch", "inputs": {"image1": ["16", 0], "image2": ["18", 0]}}
    two["17"]["inputs"]["images"] = ["20", 0]
    node2, others2 = first_ksampler(two, "17")
    assert node2 == "16" or node2 in ("15", "19"), "最初の KSampler が保存ノードに近い方になっていない"
    assert set(others2) == {"15", "19"} - {node2}, "残りの KSampler を列挙していない"


def test_the_export_dir_is_under_the_data_dir(env):
    """**何を壊すと落ちるか**: 置き場をデータの外に置く（§6.1。`<data>/recipes/<recipe>/<attempt>/`）。"""
    got = attempt_dir(env.store.data_dir, "01RECIPE", "abcd1234")
    assert Path(env.store.data_dir) in got.parents
    assert got.parts[-2:] == ("01RECIPE", "abcd1234")
    assert os.path.isdir(env.store.data_dir), "置き場の親が無い（書く前に作っていない）"
