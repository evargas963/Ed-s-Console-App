from __future__ import annotations

import pytest

from calibration.v2_a1_conformal import (
    A1_CONFORMAL_REGIME_AXES,
    apply_a1_conformal_interval,
    build_a1_conformal_artifact,
)
from v2_decision import build_module_a_a1_decision


def _prediction(
    idx: int,
    *,
    probability: float,
    label: int,
    ticker: str = "SPY",
    vol: str = "normal",
    session: str = "midday",
    direction: str = "long",
    horizon: str = "5c",
) -> dict:
    return {
        "calibration_row_id": idx,
        "ticker": ticker,
        "decision_ts_utc": 1_900_000_000.0 + idx * 60.0,
        "calibrated_probability": probability,
        "label": label,
        "volatility_regime": vol,
        "time_of_day_bucket": session,
        "expiry_dte_bucket": "not_options_applicable",
        "direction": direction,
        "primary_horizon": horizon,
    }


def _artifact(rows: list[dict]) -> dict:
    return {
        "calibration_run_id": "a1-5c-calibration-run-test",
        "calibration_window_id": "a1-5c-calibration-window-test",
        "module_id": "A",
        "expression_profile_id": "A1",
        "horizon": "5c",
        "holdout_predictions": rows,
    }


def _clean_rows(n: int = 500) -> list[dict]:
    return [
        _prediction(i, probability=0.95 if i % 2 else 0.05, label=1 if i % 2 else 0)
        for i in range(n)
    ]


def test_conformal_skips_insufficient_samples_without_interval_model():
    artifact = build_a1_conformal_artifact(_artifact(_clean_rows(40)))

    assert artifact["status"] == "conformal_skipped_insufficient_samples"
    assert artifact["reason"] == "aggregate_holdout_below_o24"
    assert artifact["interval_model"] is None
    assert artifact["holdout_intervals"] == []
    assert artifact["runtime_adapter_unchanged"] is True
    assert artifact["sample_gate"]["aggregate_holdout"]["operator_decision"] == "O-24"


def test_conformal_skips_missing_calibration_predictions_without_synthetic_output():
    rows = [_prediction(i, probability=0.5, label=1) for i in range(500)]
    for row in rows:
        row["calibrated_probability"] = None

    artifact = build_a1_conformal_artifact(_artifact(rows))

    assert artifact["status"] == "conformal_skipped_missing_calibration_predictions"
    assert artifact["reason"] == "no_usable_calibrated_holdout_predictions"
    assert artifact["interval_model"] is None
    assert artifact["evaluation_diagnostics"]["empirical_coverage"] is None


def test_conformal_emits_bounded_interval_model_when_coverage_is_nominal():
    artifact = build_a1_conformal_artifact(_artifact(_clean_rows()))

    assert artifact["status"] == "ok"
    assert artifact["reason"] is None
    assert artifact["interval_model"]["type"] == "split_conformal_probability_band"
    assert artifact["interval_model"]["operator_decision"] == "O-23"
    assert artifact["evaluation_diagnostics"]["empirical_coverage"] >= 0.90
    p_low, p_high = apply_a1_conformal_interval(artifact["interval_model"], 0.5)
    assert 0.0 <= p_low <= p_high <= 1.0
    assert artifact["holdout_intervals"]


def test_conformal_degraded_coverage_does_not_promote_intervals_with_separate_evaluation():
    fit_rows = _clean_rows()
    eval_rows = [_prediction(i, probability=0.0, label=1) for i in range(100)]

    artifact = build_a1_conformal_artifact(_artifact(fit_rows), evaluation_predictions=eval_rows)

    assert artifact["status"] == "conformal_degraded_empirical_coverage"
    assert artifact["reason"] == "empirical_coverage_below_o23_degraded_threshold"
    assert artifact["interval_model"] is None
    assert artifact["holdout_intervals"] == []
    assert artifact["evaluation_diagnostics"]["empirical_coverage"] < 0.85
    assert artifact["coverage_evaluation"]["source"] == "separate_evaluation_predictions"


def test_conformal_warning_below_nominal_keeps_interval_model_with_explicit_status():
    fit_rows = _clean_rows()
    eval_rows = [_prediction(i, probability=0.95, label=1 if i < 87 else 0) for i in range(100)]

    artifact = build_a1_conformal_artifact(_artifact(fit_rows), evaluation_predictions=eval_rows)

    assert artifact["status"] == "conformal_warning_below_nominal"
    assert artifact["reason"] == "empirical_coverage_below_o23_nominal"
    assert artifact["interval_model"] is not None
    assert artifact["evaluation_diagnostics"]["empirical_coverage"] == pytest.approx(0.87)


def test_conformal_regime_coverage_mirrors_a1_axes_and_withholds_sparse_cells():
    rows = [
        _prediction(i, probability=0.95, label=1, ticker="SPY", vol="normal")
        for i in range(60)
    ]
    rows.extend(
        _prediction(i + 60, probability=0.95, label=1, ticker="QQQ", vol="high")
        for i in range(10)
    )
    artifact = build_a1_conformal_artifact(_artifact(rows), min_holdout_samples=70)

    assert tuple(A1_CONFORMAL_REGIME_AXES) == (
        "volatility_regime",
        "time_of_day_bucket",
        "expiry_dte_bucket",
        "ticker",
        "direction",
        "primary_horizon",
    )
    regime = artifact["regime_coverage"]
    assert regime["volatility_regime:normal"]["sample_gate"]["operator_decision"] == "O-25"
    assert regime["volatility_regime:normal"]["sample_gate"]["sufficient_sample"] is True
    assert regime["volatility_regime:normal"]["empirical_coverage"] == pytest.approx(1.0)
    assert regime["volatility_regime:high"]["sample_gate"]["sufficient_sample"] is False
    assert regime["volatility_regime:high"]["empirical_coverage"] is None
    assert regime["volatility_regime:high"]["status"] == "insufficient_sample"


def test_conformal_artifact_discloses_approximate_guarantee_assumptions():
    artifact = build_a1_conformal_artifact(_artifact(_clean_rows()))
    disclosure = artifact["approximate_guarantee_disclosure"]

    assert disclosure["assumption"] == "exchangeability of calibration and future examples"
    assert "regime_shift" in disclosure["likely_violation_modes"]
    assert "volatility_clustering" in disclosure["likely_violation_modes"]
    assert "ticker_universe_drift" in disclosure["likely_violation_modes"]
    assert disclosure["qualification"] == "approximate_not_exact"
    assert disclosure["empirical_diagnostics_required"] is True
    assert artifact["coverage_evaluation"]["same_rows_as_quantile_fit"] is True


def test_conformal_scaffold_does_not_change_runtime_probability_or_ev_fields():
    decision = build_module_a_a1_decision(
        {
            "ticker": "SPY",
            "fusion_available": True,
            "fusion_dominant_direction": "up",
            "fusion_dominant_prob": 0.64,
            "dominant_dir": "up",
            "is_no_trade": False,
        }
    )
    dec = decision["decision"]

    assert dec["p_low"]["source"] == "not_implemented"
    assert dec["p_high"]["source"] == "not_implemented"
    assert dec["EV_lower"]["source"] == "not_implemented"
    assert dec["EV_upper"]["source"] == "not_implemented"
