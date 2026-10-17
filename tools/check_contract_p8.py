"""契約 `backup-manifest` を**本物の `jsonschema`** で検証する（P8-0・P8-4）。

テストの中の自前の検査（`tests/test_backup.py` の形の確認）とは別に、**本物の実装**で通す。
使い方::

    uv run --no-sync --with jsonschema python tools/check_contract_p8.py

- スキーマ自身が draft 2020-12 として正しいか（`check_schema`）
- 見本（P8-4 の `backup` が書く形）が通るか
- **P8-4: 実際に `backup()` が書いた manifest**（合成の DB で取った物）が通るか
- **壊した物が落ちるか**（1 つずつ。見本と**実物**の両方で）
- `review.json` の契約（`review-export`）に**削除の欄を足していない**か（設計 §6.1）
"""

from __future__ import annotations

import copy
import json
import pathlib
import shutil
import sys

try:
    import jsonschema
except ImportError:                                       # pragma: no cover
    print("jsonschema が要ります: uv run --no-sync --with jsonschema python tools/check_contract_p8.py")
    raise SystemExit(2)

ROOT = pathlib.Path(__file__).resolve().parent.parent
SCHEMAS = ROOT / "schemas"
#: 実際に取った manifest を作る場所（**実データは触らない**。合成の DB だけ）
WORK = ROOT / ".tmp-audit-redo" / "p8-4" / "contract"
sys.path.insert(0, str(ROOT / "src"))

#: P8-4 の `backup` が書く形（設計 §6.2 の例）
SAMPLE = {
    "schema": "urn:image-reviewer:backup-manifest",
    "abi": "0.1",
    "app_version": "0.0.1",
    "created_at": "2026-10-17T03:00:00Z",
    "data_dir": "C:\\work\\image-reviwer\\.data",
    "includes": {"db": True, "sidecar": True, "export": True, "library": False},
    "counts": {"assets": 263, "decisions": 3, "groups": 1, "annotations": 0, "tags": 0},
    "db_sha256": "sha256:" + "a" * 64,
    "db_bytes": 1003520,
}

#: 壊し方（**通ってはいけない**）
BROKEN = [
    ("schema が違う", lambda m: m.update(schema="urn:other")),
    ("abi が違う", lambda m: m.update(abi="0.2")),
    ("created_at が形違い", lambda m: m.update(created_at="2026/10/17 03:00")),
    ("counts が欠け", lambda m: m["counts"].pop("tags")),
    ("counts が負", lambda m: m["counts"].update(assets=-1)),
    ("db_sha256 が接頭辞なし", lambda m: m.update(db_sha256="a" * 64)),
    ("db_sha256 が短い", lambda m: m.update(db_sha256="sha256:abc")),
    ("includes に db が無い", lambda m: m["includes"].pop("db")),
    ("知らない欄を足した", lambda m: m.update(unknown=True)),
    ("db_bytes が文字列", lambda m: m.update(db_bytes="1003520")),
]


def real_manifest() -> dict:
    """**実際に `backup()` が書いた manifest**（合成の DB で 1 回取る）。

    見本は「人が書いた正しい形」でしかない。**実装が出す物**を本物の `jsonschema` に
    通さないと、契約と実装がずれても気づけない（P6 の監査 B1 の教訓）。
    実データ `.data/` は開かない（合成の DB を `WORK` に作って消す）。
    """
    if WORK.exists():
        shutil.rmtree(WORK)
    WORK.mkdir(parents=True)
    from image_reviewer import db                                # noqa: PLC0415
    from image_reviewer.backup import BackupService              # noqa: PLC0415
    from image_reviewer.store import Store                       # noqa: PLC0415

    data = WORK / "data"
    store = Store(data)
    try:
        asset_id, _ = store.register(
            sha256="a" * 64, path=str(data / "x.png"), size=10, mtime_ns=1,
            width=16, height=16, fmt="png", meta={"model": "synthetic"}, note=None)
        with store.transaction() as con:
            con.execute(
                "INSERT INTO decision(id, seq, subject_type, subject_id, verdict, actor,"
                " created_at) VALUES (?,?,?,?,?,?,?)",
                (db.ulid(), db.next_seq(con), "asset", asset_id, "keep", "human", db.now()))
        svc = BackupService(store, backup_dir=WORK / "backups")
        got = svc.snapshot(manual=True)
        return got["manifest"]
    finally:
        store.close()


def main() -> int:
    ok = True
    schema = json.loads((SCHEMAS / "backup-manifest.schema.json").read_text(encoding="utf-8"))
    try:
        jsonschema.Draft202012Validator.check_schema(schema)
        print(f"OK  スキーマは draft 2020-12 として正しい（{len(schema['properties'])} の欄）")
    except Exception as exc:                              # noqa: BLE001
        ok = False
        print(f"NG  スキーマが正しくない: {exc}")

    validator = jsonschema.Draft202012Validator(schema)
    errors = sorted(validator.iter_errors(SAMPLE), key=lambda e: e.path)
    if errors:
        ok = False
        print(f"NG  見本が通らない: {[e.message for e in errors]}")
    else:
        print("OK  見本（設計 §6.2 の形）が通る")

    # **P8-4: 実装が出した manifest**（見本ではなく実物）
    try:
        actual = real_manifest()
    except Exception as exc:                              # noqa: BLE001
        ok = False
        print(f"NG  実際の manifest を取れない: {type(exc).__name__}: {exc}")
        actual = None
    if actual is not None:
        errors = sorted(validator.iter_errors(actual), key=lambda e: e.path)
        if errors:
            ok = False
            print(f"NG  実際の manifest が通らない: {[e.message for e in errors]}")
        else:
            print(f"OK  実際に `backup()` が書いた manifest が通る"
                  f"（counts={actual['counts']} / db_bytes={actual['db_bytes']}）")

    for label, mutate in BROKEN:
        for name, base in (("見本", SAMPLE), ("実物", actual)):
            if base is None:
                continue
            broken = copy.deepcopy(base)
            mutate(broken)
            if list(validator.iter_errors(broken)):
                print(f"OK  壊した物が落ちる: {label}（{name}）")
            else:
                ok = False
                print(f"NG  壊した物が通ってしまう: {label}（{name}）")

    # **`review.json` の契約に削除の欄を足していない**（設計 §6.1）
    review = json.loads((SCHEMAS / "review-export.schema.json").read_text(encoding="utf-8"))
    asset = json.dumps(review, ensure_ascii=False)
    for word in ("deleted_at", "deletion", "deleted"):
        if word in asset:
            ok = False
            print(f"NG  review-export の契約に削除の欄が入っている: {word}")
    if ok:
        print("OK  review-export の契約は変えていない（削除の欄が無い）")

    shutil.rmtree(WORK, ignore_errors=True)               # 合成の DB は残さない
    if WORK.exists():
        print(f"注意: 作業場を消せませんでした: {WORK}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
