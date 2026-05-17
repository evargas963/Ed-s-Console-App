from __future__ import annotations

import pytest

from calibration.statistical_integrity import bucket_gate
from calibration.v2_a1_conformal import build_a1_conformal_artifact
from calibration.v2_a1_ev_bounds import (
    A1_EV_BOUNDS_METHOD,
    _sample_gate,
    build_a1_ev_bounds_artifact,
    compute_ev_bound,
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


def _calibration_artifact(rows: list[dict]) -> dict:
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


def _ok_conformal(rows: list[dict] | None = None) -> dict:
    return build_a1_conformal_artifact(_calibration_artifact(rows or _clean_rows()))


def test_ev_bounds_run_id_null_when_conformal_run_id_missing():
    conformal = build_a1_conformal_artifact(
        {
            "holdout_predictions": _clean_rows(500),
        }
    )
    artifact = build_a1_ev_bounds_artifact(conformal, reward_r=2.0)
    assert artifact["conformal_run_id"] is None
    assert artifact["ev_bounds_run_id"] is None


def test_ev_bounds_skips_when_conformal_status_missing():
    conformal = {**_ok_conformal(), "status": None}
    artifact = build_a1_ev_bounds_artifact(conformal, reward_r=2.0)
    assert artifact["status"] == "ev_bounds_skipped_missing_upstream_conformal_status"
    assert artifact["reason"] == "conformal_artifact_status_field_missing"


def test_ev_bounds_cascade_skipped_conformal_without_synthetic_values():
    conformal = build_a1_conformal_artifact(_calibration_artifact(_clean_rows(40)))

    artifact = build_a1_ev_bounds_artifact(conformal, reward_r=2.0)

    assert artifact["status"] == "ev_bounds_skipped_upstream_conformal_unavailable"
    assert artifact["reason"].startswith("conformal_skipped_insufficient_samples:")
    assert artifact["ev_model"] is None
    assert artifact["ev_bounds"] == []
    assert artifact["runtime_adapter_unchanged"] is True


def test_ev_bounds_cascade_degraded_conformal_without_ev_values():
    fit_rows = _clean_rows()
    eval_rows = [_prediction(i, probability=0.0, label=1) for i in range(100)]
    conformal = build_a1_conformal_artifact(_calibration_artifact(fit_rows), evaluation_predictions=eval_rows)

    artifact = build_a1_ev_bounds_artifact(conformal, reward_r=2.0)

    assert artifact["status"] == "ev_bounds_skipped_upstream_conformal_degraded"
    assert artifact["reason"].startswith("conformal_degraded_empirical_coverage:")
    assert artifact["ev_model"] is None
    assert artifact["ev_bounds"] == []


def test_ev_bounds_warning_conformal_emits_rows_with_warning_status():
    fit_rows = _clean_rows()
    eval_rows = [_prediction(i, probability=0.95, label=1 if i < 87 else 0) for i in range(100)]
    conformal = build_a1_conformal_artifact(_calibration_artifact(fit_rows), evaluation_predictions=eval_rows)

    artifact = build_a1_ev_bounds_artifact(conformal, reward_r=2.0)

    assert artifact["status"] == "ev_bounds_warning_upstream_conformal_below_nominal"
    assert artifact["reason"].startswith("conformal_warning_below_nominal:")
    assert artifact["ev_model"]["type"] == A1_EV_BOUNDS_METHOD
    assert artifact["ev_bounds"]


def test_bounded_probability_warns_when_outside_unit_interval(caplog):
    import logging

    from calibration.v2_a1_ev_bounds import _bounded_probability

    with caplog.at_level(logging.WARNING):
        assert _bounded_probability(1.5) == 1.0
    assert any("outside [0, 1]" in r.message for r in caplog.records)


def test_ev_bounds_compute_expected_r_math_from_probability_band():
    assert compute_ev_bound(0.25, reward_r=2.0, risk_r=1.0) == pytest.approx(-0.25)
    assert compute_ev_bound(0.75, reward_r=2.0, risk_r=1.0) == pytest.approx(1.25)

    conformal = {
        **_ok_conformal(),
        "holdout_intervals": [
            {
                "calibration_row_id": 1,
                "ticker": "SPY",
                "decision_ts_utc": 1_900_000_000.0,
                "p_low": 0.25,
                "p_high": 0.75,
                "volatility_regime": "normal",
                "time_of_day_bucket": "midday",
                "expiry_dte_bucket": "not_options_applicable",
                "direction": "long",
                "primary_horizon": "5c",
            }
        ],
    }

    artifact = build_a1_ev_bounds_artifact(conformal, reward_r=2.0, risk_r=1.0)

    row = artifact["ev_bounds"][0]
    assert artifact["status"] == "ok"
    assert row["EV_lower"] == pytest.approx(-0.25)
    assert row["EV_upper"] == pytest.approx(1.25)
    assert artifact["summary"]["mean_EV_lower"] == pytest.approx(-0.25)
    assert artifact["summary"]["mean_EV_upper"] == pytest.approx(1.25)


def test_ev_bounds_skip_missing_conformal_interval_rows():
    conformal = {**_ok_conformal(), "holdout_intervals": []}

    artifact = build_a1_ev_bounds_artifact(conformal, reward_r=2.0)

    assert artifact["status"] == "ev_bounds_skipped_missing_conformal_intervals"
    assert artifact["reason"] == "no_usable_conformal_interval_rows"
    assert artifact["ev_model"] is None
    assert artifact["ev_bounds"] == []


def test_ev_bounds_regime_diagnostics_mirror_axes_and_withhold_sparse_cells():
    rows = [
        _prediction(i, probability=0.95, label=1, ticker="SPY", vol="normal")
        for i in range(60)
    ]
    rows.extend(
        _prediction(i + 60, probability=0.95, label=1, ticker="QQQ", vol="high")
        for i in range(10)
    )
    conformal = build_a1_conformal_artifact(_calibration_artifact(rows), min_holdout_samples=70)

    artifact = build_a1_ev_bounds_artifact(conformal, reward_r=2.0)

    regime = artifact["regime_ev_bounds"]
    assert regime["volatility_regime:normal"]["sample_gate"]["operator_decision"] == "O-25"
    assert regime["volatility_regime:normal"]["sample_gate"]["sufficient_sample"] is True
    assert regime["volatility_regime:normal"]["mean_EV_lower"] is not None
    assert regime["volatility_regime:normal"]["mean_EV_upper"] is not None
    assert regime["volatility_regime:high"]["sample_gate"]["sufficient_sample"] is False
    assert regime["volatility_regime:high"]["mean_EV_lower"] is None
    assert regime["volatility_regime:high"]["mean_EV_upper"] is None
    assert regime["volatility_regime:high"]["status"] == "insufficient_sample"


def test_ev_bounds_disclosure_inherits_conformal_and_names_geometry_limits():
    conformal = _ok_conformal()

    artifact = build_a1_ev_bounds_artifact(conformal, reward_r=2.0)
    disclosure = artifact["approximate_guarantee_disclosure"]

    assert disclosure["inherits"] == conformal["approximate_guarantee_disclosure"]
    assert disclosure["method"] == A1_EV_BOUNDS_METHOD
    assert "reward_r and risk_r represent the candidate trade geometry at decision time" in disclosure["assumptions"]
    assert "stop_target_geometry_drift" in disclosure["likely_violation_modes"]
    assert "execution_costs_not_modeled" in disclosure["likely_violation_modes"]
    assert disclosure["qualification"] == "approximate_not_exact"
    assert disclosure["execution_adjusted_ev"] == "not_implemented"
    assert artifact["geometry_scope"]["type"] == "artifact_level"
    assert artifact["geometry_scope"]["per_row_geometry_required_for_runtime_promotion"] is True


def test_ev_bounds_scaffold_does_not_change_runtime_ev_fields():
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


@pytest.mark.parametrize("n,min_required,expected_ok", [(29, 30, False), (30, 30, True)])
def test_sample_gate_delegates_to_bucket_gate(n, min_required, expected_ok):
    gate = _sample_gate(n, min_required, "O-25")
    base = bucket_gate(n, min_required)
    assert gate["n"] == base["n"]
    assert gate["min_required"] == base["min_required"]
    assert gate["sufficient_sample"] is expected_ok
    assert gate["status"] == base["status"]
    assert gate["operator_decision"] == "O-25"


def test_sample_gate_coerces_negative_n_via_bucket_gate():
    gate = _sample_gate(-5, 30, "O-25")
    assert gate["n"] == 0
    assert gate["sufficient_sample"] is False
    assert gate["status"] == "insufficient_sample"
