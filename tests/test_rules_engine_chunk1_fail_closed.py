"""rules_engine chunk-1: fail-closed contracts for empty micro and hard time override."""

from __future__ import annotations

from rules_engine import compute_rules
from signal_types import SignalInput
from tests.mvp_test_fixtures import minimal_mvp_features


def _minimal_inp(**overrides) -> SignalInput:
    base = dict(
        ticker="SPY",
        timeframe="1m",
        expiry=None,
        dte=None,
        spot=450.0,
        candle_open=449.5,
        candle_high=450.2,
        candle_low=449.3,
        candle_close=450.0,
        candle_direction="up",
        candle_body_pts=0.5,
        candle_range_pts=0.9,
        vwap=449.8,
        vwap_side="above",
        vwap_dist_pts=0.2,
        zone="pin_bull",
        prev_zone="pin_bull",
        zone_since_bars=5,
        zone_since_bars_1m=5,
        zone_since_bars_5m=1,
        call_gamma_wall=451.0,
        put_gamma_wall=449.0,
        call_delta_wall=None,
        put_delta_wall=None,
        gamma_inflection=None,
        delta_inflection=None,
        call_oi_wall=None,
        put_oi_wall=None,
        call_vanna_wall=None,
        put_vanna_wall=None,
        pin_width_pts=2.0,
        dist_call_gamma_wall=1.0,
        dist_put_gamma_wall=-1.0,
        dist_call_delta_wall=None,
        dist_put_delta_wall=None,
        dist_gamma_inflection=None,
        dist_delta_inflection=None,
        dist_call_oi_wall=None,
        dist_put_oi_wall=None,
        dist_call_vanna_wall=None,
        dist_put_vanna_wall=None,
        nearest_above_name="CGW",
        nearest_above_val=451.0,
        nearest_above_dist=1.0,
        nearest_below_name="PGW",
        nearest_below_val=449.0,
        nearest_below_dist=1.0,
        net_gamma=1000.0,
        net_delta=500.0,
        net_vanna=None,
        charm_net=None,
        charm_direction="neutral",
        charm_drift_toward=450.0,
        charm_magnitude="moderate",
        dex_magnitude="moderate",
        iv_level=0.15,
        iv_direction="flat",
        realized_vol=None,
        atr=1.5,
        put_call_oi_ratio=0.9,
        oi_center=None,
        recent_crosses=[],
        ceiling_tests_today=0,
        floor_tests_today=0,
        spy_chg_pct=0.0,
        qqq_chg_pct=0.0,
        iwm_chg_pct=0.0,
        vix_level=18.0,
        mins_to_close=240.0,
        em_upper=452.0,
        em_lower=448.0,
        order_flow_score=0.0,
        order_flow_direction="neutral",
        order_flow_readiness="yellow",
        candles_5m=[],
        candles_1m=[],
    )
    base.update(overrides)
    return SignalInput(**base)


def test_compute_rules_empty_candles_fail_closed_wait():
    rules = compute_rules(_minimal_inp(), mvp_features=minimal_mvp_features())
    assert rules.signal == "wait"
    assert rules.conviction == "low"


def test_compute_rules_hard_time_override_forces_wait_low():
    rules = compute_rules(
        _minimal_inp(mins_to_close=15.0),
        mvp_features=minimal_mvp_features(),
    )
    assert rules.signal == "wait"
    assert rules.conviction == "low"
    assert any("no new entries" in a for a in rules.alerts)
