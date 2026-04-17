"""
math_probabilities.py
Mathematical probability, confidence, and scoring helpers.
Support-math layer for prediction and call engines.

Phase 2 extraction from math_exposure.py per Extraction Blueprint v1.
"""
from __future__ import annotations

from dataclasses import dataclass as _oe_dc
from typing import Optional
import math

from math_exposure_core import _f


# ── Constants ─────────────────────────────────────────────────────────────────

DIRECTION_THRESHOLD_PCT = 0.05  # % of spot to classify up/down/flat

DIST_BUCKET_EDGES    = [1.0, 2.0, 5.0]
DIST_BUCKET_LABELS   = ["0-1", "1-2", "2-5"]
DIST_BUCKET_OVERFLOW = "5+"

MIN_SAMPLES_STATISTICAL = 30
MIN_SAMPLES_CONFIDENT   = 150

CONFIDENCE_RULES = {
    "tier_1": {"base": "high"},
    "tier_2": {"base": "high"},
    "tier_3": {"base": "medium"},
    "tier_4": {"base": "medium"},
    "tier_5": {"base": "low"},
    "tier_6": {"base": "low"},
    "tier_7": {"base": "low"},
}

REVERSAL_RISK_LOW_MAX  = 0.20
REVERSAL_RISK_MOD_MAX  = 0.35

RECENCY_HALF_LIFE_DAYS = 21.0

# Stop-distance constants (used by call_engine)
STOP_BASE_PCT       = 0.0018
STOP_TIME_DECAY_PCT = 0.00015
STOP_VIX_MED_PCT    = 0.0004
STOP_VIX_HIGH_PCT   = 0.0008
STOP_FLOOR_PCT      = 0.0010
STOP_CEILING_PCT    = 0.0030

# OE scoring constants
OE_DELTA_GAMMA_RATIO_MIN = 2.0
OE_DELTA_GAMMA_RATIO_MAX = 8.0
OE_VOL_OI_MIN            = 0.10
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
    """
    if not walls:
        return 0.0, 0.0, {"walls_empty": True}
    row = _oe_wall_consensus_row(walls)
    if row is None:
        return 0.0, 0.0, {"no_consensus_row": True}

    level_names = (
        "call_gamma_wall", "put_gamma_wall", "dom_gamma_wall",
        "dom_delta_wall", "dom_oi_wall",
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
    if isinstance(row, dict):
        dgs = str(row.get("dom_gamma_side") or "").upper()
    else:
        dgs = str(getattr(row, "dom_gamma_side", "") or "").upper()

    if side_up == "CALL":
        if cgw and spot_f < cgw and spot_f <= strike_f <= cgw + 2.0:
            bias += 0.85
            bias_notes.append("strike_in_call_gamma_wall_approach_zone")
        if pgw and abs(strike_f - pgw) <= 2.0 and strike_f >= pgw - 0.5:
            bias += 0.55
            bias_notes.append("near_put_gamma_support")
        dgw = _wlevel(row, "dom_gamma_wall")
        if dgs == "CALL" and dgw is not None and abs(strike_f - dgw) <= 1.5:
            bias += 0.45
            bias_notes.append("dom_gamma_call_confluence")
    else:
        if pgw and spot_f > pgw and pgw - 2.0 <= strike_f <= spot_f:
            bias += 0.85
            bias_notes.append("strike_in_put_gamma_wall_approach_zone")
        if cgw and abs(strike_f - cgw) <= 2.0 and strike_f <= cgw + 0.5:
            bias += 0.55
            bias_notes.append("near_call_gamma_resistance")
        dgw = _wlevel(row, "dom_gamma_wall")
        if dgs == "PUT" and dgw is not None and abs(strike_f - dgw) <= 1.5:
            bias += 0.45
            bias_notes.append("dom_gamma_put_confluence")

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
    except Exception:
        return None
    candidates = [
        ct
        for ct in contracts
        if str(ct.get("putCall", "")).upper().strip() == side_up
        and _f(ct.get("strikePrice")) is not None
        and abs(float(ct.get("strikePrice")) - strike_f) < 0.01
    ]
    if not candidates:
        return None
    ct = candidates[0]
    bid = _f(ct.get("bid"))
    ask = _f(ct.get("ask"))
    gamma = _f(ct.get("gamma"))
    delta = _f(ct.get("delta"))
    volume = _f(ct.get("totalVolume")) or _f(ct.get("volume"))
    oi = _f(ct.get("openInterest"))
    spread = round(ask - bid, 4) if bid is not None and ask is not None else None
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
        g = _f(c.get("gamma"))
        if g is not None and abs(g) > abs(max_g):
            max_g = g
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


# ── Distance bucketing ──────────────────────────────────────────────────────

def dist_bucket(dist: float | None) -> str | None:
    if dist is None:
        return None
    d = abs(dist)
    for edge, label in zip(DIST_BUCKET_EDGES, DIST_BUCKET_LABELS):
        if d <= edge:
            return label
    return DIST_BUCKET_OVERFLOW


def bucket_lo(bucket: str | None) -> float:
    if bucket is None:
        return 0.0
    raw = bucket.split("-")[0]
    return float(raw.rstrip("+"))


def bucket_hi(bucket: str | None) -> float:
    if bucket is None:
        return 9999.0
    if bucket.endswith("+"):
        return 9999.0
    hi = bucket.split("-")[-1]
    return 9999.0 if hi == "" else float(hi)


# ── Probability computation ─────────────────────────────────────────────────

def compute_probs(similar: list, outcome_col: str,
                  half_life_days: float = RECENCY_HALF_LIFE_DAYS) -> dict:
    import time as _time
    now = _time.time()
    decay_rate = 0.693147 / (half_life_days * 86400.0)
    weights = {"up": 0.0, "down": 0.0, "flat": 0.0}
    total_weight = 0.0
    for row in similar:
        val = row.get(outcome_col)
        if val not in weights:
            continue
        ts = row.get("ts_utc")
        if ts is not None:
            age_seconds = max(now - ts, 0.0)
            w = 2.718281828 ** (-decay_rate * age_seconds)
        else:
            w = 0.5
        weights[val] += w
        total_weight += w
    if total_weight < 1e-9:
        return {"up": 0.33, "down": 0.33, "flat": 0.34}
    return {k: round(v / total_weight, 3) for k, v in weights.items()}


def dominant_direction(up: float, down: float, flat: float) -> tuple:
    probs = {"up": up, "down": down, "flat": flat}
    dom = max(probs, key=probs.get)
    return dom, probs[dom]


# ── Confidence determination ─────────────────────────────────────────────────

def determine_confidence(match_tier: int, n_used: int,
                         dominant_prob: float,
                         similar: list = None,
                         outcome_col: str = "outcome_5c") -> str:
    """outcome_col = horizon for confidence; default 5c (~5 min with 1m canonical)."""
    if similar is not None and n_used >= MIN_SAMPLES_STATISTICAL:
        counts = {"up": 0, "down": 0, "flat": 0}
        for row in similar:
            val = row.get(outcome_col)
            if val in counts:
                counts[val] += 1
        total = sum(counts.values())
        if total >= MIN_SAMPLES_STATISTICAL:
            dom_dir = max(counts, key=counts.get)
            k = counts[dom_dir]
            n = total
            p0 = 1.0 / 3.0
            p_value = _binomial_p_value(k, n, p0)
            if p_value < 0.01 and match_tier <= 4:
                return "high"
            if p_value < 0.05 and match_tier <= 5:
                return "medium" if match_tier >= 4 else "high"
            if p_value < 0.05:
                return "medium"
            if p_value < 0.10 and match_tier <= 4:
                return "medium"
            return "low"
    tier_key = f"tier_{match_tier}" if isinstance(match_tier, int) else str(match_tier)
    rules = CONFIDENCE_RULES.get(tier_key, CONFIDENCE_RULES.get("tier_7", {"base": "low"}))
    # rules is a dict like {"base": "high"} — return the base confidence
    if isinstance(rules, dict):
        return rules.get("base", "low")
    # Legacy format: list of (min_samples, min_prob, level) tuples
    for min_samples, min_prob, level in rules:
        if n_used >= min_samples and dominant_prob >= min_prob:
            return level
    return "low"


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

def compute_percentile_range(similar: list, col: str = "outcome_3c_pts",
                             lo_pct: float = 0.25, hi_pct: float = 0.75,
                             min_samples: int = 10) -> tuple:
    pts = [r.get(col) for r in similar if r.get(col) is not None]
    if len(pts) < min_samples:
        return None, None
    pts_sorted = sorted(pts)
    n = len(pts_sorted)
    lo = round(pts_sorted[int(n * lo_pct)], 2)
    hi = round(pts_sorted[int(n * hi_pct)], 2)
    return lo, hi


def classify_reversal_risk(reversal_prob: float | None) -> str:
    if reversal_prob is None:
        return ""
    if reversal_prob <= REVERSAL_RISK_LOW_MAX:
        return "low"
    elif reversal_prob <= REVERSAL_RISK_MOD_MAX:
        return "moderate"
    return "high"


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

def compute_dealer_pressure_index(
    net_dex: float,
    net_gex: float,
    total_oi: float,
) -> dict:
    """
    Dealer Pressure Index (DPI).

    Formula: DPI = sign(NetDEX) × |NetGEX| / TotalOI

    Positive DPI → dealers forced to buy underlying.
    Negative DPI → dealers forced to sell underlying.
    Magnitude reflects pressure strength.

    Args:
        net_dex:   net delta exposure (dollars or share-equiv)
        net_gex:   net gamma exposure (dollars or raw)
        total_oi:  total open interest (dollars or contracts)

    Returns dict with raw_dpi, normalized (0-100), direction, magnitude.
    """
    if total_oi is None or total_oi <= 0 or net_gex is None or net_dex is None:
        return {"raw": None, "normalized": None, "direction": "neutral", "magnitude": "negligible"}

    sign = 1.0 if net_dex >= 0 else -1.0
    raw = sign * abs(net_gex) / total_oi

    direction = "buying" if raw > 0 else "selling" if raw < 0 else "neutral"
    abs_raw = abs(raw)

    # Normalize: empirical range roughly 0–0.5 for typical options chains
    normalized = min(100.0, abs_raw / 0.5 * 100.0)

    if normalized >= 70:
        magnitude = "strong"
    elif normalized >= 40:
        magnitude = "moderate"
    elif normalized >= 15:
        magnitude = "mild"
    else:
        magnitude = "negligible"

    return {
        "raw": round(raw, 6),
        "normalized": round(normalized, 1),
        "direction": direction,
        "magnitude": magnitude,
    }


def compute_hedging_flow_score(
    net_gex_normalized: float,
    net_dex_normalized: float,
    charm_normalized: float,
    vanna_normalized: float,
    *,
    w_gex: float = 0.25,
    w_dex: float = 0.25,
    w_charm: float = 0.25,
    w_vanna: float = 0.25,
) -> dict:
    """
    Hedging Flow Score — composite dealer hedging pressure.

    Formula: Score = w1(GEX_norm) + w2(DEX_norm) + w3(Charm_norm) + w4(Vanna_norm)

    Positive score → dealers likely buy dips.
    Negative score → dealers likely sell rallies.

    All inputs should be pre-normalized to roughly -1 to +1 range.
    Output normalized to 0-100 (50 = neutral).

    Args:
        net_gex_normalized:  net GEX, normalized (-1 to +1)
        net_dex_normalized:  net DEX, normalized (-1 to +1)
        charm_normalized:    net charm, normalized (-1 to +1, positive = buying)
        vanna_normalized:    net vanna, normalized (-1 to +1)
        w_*:                 weights (default equal 0.25 each per spec)

    Returns dict with raw_score, normalized (0-100), direction, magnitude.
    """
    raw = (
        w_gex * (net_gex_normalized or 0) +
        w_dex * (net_dex_normalized or 0) +
        w_charm * (charm_normalized or 0) +
        w_vanna * (vanna_normalized or 0)
    )

    # Map from -1..+1 range to 0..100
    normalized = max(0.0, min(100.0, (raw + 1.0) * 50.0))

    direction = "buying" if raw > 0.1 else "selling" if raw < -0.1 else "neutral"

    if abs(raw) >= 0.6:
        magnitude = "strong"
    elif abs(raw) >= 0.3:
        magnitude = "moderate"
    elif abs(raw) >= 0.1:
        magnitude = "mild"
    else:
        magnitude = "negligible"

    return {
        "raw": round(raw, 4),
        "normalized": round(normalized, 1),
        "direction": direction,
        "magnitude": magnitude,
    }


def compute_gamma_gradient(
    exposures_by_strike: dict,
    spot: float,
    *,
    window_pts: float = 5.0,
) -> float | None:
    """
    Gamma Gradient = d(GEX) / d(Price)

    Per Derived Formula Dictionary Section 5:
    High gradient zones indicate unstable positioning and
    often precede sharp directional moves.

    Computed as the slope of net_gex_1pct across strikes near spot.

    Args:
        exposures_by_strike: strike → bucket dict
        spot:                current price
        window_pts:          how far above/below spot to sample

    Returns gradient (positive = increasing GEX upward), or None.
    """
    if not exposures_by_strike or not spot:
        return None

    below_gex = []
    above_gex = []

    for strike, bucket in exposures_by_strike.items():
        k = float(strike)
        gex = float(bucket.get("net_gex_1pct", 0) or 0)
        if abs(k - spot) > window_pts:
            continue
        if k < spot:
            below_gex.append(gex)
        elif k > spot:
            above_gex.append(gex)

    if not below_gex or not above_gex:
        return None

    avg_below = sum(below_gex) / len(below_gex)
    avg_above = sum(above_gex) / len(above_gex)

    gradient = (avg_above - avg_below) / (2 * window_pts)
    return round(gradient, 4)


def compute_breakout_score(
    net_gex_at_spot: float | None,
    gamma_gradient: float | None,
    void_factor: float | None,
) -> dict:
    """
    Breakout Probability Score.

    Formula: BreakoutScore = (1 / |GEX|) + GammaGradient + LiquidityVoidFactor

    Higher values indicate stronger breakout potential.

    Args:
        net_gex_at_spot:  absolute GEX near current spot
        gamma_gradient:   d(GEX)/d(Price) near spot
        void_factor:      0-1, how close/deep in a void zone (0 = no void, 1 = deep void)

    Returns dict with raw_score, normalized (0-100), label.
    """
    inv_gex = 0.0
    if net_gex_at_spot and abs(net_gex_at_spot) > 0:
        # Normalize: low GEX → high inverse. Cap at reasonable value.
        inv_gex = min(1.0, 1000.0 / abs(net_gex_at_spot))

    grad = min(1.0, max(-1.0, gamma_gradient or 0))
    void = max(0.0, min(1.0, void_factor or 0))

    raw = inv_gex + abs(grad) + void  # 0 to ~3 range
    normalized = min(100.0, raw / 3.0 * 100.0)

    if normalized >= 70:
        label = "high"
    elif normalized >= 40:
        label = "moderate"
    elif normalized >= 15:
        label = "low"
    else:
        label = "negligible"

    return {
        "raw": round(raw, 4),
        "normalized": round(normalized, 1),
        "label": label,
        "components": {
            "inv_gex": round(inv_gex, 4),
            "gradient": round(abs(grad), 4),
            "void_factor": round(void, 4),
        },
    }


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
    gex = abs(gex_at_pin or 0)
    oi_conc = max(0.0, min(1.0, oi_concentration or 0))

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


def compute_vol_expansion_signal(
    net_gex: float | None,
    iv_change: float | None,
    gamma_gradient: float | None,
) -> dict:
    """
    Volatility Expansion Signal.

    Formula: VolSignal = (−NetGEX) + IVChange + GammaGradient

    Signal strengthens when NetGEX turns negative, IV rises,
    and gamma gradient rises.

    Args:
        net_gex:          net gamma exposure (negative = expansion risk)
        iv_change:        IV direction as numeric (-1 contracting, 0 flat, +1 expanding)
        gamma_gradient:   d(GEX)/d(Price)

    Returns dict with raw_score, normalized (0-100), label.
    """
    # Negative GEX contributes positively to expansion signal
    neg_gex_component = 0.0
    if net_gex is not None:
        # Normalize: large negative GEX → high expansion signal
        neg_gex_component = max(0.0, min(1.0, -net_gex / 100000.0)) if net_gex < 0 else 0.0

    iv_comp = max(0.0, min(1.0, (iv_change or 0)))
    grad_comp = min(1.0, abs(gamma_gradient or 0))

    raw = neg_gex_component + iv_comp + grad_comp  # 0-3 range
    normalized = min(100.0, raw / 3.0 * 100.0)

    if normalized >= 65:
        label = "high"
    elif normalized >= 35:
        label = "moderate"
    elif normalized >= 15:
        label = "low"
    else:
        label = "negligible"

    return {
        "raw": round(raw, 4),
        "normalized": round(normalized, 1),
        "label": label,
        "components": {
            "neg_gex": round(neg_gex_component, 4),
            "iv_change": round(iv_comp, 4),
            "gradient": round(grad_comp, 4),
        },
    }


def compute_sweep_score(
    dist_to_nearest_wall: float | None,
    void_factor: float | None,
    momentum_factor: float | None,
) -> dict:
    """
    Liquidity Sweep Probability Score.

    Formula: SweepScore = (1 / distance_to_wall) + LiquidityVoidFactor + MomentumFactor

    Higher values suggest increased odds of a sweep into a major wall
    or liquidity pocket.

    Args:
        dist_to_nearest_wall: absolute distance in points to nearest wall
        void_factor:          0-1, how close/deep in a void zone
        momentum_factor:      0-1, current momentum strength (e.g. from candle body / ATR)

    Returns dict with raw_score, normalized (0-100), label.
    """
    # Inverse distance: closer = higher sweep probability
    inv_dist = 0.0
    if dist_to_nearest_wall and dist_to_nearest_wall > 0:
        inv_dist = min(1.0, 2.0 / dist_to_nearest_wall)  # 2pts away = 1.0

    void = max(0.0, min(1.0, void_factor or 0))
    momentum = max(0.0, min(1.0, momentum_factor or 0))

    raw = inv_dist + void + momentum  # 0-3 range
    normalized = min(100.0, raw / 3.0 * 100.0)

    if normalized >= 65:
        label = "high"
    elif normalized >= 35:
        label = "moderate"
    elif normalized >= 15:
        label = "low"
    else:
        label = "negligible"

    return {
        "raw": round(raw, 4),
        "normalized": round(normalized, 1),
        "label": label,
        "components": {
            "inv_dist": round(inv_dist, 4),
            "void_factor": round(void, 4),
            "momentum": round(momentum, 4),
        },
    }



# ── Sector Strength Ranking ──────────────────────────────────────────────────

def compute_sector_strength(
    sectors: dict,
) -> dict:
    """
    Rank sectors by performance to identify rotation and risk appetite.

    Args:
        sectors: dict of sector_name → change_pct (e.g. {'KRE': -0.5, 'XBI': 1.2, ...})

    Returns dict with:
        ranking:        list of (name, chg_pct) sorted strongest to weakest
        leader:         strongest sector name
        laggard:        weakest sector name
        breadth:        fraction of sectors positive (0-1)
        risk_signal:    'risk_on' if breadth > 0.6, 'risk_off' if < 0.4, else 'mixed'
        spread:         difference between leader and laggard
    """
    if not sectors:
        return {"ranking": [], "leader": None, "laggard": None,
                "breadth": 0.0, "risk_signal": "unknown", "spread": 0.0}

    valid = {k: v for k, v in sectors.items() if v is not None}
    if not valid:
        return {"ranking": [], "leader": None, "laggard": None,
                "breadth": 0.0, "risk_signal": "unknown", "spread": 0.0}

    ranking = sorted(valid.items(), key=lambda x: x[1], reverse=True)
    leader = ranking[0][0]
    laggard = ranking[-1][0]
    n_positive = sum(1 for _, v in ranking if v > 0)
    breadth = n_positive / len(ranking)
    spread = round(ranking[0][1] - ranking[-1][1], 2)

    if breadth >= 0.7:
        risk_signal = "risk_on"
    elif breadth <= 0.3:
        risk_signal = "risk_off"
    else:
        risk_signal = "mixed"

    return {
        "ranking": [(k, round(v, 2)) for k, v in ranking],
        "leader": leader,
        "laggard": laggard,
        "breadth": round(breadth, 2),
        "risk_signal": risk_signal,
        "spread": spread,
    }


# ── IWM Deep Confluence Analysis ─────────────────────────────────────────────

def compute_iwm_confluence(
    spy_chg: float | None,
    qqq_chg: float | None,
    iwm_chg: float | None,
    kre_chg: float | None = None,
    xbi_chg: float | None = None,
    psci_chg: float | None = None,
    xrt_chg: float | None = None,
    vix_level: float | None = None,
    vix_direction: str | None = None,
) -> dict:
    """
    IWM deep confluence analysis — institutional risk appetite signals.

    IWM (Russell 2000) is the market's risk barometer because:
    - Small caps carry more debt → rate sensitive
    - Domestic revenue → domestic economy proxy
    - First to sell in risk-off, first to rally in risk-on
    - Less institutional support → faster liquidity drain
    - Sector composition reveals rotation (financials, biotech, industrials, consumer)

    This function produces 6 confluence signals from IWM and its sector proxies.

    Args:
        spy_chg:      SPY % change today
        qqq_chg:      QQQ % change today
        iwm_chg:      IWM % change today
        kre_chg:      KRE (financials) % change
        xbi_chg:      XBI (biotech) % change
        psci_chg:     PSCI (industrials) % change
        xrt_chg:      XRT (consumer) % change
        vix_level:    current VIX
        vix_direction: 'expanding', 'contracting', 'flat'

    Returns dict with all confluence signals.
    """
    result = {
        # Signal 1: Risk regime
        "risk_regime": "unknown",
        "risk_regime_confidence": "low",

        # Signal 2: SPY-IWM divergence
        "spy_iwm_divergence": 0.0,       # IWM - SPY spread (positive = IWM outperforming)
        "spy_iwm_divergence_label": "aligned",  # 'aligned', 'iwm_leading', 'iwm_lagging', 'diverging'
        "spy_iwm_fragile": False,         # True if SPY up but IWM down → fragile rally

        # Signal 3: QQQ-IWM rotation
        "qqq_iwm_spread": 0.0,           # QQQ - IWM (positive = growth > value)
        "rotation_signal": "neutral",     # 'growth_favored', 'value_favored', 'neutral'

        # Signal 4: Sector breadth quality
        "sector_breadth_quality": "unknown",  # 'broad_strength', 'narrow', 'broad_weakness', 'rotation'
        "n_sectors_positive": 0,
        "n_sectors_negative": 0,

        # Signal 5: IWM early warning
        "early_warning": False,           # True if IWM weak while SPY/QQQ hold
        "early_warning_type": None,       # 'risk_off_forming', 'small_cap_stress', None

        # Signal 6: Composite risk score (0-100, 50=neutral)
        "risk_score": 50.0,
        "risk_score_label": "neutral",    # 'strong_risk_on', 'risk_on', 'neutral', 'risk_off', 'strong_risk_off'

        # Summary
        "summary": "",
    }

    spy = spy_chg or 0
    qqq = qqq_chg or 0
    iwm = iwm_chg or 0

    # ── Signal 1: Risk Regime ─────────────────────────────────────────────────
    # IWM is the cleanest risk barometer. Strong IWM = risk appetite.
    if iwm > 0.5:
        result["risk_regime"] = "risk_on"
        result["risk_regime_confidence"] = "high" if iwm > 1.0 else "medium"
    elif iwm > 0.1:
        result["risk_regime"] = "risk_on"
        result["risk_regime_confidence"] = "low"
    elif iwm < -0.5:
        result["risk_regime"] = "risk_off"
        result["risk_regime_confidence"] = "high" if iwm < -1.0 else "medium"
    elif iwm < -0.1:
        result["risk_regime"] = "risk_off"
        result["risk_regime_confidence"] = "low"
    else:
        result["risk_regime"] = "neutral"
        result["risk_regime_confidence"] = "low"

    # VIX confirmation — elevated VIX + IWM weakness = high confidence risk-off
    if vix_level and vix_level > 25 and iwm < -0.3:
        result["risk_regime"] = "risk_off"
        result["risk_regime_confidence"] = "high"
    elif vix_level and vix_level < 15 and iwm > 0.3:
        result["risk_regime"] = "risk_on"
        result["risk_regime_confidence"] = "high"

    # ── Signal 2: SPY-IWM Divergence ──────────────────────────────────────────
    spread = round(iwm - spy, 2)
    result["spy_iwm_divergence"] = spread

    if abs(spread) < 0.15:
        result["spy_iwm_divergence_label"] = "aligned"
    elif spread > 0.5:
        result["spy_iwm_divergence_label"] = "iwm_leading"
    elif spread > 0.15:
        result["spy_iwm_divergence_label"] = "iwm_leading"
    elif spread < -0.5:
        result["spy_iwm_divergence_label"] = "iwm_lagging"
    elif spread < -0.15:
        result["spy_iwm_divergence_label"] = "iwm_lagging"

    # Fragile rally: SPY positive, IWM negative
    if spy > 0.1 and iwm < -0.1:
        result["spy_iwm_fragile"] = True
        result["spy_iwm_divergence_label"] = "diverging"

    # ── Signal 3: QQQ-IWM Rotation ───────────────────────────────────────────
    qqq_iwm = round(qqq - iwm, 2)
    result["qqq_iwm_spread"] = qqq_iwm

    if qqq_iwm > 0.5:
        result["rotation_signal"] = "growth_favored"
    elif qqq_iwm < -0.5:
        result["rotation_signal"] = "value_favored"
    else:
        result["rotation_signal"] = "neutral"

    # ── Signal 4: Sector Breadth Quality ─────────────────────────────────────
    sectors = [v for v in [kre_chg, xbi_chg, psci_chg, xrt_chg] if v is not None]
    if sectors:
        n_pos = sum(1 for v in sectors if v > 0.05)
        n_neg = sum(1 for v in sectors if v < -0.05)
        result["n_sectors_positive"] = n_pos
        result["n_sectors_negative"] = n_neg

        if n_pos >= 3:
            result["sector_breadth_quality"] = "broad_strength"
        elif n_neg >= 3:
            result["sector_breadth_quality"] = "broad_weakness"
        elif n_pos >= 1 and n_neg >= 1 and abs(max(sectors) - min(sectors)) > 1.0:
            result["sector_breadth_quality"] = "rotation"
        elif n_pos >= 2:
            result["sector_breadth_quality"] = "narrow"
        else:
            result["sector_breadth_quality"] = "narrow"

    # ── Signal 5: Early Warning ──────────────────────────────────────────────
    # IWM weakening while mega-caps hold = risk-off forming
    if iwm < -0.3 and spy > -0.1 and qqq > -0.1:
        result["early_warning"] = True
        result["early_warning_type"] = "risk_off_forming"
    # IWM weak + financials (KRE) weak = rate stress
    elif iwm < -0.3 and kre_chg is not None and kre_chg < -0.3:
        result["early_warning"] = True
        result["early_warning_type"] = "small_cap_stress"

    # ── Signal 6: Composite Risk Score ───────────────────────────────────────
    # 0 = strong risk-off, 50 = neutral, 100 = strong risk-on
    score = 50.0

    # IWM direction is the primary driver
    score += iwm * 15  # ±1% IWM = ±15 points

    # SPY-IWM alignment bonus/penalty
    if spy > 0 and iwm > 0:
        score += 5  # both up = confirmation
    elif spy > 0 and iwm < 0:
        score -= 10  # divergence = fragile
    elif spy < 0 and iwm < 0:
        score -= 5  # both down = confirmation of weakness

    # Sector breadth
    if sectors:
        breadth_pct = n_pos / len(sectors) if sectors else 0
        score += (breadth_pct - 0.5) * 10  # 100% positive = +5, 0% = -5

    # VIX impact
    if vix_level:
        if vix_level > 30:
            score -= 15
        elif vix_level > 25:
            score -= 8
        elif vix_level < 15:
            score += 5

    score = max(0, min(100, round(score, 1)))
    result["risk_score"] = score

    if score >= 70:
        result["risk_score_label"] = "strong_risk_on"
    elif score >= 55:
        result["risk_score_label"] = "risk_on"
    elif score >= 45:
        result["risk_score_label"] = "neutral"
    elif score >= 30:
        result["risk_score_label"] = "risk_off"
    else:
        result["risk_score_label"] = "strong_risk_off"

    # ── Summary ──────────────────────────────────────────────────────────────
    parts = []
    parts.append(f"Risk: {result['risk_regime']} ({result['risk_regime_confidence']})")

    if result["spy_iwm_fragile"]:
        parts.append("SPY-IWM DIVERGING — fragile rally, small caps selling")
    elif result["spy_iwm_divergence_label"] == "iwm_leading":
        parts.append(f"IWM leading by {spread:+.2f}% — broad risk appetite")
    elif result["spy_iwm_divergence_label"] == "iwm_lagging":
        parts.append(f"IWM lagging by {spread:.2f}% — narrow leadership")

    if result["rotation_signal"] == "growth_favored":
        parts.append("Growth > Value rotation (QQQ leading)")
    elif result["rotation_signal"] == "value_favored":
        parts.append("Value > Growth rotation (IWM leading)")

    if result["early_warning"]:
        parts.append(f"EARLY WARNING: {result['early_warning_type']}")

    if result["sector_breadth_quality"] == "broad_strength":
        parts.append("Broad sector strength")
    elif result["sector_breadth_quality"] == "broad_weakness":
        parts.append("Broad sector weakness")
    elif result["sector_breadth_quality"] == "rotation":
        parts.append("Sector rotation in progress")

    result["summary"] = " | ".join(parts)

    return result


# ── Option Flow Signals (from Schwab bid/ask size + volume) ──────────────────

def compute_volume_oi_ratio(
    exposures_by_strike: dict,
    spot: float,
    *,
    window_pts: float = 5.0,
) -> dict:
    """
    Volume/OI ratio across strikes near ATM.

    Ratio > 1.0 → new positions being opened (fresh institutional activity).
    Ratio 0.5–1.0 → moderate activity, some new / some closing.
    Ratio < 0.5 → stale OI, little new activity.

    Args:
        exposures_by_strike: strike → bucket dict with call_volume, put_volume, call_oi, put_oi
        spot: current price
        window_pts: how far from spot to aggregate

    Returns dict with ratio, interpretation, total_volume, total_oi.
    """
    if not exposures_by_strike or not spot:
        return {"ratio": None, "label": "unknown", "total_volume": 0, "total_oi": 0}

    total_vol = 0.0
    total_oi = 0.0

    for strike, bucket in exposures_by_strike.items():
        k = float(strike)
        if abs(k - spot) > window_pts:
            continue
        total_vol += float(bucket.get("call_volume", 0) or 0) + float(bucket.get("put_volume", 0) or 0)
        total_oi += float(bucket.get("call_oi", 0) or 0) + float(bucket.get("put_oi", 0) or 0)

    if total_oi <= 0:
        return {"ratio": None, "label": "no_oi", "total_volume": total_vol, "total_oi": 0}

    ratio = total_vol / total_oi

    if ratio > 1.5:
        label = "heavy_new_positions"
    elif ratio > 1.0:
        label = "new_positions"
    elif ratio > 0.5:
        label = "moderate"
    elif ratio > 0.1:
        label = "stale"
    else:
        label = "dormant"

    return {
        "ratio": round(ratio, 3),
        "label": label,
        "total_volume": round(total_vol),
        "total_oi": round(total_oi),
    }


def compute_option_flow_imbalance(
    exposures_by_strike: dict,
    spot: float,
    *,
    window_pts: float = 5.0,
) -> dict:
    """
    Bid/ask size imbalance across strikes near ATM — order flow proxy.

    Positive imbalance → buyers dominating (bid-side larger). Bullish.
    Negative imbalance → sellers dominating (ask-side larger). Bearish.
    Near zero → balanced flow.

    This is the closest to real order flow Schwab gives you without tick data.

    Args:
        exposures_by_strike: strike → bucket dict with bid_size, ask_size fields
        spot: current price
        window_pts: aggregation window from spot

    Returns dict with net_imbalance, normalized (-1 to +1), label, components.
    """
    if not exposures_by_strike or not spot:
        return {"net_imbalance": 0, "normalized": 0, "label": "unknown",
                "call_imbalance": 0, "put_imbalance": 0}

    call_bid = call_ask = put_bid = put_ask = 0.0

    for strike, bucket in exposures_by_strike.items():
        k = float(strike)
        if abs(k - spot) > window_pts:
            continue
        call_bid += float(bucket.get("call_bid_size", 0) or 0)
        call_ask += float(bucket.get("call_ask_size", 0) or 0)
        put_bid += float(bucket.get("put_bid_size", 0) or 0)
        put_ask += float(bucket.get("put_ask_size", 0) or 0)

    # Call imbalance: bid > ask = buyers accumulating calls (bullish)
    call_imb = call_bid - call_ask
    # Put imbalance: bid > ask = buyers accumulating puts (bearish)
    put_imb = put_bid - put_ask

    # Net: call buying pressure minus put buying pressure
    # Positive = more call demand than put demand = bullish flow
    net = call_imb - put_imb

    # Normalize to -1..+1
    total = call_bid + call_ask + put_bid + put_ask
    normalized = net / total if total > 0 else 0
    normalized = max(-1.0, min(1.0, normalized))

    if normalized > 0.3:
        label = "strong_call_demand"
    elif normalized > 0.1:
        label = "call_leaning"
    elif normalized < -0.3:
        label = "strong_put_demand"
    elif normalized < -0.1:
        label = "put_leaning"
    else:
        label = "balanced"

    return {
        "net_imbalance": round(net),
        "normalized": round(normalized, 3),
        "label": label,
        "call_imbalance": round(call_imb),
        "put_imbalance": round(put_imb),
    }


def atm_flow_window_totals(
    exposures_by_strike: dict,
    spot: float,
    *,
    window_pts: float = 5.0,
) -> dict[str, float | int]:
    """
    Near-ATM aggregates used for option flow imbalance (same strike window as
    flow_imbalance_normalized_with_fallback). For inspection / debugging only.
    """
    empty: dict[str, float | int] = {
        "strikes_in_window": 0,
        "call_vol": 0.0,
        "put_vol": 0.0,
        "call_bid": 0.0,
        "call_ask": 0.0,
        "put_bid": 0.0,
        "put_ask": 0.0,
    }
    if not exposures_by_strike or not spot:
        return empty
    spot_f = float(spot)
    call_bid = call_ask = put_bid = put_ask = 0.0
    call_vol = put_vol = 0.0
    n = 0
    for strike, bucket in exposures_by_strike.items():
        try:
            k = float(strike)
        except (TypeError, ValueError):
            continue
        if abs(k - spot_f) > window_pts:
            continue
        n += 1
        b = bucket or {}
        call_bid += float(b.get("call_bid_size", 0) or 0)
        call_ask += float(b.get("call_ask_size", 0) or 0)
        put_bid += float(b.get("put_bid_size", 0) or 0)
        put_ask += float(b.get("put_ask_size", 0) or 0)
        call_vol += float(b.get("call_volume", 0) or 0)
        put_vol += float(b.get("put_volume", 0) or 0)
    return {
        "strikes_in_window": n,
        "call_vol": call_vol,
        "put_vol": put_vol,
        "call_bid": call_bid,
        "call_ask": call_ask,
        "put_bid": put_bid,
        "put_ask": put_ask,
    }


def flow_imbalance_normalized_with_fallback(
    exposures_by_strike: dict,
    spot: float,
    *,
    window_pts: float = 5.0,
) -> tuple[float, str]:
    """
    Prefer book imbalance (bid/ask sizes) near ATM; if combined book size is ~0,
    use call vs put volume ratio in the same window (archived chains often lack sizes).

    Returns (normalized in [-1, 1], source) where source is 'book', 'volume', or 'none'.
    """
    sums = atm_flow_window_totals(exposures_by_strike, spot, window_pts=window_pts)
    if not exposures_by_strike or not spot:
        return 0.0, "none"
    spot_f = float(spot)
    call_bid = float(sums["call_bid"])
    call_ask = float(sums["call_ask"])
    put_bid = float(sums["put_bid"])
    put_ask = float(sums["put_ask"])
    call_vol = float(sums["call_vol"])
    put_vol = float(sums["put_vol"])
    total_book = call_bid + call_ask + put_bid + put_ask
    if total_book >= 1.0:
        r = compute_option_flow_imbalance(exposures_by_strike, spot_f, window_pts=window_pts)
        return float(r.get("normalized") or 0.0), "book"
    tot_v = call_vol + put_vol
    if tot_v > 0:
        x = (call_vol - put_vol) / tot_v
        x = max(-1.0, min(1.0, x))
        return round(x, 3), "volume"
    return 0.0, "none"


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
    if not exposures_by_strike or not spot:
        return {"score": 0, "direction": "neutral", "label": "no_data",
                "vol_oi_component": 0, "flow_component": 0, "concentration_component": 0}

    # Gather data near ATM
    vol_total = oi_total = 0.0
    call_bid = call_ask = put_bid = put_ask = 0.0
    strike_activity = []

    for strike, bucket in exposures_by_strike.items():
        k = float(strike)
        if abs(k - spot) > window_pts:
            continue
        cv = float(bucket.get("call_volume", 0) or 0)
        pv = float(bucket.get("put_volume", 0) or 0)
        co = float(bucket.get("call_oi", 0) or 0)
        po = float(bucket.get("put_oi", 0) or 0)
        vol_total += cv + pv
        oi_total += co + po
        call_bid += float(bucket.get("call_bid_size", 0) or 0)
        call_ask += float(bucket.get("call_ask_size", 0) or 0)
        put_bid += float(bucket.get("put_bid_size", 0) or 0)
        put_ask += float(bucket.get("put_ask_size", 0) or 0)
        strike_activity.append(cv + pv)

    # Component 1: Volume/OI (0-40)
    vol_oi = vol_total / oi_total if oi_total > 0 else 0
    vol_oi_score = min(40, vol_oi / 2.0 * 40)  # ratio 2.0 = max score

    # Component 2: Flow imbalance (0-40)
    call_imb = call_bid - call_ask
    put_imb = put_bid - put_ask
    net_flow = call_imb - put_imb
    total_size = call_bid + call_ask + put_bid + put_ask
    flow_ratio = abs(net_flow) / total_size if total_size > 0 else 0
    flow_score = min(40, flow_ratio / 0.5 * 40)  # 50% imbalance = max

    # Component 3: Concentration (0-20)
    # If activity is concentrated at 1-2 strikes vs spread across many
    conc_score = 0
    if strike_activity and max(strike_activity) > 0:
        top_share = max(strike_activity) / sum(strike_activity) if sum(strike_activity) > 0 else 0
        conc_score = min(20, top_share * 40)  # 50%+ in one strike = max

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
