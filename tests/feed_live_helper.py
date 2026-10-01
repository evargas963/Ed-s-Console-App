"""Test helper: put live_market_plane's feed state where a real daemon heartbeat would.

Liveness is the FEED's (live_market_plane.feed_live_for): a daemon heartbeat < 3 s old that
reports the Schwab socket open and holds the symbol, judged at the `now` the caller passes.
Tests that exercise a live price mark exactly the symbols the daemon would hold -- through the
production entry point -- at an instant they name: SESSION_NOW (the market in session) or
CLOSED_NOW (a Saturday)."""
from __future__ import annotations

from datetime import datetime

import live_market_plane as lmp
from time_et import ET

#: stand-in (named): an instant the market is in session, Friday 2026-09-25 12:00 ET
SESSION_NOW = datetime(2026, 9, 25, 12, 0, tzinfo=ET).timestamp()
#: stand-in (named): an instant the market is closed, Saturday 2026-09-26 12:00 ET
CLOSED_NOW = datetime(2026, 9, 26, 12, 0, tzinfo=ET).timestamp()


def mark_feed_live(*tickers: str, now: float = SESSION_NOW) -> None:
    lmp.record_feed_heartbeat({"schwab_socket_open": True, "held": {"LEVELONE_EQUITIES": list(tickers)}}, now)


def mark_feed_down() -> None:
    lmp.record_feed_down()


def publish_daemon_rows(*tickers: str, now: float = SESSION_NOW) -> None:
    """What the daemon's price push hands the console: its price row per ticker at `now`, built
    by the daemon's own function from the daemon's plane (the test's live_market_plane stands in
    for the daemon's)."""
    import live_price_rows
    from app.options.order_flow import streaming as ofs
    for tk in tickers:
        row = live_price_rows.price_row(tk, now)
        ofs._price_rows[row["ticker"]] = row


def feed_live_during(monkeypatch, *tickers: str, now: float = SESSION_NOW) -> None:
    """For route tests that start the app (TestClient): the app's own push feed loop cannot
    reach a daemon in CI and marks the feed down on every retry, racing the test. Hold the
    feed live at `now` for this test by stubbing that mark-down; the feed loop's own behaviour is
    covered end-to-end in tests/test_live_push_channel_v1.py."""
    mark_feed_live(*tickers, now=now)
    monkeypatch.setattr(lmp, "record_feed_down", lambda: None)
