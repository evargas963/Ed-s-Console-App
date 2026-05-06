from __future__ import annotations

import json
from pathlib import Path

from calibration.a1_conformal_artifact_production import (
    augment_artifact_with_lifecycle_fields,
    current_pointer_path,
    update_current_pointer_atomically,
    write_artifact_atomically,
)
from v2_decision.a1_isotonic_artifact_loader import load_a1_isotonic_artifact


def _artifact(**overrides) -> dict:
    lifecycle_ticker = overrides.pop("lifecycle_ticker", "SPY")
    governed_max_age_seconds = overrides.pop("governed_max_age_seconds", 3600)
    generated_at_epoch_seconds = overrides.pop("generated_at_epoch_seconds", 1000)
    calibration_lineage_id = overrides.pop("calibration_lineage_id", "cal-test-run:hash")
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
            "train_start": 0,
            "train_end": 1,
            "calibration_start": 1,
            "calibration_end": 2,
            "holdout_start": 2,
            "holdout_end": 3,
        },
        "status": "ok",
        "reason": None,
        "model": {"type": "isotonic_regression", "x_thresholds": [0.0, 1.0], "y_thresholds": [0.2, 0.8]},
    }
    base.update(overrides)
    return augment_artifact_with_lifecycle_fields(
        artifact=base,
        ticker=str(lifecycle_ticker),
        governed_max_age_seconds=float(governed_max_age_seconds),
        generated_at_epoch_seconds=float(generated_at_epoch_seconds),
        calibration_lineage_id=str(calibration_lineage_id),
    )


def _write_pointer_artifact(tmp_path: Path, artifact: dict) -> Path:
    data_root = tmp_path / "data"
    artifact_path = (
        data_root
        / "v2_calibration"
        / "isotonic"
        / "A"
        / "A1"
        / "SPY"
        / "5c"
        / "cal-test-run.json"
    )
    write_artifact_atomically(artifact=artifact, output_path=artifact_path)
    update_current_pointer_atomically(
        artifact_relative_path="v2_calibration/isotonic/A/A1/SPY/5c/cal-test-run.json",
        pointer_path=current_pointer_path(ticker="SPY", horizon="5c", data_root=data_root, artifact_kind="isotonic"),
    )
    return artifact_path


def test_load_returns_isotonic_artifact_when_pointer_and_eligibility_pass(tmp_path, monkeypatch):
    artifact = _artifact()
    _write_pointer_artifact(tmp_path, artifact)
    monkeypatch.chdir(tmp_path)

    loaded = load_a1_isotonic_artifact(ticker="SPY", horizon="5c", now_epoch_seconds=1100)

    assert loaded == artifact


def test_load_returns_none_when_isotonic_pointer_missing(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    assert load_a1_isotonic_artifact(ticker="SPY", horizon="5c", now_epoch_seconds=1100) is None


def test_load_returns_none_when_isotonic_pointer_points_to_nonexistent_artifact(tmp_path, monkeypatch):
    pointer = current_pointer_path(ticker="SPY", horizon="5c", data_root=tmp_path / "data", artifact_kind="isotonic")
    update_current_pointer_atomically(
        artifact_relative_path="v2_calibration/isotonic/A/A1/SPY/5c/missing.json",
        pointer_path=pointer,
    )
    monkeypatch.chdir(tmp_path)

    assert load_a1_isotonic_artifact(ticker="SPY", horizon="5c", now_epoch_seconds=1100) is None


def test_load_returns_none_when_isotonic_artifact_schema_version_mismatch(tmp_path, monkeypatch):
    artifact = _artifact(schema_version="bad")
    _write_pointer_artifact(tmp_path, artifact)
    monkeypatch.chdir(tmp_path)

    assert load_a1_isotonic_artifact(ticker="SPY", horizon="5c", now_epoch_seconds=1100) is None


def test_load_returns_none_when_isotonic_lifecycle_schema_version_mismatch(tmp_path, monkeypatch):
    artifact = _artifact()
    artifact["artifact_lifecycle_schema_version"] = "bad"
    _write_pointer_artifact(tmp_path, artifact)
    monkeypatch.chdir(tmp_path)

    assert load_a1_isotonic_artifact(ticker="SPY", horizon="5c", now_epoch_seconds=1100) is None


def test_load_returns_none_when_isotonic_ticker_universe_excludes_requested_ticker(tmp_path, monkeypatch):
    artifact = _artifact(lifecycle_ticker="QQQ")
    _write_pointer_artifact(tmp_path, artifact)
    monkeypatch.chdir(tmp_path)

    assert load_a1_isotonic_artifact(ticker="SPY", horizon="5c", now_epoch_seconds=1100) is None


def test_load_returns_none_when_isotonic_horizon_mismatch(tmp_path, monkeypatch):
    artifact = _artifact(horizon="15c")
    _write_pointer_artifact(tmp_path, artifact)
    monkeypatch.chdir(tmp_path)

    assert load_a1_isotonic_artifact(ticker="SPY", horizon="5c", now_epoch_seconds=1100) is None


def test_load_returns_none_when_isotonic_artifact_stale_per_governed_max_age(tmp_path, monkeypatch):
    artifact = _artifact(governed_max_age_seconds=10, generated_at_epoch_seconds=1000)
    _write_pointer_artifact(tmp_path, artifact)
    monkeypatch.chdir(tmp_path)

    assert load_a1_isotonic_artifact(ticker="SPY", horizon="5c", now_epoch_seconds=1011) is None


def test_load_returns_none_when_isotonic_artifact_json_malformed(tmp_path, monkeypatch):
    artifact_path = _write_pointer_artifact(tmp_path, _artifact())
    artifact_path.write_text("{not json", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    assert load_a1_isotonic_artifact(ticker="SPY", horizon="5c", now_epoch_seconds=1100) is None


def test_load_returns_none_when_isotonic_required_field_missing(tmp_path, monkeypatch):
    artifact = _artifact()
    artifact.pop("calibration_lineage_id")
    _write_pointer_artifact(tmp_path, artifact)
    monkeypatch.chdir(tmp_path)

    assert load_a1_isotonic_artifact(ticker="SPY", horizon="5c", now_epoch_seconds=1100) is None


def test_load_does_not_raise_for_isotonic_unexpected_io_failure(tmp_path, monkeypatch):
    _write_pointer_artifact(tmp_path, _artifact())
    monkeypatch.chdir(tmp_path)

    def fail_read_text(self, *args, **kwargs):
        raise OSError("simulated io failure")

    monkeypatch.setattr(Path, "read_text", fail_read_text)

    assert load_a1_isotonic_artifact(ticker="SPY", horizon="5c", now_epoch_seconds=1100) is None


def test_load_returns_none_when_isotonic_pointer_json_malformed(tmp_path, monkeypatch):
    pointer = current_pointer_path(ticker="SPY", horizon="5c", data_root=tmp_path / "data", artifact_kind="isotonic")
    pointer.parent.mkdir(parents=True, exist_ok=True)
    pointer.write_text(json.dumps({"not_artifact_relative_path": "x"}), encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    assert load_a1_isotonic_artifact(ticker="SPY", horizon="5c", now_epoch_seconds=1100) is None


def test_load_uses_now_epoch_seconds_parameter_for_isotonic(tmp_path, monkeypatch):
    artifact = _artifact(governed_max_age_seconds=10, generated_at_epoch_seconds=1000)
    _write_pointer_artifact(tmp_path, artifact)
    monkeypatch.chdir(tmp_path)

    assert load_a1_isotonic_artifact(ticker="SPY", horizon="5c", now_epoch_seconds=1005) == artifact
    assert load_a1_isotonic_artifact(ticker="SPY", horizon="5c", now_epoch_seconds=1011) is None
