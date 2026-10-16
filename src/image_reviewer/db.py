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
- **v4（P6-0）** は要求と注記、**v5（P4-0）** はタグとジョブ（それぞれ `V4_REQUEST_DDL` / `V5_TAG_DDL`）。
- **v6（P7-0）**: 条件の記録（`recipe_record` / `recipe_export_attempt` / `recipe_export` /
  `recipe_export_result` / `preset`）と監視の既読位置（`watcher_state`）を足す。**機能は足さない**。
  **新しい表だけ**なので `ALTER TABLE` は使わず、**v6 の手当ては 1 回で終わる**（v5 のように
  「版を上げずに列を足した」経緯が無いので `_top_up_v6` は作らない）。詳細は
  `docs/p7-design.md` §2.1（**この段の正**）
"""

from __future__ import annotations

import os
import sqlite3
import time
import uuid
from pathlib import Path

SCHEMA_VERSION = 6

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
    """
    data_dir = Path(data_dir)
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

-- パスの中身が入れ替わった履歴
CREATE TABLE IF NOT EXISTS location_history (
  id                   INTEGER PRIMARY KEY AUTOINCREMENT,
  asset_id             TEXT NOT NULL,
  path                 TEXT NOT NULL,
  size                 INTEGER,
  mtime_ns             INTEGER,
  replaced_by_asset_id TEXT,
  replaced_at          TEXT NOT NULL
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
        # **v6 も同じ**（P7-4 で `recipe_export_result.fetched` を足した。表は空だったので
        # v7 は作らず v6 の DDL を直し、**既に v6 の DB にはここで列を足す**）。
        _top_up_v5(con)
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
    _top_up_v6(con)
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


def _top_up_v6(con: sqlite3.Connection) -> None:
    """v6 の**版を上げずに足した列**の手当て（P7-4）。

    `recipe_export_result.fetched`（`GET /view` で取り込んだか）を後から足した。
    表はまだ空だったので **v7 は作らず v6 の DDL を直した**が、**先に v6 になった DB**
    （P7-0〜P7-3 の間に `migrate()` が走った物）には列が無い。`current >= SCHEMA_VERSION`
    の early return 側からも呼ぶので、**既に v6 の DB にも 1 回で入る**。
    `PRAGMA table_info` を見てから足す（`ALTER TABLE ADD COLUMN` は `IF NOT EXISTS` を
    持たないため）。**何度呼んでも安全。**
    """
    have = {row["name"] for row in con.execute("PRAGMA table_info(recipe_export_result)")}
    if have and "fetched" not in have:
        # 既存の行は「取り込んでいない」＝ 0 で埋まる（この時点で行は 0 件のはずだが、
        # 実データで 1 件でもあれば参照のままだった可能性が高いので 0 が正しい）
        #
        # **（再確認 G-5）`CHECK` も付ける**: 付けないと、**新規の v6**（DDL に `CHECK` がある）と
        # **後から足した v6**（無い）で**同じ版番号なのに形が 2 つ**になる。
        # SQLite の `ALTER TABLE ADD COLUMN` は列の制約として `CHECK` を受け付ける。
        con.execute("ALTER TABLE recipe_export_result ADD COLUMN fetched INTEGER NOT NULL DEFAULT 0"
                    " CHECK (fetched IN (0, 1))")


# v6 で作る表（P7 の設計 §2.1。**点検 A-2 / B-3-1 / C-1〜C-4 / G-3〜G-5** を反映した形）。
# **機能は足さない**（表だけ）。設計 §2.1 が**この段の正**。
# - `recipe_record`: 元画像 1 枚の生成条件の写し（**生成はしない**）。`ux_recipe_source` で
#   **画像 1 枚に 1 記録**（点検 C-1 / G-5）。`reasons` は**記録時の 7 語だけ**（点検 A-3。mode に
#   依存する `text_pinned` / `llm_nondeterministic` / `manual_step` は書き出し時＝`checked_json` へ）
# - `recipe_export_attempt`: **書き出しの束**（点検 A-2b）。前の版は束の表が無く、manifest・印の理由・
#   検査の結果・`seed_node` の置き場が無かった。`client_token` の再送は**同じ `attempt_id`** を返す
# - `recipe_export`: 束の中の **1 ファイル＝1 seed**。`marker` と `marker_skip_reason` は
#   **片方だけ**（点検 A-2a の `CHECK`。前の版は `marker` が NOT NULL で「印なし」を表せなかった）
# - `ux_export_attempt_seed` は **`COALESCE(seed,'')` の式の索引**（点検 A-2c）。前の版の
#   `UNIQUE(attempt_id, seed)` は **seed が NULL のとき効かない**（実測で同じ束に 2 行入った）
# - `recipe_export_result`: 結果 1 枚。`result_asset_id` は **`ON DELETE SET NULL`**（点検 C-3 / G-3。
#   画像を消しても「どんな条件で出したか」は残す）。合否は上書き（`verdict_at` / `verdict_actor`）
# - `preset`: 名前を付けた条件（§4.10）。`source_asset_id` も **`ON DELETE SET NULL`**
# - `watcher_state`: 監視の既読位置（`design.md` §5.5 の DDL。**現物に無かったので P7 で作る**）。
#   既読の基準は `baseline_create_time`（ms。点検 B-3-1。`last_prompt_id` は UUID なので順序に使えない）。
#   `enabled` は**起動のたびに 0 に戻す**（勝手に ComfyUI を叩かない）
# - **`recipe_record.source_asset_id` は RESTRICT のまま**（記録のある画像は消せない）。P8（重複・削除）へ
#   「記録ごと消すか断るか」を申し送る（§2.1 の末尾）
V6_RECIPE_DDL = """
CREATE TABLE IF NOT EXISTS recipe_record (
  id              TEXT PRIMARY KEY,
  source_asset_id TEXT NOT NULL REFERENCES asset(id),
  mode            TEXT NOT NULL CHECK (mode IN ('pin_text', 'rerun_graph', 'manual_text')),
  recipe_hash     TEXT NOT NULL,
  graph_path      TEXT,
  graph_kind      TEXT CHECK (graph_kind IN ('api', 'api+ui')),   -- 点検 G-2（NULL は許す）
  record_json     TEXT NOT NULL,
  final_prompt    TEXT,
  final_prompt_source TEXT CHECK (final_prompt_source IN ('png_literal', 'reconstructed', 'manual')),
  captured_text   TEXT,
  captured_source TEXT CHECK (captured_source IN
                    ('comfyui_history', 'sidecar', 'textgenerate', 'manual')),  -- 点検 G-2（NULL は許す）
  text_probe      TEXT,
  env_snapshot    TEXT NOT NULL,
  status          TEXT NOT NULL CHECK (status IN ('exact', 'approx', 'impossible')),
  reasons         TEXT,
  actor           TEXT NOT NULL CHECK (actor IN ('human', 'agent')),
  client_token    TEXT,
  created_at      TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_recipe_source ON recipe_record(source_asset_id);
CREATE UNIQUE INDEX IF NOT EXISTS ux_recipe_token
  ON recipe_record(client_token) WHERE client_token IS NOT NULL;
CREATE INDEX IF NOT EXISTS ix_recipe_created ON recipe_record(created_at DESC, id DESC);

CREATE TABLE IF NOT EXISTS recipe_export_attempt (
  attempt_id    TEXT PRIMARY KEY,
  recipe_id     TEXT NOT NULL REFERENCES recipe_record(id),
  mode          TEXT NOT NULL CHECK (mode IN ('pin_text', 'rerun_graph', 'manual_text')),
  client_token  TEXT,
  marker_skip_reason TEXT CHECK (marker_skip_reason IN ('前提1', '前提2', '前提3')),
  checked_json  TEXT,
  manifest_path TEXT,
  export_dir    TEXT NOT NULL,
  seed_node     TEXT,
  created_at    TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_attempt_token
  ON recipe_export_attempt(client_token) WHERE client_token IS NOT NULL;
CREATE INDEX IF NOT EXISTS ix_attempt_recipe
  ON recipe_export_attempt(recipe_id, created_at DESC);

CREATE TABLE IF NOT EXISTS recipe_export (
  id            TEXT PRIMARY KEY,
  attempt_id    TEXT NOT NULL REFERENCES recipe_export_attempt(attempt_id) ON DELETE CASCADE,
  seed          TEXT,
  recipe_hash   TEXT NOT NULL,
  graph_path    TEXT NOT NULL,
  marker        TEXT,
  marker_skip_reason TEXT CHECK (marker_skip_reason IN ('前提1', '前提2', '前提3')),
  created_at    TEXT NOT NULL,
  CHECK ((marker IS NULL) <> (marker_skip_reason IS NULL))
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_export_attempt_seed
  ON recipe_export(attempt_id, COALESCE(seed, ''));
-- **`ix_export_attempt` は作らない**（点検 C-2 / G-4）: 主キーが `attempt_id` の前置と重なる
-- （`ix_attempt_recipe` が同じ役目。P5 の D1 と同じ判断）

CREATE TABLE IF NOT EXISTS recipe_export_result (
  id              TEXT PRIMARY KEY,
  -- **束を消すと結果も消える**（点検 G-1。束 → ファイルの CASCADE と揃える）
  export_id       TEXT NOT NULL REFERENCES recipe_export(id) ON DELETE CASCADE,
  prompt_id       TEXT,
  result_asset_id TEXT REFERENCES asset(id) ON DELETE SET NULL,
  matched_by      TEXT NOT NULL CHECK (matched_by IN ('marker', 'manual', 'conditions')),
  result_hash     TEXT,
  same_hash       INTEGER NOT NULL DEFAULT 0,
  ssim REAL, phash_distance INTEGER, changed_fraction REAL, mean_abs REAL,
  seed_changed    INTEGER NOT NULL DEFAULT 0,
  verdict         TEXT CHECK (verdict IN ('same', 'close', 'different', 'failed')),
  verdict_at      TEXT,
  verdict_actor   TEXT CHECK (verdict_actor IN ('human', 'agent')),
  note            TEXT,
  -- **`GET /view` で `<data>/results/` に取り込んだか**（P7-4 で足した。1 = 取り込んだ＝
  -- 複製を持っている、0 = ComfyUI の出力フォルダの実体を指しているだけ）。
  -- **参照のままか複製か**を画面と後始末（P8）が区別できるようにする
  fetched         INTEGER NOT NULL DEFAULT 0 CHECK (fetched IN (0, 1)),
  created_at      TEXT NOT NULL,
  -- **合否と人は対で入る**（点検 G-2。片方だけの行を作らせない）
  CHECK ((verdict IS NULL) = (verdict_actor IS NULL))
);
CREATE INDEX IF NOT EXISTS ix_result_export ON recipe_export_result(export_id, created_at);
CREATE UNIQUE INDEX IF NOT EXISTS ux_result_asset
  ON recipe_export_result(export_id, result_asset_id);

CREATE TABLE IF NOT EXISTS preset (
  id              TEXT PRIMARY KEY,
  name            TEXT NOT NULL,
  note            TEXT,
  source_asset_id TEXT REFERENCES asset(id) ON DELETE SET NULL,
  record_json     TEXT NOT NULL,
  actor           TEXT NOT NULL CHECK (actor IN ('human', 'agent')),
  created_at      TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_preset_created ON preset(created_at DESC, id DESC);

CREATE TABLE IF NOT EXISTS watcher_state (
  name           TEXT PRIMARY KEY,
  last_prompt_id TEXT,
  baseline_create_time INTEGER,
  last_polled_at TEXT,
  enabled        INTEGER NOT NULL DEFAULT 0,
  updated_at     TEXT
);
"""


def _migrate_v6(con: sqlite3.Connection) -> None:
    """v6: 条件の記録と監視の既読位置を足す（P7-0）。**機能は足さない**（表だけ）。

    DDL はすべて `IF NOT EXISTS` なので、途中で落ちてもやり直せば同じ状態になる（v2〜v5 と同じ流儀）。
    **新しい表だけ**なので `ALTER TABLE` を見る必要が無く、`_top_up_v6` は作らない
    （v5 は「版を上げずに列を足した」ので `_top_up_v5` が要った。v6 にはその経緯が無い）。
    """
    con.executescript(V6_RECIPE_DDL)


def _seed_settings(con: sqlite3.Connection) -> None:
    rows = [
        ("undo_window_sec", "300"),
        ("preview_ttl_sec", "600"),
        ("export_delay_sec", "2"),
        ("backup_dir", str(Path(os.path.expanduser("~")) / "image-reviewer-backups")),
        ("next_after_decision", "1"),
    ]
    con.executemany("INSERT OR IGNORE INTO settings(key, value) VALUES (?, ?)", rows)


def integrity(con: sqlite3.Connection) -> dict:
    """健全性。起動時と `doctor` で使う。"""
    quick = con.execute("PRAGMA quick_check").fetchone()[0]
    fk = con.execute("PRAGMA foreign_key_check").fetchall()
    return {"quick_check": quick, "foreign_key_violations": len(fk),
            "schema_version": con.execute("PRAGMA user_version").fetchone()[0],
            "journal_mode": con.execute("PRAGMA journal_mode").fetchone()[0]}


def open_db(data_dir: str | Path, *, read_only: bool = False,
            check_same_thread: bool = True) -> sqlite3.Connection:
    """接続してマイグレーションまで済ませる（通常はこれを使う）。"""
    con = connect(data_dir, read_only=read_only, check_same_thread=check_same_thread)
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
