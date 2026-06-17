"""Unit tests for stack bundle metric packing (no DB)."""

from __future__ import annotations

from arch_competition.stack_bundle_eval_v1 import pack_metrics_for_probs


def test_pack_metrics_basic():
    from calibration.statistical_integrity import MIN_SAMPLES_STATISTICAL

    base_probs = [
        [0.7, 0.2, 0.1],
        [0.2, 0.7, 0.1],
        [0.1, 0.2, 0.7],
    ]
    y_true = [i % 3 for i in range(MIN_SAMPLES_STATISTICAL)]
    prob_rows = [base_probs[i % 3] for i in range(MIN_SAMPLES_STATISTICAL)]
    m = pack_metrics_for_probs("test", y_true, prob_rows)
    assert m["n_rows_scored"] == MIN_SAMPLES_STATISTICAL
    assert m["multiclass_log_loss"] < 1.0
    assert m["balanced_accuracy"] >= 0.0
    assert "confusion_matrix" in m
    assert m["macro_f1"] >= 0.0
