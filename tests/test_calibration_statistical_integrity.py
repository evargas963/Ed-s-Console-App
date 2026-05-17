"""calibration.statistical_integrity — bucket gates, gated aggregates, leak verifiers."""

from __future__ import annotations

import math

import pytest

from calibration.statistical_integrity import (
    MIN_SAMPLES_STATISTICAL,
    bucket_gate,
    gated_mean,
    gated_ratio,
    thresholds_dict,
    verify_edge_discovery_no_numeric_leak,
    verify_phase3_no_numeric_leak,
    verify_phase4_no_numeric_leak,
)


def test_thresholds_dict_aligns_with_math_probabilities_floor():
    td = thresholds_dict()
    assert td["MIN_SAMPLES_STATISTICAL"] == MIN_SAMPLES_STATISTICAL
    assert td["confidence_bucket"] == MIN_SAMPLES_STATISTICAL


def test_bucket_gate_coerces_negative_n_to_zero():
    g = bucket_gate(-5, MIN_SAMPLES_STATISTICAL)
    assert g["n"] == 0
    assert g["sufficient_sample"] is False


@pytest.mark.parametrize("n,expected_ok", [(29, False), (30, True), (100, True)])
def test_bucket_gate_sufficient_sample(n, expected_ok):
    g = bucket_gate(n, MIN_SAMPLES_STATISTICAL)
    assert g["sufficient_sample"] is expected_ok
    assert g["status"] == ("ok" if expected_ok else "insufficient_sample")


def test_gated_mean_withholds_below_min_n():
    mean, gate = gated_mean([1.0] * (MIN_SAMPLES_STATISTICAL - 1), MIN_SAMPLES_STATISTICAL)
    assert mean is None
    assert gate["sufficient_sample"] is False


def test_gated_mean_ignores_non_finite_values():
    vals = [1.0] * (MIN_SAMPLES_STATISTICAL - 1) + [float("nan"), float("inf")]
    mean, gate = gated_mean(vals, MIN_SAMPLES_STATISTICAL)
    assert mean is None
    assert gate["n"] == MIN_SAMPLES_STATISTICAL - 1


def test_gated_mean_returns_finite_mean_when_sufficient():
    mean, gate = gated_mean([2.0] * MIN_SAMPLES_STATISTICAL, MIN_SAMPLES_STATISTICAL)
    assert mean == 2.0
    assert gate["sufficient_sample"] is True


def test_gated_ratio_withholds_when_denom_insufficient():
    ratio, gate = gated_ratio(1, MIN_SAMPLES_STATISTICAL - 1)
    assert ratio is None
    assert gate["sufficient_sample"] is False


def test_verify_phase3_fails_ungated_regime_win_rate():
    out = {
        "regime_buckets": {
            "trend": {
                "sample_gate": {"sufficient_sample": False, "n": 5},
                "mean_5c_pts": None,
                "win_rate_up_or_down_aligned": 0.42,
            }
        }
    }
    assert verify_phase3_no_numeric_leak(out) is False


def test_verify_phase4_fails_ok_comparison_without_gated_means():
    out = {
        "decision_performance_from_log": {},
        "mhap_alignment": {},
        "baselines_from_snapshots": {
            "always_up_mean_gate": {"sufficient_sample": False},
            "always_down_mean_gate": {"sufficient_sample": False},
            "vwap_mr_proxy_gate": {"sufficient_sample": False},
            "decision_log_vs_baseline_comparison": {
                "status": "ok",
                "delta_log_mean_minus_always_up_mean": 0.01,
                "decision_log_mean_pnl_proxy": 0.02,
                "decision_log_sample_gate": {"sufficient_sample": False, "n": 5},
                "baseline_always_up_mean_5c_pts": 0.01,
                "baseline_always_up_gate": {"sufficient_sample": False, "n": 5},
            },
        },
    }
    assert verify_phase4_no_numeric_leak(out) is False


def test_verify_phase4_fails_delta_when_status_not_ok():
    out = {
        "decision_performance_from_log": {},
        "mhap_alignment": {},
        "baselines_from_snapshots": {
            "always_up_mean_gate": {"sufficient_sample": True},
            "always_down_mean_gate": {"sufficient_sample": True},
            "vwap_mr_proxy_gate": {"sufficient_sample": True},
            "decision_log_vs_baseline_comparison": {
                "status": "insufficient_sample",
                "delta_log_mean_minus_always_up_mean": 0.01,
            },
        },
    }
    assert verify_phase4_no_numeric_leak(out) is False


def test_verify_edge_discovery_honors_gate_sufficient_false_with_high_n():
    report = {
        "slices_all": [
            {
                "n": MIN_SAMPLES_STATISTICAL,
                "gate_sufficient": False,
                "mean_ev_actual_final_signal": 0.05,
            }
        ],
        "feature_importance_naive": {
            "pearson_n": 0,
            "pearson_sample_gate": {"sufficient_sample": False},
            "pearson_fusion_prob_up_vs_outcome_5c_pts": None,
        },
    }
    assert verify_edge_discovery_no_numeric_leak(report) is False


def test_gate_ok_for_value_rejects_non_finite_when_gate_passes():
    out = {
        "decision_performance_from_log": {
            "long": {
                "sample_gate": {"sufficient_sample": True, "n": 30},
                "mean_pnl_proxy": float("nan"),
            }
        },
        "mhap_alignment": {},
        "baselines_from_snapshots": {
            "always_up_mean_gate": {"sufficient_sample": True},
            "always_down_mean_gate": {"sufficient_sample": True},
            "vwap_mr_proxy_gate": {"sufficient_sample": True},
            "decision_log_vs_baseline_comparison": {"status": "insufficient_sample"},
        },
    }
    assert verify_phase4_no_numeric_leak(out) is False
    assert math.isnan(out["decision_performance_from_log"]["long"]["mean_pnl_proxy"])
