"""背景ジョブ（タグ付け）のテスト（P4-1）。

設計: docs/p4-design.md §0.3（ワーカーは 1 本）・§0.11（再開と「付いている語を飛ばす」）・
§3.2（受付の検査）・§3.3（進行）・§4.1（状態）・点検 C-4 / C-5・§I-1

**模型（ComfyUI）は呼ばない**: タガーは差し替える（`tagger.build` を monkeypatch）。
実機の線 1・8 は `tools/probe_p4.py` で出す（設計 §8.4）。

> 注: このファイルは 2026-10-16 に**書き直した**（作業中のエンコーディング事故で本文が壊れたため）。
> **docstring は元の文面**（`.pyc` から取り出したもの）を使い、本文は同じ検査を組み直した。
"""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from image_reviewer import db, tagger
from image_reviewer.jobs import JobService
from image_reviewer.review import ReviewError
from image_reviewer.store import Store
from image_reviewer.tagger import png_words


# ---- 道具 ----


def add_asset(store: Store, sha: str, name: str = "a.png", **kw) -> str:
    """合成の 1 枚を登録する（実データに依存しない）。"""
    args = {"size": 100, "mtime_ns": 1, "width": 16, "height": 16, "fmt": "png",
            "meta": None, "note": None}
    args.update(kw)
    path = store.data_dir.parent / "images" / name
    asset_id, _ = store.register(sha256=sha, path=str(path), **args)
    return asset_id


def write_csv(path: Path, names: list[tuple[str, str]]) -> Path:
    """WD14 の `selected_tags.csv` の形（`id,name,category,count`）を作る。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        handle.write("id,name,category,count\n")
        for index, (name, category) in enumerate(names):
            handle.write(f"{index},{name},{category},0\n")
    return path


class FakeTagger:
    """模型の代わり。**呼ばれた回数**と**渡された名前**を覚える（点検 A-2-3 の検査）。"""

    name = "comfyui"

    def __init__(self, words, *, fail_on: set[str] | None = None):
        self.words = list(words)
        self.fail_on = fail_on or set()
        self.calls: list[str] = []
        self.names: list[str] = []

    def tag(self, image_path, *, name: str):
        self.calls.append(str(image_path))
        self.names.append(name)
        # 渡ってくる名前は **`<asset_id>-<sha256 の先頭 8>`**（点検 A-2-5）なので、前置きで照合する
        if any(name.startswith(one) for one in self.fail_on) or str(image_path) in self.fail_on:
            raise ReviewError(409, "実体が見つかりません", details={"asset_id": name})
        return list(self.words)


@pytest.fixture
def env(tmp_path, monkeypatch):
    """CSV を 1 つ置き、`tagger` の検出と構築を差し替える（模型は呼ばない）。"""
    csv = write_csv(tmp_path / "models" / "selected_tags.csv",
                    [("1girl", "0"), ("long_hair", "0"), ("black_hair", "0"), ("hatsune_miku", "4")])
    monkeypatch.setattr(tagger, "find_csv", lambda explicit=None: csv)
    monkeypatch.setattr(tagger, "find_onnx", lambda explicit=None: None)
    store = Store(tmp_path / "data")
    jobs = JobService(store, recover=False)
    fake = FakeTagger([("1girl", 0.99), ("long_hair", 0.7), ("unknown_thing", 0.4), ("x" * 100, 0.9)])
    monkeypatch.setattr(tagger, "build", lambda store, settings, engine: fake)
    monkeypatch.setattr(tagger, "detect", lambda settings: {
        "builtin": {"available": False, "reason": "onnxruntime がありません"},
        "comfyui": {"available": True, "reason": None, "url": "http://127.0.0.1:8188",
                    "node": "illust"}})
    try:
        yield SimpleNamespace(store=store, jobs=jobs, fake=fake, csv=csv, tmp_path=tmp_path)
    finally:
        store.close()


def with_prompt(env, asset: str, prompt: str) -> None:
    env.store.set_meta(asset, {"final_prompt": prompt})


# ---- PNG の語（§0.8）----


def test_png_words_are_written_with_known_flags(env):
    """§0.8 / §0.14 Q1: PNG の語は**全部**入り、語彙にあるかが `tag.known` に入る。

    `INSERT OR IGNORE` に戻すと、あとから語彙に載った語の `known` が 0 のまま残る（§I-1）。
    """
    asset = add_asset(env.store, "a" * 64)
    with_prompt(env, asset, "1girl, long_hair, (three quarter view:1.5), masterpiece")
    got = env.jobs.start_tag(asset_ids=[asset], sources=["png"])
    result = env.jobs.wait(got["job_id"])
    assert result["state"] == "done", result
    assert result["counts"] == {"tagged": 1, "skipped": 0, "failed": 0}
    with env.store.locked() as con:
        rows = con.execute("SELECT t.name, t.known, a.source FROM asset_tag a JOIN tag t ON t.id ="
                           " a.tag_id ORDER BY t.name").fetchall()
    assert [(r["name"], r["known"], r["source"]) for r in rows] == [
        ("1girl", 1, "png"), ("long_hair", 1, "png"), ("masterpiece", 0, "png"),
        ("three_quarter_view", 0, "png")], "known の付け方が違う（語彙にあるのは 1）"


def test_over_long_fragments_are_not_written(env):
    """点検 §I-3: **長すぎる断片はタグにしない**（実データの 252 字の文を防ぐ）。

    落とした数は `note` に残す（§0.8-5「黙って捨てない」）。
    """
    asset = add_asset(env.store, "a" * 64)
    with_prompt(env, asset, "1girl, " + "b" * 200)
    result = env.jobs.wait(env.jobs.start_tag(asset_ids=[asset], sources=["png"])["job_id"])
    with env.store.locked() as con:
        names = [row["name"] for row in con.execute(
            "SELECT t.name FROM asset_tag a JOIN tag t ON t.id = a.tag_id")]
    assert names == ["1girl"], names
    assert "長すぎて落とした断片 1" in (result["note"] or ""), result["note"]


# ---- タガーの語（§0.5 / §0.11）----


def test_the_job_writes_tagger_words_with_source_and_model(env):
    """§0.5: タガーの語は `source='wd14'`・`model` つきで入る。**長すぎる語は落ちる**。"""
    asset = add_asset(env.store, "a" * 64)
    got = env.jobs.start_tag(asset_ids=[asset], sources=["wd14"], engine="comfyui")
    result = env.jobs.wait(got["job_id"])
    assert result["state"] == "done" and got["engine"] == "comfyui"
    with env.store.locked() as con:
        rows = con.execute("SELECT t.name, t.known, t.category, a.score, a.model, a.actor"
                           " FROM asset_tag a JOIN tag t ON t.id = a.tag_id"
                           " WHERE a.source = 'wd14' ORDER BY t.name").fetchall()
    assert [(r["name"], r["known"], r["score"], r["actor"]) for r in rows] == [
        ("1girl", 1, 0.99, None), ("long_hair", 1, 0.7, None), ("unknown_thing", 0, 0.4, None)], \
        "長すぎる語（100 字）が落ちていない／スコアか known の付け方が違う"
    assert rows[0]["model"] == "wd-eva02-large-tagger-v3"
    # 複製の名前は `<asset_id>-<sha256 の先頭 8>`（点検 A-2-3・A-2-5。中身が変わったら名前も変える）
    assert env.fake.names == [f"{asset}-{'a' * 8}"], env.fake.names


def test_a_second_run_skips_and_force_redo(env):
    """§0.11 / 点検 C-4: 同じ `model` の語があれば**飛ばす**。`force` で付け直す。"""
    asset = add_asset(env.store, "a" * 64)
    env.jobs.wait(env.jobs.start_tag(asset_ids=[asset], sources=["wd14"])["job_id"])
    again = env.jobs.wait(env.jobs.start_tag(asset_ids=[asset], sources=["wd14"])["job_id"])
    assert again["counts"] == {"tagged": 0, "skipped": 1, "failed": 0}, again
    assert len(env.fake.calls) == 1, "飛ばすはずが模型を呼んだ"

    forced = env.jobs.wait(env.jobs.start_tag(asset_ids=[asset], sources=["wd14"],
                                             force=True)["job_id"])
    assert forced["counts"]["tagged"] == 1 and len(env.fake.calls) == 2
    with env.store.locked() as con:
        assert con.execute("SELECT count(*) AS n FROM asset_tag WHERE source = 'wd14'"
                           ).fetchone()["n"] == 3, "force で行が二重になった"


def test_one_failure_does_not_stop_the_job(env):
    """§0.3 / 点検 C-4: **失敗は 1 件ずつ `job_item` に残す**。1 枚の失敗で job は止めない。"""
    good = add_asset(env.store, "a" * 64, "a.png")
    bad = add_asset(env.store, "b" * 64, "b.png")
    env.fake.fail_on = {bad}
    result = env.jobs.wait(env.jobs.start_tag(asset_ids=[good, bad], sources=["wd14"])["job_id"])
    assert result["state"] == "done", result
    assert result["counts"] == {"tagged": 1, "skipped": 0, "failed": 1}
    assert result["items_failed"] == [{"ref": bad, "error": "ReviewError: 実体が見つかりません"}]


def test_a_job_that_processed_nothing_fails(env):
    """§4.1: `job.state='failed'` は**1 枚も処理できなかった**ときだけ。"""
    only = add_asset(env.store, "a" * 64)
    env.fake.fail_on = {only}
    result = env.jobs.wait(env.jobs.start_tag(asset_ids=[only], sources=["wd14"])["job_id"])
    assert result["state"] == "failed" and "1 枚も付けられませんでした" in result["message"]


# ---- 受付の検査（§3.2）----


def test_start_rejects_bad_input_and_busy_workers(env, monkeypatch):
    """§3.2: 語彙の外・閾値の外・知らない id は 422。動いているワーカーがあれば 409 `job_running`。"""
    asset = add_asset(env.store, "a" * 64)
    with pytest.raises(ReviewError) as got:
        env.jobs.start_tag(asset_ids=[asset], engine="magic")
    assert got.value.status == 422
    with pytest.raises(ReviewError) as got:
        env.jobs.start_tag(asset_ids=[asset], threshold=1.5)
    assert got.value.status == 422
    with pytest.raises(ReviewError) as got:
        env.jobs.start_tag(asset_ids=[asset], sources=["nope"])
    assert got.value.status == 422
    with pytest.raises(ReviewError) as got:
        env.jobs.start_tag(asset_ids=["01MISSING"])
    assert got.value.status == 422 and got.value.details["unknown_asset_ids"] == ["01MISSING"]

    # 動いている job がある間は 409（ワーカーは 1 本）
    with env.store.transaction() as con:
        con.execute("INSERT INTO job(id, kind, state, params, progress_done, progress_total,"
                    " created_at) VALUES ('j1','tag','running','{}',1,2,?)", (db.stamp(),))
    with pytest.raises(ReviewError) as got:
        env.jobs.start_tag(asset_ids=[asset], sources=["png"])
    assert got.value.status == 409 and got.value.code == "job_running"


def test_start_reports_unavailable_taggers_and_zero_targets(env, monkeypatch):
    """§3.2 / §0.4: 使えるタガーが無ければ **409 で job を作らない**。対象 0 枚は job を作らない。"""
    asset = add_asset(env.store, "a" * 64)
    # 先に「既に付いている」状態を作る（模型を呼ばない）
    with env.store.transaction() as con:
        tag_id = JobService._ensure_tag(con, "1girl", 0, "general", 1)
        con.execute("INSERT INTO asset_tag(asset_id, tag_id, score, source, model, tagged_at)"
                    " VALUES (?,?,0.9,'wd14','wd-eva02-large-tagger-v3',?)",
                    (asset, tag_id, db.stamp(),))

    monkeypatch.setattr(tagger, "detect", lambda settings: {
        "builtin": {"available": False, "reason": "onnxruntime がありません"},
        "comfyui": {"available": False, "reason": "つながりません"}})
    with pytest.raises(ReviewError) as got:
        env.jobs.start_tag(asset_ids=[asset], sources=["wd14"])
    assert got.value.status == 409 and got.value.code == "tagger_unavailable"
    with env.store.locked() as con:
        assert con.execute("SELECT count(*) AS n FROM job").fetchone()["n"] == 0, "job を作っている"

    # 使える状態に戻すと、対象 0 枚（既に付いている）→ job は作らず total 0
    monkeypatch.setattr(tagger, "detect", lambda settings: {
        "builtin": {"available": False, "reason": "onnxruntime がありません"},
        "comfyui": {"available": True, "reason": None, "url": "http://127.0.0.1:8188",
                    "node": "illust"}})
    got = env.jobs.start_tag(sources=["wd14"])          # 既定の対象は「まだ付いていない画像」
    assert got == {"job_id": None, "total": 0, "engine": "comfyui",
                   "note": "付けるものがありません"}


def test_targets_default_to_the_untagged(env):
    """§3.2: `asset_ids` も `limit` も無いときは「**その出所の語が無い画像**」（古い順）。"""
    first = add_asset(env.store, "a" * 64, "a.png")
    second = add_asset(env.store, "b" * 64, "b.png")
    with env.store.transaction() as con:
        tag_id = JobService._ensure_tag(con, "1girl", 0, "general", 1)
        con.execute("INSERT INTO asset_tag(asset_id, tag_id, source, tagged_at)"
                    " VALUES (?,?,'png',?)", (first, tag_id, db.stamp()))
    with env.store.locked() as con:
        got = env.jobs._targets(con, asset_ids=None, sources=["png"], limit=0)
    assert got == [second], "既に png の語がある画像を対象にした"


# ---- 中断と起動時の手当て（§4.1）----


def test_cancel_marks_the_job_and_keeps_written_rows(env):
    """§4.1: 中断の印は**画像 1 枚ごと**に見る。**既に書いた語は消さない**。"""
    asset = add_asset(env.store, "a" * 64)
    with env.store.transaction() as con:
        con.execute("INSERT INTO job(id, kind, state, params, progress_done, progress_total,"
                    " created_at) VALUES ('j9','tag','running','{}',0,1,?)", (db.stamp(),))
    got = env.jobs.cancel("j9")
    assert got["state"] == "running" and got["message"] == "中断しています…"
    with env.store.locked() as con:
        assert con.execute("SELECT count(*) AS n FROM asset_tag").fetchone()["n"] == 0
    with pytest.raises(ReviewError):
        env.jobs.cancel("01MISSING")


def test_recover_marks_stale_running_jobs_as_failed(env):
    """§4.1 / 起動時の手当て: プロセスが落ちた `running` を残すと次の `POST` が 409 で塞がる。"""
    with env.store.transaction() as con:
        con.execute("INSERT INTO job(id, kind, state, params, created_at)"
                    " VALUES ('j1','tag','running','{}',?)", (db.stamp(),))
        con.execute("INSERT INTO job(id, kind, state, params, created_at)"
                    " VALUES ('j2','tag','done','{}',?)", (db.stamp(),))
    assert JobService(env.store, recover=False).recover_stale() == 1
    with env.store.locked() as con:
        states = {row["id"]: row["state"] for row in con.execute("SELECT id, state FROM job")}
    assert states == {"j1": "failed", "j2": "done"}


# ---- 監査で見つかった不具合の検査（P4-1 の監査 A-1 / B-1 / B-2）----


def test_the_model_call_happens_outside_the_transaction(env, monkeypatch):
    """監査 B-1: 取引の中で模型を待つと、その間**全部の API が待たされる**。

    直す前は `_one()` が `store.transaction()` の中で `engine.tag()` を呼んでいたので、
    錠を握ったまま秒単位で待ち、`GET` も別接続の書き込みも止まった（監査の実測: 模型 1.0 秒で
    `locked()` の待ち 801〜901 ms、別接続の `INSERT` は 2,718 ms）。
    直した後は **模型の間は錠を離す**（読む → 模型 → 短い取引で書く）。
    """
    started = threading.Event()

    class Slow(FakeTagger):
        def tag(self, image_path, *, name: str):
            started.set()
            time.sleep(0.5)
            return [("1girl", 0.9)]

    monkeypatch.setattr(tagger, "build", lambda store, settings, engine: Slow([]))
    asset = add_asset(env.store, "a" * 64)
    got = env.jobs.start_tag(asset_ids=[asset], sources=["wd14"], engine="comfyui")
    assert started.wait(5.0), "模型が呼ばれていない"

    began = time.monotonic()
    with env.store.locked() as con:              # 別の API の読み（錠は取るが取引は開かない）
        con.execute("SELECT count(*) AS n FROM asset").fetchone()
    waited = time.monotonic() - began

    result = env.jobs.wait(got["job_id"], timeout=10.0)
    assert result["state"] == "done"
    assert waited < 0.25, f"模型の間に錠が待たされた（{waited * 1000:.0f} ms）"


def test_a_queued_job_makes_the_next_start_busy(env):
    """監査 B-2: **`queued` も「忙しい」**に入れる（入れないとワーカーが 2 本走る）。

    直す前は `BUSY_STATES = ("running",)` で、job の `INSERT`（`queued`）からワーカーが
    `running` に上げるまでの窓で 2 本目が通り、**`running` が 2 つ並んだ**（監査が再現）。
    """
    asset = add_asset(env.store, "a" * 64)
    with env.store.transaction() as con:
        con.execute("INSERT INTO job(id, kind, state, created_at)"
                    " VALUES ('j-queued','tag','queued',?)", (db.stamp(),))

    with pytest.raises(ReviewError) as got:
        env.jobs.start_tag(asset_ids=[asset], sources=["png"])
    assert got.value.status == 409
    assert got.value.code == "job_running"


def test_finish_does_not_die_when_the_note_column_is_missing(env):
    """監査 A-1: 閉じる側が落ちて **`running` のまま残らない**こと。

    古い形の v5（`job.note` が無い DB）では `_finish` の `UPDATE` が `no such column: note` で
    落ち、スレッドが死んで job が `running` のまま残っていた（次の `POST` が永久に 409）。
    `note` を落として書き直す道を入れた。
    """
    asset = add_asset(env.store, "a" * 64)
    with env.store.transaction() as con:
        con.execute("INSERT INTO job(id, kind, state, created_at)"
                    " VALUES ('j1','tag','running',?)", (db.stamp(),))
        con.execute("ALTER TABLE job DROP COLUMN note")      # 古い形の v5 を作る

    env.jobs._finish("j1", "failed", "わざと")
    row = env.store.con.execute("SELECT state FROM job WHERE id = 'j1'").fetchone()
    assert row["state"] == "failed", "note 列が無いと閉じられていない（監査 A-1）"
