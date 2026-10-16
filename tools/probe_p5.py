"""P5-0 の前に確かめる 3 件（設計 p5-design.md §0.1・p5-triage §3）。

1. F1: Python 同梱の SQLite で**部分索引**（`... WHERE ... IS NOT NULL`）が使えるか
2. F2: Pillow の `F` モード画像に `GaussianBlur` が効くか
3. F5: pHash の実費用（**復号込み**と純 Python の DCT を分けて測る）

使い方: uv run python tools/probe_p5.py [--images 200]
"""

from __future__ import annotations

import argparse
import math
import os
import sqlite3
import sys
import time
from pathlib import Path

from PIL import Image, ImageFilter

COS = [[math.cos((2 * x + 1) * u * math.pi / 64) for x in range(32)] for u in range(8)]


def probe_sqlite() -> None:
    print("=" * 74)
    print("1. SQLite の部分索引（F1）")
    print(f"   sqlite_version = {sqlite3.sqlite_version}")
    con = sqlite3.connect(":memory:")
    con.executescript(
        """
        CREATE TABLE decision (id TEXT PRIMARY KEY, subject_id TEXT NOT NULL,
                               seq INTEGER, client_token TEXT);
        CREATE UNIQUE INDEX ux_token ON decision(client_token) WHERE client_token IS NOT NULL;
        """
    )
    con.execute("INSERT INTO decision VALUES ('a','s',1,'tok')")
    con.execute("INSERT INTO decision VALUES ('b','s',2,NULL)")
    con.execute("INSERT INTO decision VALUES ('c','s',3,NULL)")   # NULL は何個でも入る
    try:
        con.execute("INSERT INTO decision VALUES ('d','s',4,'tok')")
        print("   NG: 重複した client_token が入ってしまった")
    except sqlite3.IntegrityError as exc:
        print(f"   OK: 重複を弾いた（{type(exc).__name__}）")
    n_null = con.execute("SELECT count(*) FROM decision WHERE client_token IS NULL").fetchone()[0]
    print(f"   OK: NULL は {n_null} 件入る（部分索引が NULL を除外している）")
    # 部分索引が効いているか（EXPLAIN QUERY PLAN）
    plan = con.execute(
        "EXPLAIN QUERY PLAN SELECT id FROM decision WHERE client_token = 'tok'"
    ).fetchall()
    used = any("ux_token" in str(r) for r in plan)
    print(f"   {'OK' if used else '注意'}: 検索で部分索引を使う = {used}")
    # WAL と同時アクセス
    con.close()
    tmp = Path(os.environ.get("TEMP", ".")) / "probe_wal.sqlite3"
    if tmp.exists():
        tmp.unlink()
    c1 = sqlite3.connect(tmp)
    print(f"   journal_mode -> {c1.execute('PRAGMA journal_mode=WAL').fetchone()[0]}")
    print(f"   foreign_keys -> {c1.execute('PRAGMA foreign_keys=ON').fetchone()}")
    c1.close()
    tmp.unlink(missing_ok=True)


def probe_pillow_fmode() -> None:
    print("=" * 74)
    print("2. Pillow の F モードとぼかし（F2）")
    im = Image.new("F", (64, 64), 0.0)
    im.putpixel((32, 32), 1.0)
    try:
        blurred = im.filter(ImageFilter.GaussianBlur(2.0))
        v = blurred.getpixel((32, 32))
        # 中心の値が減り、隣が増えていれば「効いている」
        nb = blurred.getpixel((33, 32))
        ok = 0 < v < 1.0 and nb > 0.0
        print(f"   F モード + GaussianBlur: 中心={v:.4f} 隣={nb:.5f} -> {'OK（効く）' if ok else 'NG（効かない）'}")
    except Exception as exc:  # noqa: BLE001
        print(f"   NG: {type(exc).__name__}: {exc}")
    try:
        a = Image.new("F", (8, 8))
        b = Image.new("F", (8, 8))
        d = Image.blend(a, b, 0.5)
        print(f"   F モードの算術（Image.blend）: OK（{d.mode}）")
    except Exception as exc:  # noqa: BLE001
        print(f"   F モードの算術: NG {type(exc).__name__}: {exc}")


def dct_phash(path: str) -> tuple[str, bytes]:
    """純 Python の DCT で pHash（64bit）。復号と DCT を分けて測れるよう生データを返す。"""
    with Image.open(path) as im:
        small = im.convert("L").resize((32, 32), Image.LANCZOS)
    px = list(small.getdata())
    rows = [px[y * 32:(y + 1) * 32] for y in range(32)]
    # 分離 DCT: 横 8 係数 → 縦 8 係数
    tmp = [[sum(COS[u][x] * rows[y][x] for x in range(32)) for u in range(8)] for y in range(32)]
    coef = [[sum(COS[v][y] * tmp[y][u] for y in range(32)) for u in range(8)] for v in range(8)]
    vals = [coef[v][u] for v in range(8) for u in range(8)]
    avg = sum(vals) / 64
    bits = 0
    for i, v in enumerate(vals):
        if v > avg:
            bits |= 1 << i
    return f"{bits:016x}", bytes(px)


def probe_phash(limit: int) -> None:
    print("=" * 74)
    print(f"3. pHash の実費用（F5。復号と DCT を分けて測る。{limit} 枚）")
    root = Path(r"C:\work\illust-authoring\.store\anima-dev\images")
    files = sorted(p for p in root.glob("*.png"))[:limit] if root.is_dir() else []
    if not files:
        print(f"   対象が無い: {root}")
        return
    t_decode = t_dct = 0.0
    total_bytes = 0
    sample = None
    for p in files:
        total_bytes += p.stat().st_size
        t0 = time.perf_counter()
        with Image.open(p) as im:
            small = im.convert("L").resize((32, 32), Image.LANCZOS)
        px = list(small.getdata())
        t1 = time.perf_counter()
        rows = [px[y * 32:(y + 1) * 32] for y in range(32)]
        tmp = [[sum(COS[u][x] * rows[y][x] for x in range(32)) for u in range(8)] for y in range(32)]
        coef = [[sum(COS[v][y] * tmp[y][u] for y in range(32)) for u in range(8)] for v in range(8)]
        vals = [coef[v][u] for v in range(8) for u in range(8)]
        avg = sum(vals) / 64
        bits = 0
        for i, v in enumerate(vals):
            if v > avg:
                bits |= 1 << i
        t2 = time.perf_counter()
        t_decode += t1 - t0
        t_dct += t2 - t1
        if sample is None:
            sample = (p.name, f"{bits:016x}")
    n = len(files)
    avg_ms = (t_decode + t_dct) / n * 1000
    print(f"   平均 {total_bytes / n / 1024:.0f} KB / 枚")
    print(f"   復号 + 32x32 縮小 : {t_decode / n * 1000:6.2f} ms/枚")
    print(f"   純 Python の DCT  : {t_dct / n * 1000:6.2f} ms/枚")
    print(f"   合計              : {avg_ms:6.2f} ms/枚  -> 1,000 枚で {avg_ms * 1000 / 1000:.1f} 秒")
    print(f"   1 万枚の見込み     : {avg_ms * 10000 / 1000 / 60:.1f} 分")
    print(f"   例: {sample[0]} -> {sample[1]}")
    print(f"   → 背景ジョブに要るか: {'要る（重い）' if avg_ms > 20 else '要求時に計算してもよい'}")


def probe_phash_p5_3(limit: int) -> None:
    """P5-3 の実装（`compare.hash_file`）で、**実測 F5 を測り直す**。

    設計 §0.7 の実測は「復号＋32×32 縮小 11.35 ms / 純 Python の DCT 0.53 ms / 合計 11.88 ms」。
    実装は numpy の DCT と dHash を足したので、同じものを**実装のまま**測って比べる
    （`.` の実データ = `IMAGE_REVIEWER_DATA`。**読み取り専用**で開く）。
    """
    print("=" * 74)
    print(f"4. 実装した pHash / dHash の実費用（P5-3。{limit} 枚）")
    try:
        from image_reviewer import compare
    except Exception as exc:  # noqa: BLE001
        print(f"   image_reviewer を読み込めない: {exc}")
        return
    data_dir = Path(os.environ.get("IMAGE_REVIEWER_DATA",
                                   Path(__file__).resolve().parents[1] / ".data"))
    db_path = data_dir / "db.sqlite3"
    if not db_path.exists():
        print(f"   実データが無い: {db_path}")
        return
    con = sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    try:
        rows = con.execute(
            "SELECT a.id, l.display_path, l.missing_at FROM asset a"
            " JOIN asset_location l ON l.asset_id = a.id"
            " ORDER BY l.is_primary DESC, a.id").fetchall()
    finally:
        con.close()
    paths, seen = [], set()
    for r in rows:
        if r["id"] in seen or r["missing_at"] is not None:
            continue
        p = Path(r["display_path"])
        if p.exists():
            seen.add(r["id"])
            paths.append(p)
    if not paths:
        print("   実体のある枚が無い")
        return
    sample = paths[:limit]
    print(f"   対象 {len(sample)} 枚（実データは {len(seen)} 枚）/ 例 {Image.open(sample[0]).size}")

    def bench(fn, rounds, *, per_image=True):
        """1 回の `fn()` を `rounds` 回。`per_image` なら 1 枚あたりに直す。"""
        fn()                                        # 温める
        started = time.perf_counter()
        for _ in range(rounds):
            fn()
        spent = (time.perf_counter() - started) / rounds * 1000
        return spent / len(sample) if per_image else spent

    # `decode` と `full` はサンプル全枚を回す。`pure` / `only_*` は復号済みの 1 枚
    decode = bench(lambda: [Image.open(p).convert("RGB").close() for p in sample], 3)
    full = bench(lambda: [compare.hash_file(p) for p in sample], 3)
    with Image.open(sample[0]) as im:
        ready = im.convert("RGB")
    pure = bench(lambda: compare.hashes_of_image(ready), 20, per_image=False)
    only_p = bench(lambda: compare.phash_bits(ready), 40, per_image=False)
    only_d = bench(lambda: compare.dhash_bits(ready), 40, per_image=False)

    print(f"   復号のみ（convert まで）     : {decode:6.2f} ms/枚")
    print(f"   復号 + pHash + dHash        : {full:6.2f} ms/枚")
    print(f"   その差（2 つの縮小 + DCT/勾配）: {full - decode:6.2f} ms/枚")
    print(f"   復号済みからの pHash + dHash  : {pure:6.2f} ms/枚"
          f"（pHash {only_p:.2f} / dHash {only_d:.2f}）")
    print("   設計 §0.7 の実測            : 復号+縮小 11.35 / DCT 0.53 / 合計 11.88")
    print("   → サムネイルと同じ復号に同居させる（背景ジョブにしない）で正しい")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--images", type=int, default=120)
    args = ap.parse_args()
    probe_sqlite()
    probe_pillow_fmode()
    probe_phash(args.images)
    probe_phash_p5_3(20)
    print("=" * 74)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
