"""削除の 3 段階と 5 分の窓（P8-2）のテスト。

設計: `docs/p8-design.md` §0.6（3 段階と窓）・§0.7（凍結 → 実行）・§3.2〜§3.4（口）・
      §4（状態）・§8.1 / §8.4（壊すと落ちる）

**何を壊すと落ちるか**を各テストの docstring に書いてある（家風）。
**時計は注入する**（`Clock` を 1 つだけ。`time.monotonic()` を直接呼ばない。§8 の末尾）。
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from image_reviewer import db, deletions
from image_reviewer.deletions import (AGENT_MAX_BATCH, DEFAULT_UNDO_WINDOW_SEC, HOLD_DIR,
                                      HOLD_PURGED, TRASH_DIR, DeletionService, free_name,
                                      frees_for, move_no_clobber)
from image_reviewer.review import ReviewError
from image_reviewer.store import Store, normalize_path

HUMAN = {"X-Image-Reviewer-Actor": "human"}
AGENT = {"X-Image-Reviewer-Actor": "agent"}


# ---- 道具 ----


class FakeClock:
    """テスト用の時計（**壁と単調の両方を 1 つの口から進める**。`test_clock.py` と同じ形）。"""

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
    """実体のあるファイルを 1 枚登録する（**登録した `(size, mtime_ns)` が正**になる）。"""
    key = name or path.name
    digest = hashlib.sha256(f"{key}:{path}".encode("utf-8")).hexdigest()
    asset_id, _ = store.register(
        sha256=digest, path=str(path), size=path.stat().st_size,
        mtime_ns=path.stat().st_mtime_ns, width=16, height=16, fmt="png",
        meta=None, note=None)
    return asset_id


def where(store: Store, asset_id: str) -> dict:
    """その枚の場所（1 行）。"""
    row = store.con.execute("SELECT * FROM asset_location WHERE asset_id = ?",
                            (asset_id,)).fetchone()
    return dict(row)


def root_with_stage3(store: Store, directory: Path) -> None:
    """その置き場に**段 3 を許す印**を立てる（Q8。**既定は印なし**）。"""
    store.set_roots([str(directory)])
    with store.transaction() as con:
        con.execute("UPDATE root SET allow_stage3 = 1 WHERE path = ?",
                    (normalize_path(directory),))


def stage3_row(store: Store, row_id: str, hold_path: str, *, remaining: int,
               purge_at: str | None = "2000-01-01T00:00:00Z") -> None:
    """段 3 の台帳の行を**直に入れる**（クラッシュで残った行・期限切れの試験用）。"""
    with store.transaction() as con:
        con.execute(
            "INSERT INTO deletion_log(id, asset_id, path, stage, hold_path, remaining_sec,"
            " purge_at, size, actor, at) VALUES (?,?,?,3,?,?,?,?, 'human', 't')",
            (row_id, None, None, hold_path, remaining, purge_at, 0))


@pytest.fixture
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
    """**複製の中の置き場**（実データは触らない。段 3 の印つき）。"""
    got = tmp_path / "library"
    got.mkdir(parents=True, exist_ok=True)
    root_with_stage3(store, got)
    return got


@pytest.fixture
def client(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("IMAGE_REVIEWER_DATA", str(tmp_path / "app"))
    from image_reviewer.app import create_app
    app = create_app()
    with TestClient(app, base_url="http://127.0.0.1") as got:
        yield got


# ---- 段 1（印だけ）----


def test_stage1_only_sets_the_flag_and_keeps_the_file_and_the_row(svc, store, library, tmp_path):
    """壊すと落ちる: 段 1 で**行を消す**・**ファイルを動かす**と、戻せなくなる（§4.1）。

    段 1 は「カタログから外す」だけ。`asset` の行も `asset_location` の行も残し、
    ファイルにも触らない（`size` / `mtime_ns` が変わらない）。
    """
    path = make_png(library / "a.png", seed=1)
    asset_id = add_asset(store, path)
    before = (path.stat().st_size, path.stat().st_mtime_ns)
    got = svc.delete(asset_id=asset_id, path=str(path), stage=1, reason="ボツ",
                     actor="human")
    assert got["stage"] == 1 and got["remaining_sec"] is None
    assert got["frees"]["bytes"] == 0, "段 1 で容量が空くと言っている（§8.1 の 16）"
    assert path.exists(), "段 1 でファイルを動かしている"
    assert (path.stat().st_size, path.stat().st_mtime_ns) == before
    row = store.con.execute("SELECT deleted_at FROM asset WHERE id = ?", (asset_id,)).fetchone()
    assert row["deleted_at"], "段 1 の印が立っていない"
    assert where(store, asset_id)["missing_at"] is None, "段 1 で参照切れにしている"
    log = store.con.execute("SELECT * FROM deletion_log WHERE asset_id = ?",
                            (asset_id,)).fetchall()
    assert len(log) == 1 and log[0]["stage"] == 1 and log[0]["actor"] == "human"
    assert log[0]["reason"] == "ボツ" and log[0]["request_id"]


def test_stage1_can_be_undone_without_touching_the_file(svc, store, library):
    """壊すと落ちる: 段 1 の取り消しで**ファイルを触る**（専門 §3.1「いつでも戻せる」）。"""
    path = make_png(library / "a.png", seed=2)
    asset_id = add_asset(store, path)
    got = svc.delete(asset_id=asset_id, path=str(path), stage=1, actor="human")
    back = svc.undo(got["deletion_id"], actor="human")
    assert back["restored"] is True and back["stage"] == 1
    row = store.con.execute("SELECT deleted_at FROM asset WHERE id = ?", (asset_id,)).fetchone()
    assert row["deleted_at"] is None, "取り消したのに印が残っている"
    assert path.exists()


# ---- 段 2（ゴミ箱）----


def test_stage2_moves_to_the_trash_and_restores(svc, store, library):
    """壊すと落ちる: 段 2 で**元の場所に残す**・`missing_at` を立てない・戻せない（§4.1・§3.3）。"""
    path = make_png(library / "b.png", seed=3)
    asset_id = add_asset(store, path)
    got = svc.delete(asset_id=asset_id, path=str(path), stage=2, actor="human")
    assert not path.exists(), "段 2 でファイルが動いていない"
    moved = Path(got["to_path"])
    assert moved.exists() and moved.name == "b.png"
    # 専門 §3.3: `<data>/trash/<YYYYMMDD>/<sha256[0:2]>/<元のファイル名>`
    parts = moved.parts
    assert TRASH_DIR in parts, moved
    assert store.con.execute("SELECT missing_at FROM asset_location WHERE asset_id = ?",
                             (asset_id,)).fetchone()["missing_at"], "段 2 で参照切れにしていない"
    assert len(svc.trash()["days"]) == 1 and svc.trash()["count"] == 1
    back = svc.trash_restore(got["deletion_id"], actor="human")
    assert back["restored"] is True and path.exists(), "ゴミ箱から戻っていない"
    assert store.con.execute("SELECT missing_at FROM asset_location WHERE asset_id = ?",
                             (asset_id,)).fetchone()["missing_at"] is None
    assert not moved.exists(), "戻したのにゴミ箱に残っている"
    assert store.con.execute("SELECT deleted_at FROM asset WHERE id = ?",
                             (asset_id,)).fetchone()["deleted_at"] is None


def test_stage2_chooses_a_free_name_in_the_trash(svc, store, library):
    """壊すと落ちる: ゴミ箱の同名衝突で**落ちる**（`<名前>.<連番>.<拡張子>` にしない。専門 §3.3）。"""
    first = make_png(library / "same.png", seed=4)
    a = add_asset(store, first)
    svc.delete(asset_id=a, path=str(first), stage=2, actor="human")
    # **同じ名前の別の絵**を戻して、もう一度消す（`sha256` が違うフォルダに入る）
    second = make_png(library / "same.png", seed=5)
    b = add_asset(store, second)
    got = svc.delete(asset_id=b, path=str(second), stage=2, actor="human")
    assert Path(got["to_path"]).name in ("same.png", "same.1.png")
    assert Path(got["to_path"]).exists(), "2 枚目がゴミ箱に入っていない"


# ---- 段 3（保留領域と 5 分の窓）----


def test_stage3_moves_to_the_hold_area_and_keeps_the_location_row(svc, store, library):
    """壊すと落ちる: 段 3 で**即 unlink する**（§8.1 の 8）・`asset_location` の行を消す（点検 A3）。"""
    path = make_png(library / "c.png", seed=6)
    asset_id = add_asset(store, path)
    got = svc.delete(asset_id=asset_id, path=str(path), stage=3, actor="human",
                     confirm_last_copy=True)
    assert got["stage"] == 3 and got["remaining_sec"] == DEFAULT_UNDO_WINDOW_SEC
    hold = Path(got["hold_path"])
    assert hold.exists() and not path.exists(), "段 3 の直後にファイルが保留領域に無い"
    assert str(hold).startswith(str(store.data_dir / HOLD_DIR)), hold
    loc = where(store, asset_id)
    assert loc["path"] == normalize_path(path), "（点検 A3）窓の間に asset_location を消している"
    assert loc["missing_at"], "段 3 で参照切れにしていない"
    assert store.con.execute("SELECT deleted_at FROM asset WHERE id = ?",
                             (asset_id,)).fetchone()["deleted_at"]
    pend = svc.pending(actor="human")
    assert pend["count"] == 1 and pend["items"][0]["remaining_sec"] == 300
    assert pend["items"][0]["undoable"] is True and pend["items"][0]["mine"] is True
    assert got["frees"]["at"] == got["purge_at"], "frees が窓の後の時刻を出していない"


def test_the_window_moves_with_the_monotonic_clock_only(svc, store, library, clock):
    """壊すと落ちる: 窓を**壁時計**で数える（§8.1 の 9）・`tick` が減らさない（§8.4 F8）。

    壁時計を 1 時間進めても `remaining_sec` は変わらない。単調時計を 30 秒進めて 1 周期で
    30 秒ぶんだけ減る（**アプリが動いていた時間**で数える）。
    """
    path = make_png(library / "d.png", seed=7)
    asset_id = add_asset(store, path)
    got = svc.delete(asset_id=asset_id, path=str(path), stage=3, actor="human",
                     confirm_last_copy=True)
    clock.advance(sec=3600)                       # **壁時計だけ**進める
    svc.tick()
    left = store.con.execute("SELECT remaining_sec FROM deletion_log WHERE id = ?",
                             (got["deletion_id"],)).fetchone()["remaining_sec"]
    assert left == 300, f"壁時計で窓が縮んだ（{left}）"
    clock.advance(mono=30)                        # 単調時計を 30 秒
    svc.tick()
    left = store.con.execute("SELECT remaining_sec FROM deletion_log WHERE id = ?",
                             (got["deletion_id"],)).fetchone()["remaining_sec"]
    assert left == 270, f"単調時計の 30 秒が引かれていない（{left}）"
    assert Path(got["hold_path"]).exists()


def test_the_start_does_not_delete_anything_and_the_first_tick_waits(svc, store, clock, tmp_path):
    """壊すと落ちる: **起動時に消す**（§8.1 の 10）・最初の周期で消す（§0.6-3）。

    クラッシュで `remaining_sec` が 0 のまま残った行は、**起動時には消さない**し、
    **タイマーの 1 回目でも消さない**（2 回目で消す）。`purge_at` が過去でも消えない（線 7）。
    """
    hold = store.data_dir / HOLD_DIR / "old"
    hold.mkdir(parents=True, exist_ok=True)
    kept = make_png(hold / "kept.png", seed=8)
    stage3_row(store, "old", str(kept), remaining=0, purge_at="2000-01-01T00:00:00Z")
    fresh = DeletionService(store, clock=clock)          # **起動**（消さない）
    assert kept.exists(), "起動時に消している"
    fresh.tick()                                          # 1 周期目（**まだ消さない**）
    assert kept.exists(), "起動直後の 1 回で消している（1 周期待つ）"
    clock.advance(mono=30)
    got = fresh.tick()                                    # 2 周期目
    assert got["purged"] == 1 and not kept.exists(), "2 周期目でも消えていない"
    row = store.con.execute("SELECT hold_path, remaining_sec FROM deletion_log WHERE id = 'old'"
                            ).fetchone()
    assert row["hold_path"] == HOLD_PURGED, "hold_path を『消えた印』にしていない"
    assert store.con.execute("SELECT count(*) AS n FROM deletion_log WHERE id = 'old'"
                             ).fetchone()["n"] == 1, "台帳の行を消している"


def test_the_purge_deletes_the_location_row_and_drops_out_of_the_pending_list(svc, store,
                                                                            library, clock):
    """壊すと落ちる: 窓が切れても**保留領域を消さない**・消した後も一覧に残す（§4.1）。"""
    path = make_png(library / "e.png", seed=9)
    asset_id = add_asset(store, path)
    got = svc.delete(asset_id=asset_id, path=str(path), stage=3, actor="human",
                     confirm_last_copy=True)
    with_store = store.con.execute("SELECT remaining_sec FROM deletion_log WHERE id = ?",
                                   (got["deletion_id"],)).fetchone()["remaining_sec"]
    with store.transaction() as con:                      # 窓をもうすぐ切れる所まで進める
        con.execute("UPDATE deletion_log SET remaining_sec = 5 WHERE id = ?",
                    (got["deletion_id"],))
    svc.tick()                                            # 1 周期目（消さない）
    clock.advance(mono=6)
    svc.tick()                                            # 2 周期目（**ここで消える**）
    assert not Path(got["hold_path"]).exists(), "窓が切れても保留領域が残っている"
    assert store.con.execute("SELECT count(*) AS n FROM asset_location WHERE asset_id = ?",
                             (asset_id,)).fetchone()["n"] == 0, \
        "（点検 A3）実削除のときに asset_location を消していない"
    assert svc.pending(actor="human")["count"] == 0, "実削除の後も『取り消せる』に出ている"
    led = svc.ledger(actor="human")
    assert led["items"][0]["state"] == "purged", led["items"][0]
    assert with_store == 300


# ---- 取り消し（上書きしない）----


def test_undo_restores_the_file_and_clears_both_flags(svc, store, library):
    """壊すと落ちる: 取り消しで `missing_at` / `deleted_at` を戻さない（§1.2 の線 6）。"""
    path = make_png(library / "f.png", seed=10)
    asset_id = add_asset(store, path)
    got = svc.delete(asset_id=asset_id, path=str(path), stage=3, actor="human",
                     confirm_last_copy=True)
    back = svc.undo(got["deletion_id"], actor="human")
    assert path.exists() and not Path(got["hold_path"]).exists()
    assert back["restored_at"] and back["remaining_sec"] is None and back["purge_at"] is None
    assert where(store, asset_id)["missing_at"] is None
    assert store.con.execute("SELECT deleted_at FROM asset WHERE id = ?",
                             (asset_id,)).fetchone()["deleted_at"] is None
    row = store.con.execute("SELECT restored_at, purge_at, remaining_sec FROM deletion_log"
                            " WHERE id = ?", (got["deletion_id"],)).fetchone()
    assert row["restored_at"] and row["purge_at"] is None and row["remaining_sec"] is None


def test_undo_never_overwrites_a_file_that_appeared_meanwhile(svc, store, library):
    """壊すと落ちる: 取り消しで **`os.replace` を使う**（§8.4 F2。元の場所の別のファイルが壊れる）。

    埋まっていたら **409 `target_exists`** で止めて尋ねる。**別のファイルのバイト列が変わらない**
    ことと、**保留領域のファイルが残っている**ことを見る（尋ねている間に消さない）。
    人だけが `as_copy: true` で `<名前>.<連番>.<拡張子>` に戻せる。
    """
    path = make_png(library / "g.png", seed=11)
    asset_id = add_asset(store, path)
    got = svc.delete(asset_id=asset_id, path=str(path), stage=3, actor="human",
                     confirm_last_copy=True)
    other = b"someone-elses-bytes"
    path.write_bytes(other)                              # **別のファイル**が現れた
    with pytest.raises(ReviewError) as err:
        svc.undo(got["deletion_id"], actor="human")
    assert err.value.status == 409 and err.value.code == "target_exists"
    assert path.read_bytes() == other, "取り消しが元の場所の別のファイルを壊した（os.replace）"
    assert Path(got["hold_path"]).exists(), "止めたのに保留領域のファイルが消えている"
    assert store.con.execute("SELECT purge_at FROM deletion_log WHERE id = ?",
                             (got["deletion_id"],)).fetchone()["purge_at"] is None, \
        "尋ねている間に自動削除が走る（purge_at を NULL にしていない）"
    back = svc.undo(got["deletion_id"], as_copy=True, actor="human")
    copy = Path(back["display_path"])
    assert copy.exists() and copy.name == "g.1.png", copy
    assert path.read_bytes() == other, "別名で戻したのに元の場所を触っている"
    loc = where(store, asset_id)
    assert loc["path"] == normalize_path(copy) and loc["missing_at"] is None, \
        "別名で戻したのに登録が古い名前を指している"


def test_undo_is_only_for_my_own_deletions(svc, store, library):
    """壊すと落ちる: **他人（人を含む）が消した物を戻せる**（§8.4 F9・§3.4）。

    エージェントが消した物は、人が `undo` しても **403 `not_yours`**（自分が消した物だけ）。
    エージェントは自分の分を戻せる。**`as_copy` は人だけ**（403 `human_only`）。
    """
    path = make_png(library / "h.png", seed=12)
    asset_id = add_asset(store, path)
    got = svc.delete(asset_id=asset_id, path=str(path), stage=3, actor="agent",
                     confirm_last_copy=True)
    with pytest.raises(ReviewError) as err:
        svc.undo(got["deletion_id"], actor="human")
    assert err.value.status == 403 and err.value.code == "not_yours"
    assert not path.exists(), "403 なのにファイルが戻っている"
    with pytest.raises(ReviewError) as err2:
        svc.undo(got["deletion_id"], as_copy=True, actor="agent")
    assert err2.value.status == 403 and err2.value.code == "human_only"
    ok = svc.undo(got["deletion_id"], actor="agent")
    assert ok["restored"] is True and path.exists(), "自分の削除を戻せない"


def test_the_pending_list_marks_who_deleted_it(svc, store, library):
    """壊すと落ちる: `actor` を記録しない・返さない（Q2 の帰結 a・b。§8.1 の 28）。"""
    path = make_png(library / "i.png", seed=13)
    asset_id = add_asset(store, path)
    svc.delete(asset_id=asset_id, path=str(path), stage=3, actor="agent",
               confirm_last_copy=True)
    mine = svc.pending(actor="agent")["items"][0]
    theirs = svc.pending(actor="human")["items"][0]
    assert mine["actor"] == "agent" and mine["mine"] is True and mine["undoable"] is True
    assert theirs["mine"] is False and theirs["undoable"] is False, \
        "画面が『他人の削除』に戻すボタンを出してしまう"


# ---- 安全規則（最後の 1 つ・置き場の印・別ボリューム・中身の変化）----


def test_the_last_copy_needs_a_heavy_confirmation(svc, store, library):
    """壊すと落ちる: 「最後の 1 つ」の判定を外す（§8.1 の 7）・1 枚も消さない（§3.4 `last_copy`）。"""
    path = make_png(library / "j.png", seed=14)
    asset_id = add_asset(store, path)
    with pytest.raises(ReviewError) as err:
        svc.delete(asset_id=asset_id, path=str(path), stage=3, actor="human")
    assert err.value.status == 409 and err.value.code == "last_copy"
    assert path.exists(), "409 なのにファイルが動いている"
    assert store.con.execute("SELECT count(*) AS n FROM deletion_log").fetchone()["n"] == 0, \
        "断ったのに台帳に行を残している"
    assert store.con.execute("SELECT count(*) AS n FROM delete_request").fetchone()["n"] == 0, \
        "断ったのに要求の行を残している"
    got = svc.delete(asset_id=asset_id, path=str(path), stage=3, actor="human",
                     confirm_last_copy=True)
    assert got["stage"] == 3


def test_the_second_live_location_makes_it_not_the_last_copy(svc, store, library, tmp_path):
    """**他のコピーがあれば軽い確認で段 3 に進める**（専門 §3.2 の 3。規則が逆向きでないこと）。"""
    first = make_png(library / "k1.png", seed=15)
    asset_id = add_asset(store, first)
    second = tmp_path / "library2" / "k2.png"
    make_png(second, seed=15)
    root_with_stage3(store, second.parent)
    with store.transaction() as con:            # 同じ `asset` の 2 か所目
        con.execute("INSERT INTO asset_location(path, display_path, asset_id, size, mtime_ns,"
                    " is_primary, missing_at, last_seen_at) VALUES (?,?,?,?,?,0,NULL,'t')",
                    (normalize_path(second), str(second), asset_id, second.stat().st_size,
                     second.stat().st_mtime_ns))
    got = svc.delete(asset_id=asset_id, path=str(first), stage=3, actor="human")
    assert got["stage"] == 3, "コピーが残るのに重い確認を要求している"
    assert Path(got["hold_path"]).exists()


def test_stage3_needs_the_flag_on_the_root(svc, store, tmp_path):
    """壊すと落ちる: `root.allow_stage3` を無視する（§8.1・点検 B7。**既定は印なし**）。"""
    plain = tmp_path / "plain"
    plain.mkdir(parents=True, exist_ok=True)
    store.set_roots([str(plain)])                       # 印は立てない（既定 0）
    path = make_png(plain / "l.png", seed=16)
    asset_id = add_asset(store, path)
    with pytest.raises(ReviewError) as err:
        svc.delete(asset_id=asset_id, path=str(path), stage=3, actor="human",
                   confirm_last_copy=True)
    assert err.value.status == 409 and err.value.code == "stage_not_allowed"
    assert path.exists() and not (store.data_dir / HOLD_DIR).exists()
    # **段 1・段 2 は通る**（印が無くても catalog とゴミ箱までは使える）
    assert svc.delete(asset_id=asset_id, path=str(path), stage=1, actor="human")["stage"] == 1
    assert svc.delete(asset_id=asset_id, path=str(path), stage=2, actor="human")["stage"] == 2


def test_a_root_outside_every_root_is_not_allowed(svc, store, tmp_path):
    """**どの root にも入っていない置き場は段 3 を許さない**（安全側。§0.6-6 の帰結）。"""
    path = make_png(tmp_path / "outside" / "m.png", seed=17)
    asset_id = add_asset(store, path)
    with pytest.raises(ReviewError) as err:
        svc.delete(asset_id=asset_id, path=str(path), stage=3, actor="human",
                   confirm_last_copy=True)
    assert err.value.status == 409 and err.value.code == "stage_not_allowed"


def test_another_volume_is_refused_by_stage2_and_stage3(svc, store, library, monkeypatch):
    """壊すと落ちる: `st_dev` を見ない（§8.4 F5。**コピーもしない**で断る）。"""
    path = make_png(library / "n.png", seed=18)
    asset_id = add_asset(store, path)
    real = deletions.st_dev_of

    def fake(candidate):
        text = str(candidate).lower()
        if HOLD_DIR in text or TRASH_DIR in text:
            return 2                                    # 保留領域は別のボリューム
        return real(candidate)

    monkeypatch.setattr(deletions, "st_dev_of", fake)
    for stage in (2, 3):
        with pytest.raises(ReviewError) as err:
            svc.delete(asset_id=asset_id, path=str(path), stage=stage, actor="human",
                       confirm_last_copy=True)
        assert err.value.status == 409 and err.value.code == "cross_volume", stage
        assert path.exists(), f"段 {stage}: 断ったのにファイルが動いている"
    assert store.con.execute("SELECT count(*) AS n FROM deletion_log").fetchone()["n"] == 0
    for folder in (HOLD_DIR, TRASH_DIR):                 # **コピーもしていない**
        got = store.data_dir / folder
        assert not got.exists() or not any(got.rglob("*.png")), f"{folder} にコピーが残っている"


def test_a_changed_file_is_not_deleted(svc, store, library):
    """壊すと落ちる: `(size, mtime_ns)` の再照合を外す（§8.1 の 6）。**別のファイルを消さない。**"""
    path = make_png(library / "o.png", seed=19)
    asset_id = add_asset(store, path)
    make_png(path, seed=20, size=(32, 32))               # 中身が入れ替わった
    with pytest.raises(ReviewError) as err:
        svc.delete(asset_id=asset_id, path=str(path), stage=3, actor="human",
                   confirm_last_copy=True)
    assert err.value.status == 409 and err.value.code == "changed"
    assert path.exists()
    assert store.con.execute("SELECT count(*) AS n FROM deletion_log").fetchone()["n"] == 0


def test_the_target_must_be_registered_and_matched_exactly(svc, store, library, tmp_path):
    """壊すと落ちる: `normalize_path` を `str(path)` に替える（§8.1 の 4）・**前方一致**（同 5）。

    大小文字が違っても**同じ鍵**として当たる。登録されていないパスは 409 `not_registered`。
    **前方一致にすると `…\\p.png` の登録で `…\\p.png.extra` を消せてしまう**（専門 §3.2 の 1 が
    明示的に禁じている）ので、**本当に存在する「接頭辞の長いパス」**で試す。
    """
    path = make_png(library / "p.png", seed=21)
    asset_id = add_asset(store, path)
    got = svc.delete(asset_id=asset_id, path=str(path).upper(), stage=1, actor="human")
    assert got["stage"] == 1, "大小文字違いで同じ場所に当たっていない（normalize_path を外した）"
    other = make_png(tmp_path / "other" / "q.png", seed=22)
    with pytest.raises(ReviewError) as err:
        svc.delete(asset_id=asset_id, path=str(other), stage=1, actor="human")
    assert err.value.status == 409 and err.value.code == "not_registered"
    # **前方一致なら通ってしまう形**（登録した `p.png` の接頭辞で始まる、別の実在のファイル）
    attack = Path(str(path) + ".extra")
    attack.write_bytes(b"not-registered")
    with pytest.raises(ReviewError) as err2:
        svc.delete(asset_id=asset_id, path=str(attack), stage=2, actor="human")
    assert err2.value.status == 409, "前方一致で別のファイルを消しかけている"
    assert attack.read_bytes() == b"not-registered" and path.exists()


def test_the_limit_of_the_rule_a_same_size_swap_is_not_detected(svc, store, library):
    """**規則の限界を固定する**（§8.4 F4）。`(size, mtime_ns)` が同じ差し替えは**気づけない**。

    中身を**同じ大きさ**の別の物に差し替え、`os.utime` で `mtime_ns` を元に戻すと、段 2・3 は
    そのまま進む（ハッシュを見ていないため）。**設計の限界**であって壊れ方ではないが、
    「中身を確かめてから」は再リンク（P8-3）の話なので、ここに**固定**しておく。
    **もし将来ハッシュで見るようにしたら、このテストは落ちる**（そのときは設計を直す）。
    """
    path = make_png(library / "limit.png", seed=120)
    asset_id = add_asset(store, path)
    before = path.stat()
    original = path.read_bytes()
    path.write_bytes(bytes((b + 1) % 256 for b in original))     # **同じ大きさ**の別の中身
    os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns))
    now = path.stat()
    assert (now.st_size, now.st_mtime_ns) == (before.st_size, before.st_mtime_ns), \
        "試験の前提（同じ大きさ・同じ mtime に戻す）が崩れている"
    got = svc.delete(asset_id=asset_id, path=str(path), stage=2, actor="human")
    assert got["stage"] == 2 and not path.exists(), \
        "同じ大きさ・同じ mtime の差し替えは検出できない（規則の限界。§8.4 F4）"


def test_move_no_clobber_refuses_to_overwrite(tmp_path):
    """壊すと落ちる: `os.rename` を **`os.replace`** に替える（黙って上書きする＝P7 の実測）。"""
    src = tmp_path / "src.bin"
    dst = tmp_path / "dst.bin"
    src.write_bytes(b"new")
    dst.write_bytes(b"old")
    with pytest.raises(ReviewError) as err:
        move_no_clobber(src, dst)
    assert err.value.status == 409 and err.value.code == "target_exists"
    assert dst.read_bytes() == b"old", "既存のファイルを上書きした"
    assert src.read_bytes() == b"new"
    # 空いていれば移る
    assert move_no_clobber(src, tmp_path / "free.bin")
    assert not src.exists()


def test_free_name_numbers_the_copies(tmp_path):
    """`<名前>.<連番>.<拡張子>`（専門 §3.3）。**1 枚目は元の名前**。"""
    (tmp_path / "a.png").write_bytes(b"1")
    (tmp_path / "a.1.png").write_bytes(b"2")
    assert free_name(tmp_path, "a.png").name == "a.2.png"
    assert free_name(tmp_path, "b.png").name == "b.png"


def test_the_hold_area_is_the_only_place_the_purge_touches(svc, store, tmp_path):
    """壊すと落ちる: `_remove_hold` の下見を外す（**保留領域の外を消す**事故）。"""
    outside = make_png(tmp_path / "precious.png", seed=23)
    with pytest.raises(OSError):
        svc._remove_hold(str(outside))
    assert outside.exists(), "保留領域の外のファイルを消した"


# ---- 一括（凍結 → 実行）----


def test_the_preview_freezes_the_list_and_only_that_list_is_deleted(svc, store, library):
    """壊すと落ちる: 実行時に `scope` を評価し直す（§8.1 の 14。**見せていないファイルを消す**）。

    **フォルダで選ぶ**（実行時に引き直すと、凍結の後で増えた枚が入ってしまう形）。
    凍結の後で同じフォルダに 1 枚足し、**それが消えない**ことを見る。
    """
    ids = []
    for i in range(5):
        path = make_png(library / f"bulk{i}.png", seed=30 + i)
        ids.append(add_asset(store, path))
    scope = {"kind": "folder", "id": str(library)}
    got = svc.bulk_preview(scope=scope, stage=2, actor="human")
    assert got["count"] == 5 and got["bytes"] > 0 and got["last_copies"] == 5
    # **最後の 1 つになる枚があるので、確認が要る**（1 枚も消さない）
    with pytest.raises(ReviewError) as err:
        svc.bulk_delete(preview_id=got["preview_id"], confirm=True, actor="human")
    assert err.value.status == 409 and err.value.code == "last_copy"
    assert all(p.exists() for p in library.glob("bulk*.png"))
    # **凍結の後で増えた枚**（同じフォルダに入るが、見せていない）
    extra = make_png(library / "bulk-extra.png", seed=99)
    extra_id = add_asset(store, extra)
    done = svc.bulk_delete(preview_id=got["preview_id"], confirm=True, actor="human",
                           confirm_last_copy=True)
    assert done["count"] == 5 and not done["skipped"], done
    assert len(done["deleted"]) == 5 and all(not Path(i["display_path"]).exists()
                                             for i in done["deleted"])
    assert extra.exists(), "凍結した一覧に無い枚を消した（§8.1 の 14）"
    assert where(store, extra_id)["missing_at"] is None
    # **凍結した一覧そのもの**は読める（`GET` は書かない）
    shown = svc.preview_of(got["preview_id"])
    assert shown["count"] == 5 and shown["executed_at"] and shown["result"]["count"] == 5
    assert {i["asset_id"] for i in shown["items"]} == set(ids)
    assert where(store, extra_id)["missing_at"] is None


def test_the_execute_skips_the_changed_item_and_deletes_the_rest(svc, store, library):
    """壊すと落ちる: `skipped` を返さず**全体を止める**（§8.1 の 15）・差し替えた物を消す（線 8）。"""
    ids, paths = [], []
    for i in range(5):
        path = make_png(library / f"mix{i}.png", seed=40 + i)
        ids.append(add_asset(store, path))
        paths.append(path)
    got = svc.bulk_preview(scope={"kind": "assets", "asset_ids": ids}, stage=2, actor="human")
    make_png(paths[2], seed=77, size=(32, 32))          # 1 件だけ差し替える
    done = svc.bulk_delete(preview_id=got["preview_id"], confirm=True, actor="human",
                           confirm_last_copy=True)
    assert done["count"] == 4, done
    assert [s["reason"] for s in done["skipped"]] == ["changed"], done["skipped"]
    assert paths[2].exists(), "差し替えた 1 件を消した"
    assert sum(1 for p in paths if not p.exists()) == 4


def test_an_expired_preview_deletes_nothing(svc, store, library, clock):
    """壊すと落ちる: `expires_at` を見ない（§8.1 の 13）・失効後も消す（§1.2 の線 8）。"""
    path = make_png(library / "exp.png", seed=50)
    asset_id = add_asset(store, path)
    got = svc.bulk_preview(scope={"kind": "assets", "asset_ids": [asset_id]}, stage=3,
                           actor="human")
    clock.advance(sec=601)                              # 凍結は壁時計（10 分）
    with pytest.raises(ReviewError) as err:
        svc.bulk_delete(preview_id=got["preview_id"], confirm=True, actor="human",
                        confirm_last_copy=True)
    assert err.value.status == 409 and err.value.code == "preview_expired"
    assert path.exists(), "失効した一覧で消した"
    assert store.con.execute("SELECT count(*) AS n FROM deletion_log").fetchone()["n"] == 0
    assert store.con.execute("SELECT executed_at FROM pending_delete_preview WHERE id = ?",
                             (got["preview_id"],)).fetchone()["executed_at"] is None


def test_bulk_last_copy_needs_the_confirmation(svc, store, library):
    """壊すと落ちる: 一括で `last_copy` を見ない（§3.2。**1 枚も消さない**）。"""
    path = make_png(library / "last.png", seed=51)
    asset_id = add_asset(store, path)
    got = svc.bulk_preview(scope={"kind": "assets", "asset_ids": [asset_id]}, stage=3,
                           actor="human")
    assert got["last_copies"] == 1
    with pytest.raises(ReviewError) as err:
        svc.bulk_delete(preview_id=got["preview_id"], confirm=True, actor="human")
    assert err.value.status == 409 and err.value.code == "last_copy"
    assert path.exists()
    done = svc.bulk_delete(preview_id=got["preview_id"], confirm=True, actor="human",
                           confirm_last_copy=True)
    assert done["count"] == 1


def test_the_same_preview_is_never_executed_twice(svc, store, library):
    """壊すと落ちる: 実行後に行を消す／`executed_at` を見ない（§0.16 A2・§4.3）。"""
    path = make_png(library / "twice.png", seed=52)
    asset_id = add_asset(store, path)
    got = svc.bulk_preview(scope={"kind": "assets", "asset_ids": [asset_id]}, stage=2,
                           actor="human")
    first = svc.bulk_delete(preview_id=got["preview_id"], confirm=True, actor="human",
                            confirm_last_copy=True)
    assert first["count"] == 1
    second = svc.bulk_delete(preview_id=got["preview_id"], confirm=True, actor="human",
                             confirm_last_copy=True)
    assert second["replayed"] is True and second["count"] == 1
    assert store.con.execute("SELECT count(*) AS n FROM deletion_log").fetchone()["n"] == 1, \
        "同じ凍結を 2 回消した"


def test_the_folder_and_query_scopes_freeze_what_matches(svc, store, library, tmp_path):
    """`scope` の 4 つの形（専門 §3.5 の選び方）。`folder` は下の全部、`query` は絞り込み。"""
    a = make_png(library / "sc1.png", seed=60)
    b = make_png(library / "sc2.png", seed=61)
    ids = [add_asset(store, a), add_asset(store, b)]
    folder = svc.bulk_preview(scope={"kind": "folder", "id": str(library)}, stage=1,
                              actor="human")
    assert folder["count"] == 2
    query = svc.bulk_preview(scope={"kind": "query", "q": "sc1"}, stage=1, actor="human")
    assert query["count"] == 1 and query["items"][0]["asset_id"] == ids[0]
    with pytest.raises(ReviewError) as err:
        svc.bulk_preview(scope={"kind": "nonsense"}, stage=1, actor="human")
    assert err.value.status == 422 and err.value.code == "bad_scope"


# ---- 上限（エージェントは 200 枚・人は上限なし）----


def test_the_agent_limit_is_two_hundred_and_nothing_is_deleted(svc, store, library):
    """壊すと落ちる: 上限を外す・**部分適用**にする（§8.1 の 30・31。§8.4 F3）。

    **エージェントは 201 枚で 422 `too_many` で 1 枚も消さない。** 人には上限が無い（点検 B1）。
    """
    ids = []
    for i in range(201):
        path = make_png(library / f"many{i:03d}.png", seed=i, size=(8, 8))
        ids.append(add_asset(store, path))
    with pytest.raises(ReviewError) as err:
        svc.bulk_preview(scope={"kind": "assets", "asset_ids": ids}, stage=1, actor="agent")
    assert err.value.status == 422 and err.value.code == "too_many"
    assert store.con.execute("SELECT count(*) AS n FROM pending_delete_preview"
                             ).fetchone()["n"] == 0, "422 なのに凍結を作っている"
    ok = svc.bulk_preview(scope={"kind": "assets", "asset_ids": ids}, stage=1, actor="human")
    assert ok["count"] == 201, "人に上限が掛かっている（点検 B1）"
    # **200 枚は通る**（境界）
    exactly = svc.bulk_preview(scope={"kind": "assets", "asset_ids": ids[:AGENT_MAX_BATCH]},
                               stage=1, actor="agent")
    assert exactly["count"] == AGENT_MAX_BATCH
    # **実行の段で 201 件が来ても 1 枚も消さない**（§8.4 F3。preview を迂回した場合）
    frozen = [{"asset_id": ids[i], "path": where(store, ids[i])["path"],
               "display_path": str(library / f"many{i:03d}.png"), "size": 1, "mtime_ns": 1}
              for i in range(201)]
    with store.transaction() as con:
        con.execute("INSERT INTO pending_delete_preview(id, stage, scope_json, items_json,"
                    " count, bytes, actor, created_at, expires_at)"
                    " VALUES ('sneaky', 2, '{}', ?, 201, 201, 'agent', 't', '2999-01-01T00:00:00Z')",
                    (json.dumps(frozen),))
    with pytest.raises(ReviewError) as err2:
        svc.bulk_delete(preview_id="sneaky", confirm=True, actor="agent")
    assert err2.value.status == 422 and err2.value.code == "too_many"
    assert store.con.execute("SELECT count(*) AS n FROM deletion_log").fetchone()["n"] == 0, \
        "422 なのに 200 枚だけ消した（部分適用）"
    assert all((library / f"many{i:03d}.png").exists() for i in range(201))


# ---- client_token（二重に消さない）----


def test_the_same_client_token_returns_the_same_result(svc, store, library):
    """壊すと落ちる: `delete_request` の部分索引を外す（§8.1 の 3）・2 回消す（§8.4 F1）。"""
    path = make_png(library / "tok.png", seed=70)
    asset_id = add_asset(store, path)
    first = svc.delete(asset_id=asset_id, path=str(path), stage=1, actor="human",
                       client_token="tok-1")
    assert first["replayed"] is False
    again = svc.delete(asset_id=asset_id, path=str(path), stage=1, actor="human",
                       client_token="tok-1")
    assert again["replayed"] is True and again["deletion_id"] == first["deletion_id"]
    assert store.con.execute("SELECT count(*) AS n FROM deletion_log").fetchone()["n"] == 1, \
        "同じ token の再送でもう一度消した"
    with pytest.raises(ReviewError) as err:              # **違う内容**の再送は気づく
        svc.delete(asset_id=asset_id, path=str(path), stage=2, actor="human",
                   client_token="tok-1")
    assert err.value.status == 409 and err.value.code == "client_token_conflict"
    assert path.exists(), "取り違えた token で別の段を実行した"


def test_the_same_client_token_in_the_bulk(svc, store, library):
    """壊すと落ちる: 一括で `client_token` を行に持たせる（2 行目で UNIQUE に当たる。§8.1 の 3）。"""
    ids = []
    for i in range(3):
        path = make_png(library / f"btok{i}.png", seed=80 + i)
        ids.append(add_asset(store, path))
    got = svc.bulk_preview(scope={"kind": "assets", "asset_ids": ids}, stage=1, actor="human")
    first = svc.bulk_delete(preview_id=got["preview_id"], confirm=True, actor="human",
                            client_token="bulk-1", confirm_last_copy=True)
    assert first["count"] == 3
    again = svc.bulk_delete(preview_id=got["preview_id"], confirm=True, actor="human",
                            client_token="bulk-1", confirm_last_copy=True)
    assert again["replayed"] is True and again["count"] == 3
    assert store.con.execute("SELECT count(*) AS n FROM deletion_log").fetchone()["n"] == 3


def test_two_threads_with_the_same_token_make_one_deletion(svc, store, library):
    """壊すと落ちる: 同じ token の**同時**要求で 2 回消す（§8.4 F10）。

    サービスは操作を錠で直列化するので、1 本が新規・1 本が写しになり、**台帳の行は 1 つ**。
    """
    path = make_png(library / "race.png", seed=90)
    asset_id = add_asset(store, path)
    barrier = threading.Barrier(2)
    out: list[dict] = []
    errors: list[BaseException] = []

    def run() -> None:
        try:
            barrier.wait(timeout=10)
            out.append(svc.delete(asset_id=asset_id, path=str(path), stage=1, actor="human",
                                  client_token="race-1"))
        except BaseException as exc:                     # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=run) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=20)
    assert not errors, errors
    assert len(out) == 2
    assert sum(1 for r in out if r.get("replayed")) == 1, out
    assert store.con.execute("SELECT count(*) AS n FROM deletion_log").fetchone()["n"] == 1


# ---- 読み（`GET` は 1 バイトも書かない）----


def test_get_never_writes(svc, store, library, clock):
    """壊すと落ちる: `GET` で `remaining_sec` を減らす（§8.1 の 18）・何かを書く（家風）。"""
    path = make_png(library / "get.png", seed=91)
    asset_id = add_asset(store, path)
    svc.delete(asset_id=asset_id, path=str(path), stage=3, actor="human",
               confirm_last_copy=True)
    tables = [r["name"] for r in store.con.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY name")]

    def snapshot():
        counts = tuple(store.con.execute(f"SELECT count(*) AS n FROM {t}").fetchone()["n"]
                       for t in tables)
        cells = tuple(store.con.execute("SELECT id, remaining_sec, purge_at, restored_at"
                                        " FROM deletion_log ORDER BY id").fetchall())
        files = tuple(sorted((str(p.relative_to(store.data_dir)), p.stat().st_size,
                              p.stat().st_mtime_ns)
                             for p in store.data_dir.rglob("*") if p.is_file()))
        return counts, tuple(tuple(c) for c in cells), files

    before = snapshot()
    clock.advance(sec=600, mono=600)                 # 時計を進めても `GET` は書かない
    svc.pending(actor="human")
    svc.ledger(actor="human")
    svc.trash(actor="human")
    assert snapshot() == before, "GET が書いている（行数・残り時間・ファイルのどれかが変わった）"
    left = store.con.execute("SELECT remaining_sec FROM deletion_log").fetchone()["remaining_sec"]
    assert left == 300, f"GET で残り時間が減った（{left}）"


def test_get_of_a_frozen_preview_does_not_write_either(svc, store, library):
    """凍結した一覧の `GET` も書かない（`GET` は 1 バイトも書かない。家風）。"""
    path = make_png(library / "getp.png", seed=92)
    asset_id = add_asset(store, path)
    got = svc.bulk_preview(scope={"kind": "assets", "asset_ids": [asset_id]}, stage=1,
                           actor="human")
    before = tuple(store.con.execute("SELECT * FROM pending_delete_preview").fetchall())
    shown = svc.preview_of(got["preview_id"])
    assert shown["count"] == 1 and shown["executed_at"] is None and shown["expired"] is False
    assert tuple(store.con.execute("SELECT * FROM pending_delete_preview").fetchall()) == before


# ---- 口（§3.2〜§3.4）----


def register(client, tmp_path: Path, name: str, *, seed: int = 1, stage3: bool = True):
    """口の試験の下ごしらえ（**アプリの store に**実体つきで 1 枚登録する）。"""
    store = client.app.state.store
    library = tmp_path / "httplib"
    library.mkdir(parents=True, exist_ok=True)
    if stage3:
        root_with_stage3(store, library)
    path = make_png(library / name, seed=seed)
    return store, path, add_asset(store, path)


def test_the_delete_endpoints_work_end_to_end(client, tmp_path):
    """線 5〜7 の口の往復: 段 1 → 段 3 → 取り消し（**サービス直呼びではなく HTTP で**）。"""
    store, path, asset_id = register(client, tmp_path, "api.png")
    # 凍結した一覧は読める（**実行時に評価し直さない**ことの確認用）。先に作っておく
    prev = client.post("/api/locations/bulk-delete/preview", headers=HUMAN,
                       json={"scope": {"kind": "assets", "asset_ids": [asset_id]}, "stage": 2})
    assert prev.status_code == 200, prev.text
    preview_id = prev.json()["preview_id"]
    shown = client.get(f"/api/deletions/previews/{preview_id}", headers=HUMAN).json()
    assert shown["count"] == 1 and shown["expired"] is False
    assert client.get("/api/deletions/previews/nope", headers=HUMAN).status_code == 404
    got = client.post("/api/locations/delete", headers=HUMAN,
                      json={"asset_id": asset_id, "path": str(path), "stage": 3,
                            "confirm_last_copy": True, "reason": "要らない"})
    assert got.status_code == 200, got.text
    body = got.json()
    assert body["stage"] == 3 and body["remaining_sec"] == 300 and body["replayed"] is False
    pend = client.get("/api/pending-deletes", headers=HUMAN).json()
    assert pend["count"] == 1 and pend["items"][0]["remaining_sec"] == 300
    assert pend["items"][0]["actor"] == "human" and pend["items"][0]["mine"] is True
    # 別名の口（実装の指示書の名前）でも同じ物が返る
    alias = client.get("/api/deletions/trash", headers=HUMAN).json()
    assert alias["count"] == 1
    led = client.get("/api/deletions", headers=HUMAN).json()
    assert led["count"] == 1 and led["items"][0]["state"] == "pending"
    # 取り消し（指示書の名前の口）
    back = client.post(f"/api/deletions/{body['deletion_id']}/undo", headers=HUMAN, json={})
    assert back.status_code == 200 and back.json()["restored"] is True
    assert path.exists()
    assert client.get("/api/pending-deletes", headers=HUMAN).json()["count"] == 0


def test_the_bulk_endpoints_work_end_to_end(client, tmp_path):
    """凍結 → 実行（口の往復）と、**失効したら何も消えない**こと。"""
    store = client.app.state.store
    library = tmp_path / "httplib2"
    library.mkdir(parents=True, exist_ok=True)
    root_with_stage3(store, library)
    paths = [make_png(library / f"bulk{i}.png", seed=100 + i) for i in range(3)]
    ids = [add_asset(store, p) for p in paths]
    prev = client.post("/api/locations/bulk-delete/preview", headers=HUMAN,
                       json={"scope": {"kind": "assets", "asset_ids": ids}, "stage": 2})
    assert prev.status_code == 200, prev.text
    got = prev.json()
    assert got["count"] == 3 and got["bytes"] > 0 and got["last_copies"] == 3
    # **最後の 1 つが 3 枚なので、確認なしでは 409**（1 枚も消さない。§3.4 の `last_copy`）
    refused = client.post("/api/locations/bulk-delete", headers=HUMAN,
                          json={"preview_id": got["preview_id"], "confirm": True})
    assert refused.status_code == 409 and refused.json()["code"] == "last_copy"
    assert all(p.exists() for p in paths)
    done = client.post("/api/locations/bulk-delete", headers=HUMAN,
                       json={"preview_id": got["preview_id"], "confirm": True,
                             "confirm_last_copy": True})
    assert done.status_code == 200, done.text
    assert done.json()["count"] == 3 and done.json()["skipped"] == []
    trash = client.get("/api/trash", headers=HUMAN).json()
    assert trash["count"] == 3 and len(trash["days"]) == 1
    assert sum(d["count"] for d in trash["days"]) == 3
    # ゴミ箱から戻す（**人だけ**）
    deletion_ids = [i["id"] for d in trash["days"] for i in d["items"]]
    first = client.post("/api/trash/restore", headers=HUMAN, json={"deletion_id": deletion_ids[0]})
    assert first.status_code == 200 and first.json()["restored"] is True
    assert client.post("/api/trash/restore", headers=AGENT,
                       json={"deletion_id": deletion_ids[1]}).status_code == 403
    # **confirm が無ければ 422**（押し間違いを防ぐ）
    prev2 = client.post("/api/locations/bulk-delete/preview", headers=HUMAN,
                        json={"scope": {"kind": "assets", "asset_ids": [ids[1]]}, "stage": 2}).json()
    assert client.post("/api/locations/bulk-delete", headers=HUMAN,
                       json={"preview_id": prev2["preview_id"]}).status_code == 422


def test_the_deletion_endpoints_are_guarded(client, tmp_path):
    """家風: 新しい口は `Host` / `Content-Type` / 語彙で守る（403 / 422）。"""
    store, path, asset_id = register(client, tmp_path, "guard.png")
    body = {"asset_id": asset_id, "path": str(path), "stage": 1}
    assert client.post("/api/locations/delete", json=body,
                       headers={"Host": "evil", **HUMAN}).status_code == 403
    assert client.post("/api/locations/delete", content=json.dumps(body),
                       headers={"Content-Type": "text/plain", **HUMAN}).status_code == 403
    assert client.post("/api/locations/delete", json=body,
                       headers={"X-Image-Reviewer-Actor": "robot"}).status_code == 422
    bad = client.post("/api/locations/delete", headers=HUMAN,
                      json={"asset_id": asset_id, "path": str(path), "stage": 4})
    assert bad.status_code == 422 and bad.json()["code"] == "bad_stage"
    assert client.get("/api/deletions?limit=0", headers=HUMAN).status_code == 422
    assert client.get("/api/deletions?limit=99999", headers=HUMAN).status_code == 422
    # **削除はエージェントにも許す**（Q2。`require_human` を掛けていない）
    ok = client.post("/api/locations/delete", headers=AGENT, json=body)
    assert ok.status_code == 200, ok.text
    assert ok.json()["actor"] == "agent"
    # **`as_copy` は人だけ**（403 human_only）
    assert client.post(f"/api/deletions/{ok.json()['deletion_id']}/undo", headers=AGENT,
                       json={"as_copy": True}).status_code == 403
    # **「いま消す」は人だけ**（confirm も要る）
    assert client.post("/api/deletions/x/purge", headers=AGENT,
                       json={"confirm": True}).status_code == 403
    assert client.post(f"/api/deletions/{ok.json()['deletion_id']}/purge", headers=HUMAN,
                       json={}).status_code == 422


def test_the_purge_endpoint_finishes_a_stuck_row(client, tmp_path):
    """「いま消す」の導線（§5 の画面。設計の口の表に無かったので足した。申し送り参照）。"""
    store, path, asset_id = register(client, tmp_path, "purge.png")
    got = client.post("/api/locations/delete", headers=HUMAN,
                      json={"asset_id": asset_id, "path": str(path), "stage": 3,
                            "confirm_last_copy": True}).json()
    path.write_bytes(b"occupied")                     # 戻せない状態を作る
    assert client.post(f"/api/deletions/{got['deletion_id']}/undo", headers=HUMAN,
                       json={}).status_code == 409
    assert store.con.execute("SELECT purge_at FROM deletion_log WHERE id = ?",
                             (got["deletion_id"],)).fetchone()["purge_at"] is None
    done = client.post(f"/api/deletions/{got['deletion_id']}/purge", headers=HUMAN,
                       json={"confirm": True})
    assert done.status_code == 200 and done.json()["purged"] is True
    assert not Path(got["hold_path"]).exists()
    assert store.con.execute("SELECT count(*) AS n FROM asset_location WHERE asset_id = ?",
                             (asset_id,)).fetchone()["n"] == 0


def test_the_list_hides_deleted_assets_and_include_deleted_shows_them(client, tmp_path):
    """壊すと落ちる: `deleted_at` を一覧の既定で出す（§8.1 の 25。段 1 の意味が消える）。"""
    store, path, asset_id = register(client, tmp_path, "hide.png")
    other_path = path.parent / "hide2.png"
    make_png(other_path, seed=7)
    other_id = add_asset(store, other_path)
    assert client.get("/api/assets", headers=HUMAN).json()["total"] == 2
    client.post("/api/locations/delete", headers=HUMAN,
                json={"asset_id": asset_id, "path": str(path), "stage": 1})
    listed = client.get("/api/assets", headers=HUMAN).json()
    assert listed["total"] == 1 and listed["items"][0]["id"] == other_id, listed
    shown = client.get("/api/assets?include_deleted=1", headers=HUMAN).json()
    assert shown["total"] == 2 and {i["id"] for i in shown["items"]} == {asset_id, other_id}
    assert client.get("/api/assets?include_deleted=x", headers=HUMAN).status_code == 422
    # **判断は消えない**: 段 1 の印を立てても `/api/assets/{id}` は引ける
    assert client.get(f"/api/assets/{asset_id}", headers=HUMAN).status_code == 200


def test_frees_says_when_the_space_comes_back():
    """壊すと落ちる: 段 1 でも「空く」と出す（§8.1 の 16。利用者が「空きが増えない」と混乱）。"""
    assert frees_for(1, size=1000, window_sec=300, at="x")["bytes"] == 0
    assert frees_for(1, size=1000, window_sec=300, at="x")["at"] is None
    assert frees_for(2, size=1000, window_sec=300, at="x")["bytes"] == 1000
    assert "ゴミ箱" in frees_for(2, size=1000, window_sec=300, at="x")["note"]
    three = frees_for(3, size=1000, window_sec=300, at="2026-01-01T00:05:00Z")
    assert three["bytes"] == 1000 and three["at"] == "2026-01-01T00:05:00Z"
    assert "5 分" in three["note"] and "アプリが動いていた" in three["note"]


# ---- 移行（v6 の列。**古い v6 の実データでも動く**）----


def test_the_v6_columns_are_topped_up_on_an_old_database(tmp_path):
    """壊すと落ちる: `pending_delete_preview` の列を `_top_up_v6` で足さない。

    実データの v6 は `executed_at` / `result_json` / `request_id` の**無い形**で先に作ってある。
    足さないと**一括削除が `no such column: executed_at` で丸ごと落ちる**（`migrate()` は
    `current >= 6` で早期に戻るので、`_migrate_v6` は通らない）。
    """
    con = db.open_db(tmp_path)
    try:
        cols = {r["name"] for r in con.execute("PRAGMA table_info(pending_delete_preview)")}
        assert {"executed_at", "result_json", "request_id"} <= cols, cols
        assert "payload_json" in {r["name"] for r in con.execute(
            "PRAGMA table_info(delete_request)")}
        for name in ("executed_at", "result_json", "request_id"):
            con.execute(f"ALTER TABLE pending_delete_preview DROP COLUMN {name}")
        con.execute("ALTER TABLE delete_request DROP COLUMN payload_json")
        assert db.migrate(con) == 6                      # 早期 return の道で補う
        cols = {r["name"] for r in con.execute("PRAGMA table_info(pending_delete_preview)")}
        assert {"executed_at", "result_json", "request_id"} <= cols
        assert db.migrate(con) == 6                      # 二度足さない（何度でも同じ）
        db.integrity(con)
    finally:
        con.close()
