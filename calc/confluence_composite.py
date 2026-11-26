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
from typing import TypedDict

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
#: the one assumption the hedging flow rests on, said once beside it: each trade's side is read,
#: and the dealers are on the other side of it (docs/SOURCES.md garleanu-pedersen-poteshman-2009)
FLOW_ASSUMPTION = "the convention: the dealers take the other side of each trade"


@dataclass(frozen=True)
class StrikeReadings:
    """One strike's readings of one expiry, each as its producer computed it; None: not known.

    The open interest and volume with their (call, put) legs; the change in open interest since
    the prior day's capture (`oi_new`: the prior day listed no contract at this strike); the
    expiry's gamma profile at this strike's price (`gamma_here`); the regular session's touches
    and holds at the strike so far (calc.liquidity_value_engine.visits; None before it opens);
    its readings over the look-back window (`look`).
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
    look: StrikeLookBack

    @property
    def look_volume(self) -> float | None:
        """Contracts traded at the strike in the look-back, calls and puts."""
        return _sum(self.look.volume)

    @property
    def bought_sold(self) -> float | None:
        """Contracts bought less sold at the strike in the look-back (est.)."""
        b, s = self.look.bought, self.look.sold
        return None if b is None or s is None else b - s


@dataclass(frozen=True)
class StrikeLookBack:
    """One strike's readings over the look-back window (calc.option_window.strike_look_back).

    `volume`: contracts traded in the window, (calls, puts); `iv_change`: the strike's volatility
    blend now less at the window's start, in vol points; `bought`, `sold`, `unknown`: contracts,
    calls and puts together; `flow`: the hedging flow in dollars, with `unpriced`, the contracts
    whose flow is not known. Each None when not known.
    """

    volume: tuple[float, float] | None
    iv_change: float | None
    bought: float | None
    sold: float | None
    unknown: float | None
    flow: float | None
    unpriced: float | None


#: a strike whose contracts the stream did not hold over the whole window: nothing known
NOT_HELD = StrikeLookBack(None, None, None, None, None, None, None)


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
    look: StrikeLookBack,
) -> StrikeReadings:
    """Return one strike's readings from its producers' values.

    Each leg's gamma is Schwab's as sent, whatever its sign (AGENTS rule 2). `prior` is the
    prior day's bucket of this strike (None: that day listed no contract here, or no prior day is
    held, `prior_held` False); `visit` its (touches, holds) today (None: the session not open);
    `look` its readings over the look-back (calc.option_window.strike_look_back).
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
        look=look,
    )


def iv_by_strike(contracts: list[OptionContract]) -> dict[float, float | None]:
    """(open interest + volume)-weighted Schwab volatility, in vol points.

    Each strike's blend of its contracts that carry a volatility (_blend).
    """
    grouped: dict[float, list[OptionContract]] = {}
    for c in contracts:
        if c.strike is not None:
            grouped.setdefault(float(c.strike), []).append(c)
    return {strike: _blend(rows) for strike, rows in grouped.items()}


def _blend(rows: list[OptionContract]) -> float | None:
    """Return one strike's volatility, weighted by each contract's open interest plus its volume.

    Contracts that carry one volatility give it, whatever their weights. Where they differ, every
    one needs both counts: one not known leaves the blend unknown (None), never the others' alone.
    Weights that sum to 0 give the simple mean. None when no contract carries a volatility.
    """
    priced = [(c, c.volatility) for c in rows if c.volatility is not None]
    ivs = [iv for _c, iv in priced]
    if len(set(ivs)) <= 1:
        return ivs[0] if ivs else None
    weights = [
        float(c.open_interest) + float(c.volume)
        for c, _iv in priced
        if c.open_interest is not None and c.volume is not None
    ]
    if len(weights) != len(priced):
        return None
    total = sum(weights)
    if total == 0:
        return sum(ivs) / len(ivs)
    return sum(w * iv for w, iv in zip(weights, ivs, strict=True)) / total


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
    measured = [(f, v) for f in FAMILIES if (v := strengths[f]) is not None]
    if gamma is None or not measured:
        return None
    strength = 100.0 * sum(v for _f, v in measured) / len(measured)
    return Composite(gamma, strength, tuple(f for f, _v in measured))


@dataclass(frozen=True)
class FamilyVote:
    """One family's vote on the kind of move (family_votes).

    `vote`: +1 wider and continuing, -1 calmer and reverting, None not measured; `reading`: the
    number it votes on; `text`: what the family read, as its card says it: its reading and its
    vote, or why it cast none.
    """

    family: str
    vote: int | None
    reading: float | None
    text: str


#: a vote in words: +1 wider and continuing, -1 calmer and reverting
VOTE_WORDS = {1: "votes wider, continuing", -1: "votes calmer, reverting"}
#: what the stock's book and tape card says: the matrix reads neither
NOT_MEASURED = "not measured on the matrix yet"


def _vote_sign(x: float | None) -> int | None:
    """Return the sign a reading votes by: None when it is not known or 0, which cast no vote."""
    return None if x is None or x == 0 else _sign(x)


def _why_none(*readings: tuple[str, float | None]) -> str:
    """Why a family cast no vote: its first reading not known, else its first of 0.

    A reading of 0 is a value and is said as one, never as not known.
    """
    for name, x in readings:
        if x is None:
            return f"{name} is not known"
    return next(f"{name} is 0" for name, x in readings if x == 0)


def _voted_text(family: str, vote: int, reading: float | None) -> str:
    """Return what a family that voted read, in words: its reading and its vote."""
    words = VOTE_WORDS[vote]
    if family == "positioning":
        return f"{'Negative' if vote == 1 else 'Positive'} gamma at the price: {words}"
    if family == "option trades":
        side = "with" if vote == 1 else "against"
        return f"Hedging flow {dollars_text(reading)} {side} the look-back's move: {words}"
    return f"At-the-money IV {_signed(reading, 2)} in the look-back: {words}"


def _family(
    family: str, vote: int | None, reading: float | None, *readings: tuple[str, float | None]
) -> FamilyVote:
    """One family's vote, with its card's words: voted (_voted_text), or why not (_why_none)."""
    text = _why_none(*readings) if vote is None else _voted_text(family, vote, reading)
    return FamilyVote(family, vote, reading, text)


def family_votes(
    gamma_at_price: float | None,
    flow: float | None,
    prices: tuple[float | None, float | None],
    atm_iv_change: float | None,
) -> tuple[FamilyVote, ...]:
    """Return each family's vote on the kind of move, one equal vote each (decision 64, O-1).

    Positioning: the whole book's net gamma at the price, negative wider and continuing (the
    research's read). Option trades: the expiry's hedging flow in the look-back with the
    look-back's price move (`prices`: at its start and now; continuing) or against it
    (reverting). Volatility: the expiry's at-the-money volatility rising (wider) or falling
    (calmer) in the look-back. The stock's book and tape are not measured on the matrix: no
    vote. A zero or unknown reading casts none, and its card says which.
    """
    start, now = prices
    move = None if start is None or now is None else now - start
    flow_sign, move_sign = _vote_sign(flow), _vote_sign(move)
    trades = None if flow_sign is None or move_sign is None else flow_sign * move_sign
    positioning = _vote_sign(gamma_at_price)
    return (
        _family(
            "positioning",
            None if positioning is None else -positioning,
            gamma_at_price,
            ("the gamma at the price", gamma_at_price),
        ),
        _family(
            "option trades",
            trades,
            flow,
            ("the look-back's hedging flow", flow),
            ("the look-back's price move", move),
        ),
        _family(
            "volatility",
            _vote_sign(atm_iv_change),
            atm_iv_change,
            ("the look-back's at-the-money volatility change", atm_iv_change),
        ),
        FamilyVote("stock book", None, None, NOT_MEASURED),
    )


def expiry_flow(matrix: Matrix) -> float | None:
    """Return the expiry's hedging flow over the look-back: every strike's; None when one is not."""
    flows = [r.look.flow for r in matrix.readings.values()]
    if not flows or any(f is None for f in flows):
        return None
    return sum(f for f in flows if f is not None)


def atm_iv_change(matrix: Matrix, spot: float | None) -> float | None:
    """Return the expiry's at-the-money volatility change over the look-back.

    The mean of the two listed strikes the price lies between (the at-the-money rule as built,
    calc.terrain_engine.atm_sigma_by_expiry), each its blend's change; one strike when the
    price is on it; None without a price, outside the strikes, or a change not known.
    """
    if spot is None:
        return None
    below = max((s for s in matrix.strikes if s <= spot), default=None)
    above = min((s for s in matrix.strikes if s >= spot), default=None)
    if below is None or above is None:
        return None
    changes = [matrix.readings[s].look.iv_change for s in {below, above}]
    if any(c is None for c in changes):
        return None
    return sum(c for c in changes if c is not None) / len(changes)


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


def _peak(values: Iterable[object]) -> float | None:
    """Largest absolute value on this expiry: the column's scale."""
    peak = None
    for value in values:
        if not isinstance(value, (int, float)):
            continue
        size = abs(float(value))
        if peak is None or size > peak:
            peak = size
    return peak


class Shades(TypedDict):
    """The number each shaded column's cell is shaded by, against the column's peak."""

    gamma_here: float | None
    net_gex: float | None
    oi: float | None
    oi_change: float | None
    dex: float | None
    charm: float | None
    vanna: float | None
    iv: float | None
    volume: float | None
    vol_oi: float | None
    visits: float | None
    bought_sold: float | None
    pc_vol_lean: float | None
    iv_change: float | None
    flow: float | None


def _shades(r: StrikeReadings) -> Shades:
    """Return the numbers the page shades each column's cell by, against the column's peak.

    The put/call volume shades by 1 - put/call: positive call-heavy, negative put-heavy; the
    look-back's volatility change and hedging flow by their own signed numbers.
    """
    return {
        "gamma_here": r.gamma_here,
        "net_gex": r.net_gex,
        "oi": r.oi,
        "oi_change": r.oi_change,
        "dex": r.dex,
        "charm": r.charm,
        "vanna": r.vanna,
        "iv": r.iv,
        "volume": r.look_volume,
        "vol_oi": r.vol_oi,
        "visits": r.touches,
        "bought_sold": r.bought_sold,
        "pc_vol_lean": None if r.pc_vol is None else 1 - r.pc_vol,
        "iv_change": r.look.iv_change,
        "flow": r.look.flow,
    }


def build_matrix(
    exposures: dict[float, Bucket],
    charm_by_strike: dict[float, CharmBucket],
    ivs: dict[float, float | None],
    spot: float,
    gamma_profile: Mapping[float, float],
    prior: dict[float, Bucket] | None,
    visits: Mapping[float, tuple[int, int]],
    looks: Mapping[float, StrikeLookBack] | None,
) -> Matrix:
    """Build the readings of one expiry's book and each strike's Composite.

    `gamma_profile`: the expiry's gamma profile by price (its value at each listed strike);
    `prior`: the prior day's book of the same expiry (None: no prior day held); `visits`: each
    strike's (touches, holds) in today's regular session (empty before it opens); `looks`: each
    strike's readings over the look-back (a strike not in it, or no window: NOT_HELD). The
    families measured
    at a strike: positioning (|net GEX|), option trades (the look-back's volume) and volatility
    (|the look-back's change in it|), each against its largest on the expiry. The rows the page
    shows are drawn from it (window_rows).
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
            NOT_HELD if looks is None else looks.get(s, NOT_HELD),
        )
        for s in strikes
    }
    shades: list[Mapping[str, object]] = [_shades(r) for r in by_strike.values()]
    peaks = {key: _peak(s[key] for s in shades) for key in shades[0]} if shades else {}
    composites = {
        s: composite(
            r.gamma_here,
            {
                "positioning": _share(r.net_gex, peaks["net_gex"]),
                "option trades": _share(r.look_volume, peaks["volume"]),
                "volatility": _share(r.look.iv_change, peaks["iv_change"]),
                # measured on the price row only (decision 64, O-1), not yet on the matrix
                "stock book": None,
            },
        )
        for s, r in by_strike.items()
    }
    return Matrix(readings=by_strike, composites=composites, peaks=peaks, strikes=strikes)


def window_rows(matrix: Matrix, shown: list[float]) -> list[MatrixRow]:
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
    rows: list[MatrixRow],
    strikes: list[float],
    spot: float | None,
    sigma_root_t: float | None,
) -> list[ShownRow]:
    """Return the shown rows, each with its distance from the live price, spot line and heading.

    The spot line marks the strike the price sits under (the strike the matrix selects first).
    The matrix is read at the book's price; each row's distance is from the live price
    (`distance`'s, in dollars and in the expiry's implied moves, `sigma_root_t`). The price itself
    is not served here: the page draws it from the price row (one producer). Pure: the rows given
    are not changed.
    """
    under = None if spot is None else under_strike(spot, strikes)
    shown: list[ShownRow] = []
    for row in rows:
        away = distance(row["strike"], spot, sigma_root_t)
        shown.append(
            {
                **row,
                **away,
                "spot_line": row["strike"] == under,
                # the selected strike's heading, whole (AGENTS.md rule 4): its distance only when
                # known, never a sentence with "-" in it (rule 5)
                "heading_said": row["strike_text"]
                if away["distance_text"] is None
                else f"{row['strike_text']} · {away['distance_text']} points from the price",
            }
        )
    return shown


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
    """Return a change in a count as the screen shows it: whole, signed, a rise with its plus."""
    text = count_text(n)
    if n is None or text is None:
        return None
    return "+" + text if n > 0 else text


def _absent(value: float | None, words: str) -> str | None:
    if isinstance(value, (int, float)):
        return None
    return words


def _legs_text(legs: tuple[float, float] | None, read: str) -> str | None:
    """Return a sum's parts on hover: the calls' and the puts' count."""
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


COMPOSITE_REASON = "the gamma at this strike or every family is not known"
GAMMA_REASON = "no priced contract gives the gamma at this price"


def _composite_shown(c: Composite) -> tuple[float, str, str]:
    """Return a known Composite's cell: its shading number, its text and its hover.

    Shaded by the strength against a peak of 1, red where the gamma is negative.
    """
    sign = _sign(c.gamma)
    hover = (
        f"{GAMMA_WORDS[sign]} here ({ASSUMPTION}): {GAMMA_EFFECT[sign]}. Strength "
        f"{c.strength:.0f} of 100: the equal vote of {len(c.measured)} of {len(FAMILIES)} "
        f"families measured here ({', '.join(c.measured)}), each its size against the "
        "expiry's largest. A size and a kind of move, not a direction; untested."
    )
    return sign * c.strength / 100.0, f"{GAMMA_SHORT[sign]} {c.strength:.0f}", hover


class CompositeCells(TypedDict):
    """The Composite's cell: its number, its words, why it is "-", and its hover."""

    composite: float | None
    composite_text: str | None
    composite_reason: str | None
    composite_hover: str | None


def _composite_cells(c: Composite | None) -> CompositeCells:
    """Return the Composite's cell; "-" with why when it is not known."""
    shown = None if c is None else _composite_shown(c)
    return {
        "composite": None if shown is None else shown[0],
        "composite_text": None if shown is None else shown[1],
        "composite_reason": _absent(None if shown is None else shown[0], COMPOSITE_REASON),
        "composite_hover": None if shown is None else shown[2],
    }


class GammaCells(TypedDict):
    """The gamma-if-here cell: the sign's words, why it is "-", and the model on hover."""

    gamma_here_text: str | None
    gamma_here_reason: str | None
    gamma_here_hover: str | None


def _gamma_cells(gamma: float | None) -> GammaCells:
    """Return the gamma-if-here cell: the sign's words, the model on hover; "-" with why without."""
    sign = None if gamma is None else _sign(gamma)
    return {
        "gamma_here_text": None if sign is None else GAMMA_WORDS[sign],
        "gamma_here_reason": _absent(gamma, GAMMA_REASON),
        "gamma_here_hover": None
        if sign is None
        else (
            f"Model: the expiry's net gamma if the price were at this strike, "
            f"{dollars_text(gamma)} per 1% move; {GAMMA_EFFECT[sign]} ({ASSUMPTION})."
        ),
    }


class LookCells(TypedDict):
    """The look-back's columns: volume, volatility change, bought less sold, flow and pace.

    Each its words, why it is "-", and its hover.
    """

    volume_text: str | None
    volume_reason: str | None
    volume_hover: str | None
    iv_change_text: str | None
    iv_change_reason: str | None
    iv_change_hover: str | None
    bought_sold_text: str | None
    bought_sold_reason: str | None
    bought_sold_hover: str | None
    flow_text: str | None
    flow_reason: str | None
    flow_hover: str | None
    pace_text: str | None
    pace_reason: str | None
    pace_hover: str | None


class VisitsCells(TypedDict):
    """Today's hits and bounces at the strike: its words, why it is "-", and its hover."""

    visits_text: str | None
    visits_reason: str | None
    visits_hover: str | None


class MatrixRow(Shades, CompositeCells, GammaCells, LookCells, VisitsCells):
    """One strike's row of the matrix: each column's words, why it is "-", and its hover."""

    strike: float
    strike_text: str
    net_gex_text: str | None
    net_reason: str | None
    oi_text: str | None
    oi_reason: str | None
    oi_hover: str | None
    oi_change_text: str | None
    oi_change_reason: str | None
    oi_change_hover: str | None
    dex_text: str | None
    dex_reason: str | None
    charm_text: str | None
    charm_reason: str | None
    vanna_text: str | None
    vanna_reason: str | None
    iv_text: str | None
    iv_reason: str | None
    pc_vol_text: str | None
    pc_vol_reason: str | None
    vol_oi_text: str | None
    vol_oi_reason: str | None


class ShownRow(MatrixRow, Distance):
    """A shown row: with its distance from the live price, its spot line and its heading."""

    spot_line: bool
    heading_said: str


def _row(strike: float, r: StrikeReadings, c: Composite | None) -> MatrixRow:
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
        **_look_cells(r),
        "pc_vol_text": _text(r.pc_vol, 2),
        "pc_vol_reason": _absent(r.pc_vol, "put/call volume is missing"),
        "vol_oi_text": _text(r.vol_oi, 2),
        "vol_oi_reason": _absent(r.vol_oi, "volume/open interest is missing"),
        **_visits_cells(r.touches, r.holds),
    }


#: why a look-back reading is "-": a contract at the strike was not held over the whole window
LOOK_REASON = "the stream did not hold every contract at this strike over the whole look-back"
#: why the flow alone is "-": the chain sent no multiplier (the shares a contract is on) for one
NO_MULTIPLIER = "Schwab's chain sent no multiplier for a contract at this strike"
#: why pace is "-": its baseline, the same time of day over 20 sessions (decision 63), is not held
PACE_REASON = "needs the same time of day over 20 sessions of the record; not held yet"


def _look_cells(r: StrikeReadings) -> LookCells:
    """Return the look-back's columns: volume, volatility change, bought less sold, flow, pace."""
    look = r.look
    day = _legs_text(r.volume_legs, "Today")
    traded = _legs_text(look.volume, "In the look-back")
    unknown_share = None
    b, s, u = look.bought, look.sold, look.unknown
    if b is not None and s is not None and u is not None and b + s + u > 0:
        unknown_share = f"{100.0 * u / (b + s + u):.0f}%"
    return {
        "volume_text": count_text(r.look_volume),
        "volume_reason": _absent(r.look_volume, LOOK_REASON),
        "volume_hover": " · ".join(t for t in (traded, day) if t) or None,
        "iv_change_text": None if look.iv_change is None else _signed(look.iv_change, 2),
        "iv_change_reason": _absent(look.iv_change, LOOK_REASON),
        "iv_change_hover": (
            "Schwab's volatility at the strike now less at the look-back's start (the blend over "
            "calls and puts); it moves with the price too, not only with volatility."
        ),
        "bought_sold_text": _signed_count(r.bought_sold),
        "bought_sold_reason": _absent(r.bought_sold, LOOK_REASON),
        "bought_sold_hover": None
        if unknown_share is None
        else (
            f"Bought {count_text(b)} · sold {count_text(s)} · unknown {count_text(u)} "
            f"({unknown_share}). est.: each rise in a contract's volume read whole by its last "
            "trade against the middle of the quote in force; on the middle, unknown."
        ),
        "flow_text": dollars_text(look.flow),
        "flow_reason": _absent(look.flow, LOOK_REASON if look.bought is None else NO_MULTIPLIER),
        "flow_hover": None
        if look.flow is None
        else (
            "est.: the stock the look-back's option trades would have the dealers trade, bought "
            "less sold x Schwab's delta x the contract's multiplier x the stock's price "
            f"({FLOW_ASSUMPTION}); "
            f"{count_text(look.unpriced)} contracts with no side, delta or price left out."
        ),
        "pace_text": None,
        "pace_reason": PACE_REASON,
        "pace_hover": None,
    }


VISITS_REASON = "the regular session has not opened"


def _visits_cells(touches: int | None, holds: int | None) -> VisitsCells:
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
