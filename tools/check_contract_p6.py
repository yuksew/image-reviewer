"""P6-1a の契約検証（設計 §8.1 の 20 と 31。**本物の `jsonschema`** で見る）。

P5 の F7（「契約を検証するテストが無かった」）の教訓で、テスト側は小さな自前検査しか
持っていない。ここは**本物の `jsonschema`** で、要求・応答・`annotations` の導出まで含めた
文書を検証する。

使い方（`jsonschema` を依存に足さない。設計 §8.1 の 20 と同じやり方）:
    uv run --no-project --with jsonschema python tools/check_contract_p6.py

捨てる場所（既定 `.tmp-p6-1a/contract`）に作り、`.data` には触らない。
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

from image_reviewer import db                                     # noqa: E402
from image_reviewer.export import ExportService                    # noqa: E402
from image_reviewer.review import ReviewService                    # noqa: E402
from image_reviewer.review_requests import ReviewRequestService     # noqa: E402
from image_reviewer.store import Store                             # noqa: E402

SCHEMA = os.path.join(ROOT, "schemas", "review-export.schema.json")
OK = True


def say(title: str, ok: bool, note: str = "") -> None:
    global OK
    OK = OK and ok
    # cp932 のコンソールでも落ちない字だけを使う（em dash は出さない）
    print(f"  {'OK' if ok else 'NG'}: {title}{(' - ' + note) if note else ''}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default=os.path.join(ROOT, ".tmp-p6-1a", "contract"))
    args = ap.parse_args()
    if os.path.exists(args.data):
        shutil.rmtree(args.data)

    try:
        import jsonschema
        from jsonschema import Draft202012Validator
    except ImportError:
        print("jsonschema がありません。`uv run --no-project --with jsonschema python "
              "tools/check_contract_p6.py` で走らせてください。")
        return 2
    import importlib.metadata
    print(f"jsonschema {importlib.metadata.version('jsonschema')} /"
          f" schema = {os.path.basename(SCHEMA)}")

    store = Store(args.data)
    try:
        exporter = ExportService(store, delay=3600.0, flush_on_start=False)
        review = ReviewService(store, exporter=exporter)
        requests = ReviewRequestService(store, review)

        asset_ids = []
        for i in range(3):
            asset_id, _ = store.register(
                sha256=f"{i:02d}" * 32, path=os.path.join(args.data, "images", f"img{i}.png"),
                size=100, mtime_ns=1, width=16, height=16, fmt="png", meta=None, note=None)
            asset_ids.append(asset_id)
        a, b, c = asset_ids

        # 1. 決定して閉じた要求（応答つき）
        done = requests.create(asset_ids=[a, b], ask="1 枚選んで", conditions=["左手の形"],
                               origin="作品A / カット03", wants=["selected_ids", "annotations"],
                               ai_pick_asset_id=a, ai_note="手が素直", target_key="cut-1",
                               actor="agent")
        group_id = done["group_id"]
        review.apply_group(group_id,
                           [{"asset_id": a, "verdict": "keep"},
                            {"asset_id": b, "verdict": "reject",
                             "reason_code_id": "rc.reject.other"}],
                           group_reason_code_id="rc.keep.favorite", actor="human")
        # 判断の後に付いた印（`response.annotations` が**読むときに導出**されること。§0.2）
        with store.transaction() as con:
            con.execute(
                "INSERT INTO annotation(id, asset_id, shape, x, y, w, h, body, actor,"
                " created_at, group_id) VALUES (?,?,'rect',0.1,0.2,0.3,0.4,?, 'human', ?, ?)",
                (db.ulid(), a, "ここが気になる", db.now(), group_id))

        # 2. 開いたままの要求（`response` は null）
        opened = requests.create(asset_ids=[c], ask="別の 1 枚", origin="作品B")
        # 3. 差し替えられた要求と、閉じた古いまとまり
        old = requests.create(asset_ids=[c], target_key="cut-2", ask="古い要求")
        new = requests.create(asset_ids=[a], target_key="cut-2", ask="新しい要求")

        validator = Draft202012Validator(json.load(open(SCHEMA, encoding="utf-8")))
        print(f"要求: done={done['request_id'][:8]}… open={opened['request_id'][:8]}… "
              f"superseded={old['request_id'][:8]}… → {new['request_id'][:8]}…")
        for scope in ("all", f"group:{group_id}", f"asset:{c}"):
            doc = exporter.build(scope)
            errors = sorted(validator.iter_errors(doc), key=lambda e: list(e.path))
            say(f"scope={scope} が契約を通る", not errors,
                "" if not errors else f"{errors[0].json_path}: {errors[0].message}")
            if scope == "all":
                all_doc = doc
                say("`requests[]` が 4 件（履歴を消さない）", len(doc["requests"]) == 4,
                    f"{len(doc['requests'])} 件")
                by_id = {r["id"]: r for r in doc["requests"]}
                closed = by_id[done["request_id"]]
                say("`response` がオブジェクト（文字列のまま出さない。点検 F11）",
                    isinstance(closed["response"], dict))
                say("閉じた要求の応答が入っている",
                    closed["state"] == "done"
                    and closed["response"]["selected_asset_ids"] == [a]
                    and closed["response"]["reason_label"] is not None,
                    json.dumps(closed["response"], ensure_ascii=False))
                say("`annotations` が読むときに導出される（判断の後でも入る）",
                    closed["response"]["annotations"] != [], str(closed["response"]["annotations"]))
                say("開いた要求の `response` は null",
                    by_id[opened["request_id"]]["response"] is None)
                say("差し替えの印（`superseded_by`）が両方に入る",
                    by_id[old["request_id"]]["superseded_by"] == new["request_id"]
                    and any(g["id"] == old["group_id"] for g in doc["groups"]) is False,
                    f"古いまとまり {old['group_id'][:8]}… は groups[] から外れている")
                say("契約の `Group.superseded_by` が出ている",
                    any(g.get("superseded_by") == new["request_id"]
                        for g in exporter.build("all", include_superseded=True)["groups"]))
        # 決定性（`generated_at` を除いて 2 回で同一。§6.1）
        first, second = exporter.build("all"), exporter.build("all")
        first.pop("generated_at"), second.pop("generated_at")
        say("`generated_at` を除いて 2 回で同一", first == second)
        # 鍵の順も固定（辞書の順が揺れると差分が出る）
        again = copy.deepcopy(exporter.build("all"))
        again.pop("generated_at")
        say("鍵の順まで同一", json.dumps(first, sort_keys=False) == json.dumps(again, sort_keys=False))
        exporter.close()
    finally:
        store.close()

    print("まとめ: " + ("すべて OK" if OK else "NG あり"))
    return 0 if OK else 1


if __name__ == "__main__":
    raise SystemExit(main())
