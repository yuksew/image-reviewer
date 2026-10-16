"""P7 の実測（設計 §1.2 の線 2 など）。

- `--judge`: **実データの複製**（`sqlite3` の `backup()` で WAL を畳む）を作り、**263 枚すべてに記録**を付けて
  `{exact, approx, impossible}` の数と**理由の内訳**、**鍵の計算時間**を出す。
  期待値（この環境・この版。設計 §0.6・点検 A-3）: **`exact` 183 / `approx` 0 / `impossible` 80**。
- `--http`: 複製にサーバを立てて、**口から**何枚か記録する（`POST /api/assets/{id}/recipe` が通ること）。
- **実データ `.data` は読むだけ**（`mode=ro`）。書き込むのは複製にだけ。
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sqlite3
import statistics
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

REAL = ROOT / ".data"
SCRATCH = ROOT / ".tmp-audit-redo" / "p7" / "judge"

OK = True


def say(*parts) -> None:
    print(*parts, flush=True)


def copy_real(dest: Path) -> Path:
    """**実データの複製**（`backup()` で WAL を畳む。ファイルをコピーするだけでは判断が落ちる）。"""
    dest.mkdir(parents=True, exist_ok=True)
    src = sqlite3.connect(f"file:{(REAL / 'db.sqlite3').as_posix()}?mode=ro", uri=True)
    dst = sqlite3.connect(str(dest / "db.sqlite3"))
    with dst:
        src.backup(dst)
    dst.close()
    src.close()
    return dest


def judge(data: Path, limit: int, *, fresh: bool) -> dict:
    """263 枚に記録を付けて数える（**同じコードを通す**＝`RecipeService.record`）。"""
    from image_reviewer.recipe import ComfyProbe, RecipeService
    from image_reviewer.store import Store

    store = Store(data)
    # **probe を使い回す**（1 枚ごとに作ると `/object_info/{class_type}` を何千回も引く）。
    # 口（API）は 1 回ごとに作るが、実測では同じ結果になる（宣言は変わらない）
    probe = ComfyProbe("http://127.0.0.1:8188")
    svc = RecipeService(store, probe_factory=lambda settings: probe)
    try:
        if fresh:
            with store.transaction() as con:
                con.execute("DELETE FROM recipe_record")
        ids = [r["id"] for r in store.con.execute("SELECT id FROM asset ORDER BY id")]
        if limit:
            ids = ids[:limit]
        counts: dict[str, int] = {"exact": 0, "approx": 0, "impossible": 0}
        reasons: dict[str, int] = {}
        kinds: dict[str, set] = {}
        times: list[float] = []
        graphs = 0
        for asset_id in ids:
            t0 = time.perf_counter()
            got = svc.record(asset_id, mode="pin_text", actor="human")
            times.append((time.perf_counter() - t0) * 1000)
            counts[got["status"]] = counts.get(got["status"], 0) + 1
            if got.get("graph_path"):
                graphs += 1
            for kind in got["reasons"]:
                reasons[kind] = reasons.get(kind, 0) + 1
                kinds.setdefault(kind, set())
                if len(kinds[kind]) < 3:
                    kinds[kind].add(asset_id)
        return {"n": len(ids), "counts": counts, "reasons": reasons, "kinds": kinds,
                "graphs": graphs, "times": times,
                "rows": store.con.execute("SELECT count(*) AS n FROM recipe_record").fetchone()["n"]}
    finally:
        store.close()


def http_check(data: Path, base: str, take: int = 5) -> dict:
    """**口から**記録して、`GET` が読めることを確かめる（5 枚）。"""

    def call(method: str, path: str, body=None, actor="human"):
        req = urllib.request.Request(
            base + path, method=method,
            data=None if body is None else json.dumps(body).encode(),
            headers={"Content-Type": "application/json",
                     "X-Image-Reviewer-Actor": actor})
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                return r.status, json.loads(r.read() or b"{}")
        except urllib.error.HTTPError as exc:
            return exc.code, json.loads(exc.read() or b"{}")

    ids = [r[0] for r in sqlite3.connect(str(data / "db.sqlite3")).execute(
        "SELECT id FROM asset ORDER BY id LIMIT ?", (take,))]
    out = []
    for asset_id in ids:
        code, got = call("POST", f"/api/assets/{asset_id}/recipe", {"mode": "pin_text"})
        read = call("GET", f"/api/assets/{asset_id}/recipe")[0]
        out.append((asset_id, code, got.get("status"), read))
    return {"items": out}


def export_of(data: Path, *, keep: bool) -> dict:
    """**書き出し（P7-2）を実物で通す**（設計 §1.2 の線 3・4・5）。

    複製から**グラフを持つ 1 枚**を選び、記録してから **seed を 2 つ**指定して書き出す:
    - `seed-<1>.json` / `seed-<2>.json` / `manifest.json` の **3 ファイル**
    - **印**（`SaveImage.filename_prefix` が `repro-<attempt_id>/seed-<seed>` に変わり、
      **鍵（`recipe_hash`）は変わらない**）
    - **manifest が契約（本物の `jsonschema`）を通る**
    """
    import json
    from pathlib import Path as _Path

    from image_reviewer.recipe import RecipeService
    from image_reviewer.recipe_export import RecipeExportService
    from image_reviewer.review import ReviewError
    from image_reviewer.store import Store

    store = Store(data)
    recipes = RecipeService(store)
    exports = RecipeExportService(store, recipes)
    try:
        # **保存ノードのある本物のグラフ**を持つ記録を選ぶ（契約の検査が入れた見本の行
        # `rec1` のような、グラフのファイルが無い物は飛ばす）
        with store.locked() as con:
            rows = [dict(r) for r in con.execute(
                "SELECT id, source_asset_id FROM recipe_record ORDER BY created_at LIMIT 50")]
        recipe_id = None
        for row in rows:
            _record, graph = exports._load(row["id"])
            if graph and any(str(n.get("class_type")) in ("SaveImage", "PreviewImage")
                             for n in graph.values() if isinstance(n, dict)):
                recipe_id = row["id"]
                break
        if recipe_id is None:
            # 無ければ、グラフを持つ 1 枚に記録を作る
            with store.locked() as con:
                asset = con.execute("SELECT id FROM asset ORDER BY id").fetchone()
            if asset is None:
                return {"ok": False, "why": "画像がありません"}
            recipe_id = recipes.record(asset["id"], mode="pin_text", actor="human")["recipe_id"]
        before = recipes.get(_recipe_asset(store, recipe_id))["recipe_hash"]
        # **`KSampler` の無いグラフ**（upscale など。実データに 3 枚）は seed を指定できない
        # （422 `no_sampler`）。そのときは seed 無しで 1 ファイル（印は `…/noseed`）に落とす
        try:
            got = exports.export(recipe_id, seeds=["1", "2"], actor="human")
            noseed = False
        except ReviewError as exc:
            if exc.status != 422 or exc.code != "no_sampler":
                raise
            got = exports.export(recipe_id, actor="human")
            noseed = True
        after = recipes.get(_recipe_asset(store, recipe_id))["recipe_hash"]
        out = _Path(got["export_dir"])
        names = sorted(p.name for p in out.iterdir())
        first = "seed-noseed.json" if noseed else "seed-1.json"
        marked = json.loads((out / first).read_text(encoding="utf-8"))
        prefix = next((n["inputs"].get("filename_prefix") for n in marked.values()
                       if isinstance(n, dict) and n.get("class_type") == "SaveImage"), None)
        manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
        want = (["manifest.json", "seed-noseed.json"] if noseed
                else ["manifest.json", "seed-1.json", "seed-2.json"])
        return {"ok": names == want and prefix == got["marker"] and before == after,
                "noseed": noseed,
                "recipe_id": recipe_id, "attempt_id": got["attempt_id"], "dir": str(out),
                "names": names, "marker": got["marker"], "marker_skipped": got["marker_skipped"],
                "prefix_in_graph": prefix, "hash_before": before, "hash_after": after,
                "seed_node": got["seed_node"], "reasons": got["reasons"],
                "manifest_hashes": sorted(manifest.get("export_hashes", {})),
                "manifest_path": str(out / "manifest.json")}
    finally:
        store.close()


def _recipe_asset(store, recipe_id: str) -> str:
    with store.locked() as con:
        return con.execute("SELECT source_asset_id FROM recipe_record WHERE id = ?",
                           (recipe_id,)).fetchone()["source_asset_id"]


def main() -> int:
    global OK
    parser = argparse.ArgumentParser(description="P7 の実測")
    parser.add_argument("--judge", action="store_true", help="複製で 263 枚に記録を付けて数える")
    parser.add_argument("--export", action="store_true",
                        help="複製の 1 枚から seed 2 つを書き出す（P7-2 の線 3・4・5）")
    parser.add_argument("--http", action="store_true", help="複製にサーバを立てて口から確かめる")
    parser.add_argument("--data", default=None, help="複製の置き場（既定は .tmp-audit-redo/p7/judge/data）")
    parser.add_argument("--limit", type=int, default=0, help="枚数を絞る（既定は全部）")
    parser.add_argument("--port", type=int, default=8793)
    parser.add_argument("--fresh", action="store_true", help="既存の記録を消してやり直す")
    parser.add_argument("--keep", action="store_true", help="複製を残す")
    args = parser.parse_args()

    data = Path(args.data) if args.data else SCRATCH / "data"
    if not (data / "db.sqlite3").exists():
        say(f"複製を作る: {data}")
        copy_real(data)
    else:
        say(f"既にある複製を使う: {data}")

    if args.judge:
        say("\n=== 線 2: 263 枚に判定が付く（§0.6）===")
        got = judge(data, args.limit, fresh=args.fresh)
        say(f"  対象 {got['n']} 枚 / 記録の行 {got['rows']} / グラフを書いた {got['graphs']} 枚")
        counts = got["counts"]
        say(f"  exact {counts.get('exact', 0)} / approx {counts.get('approx', 0)}"
            f" / impossible {counts.get('impossible', 0)}")
        if got["reasons"]:
            say("  理由の内訳:")
            for kind, n in sorted(got["reasons"].items(), key=lambda kv: -kv[1]):
                say(f"    {kind}: {n}")
        if got["times"]:
            say(f"  1 枚あたり: 中央 {statistics.median(got['times']):.1f} ms"
                f" / 平均 {statistics.fmean(got['times']):.1f} ms"
                f" / 最悪 {max(got['times']):.1f} ms（宣言の取得込み）")
        if args.limit == 0:
            # **期待値との突き合わせ**（実測で確定。設計 §0.6 の「183 / 0 / 80」とは 1 枚違う）
            # - `impossible` 80 = **グラフの無い画像**（JPEG など。`missing`）
            # - `approx` 1 = **ja2en の 1 枚**。`CLIPTextEncode` はあるが**文字列が分からない**
            #   （`StringConcatenate` → `TextGenerate` のリンク参照）ので `text_not_captured`。
            #   **これは正しい**（英訳は PNG に残らない＝記録の存在理由そのもの。§0.9 の監視で捕まえる）
            # - `exact` 182 = 残り。**`final_prompt` が `None` でも `CLIPTextEncode` を持たない
            #   upscale の 3 枚は `exact`**（テキストを使わないグラフは「欠けていない」。§0.6）
            want = {"exact": 182, "approx": 1, "impossible": 80}
            if counts == want:
                say(f"  OK: 期待どおり（{want}）")
            else:
                OK = False
                say(f"  NG: 期待 {want} と違う。理由の内訳を見ること")

    if args.export:
        say("\n=== 書き出し（P7-2。複製から 1 枚）===")
        if not (data / "db.sqlite3").exists():
            copy_real(data)
            say(f"  複製を作った: {data}")
        got = export_of(data, keep=args.keep)
        if not got.get("ok"):
            OK = False
        say(f"  レシピ {got.get('recipe_id')} → 束 {got.get('attempt_id')}")
        say(f"  置き場: {got.get('dir')}")
        say(f"  ファイル: {got.get('names')}")
        say(f"  印: {got.get('marker')}（グラフの中: {got.get('prefix_in_graph')}）"
            f" / 印を省いた理由: {got.get('marker_skipped')}")
        say(f"  鍵: 書き出しの前 {got.get('hash_before')} / 後 {got.get('hash_after')}"
            f"（**同じなら印で鍵が変わっていない**）")
        say(f"  seed ノード: {got.get('seed_node')} / 理由: {got.get('reasons')}")
        say(f"  manifest の export_hashes: {got.get('manifest_hashes')}")
        say(f"  manifest: {got.get('manifest_path')}"
            "（`uv run --with jsonschema python tools/check_contract_p7.py` が拾って検証する）")

    if args.http:
        say("\n=== 口から（5 枚）===")
        env = {**os.environ, "UV_CACHE_DIR": str(ROOT / ".uv-cache"),
               "IMAGE_REVIEWER_DATA": str(data)}
        proc = subprocess.Popen([sys.executable, "-m", "uvicorn", "image_reviewer.app:app",
                                 "--host", "127.0.0.1", "--port", str(args.port),
                                 "--log-level", "warning"],
                                cwd=str(ROOT), env=env,
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        base = f"http://127.0.0.1:{args.port}"
        try:
            for _ in range(40):
                time.sleep(0.5)
                try:
                    urllib.request.urlopen(base + "/api/health", timeout=3)
                    break
                except Exception:                     # noqa: BLE001
                    pass
            got = http_check(data, base)
            for asset_id, code, status, read in got["items"]:
                say(f"  {asset_id}: POST {code} status={status} / GET {read}")
                if code not in (200, 201) or read != 200:
                    OK = False
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=15)
            except Exception:                         # noqa: BLE001
                proc.kill()
            time.sleep(1)

    if not args.keep and data == SCRATCH / "data":
        shutil.rmtree(data, ignore_errors=True)
        say(f"\n複製を消した（残すなら --keep）: {data}")
    say("\nまとめ: " + ("すべて OK" if OK else "NG あり"))
    return 0 if OK else 1


if __name__ == "__main__":
    raise SystemExit(main())
