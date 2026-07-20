"""ATR rings and radar contact selection.

WHY ATR: percent means different things across instruments — 0.5% is a normal hour on SPY
and noise on TSLA. ATR normalises distance into "can price actually get there", which is
the only question the radar answers.

The ring thresholds are derived from meaning, not invented: within a tenth of a day's range
a level is effectively being touched; beyond three quarters of a day's range it cannot
matter today. Regime-change contacts outrank walls because crossing the flip changes what
every other level means.
"""

from __future__ import annotations

from terrain_atr import (
    RING_CLOSING,
    RING_CONTACT,
    RING_REGIME,
    RING_SECTOR,
    AtrPair,
    atr_distance,
    ring_for,
)


def test_rings_are_ordered_and_distinct() -> None:
    assert 0 < RING_CONTACT < RING_CLOSING < RING_SECTOR
    assert 0 < RING_REGIME < RING_CLOSING


def test_ring_classification_uses_atr_not_percent() -> None:
    """The same POINT gap lands in different rings on instruments with different ATR."""
    gap = 1.0
    assert ring_for(gap, 5.99) == "CLOSING"      # SPY-like: 1pt is 0.17 daily ATR
    assert ring_for(gap, 12.33) == "CONTACT"     # QQQ-like: 1pt is 0.08 daily ATR
    assert ring_for(gap, 0.60) is None           # tiny-ATR name: 1pt is 1.7 ATR, off-scope


def test_ring_boundaries() -> None:
    atr = 10.0
    assert ring_for(RING_CONTACT * atr, atr) == "CONTACT"
    assert ring_for(RING_CONTACT * atr + 0.01, atr) == "CLOSING"
    assert ring_for(RING_CLOSING * atr, atr) == "CLOSING"
    assert ring_for(RING_CLOSING * atr + 0.01, atr) == "SECTOR"
    assert ring_for(RING_SECTOR * atr, atr) == "SECTOR"
    assert ring_for(RING_SECTOR * atr + 0.01, atr) is None


def test_direction_does_not_change_the_ring() -> None:
    """Above or below, only the magnitude of the gap decides reachability."""
    assert ring_for(2.0, 10.0) == ring_for(-2.0, 10.0)
    assert atr_distance(2.0, 10.0) == atr_distance(-2.0, 10.0) == 0.2


def test_no_atr_means_no_ring_never_a_guess() -> None:
    """Without a scale, a distance in points is meaningless — the contact must not appear."""
    for bad in (None, 0, 0.0, -1.0):
        assert ring_for(5.0, bad) is None
        assert atr_distance(5.0, bad) is None
    assert ring_for(None, 10.0) is None
    assert atr_distance(None, 10.0) is None


def test_atr_pair_tolerates_missing_legs() -> None:
    p = AtrPair(daily=None, m15=1.5)
    assert p.daily is None and p.m15 == 1.5
    assert ring_for(1.0, p.daily) is None


def test_regime_ring_is_tighter_than_the_wall_contact_ring() -> None:
    """A flip is only a contact when it is genuinely imminent.

    RING_REGIME sits between CONTACT and CLOSING: tight enough that a flip does not
    permanently occupy the top of the scope, loose enough to warn before the crossing.
    """
    assert RING_CONTACT < RING_REGIME < RING_CLOSING
