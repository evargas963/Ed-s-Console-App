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
    REGIME_UNAVAILABLE,
    build_terrain_read,
)

TRUSTED = GAMMA_FLIP_TRUSTED


def test_above_flip_is_long_gamma_and_fades() -> None:
    r = build_terrain_read(spot=750.0, flip=740.0, flip_confidence=TRUSTED,
                           put_wall=735.0, call_wall=760.0)
    assert r.regime == REGIME_LONG_GAMMA
    assert r.posture == POSTURE_FADE
    assert "do not chase" in r.headline.lower()


def test_below_flip_is_short_gamma_and_follows() -> None:
    r = build_terrain_read(spot=743.29, flip=745.61, flip_confidence=TRUSTED,
                           put_wall=740.0, call_wall=745.0)
    assert r.regime == REGIME_SHORT_GAMMA
    assert r.posture == POSTURE_FOLLOW
    assert "do not fade" in r.headline.lower()


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
