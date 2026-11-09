"""Adversarial lock: MARK / close / chain / snapshot / bar-close cannot become current live spot.

With the feed live (a feed down in an open session is its own reason: test_data_path_rules_v1 D5).

Real data: AMZN's LEVELONE_EQUITIES message of 2026-10-05 14:00:02 CT carrying MARK, BID_PRICE and
no LAST_PRICE (real_stream_mix_2026_10_05_1400ct.json); SPY's two consecutive messages of
2026-11-06 15:53:28 ET, the first with LAST_PRICE and MARK, the next with MARK and no LAST_PRICE
(real_spy_mark_after_last_price_2026_11_06.json). Each as Schwab sent it.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import live_market_plane as L
import server
from tests.feed_live_helper import RTH_INSTANT, mark_feed_down, mark_feed_live

_FX = Path(__file__).resolve().parent / "fixtures"
_AMZN_MARK_ONLY = next(
    m
    for m in json.loads(
        (_FX / "real_stream_mix_2026_10_05_1400ct.json").read_text(encoding="utf-8")
    )["messages"]
    if m["service"] == "LEVELONE_EQUITIES"
    and m["item"]["key"] == "AMZN"
    and "MARK" in m["item"]
    and "LAST_PRICE" not in m["item"]
)
_SPY_LAST, _SPY_MARK_ONLY = json.loads(
    (_FX / "real_spy_mark_after_last_price_2026_11_06.json").read_text(encoding="utf-8")
)["messages"]


@pytest.fixture(autouse=True)
def _feed_live():
    mark_feed_live("SPY", "AMZN", now=RTH_INSTANT)
    yield
    mark_feed_down()


def test_resolve_spot_rejects_mark_close_chain_and_snapshot() -> None:
    L._by_ticker.pop("SPY", None)  # no LAST_PRICE in the plane: a chain, MARK or close is no spot
    spot, source, _ts = server.resolve_spot("SPY", now=RTH_INSTANT)
    assert spot is None
    assert source == server.SPOT_SOURCE_NONE


def test_plane_mark_only_tick_never_creates_current_spot() -> None:
    L._by_ticker.pop("AMZN", None)
    try:
        ok = L.record_from_level_one_equity(
            "AMZN", _AMZN_MARK_ONLY["item"], received_ts=_AMZN_MARK_ONLY["ts_recv"]
        )
        assert ok is True  # the quote Schwab sent is published
        assert L.get_quote("AMZN")["spot"] is None  # MARK never stands in for the spot
        spot, source, _ts = server.resolve_spot("AMZN", now=RTH_INSTANT)
    finally:
        L._by_ticker.pop("AMZN", None)
    assert spot is None
    assert source == server.SPOT_SOURCE_NONE


def test_plane_mark_cannot_replace_prior_last_price() -> None:
    L._by_ticker.pop("SPY", None)
    try:
        assert L.record_from_level_one_equity(
            "SPY", _SPY_LAST["item"], received_ts=_SPY_LAST["ts_recv"]
        )
        assert L.record_from_level_one_equity(
            "SPY", _SPY_MARK_ONLY["item"], received_ts=_SPY_MARK_ONLY["ts_recv"]
        )
        row = L.get_quote("SPY")
    finally:
        L._by_ticker.pop("SPY", None)
    assert row is not None
    assert row["spot"] == _SPY_LAST["item"]["LAST_PRICE"] == 735.89
    # Schwab's MARK is its own field, never the price
    assert row["mark"] == _SPY_MARK_ONLY["item"]["MARK"] == 735.86
