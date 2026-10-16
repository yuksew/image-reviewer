"""P6-2 の合格の線 3 を実機（サーバ）で通す。

1024² と 2048×1536 の絵に注記を作り、`GET .../export?format=json` が同じ座標を返し、
`POST .../export {format:'crops'}` の PNG が式どおりの画素であることを確かめる。

使い方: サーバをデータのコピーで立ててから
  uv run python tools/probe_p6_2.py --base http://127.0.0.1:8791
"""

from __future__ import annotations

import argparse
import io
import json
import sys
import urllib.request

from PIL import Image

HUMAN = {"X-Image-Reviewer-Actor": "human", "Content-Type": "application/json"}


def call(method: str, url: str, body: dict | None = None, headers: dict | None = None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method,
                                 headers=headers or {"Content-Type": "application/json"})
    with urllib.request.urlopen(req) as res:
        raw = res.read()
        kind = res.headers.get("content-type", "")
        if "image/png" in kind:
            return res.status, raw
        return res.status, json.loads(raw or b"null")


def sizes_of(base: str, limit: int = 400) -> list[tuple[int, int]]:
    """そのコピーにある画像の大きさ（重複を除いて、大きい順）。"""
    _, body = call("GET", f"{base}/api/assets?limit={limit}")
    seen: dict[tuple[int, int], str] = {}
    for row in body["items"]:
        width, height = row.get("width"), row.get("height")
        if width and height and (width, height) not in seen:
            seen[(width, height)] = row["id"]
    return sorted(seen, key=lambda wh: wh[0] * wh[1], reverse=True)


def id_of(base: str, size: tuple[int, int], limit: int = 400) -> str:
    _, body = call("GET", f"{base}/api/assets?limit={limit}")
    for row in body["items"]:
        if (row.get("width"), row.get("height")) == size:
            return row["id"]
    raise SystemExit(f"{size} の画像がこのコピーにありません")


def check(label: str, ok: bool, detail: str = "") -> bool:
    print(f"{'ok  ' if ok else 'NG  '}{label}{(' - ' + detail) if detail else ''}")
    return ok


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8791")
    ap.add_argument("--sizes", type=int, default=3, help="確かめる大きさの数（大きい順）")
    args = ap.parse_args()
    base = args.base.rstrip("/")
    failures = 0

    # 実データにある大きさのうち、**大きい順にいくつか**（1024² を含む。式は画素数に比例する）
    found = sizes_of(base)
    targets = [wh for wh in found if wh == (1024, 1024)][:1]
    for wh in found:
        if len(targets) >= args.sizes:
            break
        if wh not in targets:
            targets.append(wh)
    print("確かめる大きさ:", ", ".join(f"{w}x{h}" for w, h in targets))

    for width, height in targets:
        asset = id_of(base, (width, height))
        box = (0.25, 0.5, 0.25, 0.25)
        x, y, w, h = box
        status, made = call("POST", f"{base}/api/assets/{asset}/annotations",
                            {"shape": "rect", "x": x, "y": y, "w": w, "h": h, "body": "実機の確認"},
                            HUMAN)
        note = made["annotation"]["id"]
        failures += not check(f"{width}x{height}: 注記を作れる", status == 201, str(status))
        failures += not check(f"{width}x{height}: 座標は丸めずに戻る",
                              (made["annotation"]["x"], made["annotation"]["y"],
                               made["annotation"]["w"], made["annotation"]["h"]) == box)

        _, doc = call("GET", f"{base}/api/assets/{asset}/annotations/export?format=json")
        row = [a for a in doc["annotations"] if a["id"] == note][0]
        failures += not check(f"{width}x{height}: GET が同じ座標を返す",
                              (row["x"], row["y"], row["w"], row["h"]) == box)
        failures += not check(f"{width}x{height}: 実体の画素数を出す",
                              doc["image"] == {"width": width, "height": height},
                              json.dumps(doc["image"]))
        failures += not check(f"{width}x{height}: GET は crops を null で返す", doc["crops"] is None)

        expected = (int((x + w) * width) - int(x * width),
                    int((y + h) * height) - int(y * height))

        _, crops = call("POST", f"{base}/api/assets/{asset}/annotations/export",
                        {"format": "crops"}, HUMAN)
        crop = [c for c in crops["crops"] if c["annotation_id"] == note][0]
        failures += not check(f"{width}x{height}: 切り出しの画素が式どおり",
                              (crop["width"], crop["height"]) == expected,
                              f"{crop['width']}x{crop['height']} (期待 {expected[0]}x{expected[1]})")

        status, png = call("GET", f"{base}/api/annotations/{note}/crop")
        with Image.open(io.BytesIO(png)) as image:
            failures += not check(f"{width}x{height}: その場の切り出しも PNG で同じ画素",
                                  image.format == "PNG"
                                  and (image.width, image.height) == expected,
                                  f"{image.format} {image.width}x{image.height}")

        # 後始末（このコピーを汚さない）
        call("DELETE", f"{base}/api/annotations/{note}", headers=HUMAN)
    print("すべて ok" if not failures else f"{failures} 件 NG")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
