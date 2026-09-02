"""
Canonical MVP field reads for regime / volatility scoring.

**Single source of truth:** callers must pass ``InferenceSnapshotV1["features"]`` (canonical MVP dict).
SignalInput is not read for structure / anchor / price MVP fields — no parallel interpretation.
"""

from __future__ import annotations

from typing import Any, Optional

from app.domain.canonical_distances import canonicalize_distance_read


class RegimeMvpInputError(ValueError):
    """Canonical MVP dict missing or invalid for regime / vol policy."""


def require_mvp_features(mvp_features: dict[str, Any] | None, *, context: str) -> dict[str, Any]:
    """Fail closed when production paths omit the canonical MVP row."""
    if not isinstance(mvp_features, dict):
        raise RegimeMvpInputError(f"{context}: mvp_features must be InferenceSnapshotV1['features'] dict")
    return mvp_features


def mvp_zone(mvp: dict[str, Any]) -> Optional[str]:
    """Canonical ``structure.zone`` or None when missing (no fabricated sentinel)."""
    v = mvp.get("structure.zone")
    if v is None:
        return None
    s = str(v).strip().lower()
    return s if s else None


def mvp_spot(mvp: dict[str, Any]) -> float | None:
    """Canonical ``price.spot`` only (no SignalInput)."""
    v = mvp.get("price.spot")
    if v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if f > 0 else None


def mvp_vwap_side(mvp: dict[str, Any]) -> Optional[str]:
    v = mvp.get("anchor.vwap_side")
    if v is None:
        return None
    s = str(v).strip().lower()
    return s if s in ("above", "below") else None


def mvp_nearest_distances_for_regime(mvp: dict[str, Any]) -> tuple[Any, Any]:
    return canonicalize_distance_read(
        mvp.get("structure.nearest_above_dist"),
        mvp.get("structure.nearest_below_dist"),
    )


def mvp_net_gamma(mvp: dict[str, Any]) -> float | None:
    v = mvp.get("structure.net_gamma")
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None
