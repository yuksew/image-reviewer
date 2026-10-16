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

    版の数字そのものは `db.SCHEMA_VERSION` と比べる（P7-0 で v6 が増えても、このテストが
    「v5 のままであること」を主張し続けないように。v6 の表は下の v6 のテストが見る）。
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


# ---- v6（P7-0。条件の記録と監視の既読位置）----


V6_TABLES = ("recipe_record", "recipe_export_attempt", "recipe_export",
             "recipe_export_result", "preset", "watcher_state")


def test_migrate_v6_creates_the_recipe_tables(tmp_path: Path):
    """v6（P7-0）: 条件の記録の 5 表と `watcher_state` が入る（P7 の設計 §2.1）。

    設計 §8.1 の 24。**(1) v1 の DDL から 1 回で v6**・**(2) v5 から v6**・**(3) 3 回呼んでも同じ**・
    `integrity()` が綺麗、の 4 つを見る（P6-0・P4-0 の監査と同じ観点）。
    **新しい表だけ**なので `ALTER TABLE` は使わず、v6 には `_top_up_v6` が無い（早期 return 側で
    補うものが無いこと）。v5 の 3 列の手当ては v6 でも通る（上のテスト）。
    """
    # (1) v1 から 1 回で v6
    con = db.connect(tmp_path / "from-v1")
    try:
        con.executescript(db.DDL)
        con.execute("PRAGMA user_version = 1")
        assert db.migrate(con) == db.SCHEMA_VERSION
        tables = {r["name"] for r in con.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'")}
        assert set(V6_TABLES) <= tables, f"足りない: {set(V6_TABLES) - tables}"
        assert db.integrity(con)["schema_version"] == db.SCHEMA_VERSION
        assert db.integrity(con)["foreign_key_violations"] == 0
        # (3) 何度呼んでも同じ
        assert db.migrate(con) == db.SCHEMA_VERSION
        assert db.migrate(con) == db.SCHEMA_VERSION
        assert {r["name"] for r in con.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'")} == tables
    finally:
        con.close()

    # (2) v5 の DB から v6（実データ .data と同じ道）
    con = db.connect(tmp_path / "from-v5")
    try:
        con.executescript(db.DDL)
        db._migrate_v2(con)
        db._migrate_v3(con)
        db._migrate_v4(con)
        db._migrate_v5(con)
        con.execute("PRAGMA user_version = 5")
        assert "recipe_record" not in {r["name"] for r in con.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'")}
        assert db.migrate(con) == db.SCHEMA_VERSION
        assert set(V6_TABLES) <= {r["name"] for r in con.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'")}
        assert db.integrity(con)["foreign_key_violations"] == 0
    finally:
        con.close()


def test_recipe_record_is_one_per_asset_and_the_token_is_reusable(tmp_path: Path):
    """設計 §8.1 の 43（`ux_recipe_source`）と、`client_token` の部分索引（§0.10）。

    **画像 1 枚に 1 記録**（点検 C-1 / G-5。`mode` は行を分ける軸ではない）。索引を外すと
    2 行目が入ってしまい、`GET /api/assets/{id}/recipe` がどちらを返すか決まらなくなる。
    `client_token` は NULL なら何行でも、同じ値なら 1 行（部分索引。P6 と同じ形）。
    """
    con = db.open_db(tmp_path)
    try:
        a = _asset(con, "1" * 64)
        b = _asset(con, "2" * 64)
        c = _asset(con, "3" * 64)
        d = _asset(con, "4" * 64)
        e = _asset(con, "5" * 64)

        def record(asset_id, mode="pin_text", token=None):
            con.execute(
                "INSERT INTO recipe_record(id, source_asset_id, mode, recipe_hash, record_json,"
                " env_snapshot, status, actor, client_token, created_at)"
                " VALUES (?,?,?,?,?,?,?,?,?,?)",
                (db.ulid(), asset_id, mode, "sha256:" + "a" * 64, "{}", "{}",
                 "exact", "human", token, db.now()))

        record(a)
        with pytest.raises(sqlite3.IntegrityError):
            record(a, mode="rerun_graph")              # 同じ画像に 2 つ目（mode を変えても 1 記録）
        record(b, token="tok-1")
        with pytest.raises(sqlite3.IntegrityError):
            record(e, token="tok-1")                   # **別の画像**で同じ token は 1 行
        # NULL の token は何行でも入る（部分索引）
        record(c, token=None)
        record(d, token=None)
        assert con.execute("SELECT count(*) AS n FROM recipe_record").fetchone()["n"] == 4
    finally:
        con.close()


def test_recipe_export_needs_exactly_one_of_marker_or_skip_reason(tmp_path: Path):
    """設計 §8.1 の 35（点検 A-2a）: `marker` と `marker_skip_reason` は**片方だけ**。

    前の版は `marker` が `NOT NULL` で「印を付けられなかった」を表せなかった（§4.7.1 の前提 3 つ）。
    両方入る／どちらも無い、のどちらも `CHECK` で落ちる。
    """
    con = db.open_db(tmp_path)
    try:
        a = _asset(con, "5" * 64)
        con.execute(
            "INSERT INTO recipe_record(id, source_asset_id, mode, recipe_hash, record_json,"
            " env_snapshot, status, actor, created_at) VALUES ('rec1', ?, 'pin_text', 'sha256:x',"
            " '{}', '{}', 'exact', 'human', ?)", (a, db.now()))
        con.execute(
            "INSERT INTO recipe_export_attempt(attempt_id, recipe_id, mode, export_dir, created_at)"
            " VALUES ('attempt01', 'rec1', 'pin_text', 'recipes/rec1/attempt01', ?)", (db.now(),))

        def export(eid, marker, reason, seed="1"):
            con.execute(
                "INSERT INTO recipe_export(id, attempt_id, seed, recipe_hash, graph_path, marker,"
                " marker_skip_reason, created_at) VALUES (?, 'attempt01', ?, 'sha256:x', 'p', ?, ?, ?)",
                (eid, seed, marker, reason, db.now()))

        export("e1", "repro-attempt01/seed-1", None)                 # 印だけ
        export("e2", None, "前提2", seed="2")                        # 理由だけ
        with pytest.raises(sqlite3.IntegrityError):
            export("e3", "repro-attempt01/seed-3", "前提2", seed="3")  # 両方
        with pytest.raises(sqlite3.IntegrityError):
            export("e4", None, None, seed="4")                         # どちらも無い
        with pytest.raises(sqlite3.IntegrityError):
            export("e5", None, "前提4", seed="5")                      # 語彙の外
        assert con.execute("SELECT count(*) AS n FROM recipe_export").fetchone()["n"] == 2
    finally:
        con.close()


def test_recipe_export_without_a_seed_is_still_unique(tmp_path: Path):
    """設計 §8.1 の 34（点検 A-2c）: **seed が NULL でも 1 束 1 行**。

    前の版は `UNIQUE(attempt_id, seed)` だったので、`seed IS NULL` の 2 行目が入った
    （SQLite の UNIQUE は NULL を互いに別物として扱う。実測で確認）。いまは
    **`COALESCE(seed,'')` の式の索引**なので、seed 無しの束（G-4。印は `…/noseed`）でも効く。
    索引を外すとこのテストは 2 行になって落ちる。
    """
    con = db.open_db(tmp_path)
    try:
        a = _asset(con, "6" * 64)
        con.execute(
            "INSERT INTO recipe_record(id, source_asset_id, mode, recipe_hash, record_json,"
            " env_snapshot, status, actor, created_at) VALUES ('rec1', ?, 'pin_text', 'sha256:x',"
            " '{}', '{}', 'exact', 'human', ?)", (a, db.now()))
        con.execute(
            "INSERT INTO recipe_export_attempt(attempt_id, recipe_id, mode, export_dir, created_at)"
            " VALUES ('noseed01', 'rec1', 'pin_text', 'recipes/rec1/noseed01', ?)", (db.now(),))

        def export(eid):
            con.execute(
                "INSERT INTO recipe_export(id, attempt_id, seed, recipe_hash, graph_path, marker,"
                " created_at) VALUES (?, 'noseed01', NULL, 'sha256:x', 'p', 'repro-noseed01/noseed', ?)",
                (eid, db.now()))

        export("e1")
        with pytest.raises(sqlite3.IntegrityError):
            export("e2")
        # seed が違えば別の行（seed 違いは 1 束に何本でも）
        con.execute("INSERT INTO recipe_export(id, attempt_id, seed, recipe_hash, graph_path,"
                    " marker, created_at) VALUES ('e3','noseed01','1','sha256:x','p',"
                    " 'repro-noseed01/seed-1', ?)", (db.now(),))
        assert con.execute("SELECT count(*) AS n FROM recipe_export").fetchone()["n"] == 2
        # 索引そのものが式の索引であること（`seed IS NULL` を拾える形）
        sql = con.execute("SELECT sql FROM sqlite_master WHERE name = 'ux_export_attempt_seed'"
                          ).fetchone()["sql"]
        assert "COALESCE" in sql.upper(), sql
    finally:
        con.close()


def test_export_attempt_token_is_unique_and_the_indexes_are_used(tmp_path: Path):
    """設計 §8.1 の 36（束の再送）と 29（`EXPLAIN QUERY PLAN`）。

    `ux_attempt_token` の部分索引を外すと、同じ `client_token` の再送で**束が 2 つ**できる
    （＝ファイルも 2 倍できる）。索引が**実際に引かれる**ことは `EXPLAIN QUERY PLAN` で見る
    （P5 の D1 の教訓: 索引を作っただけで使われていない、を防ぐ）。

    `ux_export_attempt_seed` を引くには **`COALESCE(seed,'')` の形で問い合わせる**必要がある
    （`seed = ?` だと `ix_export_attempt` に落ちる。実測）。P7-2 はこの形で引く。
    """
    con = db.open_db(tmp_path)
    try:
        a = _asset(con, "7" * 64)
        con.execute(
            "INSERT INTO recipe_record(id, source_asset_id, mode, recipe_hash, record_json,"
            " env_snapshot, status, actor, created_at) VALUES ('rec1', ?, 'pin_text', 'sha256:x',"
            " '{}', '{}', 'exact', 'human', ?)", (a, db.now()))

        def attempt(aid, token=None):
            con.execute(
                "INSERT INTO recipe_export_attempt(attempt_id, recipe_id, mode, client_token,"
                " export_dir, created_at) VALUES (?, 'rec1', 'pin_text', ?, ?, ?)",
                (aid, token, f"recipes/rec1/{aid}", db.now()))

        attempt("attempt01", "tok-1")
        with pytest.raises(sqlite3.IntegrityError):
            attempt("attempt02", "tok-1")
        attempt("attempt03", None)
        attempt("attempt04", None)                       # NULL は何本でも
        assert con.execute("SELECT count(*) AS n FROM recipe_export_attempt"
                           ).fetchone()["n"] == 3

        plans = {
            "ux_recipe_source": ("SELECT id FROM recipe_record WHERE source_asset_id = ?", 1),
            "ux_recipe_token": ("SELECT id FROM recipe_record WHERE client_token = ?", 1),
            "ix_recipe_created": ("SELECT id FROM recipe_record ORDER BY created_at DESC,"
                                  " id DESC LIMIT 5", 0),
            "ix_attempt_recipe": ("SELECT attempt_id FROM recipe_export_attempt"
                                  " WHERE recipe_id = ? ORDER BY created_at DESC", 1),
            "ux_attempt_token": ("SELECT attempt_id FROM recipe_export_attempt"
                                 " WHERE client_token = ?", 1),
            "ux_export_attempt_seed": ("SELECT id FROM recipe_export WHERE attempt_id = ?"
                                       " AND COALESCE(seed, '') = ?", 2),
            "ix_result_export": ("SELECT id FROM recipe_export_result WHERE export_id = ?"
                                 " ORDER BY created_at", 1),
            "ux_result_asset": ("SELECT id FROM recipe_export_result WHERE export_id = ?"
                                " AND result_asset_id = ?", 2),
            "ix_preset_created": ("SELECT id FROM preset ORDER BY created_at DESC, id DESC"
                                  " LIMIT 5", 0),
        }
        for index, (query, n) in plans.items():
            plan = " ".join(str(r["detail"]) for r in con.execute(
                "EXPLAIN QUERY PLAN " + query, ("x",) * n))
            assert index in plan, f"{index} が使われていない: {plan}"
    finally:
        con.close()


def test_deleting_an_asset_keeps_presets_and_results_but_not_records(tmp_path: Path):
    """設計 §8.1 の 42（点検 C-3 / G-3）: 画像を消したときの 3 つの振る舞い。

    - `preset.source_asset_id` と `recipe_export_result.result_asset_id` は **`SET NULL`**
      （画像が消えても「どんな条件で出したか」「結果はどうだったか」は残す）
    - `recipe_record.source_asset_id` は **RESTRICT**（既定）。記録のある画像は消せない
      （記録ごと消すか断るかは **P8 の設計**へ申し送り。§2.1 の末尾）。前の版はこれを決めておらず、
      実測で `FOREIGN KEY constraint failed` になった
    """
    con = db.open_db(tmp_path)
    try:
        a = _asset(con, "8" * 64)          # 記録のある画像
        b = _asset(con, "9" * 64)          # プリセットと結果が指す画像
        con.execute(
            "INSERT INTO recipe_record(id, source_asset_id, mode, recipe_hash, record_json,"
            " env_snapshot, status, actor, created_at) VALUES ('rec1', ?, 'pin_text', 'sha256:x',"
            " '{}', '{}', 'exact', 'human', ?)", (a, db.now()))
        con.execute(
            "INSERT INTO recipe_export_attempt(attempt_id, recipe_id, mode, export_dir, created_at)"
            " VALUES ('attempt01', 'rec1', 'pin_text', 'recipes/rec1/attempt01', ?)", (db.now(),))
        con.execute(
            "INSERT INTO recipe_export(id, attempt_id, seed, recipe_hash, graph_path, marker,"
            " created_at) VALUES ('e1','attempt01','1','sha256:x','p','repro-attempt01/seed-1', ?)",
            (db.now(),))
        con.execute(
            "INSERT INTO recipe_export_result(id, export_id, result_asset_id, matched_by, created_at)"
            " VALUES ('res1','e1', ?, 'marker', ?)", (b, db.now()))
        con.execute(
            "INSERT INTO preset(id, name, source_asset_id, record_json, actor, created_at)"
            " VALUES ('p1','いつもの', ?, '{}', 'human', ?)", (b, db.now()))

        # 記録のある画像は消せない（RESTRICT）
        with pytest.raises(sqlite3.IntegrityError):
            con.execute("DELETE FROM asset WHERE id = ?", (a,))
        # 記録の無い画像は消せて、プリセットと結果は残る（SET NULL）
        con.execute("DELETE FROM asset WHERE id = ?", (b,))
        assert con.execute("SELECT source_asset_id FROM preset WHERE id = 'p1'"
                           ).fetchone()["source_asset_id"] is None
        assert con.execute("SELECT result_asset_id FROM recipe_export_result WHERE id = 'res1'"
                           ).fetchone()["result_asset_id"] is None
        assert con.execute("SELECT count(*) AS n FROM preset").fetchone()["n"] == 1
    finally:
        con.close()


def test_recipe_vocabularies_are_constrained(tmp_path: Path):
    """語彙は表でも守る（設計 §2.1。家風「`CHECK` を使う」）。

    サービス層をすり抜けても、`mode` / `status` / `actor` / `matched_by` / `verdict` /
    `verdict_actor` / `final_prompt_source` / `marker_skip_reason` の外の値は入らない。

    **悪い行は 1 つずつ別の画像に当てる。** 同じ画像に続けて入れると `ux_recipe_source` で
    先に落ちてしまい、`status` / `actor` の `CHECK` を外しても通ってしまう（実測。
    「壊しても落ちないテスト」の型なので、ここは画像を分ける）。
    """
    con = db.open_db(tmp_path)
    try:
        shas = iter(f"{i:064d}" for i in range(1, 12))
        a = _asset(con, next(shas))
        con.execute(
            "INSERT INTO recipe_record(id, source_asset_id, mode, recipe_hash, record_json,"
            " env_snapshot, status, actor, created_at) VALUES ('rec1', ?, 'pin_text', 'sha256:x',"
            " '{}', '{}', 'exact', 'human', ?)", (a, db.now()))

        def bad(sql, args=()):
            with pytest.raises(sqlite3.IntegrityError):
                con.execute(sql, args)

        base = ("INSERT INTO recipe_record(id, source_asset_id, mode, recipe_hash, record_json,"
                " env_snapshot, status, actor, created_at) VALUES (?, ?, ?, 'sha256:x', '{}',"
                " '{}', ?, ?, ?)")
        bad(base, ("r2", _asset(con, next(shas)), "l4", "exact", "human", db.now()))       # mode
        bad(base, ("r3", _asset(con, next(shas)), "pin_text", "maybe", "human", db.now()))  # status
        bad(base, ("r4", _asset(con, next(shas)), "pin_text", "exact", "robot", db.now()))  # actor
        con.execute("UPDATE recipe_record SET final_prompt_source = 'png_literal' WHERE id='rec1'")
        bad("UPDATE recipe_record SET final_prompt_source = 'guessed' WHERE id = 'rec1'")
        bad("INSERT INTO recipe_export_attempt(attempt_id, recipe_id, mode, marker_skip_reason,"
            " export_dir, created_at) VALUES ('a2','rec1','pin_text','前提4','p',?)", (db.now(),))
        con.execute("INSERT INTO recipe_export_attempt(attempt_id, recipe_id, mode, export_dir,"
                    " created_at) VALUES ('attempt01','rec1','pin_text','p',?)", (db.now(),))
        con.execute("INSERT INTO recipe_export(id, attempt_id, seed, recipe_hash, graph_path,"
                    " marker, created_at) VALUES ('e1','attempt01','1','sha256:x','p','m', ?)",
                    (db.now(),))
        res = ("INSERT INTO recipe_export_result(id, export_id, matched_by, verdict,"
               " verdict_actor, created_at) VALUES (?, 'e1', ?, ?, ?, ?)")
        bad(res, ("x1", "guess", None, None, db.now()))                 # matched_by
        bad(res, ("x2", "marker", "good", None, db.now()))              # verdict
        bad(res, ("x3", "marker", "same", "robot", db.now()))           # verdict_actor
        con.execute(res, ("x4", "marker", "close", "human", db.now()))
        # `same_hash` / `seed_changed` の既定は 0
        row = con.execute("SELECT same_hash, seed_changed, verdict_at FROM recipe_export_result"
                          " WHERE id = 'x4'").fetchone()
        assert (row["same_hash"], row["seed_changed"], row["verdict_at"]) == (0, 0, None)
        # `watcher_state.enabled` の既定は 0（勝手に ComfyUI を叩かない。設計 §0.9）
        con.execute("INSERT INTO watcher_state(name) VALUES ('comfyui')")
        assert con.execute("SELECT enabled, baseline_create_time FROM watcher_state"
                           ).fetchone()["enabled"] == 0
    finally:
        con.close()


# ---- P7-0 の監査 F-1: 監査者が「壊しても落ちない」と見つけた 5 通りを守る ----


def _recipe_with_attempt(con, *, sha: str = "7" * 64, rid: str = "rec-x",
                         attempt: str = "attempt-x") -> str:
    """記録 1 つと束 1 つを作る（下ごしらえ）。画像の id を返す。"""
    a = _asset(con, sha)
    con.execute(
        "INSERT INTO recipe_record(id, source_asset_id, mode, recipe_hash, record_json,"
        " env_snapshot, status, actor, created_at) VALUES (?, ?, 'pin_text', 'sha256:x', '{}', '{}',"
        " 'exact', 'human', ?)", (rid, a, db.now()))
    con.execute(
        "INSERT INTO recipe_export_attempt(attempt_id, recipe_id, mode, export_dir, created_at)"
        " VALUES (?, ?, 'pin_text', ?, ?)", (attempt, rid, f"recipes/{rid}/{attempt}", db.now()))
    return a


def test_deleting_an_attempt_cascades_to_files_and_results(tmp_path: Path):
    """監査 F-1 の **X1**（点検 G-1）: 束を消すと**ファイルの行も結果の行も**消える。

    `recipe_export.attempt_id` の `ON DELETE CASCADE` を外すと、束を消してもファイルの行が残って落ちる。
    `recipe_export_result.export_id` の `CASCADE`（G-1）を外すと、結果が残って落ちる。
    """
    con = db.open_db(tmp_path)
    try:
        _recipe_with_attempt(con)
        con.execute(
            "INSERT INTO recipe_export(id, attempt_id, seed, recipe_hash, graph_path, marker,"
            " created_at) VALUES ('exp1','attempt-x','1','sha256:x','p','repro-attempt-x/seed-1',?)",
            (db.now(),))
        con.execute(
            "INSERT INTO recipe_export_result(id, export_id, matched_by, created_at)"
            " VALUES ('res1','exp1','marker',?)", (db.now(),))

        con.execute("DELETE FROM recipe_export_attempt WHERE attempt_id = 'attempt-x'")
        assert con.execute("SELECT count(*) AS n FROM recipe_export").fetchone()["n"] == 0, \
            "束を消してもファイルの行が残った（X1: ON DELETE CASCADE が外れている）"
        assert con.execute("SELECT count(*) AS n FROM recipe_export_result").fetchone()["n"] == 0, \
            "束を消しても結果の行が残った（G-1: export_id の CASCADE が外れている）"
    finally:
        con.close()


def test_an_attempt_needs_a_real_recipe_and_a_record_with_attempts_cannot_go(tmp_path: Path):
    """監査 F-1 の **X2**: `recipe_export_attempt.recipe_id` の `REFERENCES` が効く。

    - 知らない `recipe_id` の束は入らない
    - **束のある記録は消せない**（`RESTRICT`。設計 §2.2「条件の記録は R12 の目的物なので黙って消さない」）
    `REFERENCES` を外すとどちらも通って落ちる。
    """
    con = db.open_db(tmp_path)
    try:
        _recipe_with_attempt(con)
        with pytest.raises(sqlite3.IntegrityError):
            con.execute(
                "INSERT INTO recipe_export_attempt(attempt_id, recipe_id, mode, export_dir,"
                " created_at) VALUES ('nope01','no-such-record','pin_text','x',?)", (db.now(),))
        with pytest.raises(sqlite3.IntegrityError):
            con.execute("DELETE FROM recipe_record WHERE id = 'rec-x'")
    finally:
        con.close()


def test_a_result_needs_a_real_export(tmp_path: Path):
    """監査 F-1 の **X4**: `recipe_export_result.export_id` の `REFERENCES` が効く。

    知らない `export_id` の結果は入らない。`REFERENCES` を外すと通って落ちる。
    """
    con = db.open_db(tmp_path)
    try:
        _recipe_with_attempt(con)
        with pytest.raises(sqlite3.IntegrityError):
            con.execute(
                "INSERT INTO recipe_export_result(id, export_id, matched_by, created_at)"
                " VALUES ('res9','no-such-export','marker',?)", (db.now(),))
    finally:
        con.close()


def test_the_attempt_recipe_index_is_used_and_the_duplicate_is_gone(tmp_path: Path):
    """監査 F-1 の **X3** と C-2 / G-4: `ix_attempt_recipe` が引かれ、**重複索引を作らない**。

    `ix_attempt_recipe` を外すと `EXPLAIN QUERY PLAN` に出ずに落ちる。
    `ix_export_attempt`（主キーの前置と重なる）が復活しても落ちる。
    """
    con = db.open_db(tmp_path)
    try:
        plan = " ".join(str(r["detail"]) for r in con.execute(
            "EXPLAIN QUERY PLAN SELECT * FROM recipe_export_attempt WHERE recipe_id = ?"
            " ORDER BY created_at DESC", ("rec-x",)))
        assert "ix_attempt_recipe" in plan, f"索引が引かれない（X3）: {plan}"
        names = {r["name"] for r in con.execute(
            "SELECT name FROM sqlite_master WHERE type = 'index'")}
        assert "ix_export_attempt" not in names, "重複索引が復活した（C-2 / G-4）"
    finally:
        con.close()


def test_the_migration_run_twice_gives_the_same_sql_not_only_the_same_names(tmp_path: Path):
    """監査 F: 「3 回呼んでも同じ」は**表の名前だけ**では足りない（索引だけ消える壊し方を見逃す）。

    `sqlite_master` の `sql` まで比べる（表・索引・トリガの定義）。
    """
    con = db.connect(tmp_path / "same-sql")
    try:
        con.executescript(db.DDL)
        con.execute("PRAGMA user_version = 1")
        db.migrate(con)
        first = {r["name"]: r["sql"] for r in con.execute(
            "SELECT name, sql FROM sqlite_master WHERE sql IS NOT NULL")}
        db.migrate(con)
        db.migrate(con)
        again = {r["name"]: r["sql"] for r in con.execute(
            "SELECT name, sql FROM sqlite_master WHERE sql IS NOT NULL")}
        assert again == first, "2 回目以降で定義が変わった（索引が消える壊し方を見逃す）"
    finally:
        con.close()


def test_the_new_vocabularies_and_the_verdict_pair_are_constrained(tmp_path: Path):
    """点検 G-2: `graph_kind` / `captured_source` の語彙と、**合否と人は対**で入ること。

    サービス層だけで守ると、口を足したときに素通りする（家風「語彙は DB でも守る」）。
    """
    con = db.open_db(tmp_path)
    try:
        a = _asset(con, "8" * 64)

        def record(rid, **kw):
            con.execute(
                "INSERT INTO recipe_record(id, source_asset_id, mode, recipe_hash, record_json,"
                " env_snapshot, status, actor, created_at, graph_kind, captured_source)"
                " VALUES (?, ?, 'pin_text', 'sha256:x', '{}', '{}', 'exact', 'human', ?, ?, ?)",
                (rid, a, db.now(), kw.get("graph_kind"), kw.get("captured_source")))

        record("ok1", graph_kind="api", captured_source="comfyui_history")   # 語彙の中
        with pytest.raises(sqlite3.IntegrityError):
            record("ng1", graph_kind="ui")                                   # 語彙の外
        with pytest.raises(sqlite3.IntegrityError):
            record("ng2", captured_source="nope")                            # 語彙の外

        _recipe_with_attempt(con, sha="9" * 64, rid="rec-v", attempt="attempt-v")
        con.execute(
            "INSERT INTO recipe_export(id, attempt_id, seed, recipe_hash, graph_path, marker,"
            " created_at) VALUES ('expv','attempt-v','1','sha256:x','p','m',?)", (db.now(),))

        def result(rid, verdict, actor):
            con.execute(
                "INSERT INTO recipe_export_result(id, export_id, matched_by, created_at, verdict,"
                " verdict_actor) VALUES (?, 'expv', 'marker', ?, ?, ?)",
                (rid, db.now(), verdict, actor))

        result("r-ok", "same", "human")                  # 対で入る
        result("r-none", None, None)                     # どちらも無い
        with pytest.raises(sqlite3.IntegrityError):
            result("r-half1", "same", None)              # 合否だけ
        with pytest.raises(sqlite3.IntegrityError):
            result("r-half2", None, "human")             # 人だけ
    finally:
        con.close()
