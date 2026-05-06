from __future__ import annotations

from copy import deepcopy

from calibration.a1_conformal_artifact_production import compute_calibration_lineage_id
from v2_decision.a1_isotonic_runtime import apply_a1_v2_calibration_to_raw_probability


def _artifact(**overrides) -> dict:
    artifact = {
        "calibration_run_id": "cal-test-run",
        "model": {
            "type": "isotonic_regression",
            "x_thresholds": [0.0, 1.0],
            "y_thresholds": [0.2, 0.8],
        },
    }
    artifact.update(overrides)
    return artifact


def test_apply_returns_calibrated_probability_and_lineage_id_when_inputs_valid():
    artifact = _artifact()

    calibrated, lineage_id = apply_a1_v2_calibration_to_raw_probability(
        isotonic_artifact=artifact,
        raw_probability=0.25,
    )

    assert calibrated == 0.35
    assert lineage_id == compute_calibration_lineage_id(artifact)


def test_apply_returns_none_when_artifact_is_none():
    assert apply_a1_v2_calibration_to_raw_probability(isotonic_artifact=None, raw_probability=0.5) == (None, None)


def test_apply_returns_none_when_artifact_lacks_model_key():
    assert apply_a1_v2_calibration_to_raw_probability(
        isotonic_artifact={"calibration_run_id": "cal-test-run"},
        raw_probability=0.5,
    ) == (None, None)


def test_apply_returns_none_when_artifact_model_is_not_dict():
    assert apply_a1_v2_calibration_to_raw_probability(
        isotonic_artifact=_artifact(model="not-a-dict"),
        raw_probability=0.5,
    ) == (None, None)


def test_apply_returns_none_when_raw_probability_is_none():
    assert apply_a1_v2_calibration_to_raw_probability(isotonic_artifact=_artifact(), raw_probability=None) == (
        None,
        None,
    )


def test_apply_returns_none_when_raw_probability_below_zero():
    assert apply_a1_v2_calibration_to_raw_probability(isotonic_artifact=_artifact(), raw_probability=-0.01) == (
        None,
        None,
    )


def test_apply_returns_none_when_raw_probability_above_one():
    assert apply_a1_v2_calibration_to_raw_probability(isotonic_artifact=_artifact(), raw_probability=1.01) == (
        None,
        None,
    )


def test_apply_returns_none_when_raw_probability_is_not_numeric():
    assert apply_a1_v2_calibration_to_raw_probability(isotonic_artifact=_artifact(), raw_probability="0.5") == (
        None,
        None,
    )


def test_apply_returns_none_when_calibrated_probability_out_of_range(monkeypatch):
    monkeypatch.setattr("v2_decision.a1_isotonic_runtime.apply_isotonic_model", lambda model, raw: 1.5)

    assert apply_a1_v2_calibration_to_raw_probability(isotonic_artifact=_artifact(), raw_probability=0.5) == (
        None,
        None,
    )


def test_apply_does_not_raise_on_unexpected_failure(monkeypatch):
    def fail_apply(model, raw_probability):
        raise RuntimeError("simulated apply failure")

    monkeypatch.setattr("v2_decision.a1_isotonic_runtime.apply_isotonic_model", fail_apply)

    assert apply_a1_v2_calibration_to_raw_probability(isotonic_artifact=_artifact(), raw_probability=0.5) == (
        None,
        None,
    )


def test_apply_lineage_id_matches_locked_recipe():
    artifact = _artifact()

    assert apply_a1_v2_calibration_to_raw_probability(
        isotonic_artifact=artifact,
        raw_probability=0.5,
    )[1] == compute_calibration_lineage_id(artifact)


def test_apply_does_not_mutate_artifact():
    artifact = _artifact()
    before = deepcopy(artifact)

    apply_a1_v2_calibration_to_raw_probability(isotonic_artifact=artifact, raw_probability=0.5)

    assert artifact == before
