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


def test_the_temporary_btree_goes_to_memory(tmp_path: Path):
    """**（P9。設計 §12.2 の「DB」の行）一時 b-tree をメモリに置く／`cache_size` は既定のまま。**

    `ORDER BY` が要る読み（`store.assets()`）は**一時ファイル**を作りに行く。1 万枚では
    バッファに収まらないので、置き場によっては
    `sqlite3.OperationalError: unable to open database file` になる。

    壊すと落ちる: `PRAGMA temp_store = MEMORY` を `db.connect()` から外すと 2 → 0 になり、
    **P9 の実測で 1 万枚の `GET /api/assets` が 500 になった**（`%TEMP%` に書けない環境）。

    **`cache_size` は既定のまま**（`assert` で固定する）。§12.2 は `-65536`（64 MB）と
    書いているが、**入れる実利が無い**（P9 の実測: 1 万枚の SQL 3 本が 43.6 → 42.5 ms。
    一覧の 200 ms は `store.assets()` の dict 組み立てが主因）ので入れていない。

    **（P9 の監査 C-1）以前ここには「既定の 2 MB なら走ったまま壊れた DB を見つける」と
    いう理由を書いていたが、それは誤りだった。** 既定でも、キャッシュに収まる大きさの DB
    （0.65 MB）では**書き込み用の接続が見落とす**。いまは `backup._refuse_if_broken()` が
    **新しい読み取り専用の接続**で見るので、`cache_size` の値は安全の話ではない
    （`tests/test_backup.py::test_a_page_in_the_writers_cache_is_still_noticed`）。

    **（P9 の監査 D-10）振る舞いの試験は足していない。** 「書けない置き場で一時 b-tree が
    落ちる」形は `pytest` の中で決定的に作れない——`TMP` / `TEMP` を**ファイル**に向けても、
    SQLite は `GetTempPath` の結果が使えなければ**カレント（`.`）に落ちる**ので通ってしまう
    （実測: `.tmp-audit-redo/p9fix/probe_temp_store.py`）。P9 で 500 になったのは
    **エージェントの sandbox が書けない所を全部塞いでいた**ためで、その再現には sandbox が要る。
    ここは pragma の値を固定する（`M1` / `M2` の壊し試験が落ちる）。
    """
    con = db.open_db(tmp_path)
    try:
        assert con.execute("PRAGMA temp_store").fetchone()[0] == 2          # 2 = MEMORY
        assert con.execute("PRAGMA mmap_size").fetchone()[0] == 268435456  # 256 MB
        # **わざと既定のまま**（P9 の実測。上の docstring）
        assert con.execute("PRAGMA cache_size").fetchone()[0] == -2000
    finally:
        con.close()
    # 読み取り専用の接続でも同じ（壊れた DB から読む道。§0.12-5）
    con = db.connect(tmp_path, read_only=True)
    try:
        assert con.execute("PRAGMA temp_store").fetchone()[0] == 2
        assert con.execute("PRAGMA cache_size").fetchone()[0] == -2000
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


# ---- v6（P8-0: 重複・削除・バックアップの表と列。**機能は足さない**）----


V6_TABLES = ("delete_request", "deletion_log", "duplicate_exclusion",
             "phash_band", "pending_delete_preview")


def _dump(con) -> list:
    """`sqlite_master` の中身（**索引と表の `sql` まで**比べる。P7-0 の監査 F-1 の教訓）。"""
    return [(r["type"], r["name"], (r["sql"] or "").replace("\n", " "))
            for r in con.execute("SELECT type, name, sql FROM sqlite_master"
                                 " ORDER BY type, name")]


def test_v6_adds_the_delete_tables_and_columns(tmp_path: Path):
    """P8-0: v6 で 5 表と 2 列が入る（設計 §2.1）。**v5 から 1 回で**。"""
    con = db.open_db(tmp_path)
    try:
        assert con.execute("PRAGMA user_version").fetchone()[0] == db.SCHEMA_VERSION == 6
        names = {r["name"] for r in con.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'")}
        for t in V6_TABLES:
            assert t in names, f"{t} が無い"
        assert "deleted_at" in {r["name"] for r in con.execute("PRAGMA table_info(asset)")}
        assert "allow_stage3" in {r["name"] for r in con.execute("PRAGMA table_info(root)")}
        assert con.execute(
            "SELECT 1 FROM sqlite_master WHERE name = 'ix_asset_del'").fetchone()
        # **既定は 0**（安全側。段 3 は置き場ごとに許す）
        con.execute("INSERT INTO root(path, display_path, added_at) VALUES ('p', 'P', 't')")
        assert con.execute("SELECT allow_stage3 FROM root").fetchone()[0] == 0
    finally:
        con.close()


def test_v6_migration_is_idempotent_and_the_version_does_not_move(tmp_path: Path):
    """3 回呼んでも `sqlite_master` が変わらない（**索引だけ消える壊し方を捕まえる**）。"""
    con = db.connect(tmp_path)
    try:
        con.executescript(db.DDL)
        con.execute("PRAGMA user_version = 4")
        db.migrate(con)
        assert con.execute("PRAGMA user_version").fetchone()[0] == 6
        before = _dump(con)
        for _ in range(3):
            assert db.migrate(con) == 6
        assert _dump(con) == before, "3 回呼びで形が変わった"
    finally:
        con.close()


def test_a_v5_database_becomes_the_same_v6_as_a_fresh_one(tmp_path: Path):
    """**v5 の道と新規の道が同じ `sqlite_master`** になる（列の順序まで同じ）。"""
    v5 = db.connect(tmp_path / "v5")
    try:
        # **v5 を正しい手順で作る**（`DDL` の後に v2〜v5 の手当てを当てる。手で `V5_TAG_DDL` だけ
        # 足すと v2〜v4 の列が抜けて、形が違って当たり前になる）
        v5.executescript(db.DDL)
        db._migrate_v2(v5)
        db._migrate_v3(v5)
        db._migrate_v4(v5)
        db._migrate_v5(v5)
        v5.execute("PRAGMA user_version = 5")
        db.migrate(v5)
        old = _dump(v5)
    finally:
        v5.close()
    new = db.open_db(tmp_path / "new")
    try:
        assert _dump(new) == old, "v5 から上げた形と新規の形が違う"
    finally:
        new.close()


def test_v6_topps_up_a_database_that_was_made_before_the_columns(tmp_path: Path):
    """**（P4-1 の監査 A-1 と同じ流儀）** 版を上げずに列を足した v6 を補う。

    `migrate()` は `current >= SCHEMA_VERSION` で早期に戻るので、**戻る側でも列を見て補う**。
    ここを外すと「古い v6 の複製」だけ列が無く、段 1 の削除が `no such column: deleted_at` で落ちる。
    """
    con = db.open_db(tmp_path)
    try:
        # **索引を先に落としてから列を落とす**（逆だと `error in index ... after drop column`）。
        # `allow_stage3` は `CHECK` が付いているので `DROP COLUMN` できない（SQLite の制限）——
        # 列が無い古い v6 は**手で作れない**ので、`deleted_at` の道で代表させる
        con.execute("DROP INDEX IF EXISTS ix_asset_del")
        con.execute("ALTER TABLE asset DROP COLUMN deleted_at")
        assert "deleted_at" not in {r["name"] for r in con.execute("PRAGMA table_info(asset)")}

        assert db.migrate(con) == 6                       # 版は上がらない（早期 return の道）
        assert "deleted_at" in {r["name"] for r in con.execute("PRAGMA table_info(asset)")}
        assert "allow_stage3" in {r["name"] for r in con.execute("PRAGMA table_info(root)")}
        assert con.execute("SELECT 1 FROM sqlite_master WHERE name = 'ix_asset_del'").fetchone()
        assert db.migrate(con) == 6                       # 二度足さない
    finally:
        con.close()


def test_v6_check_constraints_reject_the_wrong_vocabulary(tmp_path: Path):
    """**語彙は表でも守る**（家風）。`stage=4`・`(B,A)`・`band=16`・`allow_stage3=2` が入れられない。

    **（P8-0 の監査 F-1）実在の `asset_id` を使う。** 前の版は `asset_id = 'a'`（存在しない）で
    `phash_band` に入れていたので、**外部キーが先に落ちて** `CHECK` の有無と無関係に緑だった
    （**壊しても落ちないテスト**）。ここでは `asset` を 1 行入れてから、その id を使う。
    `delete_request` の `stage` / `actor`・`duplicate_exclusion` と `pending_delete_preview` の
    `actor` も**同じテストで見る**（監査で「未試験」と指摘された分）。
    """
    con = db.open_db(tmp_path)
    try:
        con.execute("INSERT INTO asset(id, sha256, kind, first_seen_at, last_seen_at)"
                    " VALUES ('a1', ?, 'generated', 't', 't')", ("a" * 64,))
        # --- 語彙（deletion_log）---
        with pytest.raises(sqlite3.IntegrityError):
            con.execute("INSERT INTO deletion_log(id, stage, actor, at)"
                        " VALUES ('x', 4, 'human', 't')")
        with pytest.raises(sqlite3.IntegrityError):
            con.execute("INSERT INTO deletion_log(id, stage, actor, at)"
                        " VALUES ('x', 1, 'robot', 't')")
        # --- 語彙（delete_request。監査 F-1 で未試験だった）---
        with pytest.raises(sqlite3.IntegrityError):
            con.execute("INSERT INTO delete_request(id, actor, stage, count, at)"
                        " VALUES ('r1', 'human', 4, 1, 't')")
        with pytest.raises(sqlite3.IntegrityError):
            con.execute("INSERT INTO delete_request(id, actor, stage, count, at)"
                        " VALUES ('r1', 'robot', 1, 1, 't')")
        # --- 順序と語彙（duplicate_exclusion）---
        with pytest.raises(sqlite3.IntegrityError):
            con.execute("INSERT INTO duplicate_exclusion(a_id, b_id, actor, at)"
                        " VALUES ('B', 'A', 'human', 't')")
        with pytest.raises(sqlite3.IntegrityError):
            con.execute("INSERT INTO duplicate_exclusion(a_id, b_id, actor, at)"
                        " VALUES ('A', 'A', 'human', 't')")
        with pytest.raises(sqlite3.IntegrityError):
            con.execute("INSERT INTO duplicate_exclusion(a_id, b_id, actor, at)"
                        " VALUES ('A', 'B', 'robot', 't')")
        # --- 帯の範囲（**実在の asset_id** なので FK では落ちない＝CHECK を見ている）---
        # **（P8-1 の監査 B-1）4bit × 16 本**なので、16 が語彙外・15 が語彙内。
        # 値も 16 進 1 文字だけ（`length(value) = 1`）
        with pytest.raises(sqlite3.IntegrityError):
            con.execute("INSERT INTO phash_band(asset_id, band, value) VALUES ('a1', 16, 'f')")
        with pytest.raises(sqlite3.IntegrityError):
            con.execute("INSERT INTO phash_band(asset_id, band, value) VALUES ('a1', -1, 'f')")
        with pytest.raises(sqlite3.IntegrityError):
            con.execute("INSERT INTO phash_band(asset_id, band, value) VALUES ('a1', 0, 'ff')")
        # --- 語彙（pending_delete_preview）---
        with pytest.raises(sqlite3.IntegrityError):
            con.execute("INSERT INTO pending_delete_preview"
                        "(id, stage, scope_json, items_json, count, bytes, actor,"
                        " created_at, expires_at) VALUES ('p', 0, '{}', '[]', 0, 0, 'human', 't', 't')")
        with pytest.raises(sqlite3.IntegrityError):
            con.execute("INSERT INTO pending_delete_preview"
                        "(id, stage, scope_json, items_json, count, bytes, actor,"
                        " created_at, expires_at) VALUES ('p', 1, '{}', '[]', 0, 0, 'robot', 't', 't')")
        # --- 語彙（root.allow_stage3）---
        con.execute("INSERT INTO root(path, display_path, added_at) VALUES ('p', 'P', 't')")
        with pytest.raises(sqlite3.IntegrityError):
            con.execute("UPDATE root SET allow_stage3 = 2")
        # --- 正しい値は通る ---
        con.execute("INSERT INTO duplicate_exclusion(a_id, b_id, actor, at)"
                    " VALUES ('A', 'B', 'human', 't')")
        con.execute("INSERT INTO deletion_log(id, stage, actor, at) VALUES ('ok', 3, 'agent', 't')")
        con.execute("INSERT INTO phash_band(asset_id, band, value) VALUES ('a1', 15, 'f')")
        con.execute("INSERT INTO delete_request(id, actor, stage, count, at)"
                    " VALUES ('rok', 'agent', 2, 1, 't')")
        con.execute("INSERT INTO pending_delete_preview"
                    "(id, stage, scope_json, items_json, count, bytes, actor,"
                    " created_at, expires_at) VALUES ('pok', 1, '{}', '[]', 0, 0, 'agent', 't', 't')")
    finally:
        con.close()


def test_v6_foreign_keys_and_indexes_are_declared(tmp_path: Path):
    """**（P8-0 の監査 F-2）外部キー・主キー・平の索引を守る。**

    前の版は v5 の道と新規の道の `sqlite_master` を比べるだけだったので、**両方から同じ物を
    落とすと気づけなかった**。ここでは **1 つずつ外すと落ちる**形で固定する。
    """
    con = db.open_db(tmp_path)
    try:
        con.execute("INSERT INTO asset(id, sha256, kind, first_seen_at, last_seen_at)"
                    " VALUES ('a1', ?, 'generated', 't', 't')", ("a" * 64,))
        # **`deletion_log.request_id` の外部キー**（知らない要求を指せない）
        with pytest.raises(sqlite3.IntegrityError):
            con.execute("INSERT INTO deletion_log(id, request_id, stage, actor, at)"
                        " VALUES ('d1', 'nope', 1, 'human', 't')")
        # 参照のある `delete_request` は消せない（既定の RESTRICT）
        con.execute("INSERT INTO delete_request(id, actor, stage, count, at)"
                    " VALUES ('r1', 'human', 1, 1, 't')")
        con.execute("INSERT INTO deletion_log(id, request_id, stage, actor, at)"
                    " VALUES ('d2', 'r1', 1, 'human', 't')")
        with pytest.raises(sqlite3.IntegrityError):
            con.execute("DELETE FROM delete_request WHERE id = 'r1'")
        # **`phash_band` の主キー（asset_id, band）**（同じ帯を 2 行入れられない）
        con.execute("INSERT INTO phash_band(asset_id, band, value) VALUES ('a1', 0, '0')")
        with pytest.raises(sqlite3.IntegrityError):
            con.execute("INSERT INTO phash_band(asset_id, band, value) VALUES ('a1', 0, 'f')")
        # **平の索引 4 本が `sqlite_master` にあり、`INDEXED BY` で引ける**
        # （`INDEXED BY` は**索引が無ければ SQLite がエラーにする**ので、存在と使えることの
        #  両方が分かる。行数が少ないと SQLite は全走査を選ぶので、計画任せでは守れない）
        names = {row[0] for row in con.execute(
            "SELECT name FROM sqlite_master WHERE type = 'index'")}
        for want in ("ix_deletion_asset", "ix_deletion_request", "ix_phash_band", "ix_preview_expiry"):
            assert want in names, f"{want} が無い（索引を外すと気づかない）"
        for i in range(20):
            con.execute("INSERT INTO deletion_log(id, asset_id, request_id, stage, actor, at)"
                        " VALUES (?, 'a1', 'r1', 1, 'human', 't')", (f"x{i}",))
            con.execute("INSERT INTO pending_delete_preview"
                        "(id, stage, scope_json, items_json, count, bytes, actor, created_at,"
                        " expires_at) VALUES (?, 1, '{}', '[]', 0, 0, 'human', 't', ?)",
                        (f"p{i}", f"2026-01-01T00:00:{i:02d}Z"))
        plans = {label: " ".join(str(r[3]) for r in con.execute("EXPLAIN QUERY PLAN " + sql))
                 for label, sql in (
                     ("ix_deletion_asset",
                      "SELECT * FROM deletion_log INDEXED BY ix_deletion_asset WHERE asset_id = 'a1'"),
                     ("ix_deletion_request",
                      "SELECT * FROM deletion_log INDEXED BY ix_deletion_request"
                      " WHERE request_id = 'r1'"),
                     ("ix_phash_band",
                      "SELECT * FROM phash_band INDEXED BY ix_phash_band WHERE band = 0"),
                     ("ix_preview_expiry",
                      "SELECT * FROM pending_delete_preview INDEXED BY ix_preview_expiry"
                      " WHERE expires_at < '2026-01-02'"),
                 )}
        for label, plan in plans.items():
            assert label in plan, f"{label} が引かれない: {plan}"
    finally:
        con.close()


def test_v6_tables_are_added_to_a_p7_style_v6_database(tmp_path: Path):
    """**（P8-0 の監査 C-1）P7 が `user_version = 6` を付けた DB でも P8 の表が入る。**

    P7 の v6 は**別の 6 表**（`recipe_*`）だった。版だけ 6 の DB は `migrate()` の早期 return に
    当たって `_migrate_v6` を通らないので、**P8 の 5 表を一生持たない**（版は 6 と答えるので
    `health` も通り、P8-1 以降で `no such table: deletion_log` になる）。
    ここでは「P7 の v6」を合成して、`migrate()` で表が入ることを固定する。
    """
    con = db.open_db(tmp_path)
    try:
        # P7 の v6 を真似る: 版だけ 6 にして、P8 の 5 表を落とす
        for table in ("delete_request", "deletion_log", "duplicate_exclusion",
                      "phash_band", "pending_delete_preview"):
            con.execute(f"DROP TABLE {table}")
        con.execute("PRAGMA user_version = 6")
        assert not con.execute("SELECT 1 FROM sqlite_master WHERE name = 'deletion_log'").fetchone()
        assert db.migrate(con) == 6
        names = {row[0] for row in con.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        for table in ("delete_request", "deletion_log", "duplicate_exclusion",
                      "phash_band", "pending_delete_preview"):
            assert table in names, f"{table} が入っていない（P7 の v6 の道が穴）"
        # **何度呼んでも同じ**（表も索引も増えない）
        before = con.execute("SELECT count(*) FROM sqlite_master").fetchone()[0]
        db.migrate(con)
        assert con.execute("SELECT count(*) FROM sqlite_master").fetchone()[0] == before
    finally:
        con.close()


def test_v6_partial_indexes_are_used(tmp_path: Path):
    """**部分索引が本当に引かれる**（`EXPLAIN QUERY PLAN`。P7 の申し送りの流儀）。

    空の表だと SQLite は全走査を選ぶ（索引を使う理由が無い）ので、**行を入れてから**計画を見る。
    一意な部分索引（`ux_request_token`）は `INDEXED BY` でも確かめる
    （**索引が無ければ SQLite がエラーにする**＝存在と使えることの両方が分かる）。
    """
    con = db.open_db(tmp_path)
    try:
        con.execute("INSERT INTO asset(id, sha256, kind, first_seen_at, last_seen_at, deleted_at)"
                    " VALUES ('a1', ?, 'generated', 't', 't', 't')", ("a" * 64,))
        for i in range(20):
            con.execute("INSERT INTO delete_request(id, client_token, actor, stage, count, at)"
                        " VALUES (?, ?, 'human', 1, 1, 't')", (f"r{i}", f"tok{i}"))
            con.execute("INSERT INTO deletion_log(id, stage, actor, at, restored_at)"
                        " VALUES (?, 3, 'human', 't', NULL)", (f"d{i}",))
        plans = {}
        for label, sql in (
            ("ix_asset_del", "SELECT * FROM asset WHERE deleted_at IS NOT NULL"),
            ("ix_deletion_pending",
             "SELECT * FROM deletion_log WHERE stage = 3 AND restored_at IS NULL"),
        ):
            plans[label] = " ".join(str(r[3]) for r in con.execute("EXPLAIN QUERY PLAN " + sql))
        assert "ix_asset_del" in plans["ix_asset_del"], plans
        assert "ix_deletion_pending" in plans["ix_deletion_pending"], plans
        # 一意な部分索引（**INDEXED BY は索引が無いとエラーになる**）。
        # **部分索引は `WHERE` が索引の条件を含意しないと使えない**ので、`IS NOT NULL` も書く。
        # **名前は `ux_delete_token`**（設計の `ux_request_token` は P6 が `review_request` で
        # 使っていて衝突し、`IF NOT EXISTS` が黙って何もしない＝再送の一意性が守られなかった）
        got = con.execute("SELECT count(*) FROM delete_request INDEXED BY ux_delete_token"
                          " WHERE client_token = 'tok7' AND client_token IS NOT NULL").fetchone()[0]
        assert got == 1
        # **同じ token は 2 行入らない**（部分索引が本当に効いている）
        with pytest.raises(sqlite3.IntegrityError):
            con.execute("INSERT INTO delete_request(id, client_token, actor, stage, count, at)"
                        " VALUES ('dup', 'tok7', 'human', 1, 1, 't')")
        # **NULL は何行でも入る**（部分索引なので）
        for i in range(3):
            con.execute("INSERT INTO delete_request(id, client_token, actor, stage, count, at)"
                        " VALUES (?, NULL, 'human', 1, 1, 't')", (f"null{i}",))
    finally:
        con.close()


def test_v6_deleting_an_asset_takes_its_bands(tmp_path: Path):
    """`phash_band` は `asset` に `ON DELETE CASCADE`（**帯だけ残らない**）。"""
    con = db.open_db(tmp_path)
    try:
        con.execute("INSERT INTO asset(id, sha256, kind, first_seen_at, last_seen_at)"
                    " VALUES ('a1', ?, 'generated', 't', 't')", ("a" * 64,))
        con.execute("INSERT INTO phash_band(asset_id, band, value) VALUES ('a1', 0, 'f')")
        con.execute("DELETE FROM asset WHERE id = 'a1'")
        assert con.execute("SELECT count(*) FROM phash_band").fetchone()[0] == 0
    finally:
        con.close()
