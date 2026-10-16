"""監視の口（P7-3）のテスト。**HTTP の層**（403 の検査・`GET` の無副作用・合否の往復）。

設計: `docs/p7-design.md` §3.4（監視の口）・§3.6（手で紐付ける口と合否）・§0.10（`GET` は書かない・`actor`）

何を壊すと落ちるか:
- 新しい `POST` に **`Host` / `Content-Type` の検査**を入れ忘れる → 403 の検査が落ちる（家風。P6 の C8）
- `GET /api/watcher` が状態を書く／開始する → 「見ただけで GPU を使う」に戻る
- 合否を `agent` でも書けるようにする → 「判断と手動の記録は人だけ」が崩れる
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from image_reviewer.recipe import RecipeService
from image_reviewer.recipe_export import RecipeExportService
from image_reviewer.watcher import ComfyWatcher
from test_recipe import GRAPH, FakeProbe, add_asset, make_png
from test_watcher import FakeComfy

HUMAN = {"X-Image-Reviewer-Actor": "human"}
AGENT = {"X-Image-Reviewer-Actor": "agent"}


@pytest.fixture
def app_env(tmp_path, monkeypatch):
    """本物の `create_app()`（**偽の ComfyUI** を差し込む。実データは使わない）。"""
    from image_reviewer.app import create_app

    monkeypatch.setenv("IMAGE_REVIEWER_DATA", str(tmp_path / "data"))
    app = create_app()
    probe = FakeProbe()
    comfy = FakeComfy()
    app.state.recipes = RecipeService(app.state.store, probe_factory=lambda s: probe)
    app.state.recipe_exports = RecipeExportService(app.state.store, app.state.recipes,
                                                  probe_factory=lambda s: probe)
    app.state.watcher = ComfyWatcher(app.state.store, app.state.recipes,
                                     app.state.recipe_exports, http=comfy,
                                     bytes_of=comfy.bytes_of, interval=3600)
    with TestClient(app, base_url="http://127.0.0.1") as client:
        yield client, app, comfy, tmp_path
    app.state.store.close()


def test_the_watcher_endpoints_are_guarded(app_env):
    """**何を壊すと落ちるか**: `Host: evil` と `Content-Type: text/plain` の検査（middleware）を外すと、
    別のサイトから状態を変えられる。**人だけ**の検査を外すとエージェントが GPU を使える。"""
    client, app, _comfy, _tmp = app_env
    # `Host` が違う → 403
    assert client.post("/api/watcher/start", headers={**HUMAN, "Host": "evil.example"},
                       json={}).status_code == 403
    # `Content-Type` が JSON でない → 403
    assert client.post("/api/watcher/start", headers={**HUMAN, "Content-Type": "text/plain"},
                       content="x").status_code == 403
    # **エージェントは 403**（人だけ）
    assert client.post("/api/watcher/start", headers=AGENT, json={}).status_code == 403
    assert client.post("/api/watcher/stop", headers=AGENT).status_code == 403
    # `actor` の語彙が変 → 422（`CHECK` に当てて 500 にしない）
    assert client.post("/api/watcher/start", headers={"X-Image-Reviewer-Actor": "robot"},
                       json={}).status_code == 422


def test_get_watcher_does_not_write_or_start(app_env):
    """**何を壊すと落ちるか**: `GET /api/watcher` が状態を書いたり監視を始めたりすると、
    画面を開いただけで回り始める（§0.10 の「`GET` は書かない」）。"""
    client, app, _comfy, tmp_path = app_env
    before = sorted((p.name, p.stat().st_size, p.stat().st_mtime_ns)
                    for p in Path(app.state.store.data_dir).rglob("*")
                    if p.is_file() and not p.name.startswith("db.sqlite3"))
    first = client.get("/api/watcher").json()
    assert first["enabled"] is False
    assert app.state.store.con.execute("SELECT * FROM watcher_state").fetchall() == []
    after = sorted((p.name, p.stat().st_size, p.stat().st_mtime_ns)
                   for p in Path(app.state.store.data_dir).rglob("*")
                   if p.is_file() and not p.name.startswith("db.sqlite3"))
    assert before == after, "`GET /api/watcher` がファイルを書いている"


def test_start_and_stop_from_the_screen(app_env):
    """**何を壊すと落ちるか**: 開始/停止の口を落とすと、画面から監視を動かせない（§3.4）。
    `start` は**そのときの最新を基準**にする（過去の job を遡らない）。"""
    client, app, comfy, _tmp = app_env
    comfy.jobs = [{"id": "j1", "status": "completed", "create_time": 1000, "outputs_count": 0}]
    got = client.post("/api/watcher/start", headers=HUMAN, json={})
    assert got.status_code == 200
    body = got.json()
    assert body["enabled"] is True and body["baseline_prompt_id"] == "j1"
    state = client.get("/api/watcher").json()
    assert state["enabled"] is True and state["baseline_create_time"] == 1000
    assert client.post("/api/watcher/stop", headers=HUMAN).json() == {"enabled": False}
    assert client.get("/api/watcher").json()["enabled"] is False


def test_attach_and_verdict_over_http(app_env):
    """**何を壊すと落ちるか**: 手で紐付ける口（`matched_by='manual'`）と合否の口（上書き）を
    落とすと、印が無い結果に人が合否を付けられない（線 7）。**記録は変わらない**。"""
    client, app, _comfy, tmp_path = app_env
    store = app.state.store
    env = SimpleNamespace(store=store, tmp_path=tmp_path)
    asset_id, _path = add_asset(env, GRAPH, name="src.png", sha="a" * 64)
    got = app.state.recipes.record(asset_id, mode="pin_text", actor="human")
    attempt = app.state.recipe_exports.export(got["recipe_id"], seeds=["1"], actor="human")
    result_png = make_png(tmp_path / "images" / "r.png", GRAPH, color=(9, 9, 9))
    result_id, _ = store.register(sha256="d" * 64, path=str(result_png),
                                  size=result_png.stat().st_size,
                                  mtime_ns=result_png.stat().st_mtime_ns, width=48, height=64,
                                  fmt="png", meta=None, note=None)

    url = f"/api/recipes/{got['recipe_id']}/exports/{attempt['attempt_id']}/results"
    assert client.post(url, headers=AGENT, json={"result_asset_id": result_id}).status_code == 403
    made = client.post(url, headers=HUMAN, json={"result_asset_id": result_id})
    assert made.status_code == 201 and made.json()["matched_by"] == "manual"
    again = client.post(url, headers=HUMAN, json={"result_asset_id": result_id})
    assert again.status_code == 200 and again.json()["replayed"] is True

    before = client.get(f"/api/assets/{asset_id}/recipe").json()
    verdict_url = f"{url}/{made.json()['id']}/verdict"
    assert client.post(verdict_url, headers=AGENT,
                       json={"verdict": "close"}).status_code == 403
    assert client.post(verdict_url, headers=HUMAN,
                       json={"verdict": "close", "note": "近い"}).json()["verdict"] == "close"
    changed = client.post(verdict_url, headers=HUMAN,
                          json={"verdict": "different", "note": "違う"}).json()
    assert changed["verdict"] == "different"
    assert client.post(verdict_url, headers=HUMAN,
                       json={"verdict": "goodish"}).status_code == 422
    # **記録は変わらない**（バイト一致）
    after = client.get(f"/api/assets/{asset_id}/recipe").json()
    assert after["recipe_hash"] == before["recipe_hash"], "合否で記録の鍵が変わった"
    assert after == before, "合否で記録が変わった"
    # 一覧に出る
    listed = client.get(f"/api/recipes/{got['recipe_id']}/exports").json()["items"][0]["results"]
    assert listed[0]["verdict"] == "different" and listed[0]["verdict_actor"] == "human"


def test_the_exports_list_still_works_without_results(app_env):
    """**何を壊すと落ちるか**: 結果の JOIN を入れたときに、結果が 1 件も無い束でも
    落ちないこと（`GET /api/recipes/{id}/exports` は P7-2 から使われている）。"""
    client, app, _comfy, _tmp = app_env
    env = SimpleNamespace(store=app.state.store, tmp_path=_tmp)
    asset_id, _path = add_asset(env, GRAPH, name="s2.png", sha="b" * 64)
    got = app.state.recipes.record(asset_id, mode="pin_text", actor="human")
    attempt = app.state.recipe_exports.export(got["recipe_id"], seeds=["1"], actor="human")
    listed = client.get(f"/api/recipes/{got['recipe_id']}/exports").json()["items"]
    assert [i["attempt_id"] for i in listed] == [attempt["attempt_id"]]
    assert listed[0]["results"] == []
