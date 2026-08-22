from __future__ import annotations

import order_flow_engine as ofe
import order_flow_live_state as live_state


def test_live_state_preserves_missing_last_size_for_order_flow_consumers():
    sym = "MISSIZE"
    live_state.clear_symbol(sym)
    live_state.push_level_one(
        sym,
        {
            "key": sym,
            "LAST_PRICE": 500.0,
            "TRADE_TIME_MILLIS": 1_000,
        },
    )

    content = live_state.get_content_for_symbol(sym)
    tape = [item for item in content if item.get("TRADE_TIME_MILLIS") == 1_000]

    assert len(tape) == 1
    assert tape[0]["LAST_PRICE"] == 500.0
    assert tape[0]["LAST_SIZE"] is None
    assert tape[0]["TRADE_TIME_MILLIS"] == 1_000
    assert tape[0]["receive_seq"] == 1
    assert tape[0]["native_event_id"] is False
    assert ofe._compute_cum_delta_proxy({"content": content}) is None


def test_live_state_present_last_size_reaches_order_flow_consumers():
    sym = "HASSIZE"
    live_state.clear_symbol(sym)
    # First print anchors the prior trade price; second print is on the
    # uptick (500.0 -> 500.1) so cum_delta should be the second print's size.
    live_state.push_level_one(
        sym,
        {
            "key": sym,
            "LAST_PRICE": 500.0,
            "LAST_SIZE": 10,
            "TRADE_TIME_MILLIS": 1_000,
        },
    )
    live_state.push_level_one(
        sym,
        {
            "key": sym,
            "LAST_PRICE": 500.1,
            "LAST_SIZE": 12,
            "TRADE_TIME_MILLIS": 2_000,
        },
    )

    content = live_state.get_content_for_symbol(sym)

    assert ofe._compute_cum_delta_proxy({"content": content}) == 12


def test_same_ms_distinct_print_is_kept():
    sym = "SAMEMS"
    live_state.clear_symbol(sym)
    live_state.push_level_one(
        sym,
        {"key": sym, "LAST_PRICE": 500.0, "LAST_SIZE": 10, "TRADE_TIME_MILLIS": 1_000},
    )
    live_state.push_level_one(
        sym,
        {"key": sym, "LAST_PRICE": 500.1, "LAST_SIZE": 4, "TRADE_TIME_MILLIS": 1_000},
    )
    tape = [
        item for item in live_state.get_content_for_symbol(sym)
        if item.get("TRADE_TIME_MILLIS") == 1_000 and "LAST_PRICE" in item
    ]
    assert len(tape) == 2
    assert ofe._compute_cum_delta_proxy({"content": live_state.get_content_for_symbol(sym)}) == 4


def test_identical_same_ms_restatement_is_dropped():
    sym = "DUPMS"
    live_state.clear_symbol(sym)
    payload = {"key": sym, "LAST_PRICE": 500.0, "LAST_SIZE": 10, "TRADE_TIME_MILLIS": 1_000}
    live_state.push_level_one(sym, payload)
    live_state.push_level_one(sym, payload)
    tape = [
        item for item in live_state.get_content_for_symbol(sym)
        if item.get("TRADE_TIME_MILLIS") == 1_000 and "LAST_SIZE" in item
    ]
    assert len(tape) == 1


def test_forget_unsubscribed_clears_leaving_symbol_only():
    live_state.clear_symbol("SPY")
    live_state.clear_symbol("QQQ")
    live_state.push_level_one(
        "SPY",
        {"key": "SPY", "LAST_PRICE": 500.0, "LAST_SIZE": 10, "TRADE_TIME_MILLIS": 1_000},
    )
    live_state.push_level_one(
        "QQQ",
        {"key": "QQQ", "LAST_PRICE": 400.0, "LAST_SIZE": 8, "TRADE_TIME_MILLIS": 1_000},
    )
    live_state.forget_unsubscribed_symbols(["SPY", "QQQ"], ["QQQ"])
    spy_tape = [i for i in live_state.get_content_for_symbol("SPY") if i.get("LAST_PRICE") is not None]
    qqq_tape = [i for i in live_state.get_content_for_symbol("QQQ") if i.get("LAST_PRICE") is not None]
    assert spy_tape == []
    assert any(i.get("LAST_PRICE") == 400.0 for i in qqq_tape)


def test_session_reset_clears_prev_trade_identity():
    live_state._prev_trade["Z"] = {"price": 1, "size": 1, "time_millis": 1}
    with live_state._lock:
        live_state._clear_all_session_state_unlocked()
    assert live_state._prev_trade == {}
