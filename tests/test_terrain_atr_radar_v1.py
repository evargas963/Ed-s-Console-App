"""ATR rings and radar contact selection.

WHY ATR: percent means different things across instruments — 0.5% is a normal hour on SPY
and noise on TSLA. ATR normalises distance into "can price actually get there", which is
the only question the radar answers.

The ring thresholds are derived from meaning, not invented: within a tenth of a day's range
a level is effectively being touched; beyond three quarters of a day's range it cannot
matter today. Regime-change contacts outrank walls because crossing the flip changes what
every other level means.
"""

from __future__ import annotations

import json
from pathlib import Path

import server as srv
from numeric_contract import count_text
from push import bars as push_bars
from push import strikes as push_strikes
from state import bar_store
from tests.feed_live_helper import RTH_INSTANT


def test_the_bars_panel_serves_canonical_bars_shape():
    """The `bars` panel is newest-last {t,o,h,l,c,v} rows.

    The rows come from the console's 1-minute bars in memory (state.bar_store: price_bars_1m loaded
    at startup, then each streamed bar).
    """
    # Real SPY 1-minute bars (tests/fixtures), each kept by the console's own bar writer.
    fx = json.loads(
        (
            Path(__file__).resolve().parent / "fixtures" / "real_spy_1m_bars_2026_09_24_25.json"
        ).read_text(encoding="utf-8")
    )["bars"]
    rows = [
        (b["timestamp"] / 1000.0, b["open"], b["high"], b["low"], b["close"], b["volume"])
        for b in fx
    ]
    bar_store._bars.pop("SPY", None)
    try:
        for b in fx:
            srv._write_streamed_bar({"symbol": "SPY", "bar_start_ms": b["timestamp"], **b})
        at = rows[-1][0] + 60.0
        body = push_bars.bars("SPY", at, {"tf": "1", "limit": 5})
        assert body["tf"] == "1" and len(body["bars"]) == 5
        row = body["bars"][-1]
        # each bar carries its served change (live_price_rows.bar_change: the bar change is
        # served, the page computes nothing), its served times (time_et.ct_label, ct_ticks) and
        # its volume and prices as the screen shows them
        assert set(row) == {
            *("t", "o", "h", "l", "c", "v", "chg", "chg_pct", "chg_text"),
            *("time_ct", "ticks", "v_text", "o_text", "h_text", "l_text", "c_text"),
        }
        assert row["v_text"] == count_text(row["v"])
        assert row["c_text"] == f"{rows[-1][4]:.2f}"
        assert (row["t"], row["c"]) == (rows[-1][0], rows[-1][4])
        ts = [b["t"] for b in body["bars"]]
        assert ts == sorted(ts), "bars must be newest-last (ascending time)"
        # the chart's candles are Schwab's completed bars exactly as stored, never altered
        full = push_bars.bars("SPY", at, {"tf": "1", "limit": len(rows)})["bars"]
        assert [(b["t"], b["o"], b["h"], b["l"], b["c"], b["v"]) for b in full] == rows
    finally:
        bar_store._bars.pop("SPY", None)


def test_terrain_strikes_endpoint_shape_and_scopes():
    """CR-03 histogram feed: per-strike rows of the one expiry chosen (here All Expirations).

    For today + prior capture, sorted by strike, read-only.
    """
    body = push_strikes.strikes(
        "SPY", RTH_INSTANT, {"scope": "auto", "centre": None, "shift": 0, "expiry": None}
    )
    assert json.loads(json.dumps(body)) == body  # the socket's frame, as it is
    assert body["ticker"] == "SPY"
    assert (body["expiry"], body["expiry_text"]) == (None, "All Expirations")
    assert isinstance(body["today"], list) and set(body["view"]) >= {"centre", "max_abs"}
    rows = body["today"]
    if rows:
        ks = [x["strike"] for x in rows]
        assert ks == sorted(ks), "strikes must be ascending"
        assert {r["strike"] for r in body["migration"]["rows"]} <= set(ks)
