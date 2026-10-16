"""条件の記録（P7-1）のテスト。

設計: `docs/p7-design.md` §0.5（鍵はグラフだけの純関数）・§0.6（判定。**記録時は 7 語だけ**）・
§0.7（グラフの置き場）・§0.10（`GET` は書かない・`actor`・`client_token`）・§3.1〜§3.2・§8.1

方針: **ComfyUI も模型も呼ばない**（宣言は `FakeProbe` で差し込む）。
各テストの docstring に「**何を壊すと落ちるか**」を §8.1 の番号で書く。
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image, PngImagePlugin

from image_reviewer import db
from image_reviewer.recipe import (
    ComfyProbe,
    RecipeService,
    canonical_graph,
    declaration_notes,
    dynamic_subkeys,
    judge,
    recipe_hash,
    record_doc,
    text_unknown,
)
from image_reviewer.review import ReviewError
from image_reviewer.store import Store

# ---- 道具 ----


def clone(graph: dict) -> dict:
    """グラフの深い写し（**テストが GRAPH を壊さない**ように。入れ子の dict は共有される）。"""
    return json.loads(json.dumps(graph))


def make_png(path: Path, graph: dict | None, *, color=(40, 60, 90)) -> Path:
    """合成の PNG（`prompt` チャンクに API 形式のグラフを入れる）。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    im = Image.new("RGB", (48, 64), color)
    info = PngImagePlugin.PngInfo()
    if graph is not None:
        info.add_text("prompt", json.dumps(graph))
    im.save(path, pnginfo=info)
    return path


#: ja2en の実物と同じ形（`TextGenerate` と**入れ子の `sampling_mode.*`** を持つ）
GRAPH = {
    "1": {"class_type": "VAELoader", "inputs": {"vae_name": "qwen_image_vae.safetensors"}},
    "2": {"class_type": "CLIPLoader", "inputs": {"clip_name": "qwen_3_06b_base.safetensors"}},
    "3": {"class_type": "UNETLoader", "inputs": {"unet_name": "anima-turbo-v1.1.safetensors"}},
    "5": {"class_type": "CLIPLoader", "inputs": {"clip_name": "qwen3vl_8b_int8_convrot.safetensors"}},
    "6": {"class_type": "LoraLoaderModelOnly",
          "inputs": {"lora_name": "BuAnime.safetensors", "strength_model": 0.8, "model": ["3", 0]}},
    "7": {"class_type": "PrimitiveStringMultiline", "inputs": {"value": "教室で少女が窓の外を見ている。"}},
    "8": {"class_type": "PrimitiveStringMultiline", "inputs": {"value": "You translate Japanese into English."}},
    "9": {"class_type": "TextGenerate",
          "inputs": {"prompt": ["7", 0], "clip": ["5", 0], "system_prompt": ["8", 0],
                     "max_length": 512, "sampling_mode": "on", "sampling_mode.temperature": 0.7,
                     "sampling_mode.seed": 20261010, "thinking": False, "mtp": "auto"}},
    "10": {"class_type": "StringConcatenate",
           "inputs": {"string_a": "(masterpiece, best quality), safe,", "string_b": ["9", 0],
                      "delimiter": "\n\n"}},
    "12": {"class_type": "CLIPTextEncode", "inputs": {"text": ["10", 0], "clip": ["2", 0]}},
    "13": {"class_type": "CLIPTextEncode", "inputs": {"text": "lowres, bad", "clip": ["2", 0]}},
    "14": {"class_type": "EmptyLatentImage", "inputs": {"width": 768, "height": 1360}},
    "15": {"class_type": "KSampler",
           "inputs": {"seed": 854343803298746, "steps": 10, "cfg": 1.0, "sampler_name": "er_sde",
                      "scheduler": "beta", "denoise": 1.0, "model": ["6", 0],
                      "positive": ["12", 0], "negative": ["13", 0], "latent_image": ["14", 0]}},
    "16": {"class_type": "VAEDecode", "inputs": {"samples": ["15", 0], "vae": ["1", 0]}},
    "17": {"class_type": "SaveImage", "inputs": {"filename_prefix": "x", "images": ["16", 0]}},
}

#: 実物から写した形の宣言（**テストで ComfyUI を叩かない**。§8.1 の 31）
DECLARATIONS = {
    "VAELoader": {"input": {"required": {"vae_name": [["qwen_image_vae.safetensors"], {}]}}},
    "CLIPLoader": {"input": {"required": {"clip_name": [["qwen_3_06b_base.safetensors",
                                                         "qwen3vl_8b_int8_convrot.safetensors"], {}]}}},
    "UNETLoader": {"input": {"required": {"unet_name": [["anima-turbo-v1.1.safetensors"], {}]}}},
    "LoraLoaderModelOnly": {"input": {"required": {
        "lora_name": [["BuAnime.safetensors"], {}], "strength_model": ["FLOAT", {}],
        "model": ["MODEL", {}]}}},
    "PrimitiveStringMultiline": {"input": {"required": {"value": ["STRING", {"multiline": True}]}}},
    # **動的コンボ**（点検 A-1。入れ子のキーは `input.required` には `sampling_mode` しか出ない）
    "TextGenerate": {"input": {"required": {
        "prompt": ["STRING", {}], "clip": ["CLIP", {}], "system_prompt": ["STRING", {}],
        "max_length": ["INT", {}], "thinking": ["BOOLEAN", {}], "mtp": [["auto"], {}],
        "sampling_mode": ["COMFY_DYNAMICCOMBO_V3", {"options": [
            {"key": "on", "inputs": {"required": {"temperature": ["FLOAT", {}],
                                                  "seed": ["INT", {}]}}},
            {"key": "off", "inputs": {"required": {}}}]}]}}},
    "StringConcatenate": {"input": {"required": {
        "string_a": ["STRING", {}], "string_b": ["STRING", {}], "delimiter": ["STRING", {}]}}},
    "CLIPTextEncode": {"input": {"required": {"text": ["STRING", {}], "clip": ["CLIP", {}]}}},
    "EmptyLatentImage": {"input": {"required": {"width": ["INT", {}], "height": ["INT", {}]}}},
    "KSampler": {"input": {"required": {
        "seed": ["INT", {}], "steps": ["INT", {}], "cfg": ["FLOAT", {}],
        "sampler_name": [["er_sde", "euler"], {}], "scheduler": [["beta", "normal"], {}],
        "denoise": ["FLOAT", {}], "model": ["MODEL", {}], "positive": ["CONDITIONING", {}],
        "negative": ["CONDITIONING", {}], "latent_image": ["LATENT", {}]}}},
    "VAEDecode": {"input": {"required": {"samples": ["LATENT", {}], "vae": ["VAE", {}]}}},
    "SaveImage": {"input": {"required": {"images": ["IMAGE", {}],
                                         "filename_prefix": ["STRING", {}]}}},
}


#: `TextGenerate` を持たない素直なグラフ（**literal のプロンプト**＝`exact` になる形）
PLAIN_GRAPH = {
    "2": {"class_type": "CLIPLoader", "inputs": {"clip_name": "qwen_3_06b_base.safetensors"}},
    "3": {"class_type": "UNETLoader", "inputs": {"unet_name": "anima-turbo-v1.1.safetensors"}},
    "12": {"class_type": "CLIPTextEncode",
           "inputs": {"text": "1girl, classroom, window", "clip": ["2", 0]}},
    "13": {"class_type": "CLIPTextEncode", "inputs": {"text": "lowres, bad", "clip": ["2", 0]}},
    "14": {"class_type": "EmptyLatentImage", "inputs": {"width": 768, "height": 1360}},
    "15": {"class_type": "KSampler",
           "inputs": {"seed": 12345, "steps": 10, "cfg": 1.0, "sampler_name": "er_sde",
                      "scheduler": "beta", "denoise": 1.0, "model": ["3", 0],
                      "positive": ["12", 0], "negative": ["13", 0], "latent_image": ["14", 0]}},
    "17": {"class_type": "SaveImage", "inputs": {"filename_prefix": "x", "images": ["15", 0]}},
}


class FakeProbe(ComfyProbe):
    """偽の ComfyUI（**ネットワークを使わない**）。宣言と環境の写しだけ返す。"""

    def __init__(self, *, declarations=None, stats=True):    # noqa: D107
        super().__init__("http://127.0.0.1:1")
        self._fake_declarations = DECLARATIONS if declarations is None else declarations
        self._fake_stats = stats
        self.calls: list[str] = []

    def system_stats(self):                                   # noqa: D102
        return {"system": {"comfyui_version": "0.39.2", "pytorch_version": "2.9.0"},
                "devices": [{"name": "cuda:0", "cuda_version": "13.0"}]} if self._fake_stats else None

    def installed_nodes(self):                                # noqa: D102
        return {"nodes": {"ComfyUI-WD14-Tagger": {"version": "1.0"}}}

    def object_info(self, class_type):                        # noqa: D102
        self.calls.append(class_type)
        got = self._fake_declarations.get(class_type)
        return {class_type: got} if got is not None else None

    def models(self, folder):                                 # noqa: D102
        return {"anima-turbo-v1.1.safetensors": {"size": 123, "mtime": 456}} if folder == "diffusion_models" else {}


@pytest.fixture
def env(tmp_path):
    """Store ＋ 記録のサービス（偽の ComfyUI）。**実データも ComfyUI も使わない**。"""
    store = Store(tmp_path / "data")
    probe = FakeProbe()
    svc = RecipeService(store, probe_factory=lambda settings: probe)
    try:
        yield SimpleNamespace(store=store, svc=svc, probe=probe, tmp_path=tmp_path)
    finally:
        store.close()


def add_asset(env, graph, *, name="a.png", sha="a" * 64) -> tuple[str, Path]:
    """合成の PNG を作って登録する。返すのは `(asset_id, path)`。"""
    path = make_png(env.tmp_path / "images" / name, graph)
    asset_id, _ = env.store.register(sha256=sha, path=str(path), size=path.stat().st_size,
                                     mtime_ns=path.stat().st_mtime_ns, width=48, height=64,
                                     fmt="png", meta=None, note=None)
    return asset_id, path


def status_of(func, *args, **kw) -> int:
    with pytest.raises(ReviewError) as got:
        func(*args, **kw)
    return got.value.status


def rows(env, sql: str, args: tuple = ()) -> list:
    return env.store.con.execute(sql, args).fetchall()


# ---- 鍵（§0.5。§8.1 の 1〜3・33）----


def test_the_marker_does_not_change_the_key():
    """§8.1 の 1: `filename_prefix` の除外を外すと落ちる（**印を付けても鍵が変わらない**）。"""
    base = clone(GRAPH)
    marked = clone(GRAPH)
    marked["17"]["inputs"]["filename_prefix"] = "repro-01J8/seed-123"
    assert recipe_hash(base) == recipe_hash(marked), "印を入れたら鍵が変わった（§0.5 の除外が効いていない）"


def test_denoise_is_in_the_key():
    """§8.1 の 2: `denoise` を鍵から外すと落ちる（**別の絵を「同じ条件」と呼ばない**）。"""
    other = clone(GRAPH)
    other["15"]["inputs"]["denoise"] = 0.5
    assert recipe_hash(GRAPH) != recipe_hash(other)


def test_links_are_in_the_key():
    """§8.1 の 3: 結線を鍵から外すと落ちる（結線は条件の一部）。"""
    other = clone(GRAPH)
    other["15"]["inputs"]["positive"] = ["13", 0]          # 結線だけ入れ替える
    assert recipe_hash(GRAPH) != recipe_hash(other)


def test_the_key_does_not_depend_on_the_file(env):
    """§8.1 の 33: **鍵はグラフだけの純関数**（`(size, mtime)` を変えても変わらない）。"""
    asset_id, path = add_asset(env, GRAPH)
    before = env.svc.get_recipe_hash_for_test(path) if hasattr(env.svc, "get_recipe_hash_for_test") else None
    first = recipe_hash(clone(GRAPH))
    os.utime(path, (time.time() - 5000, time.time() - 5000))     # size は同じ・mtime を変える
    from image_reviewer.png_meta import provenance
    again = recipe_hash(provenance(path)["graph"])
    assert first == again, "ファイルの時刻で鍵が変わった（環境の値を混ぜている）"
    assert before is None or before == first


def test_canonical_graph_keeps_literals_and_links_apart():
    """鍵の材料は人が読める形（**リテラルと結線を分ける**。§0.5）。"""
    got = canonical_graph(GRAPH)
    assert got["15"]["links"]["positive"] == ["12", 0]
    assert got["15"]["inputs"]["steps"] == 10
    assert "filename_prefix" not in got["17"]["inputs"]


# ---- 判定（§0.6。§8.1 の 4・31・32）----


def test_dynamic_combo_nested_keys_are_expanded():
    """§8.1 の 31: **動的コンボの入れ子を展開**しないと落ちる（ja2en のグラフが `unresolved` になる）。"""
    reasons, notes = declaration_notes(GRAPH, DECLARATIONS)
    assert reasons == [], f"入れ子のキーを宣言に無いと誤判定した: {reasons}"
    assert not [n for n in notes if "sampling_mode" in n]


def test_an_unknown_input_key_is_unresolved():
    """§8.1 の 31（後半）: 本当に無いキーは `unresolved`（**approx**）。"""
    other = clone(GRAPH)
    other["15"]["inputs"]["foo"] = 1
    reasons, _ = declaration_notes(other, DECLARATIONS)
    assert [r["kind"] for r in reasons] == ["unresolved"]
    assert "KSampler.foo" in reasons[0]["detail"]


def test_an_unknown_dynamic_combo_is_not_inspected():
    """展開できない `COMFY_DYNAMIC*` は**検査の対象外**にして `notes` に出す（§4.7 手順 4）。"""
    declarations = dict(DECLARATIONS)
    declarations["TextGenerate"] = {"input": {"required": {
        "sampling_mode": ["COMFY_DYNAMICCOMBO_V9", {"mystery": True}]}}}
    reasons, notes = declaration_notes({"9": {"class_type": "TextGenerate",
                                              "inputs": {"sampling_mode": "on"}},
                                        "17": {"class_type": "SaveImage",
                                               "inputs": {"images": ["9", 0]}}}, declarations)
    assert reasons == []
    assert any("展開できない動的コンボ" in n for n in notes), notes


def test_a_model_missing_from_the_combo_is_impossible():
    """§0.6: **モデルが選択肢に無い → `impossible`**（`unresolved` の重い側。監査 A-2）。

    前の版はここが `approx` のままだった（`unresolved` を `kind` だけで見ていた）。**`status` まで見る**。
    """
    other = clone(GRAPH)
    other["3"]["inputs"]["unet_name"] = "no-such-model.safetensors"
    reasons, _ = declaration_notes(other, DECLARATIONS)
    assert [r["kind"] for r in reasons] == ["unresolved"]
    assert "選択肢に無い" in reasons[0]["detail"]
    assert reasons[0].get("fatal") is True, "モデルの欠落が fatal の印を持っていない（監査 A-2）"
    got = judge(prov={"graph": other, "info": {}}, doc={"final_prompt": "x"},
                env={}, inspected=True, extra=reasons)
    assert got["status"] == "impossible", f"選択肢に無いモデルが {got['status']} になった（監査 A-2）"


def test_a_missing_node_is_impossible():
    """§8.1 の 11 / 監査 A-1: **引いたが無かった**（`{}`）ノードは `node_missing`（impossible）。

    **引けなかった**（`None`）と混ぜない（混ぜると ComfyUI 不通で全部 `impossible` になっていた）。
    """
    declarations = dict(DECLARATIONS)
    declarations["KSampler"] = {}                       # **引いたが、知らない class_type**
    reasons, _ = declaration_notes(GRAPH, declarations)
    assert "node_missing" in [r["kind"] for r in reasons]


def test_a_declaration_we_could_not_fetch_is_not_node_missing():
    """監査 A-1: **引けなかった**（`None`）は `node_missing` にしない（**検査していない**だけ）。"""
    declarations = dict(DECLARATIONS)
    declarations["KSampler"] = None
    reasons, notes = declaration_notes(GRAPH, declarations)
    assert [r["kind"] for r in reasons] == [], "引けなかった宣言を node_missing にした（監査 A-1）"
    assert any("宣言が取れなかった" in n for n in notes), notes


def test_graph_without_a_prompt_chunk_is_impossible_with_missing(env):
    """§8.1 の 4: **グラフが無い（JPEG など）→ `impossible` ＋ `missing`**（記録は作る）。"""
    asset_id, _ = add_asset(env, None, name="b.png", sha="b" * 64)
    got = env.svc.record(asset_id, mode="pin_text", actor="human")
    assert got["status"] == "impossible"
    assert got["reasons"] == ["missing"]
    assert got["graph_path"] is None
    assert env.svc.get(asset_id)["status"] == "impossible"


def test_text_not_captured_only_when_a_text_encoder_exists(env):
    """§8.1 の 32: `CLIPTextEncode` を**持たない**グラフに `text_not_captured` を付けない。"""
    plain = clone(GRAPH)
    plain = {k: v for k, v in plain.items() if v["class_type"] != "CLIPTextEncode"}
    plain["15"]["inputs"]["positive"] = ["9", 0]        # 直接つなぐ（テキストを使わない形にする）
    plain["15"]["inputs"]["negative"] = ["9", 0]
    asset_id, _ = add_asset(env, plain, name="c.png", sha="c" * 64)
    got = env.svc.record(asset_id, mode="pin_text", actor="human")
    assert "text_not_captured" not in got["reasons"], "テキストを使わないグラフに付いた"

    # `CLIPTextEncode` があって `final_prompt` が分からない方は付く
    asset_id2, _ = add_asset(env, GRAPH, name="d.png", sha="d" * 64)
    got2 = env.svc.record(asset_id2, mode="pin_text", actor="human")
    assert "text_not_captured" in got2["reasons"]
    assert got2["status"] == "approx"


def test_record_time_reasons_are_only_the_seven(env):
    """§8.1 の 32: 記録の `reasons` に**書き出し時の 3 語を出さない**（点検 A-3）。"""
    asset_id, _ = add_asset(env, GRAPH)
    got = env.svc.record(asset_id, mode="pin_text", actor="human")
    assert not ({"text_pinned", "llm_nondeterministic", "manual_step"} & set(got["reasons"]))
    assert "text_pinned" not in (got["reasons"] or [])


def test_judge_maps_reasons_to_status():
    """§8.1 の 4: 理由 0 件 → `exact`、1 件以上 → `approx`、致命的 → `impossible`。"""
    prov = {"graph": GRAPH, "info": {}}
    doc = {"final_prompt": "x"}
    assert judge(prov=prov, doc=doc, env={}, inspected=True)["status"] == "exact"
    approx = judge(prov=prov, doc={"final_prompt": None}, env={}, inspected=True)
    assert approx["status"] == "approx"
    assert [r["kind"] for r in approx["reasons"]] == ["text_not_captured"]
    fatal = judge(prov=prov, doc=doc, env={}, inspected=True,
                  extra=[{"kind": "node_missing", "detail": "X"}])
    assert fatal["status"] == "impossible"


def test_the_manual_text_fills_the_prompt():
    """L3（`manual_text`）は貼られた英文を `final_prompt` に入れる（`final_prompt_source='manual'`）。"""
    doc = record_doc(asset_id="a", prov={"graph": GRAPH, "info": {}, "graph_format": "api"},
                     mode="manual_text", text="a girl in a classroom")
    assert doc["final_prompt"] == "a girl in a classroom"
    assert doc["final_prompt_source"] == "manual"


# ---- 記録の口（§3.2。§8.1 の 14・15・28）----


def test_recording_writes_one_row_and_a_graph_file(env):
    """1 枚に 1 記録。**グラフは `<data>/workflows/<sha256>.json`** に 1 つだけ書く（§0.7）。"""
    asset_id, _ = add_asset(env, PLAIN_GRAPH)
    got = env.svc.record(asset_id, mode="pin_text", actor="human")
    assert got["status"] == "exact", got["reasons"]
    assert got["recipe_hash"].startswith("sha256:")
    assert Path(got["graph_path"]).exists()
    assert Path(got["graph_path"]).parent.name == "workflows"
    assert len(rows(env, "SELECT 1 FROM recipe_record")) == 1
    # 2 回目（トークン無し）は既存を返す＝**行を増やさない**（画像 1 枚に 1 記録）
    again = env.svc.record(asset_id, mode="pin_text", actor="human")
    assert again["replayed"] is True and again["recipe_id"] == got["recipe_id"]
    assert len(rows(env, "SELECT 1 FROM recipe_record")) == 1


def test_the_same_token_returns_the_same_recipe(env):
    """§8.1 の 15: 同じ `client_token` の再送は **200 で同じ `recipe_id`**（行は 1 つ）。"""
    asset_id, _ = add_asset(env, GRAPH)
    first = env.svc.record(asset_id, mode="pin_text", actor="human", client_token="tok-1")
    again = env.svc.record(asset_id, mode="pin_text", actor="human", client_token="tok-1")
    assert again["replayed"] is True and again["recipe_id"] == first["recipe_id"]
    assert len(rows(env, "SELECT 1 FROM recipe_record")) == 1


def test_a_conflicting_token_is_409(env):
    """同じ `client_token` で中身が違えば 409（§3.2 の表）。"""
    a1, _ = add_asset(env, GRAPH, name="e.png", sha="e" * 64)
    a2, _ = add_asset(env, GRAPH, name="f.png", sha="f" * 64)
    env.svc.record(a1, mode="pin_text", actor="human", client_token="tok-2")
    assert status_of(env.svc.record, a2, mode="pin_text", actor="human",
                     client_token="tok-2") == 409


def test_bad_mode_and_missing_text_are_422(env):
    """§3.2 の表: `mode` が語彙の外は 422、`manual_text` で英文が空も 422。"""
    asset_id, _ = add_asset(env, GRAPH)
    assert status_of(env.svc.record, asset_id, mode="nope", actor="human") == 422
    assert status_of(env.svc.record, asset_id, mode="manual_text", text="  ", actor="human") == 422


def test_unknown_asset_is_404(env):
    """§3.1 の表: 知らない画像は 404（`details.asset_id`）。"""
    assert status_of(env.svc.get, "01MISSING") == 404
    assert status_of(env.svc.record, "01MISSING", actor="human") == 404


def test_reading_never_writes(env):
    """§8.1 の 14: **`GET` は 1 バイトも書かない**（行もファイルも増えない）。"""
    asset_id, _ = add_asset(env, GRAPH)
    env.svc.record(asset_id, mode="pin_text", actor="human")
    workflows = sorted(p.name for p in (env.store.data_dir / "workflows").glob("*"))
    before = len(rows(env, "SELECT 1 FROM recipe_record"))
    for _ in range(3):
        env.svc.get(asset_id)
        env.svc.list(limit=10)
    assert len(rows(env, "SELECT 1 FROM recipe_record")) == before
    assert sorted(p.name for p in (env.store.data_dir / "workflows").glob("*")) == workflows


def test_the_indexes_are_used(env):
    """§8.1 の 29: 索引を外すと落ちる（`EXPLAIN QUERY PLAN` に出る）。"""
    plan = " ".join(str(r["detail"]) for r in env.store.con.execute(
        "EXPLAIN QUERY PLAN SELECT * FROM recipe_record WHERE source_asset_id = 'x'"))
    assert "ux_recipe_source" in plan, plan
    plan2 = " ".join(str(r["detail"]) for r in env.store.con.execute(
        "EXPLAIN QUERY PLAN SELECT * FROM recipe_record ORDER BY created_at DESC, id DESC"))
    assert "ix_recipe_created" in plan2, plan2


# ---- 口（FastAPI 経由。§8.1 の 27・28）----


def test_the_endpoints_are_guarded_and_agent_is_403(tmp_path, monkeypatch):
    """§8.1 の 27・28: **`Host: evil` / `Content-Type: text/plain` は 403**、`agent` も 403。"""
    from fastapi.testclient import TestClient

    from image_reviewer.app import create_app

    monkeypatch.setenv("IMAGE_REVIEWER_DATA", str(tmp_path / "data"))
    app = create_app()
    with TestClient(app, base_url="http://127.0.0.1") as client:
        path = make_png(tmp_path / "images" / "g.png", GRAPH)
        asset_id, _ = app.state.store.register(
            sha256="1" * 64, path=str(path), size=path.stat().st_size,
            mtime_ns=path.stat().st_mtime_ns, width=48, height=64, fmt="png",
            meta=None, note=None)
        app.state.recipes = RecipeService(app.state.store,
                                         probe_factory=lambda settings: FakeProbe())
        body = {"mode": "pin_text"}
        assert client.post(f"/api/assets/{asset_id}/recipe", json=body,
                           headers={"Host": "evil.example"}).status_code == 403
        assert client.post(f"/api/assets/{asset_id}/recipe", content=b"{}",
                           headers={"Content-Type": "text/plain"}).status_code == 403
        # エージェントは 403（`human` だけが書ける）
        got = client.post(f"/api/assets/{asset_id}/recipe", json=body,
                          headers={"X-Image-Reviewer-Actor": "agent"})
        assert got.status_code == 403, got.text
        # 人は 201、再送は 200
        human = {"X-Image-Reviewer-Actor": "human"}
        first = client.post(f"/api/assets/{asset_id}/recipe", json=body, headers=human)
        assert first.status_code == 201, first.text
        second = client.post(f"/api/assets/{asset_id}/recipe", json=body, headers=human)
        assert second.status_code == 200 and second.json()["replayed"] is True
        # GET は読める
        assert client.get(f"/api/assets/{asset_id}/recipe").status_code == 200
        assert client.get("/api/recipes?limit=5").status_code == 200
        # 知らない画像は 404
        assert client.get("/api/assets/01MISSING/recipe").status_code == 404


# ---- P7-1 の監査の指摘（A-1〜A-4 / B-1〜B-3 / C-2 / C-3 / G-6）----


def make_png_with_ui(path: Path, graph: dict, *, color=(40, 60, 90)) -> Path:
    """`prompt` と `workflow` の**両方**を持つ PNG（`api+ui`。監査 C-3）。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    im = Image.new("RGB", (48, 64), color)
    info = PngImagePlugin.PngInfo()
    info.add_text("prompt", json.dumps(graph))
    info.add_text("workflow", json.dumps({"nodes": [], "links": []}))
    im.save(path, pnginfo=info)
    return path


def test_no_comfyui_means_graph_only_and_inspected_false(tmp_path):
    """監査 A-1: **繋がらないときはグラフだけで判定**し、`inspected=false` を残す。

    - 前の版は全 `class_type` の `/object_info` を引き続けて **1 枚 20〜32 秒**かかり、
      `node_missing` を並べて **`impossible`** にしていた（設計 §0.8 に反する）。
    - **`object_info` を 1 回も呼ばない**こと（打ち切り）を `calls` で見る。
    """
    store = Store(tmp_path / "data")
    probe = FakeProbe(stats=False)
    svc = RecipeService(store, probe_factory=lambda settings: probe)
    try:
        path = make_png(tmp_path / "images" / "down.png", PLAIN_GRAPH)
        asset_id, _ = store.register(sha256="e" * 64, path=str(path), size=path.stat().st_size,
                                     mtime_ns=path.stat().st_mtime_ns, width=48, height=64,
                                     fmt="png", meta=None, note=None)
        got = svc.record(asset_id, mode="pin_text", actor="human")
        assert got["inspected"] is False
        assert got["status"] == "exact", f"繋がらないだけで {got['status']} になった（監査 A-1）"
        assert "node_missing" not in got["reasons"], got["reasons"]
        assert probe.calls == [], f"打ち切っていない（{len(probe.calls)} 回引いた。監査 A-1）"
        # **行に残る**（監査 B-3）
        doc = svc.get(asset_id)
        assert doc["inspected"] is False
        assert any("繋がらなかった" in n for n in doc["notes"]), doc["notes"]
    finally:
        store.close()


def test_two_posts_at_once_do_not_fail(env):
    """監査 A-3: 同じ画像への同時 `POST` で 500 にしない（**1 行のまま**）。

    錠を離れて ComfyUI に聞く間に 2 本目が入るので、`INSERT` は `ON CONFLICT DO NOTHING` にして
    負けた側は読み直して返す。`IntegrityError` を投げると 500 になる（前の版）。

    **衝突を決定的に起こす**: 錠の外で ComfyUI に聞いているまさにその瞬間に、**別の接続
    （別の `Store`）から同じ画像の記録を先に入れる**。前の版は 2 本のスレッドのタイミングに
    任せていたので、**衝突の経路を通ったり通らなかったりして揺れた**
    （実測: 単独 10 回中 2 回・全体で 3 回中 2 回、落ちた。**揺れるテストは穴を隠す**）。
    """
    asset_id, _ = add_asset(env, PLAIN_GRAPH)
    real = env.probe.system_stats
    other_store = Store(env.tmp_path / "data")
    other = RecipeService(other_store, probe_factory=lambda settings: env.probe)
    fired: list[bool] = []

    def stats_with_a_competitor():
        # **1 回だけ**（相手は錠の外に居る）。`fired` が無いと自分の `record` で無限に再入する
        if not fired:
            fired.append(True)
            other.record(asset_id, mode="pin_text", actor="human")
        return real()

    env.probe.system_stats = stats_with_a_competitor
    try:
        got = env.svc.record(asset_id, mode="pin_text", actor="human")
    finally:
        env.probe.system_stats = real
        other_store.close()
    assert fired, "衝突の経路を通らなかった（相手が先に入れていない＝このテストは何も守っていない）"
    assert got["replayed"] is True, "負けた側が既存を返さなかった（500 になる経路）"
    assert len(rows(env, "SELECT * FROM recipe_record WHERE source_asset_id = ?", (asset_id,))) == 1


def test_a_deleted_graph_file_is_null_then_rebuilt(env):
    """監査 A-4: 消えたグラフは `GET` が `null`、`POST` が作り直す（§0.4 / §0.10）。"""
    asset_id, _ = add_asset(env, PLAIN_GRAPH)
    got = env.svc.record(asset_id, mode="pin_text", actor="human")
    path = Path(got["graph_path"])
    assert path.exists()
    path.unlink()
    assert env.svc.get(asset_id)["graph_path"] is None, "消えたファイルのパスを返した（監査 A-4）"
    again = env.svc.record(asset_id, mode="pin_text", actor="human")
    assert again["replayed"] is True
    assert again["graph_path"] and Path(again["graph_path"]).exists(), "作り直していない（監査 A-4）"


def test_the_graph_file_is_named_after_the_image(env):
    """監査 B-1: ファイル名は**画像の内容ハッシュ**（§2.3）。

    `recipe_hash` を名前にすると、**同じ鍵で `filename_prefix` だけ違う 2 枚目が
    1 枚目のファイルを黙って書き換える**（鍵から `filename_prefix` を除いてあるため）。
    """
    first, _ = add_asset(env, PLAIN_GRAPH, name="one.png", sha="1" * 64)
    got = env.svc.record(first, mode="pin_text", actor="human")
    assert ("1" * 64) in got["graph_path"], f"画像のハッシュが名前に入っていない: {got['graph_path']}"
    body = Path(got["graph_path"]).read_text(encoding="utf-8")

    other = clone(PLAIN_GRAPH)
    other["17"]["inputs"]["filename_prefix"] = "repro-other/seed-9"
    assert recipe_hash(other) == recipe_hash(PLAIN_GRAPH), "前提: 印だけ違う（鍵は同じ）"
    second, _ = add_asset(env, other, name="two.png", sha="2" * 64)
    env.svc.record(second, mode="pin_text", actor="human")
    assert Path(got["graph_path"]).read_text(encoding="utf-8") == body, \
        "2 枚目が 1 枚目のファイルを書き換えた（監査 B-1）"


def test_text_not_captured_only_when_the_string_is_unknown():
    """監査 B-2: **文字列が分かっている**なら `text_not_captured` を付けない。

    前の版は `has_text_encoder()` だけで見ていたので、`SamplerCustomAdvanced` のように
    `final_prompt` が埋まらない経路（`KSampler` が無い）で**リテラルでも**付いていた。
    """
    literal = clone(PLAIN_GRAPH)
    assert text_unknown(literal) is False, "リテラルの文字列を「分からない」にした（監査 B-2）"
    linked = clone(GRAPH)                     # `12` の text は `10`（StringConcatenate）→ `9`（TextGenerate）
    assert text_unknown(linked) is True, "リンク参照の文字列を「分かる」と見なした"


def test_pin_text_replay_with_the_same_token_is_200(env):
    """監査 C-2: `pin_text` に `text` を添えた再送は **200**（409 になっていた）。"""
    asset_id, _ = add_asset(env, PLAIN_GRAPH)
    first = env.svc.record(asset_id, mode="pin_text", text="1girl, classroom",
                           actor="human", client_token="tok-1")
    again = env.svc.record(asset_id, mode="pin_text", text="1girl, classroom",
                           actor="human", client_token="tok-1")
    assert again["replayed"] is True and again["recipe_id"] == first["recipe_id"]


def test_graph_kind_reports_api_plus_ui(env):
    """監査 C-3: `prompt` と `workflow` の両方がある PNG は `api+ui`（常に `api` になっていた）。"""
    path = make_png_with_ui(env.tmp_path / "images" / "both.png", PLAIN_GRAPH)
    asset_id, _ = env.store.register(sha256="3" * 64, path=str(path), size=path.stat().st_size,
                                     mtime_ns=path.stat().st_mtime_ns, width=48, height=64,
                                     fmt="png", meta=None, note=None)
    got = env.svc.record(asset_id, mode="pin_text", actor="human")
    assert got["graph_path"], "グラフを保存していない"
    assert env.svc.get(asset_id)["graph_kind"] == "api+ui", "graph_kind が api+ui になっていない（監査 C-3）"


def test_the_list_returns_summaries_only(env):
    """監査 G-6-(a): 一覧は**要約だけ**（`record` / `env` は 1 枚の口で取る）。"""
    asset_id, _ = add_asset(env, PLAIN_GRAPH)
    env.svc.record(asset_id, mode="pin_text", actor="human")
    page = env.svc.list()
    assert page["items"], "一覧が空"
    item = page["items"][0]
    assert "record" not in item and "env" not in item, "一覧が重い（監査 G-6）"
    assert item["status"] and item["recipe_hash"].startswith("sha256:")
    one = env.svc.get(asset_id)
    assert one["record"] and one["env"], "1 枚の口が要約だけになっている"
