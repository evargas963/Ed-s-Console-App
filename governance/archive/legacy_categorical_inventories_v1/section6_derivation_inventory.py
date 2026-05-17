"""
Section 6 Schwab-leaf derivation audit inventory (signals + decision).

One row per ``def`` (module, class method, nested helper).
Disposition: REPLACED | KEEP_DERIVED | PASS_THROUGH | NONE
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DerivationRecord:
    file: str
    line: str
    derivation: str
    schwab_leaf: str
    disposition: str
    justification: str


SECTION6_DERIVATION_INVENTORY: tuple[DerivationRecord, ...] = (

    DerivationRecord("signals.py", "79", "canonical_forecast_from_fusion", "—", "NONE", "No Schwab market-field derivation in function body."),
    DerivationRecord("signals.py", "113", "_debug_canonical_override", "—", "NONE", "No Schwab market-field derivation in function body."),
    DerivationRecord("signals.py", "130", "_pred_override_allowed", "—", "NONE", "No Schwab market-field derivation in function body."),
    DerivationRecord("signals.py", "134", "_live_model_stack_horizons", "—", "NONE", "No Schwab market-field derivation in function body."),
    DerivationRecord("signals.py", "166", "_log_decision_bundle", "upstream ms_dict / SignalInput", "KEEP_DERIVED", "Consumes upstream Schwab-first market state; no new wire ingest."),
    DerivationRecord("signals.py", "212", "_build_calibration_payload", "upstream ms_dict / SignalInput", "KEEP_DERIVED", "Consumes upstream Schwab-first market state; no new wire ingest."),
    DerivationRecord("signals.py", "255", "_spot_for_mc_fusion_adjustment", "spot, fusion overlay", "KEEP_DERIVED", "Spot selection for MC fusion; upstream quote-derived spot."),
    DerivationRecord("signals.py", "277", "_run_model_stack", "ML + fusion inputs", "KEEP_DERIVED", "Runs model stack on snapshot features."),
    DerivationRecord("signals.py", "528", "compute_fusion_policy_flat_for_replay", "replay snapshot dict", "PASS_THROUGH", "Replay path reads persisted snapshot features only."),
    DerivationRecord("signals.py", "688", "_build_stack_decision_path", "—", "NONE", "No Schwab market-field derivation in function body."),
    DerivationRecord("signals.py", "693", "_build_stack_decision_path._model_stage", "—", "NONE", "Nested stage label helper inside decision path builder."),
    DerivationRecord("signals.py", "788", "_build_snapshot_dict", "ms_dict fields", "PASS_THROUGH", "Serializes market state for ML snapshot."),
    DerivationRecord("signals.py", "851", "compute_signals", "SignalInput / ms_dict upstream", "KEEP_DERIVED", "Main signals entry; consumes Schwab-first market state, no new ingest."),
    DerivationRecord("signals.py", "877", "_compute_signals_impl", "SignalInput fields", "KEEP_DERIVED", "Signal pipeline implementation on cached state."),
    DerivationRecord("signal_helpers.py", "6", "_ordinal", "—", "NONE", "String formatting helper."),
    DerivationRecord("signal_types.py", "186", "CanonicalForecast.dominant_probability", "fusion probabilities", "KEEP_DERIVED", "Property on forecast dataclass; no Schwab wire read."),
    DerivationRecord("rules_engine.py", "20", "_derive_bias_from_micro", "micro_structure reads", "KEEP_DERIVED", "Bias from micro structure metrics."),
    DerivationRecord("rules_engine.py", "90", "compute_rules", "micro_structure + SignalInput", "KEEP_DERIVED", "Rules layer on upstream market fields."),
    DerivationRecord("prediction_engine.py", "65", "_predict_enrichment_enabled", "—", "NONE", "No Schwab market-field derivation in function body."),
    DerivationRecord("prediction_engine.py", "69", "_as_of_ts_utc_for_similarity", "upstream ms_dict / SignalInput", "KEEP_DERIVED", "Consumes upstream Schwab-first market state; no new wire ingest."),
    DerivationRecord("prediction_engine.py", "91", "_count_labeled", "—", "NONE", "No Schwab market-field derivation in function body."),
    DerivationRecord("prediction_engine.py", "98", "_literal_empirical_horizon", "—", "NONE", "No Schwab market-field derivation in function body."),
    DerivationRecord("prediction_engine.py", "128", "_tri_probs", "model probabilities", "KEEP_DERIVED", "Probability math on model outputs."),
    DerivationRecord("prediction_engine.py", "138", "_norm_triplet_floats", "—", "NONE", "No Schwab market-field derivation in function body."),
    DerivationRecord("prediction_engine.py", "146", "_overlay_multi_horizon_ml_on_product_triplets", "upstream ms_dict / SignalInput", "KEEP_DERIVED", "Consumes upstream Schwab-first market state; no new wire ingest."),
    DerivationRecord("prediction_engine.py", "231", "_avg_outcome_pts", "—", "NONE", "No Schwab market-field derivation in function body."),
    DerivationRecord("prediction_engine.py", "238", "_pack_horizon_row", "—", "NONE", "No Schwab market-field derivation in function body."),
    DerivationRecord("prediction_engine.py", "269", "_build_horizon_prob_bars", "model probabilities", "KEEP_DERIVED", "Probability math on model outputs."),
    DerivationRecord("prediction_engine.py", "300", "_timeframe_reads", "upstream ms_dict / SignalInput", "KEEP_DERIVED", "Consumes upstream Schwab-first market state; no new wire ingest."),
    DerivationRecord("prediction_engine.py", "337", "_prediction_headline", "upstream ms_dict / SignalInput", "KEEP_DERIVED", "Consumes upstream Schwab-first market state; no new wire ingest."),
    DerivationRecord("prediction_engine.py", "394", "_get_all_recent", "upstream ms_dict / SignalInput", "KEEP_DERIVED", "Consumes upstream Schwab-first market state; no new wire ingest."),
    DerivationRecord("prediction_engine.py", "410", "build_fusion_model_overlay_for_stack", "fusion model output", "KEEP_DERIVED", "ML overlay on product triplets."),
    DerivationRecord("prediction_engine.py", "567", "_empty_prediction", "upstream ms_dict / SignalInput", "KEEP_DERIVED", "Consumes upstream Schwab-first market state; no new wire ingest."),
    DerivationRecord("prediction_engine.py", "629", "compute_prediction_core", "empirical probs", "KEEP_DERIVED", "Core prediction from labeled history."),
    DerivationRecord("prediction_engine.py", "874", "compute_prediction_enrichment", "upstream ms_dict / SignalInput", "KEEP_DERIVED", "Consumes upstream Schwab-first market state; no new wire ingest."),
    DerivationRecord("prediction_engine.py", "1190", "compute_prediction", "SignalInput / similarity DB", "KEEP_DERIVED", "Public prediction entry; no direct Schwab API."),
    DerivationRecord("call_engine.py", "30", "_mh_size_tier_from_modifier", "—", "NONE", "No Schwab market-field derivation in function body."),
    DerivationRecord("call_engine.py", "40", "_size_cue_tier", "—", "NONE", "No Schwab market-field derivation in function body."),
    DerivationRecord("call_engine.py", "51", "_tier_to_size_cue", "—", "NONE", "No Schwab market-field derivation in function body."),
    DerivationRecord("call_engine.py", "61", "_merge_size_cue_with_mh", "—", "NONE", "No Schwab market-field derivation in function body."),
    DerivationRecord("call_engine.py", "75", "_classify_trade_type", "upstream ms_dict / SignalInput", "KEEP_DERIVED", "Consumes upstream Schwab-first market state; no new wire ingest."),
    DerivationRecord("call_engine.py", "112", "_build_invalidation", "upstream ms_dict / SignalInput", "KEEP_DERIVED", "Consumes upstream Schwab-first market state; no new wire ingest."),
    DerivationRecord("call_engine.py", "148", "_time_qualifier", "upstream ms_dict / SignalInput", "KEEP_DERIVED", "Consumes upstream Schwab-first market state; no new wire ingest."),
    DerivationRecord("call_engine.py", "171", "replay_max_hold_bars_for_setup", "snapshots.* / replay dict", "PASS_THROUGH", "Reads persisted snapshot or replay payload only."),
    DerivationRecord("call_engine.py", "196", "_mc_reasoning_snippet", "—", "NONE", "No Schwab market-field derivation in function body."),
    DerivationRecord("call_engine.py", "221", "_build_call_headlines", "upstream ms_dict / SignalInput", "KEEP_DERIVED", "Consumes upstream Schwab-first market state; no new wire ingest."),
    DerivationRecord("call_engine.py", "304", "_greek_notes", "upstream ms_dict / SignalInput", "KEEP_DERIVED", "Consumes upstream Schwab-first market state; no new wire ingest."),
    DerivationRecord("call_engine.py", "327", "_add_greek_color", "—", "NONE", "No Schwab market-field derivation in function body."),
    DerivationRecord("call_engine.py", "333", "_canonical_stack_vote", "—", "NONE", "No Schwab market-field derivation in function body."),
    DerivationRecord("call_engine.py", "350", "_fusion_authoritative_directional_vote", "—", "NONE", "No Schwab market-field derivation in function body."),
    DerivationRecord("call_engine.py", "362", "_index_basket_vote", "upstream ms_dict / SignalInput", "KEEP_DERIVED", "Consumes upstream Schwab-first market state; no new wire ingest."),
    DerivationRecord("call_engine.py", "393", "_cross_instrument_signal", "upstream ms_dict / SignalInput", "KEEP_DERIVED", "Consumes upstream Schwab-first market state; no new wire ingest."),
    DerivationRecord("call_engine.py", "432", "_cross_instrument_notes", "upstream ms_dict / SignalInput", "KEEP_DERIVED", "Consumes upstream Schwab-first market state; no new wire ingest."),
    DerivationRecord("call_engine.py", "464", "_stop_distance", "upstream ms_dict / SignalInput", "KEEP_DERIVED", "Consumes upstream Schwab-first market state; no new wire ingest."),
    DerivationRecord("call_engine.py", "484", "_compute_levels", "structural levels, spot", "KEEP_DERIVED", "Stop/target levels from key levels + spot."),
    DerivationRecord("call_engine.py", "529", "_compute_levels._structural_levels", "key levels", "KEEP_DERIVED", "Nested structural level picker."),
    DerivationRecord("call_engine.py", "534", "_compute_levels._targets", "upstream ms_dict / SignalInput", "KEEP_DERIVED", "Consumes upstream Schwab-first market state; no new wire ingest."),
    DerivationRecord("call_engine.py", "545", "_compute_levels._long_levels", "upstream ms_dict / SignalInput", "KEEP_DERIVED", "Consumes upstream Schwab-first market state; no new wire ingest."),
    DerivationRecord("call_engine.py", "555", "_compute_levels._short_levels", "upstream ms_dict / SignalInput", "KEEP_DERIVED", "Consumes upstream Schwab-first market state; no new wire ingest."),
    DerivationRecord("call_engine.py", "589", "_downgrade", "—", "NONE", "No Schwab market-field derivation in function body."),
    DerivationRecord("call_engine.py", "601", "_conviction_from_canonical_forecast", "—", "NONE", "No Schwab market-field derivation in function body."),
    DerivationRecord("call_engine.py", "638", "_size_note", "—", "NONE", "No Schwab market-field derivation in function body."),
    DerivationRecord("call_engine.py", "666", "compute_position_size", "upstream ms_dict / SignalInput", "KEEP_DERIVED", "Consumes upstream Schwab-first market state; no new wire ingest."),
    DerivationRecord("call_engine.py", "954", "_validate_trade", "upstream ms_dict / SignalInput", "KEEP_DERIVED", "Consumes upstream Schwab-first market state; no new wire ingest."),
    DerivationRecord("call_engine.py", "1156", "compute_call", "CallInput / levels", "KEEP_DERIVED", "Trade call synthesis from upstream signals and levels."),
    DerivationRecord("multi_horizon_decision.py", "173", "MultiHorizonSynthesis.final_tradeable_decision", "—", "NONE", "No Schwab market-field derivation in function body."),
    DerivationRecord("multi_horizon_decision.py", "176", "MultiHorizonSynthesis.mh_directional_vote", "—", "NONE", "No Schwab market-field derivation in function body."),
    DerivationRecord("multi_horizon_decision.py", "181", "MultiHorizonSynthesis.mh_veto_stack_directional", "—", "NONE", "No Schwab market-field derivation in function body."),
    DerivationRecord("multi_horizon_decision.py", "189", "compute_multi_horizon_synthesis", "horizon rows", "KEEP_DERIVED", "Synthesis across horizon forecasts."),
    DerivationRecord("multi_horizon_decision.py", "353", "finalize_multi_horizon_bundle", "—", "NONE", "No Schwab market-field derivation in function body."),
    DerivationRecord("multi_horizon_decision.py", "463", "_safe_prob", "model probabilities", "KEEP_DERIVED", "Probability math on model outputs."),
    DerivationRecord("multi_horizon_decision.py", "475", "_norm_triplet", "—", "NONE", "No Schwab market-field derivation in function body."),
    DerivationRecord("multi_horizon_decision.py", "485", "_confidence_from_probs", "model probabilities", "KEEP_DERIVED", "Probability math on model outputs."),
    DerivationRecord("multi_horizon_decision.py", "499", "_infer_trade_mode", "—", "NONE", "No Schwab market-field derivation in function body."),
    DerivationRecord("multi_horizon_decision.py", "512", "_primary_order_for_mode", "—", "NONE", "No Schwab market-field derivation in function body."),
    DerivationRecord("multi_horizon_decision.py", "528", "_forecast_horizon_live", "snapshots.* / replay dict", "PASS_THROUGH", "Reads persisted snapshot or replay payload only."),
    DerivationRecord("multi_horizon_decision.py", "625", "_quality_from_alignment", "—", "NONE", "No Schwab market-field derivation in function body."),
    DerivationRecord("multi_horizon_decision.py", "651", "_alignment_state", "upstream ms_dict / SignalInput", "KEEP_DERIVED", "Consumes upstream Schwab-first market state; no new wire ingest."),
    DerivationRecord("multi_horizon_decision.py", "699", "_support_role", "—", "NONE", "No Schwab market-field derivation in function body."),
    DerivationRecord("multi_horizon_decision.py", "721", "_row_state", "—", "NONE", "No Schwab market-field derivation in function body."),
    DerivationRecord("multi_horizon_decision.py", "731", "_entry_state_machine", "upstream ms_dict / SignalInput", "KEEP_DERIVED", "Consumes upstream Schwab-first market state; no new wire ingest."),
    DerivationRecord("multi_horizon_decision.py", "762", "_ml_consensus_vote", "—", "NONE", "No Schwab market-field derivation in function body."),
    DerivationRecord("multi_horizon_decision.py", "780", "build_multi_horizon_bundle", "horizon triplets", "KEEP_DERIVED", "Multi-horizon bundle assembly."),
    DerivationRecord("multi_horizon_ml_bundle.py", "41", "_safe_norm_triplet", "—", "NONE", "No Schwab market-field derivation in function body."),
    DerivationRecord("multi_horizon_ml_bundle.py", "105", "MultiHorizonMLFusionBundle.snapshot", "snapshots.* / replay dict", "PASS_THROUGH", "Reads persisted snapshot or replay payload only."),
    DerivationRecord("multi_horizon_ml_bundle.py", "111", "MultiHorizonMLFusionBundle.fusion_available", "—", "NONE", "No Schwab market-field derivation in function body."),
    DerivationRecord("multi_horizon_ml_bundle.py", "121", "fusion_payload_to_horizon_snapshot", "snapshots.* / replay dict", "PASS_THROUGH", "Reads persisted snapshot or replay payload only."),
    DerivationRecord("multi_horizon_ml_bundle.py", "225", "build_multi_horizon_ml_fusion_bundle", "ML fusion outputs", "KEEP_DERIVED", "MH ML fusion bundle from model outputs."),
)

SECTION6_FILES = frozenset({
    "signals.py",
    "signal_helpers.py",
    "signal_types.py",
    "rules_engine.py",
    "prediction_engine.py",
    "call_engine.py",
    "multi_horizon_decision.py",
    "multi_horizon_ml_bundle.py",
})

