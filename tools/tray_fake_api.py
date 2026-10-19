"""トレイの検査が使う**偽のサーバ**（本物の image-reviewer ではない）。

`tools/tray_selftest.ps1`（§2d の「遅い口」）と `tests/test_tray_ports.py`（4 ポートの確認）が使う。
**実データを開かない**——DB も画像も触らず、`IMAGE_REVIEWER_DATA` も見ない。

```powershell
# /api/health だけ image-reviewer と名乗る（他の口は 404）
python tools\tray_fake_api.py --mode fake --port 8796

# /api/health は即答し、他の口は 30 秒眠る（この環境の「生きていて遅い」形）
python tools\tray_fake_api.py --mode slow --port 8797 --log .tmp-tray\slow.txt
```

- `--log` を渡すと、**来たパスを 1 行ずつ追記する**（「残りの口を打っていない」を数えるため）。
- **止めるのは起こした側**（この道具は自分からは終わらない）。
- 遅い口は `ThreadingHTTPServer` で受ける（1 本が眠っても health は答える）。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

#: `slow` で眠る秒数（トレイの見切りは 2 秒。十分に長くしておく）
SLOW_SEC = 30


def main() -> int:
    ap = argparse.ArgumentParser(description="トレイの検査が使う偽のサーバ")
    ap.add_argument("--mode", choices=["fake", "slow"], required=True)
    ap.add_argument("--port", type=int, required=True)
    ap.add_argument("--log", default="")
    args = ap.parse_args()
    log = Path(args.log) if args.log else None

    class Handler(BaseHTTPRequestHandler):
        def _note(self) -> None:
            if log is not None:
                try:
                    with log.open("a", encoding="utf-8") as fh:
                        fh.write(self.path + "\n")
                except OSError:
                    pass

        def _send(self, code: int, body: bytes) -> None:
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:  # noqa: N802  (http.server の決まり)
            self._note()
            if self.path.startswith("/api/health"):
                body = json.dumps(
                    {
                        "ok": True,
                        "app": "image-reviewer",
                        "pid": os.getpid(),
                        "version": "fake",
                        "data_dir": "FAKE",
                        "started_at": "2026-10-19T00:00:00Z",
                    }
                ).encode()
                self._send(200, body)
                return
            if args.mode == "slow":
                time.sleep(SLOW_SEC)
                self._send(200, b"{}")
                return
            self._send(404, b"{}")

        def log_message(self, *a: object) -> None:  # 標準エラーを汚さない
            return

    srv = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    print(f"listening {args.port} mode={args.mode} pid={os.getpid()}", flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
