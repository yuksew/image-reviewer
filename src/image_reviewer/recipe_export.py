"""書き出し（P7-2。R12 の中盤）。

設計: `docs/p7-design.md` **§0.4**（`mode` の写し方）・**§0.8**（書き出す前の検査。点検 A-1 / B-2）・
**§0.7**（印の前提 3 つと `'前提1'`〜`'前提3'`。**空白なし**）・**§0.9**（seed の増やし方）・
**§0.10**（`GET` は書かない・`actor`・`client_token`・原子性）・**§3.3**（`export` の口）・
**§4.7.2**（書き換えるのは最初の `KSampler` だけ）・**§6.1〜§6.2**（manifest と置き場）

専門文書: `docs/workflow-reproduction.md` §4.7（手順 1〜4）・§4.7.1（印の前提）・§4.7.2（seed）・§4.7.3（manifest）

決めたことの要点:

- **`recipe_hash` と判定の規則は `recipe.py` の物をそのまま使う**（この段では変えない）。**書き出したグラフ**の鍵は
  別に持つ（`recipe_export.recipe_hash`。§0.5）
- **検査は 3 つ**（① 保存ノードが 1 つ ② `filename_prefix` がリテラル ③ 入力キーが宣言にある）。
  **③ は動的コンボを展開してから**照合し、展開できない `COMFY_DYNAMIC*` は**対象外にして `notes`** に出す
- **`/object_info/{class_type}` だけ引く**（2.39 MB の一括は引かない。点検 B-2）。**class_type ごとに 60 秒キャッシュ**
- **ComfyUI につながらないときは止めない**（`checked.inspected=false` で**書き出す**）
- **印を付けても鍵は変わらない**（鍵から `filename_prefix` を除いてある）。**変わるのは `TextGenerate` を持つ
  グラフを `pin_text` で書き出したとき**（`text_pinned` を理由に `approx`）
- **`GET` は 1 バイトも書かない**。ファイルは `POST` のときだけ、**一時ファイル → `os.replace`** で書く
"""

from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from typing import Any, Sequence

from . import db
from .export import _atomic_write
from .recipe import (DEFAULT_MODE, MODES, OUTPUT_TYPES, _dump, _load, _provenance_of,
                     canonical_graph, recipe_hash)
from .review import ReviewError

#: 1 回の書き出しで作れるファイルの上限（§3.3）
MAX_SEEDS = 64
DEFAULT_COUNT = 8
#: seed は 64bit で折り返す（§0.9。`(seed + k) mod 2^64`）
SEED_MODULUS = 1 << 64

#: 印の前置き（§0.7）。**`subfolder` が `repro-<attempt_id>` のフォルダになる**（点検 B-4）
MARKER_PREFIX = "repro-"
ATTEMPT_MIN = 8

#: 書き出しのときにだけ出す理由（§0.6。**記録時の 7 語とは別**）
EXPORT_REASONS = ("text_pinned", "llm_nondeterministic", "manual_step")

#: 置き場（§6.1）: `<data>/recipes/<recipe_id>/<attempt_id>/`
RECIPES_DIR = "recipes"

#: 宣言のキャッシュの寿命（秒。§0.8 の「60 秒キャッシュ」）
DECL_TTL_SECONDS = 60.0


# ---- 小さな道具 ----


def new_attempt_id() -> str:
    """印に使う短い id（**8 文字以上の `[a-z0-9]`**。§0.7 / 点検 D-12）。

    `db.ulid()` は Crockford の base32（`0-9A-Z` から紛らわしい字を除いた物）なので、
    **小文字にすれば `[a-z0-9]`** になる。末尾 8 文字を使う（先頭は時刻なので、末尾の方が散る）。
    大文字を含む語（`I` `L` `O` `U`）は Crockford では使われないが、念のため小文字の英字だけを残す。
    """
    raw = "".join(ch for ch in db.ulid().lower() if ch.isdigit() or ("a" <= ch <= "z"))
    return raw[-ATTEMPT_MIN:]


def seeds_for(seed: Any, count: int) -> list[str]:
    """`seed` から `count` 個の seed（**文字列**。§0.9）。

    **`(seed + k) mod 2^64`**。`seed` は**当時の seed**（記録から取る。分からなければ呼ぶ側が決める）。
    """
    base = int(str(seed).strip() or 0)
    return [str((base + k) % SEED_MODULUS) for k in range(max(1, int(count)))]


def marker_for(attempt_id: str, seed: str | None) -> str:
    """印（`SaveImage.filename_prefix` に入れる字。§0.7）。

    **seed が無いグラフは `…/noseed`**（点検 G-3 と同じ字）。
    """
    tail = f"seed-{seed}" if seed is not None else "noseed"
    return f"{MARKER_PREFIX}{attempt_id}/{tail}"


def attempt_dir(data_dir: str | Path, recipe_id: str, attempt_id: str) -> Path:
    """書き出しの置き場（§6.1）。`<data>/recipes/<recipe_id>/<attempt_id>/`。"""
    return Path(data_dir) / RECIPES_DIR / recipe_id / attempt_id


def graph_out_name(seed: str | None) -> str:
    """1 ファイルの名前（§6.1）。seed が無いときは `seed-noseed.json`。"""
    return f"seed-{seed if seed is not None else 'noseed'}.json"


# ---- グラフを触る（検査と変換）----


def save_nodes(graph: dict) -> list[str]:
    """保存・プレビューのノード（`SaveImage` / `PreviewImage`）。**並びは安定**（§0.8 ①）。"""
    out = [str(nid) for nid, node in (graph or {}).items()
           if isinstance(node, dict) and node.get("class_type") in OUTPUT_TYPES]
    return sorted(out, key=lambda n: (0, int(n), "") if n.isdigit() else (1, 0, n))


def _links_of(graph: dict) -> dict[str, list[tuple[str, str]]]:
    """`node_id` → そのノードが**参照している** `(元の node_id, 入力キー)` の一覧。"""
    out: dict[str, list[tuple[str, str]]] = {}
    for nid, node in (graph or {}).items():
        if not isinstance(node, dict):
            continue
        refs: list[tuple[str, str]] = []
        for key, value in (node.get("inputs") or {}).items():
            if (isinstance(value, list) and len(value) == 2
                    and isinstance(value[0], (str, int)) and isinstance(value[1], int)):
                refs.append((str(value[0]), key))
        out[str(nid)] = refs
    return out


def reachable(graph: dict, start: str) -> set[str]:
    """`start` から**遡って**到達できるノード（結線を逆に辿る）。"""
    links = _links_of(graph)
    seen: set[str] = set()
    stack = [start]
    while stack:
        nid = stack.pop()
        if nid in seen or nid not in graph:
            continue
        seen.add(nid)
        for src, _key in links.get(nid, []):
            if src not in seen:
                stack.append(src)
    return seen


def first_ksampler(graph: dict, save_id: str) -> tuple[str | None, list[str]]:
    """保存ノードから遡って**最初の `KSampler`** と、**残りの `KSampler`**（§4.7.2）。

    「最初」は**保存ノードに近い方**（幅優先）。残りは `other_ksamplers` として画面に出す
    （**seed を揃えられないことを黙らない**）。
    """
    links = _links_of(graph)
    order: list[str] = []
    seen: set[str] = set()
    queue = [save_id]
    while queue:
        nid = queue.pop(0)
        if nid in seen or nid not in graph:
            continue
        seen.add(nid)
        order.append(nid)
        for src, _key in links.get(nid, []):
            if src not in seen:
                queue.append(src)
    samplers = [n for n in order
                if isinstance(graph.get(n), dict) and graph[n].get("class_type") == "KSampler"]
    return (samplers[0] if samplers else None), samplers[1:]


def _literal(value: Any) -> bool:
    return not (isinstance(value, list) and len(value) == 2
                and isinstance(value[0], (str, int)) and isinstance(value[1], int))


def precheck(graph: dict, declarations: dict | None, *, inspected: bool) -> dict:
    """**書き出す前の検査**（§0.8）。印の前提 3 つと、検査の結果。

    - ① **保存ノードが 1 つ**（0 個なら印を付けられない＝`前提1`）
    - ② **`filename_prefix` がリテラル**（結線なら書き換えられない＝`前提2`）
    - ③ **入力キーが宣言に含まれる**（動的コンボは展開。展開できない `COMFY_DYNAMIC*` は**対象外**にして `notes`）
    - **ComfyUI につながらないとき（`inspected=False`）は ③ を飛ばす**（**止めない**。§0.8）
    """
    nodes = save_nodes(graph)
    notes: list[str] = []
    skip: str | None = None
    if len(nodes) != 1:
        skip = "前提1"
        notes.append(f"保存ノードが {len(nodes)} 個あります（1 つだけのときに印を付けられます）")
    else:
        prefix = ((graph.get(nodes[0]) or {}).get("inputs") or {}).get("filename_prefix")
        if not _literal(prefix):
            skip = "前提2"
            notes.append("SaveImage の filename_prefix が結線です（リテラルのときに印を付けられます）")
    unresolved: list[str] = []
    if inspected and declarations is not None:
        for nid, node in sorted((graph or {}).items(),
                                key=lambda kv: (0, int(kv[0]), "") if str(kv[0]).isdigit()
                                else (1, 0, str(kv[0]))):
            if not isinstance(node, dict):
                continue
            decl = declarations.get(str(nid)) or {}
            allowed = set(decl.get("required") or ()) | set(decl.get("optional") or ())
            for key in (node.get("inputs") or {}):
                if key not in allowed:
                    unresolved.append(f"{node.get('class_type')}.{key}")
        if unresolved and skip is None:
            skip = "前提3"
        for key in unresolved:
            notes.append(f"宣言に無い入力: {key}")
    return {"save_nodes": nodes, "marker_ok": skip is None, "marker_skip_reason": skip,
            "unresolved": unresolved, "notes": notes, "inspected": bool(inspected)}


def apply_export(graph: dict, *, mode: str, text: str | None,
                 seed: str | None) -> tuple[dict, str | None, list[str], list[str]]:
    """**書き出すグラフ**を作る（§4.7 の手順 2〜3。元のグラフは触らない）。

    - `pin_text`（L1）: `CLIPTextEncode` に繋がる**テキスト生成の鎖を外して**、記録の英文を**リテラル**にする
    - `manual_text`（L3）: 同じくリテラルにするが、**利用者が貼った英文**を使う
    - `rerun_graph`（L2）: グラフはそのまま（**同じ条件で回す**）
    - **seed は最初の `KSampler` ただ 1 つ**を書き換える（§4.7.2）

    返り値: `(書き出すグラフ, seed_node, other_ksamplers, 理由の語)`。
    """
    import copy

    out = copy.deepcopy(graph or {})
    reasons: list[str] = []
    nodes = save_nodes(out)
    seed_node: str | None = None
    others: list[str] = []
    if nodes:
        seed_node, others = first_ksampler(out, nodes[0])
    if seed_node and seed is not None:
        (out[seed_node].setdefault("inputs", {}))["seed"] = int(seed)
    if mode in ("pin_text", "manual_text"):
        wanted = (text or "").strip() or None
        targets = [str(nid) for nid, node in out.items()
                   if isinstance(node, dict) and node.get("class_type") == "CLIPTextEncode"]
        pinned = False
        for nid in sorted(targets, key=lambda n: (0, int(n), "") if n.isdigit() else (1, 0, n)):
            value = (out[nid].get("inputs") or {}).get("text")
            if _literal(value):
                continue
            if wanted is None:
                # 貼る英文が無ければ**そのノードは触れない**（理由に残す。書き出しは続ける）
                reasons.append("text_not_captured")
                continue
            (out[nid].setdefault("inputs", {}))["text"] = wanted
            pinned = True
        if pinned:
            reasons.append("text_pinned")
            if mode == "manual_text":
                reasons.append("manual_step")
        # **繋がらなくなったテキスト生成の鎖**を落とす（貼った英文を使うので要らない）
        reach = set()
        for nid in save_nodes(out):
            reach |= reachable(out, nid)
        for nid in list(out):
            node = out.get(nid)
            if not isinstance(node, dict):
                continue
            if node.get("class_type") in ("TextGenerate", "StringConcatenate", "StringFunction",
                                          "PreviewAny", "ShowText|pysssss"):
                if nid not in reach:
                    out.pop(nid, None)
    if mode == "rerun_graph" and any(str(n.get("class_type")) == "TextGenerate"
                                     for n in out.values() if isinstance(n, dict)):
        reasons.append("llm_nondeterministic")
    return out, seed_node, others, reasons


def instruction_line(*, other_ksamplers: Sequence[str], marker_skipped: str | None,
                     mode: str) -> str:
    """利用者への手順 1 行（§5.3。**点検 B-6** の「1 ファイル 1 回・2 回目の前に `fixed`」）。"""
    parts = ["1 ファイルにつき Queue は 1 回。2 回目を押す前に seed を `fixed` にする。"]
    if mode == "pin_text":
        parts.append("貼った英文で回します（`TextGenerate` は外れています）。")
    elif mode == "rerun_graph":
        parts.append("グラフをそのまま回します（訳は毎回変わります）。")
    if other_ksamplers:
        parts.append(f"ほかの KSampler（{', '.join(other_ksamplers)}）の seed は揃えられません。")
    if marker_skipped:
        parts.append(f"印は付けていません（{marker_skipped}）。出力のファイル名は元のままです。")
    return " ".join(parts)


def manifest_doc(*, recipe_id: str, attempt_id: str, mode: str,
                 seed_files: Sequence[tuple[str | None, str, str | None]],
                 recipe_hash_value: str, export_hashes: dict[str, str], marker_skipped: str | None,
                 status: str, reasons: Sequence[str], inspected: bool,
                 source: dict, other_ksamplers: Sequence[str] = (),
                 output_dir: str | None = None) -> dict:
    """manifest（**契約 `schemas/recipe-manifest.schema.json` の形**。§6.1 / 専門文書 §4.7.3）。

    **契約は `additionalProperties: false`** なので、余分なキーを足すと**契約が落ちる**
    （P7-2 の実装で踏んだ: `marker` / `graphs` / `seed_node` などを上に置いて NG になった）。
    入る場所は決まっている:
    - 1 ファイル 1 件は **`seeds[]`**（`{seed, file, expected_prefix}`）
    - 判定と理由・検査の有無・手順は **`notes`**（`{status, reasons, inspected, instruction}`）
    - 印を省いた理由は **`marker_skipped`**（`'前提1'`〜`'前提3'` か `null`）
    """
    return {
        "schema": "urn:image-reviewer:schema:recipe-manifest",
        "abi": "0.1",
        "generated_at": db.now(),
        "attempt_id": attempt_id,
        "recipe_id": recipe_id,
        "mode": mode,
        "recipe_hash": recipe_hash_value,
        "export_hashes": export_hashes,
        "seeds": [{"seed": seed, "file": name, "expected_prefix": prefix or ""}
                  for seed, name, prefix in seed_files],
        "marker_skipped": marker_skipped,
        "source": source,
        "notes": {"status": status, "reasons": list(reasons), "inspected": bool(inspected),
                  "instruction": instruction_line(other_ksamplers=other_ksamplers,
                                                  marker_skipped=marker_skipped, mode=mode)},
        **({"output_dir": output_dir} if output_dir else {}),
    }


# ---- サービス ----


class RecipeExportService:
    """書き出し（P7-2）。**ファイルは `POST` のときだけ書く**（`GET` は書かない）。"""

    def __init__(self, store, recipes, *, probe_factory=None) -> None:
        self.store = store
        self.recipes = recipes
        self._probe_factory = probe_factory or (lambda settings: _probe(settings))
        #: `class_type` → (宣言, 取得時刻)。**60 秒だけ持つ**（§0.8）
        self._decl_cache: dict[str, tuple[dict | None, float]] = {}

    # ---- 検査（書かない）----

    def check(self, recipe_id: str) -> dict:
        """`POST /api/recipes/{id}/check`。**1 バイトも書かない**（§0.8 / §0.10）。"""
        record, graph = self._load(recipe_id)
        settings, _ = self._settings()
        probe = self._probe_factory(settings)
        inspected = bool(probe and probe.available())
        declarations = self._declarations(graph, probe) if inspected else None
        got = precheck(graph, declarations, inspected=inspected)
        return {"recipe_id": recipe_id, "marker_ok": got["marker_ok"],
                "marker_skip_reason": got["marker_skip_reason"],
                "save_nodes": got["save_nodes"], "unresolved": got["unresolved"],
                "notes": got["notes"], "inspected": got["inspected"],
                "status": record["status"], "reasons": [r["kind"] for r in _load(record["reasons"]) or []]}

    # ---- 書き出す ----

    def export(self, recipe_id: str, *, mode: str | None = None, seeds: Sequence[Any] | None = None,
               count: int | None = None, marker: bool = True, actor: str = "human",
               client_token: str | None = None) -> dict:
        """`POST /api/recipes/{id}/export`（§3.3）。"""
        if seeds is not None and count is not None:
            raise ReviewError(422, "seeds か count のどちらかです", details={"seeds": "seeds か count のどちらかです"})
        if seeds is not None and len(list(seeds)) > MAX_SEEDS:
            raise ReviewError(422, f"seeds は {MAX_SEEDS} 件までです",
                              details={"seeds": f"{MAX_SEEDS} 件まで"})
        if count is not None and not (1 <= int(count) <= MAX_SEEDS):
            raise ReviewError(422, f"count は 1〜{MAX_SEEDS} です", details={"count": f"1〜{MAX_SEEDS}"})
        record, graph = self._load(recipe_id)
        mode = mode or record["mode"] or DEFAULT_MODE
        if mode not in MODES:
            raise ReviewError(422, "mode は pin_text | rerun_graph | manual_text です",
                              details={"mode": "pin_text | rerun_graph | manual_text"})
        if not marker:
            # **自分で決めた点**: `marker=false` は 422。`marker_skip_reason` の語彙は
            # **前提 1〜3 だけ**（DDL の `CHECK`）で、「人が印を省いた」状態を表す語が無い。
            # 印を省く道は**前提が外れたとき**だけにする（表の `CHECK` とも食い違わない）。
            raise ReviewError(422, "印を省く指定はできません（前提が外れたときだけ省きます）",
                              details={"marker": "true だけ"})
        if record["status"] == "impossible":
            raise ReviewError(409, "この記録は再現できません（書き出しません）",
                              code="recipe_impossible",
                              details={"reasons": [r["kind"] for r in _load(record["reasons"]) or []]})
        # --- ① 読む（錠だけ）---
        with self.store.locked() as con:
            replay = self._replay(con, client_token, {"recipe_id": recipe_id, "mode": mode})
            if replay is not None:
                return replay
            doc = _load(record["record_json"]) or {}
            seed0 = doc.get("seed")
        # --- ② 外（ComfyUI に聞き、ファイルを書く。**錠の外**）---
        settings, _ = self._settings()
        probe = self._probe_factory(settings)
        inspected = bool(probe and probe.available())
        declarations = self._declarations(graph, probe) if inspected else None
        checked = precheck(graph, declarations, inspected=inspected)
        nodes = checked["save_nodes"]
        seed_node, others = (first_ksampler(graph, nodes[0]) if nodes else (None, []))
        seed_list: list[str | None]
        if seed_node is None:
            if seeds is not None or count is not None:
                raise ReviewError(422, "KSampler が無いグラフに seed は指定できません",
                                  code="no_sampler", details={"seeds": "KSampler がありません"})
            seed_list = [None]
        else:
            if seeds is not None:
                seed_list = [str(int(str(s))) for s in seeds]
            else:
                base = seed0 if seed0 is not None else 0
                seed_list = seeds_for(base, int(count or DEFAULT_COUNT))
        attempt_id = new_attempt_id()
        skip = None
        if not checked["marker_ok"]:
            skip = checked["marker_skip_reason"]
        out_dir = attempt_dir(self.store.data_dir, recipe_id, attempt_id)
        out_dir.mkdir(parents=True, exist_ok=True)
        files: list[str] = []
        export_hashes: dict[str, str] = {}
        marker_value: str | None = None
        reasons: list[str] = []
        per_seed: list[tuple[str | None, str | None, str]] = []      # (seed, 印, グラフのパス)
        seed_files: list[tuple[str | None, str, str | None]] = []    # (seed, ファイル名, 期待の前置き)
        for seed in seed_list:
            exported, _sn, _others, why = apply_export(graph, mode=mode, text=doc.get("final_prompt"),
                                                        seed=seed)
            mark = None
            if skip is None:
                mark = marker_for(attempt_id, seed)
                for nid in save_nodes(exported):
                    if (exported[nid].get("class_type") == "SaveImage"
                            and _literal((exported[nid].get("inputs") or {}).get("filename_prefix"))):
                        (exported[nid].setdefault("inputs", {}))["filename_prefix"] = mark
                marker_value = marker_value or mark
            digest = recipe_hash(exported)
            export_hashes["noseed" if seed is None else str(seed)] = digest
            name = graph_out_name(seed)
            path = _atomic_write(out_dir / name, exported)
            files.append(name)
            # `seeds[].expected_prefix` は**そのファイルの保存ノードに入れた字**（印を省いたときは元の字）
            prefix = mark or _literal_prefix(exported)
            per_seed.append((seed, mark, str(path)))
            seed_files.append((seed, name, prefix))
            for reason in why:
                if reason not in reasons:
                    reasons.append(reason)
        expected_prefix = (f"{marker_value}" if marker_value
                           else f"（印なし: {skip}）")
        manifest = manifest_doc(
            recipe_id=recipe_id, attempt_id=attempt_id, mode=mode, seed_files=seed_files,
            recipe_hash_value=record["recipe_hash"], export_hashes=export_hashes,
            marker_skipped=skip, status=record["status"], reasons=reasons, inspected=inspected,
            source=self._source_of(record, doc), other_ksamplers=others,
            output_dir=settings.get("output_dir"))
        _atomic_write(out_dir / "manifest.json", manifest)
        files.append("manifest.json")
        # --- ③ 短い 1 取引で書く ---
        try:
            with self.store.transaction() as con:
                con.execute(
                    "INSERT INTO recipe_export_attempt(attempt_id, recipe_id, mode, client_token,"
                    " marker_skip_reason, checked_json, manifest_path, export_dir, seed_node,"
                    " created_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (attempt_id, recipe_id, mode, client_token, skip,
                     _dump({**checked, "reasons": reasons}),
                     str(out_dir / "manifest.json"), str(out_dir), seed_node, db.now()))
                for seed, mark, path in per_seed:
                    con.execute(
                        "INSERT INTO recipe_export(id, attempt_id, seed, recipe_hash, graph_path,"
                        " marker, marker_skip_reason, created_at) VALUES (?,?,?,?,?,?,?,?)",
                        (db.ulid(), attempt_id, seed,
                         export_hashes["noseed" if seed is None else str(seed)],
                         path, mark, None if mark is not None else skip, db.now()))
        except sqlite3.IntegrityError:
            # **同じ `client_token` で同時に来た**（P7-1 の監査 A-3 と同じ型: 錠の外で ComfyUI を
            # 待ってから書くので、窓の間に入った 2 本目が部分 UNIQUE に当たる）。**500 にせず**、
            # 先に入った束を返す（ファイルは `attempt_id` ごとに別のフォルダなので実害は無い）
            with self.store.locked() as con:
                again = self._replay(con, client_token, {"recipe_id": recipe_id, "mode": mode})
            if again is not None:
                return again
            raise
        return {"attempt_id": attempt_id, "recipe_id": recipe_id, "export_dir": str(out_dir),
                "files": files, "marker": marker_value, "marker_skipped": skip,
                "status": record["status"], "reasons": reasons, "seed_node": seed_node,
                "other_ksamplers": others, "mode": mode, "inspected": inspected,
                "notes": checked["notes"], "replayed": False}

    def exports(self, recipe_id: str) -> dict:
        """`GET /api/recipes/{id}/exports`。**書かない**。"""
        with self.store.locked() as con:
            if con.execute("SELECT 1 FROM recipe_record WHERE id = ?", (recipe_id,)).fetchone() is None:
                raise ReviewError(404, "記録がありません", details={"recipe_id": recipe_id})
            rows = con.execute(
                "SELECT * FROM recipe_export_attempt WHERE recipe_id = ?"
                " ORDER BY created_at DESC, attempt_id DESC", (recipe_id,)).fetchall()
            items = []
            for row in rows:
                files = con.execute(
                    "SELECT seed, recipe_hash, graph_path, marker FROM recipe_export"
                    " WHERE attempt_id = ? ORDER BY COALESCE(seed, '')", (row["attempt_id"],)).fetchall()
                # P7-3: 結果と合否（人が付けた物。**書かない**）
                results = con.execute(
                    "SELECT r.*, e.seed FROM recipe_export_result r"
                    " JOIN recipe_export e ON e.id = r.export_id"
                    " WHERE e.attempt_id = ? ORDER BY r.created_at DESC, r.id DESC",
                    (row["attempt_id"],)).fetchall()
                items.append({
                    "attempt_id": row["attempt_id"], "mode": row["mode"],
                    "marker_skip_reason": row["marker_skip_reason"],
                    "export_dir": row["export_dir"], "manifest_path": row["manifest_path"],
                    "seed_node": row["seed_node"], "created_at": row["created_at"],
                    "checked": _load(row["checked_json"]),
                    "files": [dict(f) for f in files],
                    "results": [_result_doc(r) for r in results],
                })
        return {"recipe_id": recipe_id, "items": items}

    # ---- 道具 ----

    def _source_of(self, record, doc: dict) -> dict:
        """`manifest.source`（契約が `additionalProperties: false` なので**この 6 列だけ**）。

        `{asset_id, sha256, filename, model, seed, size}`。**パスは出さない**（ファイル名だけ。
        `include_paths` と同じ方針）。
        """
        asset_id = record["source_asset_id"]
        with self.store.locked() as con:
            asset = con.execute("SELECT sha256 FROM asset WHERE id = ?", (asset_id,)).fetchone()
            loc = con.execute("SELECT path FROM asset_location WHERE asset_id = ?"
                              " ORDER BY is_primary DESC, path LIMIT 1", (asset_id,)).fetchone()
        width, height = doc.get("width"), doc.get("height")
        long_side = max(int(width or 0), int(height or 0)) or None
        seed = doc.get("seed")
        return {"asset_id": asset_id,
                "sha256": (asset["sha256"] if asset else "") or "",
                "filename": (Path(loc["path"]).name if loc and loc["path"] else ""),
                "model": doc.get("model"),
                "seed": None if seed is None else str(seed),
                "size": long_side}

    def _load(self, recipe_id: str) -> tuple[Any, dict]:
        """記録とグラフを読む（グラフのファイルが無ければ**PNG から作り直して書く**。§0.4）。"""
        with self.store.locked() as con:
            row = con.execute("SELECT * FROM recipe_record WHERE id = ?", (recipe_id,)).fetchone()
            if row is None:
                raise ReviewError(404, "記録がありません", details={"recipe_id": recipe_id})
            paths = [r["path"] for r in con.execute(
                "SELECT path FROM asset_location WHERE asset_id = ?"
                " ORDER BY is_primary DESC, path", (row["source_asset_id"],))]
        graph: dict = {}
        if row["graph_path"]:
            path = Path(row["graph_path"])
            if path.exists():
                try:
                    graph = json.loads(path.read_text(encoding="utf-8"))
                except (TypeError, ValueError, OSError):
                    graph = {}
        if not graph:
            prov = _provenance_of(paths)
            graph = prov.get("graph") or {}
            if graph:
                from .recipe import save_graph
                save_graph(self.store.data_dir, graph, row["recipe_hash"])
        return row, graph

    def _settings(self) -> tuple[dict, None]:
        with self.store.locked() as con:
            return _settings(con), None

    def _declarations(self, graph: dict, probe) -> dict:
        """使った `class_type` の宣言だけを引く（**60 秒キャッシュ**。§0.8 / 点検 B-2）。"""
        out: dict[str, dict] = {}
        if probe is None:
            return out
        needed = sorted({str(node.get("class_type")) for node in (graph or {}).values()
                         if isinstance(node, dict) and node.get("class_type")})
        now = time.monotonic()
        for class_type in needed:
            hit = self._decl_cache.get(class_type)
            if hit and now - hit[1] < DECL_TTL_SECONDS:
                # **正規化した形をキャッシュに入れる**（生の `/object_info` の応答を入れると、
                # 2 回目の呼び出しで `required` が無くて落ちる。テストで踏んだ）
                if hit[0] is not None:
                    out[class_type] = hit[0]
                continue
            got = probe.object_info(class_type)
            if got is None:
                self._decl_cache[class_type] = (None, now)
                continue
            entry = got.get(class_type) if isinstance(got, dict) and class_type in got else got
            spec = (entry or {}).get("input") or {}
            normalized = {"required": spec.get("required") or {},
                          "optional": spec.get("optional") or {}}
            self._decl_cache[class_type] = (normalized, now)
            out[class_type] = normalized
        # ノードごとに「宣言のキー」を組み立てる（動的コンボの入れ子を展開。§0.8 ③ / 点検 A-1）
        by_node: dict[str, dict] = {}
        for nid, node in (graph or {}).items():
            if not isinstance(node, dict):
                continue
            class_type = str(node.get("class_type"))
            decl = out.get(class_type)
            if decl is None:
                continue
            allowed = set(decl["required"]) | set(decl["optional"])
            for key, spec in (decl["required"] or {}).items():
                value = (node.get("inputs") or {}).get(key)
                subs = _dynamic_subkeys(spec, value)
                if subs:
                    allowed |= {f"{key}.{sub}" for sub in subs}
            by_node[str(nid)] = {"required": sorted(allowed), "optional": []}
        return by_node

    @staticmethod
    def _replay(con, client_token: str | None, payload: dict) -> dict | None:
        """同じ `client_token` の再送（§0.10）。**同じ `attempt_id` を返す**。中身が違えば 409。"""
        if not client_token:
            return None
        row = con.execute("SELECT * FROM recipe_export_attempt WHERE client_token = ?",
                          (client_token,)).fetchone()
        if row is None:
            return None
        stored = {"recipe_id": row["recipe_id"], "mode": row["mode"]}
        if _dump(stored) != _dump(payload):
            raise ReviewError(409, "同じ client_token で違う内容が来ました",
                              code="client_token_conflict", details={"client_token": client_token})
        files = con.execute("SELECT seed, recipe_hash, graph_path, marker FROM recipe_export"
                            " WHERE attempt_id = ? ORDER BY COALESCE(seed, '')",
                            (row["attempt_id"],)).fetchall()
        return {"attempt_id": row["attempt_id"], "recipe_id": row["recipe_id"],
                "export_dir": row["export_dir"], "mode": row["mode"],
                "marker_skipped": row["marker_skip_reason"],
                "marker": next((f["marker"] for f in files if f["marker"]), None),
                "files": [Path(f["graph_path"]).name for f in files] + ["manifest.json"],
                "seed_node": row["seed_node"], "replayed": True}


def _literal_prefix(graph: dict) -> str | None:
    """保存ノードの `filename_prefix`（リテラルならその字。印を省いたときに manifest へ入れる）。"""
    for nid in save_nodes(graph):
        value = ((graph.get(nid) or {}).get("inputs") or {}).get("filename_prefix")
        if _literal(value) and value is not None:
            return str(value)
    return None


def _dynamic_subkeys(spec: Any, selected: Any) -> list[str]:
    """動的コンボ（`COMFY_DYNAMICCOMBO_V3`）の**入れ子のキー**を返す（§0.8 / 点検 A-1）。

    `spec` が `["COMFY_DYNAMICCOMBO_V3", {"options": [{"key": "on", "inputs": {"required": {...}}}, …]}]`
    の形のとき、`selected`（例 `"on"`）に対応する `options` の入れ子のキーを返す。
    **展開できない `COMFY_DYNAMIC*` は空を返す**（＝検査の対象外。呼ぶ側が `notes` に出す）。
    """
    if not (isinstance(spec, list) and len(spec) == 2 and isinstance(spec[0], str)
            and spec[0].startswith("COMFY_DYNAMIC")):
        return []
    meta = spec[1] if isinstance(spec[1], dict) else {}
    options = meta.get("options")
    if not isinstance(options, list):
        return []
    picked = None
    for option in options:
        if isinstance(option, dict) and str(option.get("key")) == str(selected):
            picked = option
            break
    if picked is None:
        return []
    inputs = picked.get("inputs") or {}
    keys = set((inputs.get("required") or {}))
    keys |= set((inputs.get("optional") or {}))
    return sorted(keys)


def _settings(con) -> dict:
    """`settings` から要る物（`comfyui.url` と `comfyui.output_dir`。§0.9 の G-1）。"""
    got: dict[str, str] = {}
    try:
        for row in con.execute("SELECT key, value FROM settings WHERE key IN"
                               " ('comfyui.url', 'comfyui.output_dir', 'tagger.comfyui')"):
            got[row["key"]] = row["value"]
    except Exception:                                  # noqa: BLE001 表が無い環境でも既定で動く
        pass
    return {"url": (got.get("comfyui.url") or got.get("tagger.comfyui")
                    or "http://127.0.0.1:8188").rstrip("/"),
            "output_dir": got.get("comfyui.output_dir") or None}


def _probe(settings: dict):
    """既定の probe（**本物の ComfyUI**。テストは差し替える）。"""
    from .recipe import ComfyProbe
    return ComfyProbe(settings["url"])

def _result_doc(row) -> dict:
    """`recipe_export_result` の 1 行（`manifest` ではなく画面向け。§3.6）。"""
    return {"id": row["id"], "attempt_id": row["attempt_id"], "seed": row["seed"],
            "prompt_id": row["prompt_id"], "result_asset_id": row["result_asset_id"],
            "matched_by": row["matched_by"], "result_hash": row["result_hash"],
            "same_hash": bool(row["same_hash"]), "ssim": row["ssim"],
            "phash_distance": row["phash_distance"], "changed_fraction": row["changed_fraction"],
            "mean_abs": row["mean_abs"], "seed_changed": bool(row["seed_changed"]),
            "verdict": row["verdict"], "verdict_at": row["verdict_at"],
            "verdict_actor": row["verdict_actor"], "note": row["note"]}
