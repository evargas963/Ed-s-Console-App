"""The price is Schwab's LEVELONE_EQUITIES fields, pushed by the capture daemon as Schwab sent
them (live_ui.py) to the browser and to the console alike. The console keeps one record of them
per ticker, its live_market_plane entry, which live_price_rows.price_row reads; it keeps no other
copy, so a price in a console calculation is the record's."""
from __future__ import annotations

import time

import live_market_plane as lmp
import server as srv
from stream_spine import MessageBus, current_key


def test_a_symbol_the_daemon_does_not_hold_is_absent_in_session_and_stands_while_closed() -> None:
    """The Schwab socket open but the symbol not held (docs/DATA_FLOW.md §2 D5): during RTH its
    row serves no values and says why; at 22:00 ET the values Schwab sent stand."""
    try:
        for now, served in ((1790780400.0, (None, None)), (1790820000.0, (9.0, 8.9))):  # 11:00, 22:00 ET
            lmp.record_feed_heartbeat({"ts": now, "schwab_socket_open": True,
                                       "held": {"LEVELONE_EQUITIES": ["ZZHELD"]}})
            lmp.record_from_level_one_equity("ZZNOTHELD", {"LAST_PRICE": 9.0, "BID_PRICE": 8.9},
                                             received_ts=now)
            row = srv.price_row("ZZNOTHELD", now)
            assert (row["spot"], row["bid"], row["feed_live"]) == (*served, False)
            assert (row["outage"] is None) == (served[0] is not None)
    finally:
        lmp.record_feed_down()


def test_the_console_spot_is_its_price_record_and_the_console_keeps_no_other_copy() -> None:
    """Measured 2026-09-28: the console's spot differed from the header's in 25 of 200
    same-moment checks -- the console rebuilt LAST_PRICE from the forwarded messages. The
    console's one price is its live_market_plane record: the order-flow tape's copy of Schwab's
    message is no price, the spot is the record's row (live_price_rows.price_row), and without
    the record the console has no price. Real TSLA quote as Schwab sent it
    (tests/fixtures/real_equity_book.json), received now."""
    import json
    from pathlib import Path

    from app.options.order_flow import streaming as ofs
    from tests.feed_live_helper import forget_price

    fx = json.loads((Path(__file__).parent / "fixtures" / "real_equity_book.json").read_text(encoding="utf-8"))
    tk, native, now = fx["ticker"], fx["quote"]["native"], time.time()
    for kept in (lmp._by_ticker, lmp._fields_by_ticker):
        kept.pop(tk, None)
    lmp.record_feed_heartbeat({"ts": now, "schwab_socket_open": True, "held": {"LEVELONE_EQUITIES": [tk]}})
    try:
        # the console receives Schwab's message on its order-flow tape: that is no price
        bus = MessageBus()                  # the record as the daemon's bus holds and pushes it
        sent = {"symbol": tk, "ts_recv": now, "native": native}
        bus.publish(f"quote.{tk}", sent)
        ofs._ingest_pushed(f"quote.{tk}", bus.current[current_key(f"quote.{tk}", sent)][1])
        assert lmp.get_quote(tk) is None and srv.resolve_spot(tk, now=now)[0] is None
        # the same fields, as the daemon pushes them, taken into the console's price record
        lmp.record_from_level_one_equity(tk, native, received_ts=now)
        row = srv.price_row(tk, now)
        assert row["spot"] == native["LAST_PRICE"]
        assert srv.resolve_spot(tk, now=now) == (row["spot"], srv.SPOT_SOURCE_PLANE, row["trade_ts"])
        # the record is the console's only copy: without it, the console has no price
        forget_price(tk)
        assert lmp.get_quote(tk) is None and srv.resolve_spot(tk, now=now)[0] is None
    finally:
        for kept in (lmp._by_ticker, lmp._fields_by_ticker):
            kept.pop(tk, None)
        lmp.record_feed_down()


def test_the_page_is_told_no_daemon_port() -> None:
    """One delivery (Ed, design A): the console's push (/api/live) is the page's only path; the
    page served carries no daemon port (the browser test that it opens no other socket:
    tests/e2e/console-gamma-heatmap.spec.js)."""
    assert "ed-live-ui-port" not in srv.root().body.decode("utf-8")






