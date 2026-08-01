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

from numeric_contract import float_finite_or_none, float_nonnegative_or_none

log = logging.getLogger(__name__)

# Schwab options API missing-greek sentinel (documented wire value).
MISSING_GREEK_SENTINEL: float = -999.0

# Per-share vanilla equity-option gamma is always ≥ 0 and rarely above ~1.0.
# Schwab occasionally returns finite garbage on 0DTE deep-ITM (e.g. gamma=-91965)
# that would otherwise dominate OI-weighted net_gamma / GEX / walls.
GAMMA_PLAUSIBLE_MAX: float = 1.0
# Deep ITM/OTM: true gamma ≈ 0; reject non-near-zero gamma when |delta| is extreme.
DELTA_DEEP_ABS_FOR_GAMMA: float = 0.98
GAMMA_DEEP_DELTA_MAX: float = 1e-4

# compute_net_charm zero-used error when contracts matched expiry but failed OI/gamma/IV gates.
CHARM_QUALITY_GATE_ERROR_MARKER = "quality gates"


def schwab_iv_to_sigma(iv: float | None) -> float | None:
    """The ONE conversion from Schwab's `volatility` field to a decimal sigma.

    Schwab reports implied volatility in PERCENT. Verified 2026-07-19 on 1,600 contract
    greeks from the 40 most recent chain snapshots: min 23.7550, median 50.4315, max
    174.2260 — 1,600 of 1,600 above 3.0, none at or below it.

    The `> 3.0` test is a defensive guard against a silent vendor unit change (a 300%
    IV is possible but vanishingly rare; a 3.0 decimal sigma is not). It is kept because
    a units flip would otherwise corrupt every gamma silently rather than loudly.

    This existed as two different inline expressions — `iv / 100.0` unconditionally in
    compute_net_charm and the guarded form in math_levels._contract_inputs — i.e. two
    modules encoding different assumptions about one vendor field. One definition now.
    """
    if iv is None or iv <= 0:
        return None
    return iv / 100.0 if iv > 3.0 else iv


def gamma_is_plausible(gamma: float | None, delta: float | None = None) -> bool:
    """True when ``gamma`` is usable in OI-weighted gamma aggregation.

    Rejects: None, MISSING_GREEK_SENTINEL, non-finite, negative, above
    ``GAMMA_PLAUSIBLE_MAX``, and non-near-zero gamma when ``|delta|`` is deep
    ITM/OTM (``>= DELTA_DEEP_ABS_FOR_GAMMA``). OI-only metrics should still
    include the contract when gamma is rejected.
    """
    if gamma is None or gamma == MISSING_GREEK_SENTINEL or not math.isfinite(gamma):
        return False
    if gamma < 0.0 or gamma > GAMMA_PLAUSIBLE_MAX:
        return False
    if (
        delta is not None
        and delta != MISSING_GREEK_SENTINEL
        and math.isfinite(delta)
        and abs(delta) >= DELTA_DEEP_ABS_FOR_GAMMA
        and gamma > GAMMA_DEEP_DELTA_MAX
    ):
        return False
    return True


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
        vol = float_nonnegative_or_none(ct.get("totalVolume"))  # volume: 0 valid, negatives are corruption
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
        gamma_ok = gamma_is_plausible(gamma, delta)

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


def pick_pin_and_strength(
    exposures: Dict[float, dict], strikes: List[float]
) -> tuple[float | None, float | None]:
    """RC-124: THE standard gamma pin — max TOTAL gamma (|call GEX$| + |put GEX$|) — plus its
    decisiveness.

    This is SpotGamma's Absolute Gamma / "sticky pin" definition and the Avellaneda–Lipkin
    mechanism: hedging MAGNITUDE pins price regardless of net sign, so calls-plus-puts is the
    magnet measure. The previous pin used the NET book (calls minus puts), which can crown a
    put-heavy strike while the true two-sided magnet sits elsewhere — that measure lives on,
    honestly named, as net_gex_peak (pick_net_gex_peak_strike below).

    strength_pct = the leader's margin over the runner-up on the same metric. A 1% lead is a
    coin flip and the label should say so; a 40% lead is a real magnet.
    Fail-closed: no dollarized GEX -> (None, None), never a raw-gamma fallback.
    """
    if not exposures_have_dollar_gex(exposures):
        return None, None
    s, v = _pick_strike_max_metric(exposures, strikes, total_gex_dollars_at_strike)
    if s is None or v is None or v <= 0:
        return None, None
    second = 0.0
    for k in strikes:
        if float(k) == s:
            continue
        t = total_gex_dollars_at_strike(exposures.get(k, {}))
        if t is not None and t > second:
            second = t
    return round(s, 2), round((v - second) / v * 100.0, 1)


def pick_net_gex_peak_strike(
    exposures: Dict[float, dict],
    strikes: List[float],
    *,
    institutional: bool = True,
) -> float | None:
    """
    Net-GEX peak: strike with largest |net GEX$| per 1% (calls minus puts).
    RC-124: this WAS displayed as "gamma pin" — a non-standard use of that name; the standard
    pin is total gamma (pick_pin_and_strength). The net peak remains a real measure of where
    the SIGNED book concentrates, and it keeps its row under its own name.
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


def pick_key_delta_strike(
    exposures: Dict[float, dict], strikes: List[float]
) -> float | None:
    """Key Delta Strike: largest total delta notional (|call DEX$| + |put DEX$|).

    Institutional only — no raw-delta fallback: delta notional needs spot, and a
    unit mix here would rank strikes on incomparable numbers.
    """
    if not exposures_have_dollar_gex(exposures):
        return None

    def _total_dex(b: dict) -> float | None:
        c = bucket_metric_abs(b, "call_dex_dollars")
        p = bucket_metric_abs(b, "put_dex_dollars")
        if c is None and p is None:
            return None
        return (c or 0.0) + (p or 0.0)

    s, _ = _pick_strike_max_metric(exposures, strikes, _total_dex)
    return round(s, 2) if s is not None else None


def pick_volatility_point_strikes(
    exposures: Dict[float, dict], strikes: List[float]
) -> tuple[float | None, float | None]:
    """(HVP, LVP): strike holding the most NEGATIVE / most POSITIVE net GEX$.

    Signed extremes, not magnitudes: HVP exists only where net dealer gamma is
    actually negative at some strike (amplification pocket), LVP only where
    positive (damping pocket). A one-sided chain returns None for the absent side.
    """
    if not exposures_have_dollar_gex(exposures):
        return None, None
    hvp_s: float | None = None
    hvp_v: float | None = None
    lvp_s: float | None = None
    lvp_v: float | None = None
    for s in strikes:
        v = net_gex_dollars_at_strike(exposures.get(s, {}))
        if v is None:
            continue
        if v < 0 and (hvp_v is None or v < hvp_v):
            hvp_s, hvp_v = float(s), float(v)
        if v > 0 and (lvp_v is None or v > lvp_v):
            lvp_s, lvp_v = float(s), float(v)
    return (
        round(hvp_s, 2) if hvp_s is not None else None,
        round(lvp_s, 2) if lvp_s is not None else None,
    )


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
    now=None,
) -> dict:
    """
    Compute dealer net charm exposure for a given expiry.

    CHARM = dDelta/dt — the rate at which dealer delta hedges decay with time.
    As expiry approaches, dealers must unwind their delta hedges. The NET direction
    of that unwind creates mechanical buying or selling pressure independent of price.

    Formula ACTUALLY IMPLEMENTED (see line ~788) — corrected 2026-07-19 to match the code:

        charm_unit = -phi(d1) * d2 / (2*T)          # delta per YEAR
        d1 = [ln(S/K) + (iv^2/2)*T] / (iv*sqrt(T))
        d2 = d1 - iv*sqrt(T)
        phi = standard normal PDF

    Relation to the textbook (Haug) charm, dDelta/dT for a call with q=0:

        dDelta/dT = -phi(d1) * [ r/(iv*sqrt(T)) - d2/(2T) ]

    Ours is dDelta/dt (CALENDAR time — as the trading day passes and T shrinks), with the
    r/(iv*sqrt(T)) term DELIBERATELY OMITTED because it explodes as T->0 (0DTE). At r=0
    that leaves  charm = +phi(d1) * d2 / (2T)  — exactly the formula above evaluated at
    r=0, which IS the calendar-time charm.
    SIGN CORRECTED 2026-07-25: a prior revision negated this to -phi*d2/(2T) on the claim
    "ours = -dDelta/dT", which INVERTED the direction — charm_direction reported "buying"
    when the dealer flow was selling (measured: sign-inverted vs the correct convention on
    70-79% of real SPY/QQQ/IWM states, exact-negation of the per-strike bs_charm path). A
    direct finite-difference of Black-Scholes delta as calendar time advances,
    (delta(T-1d)-delta(T))/dt, proves calendar charm = +phi*d2/(2T) (= math_levels.bs_charm
    at r=0) for ATM/ITM/OTM alike. The r-omission still costs accuracy that grows with T and
    rate (~6% 0DTE ATM, ~17% 7d, ~71% 3-month ATM at r=0.05); acceptable for the near-expiry
    use this feeds. The scalar here and the per-strike compute_charm_by_strike agree on
    DIRECTION and, since RC-42 unified both on time_et.time_to_expiry_years, on T as well —
    the once-tracked "hours-to-close vs 0.5-day floor" magnitude gap no longer exists in
    code (RC-179 closed it as a stale claim; parity measured at 0.02% on a real 0DTE book).

    NOTE: the ``rate`` parameter is therefore NOT used in the charm computation.

    Put charm: with q=0, Delta_put = Delta_call - 1, and the constant vanishes under
    d/dt, so charm_put == charm_call. That identity is why both sides use one formula.
    AGGREGATION IS DEALER-SIGNED (RC-179, convention pinned 2026-08-01 by operator order):
    ``net = call_charm - put_charm`` — the SAME +call/-put dealer book assumption as net
    GEX and the per-strike compute_charm_by_strike path, so ``net_charm_daily`` IS a
    dealer-signed directional flow and its sign may be read as dealer direction. An older
    revision of this paragraph claimed the two sides were summed with the same sign; the
    code below never did that after the 2026-07-25 correction, and the claim survived only
    in prose. MEASURED parity on the real SPY 2026-07-31 0DTE book (put-heavy, 782,222 put
    OI vs 530,996 call): scalar -3,529,621.8 vs per-strike dealer-signed sum -3,528,882.8
    (0.02%, the scalar's extra plausibility gates account for the gap), against a same-sign
    gross of +5,907,087.6 — the sign itself is the proof the dealer convention is live.
    Locked by tests/test_charm_sign_finite_difference.py (parity + put-heavy sign-flip).

    Dealer position: market makers are typically SHORT options (sold to retail).
    SHORT call → delta hedge = SHORT stock. As charm decays, they BUY back stock.
    SHORT put  → delta hedge = LONG stock. As charm decays, they SELL stock.
    Net charm > 0 → net dealer delta buying  → Bullish flow
    Net charm < 0 → net dealer delta selling → Bearish flow

    drift_toward_strike: institutional pin from pick_pin_and_strength (caller-supplied).
    Charm flow direction is independent of pin location.

    Returns:
        net_charm_daily  : net delta-equivalents unwound per day (negative = selling)
        charm_direction  : "buying" | "selling" | "neutral"  (for signals engine)
        drift_toward     : drift_toward_strike when provided
        gamma_pin        : same as drift_toward
        contracts_used   : number of contracts that contributed
    """
    import math as _m

    try:
        _target_exp = str(expiry)[:10]
        if len(_target_exp) != 10:
            _target_exp = None
    except Exception:
        _target_exp = None

    # SINGLE SOURCE of T: intraday time-to-session-close (time_et.time_to_expiry_years),
    # ACT/365, from `now` (defaults to now_et()). Replaces the old hours-to-close / day-count
    # split — the 0DTE branch only approximated it (hardcoded 16:00, 0.5h floor) and the
    # dte/365 branch ignored the intraday fraction entirely, so the two charm engines
    # disagreed near expiry (RC-42 / RC-37; validated against Schwab-reported gamma).
    from time_et import time_to_expiry_years as _tte

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
        delta   = _f(ct.get("delta"))
        iv      = _f(ct.get("volatility"))
        oi      = _f(ct.get("openInterest"))
        mult    = _f(ct.get("multiplier"))

        if gamma is None or strike is None:
            _skip_fields += 1
            continue
        if oi is None or oi <= 0:
            _skip_oi += 1
            continue
        if mult is None or mult <= 0:
            _skip_mult += 1
            continue
        if not gamma_is_plausible(gamma, delta):
            _skip_gamma += 1
            continue
        if iv is None or iv <= 0 or iv == MISSING_GREEK_SENTINEL or not math.isfinite(iv):
            _skip_iv += 1
            continue

        T = _tte(ct.get("expirationDate"), now=now)
        if T is None or T <= 0:
            _skip_T += 1
            continue

        iv_dec = schwab_iv_to_sigma(iv)
        if iv_dec is None or iv_dec <= 0:
            _skip_iv += 1
            continue
        S      = float(spot)
        K      = float(strike)

        # charm = dDelta/dt (CALENDAR time, i.e. as the trading day passes and T shrinks):
        #   charm = +phi(d1) * d2 / (2*T)          (with the r/(iv*sqrt(T)) term dropped for
        #                                           0DTE stability; T floor guards the rest)
        #
        # SIGN CORRECTED 2026-07-25: the prior form was -phi(d1)*d2/(2T) — the exact
        # NEGATIVE of calendar-time charm, so charm_direction was systematically INVERTED
        # ("buying" reported when dealer flow was actually selling). Proven by a direct
        # finite-difference of Black-Scholes delta as calendar time advances
        # (delta(T-1d) - delta(T)) / dt: for ATM/ITM/OTM/slight-ITM/slight-OTM the sign
        # matched +phi*d2/(2T) in every case (= math_levels.bs_charm at r=0, itself
        # finite-difference verified). This aligns the scalar net_charm with the per-strike
        # compute_charm_by_strike / bs_charm path (which was already correct and feeds the
        # charm walls), so the two charm faucets now agree on direction.
        #
        # Units: delta/year per unit contract. Scale to daily: weighted = charm/year/365*OI*mult
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

        # charm per unit in delta/year (calendar-time; sign matches bs_charm — see above)
        charm_unit = phi_d1 * d2 / (2.0 * T)

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
        del weighted  # summed with the dealer convention below, never here

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
            "gamma_pin": drift_toward_strike,
            "contracts_used": 0,
            "error": _err,
        }

    # DEALER SIGN CONVENTION (fixed 2026-07-19 — was `call_charm + put_charm`).
    #
    # charm_put == charm_call per contract (q=0), so summing the two sides produced an
    # OI-WEIGHTED MAGNITUDE with no dealer direction in it, while `charm_direction`
    # below labelled its sign "buying"/"selling" and fed that to the signals engine.
    # A prior comment claimed the sign difference was "captured in net_delta" — net_delta
    # is never referenced in this function, so no such compensation occurred.
    #
    # Charm exposure must use the SAME dealer book assumption as net GEX (+call / -put;
    # see math_levels.compute_gamma_profile). Per-strike charm exposure with this
    # convention is standard institutional practice (SpotGamma / Unusual Whales publish
    # it, and attribute the end-of-day pin to charm pressure).
    net = call_charm - put_charm

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

    gamma_pin = drift_toward_strike

    return {
        "net_charm_daily": round(net, 2),
        "call_charm_daily": round(call_charm, 2),
        "put_charm_daily": round(put_charm, 2),
        "charm_direction": direction,
        "charm_magnitude": magnitude,
        "drift_toward": gamma_pin,
        "gamma_pin": gamma_pin,
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

