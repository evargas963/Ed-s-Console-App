"""
math_levels.py: chartable key-level engine.

Walls, pins, inflections, support/resistance derived from options exposure structure.
"""

from __future__ import annotations

import functools
from dataclasses import replace
from datetime import datetime

import numpy as np

from math_exposure_core import (
    bs_charm_array,
    bsm_gamma_delta,
    bucket_metric,
    d1_vt,
    key_level_strikes_with_oi,
    norm_pdf,
    schwab_iv_to_sigma,
    strike_oi_legs,
)
from option_contract import OptionContract
from time_et import time_to_expiry_years

# ── Gamma Exposure Profile — total dealer gamma recomputed at hypothetical spot ──
# Every contract's gamma is recomputed at each candidate price; a cumulative sum does NOT
# reproduce the profile (against a real SPY reference chain: corr 0.086, never crosses zero);
# recomputing reproduces the published flip (SPY 745.61, SKHY 124.44).


def compute_charm_by_strike(
    contracts: list[OptionContract],
    spot: float,
    *,
    now: datetime,
    t_years: float | None = None,
    product: str = "EQO",
) -> dict[float, dict]:
    """Per-strike dealer CHARM exposure, in delta-shares per day. `t_years`: as _contract_inputs.

    Charm exposure is standard institutional practice (SpotGamma, Unusual Whales and
    VannaCharm all publish charm-by-strike alongside GEX), and charm pressure is the
    mechanism attributed to the end-of-day pin: dealers bleeding delta into the close.

    Convention matches net GEX exactly (+call / -put), so a positive net value means the
    dealer book gains delta as time passes, which the dealer hedges by SELLING the underlying
    (a negative net value: losing delta, hedged by buying).

    Units: charm/year * OI * multiplier / 365 -> delta-shares per day.

    A contract that cannot be priced leaves its side None and the strike's net None, as a side's
    unknown gamma does in compute_exposures_by_strike. A contract with open interest 0 adds
    nothing, so a strike whose contracts all have none is 0. A settled one has no charm left.
    """
    out: dict[float, dict] = {}
    if not contracts or not spot or spot <= 0:
        return out
    tte = _expiry_years(now, product)
    # each contract that counts: its strike, its side's slot, and its pricing inputs (NaN: it
    # cannot be priced, so its side's sum is not known)
    slot, inputs = [], []
    for c in contracts:
        years = t_years if t_years is not None else tte(c.expiration, c.settlement)
        if years == 0 or c.strike is None or c.side is None:  # settled, or no strike or side
            continue
        out.setdefault(c.strike, {"call_charm": 0.0, "put_charm": 0.0, "net_charm": 0.0})
        row = _contract_inputs(c, now, t_years=years, product=product)
        if row == "zero_open_interest":  # no contract open: it adds nothing to its strike's 0
            continue
        slot.append((c.strike, c.side == "CALL"))
        inputs.append(row[1:5] if isinstance(row, tuple) else (np.nan,) * 4)
    if not slot:
        return out
    at = {k: i for i, k in enumerate(out)}
    where = np.array([2 * at[k] + (not call) for k, call in slot])
    oi, mult, years, sigma = np.array(inputs, float).T
    strike = np.array([k for k, _call in slot], float)
    charm = bs_charm_array(float(spot), strike, years, sigma)
    exposure = charm * oi * mult / 365.0
    known = ~np.isnan(exposure)
    # bincount adds each side's exposures one at a time, in the chain's order
    sums = np.bincount(where[known], weights=exposure[known], minlength=2 * len(at)).tolist()
    for s in np.unique(where[~known]).tolist():  # one not known leaves its side not known
        sums[s] = None
    for i, b in enumerate(out.values()):
        call, put = sums[2 * i], sums[2 * i + 1]
        b["call_charm"], b["put_charm"] = call, put
        b["net_charm"] = None if call is None or put is None else call - put
    return out


def _add_charm(bucket: dict, side: str, exposure: float | None) -> None:
    """Add to one side of a strike. One unknown leaves that side and the strike's net unknown."""
    side_now = bucket[side]
    bucket[side] = None if side_now is None or exposure is None else side_now + exposure
    call, put = bucket["call_charm"], bucket["put_charm"]
    bucket["net_charm"] = None if call is None or put is None else call - put


def merge_charm_maps(maps: dict[str, dict[float, dict]]) -> dict[float, dict]:
    """Merge per-expiry maps of the same function into one strike map.

    A strike listed on more than one expiry is the sum of those expiries, +call/−put, the same
    as one call over every contract.
    """
    out: dict[float, dict] = {}
    for part in maps.values():
        for strike, bucket in part.items():
            cur = out.get(strike)
            if cur is None:
                out[strike] = {
                    "call_charm": bucket["call_charm"],
                    "put_charm": bucket["put_charm"],
                    "net_charm": bucket["net_charm"],
                }
                continue
            for side in _CHARM_SIDES:
                _add_charm(cur, side, bucket[side])
    return out


def pick_charm_wall_strikes(
    charm_by_strike: dict[float, dict],
) -> tuple[float | None, float | None]:
    """(call_charm_wall, put_charm_wall) — strikes of maximum call-side and put-side charm exposure.

    These are the strikes whose delta decay exerts the most mechanical
    pressure into the close.
    """

    def wall(side: str) -> float | None:
        known = {k: abs(b[side]) for k, b in charm_by_strike.items() if b[side] is not None}
        strike = max(known, key=known.get, default=None)
        return strike if strike is not None and known[strike] > 0 else None

    return wall("call_charm"), wall("put_charm")


_CHARM_SIDES = ("call_charm", "put_charm")


def contract_inputs(
    contracts: list[OptionContract], now: datetime, product: str = "EQO"
) -> tuple[list, dict]:
    """(priced, unpriced): the gamma profile's inputs for every contract with open interest.

    Each priced row is the contract's _profile_row. They are parsed once for the gamma profile
    (compute_terrain); `unpriced` counts the contracts with open interest the profile could not
    price, by reason.
    """
    priced, unpriced = [], {}
    tte = _expiry_years(now, product)
    for c in contracts:
        row = _profile_row(c, now, tte(c.expiration, c.settlement), product)
        if isinstance(row, tuple):
            priced.append(row)
        elif row != "zero_open_interest":
            unpriced[row] = unpriced.get(row, 0) + 1
    return priced, unpriced


def _profile_row(
    c: OptionContract, now: datetime, t_years: float | None, product: str
) -> tuple | str:
    """One contract's gamma-profile row, or the reason it cannot be priced.

    The row is _contract_inputs' (strike, oi, mult, t_years, sigma, sign) and then the contract's
    rate and dividend yield as decimals: Schwab's /chains `interestRate` (OptionChain,
    docs/schwab/schwab_market_data_api_spec.pdf p. 27) and `dividendYield`, percents as sent. A
    contract sent without either is not priced ("no_rate").
    """
    row = _contract_inputs(c, now, t_years=t_years, product=product)
    rate, dividend = c.interest_rate, c.dividend_yield
    if isinstance(row, tuple) and rate is not None and dividend is not None:
        return (*row, rate / 100.0, dividend / 100.0)
    return row if isinstance(row, str) else "no_rate"


def repriced_to_close(
    contracts: list[OptionContract], spot: float, now: datetime, t_close: float, product: str
) -> tuple[list[OptionContract], list]:
    """(contracts, priced): each contract as if it expired `t_close` years from `now`.

    Its gamma and delta are the Black-Scholes-Merton ones at that horizon (bsm_gamma_delta, on
    Schwab's volatility, rate and dividend yield as sent), from the row the gamma profile prices
    it by (`priced`, as contract_inputs'). A contract with no row has neither: not known, never
    Schwab's Greek at its own expiry.
    """
    rows = [_profile_row(c, now, t_close, product) for c in contracts]
    greeks = (
        bsm_gamma_delta(spot, r[0], *r[3:]) if isinstance(r, tuple) else (None, None) for r in rows
    )
    return (
        [replace(c, gamma=g, delta=d) for c, (g, d) in zip(contracts, greeks, strict=True)],
        [r for r in rows if isinstance(r, tuple)],
    )


def _expiry_years(now: datetime, product: str):
    """Return time_to_expiry_years at `now`, computed once per (expiration, settlement)."""
    return functools.cache(
        lambda expiration, settlement: time_to_expiry_years(
            expiration, now=now, settlement_type=settlement, product=product
        )
    )


def _contract_inputs(
    c: OptionContract,
    now: datetime,
    *,
    t_years: float | None = None,
    product: str = "EQO",
) -> tuple[float, float, float, float, float, int] | str:
    """(strike, oi, mult, t_years, sigma, sign), or the reason it cannot be priced.

    `t_years` is the canonical INTRADAY time-to-expiry (time_et.time_to_expiry_years): to the
    contract's settlement (the option market's regular close Schwab's /markets sent for its
    expiry date, or its open for Schwab's settlementType "A"; on a date /markets has not answered,
    as time_et.time_to_expiry_years says), ACT/365, from `now` (the caller's valuation instant),
    unless the caller passes `t_years`. Offline/replay callers pass
    `now` = the snapshot time.
    """
    strike, oi, mult = c.strike, c.open_interest, c.multiplier
    if oi == 0:
        return "zero_open_interest"
    if t_years is None:
        t_years = time_to_expiry_years(
            c.expiration, now=now, settlement_type=c.settlement, product=product
        )
    if t_years == 0:
        return "settled"
    if oi is None:
        return "no_open_interest"
    if strike is None or strike <= 0 or mult is None or c.side is None:
        return "invalid"
    sigma = schwab_iv_to_sigma(c.volatility)
    if sigma is None or sigma <= 0:
        return "no_volatility"
    if t_years is None:
        return "no_expiry"
    return strike, oi, mult, t_years, sigma, (1 if c.side == "CALL" else -1)


#: The gamma profile's candidate prices: spot +/- 15%, in 240 equal steps.
GAMMA_PROFILE_SPAN_PCT = 0.15
GAMMA_PROFILE_STEPS = 240


def compute_gamma_profile(parsed: list, spot: float) -> list[tuple[float, float]]:
    """Total dealer gamma exposure (per 1% move, dollars) at each candidate price.

    `parsed`: the contracts' priced rows (contract_inputs', or repriced_to_close's). One dealer
    convention for every instrument: +call / -put. Returns [(price, total_gex)] ascending. The
    zero crossing of this curve is the gamma flip.
    """
    if not parsed or spot is None or spot <= 0:
        return []
    lo, hi = spot * (1.0 - GAMMA_PROFILE_SPAN_PCT), spot * (1.0 + GAMMA_PROFILE_SPAN_PCT)
    steps = GAMMA_PROFILE_STEPS
    grid = [lo + (hi - lo) * i / steps for i in range(steps + 1)]
    totals = _gamma_profile_totals(parsed, grid)
    return list(zip(grid, totals))


#: Candidate prices evaluated per numpy block in _gamma_profile_totals (bounds memory: a
#: 30,000-contract chain x 32 prices is ~1M floats per temporary).
_GAMMA_PROFILE_BLOCK = 32


def _gamma_profile_totals(parsed: list, grid: list[float]) -> list[float]:
    """Sum over contracts of side_sign * gamma(s) * oi * mult * s^2 * 0.01, per s in grid.

    gamma is the Black-Scholes-Merton gamma with each contract's rate r and dividend yield q as
    Schwab sent them (Hull, Options, Futures and Other Derivatives, ch. 19):
    e^(-qT) * phi(d1) / (s * sigma * sqrt(T)), d1 = (ln(s/K) + (r - q + sigma^2/2) T) /
    (sigma sqrt(T)). Evaluated as arrays, one block of prices at a time. A gamma that is not
    finite contributes nothing.
    """
    arr = np.asarray(parsed, dtype=float)
    strike, oi, mult, t_years, sigma, side, rate, dividend = (arr[:, i] for i in range(8))
    weight = side * oi * mult * np.exp(-dividend * t_years)
    s_all = np.asarray(grid, dtype=float)
    out: list[float] = []
    with np.errstate(all="ignore"):
        for start in range(0, len(s_all), _GAMMA_PROFILE_BLOCK):
            s = s_all[start : start + _GAMMA_PROFILE_BLOCK, None]
            d1, vt = d1_vt(s, strike, t_years, sigma, rate - dividend, log=np.log, sqrt=np.sqrt)
            g = norm_pdf(d1, exp=np.exp) / (s * vt)
            g = np.where(np.isfinite(g), g, 0.0)
            out.extend(((g * weight).sum(axis=1) * s[:, 0] * s[:, 0] * 0.01).tolist())
    return out


def gamma_flip_from_profile(profile: list[tuple[float, float]], spot: float) -> float | None:
    """Interpolated price where net dealer gamma changes SIGN — in either direction.

    Both directions are boundaries; the direction only changes what lies on each side,
    which the caller derives from gamma_at_price at spot.

    When several crossings exist, the one NEAREST SPOT is returned:
    regime is the sign AT spot, so the closest sign change is the boundary that governs
    the move the operator is actually trading.
    """
    crossings: list[float] = []
    for i in range(1, len(profile)):
        (p0, v0), (p1, v1) = profile[i - 1], profile[i]
        if v1 == v0:
            continue
        # v0 == 0 is itself the boundary. The v1==0 side is handled below:
        # v0<0<=v1 / v0>0>=v1 interpolate to p1 when the segment ENDS at zero.
        if v0 == 0:
            crossings.append(p0)
        elif (v0 < 0 <= v1) or (v0 > 0 >= v1):
            crossings.append(_lerp(0.0, v0, v1, p0, p1))
    if not crossings:
        return None
    return min(crossings, key=lambda c: abs(c - spot))


#: Gamma Support Floor / Gamma Resistance Ceiling — construction constants.
#: phi: the support-decay fraction (Barbon & Buraschi gamma-fragility framing): the level where
#: the dealer stabilization cushion N(s) has decayed to phi of its at-spot value. 0.5 =
#: "half-support", communicable and parameter-honest; calibratable in [0.25, 0.6] on banked bars
#: later (placebo-tested), never silently re-tuned.
GSF_PHI = 0.5
#: eps guard: below this fraction of the profile's max |N|, the at-spot cushion is too small
#: for a ratio to mean anything — the regime is effectively at/below zero support and the
#: honest output is a STATE, not a fabricated price.
GSF_EPS_FRAC = 0.005
GSF_STATE_OK = "OK"
GSF_STATE_BELOW_SUPPORT = "BELOW_SUPPORT"
GSF_STATE_UNAVAILABLE = "UNAVAILABLE"


def _lerp(x: float, x0: float, x1: float, y0: float, y1: float) -> float:
    """Return y at `x` on the segment (x0, y0)-(x1, y1); y0 on a segment with no width.

    THE one linear interpolation of the profile. Read both ways: the value at a price, and the
    price at a value (the flip, the support and resistance crossings).
    """
    if x1 == x0:
        return y0
    return y0 + (y1 - y0) * (x - x0) / (x1 - x0)


def compute_gamma_support_levels(
    profile: list[tuple[float, float]],
    spot: float | None,
    *,
    phi: float = GSF_PHI,
    eps_frac: float = GSF_EPS_FRAC,
) -> dict:
    """Gamma Support Floor (GSF) + Gamma Resistance Ceiling (GRC) — ONE producer.

    On the repriced net-GEX profile N(s) (`compute_gamma_profile`; the SAME materialized
    profile the flip/regime use):

      GSF = the HIGHEST s < spot where N(s) <= phi * N(spot)
      GRC = the LOWEST s > spot where N(s) <= phi * N(spot)

    Both are measured geometry of the modelled profile (dealers taken as long calls, short
    puts); that price holds at them is not tested. When N(spot) <= eps the state is
    BELOW_SUPPORT with both levels None; an empty or unusable profile is UNAVAILABLE.
    """
    if not profile or spot is None or spot <= 0:
        return {"gsf": None, "grc": None, "state": GSF_STATE_UNAVAILABLE}
    n_spot = gamma_at_price(profile, float(spot))
    if n_spot is None:
        return {"gsf": None, "grc": None, "state": GSF_STATE_UNAVAILABLE}
    max_abs = max(abs(v) for _, v in profile)
    eps = eps_frac * max_abs if max_abs > 0 else 0.0
    if n_spot <= eps:
        return {"gsf": None, "grc": None, "state": GSF_STATE_BELOW_SUPPORT}
    target = phi * n_spot

    gsf: float | None = None
    grc: float | None = None
    # walk DOWN from spot: the FIRST crossing below spot is the highest such s
    below = [(p, v) for p, v in profile if p < spot]
    prev_p, prev_v = float(spot), float(n_spot)
    for p, v in reversed(below):
        if v <= target < prev_v:
            gsf = _lerp(target, v, prev_v, p, prev_p)  # the price where N(s) crosses target
            break
        prev_p, prev_v = p, v
    # walk UP from spot: the FIRST crossing above spot is the lowest such s
    above = [(p, v) for p, v in profile if p > spot]
    prev_p, prev_v = float(spot), float(n_spot)
    for p, v in above:
        if v <= target < prev_v:
            grc = _lerp(target, prev_v, v, prev_p, p)
            break
        prev_p, prev_v = p, v
    return {"gsf": gsf, "grc": grc, "state": GSF_STATE_OK}


#: The flip's verdict is chain coverage: how far the delivered strikes reach around spot. It does
#: not say the level is right, and it is silent on how far the level moves within a session.
GAMMA_FLIP_TRUSTED = "TRUSTED"
GAMMA_FLIP_NARROW = "LOW_CONFIDENCE_NARROW_CHAIN"
GAMMA_FLIP_UNAVAILABLE = "UNAVAILABLE"
#: Middle tier: the chain reaches GAMMA_FLIP_MIN_SPAN_PCT but not GAMMA_FLIP_TRUSTED_SPAN_PCT, so
#: the level is approximate. It certifies neither the level nor the sign of gamma at spot.
GAMMA_FLIP_LEVEL_APPROX = "LEVEL_APPROX_NARROW_SPAN"
#: The floor, as a share of spot each side: a chain that does not reach it earns GAMMA_FLIP_NARROW
#: and nothing is claimed. Reaching it earns at most GAMMA_FLIP_LEVEL_APPROX. Asserted, not derived.
GAMMA_FLIP_MIN_SPAN_PCT = 0.05
#: The span, as a share of spot each side, at which the flip level earns GAMMA_FLIP_TRUSTED: where
#: the measured error against the full-chain flip stopped falling. A floor, not proof of the level.
GAMMA_FLIP_TRUSTED_SPAN_PCT = 0.10


def gamma_at_price(profile: list[tuple[float, float]], price: float) -> float | None:
    """Net dealer gamma at `price`, linearly interpolated from the profile.

    This -- not the flip -- is what determines the regime: positive means dealers are net
    long gamma there and will dampen moves; negative means they amplify. The flip is
    simply where this value crosses zero, and a chain need not contain such a crossing.

    The claim above is SIGN-based, and that is why it is defensible — a dealer long
    gamma sells rallies and buys dips, which dampens; short gamma does the opposite. Source:
    Ni, Pearson and Poteshman, Journal of Financial Economics,
    doi:10.1016/j.jfineco.2004.08.005, where expiration-date clustering turns on NET
    positioning; and https://spotgamma.com/what-is-gex-gamma-exposure/ on the sign
    convention and on dealer ownership being modelled rather than observed.
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
            return _lerp(price, x0, x1, y0, y1)
    return None


def compute_gamma_flip_v2(
    contracts: list[OptionContract], spot: float, *, profile: list[tuple[float, float]]
) -> tuple[float | None, str, dict]:
    """Canonical gamma flip (profile zero-crossing) plus a CHAIN-COVERAGE verdict.

    `profile` is compute_gamma_profile's curve for the same contracts and spot.
    Returns (flip | None, verdict, diagnostics). The verdict is the tier the delivered strikes'
    span around spot earns: GAMMA_FLIP_TRUSTED, GAMMA_FLIP_LEVEL_APPROX or GAMMA_FLIP_NARROW.
    """
    if not contracts or not spot or spot <= 0:
        return None, GAMMA_FLIP_UNAVAILABLE, {}
    strikes = [c.strike for c in contracts if c.strike is not None]
    if not strikes:
        return None, GAMMA_FLIP_UNAVAILABLE, {}
    lo, hi = min(strikes), max(strikes)
    covers_regime = lo <= spot * (1.0 - GAMMA_FLIP_MIN_SPAN_PCT) and hi >= spot * (
        1.0 + GAMMA_FLIP_MIN_SPAN_PCT
    )
    covers_level = lo <= spot * (1.0 - GAMMA_FLIP_TRUSTED_SPAN_PCT) and hi >= spot * (
        1.0 + GAMMA_FLIP_TRUSTED_SPAN_PCT
    )
    # TRUSTED is earned by the LEVEL span, never the fetch width
    _verdict = (
        GAMMA_FLIP_TRUSTED
        if covers_level
        else GAMMA_FLIP_LEVEL_APPROX
        if covers_regime
        else GAMMA_FLIP_NARROW
    )
    # Dealer gamma AT SPOT is what defines the regime. The flip is only the price where
    # that sign changes -- it is a landmark, not a prerequisite: with no crossing inside the
    # window the regime is still known, only the flip level is not.
    at_spot = gamma_at_price(profile, spot)
    diag = {"curve_gamma_at_spot": at_spot}
    if at_spot is None:
        return None, GAMMA_FLIP_UNAVAILABLE, diag
    # nearest crossing, EITHER direction; None when the curve does not cross in the window
    return gamma_flip_from_profile(profile, spot), _verdict, diag


# ── Max Pain — OI-weighted expiry settlement magnet ────────────────────────────


def compute_max_pain(exposures_by_strike: dict[float, dict]) -> float | None:
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
    # Pain over the WHOLE grid or not at all: a strike whose OI is unknown, or whose
    # positive OI carries no contract multiplier, returns None rather than a max pain
    # computed over part of the open interest.
    weights: dict[float, tuple[float, float]] = {}
    for k, b in exposures_by_strike.items():
        legs = strike_oi_legs(b)
        if legs is None:
            return None
        call_w, put_w = (
            0.0 if oi <= 0 else bucket_metric(b, key)
            for oi, key in zip(legs, ("call_oi_mult", "put_oi_mult"), strict=True)
        )
        if call_w is None or put_w is None:
            return None
        weights[float(k)] = (call_w, put_w)

    def _pain_at(settlement: float) -> float:
        pain = 0.0
        for k in strikes:
            call_w, put_w = weights[float(k)]
            if call_w > 0 and settlement > k:
                pain += (settlement - k) * call_w
            if put_w > 0 and settlement < k:
                pain += (k - settlement) * put_w
        return pain

    return min(strikes, key=_pain_at)  # of equal pains, the lowest strike
