"""P8 の合格の線を実データで出す（設計 §1.2）。

**実データ `.data/` は `mode=ro` でしか開かない。** 試験は `backup()` で作った複製で行う
（`db.sqlite3` だけ複写すると WAL の分が抜けて判断が消える）。**画像も複製してから触る**
（P8-2 は**ファイルを動かす**ので、実データのファイルには絶対に触らない）。

    uv run --no-sync python tools/probe_p8.py              # P8-1（線 1〜3。重複）
    uv run --no-sync python tools/probe_p8.py --delete     # P8-2（線 5〜8。削除と取り消し）
    uv run --no-sync python tools/probe_p8.py --backup     # P8-4（線 10・12。バックアップと健全性）
    uv run --no-sync python tools/probe_p8.py --restore    # P8-4（線 11。復元と組み直し）
    uv run --no-sync python tools/probe_p8.py --all        # 全部
    uv run --no-sync python tools/probe_p8.py --keep       # 複製を残す
    uv run --no-sync python tools/probe_p8.py --distances 0,3,6,10   # 距離を絞る

線 2（帯 vs 総当たり）は**既定で 0〜64 の全部**を見る（P8-3 の取り落とし調査。
`docs/p8-3-band-miss.md`）。**「別物として確定」で隠れている組は総当たりから引いてから比べる**
（`candidate_pairs` が外すため。引かないと**除外 1 組が「取りこぼし 1 組」に見える**）。
線 1・3 の群の数も**総当たりから出した数**と比べる（固定の数字を期待値にしない）。

P8-2 は **HTTP（`TestClient`）で口を叩く**（設計の線が「そのまま打てる形」で書いてあるため）。
5 分の窓だけは**時計を注入**する（`Clock` を 1 つ。`app.state.deletions` を差し替える）。
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sqlite3
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
# **コンソールが cp932 でも「≤」などで落ちない**ように、この道具だけ UTF-8 で出す
# （Git Bash の日本語は cp932 に化ける。`image-reviewer-dev` スキルの §6）
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from image_reviewer.duplicates import (BANDS, MAX_DISTANCE_LIMIT, DuplicatesService,  # noqa: E402
                                       candidate_pairs)
from image_reviewer.store import Store, normalize_path           # noqa: E402

REAL = ROOT / ".data" / "db.sqlite3"
REAL_DIR = ROOT / ".data"
WORK = ROOT / ".tmp-audit-redo" / "p8probe"

#: 帯と総当たりを突き合わせる距離。**既定は 0〜64 の全部**（P8-3 の取り落とし調査。
# 前の版は (0, 3, 6, 10, 15, 16, 32, 64) の 8 段だけで、**その間の距離を見ていなかった**）。
# `--distances 0,3,6,10` で絞れる（速く回したいとき）。
DISTANCES: list[int] = list(range(0, MAX_DISTANCE_LIMIT + 1))


def copy_real(into: Path) -> Path:
    """実データの複製（**WAL を畳む**）。

    **前の実行の `-wal` / `-shm` を残さない**（本体だけ消すと WAL と食い違って
    `unable to open database file` になる。実際に踏んだ）。
    """
    into.mkdir(parents=True, exist_ok=True)
    dst_path = into / "db.sqlite3"
    for stale in (dst_path, into / "db.sqlite3-wal", into / "db.sqlite3-shm"):
        if stale.exists():
            stale.unlink()
    src = sqlite3.connect(f"file:{REAL}?mode=ro", uri=True)
    dst = sqlite3.connect(str(dst_path))
    with dst:
        src.backup(dst)
    dst.close()
    src.close()
    return into


def brute_force(con, max_distance: int) -> set[tuple[str, str]]:
    """**総当たり**で距離 ≤ `max_distance` の組を出す（帯の取りこぼしを確かめる物差し）。

    **（P8-1 の監査 C-5）距離を引数にした。** 前の版は 6 固定で、**≤10 の「取りこぼし 0」を
    確かめていなかった**（帯の群の数だけを見ていた）。いまは **≤64 まで**回せる
    （263 枚の総当たりは 34,453 組で 20 ms 程度）。
    """
    rows = con.execute("SELECT id, phash FROM asset WHERE deleted_at IS NULL"
                       " AND phash IS NOT NULL").fetchall()
    hashes = [(row["id"], int(row["phash"], 16)) for row in rows]
    out = set()
    for i, (a_id, pa) in enumerate(hashes):
        for b_id, pb in hashes[i + 1:]:
            if (pa ^ pb).bit_count() <= max_distance:
                out.add((a_id, b_id) if a_id < b_id else (b_id, a_id))
    return out


def excluded_edges(con) -> set[tuple[str, str]]:
    """**「別物として確定」で隠れている組**（`candidate_pairs` が外す物）。

    **（P8-3 の取り落とし調査。`docs/p8-3-band-miss.md`）** `brute_force` は `asset` を読むだけなので
    除外を知らない。**引かずに比べると、除外が 1 組あるだけで「取りこぼし 1 組」と嘘を言う**
    （実データで実際にそう見えた。帯は 1 組も落としていなかった）。
    """
    return {(row["a_id"], row["b_id"]) for row in
            con.execute("SELECT a_id, b_id FROM duplicate_exclusion")}


def groups_of(edges: set[tuple[str, str]]) -> tuple[int, int]:
    """組（辺）から**群の数と枚数**を出す（`near_groups` と同じ連結成分の物差し）。

    **API の `total_groups` / `total_images` を「総当たりから出した数」と比べる**ために使う
    （固定の数字を書くと、除外や実データの変化で嘘の NG になる）。
    """
    parent: dict[str, str] = {}

    def find(x: str) -> str:
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for a, b in edges:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra
    groups: dict[str, set[str]] = {}
    for a, b in edges:
        groups.setdefault(find(a), set()).update((a, b))
    return len(groups), sum(len(m) for m in groups.values())


def probe_duplicates() -> bool:
    """P8-1 の線 1〜3 を複製で通す（**サービス直呼び**。HTTP の形はテストが見る）。"""
    ok = True
    data = copy_real(WORK / "data")
    store = Store(data)
    try:
        con = store.con
        con.row_factory = sqlite3.Row
        total = con.execute("SELECT count(*) AS n FROM asset WHERE deleted_at IS NULL").fetchone()["n"]
        hashed0 = con.execute("SELECT count(*) AS n FROM asset WHERE phash IS NOT NULL"
                              " AND deleted_at IS NULL").fetchone()["n"]
        bands0 = con.execute("SELECT count(*) AS n FROM phash_band").fetchone()["n"]
        print(f"1. 実データの複製: {total} 枚 / pHash あり {hashed0} 枚 / 帯 {bands0} 行")

        # --- pHash の計算（背景ジョブ。**GET では計算しない**）---
        svc = DuplicatesService(store)
        t0 = time.monotonic()
        started = svc.start_compute()
        # **サービスを直に呼んでいる**（HTTP の 202 は `tests/test_duplicates.py` の
        # `test_the_compute_endpoint_is_202_and_human_only` が見ている。監査 C-5）
        print(f"   compute を開始（サービス直呼び）→ job={started['job_id']} total={started['total']}")
        job = svc.wait(started["job_id"], timeout=900)
        took = time.monotonic() - t0
        # **復号するのは pHash の無い枚だけ**。全部そろっていると `total` が 0 になり、
        # 前の版は「復号した -263 枚で 116.2 ms/枚」という**嘘の数字**を出していた（実測で踏んだ）
        decoded = max(0, started["total"] - hashed0)
        per = took / decoded if decoded else 0.0
        rate = f"（復号した {decoded} 枚で {per * 1000:.1f} ms/枚）" if decoded else "（復号は不要。全部そろっていた）"
        print(f"   job={job['state']} / {job['message']} / 実測 {took:.1f} 秒{rate}")
        hashed1 = con.execute("SELECT count(*) AS n FROM asset WHERE phash IS NOT NULL"
                              " AND deleted_at IS NULL").fetchone()["n"]
        bands1 = con.execute("SELECT count(*) AS n FROM phash_band").fetchone()["n"]
        print(f"   → pHash {hashed1} 枚（+{hashed1 - hashed0}）/ 帯 {bands1} 行（+{bands1 - bands0}）")
        if hashed1 != total or bands1 != total * BANDS:
            ok = False
            print(f"   NG: 全部の枚に pHash と帯（{BANDS} 本ずつ）が入っていない")

        # --- 線 2: 帯と総当たりが集合として一致（**取りこぼし 0**）---
        # **（P8-1 の監査 B-1 / C-5）距離ごとに確かめる。** 4bit × 16 本なので保証は ≤15。
        # **16 以上は総当たりに落ちる**（`candidate_pairs` の中）ので、そこも一致するはず。
        # **（P8-3 の取り落とし調査）既定は 0〜64 の全部**（`--distances` で絞れる）。
        # **除外を引いてから比べる**: `candidate_pairs` は「別物として確定」を外すので、
        # 引かずに比べると**除外 1 組が「取りこぼし 1 組」に見える**（実データで実際に踏んだ）。
        hidden = excluded_edges(con)
        print(f"2. 帯 vs 総当たり（距離 {'/'.join(str(d) for d in DISTANCES[:6])}"
              f"{'…' if len(DISTANCES) > 6 else ''}・{len(DISTANCES)} 段）:")
        if hidden:
            print(f"   除外（別物として確定）{len(hidden)} 組は総当たりから引いて比べる"
                  f"（`candidate_pairs` が外すため。帯の取りこぼしではない）")
        for dist in DISTANCES:
            t0 = time.monotonic()
            band = {tuple(sorted((a, b))) for a, b, _ in candidate_pairs(con, dist)}
            band_ms = (time.monotonic() - t0) * 1000
            brute = brute_force(con, dist)
            want = brute - hidden
            mark = "OK" if band == want else "NG"
            if band != want:
                ok = False
            print(f"   ≤{dist:<2}: 帯 {len(band):>5} 組（{band_ms:5.0f} ms）"
                  f"/ 総当たり {len(brute):>5} 組 - 除外 {len(brute & hidden):>3}"
                  f" = {len(want):>5} → {mark}" + ("" if band == want else
                  f" 取りこぼし {len(want - band)} / 余分 {len(band - want)}"))

        # --- 線 1・3: 群の数（**総当たりから出した数**と一致するか）と完全重複 ---
        # **固定の数字を期待値にしない**（除外が 1 組あるだけで嘘の NG になる。P8-3 の調査）。
        print("3. 群（連結成分）: API vs 総当たりから出した数")
        for dist in (0, 3, 6, 10, 15):
            got = svc.near(max_distance=dist)
            want_g, want_i = groups_of(brute_force(con, dist) - hidden)
            pairs_want = len(brute_force(con, dist))
            line_ok = ((got["total_groups"], got["total_images"]) == (want_g, want_i)
                       and got.get("total_pairs", 0) + got.get("excluded_pairs", 0) == pairs_want)
            if not line_ok:
                ok = False
            print(f"   ≤{dist:<2}: {got['total_groups']} 群 / {got['total_images']} 枚"
                  f"（総当たり {want_g} 群 / {want_i} 枚）・組 {got.get('total_pairs')}"
                  f" + 除外 {got.get('excluded_pairs')} = {pairs_want}"
                  f"・pHash あり {got['hashed']}・未計算 {got['unhashed']}"
                  f" → {'OK' if line_ok else 'NG'}")
        got6 = svc.near(max_distance=6)
        first = got6["groups"][0] if got6["groups"] else None
        if first:
            print(f"   先頭の群: {first['count']} 枚・最大距離 {first['max_distance_within']}"
                  f"・推薦 {first['suggested_id'][:8]}…（{first['reason']}）")
        exact = svc.exact()
        print(f"4. 完全重複: {exact['count']} 群 / {exact['message']}")
        if exact["count"] != 0:
            ok = False
            print("   NG: 完全重複が 0 群でない（`asset.sha256` は UNIQUE のはず）")

        # --- 除外が効く（その 2 枚が同じ群でなくなる／戻すと戻る）---
        if first and len(first["items"]) >= 2:
            a, b = first["items"][0]["id"], first["items"][1]["id"]

            def same_group(x: str, y: str, dist: int = 6) -> bool:
                got = svc.near(max_distance=dist)
                return any({x, y} <= {i["id"] for i in g["items"]} for g in got["groups"])

            before = svc.near(max_distance=6)["total_groups"]
            was = same_group(a, b)
            svc.exclude(a_id=a, b_id=b, reason="probe", actor="human")
            after = svc.near(max_distance=6)["total_groups"]
            now = same_group(a, b)
            svc.remove_exclusion(a_id=a, b_id=b)
            back = svc.near(max_distance=6)["total_groups"]
            again = same_group(a, b)
            print(f"5. 除外: 群 {before} → {after} → {back} / 同じ群か {was} → {now} → {again}")
            # **除外は群を増やさない**（辺を 1 本消すので、割れるか消えるか）。
            # 2 枚だけの群なら**群そのものが消える**（21 → 20 が正しい）
            if not (was and not now and again and back == before and after <= before):
                ok = False
                print("   NG: 除外と解除が群に反映されない")

        # --- `GET` は書かない（`near` の前後で帯の行数が変わらない）---
        before_rows = con.execute("SELECT count(*) AS n FROM phash_band").fetchone()["n"]
        before_hash = con.execute("SELECT count(*) AS n FROM asset WHERE phash IS NOT NULL"
                                 " AND deleted_at IS NULL").fetchone()["n"]
        svc.near(max_distance=6)
        svc.exact()
        svc.exclusions()
        after_rows = con.execute("SELECT count(*) AS n FROM phash_band").fetchone()["n"]
        after_hash = con.execute("SELECT count(*) AS n FROM asset WHERE phash IS NOT NULL"
                                 " AND deleted_at IS NULL").fetchone()["n"]
        print(f"6. GET の前後: 帯 {before_rows} → {after_rows} / pHash {before_hash} → {after_hash}")
        if (before_rows, before_hash) != (after_rows, after_hash):
            ok = False
            print("   NG: GET が書いている")
    finally:
        store.close()
    return ok


def main() -> int:
    global DISTANCES
    ap = argparse.ArgumentParser()
    ap.add_argument("--keep", action="store_true")
    ap.add_argument("--duplicates", action="store_true", help="P8-1（線 1〜3）")
    ap.add_argument("--delete", action="store_true", help="P8-2（線 5〜8）")
    ap.add_argument("--backup", action="store_true", help="P8-4（線 10・12。バックアップと健全性）")
    ap.add_argument("--restore", action="store_true", help="P8-4（線 11。復元と組み直し）")
    ap.add_argument("--all", action="store_true", help="全部")
    ap.add_argument("--distances", default=None,
                    help=f"帯と総当たりを比べる距離（既定は 0〜{MAX_DISTANCE_LIMIT} の全部。"
                         "例: 0,3,6,10）")
    args = ap.parse_args()
    if args.distances:
        DISTANCES = [int(v) for v in str(args.distances).replace(" ", "").split(",") if v != ""]
        for dist in DISTANCES:                       # 語彙の外は**先に**弾く（黙って丸めない）
            if not (0 <= dist <= MAX_DISTANCE_LIMIT):
                print(f"NG: --distances は 0〜{MAX_DISTANCE_LIMIT}（{dist} が外）")
                return 1
    chosen = (args.duplicates, args.delete, args.backup, args.restore)
    both = args.all or not any(chosen)
    ok = True
    if both or args.duplicates:
        ok = probe_duplicates() and ok
    if both or args.delete:
        ok = probe_delete() and ok
    if both or args.backup:
        ok = probe_backup() and ok
    if both or args.restore:
        ok = probe_restore() and ok
    if not args.keep:
        shutil.rmtree(WORK, ignore_errors=True)
        if WORK.exists():
            print("注意: 作業場を消せませんでした（開いたままの接続かファイルがある）:", WORK)
    else:
        print("残した:", WORK)
    print("\nまとめ:", "すべて OK" if ok else "NG あり")
    return 0 if ok else 1


# ---- P8-2（削除と取り消し。線 5〜8）----


class FakeClock:
    """テスト用の時計（**壁と単調を 1 つの口から進める**。設計 §8 の末尾）。"""

    def __init__(self) -> None:
        self._wall = time.time()
        self._mono = 1000.0

    def now(self) -> str:
        return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(self._wall))

    def monotonic(self) -> float:
        return self._mono

    def advance(self, *, sec: float = 0.0, mono: float = 0.0) -> None:
        self._wall += sec
        self._mono += mono


def copy_images(con, *, count: int, into: Path, skip: Path | None = None) -> list[dict]:
    """**実データの画像を複製して、複製の DB の登録を複製先へ向け直す**。

    実データのファイルには触らない（`shutil.copy2` は読むだけ）。`copy2` は
    `mtime_ns` を保つので、登録した `(size, mtime_ns)` と一致したまま段 2・3 に進める。
    `asset_location.path` は正規化した鍵なので、新しい場所の鍵に入れ替える。
    `skip` の下にある行は選ばない（2 回目に呼んでも同じ枚を選ばないため）。
    """
    into.mkdir(parents=True, exist_ok=True)
    sql = ("SELECT l.path, l.display_path, l.asset_id, l.size, l.mtime_ns, a.sha256"
           " FROM asset_location l JOIN asset a ON a.id = l.asset_id"
           " WHERE l.missing_at IS NULL AND a.deleted_at IS NULL")
    args: list = []
    if skip is not None:
        sql += " AND l.display_path NOT LIKE ?"
        args.append(f"{skip}%")
    sql += " ORDER BY l.size LIMIT ?"
    args.append(count)
    rows = con.execute(sql, args).fetchall()
    out: list[dict] = []
    for row in rows:
        src = Path(row["display_path"])
        if not src.exists():
            continue
        dst = into / f"{row['asset_id'][:8]}-{src.name}"
        shutil.copy2(src, dst)                       # **実データは読むだけ**
        key = normalize_path(dst)
        st = dst.stat()
        con.execute("UPDATE asset_location SET path = ?, display_path = ?, size = ?,"
                    " mtime_ns = ? WHERE path = ?",
                    (key, str(dst), st.st_size, st.st_mtime_ns, row["path"]))
        out.append({"asset_id": row["asset_id"], "path": key, "display_path": str(dst),
                    "size": int(st.st_size), "mtime_ns": int(st.st_mtime_ns),
                    "source": str(src)})
    return out


def real_data_signature() -> dict:
    """**実データが無傷か**を見るための签名（DB と、画像の size / mtime_ns の合計）。"""
    con = sqlite3.connect(f"file:{REAL.as_posix()}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    try:
        assets = con.execute("SELECT count(*) AS n FROM asset").fetchone()["n"]
        decisions = con.execute("SELECT count(*) AS n FROM decision").fetchone()["n"]
        deleted = con.execute("SELECT count(*) AS n FROM asset WHERE deleted_at IS NOT NULL"
                              ).fetchone()["n"]
        logs = con.execute("SELECT count(*) AS n FROM deletion_log").fetchone()["n"]
        locs = [r["display_path"] for r in con.execute(
            "SELECT display_path FROM asset_location ORDER BY path")]
    finally:
        con.close()
    total = 0
    missing = 0
    for path in locs:
        try:
            got = os.stat(path)
            total += int(got.st_size) + int(got.st_mtime_ns) % 1_000_000_007
        except OSError:
            missing += 1
    return {"assets": assets, "decisions": decisions, "deleted": deleted, "logs": logs,
            "files": len(locs), "sum": total, "missing": missing}


def probe_delete() -> bool:
    """P8-2 の線 5〜8 を**複製と複製した画像**で通す（実データには触らない）。"""
    ok = True
    data = copy_real(WORK / "delete-data")
    library = WORK / "delete-library"
    noflag = WORK / "delete-noflag"
    if library.exists():
        shutil.rmtree(library)
    if noflag.exists():
        shutil.rmtree(noflag)
    before = real_data_signature()
    print(f"P8-2. 実データの複製: {data}（実データ: {before['assets']} 枚 / 判断 "
          f"{before['decisions']} 件 / 削除の台帳 {before['logs']} 行）")

    store = Store(data)
    con = store.con
    copies = copy_images(con, count=8, into=library)
    safety = copy_images(con, count=5, into=library / "safety", skip=library)
    if len(copies) < 8 or len(safety) < 5:
        print("   NG: 複製できた画像が足りない")
        ok = False
    # 置き場を root にして、**段 3 を許す印**を立てる（既定は印なし。Q8）
    store.set_roots([str(library), str(library / "safety"), str(noflag)])
    with store.transaction() as c:
        c.execute("UPDATE root SET allow_stage3 = 1 WHERE path = ?", (normalize_path(library),))
        # `noflag` は印を立てない（既定 0 のまま）
    # **印の付いた実データの root** を確かめる（262 / 263 枚はここ）
    roots = [(r["display_path"], int(r["allow_stage3"])) for r in
             con.execute("SELECT display_path, allow_stage3 FROM root ORDER BY display_path")]
    print("   root の印:", roots)
    if not any("illust-authoring" in p and flag for p, flag in roots):
        print("   NG: 実データの illust-authoring の置き場に段 3 の印が無い（Q8・P8-0）")
        ok = False
    store.close()

    # **環境変数を先に立ててから `app` を読む**（`app.py` は import 時に `create_app()` する）。
    # **import 時の `app` をそのまま使う**——`create_app()` をもう一度呼ぶと `Store` が 2 本になり、
    # 閉じない方の接続が残って**作業場を消せなくなる**（Windows は開いたファイルを消せない）
    os.environ["IMAGE_REVIEWER_DATA"] = str(data)
    from fastapi.testclient import TestClient                    # noqa: PLC0415
    from image_reviewer.app import app                           # noqa: PLC0415
    from image_reviewer.deletions import DeletionService, HOLD_DIR  # noqa: PLC0415

    clock = FakeClock()
    app.state.deletions = DeletionService(app.state.store, clock=clock)
    human = {"X-Image-Reviewer-Actor": "human"}
    agent = {"X-Image-Reviewer-Actor": "agent"}

    def snapshot() -> tuple:
        """**`GET` が書かない**ことを見るための署名（全表の行数＋ファイルの size / mtime）。"""
        store = app.state.store
        tables = [r["name"] for r in store.con.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY name")]
        counts = tuple(store.con.execute(f"SELECT count(*) AS n FROM {t}").fetchone()["n"]
                       for t in tables)
        files = tuple(sorted((str(p.relative_to(data)), p.stat().st_size, p.stat().st_mtime_ns)
                             for p in data.rglob("*") if p.is_file()))
        return counts, files

    def line(label: str, good: bool, detail: str) -> None:
        nonlocal ok
        ok = ok and good
        print(f"   [{'OK' if good else 'NG'}] {label}: {detail}")

    with TestClient(app, base_url="http://127.0.0.1") as client:
        # --- 線 5: 段 1 → 段 2 → 段 3 ---
        c0 = copies[0]
        total0 = client.get("/api/assets", headers=human).json()["total"]
        r1 = client.post("/api/locations/delete", headers=human,
                         json={"asset_id": c0["asset_id"], "path": c0["display_path"],
                               "stage": 1, "reason": "probe"})
        total1 = client.get("/api/assets", headers=human).json()["total"]
        shown = client.get("/api/assets?include_deleted=1", headers=human).json()["total"]
        one = client.get(f"/api/assets/{c0['asset_id']}", headers=human)
        line("線 5a 段 1（一覧から消える・判断は残る）",
             r1.status_code == 200 and total1 == total0 - 1 and shown == total0
             and one.status_code == 200 and Path(c0["display_path"]).exists(),
             f"{r1.status_code} / 一覧 {total0} → {total1} / include_deleted {shown}"
             f" / ファイルは元のまま {Path(c0['display_path']).exists()}")

        c1 = copies[1]
        r2 = client.post("/api/locations/delete", headers=human,
                         json={"asset_id": c1["asset_id"], "path": c1["display_path"],
                               "stage": 2})
        # **戻す前に**ゴミ箱の実体を見る（戻した後では消えていて当たり前）
        trash_files = [str(p.relative_to(data)) for p in data.rglob("*.png")
                       if "trash" in str(p)]
        moved_away = not Path(c1["display_path"]).exists()
        back2 = client.post("/api/trash/restore", headers=human,
                            json={"deletion_id": r2.json()["deletion_id"]})
        line("線 5b 段 2（ゴミ箱へ移り、元へ戻せる）",
             r2.status_code == 200 and trash_files and moved_away
             and back2.status_code == 200 and Path(c1["display_path"]).exists(),
             f"{r2.status_code} / ゴミ箱 {trash_files[:1]} / 戻す {back2.status_code}"
             f" / 元に戻った {Path(c1['display_path']).exists()}")

        c2 = copies[2]
        r3 = client.post("/api/locations/delete", headers=human,
                         json={"asset_id": c2["asset_id"], "path": c2["display_path"],
                               "stage": 3, "confirm_last_copy": True})
        body3 = r3.json()
        pend = client.get("/api/pending-deletes", headers=human).json()
        line("線 5c 段 3（保留領域へ移り、残り時間つきで出る）",
             r3.status_code == 200 and Path(body3["hold_path"]).exists()
             and not Path(c2["display_path"]).exists() and pend["count"] == 1
             and pend["items"][0]["remaining_sec"] == 300,
             f"{r3.status_code} / 保留 {Path(body3['hold_path']).name}"
             f" / remaining_sec {pend['items'][0]['remaining_sec']}"
             f" / 窓 {body3['frees']['note']}")
        loc_row = app.state.store.con.execute("SELECT missing_at FROM asset_location"
                                              " WHERE asset_id = ?",
                                              (c2["asset_id"],)).fetchone()
        print(f"   段 3 の直後の asset_location: 行は在る / missing_at = {loc_row['missing_at']}")

        # --- 線 6: すぐ戻す・上書きしない ---
        undo = client.post(f"/api/deletions/{body3['deletion_id']}/undo", headers=human, json={})
        line("線 6a 段 3 の直後に戻す",
             undo.status_code == 200 and Path(c2["display_path"]).exists()
             and not Path(body3["hold_path"]).exists(),
             f"{undo.status_code} / 元に戻った {Path(c2['display_path']).exists()}")
        # もう一度消して、**別のファイル**を置いてから戻す
        r3b = client.post("/api/locations/delete", headers=human,
                          json={"asset_id": c2["asset_id"], "path": c2["display_path"],
                                "stage": 3, "confirm_last_copy": True}).json()
        occupied = b"probe-occupied"
        Path(c2["display_path"]).write_bytes(occupied)
        blocked = client.post(f"/api/deletions/{r3b['deletion_id']}/undo", headers=human, json={})
        still = Path(c2["display_path"]).read_bytes() == occupied
        held = Path(r3b["hold_path"]).exists()          # **戻す前に**保留領域の実体を見る
        as_copy = client.post(f"/api/deletions/{r3b['deletion_id']}/undo", headers=human,
                              json={"as_copy": True})
        copy_path = Path(as_copy.json().get("display_path") or "")
        line("線 6b 埋まっていたら止めて尋ねる（上書きしない）",
             blocked.status_code == 409 and blocked.json()["code"] == "target_exists" and still
             and held and as_copy.status_code == 200 and copy_path.exists(),
             f"{blocked.status_code} {blocked.json().get('code')} / 元のファイルは無傷 {still}"
             f" / 保留に残っていた {held} / as_copy {as_copy.status_code} → {copy_path.name}")
        Path(c2["display_path"]).unlink()                 # 置いただけのファイルを片づける

        # --- 線 7: 窓はアプリが動いていた時間 ---
        c3 = copies[3]
        r7 = client.post("/api/locations/delete", headers=human,
                         json={"asset_id": c3["asset_id"], "path": c3["display_path"],
                               "stage": 3, "confirm_last_copy": True}).json()
        clock.advance(sec=3600)                # **壁時計だけ**進める（消えないはず）
        svc = app.state.deletions
        svc.tick()
        left_wall = app.state.store.con.execute(
            "SELECT remaining_sec FROM deletion_log WHERE id = ?",
            (r7["deletion_id"],)).fetchone()["remaining_sec"]
        clock.advance(mono=299)
        svc.tick()
        left_mono = app.state.store.con.execute(
            "SELECT remaining_sec FROM deletion_log WHERE id = ?",
            (r7["deletion_id"],)).fetchone()["remaining_sec"]
        line("線 7a 窓は単調時計（壁時計では縮まない）",
             left_wall == 300 and left_mono == 1 and Path(r7["hold_path"]).exists(),
             f"壁 +3600 → {left_wall} / 単調 +299 → {left_mono}")
        # **再起動しても残り時間が続く**（新しいサービス＝起動し直し）
        again = DeletionService(app.state.store, clock=clock)
        still_there = Path(r7["hold_path"]).exists()
        line("線 7b 起動し直しても消えない",
             still_there, f"保留領域は残っている {still_there}（残り {left_mono} 秒）")
        clock.advance(mono=1)
        again.tick()                            # 1 周期目（消さない）
        first_tick = Path(r7["hold_path"]).exists()
        again.tick()                            # 2 周期目（消える）
        gone = not Path(r7["hold_path"]).exists()
        purged = app.state.store.con.execute(
            "SELECT hold_path, remaining_sec FROM deletion_log WHERE id = ?",
            (r7["deletion_id"],)).fetchone()
        line("線 7c 期限が切れたら消える（1 周期待つ）",
             first_tick and gone and purged["hold_path"] == "(削除済み)",
             f"1 周期目は残す {first_tick} / 2 周期目で消える {gone}"
             f" / hold_path {purged['hold_path']}")

        # --- 線 8: 凍結した一覧だけ・失効したら何も消さない ---
        ids = [c["asset_id"] for c in copies[4:8]]
        total_before = len(ids)
        prev = client.post("/api/locations/bulk-delete/preview", headers=human,
                           json={"scope": {"kind": "assets", "asset_ids": ids}, "stage": 2})
        prev_body = prev.json()
        # **凍結の後で 1 件を差し替える**
        changed = copies[5]["display_path"]
        Path(changed).write_bytes(b"probe-changed-bytes")
        run = client.post("/api/locations/bulk-delete", headers=human,
                          json={"preview_id": prev_body["preview_id"], "confirm": True,
                                "confirm_last_copy": True})
        run_body = run.json()
        line("線 8a 凍結した一覧だけを消す（食い違った 1 件は skipped）",
             prev.status_code == 200 and prev_body["count"] == total_before
             and run.status_code == 200 and run_body["count"] == total_before - 1
             and [s["reason"] for s in run_body["skipped"]] == ["changed"]
             and Path(changed).exists(),
             f"preview {prev_body['count']} 枚 / 実行 deleted {run_body['count']}"
             f" skipped {[s['reason'] for s in run_body['skipped']]}"
             f" / 差し替えた 1 件は残った {Path(changed).exists()}")
        # **失効したら何も消えない**
        prev2 = client.post("/api/locations/bulk-delete/preview", headers=human,
                            json={"scope": {"kind": "assets",
                                            "asset_ids": [safety[4]["asset_id"]]},
                                  "stage": 2}).json()
        clock.advance(sec=601)
        expired = client.post("/api/locations/bulk-delete", headers=human,
                              json={"preview_id": prev2["preview_id"], "confirm": True,
                                    "confirm_last_copy": True})
        line("線 8b 失効した凍結では 1 枚も消さない",
             expired.status_code == 409 and expired.json()["code"] == "preview_expired"
             and Path(safety[4]["display_path"]).exists(),
             f"{expired.status_code} {expired.json().get('code')}"
             f" / ファイルは残った {Path(safety[4]['display_path']).exists()}")

        # --- 安全: last_copy / 上限 / 印の無い置き場 / 別ボリューム / GET が書かない ---
        lastc = client.post("/api/locations/delete", headers=human,
                            json={"asset_id": safety[0]["asset_id"],
                                  "path": safety[0]["display_path"], "stage": 3})
        line("安全 last_copy（最後の 1 つは重い確認）",
             lastc.status_code == 409 and lastc.json()["code"] == "last_copy"
             and Path(safety[0]["display_path"]).exists(),
             f"{lastc.status_code} {lastc.json().get('code')}"
             f" / ファイルは残った {Path(safety[0]['display_path']).exists()}")

        # **上限**（preview を迂回して 201 件の凍結を直に入れる。§8.4 F3）
        logs_before = app.state.store.con.execute("SELECT count(*) AS n FROM deletion_log"
                                                 ).fetchone()["n"]
        sneaky = [{"asset_id": safety[1]["asset_id"], "path": safety[1]["path"],
                   "display_path": safety[1]["display_path"], "size": 1, "mtime_ns": 1}
                  for _ in range(201)]
        with app.state.store.transaction() as c:
            c.execute("INSERT INTO pending_delete_preview(id, stage, scope_json, items_json,"
                      " count, bytes, actor, created_at, expires_at)"
                      " VALUES ('probe-sneaky', 2, '{}', ?, 201, 201, 'agent', 't',"
                      " '2999-01-01T00:00:00Z')", (json.dumps(sneaky),))
        many = client.post("/api/locations/bulk-delete", headers=agent,
                           json={"preview_id": "probe-sneaky", "confirm": True})
        left = app.state.store.con.execute("SELECT count(*) AS n FROM deletion_log"
                                           ).fetchone()["n"]
        line("安全 上限（エージェントは 200 枚まで・部分適用しない）",
             many.status_code == 422 and many.json()["code"] == "too_many"
             and Path(safety[1]["display_path"]).exists() and left == logs_before,
             f"{many.status_code} {many.json().get('code')}"
             f"（201 件の凍結。1 枚も消していない／台帳 {logs_before} → {left} 行）")

        # **印の無い置き場**（root.allow_stage3 = 0）
        plain = noflag / "noflag.png"
        plain.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(Path(safety[1]["display_path"]), plain)
        key = normalize_path(plain)
        st = plain.stat()
        with app.state.store.transaction() as c:
            c.execute("UPDATE asset_location SET path = ?, display_path = ?, size = ?,"
                      " mtime_ns = ?, missing_at = NULL WHERE path = ?",
                      (key, str(plain), st.st_size, st.st_mtime_ns, safety[1]["path"]))
        denied = client.post("/api/locations/delete", headers=human,
                             json={"asset_id": safety[1]["asset_id"], "path": str(plain),
                                   "stage": 3, "confirm_last_copy": True})
        allowed1 = client.post("/api/locations/delete", headers=human,
                               json={"asset_id": safety[1]["asset_id"], "path": str(plain),
                                     "stage": 1})
        line("安全 印の無い root では段 3 を断る（段 1 は通る）",
             denied.status_code == 409 and denied.json()["code"] == "stage_not_allowed"
             and allowed1.status_code == 200,
             f"段 3: {denied.status_code} {denied.json().get('code')} / 段 1:"
             f" {allowed1.status_code}")

        # **別ボリューム**（st_dev を注入。実機に 2 つ目のボリュームが要らない）
        import image_reviewer.deletions as deletions_mod          # noqa: PLC0415
        real_dev = deletions_mod.st_dev_of

        def fake_dev(candidate):
            text = str(candidate).lower()
            if HOLD_DIR in text or "trash" in text:
                return real_dev(candidate) + 1
            return real_dev(candidate)

        deletions_mod.st_dev_of = fake_dev
        try:
            cross = client.post("/api/locations/delete", headers=human,
                                json={"asset_id": safety[2]["asset_id"],
                                      "path": safety[2]["display_path"], "stage": 3,
                                      "confirm_last_copy": True})
        finally:
            deletions_mod.st_dev_of = real_dev
        line("安全 別ボリュームは断る（コピーもしない）",
             cross.status_code == 409 and cross.json()["code"] == "cross_volume"
             and Path(safety[2]["display_path"]).exists(),
             f"{cross.status_code} {cross.json().get('code')}"
             f" / ファイルは残った {Path(safety[2]['display_path']).exists()}")

        # **実機の D: があれば、注入なしで 1 回試す**（設計 §10-6 の宿題）
        try:
            d_root = Path("D:/p8-2-probe-tmp")
            d_root.mkdir(parents=True, exist_ok=True)
            d_file = d_root / "on-d.png"
            shutil.copy2(Path(safety[3]["display_path"]), d_file)
            d_key = normalize_path(d_file)
            with app.state.store.transaction() as c:
                c.execute("UPDATE asset_location SET path = ?, display_path = ?, size = ?,"
                          " mtime_ns = ?, missing_at = NULL WHERE path = ?",
                          (d_key, str(d_file), d_file.stat().st_size, d_file.stat().st_mtime_ns,
                           safety[3]["path"]))
            real_cross = client.post("/api/locations/delete", headers=human,
                                     json={"asset_id": safety[3]["asset_id"],
                                           "path": str(d_file), "stage": 3,
                                           "confirm_last_copy": True})
            line("安全 実機の別ボリューム（D:）でも断る",
                 real_cross.status_code == 409 and real_cross.json()["code"] == "cross_volume"
                 and d_file.exists(),
                 f"{real_cross.status_code} {real_cross.json().get('code')}"
                 f"（C: の保留領域へはコピーしない）")
            shutil.rmtree(d_root, ignore_errors=True)
        except OSError as exc:
            print(f"   [--] 実機の別ボリューム（D:）は試せない: {exc}")

        # **GET は 1 バイトも書かない**
        before_sig = snapshot()
        client.get("/api/pending-deletes", headers=human)
        client.get("/api/deletions", headers=human)
        client.get("/api/trash", headers=human)
        client.get("/api/deletions/trash", headers=human)
        after_sig = snapshot()
        line("家風 GET は 1 バイトも書かない", before_sig == after_sig,
             "全表の行数とファイルの size / mtime が同じ" if before_sig == after_sig
             else "GET の前後で変わった")

        # **403 / 422**（守り）
        guard_host = client.post("/api/locations/delete", headers={"Host": "evil", **human},
                                 json={"asset_id": copies[0]["asset_id"], "path": "x", "stage": 1})
        guard_type = client.post("/api/locations/delete",
                                 headers={**human, "Content-Type": "text/plain"},
                                 content=json.dumps({"stage": 1}))
        guard_actor = client.post("/api/locations/delete",
                                  headers={"X-Image-Reviewer-Actor": "robot"},
                                  json={"stage": 1})
        guard_stage = client.post("/api/locations/delete", headers=human,
                                  json={"asset_id": "x", "path": "y", "stage": 4})
        line("家風 403 / 422（Host・Content-Type・語彙）",
             guard_host.status_code == 403 and guard_type.status_code == 403
             and guard_actor.status_code == 422
             and guard_stage.status_code == 422
             and guard_stage.json()["code"] == "bad_stage",
             f"Host 403={guard_host.status_code} / text/plain 403={guard_type.status_code}"
             f" / actor 422={guard_actor.status_code} / stage 422={guard_stage.status_code}")

    after = real_data_signature()
    same = before == after
    line("実データが無傷（263 枚・判断 3 件・画像の size / mtime）", same,
         f"{before['assets']} 枚 / 判断 {before['decisions']} 件 / 台帳 {before['logs']} 行"
         f" / 画像の署名 {'同じ' if same else '違う'}")
    print(f"   作業場: {WORK}（--keep で残す）")
    return ok


# ---- P8-4（バックアップと復元。線 10〜12）----


def copy_data_dir(into: Path) -> Path:
    """実データの**置き場ごと**複製する（DB は `backup()`・ファイルは `copy2`）。

    `db.sqlite3` を `cp` すると WAL の分（実データは 4 MB あった）が抜けるので、
    **必ず `sqlite3` の `backup()`**。`sidecar/` と `export/` も写す（実データは 1 件ずつ）。
    """
    if into.exists():
        shutil.rmtree(into)
    into.mkdir(parents=True)
    copy_real(into)
    for sub in ("sidecar", "export"):
        src = REAL_DIR / sub
        if src.is_dir():
            shutil.copytree(src, into / sub)
    return into


def zero_bytes(path: Path, start: int, end: int) -> None:
    """**複製の**ページを 0 で潰す（実データでは絶対にやらない）。"""
    with open(path, "r+b") as fh:
        fh.seek(start)
        fh.write(b"\x00" * (end - start))


def probe_broken_forms() -> bool:
    """**壊れた DB の 3 つの形**を実データの複製で測る（設計 §0.16 B3・§10-12）。

    先頭 4 KB / 2 ページ目 / 300 ページ目。`inspect_db` の判定と、
    生の `PRAGMA quick_check` がどうなるか（例外か行か）を出す。
    """
    from image_reviewer.backup import inspect_db                 # noqa: PLC0415

    ok = True
    forms = [("先頭 4KB", 0, 4096), ("2 ページ目", 4096, 8192), ("300 ページ目", 300 * 4096, 301 * 4096)]
    for label, start, end in forms:
        data = copy_real(WORK / f"broken-{start}")
        db_file = data / "db.sqlite3"
        if end > db_file.stat().st_size:
            print(f"   [--] {label}: ファイルが小さい（{db_file.stat().st_size} バイト）")
            continue
        zero_bytes(db_file, start, end)
        got = inspect_db(data)
        detail = (got["quick_check"] or got["error"] or "").replace("\n", " ")[:70]
        good = got["mode"] in ("read_only", "unusable") and got["read_only"] is True
        ok = ok and good
        print(f"   [{'OK' if good else 'NG'}] {label}: mode={got['mode']} reason={got['reason']}"
              f" / 行 {len(got['quick_check_rows'])} / 例外 "
              f"{'あり' if got['error'] else 'なし'} / {detail!r}")
        print(f"        schema_version={got['schema_version']} / 案内: "
              f"{(got['guidance'] or '')[:60]}")
    return ok


def probe_backup() -> bool:
    """P8-4 の線 10・12 を**実データの複製**で通す（実データには触らない）。"""
    ok = True
    before = real_data_signature()
    data = copy_data_dir(WORK / "backup-data")
    out = WORK / "backup-out"
    if out.exists():
        shutil.rmtree(out)
    print(f"P8-4. 実データの複製: {data}（実データ: {before['assets']} 枚 / 判断 "
          f"{before['decisions']} 件 / sidecar "
          f"{len(list((REAL_DIR / 'sidecar').glob('*.json')))} ファイル）")

    def line(label: str, good: bool, detail: str) -> None:
        nonlocal ok
        ok = ok and good
        print(f"   [{'OK' if good else 'NG'}] {label}: {detail}")

    from image_reviewer.backup import (BackupService, list_snapshots,   # noqa: PLC0415
                                       restore, rebuild_metadata, validate_manifest)
    from fastapi.testclient import TestClient                           # noqa: PLC0415

    clock = FakeClock()
    store = Store(data)
    try:
        svc = BackupService(store, clock=clock, backup_dir=out)
        first = svc.tick()
        snap = Path(first["taken"]["dir"]) if first["taken"] else None
        names = sorted(p.name for p in snap.iterdir()) if snap else []
        line("線 10a 日次（4 つできる・WAL を畳む）",
             snap is not None and {"db.sqlite3", "manifest.json", "sidecar", "export"}
             <= set(names),
             f"{snap.name if snap else '-'} / 中身 {names}")
        counts = first["taken"]["counts"] if first["taken"] else {}
        line("線 10b 判断が抜けない（WAL 4 MB を畳む）",
             counts.get("assets") == before["assets"] and counts.get("decisions") == before["decisions"],
             f"画像 {counts.get('assets')} 枚 / 判断 {counts.get('decisions')} 件"
             f"（実データは {before['assets']} / {before['decisions']}）")

        again = svc.tick()
        line("線 10c 自動は同じ日なら増えない", again["skipped"] == "already",
             f"skipped={again['skipped']} / 数 {len(list_snapshots(out))}")

        manual = svc.snapshot(manual=True)
        line("線 10d 「いま取る」は必ず新しく取る",
             manual["name"] != (snap.name if snap else "") and len(list_snapshots(out)) == 2,
             f"{snap.name if snap else '-'} → {manual['name']}")

        manifest = manual["manifest"]
        validate_manifest(manifest)
        db_file = Path(manual["dir"]) / "db.sqlite3"
        import hashlib                                            # noqa: PLC0415
        digest = hashlib.sha256(db_file.read_bytes()).hexdigest()
        line("線 10e manifest が契約を通る（sha256 も一致）",
             manifest["db_sha256"] == f"sha256:{digest}"
             and manifest["db_bytes"] == db_file.stat().st_size,
             f"abi={manifest['abi']} / counts={manifest['counts']}")

        linked = manual["files"]["linked"]
        line("線 10f 増分（前と同じ物はコピーしない）", linked >= 1,
             f"共有 {linked} / 写した {manual['files']['copied']}")

        bad = BackupService(store, clock=clock, backup_dir=data / "inside")
        failed = bad.tick()
        line("線 10g 失敗は last_error に残る（黙って失敗しない）",
             failed["skipped"] == "failed" and bad.state()["last_error"],
             f"{(bad.state()['last_error'] or '')[:50]}")

        # --- 線 12: 壊れた DB の 3 つの形 ---
        print("   壊れた DB の 3 つの形（実データの複製で）:")
        ok = probe_broken_forms() and ok
    finally:
        store.close()

    # --- 口（HTTP）---
    app = fresh_app(data, out)
    human = {"X-Image-Reviewer-Actor": "human"}
    agent = {"X-Image-Reviewer-Actor": "agent"}
    with TestClient(app, base_url="http://127.0.0.1") as client:
        health = client.get("/api/health/db", headers=human)
        line("線 12a 健康な DB の health/db は 200",
             health.status_code == 200 and health.json()["quick_check"] == "ok",
             f"{health.status_code} / {health.json().get('quick_check')}")
        taken = client.post("/api/backup", headers=human, json={})
        line("線 10h POST /api/backup（人だけ）",
             taken.status_code == 200 and client.post(
                 "/api/backup", headers=agent, json={}).status_code == 403,
             f"人 {taken.status_code} / エージェント "
             f"{client.post('/api/backup', headers=agent, json={}).status_code}")
        state = client.get("/api/backup", headers=human).json()
        line("線 10i GET /api/backup（一覧と最後の時刻）",
             state["count"] >= 1 and state["last_at"] and state["last_error"] is None,
             f"数 {state['count']} / 最後 {state['last_at']} / 次 {state['next_run_at']}")

        roots = client.get("/api/roots", headers=human).json()["roots"]
        marked = [r for r in roots if r["allow_stage3"]]
        line("線 12b 実データの置き場に段 3 の印がある（Q8・P8-0）",
             bool(marked), f"{len(marked)} / {len(roots)} 本に印: "
                           f"{[r['path'] for r in marked][:2]}")
        if roots:
            target = roots[0]
            flipped = client.post(f"/api/roots/{target['id']}/allow-stage3", headers=human,
                                  json={"allow": not target["allow_stage3"]})
            back = client.post(f"/api/roots/{target['id']}/allow-stage3", headers=human,
                               json={"allow": target["allow_stage3"]})
            line("線 12c allow-stage3 の口（立てて外せる・人だけ）",
                 flipped.status_code == 200 and back.status_code == 200
                 and client.post(f"/api/roots/{target['id']}/allow-stage3", headers=agent,
                                 json={"allow": True}).status_code == 403,
                 f"{flipped.json().get('allow_stage3')} → "
                 f"{back.json().get('allow_stage3')} / エージェント 403")

        tables = [r["name"] for r in app.state.store.con.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY name")]
        rows_before = tuple(app.state.store.con.execute(
            f"SELECT count(*) AS n FROM {t}").fetchone()["n"] for t in tables)
        files_before = tuple(sorted((str(p.relative_to(data)), p.stat().st_size,
                                     p.stat().st_mtime_ns)
                                    for p in data.rglob("*") if p.is_file()))
        for path in ("/api/backup", "/api/health/db", "/api/settings", "/api/roots",
                     "/api/assets", "/api/stats"):
            client.get(path, headers=human)
        rows_after = tuple(app.state.store.con.execute(
            f"SELECT count(*) AS n FROM {t}").fetchone()["n"] for t in tables)
        files_after = tuple(sorted((str(p.relative_to(data)), p.stat().st_size,
                                    p.stat().st_mtime_ns)
                                   for p in data.rglob("*") if p.is_file()))
        line("家風 GET は 1 バイトも書かない（全表・全ファイル）",
             rows_before == rows_after and files_before == files_after,
             "同じ" if rows_before == rows_after and files_before == files_after else "変わった")

        guards = [
            client.post("/api/backup", headers={"Host": "evil", **human}, json={}),
            client.post("/api/backup", headers={**human, "Content-Type": "text/plain"},
                        content=b"{}"),
            client.post("/api/backup", headers={"X-Image-Reviewer-Actor": "robot"}, json={}),
            client.patch("/api/settings", headers=human, json={"backup_dir": str(data / "b")}),
            client.post("/api/backup", headers=human, json={"out": str(data / "b")}),
        ]
        line("家風 403 / 422（Host・Content-Type・語彙・<data> の中）",
             [g.status_code for g in guards] == [403, 403, 422, 422, 422],
             f"{[g.status_code for g in guards]}")

    # --- 壊れた DB（2 ページ目）で起動するか ---
    broken = copy_data_dir(WORK / "backup-broken")
    zero_bytes(broken / "db.sqlite3", 4096, 8192)
    broken_app = fresh_app(broken, out)
    with TestClient(broken_app, base_url="http://127.0.0.1") as client:
        health = client.get("/api/health/db", headers=human)
        write = client.post("/api/backup", headers=human, json={})
        read = client.get("/api/assets", headers=human)
        line("線 12d 壊れた DB でも起動し、書き込みは 503・読みは生かす",
             health.status_code == 503 and write.status_code == 503
             and write.json()["code"] == "read_only" and read.status_code == 200,
             f"health {health.status_code} / 書き {write.status_code} / 読み {read.status_code}"
             f" / 案内 {(health.json().get('guidance') or '')[:40]}")

    after = real_data_signature()
    line("実データが無傷（複製だけで試した）", before == after,
         f"{after['assets']} 枚 / 判断 {after['decisions']} 件 / 台帳 {after['logs']} 行")
    print(f"   作業場: {WORK}（--keep で残す）")
    return ok


def probe_restore() -> bool:
    """P8-4 の線 11 を**実データの複製**で通す（`<data>` を消して戻す・組み直し）。"""
    ok = True
    before = real_data_signature()
    data = copy_data_dir(WORK / "restore-data")
    out = WORK / "restore-out"
    if out.exists():
        shutil.rmtree(out)
    print(f"P8-4（復元）. 実データの複製: {data}")

    def line(label: str, good: bool, detail: str) -> None:
        nonlocal ok
        ok = ok and good
        print(f"   [{'OK' if good else 'NG'}] {label}: {detail}")

    from image_reviewer.backup import BackupService, rebuild_metadata, restore  # noqa: PLC0415
    from fastapi.testclient import TestClient                                   # noqa: PLC0415

    clock = FakeClock()
    store = Store(data)
    try:
        svc = BackupService(store, clock=clock, backup_dir=out)
        snap = svc.snapshot(manual=False)
        # 英訳を持つ枚（実データは sidecar が 1 件）を覚えておく
        with store.locked() as con:
            row = con.execute("SELECT asset_id FROM asset_meta WHERE meta_json LIKE"
                              " '%en_text%' LIMIT 1").fetchone()
            with_en = row["asset_id"] if row else None
    finally:
        store.close()
    line("線 11a スナップショットを取った", snap["counts"]["assets"] == before["assets"],
         f"{snap['name']} / 画像 {snap['counts']['assets']} 枚 / "
         f"判断 {snap['counts']['decisions']} 件 / 英訳つき {'あり' if with_en else 'なし'}")

    shutil.rmtree(data)                                  # **複製の `<data>` を丸ごと消す**
    line("線 11b `<data>` を丸ごと消した", not data.exists(), f"{data} は {'無い' if not data.exists() else '在る'}")

    got = restore(data, Path(snap["dir"]), clock=clock, backup_dir=out)
    line("線 11c 263 枚・判断 3 件が戻る",
         got["counts"]["assets"] == before["assets"]
         and got["counts"]["decisions"] == before["decisions"] and got["after"]["ok"],
         f"画像 {got['counts']['assets']} / 判断 {got['counts']['decisions']} / "
         f"integrity {got['after']['detail']}")
    line("線 11d sidecar も戻る（PNG から取り直せない物）",
         bool(list((data / "sidecar").glob("*.json"))),
         f"{len(list((data / 'sidecar').glob('*.json')))} ファイル / "
         f"export {len(list((data / 'export').rglob('*')))} 件")

    store = Store(data)
    try:
        if with_en:
            with store.transaction() as con:             # 英訳を消してから組み直す
                con.execute("UPDATE asset_meta SET meta_json = '{}' WHERE asset_id = ?",
                            (with_en,))
            stats = rebuild_metadata(store)
            meta = store.asset(with_en)["meta"]
            line("線 11e rebuild-metadata で sidecar から英訳が戻る",
                 meta.get("en_text") is not None,
                 f"埋めた {stats['updated']} / sidecar から {stats['from_sidecar']} / "
                 f"英訳 {str(meta.get('en_text'))[:24]!r}")
        else:
            print("   [--] 英訳つきの枚が無いので rebuild-metadata は試せない")
        # **DB にある値は上書きしない**
        asset_id = store.assets()[0]["id"]
        with store.transaction() as con:
            con.execute("UPDATE asset_meta SET meta_json = ? WHERE asset_id = ?",
                        (json.dumps({"model": "db-value"}), asset_id))
        rebuild_metadata(store)
        line("線 11f 組み直しは DB の値を上書きしない",
             store.asset(asset_id)["meta"].get("model") == "db-value",
             f"model={store.asset(asset_id)['meta'].get('model')}")
    finally:
        store.close()

    after = real_data_signature()
    line("実データが無傷（複製だけで試した）", before == after,
         f"{after['assets']} 枚 / 判断 {after['decisions']} 件 / 台帳 {after['logs']} 行")
    print(f"   作業場: {WORK}（--keep で残す）")
    return ok


def fresh_app(data: Path, backup_dir: Path):
    """**複製に向けた**アプリを作る（`IMAGE_REVIEWER_DATA` を必ず付ける）。

    import 時に作られた `app`（前の probe のデータを掴んでいる）の接続は先に閉じる
    （開いたままだと、Windows では作業場を消せない）。
    """
    os.environ["IMAGE_REVIEWER_DATA"] = str(data)
    os.environ["IMAGE_REVIEWER_BACKUP_DIR"] = str(backup_dir)
    from image_reviewer import app as app_module                # noqa: PLC0415

    try:
        app_module.app.state.store.close()
    except Exception:                                            # noqa: BLE001
        pass
    return app_module.create_app()



if __name__ == "__main__":
    raise SystemExit(main())
