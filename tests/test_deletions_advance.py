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
import os
import shutil
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from image_reviewer import deletions
from image_reviewer.deletions import AGENT_MAX_BATCH, TRASH_DIR, DeletionService
from image_reviewer.review import ReviewError
from image_reviewer.scan import scan
from image_reviewer.store import Store, normalize_path

HUMAN = {"X-Image-Reviewer-Actor": "human"}
AGENT = {"X-Image-Reviewer-Actor": "agent"}

#: **移動を断られたときの案内**（利用者の依頼 2026-10-19。`docs/move-failed-message.md`）。
#: **`deletions.py` の定数を読まずに文をそのまま書く**——文言を戻したらここで落ちるようにする。
#: **（P11 の監査 D-3）「エクスプローラー」に揃えた**（`file_found` と同じ語）。
MOVE_FAILED_TEXT = (
    "このファイルは移動できませんでした。ほかのフォルダにあるファイルは、"
    "エクスプローラーで消してから「ファイルが無いので片付ける」を押してください。"
    "（詳細: [WinError 5] アクセスが拒否されました。）")


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


def deny_moves(monkeypatch) -> None:
    """**権限で断られる移動**を作る（`os.rename` を差し替える。**実データは触らない**）。

    この環境の断りは `PermissionError`（WinError 5）で来る（アプリのプロセスが
    `C:\\work\\image-reviwer` の外に書けない。`docs/design.md` §16.7 の末尾）。
    **ワークスペースの外を指す行を作らずに**同じ形にする（`test_deletions.py` と同じ流儀）。
    """
    def deny(src, dst):
        raise PermissionError(13, "アクセスが拒否されました。", str(src), 5)

    monkeypatch.setattr(deletions.os, "rename", deny)


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


def deleted_at_of(store: Store, asset_id: str) -> str | None:
    return store.con.execute("SELECT deleted_at FROM asset WHERE id = ?",
                             (asset_id,)).fetchone()["deleted_at"]


def park_away(path: Path, tmp_path: Path) -> Path:
    """**利用者がエクスプローラーで外へ出した形**（Windows のごみ箱へ移したのと同じ。移動＝mtime 不変）。"""
    parked = tmp_path / "windows-recycle"
    parked.mkdir(exist_ok=True)
    moved = parked / path.name
    shutil.move(str(path), str(moved))
    return moved


def stage3_row(svc: DeletionService, store: Store, library: Path, path: Path) -> dict:
    """段 3 の行を 1 つ作る（**印のある置き場**で、最後の 1 つを消す確認つき）。"""
    svc.set_allow_stage3(normalize_path(library), allow=True, actor="human")
    asset_id = add_asset(store, path)
    return svc.delete(asset_id=asset_id, path=str(path), stage=3, actor="human",
                      confirm_last_copy=True)


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


def test_advance_refuses_a_ledger_row_whose_image_is_replaced(svc, store, library):
    """壊すと落ちる: **別の枚のファイルをゴミ箱へ移す**（P10 の監査 A-1。**最も重大な 3 件の 1**）。

    実データの 194 行のうち 6 行は、**走査が同じ場所を別の `asset` として登録し直した**ことで
    台帳の `asset_id`（X）が古くなっている。その 6 行は**利用者が消した画像の実体がもう無く**、
    同じ場所には**別の画像 Y が登録されてカタログに見えている**。

    台帳の行が指す物（`deletion_log.size` と枚）と、いま動かそうとしているファイルを
    照合しないと、**Y のファイルをゴミ箱へ移して Y が一覧から消える**（利用者の見ている画像が
    消える）。**409 `different_file`** で断り、「ファイルが無いので片付ける」を案内する。

    壊すと落ちる: `_require_file_for_advance()` から**台帳の `size` との照合**（と
    `asset_location.asset_id` の照合）を外すと、Y のファイルが動いてこのテストが落ちる。
    """
    path = make_png(library / "stale.png", seed=70)
    got = stage1(svc, store, path)
    old_asset = row_of(store, got["deletion_id"])["asset_id"]
    make_png(path, seed=71)                        # 中身が入れ替わった
    new_asset = add_asset(store, path, name="stale-2.png")   # **別の sha256** で登録し直す
    assert new_asset != old_asset, "同じ asset のままでは、この形を作れない"
    assert store.con.execute("SELECT count(*) AS n FROM asset_location WHERE asset_id = ?",
                             (old_asset,)).fetchone()["n"] == 0, "古い場所が残っている"
    assert store.con.execute("SELECT deleted_at FROM asset WHERE id = ?",
                             (new_asset,)).fetchone()["deleted_at"] is None, "Y は見えているはず"
    before = (path.stat().st_size, path.stat().st_mtime_ns)
    with pytest.raises(ReviewError) as exc:
        svc.advance(got["deletion_id"], stage=2, actor="human")
    assert exc.value.status == 409 and exc.value.code == "different_file", exc.value
    assert "ファイルが無いので片付ける" in exc.value.detail, exc.value.detail
    # **別の枚のファイルを 1 つも動かしていない**
    assert path.exists() and (path.stat().st_size, path.stat().st_mtime_ns) == before
    assert store.con.execute("SELECT deleted_at FROM asset WHERE id = ?",
                             (new_asset,)).fetchone()["deleted_at"] is None, "Y が一覧から消えた"
    row = row_of(store, got["deletion_id"])
    assert int(row["stage"]) == 1 and row["to_path"] is None, "断ったのに段が上がっている"
    assert row["asset_id"] == old_asset, "台帳の「消した枚」を書き換えた"
    # **案内どおり「片付ける」で終われる**（Y のファイルを「まだ在る」と数えない。監査 C-1）
    out = svc.close(got["deletion_id"], reason="missing", actor="human")
    assert out["closed"] is True and out["files_touched"] == 0, out
    assert path.exists(), "片付けが別の枚のファイルを触った"
    assert store.con.execute("SELECT deleted_at FROM asset WHERE id = ?",
                             (new_asset,)).fetchone()["deleted_at"] is None, "Y が一覧から消えた"


def test_restore_clears_the_mark_of_the_asset_registered_now(svc, store, library):
    """壊すと落ちる: **戻した後、いまその場所に登録されている枚 Y の `deleted_at` が立ったまま**
    （P10 の監査 A-2。**実体があるのにカタログから永久に消える**）。

    立てる側（`advance` / `delete`）は**いま登録されている枚**に印を立てるのに、消す側
    （`_restore`）が**台帳の枚 X だけ**を見ていた。`undo` は `already_restored`、走査は
    `missing_at` しか戻さないので、**Y を見せる操作が 1 つも無い**。

    形は「X の段 2 の行が在る → 同じ場所に別の画像 Y が登録され、その Y も段 2 で外れて
    **生きた場所が 0**（＝隠れている）→ X の行を戻す」。戻すと**ファイルは元の場所に戻り、
    Y の登録も生き返る**ので、Y の印も外れていなければならない（`_sync_hidden_with_location`）。

    壊すと落ちる: `_restore()` の同期を台帳の枚だけ（`_sync_hidden(con, row["asset_id"], at)`）に
    戻すと、**Y の `deleted_at` が立ったまま**になり、このテストが落ちる。
    """
    path = make_png(library / "swap.png", seed=72)
    first = add_asset(store, path)
    gone = svc.delete(asset_id=first, path=str(path), stage=2, actor="human")
    # **同じ場所に別の画像が登録され直す**（走査が入れ替えを拾った形）→ Y が見えている
    make_png(path, seed=73)
    other = add_asset(store, path, name="swap-2.png")
    assert other != first
    # **その Y も段 2 で外す**（生きた場所が 0 になる＝隠れる）
    second = svc.delete(asset_id=other, path=str(path), stage=2, actor="human")
    assert store.con.execute("SELECT deleted_at FROM asset WHERE id = ?",
                             (other,)).fetchone()["deleted_at"], "Y が隠れていない（前提が崩れた）"
    assert not path.exists(), "Y のファイルがまだ元の場所にある（前提が崩れた）"
    # **X の行を戻す**（ファイルは元の場所へ帰る。登録は Y の物）
    back = svc.trash_restore(gone["deletion_id"], actor="human")
    assert back["restored"] is True, back
    assert path.exists(), "ファイルが戻っていない"
    row = where(store, other)
    assert row["missing_at"] is None, "いま登録されている枚の参照切れが残っている"
    assert store.con.execute("SELECT deleted_at FROM asset WHERE id = ?",
                             (other,)).fetchone()["deleted_at"] is None, \
        "戻したのに、いま登録されている枚がカタログから消えたまま"
    assert Path(second["to_path"]).exists(), "Y のゴミ箱の中身を触った"


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
    """壊すと落ちる: **別のファイルを移す**（登録した `(size, mtime_ns)` を見ない）。

    (1) **同じ大きさのまま `mtime_ns` だけ変わった**形 → 409 `changed`（登録との照合。
    `_require_file_for_advance()` の `mtime_ns` の比較を外すと落ちる）。
    (2) **大きさが変わった**形 → 409 `different_file`（台帳の `size` との照合。監査 A-1）。
    どちらも**ファイルを 1 つも動かさない**。
    """
    path = make_png(library / "changed.png", seed=13)
    got = stage1(svc, store, path)
    before = path.stat()
    # (1) 中身は同じで時刻だけ進める（**同じ大きさ・違う mtime**。規則の届く差し替え）
    os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns + 1_000_000))
    assert path.stat().st_size == before.st_size, "大きさまで変わっては (1) の形にならない"
    with pytest.raises(ReviewError) as exc:
        svc.advance(got["deletion_id"], stage=2, actor="human")
    assert exc.value.status == 409 and exc.value.code == "changed", exc.value
    assert path.exists(), "断ったのにファイルが消えた"
    assert int(row_of(store, got["deletion_id"])["stage"]) == 1
    # (2) 大きさを変える（**台帳の `size` と違う**＝この行の画像ではない）
    path.write_bytes(path.read_bytes() + b"x")
    with pytest.raises(ReviewError) as exc:
        svc.advance(got["deletion_id"], stage=2, actor="human")
    assert exc.value.status == 409 and exc.value.code == "different_file", exc.value
    assert "ファイルが無いので片付ける" in exc.value.detail, exc.value.detail
    assert path.exists() and int(row_of(store, got["deletion_id"])["stage"]) == 1


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


# ---- 移動を断られたときの案内（利用者の依頼 2026-10-19。`docs/move-failed-message.md`）----


def test_a_permission_error_when_advancing_names_the_way_that_works(svc, store, library,
                                                                   monkeypatch):
    """壊すと落ちる: 段 2 へ進める移動が権限で断られたときに**技術的な 1 行**を返す。

    この環境ではアプリのプロセスが `C:\\work\\image-reviwer` の外に書けない（WinError 5。
    `docs/design.md` §16.7 の末尾）ので、外のファイルは**必ず断られる**。通る道
    （エクスプローラで消してから「ファイルが無いので片付ける」）を 2 文で案内し、
    **段 1 に戻す**（`_unadvance`）・**動かさない**。`code` は `move_failed` のまま。
    """
    path = make_png(library / "adv-denied.png", seed=212)
    got = stage1(svc, store, path)
    deny_moves(monkeypatch)
    with pytest.raises(ReviewError) as err:
        svc.advance(got["deletion_id"], stage=2, actor="human")
    assert err.value.status == 409 and err.value.code == "move_failed", err.value.code
    assert err.value.detail == MOVE_FAILED_TEXT, err.value.detail
    assert str(path) not in err.value.detail, "元のパスを本文に出している（読めない 1 行）"
    assert path.exists(), "断られたのにファイルが動いた"
    row = row_of(store, got["deletion_id"])
    assert int(row["stage"]) == 1 and row["to_path"] is None, "動かせないのに段 2 のまま"
    assert row["restored_at"] is None and row["closed_at"] is None


def test_a_permission_error_in_advance_many_keeps_the_message(svc, store, library, monkeypatch):
    """壊すと落ちる: まとめて進める**断った 1 件を黙って捨てる**（`skipped` に文が無い）。

    まとめては 1 件の失敗で全体を止めない（数を黙って捨てない）。その 1 件の本文が
    画面の「移せませんでした」の理由になるので、**同じ案内**を `message` に残す。
    """
    paths = [make_png(library / f"adv-many{i}.png", seed=213 + i) for i in range(2)]
    rows = [stage1(svc, store, p) for p in paths]
    deny_moves(monkeypatch)
    out = svc.advance_many([r["deletion_id"] for r in rows], stage=2, actor="human")
    assert out["count"] == 0 and out["skipped_count"] == 2, out
    assert {s["reason"] for s in out["skipped"]} == {"move_failed"}, out["skipped"]
    assert [s["message"] for s in out["skipped"]] == [MOVE_FAILED_TEXT] * 2, out["skipped"]
    assert all(p.exists() for p in paths), "断られたのにファイルが動いた"
    assert all(int(row_of(store, r["deletion_id"])["stage"]) == 1 for r in rows)


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
    カタログに戻り「参照切れ」が並ぶ）。

    **（P10 の監査 A-3）ファイルがまだ無い**（または**別の画像**が戻っている）うちは 409 のまま。
    """
    path = library / "no-back.png"
    got = stage1(svc, store, path, missing=True)
    svc.close(got["deletion_id"], reason="missing", actor="human")
    with pytest.raises(ReviewError) as exc:
        svc.undo(got["deletion_id"], actor="human")
    assert exc.value.status == 409 and exc.value.code == "already_closed", exc.value
    assert row_of(store, got["deletion_id"])["restored_at"] is None
    # **別の画像が戻った**形でも開き直さない（幽霊を戻さない）
    make_png(path, seed=64)                       # 台帳の `size` と違う中身
    with pytest.raises(ReviewError) as exc:
        svc.undo(got["deletion_id"], actor="human")
    assert exc.value.status == 409 and exc.value.code == "already_closed", exc.value
    assert path.exists(), "断ったのにファイルを触った"


def test_a_closed_row_opens_again_when_the_file_comes_back(svc, store, library, tmp_path):
    """壊すと落ちる: **片付けた行は、ファイルが戻ってきても二度とカタログに戻せない**
    （P10 の監査 A-3。**監査の推奨 (a)**）。

    利用者が Windows のごみ箱からファイルを戻す → 走査が `missing_at` を外す → **そのとき
    `asset.deleted_at` も `_should_hide()` の規則で引き直す**（`scan.py`）。閉じた行しか
    無い枚は**一覧に戻る**（生きた段 1 の行がある枚は**隠れたまま**＝利用者の意思を消さない）。

    壊すと落ちる: 走査の引き直し（`sync_hidden`）を外す、`_should_hide()` から
    `closed_at IS NULL` を外す、`_live_stage1()` から `closed_at IS NULL` を外す
    （それぞれ下の検査が落ちる）。
    """
    path = make_png(library / "back.png", seed=73)
    got = stage1(svc, store, path)
    asset_id = row_of(store, got["deletion_id"])["asset_id"]
    parked = park_away(path, tmp_path)             # 利用者が外へ出す
    svc.close(got["deletion_id"], reason="missing", actor="human")
    assert deleted_at_of(store, asset_id), "片付けた後は隠れたままのはず（実体が無い）"
    # **利用者がファイルを元の場所に戻して、走査する**（記録が案内していた道）
    shutil.move(str(parked), str(path))
    stats = scan(store, [str(library)])
    assert stats["missing"] == 0 and stats["known"] == 1, stats
    assert where(store, asset_id)["missing_at"] is None, "参照切れが戻っていない"
    assert deleted_at_of(store, asset_id) is None, "ファイルが戻ったのに一覧に戻らない"
    row = row_of(store, got["deletion_id"])
    assert row["closed_at"], "片付けの記録が消えた（1 行 = 1 回の片付けの記録）"
    assert row["restored_at"] is None
    assert svc.pending(actor="human")["items"] == [], "片付けた行が「最近の削除」に戻った"
    # **（A-3）閉じた行は「生きた段 1 の行」ではない**——同じ場所をもう一度外すと**新しい行**になる
    # （古い行の再送 `replayed` になると、その行の `undo` が 409 のままで戻せない）
    again = svc.delete(asset_id=asset_id, path=str(path), stage=1, actor="human")
    assert again["replayed"] is False and again["deletion_id"] != got["deletion_id"], again
    assert svc.undo(again["deletion_id"], actor="human")["restored"] is True
    assert deleted_at_of(store, asset_id) is None, "外し直して戻したのに一覧に戻らない"


def test_a_closed_row_opens_again_when_the_file_is_back_before_the_scan(svc, store, library,
                                                                       tmp_path):
    """壊すと落ちる: **走査を待たずに「戻す」を押せる形**（P10 の監査 A-3 の (b)）。

    ファイルが戻っていれば、片付けた段 1 の行は**開き直して戻せる**（実体が在り、登録も
    生きていて、大きさも台帳と一致するときだけ）。開き直しは `closed_at` を外すだけで、
    **ファイルも登録も触らない**。

    壊すと落ちる: `_restore()` の「ファイルが戻っていれば開き直す」を外す（409 のままになる）。
    """
    path = make_png(library / "reopen.png", seed=74)
    got = stage1(svc, store, path)
    asset_id = row_of(store, got["deletion_id"])["asset_id"]
    parked = park_away(path, tmp_path)
    svc.close(got["deletion_id"], reason="missing", actor="human")
    shutil.move(str(parked), str(path))            # **走査の前に**戻ってきた
    before = (path.stat().st_size, path.stat().st_mtime_ns)
    out = svc.undo(got["deletion_id"], actor="human")
    assert out["restored"] is True and out["stage"] == 1, out
    assert (path.stat().st_size, path.stat().st_mtime_ns) == before, "戻すのにファイルを触った"
    row = row_of(store, got["deletion_id"])
    assert row["restored_at"] and row["closed_at"] is None, "片付けた印が残っている"
    assert deleted_at_of(store, asset_id) is None, "一覧に戻っていない"
    assert svc.ledger(actor="human")["items"][0]["state"] == "restored"


def test_close_refuses_a_file_that_is_in_the_hold(svc, store, library):
    """壊すと落ちる: **一時置き場に実体があるのに片付ける**（P10 の監査 F の A3＝テストの穴）。

    段 3 の行の実体は `hold_path` にある。ここを見ないと、**保留のファイルを残したまま行を
    終わりにする**（「実体がどこにも無い」の確認が 1 つ抜ける）。**監査はこの形の検査が
    1 件も無いことを示した**（`_files_of_row()` から `hold_path` を外す変異が落ちなかった）。

    壊すと落ちる: `_files_of_row()` の候補から `hold_path` を外す。
    """
    path = make_png(library / "in-hold.png", seed=75)
    got = stage3_row(svc, store, library, path)
    assert Path(got["hold_path"]).exists(), "保留に実体が無い（前提が崩れた）"
    with pytest.raises(ReviewError) as exc:
        svc.close(got["deletion_id"], reason="missing", actor="human")
    assert exc.value.status == 409 and exc.value.code == "file_found", exc.value
    assert Path(got["hold_path"]).exists(), "断ったのに保留のファイルが消えた"
    assert row_of(store, got["deletion_id"])["closed_at"] is None


def test_a_closed_row_with_the_file_back_is_not_advanced(svc, store, library, tmp_path):
    """壊すと落ちる: **片付けた行を後から段 2 へ進める**（P10 の監査 F の A14＝テストの穴）。

    閉じた行は普通は実体が無いので `missing_file` で止まる。**ファイルが戻った閉じた行**なら
    素通りして**ファイルを移してしまう**（利用者はその行を終わりにしたのに、後から動く）。
    検査が 1 件も無かった形。

    壊すと落ちる: `_advance_one()` の `already_closed` の断りを外す。
    """
    path = make_png(library / "closed-move.png", seed=76)
    got = stage1(svc, store, path)
    parked = park_away(path, tmp_path)
    svc.close(got["deletion_id"], reason="missing", actor="human")
    shutil.move(str(parked), str(path))            # ファイルが戻った
    before = (path.stat().st_size, path.stat().st_mtime_ns)
    with pytest.raises(ReviewError) as exc:
        svc.advance(got["deletion_id"], stage=2, actor="human")
    assert exc.value.status == 409 and exc.value.code == "already_closed", exc.value
    assert path.exists() and (path.stat().st_size, path.stat().st_mtime_ns) == before, \
        "断ったのにファイルを動かした"
    assert row_of(store, got["deletion_id"])["to_path"] is None


def test_close_takes_a_stage3_row_out_of_the_timer(svc, store, library):
    """壊すと落ちる: **片付けた段 3 の行がタイマーに残る**（P10 の監査 C-3。

    実体が無いので実削除にはならないが、台帳の行が「閉じたのに窓が動いている」形になる
    （`tick()` が `decremented` に数え続ける）。`stuck` と同じ扱いで `purge_at` と
    `remaining_sec` を NULL にする。

    壊すと落ちる: `_close_one()` の UPDATE から `purge_at = NULL, remaining_sec = NULL` を外す。
    """
    path = make_png(library / "stage3-close.png", seed=77)
    got = stage3_row(svc, store, library, path)
    Path(got["hold_path"]).unlink()                # 利用者が保留の中身を消した
    out = svc.close(got["deletion_id"], reason="missing", actor="human")
    assert out["closed"] is True and out["stage"] == 3, out
    row = row_of(store, got["deletion_id"])
    assert row["purge_at"] is None and row["remaining_sec"] is None, dict(row)
    assert svc.tick()["decremented"] == 0, "片付けた行の窓が動いている"


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


def test_many_records_the_request_and_counts_the_replays(svc, store, library):
    """壊すと落ちる: **まとめて・片付けの記録が `delete_request` に残らない**（P10 の監査 B-2。
    記録の「`actor` は `delete_request` に残す」は 4 つの口のうち単発の `advance` だけだった）。
    **既に片付いていた行を成功に数えた数**（`replayed_count`）も分けて返す（監査 D-1）。

    壊すと落ちる: `_run_many()` / `close()` の `_open_request()` を外す（記録が増えない）、
    `replayed_count` を外す（既に片付けた行の数が分からない）。
    """
    def requests() -> list:
        return store.con.execute(
            "SELECT * FROM delete_request WHERE result_json IS NOT NULL"
            " ORDER BY rowid").fetchall()

    live = [stage1(svc, store, make_png(library / f"rec-{n}.png", seed=80 + n))["deletion_id"]
            for n in range(2)]
    gone = [stage1(svc, store, library / f"rec-gone-{n}.png", missing=True)["deletion_id"]
            for n in range(2)]
    before = len(requests())
    # (1) まとめて段 2 へ（1 回の呼び出しで 1 行）
    out = svc.advance_many(live + ["no-such-row"], stage=2, actor="human")
    assert out["count"] == 2 and out["skipped_count"] == 1, out
    made = requests()
    assert len(made) == before + 1, "まとめての記録が残っていない"
    row = made[-1]
    assert row["actor"] == "human" and int(row["stage"]) == 2 and int(row["count"]) == 3
    payload = json.loads(row["payload_json"])
    assert payload["kind"] == "advance_many" and payload["ids"] == live + ["no-such-row"], payload
    assert "no-such-row" in str(row["result_json"]), "断りも記録に残していない"
    # (2) 単発の片付け（**段 2 の行**なので、記録の段は 2）
    Path(row_of(store, live[0])["to_path"]).unlink()
    svc.close(live[0], reason="missing", actor="human")
    made = requests()
    assert len(made) == before + 2, "単発の片付けの記録が残っていない"
    assert json.loads(made[-1]["payload_json"])["kind"] == "close"
    assert int(made[-1]["stage"]) == 2, "段 2 の行を片付けたのに、記録の段が違う"
    # (3) まとめて片付ける（既に片付けた 1 件は `replayed_count` に数える。監査 D-1）
    out = svc.close_many([live[0]] + gone, reason="missing", actor="human")
    assert out["count"] == 3 and out["replayed_count"] == 1, out
    assert [one["replayed"] for one in out["closed"]] == [True, False, False], out["closed"]
    made = requests()
    assert len(made) == before + 3, "まとめて片付けの記録が残っていない"
    assert json.loads(made[-1]["payload_json"])["kind"] == "close_many"
    assert int(made[-1]["count"]) == 3
    # **断った要求は記録に残さない**（`advance` と同じ規則）
    alive = stage1(svc, store, make_png(library / "rec-alive.png", seed=88))
    count_before = len(requests())
    with pytest.raises(ReviewError):
        svc.close(alive["deletion_id"], reason="missing", actor="human")     # 409 file_found
    assert len(requests()) == count_before, "断ったのに要求の行が残っている"


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
    # **`GET` の口は無い**（読むのは `GET /api/pending-deletes` と `/api/deletions`）。
    # **（P10 の監査 D-3）404 か 405**——405 は「口はあるが GET は無い」。GUI の静的マウントが
    # あるかどうかで変わるので**両方を許し**、そのうえで**口そのものが在ること**を経路で見る
    # （`app.routes` は取り込んだルーターを畳まないので `openapi()` の経路を使う）
    paths = set(client.app.openapi()["paths"])
    assert "/api/deletions/{deletion_id}/advance" in paths, "口が無い"
    assert "/api/deletions/advance" in paths and "/api/deletions/close" in paths, "口が無い"
    assert client.get(f"/api/deletions/{deletion_id}/advance",
                      headers=HUMAN).status_code in (404, 405)
    assert client.get("/api/deletions/close", headers=HUMAN).status_code in (404, 405)


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


def test_the_advance_endpoints_name_the_way_that_works_when_the_move_is_denied(
        client, tmp_path, monkeypatch):
    """壊すと落ちる: 口（`POST /api/deletions/{id}/advance` と `/api/deletions/advance`）の
    **画面が読む本文**が古い。

    画面は `body.detail`（1 件）と `skipped[].message`（まとめて）をそのまま出す
    （`apps/gui/pending.js`）。どちらも**同じ案内**（2 文＋詳細）にする。**パスは本文に出さない**。
    """
    store, path, asset_id = register(client, tmp_path, "http-denied.png", seed=62)
    made = client.post("/api/locations/delete", headers=HUMAN,
                       json={"asset_id": asset_id, "path": str(path), "stage": 1}).json()
    deny_moves(monkeypatch)
    one = client.post(f"/api/deletions/{made['deletion_id']}/advance", headers=HUMAN,
                      json={"stage": 2})
    assert one.status_code == 409, one.text
    body = one.json()
    assert body["code"] == "move_failed", body
    assert body["detail"] == MOVE_FAILED_TEXT, body["detail"]
    assert str(path) not in body["detail"], "元のパスを本文に出している（読めない 1 行）"
    # **まとめて**（口は 200 で `skipped` に残す。断った数を黙って捨てない）
    many = client.post("/api/deletions/advance", headers=HUMAN,
                       json={"ids": [made["deletion_id"]], "stage": 2})
    assert many.status_code == 200, many.text
    out = many.json()
    assert out["count"] == 0 and out["skipped_count"] == 1, out
    assert out["skipped"][0]["reason"] == "move_failed", out["skipped"]
    assert out["skipped"][0]["message"] == MOVE_FAILED_TEXT, out["skipped"]
    assert path.exists(), "断られたのにファイルが動いた"


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
