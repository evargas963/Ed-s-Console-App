"""
math_levels.py
Chartable key-level engine — walls, pins, inflections, support/resistance
derived from options exposure structure.

Phase 2 extraction from math_exposure.py per Extraction Blueprint v1.
"""
from __future__ import annotations

import math
from dataclasses import (
    dataclass,
)
from typing import Dict, List

from math_exposure_core import (
    _f,
    bucket_metric,
    strike_oi_legs,
    key_level_strikes_with_oi,
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



# ── Constants ─────────────────────────────────────────────────────────────────





# ── Inflection / OI helpers ───────────────────────────────────────────────────






# ── Summary rows ──────────────────────────────────────────────────────────────



# ── Wall selection / dominance helpers ────────────────────────────────────────



# ── Wall rows builder ────────────────────────────────────────────────────────







# ── Totals rows builder ──────────────────────────────────────────────────────
# Imports for IV extraction (from math_volatility)



# ── Pin zone classification ──────────────────────────────────────────────────



# ── Parity / synthetic forward ───────────────────────────────────────────────



# ── Gamma Exposure Profile — total dealer gamma recomputed at hypothetical spot ──
# CANONICAL method (FIND-GAMMA-FLIP-METHOD-V1). Proven 2026-07-19 against a real SPY
# reference chain: the cumulative-sum approach does NOT reproduce the profile
# (corr 0.086, never crosses zero, 2.19e9 divergence). Only recomputing every contract's
# gamma at each candidate price reproduces the published flip (SPY 745.61, SKHY 124.44).

_SQRT_2PI = math.sqrt(2.0 * math.pi)


def _norm_pdf(x: float) -> float:
    return math.exp(-0.5 * x * x) / _SQRT_2PI




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


def compute_charm_by_strike(contracts: List[dict], spot: float, now=None,
                            parsed: "list | None" = None) -> Dict[float, dict]:
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
    for strike, oi, mult, t_years, sigma, sign in (parsed if parsed is not None
                                                   else contract_inputs(contracts, now)):
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


def contract_inputs(contracts: List[dict], now=None) -> list:
    """_contract_inputs for every usable contract -- parse a chain once, share it between the
    gamma profile and charm (compute_terrain)."""
    return [p for p in (_contract_inputs(c, now=now) for c in contracts if isinstance(c, dict)) if p]


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
                          sign_model: str = SIGN_MODEL_NAIVE, now=None,
                          parsed: "list | None" = None) -> List[tuple[float, float]]:
    """Total dealer gamma exposure (per 1% move, dollars) at each candidate price.

    Dealer convention per `sign_model` (default naive +call/−put — the only model in
    production; empirical_prior exists for the TU-04 A/B scorecard). Returns
    [(price, total_gex)] ascending. The zero crossing of this curve is the gamma flip.
    """
    if not contracts or spot is None or spot <= 0:
        return []
    if parsed is None:
        parsed = contract_inputs(contracts, now)
    if not parsed:
        return []
    lo, hi = spot * (1.0 - span_pct), spot * (1.0 + span_pct)
    steps = max(int(steps), 2)
    grid = [lo + (hi - lo) * i / steps for i in range(steps + 1)]
    totals = _gamma_profile_totals(parsed, grid, sign_model)
    return [(round(s, 4), total) for s, total in zip(grid, totals)]


#: Candidate prices evaluated per numpy block in _gamma_profile_totals (bounds memory: a
#: 30,000-contract chain x 32 prices is ~1M floats per temporary).
_GAMMA_PROFILE_BLOCK = 32


def _gamma_profile_totals(parsed: list, grid: List[float], sign_model: str) -> List[float]:
    """sum over contracts of dealer_sign * bs_gamma(s) * oi * mult * s^2 * 0.01, per s in grid.

    The same Black-Scholes gamma bs_gamma computes (r = q = 0, as every production caller
    passes), evaluated as arrays instead of one Python call per (price, contract) pair.
    MEASURED 2026-09-25 on SPY's full chain (13,290 contracts x 241 prices): the per-call
    loop made 2.27M bs_gamma calls and was 82% of compute_terrain's 17.8 s. A gamma that is
    not finite contributes nothing, exactly as bs_gamma's None did."""
    import numpy as np

    arr = np.asarray(parsed, dtype=float)
    strike, oi, mult, t_years, sigma, side = (arr[:, i] for i in range(6))
    sign = np.array([_dealer_sign(int(x), sign_model) for x in side], dtype=float)
    vt = sigma * np.sqrt(t_years)
    drift = 0.5 * sigma * sigma * t_years
    weight = sign * oi * mult
    s_all = np.asarray(grid, dtype=float)
    out: List[float] = []
    with np.errstate(all="ignore"):
        for start in range(0, len(s_all), _GAMMA_PROFILE_BLOCK):
            s = s_all[start:start + _GAMMA_PROFILE_BLOCK, None]
            d1 = (np.log(s / strike) + drift) / vt
            g = np.exp(-0.5 * d1 * d1) / _SQRT_2PI / (s * vt)
            g = np.where(np.isfinite(g), g, 0.0)
            out.extend(((g * weight).sum(axis=1) * s[:, 0] * s[:, 0] * 0.01).tolist())
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
        if v <= target < prev_v:
            gsf = round(_cross(p, v, prev_p, prev_v), 2)
            break
        prev_p, prev_v = p, v
    # walk UP from spot: the FIRST crossing above spot is the lowest such s
    above = [(p, v) for p, v in profile if p > spot]
    prev_p, prev_v = float(spot), float(n_spot)
    for p, v in above:
        if v <= target < prev_v:
            grc = round(_cross(prev_p, prev_v, p, v), 2)
            break
        prev_p, prev_v = p, v
    return {"gsf": gsf, "grc": grc, "state": GSF_STATE_OK, "n_at_spot": round(n_spot, 2)}




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
#: NOT certify the sign: agreement between the truncated and full-chain MODELLED sign improves with
#: width, but gradually and with no threshold effect at the floor (a SUPPORTED trend, not a proven
#: one), so clearing this tier buys no guarantee. The tier means "level not placed", nothing more.
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
#: WHAT IS BEING COMPARED — read this before quoting any number above. Both sides of the comparison
#: are MODELLED. It measures whether the +call/-put dealer sign computed on a TRUNCATED window
#: matches the +call/-put dealer sign computed on the FULL DELIVERED chain. The full-chain value is
#: a reference, NOT ground truth: public OI cannot establish who actually owns the contracts, so
#: this says nothing about whether either sign matches real dealer positioning. It bounds how much
#: TRUNCATION perturbs our own modelled sign, and nothing more.
#: WHAT THIS SUPPORTS, stated no wider than the data (tightened again 2026-08-26 after review — the
#: previous wording said "WHAT THIS PROVES" and was too strong on both points):
#:  (a) The monotonic span relationship is SUPPORTED, NOT PROVEN. Agreement rises across the ladder
#:      and the extreme ends do not overlap (79.8% [0.742,0.845] at +/-1% vs 92.7% [0.888,0.954] at
#:      +/-15%), which is real evidence of a trend. It falls short of proof because ADJACENT rungs
#:      overlap heavily, the rungs are NOT independent samples (largely the same chains re-windowed,
#:      so the observations are paired/reused), NO PAIRED TEST was run, and NO POWER ANALYSIS was
#:      done. What would settle it: a paired per-chain test across rungs (e.g. McNemar on +/-1% vs
#:      +/-15% over the same chains) with a pre-registered effect size.
#:      (An earlier note said span "barely" governs the sign — an overstatement the other way, also
#:      withdrawn. Neither "barely matters" nor "genuinely reads it better" is established.)
#:  (b) The data are EVIDENCE AGAINST a special threshold at 0.05 — not proof of its absence. The
#:      curve is smooth through 0.05 with no visible cliff or knee, and at exactly the floor the
#:      modelled sign still disagrees with the full-chain modelled sign about ONE TIME IN SEVEN. So
#:      the floor is not shown to mark where the sign becomes knowable; absence of a threshold is
#:      not demonstrated to the standard a positive claim would need.
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
    # TRUSTED is earned by the LEVEL span, never the fetch width
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
    # Pain over the WHOLE grid or not at all (M-08): a strike whose OI is unknown, or whose
    # positive OI carries no contract multiplier, used to be SKIPPED -- a max pain computed
    # over part of the open interest. One-sided strikes used to be dropped too.
    weights: dict[float, tuple[float, float]] = {}
    for k, b in exposures_by_strike.items():
        legs = strike_oi_legs(b)
        if legs is None:
            return None
        w = []
        for oi, key in ((legs[0], "call_oi_mult"), (legs[1], "put_oi_mult")):
            if oi <= 0:
                w.append(0.0)
                continue
            m = bucket_metric(b, key)
            if m is None:
                return None
            w.append(float(m))
        weights[float(k)] = (w[0], w[1])

    def _pain_at(settlement: float) -> float:
        pain = 0.0
        for k in strikes:
            call_w, put_w = weights[float(k)]
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




# ── Low Gamma Void Zones — acceleration corridors ────────────────────────────



# ── Level Density — how crowded is the area around spot ──────────────────────




