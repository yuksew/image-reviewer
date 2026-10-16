"""P7-0 の契約検証（設計 §8.1 の 25・26・41。**本物の `jsonschema`** で見る）。

見るもの:
1. `schemas/recipe-manifest.schema.json` が **draft 2020-12 の正しいスキーマ**であること
   (`Draft202012Validator.check_schema`)
2. 書き出しの `manifest.json` の見本（設計 §6.1 の形）が**通る**こと
3. **壊した manifest が落ちる**こと（でたらめな `status`・`sha256:` でない `export_hashes`・
   契約に無い鍵・`seeds: []`・6 文字の `attempt_id` / 点検 B-5・D-12）
4. `review.json` に `recipes` / `presets` が**出ない**こと（設計 §6.2。DB に条件の行を入れてから
   書き出して、本物の `review-export` の契約にも通す）
5. DB が **v6** で、v6 の 6 表と索引があること（P7-0 の合格の線）

`<data>/recipes/<recipe_id>/<attempt_id>/manifest.json` が**実在すればそれも検証する**
（P7-2 が書くようになったら、この道具がそのまま実物の検査になる）。

使い方（`jsonschema` を依存に足さない。設計 §8.1 の 26 と同じやり方）:
    uv run --no-project --with jsonschema python tools/check_contract_p7.py

捨てる場所（既定 `.tmp-p7-0/contract`）に作り、`.data` には触らない。
"""

from __future__ import annotations

import argparse
import copy
import json
import os
import shutil
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from image_reviewer import db                                      # noqa: E402
from image_reviewer.export import ExportService                    # noqa: E402
from image_reviewer.review import ReviewService                    # noqa: E402
from image_reviewer.store import Store                             # noqa: E402

MANIFEST_SCHEMA = os.path.join(ROOT, "schemas", "recipe-manifest.schema.json")
REVIEW_SCHEMA = os.path.join(ROOT, "schemas", "review-export.schema.json")
OK = True

V6_TABLES = ("recipe_record", "recipe_export_attempt", "recipe_export",
             "recipe_export_result", "preset", "watcher_state")
V6_INDEXES = ("ux_recipe_source", "ux_recipe_token", "ix_recipe_created", "ux_attempt_token",
              "ix_attempt_recipe", "ux_export_attempt_seed",
              "ix_result_export", "ux_result_asset", "ix_preset_created")
#: **作らない索引**（点検 C-2 / G-4。主キーの前置と重なる）
V6_ABSENT_INDEXES = ("ix_export_attempt",)


def say(title: str, ok: bool, note: str = "") -> None:
    global OK
    OK = OK and ok
    # cp932 のコンソールでも落ちない字だけを使う（em dash は出さない）
    print(f"  {'OK' if ok else 'NG'}: {title}{(' - ' + note) if note else ''}")


def sample_manifest() -> dict:
    """設計 §6.1 の形（`seeds` 2 本・印つき）。**P7-2 が書く物の見本**。"""
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
        "source": {"asset_id": "01J8ZQ4W5N7K3M9X2QP0TVH6RB", "sha256": "c" * 64,
                   "filename": "20261010_132800_00001_.png", "model": "anima-base-v1.safetensors",
                   "seed": "123456789012345", "size": 1216},
        "seeds": [{"seed": "1", "file": "seed-1.json",
                   "expected_prefix": "repro-k3m9x2qp/seed-1"},
                  {"seed": "2", "file": "seed-2.json",
                   "expected_prefix": "repro-k3m9x2qp/seed-2"}],
        "output_dir": "C:\\ai\\ComfyUI_windows_portable\\ComfyUI\\output",
        "notes": {"status": "approx", "reasons": ["text_pinned"], "inspected": True,
                  "instruction": "1 ファイルにつき Queue は 1 回。2 回目を押す前に seed を"
                                 " fixed にする"},
    }


def breaks() -> list[tuple[str, dict]]:
    """落ちるべき manifest（設計 §8.1 の 41・点検 B-5）。"""
    out = []

    def add(name, fn):
        doc = copy.deepcopy(sample_manifest())
        fn(doc)
        out.append((name, doc))

    add("notes.status がでたらめ", lambda d: d["notes"].update(status="perfect"))
    add("export_hashes が sha256: でない", lambda d: d["export_hashes"].update({"1": "abcdef"}))
    add("mode が語彙の外", lambda d: d.update(mode="l4"))
    add("seeds が空", lambda d: d.update(seeds=[]))
    add("契約に無い鍵", lambda d: d.update(recipes=[]))
    add("marker_skipped が語彙の外", lambda d: d.update(marker_skipped="前提4"))
    add("source.sha256 が無い", lambda d: d["source"].pop("sha256"))
    add("attempt_id が 6 文字", lambda d: d.update(attempt_id="r7k2m4"))
    add("seeds[].expected_prefix が無い", lambda d: d["seeds"][0].pop("expected_prefix"))
    add("generated_at の形が違う", lambda d: d.update(generated_at="2026/10/16 09:00"))
    return out


def find_recipe_keys(doc) -> list[str]:
    """文書の中の `recipes` / `presets` という入れ物の鍵（再帰）。"""
    found = []
    if isinstance(doc, dict):
        for key, value in doc.items():
            if key in ("recipes", "presets"):
                found.append(key)
            found.extend(find_recipe_keys(value))
    elif isinstance(doc, list):
        for value in doc:
            found.extend(find_recipe_keys(value))
    return found


def check_manifests_on_disk(data_dir: str, validator) -> tuple[int, int]:
    """`<data>/recipes/**/manifest.json` が実在すれば検証する（P7-2 以降の実物）。"""
    root = os.path.join(data_dir, "recipes")
    found = 0
    bad = 0
    if not os.path.isdir(root):
        return (0, 0)
    for base, _dirs, files in os.walk(root):
        for name in files:
            if name != "manifest.json":
                continue
            found += 1
            path = os.path.join(base, name)
            try:
                doc = json.load(open(path, encoding="utf-8"))
            except Exception as exc:                                # noqa: BLE001
                bad += 1
                say(f"{os.path.relpath(path, data_dir)} が読めない", False, str(exc))
                continue
            errors = sorted(validator.iter_errors(doc), key=lambda e: list(e.path))
            if errors:
                bad += 1
            say(f"{os.path.relpath(path, data_dir)} が契約を通る", not errors,
                "" if not errors else f"{errors[0].json_path}: {errors[0].message}")
    return (found, bad)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default=os.path.join(ROOT, ".tmp-p7-0", "contract"),
                    help="下見の DB を作る場所。**既にある物は消さない**"
                         "（`<data>/recipes/**/manifest.json` があればそれも検証する）")
    ap.add_argument("--fresh", action="store_true",
                    help="下見の DB を作り直す（**--data の中を消す**。既定は消さない）")
    args = ap.parse_args()
    # **`--data` を丸ごと消さない**（P7-2 の実装で踏んだ: 書き出した `recipes/` ごと消えて、
    # probe の成果が消えた）。消すのは `--fresh` を付けたときだけにする
    if args.fresh and os.path.exists(args.data):
        shutil.rmtree(args.data)

    try:
        import jsonschema
        from jsonschema import Draft202012Validator
    except ImportError:
        print("jsonschema がありません。`uv run --no-project --with jsonschema python "
              "tools/check_contract_p7.py` で走らせてください。")
        return 2
    import importlib.metadata
    print(f"jsonschema {importlib.metadata.version('jsonschema')} /"
          f" schema = {os.path.basename(MANIFEST_SCHEMA)}")

    schema = json.load(open(MANIFEST_SCHEMA, encoding="utf-8"))
    validator = Draft202012Validator(schema)

    # 1. スキーマそのものが正しいか
    try:
        Draft202012Validator.check_schema(schema)
        say("manifest のスキーマが draft 2020-12 として正しい", True)
    except jsonschema.SchemaError as exc:                           # pragma: no cover
        say("manifest のスキーマが draft 2020-12 として正しい", False, str(exc))

    # 2. 見本が通るか（**`seeds[].expected_prefix` を含む**）
    doc = sample_manifest()
    errors = sorted(validator.iter_errors(doc), key=lambda e: list(e.path))
    say("見本の manifest が契約を通る", not errors,
        "" if not errors else f"{errors[0].json_path}: {errors[0].message}")
    say("見本の `abi` は文字列", isinstance(doc["abi"], str))
    # seed 無しの束（G-4）も通ること
    noseed = copy.deepcopy(doc)
    noseed["seeds"] = [{"seed": None, "file": "noseed.json",
                        "expected_prefix": "repro-k3m9x2qp/noseed"}]
    noseed["export_hashes"] = {"": "sha256:" + "a" * 64}
    noseed["marker_skipped"] = "前提2"
    errors = sorted(validator.iter_errors(noseed), key=lambda e: list(e.path))
    say("seed 無しの束（`seed: null` を 1 件）も通る", not errors,
        "" if not errors else f"{errors[0].json_path}: {errors[0].message}")

    # 3. 壊した物が落ちるか
    for name, broken in breaks():
        errors = list(validator.iter_errors(broken))
        say(f"落ちる: {name}", bool(errors),
            "" if errors else "**通ってしまった**（契約が緩い）")

    # 4. DB が v6 か（表と索引）
    store = Store(args.data)
    try:
        con = store.con
        version = con.execute("PRAGMA user_version").fetchone()[0]
        say(f"DB が v6（SCHEMA_VERSION = {db.SCHEMA_VERSION}）", version == db.SCHEMA_VERSION,
            f"user_version = {version}")
        names = {r["name"] for r in con.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'")}
        missing = set(V6_TABLES) - names
        say("v6 の 6 表がある", not missing, f"足りない: {sorted(missing)}")
        idx = {r["name"] for r in con.execute(
            "SELECT name FROM sqlite_master WHERE type = 'index'")}
        missing_idx = set(V6_INDEXES) - idx
        say(f"v6 の索引が {len(V6_INDEXES)} 本ある", not missing_idx, f"足りない: {sorted(missing_idx)}")
        extra_idx = set(V6_ABSENT_INDEXES) & idx
        say("重複索引を作っていない（点検 C-2 / G-4）", not extra_idx, f"余分: {sorted(extra_idx)}")
        got = db.integrity(con)
        say("integrity() が綺麗", got["quick_check"] == "ok"
            and got["foreign_key_violations"] == 0, json.dumps(got))
        # 何度でも同じ
        say("migrate() を 2 回呼んでも同じ", db.migrate(con) == version == db.migrate(con))

        # 5. review.json に条件を足していないか（**条件の行を入れてから**書き出す）
        exporter = ExportService(store, delay=3600.0, flush_on_start=False)
        try:
            review = ReviewService(store, exporter=exporter)
            asset_id, _ = store.register(
                sha256="e" * 64, path=os.path.join(args.data, "images", "a.png"), size=100,
                mtime_ns=1, width=16, height=16, fmt="png", meta=None, note=None)
            review.create_group(title="まとまり", asset_ids=[asset_id])
            now = db.now()
            with store.transaction() as con:
                con.execute(
                    "INSERT INTO recipe_record(id, source_asset_id, mode, recipe_hash,"
                    " record_json, env_snapshot, status, actor, created_at)"
                    " VALUES ('rec1', ?, 'pin_text', 'sha256:x', '{}', '{}', 'exact',"
                    " 'human', ?)", (asset_id, now))
                con.execute(
                    "INSERT INTO preset(id, name, source_asset_id, record_json, actor, created_at)"
                    " VALUES ('p1', 'いつもの', ?, '{}', 'human', ?)", (asset_id, now))
                con.execute(
                    "INSERT INTO recipe_export_attempt(attempt_id, recipe_id, mode, export_dir,"
                    " created_at) VALUES ('attempt01','rec1','pin_text','p', ?)", (now,))
                con.execute(
                    "INSERT INTO recipe_export(id, attempt_id, seed, recipe_hash, graph_path,"
                    " marker, created_at) VALUES ('e1','attempt01','1','sha256:x','p','m', ?)",
                    (now,))
                con.execute(
                    "INSERT INTO recipe_export_result(id, export_id, result_asset_id, matched_by,"
                    " created_at) VALUES ('res1','e1', ?, 'marker', ?)", (asset_id, now))
            review_doc = exporter.build("all")
            keys = find_recipe_keys(review_doc)
            say("review.json に recipes / presets が出ない", keys == [], f"出た: {keys}")
            review_validator = Draft202012Validator(
                json.load(open(REVIEW_SCHEMA, encoding="utf-8")))
            errors = sorted(review_validator.iter_errors(review_doc), key=lambda e: list(e.path))
            say("review.json が既存の契約（review-export）を通る", not errors,
                "" if not errors else f"{errors[0].json_path}: {errors[0].message}")
            say("条件の行は入っている（空の DB で通ったのではない）",
                store.con.execute("SELECT count(*) AS n FROM recipe_record").fetchone()[0] == 1)
        finally:
            exporter.close()
    finally:
        store.close()

    # 6. 実在する manifest があればそれも見る（P7-2 以降）
    found, bad = check_manifests_on_disk(args.data, validator)
    print(f"  --: 実在する manifest.json: {found} 件（NG {bad} 件）"
          f"{'。P7-2 で書き出すようになったらここに出る' if found == 0 else ''}")

    print("まとめ: " + ("すべて OK" if OK else "NG あり"))
    return 0 if OK else 1


if __name__ == "__main__":
    raise SystemExit(main())
