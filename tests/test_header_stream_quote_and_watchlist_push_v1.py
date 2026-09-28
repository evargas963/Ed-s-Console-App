"""The displayed price (header + watchlist + chart) is ONE row: live_price_rows.price_row.

Since the daemon-to-browser change (Stage 1 of the live-UI architecture) the capture daemon
pushes that row straight to the browser (app/market_data/schwab/streaming/live_ui.py, proven
end to end in tests/test_live_ui_daemon_to_browser_v1.py). The console keeps no price
relay: its analytics stream carries gamma/L1 analytics only, and its watchlist route reads
the same row function -- so a price on screen and a price in a console calculation cannot
come from two rules.
"""
from __future__ import annotations

import time

import live_market_plane as lmp
import live_price_rows
import server as srv
from tests.feed_live_helper import feed_live_during


def test_an_unheld_symbol_row_is_unavailable_with_every_quote_field_withheld(monkeypatch) -> None:
    feed_live_during(monkeypatch, "ZZHELD")
    lmp.record_from_level_one_equity("ZZNOTHELD", {"LAST_PRICE": 9.0, "BID_PRICE": 8.9},
                                     received_ts=time.time())
    row = live_price_rows.price_row("ZZNOTHELD")
    assert row["spot"] is None and row["spot_state"] == "unavailable" and row["feed_live"] is False


def test_console_spot_and_watchlist_read_the_same_row_function(monkeypatch) -> None:
    feed_live_during(monkeypatch, "ZZW1")
    lmp.record_from_level_one_equity("ZZW1", {"LAST_PRICE": 20.0}, received_ts=time.time())
    spot, src, _ = srv.resolve_spot("ZZW1")
    assert spot == live_price_rows.live_spot("ZZW1") == 20.0 and src == srv.SPOT_SOURCE_PLANE


def test_pages_are_told_the_daemon_price_port(monkeypatch) -> None:
    """The console fills the page's price-socket port from the daemon's own setting; e2e
    points it at a dead port so no test page can ever reach the real daemon."""
    from app.market_data.schwab.streaming import live_ui
    monkeypatch.setattr(live_ui, "LIVE_UI_PORT", 8811)
    html = srv.root().body.decode("utf-8")
    assert '<meta name="ed-live-ui-port" content="8811">' in html
    assert 'content="">' not in html.split("ed-live-ui-port", 1)[1][:12]






