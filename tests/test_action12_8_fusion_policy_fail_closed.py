"""Action 12.8: fusion_policy_contract must not fabricate fused_move_prob on missing fusion."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from features.fusion_policy_contract import fusion_payload_to_policy_columns


def test_unavailable_fusion_yields_none_policy_probs():
    fus = SimpleNamespace(available=False, fusion_summary="stack_down")
    cols = fusion_payload_to_policy_columns("5c", fus)
    assert cols["fused_move_prob_5c"] is None
    assert cols["fused_dir_up_prob_5c"] is None
    assert cols["fused_confidence_5c"] is None
    assert "fusion_unavailable" in cols["fused_stack_status_5c"]


def test_none_prob_flat_does_not_fabricate_move_prob_one():
    """Missing prob_flat used to coerce via ``or 0.0`` → move_prob = 1.0."""
    fus = SimpleNamespace(
        available=True,
        prob_up=0.5,
        prob_down=0.3,
        prob_flat=None,
        fusion_confidence_score=0.7,
        contributing_models=[],
        dominant_direction="up",
        fusion_confidence="medium",
    )
    cols = fusion_payload_to_policy_columns("5c", fus)
    assert cols["fused_move_prob_5c"] is None
    assert cols["fused_dir_up_prob_5c"] is None


def test_complete_fusion_triplet_computes_move_prob():
    fus = SimpleNamespace(
        available=True,
        prob_up=0.5,
        prob_down=0.2,
        prob_flat=0.3,
        fusion_confidence_score=0.8,
        contributing_models=["xgb"],
        dominant_direction="up",
        fusion_confidence="high",
    )
    cols = fusion_payload_to_policy_columns("5c", fus)
    assert cols["fused_move_prob_5c"] == 0.7
    assert cols["fused_dir_up_prob_5c"] == 0.5
    assert cols["fused_confidence_5c"] == 0.8


def test_fusion_policy_contract_no_third_defaults():
    text = (Path(__file__).resolve().parent.parent / "features" / "fusion_policy_contract.py").read_text(
        encoding="utf-8"
    )
    assert 'getattr(fusion, "prob_up", 1' not in text
    assert " or 0.0)" not in text
