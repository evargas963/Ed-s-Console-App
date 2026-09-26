"""edge_discovery fail-closed buckets, gating, and integrity."""

from __future__ import annotations



from calibration.statistical_integrity import (
    verify_edge_discovery_no_numeric_leak,
)


def _labeled_row(*, pts: float = 0.1) -> dict:
    return {
        "outcome_5c": "up",
        "outcome_5c_pts": pts,
        "final_signal": "long",
        "canonical_json": "{}",
        "fusion_json": "{}",
        "_features": {"brier_row": 0.1},
    }


def test_verify_edge_discovery_fails_when_ungated_mean_present():
    report = {
        "slices_all": [{"n": 5, "mean_ev_actual_final_signal": 0.01}],
        "feature_importance_naive": {
            "pearson_n": 0,
            "pearson_sample_gate": {"sufficient_sample": False},
            "pearson_fusion_prob_up_vs_outcome_5c_pts": None,
        },
    }
    assert verify_edge_discovery_no_numeric_leak(report) is False

