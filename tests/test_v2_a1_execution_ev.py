from __future__ import annotations

import pytest

from calibration.v2_a1_conformal import build_a1_conformal_artifact
from calibration.v2_a1_ev_bounds import build_a1_ev_bounds_artifact
from calibration.v2_a1_execution_ev import (
    A1_EXECUTION_EV_REQUIRED_REGISTRY_ENTRIES,
    build_a1_execution_ev_artifact,
    validate_normalized_execution_inputs,
)
from v2_decision.a2_option_expression import build_a2_option_expression


BASE_MS = 1_900_000_000_000.0


def _prediction(idx: int, *, probability: float, label: int) -> dict:
    return {
        "calibration_row_id": idx,
        "ticker": "SPY",
        "decision_ts_utc": 1_900_000_000.0 + idx * 60.0,
        "calibrated_probability": probability,
        "label": label,
        "volatility_regime": "normal",
        "time_of_day_bucket": "midday",
        "expiry_dte_bucket": "not_options_applicable",
        "direction": "long",
        "primary_horizon": "5c",
    }


def _clean_rows(n: int = 500) -> list[dict]:
    return [
        _prediction(i, probability=0.95 if i % 2 else 0.05, label=1 if i % 2 else 0)
        for i in range(n)
    ]


def _calibration_artifact(rows: list[dict]) -> dict:
    return {
        "calibration_run_id": "a1-5c-calibration-run-test",
        "calibration_window_id": "a1-5c-calibration-window-test",
        "module_id": "A",
        "expression_profile_id": "A1",
        "horizon": "5c",
        "holdout_predictions": rows,
    }


def _ev_bounds(status: str | None = None) -> dict:
    conformal = build_a1_conformal_artifact(_calibration_artifact(_clean_rows()))
    ev = build_a1_ev_bounds_artifact(conformal, reward_r=2.0)
    return {**ev, "status": status} if status else ev


def _normalized_contract(**overrides) -> dict:
    base = {
        "symbol": "SPY_050626C00500000",
        "bid": 1.1,
        "ask": 1.2,
        "mark": 1.15,
        "bidSize": 20,
        "askSize": 22,
        "bidAskSize": "20X22",
        "quoteTimeInLong": BASE_MS - 100.0,
        "tradeTimeInLong": BASE_MS - 90.0,
        "totalVolume": 1000,
        "openInterest": 5000,
        "putCall": "CALL",
        "strikePrice": 500.0,
        "daysToExpiration": 0,
        "multiplier": 100,
    }
    return {**base, **overrides}


def _valid_cost_model(**overrides) -> dict:
    base = {
        "model_id": "execution_cost_model_v0_scaffold",
        "source": "derived_because_schwab_does_not_provide",
        "registry_entries": list(A1_EXECUTION_EV_REQUIRED_REGISTRY_ENTRIES),
        "validated": True,
        "min_fill_history_n": 500,
        "fill_history_n": 500,
        "capacity_model_available": True,
        "expected_cost_r": 0.1,
    }
    return {**base, **overrides}


def test_execution_ev_missing_model_skips_without_synthetic_adjusted_ev():
    artifact = build_a1_execution_ev_artifact(_ev_bounds())

    assert artifact["status"] == "execution_ev_skipped_missing_execution_cost_model"
    assert artifact["reason"] == "fill_slippage_impact_model_unavailable"
    assert artifact["execution_ev_model"] is None
    assert artifact["execution_adjusted_ev"] == []
    assert artifact["runtime_adapter_unchanged"] is True


def test_execution_ev_cascades_skipped_ev_bounds():
    artifact = build_a1_execution_ev_artifact(_ev_bounds("ev_bounds_skipped_missing_conformal_intervals"))

    assert artifact["status"] == "execution_ev_skipped_upstream_ev_bounds_unavailable"
    assert artifact["reason"].startswith("ev_bounds_skipped_missing_conformal_intervals:")
    assert artifact["execution_adjusted_ev"] == []


def test_execution_ev_cascades_degraded_ev_bounds():
    artifact = build_a1_execution_ev_artifact(_ev_bounds("ev_bounds_degraded_empirical_coverage"))

    assert artifact["status"] == "execution_ev_skipped_upstream_ev_bounds_degraded"
    assert artifact["reason"].startswith("ev_bounds_degraded_empirical_coverage:")
    assert artifact["execution_adjusted_ev"] == []


def test_execution_ev_warning_ev_bounds_passes_with_valid_model_and_retains_warning():
    artifact = build_a1_execution_ev_artifact(
        _ev_bounds("ev_bounds_warning_upstream_conformal_below_nominal"),
        execution_cost_model=_valid_cost_model(),
        normalized_contract=_normalized_contract(),
        decision_time_ms=BASE_MS,
    )

    assert artifact["status"] == "execution_ev_warning_upstream_ev_bounds"
    assert artifact["reason"].startswith("ev_bounds_warning_upstream_conformal_below_nominal:")
    assert artifact["execution_ev_model"]["validated"] is True
    assert artifact["execution_adjusted_ev"]


def test_execution_ev_missing_normalized_schwab_inputs_skips_explicitly():
    contract = _normalized_contract(bid=None)

    artifact = build_a1_execution_ev_artifact(
        _ev_bounds(),
        execution_cost_model=_valid_cost_model(),
        normalized_contract=contract,
        decision_time_ms=BASE_MS,
    )

    assert artifact["status"] == "execution_ev_skipped_missing_normalized_schwab_quote_inputs"
    assert artifact["reason"] == "missing_required_normalized_quote_fields"
    assert artifact["execution_adjusted_ev"] == []
    assert "bid" in artifact["normalized_quote_input_check"]["missing_fields"]
    assert artifact["normalized_quote_input_check"]["source_boundary"] == "chains.contract_fields"


def test_execution_ev_stale_quote_inputs_skip_explicitly():
    contract = _normalized_contract(quoteTimeInLong=BASE_MS - 10_000.0)

    artifact = build_a1_execution_ev_artifact(
        _ev_bounds(),
        execution_cost_model=_valid_cost_model(),
        normalized_contract=contract,
        decision_time_ms=BASE_MS,
    )

    assert artifact["status"] == "execution_ev_skipped_stale_quote_inputs"
    assert artifact["reason"] == "quote_staleness_exceeds_o20"
    assert artifact["normalized_quote_input_check"]["quote_staleness_ms"] > 2_000
    assert artifact["execution_adjusted_ev"] == []


def test_execution_ev_insufficient_fill_history_skips_before_cost_application():
    artifact = build_a1_execution_ev_artifact(
        _ev_bounds(),
        execution_cost_model=_valid_cost_model(fill_history_n=499),
        normalized_contract=_normalized_contract(),
        decision_time_ms=BASE_MS,
    )

    assert artifact["status"] == "execution_ev_skipped_missing_fill_history"
    assert artifact["reason"] == "fill_history_below_o24_style_floor"
    assert artifact["execution_adjusted_ev"] == []


def test_execution_ev_valid_model_subtracts_explicit_cost_from_bounds():
    artifact = build_a1_execution_ev_artifact(
        _ev_bounds(),
        execution_cost_model=_valid_cost_model(expected_cost_r=0.1),
        normalized_contract=_normalized_contract(),
        decision_time_ms=BASE_MS,
    )

    row = artifact["execution_adjusted_ev"][0]
    assert artifact["status"] == "ok"
    assert row["execution_adjusted_EV_lower"] == pytest.approx(row["EV_lower"] - 0.1)
    assert row["execution_adjusted_EV_upper"] == pytest.approx(row["EV_upper"] - 0.1)
    assert artifact["execution_ev_model"]["registry_entries"] == list(A1_EXECUTION_EV_REQUIRED_REGISTRY_ENTRIES)
    assert artifact["execution_ev_model"]["expected_cost_r"] == pytest.approx(0.1)


def test_execution_ev_disclosure_inherits_ev_bounds_and_names_execution_assumptions():
    ev_bounds = _ev_bounds()

    artifact = build_a1_execution_ev_artifact(ev_bounds)
    disclosure = artifact["approximate_guarantee_disclosure"]

    assert disclosure["inherits"] == ev_bounds["approximate_guarantee_disclosure"]
    assert "top-of-book quote inputs represent actionable liquidity at decision time" in disclosure["assumptions"]
    assert "fill_rate_warmup_insufficient" in disclosure["likely_violation_modes"]
    assert "market_impact_nonlinearity" in disclosure["likely_violation_modes"]
    assert disclosure["qualification"] == "approximate_not_exact"


def test_validate_normalized_execution_inputs_documents_schwab_source_paths():
    result = validate_normalized_execution_inputs(_normalized_contract(), decision_time_ms=BASE_MS)

    assert result["ok"] is True
    assert result["source_boundary"] == "chains.contract_fields"
    assert "chains.callExpDateMap.*.bid" in result["source_paths"]["bid"]
    assert "chains.putExpDateMap.*.bidAskSize" in result["source_paths"]["bidAskSize"]


def test_execution_ev_scaffold_does_not_change_a2_runtime_execution_ev_field():
    a2 = build_a2_option_expression(
        {
            "ticker": "SPY",
            "selected_contract": _normalized_contract(),
            "selected_strike": 500.0,
            "option_right": "CALL",
            "decision_time_ms": BASE_MS,
            "server_time_ms": BASE_MS,
        },
        {
            "decision": {
                "direction": {"value": "long", "source": "v1_approximation"},
                "P_entry_success": {"value": 0.64, "source": "v1_approximation"},
            }
        },
    )

    assert a2["probability_and_ev"]["execution_adjusted_EV"]["source"] == "not_implemented"
    assert a2["execution"]["fill_probability"]["source"] == "not_implemented"
    assert a2["execution"]["slippage_estimate"]["source"] == "not_implemented"
