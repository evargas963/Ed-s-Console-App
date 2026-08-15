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
    up: float,
    down: float,
    flat: float,
) -> DirectionLabel:
    """Argmax on already-finite normalized probabilities (no parsing)."""
    return max(_TRIPLET_LABELS, key=lambda lab: {"up": up, "down": down, "flat": flat}[lab])


def direction_from_model_output(out: Any) -> DirectionLabel | None:
    """
    Stack display direction: prefer model ``dominant_class`` / ``dominant_dir`` when valid;
    else argmax ``prob_up`` / ``prob_down`` / ``prob_flat`` via ``direction_from_triplet``.
    """
    dom_raw = getattr(out, "dominant_class", None) or getattr(out, "dominant_dir", None)
    if dom_raw is not None:
        dom = str(dom_raw).strip().lower()
        if dom in _TRIPLET_LABELS:
            return dom  # type: ignore[return-value]
    return direction_from_triplet(
        getattr(out, "prob_up", None),
        getattr(out, "prob_down", None),
        getattr(out, "prob_flat", None),
    )
