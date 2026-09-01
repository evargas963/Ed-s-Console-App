"""A1 isotonic artifact production (produce_a1_isotonic_artifact + its CLI arg
parser): atomic write, current-pointer swap, and lineage id must never leave a
partial or wrongly-promoted artifact live for the runtime to load."""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from calibration.a1_conformal_artifact_production import (
    compute_calibration_lineage_id,
    current_pointer_path,
    update_current_pointer_atomically,
)
from calibration.a1_isotonic_artifact_production import produce_a1_isotonic_artifact
from calibration.run_a1_isotonic_artifact_production import build_arg_parser
from v2_decision.a1_conformal_artifact_contract import (
    artifact_output_path,
    is_eligible_for_current_pointer_isotonic,
)


def _isotonic_artifact(**overrides) -> dict:
    base = {
        "schema_version": "1",
        "calibration_run_id": "cal-test-run",
        "calibration_window_id": "window-test",
        "module_id": "A",
        "expression_profile_id": "A1",
        "horizon": "5c",
        "method": "isotonic_regression",
        "raw_probability_field": "v2_decision.decision.P_entry_success",
        "target_label": "outcome_5c_direction_matches_v2_direction",
        "sample_gate": {"aggregate_holdout": {"sufficient_sample": True, "n": 500}},
        "window": {
            "train_start": 0.0,
            "train_end": 1.0,
            "calibration_start": 1.0,
            "calibration_end": 2.0,
            "holdout_start": 2.0,
            "holdout_end": 3.0,
        },
        "status": "ok",
        "reason": None,
        "model": {"type": "isotonic_regression", "x_thresholds": [0.0, 1.0], "y_thresholds": [0.2, 0.8]},
    }
    base.update(overrides)
    return base


def test_successful_isotonic_production_writes_artifact_and_pointer(monkeypatch, tmp_path):
    _patch_basic_pipeline(monkeypatch)

    result = _produce(tmp_path)

    assert result["status"] == "ok"
    assert result["pointer_updated"] is True
    artifact = result["artifact"]
    assert artifact["ticker_universe"] == ["SPY"]
    assert artifact["governed_max_age_seconds"] == 691200
    assert artifact["generated_at_epoch_seconds"] == 1000
    assert artifact["artifact_lifecycle_schema_version"] == "1"
    assert artifact["calibration_lineage_id"] == compute_calibration_lineage_id(_isotonic_artifact())
    assert result["artifact_path"].is_file()
    pointer = current_pointer_path(ticker="SPY", horizon="5c", data_root=tmp_path, artifact_kind="isotonic")
    assert json.loads(pointer.read_text(encoding="utf-8")) == {
        "artifact_relative_path": "v2_calibration/isotonic/A/A1/SPY/5c/cal-test-run.json"
    }


def test_isotonic_status_skipped_writes_artifact_but_not_pointer(monkeypatch, tmp_path):
    _patch_basic_pipeline(monkeypatch, artifact=_isotonic_artifact(status="calibration_skipped_insufficient_training_variance"))

    result = _produce(tmp_path)

    assert result["status"] == "audit_not_promoted"
    assert result["pointer_updated"] is False
    assert "status" in str(result["eligibility_reason"])
    assert result["artifact_path"].is_file()
    assert not current_pointer_path(ticker="SPY", horizon="5c", data_root=tmp_path, artifact_kind="isotonic").exists()


def test_isotonic_insufficient_holdout_samples_writes_artifact_but_not_pointer(monkeypatch, tmp_path):
    _patch_basic_pipeline(
        monkeypatch,
        artifact=_isotonic_artifact(sample_gate={"aggregate_holdout": {"sufficient_sample": False, "n": 10}}),
    )

    result = _produce(tmp_path)

    assert result["status"] == "audit_not_promoted"
    assert result["pointer_updated"] is False
    assert "aggregate_holdout" in str(result["eligibility_reason"])
    assert result["artifact_path"].is_file()


def test_isotonic_invalid_cli_args_fail_explicitly():
    parser = build_arg_parser()

    with pytest.raises(SystemExit) as excinfo:
        parser.parse_args(["--ticker", "SPY"])

    assert excinfo.value.code == 2


def test_isotonic_lineage_hash_matches_locked_recipe():
    artifact = _isotonic_artifact(model={"z": [2, 1], "a": {"b": 3}})
    import hashlib

    model_json = json.dumps(artifact["model"], sort_keys=True, separators=(",", ":"))
    expected = f"cal-test-run:{hashlib.sha256(model_json.encode('utf-8')).hexdigest()}"

    assert compute_calibration_lineage_id(artifact) == expected


def test_isotonic_atomic_pointer_write_never_partial(monkeypatch, tmp_path):
    pointer = tmp_path / "current.json"
    pointer.write_text(json.dumps({"artifact_relative_path": "old.json"}), encoding="utf-8")

    def fail_replace(src, dst):
        raise OSError("simulated replace failure")

    monkeypatch.setattr(os, "replace", fail_replace)

    with pytest.raises(OSError):
        update_current_pointer_atomically(artifact_relative_path="new.json", pointer_path=pointer)

    assert json.loads(pointer.read_text(encoding="utf-8")) == {"artifact_relative_path": "old.json"}


def test_isotonic_path_convention_under_isotonic_subdir():
    path = artifact_output_path(
        ticker="SPY",
        horizon="5c",
        calibration_run_id="cal-test-run",
        data_root=Path("DATA_ROOT"),
        artifact_kind="isotonic",
    )

    assert path == Path("DATA_ROOT") / "v2_calibration" / "isotonic" / "A" / "A1" / "SPY" / "5c" / "cal-test-run.json"


def test_isotonic_no_partial_artifact_or_pointer_on_failure(monkeypatch, tmp_path):
    _patch_basic_pipeline(monkeypatch)

    def fail_fit(rows, *, horizon, split):
        raise RuntimeError("simulated isotonic failure")

    monkeypatch.setattr("calibration.a1_isotonic_artifact_production.fit_a1_isotonic_artifact", fail_fit)

    with pytest.raises(RuntimeError):
        _produce(tmp_path)

    assert not list(tmp_path.rglob("*.json"))


def test_is_eligible_for_current_pointer_isotonic_returns_reason_per_gate():
    valid = _isotonic_lifecycle_artifact()

    assert is_eligible_for_current_pointer_isotonic(valid) == (True, None)
    assert is_eligible_for_current_pointer_isotonic({**valid, "schema_version": "bad"})[0] is False
    assert is_eligible_for_current_pointer_isotonic({**valid, "artifact_lifecycle_schema_version": "bad"})[0] is False
    assert is_eligible_for_current_pointer_isotonic({**valid, "ticker_universe": []})[0] is False
    assert is_eligible_for_current_pointer_isotonic({**valid, "horizon": None})[0] is False
    assert is_eligible_for_current_pointer_isotonic({**valid, "status": "calibration_skipped"})[0] is False
    assert is_eligible_for_current_pointer_isotonic({**valid, "model": {}})[0] is False
    assert is_eligible_for_current_pointer_isotonic(
        {**valid, "sample_gate": {"aggregate_holdout": {"sufficient_sample": False}}}
    )[0] is False
    assert is_eligible_for_current_pointer_isotonic({**valid, "calibration_lineage_id": ""})[0] is False


def test_existing_conformal_path_helpers_unchanged_with_default_artifact_kind():
    assert artifact_output_path(
        ticker="SPY",
        horizon="5c",
        calibration_run_id="cal-test-run",
        data_root=Path("DATA_ROOT"),
    ) == Path("DATA_ROOT") / "v2_calibration" / "conformal" / "A" / "A1" / "SPY" / "5c" / "cal-test-run.json"
    assert current_pointer_path(
        ticker="SPY",
        horizon="5c",
        data_root=Path("DATA_ROOT"),
    ) == Path("DATA_ROOT") / "v2_calibration" / "conformal" / "A" / "A1" / "SPY" / "5c" / "_current.json"


def _isotonic_lifecycle_artifact() -> dict:
    artifact = _isotonic_artifact()
    lineage = compute_calibration_lineage_id(artifact)
    return {
        **artifact,
        "ticker_universe": ["SPY"],
        "governed_max_age_seconds": 691200,
        "generated_at_epoch_seconds": 1000,
        "calibration_lineage_id": lineage,
        "artifact_lifecycle_schema_version": "1",
    }


def _patch_basic_pipeline(monkeypatch, *, artifact: dict | None = None) -> None:
    monkeypatch.setattr(
        "calibration.a1_isotonic_artifact_production.load_a1_calibration_rows",
        lambda db_path, *, horizon: [{"ticker": "SPY", "decision_ts_utc": 2.5}],
    )
    monkeypatch.setattr(
        "calibration.a1_isotonic_artifact_production.fit_a1_isotonic_artifact",
        lambda rows, *, horizon, split: artifact or _isotonic_artifact(),
    )


def _produce(tmp_path):
    return produce_a1_isotonic_artifact(
        db_path=Path("unused.db"),
        ticker="SPY",
        horizon="5c",
        train_start=0,
        train_end=1,
        calibration_start=1,
        calibration_end=2,
        holdout_start=2,
        holdout_end=3,
        governed_max_age_seconds=691200,
        now_epoch_seconds=1000,
        data_root=tmp_path,
    )
