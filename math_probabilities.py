"""
math_probabilities.py
Mathematical probability, confidence, and scoring helpers.
Support-math layer for prediction and call engines.

Phase 2 extraction from math_exposure.py per Extraction Blueprint v1.
"""
from __future__ import annotations




# ── Constants ─────────────────────────────────────────────────────────────────

DIRECTION_THRESHOLD_PCT = 0.05  # % of spot to classify up/down/flat







OE_SPREAD_TIGHT_MAX      = 0.15

# ── OE scoring ───────────────────────────────────────────────────────────────












# ── Direction classification ─────────────────────────────────────────────────

def classify_direction(pts_move: float, spot: float,
                       threshold_pct: float = DIRECTION_THRESHOLD_PCT) -> str:
    if spot <= 0:
        return "flat"
    threshold = spot * threshold_pct / 100.0
    if pts_move > threshold:
        return "up"
    elif pts_move < -threshold:
        return "down"
    return "flat"




# ── Distance bucketing ──────────────────────────────────────────────────────







# ── Probability computation ─────────────────────────────────────────────────





# ── Confidence determination ─────────────────────────────────────────────────



def _binomial_p_value(k: int, n: int, p0: float) -> float:
    import math
    mu = n * p0
    sigma = math.sqrt(n * p0 * (1.0 - p0))
    if sigma < 1e-9:
        return 1.0
    z = (k - 0.5 - mu) / sigma
    p_value = 0.5 * (1.0 - math.erf(z / math.sqrt(2.0)))
    return max(p_value, 1e-15)


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



def flow_imbalance_label_from_normalized(normalized: float | None) -> str | None:
    """ONE label authority for the persisted/served flow_imbalance number.

    F11 residual: the live server used to stamp flow_imbalance_label from the
    book-only kernel while flow_imbalance itself came from
    flow_imbalance_normalized_with_fallback (book-or-volume). Same tick could
    publish 0.6 / source=volume beside label="balanced". The label is now a
    function of the same normalized value that is persisted and served.
    """
    if normalized is None:
        return None          # no measured imbalance -> no label (was the string "unknown")
    try:
        x = float(normalized)
    except (TypeError, ValueError):
        return None
    if x > 0.3:
        return "strong_call_demand"
    if x > 0.1:
        return "call_leaning"
    if x < -0.3:
        return "strong_put_demand"
    if x < -0.1:
        return "put_leaning"
    return "balanced"


def _atm_window_legs(exposures_by_strike: dict, spot: float, window_pts: float):
    """Summed strike_flow_legs over strikes within `window_pts` of spot, the strike count, and
    the per-strike volume activity. None when there is no strike in the window or ANY strike
    in it has unreported sizes/volume -- never a sum over part of the window."""
    from math_exposure_core import strike_flow_legs
    if not exposures_by_strike or not spot:
        return None
    sums = {"call_bid": 0.0, "call_ask": 0.0, "put_bid": 0.0, "put_ask": 0.0,
            "call_volume": 0.0, "put_volume": 0.0}
    n = 0
    activity: list[float] = []
    for strike, bucket in exposures_by_strike.items():
        try:
            k = float(strike)
        except (TypeError, ValueError):
            return None
        if abs(k - float(spot)) > window_pts:
            continue
        legs = strike_flow_legs(bucket)
        if legs is None:
            return None
        n += 1
        for key in sums:
            sums[key] += legs[key]
        activity.append(legs["call_volume"] + legs["put_volume"])
    if n == 0:
        return None
    return sums, n, activity


def compute_option_flow_imbalance(
    exposures_by_strike: dict,
    spot: float,
    *,
    window_pts: float = 5.0,
) -> dict:
    """
    Bid/ask size imbalance across strikes near ATM -- a displayed-size proxy for flow.

    net = (call_bid - call_ask) - (put_bid - put_ask); normalized = net / total displayed size.
    All None when the window has no strike, a strike with unreported sizes, or zero displayed
    size (2026-09-24): it used to return 0 / "balanced" for no data and sum partial legs.
    """
    none = {"net_imbalance": None, "normalized": None, "label": None,
            "call_imbalance": None, "put_imbalance": None}
    got = _atm_window_legs(exposures_by_strike, spot, window_pts)
    if got is None:
        return none
    s, _, _ = got
    total = s["call_bid"] + s["call_ask"] + s["put_bid"] + s["put_ask"]
    if total <= 0:
        return none
    call_imb = s["call_bid"] - s["call_ask"]
    put_imb = s["put_bid"] - s["put_ask"]
    net = call_imb - put_imb
    normalized = max(-1.0, min(1.0, net / total))
    return {
        "net_imbalance": round(net),
        "normalized": round(normalized, 3),
        "label": flow_imbalance_label_from_normalized(normalized),
        "call_imbalance": round(call_imb),
        "put_imbalance": round(put_imb),
    }




def option_flow_book_imbalance(
    exposures_by_strike: dict,
    spot: float,
    *,
    window_pts: float = 5.0,
) -> tuple[float | None, str]:
    """THE flow_imbalance number: the near-ATM displayed-size (book) imbalance, or None.

    Returns (normalized, source) with source "book" or "none". This was
    flow_imbalance_normalized_with_fallback: when displayed size was ~0 it switched to the
    call-vs-put VOLUME ratio -- a different quantity under the same field (audit S-06,
    2026-09-24: no fallbacks).
    """
    norm = compute_option_flow_imbalance(exposures_by_strike, spot, window_pts=window_pts)["normalized"]
    return (float(norm), "book") if norm is not None else (None, "none")


def compute_smart_money_signal(
    exposures_by_strike: dict,
    spot: float,
    *,
    window_pts: float = 3.0,
) -> dict:
    """
    Smart money composite — detects institutional accumulation.

    Combines: high volume + new OI (volume > OI) + bid-side dominance.
    When all three align at the same strikes, it signals intentional
    institutional positioning rather than random retail flow.

    Score 0-100:
      - Volume/OI component (0-40): high ratio near ATM
      - Flow imbalance component (0-40): strong directional bid/ask skew
      - Concentration component (0-20): activity focused at specific strikes

    Args:
        exposures_by_strike: strike → bucket dict
        spot: current price
        window_pts: tight window near ATM for smart money detection

    Returns dict with score (0-100), direction (bullish/bearish/neutral), components.
    """
    _sm_unavailable = {
        "score": None,
        "direction": None,
        "label": None,
        "vol_oi_component": None,
        "flow_component": None,
        "concentration_component": None,
    }
    # Every component must be MEASURED (audit S-07, 2026-09-24): a missing volume / OI / size
    # leg used to count as 0 -- "no signal" read from absence.
    got = _atm_window_legs(exposures_by_strike, spot, window_pts)
    if got is None:
        return dict(_sm_unavailable)
    s, _, strike_activity = got
    from math_exposure_core import strike_total_oi
    oi_total = 0.0
    for strike, bucket in exposures_by_strike.items():
        if abs(float(strike) - float(spot)) > window_pts:
            continue
        t = strike_total_oi(bucket)
        if t is None:
            return dict(_sm_unavailable)
        oi_total += t
    vol_total = s["call_volume"] + s["put_volume"]
    call_bid, call_ask, put_bid, put_ask = s["call_bid"], s["call_ask"], s["put_bid"], s["put_ask"]
    total_size = call_bid + call_ask + put_bid + put_ask
    if oi_total <= 0 or total_size <= 0 or vol_total <= 0:
        return dict(_sm_unavailable)     # a ratio with a zero base is undefined, not 0

    # Component 1: Volume/OI (0-40)
    vol_oi = vol_total / oi_total
    vol_oi_score = min(40, vol_oi / 2.0 * 40)  # ratio 2.0 = max score

    # Component 2: Flow imbalance (0-40)
    call_imb = call_bid - call_ask
    put_imb = put_bid - put_ask
    net_flow = call_imb - put_imb
    flow_ratio = abs(net_flow) / total_size
    flow_score = min(40, flow_ratio / 0.5 * 40)  # 50% imbalance = max

    # Component 3: Concentration (0-20) -- share of window volume at the busiest strike
    conc_score = min(20, max(strike_activity) / vol_total * 40)  # 50%+ in one strike = max

    total_score = min(100, vol_oi_score + flow_score + conc_score)

    # Direction from flow
    if net_flow > 0 and flow_ratio > 0.1:
        direction = "bullish"
    elif net_flow < 0 and flow_ratio > 0.1:
        direction = "bearish"
    else:
        direction = "neutral"

    if total_score >= 70:
        label = "strong_accumulation"
    elif total_score >= 45:
        label = "moderate_activity"
    elif total_score >= 20:
        label = "light_activity"
    else:
        label = "no_signal"

    return {
        "score": round(total_score, 1),
        "direction": direction,
        "label": label,
        "vol_oi_component": round(vol_oi_score, 1),
        "flow_component": round(flow_score, 1),
        "concentration_component": round(conc_score, 1),
    }
