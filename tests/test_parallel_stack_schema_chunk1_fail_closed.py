"""parallel_stack_schema Layer 5 chunk-1: lock Action 12.11 fail-closed contracts (slice-only walk)."""

from __future__ import annotations

from features.parallel_stack_schema import (
    _normalize_triplet,
    build_unified_stack_layer_output,
)


def test_normalize_triplet_none_when_flat_missing():
    assert _normalize_triplet({"up": 0.5, "down": 0.3}) is None


def test_normalize_triplet_none_when_sum_non_positive():
    assert _normalize_triplet({"up": -0.1, "down": -0.1, "flat": -0.1}) is None


def test_build_unified_stack_layer_output_no_prediction_labeled_unavailable():
    o = build_unified_stack_layer_output(probs=None, approved=True)
    assert o["available"] is False
    assert o["error"] == "no_prediction"
    assert o["prob_up"] is None
    assert o["prob_down"] is None
    assert o["prob_flat"] is None


def test_build_unified_stack_layer_output_complete_triplet_available():
    o = build_unified_stack_layer_output(
        probs={"up": 0.5, "down": 0.3, "flat": 0.2},
        approved=True,
    )
    assert o["available"] is True
    assert o["prob_up"] == 0.5
    assert o["prob_down"] == 0.3
    assert o["prob_flat"] == 0.2
    assert o["dominant"] == "up"
