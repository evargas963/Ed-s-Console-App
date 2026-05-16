"""
Section 15 Schwab-leaf derivation audit inventory (audit + verify + config + contracts).

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


SECTION15_DERIVATION_INVENTORY: tuple[DerivationRecord, ...] = (

    DerivationRecord("audit_expiry_data.py", "27", "main", "—", "NONE", "CLI entrypoint."),
    DerivationRecord("audit_gate_labels.py", "21", "main", "—", "NONE", "CLI entrypoint."),
    DerivationRecord("audit_model_readiness.py", "111", "_connect", "snapshots.* / artifacts", "KEEP_DERIVED", "Audit/verify pass on persisted snapshots or artifacts."),
    DerivationRecord("audit_model_readiness.py", "119", "_col_exists", "snapshots.* / artifacts", "KEEP_DERIVED", "Audit/verify pass on persisted snapshots or artifacts."),
    DerivationRecord("audit_model_readiness.py", "127", "_count", "snapshots.* / artifacts", "KEEP_DERIVED", "Audit/verify pass on persisted snapshots or artifacts."),
    DerivationRecord("audit_model_readiness.py", "135", "main", "—", "NONE", "CLI entrypoint."),
    DerivationRecord("audit_snapshot_data.py", "31", "connect", "snapshots.* / artifacts", "KEEP_DERIVED", "Audit/verify pass on persisted snapshots or artifacts."),
    DerivationRecord("audit_snapshot_data.py", "37", "run_audit", "snapshots.* / artifacts", "KEEP_DERIVED", "Audit/verify pass on persisted snapshots or artifacts."),
    DerivationRecord("audit_training_data.py", "29", "main", "—", "NONE", "CLI entrypoint."),
    DerivationRecord("canonical_distances.py", "13", "canonical_nearest_distances", "design constants", "NONE", "Institutional behavior / distance design definitions."),
    DerivationRecord("canonical_distances.py", "37", "canonicalize_distance_read", "design constants", "NONE", "Institutional behavior / distance design definitions."),
    DerivationRecord("config.py", "38", "build_config", "env / paths", "NONE", "Loads app config from env/files."),
    DerivationRecord("feature_contract_validation.py", "27", "ContractValidationReport.to_dict", "contract schema", "NONE", "Contract/design module; no Schwab derivation."),
    DerivationRecord("feature_contract_validation.py", "37", "_active_xgb_meta_files", "snapshots.* / contract", "NONE", "Contract module referencing snapshot fields without live ingest."),
    DerivationRecord("feature_contract_validation.py", "44", "_validate_xgb_train_infer_meta_parity", "contract schema", "NONE", "Static contract/schema definition or validation."),
    DerivationRecord("feature_contract_validation.py", "81", "_validate_registry_policy", "contract schema", "NONE", "Static contract/schema definition or validation."),
    DerivationRecord("feature_contract_validation.py", "104", "_validate_forbidden_reappearance_in_engineering_path", "contract schema", "NONE", "Static contract/schema definition or validation."),
    DerivationRecord("feature_contract_validation.py", "128", "_validate_lstm_transformer_contracts", "contract schema", "NONE", "Static contract/schema definition or validation."),
    DerivationRecord("feature_contract_validation.py", "167", "_validate_fusion_prediction_policy", "contract schema", "NONE", "Static contract/schema definition or validation."),
    DerivationRecord("feature_contract_validation.py", "178", "validate_feature_contracts", "contract schema", "NONE", "Static contract/schema definition or validation."),
    DerivationRecord("horizon_outcomes.py", "54", "_outcome_slug", "contract schema", "NONE", "Contract/design module; no Schwab derivation."),
    DerivationRecord("horizon_outcomes.py", "85", "forward_bar_start_utc", "snapshots.* / contract", "NONE", "Contract module referencing snapshot fields without live ingest."),
    DerivationRecord("horizon_outcomes.py", "91", "bar_complete_by_utc", "contract schema", "NONE", "Contract/design module; no Schwab derivation."),
    DerivationRecord("horizon_outcomes.py", "96", "expected_bar_end_utc", "contract schema", "NONE", "Contract/design module; no Schwab derivation."),
    DerivationRecord("horizon_outcomes.py", "100", "pts_move_anchor_close_to_forward_close", "contract schema", "NONE", "Contract/design module; no Schwab derivation."),
    DerivationRecord("inspect_trading_data.py", "95", "build_category_map", "snapshots.*", "KEEP_DERIVED", "Inspection/readiness on stored trading data."),
    DerivationRecord("inspect_trading_data.py", "187", "main", "—", "NONE", "CLI entrypoint."),
    DerivationRecord("institutional_behavior.py", "13", "_clip01", "design constants", "NONE", "Institutional behavior / distance design definitions."),
    DerivationRecord("institutional_behavior.py", "17", "compute_liquidity_behavior_row", "design constants", "NONE", "Institutional behavior / distance design definitions."),
    DerivationRecord("instrument_identity.py", "26", "ticker_storage_key", "—", "NONE", "Configuration/identity helper; no market-field derivation."),
    DerivationRecord("model_contract.py", "29", "contract_metadata_dict", "snapshots.* / contract", "NONE", "Contract module referencing snapshot fields without live ingest."),
    DerivationRecord("model_contract.py", "40", "meta_matches_system_contract", "snapshots.* / contract", "NONE", "Contract module referencing snapshot fields without live ingest."),
    DerivationRecord("model_contract.py", "51", "_xgb_impute_complete", "snapshots.* / contract", "NONE", "Contract module referencing snapshot fields without live ingest."),
    DerivationRecord("model_contract.py", "58", "validate_artifact_contract", "contract schema", "NONE", "Static contract/schema definition or validation."),
    DerivationRecord("model_contract.py", "78", "provenance_dict_with_contract", "contract schema", "NONE", "Contract/design module; no Schwab derivation."),
    DerivationRecord("movement_target_threshold.py", "23", "load_movement_thresholds_by_horizon_v1", "contract schema", "NONE", "Static contract/schema definition or validation."),
    DerivationRecord("movement_target_threshold.py", "31", "load_legacy_atr_params", "contract schema", "NONE", "Contract/design module; no Schwab derivation."),
    DerivationRecord("movement_target_threshold.py", "42", "movement_threshold_pts_v1", "contract schema", "NONE", "Static contract/schema definition or validation."),
    DerivationRecord("movement_target_threshold.py", "66", "threshold_move_pts_for_slug", "contract schema", "NONE", "Static contract/schema definition or validation."),
    DerivationRecord("movement_target_threshold.py", "90", "invalid_for_dir_target", "contract schema", "NONE", "Contract/design module; no Schwab derivation."),
    DerivationRecord("movement_target_threshold.py", "96", "directional_and_move_labels_v2", "contract schema", "NONE", "Contract/design module; no Schwab derivation."),
    DerivationRecord("movement_target_threshold.py", "121", "directional_and_move_labels_v1", "contract schema", "NONE", "Contract/design module; no Schwab derivation."),
    DerivationRecord("movement_target_threshold.py", "131", "load_movement_threshold_params_v1", "contract schema", "NONE", "Static contract/schema definition or validation."),
    DerivationRecord("production_universe.py", "35", "normalize_production_ticker", "universe config", "NONE", "Production ticker universe list."),
    DerivationRecord("production_universe.py", "40", "is_valid_production_ticker", "universe config", "NONE", "Production ticker universe list."),
    DerivationRecord("production_universe.py", "49", "assert_valid_production_ticker", "universe config", "NONE", "Production ticker universe list."),
    DerivationRecord("production_universe.py", "56", "filter_valid_tickers", "universe config", "NONE", "Production ticker universe list."),
    DerivationRecord("scheduler_user_tickers.py", "23", "load_user_scheduler_tickers", "—", "NONE", "Configuration/identity helper; no market-field derivation."),
    DerivationRecord("scheduler_user_tickers.py", "38", "record_user_ticker", "—", "NONE", "Configuration/identity helper; no market-field derivation."),
    DerivationRecord("setup_readiness.py", "6", "_clamp", "—", "NONE", "Inspection/readiness utility."),
    DerivationRecord("setup_readiness.py", "10", "_safe_lower", "—", "NONE", "Inspection/readiness utility."),
    DerivationRecord("setup_readiness.py", "28", "compute_call_readiness", "snapshots.*", "KEEP_DERIVED", "Inspection/readiness on stored trading data."),
    DerivationRecord("setup_readiness.py", "230", "compute_put_readiness", "snapshots.*", "KEEP_DERIVED", "Inspection/readiness on stored trading data."),
    DerivationRecord("ticker_readiness_lookup.py", "11", "load_ticker_readiness_lookup", "ticker metadata", "NONE", "Ticker readiness/diagnostics; no Schwab API."),
    DerivationRecord("ticker_readiness_lookup.py", "22", "get_ticker_readiness", "ticker metadata", "NONE", "Ticker readiness/diagnostics; no Schwab API."),
    DerivationRecord("ticker_switch_diagnostics.py", "17", "record_switch_event", "ticker metadata", "NONE", "Ticker readiness/diagnostics; no Schwab API."),
    DerivationRecord("ticker_switch_diagnostics.py", "25", "get_recent_events", "ticker metadata", "NONE", "Ticker readiness/diagnostics; no Schwab API."),
    DerivationRecord("tier3_design.py", "169", "_validation_evidence", "snapshots.* / contract", "NONE", "Contract module referencing snapshot fields without live ingest."),
    DerivationRecord("tier3_design.py", "192", "build_tier3_candidate_inventory_v1", "snapshots.* / contract", "NONE", "Contract module referencing snapshot fields without live ingest."),
    DerivationRecord("tier3_design.py", "206", "build_tier3_design_comparison_v1", "snapshots.* / contract", "NONE", "Contract module referencing snapshot fields without live ingest."),
    DerivationRecord("tier3_design.py", "265", "build_tier3_feature_decisions_v1", "snapshots.* / contract", "NONE", "Contract module referencing snapshot fields without live ingest."),
    DerivationRecord("tier3_design.py", "269", "build_tier3_feature_decisions_v1._c", "snapshots.* / contract", "NONE", "Contract module referencing snapshot fields without live ingest."),
    DerivationRecord("tier3_design.py", "397", "build_final_tier_architecture_proposal_v1", "snapshots.* / contract", "NONE", "Contract module referencing snapshot fields without live ingest."),
    DerivationRecord("tier3_design.py", "441", "run_tier3_context_probe", "snapshots.* / contract", "NONE", "Contract module referencing snapshot fields without live ingest."),
    DerivationRecord("tier3_design.py", "544", "emit_tier3_bundle_json", "snapshots.* / contract", "NONE", "Contract module referencing snapshot fields without live ingest."),
    DerivationRecord("verify_active_models.py", "35", "_get_active_tickers", "snapshots.* / artifacts", "KEEP_DERIVED", "Audit/verify pass on persisted snapshots or artifacts."),
    DerivationRecord("verify_active_models.py", "62", "_active_bundle_dir", "snapshots.* / artifacts", "KEEP_DERIVED", "Audit/verify pass on persisted snapshots or artifacts."),
    DerivationRecord("verify_active_models.py", "78", "check_artifact_compliance", "snapshots.* / artifacts", "KEEP_DERIVED", "Audit/verify pass on persisted snapshots or artifacts."),
    DerivationRecord("verify_active_models.py", "164", "main", "—", "NONE", "CLI entrypoint."),
    DerivationRecord("verify_mc_directional.py", "21", "_fmt", "—", "NONE", "Audit/verify helper; no live market ingest."),
    DerivationRecord("verify_mc_directional.py", "31", "_report_ticker", "snapshots.* / artifacts", "KEEP_DERIVED", "Audit/verify pass on persisted snapshots or artifacts."),
    DerivationRecord("verify_mc_directional.py", "81", "main", "—", "NONE", "CLI entrypoint."),
    DerivationRecord("verify_ml_pipeline.py", "20", "main", "—", "NONE", "CLI entrypoint."),
    DerivationRecord("verify_ml_pipeline.py", "23", "main.ok", "—", "NONE", "Audit/verify helper; no live market ingest."),
    DerivationRecord("verify_model_outputs.py", "13", "_fmt", "—", "NONE", "Audit/verify helper; no live market ingest."),
    DerivationRecord("verify_model_outputs.py", "23", "print_ticker", "snapshots.* / artifacts", "KEEP_DERIVED", "Audit/verify pass on persisted snapshots or artifacts."),
    DerivationRecord("verify_model_outputs.py", "42", "main", "—", "NONE", "CLI entrypoint."),
    DerivationRecord("verify_prefusion_mc.py", "14", "_minimal_inf_v1", "snapshots.* / artifacts", "KEEP_DERIVED", "Audit/verify pass on persisted snapshots or artifacts."),
    DerivationRecord("verify_prefusion_mc.py", "37", "main", "—", "NONE", "CLI entrypoint."),
    DerivationRecord("verify_prefusion_mc.py", "46", "main.capture_simulate", "—", "NONE", "Audit/verify helper; no live market ingest."),
    DerivationRecord("verify_snapshot_pipeline.py", "41", "print_header", "—", "NONE", "Audit/verify helper; no live market ingest."),
    DerivationRecord("verify_snapshot_pipeline.py", "47", "connect_db", "snapshots.* / artifacts", "KEEP_DERIVED", "Audit/verify pass on persisted snapshots or artifacts."),
    DerivationRecord("verify_snapshot_pipeline.py", "56", "check_schema", "snapshots.* / artifacts", "KEEP_DERIVED", "Audit/verify pass on persisted snapshots or artifacts."),
    DerivationRecord("verify_snapshot_pipeline.py", "82", "check_latest_snapshot", "snapshots.* / artifacts", "KEEP_DERIVED", "Audit/verify pass on persisted snapshots or artifacts."),
    DerivationRecord("verify_snapshot_pipeline.py", "117", "check_zone_state", "snapshots.* / artifacts", "KEEP_DERIVED", "Audit/verify pass on persisted snapshots or artifacts."),
    DerivationRecord("verify_snapshot_pipeline.py", "154", "check_snapshot_timeframe_canonical", "snapshots.* / artifacts", "KEEP_DERIVED", "Audit/verify pass on persisted snapshots or artifacts."),
    DerivationRecord("verify_snapshot_pipeline.py", "199", "check_mc_fields", "snapshots.* / artifacts", "KEEP_DERIVED", "Audit/verify pass on persisted snapshots or artifacts."),
    DerivationRecord("verify_snapshot_pipeline.py", "222", "list_tables", "snapshots.* / artifacts", "KEEP_DERIVED", "Audit/verify pass on persisted snapshots or artifacts."),
    DerivationRecord("verify_snapshot_pipeline.py", "229", "main", "—", "NONE", "CLI entrypoint."),
)

SECTION15_FILES = frozenset({
    "audit_expiry_data.py",
    "audit_gate_labels.py",
    "audit_model_readiness.py",
    "audit_snapshot_data.py",
    "audit_training_data.py",
    "canonical_distances.py",
    "config.py",
    "feature_contract_validation.py",
    "horizon_outcomes.py",
    "inspect_trading_data.py",
    "institutional_behavior.py",
    "instrument_identity.py",
    "model_contract.py",
    "movement_target_threshold.py",
    "production_universe.py",
    "scheduler_user_tickers.py",
    "setup_readiness.py",
    "ticker_readiness_lookup.py",
    "ticker_switch_diagnostics.py",
    "tier3_design.py",
    "timeframe_config.py",
    "verify_active_models.py",
    "verify_mc_directional.py",
    "verify_ml_pipeline.py",
    "verify_model_outputs.py",
    "verify_prefusion_mc.py",
    "verify_snapshot_pipeline.py",
})

