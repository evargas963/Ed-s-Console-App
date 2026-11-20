"""Base exposure engine.

Base exposure engine — raw and normalized exposure values derived
from the chain and position structure.
"""

from __future__ import annotations

import functools
import math
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, replace
from datetime import datetime
from typing import TYPE_CHECKING, Any, Literal, TypedDict, get_args

import numpy as np

from numeric_contract import float_finite_or_none
from option_contract import OptionContract, Streamed, streamed_greek_set, streamed_quote
from time_et import Session, time_to_expiry_years

if TYPE_CHECKING:
    from numpy.typing import NDArray


class Bucket(TypedDict):
    """One strike's exposure book.

    Each leg's sums, the counts of what was not reported, the net fields (_finish_bucket) and
    the `dollarized` flag. None is not known: a sum a contract's
    unreported value enters (open interest, volume), or a dollar field or vanna built without
    spot. A gamma, delta or open-interest-times-multiplier sum is always a number (a term not
    known adds nothing and is counted unreported).
    """

    oi_unreported: int
    volume_unreported: int
    call_gamma_unreported: int
    call_delta_unreported: int
    call_vanna_unreported: int
    call_oi_mult_unreported: int
    put_gamma_unreported: int
    put_delta_unreported: int
    put_vanna_unreported: int
    put_oi_mult_unreported: int
    dollarized: bool
    call_oi: float | None
    put_oi: float | None
    call_oi_mult: float
    put_oi_mult: float
    call_gamma: float
    put_gamma: float
    call_vanna: float | None
    put_vanna: float | None
    call_delta: float
    put_delta: float
    net_gamma: float
    net_delta: float
    call_dex_dollars: float | None
    put_dex_dollars: float | None
    net_dex_dollars: float | None
    call_gex_1pct: float | None
    put_gex_1pct: float | None
    net_gex_1pct: float | None
    call_volume: float | None
    put_volume: float | None
    net_vanna: float | None


#: a bucket field that holds a number (every field but the counts and the flag)
type BucketField = Literal[
    "call_oi",
    "put_oi",
    "call_oi_mult",
    "put_oi_mult",
    "call_gamma",
    "put_gamma",
    "call_vanna",
    "put_vanna",
    "call_delta",
    "put_delta",
    "net_gamma",
    "net_delta",
    "call_dex_dollars",
    "put_dex_dollars",
    "net_dex_dollars",
    "call_gex_1pct",
    "put_gex_1pct",
    "net_gex_1pct",
    "call_volume",
    "put_volume",
    "net_vanna",
]
#: a count of a leg's contracts whose term was not reported
type UnreportedField = Literal[
    "call_gamma_unreported",
    "call_delta_unreported",
    "call_vanna_unreported",
    "call_oi_mult_unreported",
    "put_gamma_unreported",
    "put_delta_unreported",
    "put_vanna_unreported",
    "put_oi_mult_unreported",
]

# ── Black-Scholes Greeks per share: the one place their formulas live ──

SQRT_2PI = math.sqrt(2.0 * math.pi)


def norm_pdf[Num: (float, NDArray[np.float64])](
    x: Num, *, exp: Callable[[Num], Num] = math.exp
) -> Num:
    """Return the standard normal density. A number, or a numpy array with exp=np.exp."""
    return exp(-0.5 * x * x) / SQRT_2PI


def d1_vt[Num: (float, NDArray[np.float64])](
    spot: Num | float,
    strike: Num,
    t_years: Num,
    sigma: Num,
    carry: Num | float = 0.0,
    *,
    log: Callable[[Num], Num] = math.log,
    sqrt: Callable[[Num], Num] = math.sqrt,
) -> tuple[Num, Num]:
    """Return THE Black-Scholes d1 and sigma*sqrt(T), with `carry` = r - q (0 unless given).

    Numbers, or numpy arrays with log=np.log and sqrt=np.sqrt (`carry` then a number or an
    array).
    """
    vt = sigma * sqrt(t_years)
    return (log(spot / strike) + (carry + 0.5 * sigma * sigma) * t_years) / vt, vt


def bsm_gamma_delta(
    spot: float, strike: float, t_years: float, sigma: float, sign: int, r: float, q: float
) -> tuple[float, float]:
    """Return the Black-Scholes-Merton gamma and delta per share of a call (`sign` 1) or a put.

    Hull, Options, Futures and Other Derivatives, ch. 19, the rate r and dividend yield q as
    decimals: gamma = e^(-qT) * phi(d1) / (S * sigma * sqrt(T)), the gamma the profile sums
    (calc.math_levels._gamma_profile_totals); delta = e^(-qT) * N(d1) for a call and
    e^(-qT) * (N(d1) - 1) for a put, negative as Schwab's is.
    """
    d1, vt = d1_vt(spot, strike, t_years, sigma, r - q)
    discount = math.exp(-q * t_years)
    cdf = 0.5 * (1.0 + math.erf(d1 / math.sqrt(2.0)))
    return discount * norm_pdf(d1) / (spot * vt), discount * (cdf if sign > 0 else cdf - 1.0)


def _each(
    f: Callable[[float], float], priced: NDArray[np.bool_]
) -> Callable[[NDArray[np.float64]], NDArray[np.float64]]:
    """Return `f` (math.log, math.exp) taken on each priced element, NaN on the rest.

    The platform's own function, as the scalar Greeks take it: numpy's exp and log round the
    last bit differently on some processors, so a value would differ between machines.
    """

    def on(x: NDArray[np.float64]) -> NDArray[np.float64]:
        out = np.full(x.shape, np.nan)
        out[priced] = [f(v) for v in x[priced].tolist()]
        return out

    return on


def _priced_d1(
    spot: float,
    strike: NDArray[np.float64],
    t_years: NDArray[np.float64],
    sigma: NDArray[np.float64],
    rate: NDArray[np.float64],
    dividend: NDArray[np.float64],
) -> tuple[NDArray[np.bool_], NDArray[np.float64], NDArray[np.float64]]:
    """Return which contracts can be priced, and each one's d1 and sigma * sqrt(T).

    Priced: every input positive and the rate and dividend yield known. d1 carries r - q
    (d1_vt), NaN where not priced.
    """
    priced = (
        (spot > 0)
        & (strike > 0)
        & (t_years > 0)
        & (sigma > 0)
        & np.isfinite(rate)
        & np.isfinite(dividend)
    )
    d1, vt = d1_vt(
        spot,
        strike,
        t_years,
        sigma,
        rate - dividend,
        log=_each(math.log, priced),
        sqrt=np.sqrt,
    )
    return priced & np.isfinite(d1), d1, vt


def bs_vanna_array(
    spot: float,
    strike: NDArray[np.float64],
    t_years: NDArray[np.float64],
    sigma: NDArray[np.float64],
    rate: NDArray[np.float64],
    dividend: NDArray[np.float64],
) -> NDArray[np.float64]:
    """Black-Scholes-Merton vanna (dDelta/dSigma) per share of each contract.

    `rate` r and `dividend` q are the chain's interestRate and dividendYield as decimals.
    Identical for calls and puts. Closed form: -e^(-qT) * phi(d1) * d2 / sigma, d1 with the
    carry r - q (Hull, Options, Futures and Other Derivatives, ch. 19; the same d1 as the gamma
    profile's). Sign is driven by -d2, never by the call/put boundary.
    Units: delta-change per 1.00 of IV (100 vol points); multiply by 0.01 for per-vol-point
    -- the sigma-scaling convention is LOCKED here beside the dealer convention.
    NaN where it cannot be priced: an input not positive (or NaN, not known), a rate or a
    dividend yield not known, a d1 or a vanna that is not finite.
    """
    with np.errstate(all="ignore"):
        priced, d1, vt = _priced_d1(spot, strike, t_years, sigma, rate, dividend)
        exp = _each(math.exp, priced)
        d2 = d1 - vt
        v = -exp(-dividend * t_years) * norm_pdf(d1, exp=exp) * d2 / sigma
    return np.where(priced & np.isfinite(v), v, np.nan)


def bs_charm_array(
    spot: float,
    strike: NDArray[np.float64],
    t_years: NDArray[np.float64],
    sigma: NDArray[np.float64],
    sign: NDArray[np.float64],
    rate: NDArray[np.float64],
    dividend: NDArray[np.float64],
) -> NDArray[np.float64]:
    """Black-Scholes-Merton charm (dDelta/dt, calendar time) per share of each contract.

    `sign` is 1 for a call and -1 for a put; `rate` r and `dividend` q are the chain's
    interestRate and dividendYield as decimals. The derivative of the Black-Scholes-Merton
    delta (bsm_gamma_delta; Hull ch. 19) as time passes, T shrinking:
    call: q e^(-qT) N(d1) - e^(-qT) phi(d1) [ (r - q)/(sigma sqrt(T)) - d2/(2T) ];
    put: -q e^(-qT) N(-d1) - the same second term. At q = 0 a call's and a put's are equal.
    Checked against a finite difference of that delta, calls and puts, on real chains'
    inputs (tests/test_charm_sign_finite_difference.py).
    NaN where it cannot be priced: an input not positive (or NaN, not known), a rate or a
    dividend yield not known, a d1 or a charm that is not finite.
    """
    with np.errstate(all="ignore"):
        priced, d1, vt = _priced_d1(spot, strike, t_years, sigma, rate, dividend)
        exp = _each(math.exp, priced)
        d2 = d1 - vt
        cdf = 0.5 * (1.0 + _each(math.erf, priced)(sign * d1 / math.sqrt(2.0)))
        c = exp(-dividend * t_years) * (
            sign * dividend * cdf
            - norm_pdf(d1, exp=exp) * ((rate - dividend) / vt - d2 / (2.0 * t_years))
        )
    return np.where(priced & np.isfinite(c), c, np.nan)


def schwab_iv_to_sigma(iv: float | None) -> float | None:
    """Convert Schwab's `volatility` field (a PERCENT) to a decimal sigma: the ONE conversion.

    Measured on 49,244 contracts across the 43-ticker board: min 7.967, median 51.0, max 4,256.8
    -- every value a percent, so one fixed conversion. Schwab's IV is carried as sent; a model input
    needs sigma > 0, so 0 or less gives no sigma.
    """
    if iv is None or iv <= 0:
        return None
    return iv / 100.0


def book_net_gex(exposures: dict[float, Bucket]) -> float | None:
    """Net dealer GEX per 1% move at spot: the sum of every strike's net_gex_1pct.

    Schwab's gamma as sent, +call/-put. The one gamma at spot (regime, headline, pin gate). None
    when no strike carried a valid gamma.
    """
    vals = [v for b in exposures.values() if (v := bucket_metric(b, "net_gex_1pct")) is not None]
    return sum(vals) if vals else None


#: Bucket fields priced from Schwab's gamma / delta / volatility -> the counts of contracts on the
#: field's legs whose term is not known (see compute_exposures_by_strike). A leg with one has no
#: value for the field; every other sum is Schwab's inputs computed, 0 included.
_GREEK_FIELD_UNREPORTED: dict[BucketField, tuple[UnreportedField, ...]] = {
    "call_gamma": ("call_gamma_unreported",),
    "put_gamma": ("put_gamma_unreported",),
    "net_gamma": ("call_gamma_unreported", "put_gamma_unreported"),
    "call_gex_1pct": ("call_gamma_unreported",),
    "put_gex_1pct": ("put_gamma_unreported",),
    "net_gex_1pct": ("call_gamma_unreported", "put_gamma_unreported"),
    "call_delta": ("call_delta_unreported",),
    "put_delta": ("put_delta_unreported",),
    "net_delta": ("call_delta_unreported", "put_delta_unreported"),
    "call_dex_dollars": ("call_delta_unreported",),
    "put_dex_dollars": ("put_delta_unreported",),
    "net_dex_dollars": ("call_delta_unreported", "put_delta_unreported"),
    "call_vanna": ("call_vanna_unreported",),
    "put_vanna": ("put_vanna_unreported",),
    "net_vanna": ("call_vanna_unreported", "put_vanna_unreported"),
    "call_oi_mult": ("call_oi_mult_unreported",),
    "put_oi_mult": ("put_oi_mult_unreported",),
    # sums no Greek prices: known or not by their own value (None)
    "call_oi": (),
    "put_oi": (),
    "call_volume": (),
    "put_volume": (),
}


def bucket_metric(bucket: Bucket, key: BucketField) -> float | None:
    """One exposure-bucket field, or None when it is not known.

    Not known: absent, not finite, or a Greek field on a leg where a contract's term is not known
    (see _GREEK_FIELD_UNREPORTED).
    """
    if key not in bucket:
        return None
    if any(bucket[u] for u in _GREEK_FIELD_UNREPORTED[key]):
        return None
    return float_finite_or_none(bucket[key])


def bucket_metric_abs(bucket: Bucket, key: BucketField) -> float | None:
    v = bucket_metric(bucket, key)
    return abs(v) if v is not None else None


# ── Data classes ──────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class ExposureDiagnostics:
    contracts_total: int
    contracts_used: int
    greeks_missing: int
    note: str


# ── Exposure primitives ──────────────────────────────────────────────────────


def _empty_bucket(dollarized: bool) -> Bucket:
    """Return a strike's bucket before its first contract (copied from _EMPTY_BUCKET).

    Its dollar fields and vanna need spot (`dollarized`): None, not known, without it.
    """
    with_spot = 0.0 if dollarized else None
    return {
        # Contracts at this strike whose openInterest was NOT REPORTED (absent, -999, text);
        # strike_total_oi() reads this so no total treats unknown as zero.
        "oi_unreported": 0,
        # Same discipline for totalVolume: an unreported one is UNKNOWN, never zero.
        "volume_unreported": 0,
        # Contracts on each leg whose gamma / delta / vanna term is not known: openInterest or
        # multiplier not reported, or open interest above 0 with no Greek (Schwab sent -999 or
        # none). That leg's sum of it is not known; a contract with open interest 0 adds 0.
        "call_gamma_unreported": 0,
        "call_delta_unreported": 0,
        "call_vanna_unreported": 0,
        "call_oi_mult_unreported": 0,
        "put_gamma_unreported": 0,
        "put_delta_unreported": 0,
        "put_vanna_unreported": 0,
        "put_oi_mult_unreported": 0,
        # True when the book was built WITH spot, i.e. the *_dollars / *_gex_1pct fields are
        # real dollar values. Set explicitly at build; never inferred from values.
        "dollarized": dollarized,
        # each leg's sums: 0.0 over no contract; None once a contract's value was not sent
        "call_oi": 0.0,
        "put_oi": 0.0,
        "call_oi_mult": 0.0,
        "put_oi_mult": 0.0,
        # NOTE: These are exposure-scaled buckets (gamma*OI*mult, delta*OI*mult)
        "call_gamma": 0.0,
        "put_gamma": 0.0,
        "call_vanna": with_spot,
        "put_vanna": with_spot,
        "call_delta": 0.0,
        "put_delta": 0.0,
        "net_gamma": 0.0,
        "net_delta": 0.0,
        # Dollarized (institutional) exposures when spot is provided
        "call_dex_dollars": with_spot,
        "put_dex_dollars": with_spot,
        "net_dex_dollars": 0.0,
        "call_gex_1pct": with_spot,
        "put_gex_1pct": with_spot,
        "net_gex_1pct": 0.0,
        # traded contracts per leg (Schwab totalVolume)
        "call_volume": 0.0,
        "put_volume": 0.0,
        # net vanna needs spot, as the other dollar fields (_finish_bucket)
        "net_vanna": with_spot,
    }


#: a strike's empty bucket, built with spot (True) and without (False)
_EMPTY_BUCKET = {d: _empty_bucket(d) for d in (True, False)}


def expiry_years(
    now: datetime, product: str, sessions: Mapping[str, Session]
) -> Callable[[str, str | None], float | None]:
    """Return time_et.time_to_expiry_years at `now` for `product`, once per expiry.

    The one valuation-T authority, computed once per (expiration, settlement) for every caller
    that prices a book at one valuation instant, on Schwab's /markets answers (`sessions`).
    """

    @functools.cache
    def years(expiration: str, settlement: str | None) -> float | None:
        return time_to_expiry_years(
            expiration, now=now, sessions=sessions, settlement_type=settlement, product=product
        )

    return years


def compute_exposures_by_strike(
    contracts: list[OptionContract],
    *,
    spot: float | None = None,
    now: datetime,
    sessions: Mapping[str, Session],
    product: str = "EQO",
) -> tuple[dict[float, Bucket], ExposureDiagnostics]:
    """Produce per-strike aggregates over every listed contract with a strike and a side.

    Call/put OI, delta exposure (delta * OI * multiplier) and gamma exposure (gamma * OI *
    multiplier); net delta and net gamma, call minus put (_finish_bucket): the dealer's position
    under the one assumption every net field makes (dealers long calls, short puts), a put keeping
    Schwab's signed delta, so a short put adds positive delta. The dollar fields (DEX$, GEX$ per
    1%) are computed when `spot` is provided.

    Every contract's terms are computed at once as arrays (numpy, IEEE double as Python's floats)
    and added to its strike's leg in the chain's order, as one contract at a time adds them. A
    value Schwab did not send is NaN in the arrays and never a number in the book: a sum it
    enters is None (open interest, volume), a term it leaves unknown adds nothing and is counted
    unreported.
    """
    # each contract with a strike and a side, with its strike
    rows = [(c, k) for c in contracts if (k := c.strike) is not None and c.side is not None]
    at = {k: i for i, k in enumerate(dict.fromkeys(k for _c, k in rows))}
    if not rows:
        return {}, _diagnostics(len(contracts), 0, 0)
    # each contract's slot: its strike's call leg (2i) or put leg (2i + 1)
    slot = np.array([2 * at[k] + (c.side != "CALL") for c, k in rows])
    # Schwab's values as read (option_contract), one row per contract; not sent: NaN
    oi, mult, volume, delta, gamma, iv, strike, rate, dividend = np.array(
        [
            (
                c.open_interest,
                c.multiplier,
                c.volume,
                c.delta,
                c.gamma,
                c.volatility,
                c.strike,
                c.interest_rate,
                c.dividend_yield,
            )
            for c, _k in rows
        ],
        float,
    ).T
    known = ~(np.isnan(oi) | np.isnan(mult))  # the contract's exposure terms can be known
    terms = {
        "oi_mult": oi * mult,
        "delta": delta * oi * mult,
        "gamma": gamma * oi * mult,
    }
    if spot is not None:
        spt = float(spot)
        # T from the ONE valuation-T authority (time_et.time_to_expiry_years, intraday ACT/365
        # to the session close) at the caller's one valuation instant `now`, per expiry
        tte = expiry_years(now, product, sessions)
        years = np.array(
            [
                np.nan if (t := tte(str(c.expiration), c.settlement)) is None else t
                for c, _k in rows
            ],
            float,
        )
        sigma = iv / 100.0  # schwab_iv_to_sigma: 0 or less is no sigma
        # the chain's own rate and dividend yield, percents as sent (calc.math_levels._profile_row)
        vanna = bs_vanna_array(spt, strike, years, sigma, rate / 100.0, dividend / 100.0)
        terms.update(
            dex_dollars=delta * oi * mult * spt,
            gex_1pct=gamma * oi * mult * spt * spt * 0.01,  # $-GEX per 1% spot move
            vanna=vanna * 0.01 * oi * mult,  # per 1 vol point
        )
    exposures = _strike_buckets(list(at), slot, known, terms, volume, oi, priced=spot is not None)
    missing = int((~known).sum() + (known & (np.isnan(delta) | np.isnan(gamma))).sum())
    return exposures, _diagnostics(len(contracts), int(known.sum()), missing)


def _strike_buckets(
    strikes: list[float],
    slot: NDArray[np.int64],
    known: NDArray[np.bool_],
    terms: dict[str, NDArray[np.float64]],
    volume: NDArray[np.float64],
    oi: NDArray[np.float64],
    *,
    priced: bool,
) -> dict[float, Bucket]:
    """Return each strike's bucket: its contracts' terms added to its call or put leg (`slot`).

    `known`: the contracts whose exposure terms can be known; `priced`: the dollar fields and
    vanna are among `terms` (priced with a spot).
    """
    counted = known & (oi > 0)  # with open interest above 0 an unknown term is unreported
    exposures = {k: _EMPTY_BUCKET[priced].copy() for k in strikes}
    slots = 2 * len(exposures)
    volume_sums = _sticky_sums(slot, volume, slots)
    oi_sums = _sticky_sums(slot, oi, slots)
    sums = {term: _known_sums(slot[known], value[known], slots) for term, value in terms.items()}
    unreported = {
        g: (
            np.bincount(slot[~known], minlength=slots)
            + (
                np.bincount(slot[counted & np.isnan(terms[g])], minlength=slots)
                if g in terms and g != "oi_mult"
                else 0
            )
        ).tolist()
        for g in ("oi_mult", "gamma", "delta", "vanna")
    }
    strike_of = slot // 2
    volume_unreported = np.bincount(strike_of[np.isnan(volume)], minlength=len(exposures)).tolist()
    oi_unreported = np.bincount(strike_of[np.isnan(oi)], minlength=len(exposures)).tolist()
    for i, b in enumerate(exposures.values()):
        c, p = 2 * i, 2 * i + 1  # the strike's call and put legs
        b["volume_unreported"], b["oi_unreported"] = volume_unreported[i], oi_unreported[i]
        b["call_oi_mult_unreported"] = unreported["oi_mult"][c]
        b["put_oi_mult_unreported"] = unreported["oi_mult"][p]
        b["call_gamma_unreported"] = unreported["gamma"][c]
        b["put_gamma_unreported"] = unreported["gamma"][p]
        b["call_delta_unreported"] = unreported["delta"][c]
        b["put_delta_unreported"] = unreported["delta"][p]
        b["call_vanna_unreported"] = unreported["vanna"][c]
        b["put_vanna_unreported"] = unreported["vanna"][p]
        b["call_volume"], b["put_volume"] = volume_sums[c], volume_sums[p]
        b["call_oi"], b["put_oi"] = oi_sums[c], oi_sums[p]
        b["call_oi_mult"], b["put_oi_mult"] = sums["oi_mult"][c], sums["oi_mult"][p]
        b["call_delta"], b["put_delta"] = sums["delta"][c], sums["delta"][p]
        b["call_gamma"], b["put_gamma"] = sums["gamma"][c], sums["gamma"][p]
        if priced:  # the dollar fields and vanna, priced with spot
            b["call_dex_dollars"] = sums["dex_dollars"][c]
            b["put_dex_dollars"] = sums["dex_dollars"][p]
            b["call_gex_1pct"], b["put_gex_1pct"] = sums["gex_1pct"][c], sums["gex_1pct"][p]
            b["call_vanna"], b["put_vanna"] = sums["vanna"][c], sums["vanna"][p]
        _finish_bucket(b)
    return exposures


def _known_sums(slot: NDArray[np.int64], values: NDArray[np.float64], slots: int) -> list[float]:
    """Each slot's sum of `values`, added in order from 0.0 as one contract at a time adds it.

    A term not known (NaN) adds nothing (the leg counts it unreported).
    """
    sent = ~np.isnan(values)
    # bincount adds each slot's values one at a time, in the order given
    return np.bincount(slot[sent], weights=values[sent], minlength=slots).tolist()


def _sticky_sums(
    slot: NDArray[np.int64], values: NDArray[np.float64], slots: int
) -> list[float | None]:
    """Each slot's sum of `values` (_known_sums); a value not sent (NaN) leaves it not known."""
    out: list[float | None] = list(_known_sums(slot, values, slots))
    for s in np.unique(slot[np.isnan(values)]).tolist():
        out[s] = None
    return out


def _finish_bucket(b: Bucket) -> None:
    """Compute a strike bucket's net fields from its call and put legs, +call/-put.

    Dealer-signed (the same convention as net GEX and the terrain's dex_dollars -- one meaning of
    each on every screen): the one place they are computed, for a book and for a merge of books.
    A dollar field or vanna needs spot (`dollarized`): none without it.
    """
    b["net_gamma"] = b["call_gamma"] - b["put_gamma"]
    b["net_delta"] = b["call_delta"] - b["put_delta"]
    b["net_dex_dollars"] = _net(b["call_dex_dollars"], b["put_dex_dollars"], b["dollarized"])
    b["net_gex_1pct"] = _net(b["call_gex_1pct"], b["put_gex_1pct"], b["dollarized"])
    b["net_vanna"] = _net(b["call_vanna"], b["put_vanna"], b["dollarized"])


def _net(call: float | None, put: float | None, dollarized: bool) -> float | None:
    """Return a dollar field's or vanna's net, +call/-put; None without spot (not dollarized).

    Dollarized, each leg is a number (a term not known adds nothing).
    """
    return call - put if dollarized and call is not None and put is not None else None


def _diagnostics(total: int, used: int, missing: int) -> ExposureDiagnostics:
    note = "OK"
    if used == 0:
        note = "No usable contracts (OI filtered or chain empty)."
    elif missing == used:
        note = (
            "All greeks missing (Schwab sent -999, or no quote came back). You will still get "
            "OI center; gamma/delta pin/inf may be N/A until RTH."
        )
    return ExposureDiagnostics(
        contracts_total=total, contracts_used=used, greeks_missing=missing, note=note
    )


def exposure_books(
    contracts: list[OptionContract],
    *,
    spot: float | None,
    now: datetime,
    sessions: Mapping[str, Session],
    product: str = "EQO",
) -> dict[tuple[str | None, float | None], tuple[dict[float, Bucket], ExposureDiagnostics]]:
    """Run compute_exposures_by_strike once per (expiry, days to expiry) group.

    Every contract is
    priced once; any subset of expiries is then a merge_exposure_books of its groups (the full
    book, 0DTE, the front expiry, each listed expiry).
    """
    groups: dict[tuple[str | None, float | None], list[OptionContract]] = {}
    for c in contracts:
        groups.setdefault((c.expiry, c.days_to_expiry), []).append(c)
    return {
        k: compute_exposures_by_strike(cs, spot=spot, now=now, sessions=sessions, product=product)
        for k, cs in groups.items()
    }


def merge_exposure_books(
    books: Iterable[tuple[dict[float, Bucket], ExposureDiagnostics]],
) -> tuple[dict[float, Bucket], ExposureDiagnostics]:
    """Merge books over DISJOINT contracts into one book.

    Every leg field a sum of the books' legs (a
    sum not known in one book is not known in the merge), each flag an OR, and each net field
    computed from the merged legs by the book's own rule (_finish_bucket). The legs are the same
    sums one compute_exposures_by_strike call over all the contracts gives, up to float addition
    order.
    """
    merged: dict[float, Bucket] = {}
    total = used = missing = 0
    for exposures, diag in books:
        total += diag.contracts_total
        used += diag.contracts_used
        missing += diag.greeks_missing
        for strike, bucket in exposures.items():
            cur = merged.get(strike)
            if cur is None:
                merged[strike] = bucket.copy()
                continue
            cur["dollarized"] = cur["dollarized"] or bucket["dollarized"]
            for k in _BUCKET_COUNTS:
                cur[k] += bucket[k]
            for k in _BUCKET_KNOWN_SUMS:
                cur[k] += bucket[k]
            for k in _BUCKET_SUMS:
                v, now = bucket[k], cur[k]
                cur[k] = None if v is None or now is None else now + v
    for b in merged.values():
        _finish_bucket(b)
    return merged, _diagnostics(total, used, missing)


#: The per-strike bucket fields summed when books merge (the flag is OR-ed; the net fields
#: _finish_bucket computes from the legs): the counts, the sums always known, and the sums a
#: value not reported leaves not known in either book (None)
type _CountField = Literal["oi_unreported", "volume_unreported"] | UnreportedField
type _KnownSumField = Literal[
    "call_oi_mult", "put_oi_mult", "call_gamma", "put_gamma", "call_delta", "put_delta"
]
type _SumField = Literal[
    "call_oi",
    "put_oi",
    "call_vanna",
    "put_vanna",
    "call_dex_dollars",
    "put_dex_dollars",
    "call_gex_1pct",
    "put_gex_1pct",
    "call_volume",
    "put_volume",
]
_BUCKET_COUNTS: tuple[_CountField, ...] = (
    "oi_unreported",
    "volume_unreported",
    *get_args(UnreportedField.__value__),
)
_BUCKET_KNOWN_SUMS: tuple[_KnownSumField, ...] = get_args(_KnownSumField.__value__)
_BUCKET_SUMS: tuple[_SumField, ...] = get_args(_SumField.__value__)


def overlay_streamed_contract_fields(
    contracts: list[OptionContract],
    streamed_by_symbol: dict[str, Streamed],
    held: set[str],
    quoted: dict[str, tuple[float, dict[str, Any]]],
) -> tuple[list[OptionContract], int]:
    """Give each contract its newest values: the stream's when it is held, else /quotes'.

    A contract Schwab does not stream (not in `held`) takes the values of its newest /quotes
    answer received since its chain began (`quoted`: symbol -> (receive time, values),
    app.options.order_flow.state.rest_quotes), the moment that answer arrives; with no such
    answer it keeps the chain's.

    A contract Schwab streams takes its newest streamed record (`streamed_by_symbol`); the pushed
    field is its one producer (AGENTS.md rule 3). Its volume, bid, ask and money intrinsic value
    are the stream's (`total_volume`, `bid`, `ask`, `money_intrinsic`), each None until the
    stream sends it. Its Greeks and
    volatility are the stream's newest once the stream holds all six (the set the chain sweep
    takes, option_contract.streamed_greek_set); until then they are the chain's, which the sweep
    asked /quotes for because the stream had not sent them. Open interest is the chain's for
    every contract (the stream does not send it for every contract it streams).

    Pure: a contract given values is a new record, every other the same one. Returns
    (new_contracts, streamed_count).
    """
    out: list[OptionContract] = []
    for c in contracts:
        if c.symbol not in held:
            out.append(replace(c, **quoted[c.symbol][1]) if c.symbol in quoted else c)
        elif c.symbol in streamed_by_symbol:
            sent = streamed_by_symbol[c.symbol]
            pushed = streamed_quote(sent)
            greeks = streamed_greek_set(sent.greeks.values())
            if greeks is not None:
                pushed.update(greeks)
            out.append(replace(c, **pushed))
        else:
            out.append(replace(c, volume=None, bid=None, ask=None, money_intrinsic=None))
    return out, sum(1 for c in contracts if c.symbol in held)


def strike_total_oi(bucket: Bucket) -> float | None:
    """Return THE total open interest at one strike, or None when it is not known.

    Known = every contract at the strike reported openInterest (oi_unreported == 0). A leg
    with no positive-OI contract then contributes a real 0 (its contracts reported 0 OI, or
    none is listed).
    """
    legs = strike_oi_legs(bucket)
    if legs is None:
        return None
    call_oi, put_oi = legs
    return call_oi + put_oi


def strike_oi_legs(bucket: Bucket) -> tuple[float, float] | None:
    """(call OI, put OI) at one strike when its OI is known (see strike_total_oi), else None.

    A leg with no contract listed is a known 0.0, the sum of none.
    """
    call, put = bucket["call_oi"], bucket["put_oi"]
    if bucket["oi_unreported"] != 0 or call is None or put is None:
        return None
    return call, put


def strike_volume_legs(bucket: Bucket) -> tuple[float, float] | None:
    """(call, put) session volume at one strike when every contract there reported totalVolume.

    0 is a real zero; else None. A leg with no listed contract is a known 0.0. THE one reader:
    GEX-by-Strike rows, heatmap cells and the put/call volume ratio.
    """
    call, put = bucket["call_volume"], bucket["put_volume"]
    if bucket["volume_unreported"] != 0 or call is None or put is None:
        return None
    return call, put


def strike_total_volume(bucket: Bucket) -> float | None:
    """Return THE total session volume at one strike.

    None when a contract there did not report it.
    """
    legs = strike_volume_legs(bucket)
    if legs is None:
        return None
    call_volume, put_volume = legs
    return call_volume + put_volume


def book_total_oi(exposures: dict[float, Bucket]) -> float | None:
    """Total OI of the whole book, or None if ANY strike's OI is unknown."""
    if not exposures:
        return None
    total = 0.0
    for b in exposures.values():
        t = strike_total_oi(b)
        if t is None:
            return None
        total += t
    return total


def _put_call_ratio(legs: Iterable[tuple[float, float] | None]) -> float | None:
    """Total put / total call over the book's strikes.

    None if any strike's legs are unknown or the calls total 0 (an empty book included).
    """
    calls = puts = 0.0
    for leg in legs:
        if leg is None:
            return None
        calls += leg[0]
        puts += leg[1]
    return puts / calls if calls > 0 else None


def put_call_oi_ratio(buckets: Iterable[Bucket]) -> float | None:
    """Total put OI / total call OI of the strike buckets -- the positions held.

    None if any strike's OI is unknown or call OI is 0.
    """
    return _put_call_ratio(strike_oi_legs(b) for b in buckets)


def put_call_volume_ratio(buckets: Iterable[Bucket]) -> float | None:
    """Total put volume / total call volume of the strike buckets -- today's trading.

    Cboe's convention (https://cdn.cboe.com/resources/us/options/market_statistics/daily/cone/archive/html/2002-05-17.html).
    None when any contract in the book did not report its volume, or no call traded. A strike with
    no call (or put) contract listed has no volume on that side, not a zero.
    """
    return _put_call_ratio(strike_volume_legs(b) for b in buckets)


def exposures_have_dollar_gex(exposures: dict[float, Bucket]) -> bool:
    """Return True when the book was built WITH spot (its dollar fields are real).

    Read from the
    explicit `dollarized` flag, never inferred from the dollar GEX values, so a spot-built book
    whose gammas are all invalid still reads as dollarized.
    """
    for b in exposures.values():
        if "dollarized" in b:
            return b["dollarized"]
    return False


def key_level_strikes_with_oi(exposures: dict[float, Bucket]) -> list[float]:
    """Strikes whose OI is KNOWN and positive (strike_total_oi -- the one reader)."""
    out: list[float] = []
    for s, bucket in sorted(exposures.items()):
        tot = strike_total_oi(bucket)
        if tot is not None and tot > 0:
            out.append(s)
    return out


def total_gex_dollars_at_strike(bucket: Bucket) -> float | None:
    """Peak gamma concentration: |call GEX$| + |put GEX$| per 1% move."""
    c = bucket_metric_abs(bucket, "call_gex_1pct")
    p = bucket_metric_abs(bucket, "put_gex_1pct")
    return None if c is None or p is None else c + p


def net_gex_dollars_at_strike(bucket: Bucket) -> float | None:
    return bucket_metric(bucket, "net_gex_1pct")


def strike_of_largest[B](
    exposures: Mapping[float, B],
    metric_fn: Callable[[B], float | None],
) -> tuple[float | None, float | None]:
    """Return (strike, value) where `metric_fn` of a strike's bucket is largest and above 0.

    Every level that is a largest-at-a-strike is picked here. Two strikes with the same value:
    the lower strike.
    """
    best_s: float | None = None
    best_v: float | None = None
    for s in sorted(exposures):
        v = metric_fn(exposures[s])
        if v is None or v <= 0:
            continue
        if best_v is None or v > best_v:
            best_s = float(s)
            best_v = float(v)
    return best_s, best_v


def pick_absolute_gamma_strike(exposures: dict[float, Bucket]) -> float | None:
    """Max TOTAL gamma — a GROSS GAMMA CONCENTRATION.

    NOT a demonstrated magnet.

    WHAT IT MEASURES. The strike carrying the largest absolute call GEX dollars plus
    absolute put GEX dollars — i.e. where the most dealer re-hedging activity sits. This is
    the quantity SpotGamma publishes as Absolute Gamma.

    WHAT IT DOES NOT ESTABLISH: that hedging MAGNITUDE pins price regardless of net sign, so
    calls-plus-puts is the magnet measure. That does not follow. Magnitude sets the SIZE of
    the hedging flow at a strike; the SIGN of the dealer position sets whether that flow is
    stabilising or destabilising — a dealer long gamma sells rallies and buys dips, a dealer
    short gamma does the opposite — and this metric discards the sign. Two strikes with equal
    absolute gamma can behave oppositely. The sign is also not observable: public open
    interest does not reveal contract ownership
    (https://spotgamma.com/what-is-gex-gamma-exposure/), so dealer direction is MODELLED.
    Expiration-date clustering in the literature turns on NET positioning — Ni, Pearson and
    Poteshman, Journal of Financial Economics, doi:10.1016/j.jfineco.2004.08.005.

    It is not the pin, which is read on open interest (calc.terrain_engine.pin_by_open_interest).

    The NET book (calls minus puts) is a different question — where the signed book leans —
    and lives under its own names, the net call and net put gamma peaks
    (pick_volatility_point_strikes below).

    Fail-closed: no dollarized GEX -> None, never a raw-gamma fallback.
    """
    if not exposures_have_dollar_gex(exposures):
        return None
    s, v = strike_of_largest(exposures, total_gex_dollars_at_strike)
    if s is None or v is None or v <= 0:
        return None
    return s


def pick_key_delta_strike(exposures: dict[float, Bucket]) -> float | None:
    """Key Delta Strike: largest total delta notional (|call DEX$| + |put DEX$|).

    Institutional only — no raw-delta fallback: delta notional needs spot, and a
    unit mix here would rank strikes on incomparable numbers.
    """
    if not exposures_have_dollar_gex(exposures):
        return None

    def _total_dex(b: Bucket) -> float | None:
        c = bucket_metric_abs(b, "call_dex_dollars")
        p = bucket_metric_abs(b, "put_dex_dollars")
        return None if c is None or p is None else c + p

    s, _ = strike_of_largest(exposures, _total_dex)
    return s


def pick_volatility_point_strikes(
    exposures: dict[float, Bucket],
) -> tuple[float | None, float | None]:
    """(net put gamma peak, net call gamma peak): the most NEGATIVE / most POSITIVE net GEX$.

    Signed extremes, not magnitudes: the put peak exists only where net gamma is
    actually negative at some strike, the call peak only where it is positive.
    A one-sided chain returns None for the absent side.
    """
    if not exposures_have_dollar_gex(exposures):
        return None, None
    hvp_s: float | None = None
    hvp_v: float | None = None
    lvp_s: float | None = None
    lvp_v: float | None = None
    for s in sorted(exposures):
        v = net_gex_dollars_at_strike(exposures[s])
        if v is None:
            continue
        if v < 0 and (hvp_v is None or v < hvp_v):
            hvp_s, hvp_v = float(s), float(v)
        if v > 0 and (lvp_v is None or v > lvp_v):
            lvp_s, lvp_v = float(s), float(v)
    return hvp_s, lvp_s


def pick_gamma_wall_strikes(
    exposures: dict[float, Bucket],
) -> tuple[tuple[float | None, float | None], tuple[float | None, float | None]]:
    """Call/put gamma walls: max |side GEX$|; none without a dollarized book (no spot)."""
    if not exposures_have_dollar_gex(exposures):
        return (None, None), (None, None)
    return (
        strike_of_largest(exposures, lambda b: bucket_metric_abs(b, "call_gex_1pct")),
        strike_of_largest(exposures, lambda b: bucket_metric_abs(b, "put_gex_1pct")),
    )


def pick_delta_wall_strikes(
    exposures: dict[float, Bucket],
) -> tuple[tuple[float | None, float | None], tuple[float | None, float | None]]:
    """Call/put delta walls: max |side DEX$|; none without a dollarized book (no spot)."""
    if not exposures_have_dollar_gex(exposures):
        return (None, None), (None, None)
    return (
        strike_of_largest(exposures, lambda b: bucket_metric_abs(b, "call_dex_dollars")),
        strike_of_largest(exposures, lambda b: bucket_metric_abs(b, "put_dex_dollars")),
    )
