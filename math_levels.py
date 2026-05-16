"""
math_levels.py
Chartable key-level engine — walls, pins, inflections, support/resistance
derived from options exposure structure.

Phase 2 extraction from math_exposure.py per Extraction Blueprint v1.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from math_exposure_core import (
    ExposureRow,
    KEY_LEVEL_STRIKE_WINDOW,
    _f,
    _nearest_strike,
    _window_strikes,
    aggregate_net_dex,
    aggregate_net_gex,
    exposures_have_dollar_gex,
    gex_magnitude_label,
    gex_regime_label,
    key_level_strikes_with_gamma,
    key_level_strikes_with_oi,
    net_gex_dollars_at_strike,
    pick_delta_wall_strikes,
    pick_gamma_pin_strike,
    pick_gamma_wall_strikes,
    pick_hvl_strike,
    total_gex_dollars_at_strike,
    total_gamma_raw_at_strike,
)


# ── Data classes ──────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class WallsRow:
    label: str
    window: int | None

    call_gamma_wall: float | None
    call_gamma_strength: float | None
    put_gamma_wall: float | None
    put_gamma_strength: float | None
    dom_gamma_side: str
    dom_gamma_wall: float | None
    dom_gamma_strength: float | None

    call_delta_wall: float | None
    call_delta_strength: float | None
    put_delta_wall: float | None
    put_delta_strength: float | None
    dom_delta_side: str
    dom_delta_wall: float | None
    dom_delta_strength: float | None

    call_oi_wall: float | None
    call_oi_strength: float | None
    put_oi_wall: float | None
    put_oi_strength: float | None
    dom_oi_side: str
    dom_oi_wall: float | None
    dom_oi_strength: float | None
    
    # Pin levels (near spot, computed on CONSENSUS row)
    call_gamma_pin: float | None = None
    call_gamma_pin_strength: float | None = None
    put_gamma_pin: float | None = None
    put_gamma_pin_strength: float | None = None
    call_delta_pin: float | None = None
    call_delta_pin_strength: float | None = None
    put_delta_pin: float | None = None
    put_delta_pin_strength: float | None = None
    call_oi_pin: float | None = None
    call_oi_pin_strength: float | None = None
    put_oi_pin: float | None = None
    put_oi_pin_strength: float | None = None
    call_vanna_wall: float | None = None
    call_vanna_strength: float | None = None
    put_vanna_wall: float | None = None
    put_vanna_strength: float | None = None

@dataclass(frozen=True)
class TotalsRow:
    label: str
    window: int | None

    call_gamma: float | None
    put_gamma: float | None
    net_gamma: float | None

    call_delta: float | None
    put_delta: float | None
    net_delta: float | None

    call_oi: float | None
    put_oi: float | None
    net_oi: float | None

    pcr_oi: float | None
    atm_iv: float | None
    skew_proxy: float | None


# ── Constants ─────────────────────────────────────────────────────────────────

WALL_MIN_MULT = 1.5
APPROACH_PTS  = 1.5

# ── Pin / inflection / OI helpers ─────────────────────────────────────────────

def _pick_gamma_pin(exposures: Dict[float, dict], strikes: List[float]) -> float | None:
    """Institutional gamma pin — delegates to math_exposure_core.pick_gamma_pin_strike."""
    return pick_gamma_pin_strike(exposures, strikes)

def _pick_oi_center(exposures: Dict[float, dict], strikes: List[float]) -> float | None:
    # strike with max total OI (call+put)
    best = None
    best_val = None
    for s in strikes:
        b = exposures.get(s, {})
        call_oi = b.get("call_oi")
        put_oi = b.get("put_oi")
        if call_oi is None and put_oi is None:
            continue
        tot = (float(call_oi) if call_oi is not None else 0.0) + (float(put_oi) if put_oi is not None else 0.0)
        if tot <= 0:
            continue
        if best is None or (best_val is not None and tot > best_val):
            best = s
            best_val = tot
    return best

def _pick_inflection_closest_zero(exposures: Dict[float, dict], strikes: List[float], key: str) -> float | None:
    # Find strike where net exposure is closest to zero (dollar GEX/DEX when available).
    if exposures_have_dollar_gex(exposures):
        if key == "net_gamma":
            key = "net_gex_1pct"
        elif key == "net_delta":
            key = "net_dex_dollars"
    best = None
    best_val = None
    for s in strikes:
        v0 = exposures.get(s, {}).get(key)
        if v0 is None:
            continue
        v = abs(v0)
        if best is None or (best_val is not None and v < best_val):
            best = s
            best_val = v
    return best

def _pin_strength(exposures: Dict[float, dict], gamma_pin: float | None, strikes: List[float]) -> str:
    if gamma_pin is None:
        return "Very Low"
    b = exposures.get(gamma_pin, {}) or exposures.get(float(gamma_pin), {})
    if exposures_have_dollar_gex(exposures):
        gp = abs(net_gex_dollars_at_strike(b))
        vals = [abs(net_gex_dollars_at_strike(exposures.get(s, {}))) for s in strikes]
    else:
        gp = abs(b.get("net_gamma") or 0.0)
        vals = [abs(exposures.get(s, {}).get("net_gamma") or 0.0) for s in strikes]
    if gp <= 0:
        return "Very Low"

    vals = [v for v in vals if v > 0]
    if not vals:
        return "Very Low"
    vals_sorted = sorted(vals)
    med = vals_sorted[len(vals_sorted)//2]
    if med <= 0:
        return "Very Low"

    ratio = gp / med
    if ratio >= 3.0:
        return "High"
    if ratio >= 2.0:
        return "Med"
    if ratio >= 1.25:
        return "Low"
    return "Very Low"

def _bias_from_net(net_gamma: float | None, net_delta: float | None, pin_strength: str) -> str:
    if net_gamma is None or net_delta is None:
        return "Neutral"
    if pin_strength in ("High", "Med"):
        if net_delta > 0 and net_gamma > 0:
            return "Bull"
        if net_delta < 0 and net_gamma > 0:
            return "Bear"
        if net_gamma < 0:
            return "Expansion"
    if pin_strength == "Very Low":
        return "Chaos Zone"
    if net_delta > 0:
        return "Tilt Bull"
    if net_delta < 0:
        return "Tilt Bear"
    return "Balanced"


# ── Summary rows ──────────────────────────────────────────────────────────────

def build_summary_rows(
    exposures: Dict[float, dict],
    spot: float,
    *,
    windows: List[int],
) -> List[ExposureRow]:
    strikes_all = sorted(list(exposures.keys()))
    if not strikes_all:
        return [
            ExposureRow("CONSENSUS", None, None, None, None, None, None, None, "Very Low", "Neutral"),
            *[
                ExposureRow(f"±{w}", w, None, None, None, None, None, None, "Very Low", "Neutral")
                for w in windows
            ],
        ]

    def aggregate(strikes: List[float]) -> tuple[float | None, float | None]:
        return aggregate_net_gex(exposures, strikes), aggregate_net_dex(exposures, strikes)

    rows: List[ExposureRow] = []

    cons_strikes = strikes_all
    cons_gamma_strikes = key_level_strikes_with_gamma(exposures) or cons_strikes
    cons_net_gamma, cons_net_delta = aggregate(cons_strikes)
    cons_gamma_pin = _pick_gamma_pin(exposures, cons_gamma_strikes)
    cons_delta_inf = _pick_inflection_closest_zero(exposures, cons_gamma_strikes, "net_delta")
    cons_gamma_inf = _pick_inflection_closest_zero(exposures, cons_gamma_strikes, "net_gamma")
    cons_oi_center = _pick_oi_center(exposures, cons_strikes)
    cons_pin_strength = _pin_strength(exposures, cons_gamma_pin, cons_gamma_strikes)
    cons_bias = _bias_from_net(cons_net_gamma, cons_net_delta, cons_pin_strength)
    rows.append(
        ExposureRow(
            "CONSENSUS",
            None,
            cons_net_gamma,
            cons_net_delta,
            cons_gamma_pin,
            cons_delta_inf,
            cons_gamma_inf,
            cons_oi_center,
            cons_pin_strength,
            cons_bias,
        )
    )

    for w in windows:
        ws = _window_strikes(strikes_all, spot, w)
        net_gamma, net_delta = aggregate(ws)
        gamma_pin = _pick_gamma_pin(exposures, ws)
        delta_inf = _pick_inflection_closest_zero(exposures, ws, "net_delta")
        gamma_inf = _pick_inflection_closest_zero(exposures, ws, "net_gamma")
        oi_center = _pick_oi_center(exposures, ws)
        pin_strength = _pin_strength(exposures, gamma_pin, ws)
        bias = _bias_from_net(net_gamma, net_delta, pin_strength)
        rows.append(
            ExposureRow(
                f"±{w}",
                w,
                net_gamma,
                net_delta,
                gamma_pin,
                delta_inf,
                gamma_inf,
                oi_center,
                pin_strength,
                bias,
            )
        )

    return rows


# ── Wall selection / dominance helpers ────────────────────────────────────────

def _pick_wall_abs(exposures: Dict[float, dict], strikes: List[float], key: str) -> tuple[float | None, float | None]:
    """
    Returns (strike, abs_strength) where abs_strength is max abs(key) across strikes.
    """
    best_s = None
    best_v = None
    for s in strikes:
        v0 = exposures.get(s, {}).get(key)
        if v0 is None:
            continue
        v = abs(float(v0))
        if best_s is None or (best_v is not None and v > best_v):
            best_s = s
            best_v = v
    return best_s, best_v

def _pick_wall_pos(exposures: Dict[float, dict], strikes: List[float], key: str) -> tuple[float | None, float | None]:
    """
    Returns (strike, strength) where strength is max positive(key) across strikes.
    For OI walls where values are non-negative.
    """
    best_s = None
    best_v = None
    for s in strikes:
        v0 = exposures.get(s, {}).get(key) or 0.0
        v = float(v0)
        if v <= 0:
            continue
        if best_s is None or (best_v is not None and v > best_v):
            best_s = s
            best_v = v
    return best_s, best_v

def _dominant(call_strike, call_strength, put_strike, put_strength) -> tuple[str, float | None, float | None]:
    """
    Chooses dominant side by strength (absolute for exposures).
    """
    c = call_strength
    p = put_strength
    if c is None and p is None:
        return "", None, None
    if p is None or (c is not None and c >= p):
        return "CALL", call_strike, c
    return "PUT", put_strike, p


# ── Wall rows builder ────────────────────────────────────────────────────────

def build_walls_rows(
    exposures: Dict[float, dict],
    spot: float,
    *,
    windows: List[int],
) -> List[WallsRow]:
    strikes_all = sorted(list(exposures.keys()))
    if not strikes_all:
        return [
            WallsRow("CONSENSUS", None, None, None, None, None, "", None, None,
                     None, None, None, None, "", None, None,
                     None, None, None, None, "", None, None)
        ]

    def strikes_for(window: int | None) -> List[float]:
        if window is None:
            return strikes_all
        return _window_strikes(strikes_all, spot, window)

    out: List[WallsRow] = []

    # CONSENSUS
    for label, w in [("CONSENSUS", None)] + [(f"±{x}", x) for x in windows]:
        sset = strikes_for(w)

        # Gamma / delta walls — institutional dollar metrics when spot known
        if label == "CONSENSUS" and KEY_LEVEL_STRIKE_WINDOW is None:
            g_strikes = key_level_strikes_with_gamma(exposures) or sset
            (cg_s, cg_v), (pg_s, pg_v) = pick_gamma_wall_strikes(exposures, g_strikes)
            (cd_s, cd_v), (pd_s, pd_v) = pick_delta_wall_strikes(exposures, g_strikes)
        else:
            cg_s, cg_v = _pick_wall_abs(exposures, sset, "call_gamma")
            pg_s, pg_v = _pick_wall_abs(exposures, sset, "put_gamma")
            cd_s, cd_v = _pick_wall_abs(exposures, sset, "call_delta")
            pd_s, pd_v = _pick_wall_abs(exposures, sset, "put_delta")
        domg_side, domg_s, domg_v = _dominant(cg_s, cg_v, pg_s, pg_v)
        domd_side, domd_s, domd_v = _dominant(cd_s, cd_v, pd_s, pd_v)

        # OI walls: max OI (non-negative)
        coi_s, coi_v = _pick_wall_pos(exposures, sset, "call_oi")
        poi_s, poi_v = _pick_wall_pos(exposures, sset, "put_oi")
        domoi_side, domoi_s, domoi_v = _dominant(coi_s, coi_v, poi_s, poi_v)

        # Vanna walls
        cv_s, cv_v = _pick_wall_abs(exposures, sset, "call_vanna")
        pv_s, pv_v = _pick_wall_abs(exposures, sset, "put_vanna")

        # Pin levels (near spot). Only populated on CONSENSUS row.
        call_gamma_pin = call_gamma_pin_strength = None
        put_gamma_pin = put_gamma_pin_strength = None
        call_delta_pin = call_delta_pin_strength = None
        put_delta_pin = put_delta_pin_strength = None
        call_oi_pin = call_oi_pin_strength = None
        put_oi_pin = put_oi_pin_strength = None
        if label == "CONSENSUS":
            pin_window = windows[0] if windows else 2
            pin_set = _window_strikes(strikes_all, spot, pin_window)

            def _pick_pin(key: str) -> tuple[float | None, float | None]:
                best_s: float | None = None
                best_v: float | None = None
                best_abs = -1.0
                for s in pin_set:
                    v = exposures.get(s, {}).get(key)
                    if v is None:
                        continue
                    a = abs(v)
                    if (a > best_abs + 1e-12) or (abs(a - best_abs) <= 1e-12 and (best_s is None or abs(s - spot) < abs(best_s - spot))):
                        best_abs = a
                        best_s = s
                        best_v = v
                return best_s, best_v

            call_gamma_pin, call_gamma_pin_strength = _pick_pin("call_gamma")
            put_gamma_pin, put_gamma_pin_strength = _pick_pin("put_gamma")
            call_delta_pin, call_delta_pin_strength = _pick_pin("call_delta")
            put_delta_pin, put_delta_pin_strength = _pick_pin("put_delta")
            call_oi_pin, call_oi_pin_strength = _pick_pin("call_oi")
            put_oi_pin, put_oi_pin_strength = _pick_pin("put_oi")

        out.append(WallsRow(
            label=label,
            window=w,

            call_gamma_wall=cg_s,
            call_gamma_strength=cg_v,
            put_gamma_wall=pg_s,
            put_gamma_strength=pg_v,
            dom_gamma_side=domg_side,
            dom_gamma_wall=domg_s,
            dom_gamma_strength=domg_v,

            call_delta_wall=cd_s,
            call_delta_strength=cd_v,
            put_delta_wall=pd_s,
            put_delta_strength=pd_v,
            dom_delta_side=domd_side,
            dom_delta_wall=domd_s,
            dom_delta_strength=domd_v,

            call_oi_wall=coi_s,
            call_oi_strength=coi_v,
            put_oi_wall=poi_s,
            put_oi_strength=poi_v,
            dom_oi_side=domoi_side,
            dom_oi_wall=domoi_s,
            dom_oi_strength=domoi_v,

            call_gamma_pin=call_gamma_pin,
            call_gamma_pin_strength=call_gamma_pin_strength,
            put_gamma_pin=put_gamma_pin,
            put_gamma_pin_strength=put_gamma_pin_strength,
            call_delta_pin=call_delta_pin,
            call_delta_pin_strength=call_delta_pin_strength,
            put_delta_pin=put_delta_pin,
            put_delta_pin_strength=put_delta_pin_strength,
            call_oi_pin=call_oi_pin,
            call_oi_pin_strength=call_oi_pin_strength,
            put_oi_pin=put_oi_pin,
            put_oi_pin_strength=put_oi_pin_strength,

            call_vanna_wall=cv_s,
            call_vanna_strength=cv_v,
            put_vanna_wall=pv_s,
            put_vanna_strength=pv_v,
        ))

    return out


# ── Totals rows builder ──────────────────────────────────────────────────────
# Imports for IV extraction (from math_volatility)
from math_volatility import _spot_atm_strike, _extract_iv_for_strike

def build_totals_rows(
    exposures: Dict[float, dict],
    spot: float,
    *,
    windows: List[int],
    contracts_for_iv: List[dict],
) -> List[TotalsRow]:
    strikes_all = sorted(list(exposures.keys()))
    if not strikes_all:
        return [
            TotalsRow("CONSENSUS", None, None, None, None, None, None, None, None, None, None, None, None, None)
        ]

    def strikes_for(window: int | None) -> List[float]:
        if window is None:
            return strikes_all
        return _window_strikes(strikes_all, spot, window)

    out: List[TotalsRow] = []

    for label, w in [("CONSENSUS", None)] + [(f"±{x}", x) for x in windows]:
        sset = strikes_for(w)

        cg = 0.0
        pg = 0.0
        cd = 0.0
        pd = 0.0
        coi = 0.0
        poi = 0.0
        any_row = False

        for s in sset:
            b = exposures.get(s, {})
            cg += float(b.get("call_gamma") or 0.0)
            pg += float(b.get("put_gamma") or 0.0)
            cd += float(b.get("call_delta") or 0.0)
            pd += float(b.get("put_delta") or 0.0)
            call_oi = b.get("call_oi")
            put_oi = b.get("put_oi")
            if call_oi is not None:
                coi += float(call_oi)
            if put_oi is not None:
                poi += float(put_oi)
            any_row = True

        if not any_row:
            cg = pg = cd = pd = coi = poi = 0.0

        ng = cg - pg
        nd = cd - pd
        noi = coi - poi

        pcr = (poi / coi) if coi > 0 else None

        # ATM IV + skew proxy
        atm = _spot_atm_strike(sset, spot)
        atm_iv = None
        skew = None
        if atm is not None:
            c_iv, p_iv = _extract_iv_for_strike(contracts_for_iv, atm)
            if c_iv is not None and p_iv is not None:
                atm_iv = (c_iv + p_iv) / 2.0
                skew = c_iv - p_iv
            elif c_iv is not None:
                atm_iv = c_iv
            elif p_iv is not None:
                atm_iv = p_iv

        out.append(TotalsRow(
            label=label,
            window=w,

            call_gamma=cg,
            put_gamma=pg,
            net_gamma=ng,

            call_delta=cd,
            put_delta=pd,
            net_delta=nd,

            call_oi=coi,
            put_oi=poi,
            net_oi=noi,

            pcr_oi=pcr,
            atm_iv=atm_iv,
            skew_proxy=skew,
        ))

    return out


# ── Pin zone classification ──────────────────────────────────────────────────

def is_pin_zone(zone: str | None) -> bool:
    return (zone or "").startswith("pin")


# ── Parity / synthetic forward ───────────────────────────────────────────────

def parity_f_minus_spot_from_contracts(
    contracts,
    *,
    spot: float,
    dte_max = None,
) -> float:
    try:
        spot_f = float(spot)
    except Exception:
        return 0.0
    use = []
    for c in contracts or []:
        try:
            raw_dte = c.get("daysToExpiration")
            dte = int(float(raw_dte)) if raw_dte is not None else None
        except Exception:
            dte = None
        if dte_max is not None and dte != int(dte_max):
            continue
        use.append(c)
    if not use:
        return 0.0
    strikes = []
    for c in use:
        try:
            strikes.append(float(c.get("strikePrice")))
        except Exception:
            continue
    if not strikes:
        return 0.0
    strikes = sorted(set(strikes))
    atm = min(strikes, key=lambda k: (abs(k - spot_f), k))
    idx = strikes.index(atm)
    lo = max(0, idx - 2)
    hi = min(len(strikes) - 1, idx + 2)
    band = set(strikes[lo : hi + 1])

    def _mid(row):
        m = _f(row.get("mark"))
        if m is not None and m > 0:
            return m
        return None

    resids = []
    for k in band:
        calls = [c for c in use if str(c.get("putCall") or "").upper() == "CALL" and float(c.get("strikePrice") or -1) == k]
        puts = [c for c in use if str(c.get("putCall") or "").upper() == "PUT" and float(c.get("strikePrice") or -1) == k]
        if not calls or not puts: continue
        call_mid = _mid(calls[0])
        put_mid = _mid(puts[0])
        if call_mid is None or put_mid is None: continue
        resid = (call_mid - put_mid) - (spot_f - float(k))
        resids.append(float(resid))
    if not resids: return 0.0
    resids = sorted(resids)
    if len(resids) >= 5: resids = resids[1:-1]
    return float(sum(resids) / len(resids))


# ── Gamma Flip — zero-crossing of cumulative net GEX ─────────────────────────

def compute_gamma_flip(exposures_by_strike: Dict[float, dict], spot: float) -> float | None:
    """
    Find the price level where net gamma exposure crosses zero.

    Above gamma flip → positive gamma → dealers dampen movement (mean reversion).
    Below gamma flip → negative gamma → dealers amplify movement (acceleration).

    Method: Walk strikes near spot. Per-strike net_gamma = call_gamma - put_gamma.
    Below spot, puts dominate (negative). Above spot, calls dominate (positive).
    Find the zero-crossing and interpolate.

    Falls back to dollarized net_gex_1pct if net_gamma has no crossing.

    Returns strike price of the flip, or None if no crossing found.
    """
    if not exposures_by_strike or not spot:
        return None

    strikes = sorted(float(k) for k in exposures_by_strike.keys())
    if len(strikes) < 3:
        return None

    # Try per-strike net_gamma first (always available, no spot dependency)
    def _find_crossing(field: str) -> float | None:
        prev_strike = None
        prev_val = None
        for strike in strikes:
            bucket = exposures_by_strike.get(strike, {})
            val = float(bucket.get(field, 0) or 0)
            if val == 0:
                continue
            if prev_val is not None and prev_val * val < 0:
                denom = abs(val - prev_val)
                if denom > 0:
                    frac = abs(prev_val) / denom
                    flip = prev_strike + frac * (strike - prev_strike)
                    return round(flip, 2)
            prev_strike = strike
            prev_val = val
        return None

    # Institutional: prefer per-strike net_gex_1pct (dollar GEX) when populated.
    if exposures_have_dollar_gex(exposures_by_strike):
        result = _find_crossing("net_gex_1pct")
        if result is not None:
            return result

    # Fallback: per-strike net_gamma (γ×OI×mult)
    result = _find_crossing("net_gamma")
    if result is not None:
        return result

    # Last resort: cumulative net_gex_1pct along strike chain
    cum_gex = 0.0
    prev_strike = None
    prev_cum = None
    for strike in strikes:
        bucket = exposures_by_strike.get(strike, {})
        net_gex = float(bucket.get("net_gex_1pct", 0) or 0)
        cum_gex += net_gex
        if prev_cum is not None and prev_cum * cum_gex < 0:
            if abs(cum_gex - prev_cum) > 0:
                frac = abs(prev_cum) / abs(cum_gex - prev_cum)
                flip = prev_strike + frac * (strike - prev_strike)
                return round(flip, 2)
        prev_strike = strike
        prev_cum = cum_gex

    return None


# ── HVL — strike with largest total gamma (call + put) ───────────────────────

def _total_gamma_at_strike(bucket: dict, *, dollarized: bool = False) -> float:
    if dollarized or (
        float(bucket.get("call_gex_1pct", 0) or 0) != 0
        or float(bucket.get("put_gex_1pct", 0) or 0) != 0
    ):
        return total_gex_dollars_at_strike(bucket)
    return total_gamma_raw_at_strike(bucket)


def compute_hvl(exposures_by_strike: Dict[float, dict]) -> float | None:
    """
    High Volatility Level: strike with largest total gamma (|call|+|put| GEX$ or γ×OI×mult).
    Distinct from gamma pin (max |net GEX$|).
    """
    if not exposures_by_strike:
        return None
    strikes = key_level_strikes_with_gamma(exposures_by_strike)
    if not strikes:
        return None
    return pick_hvl_strike(exposures_by_strike, strikes)


def hvl_gamma_strength(exposures_by_strike: Dict[float, dict], hvl: float | None) -> float | None:
    if hvl is None:
        return None
    bucket = exposures_by_strike.get(hvl) or exposures_by_strike.get(float(hvl))
    if not bucket:
        return None
    v = _total_gamma_at_strike(bucket, dollarized=exposures_have_dollar_gex(exposures_by_strike))
    return v if v > 0 else None


# ── Max Pain — OI-weighted expiry settlement magnet ────────────────────────────

def compute_max_pain(exposures_by_strike: Dict[float, dict]) -> float | None:
    """
    Classic max pain: settlement strike that minimizes total ITM option holder payout.

    For each candidate settlement S on the actual strike grid:
      pain += max(0, S-K)*call_oi(K)*mult + max(0, K-S)*put_oi(K)*mult
    Uses bucket sums call_oi_mult / put_oi_mult (= Σ OI×multiplier per strike).
    """
    if not exposures_by_strike:
        return None
    strikes = key_level_strikes_with_oi(exposures_by_strike)
    if len(strikes) < 2:
        return None

    def _pain_at(settlement: float) -> float:
        pain = 0.0
        for k in strikes:
            b = exposures_by_strike.get(k, {})
            call_w = float(b.get("call_oi_mult") or 0.0)
            put_w = float(b.get("put_oi_mult") or 0.0)
            # Fail-closed per DFR-017: Schwab `multiplier` is the only legitimate
            # source for OI-weighted dollar payout. If a strike was built with
            # missing/invalid multiplier, oi_mult is 0 and the strike is excluded
            # from max-pain instead of getting a synthetic 100.
            if call_w <= 0 and put_w <= 0:
                continue
            if call_w > 0 and settlement > k:
                pain += (settlement - k) * call_w
            if put_w > 0 and settlement < k:
                pain += (k - settlement) * put_w
        return pain

    best_s: float | None = None
    best_pain: float | None = None
    for s in strikes:
        p = _pain_at(s)
        if best_pain is None or p < best_pain:
            best_pain = p
            best_s = s
    return round(best_s, 2) if best_s is not None else None


def max_pain_oi_strength(exposures_by_strike: Dict[float, dict], max_pain: float | None) -> float | None:
    if max_pain is None:
        return None
    b = exposures_by_strike.get(max_pain) or exposures_by_strike.get(float(max_pain))
    if not b:
        return None
    call_oi = float(b.get("call_oi") or 0.0)
    put_oi = float(b.get("put_oi") or 0.0)
    tot = call_oi + put_oi
    return tot if tot > 0 else None


# ── Low Gamma Void Zones — acceleration corridors ────────────────────────────

def compute_gamma_void_zones(
    exposures_by_strike: Dict[float, dict],
    spot: float,
    *,
    void_threshold_pct: float = 0.20,
    oi_threshold_pct: float = 0.25,
    min_width_strikes: int = 2,
) -> list:
    """
    Find contiguous strike regions where gamma exposure AND open interest are sparse.

    Per Derived Formula Dictionary: "Region where |GEX| is low AND OpenInterest is low."

    These are acceleration corridors — when price enters a void,
    dealer hedging weakens and price moves fast.

    Args:
        exposures_by_strike: strike → exposure bucket dict
        spot:                current spot price
        void_threshold_pct:  GEX below this fraction of max GEX = "void" (default 20%)
        oi_threshold_pct:    OI below this fraction of max OI = "void" (default 25%)
        min_width_strikes:   minimum number of consecutive void strikes to form a zone

    Returns:
        list of dicts: [{"upper": float, "lower": float, "width_pts": float,
                         "above_spot": bool, "avg_gex_pct": float}]
        Sorted by proximity to spot (nearest first).
    """
    if not exposures_by_strike:
        return []

    strikes = sorted(float(k) for k in exposures_by_strike.keys())
    if len(strikes) < 5:
        return []

    def _get_gex(bucket):
        """Same measure for void detection and avg_gex_pct (institutional dollar GEX when available)."""
        if exposures_have_dollar_gex(exposures_by_strike):
            return total_gex_dollars_at_strike(bucket)
        total_gamma = abs(float(bucket.get("call_gamma", 0) or 0)) + abs(float(bucket.get("put_gamma", 0) or 0))
        if total_gamma > 0:
            return total_gamma
        return abs(float(bucket.get("net_gex_1pct", 0) or 0))

    def _get_oi(bucket):
        """Get total open interest for a strike bucket."""
        call_oi = bucket.get("call_oi")
        put_oi = bucket.get("put_oi")
        if call_oi is None and put_oi is None:
            return None
        return (float(call_oi) if call_oi is not None else 0.0) + (float(put_oi) if put_oi is not None else 0.0)

    # Find max absolute GEX and max OI for threshold reference
    max_abs_gex = 0.0
    max_oi = 0.0
    for k in strikes:
        bucket = exposures_by_strike.get(k, {})
        gex = _get_gex(bucket)
        oi = _get_oi(bucket)
        if gex > max_abs_gex:
            max_abs_gex = gex
        if oi is not None and oi > max_oi:
            max_oi = oi

    if max_abs_gex == 0:
        return []

    gex_threshold = max_abs_gex * void_threshold_pct
    oi_threshold = max_oi * oi_threshold_pct if max_oi > 0 else 0

    # Mark each strike as void: BOTH low GEX AND low OI
    void_flags = []
    for k in strikes:
        bucket = exposures_by_strike.get(k, {})
        gex = _get_gex(bucket)
        oi = _get_oi(bucket)
        is_void = (gex < gex_threshold) and (oi is not None and oi < oi_threshold if max_oi > 0 else True)
        void_flags.append(is_void)

    # Find contiguous void regions
    zones = []
    in_void = False
    zone_start = None

    for i, is_void in enumerate(void_flags):
        if is_void and not in_void:
            zone_start = i
            in_void = True
        elif not is_void and in_void:
            # End of void region
            zone_len = i - zone_start
            if zone_len >= min_width_strikes:
                lower = strikes[zone_start]
                upper = strikes[i - 1]
                # Average GEX in the void as % of max
                avg_gex = 0.0
                for j in range(zone_start, i):
                    bucket = exposures_by_strike.get(strikes[j], {})
                    avg_gex += _get_gex(bucket)
                avg_gex = (avg_gex / zone_len) / max_abs_gex if zone_len > 0 else 0

                zones.append({
                    "lower": lower,
                    "upper": upper,
                    "width_pts": round(upper - lower, 2),
                    "above_spot": lower > spot,
                    "below_spot": upper < spot,
                    "contains_spot": lower <= spot <= upper,
                    "avg_gex_pct": round(avg_gex * 100, 1),
                    "dist_to_spot": round(min(abs(lower - spot), abs(upper - spot)), 2),
                })
            in_void = False

    # Handle void at end of chain
    if in_void:
        zone_len = len(strikes) - zone_start
        if zone_len >= min_width_strikes:
            lower = strikes[zone_start]
            upper = strikes[-1]
            avg_gex = 0.0
            for j in range(zone_start, len(strikes)):
                bucket = exposures_by_strike.get(strikes[j], {})
                avg_gex += _get_gex(bucket)
            avg_gex = (avg_gex / zone_len) / max_abs_gex if zone_len > 0 else 0

            zones.append({
                "lower": lower,
                "upper": upper,
                "width_pts": round(upper - lower, 2),
                "above_spot": lower > spot,
                "below_spot": upper < spot,
                "contains_spot": lower <= spot <= upper,
                "avg_gex_pct": round(avg_gex * 100, 1),
                "dist_to_spot": round(min(abs(lower - spot), abs(upper - spot)), 2),
            })

    # Sort by proximity to spot
    zones.sort(key=lambda z: z["dist_to_spot"])

    return zones


# ── Level Density — how crowded is the area around spot ──────────────────────

def compute_level_density(
    levels: dict,
    spot: float,
    *,
    radius_pts: float = 3.0,
) -> dict:
    """
    Count how many key levels exist within N points of spot.

    High density = congestion zone, expect choppy price action.
    Low density = clean runway, directional moves more likely.

    Args:
        levels: dict of level_name → price (e.g. {'call_gamma_wall': 580, 'put_gamma_wall': 570})
        spot:   current price
        radius_pts: radius in points to search (default 3.0)

    Returns dict with count, level_names, density_label.
    """
    if not levels or not spot:
        return {"count": 0, "level_names": [], "density_label": "unknown", "radius": radius_pts}

    nearby = []
    for name, price in levels.items():
        if price is None:
            continue
        try:
            p = float(price)
        except (ValueError, TypeError):
            continue
        if abs(p - spot) <= radius_pts:
            nearby.append(name)

    count = len(nearby)

    if count >= 5:
        label = "congested"
    elif count >= 3:
        label = "moderate"
    elif count >= 1:
        label = "light"
    else:
        label = "clear"

    return {
        "count": count,
        "level_names": nearby,
        "density_label": label,
        "radius": radius_pts,
    }



