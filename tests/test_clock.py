"""時計の土台（P8-0。**（点検 C6）1 つの口から壁時計と単調時計を出す**）のテスト。

**何を壊すと落ちるか**: `clock_of()` の既定を外す（`None` を渡すと落ちる）／
サービスの引数から `clock` を外す（**テストが時計を進められなくなる**＝5 分の窓が揺れる）。
"""

from __future__ import annotations

from image_reviewer.clock import SYSTEM_CLOCK, Clock, clock_of


class FakeClock:
    """テスト用の時計（**壁と単調の両方を 1 つの口から進める**）。"""

    def __init__(self, *, wall: float = 0.0, mono: float = 0.0):
        self._wall = wall
        self._mono = mono

    def now(self) -> str:
        import time
        return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(self._wall))

    def monotonic(self) -> float:
        return self._mono

    def advance(self, *, sec: float = 0.0, mono: float = 0.0) -> None:
        self._wall += sec
        self._mono += mono


def test_the_system_clock_gives_both_times():
    """既定の時計は**壁時計（文字列）と単調時計（数値）の両方**を出す。"""
    clock = Clock()
    got = clock.now()
    assert isinstance(got, str) and got.endswith("Z") and "T" in got
    first = clock.monotonic()
    assert isinstance(first, float)
    assert clock.monotonic() >= first, "単調時計が減った"


def test_clock_of_falls_back_to_the_system_clock():
    """**注入が無ければシステムの時計**（`None` を渡しても落ちない）。"""
    assert clock_of(None) is SYSTEM_CLOCK
    assert clock_of() is SYSTEM_CLOCK
    fake = FakeClock()
    assert clock_of(fake) is fake, "注入した時計が使われていない"
    # **口が揃っている**（サービスは `now()` と `monotonic()` だけを呼ぶ）
    for name in ("now", "monotonic"):
        assert callable(getattr(SYSTEM_CLOCK, name)), f"{name} が無い"
        assert callable(getattr(fake, name)), f"偽の時計に {name} が無い"


def test_the_fake_clock_moves_both_times_together():
    """**1 つの口を進めると両方進む**（別々に注入できない形になっている）。"""
    clock = FakeClock()
    before = (clock.now(), clock.monotonic())
    clock.advance(sec=301, mono=301)
    after = (clock.now(), clock.monotonic())
    assert after[0] != before[0] and after[1] == before[1] + 301
