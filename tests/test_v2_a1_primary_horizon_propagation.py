from __future__ import annotations

import dataclasses
import time

import pytest

from market_state import MarketState
from server import _ms_to_dict
from v2_decision.a1_conformal_promotion import derive_a1_conformal_bounds


def _artifact(**overrides) -> dict:
    now = overrides.pop("now", time.time())
    base = {
        "schema_version": "1",
        "horizon": "5c",
        "status": "ok",
        "interval_model": {
            "type": "split_conformal_probability_band",
            "score_quantile": 0.1,
        },
        "coverage_evaluation": {
            "source": "separate_evaluation_predictions",
            "same_rows_as_quantile_fit": False,
        },
        "evaluation_diagnostics": {
            "empirical_coverage": 0.9,
        },
        "sample_gate": {
            "aggregate_holdout": {
                "sufficient_sample": True,
                "n": 500,
            },
        },
        "governed_max_age_seconds": 3600,
        "generated_at_epoch_seconds": now,
        "conformal_run_id": "a1-conformal-test",
        "calibration_lineage_id": "cal-run:test-isotonic-artifact",
    }
    base.update(overrides)
    return base


def _ms_dict(**overrides) -> dict:
    base = {
        "primary_horizon": "5c",
        "a1_calibrated_probability": 0.7,
        "a1_calibrated_probability_lineage_id": "cal-run:test-isotonic-artifact",
        "a1_conformal_artifact": _artifact(),
    }
    base.update(overrides)
    return base


def test_market_state_primary_horizon_field_exists_on_dataclass():
    fields = {field.name for field in dataclasses.fields(MarketState)}

    assert "primary_horizon" in fields


@pytest.mark.parametrize("primary_horizon", ("1c", "5c", "15c", "60c"))
def test_ms_to_dict_propagates_primary_horizon(primary_horizon):
    ms = MarketState(primary_horizon=primary_horizon)

    ms_dict = _ms_to_dict(ms)

    assert ms_dict["primary_horizon"] == primary_horizon


def test_derive_a1_conformal_bounds_accepts_matching_primary_horizon_via_ms_dict():
    low, high, status = derive_a1_conformal_bounds(_ms_dict(primary_horizon="5c"))

    assert status == "ok"
    assert low == 0.6
    assert high == 0.8


def test_derive_a1_conformal_bounds_rejects_horizon_mismatch_via_ms_dict():
    low, high, status = derive_a1_conformal_bounds(
        _ms_dict(primary_horizon="5c", a1_conformal_artifact=_artifact(horizon="15c"))
    )

    assert status == "precondition_5_horizon_match_failed"
    assert low is None
    assert high is None
