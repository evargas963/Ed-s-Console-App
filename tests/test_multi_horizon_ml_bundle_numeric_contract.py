"""FIND-MHMLB-1/2/3: multi_horizon_ml_bundle numeric_contract + triplet authority."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from multi_horizon_ml_bundle import fusion_payload_to_horizon_snapshot


def test_nan_prob_up_yields_unavailable_snapshot():
    fus = SimpleNamespace(
        available=True,
        stack_directional_authorized=True,
        prob_up=float("nan"),
        prob_down=0.2,
        prob_flat=0.2,
        dominant_direction="up",
        fusion_confidence="high",
        fusion_confidence_score=0.9,
        mc_available=True,
        contributing_models=["xgb"],
        missing_models=[],
    )
    snap = fusion_payload_to_horizon_snapshot("1c", fus)
    assert snap.horizon_fusion_available is False
    assert snap.provenance == "fusion_unavailable_non_finite_probs"
    assert snap.dominant_direction == "flat"


def test_dominant_direction_from_triplet_not_upstream_label():
    fus = SimpleNamespace(
        available=True,
        stack_directional_authorized=True,
        prob_up=0.1,
        prob_down=0.7,
        prob_flat=0.2,
        dominant_direction="up",
        fusion_confidence="medium",
        fusion_confidence_score=0.5,
        mc_available=False,
        contributing_models=[],
        missing_models=[],
    )
    snap = fusion_payload_to_horizon_snapshot("5c", fus)
    assert snap.horizon_fusion_available is True
    assert snap.dominant_direction == "down"
    assert snap.prob_down == pytest.approx(0.7)


def test_renormalized_triplet_stamps_provenance():
    fus = SimpleNamespace(
        available=True,
        stack_directional_authorized=True,
        prob_up=0.8,
        prob_down=0.8,
        prob_flat=0.8,
        dominant_direction="flat",
        fusion_confidence="low",
        fusion_confidence_score=0.1,
        mc_available=False,
        contributing_models=[],
        missing_models=[],
    )
    snap = fusion_payload_to_horizon_snapshot("15c", fus)
    assert snap.provenance == "bayesian_fusion_renormalized"
    assert snap.prob_up == pytest.approx(1.0 / 3.0)


def test_already_normalized_triplet_keeps_bayesian_fusion_provenance():
    fus = SimpleNamespace(
        available=True,
        stack_directional_authorized=True,
        prob_up=0.5,
        prob_down=0.3,
        prob_flat=0.2,
        dominant_direction="up",
        fusion_confidence="high",
        fusion_confidence_score=0.8,
        mc_available=True,
        contributing_models=[],
        missing_models=[],
    )
    snap = fusion_payload_to_horizon_snapshot("60c", fus)
    assert snap.provenance == "bayesian_fusion"
    assert snap.dominant_direction == "up"


def test_missing_fusion_confidence_score_stays_none_not_zero():
    fus = SimpleNamespace(
        available=True,
        stack_directional_authorized=True,
        prob_up=0.5,
        prob_down=0.3,
        prob_flat=0.2,
        dominant_direction="up",
        fusion_confidence="high",
        fusion_confidence_score=None,
        mc_available=False,
        contributing_models=[],
        missing_models=[],
    )
    snap = fusion_payload_to_horizon_snapshot("1c", fus)
    assert snap.horizon_fusion_available is True
    assert snap.fusion_confidence_score is None
