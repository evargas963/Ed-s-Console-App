"""Schwab -> the levels page. Each level's As-of column carries that level's time."""
from __future__ import annotations

from datetime import datetime

import pytest

import server
from liquidity_value_engine import _MATERIALIZED_SNAPSHOTS
from tests.feed_live_helper import daemon_bars, stream_daemon_bars
from time_et import ET, ct_label

_BARS = daemon_bars("real_daemon_bars_spy_tsla_2026_10_01_02.json")


def _forget(*tickers: str) -> None:
    for tk in tickers:
        server._bars.pop(tk, None)
        for key in [k for k in _MATERIALIZED_SNAPSHOTS if k[0] == tk]:
            del _MATERIALIZED_SNAPSHOTS[key]


def test_the_levels_page_carries_each_levels_time():
    """Saturday 2026-10-03 12:00 ET. SPY's VWAP keeps its price, and the time beside its age is
    the snapshot's time. The market being closed does not remove either."""
    closed = datetime(2026, 10, 3, 12, 0, tzinfo=ET)
    _forget("SPY", "TSLA")
    try:
        stream_daemon_bars(_BARS)
        server._publish_price_levels("SPY", closed)
        body = server.levels_payload("SPY", "1", closed)
        vwap = next(r for r in body["levels"] if r["id"] == "VWAP")
        as_of = vwap["staleness"]["as_of_ts_utc"]
        assert vwap["price"] is not None
        assert vwap["staleness"]["as_of_time_ct"] == ct_label(as_of)
    finally:
        _forget("SPY", "TSLA")


@pytest.mark.parametrize("now, window", [
    (datetime(2026, 10, 3, 12, 0, tzinfo=ET), "2026-10-01 RTH close -> 2026-10-02 RTH open"),
    (datetime(2026, 10, 1, 12, 0, tzinfo=ET), "2026-10-01 before the RTH open (no prior session)"),
])
def test_the_overnight_levels_name_the_sessions_they_span(now, window):
    """SPY's overnight high and low name the sessions their bars span. Saturday 2026-10-03:
    Thursday's regular close to Friday's regular open. Thursday 2026-10-01, the first day the
    bars hold: that morning's pre-open, with no session before it."""
    _forget("SPY", "TSLA")
    try:
        stream_daemon_bars(_BARS)
        server._publish_price_levels("SPY", now)
        body = server.levels_payload("SPY", "1", now)
        overnight = [r for r in body["levels"] if r["family"] == "overnight"]
        assert {r["id"] for r in overnight} == {"OVERNIGHT_HIGH", "OVERNIGHT_LOW"}
        for row in overnight:
            assert row["provenance"]["window"] == window
    finally:
        _forget("SPY", "TSLA")
