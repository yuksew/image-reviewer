"""タグ付け（P4-1）。**語を 2 つの出所から集める。**

設計: docs/p4-design.md §0.4〜§0.8・§0.10・§3（口は `api/tags.py`）

- **出所は 3 つ**（`asset_tag.source`）: `png`（生成に使った語）/ `wd14`（タガーが画像から読んだ語）/
  `manual`（人が付けた語。ここでは触らない）
- **方式は 2 つ**（`builtin` = `onnxruntime` の内蔵 / `comfyui` = ComfyUI に投げる）。
  **どちらも使えなければ job を作らない**（`tagger_unavailable`。§0.4）
- **`GET` は書かない**（§0.10）。このモジュールは**書く側**（`POST /api/assets/tag` から呼ばれる）

この環境の現物（§0.4・点検で実測）:

- `onnxruntime` は**入っていない**（任意依存。`uv sync --extra tagger`。**CUDA の DLL は自分で用意する**。
  無いと `get_providers()` が CPU だけを返し、**黙って遅くなる**＝点検 B-2）
- ComfyUI は動いている。**既定のノードは `IllustTagger`**（スコアが返り 0.26〜0.31 s/枚。
  `WD14Tagger|pysssss` はスコア無しで 2.8〜3.4 s/枚。**呼ばれるたびに 1.2 GB の ONNX を読み直す**）
- ComfyUI の `LoadImage` は **`input/` の一覧しか受けない**ので、**複製を `upload/image` で作って渡す**（点検 A-2）
"""

from __future__ import annotations

import csv
import io
import json
import re
import urllib.error
import urllib.request
import uuid
from pathlib import Path
from typing import Any, Iterable, Sequence

from . import db
from .review import ReviewError

# ---- 設定の既定（`settings` 表の `tagger.*` で上書きできる。§0.4・§0.6）----

DEFAULT_ENGINE = "auto"                 # auto | builtin | comfyui
DEFAULT_MODEL = "wd-eva02-large-tagger-v3"
DEFAULT_THRESHOLD = 0.35                # ノードの既定と同じ
DEFAULT_CHARACTER_THRESHOLD = 0.85
DEFAULT_COMFYUI = "http://127.0.0.1:8188"
DEFAULT_NODE = "illust"                 # illust（既定）| wd14
UPLOAD_SUBFOLDER = "image-reviewer"     # ComfyUI の temp に作る複製の置き場（点検 A-2 / G-6）

# モデルと CSV の置き場の候補。**この環境の現物**（kohya 命名は自動探索で見つからない。§0.4）。
# 別の場所に置くときは `settings` の `tagger.onnx_path` / `tagger.csv_path` で指定する。
ONNX_CANDIDATES = (
    r"C:\work\lora-studio\models\wd-eva02-large-tagger-v3\model.onnx",
    r"C:\ai\ComfyUI_windows_portable\ComfyUI\custom_nodes\ComfyUI-WD14-Tagger\models"
    r"\wd-eva02-large-tagger-v3.onnx",
)
CSV_CANDIDATES = (
    r"C:\work\lora-studio\models\wd-eva02-large-tagger-v3\selected_tags.csv",
    r"C:\ai\ComfyUI_windows_portable\ComfyUI\custom_nodes\ComfyUI-WD14-Tagger\models"
    r"\wd-eva02-large-tagger-v3.csv",
)

ENGINES = ("auto", "builtin", "comfyui")
SOURCES = ("png", "wd14")

#: 語の長さの上限（点検 §I-3）。実データには **`,` と `.` で割っても文が残る断片**があり、
#: 252 字の文がそのまま 1 語になった例がある。**超えた断片は入れず、数える**（黙って捨てない）。
MAX_TAG_LEN = 64


def is_acceptable(name: str) -> bool:
    """タグとして受け入れる語か（空・長すぎる断片を弾く。点検 §I-3）。"""
    return bool(name) and len(name) <= MAX_TAG_LEN

# ---- 語の正規形（§0.7。**点検 A-1**）----

#: PNG の断片から外す**前置き**（`First girl: black hair` の `First girl:`。§0.8-2）
_PREFIX_RE = re.compile(r"^(?:first|second|third|fourth|fifth|1st|2nd|3rd)\s+\w+\s*:\s*", re.I)
#: PNG の断片の**外側の重み**（`(three quarter view:1.5)` → `three quarter view`。§0.8-2）
_OUTER_WEIGHT_RE = re.compile(r"^\(+\s*(.*?)\s*:\s*[0-9.]+\s*\)+$")
#: 語尾の `:数字`（重み）
_TRAILING_WEIGHT_RE = re.compile(r"\s*:\s*[0-9.]+\s*$")


def normalize_name(raw: Any) -> str:
    """語の正規形（§0.7）。**括弧とコロンは語の一部として残す**（点検 A-1）。

    1. 前後の空白を落とす 2. 空白を `_` に 3. 小文字に 4. **`\\(` `\\)` のエスケープを外す**
    5. `[` `]` は落とす（CSV に `[` を含む語は 0 件。実測）

    **括弧を落としてはいけない**: CSV の 10,861 語のうち**括弧を含む語が 1,596**
    （キャラ名 2,751 の **51%**）。落とすと `admiral_\\(kancolle\\)` が `admiral_kancolle` になり、
    **語彙（CSV）と一致しなくなる**（キャラ名が全部落ちる）。
    """
    text = str(raw or "").strip()
    if not text:
        return ""
    text = text.replace("\\(", "(").replace("\\)", ")")     # エスケープを外す（残すのは括弧そのもの）
    text = re.sub(r"\s+", "_", text)
    text = text.lower()
    text = text.replace("[", "").replace("]", "")
    return text.strip("_")


def png_words(text: Any) -> list[str]:
    """`final_prompt` から語を**決定的に**切り出す（§0.8）。**重複は落とし、順は保つ。**

    - `,` で割り、**文の切れ目（`. ` または末尾の `.`）でも割る**（実データは
      `looking to the side. First girl: black hair, …` の形。§0.8-1）。
      **`.` の直後が空白のときだけ割る**——`(three quarter view:1.5)` の**小数を壊さない**ため
    - `First girl:` のような前置きを外す
    - **外側の 1 組の重み** `( … :1.5)` と `:数字` だけを外す（**内側の括弧は語の一部**）
    - 正規形に直す（**語彙にあるかは見ない**。`known` は `tag.known` で持つ＝利用者の回答 Q1）
    """
    if not text:
        return []
    out: list[str] = []
    seen: set[str] = set()
    for chunk in str(text).split(","):
        # さらに**文の切れ目**（`. ` または末尾の `.`）でも割る。**小数（`:1.5`）は割らない**
        for piece in re.split(r"\.\s+|\.$", chunk):
            piece = piece.strip()
            if not piece:
                continue
            piece = _PREFIX_RE.sub("", piece)
            piece = piece.replace("\\(", "(").replace("\\)", ")")
            match = _OUTER_WEIGHT_RE.match(piece)
            if match:
                piece = match.group(1)
            piece = _TRAILING_WEIGHT_RE.sub("", piece)
            piece = _balanced(piece)          # 括弧の数が合わない断片を落とす（P4-1 の監査 C-3）
            if not piece:
                continue
            name = normalize_name(piece)
            if not name or name in seen:
                continue
            seen.add(name)
            out.append(name)
    return out


def _paren_ok(text: str) -> bool:
    """括弧の数が合い、入れ子が壊れていないか（`admiral_(kancolle)` は真）。"""
    depth = 0
    for char in text:
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth < 0:
                return False
    return depth == 0


def _balanced(piece: str) -> str:
    """括弧の数が**合わない**断片を直すか落とす（P4-1 の監査 C-3）。

    `,` で先に割るので、`(masterpiece, best quality:1.2)` の**外側の重みの規則に当たらない**
    断片が残る（実データで `(masterpiece` が語として出た）。規則:

    - **数が合っていればそのまま**（`admiral_(kancolle)` / `rem_(re:zero)` は**語の一部**。点検 A-1）
    - ただし**全体を囲む組は外す**（`(bar)` → `bar`、`((foo))` → `foo`。Danbooru の語で
      括弧が先頭に来る語は無い）
    - **先頭に余分な `(` がある形**は、外して釣り合えば通す（`(masterpiece` → `masterpiece`）
    - それ以外（`masterpiece)` のような切れ端）は**落とす**
    """
    if _paren_ok(piece):
        while len(piece) > 2 and piece[0] == "(" and piece[-1] == ")" and _paren_ok(piece[1:-1]):
            piece = piece[1:-1]
        return piece
    stripped = piece.lstrip("(")
    if stripped != piece and stripped and _paren_ok(stripped):
        return stripped
    return ""


# ---- CSV（語彙。`known` の判定とカテゴリ。§0.6-6・§0.7）----


class TagCsv:
    """`selected_tags.csv`。**行順が出力ベクトルの並び**（§0.6-6）。

    `category` は **0（general）/ 4（character）/ 9（rating）** の 3 つが**連続した塊**で並ぶ
    （実測: rating 4 行 → general 8,106 行 → character 2,751 行）。
    **連続していない CSV は拒否する**（`general_index` / `character_index` の決め方が成り立たない。点検 C-2）。
    """

    def __init__(self, path: str | Path):
        self.path = Path(path)
        rows = self._read(self.path)
        if not rows:
            raise ReviewError(409, "タグの語彙（CSV）が空です", code="tagger_csv_unsupported",
                              details={"csv": str(self.path)})
        self.names: list[str] = [r["name"] for r in rows]
        self.categories: list[str] = [r["category"] for r in rows]
        self.category_names = {r["name"]: r["category"] for r in rows}
        self.general_index = self._first("0")
        self.character_index = self._first("4")
        self._check_contiguous()
        self._name_set = set(self.names)

    @staticmethod
    def _read(path: Path) -> list[dict]:
        """ヘッダを見て `name` / `category` の列を決める（列の順を決め打ちしない）。"""
        with path.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.reader(handle)
            try:
                head = next(reader)
            except StopIteration:
                return []
            lowered = [h.strip().lower() for h in head]
            if "name" in lowered:
                name_at = lowered.index("name")
                cat_at = lowered.index("category") if "category" in lowered else None
            else:                                   # ヘッダが無い CSV は tag_id,name,category とみなす
                name_at, cat_at = 1, 2 if len(head) > 2 else None
            out = []
            for row in reader:
                if len(row) <= name_at:
                    continue
                name = row[name_at].strip()
                if not name:
                    continue
                category = row[cat_at].strip() if (cat_at is not None and len(row) > cat_at) else ""
                out.append({"name": name, "category": category})
            return out

    def _first(self, category: str) -> int:
        for index, got in enumerate(self.categories):
            if got == category:
                return index
        return -1

    def _check_contiguous(self) -> None:
        """`category` が**連続した塊**で並んでいるか（同じ値が 2 回現れたら拒否）。"""
        seen: list[str] = []
        for got in self.categories:
            if not seen or seen[-1] != got:
                if got in seen:
                    raise ReviewError(
                        409, "タグの語彙（CSV）の category が連続していません",
                        code="tagger_csv_unsupported",
                        details={"csv": str(self.path), "note": "category が連続していません"})
                seen.append(got)

    def known(self, name: str) -> bool:
        """語彙にある語か（`tag.known`。§0.8-4）。"""
        return name in self._name_set

    def category_of(self, name: str) -> tuple[int | None, str | None]:
        """語の `category` と `category_name`。無ければ `(None, None)`。"""
        for index, got in enumerate(self.names):
            if got == name:
                raw = self.categories[index]
                try:
                    return int(raw), _CATEGORY_NAMES.get(raw)
                except ValueError:
                    return None, None
        return None, None


_CATEGORY_NAMES = {"0": "general", "1": "artist", "3": "copyright", "4": "character", "9": "rating"}


def read_csv(path: str | Path) -> TagCsv:
    return TagCsv(path)


def find_csv(explicit: str | None = None) -> Path | None:
    """CSV の場所。指定 → 候補（現物の 2 か所）の順に探す（§0.4）。"""
    if explicit:
        got = Path(explicit)
        return got if got.exists() else None
    for candidate in CSV_CANDIDATES:
        got = Path(candidate)
        if got.exists():
            return got
    return None


def find_onnx(explicit: str | None = None) -> Path | None:
    if explicit:
        got = Path(explicit)
        return got if got.exists() else None
    for candidate in ONNX_CANDIDATES:
        got = Path(candidate)
        if got.exists():
            return got
    return None


# ---- 内蔵方式（§0.6。**前処理は 1 つも変えない**）----


def preprocess(image, size: int):
    """内蔵方式の入力を作る（§0.6。**ComfyUI のノードと同じ手順**）。

    1. 長い辺が `size` になるよう縮小（**`Image.LANCZOS`**）
    2. **白（255,255,255）の正方形**に中央寄せで貼る（黒ではない）
    3. `float32` のまま **0〜255**（平均・標準偏差で正規化しない）
    4. **RGB → BGR**（`image[:, :, ::-1]`）

    実測（点検 C-2）: この手順で **ComfyUI と 66 語 = 66 語で一致**。
    **RGB のままだと 62 語**、**0〜1 に正規化すると 9 語**（ほぼ全滅）。**「ついで」に変えないこと。**
    """
    import numpy as np
    from PIL import Image

    width, height = image.size
    scale = size / max(width, height)
    if scale != 1.0:
        # **`int()` で切り捨てる**（P4-1 の監査 B-3）。ノードの実装（`wd14tagger.py:63`）が
        # `int(x * ratio)` なので、`round()` だと寸法が 1 px 違い、**語が 1〜2 語変わることがある**
        # （監査の実測: 768×1360 の 4 枚のうち 2 枚で語が変化）。ここを揃えないと
        # **線 8（内蔵と ComfyUI の一致）が方式の違いではなく丸めの違いで落ちる**
        image = image.resize((max(1, int(width * scale)), max(1, int(height * scale))),
                             Image.LANCZOS)
    canvas = Image.new("RGB", (size, size), (255, 255, 255))
    canvas.paste(image, ((size - image.size[0]) // 2, (size - image.size[1]) // 2))
    array = np.array(canvas).astype(np.float32)          # 0〜255 のまま
    array = array[:, :, ::-1]                            # RGB → BGR
    return np.expand_dims(array, 0)


class BuiltinTagger:
    """`onnxruntime` の内蔵タガー。**入っていなければ使えない**（§0.4）。"""

    name = "builtin"

    def __init__(self, onnx_path: Path, csv_path: Path, *, threshold: float,
                 character_threshold: float, model: str):
        import onnxruntime                                            # optional（extra: tagger）

        self.model = model
        self.threshold = threshold
        self.character_threshold = character_threshold
        self.csv = read_csv(csv_path)
        options = onnxruntime.SessionOptions()
        options.log_severity_level = 3
        self.session = onnxruntime.InferenceSession(
            str(onnx_path), options, providers=["CUDAExecutionProvider", "CPUExecutionProvider"])
        # **点検 B-2**: GPU 版を入れても CUDA の DLL が無ければ黙って CPU になる。
        # 実際に使われている provider をそのまま持つ（`doctor` がこれを出す）
        self.providers = list(self.session.get_providers())
        self.size = int(self.session.get_inputs()[0].shape[1])

    def describe(self) -> str:
        got = self.providers[0] if self.providers else "?"
        if got == "CUDAExecutionProvider":
            return f"使えます（{got}）"
        return f"使えます（{got}。CUDA の DLL が見つかりません）"

    def tag(self, image_path: str | Path, *, name: str | None = None) -> list[tuple[str, float | None]]:
        """1 枚を読んで語を返す。**スコアはこの段では入れない**（§0.10。語名だけ）。

        `name` は**受け取るだけで使わない**（ComfyUI 経由は複製の名前が要るが、内蔵は要らない）。
        **口を揃えておく**: `jobs.py` は方式を選ばずに `tag(path, name=...)` と呼ぶので、
        これが無いと内蔵のときだけ `TypeError` で全件失敗する（`onnxruntime` を入れて初めて踏んだ。
        P4-2 の実測で発覚）。
        """
        import numpy as np
        from PIL import Image

        with Image.open(image_path) as handle:
            image = handle.convert("RGB")
        batch = preprocess(image, self.size)
        result = self.session.run(None, {self.session.get_inputs()[0].name: batch})[0][0]
        general_index, character_index = self.csv.general_index, self.csv.character_index
        names = self.csv.names
        out: list[str] = []
        if general_index >= 0 and character_index > general_index:
            general = result[general_index:character_index]
            character = result[character_index:]
            for index, score in enumerate(character):
                if float(score) > self.character_threshold:
                    name = names[character_index + index]
                    out.append((normalize_name(name), None))
            for index, score in enumerate(general):
                if float(score) > self.threshold:
                    name = names[general_index + index]
                    out.append((normalize_name(name), None))
        return out


# ---- ComfyUI 方式（§0.5。**点検 A-2 / A-4 / G-2**）----


def _http_json(url: str, data: bytes | None = None, *, headers: dict | None = None,
               timeout: float = 30.0, method: str | None = None):
    request = urllib.request.Request(url, data=data, headers=headers or {}, method=method)
    with urllib.request.urlopen(request, timeout=timeout) as response:
        body = response.read()
    return json.loads(body) if body else None


class ComfyTagger:
    """ComfyUI に投げる方式。**既定のノードは `IllustTagger`**（点検 A-4 / G-2）。

    - `IllustTagger`: 出力 `outputs[node]["scores"]` が**1 要素の配列で中身は JSON 文字列**
      （`[["1girl", 0.9931], …]`）。**名前は空白形**なので `_` に直す（§0.5）
    - `WD14Tagger|pysssss`: 出力 `outputs[node]["tags"]` が**1 要素の配列で中身はカンマ区切りの 1 文字列**。
      **スコアは返らない**（§0.5・点検 B-1）
    """

    name = "comfyui"

    def __init__(self, base_url: str, *, node: str = DEFAULT_NODE, model: str = DEFAULT_MODEL,
                 threshold: float = DEFAULT_THRESHOLD,
                 character_threshold: float = DEFAULT_CHARACTER_THRESHOLD,
                 client_id: str | None = None, temp_dir: str | None = None):
        self.base = base_url.rstrip("/")
        self.node = node
        self.model = model
        self.threshold = threshold
        self.character_threshold = character_threshold
        self.client_id = client_id or db.ulid()
        # ComfyUI の `temp` の絶対パス（設定 `tagger.comfyui_temp`）。**複製を消すためだけ**に使う
        self.temp_dir = temp_dir or None

    # ---- 接続 ----

    def ping(self) -> bool:
        try:
            _http_json(self.base + "/system_stats", timeout=5.0)
            return True
        except Exception:                                     # noqa: BLE001  繋がらない理由は問わない
            return False

    # ---- 1 枚 ----

    def tag(self, image_path: str | Path, *, name: str) -> list[tuple[str, float | None]]:
        """1 枚を投げて語を返す。`name` は複製の名前（**`asset_id`** を使う。点検 A-2-3）。

        **複製は使い終わったら消す**（P4-1 の監査 C: `temp/image-reviewer` に 53 枚 19 MB が
        残っていた）。消し口は ComfyUI に無いので、**`tagger.comfyui_temp` に ComfyUI の
        `temp` の絶対パスが設定されているときだけ**ファイルを直接消す（未設定なら残る）。
        """
        uploaded = self._upload(image_path, name)
        try:
            prompt_id = self._submit(uploaded)
            outputs = self._wait(prompt_id)
            return self._parse(outputs)
        finally:
            self._remove_copy(uploaded)

    def _remove_copy(self, uploaded: str) -> None:
        """アップロードした複製を消す（**設定があるときだけ**。P4-1 の監査 C）。

        `uploaded` は `subfolder/name.png [temp]` の形。`tagger.comfyui_temp` が
        ComfyUI の `temp` ディレクトリを指していれば、その下のファイルを消す。
        """
        if not self.temp_dir:
            return
        rel = uploaded.split(" [", 1)[0]
        target = Path(self.temp_dir) / rel
        try:
            target.unlink(missing_ok=True)
        except OSError:                              # noqa: BLE001  消せなくてもジョブは続ける
            pass

    def cleanup(self) -> int:
        """`temp/<subfolder>` に残った複製を**まとめて**消す（起動時と job の終わり）。

        設定（`tagger.comfyui_temp`）が無ければ何もしない。消した数を返す。
        """
        if not self.temp_dir:
            return 0
        folder = Path(self.temp_dir) / UPLOAD_SUBFOLDER
        if not folder.is_dir():
            return 0
        removed = 0
        for path in folder.glob("*"):
            try:
                path.unlink()
                removed += 1
            except OSError:                          # noqa: BLE001
                pass
        return removed

    def _upload(self, image_path: str | Path, name: str) -> str:
        """`POST /upload/image` で **`temp` に複製**を作り、`LoadImage` に渡す参照を返す（点検 A-2）。

        `input/` に置くと 1 万枚で 10 GB 残るので **`temp`**（G-6-(a)）。ComfyUI に消す口は無いので、
        **再起動で消えるのに任せる**（消えなければ開始時に空にする運用。§10-21）。
        """
        boundary = "----image-reviewer" + uuid.uuid4().hex
        path = Path(image_path)
        body = io.BytesIO()

        def field(key: str, value: str) -> None:
            body.write(f"--{boundary}\r\n".encode())
            body.write(f'Content-Disposition: form-data; name="{key}"\r\n\r\n'.encode())
            body.write(str(value).encode())
            body.write(b"\r\n")

        body.write(f"--{boundary}\r\n".encode())
        body.write(f'Content-Disposition: form-data; name="image"; filename="{name}.png"\r\n'.encode())
        body.write(b"Content-Type: image/png\r\n\r\n")
        body.write(path.read_bytes())
        body.write(b"\r\n")
        field("type", "temp")
        field("subfolder", UPLOAD_SUBFOLDER)
        field("overwrite", "true")
        body.write(f"--{boundary}--\r\n".encode())

        got = _http_json(self.base + "/upload/image", body.getvalue(),
                         headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
                         timeout=120.0)
        stored = (got or {}).get("name") or f"{name}.png"
        subfolder = (got or {}).get("subfolder") or UPLOAD_SUBFOLDER
        return f"{subfolder}/{stored} [temp]"

    def _graph(self, image_ref: str) -> dict:
        if self.node == "wd14":
            tagger = {
                "class_type": "WD14Tagger|pysssss",
                "inputs": {"image": ["1", 0], "model": self.model,
                           "threshold": self.threshold,
                           "character_threshold": self.character_threshold,
                           # **`replace_underscore=false`**（正規形 `long_hair` が返る。§0.5）
                           "replace_underscore": False, "trailing_comma": False,
                           "exclude_tags": ""},
            }
        else:
            tagger = {
                "class_type": "IllustTagger",
                "inputs": {"image": ["1", 0], "model": self.model,
                           "threshold": self.threshold,
                           "character_threshold": self.character_threshold},
            }
        return {"1": {"class_type": "LoadImage", "inputs": {"image": image_ref}}, "2": tagger}

    def _submit(self, image_ref: str) -> str:
        got = _http_json(self.base + "/prompt",
                         json.dumps({"prompt": self._graph(image_ref),
                                     "client_id": self.client_id}).encode(),
                         headers={"Content-Type": "application/json"}, timeout=60.0)
        prompt_id = (got or {}).get("prompt_id")
        if not prompt_id:
            raise ReviewError(502, "ComfyUI が prompt_id を返しません", details={"got": got})
        return str(prompt_id)

    def _wait(self, prompt_id: str, *, timeout: float = 300.0, poll: float = 0.05) -> dict:
        """`/history/{id}` を短い間隔で見る（§0.5）。

        **P4-1 の監査 C-1**: 以前は 0.5 秒ごとで、1 枚あたり**平均 0.45 秒の空き**があった
        （API 経由の実測 0.72 s/枚 対 ノード単体 0.26〜0.31 s/枚。10,000 枚で約 1.2 時間の純粋な待ち）。
        0.05 秒に詰めた（**測ってから決める**: `tools/probe_p4.py` が 1 枚あたりの時間を出す）。

        **P4-2 の監査 B-1**: 通信の失敗（`OSError` / `URLError` / 時間切れ）は**待ち直す**。
        模型の読み込み中は ComfyUI が詰まって `/history` の接続が落ちる（実測 `WinError 10060`）。
        """
        import time

        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                got = _http_json(f"{self.base}/history/{prompt_id}", timeout=30.0) or {}
            except OSError:
                # **P4-2 の監査 B-1**: 模型の読み込みで ComfyUI が詰まると `/history` の接続が
                # 落ちる（実測 WinError 10060）。**待ち直す**（500 を返さない）
                time.sleep(poll)
                continue
            entry = got.get(prompt_id)
            if entry:
                status = (entry.get("status") or {})
                if status.get("status_str") == "error":
                    raise ReviewError(502, "ComfyUI がエラーを返しました",
                                      details={"messages": status.get("messages")})
                outputs = entry.get("outputs") or {}
                if outputs:
                    return outputs
            time.sleep(poll)
        raise ReviewError(504, "ComfyUI の応答が時間内に返りません",
                          details={"prompt_id": prompt_id})

    def _parse(self, outputs: dict) -> list[tuple[str, float | None]]:
        """**ノード番号を決め打ちしない**（`scores` / `tags` を持つ出力を探す。§0.5）。"""
        for node in outputs.values():
            if not isinstance(node, dict):
                continue
            scores = node.get("scores")
            if scores:
                payload = scores[0] if isinstance(scores, list) else scores
                if isinstance(payload, str):
                    payload = json.loads(payload)
                return [(normalize_name(name), float(score)) for name, score in payload]
            tags = node.get("tags")
            if tags:
                text = tags[0] if isinstance(tags, list) else tags
                return [(normalize_name(part), None) for part in str(text).split(",") if part.strip()]
        raise ReviewError(502, "ComfyUI の出力に語がありません", details={"outputs": list(outputs)})


# ---- 方式の検出と選択（§0.4）----


def settings_of(con) -> dict:
    """`settings` 表の `tagger.*` を読む（無ければ既定）。"""
    got: dict[str, str] = {}
    try:
        for row in con.execute("SELECT key, value FROM settings WHERE key LIKE 'tagger.%'"):
            got[row["key"]] = row["value"]
    except Exception:                                    # noqa: BLE001  表が無い環境でも既定で動く
        pass

    def number(key: str, default: float) -> float:
        try:
            return float(got.get(key, default))
        except (TypeError, ValueError):
            return default

    return {
        "engine": got.get("tagger.engine", DEFAULT_ENGINE),
        "model": got.get("tagger.model", DEFAULT_MODEL),
        "node": got.get("tagger.node", DEFAULT_NODE),
        "threshold": number("tagger.threshold", DEFAULT_THRESHOLD),
        "character_threshold": number("tagger.character_threshold", DEFAULT_CHARACTER_THRESHOLD),
        "comfyui": got.get("tagger.comfyui", DEFAULT_COMFYUI),
        # ComfyUI の `temp` の絶対パス（任意）。**入れておくと、投げた複製を消す**
        # （P4-1 の監査 C: `temp/image-reviewer` に 53 枚 19 MB が残っていた）。
        # 未設定なら消さない（ComfyUI の再起動で消えるのに任せる）
        "comfyui_temp": got.get("tagger.comfyui_temp") or None,
        "onnx_path": got.get("tagger.onnx_path") or None,
        "csv_path": got.get("tagger.csv_path") or None,
    }


def detect(settings: dict) -> dict:
    """使える方式を調べる（**job を作る前に呼ぶ**。§0.4）。"""
    report: dict[str, dict] = {}

    # 内蔵: onnxruntime が入っていて、モデルと CSV があるか
    onnx_path, csv_path = find_onnx(settings.get("onnx_path")), find_csv(settings.get("csv_path"))
    if onnx_path is None:
        report["builtin"] = {"available": False, "reason": "モデル（onnx）が見つかりません"}
    elif csv_path is None:
        report["builtin"] = {"available": False, "reason": "語彙（CSV）が見つかりません"}
    else:
        try:
            import onnxruntime                              # noqa: F401  入っているかだけ見る
        except Exception:                                   # noqa: BLE001
            report["builtin"] = {"available": False, "reason": "onnxruntime がありません"}
        else:
            report["builtin"] = {"available": True, "reason": None,
                                 "onnx": str(onnx_path), "csv": str(csv_path)}

    # ComfyUI: 繋がるか
    client = ComfyTagger(settings["comfyui"], node=settings["node"], model=settings["model"],
                         threshold=settings["threshold"],
                         character_threshold=settings["character_threshold"])
    ok = client.ping()
    report["comfyui"] = {"available": ok, "reason": None if ok else "つながりません",
                         "url": settings["comfyui"], "node": settings["node"]}
    return report


def choose(requested: str, report: dict) -> str:
    """使う方式を決める（§0.4）。**どちらも使えなければ 409 で job を作らない。**"""
    if requested not in ENGINES:
        raise ReviewError(422, "engine は auto | builtin | comfyui のいずれかです",
                          details={"engine": "auto | builtin | comfyui"})
    if requested != "auto":
        if not report.get(requested, {}).get("available"):
            raise ReviewError(409, f"{requested} のタガーが使えません", code="tagger_unavailable",
                              details={requested: report.get(requested, {}).get("reason")})
        return requested
    for candidate in ("builtin", "comfyui"):
        if report.get(candidate, {}).get("available"):
            return candidate
    raise ReviewError(409, "使えるタガーがありません", code="tagger_unavailable",
                      details={name: info.get("reason") for name, info in report.items()})


def build(store, settings: dict, engine: str):
    """方式に応じたタガーを作る（`choose` の後で呼ぶ）。"""
    if engine == "builtin":
        return BuiltinTagger(find_onnx(settings.get("onnx_path")), find_csv(settings.get("csv_path")),
                             threshold=settings["threshold"],
                             character_threshold=settings["character_threshold"],
                             model=settings["model"])
    return ComfyTagger(settings["comfyui"], node=settings["node"], model=settings["model"],
                       threshold=settings["threshold"],
                       character_threshold=settings["character_threshold"],
                       temp_dir=settings.get("comfyui_temp"))


def describe(report: dict) -> str:
    """`doctor` と起動時のログに出す 1 行（点検 B-2 の「実際の provider」を必ず含める）。"""
    builtin = report.get("builtin", {})
    comfyui = report.get("comfyui", {})
    left = f"内蔵タガー: {'使えます' if builtin.get('available') else builtin.get('reason')}"
    right = (f"ComfyUI のタガー: {comfyui.get('node')}（{comfyui.get('url')}）"
             + ("で使えます" if comfyui.get("available") else "につながりません"))
    return f"{left} / {right}"
