"""書き出しの manifest の契約（P7-0）と、`review.json` に条件を足していないこと。

設計: docs/p7-design.md §6.1（`schemas/recipe-manifest.schema.json`）・§6.2（`review.json` は変えない）・
§8.1 の 25・26・41。

`jsonschema` を依存に足さないので、ここは**小さな自前の検査**で見る（本物の `jsonschema` は
`tools/check_contract_p7.py`。P6-0 の F7「契約を検証するテストが無かった」への手当てと同じ二段構え）。

**P7-0 では manifest を書く実装がまだ無い**（書くのは P7-2）。だからここで見るのは
「契約が設計どおりの形で、**通すべき文書を通し、壊れた文書を落とす**」ことまで。
P7-2 は `manifest.json` を**実際に書いて**この契約に通すテスト（§8.1 の 26）を足す。
"""

from __future__ import annotations

import copy
import json
import re
from pathlib import Path

import pytest

from image_reviewer import db
from image_reviewer.export import ExportService
from image_reviewer.review import ReviewService
from image_reviewer.store import Store

SCHEMA_PATH = Path(__file__).resolve().parents[1] / "schemas" / "recipe-manifest.schema.json"
REVIEW_SCHEMA_PATH = Path(__file__).resolve().parents[1] / "schemas" / "review-export.schema.json"


# ---- 小さな契約検査（`jsonschema` を使わない。tests/test_export.py と同じ考え方）----


def _types(value) -> set[str]:
    if isinstance(value, bool):
        return {"boolean"}
    if isinstance(value, int):
        return {"integer", "number"}
    if isinstance(value, float):
        return {"number"}
    if isinstance(value, str):
        return {"string"}
    if isinstance(value, list):
        return {"array"}
    if isinstance(value, dict):
        return {"object"}
    if value is None:
        return {"null"}
    return {"?"}


def _resolve(schema: dict, root: dict) -> dict:
    """`$ref` を 1 段だけ解く（`#/$defs/...` しか使っていない）。"""
    seen = 0
    while "$ref" in schema:
        ref = schema["$ref"]
        assert ref.startswith("#/"), f"解けない $ref: {ref}"
        node = root
        for part in ref[2:].split("/"):
            node = node[part]
        schema = node
        seen += 1
        assert seen < 8, "`$ref` が循環している"
    return schema


def _check(instance, schema: dict, root: dict, path: str = "$") -> None:
    """契約の形か確かめる。**通すべき物を通し、壊れた物を落とす**ことだけを見る。"""
    schema = _resolve(schema, root)
    if "const" in schema:
        assert instance == schema["const"], f"{path}: const と違う（{instance!r}）"
    if "enum" in schema:
        assert instance in schema["enum"], f"{path}: enum に無い（{instance!r}）"
    if "type" in schema:
        want = schema["type"] if isinstance(schema["type"], list) else [schema["type"]]
        got = _types(instance)
        assert got & set(want), f"{path}: 型が違う（{sorted(got)} は {want} ではない）"
    if "pattern" in schema and isinstance(instance, str):
        assert re.search(schema["pattern"], instance), \
            f"{path}: pattern に合わない（{instance!r} / {schema['pattern']}）"
    if isinstance(instance, dict):
        for key in schema.get("required", []):
            assert key in instance, f"{path}: required の {key} が無い"
        props = schema.get("properties", {})
        extra = schema.get("additionalProperties", True)
        for key, value in instance.items():
            if key in props:
                _check(value, props[key], root, f"{path}.{key}")
            elif extra is False:
                raise AssertionError(f"{path}: 契約に無い鍵 {key!r}")
            elif isinstance(extra, dict):
                _check(value, extra, root, f"{path}.{key}")
    if isinstance(instance, list):
        if "minItems" in schema:
            assert len(instance) >= schema["minItems"], f"{path}: 要素が足りない"
        if "items" in schema:
            for i, value in enumerate(instance):
                _check(value, schema["items"], root, f"{path}[{i}]")


def load_schema() -> dict:
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


def check_contract(doc: dict) -> dict:
    schema = load_schema()
    _check(doc, schema, schema)
    return doc


# ---- 契約に通す文書（P7-2 が書く形。§6.1）----


def example_manifest() -> dict:
    """P7-2 が書く `manifest.json` の形（`seeds` は 2 本・印つき）。"""
    return {
        "schema": "urn:image-reviewer:schema:recipe-manifest",
        "abi": "0.1",
        "generated_at": "2026-10-16T09:00:00.123456Z",
        "attempt_id": "k3m9x2qp",
        "recipe_id": "01J8ZQ4W5N7K3M9X2QP0TVH6RB",
        "mode": "pin_text",
        "recipe_hash": "sha256:" + "a" * 64,
        "export_hashes": {"1": "sha256:" + "a" * 64, "2": "sha256:" + "b" * 64},
        "marker_skipped": None,
        "source": {
            "asset_id": "01J8ZQ4W5N7K3M9X2QP0TVH6RB",
            "sha256": "c" * 64,
            "filename": "20261010_132800_00001_.png",
            "model": "anima-base-v1.safetensors",
            "seed": "123456789012345",
            "size": 1216,
        },
        "seeds": [
            {"seed": "1", "file": "seed-1.json",
             "expected_prefix": "repro-k3m9x2qp/seed-1"},
            {"seed": "2", "file": "seed-2.json",
             "expected_prefix": "repro-k3m9x2qp/seed-2"},
        ],
        "output_dir": "C:\\ai\\ComfyUI_windows_portable\\ComfyUI\\output",
        "notes": {
            "status": "approx",
            "reasons": ["text_pinned"],
            "inspected": True,
            "instruction": "1 ファイルにつき Queue は 1 回。2 回目を押す前に seed を fixed にする",
        },
    }


def test_the_example_manifest_passes_the_contract():
    """§8.1 の 26: 契約の形（`schema` / `abi` / `mode` / `notes` / `seeds[].expected_prefix`）を通る。"""
    assert check_contract(example_manifest())["abi"] == "0.1"


def test_the_contract_itself_is_the_designed_shape():
    """契約そのものの形（設計 §6.1。**足した欄は実際に出す**の裏返し）。

    `additionalProperties: false` で、required が設計の列挙と一致すること。ここを緩めると
    「でたらめな `status` が通る」「`mode` を足すと落ちる」という前の版の誤りが戻る（点検 B-5）。
    """
    schema = load_schema()
    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    assert schema["additionalProperties"] is False
    assert schema["required"] == ["schema", "abi", "attempt_id", "recipe_id", "recipe_hash",
                                  "mode", "export_hashes", "seeds", "source", "notes"]
    assert schema["properties"]["notes"]["required"] == ["status", "reasons", "inspected",
                                                         "instruction"]
    assert schema["properties"]["seeds"]["minItems"] == 1
    assert schema["properties"]["export_hashes"]["additionalProperties"]["pattern"] == "^sha256:"
    assert schema["properties"]["mode"]["enum"] == ["pin_text", "rerun_graph", "manual_text"]


def test_a_manifest_without_a_sampler_has_one_null_seed():
    """§6.1 / G-4: **seed 無しの束でも `seeds` は空にしない**（`{"seed": null, …}` を 1 件）。

    `KSampler` の無いグラフは `seeds: []` にしたくなるが、`minItems: 1` がそれを落とす。
    読み手が「書き出しが 0 本」と「seed が無い」を区別できるようにするため。
    """
    doc = example_manifest()
    doc["seeds"] = [{"seed": None, "file": "noseed.json",
                     "expected_prefix": "repro-k3m9x2qp/noseed"}]
    doc["export_hashes"] = {"": "sha256:" + "a" * 64}
    doc["marker_skipped"] = "前提2"
    doc["notes"]["instruction"] = "保存ノードが無いので印を付けられませんでした"
    assert check_contract(doc)["seeds"][0]["seed"] is None


@pytest.mark.parametrize("name,mutate", [
    ("でたらめな status", lambda d: d["notes"].update(status="perfect")),
    ("sha256: でない export_hashes", lambda d: d["export_hashes"].update({"1": "abcdef"})),
    ("契約に無い mode", lambda d: d.update(mode="l4")),
    ("seeds が空", lambda d: d.update(seeds=[])),
    ("契約に無い鍵（recipes）", lambda d: d.update(recipes=[])),
    ("契約に無い marker_skipped", lambda d: d.update(marker_skipped="前提4")),
    ("source に sha256 が無い", lambda d: d["source"].pop("sha256")),
    ("attempt_id が 6 文字", lambda d: d.update(attempt_id="r7k2m4")),
    ("notes に inspected が無い", lambda d: d["notes"].pop("inspected")),
    ("seeds に expected_prefix が無い", lambda d: d["seeds"][0].pop("expected_prefix")),
    ("generated_at の形が違う", lambda d: d.update(generated_at="2026/10/16 09:00")),
    ("notes に契約に無い鍵", lambda d: d["notes"].update(extra="x")),
])
def test_the_contract_rejects_broken_manifests(name, mutate):
    """§8.1 の 41（点検 B-5）: **壊れた manifest は落ちる**。

    前の版の契約は `notes` に型が無く、でたらめな `status` が通った（実測）。
    ここが緩むと、manifest を読む側が「判定が 3 語のどれか」を当てにできなくなる。
    """
    doc = copy.deepcopy(example_manifest())
    mutate(doc)
    with pytest.raises(AssertionError):
        check_contract(doc)


# ---- §6.2: `review.json` は変えない（設計 §8.1 の 25）----


def recipe_keys(doc) -> list[str]:
    """文書の中に `recipes` / `presets` という**入れ物の鍵**があるか（再帰）。"""
    found = []
    if isinstance(doc, dict):
        for key, value in doc.items():
            if key in ("recipes", "presets"):
                found.append(key)
            found.extend(recipe_keys(value))
    elif isinstance(doc, list):
        for value in doc:
            found.extend(recipe_keys(value))
    return found


def test_the_review_export_contract_gains_no_recipe_or_preset_container(tmp_path):
    """§6.2 / §8.1 の 25: `review.json` は**判断の記録**。条件の入れ物を足していない。

    契約（`schemas/review-export.schema.json`）にも、**実際に書き出した文書**にも
    `recipes` / `presets` が出ないことを見る。DB に条件の行（`recipe_record` / `preset`）を
    **入れてから**書き出すので、「行があると漏れる」実装になれば落ちる。
    """
    schema = json.loads(REVIEW_SCHEMA_PATH.read_text(encoding="utf-8"))
    assert "recipes" not in schema["properties"]
    assert "presets" not in schema["properties"]
    assert "recipes" not in schema["required"] and "presets" not in schema["required"]

    store = Store(tmp_path / "data")
    exporter = ExportService(store, delay=3600.0, flush_on_start=False)
    try:
        review = ReviewService(store, exporter=exporter)
        asset_id, _ = store.register(
            sha256="d" * 64, path=str(tmp_path / "images" / "a.png"), size=100, mtime_ns=1,
            width=16, height=16, fmt="png", meta=None, note=None)
        review.create_group(title="まとまり", asset_ids=[asset_id])
        now = db.now()
        # 条件の行を**入れてから**書き出す（P7 の表がある DB で review.json を作る）
        with store.transaction() as con:
            con.execute(
                "INSERT INTO recipe_record(id, source_asset_id, mode, recipe_hash, record_json,"
                " env_snapshot, status, actor, created_at)"
                " VALUES ('rec1', ?, 'pin_text', 'sha256:x', '{}', '{}', 'exact', 'human', ?)",
                (asset_id, now))
            con.execute(
                "INSERT INTO preset(id, name, source_asset_id, record_json, actor, created_at)"
                " VALUES ('p1', 'いつもの', ?, '{}', 'human', ?)", (asset_id, now))
            con.execute(
                "INSERT INTO recipe_export_attempt(attempt_id, recipe_id, mode, export_dir,"
                " created_at) VALUES ('attempt01','rec1','pin_text','p', ?)", (now,))
            con.execute(
                "INSERT INTO recipe_export(id, attempt_id, seed, recipe_hash, graph_path, marker,"
                " created_at) VALUES ('e1','attempt01','1','sha256:x','p','m', ?)", (now,))
            con.execute(
                "INSERT INTO recipe_export_result(id, export_id, result_asset_id, matched_by,"
                " created_at) VALUES ('res1','e1', ?, 'marker', ?)", (asset_id, now))

        doc = exporter.build("all")
        assert recipe_keys(doc) == [], f"review.json に条件の入れ物が出た: {recipe_keys(doc)}"
        assert set(doc) <= set(schema["properties"]), "契約に無い鍵が出た"
        # 記録は入っているのに、判断の書き出しは 1 ビットも変わらない
        with store.transaction() as con:
            assert con.execute("SELECT count(*) AS n FROM recipe_record").fetchone()["n"] == 1
    finally:
        exporter.close()
        store.close()


def test_reproduction_in_the_contract_stays_the_place_for_the_key():
    """`review.json` の `Reproduction` は**既にある**（P7 が足す場所ではない）。

    §6.2 の「変えない」は「条件の入れ物を足さない」こと。`recipe_hash` を埋めるのは
    この既存の入れ物の中（P7-1 以降の判断）で、**新しい配列を作らない**。
    """
    schema = json.loads(REVIEW_SCHEMA_PATH.read_text(encoding="utf-8"))
    repro = schema["$defs"]["Reproduction"]["properties"]
    assert {"status", "mode", "recipe_hash", "reasons", "attempt_id", "marker", "runs"} <= set(repro)
