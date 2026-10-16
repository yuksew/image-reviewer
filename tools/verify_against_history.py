"""実データでの検証: ComfyUI の /history にある ja2en の実行を使って、来歴の取り出しを確かめる。

見本の PNG が既に消えている場合でも、`/history` にグラフと出力が残っていれば
「日本語の取り出し」「翻訳の枝の特定」「最終プロンプトの再構成」を確かめられる。

読み取りのみ。ComfyUI に何も投げない。

使い方:
  uv run python tools/verify_against_history.py [--limit 3]
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.request

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[1] / "src"))

from image_reviewer import png_meta  # noqa: E402

BASE = "http://127.0.0.1:8188"


def get(path: str):
    with urllib.request.urlopen(BASE + path, timeout=20) as r:
        return json.load(r)


def first_text(outputs: dict, node_id: str):
    """outputs[node].text は**リスト**（実測）。先頭を返す。"""
    entry = outputs.get(node_id) or {}
    text = entry.get("text")
    if isinstance(text, list):
        return text[0] if text else None
    return text


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=3)
    args = ap.parse_args()

    try:
        history = get("/history")
    except Exception as exc:  # noqa: BLE001
        print(f"ComfyUI につながりません（{BASE}）: {exc}")
        return 2

    checked = 0
    ok = 0
    for prompt_id, entry in history.items():
        prompt = entry.get("prompt")
        if not isinstance(prompt, list) or len(prompt) < 3:
            continue
        graph = prompt[2]
        if not isinstance(graph, dict):
            continue
        if not any(n.get("class_type") == "TextGenerate" for n in graph.values() if isinstance(n, dict)):
            continue

        info = png_meta.analyze_graph(graph)
        outputs = entry.get("outputs", {})
        checked += 1

        print("=" * 78)
        print(f"prompt_id = {prompt_id}")
        print(f"  モデル      : {info['model']}")
        print(f"  LoRA        : {info['loras']}")
        print(f"  seed / steps: {info['seed']} / {info['steps']}  cfg {info['cfg']}  "
              f"{info['sampler']} / {info['scheduler']}  denoise {info['denoise']}")
        print(f"  大きさ      : {info['width']} x {info['height']}")
        ja = (info.get("ja_text") or "").replace("\n", " ")
        print(f"  日本語原文  : {ja[:90]}{'…' if len(ja) > 90 else ''}")
        print(f"  TextGenerate: temperature={info['textgen_params'].get('sampling_mode.temperature')} "
              f"seed={info['textgen_params'].get('sampling_mode.seed')} "
              f"mtp={info['textgen_params'].get('mtp')} "
              f"thinking={info['textgen_params'].get('thinking')}")
        print(f"  訳の出口    : {info.get('textgen_consumers')}")

        # 捕獲: 訳の出口のうち PreviewAny（＝テキスト出力を持つノード）から取る
        captured = None
        for cons in info.get("textgen_consumers") or []:
            if cons["class_type"] in ("PreviewAny", "PreviewText", "ShowText|pysssss"):
                captured = first_text(outputs, cons["node"])
                if captured:
                    break
        if captured:
            prefix = info.get("concat_prefix") or ""
            delim = info.get("concat_delimiter") or ""
            final_prompt = f"{prefix}{delim}{captured}" if prefix else captured
            print(f"  捕獲した訳  : {captured[:90].replace(chr(10), ' ')}…（{len(captured)} 文字）")
            print(f"  最終プロンプト（再構成・{len(final_prompt)} 文字）:")
            print(f"    {final_prompt[:150].replace(chr(10), ' / ')}…")
            print("  → L1 で書き出すなら、この最終プロンプトを CLIPTextEncode に固定する（品質語を落とさない）")
            ok += 1
        else:
            print("  捕獲した訳  : 取れない（テキスト出力を持つノードがこの実行に無い）")

        if checked >= args.limit:
            break

    print("=" * 78)
    print(f"ja2en の実行を {checked} 件調べ、{ok} 件で訳の捕獲と最終プロンプトの再構成まで到達した。")
    return 0 if checked else 1


if __name__ == "__main__":
    raise SystemExit(main())
