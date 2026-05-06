"""Shared A1 raw probability helper."""

from __future__ import annotations

from typing import Any


def dominant_probability(ms_dict: dict[str, Any]) -> float | None:
    """Return the dominant A1 raw probability from ms_dict, or None.

    Public surface for the v2 isotonic calibration runtime to consume.
    Behavior is byte-equivalent to the prior private _dominant_probability
    in v2_decision.module_a_adapter.
    """
    candidates = (
        ms_dict.get("fusion_dominant_prob") if ms_dict.get("fusion_available") else None,
        ms_dict.get("dominant_prob"),
        ms_dict.get("final_confidence"),
    )
    for value in candidates:
        try:
            if value is not None:
                return round(float(value), 4)
        except (TypeError, ValueError):
            continue
    return None
