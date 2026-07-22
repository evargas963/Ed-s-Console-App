"""Deterministic terrain read — regime/posture rules and fail-closed behaviour.

These are pure-function tests over scalar levels (spot/flip/walls), not option contracts,
so no chain fixture is involved. The rule under test is the read logic itself.
"""

from __future__ import annotations

from math_levels import GAMMA_FLIP_NARROW, GAMMA_FLIP_TRUSTED, GAMMA_FLIP_UNAVAILABLE
from terrain_read import (
    POSTURE_FADE,
    POSTURE_FOLLOW,
    POSTURE_STAND_ASIDE,
    REGIME_LONG_GAMMA,
    REGIME_SHORT_GAMMA,
    REGIME_SIGN_UNPROVEN,
    REGIME_UNAVAILABLE,
    build_terrain_read,
    dealer_sign_is_proven,
)

TRUSTED = GAMMA_FLIP_TRUSTED


def test_above_flip_is_long_gamma_and_fades() -> None:
    r = build_terrain_read(spot=750.0, flip=740.0, flip_confidence=TRUSTED,
                           put_wall=735.0, call_wall=760.0, ticker="SPY")
    assert r.regime == REGIME_LONG_GAMMA
    assert r.posture == POSTURE_FADE
    assert "do not chase" in r.headline.lower()


def test_below_flip_is_short_gamma_and_follows() -> None:
    r = build_terrain_read(spot=743.29, flip=745.61, flip_confidence=TRUSTED,
                           put_wall=740.0, call_wall=745.0, ticker="SPY")
    assert r.regime == REGIME_SHORT_GAMMA
    assert r.posture == POSTURE_FOLLOW
    assert "do not fade" in r.headline.lower()


def test_single_name_regime_is_withheld_but_levels_stand() -> None:
    """SIGN-DEMOTION (operator-approved 2026-07-22): a resolvable regime on a
    single name is WITHHELD — no posture, no trend/chop verdict — while walls,
    flip landmark, and position line still render."""
    r = build_terrain_read(spot=325.0, flip=320.0, flip_confidence=TRUSTED,
                           put_wall=318.0, call_wall=330.0, ticker="AAPL")
    assert r.regime == REGIME_SIGN_UNPROVEN
    assert r.posture == POSTURE_STAND_ASIDE
    assert "unproven" in r.headline.lower()
    text = r.as_text()
    assert "318.00" in text and "330.00" in text      # walls still shown
    assert "landmark only" in text                     # flip kept, meaning withheld
    assert "fade" not in r.headline.lower() and "follow" not in r.headline.lower()


def test_sentinels_keep_regime_single_names_do_not() -> None:
    assert dealer_sign_is_proven("SPY") and dealer_sign_is_proven("qqq")
    assert not dealer_sign_is_proven("AAPL")
    assert not dealer_sign_is_proven(None)             # fail-closed: unknown demotes
    assert not dealer_sign_is_proven("")


def test_missing_ticker_fails_closed_to_sign_unproven() -> None:
    """A call site that forgets the ticker must DEMOTE, never promote."""
    r = build_terrain_read(spot=750.0, flip=740.0, flip_confidence=TRUSTED,
                           put_wall=735.0, call_wall=760.0)
    assert r.regime == REGIME_SIGN_UNPROVEN
    assert r.posture == POSTURE_STAND_ASIDE


def test_untrusted_flip_withholds_regime_and_posture() -> None:
    """Fail-closed: an unreliable level must never yield a trading posture."""
    r = build_terrain_read(spot=743.72, flip=770.35, flip_confidence=GAMMA_FLIP_NARROW,
                           put_wall=740.0, call_wall=745.0)
    assert r.regime == REGIME_UNAVAILABLE
    assert r.posture == POSTURE_STAND_ASIDE
    assert GAMMA_FLIP_NARROW in r.as_text()
    # levels are still surfaced, but explicitly marked untrusted
    assert "untrusted" in r.as_text().lower()


def test_missing_inputs_fail_closed() -> None:
    for spot, flip, conf in (
        (None, 740.0, TRUSTED),
        (0.0, 740.0, TRUSTED),
        (750.0, None, GAMMA_FLIP_UNAVAILABLE),
    ):
        r = build_terrain_read(spot=spot, flip=flip, flip_confidence=conf)
        assert r.regime == REGIME_UNAVAILABLE
        assert r.posture == POSTURE_STAND_ASIDE


def test_edge_detection_at_each_wall() -> None:
    upper = build_terrain_read(spot=744.9, flip=740.0, flip_confidence=TRUSTED,
                               put_wall=740.0, call_wall=745.0)
    assert "upper edge" in upper.as_text().lower()
    lower = build_terrain_read(spot=740.1, flip=735.0, flip_confidence=TRUSTED,
                               put_wall=740.0, call_wall=760.0)
    assert "lower edge" in lower.as_text().lower()


def test_mid_box_is_an_explicit_stand_aside_note() -> None:
    r = build_terrain_read(spot=750.0, flip=740.0, flip_confidence=TRUSTED,
                           put_wall=735.0, call_wall=765.0)
    assert "mid-box" in r.as_text().lower()
    assert "stand aside" in r.as_text().lower()


def test_missing_wall_reports_absence_not_a_default() -> None:
    """Absence must read as absence — never a fabricated neutral number."""
    r = build_terrain_read(spot=750.0, flip=740.0, flip_confidence=TRUSTED,
                           put_wall=None, call_wall=765.0)
    assert "unavailable" in r.as_text().lower()
    assert r.put_wall is None


def test_read_is_deterministic() -> None:
    kw = dict(spot=743.29, flip=745.61, flip_confidence=TRUSTED,
              put_wall=740.0, call_wall=745.0)
    assert build_terrain_read(**kw).as_text() == build_terrain_read(**kw).as_text()
