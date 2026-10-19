r"""テストの下ごしらえ。

この環境では pytest 既定の一時フォルダ（`%TEMP%` と拡張パス `\\?\` での削除）が
ファイル制限に当たるため、`tmp_path` を自前で用意する（`-p no:tmpdir` で既定を切っている）。
作る場所はワークスペース内。

**後始末は黙って諦めない。** 以前は `shutil.rmtree(..., ignore_errors=True)` だけだったので、
SQLite の接続を開いたままのテストでは Windows がファイルを握って削除に失敗し、
`tests/.tmp` にフォルダが溜まった（実測: 1 回の `uv run pytest -q` で 14 個）。
いまは**残っていたらその場で落とす**。どのテストが漏らしたかがパスで見える。
"""

from __future__ import annotations

import os
import shutil
import sys
import os
import uuid
from pathlib import Path

import pytest

# **プロセスごとに分ける**（`os.getpid()`）: 監査の担当と開発の担当が**同時に pytest を回す**ことが
# あり、base を共有すると**片方の後始末がもう片方の作ったフォルダを拾って**「残っています」で
# 落ちる（実測: 2026-10-19。失敗そのものは無関係でも**連鎖して赤くなる**）。
BASE = Path(__file__).resolve().parent / ".tmp" / str(os.getpid())

# この実行で作ったフォルダ（最後に 1 つも残っていないことを確かめる）
_CREATED: list[Path] = []


def pytest_configure(config) -> None:
    """P4: **模型（ComfyUI）を呼ぶテストの印**を登録する（既定では走らせない。設計 §8）。

    実機の線は `tools/probe_p4.py` が受け持つ。**`pyproject.toml` を触らない**のは、
    利用者のサーバが `image-reviewer.exe` を握っていると `uv run` の再インストールが
    失敗するため（実際に踏んだ）。

    **（P8-4 の監査 G-8）データ置き場とバックアップの置き場を、収集の前にテストの中へ向ける。**
    `IMAGE_REVIEWER_DATA` を忘れた瞬間に**実データ**を開く入口が残っていると
    （plugin・`python -c` の import・`conftest` 自身の import）、`migrate()` や
    `_top_up_v6` が実データに当たる。実際に、並行の作業の plugin が `image_reviewer.app` を
    import しただけで**実データに `deletion_log.stuck_reason` の列が足された**。

    **（トレイの監査 C-6。2026-10-19）`setdefault` をやめて上書きにする。**
    `setdefault` は**呼んだシェルの環境をそのまま使う**ので、親が実データ（か、監査の「安全網」の
    フォルダ）を指していると、**テストがそこへ `db.sqlite3` を作った**（実測: 安全網のフォルダが
    作られ、`test_pytest_always_has_a_data_dir_that_is_not_the_real_one` だけが落ちた。
    **落ちた時点では前のテストがもうそのフォルダを開いている**）。
    親が実データを指していたら**大きく知らせてから上書きする**（止めない——止めても
    テストの置き場はテストの中なので、上書きの方が安全）。

    **（トレイの再確認 D-3。2026-10-19）バックアップの置き場も同じ型だったので上書きにする。**
    `IMAGE_REVIEWER_BACKUP_DIR` を `setdefault` で引き継ぐと、親（監査の「安全網」）が指した
    フォルダに控えを作り得る。**実害は確かめられていない**（親を `.tmp-tray-recheck\bk-net` に
    向けて 570 件を回しても、そこには何も作られなかった）が、**引き継ぐ型は C-6 と同じ**なので揃える。
    """
    config.addinivalue_line("markers", "comfyui: 実際に ComfyUI を呼ぶ（既定では走らせない）")
    target = str(BASE / "_proto_app")
    incoming = (os.environ.get("IMAGE_REVIEWER_DATA") or "").strip()
    if incoming and Path(incoming).resolve() == (Path(__file__).resolve().parents[1] / ".data").resolve():
        print(
            "\n[重要] 呼んだシェルの IMAGE_REVIEWER_DATA が**実データ**（.data）を指しています。"
            "テストは実データを開きません（テストの中へ上書きしました）。",
            flush=True,
        )
    # **上書き**（引き継いだ値に任せない＝監査 C-6）
    os.environ["IMAGE_REVIEWER_DATA"] = target
    os.environ["IMAGE_REVIEWER_BACKUP_DIR"] = str(BASE / "_backups")


def _close_prototype_app() -> None:
    """`app.py` が import 時に作る `app = create_app()` の接続を閉じる。

    `uvicorn` の `image_reviewer.app:app` のために、`app.py` は**読み込まれた時点で**
    `create_app()` を走らせる（＝ `Store` を開く）。テストが `image_reviewer.app` を
    読み込むと、その `Store` は**テストが作った物ではない**のでテスト側からは閉じられず、
    接続が開いたまま残る（実測: 最初に読み込んだ `tests/test_compare.py` の 1 件）。
    ここで閉じる。`close()` は 2 回呼んでも安全なので、他のテストでは何もしない。
    """
    module = sys.modules.get("image_reviewer.app")
    app = getattr(module, "app", None) if module is not None else None
    state = getattr(app, "state", None)
    store = getattr(state, "store", None)
    if store is None:
        return
    try:
        store.close()
    except Exception:  # noqa: BLE001  後始末を失敗で止めない（残れば下の _remove_tree が落とす）
        pass


def _remove_tree(d: Path) -> None:
    """フォルダを消す。**残ったら落とす**（開いたままの接続があると Windows は消せない）。

    最善努力なのは「消せたとき」だけ。`d` が残っているなら、それは
    **テストが接続（かファイル）を漏らした**ということなので、パスを名指しして落とす。
    """
    shutil.rmtree(d, ignore_errors=True)
    if d.exists():
        left = sorted(str(p.relative_to(d)) for p in d.rglob("*"))
        raise AssertionError(
            f"テストの一時フォルダを消せませんでした: {d}\n"
            f"  開いたままの接続かファイルが残っています（残骸: {left[:10]}）。\n"
            "  `Store` は `with Store(...) as store:` で閉じ、`TestClient` は "
            "`with TestClient(app) as client:` で lifespan の終了側を通してください。"
        )


@pytest.fixture
def tmp_path():
    d = BASE / uuid.uuid4().hex[:12]
    d.mkdir(parents=True, exist_ok=True)
    _CREATED.append(d)
    try:
        yield d
    finally:
        # 先に「テストが作った物ではない接続」を閉じる。ここで拾うと、
        # どのテストが漏らしたのかが分からなくなる（漏らした分は次の `_remove_tree` が拾う）
        _close_prototype_app()
        _remove_tree(d)


@pytest.fixture(scope="session", autouse=True)
def _no_leftover_temp_dirs():
    """この実行で作った一時フォルダが 1 つも残っていないことを、最後に確かめる。

    個々のテストは `tmp_path` の後始末（`_remove_tree`）で落ちるので、ここは
    **取りこぼしの見張り**（例: テストの外で開かれた接続）。前の実行の残骸は
    対象にしない（自分が作った分だけを見る）。
    """
    yield
    leftovers = [str(p) for p in _CREATED if p.exists()]
    assert not leftovers, f"一時フォルダが残っています（{len(leftovers)} 件）: {leftovers[:5]}"


@pytest.fixture(autouse=True)
def _backup_dir_inside_the_tests(monkeypatch):
    """**バックアップの置き場をテストの中に向ける**（P8-4）。

    `create_app()` は lifespan で日次バックアップのタイマーを張り、**起動した直後に
    1 回見る**（設計 §0.12-1・点検 B2）。向けないと、`TestClient` を使うテストのたびに
    **利用者のホーム**（`%USERPROFILE%\\image-reviewer-backups`）へスナップショットを作り、
    「直近 7 個を残す」規則（§0.12-3）で**利用者の本物の控えを消してしまう**。
    置き場は実行の終わりに消す（`_no_leftover_backup_dir`）。
    """
    monkeypatch.setenv("IMAGE_REVIEWER_BACKUP_DIR", str(BASE / "_backups"))
    yield


@pytest.fixture(scope="session", autouse=True)
def _no_leftover_backup_dir():
    """テストが作ったバックアップの置き場を消す（**利用者のホームには作らない**）。

    **（P8-4 の監査 G-8）** `pytest_configure` が向けた既定のデータ置き場（`_proto_app`）も
    ここで消す（`image_reviewer.app` を import しただけのテストが作る物）。
    """
    yield
    shutil.rmtree(BASE / "_backups", ignore_errors=True)
    shutil.rmtree(BASE / "_proto_app", ignore_errors=True)
