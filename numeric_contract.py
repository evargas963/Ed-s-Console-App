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


def float_nonnegative_or_none(value: Any) -> float | None:
    """Parse float; require finite value >= 0 (zero is valid). Canonical read for
    non-negative vendor quantities like totalVolume/size, where 0 is a real count
    but negatives and non-finite are corruption to be dropped."""
    v = float_finite_or_none(value)
    return v if v is not None and v >= 0.0 else None


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
    up: Any,
    down: Any,
    flat: Any,
) -> DirectionLabel | None:
    """Argmax on already-finite normalized probabilities (no parsing).

    Defensive single-producer (RC-363): returns ``None`` (WITHHELD) when any leg
    is ``None`` or non-finite (NaN / ±inf / non-numeric), instead of raising
    ``TypeError`` inside ``max()`` or emitting an order-dependent garbage label
    (NaN comparisons are all False). Callers treat ``None`` as "withhold this
    observation" — the same skip-the-row policy the finite-guarded producers
    already apply.
    """
    for v in (up, down, flat):
        try:
            if v is None or not math.isfinite(v):
                return None
        except (TypeError, ValueError):
            return None
    return max(_TRIPLET_LABELS, key=lambda lab: {"up": up, "down": down, "flat": flat}[lab])

