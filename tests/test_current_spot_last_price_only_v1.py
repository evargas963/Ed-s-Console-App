"""Adversarial lock: MARK / close / chain / snapshot / bar-close cannot become current live spot.

With the feed live (a feed down in an open session is its own reason: test_data_path_rules_v1 D5).
"""

from __future__ import annotations

import pytest

import live_market_plane as L
import server
import time_et
from tests.feed_live_helper import RTH_INSTANT, mark_feed_down, mark_feed_live


@pytest.fixture(autouse=True)
def _feed_live():
    mark_feed_live("SPY", "MARKNEVER", "KEEPLAST", now=RTH_INSTANT)
    yield
    mark_feed_down()


def test_resolve_spot_rejects_mark_close_chain_and_snapshot() -> None:
    L._by_ticker.pop("SPY", None)  # no LAST_PRICE in the plane: a chain, MARK or close is no spot
    spot, source, _ts = server.resolve_spot("SPY", now=RTH_INSTANT)
    assert spot is None
    assert source == server.SPOT_SOURCE_NONE


def test_plane_mark_only_tick_never_creates_current_spot() -> None:
    L._by_ticker.pop("MARKNEVER", None)
    ok = L.record_from_level_one_equity(
        "MARKNEVER",
        {"key": "MARKNEVER", "MARK": 20.95, "BID_PRICE": 20.9, "ASK_PRICE": 21.1},
        received_ts=time_et.now(),
    )
    assert ok is True  # the quote Schwab sent is published
    assert L.get_quote("MARKNEVER")["spot"] is None  # MARK never stands in for the spot
    spot, source, _ts = server.resolve_spot("MARKNEVER", now=RTH_INSTANT)
    assert spot is None
    assert source == server.SPOT_SOURCE_NONE


def test_plane_mark_cannot_replace_prior_last_price() -> None:
    L._by_ticker.pop("KEEPLAST", None)
    assert L.record_from_level_one_equity(
        "KEEPLAST",
        {"key": "KEEPLAST", "LAST_PRICE": 50.0, "MARK": 50.2, "BID_PRICE": 49.9, "ASK_PRICE": 50.1},
        received_ts=time_et.now(),
    )
    assert L.record_from_level_one_equity(
        "KEEPLAST",
        {"key": "KEEPLAST", "MARK": 99.99, "BID_PRICE": 99.9, "ASK_PRICE": 100.1},
        received_ts=time_et.now(),
    )
    row = L.get_quote("KEEPLAST")
    assert row is not None
    assert row["spot"] == 50.0
    assert row["mark"] == 99.99  # Schwab's MARK is its own field, never the price
    L._by_ticker.pop("KEEPLAST", None)
