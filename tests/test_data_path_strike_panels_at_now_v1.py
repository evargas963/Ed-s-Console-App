"""The per-strike panels, Schwab to the screen, at the time asked: a captured chain published by the
levels producer, and every per-strike panel's answer (GEX by strike, the chart's DEX and OI, vanna,
charm) at that time is windowed around Schwab's price, whatever the wall clock says (AGENTS.md: a
function that depends on the clock takes `now`).

Real data: CRWD's 2026-10-16 expiry, every strike, captured 2026-10-07 10:38:40 ET (tests/real_chains.py
CRWD), and CRWD's LEVELONE_EQUITIES message the daemon received at 10:38:00 ET
(tests/fixtures/real_crwd_quote_2026_10_07.json), taken in by the plane at its receipt time: the
console's price record, read at the capture's instant.
"""
from __future__ import annotations

import json
from pathlib import Path

import live_market_plane as lmp
import server
from tests.feed_live_helper import forget_price
from tests.real_chains import CRWD

_QUOTE = json.loads((Path(__file__).resolve().parent / "fixtures" / "real_crwd_quote_2026_10_07.json")
                    .read_text(encoding="utf-8"))


def _clear(tk):
    with server._terrain_cache_lock:
        server._terrain_cache.pop(tk, None)
    forget_price(tk)
    lmp.record_feed_down()


def test_every_per_strike_panel_answers_at_the_time_asked_around_the_price():
    tk, at = server.ticker_storage_key(CRWD.ticker), CRWD.now.timestamp()
    _clear(tk)
    try:
        lmp.record_from_level_one_equity(tk, _QUOTE["native"], received_ts=_QUOTE["ts_recv"])
        lmp.record_feed_heartbeat({"ts": at, "schwab_socket_open": True, "held": {"LEVELONE_EQUITIES": [tk]}})
        server._publish_levels(tk, captures=[{"contracts": CRWD.chain, "ts_utc": at, "spot": CRWD.spot,
                                              "et_date": CRWD.now.date().isoformat(),
                                              "basis": server.CAPTURE_BASIS}], now=CRWD.now)
        last = _QUOTE["native"]["LAST_PRICE"]
        strikes = server.terrain_strikes_payload(tk, "auto", None, 0, at)
        assert strikes["spot"] == last and strikes["spot_strike"] is not None
        assert all(v["note"] is None for v in strikes["views"].values() if v["centre"] is not None)
        for key in server.STRIKE_BAR_METHODS:
            bars = server.strike_bar_payload(tk, key, "auto", None, 0, at)
            assert bars["available"] and bars["spot"] == last and bars["view"]["note"] is None, key
    finally:
        _clear(tk)
