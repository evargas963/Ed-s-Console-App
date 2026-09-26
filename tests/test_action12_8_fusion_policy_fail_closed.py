"""Action 12.8: fusion_policy_contract must not fabricate fused_move_prob on missing fusion."""

from __future__ import annotations

from pathlib import Path









def test_fusion_policy_contract_no_third_defaults():
    text = (Path(__file__).resolve().parent.parent / "features" / "fusion_policy_contract.py").read_text(
        encoding="utf-8"
    )
    assert 'getattr(fusion, "prob_up", 1' not in text
    assert " or 0.0)" not in text
