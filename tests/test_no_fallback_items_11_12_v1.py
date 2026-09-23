"""No-fallback items 11-12: malformed (present-but-non-list) BIDS/ASKS used to be wrapped
into a fake single-element list ([bids]) instead of being rejected -- fabricating a
valid-looking one-level book out of a shape the rest of the book pipeline never actually
produces. Fixed at both the write side (state.py's push_book, the entry point from raw
Schwab stream content) and the read side (engine.py's _iter_bids_levels/_iter_asks_levels,
an independent parser of the same raw content shape).
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import app.options.order_flow.engine as ofe
from app.options.order_flow.state import OrderFlowState


def test_push_book_drops_malformed_non_list_bids(caplog):
    st = OrderFlowState()
    with caplog.at_level(logging.WARNING):
        st.push_book("SPY", {"BIDS": "not a list", "ASKS": [{"ASK_PRICE": 1.0, "TOTAL_VOLUME": 10}]})
    book = list(st._get_book("SPY"))
    assert book == [], (
        "MUTATION CONTROL FAILED TO BITE: a malformed (non-list) BIDS must be dropped "
        f"entirely, not wrapped into a fake one-level book -- got {book!r}")
    assert any("malformed BIDS/ASKS" in r.message for r in caplog.records)


def test_push_book_drops_malformed_non_list_asks():
    st = OrderFlowState()
    st.push_book("SPY", {"BIDS": [{"BID_PRICE": 1.0, "TOTAL_VOLUME": 10}], "ASKS": {"not": "a list"}})
    assert list(st._get_book("SPY")) == []


def test_push_book_accepts_well_formed_lists():
    st = OrderFlowState()
    st.push_book("SPY", {
        "BIDS": [{"BID_PRICE": 1.0, "TOTAL_VOLUME": 10}],
        "ASKS": [{"ASK_PRICE": 1.1, "TOTAL_VOLUME": 5}],
        "BOOK_TIME": 12345,
    })
    book = list(st._get_book("SPY"))
    assert len(book) == 1
    assert book[0]["BIDS"] == [{"BID_PRICE": 1.0, "TOTAL_VOLUME": 10}]
    assert book[0]["ASKS"] == [{"ASK_PRICE": 1.1, "TOTAL_VOLUME": 5}]


def test_iter_bids_levels_rejects_malformed_scalar():
    assert ofe._iter_bids_levels({"BIDS": "garbage"}) == []
    assert ofe._iter_bids_levels({"BIDS": 42}) == []


def test_iter_asks_levels_rejects_malformed_scalar():
    assert ofe._iter_asks_levels({"ASKS": "garbage"}) == []
    assert ofe._iter_asks_levels({"ASKS": 42}) == []


def test_iter_bids_asks_levels_still_extract_well_formed_lists():
    bids = ofe._iter_bids_levels({"BIDS": [{"BID_PRICE": 100.0, "TOTAL_VOLUME": 5}]})
    asks = ofe._iter_asks_levels({"ASKS": [{"ASK_PRICE": 101.0, "TOTAL_VOLUME": 7}]})
    assert bids == [(100.0, 5.0)]
    assert asks == [(101.0, 7.0)]
