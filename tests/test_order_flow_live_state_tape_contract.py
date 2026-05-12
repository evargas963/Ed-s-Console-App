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

    assert tape == [{"LAST_PRICE": 500.0, "LAST_SIZE": None, "TRADE_TIME_MILLIS": 1_000}]
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
