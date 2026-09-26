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
     * missing spot, or BOTH flip and at-spot gamma missing -> withheld for the same reason.
       (Precise, because an earlier version of this line said "or no at-spot gamma" and was WRONG:
       the guard is `flip is None AND gamma_at_spot is None`. With a flip present and gamma_at_spot
       None, `_regime_for` deliberately falls back to spot-vs-flip and a regime IS issued. That
       state is not reachable from any caller in this repo — compute_gamma_flip_v2 returns
       UNAVAILABLE when the at-spot value is absent — but the invariant must describe the guard
       that exists, not a stricter one a reader would rely on.)
   It never presents a posture derived from a level we know is unreliable (a narrow chain
   misplaces the flip by ~3.6% — measured 2026-07-19: 770.35 against a full-chain reference of
   745.61), and it never presents a coverage verdict as proof the level is right.
2. **Absence reads as absence.** A missing level is reported missing, never defaulted to a
   neutral-looking number.

The vocabulary mirrors how the terrain is actually traded: regime first (the master
switch), then the box, then position within it. The middle of the box is an explicit
stand-aside — no edge exists there.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from math_levels import GAMMA_FLIP_LEVEL_APPROX, GAMMA_FLIP_TRUSTED

REGIME_LONG_GAMMA = "LONG_GAMMA_CHOP"
REGIME_SHORT_GAMMA = "SHORT_GAMMA_TREND"
REGIME_UNAVAILABLE = "UNAVAILABLE"
#: UNIVERSALITY (operator 2026-09-23: "show for all tickers"): the regime and posture are
#: read the same way for every ticker. They used to be withheld (SIGN_UNPROVEN) for every
#: ticker but SPY/QQQ/IWM because the +call/-put dealer-sign convention was only evidenced on
#: those three. The convention is still MODELLED, not observed -- the mechanism line below
#: says so on every ticker (governance/unproven_register.md keeps the open evidence row).

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



def _pct_from(spot: float, level: float) -> float:
    return (level - spot) / spot


def _fmt(label: str, level: float | None, spot: float) -> str:
    if level is None:
        return f"{label}: unavailable"
    return f"{label} {level:.2f} ({_pct_from(spot, level) * 100:+.2f}%)"


def regime_from_signed_gamma(signed_gamma: float | None) -> str | None:
    """THE authority for the gamma-regime SIGN THRESHOLD (RC-345 / F07). Positive dealer
    gamma is LONG_GAMMA_CHOP (dealers damp moves); negative is SHORT_GAMMA_TREND (dealers
    amplify). Returns None when the sign is absent or exactly zero, so every caller shares
    one threshold instead of re-deriving `> 0` locally. `_regime_for` and
    institutional_behavior both consume this — there is no second sign authority."""
    if signed_gamma is None or signed_gamma == 0:
        return None
    return REGIME_LONG_GAMMA if signed_gamma > 0 else REGIME_SHORT_GAMMA


def _regime_for(spot: float, flip: float | None, gamma_at_spot: float | None) -> str:
    """Regime = sign of dealer gamma at spot -- the one derivation. Absent or exactly zero
    (spot AT the flip) -> unavailable. It used to fall back to spot-vs-flip, which at a zero
    gamma picked a side of a boundary spot is sitting on, and with no signed value read a
    flip that did not come from the same curve (audit T-07, 2026-09-24: no fallbacks).
    `flip` stays in the signature for the callers that pass it."""
    signed = regime_from_signed_gamma(gamma_at_spot)
    return signed if signed is not None else REGIME_UNAVAILABLE


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
    ticker: str | None = None,
) -> TerrainRead:
    """Deterministic terrain read. Fail-closed on missing spot, or on coverage below the
    conservative floor at which this repo declines to speak at all (NARROW / UNAVAILABLE).

    That floor is NOT evidence that the sign is otherwise sound — see
    math_levels.GAMMA_FLIP_MIN_SPAN_PCT for the measurement that withdrew that claim.

    NOT "fail-closed on untrusted levels" — corrected 2026-08-26. LEVEL_APPROX is untrusted by
    construction (it is named so no surface can print it as TRUSTED) and it deliberately PASSES:
    its regime and posture are issued, and the flip LEVEL it prints carries an explicit
    APPROXIMATE disclosure. What fails closed is the SIGN being unsupportable, not the level
    being uncertified.

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
    # Gamma audit 2026-08-26: the REGIME is the sign of dealer gamma AT SPOT (see this function's
    # docstring) — it does NOT depend on how precisely the flip LEVEL is placed. Gating it on the
    # level-trust verdict conflates two different questions: coverage wide enough to PLACE the flip
    # level, versus enough strikes near spot to know its SIGN. (An earlier version of this comment
    # justified the split with "SPY/QQQ measured 8.49%/8.84%" — that was the ARCHIVE capture, not the
    # production chain; live spans are ~29%, so no ticker was actually at risk. The split stands on
    # the semantic argument above, which does not depend on any ticker's current span.)
    # So the middle tier LEVEL_APPROX keeps the regime and posture, and discloses the LEVEL below.
    # Only a chain below the conservative decline-to-speak floor (NARROW/UNAVAILABLE) stands aside.
    # NOTE (measured 2026-08-26): clearing that floor does NOT mean the at-spot sign is verified.
    # What was measured is agreement between the MODELLED +call/-put sign on a truncated window and
    # the MODELLED sign on the full delivered chain — both sides modelled, so this bounds truncation
    # sensitivity, not correctness against real dealer positioning. Agreement improves with width
    # (79.8% at +/-1% up to 92.7% at +/-15%), but that trend is SUPPORTED, NOT PROVEN: adjacent rungs
    # overlap, the rungs re-window largely the same chains (paired observations), and no paired test
    # or power analysis was run. There is no visible threshold effect at the floor, so passing it
    # certifies nothing. Separately, AT THE FLOOR ONLY, a nearly balanced book (net/gross < 10%) sat
    # near 50%; whether width rescues such a book is UNMEASURED. Recorded in unproven_register as
    # research-only; deliberately NOT gated on here — changing when advice is withheld is the
    # operator's call, not a silent threshold edit from one study.
    if flip_confidence not in (GAMMA_FLIP_TRUSTED, GAMMA_FLIP_LEVEL_APPROX):
        return _unavailable(
            f"Gamma flip is not trustworthy ({flip_confidence}) — the option chain is too "
            "narrow to place it reliably.",
            spot, flip_confidence, put_wall, call_wall,
        )

    regime = _regime_for(spot, flip, gamma_at_spot)
    posture = _posture_for(regime)

    # Gamma-audit (operator requirement): dealer positioning is MODELLED from public OI under the
    # +call/-put convention — OI does not reveal who owns the contracts — so the mechanism line says
    # "modelled net long/short", never a bare "Dealers ARE" -- on every ticker alike, which keeps
    # the claim honest rather than certain.
    if regime == REGIME_LONG_GAMMA:
        headline = "Long gamma — chop regime. Fade the edges, do not chase breakouts."
        mechanism = ("Dealers are modelled net long gamma (from OI, not observed positioning): "
                     "they sell into strength and buy into weakness, damping every move.")
        action = (f"Fade rallies into {_fmt('call wall', call_wall, spot)} and buy dips toward "
                  f"{_fmt('put wall', put_wall, spot)}; target the middle, stop beyond the wall.")
    else:
        headline = "Short gamma — trend regime. Follow breaks, do not fade."
        mechanism = ("Dealers are modelled net short gamma (from OI, not observed positioning): "
                     "they buy strength and sell weakness, amplifying every move.")
        action = (f"Trade with a break of {_fmt('put wall', put_wall, spot)} or "
                  f"{_fmt('call wall', call_wall, spot)}; fading here gets run over.")

    if flip is not None:
        distance_pct = _pct_from(spot, flip) * 100.0
        flip_line = (f"Spot {spot:.2f} vs {_fmt('flip', flip, spot)} — {abs(distance_pct):.2f}% "
                     f"{'above' if spot > flip else 'below'} the regime line.")
        # Gamma audit: at the middle tier the chain does not reach the measured flip-LEVEL
        # convergence span, so the LEVEL is approximate (~1.4% of spot in the study) even though the
        # regime is sound. Say so on the same line the operator reads the number from — a precise
        # "-0.42%" beside an unqualified level is exactly the overstatement this tier exists to end.
        if flip_confidence == GAMMA_FLIP_LEVEL_APPROX:
            flip_line += (" APPROXIMATE: the chain is too narrow to place this level precisely "
                          "(~1.4% of spot); the regime above does not depend on it.")
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
