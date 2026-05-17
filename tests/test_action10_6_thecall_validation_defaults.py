"""Action 10.6: TheCall validation gate must not default to passed (fail on 5f3d52b)."""

from __future__ import annotations

from dataclasses import fields

from signal_types import TheCall


def _field_default(name: str):
    return next(f for f in fields(TheCall) if f.name == name).default


def test_thecall_validation_fields_default_none_not_true():
    """Internal safety gate: unpopulated TheCall must not imply validation passed."""
    assert _field_default("validation_passed") is None
    assert _field_default("structure_valid") is None
    assert _field_default("probability_valid") is None
    assert _field_default("risk_valid") is None


def test_thecall_instance_validation_fields_none_when_omitted():
    call = TheCall(
        signal="wait",
        conviction="low",
        entry=None,
        stop=None,
        target=None,
        target2=None,
        reward_risk=None,
        reward_risk2=None,
        headline="",
        reasoning="",
        trade_type="none",
        invalidation="",
        confluence_count=0,
        confluence_total=0,
        confluence_detail="",
        time_qualifier="",
        size_cue="SKIP",
        rules_pred_agree=False,
        time_warning=None,
        size_note="",
    )
    assert call.validation_passed is None
    assert call.structure_valid is None
    assert call.probability_valid is None
    assert call.risk_valid is None
