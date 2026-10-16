"""比較の重い見方（P5-3）のテスト — pHash / dHash / SSIM / ヒートマップ / 似ている順。

設計: docs/p5-design.md §0.1（P5-3）・§0.5 G6（条件の外でも `force`）・§0.7（**実測 F5**）・
      §0.8 D1（`phash_distance` をキャッシュしない・`algo_version`）・§6.2（指標）、
      docs/comparison.md §2.3（位置合わせとヒートマップ）・§4（定義はここが正）・§4.1（似ている順）

**絶対値を主張しない**（点検 C15）。縮小のフィルタ（`Image.LANCZOS`）や `ALGO_VERSION` を
変えると値は変わるので、ここで固定するのは**性質**（同じ絵なら 0 / 縮小した写しは近い /
別の絵は遠い / 決定的である）だけにする。

`tmp_path` は `tests/conftest.py` が用意する。`Store` は必ず `with` で閉じる
（開いたままの接続は一時フォルダの後始末で落ちる）。
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import time
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from image_reviewer import compare, db, thumbs
from image_reviewer.store import Store

REPO = Path(__file__).resolve().parents[1]
REAL_DB = REPO / ".data" / "db.sqlite3"


# ---- 道具 ----


def make_meta(**kw) -> dict:
    """`png_meta.analyze_graph()` が返す形の来歴（既定は 2 枚で同じになる値）。"""
    meta = {
        "model": "anima-turbo-v1.1.safetensors", "clip": "clip_l.safetensors",
        "vae": "vae.safetensors", "llm": None, "loras": [],
        "sampler": "euler", "scheduler": "normal", "steps": 10, "cfg": 1.0, "denoise": 1.0,
        "seed": "338134650120909", "width": 320, "height": 240,
        "positive_literal": "1girl, solo", "negative_literal": None,
        "final_prompt": "1girl, solo", "final_prompt_source": "png_literal",
        "ja_text": None, "ja_source": None, "textgen_params": None, "has_textgen": False,
        "init_image": None, "node_types": {"KSampler": 1, "SaveImage": 1},
        "unresolved": [], "primary_ksampler": "5",
    }
    meta.update(kw)
    return meta


def pattern(seed: int = 1, w: int = 320, h: int = 240) -> Image.Image:
    """決まった絵（ノイズではなく、なだらかな濃淡＋円）。縮小や再圧縮に強い形にする。

    一様なノイズだと縮小のたびにハッシュが変わって「近い」の性質を確かめられない。
    """
    rng = np.random.default_rng(seed)
    y, x = np.mgrid[0:h, 0:w]
    base = np.sin(x / 23.0) * 60 + np.cos(y / 17.0) * 40 + 128 + (x / w) * 60
    img = np.repeat(base[:, :, None], 3, axis=2)
    for _ in range(5):
        cx, cy, r = (int(rng.integers(20, w - 20)), int(rng.integers(20, h - 20)),
                     int(rng.integers(12, 40)))
        mask = (x - cx) ** 2 + (y - cy) ** 2 < r * r
        img[mask] = rng.integers(0, 255, 3)
    return Image.fromarray(np.clip(img, 0, 255).astype(np.uint8), "RGB")


def save(img: Image.Image, path: Path, fmt: str | None = None) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    img.save(path, fmt)
    return path


def shifted(img: Image.Image, dx: int, dy: int) -> Image.Image:
    """中身を `dx` / `dy` だけ動かした絵（はみ出した所は黒）。"""
    arr = np.asarray(img.convert("L"), dtype=np.uint8)
    h, w = arr.shape
    out = np.zeros_like(arr)
    src_y = slice(max(0, -dy), min(h, h - dy))
    src_x = slice(max(0, -dx), min(w, w - dx))
    dst_y = slice(max(0, dy), min(h, h + dy))
    dst_x = slice(max(0, dx), min(w, w + dx))
    out[dst_y, dst_x] = arr[src_y, src_x]
    return Image.fromarray(out, "L").convert("RGB")


def register_file(store: Store, path: Path, name: str, *, meta: dict | None = None,
                  width: int = 320, height: int = 240) -> str:
    """実体のあるファイルを 1 枚登録する（`location` のパスが実在する＝指標を計算できる）。"""
    digest = hashlib.sha256(f"{name}:{path}".encode("utf-8")).hexdigest()
    asset_id, _ = store.register(
        sha256=digest, path=str(path), size=path.stat().st_size,
        mtime_ns=path.stat().st_mtime_ns, width=width, height=height,
        fmt=path.suffix.lstrip("."), meta=meta, note=None)
    return asset_id


def row_of(document: dict, key: str) -> dict:
    for row in document["diff"]["changed"] + document["diff"]["same"]:
        if row["key"] == key:
            return row
    raise AssertionError(f"差分表に {key} が無い")


@pytest.fixture
def app_client(tmp_path, monkeypatch):
    """`TestClient` つきの app。**`Store` を閉じる**（`tests/.tmp` の後始末のため）。"""
    monkeypatch.setenv("IMAGE_REVIEWER_DATA", str(tmp_path / "data"))
    from fastapi.testclient import TestClient

    from image_reviewer.app import create_app

    app = create_app()
    try:
        with TestClient(app, base_url="http://127.0.0.1") as client:
            yield client, app
    finally:
        app.state.store.close()


# ---- 1. pHash の性質（絶対値は主張しない。点検 C15）----


def test_the_same_image_has_distance_zero_and_a_stable_16_hex_hash(tmp_path):
    """同じ画像 → 距離 0。ハッシュは 16 進 16 文字の小文字で、2 回計算しても同じ。"""
    path = save(pattern(1), tmp_path / "a.png")

    first = compare.hash_file(path)
    second = compare.hash_file(path)

    assert first == second, "同じ画像のハッシュが 2 回で変わった（決定的でない）"
    for value in first:
        assert compare.HASH_RE.match(value), f"16 進 16 文字の小文字でない: {value!r}"
        assert value == value.lower() and len(value) == 16
    assert compare.hash_distance(first[0], first[0]) == 0
    assert compare.hash_distance(first[0], first[1]) is not None
    # 分からない方（未計算）を 0 と言わない
    assert compare.hash_distance(first[0], None) is None
    assert compare.hash_distance(None, None) is None


def test_a_resized_and_re_encoded_copy_is_near_and_an_unrelated_image_is_far(tmp_path):
    """縮小・再圧縮した写しは近い（しきい値以下）。別の絵はずっと遠い。

    **絶対値ではなく性質**（点検 C15。縮小のフィルタを変えると値は動く）。
    """
    original = save(pattern(1), tmp_path / "a.png")
    copy = save(pattern(1).resize((192, 144), Image.LANCZOS), tmp_path / "a_small.jpg", "JPEG")
    other = save(pattern(2), tmp_path / "b.png")

    near = compare.hash_file(original)
    near_copy = compare.hash_file(copy)
    far = compare.hash_file(other)

    distance_near = compare.hash_distance(near[0], near_copy[0])
    distance_far = compare.hash_distance(near[0], far[0])
    assert distance_near is not None and distance_far is not None
    assert distance_near <= compare.PHASH_NEAR_THRESHOLD, f"写しの距離 {distance_near}"
    assert distance_far > compare.PHASH_NEAR_THRESHOLD * 3, f"別の絵の距離 {distance_far}"
    assert distance_far > distance_near


def test_dhash_reads_the_horizontal_gradient_and_differs_from_phash(tmp_path):
    """dHash は**横方向の増減**（`comparison.md` §4）。pHash とは別のものを見ている。

    右へ明るくなる絵は「増えた」が続くのでビットがほぼ全部立ち、逆向きなら全部倒れる。
    pHash（構図・大きな明暗の配置）とは違う値になる。
    """
    ramp = np.tile(np.linspace(0, 255, 256), (128, 1)).astype(np.uint8)
    up = Image.fromarray(ramp, "L").convert("RGB")
    down = Image.fromarray(255 - ramp, "L").convert("RGB")

    up_phash, up_dhash = compare.hashes_of_image(up)
    down_phash, down_dhash = compare.hashes_of_image(down)

    assert bin(int(up_dhash, 16)).count("1") >= 56, "明るくなる向きを拾えていない"
    assert bin(int(down_dhash, 16)).count("1") <= 8, "暗くなる向きを拾えていない"
    assert up_dhash != down_dhash and up_phash != down_phash
    # 同じ 1 枚でも pHash と dHash は別の値（片方が他方の写しになっていない）
    assert up_phash != up_dhash, "pHash と dHash が同じ値（dHash が勾配を見ていない）"
    # 逆向きの pHash も別（低周波の配置が反転している）
    assert up_phash != down_phash


def test_the_hash_is_written_by_the_thumbnail_decode_and_only_decodes_once(
        tmp_path, monkeypatch):
    """**実測 F5**: pHash はサムネイルを作る復号と同じ 1 枚から計算する（背景ジョブにしない）。

    サムネイルが無いときは **復号 1 回**でサムネイルとハッシュの両方ができる。
    2 回目の要求はハッシュがあるので復号しない（サムネイルも既にある）。
    """
    path = save(pattern(1), tmp_path / "root" / "a.png")
    opened = []
    real_open = Image.open

    def counting_open(*args, **kw):
        opened.append(args[0] if args else None)
        return real_open(*args, **kw)

    monkeypatch.setattr(Image, "open", counting_open)
    with Store(tmp_path / "data") as store:
        asset_id = register_file(store, path, "a")
        assert store.asset(asset_id)["phash"] is None

        thumbs.ensure_thumb(str(path), store.data_dir, store.asset(asset_id)["sha256"], 256,
                            on_image=lambda im: compare.capture_hashes(store, asset_id, im))
        assert len(opened) == 1, f"サムネイルとハッシュで復号が {len(opened)} 回（実測 F5 は 1 回）"
        got = store.asset(asset_id)
        assert got["phash"] and got["dhash"], "サムネイルを作る復号でハッシュが入っていない"
        assert compare.HASH_RE.match(got["phash"]) and compare.HASH_RE.match(got["dhash"])

        # 2 回目: サムネイルもハッシュもあるので復号しない
        opened.clear()
        thumbs.ensure_thumb(str(path), store.data_dir, got["sha256"], 256,
                            on_image=lambda im: compare.capture_hashes(store, asset_id, im))
        assert opened == [], "既にあるのに復号した"
        assert compare.ensure_hashes(store, asset_id, path) is None


def test_the_hash_is_computed_alone_when_the_thumbnail_already_exists(tmp_path, monkeypatch):
    """サムネイルが既にあってハッシュが無いときだけ、**もう 1 回復号**してハッシュを作る。

    設計 §0.7 の「ハッシュだけ計算する」道。1 枚につき 1 回で終わる（次からは復号しない）。
    """
    path = save(pattern(1), tmp_path / "root" / "a.png")
    with Store(tmp_path / "data") as store:
        asset_id = register_file(store, path, "a")
        sha = store.asset(asset_id)["sha256"]
        thumbs.ensure_thumb(str(path), store.data_dir, sha, 256)     # 先にサムネイルだけ作る
        assert store.asset(asset_id)["phash"] is None

        opened = []
        real_open = Image.open
        monkeypatch.setattr(Image, "open",
                            lambda *a, **k: (opened.append(1), real_open(*a, **k))[1])
        got = compare.ensure_hashes(store, asset_id, path)
        assert got is not None and len(opened) == 1, "ハッシュだけの道が復号 1 回でない"
        assert store.asset(asset_id)["phash"] == got[0]
        # 2 回目は何もしない（復号しない）
        opened.clear()
        assert compare.ensure_hashes(store, asset_id, path) is None
        assert opened == []


def test_set_hashes_refuses_a_bad_shape(tmp_path):
    """16 進 16 文字の小文字だけを受ける（符号なし 64bit を TEXT で持つ規則）。"""
    path = save(pattern(1), tmp_path / "root" / "a.png")
    with Store(tmp_path / "data") as store:
        asset_id = register_file(store, path, "a")
        for bad in ("", "0" * 15, "0" * 17, "A" * 16, "z" * 16, None, 123):
            with pytest.raises(ValueError):
                store.set_hashes(asset_id, bad, "0" * 16)
        store.set_hashes(asset_id, "0" * 16, "f" * 16)
        assert store.asset(asset_id)["phash"] == "0" * 16


# ---- 2. SSIM / changed_fraction / mean_abs（`comparison.md` §4）----


def test_ssim_is_one_for_identical_and_below_one_for_a_shift(tmp_path):
    """同じ 2 枚で SSIM ≈ 1.0、`mean_abs` は 0。ずらした絵では 1.0 を下回る。"""
    path = save(pattern(1), tmp_path / "a.png")
    same = save(pattern(1), tmp_path / "a2.png")
    moved = save(shifted(pattern(1), 12, 7), tmp_path / "a_shift.png")

    identical = compare.compute_pair_metrics(path, same)
    assert identical["ssim"] == pytest.approx(1.0, abs=1e-9)
    assert identical["mean_abs"] == 0.0
    assert identical["changed_fraction"] == 0.0

    got = compare.compute_pair_metrics(path, moved)
    assert got["ssim"] < 1.0, f"ずらした絵の SSIM が {got['ssim']}（下がっていない）"
    assert got["mean_abs"] > 0.0
    assert 0.0 <= got["changed_fraction"] <= 1.0


def test_reduced_gray_keeps_the_aspect_and_the_long_side(tmp_path):
    """縮小は**長辺** `METRIC_SIZE`（`comparison.md` §4）。アスペクトは保つ。"""
    path = save(pattern(1, 320, 240), tmp_path / "wide.png")
    tall = save(pattern(2, 240, 320), tmp_path / "tall.png")
    assert compare.reduced_gray(path).shape == (240 * compare.METRIC_SIZE // 320,
                                                compare.METRIC_SIZE)
    assert compare.reduced_gray(tall).shape == (compare.METRIC_SIZE,
                                                compare.METRIC_SIZE * 240 // 320)


# ---- 3. 指標のキャッシュ（設計 §6.2・点検 D1）----


def test_the_metrics_cache_is_used_and_algo_version_invalidates_it(tmp_path, monkeypatch):
    """2 回目は計算しない。**`algo_version` を上げると全部無効**になり、行も書き替わる。"""
    a = save(pattern(1), tmp_path / "a.png")
    b = save(pattern(2), tmp_path / "b.png")
    with Store(tmp_path / "data") as store:
        a_id = register_file(store, a, "a")
        b_id = register_file(store, b, "b")
        calls = []
        real = compare.compute_pair_metrics

        def counting(*args, **kw):
            calls.append(args)
            return real(*args, **kw)

        monkeypatch.setattr(compare, "compute_pair_metrics", counting)
        first = compare.pair_report(store, a_id, b_id)
        assert len(calls) == 1 and first["cached"] is False
        second = compare.pair_report(store, a_id, b_id)
        assert len(calls) == 1, "2 回目に計算し直している（キャッシュを使っていない）"
        assert second["cached"] is True
        assert (second["ssim"], second["changed_fraction"], second["mean_abs"]) == (
            first["ssim"], first["changed_fraction"], first["mean_abs"])

        # 版を上げると引けなくなる（引くときも必ず版を条件に入れている）
        monkeypatch.setattr(compare, "ALGO_VERSION", compare.ALGO_VERSION + 1)
        third = compare.pair_report(store, a_id, b_id)
        assert len(calls) == 2, "版をまたいでキャッシュを読んだ（点検 D1）"
        assert third["cached"] is False
        assert third["algo_version"] == compare.ALGO_VERSION

        rows = store.con.execute(
            "SELECT a_id, b_id, algo_version FROM comparison_cache").fetchall()
        assert len(rows) == 1, "同じ組の行が版ごとに増えている（主キーは (a_id, b_id)）"
        assert rows[0]["algo_version"] == compare.ALGO_VERSION
        # 主キーは id の小さい順に正規化する
        assert (rows[0]["a_id"], rows[0]["b_id"]) == tuple(sorted((a_id, b_id)))
        # **点検 D1**: ハミング距離は列に持たない（マイクロ秒で出るので書き込む方が高い）
        columns = {r["name"] for r in store.con.execute("PRAGMA table_info(comparison_cache)")}
        assert "phash_distance" not in columns
        # `ix_comparison_a` も作らない（主キーの前置と重なる）
        indexes = {r["name"] for r in store.con.execute("PRAGMA index_list(comparison_cache)")}
        assert "ix_comparison_a" not in indexes


def test_the_pair_report_reduces_each_image_once_for_metrics_and_heatmap(tmp_path, monkeypatch):
    """1 組の要求で 256px の縮小は**画像ごとに 1 回**（指標とヒートマップで共有する）。

    実測では 1024² の 1 枚で復号＋縮小が 9.6 ms。指標とヒートマップで別々に縮小すると、
    1 組あたり 2 枚ぶん（約 20 ms）を無駄に使う。設計 §8 の 50ms に効く。
    """
    a = save(pattern(1), tmp_path / "a.png")
    b = save(pattern(1).resize((240, 180), Image.LANCZOS), tmp_path / "b.png", "JPEG")
    with Store(tmp_path / "data") as store:
        a_id = register_file(store, a, "a", meta=make_meta(seed="42"))
        b_id = register_file(store, b, "b", meta=make_meta(seed="42"))
        calls = []
        real = compare.reduced_gray

        def counting(*args, **kw):
            calls.append(args)
            return real(*args, **kw)

        monkeypatch.setattr(compare, "reduced_gray", counting)
        got = compare.pair_report(store, a_id, b_id)
        assert got["heatmap"]["available"] is True, "同じ seed で差分が出ていない"
        assert len(calls) == 2, f"256px の縮小が {len(calls)} 回（画像ごとに 1 回であること）"
        # 2 回目はキャッシュに当たるので、差分のための縮小だけ（指標は計算しない）
        calls.clear()
        compare.pair_report(store, a_id, b_id)
        assert len(calls) == 2, f"キャッシュに当たったのに {len(calls)} 回縮小した"


def test_the_pair_metrics_do_not_read_uncommitted_rows(tmp_path, monkeypatch):
    """**監査 B3**: キャッシュの読みは錠の下で行う（未コミットの行を読まない）。

    `compute_pair_metrics` の中で別スレッドが書いた未コミットの行は見えない、を固定する。
    ここでは「計算の最中に ROLLBACK される取引」を作り、その行がキャッシュとして
    読まれないことを確かめる（読むのは計算の**前**なので、取引中に読まない）。
    """
    a = save(pattern(1), tmp_path / "a.png")
    b = save(pattern(2), tmp_path / "b.png")
    with Store(tmp_path / "data") as store:
        a_id = register_file(store, a, "a")
        b_id = register_file(store, b, "b")
        real = compare.compute_pair_metrics

        def hijack(*args, **kw):
            # 計算の最中に「未コミットのキャッシュ行」を作って ROLLBACK する
            class Boom(Exception):
                pass

            try:
                with store.transaction() as con:
                    con.execute(
                        "INSERT INTO comparison_cache(a_id, b_id, algo_version, ssim,"
                        " changed_fraction, mean_abs, computed_at) VALUES (?,?,?,?,?,?,?)"
                        " ON CONFLICT(a_id, b_id) DO UPDATE SET ssim = 0.123",
                        (*sorted((a_id, b_id)), 999, 0.123, 0.5, 99.0, db.now()))
                    raise Boom()
            except Boom:
                pass
            return real(*args, **kw)

        monkeypatch.setattr(compare, "compute_pair_metrics", hijack)
        got = compare.pair_report(store, a_id, b_id)
        assert got["ssim"] != 0.123, "未コミットの行を読んだ（監査 B3）"
        rows = store.con.execute(
            "SELECT algo_version, ssim FROM comparison_cache").fetchall()
        assert len(rows) == 1 and rows[0]["algo_version"] == compare.ALGO_VERSION
        assert rows[0]["ssim"] == got["ssim"]


# ---- 4. 差分ヒートマップ（点検 G6・`comparison.md` §2.3）----


def test_the_heatmap_is_enabled_for_the_same_seed_and_for_a_near_pair():
    """規則は `heatmap_enabled()` の 1 か所（点検 G6）。**同じ seed** か **pHash 距離が閾値以下**。"""
    ok, reason = compare.heatmap_enabled("123", "123", None)
    assert ok is True and reason is None
    ok, reason = compare.heatmap_enabled(None, None, compare.HEATMAP_DISTANCE_THRESHOLD)
    assert ok is True and reason is None, "近い組（距離が閾値ちょうど）で出せない"
    # 条件の外は理由を 1 行返す
    ok, reason = compare.heatmap_enabled("1", "2", compare.HEATMAP_DISTANCE_THRESHOLD + 1)
    assert ok is False and isinstance(reason, str) and reason
    assert str(compare.HEATMAP_DISTANCE_THRESHOLD) in reason, "しきい値を理由に書いていない"
    # seed が無い（来歴なしの写真）を「同じ seed」と言わない
    ok, _ = compare.heatmap_enabled(None, None, None)
    assert ok is False
    ok, reason = compare.heatmap_enabled("1", "1", None)
    assert ok is True, "同じ seed なら pHash が未計算でも出せる"
    # 距離の定義（`PHASH_NEAR_THRESHOLD` と同じ値を使う。別の値を発明しない）
    assert compare.HEATMAP_DISTANCE_THRESHOLD == compare.PHASH_NEAR_THRESHOLD


def test_a_near_pair_produces_an_image_and_a_shifted_pair_is_aligned(tmp_path):
    """近い組では画像が出る。少しずれた組は**位置合わせしてから**重ねる。"""
    a = save(pattern(1), tmp_path / "a.png")
    a2 = save(pattern(1), tmp_path / "a2.png")
    moved = save(shifted(pattern(1), 30, 0), tmp_path / "a_shift.png")

    got = compare.build_heatmap(a, a2)
    assert got["available"] is True and got["aligned"] is True
    assert got["image"].startswith("data:image/webp;base64,")
    assert got["dx"] == 0 and got["dy"] == 0

    shifted_got = compare.build_heatmap(a, moved)
    assert shifted_got["available"] is True
    # 320px の絵を 256px に縮小しているので、30px のずれは 24px として見つかる
    assert shifted_got["dx"] < 0, "ずれの向きを取り違えている"
    assert abs(abs(shifted_got["dx"]) - 24) <= 2


def test_a_large_shift_says_it_cannot_align_instead_of_showing_an_image(tmp_path):
    """**位置が合いません**を返す（黙って誤魔化した絵を出さない。`comparison.md` §2.3）。

    平行移動だけを扱うと決めているので、縮小の座標で `ALIGN_MAX_SHIFT` を超えるずれは
    「合わない」と言う。中身が同じでも、である。
    """
    a = save(pattern(1), tmp_path / "a.png")
    big = save(shifted(pattern(1), 100, 0), tmp_path / "big_shift.png")

    got = compare.build_heatmap(a, big)
    assert got["available"] is False and got["aligned"] is False
    assert got["image"] is None
    assert "位置が合いません" in got["reason"]
    assert abs(got["dx"]) > compare.ALIGN_MAX_SHIFT or abs(got["dy"]) > compare.ALIGN_MAX_SHIFT


def test_an_unrelated_pair_is_never_called_aligned(tmp_path):
    """**監査 A2**: 無関係な 2 枚に「合わせた」と言って絵を返さない（`comparison.md` §2.3）。

    峰の比（`max / mean(|corr|)`）は**正規化した相互パワースペクトルのせいで**無関係な
    2 枚でもノイズの最大値の比（4〜7）にしかならない。前のしきい値 1.5 はその床より下で、
    **決して発火しなかった**（±64px に入ったノイズの峰が「合った」ことになっていた）。
    ここでは独立な乱数の 2 枚を使い、「峰は立つが一致しない」ことを固定する。
    """
    rng = np.random.default_rng(7)
    left = save(Image.fromarray(rng.integers(0, 256, (240, 320, 3), dtype=np.uint8), "RGB"),
                tmp_path / "left.png")
    rng = np.random.default_rng(8)
    right = save(Image.fromarray(rng.integers(0, 256, (240, 320, 3), dtype=np.uint8), "RGB"),
                 tmp_path / "right.png")

    got = compare.build_heatmap(left, right)

    assert got["available"] is False and got["aligned"] is False
    assert got["image"] is None
    assert "位置が合いません" in got["reason"]
    # 前のしきい値（1.5）ではこの組が「合わせた」ことになっていた（監査 A2 の再現）
    assert got["peak_ratio"] > 1.5, f"峰の比が立っていない: {got['peak_ratio']}"
    assert got["corr"] is None or got["corr"] < compare.ALIGN_MIN_CORR, \
        f"一致していないのに一致度が高い: {got['corr']}"


def test_a_forced_pair_of_unrelated_images_returns_no_image(tmp_path):
    """**監査 A2 の再現**: 無関係な 2 枚を `force` しても「合わせた」絵を返さない。

    この 2 枚は**峰の比が足切り（`ALIGN_MIN_PEAK_RATIO`）の上**なので、落としているのは
    **合わせた重なりの一致度**（`ALIGN_MIN_CORR`）である。以前はここで
    「全面が赤の絵」が `available: True` で返っていた（実測: 峰の比 17.6 / 一致度 -0.107）。
    """
    a = save(pattern(1), tmp_path / "a.png")
    other = save(pattern(2).resize((160, 120), Image.LANCZOS).convert("L").convert("RGB"),
                 tmp_path / "other.png")
    with Store(tmp_path / "data") as store:
        a_id = register_file(store, a, "a", meta=make_meta(seed="1"))
        other_id = register_file(store, other, "b", meta=make_meta(seed="2"))
        store.set_hashes(a_id, "0" * 16, "f" * 16)
        store.set_hashes(other_id, "f" * 16, "0" * 16)          # 規則では「遠い」（距離 64）

        got = compare.pair_report(store, a_id, other_id, force=True)
        assert got["heatmap"]["enabled"] is False
        assert got["heatmap"]["forced"] is True
        assert got["heatmap"]["available"] is False, "無関係な組に「合わせた」絵を返した（監査 A2）"
        assert got["heatmap"]["image"] is None
        assert "位置が合いません" in got["heatmap"]["reason"]
        assert got["heatmap"]["peak_ratio"] > compare.ALIGN_MIN_PEAK_RATIO, \
            "足切り（峰の比）ではなく一致度で落ちていることを確かめる"
        assert got["heatmap"]["corr"] < compare.ALIGN_MIN_CORR
        # 指標は返る（画像だけが無い）
        assert got["ssim"] is not None


def test_a_shifted_copy_and_a_rescaled_copy_are_aligned_with_the_measured_margin(tmp_path):
    """**監査 A2**: 同じ絵（ずらした写し・縮小して再圧縮した写し）は**今も合わせられる**。

    実測（§0.7）: ずらした写し 1.000 / 同じ絵の縮小＋再圧縮 0.949 で、しきい値 0.80 の上。
    ずれの向きと大きさは 256px の縮小の座標で見る（320px の 30px はずれは 24px）。
    """
    a = save(pattern(1), tmp_path / "a.png")
    moved = save(shifted(pattern(1), 30, 0), tmp_path / "a_shift.png")
    small = save(pattern(1).resize((240, 180), Image.LANCZOS), tmp_path / "a_small.jpg", "JPEG")

    same = compare.build_heatmap(a, a)
    assert same["available"] is True and same["dx"] == 0 and same["dy"] == 0
    assert same["corr"] == pytest.approx(1.0, abs=1e-9)

    shifted_got = compare.build_heatmap(a, moved)
    assert shifted_got["available"] is True, "同じ絵の写しを合わせられない"
    assert shifted_got["corr"] >= compare.ALIGN_MIN_CORR
    assert shifted_got["dx"] < 0, "ずれの向きを取り違えている"
    assert abs(abs(shifted_got["dx"]) - 24) <= 2

    rescaled = compare.build_heatmap(a, small)
    assert rescaled["available"] is True, "縮小・再圧縮した写しを合わせられない"
    assert rescaled["corr"] >= compare.ALIGN_MIN_CORR

    with Store(tmp_path / "data") as store:
        # 同じ seed の組（規則でも開く）が `pair_report` でも画像になる
        a_id = register_file(store, a, "a", meta=make_meta(seed="42"))
        b_id = register_file(store, small, "b", meta=make_meta(seed="42"))
        got = compare.pair_report(store, a_id, b_id)
        assert got["heatmap"]["enabled"] is True
        assert got["heatmap"]["available"] is True
        assert got["heatmap"]["image"].startswith("data:image/webp;base64,")


def test_the_pair_report_enables_for_the_same_seed_disables_for_a_far_pair_and_forces(
        tmp_path):
    """点検 G6: 遠い組は既定で無効（理由つき）、**`force=True` なら出す**。

    **監査 A2**: `force` で画像が出るのは、**画素が実際に合う組**だけ。ここで使う「遠い」枚は
    「規則では遠い（別 seed・pHash 距離 64 以上）が、絵は同じで 30px ずれている」写しにする
    （規則と画素は別物）。合わない絵を `force` しても画像は出ない＝
    `test_a_forced_pair_of_unrelated_images_returns_no_image`。
    以前はここに別の絵（`pattern(2)`）を置いていて、**峰が弱いことを見ていない**ので
    「合わせた」ことになっていた（監査 A2 の指摘そのもの）。
    """
    a = save(pattern(1), tmp_path / "a.png")
    near = save(pattern(1).resize((240, 180), Image.LANCZOS), tmp_path / "near.png", "JPEG")
    moved = save(shifted(pattern(1), 30, 0), tmp_path / "moved.png")
    with Store(tmp_path / "data") as store:
        # 同じ seed の 2 枚（絵も近い。同じ seed で条件が開くことを見る）
        a_id = register_file(store, a, "a", meta=make_meta(seed="42"))
        same_seed = register_file(store, near, "c", meta=make_meta(seed="42"))
        far_id = register_file(store, moved, "b", meta=make_meta(seed="7"))
        store.set_hashes(a_id, "0f0f0f0f0f0f0f0f", "ffffffffffffffff")
        store.set_hashes(same_seed, "f0f0f0f0f0f0f0f0", "0000000000000000")
        store.set_hashes(far_id, "aaaaaaaaaaaaaaaa", "5555555555555555")

        enabled = compare.pair_report(store, a_id, same_seed)
        assert enabled["heatmap"]["enabled"] is True, "同じ seed なのに無効"
        assert enabled["heatmap"]["reason"] is None
        assert enabled["heatmap"]["available"] is True
        assert enabled["heatmap"]["image"].startswith("data:image/webp;base64,")

        far = compare.pair_report(store, a_id, far_id)
        assert far["phash_distance"] == compare.hash_distance("0f0f0f0f0f0f0f0f",
                                                              "aaaaaaaaaaaaaaaa")
        assert far["phash_distance"] > compare.HEATMAP_DISTANCE_THRESHOLD
        assert far["heatmap"]["enabled"] is False
        assert far["heatmap"]["image"] is None, "無効なのに画像を作っている"
        assert "同じ seed" in far["heatmap"]["reason"]
        assert str(compare.HEATMAP_DISTANCE_THRESHOLD) in far["heatmap"]["reason"]
        # 指標は無効でも返る（無駄に隠さない）
        assert 0.0 <= far["changed_fraction"] <= 1.0 and far["mean_abs"] >= 0.0

        forced = compare.pair_report(store, a_id, far_id, force=True)
        assert forced["heatmap"]["enabled"] is False and forced["heatmap"]["forced"] is True
        assert forced["heatmap"]["available"] is True
        assert forced["heatmap"]["image"].startswith("data:image/webp;base64,")
        # 規則の外でも、絵が合うなら位置合わせは効く（監査 A2 の一致度も残る）
        assert forced["heatmap"]["corr"] is not None
        assert forced["heatmap"]["corr"] >= compare.ALIGN_MIN_CORR
        assert forced["heatmap"]["dx"] < 0, "ずれの向きを取り違えている"


def test_a_forced_far_pair_with_a_large_shift_says_it_cannot_align(tmp_path):
    """条件の外で `force` しても、**位置が合わなければ画像を出さない**（設計 §0.5 G6）。

    遠い組（規則では pHash 距離 64 で無効）を `force` で出そうとする。中身が
    大きくずれているので、平行移動では合わせられない＝「位置が合いません」。
    """
    a = save(pattern(1), tmp_path / "a.png")
    far = save(shifted(pattern(1), 100, 0), tmp_path / "far_shift.png")
    with Store(tmp_path / "data") as store:
        a_id = register_file(store, a, "a", meta=make_meta(seed="1"))
        far_id = register_file(store, far, "far", meta=make_meta(seed="2"))
        store.set_hashes(a_id, "0" * 16, "f" * 16)
        store.set_hashes(far_id, "f" * 16, "0" * 16)          # 規則では「遠い」（距離 64）

        got = compare.pair_report(store, a_id, far_id, force=True)
        assert got["phash_distance"] == 64
        assert got["heatmap"]["enabled"] is False
        assert got["heatmap"]["forced"] is True
        assert got["heatmap"]["available"] is False
        assert got["heatmap"]["image"] is None
        assert "位置が合いません" in got["heatmap"]["reason"]
        # 指標は返る（画像だけが無い）
        assert got["ssim"] is not None


def test_the_document_carries_the_pair_rules_so_the_screen_does_not_recompute(tmp_path):
    """規則はサーバ（`pairs`）。画面は「押せるか」と「理由」をそのまま描く。

    **「派生関係」の条件は P7 まで外す**（設計 §0.5 G6。その列がまだ無い）。
    """
    a = save(pattern(1), tmp_path / "a.png")
    b = save(pattern(2), tmp_path / "b.png")
    with Store(tmp_path / "data") as store:
        a_id = register_file(store, a, "a", meta=make_meta(seed="1"))
        b_id = register_file(store, b, "b", meta=make_meta(seed="2"))
        store.set_hashes(a_id, "0f0f0f0f0f0f0f0f", "f" * 16)
        store.set_hashes(b_id, "0000000000000000", "0" * 16)

        document = compare.compare_assets(store, [a_id, b_id])
        assert len(document["pairs"]) == 1
        pair = document["pairs"][0]
        assert pair["a_id"] == a_id and pair["b_id"] == b_id
        assert pair["same_seed"] is False
        assert pair["phash_distance"] == 32
        assert pair["heatmap"]["enabled"] is False
        assert "同じ seed" in pair["heatmap"]["reason"]
        # items はハッシュをそのまま写す（設計 §6.1 の `phash`）
        assert document["items"][0]["phash"] == "0f0f0f0f0f0f0f0f"
        assert document["items"][1]["dhash"] == "0" * 16


# ---- 5. 似ている順（`comparison.md` §4.1）----


def test_nearest_order_is_ascending_and_keeps_unknown_hashes_last():
    """距離の昇順。**pHash が未計算の枚は末尾**（「分からない」を「遠い」と言わない）。"""
    items = [
        {"asset_id": "a", "phash": "0000000000000000"},
        {"asset_id": "b", "phash": "0000000000000007"},      # 距離 3
        {"asset_id": "c", "phash": "ffffffffffffffff"},      # 距離 64
        {"asset_id": "d", "phash": None},                    # 分からない
        {"asset_id": "e", "phash": "0000000000000003"},      # 距離 2
    ]
    got = compare.nearest_order(items, base="a")
    assert got["base"] == "a"
    assert got["order"] == ["a", "e", "b", "c", "d"]
    assert got["distances"]["a"] == 0 and got["distances"]["d"] is None
    values = [got["distances"][i] for i in got["order"] if got["distances"][i] is not None]
    assert values == sorted(values), "昇順でない"
    # 同距離は入力順を保つ（決定的）
    tie = compare.nearest_order([{"asset_id": "a", "phash": "0" * 16},
                                 {"asset_id": "x", "phash": "00" + "0" * 14},
                                 {"asset_id": "y", "phash": "0" * 15 + "0"}], base="a")
    assert tie["order"] == ["a", "x", "y"]


def test_similarity_order_works_for_a_group_and_for_an_ad_hoc_list(app_client):
    """似ている順は**まとまりでも、その場の id の並びでも**同じように出る（設計 §6.2）。"""
    client, app = app_client
    data = Path(app.state.store.data_dir) / "images"
    store = app.state.store
    a_id = register_file(store, save(pattern(1), data / "a.png"), "a", meta=make_meta(seed="1"))
    b_id = register_file(store, save(pattern(2), data / "b.png"), "b", meta=make_meta(seed="2"))
    c_id = register_file(store, save(pattern(3), data / "c.png"), "c", meta=make_meta(seed="3"))
    store.set_hashes(a_id, "0000000000000000", "f" * 16)
    store.set_hashes(b_id, "000000000000000f", "f" * 16)     # a から距離 4
    store.set_hashes(c_id, "00000000000000ff", "f" * 16)     # a から距離 8

    ad_hoc = client.get("/api/compare", params={"ids": f"{a_id},{c_id},{b_id}"}).json()
    assert ad_hoc["base"] == a_id
    assert ad_hoc["nearest"]["order"] == [a_id, b_id, c_id], ad_hoc["nearest"]
    assert ad_hoc["nearest"]["distances"] == {a_id: 0, b_id: 4, c_id: 8}

    group_id = client.post("/api/groups", json={"asset_ids": [a_id, c_id, b_id]}).json()["id"]
    grouped = client.get(f"/api/groups/{group_id}/compare").json()
    assert grouped["nearest"]["order"] == [a_id, b_id, c_id], grouped["nearest"]
    # 基準を変えると、その枚からの順になる（似ている順も基準に従う）
    other = client.get(f"/api/groups/{group_id}/compare", params={"base": c_id}).json()
    assert other["nearest"]["base"] == c_id
    assert other["nearest"]["order"][0] == c_id
    assert [other["nearest"]["distances"][i] for i in other["nearest"]["order"]] == \
        sorted(other["nearest"]["distances"][i] for i in other["nearest"]["order"])


def test_the_api_returns_metrics_and_a_heatmap_for_a_pair(app_client):
    """`POST /api/compare/pair`（設計 §6.2）と、まとまりつきの口。"""
    client, app = app_client
    data = Path(app.state.store.data_dir) / "images"
    a = save(pattern(1), data / "a.png")
    b = save(pattern(1), data / "b.png")
    store = app.state.store
    a_id = register_file(store, a, "a", meta=make_meta(seed="5"))
    b_id = register_file(store, b, "b", meta=make_meta(seed="5"))

    # ハッシュはサムネイルの口で入る（**実測 F5**: 復号 1 回でサムネイルとハッシュの両方）
    for asset_id in (a_id, b_id):
        assert client.get(f"/api/assets/{asset_id}/thumb", params={"size": 256}).status_code == 200
        assert store.asset(asset_id)["phash"], "サムネイルの口でハッシュが入っていない"

    got = client.post("/api/compare/pair", json={"a_id": a_id, "b_id": b_id})
    assert got.status_code == 200, got.text
    body = got.json()
    assert body["a_id"] == a_id and body["b_id"] == b_id
    assert body["phash_distance"] == 0, "同じ内容の 2 枚の距離が 0 でない"
    assert body["ssim"] == pytest.approx(1.0, abs=1e-6)
    assert body["mean_abs"] == 0.0
    assert body["algo_version"] == compare.ALGO_VERSION
    assert body["heatmap"]["enabled"] is True
    assert body["heatmap"]["image"].startswith("data:image/webp;base64,")

    group_id = client.post("/api/groups", json={"asset_ids": [a_id, b_id]}).json()["id"]
    grouped = client.post(f"/api/groups/{group_id}/compare/pair",
                          json={"a_id": a_id, "b_id": b_id})
    assert grouped.status_code == 200, grouped.text
    assert grouped.json()["ssim"] == pytest.approx(1.0, abs=1e-6)

    # 入力の検査
    assert client.post("/api/compare/pair", json={"a_id": a_id}).status_code == 422
    assert client.post("/api/compare/pair", json={"a_id": a_id,
                                                  "b_id": "nope"}).status_code == 404
    outside = client.post(f"/api/groups/{group_id}/compare/pair",
                          json={"a_id": a_id, "b_id": "nope"})
    assert outside.status_code == 422 and outside.json()["details"]["extra"] == ["nope"]

    # まとまりの比較の文書にも似ている順と組の規則が入る
    document = client.get(f"/api/groups/{group_id}/compare").json()
    assert document["nearest"]["order"][0] == a_id
    assert len(document["pairs"]) == 1


def test_the_new_compare_endpoints_are_guarded(app_client):
    """守りは `app.py` の middleware がアプリ全体に掛けるので、POST の口にも効く（点検 C15）。"""
    client, app = app_client
    data = Path(app.state.store.data_dir) / "images"
    a_id = register_file(app.state.store, save(pattern(1), data / "a.png"), "a",
                         meta=make_meta())
    b_id = register_file(app.state.store, save(pattern(2), data / "b.png"), "b",
                         meta=make_meta(seed="9"))
    for path in ("/api/compare/pair", "/api/groups/nope/compare/pair"):
        assert client.post(path, json={"a_id": a_id, "b_id": b_id},
                           headers={"host": "evil.example"}).status_code == 403, path
        assert client.post(path, json={"a_id": a_id, "b_id": b_id},
                           headers={"origin": "http://evil.example"}).status_code == 403, path
        assert client.post(path, content=b"{}",
                           headers={"content-type": "text/plain"}).status_code == 403, path


# ---- 6. マイグレーション v3（列と表）----


def test_migration_v3_upgrades_a_v2_database_in_place(tmp_path):
    """v2 の DB をその場で v3 にする（列を 2 つ足し、`comparison_cache` を作る。行は消さない）。"""
    con = db.connect(tmp_path)
    try:
        con.executescript(db.DDL)
        con.execute("PRAGMA user_version = 2")
        con.execute(
            "INSERT INTO asset(id, sha256, kind, kind_source, first_seen_at, last_seen_at)"
            " VALUES ('a1', ?, 'generated', 'auto:prompt', ?, ?)",
            ("a" * 64, db.now(), db.now()))
        before = {r["name"] for r in con.execute("PRAGMA table_info(asset)")}
        assert "phash" not in before and "dhash" not in before
        assert con.execute("SELECT count(*) AS n FROM sqlite_master WHERE name ="
                           " 'comparison_cache'").fetchone()["n"] == 0

        assert db.migrate(con) == db.SCHEMA_VERSION
        after = {r["name"] for r in con.execute("PRAGMA table_info(asset)")}
        assert {"phash", "dhash"} <= after
        assert con.execute("SELECT count(*) AS n FROM asset").fetchone()["n"] == 1, "行が消えた"
        assert con.execute("SELECT phash FROM asset WHERE id = 'a1'").fetchone()["phash"] is None
        columns = {r["name"] for r in con.execute("PRAGMA table_info(comparison_cache)")}
        assert columns == {"a_id", "b_id", "algo_version", "ssim", "changed_fraction",
                           "mean_abs", "computed_at"}
        # 何度呼んでも安全
        assert db.migrate(con) == db.SCHEMA_VERSION
        assert db.integrity(con)["foreign_key_violations"] == 0
    finally:
        con.close()


# ---- 7. 初回の比較文書にハッシュを埋める（監査 B1）----


def test_the_first_compare_document_fills_the_missing_hashes_and_the_second_does_not(
        tmp_path, monkeypatch):
    """**監査 B1**: 初回の `/api/compare` は足りない pHash / dHash を**錠の外で**埋めてから
    文書を組む。

    サムネイルを 1 枚も要求していない枚（実データの 263 枚がこれ。ハッシュはサムネイルを
    作る復号に同居して入る＝**実測 F5**）は、これが無いと文書の `phash` が `null` のままに
    なり、似ている順の距離も出ず、規則も「pHash もまだ計算されていません」と言ってしまう。
    確かめるのは (a) ハッシュと距離が入る / (b) 2 回目は復号しない（1 枚につき生涯 1 回）/
    (c) 取引（錠）を開いたまま返さない、の 3 つ。
    """
    a = save(pattern(1), tmp_path / "a.png")
    b = save(pattern(2), tmp_path / "b.png")
    with Store(tmp_path / "data") as store:
        a_id = register_file(store, a, "a", meta=make_meta(seed="1"))
        b_id = register_file(store, b, "b", meta=make_meta(seed="2"))
        assert store.asset(a_id)["phash"] is None and store.asset(b_id)["phash"] is None

        opened = []
        real_open = Image.open
        monkeypatch.setattr(Image, "open",
                            lambda *args, **kw: (opened.append(args[0] if args else None),
                                                 real_open(*args, **kw))[1])

        first = compare.compare_assets(store, [a_id, b_id])
        assert len(opened) == 2, f"初回の復号が {len(opened)} 回（足りない 2 枚だけのはず）"
        for item in first["items"]:
            assert item["phash"] and item["dhash"], "初回の文書にハッシュが乗っていない（監査 B1）"
            assert compare.HASH_RE.match(item["phash"])
        assert first["nearest"]["distances"][b_id] is not None, "似ている順の距離が出ていない"
        assert first["pairs"][0]["phash_distance"] is not None
        assert store.con.in_transaction is False, "取引を開いたまま返した（監査 B3）"

        opened.clear()
        second = compare.compare_assets(store, [a_id, b_id])
        assert opened == [], f"2 回目に復号した（1 枚につき 1 回で終わっていない）: {opened}"
        assert second["nearest"]["distances"] == first["nearest"]["distances"]
        assert store.con.in_transaction is False


# ---- 8. 実データでの点検（読み取りだけ）----


def real_rows(path: Path) -> list[dict]:
    """実データを **`mode=ro`** で読み、(asset_id, path) を返す。DB は消してはいけない。"""
    con = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    try:
        rows = con.execute(
            "SELECT a.id, a.width, a.height, a.review_state, m.meta_json,"
            "       l.display_path, l.missing_at"
            " FROM asset a"
            " LEFT JOIN asset_meta m ON m.asset_id = a.id"
            " LEFT JOIN asset_location l ON l.asset_id = a.id"
            " ORDER BY a.id, l.is_primary DESC").fetchall()
    finally:
        con.close()
    out, seen = [], set()
    for r in rows:
        if r["id"] in seen or r["missing_at"] is not None:
            continue
        seen.add(r["id"])
        try:
            meta = json.loads(r["meta_json"]) if r["meta_json"] else None
        except ValueError:
            meta = None
        out.append({"id": r["id"], "path": r["display_path"], "width": r["width"],
                    "height": r["height"], "review_state": r["review_state"],
                    "meta": meta if isinstance(meta, dict) else None})
    return out


def test_real_assets_hold_the_hashing_properties_and_record_the_cost():
    """**実データの煙試験**（読み取り専用・`mode=ro`）。

    263 枚の実データから実体のある枚を数枚取り、**性質**を確かめる:
    同じ絵は距離 0 / 決定的 / 16 進 16 文字 / 距離は対称。

    あわせて **実測 F5**（11.88 ms/枚。復号＋縮小 11.35 / DCT 0.53）を測り直して印字する
    （値そのものは主張しない。主張すると機械が変わっただけで落ちる）。
    """
    if not REAL_DB.exists():
        pytest.skip(f"実データが無い: {REAL_DB}")
    rows = real_rows(REAL_DB)
    assert len(rows) >= 263, f"実データの枚数が変わった: {len(rows)}"

    def on_disk(row: dict) -> bool:
        return bool(row["path"]) and Path(row["path"]).exists()

    on_disk_rows = [r for r in rows if on_disk(r)]
    assert len(on_disk_rows) >= 10, f"実体のある枚が足りない: {len(on_disk_rows)}"

    sample = on_disk_rows[:6]
    hashes = {}
    for row in sample:
        path = Path(row["path"])
        assert path.exists(), f"実体が無い: {path}"
        hashes[row["id"]] = compare.hash_file(path)
    for asset_id, (phash, dhash) in hashes.items():
        assert compare.HASH_RE.match(phash) and compare.HASH_RE.match(dhash)
        assert compare.hash_distance(phash, phash) == 0
        # 2 回計算しても同じ（決定的）
        again = compare.hash_file(Path(next(r for r in sample if r["id"] == asset_id)["path"]))
        assert again == (phash, dhash), "実データで 2 回の値が違う"

    # 距離は対称で、0〜64 の範囲。別の絵どうしは 0 ではない
    ids = list(hashes)
    nonzero = 0
    for i, left in enumerate(ids):
        for right in ids[i + 1:]:
            d1 = compare.hash_distance(hashes[left][0], hashes[right][0])
            d2 = compare.hash_distance(hashes[right][0], hashes[left][0])
            assert d1 == d2 and 0 <= d1 <= 64
            nonzero += d1 > 0
    assert nonzero > 0, "実データの別の絵どうしが全部距離 0（ハッシュが定数になっている）"

    # 費用の実測（復号＋ハッシュ / ハッシュだけ）
    path = Path(sample[0]["path"])
    rounds = 5
    started = time.perf_counter()
    for _ in range(rounds):
        compare.hash_file(path)
    full = (time.perf_counter() - started) / rounds * 1000
    with Image.open(path) as im:
        rgb = im.convert("RGB")
    started = time.perf_counter()
    for _ in range(rounds):
        compare.hashes_of_image(rgb)
    pure = (time.perf_counter() - started) / rounds * 1000
    print(f"\n[実測] {path.name} {rgb.size}: 復号込み {full:.2f} ms/枚 / "
          f"ハッシュだけ {pure:.2f} ms/枚（設計 §0.7 の実測は 11.88 / 0.53）")


def test_real_far_pairs_are_not_called_aligned_and_record_the_margin():
    """**監査 A2 の実データ確認**（読み取り専用・`mode=ro`）。

    263 枚から「このツール自身が遠いと言う組」（pHash 距離 > `PHASH_NEAR_THRESHOLD`）を
    20 組取り、`build_heatmap()` が**1 つも「合わせた」と言わない**ことを確かめる。
    あわせて実測した一致度の最大値を印字する（しきい値 `ALIGN_MIN_CORR` の根拠。
    値そのものは主張しない＝機械や画像が変われば動く）。
    """
    if not REAL_DB.exists():
        pytest.skip(f"実データが無い: {REAL_DB}")
    rows = [r for r in real_rows(REAL_DB) if r["path"] and Path(r["path"]).exists()][:40]
    assert len(rows) >= 20, f"実体のある枚が足りない: {len(rows)}"

    hashes = {row["id"]: compare.hash_file(row["path"]) for row in rows}
    pairs = []
    for left, right in zip(rows, rows[1:]):
        distance = compare.hash_distance(hashes[left["id"]][0], hashes[right["id"]][0])
        if distance is not None and distance > compare.PHASH_NEAR_THRESHOLD:
            pairs.append((left, right, distance))
    pairs = pairs[:20]
    assert len(pairs) >= 10, f"「遠い」組が実データで足りない（前提が変わった）: {len(pairs)}"

    got = [compare.build_heatmap(left["path"], right["path"]) for left, right, _ in pairs]
    aligned = [(left["id"], right["id"], one["dx"], one["dy"], one["corr"])
               for (left, right, _), one in zip(pairs, got) if one["available"]]
    assert aligned == [], f"無関係な組を「合わせた」と言った（監査 A2）: {aligned}"

    measured = [one["corr"] for one in got if one["corr"] is not None]
    assert measured, "一致度が 1 つも出ていない"
    assert max(measured) < compare.ALIGN_MIN_CORR, \
        f"無関係な組の一致度 {max(measured):.3f} がしきい値 {compare.ALIGN_MIN_CORR} 以上"
    print(f"\n[実測] 無関係 {len(pairs)} 組: 一致度 最小 {min(measured):.3f} / "
          f"最大 {max(measured):.3f}（しきい値 {compare.ALIGN_MIN_CORR}）/ "
          f"峰の比 最大 {max(one['peak_ratio'] for one in got):.2f} / "
          "「合わせた」と言った組 0")


def test_real_assets_fill_the_hashes_on_the_first_compare_and_not_on_the_second(
        tmp_path, monkeypatch):
    """**監査 B1 の実データ確認**: 実データの 263 枚はハッシュが 1 枚も入っていない。

    実データは**読み取り専用**（`mode=ro`）で読み、その実体のパスだけを一時の `Store` に
    登録して `/api/compare` と同じ道（`compare_assets()`）を 1 回目・2 回目と通す。
    **1 回目に埋まり、2 回目は復号しない**こと、取引を開いたまま終わらないことを見る。
    """
    if not REAL_DB.exists():
        pytest.skip(f"実データが無い: {REAL_DB}")
    rows = [r for r in real_rows(REAL_DB) if r["path"] and Path(r["path"]).exists()][:4]
    assert len(rows) >= 2, f"実体のある枚が足りない: {len(rows)}"

    with Store(tmp_path / "data") as store:
        ids = [register_file(store, Path(row["path"]), f"real{at}", meta=row["meta"],
                             width=row["width"] or 0, height=row["height"] or 0)
               for at, row in enumerate(rows)]
        assert all(store.asset(asset_id)["phash"] is None for asset_id in ids), \
            "一時の Store に既にハッシュがある（前提が変わった）"

        opened = []
        real_open = Image.open
        monkeypatch.setattr(Image, "open",
                            lambda *args, **kw: (opened.append(args[0] if args else None),
                                                 real_open(*args, **kw))[1])
        first = compare.compare_assets(store, ids)
        assert len(opened) == len(ids), f"初回の復号が {len(opened)} 回（{len(ids)} 枚のはず）"
        assert all(item["phash"] and item["dhash"] for item in first["items"]), \
            "初回の文書にハッシュが乗っていない（監査 B1）"
        distances = first["nearest"]["distances"]
        assert all(distances[asset_id] is not None for asset_id in ids), distances
        assert store.con.in_transaction is False, "取引を開いたまま返した"

        opened.clear()
        second = compare.compare_assets(store, ids)
        assert opened == [], f"2 回目に復号した: {opened}"
        assert second["nearest"]["distances"] == distances
        print(f"\n[実測] 実データ {len(ids)} 枚: 1 回目に復号 {len(ids)} 回 / 2 回目 0 回 / "
              f"距離 {sorted(distances.values())}")

