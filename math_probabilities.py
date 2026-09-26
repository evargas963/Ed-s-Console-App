"""
math_probabilities.py
Mathematical probability, confidence, and scoring helpers.
Support-math layer for prediction and call engines.

Phase 2 extraction from math_exposure.py per Extraction Blueprint v1.
"""
from __future__ import annotations

from dataclasses import dataclass as _oe_dc
import math

from math_exposure_core import (
    MISSING_GREEK_SENTINEL,
    _f,
    greek_reported,
)


# ── Constants ─────────────────────────────────────────────────────────────────

DIRECTION_THRESHOLD_PCT = 0.05  # % of spot to classify up/down/flat


MIN_SAMPLES_STATISTICAL = 30





OE_SPREAD_TIGHT_MAX      = 0.15

# ── OE scoring ───────────────────────────────────────────────────────────────


@_oe_dc
class OeResult:
    spread: float | None
    liq_gate: bool
    gamma: float | None
    delta: float | None
    delta_gamma_ratio: float | None
    volume: float | None
    open_interest: float | None
    vol_oi_ratio: float | None
    gamma_x_oi: float | None
    gamma_is_max: bool
    max_gamma_strike: float | None
    entry_lo: float
    entry_hi: float
    # Wall-aware composite (same path live + replay)
    wall_proximity_component: float = 0.0
    wall_bias_component: float = 0.0
    wall_score_component: float = 0.0
    total_score_before_walls: float = 0.0
    total_score_after_walls: float = 0.0
    wall_contribution_detail: dict | None = None
    spread_source: str | None = None


def _oe_wall_consensus_row(walls):
    if not walls:
        return None
    for w in walls:
        lab = w.get("label") if isinstance(w, dict) else getattr(w, "label", None)
        if lab == "CONSENSUS":
            return w
    return walls[0]


def _wlevel(row, name: str):
    if row is None:
        return None
    v = row.get(name) if isinstance(row, dict) else getattr(row, name, None)
    return _f(v)


def compute_wall_score_components(
    strike_f: float, spot_f: float, side_up: str, walls,
) -> tuple[float, float, dict]:
    """
    Wall materiality for OE ranking. Returns (proximity_pts, bias_pts, audit dict).

    RC-434: dom_gamma_wall / dom_delta_wall are not independent levels — `_dominant`
    aliases the stronger of call/put when strengths exist. Scoring them again as a
    third proximity target (and +0.45 "confluence" bias) double-counts the same strike.
    After RC-420 terrain bind withholds strengths, dominance is permanently empty on the
    live path, so those terms were silent inert decision logic. Call/put gamma and delta
    walls remain the sole structural proximity/bias authorities.
    """
    if not walls:
        return 0.0, 0.0, {"walls_empty": True}
    row = _oe_wall_consensus_row(walls)
    if row is None:
        return 0.0, 0.0, {"no_consensus_row": True}

    level_names = (
        "call_gamma_wall", "put_gamma_wall",
        "call_delta_wall", "put_delta_wall",
    )
    levels: list[tuple[str, float]] = []
    for attr in level_names:
        v = _wlevel(row, attr)
        if v is not None and v > 0:
            levels.append((attr, float(v)))

    prox = 0.0
    cap = 3.0
    prox_detail: list[dict] = []
    for name, lv in levels:
        d = abs(strike_f - lv)
        contrib = min(1.2, 2.0 / (1.0 + d))
        if contrib > 0.05 and cap > 0:
            take = min(contrib, cap)
            prox += take
            cap -= take
            prox_detail.append({"level": name, "strike": lv, "contrib": round(take, 4)})

    bias = 0.0
    bias_notes: list[str] = []
    cgw = _wlevel(row, "call_gamma_wall")
    pgw = _wlevel(row, "put_gamma_wall")

    if side_up == "CALL":
        if cgw and spot_f < cgw and spot_f <= strike_f <= cgw + 2.0:
            bias += 0.85
            bias_notes.append("strike_in_call_gamma_wall_approach_zone")
        if pgw and abs(strike_f - pgw) <= 2.0 and strike_f >= pgw - 0.5:
            bias += 0.55
            bias_notes.append("near_put_gamma_support")
    else:
        if pgw and spot_f > pgw and pgw - 2.0 <= strike_f <= spot_f:
            bias += 0.85
            bias_notes.append("strike_in_put_gamma_wall_approach_zone")
        if cgw and abs(strike_f - cgw) <= 2.0 and strike_f <= cgw + 0.5:
            bias += 0.55
            bias_notes.append("near_call_gamma_resistance")

    bias = min(bias, 2.0)
    return prox, bias, {
        "consensus_label": (row.get("label") if isinstance(row, dict) else getattr(row, "label", None)),
        "proximity_detail": prox_detail,
        "bias_notes": bias_notes,
    }


def score_option_expression(contracts, spot, strike, side, *, walls=None):
    if not contracts or strike is None or side is None:
        return None
    side_up = str(side).upper().strip()
    try:
        strike_f = float(strike)
        spot_f = float(spot)
    except (TypeError, ValueError):
        return None
    candidates = [
        ct
        for ct in contracts
        # single source: parse the strike once via the canonical finite reader (was
        # _f for the filter + raw float() for the value — the last such double-parse).
        if str(ct.get("putCall", "")).upper().strip() == side_up
        and (sp := _f(ct.get("strikePrice"))) is not None
        and abs(sp - strike_f) < 0.01
    ]
    if not candidates:
        return None
    ct = candidates[0]
    bid = _f(ct.get("bid"))
    ask = _f(ct.get("ask"))
    gamma_raw = _f(ct.get("gamma"))
    delta_raw = _f(ct.get("delta"))
    delta = delta_raw if (delta_raw is not None and delta_raw != MISSING_GREEK_SENTINEL and math.isfinite(delta_raw)) else None
    gamma = gamma_raw if greek_reported(gamma_raw, iv=_f(ct.get("volatility"))) else None
    volume = _f(ct.get("totalVolume"))
    oi = _f(ct.get("openInterest"))
    a_px, b_px = ask, bid
    spread = round(a_px - b_px, 4) if b_px is not None and a_px is not None else None
    liq_gate = spread is not None and spread <= OE_SPREAD_TIGHT_MAX
    dgr = round(abs(delta) / abs(gamma), 2) if gamma and gamma != 0 and delta is not None else None
    voi = round(volume / oi, 3) if oi and oi > 0 and volume is not None else None
    gxoi = gamma * oi if gamma is not None and oi is not None else None
    max_g = 0.0
    max_gs = None
    gis_max = False
    for c in contracts:
        if str(c.get("putCall", "")).upper().strip() != side_up:
            continue
        g_raw = _f(c.get("gamma"))
        if not greek_reported(g_raw, iv=_f(c.get("volatility"))):
            continue
        if abs(g_raw) > abs(max_g):
            max_g = g_raw
            max_gs = _f(c.get("strikePrice"))
    if max_gs is not None and abs(max_gs - strike_f) < 0.01:
        gis_max = True

    base = 0.0
    if liq_gate:
        base += 5.0
    elif spread is not None:
        base += max(0, 3.0 - spread * 10.0)
    if gamma is not None:
        base += min(abs(gamma) * 10.0, 3.0)
    base += (1.0 / (1.0 + abs(strike_f - spot_f))) * 3.0
    if voi is not None and voi > 0:
        base += min(voi, 1.0) * 2.0
    if gxoi is not None:
        base += min(abs(gxoi) / 1000.0, 1.0)
    if gis_max:
        base += 1.0

    wp, wb, wdbg = compute_wall_score_components(strike_f, spot_f, side_up, walls)
    wsum = wp + wb
    total_after = base + wsum

    return OeResult(
        spread=spread,
        liq_gate=liq_gate,
        gamma=gamma,
        delta=delta,
        delta_gamma_ratio=dgr,
        volume=volume,
        open_interest=oi,
        vol_oi_ratio=voi,
        gamma_x_oi=gxoi,
        gamma_is_max=gis_max,
        max_gamma_strike=max_gs,
        entry_lo=round(strike_f - 0.50, 2),
        entry_hi=round(strike_f + 0.50, 2),
        wall_proximity_component=round(wp, 4),
        wall_bias_component=round(wb, 4),
        wall_score_component=round(wsum, 4),
        total_score_before_walls=round(base, 4),
        total_score_after_walls=round(total_after, 4),
        wall_contribution_detail=wdbg,
        spread_source=("derived_chain_bid_ask_pts" if spread is not None else None),
    )


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
