"""Fail-closed contracts for signals.py model-namespace and stack-stage probability handling."""
from __future__ import annotations

from types import SimpleNamespace

import signals as sig


def test_unavailable_model_namespace_has_none_probs():
    ns = sig._unavailable_model_namespace()
    assert ns.available is False
    assert ns.prob_up is None
    assert ns.prob_down is None
    assert ns.prob_flat is None
    assert ns.dominant_class is None
    assert ns.confidence_label is None


def test_unavailable_model_namespace_consistent_across_callers():
    a = sig._unavailable_model_namespace()
    b = sig._unavailable_model_namespace()
    assert a.available == b.available
    assert a.prob_up is b.prob_up is None


def test_model_stage_inactive_when_unavailable_namespace():
    path = sig._build_stack_decision_path(
        sig._unavailable_model_namespace(),
        sig._unavailable_model_namespace(),
        sig._unavailable_model_namespace(),
        SimpleNamespace(available=False),
        None,
        SimpleNamespace(signal="wait", conviction="low"),
    )
    assert path.xgboost.status == "inactive"
    assert path.xgboost.probability is None


def test_model_stage_malformed_namespace_probability_none():
    malformed = SimpleNamespace(
        available=True,
        dominant_class="up",
        confidence_label="high",
    )
    path = sig._build_stack_decision_path(
        malformed,
        sig._unavailable_model_namespace(),
        sig._unavailable_model_namespace(),
        SimpleNamespace(available=False),
        None,
        SimpleNamespace(signal="wait", conviction="low"),
    )
    assert path.xgboost.status == "active"
    assert path.xgboost.probability is None
