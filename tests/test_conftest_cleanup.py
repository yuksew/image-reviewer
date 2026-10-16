"""`tests/conftest.py` の後始末（`tests/.tmp` が溜まらないこと）のテスト。

理由（点検で見つかった漏れ）: 以前は `shutil.rmtree(..., ignore_errors=True)` だけで、
**SQLite の接続を開いたままのテスト**では Windows が `db.sqlite3` を握って削除に失敗し、
`tests/.tmp` にフォルダが溜まった（実測: 1 回の実行で 14 個。放置すると数百個）。

ここで固定すること:

1. 普通のフォルダは消える（最善努力の側）
2. **接続を開いたままのフォルダは消えず、`_remove_tree()` がパスを名指しして落ちる**
   （＝ 漏らしたテストが見える）
3. 接続を閉じれば消える（`with Store(...) as store:` が効く）

`conftest` は pytest が既に読み込んでいるモジュールなので、そのまま import して
同じ関数・同じ記録を見る（`tests/` に `__init__.py` が無いので `tests/` がパスに入る）。
"""

from __future__ import annotations

import conftest
import pytest

from image_reviewer.store import Store


def test_remove_tree_removes_a_plain_directory(tmp_path):
    d = tmp_path / "plain"
    (d / "sub").mkdir(parents=True)
    (d / "sub" / "x.txt").write_text("x", encoding="utf-8")

    conftest._remove_tree(d)

    assert not d.exists()


def test_remove_tree_raises_when_a_store_is_still_open(tmp_path):
    """漏らした接続が**見える**こと（黙って溜まらない）。

    `Store` をわざと閉じない（＝ 直す前のテストと同じ形）。この状態では Windows が
    `db.sqlite3` を消させないので、`_remove_tree()` はパスを名指しして落ちる。
    """
    d = tmp_path / "leak"
    store = Store(d / "data")            # わざと閉じない
    try:
        with pytest.raises(AssertionError) as got:
            conftest._remove_tree(d)
        # どのフォルダが残ったかを言う（テスト名だけでは分からないため）
        assert str(d) in str(got.value)
        assert "with Store" in str(got.value), "直し方（with で閉じる）を案内していない"
        assert d.exists(), "前提: 接続が開いている間は消せない"
    finally:
        store.close()

    conftest._remove_tree(d)             # 閉じれば消える
    assert not d.exists()


def test_the_tmp_path_fixture_leaves_nothing_behind(tmp_path):
    """普通に使ったテストのフォルダは、`tmp_path` の後始末で消える（このテスト自身で確かめる）。"""
    store = Store(tmp_path / "data")
    with store:
        assert (tmp_path / "data" / "db.sqlite3").exists()
    # `tmp_path` の後始末（`_remove_tree`）はこのテストの後に走る。
    # 消えなければ、そのときに `tmp_path` が AssertionError を上げる（＝ このテストが落ちる）
