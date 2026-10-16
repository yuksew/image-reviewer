"""日本語の語釈（P4-2）のテスト。

設計: `docs/p4-design.md` **§0.9**（番号付きで頼む・番号で対応・保存する条件・1 語ずつへの落とし方・
`edited=1` の保護）・§0.10（`GET` は書かない・冪等）・§3.4（`glosses` / `pending_gloss` / `counts`）・
§3.5（3 つの口）・§4.2（`tag_gloss` の状態）・§8.1 の **9・10・11・21・23**

各テストの docstring に「**何を壊すと落ちるか**」を書く（P5 の監査 F1 の教訓）。
**本物の模型は呼ばない**（偽の engine を差し込む。`@pytest.mark.comfyui` は付けない）。
"""

from __future__ import annotations

import threading
import time

import pytest
from fastapi.testclient import TestClient

from image_reviewer import db, gloss, tags
from image_reviewer.gloss import GlossService
from image_reviewer.jobs import JobService
from image_reviewer.review import ReviewError
from image_reviewer.store import Store
from types import SimpleNamespace


# ---- 道具 ----


class FakeEngine:
    """偽の模型（**本物は呼ばない**）。`replies` を 1 回の呼び出しごとに 1 つ消費する。"""

    def __init__(self, replies, *, ping: bool = True, engine: str = "fake-model",
                 sleep: float = 0.0):
        self.replies = list(replies)
        self.calls: list[list[str]] = []
        self.base = "http://127.0.0.1:1"
        self._ping = ping
        self.engine = engine
        self._sleep = sleep

    def ping(self) -> bool:
        return self._ping

    def translate(self, names):
        self.calls.append(list(names))
        if self._sleep:
            time.sleep(self._sleep)
        if not self.replies:
            raise AssertionError("偽の模型の応答を使い切りました（呼び出し回数が想定より多い）")
        return self.replies.pop(0)


@pytest.fixture
def env(tmp_path):
    store = Store(tmp_path / "data")
    try:
        yield SimpleNamespace(store=store, tmp_path=tmp_path)
    finally:
        store.close()


def make_tags(env, names) -> dict[str, int]:
    """語の行を作る（`tag` 表）。"""
    with env.store.transaction() as con:
        return {name: JobService._ensure_tag(con, name, 0, "general", 1) for name in names}


def add_asset(env, sha: str = "a" * 64) -> str:
    """合成の 1 枚を登録する（実データに依存しない）。"""
    import hashlib

    asset_id = "01" + hashlib.sha1(sha.encode()).hexdigest()[:24].upper()
    with env.store.transaction() as con:
        con.execute("INSERT INTO asset(id, sha256, kind, review_state, first_seen_at,"
                    " last_seen_at) VALUES (?,?,'generated','unreviewed',?,?)",
                    (asset_id, sha, db.now(), db.now()))
    return asset_id


def service(env, engine) -> GlossService:
    return GlossService(env.store, engine_factory=lambda settings: engine)


def gloss_rows(env) -> dict[int, tuple[str, int]]:
    with env.store.locked() as con:
        return {int(r["tag_id"]): (r["ja"], int(r["edited"]))
                for r in con.execute("SELECT tag_id, ja, edited FROM tag_gloss")}


def status_of(func, *args, **kw) -> int:
    with pytest.raises(ReviewError) as got:
        func(*args, **kw)
    return got.value.status


# ---- 応答の読み取り（純関数。§0.9 の 2〜6）----


def test_parse_numbered_keeps_only_numbered_japanese_lines():
    """§8.1 の 9（前半）: **番号での対応**を外す（位置で対応にする）と落ちる。

    番号の無い行・英語のままの行・空行・番号の重複を、それぞれ落とすことを固定する。
    """
    text = "\n".join([
        "1. 1人娘",
        "",                                  # 空行は読み飛ばす
        "2. long hair",                      # 英語のまま（ASCII だけ）
        "2. 長髪",                            # **番号の重複** → その番号は捨てる（どちらが正か決められない）
        "3. 1girl",                          # 英語のまま
        "これは説明です",                      # 番号の無い行
        "4) 微笑み",                          # `)` も受ける
    ])
    assert gloss.parse_numbered(text) == {1: "1人娘", 4: "微笑み"}


def test_parse_numbered_on_an_empty_reply_is_empty():
    """§8.1 の 9（後半）: **空の応答**で 1 行も保存しないこと。"""
    assert gloss.parse_numbered("") == {}
    assert gloss.parse_numbered("\n\n") == {}
    assert gloss.parse_numbered("1girl, long_hair") == {}          # 番号が無ければ全部捨てる


def test_format_prompt_is_numbered_lines():
    """§0.9 の 1: 頼み方は `1. 1girl`（番号＋`.`＋空白＋語）。"""
    assert gloss.format_prompt(["1girl", "long_hair"]) == "1. 1girl\n2. long_hair"


# ---- 訳す（§3.5）----


def test_numbered_reply_maps_by_number_and_retries_only_the_missing(env):
    """§8.1 の 9: 壊れた行を注入 → **それらの語は入らず、取れた番号の語だけ入る**。

    取れなかった番号は**1 語ずつ**訳し直す（成功の条件は「番号が取れて日本語が返った」）。
    """
    ids = make_tags(env, ["1girl", "long_hair", "smile", "looking_at_phone"])
    engine = FakeEngine([
        # 1 回目: 1 は正しい / 2 は重複 / 3 は英語のまま / 4 は欠け
        "1. 1人娘\n2. long hair\n2. 長髪\n3. 1girl\n番号の無い行",
        # 2（long_hair）の 1 語ずつ
        "1. 長髪",
        # 3（smile）の 1 語ずつ → まだ英語のまま（保存しない）
        "1. smile",
        # 4（looking_at_phone）の 1 語ずつ
        "1. スマホを見ている",
    ])
    got = service(env, engine).translate(tag_ids=list(ids.values()))

    rows = gloss_rows(env)
    assert rows[ids["1girl"]] == ("1人娘", 0)
    assert rows[ids["long_hair"]] == ("長髪", 0)
    assert rows[ids["looking_at_phone"]] == ("スマホを見ている", 0)
    assert ids["smile"] not in rows, "英語のままの行を保存した（§0.9 の 3）"
    assert [item["name"] for item in got["untranslated"]] == ["smile"]
    assert got["calls"] == 4, "取れなかった番号だけ 1 語ずつ訳し直していない"
    assert engine.calls[0] == ["1girl", "long_hair", "smile", "looking_at_phone"]
    assert engine.calls[1] == ["long_hair"] and engine.calls[3] == ["looking_at_phone"]


def test_an_empty_reply_stores_nothing(env):
    """§8.1 の 9: **空の応答**で `tag_gloss` に 1 行も入らないこと。"""
    ids = make_tags(env, ["1girl", "long_hair"])
    engine = FakeEngine(["", "", ""])
    got = service(env, engine).translate(tag_ids=list(ids.values()))

    assert gloss_rows(env) == {}
    assert len(got["untranslated"]) == 2 and got["translated"] == []


def test_partial_reply_applies_what_was_returned(env):
    """§0.9 の 5: **部分的に当てはめてよい**（番号で対応するので抜けても壊れない）。"""
    names = [f"w{i}" for i in range(1, 21)]
    ids = make_tags(env, names)
    lines = "\n".join(f"{i}. 語{i}" for i in range(1, 18))       # 17 語だけ返す
    engine = FakeEngine([lines, "", "", ""])                     # 残り 3 語の 1 語ずつは失敗
    got = service(env, engine).translate(tag_ids=list(ids.values()))

    assert len(got["translated"]) == 17
    assert len(got["untranslated"]) == 3
    assert len(gloss_rows(env)) == 17, "取れた 17 語が入っていない"
    assert gloss_rows(env)[ids["w17"]] == ("語17", 0)


def test_second_call_does_not_call_the_model(env):
    """§8.1 の 23: **既に語釈がある語を訳し直すように変える**と落ちる。

    既定（`force=false`）は `skipped` で**模型を回さない**（2 回押しても 2 回目は呼び出し 0 回）。
    """
    ids = make_tags(env, ["1girl", "long_hair"])
    engine = FakeEngine(["1. 1人娘\n2. 長髪"])
    svc = service(env, engine)
    first = svc.translate(tag_ids=list(ids.values()))
    assert first["calls"] == 1 and len(first["translated"]) == 2

    second = svc.translate(tag_ids=list(ids.values()))
    assert second["calls"] == 0, "2 回目で模型を回した（点検 B-3）"
    assert len(second["skipped"]) == 2 and second["translated"] == []
    assert len(engine.calls) == 1

    # `force=true` なら回す（**`edited=1` は別。次のテスト**）
    engine.replies.append("1. 女の子\n2. 長い髪")
    third = svc.translate(tag_ids=list(ids.values()), force=True)
    assert third["calls"] == 1 and len(third["translated"]) == 2
    assert gloss_rows(env)[ids["1girl"]] == ("女の子", 0)


def test_edited_gloss_is_never_overwritten(env):
    """§8.1 の 10: **`edited=1` の保護**を外すと落ちる（`force=true` でも上書きしない）。"""
    ids = make_tags(env, ["1girl", "long_hair"])
    with env.store.transaction() as con:
        con.execute("INSERT INTO tag_gloss(tag_id, ja, source, engine, edited, created_at,"
                    " updated_at) VALUES (?,?,'manual',NULL,1,?,?)",
                    (ids["1girl"], "人が直した", db.stamp(), db.stamp()))
    engine = FakeEngine(["1. 長髪"])
    got = service(env, engine).translate(tag_ids=list(ids.values()), force=True)

    rows = gloss_rows(env)
    assert rows[ids["1girl"]] == ("人が直した", 1), "人が直した語釈を上書きした"
    assert rows[ids["long_hair"]] == ("長髪", 0)
    assert [s["reason"] for s in got["skipped"]] == ["人が直した語釈は上書きしません"]
    assert engine.calls == [["long_hair"]], "守る語まで模型に送っている"


def test_too_many_words_and_empty_ids_are_422(env):
    """§8.1 の 21: **語数の上限を外す**と落ちる（21 語は 422）。空も 422。"""
    ids = make_tags(env, [f"w{i}" for i in range(1, 22)])
    svc = service(env, FakeEngine([]))
    assert status_of(svc.translate, tag_ids=list(ids.values())) == 422
    assert status_of(svc.translate, tag_ids=[]) == 422
    # 20 語は通る（上限の内側）
    engine = FakeEngine(["\n".join(f"{i}. 語{i}" for i in range(1, 21))])
    assert service(env, engine).translate(tag_ids=list(ids.values())[:20])["calls"] == 1


def test_unknown_tag_id_is_404(env):
    """設計は黙っているが、他の口（`DELETE`）に揃えて 404 にする（親の指示で決めた）。"""
    make_tags(env, ["1girl"])
    assert status_of(service(env, FakeEngine([])).translate, tag_ids=[999999]) == 404


def test_engine_unavailable_is_409(env):
    """§3.5: ComfyUI につながらないときは **409 `gloss_engine_unavailable`**。"""
    ids = make_tags(env, ["1girl"])
    svc = service(env, FakeEngine([], ping=False))
    with pytest.raises(ReviewError) as got:
        svc.translate(tag_ids=list(ids.values()))
    assert got.value.status == 409
    assert got.value.code == "gloss_engine_unavailable"
    assert got.value.details["url"] == "http://127.0.0.1:1"
    assert gloss_rows(env) == {}


def test_everything_skipped_does_not_ping_the_engine(env):
    """§0.10: 回す語が 1 つも無いときは**繋がらなくても 409 にしない**（模型を回さないので関係ない）。"""
    ids = make_tags(env, ["1girl"])
    svc = GlossService(env.store, engine_factory=lambda settings: FakeEngine([], ping=False))
    with env.store.transaction() as con:
        con.execute("INSERT INTO tag_gloss(tag_id, ja, source, engine, edited, created_at,"
                    " updated_at) VALUES (?,?,'textgenerate','m',0,?,?)",
                    (ids["1girl"], "1人娘", db.stamp(), db.stamp()))
    got = svc.translate(tag_ids=list(ids.values()))
    assert got["calls"] == 0 and len(got["skipped"]) == 1 and got["translated"] == []


def test_the_model_is_called_outside_the_transaction(env):
    """P4-1 の監査 B-1 と同じ規律: **模型を待つのは取引の外**。

    取引の中で待つと、`Store` の錠を握ったままになり、その間**全部の API が待たされる**。
    偽の模型を 0.5 秒眠らせ、その間に `locked()` が 0.25 秒以内に取れることを見る。
    """
    ids = make_tags(env, ["1girl"])
    engine = FakeEngine(["1. 1人娘"], sleep=0.5)
    svc = service(env, engine)
    done = threading.Event()

    def run():
        svc.translate(tag_ids=list(ids.values()))
        done.set()

    worker = threading.Thread(target=run)
    worker.start()
    time.sleep(0.1)                                    # 模型の中に入るのを待つ
    started = time.monotonic()
    with env.store.locked():
        waited = time.monotonic() - started
    worker.join(timeout=5)
    assert done.is_set()
    assert waited < 0.25, f"模型の間、錠が握られていた（{waited:.3f} 秒）"


# ---- 読み出し（`GET` は書かない。§0.10 / §8.1 の 11）----


def test_get_endpoints_do_not_write(env, monkeypatch):
    """§8.1 の 11: **`GET` が訳すように変える**と落ちる（語釈の口も対象。点検 F）。"""
    monkeypatch.setenv("IMAGE_REVIEWER_DATA", str(env.tmp_path / "data"))
    from image_reviewer.app import create_app

    app = create_app()
    engine = FakeEngine([], ping=False)               # 訳そうとしたら気づく（応答が無い）
    app.state.gloss = GlossService(env.store, engine_factory=lambda settings: engine)
    asset = add_asset(env)
    ids = make_tags(env, ["1girl", "long_hair"])
    with TestClient(app, base_url="http://127.0.0.1") as client:
        before = len(gloss_rows(env))
        assert client.get(f"/api/assets/{asset}/tags").status_code == 200
        assert client.get("/api/tags/gloss/pending").status_code == 200
        assert client.get(f"/api/tags/{ids['1girl']}/gloss").status_code == 200
        assert client.get("/api/tags").status_code == 200
        assert len(gloss_rows(env)) == before, "GET が語釈を書いた"
    assert engine.calls == [], "GET が模型を回した"


def test_pending_counts_words_without_gloss(env):
    """§3.5: `GET /api/tags/gloss/pending` は**数えるだけ**（訳さない）。"""
    ids = make_tags(env, ["1girl", "long_hair", "smile"])
    with env.store.transaction() as con:
        con.execute("INSERT INTO tag_gloss(tag_id, ja, source, engine, edited, created_at,"
                    " updated_at) VALUES (?,?,'textgenerate','m',0,?,?)",
                    (ids["1girl"], "1人娘", db.stamp(), db.stamp()))
    with env.store.locked() as con:
        got = gloss.pending(con, limit=10)
    assert got["count"] == 2
    assert {item["name"] for item in got["sample"]} == {"long_hair", "smile"}


def test_asset_payload_carries_glosses_pending_and_counts(env):
    """§3.4: `GET /api/assets/{id}/tags` に `glosses` / `pending_gloss` / `counts` が入る。

    P4-1 の監査 C-6 の宿題（**P4-2 で形を決める**）。`counts` は**出所ごとの数**（§3.4 の例）。
    """
    asset = add_asset(env)
    ids = make_tags(env, ["1girl", "long_hair"])
    with env.store.transaction() as con:
        for tag_id, source in ((ids["1girl"], "png"), (ids["1girl"], "wd14"),
                               (ids["long_hair"], "manual")):
            con.execute("INSERT INTO asset_tag(asset_id, tag_id, score, source, model, actor,"
                        " tagged_at) VALUES (?,?,NULL,?,NULL,NULL,?)",
                        (asset, tag_id, source, db.stamp()))
        con.execute("INSERT INTO tag_gloss(tag_id, ja, source, engine, edited, created_at,"
                    " updated_at) VALUES (?,?,'textgenerate','qwen',0,?,?)",
                    (ids["1girl"], "1人娘", db.stamp(), db.stamp()))
    with env.store.locked() as con:
        items = tags.tag_docs(con, asset)
        block = gloss.block_for(con, items)
    assert block["glosses"] == {"1girl": {"ja": "1人娘", "source": "textgenerate",
                                          "engine": "qwen", "edited": False}}
    assert block["pending_gloss"] == ["long_hair"]
    assert block["counts"] == {"png": 1, "wd14": 1, "manual": 1}


# ---- 人が直す（§3.5・§4.2）----


def test_a_human_can_write_and_edit_the_gloss(tmp_path, monkeypatch):
    """§3.5: 人が書く / 直す口は `human` だけ。`edited=1` が立ち、**`source` は由来を保つ**。

    **何を壊すと落ちるか**: `require_human` を外すと 403 が消える。`edited=1` を立てないと
    訳し直しで上書きされる（§8.1 の 10 と対）。
    """
    monkeypatch.setenv("IMAGE_REVIEWER_DATA", str(tmp_path / "data"))
    from image_reviewer.app import create_app

    app = create_app()
    with TestClient(app, base_url="http://127.0.0.1") as client:
        store = app.state.store
        with store.transaction() as con:
            tag_id = JobService._ensure_tag(con, "1girl", 0, "general", 1)
        human = {"X-Image-Reviewer-Actor": "human"}
        # エージェントは 403（ヘッダ無し＝agent）
        assert client.post(f"/api/tags/{tag_id}/gloss", json={"ja": "1人娘"}).status_code == 403
        # 空は 422
        assert client.post(f"/api/tags/{tag_id}/gloss", json={"ja": "  "},
                           headers=human).status_code == 422
        # 人がゼロから書く → source='manual'
        got = client.post(f"/api/tags/{tag_id}/gloss", json={"ja": "1人娘"}, headers=human)
        assert got.status_code == 200, got.text
        assert got.json()["edited"] is True and got.json()["source"] == "manual"
        # 自動の語釈を人が直す → **source は `textgenerate` のまま**（§4.2 の括弧書き）
        with store.transaction() as con:
            con.execute("UPDATE tag_gloss SET source = 'textgenerate', engine = 'qwen'"
                        " WHERE tag_id = ?", (tag_id,))
        again = client.post(f"/api/tags/{tag_id}/gloss", json={"ja": "女の子1人"}, headers=human)
        body = again.json()
        assert body["ja"] == "女の子1人" and body["edited"] is True
        assert body["source"] == "textgenerate", "由来（source）を書き換えた"
        assert body["engine"] == "qwen", "engine を触った"
        # 読む口は書かない
        assert client.get(f"/api/tags/{tag_id}/gloss").json()["ja"] == "女の子1人"


def test_translate_endpoint_shape_and_guards(tmp_path, monkeypatch):
    """§3.5: 応答の形（`translated` / `skipped` / `untranslated` / `calls` / `elapsed_ms`）と、
    新しい `POST` の守り（`Host` / `Content-Type`。P5・P6 と同じ観点）。"""
    monkeypatch.setenv("IMAGE_REVIEWER_DATA", str(tmp_path / "data"))
    from image_reviewer.app import create_app

    app = create_app()
    with TestClient(app, base_url="http://127.0.0.1") as client:
        store = app.state.store
        with store.transaction() as con:
            tag_id = JobService._ensure_tag(con, "1girl", 0, "general", 1)
        app.state.gloss = GlossService(store,
                                       engine_factory=lambda s: FakeEngine(["1. 1人娘"]))
        got = client.post("/api/tags/gloss", json={"tag_ids": [tag_id]})
        assert got.status_code == 200, got.text
        body = got.json()
        assert set(body) == {"translated", "skipped", "untranslated", "calls", "elapsed_ms"}
        assert body["translated"] == [{"tag_id": tag_id, "name": "1girl", "ja": "1人娘",
                                       "engine": "fake-model"}]
        assert body["calls"] == 1 and isinstance(body["elapsed_ms"], int)
        # 守り（middleware）
        assert client.post("/api/tags/gloss", json={},
                           headers={"Host": "evil.example"}).status_code == 403
        assert client.post("/api/tags/gloss", content=b"{}",
                           headers={"Content-Type": "text/plain"}).status_code == 403
        assert client.post(f"/api/tags/{tag_id}/gloss", json={"ja": "x"},
                           headers={"Host": "evil.example"}).status_code == 403


# ---- P4-2 の監査で足した検査（B-1 / C-1 / C-2）----


def test_a_communication_error_while_waiting_is_504(monkeypatch):
    """監査 B-1 / G-5: `/history` の通信が落ちても **500 にしない**（期限まで待ち直し、越えたら 504）。

    実測では冷えた模型の初回に 4 回中 1 回 `WinError 10060` で落ちていた。`_wait` が
    `OSError` を受けずに投げていたのが原因。
    """
    import urllib.error

    import image_reviewer.gloss as gloss

    def boom(*args, **kw):
        raise urllib.error.URLError("接続が時間切れ")

    monkeypatch.setattr(gloss, "_http_json", boom)
    engine = gloss.GlossEngine("http://127.0.0.1:1", timeout=0.2, poll=0.05)
    with pytest.raises(ReviewError) as got:
        engine._wait("pid-1")
    assert got.value.status == 504, "通信の失敗が 500（または別の番号）で返った（監査 B-1）"


def test_a_communication_error_on_submit_is_502(monkeypatch):
    """監査 B-1 / E-3: 投げられないときは **502**（500 にしない）。"""
    import urllib.error

    import image_reviewer.gloss as gloss

    def boom(*args, **kw):
        raise urllib.error.URLError("繋がりません")

    monkeypatch.setattr(gloss, "_http_json", boom)
    engine = gloss.GlossEngine("http://127.0.0.1:1")
    with pytest.raises(ReviewError) as got:
        engine._submit("1. 1girl")
    assert got.value.status == 502


def test_the_settings_are_read_on_every_translate(env):
    """監査 C-1 / G-2: 設定は**訳すたびに読み直す**（再起動しないと効かない、をやめる）。

    以前はプロセスで 1 回だけ読んでいたので、`gloss.llm` を変えても古い模型のまま訳が通った。
    """
    names = make_tags(env, ["long_hair"])
    seen: list[str] = []

    def factory(settings):
        seen.append(settings["llm"])
        return FakeEngine(["1. 長髪"])

    svc = GlossService(env.store, engine_factory=factory)
    svc.translate(tag_ids=[names["long_hair"]])
    with env.store.transaction() as con:
        con.execute("INSERT OR REPLACE INTO settings(key, value) VALUES ('gloss.llm', ?)",
                    ("別の模型.safetensors",))
    svc.translate(tag_ids=[names["long_hair"]], force=True)

    assert seen == ["qwen3vl_8b_int8_convrot.safetensors", "別の模型.safetensors"], \
        f"設定を読み直していない（監査 C-1）: {seen}"


def test_only_kana_or_kanji_counts_as_japanese():
    """監査 C-2 / G-3: 「ASCII だけでない」では **記号だけ**と**絵文字＋英語**が通ってしまう。

    模型が `👁️ = 視聴者を見つめる` を返した実例があるので、**かな・漢字を 1 文字以上**を条件にする。
    """
    from image_reviewer.gloss import is_japanese, parse_numbered

    assert is_japanese("長髪") and is_japanese("コミック") and is_japanese("1人娘")
    for bad in ("1girl", "……", "👁️ girl", "   ", "OK!", "3D"):
        assert not is_japanese(bad), f"日本語でない本文を通した（監査 C-2）: {bad!r}"

    got = parse_numbered("1. 長髪\n2. ……\n3. 👁️ girl\n4. モノクロ")
    assert got == {1: "長髪", 4: "モノクロ"}, f"記号・絵文字の行を保存した（監査 C-2）: {got}"
