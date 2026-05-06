from __future__ import annotations

import time

import pytest

import v2_decision.module_a_adapter as adapter
from v2_decision.module_a_adapter import build_module_a_a1_decision
from v2_decision.schema import validate_v2_decision


def _ms(**overrides) -> dict:
    now = time.time()
    base = {
        "ticker": "SPY",
        "fusion_available": True,
        "fusion_dominant_direction": "up",
        "fusion_dominant_prob": 0.64,
        "fusion_confidence": "high",
        "is_no_trade": False,
        "execution_mode": "STANDARD",
        "primary_horizon": "5c",
        "a1_calibrated_probability": 0.7,
        "a1_conformal_artifact": _artifact(now=now),
    }
    base.update(overrides)
    return base


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
    }
    base.update(overrides)
    return base


def _decision(ms: dict | None = None) -> dict:
    return build_module_a_a1_decision(ms or _ms())["decision"]


def _bounds(ms: dict | None = None) -> tuple[dict, dict]:
    decision = _decision(ms)
    return decision["p_low"], decision["p_high"]


def test_module_a_adapter_delegates_conformal_bounds(monkeypatch):
    """Contract: A1_CONFORMAL_INTERVAL_PROMOTION_CONTRACT.md test bar - adapter delegates."""
    calls: list[dict] = []

    def fake_derive(ms_dict):
        calls.append(ms_dict)
        return 0.25, 0.75, "ok"

    monkeypatch.setattr(adapter, "derive_a1_conformal_bounds", fake_derive, raising=False)

    low, high = _bounds(_ms())

    assert len(calls) == 1
    assert low == {"value": 0.25, "source": "v1_approximation", "detail": "a1_conformal_interval:ok"}
    assert high == {"value": 0.75, "source": "v1_approximation", "detail": "a1_conformal_interval:ok"}


def test_all_preconditions_pass_populates_v1_approximation_bounds():
    """Contract: all seven preconditions pass -> p_low/p_high populated."""
    low, high = _bounds()

    assert low == {
        "value": 0.6,
        "source": "v1_approximation",
        "detail": "a1_conformal_interval:ok",
    }
    assert high == {
        "value": 0.8,
        "source": "v1_approximation",
        "detail": "a1_conformal_interval:ok",
    }


@pytest.mark.parametrize(
    ("ms_overrides", "expected_status"),
    [
        ({"a1_conformal_artifact": None}, "precondition_1_artifact_present_failed"),
        ({"a1_conformal_artifact": _artifact(schema_version="bad")}, "precondition_2_schema_version_failed"),
        (
            {
                "a1_conformal_artifact": _artifact(
                    coverage_evaluation={
                        "source": "same_holdout_as_quantile_fit",
                        "same_rows_as_quantile_fit": True,
                    }
                )
            },
            "precondition_3_honest_evaluation_failed",
        ),
        (
            {
                "a1_conformal_artifact": _artifact(
                    evaluation_diagnostics={"empirical_coverage": 0.84}
                )
            },
            "precondition_3_honest_evaluation_failed",
        ),
        (
            {
                "a1_conformal_artifact": _artifact(
                    sample_gate={"aggregate_holdout": {"sufficient_sample": False, "n": 10}}
                )
            },
            "precondition_4_aggregate_sample_threshold_failed",
        ),
        ({"primary_horizon": "15c"}, "precondition_5_horizon_match_failed"),
        (
            {
                "a1_conformal_artifact": _artifact(
                    calibration_run_id="not-a-freshness-proxy",
                    governed_max_age_seconds=None,
                    generated_at_epoch_seconds=None,
                )
            },
            "precondition_6_freshness_failed",
        ),
        ({"a1_calibrated_probability": 1.1}, "precondition_7_calibrated_probability_failed"),
    ],
)
def test_precondition_failures_keep_bounds_not_implemented(ms_overrides, expected_status):
    """Contract: each failed precondition leaves p_low/p_high not_implemented."""
    low, high = _bounds(_ms(**ms_overrides))

    assert low == {
        "value": None,
        "source": "not_implemented",
        "detail": f"a1_conformal_interval:{expected_status}",
    }
    assert high == {
        "value": None,
        "source": "not_implemented",
        "detail": f"a1_conformal_interval:{expected_status}",
    }


def test_no_synthetic_interval_biconditional():
    """Contract: source=v1_approximation iff value is non-None."""
    for ms in (_ms(), _ms(a1_conformal_artifact=None)):
        low, high = _bounds(ms)
        for leaf in (low, high):
            assert (leaf["source"] == "v1_approximation") == (leaf["value"] is not None)


def test_backward_compat_when_no_artifact_loadable():
    """Contract: absent artifact preserves current baseline leaves."""
    low, high = _bounds(_ms(a1_conformal_artifact=None))

    assert low == {
        "value": None,
        "source": "not_implemented",
        "detail": "a1_conformal_interval:precondition_1_artifact_present_failed",
    }
    assert high == {
        "value": None,
        "source": "not_implemented",
        "detail": "a1_conformal_interval:precondition_1_artifact_present_failed",
    }


def test_schema_validates_promoted_and_unpromoted_states():
    """Contract: schema walker accepts promoted and unpromoted p_low/p_high leaves."""
    validate_v2_decision(build_module_a_a1_decision(_ms()))
    validate_v2_decision(build_module_a_a1_decision(_ms(a1_conformal_artifact=None)))


def test_bounds_are_symmetric_across_predicate_states():
    """Contract: p_low/p_high populate together or neither does."""
    for ms in (_ms(), _ms(a1_conformal_artifact=None)):
        low, high = _bounds(ms)
        assert (low["value"] is None) == (high["value"] is None)
        assert low["source"] == high["source"]
