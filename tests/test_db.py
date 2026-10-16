"""SQLite の土台（P5-0）のテスト。

設計: docs/p5-design.md §0.1（P5-0）、§0.7（実測で確かめた前提）
`tools/probe_p5.py` の実測を、**そのまま回帰テストにする**（部分索引・WAL・FK）。
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from image_reviewer import db


def test_migrate_creates_schema_and_is_idempotent(tmp_path: Path):
    con = db.open_db(tmp_path)
    try:
        names = {r["name"] for r in con.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'")}
        for t in ("settings", "root", "reason_code", "review_group", "asset",
                  "asset_location", "asset_meta", "location_history", "group_item", "decision"):
            assert t in names, f"{t} が無い"
        assert con.execute("PRAGMA user_version").fetchone()[0] == db.SCHEMA_VERSION
        # 何度呼んでも壊れない
        assert db.migrate(con) == db.SCHEMA_VERSION
        assert db.migrate(con) == db.SCHEMA_VERSION
    finally:
        con.close()


def test_pragmas_are_set_per_connection(tmp_path: Path):
    con = db.open_db(tmp_path)
    try:
        assert con.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"
        assert con.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        assert con.execute("PRAGMA busy_timeout").fetchone()[0] == 15000
    finally:
        con.close()


def test_integrity_is_clean(tmp_path: Path):
    con = db.open_db(tmp_path)
    try:
        got = db.integrity(con)
        assert got["quick_check"] == "ok"
        assert got["foreign_key_violations"] == 0
        assert got["schema_version"] == db.SCHEMA_VERSION
    finally:
        con.close()


def _asset(con, sha="a" * 64):
    con.execute(
        "INSERT INTO asset(id, sha256, kind, kind_source, first_seen_at, last_seen_at)"
        " VALUES (?,?,?,?,?,?)",
        (db.ulid(), sha, "generated", "auto:prompt", db.now(), db.now()),
    )
    return con.execute("SELECT id FROM asset WHERE sha256 = ?", (sha,)).fetchone()["id"]


def test_location_path_is_the_normalized_key_and_unique(tmp_path: Path):
    """同じ鍵は 1 行だけ（UNIQUE(path)）。表示用のパスは別列。点検 I1。"""
    con = db.open_db(tmp_path)
    try:
        a = _asset(con, "b" * 64)
        con.execute(
            "INSERT INTO asset_location(path, display_path, asset_id, size, mtime_ns, last_seen_at)"
            " VALUES (?,?,?,?,?,?)",
            (r"c:\img\a.png", r"C:\img\a.png", a, 10, 1, db.now()),
        )
        with pytest.raises(sqlite3.IntegrityError):
            con.execute(
                "INSERT INTO asset_location(path, display_path, asset_id, size, mtime_ns, last_seen_at)"
                " VALUES (?,?,?,?,?,?)",
                (r"c:\img\a.png", r"C:\IMG\A.PNG", a, 11, 2, db.now()),
            )
    finally:
        con.close()


def test_foreign_keys_are_enforced(tmp_path: Path):
    """存在しない asset を指す場所は入らない（FK が効いている）。CHECK も効く。"""
    con = db.open_db(tmp_path)
    try:
        with pytest.raises(sqlite3.IntegrityError):
            con.execute(
                "INSERT INTO asset_location(path, display_path, asset_id, size, mtime_ns, last_seen_at)"
                " VALUES (?,?,?,?,?,?)",
                (r"c:\img\x.png", r"C:\img\x.png", "01NOSUCHASSET", 1, 1, db.now()),
            )
        a = _asset(con, "9" * 64)
        with pytest.raises(sqlite3.IntegrityError):
            con.execute("UPDATE asset SET review_state = 'maybe' WHERE id = ?", (a,))
        # 消えた asset の場所は道連れになる（ON DELETE CASCADE）
        con.execute(
            "INSERT INTO asset_location(path, display_path, asset_id, size, mtime_ns, last_seen_at)"
            " VALUES (?,?,?,?,?,?)", (r"c:\img\y.png", r"C:\img\y.png", a, 1, 1, db.now()),
        )
        con.execute("DELETE FROM asset WHERE id = ?", (a,))
        assert con.execute("SELECT count(*) AS n FROM asset_location").fetchone()["n"] == 0
    finally:
        con.close()


def test_reason_code_applies_to_is_constrained(tmp_path: Path):
    con = db.open_db(tmp_path)
    try:
        con.execute("INSERT INTO reason_code(id,label,applies_to) VALUES ('rc.x','その他','both')")
        with pytest.raises(sqlite3.IntegrityError):
            con.execute("INSERT INTO reason_code(id,label,applies_to) VALUES ('rc.y','変な','any')")
    finally:
        con.close()


def test_decision_client_token_partial_index(tmp_path: Path):
    """送り直しに耐える: 同じ token は 1 行だけ。NULL は何個でも入る（実測 F1 の回帰）。"""
    con = db.open_db(tmp_path)
    try:
        a = _asset(con, "c" * 64)

        def add(token, seq):
            con.execute(
                "INSERT INTO decision(id, seq, subject_type, subject_id, verdict, actor,"
                " client_token, created_at) VALUES (?,?,?,?,?,?,?,?)",
                (db.ulid(), seq, "asset", a, "keep", "human", token, db.now()),
            )

        add("tok-1", 1)
        add(None, 2)
        add(None, 3)
        with pytest.raises(sqlite3.IntegrityError):
            add("tok-1", 4)
        assert con.execute("SELECT count(*) AS n FROM decision").fetchone()["n"] == 3
    finally:
        con.close()


def test_decision_seq_is_unique_and_orders_by_insertion(tmp_path: Path):
    """「最後の判断」は seq で決める（壁時計ではない。点検 C11）。"""
    con = db.open_db(tmp_path)
    try:
        a = _asset(con, "d" * 64)
        # 時計が**逆に進んでも**、挿入順で最後が決まる
        for seq, (verdict, created) in enumerate(
            [("keep", "2026-10-15T10:00:00Z"), ("reject", "2026-10-15T09:00:00Z")], start=1
        ):
            con.execute(
                "INSERT INTO decision(id, seq, subject_type, subject_id, verdict, actor, created_at)"
                " VALUES (?,?,?,?,?,?,?)",
                (db.ulid(), seq, "asset", a, verdict, "human", created),
            )
        last = con.execute(
            "SELECT verdict FROM decision WHERE subject_type='asset' AND subject_id=?"
            " ORDER BY seq DESC LIMIT 1", (a,)
        ).fetchone()["verdict"]
        assert last == "reject", "時計ではなく挿入順で最後を選んでいない"
        with pytest.raises(sqlite3.IntegrityError):
            con.execute(
                "INSERT INTO decision(id, seq, subject_type, subject_id, verdict, actor, created_at)"
                " VALUES (?,?,?,?,?,?,?)",
                (db.ulid(), 1, "asset", a, "keep", "human", db.now()),
            )
    finally:
        con.close()


def test_actor_is_constrained_to_human_or_agent(tmp_path: Path):
    con = db.open_db(tmp_path)
    try:
        a = _asset(con, "e" * 64)
        with pytest.raises(sqlite3.IntegrityError):
            con.execute(
                "INSERT INTO decision(id, seq, subject_type, subject_id, verdict, actor, created_at)"
                " VALUES (?,?,?,?,?,?,?)",
                (db.ulid(), 1, "asset", a, "keep", "robot", db.now()),
            )
    finally:
        con.close()


def test_group_dirty_columns_exist_for_export(tmp_path: Path):
    """書き出しの判定は changed_at / exported_at で行う（点検 B1）。"""
    con = db.open_db(tmp_path)
    try:
        con.execute(
            "INSERT INTO review_group(id, kind, policy, state, created_at, changed_at)"
            " VALUES ('g1','manual','pick_one','open',?,?)", (db.now(), db.now()),
        )
        dirty = con.execute(
            "SELECT count(*) AS n FROM review_group WHERE exported_at IS NULL OR changed_at > exported_at"
        ).fetchone()["n"]
        assert dirty == 1, "未書き出しのまとまりが拾えていない"
        con.execute("UPDATE review_group SET exported_at = changed_at WHERE id = 'g1'")
        dirty = con.execute(
            "SELECT count(*) AS n FROM review_group WHERE exported_at IS NULL OR changed_at > exported_at"
        ).fetchone()["n"]
        assert dirty == 0
    finally:
        con.close()


def test_migrate_upgrades_a_v1_database_in_place(tmp_path: Path):
    """v1 の DB をその場で最新にする（P5-1 の v2。P5-3 の v3 も同じ呼び出しで続けて進む）。

    `ALTER TABLE ADD COLUMN` は `IF NOT EXISTS` を持たないので、**列を見てから足す**。
    新規作成（DDL → v2 → v3）でも v1 からの更新でも同じ結果になることを固定する。

    版の数字そのものは `db.SCHEMA_VERSION` と比べる（P5-3 で v3 が増えたときに、
    このテストが「v2 のままであること」を主張し続けないように）。
    v3 の列と表は `tests/test_p5_3.py` が確かめる。
    """
    con = db.connect(tmp_path)
    try:
        con.executescript(db.DDL)
        con.execute("PRAGMA user_version = 1")
        con.execute(
            "INSERT INTO review_group(id, kind, policy, state, created_at, changed_at)"
            " VALUES ('g1','manual','pick_one','decided',?,?)", (db.now(), db.now()))
        assert "decision" not in {r["name"] for r in con.execute("PRAGMA table_info(review_group)")}

        assert db.migrate(con) == db.SCHEMA_VERSION
        names = {r["name"] for r in con.execute("PRAGMA table_info(review_group)")}
        assert {"reason_code_id", "decision", "note"} <= names
        row = con.execute("SELECT * FROM review_group WHERE id = 'g1'").fetchone()
        assert (row["state"], row["changed_at"]) and row["decision"] is None
        # 何度呼んでも安全（列を二度足さない）
        assert db.migrate(con) == db.SCHEMA_VERSION
        assert db.integrity(con)["foreign_key_violations"] == 0
    finally:
        con.close()


def test_migrate_v4_creates_the_request_and_annotation_tables(tmp_path: Path):
    """v4（P6-0）: `review_request` / `annotation` と `review_group.superseded_by` が入る。

    P6 の設計 §2.1 / 点検 A1・A3。**v1 の DDL から 1 回で最新（いまは v5）まで上がる**こと、
    **何度呼んでも同じ**こと、`integrity()` が綺麗なことを見る（P5-3 の C6 の教訓）。

    版の数字は `db.SCHEMA_VERSION` と比べる（P4-0 で v5 が増えても、このテストが
    「v4 のままであること」を主張し続けないように。v5 の表は下の v5 のテストが見る）。
    """
    con = db.connect(tmp_path)
    try:
        con.executescript(db.DDL)
        con.execute("PRAGMA user_version = 1")

        assert db.migrate(con) == db.SCHEMA_VERSION
        tables = {r["name"] for r in con.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'")}
        assert {"review_request", "annotation"} <= tables
        assert "superseded_by" in {r["name"] for r in con.execute(
            "PRAGMA table_info(review_group)")}

        # 何度呼んでも安全（表も列も二度作らない）
        assert db.migrate(con) == db.SCHEMA_VERSION
        assert db.integrity(con)["foreign_key_violations"] == 0
    finally:
        con.close()


def test_annotation_coordinates_are_all_or_nothing(tmp_path: Path):
    """点検 A1: 座標は「全部 NULL（画像 1 枚へのメモ）」か「全部あり」の 2 形だけ。

    片方だけ NULL の行は `CHECK` で弾く（表の制約なのでサービス層をすり抜けても守られる）。
    """
    con = db.open_db(tmp_path)
    try:
        con.execute("INSERT INTO asset(id, sha256, kind, review_state, first_seen_at,"
                    " last_seen_at, width, height)"
                    " VALUES ('a1', ?, 'generated', 'unreviewed', ?, ?, 1024, 1024)",
                    ("a" * 64, db.now(), db.now()))
        now = db.now()
        # 全部 NULL（画像 1 枚へのメモ）は通る
        con.execute("INSERT INTO annotation(id, asset_id, actor, created_at)"
                    " VALUES ('n1','a1','human',?)", (now,))
        # 全部あり（矩形）も通る
        con.execute("INSERT INTO annotation(id, asset_id, shape, x, y, w, h, actor, created_at)"
                    " VALUES ('n2','a1','rect',0.1,0.2,0.3,0.4,'agent',?)", (now,))
        # 片方だけ NULL は落ちる
        for bad in (
            "INSERT INTO annotation(id, asset_id, shape, actor, created_at)"
            " VALUES ('n3','a1','rect','human',?)",
            "INSERT INTO annotation(id, asset_id, x, y, w, h, actor, created_at)"
            " VALUES ('n4','a1',0.1,0.2,0.3,0.4,'human',?)",
        ):
            with pytest.raises(sqlite3.IntegrityError):
                con.execute(bad, (now,))
    finally:
        con.close()


def test_the_open_request_index_is_partial_and_ordered(tmp_path: Path):
    """点検 A3 / C4: 同じ `target_key` の `open` は 1 本だけ（部分 UNIQUE 索引）。

    **古い方を `superseded` に UPDATE してから INSERT する**（逆順だと索引で落ちる）。
    `target_key` が NULL の要求は何本でも積める。
    """
    con = db.open_db(tmp_path)
    try:
        con.execute("INSERT INTO review_group(id, kind, policy, state, created_at, changed_at)"
                    " VALUES ('g1','request','pick_one','open',?,?)", (db.now(), db.now()))
        now = db.now()
        con.execute("INSERT INTO review_request(id, group_id, target_key, state, actor, created_at)"
                    " VALUES ('r1','g1','cut-1','open','agent',?)", (now,))
        with pytest.raises(sqlite3.IntegrityError):
            con.execute("INSERT INTO review_request(id, group_id, target_key, state, actor,"
                        " created_at) VALUES ('r2','g1','cut-1','open','agent',?)", (now,))
        # 古い方を差し替えてからなら入る
        con.execute("UPDATE review_request SET state='superseded', superseded_by='r2'"
                    " WHERE id='r1'")
        con.execute("INSERT INTO review_request(id, group_id, target_key, state, actor, created_at)"
                    " VALUES ('r2','g1','cut-1','open','agent',?)", (now,))
        # 鍵が無ければ何本でも
        for rid in ("r3", "r4"):
            con.execute("INSERT INTO review_request(id, group_id, state, actor, created_at)"
                        " VALUES (?, 'g1','open','agent',?)", (rid, now))
        # 索引が引ける（`EXPLAIN QUERY PLAN` に出る）
        plan = " ".join(str(r["detail"]) for r in con.execute(
            "EXPLAIN QUERY PLAN SELECT id FROM review_request WHERE state = 'open'"
            " ORDER BY created_at DESC"))
        assert "ix_request_state" in plan, plan
    finally:
        con.close()


def test_group_item_has_no_cardinality_limit(tmp_path: Path):
    """枚数の上限は置かない（点検 B6/G8）。12 枚入る。"""
    con = db.open_db(tmp_path)
    try:
        con.execute(
            "INSERT INTO review_group(id, kind, policy, state, created_at, changed_at)"
            " VALUES ('g1','manual','pick_one','open',?,?)", (db.now(), db.now()),
        )
        for i in range(12):
            a = _asset(con, f"{i:064d}")
            con.execute("INSERT INTO group_item(group_id, asset_id, position) VALUES ('g1',?,?)", (a, i))
        n = con.execute("SELECT count(*) AS n FROM group_item WHERE group_id='g1'").fetchone()["n"]
        assert n == 12
    finally:
        con.close()


def test_ulid_is_26_chars_crockford_and_time_ordered():
    a = db.ulid(now_ms=1_700_000_000_000)
    b = db.ulid(now_ms=1_700_000_000_001)
    assert len(a) == 26
    assert a[0] in "01234567"          # 48bit の先頭は 0〜7
    assert set(a) <= set(db._B32)
    assert a < b, "時刻順に並ばない"
    # 時刻は 10 文字（48bit を 5bit ずつ）。最後の 1 文字に下位 3bit が入る
    assert a[:9] == b[:9]
    assert a[9] != b[9]
    # ランダム部は毎回違う
    assert a[10:] != b[10:]
    with pytest.raises(ValueError):
        db.ulid(now_ms=1 << 48)


def test_new_connection_sees_committed_rows_and_scan_does_not_lose_decisions(tmp_path: Path):
    """別プロセス（別接続）の走査が、判断を消さないこと。

    点検 B5 の核心。JSON ストアでは `save()` が全体を置き換えるので判断が消えた。
    行を書く SQLite では消えない。
    """
    writer = db.open_db(tmp_path)
    try:
        a = _asset(writer, "f" * 64)
        writer.execute(
            "INSERT INTO decision(id, seq, subject_type, subject_id, verdict, actor, created_at)"
            " VALUES (?,?,?,?,?,?,?)",
            (db.ulid(), 1, "asset", a, "keep", "human", db.now()),
        )
        # 別接続（＝別プロセスの走査に相当）が場所を書き、asset を更新する
        other = db.open_db(tmp_path)
        try:
            other.execute(
                "INSERT INTO asset_location(path, display_path, asset_id, size, mtime_ns, last_seen_at)"
                " VALUES (?,?,?,?,?,?)",
                (r"c:\img\a.png", r"C:\img\a.png", a, 100, 1, db.now()),
            )
            other.execute("UPDATE asset SET last_seen_at = ? WHERE id = ?", (db.now(), a))
        finally:
            other.close()
        # 判断は残っている
        n = writer.execute("SELECT count(*) AS n FROM decision WHERE subject_id = ?", (a,)).fetchone()["n"]
        assert n == 1, "別接続の書き込みで判断が消えた"
        assert writer.execute("SELECT count(*) AS n FROM asset_location").fetchone()["n"] == 1
    finally:
        writer.close()


def test_migrate_v5_creates_the_tag_and_job_tables(tmp_path: Path):
    """v5（P4-0）: `tag` / `asset_tag` / `tag_gloss` / `job` / `job_item` が入る。

    P4 の設計 §2.1。**v1 の DDL から 1 回で最新**・**v4 の DB からも最新**・**3 回呼んでも同じ**。

    版の数字そのものは `db.SCHEMA_VERSION` と比べる（版が増えても、このテストが
    「v5 のままであること」を主張し続けないように）。
    """
    # (1) v1 から 1 回で最新
    con = db.connect(tmp_path / "from-v1")
    try:
        con.executescript(db.DDL)
        con.execute("PRAGMA user_version = 1")
        assert db.migrate(con) == db.SCHEMA_VERSION
        tables = {r["name"] for r in con.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'")}
        assert {"tag", "asset_tag", "tag_gloss", "job", "job_item"} <= tables
        assert db.migrate(con) == db.SCHEMA_VERSION
        assert db.migrate(con) == db.SCHEMA_VERSION
        assert db.integrity(con)["foreign_key_violations"] == 0
    finally:
        con.close()

    # (2) v4 の DB から v5（P6 までの DB をそのまま上げる）
    con = db.connect(tmp_path / "from-v4")
    try:
        con.executescript(db.DDL)
        db._migrate_v2(con)
        db._migrate_v3(con)
        db._migrate_v4(con)
        con.execute("PRAGMA user_version = 4")
        assert db.migrate(con) == db.SCHEMA_VERSION
        assert "tag" in {r["name"] for r in con.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'")}
        assert db.integrity(con)["foreign_key_violations"] == 0
    finally:
        con.close()


def test_tag_name_is_unique_and_keeps_the_official_spelling(tmp_path: Path):
    """`tag.name` の一意性と、**括弧・コロンを落とさない**こと（点検 A-1 / G-5）。

    一意性は**大文字小文字を区別する**（正規化はサービス層で通す。設計 §2.1）。
    """
    con = db.open_db(tmp_path)
    try:
        con.execute("INSERT INTO tag(id, name, known) VALUES (1, 'long_hair', 1)")
        con.execute("INSERT INTO tag(id, name, known) VALUES"
                    " (2, 'rem_\\(re:zero\\)', 1)")     # ★括弧とコロンは語の一部
        con.execute("INSERT INTO tag(id, name, known) VALUES (3, 'looking at phone', 0)")
        with pytest.raises(sqlite3.IntegrityError):
            con.execute("INSERT INTO tag(id, name) VALUES (4, 'long_hair')")
        # 大文字小文字は別の語として入る（だから**小文字に落とすのはサービス層の仕事**）
        con.execute("INSERT INTO tag(id, name) VALUES (5, 'Long_Hair')")
        got = [r["name"] for r in con.execute("SELECT name FROM tag ORDER BY id")]
        assert got == ["long_hair", "rem_\\(re:zero\\)", "looking at phone", "Long_Hair"]
        # `known` の既定は 0（id=5 は `known` を省いて入れた行＝語彙の判定がまだ無い語）
        assert con.execute("SELECT known FROM tag WHERE id = 5").fetchone()[0] == 0
    finally:
        con.close()


def test_asset_tag_keeps_the_three_sources_apart(tmp_path: Path):
    """同じ語が PNG にもタガーにも手にもあるとき、**出所ごとに 1 行**になる（設計 §1.1）。

    主キーが `(asset_id, tag_id, source)` なので、同じ組を 2 回入れるのは落ちる
    （＝サービス層は `INSERT OR IGNORE` / `REPLACE` を使う）。`source` は `CHECK` で縛る。
    """
    con = db.open_db(tmp_path)
    try:
        con.execute("INSERT INTO asset(id, sha256, kind, review_state, first_seen_at,"
                    " last_seen_at) VALUES ('a1', ?, 'generated', 'unreviewed', ?, ?)",
                    ("a" * 64, db.now(), db.now()))
        con.execute("INSERT INTO tag(id, name, known) VALUES (1, '1girl', 1)")
        con.execute("INSERT INTO tag(id, name, known) VALUES (2, 'looking at phone', 0)")
        now = db.now()
        for source in ("png", "wd14", "manual"):
            con.execute("INSERT INTO asset_tag(asset_id, tag_id, score, source, tagged_at)"
                        " VALUES ('a1', 1, ?, ?, ?)",
                        (0.9931 if source == "wd14" else None, source, now))
        with pytest.raises(sqlite3.IntegrityError):
            con.execute("INSERT INTO asset_tag(asset_id, tag_id, source, tagged_at)"
                        " VALUES ('a1', 1, 'png', ?)", (now,))
        with pytest.raises(sqlite3.IntegrityError):
            con.execute("INSERT INTO asset_tag(asset_id, tag_id, source, tagged_at)"
                        " VALUES ('a1', 2, 'wat', ?)", (now,))
        rows = con.execute("SELECT source, score FROM asset_tag WHERE tag_id = 1"
                           " ORDER BY source").fetchall()
        assert [(r["source"], r["score"]) for r in rows] == [
            ("manual", None), ("png", None), ("wd14", 0.9931)]
        # 画像を消すとリンクも消える（`ON DELETE CASCADE`）
        con.execute("DELETE FROM asset WHERE id = 'a1'")
        assert con.execute("SELECT count(*) AS n FROM asset_tag").fetchone()["n"] == 0
    finally:
        con.close()


def test_tag_gloss_keeps_the_edited_flag(tmp_path: Path):
    """語釈の `edited` の既定は 0。**人が直したら 1**（訳し直しで上書きしない印。設計 §4.2）。"""
    con = db.open_db(tmp_path)
    try:
        con.execute("INSERT INTO tag(id, name, known) VALUES (1, 'long_hair', 1)")
        now = db.now()
        con.execute("INSERT INTO tag_gloss(tag_id, ja, source, created_at, updated_at)"
                    " VALUES (1, '長髪', 'textgenerate', ?, ?)", (now, now))
        row = con.execute("SELECT edited, engine FROM tag_gloss WHERE tag_id = 1").fetchone()
        assert row["edited"] == 0 and row["engine"] is None
        # `source` は 2 語だけ
        with pytest.raises(sqlite3.IntegrityError):
            con.execute("INSERT INTO tag_gloss(tag_id, ja, source, created_at, updated_at)"
                        " VALUES (2, 'x', 'dict', ?, ?)", (now, now))
    finally:
        con.close()


def test_job_state_is_constrained_and_items_cascade(tmp_path: Path):
    """`job.state` と `job_item.state` の語彙、`job_item` の従属（設計 §2.1・§4.1）。

    **P4-0 の監査の申し送り**: `job_item.state` の語彙が決まっていなかったので、
    P4-1 の実装にある語（`tagged` / `skipped` / `failed`）で `CHECK` を付けた（`db.py`）。
    """
    con = db.open_db(tmp_path)
    try:
        now = db.now()
        con.execute("INSERT INTO job(id, kind, state, created_at) VALUES ('j1','tag','queued',?)",
                    (now,))
        with pytest.raises(sqlite3.IntegrityError):
            con.execute("INSERT INTO job(id, kind, state, created_at)"
                        " VALUES ('j2','tag','bogus',?)", (now,))
        con.execute("INSERT INTO job_item(job_id, ref, state) VALUES ('j1','a1','tagged')")
        with pytest.raises(sqlite3.IntegrityError):
            con.execute("INSERT INTO job_item(job_id, ref, state) VALUES ('j1','a1','failed')")
        # **語彙の外の state は入らない**（P4-1 の実装は `tagged` / `skipped` / `failed` だけを使う）
        with pytest.raises(sqlite3.IntegrityError):
            con.execute("INSERT INTO job_item(job_id, ref, state) VALUES ('j1','a2','done')")
        con.execute("DELETE FROM job WHERE id = 'j1'")
        assert con.execute("SELECT count(*) AS n FROM job_item").fetchone()["n"] == 0
    finally:
        con.close()


def test_migrate_v5_tops_up_the_columns_an_older_v5_lacks(tmp_path: Path):
    """P4-0 / P4-1 の監査 A-1: **先に v5 になった DB** に、後から足した 3 列を補う。

    v5 は途中で `tag.known` / `asset_tag.actor` / `job.note` を足した（版は上げていない）。
    そのため列の無い v5 が残りうる。`migrate()` は `current >= SCHEMA_VERSION` で早期に戻るので、
    **戻る側でも列を見て補う**必要がある（監査: 列が無いとジョブが `no column named actor` で落ち、
    後始末も `no such column: note` で落ちて `job` が `running` のまま残った）。
    """
    con = db.connect(tmp_path)
    try:
        con.executescript(db.DDL)
        con.execute("PRAGMA user_version = 4")
        db.migrate(con)                                   # まず最新（v5 の表ができる）にする
        # 「後から列を足す前の v5」を作る
        con.execute("ALTER TABLE tag DROP COLUMN known")
        con.execute("ALTER TABLE asset_tag DROP COLUMN actor")
        con.execute("ALTER TABLE job DROP COLUMN note")
        assert "known" not in {r["name"] for r in con.execute("PRAGMA table_info(tag)")}

        assert db.migrate(con) == db.SCHEMA_VERSION       # 版は上がらない（早期 return の道）
        assert {"known"} <= {r["name"] for r in con.execute("PRAGMA table_info(tag)")}
        assert {"actor"} <= {r["name"] for r in con.execute("PRAGMA table_info(asset_tag)")}
        assert {"note"} <= {r["name"] for r in con.execute("PRAGMA table_info(job)")}
        # 何度呼んでも安全（列を二度足さない）
        assert db.migrate(con) == db.SCHEMA_VERSION
        assert db.integrity(con)["foreign_key_violations"] == 0
    finally:
        con.close()
