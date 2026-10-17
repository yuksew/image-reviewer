"""コマンド。

使い方:
  uv run image-reviewer scan --root C:\\path\\to\\images
  uv run image-reviewer capture --base-url http://127.0.0.1:8188
  uv run image-reviewer serve --port 8790
  uv run image-reviewer migrate-from-json        # .data/store.json を SQLite へ取り込む

どのコマンドでも、`_store()` が `app.data_dir` を読み、そのあと**起動時の書き出し**
（DB の印で拾う。監査 A1）を明示的に走らせる。以前は `app` モジュールの読み込み
（`create_app()`）がその役を兼ねていたが、読み込みの順序に依存していた（監査 C1）。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import db, reasons
from .scan import scan
from .store import Store, normalize_path

# 監査 B1: 取り込みで書く台帳の行の注記（「なぜ写しが非 unreviewed なのか」をここで説明する）
MIGRATED_NOTE = "store.json から取り込み"


def _store(*, flush: bool = True):
    """`data_dir()` を読み、**起動時の書き出し**を明示的に走らせる（監査 A1・C1）。

    以前は `app` モジュールの読み込み（`create_app()`）がその役を兼ねていたが、
    同じプロセスで 2 回目以降は読み込みが走らないので、**読み込みの順序に依存していた**
    （P5-2 の API テストが先に `create_app()` を読み込むと、CLI 側の書き出しが漏れる）。
    ここで明示的に呼べば順序に依らない。印の無い DB では `flush_dirty()` は何もしない。
    """
    from .app import data_dir

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
            print("--root を指定してください（初回は必須）", file=sys.stderr)
            return 2
        # P8-2（G-2・C-6）: サーバと同じ錠を取る（同じプロセスで走査と削除が重ならないように）。
        # **プロセスをまたぐ錠ではない**ので、走査中に別プロセスのサーバが消すことは防げない
        # （それは SQLite の取引が守る）
        guard = DeletionService(store)
        with guard.scan_guard():
            stats = scan(store, roots,
                         on_progress=lambda s: print(f"  ... {s['images']} 枚", flush=True))
        print(f"走査: 見た {stats['seen']} / 画像 {stats['images']} / 新規 {stats['created']} / "
              f"既知 {stats['known']} / 入れ替わり {stats['changed']} / 画像でない {stats['not_image']}")
        print(f"来歴あり {stats['with_provenance']} / 参照切れにした {stats['missing']}")
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
        print(f"/history {stats['history_entries']} 件を走査。")
        print(f"訳が未取得の画像 {stats['checked']} 枚のうち {stats['captured']} 枚で訳を捕獲した。")
        print(f"  実行が見つからない {stats['no_history']} / ja2en でない {stats['not_textgen']} / "
              f"テキスト出力が無い {stats['no_text_output']}")
        return 0
    finally:
        store.close()


def cmd_serve(args) -> int:
    import uvicorn

    uvicorn.run("image_reviewer.app:app", host=args.host, port=args.port, log_level="info")
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
    print("JSON ストアから取り込みました（**JSON は書き換えず、控えとして残します**）。")
    print(f"  新規 {result['created']} / 更新 {result['updated']} / そのまま {result['skipped']} 件")
    print(f"  画像 {result['assets']} 枚 / 場所 {result['locations']} 件 / "
          f"来歴あり {result['with_provenance']} / 来歴なし {result['without_provenance']} / "
          f"参照切れ {result['missing']}")
    print(f"  sidecar から補った {result['sidecars']} 件 / 場所の履歴 {result['history']} 件")
    print(f"  台帳に写した判断 {result['decisions']} 件（監査 B1。台帳が無い写しは次の起動で消える）")
    print(f"  取り込み元: {src}")
    print(f"  取り込み先: {target}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="image-reviewer", description="image-reviewer（プロトタイプ）")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_scan = sub.add_parser("scan", help="フォルダを走査して登録する")
    p_scan.add_argument("--root", action="append", help="走査するフォルダ（複数指定できる）")
    p_scan.set_defaults(func=cmd_scan)

    p_cap = sub.add_parser("capture", help="ComfyUI の /history から英訳を捕獲する（監視の代わりの 1 回走査）")
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

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
