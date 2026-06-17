from __future__ import annotations

import builtins
import json
import sqlite3
from pathlib import Path

import pytest

from calibration.schema import ensure_calibration_schema
from calibration.statistical_integrity import bucket_gate
from calibration.v2_a1_calibration import (
    A1_CALIBRATION_AGGREGATE_HOLDOUT_MIN_SAMPLES,
    A1_CALIBRATION_HORIZON,
    A1_CALIBRATION_HORIZONS,
    A1_REGIME_AXIS_MISSING,
    _fit_isotonic_model,
    _regime_reliability,
    _row_to_calibration_example,
    _sample_gate,
    _success_label,
    build_a1_calibration_health,
    build_a1_5c_calibration_health,
    apply_isotonic_model,
    fit_a1_isotonic_artifact,
    fit_a1_5c_isotonic_artifact,
    load_a1_calibration_rows,
    load_a1_5c_calibration_rows,
    write_a1_calibration_artifact,
)
from calibration.v2_advisory_backfill import WalkForwardSplit, validate_purged_embargo_splits
from db import EdDB, configure_sqlite_connection

BASE_TS = 1_900_000_000.0


def _v2_payload(*, probability: float, direction: str = "long") -> str:
    return json.dumps(
        {
            "adapter_version": "test-adapter",
            "v2_decision": {
                "decision": {
                    "action": {"value": "TRADE", "source": "v1_approximation"},
                    "direction": {"value": direction, "source": "v1_approximation"},
                    "P_entry_success": {"value": probability, "source": "v1_approximation"},
                }
            },
        }
    )


def _seed_rows(tmp_path, *, n_train: int = 40, n_holdout: int = A1_CALIBRATION_AGGREGATE_HOLDOUT_MIN_SAMPLES):
    db_path = tmp_path / "a1_calibration.db"
    _ = EdDB(db_path)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    configure_sqlite_connection(conn)
    ensure_calibration_schema(conn)
    embargo_rows = 2
    total_rows = n_train + embargo_rows + n_holdout
    for idx in range(total_rows):
        ts = BASE_TS + idx * 60.0
        probability = 0.2 + 0.6 * ((idx % 10) / 9.0)
        outcome = "up" if probability >= 0.5 else "down"
        if idx % 7 == 0:
            outcome = "down" if outcome == "up" else "up"
        conn.execute(
            """
            INSERT INTO calibration_decision_log (
                decision_ts_utc, ticker, canonical_timeframe, calibration_trust,
                advisory_v2_decision_snapshot_json, advisory_v2_adapter_version,
                outcome_1c, outcome_1c_pts,
                outcome_5c, outcome_5c_pts,
                outcome_15c, outcome_15c_pts,
                outcome_60c, outcome_60c_pts,
                vol_regime, session_bucket
            )
            VALUES (
                ?, 'SPY', '1m', 'trusted', ?, 'test-adapter',
                ?, 0.1,
                ?, 0.1,
                ?, 0.1,
                ?, 0.1,
                'normal', 'midday'
            )
            """,
            (ts, _v2_payload(probability=probability), outcome, outcome, outcome, outcome),
        )
    conn.commit()
    conn.close()
    train_end_idx = max(1, n_train // 2)
    split = WalkForwardSplit(
        train_start=BASE_TS,
        train_end=BASE_TS + train_end_idx * 60.0,
        calibration_start=BASE_TS + train_end_idx * 60.0,
        calibration_end=BASE_TS + n_train * 60.0,
        holdout_start=BASE_TS + (n_train + embargo_rows) * 60.0,
        holdout_end=BASE_TS + (n_train + embargo_rows + n_holdout) * 60.0,
    )
    return db_path, split


def test_load_a1_calibration_rows_extracts_post_fusion_probability(tmp_path):
    db_path, _split = _seed_rows(tmp_path, n_train=4, n_holdout=4)

    rows = load_a1_5c_calibration_rows(db_path)

    assert rows
    assert rows[0]["raw_probability"] == pytest.approx(0.2)
    assert rows[0]["primary_horizon"] == A1_CALIBRATION_HORIZON
    assert rows[0]["expiry_dte_bucket"] == "not_options_applicable"


@pytest.mark.parametrize("horizon", A1_CALIBRATION_HORIZONS)
def test_load_a1_calibration_rows_supports_primary_decision_horizons(tmp_path, horizon):
    db_path, _split = _seed_rows(tmp_path, n_train=4, n_holdout=4)

    rows = load_a1_calibration_rows(db_path, horizon=horizon)

    assert rows
    assert rows[0]["primary_horizon"] == horizon
    assert rows[0][f"outcome_{horizon}"] in {"up", "down"}


def test_fit_a1_isotonic_artifact_produces_bounded_holdout_probabilities(tmp_path):
    db_path, split = _seed_rows(tmp_path)
    rows = load_a1_5c_calibration_rows(db_path)

    artifact = fit_a1_5c_isotonic_artifact(rows, split=split)

    assert artifact["status"] == "ok"
    assert artifact["horizon"] == "5c"
    assert artifact["runtime_adapter_unchanged"] is True
    assert artifact["sample_gate"]["aggregate_holdout"]["operator_decision"] == "O-24"
    assert artifact["sample_gate"]["aggregate_holdout"]["sufficient_sample"] is True
    assert artifact["model"]["type"] == "isotonic_regression"
    assert artifact["holdout_predictions"]
    assert artifact["health"]["ece"] is not None
    assert artifact["health"]["brier_score"] is not None
    assert artifact["health"]["sample_gates"]["aggregate_holdout"]["operator_decision"] == "O-24"
    for row in artifact["holdout_predictions"]:
        assert 0.0 <= row["calibrated_probability"] <= 1.0


@pytest.mark.parametrize("horizon", ("1c", "15c", "60c"))
def test_fit_a1_isotonic_artifact_uses_separate_horizon_artifacts(tmp_path, horizon):
    db_path, split = _seed_rows(tmp_path)
    rows = load_a1_calibration_rows(db_path, horizon=horizon)

    artifact = fit_a1_isotonic_artifact(rows, horizon=horizon, split=split)

    assert artifact["status"] == "ok"
    assert artifact["horizon"] == horizon
    assert artifact["target_label"] == f"outcome_{horizon}_direction_matches_v2_direction"
    assert artifact["calibration_run_id"].startswith(f"a1-{horizon}-calibration-run-")
    assert artifact["calibration_window_id"].startswith(f"a1-{horizon}-calibration-window-")
    assert artifact["health"]["horizon"] == horizon
    assert artifact["holdout_predictions"][0]["primary_horizon"] == horizon
    assert artifact["holdout_predictions"][0][f"outcome_{horizon}"] in {"up", "down"}


@pytest.mark.parametrize("horizon", ("1c", "15c", "60c"))
def test_multi_horizon_insufficient_samples_skip_until_accumulation_crosses_o24(tmp_path, horizon):
    db_path, split = _seed_rows(tmp_path, n_train=20, n_holdout=40)
    rows = load_a1_calibration_rows(db_path, horizon=horizon)

    artifact = fit_a1_isotonic_artifact(rows, horizon=horizon, split=split)

    assert artifact["status"] == "calibration_skipped_insufficient_samples"
    assert artifact["reason"] == "aggregate_holdout_below_o24"
    assert artifact["horizon"] == horizon
    assert artifact["model"] is None
    assert artifact["sample_gate"]["aggregate_holdout"]["operator_decision"] == "O-24"


def test_insufficient_holdout_samples_skip_with_o24_reason(tmp_path):
    db_path, split = _seed_rows(tmp_path, n_train=20, n_holdout=40)
    rows = load_a1_5c_calibration_rows(db_path)

    artifact = fit_a1_5c_isotonic_artifact(rows, split=split)

    assert artifact["status"] == "calibration_skipped_insufficient_samples"
    assert artifact["reason"] == "aggregate_holdout_below_o24"
    assert artifact["model"] is None
    assert artifact["sample_gate"]["aggregate_holdout"]["n"] < 500


def test_apply_isotonic_model_clips_raw_probability_to_bounds():
    model = {"x_thresholds": [0.2, 0.8], "y_thresholds": [0.1, 0.9]}

    assert apply_isotonic_model(model, -1.0) == 0.1
    assert apply_isotonic_model(model, 2.0) == 0.9
    assert apply_isotonic_model(model, 0.5) == pytest.approx(0.5)


def test_write_a1_calibration_artifact_is_json_not_pickle(tmp_path):
    db_path, split = _seed_rows(tmp_path)
    rows = load_a1_5c_calibration_rows(db_path)
    artifact = fit_a1_5c_isotonic_artifact(rows, split=split, calibration_run_id="run-1")

    path = write_a1_calibration_artifact(tmp_path / "artifacts", artifact)
    loaded = json.loads(path.read_text(encoding="utf-8"))

    assert path.name == "run-1.json"
    assert loaded["calibration_run_id"] == "run-1"
    assert loaded["model"]["type"] == "isotonic_regression"
    assert "health" in loaded


def test_write_a1_calibration_artifact_uses_atomic_json_write(monkeypatch, tmp_path):
    captured: list[tuple] = []

    def _capture(path, payload, **kw):
        captured.append((path, payload, kw))

    monkeypatch.setattr(
        "calibration.v2_a1_calibration.write_json_file_atomically",
        _capture,
    )
    artifact = {"calibration_run_id": "run-atomic", "model": {"type": "isotonic_regression"}}
    out = write_a1_calibration_artifact(tmp_path / "artifacts", artifact)
    assert out.name == "run-atomic.json"
    assert len(captured) == 1
    assert captured[0][1] == artifact
    assert captured[0][2].get("sort_keys") is True


def test_v2_a1_calibration_module_has_no_write_text():
    source = Path(__file__).resolve().parents[1] / "calibration" / "v2_a1_calibration.py"
    assert ".write_text(" not in source.read_text(encoding="utf-8")


@pytest.mark.parametrize("n,min_required,expected_ok", [(29, 30, False), (30, 30, True)])
def test_sample_gate_delegates_to_bucket_gate(n, min_required, expected_ok):
    gate = _sample_gate(n, min_required, "O-26")
    base = bucket_gate(n, min_required)
    assert gate["n"] == base["n"]
    assert gate["min_required"] == base["min_required"]
    assert gate["sufficient_sample"] is expected_ok
    assert gate["status"] == base["status"]
    assert gate["operator_decision"] == "O-26"


def test_fit_isotonic_model_raises_runtime_error_on_sklearn_import_error(monkeypatch):
    real_import = builtins.__import__

    def _mock_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "sklearn.isotonic" or (
            name == "sklearn" and fromlist and "isotonic" in fromlist
        ):
            raise ImportError("mocked sklearn missing")
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", _mock_import)
    with pytest.raises(RuntimeError, match="sklearn IsotonicRegression is required") as exc_info:
        _fit_isotonic_model([0.2, 0.8], [0, 1])
    assert isinstance(exc_info.value.__cause__, ImportError)
    assert "mocked sklearn missing" in str(exc_info.value.__cause__)


def test_reliability_bins_withhold_rates_below_o26_floor():
    predictions = [
        {
            "calibrated_probability": 0.15,
            "label": 1,
            "ticker": "SPY",
            "volatility_regime": "normal",
            "time_of_day_bucket": "midday",
            "expiry_dte_bucket": "not_options_applicable",
            "direction": "long",
            "primary_horizon": "5c",
        }
        for _ in range(20)
    ]

    health = build_a1_5c_calibration_health({"holdout_predictions": predictions})
    first_nonempty = next(row for row in health["reliability_table"] if row["n"] == 20)

    assert health["ece"] is None
    assert health["brier_score"] is None
    assert first_nonempty["sample_gate"]["operator_decision"] == "O-26"
    assert first_nonempty["sample_gate"]["sufficient_sample"] is False
    assert first_nonempty["predicted_mean"] is None
    assert first_nonempty["observed_hit_rate"] is None


def test_regime_cells_emit_rates_only_above_o25_floor(tmp_path):
    db_path, split = _seed_rows(tmp_path)
    rows = load_a1_5c_calibration_rows(db_path)

    artifact = fit_a1_5c_isotonic_artifact(rows, split=split)
    regime = artifact["health"]["regime_reliability"]

    normal = regime["volatility_regime:normal"]
    assert normal["sample_gate"]["operator_decision"] == "O-25"
    assert normal["sample_gate"]["sufficient_sample"] is True
    assert normal["observed_hit_rate"] is not None

    small = build_a1_calibration_health(
        {
            "horizon": "15c",
            "holdout_predictions": [
                {
                    "calibrated_probability": 0.6,
                    "label": 1,
                    "ticker": "SPY",
                    "volatility_regime": "thin",
                    "time_of_day_bucket": "midday",
                    "expiry_dte_bucket": "not_options_applicable",
                    "direction": "long",
                    "primary_horizon": "15c",
                }
                for _ in range(10)
            ]
        }
    )
    assert small["horizon"] == "15c"
    assert small["regime_reliability"]["volatility_regime:thin"]["observed_hit_rate"] is None


def test_success_label_none_when_outcome_missing() -> None:
    assert _success_label("long", None) is None
    assert _success_label("long", "") is None


def _wait_payload() -> str:
    return json.dumps(
        {
            "adapter_version": "test-adapter",
            "v2_decision": {
                "decision": {
                    "action": {"value": "WAIT", "source": "v1_approximation"},
                    "direction": {"value": "long", "source": "v1_approximation"},
                    "P_entry_success": {"value": 0.6, "source": "v1_approximation"},
                }
            },
        }
    )


def test_load_a1_calibration_rows_skips_non_trade_without_aborting(tmp_path, caplog):
    import logging

    db_path, _split = _seed_rows(tmp_path, n_train=4, n_holdout=4)
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        """
        INSERT INTO calibration_decision_log (
            decision_ts_utc, ticker, canonical_timeframe, calibration_trust,
            advisory_v2_decision_snapshot_json, advisory_v2_adapter_version,
            outcome_5c, outcome_5c_pts, vol_regime, session_bucket
        )
        VALUES (?, 'SPY', '1m', 'trusted', ?, 'test-adapter', 'up', 0.1, 'normal', 'midday')
        """,
        (BASE_TS + 9999 * 60.0, _wait_payload()),
    )
    conn.commit()
    conn.close()

    with caplog.at_level(logging.INFO):
        rows = load_a1_5c_calibration_rows(db_path)

    assert rows
    assert any("skipped" in r.message and "unusable rows" in r.message for r in caplog.records)


def test_parse_json_mapping_logs_corrupt_advisory_snapshot(caplog):
    import logging

    from calibration.json_utils import parse_json_mapping

    with caplog.at_level(logging.WARNING):
        out = parse_json_mapping(
            "{bad json",
            context="v2_a1_calibration: advisory_v2_decision_snapshot_json",
        )
    assert out == {}
    assert any("advisory_v2_decision_snapshot_json unparseable" in r.message for r in caplog.records)


def test_row_to_calibration_example_rejects_missing_outcome() -> None:
    row = {
        "id": 1,
        "ticker": "SPY",
        "decision_ts_utc": BASE_TS,
        "advisory_v2_decision_snapshot_json": _v2_payload(probability=0.6),
        "advisory_v2_adapter_version": "test-adapter",
        "outcome": None,
        "outcome_pts": 0.1,
        "vol_regime": "normal",
        "session_bucket": "midday",
    }
    with pytest.raises(ValueError, match="unusable_label:"):
        _row_to_calibration_example(row, horizon="5c")


def test_row_to_calibration_example_rejects_non_trade_with_distinct_reason() -> None:
    row = {
        "id": 1,
        "ticker": "SPY",
        "decision_ts_utc": BASE_TS,
        "advisory_v2_decision_snapshot_json": json.dumps(
            {
                "v2_decision": {
                    "decision": {
                        "action": {"value": "WAIT"},
                        "direction": {"value": "long"},
                        "P_entry_success": {"value": 0.6},
                    }
                }
            }
        ),
        "advisory_v2_adapter_version": "test-adapter",
        "outcome": "up",
        "outcome_pts": 0.1,
        "vol_regime": "normal",
        "session_bucket": "midday",
    }
    with pytest.raises(ValueError, match="non_trade_action:'WAIT'"):
        _row_to_calibration_example(row, horizon="5c")


def test_build_a1_calibration_health_runs_numeric_leak_verifier():
    artifact = {
        "horizon": "5c",
        "holdout_predictions": [
            {
                "calibrated_probability": 0.9,
                "label": 1,
                "volatility_regime": "normal",
                "time_of_day_bucket": "midday",
                "expiry_dte_bucket": "not_options_applicable",
                "ticker": "SPY",
                "direction": "long",
                "primary_horizon": "5c",
            }
            for _ in range(A1_CALIBRATION_AGGREGATE_HOLDOUT_MIN_SAMPLES)
        ],
    }
    health = build_a1_calibration_health(artifact)
    assert health["numeric_leak_check"] == "pass"


def test_apply_isotonic_model_warns_on_out_of_range_input(caplog):
    import logging

    model = {
        "x_thresholds": [0.2, 0.8],
        "y_thresholds": [0.1, 0.9],
        "x_train_min": 0.2,
        "x_train_max": 0.8,
    }
    with caplog.at_level(logging.WARNING):
        apply_isotonic_model(model, 1.5)
    assert any("outside [0, 1]" in r.message for r in caplog.records)


def test_build_a1_calibration_health_requires_horizon() -> None:
    with pytest.raises(ValueError, match="horizon is required"):
        build_a1_calibration_health({"holdout_predictions": []})


def test_regime_reliability_separates_missing_from_unknown_vol_regime() -> None:
    base = {
        "calibrated_probability": 0.6,
        "label": 1,
        "ticker": "SPY",
        "time_of_day_bucket": "midday",
        "expiry_dte_bucket": "not_options_applicable",
        "direction": "long",
        "primary_horizon": "5c",
    }
    predictions = [
        {**base, "volatility_regime": "unknown"},
        {**base, "volatility_regime": None},
    ]
    regime = _regime_reliability(predictions)
    assert "volatility_regime:unknown" in regime
    assert f"volatility_regime:{A1_REGIME_AXIS_MISSING}" in regime
    assert regime["volatility_regime:unknown"]["n"] == 1
    assert regime[f"volatility_regime:{A1_REGIME_AXIS_MISSING}"]["n"] == 1


def test_window_overlap_detection_still_rejects_bad_embargo():
    split = WalkForwardSplit(
        train_start=0.0,
        train_end=10.0,
        calibration_start=10.0,
        calibration_end=20.0,
        holdout_start=21.0,
        holdout_end=30.0,
    )

    with pytest.raises(ValueError, match="embargo"):
        validate_purged_embargo_splits([split], embargo_span=2.0)
