"""Shared A1 raw probability helper."""

from __future__ import annotations

from typing import Any

from fusion_contract import is_ms_dict_fusion_authoritative
from app.domain.numeric_contract import float_finite_or_none


def _probability_candidate(value: Any) -> float | None:
    x = float_finite_or_none(value)
    if x is None or x < 0.0 or x > 1.0:
        return None
    return round(x, 4)


def dominant_probability(ms_dict: dict[str, Any]) -> float | None:
    """Return the dominant A1 raw probability from ms_dict, or None.

    Public surface for the v2 isotonic calibration runtime to consume.
    Uses fusion_dominant_prob when fusion is authoritative, else dominant_prob.
    Does not use final_confidence (desk aggregate; separate v2 confidence leaf).
    """
    candidates = (
        ms_dict.get("fusion_dominant_prob") if is_ms_dict_fusion_authoritative(ms_dict) else None,
        ms_dict.get("dominant_prob"),
    )
    for value in candidates:
        prob = _probability_candidate(value)
        if prob is not None:
            return prob
    return None
