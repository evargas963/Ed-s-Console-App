"""Action 11.4: math_probabilities fail-closed on missing inputs."""

from __future__ import annotations

from math_probabilities import (
    compute_breakout_score,
    compute_dealer_pressure_index,
    compute_hedging_flow_score,
    compute_iwm_confluence,
    compute_probs,
    compute_smart_money_signal,
    compute_sweep_score,
    compute_vol_expansion_signal,
    flow_imbalance_normalized_with_fallback,
)


def test_compute_probs_none_when_no_weighted_outcomes():
    similar = [{"outcome_5c": None, "ts_utc": 1.0}, {"outcome_5c": "bad", "ts_utc": 2.0}]
    assert compute_probs(similar, "outcome_5c") is None
    assert compute_probs([], "outcome_5c") is None


def test_dpi_all_none_inputs():
    out = compute_dealer_pressure_index(None, None, None)
    assert out["direction"] is None
    assert out["magnitude"] is None
    assert out["raw"] is None


def test_hedging_flow_renormalizes_partial_inputs():
    out = compute_hedging_flow_score(0.5, None, None, None)
    assert out["raw"] == 0.5
    assert out["direction"] is not None
    all_none = compute_hedging_flow_score(None, None, None, None)
    assert all_none["raw"] is None
    assert all_none["direction"] is None


def test_breakout_score_none_when_all_inputs_missing():
    out = compute_breakout_score(None, None, None)
    assert out["label"] is None
    assert out["normalized"] is None


def test_vol_expansion_and_sweep_none_when_all_missing():
    vol = compute_vol_expansion_signal(None, None, None)
    assert vol["label"] is None
    sweep = compute_sweep_score(None, None, None)
    assert sweep["label"] is None


def test_iwm_confluence_all_none_quotes():
    out = compute_iwm_confluence(None, None, None)
    assert out["risk_regime"] is None
    assert out["rotation_signal"] is None
    assert out["risk_score"] is None


def test_iwm_partial_spy_iwm_divergence_only_when_both_present():
    partial = compute_iwm_confluence(0.5, None, None)
    assert partial["spy_iwm_divergence"] is None
    both = compute_iwm_confluence(0.5, None, -0.2)
    assert both["spy_iwm_divergence"] is not None


def test_flow_imbalance_none_when_no_chain_data():
    assert flow_imbalance_normalized_with_fallback({}, 500.0) == (None, "none")


def test_smart_money_no_data_returns_none_fields():
    out = compute_smart_money_signal({}, 500.0)
    assert out["score"] is None
    assert out["direction"] is None
    assert out["label"] is None
