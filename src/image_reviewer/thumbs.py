"""サムネイルを作って配る。

設計: docs/design.md §12.2、docs/p5-design.md §0.7（**実測 F5**）
- 一度作ったら作らない（内容ハッシュ名なので不変）
- 一覧は 256px、拡大は 1024px。原本は開かない
- **P5-3**: pHash / dHash は、この**サムネイルを作る復号と同じ 1 枚**から計算する
  （`on_image`）。実測で pHash の 11.88 ms/枚 のうち 11.35 ms が復号＋縮小だったので、
  復号を 2 回にすると費用がそのまま倍になる。設計 §6.2 の「走査の背景ジョブ」は
  **この実測で取り消された**（`p5-design.md` §0.7 F5）
"""

from __future__ import annotations

import logging
import os
import tempfile
from pathlib import Path
from typing import Callable

from PIL import Image

log = logging.getLogger(__name__)

SIZES = (256, 1024)


def thumb_path(data_dir: str | Path, sha256: str, size: int) -> Path:
    return Path(data_dir) / "thumbs" / sha256[:2] / f"{sha256}_{size}.webp"


def ensure_thumb(src: str, data_dir: str | Path, sha256: str, size: int,
                 *, on_image: Callable[[Image.Image], None] | None = None) -> Path:
    """無ければ作って返す。元が小さければ拡大しない。

    一時ファイルは `mkstemp` で作る（固定名だと同時要求で取り合う。点検 I16）。

    `on_image` には**復号した 1 枚**（`RGB` に変換した直後、縮小する前）を渡す。
    P5-3 の pHash / dHash はここに同居する（**実測 F5**: 費用の 96% は復号）。
    `on_image` が投げてもサムネイルは返す（ハッシュは次の要求で埋まる。ここで
    落とすと、ハッシュの不具合で一覧の絵まで出なくなる）。

    **既にサムネイルがあるときは復号しない**ので `on_image` も呼ばない。その場合は
    呼ぶ側が `compare.ensure_hashes()`（ハッシュだけの道）を通る。
    """
    if size not in SIZES:
        raise ValueError(f"size は {SIZES} のいずれか")
    out = thumb_path(data_dir, sha256, size)
    if out.exists():
        return out
    out.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=str(out.parent), suffix=".webp")
    tmp = Path(tmp_name)
    try:
        with Image.open(src) as im:
            im = im.convert("RGB")
            if on_image is not None:
                try:
                    on_image(im)
                except Exception:  # noqa: BLE001  ハッシュの失敗でサムネイルを落とさない
                    log.exception("ハッシュを計算できませんでした: %s", src)
            im.thumbnail((size, size), Image.LANCZOS)
            with os.fdopen(fd, "wb") as fh:
                im.save(fh, "WEBP", quality=82, method=4)
        os.replace(tmp, out)
    except Exception:
        tmp.unlink(missing_ok=True)
        raise
    return out
