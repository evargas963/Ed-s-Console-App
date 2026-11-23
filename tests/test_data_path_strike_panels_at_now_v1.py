"""The per-strike panels, Schwab to the screen, at the time asked.

A captured chain published by the levels producer, and every per-strike panel's answer (GEX by
strike, the chart's DEX and OI, vanna, charm) at that time is windowed around Schwab's price,
whatever the wall clock says (AGENTS.md: a function that depends on the clock takes `now`).

Real data: CRWD's 2026-10-16 expiry, every strike, captured 2026-10-07 10:38:40 ET
(tests/real_chains.py CRWD), and CRWD's LEVELONE_EQUITIES message the daemon received at 10:38:00
ET (tests/fixtures/real_crwd_quote_2026_10_07.json), taken in by the plane at its receipt time,
whose price row the daemon's own function builds at the capture's instant when asked.
"""

from __future__ import annotations

import json
from pathlib import Path

import live_market_plane as lmp
import server
from push import strike_bars as push_strike_bars
from push import strikes as push_strikes
from state import level_store
from tests.feed_live_helper import daemon_status, publish_capture
from tests.real_chains import CRWD

_QUOTE = json.loads(
    (Path(__file__).resolve().parent / "fixtures" / "real_crwd_quote_2026_10_07.json").read_text(
        encoding="utf-8"
    )
)


def _clear(tk):
    with level_store._lock:
        level_store._levels.pop(tk, None)
    lmp._by_ticker.pop(tk, None)
    lmp._fields_by_ticker.pop(tk, None)


def test_every_per_strike_panel_answers_at_the_time_asked_around_the_price():
    tk, at = server.ticker_storage_key(CRWD.ticker), CRWD.now.timestamp()
    _clear(tk)
    try:
        lmp.record_from_level_one_equity(tk, _QUOTE["native"], received_ts=_QUOTE["ts_recv"])
        lmp.record_feed_heartbeat(
            daemon_status(at, schwab_socket_open=True, held={"LEVELONE_EQUITIES": [tk]})
        )
        publish_capture(tk, CRWD.chain, at, CRWD.spot, CRWD.now.date().isoformat(), CRWD.now)
        last = _QUOTE["native"]["LAST_PRICE"]
        strikes = push_strikes.terrain_strikes_payload(tk, "auto", None, 0, None, at)
        listed = [r["strike"] for r in strikes["today"]]
        spot = {"kind": "spot", "label": "SPOT"}
        marked = [r["strike"] for r in strikes["today"] if spot in r["marks"]]
        assert marked == [min(listed, key=lambda k: abs(k - last))]
        assert strikes["view"]["centre"] is not None and strikes["view"]["note"] is None
        for key in push_strike_bars.STRIKE_BAR_METHODS:
            bars = push_strike_bars.strike_bar_payload(tk, key, "auto", None, 0, None, at)
            own = [r["strike"] for r in bars["rows"]]
            at_price = [r["strike"] for r in bars["rows"] if spot in r["marks"]]
            assert bars["available"] and bars["view"]["note"] is None, key
            assert at_price == [min(own, key=lambda k: abs(k - last))] and "spot" not in bars, key
    finally:
        _clear(tk)
