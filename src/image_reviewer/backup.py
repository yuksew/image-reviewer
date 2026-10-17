"""バックアップと復元（P8-4。設計 `docs/p8-design.md` §0.12・§3.3・§6.2・§8.1 の 23・24）。

**利用者が「取っていない（不安）」と言っている所**（§0.2 の Q3）。決めたこと:

1. **置き場は `<data>` の外**（既定 `%USERPROFILE%\\image-reviewer-backups\\`。環境変数
   `IMAGE_REVIEWER_BACKUP_DIR`、設定 `backup_dir`）。**`<data>` の中に置くと論理が閉じない**
   ——`<data>` を消したときに備える物を `<data>` の中に置くことになる（専門 §5.1 の注記）。
   **`<data>` の下を指定されたら断る**（`422 bad_backup_dir`）。
2. **取る物**: `db.sqlite3`（**online backup API。`-wal` / `-shm` を単独でコピーしない**）・
   `sidecar/`（**PNG から取り直せない唯一のもの**）・`export/`（DB を失ったときの最後の拠り所）・
   `settings.json`（人が読める控え。**設定そのものは DB の中にも入っている**）。
   **画像とサムネイルは取らない**（参照モードでは画像は利用者の資産。`--include-library` のときだけ）。
3. **日次は 1 日 1 回**。判定は**窓のタイマーと同じ 30 秒の周期**で回し、
   **起動したときにも 1 回見る**（点検 B2。起動時だけでは「立てっぱなし」で取れない）。
   **「いま取る」は必ず新しく取る**（同じ日でも `<YYYYMMDD>-<HHMMSS>/` を作る）。
4. **増分**: 前のスナップショットと同じ中身（sha256）のファイルは**コピーしない**
   （同じボリュームなら `os.link`。駄目なら写す）。**各スナップショットは単体で戻せる**
   （前のスナップショットを消しても、リンクが中身を保つ）。
5. **直近 7 個を残す**。消すのは**自分が作った形のフォルダ**（`<YYYYMMDD>` / `<YYYYMMDD>-<HHMMSS>`
   で `manifest.json` を持つ物）だけ。**利用者が置いた物は消さない。**
6. **失敗は黙って捨てない**（`settings` の `backup.last_error` に残し、`GET /api/backup` に出る）。
7. **原子性**: 一時フォルダ（`<backup_dir>/.tmp-<名前>`）に作ってから `os.replace` で差し替える
   （書きかけのスナップショットを置かない。家風）。
8. **復元**: 元の DB を**先に退避**してから置き換え、**戻す前に `quick_check`**、
   **戻した後に `integrity_check`**（通らなければ元に戻す）。
9. **壊れた DB の判定**: `quick_check` の**例外も「壊れている」に数える**（点検 B3）。
   行が `ok` 1 行でない場合も壊れている（実測: 300 ページ目を潰すと例外ではなくエラー行が返る）。
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import shutil
import sqlite3
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

from . import db, png_meta
from .clock import clock_of
from .review import ReviewError

log = logging.getLogger(__name__)

#: スナップショットの中の印（契約 `schemas/backup-manifest.schema.json`）
MANIFEST_NAME = "manifest.json"
SCHEMA_ID = "urn:image-reviewer:backup-manifest"
ABI = "0.1"
#: 人が読める設定の控え（**契約の `includes` には欄が無い**。DB にも入っている）
SETTINGS_NAME = "settings.json"
#: 一緒に控えるフォルダ（専門 §5.2 の 1）
COPY_DIRS = ("sidecar", "export")
#: 画像の実体を入れるフォルダ（`--include-library` のときだけ）
LIBRARY_DIR = "library"
#: 置き場の既定（`<data>` の外。専門 §5.2）
DEFAULT_BACKUP_DIRNAME = "image-reviewer-backups"
ENV_BACKUP_DIR = "IMAGE_REVIEWER_BACKUP_DIR"
#: `settings` の鍵
SETTING_BACKUP_DIR = "backup_dir"
SETTING_LAST_ERROR = "backup.last_error"
SETTING_LAST_ERROR_AT = "backup.last_error_at"
SETTING_LAST_OK_AT = "backup.last_ok_at"
#: **直近いくつ残すか**（設計 §0.12-3）
KEEP_SNAPSHOTS = 7
#: 日次の判定の周期（**窓のタイマーと同じ 30 秒**。点検 B2・設計 §0.16 B2）
TICK_INTERVAL_SEC = 30.0
#: 日付の境目は**現地（JST）**（ゴミ箱の日付と同じ規則。D-3。JST は夏時間が無いので固定）
JST_OFFSET_SEC = 9 * 3600
#: スナップショットの名前（`<YYYYMMDD>` が自動、`<YYYYMMDD>-<HHMMSS>` が「いま取る」）。
#: **`-<連番>` も自分の物**（同じ秒に 2 回押したときの逃げ道。`free_dir_name`）
SNAPSHOT_RE = re.compile(r"^\d{8}(-\d{6})?(-\d+)?$")
#: 復元の前に退避するフォルダの名前（`<backup_dir>` の下。**`<data>` の外**）
RESTORE_KEEP_PREFIX = "pre-restore-"
#: **版を上げる前に取る控え**の名前（設計 §0.12-6・専門 §5.4）。**掃除の対象にしない**
#: （版が上がるのは稀で、1 つ 1 つが「その版の最後の姿」なので残す）
PRE_MIGRATE_PREFIX = "pre-migrate-"

#: 復元の案内（`GET /api/health/db` と CLI が同じ文言を使う）
RESTORE_HINT = "image-reviewer restore <バックアップのフォルダ>"


# ---- 置き場 ----


def default_backup_dir() -> Path:
    """既定の置き場（`%USERPROFILE%\\image-reviewer-backups`）。**`<data>` の外**。"""
    return Path(os.path.expanduser("~")) / DEFAULT_BACKUP_DIRNAME


def env_backup_dir() -> Path | None:
    """環境変数の指定（あれば最優先。専門 §5.2 の 1）。"""
    raw = (os.environ.get(ENV_BACKUP_DIR) or "").strip()
    return Path(raw) if raw else None


def setting_of(con: sqlite3.Connection, key: str) -> str | None:
    """`settings` の 1 件（無ければ `None`）。"""
    row = con.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    return row["value"] if row is not None else None


def resolve_backup_dir(store) -> tuple[Path, str]:
    """置き場と、その出所（`env` / `settings` / `default`）を返す。

    優先は **環境変数 → 設定 `backup_dir` → 既定**（専門 §5.2 の 1）。
    設定が空文字なら既定に落とす（空のフォルダ名を作らない）。
    """
    got = env_backup_dir()
    if got is not None:
        return got, "env"
    with store.locked() as con:
        raw = setting_of(con, SETTING_BACKUP_DIR)
    if raw and str(raw).strip():
        return Path(str(raw).strip()), "settings"
    return default_backup_dir(), "default"


def check_backup_dir(target, data_dir) -> Path:
    """置き場として使えるか（**`<data>` の中は断る**）。

    理由: `<data>` を消したときに備える対策を `<data>` の中に置くと論理が閉じない
    （専門 §5.1 の注記）。**実データの隣に作らない**という指示書の鉄則もこれで守る。
    """
    from .store import is_under                     # 循環 import を避けて局所で

    path = Path(target)
    if is_under(str(path), str(data_dir)) or is_under(str(data_dir), str(path)):
        raise ReviewError(
            422, "バックアップの置き場はデータ置き場（<data>）の外にしてください",
            code="bad_backup_dir",
            details={"backup_dir": str(path), "data_dir": str(data_dir)})
    return path


# ---- 小さな道具 ----


def sha256_file(path) -> str:
    """ファイルの中身のハッシュ（**増分の判定はこれだけ**）。"""
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def dir_size(path: Path) -> tuple[int, int]:
    """(ファイル数, 合計バイト)。"""
    files = 0
    total = 0
    for p in path.rglob("*"):
        if p.is_file():
            files += 1
            try:
                total += p.stat().st_size
            except OSError:
                pass
    return files, total


def local_day(stamp: str) -> str:
    """UTC の時刻（`YYYY-MM-DDTHH:MM:SSZ`）から**現地（JST）の日付**を出す（D-3 と同じ規則）。"""
    got = datetime.strptime(stamp, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    return (got + timedelta(seconds=JST_OFFSET_SEC)).strftime("%Y%m%d")


def local_hhmmss(stamp: str) -> str:
    got = datetime.strptime(stamp, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    return (got + timedelta(seconds=JST_OFFSET_SEC)).strftime("%H%M%S")


def plus_seconds(stamp: str, sec: int) -> str:
    got = datetime.strptime(stamp, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    return (got + timedelta(seconds=sec)).strftime("%Y-%m-%dT%H:%M:%SZ")


def next_local_midnight(stamp: str) -> str:
    """次に日付が変わる時刻（UTC の ISO。**JST の 0 時**）。"""
    got = datetime.strptime(stamp, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    jst = got + timedelta(seconds=JST_OFFSET_SEC)
    nxt = (jst + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    return (nxt - timedelta(seconds=JST_OFFSET_SEC)).strftime("%Y-%m-%dT%H:%M:%SZ")


def free_dir_name(parent: Path, name: str) -> Path:
    """空いているフォルダ名を選ぶ（同じ秒に 2 回押されても**上書きしない**）。"""
    candidate = parent / name
    if not candidate.exists():
        return candidate
    for n in range(1, 1000):
        candidate = parent / f"{name}-{n}"
        if not candidate.exists():
            return candidate
    raise ReviewError(409, "空いている名前が見つかりません", code="target_exists",
                      details={"dir": str(parent), "name": name})


# ---- manifest（契約 `schemas/backup-manifest.schema.json`）----


def validate_manifest(payload: Any) -> None:
    """契約を**自分でも**守る（本物の `jsonschema` は依存に入れていない）。

    欄・型・`additionalProperties: false` を写してある。**本物での検証は
    `tools/check_contract_p8.py`**（`uv run --no-sync --with jsonschema`）が、
    **実際に取った manifest** で行う。ここを緩めると、契約違反の manifest を
    書いてから気づくことになる（`restore` が読めなくなる）。
    """
    def bad(why: str) -> None:
        raise ReviewError(500, f"manifest が契約に合いません: {why}", code="bad_manifest",
                          details={"why": why})

    if not isinstance(payload, dict):
        bad("object でない")
    need = ("schema", "abi", "app_version", "created_at", "data_dir", "includes", "counts",
            "db_sha256", "db_bytes")
    for key in need:
        if key not in payload:
            bad(f"{key} が無い")
    for key in payload:
        if key not in need:
            bad(f"知らない欄: {key}")
    if payload["schema"] != SCHEMA_ID:
        bad("schema")
    if payload["abi"] != ABI:
        bad("abi")
    if not isinstance(payload["app_version"], str) or not payload["app_version"]:
        bad("app_version")
    if not isinstance(payload["created_at"], str) or not re.match(
            r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$", payload["created_at"]):
        bad("created_at")
    if not isinstance(payload["data_dir"], str) or not payload["data_dir"]:
        bad("data_dir")
    includes = payload["includes"]
    if not isinstance(includes, dict) or set(includes) != {"db", "sidecar", "export", "library"}:
        bad("includes の欄")
    for key, value in includes.items():
        if not isinstance(value, bool):
            bad(f"includes.{key} が真偽値でない")
    counts = payload["counts"]
    if not isinstance(counts, dict) or set(counts) != {
            "assets", "decisions", "groups", "annotations", "tags"}:
        bad("counts の欄")
    for key, value in counts.items():
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            bad(f"counts.{key}")
    if not isinstance(payload["db_sha256"], str) or not re.match(
            r"^sha256:[0-9a-f]{64}$", payload["db_sha256"]):
        bad("db_sha256")
    if not isinstance(payload["db_bytes"], int) or isinstance(payload["db_bytes"], bool) \
            or payload["db_bytes"] < 0:
        bad("db_bytes")


def read_manifest(path) -> dict:
    """`manifest.json` を読んで契約を確かめる（**戻す前**に必ず通る道）。"""
    got = Path(path)
    if not got.is_file():
        raise ReviewError(409, f"manifest.json がありません: {got}", code="bad_manifest",
                          details={"path": str(got)})
    try:
        payload = json.loads(got.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ReviewError(409, f"manifest.json を読めません: {exc}", code="bad_manifest",
                          details={"path": str(got)}) from exc
    validate_manifest(payload)
    return payload


def read_manifest_lenient(path) -> tuple[dict | None, str | None]:
    """読めるなら manifest、駄目なら理由（一覧と `--force` のために落とさない）。"""
    try:
        return read_manifest(path), None
    except ReviewError as exc:
        return None, exc.detail


def snapshot_info(directory: Path) -> dict:
    """1 つのスナップショットの要約（一覧に出す形）。"""
    files, total = dir_size(directory)
    payload, error = read_manifest_lenient(directory / MANIFEST_NAME)
    out = {
        "name": directory.name,
        "dir": str(directory),
        "kind": kind_of_snapshot(directory.name),
        "manual": "-" in directory.name,
        "created_at": None,
        "counts": None,
        "includes": None,
        "db_bytes": None,
        "files": files,
        "bytes": total,
        "ok": payload is not None,
        "error": error,
    }
    if payload is not None:
        out.update(created_at=payload["created_at"], counts=payload["counts"],
                   includes=payload["includes"], db_bytes=payload["db_bytes"])
    return out


def kind_of_snapshot(name: str) -> str:
    """名前から種類を言う（`daily` / `manual` / `pre-migrate` / `other`）。"""
    if name.startswith(PRE_MIGRATE_PREFIX):
        return "pre-migrate"
    if SNAPSHOT_RE.match(name):
        return "manual" if "-" in name else "daily"
    return "other"


def is_our_snapshot(name: str) -> bool:
    """**自分が作った形の名前か**（一覧と掃除の対象を決める 1 か所）。"""
    return bool(SNAPSHOT_RE.match(name)) or name.startswith(PRE_MIGRATE_PREFIX)


def list_snapshots(root) -> list[dict]:
    """置き場にあるスナップショット（**新しい順**）。名前的に並ぶ＝時系列に並ぶ。"""
    base = Path(root)
    if not base.is_dir():
        return []
    out = []
    for entry in sorted(base.iterdir(), key=lambda p: p.name, reverse=True):
        if entry.is_dir() and is_our_snapshot(entry.name):
            out.append(snapshot_info(entry))
    return out


def prune_snapshots(root, keep: int = KEEP_SNAPSHOTS, *, protect=None) -> list[str]:
    """古いスナップショットを消す（**直近 `keep` 個を残す**。設計 §0.12-3）。

    消すのは **`manifest.json` を持つ、日次／「いま取る」の名前のフォルダ**だけ。
    利用者が置いた別の物・`pre-restore-*`（退避した元の DB）・`pre-migrate-*`
    （版を上げる前の控え。§0.12-6）には触らない。
    """
    base = Path(root)
    if not base.is_dir():
        return []
    found = [p for p in sorted(base.iterdir(), key=lambda p: p.name, reverse=True)
             if p.is_dir() and SNAPSHOT_RE.match(p.name) and (p / MANIFEST_NAME).is_file()]
    removed: list[str] = []
    for old in found[keep:]:
        if protect is not None and old.name == protect:
            continue
        try:
            shutil.rmtree(old)
            removed.append(old.name)
        except OSError as exc:                       # 消せなくてもスナップショットは成功
            log.warning("古いスナップショットを消せませんでした: %s (%s)", old, exc)
    return removed


def backup_before_migrate(data_dir, *, backup_dir=None, clock=None,
                          expected_version: int | None = None) -> dict | None:
    """**版を上げる前に控えを取る**（設計 §0.12-6・専門 §5.4）。

    DB の版がバイナリより古いときだけ取る（同じなら `None`）。置き場は
    `<backup_dir>/pre-migrate-<YYYYMMDD>-<HHMMSS>/`（**`<data>` の外**）。
    **掃除の対象にしない**（版が上がるのは稀で、1 つ 1 つが「その版の最後の姿」）。

    **マイグレーションの前に呼ぶ**ので、`Store` を通さない（`Store` を開くと
    その場で版が上がってしまう）。生の接続を 1 本だけ開く。
    """
    clock = clock_of(clock)
    data_dir = Path(data_dir)
    path = data_dir / "db.sqlite3"
    if not path.is_file():
        return None
    con = sqlite3.connect(str(path), timeout=15.0)
    con.row_factory = sqlite3.Row
    try:
        current = con.execute("PRAGMA user_version").fetchone()[0]
        expected = db.SCHEMA_VERSION if expected_version is None else expected_version
        if current >= expected:
            return None
        raw = env_backup_dir()
        if raw is None:
            got = setting_of(con, SETTING_BACKUP_DIR)
            raw = Path(got) if got and str(got).strip() else default_backup_dir()
        root = check_backup_dir(backup_dir if backup_dir is not None else raw, data_dir)
        root.mkdir(parents=True, exist_ok=True)
        stamp = clock.now()
        final = free_dir_name(root, f"{PRE_MIGRATE_PREFIX}{local_day(stamp)}-"
                                    f"{local_hhmmss(stamp)}")
        tmp = root / f".tmp-{final.name}"
        if tmp.exists():
            shutil.rmtree(tmp, ignore_errors=True)
        tmp.mkdir(parents=True)
        out = tmp / "db.sqlite3"
        dst = sqlite3.connect(str(out))
        try:
            con.backup(dst)                          # **online backup API**（WAL を畳む）
            dst.execute("PRAGMA journal_mode = DELETE")
        finally:
            dst.close()
        for suffix in ("-wal", "-shm"):
            (tmp / f"db.sqlite3{suffix}").unlink(missing_ok=True)
        counts = counts_of(out)
        manifest = {
            "schema": SCHEMA_ID, "abi": ABI,
            "app_version": current_app_version(), "created_at": stamp,
            "data_dir": str(data_dir),
            "includes": {"db": True, "sidecar": False, "export": False, "library": False},
            "counts": counts, "db_sha256": "sha256:" + sha256_file(out),
            "db_bytes": int(out.stat().st_size),
        }
        validate_manifest(manifest)
        (tmp / MANIFEST_NAME).write_text(json.dumps(manifest, ensure_ascii=False, indent=1),
                                         encoding="utf-8")
        os.replace(tmp, final)
        return {"dir": str(final), "name": final.name, "from_version": current,
                "to_version": expected, "manifest": manifest, "counts": counts}
    finally:
        con.close()


# ---- コピー（増分）----


def copy_incremental(src: Path, dst: Path, *, previous: Path | None = None) -> dict:
    """フォルダを写す。**前と同じ中身はコピーしない**（設計 §0.12 の「増分」）。

    「前と同じ」の判定は **sha256**（mtime では見ない。バックアップの目的は中身）。
    同じボリュームなら `os.link` で**中身を共有**する（新しいスナップショットは
    単体で読める。前のスナップショットを消しても、リンクが中身を保つ）。
    リンクが張れないとき（別ボリューム・対応しない FS）は写す。
    """
    stats = {"files": 0, "linked": 0, "copied": 0, "bytes": 0, "errors": []}
    if not src.is_dir():
        return stats
    for path in sorted(src.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(src)
        out = dst / rel
        out.parent.mkdir(parents=True, exist_ok=True)
        stats["files"] += 1
        try:
            stats["bytes"] += path.stat().st_size
        except OSError:
            pass
        same = None
        if previous is not None:
            old = previous / rel
            if old.is_file():
                try:
                    if old.stat().st_size == path.stat().st_size and \
                            sha256_file(old) == sha256_file(path):
                        same = old
                except OSError:
                    same = None
        if same is not None:
            try:
                os.link(same, out)                   # 中身を共有する（コピーしない）
                stats["linked"] += 1
                continue
            except OSError:
                pass                                 # 張れなければ写す（黙って諦めない）
        try:
            shutil.copy2(path, out)
            stats["copied"] += 1
        except OSError as exc:
            stats["errors"].append(f"{path}: {exc}")
    return stats


# ---- DB の健全性（設計 §0.12-5・§10-12・§10-13）----


def guidance_for(mode: str, reason: str | None, *, backup_dir=None) -> str | None:
    """その状態のときに画面と CLI に出す案内（**黙って書き込まない**）。"""
    where = f"（バックアップの置き場: {backup_dir}）" if backup_dir else ""
    if mode == "ok":
        return None
    if reason == "version_ahead":
        return ("DB の版がこのアプリより新しいので、読み取り専用で起動しています。"
                "新しいアプリで開くか、バックアップから戻してください: " + RESTORE_HINT + where)
    if reason == "unreadable":
        return ("DB を開けません（ファイルが壊れています）。読み取り専用で起動しています。"
                "バックアップから戻してください: " + RESTORE_HINT + where)
    return ("DB が壊れています。読み取り専用で起動しています（書き込みの口は 503）。"
            "バックアップから戻してください: " + RESTORE_HINT + where)


def inspect_db(data_dir, *, expected_version: int | None = None,
               backup_dir=None) -> dict:
    """起動の前の健全性（設計 §0.12-5・§10-12・§10-13）。

    `mode` は 3 つ:

    - `ok` — そのまま開いてよい（DB が無い＝新規もここ）
    - `read_only` — **壊れている**（2 ページ目を潰した形・300 ページ目を潰した形）か、
      **DB の版がバイナリより新しい**。読み取りは通るので、読み取り専用で起動する
    - `unusable` — **開けない**（先頭 4 KB を潰した形）。読み取りも通らないので、
      健康の口以外は 503 にする

    `quick_check` の**例外も「壊れている」に数える**（点検 B3）。**行が `ok` 1 行でない**
    場合も同じ（実測: 300 ページ目を潰すと例外ではなくエラー行が返る）。
    """
    expected = db.SCHEMA_VERSION if expected_version is None else expected_version
    path = Path(data_dir) / "db.sqlite3"
    out: dict = {
        "path": str(path), "exists": path.exists(), "mode": "ok", "reason": None,
        "quick_check": None, "quick_check_ok": None, "quick_check_rows": [],
        "error": None, "schema_version": None, "expected_version": expected,
        "read_only": False, "guidance": None, "checked_at": db.now(),
    }
    if not path.exists():
        out["reason"] = "fresh"                      # 新規。migrate が作る
        return out
    try:
        con = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True, timeout=5.0)
    except sqlite3.Error as exc:
        return _finish(out, "unusable", "unopenable", error=str(exc), backup_dir=backup_dir)
    try:
        con.row_factory = sqlite3.Row
        got = db.quick_check(con)
        out["quick_check"] = got["detail"]
        out["quick_check_ok"] = got["ok"]
        out["quick_check_rows"] = got["rows"]
        out["error"] = got["error"]
        if backup_dir is None:
            # 案内に出す置き場（**設定も見る**。env → 設定 → 既定）
            try:
                raw = env_backup_dir()
                if raw is None:
                    got_setting = setting_of(con, SETTING_BACKUP_DIR)
                    raw = Path(got_setting) if got_setting and str(got_setting).strip() \
                        else default_backup_dir()
                backup_dir = raw
            except sqlite3.Error:
                backup_dir = default_backup_dir()
        version = None
        readable = True
        try:
            con.execute("SELECT count(*) FROM sqlite_master").fetchone()
            version = con.execute("PRAGMA user_version").fetchone()[0]
        except sqlite3.DatabaseError as exc:         # 先頭 4 KB を潰した形
            readable = False
            out["error"] = out["error"] or str(exc)
        out["schema_version"] = version
        if not readable:
            return _finish(out, "unusable", "unreadable", backup_dir=backup_dir)
        if not got["ok"]:
            return _finish(out, "read_only", "malformed", backup_dir=backup_dir)
        if version is not None and version > expected:
            return _finish(out, "read_only", "version_ahead", backup_dir=backup_dir)
        return _finish(out, "ok", "ok", backup_dir=backup_dir)
    finally:
        con.close()


def _finish(out: dict, mode: str, reason: str, *, error: str | None = None,
            backup_dir=None) -> dict:
    out["mode"] = mode
    out["reason"] = reason
    out["read_only"] = mode != "ok"
    if error:
        out["error"] = error
    out["guidance"] = guidance_for(mode, reason, backup_dir=backup_dir)
    return out


def check_db_file(path, *, full: bool = False) -> dict:
    """1 つの DB ファイルの健全性（**復元の前後**に使う。設計 §0.12-5）。

    `full=True` は `integrity_check`（重い。復元の後だけ）。
    """
    got = Path(path)
    if not got.is_file():
        return {"ok": False, "detail": f"ファイルがありません: {got}", "error": "missing"}
    try:
        con = sqlite3.connect(f"file:{got.as_posix()}?mode=ro", uri=True, timeout=15.0)
    except sqlite3.Error as exc:
        return {"ok": False, "detail": str(exc), "error": str(exc)}
    try:
        if full:
            try:
                rows = [str(row[0]) for row in con.execute("PRAGMA integrity_check").fetchall()]
            except sqlite3.DatabaseError as exc:
                return {"ok": False, "detail": str(exc), "error": str(exc)}
            return {"ok": rows == ["ok"], "detail": rows[0] if rows else "(行が返らない)",
                    "error": None}
        return db.quick_check(con)
    finally:
        con.close()


def _count(con: sqlite3.Connection, table: str) -> int:
    """表の行数（**無い表は 0**。契約は 5 つの数を要求する）。"""
    try:
        return int(con.execute(f"SELECT count(*) AS n FROM {table}").fetchone()["n"])
    except sqlite3.Error:
        return 0


def counts_of(db_path) -> dict:
    """スナップショットの中の数（**人が復元の前に見る数**。契約 §6.2）。"""
    con = sqlite3.connect(f"file:{Path(db_path).as_posix()}?mode=ro", uri=True, timeout=15.0)
    con.row_factory = sqlite3.Row
    try:
        return {
            "assets": _count(con, "asset"),
            "decisions": _count(con, "decision"),
            "groups": _count(con, "review_group"),
            "annotations": _count(con, "annotation"),
            "tags": _count(con, "tag"),
        }
    finally:
        con.close()


def current_app_version() -> str:
    """このアプリの版（`manifest.json` に書く）。"""
    from . import __version__

    return str(__version__)


# ---- サービス（日次と「いま取る」）----


class BackupService:
    """日次スナップショットと「いま取る」（設計 §0.12・§3.3）。

    操作は `self._lock` で直列化する（同じ瞬間に 2 本走らせない）。**DB の写しは
    `store.locked()` の下で online backup API**（`-wal` / `-shm` を単独でコピーしない）。
    ファイルの写しは取引の外（家風）。
    """

    def __init__(self, store, *, clock=None, interval: float = TICK_INTERVAL_SEC,
                 backup_dir=None, app_version: str | None = None):
        self.store = store
        self.clock = clock_of(clock)
        self.data_dir = Path(store.data_dir)
        self.interval = float(interval)
        self.app_version = app_version or current_app_version()
        self._forced_dir = Path(backup_dir) if backup_dir else None
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._ticks = 0
        self._last: dict | None = None

    # ---- 置き場 ----

    def backup_dir(self) -> Path:
        """いまの置き場（テストと画面のために 1 か所で決める）。"""
        if self._forced_dir is not None:
            return self._forced_dir
        return resolve_backup_dir(self.store)[0]

    def backup_dir_source(self) -> str:
        if self._forced_dir is not None:
            return "forced"
        return resolve_backup_dir(self.store)[1]

    # ---- 設定（`GET` / `PATCH /api/settings`）----

    def settings(self) -> dict:
        """いまの設定（**読むだけ**）。"""
        return settings_state(self.store)

    def set_dir(self, value, *, actor: str = "human") -> dict:
        """置き場を変える（**人だけ**）。`<data>` の中は断る（`422 bad_backup_dir`）。"""
        return set_backup_dir(self.store, value, actor=actor)

    # ---- タイマー（30 秒周期。**起動時にも 1 回見る**）----

    def start(self) -> None:
        """タイマーを張る。**起動した直後に 1 回見る**（設計 §0.12-1。点検 B2）。

        `DeletionService.start()` と違って**起動時にも仕事をする**（日次は「起動した日に
        1 回取る」のが目的なので、1 周期待つと「すぐ閉じる使い方」で取れない）。
        壊れた DB（読み取り専用）のときは何もしない（`tick` が断る）。
        """
        if self.store.read_only:
            log.warning("DB が壊れているのでバックアップのタイマーは張りません")
            return
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="backup-timer", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        """タイマーを止める（**2 回呼んでも安全**）。"""
        self._stop.set()
        thread, self._thread = self._thread, None
        if thread is not None:
            thread.join(timeout=2.0)

    def _loop(self) -> None:
        while True:
            try:
                self.tick()
            except Exception:                                    # noqa: BLE001
                log.exception("バックアップのタイマーで失敗しました（次の周期でやり直します）")
            if self._stop.wait(self.interval):
                return

    def tick(self) -> dict:
        """1 周期分: **今日（JST）のフォルダが無ければ取る**。**失敗は `last_error` に残す**。

        同じ日なら何もしない（設計 §0.12-1）。「いま取る」は `snapshot(manual=True)` で、
        こちらは**同じ日でも必ず新しく取る**（点検 B2）。
        """
        with self._lock:
            self._ticks += 1
            if self.store.read_only:
                return {"ticks": self._ticks, "skipped": "read_only", "taken": None,
                        "error": None}
            try:
                root = self.backup_dir()
                day = local_day(self.clock.now())
            except ReviewError as exc:                # 置き場の設定が壊れている
                return self._failed(exc, ticks=self._ticks)
            if (root / day).is_dir():
                return {"ticks": self._ticks, "skipped": "already", "day": day,
                        "taken": None, "error": None}
            try:
                taken = self.snapshot(manual=False)
            except Exception as exc:                             # noqa: BLE001
                return self._failed(exc, ticks=self._ticks)
            return {"ticks": self._ticks, "skipped": None, "day": day, "taken": taken,
                    "error": None}

    def _failed(self, exc: Exception, *, ticks: int) -> dict:
        """失敗を残す（**黙って失敗しない**。設計 §0.12 の 6）。"""
        message = exc.detail if isinstance(exc, ReviewError) else str(exc)
        self._record_error(message)
        log.warning("バックアップに失敗しました: %s", message)
        return {"ticks": ticks, "skipped": "failed", "taken": None, "error": message}

    # ---- 取る ----

    def snapshot(self, *, manual: bool = False, out=None, include_library: bool = False) -> dict:
        """1 回取る。

        - 自動: `<backup_dir>/<YYYYMMDD>/`（同じ日なら**呼ぶ側が**取らない）
        - 「いま取る」: `<backup_dir>/<YYYYMMDD>-<HHMMSS>/`（**必ず新しい**。点検 B2）
        - `out` を渡すとそこへ取る（CLI の `--out`）。**`<data>` の中は断る。**
        - **一時フォルダに作って `os.replace`**（書きかけを置かない）
        """
        with self._lock:
            if self.store.read_only:
                raise ReviewError(503, "DB が壊れているのでバックアップを取れません",
                                  code="read_only")
            target = check_backup_dir(out if out is not None else self.backup_dir(),
                                      self.data_dir)
            target.mkdir(parents=True, exist_ok=True)
            stamp = self.clock.now()
            name = (f"{local_day(stamp)}-{local_hhmmss(stamp)}" if manual else local_day(stamp))
            final = free_dir_name(target, name)
            tmp = target / f".tmp-{final.name}"
            if tmp.exists():
                shutil.rmtree(tmp, ignore_errors=True)
            tmp.mkdir(parents=True)
            previous = self._previous_snapshot(target, skip=final)
            try:
                got = self._write_snapshot(tmp, stamp=stamp, manual=manual,
                                           include_library=include_library, previous=previous)
                os.replace(tmp, final)               # 名前の付け替え（一瞬。書きかけを見せない）
            except BaseException:
                shutil.rmtree(tmp, ignore_errors=True)
                raise
            pruned = prune_snapshots(target, KEEP_SNAPSHOTS, protect=final.name)
            self._clear_error()
            self._remember_ok(stamp)
            got.update(dir=str(final), name=final.name, manual=manual, pruned=pruned,
                       backup_dir=str(target))
            self._last = got
            return got

    def _previous_snapshot(self, target: Path, *, skip: Path) -> Path | None:
        """増分の相手（**いちばん新しい、今作っている物以外**）。

        **日次と「いま取る」だけ**を相手にする（`pre-migrate-*` は DB しか持たないので、
        相手にすると sidecar / export の共有が効かない）。
        """
        for info in list_snapshots(target):
            if info["name"] != skip.name and info["kind"] in ("daily", "manual"):
                return Path(info["dir"])
        return None

    def _write_snapshot(self, tmp: Path, *, stamp: str, manual: bool,
                        include_library: bool, previous: Path | None) -> dict:
        """一時フォルダの中身を作る（DB → sidecar/export → settings → manifest）。"""
        db_out = tmp / "db.sqlite3"
        with self.store.locked():
            dst = sqlite3.connect(str(db_out))
            try:
                # **online backup API。** `-wal` を単独でコピーすると判断が抜ける
                # （P4-0 の監査 D-1 の教訓。実データの WAL は 4 MB あった）
                self.store.con.backup(dst)
                # **写しは 1 ファイルで完結させる。** online backup は元のヘッダ
                # （WAL モードの印）ごと写すので、そのままだと写しの隣に `-wal` / `-shm` が
                # 生える（実測: probe で `db.sqlite3-wal` が出来ていた）。**戻すときに
                # `-wal` を別扱いしなくて済む**ように、ここで巻き戻しジャーナルへ変える
                dst.execute("PRAGMA journal_mode = DELETE")
            finally:
                dst.close()
        for suffix in ("-wal", "-shm"):                   # 取り残しも消す（写しは 1 ファイル）
            (tmp / f"db.sqlite3{suffix}").unlink(missing_ok=True)
        db_bytes = db_out.stat().st_size
        db_digest = "sha256:" + sha256_file(db_out)

        includes = {"db": True, "sidecar": False, "export": False, "library": False}
        files = {"files": 0, "linked": 0, "copied": 0, "bytes": 0, "errors": []}
        for sub in COPY_DIRS:
            src = self.data_dir / sub
            if not src.is_dir():
                continue
            got = copy_incremental(src, tmp / sub,
                                   previous=(previous / sub) if previous else None)
            includes[sub] = True
            for key in ("files", "linked", "copied", "bytes"):
                files[key] += got[key]
            files["errors"].extend(got["errors"])

        settings = self._settings_rows()
        (tmp / SETTINGS_NAME).write_text(
            json.dumps({"schema": "urn:image-reviewer:settings", "abi": ABI,
                        "settings": settings}, ensure_ascii=False, indent=1),
            encoding="utf-8")

        library = {"files": 0, "copied": 0, "bytes": 0, "missing": 0, "errors": []}
        if include_library:
            library = self._copy_library(tmp / LIBRARY_DIR)
            includes["library"] = library["files"] > 0

        counts = counts_of(db_out)
        manifest = {
            "schema": SCHEMA_ID,
            "abi": ABI,
            "app_version": self.app_version,
            "created_at": stamp,
            "data_dir": str(self.data_dir),
            "includes": includes,
            "counts": counts,
            "db_sha256": db_digest,
            "db_bytes": int(db_bytes),
        }
        validate_manifest(manifest)
        (tmp / MANIFEST_NAME).write_text(
            json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")
        return {"created_at": stamp, "manifest": manifest, "counts": counts,
                "files": files, "library": library, "settings": len(settings),
                "db_bytes": int(db_bytes), "db_sha256": db_digest}

    def _settings_rows(self) -> dict:
        with self.store.locked() as con:
            return {row["key"]: row["value"]
                    for row in con.execute("SELECT key, value FROM settings ORDER BY key")}

    def _copy_library(self, out_dir: Path) -> dict:
        """画像の実体を控える（`--include-library` のときだけ。**読むだけ**）。

        置き場は `<sha256 の先頭 2 文字>/<sha256><拡張子>`（内容が名前。同じ画像を 2 か所に
        置いていても 1 つで足りる）。**戻すときは、記録した場所に無いときだけ**置く。
        """
        stats = {"files": 0, "copied": 0, "bytes": 0, "missing": 0, "errors": []}
        with self.store.locked() as con:
            rows = con.execute(
                "SELECT a.sha256 AS sha256, l.display_path AS path"
                " FROM asset a JOIN asset_location l ON l.asset_id = a.id"
                " WHERE l.missing_at IS NULL AND a.deleted_at IS NULL"
                " ORDER BY a.sha256").fetchall()
        seen: set[str] = set()
        for row in rows:
            sha = row["sha256"]
            if sha in seen:
                continue
            seen.add(sha)
            src = Path(row["path"])
            if not src.is_file():
                stats["missing"] += 1
                continue
            ext = src.suffix.lower() or ".bin"
            out = out_dir / sha[:2] / f"{sha}{ext}"
            out.parent.mkdir(parents=True, exist_ok=True)
            try:
                shutil.copy2(src, out)
            except OSError as exc:
                stats["errors"].append(f"{src}: {exc}")
                continue
            stats["files"] += 1
            stats["copied"] += 1
            stats["bytes"] += out.stat().st_size
        return stats

    # ---- 失敗の記録（黙って捨てない）----

    def _record_error(self, message: str) -> None:
        try:
            with self.store.transaction() as con:
                self._put(con, SETTING_LAST_ERROR, message)
                self._put(con, SETTING_LAST_ERROR_AT, self.clock.now())
        except Exception:                                        # noqa: BLE001
            log.exception("バックアップの失敗を記録できませんでした（DB にも書けません）")

    def _clear_error(self) -> None:
        try:
            with self.store.transaction() as con:
                con.execute("DELETE FROM settings WHERE key IN (?, ?)",
                            (SETTING_LAST_ERROR, SETTING_LAST_ERROR_AT))
        except Exception:                                        # noqa: BLE001
            log.exception("バックアップの失敗の記録を消せませんでした")

    def _remember_ok(self, stamp: str) -> None:
        try:
            with self.store.transaction() as con:
                self._put(con, SETTING_LAST_OK_AT, stamp)
        except Exception:                                        # noqa: BLE001
            log.exception("バックアップの時刻を記録できませんでした")

    @staticmethod
    def _put(con: sqlite3.Connection, key: str, value: str) -> None:
        con.execute("INSERT INTO settings(key, value) VALUES (?, ?)"
                    " ON CONFLICT(key) DO UPDATE SET value = excluded.value", (key, value))

    # ---- 状態（`GET /api/backup`）----

    def state(self) -> dict:
        """置き場・一覧・最後に取った時刻・次に取る予定・最後の失敗（§3.3）。**読むだけ**。"""
        with self._lock:
            root = self.backup_dir()
            snaps = list_snapshots(root)
            last = snaps[0] if snaps else None
            stamp = self.clock.now()
            day = local_day(stamp)
            with self.store.locked() as con:
                last_error = setting_of(con, SETTING_LAST_ERROR)
                last_error_at = setting_of(con, SETTING_LAST_ERROR_AT)
                last_ok_at = setting_of(con, SETTING_LAST_OK_AT)
            if last is not None and last["created_at"]:
                last_ok_at = last["created_at"]
            today_done = (root / day).is_dir()
            return {
                "backup_dir": str(root),
                "backup_dir_source": self.backup_dir_source(),
                "default_backup_dir": str(default_backup_dir()),
                "keep": KEEP_SNAPSHOTS,
                "interval_sec": self.interval,
                "snapshots": snaps,
                "count": len(snaps),
                "last": last,
                "last_at": last_ok_at,
                "today_done": today_done,
                "next_run_at": next_local_midnight(stamp) if today_done
                else plus_seconds(stamp, int(self.interval)),
                "next_run_note": ("今日の分は取りました（次は日付が変わったとき）" if today_done
                                  else "今日の分はまだです（30 秒ごとに見ています）"),
                "last_error": last_error,
                "last_error_at": last_error_at,
                "read_only": self.store.read_only,
                "running": bool(self._thread is not None and self._thread.is_alive()),
                "ticks": self._ticks,
                "last_result": self._last,
            }


# ---- 復元（CLI が主。設計 §0.15 の 2・点検 G8）----


def restore(data_dir, snapshot_dir, *, force: bool = False, clock=None,
            backup_dir=None) -> dict:
    """バックアップから戻す（設計 §0.12-4・専門 §5.3）。

    順序（**この順でしか戻さない**）:

    1. `manifest.json` を読んで**契約を確かめ、版と件数を出す**
    2. **戻す前に `quick_check`**（写しの DB が壊れていたら採用しない）
    3. **いまの DB を退避**（`<backup_dir>/pre-restore-<時刻>/`。**`<data>` の外**）
    4. 置き換え（`-wal` / `-shm` は消す。**写しはそのまま残す**）
    5. **`integrity_check`**（通らなければ**元に戻す**）
    6. `sidecar/` と `export/` を戻す

    `force=True` は「manifest が読めない」「写しの DB が `quick_check` に通らない」を
    **承知の上で進む**（既定は断る。危ない側の既定にしない）。
    """
    clock = clock_of(clock)
    data_dir = Path(data_dir)
    snap = Path(snapshot_dir)
    if not snap.is_dir():
        raise ReviewError(422, f"バックアップのフォルダがありません: {snap}",
                          code="no_snapshot", details={"dir": str(snap)})
    manifest = None
    man_error = None
    try:
        manifest = read_manifest(snap / MANIFEST_NAME)
    except ReviewError as exc:
        man_error = exc.detail
        if not force:
            raise ReviewError(409, f"{exc.detail}（--force で続けます）", code="bad_manifest",
                              details={"dir": str(snap)}) from exc
    src_db = snap / "db.sqlite3"
    if not src_db.is_file():
        raise ReviewError(409, f"バックアップに db.sqlite3 がありません: {snap}",
                          code="bad_backup", details={"dir": str(snap)})

    before = check_db_file(src_db)                     # 2. 戻す前の quick_check
    if not before["ok"] and not force:
        raise ReviewError(409, "バックアップの DB が壊れています（--force で続けます）",
                          code="bad_backup",
                          details={"dir": str(snap), "detail": before["detail"]})

    stamp = clock.now()
    setaside = None
    target_db = data_dir / "db.sqlite3"
    if target_db.exists():                             # 3. 元の DB を退避
        root = Path(backup_dir) if backup_dir else snap.parent
        root.mkdir(parents=True, exist_ok=True)
        setaside = free_dir_name(root, f"{RESTORE_KEEP_PREFIX}{local_day(stamp)}-"
                                       f"{local_hhmmss(stamp)}")
        setaside.mkdir(parents=True)
        for suffix in ("", "-wal", "-shm"):
            old = data_dir / f"db.sqlite3{suffix}"
            if old.exists():
                shutil.copy2(old, setaside / old.name)

    for suffix in ("-wal", "-shm"):                    # 4. 置き換え（古い WAL を残さない）
        stale = data_dir / f"db.sqlite3{suffix}"
        if stale.exists():
            stale.unlink()
    data_dir.mkdir(parents=True, exist_ok=True)
    try:
        shutil.copy2(src_db, target_db)                # 写しはそのまま残す（読むだけ）
    except OSError as exc:
        # **アプリが動いていると Windows は置き換えさせない**（掴んでいる）。
        # 500 にせず、人が読める 1 行で返す（設計 §3.4 の流儀）
        raise ReviewError(409, "DB を置き換えられません（アプリを止めてから戻してください）: "
                              f"{exc}", code="restore_failed",
                          details={"data_dir": str(data_dir), "from": str(src_db)}) from exc

    after = check_db_file(target_db, full=True)        # 5. 戻した後の integrity_check
    if not after["ok"]:
        if setaside is not None:                       # 元に戻す
            for suffix in ("", "-wal", "-shm"):
                old = setaside / f"db.sqlite3{suffix}"
                if old.exists():
                    shutil.copy2(old, data_dir / old.name)
        else:
            target_db.unlink(missing_ok=True)
        raise ReviewError(409, "戻した DB が integrity_check を通りません（元に戻しました）",
                          code="restore_failed",
                          details={"dir": str(snap), "detail": after["detail"],
                                   "setaside": str(setaside) if setaside else None})

    copied: dict[str, dict] = {}
    for sub in COPY_DIRS:                              # 6. sidecar / export を戻す
        src = snap / sub
        if src.is_dir():
            copied[sub] = copy_incremental(src, data_dir / sub)

    library = {"restored": 0, "kept": 0, "missing": 0}
    if (snap / LIBRARY_DIR).is_dir() and manifest is not None:
        library = _restore_library(snap / LIBRARY_DIR, data_dir)

    return {
        "dir": str(snap),
        "data_dir": str(data_dir),
        "manifest": manifest,
        "manifest_error": man_error,
        "forced": bool(force),
        "counts": (manifest or {}).get("counts") or counts_of(target_db),
        "before": before,
        "after": after,
        "setaside": str(setaside) if setaside else None,
        "copied": copied,
        "library": library,
        "restored_at": stamp,
    }


def _restore_library(library_dir: Path, data_dir: Path) -> dict:
    """画像の実体を戻す（**記録した場所に無いときだけ**。**上書きしない**）。

    画像は利用者の資産なので、**在る物には触らない**（戻すのは「消えた物」だけ）。
    """
    stats = {"restored": 0, "kept": 0, "missing": 0}
    db_path = data_dir / "db.sqlite3"
    if not db_path.is_file():
        return stats
    con = sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    try:
        rows = con.execute(
            "SELECT a.sha256 AS sha256, l.display_path AS path"
            " FROM asset a JOIN asset_location l ON l.asset_id = a.id"
            " WHERE a.deleted_at IS NULL ORDER BY a.sha256").fetchall()
    finally:
        con.close()
    seen: set[str] = set()
    for row in rows:
        sha, path = row["sha256"], Path(row["path"])
        if sha in seen:
            continue
        seen.add(sha)
        if path.exists():
            stats["kept"] += 1
            continue
        found = list((library_dir / sha[:2]).glob(f"{sha}.*")) if (library_dir / sha[:2]).is_dir() \
            else []
        if not found:
            stats["missing"] += 1
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(found[0], path)
        stats["restored"] += 1
    return stats


# ---- 来歴の組み直し（設計 §0.12-4。専門 §5.2 の 4）----

#: sidecar から `meta` へ写す鍵（**捕獲した英訳は PNG から取り直せない**。専門 §5.1）
SIDECAR_KEYS = ("en_text", "final_prompt", "ja_text", "textgen_params",
                "textgen_system_prompt", "prompt_id", "captured_from_node", "captured_at",
                "concat_prefix", "concat_delimiter")


def _read_sidecar(sidecar_dir: Path, sha256: str) -> dict | None:
    path = Path(sidecar_dir) / f"{sha256}.json"
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return payload if isinstance(payload, dict) else None


def rebuild_metadata(store, *, sidecar_dir=None, png_reader: Callable | None = None) -> dict:
    """PNG と sidecar から来歴を組み直す（設計 §0.12-4）。

    - **`<data>/sidecar/<sha256>.json` を先に見る**（捕獲した英訳は PNG から取り直せない）
    - 次に PNG の `prompt` チャンク（`png_meta.provenance`）を見る
    - **DB にある値は上書きしない**（正は DB、sidecar は組み直しの種。専門 §5.6）。
      **空いている欄だけ**を埋める（`None` / `""` / `[]` / `{}` は空とみなす）
    - 埋めた印を残す（`en_source = "sidecar"` / `en_is_rederived = 1`）
    """
    reader = png_reader or png_meta.provenance
    side_dir = Path(sidecar_dir) if sidecar_dir else Path(store.data_dir) / "sidecar"
    stats = {"assets": 0, "updated": 0, "unchanged": 0, "from_sidecar": 0, "from_png": 0,
             "missing_files": 0, "no_source": 0, "sidecars": 0, "notes": []}
    with store.locked() as con:
        rows = con.execute("SELECT id, sha256, format FROM asset ORDER BY id").fetchall()
    for row in rows:
        stats["assets"] += 1
        asset = store.asset(row["id"])
        if asset is None:
            continue
        meta = dict(asset.get("meta") or {})
        filled: list[str] = []

        side = _read_sidecar(side_dir, row["sha256"])
        if side is not None:
            stats["sidecars"] += 1
            source: dict = {}
            for key in SIDECAR_KEYS:
                if side.get(key) is not None:
                    source[key] = side[key]
            if isinstance(side.get("meta"), dict):
                for key, value in side["meta"].items():
                    source.setdefault(key, value)
            if source.get("en_text") and _absent(meta.get("en_text")):
                source["en_source"] = "sidecar"
                source["en_is_rederived"] = 1
            if side.get("llm") and _absent(meta.get("en_engine")):
                source["en_engine"] = side["llm"]
            for key, value in source.items():
                if _absent(meta.get(key)) and not _absent(value):
                    meta[key] = value
                    filled.append(key)
            if filled:
                stats["from_sidecar"] += 1

        location = _primary_live_location(asset)
        if location is None:
            stats["missing_files"] += 1
        else:
            path = Path(location["display_path"])
            if not path.is_file():
                stats["missing_files"] += 1
            else:
                try:
                    got = reader(str(path))
                except Exception as exc:                     # noqa: BLE001  1 枚で止めない
                    got = {"info": None, "note": f"PNG を読めない: {exc}"}
                info = got.get("info") if isinstance(got, dict) else None
                if isinstance(info, dict):
                    for key, value in info.items():
                        if _absent(meta.get(key)) and not _absent(value):
                            meta[key] = value
                            filled.append(key)
                    if filled:
                        stats["from_png"] += 1
                else:
                    stats["no_source"] += 1
                    note = (got or {}).get("note") if isinstance(got, dict) else None
                    if note:
                        stats["notes"].append(f"{path.name}: {note}")

        if filled:
            store.set_meta(row["id"], meta)
            stats["updated"] += 1
        else:
            stats["unchanged"] += 1
    return stats


def _primary_live_location(asset: dict) -> dict | None:
    """生きている場所の代表（**消えた物・参照切れは使わない**）。"""
    locs = [loc for loc in asset.get("locations") or [] if not loc.get("missing_at")]
    if not locs:
        return None
    locs.sort(key=lambda loc: (not loc.get("is_primary"), loc.get("path") or ""))
    return locs[0]


def _absent(value) -> bool:
    """「値が無い」の判定（`0` と `False` は**値がある**として扱う。`cli.py` と同じ規則）。"""
    return value is None or value == "" or value == [] or value == {}


# ---- 設定（`backup_dir` を変える口。設計 §3.3・§0.15 の 14）----


def settings_state(store) -> dict:
    """設定の口が返す物（いまは `backup_dir` だけ。**読むだけ**）。"""
    current, source = resolve_backup_dir(store)
    return {
        "backup_dir": str(current),
        "backup_dir_source": source,
        "default_backup_dir": str(default_backup_dir()),
        "env_backup_dir": str(env_backup_dir()) if env_backup_dir() else None,
    }


def set_backup_dir(store, value, *, actor: str = "human") -> dict:
    """`backup_dir` を変える（**人だけ**。`<data>` の中は断る）。

    **設計 §3.3 は「既存の口（`PATCH /api/settings`）に足す」と書いているが、
    その口は実装に無かった**（P8-4 で作った。記録の「設計の穴」1）。
    """
    if actor != "human":
        raise ReviewError(403, "バックアップの置き場の変更は人だけができます",
                          code="human_only", details={"actor": actor})
    if not isinstance(value, str) or not value.strip():
        raise ReviewError(422, "backup_dir は空でない文字列です", code="bad_backup_dir",
                          details={"backup_dir": value})
    path = check_backup_dir(value.strip(), store.data_dir)
    with store.transaction() as con:
        con.execute("INSERT INTO settings(key, value) VALUES (?, ?)"
                    " ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                    (SETTING_BACKUP_DIR, str(path)))
    return settings_state(store)


__all__ = [
    "ABI", "BackupService", "COPY_DIRS", "DEFAULT_BACKUP_DIRNAME", "ENV_BACKUP_DIR",
    "JST_OFFSET_SEC", "KEEP_SNAPSHOTS", "LIBRARY_DIR", "MANIFEST_NAME",
    "PRE_MIGRATE_PREFIX", "RESTORE_HINT", "RESTORE_KEEP_PREFIX", "SCHEMA_ID",
    "SETTINGS_NAME", "TICK_INTERVAL_SEC", "backup_before_migrate", "check_backup_dir",
    "check_db_file", "copy_incremental", "counts_of", "current_app_version",
    "default_backup_dir", "dir_size", "env_backup_dir", "free_dir_name", "guidance_for",
    "inspect_db", "is_our_snapshot", "kind_of_snapshot", "list_snapshots", "local_day",
    "local_hhmmss", "next_local_midnight", "plus_seconds", "prune_snapshots",
    "read_manifest", "read_manifest_lenient", "rebuild_metadata", "resolve_backup_dir",
    "restore", "set_backup_dir", "setting_of", "settings_state", "sha256_file",
    "snapshot_info", "validate_manifest",
]
