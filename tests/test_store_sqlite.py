"""SQLite のストア（P5-0）のテスト。

設計: docs/p5-design.md §0.1（P5-0）・§0.8（C11）、docs/design.md §5.1・§5.4・§13

`tests/test_prototype.py` が JSON ストアで確かめていたことを SQLite で確かめ直し、
**別プロセスの走査が判断を消さない**（点検 B5。P5-0 の目的そのもの）を固定する。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from PIL import Image

from image_reviewer import db
from image_reviewer.cli import main as cli_main
from image_reviewer.scan import scan
from image_reviewer.store import Store, normalize_path


# ---- 道具 ----

def make_png(path: Path, color=(200, 120, 90)) -> Path:
    """中身の違う PNG を作る（合成で回す。実データに依存しない）。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (16, 16), tuple(color)).save(path)
    return path


def register(store: Store, sha: str, path, **kw):
    """`store.register()` の既定を埋める（テストで見たい引数だけ書く）。"""
    args = {"size": 100, "mtime_ns": 1, "width": 16, "height": 16, "fmt": "png",
            "meta": None, "note": None}
    args.update(kw)
    return store.register(sha256=sha, path=str(path), **args)


def find(store: Store, sha: str) -> dict:
    return next(a for a in store.assets() if a["sha256"] == sha)


# ---- 1. 登録の形（ULID と内容の分離）----

def test_register_creates_ulid_id_with_separate_sha256(tmp_path: Path):
    store = Store(tmp_path / "data")
    try:
        sha = "a" * 64
        p = tmp_path / "root" / "a.png"
        asset_id, created = register(store, sha, p, meta={"model": "m"})
        assert created is True
        assert asset_id != sha and len(asset_id) == 26, "id が ULID になっていない（点検 I17）"
        assert set(asset_id) <= set(db._B32)

        asset = store.asset(asset_id)
        assert asset["id"] == asset_id and asset["sha256"] == sha
        assert asset["meta"] == {"model": "m"}
        assert asset["locations"][0]["path"] == str(p)

        # 同じ内容・同じパス・同じ大きさ・同じ mtime なら、同じ id を返して増やさない
        again, created_again = register(store, sha, p, meta={"model": "m"})
        assert (again, created_again) == (asset_id, False)
        assert len(store.assets()) == 1
        assert store.stats()["locations"] == 1
    finally:
        store.close()


def test_same_content_at_two_paths_is_one_asset_with_two_locations(tmp_path: Path):
    """同一性は内容（sha256）。場所は従属（design.md §5.1）。"""
    store = Store(tmp_path / "data")
    try:
        sha = "b" * 64
        first = tmp_path / "root" / "one.png"
        second = tmp_path / "root" / "sub" / "two.png"
        a1, c1 = register(store, sha, first)
        a2, c2 = register(store, sha, second, size=101, mtime_ns=2)

        assert (a1, c1) == (a2, True) and c2 is False
        assert len(store.assets()) == 1
        asset = store.asset(a1)
        assert len(asset["locations"]) == 2
        # 代表は最初に見つけた場所のまま（design.md §5.1 の is_primary）
        assert [l["is_primary"] for l in asset["locations"]] == [True, False]
        # 見つけた順の大きさが場所ごとに残る
        assert sorted(l["size"] for l in asset["locations"]) == [100, 101]
    finally:
        store.close()


# ---- 2. パスの中身が入れ替わったとき ----

def test_content_change_makes_new_asset_and_history_row(tmp_path: Path):
    """`test_path_content_change_creates_history_row` を SQLite で確かめ直す。"""
    root = tmp_path / "root"
    p = make_png(root / "same.png", (200, 0, 0))
    with Store(tmp_path / "data") as store:
        scan(store, [str(root)])
        old_id = store.assets()[0]["id"]
        old_sha = store.assets()[0]["sha256"]

        make_png(p, (0, 0, 200))                     # 同じパスの中身を入れ替える
        stats = scan(store, [str(root)])
        assert stats["changed"] == 1
        # 走査の数え方は「入れ替わり」を created より先に見る（プロトタイプと同じ）
        assert stats["created"] == 0 and stats["known"] == 0
        assert len(store.assets()) == 2

        history = store.location_history()
        assert len(history) == 1
        assert history[0]["asset_id"] == old_id, "履歴が古い枚を指していない"
        assert history[0]["path"] == str(p)
        assert history[0]["replaced_at"]

        # 古い枚は消さない。生きた場所が 1 つも無くなるだけ（design.md §5.1）
        old = store.asset(old_id)
        assert old is not None and old["sha256"] == old_sha
        assert old["locations"] == []
        # 同じパスの行は新しい内容だけを指す（UNIQUE(path) を守る）
        loc = store.location_of(p)
        assert loc["asset_id"] != old_id
        assert loc["sha256"] == find(store, loc["sha256"])["sha256"]
        assert store.stats()["assets"] == 2
        # 中身が入れ替わっても増えるのは 1 枚の内容だけ
        assert len({a["sha256"] for a in store.assets()}) == 2


# ---- 3. 参照切れは走査した根の下だけ ----

def test_mark_missing_only_touches_scanned_roots(tmp_path: Path):
    """`test_scan_only_marks_missing_inside_scanned_roots` を SQLite で確かめ直す。"""
    root_a, root_b = tmp_path / "a", tmp_path / "b"
    make_png(root_a / "x.png")
    make_png(root_b / "y.png", (10, 200, 10))
    with Store(tmp_path / "data") as store:
        scan(store, [str(root_a)])
        scan(store, [str(root_b)])
        assert len(store.assets()) == 2
        assert store.stats()["missing"] == 0, "b の走査で a の画像が参照切れにされた"

        # a を「1 枚も見なかった」として走査しても、b の画像には触らない
        assert store.mark_missing(set(), [str(root_a)]) == 1
        assert store.stats()["missing"] == 1
        assert store.location_of(root_b / "y.png")["missing_at"] is None
        # 大文字で指定しても同じ根（点検 I1）
        assert store.mark_missing(set(), [str(root_b).upper()]) == 1
        assert store.stats()["missing"] == 2
        # 既に参照切れの行は二度数えない
        assert store.mark_missing(set(), [str(root_a), str(root_b)]) == 0


# ---- 4. 数え方 ----

def test_stats_keys_and_by_model_come_from_meta(tmp_path: Path):
    store = Store(tmp_path / "data")
    try:
        register(store, "1" * 64, tmp_path / "a.png", meta={"model": "m1"})
        register(store, "2" * 64, tmp_path / "b.png", meta={"model": "m1"})
        register(store, "3" * 64, tmp_path / "c.png", meta={"model": "m2"})
        register(store, "4" * 64, tmp_path / "d.png", meta=None, note="prompt チャンクが無い")
        got = store.stats()
        assert set(got) == {"assets", "locations", "with_provenance", "without_provenance",
                            "by_model", "missing"}
        assert got["assets"] == 4 and got["locations"] == 4
        assert got["with_provenance"] == 3
        assert got["without_provenance"] == 1
        assert got["by_model"] == {"m1": 2, "m2": 1}, "by_model が meta から作られていない"
        assert got["missing"] == 0
        # 来歴が無い枚でも、注記は残る（JSON 版の meta_note と同じ）
        assert find(store, "4" * 64)["meta"] is None
        assert find(store, "4" * 64)["meta_note"] == "prompt チャンクが無い"
    finally:
        store.close()


# ---- 5. 来歴は写し。書き戻しが要る（capture.py が依存する）----

def test_meta_is_a_copy_and_set_meta_writes_it_back(tmp_path: Path):
    """JSON 版は同じ dict を握っていた。SQLite 版は写しなので `set_meta()` が要る（点検 I5）。"""
    store = Store(tmp_path / "data")
    try:
        asset_id, _ = register(store, "5" * 64, tmp_path / "a.png", meta={"model": "m"})
        got = store.asset(asset_id)
        got["meta"]["en_text"] = "捕獲した英訳"          # 写しを書き換えても
        assert store.asset(asset_id)["meta"].get("en_text") is None, "写しのはずが保存された"

        store.set_meta(asset_id, got["meta"])
        assert store.asset(asset_id)["meta"]["en_text"] == "捕獲した英訳"
        assert store.asset(asset_id)["meta"]["model"] == "m", "書き戻しで他の値を落とした"
        # 走査で上書きされない（PNG から取り直せない値を守る。点検 I5）
        register(store, "5" * 64, tmp_path / "a.png", meta={"model": "別の値"})
        assert store.asset(asset_id)["meta"]["en_text"] == "捕獲した英訳"
    finally:
        store.close()


# ---- 6. 現在値の書き手は 1 つ ----

def test_set_review_state_is_the_single_writer(tmp_path: Path):
    store = Store(tmp_path / "data")
    try:
        asset_id, _ = register(store, "6" * 64, tmp_path / "a.png", meta={"model": "m"})
        with pytest.raises(ValueError):
            store.set_review_state(asset_id, "maybe")     # 語彙は 3 つだけ

        store.set_review_state(asset_id, "kept", actor="human", at="2026-10-15T00:00:00Z")
        got = store.asset(asset_id)
        assert got["review_state"] == "kept"
        assert got["reviewed_at"] == "2026-10-15T00:00:00Z"
        assert got["reviewed_by"] == "human"

        # 未判断に戻すと、理由と日時も戻る（p5-design.md §2.1 の写しの規則）
        store.set_review_state(asset_id, "unreviewed")
        got = store.asset(asset_id)
        assert got["review_state"] == "unreviewed"
        assert got["reviewed_at"] is None and got["reviewed_by"] is None
        assert got["review_reason_code_id"] is None
    finally:
        store.close()


# ---- 7. store.json からの取り込み ----

def _fixture_json(data_dir: Path) -> Path:
    """テストが書く JSON ストア（プロトタイプの形そのまま）。取り込み元は**読むだけ**。"""
    data_dir.mkdir(parents=True, exist_ok=True)
    root = data_dir.parent / "images"
    root.mkdir(parents=True, exist_ok=True)
    sha = {k: k * 64 for k in ("a", "b", "c")}
    paths = {k: str(root / f"{k}.png") for k in sha}

    def asset(key: str, meta: dict | None, note: str | None = None) -> dict:
        return {
            "id": sha[key], "sha256": sha[key], "size": 100, "width": 16, "height": 16,
            "format": "png", "kind": "generated" if meta else "photo",
            "kind_source": "auto:prompt" if meta else "auto:jpeg", "source": "scan",
            "source_url": None, "ref_tags": [], "review_state": "unreviewed",
            "review_reason_id": None, "reviewed_at": None, "deleted_at": None,
            "meta": meta, "meta_note": note,
            "first_seen_at": "2026-10-01T00:00:00Z", "last_seen_at": "2026-10-01T00:00:00Z",
            "locations": [{"key": normalize_path(paths[key]), "path": paths[key],
                           "kind": "reference", "size": 100, "mtime_ns": 1,
                           "is_primary": True, "missing_at": None,
                           "last_seen_at": "2026-10-01T00:00:00Z"}],
        }

    payload = {
        "version": 1,
        "assets": {
            sha["a"]: asset("a", {"model": "m1", "final_prompt": "p-a"}),
            sha["b"]: asset("b", {"model": "m1", "en_text": "JSON に在る英訳",
                                  "final_prompt": "p-b"}),
            sha["c"]: asset("c", None, "prompt チャンクが無い（生成条件が残っていない画像）"),
        },
        "locations": {normalize_path(paths[k]): {"asset_id": sha[k], "path": paths[k],
                                                "size": 100, "mtime_ns": 1} for k in sha},
        "location_history": [],
        "roots": [str(root)],
    }
    (data_dir / "store.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")

    # sidecar は DB と同じデータ置き場に置かれる（capture.write_sidecar）。
    # a には JSON が持っていない値だけを足す。b の値は**上書きしてはいけない**
    side = data_dir / "sidecar"
    side.mkdir(parents=True, exist_ok=True)
    for key, en in (("a", "側から来た英訳"), ("b", "こちらが勝ってはいけない")):
        (side / f"{sha[key]}.json").write_text(json.dumps({
            "schema": "urn:image-reviewer:sidecar", "abi": "0.1",
            "captured_at": "2026-10-02T00:00:00Z", "sha256": sha[key], "path": paths[key],
            "prompt_id": "pid-1", "captured_from_node": "11", "en_text": en,
            "final_prompt": f"final-{key}", "ja_text": "日本語",
            "concat_prefix": "prefix,", "llm": "llm.safetensors",
            "meta": {"en_text": en, "en_source": "comfyui_history",
                     "en_engine": "llm.safetensors", "final_prompt": f"final-{key}"},
        }, ensure_ascii=False), encoding="utf-8")
    return data_dir / "store.json"


def test_migrate_from_json_keeps_counts_merges_sidecar_and_is_idempotent(
        tmp_path: Path, monkeypatch, capsys):
    data = tmp_path / "data"
    src = _fixture_json(data)
    before = src.read_bytes()
    monkeypatch.setenv("IMAGE_REVIEWER_DATA", str(data))

    # ---- 1 回目 ----
    assert cli_main(["migrate-from-json", "--from", str(src)]) == 0
    out = capsys.readouterr().out
    assert "新規 3" in out and "画像 3 枚" in out, out
    assert "来歴あり 2" in out and "参照切れ 0" in out, out

    with Store(data) as store:
        got = store.stats()
        # JSON 側の数え方（3 枚 / 3 か所 / 来歴あり 2 / 来歴なし 1 / 参照切れ 0）と一致する
        assert (got["assets"], got["locations"], got["with_provenance"],
                got["without_provenance"], got["missing"]) == (3, 3, 2, 1, 0)
        assert got["by_model"] == {"m1": 2}
        assert store.roots() == [str(data.parent / "images")]

        a = find(store, "a" * 64)
        assert a["meta"]["en_text"] == "側から来た英訳", "sidecar の値を補っていない"
        assert a["meta"]["en_source"] == "comfyui_history"
        assert a["meta"]["final_prompt"] == "p-a", "JSON に在る値を sidecar で上書きした"
        assert a["meta"]["model"] == "m1"
        assert a["meta"]["prompt_id"] == "pid-1"

        b = find(store, "b" * 64)
        assert b["meta"]["en_text"] == "JSON に在る英訳", "JSON に在る値を上書きした"
        assert b["meta"]["final_prompt"] == "p-b"

        c = find(store, "c" * 64)
        assert c["meta"] is None and c["meta_note"] == "prompt チャンクが無い（生成条件が残っていない画像）"
        assert c["kind"] == "photo" and c["kind_source"] == "auto:jpeg"
        assert a["id"] != a["sha256"] and len(a["id"]) == 26, "取り込みで ULID にしていない"
        assert a["first_seen_at"] == "2026-10-01T00:00:00Z"

        # 内容で引ける（`sha256` は UNIQUE）
        assert store.con.execute(
            "SELECT count(*) AS n FROM asset WHERE sha256 = ?", ("a" * 64,)
        ).fetchone()["n"] == 1

    # ---- 2 回目: 何も増えない ----
    assert cli_main(["migrate-from-json", "--from", str(src)]) == 0
    out2 = capsys.readouterr().out
    assert "新規 0 / 更新 0 / そのまま 3 件" in out2, out2
    with Store(data) as store:
        got = store.stats()
        assert (got["assets"], got["locations"], got["with_provenance"]) == (3, 3, 2)
        assert len(store.assets()) == 3
        assert store.location_history() == []

    # 取り込み元は**書き換えない・消さない**（控えとして残す。点検 B5）
    assert src.read_bytes() == before
    assert (data / "sidecar" / f"{'a' * 64}.json").exists()


def test_migrate_from_json_reports_created_updated_skipped(tmp_path: Path):
    """戻り値の形（`{created, updated, skipped}`）を直接確かめる。"""
    from image_reviewer.cli import migrate_from_json

    data = tmp_path / "data"
    src = _fixture_json(data)
    with Store(data) as store:
        first = migrate_from_json(store, src)
        assert (first["created"], first["updated"], first["skipped"]) == (3, 2, 0)
        assert first["sidecars"] == 2
        second = migrate_from_json(store, src)
        assert (second["created"], second["updated"], second["skipped"]) == (0, 0, 3)


def _fixture_json_with_a_kept_asset(data_dir: Path) -> Path:
    """`review_state='kept'` を 1 枚だけ持つ JSON（監査 B1 の再現用）。"""
    data_dir.mkdir(parents=True, exist_ok=True)
    root = data_dir.parent / "images"
    root.mkdir(parents=True, exist_ok=True)
    sha = "a" * 64
    path = str(root / "a.png")
    payload = {
        "version": 1,
        "assets": {sha: {
            "id": sha, "sha256": sha, "size": 100, "width": 16, "height": 16, "format": "png",
            "kind": "generated", "kind_source": "auto:prompt", "source": "scan",
            "review_state": "kept", "review_reason_id": "rc.keep.favorite",
            "reviewed_at": "2026-10-01T00:00:00Z", "reviewed_by": "human",
            "meta": {"model": "m"}, "meta_note": None,
            "first_seen_at": "2026-10-01T00:00:00Z", "last_seen_at": "2026-10-01T00:00:00Z",
            "locations": [{"key": normalize_path(path), "path": path, "kind": "reference",
                           "size": 100, "mtime_ns": 1, "is_primary": True, "missing_at": None,
                           "last_seen_at": "2026-10-01T00:00:00Z"}],
        }},
        "locations": {}, "location_history": [], "roots": [str(root)],
    }
    (data_dir / "store.json").write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return data_dir / "store.json"


def test_migrate_from_json_writes_a_ledger_row_so_reconcile_keeps_the_state(tmp_path: Path):
    """監査 B1: 取り込んだ `kept` が、次の `ReviewService()` の `reconcile()` で消えない。

    台帳に行が無い写しは「台帳が正」で組み直されて `unreviewed` に戻る（INFO ログ 1 行だけ）。
    取り込むときに `decision` を 1 行書くことで、写しの由来が台帳で説明できる。
    """
    from image_reviewer.cli import migrate_from_json
    from image_reviewer.review import ReviewService

    data = tmp_path / "data"
    src = _fixture_json_with_a_kept_asset(data)
    with Store(data) as store:
        assert migrate_from_json(store, src)["decisions"] == 1
        asset_id = find(store, "a" * 64)["id"]
        assert store.asset(asset_id)["review_state"] == "kept"
        rows = store.con.execute(
            "SELECT * FROM decision WHERE subject_type='asset' AND subject_id=?",
            (asset_id,)).fetchall()
        assert len(rows) == 1, "取り込んだ判断が台帳に 1 行も無い（監査 B1）"
        assert rows[0]["verdict"] == "keep" and rows[0]["actor"] == "human"
        assert rows[0]["reason_code_id"] == "rc.keep.favorite"
        assert rows[0]["created_at"] == "2026-10-01T00:00:00Z"
        assert rows[0]["note"] == "store.json から取り込み"
        # 二度目の取り込みでは増やさない
        assert migrate_from_json(store, src)["decisions"] == 0
        assert store.con.execute("SELECT count(*) AS n FROM decision").fetchone()["n"] == 1

    # 次の起動（`ReviewService` が台帳から写しを組み直す）でも消えない
    with Store(data) as store:
        review = ReviewService(store, reconcile_on_start=True)
        assert review.reconcile() == 0, "取り込んだ写しが台帳と食い違っている（監査 B1）"
        kept = find(store, "a" * 64)
        assert kept["review_state"] == "kept", "取り込んだ判断が消えた（監査 B1）"
        assert kept["review_reason_code_id"] == "rc.keep.favorite"
        assert kept["reviewed_by"] == "human"


# ---- 8. 点検 B5 の核心（別プロセスの走査が判断を消さない）----

def test_scan_through_another_store_keeps_decisions_and_review_state(tmp_path: Path):
    """`cli scan` は別プロセスで `Store` を開く。判断が消えないこと（点検 B5-(a)）。

    JSON 版は `save()` が `store.json` 全体を `os.replace` していたので、
    サーバが付けた判断が走査で全部消えた。行を書く SQLite では消えない。
    """
    root = tmp_path / "root"
    make_png(root / "a.png")
    data = tmp_path / "data"
    server = Store(data)
    other = Store(data)
    try:
        scan(server, [str(root)])
        asset_id = server.assets()[0]["id"]
        server.set_review_state(asset_id, "kept")
        server.con.execute(
            "INSERT INTO decision(id, seq, subject_type, subject_id, verdict, actor, created_at)"
            " VALUES (?,?,?,?,?,?,?)",
            (db.ulid(), 1, "asset", asset_id, "keep", "human", db.now()),
        )
        server.save()

        # 別の接続（別プロセスで走る走査に相当）が、同じ根をもう一度走査する
        stats = scan(other, [str(root)])
        assert stats["created"] == 0 and stats["known"] == 1

        for name, store in (("サーバ", server), ("走査", other)):
            n = store.con.execute(
                "SELECT count(*) AS n FROM decision WHERE subject_id = ?", (asset_id,)
            ).fetchone()["n"]
            assert n == 1, f"{name}の接続から判断が見えない（点検 B5）"
        assert server.asset(asset_id)["review_state"] == "kept", "走査が判断を消した"
        assert other.asset(asset_id)["review_state"] == "kept"
    finally:
        other.close()
        server.close()


# ---- 9. 寿命（`with` と二度の `close()`）----

def test_store_works_as_context_manager_and_close_is_idempotent(tmp_path: Path):
    data = tmp_path / "data"
    with Store(data) as store:
        asset_id, _ = register(store, "7" * 64, tmp_path / "a.png")
    store.close()      # 2 回目（`with` を抜けた後に呼ぶ経路がある）
    store.close()

    again = Store(data)
    try:
        assert again.asset(asset_id) is not None, "閉じて開き直すと消えた"
        assert len(again.assets()) == 1
    finally:
        again.close()
