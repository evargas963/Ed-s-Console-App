"""Deterministic terrain read — plain-English regime summary from computed levels.

Rules-based, never generative: identical inputs always produce identical output, so the
read can be tested, diffed, and trusted. There is no model in this path and nothing here
can hallucinate a level.

Two institutional invariants:

1. **Fail-closed — on the SIGN, which is what a posture rests on.** Corrected 2026-08-26: this
   invariant used to read "when the confidence is not TRUSTED, the read withholds regime and
   posture". That is no longer what the code does, and the old wording conflated two questions.
   The regime is the SIGN of dealer gamma AT SPOT, which needs strikes NEAR spot; the flip LEVEL
   is what needs a wide chain. So:
     * confidence TRUSTED or LEVEL_APPROX -> regime and posture are issued; at LEVEL_APPROX the
       flip LEVEL is explicitly disclosed as approximate on the line that prints it.
     * confidence NARROW or UNAVAILABLE -> everything is withheld, with the reason stated. This is a
       conservative DECLINE-TO-SPEAK bound, not a finding about the sign: "a chain that narrow
       cannot support even the sign" was asserted here and is WITHDRAWN (2026-08-26, second pass) —
       span was never measured against sign reliability, and when it finally was, no cliff appeared
       at the floor (see math_levels.GAMMA_FLIP_MIN_SPAN_PCT). Passing this bound means we are
       willing to speak; it does not mean the sign is verified.
     * missing spot, or dealer gamma at spot absent or exactly zero -> withheld, with the reason.
   It never presents a posture derived from a level we know is unreliable (a narrow chain
   misplaces the flip by ~3.6% — measured 2026-07-19: 770.35 against a full-chain reference of
   745.61), and it never presents a coverage verdict as proof the level is right.
2. **Absence reads as absence.** A missing level is reported missing, never defaulted to a
   neutral-looking number.

The read is the regime, its posture and headline, why no regime is issued when none is, and
what qualifies the flip level shown. Where price sits against the walls is not restated here:
the walls, their states and distances are the terrain's own served fields.
"""

from __future__ import annotations

from dataclasses import dataclass

from math_levels import (
    FLIP_CURVE_NOT_FINITE,
    FLIP_FOUND,
    FLIP_INCOMPLETE,
    FLIP_NO_CROSSING,
    FLIP_NO_INPUT,
    FLIP_NO_PRICED_CONTRACT,
    FLIP_NO_STRIKES,
    GAMMA_FLIP_LEVEL_APPROX,
    GAMMA_FLIP_TRUSTED,
    UNPRICED_SETTLED,
    GammaFlip,
)

REGIME_LONG_GAMMA = "LONG_GAMMA_CHOP"
REGIME_SHORT_GAMMA = "SHORT_GAMMA_TREND"
REGIME_UNAVAILABLE = "UNAVAILABLE"
#: The regime and posture are read the same way for every ticker. The +call/-put dealer-sign
#: convention is MODELLED, not observed -- the mechanism line below says so on every ticker.

POSTURE_FADE = "FADE_EDGES"
POSTURE_FOLLOW = "FOLLOW_BREAKS"
POSTURE_STAND_ASIDE = "STAND_ASIDE"

#: the one wording, shown whenever the flip's modelled curve and Schwab's gamma disagree on the
#: sign at today's price (the flip is placed by the curve; the regime is Schwab's gamma)
FLIP_CURVE_DISAGREES = ("The gamma flip is placed by a modelled curve that disagrees with Schwab's "
                        "gamma at today's price.")
#: the one wording for a flip level placed on a chain too narrow to place it precisely
#: (confidence LEVEL_APPROX); the regime does not depend on it
FLIP_LEVEL_APPROXIMATE = ("Approximate: the chain is too narrow to place this level precisely "
                          "(about 1.4% of spot).")
#: what every regime rests on, on every ticker: open interest does not say who holds a contract
REGIME_BASIS = ("Dealer gamma is modelled from open interest (dealers long calls, short puts), "
                "not observed positioning.")

#: why there is no gamma flip when its curve could not be built, by GammaFlip.reason
_FLIP_UNAVAILABLE_TEXT = {
    FLIP_NO_INPUT: "no option chain or price",
    FLIP_NO_STRIKES: "no strikes in the chain",
    FLIP_NO_PRICED_CONTRACT: "no contract could be priced",
    FLIP_CURVE_NOT_FINITE: "curve not finite",
}


def flip_absent_reason(flip: GammaFlip) -> str:
    """Why there is no gamma flip -- the one wording every consumer carries in its place: the
    prices searched when the curve holds one sign over them, how many of the book's contracts
    could not be priced when the curve is incomplete, else why there is no curve. "" when
    there is a flip."""
    if flip.state == FLIP_FOUND:
        return ""
    if flip.state == FLIP_NO_CROSSING:
        return f"none in {flip.domain_lo:.2f}–{flip.domain_hi:.2f}"
    if flip.state == FLIP_INCOMPLETE:
        return f"incomplete, {sum(n for r, n in flip.unpriced.items() if r != UNPRICED_SETTLED)} unpriced"
    return _FLIP_UNAVAILABLE_TEXT[flip.reason]


#: flip_side: which side of a level (the gamma flip, a wall) a price is on
FLIP_SIDE_ABOVE = "ABOVE"
FLIP_SIDE_BELOW = "BELOW"
FLIP_SIDE_AT = "AT"


def flip_side(spot: float | None, flip: float | None) -> str | None:
    """Which side of the level spot is on: the one rule behind the served flip_relation and
    the two wall relations. At the level itself it is on neither. None without a level or a
    spot."""
    if spot is None or flip is None:
        return None
    return FLIP_SIDE_AT if spot == flip else FLIP_SIDE_ABOVE if spot > flip else FLIP_SIDE_BELOW


@dataclass(frozen=True)
class TerrainRead:
    """The terrain read. `regime_reason`: why no regime is issued ("" when one is).
    `flip_caveat`: what qualifies the flip level or its absence reason ("" when nothing does)."""

    regime: str
    posture: str
    confidence: str
    headline: str
    regime_reason: str = ""
    flip_caveat: str = ""


def regime_from_signed_gamma(signed_gamma: float | None) -> str | None:
    """THE authority for the gamma-regime SIGN THRESHOLD (RC-345 / F07). Positive dealer
    gamma is LONG_GAMMA_CHOP (dealers damp moves); negative is SHORT_GAMMA_TREND (dealers
    amplify). Returns None when the sign is absent or exactly zero, so every caller shares
    one threshold instead of re-deriving `> 0` locally. build_terrain_read and
    institutional_behavior both consume this — there is no second sign authority."""
    if signed_gamma is None or signed_gamma == 0:
        return None
    return REGIME_LONG_GAMMA if signed_gamma > 0 else REGIME_SHORT_GAMMA


def _posture_for(regime: str) -> str:
    if regime == REGIME_LONG_GAMMA:
        return POSTURE_FADE
    if regime == REGIME_SHORT_GAMMA:
        return POSTURE_FOLLOW
    return POSTURE_STAND_ASIDE


def _unavailable(reason: str, confidence: str) -> TerrainRead:
    return TerrainRead(
        regime=REGIME_UNAVAILABLE,
        posture=POSTURE_STAND_ASIDE,
        confidence=confidence,
        headline="Terrain unavailable — stand aside.",
        regime_reason=reason,
    )


def build_terrain_read(
    *,
    spot: float | None,
    flip: float | None,
    flip_confidence: str,
    gamma_at_spot: float | None = None,
    flip_curve_agrees: bool | None = None,
) -> TerrainRead:
    """The regime, its posture and confidence. The regime is the sign of dealer gamma at spot
    (`gamma_at_spot`), not the side of the flip, so a curve with no flip still has one. No
    regime (with its reason) on a missing spot, a missing or zero gamma, or chain coverage
    below the floor (NARROW / UNAVAILABLE). LEVEL_APPROX coverage keeps the regime and marks
    the flip level approximate: how precisely the level is placed does not change the sign at
    spot. Clearing the floor is not evidence the sign is right
    (math_levels.GAMMA_FLIP_MIN_SPAN_PCT)."""
    if spot is None or spot <= 0:
        return _unavailable("Spot price is unavailable.", flip_confidence)
    if flip is None and gamma_at_spot is None:
        return _unavailable("Dealer gamma is unavailable, so the regime cannot be determined.",
                            flip_confidence)
    if flip_confidence not in (GAMMA_FLIP_TRUSTED, GAMMA_FLIP_LEVEL_APPROX):
        return _unavailable(
            f"Gamma flip is not trustworthy ({flip_confidence}) — the option chain is too "
            "narrow to place it reliably.", flip_confidence)

    # the regime is the sign of dealer gamma at spot; absent or exactly zero -> unavailable
    regime = regime_from_signed_gamma(gamma_at_spot) or REGIME_UNAVAILABLE
    if regime == REGIME_UNAVAILABLE:
        return _unavailable("Dealer gamma at spot is zero or unknown, so the regime cannot be "
                            "determined.", flip_confidence)

    # what qualifies the flip shown (or the reason there is none): a level placed on a chain too
    # narrow to place it precisely, and a curve that disagrees with Schwab's gamma at this price
    caveats = [FLIP_LEVEL_APPROXIMATE] if flip is not None and flip_confidence == GAMMA_FLIP_LEVEL_APPROX else []
    if flip_curve_agrees is False:
        caveats.append(FLIP_CURVE_DISAGREES)
    return TerrainRead(
        regime=regime,
        posture=_posture_for(regime),
        confidence=flip_confidence,
        headline=("Long gamma — chop regime. Fade the edges, do not chase breakouts."
                  if regime == REGIME_LONG_GAMMA else
                  "Short gamma — trend regime. Follow breaks, do not fade."),
        flip_caveat=" ".join(caveats),
    )
