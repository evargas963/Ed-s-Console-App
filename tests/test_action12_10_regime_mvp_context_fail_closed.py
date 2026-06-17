"""Action 12.10: regime_mvp_context must not fabricate anchor.vwap_side."""

from __future__ import annotations

from types import SimpleNamespace

from features.regime_mvp_context import mvp_vwap_side
from rules_engine import _derive_bias_from_micro
from micro_structure import R_RANGE


def test_mvp_vwap_side_returns_none_when_missing():
    assert mvp_vwap_side({}) is None
    assert mvp_vwap_side({"anchor.vwap_side": None}) is None


def test_mvp_vwap_side_returns_none_for_invalid_string():
    assert mvp_vwap_side({"anchor.vwap_side": "sideways"}) is None
    assert mvp_vwap_side({"anchor.vwap_side": ""}) is None


def test_mvp_vwap_side_accepts_above_below():
    assert mvp_vwap_side({"anchor.vwap_side": "above"}) == "above"
    assert mvp_vwap_side({"anchor.vwap_side": " BELOW "}) == "below"


def test_rules_engine_range_regime_waits_when_vwap_side_none():
    micro = SimpleNamespace(regime=R_RANGE)
    sig, conv = _derive_bias_from_micro(
        micro=micro,
        approaching_ceiling=False,
        approaching_floor=False,
        near_inflection=False,
        vwap_side=None,
        zone="pin_neutral",
    )
    assert sig == "wait"
    assert conv == "low"


def test_rules_engine_range_regime_long_only_when_vwap_above():
    micro = SimpleNamespace(regime=R_RANGE)
    sig, _ = _derive_bias_from_micro(
        micro=micro,
        approaching_ceiling=False,
        approaching_floor=False,
        near_inflection=False,
        vwap_side="above",
        zone="pin_neutral",
    )
    assert sig == "long"
