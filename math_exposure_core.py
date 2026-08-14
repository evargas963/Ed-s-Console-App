"""
math_exposure_core.py
Base exposure engine — raw and normalized exposure values derived
from the chain and position structure.

Phase 2 extraction from math_exposure.py per Extraction Blueprint v1.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List
import math
import logging

from numeric_contract import float_finite_or_none

log = logging.getLogger(__name__)

# Schwab options API missing-greek sentinel (documented wire value).
MISSING_GREEK_SENTINEL: float = -999.0

# compute_net_charm zero-used error when contracts matched expiry but failed OI/gamma/IV gates.
CHARM_QUALITY_GATE_ERROR_MARKER = "quality gates"


def charm_compute_unavailable_log_level(error: str | None) -> int:
    """Quality-gate failure log level:
      - quality-gate (any skip distribution — uniform or mixed) → DEBUG
      - expiry mismatch / empty input (not quality-gate) → WARNING
      - None / unrecognized error → WARNING (fail-loud)

    The failure path only fires when ``used == 0`` (server.py:3474 routes
    partial-quality outcomes to the success-log). Every emission is the same
    steady-state class: complete chain unusable for charm. The skip-distribution
    detail (gamma=40 vs gamma=37+oi=3) is preserved in the error string for
    operator inspection; it does not change the operator-actionable signal,
    so it does not need its own log level. Per-tick INFO for this class was
    log spam outside RTH / when chain greeks are -999.

    Reserve WARNING for the two non-quality-gate errors — those are different
    classes (chain misrouted to wrong expiry / no contracts received at all)
    and warrant operator attention.
    """
    if error and CHARM_QUALITY_GATE_ERROR_MARKER in error:
        return logging.DEBUG
    return logging.WARNING

# ── Formatting helpers ────────────────────────────────────────────────────────

def _f(x) -> float | None:
    return float_finite_or_none(x)


def bucket_metric(bucket: dict, key: str) -> float | None:
    """Exposure-bucket field read without ``.get(key, 0) or 0`` silent default."""
    if not isinstance(bucket, dict) or key not in bucket:
        return None
    return _f(bucket[key])


def bucket_metric_abs(bucket: dict, key: str) -> float | None:
    v = bucket_metric(bucket, key)
    return abs(v) if v is not None else None


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
        bsz = _f(ct.get("bidSize"))
        asz = _f(ct.get("askSize"))
        if side == "CALL":
            if vol is not None:
                prev = b.get("call_volume")
                b["call_volume"] = vol if prev is None else float(prev) + vol
            if bsz is not None:
                b["call_bid_size"] = b.get("call_bid_size", 0.0) + bsz
            if asz is not None:
                b["call_ask_size"] = b.get("call_ask_size", 0.0) + asz
        else:
            if vol is not None:
                prev = b.get("put_volume")
                b["put_volume"] = vol if prev is None else float(prev) + vol
            if bsz is not None:
                b["put_bid_size"] = b.get("put_bid_size", 0.0) + bsz
            if asz is not None:
                b["put_ask_size"] = b.get("put_ask_size", 0.0) + asz

        if oi is None:
            missing += 1
        if require_oi and (oi is None or oi <= 0):
            continue

        delta = _f(ct.get("delta"))
        gamma = _f(ct.get("gamma"))
        delta_ok = delta is not None and delta != MISSING_GREEK_SENTINEL and math.isfinite(delta)
        gamma_ok = gamma is not None and gamma != MISSING_GREEK_SENTINEL and math.isfinite(gamma)

        if not delta_ok or not gamma_ok:
            missing += 1

        used += 1

        if side == "CALL":
            if oi is not None:
                prev = b.get("call_oi")
                b["call_oi"] = oi if prev is None else float(prev) + oi
                b["call_oi_mult"] += oi * mult
            if oi is not None and delta_ok:
                b["call_delta"] += delta * oi * mult
            if oi is not None and gamma_ok:
                b["call_gamma"] += gamma * oi * mult
            if oi is not None and spot is not None:
                spt = float(spot)
                b["call_oi_dollars"] += oi * mult * spt
                if delta_ok:
                    b["call_dex_dollars"] += delta * oi * mult * spt
                if gamma_ok:
                    b["call_gex_1pct"] += gamma * oi * mult * spt * spt * 0.01  # $-GEX per 1% spot move
                _vega = _f(ct.get("vega"))
                _vega_ok = _vega is not None and _vega != MISSING_GREEK_SENTINEL and math.isfinite(_vega)
                _iv = _f(ct.get("volatility"))
                _iv_ok = _iv is not None and _iv > 0 and _iv != MISSING_GREEK_SENTINEL and math.isfinite(_iv)
                if _vega_ok and _iv_ok:
                    b["call_vanna"] += (_vega / (spt * (_iv / 100.0))) * oi * mult
        elif side == "PUT":
            if oi is not None:
                prev = b.get("put_oi")
                b["put_oi"] = oi if prev is None else float(prev) + oi
                b["put_oi_mult"] += oi * mult
            if oi is not None and delta_ok:
                b["put_delta"] += delta * oi * mult
            if oi is not None and gamma_ok:
                b["put_gamma"] += gamma * oi * mult
            if oi is not None and spot is not None:
                spt = float(spot)
                b["put_oi_dollars"] += oi * mult * spt
                if delta_ok:
                    b["put_dex_dollars"] += delta * oi * mult * spt
                if gamma_ok:
                    b["put_gex_1pct"] += gamma * oi * mult * spt * spt * 0.01   # $-GEX per 1% spot move
                _vega = _f(ct.get("vega"))
                _vega_ok = _vega is not None and _vega != MISSING_GREEK_SENTINEL and math.isfinite(_vega)
                _iv = _f(ct.get("volatility"))
                _iv_ok = _iv is not None and _iv > 0 and _iv != MISSING_GREEK_SENTINEL and math.isfinite(_iv)
                if _vega_ok and _iv_ok:
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


# ── Institutional key-level primitives (single source of truth) ───────────────
# Window policy for UI/chart key levels: full option chain (CONSENSUS), not ATM±N.
KEY_LEVEL_STRIKE_WINDOW: int | None = None
# Bound pin persist stamp. Historical snapshots.gamma_pin from this writer was
# already the analytics |net GEX$| peak. NULL semantic on old rows means the same.
GAMMA_PIN_SEMANTIC = "net_gex_peak"
GAMMA_PIN_PAYLOAD_KEY = "kl_gamma_pin"
GAMMA_PIN_LABEL_PAYLOAD_KEY = "kl_gamma_pin_label"
GAMMA_PIN_TIP_PAYLOAD_KEY = "kl_gamma_pin_tip"
GAMMA_PIN_CONSUMER_LABEL = "Net Γ Peak"
GAMMA_PIN_CONSUMER_TIP = (
    "Largest |net GEX$| per 1% on the selected expiry. "
    "Not the total-gamma magnet (that is HVL)."
)

# One registry for every KEY LEVELS consumer name. UI renders payload
# ``{key}_label`` / ``{key}_tip`` — no hardcoded kl_* label strings.
KEY_LEVEL_CONSUMER_REGISTRY: dict[str, tuple[str, str]] = {
    "kl_call_gamma_wall": ("Gamma Wall Call", "Strike with the largest call GEX$."),
    "kl_put_gamma_wall": ("Gamma Wall Put", "Strike with the largest put GEX$."),
    "kl_gamma_pin": (GAMMA_PIN_CONSUMER_LABEL, GAMMA_PIN_CONSUMER_TIP),
    "kl_hvl": ("HVL", "Total-gamma concentration. Not the |net GEX$| peak (that is Net Γ Peak)."),
    "kl_max_pain": ("Max Pain", "Strike where the most options expire worthless."),
    "kl_gamma_flip": ("Gamma Flip", "Zero-gamma level. Above: dealers dampen. Below: dealers amplify."),
    "kl_em_upper": ("EM Upper", "Expected-move ceiling."),
    "kl_em_lower": ("EM Lower", "Expected-move floor."),
    "kl_gamma_inflection": ("Gamma Inflection", "Gamma inflection strike."),
    "kl_delta_inflection": ("Delta Inflection", "Delta inflection strike."),
    "kl_call_delta_wall": ("Delta Wall Call", "Strike with the largest call DEX."),
    "kl_put_delta_wall": ("Delta Wall Put", "Strike with the largest put DEX."),
    "kl_call_oi_wall": ("OI Wall Call", "Strike with the largest call open interest."),
    "kl_put_oi_wall": ("OI Wall Put", "Strike with the largest put open interest."),
    "kl_call_vanna_wall": ("Vanna Wall Call (vega/S·IV proxy)", "Call vanna wall (vega/S·IV proxy)."),
    "kl_put_vanna_wall": ("Vanna Wall Put (vega/S·IV proxy)", "Put vanna wall (vega/S·IV proxy)."),
    "kl_oi_center": ("OI Center", "Open-interest center of mass."),
}

# Dollar GEX per 1% spot move: gamma × OI × mult × spot² × 0.01 (see compute_exposures_by_strike).


def exposures_have_dollar_gex(exposures: Dict[float, dict]) -> bool:
    """True when spot was provided at bucket build and at least one strike has dollar GEX."""
    for b in exposures.values():
        c = bucket_metric(b, "call_gex_1pct")
        p = bucket_metric(b, "put_gex_1pct")
        if (c is not None and c != 0) or (p is not None and p != 0):
            return True
    return False


def key_level_strikes_with_oi(exposures: Dict[float, dict]) -> List[float]:
    """Strikes with Schwab OI present (post require_oi gate in compute_exposures_by_strike)."""
    out: List[float] = []
    for s in sorted(float(k) for k in exposures.keys()):
        b = exposures.get(s, {})
        co = b.get("call_oi")
        po = b.get("put_oi")
        if co is None or po is None:
            continue
        try:
            tot = float(co) + float(po)
        except (TypeError, ValueError):
            continue
        if tot > 0:
            out.append(s)
    return out


def key_level_strikes_with_gamma(exposures: Dict[float, dict]) -> List[float]:
    """Strikes with usable gamma buckets (excludes OI-only / invalid-greek tails)."""
    if not exposures:
        return []
    dollar = exposures_have_dollar_gex(exposures)
    out: List[float] = []
    for s in sorted(float(k) for k in exposures.keys()):
        b = exposures.get(s, {})
        if dollar:
            tg = total_gex_dollars_at_strike(b)
            ng = net_gex_dollars_at_strike(b)
            if (tg is not None and tg > 0) or (
                ng is not None and abs(ng) > 1e-12
            ):
                out.append(s)
        else:
            tg = total_gamma_raw_at_strike(b)
            if tg is not None and tg > 0:
                out.append(s)
    return out


def total_gex_dollars_at_strike(bucket: dict) -> float | None:
    """Peak gamma concentration: |call GEX$| + |put GEX$| per 1% move."""
    c = bucket_metric_abs(bucket, "call_gex_1pct")
    p = bucket_metric_abs(bucket, "put_gex_1pct")
    if c is None and p is None:
        return None
    total = 0.0
    if c is not None:
        total += c
    if p is not None:
        total += p
    return total


def net_gex_dollars_at_strike(bucket: dict) -> float | None:
    return bucket_metric(bucket, "net_gex_1pct")


def total_gamma_raw_at_strike(bucket: dict) -> float | None:
    c = bucket_metric_abs(bucket, "call_gamma")
    p = bucket_metric_abs(bucket, "put_gamma")
    if c is None and p is None:
        return None
    total = 0.0
    if c is not None:
        total += c
    if p is not None:
        total += p
    return total


def net_gamma_raw_at_strike(bucket: dict) -> float | None:
    return bucket_metric(bucket, "net_gamma")


def _pick_strike_max_metric(
    exposures: Dict[float, dict],
    strikes: List[float],
    metric_fn,
) -> tuple[float | None, float | None]:
    best_s: float | None = None
    best_v: float | None = None
    for s in strikes:
        b = exposures.get(s, {})
        v = metric_fn(b)
        if v is None or v <= 0:
            continue
        if best_v is None or v > best_v:
            best_s = float(s)
            best_v = float(v)
    return best_s, best_v


def pick_gamma_pin_strike(
    exposures: Dict[float, dict],
    strikes: List[float],
    *,
    institutional: bool = True,
) -> float | None:
    """
    Gamma pin: strike with largest |net GEX$| per 1% (institutional).
    When institutional=True and spot/dollar GEX unavailable, returns None (no raw fallback).
  """
    if exposures_have_dollar_gex(exposures):
        s, _ = _pick_strike_max_metric(
            exposures, strikes, lambda b: bucket_metric_abs(b, "net_gex_1pct")
        )
        return round(s, 2) if s is not None else None
    if institutional:
        return None
    s, _ = _pick_strike_max_metric(
        exposures, strikes, lambda b: bucket_metric_abs(b, "net_gamma")
    )
    return round(s, 2) if s is not None else None


def gex_at_bound_pin_strike(
    exposures: Dict[float, dict],
    strike: float | None,
) -> float | None:
    """|net GEX$| (or |net γ| fallback) at the bound pin strike.

    Bound pin is pick_gamma_pin_strike — largest |net GEX$| per 1%.
    pin_score must read this magnitude. Not total-gamma (|call|+|put|), which is HVL.
    """
    if strike is None or not exposures:
        return None
    try:
        key = float(strike)
    except (TypeError, ValueError):
        return None
    bucket = exposures.get(key) or exposures.get(strike) or {}
    if exposures_have_dollar_gex(exposures):
        raw = net_gex_dollars_at_strike(bucket)
    else:
        raw = net_gamma_raw_at_strike(bucket)
    if raw is None:
        return None
    try:
        return abs(float(raw))
    except (TypeError, ValueError):
        return None


def pick_hvl_strike(exposures: Dict[float, dict], strikes: List[float]) -> float | None:
    """
    HVL: strike with largest total gamma concentration.
    Institutional: max (|call GEX$| + |put GEX$|); fallback: max (|call_γ| + |put_γ|).
    """
    if exposures_have_dollar_gex(exposures):
        s, _ = _pick_strike_max_metric(exposures, strikes, total_gex_dollars_at_strike)
        return round(s, 2) if s is not None else None
    s, _ = _pick_strike_max_metric(exposures, strikes, total_gamma_raw_at_strike)
    return round(s, 2) if s is not None else None


def pick_gamma_wall_strikes(
    exposures: Dict[float, dict], strikes: List[float]
) -> tuple[tuple[float | None, float | None], tuple[float | None, float | None]]:
    """Call/put gamma walls: max |side GEX$| (or |side γ| fallback)."""
    if exposures_have_dollar_gex(exposures):
        return (
            _pick_strike_max_metric(
                exposures, strikes, lambda b: bucket_metric_abs(b, "call_gex_1pct")
            ),
            _pick_strike_max_metric(
                exposures, strikes, lambda b: bucket_metric_abs(b, "put_gex_1pct")
            ),
        )
    return (
        _pick_strike_max_metric(
            exposures, strikes, lambda b: bucket_metric_abs(b, "call_gamma")
        ),
        _pick_strike_max_metric(
            exposures, strikes, lambda b: bucket_metric_abs(b, "put_gamma")
        ),
    )


def pick_delta_wall_strikes(
    exposures: Dict[float, dict], strikes: List[float]
) -> tuple[tuple[float | None, float | None], tuple[float | None, float | None]]:
    if exposures_have_dollar_gex(exposures):
        return (
            _pick_strike_max_metric(
                exposures, strikes, lambda b: bucket_metric_abs(b, "call_dex_dollars")
            ),
            _pick_strike_max_metric(
                exposures, strikes, lambda b: bucket_metric_abs(b, "put_dex_dollars")
            ),
        )
    return (
        _pick_strike_max_metric(
            exposures, strikes, lambda b: bucket_metric_abs(b, "call_delta")
        ),
        _pick_strike_max_metric(
            exposures, strikes, lambda b: bucket_metric_abs(b, "put_delta")
        ),
    )


def aggregate_net_gex(exposures: Dict[float, dict], strikes: List[float]) -> float | None:
    """Chain-aggregate net GEX$: Σ net_gex_1pct (institutional); fallback Σ net_gamma."""
    if not strikes:
        return None
    if exposures_have_dollar_gex(exposures):
        total = 0.0
        any_v = False
        for s in strikes:
            v = net_gex_dollars_at_strike(exposures.get(s, {}))
            if v is not None:
                total += v
                any_v = True
        return float(total) if any_v else None
    total = 0.0
    any_g = False
    for s in strikes:
        b = exposures.get(s, {})
        ng = net_gamma_raw_at_strike(b)
        if ng is not None:
            total += ng
            any_g = True
    return float(total) if any_g else None


def aggregate_net_dex(exposures: Dict[float, dict], strikes: List[float]) -> float | None:
    if not strikes:
        return None
    if exposures_have_dollar_gex(exposures):
        total = 0.0
        any_v = False
        for s in strikes:
            v = bucket_metric(exposures.get(s, {}), "net_dex_dollars")
            if v is not None:
                total += v
                any_v = True
        return float(total) if any_v else None
    total = 0.0
    any_d = False
    for s in strikes:
        v = bucket_metric(exposures.get(s, {}), "net_delta")
        if v is not None:
            total += float(v)
            any_d = True
    return float(total) if any_d else None


def gex_magnitude_label(net_gex: float | None) -> str:
    if net_gex is None:
        return "negligible"
    a = abs(float(net_gex))
    if a >= 50_000_000:
        return "large"
    if a >= 10_000_000:
        return "moderate"
    if a >= 1_000_000:
        return "small"
    return "negligible"


def gex_regime_label(net_gex: float | None) -> str:
    if net_gex is None or abs(float(net_gex)) < 1e-6:
        return "neutral"
    return "positive" if float(net_gex) > 0 else "negative"


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
        b = exposures_by_strike.get(k, {}) or {}
        g = bucket_metric(b, "net_gex_1pct")
        d = bucket_metric(b, "net_dex_dollars")
        o = bucket_metric(b, "total_oi_dollars")
        if g is not None:
            net_gex += float(g)
        if d is not None:
            net_dex += float(d)
        if o is not None:
            tot_oi += float(o)
    return {"spot": float(spot), "atm": float(atm), "net_gex_1pct": float(net_gex), "net_dex_dollars": float(net_dex), "total_oi_dollars": float(tot_oi)}

def strike_agg(exposures, strike):
    return dict(exposures.get(float(strike), {}))


# ── Charm ─────────────────────────────────────────────────────────────────────

def compute_net_charm(
    contracts: list,
    spot: float,
    expiry: str,
    *,
    rate: float = 0.05,
    drift_toward_strike: float | None = None,
) -> dict:
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

    drift_toward_strike: institutional gamma pin from pick_gamma_pin_strike (caller-supplied).
    Charm flow direction is independent of pin location.

    Returns:
        net_charm_daily  : net delta-equivalents unwound per day (negative = selling)
        charm_direction  : "buying" | "selling" | "neutral"  (for signals engine)
        drift_toward     : drift_toward_strike when provided
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
                from time_et import now_et

                _now_et = now_et()
            except Exception:
                _now_et = _dt2.datetime.now()
            hours_left = max(0.5, 16.0 - (_now_et.hour + _now_et.minute / 60.0))
            return hours_left / 24.0 / 365.0
        return dte_f / 365.0

    call_charm = put_charm = 0.0
    used = 0
    _input_n = len(contracts)
    _skip_expiry = _skip_side = _skip_fields = _skip_oi = _skip_mult = 0
    _skip_gamma = _skip_iv = _skip_T = _skip_math = 0

    for ct in contracts:
        # Filter to target expiry
        ct_exp = ct.get("expirationDate")
        if ct_exp and _target_exp:
            if str(ct_exp)[:10] != _target_exp:
                _skip_expiry += 1
                continue
        elif _target_exp:
            _skip_expiry += 1
            continue

        side    = (ct.get("putCall") or "").upper().strip()
        if side not in ("CALL", "PUT"):
            _skip_side += 1
            continue

        strike  = _f(ct.get("strikePrice"))
        gamma   = _f(ct.get("gamma"))
        iv      = _f(ct.get("volatility"))
        oi      = _f(ct.get("openInterest"))
        mult    = _f(ct.get("multiplier"))
        dte_raw = ct.get("daysToExpiration")

        if gamma is None or strike is None:
            _skip_fields += 1
            continue
        if oi is None or oi <= 0:
            _skip_oi += 1
            continue
        if mult is None or mult <= 0:
            _skip_mult += 1
            continue
        if gamma == MISSING_GREEK_SENTINEL or not math.isfinite(gamma):
            _skip_gamma += 1
            continue
        if iv is None or iv <= 0 or iv == MISSING_GREEK_SENTINEL or not math.isfinite(iv):
            _skip_iv += 1
            continue

        T = _resolve_T(dte_raw)
        if T is None or T <= 0:
            _skip_T += 1
            continue

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
            _skip_math += 1
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

        used += 1

    if used <= 0:
        if _input_n == 0:
            _err = f"No contracts provided for expiry={_target_exp}"
        elif _skip_expiry == _input_n:
            _err = f"No contracts with expirationDate matching expiry={_target_exp} (input={_input_n})"
        else:
            _err = (
                f"No contracts passed charm quality gates for expiry={_target_exp} "
                f"(input={_input_n}, skipped: expiry={_skip_expiry}, oi={_skip_oi}, "
                f"gamma={_skip_gamma}, iv={_skip_iv}, mult={_skip_mult}, T={_skip_T}, "
                f"fields={_skip_fields}, side={_skip_side}, math={_skip_math})"
            )
        return {
            "net_charm_daily": None,
            "call_charm_daily": None,
            "put_charm_daily": None,
            "charm_direction": None,
            "charm_magnitude": None,
            "drift_toward": drift_toward_strike,
            "contracts_used": 0,
            "error": _err,
        }

    net = call_charm + put_charm

    # Direction: positive net = dealers net buying delta (bullish), negative = selling (bearish)
    direction = "neutral" if abs(net) < 1.0 else ("buying" if net > 0 else "selling")
    abs_net = abs(net)
    if abs_net >= 5000:
        magnitude = "large"
    elif abs_net >= 1000:
        magnitude = "moderate"
    elif abs_net >= 100:
        magnitude = "small"
    else:
        magnitude = "negligible"

    return {
        "net_charm_daily": round(net, 2),
        "call_charm_daily": round(call_charm, 2),
        "put_charm_daily": round(put_charm, 2),
        "charm_direction": direction,
        "charm_magnitude": magnitude,
        "drift_toward": drift_toward_strike,
        "contracts_used": used,
        "error": "",
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
    r_sq = round((cov ** 2) / (var_s * var_t), 4) if var_t > 1e-12 else None

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
        dt_ms = c.get("datetime")
        close = c.get("close")
        if close is None or dt_ms is None:
            continue
        try:
            dt_ms = float(dt_ms)
        except (TypeError, ValueError):
            continue
        if dt_ms <= 0:
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

