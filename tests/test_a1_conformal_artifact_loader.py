from __future__ import annotations

import json
from pathlib import Path

from calibration.a1_conformal_artifact_production import (
    augment_conformal_artifact_with_lifecycle_fields,
    current_pointer_path,
    write_artifact_atomically,
    update_current_pointer_atomically,
)
from v2_decision.a1_conformal_artifact_loader import load_a1_conformal_artifact


def _artifact(**overrides) -> dict:
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
    return augment_conformal_artifact_with_lifecycle_fields(
        conformal_artifact=base,
        ticker=str(overrides.pop("lifecycle_ticker", "SPY")),
        governed_max_age_seconds=float(overrides.pop("governed_max_age_seconds", 3600)),
        generated_at_epoch_seconds=float(overrides.pop("generated_at_epoch_seconds", 1000)),
        calibration_lineage_id=str(overrides.pop("calibration_lineage_id", "cal-test-run:hash")),
    )


def _write_pointer_artifact(tmp_path: Path, artifact: dict) -> Path:
    data_root = tmp_path / "data"
    artifact_path = (
        data_root
        / "v2_calibration"
        / "conformal"
        / "A"
        / "A1"
        / "SPY"
        / "5c"
        / "cal-test-run.json"
    )
    write_artifact_atomically(artifact=artifact, output_path=artifact_path)
    update_current_pointer_atomically(
        artifact_relative_path="v2_calibration/conformal/A/A1/SPY/5c/cal-test-run.json",
        pointer_path=current_pointer_path(ticker="SPY", horizon="5c", data_root=data_root),
    )
    return artifact_path


def test_load_returns_artifact_when_pointer_and_eligibility_pass(tmp_path, monkeypatch):
    artifact = _artifact()
    _write_pointer_artifact(tmp_path, artifact)
    monkeypatch.chdir(tmp_path)

    loaded = load_a1_conformal_artifact(ticker="SPY", horizon="5c", now_epoch_seconds=1100)

    assert loaded == artifact


def test_load_returns_none_when_pointer_missing(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    assert load_a1_conformal_artifact(ticker="SPY", horizon="5c", now_epoch_seconds=1100) is None


def test_load_returns_none_when_pointer_points_to_nonexistent_artifact(tmp_path, monkeypatch):
    pointer = current_pointer_path(ticker="SPY", horizon="5c", data_root=tmp_path / "data")
    update_current_pointer_atomically(
        artifact_relative_path="v2_calibration/conformal/A/A1/SPY/5c/missing.json",
        pointer_path=pointer,
    )
    monkeypatch.chdir(tmp_path)

    assert load_a1_conformal_artifact(ticker="SPY", horizon="5c", now_epoch_seconds=1100) is None


def test_load_returns_none_when_artifact_schema_version_mismatch(tmp_path, monkeypatch):
    artifact = _artifact(schema_version="bad")
    _write_pointer_artifact(tmp_path, artifact)
    monkeypatch.chdir(tmp_path)

    assert load_a1_conformal_artifact(ticker="SPY", horizon="5c", now_epoch_seconds=1100) is None


def test_load_returns_none_when_lifecycle_schema_version_mismatch(tmp_path, monkeypatch):
    artifact = _artifact()
    artifact["artifact_lifecycle_schema_version"] = "bad"
    _write_pointer_artifact(tmp_path, artifact)
    monkeypatch.chdir(tmp_path)

    assert load_a1_conformal_artifact(ticker="SPY", horizon="5c", now_epoch_seconds=1100) is None


def test_load_returns_none_when_ticker_universe_excludes_requested_ticker(tmp_path, monkeypatch):
    artifact = _artifact(lifecycle_ticker="QQQ")
    _write_pointer_artifact(tmp_path, artifact)
    monkeypatch.chdir(tmp_path)

    assert load_a1_conformal_artifact(ticker="SPY", horizon="5c", now_epoch_seconds=1100) is None


def test_load_returns_none_when_horizon_mismatch(tmp_path, monkeypatch):
    artifact = _artifact(horizon="15c")
    _write_pointer_artifact(tmp_path, artifact)
    monkeypatch.chdir(tmp_path)

    assert load_a1_conformal_artifact(ticker="SPY", horizon="5c", now_epoch_seconds=1100) is None


def test_load_returns_none_when_artifact_stale_per_governed_max_age(tmp_path, monkeypatch):
    artifact = _artifact(governed_max_age_seconds=10, generated_at_epoch_seconds=1000)
    _write_pointer_artifact(tmp_path, artifact)
    monkeypatch.chdir(tmp_path)

    assert load_a1_conformal_artifact(ticker="SPY", horizon="5c", now_epoch_seconds=1011) is None


def test_load_returns_none_when_artifact_json_malformed(tmp_path, monkeypatch):
    artifact_path = _write_pointer_artifact(tmp_path, _artifact())
    artifact_path.write_text("{not json", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    assert load_a1_conformal_artifact(ticker="SPY", horizon="5c", now_epoch_seconds=1100) is None


def test_load_returns_none_when_required_field_missing(tmp_path, monkeypatch):
    artifact = _artifact()
    artifact.pop("calibration_lineage_id")
    _write_pointer_artifact(tmp_path, artifact)
    monkeypatch.chdir(tmp_path)

    assert load_a1_conformal_artifact(ticker="SPY", horizon="5c", now_epoch_seconds=1100) is None


def test_load_does_not_raise_for_unexpected_io_failure(tmp_path, monkeypatch):
    _write_pointer_artifact(tmp_path, _artifact())
    monkeypatch.chdir(tmp_path)

    def fail_read_text(self, *args, **kwargs):
        raise OSError("simulated io failure")

    monkeypatch.setattr(Path, "read_text", fail_read_text)

    assert load_a1_conformal_artifact(ticker="SPY", horizon="5c", now_epoch_seconds=1100) is None


def test_loader_uses_now_epoch_seconds_parameter_when_provided(tmp_path, monkeypatch):
    artifact = _artifact(governed_max_age_seconds=10, generated_at_epoch_seconds=1000)
    _write_pointer_artifact(tmp_path, artifact)
    monkeypatch.chdir(tmp_path)

    assert load_a1_conformal_artifact(ticker="SPY", horizon="5c", now_epoch_seconds=1005) == artifact
    assert load_a1_conformal_artifact(ticker="SPY", horizon="5c", now_epoch_seconds=1011) is None


def test_load_returns_none_when_pointer_json_malformed(tmp_path, monkeypatch):
    pointer = current_pointer_path(ticker="SPY", horizon="5c", data_root=tmp_path / "data")
    pointer.parent.mkdir(parents=True, exist_ok=True)
    pointer.write_text(json.dumps({"not_artifact_relative_path": "x"}), encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    assert load_a1_conformal_artifact(ticker="SPY", horizon="5c", now_epoch_seconds=1100) is None
