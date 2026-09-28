"""The live quote path and the order-flow engine read the stream only -- no stand-ins.

2026-09-24 (operator rule: no fallbacks; full compliance). Measured facts these pin:
  * Schwab LEVELONE_EQUITIES sends changed fields only (4,039 captured messages: 11% carried
    bid+ask+last together) -- so the plane holds each field's latest value with its own age.
  * NET_CHANGE_PERCENT arrives with every LAST_PRICE; CHANGE_PERCENT is never sent.
"""
from __future__ import annotations

import time


import live_market_plane as lmp


def test_plane_change_percent_is_schwab_net_change_percent():
    lmp.record_from_level_one_equity(
        "NCPX", {"key": "NCPX", "LAST_PRICE": 101.0, "NET_CHANGE": 1.0, "NET_CHANGE_PERCENT": 1.0},
        received_ts=time.time())
    row = lmp.get_quote("NCPX")
    assert row["chg_pct"] == 1.0 and row["net_change"] == 1.0
    lmp.record_from_level_one_equity("NCPX", {"key": "NCPX", "BID_PRICE": 100.9},
                                     received_ts=time.time())
    assert lmp.get_quote("NCPX")["chg_pct"] == 1.0          # unchanged field stands


def test_the_regular_session_percent_is_its_own_field_absent_until_schwab_sends_it():
    """SPY's values as Schwab sent them on 2026-09-28: pre-market, NET_CHANGE_PERCENT only
    (extended hours included); in the session, REGULAR_MARKET_CHANGE_PERCENT with every trade."""
    lmp.record_from_level_one_equity(
        "ZZREG", {"key": "ZZREG", "LAST_PRICE": 767.5294, "NET_CHANGE_PERCENT": -0.495313},
        received_ts=time.time())
    row = lmp.get_quote("ZZREG")
    assert (row["chg_pct"], row["chg_pct_regular"]) == (-0.495313, None)
    lmp.record_from_level_one_equity(
        "ZZREG", {"key": "ZZREG", "LAST_PRICE": 764.0, "NET_CHANGE_PERCENT": -0.928243,
                  "REGULAR_MARKET_CHANGE_PERCENT": -0.928243}, received_ts=time.time())
    row = lmp.get_quote("ZZREG")
    assert (row["chg_pct"], row["chg_pct_regular"]) == (-0.928243, -0.928243)




def test_rest_cum_delta_is_gone():
    import server
    assert not hasattr(server, "_update_rest_cum_delta")
    assert not hasattr(server, "_rest_cum_delta")




def test_institutional_proxy_needs_all_four_components():
    from app.options.order_flow.engine import _compute_institutional_flow_proxy
    # no tape, no options chain: two of four components absent -> no score
    assert _compute_institutional_flow_proxy({}, book_imbalance_5=0.4) is None


def test_mark_is_the_streamed_mark_only():
    from app.options.order_flow.engine import _resolve_quote_mark
    assert _resolve_quote_mark({"top": {"mark": 10.05, "bid_size": 5}}) == (10.05, "streaming.MARK")
    assert _resolve_quote_mark({"quote": {"mark": 10.05}}) == (None, None)
