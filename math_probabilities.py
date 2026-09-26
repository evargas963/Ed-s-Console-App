"""
math_probabilities.py
Mathematical probability, confidence, and scoring helpers.
Support-math layer for prediction and call engines.

Phase 2 extraction from math_exposure.py per Extraction Blueprint v1.
"""
from __future__ import annotations




# ── Constants ─────────────────────────────────────────────────────────────────









# ── OE scoring ───────────────────────────────────────────────────────────────












# ── Direction classification ─────────────────────────────────────────────────



def classify_direction_pts(pts_move: float, threshold_pts: float | None) -> str:
    """3-class direction from a precomputed per-horizon move threshold (in points).

    Sibling of ``classify_direction`` with identical comparison shape, but the
    move threshold is supplied directly in price points (e.g. the per-horizon,
    ATR-scaled ``threshold_move_pts_for_slug`` value) instead of being derived
    from ``spot * threshold_pct``. Used for horizon outcome labels so each
    horizon is balanced on its own volatility scale rather than a single fixed
    0.05%-of-spot cut applied uniformly to 1c…60c.

    Fail-closed: a non-positive or missing ``threshold_pts`` yields ``"flat"`` —
    no directional claim is made without a valid volatility scale.
    """
    if threshold_pts is None or threshold_pts <= 0:
        return "flat"
    if pts_move > threshold_pts:
        return "up"
    if pts_move < -threshold_pts:
        return "down"
    return "flat"


# ── Distance bucketing ──────────────────────────────────────────────────────







# ── Probability computation ─────────────────────────────────────────────────





# ── Confidence determination ─────────────────────────────────────────────────





# ── Percentile / range helpers ───────────────────────────────────────────────





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

    # Normalize GEX to 0-1 range (empirical: top pin GEX ~50000 for SPY)
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
        "raw": round(raw, 6),
        "normalized": round(normalized, 1),
        "label": label,
    }







# ── Option Flow Signals (from Schwab bid/ask size + volume) ──────────────────













