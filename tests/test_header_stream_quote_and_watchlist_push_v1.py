"""The price is one row, built once by the capture daemon (live_price_rows.price_row) and pushed
to the browser (live_ui.py) and to the console alike: a price on screen and a price in a
console calculation are the same value."""
from __future__ import annotations

import live_market_plane as lmp
import live_price_rows
import server as srv
from tests.feed_live_helper import SESSION_NOW, feed_live_during


def test_an_unheld_symbol_row_is_unavailable_with_every_quote_field_withheld(monkeypatch) -> None:
    feed_live_during(monkeypatch, "ZZHELD")
    lmp.record_from_level_one_equity("ZZNOTHELD", {"LAST_PRICE": 9.0, "BID_PRICE": 8.9},
                                     received_ts=SESSION_NOW)
    row = live_price_rows.price_row("ZZNOTHELD", SESSION_NOW)
    assert row["spot"] is None and row["spot_state"] == "unavailable" and row["feed_live"] is False


def test_the_console_spot_is_the_daemons_price_row_and_the_console_keeps_no_copy(monkeypatch) -> None:
    """Measured 2026-09-28: the console's spot differed from the header's in 25 of 200
    same-moment checks -- the console rebuilt LAST_PRICE from the forwarded messages. Real TSLA
    quote as Schwab sent it (tests/fixtures/real_equity_book.json), received at the named session
    instant."""
    import json
    from pathlib import Path

    from app.options.order_flow import streaming as ofs
    from tests.feed_live_helper import publish_daemon_rows

    fx = json.loads((Path(__file__).parent / "fixtures" / "real_equity_book.json").read_text(encoding="utf-8"))
    tk, native, now = fx["ticker"], fx["quote"]["native"], SESSION_NOW
    monkeypatch.setattr(lmp, "_by_ticker", {})
    monkeypatch.setattr(lmp, "_fields_by_ticker", {})
    monkeypatch.setattr(ofs, "_price_rows", {})
    feed_live_during(monkeypatch, tk)
    # the console receives Schwab's message (its order-flow tape) and keeps no price of its own
    ofs._ingest_pushed(f"quote.{tk}", {"symbol": tk, "ts_recv": now, "native": native})
    assert lmp.get_quote(tk) is None and srv.resolve_spot(tk)[0] is None
    # the daemon builds its price row from the same message and pushes it
    lmp.record_from_level_one_equity(tk, native, received_ts=now)
    publish_daemon_rows(tk)
    row = ofs.price_row(tk)
    assert row["spot"] == native["LAST_PRICE"]
    assert srv.resolve_spot(tk) == (row["spot"], srv.SPOT_SOURCE_PLANE, row["trade_ts"])


def test_pages_are_told_the_daemon_price_port(monkeypatch) -> None:
    """The console fills the page's price-socket port from the daemon's own setting; e2e
    points it at a dead port so no test page can ever reach the real daemon."""
    from app.market_data.schwab.streaming import live_ui
    monkeypatch.setattr(live_ui, "LIVE_UI_PORT", 8811)
    html = srv.root().body.decode("utf-8")
    assert '<meta name="ed-live-ui-port" content="8811">' in html
    assert 'content="">' not in html.split("ed-live-ui-port", 1)[1][:12]






