"""1 万枚の合成 DB を作る（P9 の性能の計測用）。

設計: docs/design.md §12.1（目標値）・§12.2（効かせ方）・§12.3（P8 の実測）
元ねた: `.tmp-audit-redo/p8-1-audit/synth10k.py`（**P8-1 の帯の測定で使った形**。
        `Store` を作って行を入れるだけの形）を、**一覧・サムネイル・走査が測れる形**に広げた物。

**実データには 1 バイトも触らない。** ここで作る物は全部、`--out` の下にできる使い捨て。

作る物:
- `<out>/images/f00..fNN/` に **`--count` 枚の本物の PNG**（走査・登録・サムネイルが本当に通る）。
  - 先頭 `--big` 枚は **1024x1024**（1024px サムネイルの計測用）。
  - 残りは **96x96**（1 万枚を置いても数百 MB にしないため。**一覧と走査の計測には十分**）。
  - どの PNG にも **ComfyUI の API 形式の `prompt` チャンク**が入っている（来歴が本物の道で入る）
- DB は **`scan.scan()` を 1 回通して作る**（`INSERT` を直に書かない。
  **`(path, size, mtime_ns)` が本物と一致する**ので、2 回目の走査が「差分なし」になる）。
- 判断（`review_state`）とタグ（`tag` / `asset_tag`）を少しだけ入れる（一覧の絞り込みが効く形）。
  **（P9 の監査 C-3）判断は `ReviewService.apply_asset()` で台帳に入れる**——
  `asset.review_state` を直接 `UPDATE` すると、起動時の `reconcile()`（台帳が正）が
  全部 `unreviewed` に戻し、`?state=kept` が**0 件への絞り込み**になる（名札と中身が食い違う）。

使い方:
    $env:UV_CACHE_DIR = "C:\\work\\image-reviwer\\.uv-cache"
    uv run --no-sync python -X utf8 tools/make_synthetic_db.py `
        --out .tmp-audit-redo/p9/synth10k --count 10000

`--force` を付けないと、`<out>/db.sqlite3` があるときは作り直さない（**計測の前提を揃える**）。
"""

from __future__ import annotations

import argparse
import json
import os
import random
import shutil
import struct
import sys
import time
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from PIL import Image                                                   # noqa: E402

from image_reviewer import scan as scan_mod                             # noqa: E402
from image_reviewer.store import Store                                  # noqa: E402

MODELS = ["anima-base-v1.safetensors", "anima-dev-v2.safetensors", "illust-xl-v3.safetensors"]
SAMPLERS = ["euler_ancestral", "dpmpp_2m", "ddim", "heun"]
SCHEDULERS = ["normal", "karras", "beta"]
POSITIVE = ("1girl, solo, long hair, blue eyes, school uniform, smile, "
            "outdoors, cherry blossoms, depth of field, masterpiece, best quality")
NEGATIVE = "worst quality, low quality, lowres, bad anatomy, extra digits, watermark"
JA_TEXTS = [
    "桜の下で笑う少女。青い目、長い髪、制服。背景はぼかしてある。",
    "窓辺に座る猫。午後の光。しっぽが長い。",
    "海辺を歩く後ろ姿。夕方のオレンジの光。",
    "雨の日の商店街。傘をさした二人。",
]


def png_chunk(typ: bytes, data: bytes) -> bytes:
    """PNG の 1 チャンク（長さ + 種別 + 中身 + CRC）。"""
    return (struct.pack(">I", len(data)) + typ + data
            + struct.pack(">I", zlib.crc32(typ + data) & 0xFFFFFFFF))


def with_text(base: bytes, key: str, value: str) -> bytes:
    """PNG の `IEND` の直前に `tEXt` を 1 つ挿す（**中身を枚ごとに変える**ため）。

    1 万枚が同じバイト列だと `sha256` が同じになり、`asset.sha256` の UNIQUE で
    **1 枚の asset に 1 万の場所**がぶら下がる（それは 1 万枚の DB ではない）。
    """
    tail = base.rindex(b"IEND") - 4                    # IEND の「長さ」の位置
    return base[:tail] + png_chunk(b"tEXt", key.encode() + b"\x00" + value.encode()) + base[tail:]


def api_graph(seed: int, model: str, sampler: str, scheduler: str, steps: int, size: int,
              with_ja: bool) -> dict:
    """ComfyUI の API 形式のグラフ（`png_meta.analyze_graph()` が本物の値を取り出す形）。"""
    graph = {
        "1": {"class_type": "UNETLoader",
              "inputs": {"unet_name": model, "weight_dtype": "default"}},
        "2": {"class_type": "CLIPLoader",
              "inputs": {"clip_name": "qwen_2.5_vl_7b.safetensors", "type": "qwen_image"}},
        "3": {"class_type": "VAELoader", "inputs": {"vae_name": "qwen_image_vae.safetensors"}},
        "4": {"class_type": "CLIPTextEncode",
              "inputs": {"text": POSITIVE, "clip": ["2", 0]}},
        "5": {"class_type": "CLIPTextEncode",
              "inputs": {"text": NEGATIVE, "clip": ["2", 0]}},
        "6": {"class_type": "EmptyLatentImage",
              "inputs": {"width": size, "height": size, "batch_size": 1}},
        "7": {"class_type": "KSampler",
              "inputs": {"seed": seed, "steps": steps, "cfg": 4.5,
                         "sampler_name": sampler, "scheduler": scheduler, "denoise": 1.0,
                         "model": ["1", 0], "positive": ["4", 0], "negative": ["5", 0],
                         "latent_image": ["6", 0]}},
        "8": {"class_type": "VAEDecode", "inputs": {"samples": ["7", 0], "vae": ["3", 0]}},
        "9": {"class_type": "SaveImage",
              "inputs": {"filename_prefix": "Anima/synth", "images": ["8", 0]}},
    }
    if with_ja:
        graph["10"] = {"class_type": "TextGenerate",
                       "inputs": {"prompt": random.choice(JA_TEXTS), "clip": ["2", 0],
                                  "sampling_mode": {"temperature": 0.7}}}
        graph["11"] = {"class_type": "StringConcatenate",
                       "inputs": {"string_a": ["10", 0], "string_b": "", "delimiter": ", "}}
        graph["4"]["inputs"]["text"] = ["11", 0]
    return graph


def write_images(out: Path, count: int, big: int, folders: int, rng: random.Random) -> tuple[Path, float]:
    """本物の PNG を `count` 枚作る。**先頭 `big` 枚だけ 1024x1024**。"""
    root = out / "images"
    root.mkdir(parents=True, exist_ok=True)
    # 96x96 の下地は 1 枚だけ作って使い回す（**枚ごとに変えるのは tEXt だけ**）
    small = Image.new("RGB", (96, 96))
    px = small.load()
    for y in range(96):
        for x in range(96):
            px[x, y] = ((x * 2) % 256, (y * 2) % 256, ((x + y) * 3) % 256)
    small_buf = _png_bytes(small)

    dirs = [root / f"f{i:02d}" for i in range(folders)]
    for d in dirs:
        d.mkdir(parents=True, exist_ok=True)

    t0 = time.monotonic()
    for i in range(count):
        d = dirs[i % folders]
        path = d / f"{i:06d}.png"
        seed = rng.randrange(0, 2**63)
        size = 1024 if i < big else 96
        model = MODELS[i % len(MODELS)]
        graph = api_graph(seed, model, SAMPLERS[i % len(SAMPLERS)],
                          SCHEDULERS[i % len(SCHEDULERS)], 20 + (i % 12), size,
                          with_ja=(i % 3 == 0))
        text = json.dumps(graph)
        if size == 1024:
            # 大きい方は**復号と縮小が本当に要走る**絵にする（単色だと WebP が一瞬で終わる）
            im = Image.new("RGB", (1024, 1024))
            p = im.load()
            for y in range(0, 1024, 4):
                for x in range(0, 1024, 4):
                    v = ((x * 7 + y * 13 + i * 31) % 256, (x * 3 + y * 5) % 256, (x ^ y) % 256)
                    for dy in range(4):
                        for dx in range(4):
                            p[x + dx, y + dy] = v
            base = _png_bytes(im)
            del im
        else:
            base = small_buf
        path.write_bytes(with_text(base, "prompt", text))
    return root, time.monotonic() - t0


def _png_bytes(im: Image.Image) -> bytes:
    import io
    buf = io.BytesIO()
    im.save(buf, "PNG", compress_level=1)          # 小さく速く（中身は計測に効かない）
    return buf.getvalue()


def seed_rows(store: Store, rng: random.Random, folders: int, big: int) -> dict:
    """判断とタグを少し入れる（**一覧の絞り込みと `known` の道が本当に通る**形にする）。

    **（P9 の監査 C-3）判断は台帳に書く。** 前は `asset.review_state` を直接
    `UPDATE` していたが、`create_app()` の起動時の `ReviewService.reconcile()` は
    **台帳（`decision`）が正**なので、それを**全部 `unreviewed` に戻す**（監査の実測:
    1 万枚すべて `unreviewed`・`decision` 0 件）。そのため
    `GET /api/assets?state=kept` の計測は「**0 件への絞り込み**」を測っていて、
    表の名札（「絞り込み」）と中身が食い違っていた。
    ここは `ReviewService.apply_asset()`（本物の道）で入れる——
    `keep` に `rc.keep.favorite`、`reject` に `rc.reject.other`（必須の理由）。
    """
    counts = {"kept": 0, "rejected": 0, "tags": 0}
    with store.locked() as con:
        names = ["1girl", "solo", "long_hair", "blue_eyes", "school_uniform", "smile",
                 "outdoors", "cherry_blossoms", "depth_of_field", "masterpiece",
                 "worst_quality", "lowres", "cat", "window", "sea", "umbrella"]
        for i, name in enumerate(names):
            con.execute("INSERT OR IGNORE INTO tag(name, known) VALUES (?, ?)",
                        (name, 1 if i < 10 else 0))
        tag_ids = {r["name"]: r["id"] for r in con.execute("SELECT id, name FROM tag")}
        ids = [r["id"] for r in con.execute("SELECT id FROM asset ORDER BY id")]
    with store.transaction() as con:
        for n, asset_id in enumerate(ids):
            if n % 3 == 0:
                for name in rng.sample(names[:10], 3):
                    con.execute("INSERT OR IGNORE INTO asset_tag(asset_id, tag_id, score, source,"
                                " actor, tagged_at) VALUES (?, ?, ?, 'wd14', 'agent',"
                                " '2026-10-18T00:00:00Z')", (asset_id, tag_ids[name], rng.random()))
                    counts["tags"] += 1

    from image_reviewer.review import ReviewService                      # 循環を避けて局所で

    review = ReviewService(store)                 # 台帳が正（前の判断が無いので何もしない）
    for n, asset_id in enumerate(ids):
        if n % 7 == 0:
            review.apply_asset(asset_id, "keep", reason_code_id="rc.keep.favorite",
                               actor="human")
            counts["kept"] += 1
        elif n % 11 == 0:
            review.apply_asset(asset_id, "reject", reason_code_id="rc.reject.other",
                               actor="human")
            counts["rejected"] += 1
    return counts


def main() -> int:
    ap = argparse.ArgumentParser(description="1 万枚の合成 DB を作る（P9 の計測用）")
    ap.add_argument("--out", default=str(ROOT / ".tmp-audit-redo" / "p9" / "synth10k"))
    ap.add_argument("--count", type=int, default=10000)
    ap.add_argument("--big", type=int, default=24, help="1024x1024 にする枚数（先頭から）")
    ap.add_argument("--folders", type=int, default=20, help="画像を分けるフォルダの数")
    ap.add_argument("--seed", type=int, default=9)
    ap.add_argument("--force", action="store_true", help="既にあっても作り直す")
    ap.add_argument("--no-seed-rows", action="store_true", help="判断とタグを入れない")
    args = ap.parse_args()

    out = Path(args.out)
    if (out / "db.sqlite3").exists() and not args.force:
        print(f"既にある（作り直さない）: {out}/db.sqlite3。作り直すなら --force")
        return 0
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True, exist_ok=True)
    rng = random.Random(args.seed)

    print(f"1. 画像を {args.count} 枚作る（1024x1024 が {args.big} 枚・残りは 96x96・"
          f"{args.folders} フォルダ）")
    root, sec = write_images(out, args.count, args.big, args.folders, rng)
    size = sum(f.stat().st_size for f in root.rglob("*.png"))
    print(f"   {sec:.1f} 秒 / {size / 1e6:.1f} MB / {root}")

    print("2. 走査して登録する（`scan.scan()` をそのまま通す。**`INSERT` を直に書かない**）")
    store = Store(out)
    try:
        t0 = time.monotonic()
        stats = scan_mod.scan(store, [str(root)])
        first = time.monotonic() - t0
        print(f"   初回走査 {first:.1f} 秒 / created={stats['created']} known={stats['known']}"
              f" images={stats['images']} with_provenance={stats['with_provenance']}"
              f" missing={stats['missing']}")

        if not args.no_seed_rows:
            print("3. 判断とタグを入れる")
            t0 = time.monotonic()
            counts = seed_rows(store, rng, args.folders, args.big)
            print(f"   {time.monotonic() - t0:.1f} 秒 / {counts}")
    finally:
        store.close()

    with Store(out) as store:
        with store.locked() as con:
            kept = con.execute("SELECT count(*) AS n FROM asset"
                               " WHERE review_state = 'kept'").fetchone()["n"]
            decisions = con.execute("SELECT count(*) AS n FROM decision").fetchone()["n"]
        print(f"4. できた物: asset={store.stats()['assets']} "
              f"locations={store.stats()['locations']} "
              f"with_provenance={store.stats()['with_provenance']} "
              f"kept={kept} decision={decisions}")
    db_size = (out / "db.sqlite3").stat().st_size + (out / "db.sqlite3-wal").stat().st_size \
        if (out / "db.sqlite3-wal").exists() else (out / "db.sqlite3").stat().st_size
    print(f"   DB {db_size / 1e6:.1f} MB / {out}")
    print("まとめ: できた（**実データには触っていない**）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
