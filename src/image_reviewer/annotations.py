"""画像の上の印（注記。P6-2）。

設計: docs/p6-design.md §0.6〜§0.9・§3.6・§4.2・§6.2・§6.3・§7・§8.1

守ること（どれも点検・監査の指摘が理由）:
- 座標は **0〜1 の割合**。**丸めない**（`REAL` にそのまま。§0.7）。切り出しのときだけ
  **6 桁へ丸めてから** `floor` / `ceil` する（点検 B1。`ceil((x+w)*W)` は浮動小数で 1 画素はみ出す）
- **領域なしの注記**（座標が全部 NULL）＝**画像 1 枚へのメモ**（点検 A1 / G4）。切り出しは **422**
- **`GET` は書かない**（§0.6）。書くのは `POST .../export {format:'crops'}` だけ
- **`PATCH` / `DELETE` は自分の `actor` の注記だけ**（点検 C7）
- **注記を消したら、その切り出しの PNG も消す**（点検 G3）。`<data>/annotations/` は**キャッシュ**
- 切り出しの書き出しは**一時ファイル → `os.replace`**、失敗したら一時ファイルを消す（§0.8。P5 の C1）
- 出力は **PNG・`compress_level=1`**（無劣化のまま速い。点検 B2 / G7）
"""

from __future__ import annotations

import json
import math
import os
import sqlite3
import threading
from io import BytesIO
from pathlib import Path
from typing import Any, Sequence

from PIL import Image

from . import db
from .compare import _primary_path
from .export import _safe_name
from .review import ReviewError
from .store import Store

SHAPES = ("rect", "ellipse")
MAX_BODY = 2000                 # `body`（§3.6 の表。`note` と同じ長さ）
MAX_TOKEN = 200                 # `client_token`
MAX_ANNOTATIONS = 100           # 1 枚に実用で 100 個まで（§7。上限は設けないが、書き出しの案内に使う）
# `0.1 + 0.2 <= 0.3` が偽になる類の値のための余裕（§0.7。点検 B1）
EPS = 1e-9
# 点検 B2 / G7: 無劣化のまま速い（1024² 全面 66 → 21 ms、2048² 全面 320 → 93 ms）
COMPRESS_LEVEL = 1
SCHEMA_URN = "urn:image-reviewer:schema:annotation-export"
ABI = "0.1"


def _fields_error(fields: dict[str, str]) -> ReviewError:
    return ReviewError(422, "入力を直してください", details={"fields": fields})


def _fraction(value: Any, name: str, fields: dict[str, str]) -> float | None:
    """0〜1 の実数。`None` はそのまま（座標なしの形を作れるように）。"""
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        fields[name] = "0〜1 の実数です"
        return None
    got = float(value)
    if not math.isfinite(got) or got < 0 or got > 1:
        fields[name] = "0〜1 の実数です"
        return None
    return got


def crop_box(x: float, y: float, w: float, h: float,
             width: int, height: int) -> tuple[int, int, int, int]:
    """切り出す画素の箱 `(left, top, right, bottom)`（原画像の座標）。

    **先に 6 桁へ丸めてから** `floor` / `ceil`（点検 B1）。`x + w` を浮動小数で足してから
    掛けると、整数になるはずの値が `374.00000000000006` のようになり `ceil` が 1 画素余計に返す
    （幅 1360 で 0.001 刻みの 3,170 組が該当した）。
    端は `0..width` / `0..height` にクランプし、**幅と高さが 1 画素以上**になるようにする（§0.7）。
    楕円もこの**外接矩形**で切る（点検 D3）。

    **P6-2 の監査（上位 1）**: `left` は **`width - 1` まで**に抑える。`x` が右端ぎりぎり
    （例 `x = 1 - 1e-12`, `w = 1e-12`。`x + w = 1`。**画面で右端までドラッグすると作られうる**）だと
    `floor(round(x*W, 6)) = W` になり、`right = min(W, left + 1)` でも `right == left` のまま潰れて
    **幅 0 の画像**を作り、Pillow が `cannot write empty image` で **500** になっていた。
    `top` も同じ（下端ぎりぎり）。
    """
    left = min(max(int(math.floor(round(x * width, 6))), 0), max(0, width - 1))
    top = min(max(int(math.floor(round(y * height, 6))), 0), max(0, height - 1))
    right = min(max(int(math.ceil(round((x + w) * width, 6))), 0), width)
    bottom = min(max(int(math.ceil(round((y + h) * height, 6))), 0), height)
    if right <= left:
        right = left + 1                    # 1 画素は必ず残す（`left <= width - 1` なので `right <= width`）
    if bottom <= top:
        bottom = top + 1
    return left, top, right, bottom


class AnnotationService:
    """注記の読み書きと切り出し（P6-2）。`Store` を 1 本受け取る（他のサービスと同じ）。"""

    def __init__(self, store: Store):
        self.store = store
        self.data_dir = Path(store.data_dir)
        self._lock = threading.RLock()

    # ---- 場所（§6.3）----

    def dir_for(self, asset_id: str) -> Path:
        return self.data_dir / "annotations" / _safe_name(asset_id)

    def crop_path(self, asset_id: str, annotation_id: str) -> Path:
        return self.dir_for(asset_id) / f"{_safe_name(asset_id)}__{_safe_name(annotation_id)}.png"

    def clean_stale_tmp(self) -> int:
        """`<data>/annotations/**/*.tmp` を消す（§0.8。起動時に 1 回）。

        P5 の書き出しと同じ形（`ExportService.clean_stale_tmp()`）。切り出しは**いつでも
        作り直せるキャッシュ**なので、消えても失う物は無い（座標は DB にある）。
        """
        root = self.data_dir / "annotations"
        if not root.is_dir():
            return 0
        removed = 0
        for path in sorted(root.glob("**/*.tmp")):
            try:
                path.unlink()
                removed += 1
            except OSError:                     # 掴まれていても起動は続ける
                pass
        return removed

    # ---- 形（契約 `Annotation`。API と書き出しで同じ形）----

    @staticmethod
    def _doc(row: sqlite3.Row) -> dict:
        return {
            "id": row["id"],
            "asset_id": row["asset_id"],
            "shape": row["shape"],
            "x": row["x"], "y": row["y"], "w": row["w"], "h": row["h"],
            "body": row["body"],
            "actor": row["actor"],
            "created_at": row["created_at"],
            "group_id": row["group_id"],
        }

    @staticmethod
    def _has_region(row: sqlite3.Row) -> bool:
        return row["x"] is not None and row["w"] is not None

    # ---- 読む ----

    def list_for_asset(self, asset_id: str) -> list[dict]:
        """古い順（`created_at, id`。§3.6）。**書かない**。"""
        with self.store.locked() as con:
            self._asset_or_404(con, asset_id)
            rows = con.execute(
                "SELECT * FROM annotation WHERE asset_id = ? ORDER BY created_at, id",
                (asset_id,)).fetchall()
        return [self._doc(r) for r in rows]

    def get(self, annotation_id: str) -> dict:
        with self.store.locked() as con:
            return self._doc(self._row_or_404(con, annotation_id))

    # ---- 書く ----

    def create(self, asset_id: str, *, shape: Any = None, x: Any = None, y: Any = None,
               w: Any = None, h: Any = None, body: Any = None, group_id: Any = None,
               client_token: Any = None, actor: str = "agent") -> dict:
        """印を付ける（矩形・楕円）、または**画像 1 枚へのメモ**（座標なし。点検 A1）。

        `client_token` の再送は 200 で既存を返す（§0.9。**行を作る口だけが鍵を持つ**）。
        """
        fields: dict[str, str] = {}
        if shape is not None and shape not in SHAPES:
            fields["shape"] = "rect か ellipse です"
        values = {
            "x": _fraction(x, "x", fields),
            "y": _fraction(y, "y", fields),
            "w": _fraction(w, "w", fields),
            "h": _fraction(h, "h", fields),
        }
        text = self._body(body, fields)
        token = self._token(client_token, fields)
        if fields:
            raise _fields_error(fields)

        given = [k for k, v in values.items() if v is not None]
        if given and len(given) != 4:
            missing = [k for k in values if k not in given]
            raise _fields_error({**{k: "座標は 4 つそろえてください" for k in missing},
                                 **{k: "座標は 4 つそろえてください" for k in given}})
        if len(given) == 4:
            if values["w"] <= 0:
                raise _fields_error({"w": "0 より大きい実数です"})
            if values["h"] <= 0:
                raise _fields_error({"h": "0 より大きい実数です"})
            if values["x"] + values["w"] > 1 + EPS:
                raise _fields_error({"w": "x + w は 1 以下です"})
            if values["y"] + values["h"] > 1 + EPS:
                raise _fields_error({"h": "y + h は 1 以下です"})
            if shape is None:
                raise _fields_error({"shape": "rect か ellipse が要ります"})
        else:
            # 座標なし＝画像 1 枚へのメモ。**何も書いていない**ときだけ 422（§0.7）
            if not text:
                raise _fields_error({"body": "メモか注記のどちらかが要ります"})
            shape = None

        payload = {"asset_id": asset_id, "shape": shape, "body": text, "group_id": group_id,
                   **{k: values[k] for k in ("x", "y", "w", "h")}}
        with self.store.transaction() as con:
            self._asset_or_404(con, asset_id)
            if group_id is not None:
                self._check_group(con, asset_id, group_id)
            replay = self._replay(con, token, payload)
            if replay is not None:
                return {**self._doc(replay), "replayed": True}
            annotation_id = db.ulid()
            con.execute(
                "INSERT INTO annotation(id, asset_id, shape, x, y, w, h, body, actor,"
                " created_at, group_id, client_token) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (annotation_id, asset_id, shape, values["x"], values["y"], values["w"],
                 values["h"], text, actor, db.now(), group_id, token))
            return self._doc(self._row_or_404(con, annotation_id))

    def patch(self, annotation_id: str, body: Any, *, actor: str = "agent") -> dict:
        """**メモだけ**変える（§3.6。他の欄は 422）。自分の注記だけ（点検 C7）。"""
        fields: dict[str, str] = {}
        text = self._body(body, fields, required=True)
        if fields:
            raise _fields_error(fields)
        with self.store.transaction() as con:
            row = self._row_or_404(con, annotation_id)
            self._require_own(row, actor)
            con.execute("UPDATE annotation SET body = ? WHERE id = ?", (text, annotation_id))
            return self._doc(self._row_or_404(con, annotation_id))

    def delete(self, annotation_id: str, *, actor: str = "agent") -> str:
        """消す。**切り出しの PNG も消す**（点検 G3）。自分の注記だけ（点検 C7）。"""
        with self.store.transaction() as con:
            row = self._row_or_404(con, annotation_id)
            self._require_own(row, actor)
            asset_id = row["asset_id"]
            con.execute("DELETE FROM annotation WHERE id = ?", (annotation_id,))
        path = self.crop_path(asset_id, annotation_id)
        try:
            path.unlink(missing_ok=True)
        except OSError:                          # 消せなくても害は小さい（§6.3）
            pass
        return annotation_id

    # ---- 切り出しと書き出し ----

    def export_doc(self, asset_id: str, *, annotation_ids: Sequence[str] | None = None,
                   with_crops: bool = False) -> dict:
        """契約（`schemas/annotation-export.schema.json`）の文書（§6.2）。

        `with_crops=False` は**返すだけ**（`GET`。`crops` は `null`）。
        `with_crops=True` は**切り出しを書く**（`POST`。`crops` は配列）。

        **領域なし（座標が全部 null = 画像 1 枚へのメモ）の扱い**（P6-2 の監査 上位 2）:

        - `annotation_ids` を**指定しない**（画像全体の書き出し）: メモは**黙って飛ばして**残りを書く。
          以前は 1 件でも混ざると全体が 422 になり、画面の「切り出しを書き出す」が止まっていた
          （メモは画像 1 枚への覚え書きで、切る範囲が無いのは当然）。
        - `annotation_ids` で**名指し**した: その注記がメモなら **422**（`details.annotation_id` に
          **その id**）。名指しは「これを切ってほしい」という要求なので、黙って飛ばさない。
        """
        with self.store.locked() as con:
            asset = self._asset_or_404(con, asset_id)
            rows = con.execute(
                "SELECT * FROM annotation WHERE asset_id = ? ORDER BY created_at, id",
                (asset_id,)).fetchall()
            if annotation_ids:
                wanted = list(dict.fromkeys(annotation_ids))
                known = {r["id"] for r in rows}
                extra = [i for i in wanted if i not in known]
                if extra:
                    raise ReviewError(422, "この画像の注記ではありません",
                                      details={"extra": extra})
                rows = [r for r in rows if r["id"] in set(wanted)]
            doc = {
                "schema": SCHEMA_URN,
                "abi": ABI,
                "generated_at": db.now(),
                "asset_id": asset_id,
                "image": self._image_size(asset),
                "annotations": [self._doc(r) for r in rows],
                "crops": None,
            }
        if with_crops:
            doc["crops"] = self._write_crops(asset, rows, explicit=bool(annotation_ids))
        return doc

    def crop_png(self, asset_id: str, annotation_id: str) -> bytes:
        """1 枚の切り出しを**その場で作って返す**（`GET /api/annotations/{id}/crop`。書かない）。"""
        with self.store.locked() as con:
            asset = self._asset_or_404(con, asset_id)
            row = self._row_or_404(con, annotation_id)
            if row["asset_id"] != asset_id:
                raise ReviewError(422, "この画像の注記ではありません",
                                  details={"annotation_id": annotation_id})
            size = self._image_size(asset)
        if not self._has_region(row):
            # 監査（上位 2 / 287 行）: `details` には**その注記の id** を入れる
            # （以前は文言が入っていて、どの注記が原因か分からなかった）
            raise ReviewError(422, "切る範囲がありません",
                              details={"annotation_id": annotation_id})
        with self._open(asset) as image:
            return self._png(image, row, size)

    # ---- 中: 画像 ----

    def _open(self, asset: dict) -> Image.Image:
        path = _primary_path(asset)
        if not path or not os.path.exists(path):
            raise ReviewError(409, "画像の実体がありません", code="asset_file_missing",
                              details={"asset_id": asset["id"]})
        return Image.open(path)

    def _image_size(self, asset: dict) -> dict:
        """切り出しの計算に使う画素数。

        **DB の実寸（`asset.width` / `height`）を優先**する（P5 が実体から写した値。
        復号しないので `GET .../export?format=json` が実体を要求しない）。
        無ければ復号して実体から取る（実体が無ければ 409）。
        """
        width, height = asset.get("width"), asset.get("height")
        if width and height:
            return {"width": int(width), "height": int(height)}
        with self._open(asset) as image:
            return {"width": int(image.width), "height": int(image.height)}

    def _png(self, image: Image.Image, row: sqlite3.Row, size: dict) -> bytes:
        box = crop_box(row["x"], row["y"], row["w"], row["h"],
                       size["width"], size["height"])
        cropped = image.crop(box)
        buffer = BytesIO()
        cropped.save(buffer, format="PNG", compress_level=COMPRESS_LEVEL)
        return buffer.getvalue()

    def _write_crops(self, asset: dict, rows: Sequence[sqlite3.Row], *,
                     explicit: bool = False) -> list[dict]:
        """切り出しを書く（`POST`。§0.8 の原子性）。

        **領域なし（メモ）の扱い**（P6-2 の監査 上位 2。`export_doc` の docstring を見る）:
        `explicit=False`（画像全体）なら**黙って飛ばす**。`explicit=True`（名指し）なら **422**
        で、`details.annotation_id` に**その id** を入れる。
        """
        out: list[dict] = []
        if not rows:
            return out
        size = self._image_size(asset)
        with self._open(asset) as image:
            for row in rows:
                if not self._has_region(row):
                    if not explicit:
                        continue                # メモは切れない。画像全体の書き出しは止めない
                    raise ReviewError(422, "切る範囲がありません",
                                      details={"annotation_id": row["id"]})
                box = crop_box(row["x"], row["y"], row["w"], row["h"],
                               size["width"], size["height"])
                cropped = image.crop(box)
                path = self.crop_path(asset["id"], row["id"])
                path.parent.mkdir(parents=True, exist_ok=True)
                tmp = path.with_name(f"{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
                buffer = BytesIO()
                cropped.save(buffer, format="PNG", compress_level=COMPRESS_LEVEL)
                data = buffer.getvalue()
                tmp.write_bytes(data)
                try:
                    os.replace(tmp, path)
                except OSError:
                    try:
                        tmp.unlink(missing_ok=True)      # 失敗した一時ファイルを残さない（P5 の C1）
                    except OSError:
                        pass
                    raise
                out.append({
                    "annotation_id": row["id"],
                    "path": path.relative_to(self.data_dir).as_posix(),
                    "left": box[0], "top": box[1],
                    "width": box[2] - box[0], "height": box[3] - box[1],
                    "bytes": len(data),
                })
        return out

    # ---- 中: 検査 ----

    def _asset_or_404(self, con: sqlite3.Connection, asset_id: str) -> dict:
        asset = self.store.asset(asset_id)
        if asset is None:
            raise ReviewError(404, "画像がありません", details={"asset_id": asset_id})
        return asset

    def _row_or_404(self, con: sqlite3.Connection, annotation_id: str) -> sqlite3.Row:
        row = con.execute("SELECT * FROM annotation WHERE id = ?", (annotation_id,)).fetchone()
        if row is None:
            raise ReviewError(404, "注記がありません", details={"annotation_id": annotation_id})
        return row

    def _require_own(self, row: sqlite3.Row, actor: str) -> None:
        """**自分の `actor` の注記だけ**（点検 C7。人の印をエージェントが消せない）。"""
        if row["actor"] != actor:
            raise ReviewError(403, "他の人が付けた注記は変えられません",
                              details={"actor": actor, "annotation_actor": row["actor"]})

    def _check_group(self, con: sqlite3.Connection, asset_id: str, group_id: str) -> None:
        member = con.execute("SELECT 1 FROM group_item WHERE group_id = ? AND asset_id = ?",
                             (group_id, asset_id)).fetchone()
        if member is None:
            raise ReviewError(422, "この画像のまとまりではありません",
                              details={"group_id": group_id})

    def _body(self, value: Any, fields: dict[str, str], *, required: bool = False) -> str | None:
        if value is None:
            if required:
                fields["body"] = "メモが要ります"
            return None
        if not isinstance(value, str):
            fields["body"] = "文字列です"
            return None
        text = value.strip()
        if required and not text:
            fields["body"] = "メモが要ります"
            return None
        if len(text) > MAX_BODY:
            fields["body"] = f"{MAX_BODY} 文字までです"
            return None
        return text or None

    def _token(self, value: Any, fields: dict[str, str]) -> str | None:
        if value is None:
            return None
        if not isinstance(value, str) or not value.strip():
            fields["client_token"] = "文字列です"
            return None
        text = value.strip()
        if len(text) > MAX_TOKEN:
            fields["client_token"] = f"{MAX_TOKEN} 文字までです"
            return None
        return text

    def _replay(self, con: sqlite3.Connection, token: str | None,
                payload: dict) -> sqlite3.Row | None:
        """同じ `client_token` の再送（§0.9）。**中身が同じなら 200**、違えば 409。"""
        if not token:
            return None
        row = con.execute("SELECT * FROM annotation WHERE client_token = ?", (token,)).fetchone()
        if row is None:
            return None
        same = (row["asset_id"] == payload["asset_id"] and row["shape"] == payload["shape"]
                and row["body"] == payload["body"] and row["group_id"] == payload["group_id"]
                and all(row[k] == payload[k] for k in ("x", "y", "w", "h")))
        if not same:
            raise ReviewError(409, "同じ client_token で違う内容が来ました",
                              code="client_token_conflict", details={"client_token": token})
        return row
