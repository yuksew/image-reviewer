"""条件の記録（P7-1。R12 の前半）。

設計: `docs/p7-design.md` **§0.5**（再現キー＝**グラフだけの純関数**）・**§0.6**（判定と理由。
**記録時は 7 語だけ**）・**§0.7**（グラフの置き場 `<data>/workflows/<sha256>.json`）・
§0.10（`GET` は書かない・`actor`・`client_token`・原子性）・§3.1〜§3.2（口）・§4.1（`status`）

専門文書: `docs/workflow-reproduction.md` §4.1（何を固定するか）・**§4.3（再現キー。ここが正）**・
§4.5（判定）・§4.9（記録の表）

決めたことの要点:

- **鍵は「生成に寄与する部分グラフ」だけの純関数**（`SaveImage` / `PreviewImage` から遡れるノード）。
  **`filename_prefix` と `_meta` を除く**（印を付けても鍵が変わらないため）。**環境の値は混ぜない**
  （`size` / `mtime` は `env_snapshot` と `hash_mismatch` の材料。点検 A-3）
- **記録時の理由は 7 語だけ**（`missing` / `text_not_captured` / `node_missing` / `unresolved` /
  `version_differs` / `hash_mismatch` / `gpu_differs`）。**`text_pinned` などは書き出し時**（P7-2）
- **`text_not_captured` は「到達部分グラフに `CLIPTextEncode` があるのに文字列が分からないとき」だけ**
- **動的コンボ（`COMFY_DYNAMICCOMBO_V3`）は入れ子を展開してから照合**する（点検 A-1）
- **`GET` は 1 バイトも書かない**（グラフのファイルは `POST` のときだけ書く）
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
from pathlib import Path
from typing import Any, Iterable, Sequence

from . import db
from .export import _atomic_write
from .png_meta import analyze_graph, provenance, reachable_from_outputs, resolve_input
from .review import ReviewError
from .tagger import _http_json                     # 投げ方を写しにしない（gloss.py と同じ）

#: 書き出しモード（§4.2。L1 / L2 / L3）
MODES = ("pin_text", "rerun_graph", "manual_text")
DEFAULT_MODE = "pin_text"

#: **鍵から外す入力**（§0.5）。印（`filename_prefix`）を変えても鍵が変わらないため。
#: `_meta` は UI 形式の取り込みで混ざるので念のため（API 形式には無い）。
HASH_SKIP_INPUTS = frozenset({"filename_prefix", "_meta"})
#: 保存・プレビューのノード（この 2 つから遡った部分グラフが「生成に寄与する」範囲。§4.3）
OUTPUT_TYPES = ("SaveImage", "PreviewImage")

#: **記録時に出す理由の語彙（7 つだけ）**（§0.6）
RECORD_REASONS = ("missing", "text_not_captured", "node_missing", "unresolved",
                  "version_differs", "hash_mismatch", "gpu_differs")
#: `impossible` にする理由（残りは `approx`）
FATAL_REASONS = ("missing", "node_missing")

#: グラフの置き場（§0.7）
GRAPHS_DIR = "workflows"


# ---- 鍵（純関数。§0.5 / 専門文書 §4.3）----


def _node_order(node_id: str) -> tuple:
    """ノードの並びを安定させる（数字なら数として、そうでなければ文字列として）。"""
    return (0, int(node_id), "") if str(node_id).isdigit() else (1, 0, str(node_id))


def _is_link(value: Any) -> bool:
    """結線か（`[<node_id>, <slot>]` の形）。"""
    return (isinstance(value, list) and len(value) == 2
            and isinstance(value[0], (str, int)) and isinstance(value[1], int))


def canonical_graph(graph: dict) -> dict:
    """**鍵の材料**（人が読める形。テストと説明に使う）。

    - 対象は `SaveImage` / `PreviewImage` から**遡って到達できるノード**だけ
    - ノードごとに `class_type`・**リテラルの `inputs`**・**結線**（どのノードの何番目か）を分けて持つ
    - `filename_prefix` と `_meta` は**除く**（§0.5）
    """
    graph = {str(k): v for k, v in (graph or {}).items() if isinstance(v, dict)}
    reachable = reachable_from_outputs(graph)
    out: dict[str, Any] = {}
    for node_id in sorted(reachable, key=_node_order):
        node = graph.get(node_id) or {}
        class_type = node.get("class_type")
        if not class_type:
            continue
        literals: dict[str, Any] = {}
        links: dict[str, list] = {}
        for key, value in sorted((node.get("inputs") or {}).items()):
            if key in HASH_SKIP_INPUTS:
                continue                       # 印を入れても鍵を変えない（§0.5。必須）
            if _is_link(value):
                links[key] = [str(value[0]), int(value[1])]
            else:
                literals[key] = value
        entry: dict[str, Any] = {"class_type": class_type, "inputs": literals, "links": links}
        out[node_id] = entry
    return out


def recipe_hash(graph: dict) -> str:
    """再現キー（`sha256:…`）。**グラフだけの純関数**（§0.5）。

    キー昇順・空白なしの JSON にしてから SHA-256。**環境の値（`size` / `mtime` / GPU）は混ぜない**
    （混ぜると、結果の PNG から計算した鍵と書き出しの鍵が絶対に一致しなくなる）。
    """
    payload = json.dumps(canonical_graph(graph), sort_keys=True, separators=(",", ":"),
                         ensure_ascii=False).encode("utf-8")
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def graph_file(data_dir: str | Path, digest: str) -> Path:
    """グラフの置き場（§0.7）。`<data>/workflows/<sha256>.json`。"""
    return Path(data_dir) / GRAPHS_DIR / f"{digest.split(':', 1)[-1]}.json"


def save_graph(data_dir: str | Path, graph: dict, digest: str) -> Path:
    """API 形式のグラフを**原子的に**書く（一時ファイル → `os.replace`。§0.10）。

    同じグラフなら同じ名前なので、2 回書いても増えない。
    """
    return _atomic_write(graph_file(data_dir, digest), graph)


# ---- 記録（§3.2 / 専門文書 §4.1）----


#: 「取れなかった」を明示する項目（`record_json` に `null` で入る。§3.2）
RECORD_FIELDS = (
    "graph_format", "graph_source", "width", "height",
    "model", "clip", "vae", "llm", "loras",
    "sampler", "scheduler", "steps", "cfg", "denoise", "seed",
    "positive_literal", "negative_literal",
    "final_prompt", "final_prompt_source",
    "ja_text", "ja_source", "textgen_params", "has_textgen", "init_image",
    "primary_ksampler", "node_types",
)


def record_doc(*, asset_id: str, prov: dict, mode: str, text: str | None) -> dict:
    """`record_json`（§4.1 の全項目）。**取れなかった項目も `null` で書く**。

    `final_prompt` は `manual_text`（L3）のときだけ、貼られた英文で上書きする
    （`final_prompt_source='manual'`）。
    """
    info = dict(prov.get("info") or {})
    doc: dict[str, Any] = {"asset_id": asset_id, "mode": mode}
    for key in RECORD_FIELDS:
        doc[key] = info.get(key)
    doc["graph_format"] = prov.get("graph_format")
    doc["graph_source"] = "png" if prov.get("graph") else None
    doc["width"] = prov.get("width")
    doc["height"] = prov.get("height")
    if mode in ("manual_text", "pin_text") and text:
        # **監査 C-2**: `pin_text` でも貼られた英文を**残す**（前に `manual_text` だけだったので、
        # `pin_text` に `text` を添えた再送が「同じ token で違う内容」と誤判定されて 409 になっていた）。
        # 出所は `manual`（**人が渡した文**。CHECK の語彙は `png_literal` / `reconstructed` / `manual`）
        doc["final_prompt"] = text
        doc["final_prompt_source"] = "manual"
    # **取れなかった項目を名指しする**（「記録が無い」と「取れなかった」を区別する。§3.2）
    doc["missing_fields"] = sorted(k for k in RECORD_FIELDS if doc.get(k) is None)
    doc["chunk_keys"] = prov.get("chunk_keys") or []
    if prov.get("note"):
        doc["note"] = prov["note"]
    return doc


# ---- 環境の写し（§0.7 / 専門文書 §4.1・§4.6）----


class ComfyProbe:
    """ComfyUI から環境の写しを取る（**繋がらなければ `None`。記録は失敗させない**。§3.2）。

    **`/object_info`（2.39 MB）は引かない。** 使った `class_type` だけ
    **`/object_info/{class_type}`**（0.7〜3.0 KB）で引く（点検 B-2）。
    """

    def __init__(self, url: str, *, timeout: float = 5.0):
        self.base = (url or "").rstrip("/")
        self.timeout = float(timeout)
        self._declarations: dict[str, Any] = {}
        self._stats: Any = _MISSING
        self._nodes: Any = _MISSING
        self._models: dict[str, dict] = {}

    # ---- 1 つずつ（取れなければ None）----

    def system_stats(self) -> dict | None:
        if self._stats is _MISSING:
            self._stats = self._get("/system_stats")
        return self._stats

    def installed_nodes(self) -> dict | None:
        if self._nodes is _MISSING:
            self._nodes = self._get("/api/customnode/installed")
        return self._nodes

    def object_info(self, class_type: str) -> dict | None:
        """**そのノードの宣言だけ**（§3.2。`/object_info` 全体は引かない）。"""
        if class_type not in self._declarations:
            got = self._get(f"/object_info/{class_type}")
            self._declarations[class_type] = got if isinstance(got, dict) else None
        return self._declarations[class_type]

    def models(self, folder: str) -> dict:
        """`/experiment/models/{folder}`（`name` / `size` / `modified`）。"""
        if folder not in self._models:
            got = self._get(f"/experiment/models/{folder}")
            items = got if isinstance(got, list) else []
            self._models[folder] = {str(it.get("name")): {"size": it.get("size"),
                                                          "mtime": it.get("modified")}
                                    for it in items if isinstance(it, dict) and it.get("name")}
        return self._models[folder]

    def available(self) -> bool:
        return isinstance(self.system_stats(), dict)

    def _get(self, path: str) -> Any:
        try:
            return _http_json(self.base + path, timeout=self.timeout)
        except Exception:                              # noqa: BLE001 繋がらない理由は問わない
            return None


_MISSING = object()

#: モデルの名前がどのフォルダに居るか（`/experiment/models/{folder}` を引く候補）
MODEL_FOLDERS = ("diffusion_models", "checkpoints", "loras", "vae", "text_encoders", "clip")


def collect_env(probe: ComfyProbe | None, graph: dict | None, info: dict | None) -> tuple[dict, bool]:
    """環境の写しを取る。返すのは `(env, inspected)`。

    `inspected` は「ComfyUI に繋がって**宣言を確かめられた**か」。**繋がらなくても記録は作る**
    （§3.2 の表。`reasons` に `unresolved` を足す）。
    """
    env: dict[str, Any] = {
        "comfyui_version": None, "frontend_version": None, "pytorch": None, "cuda": None,
        "devices": None, "nodes": None, "declarations": None, "models": None,
        "probed_at": db.now(),
    }
    if probe is None or graph is None:
        return env, False
    stats = probe.system_stats()
    inspected = isinstance(stats, dict)
    if not inspected:
        # **P7-1 の監査 A-1**: 繋がらないときは**ここで打ち切る**。
        # 前の版は `installed_nodes()` と全 `class_type` の `/object_info` を引き続けたので、
        # 閉じた port への接続（1.8 秒 × 11〜17 回）で **1 枚 20〜32 秒**かかり、しかも
        # 引けなかった `None` を「引いたが無かった」と読んで **`node_missing` を並べていた**
        # （`impossible` になる。設計 §0.8「繋がらないときは `impossible` にしない」に反する）。
        # `declarations` は `None`（**未検査**）のまま。**`node_missing` / `unresolved` を足さない**。
        return env, False
    sysinfo = stats.get("system") or {}
    env["comfyui_version"] = sysinfo.get("comfyui_version")
    env["frontend_version"] = (stats.get("system") or {}).get("frontend_version")
    env["pytorch"] = sysinfo.get("pytorch_version")
    devices = stats.get("devices") or []
    env["devices"] = devices
    if devices and isinstance(devices[0], dict):
        env["cuda"] = devices[0].get("cuda_version") or devices[0].get("name")
    nodes = probe.installed_nodes()
    if nodes is not None:
        env["nodes"] = nodes if isinstance(nodes, dict) else None
    # **使ったノードの宣言だけ**（点検 B-2）
    class_types = sorted({str(v.get("class_type")) for v in (graph or {}).values()
                          if isinstance(v, dict) and v.get("class_type")})
    declarations: dict[str, Any] = {}
    for class_type in class_types:
        got = probe.object_info(class_type)
        if isinstance(got, dict):
            # **引いたが無かった**（知らない `class_type`）→ `{}`（監査 A-1）
            declarations[class_type] = got.get(class_type, {})
        else:
            # **引けなかった**（通信の失敗）→ `None`。**この 2 つを混ぜない**
            declarations[class_type] = None
    env["declarations"] = declarations
    # モデルの `(name, size, mtime)`（**名前だけで足りないときの材料**。鍵には入れない。§0.5）
    wanted: dict[str, str] = {}
    for key, value in (("model", (info or {}).get("model")), ("vae", (info or {}).get("vae")),
                       ("clip", (info or {}).get("clip"))):
        if isinstance(value, str):
            wanted[value] = key
    for lora in (info or {}).get("loras") or []:
        if isinstance(lora, dict) and isinstance(lora.get("name"), str):
            wanted[lora["name"]] = "loras"
    found: dict[str, Any] = {}
    for folder in MODEL_FOLDERS:
        if not wanted:
            break
        items = probe.models(folder)
        for name, meta in items.items():
            if name in wanted and name not in found:
                found[name] = {"folder": folder, **meta}
    env["models"] = found or None
    return env, inspected


# ---- 宣言との突き合わせ（§4.7 手順 4・点検 A-1）----


def dynamic_subkeys(declaration: Any, selected: Any = None) -> set[str] | None:
    """`COMFY_DYNAMICCOMBO_V3` の**入れ子キーを展開**する（点検 A-1）。

    宣言は `["COMFY_DYNAMICCOMBO_V3", {"options": [{"key": "on", "inputs": {"required": {...}}}, …]}]`
    の形。**選ばれている選択肢**（グラフの `sampling_mode` の値）があれば、その選択肢のキーだけを返す。
    展開できない `COMFY_DYNAMIC*` は `None`（**検査の対象外にして `notes` に出す**）。
    """
    if not (isinstance(declaration, list) and len(declaration) == 2):
        return None
    tag, spec = declaration
    if not (isinstance(tag, str) and tag.startswith("COMFY_DYNAMIC")):
        return None
    options = (spec or {}).get("options") if isinstance(spec, dict) else None
    if not isinstance(options, list):
        return None
    keys: set[str] = set()
    for option in options:
        if not isinstance(option, dict):
            continue
        if selected is not None and option.get("key") != selected:
            continue
        for group in ("required", "optional"):
            block = (option.get("inputs") or {}).get(group) or {}
            if isinstance(block, dict):
                keys |= {str(k) for k in block}
    return keys


def _declared_spec(declaration: dict | None, key: str) -> Any:
    """宣言から 1 つの入力の指定を引く（`required` → `optional`）。"""
    if not isinstance(declaration, dict):
        return None
    block = declaration.get("input") or {}
    for group in ("required", "optional"):
        got = (block.get(group) or {}).get(key)
        if got is not None:
            return got
    return None


def combos(declaration: dict | None, key: str) -> list | None:
    """その入力がコンボ（選択肢）なら選択肢の一覧を返す。違えば `None`。

    受ける形は 2 つ:
    - 新しい形: `["COMBO", {"options": [...]}]`
    - 古い形: **`[["a", "b"], {…}]`（最初の要素が選択肢の配列）**
    **文字列の指定（`["STRING", {}]`）や動的コンボ（`["COMFY_DYNAMICCOMBO_V3", …]`）は `None`**
    （値を選択肢と突き合わせる検査の対象ではない）。
    """
    spec = _declared_spec(declaration, key)
    if not (isinstance(spec, list) and spec):
        return None
    if isinstance(spec[0], str) and spec[0] == "COMBO" and len(spec) == 2 and isinstance(spec[1], dict):
        options = spec[1].get("options")
        return list(options) if isinstance(options, list) else None
    if isinstance(spec[0], list):
        return list(spec[0])
    return None


def is_dynamic(spec: Any) -> bool:
    """`COMFY_DYNAMIC*` の宣言か（点検 A-1）。"""
    return (isinstance(spec, list) and len(spec) == 2 and isinstance(spec[0], str)
            and spec[0].startswith("COMFY_DYNAMIC"))


def declaration_notes(graph: dict, declarations: dict | None) -> tuple[list[dict], list[str]]:
    """ノードの `inputs` が**宣言と合っているか**を見る（§4.7 手順 4）。

    返すのは `(reasons, notes)`。`notes` は「検査できなかったこと」の記録
    （展開できない動的コンボ・宣言が取れていないノード）。

    - **動的コンボの入れ子は展開してから照合**する（点検 A-1）。展開できない `COMFY_DYNAMIC*` は**対象外**
    - **モデル / LoRA / VAE が選択肢に無い → `impossible`**（`unresolved` の重い側。§0.6）
    - **宣言に無いキー → `approx` ＋ キー名**（`unresolved` の軽い側）
    """
    reasons: list[dict] = []
    notes: list[str] = []
    if not isinstance(declarations, dict):
        return reasons, ["宣言が取れていないので入力キーは検査していない"]
    graph = {str(k): v for k, v in (graph or {}).items() if isinstance(v, dict)}
    reachable = reachable_from_outputs(graph)
    for node_id in sorted(reachable, key=_node_order):
        node = graph[node_id]
        class_type = node.get("class_type")
        declaration = declarations.get(class_type)
        if declaration is None:
            # **引けなかった**（その 1 回の `/object_info` が落ちた）→ **検査していない**。
            # 監査 A-1: 前の版はここを「今の環境に無い」と読んで `node_missing` を並べていた
            notes.append(f"{class_type} の宣言が取れなかった（検査していない）")
            continue
        if declaration == {}:
            # **引いたが無かった＝ComfyUI が知らないノード**（今の環境に無い）。**impossible**
            reasons.append(_reason("node_missing", f"{class_type}（ノード {node_id}）"))
            continue
        inputs = node.get("inputs") or {}
        for key, value in sorted(inputs.items()):
            if "." in key:                        # 動的コンボの入れ子（例 `sampling_mode.temperature`）
                container, sub = key.split(".", 1)
                spec = _declared_spec(declaration, container)
                if spec is None:
                    reasons.append(_reason("unresolved", f"{class_type}.{key}"))
                    continue
                subs = dynamic_subkeys(spec, inputs.get(container))
                if subs is None:
                    notes.append(f"{class_type}.{container} は展開できない動的コンボ（検査の対象外）")
                    continue
                if sub not in subs:
                    reasons.append(_reason("unresolved", f"{class_type}.{key}"))
                continue
            spec = _declared_spec(declaration, key)
            if spec is None:
                reasons.append(_reason("unresolved", f"{class_type}.{key}"))
                continue
            if is_dynamic(spec):
                # **展開できない動的コンボは検査の対象外**にして `notes` に出す（§4.7 手順 4）
                if dynamic_subkeys(spec, value if isinstance(value, str) else None) is None:
                    notes.append(f"{class_type}.{key} は展開できない動的コンボ（検査の対象外）")
                continue
            # モデルなどの選択肢に無い値（**重い側**。§0.6）
            if isinstance(value, str):
                options = combos(declaration, key)
                if options is not None and value not in options:
                    # **P7-1 の監査 A-2**: モデル / LoRA / VAE が選択肢に無いのは**致命**（§0.6。
                    # その値では二度と実行できない）。**語彙は増やさず** `fatal` の印で `judge` に伝える
                    reasons.append(_reason("unresolved",
                                           f"{class_type}.{key}={value}（選択肢に無い）",
                                           fatal=_is_model_input(class_type, key)))
    return reasons, notes


#: モデルを指す入力の名前（`unet_name` / `ckpt_name` / `lora_name` / `vae_name` / …）。
#: **選択肢に無ければ致命**（監査 A-2）。`_name` で終わる物とローダーの class で見る
MODEL_INPUT_KEYS = ("model", "model_name", "unet_name", "ckpt_name", "lora_name", "vae_name",
                    "clip_name", "clip_name1", "clip_name2", "text_encoder_name",
                    "control_net_name", "style_model_name", "embedding_name")


def _is_model_input(class_type: Any, key: str) -> bool:
    """その入力が**モデルの実体**を指すか（監査 A-2。選択肢に無ければ `impossible`）。"""
    if key in MODEL_INPUT_KEYS or key.endswith("_name"):
        return True
    return "Loader" in str(class_type or "")


def _reason(kind: str, detail: str, *, fatal: bool = False) -> dict:
    """理由 1 つ。`fatal=True` は「その値では実行できない」（監査 A-2。**語彙は増やさない**）。"""
    got = {"kind": kind, "detail": detail}
    if fatal:
        got["fatal"] = True
    return got


# ---- 判定（§0.6）----


def text_unknown(graph: dict) -> bool:
    """到達部分グラフに `CLIPTextEncode` があり、**その `text` が分からない**か（§0.6 / 監査 B-2）。

    **分かっている**の定義: `text` がリテラルの文字列、または結線先をたどって文字列に行き着く
    （`resolve_input`。`png_meta` の `final_prompt` は**主の `KSampler` の正側から**しか埋まらないので、
    `SamplerCustomAdvanced` のような経路では `final_prompt` が `None` でも文字列は分かっている。
    前の版はそれでも `text_not_captured` を付けていた）。
    """
    graph = {str(k): v for k, v in (graph or {}).items() if isinstance(v, dict)}
    for nid in reachable_from_outputs(graph):
        node = graph[nid]
        if node.get("class_type") != "CLIPTextEncode":
            continue
        # `resolve_input` は `(値, 出所)` を返す（`png_meta.py`）
        got, _source = resolve_input(graph, node, "text")
        if not (isinstance(got, str) and got.strip()):
            return True                     # **文字列が分からない**（例: `TextGenerate` の出力を参照）
    return False


def has_text_encoder(graph: dict) -> bool:
    """到達部分グラフに `CLIPTextEncode` があるか（`text_not_captured` の条件。§0.6）。"""
    graph = {str(k): v for k, v in (graph or {}).items() if isinstance(v, dict)}
    reachable = reachable_from_outputs(graph)
    return any((graph[nid].get("class_type") == "CLIPTextEncode") for nid in reachable)


def captured_reconstruct(info: dict, captured: str) -> str:
    """捕まえた英訳を**最終プロンプトに組み直す**（`capture.reconstruct_final_prompt` と同じ規則）。

    `StringConcatenate` の前置き（`(masterpiece, best quality), safe,` など）と区切りを戻す。
    写しを作らずに 1 か所で持つため、ここに置いて `capture` 側と**同じ規則**であることを明記する。
    """
    prefix = info.get("concat_prefix") or ""
    delim = info.get("concat_delimiter") or ""
    return f"{prefix}{delim}{captured}" if prefix else captured


def judge(*, prov: dict, doc: dict, env: dict, inspected: bool,
          extra: Sequence[dict] = (), notes: Sequence[str] = ()) -> dict:
    """記録した時点の `status` と `reasons`（§0.6。**7 語だけ**）。

    `impossible` ⊃ {グラフが無い, 必須のノード / モデルが今の環境に無い} /
    `approx` ⊃ {理由が 1 つ以上} / `exact` ⊃ {理由が 0 件}。
    """
    graph = prov.get("graph")
    reasons: list[dict] = []
    out_notes = list(notes)
    if not graph:
        reasons.append(_reason("missing", "prompt チャンクが無い（生成条件が残っていない画像）"))
    else:
        for item in (prov.get("info") or {}).get("unresolved") or []:
            reasons.append(_reason("unresolved", str(item)))
        if text_unknown(graph) and not doc.get("final_prompt"):
            reasons.append(_reason("text_not_captured",
                                   "CLIPTextEncode があるのに文字列が分からない（ja2en のリンク参照）"))
        reasons.extend(extra)
    if not inspected:
        out_notes.append("ComfyUI に繋がらなかったので宣言は確かめていない")
    # **監査 A-2**: 選択肢に無いモデルなどは `fatal` の印で `impossible` に上げる（**語彙は 7 語のまま**）
    fatal = any(r["kind"] in FATAL_REASONS or r.get("fatal") for r in reasons)
    status = "impossible" if fatal else ("approx" if reasons else "exact")
    return {"status": status, "reasons": reasons, "inspected": bool(inspected), "notes": out_notes}


# ---- サービス（口から使う）----


class RecipeService:
    """条件の記録（P7-1）。**模型も ComfyUI も呼ばない**（環境の写しを取るときだけ `GET` する）。"""

    def __init__(self, store, *, probe_factory=None) -> None:
        self.store = store
        #: テストは偽の probe を差し込む（**ComfyUI を叩かない**）
        self._probe_factory = probe_factory or (lambda settings: ComfyProbe(settings["url"]))

    # ---- 読む ----

    def get(self, asset_id: str) -> dict:
        """1 枚の記録（`GET /api/assets/{id}/recipe`）。**書かない**。無ければ 404。"""
        with self.store.locked() as con:
            row = con.execute("SELECT * FROM recipe_record WHERE source_asset_id = ?",
                              (asset_id,)).fetchone()
        if row is None:
            raise ReviewError(404, "この画像の記録はありません", details={"asset_id": asset_id})
        return self._doc_of(row)

    def list(self, *, limit: int = 50, cursor: str | None = None,
             status: str | None = None) -> dict:
        """一覧（`GET /api/recipes`）。**キーセット**（`created_at DESC, id DESC`）。**書かない**。

        **（P7-4）`status` で判定を絞れる**（画面 §5.4 の「判定で絞る」）。語彙は
        `exact` / `approx` / `impossible` だけで、外れたら **422**（`CHECK` に当てて 500 にしない）。
        """
        size = max(1, min(int(limit or 50), 200))
        where, args = [], []
        if status:
            if status not in ("exact", "approx", "impossible"):
                raise ReviewError(422, "status は exact | approx | impossible です",
                                  details={"status": status})
            where.append("status = ?")
            args.append(status)
        if cursor:
            pair = str(cursor).split("|", 1)
            if len(pair) != 2:
                raise ReviewError(422, "cursor が不正です", details={"cursor": str(cursor)})
            where.append("(created_at < ? OR (created_at = ? AND id < ?))")
            args.extend([pair[0], pair[0], pair[1]])
        clause = (" WHERE " + " AND ".join(where)) if where else ""
        with self.store.locked() as con:
            rows = con.execute("SELECT * FROM recipe_record" + clause
                               + " ORDER BY created_at DESC, id DESC LIMIT ?",
                               [*args, size + 1]).fetchall()
        more = len(rows) > size
        rows = rows[:size]
        # **監査 G-6-(a)**: 一覧は**要約だけ**（`record` / `env` は 1 枚の口で取る）
        items = [self._summary_of(r) for r in rows]
        return {"items": items,
                "next_cursor": f"{rows[-1]['created_at']}|{rows[-1]['id']}" if (more and rows) else None}

    @staticmethod
    def _summary_of(row) -> dict:
        """一覧の 1 行（**要約**。監査 G-6-(a)）。`record` / `env` は入れない。"""
        details = _load(row["reasons"]) or []
        return {
            "recipe_id": row["id"],
            "asset_id": row["source_asset_id"],
            "mode": row["mode"],
            "recipe_hash": row["recipe_hash"],
            "graph_kind": row["graph_kind"],
            "graph_path": _existing_path(row["graph_path"]),
            "status": row["status"],
            "reasons": [r.get("kind") for r in details if isinstance(r, dict)],
            "actor": row["actor"],
            "created_at": row["created_at"],
        }

    @staticmethod
    def _doc_of(row) -> dict:
        """契約に近い形（`record_json` / `reasons` / `env_snapshot` は JSON を解いて返す）。

        **`reasons` は語（`kind`）の配列**（§3.2 の応答例と同じ形。**書き込みでも再送でも同じ形**にする）。
        詳しい説明は `reason_details` に入れる（画面が「なぜ近似なのか」を出せるように）。

        **（監査 A-4）`graph_path` は実体があるときだけ返す**（消えていれば `null`。`GET` は書かない）。
        **（監査 B-3）`inspected` と `notes` は `record_json` に残す**（201 の応答だけに出して
        `GET` で消えると、「確かめた `exact`」と「繋がらなかった `exact`」を区別できない）。
        """
        details = _load(row["reasons"]) or []
        rec = _load(row["record_json"]) or {}
        return {
            "recipe_id": row["id"],
            "asset_id": row["source_asset_id"],
            "mode": row["mode"],
            "recipe_hash": row["recipe_hash"],
            "graph_path": _existing_path(row["graph_path"]),
            "graph_kind": row["graph_kind"],
            # **（P7-4）`graph_source` も `GET` で返す**（`{'png','history','sidecar'}`）。
            # `POST` の応答には前から入っていたが、`GET` には無かったので
            # **画面の「出所」が `—` になっていた**（記録の由来を画面で確かめられない）
            "graph_source": (rec.get("graph_source") if isinstance(rec, dict) else None),
            "record": rec,
            "final_prompt": row["final_prompt"],
            "final_prompt_source": row["final_prompt_source"],
            "captured_text": row["captured_text"],
            "captured_source": row["captured_source"],
            "text_probe": row["text_probe"],
            "env": _load(row["env_snapshot"]),
            "status": row["status"],
            "reasons": [r.get("kind") for r in details if isinstance(r, dict)],
            "reason_details": details,
            "inspected": rec.get("inspected"),
            "notes": rec.get("notes") or [],
            "actor": row["actor"],
            "created_at": row["created_at"],
        }

    # ---- 書く ----

    def record(self, asset_id: str, *, mode: str = DEFAULT_MODE, text: str | None = None,
               actor: str = "human", client_token: str | None = None) -> dict:
        """記録する（`POST /api/assets/{id}/recipe`。§3.2）。

        **画像 1 枚に 1 記録**（`ux_recipe_source`）。同じ `client_token` の再送は 200 で既存を返す。
        **グラフのファイルはここでだけ書く**（`GET` は書かない）。
        """
        if mode not in MODES:
            raise ReviewError(422, "mode は pin_text | rerun_graph | manual_text です",
                              details={"mode": "pin_text | rerun_graph | manual_text"})
        if mode == "manual_text" and not (text or "").strip():
            raise ReviewError(422, "manual_text には英文が要ります", details={"text": "英文が要ります"})
        text = (text or "").strip() or None
        # --- ① 読む（錠だけ）---
        found = None
        with self.store.locked() as con:
            asset = con.execute("SELECT * FROM asset WHERE id = ?", (asset_id,)).fetchone()
            if asset is None:
                raise ReviewError(404, "画像がありません", details={"asset_id": asset_id})
            payload = {"asset_id": asset_id, "mode": mode, "text": text}
            replay = self._replay(con, client_token, payload)
            if replay is not None:
                return replay
            existing = con.execute("SELECT * FROM recipe_record WHERE source_asset_id = ?",
                                   (asset_id,)).fetchone()
            if existing is not None:
                # **錠の外で**作り直す（`_ensure_graph_file` は自分で錠と取引を取るので、
                # ここで呼ぶと**錠の入れ子**になる。P7-1 の監査の直しで踏んだ）
                found = dict(existing)
            else:
                paths = [r["path"] for r in con.execute(
                    "SELECT path FROM asset_location WHERE asset_id = ?"
                    " ORDER BY is_primary DESC, path", (asset_id,))]
                settings = _settings(con)
        if found is not None:
            # **監査 A-4**: グラフのファイルが消えていたら**ここで作り直す**（`POST` だけが書く）。
            # 無ければそのまま 200 で返す（`_doc_of` が `graph_path: null` にする）
            return self._ensure_graph_file(found)
        # --- ② 外（PNG を読み、ComfyUI に聞く。**錠の外**）---
        prov = _provenance_of(paths)
        graph = prov.get("graph")
        probe = self._probe_factory(settings) if settings.get("url") else None
        env, inspected = collect_env(probe, graph, prov.get("info"))
        extra, notes = declaration_notes(graph or {}, env.get("declarations"))
        doc = record_doc(asset_id=asset_id, prov=prov, mode=mode, text=text)
        verdict = judge(prov=prov, doc=doc, env=env, inspected=inspected,
                        extra=extra, notes=notes)
        # **監査 B-3**: 「確かめたか」「検査の注記」を**行に残す**（応答だけにしない）
        doc["inspected"] = verdict["inspected"]
        doc["notes"] = verdict["notes"]
        digest = recipe_hash(graph) if graph else "sha256:" + hashlib.sha256(b"").hexdigest()
        # **監査 B-1**: ファイル名は**画像の内容ハッシュ**（§2.3）。`recipe_hash` を名前に入れると、
        # **同じ鍵で `filename_prefix` だけ違う 2 枚目が 1 枚目のファイルを黙って書き換える**
        graph_path = (str(save_graph(self.store.data_dir, graph, _asset_digest(asset)))
                      if graph else None)
        # --- ③ 短い 1 取引で書く ---
        recipe_id = db.ulid()
        with self.store.transaction() as con:
            # **監査 A-3**: 同じ画像への同時 `POST` で 2 本目が `IntegrityError` → 500 になっていた
            # （錠を離れて ComfyUI に聞く間に別の 1 本が入る）。**衝突したら黙って譲り**、
            # 入っている行を読み直して 200 で返す（`docs/p6-1a-audit-report.md` §2-2 と同じ型）
            con.execute(
                "INSERT INTO recipe_record(id, source_asset_id, mode, recipe_hash, graph_path,"
                " graph_kind, record_json, final_prompt, final_prompt_source, captured_text,"
                " captured_source, text_probe, env_snapshot, status, reasons, actor, client_token,"
                " created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)"
                " ON CONFLICT DO NOTHING",
                (recipe_id, asset_id, mode, digest, graph_path,
                 doc.get("graph_format") if graph else None, _dump(doc), doc.get("final_prompt"),
                 doc.get("final_prompt_source"), None, None, None, _dump(env),
                 verdict["status"], _dump(verdict["reasons"]), actor, client_token, db.now()))
            stored = con.execute("SELECT * FROM recipe_record WHERE source_asset_id = ?",
                                 (asset_id,)).fetchone()
            if stored is None or stored["id"] != recipe_id:
                # 負けた側（別の 1 本が先に入れた）。**その行を返す**（`replayed=True`）
                return {**self._doc_of(stored), "replayed": True}
        return {"recipe_id": recipe_id, "asset_id": asset_id, "mode": mode,
                "recipe_hash": digest, "graph_path": graph_path,
                "graph_source": doc.get("graph_source"),
                "status": verdict["status"],
                "reasons": [r["kind"] for r in verdict["reasons"]],
                "inspected": verdict["inspected"], "notes": verdict["notes"],
                "replayed": False}

    def capture_text(self, asset_id: str, *, text: str, prompt_id: str | None = None,
                     node: str | None = None) -> dict | None:
        """**（監査 A-3 / 設計 §0.9 の ①〜③）監視が捕まえた英訳を記録に取り込み、判定を上げ直す。**

        英訳（`TextGenerate` の出力）は**実行の瞬間にしか無い**（PNG には残らない）ので、
        監視が動いている間に捕まえないと**記録は `approx` のまま**になる
        （実データの ja2en の 1 枚がこれに当たる。§1.2 の線 2 の注記）。

        やること: `record_json` の `captured_text` / `captured_source` / `final_prompt` /
        `final_prompt_source` を埋め、**`judge` を通し直して `status` / `reasons` を上げる**
        （`text_not_captured` が消えれば `approx` → `exact`）。**記録が無い画像なら何もしない**。
        """
        body = (text or "").strip()
        with self.store.locked() as con:
            row = con.execute("SELECT * FROM recipe_record WHERE source_asset_id = ?",
                              (asset_id,)).fetchone()
        if row is None or not body:
            return None
        doc = json.loads(row["record_json"] or "{}")
        env = json.loads(row["env_snapshot"] or "{}")
        # **グラフは `record_json` ではなくファイル**（`graph_path`。§0.7 の置き場）にある。
        # 記録のときに書いた API 形式 JSON を読み戻す（無ければ PNG から作り直す道は P7-1 の `record`）
        graph = doc.get("graph") if isinstance(doc.get("graph"), dict) else None
        if graph is None and row["graph_path"]:
            try:
                graph = json.loads(Path(row["graph_path"]).read_text(encoding="utf-8"))
            except Exception:                        # noqa: BLE001  消えた・壊れたファイルは黙って諦める
                graph = None
        if graph is None:
            return None
        info = analyze_graph(graph)
        final_prompt = captured_reconstruct(info, body)
        doc["captured_text"] = body
        doc["captured_source"] = "comfyui_history"
        doc["final_prompt"] = final_prompt
        doc["final_prompt_source"] = "reconstructed"
        if prompt_id:
            doc["prompt_id"] = prompt_id
        if node:
            doc["captured_from_node"] = node
        verdict = judge(prov={"graph": graph, "info": info}, doc=doc, env=env,
                        inspected=bool(doc.get("inspected")), notes=doc.get("notes") or ())
        with self.store.transaction() as con:
            con.execute(
                "UPDATE recipe_record SET record_json = ?, final_prompt = ?,"
                " final_prompt_source = ?, captured_text = ?, captured_source = ?,"
                " text_probe = ?, status = ?, reasons = ? WHERE id = ?",
                (_dump(doc), final_prompt, "reconstructed", body, "comfyui_history",
                 body, verdict["status"], _dump(verdict["reasons"]), row["id"]))
        return {"recipe_id": row["id"], "status": verdict["status"], "reasons": verdict["reasons"],
                "final_prompt": final_prompt}

    def _ensure_graph_file(self, row) -> dict:
        """**消えたグラフのファイルを作り直す**（監査 A-4。`POST` だけが書く）。

        `GET` は書かないので、消えていれば `graph_path: null` を返す（`_doc_of`）。
        ここは記録の口（`POST`）から来たときだけ呼ぶ。PNG から読めなければそのまま返す。
        """
        path = row["graph_path"]
        if path and not Path(str(path)).exists():
            with self.store.locked() as con:
                paths = [r["path"] for r in con.execute(
                    "SELECT path FROM asset_location WHERE asset_id = ?"
                    " ORDER BY is_primary DESC, path", (row["source_asset_id"],))]
            graph = _provenance_of(paths).get("graph")
            if graph:
                with self.store.locked() as con:
                    asset = con.execute("SELECT * FROM asset WHERE id = ?",
                                        (row["source_asset_id"],)).fetchone()
                new_path = str(save_graph(self.store.data_dir, graph, _asset_digest(asset)))
                with self.store.transaction() as con:
                    con.execute("UPDATE recipe_record SET graph_path = ? WHERE id = ?",
                                (new_path, row["id"]))
                row = {**dict(row), "graph_path": new_path}
        return {**self._doc_of(row), "replayed": True}

    # ---- 道具 ----

    @staticmethod
    def _replay(con, client_token: str | None, payload: dict) -> dict | None:
        """同じ `client_token` の再送（§0.10）。中身が違えば 409。"""
        if not client_token:
            return None
        row = con.execute("SELECT * FROM recipe_record WHERE client_token = ?",
                          (client_token,)).fetchone()
        if row is None:
            return None
        stored = {"asset_id": row["source_asset_id"], "mode": row["mode"],
                  "text": (row["final_prompt"] if row["final_prompt_source"] == "manual" else None)}
        if _dump(stored) != _dump(payload):
            raise ReviewError(409, "同じ client_token で違う内容が来ました",
                              code="client_token_conflict",
                              details={"client_token": client_token})
        return {**RecipeService._doc_of(row), "replayed": True}


# ---- 小さな道具 ----


def _dump(value: Any) -> str:
    """JSON の文字列（キー順を固定して、比較と決定性を守る）。"""
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _asset_digest(asset) -> str:
    """グラフのファイル名に使う**画像の内容ハッシュ**（§2.3。監査 B-1）。

    前の版は `recipe_hash`（条件の鍵）を名前に入れていたので、**同じ鍵で `filename_prefix` だけ
    違う 2 枚目が 1 枚目のファイルを黙って書き換えていた**（鍵からは `filename_prefix` を除いてある）。
    **同じ画像なら同じファイル**（§0.4）にもなる。
    """
    sha = str((asset or {}).get("sha256") if hasattr(asset, "get") else asset["sha256"] or "")
    return sha if ":" in sha else f"sha256:{sha}"


def _existing_path(path: Any) -> str | None:
    """**実体があるときだけ**パスを返す（監査 A-4。`GET` は書かないので、無ければ `null`）。"""
    if path and Path(str(path)).exists():
        return str(path)
    return None


def _load(raw: Any) -> Any:
    if raw in (None, ""):
        return None
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        return None


def _provenance_of(paths: Iterable[str]) -> dict:
    """**実体がある最初の場所**から来歴を読む（無ければ「グラフ無し」の写しを返す）。"""
    last: dict | None = None
    for path in paths:
        if not path or not Path(path).exists():
            continue
        got = provenance(path)
        if got.get("graph"):
            return got
        last = last or got
    return last or {"ok": False, "width": None, "height": None, "chunk_keys": [],
                    "graph_format": None, "graph": None, "info": None,
                    "note": "実体が見つかりません"}


def _settings(con) -> dict:
    """`settings` から要る物だけ（`comfyui.url`。無ければ `tagger.comfyui` → 既定）。"""
    got: dict[str, str] = {}
    try:
        for row in con.execute("SELECT key, value FROM settings WHERE key IN"
                               " ('comfyui.url', 'tagger.comfyui')"):
            got[row["key"]] = row["value"]
    except Exception:                                  # noqa: BLE001 表が無い環境でも既定で動く
        pass
    return {"url": (got.get("comfyui.url") or got.get("tagger.comfyui")
                    or "http://127.0.0.1:8188").rstrip("/")}
