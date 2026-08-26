"""
math_levels.py
Chartable key-level engine — walls, pins, inflections, support/resistance
derived from options exposure structure.

Phase 2 extraction from math_exposure.py per Extraction Blueprint v1.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, replace
from typing import Dict, List

from math_exposure_core import (
    ExposureRow,
    KEY_LEVEL_STRIKE_WINDOW,
    _f,
    bucket_metric,
    bucket_metric_abs,
    _window_strikes,
    aggregate_net_dex,
    aggregate_net_gex,
    exposures_have_dollar_gex,
    key_level_strikes_with_gamma,
    key_level_strikes_with_oi,
    net_gex_dollars_at_strike,
    pick_delta_wall_strikes,
    pick_net_gex_peak_strike,
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


def _strike_total_oi(bucket: dict) -> float | None:
    """Total OI at strike — both call and put legs required (no silent 0 for missing openInterest)."""
    call_oi = bucket.get("call_oi")
    put_oi = bucket.get("put_oi")
    if call_oi is None or put_oi is None:
        return None
    try:
        tot = float(call_oi) + float(put_oi)
    except (TypeError, ValueError):
        return None
    return tot if tot > 0 else None


# ── Inflection / OI helpers ───────────────────────────────────────────────────

def _pick_oi_center(exposures: Dict[float, dict], strikes: List[float]) -> float | None:
    # strike with max total OI (call+put)
    best = None
    best_val = None
    for s in strikes:
        b = exposures.get(s, {})
        tot = _strike_total_oi(b)
        if tot is None:
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

def _pin_strength(exposures: Dict[float, dict], net_gex_peak: float | None, strikes: List[float]) -> str:
    """High/Med/Low concentration of |net GEX$| at the analytics net-GEX peak vs the median strike.

    Not the terrain total-gamma pin's lead % (`gamma_pin_strength_pct`).
    """
    if net_gex_peak is None:
        return "Very Low"
    b = exposures.get(net_gex_peak, {}) or exposures.get(float(net_gex_peak), {})
    if exposures_have_dollar_gex(exposures):
        gp = abs(net_gex_dollars_at_strike(b))
        vals = [abs(net_gex_dollars_at_strike(exposures.get(s, {}))) for s in strikes]
    else:
        gp_raw = bucket_metric(b, "net_gamma")
        if gp_raw is None:
            return "Very Low"
        gp = abs(gp_raw)
        vals = [
            abs(v)
            for s in strikes
            if (v := bucket_metric(exposures.get(s, {}), "net_gamma")) is not None
        ]
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
    cons_net_gex_peak = pick_net_gex_peak_strike(exposures, cons_gamma_strikes)
    cons_delta_inf = _pick_inflection_closest_zero(exposures, cons_gamma_strikes, "net_delta")
    cons_gamma_inf = _pick_inflection_closest_zero(exposures, cons_gamma_strikes, "net_gamma")
    cons_oi_center = _pick_oi_center(exposures, cons_strikes)
    cons_pin_strength = _pin_strength(exposures, cons_net_gex_peak, cons_gamma_strikes)
    cons_bias = _bias_from_net(cons_net_gamma, cons_net_delta, cons_pin_strength)
    rows.append(
        ExposureRow(
            "CONSENSUS",
            None,
            cons_net_gamma,
            cons_net_delta,
            cons_net_gex_peak,
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
        net_gex_peak = pick_net_gex_peak_strike(exposures, ws)
        delta_inf = _pick_inflection_closest_zero(exposures, ws, "net_delta")
        gamma_inf = _pick_inflection_closest_zero(exposures, ws, "net_gamma")
        oi_center = _pick_oi_center(exposures, ws)
        pin_strength = _pin_strength(exposures, net_gex_peak, ws)
        bias = _bias_from_net(net_gamma, net_delta, pin_strength)
        rows.append(
            ExposureRow(
                f"±{w}",
                w,
                net_gamma,
                net_delta,
                net_gex_peak,
                delta_inf,
                gamma_inf,
                oi_center,
                pin_strength,
                bias,
            )
        )

    return rows


# ── Wall selection / dominance helpers ────────────────────────────────────────

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

def compute_pin_width_pts(call_gamma_wall: float | None,
                          put_gamma_wall: float | None) -> float | None:
    """RC-345 / F20: THE one authority for pin width (call_gamma_wall - put_gamma_wall, in
    price points, rounded to 4). market_state and server both computed this subtraction
    independently — one unrounded, one rounded — a duplicate producer of the same semantic.
    Returns None (governed absence) unless BOTH walls are present and truthy."""
    if not call_gamma_wall or not put_gamma_wall:
        return None
    return round(call_gamma_wall - put_gamma_wall, 4)


def consensus_walls_bind_terrain_ssot(
    walls: List[WallsRow],
    terrain: dict | None,
) -> List[WallsRow]:
    """RC-420 / RC-422: CONSENSUS wall strikes bind to terrain SSOT.

    Fresh terrain (truthy and not levels_stale) rewrites CONSENSUS call/put
    gamma and delta wall strikes from the wide-chain cache the overlay already
    paints. Stale or absent terrain withholds those four strikes rather than
    leaving selected-expiry analytics in place. Strengths are withheld so
    selected-expiry GEX$ cannot sit beside a wide-chain strike. OI/vanna
    wall slots are always withheld: terrain does not compute them, and a
    selected-expiry max-OI / abs-vanna strike must not occupy the same
    CONSENSUS wall fields the overlay already blanks.
    """
    if not walls:
        return walls
    idx = 0
    for i, row in enumerate(walls):
        if row.label == "CONSENSUS":
            idx = i
            break
    row = walls[idx]
    t = terrain or {}
    fresh = bool(t) and not t.get("levels_stale")
    if fresh:
        cg = _f(t.get("call_wall"))
        pg = _f(t.get("put_wall"))
        cd = _f(t.get("call_delta_wall"))
        pd = _f(t.get("put_delta_wall"))
    else:
        cg = pg = cd = pd = None
    cg_v = pg_v = cd_v = pd_v = None
    domg_side, domg_s, domg_v = _dominant(cg, cg_v, pg, pg_v)
    domd_side, domd_s, domd_v = _dominant(cd, cd_v, pd, pd_v)
    bound = replace(
        row,
        call_gamma_wall=cg,
        call_gamma_strength=cg_v,
        put_gamma_wall=pg,
        put_gamma_strength=pg_v,
        dom_gamma_side=domg_side,
        dom_gamma_wall=domg_s,
        dom_gamma_strength=domg_v,
        call_delta_wall=cd,
        call_delta_strength=cd_v,
        put_delta_wall=pd,
        put_delta_strength=pd_v,
        dom_delta_side=domd_side,
        dom_delta_wall=domd_s,
        dom_delta_strength=domd_v,
        call_oi_wall=None,
        call_oi_strength=None,
        put_oi_wall=None,
        put_oi_strength=None,
        dom_oi_side="",
        dom_oi_wall=None,
        dom_oi_strength=None,
        call_vanna_wall=None,
        call_vanna_strength=None,
        put_vanna_wall=None,
        put_vanna_strength=None,
    )
    out = list(walls)
    out[idx] = bound
    return out


def build_walls_rows(
    exposures: Dict[float, dict],
    spot: float,
) -> List[WallsRow]:
    """Canonical walls table: CONSENSUS only.

    RC-421: plus-minus-N rows reused call_gamma_wall / call_delta_wall on the
    same walls[] list as CONSENSUS. After RC-420 CONSENSUS is terrain SSOT
    (wide chain) while those rows stayed selected-expiry strike-index windows
    — same field, two books. Key-level policy is already CONSENSUS not ATM±N
    (KEY_LEVEL_STRIKE_WINDOW). Scoped strike-window analytics remain on
    summary_rows / totals_rows (aggregates, not canonical wall strikes).
    `spot` sizes KEY_LEVEL_STRIKE_WINDOW when that policy is non-None.
    RC-422: CONSENSUS OI/vanna wall slots stay None. Terrain does not
    compute them; selected-expiry max OI / abs vanna must not occupy the
    same wall fields SignalInput, nearest-level, snapshot, A2, and OE
    already treat as structural walls.
    """
    strikes_all = sorted(list(exposures.keys()))
    if not strikes_all:
        return [
            WallsRow("CONSENSUS", None, None, None, None, None, "", None, None,
                     None, None, None, None, "", None, None,
                     None, None, None, None, "", None, None)
        ]

    if KEY_LEVEL_STRIKE_WINDOW is None:
        g_strikes = key_level_strikes_with_gamma(exposures) or strikes_all
    else:
        g_strikes = _window_strikes(strikes_all, spot, KEY_LEVEL_STRIKE_WINDOW)
    (cg_s, cg_v), (pg_s, pg_v) = pick_gamma_wall_strikes(exposures, g_strikes)
    (cd_s, cd_v), (pd_s, pd_v) = pick_delta_wall_strikes(exposures, g_strikes)
    domg_side, domg_s, domg_v = _dominant(cg_s, cg_v, pg_s, pg_v)
    domd_side, domd_s, domd_v = _dominant(cd_s, cd_v, pd_s, pd_v)

    return [WallsRow(
        label="CONSENSUS",
        window=None,

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

        call_oi_wall=None,
        call_oi_strength=None,
        put_oi_wall=None,
        put_oi_strength=None,
        dom_oi_side="",
        dom_oi_wall=None,
        dom_oi_strength=None,

        call_vanna_wall=None,
        call_vanna_strength=None,
        put_vanna_wall=None,
        put_vanna_strength=None,
    )]


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

        cg = pg = cd = pd = coi = poi = None
        any_cg = any_pg = any_cd = any_pd = any_coi = any_poi = False
        _cg_sum = _pg_sum = _cd_sum = _pd_sum = _coi_sum = _poi_sum = 0.0

        for s in sset:
            b = exposures.get(s, {})
            _cg = bucket_metric(b, "call_gamma")
            _pg = bucket_metric(b, "put_gamma")
            _cd = bucket_metric(b, "call_delta")
            _pd = bucket_metric(b, "put_delta")
            if _cg is not None:
                _cg_sum += float(_cg)
                any_cg = True
            if _pg is not None:
                _pg_sum += float(_pg)
                any_pg = True
            if _cd is not None:
                _cd_sum += float(_cd)
                any_cd = True
            if _pd is not None:
                _pd_sum += float(_pd)
                any_pd = True
            _tot_oi = _strike_total_oi(b)
            if _tot_oi is not None:
                call_oi = b.get("call_oi")
                put_oi = b.get("put_oi")
                if call_oi is not None:
                    _coi_sum += float(call_oi)
                    any_coi = True
                if put_oi is not None:
                    _poi_sum += float(put_oi)
                    any_poi = True

        if any_cg:
            cg = _cg_sum
        if any_pg:
            pg = _pg_sum
        if any_cd:
            cd = _cd_sum
        if any_pd:
            pd = _pd_sum
        if any_coi:
            coi = _coi_sum
        if any_poi:
            poi = _poi_sum

        ng = (cg - pg) if cg is not None and pg is not None else None
        nd = (cd - pd) if cd is not None and pd is not None else None
        noi = (coi - poi) if coi is not None and poi is not None else None

        pcr = (poi / coi) if coi is not None and coi > 0 and poi is not None else None

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
) -> float | None:
    """Put-call parity residual (synthetic forward minus spot), or None when it cannot be
    computed from this chain.

    RC-301: every absence path here returned 0.0, and 0.0 is not "unknown" — it is the
    specific market claim that the forward equals spot and there is NO basis. Both callers
    happen to gate on `abs(resid) > threshold`, so the fabricated zero fell below the bar
    and rendered nothing; the behaviour was right for the wrong reason and would invert the
    moment a caller compared it any other way. None makes the intent explicit.
    """
    try:
        spot_f = float(spot)
    except Exception:
        return None
    from numeric_contract import float_finite_or_none as _fin
    use = []
    for c in contracts or []:
        # single source: finite DTE (canonical reader rejects NaN/±inf that int(float()) raised on)
        dte_f = _fin(c.get("daysToExpiration"))
        dte = int(dte_f) if dte_f is not None else None
        if dte_max is not None and dte != int(dte_max):
            continue
        use.append(c)
    if not use:
        return None                      # RC-301: no usable contracts is not a zero basis
    strikes = []
    for c in use:
        # single source: reject NaN/inf/junk strikes (raw float() silently admitted NaN)
        sp = _fin(c.get("strikePrice"))
        if sp is None:
            continue
        strikes.append(sp)
    if not strikes:
        return None                      # RC-301: no strikes is not a zero basis
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
        def _chain_match(c: dict, right: str) -> bool:
            pc = c.get("putCall")
            sp = _fin(c.get("strikePrice"))  # single source: finite strike (removes the last raw float() in this function)
            if pc is None or sp is None:
                return False
            return str(pc).upper() == right and sp == k

        calls = [c for c in use if _chain_match(c, "CALL")]
        puts = [c for c in use if _chain_match(c, "PUT")]
        if not calls or not puts: continue
        call_mid = _mid(calls[0])
        put_mid = _mid(puts[0])
        if call_mid is None or put_mid is None: continue
        resid = (call_mid - put_mid) - (spot_f - float(k))
        resids.append(float(resid))
    if not resids: return None           # RC-301: no priceable pair is not a zero basis
    resids = sorted(resids)
    if len(resids) >= 5: resids = resids[1:-1]
    return float(sum(resids) / len(resids))


# ── Gamma Exposure Profile — total dealer gamma recomputed at hypothetical spot ──
# CANONICAL method (FIND-GAMMA-FLIP-METHOD-V1). Proven 2026-07-19 against a real SPY
# reference chain: the cumulative-sum approach does NOT reproduce the profile
# (corr 0.086, never crosses zero, 2.19e9 divergence). Only recomputing every contract's
# gamma at each candidate price reproduces the published flip (SPY 745.61, SKHY 124.44).

_SQRT_2PI = math.sqrt(2.0 * math.pi)


def _norm_pdf(x: float) -> float:
    return math.exp(-0.5 * x * x) / _SQRT_2PI


def bs_gamma(spot: float, strike: float, t_years: float, sigma: float,
             rate: float = 0.0, div: float = 0.0) -> float | None:
    """Black-Scholes gamma per share (identical for calls and puts).

    RATE/DIVIDEND ASSUMPTION — MEASURED 2026-08-26, previously assumed. Every production caller
    (compute_gamma_profile) invokes this with FOUR args, so the shipped repricing runs at r=0, q=0;
    r and q enter only through d1's (r - q)*T term. That omission was never quantified in-repo,
    so it was an unproven assumption behind every flip/GSF/regime number.
    MEASUREMENT (n=40 stored wide morning captures, repriced at each snapshot's own instant,
    r=4.5% / q=1.5% vs the shipped r=q=0):
      * flip LEVEL displacement: median 0.081% of spot, p90 0.147%, max 0.201% (n=33 with a flip)
      * at-spot gamma SIGN changes: 0 of 40 — the sign this function feeds never inverted
    READING (about THIS FUNCTION'S OUTPUT, not about what price does): the sign of the repriced
    aggregate is insensitive to r/q at realistic values, so r=q=0 is acceptable wherever only the
    sign is consumed. The LEVEL error it contributes (~0.08-0.20% of spot) is an order of magnitude
    below the dominant chain-span error (1.38% at ±5%, see GAMMA_FLIP_MIN_SPAN_PCT), but it is the
    SAME order as the ±10% convergence residual (0.117%) — so at the TRUSTED tier r/q is a
    comparable error source, not a negligible one.
    STILL NOT_PROVEN: this used one representative (r, q) pair on 40 captures, not a sweep, and no
    per-instrument dividend. A LEAPS-heavy book at a higher r would displace more; long-dated
    contributions are where (r-q)*T grows. Settle with a sweep over r∈[0,0.05], q∈[0,0.03] and a
    per-ticker dividend before treating any level finer than ~0.2% of spot as r/q-clean.
    """
    if spot <= 0 or strike <= 0 or t_years <= 0 or sigma <= 0:
        return None
    try:
        vt = sigma * math.sqrt(t_years)
        d1 = (math.log(spot / strike) + (rate - div + 0.5 * sigma * sigma) * t_years) / vt
        g = _norm_pdf(d1) / (spot * vt)
    except (ValueError, ZeroDivisionError, OverflowError):
        return None
    return g if math.isfinite(g) else None


def bs_vanna(spot: float, strike: float, t_years: float, sigma: float,
             rate: float = 0.0, div: float = 0.0) -> float | None:
    """Black-Scholes vanna (dDelta/dSigma) per share — identical for calls and puts.

    Closed form: -e^(-qT) * phi(d1) * d2 / sigma. Sign is driven entirely by -d2, so it
    flips through SPOT (strikes above spot positive, below negative) — never through the
    call/put boundary. INDEPENDENTLY VERIFIED 2026-08-02 (scratchpad/_vanna_independent_verify.py):
    central finite difference of the BS delta across 27 (K,T,sigma) points agrees to
    max |err| 9.1e-9, as do both identities vanna = (vega/S)(1 - d1/(sigma*sqrt(T)))
    and vanna = -Gamma * S * sqrt(T) * d2 (the gamma identity is wired into
    tests/test_charm_sign_finite_difference.py as a standing cross-check).
    Units: delta-change per 1.00 of IV (100 vol points); multiply by 0.01 for per-vol-point
    — the sigma-scaling convention is LOCKED here beside the dealer convention (RC-179).
    """
    if spot <= 0 or strike <= 0 or t_years <= 0 or sigma <= 0:
        return None
    try:
        vt = sigma * math.sqrt(t_years)
        d1 = (math.log(spot / strike) + (rate - div + 0.5 * sigma * sigma) * t_years) / vt
        d2 = d1 - vt
        v = -math.exp(-div * t_years) * _norm_pdf(d1) * d2 / sigma
    except (ValueError, ZeroDivisionError, OverflowError):
        return None
    return v if math.isfinite(v) else None


def bs_charm(spot: float, strike: float, t_years: float, sigma: float,
             rate: float = 0.0) -> float | None:
    """Black-Scholes charm (dDelta/dt, calendar time) per share, q=0.

    Textbook (Haug) charm is dDelta/dT = -phi(d1) * [ r/(sigma*sqrt(T)) - d2/(2T) ].
    Calendar-time charm is the negative of that. Callers that want the deliberate
    0DTE-stable r-omission (compute_net_charm) pass rate=0.0; the r term is otherwise
    retained and guarded by the t_years floor applied upstream.

    Identical for calls and puts at q=0: Delta_put = Delta_call - 1, and the constant
    vanishes under differentiation with respect to time.
    """
    if spot <= 0 or strike <= 0 or t_years <= 0 or sigma <= 0:
        return None
    try:
        vt = sigma * math.sqrt(t_years)
        d1 = (math.log(spot / strike) + (rate + 0.5 * sigma * sigma) * t_years) / vt
        d2 = d1 - vt
        # dDelta/dt (calendar time). Sign verified against a finite-difference
        # derivative of the BS delta -- an earlier draft returned the negation and was
        # caught by that check (exact magnitude, inverted sign) before shipping.
        c = -_norm_pdf(d1) * (rate / vt - d2 / (2.0 * t_years))
    except (ValueError, ZeroDivisionError, OverflowError):
        return None
    return c if math.isfinite(c) else None


def compute_charm_by_strike(contracts: List[dict], spot: float, now=None) -> Dict[float, dict]:
    """Per-strike dealer CHARM exposure, in delta-shares per day.

    Charm exposure is standard institutional practice (SpotGamma, Unusual Whales and
    VannaCharm all publish charm-by-strike alongside GEX), and charm pressure is the
    mechanism attributed to the end-of-day pin: dealers bleeding delta into the close.

    Convention matches net GEX exactly (+call / -put), so a positive net value means the
    dealer book's delta decay creates BUYING pressure at that strike.

    Units: charm/year * OI * multiplier / 365 -> delta-shares per day.
    """
    out: Dict[float, dict] = {}
    if not contracts or not spot or spot <= 0:
        return out
    for ct in contracts:
        parsed = _contract_inputs(ct, now=now)
        if parsed is None:
            continue
        strike, oi, mult, t_years, sigma, sign = parsed
        c = bs_charm(float(spot), strike, t_years, sigma)
        if c is None:
            continue
        exposure = c * oi * mult / 365.0
        b = out.setdefault(strike, {"call_charm": 0.0, "put_charm": 0.0, "net_charm": 0.0})
        if sign > 0:
            b["call_charm"] += exposure
        else:
            b["put_charm"] += exposure
        b["net_charm"] = b["call_charm"] - b["put_charm"]
    return out


def pick_charm_wall_strikes(charm_by_strike: Dict[float, dict]
                            ) -> tuple[float | None, float | None]:
    """(call_charm_wall, put_charm_wall) — strikes of maximum call-side and put-side
    charm exposure. These are the strikes whose delta decay exerts the most mechanical
    pressure into the close."""
    if not charm_by_strike:
        return None, None
    call_k = max(charm_by_strike, key=lambda k: abs(charm_by_strike[k]["call_charm"]))
    put_k = max(charm_by_strike, key=lambda k: abs(charm_by_strike[k]["put_charm"]))
    cw = call_k if abs(charm_by_strike[call_k]["call_charm"]) > 0 else None
    pw = put_k if abs(charm_by_strike[put_k]["put_charm"]) > 0 else None
    return (round(cw, 2) if cw is not None else None,
            round(pw, 2) if pw is not None else None)


def _contract_inputs(ct: dict, now=None) -> tuple[float, float, float, float, float, int] | None:
    """(strike, oi, mult, t_years, sigma, sign) or None when unusable.

    `t_years` is the canonical INTRADAY time-to-expiry (time_et.time_to_expiry_years): to the
    option's session close (16:00 ET / 13:00 early-close), ACT/365, from `now` (defaults to
    now_et()). Replaces the old max(dte,0.5)/365 0.5-DAY floor, which over-stated T by up to
    24x near the close and flattened the real 1/sqrt(T) gamma/charm spike (RC-42; validated
    against Schwab-reported gamma). Offline/replay callers pass `now` = the snapshot time.
    """
    from math_exposure_core import _f, schwab_iv_to_sigma
    from time_et import time_to_expiry_years

    strike = _f(ct.get("strikePrice"))
    oi = _f(ct.get("openInterest"))
    mult = _f(ct.get("multiplier"))
    side = str(ct.get("putCall") or "").upper()
    if strike is None or strike <= 0 or oi is None or oi <= 0:
        return None
    if mult is None or mult <= 0 or side not in ("CALL", "PUT"):
        return None
    # schwab_iv_to_sigma already rejects None/non-positive, so no separate iv guard.
    sigma = schwab_iv_to_sigma(_f(ct.get("volatility")))  # single source: math_exposure_core
    if sigma is None or sigma <= 0:
        return None
    t_years = time_to_expiry_years(ct.get("expirationDate"), now=now)  # single source: intraday-to-close
    if t_years is None or t_years <= 0:
        return None  # expired / holiday / missing-or-unparseable expiry -> fail closed
    return strike, oi, mult, t_years, sigma, (1 if side == "CALL" else -1)


#: TU-04 sign models. NAIVE (+call/−put) is validated at INDEX level (Baltussen JFE 2021
#: reproduced the SqueezeMetrics convention on OptionMetrics data). EMPIRICAL_PRIOR
#: encodes Garleanu-Pedersen-Poteshman Table 1 for SINGLE NAMES: end users net-WRITE
#: both calls and puts on equities, so dealers are net LONG both sides (+call/+put).
#: A/B ONLY — production stays naive until the scorecard promotes (never a silent swap).
SIGN_MODEL_NAIVE = "naive"
SIGN_MODEL_EMPIRICAL_PRIOR = "empirical_prior"


def _dealer_sign(side_sign: int, sign_model: str) -> int:
    """side_sign is +1 CALL / −1 PUT from _contract_inputs (the naive convention)."""
    if sign_model == SIGN_MODEL_EMPIRICAL_PRIOR:
        return 1                     # dealers long BOTH legs on single names (GPO Table 1)
    if sign_model == SIGN_MODEL_NAIVE:
        return side_sign
    raise ValueError(f"unknown sign_model: {sign_model!r}")


def compute_gamma_profile(contracts: List[dict], spot: float, *, span_pct: float = 0.15,
                          steps: int = 240,
                          sign_model: str = SIGN_MODEL_NAIVE, now=None) -> List[tuple[float, float]]:
    """Total dealer gamma exposure (per 1% move, dollars) at each candidate price.

    Dealer convention per `sign_model` (default naive +call/−put — the only model in
    production; empirical_prior exists for the TU-04 A/B scorecard). Returns
    [(price, total_gex)] ascending. The zero crossing of this curve is the gamma flip.
    """
    if not contracts or spot is None or spot <= 0:
        return []
    parsed = [p for p in (_contract_inputs(c, now=now) for c in contracts if isinstance(c, dict)) if p]
    if not parsed:
        return []
    lo, hi = spot * (1.0 - span_pct), spot * (1.0 + span_pct)
    steps = max(int(steps), 2)
    out: List[tuple[float, float]] = []
    for i in range(steps + 1):
        s = lo + (hi - lo) * i / steps
        total = 0.0
        for strike, oi, mult, t_years, sigma, sign in parsed:
            g = bs_gamma(s, strike, t_years, sigma)
            if g is None:
                continue
            total += _dealer_sign(sign, sign_model) * g * oi * mult * s * s * 0.01
        out.append((round(s, 4), total))
    return out


def gamma_flip_from_profile(
    profile: List[tuple[float, float]], spot: float | None = None
) -> float | None:
    """Interpolated price where net dealer gamma changes SIGN — in either direction.

    Bugbot 2026-07-20 (HIGH, confirmed): the original condition `v0 < 0 <= v1` detected
    only negative->positive crossings as price rises. A chain that is long-gamma BELOW
    and short-gamma ABOVE (positive->negative) has a real regime boundary that this
    returned None for — the flip vanished and the verdict read "no crossing" on a chain
    that crosses. Both directions are boundaries; the direction only changes what lies on
    each side, which the caller derives from gamma_at_price at spot (RC-11).

    When `spot` is given and several crossings exist, the one NEAREST SPOT is returned:
    regime is the sign AT spot, so the closest sign change is the boundary that governs
    the move the operator is actually trading.
    """
    crossings: list[float] = []
    for i in range(1, len(profile)):
        (p0, v0), (p1, v1) = profile[i - 1], profile[i]
        if v1 == v0:
            continue
        # v0 == 0 is itself the boundary (Cursor audit 2026-07-20: a profile STARTING at
        # exactly zero returned None — both strict-sign conditions are false when v0==0,
        # so a zero-touching profile dropped its flip). The v1==0 side was already
        # handled: v0<0<=v1 / v0>0>=v1 interpolate to p1 when the segment ENDS at zero.
        if v0 == 0:
            crossings.append(round(p0, 2))
        elif (v0 < 0 <= v1) or (v0 > 0 >= v1):
            crossings.append(round(p0 + (p1 - p0) * (-v0) / (v1 - v0), 2))
    if not crossings:
        return None
    if spot is None:
        return crossings[0]
    return min(crossings, key=lambda c: abs(c - spot))


#: RC-354 Gamma Support Floor / Gamma Resistance Ceiling — construction constants.
#: phi: the support-decay fraction (research 2026-08-15, Barbon & Buraschi gamma-fragility
#: framing): the level where the dealer stabilization cushion N(s) has decayed to phi of its
#: at-spot value. 0.5 = "half-support", communicable and parameter-honest; calibratable in
#: [0.25, 0.6] on banked bars later (placebo-tested), never silently re-tuned.
GSF_PHI = 0.5
#: eps guard: below this fraction of the profile's max |N|, the at-spot cushion is too small
#: for a ratio to mean anything — the regime is effectively at/below zero support and the
#: honest output is a STATE, not a fabricated price.
GSF_EPS_FRAC = 0.005
GSF_STATE_OK = "OK"
GSF_STATE_BELOW_SUPPORT = "BELOW_SUPPORT"
GSF_STATE_UNAVAILABLE = "UNAVAILABLE"


def _interp_profile_at(profile: List[tuple[float, float]], s: float) -> float | None:
    """Linear interpolation of net GEX$ at price s on an ascending profile."""
    if not profile:
        return None
    if s <= profile[0][0]:
        return profile[0][1]
    if s >= profile[-1][0]:
        return profile[-1][1]
    for i in range(1, len(profile)):
        (p0, v0), (p1, v1) = profile[i - 1], profile[i]
        if p0 <= s <= p1:
            if p1 == p0:
                return v0
            return v0 + (v1 - v0) * (s - p0) / (p1 - p0)
    return None


def compute_gamma_support_levels(
    profile: List[tuple[float, float]],
    spot: float | None,
    *,
    phi: float = GSF_PHI,
    eps_frac: float = GSF_EPS_FRAC,
) -> dict:
    """RC-354: Gamma Support Floor (GSF) + Gamma Resistance Ceiling (GRC) — ONE producer.

    On the repriced net-GEX profile N(s) (`compute_gamma_profile`; the SAME materialized
    profile the flip/regime use — RC-345 one-profile rule):

      GSF = the HIGHEST s < spot where N(s) <= phi * N(spot)
            — where the dealers' positive-gamma stabilization cushion is substantially
            exhausted BELOW spot. Sits at/above the Gamma Flip by construction (N(flip)=0):
            support effectively ends here BEFORE net gamma mathematically crosses zero.
      GRC = the LOWEST s > spot where N(s) <= phi * N(spot)
            — where vol-SUPPRESSION is exhausted ABOVE spot; beyond it dealer selling no
            longer dampens rallies. ASYMMETRIES (research 2026-08-15, encoded honestly):
            (1) N(s) often RISES into the call wall before decaying, so the GRC frequently
            sits AT/BEYOND the wall — resistance strengthens before it exhausts; (2) an
            upside breach is typically a vanna-supported grind/extension, not a mirror-image
            crash-up — the two levels are NOT symmetric in breach violence.

    MECHANISM, AND WHAT BACKS IT (RC-319/RC-320: a causal claim about price must be
    checkable, or a reader cannot refute it). Three separate standards apply here, and
    they are NOT equally settled:
      * That a positive net dealer gamma book DAMPENS moves is a first principles
        derivation from the hedge rule, not an observation: a dealer long gamma gains
        delta as spot rises and must SELL to return to flat, and must BUY as spot falls,
        so the re-hedge always opposes the move. The word "stabilises" above means only
        this mechanical opposition.
      * That this hedging is large enough to MOVE the underlying is empirical, and the
        evidence is expiration-date price clustering in Ni, Pearson and Poteshman,
        Journal of Financial Economics, doi:10.1016/j.jfineco.2004.08.005.
      * The dealer SIGN is MODELLED, never observed — public open interest does not say
        who owns the contracts (https://spotgamma.com/what-is-gex-gamma-exposure/) — so
        both levels are conditional on the naive +calls/−puts convention being right for
        the session. When it is wrong, GSF and GRC are wrong with it.
    The two ASYMMETRIES above are desk OBSERVATIONS recorded 2026-08-15, not derivations
    and not citations; they are stated as what was seen, and nothing here should be read
    as claiming they were established the way the two points above were.

    WHAT IS STILL UNPROVEN, AND IT IS THE PART A TRADER CARES ABOUT (RC-320). Everything
    above concerns the damping MECHANISM. It does NOT establish that GSF and GRC act as
    support and resistance — that price arriving at these prices tends to hold. That is a
    separate empirical claim, this repository has not tested it, and nothing here should be
    read as asserting it. The two levels are MEASURED GEOMETRY: the prices at which the
    net-gamma profile has decayed to `phi` of its at-spot value on each side. The console
    tooltips say exactly this and mark the holding behaviour UNPROVEN; if that wording and
    this docstring ever disagree, this one is the paraphrase and the honest reading is the
    weaker of the two.

    FAIL-CLOSED: when N(spot) <= eps (already negative/negligible-gamma regime) the honest
    output is state=BELOW_SUPPORT with BOTH levels None — never a fabricated price. An empty
    or unusable profile returns state=UNAVAILABLE.
    """
    if not profile or spot is None or spot <= 0:
        return {"gsf": None, "grc": None, "state": GSF_STATE_UNAVAILABLE, "n_at_spot": None}
    n_spot = _interp_profile_at(profile, float(spot))
    if n_spot is None:
        return {"gsf": None, "grc": None, "state": GSF_STATE_UNAVAILABLE, "n_at_spot": None}
    max_abs = max(abs(v) for _, v in profile)
    eps = eps_frac * max_abs if max_abs > 0 else 0.0
    if n_spot <= eps:
        return {"gsf": None, "grc": None, "state": GSF_STATE_BELOW_SUPPORT,
                "n_at_spot": round(n_spot, 2)}
    target = phi * n_spot

    def _cross(p0: float, v0: float, p1: float, v1: float) -> float:
        # price where the segment crosses `target` (v0 and v1 straddle it)
        if v1 == v0:
            return p0
        return p0 + (p1 - p0) * (target - v0) / (v1 - v0)

    gsf: float | None = None
    grc: float | None = None
    # walk DOWN from spot: the FIRST crossing below spot is the highest such s
    below = [(p, v) for p, v in profile if p < spot]
    prev_p, prev_v = float(spot), float(n_spot)
    for p, v in reversed(below):
        if v <= target < prev_v or v <= target and prev_v > target:
            gsf = round(_cross(p, v, prev_p, prev_v), 2)
            break
        prev_p, prev_v = p, v
    # walk UP from spot: the FIRST crossing above spot is the lowest such s
    above = [(p, v) for p, v in profile if p > spot]
    prev_p, prev_v = float(spot), float(n_spot)
    for p, v in above:
        if v <= target < prev_v or v <= target and prev_v > target:
            grc = round(_cross(prev_p, prev_v, p, v), 2)
            break
        prev_p, prev_v = p, v
    return {"gsf": gsf, "grc": grc, "state": GSF_STATE_OK, "n_at_spot": round(n_spot, 2)}


def snap_level_to_shelf_strike(
    level: float | None,
    strike_gex: dict[float, float] | None,
    *,
    side: str,
    spot: float | None,
    theta: float,
    snap_pct: float = 0.0025,
) -> float | None:
    """RC-354 snap-to-shelf: if a SIGNIFICANT positive-GEX strike (G_K >= theta) lies within
    snap_pct of the profile-derived level on the relevant side of spot, snap the display to
    that strike — a real OI shelf is tradeable, an abstract profile point is not. theta comes
    from the caller (85th percentile of trailing positive strike GEX$ — self-calibrating,
    nobody's proprietary output). Returns the (possibly snapped) level; None passes through.
    """
    if level is None or not strike_gex or spot is None or spot <= 0:
        return level
    tol = spot * snap_pct
    candidates = [
        k for k, g in strike_gex.items()
        if g is not None and g >= theta and abs(k - level) <= tol
        and ((side == "below" and k < spot) or (side == "above" and k > spot))
    ]
    if not candidates:
        return level
    return round(min(candidates, key=lambda k: abs(k - level)), 2)


#: WHAT THIS VERDICT ACTUALLY ASSERTS (corrected 2026-08-26 — the word overstated the evidence):
#: it is a CHAIN-COVERAGE verdict, not a certification that the flip level is correct. It says one
#: measurable thing: the delivered strikes reach GAMMA_FLIP_TRUSTED_SPAN_PCT around spot, the span
#: at which the convergence study's error stopped improving (~0.117% of spot residual vs its own
#: reference). It does NOT assert the level is right in absolute terms — the study's justified_span
#: is None, and for SPY/QQQ its reference chain is narrower than production (see the block below).
#: A SECOND, SEPARATE LIMIT — and it is NOT part of the same error budget. Corrected 2026-08-26
#: after review: an earlier version of this note said intraday drift is "~35x" the convergence
#: residual and called the residual "not the dominant error". That was a CATEGORY ERROR. The two
#: numbers answer different questions and are not commensurable, not summable, and not rankable:
#:   * ~0.117% of spot — CONVERGENCE RESIDUAL: an ACCURACY error at ONE instant, the gap between
#:     the flip computed on a truncated strike window and the flip on the full window. It is a
#:     defect of our estimate; with every strike present it would go to zero.
#:   * ~4.176% of spot median, p90 ~11.991% (unproven_register row 56, 23,718 rows / 99 RTH
#:     ticker-sessions; SPY 0.221%, QQQ 6.139%, IWM 8.663%) — INTRADAY DRIFT: the range of the flip
#:     ACROSS a session. This is NOT an error at all. The level genuinely MOVES, because gamma
#:     depends on spot, IV and time; a correctly computed flip still moves this much. It would NOT
#:     go to zero with perfect data.
#: So drift neither inflates nor excuses the residual. What each one licenses:
#:   coverage/residual -> "is the number we are showing RIGHT, given the strikes we fetched?"
#:   drift             -> "will this level still be where it is later?" (a STALENESS question)
#: This verdict speaks ONLY to the first. It is silent on the second, which is why proximity logic
#: must read the LIVE recomputed flip rather than a session-open snapshot.
#: Consumers may gate on it; no surface may render it as proof. The operator-facing strings
#: deliberately say "chain coverage" and carry the residual, never a bare "trusted".
GAMMA_FLIP_TRUSTED = "TRUSTED"
GAMMA_FLIP_NARROW = "LOW_CONFIDENCE_NARROW_CHAIN"
GAMMA_FLIP_UNAVAILABLE = "UNAVAILABLE"
#: Middle tier (gamma audit 2026-08-26): the chain reaches GAMMA_FLIP_MIN_SPAN_PCT but not the
#: measured flip-LEVEL convergence span, so the LEVEL carries the ~1.4%-of-spot placement error the
#: convergence study measured. Named so no surface can print this as TRUSTED.
#: CORRECTED 2026-08-26 (second pass): this comment used to add "the regime (sign of gamma AT SPOT)
#: is sound". THAT WAS NEVER MEASURED and is not implied by the convergence study, which measures a
#: LEVEL distance, not a sign. Measured now — see GAMMA_FLIP_MIN_SPAN_PCT — reaching this tier does
#: NOT certify the sign: wider chains do read the sign better, but the improvement is gradual and
#: nothing special happens at the floor, so clearing it buys no guarantee. The tier means "level not
#: placed", nothing more.
GAMMA_FLIP_LEVEL_APPROX = "LEVEL_APPROX_NARROW_SPAN"
#: The live chain-FETCH width, and the FLOOR below which nothing is claimed at all (the verdict is
#: LOW_CONFIDENCE_NARROW_CHAIN and terrain stands everything aside).
#: THE SIGN-FLOOR CLAIM IS WITHDRAWN — corrected 2026-08-26 (second pass). This comment used to say
#: a chain below this "cannot even support the at-spot SIGN". That was ASSERTED, never measured, and
#: the flip-LEVEL convergence study does NOT establish it: that study measures |windowed flip -
#: full-chain flip|, a LEVEL distance, and is silent about the SIGN of gamma at spot.
#: MEASURED 2026-08-26 (the study that was missing; 260 seed-fixed chains from the same
#: option_chain_morning_full cohort, at-spot gamma recomputed on truncated windows via
#: _contract_inputs/_dealer_sign/bs_gamma, counting ONLY genuinely truncated chains):
#:   sign agreement with the full delivered chain — +/-1% 79.8% (n=233), +/-5% 86.2% (n=253,
#:   95% CI [0.814, 0.899]), +/-10% 90.2% (n=254), +/-15% 92.7% (n=248).
#: WHAT THIS PROVES, stated no wider than the data (tightened 2026-08-26 after review):
#:  (a) SPAN DOES MATTER. Agreement rises monotonically across the ladder and the ends do not
#:      overlap (79.8% [0.742,0.845] at +/-1% vs 92.7% [0.888,0.954] at +/-15%), so a wider chain
#:      genuinely reads the sign better. An earlier version of this note said span "barely" governs
#:      the sign — that was an overstatement in the other direction and is withdrawn.
#:  (b) WHAT IS DISPROVED IS A SPECIAL THRESHOLD AT 0.05, not the value of span. The curve is
#:      smooth and 0.05 is unremarkable on it — no cliff, no knee — so the floor marks neither where
#:      the sign becomes knowable nor a point at which it is certified. At exactly the floor the
#:      sign still disagrees with the full chain about ONE TIME IN SEVEN.
#: SEPARATELY, and measured ONLY AT THE +/-5% FLOOR: how decisively signed the book is separates the
#: outcome far more sharply than any two adjacent rungs do. Conditioning those rows on
#: net/gross = |net gamma at spot| / sum|per-contract contributions|:
#:   net/gross >= 10% -> 95.5% agreement (n=199, CI [0.916, 0.976])
#:   net/gross <  10% -> ~50% agreement (n=54) — indistinguishable from chance AT THIS WIDTH.
#: NOT MEASURED: whether a nearly-balanced book stays near chance at OTHER widths. The concentration
#: cut was run at the floor only; there is no concentration-x-span cross-tab, so no claim is made
#: here that width cannot help such a book. That cross-tab is the next measurement (register row).
#: The floor is therefore retained as a conservative fetch / declare-nothing bound, NOT as evidence
#: about the sign. Acting on the concentration finding (gating or disclosing a weakly-signed regime)
#: is an OPERATOR decision, flagged in unproven_register — it changes when advice is withheld, and
#: rests on one sample against a reference that is itself narrow for SPY/QQQ.
#: THIS CONSTANT NO LONGER AWARDS "TRUSTED" — corrected 2026-08-26; that is
#: GAMMA_FLIP_TRUSTED_SPAN_PCT below. Reaching this floor earns at most GAMMA_FLIP_LEVEL_APPROX
#: (regime stands on the at-spot sign, flip LEVEL disclosed as approximate).
#: PROVENANCE (RC-62, operator challenge "what is scientific about this number?"): the 0.05 was
#: ASSERTED, never derived — its original comment merely restated it, and AT THAT TIME (now fixed)
#: it governed both every live chain-fetch width and every TRUSTED-vs-LOW_CONFIDENCE verdict.
#: MEASURED 2026-07-26 by `python tools/study_flip_span_convergence_v1.py` (convergence against the
#: flip on each stored wide chain's FULL delivered strike set, trading days only, fixed cohort of
#: 15 chains that yield a flip at every ladder point): the flip has NOT converged at this value —
#: median error vs the full-chain flip is 1.38% of spot at +/-5%, falling ~10x to 0.117% at +/-10%
#: and 0.257% at +/-15%; no ladder point reaches 95% of chains inside a 0.05%-of-spot tolerance.
#: So 0.05 is measurably INSUFFICIENT, not merely unjustified.
#: HELD AT 0.05 PENDING, deliberately not silently re-tuned: the cohort is only n=15 and the
#: reference is our WIDEST AVAILABLE chain (Schwab caps strikeCount), so the study bounds the
#: requirement from below rather than pinning it. Raising it also widens every fetch, which is a
#: cost/latency decision. Re-set it once `python tools/probe_chain_depth_v1.py` establishes the
#: real vendor ceiling and the cohort is large enough to pin a value.
GAMMA_FLIP_MIN_SPAN_PCT = 0.05
#: GAMMA AUDIT 2026-08-26 — the operator's concern: "±5% can still be labeled TRUSTED even though
#: our own convergence work says ±5% is insufficient." That is CORRECT and is now fixed here.
#: The 0.05 above was doing DOUBLE DUTY: (a) the live chain-fetch width, a real cost/latency
#: decision, and (b) the TRUSTED-vs-NARROW verdict on the flip LEVEL. Only (b) is refuted by the
#: study; conflating them let a fetch-width compromise silently set the trust bar.
#: This constant governs the flip-LEVEL trust ONLY, and is set at the measured convergence knee:
#: median error vs the full-chain flip falls from 1.38% of spot at ±5% to 0.117% at ±10% (~10x) and
#: does not improve at ±15% (0.257%, reference noise).
#: CORRECTED 2026-08-26 (this constant's first note cited the WRONG POPULATION — read this before
#: quoting any span number). The superseded note said "SPY (median 8.49%) and QQQ (8.84%) sit BELOW
#: this bar", implying production SPY/QQQ would lose their flip-level trust. Those were
#: option_chain_morning_full ARCHIVE captures, which are NOT the production terrain chain.
#: RE-MEASURED against the LIVE fetch (`/api/terrain` flip_diag span_below/above_pct, 2026-08-26):
#:   SPY 29.4% (216 strikes), QQQ 29.5% (216), IWM 29.8% (87), NVDA 21.7% (44), AAPL 29.4%, TSLA 25.9%
#: — every sampled production chain clears this bar with ~3x headroom and reads TRUSTED. The
#: dark-the-board risk the graduated tier was partly justified by DID NOT EXIST at these spans.
#: The tier is still correct and retained, because it is the honest verdict for a chain that
#: genuinely lands between GAMMA_FLIP_MIN_SPAN_PCT and this bar (the regime is the SIGN OF GAMMA AT
#: SPOT, which needs strikes NEAR spot; only the flip LEVEL needs the wide wing) — it simply is not
#: SPY/QQQ's situation. WHEN MEASURING DELIVERED SPAN, READ THE LIVE TERRAIN FETCH, NOT THE ARCHIVE.
#: STILL NOT_PROVEN, and now on TWO counts — see GAMMA_FLIP_TRUSTED semantics below:
#:  (1) the study's justified_span is None (no ladder point reaches 95% of chains inside the
#:      0.05%-of-spot tolerance) on an n=15 fixed cohort; and
#:  (2) MEASURED 2026-08-26: for SPY/QQQ the study's own REFERENCE chain (archive: SPY 8.9%/110
#:      strikes, QQQ 9.6%/123) is ~3x NARROWER than the production chain it is used to certify, so
#:      the ±10% and ±15% ladder points cannot even truncate those rows (they pass through at
#:      zero error by construction — 5.1% of the n=992 cohort at ±10%). The knee is therefore
#:      measured predominantly on non-SPY/QQQ chains, and the 9%->30% region is UNMEASURED for
#:      exactly the two tickers that matter most.
#: So 0.10 is an evidence-backed FLOOR, never a certified sufficiency. Settle it by widening the
#: archive capture for dense-strike ETFs (see calibration/option_chain_morning_full) so the research
#: reference is at least as wide as production, then re-running the ladder.
GAMMA_FLIP_TRUSTED_SPAN_PCT = 0.10

#: Overshoot on the derived count. Schwab centres `strikeCount` strikes near ATM but not
#: exactly on it, so a count that exactly equals the span requirement can land asymmetric
#: and miss the bar on one side. 1.2 buys that tolerance without a second round trip.
STRIKE_COUNT_MARGIN = 1.2


def infer_strike_increment(contracts: List[dict]) -> float | None:
    """The strike spacing this instrument actually uses, from its own chain.

    MEDIAN of adjacent differences, not mean: real chains carry occasional wide gaps
    (illiquid far strikes, split-adjusted odd strikes) that drag a mean upward and would
    understate the count needed. Returns None when the chain is too thin to tell.
    """
    if not contracts:
        return None
    from numeric_contract import float_finite_or_none as _fin
    strikes_set: set[float] = set()
    for c in contracts:
        if not isinstance(c, dict):
            continue
        # single source: reject NaN/inf as well as junk. Raw float() only caught the
        # non-numeric case (strikePrice='x', audit 2026-07-20); float('nan') slipped
        # through and corrupted the sorted set the spacing inference pairs over.
        sp = _fin(c.get("strikePrice"))
        if sp is None:
            continue
        strikes_set.add(sp)
    strikes = sorted(strikes_set)
    if len(strikes) < 3:
        return None
    # strict=False is the intent: strikes[1:] is deliberately one shorter, so the pairing
    # of each strike with its successor must stop at the last pair rather than raise.
    diffs = sorted(
        round(b - a, 4) for a, b in zip(strikes, strikes[1:], strict=False) if b > a
    )
    if not diffs:
        return None
    mid = len(diffs) // 2
    incr = diffs[mid] if len(diffs) % 2 else (diffs[mid - 1] + diffs[mid]) / 2.0
    return float(incr) if incr > 0 else None


def required_strike_count(spot: float | None, increment: float | None, *,
                          span_pct: float = GAMMA_FLIP_MIN_SPAN_PCT,
                          margin: float = STRIKE_COUNT_MARGIN) -> int | None:
    """How many strikes it takes to span +/-`span_pct` around spot at this spacing.

    ROOT FIX for RC-12. That entry found the cause -- "a fixed strike count cannot satisfy
    a percentage-based span requirement across instruments with different strike spacing"
    -- and then answered it with a hardcoded table for three tickers, which is the same
    defect one layer down: every other ticker still got a fixed 40.

    MEASURED across 52 stored chains 2026-07-20
    (`SELECT spot, option_chain_json FROM snapshots ... ORDER BY ts_utc DESC LIMIT 1`):
    the fixed table is wrong in BOTH directions. $SPX at 7457.69 with $5 strikes needs 150
    and was given 40; IWM at 294.32 with $1 strikes needs 30 and was given 80; ~48 equities
    need under 20 and were given 40. Over-fetching is not free -- it saturates the 2-slot
    chain gate, and every payload is persisted twice (RC-6).

    The count is a function of the span bar, spot, and the instrument's own spacing, so it
    is derived here rather than tabulated anywhere. Returns None when spot or increment is
    unknown; the caller decides the cold-start default rather than getting a fabricated one.
    """
    if spot is None or increment is None:
        return None
    try:
        s, inc = float(spot), float(increment)
    except (TypeError, ValueError):
        return None
    if s <= 0 or inc <= 0 or span_pct <= 0:
        return None
    span_points = 2.0 * span_pct * s          # full width: spot-5% .. spot+5%
    return int(math.ceil(span_points / inc * margin)) + 1


def gamma_at_price(profile: List[tuple[float, float]], price: float) -> float | None:
    """Net dealer gamma at `price`, linearly interpolated from the profile.

    This -- not the flip -- is what determines the regime: positive means dealers are net
    long gamma there and will dampen moves; negative means they amplify. The flip is
    simply where this value crosses zero, and a chain need not contain such a crossing.

    RC-320: the claim above is SIGN-based, and that is why it is defensible — a dealer long
    gamma sells rallies and buys dips, which dampens; short gamma does the opposite. Source:
    Ni, Pearson and Poteshman, Journal of Financial Economics,
    doi:10.1016/j.jfineco.2004.08.005, where expiration-date clustering turns on NET
    positioning; and https://spotgamma.com/what-is-gex-gamma-exposure/ on the sign
    convention and on dealer ownership being modelled rather than observed.

    Worth recording because of how it was found: this correct statement was already in the
    repository, uncited, while I wrote the CONTRADICTING claim -- that magnitude pins
    regardless of sign -- into pick_pin_and_strength one file away. The refutation was
    already here. Nothing compared the two, because neither carried a source.
    """
    if not profile or price is None:
        return None
    pts = sorted(profile)
    if price <= pts[0][0]:
        return pts[0][1]
    if price >= pts[-1][0]:
        return pts[-1][1]
    for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
        if x0 <= price <= x1:
            if x1 == x0:
                return y0
            t = (price - x0) / (x1 - x0)
            return y0 + t * (y1 - y0)
    return None


def compute_gamma_flip_v2(
    contracts: List[dict], spot: float, *, min_span_pct: float = GAMMA_FLIP_MIN_SPAN_PCT,
    trusted_span_pct: float = GAMMA_FLIP_TRUSTED_SPAN_PCT,
    now=None, profile: List[tuple[float, float]] | None = None
) -> tuple[float | None, str, dict]:
    """Canonical gamma flip (profile zero-crossing) plus a CHAIN-COVERAGE verdict.

    Returns (flip | None, confidence, diagnostics). The verdict reports how much of the chain
    around spot was actually delivered — it does NOT certify that the flip level is correct
    (see the GAMMA_FLIP_TRUSTED block for exactly what it does and does not assert).

    THREE tiers, by delivered span (corrected 2026-08-26 — this docstring previously described
    only two, and framed the result as trustworthiness rather than coverage):
      * >= trusted_span_pct              -> GAMMA_FLIP_TRUSTED (coverage reaches the measured
                                            convergence span; still not proof of the level)
      * >= min_span_pct, < trusted_span  -> GAMMA_FLIP_LEVEL_APPROX (enough strikes near spot for
                                            the at-spot SIGN, so the regime stands, but too narrow
                                            to place the LEVEL — consumers must disclose that)
      * < min_span_pct                   -> GAMMA_FLIP_NARROW (nothing is claimed)
    Why the floor exists at all: a narrow chain provably misplaces the flip (measured 2026-07-19 —
    a 40-contract chain returned 770.35 against a full-chain reference of 745.61, a 3.6% error).
    """
    if not contracts or not spot or spot <= 0:
        return None, GAMMA_FLIP_UNAVAILABLE, {"reason": "no_contracts_or_spot"}
    strikes = [k for k in (_f(c.get("strikePrice")) for c in contracts if isinstance(c, dict)) if k]
    if not strikes:
        return None, GAMMA_FLIP_UNAVAILABLE, {"reason": "no_strikes"}
    lo, hi = min(strikes), max(strikes)
    diag = {
        "strike_lo": lo,
        "strike_hi": hi,
        "n_strikes": len(set(strikes)),
        "span_below_pct": round((spot - lo) / spot, 4),
        "span_above_pct": round((hi - spot) / spot, 4),
        "min_span_pct": min_span_pct,
    }
    # Gamma audit 2026-08-26: TWO span tests, because they answer two different questions.
    #  covers_regime — reaches the conservative floor below which we decline to claim anything.
    #                  NOT "enough strikes for the at-spot SIGN to mean anything" — that wording was
    #                  withdrawn 2026-08-26 as unmeasured; span does not establish the sign (see
    #                  GAMMA_FLIP_MIN_SPAN_PCT for the measurement). Clearing it means we are willing
    #                  to speak, not that the sign is verified.
    #  covers_level  — the measured convergence span for the flip LEVEL itself
    #                  (GAMMA_FLIP_TRUSTED_SPAN_PCT; see its provenance block). Only this earns TRUSTED.
    # Previously ONE test (at the fetch-width constant) awarded TRUSTED, so a chain whose flip is
    # measurably ~1.4% of spot off was presented as trustworthy — the defect the operator flagged.
    covers_regime = lo <= spot * (1.0 - min_span_pct) and hi >= spot * (1.0 + min_span_pct)
    covers_level = lo <= spot * (1.0 - trusted_span_pct) and hi >= spot * (1.0 + trusted_span_pct)
    covers = covers_level          # TRUSTED is earned by the LEVEL span, never the fetch width
    _verdict = (GAMMA_FLIP_TRUSTED if covers_level
                else GAMMA_FLIP_LEVEL_APPROX if covers_regime
                else GAMMA_FLIP_NARROW)
    diag = {**diag, "trusted_span_pct": trusted_span_pct,
            "covers_regime_span": covers_regime, "covers_level_span": covers_level}
    # RC-345 / F03: accept a pre-built profile so the caller can materialize the gamma
    # profile ONCE (one producer, one pinned `now`) and share it between the flip and the
    # regime/gamma-at-spot read. When None, build it here (single-call callers). Passing a
    # profile pins its `now`, so terrain no longer materializes the same curve twice at two
    # wall-clock instants.
    if profile is None:
        profile = compute_gamma_profile(contracts, spot, now=now)
    flip = gamma_flip_from_profile(profile, spot)   # nearest crossing, EITHER direction

    # Dealer gamma AT SPOT is what defines the regime. The flip is only the price where
    # that sign changes -- it is a landmark, not a prerequisite.
    #
    # Corrected 2026-07-19 (RC-11): a profile that never crosses zero inside the window
    # used to return UNAVAILABLE, so 20 of 51 tickers displayed "TERRAIN UNAVAILABLE --
    # STAND ASIDE" while their dealer gamma was unambiguously one-signed at every price
    # (e.g. TSM all-negative, MET all-positive across a wide chain). No crossing nearby
    # means there is no regime boundary to worry about, which is MORE certain than a flip
    # sitting next to spot -- not less. Only the flip level is unknown, never the regime.
    at_spot = gamma_at_price(profile, spot)
    diag = {**diag, "gamma_at_spot": at_spot,
            "no_crossing_in_window": flip is None and at_spot is not None}

    if at_spot is None:
        return None, GAMMA_FLIP_UNAVAILABLE, {**diag, "reason": "empty_profile"}
    if flip is None:
        # regime is knowable; the flip level is not
        return None, _verdict,                {**diag, "reason": "no_zero_crossing_regime_still_defined"}
    return flip, _verdict, diag


# ── HVL — strike with largest total gamma (call + put) ───────────────────────

def _total_gamma_at_strike(bucket: dict, *, dollarized: bool = False) -> float | None:
    c = bucket_metric(bucket, "call_gex_1pct")
    p = bucket_metric(bucket, "put_gex_1pct")
    if dollarized or ((c is not None and c != 0) or (p is not None and p != 0)):
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
    return v if v is not None and v > 0 else None


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
            if _strike_total_oi(b) is None:
                continue
            call_oi_raw = bucket_metric(b, "call_oi")
            put_oi_raw = bucket_metric(b, "put_oi")
            call_w_raw = bucket_metric(b, "call_oi_mult")
            put_w_raw = bucket_metric(b, "put_oi_mult")
            if call_oi_raw is not None and float(call_oi_raw) > 0 and call_w_raw is None:
                continue
            if put_oi_raw is not None and float(put_oi_raw) > 0 and put_w_raw is None:
                continue
            call_w = 0.0
            if call_w_raw is not None:
                call_w = float(call_w_raw)
            put_w = 0.0
            if put_w_raw is not None:
                put_w = float(put_w_raw)
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
    return _strike_total_oi(b)


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
        tg = total_gamma_raw_at_strike(bucket)
        if tg is not None and tg > 0:
            return tg
        c = bucket_metric_abs(bucket, "call_gamma")
        p = bucket_metric_abs(bucket, "put_gamma")
        parts = [v for v in (c, p) if v is not None]
        if parts:
            raw = sum(parts)
            if raw > 0:
                return raw
        return bucket_metric_abs(bucket, "net_gex_1pct")

    def _get_oi(bucket):
        return _strike_total_oi(bucket)

    # Find max absolute GEX and max OI for threshold reference
    max_abs_gex = 0.0
    max_oi = 0.0
    for k in strikes:
        bucket = exposures_by_strike.get(k, {})
        gex = _get_gex(bucket)
        oi = _get_oi(bucket)
        if gex is not None and gex > max_abs_gex:
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
        if gex is None:
            is_void = False
        else:
            is_void = (gex < gex_threshold) and (
                oi is not None and oi < oi_threshold if max_oi > 0 else True
            )
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
                gex_samples = []
                for j in range(zone_start, i):
                    bucket = exposures_by_strike.get(strikes[j], {})
                    gv = _get_gex(bucket)
                    if gv is not None:
                        gex_samples.append(gv)
                avg_gex_pct: float | None = None
                if gex_samples and max_abs_gex > 0:
                    avg_gex_pct = round(
                        (sum(gex_samples) / len(gex_samples)) / max_abs_gex * 100, 1
                    )

                zones.append({
                    "lower": lower,
                    "upper": upper,
                    "width_pts": round(upper - lower, 2),
                    "above_spot": lower > spot,
                    "below_spot": upper < spot,
                    "contains_spot": lower <= spot <= upper,
                    "avg_gex_pct": avg_gex_pct,
                    "dist_to_spot": round(min(abs(lower - spot), abs(upper - spot)), 2),
                })
            in_void = False

    # Handle void at end of chain
    if in_void:
        zone_len = len(strikes) - zone_start
        if zone_len >= min_width_strikes:
            lower = strikes[zone_start]
            upper = strikes[-1]
            gex_samples_end: list[float] = []
            for j in range(zone_start, len(strikes)):
                bucket = exposures_by_strike.get(strikes[j], {})
                gv = _get_gex(bucket)
                if gv is not None:
                    gex_samples_end.append(gv)
            avg_gex_pct_end: float | None = None
            if gex_samples_end and max_abs_gex > 0:
                avg_gex_pct_end = round(
                    (sum(gex_samples_end) / len(gex_samples_end)) / max_abs_gex * 100, 1
                )

            zones.append({
                "lower": lower,
                "upper": upper,
                "width_pts": round(upper - lower, 2),
                "above_spot": lower > spot,
                "below_spot": upper < spot,
                "contains_spot": lower <= spot <= upper,
                "avg_gex_pct": avg_gex_pct_end,
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
        return {
            "count": None,
            "level_names": None,
            "density_label": None,
            "radius": radius_pts,
        }

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



