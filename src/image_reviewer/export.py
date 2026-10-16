"""`review.json` の組み立てと書き出し（P5-1）。

設計: docs/p5-design.md §0.3（B1・B2・B3・G11）・§0.5（D5・G8）・§3.4・§4、docs/design.md §6.2
契約: `schemas/review-export.schema.json`（**形はここが正**）

守ること（どれも点検の指摘が理由）:
- **「書き出し済み」をファイルの mtime で判定しない**（点検 B1）。`review_group` の
  `exported_at IS NULL OR changed_at > exported_at` だけを見る。`exported_at` には
  **書き出しの開始時に読んだ `changed_at`** を入れるので、開始後に入った変更は次回に残る
- 判断のたびに書くのは **`export/groups/<group_id>.json` だけ**（点検 B4）。対象は
  「その判断で判断行を書いた全画像の `group_item` を引いた `group_id` の和集合」（点検 B2）
- **`open` なまとまりも書く**（点検 B3。`decision` は null、未判断の枚の `verdict` も null）
- `assets[].kind` は**必ず**出す（点検 A1）。`path_map` は**出さない**（点検 C14。`locations` に一本化）
- `scope` は**どの口でも出す**。`scope=asset:{id}`（点検 G11）は**読み取り専用**で
  ファイルを書かないが、契約の `scope.kind` に `asset` を足したので範囲を省かずに書ける
- `reason_label` は**書き出し時点のマスタ**を引く（点検 G8）
- `tags` / `prompts` は `include_tags` / `include_prompts` が真のときだけ**鍵ごと**出す（点検 D5）
- 遅延は `threading.Timer`。**ID だけを持ち、書くときに DB を読み直す**（点検 D10）
- 起動時に**溜まっている分を書き出す**（COMMIT 直後に落ちても、次回の起動で追い付く。§4）。
  拾うのは**DB の印**（`exported_at IS NULL OR changed_at > exported_at`）だけで、
  メモリの `_pending` は当てにしない（**監査 A1**。1 枚の判断が落ちても拾えるようにする）
- **1 つのまとまりの失敗で残りを落とさない**（**監査 B2**）。失敗した ID は `_pending` に
  戻して次のタイマーで再試行し、理由を `log.warning` に出す
- **読み出しは `store.locked()` の下で行う**（**監査 B3**）。出口は `threading.Timer` の
  スレッド、判断は FastAPI のスレッドプールで、同じ 1 本の `sqlite3` 接続を共有している。
  錠を取らないと、判断の取引が**まだコミットしていない行**を読んでしまい、
  その取引が `ROLLBACK` されると「誰も付けていない判断」が契約ファイルに残る
- `generated_at` を除いて 2 回出して同一（§3.4 の決定性）
"""

from __future__ import annotations

import json
import logging
import os
import re
import threading
from pathlib import Path

from . import db, reasons, review_requests
from .review import ReviewError, affected_group_ids
from .store import Store

log = logging.getLogger(__name__)

SCHEMA_URN = "urn:image-reviewer:schema:review-export"
ABI = "0.1"
GENERATOR = {"name": "image-reviewer", "version": "0.1.0"}

# DB の `review_group.kind` は 'duplicates'、契約の enum は 'duplicate'（綴りが違う）。
# 契約は変えられないので、書き出すときに寄せる
KIND_FOR_CONTRACT = {"duplicates": "duplicate", "duplicate": "duplicate"}

_TS = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?Z$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_DIGITS = re.compile(r"^[0-9]+$")
_SAFE = re.compile(r"[^A-Za-z0-9._-]")

JA_SOURCES = ("png_primitive", "workflow_node", "sidecar", "manual")
EN_SOURCES = ("png_literal", "comfyui_history", "sidecar", "textgenerate", "ollama", "manual")


def parse_scope(scope: str | None) -> tuple[str, str | None]:
    """`all` / `group:<id>` / `asset:<id>` を分ける（`folder:` / `request:` は P2 / P6）。"""
    text = (scope or "all").strip()
    if text in ("", "all"):
        return "all", None
    kind, _, target = text.partition(":")
    if kind in ("group", "asset") and target:
        return kind, target
    raise ReviewError(422, f"scope が不正です: {scope!r}（all / group:<id> / asset:<id>）")


def _safe_name(name: str) -> str:
    return _SAFE.sub("_", name)


def _as_timestamp(value) -> str | None:
    return value if isinstance(value, str) and _TS.match(value) else None


def _as_hex64(value) -> str | None:
    return value if isinstance(value, str) and _HEX64.match(value) else None


def _as_seed(value) -> str | None:
    """seed は**10 進の文字列**。64bit は JSON の数値で丸められる（契約の description）。"""
    if value is None or isinstance(value, bool):
        return None
    text = str(value)
    return text if _DIGITS.match(text) else None


def _as_int(value) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, str):
        try:
            return int(value.strip())
        except ValueError:
            return None
    return None


def _as_num(value) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip())
        except ValueError:
            return None
    return None


def _as_enum(value, allowed) -> str | None:
    return value if value in allowed else None


def _referenced_reason_ids(doc: dict) -> set[str]:
    """組み立てた文書が**実際に参照している**理由の id を集める（監査 C1）。

    `reason_codes[]` をこの集合に絞ることで、改名したときに「参照していないまとまりの
    ファイル」だけが旧名を持ち続ける状態を無くす（全マスタを載せると、ファイルごとに
    同じ id の名前が食い違う）。鍵の名前で拾うので、契約に欄が増えても追随する。
    """
    found: set[str] = set()
    stack: list = [doc]
    while stack:
        node = stack.pop()
        if isinstance(node, dict):
            for key, value in node.items():
                if key.endswith("reason_code_id") and isinstance(value, str) and value:
                    found.add(value)
                elif isinstance(value, (dict, list)):
                    stack.append(value)
        elif isinstance(node, list):
            stack.extend(node)
    return found


def _atomic_write(path: Path, doc: dict) -> Path:
    """一時ファイルへ書いてから `os.replace`。**半端なファイルを読ませない**。

    監査 C1（実行込みのやり直し）: `os.replace` が落ちたとき（Windows では他の道具が
    ファイルを開いていると `PermissionError` になる）**一時ファイルを残さない**。
    残すと、2 秒ごとの再試行のたびに別名（`<id>.json.<pid>.<tid>.tmp`）で増え続ける
    （実測: 9.5 秒のロックで 4 個）。
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    tmp.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    try:
        os.replace(tmp, path)
    except OSError:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:            # 消せなくても、元の失敗を伝える方を優先する
            log.warning("書き出しに失敗し、一時ファイルも消せませんでした: %s", tmp)
        raise
    return path


class ExportService:
    """契約文書の組み立てと、影響したまとまりだけの書き出し。

    `ExportService(store)` は**起動時に溜まっている分を書き出す**（`flush_on_start=False` で切れる）。
    """

    def __init__(self, store: Store, *, delay: float = 2.0, flush_on_start: bool = True):
        self.store = store
        self.data_dir = Path(store.data_dir)
        self.delay = delay
        self._lock = threading.RLock()
        self._pending: set[str] = set()
        self._timer: threading.Timer | None = None
        if flush_on_start:
            self.flush_dirty()

    # ---- 場所 ----

    def all_path(self) -> Path:
        return self.data_dir / "export" / "review.json"

    def group_path(self, group_id: str) -> Path:
        return self.data_dir / "export" / "groups" / f"{_safe_name(group_id)}.json"

    # ---- 遅延（点検 D10）----

    def mark(self, *, asset_ids=(), group_ids=(), delay: float | None = None) -> list[str]:
        """書き出すべきまとまりの ID を積む。**中身は持たない**（実行時に読み直す）。"""
        # 監査 B3: 「影響したまとまり」の引き方も錠の下で行う（未コミットの行を見ない）
        with self.store.locked() as con:
            ids = affected_group_ids(con, list(asset_ids), list(group_ids))
        if not ids:
            return []
        with self._lock:
            self._pending.update(ids)
            self._arm_timer(delay)
        return ids

    def _arm_timer(self, delay: float | None = None) -> None:
        """遅延タイマーを張る（既に張ってあれば何もしない）。**呼ぶ側が `self._lock` を握る**。"""
        if self._timer is not None:
            return
        timer = threading.Timer(self.delay if delay is None else delay, self._on_timer)
        # 落ちる時に遅延タイマーで待たせない
        timer.daemon = True
        self._timer = timer
        timer.start()

    def flush(self, ids=None) -> list[str]:
        """積んである（または渡された）まとまりを書く。**実行時に DB を読み直す**。

        監査 B2: 1 つのまとまりで失敗しても（Windows では `os.replace` が
        `PermissionError` になることがある）**残りは書く**。失敗した ID は `_pending` に
        戻し、理由を `log.warning` に出して次のタイマーで再試行する。
        """
        with self._lock:
            targets = sorted(set(self._pending if ids is None else ids))
            self._pending.clear()
        written: list[str] = []
        for group_id in targets:
            try:
                if self.write_group(group_id) is not None:
                    written.append(group_id)
            except Exception as exc:  # noqa: BLE001  1 つの失敗で残りを落とさない（監査 B2）
                log.warning("まとまり %s の書き出しに失敗しました（次で再試行します）: %s",
                            group_id, exc)
                with self._lock:
                    self._pending.add(group_id)
        with self._lock:
            if self._pending:
                self._arm_timer()               # 失敗分を次のタイマーで書き直す（監査 B2）
        return written

    def pending_ids(self) -> list[str]:
        """まだ書けていない（再試行待ちの）まとまり（監査 B2）。"""
        with self._lock:
            return sorted(self._pending)

    def flush_dirty(self) -> list[str]:
        """点検 B1 の判定（`exported_at IS NULL OR changed_at > exported_at`）で全部書く。

        **DB の印だけを見る**（監査 A1）。メモリの `_pending` は落ちると消えるので当てにしない。

        監査 C1: 書く前に、**過去に失敗して残った一時ファイル**を片づける（起動時に 1 回）。
        """
        self.clean_stale_tmp()
        with self.store.locked() as con:          # 監査 B3
            rows = con.execute(
                "SELECT id FROM review_group"
                " WHERE exported_at IS NULL OR changed_at > exported_at ORDER BY id").fetchall()
        return self.flush([r["id"] for r in rows])

    def clean_stale_tmp(self) -> int:
        """`export/groups/*.tmp` に残った一時ファイルを消す（監査 C1）。

        消すのは**書き出しの途中で落ちた/失敗した**一時ファイルだけ（名前は
        `<id>.json.<pid>.<tid>.tmp`。本体は `<id>.json`）。本体には触らない。
        書いている最中の別プロセスの一時ファイルを消すと、その書き出しは
        `os.replace` で失敗して再試行に回る（消えるだけで、内容は失われない）。
        """
        directory = self.group_path("x").parent
        if not directory.is_dir():
            return 0
        removed = 0
        for path in sorted(directory.glob("*.tmp")):
            try:
                path.unlink()
                removed += 1
            except OSError as exc:  # noqa: BLE001  消せなくても起動は続ける
                log.warning("残った一時ファイルを消せませんでした: %s (%s)", path, exc)
        if removed:
            log.info("残っていた書き出しの一時ファイルを %d 個消しました", removed)
        return removed

    def close(self) -> None:
        """タイマーを止める。**書き出しはしない**（落ちたときと同じ扱い。起動時に拾う）。"""
        with self._lock:
            if self._timer is not None:
                self._timer.cancel()
                self._timer = None
            self._pending.clear()

    def _on_timer(self) -> None:
        with self._lock:
            self._timer = None
        try:
            self.flush()
        except Exception:                        # noqa: BLE001 点検 D11（uvicorn のログに残す）
            log.exception("遅延した書き出しで想定外の失敗")

    # ---- 書き出し ----

    def write_group(self, group_id: str, **options) -> Path | None:
        """1 つのまとまりのファイルを書く。無ければ何もしない（`None`）。

        点検 B1 のとおり、**開始時に読んだ** `changed_at` を `exported_at` に入れる
        （書き出しの最中に入った変更は `changed_at > exported_at` のまま残る）。
        **この口は取引の中から呼ばれない**（`ReviewService._notify` は取引の外。設計 §4）。
        """
        with self._lock:
            with self.store.locked() as con:      # 監査 B3
                row = con.execute(
                    "SELECT changed_at FROM review_group WHERE id = ?", (group_id,)).fetchone()
            if row is None:
                return None
            started_at = row["changed_at"]
            doc = self.build(f"group:{group_id}", **options)
            path = _atomic_write(self.group_path(group_id), doc)
            with self.store.transaction() as con:
                con.execute("UPDATE review_group SET exported_at = ? WHERE id = ?",
                            (started_at, group_id))
            return path

    def write_all(self, *, doc: dict | None = None, **options) -> Path:
        """全件（手動と日次の口。§3.4）。まとまりの印は**触らない**（個別ファイルが古くならないように）。"""
        return _atomic_write(self.all_path(), doc if doc is not None else self.build("all", **options))

    # ---- 組み立て ----

    def build(self, scope: str = "all", *, include_paths: bool = False,
              include_tags: bool = False, include_prompts: bool = False,
              include_superseded: bool = False) -> dict:
        """契約文書。**同じ状態なら `generated_at` を除いて同一**（辞書の順も固定）。

        **監査 B3**: 読み出しは `store.locked()`（取引を開かない錠）の下で行う。
        判断の取引が `COMMIT` する前の行を読むと、`ROLLBACK` された判断が契約に残る。
        ここは**取引の中から呼ばれない**（`write_group` は `build` の後に取引を開く）。

        **`include_superseded`**（P6 の点検 A3）: 要求の差し替えで閉じたまとまり
        （`review_group.superseded_by` が入っている行）を `scope=all` の `groups[]` に
        出すかどうか。既定は出さない（`GET /api/groups?include_superseded=1` と揃える）。
        `scope=group:<id>` の**名指し**では、印が入っていても返す（読むために指定している）。
        """
        kind, target = parse_scope(scope)
        with self.store.locked():
            return self._build_locked(kind, target, include_paths, include_tags,
                                      include_prompts, include_superseded)

    def _build_locked(self, kind: str, target: str | None, include_paths: bool,
                      include_tags: bool, include_prompts: bool,
                      include_superseded: bool = False) -> dict:
        """`build()` の本体。**呼ぶ側が `store.locked()` を握っている**（監査 B3）。"""
        con = self.store.con
        groups: list = []
        assets: list = []
        if kind == "all":
            groups = con.execute("SELECT * FROM review_group ORDER BY id").fetchall()
            if not include_superseded:      # 点検 A3: 差し替えで閉じたまとまりは既定で出さない
                groups = [g for g in groups if not g["superseded_by"]]
            assets = con.execute("SELECT * FROM asset ORDER BY id").fetchall()
        elif kind == "group":
            groups = con.execute("SELECT * FROM review_group WHERE id = ?", (target,)).fetchall()
            if not groups:
                raise ReviewError(404, "まとまりがありません", details={"group_id": target})
            assets = con.execute(
                "SELECT * FROM asset WHERE id IN (SELECT asset_id FROM group_item WHERE group_id = ?)"
                " ORDER BY id", (target,)).fetchall()
        else:
            assets = con.execute("SELECT * FROM asset WHERE id = ?", (target,)).fetchall()
            if not assets:
                raise ReviewError(404, "asset がありません", details={"asset_id": target})
            groups = con.execute(
                "SELECT * FROM review_group WHERE id IN"
                " (SELECT group_id FROM group_item WHERE asset_id = ?) ORDER BY id",
                (target,)).fetchall()

        reason_rows = reasons.list_all(con, include_inactive=True)
        labels = {r["id"]: r["label"] for r in reason_rows}
        group_ids_of: dict[str, list[str]] = {}
        for row in con.execute("SELECT group_id, asset_id FROM group_item"):
            group_ids_of.setdefault(row["asset_id"], []).append(row["group_id"])

        doc = {
            "schema": SCHEMA_URN,
            "abi": ABI,
            "generated_at": db.now(),
            "generator": dict(GENERATOR),
            "reason_codes": [{"id": r["id"], "label": r["label"], "applies_to": r["applies_to"]}
                             for r in reason_rows],
            "groups": [self._group_doc(g, labels) for g in groups],
            "assets": [self._asset_doc(a, labels, sorted(group_ids_of.get(a["id"], [])),
                                       include_paths, include_tags, include_prompts)
                       for a in assets],
            # P6（§6.1）: 要求を **`scope` に応じて**入れる（`all` は `superseded` も含む履歴）。
            # 並びは `created_at DESC, id DESC` に固定（`generated_at` を除いて同一にするため）
            "requests": review_requests.request_docs(con, kind, target),
        }
        # 監査 C1: `reason_codes` は**この文書が実際に参照している理由だけ**にする。
        # 全マスタを載せると、改名したときに「参照していないまとまりのファイル」だけが
        # 旧名を持ち続け、どのファイルを読んだかで同じ id の名前が食い違う
        # （改名が印を付けるのは参照しているまとまりだけ。§0.3 の C9）。
        referenced = _referenced_reason_ids(doc)
        doc["reason_codes"] = [r for r in doc["reason_codes"] if r["id"] in referenced]
        # `scope=asset:{id}`（点検 G11）も**範囲として出す**。契約の `scope.kind` に `asset` を
        # 足した（この口は**読み取り専用**で、ファイルは書かない）。
        # 以前は契約に語が無いので鍵ごと省いていた（嘘の範囲を書かないため）。契約を直したので省かない
        doc["scope"] = {"kind": kind, "id": target}
        return doc

    def _group_doc(self, group, labels: dict) -> dict:
        con = self.store.con
        items = []
        for row in con.execute(
                "SELECT asset_id, position FROM group_item WHERE group_id = ?"
                " ORDER BY position, asset_id", (group["id"],)):
            state = self._latest_asset_state(row["asset_id"])
            items.append({
                "asset_id": row["asset_id"],
                # **open で未判断なら null**（点検 B3）
                "verdict": (state or {}).get("verdict"),
                "group_decision": self._slot(row["asset_id"], group["id"]),
                "reason_code_id": (state or {}).get("reason_code_id"),
                "reason_label": labels.get((state or {}).get("reason_code_id") or ""),
                "note": (state or {}).get("note"),
            })
        decided = group["state"] == "decided"
        selected = [i["asset_id"] for i in items if i["group_decision"] == "selected"]
        return {
            "id": group["id"],
            "title": group["title"],
            "kind": KIND_FOR_CONTRACT.get(group["kind"], group["kind"]),
            "source": group["source"],
            "source_ref": group["source_ref"],
            "policy": group["policy"],
            "state": group["state"],
            # **open なら結論は無い**（点検 B3）
            "decision": group["decision"] if decided else None,
            "selected_asset_ids": selected if decided else [],
            "reason_code_id": group["reason_code_id"],
            "reason_label": labels.get(group["reason_code_id"] or ""),
            "note": group["note"],
            "created_at": _as_timestamp(group["created_at"]) or db.now(),
            "decided_at": _as_timestamp(group["decided_at"]),
            "decided_by": group["decided_by"],
            # P6（点検 A3）: 差し替えで閉じたまとまりの印（既定では `groups[]` に出さない）
            "superseded_by": group["superseded_by"],
            "items": items,
        }

    def _asset_doc(self, asset, labels: dict, group_ids: list[str], include_paths: bool,
                   include_tags: bool, include_prompts: bool) -> dict:
        state = self._latest_asset_state(asset["id"]) or {}
        meta = self._meta(asset["id"])
        locations = [dict(r) for r in self.store.con.execute(
            "SELECT display_path, is_primary, missing_at FROM asset_location"
            " WHERE asset_id = ? ORDER BY is_primary DESC, display_path", (asset["id"],))]
        doc = {
            "id": asset["id"],
            # **必ず出す**（点検 A1）。契約では required ではないので、落としても検証が通ってしまう
            "kind": asset["kind"],
            "review_state": asset["review_state"],
            "verdict": state.get("verdict"),
            "reason_code_id": asset["review_reason_code_id"],
            # **書き出し時点の** label（点検 G8。改名すると以後の書き出しでは変わる）
            "reason_label": labels.get(asset["review_reason_code_id"] or ""),
            "note": state.get("note"),
            "decided_at": _as_timestamp(asset["reviewed_at"]),
            "decided_by": _as_enum(asset["reviewed_by"], ("human", "agent")),
            "group_ids": group_ids,
            "sha256": _as_hex64(asset["sha256"]),
            "missing": all(l["missing_at"] for l in locations) if locations else True,
            "duplicate_of": None,
            "reproduction": None,
            "external_ref": self._external_ref(asset, meta, locations),
            "provenance": self._provenance(asset, meta),
            # 点検 C14: パスは `locations[]` に一本化する（`path_map` は出さない）
            "locations": ([{"path": l["display_path"], "kind": "reference",
                            "primary": bool(l["is_primary"]),
                            "missing": bool(l["missing_at"])} for l in locations]
                          if include_paths else None),
        }
        if include_tags:
            # P4-0: 仮置きの空配列をやめ、`asset_tag` → `tag` → `tag_gloss` から**契約の形**で組む。
            # **出所ごとに 1 行**（同じ語が PNG と タガーの両方にあれば 2 行。設計 §1.1）。
            # 並びは決定的（`name` → `source`。§6.1）
            doc["tags"] = self._tag_docs(asset["id"])
        if include_prompts:
            doc["prompts"] = {
                "ja_text": meta.get("ja_text"),
                "ja_source": _as_enum(meta.get("ja_source"), JA_SOURCES),
                "en_text": meta.get("en_text"),
                "en_source": _as_enum(meta.get("en_source"), EN_SOURCES),
                "en_is_rederived": bool(meta.get("en_is_rederived")),
                "en_engine": meta.get("en_engine"),
            }
        return doc

    def _tag_docs(self, asset_id: str) -> list[dict]:
        """1 枚のタグを契約（`Tag`）の形で組む（P4-0。設計 §0.12 / §6.1）。

        - **出所ごとに 1 行**（`asset_tag` の主キーが `(asset_id, tag_id, source)`）
        - `gloss` は `tag_gloss.ja`、`gloss_edited` は `edited`（**人が直した印**）
        - `known` は **タグの語彙にある語か**（利用者の回答 Q1）
        - 並びは **`name` → `source`** に固定（決定性。§6.1）
        - `include_tags` が真のときだけ呼ばれる（既定は false。`design.md` §9.4）
        """
        rows = self.store.con.execute(
            "SELECT t.name, t.category, t.category_name, t.known,"
            " a.score, a.source, g.ja, g.edited"
            " FROM asset_tag a JOIN tag t ON t.id = a.tag_id"
            " LEFT JOIN tag_gloss g ON g.tag_id = t.id"
            " WHERE a.asset_id = ?"
            " ORDER BY t.name, a.source", (asset_id,)).fetchall()
        return [{
            "name": r["name"],
            "category": r["category"],
            "category_name": r["category_name"],
            "score": r["score"],
            "source": r["source"],
            "known": bool(r["known"]),
            "gloss": r["ja"],
            "gloss_edited": (bool(r["edited"]) if r["ja"] is not None else None),
        } for r in rows]

    def _external_ref(self, asset, meta: dict, locations: list[dict]):
        prompt_id = meta.get("prompt_id")
        if prompt_id:
            name = Path(locations[0]["display_path"]).name if locations else None
            return {"kind": "comfyui", "ref": name, "url": None, "prompt_id": str(prompt_id)}
        return None

    def _provenance(self, asset, meta: dict):
        if not meta:
            return None
        loras = meta.get("loras")
        names = [str(l["name"]) for l in loras if isinstance(l, dict) and l.get("name")] \
            if isinstance(loras, list) else None
        return {
            "model": meta.get("model"),
            "loras": names or None,
            "vae": meta.get("vae"),
            "sampler": meta.get("sampler"),
            "scheduler": meta.get("scheduler"),
            # seed は**10 進の文字列**。18446744073709551615 を数値にしない
            "seed": _as_seed(meta.get("seed")),
            "steps": _as_int(meta.get("steps")),
            "cfg": _as_num(meta.get("cfg")),
            "denoise": _as_num(meta.get("denoise")),
            "width": _as_int(meta.get("width")) or _as_int(asset["width"]),
            "height": _as_int(meta.get("height")) or _as_int(asset["height"]),
            "prompt_id": str(meta["prompt_id"]) if meta.get("prompt_id") else None,
            "has_workflow_graph": meta.get("graph_format") == "api+ui",
        }

    # ---- 中 ----

    def _meta(self, asset_id: str) -> dict:
        row = self.store.con.execute(
            "SELECT meta_json FROM asset_meta WHERE asset_id = ?", (asset_id,)).fetchone()
        if row is None or not row["meta_json"]:
            return {}
        try:
            got = json.loads(row["meta_json"])
        except ValueError:
            return {}
        return got if isinstance(got, dict) else {}

    def _latest_asset_state(self, asset_id: str) -> dict | None:
        """その枚の**最後の判断**（`seq` の降順。`created_at` では選ばない。点検 C11）。"""
        row = self.store.con.execute(
            "SELECT verdict, reason_code_id, note FROM decision"
            " WHERE subject_type = 'asset' AND subject_id = ? ORDER BY seq DESC LIMIT 1",
            (asset_id,)).fetchone()
        if row is None:
            return None
        return {"verdict": None if row["verdict"] == "clear" else row["verdict"],
                "reason_code_id": row["reason_code_id"], "note": row["note"]}

    def _slot(self, asset_id: str, group_id: str) -> str | None:
        row = self.store.con.execute(
            "SELECT group_decision FROM decision WHERE subject_type = 'asset'"
            " AND subject_id = ? AND group_id = ? AND group_decision IS NOT NULL"
            " ORDER BY seq DESC LIMIT 1", (asset_id, group_id)).fetchone()
        return row["group_decision"] if row else None
