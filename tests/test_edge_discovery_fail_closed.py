"""edge_discovery fail-closed buckets, gating, and integrity."""

from __future__ import annotations

import pytest

from calibration.edge_discovery import (
    _alignment_state_bucket,
    _canonical_confidence_bucket,
    aggregate_slice,
)
from calibration.statistical_integrity import (
    MIN_SAMPLES_STATISTICAL,
    verify_edge_discovery_no_numeric_leak,
)
from calibration.v2_a1_calibration import axis_reliability_bucket_value as a1_axis


def _labeled_row(*, pts: float = 0.1) -> dict:
    return {
        "outcome_5c": "up",
        "outcome_5c_pts": pts,
        "final_signal": "long",
        "canonical_json": "{}",
        "fusion_json": "{}",
        "_features": {"brier_row": 0.1},
    }


def test_alignment_state_missing_distinct_from_unknown():
    assert _alignment_state_bucket(None) == a1_axis(None)
    assert _alignment_state_bucket("UNKNOWN") == "UNKNOWN"
    assert _alignment_state_bucket(None) != "UNKNOWN"


def test_canonical_confidence_missing_invalid_distinct():
    missing = _canonical_confidence_bucket(None)
    invalid = _canonical_confidence_bucket("garbled")
    low = _canonical_confidence_bucket("low")
    assert missing == a1_axis(None)
    assert invalid == "__invalid__"
    assert low == "low"
    assert len({missing, invalid, low}) == 3


def test_aggregate_slice_withholds_means_below_min_n():
    members = [_labeled_row(pts=0.01 * i) for i in range(MIN_SAMPLES_STATISTICAL - 1)]
    agg = aggregate_slice("test|n=small", "marginal:test", members)
    assert agg["gate_sufficient"] is False
    assert agg["mean_ev_actual_final_signal"] is None
    assert agg["mean_brier"] is None
    assert agg["bootstrap_actual_minus_long"]["mean_delta"] is None

    report = {
        "slices_all": [agg],
        "feature_importance_naive": {
            "pearson_n": 0,
            "pearson_sample_gate": {"sufficient_sample": False, "n": 0},
            "pearson_fusion_prob_up_vs_outcome_5c_pts": None,
        },
    }
    assert verify_edge_discovery_no_numeric_leak(report) is True


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
