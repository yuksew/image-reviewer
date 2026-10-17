"""書き出し（P5-1）のテスト。

設計: docs/p5-design.md §0.3（B1・B2・B3・G11）・§0.5（D5・G8）・§3.4
契約: `schemas/review-export.schema.json`（**この形に合うこと**）

- 点検 B1: 「書き出し済み」は `exported_at` / `changed_at` で決める（ファイルの mtime ではない）
- 点検 B2: 影響したまとまり ＝ 判断を書いた全画像の `group_item` の和集合
- 点検 B3: `open` なまとまりも書く（`decision` は null、未判断の `verdict` も null）
- 点検 D5: `tags` / `prompts` は既定で**鍵ごと出さない**
- `generated_at` を除いて 2 回出して同一（§3.4）

契約の検証は `_check_contract()` が行う（`jsonschema` を足さないため、契約が使う
`$ref` / `anyOf` / `oneOf` / `enum` / `const` / `required` / `additionalProperties` /
`items` / `pattern` / `type` だけを見る小さな検査）。**本物の `jsonschema` での検証**は
`uv run --no-project --with jsonschema python ...` で別に行う（作業報告を参照）。
"""

from __future__ import annotations

import json
import os
import re
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

from image_reviewer import db
from image_reviewer.export import ExportService, parse_scope
from image_reviewer.review import ReviewError, ReviewService
from image_reviewer.store import Store

SCHEMA_PATH = Path(__file__).resolve().parents[1] / "schemas" / "review-export.schema.json"


# ---- 契約の検査（jsonschema を依存に足さないための小さな実装）----


def _resolve(schema: dict, root: dict) -> dict:
    while "$ref" in schema:
        node = root
        for part in schema["$ref"][2:].split("/"):
            node = node[part]
        schema = node
    return schema


def _is_type(value, name: str) -> bool:
    if name == "object":
        return isinstance(value, dict)
    if name == "array":
        return isinstance(value, list)
    if name == "string":
        return isinstance(value, str)
    if name == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if name == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if name == "boolean":
        return isinstance(value, bool)
    if name == "null":
        return value is None
    raise AssertionError(f"知らない type: {name}")


def _check(instance, schema: dict, root: dict, path: str = "$") -> None:
    schema = _resolve(schema, root)
    if "const" in schema:
        assert instance == schema["const"], f"{path}: const"
    if "enum" in schema:
        assert instance in schema["enum"], f"{path}: {instance!r} は {schema['enum']} に無い"
    if "oneOf" in schema:
        ok = 0
        for sub in schema["oneOf"]:
            try:
                _check(instance, sub, root, path)
                ok += 1
            except AssertionError:
                pass
        assert ok == 1, f"{path}: oneOf に {ok} 個当たった"
        return
    if "anyOf" in schema:
        for sub in schema["anyOf"]:
            try:
                _check(instance, sub, root, path)
                return
            except AssertionError:
                continue
        raise AssertionError(f"{path}: anyOf のどれにも当たらない")
    types = schema.get("type")
    if types is not None:
        names = [types] if isinstance(types, str) else types
        assert any(_is_type(instance, n) for n in names), f"{path}: type {names}"
        if instance is None:
            return
    if "pattern" in schema:
        assert re.match(schema["pattern"], instance), f"{path}: pattern {schema['pattern']}"
    if isinstance(instance, dict):
        for key in schema.get("required", []):
            assert key in instance, f"{path}: required {key} が無い"
        props = schema.get("properties", {})
        if schema.get("additionalProperties") is False:
            extra = set(instance) - set(props)
            assert not extra, f"{path}: 契約に無い鍵 {extra}"
        for key, value in instance.items():
            if key in props:
                _check(value, props[key], root, f"{path}.{key}")
    if isinstance(instance, list) and "items" in schema:
        for i, value in enumerate(instance):
            _check(value, schema["items"], root, f"{path}[{i}]")


def check_contract(doc: dict) -> dict:
    """契約の形か確かめる（`jsonschema` を依存に足さないための小さな検査）。"""
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    _check(doc, schema, schema)
    return doc


# ---- 道具 ----


def add_asset(store: Store, sha: str, name: str = "a.png", **kw) -> str:
    args = {"size": 100, "mtime_ns": 1, "width": 16, "height": 16, "fmt": "png",
            "meta": None, "note": None}
    args.update(kw)
    path = store.data_dir.parent / "images" / name
    asset_id, _ = store.register(sha256=sha, path=str(path), **args)
    return asset_id


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.fixture
def env(tmp_path):
    store = Store(tmp_path / "data")
    exporter = ExportService(store, delay=3600.0, flush_on_start=False)
    review = ReviewService(store, exporter=exporter)
    try:
        yield SimpleNamespace(store=store, exporter=exporter, review=review,
                              data=store.data_dir, tmp_path=tmp_path)
    finally:
        exporter.close()
        store.close()


def decided_group(env, ids, policy="pick_one", title="まとまり"):
    return env.review.create_group(title=title, asset_ids=ids, policy=policy)


# ---- 点検 B2: 影響したまとまりのファイルだけを書く ----


def test_only_the_affected_group_files_are_written(env):
    a = add_asset(env.store, "a" * 64, "a.png")
    b = add_asset(env.store, "b" * 64, "b.png")
    ga = decided_group(env, [a])
    gb = decided_group(env, [b])

    env.exporter.flush_dirty()                       # 両方のファイルを作る
    pa, pb = env.exporter.group_path(ga["id"]), env.exporter.group_path(gb["id"])
    assert pa.exists() and pb.exists()
    before_a, before_b = pa.read_bytes(), pb.read_bytes()
    mtime_b = pb.stat().st_mtime_ns

    env.review.apply_asset(a, "keep", reason_code_id="rc.keep.favorite", actor="human")
    written = env.exporter.flush()

    assert written == [ga["id"]], "影響していないまとまりまで書いた"
    assert pb.read_bytes() == before_b, "関係ないまとまりのファイルが変わった"
    assert pb.stat().st_mtime_ns == mtime_b, "関係ないまとまりの mtime が変わった"
    assert pa.read_bytes() != before_a
    doc = read_json(pa)
    assert doc["assets"][0]["review_state"] == "kept"
    assert doc["assets"][0]["reason_label"] == "気に入った", "マスタを引いていない（点検 G8）"


def test_one_decision_dirties_every_group_sharing_the_asset(env):
    """点検 B2: 1 枚の判断でも、その画像が属する**全部**のまとまりを書く。"""
    a = add_asset(env.store, "a" * 64)
    g1 = decided_group(env, [a])
    g2 = decided_group(env, [a])
    env.exporter.flush_dirty()

    got = env.review.apply_asset(a, "keep", actor="human")
    assert sorted(got["affected_group_ids"]) == sorted([g1["id"], g2["id"]])
    assert sorted(env.exporter.flush()) == sorted([g1["id"], g2["id"]])
    for gid in (g1["id"], g2["id"]):
        assert read_json(env.exporter.group_path(gid))["assets"][0]["review_state"] == "kept"


def test_a_group_decision_dirties_the_groups_sharing_its_assets(env):
    a, b = add_asset(env.store, "a" * 64), add_asset(env.store, "b" * 64, "b.png")
    g1 = decided_group(env, [a, b])
    g2 = decided_group(env, [a], title="a だけのまとまり")
    env.exporter.flush_dirty()
    before_g2 = env.exporter.group_path(g2["id"]).read_bytes()

    got = env.review.apply_group(
        g1["id"],
        [{"asset_id": a, "verdict": "keep"},
         {"asset_id": b, "verdict": "reject", "reason_code_id": "rc.reject.other"}], actor="human")
    assert sorted(got["affected_group_ids"]) == sorted([g1["id"], g2["id"]])
    env.exporter.flush()
    assert env.exporter.group_path(g2["id"]).read_bytes() != before_g2


# ---- 監査 A1: 印はメモリではなく **DB** に置く（設計 §0.3 B1・B2）----
# `test_startup_flush_writes_a_decision_committed_before_a_crash` は
# **一度も書き出していない**まとまり（`exported_at IS NULL`）で試していたので、
# `changed_at` を動かしていなくても緑になっていた（監査 F1）。
# 下の 2 件は「一度書き出した後」に判断を入れて落とす版で、A1 を直す前は落ちる。


def test_a_single_decision_on_an_exported_group_is_flushed_at_startup(tmp_path):
    """監査 A1: **既に書き出した**まとまりへの 1 枚の判断が、遅延中に落ちても次の起動で出る。"""
    data = tmp_path / "data"
    store = Store(data)
    exporter = ExportService(store, delay=3600.0, flush_on_start=False)
    review = ReviewService(store, exporter=exporter)
    a = add_asset(store, "a" * 64)
    group = review.create_group(title="まとまり", asset_ids=[a])
    exporter.flush_dirty()                       # 一度書き出す（exported_at が入る）
    row = store.con.execute("SELECT changed_at, exported_at FROM review_group WHERE id = ?",
                            (group["id"],)).fetchone()
    assert row["exported_at"] is not None, "前提: 一度書き出せていない"
    assert row["changed_at"] <= row["exported_at"]

    review.apply_asset(a, "keep", reason_code_id="rc.keep.favorite", actor="human")
    row = store.con.execute("SELECT changed_at, exported_at FROM review_group WHERE id = ?",
                            (group["id"],)).fetchone()
    assert row["changed_at"] > row["exported_at"], \
        "1 枚の判断がまとまりの changed_at を動かしていない（監査 A1）"
    exporter.close()                             # 遅延（2 秒）の途中で落ちたのと同じ
    store.close()

    path = data / "export" / "groups" / f"{group['id']}.json"
    assert read_json(path)["assets"][0]["review_state"] == "unreviewed", "前提: まだ古いファイル"

    fresh_store = Store(data)
    fresh = ExportService(fresh_store)           # 起動時に **DB の印** で拾う
    try:
        doc = read_json(path)
        assert doc["assets"][0]["review_state"] == "kept", \
            "起動時の書き出しが漏れた（監査 A1。メモリの _pending は落ちると消える）"
        assert doc["assets"][0]["reason_label"] == "気に入った"
    finally:
        fresh.close()
        fresh_store.close()


def test_a_group_decision_dirties_other_groups_in_the_db(tmp_path):
    """監査 A1/F2: 同じ画像を含む**別の**まとまりの印も DB で動く（起動時に書き直される）。"""
    data = tmp_path / "data"
    store = Store(data)
    exporter = ExportService(store, delay=3600.0, flush_on_start=False)
    review = ReviewService(store, exporter=exporter)
    a = add_asset(store, "a" * 64)
    b = add_asset(store, "b" * 64, "b.png")
    g1 = review.create_group(title="g1", asset_ids=[a, b])
    g2 = review.create_group(title="g2（a を共有）", asset_ids=[a])
    exporter.flush_dirty()
    before_g2 = exporter.group_path(g2["id"]).read_bytes()

    review.apply_group(
        g1["id"],
        [{"asset_id": a, "verdict": "keep"},
         {"asset_id": b, "verdict": "reject", "reason_code_id": "rc.reject.other"}], actor="human")
    exporter.close()                             # 遅延の途中で落ちる（g2 はまだ古い）
    store.close()

    fresh_store = Store(data)
    fresh = ExportService(fresh_store)
    try:
        assert fresh.group_path(g2["id"]).read_bytes() != before_g2, \
            "共有するまとまりが起動時に書き直されない（監査 A1）"
        doc = read_json(fresh.group_path(g2["id"]))
        assert doc["assets"][0]["review_state"] == "kept"
    finally:
        fresh.close()
        fresh_store.close()


def test_two_decisions_in_the_same_second_both_reach_the_file(env, monkeypatch):
    """点検 B1-(b): `changed_at` が秒までだと、同じ秒に続けた判断を取りこぼす。"""
    a = add_asset(env.store, "a" * 64)
    b = add_asset(env.store, "b" * 64, "b.png")
    group = decided_group(env, [a, b])
    env.exporter.flush_dirty()
    monkeypatch.setattr(db, "now", lambda: "2026-10-15T00:00:00Z")   # 同じ秒に固定
    env.review.apply_asset(a, "keep", reason_code_id="rc.keep.favorite", actor="human")
    env.review.apply_asset(b, "keep", reason_code_id="rc.keep.as_intended", actor="human")

    row = env.store.con.execute("SELECT changed_at, exported_at FROM review_group WHERE id = ?",
                                (group["id"],)).fetchone()
    assert "." in row["changed_at"], "changed_at が秒までしか無い（点検 B1-(b)）"
    assert row["changed_at"] > row["exported_at"]
    env.exporter.flush()
    states = {x["id"]: x["review_state"]
              for x in read_json(env.exporter.group_path(group["id"]))["assets"]}
    assert states == {a: "kept", b: "kept"}


# ---- 監査 B2: 1 つのまとまりの失敗で残りを落とさない ----


def test_a_failing_group_does_not_stop_the_others_and_is_retried(env, monkeypatch):
    """監査 B2: 1 つが失敗しても残りは書かれ、失敗した ID は `_pending` に戻って再試行される。"""
    a = add_asset(env.store, "a" * 64)
    b = add_asset(env.store, "b" * 64, "b.png")
    g1 = decided_group(env, [a], title="g1")
    g2 = decided_group(env, [b], title="g2")
    env.exporter.mark(group_ids=[g1["id"], g2["id"]])
    real = env.exporter.write_group
    failed: list[str] = []

    def flaky(group_id, **options):
        if group_id == g1["id"] and not failed:
            failed.append(group_id)
            # Windows で他の道具がファイルを開いているときに起きる形の失敗
            raise PermissionError("他の道具がファイルを開いている")
        return real(group_id, **options)

    monkeypatch.setattr(env.exporter, "write_group", flaky)
    written = env.exporter.flush()
    assert written == [g2["id"]], "1 つの失敗で残りの書き出しが止まった（監査 B2）"
    assert env.exporter.group_path(g2["id"]).exists()
    assert env.exporter.pending_ids() == [g1["id"]], "失敗した分が再試行に残っていない（監査 B2）"

    # 次のタイマー（ここでは手で流す）で書ける
    assert env.exporter.flush() == [g1["id"]]
    assert env.exporter.group_path(g1["id"]).exists()
    assert env.exporter.pending_ids() == []


# ---- 監査 C1: 失敗した一時ファイルを残さない（実行込みのやり直し）----


def test_a_failed_replace_does_not_leave_a_tmp_file(env, monkeypatch):
    """監査 C1: `os.replace` が落ちても一時ファイルを残さない。

    実測では、ファイルを掴まれたまま 9.5 秒待つと `*.tmp` が 4 個増えていた
    （再試行のたびに別名で作られ、誰も消さない）。2 秒ごとに 1 個増え続ける。
    """
    a = add_asset(env.store, "a" * 64)
    group = decided_group(env, [a])
    env.exporter.mark(group_ids=[group["id"]])
    real = os.replace

    def failing(src, dst):
        raise PermissionError("他の道具がファイルを開いている")

    monkeypatch.setattr(os, "replace", failing)
    assert env.exporter.flush() == [], "失敗したのに書けたと言った"
    directory = env.exporter.group_path(group["id"]).parent
    assert list(directory.glob("*.tmp")) == [], "失敗した一時ファイルが残った（監査 C1）"
    assert env.exporter.pending_ids() == [group["id"]], "再試行に残っていない"

    monkeypatch.setattr(os, "replace", real)
    assert env.exporter.flush() == [group["id"]], "解除後に書けていない"
    assert list(directory.glob("*.tmp")) == [], "成功した後も一時ファイルが残った"


def test_stale_tmp_files_are_cleaned_at_startup(env):
    """監査 C1: 起動時（`flush_dirty()`）に、過去に残った一時ファイルを片づける。

    監査 F2: **`flush_dirty()` を通して**確かめる（`clean_stale_tmp()` を直接呼ぶと、
    `flush_dirty()` の先頭の呼び出しを消しても緑のままになる）。
    """
    a = add_asset(env.store, "a" * 64)
    group = decided_group(env, [a])
    env.exporter.flush_dirty()
    keep = env.exporter.group_path(group["id"])
    stale = keep.parent / f"{keep.name}.999.888.tmp"
    stale.write_text("{}", encoding="utf-8")

    env.exporter.flush_dirty()                      # 起動と同じ経路
    assert not stale.exists(), "起動の経路で残った一時ファイルを消していない（監査 C1）"
    assert keep.exists(), "本体まで消した"
    assert env.exporter.clean_stale_tmp() == 0, "消し残しがある"


# ---- 監査 C9: 理由の改名も契約ファイルに届く ----


def test_reason_codes_are_only_the_ones_the_document_uses(env):
    """監査 C1: `reason_codes` は**その文書が参照する理由だけ**（全マスタを載せない）。

    全マスタを載せると、改名したときに「参照していないまとまりのファイル」だけが旧名を
    持ち続け、どのファイルを読んだかで同じ id の名前が食い違う（改名が印を付けるのは
    参照しているまとまりだけ。§0.3 の C9）。
    """
    a = add_asset(env.store, "a" * 64)
    group = decided_group(env, [a])
    env.review.apply_asset(a, "keep", reason_code_id="rc.keep.favorite", actor="human")
    env.exporter.flush()

    doc = read_json(env.exporter.group_path(group["id"]))
    ids = {row["id"] for row in doc["reason_codes"]}
    assert "rc.keep.favorite" in ids, "参照している理由がマスタに無い"
    assert ids == {"rc.keep.favorite"}, f"参照していない理由まで載せている（監査 C1）: {sorted(ids)}"
    # 参照は解決できる（`reason_label` も契約にある）
    assert doc["assets"][0]["reason_label"] == "気に入った"


def test_renaming_a_reason_code_touches_the_groups_that_use_it(env):
    """監査 C9: 改名したら、参照しているまとまりに印を付けて書き直す。

    実行での再現: 改名して 3 秒待っても `changed_at` は動かず、`groups/<id>.json` の
    `reason_label` は**旧名のまま**だった（他ツールは次に誰かがそのまとまりに触るまで
    旧名を読む）。契約の `reason_label` は「書き出し時点のマスタ」（点検 G8）。
    """
    a = add_asset(env.store, "a" * 64)
    group = decided_group(env, [a])
    env.review.apply_asset(a, "keep", reason_code_id="rc.keep.favorite", actor="human")
    env.exporter.flush()
    path = env.exporter.group_path(group["id"])
    before = read_json(path)
    assert any(row["reason_label"] == "気に入った" for row in before["assets"]), \
        "前提が崩れている（rc.keep.favorite の表示名）"

    env.review.patch_reason_code("rc.keep.favorite", {"label": "いちばん好き"})

    row = env.store.con.execute(
        "SELECT changed_at, exported_at FROM review_group WHERE id = ?", (group["id"],)).fetchone()
    assert row["exported_at"] is None or row["changed_at"] > row["exported_at"], \
        "改名が印になっていない（監査 C9）"
    assert env.exporter.flush() == [group["id"]], "改名で書き直していない（監査 C9）"
    after = read_json(path)
    assert any(row["reason_label"] == "いちばん好き" for row in after["assets"]), \
        "契約ファイルが新しい理由名になっていない（監査 C9）"


# ---- 監査 B3: 書き出しは取引の**途中**の行を読まない ----


def test_the_exporter_is_never_notified_inside_a_transaction(env, monkeypatch):
    """監査 B3 の前提: 書き出しの呼び出し（`mark`）は**取引の外**にある。

    中にあると、錠の取り方が逆向きになり、書き出しと判断が互いを待つ（設計 §4 も
    「書き出しは取引の外で遅延させる」と言う）。
    """
    a = add_asset(env.store, "a" * 64)
    group = decided_group(env, [a])
    seen: list[bool] = []

    def mark(**kw):
        seen.append(env.store.con.in_transaction)
        return []

    monkeypatch.setattr(env.exporter, "mark", mark)
    env.review.apply_asset(a, "keep", actor="human")
    env.review.apply_group(group["id"], [{"asset_id": a, "verdict": "keep"}], actor="human")
    env.review.reopen(group["id"], actor="human")
    env.review.create_group(title="g2", asset_ids=[a])
    assert seen == [False, False, False, False], \
        "取引の中で書き出しを呼んでいる（監査 B3。錠の向きが逆になる）"


def test_an_export_never_sees_uncommitted_rows(tmp_path):
    """監査 B3: 同じ 1 本の接続を共有しているので、錠を取らないと
    `ROLLBACK` される判断が契約ファイルに残る（書き出しは Timer のスレッドで走る）。"""
    data = tmp_path / "data"
    store = Store(data)
    exporter = ExportService(store, delay=3600.0, flush_on_start=False)
    review = ReviewService(store, exporter=exporter)
    a = add_asset(store, "a" * 64)
    group = review.create_group(title="まとまり", asset_ids=[a])

    started = threading.Event()
    release = threading.Event()

    def half_open_transaction():
        """判断の取引の「途中」（行は入ったが写しはまだ）を作り、最後に ROLLBACK する。"""
        try:
            with store.transaction() as con:
                con.execute(
                    "INSERT INTO decision(id, seq, subject_type, subject_id, verdict, actor,"
                    " created_at) VALUES (?,?,?,?,?,?,?)",
                    (db.ulid(), db.next_seq(con), "asset", a, "keep", "human", db.now()))
                con.execute("UPDATE asset SET review_state = 'kept', reviewed_by = 'human'"
                            " WHERE id = ?", (a,))
                started.set()
                release.wait(10)
                raise RuntimeError("この取引は ROLLBACK される")
        except RuntimeError:
            pass

    doc: dict = {}

    def do_export():
        doc.update(exporter.build(f"group:{group['id']}"))

    writer = threading.Thread(target=half_open_transaction, daemon=True)
    writer.start()
    assert started.wait(10), "取引を開けなかった"
    reader = threading.Thread(target=do_export, daemon=True)
    reader.start()
    reader.join(0.5)
    blocked = reader.is_alive()          # 錠が効いていれば、取引が終わるまで待たされる
    release.set()
    writer.join(10)
    reader.join(10)
    try:
        assert blocked, "書き出しが取引の途中で走った（錠を取っていない。監査 B3）"
        assert not reader.is_alive()
        assert doc["assets"][0]["review_state"] == "unreviewed", \
            "未コミット（後に ROLLBACK される）判断が書き出しに出た（監査 B3）"
        assert doc["groups"][0]["items"][0]["verdict"] is None
    finally:
        release.set()
        exporter.close()
        store.close()


# ---- 点検 B1: 遅延中に落ちても、開始後に入った変更は残る ----


def test_a_change_during_the_export_stays_dirty(env, monkeypatch):
    a = add_asset(env.store, "a" * 64)
    group = decided_group(env, [a])
    original = env.exporter.build

    def build_with_a_change(scope, **options):
        doc = original(scope, **options)
        if scope == f"group:{group['id']}":
            # 書き出しの**最中**に同じまとまりが変わった状況を作る
            with env.store.transaction() as con:
                con.execute("UPDATE review_group SET changed_at = ? WHERE id = ?",
                            (db.stamp(), group["id"]))
        return doc

    monkeypatch.setattr(env.exporter, "build", build_with_a_change)
    env.exporter.write_group(group["id"])
    dirty = env.store.con.execute(
        "SELECT count(*) AS n FROM review_group"
        " WHERE exported_at IS NULL OR changed_at > exported_at").fetchone()["n"]
    assert dirty == 1, "開始後に入った変更を書き出し済みにしてしまった"


def test_startup_flush_writes_a_decision_committed_before_a_crash(tmp_path):
    """COMMIT の直後に落ちても、次回の起動で書き出しが出る（§4 の主張そのもの）。"""
    data = tmp_path / "data"
    store = Store(data)
    exporter = ExportService(store, delay=3600.0, flush_on_start=False)
    review = ReviewService(store, exporter=exporter)
    a = add_asset(store, "a" * 64)
    group = review.create_group(title="まとまり", asset_ids=[a])
    review.apply_asset(a, "keep", reason_code_id="rc.keep.favorite", actor="human")
    exporter.close()                     # 落ちたのと同じ（書き出さない）
    store.close()

    path = data / "export" / "groups" / f"{group['id']}.json"
    assert not path.exists(), "遅延が効いていない（落ちる前に書いてしまった）"

    fresh_store = Store(data)
    fresh = ExportService(fresh_store)    # 起動時に溜まっている分を書く
    try:
        assert path.exists(), "起動時の書き出しが漏れた"
        doc = read_json(path)
        assert doc["assets"][0]["review_state"] == "kept"
        assert doc["assets"][0]["reason_label"] == "気に入った"
    finally:
        fresh.close()
        fresh_store.close()


# ---- 点検 B3・契約: open なまとまりも書く ----


def test_open_group_is_exported_as_null_verdicts_and_validates(env):
    a, b = add_asset(env.store, "a" * 64), add_asset(env.store, "b" * 64, "b.png")
    group = decided_group(env, [a, b])
    # 片方だけ判断して、まとまりは open のまま
    env.review.apply_asset(b, "reject", reason_code_id="rc.reject.character", actor="human")

    doc = env.exporter.build(f"group:{group['id']}")
    check_contract(doc)
    got = doc["groups"][0]
    assert got["state"] == "open"
    assert got["decision"] is None, "open なのに結論を出した（点検 B3）"
    assert got["selected_asset_ids"] == []
    items = {i["asset_id"]: i for i in got["items"]}
    assert items[a]["verdict"] is None and items[a]["group_decision"] is None
    assert items[b]["verdict"] == "reject" and items[b]["group_decision"] is None
    assert items[b]["reason_label"] == "キャラが違う（別人化）"
    # 契約の上で `kind` は required では無いので、必ず出すことを固定する（点検 A1）
    assert all("kind" in item for item in doc["assets"])
    assert "path_map" not in doc, "パスの持ち方が 2 つある（点検 C14）"
    check_contract(env.exporter.build("all"))
    check_contract(env.exporter.build(f"asset:{a}"))


def test_decided_group_export_maps_one_to_one(env):
    a, b = add_asset(env.store, "a" * 64), add_asset(env.store, "b" * 64, "b.png")
    group = decided_group(env, [a, b])
    env.review.apply_group(
        group["id"],
        [{"asset_id": a, "verdict": "keep", "reason_code_id": "rc.keep.as_intended"},
         {"asset_id": b, "verdict": "reject", "reason_code_id": "rc.reject.breakdown",
          "note": "右腕が溶けている"}], note="狙いどおり", actor="human")
    doc = check_contract(env.exporter.build("all"))
    got = doc["groups"][0]
    assert got["decision"] == "selected"
    assert got["selected_asset_ids"] == [a]
    assert got["reason_code_id"] == "rc.keep.as_intended" and got["reason_label"] == "意図どおり"
    assert got["note"] == "狙いどおり"
    items = {i["asset_id"]: i for i in got["items"]}
    assert items[a]["verdict"] == "keep" and items[a]["group_decision"] == "selected"
    assert items[b]["group_decision"] == "not_selected" and items[b]["note"] == "右腕が溶けている"
    # 他ツールが 1 回の読み取りで「どのまとまりの、どの 1 枚か」を分かる
    assert [x["id"] for x in doc["assets"] if x["review_state"] == "kept"] == got["selected_asset_ids"]


def test_all_rejected_group_export(env):
    a, b = add_asset(env.store, "a" * 64), add_asset(env.store, "b" * 64, "b.png")
    group = decided_group(env, [a, b], policy="all_reject_only")
    env.review.apply_group(
        group["id"],
        [{"asset_id": a, "verdict": "reject", "reason_code_id": "rc.reject.other"},
         {"asset_id": b, "verdict": "reject", "reason_code_id": "rc.reject.expression"}],
        group_reason_code_id="rc.reject.intent", actor="human")
    doc = check_contract(env.exporter.build(f"group:{group['id']}"))
    got = doc["groups"][0]
    assert got["decision"] == "all_rejected" and got["selected_asset_ids"] == []
    assert got["reason_label"] == "意図・場面と違う"
    assert {i["group_decision"] for i in got["items"]} == {"all_rejected"}


# ---- 決定性（§3.4）----


def test_two_exports_differ_only_in_generated_at(env):
    a, b = add_asset(env.store, "a" * 64), add_asset(env.store, "b" * 64, "b.png")
    group = decided_group(env, [a, b])
    env.review.apply_group(
        group["id"],
        [{"asset_id": a, "verdict": "keep"},
         {"asset_id": b, "verdict": "reject", "reason_code_id": "rc.reject.other"}], actor="human")
    first = env.exporter.build("all")
    second = env.exporter.build("all")
    first.pop("generated_at")
    second.pop("generated_at")
    assert json.dumps(first, ensure_ascii=False, sort_keys=False) == \
        json.dumps(second, ensure_ascii=False, sort_keys=False)

    path = env.exporter.write_all()
    one = read_json(path)
    env.exporter.write_all()
    two = read_json(path)
    assert one.pop("generated_at") and two.pop("generated_at")
    assert one == two
    # ファイルは `<data>/export/review.json`（§3.4）
    assert path == env.data / "export" / "review.json"


# ---- 点検 D5: tags / prompts は既定で鍵ごと出さない ----


def test_tags_and_prompts_are_omitted_by_default(env):
    a = add_asset(env.store, "a" * 64, meta={"model": "m", "ja_text": "日本語", "en_text": "en",
                                             "en_source": "comfyui_history", "seed": "1"})
    plain = env.exporter.build("all")
    assert "tags" not in plain["assets"][0], "include_tags=false で鍵が出ている（点検 D5）"
    assert "prompts" not in plain["assets"][0]

    full = env.exporter.build("all", include_tags=True, include_prompts=True, include_paths=True)
    check_contract(full)
    got = full["assets"][0]
    assert got["tags"] == []                       # タグは P4 まで空（点検 D5）
    assert got["prompts"]["ja_text"] == "日本語"
    assert got["prompts"]["en_source"] == "comfyui_history"
    assert got["prompts"]["en_is_rederived"] is False
    # パスは locations[] に一本化（点検 C14）。`path_map` は出さない
    assert "path_map" not in full
    assert got["locations"][0]["path"].endswith("a.png")
    assert got["locations"][0]["kind"] == "reference"
    assert got["locations"][0]["missing"] is False
    # include_paths=false でも鍵は在って null（契約の description）
    assert plain["assets"][0]["locations"] is None


# ---- 大きい seed（点検 C15）----


def test_a_64bit_seed_survives_as_a_string(env):
    big = "18446744073709551615"
    a = add_asset(env.store, "a" * 64, meta={"model": "m", "seed": big, "steps": 10, "cfg": 1.0})
    doc = env.exporter.build("all")
    assert doc["assets"][0]["provenance"]["seed"] == big
    assert isinstance(doc["assets"][0]["provenance"]["seed"], str)
    env.exporter.write_all()
    text = env.exporter.all_path().read_text(encoding="utf-8")
    assert f'"seed": "{big}"' in text, "数値に落ちて丸められた"
    check_contract(doc)


# ---- scope の口（点検 G11）----


def test_scope_group_and_asset_do_not_write_files(env):
    a = add_asset(env.store, "a" * 64)
    group = decided_group(env, [a])
    assert parse_scope("all") == ("all", None)
    assert parse_scope("group:g1") == ("group", "g1")
    assert parse_scope(f"asset:{a}") == ("asset", a)
    with pytest.raises(ReviewError):
        parse_scope("folder:x")

    doc = env.exporter.build(f"asset:{a}")
    check_contract(doc)
    # 契約の `scope.kind` に `asset` を足した（点検 G11）。**範囲を省かない**
    # （以前は契約に語が無いので鍵ごと省いていた。嘘の範囲を書かないための回避策だった）
    assert doc["scope"] == {"kind": "asset", "id": a}
    assert [x["id"] for x in doc["assets"]] == [a]
    assert [g["id"] for g in doc["groups"]] == [group["id"]]
    assert not (env.data / "export").exists(), "asset の書き出しがファイルを作った（点検 G11）"

    with pytest.raises(ReviewError) as got:
        env.exporter.build("group:nope")
    assert got.value.status == 404


def test_every_scope_carries_its_range(env):
    """`scope` はどの口でも出る（`all` は `id: null`、`group` / `asset` は対象の id）。"""
    a = add_asset(env.store, "a" * 64)
    group = decided_group(env, [a])

    assert env.exporter.build("all")["scope"] == {"kind": "all", "id": None}
    assert env.exporter.build(f"group:{group['id']}")["scope"] == {"kind": "group", "id": group["id"]}
    assert env.exporter.build(f"asset:{a}")["scope"] == {"kind": "asset", "id": a}


def test_a_cli_command_flushes_what_the_db_marks_dirty(tmp_path, monkeypatch):
    """監査 A1: `serve` 以外のコマンド（`scan` など）でも、起動時に **DB の印**で書き出す。

    `cli` は `app.data_dir` を読むときに `app` モジュールを読み込み、その時点で
    `create_app()` が起動時の書き出しを走らせる（点検 C1 の副作用）。
    C1 を直すときは、CLI 側に**明示の**起動時 flush を足すこと（この検査がそれを教える）。
    """
    from image_reviewer.cli import main as cli_main

    data = tmp_path / "data"
    root = tmp_path / "root"
    root.mkdir(parents=True, exist_ok=True)
    store = Store(data)
    exporter = ExportService(store, delay=3600.0, flush_on_start=False)
    review = ReviewService(store, exporter=exporter)
    a = add_asset(store, "a" * 64)
    group = review.create_group(title="まとまり", asset_ids=[a])
    review.apply_asset(a, "keep", reason_code_id="rc.keep.favorite", actor="human")
    exporter.close()                             # 遅延の途中で落ちたのと同じ
    store.close()

    path = data / "export" / "groups" / f"{group['id']}.json"
    assert not path.exists(), "前提: まだ書き出していない"
    monkeypatch.setenv("IMAGE_REVIEWER_DATA", str(data))
    assert cli_main(["scan", "--root", str(root)]) == 0
    assert path.exists(), "CLI の起動時に DB の印で書き出していない（監査 A1）"
    assert read_json(path)["assets"][0]["review_state"] == "kept"


def test_shutdown_flushes_what_is_still_pending(tmp_path, monkeypatch):
    """監査 A1: 普通に終了しても、溜まっていた分が書き出される（`Timer` は daemon なので
    何もしないと消える）。`create_app()` の lifespan の終了側で `flush()` する。"""
    monkeypatch.setenv("IMAGE_REVIEWER_DATA", str(tmp_path / "data"))
    from fastapi.testclient import TestClient

    from image_reviewer.app import create_app

    app = create_app()
    human = {"X-Image-Reviewer-Actor": "human"}
    with TestClient(app, base_url="http://127.0.0.1") as client:
        a = add_asset(app.state.store, "a" * 64)
        group = client.post("/api/groups", json={"asset_ids": [a]}).json()
        app.state.export.flush()                 # 一度書き出す（既に書き出したまとまり）
        path = app.state.export.group_path(group["id"])
        assert read_json(path)["assets"][0]["review_state"] == "unreviewed"

        client.post("/api/reviews", json={"subject_type": "asset", "subject_id": a,
                                          "verdict": "keep"}, headers=human)
        # 遅延（既定 2 秒）の中。ここで抜ける = サーバの終了
        assert read_json(path)["assets"][0]["review_state"] == "unreviewed", "前提: まだ遅延中"

    assert read_json(path)["assets"][0]["review_state"] == "kept", \
        "終了時の書き出しが無い（監査 A1）"


def test_export_endpoint_shape_with_a_client(tmp_path, monkeypatch):
    monkeypatch.setenv("IMAGE_REVIEWER_DATA", str(tmp_path / "data"))
    from fastapi.testclient import TestClient

    from image_reviewer.app import create_app

    app = create_app()
    human = {"X-Image-Reviewer-Actor": "human"}
    with TestClient(app, base_url="http://127.0.0.1") as client:
        a = add_asset(app.state.store, "a" * 64)
        group = client.post("/api/groups", json={"asset_ids": [a]}).json()
        client.post("/api/reviews", json={"subject_type": "asset", "subject_id": a,
                                          "verdict": "keep"}, headers=human)

        # まとまりのファイルは判断のたびに書かれている（遅延を明示的に流す）
        app.state.export.flush()
        path = app.state.export.group_path(group["id"])
        check_contract(read_json(path))

        got = client.get("/api/export/review.json", params={"scope": "all"})
        assert got.status_code == 200
        check_contract(got.json())
        # 監査 C8/G2: **GET は書かない**（読み出しに副作用を持たせない）
        assert not (tmp_path / "data" / "export" / "review.json").exists(), \
            "GET が全件を書いた（監査 C8/G2）"
        assert "tags" not in got.json()["assets"][0]

        # 書くのは POST（手動の書き出し）
        posted = client.post("/api/export/review.json", json={"scope": "all"},
                             headers=human)
        assert posted.status_code == 200
        check_contract(posted.json())
        assert (tmp_path / "data" / "export" / "review.json").exists(), "全件は POST で書く（§3.4）"
        # 返す文書は GET と同じ形（`generated_at` を除いて同一）
        one, two = posted.json(), got.json()
        one.pop("generated_at")
        two.pop("generated_at")
        assert one == two

        read_only = client.get("/api/export/review.json", params={"scope": f"asset:{a}"})
        assert read_only.status_code == 200
        # 読み取り専用の口でも範囲を書く（点検 G11。契約の `scope.kind` に `asset` を足した）
        assert read_only.json()["scope"] == {"kind": "asset", "id": a}
        check_contract(read_only.json())
        assert "path_map" not in read_only.json()

        assert client.get("/api/export/review.json",
                          params={"scope": "folder:x"}).status_code == 422
        schema = client.get("/api/export/review.schema.json")
        assert schema.status_code == 200
        assert schema.json()["$id"] == "urn:image-reviewer:schema:review-export"


# ---- P6-0: 要求の配列と、差し替えで閉じたまとまり（点検 D8 / A3）----


def test_the_document_carries_an_empty_requests_array(env):
    """P6-0（点検 D8）: 契約には `requests[]` が**既にある**（P5 で足した）。

    P6-0 では**空**で出し、契約を通ることを固定する（P6-1 で要求の表から埋める。
    P6 の設計 §6.1）。
    """
    a = add_asset(env.store, "a" * 64)
    decided_group(env, [a])
    doc = env.exporter.build("all")
    assert doc["requests"] == []
    check_contract(doc)


def test_superseded_groups_are_hidden_by_default(env):
    """点検 A3: 差し替えで閉じたまとまり（`superseded_by` が入った行）は**既定で出さない**。

    - `scope=all` の `groups[]` から外れる（`include_superseded=True` で出る）
    - **名指し（`scope=group:<id>`）では返す**（読むために指定しているので隠さない）
    """
    a = add_asset(env.store, "a" * 64)
    group = decided_group(env, [a])
    with env.store.transaction() as con:
        con.execute("UPDATE review_group SET superseded_by = 'r-new' WHERE id = ?",
                    (group["id"],))

    doc = env.exporter.build("all")
    assert group["id"] not in [g["id"] for g in doc["groups"]], "閉じたまとまりを出した（点検 A3）"
    check_contract(doc)

    with_all = env.exporter.build("all", include_superseded=True)
    assert group["id"] in [g["id"] for g in with_all["groups"]], "指定しても出ない"
    # 点検 B1（P6-0 の監査）: **出したときは印が載っている**こと（隠れるだけでは足りない）
    emitted = [g for g in with_all["groups"] if g["id"] == group["id"]][0]
    assert emitted["superseded_by"] == "r-new", "印を契約に出していない（点検 B1）"

    named = env.exporter.build(f"group:{group['id']}")
    assert [g["id"] for g in named["groups"]] == [group["id"]]


def test_the_two_contracts_define_the_same_annotation_shape():
    """P6 の設計 §6.2: `Annotation` は 2 つの契約で**同じ形**（写し。2 か所で別々に育てない）。

    JSON Schema は `$defs` を跨いで参照できないので写しにしている。**写しがずれたら落ちる**ように、
    説明文を除いた形（型・enum・required・additionalProperties）を突き合わせる。
    """
    root = Path(__file__).resolve().parents[1] / "schemas"
    review = json.loads((root / "review-export.schema.json").read_text(encoding="utf-8"))
    annotations = json.loads((root / "annotation-export.schema.json").read_text(encoding="utf-8"))

    def shape(node):
        if isinstance(node, dict):
            return {k: shape(v) for k, v in node.items() if k != "description"}
        if isinstance(node, list):
            return [shape(v) for v in node]
        return node

    assert shape(review["$defs"]["Annotation"]) == shape(annotations["$defs"]["Annotation"]), \
        "2 つの契約の Annotation がずれた（点検 §6.2）"
    assert annotations["$id"] == "urn:image-reviewer:schema:annotation-export"
    assert annotations["properties"]["abi"]["type"] == "string", "abi は文字列（点検 D2）"


# ---- P4-0: タグの契約（設計 §0.12 / §6.1。点検 E・§8.1-18）----


def _add_tag(store: Store, name: str, *, known: bool = True, category=0, ja: str | None = None,
             edited: int = 0) -> int:
    """タグを 1 語入れる（語釈は任意）。P4-1 のサービスが入るまでの足場。"""
    with store.transaction() as con:
        con.execute("INSERT INTO tag(name, category, category_name, known) VALUES (?,?,?,?)",
                    (name, category, "general" if category == 0 else None, 1 if known else 0))
        tag_id = con.execute("SELECT id FROM tag WHERE name = ?", (name,)).fetchone()["id"]
        if ja is not None:
            now = db.now()
            con.execute("INSERT INTO tag_gloss(tag_id, ja, source, edited, created_at, updated_at)"
                        " VALUES (?,?,?,?,?,?)", (tag_id, ja, "textgenerate", edited, now, now))
    return tag_id


def test_tags_carry_gloss_known_and_the_official_spelling(env):
    """P4-0（§8.1-18）: `include_tags=true` で `tags[]` に `gloss` / `gloss_edited` / `known` が出る。

    **契約に足した欄は実際に出す**（P6-0 の監査 B1「足したのに一度も出さない」の再発防止）。
    括弧つきの語（`rem_(re:zero)`）が**壊れない**ことも見る（点検 A-1 / G-5）。
    """
    a = add_asset(env.store, "a" * 64)
    long_hair = _add_tag(env.store, "long_hair", ja="長髪")
    rem = _add_tag(env.store, "rem_\\(re:zero\\)", category=4, ja="レム", edited=1)
    unknown = _add_tag(env.store, "looking at phone", known=False, category=None)
    now = db.now()
    with env.store.transaction() as con:
        for tag_id, source, score in ((long_hair, "png", None), (long_hair, "wd14", 0.9931),
                                      (rem, "manual", None), (unknown, "png", None)):
            con.execute("INSERT INTO asset_tag(asset_id, tag_id, score, source, tagged_at)"
                        " VALUES (?,?,?,?,?)", (a, tag_id, score, source, now))

    doc = env.exporter.build("all", include_tags=True)
    tags = doc["assets"][0]["tags"]
    # 出所ごとに 1 行（同じ語が 2 つの出所にあれば 2 行）。並びは name → source
    assert [(t["name"], t["source"]) for t in tags] == [
        ("long_hair", "png"), ("long_hair", "wd14"),
        ("looking at phone", "png"), ("rem_\\(re:zero\\)", "manual")]
    by = {(t["name"], t["source"]): t for t in tags}
    assert by[("long_hair", "wd14")]["gloss"] == "長髪"
    assert by[("long_hair", "wd14")]["gloss_edited"] is False
    assert by[("long_hair", "wd14")]["known"] is True
    assert by[("long_hair", "wd14")]["score"] == 0.9931
    assert by[("rem_\\(re:zero\\)", "manual")]["gloss_edited"] is True
    assert by[("rem_\\(re:zero\\)", "manual")]["category"] == 4
    assert by[("looking at phone", "png")]["known"] is False
    assert by[("looking at phone", "png")]["gloss"] is None
    assert by[("looking at phone", "png")]["gloss_edited"] is None   # 語釈が無ければ null
    check_contract(doc)


def test_tags_are_absent_by_default_and_deterministic(env):
    """既定（`include_tags=false`）では **`tags` の鍵ごと出さない**（点検 D5）。決定性も見る。"""
    a = add_asset(env.store, "a" * 64)
    tag_id = _add_tag(env.store, "1girl", ja="1人娘")
    now = db.now()
    with env.store.transaction() as con:
        con.execute("INSERT INTO asset_tag(asset_id, tag_id, score, source, tagged_at)"
                    " VALUES (?,?,?,'wd14',?)", (a, tag_id, 0.99, now))

    off = env.exporter.build("all")
    assert "tags" not in off["assets"][0], "既定で tags を出した（点検 D5）"
    check_contract(off)

    one = env.exporter.build("all", include_tags=True)     # ★契約の検証は本物でも別に行う
    two = env.exporter.build("all", include_tags=True)
    one.pop("generated_at"), two.pop("generated_at")
    assert one == two, "2 回出して違う（決定性。§6.1）"
    assert one["assets"][0]["tags"][0]["gloss"] == "1人娘"


# ---- P8-0: `review.json` は**削除の欄を足さない**（設計 §6.1）----


def test_review_json_does_not_carry_deletion_fields(env):
    """P8-0: 段 1（論理削除）で `deleted_at` を立てても、**`review.json` の形は変えない**。

    理由（設計 §6.1）: 台帳は画像より長く生きる。**消した物も判断つきで出し続ける**
    （実体が無いことは既存の `missing` で表せるので欄を足す必要が無い）。
    ここを壊すと（`deleted_at` や `deletions` を載せると）、**下流の読み手が壊れる**。
    """
    a = add_asset(env.store, "a" * 64, "a.png")
    b = add_asset(env.store, "b" * 64, "b.png")
    env.review.apply_asset(a, "keep", reason_code_id="rc.keep.favorite", actor="human")

    before = env.exporter.build("all")
    check_contract(before)
    assert sorted(x["id"] for x in before["assets"]) == sorted([a, b])

    with env.store.transaction() as con:                     # 段 1（論理削除）
        con.execute("UPDATE asset SET deleted_at = ? WHERE id = ?", (db.now(), b))

    after = env.exporter.build("all")
    check_contract(after)
    assert sorted(x["id"] for x in after["assets"]) == sorted([a, b]), "消した資産が書き出しから外れた"
    text = json.dumps(after, ensure_ascii=False)
    for word in ("deleted_at", "deletion", "deleted"):
        assert word not in text, f"削除の欄が review.json に入った: {word}"
    # 判断は変わらない（**台帳を消さない**）
    # **判断は生きている**（台帳を消さない）。`deleted_at` は書き出しに載らないので、
    # 論理削除の前後で**同じ資産の辞書が完全に一致**するはず（形が変わっていないことの強い証拠）
    keep_before = [x for x in before["assets"] if x["id"] == a][0]
    keep_after = [x for x in after["assets"] if x["id"] == a][0]
    assert keep_after == keep_before, "生きている資産の書き出しが変わった"
    gone_before = [x for x in before["assets"] if x["id"] == b][0]
    gone_after = [x for x in after["assets"] if x["id"] == b][0]
    assert gone_after == gone_before, "論理削除で書き出しの形が変わった（欄を足した疑い）"
    # 契約そのものにも削除の欄が無い（**足していない**ことを固定）
    schema = SCHEMA_PATH.read_text(encoding="utf-8")
    for word in ("deleted_at", "deletion", "deleted"):
        assert word not in schema, f"review-export の契約に削除の欄が入った: {word}"
