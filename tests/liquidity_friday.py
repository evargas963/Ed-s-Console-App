"""The liquidity tests' real data and their `published` fixture.

Schwab's SPY 1-minute bars to 15:00 ET on Friday 2026-10-02, as the capture daemon recorded them
on Thursday 2026-10-01 and Friday 10-02; each minute's newest receipt is kept. Stand-in: ticker
ZZLIQ carries the SPY bars. tests/conftest.py loads this module as a plugin (pytest_plugins), so
every test file can ask for `published`.
"""

from __future__ import annotations

from datetime import datetime
from functools import cache

import pytest

import liquidity_value_engine as lve
import live_market_plane as lmp
import server as srv
from micro_structure import Candle
from tests.feed_live_helper import daemon_bars
from time_et import ET

TK = "ZZLIQ"
FRIDAY = datetime(2026, 10, 2, 15, 0, tzinfo=ET)


@cache
def friday_bars() -> tuple[dict, ...]:
    """Return the bars before FRIDAY, oldest first, each minute's newest receipt as recorded."""
    newest = {}
    for r in sorted(
        daemon_bars("real_daemon_bars_spy_tsla_2026_10_01_02.json", "SPY"),
        key=lambda r: r["ts_recv"],
    ):
        newest[r["bar_start_ms"]] = r
    return tuple(
        {
            "timestamp": ms,
            "open": r["open"],
            "high": r["high"],
            "low": r["low"],
            "close": r["close"],
            "volume": r["volume"],
        }
        for ms, r in sorted(newest.items())
        if ms / 1000 < FRIDAY.timestamp()
    )


@pytest.fixture
def published():
    """Put the SPY bars to 15:00 ET on Friday in the console's memory and publish their levels.

    Nothing of the stand-in ticker is left behind.
    """

    def forget():
        srv._bars.pop(TK, None)
        with lmp._lock:
            lmp._by_ticker.pop(TK, None)
            lmp._fields_by_ticker.pop(TK, None)
        for key in [k for k in lve._MATERIALIZED_SNAPSHOTS if k[0] == TK]:
            del lve._MATERIALIZED_SNAPSHOTS[key]

    forget()
    for b in friday_bars():
        srv._keep_bar(
            TK,
            Candle(
                ts=b["timestamp"] / 1000,
                open=b["open"],
                high=b["high"],
                low=b["low"],
                close=b["close"],
                volume=b["volume"],
            ),
        )
    srv._publish_price_levels(TK, FRIDAY)
    yield
    forget()
