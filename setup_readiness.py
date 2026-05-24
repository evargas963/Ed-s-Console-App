from __future__ import annotations

from typing import Any, List


def _clamp(value: float, low: float = 0.0, high: float = 100.0) -> int:
    return int(max(low, min(high, round(value))))


def _safe_lower(value: Any) -> str:
    return str(value or "").strip().lower()


# ═══════════════════════════════════════════════════════════════════════════════
# READINESS STRUCTURE INPUT ARCHITECTURE (by role, not timeframe name)
# ═══════════════════════════════════════════════════════════════════════════════
# Execution timing:  not in structure inputs — readiness uses narrative reads only.
# Structure confirmation: ~15m structural read (prediction_engine reads["15m"])
# Higher-timeframe bias:   ~60m trend read     (prediction_engine reads["60m"])
#
# Data flow: pred.timeframe_reads["15m"]  → structure_confirmation
#            pred.timeframe_reads["60m"]  → structure_higher_tf
# Call site: call_engine.py passes _tf.get("15m") and _tf.get("60m").
# NOTE: No 5m in readiness structure inputs. 15m and 60m are conceptual horizons.
# ═══════════════════════════════════════════════════════════════════════════════


def compute_call_readiness(call_input: dict) -> dict:
    """
    V1 deterministic readiness model for the CALL card.

    Expected input keys (use what you already have; missing keys are handled):
        regime
        trend
        structure_confirmation   # ~15m structure read (role: structure confirmation)
        structure_higher_tf     # ~60m trend read (role: higher-timeframe bias)
        prediction_direction
        prediction_dominant_prob
        confluence_read
        validation_passed
        level_proximity
        near_support
        breakout_ready

    Returns:
        {
            "call_state": "WAIT" | "WATCH" | "ACTIVE",
            "forecast_state": "dormant" | "forming" | "near_trigger" | "active" | "invalidated",
            "readiness_score": int,
            "reasons": [str, ...],
            "missing_conditions": [str, ...],
            "component_scores": {...}
        }
    """

    regime = _safe_lower(call_input.get("regime"))
    trend = _safe_lower(call_input.get("trend"))
    structure_confirmation = _safe_lower(call_input.get("structure_confirmation", ""))
    structure_higher_tf = _safe_lower(call_input.get("structure_higher_tf", ""))
    prediction_direction = _safe_lower(call_input.get("prediction_direction"))
    confluence_read = _safe_lower(call_input.get("confluence_read"))
    level_proximity = _safe_lower(call_input.get("level_proximity"))

    prob_raw = call_input.get("prediction_dominant_prob", 0.0)
    try:
        prob = float(prob_raw or 0.0)
    except (TypeError, ValueError):
        prob = 0.0

    validation_passed = bool(call_input.get("validation_passed", False))
    near_support = bool(call_input.get("near_support", False))
    breakout_ready = bool(call_input.get("breakout_ready", False))

    reasons: List[str] = []
    missing: List[str] = []

    # -----------------------------
    # 1) Trend / regime score (20)
    # -----------------------------
    trend_score = 0.0
    bullish_regime = any(x in regime for x in ["bull", "trend", "up"])
    bullish_trend = any(x in trend for x in ["bull", "up", "higher", "intact"])

    if bullish_regime and bullish_trend:
        trend_score = 20
        reasons.append("Higher timeframe trend/regime supports CALLs.")
    elif bullish_regime or bullish_trend:
        trend_score = 12
        reasons.append("Trend context is somewhat supportive.")
        missing.append("Need stronger bullish regime/trend alignment.")
    else:
        trend_score = 4
        missing.append("Trend/regime is not clearly bullish.")

    # -----------------------------
    # 2) Structure score (20)
    # -----------------------------
    # structure_confirmation = ~15m read, structure_higher_tf = ~60m read (role-based, not timeframe names)
    structure_score = 0.0
    structure_text = f"{structure_confirmation} {structure_higher_tf}"

    if any(x in structure_text for x in ["higher low", "reclaim", "breakout confirmed", "confirmed"]):
        structure_score = 20
        reasons.append("Structure confirmation is present.")
    elif any(x in structure_text for x in ["bull flag", "forming", "pullback", "uptrend intact"]):
        structure_score = 12
        reasons.append("Bullish structure is forming.")
        missing.append("Need structure confirmation or a higher low/reclaim.")
    elif any(x in structure_text for x in ["bear", "choch_bear", "breakdown"]):
        structure_score = 2
        missing.append("Structure is conflicting or bearish.")
    else:
        structure_score = 5
        missing.append("No clean structure trigger yet.")

    # -----------------------------
    # 3) Level proximity score (20)
    # -----------------------------
    level_score = 0.0

    if breakout_ready:
        level_score = 20
        reasons.append("Price is at an actionable breakout/trigger area.")
    elif near_support or level_proximity in {"near", "support", "trigger_zone"}:
        level_score = 15
        reasons.append("Price is near a relevant support/trigger area.")
    elif level_proximity in {"mid", "mid_range", "far"}:
        level_score = 5
        missing.append("Price is not yet at a strong action level.")
    else:
        level_score = 8
        missing.append("Need better proximity to a trigger level.")

    # -----------------------------
    # 4) Probability score (15)
    # -----------------------------
    prob_score = 0.0

    if prediction_direction == "up":
        if prob >= 0.60:
            prob_score = 15
            reasons.append(f"Dominant probability is strong ({prob:.2%}).")
        elif prob >= 0.56:
            prob_score = 11
            reasons.append(f"Dominant probability is acceptable ({prob:.2%}).")
        elif prob >= 0.52:
            prob_score = 7
            missing.append(f"Need stronger probability; current {prob:.2%}.")
        else:
            prob_score = 3
            missing.append(f"Probability is too weak for a CALL; current {prob:.2%}.")
    else:
        prob_score = 1
        missing.append("Prediction direction is not bullish.")

    # -----------------------------
    # 5) Confluence score (15)
    # -----------------------------
    confluence_score = 0.0

    # Avoid treating "no … alignment" / "none aligned" as positive (substring "aligned").
    _cr = confluence_read
    _has_aligned_kw = "aligned" in _cr and "none aligned" not in _cr and "no directional alignment" not in _cr and "no stack alignment" not in _cr
    if any(x in _cr for x in ["strong", "bullish", "clear directional"]) or _has_aligned_kw:
        confluence_score = 15
        reasons.append("Confluence is supportive.")
    elif any(x in _cr for x in ["mixed", "neutral"]):
        confluence_score = 7
        missing.append("Need stronger directional confluence.")
    else:
        confluence_score = 5
        missing.append("Confluence is not clearly supportive.")

    # -----------------------------
    # 6) Validation score (10)
    # -----------------------------
    validation_score = 0.0

    if validation_passed:
        validation_score = 10
        reasons.append("Validation checks passed.")
    else:
        validation_score = 0
        missing.append("Validation has not passed.")

    total_score = _clamp(
        trend_score
        + structure_score
        + level_score
        + prob_score
        + confluence_score
        + validation_score
    )

    # Call state
    if total_score >= 80:
        call_state = "ACTIVE"
    elif total_score >= 50:
        call_state = "WATCH"
    else:
        call_state = "WAIT"

    # Forecast state
    if call_state == "ACTIVE":
        forecast_state = "active"
    elif total_score >= 65:
        forecast_state = "near_trigger"
    elif total_score >= 40:
        forecast_state = "forming"
    else:
        forecast_state = "dormant"

    return {
        "call_state": call_state,
        "forecast_state": forecast_state,
        "readiness_score": total_score,
        "reasons": reasons,
        "missing_conditions": missing,
        "component_scores": {
            "trend_score": _clamp(trend_score, 0, 20),
            "structure_score": _clamp(structure_score, 0, 20),
            "level_score": _clamp(level_score, 0, 20),
            "probability_score": _clamp(prob_score, 0, 15),
            "confluence_score": _clamp(confluence_score, 0, 15),
            "validation_score": _clamp(validation_score, 0, 10),
        },
    }


def compute_put_readiness(put_input: dict) -> dict:
    """
    V1 deterministic readiness model for the PUT card.
    Bearish mirror of compute_call_readiness.
    """
    regime = _safe_lower(put_input.get("regime"))
    trend = _safe_lower(put_input.get("trend"))
    structure_confirmation = _safe_lower(put_input.get("structure_confirmation", ""))
    structure_higher_tf = _safe_lower(put_input.get("structure_higher_tf", ""))
    prediction_direction = _safe_lower(put_input.get("prediction_direction"))
    confluence_read = _safe_lower(put_input.get("confluence_read"))
    level_proximity = _safe_lower(put_input.get("level_proximity"))

    prob_raw = put_input.get("prediction_dominant_prob", 0.0)
    try:
        prob = float(prob_raw or 0.0)
    except (TypeError, ValueError):
        prob = 0.0

    validation_passed = bool(put_input.get("validation_passed", False))
    near_resistance = bool(put_input.get("near_resistance", put_input.get("near_support", False)))
    breakdown_ready = bool(put_input.get("breakdown_ready", put_input.get("breakout_ready", False)))

    reasons: List[str] = []
    missing: List[str] = []

    # 1) Trend / regime (bearish)
    trend_score = 0.0
    bearish_regime = any(x in regime for x in ["bear", "trend", "down", "breakdown"])
    bearish_trend = any(x in trend for x in ["bear", "down", "lower", "breakdown", "intact"])

    if bearish_regime and bearish_trend:
        trend_score = 20
        reasons.append("Higher timeframe trend/regime supports PUTs.")
    elif bearish_regime or bearish_trend:
        trend_score = 12
        reasons.append("Trend context is somewhat supportive.")
        missing.append("Need stronger bearish regime/trend alignment.")
    else:
        trend_score = 4
        missing.append("Trend/regime is not clearly bearish.")

    # 2) Structure (bearish) — structure_confirmation=~15m, structure_higher_tf=~60m
    structure_score = 0.0
    structure_text = f"{structure_confirmation} {structure_higher_tf}"

    if any(x in structure_text for x in ["lower high", "breakdown confirmed", "confirmed"]):
        structure_score = 20
        reasons.append("Structure confirmation is present.")
    elif any(x in structure_text for x in ["bear flag", "forming", "pullback", "downtrend intact"]):
        structure_score = 12
        reasons.append("Bearish structure is forming.")
        missing.append("Need structure confirmation or a lower high.")
    elif any(x in structure_text for x in ["bull", "choch_bull", "breakout"]):
        structure_score = 2
        missing.append("Structure is conflicting or bullish.")
    else:
        structure_score = 5
        missing.append("No clean structure trigger yet.")

    # 3) Level proximity (resistance for puts)
    level_score = 0.0
    if breakdown_ready:
        level_score = 20
        reasons.append("Price is at an actionable breakdown/trigger area.")
    elif near_resistance or level_proximity in {"near", "resistance", "trigger_zone"}:
        level_score = 15
        reasons.append("Price is near a relevant resistance/trigger area.")
    elif level_proximity in {"mid", "mid_range", "far"}:
        level_score = 5
        missing.append("Price is not yet at a strong action level.")
    else:
        level_score = 8
        missing.append("Need better proximity to a trigger level.")

    # 4) Probability (bearish)
    prob_score = 0.0
    if prediction_direction == "down":
        if prob >= 0.60:
            prob_score = 15
            reasons.append(f"Dominant probability is strong ({prob:.2%}).")
        elif prob >= 0.56:
            prob_score = 11
            reasons.append(f"Dominant probability is acceptable ({prob:.2%}).")
        elif prob >= 0.52:
            prob_score = 7
            missing.append(f"Need stronger probability; current {prob:.2%}.")
        else:
            prob_score = 3
            missing.append(f"Probability is too weak for a PUT; current {prob:.2%}.")
    else:
        prob_score = 1
        missing.append("Prediction direction is not bearish.")

    # 5) Confluence (same "aligned" substring guard as call side)
    confluence_score = 0.0
    _pcr = confluence_read
    _phas_aligned_kw = "aligned" in _pcr and "none aligned" not in _pcr and "no directional alignment" not in _pcr and "no stack alignment" not in _pcr
    if any(x in _pcr for x in ["strong", "bearish", "clear directional"]) or _phas_aligned_kw:
        confluence_score = 15
        reasons.append("Confluence is supportive.")
    elif any(x in _pcr for x in ["mixed", "neutral"]):
        confluence_score = 7
        missing.append("Need stronger directional confluence.")
    else:
        confluence_score = 5
        missing.append("Confluence is not clearly supportive.")

    # 6) Validation
    validation_score = 10.0 if validation_passed else 0.0
    if validation_passed:
        reasons.append("Validation checks passed.")
    else:
        missing.append("Validation has not passed.")

    total_score = _clamp(
        trend_score + structure_score + level_score +
        prob_score + confluence_score + validation_score
    )

    call_state = "ACTIVE" if total_score >= 80 else "WATCH" if total_score >= 50 else "WAIT"
    forecast_state = "active" if call_state == "ACTIVE" else ("near_trigger" if total_score >= 65 else ("forming" if total_score >= 40 else "dormant"))

    return {
        "call_state": call_state,
        "forecast_state": forecast_state,
        "readiness_score": total_score,
        "reasons": reasons,
        "missing_conditions": missing,
        "component_scores": {
            "trend_score": _clamp(trend_score, 0, 20),
            "structure_score": _clamp(structure_score, 0, 20),
            "level_score": _clamp(level_score, 0, 20),
            "probability_score": _clamp(prob_score, 0, 15),
            "confluence_score": _clamp(confluence_score, 0, 15),
            "validation_score": _clamp(validation_score, 0, 10),
        },
    }


if __name__ == "__main__":
    sample = {
        "regime": "bull trend",
        "trend": "uptrend intact",
        "structure_confirmation": "bull flag forming",
        "structure_higher_tf": "uptrend intact",
        "prediction_direction": "up",
        "prediction_dominant_prob": 0.55,
        "confluence_read": "mixed",
        "validation_passed": False,
        "level_proximity": "near",
        "near_support": True,
        "breakout_ready": False,
    }

    out = compute_call_readiness(sample)
    from pprint import pprint
    pprint(out)
