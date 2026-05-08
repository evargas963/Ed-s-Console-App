"""
math_exposure_core.py
Base exposure engine — raw and normalized exposure values derived
from the chain and position structure.

Phase 2 extraction from math_exposure.py per Extraction Blueprint v1.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple
import math
import logging

log = logging.getLogger(__name__)


# ── Formatting helpers ────────────────────────────────────────────────────────

def _f(x) -> float | None:
    try:
        if x is None:
            return None
        return float(x)
    except Exception:
        return None


# ── Data classes ──────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class ExposureRow:
    label: str                 # CONSENSUS, ±5, ±10, ±15, ±20
    window: int | None         # None = all (consensus)
    net_gamma: float | None
    net_delta: float | None
    gamma_pin: float | None
    delta_inflection: float | None
    gamma_inflection: float | None
    oi_center: float | None
    pin_strength: str
    bias_signal: str

@dataclass(frozen=True)
class ExposureDiagnostics:
    contracts_total: int
    contracts_used: int
    greeks_missing: int
    note: str


# ── Exposure primitives ──────────────────────────────────────────────────────

def _is_valid_greek(x: float | None) -> bool:
    return x is not None and x != -999.0

def _strike_bucket(exposures_by_strike: Dict[float, dict], strike: float) -> dict:
    if strike not in exposures_by_strike:
        exposures_by_strike[strike] = {
            "call_oi": None,
            "put_oi": None,
            "call_oi_mult": 0.0,
            "put_oi_mult": 0.0,
            # NOTE: These are exposure-scaled buckets (gamma*OI*mult, delta*OI*mult)
            "call_gamma": 0.0,
            "put_gamma": 0.0,
            "call_vanna": 0.0,
            "put_vanna": 0.0,
            "call_delta": 0.0,
            "put_delta": 0.0,
            "net_gamma": 0.0,
            "net_delta": 0.0,
            # Dollarized (institutional) exposures when spot is provided
            "call_dex_dollars": 0.0,
            "put_dex_dollars": 0.0,
            "net_dex_dollars": 0.0,
            "call_gex_1pct": 0.0,
            "put_gex_1pct": 0.0,
            "net_gex_1pct": 0.0,
            "call_oi_dollars": 0.0,
            "put_oi_dollars": 0.0,
            "total_oi_dollars": 0.0,
            # Option-chain order flow (Schwab: bidSize, askSize, totalVolume per leg)
            "call_volume": None,
            "put_volume": None,
            "call_bid_size": 0.0,
            "call_ask_size": 0.0,
            "put_bid_size": 0.0,
            "put_ask_size": 0.0,
        }
    return exposures_by_strike[strike]

def compute_exposures_by_strike(
    contracts: List[dict],
    *,
    spot: float | None = None,
    use_only_dte_max: int | None = None,
    require_oi: bool = True,
) -> tuple[Dict[float, dict], ExposureDiagnostics]:
    """
    Produces per-strike aggregated:
      - call/put OI
      - call/put delta exposure (scaled)
      - call/put gamma exposure (scaled)
      - net delta, net gamma (Call + Put; puts keep signed delta)

    Scaling (Option A):
      delta_exposure = delta * OI * multiplier
      gamma_exposure = gamma * OI * multiplier

    NOTE: Dollarized fields (DEX$, GEX$ per 1%, OI$) are computed when `spot` is provided. Net gamma follows Call - Put convention.
    """
    exposures: Dict[float, dict] = {}
    total = 0
    used = 0
    missing = 0

    for ct in contracts:
        total += 1
        strike = _f(ct.get("strikePrice"))
        if strike is None:
            continue

        dte = _f(ct.get("daysToExpiration"))
        if use_only_dte_max is not None and dte is not None and dte > use_only_dte_max:
            continue

        oi = _f(ct.get("openInterest"))
        side = (ct.get("putCall") or "").upper()
        if side not in ("CALL", "PUT"):
            continue

        mult = _f(ct.get("multiplier"))
        if mult is None or mult <= 0:
            missing += 1
            continue

        b = _strike_bucket(exposures, strike)
        vol = _f(ct.get("totalVolume"))
        bsz = _f(ct.get("bidSize")) or 0.0
        asz = _f(ct.get("askSize")) or 0.0
        if side == "CALL":
            if vol is not None:
                current_call_volume = b.get("call_volume")
                b["call_volume"] = (float(current_call_volume) if current_call_volume is not None else 0.0) + vol
            b["call_bid_size"] = b.get("call_bid_size", 0.0) + bsz
            b["call_ask_size"] = b.get("call_ask_size", 0.0) + asz
        else:
            if vol is not None:
                current_put_volume = b.get("put_volume")
                b["put_volume"] = (float(current_put_volume) if current_put_volume is not None else 0.0) + vol
            b["put_bid_size"] = b.get("put_bid_size", 0.0) + bsz
            b["put_ask_size"] = b.get("put_ask_size", 0.0) + asz

        if oi is None:
            missing += 1
        if require_oi and (oi is None or oi <= 0):
            continue

        delta = _f(ct.get("delta"))
        gamma = _f(ct.get("gamma"))

        if not _is_valid_greek(delta) or not _is_valid_greek(gamma):
            missing += 1

        used += 1

        if side == "CALL":
            if oi is not None:
                current_call_oi = b.get("call_oi")
                b["call_oi"] = (float(current_call_oi) if current_call_oi is not None else 0.0) + oi
                b["call_oi_mult"] += oi * mult
            if oi is not None and _is_valid_greek(delta):
                b["call_delta"] += delta * oi * mult
            if oi is not None and _is_valid_greek(gamma):
                b["call_gamma"] += gamma * oi * mult
            if oi is not None and spot is not None:
                spt = float(spot)
                b["call_oi_dollars"] += oi * mult * spt
                if _is_valid_greek(delta):
                    b["call_dex_dollars"] += delta * oi * mult * spt
                if _is_valid_greek(gamma):
                    b["call_gex_1pct"] += gamma * oi * mult * spt * spt * 0.01  # $-GEX per 1% spot move
                _vega = _f(ct.get("vega")); _iv = _f(ct.get("volatility"))
                if _is_valid_greek(_vega) and _iv and _iv > 0:
                    b["call_vanna"] += (_vega / (spt * (_iv / 100.0))) * oi * mult
        elif side == "PUT":
            if oi is not None:
                current_put_oi = b.get("put_oi")
                b["put_oi"] = (float(current_put_oi) if current_put_oi is not None else 0.0) + oi
                b["put_oi_mult"] += oi * mult
            if oi is not None and _is_valid_greek(delta):
                b["put_delta"] += delta * oi * mult
            if oi is not None and _is_valid_greek(gamma):
                b["put_gamma"] += gamma * oi * mult
            if oi is not None and spot is not None:
                spt = float(spot)
                b["put_oi_dollars"] += oi * mult * spt
                if _is_valid_greek(delta):
                    b["put_dex_dollars"] += delta * oi * mult * spt
                if _is_valid_greek(gamma):
                    b["put_gex_1pct"] += gamma * oi * mult * spt * spt * 0.01   # $-GEX per 1% spot move
                _vega = _f(ct.get("vega")); _iv = _f(ct.get("volatility"))
                if _is_valid_greek(_vega) and _iv and _iv > 0:
                    b["put_vanna"] += (_vega / (spt * (_iv / 100.0))) * oi * mult
        else:
            continue

    for strike, b in exposures.items():
        b["net_gamma"] = b["call_gamma"] - b["put_gamma"]
        b["net_delta"] = b["call_delta"] + b["put_delta"]
        # Dollarized net fields (remain 0.0 if spot is None)
        b["net_dex_dollars"] = b.get("call_dex_dollars", 0.0) + b.get("put_dex_dollars", 0.0)
        b["net_gex_1pct"] = b.get("call_gex_1pct", 0.0) - b.get("put_gex_1pct", 0.0)
        b["total_oi_dollars"] = b.get("call_oi_dollars", 0.0) + b.get("put_oi_dollars", 0.0)

    note = "OK"
    if used == 0:
        note = "No usable contracts (OI filtered or chain empty)."
    elif missing == used:
        note = "All greeks missing (-999). You will still get OI center; gamma/delta pin/inf may be N/A until RTH."

    return exposures, ExposureDiagnostics(
        contracts_total=total,
        contracts_used=used,
        greeks_missing=missing,
        note=note,
    )


# ── Strike selection helpers ─────────────────────────────────────────────────
# (foundational — used by both levels and volatility modules)

def _nearest_strike(strikes: List[float], spot: float) -> float:
    # Deterministic tie-break: lower strike if equal distance
    best = None
    best_d = None
    for s in sorted(strikes):
        d = abs(s - spot)
        if best is None or d < best_d:
            best = s
            best_d = d
    return float(best)

def _window_strikes(strikes: List[float], spot: float, window: int) -> List[float]:
    strikes_sorted = sorted(strikes)
    center = _nearest_strike(strikes_sorted, spot)
    idx = strikes_sorted.index(center)
    lo = max(0, idx - window)
    hi = min(len(strikes_sorted), idx + window + 1)
    return strikes_sorted[lo:hi]


# ── Validation / sanitization ────────────────────────────────────────────────

def greeks_validity(contracts_used: int, greeks_missing: int) -> bool:
    """Return True if dealer metrics (DEX/GEX) are usable based on greek availability."""
    try:
        cu = int(contracts_used)
        gm = int(greeks_missing)
    except Exception:
        return False
    if cu <= 0:
        return False
    if gm >= cu:
        return False
    return True


def sanitize_dealer_metrics(net_dex_dollars, net_gex_1pct, *, contracts_used: int, greeks_missing: int):
    """Return (net_dex, net_gex, dealer_valid). If not valid, net_dex/net_gex are None."""
    valid = greeks_validity(contracts_used, greeks_missing)
    if not valid:
        return None, None, False
    return net_dex_dollars, net_gex_1pct, True


# ── Exposure aggregation ─────────────────────────────────────────────────────

def window_summary(exposures_by_strike: dict[float, dict], spot: float, strike_window: int) -> dict[str, float]:
    """Aggregate exposure outputs across an ATM-centered strike window.

    This is *math layer* because it is part of the exposure aggregation pipeline and must be consistent across UIs.
    """
    strikes = sorted([float(k) for k in (exposures_by_strike or {}).keys()])
    if not strikes:
        return {"spot": float(spot), "atm": float(spot), "net_gex_1pct": 0.0, "net_dex_dollars": 0.0, "total_oi_dollars": 0.0}
    atm = min(strikes, key=lambda x: abs(x - float(spot)))
    lo = atm - float(strike_window)
    hi = atm + float(strike_window)
    use = [k for k in strikes if lo <= k <= hi]
    net_gex = net_dex = tot_oi = 0.0
    for k in use:
        b = (exposures_by_strike.get(k, {}) or {})
        net_gex += float(b.get("net_gex_1pct") or 0.0)
        net_dex += float(b.get("net_dex_dollars") or 0.0)
        tot_oi += float(b.get("total_oi_dollars") or 0.0)
    return {"spot": float(spot), "atm": float(atm), "net_gex_1pct": float(net_gex), "net_dex_dollars": float(net_dex), "total_oi_dollars": float(tot_oi)}

def strike_agg(exposures, strike):
    return dict(exposures.get(float(strike), {}))


# ── Charm ─────────────────────────────────────────────────────────────────────

def compute_net_charm(contracts: list, spot: float, expiry: str, *, rate: float = 0.05) -> dict:
    """
    Compute dealer net charm exposure for a given expiry.

    CHARM = dDelta/dt — the rate at which dealer delta hedges decay with time.
    As expiry approaches, dealers must unwind their delta hedges. The NET direction
    of that unwind creates mechanical buying or selling pressure independent of price.

    Formula (Black-Scholes):
        For calls:  charm = -phi(d1) * [d2/(2*S*iv*sqrt(T)) + r/(iv*sqrt(T))]
        For puts:   charm_put = charm_call - phi(d1) (by put-call parity)
        phi = standard normal PDF
        d1 = [ln(S/K) + (r + iv²/2)*T] / (iv*sqrt(T))
        d2 = d1 - iv*sqrt(T)

    Dealer position: market makers are typically SHORT options (sold to retail).
    SHORT call → delta hedge = SHORT stock. As charm decays, they BUY back stock.
    SHORT put  → delta hedge = LONG stock. As charm decays, they SELL stock.
    Net charm > 0 → net dealer delta buying  → Bullish flow
    Net charm < 0 → net dealer delta selling → Bearish flow

    Gamma pin (drift_toward): strike with highest TOTAL OI-weighted GEX (calls+puts).
    This is where price is mechanically pinned by dealer hedging, independent of charm flow.
    The gamma pin and charm direction CAN conflict — price wants to pin at gamma_pin
    while charm creates a directional unwind force.

    Returns:
        net_charm_daily  : net delta-equivalents unwound per day (negative = selling)
        charm_direction  : "buying" | "selling" | "neutral"  (for signals engine)
        drift_toward     : strike of gamma pin (TOTAL GEX, not call-only)
        gamma_pin        : same as drift_toward
        contracts_used   : number of contracts that contributed
    """
    import datetime as _dt2, math as _m

    try:
        _target_exp = str(expiry)[:10]
        if len(_target_exp) != 10:
            _target_exp = None
    except Exception:
        _target_exp = None

    # For 0DTE: use remaining hours to close as T
    # Prevents formula explosion as T → 0
    def _resolve_T(dte_raw):
        if dte_raw is None: return None
        dte_f = float(dte_raw)
        if dte_f <= 0:
            try:
                from zoneinfo import ZoneInfo
                _now_et = _dt2.datetime.now(ZoneInfo("America/New_York"))
            except Exception:
                _now_et = _dt2.datetime.now()
            hours_left = max(0.5, 16.0 - (_now_et.hour + _now_et.minute / 60.0))
            return hours_left / 24.0 / 365.0
        return dte_f / 365.0

    call_charm = put_charm = 0.0
    total_gex_by_strike: dict = {}   # strike → total abs GEX (calls + puts)
    used = 0

    for ct in contracts:
        # Filter to target expiry
        ct_exp = ct.get("expirationDate")
        if ct_exp and _target_exp:
            if str(ct_exp)[:10] != _target_exp:
                continue
        elif _target_exp:
            continue

        side    = (ct.get("putCall") or "").upper().strip()
        if side not in ("CALL", "PUT"): continue

        strike  = _f(ct.get("strikePrice"))
        gamma   = _f(ct.get("gamma"))
        iv      = _f(ct.get("volatility"))
        delta   = _f(ct.get("delta"))
        oi      = _f(ct.get("openInterest"))
        mult    = _f(ct.get("multiplier"))
        dte_raw = ct.get("daysToExpiration")

        if gamma is None or strike is None:
            continue
        if oi is None or oi <= 0:
            continue
        if mult is None or mult <= 0:
            continue
        if not _is_valid_greek(gamma):
            continue
        if iv is None or iv <= 0:
            continue

        T = _resolve_T(dte_raw)
        if T is None or T <= 0: continue

        iv_dec = iv / 100.0
        S      = float(spot)
        K      = float(strike)
        r      = rate

        # charm = dDelta/dt using the standard dealer-positioning form:
        #   charm = -phi(d1) * d2 / (2*T)
        #
        # This form (not the full BS expansion) stays bounded as T→0 because
        # d2 → 0 at the same rate. The full expansion includes r/(iv*sqrt(T))
        # which explodes for 0DTE (e.g. 0.05/0.005 = 10 → billions).
        #
        # Units: delta/year per unit contract. Scale to daily:
        #   weighted = charm/year / 365 * OI * mult
        #
        # Sign: negative charm = delta decaying = dealers buying back delta = bullish.
        # We flip sign below: net > 0 means dealers net BUYING (bullish flow).
        try:
            ln_SK = _m.log(S / K)
            sqrt_T = _m.sqrt(T)
            d1 = (ln_SK + 0.5 * iv_dec**2 * T) / (iv_dec * sqrt_T)
            d2 = d1 - iv_dec * sqrt_T
            phi_d1 = (1.0 / _m.sqrt(2.0 * _m.pi)) * _m.exp(-0.5 * d1**2)
        except Exception:
            continue

        if T <= 0: continue

        # charm per unit in delta/year
        charm_unit = -phi_d1 * d2 / (2.0 * T)

        # For puts: by put-call parity, charm_put = charm_call (same sign, same magnitude
        # at ATM; put delta decays symmetrically to call delta). Use same formula.
        # The sign difference between calls and puts is already captured in the
        # direction of net_delta (calls positive, puts negative).

        # Daily aggregate: charm_unit/365 * OI * mult
        weighted = charm_unit / 365.0 * oi * mult

        if side == "CALL":
            call_charm += weighted
        else:
            put_charm  += weighted

        # Gamma pin: track total OI-weighted GEX per strike (calls + puts)
        if strike is not None:
            g_weighted = abs(gamma) * oi * mult
            total_gex_by_strike[strike] = total_gex_by_strike.get(strike, 0.0) + g_weighted

        used += 1

    net = call_charm + put_charm

    # Direction: positive net = dealers net buying delta (bullish), negative = selling (bearish)
    direction = "neutral" if abs(net) < 1.0 else ("buying" if net > 0 else "selling")

    # Gamma pin = strike with highest TOTAL (call + put) OI-weighted GEX
    gamma_pin = max(total_gex_by_strike, key=total_gex_by_strike.get) if total_gex_by_strike else None

    return {
        "net_charm_daily":  round(net, 2),
        "call_charm_daily": round(call_charm, 2),
        "put_charm_daily":  round(put_charm, 2),
        "charm_direction":  direction,
        "drift_toward":     gamma_pin,
        "gamma_pin":        gamma_pin,
        "contracts_used":   used,
        "error": "" if used > 0 else f"No contracts matched expiry={_target_exp}",
    }


# ── Greek bias ────────────────────────────────────────────────────────────────

GREEK_BIAS_DELTA_WEIGHT = 1.0
GREEK_BIAS_CHARM_WEIGHT = 0.5
GREEK_BIAS_PCOI_WEIGHT  = 0.5
GREEK_BIAS_PCOI_BEARISH = 1.3
GREEK_BIAS_PCOI_BULLISH = 0.8
GREEK_BIAS_THRESHOLD    = 0.5

def greek_bias(net_delta: float | None, charm_direction: str | None,
               put_call_oi_ratio: float | None,
               dex_magnitude: str = "moderate",
               charm_magnitude: str = "moderate") -> str:
    MAG_SCALE = {"large": 1.0, "moderate": 0.7, "small": 0.3, "negligible": 0.0}
    score = 0.0
    delta_scale = MAG_SCALE.get(dex_magnitude, 0.7)
    if net_delta is not None and delta_scale > 0:
        if net_delta > 0:
            score += GREEK_BIAS_DELTA_WEIGHT * delta_scale
        elif net_delta < 0:
            score -= GREEK_BIAS_DELTA_WEIGHT * delta_scale
    charm_scale = MAG_SCALE.get(charm_magnitude, 0.7)
    if charm_direction == "buying":
        score += GREEK_BIAS_CHARM_WEIGHT * charm_scale
    elif charm_direction == "selling":
        score -= GREEK_BIAS_CHARM_WEIGHT * charm_scale
    if put_call_oi_ratio is not None:
        if put_call_oi_ratio > GREEK_BIAS_PCOI_BEARISH:
            score -= GREEK_BIAS_PCOI_WEIGHT
        elif put_call_oi_ratio < GREEK_BIAS_PCOI_BULLISH:
            score += GREEK_BIAS_PCOI_WEIGHT
    if score > GREEK_BIAS_THRESHOLD:
        return "bullish"
    elif score < -GREEK_BIAS_THRESHOLD:
        return "bearish"
    return "neutral"


# ── Beta / returns ────────────────────────────────────────────────────────────

BETA_LOOKBACK_DAYS = 20

def compute_beta(ticker_returns: list, spy_returns: list) -> dict:
    """Compute beta from paired daily returns via OLS regression.

    Beta = Cov(ticker, SPY) / Var(SPY)

    Args:
        ticker_returns: list of float (daily % returns, e.g. [0.5, -1.2, ...])
        spy_returns:    list of float (same length, same dates)

    Returns:
        {"beta": float, "r_squared": float, "n": int}
        or {"beta": None, ...} if insufficient data.
    """
    import math

    n = min(len(ticker_returns), len(spy_returns))
    if n < 5:
        return {"beta": None, "r_squared": None, "n": n,
                "error": f"Need 5+ paired returns, have {n}"}

    tr = ticker_returns[-n:]
    sr = spy_returns[-n:]

    mean_t = sum(tr) / n
    mean_s = sum(sr) / n

    cov = sum((tr[i] - mean_t) * (sr[i] - mean_s) for i in range(n)) / n
    var_s = sum((sr[i] - mean_s) ** 2 for i in range(n)) / n

    if var_s < 1e-12:
        return {"beta": None, "r_squared": None, "n": n,
                "error": "SPY variance near zero"}

    beta = round(cov / var_s, 4)

    # R-squared
    var_t = sum((tr[i] - mean_t) ** 2 for i in range(n)) / n
    r_sq = round((cov ** 2) / (var_s * var_t), 4) if var_t > 1e-12 else 0.0

    return {"beta": beta, "r_squared": r_sq, "n": n, "error": ""}


def compute_beta_residual(ticker_chg_pct: float, spy_chg_pct: float,
                          beta: float) -> float:
    """Beta-adjusted residual: how much the ticker moved beyond what beta implies.

    residual = ticker_chg - (spy_chg × beta)
    Positive = outperforming (stronger than market implies)
    Negative = underperforming (weaker than market implies)
    """
    return round(ticker_chg_pct - (spy_chg_pct * beta), 4)

def returns_from_candles(candles: list) -> list:
    """Extract daily close-to-close % returns from 1-min candle list.

    Groups candles by date, takes last close per day, computes daily return.
    Expects candles with 'datetime' (epoch ms) and 'close' fields.
    """
    from datetime import datetime, timezone
    from collections import OrderedDict

    daily_close = OrderedDict()
    for c in candles:
        dt_ms = c.get("datetime", 0)
        close = c.get("close")
        if not close or not dt_ms:
            continue
        dt = datetime.fromtimestamp(dt_ms / 1000, tz=timezone.utc)
        day = dt.strftime("%Y-%m-%d")
        daily_close[day] = float(close)  # last candle of each day wins

    closes = list(daily_close.values())
    if len(closes) < 2:
        return []

    returns = []
    for i in range(1, len(closes)):
        if closes[i - 1] > 0:
            ret = (closes[i] - closes[i - 1]) / closes[i - 1] * 100.0
            returns.append(round(ret, 4))
    return returns

