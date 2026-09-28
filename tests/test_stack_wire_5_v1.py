"""The order-flow state's session reset follows the one market calendar (time_et.session_label).

ONE-10 (2026-09-28 audit): the state kept its own 09:30-16:00 weekday rule (is_rth_open), blind to
holidays and early closes, so a holiday's first quote at 10:00 wiped the books and tape as if a
session had opened. Real SPY NASDAQ_BOOK (tests/fixtures/real_spy_nyse_nasdaq_books.json); the
clock is pinned; stand-in: 2026-09-24 declared a full holiday or a 13:00 early close."""
from __future__ import annotations

import datetime as _dt
import json
from pathlib import Path

import pytest

import app.options.order_flow.state as ofls
import time_et
from time_et import ET

_BOOK = json.loads((Path(__file__).parent / "fixtures" / "real_spy_nyse_nasdaq_books.json")
                   .read_text(encoding="utf-8"))["books"]["NASDAQ_BOOK"]["content"]


def _book_kept_after_a_quote_at(monkeypatch, hh, mm):
    """A book arrives before the open; one quote arrives at hh:mm on 2026-09-24. Is the book
    still there (no session reset)?"""
    monkeypatch.setattr(ofls, "now_et", lambda: _dt.datetime(2026, 9, 24, 8, 0, tzinfo=ET))
    st = ofls.OrderFlowState()
    st.push_book("SPY", _BOOK, "NASDAQ_BOOK")
    monkeypatch.setattr(ofls, "now_et", lambda: _dt.datetime(2026, 9, 24, hh, mm, tzinfo=ET))
    st.push_level_one("SPY", {"key": "SPY", "LAST_PRICE": 660.0}, ts_recv=1.0)
    return any(i.get("BIDS") for i in st.get_content_for_symbol("SPY", "NASDAQ_BOOK"))


def test_the_session_opens_at_0930_on_a_trading_day(monkeypatch):
    assert _book_kept_after_a_quote_at(monkeypatch, 9, 29) is True
    assert _book_kept_after_a_quote_at(monkeypatch, 9, 30) is False     # the session reset


def test_a_holiday_never_opens_a_session(monkeypatch):
    monkeypatch.setattr(time_et, "US_EQUITY_FULL_HOLIDAYS_ET",
                        time_et.US_EQUITY_FULL_HOLIDAYS_ET | {"2026-09-24"})
    assert _book_kept_after_a_quote_at(monkeypatch, 10, 0) is True


@pytest.mark.parametrize("hh,mm,kept", [(12, 59, False), (13, 30, True)])
def test_an_early_close_ends_the_session_at_the_calendars_close(monkeypatch, hh, mm, kept):
    monkeypatch.setitem(time_et.US_EQUITY_EARLY_CLOSE_MINS_ET, "2026-09-24", time_et.EARLY_CLOSE_MINS)
    assert _book_kept_after_a_quote_at(monkeypatch, hh, mm) is kept
