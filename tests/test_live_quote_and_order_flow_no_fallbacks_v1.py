"""The live quote path and the order-flow engine read the stream only -- no stand-ins.

2026-09-24 (operator rule: no fallbacks; full compliance). Measured facts these pin:
  * Schwab LEVELONE_EQUITIES sends changed fields only (4,039 captured messages: 11% carried
    bid+ask+last together) -- so the plane holds each field's latest value with its own age.
  * NET_CHANGE_PERCENT arrives with every LAST_PRICE; CHANGE_PERCENT is never sent.
"""
from __future__ import annotations

import inspect
import time

import pytest

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


def test_fetch_state_reads_no_rest_quote():
    import server
    src = inspect.getsource(server._fetch_state)
    assert "_memoized_quote_response" not in src, "the per-cycle REST quote is back"
    assert "q_json" not in src and "_quote_fut" not in src
    assert "safe_get_price_history(client, ticker, frequency_minutes=1" not in src, (
        "the REST price-history candle-volume stand-in is back")


def test_rest_cum_delta_is_gone():
    import server
    assert not hasattr(server, "_update_rest_cum_delta")
    assert not hasattr(server, "_rest_cum_delta")


def test_order_flow_state_requires_the_daemon_receive_time():
    from app.options.order_flow.state import OrderFlowState
    st = OrderFlowState()
    with pytest.raises(TypeError):
        st.push_level_one("SPY", {"LAST_PRICE": 1.0})
    t = time.time() - 30.0
    st.push_level_one("SPY", {"LAST_PRICE": 1.0, "LAST_SIZE": 5, "TRADE_TIME_MILLIS": 1}, ts_recv=t)
    assert st.get_receive_log("SPY")[-1]["server_received_ts"] == t   # not the console clock
    assert not hasattr(st, "get_stream_chg_pct")


def test_institutional_proxy_needs_all_four_components():
    from app.options.order_flow.engine import _compute_institutional_flow_proxy
    # no tape, no options chain: two of four components absent -> no score
    assert _compute_institutional_flow_proxy({}, book_imbalance_5=0.4) is None


def test_mark_is_resolved_per_field_from_the_stream():
    from app.options.order_flow.engine import _resolve_quote_mark
    now = time.time()
    items = [{"MARK": 10.05, "MARK_TS_RECV": now - 1}, {"BID_SIZE": 5, "BID_SIZE_TS_RECV": now}]
    assert _resolve_quote_mark({"content": items}, now_ts=now) == (10.05, "streaming.MARK")
    assert _resolve_quote_mark({"quote": {"mark": 10.05}}, now_ts=now) == (None, None)
