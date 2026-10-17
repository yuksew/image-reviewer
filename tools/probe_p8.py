"""P8-1（重複の検出と整理）の合格の線を実データで出す（設計 §1.2 の線 1〜3）。

**実データ `.data/` は `mode=ro` でしか開かない。** 試験は `backup()` で作った複製で行う
（`db.sqlite3` だけ複写すると WAL の分が抜けて判断が消える）。

    uv run --no-sync python tools/probe_p8.py            # 複製を作って線を通す
    uv run --no-sync python tools/probe_p8.py --keep     # 複製を残す
"""

from __future__ import annotations

import argparse
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

from image_reviewer import db                                    # noqa: E402
from image_reviewer.duplicates import (BANDS, DuplicatesService, bands_of,  # noqa: E402
                                       candidate_pairs, near_groups)
from image_reviewer.store import Store                           # noqa: E402

REAL = ROOT / ".data" / "db.sqlite3"
WORK = ROOT / ".tmp-audit-redo" / "p8probe"


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


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--keep", action="store_true")
    args = ap.parse_args()
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
        decoded = started["total"] - hashed0          # **復号するのは pHash の無い枚だけ**
        per = took / max(1, decoded)
        print(f"   job={job['state']} / {job['message']} / 実測 {took:.1f} 秒"
              f"（復号した {decoded} 枚で {per * 1000:.1f} ms/枚）")
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
        print("2. 帯 vs 総当たり（距離ごと）:")
        for dist in (0, 3, 6, 10, 15, 16, 32, 64):
            t0 = time.monotonic()
            band = {tuple(sorted((a, b))) for a, b, _ in candidate_pairs(con, dist)}
            band_ms = (time.monotonic() - t0) * 1000
            brute = brute_force(con, dist)
            mark = "OK" if band == brute else "NG"
            if band != brute:
                ok = False
            print(f"   ≤{dist:<2}: 帯 {len(band):>5} 組（{band_ms:5.0f} ms）/ 総当たり {len(brute):>5} 組"
                  f" → {mark}" + ("" if band == brute else
                                  f" 取りこぼし {len(brute - band)} / 余分 {len(band - brute)}"))
        # 参考: ≤6 の群の数（点検・P8-1 の実測と一致するはず）

        # --- 線 1・3: 群の数（≤3 / ≤6 / ≤10）と完全重複 ---
        print("3. 群（連結成分）:")
        for dist in (3, 6, 10):
            got = svc.near(max_distance=dist)
            print(f"   ≤{dist}: {got['total_groups']} 群 / {got['total_images']} 枚"
                  f"（pHash あり {got['hashed']}・未計算 {got['unhashed']}）")
        got6 = svc.near(max_distance=6)
        expect = {3: (17, 39), 6: (21, 57), 10: (28, 87)}[6]
        if (got6["total_groups"], got6["total_images"]) != expect:
            ok = False
            print(f"   NG: ≤6 が {expect} のはず（点検の実測）")
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

    print("\nまとめ:", "すべて OK" if ok else "NG あり")
    if args.keep:
        print("残した:", data)
    else:
        shutil.rmtree(WORK, ignore_errors=True)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
