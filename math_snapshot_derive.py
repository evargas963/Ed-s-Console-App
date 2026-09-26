"""
Derived snapshot fields that must stay consistent with persisted OHLC/VWAP/IV.

Used by server (live inserts), snapshot_normalizer (1m buckets), and backfill.
"""
from __future__ import annotations

from typing import Any, Optional


def derive_vwap_side(spot: Any, vwap: Any) -> Optional[str]:
    """
    Match market_state semantics: above if spot > vwap, else below (includes spot == vwap).
    Returns None if either input missing or non-numeric.
    """
    if spot is None or vwap is None:
        return None
    try:
        s = float(spot)
        v = float(vwap)
    except (TypeError, ValueError):
        return None
    if s > v:
        return "above"
    return "below"


def derive_pressure_trend(
    prev_dpi_norm: Optional[float],
    cur_dpi_norm: Optional[float],
    *,
    eps: float = 2.0,
) -> Optional[str]:
    """
    Compare dealer-pressure index (0–100) to previous tick for the same ticker.
    """
    if cur_dpi_norm is None:
        return None
    try:
        cur = float(cur_dpi_norm)
    except (TypeError, ValueError):
        return None
    if prev_dpi_norm is None:
        return "flat"
    try:
        prev = float(prev_dpi_norm)
    except (TypeError, ValueError):
        return "flat"
    if cur > prev + eps:
        return "rising"
    if cur < prev - eps:
        return "falling"
    return "flat"
