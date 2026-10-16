"""エージェントからの要求（P6-1a）のテスト。

設計: docs/p6-design.md §0.2〜§0.4・§0.9・§3.2〜§3.5・§4.1・§6.1
テスト方針: §8.1 の表（**何を壊すと落ちるか**）。各テストの docstring に、表と同じ番号で
「何を壊すと落ちるか」を書く（P5 の監査 F1「何も守っていないテスト」の教訓）。

`tmp_path` は `tests/conftest.py` が用意する（実データは使わない。§8 の末尾）。
"""

from __future__ import annotations

import json
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

from image_reviewer import db
from image_reviewer.export import ExportService
from image_reviewer.review import ReviewError, ReviewService
from image_reviewer.review_requests import (
    MAX_ASK,
    MAX_CONDITIONS,
    MAX_TEXT,
    ReviewRequestService,
)
from image_reviewer.store import Store

# 契約 `ReviewRequest` の鍵（`additionalProperties: false`）。写し間違いをここで落とす
REQUEST_KEYS = {"id", "group_id", "state", "target_key", "actor", "ask", "conditions", "origin",
                "wants", "ai", "created_at", "closed_at", "closed_by", "decline_note",
                "superseded_by", "response"}


# ---- 道具 ----


def add_asset(store: Store, sha: str, name: str = "a.png", **kw) -> str:
    """合成の 1 枚を登録する（実データに依存しない）。"""
    args = {"size": 100, "mtime_ns": 1, "width": 16, "height": 16, "fmt": "png",
            "meta": None, "note": None}
    args.update(kw)
    path = store.data_dir.parent / "images" / name
    asset_id, _ = store.register(sha256=sha, path=str(path), **args)
    return asset_id


def rows(store: Store, sql: str, args: tuple = ()) -> list:
    return store.con.execute(sql, args).fetchall()


def status_of(func, *args, **kw) -> int:
    with pytest.raises(ReviewError) as got:
        func(*args, **kw)
    return got.value.status


def error_of(func, *args, **kw) -> ReviewError:
    with pytest.raises(ReviewError) as got:
        func(*args, **kw)
    return got.value


def snapshot(root: Path) -> set[str]:
    """ファイルの**一覧**（GET が書かないことの検査。中身は見ない）。"""
    return {str(p.relative_to(root)) for p in root.rglob("*") if p.is_file()}


@pytest.fixture
def env(tmp_path):
    """Store + ReviewService + ExportService + ReviewRequestService（遅延書き出しは発火しない）。"""
    store = Store(tmp_path / "data")
    exporter = ExportService(store, delay=3600.0, flush_on_start=False)
    review = ReviewService(store, exporter=exporter)
    requests = ReviewRequestService(store, review)
    try:
        yield SimpleNamespace(store=store, exporter=exporter, review=review, requests=requests,
                              tmp_path=tmp_path)
    finally:
        exporter.close()
        store.close()


def decide(env, group_id, items, **kw):
    return env.review.apply_group(group_id, items, actor="human", **kw)


# ---- 1. 差し替え（§0.3）----


def test_a_second_request_with_the_same_target_key_supersedes_the_first(env):
    """§8.1 の 1: `ux_request_target_open` を外す / `state='open'` で絞らないと落ちる。"""
    a = add_asset(env.store, "a" * 64)
    first = env.requests.create(asset_ids=[a], target_key="cut-1", ask="1 枚")
    second = env.requests.create(asset_ids=[a], target_key="cut-1", ask="1 枚（やり直し）")

    assert "superseded_request_id" not in first
    assert second["superseded_request_id"] == first["request_id"]
    got = env.requests.get(first["request_id"])
    assert got["state"] == "superseded"
    assert got["superseded_by"] == second["request_id"]
    assert got["closed_at"] is None, "差し替えは「閉じた」ではない（§4.1）"
    assert env.requests.get(second["request_id"])["state"] == "open"
    assert len(rows(env.store, "SELECT * FROM review_request")) == 2


def test_a_later_request_does_not_touch_done_or_declined_ones(env):
    """§8.1 の 2: 差し替えの条件から `state='open'` を外すと、履歴が書き換わって落ちる。"""
    a, b = add_asset(env.store, "a" * 64), add_asset(env.store, "b" * 64, "b.png")
    done = env.requests.create(asset_ids=[a], target_key="k-done")
    decide(env, done["group_id"], [{"asset_id": a, "verdict": "keep"}])
    declined = env.requests.create(asset_ids=[b], target_key="k-declined")
    env.requests.decline(declined["request_id"], "別のカットで使った", actor="human")

    for old, key in ((done, "k-done"), (declined, "k-declined")):
        new = env.requests.create(asset_ids=[a, b], target_key=key)
        assert "superseded_request_id" not in new
        row = rows(env.store, "SELECT * FROM review_request WHERE id = ?", (old["request_id"],))[0]
        assert row["state"] in ("done", "declined"), "閉じた要求を差し替えた"
        assert row["superseded_by"] is None


def test_eight_concurrent_requests_leave_exactly_one_open(env):
    """§8.1 の 3: 判定と更新を別の取引に分けると落ちる（**別の接続 × 8** で試す。点検 C9）。

    同じプロセスの `Store._lock` では隠れるので、スレッドごとに `Store` を作る。
    """
    a = add_asset(env.store, "a" * 64)
    data = env.store.data_dir
    results: list[dict] = []
    errors: list[BaseException] = []
    start = threading.Barrier(8)

    def run():
        store = Store(data)
        try:
            review = ReviewService(store, reconcile_on_start=False)
            svc = ReviewRequestService(store, review)
            start.wait(timeout=15)
            results.append(svc.create(asset_ids=[a], target_key="cut-1", ask="同時"))
        except BaseException as exc:                    # noqa: BLE001  集めて最後に出す
            errors.append(exc)
        finally:
            store.close()

    threads = [threading.Thread(target=run) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=60)
    assert not errors, f"同時に投げて失敗した: {errors!r}"
    assert len(results) == 8, "8 本そろわなかった"

    all_rows = rows(env.store, "SELECT * FROM review_request")
    open_rows = [r for r in all_rows if r["state"] == "open"]
    superseded = [r for r in all_rows if r["state"] == "superseded"]
    assert len(all_rows) == 8
    assert len(open_rows) == 1, f"open が {len(open_rows)} 本ある（部分索引が効いていない）"
    assert len(superseded) == 7
    # `superseded_by` が 1 本の鎖になり、行き止まりが open の 1 本
    by_id = {r["id"]: r["superseded_by"] for r in all_rows}
    for row in superseded:
        seen, cur = {row["id"]}, row["superseded_by"]
        while cur is not None:
            assert cur not in seen, "superseded_by が輪になっている"
            assert cur in by_id, "superseded_by が知らない id を指している"
            seen.add(cur)
            cur = by_id[cur]
        assert seen & {open_rows[0]["id"]}, "鎖が open の 1 本に繋がっていない"


# ---- 2. 判断で閉じる（§0.4 / §0.2）----


def test_decide_closes_the_open_request_and_reports_it(env):
    """§8.1 の 5: 判断で閉じる処理を消すと落ちる（合格の線 2）。"""
    a, b = add_asset(env.store, "a" * 64), add_asset(env.store, "b" * 64, "b.png")
    req = env.requests.create(asset_ids=[a, b], ask="1 枚選んで")
    got = decide(env, req["group_id"],
                 [{"asset_id": a, "verdict": "keep"},
                  {"asset_id": b, "verdict": "reject", "reason_code_id": "rc.reject.other"}],
                 group_reason_code_id="rc.keep.favorite")
    assert got["closed_request_ids"] == [req["request_id"]]
    row = env.requests.get(req["request_id"])
    assert row["state"] == "done"
    assert row["closed_by"] == "human"
    assert row["closed_at"] is not None
    assert row["response"]["selected_asset_ids"] == [a]
    assert row["response"]["reason_code_id"] == "rc.keep.favorite"
    assert row["response"]["reason_label"] is not None
    # 閉じた要求は既定の一覧に出ない（§5.1 の既定は open だけ）
    assert [r["id"] for r in env.requests.list()["items"]] == []
    assert env.requests.list(state="done")["counts"] == {"open": 0}


def test_the_stored_response_survives_decide_and_reopen(env):
    """§8.1 の 4: 応答を保存せず毎回導出するように変えると落ちる（`annotations` は除く）。"""
    a, b = add_asset(env.store, "a" * 64), add_asset(env.store, "b" * 64, "b.png")
    req = env.requests.create(asset_ids=[a, b], ask="1 枚選んで")
    decide(env, req["group_id"],
           [{"asset_id": a, "verdict": "keep"},
            {"asset_id": b, "verdict": "reject", "reason_code_id": "rc.reject.other"}],
           group_reason_code_id="rc.keep.favorite")
    first = env.requests.get(req["request_id"])["response"]
    # 閉じた後にマスタを改名しても、答えの写しは変わらない（§0.2。design.md の「当時の値」）
    env.review.patch_reason_code("rc.keep.favorite", {"label": "後から改名した"})
    env.review.reopen(req["group_id"], actor="human")
    second = env.requests.get(req["request_id"])["response"]

    def strip(d: dict) -> dict:
        """`annotations` を除いた写し（判断の後に増える欄。点検 B3）。"""
        return {k: v for k, v in d.items() if k != "annotations"}

    assert strip(first) == strip(second)
    assert second["reason_label"] == first["reason_label"] != "後から改名した"
    # `annotations` だけは**読むときに導出**する（P6-2 で中身が入る。§0.2 / 点検 B3）
    assert second["annotations"] == []


def test_reopen_does_not_reopen_the_request(env):
    """§8.1 の 6: `reopen` で要求を開き直すように変えると落ちる（§0.4）。"""
    a = add_asset(env.store, "a" * 64)
    req = env.requests.create(asset_ids=[a], ask="1 枚")
    decide(env, req["group_id"], [{"asset_id": a, "verdict": "keep"}])
    closed_at = env.requests.get(req["request_id"])["closed_at"]
    env.review.reopen(req["group_id"], actor="human")
    row = env.requests.get(req["request_id"])
    assert row["state"] == "done"
    assert row["closed_at"] == closed_at
    assert row["response"]["selected_asset_ids"] == [a]


def test_a_new_request_for_the_same_group_after_a_decision(env):
    """判断で閉じた後は、同じまとまりに**新しい要求**を出せない（`decided` は 422。点検 C2）。"""
    a = add_asset(env.store, "a" * 64)
    req = env.requests.create(asset_ids=[a], ask="1 枚")
    decide(env, req["group_id"], [{"asset_id": a, "verdict": "keep"}])
    assert status_of(env.requests.create, group_id=req["group_id"]) == 422
    env.review.reopen(req["group_id"], actor="human")
    again = env.requests.create(group_id=req["group_id"], ask="やり直し")
    assert again["group_id"] == req["group_id"] and again["state"] == "open"


# ---- 3. 断る（§3.5）----


def test_decline_needs_a_note_and_is_idempotent(env):
    """§8.1 の 7: 断りの理由の検査を外すと落ちる（`design.md` §9.6）。"""
    a = add_asset(env.store, "a" * 64)
    req = env.requests.create(asset_ids=[a], ask="1 枚")
    assert status_of(env.requests.decline, req["request_id"], "   ", actor="human") == 422
    assert status_of(env.requests.decline, req["request_id"], None, actor="human") == 422
    got = env.requests.decline(req["request_id"], "この 8 枚はもう別のカットで使った", actor="human")
    assert got == {"id": req["request_id"], "state": "declined",
                   "decline_note": "この 8 枚はもう別のカットで使った"}
    # 同じ理由の再送は 200（同じ結果。点検 B5）
    assert env.requests.decline(req["request_id"], got["decline_note"], actor="human") == got
    # 違う理由は 409（状態機械が冪等性を与える。§3.5）
    err = error_of(env.requests.decline, req["request_id"], "別の理由", actor="human")
    assert err.status == 409 and err.code == "request_not_open" and err.details == {"state": "declined"}
    row = rows(env.store, "SELECT * FROM review_request WHERE id = ?", (req["request_id"],))[0]
    assert (row["state"], row["decline_note"]) == ("declined", got["decline_note"])
    # 閉じた後も `open` の一覧に出ない
    assert [r["id"] for r in env.requests.list(state="all")["items"]] == [req["request_id"]]


def test_only_a_human_can_decline_and_decide(env):
    """§8.1 の 8: `human` の検査を外すと落ちる（口ごとに確かめる）。"""
    a = add_asset(env.store, "a" * 64)
    # 要求を**出す**のはエージェントの仕事（actor は自己申告。§3.1）
    req = env.requests.create(asset_ids=[a], ask="1 枚", actor="agent")
    assert req["state"] == "open"
    assert status_of(env.requests.decline, req["request_id"], "理由", actor="agent") == 403
    assert status_of(env.requests.decline, req["request_id"], "理由", actor="robot") == 403
    assert status_of(env.review.apply_group, req["group_id"],
                     [{"asset_id": a, "verdict": "keep"}], actor="agent") == 403
    # 断られていない（403 の後始末）
    assert env.requests.get(req["request_id"])["state"] == "open"


# ---- 4. 対象の解決（§0.10 / §3.2 の検査）----


def test_a_registered_path_resolves_to_the_same_asset_as_the_id(env):
    """§8.1 の 9: パスの解決を外すと落ちる（`store.location_of()` を通す。点検 C1）。"""
    a = add_asset(env.store, "a" * 64, "a.png")
    path = str(env.store.data_dir.parent / "images" / "a.png")
    by_path = env.requests.create(asset_ids=[path], ask="パスで")
    group = env.review.group_state(by_path["group_id"])
    assert [i["id"] for i in group["items"]] == [a]
    assert (group["kind"], group["source"], group["source_ref"]) == (
        "request", "request", by_path["request_id"])
    # 同じ画像を id とパスの両方で書いても 1 枚に畳む
    mixed = env.requests.create(asset_ids=[a, path.upper()], ask="両方で")
    assert [i["id"] for i in env.review.group_state(mixed["group_id"])["items"]] == [a]
    # 知らないパスは 422（`unknown_paths`）。知らない id は `unknown_asset_ids`
    err = error_of(env.requests.create, asset_ids=[r"C:\nope\x.png"])
    assert err.status == 422 and err.details == {"unknown_paths": [r"C:\nope\x.png"]}
    unknown_id = db.ulid()
    err = error_of(env.requests.create, asset_ids=[unknown_id])
    assert err.status == 422 and err.details == {"unknown_asset_ids": [unknown_id]}
    assert len(rows(env.store, "SELECT * FROM review_request")) == 2, "失敗した要求の行が増えた"


def test_create_needs_exactly_one_of_asset_ids_and_group_id(env):
    """§3.2 の表: 両方 / どちらも無い は 422（`details.fields.asset_ids`）。"""
    a = add_asset(env.store, "a" * 64)
    group = env.review.create_group(asset_ids=[a])
    for kw in ({"asset_ids": [a], "group_id": group["id"]}, {}, {"asset_ids": [], "group_id": None}):
        err = error_of(env.requests.create, **kw)
        assert err.status == 422 and err.details == {"fields": {"asset_ids": "どちらか一方が要ります"}}
    assert status_of(env.requests.create, group_id="01MISSING") == 404
    assert status_of(env.requests.create, asset_ids="a" * 64) == 422, "文字列は配列ではない"


def test_create_validates_the_vocabulary_and_the_lengths(env):
    """§3.2 の表: `policy` / 長さ / `ai_pick_asset_id` の検査。"""
    a, b = add_asset(env.store, "a" * 64), add_asset(env.store, "b" * 64, "b.png")
    err = error_of(env.requests.create, asset_ids=[a], policy="nope")
    assert err.status == 422 and err.details == {"policy": "pick_one | pick_many | all_reject_only"}
    err = error_of(env.requests.create, asset_ids=[a], ask="あ" * (MAX_ASK + 1))
    assert err.status == 422 and "ask" in err.details["fields"]
    err = error_of(env.requests.create, asset_ids=[a],
                   conditions=["c"] * (MAX_CONDITIONS + 1))
    assert err.status == 422 and "conditions" in err.details["fields"]
    err = error_of(env.requests.create, asset_ids=[a], origin="o" * (MAX_TEXT + 1))
    assert err.status == 422 and "origin" in err.details["fields"]
    err = error_of(env.requests.create, asset_ids=[a], target_key="k" * (MAX_TEXT + 1))
    assert err.status == 422 and "target_key" in err.details["fields"]
    err = error_of(env.requests.create, asset_ids=[a], ai_pick_asset_id=b)
    assert err.status == 422 and err.details == {"ai_pick_asset_id": b}
    assert rows(env.store, "SELECT * FROM review_request") == []


def test_unknown_wants_are_ignored(env):
    """§8.1 の 10: `wants` の未知語で 422 を返すように変えると落ちる（§0.10）。"""
    a = add_asset(env.store, "a" * 64)
    req = env.requests.create(asset_ids=[a], wants=["selected_ids", "まだ知らない語"])
    got = env.requests.get(req["request_id"])
    assert got["wants"] == ["selected_ids", "まだ知らない語"]
    # 無ければ `null` ではなく `[]`（契約が `type: array`。点検 D1）
    other = env.requests.create(asset_ids=[a], ask="指定なし")
    assert env.requests.get(other["request_id"])["conditions"] == []
    assert env.requests.get(other["request_id"])["wants"] == []
    assert env.requests.get(other["request_id"])["ai"] is None


# ---- 5. 再送（§0.9 / 点検 B4）----


def test_the_same_token_and_target_key_twice_writes_one_row(env):
    """§8.1 の 25: `client_token` の照合を `target_key` の後ろに回すと落ちる（点検 B4）。"""
    a = add_asset(env.store, "a" * 64)
    first = env.requests.create(asset_ids=[a], target_key="cut-1", ask="1 枚",
                                client_token="tok-1")
    again = env.requests.create(asset_ids=[a], target_key="cut-1", ask="1 枚",
                                client_token="tok-1")
    assert again["replayed"] is True
    assert again["request_id"] == first["request_id"]
    assert "superseded_request_id" not in again
    all_rows = rows(env.store, "SELECT * FROM review_request")
    assert len(all_rows) == 1 and all_rows[0]["state"] == "open"
    assert len(rows(env.store, "SELECT * FROM review_group")) == 1, "再送でまとまりが増えた"
    # パスで送っても同じ対象（id と同じ集合）なら再送として扱う
    path = str(env.store.data_dir.parent / "images" / "a.png")
    same = env.requests.create(asset_ids=[path], target_key="cut-1", ask="1 枚",
                               client_token="tok-1")
    assert same["replayed"] is True and same["request_id"] == first["request_id"]
    assert len(rows(env.store, "SELECT * FROM review_request")) == 1


def test_the_same_token_with_a_different_payload_is_409(env):
    """§3.2 の表: 同じ `client_token` で中身が違う → 409 `client_token_conflict`。"""
    a = add_asset(env.store, "a" * 64)
    env.requests.create(asset_ids=[a], ask="1 枚", client_token="tok-2")
    err = error_of(env.requests.create, asset_ids=[a], ask="ちがう用件", client_token="tok-2")
    assert err.status == 409 and err.code == "client_token_conflict"
    assert len(rows(env.store, "SELECT * FROM review_request")) == 1
    # 閉じた後（`done`）の再送も 200 で返す（点検 B4: 再送が失敗しない）
    group_id = rows(env.store, "SELECT * FROM review_request")[0]["group_id"]
    decide(env, group_id, [{"asset_id": a, "verdict": "keep"}])
    again = env.requests.create(asset_ids=[a], ask="1 枚", client_token="tok-2")
    assert again["replayed"] is True and again["state"] == "done"


# ---- 6. 一覧と取得（§3.3 / §3.4）----


def test_list_defaults_to_open_newest_first_and_pages_with_a_cursor(env):
    """§3.3: 既定は `open`、`created_at DESC, id DESC` のキーセット。**書かない**（§0.6）。"""
    a = add_asset(env.store, "a" * 64)
    made = [env.requests.create(asset_ids=[a], ask=f"ask{i}", target_key=f"k{i}")["request_id"]
            for i in range(3)]
    done = env.requests.create(asset_ids=[a], ask="決定済み")
    decide(env, done["group_id"], [{"asset_id": a, "verdict": "keep"}])

    page = env.requests.list()
    assert page["counts"] == {"open": 3}
    assert sorted(r["id"] for r in page["items"]) == sorted(made)
    assert all(r["state"] == "open" for r in page["items"])
    stamp_of = [(r["created_at"], r["id"]) for r in page["items"]]
    assert stamp_of == sorted(stamp_of, reverse=True), "並びが `created_at DESC, id DESC` でない"
    # カーソルで 2 件 → 1 件（重複も抜けも無い）
    first = env.requests.list(limit=2)
    assert len(first["items"]) == 2 and first["next_cursor"]
    second = env.requests.list(limit=2, cursor=first["next_cursor"])
    assert len(second["items"]) == 1 and second["next_cursor"] is None
    got = [r["id"] for r in first["items"] + second["items"]]
    assert sorted(got) == sorted(made) and len(set(got)) == 3
    # `state` と `target_key` で絞れる。件数だけも取れる
    assert [r["id"] for r in env.requests.list(state="done")["items"]] == [done["request_id"]]
    everything = env.requests.list(state="all")["items"]
    assert sorted(r["id"] for r in everything) == sorted(made + [done["request_id"]])
    assert [r["id"] for r in env.requests.list(target_key="k1")["items"]] == [made[1]]
    only_counts = env.requests.list(count_only=True)
    assert only_counts == {"items": [], "next_cursor": None, "counts": {"open": 3}}
    err = error_of(env.requests.list, state="nope")
    assert err.status == 422
    err = error_of(env.requests.list, cursor="!!!not-base64!!!")
    assert err.status == 422 and "cursor" in err.details


def test_get_returns_the_contract_shape_and_404_for_unknown(env):
    """§3.4: 契約と同じ形。`response` は `open` なら `null`、`conditions` / `wants` は `[]`。"""
    a = add_asset(env.store, "a" * 64)
    req = env.requests.create(asset_ids=[a], ask="1 枚選んで", conditions=["左手の形"],
                              origin="作品A / カット03", ai_pick_asset_id=a, ai_note="手が素直",
                              target_key="cut-1", actor="agent")
    got = env.requests.get(req["request_id"])
    assert set(got) == REQUEST_KEYS, f"契約と形が違う: {sorted(set(got) ^ REQUEST_KEYS)}"
    assert got["state"] == "open" and got["response"] is None and got["closed_at"] is None
    # P6-1b の監査（申し送り 1）: `pick_index` を足した（画面が「AI の推し: N 番」を 1 回で出せる）
    assert got["ai"] == {"pick_asset_id": a, "note": "手が素直", "pick_index": 1}
    assert got["conditions"] == ["左手の形"] and got["wants"] == []
    assert got["actor"] == "agent" and got["target_key"] == "cut-1"
    assert status_of(env.requests.get, "01MISSING") == 404


def test_reading_requests_writes_no_files(env):
    """§0.6 / §8.1 の 17: GET が書き出すように変えると落ちる（`GET` は書かない）。"""
    a = add_asset(env.store, "a" * 64)
    req = env.requests.create(asset_ids=[a], ask="1 枚", target_key="cut-1")
    before = snapshot(env.tmp_path)
    env.requests.list()
    env.requests.list(state="all", count_only=True)
    env.requests.get(req["request_id"])
    env.exporter.build("all")
    env.exporter.build(f"group:{req['group_id']}")
    assert snapshot(env.tmp_path) == before, "読むだけでファイルが増えた"


# ---- 7. 古いまとまりを閉じる（§0.3 / 点検 A3）----


def test_superseding_hides_the_old_group_only_when_it_has_no_decisions(env):
    """§8.1 の 27: 古いまとまりを閉じる処理を外すと落ちる（点検 A3 / G6）。"""
    a, b, c = (add_asset(env.store, "a" * 64), add_asset(env.store, "b" * 64, "b.png"),
               add_asset(env.store, "c" * 64, "c.png"))
    old = env.requests.create(asset_ids=[a], target_key="cut-1", ask="1 枚")
    new = env.requests.create(asset_ids=[b], target_key="cut-1", ask="1 枚（やり直し）")
    assert env.review.group_state(old["group_id"])["superseded_by"] == new["request_id"]
    # `GET /api/groups` の既定と `review.json` の `groups[]` の既定から外れる
    listed = [g["id"] for g in env.review.list_groups()["items"]]
    assert old["group_id"] not in listed and new["group_id"] in listed
    assert old["group_id"] in [g["id"] for g in env.review.list_groups(include_superseded=True)["items"]]
    doc = env.exporter.build("all")
    assert old["group_id"] not in [g["id"] for g in doc["groups"]]
    assert old["group_id"] in [g["id"] for g in env.exporter.build("all", include_superseded=True)["groups"]]
    # 名指し（`scope=group:`）では印が入っていても返す（読むために指定している）
    named = env.exporter.build(f"group:{old['group_id']}")
    assert [g["id"] for g in named["groups"]] == [old["group_id"]]
    assert named["groups"][0]["superseded_by"] == new["request_id"]

    # 判断がある古いまとまりは**残す**（履歴。点検 A3）
    decided_old = env.requests.create(asset_ids=[c], target_key="cut-2", ask="1 枚")
    decide(env, decided_old["group_id"], [{"asset_id": c, "verdict": "keep"}])
    decided_new = env.requests.create(asset_ids=[a], target_key="cut-2", ask="やり直し")
    assert env.review.group_state(decided_old["group_id"])["superseded_by"] is None
    assert decided_old["request_id"] != decided_new["request_id"]


# ---- 8. 書き出し（§6.1）----


def test_requests_appear_in_the_export_per_scope(env):
    """§6.1 / §8.1 の 21・31: 要求が `scope` どおりに入り、`response` は**オブジェクト**で出る。"""
    a, b, c = (add_asset(env.store, "a" * 64), add_asset(env.store, "b" * 64, "b.png"),
               add_asset(env.store, "c" * 64, "c.png"))
    r1 = env.requests.create(asset_ids=[a, b], ask="1 枚")
    decide(env, r1["group_id"],
           [{"asset_id": a, "verdict": "keep"},
            {"asset_id": b, "verdict": "reject", "reason_code_id": "rc.reject.other"}])
    r2 = env.requests.create(asset_ids=[c], ask="別の 1 枚")

    doc = env.exporter.build("all")
    by_id = {r["id"]: r for r in doc["requests"]}
    assert set(by_id) == {r1["request_id"], r2["request_id"]}
    assert set(by_id[r1["request_id"]]) == REQUEST_KEYS
    assert isinstance(by_id[r1["request_id"]]["response"], dict), "写しが文字列のまま出た（点検 F11）"
    assert by_id[r1["request_id"]]["response"]["selected_asset_ids"] == [a]
    assert by_id[r2["request_id"]]["response"] is None
    assert (by_id[r1["request_id"]]["state"], by_id[r2["request_id"]]["state"]) == ("done", "open")
    # `scope` で絞る（`asset:` はその画像を含むまとまりの要求だけ）
    assert [r["id"] for r in env.exporter.build(f"group:{r1['group_id']}")["requests"]] == \
        [r1["request_id"]]
    assert [r["id"] for r in env.exporter.build(f"asset:{a}")["requests"]] == [r1["request_id"]]
    assert [r["id"] for r in env.exporter.build(f"asset:{c}")["requests"]] == [r2["request_id"]]
    # 決定性（`generated_at` を除いて 2 回で同一。§6.1）
    first, second = env.exporter.build("all"), env.exporter.build("all")
    assert first.pop("generated_at") is not None
    assert second.pop("generated_at") is not None
    assert first == second


# ---- 9. 口の守り（§8.1 の 24）----


def test_the_new_endpoints_are_guarded_and_create_is_201(tmp_path, monkeypatch):
    """§8.1 の 24: `include_router` から外すと落ちる（守りは middleware 任せ）。"""
    monkeypatch.setenv("IMAGE_REVIEWER_DATA", str(tmp_path / "data"))
    from fastapi.testclient import TestClient

    from image_reviewer.app import create_app

    app = create_app()
    with TestClient(app, base_url="http://127.0.0.1") as client:
        a = add_asset(app.state.store, "a" * 64)
        body = {"asset_ids": [a], "ask": "1 枚選んで", "client_token": "tok-http"}
        for path in ("/api/review-requests", "/api/review-requests/missing/decline"):
            assert client.post(path, json=body,
                               headers={"host": "evil.example"}).status_code == 403, path
            assert client.post(path, json=body,
                               headers={"origin": "http://evil.example"}).status_code == 403, path
            assert client.post(path, content=b"{}",
                               headers={"content-type": "text/plain"}).status_code == 403, path
        # ヘッダが無ければ `agent`。**要求は通る**（201）
        created = client.post("/api/review-requests", json=body)
        assert created.status_code == 201, created.text
        assert created.json()["replayed"] is False
        # 再送は 200（行は増えない）
        again = client.post("/api/review-requests", json=body)
        assert again.status_code == 200, again.text
        assert again.json()["replayed"] is True
        assert len(rows(app.state.store, "SELECT * FROM review_request")) == 1
        # 一覧と取得
        listed = client.get("/api/review-requests")
        assert listed.status_code == 200 and listed.json()["counts"] == {"open": 1}
        # 断るのは人だけ（ヘッダ無し＝agent は 403）
        decline = f"/api/review-requests/{created.json()['request_id']}/decline"
        assert client.post(decline, json={"note": "理由"}).status_code == 403
        ok = client.post(decline, json={"note": "理由"},
                         headers={"X-Image-Reviewer-Actor": "human"})
        assert ok.status_code == 200 and ok.json()["state"] == "declined"


# ---- P6-1a の監査で直したもの（A1 / B1 / B2 / B3 / 設計の穴 5）----


def test_a_bogus_actor_header_is_422_not_500(tmp_path, monkeypatch):
    """監査 A1: `X-Image-Reviewer-Actor: robot` は **422**（表の `CHECK` に当たって 500 にしない）。

    口（FastAPI）を通して確かめる（`actor_of` の検査なので、サービス直呼びでは見えない）。
    """
    monkeypatch.setenv("IMAGE_REVIEWER_DATA", str(tmp_path / "data"))
    from fastapi.testclient import TestClient

    from image_reviewer.app import create_app

    app = create_app()
    with TestClient(app, base_url="http://127.0.0.1") as client:
        a = add_asset(app.state.store, "a" * 64)
        got = client.post("/api/review-requests", json={"asset_ids": [a]},
                          headers={"X-Image-Reviewer-Actor": "robot"})
        assert got.status_code == 422, got.text
        assert "human" in got.json()["detail"]


def test_a_request_on_an_existing_group_marks_that_group_for_export(env):
    """監査 B1: `group_id` を指名した要求も、そのまとまりのファイルを書き直す。

    以前は書き出しの対象に積まれず、`groups/<id>.json` の `requests[]` が空のままだった。
    """
    a = add_asset(env.store, "a" * 64)
    group = env.review.create_group(asset_ids=[a])
    env.exporter.flush_dirty()
    env.requests.create(group_id=group["id"], ask="見てほしい")

    env.exporter.flush()
    doc = json.loads(env.exporter.group_path(group["id"]).read_text(encoding="utf-8"))
    assert [r["id"] for r in doc["requests"]], "指名したまとまりのファイルに要求が載っていない（監査 B1）"


def test_a_group_without_its_own_decisions_is_closed_on_supersede(env):
    """監査 B2: 「判断が 1 つも無い」は**そのまとまりの判断**だけを見る。

    画像が別のまとまりで判断されていても、このまとまりをレビューしたことにはならない。
    以前はそれを判断と数えたので、差し替えても古いまとまりが既定の一覧に残った（点検 A3 の趣旨が崩れる）。
    """
    a = add_asset(env.store, "a" * 64)
    first = env.requests.create(asset_ids=[a], target_key="cut-b2")
    g1 = first["group_id"]
    other = env.review.create_group(asset_ids=[a])
    decide(env, other["id"],
           [{"asset_id": a, "verdict": "keep", "reason_code_id": "rc.keep.favorite"}])

    second = env.requests.create(asset_ids=[a], target_key="cut-b2")
    assert second["superseded_request_id"] == first["request_id"]
    row = rows(env.store, "SELECT superseded_by FROM review_group WHERE id = ?", (g1,))[0]
    assert row["superseded_by"] == second["request_id"], "自分の判断が無いのに閉じていない（監査 B2）"


def test_a_replayed_decide_does_not_report_closed_requests(env):
    """監査 B3: 再送では `closed_request_ids` を出さない（近似で 1 つ前を拾いうるため）。"""
    a = add_asset(env.store, "a" * 64)
    req = env.requests.create(asset_ids=[a], ask="1 枚")
    items = [{"asset_id": a, "verdict": "keep", "reason_code_id": "rc.keep.favorite"}]
    token = "tok-done-1"
    first = decide(env, req["group_id"], items, client_token=token)
    assert first["closed_request_ids"] == [req["request_id"]], "通常経路で閉じた要求を出していない"

    env.review.reopen(req["group_id"], actor="human")
    again = decide(env, req["group_id"], items, client_token=token)
    assert again["superseded"] is True
    assert again["closed_request_ids"] == [], "再送で閉じた要求を出した（監査 B3）"


def test_a_policy_that_contradicts_the_named_group_is_422(env):
    """設計の穴 5（監査で「今決める」）: `group_id` を指名して違う `policy` を送ったら 422。

    黙って捨てると、エージェントは自分の指定が効いたと思い込む。**送らなければ**通る
    （まとまりの設定が正）。
    """
    a, b = add_asset(env.store, "a" * 64), add_asset(env.store, "b" * 64, "b.png")
    group = env.review.create_group(asset_ids=[a, b], policy="pick_many")

    with pytest.raises(ReviewError) as got:
        env.requests.create(group_id=group["id"], policy="pick_one", ask="x")
    assert got.value.status == 422
    assert got.value.details["policy"] == "pick_many"

    ok = env.requests.create(group_id=group["id"], ask="x")
    assert ok["state"] == "open"
