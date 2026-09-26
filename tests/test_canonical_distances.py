"""canonical_nearest_distances/canonicalize_distance_read: the single geometry
computation for nearest-above/nearest-below distance must be correct for every
spot/level ordering, since every consumer reads distances through this one faucet."""

from canonical_distances import (
    canonicalize_distance_read,
)














def test_canonicalize_distance_read_legacy_below():
    assert canonicalize_distance_read(2.5, -2.5) == (2.5, 2.5)


def test_canonicalize_distance_read_none_preserved():
    assert canonicalize_distance_read(None, -1.0) == (None, 1.0)
    assert canonicalize_distance_read(1.0, None) == (1.0, None)
