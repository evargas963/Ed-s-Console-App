"""
math_levels.py
Chartable key-level engine — walls, pins, inflections, support/resistance
derived from options exposure structure.

Phase 2 extraction from math_exposure.py per Extraction Blueprint v1.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from math_exposure_core import ExposureRow, _f, _nearest_strike, _window_strikes


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
    # strike with max abs NET gamma
    best = None
    best_val = None
    for s in strikes:
        ng = exposures.get(s, {}).get("net_gamma")
        if ng is None:
            continue
        v = abs(ng)
        if best is None or (best_val is not None and v > best_val):
            best = s
            best_val = v
    return best

def _pick_oi_center(exposures: Dict[float, dict], strikes: List[float]) -> float | None:
    # strike with max total OI (call+put)
    best = None
    best_val = None
    for s in strikes:
        b = exposures.get(s, {})
        tot = (b.get("call_oi") or 0.0) + (b.get("put_oi") or 0.0)
        if tot <= 0:
            continue
        if best is None or (best_val is not None and tot > best_val):
            best = s
            best_val = tot
    return best

def _pick_inflection_closest_zero(exposures: Dict[float, dict], strikes: List[float], key: str) -> float | None:
    # Find strike where exposure (net_delta or net_gamma) is closest to 0
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
    gp = abs(exposures.get(gamma_pin, {}).get("net_gamma") or 0.0)
    if gp <= 0:
        return "Very Low"

    vals = [abs(exposures.get(s, {}).get("net_gamma") or 0.0) for s in strikes]
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
        ng = 0.0
        nd = 0.0
        any_g = False
        any_d = False
        for s in strikes:
            b = exposures.get(s, {})
            if b.get("net_gamma") is not None:
                ng += float(b.get("net_gamma") or 0.0)
                any_g = True
            if b.get("net_delta") is not None:
                nd += float(b.get("net_delta") or 0.0)
                any_d = True
        return (ng if any_g else None), (nd if any_d else None)

    rows: List[ExposureRow] = []

    cons_strikes = strikes_all
    cons_net_gamma, cons_net_delta = aggregate(cons_strikes)
    cons_gamma_pin = _pick_gamma_pin(exposures, cons_strikes)
    cons_delta_inf = _pick_inflection_closest_zero(exposures, cons_strikes, "net_delta")
    cons_gamma_inf = _pick_inflection_closest_zero(exposures, cons_strikes, "net_gamma")
    cons_oi_center = _pick_oi_center(exposures, cons_strikes)
    cons_pin_strength = _pin_strength(exposures, cons_gamma_pin, cons_strikes)
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

        # Gamma walls: use exposure buckets call_gamma / put_gamma
        cg_s, cg_v = _pick_wall_abs(exposures, sset, "call_gamma")
        pg_s, pg_v = _pick_wall_abs(exposures, sset, "put_gamma")
        domg_side, domg_s, domg_v = _dominant(cg_s, cg_v, pg_s, pg_v)

        # Delta walls
        cd_s, cd_v = _pick_wall_abs(exposures, sset, "call_delta")
        pd_s, pd_v = _pick_wall_abs(exposures, sset, "put_delta")
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
            coi += float(b.get("call_oi") or 0.0)
            poi += float(b.get("put_oi") or 0.0)
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
        use = list(contracts or [])
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
        for key in ("mark", "mid", "last"):
            v = row.get(key)
            try:
                if v is None: continue
                x = float(v)
                if x > 0: return x
            except Exception: continue
        try:
            b = float(row.get("bid") or 0)
            a = float(row.get("ask") or 0)
            if a > 0 and b >= 0: return (a + b) / 2.0
        except Exception: pass
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

    # Primary: per-strike net_gamma (call_gamma - put_gamma)
    result = _find_crossing("net_gamma")
    if result is not None:
        return result

    # Fallback: cumulative net_gex_1pct (dollarized, needs spot)
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

    # Use total gamma (call + put, always available) as primary measure.
    # Falls back to dollarized net_gex_1pct if total gamma is zero.
    def _get_gex(bucket):
        """Get absolute gamma exposure for a strike bucket."""
        total_gamma = abs(float(bucket.get("call_gamma", 0) or 0)) + abs(float(bucket.get("put_gamma", 0) or 0))
        if total_gamma > 0:
            return total_gamma
        return abs(float(bucket.get("net_gex_1pct", 0) or 0))

    def _get_oi(bucket):
        """Get total open interest for a strike bucket."""
        return float(bucket.get("call_oi", 0) or 0) + float(bucket.get("put_oi", 0) or 0)

    # Find max absolute GEX and max OI for threshold reference
    max_abs_gex = 0.0
    max_oi = 0.0
    for k in strikes:
        bucket = exposures_by_strike.get(k, {})
        gex = _get_gex(bucket)
        oi = _get_oi(bucket)
        if gex > max_abs_gex:
            max_abs_gex = gex
        if oi > max_oi:
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
        is_void = (gex < gex_threshold) and (oi < oi_threshold if max_oi > 0 else True)
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
                    avg_gex += abs(float(bucket.get("net_gex_1pct", 0) or 0))
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
                avg_gex += abs(float(bucket.get("net_gex_1pct", 0) or 0))
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



