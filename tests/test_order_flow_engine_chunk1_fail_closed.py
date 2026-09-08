"""order_flow_engine chunk-1: lock 92b85ff/0edebc3 I-01 contracts on HEAD (slice-only walk)."""

from __future__ import annotations

from app.options.order_flow.engine import OrderFlowEngine, _compute_rvol, _compute_spread


def test_rvol_fail_closed_when_avg_volume_missing():
    rvol, reason = _compute_rvol({"quote": {"totalVolume": 500}, "fundamental": {}})
    assert rvol is None
    assert reason == "avg_volume_unavailable"


def test_rvol_fail_closed_when_current_volume_missing():
    rvol, reason = _compute_rvol({"fundamental": {"avg10DaysVolume": 1_000_000}})
    assert rvol is None
    assert reason == "current_volume_unavailable"


def test_spread_fail_closed_when_bid_ask_missing():
    spread_d = _compute_spread({"quote": {}})
    assert spread_d["spread_pts"] is None
    assert spread_d["spread_frac"] is None


def test_engine_empty_result_verdict_unavailable_not_flow_neutral():
    out = OrderFlowEngine()._empty_result()
    assert out["order_flow_verdict"] is None
    assert out["order_flow_direction"] is None
    assert out["order_flow_agreement"] == "unavailable"
    assert out["rvol"] is None
    assert out["rvol_unavailable_reason"] is None
