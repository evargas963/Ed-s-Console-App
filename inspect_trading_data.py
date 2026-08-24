#!/usr/bin/env python3
"""
Inspect all data feeding the trading engine.
Lists MarketState fields, SnapshotRow fields, and groups by source.
Run: python inspect_trading_data.py
"""
from __future__ import annotations


# ── MarketState fields (from market_state.py) ─────────────────────────────────
MS_FIELDS = [
    "ticker", "selected_exp", "session_label",
    "spot", "bid", "ask", "spot_disp", "bid_disp", "ask_disp",
    "bias_signal", "pin_strength", "net_delta", "net_gamma",
    "gex_magnitude", "dex_magnitude", "zone",
    "bias_color_css", "pin_color_css", "nd_color_css", "nd_disp",
    "vix", "vix_regime", "vix_color", "vix_implication",
    "pcr_val", "pcr_arrow", "pcr_color", "pcr_label",
    "iv_direction", "bias_resolved", "nd_resolved",
    "rec_strike", "rec_side", "is_no_trade", "dte_warn", "dte_color",
    "liq_ok", "ratio", "vol_oi", "spread",
    "entry_zone_lo", "entry_zone_hi", "entry_zone_str",
    "rules_signal", "rules_conviction", "zone_label", "zone_badge_css",
    "rules_headline", "rules_headline_1m", "rules_detail", "rules_alerts",
    "session_high", "session_low", "last_sweep_type", "last_sweep_level",
    "last_sweep_held", "n_sweeps_today",
    "validation_passed", "structure_valid", "probability_valid", "risk_valid",
    "validation_summary", "r_units", "execution_mode", "sizing_summary",
    "call_signal", "call_conviction", "entry", "stop", "target", "target2",
    "reward_risk", "reward_risk2",
    "entry_disp", "stop_disp", "target_disp", "target2_disp", "rr_disp", "rr2_disp",
    "call_headline", "call_reasoning", "trade_type", "trade_type_label",
    "invalidation", "confluence_count", "confluence_total", "confluence_detail",
    "time_qualifier", "size_cue", "rules_pred_agree", "time_warning", "size_note",
    "call_readiness_score", "call_state", "call_forecast_state",
    "call_readiness_reasons", "call_missing_conditions", "call_readiness_component_scores",
    "put_readiness_score", "put_state", "put_forecast_state",
    "put_readiness_reasons", "put_missing_conditions", "put_readiness_component_scores",
    "pred_headline", "up_prob_3c", "down_prob_3c", "flat_prob_3c",
    "up_prob_5c", "down_prob_5c", "flat_prob_5c",
    "up_prob_8c", "down_prob_8c", "flat_prob_8c",
    "up_prob_13c", "down_prob_13c", "flat_prob_13c",
    "up_prob_15c", "down_prob_15c", "flat_prob_15c",
    "dominant_dir", "dominant_prob", "confidence", "samples_used", "model_note",
    "model_version", "timeframe_reads", "avg_3c_pts", "avg_5c_pts", "avg_8c_pts", "avg_13c_pts", "avg_15c_pts",
    "reversal_risk", "reversal_label", "reversal_shortfall", "reversal_severity",
    "regime_primary", "regime_secondary", "regime_confidence", "regime_score",
    "regime_summary", "regime_support", "regime_contradiction",
    "fusion_available", "fusion_dominant", "fusion_dominant_prob",
    "fusion_confidence", "fusion_confidence_score", "fusion_summary",
    "fusion_breakout", "fusion_pinning", "fusion_continuation", "fusion_reversal",
    "fusion_vol_expansion", "fusion_mean_reversion",
    "fusion_model_agreement", "fusion_agreement_label", "fusion_n_models_active",
    "fusion_evidence", "fusion_contradictions",
    "mc_available", "mc_containment", "mc_expansion", "mc_efe", "mc_eae",
    "mc_upper_50", "mc_lower_50", "mc_paths", "mc_horizon",
    "mc_vol_source", "mc_sigma_value",
    "nearest_above_name", "nearest_above_val", "nearest_above_dist",
    "nearest_below_name", "nearest_below_val", "nearest_below_dist",
    "vwap_side",
    "charm_net", "charm_direction", "charm_direction_display",
    "charm_drift_toward", "charm_magnitude", "charm_top_drivers",
    "live_on",
]


# ── Category mapping (field -> source category) ──────────────────────────────
def build_category_map():
    m = {}
    for f in [
        "ticker", "selected_exp", "session_label", "spot", "bid", "ask",
        "spot_disp", "bid_disp", "ask_disp", "live_on",
    ]:
        m[f] = "identity"
    for f in [
        "bias_signal", "pin_strength", "net_delta", "net_gamma",
        "gex_magnitude", "dex_magnitude", "zone",
        "bias_color_css", "pin_color_css", "nd_color_css", "nd_disp",
        "bias_resolved", "nd_resolved",
    ]:
        m[f] = "price/structure"
    for f in [
        "vix", "vix_regime", "vix_color", "vix_implication",
        "pcr_val", "pcr_arrow", "pcr_color", "pcr_label", "iv_direction",
    ]:
        m[f] = "volatility"
    for f in [
        "rec_strike", "rec_side", "is_no_trade", "dte_warn", "dte_color",
        "liq_ok", "ratio", "vol_oi", "spread",
        "entry_zone_lo", "entry_zone_hi", "entry_zone_str",
    ]:
        m[f] = "OE / levels"
    for f in [
        "nearest_above_name", "nearest_above_val", "nearest_above_dist",
        "nearest_below_name", "nearest_below_val", "nearest_below_dist",
        "vwap_side",
    ]:
        m[f] = "levels (gamma/delta/em/etc)"
    for f in [
        "rules_signal", "rules_conviction", "zone_label", "zone_badge_css",
        "rules_headline", "rules_headline_1m", "rules_detail", "rules_alerts",
        "session_high", "session_low", "last_sweep_type", "last_sweep_level",
        "last_sweep_held", "n_sweeps_today",
    ]:
        m[f] = "micro structure (Right Now)"
    for f in [
        "validation_passed", "structure_valid", "probability_valid", "risk_valid",
        "validation_summary", "r_units", "execution_mode", "sizing_summary",
    ]:
        m[f] = "validation gate"
    for f in [
        "call_signal", "call_conviction", "entry", "stop", "target", "target2",
        "reward_risk", "reward_risk2", "entry_disp", "stop_disp", "target_disp",
        "target2_disp", "rr_disp", "rr2_disp", "call_headline", "call_reasoning",
        "trade_type", "trade_type_label", "invalidation", "confluence_count",
        "confluence_total", "confluence_detail", "time_qualifier", "size_cue",
        "rules_pred_agree", "time_warning", "size_note",
        "call_readiness_score", "call_state", "call_forecast_state",
        "call_readiness_reasons", "call_missing_conditions", "call_readiness_component_scores",
        "put_readiness_score", "put_state", "put_forecast_state",
        "put_readiness_reasons", "put_missing_conditions", "put_readiness_component_scores",
    ]:
        m[f] = "The Call (signals/call_engine)"
    for f in [
        "pred_headline", "up_prob_3c", "down_prob_3c", "flat_prob_3c",
        "up_prob_5c", "down_prob_5c", "flat_prob_5c",
        "up_prob_8c", "down_prob_8c", "flat_prob_8c",
        "up_prob_13c", "down_prob_13c", "flat_prob_13c",
        "up_prob_15c", "down_prob_15c", "flat_prob_15c",
        "dominant_dir", "dominant_prob", "confidence", "samples_used", "model_note",
        "model_version", "timeframe_reads", "avg_3c_pts", "avg_5c_pts", "avg_8c_pts", "avg_13c_pts", "avg_15c_pts",
        "reversal_risk", "reversal_label", "reversal_shortfall", "reversal_severity",
    ]:
        m[f] = "model predictions (prediction_engine)"
    for f in [
        "regime_primary", "regime_secondary", "regime_confidence", "regime_score",
        "regime_summary", "regime_support", "regime_contradiction",
    ]:
        m[f] = "regime engine"
    for f in [
        "fusion_available", "fusion_dominant", "fusion_dominant_prob",
        "fusion_confidence", "fusion_confidence_score", "fusion_summary",
        "fusion_breakout", "fusion_pinning", "fusion_continuation", "fusion_reversal",
        "fusion_vol_expansion", "fusion_mean_reversion",
        "fusion_model_agreement", "fusion_agreement_label", "fusion_n_models_active",
        "fusion_evidence", "fusion_contradictions",
        "mc_available", "mc_containment", "mc_expansion", "mc_efe", "mc_eae",
        "mc_upper_50", "mc_lower_50", "mc_paths", "mc_horizon",
        "mc_vol_source", "mc_sigma_value",
    ]:
        m[f] = "Bayesian fusion / Monte Carlo"
    for f in [
        "charm_net", "charm_direction", "charm_direction_display",
        "charm_drift_toward", "charm_magnitude", "charm_top_drivers",
    ]:
        m[f] = "charm (greeks)"
    return m


def main():
    cat = build_category_map()
    by_cat = {}
    for f in MS_FIELDS:
        c = cat.get(f, "other")
        by_cat.setdefault(c, []).append(f)

    print("=" * 70)
    print("TRADING ENGINE DATA INVENTORY")
    print("=" * 70)

    print("\n## 1. MarketState fields (", len(MS_FIELDS), ")")
    print("-" * 50)
    for f in MS_FIELDS:
        print(f"  {f}")

    print("\n## 2. SnapshotRow fields (from _snapshot_kwargs)")
    print("-" * 50)
    print("  Populated from: ms (MarketState) + server-computed values")
    print("  Note: xgb_*, lstm_* in SnapshotRow exist but are NOT populated by server")
    print("  See db.py SnapshotRow for full schema")

    print("\n## 3. Fields by source category")
    print("-" * 50)
    for c in sorted(by_cat.keys()):
        print(f"\n  [{c}]")
        for f in sorted(by_cat[c]):
            print(f"    {f}")

    print("\n## 4. Typically null/missing fields")
    print("-" * 50)
    null_often = [
        "bid", "ask", "rec_strike", "rec_side",
        "entry", "stop", "target", "target2", "reward_risk", "reward_risk2",
        "session_high", "session_low", "last_sweep_type", "last_sweep_level", "last_sweep_held",
        "reversal_risk", "reversal_shortfall",
        "mc_efe", "mc_eae", "mc_containment", "mc_expansion",
        "mc_upper_50", "mc_lower_50", "mc_paths", "mc_horizon",
        "charm_drift_toward",
    ]
    print("  (Populated only when conditions met:)")
    for f in null_often:
        if f in MS_FIELDS:
            print(f"    {f}")

    print("\n## 5. SnapshotRow fields NOT in _snapshot_kwargs (always NULL)")
    print("-" * 50)
    snap_not_populated = [
        "pred_1c_up_prob", "pred_1c_down_prob", "pred_1c_flat_prob",
        "xgb_available", "xgb_dominant", "xgb_confidence",
        "lstm_available", "lstm_dominant", "lstm_confidence",
    ]
    for f in snap_not_populated:
        print(f"    {f}")

    print("\n" + "=" * 70)


if __name__ == "__main__":
    main()
