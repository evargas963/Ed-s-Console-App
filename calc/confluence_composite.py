"""The Confluence matrix of one expiry: each strike's readings, its Composite and the heat scales.

Every reading is its producer's, already computed for that expiry: the exposure book
(calc.math_exposure_core), the charm map (calc.math_levels), the volatility blend (iv_by_strike),
the expiry's gamma profile (calc.math_levels.compute_gamma_profile), the prior day's book of the
same expiry and the look-back's readings (calc.option_window). This module reads them per strike,
once, and computes only the Composite (docs/derived_register.md "Composite").
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any, TypedDict

from calc.math_exposure_core import (
    Bucket,
    bucket_metric,
    strike_oi_legs,
    strike_volume_legs,
)
from calc.math_levels import CharmBucket
from numeric_contract import (
    compact_text,
    count_text,
    dollars_text,
    iv_text,
    price_text,
    schwab_number,
)
from option_contract import OptionContract

#: the families of input that vote in the Composite, one equal vote each (decision 56)
FAMILIES = ("positioning", "option trades", "volatility", "stock book")
#: the one assumption every gamma reading rests on, said once beside it
ASSUMPTION = "the convention: dealers long calls, short puts"


@dataclass(frozen=True)
class StrikeReadings:
    """One strike's readings of one expiry, each as its producer computed it; None: not known.

    The open interest and volume with their (call, put) legs; the change in open interest since
    the prior day's capture (`oi_new`: the prior day listed no contract at this strike); the
    expiry's gamma profile at this strike's price (`gamma_here`); the regular session's touches
    and holds at the strike so far (calc.liquidity_value_engine.visits; None before it opens).
    """

    net_gex: float | None
    oi: float | None
    oi_legs: tuple[float, float] | None
    oi_change: float | None
    oi_change_legs: tuple[float, float] | None
    oi_new: bool
    dex: float | None
    charm: float | None
    vanna: float | None
    iv: float | None
    volume: float | None
    volume_legs: tuple[float, float] | None
    vol_oi: float | None
    pc_vol: float | None
    gamma_here: float | None
    touches: int | None
    holds: int | None


def _sum(legs: tuple[float, float] | None) -> float | None:
    return None if legs is None else legs[0] + legs[1]


def _oi_change(
    legs: tuple[float, float] | None, prior: Bucket | None
) -> tuple[float, float] | None:
    """Return today's (call, put) open interest less the prior day's at one strike.

    None when either day's open interest there is not known (a count not reported), or the prior
    day holds no contract at the strike (`prior` None).
    """
    before = None if prior is None else strike_oi_legs(prior)
    if legs is None or before is None:
        return None
    return legs[0] - before[0], legs[1] - before[1]


def readings(
    bucket: Bucket,
    charm: CharmBucket | None,
    iv: float | None,
    spot: float,
    gamma_here: float | None,
    prior: Bucket | None,
    prior_held: bool,
    visit: tuple[int, int] | None,
) -> StrikeReadings:
    """Return one strike's readings from its producers' values.

    Each leg's gamma is Schwab's as sent, whatever its sign (AGENTS rule 2). `prior` is the
    prior day's bucket of this strike (None: that day listed no contract here, or no prior day is
    held, `prior_held` False); `visit` its (touches, holds) today (None: the session not open).
    """
    oi_legs = strike_oi_legs(bucket)
    volume_legs = strike_volume_legs(bucket)
    oi, volume = _sum(oi_legs), _sum(volume_legs)
    vanna = bucket_metric(bucket, "net_vanna")
    change = _oi_change(oi_legs, prior)
    return StrikeReadings(
        net_gex=bucket_metric(bucket, "net_gex_1pct"),
        oi=oi,
        oi_legs=oi_legs,
        oi_change=_sum(change),
        oi_change_legs=change,
        oi_new=prior_held and prior is None,
        dex=bucket_metric(bucket, "net_dex_dollars"),
        charm=None if charm is None else schwab_number(charm["net_charm"]),
        vanna=None if vanna is None else vanna * spot,
        iv=iv,
        volume=volume,
        volume_legs=volume_legs,
        vol_oi=None if oi is None or oi == 0 or volume is None else volume / oi,
        pc_vol=(
            None if volume_legs is None or volume_legs[0] == 0 else volume_legs[1] / volume_legs[0]
        ),
        gamma_here=gamma_here,
        touches=None if visit is None else visit[0],
        holds=None if visit is None else visit[1],
    )


def iv_by_strike(contracts: list[OptionContract]) -> dict[float, float | None]:
    """(open interest + volume)-weighted Schwab volatility, in vol points."""
    grouped: dict[float, list[OptionContract]] = {}
    for c in contracts:
        if c.strike is not None:
            grouped.setdefault(float(c.strike), []).append(c)
    out: dict[float, float | None] = {}
    for strike, rows in grouped.items():
        weighted = 0.0
        weight = 0.0
        plain: list[float] = []
        for c in rows:
            iv = c.volatility
            if iv is None:
                continue
            plain.append(iv)
            oi, vol = c.open_interest, c.volume
            if oi is None or vol is None:
                continue
            w = float(oi) + float(vol)
            weighted += w * iv
            weight += w
        if plain and weight == 0:
            out[strike] = sum(plain) / len(plain)
        elif weight > 0:
            out[strike] = weighted / weight
        else:
            out[strike] = None
    return out


@dataclass(frozen=True)
class Composite:
    """A strike's Composite: its condition and strength (composite).

    `gamma`: the expiry's gamma profile at the strike, whose sign is the condition; `strength`:
    0 to 100, the mean of the families measured there; `measured`: those families' names.
    """

    gamma: float
    strength: float
    measured: tuple[str, ...]


def composite(gamma: float | None, strengths: Mapping[str, float | None]) -> Composite | None:
    """Return a strike's Composite: the condition and the families' equal vote on its strength.

    The condition is the sign of the expiry's gamma profile at the strike (negative: the hedging
    accelerates moves; positive: it dampens them; on the convention, ASSUMPTION). The strength is
    100 times the mean of each family's strength measured at the strike (its value against its
    column's peak on the expiry, 0 to 1); a family not measured there is left out, never counted
    as a vote (decision 56: one equal vote a family, no fitted weights; Dawes 1979). None when
    the gamma there or every family is not known.
    """
    measured = tuple(f for f in FAMILIES if strengths.get(f) is not None)
    if gamma is None or not measured:
        return None
    total = 0.0
    for family in measured:
        value = strengths[family]
        total += 0.0 if value is None else value
    return Composite(gamma, 100.0 * total / len(measured), measured)


def _share(value: float | None, peak: float | None) -> float | None:
    """`value`'s size against its column's peak, 0 to 1; None when either is not known."""
    if value is None or not peak:
        return None
    return min(1.0, abs(value) / peak)


@dataclass(frozen=True)
class Matrix:
    """The readings of one expiry's book (build_matrix).

    Every strike's readings and Composite, each shaded column's peak, and the listed strikes,
    ascending.
    """

    readings: dict[float, StrikeReadings]
    composites: dict[float, Composite | None]
    peaks: dict[str, float | None]
    strikes: list[float]


def _peak(values: Iterable[float | None]) -> float | None:
    """Largest absolute value on this expiry: the column's scale."""
    peak = None
    for value in values:
        if not isinstance(value, (int, float)):
            continue
        size = abs(float(value))
        if peak is None or size > peak:
            peak = size
    return peak


#: each shaded column: the row's key for its number and the reading it carries
SHADED = {
    "gamma_here": "gamma_here",
    "net_gex": "net_gex",
    "oi": "oi",
    "oi_change": "oi_change",
    "dex": "dex",
    "charm": "charm",
    "vanna": "vanna",
    "iv": "iv",
    "volume": "volume",
    "vol_oi": "vol_oi",
    "visits": "touches",
}


def _shades(r: StrikeReadings) -> dict[str, float | None]:
    """Return the numbers the page shades each column's cell by, against the column's peak.

    The put/call volume shades by 1 - put/call: positive call-heavy, negative put-heavy.
    """
    out: dict[str, float | None] = {key: getattr(r, name) for key, name in SHADED.items()}
    out["pc_vol_lean"] = None if r.pc_vol is None else 1 - r.pc_vol
    return out


def build_matrix(
    exposures: dict[float, Bucket],
    charm_by_strike: dict[float, CharmBucket],
    ivs: dict[float, float | None],
    spot: float,
    gamma_profile: Mapping[float, float],
    prior: dict[float, Bucket] | None,
    visits: Mapping[float, tuple[int, int]],
) -> Matrix:
    """Build the readings of one expiry's book and each strike's Composite.

    `gamma_profile`: the expiry's gamma profile by price (its value at each listed strike);
    `prior`: the prior day's book of the same expiry (None: no prior day held); `visits`: each
    strike's (touches, holds) in today's regular session (empty before it opens). The rows the
    page shows are drawn from it (window_rows).
    """
    strikes = sorted(float(s) for s in exposures)
    by_strike = {
        s: readings(
            exposures[s],
            charm_by_strike.get(s),
            ivs.get(s),
            spot,
            gamma_profile.get(s),
            None if prior is None else prior.get(s),
            prior is not None,
            visits.get(s),
        )
        for s in strikes
    }
    shades = [_shades(r) for r in by_strike.values()]
    peaks = {key: _peak(s[key] for s in shades) for key in (*SHADED, "pc_vol_lean")}
    composites = {
        s: composite(r.gamma_here, {"positioning": _share(r.net_gex, peaks["net_gex"])})
        for s, r in by_strike.items()
    }
    return Matrix(readings=by_strike, composites=composites, peaks=peaks, strikes=strikes)


def window_rows(matrix: Matrix, shown: list[float]) -> list[dict[str, Any]]:
    """Return the rows of the strikes `shown`, highest strike first.

    Each cell shades against its whole expiry's peak (the matrix's `peaks`).
    """
    return [
        _row(strike, matrix.readings[strike], matrix.composites[strike])
        for strike in sorted(shown, reverse=True)
    ]


def under_strike(price: float, strikes: list[float]) -> float | None:
    """Return the lowest listed strike at or above `price`, where a marker sits."""
    at_or_above = [s for s in strikes if s >= price]
    if not at_or_above:
        return None
    return min(at_or_above)


def _text(n: float | None, digits: int) -> str | None:
    if n is None:
        return None
    return f"{n:.{digits}f}"


def implied_move(atm_iv_pct: float | None, years: float | None) -> float | None:
    """Return an expiry's one implied move as a share of the price: σ_ATM × √(time left).

    `atm_iv_pct` is the expiry's at-the-money volatility, a percent; `years` its time left. None
    when either is not known.
    """
    return None if atm_iv_pct is None or years is None else atm_iv_pct / 100.0 * math.sqrt(years)


class Distance(TypedDict):
    """A price's distance from the live price: in dollars, and in the expiry's implied moves."""

    distance_text: str | None
    sigma: float | None
    sigma_text: str | None


def distance(price: float, spot: float | None, sigma_root_t: float | None) -> Distance:
    """Return `price`'s distance from the live price `spot`, in dollars and in implied moves.

    In dollars: the price less `spot`, signed. In implied moves (σ): ln(price / spot) over the
    expiry's at-the-money volatility times the square root of its time left (`sigma_root_t`),
    the distance options desks quote because it compares across tickers and expiries (the
    normalised strike, z = ln(K / F) / (σ √T); `Trading/matrix_research_key_levels_2026_11_23.md`).
    It is measured from the live price, the base of the dollar distance beside it, not the
    forward: the two differ by the interest to the expiry, under 0.1 σ for SPY within two months.
    Unknown without a price, or with no volatility or no time left.
    """
    sigma = None if spot is None or not sigma_root_t else math.log(price / spot) / sigma_root_t
    return {
        "distance_text": None if spot is None else _signed(price - spot, 2),
        "sigma": sigma,
        "sigma_text": None if sigma is None else f"{_signed(sigma, 1)}σ",
    }


def at_price(
    rows: list[dict[str, Any]],
    strikes: list[float],
    spot: float | None,
    sigma_root_t: float | None,
) -> dict[str, Any]:
    """Return the shown rows, each with its distance from the live price and its spot line.

    The spot line marks the strike the price sits under; the price row is drawn below it, and
    `price_between_text` names the two listed strikes the price falls between (one, when it is
    on a strike). The matrix is read at the book's price, the price on screen is the live one;
    each row's distance is `distance`'s, in dollars and in the expiry's implied moves
    (`sigma_root_t`). Pure: the rows given are not changed.
    """
    under = None if spot is None else under_strike(spot, strikes)
    below = None if spot is None else max((s for s in strikes if s <= spot), default=None)
    if under is None or below is None:
        between = None
    elif under == below:
        between = f"at {price_text(under)}"
    else:
        between = f"between {price_text(under)} and {price_text(below)}"
    return {
        "rows": [
            {
                **row,
                **distance(row["strike"], spot, sigma_root_t),
                "spot_line": row["strike"] == under,
            }
            for row in rows
        ],
        "spot": spot,
        "spot_text": price_text(spot),
        "price_between_text": between,
    }


def _signed(n: float | None, digits: int) -> str | None:
    """Format a number signed: a positive one keeps its plus. Zero and a rounded zero do not."""
    if n is None:
        return None
    shown = f"{float(n):.{digits}f}"
    if shown.startswith("-"):
        if float(shown) == 0:
            return shown[1:]
        return shown
    if float(shown) == 0:
        return shown
    return "+" + shown


def _signed_count(n: float | None) -> str | None:
    """A change in a count as the screen shows it: whole, signed, a rise with its plus."""
    text = count_text(n)
    if n is None or text is None:
        return None
    return "+" + text if n > 0 else text


def _absent(value: float | None, words: str) -> str | None:
    if isinstance(value, (int, float)):
        return None
    return words


def _legs_text(legs: tuple[float, float] | None, read: str) -> str | None:
    """A sum's parts on hover: the calls' and the puts' count."""
    if legs is None:
        return None
    return f"{read}: calls {count_text(legs[0])} · puts {count_text(legs[1])}"


#: the gamma profile's sign in the industry's words (decisions 29 and 53, AGENTS rule 17)
GAMMA_WORDS = {-1: "Negative gamma", 0: "Zero gamma", 1: "Positive gamma"}
#: the same, short, in the Composite cell
GAMMA_SHORT = {-1: "Neg. gamma", 0: "Zero gamma", 1: "Pos. gamma"}
#: what the hedging does to a move at that sign, on hover
GAMMA_EFFECT = {
    -1: "the hedging accelerates moves",
    0: "the hedging neither accelerates nor dampens moves",
    1: "the hedging dampens moves",
}
OI_CHANGE_REASON = "no prior day's chain is held"
NEW_TEXT = "new"


def _sign(value: float) -> int:
    return (value > 0) - (value < 0)


def _composite_cells(c: Composite | None) -> dict[str, Any]:
    if c is None:
        return {
            "composite": None,
            "composite_text": None,
            "composite_reason": "the gamma at this strike or every family is not known",
            "composite_hover": None,
        }
    sign = _sign(c.gamma)
    return {
        # shaded by the strength, red where the gamma is negative, against a peak of 1
        "composite": sign * c.strength / 100.0,
        "composite_text": f"{GAMMA_SHORT[sign]} {c.strength:.0f}",
        "composite_reason": None,
        "composite_hover": (
            f"{GAMMA_WORDS[sign]} here ({ASSUMPTION}): {GAMMA_EFFECT[sign]}. Strength "
            f"{c.strength:.0f} of 100: the equal vote of {len(c.measured)} of {len(FAMILIES)} "
            f"families measured here ({', '.join(c.measured)}), each its size against the "
            "expiry's largest. A size and a kind of move, not a direction; untested."
        ),
    }


def _gamma_cells(gamma: float | None) -> dict[str, Any]:
    if gamma is None:
        return {
            "gamma_here_text": None,
            "gamma_here_reason": "no priced contract gives the gamma at this price",
            "gamma_here_hover": None,
        }
    sign = _sign(gamma)
    return {
        "gamma_here_text": GAMMA_WORDS[sign],
        "gamma_here_reason": None,
        "gamma_here_hover": (
            f"Model: the expiry's net gamma if the price were at this strike, "
            f"{dollars_text(gamma)} per 1% move; {GAMMA_EFFECT[sign]} ({ASSUMPTION})."
        ),
    }


def _row(strike: float, r: StrikeReadings, c: Composite | None) -> dict[str, Any]:
    """One strike's row of the matrix.

    Each column's text and the number its cell shades by (_shades), against the expiry's peaks;
    where a cell sums parts, its parts on hover.
    """
    return {
        "strike": strike,
        "strike_text": price_text(strike),
        **_shades(r),
        **_composite_cells(c),
        **_gamma_cells(r.gamma_here),
        "net_gex_text": dollars_text(r.net_gex),
        "net_reason": _absent(r.net_gex, "net gamma is missing"),
        "oi_text": count_text(r.oi),
        "oi_reason": _absent(r.oi, "open interest is missing"),
        "oi_hover": _legs_text(r.oi_legs, "Open interest"),
        "oi_change_text": NEW_TEXT if r.oi_new else _signed_count(r.oi_change),
        "oi_change_reason": None if r.oi_new else _absent(r.oi_change, OI_CHANGE_REASON),
        "oi_change_hover": _legs_text(r.oi_change_legs, "Change since the prior day"),
        "dex_text": dollars_text(r.dex),
        "dex_reason": _absent(r.dex, "delta exposure is missing"),
        "charm_text": compact_text(r.charm),
        "charm_reason": _absent(r.charm, "charm is missing"),
        "vanna_text": dollars_text(r.vanna),
        "vanna_reason": _absent(r.vanna, "vanna is missing"),
        "iv_text": iv_text(r.iv),
        "iv_reason": _absent(r.iv, "implied volatility is missing"),
        "volume_text": count_text(r.volume),
        "volume_reason": _absent(r.volume, "volume is missing"),
        "volume_hover": _legs_text(r.volume_legs, "Today's volume"),
        "pc_vol_text": _text(r.pc_vol, 2),
        "pc_vol_reason": _absent(r.pc_vol, "put/call volume is missing"),
        "vol_oi_text": _text(r.vol_oi, 2),
        "vol_oi_reason": _absent(r.vol_oi, "volume/open interest is missing"),
        **_visits_cells(r.touches, r.holds),
    }


VISITS_REASON = "the regular session has not opened"


def _visits_cells(touches: int | None, holds: int | None) -> dict[str, Any]:
    """Today's hits and bounces at the strike: "b of h", "none yet" with no hit."""
    if touches is None or holds is None:
        return {"visits_text": None, "visits_reason": VISITS_REASON, "visits_hover": None}
    return {
        "visits_text": "none yet" if touches == 0 else f"{holds} of {touches}",
        "visits_reason": None,
        "visits_hover": (
            f"Today: {touches} hits, {holds} bounced. A hit is a 1-minute bar reaching the "
            "strike from one side, once per approach; it bounced when the close 15 minutes "
            "later is still on that side, so a hit counts once its 15 minutes have passed. A "
            "count, not a forecast."
        ),
    }
