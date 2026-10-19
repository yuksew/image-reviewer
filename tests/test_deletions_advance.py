"""後から段 2 へ進める・実体が無い行を片付ける（P10）のテスト。

利用者の要望「一度カタログから削除したものをゴミ箱に移す方法はない？」への実装
（記録: `docs/deletions-advance.md`）。

**何を壊すと落ちるか**を各テストの docstring に書いてある（家風）。
**実データは触らない**（`tmp_path` の中だけで動かす。画像の複製も作らない）。
**時計は注入する**（`Clock` を 1 つだけ。`time.monotonic()` を直接呼ばない）。
"""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from image_reviewer import deletions
from image_reviewer.deletions import AGENT_MAX_BATCH, TRASH_DIR, DeletionService
from image_reviewer.review import ReviewError
from image_reviewer.store import Store, normalize_path

HUMAN = {"X-Image-Reviewer-Actor": "human"}
AGENT = {"X-Image-Reviewer-Actor": "agent"}


# ---- 道具（`tests/test_deletions.py` と同じ形。ファイルをまたいで import しない）----


class FakeClock:
    """テスト用の時計（**壁と単調の両方を 1 つの口から進める**）。"""

    def __init__(self, *, wall: float = 1_700_000_000.0, mono: float = 1000.0):
        self._wall = wall
        self._mono = mono

    def now(self) -> str:
        return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(self._wall))

    def monotonic(self) -> float:
        return self._mono

    def advance(self, *, sec: float = 0.0, mono: float = 0.0) -> None:
        self._wall += sec
        self._mono += mono


def make_png(path: Path, *, seed: int = 0, size: tuple[int, int] = (16, 16)) -> Path:
    """合成の PNG（`seed` で中身を変える）。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    w, h = size
    im = Image.new("RGB", (w, h))
    px = im.load()
    for y in range(h):
        for x in range(w):
            px[x, y] = ((x * 7 + y * 3 + seed * 29) % 256, (x * 5 + seed * 11) % 256,
                        (y * 9 + seed * 17) % 256)
    im.save(path)
    return path


def add_asset(store: Store, path: Path, *, name: str | None = None) -> str:
    """実体のあるファイルを 1 枚登録する。"""
    key = name or path.name
    digest = hashlib.sha256(f"{key}:{path}".encode("utf-8")).hexdigest()
    asset_id, _ = store.register(
        sha256=digest, path=str(path), size=path.stat().st_size,
        mtime_ns=path.stat().st_mtime_ns, width=16, height=16, fmt="png",
        meta=None, note=None)
    return asset_id


def add_missing_asset(store: Store, path: Path, *, size: int = 1234, mtime_ns: int = 5678,
                      name: str | None = None) -> str:
    """**実体の無い行**を 1 枚登録する（利用者がエクスプローラーで消した後と同じ形）。

    段 1 はファイルを見ないので、これで「カタログから外したが実体が無い」行が作れる
    （実データの 194 行のうち 187 行がこの形）。
    """
    key = name or path.name
    digest = hashlib.sha256(f"missing:{key}:{path}".encode("utf-8")).hexdigest()
    asset_id, _ = store.register(
        sha256=digest, path=str(path), size=size, mtime_ns=mtime_ns, width=16, height=16,
        fmt="png", meta=None, note=None)
    return asset_id


def where(store: Store, asset_id: str) -> dict:
    row = store.con.execute("SELECT * FROM asset_location WHERE asset_id = ?",
                            (asset_id,)).fetchone()
    return dict(row)


def files_under(root: Path) -> tuple:
    """その下のファイルの `(場所, 大きさ, mtime)`（**動いた・消えた・変わった**を見る）。

    **DB のファイル（`db.sqlite3` と `-wal` / `-shm`）は外す**——台帳を書く口なので、
    比較したいのは**画像などの実体**が動いていないこと（`store.data_dir` を丸ごと比べると
    必ず WAL の大きさが変わって落ちる）。
    """
    out = []
    for p in root.rglob("*"):
        if not p.is_file() or p.name.startswith("db.sqlite3"):
            continue
        out.append((str(p.relative_to(root)), p.stat().st_size, p.stat().st_mtime_ns))
    return tuple(sorted(out))


@ pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def store(tmp_path: Path):
    got = Store(tmp_path / "data")
    try:
        yield got
    finally:
        got.close()


@pytest.fixture
def svc(store: Store, clock: FakeClock):
    return DeletionService(store, clock=clock)


@pytest.fixture
def library(tmp_path: Path, store: Store):
    """**複製の中の置き場**（実データは触らない）。"""
    got = tmp_path / "library"
    got.mkdir(parents=True, exist_ok=True)
    store.set_roots([str(got)])
    return got


@pytest.fixture
def client(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("IMAGE_REVIEWER_DATA", str(tmp_path / "app"))
    from image_reviewer.app import create_app
    app = create_app()
    app.state.deletions.interval = 3600.0            # タイマーで残り時間が減らないように
    with TestClient(app, base_url="http://127.0.0.1") as got:
        yield got


def stage1(svc: DeletionService, store: Store, path: Path, *, actor: str = "human",
           seed: int = 1, missing: bool = False) -> dict:
    """段 1 の行を 1 つ作る（既定は実体つき）。"""
    if missing:
        asset_id = add_missing_asset(store, path)
    else:
        asset_id = add_asset(store, path)
    return svc.delete(asset_id=asset_id, path=str(path), stage=1, actor=actor)


def row_of(store: Store, deletion_id: str) -> dict:
    return dict(store.con.execute("SELECT * FROM deletion_log WHERE id = ?",
                                  (deletion_id,)).fetchone())


# ---- 段 1 → 段 2（後から進める）----


def test_advance_moves_the_file_into_the_trash_and_undo_brings_it_back(svc, store, library, clock):
    """壊すと落ちる: 段 1 の行を段 2 へ進めたとき、**ファイルを移さない**・`to_path` を書かない・
    **「戻す」で戻らない**（利用者の要望そのもの。段 1 が行き止まりだった）。"""
    path = make_png(library / "post.png", seed=11)
    got = stage1(svc, store, path)
    before = (path.stat().st_size, path.stat().st_mtime_ns)
    out = svc.advance(got["deletion_id"], stage=2, actor="human")
    assert out["stage"] == 2 and out["to_path"], out
    moved = Path(out["to_path"])
    assert moved.exists() and not path.exists(), "ファイルを移していない"
    assert (moved.stat().st_size, moved.stat().st_mtime_ns) == before, "中身が変わった"
    assert out["to_path"].startswith(str(store.data_dir / TRASH_DIR)), out["to_path"]
    row = row_of(store, got["deletion_id"])
    assert int(row["stage"]) == 2 and row["to_path"] == out["to_path"]
    assert row["hold_path"] is None and row["purge_at"] is None
    assert where(store, row["asset_id"])["missing_at"], "参照切れの印が立っていない"
    # **「戻す」がそのまま効く**（段 2 の既存の道。`trash_restore` は人だけ）
    back = svc.trash_restore(got["deletion_id"], actor="human")
    assert back["restored"] is True and back["stage"] == 2
    assert path.exists() and not moved.exists(), "戻っていない"
    assert (path.stat().st_size, path.stat().st_mtime_ns) == before, "戻した中身が変わった"
    assert where(store, row["asset_id"])["missing_at"] is None, "参照切れの印が残っている"


def test_advance_keeps_the_catalog_hidden(svc, store, library):
    """壊すと落ちる: 段 2 へ進めた拍子に**カタログへ戻す**（`asset.deleted_at` を消す）。"""
    path = make_png(library / "hidden.png", seed=12)
    got = stage1(svc, store, path)
    asset_id = row_of(store, got["deletion_id"])["asset_id"]
    assert store.con.execute("SELECT deleted_at FROM asset WHERE id = ?",
                             (asset_id,)).fetchone()["deleted_at"], "段 1 で隠れていない"
    svc.advance(got["deletion_id"], stage=2, actor="human")
    assert store.con.execute("SELECT deleted_at FROM asset WHERE id = ?",
                            (asset_id,)).fetchone()["deleted_at"], "カタログに戻っている"


def test_advance_works_when_the_ledger_asset_id_is_stale(svc, store, library):
    """壊すと落ちる: **走査が同じ場所を別の `asset` として登録し直した後**、台帳の古い
    `asset_id` を要求して、**実体が在るのに `not_registered` で永久に進めない**。

    実データの 194 行のうち **6 行がこの形**（実体が在る 7 行のうち 6 行。中身が入れ替わって
    走査が登録し直した）。`delete()` の `_target(asset_id, path)` をそのまま使うと起きる。
    """
    path = make_png(library / "stale.png", seed=70)
    got = stage1(svc, store, path)
    old_asset = row_of(store, got["deletion_id"])["asset_id"]
    make_png(path, seed=71)                        # 中身が入れ替わった
    new_asset = add_asset(store, path, name="stale-2.png")   # **別の sha256** で登録し直す
    assert new_asset != old_asset, "同じ asset のままでは、この形を作れない"
    assert store.con.execute("SELECT count(*) AS n FROM asset_location WHERE asset_id = ?",
                             (old_asset,)).fetchone()["n"] == 0, "古い場所が残っている"
    out = svc.advance(got["deletion_id"], stage=2, actor="human")
    assert out["stage"] == 2 and out["asset_id"] == new_asset, out
    assert not path.exists() and Path(out["to_path"]).exists()
    assert row_of(store, got["deletion_id"])["asset_id"] == old_asset, \
        "台帳の「消した枚」を書き換えた（1 行 = 1 回の削除の記録）"
    assert where(store, new_asset)["missing_at"], "いま登録されている場所に印が立っていない"
    # **戻すと、いまの登録が元に戻る**（古い枚の印はそのまま）
    svc.trash_restore(got["deletion_id"], actor="human")
    assert path.exists() and where(store, new_asset)["missing_at"] is None


def test_advance_refuses_when_the_file_is_gone(svc, store, library):
    """壊すと落ちる: 実体が無いのに移したことにする（**409 `missing_file`**。実データの 187 行）。

    文には**次の一手（「ファイルが無いので片付ける」）**が要る（利用者が何を押せばよいか分かる）。
    """
    path = library / "gone.png"
    got = stage1(svc, store, path, missing=True)
    assert not path.exists()
    with pytest.raises(ReviewError) as exc:
        svc.advance(got["deletion_id"], stage=2, actor="human")
    assert exc.value.status == 409 and exc.value.code == "missing_file", exc.value
    assert "ファイルが無いので片付ける" in exc.value.detail, exc.value.detail
    row = row_of(store, got["deletion_id"])
    assert int(row["stage"]) == 1 and row["to_path"] is None, "断ったのに段が上がっている"
    assert not (store.data_dir / TRASH_DIR).exists() or not any(
        (store.data_dir / TRASH_DIR).rglob("*")), "断ったのにゴミ箱に何か作った"


def test_advance_refuses_when_the_file_changed(svc, store, library):
    """壊すと落ちる: **別のファイルを移す**（登録した `(size, mtime_ns)` を見ない）。"""
    path = make_png(library / "changed.png", seed=13)
    got = stage1(svc, store, path)
    make_png(path, seed=99)                       # 中身が入れ替わった（別のファイル）
    with pytest.raises(ReviewError) as exc:
        svc.advance(got["deletion_id"], stage=2, actor="human")
    assert exc.value.status == 409 and exc.value.code == "changed", exc.value
    assert path.exists(), "断ったのにファイルが消えた"
    assert int(row_of(store, got["deletion_id"])["stage"]) == 1


def test_advance_refuses_rows_that_are_already_past_stage_1(svc, store, library):
    """壊すと落ちる: **二重に移す**（既に段 2 の行をもう一度段 2 へ）・段 3 へ直行する。"""
    path = make_png(library / "twice.png", seed=14)
    asset_id = add_asset(store, path)
    got = svc.delete(asset_id=asset_id, path=str(path), stage=2, actor="human")
    with pytest.raises(ReviewError) as exc:
        svc.advance(got["deletion_id"], stage=2, actor="human")
    assert exc.value.status == 409 and exc.value.code == "already_stage2", exc.value
    row = row_of(store, got["deletion_id"])
    assert row["to_path"] == got["to_path"], "二重に移した（`to_path` が変わった）"
    # **段 1 へは戻せない・段 3 へは直行できない**（語彙は 422）
    one = stage1(svc, store, make_png(library / "s1.png", seed=15))
    for bad in (1, 3, None, True, 2.5):
        with pytest.raises(ReviewError) as exc:
            svc.advance(one["deletion_id"], stage=bad, actor="human")
        assert exc.value.status == 422 and exc.value.code == "bad_stage", (bad, exc.value)
    assert int(row_of(store, one["deletion_id"])["stage"]) == 1, "422 なのに動いた"


def test_advance_never_overwrites_an_existing_file(svc, store, library, monkeypatch):
    """壊すと落ちる: ゴミ箱の同名ファイルを**上書きする**（`os.replace` にすると起きる）。

    名前は `free_name()` が避けるので、**競合を直に作る**（移動先を先に埋めてから進める）。
    断ったときは**段 1 に戻す**（`to_path` を残さない＝帰り道が壊れない）。
    """
    path = make_png(library / "same.png", seed=16)
    got = stage1(svc, store, path)
    holder: dict = {}

    def occupied_free_name(directory, name):
        occupied = Path(directory) / name
        occupied.write_bytes(b"someone else")
        holder["path"] = occupied
        holder["before"] = (occupied.stat().st_size, occupied.stat().st_mtime_ns)
        return occupied

    monkeypatch.setattr(deletions, "free_name", occupied_free_name)
    with pytest.raises(ReviewError) as exc:
        svc.advance(got["deletion_id"], stage=2, actor="human")
    assert exc.value.status == 409 and exc.value.code == "target_exists", exc.value
    now = (holder["path"].stat().st_size, holder["path"].stat().st_mtime_ns)
    assert now == holder["before"], "既存のファイルを上書きした"
    assert path.exists(), "断ったのに元のファイルが消えた"
    row = row_of(store, got["deletion_id"])
    assert int(row["stage"]) == 1 and row["to_path"] is None and row["from_path"] is None, \
        "断ったのに段が上がったまま（帰り道が壊れる）"


def test_advance_is_human_only(svc, store, library):
    """壊すと落ちる: **エージェントがファイルを動かす**（段を進めるのは人の操作。403）。"""
    got = stage1(svc, store, make_png(library / "human.png", seed=17), actor="agent")
    with pytest.raises(ReviewError) as exc:
        svc.advance(got["deletion_id"], stage=2, actor="agent")
    assert exc.value.status == 403 and exc.value.code == "human_only", exc.value
    assert int(row_of(store, got["deletion_id"])["stage"]) == 1


def test_advance_records_the_actor_without_rewriting_who_deleted(svc, store, library):
    """壊すと落ちる: **誰が進めたかを残さない**・**消した人を書き換える**（1 行 = 1 回の削除の記録）。"""
    got = stage1(svc, store, make_png(library / "actor.png", seed=18), actor="agent")
    svc.advance(got["deletion_id"], stage=2, actor="human")
    assert row_of(store, got["deletion_id"])["actor"] == "agent", "消した人が書き換わった"
    rows = store.con.execute(
        "SELECT * FROM delete_request WHERE actor = 'human' AND result_json IS NOT NULL"
        " ORDER BY at DESC").fetchall()
    hit = [r for r in rows if "advance" in str(r["payload_json"] or "")]
    assert hit, "進めた人の記録が無い"
    assert got["deletion_id"] in str(hit[0]["result_json"]), hit[0]["result_json"]


# ---- 「実体が無いので片付ける」----


def test_close_refuses_while_the_file_is_still_there(svc, store, library):
    """壊すと落ちる: **生きているファイルの行を片付ける**（409 `file_found`。ファイルは無傷）。"""
    path = make_png(library / "alive.png", seed=21)
    got = stage1(svc, store, path)
    before = (path.stat().st_size, path.stat().st_mtime_ns)
    with pytest.raises(ReviewError) as exc:
        svc.close(got["deletion_id"], reason="missing", actor="human")
    assert exc.value.status == 409 and exc.value.code == "file_found", exc.value
    assert normalize_path(path) in [normalize_path(p) for p in exc.value.details["found"]], \
        exc.value.details
    assert str(path) in exc.value.detail, "どのファイルが残っているかを文に出していない"
    assert (path.stat().st_size, path.stat().st_mtime_ns) == before, "断ったのにファイルを触った"
    assert row_of(store, got["deletion_id"])["closed_at"] is None, "断ったのに閉じた"


def test_close_refuses_a_file_that_is_in_the_app_trash(svc, store, library):
    """壊すと落ちる: **ゴミ箱に実体があるのに片付ける**（見るのは登録の場所だけ、にすると起きる）。"""
    path = make_png(library / "trapped.png", seed=22)
    asset_id = add_asset(store, path)
    got = svc.delete(asset_id=asset_id, path=str(path), stage=2, actor="human")
    assert Path(got["to_path"]).exists()
    with pytest.raises(ReviewError) as exc:
        svc.close(got["deletion_id"], reason="missing", actor="human")
    assert exc.value.status == 409 and exc.value.code == "file_found", exc.value
    assert Path(got["to_path"]).exists(), "断ったのにゴミ箱のファイルが消えた"


def test_close_ends_the_row_and_touches_nothing_else(svc, store, library, tmp_path):
    """壊すと落ちる: 片付けで**ファイルを消す・動かす**・`asset.deleted_at` を戻す・
    `asset_location` を消す（利用者の要望は「行を終わりにする」だけ）。"""
    path = make_png(library / "vanish.png", seed=23)
    got = stage1(svc, store, path)
    asset_id = row_of(store, got["deletion_id"])["asset_id"]
    # **利用者がエクスプローラーで Windows のごみ箱へ移した形**（このツールは触らない）
    elsewhere = tmp_path / "windows-recycle"
    elsewhere.mkdir()
    parked = elsewhere / path.name
    path.rename(parked)
    loc_before = where(store, asset_id)
    hidden_before = store.con.execute("SELECT deleted_at FROM asset WHERE id = ?",
                                      (asset_id,)).fetchone()["deleted_at"]
    files_before = (files_under(store.data_dir), files_under(tmp_path))
    out = svc.close(got["deletion_id"], reason="missing", actor="human")
    assert out["closed"] is True and out["close_reason"] == "missing" and out["closed_at"]
    assert out["files_touched"] == 0, out
    row = row_of(store, got["deletion_id"])
    assert row["closed_at"] == out["closed_at"] and row["close_reason"] == "missing"
    assert row["restored_at"] is None and int(row["stage"]) == 1, "段や戻すの印を触った"
    assert store.con.execute("SELECT deleted_at FROM asset WHERE id = ?",
                            (asset_id,)).fetchone()["deleted_at"] == hidden_before, \
        "カタログに戻した（隠れたままのはず）"
    assert where(store, asset_id) == loc_before, "登録（`asset_location`）を触った"
    assert (files_under(store.data_dir), files_under(tmp_path)) == files_before, \
        "ファイルを 1 つでも動かした・消した"


def test_close_twice_records_once(svc, store, library, tmp_path):
    """壊すと落ちる: **二重に記録する**（2 度目は 200 で `replayed: true`。時刻も変わらない）。"""
    path = library / "twice-close.png"
    got = stage1(svc, store, path, missing=True)
    first = svc.close(got["deletion_id"], reason="missing", actor="human")
    second = svc.close(got["deletion_id"], reason="missing", actor="human")
    assert first["replayed"] is False and second["replayed"] is True, second
    assert second["closed_at"] == first["closed_at"], "閉じた時刻を書き直した"
    row = row_of(store, got["deletion_id"])
    assert row["closed_at"] == first["closed_at"]


def test_close_is_human_only_and_checks_the_reason(svc, store, library):
    """壊すと落ちる: エージェントが片付ける（403）・語彙の外の理由が `CHECK` に当たる（500）。"""
    got = stage1(svc, store, library / "reason.png", missing=True)
    with pytest.raises(ReviewError) as exc:
        svc.close(got["deletion_id"], reason="missing", actor="agent")
    assert exc.value.status == 403 and exc.value.code == "human_only", exc.value
    for bad in ("whatever", None, "", 1):
        with pytest.raises(ReviewError) as exc:
            svc.close(got["deletion_id"], reason=bad, actor="human")
        assert exc.value.status == 422 and exc.value.code == "bad_reason", (bad, exc.value)
    assert row_of(store, got["deletion_id"])["closed_at"] is None, "422 なのに閉じた"


def test_a_closed_row_leaves_the_pending_list_and_stays_in_the_ledger(svc, store, library):
    """壊すと落ちる: 片付けた行を**「最近の削除」に残す**（押しても必ず失敗する行が並ぶ）。
    台帳（`GET /api/deletions`）からは**消さない**（1 行 = 1 回の削除の記録）。"""
    got = stage1(svc, store, library / "leaves.png", missing=True)
    assert [i["id"] for i in svc.pending(actor="human")["items"]] == [got["deletion_id"]]
    svc.close(got["deletion_id"], reason="missing", actor="human")
    assert svc.pending(actor="human")["items"] == [], "片付けた行がまだ出ている"
    listed = svc.ledger(actor="human")["items"]
    assert [i["id"] for i in listed] == [got["deletion_id"]], "台帳から消えた"
    assert listed[0]["state"] == "closed", listed[0]["state"]
    assert listed[0]["closeable"] is False and listed[0]["undoable"] is False, listed[0]


def test_a_closed_row_cannot_be_restored(svc, store, library):
    """壊すと落ちる: 片付けた行を戻す（**段 1 はファイルを見ない**ので、実体の無い枚が
    カタログに戻り「参照切れ」が並ぶ）。"""
    path = library / "no-back.png"
    got = stage1(svc, store, path, missing=True)
    svc.close(got["deletion_id"], reason="missing", actor="human")
    with pytest.raises(ReviewError) as exc:
        svc.undo(got["deletion_id"], actor="human")
    assert exc.value.status == 409 and exc.value.code == "already_closed", exc.value
    assert row_of(store, got["deletion_id"])["restored_at"] is None


def test_close_takes_the_row_out_of_the_trash_too(svc, store, library, tmp_path):
    """壊すと落ちる: ゴミ箱の欄に**片付けた行を出し続ける**（「戻す」が必ず失敗する行が並ぶ）。"""
    path = make_png(library / "emptied.png", seed=24)
    asset_id = add_asset(store, path)
    got = svc.delete(asset_id=asset_id, path=str(path), stage=2, actor="human")
    assert svc.trash(actor="human")["count"] == 1
    # **利用者が `<data>/trash` の中身をエクスプローラーで消した形**
    parked = tmp_path / "windows-recycle"
    parked.mkdir()
    Path(got["to_path"]).rename(parked / Path(got["to_path"]).name)
    out = svc.close(got["deletion_id"], reason="missing", actor="human")
    assert out["stage"] == 2 and out["files_touched"] == 0
    assert svc.trash(actor="human")["count"] == 0, "片付けた行がゴミ箱に残っている"
    assert [i["id"] for i in svc.ledger(actor="human")["items"]] == [got["deletion_id"]]


# ---- まとめて（194 件を 1 回で）----


def test_close_many_closes_194_rows_in_one_call(svc, store, library):
    """壊すと落ちる: 実データの 194 行が**1 回で片付かない**（利用者の要望そのもの）。

    実体がまだ在る 1 件は**断って `skipped` に残す**（**数を黙って捨てない**）。
    """
    ids = []
    for n in range(194):
        ids.append(stage1(svc, store, library / f"gone-{n:03d}.png", missing=True)["deletion_id"])
    alive = stage1(svc, store, make_png(library / "alive-194.png", seed=25))["deletion_id"]
    out = svc.close_many(ids + [alive], reason="missing", actor="human")
    assert out["requested"] == 195 and out["count"] == 194, out["count"]
    assert out["skipped_count"] == 1 and out["skipped"][0]["deletion_id"] == alive
    assert out["skipped"][0]["reason"] == "file_found", out["skipped"][0]
    assert store.con.execute("SELECT count(*) AS n FROM deletion_log"
                             " WHERE closed_at IS NOT NULL").fetchone()["n"] == 194
    assert store.con.execute("SELECT count(*) AS n FROM asset"
                             " WHERE deleted_at IS NOT NULL").fetchone()["n"] == 195, \
        "カタログから戻した行がある（隠れたままのはず）"
    assert [i["id"] for i in svc.pending(actor="human")["items"]] == [alive], \
        "片付けた行が「最近の削除」に残っている"
    assert (library / "alive-194.png").exists(), "断った行のファイルが消えた"


def test_advance_many_moves_the_live_ones_and_keeps_the_rest(svc, store, library):
    """壊すと落ちる: まとめて進めたとき、**1 件の失敗で全部を止める**・**失敗を数から落とす**。"""
    live = [stage1(svc, store, make_png(library / f"live-{n}.png", seed=30 + n))["deletion_id"]
            for n in range(2)]
    gone = [stage1(svc, store, library / f"gone-{n}.png", missing=True)["deletion_id"]
            for n in range(3)]
    out = svc.advance_many(live + gone, stage=2, actor="human")
    assert out["requested"] == 5 and out["count"] == 2 and out["skipped_count"] == 3, out
    assert {s["reason"] for s in out["skipped"]} == {"missing_file"}, out["skipped"]
    assert out["count"] + out["skipped_count"] == out["requested"], "数を捨てている"
    for deletion_id in live:
        assert int(row_of(store, deletion_id)["stage"]) == 2
        assert Path(row_of(store, deletion_id)["to_path"]).exists()
    for deletion_id in gone:
        assert int(row_of(store, deletion_id)["stage"]) == 1
    assert not (library / "live-0.png").exists(), "移していない"


def test_many_does_not_silently_drop_failures(svc, store, library):
    """壊すと落ちる: **行の無い id を黙って捨てる**（`skipped` に理由つきで残す）。
    片付けの 2 度目は**成功に数える**（`replayed`。断りではない）。"""
    gone = stage1(svc, store, library / "dropped.png", missing=True)["deletion_id"]
    svc.close(gone, reason="missing", actor="human")
    out = svc.close_many(["no-such-row", gone], reason="missing", actor="human")
    assert out["requested"] == 2 and out["count"] == 1 and out["skipped_count"] == 1, out
    assert out["skipped"][0]["reason"] == "refused", out["skipped"][0]
    assert out["closed"][0]["replayed"] is True, out["closed"][0]


def test_many_over_the_limit_changes_nothing(svc, store, library):
    """壊すと落ちる: 上限を超えた要求で**一部だけ適用する**（422 `too_many` で 1 件も動かさない）。"""
    got = stage1(svc, store, make_png(library / "over.png", seed=40))
    ids = [got["deletion_id"]] + [f"x{n}" for n in range(AGENT_MAX_BATCH)]
    assert len(ids) == AGENT_MAX_BATCH + 1
    for call in (lambda: svc.advance_many(ids, stage=2, actor="human"),
                 lambda: svc.close_many(ids, reason="missing", actor="human")):
        with pytest.raises(ReviewError) as exc:
            call()
        assert exc.value.status == 422 and exc.value.code == "too_many", exc.value
        assert exc.value.details["limit"] == AGENT_MAX_BATCH, exc.value.details
    row = row_of(store, got["deletion_id"])
    assert int(row["stage"]) == 1 and row["to_path"] is None and row["closed_at"] is None
    assert (library / "over.png").exists(), "上限を断ったのにファイルが動いた"


def test_many_needs_a_non_empty_list_of_ids(svc, store, library):
    """壊すと落ちる: `ids` の形を確かめない（文字列を 1 件として受ける・空で 200 を返す）。"""
    for bad in (None, "", "d1", [], [""], 5, {"id": "d1"}):
        for call in (lambda: svc.advance_many(bad, stage=2, actor="human"),
                     lambda: svc.close_many(bad, reason="missing", actor="human")):
            with pytest.raises(ReviewError) as exc:
                call()
            assert exc.value.status == 422 and exc.value.code == "bad_ids", (bad, exc.value)


def test_many_folds_duplicate_ids(svc, store, library):
    """壊すと落ちる: 同じ id を 2 回処理する（**1 件に畳む**。2 度目は断りに出る）。"""
    got = stage1(svc, store, library / "dupe.png", missing=True)
    out = svc.close_many([got["deletion_id"], got["deletion_id"]], reason="missing", actor="human")
    assert out["requested"] == 1 and out["count"] == 1 and out["skipped_count"] == 0, out


# ---- 読みは書かない ----


def test_get_never_writes_for_the_new_flows(svc, store, library):
    """壊すと落ちる: `GET`（`pending` / `trash` / `ledger`）が 1 バイトでも書く（家風）。

    片付けた行・進めた行が混ざった状態でも、読むだけであることを見る。
    """
    moved = stage1(svc, store, make_png(library / "read.png", seed=50))
    svc.advance(moved["deletion_id"], stage=2, actor="human")
    closed = stage1(svc, store, library / "read-gone.png", missing=True)
    svc.close(closed["deletion_id"], reason="missing", actor="human")
    tables = [r["name"] for r in store.con.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY name")]
    before = (tuple(store.con.execute(f"SELECT count(*) AS n FROM {t}").fetchone()["n"]
                    for t in tables),
              tuple(tuple(r) for r in store.con.execute(
                  "SELECT id, stage, to_path, closed_at, close_reason, restored_at"
                  " FROM deletion_log ORDER BY id")),
              files_under(store.data_dir), files_under(library))
    svc.pending(actor="human")
    svc.trash(actor="human")
    svc.ledger(actor="human")
    svc.found_in_hold()
    after = (tuple(store.con.execute(f"SELECT count(*) AS n FROM {t}").fetchone()["n"]
                   for t in tables),
             tuple(tuple(r) for r in store.con.execute(
                 "SELECT id, stage, to_path, closed_at, close_reason, restored_at"
                 " FROM deletion_log ORDER BY id")),
             files_under(store.data_dir), files_under(library))
    assert after == before, "GET が書いている"


# ---- 口（HTTP）----


def register(client, tmp_path: Path, name: str, *, seed: int = 1, missing: bool = False):
    """口の試験の下ごしらえ（**アプリの store に** 1 枚登録する）。"""
    store = client.app.state.store
    root = tmp_path / "httplib"
    root.mkdir(parents=True, exist_ok=True)
    store.set_roots([str(root)])
    path = root / name
    asset_id = add_missing_asset(store, path) if missing else add_asset(store, make_png(path, seed=seed))
    return store, path, asset_id


def test_the_new_endpoints_are_guarded(client, tmp_path):
    """家風: 新しい口も `Host` / `Content-Type` / 語彙で守る（403 / 422）。"""
    store, path, asset_id = register(client, tmp_path, "guard.png")
    made = client.post("/api/locations/delete", headers=HUMAN,
                       json={"asset_id": asset_id, "path": str(path), "stage": 1}).json()
    deletion_id = made["deletion_id"]
    for url, body in ((f"/api/deletions/{deletion_id}/advance", {"stage": 2}),
                      ("/api/deletions/advance", {"ids": [deletion_id], "stage": 2}),
                      (f"/api/deletions/{deletion_id}/close", {"reason": "missing"}),
                      ("/api/deletions/close", {"ids": [deletion_id], "reason": "missing"})):
        assert client.post(url, json=body, headers={"Host": "evil", **HUMAN}).status_code == 403
        assert client.post(url, content=json.dumps(body),
                           headers={"Content-Type": "text/plain", **HUMAN}).status_code == 403
        # **人だけ**（エージェントは 403 `human_only`）
        bad = client.post(url, json=body, headers=AGENT)
        assert bad.status_code == 403 and bad.json()["code"] == "human_only", (url, bad.text)
        # 語彙の外の actor は 422
        assert client.post(url, json=body,
                           headers={"X-Image-Reviewer-Actor": "robot"}).status_code == 422
    # **段 3 への直行は無い**（422 `bad_stage`）
    assert client.post(f"/api/deletions/{deletion_id}/advance", headers=HUMAN,
                       json={"stage": 3}).status_code == 422
    assert client.post("/api/deletions/advance", headers=HUMAN,
                       json={"ids": [deletion_id], "stage": 3}).json()["code"] == "bad_stage"
    # **語彙の外の理由**（422 `bad_reason`）・`ids` の形（422 `bad_ids`）
    assert client.post(f"/api/deletions/{deletion_id}/close", headers=HUMAN,
                       json={"reason": "other"}).json()["code"] == "bad_reason"
    assert client.post("/api/deletions/close", headers=HUMAN,
                       json={"ids": [], "reason": "missing"}).json()["code"] == "bad_ids"
    # **`GET` の口は無い**（読むのは `GET /api/pending-deletes` と `/api/deletions`）
    assert client.get(f"/api/deletions/{deletion_id}/advance", headers=HUMAN).status_code == 404
    assert client.get("/api/deletions/close", headers=HUMAN).status_code == 404


def test_advance_and_close_over_http(client, tmp_path):
    """口が**実物の形**で動く（1 件と、まとめての両方）。"""
    store, path, asset_id = register(client, tmp_path, "http-adv.png", seed=60)
    made = client.post("/api/locations/delete", headers=HUMAN,
                       json={"asset_id": asset_id, "path": str(path), "stage": 1}).json()
    out = client.post(f"/api/deletions/{made['deletion_id']}/advance", headers=HUMAN,
                      json={"stage": 2})
    assert out.status_code == 200, out.text
    body = out.json()
    assert body["stage"] == 2 and body["actor"] == "human" and Path(body["to_path"]).exists()
    assert not path.exists()
    # **「戻す」がそのまま効く**
    back = client.post("/api/pending-deletes/{}/undo".format(made["deletion_id"]), headers=HUMAN,
                       json={})
    assert back.status_code == 200 and path.exists(), back.text
    # まとめて（進める → 片付ける）
    store2, path2, asset2 = register(client, tmp_path, "http-many.png", seed=61)
    made2 = client.post("/api/locations/delete", headers=HUMAN,
                        json={"asset_id": asset2, "path": str(path2), "stage": 1}).json()
    many = client.post("/api/deletions/advance", headers=HUMAN,
                       json={"ids": [made2["deletion_id"]], "stage": 2})
    assert many.status_code == 200 and many.json()["count"] == 1, many.text
    assert Path(many.json()["advanced"][0]["to_path"]).exists()
    # ゴミ箱の中身を利用者が消した形にしてから、まとめて片付ける
    Path(many.json()["advanced"][0]["to_path"]).unlink()
    closed = client.post("/api/deletions/close", headers=HUMAN,
                         json={"ids": [made2["deletion_id"]], "reason": "missing"})
    assert closed.status_code == 200, closed.text
    assert closed.json()["count"] == 1 and closed.json()["closed"][0]["files_touched"] == 0
    one = client.post(f"/api/deletions/{made2['deletion_id']}/close", headers=HUMAN,
                      json={"reason": "missing"})
    assert one.status_code == 200 and one.json()["replayed"] is True, one.text
    # **片付けた行は「最近の削除」から外れる**
    left = client.get("/api/pending-deletes", headers=HUMAN).json()
    assert [i["id"] for i in left["items"]] == [], left["items"]


def test_advance_over_http_without_a_file_names_the_close_button(client, tmp_path):
    """壊すと落ちる: 実体が無いときの断りに**次の一手が無い**（409 `missing_file`。画面のボタン名）。"""
    store, path, asset_id = register(client, tmp_path, "http-gone.png", missing=True)
    made = client.post("/api/locations/delete", headers=HUMAN,
                       json={"asset_id": asset_id, "path": str(path), "stage": 1}).json()
    got = client.post(f"/api/deletions/{made['deletion_id']}/advance", headers=HUMAN,
                      json={"stage": 2})
    assert got.status_code == 409, got.text
    body = got.json()
    assert body["code"] == "missing_file" and "ファイルが無いので片付ける" in body["detail"], body
    # **片付ければ終われる**（案内どおりに押すと通る）
    done = client.post(f"/api/deletions/{made['deletion_id']}/close", headers=HUMAN,
                       json={"reason": "missing"})
    assert done.status_code == 200 and done.json()["closed"] is True, done.text
    assert store.con.execute("SELECT deleted_at FROM asset WHERE id = ?",
                             (asset_id,)).fetchone()["deleted_at"], "カタログに戻った"
