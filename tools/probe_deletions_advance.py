"""**後から段 2 へ進める・実体が無い行を片付ける**（P10）の合格の線を、**複製**で通す道具。

利用者の要望「一度カタログから削除したものをゴミ箱に移す方法はない？」への実装
（記録: `docs/deletions-advance.md`）を、**実データを 1 バイトも触らずに**実機で確かめる。

- **複製は `sqlite3.Connection.backup()` で作る**（`.data/db.sqlite3` は WAL なので `cp` では
  未畳み込みの分が抜ける）。画像は `shutil.copy2` で複製に置く。
- **サーバは必ず `IMAGE_REVIEWER_DATA=<複製>` で立てる**（`create_app()` が env を検査する）。
  バックアップの置き場も**リポジトリの中**へ向ける（`%USERPROFILE%` の下には書けない）。
- **実データは `mode=ro` でしか開かない**。使い捨ては `.tmp-audit-redo/`。

使い方::

    $env:UV_CACHE_DIR = "C:\\work\\image-reviwer\\.uv-cache"
    .venv\\Scripts\\python.exe tools\\probe_deletions_advance.py --port 8796
    .venv\\Scripts\\python.exe tools\\probe_deletions_advance.py --port 8796 --keep
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REAL = ROOT / ".data"
WORK_ROOT = ROOT / ".tmp-audit-redo"
HUMAN = "human"


# ---- 道具 ----


def http(base: str, method: str, path: str, body: dict | None = None,
         actor: str | None = HUMAN) -> tuple[int, dict]:
    """1 回の HTTP（`urllib` だけで足りる）。**本文が JSON でなくても落とさない**。"""
    data = None if body is None else json.dumps(body).encode("utf-8")
    req = urllib.request.Request(base + path, data=data, method=method)
    if data is not None:
        req.add_header("Content-Type", "application/json")
    if actor:
        req.add_header("X-Image-Reviewer-Actor", actor)
    try:
        with urllib.request.urlopen(req, timeout=60) as got:
            raw = got.read().decode("utf-8", "replace")
            status = got.status
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", "replace")
        status = exc.code
    try:
        return status, json.loads(raw)
    except json.JSONDecodeError:
        return status, {"raw": raw[:400]}


def wait_up(base: str, proc: subprocess.Popen, timeout: float = 60.0) -> None:
    end = time.time() + timeout
    while time.time() < end:
        if proc.poll() is not None:
            raise SystemExit(f"サーバが落ちました（終了コード {proc.returncode}）")
        try:
            status, _ = http(base, "GET", "/api/pending-deletes")
            if status == 200:
                return
        except OSError:
            pass
        time.sleep(0.4)
    raise SystemExit("サーバが上がりませんでした")


def ro(path: Path) -> sqlite3.Connection:
    con = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    return con


def _rewrite(text: str, pairs: list[tuple[str, str]], *, key: bool) -> str:
    """パスの頭を貼り替える（**大小は見ないで比べ、尾はそのまま**）。

    `key=True` の列（`path`）は `normalize_path()` の形（`os.path.normcase`）に揃える。
    **貼り替えが要るのは、複製の DB が実データの絶対パスを持っているから**——
    そのままサーバを立てると、**複製の操作が実データの画像を動かす**。
    """
    low = str(text).lower()
    for real, new in pairs:
        head = str(real).lower().rstrip("\\/")
        if low == head:
            return os.path.normcase(str(new)) if key else str(new)
        if low.startswith(head + "\\") or low.startswith(head + "/"):
            tail = str(text)[len(head):]
            got = str(new) + tail
            return os.path.normcase(got) if key else got
    return str(text)


def _rewrite_json(text: str | None, pairs: list[tuple[str, str]]) -> str | None:
    """JSON の中のパスも貼り替える（**エスケープされた形**でも当たるようにする）。"""
    if not text:
        return text
    out = str(text)
    for real, new in pairs:
        for form, to in ((json.dumps(str(real))[1:-1], json.dumps(str(new))[1:-1]),
                         (str(real), str(new))):
            out = out.replace(form, to)
            out = out.replace(form.lower(), to)
    return out


def make_replica(work: Path, real: Path) -> dict:
    """**複製を作る**（DB は `backup()`・画像は `copy2`・**パスは複製の中へ貼り替える**）。

    **実データは `mode=ro` でしか開かない。** 貼り替えないと、複製のサーバが
    **実データの画像を動かす**（`os.rename` は絶対パスで動く）ので、ここが一番危ない。
    """
    data = work / "data"
    data.mkdir(parents=True, exist_ok=True)
    src = sqlite3.connect(f"file:{(real / 'db.sqlite3').as_posix()}?mode=ro", uri=True)
    dst = sqlite3.connect(str(data / "db.sqlite3"))
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()
    # 置き場ごとに複製の行き先を決める（**同じボリューム**に置く＝`same_volume` が成り立つ）
    con = sqlite3.connect(str(data / "db.sqlite3"))
    con.row_factory = sqlite3.Row
    library = data / "library"
    pairs: list[tuple[str, str]] = []
    copies: list[tuple[str, str]] = []            # (実データの場所, 複製の場所)
    try:
        roots = [r["display_path"] for r in con.execute("SELECT display_path FROM root")]
        for i, root in enumerate(roots):
            pairs.append((str(root), str(library / str(i))))
        pairs.append((str(real), str(data)))          # 一時置き場・ゴミ箱の中のパス
        # 列ごとに貼り替える（**鍵は `normcase` の形**）。**元の値も控える**（複製に写すため）
        tables = (
            ("root", ("path", True), ("display_path", False)),
            ("asset_location", ("path", True), ("display_path", False)),
            ("deletion_log", ("path", True), ("from_path", True), ("to_path", False),
             ("hold_path", False)),
            ("location_history", ("path", True), ("to_path", False)),
        )
        for table, *columns in tables:
            have = {r[1] for r in con.execute(f"PRAGMA table_info({table})")}
            for column, is_key in columns:
                if column not in have:
                    continue
                rows = con.execute(f"SELECT rowid AS rid, {column} AS v FROM {table}"
                                   " WHERE v IS NOT NULL").fetchall()
                for row in rows:
                    new = _rewrite(row["v"], pairs, key=is_key)
                    if new != row["v"]:
                        copies.append((str(row["v"]), new))
                        con.execute(f"UPDATE {table} SET {column} = ? WHERE rowid = ?",
                                    (new, row["rid"]))
        for table, column in (("delete_request", "payload_json"),
                              ("pending_delete_preview", "items_json"),
                              ("pending_delete_preview", "scope_json")):
            have = {r[1] for r in con.execute(f"PRAGMA table_info({table})")}
            if column not in have:
                continue
            for row in con.execute(f"SELECT rowid AS rid, {column} AS v FROM {table}"
                                   " WHERE v IS NOT NULL").fetchall():
                new = _rewrite_json(row["v"], pairs)
                if new != row["v"]:
                    con.execute(f"UPDATE {table} SET {column} = ? WHERE rowid = ?",
                                (new, row["rid"]))
        con.commit()
    finally:
        con.close()
    # **画像を複製に写す**（実データの場所 → 複製の場所）。同じ物は 1 回だけ
    copied = missing = 0
    done: set[str] = set()
    for source_text, target in copies:
        key = os.path.normcase(str(target))
        if key in done:
            continue
        done.add(key)
        source = Path(source_text)
        try:
            if not source.is_file():
                missing += 1
                continue
            if Path(target).is_file():
                copied += 1
                continue
            Path(target).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
            copied += 1
        except OSError as exc:
            missing += 1
            print(f"  注意: 複製できないファイル: {source}（{exc}）")
    # **一時置き場とゴミ箱の中身も複製する**（空のはずだが、在れば持って行く）
    for sub in ("pending-delete", "trash"):
        base = real / sub
        if not base.exists():
            continue
        for path in base.rglob("*"):
            if path.is_file():
                target = data / sub / path.relative_to(base)
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(path, target)
    # **安全の確認（事故を隠さない）**: 複製の DB が持つパスが**複製の外**を指していたら止める
    con = ro(data / "db.sqlite3")
    try:
        outside = [str(r["display_path"]) for r in
                   con.execute("SELECT display_path FROM asset_location")
                   if r["display_path"]
                   and not str(r["display_path"]).lower().startswith(str(library).lower())]
    finally:
        con.close()
    if outside:
        raise SystemExit("複製のパスが複製の外を指しています（危険なので止めます）: "
                         f"{outside[:3]}（{len(outside)} 件）")
    return {"data": str(data), "copied": copied, "missing": missing,
            "wanted": len(done), "pairs": pairs, "library": str(library)}


def tree_signature(data: Path, library_roots: list[str]) -> tuple:
    """**画像の署名**（置き場と複製の中のファイルの `(場所, 大きさ, mtime)`）。

    DB のファイル（`db.sqlite3` と `-wal` / `-shm`）は**外す**（台帳を書く道具なので）。
    """
    out = []
    for base in [Path(x) for x in library_roots] + [data]:
        if not base.exists():
            continue
        for path in base.rglob("*"):
            if not path.is_file() or path.name.startswith("db.sqlite3"):
                continue
            try:
                got = path.stat()
            except OSError:
                continue
            out.append((str(path), int(got.st_size), int(got.st_mtime_ns)))
    return tuple(sorted(out))


def report(rows: list[tuple[str, bool, str]], title: str) -> int:
    print(f"\n== {title} ==")
    bad = 0
    for line, ok, note in rows:
        print(f"  {'ok  ' if ok else 'NG  '}{line}: {note}")
        bad += 0 if ok else 1
    print(f"  → {'すべて ok' if not bad else f'{bad} 件 NG'}（{len(rows)} 件）")
    return bad


# ---- 線 ----


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8796)
    ap.add_argument("--data", default=str(REAL))
    ap.add_argument("--keep", action="store_true", help="複製とサーバを残す")
    ap.add_argument("--serve", action="store_true",
                    help="複製を作ってサーバだけ立てる（線は回さない。`gui_layout` 用。--keep を含む）")
    ap.add_argument("--work", default="")
    got = ap.parse_args()
    base = f"http://127.0.0.1:{got.port}"
    work = Path(got.work) if got.work else WORK_ROOT / \
        f"advance-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
    work.mkdir(parents=True, exist_ok=True)
    real = Path(got.data)
    print(f"複製を作ります: {work}（実データ {real} は読み取り専用）")
    made = make_replica(work, real)
    data = Path(made["data"])
    library = str(made["library"]).lower()
    print(f"  複製: 画像 {made['copied']} 件・見つからない物 {made['missing']} 件"
          f"（対象 {made['wanted']} 件）")

    env = dict(os.environ)
    env.update({
        "IMAGE_REVIEWER_DATA": str(data),
        "IMAGE_REVIEWER_BACKUP_DIR": str(work / "backups"),     # **%USERPROFILE% には作らない**
        "PYTHONIOENCODING": "utf-8",
        "PYTHONUTF8": "1",
    })
    log = (work / "server.log").open("wb")
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "image_reviewer.app:app",
         "--host", "127.0.0.1", "--port", str(got.port), "--log-level", "warning"],
        env=env, stdout=log, stderr=subprocess.STDOUT, cwd=str(ROOT))
    out_rows: list[tuple[str, bool, str]] = []
    failures = 0
    try:
        wait_up(base, proc)
        print(f"サーバ: {base}（IMAGE_REVIEWER_DATA={data}）")
        if got.serve:
            print("`gui_layout` をこの URL に向けて回せます:"
                  f"\n  node tools/gui_layout.mjs --base {base} --screen pending"
                  "\n  node tools/gui_layout.mjs --base "
                  f"{base} --screen pending --ids <id>,<id>"
                  "\n止めるには Ctrl+C（複製は残ります）")
            try:
                while True:
                    time.sleep(1)
            except KeyboardInterrupt:
                print("止めます（複製は残します）")
            return 0
        con = ro(data / "db.sqlite3")
        try:
            rows = [dict(r) for r in con.execute(
                "SELECT d.*, l.display_path AS loc_display FROM deletion_log d"
                "   LEFT JOIN asset_location l ON l.path = d.path"
                " WHERE d.stage = 1 AND d.restored_at IS NULL ORDER BY d.at, d.id")]
            roots = [r["display_path"] for r in con.execute("SELECT display_path FROM root")]
            hidden_before = {r["id"]: r["deleted_at"] for r in
                             con.execute("SELECT id, deleted_at FROM asset")}
            assets_before = con.execute("SELECT count(*) AS n FROM asset").fetchone()["n"]
            locs_before = [tuple(r) for r in con.execute(
                "SELECT path, asset_id, display_path, missing_at FROM asset_location"
                " ORDER BY path")]
        finally:
            con.close()
        live = [r for r in rows if r["loc_display"] and os.path.exists(str(r["loc_display"]))
                and str(r["loc_display"]).lower().startswith(library)]
        gone = [r for r in rows if r not in live]
        outside = [r for r in rows if r["loc_display"]
                   and not str(r["loc_display"]).lower().startswith(library)]
        if outside:
            out_rows.append(("複製の外を指す行が 1 つも無い", False,
                             f"{len(outside)} 件（危険なので触りません）"))
        print(f"複製の中: 段 1 の生きた行 {len(rows)} 件（実体あり {len(live)}・実体なし {len(gone)}）")

        # 線 1: 実体がある行を段 2 へ進める → 移る・`to_path` が入る・`missing_at` が立つ
        advanced_ok = False
        restored_id = None                     # 線 2 で「戻す」に使った行（一覧から外れる）
        if live:
            one = live[0]
            path = Path(str(one["loc_display"]))
            before = (path.stat().st_size, path.stat().st_mtime_ns)
            status, body = http(base, "POST", f"/api/deletions/{one['id']}/advance",
                                {"stage": 2})
            moved = Path(str(body.get("to_path") or "."))
            advanced_ok = (status == 200 and body.get("stage") == 2 and moved.is_file()
                           and not path.exists()
                           and (moved.stat().st_size, moved.stat().st_mtime_ns) == before)
            con = ro(data / "db.sqlite3")
            try:
                missing_at = con.execute("SELECT missing_at FROM asset_location WHERE path = ?",
                                         (one["path"],)).fetchone()
            finally:
                con.close()
            out_rows.append((
                "ファイルがある → アプリのゴミ箱へ移る",
                advanced_ok and bool(missing_at and missing_at["missing_at"]),
                f"{status} code={body.get('code')} to_path={moved} 実体={moved.is_file()} "
                f"元={path.exists()} missing_at={bool(missing_at and missing_at['missing_at'])}"))
            # 線 2: **「戻す」がそのまま効く**（既存の trash restore の道）
            restored_id = one["id"] if advanced_ok else None
            status2, body2 = http(base, "POST", "/api/trash/restore", {"deletion_id": one["id"]})
            out_rows.append((
                "「戻す」で元の場所に戻る",
                advanced_ok and status2 == 200 and body2.get("restored") is True
                and path.is_file() and not moved.exists(),
                f"{status2} restored={body2.get('restored')} 元={path.is_file()}"
                + ("" if advanced_ok else "（前の線が NG なので飛ばしました）")))
        else:
            print("  注意: 実体の在る段 1 の行が 0 件（線 1・2 は飛ばします）")

        # 線 3: 実体が無い行を段 2 へ進めようとすると 409 `missing_file`（次の一手を案内）
        if gone:
            one = gone[0]
            status, body = http(base, "POST", f"/api/deletions/{one['id']}/advance",
                                {"stage": 2})
            out_rows.append((
                "ファイルが無い → 409 missing_file",
                status == 409 and body.get("code") == "missing_file"
                and "ファイルが無いので片付ける" in str(body.get("detail")),
                f"{status} code={body.get('code')}"))

        # 線 4: **片付けの前後でファイルが 1 つも動かない**（署名）
        sig_before = tree_signature(data, roots)
        con = ro(data / "db.sqlite3")
        try:
            before_close = {r["id"]: r["deleted_at"] for r in
                            con.execute("SELECT id, deleted_at FROM asset")}
        finally:
            con.close()

        # 線 5: **194 行をまとめて片付ける**（1 回の上限 200 の中。実データと同じ数）
        ids = [r["id"] for r in rows]
        status, body = http(base, "POST", "/api/deletions/close",
                            {"ids": ids, "reason": "missing"})
        closed = int(body.get("count") or 0)
        skipped = body.get("skipped") or []
        out_rows.append((
            f"まとめて片付ける（{len(ids)} 件を 1 回で）",
            status == 200 and closed == len(gone) and len(skipped) == len(live),
            f"{status} 片付けた={closed} 断った={len(skipped)}"
            f"（実体あり {len(live)} と一致={len(skipped) == len(live)}）"))
        reasons = sorted({s.get("reason") for s in skipped})
        others = [r for r in live if r["id"] != restored_id]
        out_rows.append((
            "断った理由は file_found（生きているファイルを片付けない）",
            set(reasons) <= {"file_found", "already_restored"}
            and ("file_found" in reasons or not others),
            f"{reasons}（実体あり {len(live)} のうち、戻した 1 件は already_restored）"))

        # 線 6: `closed_at` が入り、`asset.deleted_at` はそのまま（**カタログに戻さない**）
        con = ro(data / "db.sqlite3")
        try:
            after_rows = {r["id"]: dict(r) for r in con.execute(
                "SELECT id, asset_id, stage, closed_at, close_reason, restored_at"
                " FROM deletion_log")}
            hidden_after = {r["id"]: r["deleted_at"] for r in
                            con.execute("SELECT id, deleted_at FROM asset")}
            assets_after = con.execute("SELECT count(*) AS n FROM asset").fetchone()["n"]
            locs_after = [tuple(r) for r in con.execute(
                "SELECT path, asset_id, display_path, missing_at FROM asset_location"
                " ORDER BY path")]
        finally:
            con.close()
        closed_ids = [r["id"] for r in rows if after_rows[r["id"]]["closed_at"]]
        out_rows.append((
            "closed_at と close_reason が入る",
            len(closed_ids) == len(gone)
            and all(after_rows[i]["close_reason"] == "missing" for i in closed_ids),
            f"closed={len(closed_ids)}（実体なし {len(gone)} と一致={len(closed_ids) == len(gone)}）"))
        # **片付けた行の `asset.deleted_at` が残っているか**（**カタログに戻さない**）
        still_hidden = [i for i in closed_ids
                        if hidden_after.get(after_rows[i]["asset_id"])]
        out_rows.append((
            "片付けた行の asset.deleted_at はそのまま（カタログに戻さない）",
            len(still_hidden) == len(closed_ids),
            f"隠れたまま {len(still_hidden)}/{len(closed_ids)}"
            f"（全体では隠れ {sum(1 for v in hidden_after.values() if v)} 件）"))
        out_rows.append((
            "asset と asset_location の行は減らない",
            assets_after == assets_before and locs_after == locs_before,
            f"asset {assets_before}→{assets_after}・登録 {len(locs_before)}→{len(locs_after)}"))
        out_rows.append((
            "片付けはファイルを 1 つも動かさない（署名）",
            tree_signature(data, roots) == sig_before,
            f"{len(sig_before)} 件のファイルが同じ"))

        # 線 7: 二重に片付けても 1 行（200 で `replayed: true`）
        if gone:
            status, body = http(base, "POST", f"/api/deletions/{gone[0]['id']}/close",
                                {"reason": "missing"})
            out_rows.append((
                "二重に片付けても 200 で replayed（記録は 1 回）",
                status == 200 and body.get("replayed") is True,
                f"{status} replayed={body.get('replayed')}"))

        # 線 8: 片付けた行は「最近の削除」から外れ、**断った行だけ残る**（台帳には全部残る）
        status, pend = http(base, "GET", "/api/pending-deletes")
        status2, led = http(base, "GET", "/api/deletions?limit=1000")
        wanted = set(ids)
        left = [i for i in (pend.get("items") or []) if i["id"] in wanted]
        kept = [i for i in (led.get("items") or []) if i["id"] in wanted]
        skipped_ids = {s.get("deletion_id") for s in skipped}
        # **戻した 1 件**（線 1・2 で使った行）は `restored_at` が立つので、そもそも一覧に出ない
        want_left = skipped_ids - ({restored_id} if restored_id else set())
        closed_left = [i for i in left if i["id"] not in skipped_ids]
        out_rows.append((
            "片付けた行は「最近の削除」から外れ、台帳に残る",
            status == 200 and status2 == 200 and not closed_left
            and len(kept) == len(ids) and {i["id"] for i in left} == want_left,
            f"一覧に残った={len(left)}（断った {len(want_left)} と一致="
            f"{({i['id'] for i in left} == want_left)}）台帳={len(kept)}/{len(ids)}"))

        # 線 9: `GET` は 1 バイトも書かない（署名が変わらない）
        columns = ("id", "stage", "closed_at", "close_reason", "restored_at")
        con = ro(data / "db.sqlite3")
        try:
            states_before = {r["id"]: dict(r) for r in con.execute(
                "SELECT " + ", ".join(columns) + " FROM deletion_log")}
        finally:
            con.close()
        sig_before_get = tree_signature(data, roots)
        for path in ("/api/pending-deletes", "/api/trash", "/api/deletions?limit=1000"):
            http(base, "GET", path)
        con = ro(data / "db.sqlite3")
        try:
            states_after = {r["id"]: dict(r) for r in con.execute(
                "SELECT " + ", ".join(columns) + " FROM deletion_log")}
        finally:
            con.close()
        out_rows.append((
            "GET は 1 バイトも書かない",
            tree_signature(data, roots) == sig_before_get and states_after == states_before,
            f"署名 {'同じ' if tree_signature(data, roots) == sig_before_get else '違う'}・"
            f"台帳の列 {'同じ' if states_after == states_before else '違う'}"))

        # 線 10: 人だけ（エージェントは 403 `human_only`）
        if gone:
            status, body = http(base, "POST", f"/api/deletions/{gone[0]['id']}/close",
                                {"reason": "missing"}, actor="agent")
            out_rows.append((
                "エージェントは片付けられない（403 human_only）",
                status == 403 and body.get("code") == "human_only",
                f"{status} code={body.get('code')}"))
            status, body = http(base, "POST", "/api/deletions/advance",
                                {"ids": [gone[0]["id"]], "stage": 2}, actor="agent")
            out_rows.append((
                "エージェントは段 2 へ進められない（403 human_only）",
                status == 403 and body.get("code") == "human_only",
                f"{status} code={body.get('code')}"))

        failures = report(out_rows, "P10（後から段 2・片付け）の線")
    finally:
        if got.keep:
            print(f"\n残しました（--keep）: サーバ {base} / 複製 {work}")
        else:
            proc.terminate()
            try:
                proc.wait(timeout=20)
            except subprocess.TimeoutExpired:
                proc.kill()
            log.close()
            time.sleep(1.0)                       # `lifespan` の後始末を待つ
            shutil.rmtree(work, ignore_errors=True)
            if work.exists():
                print(f"注意: 複製を消せませんでした（開いたままのファイル）: {work}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
