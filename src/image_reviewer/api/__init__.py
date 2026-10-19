"""P5-1 のルーター（`app.py` の閉包から出す。点検 C13）。

設計: docs/p5-design.md §3・§9

- `store` は `app.state` から取る（閉包で掴まない）
- **actor はヘッダ `X-Image-Reviewer-Actor` だけから取る。本文の `actor` は見ない。**
  無ければ `agent` として扱い、`ReviewService` が 403 にする（点検 A2）
- `ReviewError` は 1 つのハンドラで HTTP に写す（規則を 2 か所に書かない）
"""

from __future__ import annotations

import sqlite3

from fastapi import Request
from fastapi.responses import JSONResponse

from ..annotations import AnnotationService
from ..export import ExportService
from ..review import ReviewError, ReviewService
from ..review_requests import ReviewRequestService
from ..store import Store

ACTOR_HEADER = "X-Image-Reviewer-Actor"


def review_of(request: Request) -> ReviewService:
    return request.app.state.review


def requests_of(request: Request) -> ReviewRequestService:
    """要求の口（P6-1a）。`app.state` から取る（閉包で掴まない）。"""
    return request.app.state.requests


def store_of(request: Request) -> Store:
    """比較（P5-2）が使う。読み出しだけ（書き込みは `ReviewService` を通す）。"""
    return request.app.state.store


def export_of(request: Request) -> ExportService:
    return request.app.state.export


def annotations_of(request: Request) -> AnnotationService:
    """注記の口（P6-2）。`app.state` から取る（閉包で掴まない）。"""
    return request.app.state.annotations


def jobs_of(request: Request):
    """タグ付けの背景ジョブ（P4-1）。`app.state` から取る（閉包で掴まない）。"""
    return request.app.state.jobs


def gloss_of(request: Request):
    """語釈（P4-2）。`app.state` から取る（閉包で掴まない）。"""
    return request.app.state.gloss


def duplicates_of(request: Request):
    """重複の検出と整理（P8-1）。`app.state` から取る（閉包で掴まない）。"""
    return request.app.state.duplicates


def deletions_of(request: Request):
    """削除の 3 段階と取り消し（P8-2）。`app.state` から取る（閉包で掴まない）。"""
    return request.app.state.deletions


def backup_of(request: Request):
    """バックアップと復元（P8-4）。`app.state` から取る（閉包で掴まない）。"""
    return request.app.state.backup


def relink_of(request: Request):
    """参照切れの再リンク（P8-6）。`app.state` から取る（閉包で掴まない）。"""
    return request.app.state.relink


def require_human(actor: str, *, what: str = "この操作") -> str:
    """**人が要る口の検査を 1 か所に置く**（家風。P4 の §0.14 Q3 から続く流儀）。

    `actor` を返すので、そのまま `actor` 欄に使える。エージェントには **403 `human_only`**。
    設計 §3.1 は「計算と除外は人だけ」（**重い計算を投げる口と、候補を消す口**）。
    """
    if actor != "human":
        raise ReviewError(403, f"{what}は人だけができます", details={"actor": actor},
                          code="human_only")
    return actor


def actor_of(request: Request) -> str:
    """点検 A2: actor は**ヘッダだけ**から取る。無ければ `agent`（＝判断は 403）。

    P6-1a の監査 A1: `human` / `agent` 以外は **422**。以前はそのまま `review_request.actor` /
    `annotation.actor` に入り、表の `CHECK` に当たって **500**（ログに `IntegrityError`）になっていた。
    """
    got = (request.headers.get(ACTOR_HEADER) or "").strip()
    if not got:
        return "agent"
    if got not in ("human", "agent"):
        raise ReviewError(422, "actor は human / agent のいずれかです", details={"actor": got})
    return got


def review_error_handler(request: Request, exc: ReviewError) -> JSONResponse:
    """`ReviewError` → JSON。`details` と `code` を落とさない（`missing` / `extra` / `group_decided`）。"""
    body: dict = {"detail": exc.detail}
    if exc.code:
        body["code"] = exc.code
    if exc.details:
        body["details"] = exc.details
    return JSONResponse(body, status_code=exc.status)


def sqlite_error_handler(request: Request, exc: sqlite3.DatabaseError) -> JSONResponse:
    """**壊れたページを触った `GET` を 500 にしない**（P8-4 の監査 C-3）。

    `quick_check` が通る壊れ方（2 ページ目を潰した形）でも、**そのページに載っている表**を
    触る口は素の `sqlite3.DatabaseError`（`database disk image is malformed`）で 500 に
    なっていた（監査の実測: 台帳 3 本）。読み取り専用で起動しているなら、番号は
    **503 `read_only`**（本文に `mode` / `reason` / 案内）にして、画面がそのまま案内できる形にする。

    読み取り専用でない（走ったまま壊れた）ときは `code` を `db_error` にして、
    **DB そのものが壊れている**ことを伝える（どちらも 503。500 にしない）。

    ---

    **（P9。P8-6 の監査 D-8）ここは `sqlite3.DatabaseError` ぜんぶを受けていた。**
    `DatabaseError` は `IntegrityError` と `OperationalError` の**親**なので、
    「DB が壊れている」の写しが**壊れていない DB にも掛かっていた**——実測（P9）:
    1 万枚の合成 DB で `GET /api/assets` が
    `{"code": "db_error", "details": {"reason": "malformed", "error": "unable to open
    database file"}}` を返し、**画面は「バックアップから戻してください」と言った**
    （本当の原因は一時ファイルを作れないこと。**DB は健全**）。

    そこで**語彙を分ける**:

    - **壊れている仲間**（`malformed` / `not a database` / `corrupt` / `encrypted`）だけ 503
      （今までどおり。読み取り専用なら `read_only`）
    - **（P9 の監査 D-1）`disk i/o error` は「壊れている」に数えない。** 一時的な I/O の失敗
      （USB の抜け・ウイルス対策の掴み）にも「バックアップから戻してください」と言っていた。
      503 **`io_error`** ＋ `Retry-After` にして「もう一度」を案内する（**復元は勧めない**）
    - **（P9 の監査 D-2）`database is locked` は「混んでいる」**（`busy_timeout` 15 秒の後なので
      稀）。内部エラー（500）ではなく 503 **`busy`** ＋ `Retry-After: 1`
    - それ以外（`unable to open database file`・`no such table`・`IntegrityError` など）は
      **500 `sqlite_error`**。**「バックアップから戻してください」とは言わない**
      （壊れているとは限らない）

    `kind` に例外のクラス名を入れる（`IntegrityError` か `OperationalError` かがログ無しで分かる）。
    """
    store = getattr(getattr(request.app, "state", None), "store", None)
    state = getattr(getattr(request.app, "state", None), "db_state", None) or {}
    read_only = bool(getattr(store, "read_only", False))
    if _is_io_error(exc):
        # **（P9 の監査 D-1 / G-6）復元を勧めない。** 一時的な読み書きの失敗
        return JSONResponse(
            {"detail": "DB の読み書きで一時的なエラーが起きました。少し待って、"
                       "もう一度試してください（バックアップから戻す必要はありません）",
             "code": "io_error",
             "details": {"kind": type(exc).__name__, "error": str(exc),
                         "read_only": read_only, "mode": state.get("mode")}},
            status_code=503, headers={"Retry-After": "5"})
    if _is_busy(exc):
        # **（P9 の監査 D-2）「混んでいる」は 500 ではなく 503 ＋ もう一度**
        # **（B-10）** 「処理」は `frontend-design.md` §6 の使わない語。起きていることをそのまま書く
        return JSONResponse(
            {"detail": "DB がいま混んでいます（ほかの書き込みが進んでいます）。"
                       "少し待って、もう一度試してください",
             "code": "busy",
             "details": {"kind": type(exc).__name__, "error": str(exc),
                         "read_only": read_only, "mode": state.get("mode")}},
            status_code=503, headers={"Retry-After": "1"})
    if not _is_corruption(exc):
        # **壊れているとは限らない**。番号も文言も分ける（D-8）
        return JSONResponse(
            {"detail": "DB の操作で内部エラーが起きました（DB が壊れているとは限りません）",
             "code": "sqlite_error",
             "details": {"kind": type(exc).__name__, "error": str(exc),
                         "read_only": read_only, "mode": state.get("mode")}},
            status_code=500)
    body: dict = {
        "detail": ("DB が壊れているので読めません（読み取り専用で起動しています）。"
                   "バックアップから戻してください" if read_only
                   else "DB が壊れているので読めません。バックアップから戻してください"),
        "code": "read_only" if read_only else "db_error",
        "details": {"reason": "malformed", "error": str(exc), "read_only": read_only,
                    "mode": state.get("mode")},
    }
    guidance = state.get("guidance")
    if guidance:
        body["guidance"] = guidance
    return JSONResponse(body, status_code=503)


#: 「DB が壊れている」と言ってよい SQLite の言い方（**ここが 1 か所**。D-8）
#: **（P9 の監査 D-1）`disk i/o error` はここから外した**（一時的な失敗でもある）
CORRUPTION_WORDS = ("malformed", "not a database", "corrupt", "encrypted",
                    "file is encrypted")

#: **一時的な読み書きの失敗**（D-1 / G-6）。503 `io_error` ＋ `Retry-After`。復元を勧めない
IO_WORDS = ("disk i/o error",)

#: **混んでいる**だけの言い方（D-2）。503 `busy` ＋ `Retry-After`
BUSY_WORDS = ("database is locked", "database table is locked", "database schema is locked",
              "busy")


def _is_corruption(exc: BaseException) -> bool:
    """その `DatabaseError` は**壊れている仲間**か（P9。D-8）。

    例外の**クラスでは分けられない**（`OperationalError` も `IntegrityError` も
    `DatabaseError` の子で、「壊れている」も「一時ファイルが作れない」も
    `OperationalError` で来る）。SQLite の**文言**で分ける（`quick_check` の判定と同じ流儀）。
    """
    text = str(exc).lower()
    return any(word in text for word in CORRUPTION_WORDS)


def _is_io_error(exc: BaseException) -> bool:
    """その `DatabaseError` は**一時的な読み書きの失敗**か（P9 の監査 D-1）。

    `disk i/o error` は「壊れている」ではなく**もう一度で直りうる**（USB の抜け・
    ウイルス対策の掴み・ネットワークドライブの瞬断）。**復元を勧めない**。
    """
    text = str(exc).lower()
    return any(word in text for word in IO_WORDS)


def _is_busy(exc: BaseException) -> bool:
    """その `DatabaseError` は**混んでいる**だけか（P9 の監査 D-2）。"""
    text = str(exc).lower()
    return any(word in text for word in BUSY_WORDS)

