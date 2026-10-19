"""トレイの自己検査が**使う 4 つのポートを 4 つとも見ている**ことを、実行して確かめる。

`docs/tray-audit-recheck.md` の A-1: `@($Port, $Port + 1, $Port + 2, $Port + 3)` は
PowerShell では**カンマが `+` より強く**結び付くので **7 要素**（`8795,8795,1,8795,2,8795,3`）になり、
**8795 しか見ていなかった**。`tests/test_tray.py` の静的な検査（文字列を探す）はこれを通した
（監査 F「静的な検査の限界の実例」）。ここは**本物の自己検査を子プロセスで回して**振る舞いで見る。

壊すと落ちる: `tools/tray_selftest.ps1` の括弧を外す（`-Port + 1` に立てた**他人のサーバ**を
§10 の後始末が止め、`exit 2` にならず最後まで走る）。`IMAGE_REVIEWER_TRAY_SELFTEST` に写しを
渡すと、その写しを回すので**壊し試験ができる**（実測は `docs/tray-recheck-triage.md` A-1）。

**この検査は 8790 も実データも使わない**: 空いている 4 つ組を自分で選び、偽サーバは
`tools/tray_fake_api.py`（DB も画像も触らない）、親には安全網の置き場を置く。
"""

from __future__ import annotations

import os
import shutil
import socket
import subprocess
import time
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
PY = REPO / ".venv" / "Scripts" / "python.exe"
FAKE = REPO / "tools" / "tray_fake_api.py"
#: 壊し試験で写しを指すための口（既定は本物）
SELFTEST = Path(
    os.environ.get("IMAGE_REVIEWER_TRAY_SELFTEST") or (REPO / "tools" / "tray_selftest.ps1")
)


def _powershell() -> str:
    exe = shutil.which("powershell")
    assert exe, "powershell が見つかりません"
    return exe


def _port_is_free(port: int) -> bool:
    with socket.socket() as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind(("127.0.0.1", port))
        except OSError:
            return False
    return True


def _free_base() -> int:
    """`base`〜`base + 3` が空いている組を 1 つ選ぶ（`base + 1` に偽サーバを立てる）。

    **8795〜8798 は使わない**（監査の再現と同じ番号を使うと、並行の検査と取り合う）。
    """
    for base in range(8851, 8901, 5):
        if all(_port_is_free(base + i) for i in range(4)):
            return base
    raise AssertionError("空いている 4 つ組が見つかりません（8851〜8900 を試しました）")


def _wait_health(port: int, timeout: float = 30.0) -> None:
    deadline = time.time() + timeout
    url = f"http://127.0.0.1:{port}/api/health"
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=1) as res:
                if res.status == 200:
                    return
        except OSError:
            time.sleep(0.1)
    raise AssertionError(f"偽サーバが {port} で上がりませんでした")


def _decode(raw: bytes) -> str:
    """PowerShell の子の出力を読む（この環境は UTF-8。古い環境向けに cp932 も試す）。"""
    for enc in ("utf-8-sig", "cp932"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", "replace")


def test_the_selftest_refuses_when_any_of_the_four_ports_is_taken(tmp_path):
    """**`-Port + 1` が埋まっていれば、1 つも起動せず exit 2**（4 つとも見ていること）。

    壊すと落ちる: 括弧を外して 7 要素の `foreach` に戻す（8795 しか見ない）。
    そのときの実測は「exit 1・最後まで走る・§10 が偽サーバを止める」で、下の 3 つの assert が
    それぞれ落ちる（`docs/tray-recheck-triage.md` A-1）。
    """
    base = _free_base()
    fake = subprocess.Popen(
        [str(PY), str(FAKE), "--mode", "fake", "--port", str(base + 1)],
        cwd=str(REPO),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        _wait_health(base + 1)
        assert fake.poll() is None, "偽サーバが立ち上がっていません（下ごしらえの失敗）"
        env = dict(os.environ)
        # **親に安全網**を置く（監査と同じやり方。置き場を忘れた子が実データでなくここを開く）
        env["IMAGE_REVIEWER_DATA"] = str(tmp_path / "safety-net")
        env["IMAGE_REVIEWER_BACKUP_DIR"] = str(tmp_path / "safety-backups")
        env.pop("IMAGE_REVIEWER_TRAY_SELFTEST", None)
        # **前の回のログを消してから回す**（§1 で止まる回は自分でログを作らないので、
        #  残っていると「前の回が起こしたサーバ」を今回の物と読み違える）
        tray_log = REPO / ".tmp-tray" / "log" / "tray-selftest.log"
        tray_log.unlink(missing_ok=True)
        proc = subprocess.run(
            [
                _powershell(), "-NoProfile", "-ExecutionPolicy", "Bypass",
                "-File", str(SELFTEST), "-Port", str(base),
            ],
            cwd=str(REPO),
            env=env,
            capture_output=True,
            timeout=300,
        )
        out = _decode(proc.stdout) + _decode(proc.stderr)
        assert proc.returncode == 2, (
            f"埋まっていても exit 2 で止まっていない（exit {proc.returncode}）:\n{out[-3000:]}"
        )
        assert "使うポートが空いていません" in out, out[-3000:]
        assert f"{base + 1}=ours" in out, (
            f"{base + 1} を見ていない（4 つのポートを 4 つとも見ていない）:\n{out[-3000:]}"
        )
        # **他人（この偽サーバ）を止めていない**
        assert fake.poll() is None, "4 つのポートの確認で、他人のサーバを止めた"
        # **1 つも起動していない**（本物のサーバのログに「起動します」が無い）
        if tray_log.is_file():
            text = tray_log.read_text(encoding="utf-8-sig", errors="replace")
            assert "サーバを起動します" not in text, "1 つも起動しないはずが、サーバを起こした"
        # **安全網に 1 ファイルも作っていない**（置き場を明示していない子が居ない）
        safety = tmp_path / "safety-net"
        assert not (safety.exists() and any(safety.rglob("*"))), (
            "安全網に何か作った（置き場を明示していない子が居る）"
        )
    finally:
        fake.kill()
        fake.wait(timeout=30)
