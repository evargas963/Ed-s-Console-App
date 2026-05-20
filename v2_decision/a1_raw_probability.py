"""Shared A1 raw probability helper."""

from __future__ import annotations

from typing import Any

from fusion_contract import canonical_provenance_is_tradable
from numeric_contract import float_finite_or_none


def _probability_candidate(value: Any) -> float | None:
    x = float_finite_or_none(value)
    if x is None or x < 0.0 or x > 1.0:
        return None
    return round(x, 4)


def _fusion_prob_authoritative(ms_dict: dict[str, Any]) -> bool:
    if not ms_dict.get("fusion_available"):
        return False
    prov = ms_dict.get("canonical_provenance")
    if prov is None:
        return True
    return canonical_provenance_is_tradable(str(prov))


def dominant_probability(ms_dict: dict[str, Any]) -> float | None:
    """Return the dominant A1 raw probability from ms_dict, or None.

    Public surface for the v2 isotonic calibration runtime to consume.
    Behavior is byte-equivalent to the prior private _dominant_probability
    in v2_decision.module_a_adapter.
    """
    candidates = (
        ms_dict.get("fusion_dominant_prob") if _fusion_prob_authoritative(ms_dict) else None,
        ms_dict.get("dominant_prob"),
        ms_dict.get("final_confidence"),
    )
    for value in candidates:
        prob = _probability_candidate(value)
        if prob is not None:
            return prob
    return None
