"""削除の 3 段階と 5 分の窓（P8-2）のテスト。

設計: `docs/p8-design.md` §0.6（3 段階と窓）・§0.7（凍結 → 実行）・§3.2〜§3.4（口）・
      §4（状態）・§8.1 / §8.4（壊すと落ちる）

**何を壊すと落ちるか**を各テストの docstring に書いてある（家風）。
**時計は注入する**（`Clock` を 1 つだけ。`time.monotonic()` を直接呼ばない。§8 の末尾）。
"""

from __future__ import annotations

import calendar
import hashlib
import json
import os
import shutil
import sqlite3
import stat
import threading
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from image_reviewer import db, deletions
from image_reviewer.deletions import (AGENT_MAX_BATCH, DEFAULT_UNDO_WINDOW_SEC, HOLD_DIR,
                                      HOLD_PURGED, PREVIEW_KEEP_SEC, TRASH_DIR, DeletionService,
                                      free_name, frees_for, move_no_clobber)
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
    # **（D-17）タイマーの周期を 1 時間にする。** 既定の 30 秒のままだと、テストが数秒で
    # 終わるので普通は当たらないが、遅い環境で当たると `remaining_sec` が理由もなく減る
    # （`start()` は張る＝本番と同じ道を通す）
    app.state.deletions.interval = 3600.0
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


def test_a_human_can_undo_anyones_deletion_and_an_agent_only_their_own(svc, store, library):
    """壊すと落ちる: **人がエージェントの削除を戻せない**（C-1・§0.14 の帰結 e・設計 §8.4 F9）。

    エージェントが消した物に人が気づいて戻せるのがこの段の安全網なので、**人には `not_yours` を
    掛けない**。**エージェントは自分の分だけ**（他人の分は 403 `not_yours`）。
    **`as_copy` は人だけ**（エージェントは 403 `human_only`）。
    """
    path = make_png(library / "h.png", seed=12)
    asset_id = add_asset(store, path)
    got = svc.delete(asset_id=asset_id, path=str(path), stage=3, actor="agent",
                     confirm_last_copy=True)
    # **エージェントは人の削除を戻せない**（`mine` の規則はエージェントにだけ掛かる）
    human_made = make_png(library / "h2.png", seed=112)
    human_id = add_asset(store, human_made)
    by_human = svc.delete(asset_id=human_id, path=str(human_made), stage=3, actor="human",
                          confirm_last_copy=True)
    with pytest.raises(ReviewError) as err:
        svc.undo(by_human["deletion_id"], actor="agent")
    assert err.value.status == 403 and err.value.code == "not_yours"
    assert not human_made.exists(), "403 なのにファイルが戻っている"
    # **人は誰の削除でも戻せる**（エージェントが消した物も）
    ok = svc.undo(got["deletion_id"], actor="human")
    assert ok["restored"] is True and path.exists(), "人がエージェントの削除を戻せない（C-1）"
    # **`as_copy` は人だけ**
    with pytest.raises(ReviewError) as err2:
        svc.undo(by_human["deletion_id"], as_copy=True, actor="agent")
    assert err2.value.status == 403 and err2.value.code == "human_only"
    back = svc.undo(by_human["deletion_id"], actor="human")
    assert back["restored"] is True and human_made.exists(), "人が自分の削除を戻せない"


def test_the_pending_list_marks_who_deleted_it(svc, store, library):
    """壊すと落ちる: `actor` を記録しない・返さない（Q2 の帰結 a・b。§8.1 の 28）・
    人が他人の削除に「戻す」を押せない（C-1）。"""
    path = make_png(library / "i.png", seed=13)
    asset_id = add_asset(store, path)
    svc.delete(asset_id=asset_id, path=str(path), stage=3, actor="agent",
               confirm_last_copy=True)
    mine = svc.pending(actor="agent")["items"][0]
    theirs = svc.pending(actor="human")["items"][0]
    assert mine["actor"] == "agent" and mine["mine"] is True and mine["undoable"] is True
    assert theirs["mine"] is False
    assert theirs["undoable"] is True, "人が他人（エージェント）の削除を戻せない（C-1）"


def test_the_pending_list_shows_the_stage1_and_stage2_rows_too(svc, store, library, clock):
    """壊すと落ちる: `GET /api/pending-deletes` を**段 3 だけ**にする（**P8-3 の監査 C-2**）。

    `frontend-design.md` §4.6 は「**1 行 = `deletion_log` の 1 行**」と決めている。段 1 で
    カタログから外しただけの行がここに出ないと、**画面で実行できるのに戻す押し先が無い**
    （`undo` は元から段 1〜3 に効く）。段 1・2 の行は `state` が `hidden` / `trashed` のまま
    `undoable: true` で出る（人が押せば戻る）。

    並びは**窓のある段 3 が先・窓の無い段 1・2 は新しい順**（§11）。
    """
    first = make_png(library / "p1.png", seed=31)
    a1 = add_asset(store, first)
    one = svc.delete(asset_id=a1, path=str(first), stage=1, actor="human")
    clock.advance(sec=1)                                   # `at` を分ける（並びを決定的にする）
    second = make_png(library / "p2.png", seed=32)
    a2 = add_asset(store, second)
    two = svc.delete(asset_id=a2, path=str(second), stage=2, actor="human")
    pend = svc.pending(actor="human")
    assert [i["state"] for i in pend["items"]] == ["trashed", "hidden"], \
        [i["state"] for i in pend["items"]]
    assert [i["stage"] for i in pend["items"]] == [2, 1]
    assert all(i["undoable"] for i in pend["items"]), "段 1・2 の行に戻す押し先が無い（C-2）"
    assert pend["count"] == 2 and pend["pending"] == 0
    # 段 1 は**ファイルを動かさない**。戻すと `deleted_at` が消えて一覧に戻る
    svc.undo(one["deletion_id"], actor="human")
    assert first.exists() and not second.exists()
    assert store.con.execute("SELECT deleted_at FROM asset WHERE id = ?",
                             (a1,)).fetchone()["deleted_at"] is None
    # 段 2 も**同じ口**で戻せる（`trash_restore` は人だけだが、窓の無い段 2 にも `undo` が効く）
    svc.undo(two["deletion_id"], actor="human")
    assert second.exists()
    assert svc.pending(actor="human")["count"] == 0, "戻したのに一覧から消えていない"


def test_the_pending_list_puts_the_window_rows_first_by_remaining_time(svc, store, library,
                                                                      clock):
    """壊すと落ちる: 並びを**新しい順**だけにする（§11「残り時間の短い順」）。

    段 1 の行（窓が無い）を先に作り、そのあとに段 3 の行を作る。**新しい順だと段 1 が先頭**に
    来てしまうので、窓のある段 3 が先に来ることを見る。段 3 が 2 つあるときは**残り時間の
    短い順**。
    """
    old = make_png(library / "q1.png", seed=41)
    a1 = add_asset(store, old)
    svc.delete(asset_id=a1, path=str(old), stage=1, actor="human")
    clock.advance(sec=1)
    live = make_png(library / "q2.png", seed=42)
    a2 = add_asset(store, live)
    got = svc.delete(asset_id=a2, path=str(live), stage=3, actor="human",
                     confirm_last_copy=True)
    clock.advance(sec=1)
    late = make_png(library / "q3.png", seed=43)
    a3 = add_asset(store, late)
    other = svc.delete(asset_id=a3, path=str(late), stage=3, actor="human",
                       confirm_last_copy=True)
    with store.transaction() as con:                       # 片方だけ残り時間を短くする
        con.execute("UPDATE deletion_log SET remaining_sec = 10 WHERE id = ?",
                    (got["deletion_id"],))
    items = svc.pending(actor="human")["items"]
    assert [i["state"] for i in items] == ["pending", "pending", "hidden"], \
        [i["state"] for i in items]
    assert items[0]["id"] == got["deletion_id"], "残り時間の短い順になっていない"
    assert items[0]["remaining_sec"] == 10 and items[1]["id"] == other["deletion_id"]
    assert items[2]["remaining_sec"] is None, "窓の無い行に残り時間を出している"


def test_the_stuck_reason_says_why_it_could_not_go_back(svc, store, library, clock, tmp_path):
    """壊すと落ちる: 戻せなかった**理由を残さない**（**P8-3 の監査 G-3**）。

    理由を残さないと、`target_exists`（元の場所が埋まっているだけ）にも
    「保留していたファイルが見つかりません」と出て、**利用者が次に何をすればよいか分からない**。
    4 通り（`target_exists` / `move_failed` / `different` / `missing`）を台帳に残す。
    語彙はサービス層でも守る（`CHECK` に当てて 500 にしない。家風）。

    **（3）の前提は「登録と `(size, mtime_ns)` が違う」こと**（`os.utime` で決定的にする）。
    `_original_state` は `(size, mtime_ns)` で見る（P8-2 の監査 D-2）ので、**同じ大きさの
    差し替えが同じ `mtime_ns` に落ちると `same` と読む**——それは §8.4 F4 の「規則の限界」
    （`test_the_limit_of_the_rule_a_same_size_swap_is_not_detected`）。**書き直しは登録の
    0.3 ms 後**（実測 15 回で 290,000〜375,000 ns）で、この機械のファイル時刻の刻み
    （0.5〜1 ms 程度）より短いので、**20 回中 15 回で `mtime_ns` が同じになった**
    （時計の刻みに頼るとこのテストが揺れる）。
    """
    # (1) 元の場所が埋まっている（`target_exists`）
    blocked = make_png(library / "r1.png", seed=51)
    a1 = add_asset(store, blocked)
    one = svc.delete(asset_id=a1, path=str(blocked), stage=3, actor="human",
                     confirm_last_copy=True)
    blocked.write_bytes(b"someone else")
    with pytest.raises(ReviewError) as err:
        svc.undo(one["deletion_id"], actor="human")
    assert err.value.code == "target_exists"
    row = svc.pending(actor="human")["items"][0]
    assert row["state"] == "stuck" and row["stuck_reason"] == "target_exists", row
    assert row["needs_as_copy"] is True, "「別名で戻す」を出せない"
    # (2) 元のフォルダが無い（`move_failed`）
    clock.advance(sec=1)                                   # 台帳の `at` を分ける（並びを決定的に）
    nested = library / "sub"
    gone = make_png(nested / "r2.png", seed=52)
    a2 = add_asset(store, gone)
    two = svc.delete(asset_id=a2, path=str(gone), stage=3, actor="human",
                     confirm_last_copy=True)
    nested.rmdir()
    with pytest.raises(ReviewError) as err2:
        svc.undo(two["deletion_id"], actor="human")
    assert err2.value.code == "move_failed"
    assert svc.ledger(actor="human")["items"][0]["stuck_reason"] == "move_failed"
    # (3) 保留の実体が無く、元の場所には**別のファイル**（`different`。窓切れの後始末の道）
    clock.advance(sec=1)
    swapped = make_png(library / "r3.png", seed=53)
    registered = swapped.stat()                            # 登録される値（`add_asset` が見る物）
    a3 = add_asset(store, swapped)
    three = svc.delete(asset_id=a3, path=str(swapped), stage=3, actor="human",
                       confirm_last_copy=True)
    Path(three["hold_path"]).unlink()
    make_png(swapped, seed=54)                             # 登録した物とは違う中身（同じ大きさ）
    # **`mtime_ns` を明示して登録の値と違える。** 書き直しは登録の 0.3 ms 後（実測）で、
    # この機械のファイル時刻の刻み（0.5〜1 ms 程度）より短いため、**20 回中 15 回で
    # 登録と同じ `mtime_ns` に落ちた**。その形は §8.4 F4 の「規則の限界」
    # （`test_the_limit_of_the_rule_a_same_size_swap_is_not_detected`）そのもので、
    # **`same` と読むのが設計どおり**（`_original_state` は `(size, mtime_ns)` で見る。
    # P8-2 の監査 D-2）。ここで見たいのは `different` の道なので、前提を決定的にする。
    os.utime(swapped, ns=(registered.st_atime_ns, registered.st_mtime_ns + 1_000_000))
    now = swapped.stat()
    assert (now.st_size, now.st_mtime_ns) != (registered.st_size, registered.st_mtime_ns), \
        "試験の前提（登録と違う (size, mtime_ns)）が崩れている"
    with store.transaction() as con:
        con.execute("UPDATE deletion_log SET remaining_sec = 0 WHERE id = ?",
                    (three["deletion_id"],))
    clock.advance(mono=60)
    svc.tick()
    svc.tick()
    assert svc.ledger(actor="human")["items"][0]["stuck_reason"] == "different"
    # (4) 保留の実体が無く、元の場所にも無い（`missing`）
    clock.advance(sec=1)
    lost = make_png(library / "r4.png", seed=55)
    a4 = add_asset(store, lost)
    four = svc.delete(asset_id=a4, path=str(lost), stage=3, actor="human",
                      confirm_last_copy=True)
    Path(four["hold_path"]).unlink()                       # 保留の実体が消えた（元の場所にも無い）
    with pytest.raises(ReviewError) as err3:
        svc.undo(four["deletion_id"], actor="human")
    assert err3.value.code == "restore_failed"
    assert svc.ledger(actor="human")["items"][0]["stuck_reason"] == "missing"
    # 語彙は 1 か所で守る（知らない語は通さない。古い行の `NULL` は通す）
    assert deletions.stuck_reason_of(None) is None
    with pytest.raises(ValueError):
        deletions.stuck_reason_of("nope")


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


def test_the_hold_area_itself_is_never_removed(svc, store):
    """壊すと落ちる: `_remove_hold` に**保留領域そのもの**を渡すと丸ごと消える（D-1）。

    `is_under(root, root)` は True なので、深さを見ないと `rmtree` が**他の保留を巻き込む**
    （その後の `undo` が `restore_failed` になる）。深さ 1（`<削除ID>/`）と 2（中のファイル）
    だけを許す。
    """
    root = store.data_dir / HOLD_DIR
    one, two = root / "one", root / "two"
    for directory, seed in ((one, 226), (two, 227)):
        directory.mkdir(parents=True, exist_ok=True)
        make_png(directory / "keep.png", seed=seed)
    for bad in (str(root), str(root.parent), str(root / "one" / "deep" / "x.png")):
        with pytest.raises(OSError):
            svc._remove_hold(bad)
    assert (one / "keep.png").exists() and (two / "keep.png").exists(), \
        "保留領域そのものを渡されて他の保留を消した（D-1）"
    svc._remove_hold(str(one / "keep.png"))                     # 深さ 2 は消せる
    assert not (one / "keep.png").exists() and (two / "keep.png").exists()


# ---- 一括（凍結 → 実行）----


def test_the_preview_freezes_the_list_and_only_that_list_is_deleted(svc, store, library):
    """壊すと落ちる: 実行時に `scope` を評価し直す（§8.1 の 14。**見せていないファイルを消す**）。

    **フォルダで選ぶ**（実行時に引き直すと、凍結の後で増えた枚が入ってしまう形）。
    凍結の後で同じフォルダに 1 枚足し、**それが消えない**ことを見る。
    **段 3**（最後の 1 つは `confirm_last_copy` が要る。C-4）で回す。
    """
    ids = []
    for i in range(5):
        path = make_png(library / f"bulk{i}.png", seed=30 + i)
        ids.append(add_asset(store, path))
    scope = {"kind": "folder", "id": str(library)}
    got = svc.bulk_preview(scope=scope, stage=3, actor="human")
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
    # **（監査 G-3）口にも `stuck_reason` が出る**（足した欄を 1 回も出さないままにしない。家風）
    assert "stuck_reason" in pend["items"][0] and pend["items"][0]["stuck_reason"] is None
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
    """凍結 → 実行（口の往復）と、**段 3 だけが `confirm_last_copy` を要求する**こと（C-4）。

    段 1・2 は内容が失われない（一覧から外す／ゴミ箱へ移す）ので、**重い確認は要求しない**。
    """
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
    # **（C-4）段 2 は内容が失われないので `confirm_last_copy` は要らない**
    done = client.post("/api/locations/bulk-delete", headers=HUMAN,
                       json={"preview_id": got["preview_id"], "confirm": True})
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
    # **段 3 は最後の 1 つに重い確認が要る**（無ければ 409・1 枚も消さない。C-4）
    alive = [i for i in ids if where(store, i)["missing_at"] is None]
    assert alive, "戻した 1 枚が生きている"
    prev3 = client.post("/api/locations/bulk-delete/preview", headers=HUMAN,
                        json={"scope": {"kind": "assets", "asset_ids": alive}, "stage": 3}).json()
    refused = client.post("/api/locations/bulk-delete", headers=HUMAN,
                          json={"preview_id": prev3["preview_id"], "confirm": True})
    assert refused.status_code == 409 and refused.json()["code"] == "last_copy"
    assert all(Path(i["display_path"]).exists() for i in prev3["items"]), "409 なのに動かした"
    ok3 = client.post("/api/locations/bulk-delete", headers=HUMAN,
                      json={"preview_id": prev3["preview_id"], "confirm": True,
                            "confirm_last_copy": True})
    assert ok3.status_code == 200 and ok3.json()["count"] == len(alive), ok3.text
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


#: **（P8-3 の監査 G-3）列を足す前の `deletion_log`**（`DROP COLUMN` は `CHECK` 付きの列に
#: 使えないので、古い形の表を手で作って「列を見てから足す」道を通す）
OLD_LOG_DDL = """
CREATE TABLE deletion_log (
  id           TEXT PRIMARY KEY,
  asset_id     TEXT,
  path         TEXT,
  stage        INTEGER NOT NULL CHECK (stage IN (1, 2, 3)),
  from_path    TEXT,
  to_path      TEXT,
  hold_path    TEXT,
  remaining_sec INTEGER,
  purge_at     TEXT,
  restored_at  TEXT,
  size         INTEGER,
  request_id   TEXT REFERENCES delete_request(id),
  reason       TEXT,
  actor        TEXT NOT NULL CHECK (actor IN ('human', 'agent')),
  at           TEXT NOT NULL
);
"""


def test_the_stuck_reason_column_is_topped_up_on_an_old_database(tmp_path):
    """壊すと落ちる: `deletion_log.stuck_reason` を `_top_up_v6` で足さない（**監査 G-3**）。

    実データの v6 はこの列が無い形で先に作ってある。足さないと `_mark_unrestorable` が
    `no such column: stuck_reason` で落ち、**取り消しの失敗が 409 ではなく 500 になる**
    （`migrate()` は `current >= 6` で早期に戻るので `_migrate_v6` は通らない）。
    **`CHECK` も DDL と同じ物を付ける**（新規の DB と形が揃う＝語彙は表でも守る）。
    """
    con = db.open_db(tmp_path)
    try:
        con.execute("DROP TABLE deletion_log")
        con.executescript(OLD_LOG_DDL)
        assert "stuck_reason" not in {r["name"] for r in con.execute(
            "PRAGMA table_info(deletion_log)")}
        assert db.migrate(con) == 6                      # 早期 return の道で補う
        assert "stuck_reason" in {r["name"] for r in con.execute(
            "PRAGMA table_info(deletion_log)")}
        con.execute("INSERT INTO deletion_log(id, stage, actor, at)"
                    " VALUES ('x', 3, 'human', 't')")
        with pytest.raises(sqlite3.IntegrityError):
            con.execute("UPDATE deletion_log SET stuck_reason = 'nope' WHERE id = 'x'")
        con.execute("UPDATE deletion_log SET stuck_reason = 'target_exists' WHERE id = 'x'")
        assert db.migrate(con) == 6                      # 二度足さない（何度でも同じ）
        db.integrity(con)
    finally:
        con.close()


# ---- P8-2 の監査の指摘（B-1〜B-3。**失敗の道**。すべて「壊すと落ちる」形）----


def test_the_ledger_row_is_written_before_the_file_moves(svc, store, library, monkeypatch):
    """壊すと落ちる: **移動 → 台帳**の順（B-1）。順序を逆にすると、取引が失敗したときに
    **ファイルだけが移って台帳にも要求にも残らない**迷子になる（一覧には「在る」と出続ける）。
    """
    path = make_png(library / "b1.png", seed=200)
    asset_id = add_asset(store, path)
    seen: dict = {}
    real = deletions.move_no_clobber

    def peek(src, dst):
        row = store.con.execute("SELECT id, hold_path, to_path FROM deletion_log").fetchone()
        seen["row"] = dict(row) if row is not None else None
        seen["src_exists"] = Path(src).exists()
        return real(src, dst)

    monkeypatch.setattr(deletions, "move_no_clobber", peek)
    got = svc.delete(asset_id=asset_id, path=str(path), stage=3, actor="human",
                     confirm_last_copy=True)
    assert seen["row"] is not None, "**移動の前に台帳の行が無い**（B-1 の順序が逆）"
    assert seen["row"]["hold_path"] == got["hold_path"], seen["row"]
    assert seen["row"]["to_path"] is None and seen["src_exists"] is True


def test_a_failed_move_leaves_no_ledger_row_and_no_moved_file(svc, store, library, monkeypatch):
    """壊すと落ちる: 動かせなかったのに**台帳の行を残す**（B-1。「保留に在る」ことになる）。

    動かせなければ行を消し、作った移動先も片づける。ファイルは元の場所のまま・登録も無傷。
    """
    path = make_png(library / "b1b.png", seed=201)
    asset_id = add_asset(store, path)

    def boom(src, dst):
        raise ReviewError(409, "ファイルを移動できません: 試験", code="move_failed")

    monkeypatch.setattr(deletions, "move_no_clobber", boom)
    for stage in (2, 3):
        with pytest.raises(ReviewError) as err:
            svc.delete(asset_id=asset_id, path=str(path), stage=stage, actor="human",
                       confirm_last_copy=True)
        assert err.value.code == "move_failed", err.value.code
    assert path.exists(), "動かせないのにファイルが消えた"
    assert store.con.execute("SELECT count(*) AS n FROM deletion_log").fetchone()["n"] == 0, \
        "動かせなかったのに台帳の行が残っている（迷子の元。B-1）"
    assert store.con.execute("SELECT count(*) AS n FROM delete_request").fetchone()["n"] == 0, \
        "断った要求の行が残っている"
    assert where(store, asset_id)["missing_at"] is None, "動いていないのに参照切れにした"
    for folder in (HOLD_DIR, TRASH_DIR):
        got = store.data_dir / folder
        assert not got.exists() or not any(got.rglob("*")), f"{folder} に空の入れ物が残った"


def test_a_row_whose_move_never_happened_is_recovered_not_purged(svc, store, library, clock):
    """壊すと落ちる: 「移動の前に落ちた行」を、窓切れで**黙って消す**（B-1 の後始末）。

    台帳を先に書く順にしたので、`rename` の前にプロセスが落ちると「台帳は在る・ファイルは
    元の場所」の行が残る。窓が切れても**ファイルも登録も消さない**（戻したことにする）。
    """
    path = make_png(library / "b1c.png", seed=202)
    asset_id = add_asset(store, path)
    hold = store.data_dir / HOLD_DIR / "never-moved" / path.name
    hold.parent.mkdir(parents=True, exist_ok=True)          # フォルダだけ作られた形
    with store.transaction() as con:
        con.execute(
            "INSERT INTO deletion_log(id, asset_id, path, stage, hold_path, remaining_sec,"
            " purge_at, size, actor, at) VALUES ('never-moved', ?, ?, 3, ?, 0,"
            " '2000-01-01T00:00:00Z', ?, 'human', 't')",
            (asset_id, normalize_path(path), str(hold), path.stat().st_size))
    svc.tick()
    svc.tick()                                              # 2 周期目で期限切れを片づける
    assert path.exists(), "ファイルは元の場所に在るのに消した（B-1 の順序で増えた道）"
    assert where(store, asset_id)["missing_at"] is None, "削除は起きていないのに登録を消した"
    row = store.con.execute("SELECT restored_at FROM deletion_log WHERE id = 'never-moved'"
                            ).fetchone()
    assert row["restored_at"], "戻したことにしていない（『取り消せる』に出続ける）"
    # **戻す操作でも同じ**（409 にしない。ファイルは元のまま）
    assert svc.pending(actor="human")["count"] == 0


def test_a_failed_undo_is_not_purged_when_the_window_runs_out(svc, store, library, clock):
    """壊すと落ちる: `move_failed` の行の `purge_at` を残す（B-2・専門 §3.4）。

    元のフォルダが消えた（別プロセスが掴んでいる等）で取り消しが失敗したら、`purge_at` を
    NULL にして自動削除から外す。**窓が尽きても消えない**（利用者は「戻せませんでした」を
    見ているのに、画面は「あと N 分」のまま実体が消える、を防ぐ）。
    """
    nested = library / "sub"
    path = make_png(nested / "b2.png", seed=203)
    asset_id = add_asset(store, path)
    got = svc.delete(asset_id=asset_id, path=str(path), stage=3, actor="human",
                     confirm_last_copy=True)
    nested.rmdir()                                          # **元のフォルダが無くなった**
    with pytest.raises(ReviewError) as err:
        svc.undo(got["deletion_id"], actor="human")
    assert err.value.status == 409 and err.value.code == "move_failed", err.value.code
    row = store.con.execute("SELECT purge_at, restored_at FROM deletion_log WHERE id = ?",
                            (got["deletion_id"],)).fetchone()
    assert row["purge_at"] is None, "失敗したのに purge_at が残っている（窓が尽きると黙って消える）"
    assert row["restored_at"] is None
    assert svc.ledger(actor="human")["items"][0]["state"] == "stuck"
    with store.transaction() as con:                        # 窓を尽きさせる
        con.execute("UPDATE deletion_log SET remaining_sec = 0 WHERE id = ?",
                    (got["deletion_id"],))
    clock.advance(mono=60)
    svc.tick()
    svc.tick()
    assert Path(got["hold_path"]).exists(), "窓が尽きて黙って消えた（B-2）"


def test_the_timer_and_undo_never_lose_the_registration(svc, store, library, clock):
    """壊すと落ちる: `tick` が錠を取らない（B-3。窓の最後の周期の取り消しで登録が消える）。

    実削除の直前で止めた `tick` の間に `undo` を走らせる。**「ファイルは元の場所に在るのに
    `asset_location` の行が無い」**が最悪の形（監査が Event で決定的に再現した）。
    """
    path = make_png(library / "b3.png", seed=204)
    asset_id = add_asset(store, path)
    got = svc.delete(asset_id=asset_id, path=str(path), stage=3, actor="human",
                     confirm_last_copy=True)
    with store.transaction() as con:
        con.execute("UPDATE deletion_log SET remaining_sec = 0 WHERE id = ?",
                    (got["deletion_id"],))
    real = svc._remove_hold
    entered, release = threading.Event(), threading.Event()

    def slow(hold_path):
        entered.set()
        release.wait(timeout=10)
        return real(hold_path)

    svc._remove_hold = slow                                 # **実削除の直前で止める**
    svc.tick()                                              # 1 周期目（実削除はまだ走らない）
    out: list[dict] = []
    errors: list[BaseException] = []

    def undo_it():
        try:
            out.append(svc.undo(got["deletion_id"], actor="human"))
        except BaseException as exc:                        # noqa: BLE001
            errors.append(exc)

    ticker = threading.Thread(target=svc.tick)
    ticker.start()
    assert entered.wait(timeout=10), "実削除の直前まで進まなかった"
    undoer = threading.Thread(target=undo_it)
    undoer.start()
    undoer.join(timeout=1.0)
    assert undoer.is_alive(), "錠を取らずに取り消しが走った（B-3）"
    release.set()
    ticker.join(timeout=10)
    undoer.join(timeout=10)
    at_original = path.exists()
    left = store.con.execute("SELECT count(*) AS n FROM asset_location WHERE asset_id = ?",
                             (asset_id,)).fetchone()["n"]
    assert not (at_original and left == 0), "ファイルは元の場所に在るのに登録が消えた（B-3）"
    if out and out[0].get("restored"):
        assert at_original and left == 1, "戻したと言いながら実体か登録が無い"
    else:
        assert not at_original and left == 0, "実削除が中途半端（ファイルだけ消えた等）"
        # 実削除が先に済んだので、取り消しは 409 で断る（`already_purged` / `restore_failed`）
        assert errors and getattr(errors[0], "code", None) in ("already_purged",
                                                              "restore_failed"), errors


def test_undo_waits_for_the_service_lock(svc, store, library):
    """壊すと落ちる: `undo` の錠を外す（§8.4 X8）。走査（`scan_guard`）と**同じ錠**なので、
    走査が歩いている間に戻ると、走査の最後の `mark_missing` がその枚を参照切れにする（C-6）。
    """
    path = make_png(library / "x8.png", seed=205)
    asset_id = add_asset(store, path)
    got = svc.delete(asset_id=asset_id, path=str(path), stage=3, actor="human",
                     confirm_last_copy=True)
    entered, release = threading.Event(), threading.Event()

    def walk():
        with svc.scan_guard():                              # **走査のつもり**で錠を握る
            entered.set()
            release.wait(timeout=10)

    out: list[dict] = []
    walker = threading.Thread(target=walk)
    walker.start()
    assert entered.wait(timeout=10)
    undoer = threading.Thread(target=lambda: out.append(svc.undo(got["deletion_id"],
                                                                 actor="human")))
    undoer.start()
    undoer.join(timeout=1.0)
    assert undoer.is_alive(), "走査中に取り消しが走った（錠を取っていない）"
    release.set()
    walker.join(timeout=10)
    undoer.join(timeout=10)
    assert out and out[0]["restored"] is True and path.exists()


# ---- P8-2 の監査の指摘（C-2〜C-5。安全規則の穴）----


def test_a_read_only_file_in_the_hold_area_is_still_purged(svc, store, library, clock):
    """壊すと落ちる: `unlink` の前に `S_IWRITE` を立てない（C-2）。

    他のツールが付けた読み取り専用の属性（配布物・バックアップからの復元）があると、
    Windows の `unlink` は `WinError 5` で失敗し、**30 秒ごとにやり直し続ける**。
    """
    path = make_png(library / "c2.png", seed=206)
    asset_id = add_asset(store, path)
    got = svc.delete(asset_id=asset_id, path=str(path), stage=3, actor="human",
                     confirm_last_copy=True)
    hold = Path(got["hold_path"])
    os.chmod(hold, stat.S_IREAD)                            # 読み取り専用の属性
    with store.transaction() as con:
        con.execute("UPDATE deletion_log SET remaining_sec = 0 WHERE id = ?",
                    (got["deletion_id"],))
    svc.tick()
    svc.tick()
    assert not hold.exists(), "読み取り専用の属性のせいで実削除できない（C-2）"
    assert store.con.execute("SELECT hold_path FROM deletion_log WHERE id = ?",
                             (got["deletion_id"],)).fetchone()["hold_path"] == HOLD_PURGED


def test_the_purge_endpoint_says_409_when_it_cannot_delete(svc, store, library, monkeypatch):
    """壊すと落ちる: `purge_now` の `OSError` をそのまま上げる（C-2。口なら 500 になる）。"""
    path = make_png(library / "c2b.png", seed=207)
    asset_id = add_asset(store, path)
    got = svc.delete(asset_id=asset_id, path=str(path), stage=3, actor="human",
                     confirm_last_copy=True)

    def boom(hold_path):
        raise PermissionError("他のプロセスが掴んでいます")

    monkeypatch.setattr(svc, "_remove_hold", boom)
    with pytest.raises(ReviewError) as err:
        svc.purge_now(got["deletion_id"], confirm=True, actor="human")
    assert err.value.status == 409 and err.value.code == "purge_failed"
    assert Path(got["hold_path"]).exists(), "消せないのに消したと言っている"


def test_a_second_live_location_keeps_the_asset_visible(svc, store, library, clock):
    """壊すと落ちる: 場所が 2 つある画像の片方を消しただけで一覧から外す（C-3・G-7）。

    削除は**場所**の単位、`asset.deleted_at` は**資産**の単位。生きている複製が残っている間は
    一覧に出す（実削除の後も同じ）。
    """
    first = make_png(library / "c3a.png", seed=208)
    asset_id = add_asset(store, first)
    second = library / "c3b.png"
    shutil.copy2(first, second)
    with store.transaction() as con:                        # 同じ `asset` の 2 か所目
        con.execute("INSERT INTO asset_location(path, display_path, asset_id, size, mtime_ns,"
                    " is_primary, missing_at, last_seen_at) VALUES (?,?,?,?,?,0,NULL,'t')",
                    (normalize_path(second), str(second), asset_id, second.stat().st_size,
                     second.stat().st_mtime_ns))
    first_got = svc.delete(asset_id=asset_id, path=str(first), stage=3, actor="human")
    assert first_got["stage"] == 3
    assert store.con.execute("SELECT deleted_at FROM asset WHERE id = ?",
                             (asset_id,)).fetchone()["deleted_at"] is None, \
        "生きている複製が在るのに一覧から外した（C-3）"
    # **実削除の後も**（窓が尽きても、生きている方が在れば出る）
    clock.advance(mono=DEFAULT_UNDO_WINDOW_SEC + 1)
    svc.tick()
    svc.tick()
    assert not Path(first_got["hold_path"]).exists()
    assert store.con.execute("SELECT deleted_at FROM asset WHERE id = ?",
                             (asset_id,)).fetchone()["deleted_at"] is None, \
        "実削除の後で一覧から外した（C-3）"
    # **最後の 1 つ**を消すと外れる（元の規則は生きている）
    last = svc.delete(asset_id=asset_id, path=str(second), stage=3, actor="human",
                      confirm_last_copy=True)
    assert last["stage"] == 3
    assert store.con.execute("SELECT deleted_at FROM asset WHERE id = ?",
                             (asset_id,)).fetchone()["deleted_at"], "最後の 1 つを消しても外れない"


def test_bulk_stage1_and_stage2_do_not_need_the_last_copy_confirmation(svc, store, library):
    """壊すと落ちる: 段を見ずに `last_copy` を要求する（C-4）。

    段 1（カタログから外す）と段 2（ゴミ箱）は**内容が失われない**ので重い確認は要らない。
    実データは全枚が最後の 1 つなので、段 1 の一括まで毎回 409 になっていた。
    **段 3 は要る**（消すと内容そのものが失われる）。
    """
    for stage in (1, 2):
        path = make_png(library / f"c4-{stage}.png", seed=210 + stage)
        asset_id = add_asset(store, path)
        got = svc.bulk_preview(scope={"kind": "assets", "asset_ids": [asset_id]}, stage=stage,
                               actor="human")
        assert got["last_copies"] == 1, got
        done = svc.bulk_delete(preview_id=got["preview_id"], confirm=True, actor="human")
        assert done["count"] == 1 and not done["skipped"], (stage, done)
    path = make_png(library / "c4-3.png", seed=213)
    asset_id = add_asset(store, path)
    got = svc.bulk_preview(scope={"kind": "assets", "asset_ids": [asset_id]}, stage=3,
                           actor="human")
    with pytest.raises(ReviewError) as err:
        svc.bulk_delete(preview_id=got["preview_id"], confirm=True, actor="human")
    assert err.value.status == 409 and err.value.code == "last_copy"
    assert path.exists(), "409 なのに消した"


def test_the_frozen_size_and_mtime_are_compared_at_execution(svc, store, library):
    """壊すと落ちる: 凍結した `(size, mtime_ns)` を実行時に見ない（C-5・§0.7）。

    走査が同じ内容の `touch` を取り込んだ後（DB の登録と実ファイルは一致）でも、
    **凍結した値と違えば `skipped: changed`** にする（凍結の値を使わないなら入れる意味が無い）。
    """
    path = make_png(library / "c5.png", seed=214)
    asset_id = add_asset(store, path)
    got = svc.bulk_preview(scope={"kind": "assets", "asset_ids": [asset_id]}, stage=2,
                           actor="human")
    frozen = got["items"][0]
    after = path.stat()
    os.utime(path, ns=(after.st_atime_ns, after.st_mtime_ns + 1_000_000))
    now = path.stat()
    with store.transaction() as con:                        # 走査が取り込んだのと同じ形
        con.execute("UPDATE asset_location SET mtime_ns = ?, size = ? WHERE path = ?",
                    (now.st_mtime_ns, now.st_size, normalize_path(path)))
    assert (now.st_size, now.st_mtime_ns) != (frozen["size"], frozen["mtime_ns"])
    done = svc.bulk_delete(preview_id=got["preview_id"], confirm=True, actor="human")
    assert [s["reason"] for s in done["skipped"]] == ["changed"], done
    assert done["count"] == 0 and path.exists(), "凍結した値と違うのに消した（C-5）"


# ---- P8-2 の監査の指摘（D の残りと F の穴）----


def test_a_stuck_row_is_never_purged_automatically(svc, store, library, clock):
    """壊すと落ちる: `purge_at IS NULL`（stuck）の行も自動で消す（§8.4 X1・専門 §3.4）。

    **25 周期回しても**実体は動かない（**人が「いま消す」を選ぶまで触らない**）。
    """
    path = make_png(library / "stuck.png", seed=220)
    asset_id = add_asset(store, path)
    got = svc.delete(asset_id=asset_id, path=str(path), stage=3, actor="human",
                     confirm_last_copy=True)
    with store.transaction() as con:
        con.execute("UPDATE deletion_log SET purge_at = NULL, remaining_sec = 0 WHERE id = ?",
                    (got["deletion_id"],))
    for _ in range(25):
        clock.advance(mono=30)
        svc.tick()
    assert Path(got["hold_path"]).exists(), "戻せない行を黙って消した（専門 §3.4）"
    assert svc.ledger(actor="human")["items"][0]["state"] == "stuck"
    assert svc.pending(actor="human")["count"] == 1, "『取り消せる』から消えた（戻す導線が消える）"
    done = svc.purge_now(got["deletion_id"], confirm=True, actor="human")
    assert done["purged"] is True and not Path(got["hold_path"]).exists(), \
        "人が「いま消す」を選んでも消せない"


def test_the_window_is_charged_by_the_shorter_elapsed_time(svc, store, library, clock):
    """壊すと落ちる: 決定 7 の上限を外す（§8.4 X2）・端数を捨てる（D-11）。

    引くのは **min(前回の周期からの経過, その行が生まれてからの経過)**。消した直後の周期で
    「消す前の時間」まで引かれない（実機で 35 秒に 60 秒ぶん引かれた形）。
    端数は次の周期に繰り越す（切り捨ては**窓が延びる側**に倒れる）。
    """
    clock.advance(mono=25)                                  # 周期の途中（前回の周期から 25 秒）
    path = make_png(library / "win.png", seed=221)
    asset_id = add_asset(store, path)
    got = svc.delete(asset_id=asset_id, path=str(path), stage=3, actor="human",
                     confirm_last_copy=True)

    def left() -> int:
        return store.con.execute("SELECT remaining_sec FROM deletion_log WHERE id = ?",
                                 (got["deletion_id"],)).fetchone()["remaining_sec"]

    clock.advance(mono=10)                                  # 前回から 35 秒・生まれてから 10 秒
    tick = svc.tick()
    assert tick["delta"] == 35, tick
    assert left() == 290, f"生まれる前の 25 秒ぶんまで引いた（{left()}。設計の字義なら 265）"
    clock.advance(mono=0.9)                                 # **端数**（1 秒に満たない）
    svc.tick()
    assert left() == 290, f"1 秒未満の経過で窓が減った（{left()}）"
    clock.advance(mono=0.2)                                 # 0.9 + 0.2 = 1.1 秒
    svc.tick()
    assert left() == 289, f"端数を捨てて窓が延びる（{left()}。D-11）"


def test_the_last_copies_are_counted_as_a_bundle(svc, store, library):
    """壊すと落ちる: `last_copies` を 1 枚ずつ数える（§8.4 X3・設計の穴 10）。

    同じ画像の 2 か所が両方凍結に入ると**内容は失われる**ので 2 と数える
    （1 枚ずつ見ると「もう 1 か所が残る」ので 0 に見える）。
    """
    first = make_png(library / "x3a.png", seed=222)
    asset_id = add_asset(store, first)
    second = library / "x3b.png"
    shutil.copy2(first, second)
    with store.transaction() as con:
        con.execute("INSERT INTO asset_location(path, display_path, asset_id, size, mtime_ns,"
                    " is_primary, missing_at, last_seen_at) VALUES (?,?,?,?,?,0,NULL,'t')",
                    (normalize_path(second), str(second), asset_id, second.stat().st_size,
                     second.stat().st_mtime_ns))
    got = svc.bulk_preview(scope={"kind": "folder", "id": str(library)}, stage=2, actor="human")
    assert got["count"] == 2 and got["last_copies"] == 2, got["last_copies"]


def test_the_same_asset_id_twice_in_the_scope_is_one_item(svc, store, library):
    """壊すと落ちる: 同じ `asset_id` を畳まない（§8.4 X4。同じファイルを 2 回消しにいく）。"""
    path = make_png(library / "x4.png", seed=223)
    asset_id = add_asset(store, path)
    got = svc.bulk_preview(scope={"kind": "assets",
                                  "asset_ids": [asset_id, asset_id, asset_id]},
                           stage=2, actor="human")
    assert got["count"] == 1 and got["bytes"] == path.stat().st_size, got


def test_as_copy_avoids_names_that_the_catalog_already_uses(svc, store, library):
    """壊すと落ちる: `as_copy` の別名を**ファイルだけ**で選ぶ（§8.4 X5。`path` は主キー）。

    実体が無くても `asset_location` の行が同じ鍵を持っていれば、その名前は使えない
    （使うと登録の付け替えで UNIQUE に当たる）。
    """
    path = make_png(library / "x5.png", seed=224)
    asset_id = add_asset(store, path)
    got = svc.delete(asset_id=asset_id, path=str(path), stage=3, actor="human",
                     confirm_last_copy=True)
    path.write_bytes(b"occupied")
    ghost = path.with_name("x5.1.png")                      # **行だけが先に在る**名前
    with store.transaction() as con:
        con.execute("INSERT INTO asset_location(path, display_path, asset_id, size, mtime_ns,"
                    " is_primary, missing_at, last_seen_at) VALUES (?,?,?,0,0,0,'t','t')",
                    (normalize_path(ghost), str(ghost), asset_id))
    back = svc.undo(got["deletion_id"], as_copy=True, actor="human")
    assert Path(back["display_path"]).name == "x5.2.png", back["display_path"]
    assert path.read_bytes() == b"occupied", "元の場所の別のファイルを壊した"
    row = store.con.execute("SELECT path FROM asset_location WHERE display_path = ?",
                            (str(Path(back["display_path"])),)).fetchone()
    assert row is not None and row["path"] == normalize_path(back["display_path"])


def test_the_confirmation_flags_do_not_accept_the_string_false(client, tmp_path):
    """壊すと落ちる: `_flag` を `bool()` にする（§8.4 X6。`"false"` が真になる＝確認を飛ばせる）。"""
    store, path, asset_id = register(client, tmp_path, "flag.png")
    refused = client.post("/api/locations/delete", headers=HUMAN,
                          json={"asset_id": asset_id, "path": str(path), "stage": 3,
                                "confirm_last_copy": "false"})
    assert refused.status_code == 409 and refused.json()["code"] == "last_copy", refused.text
    assert path.exists()
    prev = client.post("/api/locations/bulk-delete/preview", headers=HUMAN,
                       json={"scope": {"kind": "assets", "asset_ids": [asset_id]},
                             "stage": 2}).json()
    bad = client.post("/api/locations/bulk-delete", headers=HUMAN,
                      json={"preview_id": prev["preview_id"], "confirm": "false"})
    assert bad.status_code == 422 and bad.json()["code"] == "confirm_required", bad.text
    ok = client.post("/api/locations/delete", headers=HUMAN,
                     json={"asset_id": asset_id, "path": str(path), "stage": 3,
                           "confirm_last_copy": "true"})
    assert ok.status_code == 200, "`\"true\"` は通る（安全側に倒すだけ）"


def test_start_does_not_delete_and_the_first_tick_after_it_waits(svc, store, clock):
    """壊すと落ちる: `start()` で期限切れを消す（§8.4 X25）。

    前は「起動時に消さない」の試験が `DeletionService()` を**作るだけ**で `start()` を
    呼んでいなかったので、この穴が隠れていた（`init` ではなく `start` が見られる）。
    """
    hold = store.data_dir / HOLD_DIR / "old2"
    hold.mkdir(parents=True, exist_ok=True)
    kept = make_png(hold / "kept2.png", seed=225)
    stage3_row(store, "old2", str(kept), remaining=0, purge_at="2000-01-01T00:00:00Z")
    fresh = DeletionService(store, clock=clock, interval=3600.0)
    fresh.start()                                           # **起動**
    try:
        assert kept.exists(), "start() で消している（§0.6-3）"
        fresh.tick()                                        # 1 周期目も消さない
        assert kept.exists(), "起動直後の 1 回で消している"
        clock.advance(mono=30)
        assert fresh.tick()["purged"] == 1 and not kept.exists(), "2 周期目でも消えていない"
    finally:
        fresh.stop()


def test_old_expired_previews_are_swept_but_fresh_ones_are_kept(svc, store, library, clock):
    """壊すと落ちる: `PREVIEW_KEEP_SEC` を使わない（G-5・D-10。1 件 1 行が永久に残る）。

    失効して**すぐは消さない**（線 8 の「10 分後に実行 → 409 `preview_expired`」を守る）が、
    1 日過ぎた未実行の行は片づける。**実行済みは残す**（`result_json` を返すため。§4.3）。
    """
    def previews() -> int:
        return store.con.execute("SELECT count(*) AS n FROM pending_delete_preview"
                                 ).fetchone()["n"]

    a = make_png(library / "d10a.png", seed=234)
    a_id = add_asset(store, a)
    old = svc.bulk_preview(scope={"kind": "assets", "asset_ids": [a_id]}, stage=1, actor="human")
    b = make_png(library / "d10b.png", seed=235)
    b_id = add_asset(store, b)
    done = svc.bulk_preview(scope={"kind": "assets", "asset_ids": [b_id]}, stage=1, actor="human")
    svc.bulk_delete(preview_id=done["preview_id"], confirm=True, actor="human")
    clock.advance(sec=601)                                  # 失効（10 分）
    svc.tick()
    assert previews() == 2, "失効しただけで消した（409 が 404 になり、線 8 を確かめられない）"
    clock.advance(sec=PREVIEW_KEEP_SEC + 1)                 # 1 日過ぎた
    svc.tick()
    assert previews() == 1, "1 日過ぎた未実行の凍結を掃除していない（G-5）"
    assert store.con.execute("SELECT 1 FROM pending_delete_preview WHERE id = ?",
                             (done["preview_id"],)).fetchone() is not None, \
        "実行済みの凍結を消した（同じ `preview_id` の再送が 404 になる）"
    assert store.con.execute("SELECT 1 FROM pending_delete_preview WHERE id = ?",
                             (old["preview_id"],)).fetchone() is None


def test_the_trash_folder_uses_the_local_day(svc, store, library):
    """壊すと落ちる: ゴミ箱の日付を UTC で取る（D-3。JST 02:30 の削除が前日に入る）。"""
    wall = float(calendar.timegm(time.strptime("2026-10-17T17:30:00", "%Y-%m-%dT%H:%M:%S")))
    jst = DeletionService(store, clock=FakeClock(wall=wall))
    path = make_png(library / "d3.png", seed=236)
    asset_id = add_asset(store, path)
    got = jst.delete(asset_id=asset_id, path=str(path), stage=2, actor="human")
    assert str(got["to_path"]).startswith(str(store.data_dir / TRASH_DIR))
    assert "20261018" in Path(got["to_path"]).parts, got["to_path"]
    assert jst.trash()["days"][0]["date"] == "20261018", jst.trash()["days"][0]["date"]


def test_the_ledger_shows_the_display_path(svc, store, library):
    """壊すと落ちる: 台帳の `display_path` に正規化した鍵（小文字）を出す（D-4）。"""
    path = make_png(library / "D4Case" / "D4.PNG", seed=237)
    asset_id = add_asset(store, path)
    svc.delete(asset_id=asset_id, path=str(path), stage=1, actor="human")
    row = svc.ledger(actor="human")["items"][0]
    assert row["display_path"] == str(path), row["display_path"]
    assert row["path"] == normalize_path(path) and row["path"] != row["display_path"]


def test_the_preview_endpoint_checks_the_actor(client, tmp_path):
    """壊すと落ちる: `GET /api/deletions/previews/{id}` が `actor` を見ない（D-5。`robot` で 200）。"""
    store, path, asset_id = register(client, tmp_path, "d5.png")
    prev = client.post("/api/locations/bulk-delete/preview", headers=HUMAN,
                       json={"scope": {"kind": "assets", "asset_ids": [asset_id]},
                             "stage": 1}).json()
    got = client.get(f"/api/deletions/previews/{prev['preview_id']}",
                     headers={"X-Image-Reviewer-Actor": "robot"})
    assert got.status_code == 422, got.text
    assert client.get(f"/api/deletions/previews/{prev['preview_id']}",
                      headers=HUMAN).status_code == 200


def test_the_stage_must_be_one_of_the_three_numbers(client, tmp_path):
    """壊すと落ちる: `stage: true` を段 1 として通す（D-6。`int(True)` は 1・`int(3.9)` は 3）。"""
    store, path, asset_id = register(client, tmp_path, "d6.png")
    for bad in (True, 3.9, "x", 0, 4, None):
        got = client.post("/api/locations/delete", headers=HUMAN,
                          json={"asset_id": asset_id, "path": str(path), "stage": bad})
        assert got.status_code == 422 and got.json()["code"] == "bad_stage", (bad, got.text)
    assert path.exists() and store.con.execute("SELECT count(*) AS n FROM deletion_log"
                                               ).fetchone()["n"] == 0


def test_a_refused_volume_leaves_no_empty_folder(svc, store, library, monkeypatch):
    """壊すと落ちる: ボリュームを確かめる**前に**フォルダを作る（D-7。空の `<id>/` が残る）。"""
    path = make_png(library / "d7.png", seed=238)
    asset_id = add_asset(store, path)
    real = deletions.st_dev_of
    monkeypatch.setattr(deletions, "st_dev_of",
                        lambda p: 2 if (HOLD_DIR in str(p) or TRASH_DIR in str(p)) else real(p))
    for stage in (2, 3):
        with pytest.raises(ReviewError) as err:
            svc.delete(asset_id=asset_id, path=str(path), stage=stage, actor="human",
                       confirm_last_copy=True)
        assert err.value.code == "cross_volume", err.value.code
    assert path.exists()
    assert not (store.data_dir / HOLD_DIR).exists(), "断ったのに空の保留領域が残った（D-7）"
    assert not (store.data_dir / TRASH_DIR).exists(), "断ったのに空のゴミ箱が残った（D-7）"


def test_a_stale_in_progress_token_can_be_resent(svc, store, library):
    """壊すと落ちる: `result_json` の無い行を永久に `in_progress` にする（D-8。落ちた要求）。

    古ければ巻き取って再送を許し、**新しければ**（同時に走っている 1 本を踏まないように）
    409 `client_token_in_progress` で断る。
    """
    path = make_png(library / "d8.png", seed=239)
    asset_id = add_asset(store, path)
    payload = {"kind": "asset", "asset_id": asset_id, "path": normalize_path(path), "stage": 1}
    with store.transaction() as con:                        # **落ちた要求**（結果が無いまま古い）
        con.execute("INSERT INTO delete_request(id, client_token, actor, stage, count,"
                    " payload_json, at) VALUES ('dead', 'tok-dead', 'human', 1, 1, ?,"
                    " '2000-01-01T00:00:00Z')", (json.dumps(payload),))
    got = svc.delete(asset_id=asset_id, path=str(path), stage=1, actor="human",
                     client_token="tok-dead")
    assert got["replayed"] is False and got["stage"] == 1
    assert store.con.execute("SELECT count(*) AS n FROM delete_request WHERE client_token ="
                             " 'tok-dead'").fetchone()["n"] == 1
    # **新しい要求は「進行中」で断る**
    other = make_png(library / "d8b.png", seed=240)
    other_id = add_asset(store, other)
    live = {"kind": "asset", "asset_id": other_id, "path": normalize_path(other), "stage": 1}
    svc._open_request(actor="human", stage=1, count=1, client_token="tok-live", payload=live)
    with pytest.raises(ReviewError) as err:
        svc.delete(asset_id=other_id, path=str(other), stage=1, actor="human",
                   client_token="tok-live")
    assert err.value.status == 409 and err.value.code == "client_token_in_progress"


def test_the_stage3_preview_does_not_promise_the_free_time(svc, store, library):
    """壊すと落ちる: 段 3 の preview の `frees.at` に凍結の失効時刻を出す（D-9）。

    いつ空くかは**実行してから**決まる（凍結の失効は「5 分の窓が過ぎた時点」ではない）。
    """
    path = make_png(library / "d9.png", seed=241)
    asset_id = add_asset(store, path)
    got = svc.bulk_preview(scope={"kind": "assets", "asset_ids": [asset_id]}, stage=3,
                           actor="human")
    assert got["frees"]["at"] is None, "実行前なのに『いつ空くか』を約束している（D-9）"
    assert "5 分" in got["frees"]["note"]
    assert svc.delete(asset_id=asset_id, path=str(path), stage=3, actor="human",
                      confirm_last_copy=True)["frees"]["at"] is not None, \
        "実行したら窓の後の時刻を出す（段 3 の意味）"


def test_the_stage3_preview_shows_the_items_the_flag_does_not_allow(svc, store, tmp_path):
    """壊すと落ちる: 段 3 の preview が印の無い置き場を数えない（D-2）。

    「2 枚消えます」と見せて実行で 1 枚 `stage_not_allowed` になる形を防ぐ。
    """
    plain = tmp_path / "noflag-d2"
    plain.mkdir(parents=True, exist_ok=True)
    store.set_roots([str(plain)])                           # 印は立てない（既定 0）
    path = make_png(plain / "d2.png", seed=242)
    asset_id = add_asset(store, path)
    got = svc.bulk_preview(scope={"kind": "assets", "asset_ids": [asset_id]}, stage=3,
                           actor="human")
    assert got["count"] == 1 and got["not_allowed_count"] == 1, got
    assert got["not_allowed"][0]["asset_id"] == asset_id
    done = svc.bulk_delete(preview_id=got["preview_id"], confirm=True, actor="human",
                           confirm_last_copy=True)
    assert [s["reason"] for s in done["skipped"]] == ["stage_not_allowed"] and path.exists()


def test_a_folder_outside_the_registered_roots_cannot_be_frozen(svc, store, library, tmp_path):
    """壊すと落ちる: `folder` の `scope` に置き場の制限を掛けない（D-14）。

    `C:\\` のような指定で**管理下でない物まで凍結の一覧に入る**（人に上限が無いので、
    preview が現実的な歯止めになる）。
    """
    outside = tmp_path / "outside-d14"
    path = make_png(outside / "d14.png", seed=243)
    add_asset(store, path)
    with pytest.raises(ReviewError) as err:
        svc.bulk_preview(scope={"kind": "folder", "id": str(outside)}, stage=1, actor="human")
    assert err.value.status == 422 and err.value.code == "bad_scope"
    inside = svc.bulk_preview(scope={"kind": "folder", "id": str(library)}, stage=1, actor="human")
    assert inside["count"] == 0                             # 置き場の中は通る（空でも 200）


def test_deleting_the_same_place_twice_is_one_row_and_one_undo(svc, store, library):
    """壊すと落ちる: 段 1 を 2 回で行が 2 つになり、1 回戻しても隠れたまま（D-12）。"""
    path = make_png(library / "d12.png", seed=244)
    asset_id = add_asset(store, path)
    first = svc.delete(asset_id=asset_id, path=str(path), stage=1, actor="human")
    again = svc.delete(asset_id=asset_id, path=str(path), stage=1, actor="human")
    assert again["replayed"] is True and again["deletion_id"] == first["deletion_id"]
    assert store.con.execute("SELECT count(*) AS n FROM deletion_log").fetchone()["n"] == 1, \
        "同じ場所を 2 回外して行が 2 つになった（D-12）"
    svc.undo(first["deletion_id"], actor="human")
    assert store.con.execute("SELECT deleted_at FROM asset WHERE id = ?",
                             (asset_id,)).fetchone()["deleted_at"] is None, \
        "1 回戻したのに一覧から出てこない（D-12）"


def test_a_missing_path_is_422_not_409(client, tmp_path):
    """壊すと落ちる: `path` の欠落を `not_registered`（409）にする（D-13。入力の不足は 422）。"""
    store, path, asset_id = register(client, tmp_path, "d13.png")
    for empty in ("", "   ", None):
        got = client.post("/api/locations/delete", headers=HUMAN,
                          json={"asset_id": asset_id, "path": empty, "stage": 1})
        assert got.status_code == 422 and got.json()["code"] == "bad_path", (empty, got.text)


def test_the_http_gets_never_write_with_a_live_window(client, tmp_path):
    """壊すと落ちる: `GET /api/pending-deletes` で `remaining_sec` を減らす（§8.1 の 18・D-17）。

    サービス直呼びだけでなく**口から**も見る（`remaining_sec` の在る状態で比べる）。
    """
    store, path, asset_id = register(client, tmp_path, "d17.png")
    got = client.post("/api/locations/delete", headers=HUMAN,
                      json={"asset_id": asset_id, "path": str(path), "stage": 3,
                            "confirm_last_copy": True}).json()
    prev = client.post("/api/locations/bulk-delete/preview", headers=HUMAN,
                       json={"scope": {"kind": "assets", "asset_ids": [asset_id]},
                             "stage": 1}).json()
    tables = [r["name"] for r in store.con.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY name")]

    def snapshot():
        counts = tuple(store.con.execute(f"SELECT count(*) AS n FROM {t}").fetchone()["n"]
                       for t in tables)
        cells = tuple(store.con.execute("SELECT id, remaining_sec, purge_at, restored_at,"
                                        " hold_path FROM deletion_log ORDER BY id").fetchall())
        files = tuple(sorted((str(p.relative_to(store.data_dir)), p.stat().st_size,
                              p.stat().st_mtime_ns)
                             for p in store.data_dir.rglob("*") if p.is_file()))
        return counts, tuple(tuple(c) for c in cells), files

    before = snapshot()
    for url in ("/api/pending-deletes", "/api/deletions", "/api/trash", "/api/deletions/trash",
                f"/api/deletions/previews/{prev['preview_id']}"):
        assert client.get(url, headers=HUMAN).status_code == 200, url
    assert snapshot() == before, "GET が書いている（D-17）"
    assert store.con.execute("SELECT remaining_sec FROM deletion_log WHERE id = ?",
                             (got["deletion_id"],)).fetchone()["remaining_sec"] == 300, \
        "GET で残り時間が減った"


def test_the_hold_area_reports_what_the_ledger_does_not_know(svc, store, library):
    """壊すと落ちる: 台帳に無い保留領域の中身を**黙って残す**（G-4 の「拾い物」）。

    起動時に警告に出し、`GET /api/pending-deletes` の `found` に出す。**消しも動かしもしない。**
    """
    orphan = store.data_dir / HOLD_DIR / "orphan" / "lost.png"
    orphan.parent.mkdir(parents=True, exist_ok=True)
    make_png(orphan, seed=245)
    known = make_png(library / "known.png", seed=246)
    asset_id = add_asset(store, known)
    got = svc.delete(asset_id=asset_id, path=str(known), stage=3, actor="human",
                     confirm_last_copy=True)
    svc.start()                                             # **起動**（拾い物を出す）
    try:
        showed = svc.pending(actor="human")
        assert showed["found_count"] == 1, showed["found"]
        assert showed["found"][0]["path"] == str(orphan)
        assert orphan.exists(), "拾い物を消した（人が決めるまで触らない）"
        assert Path(got["hold_path"]).exists()
        assert svc.found_in_hold()["count"] == 1, "台帳に在る物を拾い物に数えている"
    finally:
        svc.stop()


# ---- P8-3 の D-1・D-2（再確認の軽微 2 件。どちらも「失敗の道」）----


def test_a_failure_after_the_move_keeps_the_original_error(svc, store, library, monkeypatch):
    """壊すと落ちる: `_drop_request` が台帳の外部キーに当たって**元の例外を隠す**（D-1）。

    B-1 で台帳を先に書く順にしたので、移動の後で取引が落ちると
    `deletion_log.request_id` が要求の行を指している。そこで `DELETE FROM delete_request` を
    素直に投げると `PRAGMA foreign_keys = ON` の外部キーに当たり、
    **上がる例外が `IntegrityError` になって元の失敗（`RuntimeError`）が隠れる**
    （監査 `checks2.py` K3a。500 の文面が外部キーになる）。
    """
    path = make_png(library / "d1.png", seed=251)
    asset_id = add_asset(store, path)
    moved = {}

    def boom(con, asset_id_, at):
        raise RuntimeError("移動の後の取引で落ちた")

    monkeypatch.setattr(DeletionService, "_sync_hidden", staticmethod(boom))
    with pytest.raises(RuntimeError) as err:
        svc.delete(asset_id=asset_id, path=str(path), stage=2, actor="human",
                   client_token="tok-d1")
    assert "落ちた" in str(err.value), f"元の例外が隠れた: {err.value!r}"
    # **行は正しく残る**（台帳 1 行・要求 1 行）。ファイルはゴミ箱に在る
    row = store.con.execute("SELECT request_id, restored_at FROM deletion_log").fetchone()
    assert row is not None and row["request_id"], "台帳の行が消えた（迷子になる）"
    assert store.con.execute("SELECT count(*) AS n FROM delete_request WHERE client_token ="
                             " 'tok-d1'").fetchone()["n"] == 1, "要求の控えが消えた"
    assert svc.ledger(actor="human")["items"][0]["state"] == "trashed", "ゴミ箱に出ない"
    assert svc.pending(actor="human")["found_count"] == 0, "保留に無い物を拾い物に数えている"
    # **同じ token の再送は二重に消さない**（台帳が参照しているので巻き取らない）
    monkeypatch.undo()                                      # `_sync_hidden` を元に戻す
    with pytest.raises(ReviewError) as again:
        svc.delete(asset_id=asset_id, path=str(path), stage=2, actor="human",
                   client_token="tok-d1")
    assert again.value.status == 409 and again.value.code == "client_token_in_progress", \
        again.value.code


def test_a_different_file_at_the_original_place_is_not_recovered(svc, store, library, clock):
    """壊すと落ちる: 「戻したことにする」が**元の場所の中身を見ない**（D-2。窓切れの道）。

    保留の実体が外から消え、元の場所に**別のファイル**が在る形。`os.path.exists` だけで
    判断すると `restored_at` が立ち、**`missing_at` が立ったまま `restored_at` も立つ**
    矛盾した行ができる（監査 `checks2.py` K3c。登録 565,252 B に対して実体 12 B）。
    """
    path = make_png(library / "d2.png", seed=252)
    asset_id = add_asset(store, path)
    got = svc.delete(asset_id=asset_id, path=str(path), stage=3, actor="human",
                     confirm_last_copy=True)
    os.remove(got["hold_path"])                             # **保留を外から消す**
    path.write_bytes(b"x" * 12)                             # **元の場所は別のファイル**
    with store.transaction() as con:                        # 窓を尽きさせる
        con.execute("UPDATE deletion_log SET remaining_sec = 0 WHERE id = ?",
                    (got["deletion_id"],))
    clock.advance(mono=60)
    svc.tick()
    svc.tick()
    row = store.con.execute("SELECT restored_at, purge_at FROM deletion_log WHERE id = ?",
                            (got["deletion_id"],)).fetchone()
    assert row["restored_at"] is None, "別のファイルを『戻した』ことにした（D-2）"
    assert row["purge_at"] is None, "戻せない行が自動削除の対象に残っている"
    assert svc.ledger(actor="human")["items"][0]["state"] == "stuck", "戻せませんでしたに出ない"
    assert path.read_bytes() == b"x" * 12, "元の場所の別のファイルに触った（1 バイトも触らない）"
    assert where(store, asset_id)["missing_at"] is not None, "削除は起きているのに登録を戻した"


def test_undo_refuses_when_the_original_place_holds_another_file(svc, store, library):
    """壊すと落ちる: `undo` が**別のファイル**を「戻した」ことにする（D-2。取り消しの道）。

    保留の実体が無く、元の場所に別のファイルが在るときは 409 `restore_failed` で止め、
    `stuck`（`purge_at` NULL）にする。**元の場所のファイルは 1 バイトも触らない。**
    """
    path = make_png(library / "d2b.png", seed=253)
    asset_id = add_asset(store, path)
    got = svc.delete(asset_id=asset_id, path=str(path), stage=3, actor="human",
                     confirm_last_copy=True)
    os.remove(got["hold_path"])
    path.write_bytes(b"y" * 20)
    with pytest.raises(ReviewError) as err:
        svc.undo(got["deletion_id"], actor="human")
    assert err.value.status == 409 and err.value.code == "restore_failed", err.value.code
    row = store.con.execute("SELECT restored_at, purge_at FROM deletion_log WHERE id = ?",
                            (got["deletion_id"],)).fetchone()
    assert row["restored_at"] is None and row["purge_at"] is None, "stuck になっていない"
    assert path.read_bytes() == b"y" * 20, "別のファイルに触った"
    assert where(store, asset_id)["missing_at"] is not None
