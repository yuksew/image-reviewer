"""P6-1a の HTTP 計測（設計 p6-design.md §1.2 の 1 と §7 の表）。

測るもの:
1. `GET /api/review-requests?state=open`（1,000 件）→ **p95 20 ms 以内**（`ix_request_state`）
2. `GET /api/review-requests?count_only=1` / `GET /api/review-requests/{id}` / `?target_key=`
3. `POST /api/review-requests`（8 枚）を 30 回 → **p95 150 ms 以内**、30/30 が `state: "open"`
4. 参考: **書き出しと重なったとき**の一覧（`ExportService` は `store` の錠を握って
   まとまりのファイルを書くので、混ざると待たされる。P5 からの性質で、P6-1a の欠陥ではない）

**本物の HTTP**（uvicorn を別プロセスで立て、`urllib` で叩く）で測る。データは捨てる場所
（既定 `.tmp-p6-1a/data`）に作り、`.data` には触らない。

1,000 件はサーバを立てる**前に**、書き出しを伴わない service（`exporter=None`）で作る
（POST で作ると 1,000 個のまとまりが「書き出し待ち」になり、一覧の計測が書き出しと混ざる）。

使い方: uv run python tools/probe_p6_1a.py [--port 8797] [--total 1000] [--runs 30]
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import statistics
import subprocess
import sys
import time
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from image_reviewer.review import ReviewService                 # noqa: E402
from image_reviewer.review_requests import ReviewRequestService  # noqa: E402
from image_reviewer.store import Store                          # noqa: E402

BASE = os.path.join(ROOT, ".tmp-p6-1a")
OK = True
KEEPALIVE = True                 # 既定は keep-alive（接続を作り直す費用を測り込まない）
_CLIENT = None


def _call_urllib(method: str, url: str, body: dict | None = None,
                 headers: dict | None = None) -> tuple[int, dict, float]:
    """1 回叩いて (status, body, ミリ秒)。**毎回接続を作る**（`--fresh` のとき）。"""
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    if data is not None:
        req.add_header("Content-Type", "application/json")
    for key, value in (headers or {}).items():
        req.add_header(key, value)
    start = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=120) as res:
            raw, status = res.read(), res.status
    except urllib.error.HTTPError as exc:               # 4xx も中身を見たい
        raw, status = exc.read(), exc.code
    ms = (time.perf_counter() - start) * 1000
    try:
        got = json.loads(raw.decode("utf-8"))
    except ValueError:
        got = {"raw": raw[:200].decode("utf-8", "replace")}
    return status, got, ms


def call(method: str, url: str, body: dict | None = None,
         headers: dict | None = None) -> tuple[int, dict, float]:
    """1 回叩いて (status, body, ミリ秒)。

    既定は **keep-alive**（`httpx.Client`）。Windows では 127.0.0.1 でも接続ごとに
    検査が入るようで、毎回つなぎ直すと 20 ms 前後の裾が混ざる（測っているものが
    「HTTP の応答」から「接続の設立」に変わる）。`--fresh` で毎回つなぎ直す測り方も選べる。
    """
    global _CLIENT
    if not KEEPALIVE:
        return _call_urllib(method, url, body, headers)
    if _CLIENT is None:
        import httpx
        _CLIENT = httpx.Client(timeout=120.0)
    start = time.perf_counter()
    res = _CLIENT.request(method, url, json=body, headers=headers)
    ms = (time.perf_counter() - start) * 1000
    try:
        got = res.json()
    except ValueError:
        got = {"raw": res.text[:200]}
    return res.status_code, got, ms


def at(ordered: list[float], q: float) -> float:
    return ordered[min(len(ordered) - 1, int(round(q * (len(ordered) - 1))))]


def show(title: str, samples: list[float], limit_ms: float | None = None) -> None:
    global OK
    if not KEEPALIVE and limit_ms is not None:
        # `--fresh` は「HTTP の応答」ではなく「接続の設立込み」を測っている。§1.2 の線は
        # 応答に対するものなので、この測定方法では線を設けない（参考値として出す）
        limit_ms = None
    ordered = sorted(samples)
    line = (f"  {title}: n={len(ordered)} min={ordered[0]:.1f} p50={at(ordered, .5):.1f}"
            f" p95={at(ordered, .95):.1f} max={ordered[-1]:.1f}"
            f" mean={statistics.fmean(ordered):.1f} ms")
    if limit_ms is None:
        print(line + "  （参考。線は設けない）")
        return
    ok = at(ordered, 0.95) <= limit_ms
    OK = OK and ok
    print(line + f"  -> {'OK' if ok else 'NG'}（線 {limit_ms:.0f} ms）")


def wait_health(base: str, timeout: float = 60.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            if call("GET", base + "/api/health")[0] == 200:
                return
        except Exception:            # noqa: BLE001  まだ立っていない（接続を拒否された）
            pass
        time.sleep(0.2)
    raise SystemExit("サーバが起動しませんでした（/api/health が 200 にならない）")


def seed(data: str, total: int) -> list[str]:
    """8 枚と `total` 件の要求を作る（**書き出しを伴わない** service で。サーバを立てる前に）。"""
    store = Store(data)
    try:
        review = ReviewService(store, reconcile_on_start=False)     # exporter=None
        requests = ReviewRequestService(store, review)
        asset_ids = []
        for i in range(8):
            asset_id, _ = store.register(
                sha256=f"{i:02d}" * 32, path=os.path.join(data, "images", f"img{i}.png"),
                size=100, mtime_ns=1, width=16, height=16, fmt="png", meta=None, note=None)
            asset_ids.append(asset_id)
        for i in range(total):
            requests.create(asset_ids=asset_ids[:2], ask=f"一覧の計測用 {i}",
                            conditions=["左手の形"], origin="計測")
        return asset_ids
    finally:
        store.close()


def main() -> int:
    global OK

    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8797)
    ap.add_argument("--total", type=int, default=1000, help="一覧の計測に使う要求の数")
    ap.add_argument("--runs", type=int, default=30, help="POST を投げる回数")
    ap.add_argument("--busy", type=int, default=200, help="混雑を作る POST の数")
    ap.add_argument("--fresh", action="store_true", help="毎回つなぎ直して測る（裾の比較用）")
    ap.add_argument("--keep", action="store_true",
                    help="使い捨てのデータ（.tmp-p6-1a。既定 90 MB 前後）を残す（既定は削除）")
    args = ap.parse_args()

    global KEEPALIVE
    KEEPALIVE = not args.fresh
    print(f"測り方: {'keep-alive' if KEEPALIVE else '毎回つなぎ直す（--fresh）'}")

    data = os.path.join(BASE, "data")
    if os.path.exists(data):
        shutil.rmtree(data)
    os.makedirs(data, exist_ok=True)

    asset_ids = seed(data, args.total)
    print(f"8 枚 + {args.total} 件を用意した（data={data}）")

    env = {**os.environ, "IMAGE_REVIEWER_DATA": data, "PYTHONUNBUFFERED": "1"}
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "image_reviewer.app:app",
         "--host", "127.0.0.1", "--port", str(args.port), "--log-level", "warning"],
        cwd=ROOT, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    base = f"http://127.0.0.1:{args.port}"
    try:
        wait_health(base)
        print(f"uvicorn を立てた（pid={proc.pid}, {base}）。起動時に書き出しは済んでいる\n")

        # ---- 1. 一覧（1,000 件）----
        print(f"1. 一覧（open {args.total} 件。p95 20 ms 以内）")
        samples, got = [], {}
        for _ in range(30):
            status, got, ms = call("GET", base + "/api/review-requests?state=open")
            assert status == 200, got
            samples.append(ms)
        show("GET ?state=open（既定 limit=50）", samples, 20.0)
        print(f"  counts.open = {got['counts']['open']} / items = {len(got['items'])}"
              f" / 先頭の形 = {sorted(got['items'][0])[:6]}…")
        OK = OK and got["counts"]["open"] >= args.total and len(got["items"]) == 50

        samples = []
        for _ in range(30):
            samples.append(call("GET", base + "/api/review-requests?count_only=1")[2])
        show("GET ?count_only=1", samples, 20.0)

        samples = []
        for _ in range(30):
            _s, one_200, ms = call("GET", base + "/api/review-requests?limit=200")
            samples.append(ms)
        # §1.2 の線は既定（limit=50）に対するもの。200 件は**参考**（1 件あたり約 0.1 ms）
        show("GET ?state=open&limit=200（200 件を組む）", samples)
        print(f"  items = {len(one_200['items'])}")

        # ---- 2. 取得と絞り込み ----
        print("\n2. 取得（§3.4）と `target_key`（点検 C1）")
        request_id = got["items"][0]["id"]
        samples = []
        for _ in range(30):
            _s, one, ms = call("GET", f"{base}/api/review-requests/{request_id}")
            samples.append(ms)
        show("GET /{id}", samples, 20.0)
        print(f"  state = {one['state']} / response = {one['response']} / ai = {one['ai']}")
        _s, keyed, ms = call("POST", base + "/api/review-requests",
                             {"asset_ids": asset_ids[:1], "ask": "鍵つき",
                              "target_key": "cut-20261011-031201"})
        _s, got_key, ms = call("GET",
                               base + "/api/review-requests?target_key=cut-20261011-031201")
        print(f"  GET ?target_key=... -> items = {len(got_key['items'])}（{ms:.1f} ms）"
              f" / target_key = {got_key['items'][0]['target_key'] if got_key['items'] else None}")
        OK = OK and len(got_key["items"]) == 1

        # ---- 3. POST（8 枚）を 30 回。**投げてすぐ返る**（§1.2 の 1）----
        print(f"\n3. POST /api/review-requests（8 枚 × {args.runs} 回。p95 150 ms 以内）")
        samples, states, statuses = [], [], []
        for i in range(args.runs):
            status, one, ms = call("POST", base + "/api/review-requests",
                                   {"asset_ids": asset_ids, "ask": f"{i} 回目の要求",
                                    "conditions": ["左手の形", "背景の窓の位置"],
                                    "origin": "作品A / カット03",
                                    "wants": ["selected_ids", "reason", "annotations"],
                                    "ai_pick_asset_id": asset_ids[0],
                                    "ai_note": "手が素直で窓の位置も合っている"})
            statuses.append(status)
            states.append(one.get("state"))
            samples.append(ms)
        show("POST（要求 1 行＋まとまり 1 行＋枚の行）", samples, 150.0)
        all_open, all_201 = all(s == "open" for s in states), all(s == 201 for s in statuses)
        print(f"  {args.runs}/{args.runs} が state='open' = {all_open} / 201 = {all_201}")
        OK = OK and all_open and all_201

        # ---- 4. 参考: 書き出しと重なったときの一覧 ----
        print(f"\n4. 参考: 書き出しと重なったとき（POST {args.busy} 回の直後。"
              "`ExportService` は錠を握ってファイルを書く）")
        for _ in range(args.busy):
            call("POST", base + "/api/review-requests",
                 {"asset_ids": asset_ids[:1], "ask": "混雑用"})
        time.sleep(2.0)                       # 遅延 2 秒の書き出しが始まる時刻に合わせる
        samples = []
        for _ in range(30):
            samples.append(call("GET", base + "/api/review-requests?state=open")[2])
        show("GET ?state=open（書き出し中）", samples)
        dirty_left = os.path.exists(os.path.join(data, "export"))
        print(f"  export ディレクトリ = {dirty_left}（混雑の再現に使うだけで、合否には使わない）")

        # ---- 5. 守り（Host / Content-Type）----
        print("\n5. 守り（middleware）")
        code = call("POST", base + "/api/review-requests", {}, {"Host": "evil.example"})[0]
        print(f"  Host: evil.example -> {code}（403 が正）")
        OK = OK and code == 403
        code = call("POST", base + "/api/review-requests", {}, {"Content-Type": "text/plain"})[0]
        print(f"  Content-Type: text/plain -> {code}（403 が正）")
        OK = OK and code == 403
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=15)
        except subprocess.TimeoutExpired:
            proc.kill()
        # P6-1a の監査: 使い捨てのデータ（既定 90 MB 前後）を残さない。`--keep` で残せる
        if not args.keep:
            shutil.rmtree(BASE, ignore_errors=True)

    print("\n" + "=" * 74)
    print("まとめ: " + ("すべて OK" if OK else "NG あり（上の -> NG を見る）"))
    return 0 if OK else 1


if __name__ == "__main__":
    raise SystemExit(main())
