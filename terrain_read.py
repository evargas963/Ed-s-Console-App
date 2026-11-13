"""The regime read and the relations of a price to a level.

Rules, never generative: identical inputs give identical output.

The regime is the sign of dealer gamma at spot, which needs strikes near spot; the flip level is
what needs a wide chain. So:
  * confidence TRUSTED or LEVEL_APPROX: the regime and its posture are issued; the confidence is
    served beside them and says when the flip level is approximate.
  * confidence NARROW or UNAVAILABLE, a missing spot, or dealer gamma at spot absent or exactly
    zero: no regime (UNAVAILABLE) and the posture is to stand aside. The coverage floor is a
    bound below which the read declines to speak, not proof the sign is right above it
    (math_levels.GAMMA_FLIP_MIN_SPAN_PCT).
"""

from __future__ import annotations

from dataclasses import dataclass

from math_levels import GAMMA_FLIP_LEVEL_APPROX, GAMMA_FLIP_TRUSTED
from numeric_contract import price_text

REGIME_LONG_GAMMA = "LONG_GAMMA_CHOP"
REGIME_SHORT_GAMMA = "SHORT_GAMMA_TREND"
REGIME_UNAVAILABLE = "UNAVAILABLE"

POSTURE_FADE = "FADE_EDGES"
POSTURE_FOLLOW = "FOLLOW_BREAKS"
POSTURE_STAND_ASIDE = "STAND_ASIDE"

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
    if side is None:
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


def flip_note(curve_agrees: bool | None) -> str | None:
    """Return the note shown beside the gamma flip, or None when there is nothing to say.

    FLIP_CURVE_DISAGREES when the flip's curve and Schwab's gamma are both known at the chain's
    price and their signs differ (`curve_agrees` False); None when they agree or one is unknown.
    """
    return FLIP_CURVE_DISAGREES if curve_agrees is False else None


@dataclass(frozen=True)
class TerrainRead:
    """The regime, its posture, the flip's confidence and the headline."""

    regime: str
    posture: str
    confidence: str
    headline: str


def regime_from_signed_gamma(signed_gamma: float | None) -> str | None:
    """Return the regime: the one rule for the sign of dealer gamma.

    Positive dealer gamma is LONG_GAMMA_CHOP (dealers damp moves); negative is
    SHORT_GAMMA_TREND (dealers amplify). None when the sign is absent or exactly zero.
    """
    if signed_gamma is None or signed_gamma == 0:
        return None
    return REGIME_LONG_GAMMA if signed_gamma > 0 else REGIME_SHORT_GAMMA


#: each regime's posture and headline
_READS = {
    REGIME_LONG_GAMMA: (
        POSTURE_FADE,
        "Long gamma — chop regime. Fade the edges, do not chase breakouts.",
    ),
    REGIME_SHORT_GAMMA: (
        POSTURE_FOLLOW,
        "Short gamma — trend regime. Follow breaks, do not fade.",
    ),
    REGIME_UNAVAILABLE: (POSTURE_STAND_ASIDE, "Terrain unavailable — stand aside."),
}


def build_terrain_read(
    *, spot: float | None, flip_confidence: str, gamma_at_spot: float | None = None
) -> TerrainRead:
    """Return the regime read at `spot` for a flip of `flip_confidence`.

    The regime is the sign of dealer gamma at spot (`gamma_at_spot`), not the side of the flip
    the price is on, so a chain whose profile never crosses zero still has one. It is issued
    with a spot above 0 and a confidence of TRUSTED or LEVEL_APPROX; otherwise it is
    UNAVAILABLE.
    """
    speaks = (
        spot is not None
        and spot > 0
        and flip_confidence in (GAMMA_FLIP_TRUSTED, GAMMA_FLIP_LEVEL_APPROX)
    )
    regime = regime_from_signed_gamma(gamma_at_spot) if speaks else None
    if regime is None:
        regime = REGIME_UNAVAILABLE
    posture, headline = _READS[regime]
    return TerrainRead(
        regime=regime, posture=posture, confidence=flip_confidence, headline=headline
    )
