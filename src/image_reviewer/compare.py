"""比較の基本（P5-2）— 並べるための材料を**サーバ側で 1 回**作る。

設計: docs/p5-design.md §0.1（P5-2 の範囲）・§0.6（点検 C5 の鍵）・§0.8（C10・D5）・
      §5.3（比較の画面）・§6.1（差分表）、
      docs/comparison.md §2.1（並べる）・§3.1（表の作り方）・§3.2（正規化）・§6（操作）

守ること（どれも点検・監査の指摘が理由）:
- **差分はここだけで計算する**（設計 §10-4）。画面は返ってきた行を描くだけ。
  どのセルが違うか（`cells`）も**サーバが決める**ので、画面は突き合わせをしない
- 鍵は `png_meta.analyze_graph()` が返す欄から作る（**発明しない**）。設計 §6.1 の列挙に
  点検 C5 の 5 つ（`negative_literal` / `init_image` / `textgen_params` / `node_types` /
  `final_prompt_source`）を足したものが `COMPARE_KEYS`
- `clip_skip` は **`png_meta.py` が読んでいない**ので鍵に入れない（設計 §0.6。
  要るなら `png_meta.py` の変更を P5-3 以降に含める）
- **正規化は 2 段**（点検 G5。`comparison.md` §3.2 の正規化から「重みの表記を同一視する」を外す）:
  段 1 = **語の同一性**（大小文字・`_` と空白・空白の詰め・末尾のカンマ）、
  段 2 = **値の比較**（重み）。`(word:1.2)` と `word` は `same` ではなく **`reweighted`**
- **語順だけの違いは `moved`**（C10。追加＋削除に割らない）。差分は LCS（`difflib`）
- `width` / `height` は**実体の画素数**（点検 C5。`EmptyLatentImage` は img2img で `null` になる）
- `tags` は `[]` ではなく **`null`**（点検 D5。「未計算」と「無い」を区別する。P4 で埋まる）
- **監査 B1**: 語の union（`_union_tokens`）は `diff_sequence`（LCS）を**画像ごとに 1 回**しか
  呼ばない。`build_prompt_diff()` が計算した `item_states` を受け取る（呼び直すと
  語数² × 画像数 になり、設計 §8 の 30ms が語数 60 あたりで破れる）
- **監査 B2**: **捕獲できていない英訳を「前置語だけ」で `final_prompt` の値にしない。**
  `final_prompt_source == "reconstructed"` で訳が無い枚は `final_prompt=None` ＋
  `final_prompt_unknown=True` とし、表の行は `same` ではなく **`unknown`（全部）/
  `incomplete`（一部）** を返す。分かっている前置語は `known_prefix` に別に出す
- **pHash / dHash / SSIM / `changed_fraction` / `mean_abs` / 差分ヒートマップ / 似ている順 /
  `comparison_cache` は P5-3**（このファイルの後半）。定義は
  [`comparison.md`](../docs/comparison.md) §4 が正で、**ここで再定義しない**（参照する）
- **監査 A2**: 位置合わせは「峰が立ったか」だけでは足りない（無関係な 2 枚でも峰は立つ。
  実測は §0.7）。**合わせた重なりの一致度**（`_aligned_corr()` ≧ `ALIGN_MIN_CORR`）まで見て、
  下回る組は**画像を返さず**「位置が合いません」を返す（`comparison.md` §2.3「黙って誤魔化さない」）
- **監査 B1**: `compare_assets()` は文書を組む前に、**錠の外で**足りない pHash / dHash だけを
  埋める（`ensure_hashes()`。最大 `MAX_COMPARE_IDS` 枚 × 約 14 ms。1 枚につき生涯 1 回）。
  これが無いと初回の文書にハッシュが乗らず、似ている順の距離も出ない（起動時の全件は走らせない）
- 枚数の上限: **比較の画面の上限として 8 枚**（`comparison.md` §2.1 のレイアウト表が 2〜8 枚）。
  **まとまりの枚数の上限ではない**（点検 B6/G8）ので、9 枚以上は `ids=` で 8 枚ずつ渡す
"""

from __future__ import annotations

import base64
import collections
import difflib
import functools
import io
import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Sequence

import numpy as np
from PIL import Image

from . import db
from .review import ReviewError
from .store import Store

log = logging.getLogger(__name__)

# 比較の画面の上限（`comparison.md` §2.1 のレイアウトが 2〜8 枚）。
# **まとまりの枚数の上限ではない**（点検 B6/G8）。
MAX_COMPARE_IDS = 8
# 文字単位の差分を回す上限（日本語原文が長いときの保険。超えたら文字単位は省く）
MAX_CHAR_DIFF = 2000
# 語単位の差分を回す上限（**1 画像の語数**。超えたら語の差分を省く。監査 B1 の提案）。
# 語の LCS は語数の積で効くので、上限が無いと長いプロンプトで応答が秒単位になる。
# 行の値（生の文字列）は残るので「分からない」にはならない（`prompt_diff["too_long"]` を見る）。
MAX_PROMPT_WORDS = 2000
_EPS = 1e-9
_NUMBER_RE = re.compile(r"^[+-]?(?:\d+\.?\d*|\.\d+)$")
_LORA_RE = re.compile(r"^<lora:(?P<name>[^:>]+)(?::(?P<w>[+-]?(?:\d+\.?\d*|\.\d+)))?>$", re.I)
_SEPARATORS = ",、\n\r"
_SENTENCE_END = "。！？!?"

# ---- P5-3 の定数（`comparison.md` §2.3・§4 の値をここに 1 回だけ書く）----

# **点検 D1**: 縮小のフィルタや指標の式を変えたら `comparison_cache` を全部無効にする。
# `cached_pair_metrics()` は**引くときもこの値を条件に入れる**ので、上げれば必ず外れる。
ALGO_VERSION = 1
# 指標に使う縮小の長辺（`comparison.md` §4: 256px）
METRIC_SIZE = 256
# 「近い」のしきい値（`comparison.md` §4 の初期値: pHash 距離 ≤ 6）。
# 実データで調整する前提の**未調整の初期値**なので、動かすときはここ 1 か所を直す。
PHASH_NEAR_THRESHOLD = 6
# 差分ヒートマップを**自動で**出す距離（点検 G6。`comparison.md` §2.3 の 3 番目の条件）。
# `comparison.md` §2.3 は「知覚ハッシュ距離がしきい値以下」としか書かないので、
# §4 の「近い」の初期値と同じ値を使う（別の値を発明しない）。
HEATMAP_DISTANCE_THRESHOLD = PHASH_NEAR_THRESHOLD
# `changed_fraction` の閾値（`comparison.md` §4: **増幅前**の絶対差が 8 を超えた画素）
CHANGED_THRESHOLD = 8
# 赤の増幅（`comparison.md` §2.3 の手順 3: 3 倍。**表示だけ**で指標には掛けない）
HEATMAP_AMPLIFY = 3
# 位置合わせ（平行移動だけ。`comparison.md` §2.3 の手順 2・§8-1）
# 256px の縮小での上限。これを超えるずれは「位置が合いません」と出す（黙って誤魔化さない）
ALIGN_MAX_SHIFT = 64
# **監査 A2（実測は `docs/p5-design.md` §0.7）**: 位相相関は正規化した相互パワースペクトル
# （全周波数で振幅 1）の逆 FFT なので、全体のエネルギーが 1 に固定される。だから
# **無関係な 2 枚**でも `max / mean(|corr|)` はノイズの最大値の比にしかならない
# （実データ 200 組で p50 5.66 / p90 7.12 / 最大 71.8）。**同じ seed の組は 5.14〜216.3** で
# この範囲と**重なる**ので、この比だけでは判別できない。前の値 1.5 はノイズの床より下で、
# 無関係な 2 枚でも決して発火しなかった（監査 A2 の指摘そのもの）。
# ここは「峰がノイズの床から十分に立っているか」の**足切り**だけに使い、判別は
# 「合わせた重なりが本当に一致しているか」（`ALIGN_MIN_CORR`）で行う。
ALIGN_MIN_PEAK_RATIO = 8.0
# **監査 A2**: 位置合わせした重なり（両方が実在する画素だけ）の正規化相互相関（-1〜1）。
# 「ずれを戻した後で実際に画素が一致しているか」を直接見る。実測（§0.7）:
# 無関係な 200 組は p90 0.205 / 最大 0.758、同じ絵の縮小・再圧縮は 0.949、
# ずらした写しは 1.000。**0.80 はこの間**（無関係の最大より上、同じ絵より下）。
# 下回る組は**画像を返さない**（`comparison.md` §2.3「黙って誤魔化さない」）。
ALIGN_MIN_CORR = 0.80
# 一致度を出すのに要る最小の重なり（画素）。これ未満は「分からない」＝合わせない
# （256px の縮小で 64px ずらしても 24,576 画素は残るので、実際は縦横比が違う組で効く）
ALIGN_MIN_OVERLAP = 1024
# SSIM の局所窓（`comparison.md` §4「局所平均・分散・共分散」）。
# 重なりの無い 8×8 のブロックで取る（窓をずらす実装より速く、判定には十分）
SSIM_WINDOW = 8
# ハッシュの形（`design.md` §5.1: 16 進 16 文字の小文字）
HASH_RE = re.compile(r"^[0-9a-f]{16}$")
# SSIM の定数（`comparison.md` §4 の定義には無いが、SSIM の標準値。式を 2 か所に書かない）
_SSIM_C1 = (0.01 * 255) ** 2
_SSIM_C2 = (0.03 * 255) ** 2


@dataclass(frozen=True)
class CompareKey:
    """差分表の 1 行。

    `key` は英語のタグ名（機械が読む名前）、`label` は画面に出す日本語
    （§0 の決定「日本語のラベル・英語のタグ名」。`p5-design.md` §6.1 の例は
    `label` に鍵と同じ文字列を置いているが、画面の言語は日本語なので表示名を入れる）。
    """

    key: str
    label: str
    kind: str          # text / num / list / set / params / prompt / ja
    where: str         # provenance / prompts


COMPARE_KEYS: tuple[CompareKey, ...] = (
    # ---- 来歴（`png_meta.analyze_graph()` の欄）----
    CompareKey("model", "モデル", "text", "provenance"),
    CompareKey("loras", "LoRA", "list", "provenance"),
    CompareKey("clip", "テクストエンコーダ", "text", "provenance"),
    CompareKey("llm", "LLM", "text", "provenance"),
    CompareKey("vae", "VAE", "text", "provenance"),
    CompareKey("sampler", "サンプラ", "text", "provenance"),
    CompareKey("scheduler", "スケジューラ", "text", "provenance"),
    CompareKey("steps", "steps", "num", "provenance"),
    CompareKey("cfg", "cfg", "num", "provenance"),
    CompareKey("denoise", "denoise", "num", "provenance"),
    CompareKey("width", "幅", "num", "provenance"),               # 点検 C5: 実体の画素数
    CompareKey("height", "高さ", "num", "provenance"),            # 点検 C5: 実体の画素数
    CompareKey("seed", "seed", "text", "provenance"),
    CompareKey("init_image", "元画像", "text", "provenance"),      # 点検 C5
    CompareKey("node_types", "ノード", "set", "provenance"),       # 点検 C5（集合の差で比べる）
    CompareKey("textgen_params", "翻訳の設定", "params", "provenance"),  # 点検 C5
    # 監査 G4（実行込みのやり直し）: 訳し直しの条件そのもの。差分表に出さないと
    # 「なぜ訳が変わったか」を追えない（`analyze_graph()` が既に返している値）
    CompareKey("textgen_system_prompt", "翻訳の指示", "prompt", "provenance"),
    CompareKey("en_source", "英訳の出所", "text", "provenance"),
    # ---- プロンプト ----
    CompareKey("final_prompt", "最終プロンプト", "prompt", "prompts"),
    CompareKey("final_prompt_source", "最終プロンプトの出所", "text", "prompts"),  # 点検 C5
    CompareKey("negative_literal", "ネガティブ", "prompt", "prompts"),             # 点検 C5
    CompareKey("en_text", "英訳", "prompt", "prompts"),
    CompareKey("ja_text", "日本語原文", "ja", "prompts"),
)

KEY_BY_NAME: dict[str, CompareKey] = {k.key: k for k in COMPARE_KEYS}

# `prompt_diff` が詳しく見せる鍵（C10 の基準つきの差分）。
PROMPT_DIFF_KEY = "final_prompt"

# 監査 B2: 「値が分からない」を `same` / `changed` と言わないための欄。
# 鍵 → `asset_item()` の `prompts` に入れた印の欄。
_UNKNOWN_FIELD = {"final_prompt": "final_prompt_unknown"}
# 監査 B2: 分からないときに「何が分かっているか」を別に返す欄（鍵 → `prompts` の欄）。
# `values` に入れると**一部を全体に見せてしまう**ので、行の `known_prefix` に分けて出す。
_KNOWN_EXTRA = {"final_prompt": "concat_prefix"}


# ---- 段 1: 語の同一性（点検 G5 の 1 段目。`comparison.md` §3.2）----


def _squeeze(text: str) -> str:
    text = text.replace("_", " ")                       # `_` と空白（Danbooru の表記）
    text = re.sub(r"\s+", " ", text)                    # 空白・改行の詰め
    text = re.sub(r"\s*,\s*", ", ", text)               # カンマの前後の空白
    return text.strip()


def normalize_text(value: Any) -> str | None:
    """段 1: 大小文字・`_` と空白・空白・末尾のカンマを揃えた「語の同一性」。

    `None` と空文字は「無い」を表す `None` に寄せる（差分表の `only_in_some` の判定に使う）。
    """
    if value is None:
        return None
    text = _squeeze(str(value)).strip(",").strip()
    if not text:
        return None
    return text.casefold()


def normalize_number(value: Any) -> str | None:
    """数値の比較の鍵。`10` と `10.0` を同じにする（表示は `_num_text` が元の型を保つ）。"""
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return str(value)
    try:
        num = float(value)
    except (TypeError, ValueError):
        return normalize_text(value)
    if num != num or num in (float("inf"), float("-inf")):     # NaN / inf は文字列として比べる
        return normalize_text(str(value))
    if num.is_integer():
        return str(int(num))
    return repr(num)


def _num_text(value: Any) -> str:
    """表示用。浮動小数はそのまま（`1.0` を `1` にしない）。"""
    if isinstance(value, float):
        return f"{value:g}" if value != int(value) else f"{value:.1f}"
    return str(value)


# ---- プロンプトの語（重みつき）----


def split_prompt(text: Any) -> list[str]:
    """プロンプトを語に割る。

    **括弧の中のカンマでは割らない**（`(a, b:1.2)` を 1 語として保つ）。
    文末（`.` の後が空白か行末 / `。` など）とカンマ・改行で割る。
    """
    chars = str(text or "")
    out: list[str] = []
    buf: list[str] = []
    depth = 0
    for i, ch in enumerate(chars):
        if ch == "(":
            depth += 1
        elif ch == ")" and depth:
            depth -= 1
        end_of_sentence = (ch in _SENTENCE_END
                           or (ch == "." and (i + 1 == len(chars) or chars[i + 1].isspace())))
        if depth == 0 and (ch in _SEPARATORS or end_of_sentence):
            part = "".join(buf).strip()
            if part:
                out.append(part)
            buf = []
            continue
        buf.append(ch)
    part = "".join(buf).strip()
    if part:
        out.append(part)
    return out


def _wrapped(text: str) -> bool:
    """全体が 1 組の括弧で囲われているか（`(a) (b)` を 1 語と見なさない）。"""
    if len(text) < 2 or not (text.startswith("(") and text.endswith(")")):
        return False
    depth = 0
    for i, ch in enumerate(text):
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0 and i != len(text) - 1:
                return False
    return depth == 0


@dataclass(frozen=True)
class Word:
    """プロンプトの 1 語。`base` が段 1（同一性）、`weight` が段 2（値）。"""

    base: str
    weight: float
    raw: str


def parse_weight(token: str) -> tuple[str, float]:
    """1 語から (本体, 重み) を取り出す。

    - `(word:1.2)` → `word` / 1.2
    - `((word))`   → `word` / 1.1^2（段数。`comparison.md` §3.2）
    - `<lora:name:0.8>` → `lora:name` / 0.8
    """
    text = token.strip()
    depth = 0
    while _wrapped(text):
        text = text[1:-1].strip()
        depth += 1
    weight = 1.1 ** depth if depth else 1.0
    got = re.match(r"^(?P<body>.+?):(?P<w>[+-]?(?:\d+\.?\d*|\.\d+))$", text)
    if got and _NUMBER_RE.match(got.group("w")):
        text, weight = got.group("body").strip(), float(got.group("w"))
    lora = _LORA_RE.match(text)
    if lora:
        text = f"lora:{lora.group('name')}"
        if lora.group("w"):
            weight = float(lora.group("w"))
    return text, weight


def prompt_words(text: Any) -> list[Word]:
    """プロンプトを語の列にする（段 1 の `base` と段 2 の `weight`）。"""
    out: list[Word] = []
    for token in split_prompt(text):
        body, weight = parse_weight(token)
        out.append(Word(normalize_text(body) or "", weight, token))
    return out


def _weight_text(weight: float) -> str:
    return _num_text(round(weight, 4))


# ---- 語順の差分（C10。追加＋削除に割らない）----


def diff_sequence(base_keys: Sequence[str],
                  item_keys: Sequence[str]) -> tuple[list[str], list[str]]:
    """(item 側の状態, base 側の状態) を返す。

    状態は `same` / `added` / `removed` / `moved`。**語順だけの違いは `moved`**
    （点検 C10。base で消えて item で現れた同じ語を「移動」にする。
    追加と削除に割ると、順番を入れ替えただけの差が 2 倍に見える）。
    """
    item_states = ["same"] * len(item_keys)
    base_states = ["same"] * len(base_keys)
    matcher = difflib.SequenceMatcher(None, list(base_keys), list(item_keys), autojunk=False)
    removed: list[int] = []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            continue
        if tag == "delete":
            for i in range(i1, i2):
                base_states[i] = "removed"
                removed.append(i)
            continue
        for j in range(j1, j2):
            item_states[j] = "added"
        if tag == "replace":
            for i in range(i1, i2):
                base_states[i] = "removed"
                removed.append(i)
    pool: dict[str, list[int]] = collections.defaultdict(list)
    for i in removed:
        pool[base_keys[i]].append(i)
    for j, state in enumerate(item_states):
        if state == "added" and pool.get(item_keys[j]):
            i = pool[item_keys[j]].pop(0)
            item_states[j] = "moved"
            base_states[i] = "moved"
    return item_states, base_states


def _char_runs(base: str, item: str) -> list[dict]:
    """文字単位の差分を、同じ状態が続く範囲（run）にまとめる（`comparison.md` §3.2）。"""
    runs: list[dict] = []

    def push(text: str, state: str) -> None:
        if not text:
            return
        if runs and runs[-1]["state"] == state:
            runs[-1]["t"] += text
        else:
            runs.append({"t": text, "state": state})

    matcher = difflib.SequenceMatcher(None, base, item, autojunk=False)
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            push(base[i1:i2], "same")
        elif tag == "delete":
            push(base[i1:i2], "removed")
        elif tag == "insert":
            push(item[j1:j2], "added")
        else:
            push(base[i1:i2], "removed")
            push(item[j1:j2], "added")
    return runs


def split_sentences(text: Any) -> list[str]:
    """日本語原文を文に割る（`comparison.md` §3.2 の「文単位 → 文字単位」の 1 段目）。"""
    out: list[str] = []
    buf: list[str] = []
    for ch in str(text or ""):
        if ch in "\r\n":
            part = "".join(buf).strip()
            if part:
                out.append(part)
            buf = []
            continue
        buf.append(ch)
        if ch in _SENTENCE_END:
            out.append("".join(buf).strip())
            buf = []
    part = "".join(buf).strip()
    if part:
        out.append(part)
    return out


# ---- 1 枚ぶんの材料（`p5-design.md` §6.1 の `items[]`）----


def _effective_final_prompt(meta: dict) -> tuple[str | None, bool]:
    """(実際に渡った最終プロンプト, 分からないか) を返す。

    **監査 B2**: `analyze_graph()` は英訳を捕獲していない再構成（`StringConcatenate`）のとき
    `final_prompt` を `None` にし、前置語（品質語）を `concat_prefix` に入れる。以前はここで
    前置語を `final_prompt` の値にしていたが、**前置語は最終プロンプトの一部**でしかない
    （後ろに翻訳文が続いていた。`textgen_params` の seed が違えば訳も違う）。実データでは
    英訳を持つ枚が 263 枚中 1 枚しかないので、前置語を値にすると **訳が違う 2 枚が「同じ」**
    と出て、捕獲した 1 枚と比べると訳文がまるごと「追加」に見える。

    そこで **捕獲できたときだけ値を返し、無いときは `(None, True)`**（分からない）にする。
    前置語は `asset_item()` が `prompts["concat_prefix"]` として別に返すので、画面は
    「分からない」と「何が分かっているか」を混ぜずに出せる。
    """
    got = meta.get("final_prompt")
    if isinstance(got, str) and got.strip():
        return got, False
    return None, True


def asset_item(asset: dict) -> dict:
    """`asset`（`Store.asset()` の形）から、比較の 1 列ぶんを作る。"""
    meta = asset.get("meta") or {}
    asset_id = asset["id"]
    provenance = {
        "model": meta.get("model"),
        "loras": meta.get("loras") or [],
        "clip": meta.get("clip"),
        "llm": meta.get("llm"),
        "vae": meta.get("vae"),
        "sampler": meta.get("sampler"),
        "scheduler": meta.get("scheduler"),
        "steps": meta.get("steps"),
        "cfg": meta.get("cfg"),
        "denoise": meta.get("denoise"),
        # 点検 C5: **実体の画素数**。`analyze_graph()` の `width` / `height` は
        # `EmptyLatentImage` から取るので img2img では `null` になる
        "width": asset.get("width"),
        "height": asset.get("height"),
        "seed": meta.get("seed"),
        "init_image": meta.get("init_image"),
        "node_types": dict(meta.get("node_types") or {}),
        "textgen_params": meta.get("textgen_params"),
        # 監査 G4: 訳し直しの条件（指示文と、英訳の出所）も差分の材料にする
        "textgen_system_prompt": meta.get("textgen_system_prompt"),
        "en_source": meta.get("en_source"),
    }
    final_prompt, final_prompt_unknown = _effective_final_prompt(meta)
    prompts = {
        "ja_text": meta.get("ja_text"),
        "en_text": meta.get("en_text"),
        "final_prompt": final_prompt,
        # 監査 B2: 「値が無い」を「同じ」と言わないための印（`_row()` / `build_prompt_diff()` が読む）
        "final_prompt_unknown": final_prompt_unknown,
        # 監査 B2: 分からないときに「何が分かっているか」（前置語だけ）を添える欄
        "concat_prefix": meta.get("concat_prefix"),
        "final_prompt_source": meta.get("final_prompt_source"),
        "negative_literal": meta.get("negative_literal"),
    }
    return {
        "asset_id": asset_id,
        # 並べる見方は 1024 サムネを使う（`comparison.md` §2.1。原本は開かない）
        "thumb": f"/api/assets/{asset_id}/thumb?size=1024",
        "thumb_small": f"/api/assets/{asset_id}/thumb?size=256",
        "provenance": provenance,
        "prompts": prompts,
        # 点検 D5: 「未計算」と「無い」を区別する。P4 で埋まる
        "tags": None,
        # P5-3: `asset` の列をそのまま写す（16 進 16 文字。未計算は `null`）。
        # 計算はサムネイルを作る復号と同じ 1 回（`thumbs.ensure_thumb` の `on_image`）
        "phash": asset.get("phash"),
        "dhash": asset.get("dhash"),
        "review_state": asset.get("review_state") or "unreviewed",
    }


# ---- 値・署名・表示 ----


def _raw_of(ck: CompareKey, item: dict) -> Any:
    """差分に使う生の値。空の入れ物・空文字は「無い」（`None`）に寄せる。"""
    raw = (item.get(ck.where) or {}).get(ck.key)
    if raw is None:
        return None
    if isinstance(raw, str):
        return raw if raw.strip() else None
    if isinstance(raw, (list, dict)) and not raw:
        return None
    return raw


def _lora_key(entry: Any) -> tuple:
    if not isinstance(entry, dict):
        return (normalize_text(entry), None, None)
    return (normalize_text(entry.get("name")),
            normalize_number(entry.get("strength_model")),
            normalize_number(entry.get("strength_clip")))


def _lora_text(entry: Any) -> str:
    if not isinstance(entry, dict):
        return str(entry)
    model = entry.get("strength_model")
    clip = entry.get("strength_clip")
    parts = [f"model {_num_text(model)}" if model is not None else "model —"]
    if clip is not None:
        parts.append(f"clip {_num_text(clip)}")
    return f"{entry.get('name') or '?'} ({' / '.join(parts)})"


def _param_text(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return _num_text(value)
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _param_key(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return normalize_number(value) or ""
    if isinstance(value, str):
        return normalize_text(value) or ""
    return normalize_text(_param_text(value)) or ""


def params_signature(params: dict) -> tuple:
    """`textgen_params` を 1 本の正規化した行にする（点検 C5）。"""
    return tuple((str(k), _param_key(params[k])) for k in sorted(params))


def params_line(params: dict) -> str:
    return ", ".join(f"{k}={_param_text(params[k])}" for k in sorted(params))


def _signature(ck: CompareKey, raw: Any):
    """段 1 と段 2 まで込めた比較の鍵。"""
    if ck.kind == "num":
        return normalize_number(raw)
    if ck.kind == "list":
        # `None`（重みなし）が混ざっても落ちないように `repr` で並べる
        return tuple(sorted((_lora_key(x) for x in raw), key=repr))
    if ck.kind == "set":
        return frozenset(raw.keys())
    if ck.kind == "params":
        return params_signature(raw)
    if ck.kind == "prompt":
        return tuple((w.base, round(w.weight, 6)) for w in prompt_words(raw))
    if ck.kind == "ja":
        return tuple(normalize_text(s) for s in split_sentences(raw))
    return normalize_text(raw)


def _word_signature(ck: CompareKey, raw: Any):
    """段 1 だけの鍵（重みを無視）。`reweighted` の判定に使う（点検 G5）。"""
    if ck.kind == "prompt":
        return tuple(w.base for w in prompt_words(raw))
    return _signature(ck, raw)


def _display(ck: CompareKey, raw: Any) -> str | None:
    if raw is None:
        return None
    if ck.kind == "num":
        return _num_text(raw)
    if ck.kind == "list":
        return ", ".join(_lora_text(x) for x in raw)
    if ck.kind == "set":
        return ", ".join(sorted(raw))
    if ck.kind == "params":
        return params_line(raw)
    return str(raw)


def _row(ck: CompareKey, items: list[dict], base_index: int) -> dict:
    """1 行ぶんの差分。`values`（表示）と `cells`（どの列が違うか）をサーバが決める。"""
    raws = [_raw_of(ck, item) for item in items]
    present = [raw is not None for raw in raws]
    signatures = [_signature(ck, raw) if raw is not None else None for raw in raws]
    # 監査 B2: 値が無いことを「同じ」と言わない印（`final_prompt` が持つ）
    unknown_field = _UNKNOWN_FIELD.get(ck.key)
    unknown = ([bool((item.get(ck.where) or {}).get(unknown_field)) for item in items]
               if unknown_field else [False] * len(items))

    if unknown_field and any(unknown):
        # 1 枚でも分からなければ「同じ」とは言えない。全部なら `unknown`、一部なら
        # `incomplete`（どちらも `state != "same"` なので `changed` 側に返る＝既定で見える）
        state = "unknown" if all(unknown) else "incomplete"
    elif not any(present):
        state = "same"
    elif not all(present):
        state = "only_in_some"
    elif len({_hashable(s) for s in signatures}) == 1:
        state = "same"
    elif ck.kind in ("prompt",) and len({_hashable(_word_signature(ck, raw))
                                        for raw in raws}) == 1:
        # 点検 G5: 語は同じで重みだけ違う → `same` ではなく `reweighted`
        state = "reweighted"
    else:
        state = "changed"

    base_sig = signatures[base_index] if 0 <= base_index < len(items) else None
    cells = []
    for raw, sig, is_unknown in zip(raws, signatures, unknown):
        if is_unknown:
            cells.append("unknown")
        elif state in ("unknown", "incomplete"):
            # 監査 B2: 分からない枚が混ざっている行では、分かっている枚を**基準と比べない**
            # （比べられない相手との差を「違い」とも「同じ」とも言わない。行の印で伝える）
            cells.append("missing" if raw is None else "same")
        elif raw is None:
            cells.append("missing")
        elif state == "same":
            cells.append("same")
        elif base_sig is None or _hashable(sig) != _hashable(base_sig):
            cells.append("reweighted" if state == "reweighted" else "changed")
        else:
            cells.append("same")

    row = {
        "key": ck.key,
        "label": ck.label,
        "kind": ck.kind,
        "state": state,
        "values": [_display(ck, raw) for raw in raws],
        "cells": cells,
    }
    if unknown_field and any(unknown):
        # 監査 B2: どの画像が分からないかを応答で言う（画面は「分からない」と出す）
        row["unknown"] = [item["asset_id"] for item, flag in zip(items, unknown) if flag]
        extra_field = _KNOWN_EXTRA.get(ck.key)
        if extra_field:
            known = {}
            for item, flag in zip(items, unknown):
                if flag:
                    value = (item.get(ck.where) or {}).get(extra_field)
                    if isinstance(value, str) and value.strip():
                        known[item["asset_id"]] = value
            if known:
                # 分かっているのは**前置語だけ**（値を `values` に混ぜない。監査 B2）
                row["known_prefix"] = known
    if ck.kind == "set":
        # 点検 C5: `node_types` は**集合の差**で見る（共通部分に無い型を列に出す）
        common: set = set(items[0]["provenance"]["node_types"]) if items else set()
        for item in items:
            common &= set(item["provenance"]["node_types"])
        row["only_in"] = {item["asset_id"]: sorted(set(item["provenance"]["node_types"]) - common)
                          for item in items}
    return row


def _hashable(value):
    """集合・タプルの混ざった署名を `set()` に入れられる形にする。"""
    if isinstance(value, (set, frozenset)):
        return tuple(sorted(value))
    if isinstance(value, tuple):
        return tuple(_hashable(v) for v in value)
    if isinstance(value, list):
        return tuple(_hashable(v) for v in value)
    return value


# ---- プロンプトの差分（C10: 基準を必ず持たせる）----


def build_prompt_diff(items: list[dict], base_index: int,
                      key: str = PROMPT_DIFF_KEY) -> dict:
    """`{"base": ..., "per_asset": {...}}` を持つ語単位の差分（点検 C10）。

    `per_asset[asset_id]` は**その画像の語**を、基準（`base`）に対する状態つきで並べる。
    状態は `same` / `added` / `removed` / `moved`。`moved` は「語順だけの違い」で、
    追加＋削除には割らない。`tokens` は全画像をまとめた union の見方（`p5-design.md` §6.1）。

    **監査 B1**: 画像ごとの `diff_sequence`（LCS）はここで 1 回だけ回し、その結果を
    `_union_tokens()` に渡す（渡さないと union が語ごとに回し直して O(語数² × 画像数) になる）。
    **監査 B2**: 最終プロンプトが分からない枚は語を「差分」にせず、`unknown` に id を並べる。
    """
    ck = KEY_BY_NAME.get(key) or CompareKey(key, key, "prompt", "prompts")
    values = [_raw_of(ck, item) for item in items]
    words = [prompt_words(raw) if raw is not None else [] for raw in values]
    ids = [item["asset_id"] for item in items]
    base_words = words[base_index]
    base_weights = {}
    for word in base_words:
        base_weights.setdefault(word.base, word.weight)
    unknown_field = _UNKNOWN_FIELD.get(key)
    unknown = ([bool((item.get(ck.where) or {}).get(unknown_field)) for item in items]
               if unknown_field else [False] * len(items))
    # 監査 B2: 基準の最終プロンプトが分からないと、他の枚の語を「追加」と言えない
    # （捕獲した 1 枚と比べて訳文がまるごと「追加」に見えたのと同じ形が、基準が逆でも起きる）
    base_unknown = bool(unknown[base_index]) if unknown else False
    # 監査 B1: 語数の上限（1 画像）。超えたら語単位の差分は省く（行の生の文字列は残る）
    too_long = bool(words) and max(len(ws) for ws in words) > MAX_PROMPT_WORDS

    per_asset: dict[str, list[dict]] = {}
    item_states: dict[int, list[str]] = {}
    words_equal = True
    weights_equal = True
    for index, item in enumerate(items):
        if index == base_index:
            # 基準そのものは全部 `same`（比べる相手は他の画像）
            per_asset[item["asset_id"]] = [{"t": w.raw, "state": "same"} for w in base_words]
            continue
        if unknown[index] or too_long or base_unknown:
            # 監査 B2: 分からない枚の語を「追加 / 削除」にしない（比べられない）。
            # 基準が分からないときは、**分かっている枚の語をそのまま並べるだけ**にする
            per_asset[item["asset_id"]] = (
                [] if (unknown[index] or too_long)
                else [{"t": w.raw, "state": "unknown"} for w in words[index]])
            words_equal = False
            continue
        states, _base_states = diff_sequence(
            [w.base for w in base_words], [w.base for w in words[index]])
        item_states[index] = states
        if any(state != "same" for state in states):
            words_equal = False
        entries = []
        for word, state in zip(words[index], states):
            entry: dict = {"t": word.raw, "state": state}
            if state == "same":
                want = base_weights.get(word.base)
                if want is not None and abs(want - word.weight) > _EPS:
                    entry["w"] = _weight_text(word.weight)
                    entry["base_w"] = _weight_text(want)
                    weights_equal = False
            elif word.weight != 1.0:
                entry["w"] = _weight_text(word.weight)
            entries.append(entry)
        per_asset[item["asset_id"]] = entries
        if len(words[index]) != len(base_words):
            words_equal = False
    if any(unknown):
        # 語も重みも「同じ」とは言えない（分からない枚がある。監査 B2）
        words_equal = False
        weights_equal = False
    tokens = [] if too_long else _union_tokens(items, words, ids, base_index,
                                               item_states, unknown)
    out = {
        "key": key,
        "base": ids[base_index],
        "per_asset": per_asset,
        "tokens": tokens,
        # 段 1（語）まで同じか / 段 2（重み）まで同じか（点検 G5）
        "words_equal": words_equal,
        "normalized_equal": words_equal and weights_equal,
        "reweighted": words_equal and not weights_equal,
    }
    if any(unknown):
        out["unknown"] = [ids[i] for i, flag in enumerate(unknown) if flag]
    if too_long:
        out["too_long"] = True
    return out


def _union_tokens(items: list[dict], words: list[list[Word]], ids: list[str],
                  base_index: int, item_states: dict[int, list[str]],
                  unknown: list[bool]) -> list[dict]:
    """全画像をまとめた語の見方（`p5-design.md` §6.1 の `tokens`）。

    基準の語順を先に、そのあと他の画像にだけ現れた語を画像の順で並べる。

    **監査 B1**: `item_states` は `build_prompt_diff()` が画像ごとに 1 回だけ計算した
    `diff_sequence` の結果（添字 → その画像の語の状態）。以前はここで**基準の語ごとに
    全画像ぶん `diff_sequence` を呼び直して**いた（O(語数² × 画像数)。語数 60 で §8 の 30ms を
    超え、200 語では秒に近づいた）。
    **監査 B2**: 最終プロンプトが分からない枚は「その語を持っていない」ではないので、
    削除 / 追加の根拠にせず、`assets` にも入れない。
    """
    base_words = words[base_index]
    has = [{w.base for w in ws} for ws in words]
    known = [not flag for flag in unknown]
    base_known = known[base_index] if base_index < len(known) else True
    states: dict[str, str] = {}
    for word in base_words:
        if word.base in states:
            continue
        # 分からない枚は「無い」ではない（監査 B2）
        if not all(word.base in got for i, got in enumerate(has) if known[i]):
            states[word.base] = "removed"
            continue
        moved = False
        for index in range(len(items)):
            if index == base_index:
                continue
            for w, state in zip(words[index], item_states.get(index) or []):
                if w.base == word.base and state == "moved":
                    moved = True
        states[word.base] = "moved" if moved else "same"
    out: list[dict] = []
    seen: set[str] = set()
    order: list[Word] = list(base_words)
    for index in range(len(items)):
        if index == base_index:
            continue
        for word in words[index]:
            if word.base not in states:
                if not base_known:
                    # 基準が分からないので「追加」とは言えない（監査 B2）
                    states[word.base] = "unknown"
                else:
                    states[word.base] = "added" if word.base not in has[base_index] else "same"
            order.append(word)
    for word in order:
        if word.base in seen:
            continue
        seen.add(word.base)
        out.append({
            "t": word.raw,
            "state": states.get(word.base, "same"),
            # 分からない枚は「持っていない」ではなく「分からない」ので入れない（監査 B2）
            "assets": [ids[i] for i, got in enumerate(has) if got and known[i]],
        })
    return out


# ---- 日本語原文の差分（文単位 → 文字単位。`comparison.md` §3.2）----


def build_ja_diff(items: list[dict], base_index: int) -> dict:
    """`ja_text` の差分。文単位で見てから、変わった範囲を文字単位で見る。"""
    raw_values = [_raw_of(KEY_BY_NAME["ja_text"], item) for item in items]
    sentences = [[normalize_text(s) or "" for s in split_sentences(raw)] if raw else []
                 for raw in raw_values]
    ids = [item["asset_id"] for item in items]
    base_sentences = sentences[base_index]
    per_asset: dict[str, dict] = {}
    equal = True
    for index, item in enumerate(items):
        if index == base_index:
            per_asset[item["asset_id"]] = {
                "sentences": [{"t": t, "state": "same"} for t in base_sentences],
                "chars": []}
            continue
        if not base_sentences and not sentences[index]:
            # 両側とも空なら LCS は要らない（監査 B1: 呼び出し回数を語数に依らせない）
            per_asset[item["asset_id"]] = {"sentences": [], "chars": []}
            continue
        item_states, base_states = diff_sequence(base_sentences, sentences[index])
        if any(state != "same" for state in item_states):
            equal = False
        base_changed = "".join(t for t, state in zip(base_sentences, base_states)
                               if state != "same")
        item_changed = "".join(t for t, state in zip(sentences[index], item_states)
                               if state != "same")
        chars: list[dict] = []
        if len(base_changed) + len(item_changed) <= MAX_CHAR_DIFF:
            chars = _char_runs(base_changed, item_changed)
        per_asset[item["asset_id"]] = {
            "sentences": [{"t": t, "state": state}
                          for t, state in zip(sentences[index], item_states)],
            "chars": chars,
        }
    return {"base": ids[base_index], "per_asset": per_asset, "normalized_equal": equal}


# ---- 文書（`p5-design.md` §6.1 + C5/C10/G5/D5）----


def build_document(items: list[dict], *, base: str | None = None,
                   group: dict | None = None) -> dict:
    """比較の 1 文書。**純関数**（DB を触らない。テストと実データの点検に使う）。"""
    ids = [item["asset_id"] for item in items]
    if not ids:
        raise ReviewError(422, "比べる画像がありません")
    if base is None:
        base_index = 0                                   # 既定は入力順の先頭
    else:
        if base not in ids:
            raise ReviewError(422, "base が ids の中にありません",
                              details={"base": base, "ids": ids})
        base_index = ids.index(base)
    rows = [_row(ck, items, base_index) for ck in COMPARE_KEYS]
    changed = [row for row in rows if row["state"] != "same"]
    same = [row for row in rows if row["state"] == "same"]
    document: dict = {}
    if group is not None:
        document["group"] = group
    document.update({
        "base": ids[base_index],
        "ids": ids,
        "items": items,
        # P5-3: 似ている順（`comparison.md` §4.1）。画面は `order` の順に並べ替えるだけ。
        # 指標（SSIM など）は要求時に `pair_report()` で引く（ここでは復号しない）
        "nearest": nearest_order(items, base=ids[base_index]),
        # P5-3: 基準と各枚のヒートマップの可否（点検 G6 の規則を 1 か所で決める）
        "pairs": pair_rules(items, base_index),
        "diff": {
            # 違う行を先に、同じ行を畳んで返す（`p5-design.md` §6.1。画面の既定の見え方）
            "keys": [ck.key for ck in COMPARE_KEYS],
            "changed": changed,
            "same": same,
            "prompt_diff": build_prompt_diff(items, base_index),
            "ja_diff": build_ja_diff(items, base_index),
        },
    })
    return document


# ---- P5-3: pHash / dHash（`comparison.md` §4）----
#
# **定義は `comparison.md` §4 が正**（ここで再定義しない。同じ式を 2 か所に置かない）:
#   pHash: 32×32 グレースケール → DCT → 低周波 8×8 → 中央値で 2 値化
#   dHash: 9×8 グレースケール → 横方向の増減
# 保存は **16 進 16 文字の小文字の TEXT**（`design.md` §5.1。符号なし 64bit は
# SQLite の符号付き `INTEGER` に入らない）。ビットの並びは行優先（左上が最上位ビット）。
#
# **実測 F5**（`tools/probe_p5.py`）: 1 枚 11.88 ms のうち 11.35 ms が復号＋縮小で、
# 純 Python の DCT は 0.53 ms だった。だから pHash は**背景ジョブにしない**。
# サムネイルを作る復号（`thumbs.ensure_thumb` の `on_image`）に同居させる。


@functools.lru_cache(maxsize=1)
def _dct_matrix(n: int = 32) -> np.ndarray:
    """DCT-II の直交行列（`C[k, x]`）。1 回だけ作って使い回す。"""
    k = np.arange(n).reshape(-1, 1)
    x = np.arange(n).reshape(1, -1)
    scale = np.sqrt(1.0 / n) * np.where(np.arange(n) == 0, 1.0, np.sqrt(2.0))
    return scale.reshape(-1, 1) * np.cos(np.pi * (2 * x + 1) * k / (2 * n))


def _pack_bits(bits: np.ndarray) -> int:
    """真偽の並びを 1 つの整数にする（行優先。64bit なら 8 バイト）。"""
    return int.from_bytes(np.packbits(bits).tobytes(), "big")


def phash_bits(im: Image.Image) -> int:
    """`comparison.md` §4: 32×32 グレースケール → DCT → 低周波 8×8 → 中央値で 2 値化。

    中央値は **DC 成分も込めた 64 個**で取る（標準的な pHash と同じ）。
    """
    small = im.convert("L").resize((32, 32), Image.LANCZOS)
    block = np.asarray(small, dtype=np.float64)
    matrix = _dct_matrix()
    low = (matrix @ block @ matrix.T)[:8, :8]
    return _pack_bits((low > np.median(low)).reshape(-1))


def dhash_bits(im: Image.Image) -> int:
    """`comparison.md` §4: 9×8 グレースケール → 横方向の増減（64bit）。"""
    small = im.convert("L").resize((9, 8), Image.LANCZOS)
    gray = np.asarray(small, dtype=np.int16)
    return _pack_bits((gray[:, 1:] > gray[:, :-1]).reshape(-1))


def hash_hex(value: int) -> str:
    """16 進 16 文字の小文字（`design.md` §5.1）。"""
    return f"{value:016x}"


def hashes_of_image(im: Image.Image) -> tuple[str, str]:
    """復号済みの画像から (pHash, dHash)。**復号しない**（**実測 F5**）。"""
    return hash_hex(phash_bits(im)), hash_hex(dhash_bits(im))


def hash_file(src: str | Path) -> tuple[str, str]:
    """1 枚を復号して (pHash, dHash)。

    `Store` を通さない道（計測・実データの点検・サムネイルが既にある枚の 1 回だけの復号）。
    """
    with Image.open(src) as im:
        return hashes_of_image(im.convert("RGB"))


def hash_distance(a: str | None, b: str | None) -> int | None:
    """64bit のハミング距離。

    **点検 D1**: これはマイクロ秒で出るので `comparison_cache` に覚えない。
    どちらか欠けていれば `None`（0 と「分からない」を混ぜない）。
    """
    if not a or not b or not isinstance(a, str) or not isinstance(b, str):
        return None
    if not HASH_RE.match(a) or not HASH_RE.match(b):
        return None
    return (int(a, 16) ^ int(b, 16)).bit_count()


def capture_hashes(store: Store, asset_id: str, im: Image.Image) -> tuple[str, str] | None:
    """**復号済みの画像**からハッシュを作って `asset` に書く（復号しない）。

    既に入っていれば何もしない（サムネイルの要求のたびに書かない）。
    呼ぶ側は `thumbs.ensure_thumb(..., on_image=...)`（`app.py` のサムネイルの口）。

    **（P8-4）読み取り専用で開いているときは計算しない。** 壊れた DB を
    「読み取り専用で起動」する道では、書けないのに計算しても捨てるだけになる
    （`attempt to write a readonly database` を 500 にしない）。
    """
    if getattr(store, "read_only", False):
        return None
    with store.locked() as con:                       # 監査 B3: 未コミットの行を読まない
        row = con.execute("SELECT phash, dhash FROM asset WHERE id = ?", (asset_id,)).fetchone()
    if row is None:
        return None
    if row["phash"] and row["dhash"]:
        return (row["phash"], row["dhash"])
    got = hashes_of_image(im)
    store.set_hashes(asset_id, *got)
    return got


def ensure_hashes(store: Store, asset_id: str, src: str | Path) -> tuple[str, str] | None:
    """**サムネイルが既にある枚**の道（設計 §0.7 の「ハッシュだけ計算する」場合）。

    このときだけは復号を共有できないので、もう 1 回だけ復号する。1 枚につき 1 回で、
    次からは `asset.phash` があるので何もしない（復号の回数が増え続けない）。

    **（P8-4）読み取り専用のときは計算しない**（`capture_hashes` と同じ理由）。
    """
    if getattr(store, "read_only", False):
        return None
    with store.locked() as con:
        row = con.execute("SELECT phash, dhash FROM asset WHERE id = ?", (asset_id,)).fetchone()
    if row is None or (row["phash"] and row["dhash"]):
        return None
    got = hash_file(src)
    store.set_hashes(asset_id, *got)
    return got


# ---- P5-3: 256px の縮小と指標（`comparison.md` §4）----


def reduced_gray(src: str | Path, size: int = METRIC_SIZE) -> np.ndarray:
    """**長辺** `size` へ縮小したグレースケール（`comparison.md` §4 の縮小）。

    アスペクトは保つ（`Image.thumbnail`）。定義は 1 か所だけにする。
    """
    with Image.open(src) as im:
        gray = im.convert("L")
        gray.thumbnail((size, size), Image.LANCZOS)
        return np.array(gray, dtype=np.float64)      # 写しを取る（`im` を閉じても残る）


def _common_frame(a: np.ndarray, b: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """縦横比が違うと縮小後の形も違うので、重なる範囲だけを見る。"""
    h = min(a.shape[0], b.shape[0])
    w = min(a.shape[1], b.shape[1])
    return a[:h, :w], b[:h, :w]


def _blocks(x: np.ndarray, window: int) -> np.ndarray:
    """重なりの無い `window`×`window` のブロックに分ける（`(行, 列, window, window)`）。"""
    window = max(1, min(window, x.shape[0], x.shape[1]))
    h = (x.shape[0] // window) * window
    w = (x.shape[1] // window) * window
    return x[:h, :w].reshape(h // window, window, w // window, window).transpose(0, 2, 1, 3)


def ssim(a: np.ndarray, b: np.ndarray, *, window: int = SSIM_WINDOW) -> float:
    """`comparison.md` §4 の SSIM（256px の縮小 → 局所平均・分散・共分散）。

    **位置合わせはしない**（設計 §4 の手順に無い。ずれは SSIM が下がることで示す）。
    窓は重なりの無い 8×8 ブロック。同じ 2 枚なら 1.0 になる。
    """
    a2, b2 = _common_frame(a, b)
    ba, bb = _blocks(a2, window), _blocks(b2, window)
    mu_a, mu_b = ba.mean(axis=(2, 3)), bb.mean(axis=(2, 3))
    var_a, var_b = ba.var(axis=(2, 3)), bb.var(axis=(2, 3))
    cov = (ba * bb).mean(axis=(2, 3)) - mu_a * mu_b
    num = (2 * mu_a * mu_b + _SSIM_C1) * (2 * cov + _SSIM_C2)
    den = (mu_a ** 2 + mu_b ** 2 + _SSIM_C1) * (var_a + var_b + _SSIM_C2)
    return float(np.mean(num / den))


def diff_metrics(a: np.ndarray, b: np.ndarray) -> dict:
    """`changed_fraction` と `mean_abs`（`comparison.md` §4 の定義・**増幅前**の絶対差）。

    赤く重ねるときの 3 倍増幅（`HEATMAP_AMPLIFY`）は**ここには掛けない**。
    """
    a2, b2 = _common_frame(a, b)
    delta = np.abs(a2 - b2)
    return {
        "changed_fraction": float((delta > CHANGED_THRESHOLD).mean()),
        "mean_abs": float(delta.mean()),
    }


def compute_pair_metrics(a_src: str | Path, b_src: str | Path, *,
                         gray: tuple[np.ndarray, np.ndarray] | None = None) -> dict:
    """2 枚を復号して `ssim` / `changed_fraction` / `mean_abs` を出す。**DB を触らない**。

    `gray` を渡すと**その縮小を使う**（差分ヒートマップと同じ組では復号と縮小を 1 回で済ませる。
    実測では 1024² の 1 枚で復号＋縮小が 9.6 ms なので、2 回にするとそのまま倍になる）。
    差し替えられるように分けてある（キャッシュが効いているかをテストで数える）。
    """
    if gray is None:
        gray = (reduced_gray(a_src), reduced_gray(b_src))
    gray_a, gray_b = gray
    return {"ssim": ssim(gray_a, gray_b), **diff_metrics(gray_a, gray_b)}


def _primary_path(asset: dict) -> str | None:
    """実体の代表の場所。`app.py` の `_primary_path` と同じ規則（無い場所は使わない）。"""
    locs = [l for l in asset.get("locations") or [] if not l.get("missing_at")]
    if not locs:
        locs = list(asset.get("locations") or [])
    if not locs:
        return None
    locs.sort(key=lambda l: (not l.get("is_primary"), l["path"]))
    return locs[0]["path"]


def cached_pair_metrics(store: Store, a: dict, b: dict, *,
                        gray: tuple[np.ndarray, np.ndarray] | None = None) -> dict:
    """1 組の指標（256px へ縮小）。`comparison_cache` に覚える（設計 §6.2）。

    **監査 D1**: `phash_distance` は覚えない（64bit のハミング距離はマイクロ秒で出るので、
    書き込む方が高い）。距離は要求のたびに `hash_distance()` で出す。

    **監査 D3/B3**: 読みは `store.locked()`、書きは `store.transaction()` の下で行う
    （未コミットの行を読まない）。**復号と SSIM は錠の外**で行う（書き手を待たせない）。
    引くときは `algo_version` を必ず条件に入れる（縮小を変えたら全部無効）。

    `gray` は「もう縮小してある 2 枚」（差分ヒートマップと共有するため。`compute_pair_metrics` を見る）。
    """
    a_id, b_id = (a["id"], b["id"]) if a["id"] <= b["id"] else (b["id"], a["id"])
    with store.locked() as con:
        row = con.execute(
            "SELECT ssim, changed_fraction, mean_abs FROM comparison_cache"
            " WHERE a_id = ? AND b_id = ? AND algo_version = ?",
            (a_id, b_id, ALGO_VERSION),
        ).fetchone()
    if row is not None:
        return {"ssim": row["ssim"], "changed_fraction": row["changed_fraction"],
                "mean_abs": row["mean_abs"], "cached": True}

    a_src, b_src = _primary_path(a), _primary_path(b)
    if not a_src or not b_src:
        raise ReviewError(404, "実体が見つかりません（サムネイルも作れません）",
                          details={"a_id": a_id, "b_id": b_id})
    got = compute_pair_metrics(a_src, b_src, gray=gray)
    with store.transaction() as con:
        con.execute(
            "INSERT INTO comparison_cache(a_id, b_id, algo_version, ssim, changed_fraction,"
            " mean_abs, computed_at) VALUES (?,?,?,?,?,?,?)"
            " ON CONFLICT(a_id, b_id) DO UPDATE SET algo_version = excluded.algo_version,"
            " ssim = excluded.ssim, changed_fraction = excluded.changed_fraction,"
            " mean_abs = excluded.mean_abs, computed_at = excluded.computed_at",
            (a_id, b_id, ALGO_VERSION, got["ssim"], got["changed_fraction"], got["mean_abs"],
             db.now()),
        )
    return {**got, "cached": False}


# ---- P5-3: 差分ヒートマップ（`comparison.md` §2.3）----


def _same_seed(seed_a: Any, seed_b: Any) -> bool:
    """同じ seed か。**両方に値があるときだけ** True（「無い」を「同じ」と言わない）。"""
    if seed_a is None or seed_b is None:
        return False
    return str(seed_a) == str(seed_b)


def heatmap_enabled(seed_a: Any, seed_b: Any,
                    distance: int | None) -> tuple[bool, str | None]:
    """差分ヒートマップを**自動で**出せるか（点検 G6。`comparison.md` §2.3 の条件）。

    条件は 2 つだけ:
    - **同じ seed**（`provenance.seed` が一致）
    - **pHash 距離が `HEATMAP_DISTANCE_THRESHOLD` 以下**

    **「派生関係」（`external_ref` / `regenerated_from`）の条件は P7 まで外す**（設計 §0.5 G6）。
    その関係を持つ列がまだ無いので、条件に書くと**存在しない列で判定した気になる**。
    条件の外でも利用者が押せば出せる（`force`。G6）。

    戻り値は `(出せるか, 出せない理由を 1 行)`
    """
    if _same_seed(seed_a, seed_b):
        return True, None
    if distance is None:
        return False, ("同じ seed ではなく、pHash もまだ計算されていません"
                       f"（サムネイルを開くと計算されます。距離 {HEATMAP_DISTANCE_THRESHOLD}"
                       " 以下なら出せます）")
    if distance <= HEATMAP_DISTANCE_THRESHOLD:
        return True, None
    return False, (f"同じ seed ではなく、pHash 距離 {distance} がしきい値"
                   f" {HEATMAP_DISTANCE_THRESHOLD} より大きい（画素はほぼ別物です）")


def _pad_pair(a: np.ndarray, b: np.ndarray) -> tuple[np.ndarray, np.ndarray,
                                                    np.ndarray, np.ndarray]:
    """形を揃える（右下を 0 で埋める）。同時に**埋めた所を無効**とするマスクを作る。

    戻り値は `(a, b, a のマスク, b のマスク)`。
    """
    h = max(a.shape[0], b.shape[0])
    w = max(a.shape[1], b.shape[1])
    padded, masks = [], []
    for x in (a, b):
        mask = np.zeros((h, w), dtype=np.float64)
        mask[:x.shape[0], :x.shape[1]] = 1.0
        padded.append(np.pad(x, ((0, h - x.shape[0]), (0, w - x.shape[1]))))
        masks.append(mask)
    return padded[0], padded[1], masks[0], masks[1]


def _shift(img: np.ndarray, dy: int, dx: int) -> np.ndarray:
    """**中身**を `dy` / `dx` だけ動かす。はみ出した所は 0。

    （`np.roll` は反対側が回り込んで、端に嘘の差が出る。位相相関の峰は
    「b の中身がどれだけ動いているか」の符号を返すので、これをそのまま渡せば戻る）
    """
    out = np.zeros_like(img)
    h, w = img.shape
    src_y = slice(max(0, -dy), min(h, h - dy))
    src_x = slice(max(0, -dx), min(w, w - dx))
    dst_y = slice(max(0, dy), min(h, h + dy))
    dst_x = slice(max(0, dx), min(w, w + dx))
    out[dst_y, dst_x] = img[src_y, src_x]
    return out


def _overlap(pa: np.ndarray, pb: np.ndarray, mask_a: np.ndarray, mask_b: np.ndarray,
             dy: int, dx: int) -> tuple[np.ndarray, np.ndarray]:
    """`pb` を `dy` / `dx` だけ戻して、**両方が実在する画素**だけを残した組を返す。

    `_pad_pair()` が右下を 0 で埋めた所は「実在しない」ので落とす
    （0 どうしの一致を一致と数えない。`comparison.md` §2.3 の手順 2）。
    """
    moved = _shift(pb, dy, dx)
    valid = mask_a * _shift(mask_b, dy, dx) > 0.5
    return moved, valid


def _aligned_corr(pa: np.ndarray, pb: np.ndarray, mask_a: np.ndarray, mask_b: np.ndarray,
                  dy: int, dx: int) -> float | None:
    """**監査 A2**: 位置合わせした重なりの正規化相互相関（-1〜1）。

    「ずれを戻した後で、実際に画素が一致しているか」を直接見る。無関係な 2 枚では
    ずれを戻しても一致しないので 0 の近くになり、同じ絵なら 1 の近くになる（実測は §0.7）。
    判定できないとき（重なりが小さすぎる / どちらかが一様で濃淡が無い）は `None`
    （**「分からない」を「一致した」と言わない**）。
    """
    moved, valid = _overlap(pa, pb, mask_a, mask_b, dy, dx)
    a_in, b_in = pa[valid], moved[valid]
    if a_in.size < ALIGN_MIN_OVERLAP:
        return None
    spread_a, spread_b = float(a_in.std()), float(b_in.std())
    if spread_a < 1e-6 or spread_b < 1e-6:
        return None
    return float((((a_in - a_in.mean()) * (b_in - b_in.mean())).mean())
                 / (spread_a * spread_b))


def _phase_shift(a: np.ndarray, b: np.ndarray, mask_a: np.ndarray | None = None,
                 mask_b: np.ndarray | None = None) -> dict:
    """位相相関（numpy の FFT）で**平行移動だけ**を推定する（`comparison.md` §2.3 の手順 2）。

    回転・拡大は扱わない（`comparison.md` §8-1）。**ずれが大きい / 峰が弱い /
    合わせても画素が一致しない**ときは「位置が合いません」を返す
    （黙って誤魔化した絵を出さない）。

    `mask_a` / `mask_b` は `_pad_pair()` のマスク。渡されたときだけ**合わせた重なりの
    一致度**（`_aligned_corr()`）まで見る（`build_heatmap()` は必ず渡す。**監査 A2**）。
    渡さない呼び方は推定だけ（マスクが分からないので「実在する画素」を決められない）。
    """
    fa = np.fft.rfft2(a - a.mean())
    fb = np.fft.rfft2(b - b.mean())
    cross = fa * np.conj(fb)
    mag = np.abs(cross)
    mag[mag < 1e-9] = 1e-9
    corr = np.fft.irfft2(cross / mag, s=a.shape)
    dy, dx = (int(v) for v in np.unravel_index(int(np.argmax(corr)), corr.shape))
    h, w = a.shape
    if dy > h // 2:
        dy -= h
    if dx > w // 2:
        dx -= w
    ratio = float(corr.max() / (np.abs(corr).mean() + 1e-12))
    corr_coef = None
    if mask_a is not None and mask_b is not None:
        corr_coef = _aligned_corr(a, b, mask_a, mask_b, dy, dx)
    if abs(dx) > ALIGN_MAX_SHIFT or abs(dy) > ALIGN_MAX_SHIFT:
        return {"ok": False, "dx": dx, "dy": dy, "peak_ratio": ratio, "corr": corr_coef,
                "reason": (f"位置が合いません（平行移動が大きすぎます: {abs(dx)}×{abs(dy)}px。"
                           "回転・拡大は扱いません）")}
    if ratio < ALIGN_MIN_PEAK_RATIO:
        return {"ok": False, "dx": dx, "dy": dy, "peak_ratio": ratio, "corr": corr_coef,
                "reason": ("位置が合いません（ずれの手がかりが弱い＝別の絵の可能性が高い。"
                           f"峰の比 {ratio:.1f} < {ALIGN_MIN_PEAK_RATIO}）")}
    # **監査 A2**: 峰が立っていても、戻した重なりが一致していなければ「別の絵」。
    # ここが無いと、ノイズの一番高い点が ±64px に入っただけの無関係な組に
    # でたらめな dx/dy と全面が赤の絵を「合わせた」と言って返してしまう。
    if mask_a is not None and mask_b is not None and not (
            corr_coef is not None and corr_coef >= ALIGN_MIN_CORR):
        shown = "判定できません" if corr_coef is None else f"{corr_coef:.2f}"
        return {"ok": False, "dx": dx, "dy": dy, "peak_ratio": ratio, "corr": corr_coef,
                "reason": ("位置が合いません（ずらしても画素が一致しない＝別の絵です。"
                           f"重なりの一致度 {shown} < {ALIGN_MIN_CORR}）")}
    return {"ok": True, "dx": dx, "dy": dy, "peak_ratio": ratio, "corr": corr_coef,
            "reason": None}


def build_heatmap(a_src: str | Path, b_src: str | Path, *,
                  gray: tuple[np.ndarray, np.ndarray] | None = None) -> dict:
    """差分ヒートマップ（`comparison.md` §2.3。**保存しない**。設計 §6.2）。

    1. 両方を 256px の長辺へ縮小（グレースケール。アスペクトは保つ）
    2. **平行移動だけ**を位相相関で推定して補正する（回転・拡大は扱わない）
    3. 絶対差を `HEATMAP_AMPLIFY` 倍して赤で元画像に重ねる（**増幅は表示だけ**）

    合わないときは画像ではなく `available=False` と理由（「位置が合いません」）を返す。
    **監査 A2**: 「峰が立ったか」だけでなく、**合わせた重なりの一致度**（`ALIGN_MIN_CORR`）
    まで見る。無関係な 2 枚に「合わせた」と言って無意味な絵を返さない。

    `dx` / `dy` は**縮小した座標**（256px の長辺）での平行移動。
    `gray` は「もう縮小してある 2 枚」（指標と同じ組では復号と縮小を 1 回で済ませる）。
    """
    if gray is None:
        gray = (reduced_gray(a_src), reduced_gray(b_src))
    gray_a, gray_b = gray
    pa, pb, mask_a, mask_b = _pad_pair(gray_a, gray_b)
    found = _phase_shift(pa, pb, mask_a, mask_b)
    if not found["ok"]:
        return {"available": False, "aligned": False, "dx": found["dx"], "dy": found["dy"],
                "peak_ratio": found["peak_ratio"], "corr": found["corr"],
                "reason": found["reason"], "image": None}

    moved, valid = _overlap(pa, pb, mask_a, mask_b, found["dy"], found["dx"])
    delta = np.where(valid, np.abs(pa - moved), 0.0)

    amp = np.clip(delta * HEATMAP_AMPLIFY, 0, 255)
    base = np.repeat(np.clip(pa, 0, 255)[:, :, None], 3, axis=2)
    alpha = (amp / 255.0)[:, :, None]
    red = np.array([255.0, 40.0, 40.0], dtype=np.float64)
    blended = base * (1 - alpha) + red * alpha

    buf = io.BytesIO()
    Image.fromarray(np.clip(blended, 0, 255).astype(np.uint8), "RGB").save(
        buf, "WEBP", quality=82, method=4)
    encoded = base64.b64encode(buf.getvalue()).decode("ascii")
    return {"available": True, "aligned": True, "dx": found["dx"], "dy": found["dy"],
            "peak_ratio": found["peak_ratio"], "corr": found["corr"], "reason": None,
            "image": f"data:image/webp;base64,{encoded}"}


def pair_report(store: Store, a_id: str, b_id: str, *, force: bool = False) -> dict:
    """1 組の指標と差分ヒートマップ（設計 §6.2 の `POST .../compare/pair`）。

    - 指標（`ssim` / `changed_fraction` / `mean_abs`）は**キャッシュを通す**（`comparison_cache`）
    - `phash_distance` は**その場で**出す（監査 D1。キャッシュしない）
    - ヒートマップは**要求のたびに作って返すだけ**（保存しない）。条件の外でも `force` で出す（点検 G6）
    - `force` でも位置が合わなければ画像は返さず「位置が合いません」を返す（`comparison.md` §2.3）
    """
    if not a_id or not b_id:
        raise ReviewError(422, "a_id と b_id が要ります", details={"a_id": a_id, "b_id": b_id})
    # 監査 B3: 未コミットの行を読まない（読みは錠の下）
    with store.locked():
        a, b = store.asset(a_id), store.asset(b_id)
    if a is None or b is None:
        missing = a_id if a is None else b_id
        raise ReviewError(404, "asset がありません", details={"asset_id": missing})

    distance = hash_distance(a.get("phash"), b.get("phash"))
    seed_a = (a.get("meta") or {}).get("seed")
    seed_b = (b.get("meta") or {}).get("seed")
    enabled, reason = heatmap_enabled(seed_a, seed_b, distance)

    heatmap: dict = {
        "enabled": enabled,
        "forced": bool(force) and not enabled,
        "reason": reason,
        "distance_threshold": HEATMAP_DISTANCE_THRESHOLD,
        "available": False, "aligned": None, "dx": None, "dy": None,
        "peak_ratio": None, "corr": None, "image": None,
    }
    # 差分を作るなら、256px の縮小を**指標と共有する**（実測: 1024² の 1 枚で
    # 復号＋縮小が 9.6 ms。2 回にすると 1 組で 20 ms 近く無駄になる）
    gray = None
    a_src = b_src = None
    if enabled or force:
        a_src, b_src = _primary_path(a), _primary_path(b)
        if not a_src or not b_src:
            heatmap["reason"] = "実体が見つからないので差分を作れません"
        else:
            gray = (reduced_gray(a_src), reduced_gray(b_src))

    metrics = cached_pair_metrics(store, a, b, gray=gray)

    if enabled or force:
        if a_src and b_src:
            got = build_heatmap(a_src, b_src, gray=gray)
            heatmap.update(got)
            if not got["available"]:
                heatmap["reason"] = got["reason"]

    return {
        "a_id": a_id,
        "b_id": b_id,
        "algo_version": ALGO_VERSION,
        "phash_distance": distance,
        "ssim": metrics["ssim"],
        "changed_fraction": metrics["changed_fraction"],
        "mean_abs": metrics["mean_abs"],
        "cached": metrics["cached"],
        "heatmap": heatmap,
    }


# ---- P5-3: 似ている順（`comparison.md` §4.1）----


def nearest_order(items: list[dict], base: str | None = None) -> dict:
    """**似ている順**（基準からの pHash 距離の昇順。`comparison.md` §4.1）。

    距離はサーバ（ここ）で出す（設計 §10-4: 画面は並べ替えるだけ）。
    pHash が未計算の枚は距離が分からないので**末尾**に置き、入力順を保つ
    （「分からない」を「遠い」と言わない。`final_prompt` と同じ扱い）。
    """
    ids = [item["asset_id"] for item in items]
    base_id = base if base in ids else (ids[0] if ids else None)
    if base_id is None:
        return {"base": None, "order": [], "distances": {}}
    base_hash = next((item.get("phash") for item in items
                      if item["asset_id"] == base_id), None)
    entries: list[tuple[int, str, int | None]] = []
    for index, item in enumerate(items):
        if item["asset_id"] == base_id:
            continue
        entries.append((index, item["asset_id"],
                        hash_distance(base_hash, item.get("phash"))))
    known = sorted((e for e in entries if e[2] is not None), key=lambda e: (e[2], e[0]))
    unknown = [e for e in entries if e[2] is None]
    order = [base_id] + [e[1] for e in known] + [e[1] for e in unknown]
    distances = {base_id: 0}
    distances.update({e[1]: e[2] for e in entries})
    return {"base": base_id, "order": order, "distances": distances}


def pair_rules(items: list[dict], base_index: int) -> list[dict]:
    """基準と各枚の組について、ヒートマップを**自動で**出せるかを返す（点検 G6）。

    画像は復号しない（規則だけ。指標は要求時に計算する）。`pair_report()` は同じ
    `heatmap_enabled()` を使うので、規則が 2 か所に分かれない。
    """
    if not items:
        return []
    base = items[base_index]
    out = []
    for item in items:
        if item["asset_id"] == base["asset_id"]:
            continue
        seed_a = (base.get("provenance") or {}).get("seed")
        seed_b = (item.get("provenance") or {}).get("seed")
        distance = hash_distance(base.get("phash"), item.get("phash"))
        enabled, reason = heatmap_enabled(seed_a, seed_b, distance)
        out.append({
            "a_id": base["asset_id"], "b_id": item["asset_id"],
            "phash_distance": distance, "same_seed": _same_seed(seed_a, seed_b),
            "heatmap": {"enabled": enabled, "reason": reason},
        })
    return out


# ---- 入力の検査 ----


def parse_ids_param(raw: str | None) -> list[str]:
    """`?ids=a,b,c` を配列にする。空・末尾のカンマだけ許す。"""
    if raw is None or not str(raw).strip():
        return []
    parts = [part.strip() for part in str(raw).split(",")]
    if parts and parts[-1] == "":
        parts.pop()
    if not parts or any(not part for part in parts):
        raise ReviewError(422, "ids はカンマ区切りの asset_id です", details={"ids": raw})
    return parts


def check_ids(ids: Iterable[str]) -> list[str]:
    """2 枚以上・重複なし・8 枚まで（画面の上限）。"""
    got = [str(i).strip() for i in ids]
    if any(not i for i in got):
        raise ReviewError(422, "ids に空があります")
    if len(got) < 2:
        raise ReviewError(422, "比較には 2 枚以上が要ります", details={"ids": got})
    if len(set(got)) != len(got):
        counted = collections.Counter(got)
        dupes = sorted(name for name, n in counted.items() if n > 1)
        raise ReviewError(422, "ids に同じ id が 2 回あります", details={"duplicate": dupes})
    if len(got) > MAX_COMPARE_IDS:
        raise ReviewError(
            422,
            f"一度に並べられるのは {MAX_COMPARE_IDS} 枚までです"
            "（比較の画面の上限。まとまりの枚数の上限ではありません）",
            details={"max": MAX_COMPARE_IDS, "got": len(got),
                     "hint": "ids= で 8 枚までを指定してください"})
    return got


def _read_assets(store: Store, ids: Iterable[str]) -> list[dict]:
    """**錠の下で** 1 枚ずつ読む（**監査 B3**: 未コミットの行を読まない）。"""
    out: list[dict] = []
    with store.locked():
        for asset_id in ids:
            asset = store.asset(asset_id)
            if asset is None:
                raise ReviewError(404, "asset がありません", details={"asset_id": asset_id})
            out.append(asset)
    return out


def _fill_missing_hashes(store: Store, assets: Sequence[dict]) -> int:
    """**監査 B1**: 文書を組む前に、足りない pHash / dHash だけを埋める。

    `asset.phash` はサムネイルを作る復号に同居して入る（**実測 F5**）ので、**サムネイルを
    まだ開いていない枚**（既存の 263 枚がこれ）は比較の文書を組む時点で `null` になる。
    ここで足りない枚だけ `ensure_hashes()` を通す（復号は 1 枚 14 ms。最大 `MAX_COMPARE_IDS`
    枚で 1 度きり。**起動時の全件は走らせない**＝263 枚で 3.7 秒、1 万枚で 2.3 分）。

    **錠は復号の間は握らない**（`ensure_hashes()` が読むときだけ錠を取り、復号と書きは外。
    点検 D3 / 監査 B3 と同じ規則）。実体が無い枚と復号できない枚はそのままにする
    （**「分からない」を偽の値で埋めない**。理由の 1 行がそのまま出る）。
    """
    filled = 0
    for asset in assets:
        if asset.get("phash") and asset.get("dhash"):
            continue                     # 1 枚につき生涯 1 回で終わる
        path = _primary_path(asset)
        if not path or not Path(path).exists():
            continue
        try:
            if ensure_hashes(store, asset["id"], path) is not None:
                filled += 1
        except Exception:  # noqa: BLE001  1 枚の失敗で比較そのものを落とさない
            log.warning("pHash を計算できませんでした（比較は続けます）: %s", path,
                        exc_info=True)
    return filled


def compare_assets(store: Store, ids: Iterable[str], *, base: str | None = None) -> dict:
    """`GET /api/compare` の中身。**まとまりが無くても引ける**（点検 C9）。

    **監査 B1**: 文書を組む前に、足りない pHash / dHash だけを埋める（`_fill_missing_hashes()`）。
    比較の画面は `/api/compare` を先に引き、サムネイル（＝ハッシュを計算する復号）はその後に
    要求するので、これが無いと**初回の文書にハッシュが乗らない**（似ている順の距離が出ず、
    規則でも「pHash もまだ計算されていません」と言ってしまう）。
    """
    checked = check_ids(ids)
    assets = _read_assets(store, checked)
    _fill_missing_hashes(store, assets)
    # 埋めた値を読む（`asset_item()` は写しを取るので、古い dict のまま組まない）
    items = [asset_item(asset) for asset in _read_assets(store, checked)]
    return build_document(items, base=base)


def group_head(group: dict) -> dict:
    """`group` の欄（`p5-design.md` §6.1 の `group` ＋ 画面が使う印）。"""
    return {
        "id": group["id"],
        "title": group.get("title"),
        "kind": group.get("kind"),
        "policy": group.get("policy"),
        "state": group.get("state"),
        "decision": group.get("decision"),
        "selected_asset_ids": list(group.get("selected_asset_ids") or []),
        "item_count": len(group.get("items") or []),
        "changed_at": group.get("changed_at"),
        "exported_at": group.get("exported_at"),
    }
