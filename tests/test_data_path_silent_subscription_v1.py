"""Schwab -> the Flow panel. A missing heartbeat keeps the last subscription."""

from __future__ import annotations

import live_market_plane as lmp
from app.options.order_flow import streaming as ofs
from tests.feed_live_helper import RTH_INSTANT, daemon_status

#: a contract Schwab listed and streamed: TSLA's 2026-08-31 367.5 call
#: (tests/fixtures/real_options_stream_history_samples.json)
_SYM = "TSLA  260831C00367500"


def test_a_missing_heartbeat_keeps_the_last_subscription():
    """The last beat held the contract.

    When that beat is gone the contract is still the one the daemon held, and the feed is down.
    The page says OFFLINE. It does not say the daemon released the contract. Judged in regular
    hours, the option market open (RTH_INSTANT).
    """
    now = RTH_INSTANT
    held = {"LEVELONE_OPTIONS": [_SYM], "OPTIONS_BOOK": [_SYM]}
    lmp.record_feed_heartbeat(daemon_status(now, schwab_socket_open=True, held=held))
    try:
        live = ofs.get_option_contract_streaming_diagnostics(_SYM, now)  # a stock option
        lmp.record_feed_down()
        down = ofs.get_option_contract_streaming_diagnostics(_SYM, now)
    finally:
        lmp.record_feed_down()
    assert live["subscription_state"] == ofs.SUBSCRIBED
    assert live["feed_health"]["l1"]["state"] == "LIVE"
    assert down["subscription_state"] == ofs.SUBSCRIBED
    assert down["feed_health"]["l1"]["state"] == "OFFLINE"
    # the badge the page draws is served: ACTIVE while held and live, the feed's own state after
    assert (live["subscription_active"], live["subscription_text"]) == (True, ofs.ACTIVE)
    assert (down["subscription_active"], down["subscription_text"]) == (False, "OFFLINE")
