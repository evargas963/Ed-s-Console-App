"""Unit tests for stack bundle metric packing (no DB)."""

from __future__ import annotations

from arch_competition.stack_bundle_eval_v1 import pack_metrics_for_probs


def test_pack_metrics_basic():
    y_true = [0, 1, 2, 0, 1, 2, 0, 1, 2, 0]
    prob_rows = [
        [0.7, 0.2, 0.1],
        [0.2, 0.7, 0.1],
        [0.1, 0.2, 0.7],
        [0.6, 0.3, 0.1],
        [0.15, 0.75, 0.1],
        [0.1, 0.15, 0.75],
        [0.55, 0.25, 0.2],
        [0.2, 0.55, 0.25],
        [0.25, 0.2, 0.55],
        [0.8, 0.1, 0.1],
    ]
    m = pack_metrics_for_probs("test", y_true, prob_rows)
    assert m["n_rows_scored"] == 10
    assert m["multiclass_log_loss"] < 1.0
    assert m["balanced_accuracy"] >= 0.0
    assert "confusion_matrix" in m
    assert m["macro_f1"] >= 0.0
