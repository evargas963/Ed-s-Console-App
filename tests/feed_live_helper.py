"""Test helper: put live_market_plane's feed state where a real daemon heartbeat would.

Liveness is the FEED's (live_market_plane.feed_live_for): a daemon heartbeat < 3 s old that
reports the Schwab socket open and holds the symbol. Tests that exercise a live price mark
exactly the symbols the daemon would hold -- through the production entry point."""
from __future__ import annotations

import time

import live_market_plane as lmp


def mark_feed_live(*tickers: str) -> None:
    lmp.record_feed_heartbeat({"schwab_socket_open": True, "equities_held": list(tickers)}, time.time())


def mark_feed_down() -> None:
    lmp.record_feed_down()
