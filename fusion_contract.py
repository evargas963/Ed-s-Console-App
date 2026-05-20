"""Fusion payload and canonical tradability contracts (COH-SA fusion-predicates)."""

from __future__ import annotations

from typing import Any

from signal_types import TRADABLE_CANONICAL_PROVENANCE


def fusion_is_authoritative(fusion: Any) -> bool:
    """True when fusion exists and reports ``available=True`` (authoritative posterior)."""
    if fusion is None:
        return False
    return bool(getattr(fusion, "available", False))


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
    """True when Tier C ``ms_dict`` fusion fields are safe to read (available + tradable provenance)."""
    if not ms.get("fusion_available"):
        return False
    prov = ms.get("canonical_provenance")
    return canonical_provenance_is_tradable(str(prov or ""))
