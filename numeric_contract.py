"""Shared numeric parsing and directional triplet policy (COH-SA TIER-1.5)."""

from __future__ import annotations

import math
from typing import (
    Any,
)




def float_finite_or_none(value: Any) -> float | None:
    """Parse float; reject None, non-numeric, NaN, and ±inf."""
    if value is None or value == "":
        return None
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


def float_positive_or_none(value: Any) -> float | None:
    """Parse float; require finite value strictly greater than zero."""
    v = float_finite_or_none(value)
    return v if v is not None and v > 0.0 else None


def float_nonnegative_or_none(value: Any) -> float | None:
    """Parse float; require finite value >= 0 (zero is valid). Canonical read for
    non-negative vendor quantities like totalVolume/size, where 0 is a real count
    but negatives and non-finite are corruption to be dropped."""
    v = float_finite_or_none(value)
    return v if v is not None and v >= 0.0 else None







