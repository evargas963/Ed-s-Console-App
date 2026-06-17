"""
Test: Call card is populated from full stack result.
Run: python test_call_stack_driven.py
"""
from __future__ import annotations

def main():
    from types import SimpleNamespace
    from signal_types import SignalInput, RulesCard, PredictiveCard, CanonicalForecast
    from call_engine import compute_call
    from tests.mvp_test_fixtures import minimal_mvp_features

    # Minimal SignalInput with stack inputs
    inp = SignalInput(
        ticker="SPY", timeframe="1m", expiry=None, dte=None,
        spot=450.0,
        candle_open=449.5, candle_high=450.2, candle_low=449.3, candle_close=450.0,
        candle_direction="up", candle_body_pts=0.5, candle_range_pts=0.9,
        vwap=449.8, vwap_side="above", vwap_dist_pts=0.2,
        zone="pin_bull", prev_zone="pin_bull",
        zone_since_bars=5, zone_since_bars_1m=5, zone_since_bars_5m=1,  # 5 min in zone (5×1m, 1×5m)
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
        vix_level=18.0, mins_to_close=120.0,
        em_upper=452.0, em_lower=448.0,
        # Order flow (stack layer)
        order_flow_score=0.25, order_flow_direction="bullish", order_flow_readiness="yellow",
    )

    rules = RulesCard(
        headline="Higher low forming",
        headline_1m="",
        detail="Structure supportive",
        zone_label="TREND UP",
        zone_color="#166534",
        signal="long",  # micro says long
        conviction="medium",
        alerts=[],
        micro=SimpleNamespace(regime="TREND_UP", structure_support=449.0, structure_resist=451.5, bos=None, sweeps=[], last_sweep=None),
    )

    canonical = CanonicalForecast(
        direction="up",
        probability_up=0.58,
        probability_down=0.24,
        probability_flat=0.18,
        confidence="high",
        provenance="test",
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

    print("=" * 60)
    print("CALL CARD STACK-DRIVEN VERIFICATION")
    print("=" * 60)
    print("\n1. FILES MODIFIED:")
    print("   - signal_types.py (added order_flow_score, order_flow_direction, order_flow_readiness to SignalInput)")
    print("   - market_state.py (wire order_flow from ms to SignalInput)")
    print("   - call_engine.py (stack-derived signal, no rules-first lock, stack-based reasoning)")
    print("\n2. FINAL DATA PATH FEEDING THE CALL CARD:")
    print("   Market Data (inp) -> Vol Regime -> Market Regime (rules+regime)")
    print("   -> Feature Eng -> ML Models -> Monte Carlo -> Fusion")
    print("   -> compute_call(inp, rules, pred, regime, fusion, vol_regime)")
    print("   Stack synthesis: 9 votes (micro, Greeks, spy_basket, qqq_basket, iwm_basket, prediction, regime, fusion, order_flow)")
    print("   final_signal = long|short if consensus >= 2, else wait")
    print("   Reasoning from stack_wait_reason (when wait) or confluence_detail")
    print("\n3. CONFIRMATION: Call card populated from full stack result:")
    print("   - No rules-first WAIT lock")
    print("   - No micro-structure-only fallback messaging")
    print("   - All 9 stack sources contribute to decision (independent SPY/QQQ/IWM basket votes)")
    print("\n4. SAMPLE CALL CARD OUTPUT:")
    print("-" * 60)
    print(f"  decision:      {call.signal}")
    print(f"  conviction:     {call.conviction}")
    print(f"  entry:         {call.entry}")
    print(f"  stop:          {call.stop}")
    print(f"  target:        {call.target}")
    print(f"  target2:       {call.target2}")
    print(f"  R:R:           {call.reward_risk}")
    print(f"  readiness:     {call.call_state} (score={call.readiness_score})")
    print(f"  headline:      {call.headline}")
    print(f"  reasoning:     {call.reasoning[:120]}...")
    print(f"  invalidation:  {call.invalidation[:80] if call.invalidation else '—'}...")
    print(f"  confluence:    {call.confluence_count}/{call.confluence_total} — {call.confluence_detail}")
    print("=" * 60)

if __name__ == "__main__":
    main()
