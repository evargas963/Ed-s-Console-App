"""Every ticker's 1-minute bars and Schwab's other /pricehistory series, as the bar writer holds.

The bars are Schwab's own 1-minute price history (MINUTE_SERIES: its last 10 days with extended
hours, and 90 days of the regular session, from the capture daemon's /pricehistory requests each
ET date) with Schwab's streamed CHART_EQUITY bars on top, a streamed minute replacing Schwab's
history of it. The bar writer (server._bar_writer) is the one writer; every live reader reads
them here, never a database (docs/DATA_FLOW.md §2 D6).
"""

from __future__ import annotations

import threading

from instrument_identity import ticker_storage_key
from micro_structure import Candle

#: one RTH day of 1-minute bars
CANDLE_1M_MAX_BARS: int = 390
#: the newest bars kept per ticker: 62 sessions of 390 regular bars and 10 days of extended hours
#: (~9,600)
BARS_KEPT = 40_000
#: the daemon's /pricehistory series of 1-minute bars, both kept in the ticker's bars
MINUTE_SERIES = ("1m", "1m60")

#: ticker -> its completed 1-minute bars, oldest first, the newest BARS_KEPT
_bars: dict[str, list[Candle]] = {}
#: (ticker, series) -> Schwab's newest answer of that series, oldest first: every series of the
#: daemon's PRICE_HISTORY but MINUTE_SERIES
_series: dict[tuple[str, str], list[Candle]] = {}
_lock = threading.Lock()


def keep_bar(tk: str, bar: Candle) -> None:
    """Put a streamed bar into `tk`'s bars.

    A minute already held is replaced (Schwab's newest bar for it), a new one takes its place in
    time; the oldest beyond BARS_KEPT leave.
    """
    with _lock:
        held = _bars.setdefault(tk, [])
        i = len(held)  # bars arrive in time order: found at once
        while i and held[i - 1].ts > bar.ts:
            i -= 1
        if i and held[i - 1].ts == bar.ts:
            held[i - 1] = bar
        else:
            held.insert(i, bar)
        del held[:-BARS_KEPT]


def held_minutes(tk: str) -> set[float]:
    """Return the start of every 1-minute bar `tk` holds."""
    with _lock:
        return {b.ts for b in _bars[tk]} if tk in _bars else set()


def take_history(tk: str, taken: list[Candle]) -> bool:
    """Add Schwab's history bars `taken`, minutes `tk` does not hold, to its bars.

    True when one of them is among the BARS_KEPT kept.
    """
    if not taken:
        return False
    with _lock:
        held = _bars[tk] if tk in _bars else []
        bars = sorted([*held, *taken], key=lambda b: b.ts)[-BARS_KEPT:]
        _bars[tk] = bars
    return any(b.ts >= bars[0].ts for b in taken)


def put_series(tk: str, series: str, candles: list[Candle]) -> bool:
    """Hold `candles` as Schwab's newest answer of `series` for `tk`. True when it changed."""
    key = (tk, series)
    with _lock:
        if key in _series and _series[key] == candles:
            return False
        _series[key] = candles
    return True


def bars_1m(tk: str, limit: int = CANDLE_1M_MAX_BARS) -> list[Candle]:
    """`tk`'s newest `limit` completed 1-minute bars, oldest first.

    A minute Schwab did not deliver is absent, never filled in.
    """
    key = ticker_storage_key(tk)
    with _lock:
        return list(_bars[key][-int(limit) :]) if key in _bars else []


def series(tk: str, name: str) -> list[Candle]:
    """`tk`'s Schwab /pricehistory series `name`, oldest first; none held: none."""
    with _lock:
        return list(_series[(tk, name)]) if (tk, name) in _series else []
