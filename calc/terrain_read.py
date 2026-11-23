"""The regime read and the relations of a price to a level.

Rules, never generative: identical inputs give identical output.

The regime is the sign of net GEX at spot. It is issued whenever that number is known and not zero
and the spot is above 0; otherwise there is no regime (UNAVAILABLE).

The headline says only what published evidence supports: the sign goes with the size of price
swings, not with a trade direction; the sign is a model (it assumes dealers long calls and short
puts), said once in the hover with the sources rather than on the headline (Ni, Pearson,
Poteshman & White, RFS 2021; Baltussen, Da, Lammers & Martens, JFE 2021; Amaya, Garcia-Ares,
Pearson & Vasquez 2025). The names are the industry's: positive and negative gamma (IMF Global
Financial Stability Report, April 2026, chapter 1) and the gamma flip (the Options Industry
Council's June 2026 FAQ).
"""

from __future__ import annotations

from dataclasses import dataclass

from numeric_contract import price_text

REGIME_POSITIVE_GAMMA = "POSITIVE_GAMMA"
REGIME_NEGATIVE_GAMMA = "NEGATIVE_GAMMA"
REGIME_UNAVAILABLE = "UNAVAILABLE"

#: where a level sits against a price (level_side)
LEVEL_ABOVE, LEVEL_AT, LEVEL_BELOW = "ABOVE", "AT", "BELOW"
#: the way a price moved through a level (crossed)
CROSSED_UP, CROSSED_DOWN = "up", "down"


def level_side(level: float | None, price: float | None) -> str | None:
    """Where `level` sits against `price`: LEVEL_ABOVE, LEVEL_AT or LEVEL_BELOW.

    From the exact values (rounding happens only on screen); None when either is unknown. The
    one side rule of every relation of a price to a level: the wall states, the flip side, the
    levels' sides and the crosses.
    """
    if level is None or price is None:
        return None
    if level > price:
        return LEVEL_ABOVE
    if level < price:
        return LEVEL_BELOW
    return LEVEL_AT


def price_side(level: float | None, price: float | None) -> str | None:
    """Where `price` sits against `level` (the other way round from level_side).

    LEVEL_ABOVE when the price is over the level, LEVEL_AT, LEVEL_BELOW; None when either is
    unknown.
    """
    return {LEVEL_ABOVE: LEVEL_BELOW, LEVEL_AT: LEVEL_AT, LEVEL_BELOW: LEVEL_ABOVE, None: None}[
        level_side(level, price)
    ]


def from_spot_text(distance: float | None, side: str | None) -> str | None:
    """Word a level's distance from the live price (level minus price) and its side.

    The side is level_side's, as the screen words it: "at spot", "1.30 above spot", "1.30 below
    spot". None when unknown.
    """
    if side is None or distance is None:
        return None
    if side == LEVEL_AT:
        return "at spot"
    return f"{price_text(abs(distance))} {side.lower()} spot"


def within(low: float | None, high: float | None, price: float | None) -> bool:
    """Whether `price` is inside the range from `low` to `high`, either edge included.

    By level_side.
    """
    return level_side(low, price) in (LEVEL_BELOW, LEVEL_AT) and level_side(high, price) in (
        LEVEL_ABOVE,
        LEVEL_AT,
    )


def crossed(level: float | None, before: float | None, after: float | None) -> str | None:
    """CROSSED_UP or CROSSED_DOWN when the price crossed `level`; None otherwise.

    CROSSED_UP when the price moved from under `level` to at or over it, CROSSED_DOWN from over
    it to at or under it (level_side).
    """
    was, now = level_side(level, before), level_side(level, after)
    if was == LEVEL_ABOVE and now in (LEVEL_AT, LEVEL_BELOW):
        return CROSSED_UP
    if was == LEVEL_BELOW and now in (LEVEL_AT, LEVEL_ABOVE):
        return CROSSED_DOWN
    return None


#: the flip's note (flip_note): the flip is placed by a modelled curve, the regime is Schwab's
#: gamma, and at the chain's price the two disagree on the sign
FLIP_CURVE_DISAGREES = (
    "The gamma flip is placed by a modelled curve that disagrees with Schwab's "
    "gamma at today's price."
)


def flip_note(gamma_at_spot: float | None, curve_at_spot: float | None) -> str | None:
    """Return the note shown beside the gamma flip, or None when there is nothing to say.

    FLIP_CURVE_DISAGREES when Schwab's gamma (`gamma_at_spot`) and the flip's curve
    (`curve_at_spot`) are both known at the chain's price and their signs differ; None when they
    agree or one is unknown.
    """
    differ = (
        gamma_at_spot is not None
        and curve_at_spot is not None
        and (gamma_at_spot > 0) != (curve_at_spot > 0)
    )
    return FLIP_CURVE_DISAGREES if differ else None


@dataclass(frozen=True)
class TerrainRead:
    """The regime, the headline and its sources (shown on hover)."""

    regime: str
    headline: str
    headline_source: str


def regime_from_signed_gamma(signed_gamma: float | None) -> str | None:
    """Return the regime: the one rule for the sign of net GEX.

    None when the number is absent or exactly zero.
    """
    if signed_gamma is None or signed_gamma == 0:
        return None
    return REGIME_POSITIVE_GAMMA if signed_gamma > 0 else REGIME_NEGATIVE_GAMMA


#: the assumption every estimate rests on (the hover's first line)
_ASSUMPTION = (
    "Estimate assumes dealers long calls, short puts (SqueezeMetrics 2017), the convention "
    "least reliable for single stocks (Garleanu, Pedersen & Poteshman 2009)."
)
#: each regime's headline (what the evidence supports, no trade instruction) and its sources,
#: shown on hover
_READS = {
    REGIME_POSITIVE_GAMMA: (
        "Net GEX is positive: research links this to smaller price swings, "
        "not to a trade direction.",
        _ASSUMPTION + " Swings: Ni, Pearson, Poteshman & White, RFS 2021; Amaya, Garcia-Ares, "
        "Pearson & Vasquez 2025.",
    ),
    REGIME_NEGATIVE_GAMMA: (
        "Net GEX is negative: research links this to larger price swings and "
        "some late-day continuation, not to a trade direction.",
        _ASSUMPTION + " Swings: Ni, Pearson, Poteshman & White, RFS 2021; late-day "
        "continuation: Baltussen, Da, Lammers & Martens, JFE 2021.",
    ),
    REGIME_UNAVAILABLE: (
        "No estimate: net GEX at the price is unknown or zero, or there is no price.",
        "",
    ),
}
#: each regime as every screen says it
REGIME_TEXT = {
    REGIME_POSITIVE_GAMMA: "Positive gamma",
    REGIME_NEGATIVE_GAMMA: "Negative gamma",
    REGIME_UNAVAILABLE: "unavailable",
}
#: where the price sits against the gamma flip (price_side), as the Desk's agreement strip says
#: it; no words where it is not known
FLIP_RELATION_TEXT: dict[str | None, str | None] = {
    LEVEL_ABOVE: "Above gamma flip",
    LEVEL_AT: "At gamma flip",
    LEVEL_BELOW: "Below gamma flip",
    None: None,
}


def build_terrain_read(*, spot: float | None, gamma_at_spot: float | None = None) -> TerrainRead:
    """Return the regime read at `spot`.

    The regime is the sign of net GEX at spot (`gamma_at_spot`), not the side of the flip the
    price is on, so a chain whose profile never crosses zero still has one. It is issued with a
    spot above 0 and that number known and not zero; otherwise it is UNAVAILABLE.
    """
    regime = regime_from_signed_gamma(gamma_at_spot) if spot is not None and spot > 0 else None
    if regime is None:
        regime = REGIME_UNAVAILABLE
    headline, source = _READS[regime]
    return TerrainRead(regime=regime, headline=headline, headline_source=source)
