"""**実データを事故で開かない**（P8-6 の硬化）のテスト。

事故 3 件の型（P8-4 の監査 G-8／G-9・P8-6 の 3 件目）は、どれも
「**環境変数の無いまま `create_app()` が既定の `.data` を書き込み可で開いた**」ことから
始まっている:

1. `import image_reviewer.app` でモジュールの末尾が `create_app()` を走らせていた（G-8）
2. 版を上げずに列を足す道（`_top_up_v6`）に控えが無かった（G-9。実データに `stuck_reason`）
3. **P8-6**: 実装者が `IMAGE_REVIEWER_DATA` を付けずに `create_app()` を呼び、
   実データに `location_history` の 3 列が足された（`.backup/pre-p8-6-*` に控え）

いまは `create_app()` が**開く前に断る**。ここはその 1 点だけを見る。
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from image_reviewer import cli
from image_reviewer.app import DATA_ENV, DEFAULT_DATA_DIR, create_app

REPO = Path(__file__).resolve().parents[1]


def real_data_signature(root: Path) -> list[tuple[str, int, int]]:
    """実データの中身の署名（**名前・大きさ・mtime**）。無ければ空。

    **`-shm` だけは mtime を数えない**: SQLite の共有メモリは **`mode=ro` で開くだけでも
    mtime が動く**（並行して別の担当が読むと揺れる）ので、**書き込みの証拠にならない**。
    大きさは見る（消えたり増えたりは捕まえる）。
    """
    if not root.exists():
        return []
    out = []
    for p in root.rglob("*"):
        if not p.is_file():
            continue
        mtime = 0 if p.name.endswith("-shm") else p.stat().st_mtime_ns
        out.append((str(p.relative_to(root)), p.stat().st_size, mtime))
    return sorted(out)


def child_env(*, with_data: Path | None) -> dict:
    """子プロセスの環境（`IMAGE_REVIEWER_DATA` を**必ず外してから**必要なら足す）。"""
    env = {**os.environ}
    env.pop(DATA_ENV, None)
    env.pop("PYTHONPATH", None)
    if with_data is not None:
        env[DATA_ENV] = str(with_data)
    return env


def run_python(code: str, env: dict) -> subprocess.CompletedProcess:
    """子プロセスで 1 回走らせる（**`-X utf8`**。コンソールが cp932 でも文言が読める）。

    `errors="replace"` を付けるのは、cp932 のバイト列で読み取りのスレッドが落ちると
    `stderr` が `None` になり、**何が起きたか分からなくなる**ため（実際に踏んだ）。
    """
    return subprocess.run([sys.executable, "-X", "utf8", "-c", code], cwd=str(REPO), env=env,
                          capture_output=True, text=True, encoding="utf-8", errors="replace",
                          timeout=120)


# ---- 1. env が無ければ断る（別プロセス。実データが 1 バイトも変わらない）----


def test_create_app_refuses_without_the_data_env_and_writes_nothing():
    """**`IMAGE_REVIEWER_DATA` 無しの `create_app()` は例外になり、実データを触らない。**

    壊すと落ちる: 既定を決め打ちして開く（＝事故 3 件の型。実データに `_top_up_v6` の
    `ALTER` が当たる）。**例外の文面に環境変数の名前が出る**ことも見る（人はそこを直す）。

    実データは `mode=ro` の読み（**`rglob` と `stat` だけ**）。`.data` が無い複製
    （別の機械）では署名の比較だけを飛ばす。
    """
    before = real_data_signature(DEFAULT_DATA_DIR)
    got = run_python("import image_reviewer.app as m\nm.create_app()\n", child_env(with_data=None))
    assert got.returncode != 0, "env 無しで create_app() が通ってしまった"
    assert DATA_ENV in got.stderr, got.stderr[-2000:]
    assert "IMAGE_REVIEWER_DATA=<複製>" in got.stderr
    assert real_data_signature(DEFAULT_DATA_DIR) == before, "実データが変わった"
    # **遅延の道（`image_reviewer.app:app`）も同じ**（uvicorn を env 無しで起動した形）
    got2 = run_python("import image_reviewer.app as m\nm.app\n", child_env(with_data=None))
    assert got2.returncode != 0 and DATA_ENV in got2.stderr, got2.stderr[-2000:]
    assert real_data_signature(DEFAULT_DATA_DIR) == before, "実データが変わった"


def test_create_app_opens_when_the_env_points_at_a_copy(tmp_path: Path, monkeypatch):
    """**複製を指せば開く**（硬化が「開けなくする」ではないこと）。

    壊すと落ちる: 常に例外にする（検証もテストも回せなくなる）。
    """
    data = tmp_path / "copy"
    monkeypatch.setenv(DATA_ENV, str(data))
    app = create_app()
    try:
        assert (data / "db.sqlite3").is_file(), "複製の DB を作っていない"
        assert app.state.store.data_dir == data
    finally:
        app.state.store.close()


# ---- 2. `cli serve` は今までどおり（既定を明示的に指す）----


def test_the_serve_path_points_the_env_at_the_default(tmp_path: Path, monkeypatch):
    """**`serve` は既定の `.data` を明示的に指す**（利用者の本来の起動を壊さない）。

    壊すと落ちる: `serve_data_dir()` を外す（`create_app()` が断って
    **`image-reviewer serve` が起動しなくなる**）。
    """
    monkeypatch.delenv(DATA_ENV, raising=False)
    assert cli.serve_data_dir() == str(DEFAULT_DATA_DIR)
    assert os.environ[DATA_ENV] == str(DEFAULT_DATA_DIR), "env を立てていない"
    # 既に指してあれば**そのまま**（複製のサーバを立てる道）
    monkeypatch.setenv(DATA_ENV, str(tmp_path / "copy"))
    assert cli.serve_data_dir() == str(tmp_path / "copy")


def test_pytest_always_has_a_data_dir_that_is_not_the_real_one():
    """**テストは収集の前に向けられている**（`conftest.pytest_configure` の `setdefault`）。

    壊すと落ちる: `conftest` の `setdefault` を外すと、`create_app()` を使うテストが
    例外になる（か、危なければ実データを開く）。**ここでその 1 行が効いていることを見る。**
    """
    got = os.environ.get(DATA_ENV)
    assert got, "pytest の最中に IMAGE_REVIEWER_DATA が無い"
    assert Path(got).resolve() != DEFAULT_DATA_DIR.resolve(), "テストが実データを指している"
    assert (Path(__file__).resolve().parent / ".tmp") in Path(got).resolve().parents, got
    assert DEFAULT_DATA_DIR == REPO / ".data"
