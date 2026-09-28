"""Test helper: put live_market_plane's feed state where a real daemon heartbeat would.

Liveness is the FEED's (live_market_plane.feed_live_for): a daemon heartbeat < 3 s old that
reports the Schwab socket open and holds the symbol. Tests that exercise a live price mark
exactly the symbols the daemon would hold -- through the production entry point."""
from __future__ import annotations

import time

import live_market_plane as lmp


def mark_feed_live(*tickers: str) -> None:
    lmp.record_feed_heartbeat({"schwab_socket_open": True, "held": {"LEVELONE_EQUITIES": list(tickers)}}, time.time())


def mark_feed_down() -> None:
    lmp.record_feed_down()


def publish_daemon_rows(*tickers: str) -> None:
    """What the daemon's price push hands the console: its price row per ticker, built by the
    daemon's own function from the daemon's plane (the test's live_market_plane stands in for
    the daemon's)."""
    import live_price_rows
    from app.options.order_flow import streaming as ofs
    for tk in tickers:
        row = live_price_rows.price_row(tk)
        ofs._price_rows[row["ticker"]] = row


def feed_live_during(monkeypatch, *tickers: str) -> None:
    """For route tests that start the app (TestClient): the app's own push feed loop cannot
    reach a daemon in CI and marks the feed down on every retry, racing the test. Hold the
    feed live for this test by stubbing that mark-down; the feed loop's own behaviour is
    covered end-to-end in tests/test_live_push_channel_v1.py."""
    mark_feed_live(*tickers)
    monkeypatch.setattr(lmp, "record_feed_down", lambda: None)
    # importing/starting the app can take longer than the 3 s heartbeat bound on a loaded CI
    # worker; heartbeat AGE is not what these tests exercise (it has its own tests)
    monkeypatch.setattr(lmp, "FEED_HEARTBEAT_MAX_AGE_SEC", 3600.0)
