"""フォルダを走査して画像を登録する。

設計: docs/design.md §5.1、docs/duplicates-deletion-backup.md §1.4

守ること（点検で見つかった誤りを反映）:
- 中身（sha256）を正体にする。走査の一部として計算する（実測 399 MB/s）
- パスは `normalize_path` で正規化した鍵で照合する（I1）
- **ファイルは 1 回だけ開く**（I19）。先頭 8 バイト・ハッシュ・チャンクを同じハンドルから取る
- （パス・サイズ・mtime）が同じなら何もしない（2 回目以降を安くする）。**ただし参照切れの
  印（`missing_at`）が立っていれば戻す**（P8-6 の監査 C-1。戻ってきたファイルを生き返らせる）
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

from . import png_meta
from .store import Store, normalize_path

IMAGE_EXT = {".png", ".jpg", ".jpeg", ".webp"}
MAGIC = ((b"\x89PNG\r\n\x1a\n", "png"), (b"\xff\xd8\xff", "jpeg"), (b"RIFF", "webp"))
READ_CAP = 256 * 1024


def _read_head_hash_chunks(path: str) -> tuple[str | None, bytes, str]:
    """1 回の open で、先頭バイト・チャンク用の先頭バイト列・内容ハッシュを取る。"""
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        head = fh.read(8)
        fh.seek(0)
        buf = fh.read(READ_CAP)
        digest.update(buf)
        for block in iter(lambda: fh.read(1 << 20), b""):
            digest.update(block)
    fmt = None
    for sig, name in MAGIC:
        if head.startswith(sig):
            fmt = name
            break
    return fmt, buf, digest.hexdigest()


def iter_images(root: str | Path):
    root = str(root)
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if not d.startswith(".")]
        for name in filenames:
            if Path(name).suffix.lower() in IMAGE_EXT:
                yield os.path.join(dirpath, name)


def scan(store: Store, roots: list[str], *, on_progress=None) -> dict:
    """走査して登録する。戻り値は集計。"""
    roots = [str(Path(r)) for r in roots]
    stats = {"roots": roots, "seen": 0, "created": 0, "known": 0, "changed": 0,
             "images": 0, "not_image": 0, "errors": [], "with_provenance": 0, "missing": 0}
    seen_keys: set[str] = set()
    store.set_roots(roots)

    for root in roots:
        if not os.path.isdir(root):
            stats["errors"].append(f"フォルダが無い: {root}")
            continue
        for path in iter_images(root):
            stats["seen"] += 1
            key = normalize_path(path)
            seen_keys.add(key)
            try:
                st = os.stat(path)
            except OSError as exc:
                stats["errors"].append(f"{path}: {exc}")
                continue

            known = store.location_of(path)
            if known and known["size"] == st.st_size and known["mtime_ns"] == st.st_mtime_ns:
                # **戻ってきたファイルを生き返らせる**（P8-6 の監査 C-1 / G-1）。
                # 移動は `mtime_ns` を変えないので、外へ出て**同じパスへ戻った**枚はこの早道に
                # 落ちる（`register()` の `missing_at = NULL` に届かない）。ここで戻さないと、
                # 走査を何度回しても「参照切れ」のままで、人は何を押せばよいか分からない。
                if known["missing_at"]:
                    store.mark_seen(path)
                stats["known"] += 1
                asset = store.asset(known["asset_id"])
                if asset and asset.get("meta"):
                    stats["with_provenance"] += 1
                continue

            try:
                fmt, buf, sha = _read_head_hash_chunks(path)
            except OSError as exc:
                stats["errors"].append(f"{path}: {exc}")
                continue
            if fmt is None:
                stats["not_image"] += 1
                continue
            stats["images"] += 1
            # 入れ替わりの判定は**内容**で行う。`asset_id` は ULID になったので、
            # ハッシュと比べては常に「入れ替わった」になる（点検 I17 の帰結）
            replaced = bool(known and known["sha256"] != sha)

            width = height = None
            meta = note = kind = kind_source = None
            if fmt == "png":
                chunks = png_meta.parse_chunks(buf)
                width, height = chunks["width"], chunks["height"]
                raw = chunks["text"].get("prompt")
                if raw is not None:
                    prov = _analyze(raw, chunks["text"])
                    meta, note = prov["info"], prov["note"]
                    if meta:
                        stats["with_provenance"] += 1
                    # 種別の規則（点検 C2）: prompt があれば生成物。無ければ PNG は生成物と推定する
                    kind, kind_source = "generated", "auto:prompt" if meta else "auto:png"
                else:
                    note = chunks.get("error") or "prompt チャンクが無い（生成条件が残っていない画像）"
                    kind, kind_source = "generated", "auto:png"
            else:
                kind, kind_source = "photo", "auto:jpeg"

            asset_id, created = store.register(
                sha256=sha, path=path, size=st.st_size, mtime_ns=st.st_mtime_ns,
                width=width, height=height, fmt=fmt, meta=meta, note=note,
                kind=kind, kind_source=kind_source,
            )
            # 置き換えは created より先に見る（置き換えると新しい内容＝新規 asset にもなるため）
            if replaced:
                stats["changed"] += 1
            elif created:
                stats["created"] += 1
            else:
                stats["known"] += 1
            if on_progress and stats["images"] % 100 == 0:
                on_progress(stats)

    stats["missing"] = store.mark_missing(seen_keys, roots)
    store.save()
    return stats


def _analyze(raw: bytes, text: dict) -> dict:
    import json

    out = {"info": None, "note": None}
    try:
        graph = json.loads(raw.decode("utf-8", "replace"))
    except Exception as exc:  # noqa: BLE001
        out["note"] = f"prompt チャンクを JSON として読めない: {exc}"
        return out
    if not isinstance(graph, dict) or not all(isinstance(v, dict) for v in graph.values()):
        out["note"] = "prompt チャンクが API 形式のグラフではない"
        return out
    info = png_meta.analyze_graph(graph)
    info["graph_format"] = "api+ui" if "workflow" in text else "api"
    out["info"] = info
    return out
