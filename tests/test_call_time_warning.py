"""
test_call_time_warning.py — Time-warning consistency

Verifies that when ≤30 min to close forces WAIT, headline, reasoning, badge,
and wait_blocker all reflect the same final state (no LONG/SHORT headline
with WAIT badge mismatch).
"""
from __future__ import annotations

import sys
import os
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parent.parent
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))

from tests.mvp_test_fixtures import minimal_mvp_features


def _minimal_input(mins_to_close: float):
    """Minimal SignalInput that yields stack consensus long (before time override)."""
    from signal_types import SignalInput

    return SignalInput(
        ticker="SPY", timeframe="1m", expiry=None, dte=None,
        spot=450.0,
        candle_open=449.5, candle_high=450.2, candle_low=449.3, candle_close=450.0,
        candle_direction="up", candle_body_pts=0.5, candle_range_pts=0.9,
        vwap=449.8, vwap_side="above", vwap_dist_pts=0.2,
        zone="pin_bull", prev_zone="pin_bull",
        zone_since_bars=5, zone_since_bars_1m=5, zone_since_bars_5m=1,
        call_gamma_wall=451.0, put_gamma_wall=449.0, call_delta_wall=None, put_delta_wall=None,
        gamma_inflection=None, delta_inflection=None,
        call_oi_wall=None, put_oi_wall=None, call_vanna_wall=None, put_vanna_wall=None,
        pin_width_pts=2.0,
        dist_call_gamma_wall=1.0, dist_put_gamma_wall=-1.0,
        dist_call_delta_wall=None, dist_put_delta_wall=None,
        dist_gamma_inflection=None, dist_delta_inflection=None,
        dist_call_oi_wall=None, dist_put_oi_wall=None,
        dist_call_vanna_wall=None, dist_put_vanna_wall=None,
        nearest_above_name="CGW", nearest_above_val=451.0, nearest_above_dist=1.0,
        nearest_below_name="PGW", nearest_below_val=449.0, nearest_below_dist=1.0,
        net_gamma=1000.0, net_delta=500.0, net_vanna=None,
        charm_net=None, charm_direction="buying", charm_drift_toward=450.0,
        charm_magnitude="moderate", dex_magnitude="moderate",
        iv_level=0.15, iv_direction="flat", realized_vol=None, atr=1.5,
        put_call_oi_ratio=0.9, oi_center=None,
        recent_crosses=[], ceiling_tests_today=0, floor_tests_today=0,
        spy_chg_pct=0.3, qqq_chg_pct=0.4, iwm_chg_pct=0.2,
        vix_level=18.0, mins_to_close=mins_to_close,
        em_upper=452.0, em_lower=448.0,
        order_flow_score=0.25, order_flow_direction="bullish", order_flow_readiness="yellow",
    )


def _minimal_rules_pred_regime_fusion():
    from signal_types import RulesCard, PredictiveCard, CanonicalForecast

    canonical = CanonicalForecast(
        direction="up",
        probability_up=0.58,
        probability_down=0.24,
        probability_flat=0.18,
        confidence="high",
        provenance="test",
    )

    rules = RulesCard(
        headline="Higher low forming",
        headline_1m="",
        detail="Structure supportive",
        zone_label="TREND UP",
        zone_color="#166534",
        signal="long",
        conviction="medium",
        alerts=[],
        micro=SimpleNamespace(
            regime="TREND_UP", structure_support=449.0, structure_resist=451.5,
            bos=None, sweeps=[], last_sweep=None,
        ),
    )
    pred = PredictiveCard(
        headline="Prediction: UP toward 451.50",
        prediction_dir="up",
        prediction_target=451.5,
        historical_5c_dominant_dir="up",
        historical_5c_dominant_prob=0.58,
        empirical_confidence="high",
        forward_direction=canonical.direction,
        forward_prob_up=canonical.probability_up,
        forward_prob_down=canonical.probability_down,
        forward_prob_flat=canonical.probability_flat,
        forward_confidence=canonical.confidence,
        forward_provenance=canonical.provenance,
        samples_used=50,
        model_note="Stack test",
        timeframe_reads={},
        up_prob_5c=0.56, down_prob_5c=0.26, flat_prob_5c=0.18,
    )
    regime = SimpleNamespace(primary="trend_continuation", confidence="medium")
    fusion = SimpleNamespace(
        available=True,
        dominant_direction="up",
        fusion_dominant_direction="up",
        model_agreement=0.75,
        model_agreement_label="high",
        n_sources_active=3,
        fusion_confidence="medium",
        mc_available=True,
        mc_containment=0.4,
        mc_expansion=0.5,
        mc_eae=1.2,
        mc_efe=0.9,
    )
    vol_regime = SimpleNamespace(
        vol_regime="normal",
        trade_permissive=True,
        conviction_multiplier=1.0,
        risk_multiplier=1.0,
    )
    return rules, pred, regime, fusion, vol_regime, canonical


def test_time_warning_forces_wait_consistent_display():
    """≤30 min to close: signal, headline, reasoning, wait_blocker all WAIT."""
    from call_engine import compute_call

    inp = _minimal_input(mins_to_close=25.0)
    rules, pred, regime, fusion, vol_regime, canonical = _minimal_rules_pred_regime_fusion()
    call = compute_call(
        inp,
        rules,
        pred,
        regime=regime,
        fusion=fusion,
        vol_regime=vol_regime,
        canonical=canonical,
        mvp_features=minimal_mvp_features(zone="pin_bull"),
    )

    assert call.signal == "wait", f"expected signal=wait, got {call.signal}"
    assert "WAIT" in call.headline, f"headline must show WAIT; got: {call.headline}"
    assert not call.headline.startswith(("LONG", "SHORT")), (
        f"headline must not suggest LONG/SHORT when time override; got: {call.headline}"
    )
    assert "25" in call.headline or "min" in call.headline.lower() or "close" in call.headline.lower(), (
        f"headline should mention time context; got: {call.headline}"
    )
    assert call.wait_blocker is not None, "wait_blocker must be set when time forces wait"
    assert call.wait_blocker.get("reason") == "time", (
        f"wait_blocker.reason must be 'time'; got: {call.wait_blocker}"
    )
    assert call.size_cue == "SKIP", f"expected size_cue=SKIP when ≤30min; got {call.size_cue}"
    assert call.conviction == "low", f"expected conviction=low when time block; got {call.conviction}"
    # Reasoning should align with time blocker, not long/short confluence
    assert "close" in call.reasoning.lower() or "25" in call.reasoning, (
        f"reasoning should reflect time; got: {call.reasoning[:150]}..."
    )


def test_time_warning_120min_does_not_override_signal():
    """60–120 min: time warning present but signal unchanged (no override)."""
    from call_engine import compute_call

    inp = _minimal_input(mins_to_close=90.0)
    rules, pred, regime, fusion, vol_regime, canonical = _minimal_rules_pred_regime_fusion()
    call = compute_call(
        inp,
        rules,
        pred,
        regime=regime,
        fusion=fusion,
        vol_regime=vol_regime,
        canonical=canonical,
        mvp_features=minimal_mvp_features(zone="pin_bull"),
    )

    assert call.signal != "wait" or call.wait_blocker is None or call.wait_blocker.get("reason") != "time", (
        "90 min to close: signal should not be overridden by time; "
        f"signal={call.signal} wait_blocker={call.wait_blocker}"
    )
    # If stack produced long, we should see LONG in headline (not forced to WAIT)
    if call.signal == "long":
        assert "LONG" in call.headline, f"expected LONG headline when signal=long; got: {call.headline}"


def test_time_warning_zero_or_negative_ignored():
    """mins_to_close=0 or negative: no time block applied."""
    from call_engine import compute_call

    inp = _minimal_input(mins_to_close=0.0)
    rules, pred, regime, fusion, vol_regime, canonical = _minimal_rules_pred_regime_fusion()
    call = compute_call(
        inp,
        rules,
        pred,
        regime=regime,
        fusion=fusion,
        vol_regime=vol_regime,
        canonical=canonical,
        mvp_features=minimal_mvp_features(zone="pin_bull"),
    )

    # With mins_to_close=0, time block should not trigger (condition: <=30 and >0)
    if call.wait_blocker and call.wait_blocker.get("reason") == "time":
        raise AssertionError("mins_to_close=0 should not set time wait_blocker; got wait_blocker=time")


if __name__ == "__main__":
    print("Running time-warning consistency tests...")
    test_time_warning_forces_wait_consistent_display()
    print("  [OK] test_time_warning_forces_wait_consistent_display")
    test_time_warning_120min_does_not_override_signal()
    print("  [OK] test_time_warning_120min_does_not_override_signal")
    test_time_warning_zero_or_negative_ignored()
    print("  [OK] test_time_warning_zero_or_negative_ignored")
    print("All tests passed.")
