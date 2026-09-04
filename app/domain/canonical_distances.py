"""Canonical nearest above/below distances for snapshots and live state (Option A).

Both stored distances are non-negative magnitudes; direction is implied by field name
(nearest_above_* vs nearest_below_*), not by sign.
"""
from __future__ import annotations

from typing import Optional, Tuple

NEAREST_DIST_ROUND_DECIMALS = 4


def canonical_nearest_distances(
    spot: Optional[float],
    nearest_above_level: Optional[float],
    nearest_below_level: Optional[float],
) -> Tuple[Optional[float], Optional[float]]:
    """
    Return (nearest_above_dist, nearest_below_dist) as rounded non-negative magnitudes.

    If spot is None, both distances are None. A missing chosen level yields None for
    that side only.
    """
    r = NEAREST_DIST_ROUND_DECIMALS
    if spot is None:
        return None, None
    spot_f = float(spot)
    nad: Optional[float] = None
    if nearest_above_level is not None:
        nad = round(abs(float(nearest_above_level) - spot_f), r)
    nbd: Optional[float] = None
    if nearest_below_level is not None:
        nbd = round(abs(spot_f - float(nearest_below_level)), r)
    return nad, nbd


def canonicalize_distance_read(
    nearest_above_dist: Optional[float],
    nearest_below_dist: Optional[float],
) -> Tuple[Optional[float], Optional[float]]:
    """
    Normalize stored or streamed distances to Option A magnitudes for consumers.

    Legacy rows may store nearest_below_dist < 0; new rows use non-negative magnitudes
    for both columns. Direction is implied by field names, not sign.

    Returns (nad, nbd) with each side independently set to abs(value) when not None.
    """
    nad: Optional[float] = None
    if nearest_above_dist is not None:
        nad = abs(float(nearest_above_dist))
    nbd: Optional[float] = None
    if nearest_below_dist is not None:
        nbd = abs(float(nearest_below_dist))
    return nad, nbd
