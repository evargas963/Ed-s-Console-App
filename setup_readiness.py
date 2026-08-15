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

# ═══════════════════════════════════════════════════════════════════════════════
# RC-338 — THE ONE READINESS SCORING POLICY
# ═══════════════════════════════════════════════════════════════════════════════
# Until 2026-08-10 this policy was written TWICE: compute_call_readiness and
# compute_put_readiness each carried their own copy of every point table, the
# probability bands (0.60 / 0.56 / 0.52), the state thresholds (80 / 50) and the
# forecast thresholds (65 / 40). Neither delegated to the other; both called only
# _clamp/_safe_lower. The numbers agreed by coincidence of authorship, and a change
# to one side would silently diverge the CALL and PUT chips the operator reads
# side by side. What is side-specific is the CLASSIFICATION of inputs into tiers
# (bullish vs bearish keyword sets, support vs resistance keys, "up" vs "down")
# and the operator-facing wording. The scoring policy itself is one semantic
# concept, so it now has exactly one computation authority: score_readiness().
READINESS_TREND_POINTS = {"aligned": 20, "partial": 12, "weak": 4}
READINESS_STRUCTURE_POINTS = {"confirmed": 20, "forming": 12, "conflicting": 2, "none": 5}
READINESS_LEVEL_POINTS = {"trigger": 20, "near": 15, "far": 5, "unknown": 8}
READINESS_PROB_BANDS = ((0.60, 15, "strong"), (0.56, 11, "acceptable"), (0.52, 7, "needs_more"))
READINESS_PROB_WEAK_POINTS = 3
READINESS_PROB_WRONG_DIRECTION_POINTS = 1
READINESS_CONFLUENCE_POINTS = {"supportive": 15, "mixed": 7, "weak": 5}
READINESS_VALIDATION_POINTS = 10
READINESS_ACTIVE_MIN = 80
READINESS_WATCH_MIN = 50
READINESS_NEAR_TRIGGER_MIN = 65
READINESS_FORMING_MIN = 40


def score_readiness(
    *,
    trend_tier: str,
    structure_tier: str,
    level_tier: str,
    direction_matches: bool,
    prob: float,
    confluence_tier: str,
    validation_passed: bool,
) -> dict:
    """THE readiness scoring authority — every number and mapping lives here, once.

    The side functions classify their inputs into tiers (that classification is the
    genuinely side-specific concept) and consume this. They may not re-encode any
    point value, band, or threshold; the retained structural test rejects a side
    function whose body carries scoring literals or state strings.

    Returns the readiness result dict plus ``prob_band`` (the band label the sides
    use to pick their wording; they pop it before returning).
    """
    trend_score = READINESS_TREND_POINTS[trend_tier]
    structure_score = READINESS_STRUCTURE_POINTS[structure_tier]
    level_score = READINESS_LEVEL_POINTS[level_tier]

    if direction_matches:
        for floor, points, band in READINESS_PROB_BANDS:
            if prob >= floor:
                prob_score, prob_band = points, band
                break
        else:
            prob_score, prob_band = READINESS_PROB_WEAK_POINTS, "weak"
    else:
        prob_score, prob_band = READINESS_PROB_WRONG_DIRECTION_POINTS, "wrong_direction"

    confluence_score = READINESS_CONFLUENCE_POINTS[confluence_tier]
    validation_score = READINESS_VALIDATION_POINTS if validation_passed else 0

    total_score = _clamp(
        trend_score
        + structure_score
        + level_score
        + prob_score
        + confluence_score
        + validation_score
    )

    if total_score >= READINESS_ACTIVE_MIN:
        call_state = "ACTIVE"
    elif total_score >= READINESS_WATCH_MIN:
        call_state = "WATCH"
    else:
        call_state = "WAIT"

    if call_state == "ACTIVE":
        forecast_state = "active"
    elif total_score >= READINESS_NEAR_TRIGGER_MIN:
        forecast_state = "near_trigger"
    elif total_score >= READINESS_FORMING_MIN:
        forecast_state = "forming"
    else:
        forecast_state = "dormant"

    return {
        "call_state": call_state,
        "forecast_state": forecast_state,
        "readiness_score": total_score,
        "prob_band": prob_band,
        "component_scores": {
            "trend_score": _clamp(trend_score, 0, 20),
            "structure_score": _clamp(structure_score, 0, 20),
            "level_score": _clamp(level_score, 0, 20),
            "probability_score": _clamp(prob_score, 0, 15),
            "confluence_score": _clamp(confluence_score, 0, 15),
            "validation_score": _clamp(validation_score, 0, 10),
        },
    }


def _prob_float(raw: Any) -> float:
    try:
        return float(raw or 0.0)
    except (TypeError, ValueError):
        return 0.0  # absence-ok: readiness scores an unreadable probability as 0.0 BY DESIGN — it lands in the weakest band (3 points, "too weak"), i.e. no probabilistic support, the fail-closed reading; identical semantics to the pre-RC-338 inline handlers


def _confluence_tier(confluence_read: str, directional_keyword: str) -> str:
    """Shared confluence classification; only the directional keyword differs by side.

    Avoid treating "no … alignment" / "none aligned" as positive (substring "aligned").
    """
    cr = confluence_read
    has_aligned_kw = (
        "aligned" in cr
        and "none aligned" not in cr
        and "no directional alignment" not in cr
        and "no stack alignment" not in cr
    )
    if any(x in cr for x in ["strong", directional_keyword, "clear directional"]) or has_aligned_kw:
        return "supportive"
    if any(x in cr for x in ["mixed", "neutral"]):
        return "mixed"
    return "weak"


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

    Classification (bullish keywords) and wording live here; every score, band and
    threshold comes from score_readiness — the one policy authority (RC-338).
    """
    regime = _safe_lower(call_input.get("regime"))
    trend = _safe_lower(call_input.get("trend"))
    structure_confirmation = _safe_lower(call_input.get("structure_confirmation", ""))
    structure_higher_tf = _safe_lower(call_input.get("structure_higher_tf", ""))
    prediction_direction = _safe_lower(call_input.get("prediction_direction"))
    confluence_read = _safe_lower(call_input.get("confluence_read"))
    level_proximity = _safe_lower(call_input.get("level_proximity"))
    prob = _prob_float(call_input.get("prediction_dominant_prob", 0.0))
    validation_passed = bool(call_input.get("validation_passed", False))
    near_support = bool(call_input.get("near_support", False))
    breakout_ready = bool(call_input.get("breakout_ready", False))

    reasons: List[str] = []
    missing: List[str] = []

    # 1) Trend / regime tier (bullish keywords — side-specific classification)
    bullish_regime = any(x in regime for x in ["bull", "trend", "up"])
    bullish_trend = any(x in trend for x in ["bull", "up", "higher", "intact"])
    if bullish_regime and bullish_trend:
        trend_tier = "aligned"
        reasons.append("Higher timeframe trend/regime supports CALLs.")
    elif bullish_regime or bullish_trend:
        trend_tier = "partial"
        reasons.append("Trend context is somewhat supportive.")
        missing.append("Need stronger bullish regime/trend alignment.")
    else:
        trend_tier = "weak"
        missing.append("Trend/regime is not clearly bullish.")

    # 2) Structure tier (structure_confirmation=~15m, structure_higher_tf=~60m)
    structure_text = f"{structure_confirmation} {structure_higher_tf}"
    if any(x in structure_text for x in ["higher low", "reclaim", "breakout confirmed", "confirmed"]):
        structure_tier = "confirmed"
        reasons.append("Structure confirmation is present.")
    elif any(x in structure_text for x in ["bull flag", "forming", "pullback", "uptrend intact"]):
        structure_tier = "forming"
        reasons.append("Bullish structure is forming.")
        missing.append("Need structure confirmation or a higher low/reclaim.")
    elif any(x in structure_text for x in ["bear", "choch_bear", "breakdown"]):
        structure_tier = "conflicting"
        missing.append("Structure is conflicting or bearish.")
    else:
        structure_tier = "none"
        missing.append("No clean structure trigger yet.")

    # 3) Level proximity tier (support for calls)
    if breakout_ready:
        level_tier = "trigger"
        reasons.append("Price is at an actionable breakout/trigger area.")
    elif near_support or level_proximity in {"near", "support", "trigger_zone"}:
        level_tier = "near"
        reasons.append("Price is near a relevant support/trigger area.")
    elif level_proximity in {"mid", "mid_range", "far"}:
        level_tier = "far"
        missing.append("Price is not yet at a strong action level.")
    else:
        level_tier = "unknown"
        missing.append("Need better proximity to a trigger level.")

    # 4-6) Probability / confluence / validation — classified here, SCORED by the authority.
    scored = score_readiness(
        trend_tier=trend_tier,
        structure_tier=structure_tier,
        level_tier=level_tier,
        direction_matches=(prediction_direction == "up"),
        prob=prob,
        confluence_tier=_confluence_tier(confluence_read, "bullish"),
        validation_passed=validation_passed,
    )
    prob_band = scored.pop("prob_band")

    if prob_band == "strong":
        reasons.append(f"Dominant probability is strong ({prob:.2%}).")
    elif prob_band == "acceptable":
        reasons.append(f"Dominant probability is acceptable ({prob:.2%}).")
    elif prob_band == "needs_more":
        missing.append(f"Need stronger probability; current {prob:.2%}.")
    elif prob_band == "weak":
        missing.append(f"Probability is too weak for a CALL; current {prob:.2%}.")
    else:
        missing.append("Prediction direction is not bullish.")

    _ct = scored["component_scores"]["confluence_score"]
    if _ct == READINESS_CONFLUENCE_POINTS["supportive"]:
        reasons.append("Confluence is supportive.")
    elif _ct == READINESS_CONFLUENCE_POINTS["mixed"]:
        missing.append("Need stronger directional confluence.")
    else:
        missing.append("Confluence is not clearly supportive.")

    if validation_passed:
        reasons.append("Validation checks passed.")
    else:
        missing.append("Validation has not passed.")

    scored["reasons"] = reasons
    scored["missing_conditions"] = missing
    return scored


def compute_put_readiness(put_input: dict) -> dict:
    """
    V1 deterministic readiness model for the PUT card.
    Bearish mirror of compute_call_readiness: classification and wording only —
    every score, band and threshold comes from score_readiness (RC-338).
    """
    regime = _safe_lower(put_input.get("regime"))
    trend = _safe_lower(put_input.get("trend"))
    structure_confirmation = _safe_lower(put_input.get("structure_confirmation", ""))
    structure_higher_tf = _safe_lower(put_input.get("structure_higher_tf", ""))
    prediction_direction = _safe_lower(put_input.get("prediction_direction"))
    confluence_read = _safe_lower(put_input.get("confluence_read"))
    level_proximity = _safe_lower(put_input.get("level_proximity"))
    prob = _prob_float(put_input.get("prediction_dominant_prob", 0.0))
    validation_passed = bool(put_input.get("validation_passed", False))
    near_resistance = bool(put_input.get("near_resistance", put_input.get("near_support", False)))
    breakdown_ready = bool(put_input.get("breakdown_ready", put_input.get("breakout_ready", False)))

    reasons: List[str] = []
    missing: List[str] = []

    # 1) Trend / regime tier (bearish keywords)
    bearish_regime = any(x in regime for x in ["bear", "trend", "down", "breakdown"])
    bearish_trend = any(x in trend for x in ["bear", "down", "lower", "breakdown", "intact"])
    if bearish_regime and bearish_trend:
        trend_tier = "aligned"
        reasons.append("Higher timeframe trend/regime supports PUTs.")
    elif bearish_regime or bearish_trend:
        trend_tier = "partial"
        reasons.append("Trend context is somewhat supportive.")
        missing.append("Need stronger bearish regime/trend alignment.")
    else:
        trend_tier = "weak"
        missing.append("Trend/regime is not clearly bearish.")

    # 2) Structure tier (bearish) — structure_confirmation=~15m, structure_higher_tf=~60m
    structure_text = f"{structure_confirmation} {structure_higher_tf}"
    if any(x in structure_text for x in ["lower high", "breakdown confirmed", "confirmed"]):
        structure_tier = "confirmed"
        reasons.append("Structure confirmation is present.")
    elif any(x in structure_text for x in ["bear flag", "forming", "pullback", "downtrend intact"]):
        structure_tier = "forming"
        reasons.append("Bearish structure is forming.")
        missing.append("Need structure confirmation or a lower high.")
    elif any(x in structure_text for x in ["bull", "choch_bull", "breakout"]):
        structure_tier = "conflicting"
        missing.append("Structure is conflicting or bullish.")
    else:
        structure_tier = "none"
        missing.append("No clean structure trigger yet.")

    # 3) Level proximity tier (resistance for puts)
    if breakdown_ready:
        level_tier = "trigger"
        reasons.append("Price is at an actionable breakdown/trigger area.")
    elif near_resistance or level_proximity in {"near", "resistance", "trigger_zone"}:
        level_tier = "near"
        reasons.append("Price is near a relevant resistance/trigger area.")
    elif level_proximity in {"mid", "mid_range", "far"}:
        level_tier = "far"
        missing.append("Price is not yet at a strong action level.")
    else:
        level_tier = "unknown"
        missing.append("Need better proximity to a trigger level.")

    scored = score_readiness(
        trend_tier=trend_tier,
        structure_tier=structure_tier,
        level_tier=level_tier,
        direction_matches=(prediction_direction == "down"),
        prob=prob,
        confluence_tier=_confluence_tier(confluence_read, "bearish"),
        validation_passed=validation_passed,
    )
    prob_band = scored.pop("prob_band")

    if prob_band == "strong":
        reasons.append(f"Dominant probability is strong ({prob:.2%}).")
    elif prob_band == "acceptable":
        reasons.append(f"Dominant probability is acceptable ({prob:.2%}).")
    elif prob_band == "needs_more":
        missing.append(f"Need stronger probability; current {prob:.2%}.")
    elif prob_band == "weak":
        missing.append(f"Probability is too weak for a PUT; current {prob:.2%}.")
    else:
        missing.append("Prediction direction is not bearish.")

    _pt = scored["component_scores"]["confluence_score"]
    if _pt == READINESS_CONFLUENCE_POINTS["supportive"]:
        reasons.append("Confluence is supportive.")
    elif _pt == READINESS_CONFLUENCE_POINTS["mixed"]:
        missing.append("Need stronger directional confluence.")
    else:
        missing.append("Confluence is not clearly supportive.")

    if validation_passed:
        reasons.append("Validation checks passed.")
    else:
        missing.append("Validation has not passed.")

    scored["reasons"] = reasons
    scored["missing_conditions"] = missing
    return scored


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
