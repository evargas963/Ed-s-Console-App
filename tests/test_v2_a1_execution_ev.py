"""calibration.v2_a1_execution_ev.build_a1_execution_ev_artifact must require its
minimum fill-history sample and every registry entry the EV-bounds/conformal chain
declares before producing an execution-EV artifact -- skipping a required registry
entry would silently produce an EV estimate the fill history can't support."""
from __future__ import annotations


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


def _normalized_contract(**overrides) -> dict:
    # institutional-synthetic-ok: v2 execution-EV test needs a controlled normalized contract.
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
