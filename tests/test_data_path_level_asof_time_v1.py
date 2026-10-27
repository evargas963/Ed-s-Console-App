"""Schwab -> the levels page. Each level's As-of column carries that level's time."""
from __future__ import annotations

from datetime import datetime

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


def test_the_overnight_levels_name_the_sessions_they_span():
    """Saturday 2026-10-03. SPY's overnight high and low span Thursday's regular close to
    Friday's regular open, and their window names those two sessions."""
    closed = datetime(2026, 10, 3, 12, 0, tzinfo=ET)
    _forget("SPY", "TSLA")
    try:
        stream_daemon_bars(_BARS)
        server._publish_price_levels("SPY", closed)
        body = server.levels_payload("SPY", "1", closed)
        overnight = [r for r in body["levels"] if r["family"] == "overnight"]
        assert {r["id"] for r in overnight} == {"OVERNIGHT_HIGH", "OVERNIGHT_LOW"}
        for row in overnight:
            assert row["provenance"]["window"] == "2026-10-01 RTH close -> 2026-10-02 RTH open"
    finally:
        _forget("SPY", "TSLA")
