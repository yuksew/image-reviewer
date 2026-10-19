"""コマンド。

使い方:
  uv run image-reviewer scan --root C:\\path\\to\\images
  uv run image-reviewer capture --base-url http://127.0.0.1:8188
  uv run image-reviewer serve --port 8790
  uv run image-reviewer migrate-from-json        # .data/store.json を SQLite へ取り込む
  uv run image-reviewer backup --out D:\\backups  # いま 1 回取る（P8-4）
  uv run image-reviewer restore D:\\backups\\20261018
  uv run image-reviewer rebuild-metadata         # PNG と sidecar から来歴を組み直す

どのコマンドでも、`_store()` が `app.data_dir` を読み、そのあと**起動時の書き出し**
（DB の印で拾う。監査 A1）を明示的に走らせる。以前は `app` モジュールの読み込み
（`create_app()`）がその役を兼ねていたが、読み込みの順序に依存していた（監査 C1）。
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from . import db, reasons
from .review import ReviewError
from .scan import scan
from .store import Store, normalize_path

# 監査 B1: 取り込みで書く台帳の行の注記（「なぜ写しが非 unreviewed なのか」をここで説明する）
MIGRATED_NOTE = "store.json から取り込み"


class JaHelpFormatter(argparse.HelpFormatter):
    """`--help` の骨組みを日本語にする（**C-19・G-5**。監査の推奨を採用）。

    argparse の既定は英語（`usage:` / `positional arguments:` / `options:` /
    `show this help message and exit`）。利用者が打つ CLI は `scan` と `serve` だけなので、
    ここで差し替える（数行で済む）。
    """

    def add_usage(self, usage, actions, groups, prefix=None):  # noqa: ANN001
        super().add_usage(usage, actions, groups,
                          prefix if prefix is not None else "使い方: ")


class JaArgumentParser(argparse.ArgumentParser):
    """見出しを「コマンド」「オプション」にし、`-h` の 1 行も日本語にする。"""

    def __init__(self, *args, **kwargs):  # noqa: ANN002, ANN003
        kwargs.setdefault("formatter_class", JaHelpFormatter)
        kwargs.setdefault("add_help", False)
        super().__init__(*args, **kwargs)
        self._positionals.title = "コマンド"
        self._optionals.title = "オプション"
        self.add_argument("-h", "--help", action="help",
                          help="この使い方を表示して終了する")


def _when(iso: str | None) -> str:
    """**画面と同じ現地の 1 形式**（`2026-10-19 02:31`）にする（**A-1・G-7**）。

    台帳と manifest は UTC の ISO で持っている（`db.now()`）。CLI だけ UTC を出していたので、
    同じ 1 回のバックアップが画面と CLI で別の時刻に見えていた。
    """
    if not iso:
        return "—"
    try:
        at = datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
    except ValueError:
        return str(iso)
    if at.tzinfo is None:
        at = at.replace(tzinfo=timezone.utc)
    return at.astimezone().strftime("%Y-%m-%d %H:%M")


def _bytes(n) -> str:  # noqa: ANN001
    """**画面と同じ容量の書き方**（KB は整数、MB は小数 1 桁。**A-2・規則 1**）。

    前は「DB 3428.0 KB」と KB に小数を付けていた（画面は「3.4 MB」）。
    """
    size = int(n or 0)
    if size < 1024:
        return f"{size} B"
    if size < 1024 * 1024:
        return f"{size // 1024} KB"
    return f"{size / 1048576:.1f} MB"


def _store(*, flush: bool = True):
    """`data_dir()` を読み、**起動時の書き出し**を明示的に走らせる（監査 A1・C1）。

    以前は `app` モジュールの読み込み（`create_app()`）がその役を兼ねていたが、
    同じプロセスで 2 回目以降は読み込みが走らないので、**読み込みの順序に依存していた**
    （P5-2 の API
    テストが先に `create_app()` を読み込むと、CLI 側の書き出しが漏れる）。
    ここで明示的に呼べば順序に依らない。印の無い DB では `flush_dirty()` は何もしない。

    **P8-4**: 版が古ければ、`Store` を開く（＝マイグレーションが走る）**前に控えを取る**
    （設計 §0.12-6）。取れなければ `ReviewError` を投げる（`main()` が 2 で返す）。
    """
    from .app import data_dir
    from .backup import backup_before_migrate, inspect_db
    from .review import ReviewError

    state = inspect_db(data_dir())
    if state["mode"] != "ok":
        raise ReviewError(503, state["guidance"] or "DB が壊れています", code="read_only")
    if state["schema_version"] and state["schema_version"] < db.SCHEMA_VERSION:
        backup_before_migrate(data_dir())

    store = Store(data_dir())
    if flush:
        from .export import ExportService

        exporter = ExportService(store, flush_on_start=False)
        try:
            exporter.flush_dirty()
        finally:
            exporter.close()
    return store


def cmd_scan(args) -> int:
    from .deletions import DeletionService  # noqa: PLC0415  走査と削除を同じ錠で直列化する

    store = _store()
    try:
        roots = args.root or store.roots() or []
        if not roots:
            print("--root を指定してください（初回は必須です）。", file=sys.stderr)
            return 2
        # P8-2（G-2・C-6）: サーバと同じ錠を取る（同じプロセスで走査と削除が重ならないように）。
        # **プロセスをまたぐ錠ではない**ので、走査中に別プロセスのサーバが消すことは防げない
        # （それは SQLite の取引が守る）
        guard = DeletionService(store)
        with guard.scan_guard():
            stats = scan(store, roots,
                         on_progress=lambda s: print(f"  ... {s['images']} 枚", flush=True))
        # **（A-14・C-18）** 「/」で 6 組を並べる形をやめ、**何を数えたかが読める文**にする
        # （「画像 0」と「既知 299」が同じ行にあり、「画像」が何を数えているか分からなかった）
        print(f"走査しました: {stats['seen']} 件を見て、新しく読んだ {stats['created']}、"
              f"登録済み {stats['known']}、入れ替わり {stats['changed']}、"
              f"画像でない {stats['not_image']}。"
              f"来歴あり {stats['with_provenance']}、参照切れにした {stats['missing']}。")
        for err in stats["errors"][:10]:
            print(f"  エラー: {err}", file=sys.stderr)
        return 0
    finally:
        # 接続を閉じる（`cmd_migrate_from_json` と同じ形）。開いたままだと、同じ
        # プロセスで後始末する側（テストなど）が `db.sqlite3` を消せない
        store.close()


def cmd_capture(args) -> int:
    from .capture import capture_history
    from .scan import scan  # noqa: F401  (未使用だが、走査済みであることを意識させる)

    store = _store()
    try:
        stats = capture_history(store, args.base_url)
        if stats["error"]:
            print(stats["error"], file=sys.stderr)
            return 2
        # **（ワーディング監査 C-3）** 端末の出力は敬体に揃える（同じ CLI の他の行と同じ）
        # **（D-4）** 「捕獲」→「取り込む」（`design.md` §17 の画面の語）
        print(f"/history を {stats['history_entries']} 件見ました。")
        print(f"訳が未取得の画像 {stats['checked']} 枚のうち {stats['captured']} 枚で訳を取り込みました。")
        print(f"  実行が見つからない {stats['no_history']} / ja2en でない {stats['not_textgen']} / "
              f"テキスト出力が無い {stats['no_text_output']}")
        return 0
    finally:
        store.close()


def serve_data_dir() -> str:
    """**`serve` が使うデータ置き場**（P8-6）。

    `create_app()` は `IMAGE_REVIEWER_DATA` が無ければ**断る**（実データを事故で開かない
    ため）。利用者の本来の起動（`image-reviewer serve`）はここで**既定の `.data` を
    明示的に指してから**アプリを作る（今までどおり動く）。

    環境変数が既にあればそのまま使う（複製のサーバを立てるときはここで複製を指せる）。
    """
    import os

    from .app import DATA_ENV, DEFAULT_DATA_DIR

    raw = (os.environ.get(DATA_ENV) or "").strip()
    if not raw:
        raw = str(DEFAULT_DATA_DIR)
        os.environ[DATA_ENV] = raw                     # **明示的に**指す（既定のまま開かせない）
    return raw


def cmd_serve(args) -> int:
    """サーバを起動する。

    **（P8-4 の監査 G-8）`--factory` で作る。** `image_reviewer.app` を import した
    だけで実データを開かないようにしたので（モジュールの `__getattr__`）、
    `create_app` を名指しで渡す方が意図がはっきりする。

    **（P8-6）`serve_data_dir()` を先に通す。** ここで env を立てないと `create_app()` が
    断る（＝`import` でも素の `create_app()` でも実データを開けない）。
    """
    import uvicorn

    serve_data_dir()
    uvicorn.run("image_reviewer.app:create_app", factory=True,
                host=args.host, port=args.port, log_level="info")
    return 0


# ---- バックアップと復元（P8-4。設計 §0.12・§3.3）----


def _guard_db(data_dir_path) -> dict | None:
    """壊れた DB では**書く仕事をしない**（設計 §0.12-5）。

    壊れているのに `Store(data_dir())` を開くと、`migrate()` の手当て（`_top_up_*`）が
    書こうとして落ちる。**先に健全性を見て、案内を出して止める**（CLI の流儀）。
    """
    from .backup import inspect_db

    state = inspect_db(data_dir_path)
    if state["mode"] == "ok":
        return None
    print(state["guidance"] or "DB が壊れています", file=sys.stderr)
    return state


def cmd_backup(args) -> int:
    """**いま 1 回取る**（`--out` で置き場を指定。既定は `backup_dir`）。"""
    from .app import data_dir
    from .backup import BackupService
    from .review import ReviewError

    broken = _guard_db(data_dir())
    if broken is not None:
        return 2
    store = _store()
    try:
        svc = BackupService(store)
        try:
            got = svc.snapshot(manual=True, out=args.out, include_library=args.include_library)
        except ReviewError as exc:
            print(exc.detail, file=sys.stderr)
            return 2
    finally:
        store.close()
    manifest = got["manifest"]
    print(f"バックアップを取りました: {got['dir']}")
    # **（A-1・G-7）** 時刻は画面と同じ現地の 1 形式にする（前は UTC の ISO だった）
    print(f"  作った時刻 {_when(manifest['created_at'])} / 版 {manifest['app_version']} / "
          f"abi {manifest['abi']}")
    counts = manifest["counts"]
    # **（ワーディング監査 C-9）** 単位を揃える（まとまりは件、注記は件、語は語）
    print(f"  画像 {counts['assets']} 枚 / 判断 {counts['decisions']} 件 / "
          f"まとまり {counts['groups']} 件 / 注記 {counts['annotations']} 件 / 語 {counts['tags']} 語")
    # **（A-2）** 容量の書き方を画面に揃える（KB は整数、MB は小数 1 桁）
    print(f"  DB {_bytes(manifest['db_bytes'])}（sha256 {manifest['db_sha256'][:19]}…）")
    check = got.get("db_check") or {}
    if check:
        stages = check.get("stages") or {}
        # **（E-11）** 「写し」「quick_check=ok」は内部の語。人が読める 1 行にする
        stage = str(check.get("stage") or "")
        if stage == "ok":
            print("  コピーの検査: 問題なし")
        else:
            print(f"  コピーの検査: {stage}"
                  f"（quick_check: {(stages.get('quick_check') or {}).get('detail')}）")
    files = got["files"]
    # **（E-11・D-3）** 「写した」「sidecar / export」を人が読める形に
    print(f"  sidecar と export: コピーした {files['copied']}、"
          f"変わっていないので共有した {files['linked']}、設定 {got['settings']} 件")
    if got["library"]["files"]:
        # **（D-5）** 「実体」→「ファイル」
        print(f"  画像のファイル {got['library']['files']} 枚（"
              f"{_bytes(got['library']['bytes'])}）")
    if got["pruned"]:
        # **（D-3）** 「スナップショット」→「バックアップ」
        print(f"  古いバックアップを消しました: {', '.join(got['pruned'])}")
    # **（D-6）** 登録したフォルダは「フォルダ」、バックアップの場所は「保存先」
    print(f"  保存先: {got['backup_dir']}")
    return 0


def cmd_restore(args) -> int:
    """**バックアップから戻す**（`<data>` を消していても戻せる。設計 §0.12-4）。

    **`Store` を開かない**（壊れた DB を置き換えるのがこの道具の仕事なので、
    開いてからでは遅い）。`manifest.json` を読んで**版と件数を先に出す**。
    """
    from .app import data_dir
    from .backup import restore
    from .review import ReviewError

    try:
        got = restore(data_dir(), args.dir, force=args.force)
    except ReviewError as exc:
        print(exc.detail, file=sys.stderr)
        return 2
    manifest = got["manifest"]
    print(f"バックアップ: {got['dir']}")
    if manifest is None:
        print(f"  注意: manifest.json が読めません（--force で進みました）: "
              f"{got['manifest_error']}")
    else:
        counts = manifest["counts"]
        # **（A-1・G-7）** 画面と同じ現地の 1 形式
        print(f"  作った時刻 {_when(manifest['created_at'])} / 版 {manifest['app_version']}")
        print(f"  画像 {counts['assets']} 枚 / 判断 {counts['decisions']} 件 / "
              f"まとまり {counts['groups']} / 注記 {counts['annotations']} / 語 {counts['tags']}")
    # **（C-1）写しの中身が manifest と一致したか**（1 バイトでも違えば戻さない）
    sha = got.get("sha256") or {}
    if sha.get("expected") is None:
        print("  sha256: manifest に無いので照合していません")
    elif sha.get("ok"):
        print(f"  sha256 一致: {sha['actual'][:19]}…")
    else:
        print(f"  注意: sha256 が manifest と違います（--force で進みました）: "
              f"期待 {str(sha.get('expected'))[:19]}… / 実際 {str(sha.get('actual'))[:19]}…")
    # **（E-11）** 「quick_check」は内部の語（人が読む 1 行にする）
    print(f"  戻す前の検査: {got['before']['detail']}")
    if got["setaside"]:
        # **（ワーディング監査 C-1）** Markdown の記法（`**太字**`・バッククォート）を端末に出さない
        print(f"  元の DB を退避しました: {got['setaside']}"
              "（バックアップのフォルダの隣です。--backup-dir という選択肢は無いためです）")
    print(f"  戻しました: {got['data_dir']}\\db.sqlite3"
          f"（integrity_check: {got['after']['detail']}）")
    for name, stat in got["copied"].items():
        print(f"  {name}: {stat['files']} ファイルを戻しました")
    if got["library"]["restored"] or got["library"]["missing"]:
        # **（D-5）** 「実体」→「ファイル」
        print(f"  画像のファイル: 戻した {got['library']['restored']} / 既にあった "
              f"{got['library']['kept']} / 見つからない {got['library']['missing']}")
    # **（D-6・C-1）** 「置き場」→「フォルダ」（登録したフォルダ）
    print("  参照切れを拾うため、走査を 1 回してください: image-reviewer scan --root <フォルダ>")
    return 0


def cmd_rebuild_metadata(args) -> int:
    """**PNG と sidecar から来歴を組み直す**（設計 §0.12-4。専門 §5.2 の 4）。"""
    from .app import data_dir
    from .backup import rebuild_metadata

    broken = _guard_db(data_dir())
    if broken is not None:
        return 2
    store = _store()
    try:
        got = rebuild_metadata(store)
    finally:
        store.close()
    print("来歴を組み直しました（DB にある値は上書きしません）。")
    print(f"  見た {got['assets']} 枚 / 埋めた {got['updated']} / そのまま {got['unchanged']}")
    print(f"  sidecar から {got['from_sidecar']} / PNG から {got['from_png']} / "
          f"sidecar {got['sidecars']} ファイル")
    print(f"  ファイルが見つからない {got['missing_files']} / 元になるものが無い {got['no_source']}")
    for note in got["notes"][:10]:
        # **（B-3）** 注記の本文も敬体（`png_meta` / `scan` が作る）
        print(f"  注記: {note}", file=sys.stderr)
    return 0


# ---- JSON ストア（プロトタイプ）からの取り込み（P5-0）----

def migrate_from_json(store: Store, json_path: str | Path, *,
                      sidecar_dir: str | Path | None = None) -> dict:
    """JSON ストアを SQLite へ取り込む（`docs/p5-design.md` §0.1 の「取り込み」）。

    - **JSON は読むだけ。書き換えないし消さない**（そのまま控えとして残す。点検 B5）
    - 何度打っても増えない（`sha256` と正規化したパスを鍵にする）
    - 取り込み後に `stats()` が JSON と同じ件数を返すこと（**数え方を変えない**）
    - `sidecar/*.json` を重ねる。**PNG から取り直せない値（英訳）は JSON に無いことがある**
      （点検 I5）。JSON に値があるときは**上書きしない**
    - 監査 B1: `review_state` が `unreviewed` 以外の枚には **`decision` を 1 行**書く。
      台帳が無い写しは、次の `ReviewService()` の `reconcile()`（台帳が正）で
      **黙って** `unreviewed` に戻される。取り込んだ判断を失わないために行で説明する
    """
    src = Path(json_path)
    data = json.loads(src.read_text(encoding="utf-8"))
    now = db.now()
    created = updated = skipped = decisions = 0
    store.set_roots([str(r) for r in (data.get("roots") or [])])
    # 監査 B1: JSON の `review_reason_id` を `decision` と `asset` に入れるので、
    # builtin の理由を先に埋める（無いと FK で落ちる）。`ON CONFLICT DO NOTHING` なので安全
    reasons.seed(store.con)

    # sha256 → 新しい asset_id。場所の履歴は相手を書き替えるので、先に全部作る
    remap: dict[str, str] = {}
    for key, a in (data.get("assets") or {}).items():
        sha = a.get("sha256") or a.get("id") or key
        with store.transaction():
            row = store.con.execute("SELECT id FROM asset WHERE sha256 = ?", (sha,)).fetchone()
            fresh = row is None
            state = a.get("review_state")
            if state not in ("kept", "rejected"):
                state = "unreviewed"
            # 知らない理由 id は NULL に寄せる（FK。JSON に無い理由を勝手に作らない）
            reason_id = a.get("review_reason_code_id") or a.get("review_reason_id")
            if reason_id and reasons.row(store.con, reason_id) is None:
                reason_id = None
            if fresh:
                asset_id = db.ulid()
                store.con.execute(
                    "INSERT INTO asset(id, sha256, kind, kind_source, width, height, format,"
                    " review_state, review_reason_code_id, reviewed_at, reviewed_by,"
                    " first_seen_at, last_seen_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        asset_id, sha, a.get("kind") or "generated", a.get("kind_source") or "auto",
                        a.get("width"), a.get("height"), a.get("format"),
                        state,
                        reason_id,
                        a.get("reviewed_at"), a.get("reviewed_by"),
                        a.get("first_seen_at") or now, a.get("last_seen_at") or now,
                    ),
                )
                created += 1
            else:
                asset_id = row["id"]
            remap[sha] = asset_id
            touched = False

            # 監査 B1: 写しを書いたなら、台帳にも 1 行書いて説明できるようにする
            if state != "unreviewed":
                decisions += _write_migrated_decision(store, asset_id, a, state, now)

            if store.con.execute(
                "SELECT 1 FROM asset_meta WHERE asset_id = ?", (asset_id,)
            ).fetchone() is None:
                store.con.execute(
                    "INSERT INTO asset_meta(asset_id, meta_json, note, source, extracted_at)"
                    " VALUES (?,?,?,?,?)",
                    (asset_id, json.dumps(a.get("meta"), ensure_ascii=False), a.get("meta_note"),
                     a.get("source") or "scan", now),
                )
                touched = True

            for loc in a.get("locations") or []:
                path = loc.get("path")
                loc_key = loc.get("key") or (normalize_path(path) if path else None)
                if not loc_key:
                    continue
                if store.con.execute(
                    "SELECT 1 FROM asset_location WHERE path = ?", (loc_key,)
                ).fetchone() is not None:
                    continue          # 同じパスは 1 行だけ。二度目は何もしない
                store.con.execute(
                    "INSERT INTO asset_location(path, display_path, asset_id, size, mtime_ns,"
                    " is_primary, missing_at, last_seen_at) VALUES (?,?,?,?,?,?,?,?)",
                    (loc_key, path or loc_key, asset_id, int(loc.get("size") or 0),
                     int(loc.get("mtime_ns") or 0), 1 if loc.get("is_primary") else 0,
                     loc.get("missing_at"), loc.get("last_seen_at") or now),
                )
                touched = True

            if not fresh:
                if touched:
                    updated += 1
                else:
                    skipped += 1

    # パスの中身が入れ替わった履歴（JSON では sha256 だった id を ULID に読み替える）
    history = 0
    for h in data.get("location_history") or []:
        old = remap.get(h.get("asset_id"), h.get("asset_id"))
        new = remap.get(h.get("replaced_by_asset_id"), h.get("replaced_by_asset_id"))
        path = h.get("path") or ""
        at = h.get("replaced_at") or now
        with store.transaction():
            if store.con.execute(
                "SELECT 1 FROM location_history WHERE asset_id = ? AND path = ?"
                " AND replaced_at = ?", (old, path, at)
            ).fetchone() is not None:
                continue
            store.con.execute(
                "INSERT INTO location_history(asset_id, path, size, mtime_ns,"
                " replaced_by_asset_id, replaced_at) VALUES (?,?,?,?,?,?)",
                (old, path, h.get("size"), h.get("mtime_ns"), new, at),
            )
            history += 1

    sidecars = _merge_sidecars(
        store, Path(sidecar_dir) if sidecar_dir is not None else store.data_dir / "sidecar")
    stats = store.stats()
    return {"created": created, "updated": updated + sidecars, "skipped": skipped,
            "sidecars": sidecars, "history": history, "decisions": decisions, **stats}


def _write_migrated_decision(store: Store, asset_id: str, a: dict, state: str, now: str) -> int:
    """監査 B1: 取り込んだ `review_state`（`kept` / `rejected`）を**台帳の 1 行**にする。

    これが無いと `ReviewService.reconcile()`（台帳が正）が写しを `unreviewed` に戻し、
    `store.json` から取り込んだ判断が黙って消える（`docs/p5-audit-report.md` B1）。
    二度目の取り込みでは増やさない（その枚の判断行が既にあれば書かない）。
    """
    if store.con.execute(
        "SELECT 1 FROM decision WHERE subject_type = 'asset' AND subject_id = ?", (asset_id,)
    ).fetchone() is not None:
        return 0
    reason_id = a.get("review_reason_code_id") or a.get("review_reason_id")
    if reason_id and reasons.row(store.con, reason_id) is None:
        reason_id = None
    store.con.execute(
        "INSERT INTO decision(id, seq, subject_type, subject_id, verdict, reason_code_id,"
        " note, actor, supersedes, client_token, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (db.ulid(), db.next_seq(store.con), "asset", asset_id,
         "keep" if state == "kept" else "reject", reason_id, MIGRATED_NOTE, "human",
         None, None, a.get("reviewed_at") or now),
    )
    return 1


def _merge_sidecars(store: Store, sidecar_dir: Path) -> int:
    """`<data>/sidecar/*.json` を重ねる。**JSON に値があるときは上書きしない**（点検 I5）。"""
    if not sidecar_dir.is_dir():
        return 0
    merged = 0
    for f in sorted(sidecar_dir.glob("*.json")):
        try:
            payload = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue          # 壊れた控えで取り込み全体を止めない
        if not isinstance(payload, dict):
            continue
        sha = payload.get("sha256") or f.stem
        row = store.con.execute(
            "SELECT a.id AS id, m.meta_json AS meta_json FROM asset a"
            " LEFT JOIN asset_meta m ON m.asset_id = a.id WHERE a.sha256 = ?", (sha,)
        ).fetchone()
        if row is None:
            continue
        try:
            meta = json.loads(row["meta_json"]) if row["meta_json"] else {}
        except ValueError:
            meta = {}
        if not isinstance(meta, dict):
            meta = {}
        changed = False
        for source in (payload.get("meta") or {}, payload):
            for k, v in source.items():
                if k in ("schema", "abi", "sha256", "path", "meta"):
                    continue
                if _absent(v) or not _absent(meta.get(k)):
                    continue          # 空だけを埋める。入っている値は触らない
                meta[k] = v
                changed = True
        if changed:
            store.set_meta(row["id"], meta)
            merged += 1
    return merged


def _absent(value) -> bool:
    """「値が無い」の判定。`0` と `False` は**値がある**として扱う。"""
    return value is None or value == "" or value == [] or value == {}


def cmd_migrate_from_json(args) -> int:
    from .app import data_dir

    src = Path(args.from_json) if args.from_json else Path(data_dir()) / "store.json"
    if not src.exists():
        print(f"取り込み元の JSON ストアがありません: {src}", file=sys.stderr)
        return 2
    store = _store()
    try:
        result = migrate_from_json(store, src)
        target = store.data_dir / "db.sqlite3"
    finally:
        store.close()
    # **（D-3）** 「控え」→「バックアップ」
    print("JSON ストアから取り込みました（JSON は書き換えず、バックアップとして残します）。")
    print(f"  新規 {result['created']} / 更新 {result['updated']} / そのまま {result['skipped']} 件")
    print(f"  画像 {result['assets']} 枚 / 場所 {result['locations']} 件 / "
          f"来歴あり {result['with_provenance']} / 来歴なし {result['without_provenance']} / "
          f"参照切れ {result['missing']}")
    print(f"  sidecar から補った {result['sidecars']} 件 / 場所の履歴 {result['history']} 件")
    print(f"  台帳に写した判断 {result['decisions']} 件（台帳の無い写しは次の起動で消えます）")
    print(f"  取り込み元: {src}")
    print(f"  取り込み先: {target}")
    return 0


def main(argv: list[str] | None = None) -> int:
    # **（C-19・G-5）** `--help` の骨組みを日本語にする（`usage:` / `positional arguments:` /
    # `options:` / `show this help message and exit` を出さない）
    parser = JaArgumentParser(prog="image-reviewer", description="image-reviewer（プロトタイプ）")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_scan = sub.add_parser("scan", help="フォルダを走査して登録する")
    p_scan.add_argument("--root", action="append", help="走査するフォルダ（複数指定できる）")
    p_scan.set_defaults(func=cmd_scan)

    # **（D-4）** 「捕獲」→「取り込む」
    p_cap = sub.add_parser("capture", help="ComfyUI の /history から英訳を取り込む（監視の代わりの 1 回走査）")
    p_cap.add_argument("--base-url", default="http://127.0.0.1:8188")
    p_cap.set_defaults(func=cmd_capture)

    p_serve = sub.add_parser("serve", help="サーバを起動する")
    p_serve.add_argument("--host", default="127.0.0.1")
    p_serve.add_argument("--port", type=int, default=8790)
    p_serve.set_defaults(func=cmd_serve)

    p_mig = sub.add_parser(
        "migrate-from-json",
        help="プロトタイプの store.json を SQLite へ取り込む（JSON はそのまま残す）")
    p_mig.add_argument("--from", dest="from_json", default=None,
                       help="取り込み元の JSON（既定: <data>/store.json）")
    p_mig.set_defaults(func=cmd_migrate_from_json)

    # ---- P8-4（バックアップと復元。設計 §0.12-4）----
    # **（ワーディング監査 C-1）** `--help` にも Markdown の記法を出さない
    p_backup = sub.add_parser("backup", help="いま 1 回バックアップを取る（必ず新しく取る）")
    p_backup.add_argument("--out", default=None,
                          help="保存先（既定: 設定の backup_dir。アプリの中（.data）は断る）")
    # **（D-3・D-5）** 「実体も控える」→「画像のファイルもバックアップに含める」
    p_backup.add_argument("--include-library", action="store_true",
                          help="画像のファイルもバックアップに含める（既定では含めません。参照モードの画像は利用者のものだからです）")
    p_backup.set_defaults(func=cmd_backup)

    p_restore = sub.add_parser("restore", help="バックアップから戻す（元の DB は退避してから）")
    p_restore.add_argument("dir", help="バックアップのフォルダ（manifest.json のある所）")
    p_restore.add_argument("--force", action="store_true",
                           help="manifest が読めない・写しの DB が quick_check に通らなくても戻す")
    p_restore.set_defaults(func=cmd_restore)

    p_rebuild = sub.add_parser(
        "rebuild-metadata",
        help="PNG と sidecar から来歴を組み直す（DB にある値は上書きしない）")
    p_rebuild.set_defaults(func=cmd_rebuild_metadata)

    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except ReviewError as exc:
        # **P8-4**: 壊れた DB・控えが取れない、は**番号ではなく終了コードで**返す
        # （人が読む 1 行を stderr に出す。スタックトレースを出さない）
        print(exc.detail, file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
