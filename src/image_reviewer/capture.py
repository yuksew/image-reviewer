"""生成の瞬間にしか無い値を、ComfyUI の `/history` から捕獲する。

設計: docs/design.md §7.3.1、docs/workflow-reproduction.md §5

守ること（実機で確かめた形）:
1. `outputs[node].text` は**リスト**。先頭を取る
2. その出力が `TextGenerate` に由来することを**グラフの結線で**確かめる（ノード番号ではない）
3. 捕獲値は**最終プロンプトではない**。`string_a + delimiter + 捕獲値` を**再構成**する
4. 捕獲した値は `<data>/sidecar/<sha256>.json` にも書く
   （**PNG から取り直せない唯一のもの**。DB を失っても残るようにする。点検 I5）
5. 同じ名前の別フォルダの画像を取り違えない（`subfolder` を突き合わせる。点検 I6）

読み取りのみ。ComfyUI には何も投げない。
"""

from __future__ import annotations

import json
import os
import time
import urllib.request
from pathlib import Path

from .png_meta import analyze_graph, resolve_input
from .store import normalize_path

DEFAULT_BASE = "http://127.0.0.1:8188"
TEXT_NODE_TYPES = {"PreviewAny", "PreviewText", "ShowText|pysssss", "PreviewText|pysssss"}


def fetch_history(base_url: str = DEFAULT_BASE, timeout: int = 25) -> dict:
    with urllib.request.urlopen(base_url.rstrip("/") + "/history", timeout=timeout) as r:
        return json.load(r)


def index_outputs(history: dict) -> list[dict]:
    """出力 1 つ = 1 件の索引。(subfolder, filename) と filename で引けるようにする。"""
    rows = []
    for prompt_id, entry in history.items():
        for nid, out in (entry.get("outputs") or {}).items():
            for im in out.get("images") or []:
                name = im.get("filename")
                if not name:
                    continue
                rows.append({
                    "prompt_id": prompt_id,
                    "entry": entry,
                    "node": nid,
                    "filename": name,
                    "subfolder": (im.get("subfolder") or "").replace("/", "\\"),
                })
    return rows


def _path_matches(row: dict, asset_path: str) -> bool:
    """出力の subfolder とファイル名が、その画像のパスと合うか。"""
    if os.path.basename(asset_path).lower() != row["filename"].lower():
        return False
    if not row["subfolder"]:
        return True
    parent = normalize_path(os.path.dirname(asset_path))
    tail = normalize_path(row["subfolder"]).strip("\\/")
    return parent.endswith(tail) or tail.endswith(os.path.basename(parent))


def text_output_for(entry: dict, consumers: list[dict] | None) -> tuple[str | None, str | None]:
    """訳の出口のうち、テキストを持つノードから値を取る（リストの先頭）。"""
    outputs = entry.get("outputs") or {}
    for cons in consumers or []:
        if cons.get("class_type") not in TEXT_NODE_TYPES:
            continue
        raw = (outputs.get(cons["node"]) or {}).get("text")
        text = raw[0] if isinstance(raw, list) and raw else raw
        if isinstance(text, str) and text.strip():
            return text, cons["node"]
    return None, None


def reconstruct_final_prompt(info: dict, captured: str) -> str:
    prefix = info.get("concat_prefix") or ""
    delim = info.get("concat_delimiter") or ""
    return f"{prefix}{delim}{captured}" if prefix else captured


def write_sidecar(data_dir: str | Path, meta: dict, extra: dict) -> Path:
    """捕獲した来歴を人間が読める JSON として残す（原子的に置き換える）。"""
    out_dir = Path(data_dir) / "sidecar"
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"{extra['sha256']}.json"
    payload = {
        "schema": "urn:image-reviewer:sidecar",
        "abi": "0.1",
        "captured_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        **extra,
        "meta": meta,
    }
    tmp = out.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, out)
    return out


def capture_history(store, base_url: str = DEFAULT_BASE) -> dict:
    """走査済みの画像のうち、訳が未取得のものを `/history` から埋める。"""
    stats = {"checked": 0, "captured": 0, "no_history": 0, "no_text_output": 0,
             "not_textgen": 0, "ambiguous": 0, "history_entries": 0, "sidecars": 0, "error": None}
    try:
        history = fetch_history(base_url)
    except Exception as exc:  # noqa: BLE001
        stats["error"] = f"ComfyUI につながりません（{base_url}）: {exc}"
        return stats
    stats["history_entries"] = len(history)
    rows = index_outputs(history)

    for asset in store.assets():
        meta = asset.get("meta")
        if not meta or meta.get("en_text"):
            continue
        stats["checked"] += 1

        hits = []
        for loc in asset.get("locations", []):
            for row in rows:
                if _path_matches(row, loc.get("path", "")):
                    hits.append(row)
        if not hits:
            stats["no_history"] += 1
            continue
        if len({h["prompt_id"] for h in hits}) > 1:
            # 同じファイル名が複数の実行にある。取り違えるより、埋めないほうがよい
            stats["ambiguous"] += 1
            continue

        row = hits[0]
        prompt_id, entry = row["prompt_id"], row["entry"]
        graph = (entry.get("prompt") or [None, None, None])[2]
        if not isinstance(graph, dict):
            stats["no_history"] += 1
            continue
        info = analyze_graph(graph)
        if not info.get("has_textgen"):
            stats["not_textgen"] += 1
            continue
        captured, node = text_output_for(entry, info.get("textgen_consumers"))
        if not captured:
            stats["no_text_output"] += 1
            continue

        meta["en_text"] = captured
        meta["en_source"] = "comfyui_history"
        meta["en_is_rederived"] = 0
        meta["en_engine"] = info.get("llm") or "(ja2en 不明)"   # 点検 I3: 実在する鍵を使う
        meta["final_prompt"] = reconstruct_final_prompt(info, captured)
        meta["final_prompt_source"] = "reconstructed"
        meta["prompt_id"] = prompt_id
        meta["captured_from_node"] = node
        meta["captured_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

        # `asset()["meta"]` は**写し**（SQLite 版）。書き戻さないと捕獲が消える（点検 I5）
        store.set_meta(asset["id"], meta)

        write_sidecar(store.data_dir, meta, {
            "sha256": asset["sha256"],
            "path": (asset["locations"][0].get("path") if asset.get("locations") else None),
            "prompt_id": prompt_id,
            "captured_from_node": node,
            "en_text": captured,
            "final_prompt": meta["final_prompt"],
            "ja_text": meta.get("ja_text"),
            "textgen_params": meta.get("textgen_params"),
            "textgen_system_prompt": meta.get("textgen_system_prompt"),
            "concat_prefix": info.get("concat_prefix"),
            "concat_delimiter": info.get("concat_delimiter"),
            "llm": info.get("llm"),
        })
        stats["sidecars"] += 1
        stats["captured"] += 1

    if stats["captured"]:
        store.save()
    return stats


__all__ = ["capture_history", "fetch_history", "index_outputs", "text_output_for",
           "reconstruct_final_prompt", "write_sidecar", "resolve_input"]
