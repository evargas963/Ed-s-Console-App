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
    measured = [(f, v) for f in FAMILIES if (v := strengths[f]) is not None]
    if gamma is None or not measured:
        return None
    strength = 100.0 * sum(v for _f, v in measured) / len(measured)
    return Composite(gamma, strength, tuple(f for f, _v in measured))


@dataclass(frozen=True)
class FamilyVote:
    """One family's vote on the kind of move (family_votes).

    `vote`: +1 wider and continuing, -1 calmer and reverting, None not measured; `reading`: the
    number it votes on.
    """

    family: str
    vote: int | None
    reading: float | None


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
    vote. A zero or unknown reading casts none.
    """

    def sign(x: float | None) -> int | None:
        return None if x is None or x == 0 else (1 if x > 0 else -1)

    start, now = prices
    move = None if start is None or now is None else now - start
    flow_sign, move_sign = sign(flow), sign(move)
    trades = None if flow_sign is None or move_sign is None else flow_sign * move_sign
    positioning = sign(gamma_at_price)
    return (
        FamilyVote("positioning", None if positioning is None else -positioning, gamma_at_price),
        FamilyVote("option trades", trades, flow),
        FamilyVote("volatility", sign(atm_iv_change), atm_iv_change),
        FamilyVote("stock book", None, None),
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
    "volume": "look_volume",
    "vol_oi": "vol_oi",
    "visits": "touches",
    "bought_sold": "bought_sold",
}


def _shades(r: StrikeReadings) -> dict[str, float | None]:
    """Return the numbers the page shades each column's cell by, against the column's peak.

    The put/call volume shades by 1 - put/call: positive call-heavy, negative put-heavy; the
    look-back's volatility change and hedging flow by their own signed numbers.
    """
    out: dict[str, float | None] = {key: getattr(r, name) for key, name in SHADED.items()}
    out["pc_vol_lean"] = None if r.pc_vol is None else 1 - r.pc_vol
    out["iv_change"] = r.look.iv_change
    out["flow"] = r.look.flow
    return out


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
    shades = [_shades(r) for r in by_strike.values()]
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

    The spot line marks the strike the price sits under; the price row is drawn after the rows at
    or above the price (`price_row_index`, the rows running highest strike first), and
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
        "price_row_index": None if spot is None else sum(r["strike"] >= spot for r in rows),
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


def _composite_cells(c: Composite | None) -> dict[str, Any]:
    """Return the Composite's cell; "-" with why when it is not known."""
    shown = None if c is None else _composite_shown(c)
    return {
        "composite": None if shown is None else shown[0],
        "composite_text": None if shown is None else shown[1],
        "composite_reason": _absent(None if shown is None else shown[0], COMPOSITE_REASON),
        "composite_hover": None if shown is None else shown[2],
    }


def _gamma_cells(gamma: float | None) -> dict[str, Any]:
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


def _look_cells(r: StrikeReadings) -> dict[str, Any]:
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
            f"({ASSUMPTION}); "
            f"{count_text(look.unpriced)} contracts with no side, delta or price left out."
        ),
        "pace_text": None,
        "pace_reason": PACE_REASON,
        "pace_hover": None,
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
