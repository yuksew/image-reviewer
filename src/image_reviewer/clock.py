"""時計（P8-0 の土台。**（点検 C6）1 つの口から 2 つの時計を出す**）。

なぜ要るか: P8 の削除は **壁時計と単調時計を両方**使う。

- **凍結（`pending_delete_preview.expires_at`）は壁時計**（人が見る時刻。再起動をまたぐ）
- **5 分の窓（`deletion_log.remaining_sec`）は単調時計**（眠っている間や時計の変更で縮まない）

**2 つを別々に注入できる形にしない**（片方だけ差し替えて「窓は切れたが凍結は生きている」のような
**現実に起きない組合せ**のテストを書けてしまう）。テストはこの 1 つを進めて、
**「窓が切れる」「凍結が失効する」を決定的に**作る（`time.monotonic` を直接呼ばない）。

使い方（サービス側）::

    def __init__(self, store, *, clock=None):
        self.clock = clock_of(clock)      # 注入が無ければシステムの時計

    self.clock.now()          # 壁時計（UTC・秒。`db.now()` と同じ形）
    self.clock.monotonic()    # 単調時計（秒）
"""

from __future__ import annotations

import time
from typing import Protocol

from . import db


class ClockLike(Protocol):
    """時計の口（**テストはこれを真似た物を渡す**）。"""

    def now(self) -> str: ...

    def monotonic(self) -> float: ...


class Clock:
    """システムの時計（壁時計と単調時計を 1 つの口から出す）。"""

    def now(self) -> str:
        """壁時計（UTC・秒）。**表示と `expires_at` に使う**（順序の判定には使わない）。"""
        return db.now()

    def monotonic(self) -> float:
        """単調時計（秒）。**窓の計算はこれだけを使う**（壁時計では数えない）。"""
        return time.monotonic()


#: 既定の時計（プロセスで 1 つ）
SYSTEM_CLOCK = Clock()


def clock_of(clock: ClockLike | None = None) -> ClockLike:
    """注入された時計、無ければシステムの時計。

    **`None` を既定にする**（サービスの引数を `clock=None` にしておけば、
    テストは本物の時計を渡すだけでよい）。
    """
    return clock if clock is not None else SYSTEM_CLOCK
