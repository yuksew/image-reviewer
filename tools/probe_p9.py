"""P9 の性能の計測（設計 `docs/design.md` §12.1 の「目標」の行を実測で埋める）。

**測り方の約束**（家風。P4・P6 の教訓）:
- **サーバ内で測る**（`TestClient`＝ASGI を直接叩く。**ネットワークを挟まない**）。
  比較のため `/api/health` の p95 を「**土台（枠の費用）**」として一緒に出す
- **何回の中央値・何回の p95 か**を書く（既定は 50 回。`--runs` で変えられる）
- **別々の入力で測る**（同じ 1 枚を繰り返し叩かない。サムネイルは 24 枚を順に回す）
- **「生成済み」と「初回生成」を分ける**（1024px サムネイル）
- **実データには 1 バイトも書かない**。合成 DB と複製だけで測る

測る物（§12.1 の行との対応）:
| この道具の印 | §12.1 の行 |
| --- | --- |
| `--list` | 一覧 API の応答（p95 20ms 以内・1 万枚の DB・サーバ内） |
| `--thumbs` | 詳細表示（1024 サムネ）200ms 以内（生成済み）／**サムネイル生成 1 万枚（1024px）は未定** |
| `--compare` | 比較の 8 枚表示 400ms 以内（生成済み） |
| `--scan` | 初回走査 1 万枚（ハッシュ＋登録）90 秒以内／2 回目以降（差分なし）10 秒以内 |
| `--delete` | 一括削除の再照合（1,000 件で 1 秒以内。§12.3） |
| `--relink` | 再リンクの `nearby`（1 万枚の置き場で同じ名前を探す） |
| `--library` | `--include-library`（実データ 292 MB。§12.3） |

使い方:
    $env:UV_CACHE_DIR = "C:\\work\\image-reviwer\\.uv-cache"
    uv run --no-sync python -X utf8 tools/probe_p9.py --all
    uv run --no-sync python -X utf8 tools/probe_p9.py --list --thumbs --compare
    uv run --no-sync python -X utf8 tools/probe_p9.py --library --replica <実データの複製>

後始末: `--keep` を付けないと、**この道具が作った複製**（`<out>/w/*`）は消す。
合成 DB（`<out>/synth10k`）は **`make_synthetic_db.py` の物**なので消さない（`--rebuild-synth` で作り直す）。
"""

from __future__ import annotations

import argparse
import os
import shutil
import sqlite3
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

REAL_DATA = ROOT / ".data"
OK = True
FAILURES: list[str] = []


# ---- 小物 ----


def say(line: str = "") -> None:
    print(line, flush=True)


def at(ordered: list[float], q: float) -> float:
    return ordered[min(len(ordered) - 1, int(round(q * (len(ordered) - 1))))]


def report(title: str, samples: list[float], limit_ms: float | None = None,
           note: str = "") -> dict:
    """p50 / p95 / max / 中央値を出す。`limit_ms` があれば合否も出す。"""
    global OK
    ordered = sorted(samples)
    got = {"n": len(ordered), "min": ordered[0], "p50": at(ordered, .5), "p95": at(ordered, .95),
           "max": ordered[-1], "mean": statistics.fmean(ordered), "median": statistics.median(ordered)}
    line = (f"  {title}: n={got['n']} min={got['min']:.1f} p50={got['p50']:.1f}"
            f" p95={got['p95']:.1f} max={got['max']:.1f} mean={got['mean']:.1f} ms")
    if limit_ms is None:
        say(line + (f"  （{note}）" if note else ""))
        return got
    ok = got["p95"] <= limit_ms
    OK = OK and ok
    if not ok:
        FAILURES.append(f"{title}: p95 {got['p95']:.1f} ms > 目標 {limit_ms:.0f} ms")
    say(line + f"  -> {'OK' if ok else 'NG'}（目標 {limit_ms:.0f} ms）" + (f"  {note}" if note else ""))
    return got


def backup_db(src: Path, dst_dir: Path) -> Path:
    """`sqlite3` の `backup()` で複製する（**WAL を畳む**。`cp` では判断が抜ける）。"""
    dst_dir.mkdir(parents=True, exist_ok=True)
    dst = dst_dir / "db.sqlite3"
    src_con = sqlite3.connect(f"file:{src.as_posix()}?mode=ro", uri=True, timeout=30.0)
    dst_con = sqlite3.connect(dst)
    try:
        src_con.backup(dst_con)
    finally:
        dst_con.close()
        src_con.close()
    return dst


def make_app(data_dir: Path, backup_dir: Path):
    """`IMAGE_REVIEWER_DATA` を向けてアプリを作る（**実データは開かない**）。"""
    os.environ["IMAGE_REVIEWER_DATA"] = str(data_dir)
    os.environ["IMAGE_REVIEWER_BACKUP_DIR"] = str(backup_dir)
    for mod in [m for m in list(sys.modules) if m.startswith("image_reviewer")]:
        del sys.modules[mod]
    from image_reviewer.app import create_app

    return create_app()


class Client:
    """`TestClient`（ASGI 直叩き。**ネットワークを挟まない**）と時間の測り方をまとめる。"""

    def __init__(self, data_dir: Path, backup_dir: Path):
        from fastapi.testclient import TestClient

        self.app = make_app(data_dir, backup_dir)
        self._ctx = TestClient(self.app)
        self.client = self._ctx.__enter__()

    def close(self) -> None:
        self._ctx.__exit__(None, None, None)

    def get(self, url: str, **kw) -> tuple[int, dict | bytes, float, int]:
        t0 = time.perf_counter()
        res = self.client.get(url, headers={"Host": "127.0.0.1"}, **kw)
        ms = (time.perf_counter() - t0) * 1000
        try:
            body = res.json()
        except ValueError:
            body = res.content
        return res.status_code, body, ms, len(res.content)


def ids_of(data_dir: Path, *, limit: int | None = None, big: bool = False) -> list[str]:
    """合成 DB から枚を選ぶ（`big=True` は 1024x1024 の枚＝サムネイルの計測用）。"""
    con = sqlite3.connect(f"file:{(data_dir / 'db.sqlite3').as_posix()}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    try:
        sql = ("SELECT a.id FROM asset a JOIN asset_location l ON l.asset_id = a.id"
               " WHERE l.missing_at IS NULL AND a.deleted_at IS NULL AND a.width = 1024"
               " ORDER BY l.display_path")
        rows = [r["id"] for r in con.execute(sql)]
        if not big:
            sql2 = ("SELECT a.id FROM asset a JOIN asset_location l ON l.asset_id = a.id"
                    " WHERE l.missing_at IS NULL AND a.deleted_at IS NULL"
                    " ORDER BY l.display_path LIMIT ?")
            rows = [r["id"] for r in con.execute(sql2, (limit or 100,))]
        return rows[:limit] if limit else rows
    finally:
        con.close()


# ---- 1. 一覧 API ----


def probe_list(out: Path, synth: Path, runs: int) -> None:
    say("\n1. 一覧 API の応答（1 万枚の DB・**サーバ内**＝`TestClient`。目標 p95 20 ms）")
    cli = Client(synth, out / "backups")
    try:
        floor = []
        for _ in range(runs):
            floor.append(cli.get("/api/health")[2])
        report("GET /api/health（**土台**＝枠の費用。目標なし）", floor)

        first = cli.get("/api/assets")
        total = first[1]["total"]
        say(f"  total = {total} / items = {len(first[1]['items'])} / 応答 {len(str(first[1]))} 字")

        samples, sizes = [], []
        for _ in range(runs):
            status, body, ms, nbytes = cli.get("/api/assets")
            samples.append(ms)
            sizes.append(nbytes)
            assert status == 200, body
        got = report("GET /api/assets（既定 limit=100・sort=path）", samples, 20.0,
                     note=f"本文 {statistics.median(sizes) / 1024:.0f} KB")
        got["total"] = total

        samples = []
        for _ in range(runs):
            samples.append(cli.get("/api/assets?sort=model")[2])
        report("GET /api/assets?sort=model", samples, 20.0)

        samples = []
        for _ in range(runs):
            samples.append(cli.get("/api/assets?state=kept")[2])
        report("GET /api/assets?state=kept（絞り込み）", samples, 20.0)

        samples = []
        for _ in range(runs):
            samples.append(cli.get("/api/assets?tag=1girl&known=1")[2])
        report("GET /api/assets?tag=1girl（語の絞り込み。SQL → メモリ）", samples, 20.0)

        # 参考: 一覧を組む元（`store.assets()` が全部を読んで Python で並べ替える）
        from image_reviewer.store import Store

        store = Store(synth)
        try:
            samples = []
            for _ in range(max(5, runs // 5)):
                t0 = time.perf_counter()
                store.assets()
                samples.append((time.perf_counter() - t0) * 1000)
            report("参考: store.assets()（SQL 3 本＋1 万件の dict 組み立て＋並べ替え）",
                   samples, note="口の外。一覧の下限")
            # どこに時間が行っているかの内訳（**SQL だけ**を別に測る）
            sql_samples = []
            for _ in range(max(5, runs // 5)):
                t0 = time.perf_counter()
                with store.locked() as con:
                    rows = con.execute("SELECT * FROM asset").fetchall()
                    locs = [r for r in con.execute(
                        "SELECT * FROM asset_location ORDER BY is_primary DESC, display_path")]
                    metas = [r for r in con.execute("SELECT * FROM asset_meta")]
                sql_samples.append((time.perf_counter() - t0) * 1000)
            report("  うち SQL の 3 本だけ（`fetchall` まで。dict 組み立てを含まない）",
                   sql_samples, note=f"asset {len(rows)} / location {len(locs)} / meta {len(metas)} 行")
        finally:
            store.close()
    finally:
        cli.close()

    with sqlite3.connect(f"file:{(synth / 'db.sqlite3').as_posix()}?mode=ro", uri=True) as con:
        con.row_factory = sqlite3.Row
        plan = con.execute(
            "EXPLAIN QUERY PLAN SELECT * FROM asset").fetchall()
        say(f"  参考: SELECT * FROM asset の計画 = {plan[0]['detail'] if plan else '?'}")


# ---- 2. サムネイル（1024px）----


def probe_thumbs(out: Path, synth: Path, runs: int) -> None:
    say("\n2. サムネイル（**1024px**。目標 200 ms 以内＝生成済み。初回生成は別に測る）")
    cli = Client(synth, out / "backups")
    try:
        big = ids_of(synth, big=True)
        say(f"  1024x1024 の枚 = {len(big)} 枚（別々の入力を順に回す）")

        # **「初回生成」を測るために、できているサムネイルを消す**（合成 DB の中だけ。
        # 前の計測が残した物があると `ensure_thumb()` が「在る」を返し、
        # 復号が 1 度も走らない＝**測っている物が「配信」に変わる**）
        shutil.rmtree(synth / "thumbs", ignore_errors=True)
        say(f"  できているサムネイルを消した（**合成 DB の中だけ**）: {synth / 'thumbs'}")

        # (a) 初回生成（**サムネイルがまだ無い**状態から）
        gen1024, gen256, bytes1024 = [], [], []
        for asset_id in big:
            status, _body, ms, nbytes = cli.get(f"/api/assets/{asset_id}/thumb?size=1024")
            assert status == 200, (asset_id, status)
            gen1024.append(ms)
            bytes1024.append(nbytes)
        report("**初回生成** 1024px（復号＋縮小＋WebP 書き出し。pHash も同じ復号で入る）",
               gen1024, note=f"{len(gen1024)} 枚の中央値。{statistics.median(bytes1024) / 1024:.0f} KB")
        for asset_id in big:
            status, _b, ms, _n = cli.get(f"/api/assets/{asset_id}/thumb?size=256")
            gen256.append(ms)
        report("**初回生成** 256px（同じ 24 枚）", gen256)

        # (b) 生成済み（**ファイルを返すだけ**）
        samples = []
        for i in range(runs):
            asset_id = big[i % len(big)]
            samples.append(cli.get(f"/api/assets/{asset_id}/thumb?size=1024")[2])
        report("**生成済み** 1024px（`FileResponse`。24 枚を順に回す）", samples, 200.0)

        samples = []
        for i in range(runs):
            asset_id = big[i % len(big)]
            samples.append(cli.get(f"/api/assets/{asset_id}/thumb?size=256")[2])
        report("**生成済み** 256px", samples, 200.0)

        # (c) 1 万枚ぶんの見積り（**実測から比例**）
        med = statistics.median(gen1024)
        say(f"  見積り（**比例**）: 1024px を 1 万枚 = {med:.0f} ms/枚 × 10000 "
            f"= {med * 10000 / 1000 / 60:.1f} 分（1 スレッド。§12.2 はスレッドプールで並列化）")
        med256 = statistics.median(gen256)
        say(f"  見積り（**比例**）: 256px を 1 万枚 = {med256:.0f} ms/枚 × 10000 "
            f"= {med256 * 10000 / 1000 / 60:.1f} 分（§12.1 の目標は 6 分。**実測 36 枚/秒＝4.6 分**）")

        # (d) 詳細表示（`GET /api/assets/{id}` = JSON）
        samples = []
        for i in range(runs):
            samples.append(cli.get(f"/api/assets/{big[i % len(big)]}")[2])
        report("GET /api/assets/{id}（詳細の JSON）", samples, 200.0)
    finally:
        cli.close()


# ---- 2c. 判断の記録（§12.1 の「判断の記録 100 ms 以内」）----


def probe_decide(out: Path, synth: Path, runs: int) -> None:
    """`POST /api/reviews`（1 枚の判断＝台帳 1 行＋現在値）。

    §12.1 の行は「判断の記録 100ms 以内（台帳＋現在値。**書き出しは除く**）」。
    ここは **1 枚ずつ別の枚**に書く（同じ枚に 2 回書くと `supersedes` が増えて形が変わる）。
    """
    say("\n2c. 判断の記録（目標 100 ms 以内。台帳＋現在値。**書き出しは除く**）")
    work = out / "w" / "decide"
    if work.exists():
        shutil.rmtree(work)
    backup_db(synth / "db.sqlite3", work)
    cli = Client(work, out / "backups")
    try:
        ids = ids_of(work, limit=runs + 5)
        samples = []
        for asset_id in ids[:runs]:
            t0 = time.perf_counter()
            res = cli.client.post("/api/reviews",
                                  json={"subject_type": "asset", "subject_id": asset_id,
                                        "verdict": "keep"},
                                  headers={"Host": "127.0.0.1",
                                           "Content-Type": "application/json",
                                           "X-Image-Reviewer-Actor": "human"})
            samples.append((time.perf_counter() - t0) * 1000)
            assert res.status_code == 200, res.text
        body = res.json()
        report("POST /api/reviews（keep を 1 枚ずつ・別々の枚）", samples, 100.0,
               note=f"decision_id={body.get('decision_id')} state={body.get('review_state')}"
                    f" / 掃き出し待ち {body.get('export_pending')}")
    finally:
        cli.close()
    shutil.rmtree(work, ignore_errors=True)


# ---- 3. 比較の 8 枚 ----


def probe_compare(out: Path, synth: Path, runs: int) -> None:
    say("\n3. 比較の 8 枚表示（目標 400 ms 以内＝**生成済み**）")
    cli = Client(synth, out / "backups")
    try:
        big = ids_of(synth, big=True)[:8]
        say(f"  8 枚 = {len(big)} 枚（1024x1024。phash は §2 の初回生成で入っている）")

        # 先に 8 枚の 1024 サムネイルを作っておく（「生成済み」の前提を自分で作る）
        for asset_id in big:
            cli.get(f"/api/assets/{asset_id}/thumb?size=1024")

        samples = []
        for _ in range(runs):
            status, body, ms, _n = cli.get("/api/compare?ids=" + ",".join(big))
            samples.append(ms)
            assert status == 200, body
        report("GET /api/compare?ids=（8 枚の来歴の差分表）", samples, 400.0)

        # 画面は「文書＋8 枚のサムネイル」を取る。**8 枚ぶんの配信**も測って足す
        thumbs = []
        for i in range(runs):
            asset_id = big[i % len(big)]
            thumbs.append(cli.get(f"/api/assets/{asset_id}/thumb?size=1024")[2])
        got = report("  うち 8 枚ぶんの 1024 サムネイル配信（1 枚ずつ）", thumbs)
        say(f"  → 画面 1 回ぶんの見積り（**文書の p50 ＋ 8 枚の p50**）= "
            f"{statistics.median(samples):.1f} + 8 × {got['p50']:.1f} = "
            f"{statistics.median(samples) + 8 * got['p50']:.0f} ms")
    finally:
        cli.close()


# ---- 4. 走査 ----


def probe_scan(out: Path, synth: Path) -> None:
    say("\n4. 走査（1 万枚。目標: 初回 90 秒以内 / 2 回目以降（差分なし）10 秒以内）")
    images = synth / "images"
    files = sorted(images.rglob("*.png"))
    total_bytes = sum(f.stat().st_size for f in files)
    say(f"  入力: {len(files)} 枚 / {total_bytes / 1e6:.1f} MB"
        f"（**96x96 が大半**＝ハッシュの費用は本物よりずっと安い。下の注記を見る）")

    from image_reviewer import scan as scan_mod
    from image_reviewer.store import Store

    # (a) 2 回目以降（差分なし）— 合成 DB は作るときに 1 回走査してある
    work = out / "w" / "scan2"
    if work.exists():
        shutil.rmtree(work)
    work.mkdir(parents=True)
    store = Store(work)
    try:
        t0 = time.perf_counter()
        stats = scan_mod.scan(store, [str(images)])          # 1 回目（この複製では初）
        first = time.perf_counter() - t0
        say(f"  初回（この空の DB へ登録）: {first:.1f} 秒 / created={stats['created']}"
            f" known={stats['known']} images={stats['images']}")
        for i in (1, 2, 3):
            t0 = time.perf_counter()
            stats = scan_mod.scan(store, [str(images)])
            sec = time.perf_counter() - t0
            report(f"2 回目以降の走査（差分なし・{i} 回目）", [sec * 1000], 10_000.0,
                   note=f"known={stats['known']} created={stats['created']}"
                        f" missing={stats['missing']}")
    finally:
        store.close()
    shutil.rmtree(work, ignore_errors=True)

    # 本物の 1 万枚（1.11 MB/枚）への見積り
    say("  見積り（**比例**。§12.1 の言い方に合わせる）: 1 万枚 = 11.1 GB")
    say(f"    ハッシュは実測 399 MB/s（P1 の実測）→ 11.1 GB = {11.1e9 / 399e6:.0f} 秒")
    say(f"    歩査＋解析＋登録は**上の初回走査から、ハッシュぶんを引いた物**"
        f"（この合成は 20.3 MB なのでハッシュはほぼ 0）")


# ---- 5. 一括削除の再照合 ----


def probe_delete(out: Path, synth: Path) -> None:
    say("\n5. 一括削除の再照合（§12.3。目標 1,000 件で 1 秒以内＝`os.stat` 1 回/件）")
    work = out / "w" / "delete"
    if work.exists():
        shutil.rmtree(work)
    backup_db(synth / "db.sqlite3", work)
    cli = Client(work, out / "backups")
    try:
        # 1,000 件の凍結（preview）を作る。**書き込みの口**なので人として投げる。
        # **`assets` で 1,000 枚を名指しする**（件数を決め打ちにするため）
        want_ids = ids_of(synth, limit=1000)
        res = cli.client.post("/api/locations/bulk-delete/preview",
                              json={"stage": 1, "scope": {"kind": "assets",
                                                          "asset_ids": want_ids}},
                              headers={"Host": "127.0.0.1", "Content-Type": "application/json",
                                       "X-Image-Reviewer-Actor": "human"})
        got = res.json()
        say(f"  preview: HTTP {res.status_code} / 件数 = {got.get('count')}"
            f" / preview_id = {got.get('preview_id')}")
        if res.status_code != 200 or not got.get("preview_id"):
            say(f"  **preview を作れなかった**ので、この計測は飛ばす: {got}")
            return
        items = got.get("items") or []
        say(f"  凍結した件数 = {len(items)}（目標の 1,000 件に合わせる）")
        want = min(1000, len(items))

        # 再照合だけの下限（`os.stat` 1 回/件。**口の外**）
        from image_reviewer.deletions import identity_of

        paths = [i["path"] for i in items[:want]]
        t0 = time.perf_counter()
        for p in paths:
            identity_of(p)
        floor = (time.perf_counter() - t0) * 1000
        report(f"再照合の下限: `identity_of()` × {want} 件（`os.stat` 1 回/件）", [floor],
               note="口の外。ここに台帳 1 行の書き込みが乗る")

        # 本体（**凍結した一覧を実行**＝再照合＋台帳 1 行）
        t0 = time.perf_counter()
        res2 = cli.client.post("/api/locations/bulk-delete",
                               json={"preview_id": got["preview_id"], "confirm": True},
                               headers={"Host": "127.0.0.1", "Content-Type": "application/json",
                                        "X-Image-Reviewer-Actor": "human"})
        sec = time.perf_counter() - t0
        body2 = res2.json()
        report(f"bulk-delete 段 1（再照合＋台帳 {want} 行。HTTP {res2.status_code}）", [sec * 1000],
               1000.0, note=f"deleted={body2.get('count')} skipped={len(body2.get('skipped') or [])}")
    finally:
        cli.close()


# ---- 6. 再リンクの nearby ----


def probe_relink(out: Path, synth: Path) -> None:
    say("\n6. 再リンクの `nearby`（1 万枚の置き場で同じ名前を探す。**未計測**だった物）")
    work = out / "w" / "relink"
    if work.exists():
        shutil.rmtree(work)
    backup_db(synth / "db.sqlite3", work)

    # 1 枚を「外へ出して」参照切れにする（**合成なので動かしてよい**）
    moved_dir = out / "w" / "relink-moved"
    if moved_dir.exists():
        shutil.rmtree(moved_dir)
    moved_dir.mkdir(parents=True)
    con = sqlite3.connect(work / "db.sqlite3")
    con.row_factory = sqlite3.Row
    try:
        row = con.execute(
            "SELECT l.path, l.display_path, l.asset_id, a.sha256 FROM asset_location l"
            " JOIN asset a ON a.id = l.asset_id WHERE a.width = 1024"
            " ORDER BY l.display_path LIMIT 1").fetchone()
        src = Path(row["display_path"])
        shutil.move(str(src), str(moved_dir / src.name))
        con.execute("UPDATE asset_location SET missing_at = ? WHERE path = ?",
                    ("2026-10-18T00:00:00Z", row["path"]))
        con.commit()
        say(f"  参照切れにした枚: {src.name}（1 万枚のうち 1 枚。**合成データ**）")
        asset_id = row["asset_id"]
    finally:
        con.close()

    from image_reviewer.relink import RelinkService
    from image_reviewer.review import ReviewError
    from image_reviewer.store import Store

    store = Store(work)
    try:
        service = RelinkService(store)

        def try_nearby(what: str, note: str = "") -> None:
            t0 = time.perf_counter()
            try:
                answer = service.relink(asset_id=asset_id, path=None, mode="nearby", actor="human")
                extra = (f"found={len(answer.get('also_found') or []) + 1}"
                         f" folders={len(answer.get('folders') or [])}"
                         f" searched={answer.get('searched')}"
                         f" found_in={answer.get('found_in')}")
            except ReviewError as exc:
                extra = f"見つからず {exc.status} {exc.code}（**全部歩いた**）"
            sec = time.perf_counter() - t0
            report(what, [sec * 1000], note=f"{extra} {note}".strip())

        # (a) 同じ名前が 1 つも無い（**1 万枚・20 フォルダを全部歩く最悪の場合**）
        try_nearby("nearby（同じ名前が無い＝**置き場を全部歩く**）")
        # (b) 置き場の中に在る（**1 段目で見つかる**）
        shutil.move(str(moved_dir / src.name), str(src))
        try_nearby("nearby（**置き場の中に在る**＝1 段目で見つかって止まる）")
    finally:
        store.close()
        # **動かしたファイルを必ず戻す**（例外で抜けても合成 DB の形を崩さない）
        src.parent.mkdir(parents=True, exist_ok=True)
        if (moved_dir / src.name).exists() and not src.exists():
            shutil.move(str(moved_dir / src.name), str(src))
    shutil.rmtree(work, ignore_errors=True)
    shutil.rmtree(moved_dir, ignore_errors=True)


def probe_real(out: Path, replica: Path, runs: int) -> None:
    """**実データの複製**で測る（455 枚。1 万枚と同じ物を小さい方でも見る）。

    実画像は 1.11 MB/枚 あるので、**サムネイルの生成はこちらが本物**である
    （合成の 1024x1024 は平らな絵なので復号が速すぎる。§2 の注記を見る）。
    **実データのファイルは読むだけ**（サムネイルは複製の中に書く）。
    """
    say("\n2b. 実データの複製（455 枚）で測る（**サムネイルの生成はこちらが本物**）")
    if not (replica / "db.sqlite3").is_file():
        say(f"  **複製が無い**ので飛ばす: {replica}（`--replica` で指す）")
        return
    cli = Client(replica, out / "backups")
    try:
        status, body, ms, nbytes = cli.get("/api/assets?limit=1000")
        say(f"  一覧（455 枚・limit=1000）: 1 回目 {ms:.1f} ms / total={body.get('total')}"
            f" / items={len(body.get('items') or [])} / 本文 {nbytes / 1024:.0f} KB")
        samples = []
        for _ in range(runs):
            samples.append(cli.get("/api/assets?limit=1000")[2])
        report("GET /api/assets?limit=1000（実データ 455 枚）", samples,
               note="§12.1 の目標は 1 万枚に対する物。**参考**")

        # 実体があって、まだサムネイルが無い枚を選ぶ
        from image_reviewer.thumbs import thumb_path

        con = sqlite3.connect(f"file:{(replica / 'db.sqlite3').as_posix()}?mode=ro", uri=True)
        con.row_factory = sqlite3.Row
        try:
            rows = con.execute(
                "SELECT a.id AS id, a.sha256 AS sha, l.display_path AS path"
                " FROM asset a JOIN asset_location l ON l.asset_id = a.id"
                " WHERE l.missing_at IS NULL AND a.deleted_at IS NULL AND a.width >= 1024"
                " ORDER BY l.display_path").fetchall()
        finally:
            con.close()
        picked = [r for r in rows if Path(r["path"]).is_file()][:24]
        say(f"  サムネイルを作る枚 = {len(picked)} 枚（実体があって 1024px 以上の物）")
        if not picked:
            return
        # **初回生成を測るために、複製の中のサムネイルを消す**（**実データの `.data/thumbs` は触らない**。
        # 消すのは `--replica` の下だけ）
        shutil.rmtree(replica / "thumbs", ignore_errors=True)
        say(f"  できているサムネイルを消した（**複製の中だけ**）: {replica / 'thumbs'}")
        for size in (1024, 256):
            missing = [r for r in picked if not thumb_path(replica, r["sha"], size).exists()]
            if not missing:
                say(f"  {size}px: **既に全部できている**ので、初回生成は測れない（この複製は前の計測の物）")
                continue
            samples, sizes = [], []
            for row in missing:
                status, _b, ms, nbytes = cli.get(f"/api/assets/{row['id']}/thumb?size={size}")
                assert status == 200, (row["id"], status)
                samples.append(ms)
                sizes.append(nbytes)
            report(f"**初回生成** {size}px（実画像）", samples,
                   note=f"{len(samples)} 枚の中央値 {statistics.median(samples):.0f} ms"
                        f" / 元 {statistics.median([Path(r['path']).stat().st_size for r in missing]) / 1e6:.2f} MB"
                        f" / 出力 {statistics.median(sizes) / 1024:.0f} KB")
            med = statistics.median(samples)
            say(f"    見積り（**比例**）: 1 万枚 = {med:.0f} ms/枚 → {med * 10000 / 1000 / 60:.1f} 分"
                f"（1 スレッド。§12.2 のスレッドプール min(8, cpu) なら ÷8）")

        # **「生成済み」はここで測る**（下の「同時 8 本」はサムネイルを消して作り直すので、
        # その後に測ると**また生成する**＝測っている物が変わる）
        samples = []
        for i in range(runs):
            samples.append(cli.get(f"/api/assets/{picked[i % len(picked)]['id']}/thumb?size=1024")[2])
        report("**生成済み** 1024px（実画像。`FileResponse`）", samples, 200.0)

        # (c) 8 本で並べたとき（§12.2 は「スレッドプール min(8, cpu_count)」）
        from concurrent.futures import ThreadPoolExecutor

        from image_reviewer import thumbs as thumbs_mod

        cpu = os.cpu_count() or 1
        workers = min(8, cpu)
        for size in (1024, 256):
            shutil.rmtree(replica / "thumbs", ignore_errors=True)
            t0 = time.perf_counter()
            with ThreadPoolExecutor(max_workers=workers) as pool:
                list(pool.map(lambda r: thumbs_mod.ensure_thumb(
                    r["path"], replica, r["sha"], size), picked))
            sec = time.perf_counter() - t0
            per = sec / len(picked) * 1000
            report(f"**同時 {workers} 本**で {size}px を作る（実画像 {len(picked)} 枚）",
                   [sec * 1000 / len(picked)], note=f"1 枚あたり {per:.0f} ms"
                        f"（cpu={cpu}）/ 1 万枚なら {per * 10000 / 1000 / 60:.1f} 分")

        # 比較の 8 枚（実データ）
        ids = [r["id"] for r in picked[:8]]
        for asset_id in ids:
            cli.get(f"/api/assets/{asset_id}/thumb?size=1024")
        samples = []
        for _ in range(runs):
            status, body, ms, _n = cli.get("/api/compare?ids=" + ",".join(ids))
            samples.append(ms)
            assert status == 200, body
        report("GET /api/compare?ids=（実データの 8 枚）", samples, 400.0)
    finally:
        cli.close()


# ---- 7. --include-library ----


def probe_library(out: Path, replica: Path) -> None:
    say("\n7. `--include-library`（日次バックアップに**画像の実体**も入れる。§12.3 の未計測）")
    if not (replica / "db.sqlite3").is_file():
        say(f"  **複製が無い**ので飛ばす: {replica}（`--replica` で実データの複製を指す）")
        return
    con = sqlite3.connect(f"file:{(replica / 'db.sqlite3').as_posix()}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    try:
        rows = con.execute(
            "SELECT a.sha256 AS sha256, l.display_path AS path"
            " FROM asset a JOIN asset_location l ON l.asset_id = a.id"
            " WHERE l.missing_at IS NULL AND a.deleted_at IS NULL"
            " ORDER BY a.sha256").fetchall()
    finally:
        con.close()
    seen, files, missing = set(), 0, 0
    total = 0
    for row in rows:
        if row["sha256"] in seen:
            continue
        seen.add(row["sha256"])
        p = Path(row["path"])
        if p.is_file():
            files += 1
            total += p.stat().st_size
        else:
            missing += 1
    say(f"  対象: 生きた場所 {len(rows)} 行 → 重複を畳んで {len(seen)} 枚 / 実体がある {files} 枚"
        f" / 実体が無い {missing} 枚 / 合計 {total / 1e6:.1f} MB（{total / 2**20:.0f} MiB）")

    from image_reviewer.backup import BackupService
    from image_reviewer.store import Store

    # 前の計測の世代を消してから測る（**292 MB の写しが積み上がらない**ように）
    shutil.rmtree(out / "backups-library", ignore_errors=True)
    store = Store(replica)
    try:
        service = BackupService(store, backup_dir=out / "backups-library")
        # (a) 画像なし（日次の既定）
        t0 = time.perf_counter()
        a = service.snapshot(manual=True)
        sec_a = time.perf_counter() - t0
        report("バックアップ（**画像なし**。DB ＋ sidecar ＋ export）", [sec_a * 1000], 5000.0,
               note=f"{a['files']['files']} ファイル / {a['files']['bytes'] / 1e6:.1f} MB"
                    f" / DB {a['db_bytes'] / 1e6:.1f} MB")
        # (b) 画像あり
        t0 = time.perf_counter()
        b = service.snapshot(manual=True, include_library=True)
        sec_b = time.perf_counter() - t0
        report("バックアップ（**--include-library**）", [sec_b * 1000], 5000.0,
               note=f"library {b['library']['files']} 枚 / {b['library']['bytes'] / 1e6:.1f} MB"
                    f" / 全体 {(b['files']['bytes'] + b['library']['bytes']) / 1e6:.1f} MB"
                    f" / missing {b['library']['missing']}")
        if b["library"]["errors"]:
            say(f"  エラー {len(b['library']['errors'])} 件（先頭）: {b['library']['errors'][0]}")
        extra = max(sec_b - sec_a, 1e-9)
        rate = b["library"]["bytes"] / extra / 1e6
        say(f"  見積り（**比例**）: 画像ぶん {extra:.2f} 秒 / {b['library']['bytes'] / 1e6:.0f} MB"
            f" → {rate:.0f} MB/s（1 万枚 11.1 GB なら {11.1e9 / (rate * 1e6) / 60:.1f} 分）")
        say(f"  世代: {[p.name for p in sorted((out / 'backups-library').iterdir())]}")
    finally:
        store.close()


# ---- main ----


def main() -> int:
    ap = argparse.ArgumentParser(description="P9 の性能の計測（§12.1 の目標を実測で埋める）")
    ap.add_argument("--out", default=str(ROOT / ".tmp-audit-redo" / "p9"))
    ap.add_argument("--synth", default=None, help="合成 DB の置き場（既定 <out>/synth10k）")
    ap.add_argument("--replica", default=None, help="実データの複製（--include-library の計測用）")
    ap.add_argument("--synth-count", type=int, default=10000)
    ap.add_argument("--rebuild-synth", action="store_true", help="合成 DB を作り直す")
    ap.add_argument("--runs", type=int, default=50, help="p95 を出す回数")
    ap.add_argument("--keep", action="store_true", help="使い捨ての複製を残す")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--thumbs", action="store_true")
    ap.add_argument("--compare", action="store_true")
    ap.add_argument("--decide", action="store_true", help="判断の記録（§12.1 の未計測）")
    ap.add_argument("--scan", action="store_true")
    ap.add_argument("--delete", action="store_true")
    ap.add_argument("--relink", action="store_true")
    ap.add_argument("--library", action="store_true")
    ap.add_argument("--real", action="store_true", help="実データの複製で測る（455 枚）")
    ap.add_argument("--all", action="store_true")
    args = ap.parse_args()

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    synth = Path(args.synth) if args.synth else out / "synth10k"

    wanted = {k: getattr(args, k) or args.all
              for k in ("list", "thumbs", "compare", "decide", "scan", "delete", "relink",
                        "library", "real")}
    if not any(wanted.values()):
        wanted = {k: True for k in wanted}                    # 既定は全部

    if args.rebuild_synth or not (synth / "db.sqlite3").is_file():
        if any(wanted[k] for k in ("list", "thumbs", "compare", "scan", "delete", "relink")):
            say(f"合成 DB を作る: {synth}")
            cmd = [sys.executable, "-X", "utf8", str(ROOT / "tools" / "make_synthetic_db.py"),
                   "--out", str(synth), "--count", str(args.synth_count)]
            import subprocess

            subprocess.run(cmd, check=True, cwd=str(ROOT))

    started = time.time()
    if wanted["list"]:
        probe_list(out, synth, args.runs)
    if wanted["thumbs"]:
        probe_thumbs(out, synth, args.runs)
    if wanted["compare"]:
        probe_compare(out, synth, args.runs)
    if wanted["decide"]:
        probe_decide(out, synth, args.runs)
    if wanted["scan"]:
        probe_scan(out, synth)
    if wanted["delete"]:
        probe_delete(out, synth)
    if wanted["relink"]:
        probe_relink(out, synth)
    if wanted["library"]:
        probe_library(out, Path(args.replica) if args.replica else out / "real")
    if wanted["real"]:
        probe_real(out, Path(args.replica) if args.replica else out / "real", args.runs)

    if not args.keep:
        shutil.rmtree(out / "w", ignore_errors=True)
        say(f"\n使い捨て（{out / 'w'}）を消した（残すなら --keep）")

    say(f"\n{'=' * 74}\n所要 {time.time() - started:.0f} 秒")
    if FAILURES:
        say("目標に届かなかった物:")
        for line in FAILURES:
            say(f"  - {line}")
    say("まとめ: " + ("すべて目標の内側" if OK else f"目標に届かない物が {len(FAILURES)} 件（上を見る）"))
    return 0 if OK else 1


if __name__ == "__main__":
    raise SystemExit(main())
