"""PNG のテキストチャンクを読み、ComfyUI の生成条件（来歴）を取り出す。

設計: docs/design.md §7、docs/workflow-reproduction.md §4.1

守ること（点検で見つかった誤りを反映）:
- ファイル全体を読まない（**読んだバイト数**で上限を掛ける。オフセットでは測らない）
- チャンクは `長さ(4) + 種別(4) + データ(n) + CRC(4)` = 12 + n バイト進む（CRC を忘れると全部ずれる）
- **結線（["9", 0]）はグラフを辿って解決する**。値が結線のとき `str(["20", 0])` を値にしてはいけない
- `tEXt` はそのまま、`zTXt` は zlib、`iTXt` は UTF-8 で復号する
- 読めなかった理由は `note` に残す（「png ではない」と権限エラーを混同しない）
"""

from __future__ import annotations

import json
import struct
import zlib
from pathlib import Path

PNG_SIG = b"\x89PNG\r\n\x1a\n"
TEXT_CHUNKS = (b"tEXt", b"zTXt", b"iTXt")
DEFAULT_CAP = 256 * 1024
PRIMITIVES = {"PrimitiveInt", "PrimitiveFloat", "PrimitiveString", "PrimitiveStringMultiline",
              "PrimitiveBoolean", "INTConstant", "FloatConstant", "StringConstant"}
SAVE_TYPES = {"SaveImage", "PreviewImage", "SaveAnimatedWEBP", "SaveAnimatedPNG"}


def parse_chunks(buf: bytes, cap: int = DEFAULT_CAP) -> dict:
    """メモリ上の先頭バイト列からチャンクを読む（走査では 1 回の読みで済ませるため）。"""
    out: dict = {"ok": False, "error": None, "text": {}, "width": None, "height": None,
                 "bit_depth": None, "color_type": None, "bytes_read": 0, "truncated": False}
    if not buf.startswith(PNG_SIG):
        out["error"] = "PNG ではない（シグネチャが違う）"
        return out
    out["ok"] = True
    pos = 8
    out["bytes_read"] = 8
    while pos + 8 <= len(buf) and pos < cap:
        (n,) = struct.unpack(">I", buf[pos:pos + 4])
        typ = buf[pos + 4:pos + 8]
        if n > (1 << 31):
            out["error"] = f"チャンクの長さが異常（{typ.decode('latin-1', 'replace')}: {n}）"
            break
        body = buf[pos + 8:pos + 8 + n]
        if len(body) < n:
            out["truncated"] = True
            break
        if typ == b"IHDR":
            w, h, depth, ctype = struct.unpack(">IIBB", body[:10])
            out["width"], out["height"] = w, h
            out["bit_depth"], out["color_type"] = depth, ctype
        elif typ in TEXT_CHUNKS:
            key, value = _decode_text(typ, body)
            if key:
                out["text"][key] = value
        elif typ == b"IEND":
            break
        pos += 12 + n
        out["bytes_read"] = pos
    if pos >= cap:
        out["truncated"] = True
    return out


def read_png(path: str | Path, cap: int = DEFAULT_CAP) -> dict:
    """先頭 `cap` バイトだけ読んでチャンクを取る。戻り値の `error` に理由が入る。"""
    try:
        with open(path, "rb") as fh:
            buf = fh.read(cap)
    except OSError as exc:
        return {"ok": False, "error": f"開けない: {exc}", "text": {}, "width": None, "height": None,
                "chunk_keys": [], "bytes_read": 0, "truncated": False}
    result = parse_chunks(buf, cap)
    result["chunk_keys"] = sorted(result["text"].keys())
    return result


def _decode_text(typ: bytes, data: bytes) -> tuple[str | None, bytes]:
    """tEXt / zTXt / iTXt を復号する。"""
    try:
        if typ == b"tEXt":
            key, _, value = data.partition(b"\x00")
            return key.decode("latin-1"), value
        if typ == b"zTXt":
            key, _, rest = data.partition(b"\x00")
            if len(rest) < 1:
                return key.decode("latin-1"), b""
            method, _, compressed = rest[0:1], None, rest[1:]
            if method != b"\x00":
                return key.decode("latin-1"), b""
            return key.decode("latin-1"), zlib.decompress(compressed)
        if typ == b"iTXt":
            key, _, rest = data.partition(b"\x00")
            if len(rest) < 2:
                return key.decode("latin-1"), b""
            compressed_flag, rest = rest[0:1], rest[1:]
            # 言語タグ / 翻訳済みキーワードは空が多い。2 つの NUL を跨ぐ
            _, _, rest = rest.partition(b"\x00")
            _, _, text = rest.partition(b"\x00")
            if compressed_flag == b"\x01":
                text = zlib.decompress(text)
            return key.decode("latin-1"), text
    except Exception:  # noqa: BLE001  壊れたチャンクで全体を落とさない
        return None, b""
    return None, b""


# ---- グラフの読み方（API 形式 {"1": {"class_type": ..., "inputs": {...}}}） ----


def _link(value):
    """["9", 0] のような結線なら (node_id, slot) を返す。リテラルなら None。"""
    if isinstance(value, list) and len(value) == 2 and isinstance(value[0], str):
        return value[0], value[1]
    return None


def _by_type(graph: dict, class_type: str) -> list[str]:
    return [nid for nid, n in graph.items() if isinstance(n, dict) and n.get("class_type") == class_type]


def _numeric_order(nid: str) -> tuple:
    return (0, int(nid)) if nid.isdigit() else (1, nid)


def resolve_input(graph: dict, node: dict, key: str, depth: int = 0):
    """入力の実値を解決する。結線ならソースを辿る。

    戻り値: (値, 出所)。出所は 'literal' / 'primitive' / 'via:<class>' / 'unresolved:<class>'。
    点検 I2: `KSampler` の seed などが結線のとき、リストを文字列にしてはいけない。
    """
    value = (node or {}).get("inputs", {}).get(key)
    if not isinstance(value, list):
        return value, ("literal" if value is not None else "missing")
    if depth > 4:
        return None, "too_deep"
    link = _link(value)
    if not link:
        return None, "bad_link"
    src = graph.get(link[0])
    if not isinstance(src, dict):
        return None, "unresolved:missing_node"
    ct = src.get("class_type") or "?"
    ins = src.get("inputs", {})
    if ct in PRIMITIVES:
        return ins.get("value"), "primitive"
    for cand in (key, "value", "int", "float", "string", "text"):
        if cand in ins and not isinstance(ins[cand], list):
            return ins[cand], f"via:{ct}"
    return None, f"unresolved:{ct}"


def reachable_from_outputs(graph: dict) -> set[str]:
    """保存・表示のノードから遡って到達できるノード（生成に寄与する部分グラフ）。"""
    roots = [nid for nid in _by_type(graph, "SaveImage") + _by_type(graph, "PreviewImage")]
    if not roots:  # 保存ノードが無ければ全部を対象にする
        return set(graph.keys())
    seen: set[str] = set()
    stack = list(roots)
    while stack:
        nid = stack.pop()
        if nid in seen or nid not in graph:
            continue
        seen.add(nid)
        node = graph[nid]
        if not isinstance(node, dict):
            continue
        for value in node.get("inputs", {}).values():
            link = _link(value)
            if link and link[0] not in seen:
                stack.append(link[0])
    return seen


def _primary_ksampler(graph: dict, reachable: set[str]) -> str | None:
    ids = [nid for nid in _by_type(graph, "KSampler") if nid in reachable] or _by_type(graph, "KSampler")
    if not ids:
        return None
    ids.sort(key=_numeric_order)
    return ids[0]


def _encode_text_side(graph: dict, node: dict, key: str) -> dict:
    """CLIPTextEncode の側（text）を、リテラルか連結かで表す。"""
    value = (node or {}).get("inputs", {}).get(key)
    if isinstance(value, str):
        return {"text": value, "source": "png_literal", "concat_prefix": None, "delimiter": None}
    link = _link(value)
    if not link:
        return {"text": None, "source": None, "concat_prefix": None, "delimiter": None}
    src = graph.get(link[0])
    if isinstance(src, dict) and src.get("class_type") == "StringConcatenate":
        prefix, _ = resolve_input(graph, src, "string_a")
        delim, _ = resolve_input(graph, src, "delimiter")
        return {"text": None, "source": "reconstructed",
                "concat_prefix": prefix if isinstance(prefix, str) else "",
                "delimiter": delim if isinstance(delim, str) else ""}
    resolved, origin = resolve_input(graph, node, key)
    if isinstance(resolved, str) and origin.startswith("via:"):
        return {"text": resolved, "source": "png_literal", "concat_prefix": None, "delimiter": None}
    return {"text": None, "source": None, "concat_prefix": None, "delimiter": None}


def analyze_graph(graph: dict) -> dict:
    """API 形式のグラフから、表示・記録に要る値を取り出す。"""
    graph = {k: v for k, v in (graph or {}).items() if isinstance(v, dict)}
    reachable = reachable_from_outputs(graph)
    info: dict = {
        "model": None, "clip": None, "clip_all": [], "vae": None, "llm": None,
        "loras": [], "sampler": None, "scheduler": None, "steps": None, "cfg": None,
        "denoise": None, "seed": None, "seed_raw": None, "width": None, "height": None,
        "positive_literal": None, "negative_literal": None,
        "final_prompt": None, "final_prompt_source": None,
        "ja_text": None, "ja_source": None, "textgen_params": None,
        "has_textgen": False, "init_image": None, "node_types": {},
        "unresolved": [], "primary_ksampler": None,
    }
    for node in graph.values():
        ct = node.get("class_type")
        if ct:
            info["node_types"][ct] = info["node_types"].get(ct, 0) + 1

    # モデル類（結線でも解決する）
    for nid in _by_type(graph, "UNETLoader"):
        v, _ = resolve_input(graph, graph[nid], "unet_name")
        if isinstance(v, str) and not info["model"]:
            info["model"] = v
    for nid in _by_type(graph, "VAELoader"):
        v, _ = resolve_input(graph, graph[nid], "vae_name")
        if isinstance(v, str) and not info["vae"]:
            info["vae"] = v
    for nid in _by_type(graph, "CLIPLoader"):
        v, _ = resolve_input(graph, graph[nid], "clip_name")
        if isinstance(v, str):
            info["clip_all"].append(v)

    # LoRA は名前と重みの両方を取る（点検 I13）。LoraLoader（clip 付き）も読む。
    for ct in ("LoraLoaderModelOnly", "LoraLoader"):
        for nid in _by_type(graph, ct):
            node = graph[nid]
            name, _ = resolve_input(graph, node, "lora_name")
            strength, _ = resolve_input(graph, node, "strength_model")
            clip_strength, _ = resolve_input(graph, node, "strength_clip")
            if isinstance(name, str):
                info["loras"].append({"name": name, "strength_model": strength,
                                      "strength_clip": clip_strength, "loader": ct})

    # 主のサンプラ（保存ノードから遡った最初の 1 つ。複数あっても上書きしない）
    primary = _primary_ksampler(graph, reachable)
    info["primary_ksampler"] = primary
    if primary:
        node = graph[primary]
        for key, dst in (("sampler_name", "sampler"), ("scheduler", "scheduler"),
                         ("steps", "steps"), ("cfg", "cfg"), ("denoise", "denoise")):
            value, origin = resolve_input(graph, node, key)
            info[dst] = value
            if origin.startswith("unresolved"):
                info["unresolved"].append(f"KSampler.{key}: {origin}")
        seed, origin = resolve_input(graph, node, "seed")
        if seed is not None:
            info["seed_raw"] = seed
            info["seed"] = str(seed)  # 符号なし 64bit を落とさない（design.md §5.1）
        else:
            info["unresolved"].append(f"KSampler.seed: {origin}")
        # 正負は「空文字か」ではなく**結線の先**で決める（点検 I3）
        for key, dst in (("positive", "positive"), ("negative", "negative")):
            link = _link(node.get("inputs", {}).get(key))
            enc = graph.get(link[0]) if link else None
            if not isinstance(enc, dict) or enc.get("class_type") != "CLIPTextEncode":
                info["unresolved"].append(f"KSampler.{key}: CLIPTextEncode に辿れない")
                continue
            side = _encode_text_side(graph, enc, "text")
            info[f"{dst}_side"] = side
            if dst == "positive":
                info["positive_literal"] = side["text"]
                if side["source"]:
                    info["final_prompt"] = side["text"]
                    info["final_prompt_source"] = side["source"]
                info["concat_prefix"] = side["concat_prefix"]
                info["concat_delimiter"] = side["delimiter"]
            else:
                info["negative_literal"] = side["text"]

    for nid in _by_type(graph, "EmptyLatentImage"):
        node = graph[nid]
        for key in ("width", "height"):
            value, _ = resolve_input(graph, node, key)
            if isinstance(value, int) and info[key] is None:
                info[key] = value

    for nid in _by_type(graph, "LoadImage"):
        v, _ = resolve_input(graph, graph[nid], "image")
        if isinstance(v, str):
            info["init_image"] = v
            break

    # 日本語原文と TextGenerate（結線で判定する。番号では判定しない）
    for tg_id in _by_type(graph, "TextGenerate"):
        info["has_textgen"] = True
        tg = graph[tg_id]
        ja, origin = resolve_input(graph, tg, "prompt")
        if isinstance(ja, str):
            info["ja_text"] = ja
            info["ja_source"] = "png_primitive" if origin == "primitive" else f"png_{origin}"
        sysprompt, _ = resolve_input(graph, tg, "system_prompt")
        params = {k: v for k, v in tg.get("inputs", {}).items() if not isinstance(v, list)}
        params.pop("sampling_mode", None)
        info["textgen_params"] = params
        info["textgen_system_prompt"] = sysprompt
        clip_link = _link(tg.get("inputs", {}).get("clip"))
        if clip_link:
            src = graph.get(clip_link[0])
            if isinstance(src, dict) and src.get("class_type") == "CLIPLoader":
                v, _ = resolve_input(graph, src, "clip_name")
                if isinstance(v, str):
                    info["llm"] = v
        consumers = []
        for nid, node in graph.items():
            if nid == tg_id:
                continue
            for key, value in node.get("inputs", {}).items():
                link = _link(value)
                if link and link[0] == tg_id:
                    consumers.append({"node": nid, "class_type": node.get("class_type"), "input": key})
        if consumers:
            info["textgen_consumers"] = consumers

    # 使ったテキストエンコーダは「主のサンプラの正側が参照している CLIPLoader」（点検 I3）
    info["clip"] = info["clip_all"][0] if info["clip_all"] else None
    if primary:
        link = _link(graph[primary].get("inputs", {}).get("positive"))
        enc = graph.get(link[0]) if link else None
        clink = _link((enc or {}).get("inputs", {}).get("clip"))
        src = graph.get(clink[0]) if clink else None
        if isinstance(src, dict) and src.get("class_type") == "CLIPLoader":
            v, _ = resolve_input(graph, src, "clip_name")
            if isinstance(v, str):
                info["clip"] = v
    return info


def provenance(path: str | Path) -> dict:
    """1 枚の PNG から、来歴（メタデータ）を取り出す。"""
    chunks = read_png(path)
    result = {
        "ok": bool(chunks["ok"]),
        "width": chunks["width"], "height": chunks["height"],
        "chunk_keys": sorted(chunks["text"].keys()),
        "graph_format": None, "graph": None, "info": None,
        "note": chunks.get("error"),
    }
    if not chunks["ok"]:
        return result
    raw = chunks["text"].get("prompt")
    if raw is None:
        result["note"] = "prompt チャンクが無い（生成条件が残っていない画像）"
        return result
    try:
        graph = json.loads(raw.decode("utf-8", "replace"))
    except Exception as exc:  # noqa: BLE001
        result["note"] = f"prompt チャンクを JSON として読めない: {exc}"
        return result
    if not isinstance(graph, dict) or not all(isinstance(v, dict) for v in graph.values()):
        result["note"] = "prompt チャンクが API 形式のグラフではない"
        return result
    result["graph_format"] = "api+ui" if "workflow" in chunks["text"] else "api"
    result["graph"] = graph
    result["info"] = analyze_graph(graph)
    return result
