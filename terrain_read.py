"""Deterministic terrain read — plain-English regime summary from computed levels.

Rules-based, never generative: identical inputs always produce identical output, so the
read can be tested, diffed, and trusted. There is no model in this path and nothing here
can hallucinate a level.

Two institutional invariants:

1. **Fail-closed.** When the flip is missing or its confidence is not TRUSTED, the read
   withholds the regime and the trading posture and says why. It never presents a posture
   derived from a level we know is unreliable (a narrow chain misplaces the flip by ~3.6%
   — measured 2026-07-19: 770.35 against a full-chain reference of 745.61).
2. **Absence reads as absence.** A missing level is reported missing, never defaulted to a
   neutral-looking number.

The vocabulary mirrors how the terrain is actually traded: regime first (the master
switch), then the box, then position within it. The middle of the box is an explicit
stand-aside — no edge exists there.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from math_levels import GAMMA_FLIP_TRUSTED

REGIME_LONG_GAMMA = "LONG_GAMMA_CHOP"
REGIME_SHORT_GAMMA = "SHORT_GAMMA_TREND"
REGIME_UNAVAILABLE = "UNAVAILABLE"

POSTURE_FADE = "FADE_EDGES"
POSTURE_FOLLOW = "FOLLOW_BREAKS"
POSTURE_STAND_ASIDE = "STAND_ASIDE"

#: Within this fraction of a wall, price is "at the edge" and the reaction is tradeable.
EDGE_PROXIMITY_PCT = 0.004


@dataclass(frozen=True)
class TerrainRead:
    """Structured, renderable terrain read. `lines` is ordered for display."""

    regime: str
    posture: str
    confidence: str
    headline: str
    lines: list[str] = field(default_factory=list)
    spot: float | None = None
    flip: float | None = None
    put_wall: float | None = None
    call_wall: float | None = None

    def as_text(self) -> str:
        return "\n".join([self.headline, *self.lines])


def _pct_from(spot: float, level: float) -> float:
    return (level - spot) / spot


def _fmt(label: str, level: float | None, spot: float) -> str:
    if level is None:
        return f"{label}: unavailable"
    return f"{label} {level:.2f} ({_pct_from(spot, level) * 100:+.2f}%)"


def _regime_for(spot: float, flip: float | None, gamma_at_spot: float | None) -> str:
    """Regime = sign of dealer gamma at spot. Falls back to spot-vs-flip only when the
    signed value is unavailable (the two always agree when both are present)."""
    if gamma_at_spot is not None and gamma_at_spot != 0:
        return REGIME_LONG_GAMMA if gamma_at_spot > 0 else REGIME_SHORT_GAMMA
    if flip is not None:
        return REGIME_LONG_GAMMA if spot > flip else REGIME_SHORT_GAMMA
    return REGIME_UNAVAILABLE


def _posture_for(regime: str) -> str:
    if regime == REGIME_LONG_GAMMA:
        return POSTURE_FADE
    if regime == REGIME_SHORT_GAMMA:
        return POSTURE_FOLLOW
    return POSTURE_STAND_ASIDE


def _near(spot: float, level: float | None) -> bool:
    return level is not None and abs(_pct_from(spot, level)) <= EDGE_PROXIMITY_PCT


def _position_line(spot: float, put_wall: float | None, call_wall: float | None) -> str:
    if _near(spot, put_wall):
        return "At the lower edge — wait for the reaction at the put wall, do not anticipate."
    if _near(spot, call_wall):
        return "At the upper edge — wait for the reaction at the call wall, do not anticipate."
    if put_wall is not None and call_wall is not None:
        return "Mid-box — no edge here. Stand aside; act at the walls, not in the middle."
    return "Box incomplete — at least one wall is unavailable."


def _unavailable(reason: str, spot: float | None, confidence: str,
                 put_wall: float | None, call_wall: float | None) -> TerrainRead:
    lines = [reason, "No regime and no posture are issued while the levels are unreliable."]
    if spot is not None and (put_wall is not None or call_wall is not None):
        lines.append(
            f"Levels seen (untrusted): {_fmt('put wall', put_wall, spot)} · "
            f"{_fmt('call wall', call_wall, spot)}"
        )
    return TerrainRead(
        regime=REGIME_UNAVAILABLE,
        posture=POSTURE_STAND_ASIDE,
        confidence=confidence,
        headline="Terrain unavailable — stand aside.",
        lines=lines,
        spot=spot,
        put_wall=put_wall,
        call_wall=call_wall,
    )


def build_terrain_read(
    *,
    spot: float | None,
    flip: float | None,
    flip_confidence: str,
    put_wall: float | None = None,
    call_wall: float | None = None,
    gamma_at_spot: float | None = None,
) -> TerrainRead:
    """Deterministic terrain read. Fail-closed on missing spot or untrusted levels.

    The regime comes from the SIGN OF DEALER GAMMA AT SPOT (`gamma_at_spot`), not from
    comparing spot to the flip. Corrected 2026-07-19 (RC-11): requiring a flip meant a
    chain whose profile never crosses zero reported "unavailable" even though its regime
    was unambiguous at every price. The flip is a landmark to display when it exists.
    """
    if spot is None or spot <= 0:
        return _unavailable("Spot price is unavailable.", None, flip_confidence, None, None)
    if flip is None and gamma_at_spot is None:
        return _unavailable("Dealer gamma is unavailable, so the regime cannot be determined.",
                            spot, flip_confidence, put_wall, call_wall)
    if flip_confidence != GAMMA_FLIP_TRUSTED:
        return _unavailable(
            f"Gamma flip is not trustworthy ({flip_confidence}) — the option chain is too "
            "narrow to place it reliably.",
            spot, flip_confidence, put_wall, call_wall,
        )

    regime = _regime_for(spot, flip, gamma_at_spot)
    posture = _posture_for(regime)

    if regime == REGIME_LONG_GAMMA:
        headline = "Long gamma — chop regime. Fade the edges, do not chase breakouts."
        mechanism = ("Dealers are net long gamma: they sell into strength and buy into "
                     "weakness, damping every move.")
        action = (f"Fade rallies into {_fmt('call wall', call_wall, spot)} and buy dips toward "
                  f"{_fmt('put wall', put_wall, spot)}; target the middle, stop beyond the wall.")
    else:
        headline = "Short gamma — trend regime. Follow breaks, do not fade."
        mechanism = ("Dealers are net short gamma: they buy strength and sell weakness, "
                     "amplifying every move.")
        action = (f"Trade with a break of {_fmt('put wall', put_wall, spot)} or "
                  f"{_fmt('call wall', call_wall, spot)}; fading here gets run over.")

    if flip is not None:
        distance_pct = _pct_from(spot, flip) * 100.0
        flip_line = (f"Spot {spot:.2f} vs {_fmt('flip', flip, spot)} — {abs(distance_pct):.2f}% "
                     f"{'above' if spot > flip else 'below'} the regime line.")
    else:
        flip_line = (f"Spot {spot:.2f} — dealer gamma holds one sign across the whole chain, "
                     f"so there is no flip nearby to cross. The regime is unambiguous.")

    lines = [
        mechanism,
        flip_line,
        f"Box: {_fmt('put wall', put_wall, spot)} · {_fmt('call wall', call_wall, spot)}",
        _position_line(spot, put_wall, call_wall),
        action,
    ]
    return TerrainRead(
        regime=regime,
        posture=posture,
        confidence=flip_confidence,
        headline=headline,
        lines=lines,
        spot=spot,
        flip=flip,
        put_wall=put_wall,
        call_wall=call_wall,
    )
