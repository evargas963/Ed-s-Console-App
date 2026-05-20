"""Shared numeric parsing and directional triplet policy (COH-SA TIER-1.5)."""

from __future__ import annotations

import math
from typing import Any, Literal

DirectionLabel = Literal["up", "down", "flat"]

_TRIPLET_LABELS: tuple[DirectionLabel, ...] = ("up", "down", "flat")


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


def float_or_none(value: Any) -> float | None:
    """Backward-compatible alias for finite-or-none parsing."""
    return float_finite_or_none(value)


def direction_from_triplet(
    up: Any,
    down: Any,
    flat: Any,
    *,
    parse: Any = float_finite_or_none,
) -> DirectionLabel | None:
    """
    Argmax over present finite triplet legs.

    Tie-break (stable): up, then down, then flat — matches legacy
    ``max("up", "down", "flat", key=...)`` and ``max(present.items(), ...)``
    insertion order.
    """
    present: list[tuple[DirectionLabel, float]] = []
    for lab in _TRIPLET_LABELS:
        v = parse(up if lab == "up" else down if lab == "down" else flat)
        if v is not None:
            present.append((lab, v))
    if not present:
        return None
    return max(present, key=lambda kv: kv[1])[0]


def direction_from_normalized_triplet(
    up: float,
    down: float,
    flat: float,
) -> DirectionLabel:
    """Argmax on already-finite normalized probabilities (no parsing)."""
    return max(_TRIPLET_LABELS, key=lambda lab: {"up": up, "down": down, "flat": flat}[lab])
