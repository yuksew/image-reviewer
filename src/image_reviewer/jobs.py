"""背景ジョブ（P4-1）。**時間のかかる処理を 1 本のワーカーで流す。**

設計: docs/p4-design.md §0.3（job をこの段で作る）・§0.11（再開と「付いている語を飛ばす」）・
§3.2〜§3.3（受付と進行）・§4.1（状態）・§0.10（`GET` は書かない・決定性）

- **ワーカーは 1 本**（プロセス内の 1 スレッド）。`design.md` §8.2 の「GPU の同時実行は 1」をスレッド数で満たす
- **1 枚 1 取引**（点検 C-5）。中断の印は**画像 1 枚ごとに**見る
- **失敗は 1 件ずつ `job_item` に残す**（握りつぶさない）。`job.state='failed'` は**1 枚も処理できなかった**ときだけ
  （点検 C-4）
- **`GET` は書かない**（進みは `job` の行を読むだけ）
- **再開**は「同じ params でもう一度流す」。既に付いた語は飛ばす（`source='wd14'` は **`model` を見る**。
  `source='png'` は毎回やり直す）
- **語の作り方**（点検 §I）: `tag` への書き込みは **`ON CONFLICT ... DO UPDATE SET known = max(known, …)`**。
  `INSERT OR IGNORE` だと **PNG の語が先に入った語が `known=0` のまま残る**
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from typing import Any, Iterable, Sequence

from . import db, tagger
from .compare import _primary_path
from .review import ReviewError

#: 409 の対象にする状態は `running` だけ（点検 C-4。`queued` が残るのはワーカーが動けないときで、
#: そのときは job を作らずに `tagger_unavailable` を返す）
BUSY_STATES = ("queued", "running")     # **`queued` も忙しい**（P4-1 の監査 B-2）。
# `queued` を外すと、job の INSERT からワーカーが `running` に上げるまでの窓で 2 本目が通り、
# **ワーカーが 2 本走る**（監査が再現）。`recover_stale()` が起動時に `queued` も片づけるので、
# `queued` のまま残って詰まることはない


def _loads(value: Any, default):
    if not value:
        return default
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return default


def job_doc(con, row, *, failed_limit: int = 20) -> dict:
    """`GET /api/jobs/{id}` の形（§3.3）。**読むだけ**。"""
    params = _loads(row["params"], {})
    done, total = int(row["progress_done"] or 0), int(row["progress_total"] or 0)
    counts = {"tagged": 0, "skipped": 0, "failed": 0}
    for got in con.execute("SELECT state, count(*) AS n FROM job_item WHERE job_id = ? GROUP BY state",
                           (row["id"],)):
        if got["state"] in counts:
            counts[got["state"]] = int(got["n"])
    failed = [{"ref": item["ref"], "error": item["error"]}
              for item in con.execute(
                  "SELECT ref, error FROM job_item WHERE job_id = ? AND state = 'failed'"
                  " ORDER BY ref LIMIT ?", (row["id"], failed_limit))]
    return {
        "id": row["id"],
        "kind": row["kind"],
        "state": row["state"],
        "params": params,
        "progress": {"done": done, "total": total},
        "message": row["message"],
        # **結果の 1 行**（「PNG の語: 42 語を採用（長すぎて落とした断片 3）」など。§0.8-5）
        "note": (row["note"] if "note" in row.keys() else None),
        "counts": counts,
        "error": row["error"],
        "started_at": row["started_at"],
        "finished_at": row["finished_at"],
        "items_failed": failed,
    }


class JobService:
    """ジョブの受付と実行（**1 本のワーカー**）。"""

    def __init__(self, store, *, recover: bool = True, poll: float = 0.05):
        self.store = store
        self.poll = poll
        self._lock = threading.RLock()
        self._thread: threading.Thread | None = None
        self._cancelled: set[str] = set()
        self._notes: dict[str, list[str]] = {}
        if recover:
            self.recover_stale()

    # ---- 起動時の手当て ----

    def recover_stale(self) -> int:
        """**プロセスが落ちたときに `running` のまま残った job を `failed` にする。**

        残すと 1 本しかないワーカーが塞がって、次の `POST` が 409 になる（§4.1）。
        付いた語は消さないので、**同じ params でもう一度流せば続きから**（§0.11）。
        """
        with self.store.transaction() as con:
            got = con.execute(
                "UPDATE job SET state = 'failed', finished_at = ?, message = ?,"
                " error = 'プロセスが終了しました（同じ条件でもう一度流すと続きから付けます）'"
                " WHERE state IN ('queued', 'running')", (db.now(), "中断されました"))
            return got.rowcount or 0

    # ---- 受付 ----

    def start_tag(self, *, asset_ids: Sequence[str] | None = None, engine: str = "auto",
                  model: str | None = None, threshold: float | None = None,
                  character_threshold: float | None = None,
                  sources: Sequence[str] | None = None, limit: int = 0,
                  force: bool = False) -> dict:
        """タグ付けの job を作る（§3.2）。**投げてすぐ返る**（実行は背景）。

        **検査（忙しい）と `INSERT` を同じ取引で行う**（P4-1 の監査 B-2）。分けると、
        `queued` の job をワーカーが `running` に上げるまでの窓で**2 本目が通る**
        （監査は `running` が 2 つ並ぶのを再現した）。**方式の検出（`tagger.detect`）は
        錠の外**で行う（ComfyUI への問い合わせで待つため。点検 B-1 と同じ趣旨）。
        """
        with self.store.locked() as con:
            settings = tagger.settings_of(con)
        sources = list(sources or ("png", "wd14"))
        if not sources or any(name not in tagger.SOURCES for name in sources):
            raise ReviewError(422, "sources は png | wd14 です", details={"sources": "png | wd14"})
        if engine not in tagger.ENGINES:
            raise ReviewError(422, "engine は auto | builtin | comfyui のいずれかです",
                              details={"engine": "auto | builtin | comfyui"})
        values = {"threshold": settings["threshold"] if threshold is None else float(threshold),
                  "character_threshold": (settings["character_threshold"]
                                          if character_threshold is None
                                          else float(character_threshold))}
        bad = {name: "0〜1 の数値です" for name, value in values.items()
               if not (0.0 <= value <= 1.0)}
        if bad:
            raise ReviewError(422, "閾値が 0〜1 の外です", details={"fields": bad})
        params = {"engine": engine, "model": model or settings["model"],
                  "node": settings["node"], "threshold": values["threshold"],
                  "character_threshold": values["character_threshold"],
                  "sources": sources, "force": bool(force), "limit": int(limit or 0)}
        needs_tag = "wd14" in sources
        report = tagger.detect(settings) if needs_tag else {}       # ← 錠の外（監査 B-2）
        chosen = tagger.choose(engine, report) if needs_tag else "builtin"
        params["engine"] = chosen
        job_id = db.ulid()
        with self.store.transaction() as con:                        # ← 検査と INSERT を同じ取引
            # ワーカーは 1 本（点検 C-4）。**`queued` も忙しいに入れる**（監査 B-2）
            busy = con.execute("SELECT id FROM job WHERE kind = 'tag' AND state IN (?,?)"
                               " ORDER BY created_at DESC LIMIT 1",
                               BUSY_STATES).fetchone()
            if busy is not None:
                raise ReviewError(409, "タグ付けの job が動いています", code="job_running",
                                  details={"job_id": busy["id"]})
            targets = self._targets(con, asset_ids=asset_ids, sources=sources, limit=limit)
            if not targets:
                return {"job_id": None, "total": 0, "engine": chosen,
                        "note": "付けるものがありません"}
            con.execute(
                "INSERT INTO job(id, kind, state, params, progress_done, progress_total, message,"
                " created_at) VALUES (?, 'tag', 'queued', ?, 0, ?, ?, ?)",
                (job_id, json.dumps(params, ensure_ascii=False), len(targets),
                 f"待っています（{len(targets)} 枚）", db.stamp()))
        self._start(job_id, targets, params)
        return {"job_id": job_id, "total": len(targets), "engine": chosen}

    def _targets(self, con, *, asset_ids: Sequence[str] | None, sources: Sequence[str],
                 limit: int) -> list[str]:
        """対象の画像を決める（§3.2 の既定）。"""
        if asset_ids:
            ids = list(asset_ids)
            unknown = [one for one in ids if con.execute(
                "SELECT 1 FROM asset WHERE id = ?", (one,)).fetchone() is None]
            if unknown:
                raise ReviewError(422, "知らない asset_id があります",
                                  details={"unknown_asset_ids": unknown})
            rows = [{"id": one} for one in ids]
        else:
            # 既定は「**その出所の語が 1 つも無い画像**」（古い順）。
            # **P4-1 の監査 C-2**: 複数の出所を **AND** すると、`sources=["png","wd14"]`（既定）で
            # 「png も wd14 も無い画像」だけになり、**png だけ先に付いた画像が対象から外れる**。
            # 設計 §3.2 の趣旨どおり、**`wd14` が入っていれば `wd14` の有無だけで決める**
            # （`png` の語は画像に埋まっている語なので、それを理由に対象から外さない）。
            key = "wd14" if "wd14" in sources else sources[0]
            missing = (f"NOT EXISTS (SELECT 1 FROM asset_tag t WHERE t.asset_id = a.id"
                       f" AND t.source = '{key}')")
            rows = con.execute(f"SELECT a.id FROM asset a WHERE {missing}"
                               " ORDER BY a.first_seen_at, a.id").fetchall()
        ids = [row["id"] for row in rows]
        if limit and limit > 0:
            ids = ids[:int(limit)]
        return ids

    # ---- 実行 ----

    def _start(self, job_id: str, targets: list[str], params: dict) -> None:
        with self._lock:
            self._cancelled.discard(job_id)
            thread = threading.Thread(target=self._run, args=(job_id, targets, params),
                                      name=f"job-{job_id}", daemon=True)
            self._thread = thread
            thread.start()

    def cancel(self, job_id: str) -> dict:
        """中断の印を立てる（§3.1）。**画像 1 枚ごとに見る**（すぐには止まらない）。"""
        with self.store.transaction() as con:
            row = con.execute("SELECT * FROM job WHERE id = ?", (job_id,)).fetchone()
            if row is None:
                raise ReviewError(404, "その job はありません", details={"job_id": job_id})
            if row["state"] not in ("queued", "running"):
                return job_doc(con, row)                     # 終わっている job はそのまま返す
            con.execute("UPDATE job SET message = ? WHERE id = ?", ("中断しています…", job_id))
        with self._lock:
            self._cancelled.add(job_id)
        return self.get(job_id)

    def _is_cancelled(self, job_id: str) -> bool:
        with self._lock:
            return job_id in self._cancelled

    def _run(self, job_id: str, targets: list[str], params: dict) -> None:
        started = time.monotonic()
        engine_obj = None
        try:
            with self.store.transaction() as con:
                con.execute("UPDATE job SET state = 'running', started_at = ? WHERE id = ?",
                            (db.stamp(), job_id))
            settings = tagger.settings_of(self.store.con)
            # **CSV は方式によらず読む**（`known` と `category` の出所。PNG の語にもタガーの語にも要る）。
            # 壊れた CSV（`category` が連続していない）は: 内蔵なら**そのまま失敗させる**
            # （前処理の切り方が決まらない。§0.6-6）。ComfyUI 経由なら**カテゴリ無しで続ける**
            csv_path = tagger.find_csv(settings.get("csv_path"))
            csv = None
            if csv_path is not None:
                try:
                    csv = tagger.read_csv(csv_path)
                except ReviewError:
                    if params["engine"] == "builtin":
                        raise
                    self._note(job_id, f"語彙（CSV）を読めないのでカテゴリは付けません: {csv_path}")
            self._refresh_known(csv)                          # 点検 §I-1: 語彙の引き直し（1 回）
            engine_obj = (tagger.build(self.store, settings, params["engine"])
                          if "wd14" in params["sources"] else None)
            processed = 0
            for index, asset_id in enumerate(targets):
                if self._is_cancelled(job_id):
                    self._finish(job_id, "cancelled", "中断しました（付いた語は残ります）")
                    return
                try:
                    outcome = self._one(job_id, asset_id, params, engine_obj, csv)
                except Exception as exc:                      # noqa: BLE001  1 枚の失敗で job を止めない
                    outcome = "failed"
                    self._item(job_id, asset_id, "failed", f"{type(exc).__name__}: {exc}")
                else:
                    processed += 1
                    self._item(job_id, asset_id, outcome, None)
                self._progress(job_id, index + 1, len(targets), started,
                               "skipped" if outcome == "skipped" else "tagged")
            states = dict(self._counts(job_id))
            if processed == 0 and states.get("tagged", 0) == 0 and states.get("failed", 0):
                self._finish(job_id, "failed", "1 枚も処理できませんでした")
            else:
                self._finish(job_id, "done",
                             f"{states.get('tagged', 0)} 枚に付けました"
                             f"（飛ばした {states.get('skipped', 0)} / 失敗 {states.get('failed', 0)}）")
        except Exception as exc:                              # noqa: BLE001  ワーカーは落とさない
            self._finish(job_id, "failed", f"{type(exc).__name__}: {exc}")
        finally:
            # **投げた複製を片づける**（P4-1 の監査 C: `temp/image-reviewer` に 53 枚 19 MB が
            # 残っていた）。設定 `tagger.comfyui_temp`（ComfyUI の `temp` の絶対パス）があるときだけ
            cleanup = getattr(engine_obj, "cleanup", None)
            if callable(cleanup):
                try:
                    removed = cleanup()
                    if removed:
                        self._note(job_id, f"ComfyUI の複製を {removed} 枚消しました")
                except Exception:                             # noqa: BLE001  片づけで job を落とさない
                    pass

    def _one(self, job_id: str, asset_id: str, params: dict, engine_obj, csv) -> str:
        """1 枚。**模型の待ちを取引の中に入れない**（P4-1 の監査 B-1）。

        点検 C-5 の「1 枚 1 取引」は**書き込みを 1 取引にまとめる**という趣旨で、
        **模型の待ち（秒単位）を取引に入れる**ことではない。取引の中で待つと、
        `Store` の錠を握ったままになるので、その間**全部の API（`GET` も）が待たされる**
        （監査の実測: 模型 1.0 秒で `locked()` の待ち 801〜901 ms、別接続の `INSERT` は 2,718 ms）。

        順序: **読む（錠だけ）→ 模型を呼ぶ（錠の外）→ 書く（短い 1 取引）**。
        戻り値は `tagged` か `skipped`。
        """
        sources = params["sources"]
        force = bool(params["force"])
        # **`store.asset()` を使う**（`locations` つきの dict。`_primary_path` がそれを見る）
        asset = self.store.asset(asset_id)
        if asset is None:
            raise ReviewError(404, "画像がありません", details={"asset_id": asset_id})
        # --- PNG の語（模型を使わない。毎回やり直す。§0.11）---
        if "png" in sources:
            with self.store.transaction() as con:
                self._write_png(con, asset, csv, job_id)
        if "wd14" not in sources:
            return "tagged"
        # --- 飛ばす判定（取引を開かない読み。§0.11）---
        model = params["model"]
        with self.store.locked() as con:
            done = con.execute(
                "SELECT 1 FROM asset_tag WHERE asset_id = ? AND source = 'wd14' AND model = ?"
                " LIMIT 1", (asset_id, model)).fetchone()
        if done is not None and not force:
            return "skipped"
        path = _primary_path(asset)
        if not path:
            raise ReviewError(409, "画像の実体が見つかりません", details={"asset_id": asset_id})
        # --- **模型（ここが秒単位で待つ。錠の外）** ---
        words = engine_obj.tag(path, name=self._copy_name(asset))
        # --- 書く（短い 1 取引）---
        with self.store.transaction() as con:
            con.execute("DELETE FROM asset_tag WHERE asset_id = ? AND source = 'wd14'",
                        (asset_id,))
            for name, score in words:
                if not tagger.is_acceptable(name):
                    continue
                category, category_name = (csv.category_of(name) if csv else (None, None))
                tag_id = self._ensure_tag(con, name, category, category_name,
                                          1 if (csv and csv.known(name)) else 0)
                con.execute(
                    "INSERT INTO asset_tag(asset_id, tag_id, score, source, model, actor,"
                    " tagged_at) VALUES (?,?,?,'wd14',?,NULL,?)"
                    " ON CONFLICT(asset_id, tag_id, source) DO UPDATE SET"
                    " score = excluded.score, model = excluded.model,"
                    " tagged_at = excluded.tagged_at",
                    (asset_id, tag_id, score, model, db.stamp()))
        return "tagged"

    def _write_png(self, con, asset, csv, job_id: str) -> None:
        """`final_prompt` から語を取って `source='png'` を入れ直す（§0.8）。"""
        meta_row = con.execute("SELECT meta_json FROM asset_meta WHERE asset_id = ?",
                               (asset["id"],)).fetchone()
        meta = _loads(meta_row["meta_json"] if meta_row else None, None)
        text = None
        if isinstance(meta, dict):
            text = meta.get("final_prompt") or meta.get("prompt")
        con.execute("DELETE FROM asset_tag WHERE asset_id = ? AND source = 'png'", (asset["id"],))
        if not text:
            return
        kept = dropped = 0
        for name in tagger.png_words(text):
            if not tagger.is_acceptable(name):                # 点検 §I-3: 長すぎる断片は入れない
                dropped += 1
                continue
            category, category_name = (csv.category_of(name) if csv else (None, None))
            tag_id = self._ensure_tag(con, name, category, category_name,
                                      1 if (csv and csv.known(name)) else 0)
            con.execute(
                "INSERT INTO asset_tag(asset_id, tag_id, score, source, model, actor, tagged_at)"
                " VALUES (?,?,NULL,'png',NULL,NULL,?)"
                " ON CONFLICT(asset_id, tag_id, source) DO NOTHING", (asset["id"], tag_id, db.stamp()))
            kept += 1
        if dropped:
            self._note(job_id, f"PNG の語: {kept} 語を採用（長すぎて落とした断片 {dropped}）")

    @staticmethod
    def _copy_name(asset) -> str:
        """ComfyUI に上げる複製の名前（点検 A-2-3・A-2-5）。

        **`asset_id`** を使い、**中身が変わった画像は名前も変える**（`<id>-<sha256 の先頭 8>`）。
        ComfyUI は `LoadImage` の出力を**ファイルのハッシュ**で持つので、同名のまま中身が変わると
        **古い結果**が返りうる。
        """
        sha = (asset["sha256"] or "")[:8]
        return f"{asset['id']}-{sha}" if sha else str(asset["id"])

    @staticmethod
    def _ensure_tag(con, name: str, category, category_name, known) -> int:
        """語の行を確保する（**点検 §I-1**）。

        `INSERT OR IGNORE` だと **PNG の語が先に入った語が `known=0` のまま残る**ので、
        **`ON CONFLICT ... DO UPDATE SET known = max(known, excluded.known)`** で**上げる**。
        `category` は空いていれば埋める（後から分かっても上書きしない）。
        """
        con.execute(
            "INSERT INTO tag(name, category, category_name, known) VALUES (?,?,?,?)"
            " ON CONFLICT(name) DO UPDATE SET"
            " known = max(tag.known, excluded.known),"
            " category = COALESCE(tag.category, excluded.category),"
            " category_name = COALESCE(tag.category_name, excluded.category_name)",
            (name, category, category_name, 1 if known else 0))
        row = con.execute("SELECT id FROM tag WHERE name = ?", (name,)).fetchone()
        return int(row["id"])

    def _refresh_known(self, csv) -> None:
        """**ジョブの開始時に 1 回**、`known` を語彙から引き直す（点検 §I-1。3,154 行で 1 ms）。"""
        if csv is None:
            return
        with self.store.transaction() as con:
            con.execute("CREATE TEMP TABLE IF NOT EXISTS _vocab(name TEXT PRIMARY KEY)")
            con.execute("DELETE FROM _vocab")
            con.executemany("INSERT OR IGNORE INTO _vocab(name) VALUES (?)",
                            [(name,) for name in csv.names])
            con.execute("UPDATE tag SET known = (name IN (SELECT name FROM _vocab))")
            con.execute("DROP TABLE _vocab")

    # ---- job の行 ----

    def _progress(self, job_id: str, done: int, total: int, started: float, last: str) -> None:
        spent = max(0.001, time.monotonic() - started)
        per = spent / max(1, done)
        left = max(0.0, per * (total - done))
        message = (f"{done} / {total}（1 枚 {per:.2f} 秒。残り {int(left // 60)} 分 {int(left % 60)} 秒）")
        with self.store.transaction() as con:
            con.execute("UPDATE job SET progress_done = ?, message = ? WHERE id = ?",
                        (done, message, job_id))

    def _item(self, job_id: str, ref: str, state: str, error: str | None) -> None:
        with self.store.transaction() as con:
            con.execute("INSERT INTO job_item(job_id, ref, state, error) VALUES (?,?,?,?)"
                        " ON CONFLICT(job_id, ref) DO UPDATE SET state = excluded.state,"
                        " error = excluded.error", (job_id, ref, state, error))

    def _note(self, job_id: str, text: str) -> None:
        """**結果の 1 行**を溜める（§0.8-5。終わったときに `job.note` へ書く）。

        数を黙って捨てない（「PNG の語: 42 語を採用（長すぎて落とした断片 3）」など）。
        """
        with self._lock:
            self._notes.setdefault(job_id, [])
            if text not in self._notes[job_id]:
                self._notes[job_id].append(text)

    def _counts(self, job_id: str) -> list[tuple[str, int]]:
        with self.store.locked() as con:
            return [(row["state"], int(row["n"])) for row in con.execute(
                "SELECT state, count(*) AS n FROM job_item WHERE job_id = ? GROUP BY state",
                (job_id,))]

    def _finish(self, job_id: str, state: str, message: str) -> None:
        """job を閉じる。**閉じる側が落ちて `running` のまま残らない**ようにする（P4-1 の監査 A-1）。

        古い v5 の DB には `job.note` が無い（`_migrate_v5` が足すが、**足せていない DB でも
        ここで死なない**ようにする）。`note` で落ちたら `note` 抜きで書き直し、それでも落ちたら
        `state` だけを書く（`running` のまま残すと、次の `POST` が永久に 409 になる）。
        """
        with self._lock:
            notes = "; ".join(self._notes.pop(job_id, [])) or None
        try:
            with self.store.transaction() as con:
                con.execute("UPDATE job SET state = ?, message = ?, note = ?, finished_at = ?"
                            " WHERE id = ?", (state, message, notes, db.stamp(), job_id))
            return
        except sqlite3.OperationalError:
            pass                                   # `note` 列が無い DB（古い v5）
        with self.store.transaction() as con:
            con.execute("UPDATE job SET state = ?, message = ?, finished_at = ? WHERE id = ?",
                        (state, message, db.stamp(), job_id))

    # ---- 読み出し（`GET` は書かない）----

    def get(self, job_id: str) -> dict:
        with self.store.locked() as con:
            row = con.execute("SELECT * FROM job WHERE id = ?", (job_id,)).fetchone()
            if row is None:
                raise ReviewError(404, "その job はありません", details={"job_id": job_id})
            return job_doc(con, row)

    def list(self, *, limit: int = 50) -> dict:
        """一覧（`#/jobs`）。**失敗した項目も先頭 20 件返す**（P4-3 の監査 A-1）。

        以前は `failed_limit=0` だったので、画面（一覧だけを読む）は**失敗の理由も
        「もう一度」の押し場も出せなかった**（`GET /api/jobs/{id}` には入っているのに、
        画面が読む口だけ空）。設計 §3.3 の「`items_failed` は先頭 20 件」は**一覧にも当てはめる**。
        """
        with self.store.locked() as con:
            rows = con.execute("SELECT * FROM job ORDER BY created_at DESC, id DESC LIMIT ?",
                               (max(1, min(int(limit or 50), 200)),)).fetchall()
            return {"items": [job_doc(con, row, failed_limit=20) for row in rows]}

    def wait(self, job_id: str, *, timeout: float = 60.0) -> dict:
        """テストと `probe` のための待ち（**API には出さない**）。"""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            got = self.get(job_id)
            if got["state"] not in ("queued", "running"):
                return got
            time.sleep(self.poll)
        return self.get(job_id)
