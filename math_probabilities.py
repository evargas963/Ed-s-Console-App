"""
math_probabilities.py
Mathematical probability, confidence, and scoring helpers.
Support-math layer for prediction and call engines.
"""

from __future__ import annotations

# ══════════════════════════════════════════════════════════════════════════════
# DERIVED FORMULA DICTIONARY — SECTION 8
# Predictive Positioning Signals
#
# Per spec: "Without Section 8 the system only produces levels. With Section 8
# the system produces decision signals required for automated trade scoring,
# probability modeling, entry logic, and exit logic."
#
# All signals normalized to 0–100 per spec implementation guidance.
# ══════════════════════════════════════════════════════════════════════════════


def compute_pin_score(
    gex_at_pin: float | None,
    oi_concentration: float | None,
) -> dict:
    """
    Pin Probability Score.

    Formula: PinScore = |GEX at strike| × OI concentration

    High pin score suggests price will settle near that strike.

    Args:
        gex_at_pin:       absolute GEX at the gamma pin strike
        oi_concentration: fraction of total OI at/near pin (0-1)

    Returns dict with raw_score, normalized (0-100), label.
    """
    if gex_at_pin is None or oi_concentration is None:
        return {"raw": None, "normalized": None, "label": "missing_oi"}

    gex = abs(gex_at_pin)
    oi_conc = max(0.0, min(1.0, oi_concentration))

    if gex <= 0 or oi_conc <= 0:
        return {"raw": 0.0, "normalized": 0.0, "label": "negligible"}

    # gex is DOLLAR GEX at the strike. Measured: the pin strike of every board ticker but three
    # carries far more than $50,000, so this term is 1 and the score is the OI share alone; the
    # three tiny option books (MTA $5,088, NBIX $33,028, TSL $965) are scaled down.
    # It acts as a small-book floor; whether $50,000 is the right floor is an open research item.
    gex_norm = min(1.0, gex / 50000.0)
    raw = gex_norm * oi_conc  # 0-1 range

    normalized = raw * 100.0

    if normalized >= 60:
        label = "high"
    elif normalized >= 30:
        label = "moderate"
    elif normalized >= 10:
        label = "low"
    else:
        label = "negligible"

    return {
        "raw": raw,
        "normalized": normalized,
        "label": label,
    }
