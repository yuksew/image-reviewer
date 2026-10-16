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


def watch_of(data: Path, *, port: int = 8794, keep: bool = False) -> dict:
    """**線 6（合格の門）を実物で通す**（P7-3）。

    **偽の ComfyUI**（`/api/jobs` と `/api/jobs/{id}` を返す小さな HTTP サーバ）を立て、
    **印つきの出力を持つ job** を 1 つ流す。監視が拾って `recipe_export_result` が
    `matched_by='marker'` で 1 行できること、**その `outputs` が指す実ファイル**
    （合成 PNG。`prompt` に**書き出したグラフ**を入れる）を `comfyui.output_dir` に置いて
    **登録・鍵・指標・`seed_changed` まで通す**ことを見る。**印の無い job では作られない**ことも見る。

    **本物の ComfyUI は使わない**（`POST` しない＝画像を生成しない）。
    """
    import json
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    from PIL import Image, PngImagePlugin

    from image_reviewer.recipe import RecipeService
    from image_reviewer.recipe_export import RecipeExportService
    from image_reviewer.store import Store
    from image_reviewer.watcher import ComfyWatcher

    out_dir = data.parent / "output"
    out_dir.mkdir(parents=True, exist_ok=True)
    store = Store(data)
    recipes = RecipeService(store)
    exports = RecipeExportService(store, recipes)
    with store.transaction() as con:               # **複製の上**。何度でも同じ結果にする
        con.execute("DELETE FROM recipe_export_result")

    # ---- ① グラフを持つ 1 枚に記録を作り、**印つきで書き出す** ----
    with store.locked() as con:
        asset = con.execute("SELECT id FROM asset ORDER BY id").fetchone()
        if asset is None:
            store.close()
            return {"ok": False, "why": "画像がありません"}
        graph_rows = con.execute("SELECT id, source_asset_id FROM recipe_record"
                                 " ORDER BY created_at LIMIT 50").fetchall()
    recipe_id = None
    for row in graph_rows:
        _record, graph = exports._load(row["id"])
        if graph and any(str(n.get("class_type")) in ("SaveImage", "PreviewImage")
                         for n in graph.values() if isinstance(n, dict)):
            recipe_id = row["id"]
            break
    if recipe_id is None:
        recipe_id = recipes.record(asset["id"], mode="pin_text", actor="human")["recipe_id"]
    got = exports.export(recipe_id, seeds=["7"], actor="human")
    attempt_id = got["attempt_id"]
    sub = f"repro-{attempt_id}"
    graph_path = Path(got["export_dir"]) / "seed-7.json"
    graph = json.loads(graph_path.read_text(encoding="utf-8"))
    exported_hash = recipes.get(_recipe_asset(store, recipe_id))["recipe_hash"]

    # ---- ② 出力先に合成の PNG を 2 枚置く（同じ seed / 違う seed） ----
    def put(name: str, seed: int) -> Path:
        body = json.loads(json.dumps(graph))
        for node in body.values():
            if isinstance(node, dict) and node.get("class_type") in ("KSampler", "KSamplerAdvanced"):
                node.setdefault("inputs", {})["seed"] = seed
                break
        path = out_dir / sub / name
        path.parent.mkdir(parents=True, exist_ok=True)
        im = Image.new("RGB", (48, 64), (30, 40, 50))
        info = PngImagePlugin.PngInfo()
        info.add_text("prompt", json.dumps(body))
        im.save(path, pnginfo=info)
        return path

    same_png = put("seed-7_00001_.png", 7)
    other_png = put("seed-7_00002_.png", 999)          # **seed を変えた物**（`seed_changed` 用）
    # **印なしの PNG はグラフにも印を入れない**（保険の照合＝PNG の `prompt` を見る規則があるため）
    plain = json.loads(json.dumps(graph))
    for node in plain.values():
        if isinstance(node, dict) and node.get("class_type") in ("SaveImage", "PreviewImage"):
            node.setdefault("inputs", {})["filename_prefix"] = "plain"
            break
    stray_png = out_dir / "other" / "no_marker_00001_.png"
    stray_png.parent.mkdir(parents=True, exist_ok=True)
    im = Image.new("RGB", (48, 64), (30, 40, 50))
    info = PngImagePlugin.PngInfo()
    info.add_text("prompt", json.dumps(plain))
    im.save(stray_png, pnginfo=info)

    # ---- ③ 偽の ComfyUI ----
    jobs: list[dict] = []
    details: dict[str, dict] = {}

    def add_job(job_id: str, images: list[dict], when: int) -> None:
        jobs.append({"id": job_id, "status": "completed", "create_time": when,
                     "outputs_count": len(images), "previewable_outputs_count": len(images)})
        details[job_id] = {"id": job_id, "workflow": {"prompt": graph},
                           "outputs": {"9": {"images": images}},
                           "execution_status": {"status_str": "success",
                                                "messages": [["execution_cached", {"nodes": []}]]}}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):                  # 静かにする
            pass

        def _json(self, body) -> None:
            raw = json.dumps(body).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def do_GET(self):                              # noqa: N802
            path = urllib.parse.urlsplit(self.path).path
            if path == "/api/jobs":
                self._json({"jobs": jobs, "pagination": {"total": len(jobs)}})
            elif path.startswith("/api/jobs/"):
                self._json(details.get(path.rsplit("/", 1)[-1], {}))
            elif path == "/internal/folder_paths":
                self._json({"checkpoints": [str(out_dir.parent / "models" / "checkpoints")]})
            else:
                self.send_response(404)
                self.end_headers()

    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{port}"
    watcher = ComfyWatcher(store, recipes, exports, interval=999.0)
    try:
        # ---- ④ 設定（監視の接続先と出力先）----
        with store.transaction() as con:
            con.execute("INSERT OR REPLACE INTO settings(key, value) VALUES ('comfyui.url', ?)", (base,))
            con.execute("INSERT OR REPLACE INTO settings(key, value) VALUES ('comfyui.output_dir', ?)",
                        (str(out_dir),))
        # ---- ⑤ 1 周期目: 印つきの 2 枚 ----
        before = int(__import__("time").time() * 1000) + 500     # **開始より後**に来た job にする
        watcher.start(base_url=base, run=False)       # **開始のあとに job を流す**
        add_job("job-marker", [{"filename": same_png.name, "subfolder": sub, "type": "output"},
                               {"filename": other_png.name, "subfolder": sub, "type": "output"}], before)
        cycle1 = watcher.poll_once()
        rows = store.con.execute(
            "SELECT r.*, e.seed FROM recipe_export_result r JOIN recipe_export e ON e.id = r.export_id"
            " ORDER BY r.created_at, r.id").fetchall()
        # ---- ⑥ 2 周期目: 印の無い job（**作られない**）----
        add_job("job-stray", [{"filename": stray_png.name, "subfolder": "other", "type": "output"}],
                before + 10_000)
        cycle2 = watcher.poll_once()
        after_rows = store.con.execute("SELECT count(*) AS n FROM recipe_export_result").fetchone()["n"]
        # ---- ⑦ タグ付けの job（`outputs_count: 0`）は詳細を取らない ----
        jobs.append({"id": "job-tags", "status": "completed", "create_time": before + 20_000,
                     "outputs_count": 0, "previewable_outputs_count": 0})
        called: list[str] = []
        watcher._http = lambda url, **kw: (called.append(url), _probe_get(url, base, jobs, details))[1]
        cycle3 = watcher.poll_once()
        sidecars = sorted(p.name for p in (out_dir / sub).glob("*.result.json"))
        return {
            "ok": (len(rows) == 2 and after_rows == 2 and cycle1["results"] == 2
                   and cycle2["results"] == 0 and cycle3["results"] == 0
                   and not any("job-tags" in u for u in called)),
            "attempt_id": attempt_id, "marker": got.get("marker"), "out_dir": str(out_dir),
            "results": [{"matched_by": r["matched_by"], "same_hash": bool(r["same_hash"]),
                         "seed_changed": bool(r["seed_changed"]), "ssim": r["ssim"],
                         "phash_distance": r["phash_distance"], "seed": r["seed"],
                         "result_asset_id": r["result_asset_id"]} for r in rows],
            "cycles": {"marker": cycle1, "stray": cycle2, "tags": cycle3},
            "rows_after_stray": after_rows, "sidecars": sidecars,
            "exported_hash": exported_hash,
            "tag_job_detail_calls": [u for u in called if "job-tags" in u],
        }
    finally:
        watcher.stop()
        server.shutdown()
        store.close()


def _probe_get(url: str, base: str, jobs: list, details: dict):
    """偽の ComfyUI を**差し替えずに**数えるための小さな中継（3 周期目だけ使う）。"""
    path = urllib.parse.urlsplit(url).path
    if path == "/api/jobs":
        return {"jobs": jobs, "pagination": {"total": len(jobs)}}
    if path.startswith("/api/jobs/"):
        return details.get(path.rsplit("/", 1)[-1], {})
    return {}


def main() -> int:
    global OK
    parser = argparse.ArgumentParser(description="P7 の実測")
    parser.add_argument("--judge", action="store_true", help="複製で 263 枚に記録を付けて数える")
    parser.add_argument("--export", action="store_true",
                        help="複製の 1 枚から seed 2 つを書き出す（P7-2 の線 3・4・5）")
    parser.add_argument("--http", action="store_true", help="複製にサーバを立てて口から確かめる")
    parser.add_argument("--watch", action="store_true",
                        help="偽の ComfyUI を立てて監視を通す（P7-3 の線 6。**生成はしない**）")
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

    if args.watch:
        say("\n=== 線 6: 印から結果が紐付く（P7-3。偽の ComfyUI）===")
        got = watch_of(data, port=args.port + 1, keep=args.keep)
        if not got.get("ok") and got.get("why"):
            say(f"  NG: {got['why']}")
            OK = False
        else:
            say(f"  印: {got['marker']} / 出力先: {got['out_dir']}")
            for one in got["results"]:
                say(f"  結果: matched_by={one['matched_by']} same_hash={one['same_hash']}"
                    f" seed_changed={one['seed_changed']} seed={one['seed']}"
                    f" ssim={one['ssim']} phash={one['phash_distance']}")
                if one["seed_changed"]:
                    say("    （seed が違う物を混ぜた。**気づけている**のが正）")
            say(f"  周期: 印つき={got['cycles']['marker']['results']} 枚"
                f" / 印なし={got['cycles']['stray']['results']} 枚（0 が正）"
                f" / タグ付け job の詳細取得={len(got['tag_job_detail_calls'])} 回（0 が正）")
            say(f"  sidecar: {got['sidecars']}")
            if not got["ok"]:
                say("  NG: 期待（印つき 2 行・印なし 0 行・タグ付け job の詳細 0 回）に合いません")
                OK = False

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
