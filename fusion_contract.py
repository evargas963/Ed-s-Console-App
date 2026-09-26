"""Fusion payload and canonical tradability contracts (COH-SA fusion-predicates)."""

from __future__ import annotations

import math
from typing import Any

from signal_types import TRADABLE_CANONICAL_PROVENANCE


def fusion_is_authoritative(fusion: Any) -> bool:
    """True when fusion exists and reports ``available=True`` (setup-family posterior ran)."""
    if fusion is None:
        return False
    return bool(getattr(fusion, "available", False))


def fusion_direction_is_authorized(fusion: Any) -> bool:
    """Consume the producer's directional-authorization verdict without reconstructing it."""
    return bool(
        fusion_is_authoritative(fusion)
        and getattr(fusion, "stack_directional_authorized", None) is True
    )


def fusion_has_tradable_direction(fusion: Any) -> bool:
    """True when fusion carries a complete ML directional triplet safe for horizon cards / canonical."""
    if not fusion_direction_is_authorized(fusion):
        return False
    values: list[float] = []
    for key in ("prob_up", "prob_down", "prob_flat"):
        try:
            value = float(getattr(fusion, key, None))
        except (TypeError, ValueError):
            return False
        if not math.isfinite(value) or value < 0.0 or value > 1.0:
            return False
        values.append(value)
    return sum(values) > 0.0


def canonical_provenance_is_tradable(provenance: str | None) -> bool:
    """True only for explicitly known-tradable provenance (fail-closed allow-list, FIND-FP1-3)."""
    return (provenance or "") in TRADABLE_CANONICAL_PROVENANCE


def is_canonical_tradable(canonical: Any) -> bool:
    """True when a CanonicalForecast (or duck-type) is safe for tradable directional mass."""
    if canonical is None:
        return False
    prov = getattr(canonical, "provenance", None)
    if prov is None and isinstance(canonical, dict):
        prov = canonical.get("provenance")
    return canonical_provenance_is_tradable(str(prov or ""))


def is_ms_dict_fusion_authoritative(ms: dict[str, Any]) -> bool:
    """True when Tier C carries the producer verdict plus tradable canonical provenance."""
    if not ms.get("fusion_available"):
        return False
    if ms.get("stack_directional_authorized") is not True:
        return False
    prov = ms.get("canonical_provenance")
    return canonical_provenance_is_tradable(str(prov or ""))
