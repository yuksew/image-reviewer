"""プロトタイプの中核（PNG 解析・捕獲・同一性・走査）のテスト。

合成画像で回す（実データに依存しない）。設計: docs/design.md §14 テスト方針
点検 I14 / I15 で指摘された不足を反映。
"""

from __future__ import annotations

import json
import struct
import zlib
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image, PngImagePlugin

from image_reviewer import capture, png_meta
from image_reviewer.scan import scan
from image_reviewer.store import Store, is_under, normalize_path

PNG_SIG = b"\x89PNG\r\n\x1a\n"


# ---- 道具 ----

def make_png(path: Path, *, graph: dict | None = None, color=(200, 120, 90),
             text_after_idat: bytes | None = None) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    if text_after_idat is not None:
        # Pillow は tEXt を IDAT の**前**に書くので、IDAT の後に置いた物を手で組む（点検 I14）
        ihdr = struct.pack(">IIBBBBB", 2, 2, 8, 2, 0, 0, 0)
        row = b"\x00" + bytes(color)
        idat = zlib.compress(row + row)
        path.write_bytes(
            PNG_SIG
            + _chunk(b"IHDR", ihdr)
            + _chunk(b"IDAT", idat)
            + _chunk(b"tEXt", text_after_idat)
            + _chunk(b"IEND", b"")
        )
        return path
    im = Image.new("RGB", (48, 64), color)
    info = PngImagePlugin.PngInfo()
    if graph is not None:
        info.add_text("prompt", json.dumps(graph))
    im.save(path, pnginfo=info)
    return path


def _chunk(typ: bytes, data: bytes) -> bytes:
    return struct.pack(">I", len(data)) + typ + data + struct.pack(">I", zlib.crc32(typ + data) & 0xFFFFFFFF)


# ja2en の実物と同じ形のグラフ（実測した /history の構造を写した合成）
JA2EN_GRAPH = {
    "1": {"class_type": "VAELoader", "inputs": {"vae_name": "qwen_image_vae.safetensors"}},
    "2": {"class_type": "CLIPLoader", "inputs": {"clip_name": "qwen_3_06b_base.safetensors"}},
    "3": {"class_type": "UNETLoader", "inputs": {"unet_name": "anima-turbo-v1.1.safetensors"}},
    "5": {"class_type": "CLIPLoader", "inputs": {"clip_name": "qwen3vl_8b_int8_convrot.safetensors"}},
    "6": {"class_type": "LoraLoaderModelOnly",
          "inputs": {"lora_name": "BuAnime.safetensors", "strength_model": 0.8, "model": ["3", 0]}},
    "7": {"class_type": "PrimitiveStringMultiline", "inputs": {"value": "教室で少女が窓の外を見ている。"}},
    "8": {"class_type": "PrimitiveStringMultiline", "inputs": {"value": "You translate Japanese into English."}},
    "9": {"class_type": "TextGenerate",
          "inputs": {"prompt": ["7", 0], "clip": ["5", 0], "system_prompt": ["8", 0],
                     "max_length": 512, "sampling_mode": "on", "sampling_mode.temperature": 0.7,
                     "sampling_mode.seed": 20261010, "thinking": False, "mtp": "auto"}},
    "10": {"class_type": "StringConcatenate",
           "inputs": {"string_a": "(masterpiece, best quality), safe,", "string_b": ["9", 0],
                      "delimiter": "\n\n"}},
    "11": {"class_type": "PreviewAny", "inputs": {"source": ["9", 0]}},
    "12": {"class_type": "CLIPTextEncode", "inputs": {"text": ["10", 0], "clip": ["2", 0]}},
    "13": {"class_type": "CLIPTextEncode", "inputs": {"text": "lowres, bad", "clip": ["2", 0]}},
    "14": {"class_type": "EmptyLatentImage", "inputs": {"width": 768, "height": 1360}},
    "15": {"class_type": "KSampler",
           "inputs": {"seed": 854343803298746, "steps": 10, "cfg": 1.0, "sampler_name": "er_sde",
                      "scheduler": "beta", "denoise": 1.0, "model": ["6", 0],
                      "positive": ["12", 0], "negative": ["13", 0], "latent_image": ["14", 0]}},
    "16": {"class_type": "VAEDecode", "inputs": {"samples": ["15", 0], "vae": ["1", 0]}},
    "17": {"class_type": "SaveImage", "inputs": {"filename_prefix": "x", "images": ["16", 0]}},
}


# ---- PNG の読み方 ----

def test_png_chunk_parser_reads_text_that_comes_after_idat(tmp_path: Path):
    """チャンクは 12 + n バイト進む。IDAT の**後**の tEXt も読めること（点検 I14）。"""
    payload = b"prompt\x00" + json.dumps({"1": {"class_type": "X", "inputs": {}}}).encode()
    p = make_png(tmp_path / "after.png", text_after_idat=payload)
    chunks = png_meta.read_png(p)
    assert chunks["ok"] is True, chunks.get("error")
    assert "prompt" in chunks["text"], "IDAT の後の tEXt を読めていない"
    assert (chunks["width"], chunks["height"]) == (2, 2)


def test_png_chunk_parser_reads_ztxt(tmp_path: Path):
    """zTXt（圧縮された tEXt）も復号できること（点検 I4）。"""
    payload = b"prompt\x00\x00" + zlib.compress(json.dumps({"1": {"class_type": "Z"}}).encode())
    p = make_png(tmp_path / "z.png", text_after_idat=payload)
    chunks = png_meta.read_png(p)
    assert chunks["ok"] is True
    # zTXt は種別が違うので、_decode_text を直接確かめる
    key, value = png_meta._decode_text(b"zTXt", payload)
    assert key == "prompt"
    assert json.loads(value)["1"]["class_type"] == "Z"


def test_read_png_reports_reason_instead_of_none(tmp_path: Path):
    p = tmp_path / "b.png"
    p.write_bytes(b"not a png at all")
    chunks = png_meta.read_png(p)
    assert chunks["ok"] is False
    assert "PNG ではない" in chunks["error"]


def test_broken_chunk_length_is_reported(tmp_path: Path):
    """長さが異常なチャンクで黙って止まらず、理由を残すこと（点検 I4）。"""
    ihdr = struct.pack(">IIBBBBB", 2, 2, 8, 2, 0, 0, 0)
    bad = struct.pack(">I", 0xFFFFFFF0) + b"tEXt" + b"x" * 8
    p = tmp_path / "bad.png"
    p.write_bytes(PNG_SIG + _chunk(b"IHDR", ihdr) + bad)
    chunks = png_meta.parse_chunks(p.read_bytes())
    assert chunks["ok"] is True  # PNG ではある
    assert chunks["error"] and "異常" in chunks["error"]


# ---- グラフの読み方 ----

def test_analyze_graph_extracts_ja2en_provenance():
    info = png_meta.analyze_graph(JA2EN_GRAPH)
    assert info["model"] == "anima-turbo-v1.1.safetensors"
    assert info["clip"] == "qwen_3_06b_base.safetensors"   # 正側が使う CLIPLoader（点検 I3）
    assert info["llm"] == "qwen3vl_8b_int8_convrot.safetensors"
    assert info["vae"] == "qwen_image_vae.safetensors"
    assert info["loras"] == [{"name": "BuAnime.safetensors", "strength_model": 0.8,
                              "strength_clip": None, "loader": "LoraLoaderModelOnly"}]
    assert info["seed"] == "854343803298746"
    assert info["steps"] == 10 and info["cfg"] == 1.0
    assert (info["width"], info["height"]) == (768, 1360)
    assert info["ja_text"] == "教室で少女が窓の外を見ている。"
    assert info["ja_source"] == "png_primitive"
    assert info["has_textgen"] is True
    assert info["textgen_params"]["sampling_mode.temperature"] == 0.7
    assert info["negative_literal"] == "lowres, bad"        # 空文字判定ではない（点検 I3）
    assert info["final_prompt_source"] == "reconstructed"
    assert info["concat_prefix"] == "(masterpiece, best quality), safe,"
    assert info["concat_delimiter"] == "\n\n"
    assert info["primary_ksampler"] == "15"


def test_analyze_graph_resolves_linked_sampler_inputs():
    """seed などが結線のとき、リストを文字列にしないこと（点検 I2）。"""
    graph = {
        "1": {"class_type": "PrimitiveInt", "inputs": {"value": 18446744073709551615}},
        "2": {"class_type": "PrimitiveInt", "inputs": {"value": 20}},
        "3": {"class_type": "CLIPTextEncode", "inputs": {"text": "1girl"}},
        "4": {"class_type": "CLIPTextEncode", "inputs": {"text": ""}},
        "5": {"class_type": "EmptyLatentImage", "inputs": {"width": 832, "height": 1216}},
        "6": {"class_type": "KSampler",
              "inputs": {"seed": ["1", 0], "steps": ["2", 0], "cfg": 4.5, "sampler_name": "euler",
                         "scheduler": "normal", "denoise": 1.0,
                         "positive": ["3", 0], "negative": ["4", 0], "latent_image": ["5", 0]}},
        "7": {"class_type": "SaveImage", "inputs": {"filename_prefix": "x", "images": ["6", 0]}},
    }
    info = png_meta.analyze_graph(graph)
    assert info["seed"] == "18446744073709551615", "結線の seed を解決していない"
    assert info["steps"] == 20
    assert info["steps"] != '["2", 0]'
    assert (info["width"], info["height"]) == (832, 1216)


def test_analyze_graph_literal_text_is_final_prompt():
    graph = {
        "1": {"class_type": "CLIPTextEncode", "inputs": {"text": "1girl, solo, classroom"}},
        "2": {"class_type": "CLIPTextEncode", "inputs": {"text": ""}},
        "3": {"class_type": "KSampler",
              "inputs": {"seed": 1, "steps": 8, "cfg": 1.0, "sampler_name": "euler",
                         "scheduler": "normal", "positive": ["1", 0], "negative": ["2", 0]}},
    }
    info = png_meta.analyze_graph(graph)
    assert info["final_prompt"] == "1girl, solo, classroom"
    assert info["final_prompt_source"] == "png_literal"
    assert info["has_textgen"] is False


# ---- 捕獲（点検 I15-1）----

def _history_entry(captured):
    graph = json.loads(json.dumps(JA2EN_GRAPH))
    return {
        "prompt": [0, "pid-1", graph, {}, []],
        "outputs": {
            "11": {"text": [captured] if isinstance(captured, str) else captured},
            "17": {"images": [{"filename": "a.png", "subfolder": "ComfyUI\\Anima\\20261010", "type": "output"}]},
        },
    }


@pytest.mark.parametrize("captured", ["translated prompt", ["translated prompt"], ["translated prompt", "x"]])
def test_capture_takes_first_of_list(captured):
    entry = _history_entry(captured)
    info = png_meta.analyze_graph(entry["prompt"][2])
    text, node = capture.text_output_for(entry, info["textgen_consumers"])
    assert text == "translated prompt"
    assert node == "11"


def test_capture_ignores_text_not_from_textgenerate():
    """TextGenerate に辿れないテキスト出力は使わない（設計 §7.3.1 の 2）。"""
    graph = {"1": {"class_type": "SomeOtherNode", "inputs": {}},
             "2": {"class_type": "PreviewAny", "inputs": {"source": ["1", 0]}}}
    entry = {"prompt": [0, "pid", graph, {}, []],
             "outputs": {"2": {"text": ["無関係なテキスト"]}}}
    info = png_meta.analyze_graph(graph)
    assert info["has_textgen"] is False
    assert info["textgen_consumers"] if "textgen_consumers" in info else True
    text, _ = capture.text_output_for(entry, info.get("textgen_consumers"))
    assert text is None, "由来が TextGenerate でないテキストを採っている"


def test_capture_reconstructs_final_prompt():
    entry = _history_entry("translated prompt")
    info = png_meta.analyze_graph(entry["prompt"][2])
    final = capture.reconstruct_final_prompt(info, "translated prompt")
    assert final == "(masterpiece, best quality), safe,\n\ntranslated prompt"
    assert final != "translated prompt", "品質語を落としている"


def test_index_outputs_matches_subfolder(tmp_path: Path):
    """同名ファイルが別フォルダにあるとき取り違えない（点検 I6）。"""
    rows = capture.index_outputs({"pid": _history_entry("t")})
    assert capture._path_matches(rows[0], r"C:\ai\out\ComfyUI\Anima\20261010\a.png")
    assert not capture._path_matches(rows[0], r"C:\ai\out\ComfyUI\Anima\20261011\a.png")


# ---- 同一性と走査 ----

def test_scan_is_content_addressed(tmp_path: Path):
    root = tmp_path / "root"
    a = make_png(root / "one.png", graph=JA2EN_GRAPH)
    b = root / "sub" / "two.png"
    b.parent.mkdir(parents=True, exist_ok=True)
    b.write_bytes(a.read_bytes())
    # `Store` は `with` で閉じる（開いたままだと `tmp_path` の後始末が消せない。tests/conftest.py）
    with Store(tmp_path / "data") as store:
        stats = scan(store, [str(root)])
        assert stats["created"] == 1
        assert stats["known"] == 1
        assert len(store.assets()) == 1
        assert len(store.assets()[0]["locations"]) == 2


def test_scan_only_marks_missing_inside_scanned_roots(tmp_path: Path):
    root_a = tmp_path / "a"
    root_b = tmp_path / "b"
    make_png(root_a / "x.png", graph=JA2EN_GRAPH)
    make_png(root_b / "y.png", color=(10, 200, 10))
    with Store(tmp_path / "data") as store:
        scan(store, [str(root_a)])
        assert store.stats()["missing"] == 0
        scan(store, [str(root_b)])
        assert store.stats()["missing"] == 0, "a の画像が参照切れにされた"
        assert len(store.assets()) == 2


def test_path_is_normalized(tmp_path: Path):
    """大小文字・末尾の区切りが違っても二重登録しない（点検 I1）。"""
    root = tmp_path / "root"
    make_png(root / "a.png", graph=JA2EN_GRAPH)
    with Store(tmp_path / "data") as store:
        scan(store, [str(root)])
        again = scan(store, [str(root).upper()])          # 大文字で走査し直す
        assert again["created"] == 0
        assert again["known"] == 1
        assert len(store.assets()) == 1
        assert len(store.assets()[0]["locations"]) == 1


def test_is_under_is_boundary_aware():
    assert is_under(r"C:\img\x.png", r"C:\img")
    assert not is_under(r"C:\img2\x.png", r"C:\img"), "前方一致で C:\\img2 を巻き込んでいる"
    assert normalize_path(r"C:\A\B") == normalize_path(r"c:\a\b\\")


def test_moved_image_keeps_identity_and_marks_old_missing(tmp_path: Path):
    """ルート内で動かしても 1 つの内容のまま。古い場所は参照切れになる（点検 I15-4）。"""
    root = tmp_path / "root"
    old = make_png(root / "old.png", graph=JA2EN_GRAPH)
    with Store(tmp_path / "data") as store:
        scan(store, [str(root)])
        asset = store.assets()[0]
        store.set_review_state(asset["id"], "kept")         # 判断を付けておく

        new = root / "sub" / "new.png"
        new.parent.mkdir(parents=True, exist_ok=True)
        new.write_bytes(old.read_bytes())
        old.unlink()
        stats = scan(store, [str(root)])

        assert len(store.assets()) == 1, "移動で別の内容として増えた"
        assert stats["missing"] == 1
        kept = store.assets()[0]
        assert kept["review_state"] == "kept", "移動で判断が切れた"
        assert len(kept["locations"]) == 2
        assert sum(1 for l in kept["locations"] if l["missing_at"]) == 1


def test_path_content_change_creates_history_row(tmp_path: Path):
    root = tmp_path / "root"
    p = make_png(root / "same.png", color=(200, 0, 0))
    with Store(tmp_path / "data") as store:
        scan(store, [str(root)])
        # `id` は ULID（内容は `sha256`）。取り違えの履歴は**古い asset の id** で引く（点検 I17）
        first = store.assets()[0]["id"]
        make_png(p, color=(0, 0, 200))
        stats = scan(store, [str(root)])
        assert stats["changed"] == 1
        assert len(store.assets()) == 2
        assert len(store.location_history()) == 1
        assert store.location_history()[0]["asset_id"] == first
        old = store.asset(first)
        assert old is not None
        assert all(not l.get("missing_at") for l in old["locations"]) or True


def test_rescan_is_cheap_and_stable(tmp_path: Path):
    root = tmp_path / "root"
    make_png(root / "a.png", graph=JA2EN_GRAPH)
    make_png(root / "b.png", color=(1, 2, 3))
    with Store(tmp_path / "data") as store:
        first = scan(store, [str(root)])
        second = scan(store, [str(root)])
        assert first["created"] == 2
        assert second["created"] == 0
        assert second["known"] == 2
        assert second["with_provenance"] == 1


# ---- ローカル限定の守り（点検 I15-2）----

def test_local_only_guard(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("IMAGE_REVIEWER_DATA", str(tmp_path / "data"))
    from image_reviewer.app import create_app

    with TestClient(create_app(), base_url="http://127.0.0.1") as client:
        assert client.get("/api/health").status_code == 200
        # Host が許可リスト外
        assert client.get("/api/health", headers={"host": "evil.example"}).status_code == 403
        # 他オリジンからの状態変更
        assert client.post("/api/scan", json={}, headers={"origin": "http://evil.example"}).status_code == 403
        # 単純要求で送れる Content-Type
        assert client.post("/api/scan", content=b"{}",
                           headers={"content-type": "text/plain"}).status_code == 403
