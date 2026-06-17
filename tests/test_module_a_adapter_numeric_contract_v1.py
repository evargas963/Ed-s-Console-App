"""AUDIT_LANE module_a_adapter — fusion provenance + finite numerics."""

from __future__ import annotations

from v2_decision.a1_raw_probability import dominant_probability
from fusion_contract import is_ms_dict_fusion_authoritative
from v2_decision.module_a_adapter import (
    _decision_block,
    _desk_confidence_value,
    _direction,
    _position_size_fraction,
)
from signal_types import NON_TRADABLE_CANONICAL_PROVENANCE


def test_fusion_ms_authoritative_rejects_non_tradable_provenance():
    prov = next(iter(NON_TRADABLE_CANONICAL_PROVENANCE))
    ms = {"fusion_available": True, "canonical_provenance": prov}
    assert is_ms_dict_fusion_authoritative(ms) is False


def test_direction_uses_dominant_dir_when_fusion_provenance_non_tradable():
    prov = next(iter(NON_TRADABLE_CANONICAL_PROVENANCE))
    ms = {
        "fusion_available": True,
        "fusion_dominant_direction": "up",
        "canonical_provenance": prov,
        "dominant_dir": "down",
    }
    assert _direction(ms) == "short"


def test_desk_confidence_rejects_nan():
    assert _desk_confidence_value({"final_confidence": float("nan")}) is None
    assert _desk_confidence_value({"final_confidence": 0.42}) == 0.42


def test_position_size_rejects_nan():
    assert _position_size_fraction({"r_units": float("nan")}) is None
    assert _position_size_fraction({"r_units": 1.25}) == 1.25


def test_dominant_probability_skips_non_tradable_fusion_prob():
    prov = next(iter(NON_TRADABLE_CANONICAL_PROVENANCE))
    ms = {
        "fusion_available": True,
        "fusion_dominant_prob": 0.99,
        "canonical_provenance": prov,
        "dominant_prob": 0.25,
    }
    assert dominant_probability(ms) == 0.25


def test_dominant_probability_rejects_nan_and_does_not_use_final_confidence():
    ms = {"dominant_prob": float("nan"), "final_confidence": 0.5}
    assert dominant_probability(ms) is None


def test_decision_probability_none_when_all_candidates_non_finite():
    block = _decision_block({"dominant_prob": float("nan"), "final_confidence": float("inf")})
    assert block["probability"]["value"] is None
    assert block["P_entry_success"]["value"] is None
