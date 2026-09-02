"""Compatibility shim — the canonical owner is `app.domain.canonical_distances` (RC-505).

No logic here. New code must import from `app.domain.canonical_distances`; this file dies
when nothing imports it.
"""
from __future__ import annotations

from app.domain.canonical_distances import (
    NEAREST_DIST_ROUND_DECIMALS,
    canonical_nearest_distances,
    canonicalize_distance_read,
)

__all__ = [
    "NEAREST_DIST_ROUND_DECIMALS",
    "canonical_nearest_distances",
    "canonicalize_distance_read",
]
