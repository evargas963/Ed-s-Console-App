"""Deterministic terrain read — regime/posture rules and fail-closed behaviour.

These are pure-function tests over scalar levels (spot/flip/walls), not option contracts,
so no chain fixture is involved. The rule under test is the read logic itself.
"""

from __future__ import annotations

from math_levels import GAMMA_FLIP_TRUSTED, GAMMA_FLIP_UNAVAILABLE
from terrain_read import (
    POSTURE_FADE,
    POSTURE_FOLLOW,
    POSTURE_STAND_ASIDE,
    REGIME_LONG_GAMMA,
    REGIME_SHORT_GAMMA,
    REGIME_UNAVAILABLE,
    build_terrain_read,
)

TRUSTED = GAMMA_FLIP_TRUSTED


def test_above_flip_is_long_gamma_and_fades() -> None:
    r = build_terrain_read(spot=750.0, flip=740.0, flip_confidence=TRUSTED,
                           put_wall=735.0, call_wall=760.0, gamma_at_spot=2.5e8)
    assert r.regime == REGIME_LONG_GAMMA
    assert r.posture == POSTURE_FADE
    assert "do not chase" in r.headline.lower()


def test_below_flip_is_short_gamma_and_follows() -> None:
    r = build_terrain_read(spot=743.29, flip=745.61, flip_confidence=TRUSTED,
                           put_wall=740.0, call_wall=745.0, gamma_at_spot=-1.1e8)
    assert r.regime == REGIME_SHORT_GAMMA
    assert r.posture == POSTURE_FOLLOW
    assert "do not fade" in r.headline.lower()




def test_regime_is_the_signed_gamma_at_spot_only() -> None:
    """T-07 (2026-09-24): no spot-vs-flip fallback. No signed gamma, or exactly zero (spot
    AT the flip), is no regime -- not a side picked from the flip."""
    for g in (None, 0.0):
        r = build_terrain_read(spot=750.0, flip=740.0, flip_confidence=TRUSTED,
                               put_wall=735.0, call_wall=760.0, gamma_at_spot=g)
        assert r.regime not in (REGIME_LONG_GAMMA, REGIME_SHORT_GAMMA), g




def test_missing_inputs_fail_closed() -> None:
    for spot, flip, conf in (
        (None, 740.0, TRUSTED),
        (0.0, 740.0, TRUSTED),
        (750.0, None, GAMMA_FLIP_UNAVAILABLE),
    ):
        r = build_terrain_read(spot=spot, flip=flip, flip_confidence=conf)
        assert r.regime == REGIME_UNAVAILABLE
        assert r.posture == POSTURE_STAND_ASIDE


def test_the_regime_is_read_by_one_rule_for_every_instrument(pin_clock):
    """All tickers (operator 2026-09-23, "show for all tickers"): the regime is the sign of
    Schwab's gamma at spot wherever the chain covers spot well enough to know it, for an ETF and
    a single name alike; a single name's regime was once withheld (SIGN-DEMOTION) and the
    argument that carried the ticker in stayed behind, dead. Real Schwab chains (tests/fixtures),
    each valued at its own capture: SPY's 0DTE chain is too narrow for the sign (withheld, the
    coverage rule); CRWD's complete chain is trusted (issued)."""
    import json
    from pathlib import Path

    from math_levels import GAMMA_FLIP_NARROW
    from terrain_engine import compute_terrain
    fx = Path(__file__).resolve().parent / "fixtures"
    got = {}
    for name, tk, at in (("real_spy_0dte_chain.json", "SPY", (2026, 9, 22, 12, 46)),
                         ("real_crwd_complete_chain_quarter.json", "CRWD", (2026, 9, 2, 12, 0))):
        pin_clock(*at)
        d = json.loads((fx / name).read_text(encoding="utf-8"))
        snap = compute_terrain(tk, [dict(c) for c in d["chain"]], float(d["spot"]))
        g = snap.flip_diag.get("gamma_at_spot")
        got[tk] = (snap.confidence, snap.regime)
        if snap.confidence in (GAMMA_FLIP_NARROW, GAMMA_FLIP_UNAVAILABLE) or not g:
            assert snap.regime == REGIME_UNAVAILABLE, tk
        else:
            assert snap.regime == (REGIME_LONG_GAMMA if g > 0 else REGIME_SHORT_GAMMA), tk
    assert got["CRWD"][1] != REGIME_UNAVAILABLE, "a single name's regime is issued"








