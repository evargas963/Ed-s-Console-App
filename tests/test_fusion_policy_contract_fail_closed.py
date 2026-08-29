"""I-01: fused_confidence_<hz> is None when fusion unavailable (fusion_policy_contract)."""
from __future__ import annotations

from types import SimpleNamespace

from features.fusion_policy_contract import fusion_payload_to_policy_columns


def test_fused_confidence_none_when_fusion_unavailable() -> None:
    fusion = SimpleNamespace(
        available=False,
        fusion_summary="unavailable",
        dominant_direction="?",
        fusion_confidence="?",
    )
    cols = fusion_payload_to_policy_columns("1c", fusion)
    assert cols["fused_confidence_1c"] is None
    assert cols["fused_move_prob_1c"] is None
    assert cols["fused_dir_up_prob_1c"] is None


def test_fused_confidence_none_when_directional_triplet_missing() -> None:
    fusion = SimpleNamespace(
        available=True,
        stack_directional_authorized=True,
        prob_up=None,
        prob_down=None,
        prob_flat=None,
        fusion_confidence_score=0.72,
        dominant_direction="up",
        fusion_confidence="high",
        contributing_models=["rules"],
    )
    cols = fusion_payload_to_policy_columns("5c", fusion)
    assert cols["fused_confidence_5c"] is None


def test_fused_confidence_bounded_when_fusion_ok() -> None:
    fusion = SimpleNamespace(
        available=True,
        stack_directional_authorized=True,
        prob_up=0.6,
        prob_down=0.2,
        prob_flat=0.2,
        fusion_confidence_score=0.81,
        dominant_direction="up",
        fusion_confidence="high",
        contributing_models=["xgboost", "rules"],
    )
    cols = fusion_payload_to_policy_columns("15c", fusion)
    assert cols["fused_confidence_15c"] == 0.81
    assert cols["fused_move_prob_15c"] == 0.8
