"""
math_volatility.py
Volatility-derived transforms — expected move, IV extraction,
movement envelopes, and time/session context.

Phase 2 extraction from math_exposure.py per Extraction Blueprint v1.
"""
from __future__ import annotations

from typing import List

from math_exposure_core import (
    MISSING_GREEK_SENTINEL,
    _f,
)



# ── Constants ─────────────────────────────────────────────────────────────────




# ── RC-358: 25-delta risk reversal (skew steepness) ──────────────────────────

#: A wing quote only counts as "the 25Δ option" if its delta is within this distance of
#: the ±0.25 target; farther than this and the chain has no usable 25Δ wing — fail closed.
RR25_DELTA_TOL = 0.10


def compute_25d_risk_reversal(contracts: List[dict]) -> dict | None:
    """RC-358: IV(25Δ call) − IV(25Δ put) on the front expiry, in vol points.

    The skew-steepness read: SPX-typical is −2..−4 (puts richer); deterioration toward
    −6 and beyond = the put bid building — the same-session confirm for a Gamma Support
    Floor breach. Selection: the front expiry (smallest usable dte ≥ 0), then the call
    whose delta is nearest +0.25 and the put nearest −0.25, each tolerance-gated
    (|delta − target| ≤ RR25_DELTA_TOL, else the wing is unusable). Schwab `volatility`
    is in PERCENT and stays in vol points here. FAIL-CLOSED: None when either wing is
    missing/unusable — never a fabricated skew.
    """
    if not contracts:
        return None
    usable: list[tuple[int, str, float, float]] = []   # (dte, side, delta, iv)
    for ct in contracts:
        if not isinstance(ct, dict):
            continue
        dte = _f(ct.get("daysToExpiration"))
        delta = _f(ct.get("delta"))
        iv = _f(ct.get("volatility"))
        side = (ct.get("putCall") or "").upper().strip()
        if dte is None or dte < 0 or delta is None or iv is None or iv <= 0:
            continue
        if delta == MISSING_GREEK_SENTINEL or iv == MISSING_GREEK_SENTINEL:
            continue
        if side not in ("CALL", "PUT"):
            continue
        usable.append((int(dte), side, float(delta), float(iv)))
    if not usable:
        return None
    front_dte = min(u[0] for u in usable)
    front = [u for u in usable if u[0] == front_dte]
    calls = [u for u in front if u[1] == "CALL"]
    puts = [u for u in front if u[1] == "PUT"]
    if not calls or not puts:
        return None
    c = min(calls, key=lambda u: abs(u[2] - 0.25))
    p = min(puts, key=lambda u: abs(u[2] - (-0.25)))
    if abs(c[2] - 0.25) > RR25_DELTA_TOL or abs(p[2] - (-0.25)) > RR25_DELTA_TOL:
        return None
    return {
        "rr_pts": round(c[3] - p[3], 2),
        "call_iv_25d": round(c[3], 2),
        "put_iv_25d": round(p[3], 2),
        "dte": front_dte,
    }


# ── ATM strike / IV extraction ────────────────────────────────────────────────




# ── Charm intraday context ───────────────────────────────────────────────────



# ── Session / VIX bucketing ──────────────────────────────────────────────────









# ── Expected move calculations ───────────────────────────────────────────────












# ── IV Skew ──────────────────────────────────────────────────────────────────



# ── Realized Volatility ─────────────────────────────────────────────────────





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





# ── Volatility Envelope (ATR Bands) ─────────────────────────────────────────




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


# alpha + beta = 0.95 < 1.0 (stationary, moderate persistence)










# ── Theoretical IV Model Spread ──────────────────────────────────────────────

