"""ComfyUI の監視の最小形と、結果の紐付け（P7-3。R12 の後半）。

設計: `docs/p7-design.md` **§0.2**（P3 との分担）・**§0.9**（監視の最小形。**この実装の正**）・
§0.10（`GET` は書かない・`actor`）・§2.1（`watcher_state` / `recipe_export_result`）・
§3.4（監視の口）・§3.6（手で紐付ける口と合否）・§4（状態）・§8.1（テスト）

決めたことの要点（**設計 §0.9 をそのまま実装する**）:

- **必要なときだけ人が開始**する（`POST /api/watcher/start`）。**常駐しない**。
  `enabled` はプロセスの状態ではなく **`watcher_state` の行**（再起動したら止まっている）
- **2 秒ごと**に ComfyUI の **`GET /api/jobs?limit=50&status=completed`** を見る（**一覧に `workflow` は無い**ので 2 段）。
  **`outputs_count: 0` の job（タグ付けなど）は詳細を取らずに弾く**（点検 B-3-4）
- **既読は `create_time`（ms）基準**＋**処理済み id の集合**（同じ ms に 2 件入ることがある）。
  **`in_progress` は既読にしない**（基準を進めるのは、それより古い未完了が無いときだけ）
- **`execution_cached` は全 job に出る**（当たっていない job は `nodes: []`）。
  **保存ノードの id が `execution_cached.nodes` に含まれるとき＝新しい画像は出ていない**（点検 B-3-3）
- **結果の実体**は設定 **`comfyui.output_dir`**（無ければ `/internal/folder_paths` から**推定**し、
  **実在するときだけ**使う）。**推定が当たらなければ `GET /view` で `<data>/results/<sha256>.png` に取り込む**
- **印の照合**は `subfolder`（**Windows ではバックスラッシュ**。点検 B-4）の前方一致。
  見つからなければ**PNG の `prompt` チャンク**を見る（利用者の回答 Q2 の保険）
- **合否は人だけ**（`human` 以外 403）。**上書き**＋`verdict_at` / `verdict_actor`
- **1 周期で登録する枚数の上限は 20**。**外部（HTTP）は取引の外で待つ**（家風）
"""

from __future__ import annotations

import hashlib
import json
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Callable, Iterable, Sequence

from . import db, png_meta
from .recipe import ComfyProbe, recipe_hash
from .recipe_export import MARKER_PREFIX
from .review import ReviewError

#: `watcher_state.name`。将来の監視を増やせるように名前で持つ（§2.1）
WATCHER_NAME = "comfyui"

DEFAULT_URL = "http://127.0.0.1:8188"
DEFAULT_INTERVAL = 2.0
#: 1 周期で登録する枚数の上限（§0.9 の決定）
MAX_PER_CYCLE = 20
#: 一覧を引く件数（新しい順）
LIST_LIMIT = 50
#: 結果の画像の置き場（推定が当たらなかったときの取り込み先）
RESULTS_DIR = "results"

VERDICTS = ("same", "close", "different", "failed")
MATCHED_BY = ("marker", "manual", "conditions")


# ---- 設定（`settings` 表）----


def settings_of(con) -> dict:
    """`comfyui.*` を読む（無ければ既定）。**呼ぶたびに読む**（P4-2 の監査 C-1 の教訓）。"""
    got: dict[str, str] = {}
    try:
        for row in con.execute("SELECT key, value FROM settings WHERE key LIKE 'comfyui.%'"
                               " OR key = 'tagger.comfyui'"):
            got[row["key"]] = row["value"]
    except Exception:                                    # noqa: BLE001  表が無い環境でも既定で動く
        pass
    return {
        "url": (got.get("comfyui.url") or got.get("tagger.comfyui") or DEFAULT_URL).rstrip("/"),
        "output_dir": (got.get("comfyui.output_dir") or "").strip() or None,
        "interval": _number(got.get("comfyui.interval"), DEFAULT_INTERVAL),
    }


def _number(raw: Any, default: float) -> float:
    try:
        return float(raw)
    except (TypeError, ValueError):
        return default


# ---- HTTP（差し替えられる形にする。テストは偽の ComfyUI を渡す）----


def _http_json(url: str, *, timeout: float = 5.0) -> Any:
    """`GET` して JSON を返す。**失敗は例外**（呼ぶ側が「その回を飛ばす」を決める）。"""
    req = urllib.request.Request(url, method="GET")
    with urllib.request.urlopen(req, timeout=timeout) as got:
        body = got.read()
    try:
        return json.loads(body or b"null")
    except json.JSONDecodeError:
        return None


def _http_bytes(url: str, *, timeout: float = 30.0) -> bytes:
    req = urllib.request.Request(url, method="GET")
    with urllib.request.urlopen(req, timeout=timeout) as got:
        return got.read()


def infer_output_dir(base_url: str, *, http: Callable[..., Any] = _http_json) -> str | None:
    """`/internal/folder_paths` から出力先を推定する（§0.9。**実在するときだけ**返す）。

    **ComfyUI は `output` を教えない**（実測: `checkpoints` / `loras` / `vae` / `text_encoders` / `configs` だけ）。
    一覧の `<ComfyUI>/models/checkpoints` の**`models` の親**が ComfyUI の根なので、**`<根>/output`** を見る。
    """
    try:
        got = http(base_url.rstrip("/") + "/internal/folder_paths") or {}
    except OSError:
        return None
    if not isinstance(got, dict):
        return None
    for key in ("checkpoints", "loras", "vae", "text_encoders", "configs"):
        for one in got.get(key) or []:
            path = Path(str(one))
            parent = path.parent
            if parent.name.lower() == "models":
                out = parent.parent / "output"
                if out.is_dir():
                    return str(out)
    return None


# ---- 監視 ----


class ComfyWatcher:
    """監視の最小形（§0.9）。**人が開始したときだけ**回る。"""

    def __init__(self, store, recipes, exports, *, interval: float | None = None,
                 http: Callable[..., Any] | None = None, bytes_of: Callable[..., bytes] | None = None,
                 probe_factory: Callable[..., Any] | None = None) -> None:
        self.store = store
        self.recipes = recipes
        self.exports = exports
        self._http = http or _http_json
        self._bytes = bytes_of or _http_bytes
        self._probe_factory = probe_factory          # 検査用（P7-2 と同じ形。使わないこともある）
        self.interval = float(interval if interval is not None else DEFAULT_INTERVAL)
        #: 処理済みの job id（**同じ ms に 2 件入る**ことがあるので集合で弾く。§0.9）
        self._seen: set[str] = set()
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        #: 直近の周期の数え方（`GET /api/watcher` が返す）
        self.picked = {"results": 0, "texts": 0, "skipped_jobs": 0}

    # ---- 状態（`watcher_state` の 1 行。**プロセスの状態ではない**）----

    def _row(self, con):
        return con.execute("SELECT * FROM watcher_state WHERE name = ?", (WATCHER_NAME,)).fetchone()

    def status(self) -> dict:
        """`GET /api/watcher`（§3.4）。**1 バイトも書かない**。"""
        with self.store.locked() as con:
            row = self._row(con)
        if row is None:
            return {"enabled": False, "last_prompt_id": None, "baseline_create_time": None,
                    "last_polled_at": None, "last_error": None, "picked": dict(self.picked),
                    "output_dir": None, "output_dir_inferred": False}
        return {"enabled": bool(row["enabled"]), "last_prompt_id": row["last_prompt_id"],
                "baseline_create_time": row["baseline_create_time"],
                "last_polled_at": row["last_polled_at"], "last_error": None,
                "picked": dict(self.picked),
                "output_dir": self._saved_output_dir(),
                "output_dir_inferred": bool(self._saved_output_dir()) and not self._configured()}

    def _configured(self) -> str | None:
        with self.store.locked() as con:
            return settings_of(con)["output_dir"]

    def _saved_output_dir(self) -> str | None:
        return self._out_dir_cache

    # ---- 開始 / 停止 ----

    def start(self, *, base_url: str | None = None, actor: str = "human") -> dict:
        """`POST /api/watcher/start`（§3.4）。**設定は開始のたびに読む**（点検 C-6）。

        開始時に**そのときの最新の `create_time` を基準**にする（過去の job を遡らない）。
        """
        with self.store.locked() as con:
            settings = settings_of(con)
        base = (base_url or settings["url"]).rstrip("/")
        self.interval = float(settings.get("interval") or DEFAULT_INTERVAL)
        # **出力先**: 設定 → 推定（実在するときだけ）→ 取り込み（`<data>/results/`）
        out_dir = settings["output_dir"]
        inferred = False
        if not out_dir:
            out_dir = infer_output_dir(base, http=self._http)
            inferred = bool(out_dir)
        if out_dir and not Path(out_dir).is_dir():
            out_dir, inferred = None, False
        self._out_dir_cache = out_dir
        baseline = None
        last_id = None
        try:
            jobs = self._jobs(base)
            if jobs:
                baseline = max(int(j.get("create_time") or 0) for j in jobs)
                last_id = str(jobs[0].get("id") or "") or None
        except OSError:
            baseline = int(time.time() * 1000)          # 繋がらないときは「いま」から
        if out_dir:
            self._add_root(out_dir)
        with self.store.transaction() as con:
            con.execute(
                "INSERT INTO watcher_state(name, last_prompt_id, baseline_create_time,"
                " last_polled_at, enabled, updated_at) VALUES (?, ?, ?, ?, 1, ?)"
                " ON CONFLICT(name) DO UPDATE SET last_prompt_id = excluded.last_prompt_id,"
                " baseline_create_time = excluded.baseline_create_time, enabled = 1,"
                " updated_at = excluded.updated_at",
                (WATCHER_NAME, last_id, baseline, db.now(), db.now()))
        self.picked = {"results": 0, "texts": 0, "skipped_jobs": 0}
        self._seen.clear()
        self._start_thread()
        return {"enabled": True, "baseline_prompt_id": last_id, "base_url": base,
                "output_dir": out_dir, "output_dir_inferred": inferred,
                "interval": self.interval}

    def stop(self) -> dict:
        """`POST /api/watcher/stop`。**冪等**（既に止まっていても 200）。"""
        self._stop.set()
        thread, self._thread = self._thread, None
        if thread is not None and thread.is_alive():
            thread.join(timeout=2.0)
        with self.store.transaction() as con:
            con.execute("UPDATE watcher_state SET enabled = 0, updated_at = ? WHERE name = ?",
                        (db.now(), WATCHER_NAME))
        return {"enabled": False}

    def _add_root(self, path: str) -> None:
        """出力先を**登録ルートに足す**（§0.9。出力は普通は登録ルートの外にある）。"""
        try:
            roots = [str(r) for r in self.store.roots()]
        except Exception:                                # noqa: BLE001  古い DB でも落とさない
            return
        if any(str(Path(r)) == str(Path(path)) for r in roots):
            return
        self.store.set_roots([*roots, str(path)])

    # ---- ポーリング ----

    def _start_thread(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="comfy-watcher", daemon=True)
        self._thread.start()

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                self.poll_once()
            except Exception:                            # noqa: BLE001  1 周期の失敗で監視を止めない
                pass
            self._stop.wait(self.interval)

    def poll_once(self) -> dict:
        """1 周期（§0.9）。**`GET` からは呼ばない**（結果の登録＝書き込みを伴う）。

        繋がらない・詳細が取れない → **その回を飛ばして次の周期で再試行**（既読にしない）。
        """
        with self.store.locked() as con:
            row = self._row(con)
            settings = settings_of(con)
        if row is None or not row["enabled"]:
            return {"skipped": "stopped"}
        base = settings["url"]
        out_dir = self._out_dir_cache or settings["output_dir"]
        baseline = int(row["baseline_create_time"] or 0)
        counters = {"results": 0, "texts": 0, "skipped_jobs": 0, "jobs": 0, "cached": 0, "error": None}
        try:
            jobs = self._jobs(base)
        except OSError as exc:
            counters["error"] = f"{type(exc).__name__}: {exc}"
            self._touch(baseline, error=True)
            return counters
        # **画像を出す job だけ**（`outputs_count: 0` は詳細を取らずに弾く。点検 B-3-4）
        picked = [j for j in jobs
                  if int(j.get("outputs_count") or 0) > 0
                  and int(j.get("create_time") or 0) >= baseline
                  and str(j.get("id") or "") not in self._seen]
        counters["skipped_jobs"] = len(jobs) - len(picked)
        newest = baseline
        for job in picked[:MAX_PER_CYCLE]:
            job_id = str(job.get("id") or "")
            if not job_id:
                continue
            counters["jobs"] += 1
            try:
                detail = self._detail(base, job_id)
            except OSError:
                continue                                 # **既読にしない**（次の周期で再試行）
            if self._cached_only(detail):
                counters["cached"] += 1
                self._seen.add(job_id)
                newest = max(newest, int(job.get("create_time") or 0))
                continue
            got = self._take_images(detail, base, out_dir)
            counters["results"] += got["results"]
            counters["texts"] += got["texts"]
            self._seen.add(job_id)
            newest = max(newest, int(job.get("create_time") or 0))
        self.picked = {"results": counters["results"], "texts": counters["texts"],
                       "skipped_jobs": counters["skipped_jobs"]}
        # **`failed` / `cancelled` は既読にだけする**（§0.9）
        for status in ("failed", "cancelled"):
            for job in self._status_jobs(base, status) or []:
                job_id = str(job.get("id") or "")
                when = int(job.get("create_time") or 0)
                if job_id and when >= baseline:
                    self._seen.add(job_id)
                    newest = max(newest, when)
        # **進めない条件**: それより古い未完了（`pending` / `in_progress`）があれば、そこで止める
        # （点検 B-3-2）。引けない環境では判定に使わない（繋がらないだけで止まらない）
        clamp = self._unfinished_ct(base)
        if clamp is not None:
            newest = max(baseline, min(newest, clamp - 1))
        self._touch(newest, count=len(picked))
        return counters

    def _status_jobs(self, base: str, status: str) -> list[dict] | None:
        """`?status=` で引く。**引けなければ `None`**（判定に使わない）。"""
        try:
            got = self._http(f"{base}/api/jobs?limit={LIST_LIMIT}&offset=0&status={status}", timeout=5.0)
        except OSError:
            return None
        if isinstance(got, dict):
            return list(got.get("jobs") or [])
        return list(got) if got is not None else None

    def _unfinished_ct(self, base: str) -> int | None:
        """未完了の job の**最も古い `create_time`**（無ければ `None`）。"""
        times: list[int] = []
        for status in ("pending", "in_progress"):
            for job in self._status_jobs(base, status) or []:
                if job.get("create_time") is not None:
                    times.append(int(job.get("create_time") or 0))
        return min(times) if times else None

    def _jobs(self, base: str) -> list[dict]:
        got = self._http(f"{base}/api/jobs?limit={LIST_LIMIT}&offset=0&status=completed", timeout=5.0)
        if isinstance(got, dict):
            return list(got.get("jobs") or [])
        return list(got or [])

    def _detail(self, base: str, job_id: str) -> dict:
        got = self._http(f"{base}/api/jobs/{urllib.parse.quote(job_id)}", timeout=10.0)
        return got if isinstance(got, dict) else {}

    def _cached_only(self, detail: dict) -> bool:
        """**保存ノードが `execution_cached.nodes` に含まれる**＝新しい画像は出ていない（点検 B-3-3）。"""
        cached = (((detail.get("execution_status") or {}).get("messages") or [])
                  if isinstance(detail.get("execution_status"), dict) else [])
        nodes: list[str] = []
        for entry in cached:
            if isinstance(entry, (list, tuple)) and len(entry) >= 2 and entry[0] == "execution_cached":
                data = entry[1] if isinstance(entry[1], dict) else {}
                nodes = [str(n) for n in (data.get("nodes") or [])]
        if not nodes:
            return False
        saves = [str(nid) for nid, node in ((detail.get("workflow") or {}).get("prompt") or {}).items()
                 if isinstance(node, dict) and node.get("class_type") in ("SaveImage", "PreviewImage")]
        return bool(saves) and all(nid in nodes for nid in saves)

    def _touch(self, baseline: int, *, count: int = 0, error: bool = False) -> None:
        with self.store.transaction() as con:
            con.execute("UPDATE watcher_state SET baseline_create_time = ?, last_polled_at = ?,"
                        " updated_at = ? WHERE name = ?",
                        (int(baseline), db.now(), db.now(), WATCHER_NAME))

    # ---- 結果を拾う ----

    def _take_images(self, detail: dict, base: str, out_dir: str | None) -> dict:
        """1 つの job の出力画像を、印で記録に当てて結果にする（§0.9）。"""
        got = {"results": 0, "texts": 0}
        images = _images_of(detail)
        for image in images:
            export = self._match(image, base, out_dir)
            if export is None:
                continue
            made = self._register_result(export, image, detail, base, out_dir)
            if made:
                got["results"] += 1
                if made.get("text_captured"):
                    got["texts"] += 1
        return got

    def _match(self, image: dict, base: str, out_dir: str | None):
        """印から `recipe_export` の行を引く（§0.9 の照合）。

        ① `subfolder` の前方一致（**Windows はバックスラッシュ**。点検 B-4）
        ② 見つからなければ**PNG の `prompt` チャンク**の `filename_prefix` を見る（保険）
        """
        sub = _norm_sub(image.get("subfolder"))
        attempt_id = None
        parts = [p for p in sub.split("/") if p]
        for one in parts:
            if one.startswith(MARKER_PREFIX) and len(one) > len(MARKER_PREFIX):
                attempt_id = one[len(MARKER_PREFIX):]
                break
        seed = _seed_of(image.get("filename"))
        if attempt_id:
            row = self._export_row(attempt_id, seed)
            if row is not None:
                return row
        # ② 保険: 実体の PNG を見る
        path = self._local_path(image, out_dir)
        if path is None or not Path(path).exists():
            return None
        try:
            prov = png_meta.provenance(str(path))
        except Exception:                                # noqa: BLE001  壊れた PNG はスキップ
            return None
        prefix = _save_prefix(prov.get("graph"))
        if not prefix:
            return None
        name = str(prefix).replace("\\", "/")
        for one in [p for p in name.split("/") if p]:
            if one.startswith(MARKER_PREFIX) and len(one) > len(MARKER_PREFIX):
                row = self._export_row(one[len(MARKER_PREFIX):], seed)
                if row is not None:
                    return row
        return None

    def _export_row(self, attempt_id: str, seed: str | None):
        with self.store.locked() as con:
            rows = con.execute("SELECT * FROM recipe_export WHERE attempt_id = ?", (attempt_id,)).fetchall()
        if not rows:
            return None
        if seed is not None:
            for row in rows:
                if str(row["seed"]) == str(seed):
                    return row
        return rows[0]

    def _local_path(self, image: dict, out_dir: str | None) -> Path | None:
        if not out_dir:
            return None
        sub = _norm_sub(image.get("subfolder"))
        name = str(image.get("filename") or "")
        if not name:
            return None
        return Path(out_dir).joinpath(*[p for p in f"{sub}/{name}".split("/") if p])

    def _register_result(self, export, image: dict, detail: dict, base: str, out_dir: str | None):
        """結果の画像を**登録**し、`recipe_export_result` に 1 行作る（§0.9）。"""
        path = self._local_path(image, out_dir)
        taken = False
        if path is None or not path.exists() or not path.is_file():
            path = self._fetch(image, base)
            taken = path is not None
        if path is None:
            return None
        with self.store.locked() as con:
            row = con.execute("SELECT * FROM recipe_record WHERE id = ?", (export["recipe_id"],)).fetchone()
        if row is None:
            return None
        asset_id, _created = self._register_asset(path)
        prov = png_meta.provenance(str(path))
        result_hash = None
        if isinstance(prov.get("graph"), dict):
            result_hash = recipe_hash(prov["graph"])
        same = int(bool(result_hash) and result_hash == export["recipe_hash"])
        seed_got = _seed_of_graph(prov.get("graph"))
        seed_changed = int(seed_got is not None and export["seed"] is not None
                           and str(seed_got) != str(export["seed"]))
        metrics = self._metrics(row, path)
        with self.store.transaction() as con:
            exists = con.execute("SELECT id FROM recipe_export_result WHERE export_id = ?"
                                 " AND result_asset_id = ?", (export["id"], asset_id)).fetchone()
            if exists is not None:
                return {"id": exists["id"], "asset_id": asset_id, "replayed": True}
            result_id = db.ulid()
            con.execute(
                "INSERT INTO recipe_export_result(id, export_id, prompt_id, result_asset_id,"
                " matched_by, result_hash, same_hash, ssim, phash_distance, changed_fraction,"
                " mean_abs, seed_changed, created_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (result_id, export["id"], _prompt_id(detail), asset_id, "marker", result_hash, same,
                 metrics.get("ssim"), metrics.get("phash_distance"), metrics.get("changed_fraction"),
                 metrics.get("mean_abs"), seed_changed, db.now()))
        sidecar = self._sidecar(path, row, export, result_id, result_hash, same, seed_changed, metrics)
        return {"id": result_id, "asset_id": asset_id, "replayed": False, "sidecar": sidecar,
                "taken": taken, "text_captured": bool(prov.get("info"))}

    def _register_asset(self, path: Path) -> tuple[str, bool]:
        """結果の PNG を `asset` に登録する（走査と同じ形。§0.9）。"""
        data = path.read_bytes()
        sha = hashlib.sha256(data).hexdigest()
        st = path.stat()
        prov = png_meta.provenance(str(path))
        meta = prov.get("info") if isinstance(prov.get("info"), dict) else None
        return self.store.register(
            sha256=sha, path=str(path), size=st.st_size, mtime_ns=st.st_mtime_ns,
            width=prov.get("width"), height=prov.get("height"), fmt="png",
            meta=meta, note=prov.get("note"), kind="generated", kind_source="auto:result")

    def _metrics(self, record_row, path: Path) -> dict:
        """元の画像と結果の指標（`comparison.md` §4 の定義。**同じ実装**を使う）。"""
        try:
            with self.store.locked() as con:
                loc = con.execute("SELECT path FROM asset_location WHERE asset_id = ?"
                                  " ORDER BY is_primary DESC, path LIMIT 1",
                                  (record_row["source_asset_id"],)).fetchone()
        except Exception:                                # noqa: BLE001
            loc = None
        if loc is None:
            return {}
        src = Path(loc["path"])
        if not src.exists():
            return {}
        try:
            from .compare import compute_pair_metrics, phash_bits
            from PIL import Image

            got = dict(compute_pair_metrics(str(src), str(path)))
            with Image.open(src) as a, Image.open(path) as b:
                got["phash_distance"] = bin(phash_bits(a.convert("RGB"))
                                            ^ phash_bits(b.convert("RGB"))).count("1")
            return got
        except Exception:                                # noqa: BLE001  指標は無くても登録する
            return {}

    def _fetch(self, image: dict, base: str) -> Path | None:
        """`GET /view` で取り寄せて `<data>/results/<sha256>.png` に**取り込む**（§0.9）。

        推定が当たらなかったときの道。**どちらの道を通ったかは画面に出す**（`taken` を返す）。
        """
        query = urllib.parse.urlencode({"filename": image.get("filename") or "",
                                        "subfolder": image.get("subfolder") or "",
                                        "type": image.get("type") or "output"})
        try:
            body = self._bytes(f"{base}/view?{query}")
        except OSError:
            return None
        if not body:
            return None
        digest = hashlib.sha256(body).hexdigest()
        out = Path(self.store.data_dir) / RESULTS_DIR / f"{digest}.png"
        out.parent.mkdir(parents=True, exist_ok=True)
        tmp = out.with_suffix(".png.part")
        tmp.write_bytes(body)
        tmp.replace(out)                                 # **原子的に**（`os.replace` 相当）
        return out

    def _sidecar(self, path: Path, record_row, export, result_id: str, result_hash: str | None,
                 same: int, seed_changed: int, metrics: dict) -> str | None:
        """結果の隣に人が読める JSON を置く（§0.9。`capture.py` に倣う）。"""
        try:
            doc = {"abi": "0.1", "kind": "recipe_result", "result_id": result_id,
                   "recipe_id": record_row["id"], "attempt_id": export["attempt_id"],
                   "seed": export["seed"], "result_hash": result_hash,
                   "recipe_hash": export["recipe_hash"], "same_hash": bool(same),
                   "seed_changed": bool(seed_changed), "metrics": metrics,
                   "at": db.now()}
            out = path.with_suffix(".result.json")
            tmp = out.with_suffix(".json.part")
            tmp.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
            tmp.replace(out)
            return str(out)
        except OSError:
            return None

    # ---- 手で紐付ける・合否（§3.6）----

    def attach(self, recipe_id: str, attempt_id: str, result_asset_id: str, *, actor: str = "human",
               client_token: str | None = None) -> dict:
        """`POST /api/recipes/{id}/exports/{attempt_id}/results`（**人だけ**）。"""
        export = self._export_of(recipe_id, attempt_id)
        if export is None:
            raise ReviewError(404, "その書き出しはありません",
                              details={"attempt_id": attempt_id})
        with self.store.locked() as con:
            asset = con.execute("SELECT id FROM asset WHERE id = ?", (result_asset_id,)).fetchone()
        if asset is None:
            raise ReviewError(404, "その画像はありません", details={"result_asset_id": result_asset_id})
        with self.store.transaction() as con:
            if client_token:
                old = con.execute("SELECT * FROM recipe_export_result WHERE id = ?",
                                  (str(client_token),)).fetchone()
                if old is not None:
                    return {"id": old["id"], "replayed": True}
            exists = con.execute("SELECT * FROM recipe_export_result WHERE export_id = ?"
                                 " AND result_asset_id = ?", (export["id"], result_asset_id)).fetchone()
            if exists is not None:
                return {"id": exists["id"], "replayed": True}
            result_id = db.ulid()
            con.execute(
                "INSERT INTO recipe_export_result(id, export_id, prompt_id, result_asset_id,"
                " matched_by, created_at) VALUES (?, ?, NULL, ?, 'manual', ?)",
                (result_id, export["id"], result_asset_id, db.now()))
        return {"id": result_id, "replayed": False, "matched_by": "manual"}

    def set_verdict(self, recipe_id: str, attempt_id: str, result_id: str, verdict: str, *,
                    note: str | None = None, actor: str = "human") -> dict:
        """`POST …/results/{result_id}/verdict`（§3.6。**人だけ**・**上書き**）。"""
        if verdict not in VERDICTS:
            raise ReviewError(422, "verdict は same | close | different | failed です",
                              details={"verdict": "same | close | different | failed"})
        export = self._export_of(recipe_id, attempt_id)
        if export is None:
            raise ReviewError(404, "その書き出しはありません", details={"attempt_id": attempt_id})
        with self.store.transaction() as con:
            row = con.execute("SELECT * FROM recipe_export_result WHERE id = ? AND export_id = ?",
                              (result_id, export["id"])).fetchone()
            if row is None:
                raise ReviewError(404, "その結果はありません", details={"result_id": result_id})
            con.execute("UPDATE recipe_export_result SET verdict = ?, verdict_at = ?,"
                        " verdict_actor = ?, note = ? WHERE id = ?",
                        (verdict, db.now(), actor, note, result_id))
        return {"id": result_id, "verdict": verdict, "verdict_actor": actor, "note": note}

    def _export_of(self, recipe_id: str, attempt_id: str):
        """記録 id と束 id から**ファイルの 1 行**を引く（`recipe_id` は束の側にある）。"""
        with self.store.locked() as con:
            return con.execute(
                "SELECT e.* FROM recipe_export e"
                " JOIN recipe_export_attempt a ON a.attempt_id = e.attempt_id"
                " WHERE a.recipe_id = ? AND e.attempt_id = ?"
                " ORDER BY COALESCE(e.seed, '') LIMIT 1",
                (recipe_id, attempt_id)).fetchone()

    def results(self, recipe_id: str) -> dict:
        """結果の一覧（`GET /api/recipes/{id}/exports` の材料。**書かない**）。"""
        with self.store.locked() as con:
            rows = con.execute(
                "SELECT r.*, e.attempt_id, e.seed, e.recipe_hash FROM recipe_export_result r"
                " JOIN recipe_export e ON e.id = r.export_id"
                " WHERE e.recipe_id = ? ORDER BY r.created_at DESC, r.id DESC",
                (recipe_id,)).fetchall()
        return {"recipe_id": recipe_id, "items": [
            {"id": r["id"], "attempt_id": r["attempt_id"], "seed": r["seed"],
             "prompt_id": r["prompt_id"], "result_asset_id": r["result_asset_id"],
             "matched_by": r["matched_by"], "result_hash": r["result_hash"],
             "same_hash": bool(r["same_hash"]), "ssim": r["ssim"],
             "phash_distance": r["phash_distance"], "changed_fraction": r["changed_fraction"],
             "mean_abs": r["mean_abs"], "seed_changed": bool(r["seed_changed"]),
             "verdict": r["verdict"], "verdict_at": r["verdict_at"],
             "verdict_actor": r["verdict_actor"], "note": r["note"]}
            for r in rows]}


# ---- 純関数（テストはここを直接叩く）----


def _norm_sub(subfolder: Any) -> str:
    """`subfolder` を `/` 区切りにする（**Windows ではバックスラッシュで来る**。点検 B-4）。"""
    return str(subfolder or "").replace("\\", "/").strip("/")


def _images_of(detail: dict) -> list[dict]:
    """job の詳細から出力画像を取り出す（`outputs[*].images`）。"""
    out: list[dict] = []
    outputs = detail.get("outputs") or {}
    if isinstance(outputs, dict):
        for node in outputs.values():
            if isinstance(node, dict):
                out.extend([i for i in (node.get("images") or []) if isinstance(i, dict)])
    elif isinstance(outputs, list):
        for node in outputs:
            if isinstance(node, dict):
                out.extend([i for i in (node.get("images") or []) if isinstance(i, dict)])
    return out


def _seed_of(filename: Any) -> str | None:
    """ファイル名の `seed-<値>_` を読む（印の後半。§0.7）。無ければ `None`。"""
    name = str(filename or "")
    if not name.startswith("seed-"):
        return None
    body = name[len("seed-"):]
    head = body.split("_", 1)[0]
    return head or None


def _prompt_id(detail: dict) -> str | None:
    return str(detail.get("id") or "") or None


def _save_prefix(graph: Any) -> str | None:
    """グラフの `SaveImage.filename_prefix`（印の照合の保険）。"""
    if not isinstance(graph, dict):
        return None
    for node in graph.values():
        if isinstance(node, dict) and node.get("class_type") in ("SaveImage", "PreviewImage"):
            got = (node.get("inputs") or {}).get("filename_prefix")
            if isinstance(got, str):
                return got
    return None


def _seed_of_graph(graph: Any) -> str | None:
    """グラフの `KSampler.seed`（結果の seed。§0.9 の `seed_changed`）。"""
    if not isinstance(graph, dict):
        return None
    for node in graph.values():
        if isinstance(node, dict) and node.get("class_type") in ("KSampler", "KSamplerAdvanced"):
            got = (node.get("inputs") or {}).get("seed")
            if got is not None:
                return str(got)
    return None
