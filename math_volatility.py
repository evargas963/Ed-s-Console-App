"""
math_volatility.py
Volatility-derived transforms — expected move, IV extraction,
movement envelopes, and time/session context.

Phase 2 extraction from math_exposure.py per Extraction Blueprint v1.
"""
from __future__ import annotations

from typing import List
import math
import logging

from math_exposure_core import MISSING_GREEK_SENTINEL, _f, _nearest_strike

log = logging.getLogger(__name__)


# ── Constants ─────────────────────────────────────────────────────────────────

BUCKET_OPEN      = "open"
BUCKET_MORNING   = "morning"
BUCKET_MIDDAY    = "midday"
BUCKET_AFTERNOON = "afternoon"
BUCKET_CLOSE     = "close"

EM_STRADDLE_MULT = 0.85

TRADING_DAYS_PER_YEAR = 252
TRADING_HOURS_PER_DAY = 6.5

# ── ATM strike / IV extraction ────────────────────────────────────────────────

def _spot_atm_strike(strikes: List[float], spot: float) -> float | None:
    if not strikes:
        return None
    return _nearest_strike(strikes, spot)

def _extract_iv_for_strike(contracts: List[dict], strike: float) -> tuple[float | None, float | None]:
    """
    Returns (call_iv_mean, put_iv_mean) for contracts at the given strike.
    Uses ct['volatility'] if present (Schwab often uses 'volatility').
    """
    c_vals = []
    p_vals = []
    for ct in contracts:
        s = _f(ct.get("strikePrice"))
        if s is None or float(s) != float(strike):
            continue
        iv = _f(ct.get("volatility"))
        if iv is None or iv <= 0 or iv == MISSING_GREEK_SENTINEL or not math.isfinite(iv):
            continue
        side = (ct.get("putCall") or "").upper()
        if side == "CALL":
            c_vals.append(iv)
        elif side == "PUT":
            p_vals.append(iv)
    c_iv = (sum(c_vals) / len(c_vals)) if c_vals else None
    p_iv = (sum(p_vals) / len(p_vals)) if p_vals else None
    return c_iv, p_iv


# ── Charm intraday context ───────────────────────────────────────────────────

def charm_intraday_context(charm_result: dict, spot: float, *, et_hour: int | None = None) -> dict:
    net = charm_result.get("net_charm_daily", 0.0)
    direction = charm_result.get("charm_direction", "neutral")
    pin = charm_result.get("drift_toward")
    used = charm_result.get("contracts_used", 0)
    if used == 0: return {"available": False, "banner_line": "", "card_text": ""}
    net_deltas = abs(net) / 100.0
    if et_hour is not None:
        if et_hour >= 15:   urgency = "🔴 FINAL HOUR"; note = "Charm at maximum — dealer unwind accelerating into close."
        elif et_hour >= 14: urgency = "🟠 POST 2PM";   note = "Charm accelerating — reduce fade size, no new entries after 3pm."
        elif et_hour >= 12: urgency = "🟡 MIDDAY";     note = "Charm building — monitor drift toward pin."
        else:               urgency = "🟢 MORNING";    note = "Charm minimal — full position sizing normal."
    else:
        urgency = note = ""
    if direction == "buying":
        dir_text  = f"Charm driving +{net_deltas:.0f}Δ dealer BUYING into close"
        drift_txt = f"upward drift toward {pin:.0f}" if pin and pin > spot else "upward drift"
    elif direction == "selling":
        dir_text  = f"Charm driving {net_deltas:.0f}Δ dealer SELLING into close"
        drift_txt = f"downward drift toward {pin:.0f}" if pin and pin < spot else "downward drift"
    else:
        dir_text  = "Charm balanced — no dominant drift pressure"
        drift_txt = f"pin at {pin:.0f}" if pin else "current level"
    banner = f"{urgency}  ⏱ Charm: {dir_text} → expect {drift_txt}" if urgency else f"⏱ Charm: {dir_text} → expect {drift_txt}"
    card   = (f"{note}  " if note else "") + f"Net charm: {'+' if net>=0 else ''}{net:.2f} Δ-equiv/day. {dir_text}. Expect {drift_txt} into close."
    return {"available": True, "banner_line": banner, "card_text": card,
            "net_deltas": net_deltas, "direction": direction, "urgency": urgency, "drift_toward": pin}


# ── Session / VIX bucketing ──────────────────────────────────────────────────

def session_bucket(et_hour: int, et_minute: int) -> str:
    mins = et_hour * 60 + et_minute
    if mins < 570:   return BUCKET_MORNING
    if mins < 600:   return BUCKET_OPEN
    if mins < 690:   return BUCKET_MORNING
    if mins < 810:   return BUCKET_MIDDAY
    if mins < 900:   return BUCKET_AFTERNOON
    if mins < 960:   return BUCKET_CLOSE
    return BUCKET_MORNING


# VIX tier cuts — single authority shared between math_volatility.vix_bucket (SignalInput
# "vix_*" labels) and planes.l1_thresholds._vol_regime (adaptive-materiality regime token).
# Cuts: <15 low, <20 normal, <30 elevated, otherwise high. None when vix_level is missing /
# non-positive / NaN — callers compose their own "unknown" fallback semantics.
VIX_TIER_LOW_MAX: float = 15.0
VIX_TIER_NORMAL_MAX: float = 20.0
VIX_TIER_ELEVATED_MAX: float = 30.0


def vix_tier_token(vix_level: float | None) -> str | None:
    """
    Canonical VIX tier — single source for 15/20/30 cuts used across vix_bucket and
    the L1 adaptive-materiality engine.

    Returns "low" / "normal" / "elevated" / "high", or None when vix_level is None,
    non-positive, or NaN. Callers add their own prefix / fallback as needed.
    """
    if vix_level is None:
        return None
    try:
        v = float(vix_level)
    except (TypeError, ValueError):
        return None
    if v != v or v <= 0:  # NaN or non-positive
        return None
    if v < VIX_TIER_LOW_MAX:
        return "low"
    if v < VIX_TIER_NORMAL_MAX:
        return "normal"
    if v < VIX_TIER_ELEVATED_MAX:
        return "elevated"
    return "high"


def vix_bucket(vix_level: float | None) -> str | None:
    """SignalInput.vix_bucket — 'vix_low' / 'vix_normal' / 'vix_elevated' / 'vix_high' or None."""
    tier = vix_tier_token(vix_level)
    return f"vix_{tier}" if tier is not None else None


# ── Expected move calculations ───────────────────────────────────────────────

def compute_expected_move_straddle(atm_call_mark: float, atm_put_mark: float,
                                    today_open: float) -> dict:
    """Expected move from ATM straddle price.

    Formula: EM = (ATM_call_mark + ATM_put_mark) × 0.85
    Upper/Lower = today's open ± EM

    Args:
        atm_call_mark: ATM call mid/mark price
        atm_put_mark:  ATM put mid/mark price
        today_open:    today's opening price (anchor for EM range)

    Returns dict with straddle, em_pts, upper, lower.
    Returns None values if inputs are invalid.
    """
    if not all(v and v > 0 for v in [atm_call_mark, atm_put_mark, today_open]):
        return {"straddle": None, "em_pts": None, "upper": None, "lower": None,
                "error": "Missing ATM straddle or open price"}

    straddle = round(atm_call_mark + atm_put_mark, 2)
    em_pts = round(straddle * EM_STRADDLE_MULT, 2)
    upper = round(today_open + em_pts, 2)
    lower = round(today_open - em_pts, 2)

    return {
        "straddle": straddle,
        "em_pts": em_pts,
        "upper": upper,
        "lower": lower,
        "error": "",
    }

def compute_expected_move_iv(spot: float, atm_iv: float,
                              hours_remaining: float) -> dict:
    """Expected move from IV with intraday time decay.

    Formula: EM = spot × (IV/100) × sqrt(hours_remaining / (252 × 6.5))

    This produces a SHRINKING expected move throughout the day — theta decay
    in real-time. At 10 AM with 6 hours left, EM is wide. At 3 PM with 1 hour
    left, EM is narrow. This is more accurate than the straddle method for
    gauging remaining risk.

    Args:
        spot:            current price
        atm_iv:          ATM implied volatility (e.g. 26.1 for 26.1%)
        hours_remaining: hours until market close (e.g. 6.0 at 10:00 AM)

    Returns dict with em_pts, upper, lower.
    """
    import math

    if not spot or spot <= 0 or not atm_iv or atm_iv <= 0:
        return {"em_pts": None, "upper": None, "lower": None,
                "error": "Missing spot or IV"}

    if hours_remaining <= 0:
        return {"em_pts": None, "upper": None, "lower": None,
                "error": "session_hours_unavailable"}

    annualized_hours = TRADING_DAYS_PER_YEAR * TRADING_HOURS_PER_DAY
    em_pts = round(spot * (atm_iv / 100.0) * math.sqrt(hours_remaining / annualized_hours), 2)
    upper = round(spot + em_pts, 2)
    lower = round(spot - em_pts, 2)

    return {
        "em_pts": em_pts,
        "upper": upper,
        "lower": lower,
        "hours_remaining": round(hours_remaining, 2),
        "error": "",
    }


def resolve_kl_em_anchor(em_straddle: dict, em_iv: dict) -> str:
    """Which EM path KEY LEVELS and Monte Carlo must share."""
    if em_straddle.get("upper") is not None:
        return "straddle_open"
    if em_iv.get("upper") is not None:
        return "iv_spot"
    return "unavailable"


def iv_percent_from_em_pts(spot: float, em_pts: float, hours_remaining: float) -> float | None:
    """Invert IV-EM formula: em_pts = spot × (iv/100) × sqrt(h / annualized_hours)."""
    if not (spot and spot > 0 and em_pts and em_pts > 0 and hours_remaining and hours_remaining > 0):
        return None
    annualized_hours = TRADING_DAYS_PER_YEAR * TRADING_HOURS_PER_DAY
    denom = spot * math.sqrt(hours_remaining / annualized_hours)
    if denom <= 0:
        return None
    iv = 100.0 * em_pts / denom
    return iv if iv > 0 and math.isfinite(iv) else None


def resolve_mc_iv_for_kl_em_anchor(
    *,
    kl_em_anchor: str,
    atm_iv: float | None,
    spot: float | None,
    em_straddle: dict,
    hours_remaining: float | None,
) -> tuple[float | None, str]:
    """Monte Carlo IV (percent) aligned with ``kl_em_anchor`` — not raw chain ATM when straddle wins."""
    if kl_em_anchor == "iv_spot":
        if atm_iv is not None and atm_iv > 0:
            return float(atm_iv), "mc_iv_kl_anchor_iv_spot"
        return None, "unavailable"
    if kl_em_anchor == "straddle_open":
        em_pts = _f(em_straddle.get("em_pts"))
        if spot is not None and em_pts is not None and hours_remaining is not None:
            iv = iv_percent_from_em_pts(float(spot), float(em_pts), float(hours_remaining))
            if iv is not None:
                return iv, "mc_iv_kl_anchor_straddle_em_pts"
        return None, "unavailable"
    return None, "unavailable"


def compute_em_progress(spot: float, today_open: float,
                         em_upper: float, em_lower: float) -> dict:
    """How far through the expected move has price traveled.

    Progress = abs(spot - open) / em_half_range × 100

    Returns:
        progress_pct: 0-100+ (>100 = breached)
        breached: bool
        direction: 'up' or 'down' from open
        severity: 'normal', 'warning', 'danger', 'breached'
    """
    if not all(v is not None for v in [spot, today_open, em_upper, em_lower]):
        return {
            "progress_pct": None,
            "breached": None,
            "direction": None,
            "severity": None,
            "error": "Missing data",
        }

    em_half = (em_upper - em_lower) / 2.0
    if em_half <= 0:
        return {
            "progress_pct": None,
            "breached": None,
            "direction": None,
            "severity": None,
            "error": "EM range is zero",
        }

    move = spot - today_open
    direction = "up" if move >= 0 else "down"
    progress = round(abs(move) / em_half * 100, 1)
    breached = progress > 100.0

    if progress <= 60:
        severity = "normal"
    elif progress <= 85:
        severity = "warning"
    elif progress <= 100:
        severity = "danger"
    else:
        severity = "breached"

    return {
        "progress_pct": progress,
        "breached": breached,
        "direction": direction,
        "severity": severity,
        "move_pts": round(move, 2),
        "error": "",
    }


# ── IV Skew ──────────────────────────────────────────────────────────────────

def compute_iv_skew(contracts: List[dict], spot: float) -> dict:
    """
    Implied Volatility Skew = IV_put − IV_call at ATM strike.

    Per Derived Formula Dictionary Section 6:
        Skew = IV_put − IV_call
        Positive skew → downside hedging demand dominates.
        Negative skew → upside speculation dominates.

    Args:
        contracts: list of option contract dicts from Schwab API
        spot:      current underlying price

    Returns dict with skew, atm_call_iv, atm_put_iv, interpretation.
    """
    if not contracts or not spot or spot <= 0:
        return {
            "skew": None,
            "atm_call_iv": None,
            "atm_put_iv": None,
            "interpretation": None,
        }

    # Find ATM strike — gate float() so a non-numeric strikePrice cannot crash the iter
    strikes_set: set[float] = set()
    for ct in contracts:
        sp = ct.get("strikePrice")
        if sp is None:
            continue
        try:
            strikes_set.add(float(sp))
        except (TypeError, ValueError):
            continue
    strikes = sorted(strikes_set)
    if not strikes:
        return {
            "skew": None,
            "atm_call_iv": None,
            "atm_put_iv": None,
            "interpretation": None,
        }

    atm_k = _nearest_strike(strikes, spot)
    call_iv, put_iv = _extract_iv_for_strike(contracts, atm_k)

    if call_iv is None or put_iv is None:
        return {
            "skew": None,
            "atm_call_iv": call_iv,
            "atm_put_iv": put_iv,
            "interpretation": None,
        }

    skew = round(put_iv - call_iv, 2)

    if skew > 3.0:
        interp = "strong_put_demand"
    elif skew > 1.0:
        interp = "mild_put_demand"
    elif skew < -3.0:
        interp = "strong_call_demand"
    elif skew < -1.0:
        interp = "mild_call_demand"
    else:
        interp = "balanced"

    return {
        "skew": skew,
        "atm_call_iv": round(call_iv, 2),
        "atm_put_iv": round(put_iv, 2),
        "atm_strike": atm_k,
        "interpretation": interp,
    }


# ── Realized Volatility ─────────────────────────────────────────────────────

def compute_realized_vol(closes: List[float], *, annualize: bool = True) -> float | None:
    """
    Realized (historical) volatility from close prices.

    Formula: RV = std(log_returns) × sqrt(annualization_factor)

    For 5-min bars: annualization = sqrt(252 × 78) where 78 = bars per RTH day
    For daily bars: annualization = sqrt(252)

    Args:
        closes:    list of close prices (chronological order)
        annualize: if True, annualize; if False, return per-bar vol

    Returns annualized realized volatility as percentage (e.g. 18.5 for 18.5%),
    or None if insufficient data.
    """
    if not closes or len(closes) < 5:
        return None

    import numpy as np
    prices = np.array(closes, dtype=np.float64)
    prices = prices[prices > 0]
    if len(prices) < 5:
        return None

    log_returns = np.diff(np.log(prices))
    if len(log_returns) < 3:
        return None

    vol = float(np.std(log_returns, ddof=1))
    if annualize:
        # Assume 5-min bars: 78 bars per 6.5hr RTH day × 252 days
        bars_per_year = 252 * 78
        vol *= math.sqrt(bars_per_year)

    return round(vol * 100, 2)  # as percentage


# ── ATR (Average True Range) ────────────────────────────────────────────────

def compute_atr(candles: list, *, period: int = 14) -> float | None:
    """
    Average True Range from OHLC candles.

    Formula:
        TR = max(high - low, abs(high - prev_close), abs(low - prev_close))
        ATR = SMA(TR, period)

    Args:
        candles:  list of candle objects/dicts with o/h/l/c or open/high/low/close
        period:   ATR lookback period (default 14)

    Returns ATR in price points, or None if insufficient data.
    """
    if not candles or len(candles) < period + 1:
        return None

    def _get(candle, *keys):
        for k in keys:
            v = getattr(candle, k, None) if not isinstance(candle, dict) else candle.get(k)
            if v is not None:
                try:
                    return float(v)
                except (ValueError, TypeError):
                    continue
        return None

    trs = []
    prev_close = None
    for candle in candles:
        h = _get(candle, 'h', 'high')
        l = _get(candle, 'l', 'low')
        c = _get(candle, 'c', 'close')
        if h is None or l is None or c is None:
            prev_close = c
            continue

        if prev_close is not None:
            tr = max(h - l, abs(h - prev_close), abs(l - prev_close))
            trs.append(tr)

        prev_close = c

    if len(trs) < period:
        return None

    atr = sum(trs[-period:]) / period
    return round(atr, 4)


# ── IV Rank and IV Percentile ────────────────────────────────────────────────

def compute_iv_rank(current_iv: float, iv_history: List[float]) -> float | None:
    """
    IV Rank = (Current IV − 52w Low) / (52w High − 52w Low) × 100

    Tells you where current IV sits relative to its range.
    0 = at the yearly low. 100 = at the yearly high.

    Args:
        current_iv:  current ATM IV (percentage, e.g. 26.1)
        iv_history:  list of historical IV readings (at least 20)

    Returns IV Rank as 0-100 score, or None if insufficient history.
    """
    if current_iv is None or not iv_history or len(iv_history) < 20:
        return None

    valid = [v for v in iv_history if v is not None and v > 0]
    if len(valid) < 20:
        return None

    iv_low = min(valid)
    iv_high = max(valid)
    if iv_high == iv_low:
        return 50.0  # no range

    rank = (current_iv - iv_low) / (iv_high - iv_low) * 100
    return round(max(0, min(100, rank)), 1)


def compute_iv_percentile(current_iv: float, iv_history: List[float]) -> float | None:
    """
    IV Percentile = % of days where IV was LOWER than current IV.

    Tells you how often IV has been cheaper than now.
    90th percentile = IV is higher than 90% of historical readings.

    Args:
        current_iv:  current ATM IV (percentage, e.g. 26.1)
        iv_history:  list of historical IV readings (at least 20)

    Returns IV Percentile as 0-100 score, or None if insufficient history.
    """
    if current_iv is None or not iv_history or len(iv_history) < 20:
        return None

    valid = [v for v in iv_history if v is not None and v > 0]
    if len(valid) < 20:
        return None

    below = sum(1 for v in valid if v < current_iv)
    percentile = below / len(valid) * 100
    return round(percentile, 1)


# ── Volatility Envelope (ATR Bands) ─────────────────────────────────────────

def compute_volatility_envelope(
    spot: float,
    atr: float | None,
    *,
    multiplier: float = 1.5,
) -> dict:
    """
    Volatility envelope — ATR-based bands around current price.

    Upper = spot + ATR × multiplier
    Lower = spot - ATR × multiplier

    Tells the engine whether price is inside normal movement range
    or has entered volatility expansion.

    Args:
        spot:       current price
        atr:        average true range (from compute_atr)
        multiplier: band width multiplier (default 1.5 ATR)

    Returns dict with upper, lower, width_pts, price_position ('inside', 'upper_band', 'lower_band').
    """
    if not spot or spot <= 0 or not atr or atr <= 0:
        return {"upper": None, "lower": None, "width_pts": None, "position": "unknown"}

    width = atr * multiplier
    upper = round(spot + width, 2)
    lower = round(spot - width, 2)

    return {
        "upper": upper,
        "lower": lower,
        "width_pts": round(width * 2, 2),
        "atr": round(atr, 4),
        "multiplier": multiplier,
    }



# ── GARCH(1,1) Volatility Forecasting ────────────────────────────────────────
#
# Per consultant Phase 2 recommendation + corrections:
#   - Uses consistent 5-minute log returns
#   - Produces per-bar forward sigma forecast (horizon bars)
#   - Blended with IV + RV before feeding MC (don't fully replace)
#   - Sigma floor prevents collapse
#   - Regime multiplier applied downstream in monte_carlo.py (already built)
#
# GARCH(1,1) model:
#   sigma²[t] = omega + alpha * epsilon²[t-1] + beta * sigma²[t-1]
#
# where:
#   omega = long-run variance weight
#   alpha = shock reactivity (how much yesterday's surprise matters)
#   beta  = persistence (how sticky is current vol level)
#   alpha + beta < 1 for stationarity
#
# No ML training needed — parameters estimated analytically from recent returns.

import math as _math

# Default GARCH(1,1) parameters — reasonable starting values for intraday equities.
# These can be calibrated later from accumulated data.
GARCH_OMEGA_DEFAULT = 0.00001   # baseline variance per bar
GARCH_ALPHA_DEFAULT = 0.10      # shock reactivity
GARCH_BETA_DEFAULT  = 0.85      # persistence
# alpha + beta = 0.95 < 1.0 (stationary, moderate persistence)

# Blending weights for GARCH + IV + RV (per consultant: don't fully replace)
GARCH_BLEND_GARCH = 0.60
GARCH_BLEND_IV    = 0.25
GARCH_BLEND_RV    = 0.15

# Minimum history needed for GARCH estimation
GARCH_MIN_BARS = 20


def estimate_garch_params(returns: list, max_iter: int = 50) -> tuple:
    """
    Estimate GARCH(1,1) parameters from a return series using
    variance targeting + simple moment matching.

    This is not full MLE — it's a fast analytical approximation
    suitable for real-time intraday use. Full MLE can be added later
    when scipy is available and calibration data is deeper.

    Args:
        returns: list of log returns (5-min bars)
        max_iter: unused (reserved for future MLE)

    Returns (omega, alpha, beta, long_run_var)
    """
    if not returns or len(returns) < GARCH_MIN_BARS:
        return GARCH_OMEGA_DEFAULT, GARCH_ALPHA_DEFAULT, GARCH_BETA_DEFAULT, None

    n = len(returns)
    mean_r = sum(returns) / n
    # Unconditional variance
    var = sum((r - mean_r) ** 2 for r in returns) / (n - 1)

    if var <= 0:
        return GARCH_OMEGA_DEFAULT, GARCH_ALPHA_DEFAULT, GARCH_BETA_DEFAULT, None

    # Moment-based alpha estimation:
    # Measure how much variance clusters (autocorrelation of squared returns)
    sq_returns = [(r - mean_r) ** 2 for r in returns]
    sq_mean = sum(sq_returns) / n

    # Lag-1 autocorrelation of squared returns → proxy for alpha + beta
    if n > 2 and sq_mean > 0:
        cov_lag1 = sum(
            (sq_returns[i] - sq_mean) * (sq_returns[i - 1] - sq_mean)
            for i in range(1, n)
        ) / (n - 1)
        var_sq = sum((s - sq_mean) ** 2 for s in sq_returns) / (n - 1)
        rho1 = cov_lag1 / var_sq if var_sq > 0 else 0
    else:
        rho1 = 0

    # Constrain rho1 to reasonable range
    rho1 = max(0.0, min(0.98, rho1))

    # Split persistence: alpha = reactivity, beta = stickiness
    # Empirical split: alpha ≈ 20% of total persistence, beta ≈ 80%
    total_persist = max(0.5, min(0.98, rho1 + 0.30))  # nudge up from raw autocorrelation
    alpha = total_persist * 0.15  # shock component
    beta = total_persist * 0.85   # persistence component

    # Clamp
    alpha = max(0.02, min(0.25, alpha))
    beta = max(0.50, min(0.95, beta))

    # Ensure stationarity
    if alpha + beta >= 0.999:
        beta = 0.999 - alpha

    # Variance targeting: omega = long_run_var * (1 - alpha - beta)
    omega = var * (1.0 - alpha - beta)
    omega = max(1e-8, omega)

    return omega, alpha, beta, var


def compute_garch_forecast(
    closes: list,
    horizon: int = 13,
    *,
    omega: float | None = None,
    alpha: float | None = None,
    beta: float | None = None,
) -> list | None:
    """
    GARCH(1,1) conditional variance forecast for the next `horizon` bars.

    Computes the forward sigma (standard deviation) per bar, capturing
    volatility clustering: a recent spike means the next few bars will
    likely be volatile too, decaying back to the long-run mean.

    Args:
        closes: list of 5-min close prices (at least GARCH_MIN_BARS + 1)
        horizon: number of bars to forecast forward (default 13 = 65 min)
        omega/alpha/beta: override GARCH params (None = estimate from data)

    Returns:
        List of `horizon` per-bar sigma values (as price-fraction, not annualized),
        or None if insufficient data.
    """
    if not closes or len(closes) < GARCH_MIN_BARS + 1:
        return None

    # Step 1: compute log returns from 5-min closes
    returns = []
    for i in range(1, len(closes)):
        if closes[i] > 0 and closes[i - 1] > 0:
            returns.append(_math.log(closes[i] / closes[i - 1]))

    if len(returns) < GARCH_MIN_BARS:
        return None

    # Step 2: estimate or use provided parameters
    if omega is None or alpha is None or beta is None:
        _omega, _alpha, _beta, _lrv = estimate_garch_params(returns)
    else:
        _omega, _alpha, _beta = omega, alpha, beta
        _lrv = _omega / (1.0 - _alpha - _beta) if (_alpha + _beta) < 1.0 else None

    # Step 3: run GARCH filter on historical returns to get current sigma²
    sigma_sq = sum(r ** 2 for r in returns) / len(returns)  # initialize with sample variance

    for r in returns:
        sigma_sq = _omega + _alpha * (r ** 2) + _beta * sigma_sq

    # sigma_sq now represents the conditional variance at the most recent bar

    # Step 4: forecast forward
    # GARCH(1,1) multi-step forecast:
    #   sigma²[t+k] = long_run_var + (alpha + beta)^k * (sigma²[t] - long_run_var)
    # This shows vol decaying back to long-run mean over the horizon.
    long_run_var = _omega / (1.0 - _alpha - _beta) if (_alpha + _beta) < 1.0 else sigma_sq

    forecasts = []
    current_var = sigma_sq
    persist = _alpha + _beta

    for k in range(horizon):
        # One-step ahead: sigma²[t+1] = omega + (alpha + beta) * sigma²[t]
        # Which is equivalent to: long_run_var + persist^k * (current - long_run)
        forecast_var = long_run_var + (persist ** (k + 1)) * (sigma_sq - long_run_var)
        forecast_var = max(1e-10, forecast_var)  # prevent negative/zero
        forecasts.append(_math.sqrt(forecast_var))

    return forecasts


def blend_garch_sigma(
    garch_sigmas: list,
    iv: float | None,
    realized_vol: float | None,
    spot: float | None = None,
) -> list:
    """
    Blend GARCH per-bar forecasts with IV and realized vol.

    Per consultant requirement: don't fully replace existing sigma.
    Weights: 60% GARCH + 25% IV + 15% realized vol.
    Includes sigma floor at 0.5 × realized_vol to prevent collapse.

    Args:
        garch_sigmas: list of per-bar sigma values from compute_garch_forecast
        iv:           annualized implied volatility (decimal, e.g. 0.20)
        realized_vol: annualized realized volatility (decimal)
        spot:         current price (for annualization context)

    Returns:
        List of blended per-bar sigma values (same length as garch_sigmas).
    """
    # Convert IV and RV from annualized to per-bar scale
    # Per-bar: sigma_bar = sigma_annual * sqrt(dt)
    # dt = 5 minutes / (252 * 6.5 * 60 minutes)
    minutes_per_year = 252 * 6.5 * 60
    dt = 5.0 / minutes_per_year
    sqrt_dt = _math.sqrt(dt)

    iv_bar = (iv * sqrt_dt) if (iv is not None and iv > 0) else None
    rv_bar = (realized_vol * sqrt_dt) if (realized_vol is not None and realized_vol > 0) else None

    # Sigma floor: 0.5 × realized vol per bar (prevents GARCH collapse)
    sigma_floor = (rv_bar * 0.5) if rv_bar else 0.00001

    blended = []
    for g_sigma in garch_sigmas:
        # Blend available components
        if iv_bar is not None and rv_bar is not None:
            s = GARCH_BLEND_GARCH * g_sigma + GARCH_BLEND_IV * iv_bar + GARCH_BLEND_RV * rv_bar
        elif iv_bar is not None:
            s = 0.70 * g_sigma + 0.30 * iv_bar
        elif rv_bar is not None:
            s = 0.75 * g_sigma + 0.25 * rv_bar
        else:
            s = g_sigma

        # Apply floor
        s = max(s, sigma_floor)

        blended.append(round(s, 8))

    return blended


# ── Theoretical IV Model Spread ──────────────────────────────────────────────

def compute_iv_model_spread(
    contracts: list,
    spot: float,
    *,
    atm_window: float = 3.0,
) -> dict:
    """
    Spread between market IV and Schwab's theoretical (model) IV at ATM.

    Market IV > Theoretical IV → fear premium (market pricing in more risk than model)
    Market IV < Theoretical IV → market underpricing risk (complacency)

    Args:
        contracts: list of contract dicts with 'volatility' and 'theoreticalVolatility'
        spot: current price
        atm_window: how far from spot to consider ATM

    Returns dict with spread, interpretation.
    """
    if not contracts or not spot:
        return {"spread": None, "label": None, "market_iv": None, "model_iv": None}

    market_ivs = []
    model_ivs = []

    for ct in contracts:
        strike = ct.get("strikePrice")
        if strike is None:
            continue
        try:
            k = float(strike)
        except (ValueError, TypeError):
            continue
        if abs(k - spot) > atm_window:
            continue

        mkt_iv = ct.get("volatility")
        mdl_iv = ct.get("theoreticalVolatility")
        if mkt_iv is not None and mdl_iv is not None:
            try:
                market_ivs.append(float(mkt_iv))
                model_ivs.append(float(mdl_iv))
            except (ValueError, TypeError):
                continue

    if not market_ivs or not model_ivs:
        return {"spread": None, "label": None, "market_iv": None, "model_iv": None}

    avg_market = sum(market_ivs) / len(market_ivs)
    avg_model = sum(model_ivs) / len(model_ivs)
    spread = avg_market - avg_model  # positive = fear premium

    if spread > 3.0:
        label = "high_fear_premium"
    elif spread > 1.0:
        label = "mild_fear_premium"
    elif spread < -3.0:
        label = "complacency"
    elif spread < -1.0:
        label = "mild_underpricing"
    else:
        label = "fair"

    return {
        "spread": round(spread, 2),
        "label": label,
        "market_iv": round(avg_market, 2),
        "model_iv": round(avg_model, 2),
    }
