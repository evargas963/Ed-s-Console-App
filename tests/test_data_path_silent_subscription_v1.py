"""Schwab -> the Flow panel. A missing heartbeat keeps the last subscription."""
from __future__ import annotations

import time

import live_market_plane as lmp
from app.options.order_flow import streaming as ofs


def test_a_missing_heartbeat_keeps_the_last_subscription():
    """The last beat held the contract. When that beat is gone the contract is still the one the
    daemon held, and the feed is not live. The page says OFFLINE. It does not say the daemon
    released the contract."""
    now = time.time()
    lmp.record_feed_heartbeat({
        "ts": now, "schwab_socket_open": True,
        "held": {"LEVELONE_OPTIONS": ["A"], "OPTIONS_BOOK": ["A"]},
    })
    try:
        live = ofs.get_option_contract_streaming_diagnostics("A", now)
        lmp.record_feed_down()
        down = ofs.get_option_contract_streaming_diagnostics("A", now)
    finally:
        lmp.record_feed_down()
    assert live["subscription_state"] == ofs.SUBSCRIBED
    assert live["feed_health"]["l1"]["state"] == "LIVE"
    assert down["subscription_state"] == ofs.SUBSCRIBED
    assert down["feed_health"]["l1"]["state"] == "NOT LIVE"
