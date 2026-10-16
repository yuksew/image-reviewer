"""判断の台帳と現在値の写し（P5-1）のテスト。

設計: docs/p5-design.md §0.2（A2）・§0.4（B4・G7・G9）・§0.8（C11・C12）・§3.1・§3.2・§7
点検報告の **C15 の一覧**を、そのまま固定する（E2E ではなく、サーバを立てずに回す部分）。

`tmp_path` は `tests/conftest.py` が用意する（この環境の一時フォルダの制限を避けるため）。
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

from image_reviewer.export import ExportService
from image_reviewer.review import MAX_NOTE, ReviewError, ReviewService
from image_reviewer.scan import scan
from image_reviewer.store import Store

# ---- 道具 ----


def add_asset(store: Store, sha: str, name: str = "a.png", **kw) -> str:
    """合成の 1 枚を登録する（実データに依存しない）。"""
    args = {"size": 100, "mtime_ns": 1, "width": 16, "height": 16, "fmt": "png",
            "meta": None, "note": None}
    args.update(kw)
    path = store.data_dir.parent / "images" / name
    asset_id, _ = store.register(sha256=sha, path=str(path), **args)
    return asset_id


def make_png(path: Path, color=(200, 120, 90)) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (16, 16), tuple(color)).save(path)
    return path


def rows(store: Store, sql: str, args: tuple = ()) -> list:
    return store.con.execute(sql, args).fetchall()


def decisions_for(store: Store, asset_id: str) -> list:
    return rows(store, "SELECT * FROM decision WHERE subject_type='asset' AND subject_id=?"
                 " ORDER BY seq", (asset_id,))


@pytest.fixture
def env(tmp_path):
    """Store + ReviewService + ExportService（書き出しの遅延は**発火しない**長さにする）。"""
    store = Store(tmp_path / "data")
    exporter = ExportService(store, delay=3600.0, flush_on_start=False)
    review = ReviewService(store, exporter=exporter)
    try:
        yield SimpleNamespace(store=store, exporter=exporter, review=review,
                              data=store.data_dir, tmp_path=tmp_path)
    finally:
        exporter.close()
        store.close()


def make_group(env, asset_ids, policy="pick_one", title="まとまり"):
    return env.review.create_group(title=title, asset_ids=asset_ids, policy=policy)


def status_of(func, *args, **kw) -> int:
    with pytest.raises(ReviewError) as got:
        func(*args, **kw)
    return got.value.status


# ---- 1. 理由の妥当性（点検 C12・§3.1）----


def test_reject_without_a_reason_is_422(env):
    a = add_asset(env.store, "a" * 64)
    assert status_of(env.review.apply_asset, a, "reject", actor="human") == 422
    with pytest.raises(ReviewError) as got:
        env.review.apply_asset(a, "reject", actor="human")
    assert "理由" in got.value.detail
    assert decisions_for(env.store, a) == [], "失敗した判断が台帳に残った"


def test_unknown_or_inactive_reason_is_422(env):
    a = add_asset(env.store, "a" * 64)
    assert status_of(env.review.apply_asset, a, "reject",
                     reason_code_id="rc.nope", actor="human") == 422
    with env.store.transaction() as con:
        con.execute("INSERT INTO reason_code(id,label,applies_to,position,builtin,active)"
                    " VALUES ('rc.user.off','もう使わない','reject',99,0,0)")
    assert status_of(env.review.apply_asset, a, "reject",
                     reason_code_id="rc.user.off", actor="human") == 422


def test_applies_to_mismatch_is_422(env):
    """点検 C12: 「意図どおり」でボツにできない。"""
    a = add_asset(env.store, "a" * 64)
    assert status_of(env.review.apply_asset, a, "reject",
                     reason_code_id="rc.keep.as_intended", actor="human") == 422
    assert status_of(env.review.apply_asset, a, "keep",
                     reason_code_id="rc.reject.other", actor="human") == 422
    # `both` はどちらにも使える
    with env.store.transaction() as con:
        con.execute("INSERT INTO reason_code(id,label,applies_to,position,builtin,active)"
                    " VALUES ('rc.user.both','どちらにも','both',50,0,1)")
    assert env.review.apply_asset(a, "reject", reason_code_id="rc.user.both",
                                  actor="human")["asset"]["review_state"] == "rejected"


def test_note_over_2000_chars_is_422(env):
    a = add_asset(env.store, "a" * 64)
    assert status_of(env.review.apply_asset, a, "keep", note="あ" * (MAX_NOTE + 1),
                     actor="human") == 422
    got = env.review.apply_asset(a, "keep", note="あ" * MAX_NOTE, actor="human")
    assert got["asset"]["note"] == "あ" * MAX_NOTE


# ---- 2. キープは理由なしで通る ----

def test_keep_without_a_reason_is_200(env):
    a = add_asset(env.store, "a" * 64)
    got = env.review.apply_asset(a, "keep", actor="human")
    assert got["asset"]["review_state"] == "kept"
    assert got["asset"]["reason_code_id"] is None
    assert got["asset"]["decided_by"] == "human"
    assert len(decisions_for(env.store, a)) == 1


# ---- 3. clear は未判断に戻す ----

def test_clear_returns_to_unreviewed_and_nulls_the_reason(env):
    a = add_asset(env.store, "a" * 64)
    env.review.apply_asset(a, "keep", reason_code_id="rc.keep.favorite", actor="human")
    got = env.review.apply_asset(a, "clear", reason_code_id="rc.reject.other", actor="human")
    assert got["asset"] == {"id": a, "asset_id": a, "review_state": "unreviewed", "verdict": None,
                            "reason_code_id": None, "reason_label": None, "note": None,
                            "decided_at": None, "decided_by": None}
    row = env.store.asset(a)
    assert (row["review_state"], row["review_reason_code_id"], row["reviewed_at"],
            row["reviewed_by"]) == ("unreviewed", None, None, None)
    # 取り消しも**追記**（台帳は消さない）
    ledger = decisions_for(env.store, a)
    assert [d["verdict"] for d in ledger] == ["keep", "clear"]


# ---- 4. actor はヘッダだけ（点検 A2）----


def test_actor_is_enforced_in_the_service(env):
    a = add_asset(env.store, "a" * 64)
    assert status_of(env.review.apply_asset, a, "keep", actor="agent") == 403
    assert status_of(env.review.apply_asset, a, "keep", actor="robot") == 403
    assert decisions_for(env.store, a) == []


def test_actor_comes_only_from_the_header(tmp_path, monkeypatch):
    monkeypatch.setenv("IMAGE_REVIEWER_DATA", str(tmp_path / "data"))
    from fastapi.testclient import TestClient

    from image_reviewer.app import create_app

    app = create_app()
    with TestClient(app, base_url="http://127.0.0.1") as client:
        asset_id = add_asset(app.state.store, "a" * 64)
        body = {"subject_type": "asset", "subject_id": asset_id, "verdict": "keep"}

        # ヘッダが無ければ `agent`（＝403）
        assert client.post("/api/reviews", json=body).status_code == 403
        # **本文の actor は無視する**
        assert client.post("/api/reviews", json={**body, "actor": "human"}).status_code == 403
        # ヘッダが human なら通る
        ok = client.post("/api/reviews", json=body,
                         headers={"X-Image-Reviewer-Actor": "human"})
        assert ok.status_code == 200, ok.text
        assert ok.json()["asset"]["review_state"] == "kept"
        assert ok.json()["reopened_group_ids"] == []
        # ヘッダが human 以外なら 403
        assert client.post("/api/reviews", json=body,
                           headers={"X-Image-Reviewer-Actor": "agent"}).status_code == 403


# ---- 5. client_token（点検 D3）----


def test_same_client_token_is_replayed_and_a_different_payload_is_409(env):
    a = add_asset(env.store, "a" * 64)
    token = "11111111-2222-3333-4444-555555555555"
    first = env.review.apply_asset(a, "keep", reason_code_id="rc.keep.favorite", actor="human",
                                   client_token=token)
    again = env.review.apply_asset(a, "keep", reason_code_id="rc.keep.favorite", actor="human",
                                   client_token=token)
    assert again["decision_id"] == first["decision_id"], "再送で新しい行を書いた"
    assert len(decisions_for(env.store, a)) == 1
    assert status_of(env.review.apply_asset, a, "keep", reason_code_id="rc.keep.as_intended",
                     actor="human", client_token=token) == 409


def test_same_client_token_for_a_group_is_replayed(env):
    a, b = add_asset(env.store, "a" * 64), add_asset(env.store, "b" * 64, "b.png")
    group = make_group(env, [a, b])
    token = "tok-group"
    items = [{"asset_id": a, "verdict": "keep"},
             {"asset_id": b, "verdict": "reject", "reason_code_id": "rc.reject.other"}]
    first = env.review.apply_group(group["id"], items, actor="human", client_token=token)
    again = env.review.apply_group(group["id"], items, actor="human", client_token=token)
    assert again["decision_id"] == first["decision_id"]
    assert rows(env.store, "SELECT count(*) AS n FROM decision WHERE client_token=?", (token,))[0]["n"] == 1
    assert status_of(env.review.apply_group, group["id"],
                     [{"asset_id": a, "verdict": "reject", "reason_code_id": "rc.reject.other"},
                      {"asset_id": b, "verdict": "keep"}],
                     actor="human", client_token=token) == 409


def test_a_stale_client_token_replay_is_200_and_says_superseded(env):
    """監査 C6: 再送の間に同じ枚へ新しい判断が入っても、**再送は 200**（設計 §3.1）。

    以前は 409 `client_token_conflict` で、「中身が違う再送」と同じコードだった
    （送った側は自分が間違えたと誤解する）。いまは 200＋`superseded` で返し、
    いまの値をそのまま添える。
    """
    a = add_asset(env.store, "a" * 64)
    token = "stale-token-1"
    first = env.review.apply_asset(a, "keep", reason_code_id="rc.keep.favorite",
                                   actor="human", client_token=token)
    assert "superseded" not in first, "新しい判断を superseded と言った"
    # 同じ枚に新しい判断が入る（別の操作・別のタブ・エージェント）
    env.review.apply_asset(a, "reject", reason_code_id="rc.reject.other", actor="human")

    again = env.review.apply_asset(a, "keep", reason_code_id="rc.keep.favorite",
                                   actor="human", client_token=token)
    assert again["decision_id"] == first["decision_id"], "再送で新しい行を書いた"
    assert again["superseded"] is True, "古い再送に superseded を付けていない（監査 C6）"
    assert again["asset"]["review_state"] == "rejected", "いまの値を返していない"
    assert len(decisions_for(env.store, a)) == 2, "再送が行を増やした"
    # 中身が違う再送（トークンの取り違え）は今までどおり 409
    assert status_of(env.review.apply_asset, a, "keep",
                     reason_code_id="rc.keep.as_intended",
                     actor="human", client_token=token) == 409


def test_a_stale_client_token_replay_for_a_group_is_200(env):
    """まとまりも同じ規則（監査 C6）。open に戻った後の再送は 200＋`superseded`。"""
    a, b = add_asset(env.store, "a" * 64), add_asset(env.store, "b" * 64, "b.png")
    group = make_group(env, [a, b])
    token = "stale-token-group"
    items = [{"asset_id": a, "verdict": "keep"},
             {"asset_id": b, "verdict": "reject", "reason_code_id": "rc.reject.other"}]
    first = env.review.apply_group(group["id"], items, actor="human", client_token=token)
    env.review.reopen(group["id"], actor="human")

    again = env.review.apply_group(group["id"], items, actor="human", client_token=token)
    assert again["decision_id"] == first["decision_id"]
    assert again["superseded"] is True, "古い再送に superseded を付けていない（監査 C6）"
    assert again["group"]["state"] == "open", "いまの状態を返していない"


# ---- 6. 台帳は追記のみ。写しは導出できる ----

def test_ledger_is_append_only_and_reconcile_restores_a_corrupted_copy(env):
    a = add_asset(env.store, "a" * 64)
    env.review.apply_asset(a, "keep", reason_code_id="rc.keep.favorite", actor="human")
    before = len(decisions_for(env.store, a))

    # 写しをわざと壊す（JSON ストアでは失われていた状況）
    with env.store.transaction() as con:
        con.execute("UPDATE asset SET review_state='rejected', review_reason_code_id=NULL,"
                    " reviewed_at=NULL, reviewed_by=NULL WHERE id=?", (a,))
    assert env.review.reconcile() == 1
    got = env.store.asset(a)
    assert (got["review_state"], got["review_reason_code_id"]) == ("kept", "rc.keep.favorite")
    assert env.review.reconcile() == 0, "2 回目も直すべきものが残っている"
    assert len(decisions_for(env.store, a)) == before, "組み直しが台帳に手を入れた"


def test_reconcile_logs_the_count(env, caplog):
    a = add_asset(env.store, "a" * 64)
    env.review.apply_asset(a, "keep", actor="human")
    with caplog.at_level("INFO", logger="image_reviewer.review"):
        env.review.reconcile()
    assert any("組み直しました" in r.getMessage() for r in caplog.records), caplog.text


def test_reconcile_warns_with_the_before_and_after_values(env, caplog):
    """監査 B1: 写しを直したときは **WARNING** で、直す前の値を併記する（INFO 1 行にしない）。"""
    a = add_asset(env.store, "a" * 64)
    env.review.apply_asset(a, "keep", reason_code_id="rc.keep.favorite", actor="human")
    with env.store.transaction() as con:
        con.execute("UPDATE asset SET review_state='unreviewed', review_reason_code_id=NULL,"
                    " reviewed_at=NULL, reviewed_by=NULL WHERE id=?", (a,))
    with caplog.at_level("WARNING", logger="image_reviewer.review"):
        assert env.review.reconcile() == 1
    records = [r for r in caplog.records if r.levelname == "WARNING"]
    assert records, "直したのに WARNING が出ていない（監査 B1）"
    text = records[0].getMessage()
    assert a in text, "どの枚かがログに無い"
    assert "unreviewed" in text, "直す前の値がログに無い"
    assert "kept" in text and "rc.keep.favorite" in text, "直した後の値がログに無い"


# ---- 7. 順序は seq（点検 C11）----

def test_materialized_state_follows_insertion_order_not_created_at(env):
    a = add_asset(env.store, "a" * 64)
    first = env.review.apply_asset(a, "keep", reason_code_id="rc.keep.favorite", actor="human")
    second = env.review.apply_asset(a, "reject", reason_code_id="rc.reject.other", actor="human")
    # 時計を逆行させる（NTP 補正や手動変更で起きる）
    with env.store.transaction() as con:
        con.execute("UPDATE decision SET created_at = '1999-01-01T00:00:00Z' WHERE id = ?",
                    (second["decision_id"],))
    by_clock = rows(env.store, "SELECT created_at, verdict FROM decision WHERE subject_id=?"
                    " ORDER BY created_at DESC", (a,))
    assert by_clock[0]["verdict"] == "keep", "前提: 時計で選ぶと誤る並びになっていない"
    assert env.store.asset(a)["review_state"] == "rejected", "写しが挿入順で選んでいない"
    # 時計で選ぶ実装が出す値（'kept'）に写しを壊し、組み直しが挿入順で選ぶことを示す
    with env.store.transaction() as con:
        con.execute("UPDATE asset SET review_state='kept', review_reason_code_id='rc.keep.favorite'"
                    " WHERE id = ?", (a,))
    assert env.review.reconcile() == 1
    assert (env.store.asset(a)["review_state"],
            env.store.asset(a)["review_reason_code_id"]) == ("rejected", "rc.reject.other")


# ---- 8. まとまりの検査（§3.2）----


def test_items_must_cover_the_group_exactly(env):
    a, b, c = (add_asset(env.store, "a" * 64), add_asset(env.store, "b" * 64, "b.png"),
               add_asset(env.store, "c" * 64, "c.png"))
    group = make_group(env, [a, b])
    with pytest.raises(ReviewError) as got:
        env.review.apply_group(group["id"], [{"asset_id": a, "verdict": "keep"}], actor="human")
    assert got.value.status == 422
    assert got.value.details["missing"] == [b] and got.value.details["extra"] == []
    with pytest.raises(ReviewError) as got:
        env.review.apply_group(
            group["id"], [{"asset_id": a, "verdict": "keep"},
                          {"asset_id": b, "verdict": "keep"},
                          {"asset_id": c, "verdict": "keep"}], actor="human")
    assert got.value.details["missing"] == [] and got.value.details["extra"] == [c]
    with pytest.raises(ReviewError) as got:
        env.review.apply_group(group["id"], [], actor="human")
    assert got.value.details["missing"] == [a, b], "空の items が過不足として返らない"
    assert env.review.group_state(group["id"])["state"] == "open", "失敗したのに決定になった"


def test_duplicate_asset_id_in_items_is_422(env):
    a, b = add_asset(env.store, "a" * 64), add_asset(env.store, "b" * 64, "b.png")
    group = make_group(env, [a, b])
    assert status_of(env.review.apply_group, group["id"],
                     [{"asset_id": a, "verdict": "keep"}, {"asset_id": a, "verdict": "keep"},
                      {"asset_id": b, "verdict": "keep"}], actor="human") == 422


def test_create_group_validates_source_and_asset_ids(env):
    """点検 C5/D8/D9: 契約を落とす `source`・0 枚・文字列の `asset_ids` を弾く。"""
    a = add_asset(env.store, "a" * 64)
    assert status_of(env.review.create_group, asset_ids=[a], source="x") == 422
    assert status_of(env.review.create_group, asset_ids=[]) == 422
    assert status_of(env.review.create_group, asset_ids="abc") == 422     # 1 文字ずつに割れない
    got = env.review.create_group(asset_ids=[a], source="comfyui")
    assert got["source"] == "comfyui"
    assert rows(env.store, "SELECT count(*) AS n FROM review_group")[0]["n"] == 1


def test_every_reject_item_needs_its_own_reason(env):
    a, b = add_asset(env.store, "a" * 64), add_asset(env.store, "b" * 64, "b.png")
    group = make_group(env, [a, b])
    assert status_of(env.review.apply_group, group["id"],
                     [{"asset_id": a, "verdict": "keep"},
                      {"asset_id": b, "verdict": "reject"}], actor="human") == 422


def test_all_rejected_requires_the_group_reason(env):
    a, b = add_asset(env.store, "a" * 64), add_asset(env.store, "b" * 64, "b.png")
    group = make_group(env, [a, b])
    items = [{"asset_id": a, "verdict": "reject", "reason_code_id": "rc.reject.other"},
             {"asset_id": b, "verdict": "reject", "reason_code_id": "rc.reject.expression"}]
    assert status_of(env.review.apply_group, group["id"], items, actor="human") == 422
    ok = env.review.apply_group(group["id"], items,
                                group_reason_code_id="rc.reject.intent", actor="human")
    assert ok["group"]["decision"] == "all_rejected"


def test_policy_rules_are_enforced(env):
    a, b = add_asset(env.store, "a" * 64), add_asset(env.store, "b" * 64, "b.png")
    two_keeps = [{"asset_id": a, "verdict": "keep"}, {"asset_id": b, "verdict": "keep"}]
    one = make_group(env, [a, b], policy="pick_one")
    assert status_of(env.review.apply_group, one["id"], two_keeps, actor="human") == 422

    only_reject = make_group(env, [a, b], policy="all_reject_only")
    assert status_of(env.review.apply_group, only_reject["id"], two_keeps, actor="human") == 422

    many = make_group(env, [a, b], policy="pick_many")
    got = env.review.apply_group(many["id"], two_keeps, actor="human")
    assert got["group"]["decision"] == "selected"
    assert sorted(got["group"]["selected_asset_ids"]) == sorted([a, b])


def test_deciding_a_decided_group_is_409_group_decided(env):
    a, b = add_asset(env.store, "a" * 64), add_asset(env.store, "b" * 64, "b.png")
    group = make_group(env, [a, b])
    items = [{"asset_id": a, "verdict": "keep"},
             {"asset_id": b, "verdict": "reject", "reason_code_id": "rc.reject.other"}]
    env.review.apply_group(group["id"], items, actor="human")
    with pytest.raises(ReviewError) as got:
        env.review.apply_group(group["id"], items, actor="human")
    assert got.value.status == 409 and got.value.code == "group_decided"


# ---- 9. 枚ごとの理由が残る ----

def test_a_group_decision_supersedes_the_previous_group_decision(env):
    """点検 C7: まとまりの行も、**同じまとまりの直前の行**を指す（reopen → 再 decide で鎖が切れない）。"""
    a, b = add_asset(env.store, "a" * 64), add_asset(env.store, "b" * 64, "b.png")
    group = make_group(env, [a, b])
    first = env.review.apply_group(
        group["id"],
        [{"asset_id": a, "verdict": "keep"},
         {"asset_id": b, "verdict": "reject", "reason_code_id": "rc.reject.other"}], actor="human")
    env.review.reopen(group["id"], actor="human")
    second = env.review.apply_group(
        group["id"],
        [{"asset_id": b, "verdict": "keep"},
         {"asset_id": a, "verdict": "reject", "reason_code_id": "rc.reject.other"}], actor="human")
    got = rows(env.store, "SELECT subject_type, supersedes FROM decision WHERE id = ?",
               (second["decision_id"],))[0]
    assert got["subject_type"] == "group"
    assert got["supersedes"] == first["decision_id"], "まとまりの鎖が切れている（点検 C7）"


def test_group_decide_writes_per_image_reasons(env):
    a, b = add_asset(env.store, "a" * 64), add_asset(env.store, "b" * 64, "b.png")
    group = make_group(env, [a, b])
    got = env.review.apply_group(
        group["id"],
        [{"asset_id": a, "verdict": "keep", "reason_code_id": "rc.keep.as_intended"},
         {"asset_id": b, "verdict": "reject", "reason_code_id": "rc.reject.breakdown",
          "note": "右腕が溶けている"}], actor="human")
    assert got["group"]["state"] == "decided" and got["group"]["decision"] == "selected"
    assert got["group"]["selected_asset_ids"] == [a]
    # 契約の実例に合わせて、1 枚に決めたときはその枚のキープ理由をまとまりの理由に写す
    assert got["group"]["reason_code_id"] == "rc.keep.as_intended"
    slots = {i["asset_id"]: (i["review_state"], i["group_decision"], i["reason_code_id"])
             for i in got["items"]}
    assert slots[a] == ("kept", "selected", "rc.keep.as_intended")
    assert slots[b] == ("rejected", "not_selected", "rc.reject.breakdown")
    assert slots[b][2] and env.store.asset(b)["review_reason_code_id"] == "rc.reject.breakdown"
    # 枚ごとの理由が台帳にも残っている（台帳は消さない）
    assert [d["reason_code_id"] for d in decisions_for(env.store, b)] == ["rc.reject.breakdown"]
    assert decisions_for(env.store, b)[0]["group_decision"] == "not_selected"


def test_all_rejected_keeps_the_group_reason_and_each_image_reason(env):
    a, b = add_asset(env.store, "a" * 64), add_asset(env.store, "b" * 64, "b.png")
    group = make_group(env, [a, b])
    got = env.review.apply_group(
        group["id"],
        [{"asset_id": a, "verdict": "reject", "reason_code_id": "rc.reject.other"},
         {"asset_id": b, "verdict": "reject", "reason_code_id": "rc.reject.expression"}],
        group_reason_code_id="rc.reject.intent", note="どれも意図と違う", actor="human")
    assert got["group"]["decision"] == "all_rejected"
    assert got["group"]["selected_asset_ids"] == []
    assert got["group"]["reason_code_id"] == "rc.reject.intent"
    assert got["group"]["note"] == "どれも意図と違う"
    assert {i["group_decision"] for i in got["items"]} == {"all_rejected"}
    assert env.store.asset(a)["review_reason_code_id"] == "rc.reject.other"
    assert env.store.asset(b)["review_reason_code_id"] == "rc.reject.expression"
    group_row = rows(env.store, "SELECT * FROM decision WHERE subject_type='group'")[0]
    assert group_row["group_decision"] == "all_rejected"
    assert group_row["reason_code_id"] == "rc.reject.intent"


def test_group_decide_is_one_transaction(env, monkeypatch):
    """途中で失敗したら 1 行も入らない（§3.2）。"""
    a, b = add_asset(env.store, "a" * 64), add_asset(env.store, "b" * 64, "b.png")
    group = make_group(env, [a, b])
    original = ReviewService._materialize_asset

    def boom(self, con, asset_id):
        raise RuntimeError("とちゅうで落ちる")

    monkeypatch.setattr(ReviewService, "_materialize_asset", boom)
    with pytest.raises(RuntimeError):
        env.review.apply_group(
            group["id"],
            [{"asset_id": a, "verdict": "keep"},
             {"asset_id": b, "verdict": "reject", "reason_code_id": "rc.reject.other"}],
            actor="human")
    monkeypatch.setattr(ReviewService, "_materialize_asset", original)
    assert rows(env.store, "SELECT count(*) AS n FROM decision")[0]["n"] == 0
    assert env.review.group_state(group["id"])["state"] == "open"


# ---- 10. reopen は枚ごとの判断を消さない（点検 G7）----

def test_reopen_keeps_per_image_decisions(env):
    a, b = add_asset(env.store, "a" * 64), add_asset(env.store, "b" * 64, "b.png")
    group = make_group(env, [a, b])
    env.review.apply_group(
        group["id"],
        [{"asset_id": a, "verdict": "keep"},
         {"asset_id": b, "verdict": "reject", "reason_code_id": "rc.reject.other"}],
        group_reason_code_id=None, actor="human")
    before = rows(env.store, "SELECT count(*) AS n FROM decision")[0]["n"]
    got = env.review.reopen(group["id"], actor="human")
    assert got["group"]["state"] == "open"
    assert got["group"]["decision"] is None and got["group"]["selected_asset_ids"] == []
    assert got["group"]["reason_code_id"] is None and got["group"]["decided_at"] is None
    after = rows(env.store, "SELECT * FROM decision ORDER BY seq")
    assert len(after) == before, "reopen が台帳に行を足した"
    assert not [d for d in after if d["verdict"] == "clear"], "reopen が clear を書いている（点検 G7）"
    # 枚ごとの判断はそのまま残っている
    states = {i["asset_id"]: (i["review_state"], i["group_decision"]) for i in got["items"]}
    assert states[a] == ("kept", "selected") and states[b] == ("rejected", "not_selected")


# ---- 11. 結論が変わるときだけ open に戻す（点検 B4/G9）----

def test_rejecting_the_selected_asset_reopens_the_group(env):
    a, b = add_asset(env.store, "a" * 64), add_asset(env.store, "b" * 64, "b.png")
    group = make_group(env, [a, b])
    env.review.apply_group(
        group["id"],
        [{"asset_id": a, "verdict": "keep"},
         {"asset_id": b, "verdict": "reject", "reason_code_id": "rc.reject.other"}], actor="human")
    got = env.review.apply_asset(a, "reject", reason_code_id="rc.reject.breakdown", actor="human")
    assert group["id"] in got["reopened_group_ids"]
    assert env.review.group_state(group["id"])["state"] == "open"
    # 理由だけの変更（同じ verdict）では戻らない
    again = env.review.apply_asset(a, "reject", reason_code_id="rc.reject.other",
                                   note="理由だけ直した", actor="human")
    assert again["reopened_group_ids"] == []
    assert env.review.group_state(group["id"])["state"] == "open"


def test_changing_only_the_reason_keeps_the_group_decided(env):
    a, b = add_asset(env.store, "a" * 64), add_asset(env.store, "b" * 64, "b.png")
    group = make_group(env, [a, b])
    env.review.apply_group(
        group["id"],
        [{"asset_id": a, "verdict": "keep"},
         {"asset_id": b, "verdict": "reject", "reason_code_id": "rc.reject.other"}], actor="human")
    got = env.review.apply_asset(a, "keep", reason_code_id="rc.keep.finalize",
                                 note="理由だけ", actor="human")
    assert got["reopened_group_ids"] == []
    state = env.review.group_state(group["id"])
    assert state["state"] == "decided", "理由だけの変更でまとまりが未決定に戻った"
    assert state["decision"] == "selected"
    # 引き継いだ `group_decision` が最新の行に載っている
    newest = rows(env.store, "SELECT * FROM decision WHERE subject_id=? ORDER BY seq DESC LIMIT 1",
                  (a,))[0]
    assert newest["group_decision"] == "selected" and newest["group_id"] == group["id"]


def test_a_keep_on_a_not_selected_asset_reopens_only_pick_one(env):
    a, b = add_asset(env.store, "a" * 64), add_asset(env.store, "b" * 64, "b.png")
    one = make_group(env, [a, b], policy="pick_one", title="pick_one")
    env.review.apply_group(
        one["id"],
        [{"asset_id": a, "verdict": "keep"},
         {"asset_id": b, "verdict": "reject", "reason_code_id": "rc.reject.other"}], actor="human")
    got = env.review.apply_asset(b, "keep", reason_code_id="rc.keep.favorite", actor="human")
    assert one["id"] in got["reopened_group_ids"]
    assert env.review.group_state(one["id"])["state"] == "open"

    many = make_group(env, [a, b], policy="pick_many", title="pick_many")
    env.review.apply_group(
        many["id"],
        [{"asset_id": a, "verdict": "keep"},
         {"asset_id": b, "verdict": "reject", "reason_code_id": "rc.reject.other"}], actor="human")
    got = env.review.apply_asset(b, "keep", reason_code_id="rc.keep.favorite", actor="human")
    assert many["id"] not in got["reopened_group_ids"], "pick_many で結論が変わっていないのに戻した"
    assert env.review.group_state(many["id"])["state"] == "decided"


# ---- 11b. 監査 A2: 取りこぼしていた 2 つの経路（設計 §0.4 の 4 条件）----


def test_a_keep_on_an_all_rejected_group_reopens_it(env):
    """監査 A2-a: 「全部ボツ」と決めた 1 枚を後からキープしたら `open` に戻る。

    戻さないと、契約ファイルが `decision: "all_rejected"` と
    `items[a].verdict: "keep"` を同時に出す（他ツールが矛盾した結論を読む）。
    """
    a, b = add_asset(env.store, "a" * 64), add_asset(env.store, "b" * 64, "b.png")
    group = make_group(env, [a, b])
    env.review.apply_group(
        group["id"],
        [{"asset_id": a, "verdict": "reject", "reason_code_id": "rc.reject.other"},
         {"asset_id": b, "verdict": "reject", "reason_code_id": "rc.reject.expression"}],
        group_reason_code_id="rc.reject.intent", actor="human")

    got = env.review.apply_asset(a, "keep", reason_code_id="rc.keep.favorite", actor="human")
    assert group["id"] in got["reopened_group_ids"], "all_rejected への keep が open に戻していない"
    state = env.review.group_state(group["id"])
    assert state["state"] == "open" and state["decision"] is None
    assert state["selected_asset_ids"] == [] and state["reason_code_id"] is None
    # 結論が変わらない変更（同じ verdict の keep を重ねる）では戻らない
    again = env.review.apply_asset(a, "keep", reason_code_id="rc.keep.as_intended", actor="human")
    assert again["reopened_group_ids"] == []


def test_clearing_the_selected_asset_reopens_the_group(env):
    """監査 A2-b: 選ばれた 1 枚を取り消したら `open` に戻り、`selected_asset_ids` が空になる。

    戻さないと、契約ファイルが `selected_asset_ids: [a]` と
    `assets[a].review_state: "unreviewed"` を同時に出す。
    """
    a, b = add_asset(env.store, "a" * 64), add_asset(env.store, "b" * 64, "b.png")
    group = make_group(env, [a, b])
    env.review.apply_group(
        group["id"],
        [{"asset_id": a, "verdict": "keep"},
         {"asset_id": b, "verdict": "reject", "reason_code_id": "rc.reject.other"}], actor="human")
    assert env.review.group_state(group["id"])["selected_asset_ids"] == [a]

    got = env.review.apply_asset(a, "clear", actor="human")
    assert group["id"] in got["reopened_group_ids"], "selected の clear が open に戻していない"
    state = env.review.group_state(group["id"])
    assert state["state"] == "open"
    assert state["selected_asset_ids"] == []
    assert state["decision"] is None
    # 台帳は消さない（取り消しも追記）
    assert [d["verdict"] for d in decisions_for(env.store, a)] == ["keep", "clear"]


def test_clearing_all_the_selected_images_in_pick_many_reopens(env):
    """監査 A2-b の帰結: `pick_many` で選ばれた枚が 0 になるときも `open` に戻る。"""
    a, b = add_asset(env.store, "a" * 64), add_asset(env.store, "b" * 64, "b.png")
    group = make_group(env, [a, b], policy="pick_many")
    env.review.apply_group(
        group["id"],
        [{"asset_id": a, "verdict": "keep"}, {"asset_id": b, "verdict": "keep"}], actor="human")
    assert sorted(env.review.group_state(group["id"])["selected_asset_ids"]) == sorted([a, b])

    first = env.review.apply_asset(a, "clear", actor="human")
    assert group["id"] in first["reopened_group_ids"]
    assert env.review.apply_asset(b, "clear", actor="human")["asset"]["review_state"] == "unreviewed"
    state = env.review.group_state(group["id"])
    assert state["state"] == "open"
    assert state["selected_asset_ids"] == []
    assert {i["review_state"] for i in state["items"]} == {"unreviewed"}


# ---- 14. 別の Store（別プロセスの走査）が判断を消さない（点検 B5）----

def test_decision_survives_a_concurrent_store_scanning(tmp_path):
    root = tmp_path / "root"
    make_png(root / "a.png")
    data = tmp_path / "data"
    server = Store(data)
    review = ReviewService(server)
    try:
        scan(server, [str(root)])
        asset_id = server.assets()[0]["id"]
        review.apply_asset(asset_id, "keep", reason_code_id="rc.keep.favorite", actor="human")

        other = Store(data)
        try:
            stats = scan(other, [str(root)])
            assert stats["created"] == 0 and stats["known"] == 1
            assert other.asset(asset_id)["review_state"] == "kept"
        finally:
            other.close()
        assert server.asset(asset_id)["review_state"] == "kept"
        assert rows(server, "SELECT count(*) AS n FROM decision")[0]["n"] == 1
    finally:
        server.close()


# ---- 15. 新しい口にも Host / Origin / Content-Type が効く（点検 C15）----

def test_new_post_endpoints_are_guarded(tmp_path, monkeypatch):
    monkeypatch.setenv("IMAGE_REVIEWER_DATA", str(tmp_path / "data"))
    from fastapi.testclient import TestClient

    from image_reviewer.app import create_app

    app = create_app()
    human = {"X-Image-Reviewer-Actor": "human"}
    with TestClient(app, base_url="http://127.0.0.1") as client:
        asset_id = add_asset(app.state.store, "a" * 64)
        body = {"subject_type": "asset", "subject_id": asset_id, "verdict": "keep"}
        for path in ("/api/reviews", "/api/groups/missing/decide", "/api/groups/missing/reopen",
                     "/api/export/review.json", "/api/reason-codes"):
            assert client.post(path, json=body,
                               headers={"host": "evil.example"}).status_code == 403, path
            assert client.post(path, json=body,
                               headers={"origin": "http://evil.example"}).status_code == 403, path
            assert client.post(path, content=b"{}",
                               headers={"content-type": "text/plain"}).status_code == 403, path
        # 正しい要求は通る（守りが強すぎない）
        assert client.post("/api/reviews", json=body, headers=human).status_code == 200
        assert client.get("/api/health").status_code == 200


# ---- API の形（現在値を返す）----

def test_api_returns_the_current_state_and_the_ledger(tmp_path, monkeypatch):
    monkeypatch.setenv("IMAGE_REVIEWER_DATA", str(tmp_path / "data"))
    from fastapi.testclient import TestClient

    from image_reviewer.app import create_app

    app = create_app()
    human = {"X-Image-Reviewer-Actor": "human"}
    with TestClient(app, base_url="http://127.0.0.1") as client:
        a, b = add_asset(app.state.store, "a" * 64), add_asset(app.state.store, "b" * 64, "b.png")
        created = client.post("/api/groups", json={"title": "g", "kind": "manual",
                                                  "asset_ids": [a, b], "policy": "pick_one"})
        assert created.status_code == 200, created.text
        group = created.json()
        assert group["source"] == "manual" and group["policy"] == "pick_one"
        assert group["state"] == "open" and group["decision"] is None

        got = client.post(f"/api/groups/{group['id']}/decide",
                          json={"items": [
                              {"asset_id": a, "verdict": "keep"},
                              {"asset_id": b, "verdict": "reject",
                               "reason_code_id": "rc.reject.other"}]}, headers=human)
        assert got.status_code == 200, got.text
        assert got.json()["group"]["state"] == "decided"
        assert got.json()["reopened_group_ids"] == []

        listed = client.get("/api/groups", params={"state": "decided"})
        assert listed.json()["total"] == 1
        assert listed.json()["items"][0]["kept_count"] == 1

        ledger = client.get("/api/reviews", params={"group": group["id"]})
        assert ledger.json()["total"] == 3            # 枚ごと 2 + まとまり 1
        assert [i["verdict"] for i in ledger.json()["items"]][0] == "keep"

        reasons = client.get("/api/reason-codes", params={"applies_to": "reject"})
        labels = [r["label"] for r in reasons.json()["items"]]
        assert "破綻（体・関節・結合）" in labels
        assert "意図どおり" not in labels, "applies_to の絞り込みが効いていない"

        added = client.post("/api/reason-codes", json={"label": "自分の理由", "applies_to": "both"})
        assert added.status_code == 200 and added.json()["builtin"] == 0
        patched = client.patch(f"/api/reason-codes/{added.json()['id']}",
                               json={"label": "改名した"})
        assert patched.json()["label"] == "改名した"
        # builtin の applies_to は変えられない（点検 D9）
        assert client.patch("/api/reason-codes/rc.keep.favorite",
                            json={"applies_to": "reject"}).status_code == 422
        assert client.patch("/api/reason-codes/rc.nope", json={"label": "x"}).status_code == 404
        # まとまりを消さずに open に戻せる
        reopened = client.post(f"/api/groups/{group['id']}/reopen", json={}, headers=human)
        assert reopened.status_code == 200 and reopened.json()["group"]["state"] == "open"

        # 知らないまとまりは 404
        assert client.get("/api/groups/nope").status_code == 404
        assert client.post("/api/groups/nope/reopen", json={}, headers=human).status_code == 404
        # subject_type が asset 以外は 422（§3.1）
        assert client.post("/api/reviews", json={"subject_type": "group", "subject_id": group["id"],
                                                 "verdict": "keep"},
                           headers=human).status_code == 422
