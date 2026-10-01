"""The live quote path and the order-flow engine read the stream only -- no stand-ins.

Measured facts these pin:
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




def test_mark_is_the_streamed_mark_only():
    """The spread as a fraction of MARK uses the streamed top of book's MARK; a REST quote block's
    mark is not read."""
    from app.options.order_flow.engine import compute_book_microstructure
    streamed = {"top": {"bid": 10.0, "ask": 10.1, "mark": 10.05}}
    assert compute_book_microstructure(streamed, now_ts=1.0)["spread_frac"] == round(0.1 / 10.05, 6)
    rest_only = {"top": {"bid": 10.0, "ask": 10.1}, "quote": {"mark": 10.05}}
    assert compute_book_microstructure(rest_only, now_ts=1.0)["spread_frac"] is None
