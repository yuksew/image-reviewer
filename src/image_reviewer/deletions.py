"""削除の 3 段階と 5 分の窓（P8-2。設計 `docs/p8-design.md` §0.6・§0.7・§3.2〜§3.4・§4・§8.1）。

**利用者の実データのファイルを動かす・消す機能**なので、ここがこの段で一番危ない。
決めたこと（設計が正。破ったら壊れる物の順に書く）:

1. **触ってよいのは、登録済みの `asset_location` に実在するパスそのものだけ**（専門 §3.2 の 1）。
   照合は `normalize_path()` の**完全一致**だけ。**前方一致は使わない**（`C:\\img` が
   `C:\\img2\\x.png` を消せてしまう）。
2. **`os.rename` を使う**（**`os.replace` は既存のファイルを黙って上書きする**＝P7 の実測）。
   `FileExistsError`（WinError 183）は **409 `target_exists`** で止める。**1 バイトも壊さない。**
3. **段 3 は消さないで移す。** `<data>/pending-delete/<削除ID>/` へ移し、**5 分の窓**を置く。
   窓は**単調時計**（`Clock.monotonic()`）で数える（壁時計では数えない）。**起動時には消さない。**
4. **「最後の 1 つ」は軽い確認で消さない**（`last_copy`。`confirm_last_copy` を要求し、**1 枚も消さない**）。
5. **段 3 は `root.allow_stage3 = 1` の置き場だけ**（**既定は印なし**。Q8・点検 B7）。
6. **上限は `actor` ごと**: **エージェントは 1 回 200 枚**（超えたら **422 `too_many`** で
   **1 枚も消さない**＝**部分適用しない**）。**人に上限は無い**（点検 B1。preview が件数と
   合計バイトを見せるのが守り）。
7. **凍結した一覧だけを消す**（`pending_delete_preview`。**実行時に `scope` を評価し直さない**）。
8. **`undo` は人が誰の削除でも戻せる**（C-1。人が気づいて戻せるのがこの段の安全網）。
   **エージェントは自分の分だけ**（他人の分は **403 `not_yours`**。§3.4）。**`as_copy` は人だけ**
   （403 `human_only`）。**別名は `<名前>.<連番>.<拡張子>`**（専門 §3.3）。
9. **ファイル操作は取引の外**（家風）。取引は台帳の 1 行だけを短く。
10. **台帳の行を先に書いてから動かす**（B-1）。**動かせなければ行を消す。** 逆順だと、取引が
    失敗したときにファイルだけが移り、台帳にも要求にも残らず、一覧には「在る」と出続ける
    （`pending` / `trash` / `ledger` のどこにも出ない迷子になる）。**起動時に、台帳に無い
    `pending-delete/` の中身は「拾い物」として出す**（黙って残さない。消しはしない）。
11. **保留領域を消す前に読み取り専用の属性を外す**（C-2。付いたままだと `WinError 5` で
    30 秒ごとにやり直し続ける）。
12. **数を黙って捨てない**（`skipped` の理由・`frees`・`remaining_sec`・拾い物を返す）。
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import sqlite3
import stat
import threading
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator, Sequence

from . import db
from .clock import clock_of
from .review import ReviewError
from .store import is_under, normalize_path

log = logging.getLogger(__name__)

#: 段の語彙（`deletion_log.stage` の `CHECK` と同じ。**口でも守る**）
STAGES = (1, 2, 3)
#: 5 分の窓の既定（**`settings.undo_window_sec` が正**）
DEFAULT_UNDO_WINDOW_SEC = 300
#: 凍結の既定の有効期限（**`settings.preview_ttl_sec` が正**）
DEFAULT_PREVIEW_TTL_SEC = 600
#: **エージェントが 1 回の要求で消せる枚数**（Q2 の帰結 d。**人に上限は無い**）
AGENT_MAX_BATCH = 200
#: タイマーの周期（設計 §0.6-2「30 秒ごとに前回からの経過を引く」）
TICK_INTERVAL_SEC = 30.0
#: 保留領域（段 3）とゴミ箱（段 2）のフォルダ名
HOLD_DIR = "pending-delete"
TRASH_DIR = "trash"
#: **実体を消した印**（`deletion_log.hold_path` に入れる。§4.1「消えた印にする」）
HOLD_PURGED = "(削除済み)"
#: 一括削除の選び方（専門 §3.5 の 3 つ＋まとまり）
SCOPE_KINDS = ("assets", "folder", "group", "query")
#: 「最近の削除」の既定の件数（口の `limit`）
DEFAULT_LEDGER_LIMIT = 100
MAX_LEDGER_LIMIT = 1000
#: 失効した凍結を掃除するまでの猶予（**§2.1 の「1 時間ごと」を、線 8 の 409 を壊さない形にした**）
PREVIEW_KEEP_SEC = 86400
#: **落ちた要求の印**（`result_json` が無いまま残った `delete_request`。D-8）。
#: `self._lock` の中では「進行中」の要求は同時に居ないので、残っていれば落ちた物。
#: 念のため**この秒数より古い物だけ**を捨てて、同じ `client_token` の再送を許す。
STALE_REQUEST_SEC = 600
#: ゴミ箱のフォルダ名は**現地（JST）の日付**（D-3）。JST は夏時間が無いので固定の +9 時間。
JST_OFFSET_SEC = 9 * 3600
#: 拾い物（台帳に無い保留領域の中身）を `GET` に出す上限（**数は全部数える**）
FOUND_LIMIT = 200


# ---- 純関数に近い道具（テストが差し替えられる形にする）----


def st_dev_of(path) -> int:
    """その場所のボリュームの番号（**別ボリュームの判定はこれだけ**。設計 §0.6 の決定）。

    テストはこれを差し替えて「別ボリューム」を作る（§8.4 F5。CI に 2 つのボリュームは無い）。
    """
    return os.stat(path).st_dev


def same_volume(a, b) -> bool:
    """同じボリュームか（**違うなら段 2・段 3 は断る**。コピーもしない）。"""
    return st_dev_of(a) == st_dev_of(b)


def identity_of(path) -> tuple[int, int]:
    """`(size, mtime_ns)`。**実行の直前の再照合**に使う（専門 §3.2 の 2）。"""
    got = os.stat(path)
    return int(got.st_size), int(got.st_mtime_ns)


def free_name(directory: Path, name: str) -> Path:
    """`<名前>.<連番>.<拡張子>` で空いている名前を返す（専門 §3.3）。

    **ゴミ箱の中の衝突**と、**`as_copy` で別名に戻す**ときに使う。`os.rename` の
    `FileExistsError` に頼らず**先に空きを選ぶ**（人が選んだ別名なので、そこで失敗させない）。
    """
    candidate = directory / name
    if not candidate.exists():
        return candidate
    stem, ext = os.path.splitext(name)
    for n in range(1, 10000):
        candidate = directory / f"{stem}.{n}{ext}"
        if not candidate.exists():
            return candidate
    raise ReviewError(409, "空いている名前が見つかりません", code="target_exists",
                      details={"name": name, "dir": str(directory)})


def move_no_clobber(src, dst) -> str:
    """**`os.rename` で移す**（`os.replace` は**在ると黙って上書きする**＝P7 の実測）。

    Windows の `os.rename` は `MoveFileExW` を `MOVEFILE_REPLACE_EXISTING` **無し**で呼ぶので、
    在れば `FileExistsError`（WinError 183）になる。**事前の `exists` 検査は要らない**
    （検査と置き換えの間の競合が無い。設計 §0.6-4）。

    失敗は**動かさないまま**返す（元のファイルは 1 バイトも変わらない）。
    """
    try:
        os.rename(str(src), str(dst))
    except FileExistsError as exc:                                 # WinError 183
        raise ReviewError(409, "移動先に既にファイルがあります（上書きしません）",
                          code="target_exists",
                          details={"from": str(src), "to": str(dst)}) from exc
    except OSError as exc:
        raise ReviewError(409, f"ファイルを移動できません: {exc}", code="move_failed",
                          details={"from": str(src), "to": str(dst)}) from exc
    return str(dst)


def plus_seconds(iso: str, sec: int) -> str:
    """ISO（UTC・秒）に秒を足す（`purge_at` / `expires_at` の**目安の壁時計**）。

    書式が固定長で辞書順＝時刻順なので、**比較は文字列のまま**できる（`db.now()` と同じ形）。
    壊れた文字列が来たら**そのまま返す**（時計の都合で削除を止めない）。
    """
    try:
        base = datetime.strptime(iso, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return iso
    return (base + timedelta(seconds=int(sec))).strftime("%Y-%m-%dT%H:%M:%SZ")


def jst_day(iso: str) -> str:
    """UTC の ISO を**現地（JST）の `YYYYMMDD`** にする（D-3。ゴミ箱のフォルダ名）。

    `self.clock.now()` は UTC なので、そのまま日付を取ると **JST 02:30 の削除が
    `trash/20261017/`** に入る（利用者の画面とエクスプローラは現地時刻）。**JST は夏時間が
    無い**ので固定 +9 時間で足りる。壊れた文字列が来たら**日付らしき物をそのまま返す**。
    """
    try:
        base = datetime.strptime(str(iso)[:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return str(iso)[:10].replace("-", "")
    return (base + timedelta(seconds=JST_OFFSET_SEC)).strftime("%Y%m%d")


def frees_for(stage: int, *, size: int, window_sec: int, at: str | None) -> dict:
    """**何がいつ空くか**（§0.7。画面に出す。「消したのに空きが増えない」と思わせない）。

    段 1 は 0（カタログから外すだけ）／段 2 はゴミ箱の掃除まで／段 3 は**窓が過ぎた時点**。
    """
    if stage == 1:
        return {"stage": 1, "bytes": 0, "at": None,
                "note": "カタログから外すだけです（容量は空きません）"}
    if stage == 2:
        return {"stage": 2, "bytes": int(size), "at": None,
                "note": "ゴミ箱の掃除まで容量は空きません"}
    return {"stage": 3, "bytes": int(size), "at": at,
            "note": f"{max(1, window_sec // 60)} 分の窓が過ぎた時点で空きます"
                    "（アプリが動いていた時間で数えます）"}


def _stage_of(stage: Any) -> int:
    """段の語彙を検査する（**語彙外は 422**。`CHECK` に当てて 500 にしない）。

    **（D-6）`true` と `3.9` は通さない。** `int(True)` は 1、`int(3.9)` は 3 になるので、
    「確認のつもりで `true` を送った」人が**段 1 の論理削除を実行してしまう**。
    """
    if isinstance(stage, bool):
        raise ReviewError(422, "stage は 1 / 2 / 3 のいずれかです（真偽値は使えません）",
                          code="bad_stage", details={"stage": stage})
    try:
        got = int(stage)
    except (TypeError, ValueError):
        got = -1
    if isinstance(stage, float) and float(stage) != got:
        got = -1                                              # 3.9 は 3 に丸めない（D-6）
    if got not in STAGES:
        raise ReviewError(422, "stage は 1 / 2 / 3 のいずれかです", code="bad_stage",
                          details={"stage": stage})
    return got


def _actor_of(actor: Any) -> str:
    """`actor` の語彙を検査する（**語彙外は 422**。Q2 の帰結 a）。"""
    if actor not in ("human", "agent"):
        raise ReviewError(422, "actor は human / agent のいずれかです", code="bad_actor",
                          details={"actor": actor})
    return str(actor)


def _require_human(actor: str, what: str) -> str:
    """**人が要る操作の検査**（`as_copy` とゴミ箱からの復帰。家風「検査は 1 か所」）。"""
    if actor != "human":
        raise ReviewError(403, f"{what}は人だけができます", code="human_only",
                          details={"actor": actor})
    return actor


class DeletionService:
    """削除の 3 段階・凍結・取り消し・タイマー（§0.6・§0.7・§3.2）。

    操作は `self._lock` で直列化する（**同じ `client_token` の同時要求**と
    **同じファイルを掴み合う 2 本**を決定的にする。§8.4 F10）。
    ファイル操作は取引の外、DB は短い 1 取引（家風）。
    """

    def __init__(self, store, *, clock=None, interval: float = TICK_INTERVAL_SEC):
        self.store = store
        self.clock = clock_of(clock)
        self.data_dir = Path(store.data_dir)
        self.interval = float(interval)
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        # **起動のたびに単調時計を取り直す**（閉じている間は時間が進まない。専門 §3.4）
        self._last_tick = self.clock.monotonic()
        self._ticks = 0
        # **このプロセスが作った段 3 の行**の「生まれた時刻」（単調時計）。周期の引きすぎを防ぐ
        self._born: dict[str, float] = {}
        # **起動時に見つけた拾い物**（台帳に無い保留領域の中身。G-4。**消さない**）
        self._found: dict = {"items": [], "count": 0, "root": str(self.data_dir / HOLD_DIR)}

    # ---- タイマー（30 秒周期。**起動時には消さない**）----

    def start(self) -> None:
        """タイマーを張る。**この時点では何も消さない**（設計 §0.6-3・§1.2 の線 7）。

        **（G-4）起動時に、台帳に無い `pending-delete/` の中身を「拾い物」として記録し、
        警告に出す**（黙って残さない。**消しも動かしもしない**）。`GET /api/pending-deletes` の
        `found` に出るので、画面と監査が気づける。
        """
        self._found = self.found_in_hold()
        if self._found["count"]:
            log.warning("保留領域に台帳の無いファイルが %d 件あります（拾い物。消しません）: %s",
                        self._found["count"],
                        [i["path"] for i in self._found["items"][:5]])
        if self._thread is not None and self._thread.is_alive():
            return
        self._last_tick = self.clock.monotonic()
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="deletion-timer", daemon=True)
        self._thread.start()

    @contextmanager
    def scan_guard(self) -> Iterator[None]:
        """**走査の間、削除と取り消しを待たせる**（G-2・C-6。設計 §3.4 の `scan_running` の代わり）。

        `scan` は同期の口で `job` に行を作らないので「走査中」を判定する材料が無い（申し送り 2）。
        代わりに**同じ錠**を取る: 走査が歩いている間に削除・取り消しが割り込まないので、
        「走査中は消さない」も、**走査の最後の `mark_missing` が、戻したばかりの枚を
        参照切れにする**逆向きの事故も両方止まる。**待つだけ**で 409 は返さない。
        """
        with self._lock:
            yield

    def stop(self) -> None:
        """タイマーを止める（`lifespan` の終了側。**2 回呼んでも安全**）。"""
        self._stop.set()
        thread, self._thread = self._thread, None
        if thread is not None:
            thread.join(timeout=2.0)

    def _loop(self) -> None:
        while not self._stop.wait(self.interval):
            try:
                self.tick()
            except Exception:                                      # noqa: BLE001
                log.exception("削除のタイマーで失敗しました（次の周期でやり直します）")

    def tick(self) -> dict:
        """1 周期分: **前回からの経過（単調時計）を `remaining_sec` から引く**。

        - **`purge_at IS NULL` の行は触らない**（戻せなかった物。§0.6-3）
        - **起動直後の 1 回は消さない**（`_ticks <= 1`）。クラッシュで `remaining_sec` が 0 のまま
          残った行も、ここでは消さず**次の周期**に消す（専門 §3.4・§1.2 の線 7）
        - 期限切れの掃除は `_purge_expired()`（**ファイル操作は取引の外**）
        - **失効して久しい凍結**は `_sweep_previews()` が片づける（G-5）

        **（B-3）本体を `self._lock` で包む。** 包まないと、窓の最後の周期で `undo` と競合して
        「**ファイルは元の場所に在るのに `asset_location` の行が消え、台帳は『削除済み』**」に
        なる（監査が `threading.Event` で決定的に再現した）。
        """
        with self._lock:
            mono = self.clock.monotonic()
            delta = max(0.0, mono - self._last_tick)
            # **（D-11）端数は次の周期に繰り越す。** `int(delta)` で捨てると、30.9 秒の周期で
            # 0.9 秒ずつ**窓が延びる**（切り捨ては延びる側に倒れる）
            charge = int(delta)
            if charge > 0:
                self._last_tick += charge
            self._ticks += 1
            with self.store.locked() as con:
                rows = con.execute(
                    "SELECT id FROM deletion_log"
                    " WHERE stage = 3 AND restored_at IS NULL AND purge_at IS NOT NULL").fetchall()
            # **その行が生まれる前の経過は引かない。** 「前回の周期からの経過」をそのまま引くと、
            # 消した直後に来た周期で**最大 30 秒ぶん多く**引かれ、「あと 5:00」が数秒で 4:30 になる
            # （実機で 35 秒に 60 秒ぶん引かれた）。**このプロセスが作った行**は生まれてからの
            # 経過で上限を付ける（再起動をまたいだ行は設計どおり「前回からの経過」で引く）。
            alive = {row["id"] for row in rows}
            self._born = {k: v for k, v in self._born.items() if k in alive}
            with self.store.transaction() as con:
                for row in rows:
                    got = charge
                    born = self._born.get(row["id"])
                    if born is not None:
                        got = max(0, min(got, int(mono - born)))
                    con.execute("UPDATE deletion_log SET remaining_sec = max(0, remaining_sec - ?)"
                                " WHERE id = ?", (got, row["id"]))
            purged = self._purge_expired() if self._ticks > 1 else 0
            cleaned = self._sweep_previews()
            return {"ticks": self._ticks, "delta": charge, "decremented": len(rows),
                    "purged": purged, "previews_cleaned": cleaned, "first": self._ticks == 1}

    def _sweep_previews(self) -> int:
        """**失効してから十分に古い凍結だけ**を片づける（G-5。`PREVIEW_KEEP_SEC` = 1 日）。

        失効した凍結を**すぐ消さない**のは、線 8 の「10 分後に実行 → **409 `preview_expired`**」を
        守るため（消すと 404 になり「何も消さない」ことを確かめられない）。実行済みの行は
        `result_json` を返すために残す（§4.3）ので、**未実行で 1 日過ぎた物**だけを消す。
        """
        limit = plus_seconds(self.clock.now(), -PREVIEW_KEEP_SEC)
        with self.store.transaction() as con:
            cur = con.execute("DELETE FROM pending_delete_preview"
                              " WHERE executed_at IS NULL AND expires_at < ?", (limit,))
            return int(cur.rowcount or 0)

    def found_in_hold(self) -> dict:
        """**台帳に無い保留領域の中身**（G-4 の「拾い物」）。**読むだけ**（消さない・動かさない）。

        `pending-delete/` は**このツールが作った**場所なので、そこに台帳の無いファイルが在れば
        「移動は済んだが台帳に残らなかった」か「人が置いた」かのどちらか。**黙って残さず**、
        `GET /api/pending-deletes` の `found` に出して人に見せる（**消すかどうかは人が決める**）。
        """
        root = self.data_dir / HOLD_DIR
        if not root.exists():
            return {"items": [], "count": 0, "shown": 0, "root": str(root)}
        with self.store.locked() as con:
            known = {normalize_path(r["hold_path"]) for r in con.execute(
                "SELECT hold_path FROM deletion_log WHERE hold_path IS NOT NULL"
                "   AND hold_path <> ?", (HOLD_PURGED,))}
        items: list[dict] = []
        total = 0
        for path in sorted(root.rglob("*")):
            if not path.is_file() or normalize_path(path) in known:
                continue
            total += 1
            if len(items) >= FOUND_LIMIT:
                continue                                          # **数は全部数える**
            try:
                got = path.stat()
            except OSError:
                continue
            items.append({"path": str(path), "size": int(got.st_size),
                          "mtime_ns": int(got.st_mtime_ns)})
        return {"items": items, "count": total, "shown": len(items), "root": str(root)}

    def _purge_expired(self) -> int:
        """`remaining_sec <= 0` の保留を片づける（**段 3 の実削除はここだけ**）。

        **（点検 A3）窓の間は `asset_location` の行を消さない。** 消すのはここ——
        保留領域のファイルを消したときだけ。`hold_path` は「消えた印」にする（行は残す）。

        **（B-3）`self._lock` を取る**（`undo` と競合すると、戻したファイルの登録が消える）。
        **（B-1）台帳を先に書く順にした**ので、ここでは「保留の実体が無い行」も拾える:
        元の場所にファイルが在れば**動かす前に落ちた**（削除は起きていない）ので戻し、
        どちらにも無ければ**前の周期の実削除が途中で落ちた**ので後始末を完了する。
        """
        with self._lock:
            with self.store.locked() as con:
                rows = con.execute(
                    "SELECT id, asset_id, path, hold_path FROM deletion_log"
                    " WHERE stage = 3 AND restored_at IS NULL AND purge_at IS NOT NULL"
                    "   AND remaining_sec IS NOT NULL AND remaining_sec <= 0").fetchall()
            done = 0
            for row in rows:
                if row["hold_path"] == HOLD_PURGED:
                    continue
                # **（B-3）消す直前にもう一度見る**（取引の外でファイルを消すので、
                # その間に戻されていないことを確かめる）
                with self.store.locked() as con:
                    now_row = con.execute("SELECT restored_at, hold_path FROM deletion_log"
                                          " WHERE id = ?", (row["id"],)).fetchone()
                if (now_row is None or now_row["restored_at"]
                        or now_row["hold_path"] != row["hold_path"]):
                    continue
                if not os.path.exists(str(row["hold_path"] or "")):
                    if self._recover_missing_hold(row):
                        done += 1                                 # 後始末の完了＝実削除
                    continue
                try:
                    self._remove_hold(row["hold_path"])            # **取引の外**
                except OSError as exc:
                    log.warning("保留領域を消せませんでした（次の周期でやり直します）: %s", exc)
                    continue
                with self.store.transaction() as con:
                    cur = con.execute(
                        "UPDATE deletion_log SET hold_path = ? WHERE id = ? AND restored_at IS NULL",
                        (HOLD_PURGED, row["id"]))
                    if int(cur.rowcount or 0) == 0:
                        # **錠の下では起きない**（取引の間に戻されたら、消したファイルが戻せない）。
                        # 起きたら黙って進まず、警告に残す
                        log.error("実削除の直前に取り消されました（保留の実体は消えています）: %s",
                                  row["id"])
                        continue
                    if row["path"]:
                        con.execute("DELETE FROM asset_location WHERE path = ? AND asset_id = ?",
                                    (row["path"], row["asset_id"]))
                self._born.pop(row["id"], None)
                done += 1
            return done

    def _original_exists(self, row) -> bool:
        """その行の**元の場所にファイルが在るか**（B-1 の「動かす前に落ちた」の判定）。"""
        if not row["path"]:
            return False
        with self.store.locked() as con:
            loc = con.execute("SELECT display_path FROM asset_location WHERE path = ?",
                              (row["path"],)).fetchone()
        return bool(loc is not None and os.path.exists(str(loc["display_path"])))

    def _recover_missing_hold(self, row) -> bool:
        """**保留の実体が無い行**の後始末（B-1 の順序にしたことで増えた道）。

        - **元の場所にファイルが在る** → `rename` の前に落ちた（**削除は起きていない**）。
          **戻したことにする**（`restored_at` を立てる）。ファイルも登録もそのまま。
        - **どちらにも無い** → 前の周期の実削除が DB の前に落ちた。**後始末を完了する**
          （`asset_location` の行を消して `hold_path` を「消えた印」に）。

        どちらも**ファイルを 1 バイトも触らない**（消えた物は戻せないし、在る物は消さない）。
        """
        at = self.clock.now()
        if self._original_exists(row):
            log.warning("保留に移す前に落ちた行を戻しました（削除は起きていません）: %s", row["id"])
            with self.store.transaction() as con:
                con.execute("UPDATE deletion_log SET restored_at = ?, purge_at = NULL,"
                            " remaining_sec = NULL WHERE id = ? AND restored_at IS NULL",
                            (at, row["id"]))
                self._sync_hidden(con, row["asset_id"], at)
            self._born.pop(row["id"], None)
            return False                                          # 実削除ではない
        log.warning("保留の実体が無い行の後始末を完了します（前の周期が途中で落ちています）: %s",
                    row["id"])
        with self.store.transaction() as con:
            if row["path"]:
                con.execute("DELETE FROM asset_location WHERE path = ? AND asset_id = ?",
                            (row["path"], row["asset_id"]))
            con.execute("UPDATE deletion_log SET hold_path = ? WHERE id = ? AND restored_at IS NULL",
                        (HOLD_PURGED, row["id"]))
        self._born.pop(row["id"], None)
        return True

    def _remove_hold(self, hold_path: str | None) -> None:
        """保留領域のファイルとフォルダを消す。**`<data>/pending-delete/<削除ID>/` の下だけ**を触る。

        ここは**このツールが自分で作った一時領域**なので、印の付いた 1 本を消すだけでよい。

        - **（D-1）保留領域そのものは断る。** `is_under(root, root)` は True なので、渡されると
          `rmtree` が**他の保留を丸ごと巻き込む**（その後の `undo` が `restore_failed` になる）。
          **深さ 1（`<削除ID>/`）と 2（その中のファイル）だけ**を許す。
        - **（C-2）消す前に `S_IWRITE` を立てる**（読み取り専用の属性が付いたままだと
          `WinError 5` で毎周期やり直し続ける）。
        """
        if not hold_path:
            raise OSError("保留領域のパスがありません")
        root = self.data_dir / HOLD_DIR
        if not is_under(hold_path, root):
            raise OSError(f"保留領域の外は消しません: {hold_path}")
        rel = os.path.relpath(normalize_path(hold_path), normalize_path(root))
        depth = 0 if rel in (".", "") else len(Path(rel).parts)
        if depth not in (1, 2):
            raise OSError(f"保留領域そのもの（か、その外）は消しません: {hold_path}")
        target = Path(hold_path)
        if target.exists():
            self._make_writable(target)
            if target.is_dir():
                shutil.rmtree(target)
            else:
                target.unlink()
        parent = target.parent
        if parent != root and parent.exists() and not any(parent.iterdir()):
            parent.rmdir()                                          # 空になった <削除ID>/ を片づける

    @staticmethod
    def _make_writable(target: Path) -> None:
        """**読み取り専用の属性を外す**（C-2。**自分の保留領域の中だけ**）。

        他のツールが付けた `S_IREAD`（配布物・バックアップからの復元）のままだと `unlink` が
        `WinError 5` で失敗し、30 秒ごとに同じ警告を出し続ける。**外せなくても進む**
        （そのときは `unlink` の失敗がそのまま報告される）。
        """
        paths = [target]
        if target.is_dir():
            paths += list(target.rglob("*"))
        for path in paths:
            try:
                if not path.stat().st_mode & stat.S_IWRITE:
                    os.chmod(path, path.stat().st_mode | stat.S_IWRITE)
            except OSError:
                continue

    # ---- 読み（**`GET` は 1 バイトも書かない**。`remaining_sec` も減らさない）----

    def pending(self, *, actor: str = "human") -> dict:
        """**取り消せる削除**（段 3 の保留）の一覧（§3.2 の `GET /api/pending-deletes`）。

        **残り時間を減らさない**（減らすのはタイマー。§0.13）。`mine` は「自分が消した物か」で、
        画面はこれで「戻す」を押せるかどうかを決める（§5・点検 G2）。**人は誰の分でも戻せる**
        ので `undoable` は人なら常に真（C-1）。

        **（G-4）台帳に無い `pending-delete/` の中身を `found`（拾い物）として出す**（読むだけ）。
        """
        _actor_of(actor)
        with self.store.locked() as con:
            rows = con.execute(
                "SELECT d.*, l.display_path AS loc_display FROM deletion_log d"
                "   LEFT JOIN asset_location l ON l.path = d.path"
                " WHERE d.stage = 3 AND d.restored_at IS NULL"
                "   AND d.hold_path IS NOT NULL AND d.hold_path <> ?"
                " ORDER BY d.at DESC, d.id DESC", (HOLD_PURGED,)).fetchall()
            window = self._setting(con, "undo_window_sec", DEFAULT_UNDO_WINDOW_SEC)
        items = [self._log_doc(row, actor=actor) for row in rows]
        found = self.found_in_hold()
        return {"items": items, "count": len(items), "window_sec": window,
                "pending": sum(1 for i in items if i["state"] == "pending"),
                "found": found["items"], "found_count": found["count"]}

    def ledger(self, *, limit: int = DEFAULT_LEDGER_LIMIT, actor: str = "human") -> dict:
        """**最近の削除**（削除の台帳。段 1〜3 の全部。§3.2）。**読むだけ**。"""
        _actor_of(actor)
        if not 1 <= int(limit) <= MAX_LEDGER_LIMIT:
            raise ReviewError(422, f"limit は 1〜{MAX_LEDGER_LIMIT} です", details={"limit": limit})
        with self.store.locked() as con:
            rows = con.execute(
                "SELECT d.*, l.display_path AS loc_display FROM deletion_log d"
                "   LEFT JOIN asset_location l ON l.path = d.path"
                " ORDER BY d.at DESC, d.id DESC LIMIT ?",
                (int(limit),)).fetchall()
            total = con.execute("SELECT count(*) AS n FROM deletion_log").fetchone()["n"]
            window = self._setting(con, "undo_window_sec", DEFAULT_UNDO_WINDOW_SEC)
        items = [self._log_doc(row, actor=actor) for row in rows]
        return {"items": items, "count": len(items), "total": int(total),
                "limit": int(limit), "window_sec": window,
                "pending": sum(1 for i in items if i["state"] == "pending")}

    def trash(self, *, actor: str = "human") -> dict:
        """**ゴミ箱**（段 2 で移した物。日付ごと。§3.2 / §4.1）。**メインの一覧とは別**。"""
        _actor_of(actor)
        with self.store.locked() as con:
            rows = con.execute(
                "SELECT d.*, l.display_path AS loc_display FROM deletion_log d"
                "   LEFT JOIN asset_location l ON l.path = d.path"
                " WHERE d.stage = 2 AND d.restored_at IS NULL"
                " ORDER BY d.at DESC, d.id DESC").fetchall()
        days: dict[str, dict] = {}
        for row in rows:
            day = self._trash_day(row["to_path"]) or (row["at"] or "")[:10].replace("-", "")
            got = days.setdefault(day, {"date": day, "items": [], "count": 0, "bytes": 0})
            got["items"].append(self._log_doc(row, actor=actor))
            got["count"] += 1
            got["bytes"] += int(row["size"] or 0)
        ordered = [days[k] for k in sorted(days, reverse=True)]
        return {"days": ordered, "count": len(rows),
                "bytes": sum(int(r["size"] or 0) for r in rows)}

    def preview_of(self, preview_id: str, *, actor: str = "human") -> dict:
        """凍結した一覧（**実行時に `scope` を評価し直さない**ことを確かめられる形で返す）。

        **（D-5）`actor` を見る**（他の口と同じく語彙外は 422。見ないと `robot` で 200 になる）。
        """
        _actor_of(actor)
        with self.store.locked() as con:
            row = con.execute("SELECT * FROM pending_delete_preview WHERE id = ?",
                              (preview_id,)).fetchone()
        if row is None:
            raise ReviewError(404, "その凍結はありません", details={"preview_id": preview_id})
        return self._preview_doc(row)

    # ---- 段 1〜3（1 件）----

    def delete(self, *, asset_id: str | None, path: str, stage: int,
               reason: str | None = None, client_token: str | None = None,
               confirm_last_copy: bool = False, actor: str = "human") -> dict:
        """1 件を段 1〜3 で消す（§3.2 の `POST /api/locations/delete`）。

        **`DELETE` ではなく `POST`**（本文を持たせるため。§0.15 の 1）。
        同じ `client_token` の再送は **200 で前の結果**（`replayed: true`）。

        **（D-13）`path` の欠落は 422**（`not_registered` に混ぜない。入力の不足は入力の誤り）。
        """
        stage = _stage_of(stage)
        _actor_of(actor)
        if not str(path or "").strip():
            raise ReviewError(422, "path が要ります", code="bad_path", details={"path": path})
        payload = {"kind": "asset", "asset_id": str(asset_id or ""),
                   "path": normalize_path(path), "stage": stage}
        with self._lock:
            replay = self._replay(client_token, payload)
            if replay is not None:
                return replay
            target = self._target(asset_id, path)                   # 409 not_registered
            request_id = self._open_request(actor=actor, stage=stage, count=1,
                                           client_token=client_token, payload=payload)
            try:
                result = self._perform(target, stage, actor=actor, reason=reason,
                                       request_id=request_id,
                                       permit_last_copy=bool(confirm_last_copy))
            except BaseException:
                # **断った要求は残さない**（残すと同じ token の再送が「進行中」に見える）
                self._drop_request(request_id)
                raise
            result.setdefault("replayed", False)
            self._close_request(request_id, count=1, result=result)
            return result

    def _perform(self, target: dict, stage: int, *, actor: str, reason: str | None,
                 request_id: str, permit_last_copy: bool,
                 frozen: dict | None = None) -> dict:
        """1 件を実行する（**単発も一括もこの道を通る**。規則を 2 か所に書かない）。

        段 1 はファイルに触らない。段 2・段 3 は**実行の直前に `(size, mtime_ns)` を再照合**し
        （**凍結した値とも比べる**。C-5）、段 3 は**最後の 1 つ**と**置き場の印**を確かめる
        （足りなければ `ReviewError`）。

        **（B-1）台帳の行を先に書いてから動かす。** 動かせなければ行を消す（`_drop_log`）。
        逆順だと、取引が失敗したときに**ファイルだけが移り、台帳にも要求にも残らない**——
        一覧には「在る」と出続け、`pending` / `trash` / `ledger` のどこにも出ない迷子になる。
        """
        at = self.clock.now()
        if stage == 1:
            already = self._live_stage1(target)
            if already is not None:
                # **（D-12）同じ場所を 2 回外しても行を増やさない。** 増やすと、1 回戻しても
                # もう 1 行が生きていて「戻したのに一覧に出ない」になる
                return self._stage1_doc(already, target=target, replayed=True)
            deletion_id = db.ulid()
            with self.store.transaction() as con:
                self._write_log(con, deletion_id=deletion_id, target=target, stage=1, actor=actor,
                                reason=reason, request_id=request_id, size=target["size"], at=at)
                self._sync_hidden(con, target["asset_id"], at)
            return {"deletion_id": deletion_id, "stage": 1, "asset_id": target["asset_id"],
                    "path": target["path"], "display_path": target["display_path"],
                    "actor": actor, "at": at, "remaining_sec": None, "purge_at": None,
                    "frees": frees_for(1, size=target["size"], window_sec=0, at=None),
                    "replayed": False}
        self._require_file(target, frozen=frozen)
        if stage == 3:
            self._require_last_copy(target, permit=permit_last_copy)
            self._require_stage3_root(target["display_path"])
        deletion_id = db.ulid()
        dest_dir, dest = self._destination(target, stage, deletion_id)
        hold_path = str(dest) if stage == 3 else None
        to_path = str(dest) if stage == 2 else None
        window = self._window_sec()
        purge_at = plus_seconds(at, window) if stage == 3 else None
        # **（B-1）先に台帳の 1 行を書く**（`restored_at` は NULL・`hold_path` / `to_path` 込み）。
        # ここで落ちても「保留に在る」が台帳に残るので、`pending` に出て人が拾える
        with self.store.transaction() as con:
            self._write_log(con, deletion_id=deletion_id, target=target, stage=stage, actor=actor,
                            reason=reason, request_id=request_id, size=target["size"], at=at,
                            from_path=target["path"], to_path=to_path, hold_path=hold_path,
                            remaining_sec=window if stage == 3 else None, purge_at=purge_at)
        try:
            move_no_clobber(target["display_path"], dest)           # **取引の外**
        except BaseException:
            self._drop_log(deletion_id, dest_dir)                   # **動かせなければ行を消す**
            raise
        with self.store.transaction() as con:
            con.execute("UPDATE asset_location SET missing_at = ? WHERE path = ? AND asset_id = ?",
                        (at, target["path"], target["asset_id"]))
            self._sync_hidden(con, target["asset_id"], at)
        if stage == 3:
            # この行が生まれた時刻（単調時計）。**次の周期で引きすぎない**ための基準（`tick`）
            self._born[deletion_id] = self.clock.monotonic()
        out = {"deletion_id": deletion_id, "stage": stage, "asset_id": target["asset_id"],
               "path": target["path"], "display_path": target["display_path"], "actor": actor,
               "at": at, "size": int(target["size"]),
               "frees": frees_for(stage, size=target["size"], window_sec=window, at=purge_at)}
        if stage == 2:
            out.update({"from_path": target["path"], "to_path": to_path})
        else:
            out.update({"hold_path": hold_path, "remaining_sec": window, "purge_at": purge_at,
                        "window_sec": window,
                        "undo_path": f"/api/pending-deletes/{deletion_id}/undo"})
        return out

    def _live_stage1(self, target: dict):
        """**同じ場所を既に段 1 で外しているか**（D-12。2 回目は行を増やさない）。"""
        with self.store.locked() as con:
            return con.execute(
                "SELECT * FROM deletion_log WHERE stage = 1 AND restored_at IS NULL"
                "   AND asset_id = ? AND path = ? ORDER BY at DESC, id DESC LIMIT 1",
                (target["asset_id"], target["path"])).fetchone()

    @staticmethod
    def _stage1_doc(row, target: dict, *, replayed: bool) -> dict:
        """**既に外している場所**の段 1 の結果（新しい行は書かない）。"""
        return {"deletion_id": row["id"], "stage": 1, "asset_id": row["asset_id"],
                "path": row["path"], "display_path": target["display_path"],
                "actor": row["actor"], "at": row["at"], "remaining_sec": None, "purge_at": None,
                "frees": frees_for(1, size=int(row["size"] or 0), window_sec=0, at=None),
                "replayed": replayed}

    def _drop_log(self, deletion_id: str, dest_dir: Path | None = None) -> None:
        """**動かせなかった台帳の行**を消す（B-1。`_drop_request` と同じ形）。

        **`restored_at` が立っている行は消さない**（取り消しの記録を消さない）。
        作った移動先のフォルダが空なら片づける（`cross_volume` のときと同じ後始末）。
        """
        with self.store.transaction() as con:
            con.execute("DELETE FROM deletion_log WHERE id = ? AND restored_at IS NULL",
                        (deletion_id,))
        self._born.pop(deletion_id, None)
        if dest_dir is not None:
            self._prune_empty(dest_dir)

    def _prune_empty(self, path: Path) -> None:
        """**空になった入れ物を `<data>` の手前まで片づける**（`<data>` は消さない）。

        `_drop_log` と `cross_volume` の後始末に使う（**断ったのに空の
        `pending-delete/<id>/` や `trash/<日付>/` が残る**のを防ぐ。D-7）。
        中身が在ればそこで止まる（他の保留を消さない）。
        """
        current = path
        while normalize_path(current) != normalize_path(self.data_dir):
            try:
                if not current.is_dir() or any(current.iterdir()):
                    return
                current.rmdir()
            except OSError:
                return
            current = current.parent

    def _destination(self, target: dict, stage: int, deletion_id: str) -> tuple[Path, Path]:
        """移動先（段 2 = ゴミ箱 / 段 3 = 保留領域）。**別ボリュームなら 409 `cross_volume`**。

        **同じボリュームでなければ断る**（コピーになり、大きいファイルで待たされ、途中で
        失敗すると中途半端になる。専門 §3.4・設計 §0.6 の決定）。**コピーもしない。**

        **（D-7）ボリュームの判定を先に**やり、断ったときは作った入れ物を片づける
        （`cross_volume` の後に空の `pending-delete/<id>/` や `trash/<日付>/` が残らない）。
        **（D-3）ゴミ箱の日付は現地（JST）**。
        """
        name = Path(target["display_path"]).name
        base = self.data_dir / (TRASH_DIR if stage == 2 else HOLD_DIR)
        base.mkdir(parents=True, exist_ok=True)
        if not same_volume(target["display_path"], base):
            self._prune_empty(base)                # **空なら**片づける（他の保留が在れば残る）
            raise ReviewError(409, "この置き場は保留領域と別のボリュームです"
                                   "（コピーになるので、いまはアプリから消せません。"
                                   "エクスプローラで消してください）",
                              code="cross_volume",
                              details={"path": target["display_path"], "hold": str(base)})
        if stage == 2:
            # 専門 §3.3: `<data>/trash/<YYYYMMDD>/<sha256[0:2]>/<元のファイル名>`
            directory = base / jst_day(self.clock.now()) / (str(target.get("sha256") or "00")[:2])
        else:
            directory = base / deletion_id
        directory.mkdir(parents=True, exist_ok=True)
        return directory, free_name(directory, name)

    def _require_file(self, target: dict, *, frozen: dict | None = None) -> None:
        """**登録した時と同じファイルか**を確かめる（専門 §3.2 の 1・2）。

        段 2・3 は**ファイルを動かす**ので、ここを外すと**別のファイルを消す**。

        **（C-5）凍結した `(size, mtime_ns)` も比べる。** §0.7 の「実行の直前に 1 件ずつ再照合」は
        **凍結した一覧の値**と**いまの実ファイル**の両方に対して行う（凍結の値を一度も見ないなら、
        凍結に入れる意味が無い）。
        """
        path = target["display_path"]
        if target.get("missing_at"):
            raise ReviewError(409, "その場所は既に参照切れです", code="not_registered",
                              details={"path": path})
        if not os.path.exists(path):
            raise ReviewError(409, "実体が見つかりません", code="not_registered",
                              details={"path": path})
        if frozen is not None:
            fsize, fmtime = frozen.get("size"), frozen.get("mtime_ns")
            if fsize is not None and fmtime is not None and (
                    int(fsize) != int(target["size"]) or int(fmtime) != int(target["mtime_ns"])):
                raise ReviewError(409, "確認した一覧の登録と変わっています（もう一度 preview してください）",
                                  code="changed",
                                  details={"path": path,
                                           "frozen": {"size": int(fsize), "mtime_ns": int(fmtime)},
                                           "now": {"size": int(target["size"]),
                                                   "mtime_ns": int(target["mtime_ns"])}})
        size, mtime_ns = identity_of(path)
        if int(target["size"]) != size or int(target["mtime_ns"]) != mtime_ns:
            raise ReviewError(409, "登録した時と中身が変わっています（別のファイルを消しかけています）",
                              code="changed",
                              details={"path": path,
                                       "registered": {"size": int(target["size"]),
                                                      "mtime_ns": int(target["mtime_ns"])},
                                       "now": {"size": size, "mtime_ns": mtime_ns}})

    def _require_last_copy(self, target: dict, *, permit: bool) -> None:
        """**最後の 1 つ**なら重い確認を要求する（`confirm_last_copy`。§3.4 の `last_copy`）。

        **1 枚も消さない**（ファイルも DB も触らない）。
        """
        if permit:
            return
        live = self._live_locations(target["asset_id"])
        if live <= 1:
            raise ReviewError(
                409, "これが最後の 1 つです（消すと内容そのものが失われます）。"
                     "confirm_last_copy: true が要ります",
                code="last_copy",
                details={"asset_id": target["asset_id"], "path": target["display_path"],
                         "live_locations": live})

    def _require_stage3_root(self, display_path: str) -> None:
        """**段 3 は `root.allow_stage3 = 1` の置き場だけ**（Q8・点検 B7。**既定は印なし**）。

        印が無ければ **409 `stage_not_allowed`**（段 1・2 は通る）。**どの root にも入っていない
        場所も許さない**（印が無いのと同じ扱い。§0.6-6 の帰結）。
        """
        with self.store.locked() as con:
            if self._stage3_ok(con, display_path):
                return
            roots = [r for r in self._stage3_roots(con) if is_under(display_path, r["root"])]
        raise ReviewError(
            409, "この置き場では実ファイルの削除（段 3）を許していません"
                 "（別のツールの管理下かもしれません。段 1・2 は使えます）",
            code="stage_not_allowed", details={"path": display_path, "roots": roots})

    # ---- 一括（凍結 → 実行。§0.7）----

    def bulk_preview(self, *, scope: dict | None, stage: int, actor: str = "human") -> dict:
        """対象を**凍結**する（§3.2 の `preview`）。実行時に評価し直さないための一覧。

        **エージェントは 200 枚を超えたら 422 `too_many`**（人に上限は無い。点検 B1）。
        `last_copies` は「**最後の 1 つになる枚数**」（消すと内容が失われる物）。
        **（D-2）段 3 では `not_allowed`（印の無い置き場の枚）も返す**（実行で初めて
        `stage_not_allowed` になる枚を「消えます」と見せない）。
        **（D-9）段 3 の `frees.at` は `null`**（いつ空くかは実行してから決まる。凍結の失効時刻は
        「5 分の窓が過ぎた時点」ではない）。
        """
        stage = _stage_of(stage)
        _actor_of(actor)
        now = self.clock.now()
        with self.store.locked() as con:
            items = self._resolve_scope(con, scope)
            last_copies = self._count_last_copies(con, items)
            ttl = self._setting(con, "preview_ttl_sec", DEFAULT_PREVIEW_TTL_SEC)
            not_allowed = ([self._item_doc(i) for i in items
                            if not self._stage3_ok(con, i["display_path"])]
                           if stage == 3 else [])
        if actor == "agent" and len(items) > AGENT_MAX_BATCH:
            raise ReviewError(422, f"エージェントが 1 回に消せるのは {AGENT_MAX_BATCH} 枚までです",
                              code="too_many",
                              details={"count": len(items), "limit": AGENT_MAX_BATCH})
        preview_id = db.ulid()
        total = sum(int(i["size"]) for i in items)
        expires_at = plus_seconds(now, ttl)
        with self.store.transaction() as con:
            con.execute(
                "INSERT INTO pending_delete_preview(id, stage, scope_json, items_json, count,"
                " bytes, actor, created_at, expires_at) VALUES (?,?,?,?,?,?,?,?,?)",
                (preview_id, stage, json.dumps(scope or {}, ensure_ascii=False),
                 json.dumps(items, ensure_ascii=False), len(items), total, actor, now, expires_at))
        return {"preview_id": preview_id, "stage": stage, "items": items, "count": len(items),
                "bytes": total, "last_copies": last_copies, "expires_at": expires_at,
                "not_allowed": not_allowed, "not_allowed_count": len(not_allowed),
                "frees": frees_for(stage, size=total, window_sec=self._window_sec(), at=None),
                "scope": scope or {}, "actor": actor, "created_at": now}

    def bulk_delete(self, *, preview_id: str, confirm: bool = False,
                    client_token: str | None = None, confirm_last_copy: bool = False,
                    actor: str = "human") -> dict:
        """**凍結した一覧だけ**を実行する（§3.2 の `bulk-delete`）。

        - 失効していれば **409 `preview_expired`**（**何も消さない**）
        - **（C-4）段 3 で** `last_copies > 0` なら `confirm_last_copy: true` が要る
          （**409 `last_copy`**）。段 1・2 は**内容が失われない**ので要求しない
          （実データは全枚が最後の 1 つなので、段 1 の一括まで毎回重い確認になっていた）
        - 実行の直前に 1 件ずつ **凍結した値と** `(size, mtime_ns)` を再照合し、
          **食い違った 1 件だけ `skipped`** にして**残りは消す**（専門 §3.2 の 2・§3.5）
        - 同じ `preview_id` の 2 度目は**前の結果を返す**（凍結を 2 回消さない）
        """
        _actor_of(actor)
        if not confirm:
            raise ReviewError(422, "confirm: true が要ります", code="confirm_required",
                              details={"preview_id": preview_id})
        payload = {"kind": "bulk", "preview_id": str(preview_id)}
        with self._lock:
            replay = self._replay(client_token, payload)
            if replay is not None:
                return replay
            with self.store.locked() as con:
                row = con.execute("SELECT * FROM pending_delete_preview WHERE id = ?",
                                  (preview_id,)).fetchone()
                if row is None:
                    raise ReviewError(404, "その凍結はありません", details={"preview_id": preview_id})
                executed, stored = row["executed_at"], row["result_json"]
                items = json.loads(row["items_json"] or "[]")
                stage = int(row["stage"])
                expires_at = row["expires_at"]
                last_copies = self._count_last_copies(con, items)
            if executed and stored:
                return {**json.loads(stored), "replayed": True}
            if actor == "agent" and len(items) > AGENT_MAX_BATCH:
                raise ReviewError(
                    422, f"エージェントが 1 回に消せるのは {AGENT_MAX_BATCH} 枚までです",
                    code="too_many", details={"count": len(items), "limit": AGENT_MAX_BATCH})
            if self.clock.now() > str(expires_at):
                raise ReviewError(409, "確認した一覧の有効期限が切れました。もう一度 preview してください",
                                  code="preview_expired",
                                  details={"preview_id": preview_id, "expires_at": expires_at})
            if stage == 3 and last_copies and not confirm_last_copy:
                raise ReviewError(
                    409, f"この一括には最後の 1 つが {last_copies} 枚あります。"
                         "confirm_last_copy: true が要ります",
                    code="last_copy", details={"last_copies": last_copies})
            request_id = self._open_request(actor=actor, stage=stage, count=len(items),
                                            client_token=client_token, payload=payload)
            deleted: list[dict] = []
            skipped: list[dict] = []
            bytes_done = 0
            try:
                for item in items:
                    try:
                        target = self._target(item.get("asset_id"), item.get("path"))
                        got = self._perform(target, stage, actor=actor, reason=None,
                                            request_id=request_id, permit_last_copy=True,
                                            frozen=item)
                    except ReviewError as exc:
                        skipped.append({**self._item_doc(item), "reason": exc.code or "refused",
                                        "message": exc.detail})
                        continue
                    except Exception as exc:                        # noqa: BLE001  1 件で全体を止めない
                        skipped.append({**self._item_doc(item), "reason": "failed",
                                        "message": f"{type(exc).__name__}: {exc}"})
                        continue
                    deleted.append({**self._item_doc(item), "deletion_id": got["deletion_id"],
                                    "stage": stage})
                    bytes_done += int(item.get("size") or 0)
            except BaseException:
                self._drop_request(request_id)
                raise
            result = {"preview_id": preview_id, "stage": stage, "deleted": deleted,
                      "skipped": skipped, "count": len(deleted), "bytes": bytes_done,
                      "requested": len(items), "replayed": False}
            with self.store.transaction() as con:
                con.execute("UPDATE pending_delete_preview SET executed_at = ?, result_json = ?,"
                            " request_id = ? WHERE id = ?",
                            (self.clock.now(), json.dumps(result, ensure_ascii=False),
                             request_id, preview_id))
            self._close_request(request_id, count=len(items), result=result)
            return result

    # ---- 取り消し（段 3 の窓・段 2 のゴミ箱・段 1 の印）----

    def undo(self, deletion_id: str, *, as_copy: bool = False, actor: str = "human") -> dict:
        """取り消す（§3.2 の `undo`）。**`os.rename` で戻す**（上書きしない）。

        - **（C-1）人は誰の削除でも戻せる**（人が気づいて戻せるのがこの段の安全網。
          Q2 の帰結 e・点検 G-1）。**エージェントは自分が消した物だけ**（他人の分は
          **403 `not_yours`**。§3.4）
        - **`as_copy` は人だけ**（403 `human_only`）。別名は `<名前>.<連番>.<拡張子>`
        - 元の場所が埋まっていれば **409 `target_exists`** で**止めて尋ねる**／動かせなければ
          **409 `move_failed`**。**どちらも `purge_at` を NULL にして自動削除から外す**
          （尋ねている間・失敗したまま窓が尽きて**黙って消える**のを防ぐ。§0.6-4・B-2）
        """
        _actor_of(actor)
        if as_copy:
            _require_human(actor, "別名で戻すこと")
        with self._lock:
            return self._restore(deletion_id, as_copy=as_copy, actor=actor,
                                 check_owner=(actor != "human"))

    def trash_restore(self, deletion_id: str, *, actor: str = "human") -> dict:
        """**ゴミ箱から戻す**（§3.2 の `POST /api/trash/restore`。**人だけ**）。

        ゴミ箱は人の口なので「他人の分」は無い（`not_yours` は掛けない）。
        """
        _actor_of(actor)
        _require_human(actor, "ゴミ箱から戻すこと")
        with self._lock:
            return self._restore(deletion_id, as_copy=False, actor=actor, check_owner=False)

    def purge_now(self, deletion_id: str, *, confirm: bool = False, actor: str = "human") -> dict:
        """**「いま消す」**（保留領域のファイルを今すぐ消す。**人だけ**）。

        §5 の画面は「戻せませんでした」の行に**「いま消す」**を出す（専門 §3.4:
        「利用者が明示的に『消す』を選ぶか、もう一度『戻す』を試すまで、このツールはこのファイルに
        触らない」）。**その押し先が設計の口の表に無かった**ので、ここに足した（記録に申し送り）。
        `remaining_sec` を 0 にしてからタイマーと同じ道（`_purge_expired`）で消す。

        **（C-2）消せなかったとき（`PermissionError` を含む `OSError`）は 409 `purge_failed`**
        （500 にしない。「消せませんでした」と正直に返す）。
        """
        _require_human(actor, "いま消すこと")
        if not confirm:
            raise ReviewError(422, "confirm: true が要ります", code="confirm_required",
                              details={"deletion_id": deletion_id})
        with self._lock:
            with self.store.locked() as con:
                row = con.execute("SELECT * FROM deletion_log WHERE id = ?",
                                  (deletion_id,)).fetchone()
            if row is None or int(row["stage"]) != 3:
                raise ReviewError(404, "その削除はありません", details={"deletion_id": deletion_id})
            if row["restored_at"]:
                raise ReviewError(409, "既に戻しています", code="already_restored",
                                  details={"deletion_id": deletion_id})
            if row["hold_path"] == HOLD_PURGED:
                raise ReviewError(409, "既に実体を消しています", code="already_purged",
                                  details={"deletion_id": deletion_id})
            if not os.path.exists(str(row["hold_path"] or "")):
                # **（B-1）台帳を先に書く順で増えた道**: 移動の前に落ちた行。ここで登録だけ
                # 消すと「消した」と言いながらファイルが元の場所に残るので、正直に断る
                raise ReviewError(409, "保留領域に実体がありません（元の場所に在るかもしれません）。"
                                       "「戻す」を試してください",
                                  code="not_in_hold",
                                  details={"deletion_id": deletion_id, "hold_path": row["hold_path"]})
            try:
                self._remove_hold(row["hold_path"])
            except OSError as exc:
                raise ReviewError(409, f"保留領域のファイルを消せません: {exc}",
                                  code="purge_failed",
                                  details={"deletion_id": deletion_id,
                                           "hold_path": row["hold_path"]}) from exc
            with self.store.transaction() as con:
                if row["path"]:
                    con.execute("DELETE FROM asset_location WHERE path = ? AND asset_id = ?",
                                (row["path"], row["asset_id"]))
                con.execute("UPDATE deletion_log SET hold_path = ?, remaining_sec = 0, purge_at = ?"
                            " WHERE id = ? AND restored_at IS NULL",
                            (HOLD_PURGED, self.clock.now(), deletion_id))
        self._born.pop(deletion_id, None)
        return {"deletion_id": deletion_id, "purged": True, "asset_id": row["asset_id"],
                "path": row["path"], "actor": actor}

    def _restore(self, deletion_id: str, *, as_copy: bool, actor: str,
                 check_owner: bool) -> dict:
        """戻す本体（段 1〜3 で道が違う）。**動かす前に検査し、失敗したら 1 バイトも変えない。**"""
        with self.store.locked() as con:
            row = con.execute("SELECT * FROM deletion_log WHERE id = ?",
                              (deletion_id,)).fetchone()
            loc = None
            if row is not None and row["path"]:
                loc = con.execute("SELECT * FROM asset_location WHERE path = ?",
                                  (row["path"],)).fetchone()
        if row is None:
            raise ReviewError(404, "その削除はありません", details={"deletion_id": deletion_id})
        if check_owner and row["actor"] != actor:
            raise ReviewError(403, "自分が消した物だけ戻せます", code="not_yours",
                              details={"deletion_id": deletion_id, "actor": row["actor"]})
        if row["restored_at"]:
            raise ReviewError(409, "既に戻しています", code="already_restored",
                              details={"deletion_id": deletion_id, "restored_at": row["restored_at"]})
        stage = int(row["stage"])
        source = row["hold_path"] if stage == 3 else row["to_path"]
        destination = self._restore_destination(row, loc)
        if stage != 1:
            if not source:
                raise ReviewError(409, "戻す元の場所が台帳にありません", code="restore_failed",
                                  details={"deletion_id": deletion_id})
            if stage == 3 and source == HOLD_PURGED:
                raise ReviewError(409, "実体は既に消えています（戻せません）", code="already_purged",
                                  details={"deletion_id": deletion_id})
            if not os.path.exists(source):
                if os.path.exists(str(destination)):
                    # **（B-1）台帳を先に書く順で増えた道**: 移動の前に落ちた（削除は起きていない）。
                    # **ファイルは元の場所に在る**ので、戻したことにする（1 バイトも触らない）
                    return self._mark_recovered(row, at=self.clock.now(), actor=actor)
                self._mark_unrestorable(deletion_id)
                raise ReviewError(409, "保留していたファイルが見つかりません（戻せませんでした）",
                                  code="restore_failed",
                                  details={"deletion_id": deletion_id, "source": source})
        at = self.clock.now()
        if as_copy:
            destination = self._free_db_name(destination)
        if stage != 1:
            try:
                move_no_clobber(source, destination)                # **取引の外**・上書きしない
            except ReviewError as exc:
                if exc.code in ("target_exists", "move_failed"):
                    # **止めて尋ねる**（`as_copy` で送り直す）／**動かせなかった**。
                    # **どちらも `purge_at` を NULL にする**（§0.6-4 の失敗の規則。専門 §3.4
                    # 「取り消し自体が失敗したときは…自動削除の対象から完全に外す」＝ B-2）
                    self._mark_unrestorable(deletion_id)
                raise
        with self.store.transaction() as con:
            if stage != 1 and loc is not None:
                key = normalize_path(destination)
                if as_copy:
                    # 別名で戻したので**登録もその名前へ付け替える**（さもないと登録が実体を指さない）
                    con.execute("UPDATE asset_location SET path = ?, display_path = ?,"
                                " missing_at = NULL, last_seen_at = ? WHERE path = ?",
                                (key, str(destination), at, row["path"]))
                else:
                    con.execute("UPDATE asset_location SET missing_at = NULL, last_seen_at = ?"
                                " WHERE path = ?", (at, row["path"]))
            con.execute("UPDATE deletion_log SET restored_at = ?, purge_at = NULL,"
                        " remaining_sec = NULL WHERE id = ?", (at, deletion_id))
            self._sync_hidden(con, row["asset_id"], at)
        self._born.pop(deletion_id, None)
        return {"deletion_id": deletion_id, "restored": True, "stage": stage,
                "asset_id": row["asset_id"], "as_copy": bool(as_copy),
                "path": normalize_path(destination) if stage != 1 else row["path"],
                "display_path": str(destination) if stage != 1 else (loc["display_path"] if loc else None),
                "actor": actor, "restored_at": at, "remaining_sec": None, "purge_at": None}

    def _mark_recovered(self, row, *, at: str, actor: str) -> dict:
        """**動かす前に落ちた行を「戻した」ことにする**（B-1。**ファイルは元の場所に在る**）。

        台帳を先に書く順にしたので、`rename` の前にプロセスが落ちると「保留に在る」と台帳に
        残る。そのときファイルはまだ**元の場所**にある（削除は起きていない）ので、戻す操作は
        **何も動かさずに**「戻した」でよい（`missing_at` も元から NULL のまま）。
        """
        with self.store.transaction() as con:
            con.execute("UPDATE deletion_log SET restored_at = ?, purge_at = NULL,"
                        " remaining_sec = NULL WHERE id = ?", (at, row["id"]))
            self._sync_hidden(con, row["asset_id"], at)
        self._born.pop(row["id"], None)
        return {"deletion_id": row["id"], "restored": True, "stage": int(row["stage"]),
                "asset_id": row["asset_id"], "as_copy": False, "path": row["path"],
                "display_path": row["path"], "actor": actor, "restored_at": at,
                "remaining_sec": None, "purge_at": None, "recovered": True}

    def _restore_destination(self, row, loc) -> Path:
        """戻す先。**元の場所（登録の表示パス）**（登録が無ければ台帳の鍵）。"""
        display = loc["display_path"] if loc is not None else row["path"]
        return Path(display)

    def _free_db_name(self, candidate: Path) -> Path:
        """**空いている別名**（`<名前>.<連番>.<拡張子>`。専門 §3.3）。

        ファイルが空いているだけでは足りない——**`asset_location.path` は主キー**なので、
        同じ鍵の行が残っていると登録の付け替えで落ちる。**両方を見て決める。**
        """
        stem, ext = os.path.splitext(candidate.name)
        with self.store.locked() as con:
            for n in range(0, 10000):
                cand = candidate if n == 0 else candidate.with_name(f"{stem}.{n}{ext}")
                if cand.exists():
                    continue
                if con.execute("SELECT 1 FROM asset_location WHERE path = ?",
                               (normalize_path(cand),)).fetchone() is not None:
                    continue
                return cand
        raise ReviewError(409, "空いている名前が見つかりません", code="target_exists",
                          details={"name": candidate.name})

    def _mark_unrestorable(self, deletion_id: str) -> None:
        """**戻せなかった**印（`purge_at` を NULL にして自動削除から外す。専門 §3.4）。

        この行は「最近の削除」に**戻せませんでした**（`state: "stuck"`）として残り、
        **利用者が明示的に触るまでこのツールはこのファイルに触らない**（黙って再試行しない）。

        **（B-2）呼ぶのは `target_exists`（元の場所が埋まっている）と `move_failed`
        （元のフォルダが無い・他プロセスが掴んでいる）の両方。** 片方だけだと、409 を見た
        利用者の画面が「あと N 分」のまま進み、**窓が尽きたときに黙って消える**（専門 §3.4 は
        「取り消し自体が失敗したとき（`os.replace` の失敗、別名での復帰の失敗のどちらも）…
        `purge_at` を NULL にして自動削除の対象から完全に外す」）。
        """
        with self.store.transaction() as con:
            con.execute("UPDATE deletion_log SET purge_at = NULL WHERE id = ?", (deletion_id,))

    # ---- 中: 台帳と要求 ----

    def _target(self, asset_id: str | None, path: str | None) -> dict:
        """**登録済みの場所**を引く（**完全一致**。前方一致は使わない。専門 §3.2 の 1）。"""
        key = normalize_path(path)
        with self.store.locked() as con:
            row = con.execute(
                "SELECT l.path, l.display_path, l.asset_id, l.size, l.mtime_ns, l.is_primary,"
                " l.missing_at, a.deleted_at, a.sha256 FROM asset_location l"
                " JOIN asset a ON a.id = l.asset_id WHERE l.path = ?", (key,)).fetchone()
        if row is None or (asset_id and row["asset_id"] != str(asset_id)):
            raise ReviewError(409, "その場所は登録されていません", code="not_registered",
                              details={"path": key, "asset_id": asset_id})
        return dict(row)

    def _live_locations(self, asset_id: str) -> int:
        with self.store.locked() as con:
            return int(con.execute("SELECT count(*) AS n FROM asset_location WHERE asset_id = ?"
                                   " AND missing_at IS NULL", (asset_id,)).fetchone()["n"])

    def _window_sec(self) -> int:
        with self.store.locked() as con:
            return self._setting(con, "undo_window_sec", DEFAULT_UNDO_WINDOW_SEC)

    @staticmethod
    def _setting(con, key: str, default: int) -> int:
        row = con.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
        try:
            got = int(row["value"]) if row is not None else default
        except (TypeError, ValueError):
            return int(default)
        return got if got >= 0 else int(default)

    def _write_log(self, con, *, deletion_id: str, target: dict, stage: int, actor: str,
                   reason: str | None, request_id: str, size: int, at: str,
                   from_path: str | None = None, to_path: str | None = None,
                   hold_path: str | None = None, remaining_sec: int | None = None,
                   purge_at: str | None = None) -> None:
        """台帳の 1 行（**削除後も消さない**。専門 §3.2 の 4）。`actor` は必ず入れる（Q2 の帰結 a）。"""
        con.execute(
            "INSERT INTO deletion_log(id, asset_id, path, stage, from_path, to_path, hold_path,"
            " remaining_sec, purge_at, size, request_id, reason, actor, at)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (deletion_id, target["asset_id"], target["path"], stage, from_path, to_path, hold_path,
             remaining_sec, purge_at, int(size), request_id, reason, actor, at))

    @classmethod
    def _sync_hidden(cls, con, asset_id: str | None, at: str) -> None:
        """**カタログから外す印（`asset.deleted_at`）を、いまの状態から引き直す**（§4.1・C-3）。

        立てる条件は 2 つだけ:

        - **生きている場所が 0**（段 2・3 で最後の 1 つを移した／実削除した）
        - **生きた段 1 の行がある**（段 1 は場所を消さずにカタログから外す）

        どちらでもなければ**外す**。**（C-3）場所が 2 つある画像の片方を消しただけで一覧から
        消えない**ようにするため（削除は**場所**の単位、`deleted_at` は**資産**の単位）。
        段 1 の印は**場所ごと**なので、2 か所の片方だけを外したときも一覧からは消さない
        （生きている場所が残っている＝まだ見られる）。
        """
        if not asset_id:
            return
        if cls._should_hide(con, asset_id):
            con.execute("UPDATE asset SET deleted_at = COALESCE(deleted_at, ?) WHERE id = ?",
                        (at, asset_id))
        else:
            con.execute("UPDATE asset SET deleted_at = NULL WHERE id = ?", (asset_id,))

    @staticmethod
    def _should_hide(con, asset_id: str) -> bool:
        """**一覧から外すべきか**（C-3 の規則そのもの。1 か所に書く）。"""
        live = con.execute("SELECT count(*) AS n FROM asset_location WHERE asset_id = ?"
                           " AND missing_at IS NULL", (asset_id,)).fetchone()["n"]
        if int(live) == 0:
            return True
        hidden = con.execute("SELECT count(*) AS n FROM deletion_log WHERE asset_id = ?"
                             " AND stage = 1 AND restored_at IS NULL", (asset_id,)).fetchone()["n"]
        return int(hidden) > 0

    def _open_request(self, *, actor: str, stage: int, count: int,
                      client_token: str | None, payload: dict) -> str:
        """要求の行（**`client_token` の予約**。§0.16 A2）。`deletion_log.request_id` が指す先。

        `client_token` は部分索引 `ux_delete_token` が守る。ここに来る前に `_replay` が
        見ているので普通は当たらないが、**当たったら 409 で返す**（500 にしない）。
        """
        request_id = db.ulid()
        try:
            with self.store.transaction() as con:
                con.execute(
                    "INSERT INTO delete_request(id, client_token, actor, stage, count,"
                    " payload_json, at) VALUES (?,?,?,?,?,?,?)",
                    (request_id, client_token, actor, stage, count,
                     json.dumps(payload, ensure_ascii=False), self.clock.now()))
        except sqlite3.IntegrityError as exc:
            raise ReviewError(409, "同じ client_token の要求が既にあります",
                              code="client_token_conflict",
                              details={"client_token": client_token}) from exc
        return request_id

    def _drop_request(self, request_id: str) -> None:
        """断った要求の行を消す（**台帳は消さないが、要求の控えは残さない**）。"""
        with self.store.transaction() as con:
            con.execute("DELETE FROM delete_request WHERE id = ? AND result_json IS NULL",
                        (request_id,))

    def _close_request(self, request_id: str, *, count: int, result: dict) -> None:
        with self.store.transaction() as con:
            con.execute("UPDATE delete_request SET count = ?, result_json = ? WHERE id = ?",
                        (int(count), json.dumps(result, ensure_ascii=False), request_id))

    def _replay(self, client_token: str | None, payload: dict) -> dict | None:
        """同じ `client_token` の再送は **200 で前の結果**（§0.13。二重に消さない）。

        **中身が違う再送は 409 `client_token_conflict`**（トークンの取り違え。P6 と同じ流儀）。

        **（D-8）`result_json` の無いまま古く残った行は「落ちた要求」**として捨て、再送を許す。
        `self._lock` の中では「進行中」の要求は同時に居ないので、残っていれば落ちた物
        （別プロセスが動いていても、`STALE_REQUEST_SEC` より古ければ巻き取ってよい）。
        """
        if not client_token:
            return None
        with self.store.locked() as con:
            row = con.execute("SELECT * FROM delete_request WHERE client_token = ?",
                              (client_token,)).fetchone()
        if row is None:
            return None
        got = json.loads(row["payload_json"]) if row["payload_json"] else None
        if got is not None and got != payload:
            raise ReviewError(409, "同じ client_token で違う内容が来ました",
                              code="client_token_conflict",
                              details={"client_token": client_token, "asked": got, "now": payload})
        if not row["result_json"]:
            if plus_seconds(str(row["at"]), STALE_REQUEST_SEC) >= self.clock.now():
                raise ReviewError(409, "同じ client_token の処理が進んでいます",
                                  code="client_token_in_progress",
                                  details={"client_token": client_token})
            # **落ちた要求の行を捨てる**（残すと同じ token が永久に `in_progress` になる）
            log.warning("結果の残っていない古い要求を捨てます（同じ client_token の再送を許します）: %s",
                        client_token)
            with self.store.transaction() as con:
                con.execute("DELETE FROM delete_request WHERE id = ? AND result_json IS NULL",
                            (row["id"],))
            return None
        return {**json.loads(row["result_json"]), "replayed": True}

    # ---- 中: 凍結（一括）----

    def _resolve_scope(self, con, scope: dict | None) -> list[dict]:
        """凍結する対象を**この瞬間に 1 回だけ**解決する（§0.7）。

        - `assets`: 手で選んだ枚（**その枚の代表の場所**）
        - `folder`: そのフォルダの下の**生きた場所すべて**
        - `group`: まとまりの枚（**代表の場所**）
        - `query`: 絞り込み（`q` / `state` / `tag` / `known`。`GET /api/assets` と同じ意味）
        """
        got = scope or {}
        kind = got.get("kind")
        if kind not in SCOPE_KINDS:
            raise ReviewError(422, f"scope.kind は {' / '.join(SCOPE_KINDS)} のいずれかです",
                              code="bad_scope", details={"kind": kind})
        if kind in ("assets", "group"):
            if kind == "assets":
                # **同じ id を 2 回書かれても 1 件**（同じファイルを 2 回消しにいかない）
                seen: dict[str, None] = {}
                for x in (got.get("asset_ids") or []):
                    seen.setdefault(str(x), None)
                ids = list(seen)
            else:
                group_id = str(got.get("id") or "")
                ids = [r["asset_id"] for r in con.execute(
                    "SELECT asset_id FROM group_item WHERE group_id = ? ORDER BY position, asset_id",
                    (group_id,))]
            out = []
            for asset_id in ids:
                row = self._location_of_asset(con, asset_id)
                if row is not None:
                    out.append(self._item_doc(row))
            return out
        if kind == "folder":
            root = str(got.get("id") or got.get("path") or "")
            if not root:
                raise ReviewError(422, "folder には id（フォルダのパス）が要ります",
                                  code="bad_scope", details=got)
            # **（D-14）登録した置き場（`root`）の下だけ**を凍結の対象にする。
            # 見ないと `C:\` のような指定で**管理下でない物まで凍結の一覧に入る**
            # （人に上限が無いので、1 回の preview が現実的な歯止めになる）
            if not self._under_a_root(con, root):
                raise ReviewError(422, "そのフォルダは登録した置き場の下にありません",
                                  code="bad_scope", details={"folder": root})
            rows = [r for r in self._live_location_rows(con) if is_under(r["display_path"], root)]
        else:
            rows = self._query_rows(con, got)
        return [self._item_doc(r) for r in rows]

    @staticmethod
    def _stage3_roots(con) -> list[dict]:
        """`root` と**段 3 を許す印**（1 回だけ読む。枚ごとに読まない）。"""
        return [{"root": r["display_path"], "allow_stage3": int(r["allow_stage3"])}
                for r in con.execute("SELECT display_path, allow_stage3 FROM root")]

    @staticmethod
    def _stage3_ok(con, display_path: str) -> bool:
        """**その場所が段 3 を許されているか**（`root.allow_stage3`。Q8・点検 B7）。

        **どの root にも入っていない場所は許さない**（§0.6-6 の帰結。安全側）。
        """
        covering = [r for r in DeletionService._stage3_roots(con)
                    if is_under(display_path, r["root"])]
        return any(r["allow_stage3"] for r in covering)

    @staticmethod
    def _under_a_root(con, path: str) -> bool:
        """**登録した置き場の下か**（`folder` の `scope` の歯止め。D-14）。"""
        return any(is_under(path, r["display_path"]) for r in
                   con.execute("SELECT display_path FROM root"))

    @staticmethod
    def _location_of_asset(con, asset_id: str) -> Any:
        """その枚の**代表の場所**（`is_primary` → パスの順。生きている物だけ）。"""
        return con.execute(
            "SELECT l.* FROM asset_location l JOIN asset a ON a.id = l.asset_id"
            " WHERE l.asset_id = ? AND l.missing_at IS NULL AND a.deleted_at IS NULL"
            " ORDER BY l.is_primary DESC, l.path LIMIT 1", (asset_id,)).fetchone()

    @staticmethod
    def _live_location_rows(con) -> list:
        return con.execute(
            "SELECT l.* FROM asset_location l JOIN asset a ON a.id = l.asset_id"
            " WHERE l.missing_at IS NULL AND a.deleted_at IS NULL"
            " ORDER BY l.display_path").fetchall()

    def _query_rows(self, con, got: dict) -> list:
        """`query` の絞り込み。`GET /api/assets` の規則に合わせる（**同じ意味に保つ**）。"""
        rows = self._live_location_rows(con)
        state = got.get("state")
        if state:
            if state not in ("unreviewed", "kept", "rejected"):
                raise ReviewError(422, "state は unreviewed / kept / rejected のいずれかです",
                                  code="bad_scope", details={"state": state})
            rows = [r for r in rows if self._asset_state(con, r["asset_id"]) == state]
        tag = got.get("tag")
        if tag:
            known = str(got.get("known", "1"))
            if known not in ("0", "1", "all"):
                raise ReviewError(422, "known は 1 | 0 | all です", code="bad_scope",
                                  details={"known": known})
            name = str(tag).strip().lower().replace(" ", "_")
            sql = ("SELECT a.asset_id FROM asset_tag a JOIN tag t ON t.id = a.tag_id"
                   " WHERE t.name = ?")
            args: list = [name]
            if known != "all":
                sql += " AND t.known = ?"
                args.append(int(known))
            hit = {r["asset_id"] for r in con.execute(sql, args)}
            rows = [r for r in rows if r["asset_id"] in hit]
        needle = got.get("q")
        if needle:
            low = str(needle).lower()
            keep = []
            for r in rows:
                meta = con.execute("SELECT meta_json FROM asset_meta WHERE asset_id = ?",
                                   (r["asset_id"],)).fetchone()
                blob = (str(r["display_path"]) + " " + (meta["meta_json"] if meta else "")).lower()
                if low in blob:
                    keep.append(r)
            rows = keep
        return rows

    @staticmethod
    def _asset_state(con, asset_id: str) -> str:
        row = con.execute("SELECT review_state FROM asset WHERE id = ?", (asset_id,)).fetchone()
        return str(row["review_state"]) if row is not None else "unreviewed"

    @staticmethod
    def _count_last_copies(con, items: Sequence[dict]) -> int:
        """**最後の 1 つになる枚数**（消すと内容そのものが失われる物。§3.2・専門 §3.2 の 3）。

        同じ画像の生きた場所が**凍結した一覧の中に全部入っている**場合も「失われる」に数える
        （1 枚ずつ見ると「最後の 1 つ」に見えないので、**束で見る**）。
        """
        per_asset: dict[str, int] = {}
        for item in items:
            asset_id = str(item.get("asset_id") or "")
            per_asset[asset_id] = per_asset.get(asset_id, 0) + 1
        out = 0
        for asset_id, in_batch in per_asset.items():
            live = con.execute("SELECT count(*) AS n FROM asset_location WHERE asset_id = ?"
                               " AND missing_at IS NULL", (asset_id,)).fetchone()["n"]
            if int(live) - in_batch <= 0:
                out += in_batch
        return out

    @staticmethod
    def _item_doc(row) -> dict:
        """凍結に入れる 1 件（**`path` は正規化した鍵・`display_path` は人に見せる表記**。点検 D6）。"""
        return {"asset_id": row["asset_id"], "path": row["path"],
                "display_path": row["display_path"], "size": int(row["size"]),
                "mtime_ns": int(row["mtime_ns"])}

    # ---- 中: 読みの形 ----

    def _log_doc(self, row, *, actor: str) -> dict:
        """台帳の 1 行を口の形にする（`state` と `mine` と `undoable` を付ける）。

        **（D-4）`display_path` は登録の表記**（`asset_location.display_path`）を引く。
        台帳の `path` は**正規化した鍵**（小文字）なので、そのまま出すと画面が登録と違う表記を
        見せる（行が消えていれば鍵しか無いので、そのときだけ鍵を出す）。
        """
        state = self._state_of(row)
        mine = row["actor"] == actor
        keys = set(row.keys())
        display = (row["loc_display"] if "loc_display" in keys else None) or row["path"]
        return {
            "id": row["id"], "asset_id": row["asset_id"], "stage": int(row["stage"]),
            "path": row["path"], "display_path": display, "from_path": row["from_path"],
            "to_path": row["to_path"], "hold_path": row["hold_path"],
            "remaining_sec": row["remaining_sec"], "purge_at": row["purge_at"],
            "restored_at": row["restored_at"], "size": row["size"], "reason": row["reason"],
            "actor": row["actor"], "at": row["at"], "request_id": row["request_id"],
            "state": state, "mine": mine,
            # **（C-1）人は誰の削除でも戻せる**（人の安全網）。エージェントは自分の分だけ。
            # 画面はこれで「戻す」を押せるかどうかを決める（§5・点検 G2）
            "undoable": state in ("pending", "stuck") and (mine or actor == "human"),
            "needs_as_copy": state == "stuck",
        }

    @staticmethod
    def _state_of(row) -> str:
        """行の状態（語彙はここ 1 か所。画面の文言は P8-5）。

        - `hidden` 段 1（カタログから外しただけ）／`trashed` 段 2（ゴミ箱）
        - `pending` 段 3 で窓の間（取り消せる）／`stuck` 戻せなかった（**自動では消さない**）
        - `purged` 実体を消した／`restored` 取り消した
        """
        if row["restored_at"]:
            return "restored"
        stage = int(row["stage"])
        if stage == 1:
            return "hidden"
        if stage == 2:
            return "trashed"
        if row["hold_path"] == HOLD_PURGED:
            return "purged"
        if row["purge_at"] is None:
            return "stuck"
        return "pending"

    @staticmethod
    def _trash_day(to_path: str | None) -> str | None:
        """`<data>/trash/<YYYYMMDD>/…` から日付を取る（ゴミ箱の一覧を日付ごとに組む）。"""
        if not to_path:
            return None
        parts = Path(to_path).parts
        for i, part in enumerate(parts):
            if part == TRASH_DIR and i + 1 < len(parts):
                return parts[i + 1]
        return None

    def _preview_doc(self, row) -> dict:
        items = json.loads(row["items_json"] or "[]")
        return {"preview_id": row["id"], "stage": int(row["stage"]),
                "items": items, "count": int(row["count"]), "bytes": int(row["bytes"]),
                "actor": row["actor"], "created_at": row["created_at"],
                "expires_at": row["expires_at"], "executed_at": row["executed_at"],
                "request_id": row["request_id"],
                "scope": json.loads(row["scope_json"] or "{}"),
                "expired": self.clock.now() > str(row["expires_at"]),
                "result": json.loads(row["result_json"]) if row["result_json"] else None}
