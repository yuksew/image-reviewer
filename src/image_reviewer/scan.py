"""フォルダを走査して画像を登録する。

設計: docs/design.md §5.1、docs/duplicates-deletion-backup.md §1.4

守ること（点検で見つかった誤りを反映）:
- 中身（sha256）を正体にする。走査の一部として計算する（実測 399 MB/s）
- パスは `normalize_path` で正規化した鍵で照合する（I1）
- **ファイルは 1 回だけ開く**（I19）。先頭 8 バイト・ハッシュ・チャンクを同じハンドルから取る
- （パス・サイズ・mtime）が同じなら何もしない（2 回目以降を安くする）。**ただし参照切れの
  印（`missing_at`）が立っていれば戻す**（P8-6 の監査 C-1。戻ってきたファイルを生き返らせる）
- **（P10 の監査 A-3）参照切れを戻した枚は、カタログから外す印（`asset.deleted_at`）も引き直す。**
  片付けた行（`closed_at`）しか無い枚は、**ファイルが戻れば一覧にも戻る**（規則は
  `deletions.sync_hidden()` の 1 か所。**走査は規則を持たない**）
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

from . import png_meta
from .deletions import sync_hidden        # **`asset.deleted_at` の規則は 1 か所**（deletions.py）
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
    #: **（P10 の監査 A-3）参照切れを戻した枚**（走査の最後に `deleted_at` を引き直す）
    revived: list[str] = []
    store.set_roots(roots)

    for root in roots:
        if not os.path.isdir(root):
            stats["errors"].append(f"フォルダがありません: {root}")
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
                    if store.mark_seen(path):
                        revived.append(known["asset_id"])
                elif known["deleted_at"]:
                    # **（P10 の監査 A-3）ファイルが在り、登録も生きているのに隠れている枚。**
                    # 段 1 で外しただけの行は**ファイルを動かさない**（利用者が外へ出しても
                    # `missing_at` は立たないことがある）ので、上の「印が立っていれば戻す」だけでは
                    # **片付けた後にファイルが戻った枚**を拾えない。ここで印を引き直す
                    revived.append(known["asset_id"])
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
                    # **（B-3）** 注記も敬体に（CLI と画面の来歴にそのまま出る）
                    note = chunks.get("error") or "prompt チャンクがありません（生成条件が残っていない画像です）"
                    kind, kind_source = "generated", "auto:png"
            else:
                kind, kind_source = "photo", "auto:jpeg"

            asset_id, created = store.register(
                sha256=sha, path=path, size=st.st_size, mtime_ns=st.st_mtime_ns,
                width=width, height=height, fmt=fmt, meta=meta, note=note,
                kind=kind, kind_source=kind_source,
            )
            # **（P10 の監査 A-3）参照切れだった場所・隠れていた枚**も、印を戻した側に数える
            # （`register()` は `missing_at` を NULL に戻す。`mark_seen()` を通らない道）
            if known and (known["missing_at"] or known["deleted_at"]):
                revived.append(asset_id)
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
    # **（P10 の監査 A-3）ファイルが戻った枚の「カタログから外す印」を引き直す。**
    # 片付けた行（`closed_at`）しか無い枚は**ここで一覧に戻る**（実体が無い間は `live == 0` で
    # 隠れたままになるので、幽霊は戻らない）。生きた段 1 の行がある枚は**隠れたまま**（利用者の意思）。
    # **規則は `deletions.sync_hidden()` の 1 か所**（走査はここで呼ぶだけ）。
    if revived:
        with store.transaction() as con:
            for asset_id in sorted(set(revived)):
                sync_hidden(con, asset_id)
    store.save()
    return stats


def _analyze(raw: bytes, text: dict) -> dict:
    import json

    out = {"info": None, "note": None}
    try:
        graph = json.loads(raw.decode("utf-8", "replace"))
    except Exception as exc:  # noqa: BLE001
        out["note"] = f"prompt チャンクを JSON として読めません（{exc}）。"
        return out
    if not isinstance(graph, dict) or not all(isinstance(v, dict) for v in graph.values()):
        out["note"] = "prompt チャンクが API 形式のグラフではありません"
        return out
    info = png_meta.analyze_graph(graph)
    info["graph_format"] = "api+ui" if "workflow" in text else "api"
    out["info"] = info
    return out
