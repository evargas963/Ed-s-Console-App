"""Fail-closed contracts for ml_predict model-probability → fusion/UI conversion."""
from __future__ import annotations

import ml_predict as mp


def test_require_direction_probability_triplet_none_input():
    assert mp._require_direction_probability_triplet(None) is None


def test_require_direction_probability_triplet_missing_key():
    assert mp._require_direction_probability_triplet({"up": 0.5, "down": 0.3}) is None
    assert mp._require_direction_probability_triplet({"up": 0.5, "flat": 0.2}) is None


def test_require_direction_probability_triplet_complete():
    tri = mp._require_direction_probability_triplet({"up": 0.5, "down": 0.3, "flat": 0.2})
    assert tri == (0.5, 0.3, 0.2)


def test_model_probs_to_fusion_out_fail_closed_on_partial_dict():
    assert mp._model_probs_to_fusion_out({"up": 0.5, "down": 0.3}, "wait") is None


def test_model_probs_to_fusion_out_available_on_complete_dict():
    out = mp._model_probs_to_fusion_out(
        {"up": 0.5, "down": 0.3, "flat": 0.2},
        "long",
    )
    assert out is not None
    assert out["available"] is True
    assert out["prob_up"] == 0.5
    assert out["prob_down"] == 0.3
    assert out["prob_flat"] == 0.2
    assert out["dominant_class"] == "up"
    assert out["continuation_support"] == 0.5
    assert out["reversal_support"] == 0.3


def test_model_probs_to_fusion_out_none_input():
    assert mp._model_probs_to_fusion_out(None, "wait") is None


def test_model_probs_to_ui_output_fail_closed_on_partial_dict():
    out = mp._model_probs_to_ui_output({"up": 0.5, "down": 0.3}, approved=True)
    assert out["available"] is False
    assert out["dominant"] is None
    assert out["approved"] is False


def test_model_probs_to_ui_output_available_on_complete_dict():
    out = mp._model_probs_to_ui_output(
        {"up": 0.5, "down": 0.3, "flat": 0.2},
        approved=True,
    )
    assert out["available"] is True
    assert out["dominant"] == "up"
    assert out["up"] == 0.5
    assert out["down"] == 0.3
    assert out["flat"] == 0.2
    assert out["approved"] is True


def test_model_probs_to_ui_output_none_input():
    out = mp._model_probs_to_ui_output(None, approved=True)
    assert out["available"] is False


def test_parallel_base_stack_complete_requires_all_legs():
    tri = {"up": 0.4, "down": 0.3, "flat": 0.3}
    assert mp._parallel_base_stack_complete(tri, tri, tri) is True
    assert mp._parallel_base_stack_complete(tri, tri, None) is False
    assert mp._parallel_base_stack_complete(tri, {"up": 0.5}, tri) is False


def test_weighted_average_fail_closed_on_partial_stack():
    tri = {"up": 0.4, "down": 0.3, "flat": 0.3}
    assert mp._weighted_average("SPY", tri, tri, None) is None


def test_stack_probs_fail_closed_on_partial_stack():
    tri = {"up": 0.4, "down": 0.3, "flat": 0.3}
    assert mp._stack_probs(tri, tri, None) is None


def test_ensemble_parallel_probs_fail_closed_on_partial_stack():
    tri = {"up": 0.4, "down": 0.3, "flat": 0.3}
    assert mp._ensemble_parallel_probs("SPY", tri, None, tri) is None
