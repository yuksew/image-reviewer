"""P2-0（スキーマ v7 = 取り込みとカタログ）のテスト。

設計: `docs/design.md` §5.3（`folder` / `folder_member`）・§6.1（カタログの口）・
§10.1〜§10.2（仮想フォルダとスマートフォルダ）・§5.1（取り込み元の `source` / `source_url` /
`ref_tags`）。**P2 の設計書（`docs/p2-design.md`）は無い**ので、`design.md` の字が正。

**この小段は機能を足さない**（表と列だけ。P8-0 / P6-0 / P4-0 と同じ流儀）。守るのは:

- **v6 → v7 で行も値も変わらない**（`asset` / `decision` / `deletion_log` など。家風「移行は足すだけ」）
- v7 の**表・列・索引・外部キー**が在り、**外部キーが本当に効く**（フォルダを物理で消すと中身も、
  画像を消すと中身も消える。**論理削除では消さない**＝設計の決め）
- **2 回目・3 回目の移行が何もしない**（`sqlite_master` が変わらない。索引を落とす壊し方を捕まえる）
- **索引名が黙って無効にならない**（`CREATE INDEX IF NOT EXISTS` は同名が他の表にあると何もしない。
  P8-0 の監査 C-0 で実際に踏んだ型）
- **`GET` は 1 バイトも書かない**（家風。ファイルの中身と全表の中身を前後で比べる）
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from image_reviewer import backup, db
from image_reviewer.store import Store

HUMAN = {"X-Image-Reviewer-Actor": "human"}
CATALOG_TABLES = ("folder", "folder_member")


# ---- 下ごしらえ ----


def _make_v6(data: Path) -> sqlite3.Connection:
    """**v6 の DB** を手順どおりに作る（`DDL` → v2〜v6 の手当て → `user_version = 6`）。

    `db.open_db()` を使うと v7 まで上がってしまうので、**v6 で止める**。
    実データの複製をテストに持ち込まないため、中身は合成の行（`_seed_v6`）で作る。
    """
    data.mkdir(parents=True, exist_ok=True)
    con = db.connect(data)
    con.executescript(db.DDL)
    db._migrate_v2(con)
    db._migrate_v3(con)
    db._migrate_v4(con)
    db._migrate_v5(con)
    db._migrate_v6(con)
    con.execute("PRAGMA user_version = 6")
    _seed_v6(con)
    return con


def _seed_v6(con: sqlite3.Connection) -> None:
    """v6 の形の**合成データ**（どの表にも 1 行以上入れて、移行で消えないことを見る）。

    `asset.phash` は**帯を 16 本そろえて**入れる（`_top_up_v6` の `fill_missing_bands` が
    「足りない帯を埋める」で行を増やさないように。実データも 463 枚 × 16 本そろっている）。
    """
    from image_reviewer.duplicates import bands_of

    con.execute("INSERT INTO settings(key, value) VALUES ('undo_window_sec', '300')")
    con.execute("INSERT INTO root(path, display_path, added_at, allow_stage3)"
                " VALUES ('r', 'R', 't', 1)")
    con.execute("INSERT INTO reason_code(id, label, applies_to, position, builtin, active)"
                " VALUES ('rc1', '構図が良い', 'both', 1, 1, 1)")
    con.execute("INSERT INTO review_group(id, title, kind, source, policy, state,"
                " created_at, changed_at) VALUES ('g1', 'まとまり', 'manual', 'manual',"
                " 'pick_one', 'open', 't', 't')")
    phash = "0123456789abcdef"
    for asset_id, sha in (("a1", "a" * 64), ("a2", "b" * 64)):
        con.execute(
            "INSERT INTO asset(id, sha256, kind, kind_source, width, height, format,"
            " review_state, review_reason_code_id, reviewed_at, reviewed_by, phash, dhash,"
            " first_seen_at, last_seen_at, deleted_at)"
            " VALUES (?,?,'generated','auto:png',16,16,'png','kept','rc1','t','human',?,?,"
            " 't','t',NULL)", (asset_id, sha, phash, phash))
        con.execute("INSERT INTO asset_location(path, display_path, asset_id, size, mtime_ns,"
                    " is_primary, missing_at, last_seen_at)"
                    " VALUES (?,?,?,10,1,1,NULL,'t')", (f"c:/img/{asset_id}.png",
                                                        f"C:/img/{asset_id}.png", asset_id))
        con.execute("INSERT INTO asset_meta(asset_id, meta_json, note, source, extracted_at)"
                    " VALUES (?,?,?,'scan','t')", (asset_id, json.dumps({"seed": asset_id}),
                                                    "メモ"))
        con.execute("INSERT INTO group_item(group_id, asset_id, position) VALUES ('g1',?,0)",
                    (asset_id,))
        con.executemany("INSERT INTO phash_band(asset_id, band, value) VALUES (?,?,?)",
                        [(asset_id, band, value) for band, value in bands_of(phash)])
    con.execute("INSERT INTO decision(id, seq, subject_type, subject_id, group_id, verdict,"
                " reason_code_id, note, actor, group_decision, created_at)"
                " VALUES ('d1', 1, 'asset', 'a1', 'g1', 'keep', 'rc1', '良い', 'human',"
                " 'selected', 't')")
    con.execute("INSERT INTO decision(id, seq, subject_type, subject_id, verdict, actor,"
                " client_token, created_at)"
                " VALUES ('d2', 2, 'asset', 'a2', 'reject', 'agent', 'tok-d2', 't')")
    con.execute("INSERT INTO delete_request(id, client_token, actor, stage, count, at)"
                " VALUES ('q1', 'tok-q1', 'human', 1, 1, 't')")
    con.execute("INSERT INTO deletion_log(id, asset_id, path, stage, request_id, reason,"
                " stuck_reason, closed_at, close_reason, actor, at)"
                " VALUES ('l1', 'a1', 'c:/img/a1.png', 1, 'q1', '重複', 'missing', 't',"
                " 'missing', 'human', 't')")
    con.execute("INSERT INTO duplicate_exclusion(a_id, b_id, reason, actor, at)"
                " VALUES ('a1', 'a2', '別物', 'human', 't')")
    con.execute("INSERT INTO pending_delete_preview(id, stage, scope_json, items_json, count,"
                " bytes, actor, created_at, expires_at)"
                " VALUES ('p1', 1, '{}', '[]', 0, 0, 'human', 't', 't')")
    con.execute("INSERT INTO location_history(asset_id, path, size, mtime_ns,"
                " replaced_by_asset_id, replaced_at, to_path, reason, actor)"
                " VALUES ('a2', 'C:/img/old.png', 10, 1, 'a1', 't', NULL, 'replaced', NULL)")
    con.execute("INSERT INTO tag(id, name, category, category_name, known)"
                " VALUES (1, '1girl', 0, 'general', 1)")
    con.execute("INSERT INTO asset_tag(asset_id, tag_id, score, source, model, actor, tagged_at)"
                " VALUES ('a1', 1, 0.9, 'wd14', 'wd14', NULL, 't')")
    con.execute("INSERT INTO tag_gloss(tag_id, ja, source, engine, edited, created_at,"
                " updated_at) VALUES (1, '女の子', 'textgenerate', 'llm', 0, 't', 't')")
    con.execute("INSERT INTO job(id, kind, state, params, progress_done, progress_total,"
                " message, note, error, created_at, started_at, finished_at, cancel_requested)"
                " VALUES ('j1', 'tag', 'done', '{}', 2, 2, '完了', '2 枚', NULL, 't', 't', 't', 0)")
    con.execute("INSERT INTO job_item(job_id, ref, state, error) VALUES ('j1', 'a1', 'tagged', NULL)")
    con.execute("INSERT INTO comparison_cache(a_id, b_id, algo_version, ssim,"
                " changed_fraction, mean_abs, computed_at)"
                " VALUES ('a1', 'a2', 1, 0.5, 0.1, 3.0, 't')")
    con.execute("INSERT INTO review_request(id, group_id, target_key, state, actor, created_at)"
                " VALUES ('rq1', 'g1', 'a1', 'open', 'agent', 't')")
    con.execute("INSERT INTO annotation(id, asset_id, shape, x, y, w, h, body, actor,"
                " created_at, group_id) VALUES ('n1', 'a1', 'rect', 0.1, 0.1, 0.2, 0.2,"
                " 'ここ', 'human', 't', 'g1')")


def _tables(con: sqlite3.Connection) -> list[str]:
    return [row[0] for row in con.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
        " ORDER BY name")]


def _contents(con: sqlite3.Connection) -> dict[str, dict]:
    """表ごとの**列と行**（`rowid` 順）。列の一覧も持つ（移行で列が増えた分を比べないため）。"""
    out: dict[str, dict] = {}
    for table in _tables(con):
        columns = [row[1] for row in con.execute(f"PRAGMA table_info({table})")]
        rows = [tuple(row) for row in con.execute(
            f"SELECT {', '.join(columns)} FROM {table} ORDER BY rowid")]
        out[table] = {"columns": columns, "rows": rows}
    return out


def _dump(con: sqlite3.Connection) -> list:
    """`sqlite_master` の中身（**表と索引の `sql` まで**比べる。P7-0 の監査 F-1 の教訓）。"""
    return [(row["type"], row["name"], (row["sql"] or "").replace("\n", " "))
            for row in con.execute("SELECT type, name, sql FROM sqlite_master"
                                  " ORDER BY type, name")]


def _user_version(path: Path) -> int:
    con = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    try:
        return con.execute("PRAGMA user_version").fetchone()[0]
    finally:
        con.close()


# ---- 1. v7 の形 ----


def test_v7_adds_the_catalog_tables_columns_and_indexes(tmp_path: Path):
    """v7 で `folder` / `folder_member` と `asset` の取り込み元の 3 列が入る（設計 §5.3・§5.1）。"""
    con = db.open_db(tmp_path)
    try:
        assert con.execute("PRAGMA user_version").fetchone()[0] == db.SCHEMA_VERSION
        assert db.SCHEMA_VERSION == 7
        names = {row[0] for row in con.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'")}
        for table in CATALOG_TABLES:
            assert table in names, f"{table} が無い"
        folder_columns = {row[1] for row in con.execute("PRAGMA table_info(folder)")}
        for column in ("id", "parent_id", "name", "kind", "smart_query", "position",
                       "count_cache", "count_cached_at", "created_at", "deleted_at"):
            assert column in folder_columns, f"folder.{column} が無い"
        member_columns = {row[1] for row in con.execute("PRAGMA table_info(folder_member)")}
        assert member_columns == {"folder_id", "asset_id", "position", "added_at"}
        asset_columns = {row[1] for row in con.execute("PRAGMA table_info(asset)")}
        for column in ("source", "source_url", "ref_tags"):
            assert column in asset_columns, f"asset.{column} が無い"
        # 索引は**名前だけでなく、どの表の物か**まで見る（`IF NOT EXISTS` は同名で黙る）
        for name, table in db.V7_INDEXES:
            row = con.execute("SELECT tbl_name FROM sqlite_master WHERE type = 'index'"
                              " AND name = ?", (name,)).fetchone()
            assert row is not None, f"{name} が無い（索引を外すと気づかない）"
            assert row[0] == table, f"{name} が {table} の索引ではない: {row[0]}"
    finally:
        con.close()


def test_the_catalog_shape_is_the_design_not_the_sketch(tmp_path: Path):
    """**設計 §5.3 の字**に従っている（指示書の `folder_item` / `smart_folder` は作らない）。

    設計は「1 枚が複数のフォルダ」を `folder_member` の多対多で表し、**スマートフォルダは
    別表ではなく `folder.kind='smart'` の行**（条件は `smart_query`）と決めている。
    ここを取り違えると、P2-1 が設計 §6.1 の口（`POST /api/folders {parent_id,name,kind}`）を
    作れなくなる。**設計の字を固定する**ための試験。
    """
    con = db.open_db(tmp_path)
    try:
        names = {row[0] for row in con.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'")}
        assert "folder_item" not in names
        assert "smart_folder" not in names
        # 階層（親）と並び（position）と種別（manual / smart）が `folder` に在る
        con.execute("INSERT INTO folder(id, name, kind, created_at)"
                    " VALUES ('f1', '2026-10 生成', 'manual', 't')")
        con.execute("INSERT INTO folder(id, parent_id, name, kind, position, created_at)"
                    " VALUES ('f2', 'f1', '気に入った', 'manual', 1, 't')")
        con.execute("INSERT INTO folder(id, name, kind, smart_query, created_at)"
                    " VALUES ('f3', '1girl だけ', 'smart', '{\"all\": []}', 't')")
        # **名前は一意ではない**（設計 §5.3 は UNIQUE を要求していない。親が違えば同名は普通）
        con.execute("INSERT INTO folder(id, name, kind, created_at)"
                    " VALUES ('f4', '2026-10 生成', 'manual', 't')")
        assert con.execute("SELECT count(*) FROM folder WHERE name = '2026-10 生成'"
                           ).fetchone()[0] == 2
    finally:
        con.close()


def test_v7_check_constraints_reject_the_wrong_vocabulary(tmp_path: Path):
    """語彙は表でも守る（家風）。`folder.kind` と `asset.source` の外は入れられない。"""
    con = db.open_db(tmp_path)
    try:
        con.execute("INSERT INTO asset(id, sha256, kind, first_seen_at, last_seen_at)"
                    " VALUES ('a1', ?, 'generated', 't', 't')", ("a" * 64,))
        # `asset.source` は**既定が 'scan'**（実データの 463 枚は全部走査で入った）
        assert con.execute("SELECT source FROM asset WHERE id = 'a1'").fetchone()[0] == "scan"
        for good in ("scan", "drop", "clipboard", "url", "watch"):
            con.execute("UPDATE asset SET source = ? WHERE id = 'a1'", (good,))
        with pytest.raises(sqlite3.IntegrityError):
            con.execute("UPDATE asset SET source = 'file' WHERE id = 'a1'")
        # `folder.kind` は 'manual' | 'smart' だけ
        with pytest.raises(sqlite3.IntegrityError):
            con.execute("INSERT INTO folder(id, name, kind, created_at)"
                        " VALUES ('f0', 'x', 'robot', 't')")
        con.execute("INSERT INTO folder(id, name, kind, created_at)"
                    " VALUES ('f1', 'x', 'manual', 't')")
    finally:
        con.close()


# ---- 2. 外部キーが本当に効く ----


def test_the_catalog_foreign_keys_are_declared_as_cascades(tmp_path: Path):
    """`folder_member` の 2 つの外部キーは**両方 CASCADE**、`folder.parent_id` も CASCADE。"""
    con = db.open_db(tmp_path)
    try:
        got = {row[2]: (row[3], row[6]) for row in con.execute(
            "PRAGMA foreign_key_list(folder_member)")}
        assert got["folder"] == ("folder_id", "CASCADE")
        assert got["asset"] == ("asset_id", "CASCADE")
        parent = {row[2]: row[6] for row in con.execute("PRAGMA foreign_key_list(folder)")}
        assert parent["folder"] == "CASCADE"
        assert con.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    finally:
        con.close()


def test_deleting_a_folder_or_an_asset_takes_its_members(tmp_path: Path):
    """**外部キーを外すと落ちる**。フォルダを物理で消すと中身も、画像を消すと中身も消える。

    設計 §5.3 の `ON DELETE CASCADE`。**論理削除（`asset.deleted_at`）では消さない**——
    そちらは読む側が外す（P2-1）。ここはその 2 つを分けて固定する。
    """
    con = db.open_db(tmp_path)
    try:
        for asset_id, sha in (("a1", "a" * 64), ("a2", "b" * 64)):
            con.execute("INSERT INTO asset(id, sha256, kind, first_seen_at, last_seen_at)"
                        " VALUES (?, ?, 'generated', 't', 't')", (asset_id, sha))
        con.execute("INSERT INTO folder(id, name, kind, created_at)"
                    " VALUES ('p', '親', 'manual', 't')")
        con.execute("INSERT INTO folder(id, parent_id, name, kind, created_at)"
                    " VALUES ('c', 'p', '子', 'manual', 't')")
        con.execute("INSERT INTO folder_member(folder_id, asset_id, added_at)"
                    " VALUES ('c', 'a1', 't')")
        con.execute("INSERT INTO folder_member(folder_id, asset_id, added_at)"
                    " VALUES ('p', 'a2', 't')")
        # 論理削除では行が残る（設計の決め。カタログから外すのは読む側）
        con.execute("UPDATE asset SET deleted_at = 't' WHERE id = 'a1'")
        assert con.execute("SELECT count(*) FROM folder_member").fetchone()[0] == 2
        # 画像を**物理で**消すと、その画像の中身が消える
        con.execute("DELETE FROM asset WHERE id = 'a1'")
        assert [row[0] for row in con.execute("SELECT asset_id FROM folder_member")] == ["a2"]
        # 親フォルダを消すと、子フォルダ（parent_id の CASCADE）も中身も消える
        con.execute("DELETE FROM folder WHERE id = 'p'")
        assert con.execute("SELECT count(*) FROM folder").fetchone()[0] == 0
        assert con.execute("SELECT count(*) FROM folder_member").fetchone()[0] == 0
    finally:
        con.close()


def test_the_folder_member_key_rejects_bad_rows(tmp_path: Path):
    """主キー `(folder_id, asset_id)` と外部キーが**本物**（知らない id・二重を入れられない）。"""
    con = db.open_db(tmp_path)
    try:
        con.execute("INSERT INTO asset(id, sha256, kind, first_seen_at, last_seen_at)"
                    " VALUES ('a1', ?, 'generated', 't', 't')", ("a" * 64,))
        con.execute("INSERT INTO folder(id, name, kind, created_at)"
                    " VALUES ('f1', 'x', 'manual', 't')")
        con.execute("INSERT INTO folder_member(folder_id, asset_id, added_at)"
                    " VALUES ('f1', 'a1', 't')")
        with pytest.raises(sqlite3.IntegrityError):
            con.execute("INSERT INTO folder_member(folder_id, asset_id, added_at)"
                        " VALUES ('f1', 'a1', 't')")
        with pytest.raises(sqlite3.IntegrityError):
            con.execute("INSERT INTO folder_member(folder_id, asset_id, added_at)"
                        " VALUES ('nope', 'a1', 't')")
        with pytest.raises(sqlite3.IntegrityError):
            con.execute("INSERT INTO folder_member(folder_id, asset_id, added_at)"
                        " VALUES ('f1', 'nope', 't')")
    finally:
        con.close()


# ---- 3. v6 → v7 の移行（中身が変わらない・冪等）----


def test_v6_to_v7_keeps_every_row_and_value(tmp_path: Path):
    """**v6 の DB を v7 に上げても、行数も値も変わらない**（家風「移行は足すだけ」）。

    `asset` は**列が 3 つ増える**ので、増える前の列だけで比べる。増えた列は
    `source='scan'`・`source_url`/`ref_tags` は NULL で埋まる（実データの 463 枚は走査で入った）。

    壊すと落ちる: 移行で表を作り直す／`DELETE` する／`UPDATE` する実装。
    """
    data = tmp_path / "v6"
    con = _make_v6(data)
    try:
        before = _contents(con)
        assert con.execute("PRAGMA user_version").fetchone()[0] == 6
        assert db.migrate(con) == db.SCHEMA_VERSION
        assert con.execute("PRAGMA user_version").fetchone()[0] == 7
        after = _contents(con)
        # **行数と値**（列は移行前の一覧で読む）
        for table, old in before.items():
            assert table in after, f"{table} が消えた"
            columns = old["columns"]
            rows = [tuple(row) for row in con.execute(
                f"SELECT {', '.join(columns)} FROM {table} ORDER BY rowid")]
            assert rows == old["rows"], f"{table} の値が変わった"
        # **増えた表は空**（v7 は表を足すだけ）
        for table in CATALOG_TABLES:
            assert con.execute(f"SELECT count(*) FROM {table}").fetchone()[0] == 0
        # **増えた列の埋まり方**
        assert con.execute("SELECT min(source), max(source) FROM asset").fetchone()[:] == ("scan", "scan")
        assert con.execute("SELECT count(*) FROM asset WHERE source_url IS NOT NULL"
                           " OR ref_tags IS NOT NULL").fetchone()[0] == 0
        # 帯（`_top_up_v6` が走っても増えない）
        assert con.execute("SELECT count(*) FROM phash_band").fetchone()[0] == 32
    finally:
        con.close()


def test_a_v6_database_becomes_the_same_v7_shape_as_a_fresh_one(tmp_path: Path):
    """**v6 から上げた形と新規の形が同じ**（表・索引の `sql` まで。列の順序も）。

    `ALTER TABLE ADD COLUMN` は末尾に足すので、新規の DB も**同じ道**（v1 の `DDL` → v7 の
    `ALTER`）を通る。片方だけ `DDL` に列を書くとここで落ちる。
    """
    v6 = db.connect(tmp_path / "old")
    try:
        v6.executescript(db.DDL)
        db._migrate_v2(v6)
        db._migrate_v3(v6)
        db._migrate_v4(v6)
        db._migrate_v5(v6)
        db._migrate_v6(v6)
        v6.execute("PRAGMA user_version = 6")
        db.migrate(v6)
        old = _dump(v6)
    finally:
        v6.close()
    fresh = db.open_db(tmp_path / "new")
    try:
        assert _dump(fresh) == old, "v6 から上げた形と新規の形が違う"
    finally:
        fresh.close()


def test_the_v7_migration_is_idempotent(tmp_path: Path):
    """**3 回呼んでも `sqlite_master` と中身が変わらない**（索引だけ消える壊し方を捕まえる）。"""
    con = _make_v6(tmp_path / "data")
    try:
        assert db.migrate(con) == 7
        before = (_dump(con), _contents(con))
        for _ in range(3):
            assert db.migrate(con) == 7
        assert (_dump(con), _contents(con)) == before, "移行を繰り返すと形か中身が変わる"
    finally:
        con.close()


# ---- 4. 索引名が黙って無効にならない（P8-0 の監査 C-0 の型）----


def test_a_squatted_index_name_is_refused_loudly(tmp_path: Path):
    """**同じ名前の索引が他の表にあると `IF NOT EXISTS` は黙って何もしない**。

    そのまま通すと「版は 7・`folder` に索引が無い」という静かな穴になる（P8-0 の監査 C-0 で
    `ux_request_token` が実際に踏んだ）。`_check_v7_shape` が**落とす**ことを固定する。
    **落ちても版は上がらない**（次の起動でやり直せる）。
    """
    data = tmp_path / "data"
    con = _make_v6(data)
    try:
        con.execute("CREATE INDEX ix_folder_parent ON asset(kind)")     # 名前だけ先に取る
        with pytest.raises(RuntimeError) as got:
            db.migrate(con)
        assert "ix_folder_parent" in str(got.value)
        assert con.execute("PRAGMA user_version").fetchone()[0] == 6    # 版は上げない
        # 邪魔者をどければ、やり直しで正しい形になる
        con.execute("DROP INDEX ix_folder_parent")
        assert db.migrate(con) == 7
    finally:
        con.close()


def test_a_squatted_catalog_table_is_refused_loudly(tmp_path: Path):
    """**別の形の `folder` が居たら落とす**（`CREATE TABLE IF NOT EXISTS` は既存の表を変えない）。"""
    data = tmp_path / "data"
    con = _make_v6(data)
    try:
        con.execute("CREATE TABLE folder (id TEXT PRIMARY KEY, parent_id TEXT, name TEXT,"
                    " kind TEXT, smart_query TEXT, position INTEGER, count_cache INTEGER,"
                    " count_cached_at TEXT, created_at TEXT)")
        with pytest.raises(RuntimeError) as got:
            db.migrate(con)
        assert "deleted_at" in str(got.value)
        assert con.execute("PRAGMA user_version").fetchone()[0] == 6
        con.execute("DROP TABLE folder")
        assert db.migrate(con) == 7
    finally:
        con.close()


# ---- 5. 控えを取ってから版を上げる（既存の P8-4 の道が v7 でも効く）----


def test_the_pre_migrate_backup_is_a_v6_copy_before_the_version_moves(tmp_path: Path):
    """**v6 の控えを取ってから v7 に上げる**（`pre-migrate-<日時>/`。

    控えは**その版の最後の姿**（設計 §0.12-6）。中身が v6 のままであること・manifest が在ること・
    `prune` で消えないことを見る。壊すと落ちる: 控えを取らずに移行する／控えの中身が v7。
    """
    data = tmp_path / "data"
    backups = tmp_path / "backups"
    con = _make_v6(data)
    con.close()
    got = backup.backup_before_migrate(data, backup_dir=backups)
    assert got is not None
    folder = Path(got["dir"])
    assert folder.name.startswith(backup.PRE_MIGRATE_PREFIX)
    assert folder.parent == backups
    manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["counts"]["assets"] == 2
    # **どの版からどの版へ**かは戻り値に残る（manifest は契約の欄だけ）
    assert got["from_version"] == 6 and got["to_version"] == 7
    con = sqlite3.connect(f"file:{(folder / 'db.sqlite3').as_posix()}?mode=ro", uri=True)
    try:
        assert con.execute("PRAGMA user_version").fetchone()[0] == 6     # **控えは v6**
        assert not con.execute("SELECT 1 FROM sqlite_master WHERE name = 'folder'").fetchone()
        assert con.execute("SELECT count(*) FROM asset").fetchone()[0] == 2
    finally:
        con.close()
    # 掃除の対象にしない（版が上がる前の姿）
    backup.prune_snapshots(backups, keep=0)
    assert any(s["kind"] == "pre-migrate" for s in backup.list_snapshots(backups))
    # 控えの後に版が上がる
    con = db.open_db(data)
    try:
        assert con.execute("PRAGMA user_version").fetchone()[0] == 7
    finally:
        con.close()


def test_the_version_does_not_move_when_the_backup_fails(tmp_path: Path, monkeypatch):
    """**控えが取れないなら版を上げない**（読み取り専用で起動して案内する。設計 §0.12-6）。

    差し替えで確かめる（`app.backup_before_migrate` を落とす）。**v7 の表が 1 つも作られず、
    版も 6 のまま**であること。壊すと落ちる: 控えの失敗を握りつぶして `migrate()` を走らせる。
    """
    from image_reviewer import app as app_module

    data = tmp_path / "data"
    con = _make_v6(data)
    con.close()
    monkeypatch.setenv("IMAGE_REVIEWER_DATA", str(data))
    monkeypatch.setenv("IMAGE_REVIEWER_BACKUP_DIR", str(tmp_path / "backups"))

    def boom(*_args, **_kwargs):
        raise RuntimeError("控えを作れません（差し替え）")

    monkeypatch.setattr(app_module, "backup_before_migrate", boom)
    app = app_module.create_app()
    with TestClient(app, base_url="http://127.0.0.1") as client:
        health = client.get("/api/health/db", headers=HUMAN)
        assert health.status_code == 503
        body = health.json()
        assert body["read_only"] is True
        assert body["reason"] == "pre_migrate_backup_failed"
        # 読みは通る（読めば何が残っているか分かる）
        assert client.get("/api/assets", headers=HUMAN).status_code == 200
        assert client.post("/api/backup", headers=HUMAN, json={}).status_code == 503
    assert _user_version(data / "db.sqlite3") == 6
    con = sqlite3.connect(f"file:{(data / 'db.sqlite3').as_posix()}?mode=ro", uri=True)
    try:
        names = {row[0] for row in con.execute("SELECT name FROM sqlite_master"
                                               " WHERE type = 'table'")}
        assert "folder" not in names and "folder_member" not in names
        assert con.execute("SELECT count(*) FROM asset").fetchone()[0] == 2
    finally:
        con.close()


# ---- 6. GET は 1 バイトも書かない ----


def _make_png(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (16, 16), (11, 22, 33)).save(path)
    return path


def _register(store: Store, path: Path) -> str:
    blob = path.read_bytes()
    asset_id, _ = store.register(
        sha256=hashlib.sha256(blob).hexdigest(), path=str(path), size=len(blob),
        mtime_ns=path.stat().st_mtime_ns, width=16, height=16, fmt="png",
        meta=None, note=None)
    return asset_id


def _files(root: Path) -> dict:
    """ファイルの**中身まで**（`GET` が 1 バイトも書かないことの検査）。"""
    out = {}
    for path in sorted(Path(root).rglob("*")):
        if path.is_file():
            got = path.stat()
            out[str(path.relative_to(root))] = (
                got.st_size, got.st_mtime_ns, hashlib.sha256(path.read_bytes()).hexdigest())
    return out


def _rows_digest(con: sqlite3.Connection) -> dict:
    out = {}
    for table in _tables(con):
        out[table] = [tuple(row) for row in con.execute(f"SELECT * FROM {table}")]
    return out


def test_get_endpoints_write_nothing_on_a_v7_database(tmp_path: Path, monkeypatch):
    """**`GET` は 1 バイトも書かない**（家風。設計 §0.13）。

    P2-0 は口を足さないので、既存の GET が v7 の DB でも書かないことを確かめる
    （**ファイルの中身と全表の中身**を前後で比べる。P8-4 の監査 F(e) と同じ物差し）。
    ついでに **`/api/folders` は 404**（P2-1 で作る口。この段では作らない）。
    """
    from image_reviewer.app import create_app

    data = tmp_path / "data"
    backups = tmp_path / "backups"
    store = Store(data)
    try:
        asset_id = _register(store, _make_png(data / "a.png"))
    finally:
        store.close()
    monkeypatch.setenv("IMAGE_REVIEWER_DATA", str(data))
    monkeypatch.setenv("IMAGE_REVIEWER_BACKUP_DIR", str(backups))
    app = create_app()
    app.state.backup.interval = 3600.0          # 周期が来ないようにする
    with TestClient(app, base_url="http://127.0.0.1") as client:
        # 起動の直後に日次バックアップが 1 回走る（`settings` に時刻を書く）。**先に書かせてから**測る
        assert client.post("/api/backup", headers=HUMAN, json={}).status_code < 500
        before_files = _files(data)
        with app.state.store.locked() as con:
            before_rows = _rows_digest(con)
        for path in ("/api/health", "/api/health/db", "/api/stats", "/api/assets",
                     f"/api/assets/{asset_id}", f"/api/assets/{asset_id}/file",
                     f"/api/assets/{asset_id}/metadata", f"/api/assets/{asset_id}/tags",
                     f"/api/assets/{asset_id}/annotations", "/api/groups", "/api/tags",
                     "/api/jobs", "/api/backup", "/api/settings", "/api/roots",
                     "/api/pending-deletes", "/api/trash", "/api/deletions",
                     "/api/duplicates/near", "/api/duplicates/exact",
                     "/api/duplicates/exclusions", "/api/locations/missing",
                     "/api/review-requests", "/api/reviews", "/api/reason-codes",
                     "/api/review.json"):
            resp = client.get(path, headers=HUMAN)
            assert resp.status_code < 500, f"{path}: {resp.status_code} {resp.text[:200]}"
        # v7 の口（P2-1）はまだ無い
        assert client.get("/api/folders", headers=HUMAN).status_code == 404
        with app.state.store.locked() as con:
            assert _rows_digest(con) == before_rows, "GET が行の中身を変えた"
        assert _files(data) == before_files, "GET がファイルの中身を変えた"
