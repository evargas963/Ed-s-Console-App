"""Gamma audit 2026-08-26 — the flip TRUSTED label must be earned by the measured convergence span.

OPERATOR CONCERN (confirmed): a chain covering only ±5% was labeled TRUSTED even though the
console's own convergence study (tools/study_flip_span_convergence_v1.py, quoted in
math_levels.GAMMA_FLIP_MIN_SPAN_PCT's provenance) measured the flip error at 1.38% of spot there —
~10x the 0.117% at ±10%, and concluded "0.05 is measurably INSUFFICIENT".

ROOT CAUSE: one constant did double duty — the chain-FETCH width (a cost/latency decision) and the
flip-LEVEL trust verdict. Only the latter is refuted by the study.

WHY GRADUATED, NOT JUST RAISED — and a CORRECTION to this docstring's first version, which cited the
WRONG POPULATION. It claimed "SPY (median 8.49%) and QQQ (8.84%)" fall below the bar, so a binary
raise would dark the two primary instruments. Those were option_chain_morning_full ARCHIVE captures,
NOT the production terrain chain. Re-measured against the LIVE fetch (2026-08-26): SPY 29.4%, QQQ
29.5%, IWM 29.8%, NVDA 21.7% — every production chain clears the bar with ~3x headroom. The
dark-the-board risk did not exist.

The graduated tier is KEPT anyway, on its own merit: it is the honest verdict for a chain that
genuinely lands between the floor and the bar, because the REGIME is the sign of dealer gamma AT
SPOT (it needs strikes near spot, not a wide wing) while only the flip LEVEL needs the wide span.
That case is real; it simply is not SPY/QQQ's today.

These tests therefore pin the SEMANTICS (which verdict a given span earns, and what each verdict
permits), not the population — so they stay valid whichever chains production happens to deliver.
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from math_levels import (
    GAMMA_FLIP_LEVEL_APPROX,
    GAMMA_FLIP_MIN_SPAN_PCT,
    GAMMA_FLIP_NARROW,
    GAMMA_FLIP_TRUSTED,
    GAMMA_FLIP_TRUSTED_SPAN_PCT,
    compute_gamma_flip_v2,
)
from terrain_read import build_terrain_read


def _chain(span: float, spot: float = 100.0, n: int = 41):
    # institutional-synthetic-ok: a span-threshold discriminator needs chains built at EXACT
    # controlled spans around spot; no captured chain can be pinned to ±3%/±6%/±12% on demand.
    lo, hi = spot * (1 - span), spot * (1 + span)
    out = []
    for i in range(n):
        k = lo + (hi - lo) * i / (n - 1)
        for side in ("CALL", "PUT"):
            out.append({"strikePrice": round(k, 2), "putCall": side, "openInterest": 100,
                        "multiplier": 100, "volatility": 20.0, "daysToExpiration": 30,
                        "expirationDate": "2030-01-18T00:00:00.000+00:00"})
    return out


def test_trusted_requires_the_measured_convergence_span():
    """±5%-class coverage must NOT be TRUSTED (the defect); the convergence span must be."""
    assert GAMMA_FLIP_TRUSTED_SPAN_PCT > GAMMA_FLIP_MIN_SPAN_PCT, (
        "the flip-LEVEL trust bar must be strictly above the fetch-width floor, or the two are "
        "conflated again and the fetch compromise sets the trust bar")
    _, conf_5, _ = compute_gamma_flip_v2(_chain(0.055), 100.0)
    assert conf_5 != GAMMA_FLIP_TRUSTED, (
        f"a ~±5% chain must not be TRUSTED — the study measured 1.38%-of-spot error there; got {conf_5}")
    _, conf_wide, _ = compute_gamma_flip_v2(_chain(0.12), 100.0)
    assert conf_wide == GAMMA_FLIP_TRUSTED, f"a ±12% chain should be TRUSTED, got {conf_wide}"


def test_three_tiers_are_ordered_by_span():
    below, mid, above = (compute_gamma_flip_v2(_chain(s), 100.0)[1] for s in (0.03, 0.07, 0.15))
    assert below == GAMMA_FLIP_NARROW, below
    assert mid == GAMMA_FLIP_LEVEL_APPROX, mid
    assert above == GAMMA_FLIP_TRUSTED, above


def test_regime_survives_the_middle_tier_but_level_is_disclosed_approximate():
    """SPY/QQQ class (~8-9% span): the regime must STILL be issued — its basis is the sign of gamma
    at spot, independent of flip-level precision — while the flip LEVEL says it is approximate."""
    read = build_terrain_read(
        spot=100.0, flip=99.0, flip_confidence=GAMMA_FLIP_LEVEL_APPROX,
        put_wall=95.0, call_wall=105.0, gamma_at_spot=5.0e9, ticker="SPY",
    )
    assert read.regime, "the regime must survive the middle tier (its basis is the at-spot sign)"
    assert read.posture, "posture accompanies a resolved regime"
    joined = " ".join(read.lines)
    assert "APPROXIMATE" in joined, f"the flip level must be disclosed as approximate: {read.lines}"


def test_a_chain_too_narrow_for_the_at_spot_sign_still_stands_everything_aside():
    read = build_terrain_read(
        spot=100.0, flip=99.0, flip_confidence=GAMMA_FLIP_NARROW,
        put_wall=95.0, call_wall=105.0, gamma_at_spot=5.0e9, ticker="SPY",
    )
    assert not read.regime or read.regime in ("", None) or "not trustworthy" in " ".join(read.lines), (
        f"a NARROW chain must not issue a regime: {read.regime} / {read.lines}")


def test_regime_wording_discloses_the_modeled_dealer_sign():
    """Operator requirement: modeled dealer positioning must not read as observed fact."""
    read = build_terrain_read(
        spot=100.0, flip=99.0, flip_confidence=GAMMA_FLIP_TRUSTED,
        put_wall=95.0, call_wall=105.0, gamma_at_spot=5.0e9, ticker="SPY",
    )
    mech = " ".join(read.lines)
    assert "modelled" in mech.lower(), f"the mechanism line must disclose the modeled sign: {mech}"
