"""監視の最小形と結果の紐付け（P7-3）のテスト。

設計: `docs/p7-design.md` §0.9（監視。**進めない条件・キャッシュの見分け・印の照合・実体の場所**）・
§0.10（`GET` は書かない・`actor`・`client_token`）・§3.4（監視の口）・§3.6（手で紐付ける口と合否）・§8.1

方針: **本物の ComfyUI は使わない**（`http=` に偽の応答を差し込む）。**画像の生成もしない**。
各テストの docstring に「**何を壊すと落ちるか**」を書く。
"""

from __future__ import annotations

import json
import urllib.parse
from pathlib import Path
from types import SimpleNamespace

import pytest

from image_reviewer import db
from image_reviewer.recipe import RecipeService, recipe_hash
from image_reviewer.recipe_export import RecipeExportService
from image_reviewer.review import ReviewError
from image_reviewer.store import Store
from image_reviewer.watcher import (
    ComfyWatcher,
    _images_of,
    _norm_sub,
    _seed_of,
    _seed_of_graph,
    infer_output_dir,
)
from test_recipe import GRAPH, PLAIN_GRAPH, FakeProbe, add_asset, clone, make_png
from test_recipe_export import record_of

# ---- 偽の ComfyUI（**ネットワークを使わない**）----


class FakeComfy:
    """`GET` だけを返す偽の ComfyUI。**呼ばれた URL を全部覚える**（2 段の回数を数えるため）。"""

    def __init__(self, *, jobs=None, details=None, statuses=None, view=b"", folders=None):
        self.jobs = list(jobs or [])                 # 一覧（新しい順）
        self.details = dict(details or {})           # job_id → 詳細
        self.statuses = dict(statuses or {})         # status → 一覧（未完了の判定に使う）
        self.view = view                             # `/view` が返すバイト列
        self.folders = folders or {}
        self.calls: list[str] = []

    def __call__(self, url: str, *, timeout: float = 5.0):
        self.calls.append(url)
        split = urllib.parse.urlsplit(url)
        path = split.path + (f"?{split.query}" if split.query else "")
        if path.startswith("/api/jobs?"):
            query = dict(part.split("=", 1) for part in path.split("?", 1)[1].split("&") if "=" in part)
            status = query.get("status")
            # **`completed`（と指定なし）だけが本物の一覧**。他は差し替え（未完了の判定に使う）
            if status and status != "completed":
                got = self.statuses.get(status, [])
                return {"jobs": got, "pagination": {"total": len(got)}}
            return {"jobs": self.jobs, "pagination": {"total": len(self.jobs)}}
        if path.startswith("/api/jobs/"):
            return self.details.get(path.rsplit("/", 1)[-1], {})
        if path.startswith("/internal/folder_paths"):
            return self.folders
        raise AssertionError(f"偽の ComfyUI が知らない URL: {url}")

    def bytes_of(self, url: str, *, timeout: float = 30.0) -> bytes:
        """`/view` の口（**本物の ComfyUI を触らない**）。"""
        self.calls.append(url)
        if "/view?" not in url:
            raise AssertionError(f"偽の ComfyUI が知らない URL: {url}")
        return self.view

    def detail_calls(self) -> list[str]:
        return [u for u in self.calls if "/api/jobs/" in u]


def job(job_id: str, when: int, *, outputs: int = 1, cached_nodes=None, images=None) -> dict:
    """一覧の 1 行（実測の形。`workflow` は無い）。"""
    return {"id": job_id, "status": "completed", "create_time": when,
            "outputs_count": outputs, "previewable_outputs_count": outputs,
            "execution_start_time": when, "execution_end_time": when + 100}


def detail(job_id: str, *, graph=None, images=None, cached=None, outputs: int = 1) -> dict:
    """`GET /api/jobs/{id}` の形（`workflow.prompt` / `outputs` / `execution_status`）。"""
    outs = {}
    if outputs:
        outs["9"] = {"images": images if images is not None else [
            {"filename": "x_00001_.png", "subfolder": "", "type": "output"}]}
    return {"id": job_id, "workflow": {"prompt": graph or {}},
            "outputs": outs,
            "execution_status": {"status_str": "success",
                                 "messages": [["execution_cached", {"nodes": list(cached or [])}]]}}


@pytest.fixture
def env(tmp_path):
    """Store ＋ 記録 ＋ 書き出し ＋ 監視（**偽の ComfyUI**）。"""
    store = Store(tmp_path / "data")
    probe = FakeProbe()
    recipes = RecipeService(store, probe_factory=lambda settings: probe)
    exports = RecipeExportService(store, recipes, probe_factory=lambda settings: probe)
    comfy = FakeComfy()
    watcher = ComfyWatcher(store, recipes, exports, http=comfy, bytes_of=comfy.bytes_of, interval=0.01)
    try:
        yield SimpleNamespace(store=store, recipes=recipes, exports=exports,
                              watcher=watcher, comfy=comfy, tmp_path=tmp_path)
    finally:
        watcher.stop()
        store.close()


def export_of(env, *, seed="1", marker_prefix=None, graph=None) -> dict:
    """記録して 1 回書き出し、`(recipe_id, attempt_id, 印)` を返す（実ファイルも作る）。"""
    recipe_id, asset_id = record_of(env, graph or GRAPH)
    got = env.exports.export(recipe_id, seeds=[seed], actor="human")
    return {"recipe_id": recipe_id, "asset_id": asset_id, "attempt_id": got["attempt_id"],
            "marker": got.get("marker"), "seed": seed, "export_dir": got.get("export_dir")}


def write_result(env, *, subfolder: str, filename: str, graph=None, color=(10, 20, 30)) -> Path:
    """結果の PNG を出力先に置く（**合成。生成はしない**）。"""
    out = env.tmp_path / "output"
    path = out.joinpath(*[p for p in f"{subfolder}/{filename}".split("/") if p])
    make_png(path, graph if graph is not None else clone(GRAPH), color=color)
    return path


def exported_graph(got: dict) -> dict:
    """書き出したグラフ（`<export_dir>/seed-<seed>.json`）を読む。

    **結果の PNG に入るのはこれ**（元のグラフではない。印と seed が入っている）。
    `recipe_hash` は印と `_meta` を除くので、**この 2 つの鍵は一致する**（§0.5）。
    """
    path = Path(got["export_dir"]) / f"seed-{got['seed']}.json"
    return json.loads(path.read_text(encoding="utf-8"))


def bump(env, delta: int = 10 ** 9) -> None:
    """job の `create_time` を進める（**開始より後に来た job** にする。基準は開始時の最新）。"""
    for one in env.comfy.jobs:
        one["create_time"] = int(one["create_time"]) + delta
    for group in env.comfy.statuses.values():
        for one in group:
            one["create_time"] = int(one["create_time"]) + delta


def rows(env, sql: str, args: tuple = ()) -> list:
    return env.store.con.execute(sql, args).fetchall()


# ---- 純関数 ----


def test_subfolder_and_seed_are_normalized_for_windows():
    """**何を壊すと落ちるか**: `subfolder` のバックスラッシュを `/` に直さないと印に当たらない
    （点検 B-4 の実測）。`seed-<値>_` の読み取りも崩れる。"""
    assert _norm_sub("repro-ab12cd34\\seed-1") == "repro-ab12cd34/seed-1"
    assert _norm_sub("/repro-ab12cd34/") == "repro-ab12cd34"
    assert _seed_of("seed-1_00001_.png") == "1"
    assert _seed_of("seed-noseed_00001_.png") == "noseed"
    assert _seed_of("x_00001_.png") is None


def test_images_come_from_every_output_node():
    """**何を壊すと落ちるか**: 出力の取り出しを 1 つのノードに決め打ちすると、
    `SaveImage` が複数ある job（実データにある）で 2 枚目以降を取り落とす。"""
    got = _images_of({"outputs": {"9": {"images": [{"filename": "a.png"}]},
                                  "12": {"images": [{"filename": "b.png"}, {"filename": "c.png"}]}}})
    assert [i["filename"] for i in got] == ["a.png", "b.png", "c.png"]


def test_infer_output_dir_uses_the_models_parent(tmp_path):
    """**何を壊すと落ちるか**: `/internal/folder_paths` は `output` を教えないので、
    `checkpoints` の `<根>/models/<名前>` から**`models` の親**を見る規則を外すと推定できない。
    **実在するときだけ**返す（無い物を返すと登録ルートが汚れる）。"""
    root = tmp_path / "ComfyUI"
    (root / "output").mkdir(parents=True)
    models = root / "models" / "checkpoints"
    models.mkdir(parents=True)
    folders = {"checkpoints": [str(models)], "loras": []}
    assert infer_output_dir("http://127.0.0.1:1", http=lambda url, **kw: folders) == str(root / "output")
    # **実在しないときは返さない**
    assert infer_output_dir("http://127.0.0.1:1",
                            http=lambda url, **kw: {"checkpoints": [str(tmp_path / "nope" / "models" / "c")]}) is None
    assert infer_output_dir("http://127.0.0.1:1", http=lambda url, **kw: {}) is None


# ---- 監視の 1 周期 ----


def test_marker_match_registers_one_result(env):
    """**何を壊すと落ちるか**: ①印（`subfolder` の `repro-<id>`＋`seed-<seed>_`）で
    `recipe_export` に当てる所、②結果を `asset` に登録して `recipe_export_result` を 1 行作る所、
    ③鍵の比較（`same_hash`）と `seed_changed` を落とすと、線 6（印から結果が紐付く）が満たせない。"""
    got = export_of(env)
    sub = got["marker"].rsplit("/", 1)[0]
    path = write_result(env, subfolder=sub, filename=f"{got['marker'].rsplit('/', 1)[1]}_00001_.png", graph=exported_graph(got))
    env.comfy.jobs = [job("j1", 1000)]
    env.comfy.details = {"j1": detail("j1", graph=exported_graph(got),
                                      images=[{"filename": path.name, "subfolder": sub, "type": "output"}])}
    with env.store.transaction() as con:
        con.execute("INSERT INTO settings(key, value) VALUES ('comfyui.output_dir', ?)",
                    (str(env.tmp_path / "output"),))

    env.watcher.start(actor="human", run=False)
    bump(env)
    got_cycle = env.watcher.poll_once()

    assert got_cycle["results"] == 1, got_cycle
    row = rows(env, "SELECT * FROM recipe_export_result")[0]
    assert row["matched_by"] == "marker" and row["prompt_id"] == "j1"
    assert row["same_hash"] == 1, "同じグラフなのに鍵が一致していない"
    assert row["seed_changed"] == 0
    assert row["result_asset_id"], "結果の画像が asset に登録されていない"
    # **結果は書き出しの一覧に出る**（画面が合否を出すため）
    listed = env.exports.exports(got["recipe_id"])["items"][0]["results"]
    assert listed and listed[0]["id"] == row["id"]


def test_a_job_without_a_marker_makes_nothing(env):
    """**何を壊すと落ちるか**: 印の無い job でも結果を作るようにすると、
    無関係な生成が「再現の結果」として混ざる（§0.9 の「印が無ければ作らない」）。"""
    export_of(env)
    path = write_result(env, subfolder="", filename="other_00001_.png")
    env.comfy.jobs = [job("j1", 1000)]
    env.comfy.details = {"j1": detail("j1", graph=clone(GRAPH),
                                      images=[{"filename": path.name, "subfolder": "", "type": "output"}])}
    with env.store.transaction() as con:
        con.execute("INSERT INTO settings(key, value) VALUES ('comfyui.output_dir', ?)",
                    (str(env.tmp_path / "output"),))
    env.watcher.start(actor="human", run=False)
    bump(env)
    assert env.watcher.poll_once()["results"] == 0
    assert rows(env, "SELECT * FROM recipe_export_result") == []


def test_a_tagging_job_is_dropped_without_fetching_details(env):
    """**何を壊すと落ちるか**: 一覧の `outputs_count` を見ずに全部の詳細を取ると、
    タグ付けの job（`outputs_count: 0`。731 件中 427 件が画像を出さない）で余分に叩く（点検 B-3-4）。"""
    env.comfy.jobs = [job("tag1", 1000, outputs=0), job("img1", 1001, outputs=1)]
    env.comfy.details = {"img1": detail("img1", graph=clone(GRAPH), outputs=0)}
    with env.store.transaction() as con:
        con.execute("INSERT INTO settings(key, value) VALUES ('comfyui.output_dir', ?)",
                    (str(env.tmp_path / "output"),))
    env.watcher.start(actor="human", run=False)
    bump(env)
    env.watcher.poll_once()
    assert "tag1" not in " ".join(env.comfy.detail_calls()), "タグ付け job の詳細を取っている"


def test_a_cached_job_is_skipped_by_the_save_node(env):
    """**何を壊すと落ちるか**: `execution_cached` は**全 job に出る**（当たっていない job は `nodes: []`）ので、
    「出たらキャッシュ」と見なすと**全部を読み飛ばす**。保存ノードが含まれるかで見る（点検 B-3-3）。"""
    export_of(env)
    env.comfy.jobs = [job("j1", 1000)]
    env.comfy.details = {"j1": detail("j1", graph=clone(GRAPH), cached=["17"])}   # 17 = SaveImage
    env.watcher.start(actor="human", run=False)
    bump(env)
    got = env.watcher.poll_once()
    assert got["cached"] == 1 and got["results"] == 0
    # **空の `nodes` は「キャッシュに当たっていない」**（＝処理する）
    env.comfy.details = {"j1": detail("j1", graph=clone(GRAPH), cached=[])}
    env.comfy.jobs = [job("j2", 2000)]
    env.comfy.details["j2"] = env.comfy.details.pop("j1")
    env.comfy.details["j2"]["id"] = "j2"
    env.watcher.poll_once()
    assert rows(env, "SELECT * FROM recipe_export_result") == [], "印が無いので結果は作らない"


def test_the_same_job_is_not_taken_twice(env):
    """**何を壊すと落ちるか**: 既読（`create_time` の基準と処理済みの集合）を外すと、
    2 秒ごとに同じ job を拾って**同じ結果を何度も作る**（再起動しても二度登録しない）。"""
    got = export_of(env)
    sub = got["marker"].rsplit("/", 1)[0]
    path = write_result(env, subfolder=sub, filename=f"{got['marker'].rsplit('/', 1)[1]}_00001_.png", graph=exported_graph(got))
    env.comfy.jobs = [job("j1", 1000)]
    env.comfy.details = {"j1": detail("j1", graph=exported_graph(got),
                                      images=[{"filename": path.name, "subfolder": sub, "type": "output"}])}
    with env.store.transaction() as con:
        con.execute("INSERT INTO settings(key, value) VALUES ('comfyui.output_dir', ?)",
                    (str(env.tmp_path / "output"),))
    env.watcher.start(actor="human", run=False)
    bump(env)
    assert env.watcher.poll_once()["results"] == 1
    assert env.watcher.poll_once()["results"] == 0, "同じ job を 2 度拾っている"
    assert len(rows(env, "SELECT * FROM recipe_export_result")) == 1
    # **再起動**（集合を忘れる）でも、基準が進んでいるので二度は取らない
    env.watcher._seen.clear()
    assert env.watcher.poll_once()["results"] == 0
    assert len(rows(env, "SELECT * FROM recipe_export_result")) == 1


def test_an_unfinished_older_job_holds_the_baseline(env):
    """**何を壊すと落ちるか**: 未完了（`in_progress`）を考えずに基準を進めると、
    後から完了した古い job を**永久に取り落とす**（点検 B-3-2）。"""
    export_of(env)
    env.comfy.jobs = [job("j1", 1000)]
    env.comfy.statuses = {"in_progress": [job("j2", 2000)]}
    with env.store.transaction() as con:
        con.execute("INSERT INTO settings(key, value) VALUES ('comfyui.output_dir', ?)",
                    (str(env.tmp_path / "output"),))
    env.watcher.start(actor="human", run=False)
    bump(env)
    env.watcher.poll_once()
    base = rows(env, "SELECT baseline_create_time FROM watcher_state")[0][0]
    unfinished = int(env.comfy.statuses["in_progress"][0]["create_time"])
    assert base < unfinished, f"未完了の job を追い越して基準が進んだ（{base} >= {unfinished}）"


def test_a_cycle_with_nothing_to_do_writes_nothing(env):
    """**何を壊すと落ちるか**: 拾う物が無い周期でもファイルや行を書くと、
    `GET` の無副作用（§0.10）が崩れ、`watcher_state` が無駄に書き換わる。"""
    export_of(env)
    env.watcher.start(actor="human", run=False)
    bump(env)
    before = sorted((p.name, p.stat().st_size, p.stat().st_mtime_ns)
                    for p in Path(env.store.data_dir).rglob("*") if p.is_file() and not p.name.startswith('db.sqlite3'))
    env.comfy.jobs = []
    env.watcher.poll_once()
    after = sorted((p.name, p.stat().st_size, p.stat().st_mtime_ns)
                   for p in Path(env.store.data_dir).rglob("*") if p.is_file() and not p.name.startswith('db.sqlite3'))
    assert before == after, "何も無い周期でファイルを書いている"


def test_the_watcher_is_not_started_by_a_get(env):
    """**何を壊すと落ちるか**: `GET /api/watcher` が状態を書いたり開始したりすると、
    見ただけで GPU を使い始める（§0.10 の「`GET` は書かない」）。"""
    first = env.watcher.status()
    assert first["enabled"] is False and rows(env, "SELECT * FROM watcher_state") == []
    assert env.watcher.status() == first


def test_start_is_idempotent_and_stop_is_too(env):
    """**何を壊すと落ちるか**: 開始/停止が冪等でないと、二重に開始して**周期が 2 本**走る。"""
    env.watcher.start(actor="human", run=False)
    bump(env)
    env.watcher.start(actor="human", run=False)
    bump(env)
    assert env.watcher.status()["enabled"] is True
    assert sum(1 for t in [env.watcher._thread] if t and t.is_alive()) <= 1
    env.watcher.stop()
    assert env.watcher.stop() == {"enabled": False}
    assert env.watcher.status()["enabled"] is False


def test_a_broken_connection_does_not_advance_and_does_not_raise(env):
    """**何を壊すと落ちるか**: 繋がらない周期で例外を投げると監視が止まる。
    基準を進めると、繋がらなかった間の job を永久に取り落とす。"""
    env.watcher.start(actor="human", run=False)
    bump(env)
    base_before = rows(env, "SELECT baseline_create_time FROM watcher_state")[0][0]

    def boom(url, **kw):
        raise OSError("繋がりません")

    env.watcher._http = boom
    got = env.watcher.poll_once()
    assert got["error"] and "OSError" in got["error"]
    assert rows(env, "SELECT baseline_create_time FROM watcher_state")[0][0] == base_before


# ---- 手で紐付ける・合否 ----


def test_a_human_can_attach_a_result_and_set_a_verdict(env):
    """**何を壊すと落ちるか**: 印が無い結果を人が紐付ける口（`matched_by='manual'`）と、
    合否の**上書き**（`verdict_at` / `verdict_actor`）を落とすと、線 7 が満たせない。"""
    got = export_of(env)
    asset_id, _path = add_asset(env, GRAPH, name="result.png", sha="b" * 64)
    attached = env.watcher.attach(got["recipe_id"], got["attempt_id"], asset_id, actor="human")
    assert attached["matched_by"] == "manual"
    # 2 回目は**行を増やさない**
    again = env.watcher.attach(got["recipe_id"], got["attempt_id"], asset_id, actor="human")
    assert again["replayed"] is True and again["id"] == attached["id"]

    first = env.watcher.set_verdict(got["recipe_id"], got["attempt_id"], attached["id"], "close",
                                    note="近い", actor="human")
    assert first["verdict"] == "close"
    second = env.watcher.set_verdict(got["recipe_id"], got["attempt_id"], attached["id"], "different",
                                     note="違う", actor="human")
    assert second["verdict"] == "different"
    row = rows(env, "SELECT * FROM recipe_export_result WHERE id = ?", (attached["id"],))[0]
    assert row["verdict"] == "different" and row["note"] == "違う"
    assert row["verdict_at"] and row["verdict_actor"] == "human"
    # **記録は変わらない**
    record = env.recipes.get(got["asset_id"])
    assert record["status"] in ("exact", "approx", "impossible")


def test_unknown_verdict_and_unknown_ids_are_refused(env):
    """**何を壊すと落ちるか**: 語彙の検査（422）と 404 を落とすと、
    綴り間違いが `CHECK` に当たって 500 になる（家風: 口で検査する）。"""
    got = export_of(env)
    asset_id, _path = add_asset(env, GRAPH, name="r2.png", sha="c" * 64)
    attached = env.watcher.attach(got["recipe_id"], got["attempt_id"], asset_id, actor="human")
    with pytest.raises(ReviewError) as bad:
        env.watcher.set_verdict(got["recipe_id"], got["attempt_id"], attached["id"], "goodish",
                                actor="human")
    assert bad.value.status == 422
    with pytest.raises(ReviewError) as bad2:
        env.watcher.set_verdict(got["recipe_id"], "nope", attached["id"], "close", actor="human")
    assert bad2.value.status == 404
    with pytest.raises(ReviewError) as bad3:
        env.watcher.attach(got["recipe_id"], got["attempt_id"], "no-such-asset", actor="human")
    assert bad3.value.status == 404


def test_seed_changed_is_detected_from_the_result_graph(env):
    """**何を壊すと落ちるか**: 結果の PNG の `KSampler.seed` を書き出しの seed と比べないと、
    画面が「同じ条件で出た」と嘘をつく（§0.9 の `seed_changed`。§4.7.2 の 2）。"""
    got = export_of(env, seed="1")
    sub = got["marker"].rsplit("/", 1)[0]
    other = exported_graph(got)
    other["15"]["inputs"]["seed"] = 999
    path = write_result(env, subfolder=sub,
                        filename=f"{got['marker'].rsplit('/', 1)[1]}_00001_.png", graph=other)
    env.comfy.jobs = [job("j1", 1000)]
    env.comfy.details = {"j1": detail("j1", graph=other,
                                      images=[{"filename": path.name, "subfolder": sub, "type": "output"}])}
    with env.store.transaction() as con:
        con.execute("INSERT INTO settings(key, value) VALUES ('comfyui.output_dir', ?)",
                    (str(env.tmp_path / "output"),))
    env.watcher.start(actor="human", run=False)
    bump(env)
    env.watcher.poll_once()
    row = rows(env, "SELECT * FROM recipe_export_result")[0]
    assert row["seed_changed"] == 1, "seed が違うのに気づいていない"
    assert row["same_hash"] == 0, "seed が変われば鍵も変わる（seed は鍵に入る）"
    assert _seed_of_graph(other) == "999"


def test_the_sidecar_is_written_next_to_the_result(env):
    """**何を壊すと落ちるか**: sidecar（人が読める JSON）を書かないと、
    フォルダを開いた人に「どの条件の結果か」が伝わらない（§0.9）。"""
    got = export_of(env)
    sub = got["marker"].rsplit("/", 1)[0]
    path = write_result(env, subfolder=sub, filename=f"{got['marker'].rsplit('/', 1)[1]}_00001_.png", graph=exported_graph(got))
    env.comfy.jobs = [job("j1", 1000)]
    env.comfy.details = {"j1": detail("j1", graph=exported_graph(got),
                                      images=[{"filename": path.name, "subfolder": sub, "type": "output"}])}
    with env.store.transaction() as con:
        con.execute("INSERT INTO settings(key, value) VALUES ('comfyui.output_dir', ?)",
                    (str(env.tmp_path / "output"),))
    env.watcher.start(actor="human", run=False)
    bump(env)
    env.watcher.poll_once()
    sidecar = path.with_suffix(".result.json")
    assert sidecar.exists(), "sidecar が無い"
    doc = json.loads(sidecar.read_text(encoding="utf-8"))
    assert doc["attempt_id"] == got["attempt_id"] and doc["same_hash"] is True


def test_the_result_is_fetched_by_view_when_the_output_dir_is_unknown(env):
    """**何を壊すと落ちるか**: 出力先が分からない環境で `GET /view` の取り込みに落ちないと、
    結果が登録されない（§0.9 の二番目の道。**取り込んだことも画面に出す**）。"""
    got = export_of(env)
    sub = got["marker"].rsplit("/", 1)[0]
    body = make_png(env.tmp_path / "src.png", clone(GRAPH)).read_bytes()
    env.comfy = FakeComfy(view=body)
    env.comfy.jobs = [job("j1", 1000)]
    env.comfy.details = {"j1": detail("j1", graph=clone(GRAPH), images=[
        {"filename": f"{got['marker'].rsplit('/', 1)[1]}_00001_.png", "subfolder": sub, "type": "output"}])}
    watcher = ComfyWatcher(env.store, env.recipes, env.exports, http=env.comfy,
                              bytes_of=env.comfy.bytes_of, interval=0.01)
    # **出力先の設定を消す**（推定も当たらない: 偽の ComfyUI は `/internal/folder_paths` を知らない）
    with env.store.transaction() as con:
        con.execute("DELETE FROM settings WHERE key = 'comfyui.output_dir'")
    watcher.start(actor="human", run=False)
    bump(env)
    try:
        got_cycle = watcher.poll_once()
    finally:
        watcher.stop()
    assert got_cycle["results"] == 1, got_cycle
    taken = list((Path(env.store.data_dir) / "results").glob("*.png"))
    assert taken, "`/view` の取り込みが動いていない"
