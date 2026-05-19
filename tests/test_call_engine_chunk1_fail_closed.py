"""call_engine chunk-1: I-01 contract when canonical/fusion/mh_policy are absent."""

from __future__ import annotations

from types import SimpleNamespace

from call_engine import compute_call
from signal_types import PredictiveCard, RulesCard, SignalInput
from tests.mvp_test_fixtures import minimal_mvp_features


def _strong_long_stack_input() -> SignalInput:
    return SignalInput(
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
        zone="breakout",
        prev_zone="pin_bull",
        zone_since_bars=5,
        zone_since_bars_1m=5,
        zone_since_bars_5m=1,
        call_gamma_wall=460.0,
        put_gamma_wall=440.0,
        call_delta_wall=None,
        put_delta_wall=None,
        gamma_inflection=None,
        delta_inflection=None,
        call_oi_wall=None,
        put_oi_wall=None,
        call_vanna_wall=None,
        put_vanna_wall=None,
        pin_width_pts=2.0,
        dist_call_gamma_wall=10.0,
        dist_put_gamma_wall=-10.0,
        dist_call_delta_wall=None,
        dist_put_delta_wall=None,
        dist_gamma_inflection=None,
        dist_delta_inflection=None,
        dist_call_oi_wall=None,
        dist_put_oi_wall=None,
        dist_call_vanna_wall=None,
        dist_put_vanna_wall=None,
        nearest_above_name="CGW",
        nearest_above_val=460.0,
        nearest_above_dist=10.0,
        nearest_below_name="PGW",
        nearest_below_val=440.0,
        nearest_below_dist=10.0,
        net_gamma=1000.0,
        net_delta=800.0,
        net_vanna=None,
        charm_net=None,
        charm_direction="buying",
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
        spy_chg_pct=0.8,
        qqq_chg_pct=0.9,
        iwm_chg_pct=0.7,
        spy_weighted_push=0.5,
        qqq_weighted_push=0.5,
        iwm_weighted_push=0.5,
        vix_level=18.0,
        mins_to_close=240.0,
        em_upper=452.0,
        em_lower=448.0,
        order_flow_score=0.5,
        order_flow_direction="bullish",
        order_flow_readiness="green",
    )


def test_compute_call_missing_upstreams_forces_wait_not_sized_trade():
    """Stack may lean long, but missing canonical provenance must not emit a sized trade."""
    rules = RulesCard(
        headline="Stack lean",
        headline_1m="",
        detail="",
        zone_label="UP",
        zone_color="#166534",
        signal="long",
        conviction="high",
        alerts=[],
        micro=SimpleNamespace(
            regime="TREND_UP",
            structure_support=449.0,
            structure_resist=451.5,
            bos=None,
            sweeps=[],
            last_sweep=None,
        ),
    )
    pred = PredictiveCard(
        headline="Lean up",
        prediction_dir="up",
        prediction_target=455.0,
        historical_5c_dominant_dir="up",
        historical_5c_dominant_prob=0.7,
        empirical_confidence="high",
        forward_direction="flat",
        forward_prob_up=1.0 / 3.0,
        forward_prob_down=1.0 / 3.0,
        forward_prob_flat=1.0 / 3.0,
        forward_confidence="low",
        forward_provenance="missing",
        samples_used=0,
        model_note="",
        timeframe_reads={},
        up_prob_5c=0.7,
        down_prob_5c=0.15,
        flat_prob_5c=0.15,
    )

    call = compute_call(
        _strong_long_stack_input(),
        rules,
        pred,
        regime=None,
        fusion=None,
        vol_regime=None,
        canonical=None,
        mvp_features=minimal_mvp_features(zone="breakout"),
        mh_policy=None,
    )

    assert call.signal == "wait"
    assert call.r_units == 0.0
    assert call.execution_mode == "NO_TRADE"
    assert call.wait_blocker is not None
    assert call.wait_blocker.get("provenance") == "missing_canonical_fallback"
    assert call.signal not in ("long", "short") or not call.validation_passed
