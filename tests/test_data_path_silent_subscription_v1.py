"""Schwab -> the Flow panel. A missing heartbeat keeps the last subscription."""

from __future__ import annotations

import live_market_plane as lmp
from app.options.order_flow import streaming as ofs
from tests.feed_live_helper import RTH_INSTANT
from time_et import EQUITY_OPTIONS


def test_a_missing_heartbeat_keeps_the_last_subscription():
    """The last beat held the contract. When that beat is gone the contract is still the one the
    daemon held, and the feed is down. The page says OFFLINE. It does not say the daemon
    released the contract. Judged in regular hours, the option market open (RTH_INSTANT)."""
    now = RTH_INSTANT
    lmp.record_feed_heartbeat(
        {
            "ts": now,
            "schwab_socket_open": True,
            "held": {"LEVELONE_OPTIONS": ["A"], "OPTIONS_BOOK": ["A"]},
        }
    )
    try:
        live = ofs.get_option_contract_streaming_diagnostics(
            "A", now, EQUITY_OPTIONS
        )  # a stock option
        lmp.record_feed_down()
        down = ofs.get_option_contract_streaming_diagnostics("A", now, EQUITY_OPTIONS)
    finally:
        lmp.record_feed_down()
    assert live["subscription_state"] == ofs.SUBSCRIBED
    assert live["feed_health"]["l1"]["state"] == "LIVE"
    assert down["subscription_state"] == ofs.SUBSCRIBED
    assert down["feed_health"]["l1"]["state"] == "OFFLINE"
