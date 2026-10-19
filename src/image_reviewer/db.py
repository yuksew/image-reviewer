"""SQLite の接続・スキーマ・マイグレーション（P5-0）。

設計: docs/p5-design.md §0.1（P5-0）、docs/design.md §5・§13

方針:
- **pragma は接続のたびに必ず掛ける**（WAL / foreign_keys / busy_timeout / synchronous）
- スキーマの版は `PRAGMA user_version` で持つ。マイグレーションは**前へだけ**進み、何度呼んでも安全
- `asset.id` は **ULID**（内容の正体は `sha256` の別列。点検 I17）
- **`asset_location.path` は正規化した鍵**（`store.normalize_path`）。表示用は `display_path`
- `decision.seq` は**挿入順の単調な整数**。「最後の判断」を壁時計で選ばない（点検 C11）
- 場所と来歴の書き手は 1 プロセスに限らない（`cli scan` が別プロセスで走る）。
  **判断と写しの書き手はサーバだけ**（点検 D10。`review.py` の「`review_state` の書き手は
  ここだけ」が正）。**行を書くのであって、ファイル全体を置き換えない**ので、
  別プロセスの走査が判断を消さない（点検 B5）
- **v2（P5-1）**: まとまりの結論を `review_group` の列に持つ（`reason_code_id` / `decision` / `note`）。
  `decision` から引くと、台帳に行を書かない `reopen` と食い違う（点検 C2・G7）
- **v3（P5-3）**: `asset` に `phash` / `dhash`（64bit を **16 進 16 文字の TEXT** で持つ。
  符号なし 64bit は SQLite の符号付き `INTEGER` に入らない）と、比較の指標のキャッシュ
  `comparison_cache` を足す。**点検 D1**: キャッシュに `phash_distance` は置かない
  （ハミング距離はマイクロ秒で出るので、書き込む方が高い）。`ix_comparison_a` も作らない
  （主キー `(a_id, b_id)` の前置と重なる）。`algo_version` を持ち、**引くときも必ず条件に入れる**
- `changed_at` / `exported_at` は `stamp()`（マイクロ秒）。秒までだと同じ秒の 2 件を取りこぼす（点検 B1）
- **v4（P6-0）** は要求と注記、**v5（P4-0）** はタグとジョブ（それぞれ `V4_REQUEST_DDL` / `V5_TAG_DDL`）、
  **v6（P8-0）** は削除とバックアップ（`V6_DELETE_DDL`）、**v7（P2-0）** はカタログと取り込み元
  （`V7_CATALOG_DDL` と `asset.source` / `source_url` / `ref_tags`）。
  **v4〜v7 はどれも「表と列だけ」で機能は足さない**（P6-0 / P4-0 / P8-0 / P2-0 の流儀）。
"""

from __future__ import annotations

import logging
import os
import sqlite3
import time
import uuid
from pathlib import Path

log = logging.getLogger(__name__)

SCHEMA_VERSION = 7       # v6 = P8（重複・削除・バックアップ）、v7 = P2（取り込みとカタログ）。
                         # **P7 の v6（条件の記録）は 2026-10-17 に廃止したので、番号が空いていた**
                         # （`docs/p7-decision.md`）。v7 は `docs/design.md` §5.3 / §5.1 の表と列だけ

# Cronford の base32（ULID）
_B32 = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"


def ulid(now_ms: int | None = None) -> str:
    """ULID（26 文字）。時刻順に並ぶ。`asset.id` と `decision.id` に使う。"""
    ts = int(time.time() * 1000) if now_ms is None else now_ms
    if not 0 <= ts < (1 << 48):
        raise ValueError("時刻が ULID の範囲外")
    chars = []
    for shift in range(45, -1, -5):
        chars.append(_B32[(ts >> shift) & 31])
    rand = uuid.uuid4().int & ((1 << 80) - 1)
    for shift in range(75, -1, -5):
        chars.append(_B32[(rand >> shift) & 31])
    return "".join(chars)


def now() -> str:
    """表示用の時刻（UTC・秒）。**順序の判定には使わない**（点検 C11）。"""
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def stamp() -> str:
    """`changed_at` / `exported_at` 用の時刻（UTC・マイクロ秒）。

    `now()` は秒までしか無いので、同じ秒に続けて判断すると
    `changed_at > exported_at` が成り立たず、書き出しが取りこぼされる（点検 B1-(b)）。
    契約の `Timestamp` も小数秒を許すので、そのまま書き出しに載ってもよい。
    """
    ns = time.time_ns()
    sec, frac = divmod(ns, 1_000_000_000)
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(sec)) + f".{frac // 1000:06d}Z"


def connect(data_dir: str | Path, *, read_only: bool = False,
            check_same_thread: bool = True) -> sqlite3.Connection:
    """接続して pragma を掛ける。呼び出し側が `close()` する。

    `check_same_thread=False` は `Store` だけが使う。FastAPI の同期エンドポイントは
    スレッドプールで走るので、既定の True だと別スレッドの要求で落ちる（点検 F6）。
    使う側が `RLock` で直列化することを前提にする。

    **（P8-4）`read_only=True` ではフォルダを作らない。** 壊れた DB を「読み取り専用で
    開く」道（設計 §0.12-5・§10-12）では、`<data>` に 1 バイトも書かないのが約束
    （`mkdir` も書く側なので、無いフォルダを作らない。無ければ接続そのものが失敗し、
    それが「開けない」の正しい判定になる）。
    """
    data_dir = Path(data_dir)
    if not read_only:
        data_dir.mkdir(parents=True, exist_ok=True)
    db_path = data_dir / "db.sqlite3"
    if read_only:
        con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=15.0,
                              check_same_thread=check_same_thread)
    else:
        con = sqlite3.connect(str(db_path), timeout=15.0, isolation_level=None,
                              check_same_thread=check_same_thread)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA busy_timeout = 15000")
    con.execute("PRAGMA foreign_keys = ON")
    # **（P9。設計 §12.2 の「DB」の 4 行）一時 b-tree をメモリに置く。**
    # これを掛けないと、`ORDER BY` が要る読み（`store.assets()` の
    # `ORDER BY is_primary DESC, display_path`）が**一時ファイルを作りに行く**。
    # 1 万枚ではバッファに収まらず、置き場によっては
    # `sqlite3.OperationalError: unable to open database file` になる
    # （**P9 の実測**: 1 万枚の合成 DB で `GET /api/assets` が 500 になった。
    #   `%TEMP%` に書けない環境＝エージェントの sandbox。§12.2 は最初からこれを書いていた）。
    con.execute("PRAGMA temp_store = MEMORY")
    # **`cache_size` は既定のままにする**（§12.2 は `-65536`＝64 MB と書いているが、
    # **入れなかった**）。**理由は速さだけ**（P9 の実測: 1 万枚の SQL 3 本が
    # 43.6 → 42.5 ms。一覧の 200 ms は `store.assets()` の dict 組み立てが主因で、
    # ページキャッシュでは動かない。入れる実利が無い）。
    # **（P9 の監査 C-1。前の理由は誤りだった。）** ここには「64 MB にすると、走ったまま
    # 壊れた DB を live の接続の `quick_check` が見落とす（既定の 2 MB なら見つける）」と
    # 書いてあった。**既定でも見落とす**——それに収まる大きさの DB（実測 0.65 MB・250 行）
    # では、書き込み用の接続が自分が書いたページをキャッシュに持つので、外から潰された
    # ページを読み直さない（監査の実測。28 通りすべてで既定でも見落とした）。
    # いまは `backup._refuse_if_broken()` が**新しい読み取り専用の接続**で `quick_check`
    # するので、`cache_size` の値は安全の話ではない（`tests/test_backup.py` の
    # `test_a_page_in_the_writers_cache_is_still_noticed` が守っている）。
    # `cache_size` と `mmap_size` は**ページの大きさを読む**ので、**壊れた DB では投げる**
    # （実測: 先頭 4 KB を潰した DB で `DatabaseError: file is not a database`）。
    # ここで落とすと「壊れた DB でも起動して 503 で案内する」道（§0.12-5）が**開けなくなる**
    # ので、**最善努力**にする（速さの話であって、正しさの話ではない）。
    try:
        con.execute("PRAGMA mmap_size = 268435456")     # 256 MB
    except sqlite3.Error as exc:
        log.warning("mmap_size を掛けられませんでした（壊れた DB の道）: %s", exc)
    if not read_only:
        con.execute("PRAGMA journal_mode = WAL")
        con.execute("PRAGMA synchronous = NORMAL")
    return con


DDL = """
-- 設定（理由マスタの system_prompt、バックアップ先、閾値など）
CREATE TABLE IF NOT EXISTS settings (
  key   TEXT PRIMARY KEY,
  value TEXT NOT NULL
);

-- 走査したフォルダ
CREATE TABLE IF NOT EXISTS root (
  path     TEXT PRIMARY KEY,       -- 正規化した鍵
  display_path TEXT NOT NULL,
  added_at TEXT NOT NULL
);

-- 判断の理由（利用者が編集できる。builtin は削除できない）
CREATE TABLE IF NOT EXISTS reason_code (
  id         TEXT PRIMARY KEY,
  label      TEXT NOT NULL,
  applies_to TEXT NOT NULL CHECK (applies_to IN ('keep', 'reject', 'both')),
  position   INTEGER NOT NULL DEFAULT 0,
  builtin    INTEGER NOT NULL DEFAULT 0,
  active     INTEGER NOT NULL DEFAULT 1
);

-- まとまり（レビューの単位）
CREATE TABLE IF NOT EXISTS review_group (
  id          TEXT PRIMARY KEY,
  title       TEXT,
  kind        TEXT NOT NULL CHECK (kind IN ('manual', 'request', 'duplicates', 'batch')),
  source      TEXT NOT NULL DEFAULT 'manual',
  source_ref  TEXT,
  policy      TEXT NOT NULL DEFAULT 'pick_one'
              CHECK (policy IN ('pick_one', 'pick_many', 'all_reject_only')),
  state       TEXT NOT NULL DEFAULT 'open' CHECK (state IN ('open', 'decided')),
  created_at  TEXT NOT NULL,
  decided_at  TEXT,
  decided_by  TEXT,
  -- 書き出しの判定は**この 2 列**で行う（ファイルの mtime は使わない。点検 B1）
  changed_at  TEXT NOT NULL,
  exported_at TEXT
);
CREATE INDEX IF NOT EXISTS ix_group_dirty ON review_group(exported_at, changed_at);

-- 画像（内容が正体。id は ULID、sha256 は別）
CREATE TABLE IF NOT EXISTS asset (
  id                   TEXT PRIMARY KEY,
  sha256               TEXT NOT NULL UNIQUE,
  kind                 TEXT NOT NULL CHECK (kind IN ('generated', 'reference', 'photo')),
  kind_source          TEXT NOT NULL DEFAULT 'auto',
  width                INTEGER,
  height               INTEGER,
  format               TEXT,
  review_state         TEXT NOT NULL DEFAULT 'unreviewed'
                       CHECK (review_state IN ('unreviewed', 'kept', 'rejected')),
  review_reason_code_id TEXT REFERENCES reason_code(id),
  reviewed_at          TEXT,
  reviewed_by          TEXT,
  first_seen_at        TEXT NOT NULL,
  last_seen_at         TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_asset_state ON asset(review_state);
CREATE INDEX IF NOT EXISTS ix_asset_kind ON asset(kind);

-- 場所（従属。path は正規化した鍵）
CREATE TABLE IF NOT EXISTS asset_location (
  path         TEXT PRIMARY KEY,
  display_path TEXT NOT NULL,
  asset_id     TEXT NOT NULL REFERENCES asset(id) ON DELETE CASCADE,
  size         INTEGER NOT NULL,
  mtime_ns     INTEGER NOT NULL,
  is_primary   INTEGER NOT NULL DEFAULT 0,
  missing_at   TEXT,
  last_seen_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_location_asset ON asset_location(asset_id);
CREATE INDEX IF NOT EXISTS ix_location_missing ON asset_location(missing_at);

-- 来歴（PNG / sidecar から取ったもの。json のまま持つ）
CREATE TABLE IF NOT EXISTS asset_meta (
  asset_id     TEXT PRIMARY KEY REFERENCES asset(id) ON DELETE CASCADE,
  meta_json    TEXT NOT NULL,
  note         TEXT,
  source       TEXT NOT NULL DEFAULT 'png',
  extracted_at TEXT NOT NULL
);

-- パスの中身が入れ替わった履歴・場所を繋ぎ直した履歴（P8-6 で 3 列足した）
-- - `path` は**人が見る表記**（`display_path`）。鍵（`normalize_path`）は `asset_location` が正
-- - `reason` は 'replaced'（同じパスの中身が入れ替わった）/ 'relinked'（参照切れを繋ぎ直した）。
--   **古い行は NULL**（列を足す前の入れ替わり。読む側は NULL を 'replaced' と同じに扱う）
-- - `to_path` は再リンクの**移動先**（入れ替わりの行は NULL）
-- - `actor` は再リンクした人（`human` / `agent`。走査の入れ替わりは NULL）
CREATE TABLE IF NOT EXISTS location_history (
  id                   INTEGER PRIMARY KEY AUTOINCREMENT,
  asset_id             TEXT NOT NULL,
  path                 TEXT NOT NULL,
  size                 INTEGER,
  mtime_ns             INTEGER,
  replaced_by_asset_id TEXT,
  replaced_at          TEXT NOT NULL,
  -- ★ P8-6。**（P8-6 の設計の穴）** 設計 §0.11 は「`location_history` に『入れ替わった』
  --   『繋ぎ直した』を残す」と言うが、**この 2 つを区別する列が無かった**ので足した。
  --   版は上げない（`TOP_UP_COLUMNS` が既存の DB にも当てる＝`pre-topup-*` の控えが付く）
  to_path              TEXT,
  reason               TEXT CHECK (reason IN ('replaced', 'relinked')),
  actor                TEXT CHECK (actor IN ('human', 'agent'))
);

-- まとまりの項目（枚数の上限は無い。点検 B6/G8）
CREATE TABLE IF NOT EXISTS group_item (
  group_id TEXT NOT NULL REFERENCES review_group(id) ON DELETE CASCADE,
  asset_id TEXT NOT NULL REFERENCES asset(id) ON DELETE CASCADE,
  position INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (group_id, asset_id)
);
CREATE INDEX IF NOT EXISTS ix_group_item_asset ON group_item(asset_id);

-- 判断の台帳（追記のみ。消さない・書き換えない）
CREATE TABLE IF NOT EXISTS decision (
  id             TEXT PRIMARY KEY,
  seq            INTEGER NOT NULL,          -- 挿入順。順序の判定はこれだけ（点検 C11）
  subject_type   TEXT NOT NULL CHECK (subject_type IN ('asset', 'group')),
  subject_id     TEXT NOT NULL,
  group_id       TEXT REFERENCES review_group(id),
  verdict        TEXT NOT NULL CHECK (verdict IN ('keep', 'reject', 'clear')),
  reason_code_id TEXT REFERENCES reason_code(id),
  note           TEXT,
  actor          TEXT NOT NULL CHECK (actor IN ('human', 'agent')),
  group_decision TEXT CHECK (group_decision IN ('selected', 'not_selected', 'all_rejected')),
  supersedes     TEXT REFERENCES decision(id),
  client_token   TEXT,                      -- 送り直しに耐える（部分索引で重複を弾く）
  created_at     TEXT NOT NULL              -- 表示用。順序には使わない
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_decision_token
  ON decision(client_token) WHERE client_token IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS ux_decision_seq ON decision(seq);
CREATE INDEX IF NOT EXISTS ix_decision_subject ON decision(subject_type, subject_id, seq DESC);
CREATE INDEX IF NOT EXISTS ix_decision_group ON decision(group_id, seq DESC);
"""


def migrate(con: sqlite3.Connection) -> int:
    """スキーマを最新にする。**何度呼んでも安全**。

    `executescript` は実行の前に暗黙で COMMIT するので、明示的な BEGIN/COMMIT で囲まない
    （囲むと「no transaction is active」で落ちる）。DDL はすべて `IF NOT EXISTS` なので、
    途中で落ちてもやり直せば同じ状態になる。

    版ごとの手当ては**足すだけ**。既にある版の手当ては書き換えない（済んだ DB に二度当てない）。
    """
    current = con.execute("PRAGMA user_version").fetchone()[0]
    if current >= SCHEMA_VERSION:
        # **版を上げずに列を足した版の手当て**（P4-1 の監査 A-1）。v5 は途中で
        # `tag.known` / `asset_tag.actor` / `job.note` を足したので、**先に v5 になった DB** が
        # 列の無いまま残りうる（`current < 5` の道を通らないので、ここで補う）。
        _top_up_v5(con)
        # v6 も同じ流儀（**版を上げずに列を足したら、ここで補う**。P4-1 の監査 A-1）
        _top_up_v6(con)
        return current
    if current < 1:
        con.executescript(DDL)
        _seed_settings(con)
    if current < 2:
        _migrate_v2(con)
    if current < 3:
        _migrate_v3(con)
    if current < 4:
        _migrate_v4(con)
    if current < 5:
        _migrate_v5(con)
    if current < 6:
        _migrate_v6(con)
    elif current == 6:
        # **（P8-0 の監査 C-1 を v7 でも守る）** 版だけ 6 を名乗る DB（P7 の v6。控えの
        # `.backup/pre-p7-*` が該当）は `current < 6` を通らない。v7 に上げるこの道でも
        # **P8 の表・列を補う**（`_migrate_v6` は全部 `IF NOT EXISTS` と `PRAGMA table_info` なので
        # 何度呼んでも同じ）。**ここを外すと、P7 の v6 は v7 になったのに `deletion_log` を
        # 一生持たない**（`test_v6_tables_are_added_to_a_p7_style_v6_database` が守る）。
        _migrate_v6(con)
    if current < 7:
        _migrate_v7(con)
    con.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
    return SCHEMA_VERSION


def _migrate_v2(con: sqlite3.Connection) -> None:
    """v2: まとまりの結論を `review_group` の列に持つ（点検 C2）。

    契約の `Group.decision` / `reason_code_id` / `note` と 1 対 1 にする。
    `decision(subject_type='group')` の最新行から引く形にすると、
    **台帳に行を書かない `reopen`（点検 G7）** と組み合わせたときに
    「open なのに結論が在る」状態が作れてしまう。

    `ALTER TABLE ADD COLUMN` は `IF NOT EXISTS` を持たないので、**列を見てから足す**。
    こうすると v1 からの更新でも、新規作成（DDL → ここ）でも同じ結果になる。
    """
    have = {row["name"] for row in con.execute("PRAGMA table_info(review_group)")}
    if "reason_code_id" not in have:
        con.execute("ALTER TABLE review_group ADD COLUMN reason_code_id TEXT"
                    " REFERENCES reason_code(id)")
    if "decision" not in have:
        con.execute("ALTER TABLE review_group ADD COLUMN decision TEXT"
                    " CHECK (decision IN ('selected', 'all_rejected'))")
    if "note" not in have:
        con.execute("ALTER TABLE review_group ADD COLUMN note TEXT")


# v3 で作る表（設計 §2 の `comparison_cache`。**点検 D1** を反映した形）。
# - `algo_version`: 縮小のフィルタや指標の式を変えたら**全部無効**にする。引くときも条件に入れる
# - `phash_distance` は**置かない**（64bit のハミング距離はマイクロ秒で出る。書き込む方が高い）
# - `ix_comparison_a` は**作らない**（主キー `(a_id, b_id)` の前置と重なる）
COMPARISON_CACHE_DDL = """
CREATE TABLE IF NOT EXISTS comparison_cache (
  a_id             TEXT NOT NULL,          -- a_id < b_id に正規化して入れる
  b_id             TEXT NOT NULL,
  algo_version     INTEGER NOT NULL,       -- 点検 D1。引くときに必ず条件に入れる
  ssim             REAL,
  changed_fraction REAL,
  mean_abs         REAL,
  computed_at      TEXT NOT NULL,
  PRIMARY KEY (a_id, b_id)
);
"""


def _migrate_v3(con: sqlite3.Connection) -> None:
    """v3: pHash / dHash を `asset` に足し、比較の指標のキャッシュを作る（P5-3）。

    - ハッシュは **16 進 16 文字の TEXT**。符号なし 64bit は SQLite の符号付き `INTEGER` に
      入らない（`design.md` §5.1・`duplicates-deletion-backup.md` §1.3）。
      書き手は `compare.capture_hashes()`（サムネイルを作る復号と同じ 1 回。**実測 F5**）
    - **点検 D1**: `phash_distance` の列を置かず、`ix_comparison_a` も作らない（上の DDL の注記）。
      `algo_version` を足し、**引くときも必ず版を条件に入れる**（`compare.cached_pair_metrics`）
    - `ALTER TABLE ADD COLUMN` は `IF NOT EXISTS` を持たないので、**列を見てから足す**（v2 と同じ）。
      こうすると v2 からの更新でも、新規作成（DDL → v2 → ここ）でも同じ結果になる
    """
    have = {row["name"] for row in con.execute("PRAGMA table_info(asset)")}
    if "phash" not in have:
        con.execute("ALTER TABLE asset ADD COLUMN phash TEXT")
    if "dhash" not in have:
        con.execute("ALTER TABLE asset ADD COLUMN dhash TEXT")
    con.executescript(COMPARISON_CACHE_DDL)


# v4 で作る表（P6 の設計 §2.1。**点検 A1 / A3** を反映した形）。
# - `review_request`: エージェントからの要求（投げてすぐ返り、判断で閉じる）
#   - `ux_request_target_open`: **`open` のときだけ効く部分索引**。同じ `target_key` の
#     `open` を 2 本作らせない（**先に古い方を `superseded` に UPDATE してから INSERT する**。
#     逆順だとこの索引で落ちる。点検 C4）
#   - `response`: 閉じた時点の応答（JSON の文字列）。`reopen` しても答えが変わらないため（点検 §0.2）
# - `annotation`: 画像の上の印。座標は 0〜1 の割合。
#   - **座標は NULL 可**（点検 A1）: 「全部 NULL（画像 1 枚へのメモ）」か「全部あり」の 2 形だけを
#     `CHECK` で許す（片方だけ NULL の行を作らせない）。`design.md` §9.7 の「領域なしの注記」を満たす
# - `review_group.superseded_by`: 差し替えで閉じた**まとまり**の印（点検 A3）。判断が 1 つも無い
#   まとまりにだけ入れる。`state` の `CHECK` は増やさず、列で表す（一覧と `review.json` の既定から外す）
V4_REQUEST_DDL = """
CREATE TABLE IF NOT EXISTS review_request (
  id            TEXT PRIMARY KEY,
  group_id      TEXT NOT NULL REFERENCES review_group(id),
  target_key    TEXT,
  state         TEXT NOT NULL
                CHECK (state IN ('open', 'done', 'declined', 'superseded')),
  ask           TEXT,
  conditions    TEXT,
  origin        TEXT,
  wants         TEXT,
  ai_pick_asset_id TEXT,
  ai_note       TEXT,
  actor         TEXT NOT NULL CHECK (actor IN ('human', 'agent')),
  created_at    TEXT NOT NULL,
  closed_at     TEXT,
  closed_by     TEXT,
  decline_note  TEXT,
  superseded_by TEXT,
  response      TEXT,
  client_token  TEXT
);
CREATE INDEX IF NOT EXISTS ix_request_state ON review_request(state, created_at DESC);
CREATE INDEX IF NOT EXISTS ix_request_group ON review_request(group_id, state);
CREATE UNIQUE INDEX IF NOT EXISTS ux_request_target_open
  ON review_request(target_key) WHERE state = 'open' AND target_key IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS ux_request_token
  ON review_request(client_token) WHERE client_token IS NOT NULL;

CREATE TABLE IF NOT EXISTS annotation (
  id         TEXT PRIMARY KEY,
  asset_id   TEXT NOT NULL REFERENCES asset(id) ON DELETE CASCADE,
  shape      TEXT CHECK (shape IN ('rect', 'ellipse')),
  x REAL, y REAL, w REAL, h REAL,
  body       TEXT,
  actor      TEXT NOT NULL CHECK (actor IN ('human', 'agent')),
  created_at TEXT NOT NULL,
  group_id   TEXT REFERENCES review_group(id),
  client_token TEXT,
  CHECK ((shape IS NULL) = (x IS NULL)
         AND (x IS NULL) = (y IS NULL)
         AND (y IS NULL) = (w IS NULL)
         AND (w IS NULL) = (h IS NULL)
         AND (shape IS NOT NULL OR x IS NULL)),
  -- 座標の範囲（P6-0 の監査 C2）。サービス層の検査をすり抜けても表が守る。
  -- 0〜1 の割合で、幅と高さは正。右端・下端は丸めの誤差を見て 1e-9 まで許す
  CHECK (x IS NULL OR (x >= 0 AND x <= 1 AND y >= 0 AND y <= 1
                       AND w > 0 AND h > 0
                       AND x + w <= 1 + 1e-9 AND y + h <= 1 + 1e-9))
);
CREATE INDEX IF NOT EXISTS ix_annotation_asset ON annotation(asset_id, created_at);
CREATE UNIQUE INDEX IF NOT EXISTS ux_annotation_token
  ON annotation(client_token) WHERE client_token IS NOT NULL;
"""


def _migrate_v4(con: sqlite3.Connection) -> None:
    """v4: 要求（`review_request`）と注記（`annotation`）の表を足す（P6-0）。

    - `ALTER TABLE ADD COLUMN` は `IF NOT EXISTS` を持たないので、**列を見てから足す**
      （v2 / v3 と同じ。v1 からの更新でも新規作成でも同じ結果になる）。
    - DDL はすべて `IF NOT EXISTS` なので、途中で落ちてもやり直せば同じ状態になる。
    """
    con.executescript(V4_REQUEST_DDL)
    have = {row["name"] for row in con.execute("PRAGMA table_info(review_group)")}
    if "superseded_by" not in have:
        con.execute("ALTER TABLE review_group ADD COLUMN superseded_by TEXT")


# v5 で作る表（P4 の設計 §2.1。**利用者の回答 Q1（`tag.known`）と点検 G-1〜G-9** を反映した形）。
# - `tag`: 語の台帳。`name` は**正規形**（小文字・語間は `_`。`rem_(re:zero)` のように**括弧とコロンは
#   語の一部**として残す。点検 A-1 / G-5）。一意性は**大文字小文字を区別する**ので、
#   正規化は**サービス層で必ず通す**（表の `COLLATE` は使わない。後から変えるには表の作り直しが要る）
# - `tag.known`: タグの語彙（CSV 10,861 語）にある語か（利用者の回答 Q1。**PNG の語は語彙に無くても
#   入れる**ので、これで見分ける。検索は既定で `known=1` だけに当てる）
# - `asset_tag`: **出所ごとに 1 行**（主キーが `(asset_id, tag_id, source)`。同じ語が PNG と タガーの
#   両方にあれば 2 行）。`score` は **IllustTagger 経由だけ**入る（WD14Tagger は返さない）
# - `tag_gloss`: 語釈。`edited=1` は**人が直した**印で、訳し直しで上書きしない
# - `job` / `job_item`: 時間のかかる処理（**P4 で初めて作る**。`design.md` §5.5）。
#   遷移の規則はサービス層、語彙だけ `CHECK`（P6 の §0.10 と同じ方針）
V5_TAG_DDL = """
CREATE TABLE IF NOT EXISTS tag (
  id INTEGER PRIMARY KEY,
  name TEXT NOT NULL UNIQUE,
  category INTEGER,
  category_name TEXT,
  -- 語彙（CSV）にある語か。**INSERT OR IGNORE で入れると 0 のまま残る**ので、
  -- 書き込みは `ON CONFLICT ... DO UPDATE SET known = max(known, excluded.known)`（点検 §I-1）
  known INTEGER NOT NULL DEFAULT 0 CHECK (known IN (0, 1))
);

CREATE TABLE IF NOT EXISTS asset_tag (
  asset_id TEXT NOT NULL REFERENCES asset(id) ON DELETE CASCADE,
  tag_id   INTEGER NOT NULL REFERENCES tag(id),
  score    REAL,
  source   TEXT NOT NULL CHECK (source IN ('png', 'wd14', 'manual')),
  model    TEXT,
  -- **誰が付けたか**（点検 §I-4）。手動は `human` / `agent`、タガーの行は NULL。
  -- 「いまは human だけ、必要になったらエージェントにも許す」(Q3) に備えて**いま列を足す**
  -- （`ALTER TABLE` を後で当てなくて済む）
  actor    TEXT,
  tagged_at TEXT NOT NULL,
  PRIMARY KEY (asset_id, tag_id, source)
);
CREATE INDEX IF NOT EXISTS ix_asset_tag_tag ON asset_tag(tag_id, asset_id);

CREATE TABLE IF NOT EXISTS tag_gloss (
  tag_id     INTEGER PRIMARY KEY REFERENCES tag(id) ON DELETE CASCADE,
  ja         TEXT NOT NULL,
  source     TEXT NOT NULL CHECK (source IN ('textgenerate', 'manual')),
  engine     TEXT,
  edited     INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS job (
  id TEXT PRIMARY KEY,
  kind TEXT NOT NULL,
  state TEXT NOT NULL CHECK (state IN ('queued','running','done','failed','cancelled')),
  params TEXT,
  progress_done INTEGER DEFAULT 0,
  progress_total INTEGER,
  message TEXT,
  -- **結果の 1 行の注記**（§0.8-5「採った数と語彙外だった数を結果に残す」）。
  -- `message` は進行の文なので分ける（終わった後も数が読める）
  note TEXT,
  error TEXT,
  created_at TEXT NOT NULL,
  started_at TEXT,
  finished_at TEXT
);
CREATE INDEX IF NOT EXISTS ix_job_state ON job(state, created_at DESC);

CREATE TABLE IF NOT EXISTS job_item (
  job_id TEXT NOT NULL REFERENCES job(id) ON DELETE CASCADE,
  ref    TEXT NOT NULL,
  -- **語彙を CHECK で縛る**（P4-0 の監査の申し送り。P4-1 の実装にある語に合わせた）。
  -- `tagged` = 語を付けた / `skipped` = 既に付いていたので飛ばした / `failed` = 失敗した
  state  TEXT NOT NULL CHECK (state IN ('tagged', 'skipped', 'failed')),
  error  TEXT,
  PRIMARY KEY (job_id, ref)
);
CREATE INDEX IF NOT EXISTS ix_job_item_state ON job_item(job_id, state);
"""


# ---- v6（P8: 重複・削除・バックアップ。**P8-0 は機能を足さない＝表と契約だけ**）----
#
# 出所: `docs/p8-design.md` §2.1（正）・`docs/duplicates-deletion-backup.md` §2.2 / §3.1 / §3.5。
#
# - **段 1（論理削除）**: `asset.deleted_at`。**行は消さない**（判断と来歴を残す）。
#   列なので `CHECK` は付けられない（`ALTER` で足せないため）。**値の検査はサービス層**（設計 §0.13）。
# - **`root.allow_stage3`**: その置き場で**実ファイルの削除（段 3）を許すか**。
#   **既定は 0**（安全側）。別のツールの管理下のフォルダを守るための印（利用者の回答 Q8）。
# - **`deletion_log`**: 削除の台帳。**削除後も消さない**（専門 §3.2 の 4）。
#   `asset_id` に `REFERENCES` を**張らない**（`asset` を消す道を作らないため）。
# - **`delete_request`**（点検 A2）: **再送の鍵は要求の単位**。一括は 1 要求で最大 200 行を書くので、
#   `client_token` を行に持たせると**2 行目で UNIQUE に当たる**。同じ token の再送は `result_json` を返す。
#   **索引名は `ux_delete_token`**（設計は `ux_request_token` と書いていたが、**P6 が `review_request` に
#   同じ名前を使っている**。SQLite の索引名は DB 全体で一意なので、`IF NOT EXISTS` が黙って何もしなくなり、
#   **再送の一意性が守られない**。P8-0 で気づいて改名した）。
# - **`duplicate_exclusion`**: 「別物として確定」した組。**`CHECK (a_id < b_id)` で順序を機械的に守る**
#   （`(A,B)` と `(B,A)` を別行にしない。専門 C10）。
# - **`phash_band`**: 準重複の候補を絞る帯索引（**4bit × 16 本**。専門 §2.2）。
#   `asset` に `ON DELETE CASCADE`。
#   **（P8-1 の監査 B-1）8bit × 8 本から作り直した。** 8bit × 8 本で「1 本は完全に一致する」のは
#   **ハミング距離 ≤ 7** のときだけ（鳩の巣）で、`max_distance` を 64 まで受ける口とは両立しなかった
#   （実測: ≤12 で 3 組・≤16 で 72 組を取りこぼす）。**4bit × 16 本なら保証は ≤15** になる
#   （距離 ≤ 15 なら 16 本のうち 1 本は必ず一致する）。**16 以上は帯で絞らず総当たりに落とす**
#   （`duplicates.candidate_pairs`。263 枚で 20 ms）。
#   **実データの帯は 0 行だったので、作り直しは無料だった**（P8-0 の `CHECK` と同じ判断）。
# - **`pending_delete_preview`**: 一括削除の凍結。**DB に持つ**（再起動をまたいでも「確認した一覧」が失われない）。
#   **実行時に `scope` を評価し直さない**（見せていないファイルを消さないため。専門 §3.5）。
#   `items_json` は **`path`（正規化した鍵）と `display_path`（人に見せる表記）の両方**を持つ（点検 D6）。
#
# **`CHECK` は `ALTER` で足せない**（P7 の教訓）ので、**新表には最初から**付けてある。
V6_DELETE_DDL = """
CREATE TABLE IF NOT EXISTS delete_request (
  id           TEXT PRIMARY KEY,
  client_token TEXT,
  actor        TEXT NOT NULL CHECK (actor IN ('human', 'agent')),
  stage        INTEGER NOT NULL CHECK (stage IN (1, 2, 3)),
  count        INTEGER NOT NULL,
  result_json  TEXT,
  -- **（P8-2）何を頼まれたか**を残す。同じ `client_token` で**違う内容**が来たときに
  -- 気づけるようにする（前の結果を黙って返すと、2 件目の削除が消える。P6 の
  -- `client_token_conflict` と同じ流儀）。列なので `CHECK` は無い（`ALTER` で足すため）
  payload_json TEXT,
  at           TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_delete_token
  ON delete_request(client_token) WHERE client_token IS NOT NULL;

CREATE TABLE IF NOT EXISTS deletion_log (
  id           TEXT PRIMARY KEY,
  asset_id     TEXT,
  path         TEXT,
  stage        INTEGER NOT NULL CHECK (stage IN (1, 2, 3)),
  from_path    TEXT,
  to_path      TEXT,
  hold_path    TEXT,
  remaining_sec INTEGER,
  purge_at     TEXT,
  restored_at  TEXT,
  size         INTEGER,
  request_id   TEXT REFERENCES delete_request(id),
  reason       TEXT,
  -- **（P8-3 の監査 G-3）戻せなかった理由**（`target_exists` / `move_failed` / `different` /
  -- `missing`）。段 3 の取り消しに失敗したときだけ入り、画面の「戻せませんでした」の
  -- 1 行を 4 通りに分けるのに使う（`reason` は「消した理由」で別の物）。版は上げずに足したので
  -- **古い v6 は `_top_up_v6` が `ALTER` で足す**（家風。「同じ版番号で形が違う DB」を塞ぐ）
  stuck_reason TEXT CHECK (stuck_reason IN ('target_exists', 'move_failed', 'different', 'missing')),
  -- **（P10）片付けた印**（利用者の要望「実体が無いので片付ける」。`docs/deletions-advance.md`）。
  -- 登録の場所・ゴミ箱・保留のどこにも実体が無い行を**終わりにする**（`asset.deleted_at` はそのまま
  -- ＝カタログには戻さない。**ファイルは 1 つも消さない・動かさない**）。版は上げずに足すので
  -- **古い v6 は `_top_up_v6` が `ALTER` で足す**（家風）。`close_reason` の語彙は
  -- **サービス層でも守る**（`CHECK` に当てて 500 にしない）
  closed_at    TEXT,
  close_reason TEXT CHECK (close_reason IN ('missing')),
  actor        TEXT NOT NULL CHECK (actor IN ('human', 'agent')),
  at           TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_deletion_pending
  ON deletion_log(restored_at, purge_at) WHERE stage = 3;
CREATE INDEX IF NOT EXISTS ix_deletion_asset ON deletion_log(asset_id, at DESC);
CREATE INDEX IF NOT EXISTS ix_deletion_request ON deletion_log(request_id);

CREATE TABLE IF NOT EXISTS duplicate_exclusion (
  a_id   TEXT NOT NULL,
  b_id   TEXT NOT NULL,
  reason TEXT,
  actor  TEXT NOT NULL CHECK (actor IN ('human', 'agent')),
  at     TEXT NOT NULL,
  PRIMARY KEY (a_id, b_id),
  CHECK (a_id < b_id)
);

CREATE TABLE IF NOT EXISTS phash_band (
  asset_id TEXT NOT NULL REFERENCES asset(id) ON DELETE CASCADE,
  -- **（P8-1 の監査 B-1）4bit × 16 本**。距離 ≤ 15 なら 16 本のうち 1 本は必ず一致する
  band     INTEGER NOT NULL CHECK (band BETWEEN 0 AND 15),
  value    TEXT NOT NULL CHECK (length(value) = 1),
  PRIMARY KEY (asset_id, band)
);
CREATE INDEX IF NOT EXISTS ix_phash_band ON phash_band(band, value);

CREATE TABLE IF NOT EXISTS pending_delete_preview (
  id         TEXT PRIMARY KEY,
  stage      INTEGER NOT NULL CHECK (stage IN (1, 2, 3)),
  scope_json TEXT NOT NULL,
  items_json TEXT NOT NULL,
  count      INTEGER NOT NULL,
  bytes      INTEGER NOT NULL,
  actor      TEXT NOT NULL CHECK (actor IN ('human', 'agent')),
  created_at TEXT NOT NULL,
  expires_at TEXT NOT NULL,
  -- **（P8-2。設計 §0.16 A2 / §4.3）実行しても行を消さない。**
  -- `executed_at` が入っていれば「実行済み」で、2 度目は `result_json` をそのまま返す
  -- （凍結した一覧をもう一度消してしまわない）。`request_id` は要求（`delete_request`）への参照
  executed_at TEXT,
  result_json TEXT,
  request_id  TEXT
);
CREATE INDEX IF NOT EXISTS ix_preview_expiry ON pending_delete_preview(expires_at);
"""


def _migrate_v5(con: sqlite3.Connection) -> None:
    """v5: タグ（`tag` / `asset_tag` / `tag_gloss`）とジョブ（`job` / `job_item`）を足す（P4-0）。

    **機能は足さない**（表と契約だけ）。DDL はすべて `IF NOT EXISTS` なので、
    途中で落ちてもやり直せば同じ状態になる（v2〜v4 と同じ流儀）。

    **P4-0 の監査 A-1（P4-1 の監査 A-1）**: v5 は**版を上げずに列を 3 つ足した**経緯がある
    （`tag.known` / `asset_tag.actor` / `job.note`）。先に v5 になった DB（開発中の複製）には
    その列が無く、**ジョブが `no column named actor` で落ち、その後始末も `no such column: note` で
    落ちて `job` が `running` のまま残る**（監査が再現）。`ALTER TABLE ADD COLUMN` は
    `IF NOT EXISTS` を持たないので、**v2 / v3 / v4 と同じく列を見てから足す**。
    実データ（v3）は 1 回で正しい形の v5 になるので、この手当ては通らない。
    """
    con.executescript(V5_TAG_DDL)
    _top_up_v5(con)


def _top_up_v5(con: sqlite3.Connection) -> None:
    """v5 で**版を上げずに足した列**を補う（P4-1 の監査 A-1）。

    `tag.known` / `asset_tag.actor` / `job.note` は、いったん v5 を作った後に足した。
    そのため**先に v5 になった DB**（開発中の複製）にはこの 3 列が無く、
    **ジョブが `no column named actor` で落ち、その後始末も `no such column: note` で
    落ちて `job` が `running` のまま残る**（監査が再現。次の `POST` が永久に 409）。
    `ALTER TABLE ADD COLUMN` は `IF NOT EXISTS` を持たないので、**列を見てから足す**
    （v2 / v3 / v4 と同じ流儀）。**何度呼んでも安全**（`migrate()` の early return 側からも呼ぶ）。
    """
    have_tag = {row["name"] for row in con.execute("PRAGMA table_info(tag)")}
    if have_tag and "known" not in have_tag:
        # 古い v5 には `CHECK` を後から足せない（表の作り直しが要る）。値だけ揃える
        con.execute("ALTER TABLE tag ADD COLUMN known INTEGER NOT NULL DEFAULT 0")
    have_at = {row["name"] for row in con.execute("PRAGMA table_info(asset_tag)")}
    if have_at and "actor" not in have_at:
        con.execute("ALTER TABLE asset_tag ADD COLUMN actor TEXT")
    have_job = {row["name"] for row in con.execute("PRAGMA table_info(job)")}
    if have_job and "note" not in have_job:
        con.execute("ALTER TABLE job ADD COLUMN note TEXT")
    # 古い v5 の `job_item.state` には `CHECK` が無い（`ALTER` では足せない）。
    # 語彙の外の値が入っていたら `failed` に寄せる（落とさない）
    if {row["name"] for row in con.execute("PRAGMA table_info(job_item)")}:
        con.execute("UPDATE job_item SET state = 'failed' WHERE state NOT IN"
                    " ('tagged', 'skipped', 'failed')")


def _migrate_v6(con: sqlite3.Connection) -> None:
    """v6: 重複・削除・バックアップの表と列を足す（P8-0）。**機能は足さない**。

    - **`asset.deleted_at`**（段 1 の論理削除。列なので `CHECK` は付けられない＝値はサービス層）
    - **`root.allow_stage3`**（その置き場で実ファイルの削除を許すか。**既定 0**）
    - **`V6_DELETE_DDL` の 5 表**（`delete_request` / `deletion_log` / `duplicate_exclusion` /
      `phash_band` / `pending_delete_preview`）と索引

    実データ（v5）は 1 回で正しい形の v6 になる。**既にある版の手当ては書き換えない**。
    """
    con.executescript(V6_DELETE_DDL)
    _top_up_v6(con)


def _top_up_v6(con: sqlite3.Connection) -> None:
    """v6 で**版を上げずに足した物**を補う（P4-1 の監査 A-1 と同じ流儀）。

    `ALTER TABLE ADD COLUMN` は `IF NOT EXISTS` を持たないので、**列を見てから足す**。
    **何度呼んでも安全**（`migrate()` の early return 側からも呼ぶ）。
    新しい列には `CHECK` を付けられる（P7 の `fetched` で実績）ので、`allow_stage3` には付ける。

    **（P8-0 の監査 C-1）表そのものもここで作る。** P7 が `user_version = 6` を付けた DB
    （控えの `.backup/pre-p7-*` が該当）は `current >= SCHEMA_VERSION` の**早期 return** に当たって
    `_migrate_v6` を通らないので、**P8 の 5 表を一生持たない**（版は 6 と答えるので気づきにくく、
    P8-1 以降で `no such table: deletion_log` になる）。`V6_DELETE_DDL` は**全部 `IF NOT EXISTS`**
    なので、ここでも流して害が無い（`_migrate_v6` と二重でも同じ結果になる）。

    **（P8-2）`pending_delete_preview` の `executed_at` / `result_json` / `request_id` と
    `delete_request.payload_json` もここで足す**（実データの v6 はこの列が無い形で先に作ってある）。
    `CREATE TABLE IF NOT EXISTS` は既存の表に列を足さないので、**列を見てから `ALTER`**。

    **（P8-4 の監査 D-2 / G-5）列の一覧は `TOP_UP_COLUMNS` が正。** ここはその表を回すだけに
    して、`missing_top_ups()`（控えを取る判断）と**同じ物を見る**ようにした
    （2 か所に書くと、片方だけ足したときに控え無しで形が変わる）。
    """
    con.executescript(V6_DELETE_DDL)
    # **（P8-1 の監査 B-1）帯を 4bit × 16 本に作り直した。** 古い 8bit × 8 本の表を持っている DB は
    # `CHECK (band BETWEEN 0 AND 7)` のせいで**新しい帯（8〜15）を入れられない**。`CREATE TABLE
    # IF NOT EXISTS` は既存の表を変えないので、**帯だけ落として作り直す**（帯は `asset.phash` から
    # いつでも引き直せる＝失う物が無い。実データは帯 0 行だったので無料だった）。
    band_sql = con.execute("SELECT sql FROM sqlite_master WHERE type = 'table'"
                           " AND name = 'phash_band'").fetchone()
    if band_sql is not None and "BETWEEN 0 AND 15" not in (band_sql[0] or ""):
        con.execute("DROP TABLE phash_band")
        con.executescript(V6_DELETE_DDL)
    for table, column, ddl in TOP_UP_COLUMNS:
        have = {row[1] for row in con.execute(f"PRAGMA table_info({table})")}
        if have and column not in have:
            con.execute(ddl)
    # 「消えた物だけ」を引く（生きている 263 枚の索引を太らせない）
    if con.execute("SELECT 1 FROM sqlite_master WHERE type = 'table'"
                   " AND name = 'asset'").fetchone() is not None:
        con.execute("CREATE INDEX IF NOT EXISTS ix_asset_del"
                    " ON asset(deleted_at) WHERE deleted_at IS NOT NULL")
    # **（P8-1 の監査 B-1）帯の中身も新しい形に揃える。** 版は 6 のままなので、表の形だけ直しても
    # 古い 8bit の帯が残る（`phash_band` を落とした DB もここで埋まる）。何度呼んでも同じ。
    # **落とした直後は 0 行**なので、**「本数が違う物」だけでなく「1 本も無い物」も埋める**
    # （`fill_missing_bands`。これを忘れると帯が空のまま**重複が 1 群も出なくなる**——
    # 静かに壊れて気づきにくい。合成 1 万枚の測定で実際に踏んだ）。
    from .duplicates import fill_missing_bands, rebuild_stale_bands   # 循環 import を避けて局所で
    rebuild_stale_bands(con)
    fill_missing_bands(con)


#: **版を上げずに足す列**（表, 列, `ALTER` の SQL）。`_top_up_v6` と `missing_top_ups` が
#: **同じ物を見る**ための 1 か所（P8-4 の監査 D-2 / G-5）。**足す物を増やすときはここに足す**
#: （`pre-topup-*` の控えが自動で付く）。
TOP_UP_COLUMNS: tuple[tuple[str, str, str], ...] = (
    # 段 1（論理削除）。**NULL = 生きている**。列なので `CHECK` は付けられない
    ("asset", "deleted_at", "ALTER TABLE asset ADD COLUMN deleted_at TEXT"),
    # その置き場で実ファイルの削除を許すか（**既定 0**。P8-0）
    ("root", "allow_stage3", "ALTER TABLE root ADD COLUMN allow_stage3 INTEGER NOT NULL"
                             " DEFAULT 0 CHECK (allow_stage3 IN (0, 1))"),
    # **（P8-1 の監査 C-1）中断の印**（`JobService` と `DuplicatesService` が同じ印を見る）
    ("job", "cancel_requested", "ALTER TABLE job ADD COLUMN cancel_requested INTEGER NOT NULL"
                                " DEFAULT 0 CHECK (cancel_requested IN (0, 1))"),
    # **（P8-2）凍結した一覧は実行後も消さない**
    ("pending_delete_preview", "executed_at",
     "ALTER TABLE pending_delete_preview ADD COLUMN executed_at TEXT"),
    ("pending_delete_preview", "result_json",
     "ALTER TABLE pending_delete_preview ADD COLUMN result_json TEXT"),
    ("pending_delete_preview", "request_id",
     "ALTER TABLE pending_delete_preview ADD COLUMN request_id TEXT"),
    # **（P8-2）要求の内容**（同じ `client_token` で違う内容が来たことに気づくため）
    ("delete_request", "payload_json", "ALTER TABLE delete_request ADD COLUMN payload_json TEXT"),
    # **（P8-3 の監査 G-3）「戻せなかった理由」を台帳に残す**
    ("deletion_log", "stuck_reason",
     "ALTER TABLE deletion_log ADD COLUMN stuck_reason TEXT"
     " CHECK (stuck_reason IN ('target_exists', 'move_failed', 'different', 'missing'))"),
    # **（P10）片付けた印**（`closed_at` と理由）。**版は上げない**ので、実データには
    # `Store` が開く前の `pre-topup-*` の控えが付いてから足される（`missing_top_ups`）。
    # 「実体が無いので片付ける」で行を終わりにする（`deletions.py` の `close`）
    ("deletion_log", "closed_at", "ALTER TABLE deletion_log ADD COLUMN closed_at TEXT"),
    ("deletion_log", "close_reason",
     "ALTER TABLE deletion_log ADD COLUMN close_reason TEXT"
     " CHECK (close_reason IN ('missing'))"),
    # **（P8-6）再リンクを履歴に残す**（移動先・理由・人）。
    # 設計 §0.11 は「入れ替わった」「繋ぎ直した」を `location_history` に残せと言うが、
    # **この 2 つを区別する列が無かった**（`path` は移動元、`replaced_by_asset_id` は入れ替わりの相手）。
    # **`DDL` にも同じ 3 列がある**（新しい DB はそちらで作る。**列の順序は末尾で揃えてある**）
    ("location_history", "to_path", "ALTER TABLE location_history ADD COLUMN to_path TEXT"),
    ("location_history", "reason",
     "ALTER TABLE location_history ADD COLUMN reason TEXT"
     " CHECK (reason IN ('replaced', 'relinked'))"),
    ("location_history", "actor",
     "ALTER TABLE location_history ADD COLUMN actor TEXT CHECK (actor IN ('human', 'agent'))"),
)


def missing_top_ups(con: sqlite3.Connection) -> list[str]:
    """**版を上げずに足す物のうち、まだ足りていない物**（P8-4 の監査 D-2 / G-5）。

    `Store` が開く前にこれを見て、空でなければ `pre-topup-*` の控えを取る
    （実データで `deletion_log.stuck_reason` が**控え無しで**足された。
    版は 6 のままなので `pre-migrate-*` の道を通らない）。

    **表そのものが無い DB は「足りていない」に数えない**（新規の DB は `migrate()` が
    `CREATE TABLE` から作るので、控えを取る意味が無い）。帯の形（8bit × 8 本）も見る。
    """
    out: list[str] = []
    for table, column, _ddl in TOP_UP_COLUMNS:
        have = {row[1] for row in con.execute(f"PRAGMA table_info({table})")}
        if have and column not in have:
            out.append(f"{table}.{column}")
    band = con.execute("SELECT sql FROM sqlite_master WHERE type = 'table'"
                       " AND name = 'phash_band'").fetchone()
    if band is not None and "BETWEEN 0 AND 15" not in (band[0] or ""):
        out.append("phash_band.band(0..15)")
    return out


# ---- v7（P2-0: 取り込みとカタログ。**機能は足さない＝表と列だけ**）----
#
# 出所: `docs/design.md` §5.3（カタログの表）・§6.1（カタログの口）・§10.1〜§10.2（仮想フォルダと
# スマートフォルダ）・§5.1（取り込み元）。**P2 の設計書は無い**（`docs/p2-design.md` は作られていない）ので、
# 本文の `design.md` が正。
#
# - **表の名前は `folder` と `folder_member`。** 指示書の `folder_item` / `smart_folder` は設計に無い。
#   スマートフォルダは**別の表ではなく `folder.kind='smart'` の行**で、条件は `smart_query` に持つ
#   （§5.3 の DDL・§10.2）。**`sort_key` / `note` も設計に無い**（並びは `position`）。
# - **`folder.deleted_at` は §5.3 の DDL に無いが、§6.1 が「既定は論理削除（`deleted_at`）」と決めている**
#   ので足した（**設計の穴**。この列が無いと P2-1 の `DELETE /api/folders/{id}` が作れない）。
# - **`folder.name` に UNIQUE は付けない。** 設計 §5.3 は名前の一意を要求していない（`parent_id` の
#   階層があり、別の親の下の同名は普通にある）。同名を作らせない規則が要るなら**サービス層**（親の中で一意）
#   にする（`UNIQUE(parent_id, name)` は根（`parent_id IS NULL`）の重複を SQLite が許すので、
#   そのままでは「一意」にならない。NULL を含む一意性の罠。`p8-design.md` §2.2）。
# - **`folder_member` の `asset_id` は論理削除（`asset.deleted_at`）では消さない。** 行が消えるのは
#   `asset` の行を**物理で消した**とき（`ON DELETE CASCADE`）。論理削除した枚をカタログに出さないのは
#   **読む側**（`deleted_at IS NULL`）の仕事（P2-1）。
# - **取り込み元の列は `asset` に足す**（§5.1 の `source` / `source_url` / `ref_tags`）。設計の
#   `source_ref` は **`review_group` の列**（要求 ID など）で、取り込みとは別物。**取り込みの履歴の表は
#   設計に無い**ので作らない（`asset.source` と `asset.source_url` がその記録）。
#   **実装はいま `asset_meta.source` を「出所」として返している**（`store._asset_dict`）。値は全行
#   `'scan'` で、上の `DEFAULT 'scan'` と同じ。P2-1 で**読み書きを `asset.source` に寄せる**（申し送り）。
V7_CATALOG_DDL = """
-- 仮想フォルダ（設計 §5.3）。**実ファイルは動かさない**（§10.1）。`kind='smart'` は条件で貯まる
CREATE TABLE IF NOT EXISTS folder (
  id              TEXT PRIMARY KEY,                          -- ULID
  parent_id       TEXT REFERENCES folder(id) ON DELETE CASCADE,   -- NULL = 根
  name            TEXT NOT NULL,                             -- **一意ではない**（親が違えば同名可）
  kind            TEXT NOT NULL CHECK (kind IN ('manual', 'smart')),
  smart_query     TEXT,                                      -- kind='smart' の条件（JSON。§10.2）
  position        INTEGER NOT NULL DEFAULT 0,                -- 同じ親の中の並び
  count_cache     INTEGER,                                   -- 中の枚数（概算のキャッシュ。§10.2）
  count_cached_at TEXT,
  created_at      TEXT NOT NULL,
  -- **§5.3 の DDL には無いが、§6.1 が論理削除を要求する**（設計の穴。P2-1 で使う）
  deleted_at      TEXT
);
CREATE INDEX IF NOT EXISTS ix_folder_parent ON folder(parent_id, position);

-- 多対多（設計 §5.3・§10.1）。同じ画像を複数のフォルダに置ける。**主キーは 2 つ**
CREATE TABLE IF NOT EXISTS folder_member (
  folder_id TEXT NOT NULL REFERENCES folder(id) ON DELETE CASCADE,
  asset_id  TEXT NOT NULL REFERENCES asset(id) ON DELETE CASCADE,
  position  INTEGER NOT NULL DEFAULT 0,                      -- フォルダの中の並び
  added_at  TEXT NOT NULL,
  PRIMARY KEY (folder_id, asset_id)
);
CREATE INDEX IF NOT EXISTS ix_folder_member_asset ON folder_member(asset_id);
"""

#: v7 で `asset` に足す列（設計 §5.1 の取り込み元）。
#: `ALTER TABLE ADD COLUMN` は `IF NOT EXISTS` を持たないので、**列を見てから足す**（v2〜v6 と同じ流儀）。
#: `source` は **NOT NULL DEFAULT 'scan'**。実データの 463 枚はすべて走査で入ったので、その値が正しい
#: （`asset_meta.source` も全行 `'scan'` だった）。`drop` / `clipboard` / `url` / `watch` は P2-1 以降が書く。
V7_ASSET_COLUMNS: tuple[tuple[str, str], ...] = (
    ("source", "ALTER TABLE asset ADD COLUMN source TEXT NOT NULL DEFAULT 'scan'"
               " CHECK (source IN ('scan', 'drop', 'clipboard', 'url', 'watch'))"),
    ("source_url", "ALTER TABLE asset ADD COLUMN source_url TEXT"),
    ("ref_tags", "ALTER TABLE asset ADD COLUMN ref_tags TEXT"),   # 「何の参考か」の JSON 配列（§5.1）
)

#: v7 の表 → **列の形**。`PRAGMA table_info` の `(型, NOT NULL, 既定値, 主キーの位置)`。
#:
#: **名前だけでは足りない**（P2-0 の監査 B-1）。`CREATE TABLE IF NOT EXISTS` は同じ名前の別の表を
#: 変えないので、**同じ列名で `NOT NULL` も `CHECK` も無い `folder`** を先に置かれると、
#: 版だけ 7 の「中身の違う v7」ができる（実測: 監査の `squat2`。`folder.name` に NULL が入り、
#: `kind` に何でも入った）。ここは**列の名前ではなく形**を見る。
#: `asset` は既存の表なので、**v7 で足した `source` の形だけ**を見る。
V7_TABLE_SHAPE: dict[str, dict[str, tuple[str, int, str | None, int]]] = {
    "folder": {
        "id": ("TEXT", 0, None, 1),
        "parent_id": ("TEXT", 0, None, 0),
        "name": ("TEXT", 1, None, 0),
        "kind": ("TEXT", 1, None, 0),
        "smart_query": ("TEXT", 0, None, 0),
        "position": ("INTEGER", 1, "0", 0),
        "count_cache": ("INTEGER", 0, None, 0),
        "count_cached_at": ("TEXT", 0, None, 0),
        "created_at": ("TEXT", 1, None, 0),
        "deleted_at": ("TEXT", 0, None, 0),
    },
    "folder_member": {
        "folder_id": ("TEXT", 1, None, 1),
        "asset_id": ("TEXT", 1, None, 2),
        "position": ("INTEGER", 1, "0", 0),
        "added_at": ("TEXT", 1, None, 0),
    },
    "asset": {
        "source": ("TEXT", 1, "'scan'", 0),
    },
}

#: v7 の外部キー → `(この表の列, 参照する表, 参照する列, ON DELETE)`。
#: **`folder.parent_id` と `folder_member` の 2 本は `CASCADE`**（設計 §5.3）。
#: `REFERENCES` が無い・`ON DELETE SET NULL` になっていると、**親を消しても子が残る**。
V7_FOREIGN_KEYS: dict[str, tuple[tuple[str, str, str, str], ...]] = {
    "folder": (("parent_id", "folder", "id", "CASCADE"),),
    "folder_member": (
        ("folder_id", "folder", "id", "CASCADE"),
        ("asset_id", "asset", "id", "CASCADE"),
    ),
}

#: v7 の索引 → `(索引の名前, 表, 列の並び)`。**索引名は DB 全体で一意**なので、
#: 同じ名前が他の表にあると `CREATE INDEX IF NOT EXISTS` は**黙って何もしない**
#: （P8-0 の監査 C-0 で `ux_request_token` が実際に踏んだ）。**同じ表の同じ名前でも
#: 列が違えば使えない**（P2-0 の監査 B-1: `ix_folder_parent ON folder(name)`）ので、列まで見る。
#: **期待値は `tests/test_p2_0.py` にリテラルで書く**（ここから作ると、索引を消す変異が通る＝B-2）。
V7_INDEXES: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("ix_folder_parent", "folder", ("parent_id", "position")),
    ("ix_folder_member_asset", "folder_member", ("asset_id",)),
)

#: v7 で **`CHECK` で守る語彙**（`sqlite_master.sql` を空白を詰めて比べる）。
#: `CHECK` が無いと `kind` に 'robot'、`source` に 'ftp' が入る（P2-0 の監査 B-1）。
V7_CHECK_SQL: dict[str, tuple[str, str]] = {
    "folder": ("kind", "check(kindin('manual','smart'))"),
    "asset": ("source", "check(sourcein('scan','drop','clipboard','url','watch'))"),
}


def _migrate_v7(con: sqlite3.Connection) -> None:
    """v7: カタログ（仮想フォルダ・スマートフォルダ）と取り込み元の列を足す（P2-0）。

    **機能は足さない**（表と列だけ。P2-1 が口、P2-2 以降が画面）。設計は `design.md` §5.3・§6.1・
    §10.1〜§10.2・§5.1。表の名前と形は**設計の字**に合わせた（`folder` / `folder_member`。
    `folder_item` / `smart_folder` は作らない。上の `V7_CATALOG_DDL` の注記）。

    **実データ（v6）は 1 回で正しい形の v7 になる。** `migrate()` の早期 return 側には何も足していない——
    v7 は**版を上げて**足すので、`user_version = 7` を名乗る DB に v7 の表が無い形は作れない
    （途中で落ちた DB は版が 6 のままなので、次の起動でこの関数をもう一度通る。P8-0 の `_top_up_v6` は
    P7 が**同じ 6 を名乗って別の表を作った**事故の手当てで、v7 にはその事情が無い）。
    """
    con.executescript(V7_CATALOG_DDL)
    have = {row[1] for row in con.execute("PRAGMA table_info(asset)")}
    if have:                                    # `asset` は v1 から在る（無ければ v1 の DDL から作る）
        for column, ddl in V7_ASSET_COLUMNS:
            if column not in have:
                con.execute(ddl)
    _check_v7_shape(con)


def _schema_sql(con: sqlite3.Connection, name: str) -> str:
    """`sqlite_master` の `sql` を**空白を詰めて小文字に**した物（`CHECK` の比較用）。

    `ALTER TABLE ADD COLUMN` で足した列も `sqlite_master.sql` に載る（実測: v6 から上げた
    `asset` の `sql` に `CHECK (source IN (…))` が入る）。空白の入れ方は SQLite が文を
    そのまま覚えるので、**空白だけ落として比べれば**書き方の違いに強い。
    """
    row = con.execute("SELECT sql FROM sqlite_master WHERE type = 'table' AND name = ?",
                      (name,)).fetchone()
    return "".join(str(row[0] or "").split()).lower() if row is not None else ""


def _check_v7_shape(con: sqlite3.Connection) -> None:
    """v7 の表・列・索引・外部キーが**狙った形で**在ることを確かめる（黙って無効にならないように）。

    なぜ要るか（3 つとも実際に踏んだ型）:

    - `CREATE TABLE IF NOT EXISTS` は**同じ名前の別の表**があると黙って何もしない
    - `CREATE INDEX IF NOT EXISTS` は**索引名が DB 全体で一意**なので、同じ名前が他の表にあると
      黙って何もしない（P8-0 の監査 C-0。`ux_request_token` が `review_request` に在ったため
      `delete_request` の一意索引が作られず、**再送の二重削除**が通った）
    - **名前だけを見るガードは「同じ列名で中身が違う表」を通す**（P2-0 の監査 B-1）。
      同じ列名で `NOT NULL` も `CASCADE` も `CHECK` も無い `folder` と、列の違う
      `ix_folder_parent` を v6 に先に置くと、**版は 7・`kind` に何でも入る・親を消しても子が残る**
      という v7 ができた（実測）。ここは**形**（`NOT NULL`・既定・主キー・外部キーの
      `ON DELETE`・索引の列・`CHECK`）まで見る。

    どれも「版は 7・名前は在るのに中身が違う」という**静かな穴**になるので、ここで落とす
    （`sqlite3.DatabaseError` ではなく `RuntimeError`。呼び手は起動を止めるので、人はログで気づく）。
    **落ちる時の文には何が違うかを書く**（「索引 ix_folder_parent の列が parent_id,position でない
    （いま name）」）。

    **何度呼んでも同じ**（表・索引・外部キーは読むだけ。**語彙の `CHECK` だけは `SAVEPOINT` で
    1 行入れて拒否されるかを見て、必ず `ROLLBACK TO` で戻す**）。
    """
    for table, shape in V7_TABLE_SHAPE.items():
        got = {row[1]: (str(row[2] or "").upper(), int(row[3]), row[4], int(row[5]))
               for row in con.execute(f"PRAGMA table_info({table})")}
        if not got:
            raise RuntimeError(
                f"v7 の表 {table} がありません（同じ名前の別の物が使っています）")
        missing = [column for column in shape if column not in got]
        if missing:
            raise RuntimeError(
                f"v7 の表 {table} の列が足りません: {', '.join(missing)}")
        for column, (want_type, want_notnull, want_default, want_pk) in shape.items():
            got_type, got_notnull, got_default, got_pk = got[column]
            different = []
            if got_type != want_type:
                different.append(f"型が {got_type or '空'}（期待 {want_type}）")
            if got_notnull != want_notnull:
                different.append("`NOT NULL` がありません" if want_notnull
                                 else "`NOT NULL` が余計にあります")
            if got_default != want_default:
                different.append(f"既定が {got_default!r}（期待 {want_default!r}）")
            if got_pk != want_pk:
                different.append(f"主キーの位置が {got_pk}（期待 {want_pk}）")
            if different:
                raise RuntimeError(
                    f"v7 の表 {table}.{column} の形が違います: " + "、".join(different))
    for table, wanted in V7_FOREIGN_KEYS.items():
        got_fks = [(row[3], row[2], row[4], row[6])
                   for row in con.execute(f"PRAGMA foreign_key_list({table})")]
        for source, target, target_column, on_delete in wanted:
            matches = [fk for fk in got_fks if fk[0] == source]
            if not matches:
                raise RuntimeError(
                    f"v7 の外部キー {table}.{source} → {target}({target_column}) がありません"
                    "（設計 §5.3 の `ON DELETE CASCADE` が効きません）")
            fk = matches[0]
            if fk[1:] != (target, target_column, on_delete):
                raise RuntimeError(
                    f"v7 の外部キー {table}.{source} が {target}({target_column}) の"
                    f" `ON DELETE {on_delete}` ではありません"
                    f"（いま {fk[1]}({fk[2]}) の `ON DELETE {fk[3]}`）")
    for name, table, columns in V7_INDEXES:
        row = con.execute("SELECT tbl_name FROM sqlite_master WHERE type = 'index'"
                          " AND name = ?", (name,)).fetchone()
        if row is None or row[0] != table:
            where = row[0] if row is not None else "どこにも無い"
            raise RuntimeError(
                f"v7 の索引 {name} を {table} に作れませんでした（同じ名前が {where} にあります）")
        got_columns = tuple(info[2] for info in con.execute(f"PRAGMA index_info({name})"))
        if got_columns != tuple(columns):
            raise RuntimeError(
                f"v7 の索引 {name} の列が {','.join(columns)} でない"
                f"（いま {','.join(got_columns) or 'なし'}）")
    # **語彙は `CHECK` の文と、実際に拒むかの両方で見る**（P2-0 の監査 B-1）。
    # 文だけだと、同じ語彙を**別の列**に書いた表を通す。振る舞いだけだと、`asset` の
    # `source` を試すのに 1 行要る（空の DB では `UPDATE` が 0 行に当たって何も分からない）。
    for table, (column, clause) in V7_CHECK_SQL.items():
        if clause not in _schema_sql(con, table):
            raise RuntimeError(
                f"v7 の表 {table}.{column} に語彙の `CHECK` がありません"
                f"（`{clause}`。設計の語彙を表でも守る）")
    # **不正な kind を入れて拒否されるか**（SAVEPOINT で必ず戻す）
    probe = f"__v7_shape_probe_{os.getpid()}__"
    con.execute("SAVEPOINT v7_shape")
    try:
        try:
            con.execute("INSERT INTO folder(id, parent_id, name, kind, position, created_at)"
                        " VALUES (?, NULL, ?, 'robot', 0, 'probe')", (probe, probe))
        except sqlite3.IntegrityError:
            pass                                  # 期待どおり（CHECK が拒んだ）
        else:
            raise RuntimeError(
                "v7 の表 folder.kind の `CHECK` が効いていません（'robot' を受け付けました。"
                "設計 §5.3 は 'manual' / 'smart' だけ）")
    finally:
        con.execute("ROLLBACK TO v7_shape")
        con.execute("RELEASE v7_shape")


def _seed_settings(con: sqlite3.Connection) -> None:
    rows = [
        ("undo_window_sec", "300"),
        ("preview_ttl_sec", "600"),
        ("export_delay_sec", "2"),
        ("backup_dir", str(Path(os.path.expanduser("~")) / "image-reviewer-backups")),
        ("next_after_decision", "1"),
    ]
    con.executemany("INSERT OR IGNORE INTO settings(key, value) VALUES (?, ?)", rows)


def quick_check(con: sqlite3.Connection) -> dict:
    """`PRAGMA quick_check` を**例外ごと受ける**（P8-4。設計 §0.12-5・点検 B3）。

    **例外も「壊れている」に数える。** `fetchall()` の中身だけで判定すると、
    壊れた DB ほど 500 になる（実測: 2 ページ目を 0 で潰すと
    `sqlite3.DatabaseError: database disk image is malformed`、
    先頭 4 KB を潰すと `file is not a database`。どちらも `quick_check` が投げる）。

    **行が `ok` 1 行でない場合も「壊れている」**にする。300 ページ目を潰した複製は
    例外を投げずに**エラーの行**を返す（実測: `*** in database main ***` と
    `wrong # of entries in index …`）。`fetchone()[0]` だけを見ると
    「壊れているのに `ok` 以外の文字列」になり、判定が 2 通りに散る。

    戻り値: `ok`（真偽）/ `detail`（人に見せる 1 行）/ `rows` / `error`（例外の文言）。
    """
    try:
        rows = [str(row[0]) for row in con.execute("PRAGMA quick_check").fetchall()]
    except sqlite3.DatabaseError as exc:
        return {"ok": False, "detail": str(exc), "rows": [], "error": str(exc)}
    if rows == ["ok"]:
        return {"ok": True, "detail": "ok", "rows": rows, "error": None}
    return {"ok": False, "detail": rows[0] if rows else "(行が返らない)",
            "rows": rows, "error": None}


def integrity(con: sqlite3.Connection) -> dict:
    """健全性。起動時と `doctor` で使う。

    **（P8-4）壊れた DB でも落ちない。** 前の版は `PRAGMA quick_check` の
    `fetchone()[0]` を直に呼んでいたので、壊れた DB ではこの関数そのものが例外になった
    （設計 §1.2 の線 12 が「結果が出る」ことを要求している）。
    `quick_check` は**文字列のまま**残す（既存の呼び出しが `== "ok"` で見ている）。
    """
    got = quick_check(con)
    try:
        fk = con.execute("PRAGMA foreign_key_check").fetchall()
        version = con.execute("PRAGMA user_version").fetchone()[0]
        journal = con.execute("PRAGMA journal_mode").fetchone()[0]
    except sqlite3.DatabaseError as exc:          # 先頭 4 KB を潰した DB（開けない）
        got = {"ok": False, "detail": got["detail"] if got["error"] else str(exc),
               "rows": got["rows"], "error": got["error"] or str(exc)}
        fk, version, journal = [], None, None
    return {"quick_check": got["detail"], "quick_check_ok": got["ok"],
            "quick_check_error": got["error"], "quick_check_rows": got["rows"],
            "foreign_key_violations": len(fk), "schema_version": version,
            "journal_mode": journal}


def open_db(data_dir: str | Path, *, read_only: bool = False,
            check_same_thread: bool = True) -> sqlite3.Connection:
    """接続してマイグレーションまで済ませる（通常はこれを使う）。

    **（P8-4）`read_only=True` ではマイグレーションを走らせない。** 読み取り専用の接続で
    `PRAGMA user_version = 7` や `CREATE TABLE` を流すと `attempt to write a readonly
    database` で落ちる（壊れた DB を「読み取り専用で起動」する道そのものが開かなくなる）。
    """
    con = connect(data_dir, read_only=read_only, check_same_thread=check_same_thread)
    if read_only:
        return con
    try:
        migrate(con)
    except Exception:
        con.close()
        raise
    return con


def next_seq(con: sqlite3.Connection) -> int:
    """台帳の次の `seq`。トランザクションの中で呼ぶ。"""
    row = con.execute("SELECT COALESCE(MAX(seq), 0) + 1 AS n FROM decision").fetchone()
    return int(row["n"])
