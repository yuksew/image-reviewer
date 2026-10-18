"""日本語の語釈（P4-2。R3 の「日本語の語釈」）。

設計: `docs/p4-design.md` **§0.9**（語釈の作法。**点検 A-3 / G-1・G-7 で確定**）・
§0.10（`GET` は書かない・再送・決定性）・§3.4（`glosses` / `pending_gloss` / `counts`）・
§3.5（3 つの口）・§4.2（`tag_gloss` の状態）・§7（時間）・§8.1 の 9〜11・21・23

決めたことの要点（**設計 §0.9 をそのまま実装する**）:

- **頼み方は `1. 1girl`（番号＋`.`＋空白＋語）**。返った本文は **`^(\\d+)[.)]\\s*(.+)$` で番号を取り、
  番号で語に対応**させる（**位置に依存しない**。実行で位置対応は崩れた）
- **保存するのは「番号が取れた」かつ「本文が ASCII だけではない」行だけ**。空行は読み飛ばし、
  **番号の重複はその番号を捨てる**（どちらが正か決められない）
- **取れなかった番号だけ 1 語ずつ訳し直す**（成功の条件は「番号が取れて日本語が返った」）。
  それでも駄目な語は**保存しない**（`tag_gloss` に行を作らない）。**部分的に当てはめてよい**
- **まとめて訳すのは最大 20 語**。**既定は「語釈の無い語だけ」**（既にある語は模型を回さず `skipped`）
- **`edited=1` は上書きしない**（`force=true` でも）
- **模型を待つのは取引の外**（読む → 模型 → 短い 1 取引で書く。`jobs.py` と同じ形）
- **`GET` は 1 バイトも書かない**（訳すのは `POST` だけ）
"""

from __future__ import annotations

import json
import re
import time
from typing import Iterable, Sequence

from . import db
from .review import ReviewError
from .tagger import _http_json                      # 同じ投げ方を使う（写しを作らない）

#: 語釈の模型（利用者の回答 Q5。`CLIPLoader` の `clip_name`）
DEFAULT_LLM = "qwen3vl_8b_int8_convrot.safetensors"
#: ComfyUI の URL（設定 `gloss.url` が無ければ `tagger.comfyui` を使う）
DEFAULT_URL = "http://127.0.0.1:8188"
#: `TextGenerate` の `max_length`（20 語で足りた。実測）
DEFAULT_MAX_LENGTH = 512
#: まとめて訳す単位（§0.9）
DEFAULT_BATCH = 20
MAX_BATCH = 20
#: 人が書く語釈の長さの上限（設計は黙っている。`ask` などと同じ 200 に揃える）
MAX_JA = 200

#: `system_prompt` の初期値（**設定に置く**。コードに埋めない＝`design.md` §7.3.2 と同じ規律。
#: ここはその既定値で、`settings` の `gloss.system_prompt` があればそちらを使う）
DEFAULT_SYSTEM_PROMPT = (
    "あなたは Danbooru のタグを日本語にする辞書です。"
    "入力は 1 行に 1 つ、番号付きで並んでいます。"
    "同じ番号を付けて、1 行に 1 つ、日本語の語釈だけを返してください。"
    "説明・例・括弧書き・英語の繰り返しは書かないでください。"
    "タグ用語として通る短い日本語にしてください。"
)

#: 「番号. 本文」の形（`.` と `)` の両方を受ける。§0.9 の 2
_NUMBERED = re.compile(r"^(\d+)[.)]\s*(.+)$")


def settings_of(con) -> dict:
    """`settings` 表の `gloss.*` を読む（無ければ既定）。

    `url` は `gloss.url` → `tagger.comfyui` → 既定、の順に落とす（同じ ComfyUI を使うため）。
    """
    got: dict[str, str] = {}
    tagger_url = None
    try:
        for row in con.execute("SELECT key, value FROM settings WHERE key LIKE 'gloss.%'"
                               " OR key = 'tagger.comfyui'"):
            if row["key"] == "tagger.comfyui":
                tagger_url = row["value"]
            else:
                got[row["key"]] = row["value"]
    except Exception:                                # noqa: BLE001  表が無い環境でも既定で動く
        pass

    def number(key: str, default: int) -> int:
        try:
            return int(float(got.get(key, default)))
        except (TypeError, ValueError):
            return default

    return {
        "url": (got.get("gloss.url") or tagger_url or DEFAULT_URL).rstrip("/"),
        "llm": got.get("gloss.llm") or DEFAULT_LLM,
        "system_prompt": got.get("gloss.system_prompt") or DEFAULT_SYSTEM_PROMPT,
        "max_length": number("gloss.max_length", DEFAULT_MAX_LENGTH),
        "batch": max(1, min(number("gloss.batch", DEFAULT_BATCH), MAX_BATCH)),
        "timeout": number("gloss.timeout", 300),
    }


# ---- 本文の組み立てと読み取り（**純関数**。テストはここを直接叩く）----


#: **かな・漢字**（半角カナも）。**記号だけ・絵文字＋英語**を弾く（P4-2 の監査 C-2 / G-3）
JAPANESE_CHARS = re.compile(r"[\u3041-\u309f\u30a0-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uff66-\uff9f]")


def is_japanese(text: str) -> bool:
    """**かな・漢字を 1 文字以上含む**か（§0.9 の 3。点検 A-3 / P4-2 の監査 C-2）。

    - 英語のままの行（`1girl`）を弾く
    - **`……` のような記号だけ**と、**`👁️ girl` のような絵文字＋英語**も弾く
      （模型が `👁️ = 視聴者を見つめる` を返した実例がある。点検 A-3）
    - 空白だけの本文は落とす（空行と同じ扱い）
    """
    body = (text or "").strip()
    return bool(body) and bool(JAPANESE_CHARS.search(body))


def format_prompt(names: Sequence[str]) -> str:
    """**`1. 1girl` の形**で 1 行ずつ並べる（§0.9 の 1）。"""
    return "\n".join(f"{index}. {name}" for index, name in enumerate(names, 1))


def parse_numbered(text: str) -> dict[int, str]:
    """模型の応答 → `{番号: 語釈}`（§0.9 の 2〜6）。**読むだけの純関数**。

    - **空行は読み飛ばす**（実測で `胸\\n\\n見る` のように行間が空く）
    - `^(\\d+)[.)]\\s*(.+)$` に合わない行（**番号の無い行**）は捨てる
    - **番号の重複はその番号を捨てる**（どちらが正か決められない）
    - **本文が ASCII だけの行**（英語のまま）は捨てる
    """
    out: dict[int, str] = {}
    seen: set[int] = set()
    for raw in (text or "").splitlines():
        line = raw.strip()
        if not line:
            continue                                 # 空行は読み飛ばす
        matched = _NUMBERED.match(line)
        if matched is None:
            continue                                 # 番号の無い行
        number, body = int(matched.group(1)), matched.group(2).strip()
        if number in seen:
            out.pop(number, None)                    # 番号の重複 → その番号を捨てる
            continue
        seen.add(number)
        if not is_japanese(body):
            continue                                 # 英語のままの行
        out[number] = body
    return out


def _chunks(items: list, size: int) -> Iterable[list]:
    for start in range(0, len(items), size):
        yield items[start:start + size]


# ---- 模型を回す所（ComfyUI の `TextGenerate`）----


class GlossEngine:
    """ComfyUI の `TextGenerate` で訳す（§0.9 の表）。

    グラフ: `CLIPLoader(clip_name=<設定の LLM>, type='qwen_image')` →
    `TextGenerate(clip, prompt, max_length, sampling_mode='off', thinking=False,
    use_default_template=True, mtp='auto', system_prompt)` → **`PreviewAny` を繋ぐ**
    （`TextGenerate` は `output_node: false` なので、繋がないと `prompt_no_outputs` で 400）。
    """

    #: 保存する `tag_gloss.engine` の値（**使った模型名**。§0.9 の最後）
    name = "textgenerate"

    def __init__(self, url: str, *, llm: str = DEFAULT_LLM,
                 system_prompt: str = DEFAULT_SYSTEM_PROMPT, max_length: int = DEFAULT_MAX_LENGTH,
                 timeout: float = 300.0, poll: float = 0.05, client_id: str | None = None):
        self.base = url.rstrip("/")
        self.llm = llm
        self.system_prompt = system_prompt
        self.max_length = int(max_length)
        self.timeout = float(timeout)
        self.poll = float(poll)
        self.client_id = client_id or db.ulid()

    #: `tag_gloss.engine` に入れる値（模型名。§3.4 の例）
    @property
    def engine(self) -> str:
        return self.llm

    def ping(self) -> bool:
        """繋がるか（**模型を回す前に 1 回**。§3.5 の 409 のため）。"""
        try:
            _http_json(self.base + "/system_stats", timeout=5.0)
            return True
        except Exception:                            # noqa: BLE001  繋がらない理由は問わない
            return False

    def translate(self, names: Sequence[str]) -> str:
        """1 回投げて**本文**を返す（`names` は 1〜20 語）。"""
        prompt = format_prompt(names)
        prompt_id = self._submit(prompt)
        outputs = self._wait(prompt_id)
        return self._text(outputs)

    # ---- 中身 ----

    def _graph(self, prompt: str) -> dict:
        return {
            "1": {"class_type": "CLIPLoader",
                  "inputs": {"clip_name": self.llm, "type": "qwen_image"}},
            "2": {"class_type": "TextGenerate",
                  "inputs": {"clip": ["1", 0], "prompt": prompt,
                             "max_length": self.max_length,
                             # **決定的にする**（G-7。2 回同じ出力を実測で確認）
                             "sampling_mode": "off",
                             "thinking": False, "use_default_template": True, "mtp": "auto",
                             "system_prompt": self.system_prompt}},
            # 出力ノード（繋がないと 400 `prompt_no_outputs`）
            "3": {"class_type": "PreviewAny", "inputs": {"source": ["2", 0]}},
        }

    def _submit(self, prompt: str) -> str:
        try:
            got = _http_json(self.base + "/prompt",
                             json.dumps({"prompt": self._graph(prompt),
                                         "client_id": self.client_id}).encode(),
                             headers={"Content-Type": "application/json"}, timeout=60.0)
        except OSError as exc:
            # **P4-2 の監査 B-1 / E-3**: 繋がらない・時間切れは 500 にしない（502）
            raise ReviewError(502, "ComfyUI につながりません",
                              details={"url": self.base, "error": str(exc)}) from exc
        prompt_id = (got or {}).get("prompt_id")
        if not prompt_id:
            raise ReviewError(502, "ComfyUI が prompt_id を返しません", details={"got": got})
        return str(prompt_id)

    def _wait(self, prompt_id: str) -> dict:
        """`/history/{id}` を 0.05 秒ごとに見る（P4-1 の監査 C-1 と同じ間隔）。

        **P4-2 の監査 B-1**: 模型の読み込みで ComfyUI のイベントループが長く塞がると、
        `/history` の接続が OS の時間切れで落ちる（実測: 冷えた模型の初回に 4 回中 1 回
        `WinError 10060`。**そのとき 500 を返していた**）。**通信の失敗は待ち直し**、
        期限を越えたら 504 にする（読み込み中の無応答は数秒〜十数秒で、待てば通る）。
        """
        deadline = time.monotonic() + self.timeout
        while time.monotonic() < deadline:
            try:
                got = _http_json(f"{self.base}/history/{prompt_id}", timeout=30.0) or {}
            except OSError:
                time.sleep(self.poll)
                continue
            entry = got.get(prompt_id)
            if entry:
                status = entry.get("status") or {}
                if status.get("status_str") == "error":
                    raise ReviewError(502, "ComfyUI がエラーを返しました",
                                      details={"messages": status.get("messages")})
                outputs = entry.get("outputs") or {}
                if outputs:
                    return outputs
            time.sleep(self.poll)
        raise ReviewError(504, "ComfyUI の応答が時間内に返りません",
                          details={"prompt_id": prompt_id})

    def _text(self, outputs: dict) -> str:
        """**ノード番号を決め打ちしない**（本文らしい出力を探す。§0.5 と同じ流儀）。

        `PreviewAny` の出力は `text` だが、ComfyUI の版で鍵が変わりうるので、
        既知の鍵 → 「文字列の配列を持つ最初の鍵」の順に探す。
        """
        for node in outputs.values():
            if not isinstance(node, dict):
                continue
            for key in ("text", "string", "generated_text", "value", "source"):
                got = node.get(key)
                if isinstance(got, list) and got and isinstance(got[0], str):
                    return got[0]
                if isinstance(got, str):
                    return got
            for got in node.values():
                if isinstance(got, list) and got and isinstance(got[0], str):
                    return got[0]
        raise ReviewError(502, "ComfyUI の出力に本文がありません", details={"outputs": list(outputs)})


def build(settings: dict) -> GlossEngine:
    """設定から模型の実体を作る。"""
    return GlossEngine(settings["url"], llm=settings["llm"],
                       system_prompt=settings["system_prompt"],
                       max_length=settings["max_length"], timeout=settings["timeout"])


# ---- 読み出し（`GET` 用。**書かない**）----


def lookup(con, tag_id: int) -> dict:
    """1 語の語釈（§3.5 の `GET /api/tags/{tag_id}/gloss`）。**訳さない**。"""
    row = con.execute(
        "SELECT t.id, t.name, g.ja, g.source, g.engine, g.edited, g.updated_at"
        " FROM tag t LEFT JOIN tag_gloss g ON g.tag_id = t.id WHERE t.id = ?",
        (int(tag_id),)).fetchone()
    if row is None:
        raise ReviewError(404, "その語はありません", details={"tag_id": tag_id})
    return {"tag_id": int(row["id"]), "name": row["name"], "ja": row["ja"],
            "source": row["source"], "engine": row["engine"],
            "edited": bool(row["edited"]) if row["edited"] is not None else None,
            "updated_at": row["updated_at"]}


def pending(con, *, limit: int = 100) -> dict:
    """語釈の無い語を**数えるだけ**（§3.5 の `GET /api/tags/gloss/pending`）。

    使用数の多い順（画面が「見えている語」から訳すため、よく使う語が先に来る方がよい）。
    """
    size = max(1, min(int(limit or 100), 1000))
    total = con.execute(
        "SELECT count(*) AS n FROM tag t LEFT JOIN tag_gloss g ON g.tag_id = t.id"
        " WHERE g.tag_id IS NULL").fetchone()["n"]
    rows = con.execute(
        "SELECT t.id, t.name FROM tag t LEFT JOIN tag_gloss g ON g.tag_id = t.id"
        " WHERE g.tag_id IS NULL"
        " ORDER BY (SELECT count(*) FROM asset_tag a WHERE a.tag_id = t.id) DESC, t.name"
        " LIMIT ?", (size,)).fetchall()
    return {"count": int(total),
            "sample": [{"tag_id": int(r["id"]), "name": r["name"]} for r in rows]}


def block_for(con, items: list[dict]) -> dict:
    """§3.4 の `glosses` / `pending_gloss` / `counts` を作る（**読むだけ**）。

    - `glosses`: **語の名前**を鍵にした辞書（`ja` / `source` / `engine` / `edited`）
    - `pending_gloss`: 語釈の無い語の**名前**の配列（`items` の順）
    - `counts`: **出所ごとの数**（`items` は同じ語を 1 行にまとめているので `sources` を数える）
    """
    names = [item["name"] for item in items]
    glosses: dict[str, dict] = {}
    if names:
        marks = ",".join("?" * len(names))
        for row in con.execute(
                f"SELECT t.name, g.ja, g.source, g.engine, g.edited"
                f" FROM tag t LEFT JOIN tag_gloss g ON g.tag_id = t.id"
                f" WHERE t.name IN ({marks})", names):
            if row["ja"] is not None:
                glosses[row["name"]] = {"ja": row["ja"], "source": row["source"],
                                        "engine": row["engine"], "edited": bool(row["edited"])}
    counts: dict[str, int] = {}
    for item in items:
        for source in (item.get("sources") or [item.get("source")]):
            if source:
                counts[source] = counts.get(source, 0) + 1
    return {"glosses": glosses,
            "pending_gloss": [name for name in names if name not in glosses],
            "counts": counts}


def set_manual(con, tag_row, ja: str) -> dict:
    """人が語釈を書く / 直す（§3.5・§4.2）。**呼ぶ側が取引を開く**。

    - 行が無ければ **`source='manual'`・`edited=1`** で作る（人がゼロから書いた）
    - 行があれば **`edited=1` を立て、`ja` を差し替える**。**`source` は由来を保つ**
      （自動の訳を人が直したなら `textgenerate` のまま。§4.2 の括弧書き）・**`engine` は触らない**
    """
    now = db.stamp()
    tag_id = int(tag_row["id"])
    row = con.execute("SELECT 1 FROM tag_gloss WHERE tag_id = ?", (tag_id,)).fetchone()
    if row is None:
        con.execute("INSERT INTO tag_gloss(tag_id, ja, source, engine, edited, created_at,"
                    " updated_at) VALUES (?,?,'manual',NULL,1,?,?)", (tag_id, ja, now, now))
    else:
        con.execute("UPDATE tag_gloss SET ja = ?, edited = 1, updated_at = ? WHERE tag_id = ?",
                    (ja, now, tag_id))
    return lookup(con, tag_id)


# ---- 訳す（`POST /api/tags/gloss`）----


class GlossService:
    """語釈を作る（P4-2）。**模型を待つのは取引の外**（P4-1 の監査 B-1 と同じ規律）。"""

    def __init__(self, store, *, engine_factory=None):
        self.store = store
        #: テストは偽の模型を差し込む（**本物は呼ばない**）
        self._factory = engine_factory or (lambda settings: build(settings))

    def engine(self):
        """**呼ぶたびに設定を読み直す**（P4-2 の監査 C-1 / G-2）。

        以前はプロセスで 1 回だけ読んでいたので、`gloss.llm` / `gloss.url` /
        `gloss.system_prompt` を変えても**再起動するまで効かなかった**
        （実測: 無い模型名を指定しても古い模型で訳が通り、409 の検査も再起動が要った）。
        `GlossEngine` は状態を持たないので作り直しは軽い。
        """
        with self.store.locked() as con:
            settings = settings_of(con)
        return self._factory(settings)

    # ---- 訳す ----

    def translate(self, *, tag_ids: Sequence[int] | None, limit: int | None = None,
                  force: bool = False) -> dict:
        """§3.5。**既定は「語釈の無い語だけ」**（点検 B-3）。`force=true` でも `edited=1` は守る。"""
        started = time.monotonic()
        ids = self._check_ids(tag_ids, limit)
        # --- ① 読む（錠だけ）---
        with self.store.locked() as con:
            rows = self._rows(con, ids)
        work: list[dict] = []
        skipped: list[dict] = []
        for row in rows:
            if row["ja"] is not None and row["edited"]:
                skipped.append({"tag_id": row["id"], "name": row["name"],
                                "reason": "人が直した語釈は上書きしません"})
            elif row["ja"] is not None and not force:
                skipped.append({"tag_id": row["id"], "name": row["name"],
                                "reason": "既に語釈があります"})
            else:
                work.append(row)
        empty = {"translated": [], "skipped": skipped, "untranslated": [], "calls": 0,
                 "elapsed_ms": self._ms(started)}
        if not work:
            # **模型を回さない**（2 回押しても 2 回目は呼び出し 0 回。点検 B-3）。
            # 繋がらないときの 409 も出さない（回さないので関係ない）
            return empty
        # --- ② 模型（錠の外）---
        engine = self.engine()
        if not engine.ping():
            raise ReviewError(409, "語釈のモデル（ComfyUI）につながりません。ComfyUI を起動すると訳が使えます",
                              code="gloss_engine_unavailable",
                              details={"url": getattr(engine, "base", None)})
        calls = 0
        with self.store.locked() as con:
            batch_size = settings_of(con)["batch"]
        got: dict[int, str] = {}
        untranslated: list[dict] = []
        for batch in _chunks(work, batch_size):
            text = engine.translate([row["name"] for row in batch])
            calls += 1
            mapping = parse_numbered(text)
            for index, row in enumerate(batch, 1):
                ja = mapping.get(index)
                if ja:
                    got[row["id"]] = ja
                else:
                    # **取れなかった番号だけ 1 語ずつ**（成功の条件は「番号が取れて日本語が返った」）
                    again = parse_numbered(engine.translate([row["name"]]))
                    calls += 1
                    if again.get(1):
                        got[row["id"]] = again[1]
                    else:
                        untranslated.append({
                            "tag_id": row["id"], "name": row["name"],
                            "reason": "番号が取れず、1 語ずつでも訳せませんでした"})
        # --- ③ 書く（短い 1 取引）---
        translated = []
        if got:
            now = db.stamp()
            with self.store.transaction() as con:
                for row in rows:
                    ja = got.get(row["id"])
                    if not ja:
                        continue
                    # **`edited=1` を `WHERE` でも守る**（①の仕分けをすり抜けた場合の保険）
                    con.execute(
                        "INSERT INTO tag_gloss(tag_id, ja, source, engine, edited, created_at,"
                        " updated_at) VALUES (?,?,'textgenerate',?,0,?,?)"
                        " ON CONFLICT(tag_id) DO UPDATE SET ja = excluded.ja,"
                        " source = 'textgenerate', engine = excluded.engine, edited = 0,"
                        " updated_at = excluded.updated_at WHERE tag_gloss.edited = 0",
                        (row["id"], ja, engine.engine, now, now))
                    translated.append({"tag_id": row["id"], "name": row["name"], "ja": ja,
                                       "engine": engine.engine})
        return {"translated": translated, "skipped": skipped, "untranslated": untranslated,
                "calls": calls, "elapsed_ms": self._ms(started)}

    # ---- 中身 ----

    @staticmethod
    def _ms(started: float) -> int:
        return int(round((time.monotonic() - started) * 1000))

    @staticmethod
    def _check_ids(tag_ids: Sequence[int] | None, limit: int | None) -> list[int]:
        """§3.5 の 422（空・上限超え）と、id の正規化（渡された順を保つ）。"""
        size = MAX_BATCH if limit is None else max(1, min(int(limit), MAX_BATCH))
        if not isinstance(tag_ids, (list, tuple)):
            raise ReviewError(422, "tag_ids は配列です", details={"tag_ids": "1 つ以上"})
        ids: list[int] = []
        for raw in tag_ids:
            try:
                value = int(raw)
            except (TypeError, ValueError):
                raise ReviewError(422, "tag_ids は整数の配列です",
                                  details={"tag_ids": str(raw)}) from None
            if value not in ids:
                ids.append(value)
        if not ids:
            raise ReviewError(422, "tag_ids を 1 つ以上ください", details={"tag_ids": "1 つ以上"})
        if len(ids) > size:
            raise ReviewError(422, f"一度に訳せるのは {size} 語までです",
                              details={"tag_ids": f"{size} 語まで", "count": len(ids)})
        return ids

    def _rows(self, con, ids: list[int]) -> list[dict]:
        """渡された順のまま引く。**知らない id は 404**（設計は黙っているので他の口に揃える）。"""
        marks = ",".join("?" * len(ids))
        found = {int(row["id"]): row for row in con.execute(
            f"SELECT t.id, t.name, g.ja, g.edited FROM tag t"
            f" LEFT JOIN tag_gloss g ON g.tag_id = t.id WHERE t.id IN ({marks})", ids)}
        out: list[dict] = []
        for tag_id in ids:
            row = found.get(tag_id)
            if row is None:
                raise ReviewError(404, "その語はありません", details={"tag_id": tag_id})
            out.append({"id": int(row["id"]), "name": row["name"], "ja": row["ja"],
                        "edited": int(row["edited"] or 0)})
        return out


def describe(settings: dict) -> str:
    """起動時のログに出す 1 行。"""
    return f"語釈: {settings['llm']}（{settings['url']}）"
