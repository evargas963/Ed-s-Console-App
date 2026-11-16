"""Schwab -> the trade desk. The LEVELS pill carries the snapshot's time."""

from __future__ import annotations

from datetime import datetime

import server
from push import levels as push_levels
from state import bar_store, price_level_store
from tests.feed_live_helper import daemon_bars, newest_bars, stream_daemon_bars
from time_et import ET, ct_label

_BARS = daemon_bars("real_daemon_bars_spy_tsla_2026_10_01_02.json")


def _forget(*tickers: str) -> None:
    for tk in tickers:
        bar_store._bars.pop(tk, None)
        for key in [k for k in price_level_store._MATERIALIZED_SNAPSHOTS if k[0] == tk]:
            del price_level_store._MATERIALIZED_SNAPSHOTS[key]


def test_the_levels_pill_carries_the_snapshots_time():
    """Saturday 2026-10-03 12:00 ET.

    SPY's last session snapshot keeps its time, the newest bar's start, so the desk map can show
    it beside the age.
    """
    closed = datetime(2026, 10, 3, 12, 0, tzinfo=ET)
    _forget("SPY", "TSLA")
    try:
        stream_daemon_bars(_BARS)
        server._publish_price_levels("SPY", closed)
        body = push_levels.levels_payload("SPY", "1", closed)
        as_of = newest_bars(_BARS, "SPY")[-1]["bar_start_ms"] / 1000
        assert body["snapshot_time_ct"] == ct_label(as_of)
    finally:
        _forget("SPY", "TSLA")
