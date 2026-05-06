from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from calibration.a1_conformal_artifact_production import (
    ARTIFACT_LIFECYCLE_SCHEMA_VERSION,
    artifact_output_path,
    augment_conformal_artifact_with_lifecycle_fields,
    compute_calibration_lineage_id,
    current_pointer_path,
    is_eligible_for_current_pointer,
    produce_a1_conformal_artifact,
    update_current_pointer_atomically,
)
from calibration.run_a1_conformal_artifact_production import build_arg_parser


def _calibration_artifact(**overrides) -> dict:
    base = {
        "schema_version": "1",
        "calibration_run_id": "cal-test-run",
        "calibration_window_id": "window-test",
        "module_id": "A",
        "expression_profile_id": "A1",
        "horizon": "5c",
        "status": "ok",
        "model": {"type": "isotonic_regression", "x_thresholds": [0.0, 1.0], "y_thresholds": [0.2, 0.8]},
        "holdout_predictions": [{"calibrated_probability": 0.7, "label": 1}],
    }
    base.update(overrides)
    return base


def _conformal_artifact(**overrides) -> dict:
    base = {
        "schema_version": "1",
        "calibration_run_id": "cal-test-run",
        "calibration_window_id": "window-test",
        "conformal_run_id": "cal-test-run-conformal",
        "module_id": "A",
        "expression_profile_id": "A1",
        "horizon": "5c",
        "status": "ok",
        "interval_model": {"type": "split_conformal_probability_band", "score_quantile": 0.1},
        "coverage_evaluation": {
            "source": "separate_evaluation_predictions",
            "same_rows_as_quantile_fit": False,
        },
        "evaluation_diagnostics": {"empirical_coverage": 0.9},
        "sample_gate": {"aggregate_holdout": {"sufficient_sample": True, "n": 500}},
    }
    base.update(overrides)
    return base


def test_successful_production_writes_artifact_and_pointer(monkeypatch, tmp_path):
    """Contract §196 bullet 1: all preconditions satisfied writes artifact and updates pointer."""
    monkeypatch.setattr(
        "calibration.a1_conformal_artifact_production.load_a1_calibration_rows",
        lambda db_path, *, horizon: [{"ticker": "SPY", "decision_ts_utc": 1.0}],
    )
    monkeypatch.setattr(
        "calibration.a1_conformal_artifact_production.fit_a1_isotonic_artifact",
        lambda rows, *, horizon, split: _calibration_artifact(),
    )
    monkeypatch.setattr(
        "calibration.a1_conformal_artifact_production.apply_isotonic_model",
        lambda model, raw_probability: 0.7,
    )
    monkeypatch.setattr(
        "calibration.a1_conformal_artifact_production.build_a1_conformal_artifact",
        lambda calibration_artifact, *, evaluation_predictions: _conformal_artifact(),
    )

    result = produce_a1_conformal_artifact(
        db_path=Path("unused.db"),
        ticker="SPY",
        horizon="5c",
        train_start=0,
        train_end=1,
        calibration_start=1,
        calibration_end=2,
        holdout_start=2,
        holdout_end=3,
        eval_start=3,
        eval_end=4,
        governed_max_age_seconds=3600,
        now_epoch_seconds=1000,
        data_root=tmp_path,
    )

    assert result["status"] == "ok"
    assert result["pointer_updated"] is True
    artifact = result["artifact"]
    assert artifact["ticker_universe"] == ["SPY"]
    assert artifact["governed_max_age_seconds"] == 3600
    assert artifact["generated_at_epoch_seconds"] == 1000
    assert artifact["calibration_lineage_id"] == compute_calibration_lineage_id(_calibration_artifact())
    assert artifact["artifact_lifecycle_schema_version"] == ARTIFACT_LIFECYCLE_SCHEMA_VERSION
    assert result["artifact_path"].is_file()
    pointer = current_pointer_path(ticker="SPY", horizon="5c", data_root=tmp_path)
    pointer_payload = json.loads(pointer.read_text(encoding="utf-8"))
    assert pointer_payload == {
        "artifact_relative_path": "v2_calibration/conformal/A/A1/SPY/5c/cal-test-run.json"
    }


def test_o1_coverage_failure_writes_artifact_but_not_pointer(monkeypatch, tmp_path):
    """Contract §196 bullet 2: O1 failure writes audit artifact but does not update pointer."""
    _patch_basic_pipeline(monkeypatch, conformal_artifact=_conformal_artifact(evaluation_diagnostics={"empirical_coverage": 0.8}))

    result = _produce(tmp_path)

    assert result["status"] == "audit_not_promoted"
    assert result["pointer_updated"] is False
    assert "empirical_coverage" in str(result["eligibility_reason"])
    assert result["artifact_path"].is_file()
    assert not current_pointer_path(ticker="SPY", horizon="5c", data_root=tmp_path).exists()


def test_eval_window_too_small_writes_artifact_but_not_pointer(monkeypatch, tmp_path):
    """Contract §196 bullet 3: insufficient eval window writes audit artifact only."""
    _patch_basic_pipeline(
        monkeypatch,
        conformal_artifact=_conformal_artifact(sample_gate={"aggregate_holdout": {"sufficient_sample": False, "n": 10}}),
    )

    result = _produce(tmp_path)

    assert result["status"] == "audit_not_promoted"
    assert result["pointer_updated"] is False
    assert "aggregate_holdout" in str(result["eligibility_reason"])
    assert result["artifact_path"].is_file()
    assert not current_pointer_path(ticker="SPY", horizon="5c", data_root=tmp_path).exists()


def test_invalid_cli_args_fail_explicitly():
    """Contract §196 bullet 4: missing required CLI args fail validation."""
    parser = build_arg_parser()

    with pytest.raises(SystemExit) as excinfo:
        parser.parse_args(["--ticker", "SPY"])

    assert excinfo.value.code == 2


def test_lineage_hash_matches_locked_recipe():
    """Contract §196 bullet 5 and §113-128: lineage hash follows locked SHA-256 recipe."""
    artifact = _calibration_artifact(model={"z": [2, 1], "a": {"b": 3}})
    expected_model_json = json.dumps(artifact["model"], sort_keys=True, separators=(",", ":"))
    import hashlib

    expected = f"cal-test-run:{hashlib.sha256(expected_model_json.encode('utf-8')).hexdigest()}"

    assert compute_calibration_lineage_id(artifact) == expected


def test_atomic_pointer_write_never_partial(monkeypatch, tmp_path):
    """Contract §196 bullet 6: pointer update uses atomic replace, never empty/partial pointer."""
    pointer = tmp_path / "current.json"
    pointer.write_text(json.dumps({"artifact_relative_path": "old.json"}), encoding="utf-8")

    def fail_replace(src, dst):
        raise OSError("simulated replace failure")

    monkeypatch.setattr(os, "replace", fail_replace)

    with pytest.raises(OSError):
        update_current_pointer_atomically(artifact_relative_path="new.json", pointer_path=pointer)

    assert json.loads(pointer.read_text(encoding="utf-8")) == {"artifact_relative_path": "old.json"}


def test_path_convention_per_ticker():
    """Contract §196 bullet 7: per-ticker path and single-ticker lifecycle field."""
    root = Path("DATA_ROOT")
    path = artifact_output_path(
        ticker="SPY",
        horizon="5c",
        calibration_run_id="cal-test-run",
        data_root=root,
    )
    artifact = augment_conformal_artifact_with_lifecycle_fields(
        conformal_artifact=_conformal_artifact(),
        ticker="SPY",
        governed_max_age_seconds=3600,
        generated_at_epoch_seconds=1000,
        calibration_lineage_id="cal-test-run:hash",
    )

    assert path == root / "v2_calibration" / "conformal" / "A" / "A1" / "SPY" / "5c" / "cal-test-run.json"
    assert artifact["ticker_universe"] == ["SPY"]


def test_no_partial_artifact_or_pointer_on_failure(monkeypatch, tmp_path):
    """Contract §196 bullet 8: failed build leaves no artifact or pointer partials."""
    _patch_basic_pipeline(monkeypatch)

    def fail_build(calibration_artifact, *, evaluation_predictions):
        raise RuntimeError("simulated conformal failure")

    monkeypatch.setattr("calibration.a1_conformal_artifact_production.build_a1_conformal_artifact", fail_build)

    with pytest.raises(RuntimeError):
        _produce(tmp_path)

    assert not list(tmp_path.rglob("*.json"))


def test_is_eligible_returns_reason_for_each_contract_gate():
    """Optional helper regression: each eligibility gate returns a readable first-failure reason."""
    valid = augment_conformal_artifact_with_lifecycle_fields(
        conformal_artifact=_conformal_artifact(),
        ticker="SPY",
        governed_max_age_seconds=3600,
        generated_at_epoch_seconds=1000,
        calibration_lineage_id="cal-test-run:hash",
    )

    assert is_eligible_for_current_pointer(valid) == (True, None)
    assert is_eligible_for_current_pointer({**valid, "schema_version": "bad"})[0] is False
    assert is_eligible_for_current_pointer({**valid, "artifact_lifecycle_schema_version": "bad"})[0] is False
    assert is_eligible_for_current_pointer({**valid, "ticker_universe": []})[0] is False
    assert is_eligible_for_current_pointer({**valid, "horizon": None})[0] is False
    assert is_eligible_for_current_pointer({**valid, "evaluation_diagnostics": {"empirical_coverage": 0.1}})[0] is False
    assert is_eligible_for_current_pointer({**valid, "sample_gate": {"aggregate_holdout": {"sufficient_sample": False}}})[0] is False
    assert is_eligible_for_current_pointer({**valid, "calibration_lineage_id": ""})[0] is False


def test_lineage_hash_deterministic_across_invocations():
    """Optional helper regression: model key order does not alter lineage hash."""
    left = _calibration_artifact(model={"b": 2, "a": 1})
    right = _calibration_artifact(model={"a": 1, "b": 2})

    assert compute_calibration_lineage_id(left) == compute_calibration_lineage_id(right)


def _patch_basic_pipeline(monkeypatch, *, conformal_artifact: dict | None = None) -> None:
    monkeypatch.setattr(
        "calibration.a1_conformal_artifact_production.load_a1_calibration_rows",
        lambda db_path, *, horizon: [{"ticker": "SPY", "decision_ts_utc": 3.5, "raw_probability": 0.6, "label": 1}],
    )
    monkeypatch.setattr(
        "calibration.a1_conformal_artifact_production.fit_a1_isotonic_artifact",
        lambda rows, *, horizon, split: _calibration_artifact(),
    )
    monkeypatch.setattr(
        "calibration.a1_conformal_artifact_production.apply_isotonic_model",
        lambda model, raw_probability: 0.7,
    )
    monkeypatch.setattr(
        "calibration.a1_conformal_artifact_production.build_a1_conformal_artifact",
        lambda calibration_artifact, *, evaluation_predictions: conformal_artifact or _conformal_artifact(),
    )


def _produce(tmp_path):
    return produce_a1_conformal_artifact(
        db_path=Path("unused.db"),
        ticker="SPY",
        horizon="5c",
        train_start=0,
        train_end=1,
        calibration_start=1,
        calibration_end=2,
        holdout_start=2,
        holdout_end=3,
        eval_start=3,
        eval_end=4,
        governed_max_age_seconds=3600,
        now_epoch_seconds=1000,
        data_root=tmp_path,
    )
