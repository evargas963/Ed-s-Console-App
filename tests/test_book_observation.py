"""book_observation: BookSnapshotObservation/BookLevel vs. the real production formulas."""
from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pytest

from book_observation import BookLevel, BookSnapshotObservation
from market_observation import FreshnessState


def _real_book_side_depth_total(levels, depth):
    """Reproduces app/options/order_flow/engine.py:_book_side_depth_total exactly."""
    if not levels:
        return None
    return sum(v for _, v in levels[:depth])


def _real_book_imbalance_from_totals(bid_total, ask_total):
    """Reproduces app/options/order_flow/engine.py:_book_imbalance_from_totals exactly."""
    if bid_total is None or ask_total is None:
        return None
    total = bid_total + ask_total
    if total <= 0:
        return None
    return (bid_total - ask_total) / total


BID_RAW = [(100.5, 300.0), (100.4, 500.0), (100.3, 200.0)]
ASK_RAW = [(100.6, 250.0), (100.7, 400.0)]


def _live_snapshot():
    return BookSnapshotObservation(
        bid_levels=tuple(BookLevel(p, v) for p, v in BID_RAW),
        ask_levels=tuple(BookLevel(p, v) for p, v in ASK_RAW),
        state=FreshnessState.LIVE,
        source="schwab_streaming_book",
        book_time_ms=1_778_018_400_000.0,
        received_ts=time.time(),
    )


@pytest.mark.parametrize("depth", [1, 3, 5])
def test_depth_total_matches_real_formula(depth):
    snap = _live_snapshot()
    assert snap.depth_total("bid", depth) == _real_book_side_depth_total(BID_RAW, depth)
    assert snap.depth_total("ask", depth) == _real_book_side_depth_total(ASK_RAW, depth)


@pytest.mark.parametrize("depth", [1, 3, 5])
def test_imbalance_matches_real_formula(depth):
    snap = _live_snapshot()
    real_bid = _real_book_side_depth_total(BID_RAW, depth)
    real_ask = _real_book_side_depth_total(ASK_RAW, depth)
    assert snap.imbalance(depth) == _real_book_imbalance_from_totals(real_bid, real_ask)


def test_unavailable_book_is_none_everywhere_and_distinct_state():
    snap = BookSnapshotObservation.unavailable(source="schwab_streaming_book", received_ts=time.time())
    assert snap.state is FreshnessState.UNAVAILABLE
    assert snap.depth_total("bid", 3) is None
    assert snap.depth_total("ask", 3) is None
    assert snap.imbalance(3) is None
    assert snap.bid_levels == ()
    assert snap.ask_levels == ()
    assert snap.book_time_ms is None


def test_stale_book_still_reports_a_real_number_disclosed_as_stale():
    """RC-REHAB-1: the gap this type exists to close -- _extract_canonical_book today
    collapses an aged-out book to the same has_book=False an ACTUALLY-absent book gets. A
    STALE snapshot must still compute a real imbalance from its carried levels, distinct
    from an UNAVAILABLE one that has none at all."""
    stale = BookSnapshotObservation(
        bid_levels=tuple(BookLevel(p, v) for p, v in BID_RAW),
        ask_levels=tuple(BookLevel(p, v) for p, v in ASK_RAW),
        state=FreshnessState.STALE,
        source="schwab_streaming_book",
        book_time_ms=1_778_018_000_000.0,
        received_ts=time.time(),
    )
    real_bid = _real_book_side_depth_total(BID_RAW, 3)
    real_ask = _real_book_side_depth_total(ASK_RAW, 3)
    assert stale.imbalance(3) == _real_book_imbalance_from_totals(real_bid, real_ask)
    assert stale.state is not FreshnessState.UNAVAILABLE


def test_depth_total_rejects_an_invalid_side_instead_of_silently_reading_ask():
    """RC-REHAB-1 mutation test: an adversarial review caught depth_total("BID", ...) (or any
    non-"bid" string) silently falling through to the ask side. Must raise instead."""
    snap = _live_snapshot()
    with pytest.raises(ValueError):
        snap.depth_total("BID", 3)
    with pytest.raises(ValueError):
        snap.depth_total("", 3)
    with pytest.raises(ValueError):
        snap.depth_total(None, 3)  # type: ignore[arg-type]


def test_unavailable_book_rejects_levels_or_a_book_time():
    with pytest.raises(ValueError):
        BookSnapshotObservation(
            bid_levels=(BookLevel(1.0, 1.0),), ask_levels=(),
            state=FreshnessState.UNAVAILABLE,
            source="x", book_time_ms=None, received_ts=time.time(),
        )
    with pytest.raises(ValueError):
        BookSnapshotObservation(
            bid_levels=(), ask_levels=(),
            state=FreshnessState.UNAVAILABLE,
            source="x", book_time_ms=1.0, received_ts=time.time(),
        )


def test_book_level_rejects_non_positive_price_and_negative_volume():
    with pytest.raises(ValueError):
        BookLevel(0.0, 1.0)
    with pytest.raises(ValueError):
        BookLevel(-1.0, 1.0)
    with pytest.raises(ValueError):
        BookLevel(1.0, -1.0)
