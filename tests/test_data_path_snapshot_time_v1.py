"""Schwab -> the trade desk. The LEVELS pill carries the snapshot's time."""
from __future__ import annotations

from datetime import datetime

import server
from liquidity_value_engine import _MATERIALIZED_SNAPSHOTS
from tests.feed_live_helper import daemon_bars, stream_daemon_bars
from time_et import ET, ct_label

_BARS = daemon_bars("real_daemon_bars_spy_tsla_2026_10_01_02.json")


def _newest(rows: list[dict], tk: str) -> list[dict]:
    out = {}
    for r in sorted(rows, key=lambda r: r["ts_recv"]):
        if r["symbol"] == tk:
            out[r["bar_start_ms"]] = r
    return [out[ms] for ms in sorted(out)]


def _forget(*tickers: str) -> None:
    for tk in tickers:
        server._bars.pop(tk, None)
        for key in [k for k in _MATERIALIZED_SNAPSHOTS if k[0] == tk]:
            del _MATERIALIZED_SNAPSHOTS[key]


def test_the_levels_pill_carries_the_snapshots_time():
    """Saturday 2026-10-03 12:00 ET. SPY's last session snapshot keeps its time, the newest
    bar's start, so the desk map can show it beside the age."""
    closed = datetime(2026, 10, 3, 12, 0, tzinfo=ET)
    _forget("SPY", "TSLA")
    try:
        stream_daemon_bars(_BARS)
        server._publish_price_levels("SPY", closed)
        body = server.levels_payload("SPY", "1", closed)
        as_of = _newest(_BARS, "SPY")[-1]["bar_start_ms"] / 1000
        assert body["snapshot_as_of_ts_utc"] == as_of
        assert body["snapshot_time_ct"] == ct_label(as_of)
    finally:
        _forget("SPY", "TSLA")
