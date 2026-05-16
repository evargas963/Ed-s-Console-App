"""
Section 9 Schwab-leaf derivation audit inventory (features / ML inputs).

One row per ``def`` in ``features/*.py`` (module, class method, nested helper).
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


SECTION9_DERIVATION_INVENTORY: tuple[DerivationRecord, ...] = (

    DerivationRecord("features/canonical_contract.py", "251", "get_mvp_feature_names", "canonical feature fields", "KEEP_DERIVED", "Feature-layer transform on upstream Schwab-first inputs."),
    DerivationRecord("features/canonical_contract.py", "256", "get_feature_spec", "canonical feature fields", "KEEP_DERIVED", "Feature-layer transform on upstream Schwab-first inputs."),
    DerivationRecord("features/canonical_contract.py", "263", "get_mvp_field_semantics", "canonical feature fields", "KEEP_DERIVED", "Feature-layer transform on upstream Schwab-first inputs."),
    DerivationRecord("features/canonical_contract.py", "270", "validate_feature_contract_row", "—", "NONE", "Schema/contract validation; no market-field derivation."),
    DerivationRecord("features/canonical_contract.py", "344", "excluded_from_mvp", "—", "NONE", "No Schwab market-field derivation in function body."),
    DerivationRecord("features/cascade_stack_contract.py", "68", "validate_cascade_inference_lineage", "—", "NONE", "Schema/contract validation; no market-field derivation."),
    DerivationRecord("features/cascade_stack_contract.py", "124", "assert_no_legacy_mvp_in_fusion_overlay", "canonical feature fields", "KEEP_DERIVED", "Feature-layer transform on upstream Schwab-first inputs."),
    DerivationRecord("features/cascade_stack_schema.py", "28", "build_cascade_challenger_run_metadata", "—", "NONE", "Schema/contract validation; no market-field derivation."),
    DerivationRecord("features/db_feature_adapter.py", "20", "build_db_mvp_feature_row", "snapshots.* / InferenceSnapshotV1", "KEEP_DERIVED", "Feature builder from upstream or persisted canonical inputs."),
    DerivationRecord("features/feature_gap_report.py", "10", "compare_live_and_db_feature_support", "—", "NONE", "Schema/contract validation; no market-field derivation."),
    DerivationRecord("features/fusion_model_input.py", "28", "similar_setup_filters_from_canonical_features", "canonical feature fields", "KEEP_DERIVED", "Feature-layer transform on upstream Schwab-first inputs."),
    DerivationRecord("features/fusion_model_input.py", "50", "similar_setup_filters_from_db_snapshot_row", "canonical feature fields", "KEEP_DERIVED", "Feature-layer transform on upstream Schwab-first inputs."),
    DerivationRecord("features/fusion_model_input.py", "65", "strip_mvp_keys_from_fusion_overlay", "canonical feature fields", "KEEP_DERIVED", "Feature-layer transform on upstream Schwab-first inputs."),
    DerivationRecord("features/fusion_model_input.py", "70", "assert_fusion_overlay_has_no_mvp_keys", "canonical feature fields", "KEEP_DERIVED", "Feature-layer transform on upstream Schwab-first inputs."),
    DerivationRecord("features/fusion_model_input.py", "79", "validate_inference_snapshot_for_fusion_stack", "—", "NONE", "Schema/contract validation; no market-field derivation."),
    DerivationRecord("features/fusion_policy_contract.py", "15", "fusion_payload_to_policy_columns", "snapshots.* / InferenceSnapshotV1", "KEEP_DERIVED", "Feature builder from upstream or persisted canonical inputs."),
    DerivationRecord("features/fusion_policy_contract.py", "58", "policy_move_column", "—", "NONE", "No Schwab market-field derivation in function body."),
    DerivationRecord("features/fusion_policy_contract.py", "62", "policy_dir_up_column", "—", "NONE", "No Schwab market-field derivation in function body."),
    DerivationRecord("features/fusion_replay_grade_v1.py", "9", "fusion_replay_stack_grade_v1", "—", "NONE", "No Schwab market-field derivation in function body."),
    DerivationRecord("features/inference_snapshot.py", "26", "build_feature_lineage_map", "snapshots.* / InferenceSnapshotV1", "KEEP_DERIVED", "Feature builder from upstream or persisted canonical inputs."),
    DerivationRecord("features/inference_snapshot.py", "46", "_feature_quality_from_row", "canonical feature fields", "KEEP_DERIVED", "Feature-layer transform on upstream Schwab-first inputs."),
    DerivationRecord("features/inference_snapshot.py", "56", "build_inference_snapshot_v1_from_feature_row", "—", "NONE", "Schema/contract validation; no market-field derivation."),
    DerivationRecord("features/inference_snapshot.py", "95", "build_inference_snapshot_v1_from_db_row", "snapshots.* / InferenceSnapshotV1", "KEEP_DERIVED", "Feature builder from upstream or persisted canonical inputs."),
    DerivationRecord("features/inference_snapshot.py", "113", "build_inference_snapshot_v1_from_signal_input", "snapshots.* / InferenceSnapshotV1", "KEEP_DERIVED", "Feature builder from upstream or persisted canonical inputs."),
    DerivationRecord("features/inference_snapshot.py", "118", "build_inference_snapshot_v1_from_signal_input._dist_to_vwap_pts", "canonical feature fields", "KEEP_DERIVED", "Feature-layer transform on upstream Schwab-first inputs."),
    DerivationRecord("features/inference_snapshot.py", "157", "build_inference_snapshot_v1", "ms_dict / DB row", "KEEP_DERIVED", "Canonical inference row from upstream market state."),
    DerivationRecord("features/inference_snapshot.py", "206", "_assert_inference_snapshot_v1", "—", "NONE", "Schema/contract validation; no market-field derivation."),
    DerivationRecord("features/live_feature_adapter.py", "25", "build_live_mvp_feature_row", "snapshots.* / InferenceSnapshotV1", "KEEP_DERIVED", "Feature builder from upstream or persisted canonical inputs."),
    DerivationRecord("features/lstm_sequence_input.py", "82", "_canonical_missing_masks", "canonical feature fields", "KEEP_DERIVED", "Feature-layer transform on upstream Schwab-first inputs."),
    DerivationRecord("features/lstm_sequence_input.py", "86", "_patch_lstm_categoricals", "canonical feature fields", "KEEP_DERIVED", "Feature-layer transform on upstream Schwab-first inputs."),
    DerivationRecord("features/lstm_sequence_input.py", "107", "encode_lstm_structure_bar_with_masks", "canonical feature fields", "KEEP_DERIVED", "Feature-layer transform on upstream Schwab-first inputs."),
    DerivationRecord("features/lstm_sequence_input.py", "123", "encode_lstm_micro_bar_with_masks", "—", "NONE", "Schema/contract validation; no market-field derivation."),
    DerivationRecord("features/lstm_sequence_input.py", "135", "merge_db_row_with_canonical_mvp", "canonical feature fields", "KEEP_DERIVED", "Feature-layer transform on upstream Schwab-first inputs."),
    DerivationRecord("features/lstm_sequence_input.py", "149", "_ts_close", "—", "NONE", "No Schwab market-field derivation in function body."),
    DerivationRecord("features/lstm_sequence_input.py", "158", "build_lstm_merged_windows", "—", "NONE", "Schema/contract validation; no market-field derivation."),
    DerivationRecord("features/lstm_sequence_input.py", "217", "build_transformer_merged_window", "snapshots.* / InferenceSnapshotV1", "KEEP_DERIVED", "Feature builder from upstream or persisted canonical inputs."),
    DerivationRecord("features/monte_carlo_stack_input.py", "31", "resolve_monte_carlo_stack_inputs", "canonical feature fields", "KEEP_DERIVED", "Feature-layer transform on upstream Schwab-first inputs."),
    DerivationRecord("features/mvp_source_coercion.py", "27", "_contains_key", "—", "NONE", "No Schwab market-field derivation in function body."),
    DerivationRecord("features/mvp_source_coercion.py", "34", "strict_float_from_raw", "canonical feature fields", "KEEP_DERIVED", "Fail-closed numeric coercion; no silent default to 0."),
    DerivationRecord("features/mvp_source_coercion.py", "53", "read_optional_float", "canonical feature fields", "KEEP_DERIVED", "Feature-layer transform on upstream Schwab-first inputs."),
    DerivationRecord("features/mvp_source_coercion.py", "66", "read_optional_zone", "—", "NONE", "Schema/contract validation; no market-field derivation."),
    DerivationRecord("features/mvp_source_coercion.py", "88", "read_optional_vwap_side", "—", "NONE", "Schema/contract validation; no market-field derivation."),
    DerivationRecord("features/mvp_source_coercion.py", "110", "read_liquidity_summary_subdict", "canonical feature fields", "KEEP_DERIVED", "Feature-layer transform on upstream Schwab-first inputs."),
    DerivationRecord("features/parallel_stack_schema.py", "31", "empty_parallel_output", "—", "NONE", "Schema/contract validation; no market-field derivation."),
    DerivationRecord("features/parallel_stack_schema.py", "47", "build_parallel_base_output", "—", "NONE", "Schema/contract validation; no market-field derivation."),
    DerivationRecord("features/regime_mvp_context.py", "19", "require_mvp_features", "canonical feature fields", "KEEP_DERIVED", "Feature-layer transform on upstream Schwab-first inputs."),
    DerivationRecord("features/regime_mvp_context.py", "26", "mvp_zone", "—", "NONE", "No Schwab market-field derivation in function body."),
    DerivationRecord("features/regime_mvp_context.py", "33", "mvp_spot", "canonical feature fields", "KEEP_DERIVED", "Feature-layer transform on upstream Schwab-first inputs."),
    DerivationRecord("features/regime_mvp_context.py", "45", "mvp_vwap_side", "canonical feature fields", "KEEP_DERIVED", "Feature-layer transform on upstream Schwab-first inputs."),
    DerivationRecord("features/regime_mvp_context.py", "52", "mvp_nearest_distances_for_regime", "canonical feature fields", "KEEP_DERIVED", "Feature-layer transform on upstream Schwab-first inputs."),
    DerivationRecord("features/regime_mvp_context.py", "59", "mvp_net_gamma", "canonical feature fields", "KEEP_DERIVED", "Feature-layer transform on upstream Schwab-first inputs."),
    DerivationRecord("features/replay_signal_input_v1.py", "16", "_positive_float_required", "canonical feature fields", "KEEP_DERIVED", "Feature-layer transform on upstream Schwab-first inputs."),
    DerivationRecord("features/replay_signal_input_v1.py", "29", "signal_input_from_snapshot_row_dict", "canonical feature fields", "KEEP_DERIVED", "Feature-layer transform on upstream Schwab-first inputs."),
    DerivationRecord("features/semantic_parity.py", "17", "assert_live_db_canonicalization_equivalent", "canonical feature fields", "KEEP_DERIVED", "Feature-layer transform on upstream Schwab-first inputs."),
    DerivationRecord("features/shared_sequence_context.py", "33", "_max_transformer_seq_len_for_ticker", "canonical feature fields", "KEEP_DERIVED", "Feature-layer transform on upstream Schwab-first inputs."),
    DerivationRecord("features/shared_sequence_context.py", "63", "build_shared_sequence_context", "snapshots DB", "PASS_THROUGH", "Shared LSTM/Transformer sequence fetch from DB."),
    DerivationRecord("features/shared_sequence_context.py", "132", "transformer_window_chronological", "canonical feature fields", "KEEP_DERIVED", "Feature-layer transform on upstream Schwab-first inputs."),
    DerivationRecord("features/signal_layer_v1.py", "34", "_f", "—", "NONE", "No Schwab market-field derivation in function body."),
    DerivationRecord("features/signal_layer_v1.py", "46", "_clip", "—", "NONE", "No Schwab market-field derivation in function body."),
    DerivationRecord("features/signal_layer_v1.py", "50", "_safe_div", "canonical feature fields", "KEEP_DERIVED", "Feature-layer transform on upstream Schwab-first inputs."),
    DerivationRecord("features/signal_layer_v1.py", "56", "_tr", "—", "NONE", "No Schwab market-field derivation in function body."),
    DerivationRecord("features/signal_layer_v1.py", "71", "_atr", "—", "NONE", "No Schwab market-field derivation in function body."),
    DerivationRecord("features/signal_layer_v1.py", "83", "_percentile_rank_window", "—", "NONE", "No Schwab market-field derivation in function body."),
    DerivationRecord("features/signal_layer_v1.py", "92", "_ols_slope_yx", "—", "NONE", "No Schwab market-field derivation in function body."),
    DerivationRecord("features/signal_layer_v1.py", "106", "_ols_log_slope_close", "—", "NONE", "No Schwab market-field derivation in function body."),
    DerivationRecord("features/signal_layer_v1.py", "114", "_fractal_swings", "canonical feature fields", "KEEP_DERIVED", "Feature-layer transform on upstream Schwab-first inputs."),
    DerivationRecord("features/signal_layer_v1.py", "141", "_aggregate_bars", "canonical feature fields", "KEEP_DERIVED", "Feature-layer transform on upstream Schwab-first inputs."),
    DerivationRecord("features/signal_layer_v1.py", "168", "_sign_trend", "—", "NONE", "No Schwab market-field derivation in function body."),
    DerivationRecord("features/signal_layer_v1.py", "178", "_volume_profile_proxy", "canonical feature fields", "KEEP_DERIVED", "Feature-layer transform on upstream Schwab-first inputs."),
    DerivationRecord("features/signal_layer_v1.py", "228", "load_bars_before_decision", "snapshots.* / InferenceSnapshotV1", "KEEP_DERIVED", "Feature builder from upstream or persisted canonical inputs."),
    DerivationRecord("features/signal_layer_v1.py", "257", "compute_signal_layer_v1", "canonical feature fields", "KEEP_DERIVED", "Feature-layer transform on upstream Schwab-first inputs."),
    DerivationRecord("features/signal_layer_v1.py", "596", "compute_signal_layer_v1_from_db", "—", "NONE", "No Schwab market-field derivation in function body."),
    DerivationRecord("features/signal_layer_v1.py", "609", "_sqlite_conn_from_db", "—", "NONE", "No Schwab market-field derivation in function body."),
    DerivationRecord("features/signal_layer_v1.py", "619", "compute_signal_layer_v1_for_calibration", "—", "NONE", "No Schwab market-field derivation in function body."),
    DerivationRecord("features/signal_layer_v1.py", "640", "layer_direction_policy", "canonical feature fields", "KEEP_DERIVED", "Feature-layer transform on upstream Schwab-first inputs."),
    DerivationRecord("features/signal_layer_v1.py", "663", "signal_layer_v1_to_direction_probs", "canonical feature fields", "KEEP_DERIVED", "Feature-layer transform on upstream Schwab-first inputs."),
    DerivationRecord("features/signal_layer_v1.py", "694", "flatten_numeric_features", "canonical feature fields", "KEEP_DERIVED", "Feature-layer transform on upstream Schwab-first inputs."),
    DerivationRecord("features/stack_integrity_v1.py", "15", "record_stack_degradation", "—", "NONE", "No Schwab market-field derivation in function body."),
    DerivationRecord("features/stack_integrity_v1.py", "45", "merge_stack_integrity_events", "—", "NONE", "Schema/contract validation; no market-field derivation."),
    DerivationRecord("features/stack_integrity_v1.py", "55", "finalize_stack_integrity_v1", "—", "NONE", "Schema/contract validation; no market-field derivation."),
    DerivationRecord("features/training_canonical_input.py", "30", "training_canonical_lineage_header", "—", "NONE", "Schema/contract validation; no market-field derivation."),
    DerivationRecord("features/training_canonical_input.py", "38", "assert_training_lineage_matches_canonical", "—", "NONE", "Schema/contract validation; no market-field derivation."),
    DerivationRecord("features/training_canonical_input.py", "55", "training_snapshot_for_sequence_encode", "—", "NONE", "Schema/contract validation; no market-field derivation."),
    DerivationRecord("features/training_canonical_input.py", "72", "_row_dict_from_df", "—", "NONE", "No Schwab market-field derivation in function body."),
    DerivationRecord("features/training_canonical_input.py", "76", "validate_tabular_training_dataframe_canonical", "—", "NONE", "Schema/contract validation; no market-field derivation."),
    DerivationRecord("features/training_canonical_input.py", "107", "assert_shared_feature_cache_keys_equal", "canonical feature fields", "KEEP_DERIVED", "Feature-layer transform on upstream Schwab-first inputs."),
    DerivationRecord("features/xgb_model_input.py", "47", "validate_inference_snapshot_v1_envelope", "—", "NONE", "Schema/contract validation; no market-field derivation."),
    DerivationRecord("features/xgb_model_input.py", "73", "validate_inference_snapshot_v1_for_xgb", "—", "NONE", "Schema/contract validation; no market-field derivation."),
    DerivationRecord("features/xgb_model_input.py", "90", "_et_from_ts_utc", "—", "NONE", "No Schwab market-field derivation in function body."),
    DerivationRecord("features/xgb_model_input.py", "95", "inference_snapshot_v1_to_engineering_snapshot", "—", "NONE", "Schema/contract validation; no market-field derivation."),
    DerivationRecord("features/xgb_model_input.py", "119", "merge_xgb_fusion_overlay", "canonical feature fields", "KEEP_DERIVED", "Feature-layer transform on upstream Schwab-first inputs."),
    DerivationRecord("features/xgb_model_input.py", "137", "assert_not_raw_l1_payload", "canonical feature fields", "KEEP_DERIVED", "Feature-layer transform on upstream Schwab-first inputs."),
)

SECTION9_FILES = frozenset({
    "features/canonical_contract.py",
    "features/cascade_stack_contract.py",
    "features/cascade_stack_schema.py",
    "features/db_feature_adapter.py",
    "features/feature_gap_report.py",
    "features/fusion_model_input.py",
    "features/fusion_policy_contract.py",
    "features/fusion_replay_grade_v1.py",
    "features/inference_snapshot.py",
    "features/live_feature_adapter.py",
    "features/lstm_sequence_input.py",
    "features/monte_carlo_stack_input.py",
    "features/mvp_source_coercion.py",
    "features/parallel_stack_schema.py",
    "features/regime_mvp_context.py",
    "features/replay_signal_input_v1.py",
    "features/semantic_parity.py",
    "features/shared_sequence_context.py",
    "features/signal_layer_v1.py",
    "features/stack_integrity_v1.py",
    "features/training_canonical_input.py",
    "features/xgb_model_input.py",
})

