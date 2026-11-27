"""The live quote path and the order-flow engine read the stream only -- no stand-ins.

2026-09-24 (operator rule: no fallbacks; full compliance). Measured facts these pin:
  * Schwab LEVELONE_EQUITIES sends changed fields only (4,039 captured messages: 11% carried
    bid+ask+last together) -- so the plane holds each field's latest value with its own age.
  * NET_CHANGE_PERCENT arrives with every LAST_PRICE; CHANGE_PERCENT is never sent.
"""

from __future__ import annotations

import live_market_plane as lmp
from calc.order_flow import FlowInput, _resolve_quote_mark
from option_contract import StreamedTop


def test_plane_change_percent_is_schwab_net_change_percent():
    lmp.record_from_level_one_equity(
        "NCPX",
        {"key": "NCPX", "LAST_PRICE": 101.0, "NET_CHANGE": 1.0, "NET_CHANGE_PERCENT": 1.0},
        received_ts=100.0,
    )
    row = lmp.get_quote("NCPX")
    assert row.chg_pct == 1.0 and row.net_change == 1.0
    lmp.record_from_level_one_equity("NCPX", {"key": "NCPX", "BID_PRICE": 100.9}, received_ts=105.0)
    assert lmp.get_quote("NCPX").chg_pct == 1.0  # unchanged field stands


def test_a_quote_an_earlier_test_recorded_is_not_held_for_the_next():
    """Every test starts with no quote held, as the program starts with none.

    The test above, run before this one in the same process, recorded NCPX; nothing of it is
    held here (each run of one process found a quote of an earlier test's: mutmut's runs, one
    process for every test, failed on it).
    """
    assert lmp.get_quote("NCPX") == lmp.NO_QUOTE


def test_the_regular_session_percent_is_its_own_field_absent_until_schwab_sends_it():
    """SPY's values as Schwab sent them on 2026-09-28.

    Pre-market, NET_CHANGE_PERCENT only (extended hours included); in the session,
    REGULAR_MARKET_CHANGE_PERCENT with every trade.
    """
    lmp.record_from_level_one_equity(
        "ZZREG",
        {"key": "ZZREG", "LAST_PRICE": 767.5294, "NET_CHANGE_PERCENT": -0.495313},
        received_ts=100.0,
    )
    row = lmp.get_quote("ZZREG")
    assert (row.chg_pct, row.chg_pct_regular) == (-0.495313, None)
    lmp.record_from_level_one_equity(
        "ZZREG",
        {
            "key": "ZZREG",
            "LAST_PRICE": 764.0,
            "NET_CHANGE_PERCENT": -0.928243,
            "REGULAR_MARKET_CHANGE_PERCENT": -0.928243,
        },
        received_ts=105.0,
    )
    row = lmp.get_quote("ZZREG")
    assert (row.chg_pct, row.chg_pct_regular) == (-0.928243, -0.928243)


def test_mark_is_the_streamed_mark_only():
    assert (
        _resolve_quote_mark(FlowInput(book=None, top=StreamedTop(mark=10.05, bid_size=5))) == 10.05
    )
    assert _resolve_quote_mark(FlowInput(book=None)) is None, "no top of book: no mark"
