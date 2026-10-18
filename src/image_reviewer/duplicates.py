"""重複の検出と整理（P8-1。設計 `docs/p8-design.md` §0.5・§0.9・§0.10・§3.1）。

決めたこと（設計が正）:

- **pHash は `GET` では計算しない**（家風: `GET` は 1 バイトも書かない）。足りない分は
  **`POST /api/duplicates/compute` の背景ジョブ**（`job` を使う。`kind='hash'`）で埋める。
  実測: **14.8 ms/枚（復号込み）**。実データは **91 / 263 枚**にしか入っていない
- **帯索引**（`phash_band`。**4bit × 16 本**の 16 進 1 文字）で候補を絞る。
  **取りこぼし 0 の保証は「ハミング距離 ≤ 15」**: 距離 `d` なら**少なくとも 1 本の帯は完全に一致する**
  （鳩の巣。`d < 16`）ので、同じ `(band, value)` を持つ組だけを候補にすれば必ず含まれる。
  **（P8-1 の監査 B-1）8bit × 8 本では保証が距離 7 までだった**（実測: ≤12 で 3 組・≤16 で 72 組を
  取りこぼす）。**16 以上を求められたら帯で絞らず総当たりに落とす**（263 枚で 20 ms）。
- **群は連結成分**。**群の中の最大距離が小さい順**に出す（**確実な物から**。点検の規模の判定）。
  **頁送りは付けない**（連結成分は切れない。点検 C7）
- **代表は推薦するだけ**（§0.9 の決定的な規則）。**自動では外さない**
- **除外は `(小さい方, 大きい方)` に正規化**（表の `CHECK (a_id < b_id)` が守る）
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from typing import Any, Iterable, Sequence

from . import db
from .review import ReviewError

#: 帯の本数と 1 本のビット数（`comparison.md` §1.3。**4 × 16 = 64bit**。監査 B-1）
BANDS = 16
BAND_HEX = 1                                   # 4bit = 16 進 1 文字
#: 帯で**取りこぼし 0** を保証できる最大の距離（鳩の巣。`d < BANDS`）
BAND_GUARANTEE = BANDS - 1

#: 「近い」の既定（`compare.PHASH_NEAR_THRESHOLD` と同じ値。**画面で切り替えられる**）
DEFAULT_MAX_DISTANCE = 6
#: 画面が選べる 3 段（§0.14 Q3）。**どれも帯の保証（≤15）の中**なので、Q3 の ≤10 が正しい
ALLOWED_MAX_DISTANCE = (3, 6, 10)
#: 口が受ける上限（**16 以上は総当たりに落ちる**）
MAX_DISTANCE_LIMIT = 64


# ---- 帯（純関数に近い。`con` を渡すのは書き込みだけ）----


def bands_of(phash: str) -> list[tuple[int, str]]:
    """16 進 16 文字の pHash を **16 本の帯**（4bit ずつ）に割る。

    **小文字に揃える**（同じ値が大文字と小文字で別の帯にならないように）。
    """
    body = (phash or "").strip().lower()
    if len(body) != BANDS * BAND_HEX:
        raise ValueError(f"pHash は 16 進 {BANDS * BAND_HEX} 文字のはず: {phash!r}")
    return [(i, body[i * BAND_HEX:(i + 1) * BAND_HEX]) for i in range(BANDS)]


def write_bands(con: sqlite3.Connection, asset_id: str, phash: str | None) -> int:
    """その画像の帯を**入れ直す**（`asset.phash` が入ったときに一緒に書く。§0.5）。

    `phash` が `None` なら**消す**（前の値の帯が残ると、嘘の候補が出る）。
    """
    con.execute("DELETE FROM phash_band WHERE asset_id = ?", (asset_id,))
    if not phash:
        return 0
    rows = [(asset_id, band, value) for band, value in bands_of(phash)]
    con.executemany("INSERT INTO phash_band(asset_id, band, value) VALUES (?, ?, ?)", rows)
    return len(rows)


def _band_rows(rows) -> list[tuple[str, int, str]]:
    """`(id, phash)` の並びを `phash_band` の行に開く（**まとめて入れるため**）。"""
    out: list[tuple[str, int, str]] = []
    for row in rows:
        for band, value in bands_of(row["phash"]):
            out.append((row["id"], band, value))
    return out


def fill_missing_bands(con: sqlite3.Connection) -> int:
    """`asset.phash` はあるのに帯が無い枚を埋める（**移行の後始末**。何度呼んでも同じ）。

    **1 枚ずつではなくまとめて入れる**（1 万枚の移行で 16 万行を書くので、1 枚 1 取引だと
    何分もかかる。実測で踏んだ）。**`asset.phash` がまだ無い DB では何もしない**。
    """
    cols = {row["name"] for row in con.execute("PRAGMA table_info(asset)")}
    if "phash" not in cols:
        return 0
    rows = con.execute(
        "SELECT a.id, a.phash FROM asset a"
        " WHERE a.phash IS NOT NULL AND a.phash <> ''"
        "   AND NOT EXISTS (SELECT 1 FROM phash_band b WHERE b.asset_id = a.id)").fetchall()
    if not rows:
        return 0
    con.executemany("INSERT OR REPLACE INTO phash_band(asset_id, band, value) VALUES (?, ?, ?)",
                    _band_rows(rows))
    return len(rows)


def rebuild_stale_bands(con: sqlite3.Connection) -> int:
    """**本数が 16 でない帯**を `asset.phash` から作り直す（監査 B-1 の移行。何度でも安全）。

    8bit × 8 本で作られた帯（旧版）や、帯の表を作り直した直後の DB が対象。
    **帯は `asset.phash` から引き直せる**ので、消して作り直して害が無い。

    **`asset.phash` がまだ無い DB**（v3 より前の形のまま版だけ進んだ試験用の DB など）では
    **何もしない**（列の有無を見てから触る。家風「列を見てから」）。
    """
    cols = {row["name"] for row in con.execute("PRAGMA table_info(asset)")}
    if "phash" not in cols:
        return 0
    rows = con.execute(
        "SELECT a.id, a.phash FROM asset a JOIN phash_band b ON b.asset_id = a.id"
        " WHERE a.phash IS NOT NULL AND a.phash <> ''"
        " GROUP BY a.id, a.phash HAVING count(*) <> ?", (BANDS,)).fetchall()
    if not rows:
        return 0
    # **まとめて**（1 枚ずつだと 1 万枚で何分もかかる。`fill_missing_bands` と同じ理由）
    con.executemany("DELETE FROM phash_band WHERE asset_id = ?",
                    [(row["id"],) for row in rows])
    con.executemany("INSERT OR REPLACE INTO phash_band(asset_id, band, value) VALUES (?, ?, ?)",
                    _band_rows(rows))
    return len(rows)


# ---- 群（読み取りだけ）----


def _asset_rows(con: sqlite3.Connection, ids: Sequence[str]) -> dict[str, dict]:
    """群に出す情報（**1 問い合わせで引く**。N+1 にしない）。"""
    if not ids:
        return {}
    marks = ",".join("?" * len(ids))
    rows = con.execute(
        f"SELECT a.id, a.sha256, a.width, a.height, a.phash, a.dhash, a.first_seen_at,"
        f"  (SELECT l.size FROM asset_location l WHERE l.asset_id = a.id"
        f"    ORDER BY l.is_primary DESC, l.path LIMIT 1) AS size,"
        f"  (SELECT l.mtime_ns FROM asset_location l WHERE l.asset_id = a.id"
        f"    ORDER BY l.is_primary DESC, l.path LIMIT 1) AS mtime_ns,"
        f"  (SELECT l.display_path FROM asset_location l WHERE l.asset_id = a.id"
        f"    ORDER BY l.is_primary DESC, l.path LIMIT 1) AS path,"
        f"  (SELECT d.verdict FROM decision d WHERE d.subject_type = 'asset'"
        f"    AND d.subject_id = a.id ORDER BY d.seq DESC LIMIT 1) AS verdict"
        f" FROM asset a WHERE a.id IN ({marks})", list(ids)).fetchall()
    return {row["id"]: dict(row) for row in rows}


def _pixels(row: dict) -> int:
    return int(row.get("width") or 0) * int(row.get("height") or 0)


def _kept(row: dict) -> int:
    return 1 if (row.get("verdict") or "") == "keep" else 0


def _rejected(row: dict) -> int:
    """**人が「ボツ」と言った物は推薦しない**（監査 D-3 / G-4）。0 = ボツでない、1 = ボツ。"""
    return 1 if (row.get("verdict") or "") == "reject" else 0


def _rank(row: dict) -> tuple:
    # **大きい方が先**（`-` を付ける）。`reject` と `id` だけ「小さい方が先」
    return (-_kept(row), _rejected(row), -_pixels(row), -int(row.get("size") or 0),
            -int(row.get("mtime_ns") or 0), str(row.get("id")))


#: 推薦の規則（**上から順に見て、上位 2 枚を分けた規則を言う**。監査 D-2）
_RULES: tuple[tuple[str, Any], ...] = (
    ("人がキープにしたもの", _kept),
    ("人がボツにしていないもの", lambda r: -_rejected(r)),
    ("画素数がいちばん多い", _pixels),
    ("ファイルがいちばん大きい", lambda r: int(r.get("size") or 0)),
    ("いちばん新しい（同じ寸法の作り直しは最終版を残す）", lambda r: int(r.get("mtime_ns") or 0)),
)


def representative(members: Sequence[dict]) -> tuple[str, str]:
    """**代表を推薦する**（§0.9 の決定的な規則。**自動では外さない**）。

    1. **人が「キープ」と言った物**（`decision` の最新が `keep`）
    2. **人が「ボツ」と言っていない物**（**`reject` は最下位**。監査 D-3 / G-4 =
       「要らない」と言った物を「おすすめ」に出さない）
    3. **画素数が最大**
    4. **ファイルが大きい**
    5. **`mtime_ns` が新しい**（**同じ寸法の作り直しでは「最終版」が新しい**。点検 C2・G3。
       `first_seen_at` は効かない＝全 263 枚が 1 回の走査で入っている）
    6. **`id` の昇順**（決定的にする）

    返すのは `(asset_id, reason)`。**`reason` は「上位 2 枚を分けた規則」**（監査 D-2:
    群の中で最初に違う属性ではなく、**推薦の決め手**を言う。例: 画素数が同じでサイズが違うなら
    「ファイルが大きい」）。
    """
    if not members:
        raise ValueError("空の群からは選べない")
    ordered = sorted(members, key=_rank)
    best = ordered[0]
    if len(ordered) == 1:
        return str(best["id"]), "1 枚だけ"
    second = ordered[1]
    for label, get in _RULES:
        if get(best) != get(second):
            return str(best["id"]), label
    return str(best["id"]), "id の順（ほかに違いが無い）"


def _hashed_assets(con: sqlite3.Connection) -> dict[str, int]:
    """**生きている**（`deleted_at IS NULL`）枚の pHash を int で返す（監査 C-4 / D-7）。

    **段 1（`deleted_at`）の枚は群にも候補にも出さない**。同じ応答の中で `hashed` の数と
    群の中身が食い違わないようにする（監査 C-4）。
    """
    return {row["id"]: int(row["phash"], 16) for row in con.execute(
        "SELECT id, phash FROM asset WHERE deleted_at IS NULL"
        "   AND phash IS NOT NULL AND phash <> ''")}


def excluded_pair_count(con: sqlite3.Connection, max_distance: int) -> int:
    """その距離でなら候補に入っていたのに、**除外（「別物として確定」）で隠れている組**の数。

    **（P8-3 の取り落とし調査。`docs/p8-3-band-miss.md`）** `candidate_pairs` は除外を
    黙って外すので、**これが無いと「帯の取りこぼし」と見分けが付かない**。実データで実際に
    起きた: 「別物として確定」が 1 組あるだけで、距離 4 の 2 枚だけの群が丸ごと消え、
    `GET /api/duplicates/near?max_distance=6` が **20 群 / 55 枚**（総当たりは 21 群 / 57 枚）
    を返した。帯は 1 組も落としていなかった（4208 行が `asset.phash` と完全に一致）。

    `near_groups` が返す `total_pairs` と足すと、**その距離の総当たりの組数**になる
    （`total_pairs + excluded_pairs = 距離 ≤ d の総当たり`）。**数えた物は消さない**（家風）。
    """
    hashes = _hashed_assets(con)
    n = 0
    for row in con.execute("SELECT a_id, b_id FROM duplicate_exclusion"):
        pa, pb = hashes.get(row["a_id"]), hashes.get(row["b_id"])
        if pa is None or pb is None:      # 消した枚・pHash の無い枚は候補に入らない
            continue
        if (pa ^ pb).bit_count() <= max_distance:
            n += 1
    return n


def candidate_pairs(con: sqlite3.Connection, max_distance: int) -> list[tuple[str, str, int]]:
    """**帯で絞ってから**距離を計算する（`max_distance` 以下だけ返す）。

    - **除外（`duplicate_exclusion`）はここで外す**（§0.10）
    - **`deleted_at` の枚は候補に入れない**（監査 C-4）
    - **帯の保証は距離 ≤ 15**（鳩の巣。`BAND_GUARANTEE`）。**16 以上は帯で絞らず総当たり**
      （263 枚で 20 ms。**帯で絞ると取りこぼす**＝監査 B-1）
    - **距離は int に直してから** `bit_count()`（文字列の正規表現を毎回回さない。監査 D-7）
    """
    if not (0 <= int(max_distance) <= MAX_DISTANCE_LIMIT):
        raise ReviewError(422, f"max_distance は 0〜{MAX_DISTANCE_LIMIT} です",
                          details={"max_distance": max_distance})
    excluded = {(row["a_id"], row["b_id"]) for row in
                con.execute("SELECT a_id, b_id FROM duplicate_exclusion")}
    out: list[tuple[str, str, int]] = []
    if max_distance >= BANDS:
        # **帯では保証できない距離**。総当たり（`deleted_at` は `_hashed_assets` で外れる）
        hashes = _hashed_assets(con)
        ids = sorted(hashes)
        for i, a_id in enumerate(ids):
            pa = hashes[a_id]
            for b_id in ids[i + 1:]:
                dist = (pa ^ hashes[b_id]).bit_count()
                if dist <= max_distance and (a_id, b_id) not in excluded:
                    out.append((a_id, b_id, dist))
        return out
    # **帯ごとに引く**（1 本ずつ。`(band, value)` の索引が効く）。
    # 1 回の大きな自己結合にすると SQLite が**一時ファイル**を要求し、この環境では
    # `unable to open database file` で落ちる（実測。`%TEMP%` に書けない制約）。
    # **候補を全部溜めない**: 帯で当たった組は**その場で距離を計算して、条件を満たす物だけ**残す
    # （1 万枚では候補が 240 万組になるので、溜めてから距離を取ると遅い。実測）。
    hashes = _hashed_assets(con)
    found: dict[tuple[str, str], int] = {}
    for band in range(BANDS):
        rows = con.execute(
            "SELECT ba.asset_id AS a, bb.asset_id AS b"
            "  FROM phash_band ba"
            "  JOIN phash_band bb"
            "    ON bb.band = ba.band AND bb.value = ba.value AND bb.asset_id > ba.asset_id"
            "  JOIN asset xa ON xa.id = ba.asset_id AND xa.deleted_at IS NULL"
            "  JOIN asset xb ON xb.id = bb.asset_id AND xb.deleted_at IS NULL"
            " WHERE ba.band = ?", (band,)).fetchall()
        for row in rows:
            key = (row["a"], row["b"])
            if key in found or key in excluded:
                continue
            pa, pb = hashes.get(key[0]), hashes.get(key[1])
            if pa is None or pb is None:
                continue
            dist = (pa ^ pb).bit_count()
            if dist <= max_distance:
                found[key] = dist
    return [(a_id, b_id, dist) for (a_id, b_id), dist in found.items()]


def near_groups(con: sqlite3.Connection, *, max_distance: int = DEFAULT_MAX_DISTANCE,
                limit: int | None = None) -> dict:
    """準重複の**群**（連結成分）を返す（§3.1 の `GET /api/duplicates/near`）。

    - **群の中の最大距離が小さい順**（＝**確実な物から**）→ 群の大きさ → `id`
    - 各群に **`suggested_id` / `reason` / `max_distance_within`** を入れる（§0.9・点検 C2）
    - **`unhashed`**（pHash がまだの枚数）を返す（**計算はしない**）
    - **`cursor` は付けない**（連結成分は切れない。点検 C7）
    - **`total_pairs` / `excluded_pairs`** を返す（**P8-3 の取り落とし調査**）。
      `total_pairs` は距離 ≤ `max_distance` の組の数、`excluded_pairs` は
      **「別物として確定」で隠れている組の数**。**足すとその距離の総当たりの組数**になるので、
      群が丸ごと消えたときに「帯の取りこぼし」と「人の除外」を**外から見分けられる**。
    """
    if limit is not None and int(limit) < 1:
        # **（監査 D-4）負や 0 は黙って 1 にしない**。語彙の外は 422（家風）
        raise ReviewError(422, "limit は 1 以上です", details={"limit": limit})
    hashed = _hashed_assets(con)
    unhashed = con.execute(
        "SELECT count(*) AS n FROM asset"
        " WHERE deleted_at IS NULL AND (phash IS NULL OR phash = '')").fetchone()["n"]
    pairs = candidate_pairs(con, max_distance)
    hidden = excluded_pair_count(con, max_distance)
    # --- 連結成分（union-find）---
    parent: dict[str, str] = {}

    def find(x: str) -> str:
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for a, b, _ in pairs:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra
    groups: dict[str, set[str]] = {}
    for a, b, _ in pairs:
        groups.setdefault(find(a), set()).update((a, b))
    # --- 群の情報を組む ---
    built = []
    for members in groups.values():
        ids = sorted(members)
        within = max(d for a, b, d in pairs if a in members and b in members)
        built.append({"ids": ids, "max_distance_within": within})
    # 小さい距離の群から。同じなら大きい群。同じなら最初の id
    built.sort(key=lambda g: (g["max_distance_within"], -len(g["ids"]), g["ids"][0]))
    if limit is not None:
        built = built[:int(limit)]
    info = _asset_rows(con, [i for g in built for i in g["ids"]])
    out_groups = []
    for g in built:
        members = [info[i] for i in g["ids"] if i in info]
        suggested, reason = representative(members)
        out_groups.append({
            "suggested_id": suggested,
            "reason": reason,
            "max_distance_within": g["max_distance_within"],
            "count": len(members),
            "items": members,
        })
    return {
        "max_distance": max_distance,
        "hashed": len(hashed),
        "unhashed": int(unhashed),
        # **数の辻褄**（`total_pairs + excluded_pairs` = その距離の総当たり。P8-3 の調査）
        "total_pairs": len(pairs),
        "excluded_pairs": int(hidden),
        "groups": out_groups,
        "total_groups": len(built),
        "total_images": sum(g["count"] for g in out_groups),
    }


def exact_groups(con: sqlite3.Connection) -> dict:
    """**完全重複**（2 か所以上に登録されている `asset`）の一覧（§3.1）。

    この環境では `asset.sha256` が `UNIQUE` なので**構造的に 0 群**になる。それでも口を作るのは、
    **消えた画像の再リンクや将来の複数ルートで増えうる**から。**空のときは 1 行で説明する**
    （黙って空を返すと壊れて見える。§0.4）。
    """
    rows = con.execute(
        "SELECT a.id, a.sha256, count(l.path) AS places"
        " FROM asset a JOIN asset_location l ON l.asset_id = a.id"
        " WHERE l.missing_at IS NULL"
        " GROUP BY a.id HAVING count(l.path) > 1").fetchall()
    items = [{"asset_id": r["id"], "sha256": r["sha256"], "places": int(r["places"])}
             for r in rows]
    return {
        "items": items,
        "count": len(items),
        "message": None if items else "完全に同じファイルはありません（同じ内容は 1 行にまとめています）",
    }


# ---- サービス（背景ジョブと口）----


class DuplicatesService:
    """重複の計算（背景ジョブ）と、群・除外の口（§3.1）。"""

    def __init__(self, store, *, recover: bool = True, poll: float = 0.05):
        self.store = store
        self._poll = poll
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        if recover:
            self.recover_stale()

    # ---- 背景ジョブ（`job` を使う。形は `jobs.py` に倣う）----

    def recover_stale(self) -> int:
        """**前のプロセスの `running` を `failed` にする**（起動時に 1 回。`jobs.py` と同じ）。"""
        with self.store.transaction() as con:
            rows = con.execute("SELECT id FROM job WHERE kind = 'hash' AND state IN"
                               " ('queued', 'running')").fetchall()
            for row in rows:
                con.execute("UPDATE job SET state = 'failed', finished_at = ?,"
                            " message = ? WHERE id = ?",
                            (db.now(), "アプリが終了したため中断しました", row["id"]))
        return len(rows)

    def start_compute(self, *, force: bool = False, actor: str = "human") -> dict:
        """足りない pHash を計算する**背景ジョブ**を始める（202 で返す。§0.5）。

        **`GET` では計算しない**ので、これが唯一の計算の入口。`force` で**全部やり直す**。
        """
        with self.store.transaction() as con:
            busy = con.execute("SELECT id FROM job WHERE kind = 'hash' AND state IN"
                               " ('queued', 'running')").fetchone()
            if busy:
                raise ReviewError(409, "既にハッシュの計算が走っています",
                                  details={"job_id": busy["id"]})
            where = "" if force else (
                " AND (a.phash IS NULL OR a.phash = ''"
                "      OR NOT EXISTS (SELECT 1 FROM phash_band b WHERE b.asset_id = a.id))")
            targets = [row["id"] for row in con.execute(
                "SELECT a.id FROM asset a JOIN asset_location l ON l.asset_id = a.id"
                " WHERE a.deleted_at IS NULL" + where +
                " GROUP BY a.id ORDER BY a.id")]
            job_id = db.ulid()
            con.execute("INSERT INTO job(id, kind, state, params, progress_done, progress_total,"
                        " created_at, started_at) VALUES (?, 'hash', 'running', ?, 0, ?, ?, ?)",
                        (job_id, json.dumps({"force": bool(force)}, ensure_ascii=False),
                         len(targets), db.now(), db.now()))
        self._start(job_id, targets)
        return {"job_id": job_id, "total": len(targets), "force": bool(force)}

    def _start(self, job_id: str, targets: list[str]) -> None:
        with self._lock:
            thread = threading.Thread(target=self._run, args=(job_id, targets),
                                      name=f"hash-{job_id}", daemon=True)
            self._thread = thread
            thread.start()

    def cancel(self, job_id: str) -> dict:
        """**中断の印を `job` 表に立てる**（監査 C-1。**画像 1 枚ごとに見る**）。

        印を**メモリでなく DB** に置くのが要点: `POST /api/jobs/{id}/cancel`
        （`JobService`）からもこのサービスからも**同じ印が見える**ので、
        **ハッシュの背景ジョブが HTTP から止まる**（前の版は別の集合を見ていて止まらなかった）。
        再起動をまたいでも印が残る。
        """
        with self.store.transaction() as con:
            row = con.execute("SELECT * FROM job WHERE id = ?", (job_id,)).fetchone()
            if row is None:
                raise ReviewError(404, "その job はありません", details={"job_id": job_id})
            if row["state"] not in ("queued", "running"):
                return self.get(job_id)
            con.execute("UPDATE job SET cancel_requested = 1 WHERE id = ?", (job_id,))
        return self.get(job_id)

    def _is_cancelled(self, job_id: str) -> bool:
        """**DB の印を見る**（監査 C-1。メモリの集合はもう使わない）。"""
        with self.store.locked() as con:
            row = con.execute("SELECT cancel_requested FROM job WHERE id = ?",
                              (job_id,)).fetchone()
        return bool(row and row["cancel_requested"])

    def _run(self, job_id: str, targets: list[str]) -> None:
        """**1 枚ずつ**: 復号（重い）は**取引の外**、`asset` と帯の書き込みは**短い 1 取引**。

        **（監査 D-1）1 枚あたりの時間**: 実データの既定の対象は 172 枚（pHash が無い枚）で
        2.3 秒＝**13.4 ms/枚**（点検の 14.0 ms/枚と同じ桁。91 枚は帯を書くだけで復号しない）。
        """
        done = 0
        failed = 0
        started = time.monotonic()
        try:
            for asset_id in targets:
                if self._is_cancelled(job_id):
                    self._finish(job_id, "cancelled",
                                 f"中断しました（{done} / {len(targets)} 枚）")
                    return
                try:
                    with self.store.locked() as con:
                        row = con.execute(
                            "SELECT a.phash, l.path FROM asset a JOIN asset_location l"
                            " ON l.asset_id = a.id"
                            " WHERE a.id = ? AND l.missing_at IS NULL"
                            " ORDER BY l.is_primary DESC, l.path LIMIT 1",
                            (asset_id,)).fetchone()
                    if row is None:
                        raise FileNotFoundError("生きている場所がありません")
                    if row["phash"]:
                        # **帯だけ足りない枚**（P5-3 が pHash を入れたが帯が無い）。**復号しない**
                        with self.store.transaction() as con:
                            write_bands(con, asset_id, row["phash"])
                    else:
                        from .compare import hash_file
                        phash, dhash = hash_file(row["path"])       # **取引の外**
                        # **（監査 C-3）`set_hashes` を通す**（pHash の書き手を 1 つに。
                        # 検査（16 進 16 文字の小文字）と**帯も一緒に書く**が 1 か所に入る）
                        self.store.set_hashes(asset_id, phash, dhash)
                    done += 1
                except Exception as exc:                          # noqa: BLE001  1 枚の失敗で全体を止めない
                    failed += 1
                    with self.store.transaction() as con:
                        con.execute("INSERT OR REPLACE INTO job_item(job_id, ref, state, error)"
                                    " VALUES (?, ?, 'failed', ?)",
                                    (job_id, asset_id, f"{type(exc).__name__}: {exc}"))
                self._progress(job_id, done + failed, len(targets), started)
            note = f"{done} 枚の pHash を計算しました"
            if failed:
                note += f"（失敗 {failed} 枚）"
            self._finish(job_id, "done", note, note=note)
        except Exception as exc:                                  # noqa: BLE001  最後の砦
            self._finish(job_id, "failed", f"{type(exc).__name__}: {exc}")

    def _progress(self, job_id: str, done: int, total: int, started: float) -> None:
        took = time.monotonic() - started
        per = took / done if done else 0.0
        left = (total - done) * per
        with self.store.transaction() as con:
            con.execute("UPDATE job SET progress_done = ?, progress_total = ?, message = ?"
                        " WHERE id = ?",
                        (done, total, f"{done} / {total} 枚（1 枚 {per:.2f} 秒・残り {left:.0f} 秒）",
                         job_id))

    def _finish(self, job_id: str, state: str, message: str, *, note: str | None = None) -> None:
        with self.store.transaction() as con:
            con.execute("UPDATE job SET state = ?, message = ?, note = ?, finished_at = ?"
                        " WHERE id = ?", (state, message, note, db.now(), job_id))

    def get(self, job_id: str) -> dict:
        from .jobs import job_doc
        with self.store.locked() as con:
            row = con.execute("SELECT * FROM job WHERE id = ?", (job_id,)).fetchone()
            if row is None:
                raise ReviewError(404, "その job はありません", details={"job_id": job_id})
            return job_doc(con, row)

    def wait(self, job_id: str, *, timeout: float = 300.0) -> dict:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            got = self.get(job_id)
            if got["state"] in ("done", "failed", "cancelled"):
                return got
            time.sleep(self._poll)
        raise ReviewError(504, "待ち時間を超えました", details={"job_id": job_id})

    # ---- 読み（`GET` は書かない）----

    def near(self, *, max_distance: int = DEFAULT_MAX_DISTANCE, limit: int | None = None) -> dict:
        with self.store.locked() as con:
            return near_groups(con, max_distance=max_distance, limit=limit)

    def exact(self) -> dict:
        with self.store.locked() as con:
            return exact_groups(con)

    # ---- 除外（人だけ。§0.10）----

    def exclude(self, *, a_id: str, b_id: str, reason: str | None = None,
                actor: str = "human") -> dict:
        """「別物として確定」する（**解除できる**）。`(小さい方, 大きい方)` に正規化する。"""
        if not a_id or not b_id or a_id == b_id:
            raise ReviewError(422, "2 つの違う画像を指してください",
                              details={"a_id": a_id, "b_id": b_id})
        low, high = sorted([str(a_id), str(b_id)])
        with self.store.transaction() as con:
            missing = [i for i in (low, high) if con.execute(
                "SELECT 1 FROM asset WHERE id = ?", (i,)).fetchone() is None]
            if missing:
                raise ReviewError(404, "その画像はありません", details={"missing": missing})
            con.execute("INSERT OR REPLACE INTO duplicate_exclusion(a_id, b_id, reason, actor, at)"
                        " VALUES (?, ?, ?, ?, ?)", (low, high, reason, actor, db.now()))
        return {"a_id": low, "b_id": high, "excluded": True}

    def remove_exclusion(self, *, a_id: str, b_id: str) -> dict:
        """**解除**（必須。専門 §3.1 の点検 C10）。"""
        low, high = sorted([str(a_id), str(b_id)])
        with self.store.transaction() as con:
            cur = con.execute("DELETE FROM duplicate_exclusion WHERE a_id = ? AND b_id = ?",
                              (low, high))
            if cur.rowcount == 0:
                raise ReviewError(404, "その除外はありません", details={"a_id": low, "b_id": high})
        return {"a_id": low, "b_id": high, "excluded": False}

    def exclusions(self) -> dict:
        with self.store.locked() as con:
            rows = con.execute("SELECT a_id, b_id, reason, actor, at FROM duplicate_exclusion"
                               " ORDER BY at DESC, a_id, b_id").fetchall()
        return {"items": [dict(r) for r in rows], "count": len(rows)}
