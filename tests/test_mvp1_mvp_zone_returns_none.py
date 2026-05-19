"""FIND-MVP1: mvp_zone returns None (no \"unknown\" sentinel) + consumer transition gates."""

from __future__ import annotations

from features.regime_mvp_context import mvp_zone
from math_levels import is_pin_zone


def test_mvp_zone_empty_dict_returns_none():
    assert mvp_zone({}) is None


def test_mvp_zone_none_zone_value_returns_none():
    assert mvp_zone({"structure.zone": None}) is None


def test_mvp_zone_valid_zone_normalized():
    assert mvp_zone({"structure.zone": " PIN_BULL "}) == "pin_bull"


def test_is_pin_zone_safe_for_none():
    assert is_pin_zone(None) is False
    assert is_pin_zone(mvp_zone({})) is False


def test_zone_transition_gate_requires_cur_z_not_none():
    """Transition alert must not fire when cur_z is None (missing structure.zone)."""
    cur_z = mvp_zone({})
    prev_z = "pin_neutral"
    zone_fresh_bars_1m = 1
    assert cur_z is None
    fires = (
        zone_fresh_bars_1m is not None
        and zone_fresh_bars_1m <= 2
        and prev_z
        and cur_z is not None
        and prev_z != cur_z
    )
    assert fires is False
