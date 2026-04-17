import pytest

from canonical_distances import canonical_nearest_distances, canonicalize_distance_read


def test_both_levels_typical_geometry():
    nad, nbd = canonical_nearest_distances(100.0, 103.0, 97.0)
    assert nad == 3.0
    assert nbd == 3.0


def test_nearest_above_only():
    nad, nbd = canonical_nearest_distances(100.0, 101.5, None)
    assert nad == 1.5
    assert nbd is None


def test_nearest_below_only():
    nad, nbd = canonical_nearest_distances(100.0, None, 99.25)
    assert nad is None
    assert nbd == 0.75


def test_spot_none():
    assert canonical_nearest_distances(None, 101.0, 99.0) == (None, None)


def test_rounding_four_decimals():
    nad, nbd = canonical_nearest_distances(100.12345, 100.456781, 99.111119)
    assert nad == pytest.approx(0.3333)
    assert nbd == pytest.approx(1.0123)


def test_levels_already_canonical_still_correct():
    """abs() is idempotent for non-negative deltas when geometry is valid."""
    nad, nbd = canonical_nearest_distances(50.0, 55.0, 48.0)
    assert nad == 5.0
    assert nbd == 2.0


def test_canonicalize_distance_read_legacy_below():
    assert canonicalize_distance_read(2.5, -2.5) == (2.5, 2.5)


def test_canonicalize_distance_read_none_preserved():
    assert canonicalize_distance_read(None, -1.0) == (None, 1.0)
    assert canonicalize_distance_read(1.0, None) == (1.0, None)
