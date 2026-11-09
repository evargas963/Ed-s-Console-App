"""Schwab -> the book panel. The quote time and the book time stay when the feed is down."""

from __future__ import annotations

import json
from pathlib import Path

import live_market_plane as lmp
import server
import time_et
from app.options.order_flow import state as of_state
from app.options.order_flow.engine import book_age_sec
from tests.feed_live_helper import mark_feed_live

_FX = Path(__file__).resolve().parent / "fixtures"
_TK = "ZZBKTIME"
_WHEN = 1790380799830  # Fri 09/25 06:59 PM CT


def test_a_down_feed_keeps_schwabs_quote_time_and_book_time_on_the_book():
    """QUOTE_TIME and BOOK_TIME are on the book the page paints. A feed that stops does not
    remove them, and the last bid stays.
    """
    mark_feed_live(_TK)
    lmp.record_from_level_one_equity(
        _TK,
        {
            "LAST_PRICE": 772.04,
            "BID_PRICE": 772.00,
            "ASK_PRICE": 772.08,
            "QUOTE_TIME_MILLIS": _WHEN,
            "TRADE_TIME_MILLIS": _WHEN,
        },
        received_ts=time_et.now(),
    )
    of_state.push_book(
        _TK,
        {
            "BIDS": [{"BID_PRICE": 772.00, "TOTAL_VOLUME": 10}],
            "ASKS": [{"ASK_PRICE": 772.08, "TOTAL_VOLUME": 8}],
            "BOOK_TIME": _WHEN,
        },
        "NASDAQ_BOOK",
    )
    now = time_et.now()
    try:
        lmp.record_feed_down()
        body = server.order_flow_microstructure(_TK, "NASDAQ_BOOK", now)
    finally:
        lmp._by_ticker.pop(_TK, None)
        lmp._fields_by_ticker.pop(_TK, None)
        of_state._LIVE_STATE._book.pop(_TK, None)
        lmp.record_feed_down()
    assert body["top_of_book"]["bid"] == 772.00
    assert body["top_outage"] is not None
    assert body["quote_time_ct"] == "Fri 09/25 06:59 PM CT"
    assert body["book_time_ct"] == "Fri 09/25 06:59 PM CT"
    # each time with its age, by the one formatter (time_et.age_text): the page draws the text
    age = time_et.age_text(now - _WHEN / 1000.0)
    assert body["book_when_age_text"] == "Fri 09/25 06:59 PM CT · " + age
    assert body["quote_when_age_text"] == "Fri 09/25 06:59 PM CT · " + age
    assert body["book_age_text"] == age


def _served_book_age(content: dict, now: float) -> float | None:
    of_state.push_book(_TK, content, "NYSE_BOOK")
    try:
        return server.order_flow_microstructure(_TK, "NYSE_BOOK", now)["ages"]["book_age_sec"]
    finally:
        of_state._LIVE_STATE._book.pop(_TK, None)


def test_the_book_age_is_read_from_schwabs_book_time_as_sent():
    """SPY's first NYSE_BOOK message of 2026-11-02 10:00 ET, as Schwab sent it: its age is the
    seconds from its BOOK_TIME to now, the one age (engine.book_age_sec) the microstructure and
    the Liquidity card both serve. INDUCED CONDITION: the same message with BOOK_TIME 0. Schwab's
    0 is a value (rule 2), so the age is from 0; it was served as no age here while the card
    served one.
    """
    rows = json.loads((_FX / "real_spy_books_2026_11_02.json").read_text(encoding="utf-8"))
    ts_recv, service, sent = next(r for r in rows["rows"] if r[1] == "NYSE_BOOK")
    assert service == "NYSE_BOOK"
    assert _served_book_age(sent, ts_recv) == ts_recv - sent["BOOK_TIME"] / 1000.0
    assert book_age_sec(sent["BOOK_TIME"], ts_recv) == ts_recv - sent["BOOK_TIME"] / 1000.0
    assert _served_book_age({**sent, "BOOK_TIME": 0}, ts_recv) == ts_recv
    assert book_age_sec(None, ts_recv) is None
