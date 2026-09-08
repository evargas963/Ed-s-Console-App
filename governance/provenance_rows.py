"""The provenance rows: one module, one row type, no bookkeeping rows.

GENERATED 2026-09-07 from the four mega inventories by the mega REPAIR (scratchpad/mega_build.py):
every row whose disposition carries provenance (SCHWAB_LEAF, REPLACED, DERIVED, ALLOWLISTED)
was copied verbatim; the 1,421 NONE rows (every-function bookkeeping) were dropped because a
row that says nothing about lineage proves nothing about lineage. Rows are keyed
(file, derivation) and resolved by governance/provenance_inventory.py. Edit by hand.
"""
from __future__ import annotations

from governance.provenance_inventory import Row

ROWS: tuple[Row, ...] = (
    Row(
        file='arch_competition/eval_runner.py', derivation='run_architecture_pair_evaluation', disposition='ALLOWLISTED',
        allowlist_id='mega1_sqlite_internal',
        justification='Orchestrator: passes db_path to ml_scheduler._evaluate_parallel_on_full_rth + _evaluate_cascade_on_full_rth which read persisted feature-snapshot SQLite rows. No direct Schwab wire derivation; the persisted rows trace to Mega1/2/3 producers via the canonical feature cache.',
    ),
    Row(
        file='arch_competition/live_drift_monitoring.py', derivation='build_live_drift_monitoring_payload', disposition='ALLOWLISTED',
        allowlist_id='mega1_sqlite_internal',
        justification='Orchestrator: composes governed baseline manifests + optional run_architecture_pair_evaluation (which reads persisted feature-snapshot SQLite rows via ml_scheduler). Output is a drift summary payload; no direct Schwab wire derivation.',
    ),
    Row(
        file='arch_competition/stack_bundle_eval_v1.py', derivation='_fusion_branch_to_prob_dict', disposition='DERIVED',
        producer_refs=('market_state.py:build_market_state',),
        justification='Probability fusion; consumes model outputs only.',
    ),
    Row(
        file='arch_competition/stack_bundle_eval_v1.py', derivation='_probs_from_fusion_branch', disposition='DERIVED',
        producer_refs=('market_state.py:build_market_state',),
        justification='Probability fusion; consumes model outputs only.',
    ),
    Row(
        file='arch_competition/stack_bundle_eval_v1.py', derivation='run_stack_bundle_evaluation', disposition='ALLOWLISTED',
        allowlist_id='mega1_sqlite_internal',
        justification='Orchestrator: takes db_path, calls ml_scheduler._load_rth_rows_for_ticker which reads persisted feature-snapshot SQLite rows, composes fusion-branch / meta-stack / xgb-only / triplet-explicit configs for paired evaluation. No direct Schwab wire derivation; the persisted rows trace to Mega1/2/3 producers via the canonical feature cache.',
    ),
    Row(
        file='bayesian_fusion.py', derivation='_bayesian_update', disposition='DERIVED',
        producer_refs=('market_state.py:build_market_state',),
        justification='Probability fusion; consumes model outputs only.',
    ),
    Row(
        file='bayesian_fusion.py', derivation='_fuse_impl', disposition='DERIVED',
        producer_refs=('bayesian_fusion.py:_translate_xgb_evidence', 'bayesian_fusion.py:_translate_lstm_evidence', 'bayesian_fusion.py:_translate_transformer_evidence', 'bayesian_fusion.py:_bayesian_update', 'market_state.py:build_market_state', 'bayesian_fusion.py:_translate_rules_evidence'),
        justification='Probability fusion; consumes model outputs only.',
    ),
    Row(
        file='bayesian_fusion.py', derivation='_translate_lstm_evidence', disposition='DERIVED',
        producer_refs=('market_state.py:build_market_state',),
        justification='Probability fusion; consumes model outputs only.',
    ),
    Row(
        file='bayesian_fusion.py', derivation='_translate_rules_evidence', disposition='DERIVED',
        producer_refs=('market_state.py:build_market_state',),
        justification='Probability fusion; consumes model outputs only.',
    ),
    Row(
        file='bayesian_fusion.py', derivation='_translate_transformer_evidence', disposition='DERIVED',
        producer_refs=('market_state.py:build_market_state',),
        justification='Probability fusion; consumes model outputs only.',
    ),
    Row(
        file='bayesian_fusion.py', derivation='_translate_xgb_evidence', disposition='DERIVED',
        producer_refs=('market_state.py:build_market_state',),
        justification='Probability fusion; consumes model outputs only.',
    ),
    Row(
        file='bayesian_fusion.py', derivation='build_fusion_tick_cache', disposition='DERIVED',
        producer_refs=('market_state.py:build_market_state', 'bayesian_fusion.py:_translate_rules_evidence'),
        justification='Probability fusion; consumes model outputs only.',
    ),
    Row(
        file='bayesian_fusion.py', derivation='fuse', disposition='DERIVED',
        producer_refs=('bayesian_fusion.py:_fuse_impl',),
        justification='Probability fusion; consumes model outputs only.',
    ),
    Row(
        file='calibration/a1_conformal_artifact_production.py', derivation='produce_a1_conformal_artifact', disposition='ALLOWLISTED',
        allowlist_id='mega1_sqlite_internal',
        justification='Orchestrator: takes db_path, calls calibration.v2_a1_calibration.load_a1_calibration_rows which reads persisted calibration rows from SQLite; composes fit_a1_isotonic_artifact + build_a1_conformal_artifact + lifecycle augmentation + atomic artifact + pointer writes. No direct Schwab wire derivation.',
    ),
    Row(
        file='calibration/a1_isotonic_artifact_production.py', derivation='produce_a1_isotonic_artifact', disposition='ALLOWLISTED',
        allowlist_id='mega1_sqlite_internal',
        justification='Orchestrator: takes db_path, calls calibration.v2_a1_calibration.load_a1_calibration_rows which reads persisted calibration rows from SQLite; composes fit_a1_isotonic_artifact + lifecycle augmentation + atomic artifact + pointer writes. No direct Schwab wire derivation.',
    ),
    Row(
        file='calibration/analyze_phase3.py', derivation='_snapshot_fallback', disposition='ALLOWLISTED',
        allowlist_id='mega1_sqlite_internal',
        justification='Opens a row read on the caller-supplied sqlite3 Connection (parameter, not opened here) to compute fallback bucket aggregates for phase3 analysis. Mega4 internal SQLite read; no Schwab wire derivation.',
    ),
    Row(
        file='calibration/analyze_phase3.py', derivation='analyze', disposition='ALLOWLISTED',
        allowlist_id='mega1_sqlite_internal',
        justification='Phase3 orchestrator: takes db_path, opens SQLite connection on the calibration DB, loads decision-log rows + snapshot fallback, composes Brier triplet + bucket statistical-integrity gates. No direct Schwab wire derivation.',
    ),
    Row(
        file='calibration/analyze_phase4.py', derivation='analyze', disposition='ALLOWLISTED',
        allowlist_id='mega1_sqlite_internal',
        justification='Phase4 orchestrator: takes db_path, opens SQLite connection on the calibration DB, reads decision-log + snapshot rows, computes directional-PnL EV by direction + bucket statistical-integrity. No direct Schwab wire derivation.',
    ),
    Row(
        file='calibration/anchor_audit.py', derivation='snapshot_has_bar_anchor', disposition='ALLOWLISTED',
        allowlist_id='mega1_sqlite_internal',
        justification='Reads via caller-supplied sqlite3.Connection (parameter, not opened here) to check whether a bar anchor exists for (ticker, ts_utc). Mega4 internal SQLite read; no Schwab wire derivation.',
    ),
    Row(
        file='calibration/audit_phase1.py', derivation='_connect', disposition='ALLOWLISTED',
        allowlist_id='mega1_sqlite_internal',
        justification='Opens a sqlite3 read-only connection on the caller-supplied db_path. Mega4 internal SQLite connection factory; no Schwab wire derivation.',
    ),
    Row(
        file='calibration/audit_phase1.py', derivation='_table_exists', disposition='ALLOWLISTED',
        allowlist_id='mega1_sqlite_internal',
        justification='Reads via caller-supplied sqlite3 Connection (sqlite_master row) to check table existence. Mega4 internal SQLite read; no Schwab wire derivation.',
    ),
    Row(
        file='calibration/backfill_outcomes.py', derivation='_resync_existing_outcomes_from_snapshots', disposition='ALLOWLISTED',
        allowlist_id='mega1_sqlite_internal',
        justification='Per-row outcomes resync writer on caller-supplied sqlite3 Connection. Persistence-only; no Schwab wire derivation.',
    ),
    Row(
        file='calibration/backfill_outcomes.py', derivation='backfill', disposition='ALLOWLISTED',
        allowlist_id='mega1_sqlite_internal',
        justification='Outcomes backfill orchestrator: takes db_path, opens SQLite read+write, iterates calibration_decision_log rows lacking outcomes and stamps from the resolved snapshot row. Persistence-only; no Schwab wire derivation.',
    ),
    Row(
        file='calibration/backfill_outcomes.py', derivation='resolve_snapshot_for_backfill', disposition='ALLOWLISTED',
        allowlist_id='mega1_sqlite_internal',
        justification='Opens SQLite read on caller-supplied sqlite3 Connection to resolve the source snapshot for an outcomes backfill row. Mega4 internal SQLite read; no Schwab wire derivation.',
    ),
    Row(
        file='calibration/backfill_signal_layer_v1_bundle.py', derivation='backfill', disposition='ALLOWLISTED',
        allowlist_id='mega1_sqlite_internal',
        justification='Signal-layer-v1-bundle backfill orchestrator: opens SQLite on caller-supplied db_path, iterates calibration_decision_log rows lacking the signal_layer_v1 bundle, writes the rebuilt bundle per row. Persistence-only; no Schwab wire derivation.',
    ),
    Row(
        file='calibration/build_trusted_anchor_proof_dataset.py', derivation='_seed_bars_and_snapshots', disposition='ALLOWLISTED',
        allowlist_id='mega1_sqlite_internal',
        justification='Opens SQLite write on caller-supplied db_path; seeds price_bars_1m + snapshots with controlled fixture data for the proof dataset. Mega4 internal SQLite write; no Schwab wire derivation.',
    ),
    Row(
        file='calibration/canonical_1m_grid_scan.py', derivation='scan_db', disposition='ALLOWLISTED',
        allowlist_id='mega1_sqlite_internal',
        justification='Opens SQLite read on caller-supplied db_path; walks price_bars_1m rows to verify canonical 60s UTC grid alignment per ticker. Mega4 internal SQLite read; no Schwab wire derivation.',
    ),
    Row(
        file='calibration/canonical_enforcement.py', derivation='enforce_calibration_decision_log_only_1m', disposition='ALLOWLISTED',
        allowlist_id='mega1_sqlite_internal',
        justification='Opens SQLite on the caller-supplied db_path; enforces the canonical 1m timeframe constraint on calibration_decision_log inserts. Persistence-only; no Schwab wire derivation.',
    ),
    Row(
        file='calibration/canonical_enforcement.py', derivation='enforce_snapshots_fallback_is_1m_only', disposition='ALLOWLISTED',
        allowlist_id='mega1_sqlite_internal',
        justification='Opens SQLite on the caller-supplied db_path; enforces the snapshots fallback path is 1m-only. Persistence-only; no Schwab wire derivation.',
    ),
    Row(
        file='calibration/canonical_enforcement.py', derivation='run_binary_gate', disposition='ALLOWLISTED',
        allowlist_id='mega1_sqlite_internal',
        justification='Opens SQLite on the caller-supplied db_path; runs the binary canonical-enforcement gate (any non-1m row → fail). Persistence-only; no Schwab wire derivation.',
    ),
    Row(
        file='calibration/canonical_enforcement.py', derivation='snapshots_1m_labeled_counts', disposition='ALLOWLISTED',
        allowlist_id='mega1_sqlite_internal',
        justification='Opens SQLite on the caller-supplied db_path; counts 1m-labeled vs other-tf snapshots for enforcement reporting. Mega4 internal SQLite read; no Schwab wire derivation.',
    ),
    Row(
        file='calibration/edge_discovery.py', derivation='_fusion_top_probs', disposition='DERIVED',
        producer_refs=('market_state.py:build_market_state',),
        justification='Probability fusion; consumes model outputs only.',
    ),
    Row(
        file='calibration/edge_discovery.py', derivation='load_labeled_rows', disposition='ALLOWLISTED',
        allowlist_id='mega1_sqlite_internal',
        justification='Opens SQLite read on the caller-supplied db_path; loads calibration_decision_log + label columns into Python dict rows. Mega4 internal SQLite read; no Schwab wire derivation.',
    ),
    Row(
        file='calibration/edge_discovery.py', derivation='run_discovery', disposition='ALLOWLISTED',
        allowlist_id='mega1_sqlite_internal',
        justification='Orchestrator: takes db_path, calls load_labeled_rows for SQLite reads, runs the edge-discovery slice + bootstrap evaluation pipeline. No direct Schwab wire derivation.',
    ),
    Row(
        file='calibration/edge_discovery.py', derivation='run_discovery_rows', disposition='ALLOWLISTED',
        allowlist_id='mega1_sqlite_internal',
        justification='Orchestrator variant: same as run_discovery but works on already-loaded rows; if rows are None it loads via load_labeled_rows (SQLite read). No direct Schwab wire derivation.',
    ),
    Row(
        file='calibration/edge_validation.py', derivation='analyze_edge', disposition='ALLOWLISTED',
        allowlist_id='mega1_sqlite_internal',
        justification='Orchestrator: takes db_path, calls edge_discovery.load_labeled_rows for SQLite reads, runs the edge-validation slice / bootstrap pipeline. No direct Schwab wire derivation.',
    ),
    Row(
        file='calibration/legacy_report.py', derivation='analyze', disposition='ALLOWLISTED',
        allowlist_id='mega1_sqlite_internal',
        justification='Legacy report orchestrator: takes db_path, opens SQLite connection on the calibration DB, reads calibration_decision_log rows, builds the legacy summary report. Mega4 internal SQLite read; no Schwab wire derivation.',
    ),
    Row(
        file='calibration/movement_target_phase5_discrimination_v1.py', derivation='run', disposition='ALLOWLISTED',
        allowlist_id='mega1_sqlite_internal',
        justification='Orchestrator: takes db_path, calls phase6_edge_discovery_governed_v1.load_rows which reads persisted calibration rows from SQLite, then composes movement_target_eval_common metrics + discrimination gates. No direct Schwab wire derivation.',
    ),
    Row(
        file='calibration/movement_target_phase65_isolation_v1.py', derivation='run_phase65_movement', disposition='ALLOWLISTED',
        allowlist_id='mega1_sqlite_internal',
        justification='Orchestrator: takes db_path, calls phase6_edge_discovery_governed_v1.load_rows which reads persisted calibration rows from SQLite, then composes IS/OOS isolation evaluations. No direct Schwab wire derivation.',
    ),
    Row(
        file='calibration/movement_target_phase6_edge_v1.py', derivation='run', disposition='ALLOWLISTED',
        allowlist_id='mega1_sqlite_internal',
        justification='Orchestrator: takes db_path, calls phase6_edge_discovery_governed_v1.load_rows which reads persisted calibration rows from SQLite, then composes horizon-level edge metrics for the movement heads. No direct Schwab wire derivation.',
    ),
    Row(
        file='calibration/phase65_edge_isolation_v1.py', derivation='run_phase65', disposition='ALLOWLISTED',
        allowlist_id='mega1_sqlite_internal',
        justification='Phase 6.5 orchestrator: takes db_path, calls phase6_edge_discovery_governed_v1.load_rows for SQLite reads, walks marginal slices via pure binners, evaluates IS/OOS slices via multiclass_metrics. No direct Schwab wire derivation.',
    ),
    Row(
        file='calibration/phase6_edge_discovery_governed_v1.py', derivation='_load_bar_ends', disposition='ALLOWLISTED',
        allowlist_id='mega1_sqlite_internal',
        justification='Reads via caller-supplied sqlite3.Connection from price_bars_1m table; returns dict of ticker → sorted bar_end ts list for anchor presence checks. Mega4 internal SQLite read; no Schwab wire derivation.',
    ),
    Row(
        file='calibration/phase6_edge_discovery_governed_v1.py', derivation='load_rows', disposition='ALLOWLISTED',
        allowlist_id='mega1_sqlite_internal',
        justification='Opens SQLite on caller-supplied db_path; reads calibration_decision_log rows joined with outcomes for the configured horizon range. Mega4 internal SQLite read; no Schwab wire derivation.',
    ),
    Row(
        file='calibration/phase6_edge_discovery_governed_v1.py', derivation='run_phase6', disposition='ALLOWLISTED',
        allowlist_id='mega1_sqlite_internal',
        justification='Phase 6 orchestrator: takes db_path, calls load_rows for SQLite read, composes horizon_metrics + split_time_quartiles + bootstrap CI. No direct Schwab wire derivation.',
    ),
    Row(
        file='calibration/repair_anchor_coverage_pad_v1.py', derivation='_tickers_needing_pad', disposition='ALLOWLISTED',
        allowlist_id='mega1_sqlite_internal',
        justification='Opens SQLite read on caller-supplied db_path; returns tickers whose anchor-coverage needs padding for the repair pass. Mega4 internal SQLite read; no Schwab wire derivation.',
    ),
    Row(
        file='calibration/repair_anchor_coverage_pad_v1.py', derivation='run', disposition='ALLOWLISTED',
        allowlist_id='mega1_sqlite_internal',
        justification='Anchor-coverage pad repair orchestrator: opens SQLite, iterates _tickers_needing_pad, inserts pad rows into price_bars_1m. Persistence-only; no Schwab wire derivation.',
    ),
    Row(
        file='calibration/repair_canonical_1m_bars_for_outcomes.py', derivation='repair_snapshot_horizon_bars', disposition='ALLOWLISTED',
        allowlist_id='mega1_sqlite_internal',
        justification='Opens SQLite read+write on caller-supplied db_path; repairs missing horizon bars for snapshots that have outcomes but lack the forward bars. Persistence-only; no Schwab wire derivation.',
    ),
    Row(
        file='calibration/repair_canonical_1m_edge_carry_v1.py', derivation='_planned_edge_carries', disposition='ALLOWLISTED',
        allowlist_id='mega1_sqlite_internal',
        justification='Opens SQLite read on caller-supplied db_path; computes the planned edge-carry operations for the repair pass. Mega4 internal SQLite read; no Schwab wire derivation.',
    ),
    Row(
        file='calibration/repair_canonical_1m_edge_carry_v1.py', derivation='run_repair', disposition='ALLOWLISTED',
        allowlist_id='mega1_sqlite_internal',
        justification='Edge-carry repair orchestrator: opens SQLite, iterates _planned_edge_carries, writes carry-forward bars to price_bars_1m. Persistence-only; no Schwab wire derivation.',
    ),
    Row(
        file='calibration/repair_canonical_1m_interior_gaps_v1.py', derivation='_collect_interior_missing', disposition='ALLOWLISTED',
        allowlist_id='mega1_sqlite_internal',
        justification='Opens SQLite read on caller-supplied db_path; collects interior-gap (missing bar) entries per ticker for the repair pass. Mega4 internal SQLite read; no Schwab wire derivation.',
    ),
    Row(
        file='calibration/repair_canonical_1m_interior_gaps_v1.py', derivation='run_repair', disposition='ALLOWLISTED',
        allowlist_id='mega1_sqlite_internal',
        justification='Interior-gap repair orchestrator: opens SQLite, iterates _collect_interior_missing, writes fill rows to price_bars_1m. Persistence-only; no Schwab wire derivation.',
    ),
    Row(
        file='calibration/run_production_accumulation_validation.py', derivation='_duplicate_key_groups', disposition='ALLOWLISTED',
        allowlist_id='mega1_sqlite_internal',
        justification='Opens SQLite read on caller-supplied db_path; returns groups of duplicate (ticker, ts_utc, ml_horizon) keys for the validation pass. Mega4 internal SQLite read; no Schwab wire derivation.',
    ),
    Row(
        file='calibration/run_production_accumulation_validation.py', derivation='_outcome_row_for_index', disposition='ALLOWLISTED',
        allowlist_id='mega1_sqlite_internal',
        justification='Opens SQLite read on caller-supplied db_path; returns the outcome row at a given index for validation comparison. Mega4 internal SQLite read; no Schwab wire derivation.',
    ),
    Row(
        file='calibration/run_production_accumulation_validation.py', derivation='_seed_bars_and_snapshots', disposition='ALLOWLISTED',
        allowlist_id='mega1_sqlite_internal',
        justification='Opens SQLite write on caller-supplied db_path; seeds price_bars_1m + snapshots with controlled fixture data for the validation harness. Mega4 internal SQLite write; no Schwab wire derivation.',
    ),
    Row(
        file='calibration/run_production_accumulation_validation.py', derivation='_stub_models', disposition='ALLOWLISTED',
        allowlist_id='mega1_sqlite_internal',
        justification='Pure helper: returns stub model artifact dicts for the accumulation-validation harness. No DB read here; classified ALLOWLISTED because the parent run() pipeline is the orchestrator that DOES open SQLite; this helper is filesystem fixture only. No market-field derivation.',
    ),
    Row(
        file='calibration/run_production_accumulation_validation.py', derivation='_unsafe_non_exact_joins', disposition='ALLOWLISTED',
        allowlist_id='mega1_sqlite_internal',
        justification='Opens SQLite read on caller-supplied db_path; returns rows whose snapshot/outcome joins are non-exact (would-be-unsafe inserts) for the validation pass. Mega4 internal SQLite read; no Schwab wire derivation.',
    ),
    Row(
        file='calibration/run_production_accumulation_validation.py', derivation='run', disposition='ALLOWLISTED',
        allowlist_id='mega1_sqlite_internal',
        justification='Production accumulation validation orchestrator: takes db_path, seeds fixtures, validates that every snapshot ↔ outcome join is exact and that no duplicate keys exist. Persistence-only; no Schwab wire derivation.',
    ),
    Row(
        file='calibration/schema.py', derivation='_migrate_calibration_decision_log_columns', disposition='ALLOWLISTED',
        allowlist_id='mega1_sqlite_internal',
        justification='DDL migration: takes a sqlite3.Connection, ADD COLUMN on calibration_decision_log for any missing nullable columns under the current schema. Persistence-only; no Schwab wire derivation.',
    ),
    Row(
        file='calibration/schema.py', derivation='_migrate_calibration_pending_index', disposition='ALLOWLISTED',
        allowlist_id='mega1_sqlite_internal',
        justification='DDL migration: takes a sqlite3.Connection, CREATE INDEX IF NOT EXISTS on the pending rows index. Persistence-only; no Schwab wire derivation.',
    ),
    Row(
        file='calibration/schema.py', derivation='_migrate_calibration_unique_ticker_decision_ts', disposition='ALLOWLISTED',
        allowlist_id='mega1_sqlite_internal',
        justification='DDL migration: takes a sqlite3.Connection, alters calibration_decision_log to add the (ticker, decision_ts_utc) unique constraint. Persistence-only; no Schwab wire derivation.',
    ),
    Row(
        file='calibration/signal_engineering.py', derivation='run_engineering', disposition='ALLOWLISTED',
        allowlist_id='mega1_sqlite_internal',
        justification='Orchestrator: takes db_path, calls calibration.edge_discovery.load_labeled_rows(db_path) which reads persisted calibration_decision_log rows from SQLite, then composes pure analysis (directional_diagnostics, failure_identification, filter combinations). No direct Schwab wire derivation.',
    ),
    Row(
        file='calibration/signal_layer_discrimination.py', derivation='run_discrimination', disposition='ALLOWLISTED',
        allowlist_id='mega1_sqlite_internal',
        justification='Discrimination orchestrator: takes db_path, calls edge_discovery.load_labeled_rows for SQLite reads, then composes Pearson / Spearman / MI per feature. No direct Schwab wire derivation.',
    ),
    Row(
        file='calibration/v2_a1_calibration.py', derivation='load_a1_5c_calibration_rows', disposition='ALLOWLISTED',
        allowlist_id='mega1_sqlite_internal',
        justification='Thin wrapper around load_a1_calibration_rows for the 5c horizon. Same SQLite read via the parent. Persistence-only; no Schwab wire derivation.',
    ),
    Row(
        file='calibration/v2_a1_calibration.py', derivation='load_a1_calibration_rows', disposition='ALLOWLISTED',
        allowlist_id='mega1_sqlite_internal',
        justification='Opens SQLite on caller-supplied db_path; reads calibration_decision_log rows matching the target horizon + trusted predicate + canonical_timeframe, returns list of calibration examples. Persistence-only; no Schwab wire derivation.',
    ),
    Row(
        file='calibration/v2_advisory_backfill.py', derivation='_mark_backfill_status', disposition='ALLOWLISTED',
        allowlist_id='mega1_sqlite_internal',
        justification='Per-row backfill status writer on caller-supplied sqlite3.Connection. Persistence-only; no Schwab wire derivation.',
    ),
    Row(
        file='calibration/v2_advisory_backfill.py', derivation='backfill_v2_advisory_decisions', disposition='ALLOWLISTED',
        allowlist_id='mega1_sqlite_internal',
        justification='Backfill orchestrator: takes db_path, opens SQLite read+write connections to iterate calibration_decision_log rows lacking an advisory_v2 snapshot and stamp one from each persisted snapshot row. Persistence-only; no Schwab wire derivation.',
    ),
    Row(
        file='calibration/v2_live_logging.py', derivation='append_live_v2_calibration_decision', disposition='ALLOWLISTED',
        allowlist_id='mega1_sqlite_internal',
        justification='DB writer orchestrator: takes db_path, delegates to calibration.writer.append_calibration_decision which inserts a row into the calibration_decision_log SQLite table. Idempotent upsert; no direct Schwab wire derivation.',
    ),
    Row(
        file='calibration/validate_outcome_join.py', derivation='analyze', disposition='ALLOWLISTED',
        allowlist_id='mega1_sqlite_internal',
        justification='Outcome-join validator: takes db_path, opens SQLite on the calibration DB, reads outcomes + snapshots join + reports gap statistics. Persistence-only; no Schwab wire derivation.',
    ),
    Row(
        file='calibration/writer.py', derivation='append_calibration_decision', disposition='ALLOWLISTED',
        allowlist_id='mega1_sqlite_internal',
        justification='Single canonical inserter for the calibration_decision_log SQLite table; opens connection on caller-supplied db_path, idempotent upsert with retry-on-busy. Persistence-only; no Schwab wire derivation.',
    ),
    Row(
        file='debug_flow_snapshot.py', derivation='_contracts_from_chain_json', disposition='SCHWAB_LEAF',
        schwab_leaf='chains.callExpDateMap.*.openInterest',
        justification='Parses option chain JSON for debug snapshot.',
    ),
    Row(
        file='features/canonical_contract.py', derivation='get_feature_spec', disposition='DERIVED',
        producer_refs=('market_state.py:build_market_state',),
        justification='Composes Mega1 producers for get_feature_spec output fields.',
    ),
    Row(
        file='features/canonical_contract.py', derivation='get_mvp_feature_names', disposition='DERIVED',
        producer_refs=('market_state.py:build_market_state',),
        justification='Composes Mega1 producers for get_mvp_feature_names output fields.',
    ),
    Row(
        file='features/canonical_contract.py', derivation='get_mvp_field_semantics', disposition='DERIVED',
        producer_refs=('market_state.py:build_market_state',),
        justification='Composes Mega1 producers for get_mvp_field_semantics output fields.',
    ),
    Row(
        file='features/cascade_stack_contract.py', derivation='assert_no_legacy_mvp_in_fusion_overlay', disposition='DERIVED',
        producer_refs=('market_state.py:build_market_state',),
        justification='Composes Mega1 producers for assert_no_legacy_mvp_in_fusion_overlay output fields.',
    ),
    Row(
        file='features/db_feature_adapter.py', derivation='build_db_mvp_feature_row', disposition='DERIVED',
        producer_refs=('features/inference_snapshot.py:build_inference_snapshot_v1',),
        justification='Reads persisted snapshot SQLite rows, not Schwab wire JSON (build_db_mvp_feature_row).',
    ),
    Row(
        file='features/fusion_model_input.py', derivation='assert_fusion_overlay_has_no_mvp_keys', disposition='DERIVED',
        producer_refs=('market_state.py:build_market_state',),
        justification='Composes Mega1 producers for assert_fusion_overlay_has_no_mvp_keys output fields.',
    ),
    Row(
        file='features/fusion_model_input.py', derivation='similar_setup_filters_from_canonical_features', disposition='DERIVED',
        producer_refs=('market_state.py:build_market_state',),
        justification='Composes Mega1 producers for similar_setup_filters_from_canonical_features output fields.',
    ),
    Row(
        file='features/fusion_model_input.py', derivation='similar_setup_filters_from_db_snapshot_row', disposition='DERIVED',
        producer_refs=('features/db_feature_adapter.py:build_db_mvp_feature_row', 'features/fusion_model_input.py:similar_setup_filters_from_canonical_features'),
        justification='Composes Mega1 producers for similar_setup_filters_from_db_snapshot_row output fields.',
    ),
    Row(
        file='features/fusion_model_input.py', derivation='strip_mvp_keys_from_fusion_overlay', disposition='DERIVED',
        producer_refs=('market_state.py:build_market_state',),
        justification='Composes Mega1 producers for strip_mvp_keys_from_fusion_overlay output fields.',
    ),
    Row(
        file='features/fusion_policy_contract.py', derivation='fusion_payload_to_policy_columns', disposition='ALLOWLISTED',
        allowlist_id='mega1_sqlite_internal',
        justification='Reads persisted snapshot SQLite rows, not Schwab wire JSON (fusion_payload_to_policy_columns).',
    ),
    Row(
        file='features/fusion_policy_contract.py', derivation='fusion_policy_columns_horizon_failed', disposition='ALLOWLISTED',
        allowlist_id='mega1_sqlite_internal',
        justification='Internal helper returning the canonical-failed column tuple for a horizon; not Schwab wire derivation (fusion_policy_columns_horizon_failed).',
    ),
    Row(
        file='features/inference_snapshot.py', derivation='_feature_quality_from_row', disposition='DERIVED',
        producer_refs=('market_state.py:build_market_state',),
        justification='Composes Mega1 producers for _feature_quality_from_row output fields.',
    ),
    Row(
        file='features/inference_snapshot.py', derivation='_quote_field_lineage', disposition='DERIVED',
        producer_refs=('server.py:_fetch_state',),
        justification='Classifies existing quote_source_detail keys; no wire read or value mutation.',
    ),
    Row(
        file='features/inference_snapshot.py', derivation='build_feature_lineage_map', disposition='ALLOWLISTED',
        allowlist_id='mega1_sqlite_internal',
        justification='Reads persisted snapshot SQLite rows, not Schwab wire JSON (build_feature_lineage_map).',
    ),
    Row(
        file='features/inference_snapshot.py', derivation='build_inference_snapshot_v1', disposition='DERIVED',
        producer_refs=('market_state.py:build_market_state',),
        justification='Canonical inference row from upstream market state.',
    ),
    Row(
        file='features/inference_snapshot.py', derivation='build_inference_snapshot_v1_from_db_row', disposition='ALLOWLISTED',
        allowlist_id='mega1_sqlite_internal',
        justification='Reads persisted snapshot SQLite rows, not Schwab wire JSON (build_inference_snapshot_v1_from_db_row).',
    ),
    Row(
        file='features/inference_snapshot.py', derivation='build_inference_snapshot_v1_from_signal_input', disposition='ALLOWLISTED',
        allowlist_id='mega1_sqlite_internal',
        justification='Reads persisted snapshot SQLite rows, not Schwab wire JSON (build_inference_snapshot_v1_from_signal_input).',
    ),
    Row(
        file='features/inference_snapshot.py', derivation='build_inference_snapshot_v1_from_signal_input._dist_to_vwap_pts', disposition='DERIVED',
        producer_refs=('features/inference_snapshot.py:build_inference_snapshot_v1_from_signal_input',),
        justification='Composes Mega1 producers for _dist_to_vwap_pts output fields.',
    ),
    Row(
        file='features/inference_snapshot.py', derivation='build_operator_field_lineage', disposition='DERIVED',
        producer_refs=('server.py:_fetch_state', 'market_state.py:build_market_state'),
        justification='Classifies existing Tier-C md keys into field_lineage map; no wire read or value mutation.',
    ),
    Row(
        file='features/live_feature_adapter.py', derivation='build_live_mvp_feature_row', disposition='DERIVED',
        producer_refs=('market_state.py:build_market_state',),
        justification='Reads persisted snapshot SQLite rows, not Schwab wire JSON (build_live_mvp_feature_row).',
    ),
    Row(
        file='features/lstm_sequence_input.py', derivation='_canonical_missing_masks', disposition='DERIVED',
        producer_refs=('market_state.py:build_market_state',),
        justification='Composes Mega1 producers for _canonical_missing_masks output fields.',
    ),
    Row(
        file='features/lstm_sequence_input.py', derivation='_patch_lstm_categoricals', disposition='DERIVED',
        producer_refs=('market_state.py:build_market_state',),
        justification='Composes Mega1 producers for _patch_lstm_categoricals output fields.',
    ),
    Row(
        file='features/lstm_sequence_input.py', derivation='build_transformer_merged_window', disposition='ALLOWLISTED',
        allowlist_id='mega1_sqlite_internal',
        justification='Reads persisted snapshot SQLite rows, not Schwab wire JSON (build_transformer_merged_window).',
    ),
    Row(
        file='features/lstm_sequence_input.py', derivation='encode_lstm_structure_bar_with_masks', disposition='DERIVED',
        producer_refs=('features/lstm_sequence_input.py:_patch_lstm_categoricals', 'features/lstm_sequence_input.py:_canonical_missing_masks'),
        justification='Composes Mega1 producers for encode_lstm_structure_bar_with_masks output fields.',
    ),
    Row(
        file='features/lstm_sequence_input.py', derivation='merge_db_row_with_canonical_mvp', disposition='DERIVED',
        producer_refs=('market_state.py:build_market_state',),
        justification='Composes Mega1 producers for merge_db_row_with_canonical_mvp output fields.',
    ),
    Row(
        file='features/monte_carlo_stack_input.py', derivation='resolve_monte_carlo_stack_inputs', disposition='DERIVED',
        producer_refs=('market_state.py:build_market_state',),
        justification='Composes Mega1 producers for resolve_monte_carlo_stack_inputs output fields.',
    ),
    Row(
        file='features/mvp_source_coercion.py', derivation='_require_mapping', disposition='ALLOWLISTED',
        allowlist_id='mega1_sqlite_internal',
        justification='Internal type-guard helper for source-mapping inputs; not Schwab wire derivation (_require_mapping).',
    ),
    Row(
        file='features/mvp_source_coercion.py', derivation='read_liquidity_summary_subdict', disposition='DERIVED',
        producer_refs=('market_state.py:build_market_state',),
        justification='Composes Mega1 producers for read_liquidity_summary_subdict output fields.',
    ),
    Row(
        file='features/mvp_source_coercion.py', derivation='read_optional_float', disposition='DERIVED',
        producer_refs=('features/mvp_source_coercion.py:strict_float_from_raw', 'market_state.py:build_market_state'),
        justification='Composes Mega1 producers for read_optional_float output fields.',
    ),
    Row(
        file='features/mvp_source_coercion.py', derivation='strict_float_from_raw', disposition='DERIVED',
        producer_refs=('market_state.py:build_market_state',),
        justification='Fail-closed numeric coercion; no silent default to 0.',
    ),
    Row(
        file='features/regime_mvp_context.py', derivation='mvp_nearest_distances_for_regime', disposition='DERIVED',
        producer_refs=('market_state.py:build_market_state',),
        justification='Composes Mega1 producers for mvp_nearest_distances_for_regime output fields.',
    ),
    Row(
        file='features/regime_mvp_context.py', derivation='mvp_net_gamma', disposition='DERIVED',
        producer_refs=('market_state.py:build_market_state',),
        justification='Composes Mega1 producers for mvp_net_gamma output fields.',
    ),
    Row(
        file='features/regime_mvp_context.py', derivation='mvp_spot', disposition='DERIVED',
        producer_refs=('market_state.py:build_market_state',),
        justification='Composes Mega1 producers for mvp_spot output fields.',
    ),
    Row(
        file='features/regime_mvp_context.py', derivation='mvp_vwap_side', disposition='DERIVED',
        producer_refs=('market_state.py:build_market_state',),
        justification='Composes Mega1 producers for mvp_vwap_side output fields.',
    ),
    Row(
        file='features/regime_mvp_context.py', derivation='require_mvp_features', disposition='DERIVED',
        producer_refs=('market_state.py:build_market_state',),
        justification='Composes Mega1 producers for require_mvp_features output fields.',
    ),
    Row(
        file='features/replay_signal_input_v1.py', derivation='_positive_float_required', disposition='DERIVED',
        producer_refs=('market_state.py:build_market_state',),
        justification='Composes Mega1 producers for _positive_float_required output fields.',
    ),
    Row(
        file='features/replay_signal_input_v1.py', derivation='_replay_vol_decimal', disposition='DERIVED',
        producer_refs=('market_state.py:build_market_state',),
        justification='VOL_INPUT_CONTRACT 1.0.0 replay unit boundary (VOL-UNIT-001): persisted percent-form iv_level/realized_vol (stamped by the canonical builder) -> canonical decimal via the same vol_percent_to_decimal as the live stamp (idempotent for already-decimal, so no double conversion); missing/invalid/nonfinite -> None (fail-closed, never directional evidence). Locked by tests/test_replay_signal_input_v1.py GR-1/GR-2/GR-3.',
    ),
    Row(
        file='features/replay_signal_input_v1.py', derivation='signal_input_from_snapshot_row_dict', disposition='DERIVED',
        producer_refs=('features/replay_signal_input_v1.py:_positive_float_required',),
        justification='Composes Mega1 producers for signal_input_from_snapshot_row_dict output fields.',
    ),
    Row(
        file='features/semantic_parity.py', derivation='assert_live_db_canonicalization_equivalent', disposition='DERIVED',
        producer_refs=('features/live_feature_adapter.py:build_live_mvp_feature_row', 'features/db_feature_adapter.py:build_db_mvp_feature_row'),
        justification='Composes Mega1 producers for assert_live_db_canonicalization_equivalent output fields.',
    ),
    Row(
        file='features/shared_sequence_context.py', derivation='_max_transformer_seq_len_for_ticker', disposition='DERIVED',
        producer_refs=('market_state.py:build_market_state',),
        justification='Composes Mega1 producers for _max_transformer_seq_len_for_ticker output fields.',
    ),
    Row(
        file='features/shared_sequence_context.py', derivation='build_shared_sequence_context', disposition='ALLOWLISTED',
        allowlist_id='mega1_sqlite_internal',
        justification='Reads persisted snapshot SQLite rows, not Schwab wire JSON (build_shared_sequence_context).',
    ),
    Row(
        file='features/shared_sequence_context.py', derivation='transformer_window_chronological', disposition='DERIVED',
        producer_refs=('market_state.py:build_market_state',),
        justification='Composes Mega1 producers for transformer_window_chronological output fields.',
    ),
    Row(
        file='features/signal_layer_v1.py', derivation='_aggregate_bars', disposition='DERIVED',
        producer_refs=('market_state.py:build_market_state',),
        justification='Composes Mega1 producers for _aggregate_bars output fields.',
    ),
    Row(
        file='features/signal_layer_v1.py', derivation='_fractal_swings', disposition='DERIVED',
        producer_refs=('market_state.py:build_market_state',),
        justification='Composes Mega1 producers for _fractal_swings output fields.',
    ),
    Row(
        file='features/signal_layer_v1.py', derivation='_safe_div', disposition='DERIVED',
        producer_refs=('market_state.py:build_market_state',),
        justification='Composes Mega1 producers for _safe_div output fields.',
    ),
    Row(
        file='features/signal_layer_v1.py', derivation='_volume_profile_proxy', disposition='DERIVED',
        producer_refs=('market_state.py:build_market_state',),
        justification='Composes Mega1 producers for _volume_profile_proxy output fields.',
    ),
    Row(
        file='features/signal_layer_v1.py', derivation='compute_signal_layer_v1', disposition='DERIVED',
        producer_refs=('market_state.py:build_market_state', 'features/signal_layer_v1.py:_fractal_swings', 'features/signal_layer_v1.py:_volume_profile_proxy', 'features/signal_layer_v1.py:_aggregate_bars', 'features/signal_layer_v1.py:_safe_div'),
        justification='Composes Mega1 producers for compute_signal_layer_v1 output fields.',
    ),
    Row(
        file='features/signal_layer_v1.py', derivation='flatten_numeric_features', disposition='DERIVED',
        producer_refs=('market_state.py:build_market_state',),
        justification='Composes Mega1 producers for flatten_numeric_features output fields.',
    ),
    Row(
        file='features/signal_layer_v1.py', derivation='layer_direction_policy', disposition='DERIVED',
        producer_refs=('market_state.py:build_market_state',),
        justification='Composes Mega1 producers for layer_direction_policy output fields.',
    ),
    Row(
        file='features/signal_layer_v1.py', derivation='load_bars_before_decision', disposition='ALLOWLISTED',
        allowlist_id='mega1_sqlite_internal',
        justification='Reads persisted snapshot SQLite rows, not Schwab wire JSON (load_bars_before_decision).',
    ),
    Row(
        file='features/signal_layer_v1.py', derivation='meta_n_bars_int', disposition='ALLOWLISTED',
        allowlist_id='mega1_sqlite_internal',
        justification='Internal meta-bar count coercion helper; not Schwab wire derivation (meta_n_bars_int).',
    ),
    Row(
        file='features/signal_layer_v1.py', derivation='signal_layer_v1_to_direction_probs', disposition='DERIVED',
        producer_refs=('features/signal_layer_v1.py:flatten_numeric_features',),
        justification='Composes Mega1 producers for signal_layer_v1_to_direction_probs output fields.',
    ),
    Row(
        file='features/training_canonical_input.py', derivation='assert_shared_feature_cache_keys_equal', disposition='DERIVED',
        producer_refs=('market_state.py:build_market_state',),
        justification='Composes Mega1 producers for assert_shared_feature_cache_keys_equal output fields.',
    ),
    Row(
        file='features/xgb_model_input.py', derivation='assert_not_raw_l1_payload', disposition='DERIVED',
        producer_refs=('market_state.py:build_market_state',),
        justification='Composes Mega1 producers for assert_not_raw_l1_payload output fields.',
    ),
    Row(
        file='features/xgb_model_input.py', derivation='merge_xgb_fusion_overlay', disposition='DERIVED',
        producer_refs=('market_state.py:build_market_state',),
        justification='Composes Mega1 producers for merge_xgb_fusion_overlay output fields.',
    ),
    Row(
        file='governed_stack_contract.py', derivation='classify_stack_health', disposition='ALLOWLISTED',
        allowlist_id='mega4_governed_stack_contract',
        justification='Governed stack contract validation.',
    ),
    Row(
        file='governed_stack_contract.py', derivation='horizon_slug_to_mc_bars', disposition='ALLOWLISTED',
        allowlist_id='mega4_governed_stack_contract',
        justification='Governed stack contract validation.',
    ),
    Row(
        file='governed_stack_contract.py', derivation='mc_model_direction_inputs', disposition='ALLOWLISTED',
        allowlist_id='mega4_governed_stack_contract',
        justification='Governed stack contract validation.',
    ),
    Row(
        file='levels.py', derivation='key_levels_to_plot_rows', disposition='ALLOWLISTED',
        allowlist_id='mega2_internal_helper',
        justification='Plot row formatter; no derivation.',
    ),
    Row(
        file='levels.py', derivation='to_display_rows', disposition='ALLOWLISTED',
        allowlist_id='mega2_display_formatter',
        justification='ALLOWLISTED for to_display_rows: Display mapping only.',
    ),
    Row(
        file='levels.py', derivation='totals_to_df_rows', disposition='ALLOWLISTED',
        allowlist_id='mega2_display_formatter',
        justification='Totals display mapping.',
    ),
    Row(
        file='levels.py', derivation='walls_to_df_rows', disposition='ALLOWLISTED',
        allowlist_id='mega2_display_formatter',
        justification='Walls display mapping.',
    ),
    Row(
        file='live_decision_bundle.py', derivation='_key_levels_from_ms_dict', disposition='DERIVED',
        producer_refs=('market_state.py:build_market_state', 'server.py:_fetch_state'),
        justification='Extracts level tuples from cached state.',
    ),
    Row(
        file='live_decision_bundle.py', derivation='_live_session_label', disposition='DERIVED',
        producer_refs=('server.py:_fetch_state',),
        justification='Session label via market_context.',
    ),
    Row(
        file='live_decision_bundle.py', derivation='_session_bucket_et', disposition='ALLOWLISTED',
        allowlist_id='mega1_sqlite_internal',
        justification='Reads persisted snapshot SQLite rows, not Schwab wire JSON (_session_bucket_et).',
    ),
    Row(
        file='live_decision_bundle.py', derivation='recompute_nearest_struct_at_spot', disposition='DERIVED',
        producer_refs=('live_decision_bundle.py:_key_levels_from_ms_dict',),
        justification='Nearest wall recompute at stream spot.',
    ),
    Row(
        file='live_decision_bundle.py', derivation='tick_triggers_coherent_refresh', disposition='DERIVED',
        producer_refs=('server.py:_fetch_state', 'live_decision_bundle.py:_live_session_label', 'live_decision_bundle.py:recompute_nearest_struct_at_spot'),
        justification='Coherence triggers vs stream spot and cached bundle.',
    ),
    Row(
        file='live_market_plane.py', derivation='_plane_tuple_sig', disposition='DERIVED',
        producer_refs=('server.py:_fetch_state',),
        justification='Dedup signature for plane tuple.',
    ),
    Row(
        file='live_market_plane.py', derivation='apply_l1_live_quote_overlay', disposition='DERIVED',
        producer_refs=('live_market_plane.py:get_quote',),
        justification='Delegates to Schwab transport producers for apply_l1_live_quote_overlay.',
    ),
    Row(
        file='live_market_plane.py', derivation='get_quote', disposition='DERIVED',
        producer_refs=('schwab_client.py:safe_get_quote',),
        justification='Delegates to Schwab transport producers for get_quote.',
    ),
    Row(
        file='live_market_plane.py', derivation='merge_into_state', disposition='DERIVED',
        producer_refs=('server.py:_fetch_state', 'live_market_plane.py:get_quote'),
        justification='Delegates to Schwab transport producers for merge_into_state.',
    ),
    Row(
        file='live_market_plane.py', derivation='record_from_level_one_equity', disposition='DERIVED',
        producer_refs=('server.py:_fetch_state', 'live_market_plane.py:_plane_tuple_sig'),
        justification='Delegates to Schwab transport producers for record_from_level_one_equity.',
    ),
    Row(
        file='live_market_plane.py', derivation='record_quote', disposition='SCHWAB_LEAF',
        schwab_leaf='quotes.quote.lastPrice',
        justification='Records REST-shaped quote into plane cache.',
    ),
    Row(
        file='live_market_plane.py', derivation='reset_sse_push_cursor', disposition='ALLOWLISTED',
        allowlist_id='mega1_sqlite_internal',
        justification='Reads persisted snapshot SQLite rows, not Schwab wire JSON (reset_sse_push_cursor).',
    ),
    Row(
        file='live_market_plane.py', derivation='take_fresh_sse_quote_payload', disposition='DERIVED',
        producer_refs=('server.py:_fetch_state',),
        justification='Delegates to Schwab transport producers for take_fresh_sse_quote_payload.',
    ),
    Row(
        file='live_vs_replay_validation.py', derivation='_live_expiry_from_proof', disposition='ALLOWLISTED',
        allowlist_id='mega1_sqlite_internal',
        justification='Reads persisted snapshot SQLite rows, not Schwab wire JSON (_live_expiry_from_proof).',
    ),
    Row(
        file='live_vs_replay_validation.py', derivation='_live_from_row', disposition='ALLOWLISTED',
        allowlist_id='mega1_sqlite_internal',
        justification='Reads persisted snapshot SQLite rows, not Schwab wire JSON (_live_from_row).',
    ),
    Row(
        file='live_vs_replay_validation.py', derivation='_replay_one_row', disposition='ALLOWLISTED',
        allowlist_id='mega1_sqlite_internal',
        justification='Reads persisted snapshot SQLite rows, not Schwab wire JSON (_replay_one_row).',
    ),
    Row(
        file='live_vs_replay_validation.py', derivation='run_live_vs_replay_validation', disposition='ALLOWLISTED',
        allowlist_id='mega1_sqlite_internal',
        justification='Reads persisted snapshot SQLite rows, not Schwab wire JSON (run_live_vs_replay_validation).',
    ),
    Row(
        file='lstm_data.py', derivation='_connect', disposition='ALLOWLISTED',
        allowlist_id='mega1_sqlite_internal',
        justification='Opens sqlite3 read connection on caller-supplied db_path; configures row_factory + calibration schema. Mega4 internal SQLite connection factory; no Schwab wire derivation.',
    ),
    Row(
        file='lstm_data.py', derivation='build_lstm_dataset', disposition='ALLOWLISTED',
        allowlist_id='mega1_sqlite_internal',
        justification='Dataset orchestrator: takes db_path, calls extract_rth_snapshots for SQLite read, encodes each snapshot via the pure encoders, returns LSTMDataset. No direct Schwab wire derivation.',
    ),
    Row(
        file='lstm_data.py', derivation='extract_rth_snapshots', disposition='ALLOWLISTED',
        allowlist_id='mega1_sqlite_internal',
        justification='Opens SQLite on caller-supplied db_path; reads snapshots table filtered to RTH + ticker + timeframe, returns list of row dicts. Mega4 internal SQLite read; no Schwab wire derivation here (the persisted rows trace to Mega1 producers).',
    ),
    Row(
        file='lstm_model.py', derivation='_lstm_xgb_probs_fp', disposition='DERIVED',
        producer_refs=('market_state.py:build_market_state',),
        justification='Inference on canonical features; no Schwab wire ingest.',
    ),
    Row(
        file='market_context.py', derivation='_build_confluence', disposition='DERIVED',
        producer_refs=('market_context.py:fetch_market_context',),
        justification='Cap-weighted confluence from quote-derived chg_pct inputs.',
    ),
    Row(
        file='market_context.py', derivation='_build_iwm_confluence', disposition='DERIVED',
        producer_refs=('market_context.py:fetch_market_context',),
        justification='IWM sector confluence composite.',
    ),
    Row(
        file='market_context.py', derivation='_derive_session', disposition='ALLOWLISTED',
        allowlist_id='mega1_session_calendar',
        justification='ET session label; no Schwab session_label leaf.',
    ),
    Row(
        file='market_context.py', derivation='_extract_quote', disposition='SCHWAB_LEAF',
        schwab_leaf='quotes.quote.lastPrice',
        justification='Schwab quote hierarchy via _last_traded_price; pct from netChange when percent leaf absent.',
    ),
    Row(
        file='market_context.py', derivation='_last_traded_price', disposition='SCHWAB_LEAF',
        schwab_leaf='quotes.quote.lastPrice',
        justification='Trade-only last ladder (quote/extended lastPrice); regularMarketLastPrice close only as last resort (RC-16/RC-18).',
    ),
    Row(
        file='market_context.py', derivation='_vix_regime', disposition='DERIVED',
        producer_refs=('market_context.py:fetch_market_context',),
        justification='Composes Mega1 producers for _vix_regime output fields.',
    ),
    Row(
        file='market_context.py', derivation='_volume_profile_poc_vah_val', disposition='DERIVED',
        producer_refs=('market_state.py:build_market_state',),
        justification='Volume profile POC/VAH/VAL; no Schwab profile leaves.',
    ),
    Row(
        file='market_context.py', derivation='configured_index_futures_symbols', disposition='ALLOWLISTED',
        allowlist_id='mega1_env_config',
        justification='Composes Mega1 producers for configured_index_futures_symbols output fields.',
    ),
    Row(
        file='market_context.py', derivation='fetch_market_context', disposition='SCHWAB_LEAF',
        schwab_leaf='quotes.quote.lastPrice',
        justification='Multi-symbol quote fetch via safe_get_quote wrapper.',
    ),
    Row(
        file='market_context.py', derivation='fetch_market_context._chg_for', disposition='SCHWAB_LEAF',
        schwab_leaf='quotes.quote.netPercentChange',
        justification='Nested pct change helper from quote JSON.',
    ),
    Row(
        file='market_context.py', derivation='fetch_market_context._fetch', disposition='SCHWAB_LEAF',
        schwab_leaf='quotes.quote.lastPrice',
        justification='Nested per-symbol quote fetch inside fetch_market_context.',
    ),
    Row(
        file='market_context.py', derivation='fetch_price_levels', disposition='REPLACED',
        schwab_leaf='pricehistory.candles.*.datetime',
        justification='Skip candles missing datetime leaf (fail-closed; no .get(datetime,0)).',
    ),
    Row(
        file='market_context.py', derivation='iwm_blended_participation_push', disposition='DERIVED',
        producer_refs=('market_context.py:fetch_market_context',),
        justification='Composes Mega1 producers for iwm_blended_participation_push output fields.',
    ),
    Row(
        file='market_context.py', derivation='market_context_panel_symbols_excluding_core', disposition='SCHWAB_LEAF',
        schwab_leaf='quotes.quote.lastPrice',
        justification='Schwab API or wire JSON ingest path.',
    ),
    Row(
        file='market_context.py', derivation='proximity_alerts', disposition='DERIVED',
        producer_refs=('market_context.py:proximity_alerts._check',),
        justification='Distance alerts vs key levels; inputs from upstream math.',
    ),
    Row(
        file='market_context.py', derivation='proximity_alerts._check', disposition='ALLOWLISTED',
        allowlist_id='mega1_internal_helper',
        justification='Nested distance check helper.',
    ),
    Row(
        file='market_data_adapter.py', derivation='NormalizedBar.to_dict', disposition='SCHWAB_LEAF',
        schwab_leaf='pricehistory.candles.*.datetime',
        justification='Serializes NormalizedBar; fields already Schwab-mapped.',
    ),
    Row(
        file='market_data_adapter.py', derivation='normalize_bar', disposition='REPLACED',
        schwab_leaf='pricehistory.candles.*.datetime',
        justification='Fail-closed Schwab leaf read: pricehistory.candles.*.datetime.',
    ),
    Row(
        file='market_data_adapter.py', derivation='normalize_bar._f', disposition='ALLOWLISTED',
        allowlist_id='mega1_internal_helper',
        justification='Nested float parse inside normalize_bar; covered by parent REPLACED.',
    ),
    Row(
        file='market_data_adapter.py', derivation='normalize_bar._volume', disposition='ALLOWLISTED',
        allowlist_id='mega1_internal_helper',
        justification='Nested volume parse inside normalize_bar; covered by parent REPLACED.',
    ),
    Row(
        file='market_data_adapter.py', derivation='normalize_bars', disposition='SCHWAB_LEAF',
        schwab_leaf='pricehistory.candles.*.datetime',
        justification='Batch normalize_bar.',
    ),
    Row(
        file='market_data_adapter.py', derivation='schwab_candles_to_bars', disposition='SCHWAB_LEAF',
        schwab_leaf='pricehistory.candles.*.datetime',
        justification='Schwab JSON candles → normalized bars + _ts.',
    ),
    Row(
        file='market_state.py', derivation='_build_contract_context_ms', disposition='DERIVED',
        producer_refs=('market_state.py:_schwab_days_to_expiration_for_contract', 'market_state.py:_oe_bid_ask_mid'),
        justification='Composes Mega1 producers for _build_contract_context_ms output fields.',
    ),
    Row(
        file='market_state.py', derivation='_oe_bid_ask_mid', disposition='DERIVED',
        producer_refs=('market_state.py:build_market_state',),
        justification='OP-006 mark-first mid ladder; bid/ask/2 only when mark+last absent.',
    ),
    Row(
        file='market_state.py', derivation='_oe_chain_row_snapshot', disposition='SCHWAB_LEAF',
        schwab_leaf='chains.callExpDateMap.*.openInterest',
        justification='Snapshots Schwab chain contract row fields.',
    ),
    Row(
        file='market_state.py', derivation='_oe_composite_strike_row', disposition='SCHWAB_LEAF',
        schwab_leaf='chains.callExpDateMap.*.openInterest',
        justification='Aggregates call/put rows at strike from chain JSON.',
    ),
    Row(
        file='market_state.py', derivation='_oe_first_contract_row', disposition='DERIVED',
        producer_refs=('market_state.py:build_market_state',),
        justification='Composes Mega1 producers for _oe_first_contract_row output fields.',
    ),
    Row(
        file='market_state.py', derivation='_schwab_days_to_expiration_for_contract', disposition='SCHWAB_LEAF',
        schwab_leaf='chains.*.daysToExpiration',
        justification='Reads Schwab DTE leaf when present.',
    ),
    Row(
        file='market_state.py', derivation='build_market_state', disposition='DERIVED',
        producer_refs=('server.py:_build_rest_fast_quote_payload', 'server.py:_fetch_state', 'market_context.py:fetch_price_levels'),
        justification='Delegates to Schwab transport producers for build_market_state.',
    ),
    Row(
        file='market_state.py', derivation='derive_zone', disposition='DERIVED',
        producer_refs=('market_state.py:build_market_state',),
        justification='Regime taxonomy from bias_signal + net_delta.',
    ),
    Row(
        file='market_state.py', derivation='nd_color', disposition='DERIVED',
        producer_refs=('market_state.py:build_market_state',),
        justification='Composes Mega1 producers for nd_color output fields.',
    ),
    Row(
        file='market_state.py', derivation='recommend_option_expression', disposition='DERIVED',
        producer_refs=('market_state.py:_oe_composite_strike_row', 'market_state.py:_oe_chain_row_snapshot', 'market_state.py:_oe_first_contract_row', 'market_state.py:build_market_state'),
        justification='OE recommendation from chain fields.',
    ),
    Row(
        file='math_exposure_core.py', derivation='_nearest_strike', disposition='SCHWAB_LEAF',
        schwab_leaf='chains.*.strikePrice',
        justification='ATM strike selection.',
    ),
    Row(
        file='math_exposure_core.py', derivation='_pick_strike_max_metric', disposition='DERIVED',
        producer_refs=('server.py:_fetch_state', 'market_state.py:build_market_state'),
        justification='Max-metric strike picker.',
    ),
    Row(
        file='math_exposure_core.py', derivation='_strike_bucket', disposition='SCHWAB_LEAF',
        schwab_leaf='chains.callExpDateMap.*.openInterest',
        justification='Strike dict lookup.',
    ),
    Row(
        file='math_exposure_core.py', derivation='_window_strikes', disposition='SCHWAB_LEAF',
        schwab_leaf='chains.*.strikePrice',
        justification='Strike window filter.',
    ),
    Row(
        file='math_exposure_core.py', derivation='aggregate_net_dex', disposition='DERIVED',
        producer_refs=('math_exposure_core.py:exposures_have_dollar_gex', 'math_exposure_core.py:bucket_metric'),
        justification='Sum net_dex over strikes.',
    ),
    Row(
        file='math_exposure_core.py', derivation='aggregate_net_gex', disposition='DERIVED',
        producer_refs=('math_exposure_core.py:exposures_have_dollar_gex', 'math_exposure_core.py:net_gamma_raw_at_strike', 'math_exposure_core.py:net_gex_dollars_at_strike'),
        justification='Sum net_gex_1pct over strikes.',
    ),
    Row(
        file='math_exposure_core.py', derivation='bucket_metric', disposition='DERIVED',
        producer_refs=('server.py:_fetch_state',),
        justification='Fail-closed; no .get(k,0).',
    ),
    Row(
        file='math_exposure_core.py', derivation='bucket_metric_abs', disposition='DERIVED',
        producer_refs=('math_exposure_core.py:bucket_metric',),
        justification='Abs of bucket_metric.',
    ),
    Row(
        file='math_exposure_core.py', derivation='compute_beta', disposition='DERIVED',
        producer_refs=('server.py:_fetch_state', 'market_state.py:build_market_state'),
        justification='Beta from return series; inputs from Schwab candles.',
    ),
    Row(
        file='math_exposure_core.py', derivation='compute_beta_residual', disposition='DERIVED',
        producer_refs=('server.py:_fetch_state', 'market_state.py:build_market_state'),
        justification='Residual vs SPY; quote-derived inputs.',
    ),
    Row(
        file='math_exposure_core.py', derivation='compute_delta_oi_walls', disposition='DERIVED',
        producer_refs=('terrain_engine.py:compute_terrain',),
        justification="RC-359: diffs today's {strike: (call_oi, put_oi)} map — taken from the terrain snapshot's oi_by_strike, i.e. the same exposures book — against the prior session banked by server.py, then picks the largest call build, largest put build and deepest combined unwind. It reads no vendor leaf; the OI values reach it already parsed. Fail-closed: None when no prior session is banked, so the diff is withheld rather than invented.",
    ),
    Row(
        file='math_exposure_core.py', derivation='compute_exposures_by_strike', disposition='DERIVED',
        producer_refs=('server.py:_fetch_state',),
        justification='Core Schwab chain aggregation; skip -999 greeks.',
    ),
    Row(
        file='math_exposure_core.py', derivation='compute_net_charm', disposition='DERIVED',
        producer_refs=('server.py:_fetch_state',),
        justification='Net charm from chain; Schwab charm leaf when present.',
    ),
    Row(
        file='math_exposure_core.py', derivation='compute_net_charm._tte_memo', disposition='DERIVED',
        producer_refs=('math_exposure_core.py:compute_net_charm',),
        justification='Nested: memoises time_et.time_to_expiry_years per distinct expiry against a `now` pinned once for the aggregate (RC-245). Not an optimisation only — with now=None each per-contract call re-read the clock, so T drifted across the loop and one reported figure described several moments.',
    ),
    Row(
        file='math_exposure_core.py', derivation='compute_net_dex_dollars', disposition='DERIVED',
        producer_refs=('math_exposure_core.py:compute_exposures_by_strike',),
        justification="RC-361: sums call_dex_dollars MINUS put_dex_dollars over the same exposures book, giving the dealer's net delta notional (put deltas already arrive negative, so subtracting the put leg lands on the dealer's side). Consumes only fields the book produced; fail-closed to None on an empty/degenerate book rather than a fabricated $0.",
    ),
    Row(
        file='math_exposure_core.py', derivation='compute_net_vanna', disposition='DERIVED',
        producer_refs=('math_exposure_core.py:compute_exposures_by_strike', 'terrain_engine.py:compute_terrain'),
        justification='RC-362: sums call_vanna MINUS put_vanna over the ONE exposures book compute_exposures_by_strike already built (per-strike vanna is the vega/(S*IV) proxy accumulated with OI and multiplier at parse time), divides by 100 for per-vol-point and multiplies by spot for dollars. Reads no vendor field itself; the dealer sign model is inherited from the book, not re-encoded. Fail-closed: None on an empty/valueless book or missing spot, never a fabricated zero.',
    ),
    Row(
        file='math_exposure_core.py', derivation='compute_zero_dte_gamma_share', disposition='DERIVED',
        producer_refs=('math_exposure_core.py:compute_exposures_by_strike',),
        justification='RC-357: share of sum(|net_gex_1pct|) contributed by the same-day-expiry book over the full book, where BOTH books come from compute_exposures_by_strike (the 0DTE one is the same call with use_only_dte_max=0) — same parser, same sign model, no second math path. A bucket missing net_gex_1pct withholds the whole ratio rather than contributing a fabricated zero weight (RC-369).',
    ),
    Row(
        file='math_exposure_core.py', derivation='exposures_have_dollar_gex', disposition='DERIVED',
        producer_refs=('math_exposure_core.py:bucket_metric',),
        justification='Detects dollarized GEX availability.',
    ),
    Row(
        file='math_exposure_core.py', derivation='gamma_is_plausible', disposition='DERIVED',
        producer_refs=('math_exposure_core.py:compute_exposures_by_strike',),
        justification='Rejects poisoned Schwab per-contract gamma (negative or implausibly large) before aggregation.',
    ),
    Row(
        file='math_exposure_core.py', derivation='gex_magnitude_label', disposition='DERIVED',
        producer_refs=('server.py:_fetch_state', 'market_state.py:build_market_state'),
        justification='Label from GEX magnitude.',
    ),
    Row(
        file='math_exposure_core.py', derivation='gex_regime_label', disposition='DERIVED',
        producer_refs=('server.py:_fetch_state', 'market_state.py:build_market_state'),
        justification='Regime label from sign of GEX.',
    ),
    Row(
        file='math_exposure_core.py', derivation='greek_bias', disposition='DERIVED',
        producer_refs=('server.py:_fetch_state', 'market_state.py:build_market_state'),
        justification='Bias string from greeks.',
    ),
    Row(
        file='math_exposure_core.py', derivation='greeks_validity', disposition='DERIVED',
        producer_refs=('server.py:_fetch_state', 'market_state.py:build_market_state'),
        justification='Validity gate on greek coverage.',
    ),
    Row(
        file='math_exposure_core.py', derivation='key_level_strikes_with_gamma', disposition='SCHWAB_LEAF',
        schwab_leaf='chains.*.gamma',
        justification='Strikes with usable gamma.',
    ),
    Row(
        file='math_exposure_core.py', derivation='key_level_strikes_with_oi', disposition='SCHWAB_LEAF',
        schwab_leaf='chains.*.openInterest',
        justification='Strikes with OI leaf.',
    ),
    Row(
        file='math_exposure_core.py', derivation='net_gamma_raw_at_strike', disposition='DERIVED',
        producer_refs=('math_exposure_core.py:bucket_metric',),
        justification='Raw net gamma.',
    ),
    Row(
        file='math_exposure_core.py', derivation='net_gex_dollars_at_strike', disposition='DERIVED',
        producer_refs=('math_exposure_core.py:bucket_metric',),
        justification='Net GEX$ at strike.',
    ),
    Row(
        file='math_exposure_core.py', derivation='pick_delta_wall_strikes', disposition='DERIVED',
        producer_refs=('math_exposure_core.py:exposures_have_dollar_gex', 'math_exposure_core.py:_pick_strike_max_metric', 'math_exposure_core.py:bucket_metric_abs'),
        justification='Call/put delta walls.',
    ),
    Row(
        file='math_exposure_core.py', derivation='pick_gamma_wall_strikes', disposition='DERIVED',
        producer_refs=('math_exposure_core.py:exposures_have_dollar_gex', 'math_exposure_core.py:_pick_strike_max_metric', 'math_exposure_core.py:bucket_metric_abs'),
        justification='Call/put gamma walls.',
    ),
    Row(
        file='math_exposure_core.py', derivation='pick_hvl_strike', disposition='DERIVED',
        producer_refs=('math_exposure_core.py:exposures_have_dollar_gex', 'math_exposure_core.py:_pick_strike_max_metric'),
        justification='High-vol level strike.',
    ),
    Row(
        file='math_exposure_core.py', derivation='pick_key_delta_strike', disposition='DERIVED',
        producer_refs=('math_exposure_core.py:bucket_metric_abs',),
        justification='Selects the strike with the largest total delta notional (|call DEX$|+|put DEX$|) from derived exposures; no raw leaf read.',
    ),
    Row(
        file='math_exposure_core.py', derivation='pick_key_delta_strike._total_dex', disposition='DERIVED',
        producer_refs=('math_exposure_core.py:bucket_metric_abs',),
        justification='Nested: sums |call DEX$|+|put DEX$| per strike bucket for the key-delta selection.',
    ),
    Row(
        file='math_exposure_core.py', derivation='pick_net_gex_peak_strike', disposition='DERIVED',
        producer_refs=('math_levels.py:build_summary_rows', 'server.py:_fetch_state', 'terrain_engine.py:compute_terrain'),
        justification="RC-124/RC-417: the strike with the largest |net GEX$| per 1% (calls MINUS puts) — a real measure of where the signed book concentrates, formerly displayed under the name 'gamma pin'. ExposureRow.net_gex_peak is this strike; the canonical pin is pick_pin_and_strength. institutional=True returns None rather than falling back to raw gamma.",
    ),
    Row(
        file='math_exposure_core.py', derivation='pick_pin_and_strength', disposition='DERIVED',
        producer_refs=('terrain_engine.py:compute_terrain',),
        justification="RC-124/RC-315: the strike with maximum TOTAL gamma (|call GEX$| + |put GEX$|) — a GROSS GAMMA CONCENTRATION, i.e. where the most dealer re-hedging activity sits — plus strength_pct, the leader's margin over the runner-up on the same metric. It is a pin CANDIDATE and NOT a demonstrated magnet: magnitude sets the SIZE of the hedging flow while the SIGN of the dealer position sets whether that flow stabilises or repels, and this metric discards the sign, so two strikes with equal absolute gamma can behave oppositely. The sign is also not observable — public open interest does not say who owns the contracts, so dealer direction is modelled (https://spotgamma.com/what-is-gex-gamma-exposure/). Expiration-date clustering turns on NET positioning, not gross: Ni, Pearson and Poteshman, Journal of Financial Economics, doi:10.1016/j.jfineco.2004.08.005. An earlier version of this row asserted that magnitude pins regardless of sign; that was refuted (RC-315) and must not return. Fail-closed: no dollarized GEX gives (None, None), never a raw-gamma fallback.",
    ),
    Row(
        file='math_exposure_core.py', derivation='pick_volatility_point_strikes', disposition='DERIVED',
        producer_refs=('math_exposure_core.py:bucket_metric',),
        justification='(HVP, LVP): strikes holding the most-negative / most-positive net GEX$ from derived exposures.',
    ),
    Row(
        file='math_exposure_core.py', derivation='returns_from_candles', disposition='SCHWAB_LEAF',
        schwab_leaf='pricehistory.candles.*.close',
        justification='Daily returns; datetime required (cross-section fix).',
    ),
    Row(
        file='math_exposure_core.py', derivation='sanitize_dealer_metrics', disposition='DERIVED',
        producer_refs=('math_exposure_core.py:greeks_validity',),
        justification='Sanitize when greeks invalid.',
    ),
    Row(
        file='math_exposure_core.py', derivation='schwab_iv_to_sigma', disposition='SCHWAB_LEAF',
        schwab_leaf='chains.callExpDateMap.*.volatility',
        justification='Single conversion of Schwab IV (reported in percent) to decimal sigma; guards a vendor units change.',
    ),
    Row(
        file='math_exposure_core.py', derivation='strike_agg', disposition='DERIVED',
        producer_refs=('server.py:_fetch_state', 'market_state.py:build_market_state'),
        justification='Delegates to Schwab transport producers for strike_agg.',
    ),
    Row(
        file='math_exposure_core.py', derivation='total_gamma_raw_at_strike', disposition='DERIVED',
        producer_refs=('math_exposure_core.py:bucket_metric_abs',),
        justification='Raw gamma magnitude fallback.',
    ),
    Row(
        file='math_exposure_core.py', derivation='total_gex_dollars_at_strike', disposition='DERIVED',
        producer_refs=('math_exposure_core.py:bucket_metric_abs',),
        justification='Sum |call|+|put| GEX$.',
    ),
    Row(
        file='math_exposure_core.py', derivation='window_summary', disposition='DERIVED',
        producer_refs=('math_exposure_core.py:bucket_metric',),
        justification='Window-level DEX/GEX/OI summary.',
    ),
    Row(
        file='math_levels.py', derivation='_bias_from_net', disposition='DERIVED',
        producer_refs=('server.py:_fetch_state', 'market_state.py:build_market_state'),
        justification='Bias signal taxonomy.',
    ),
    Row(
        file='math_levels.py', derivation='_contract_inputs', disposition='SCHWAB_LEAF',
        schwab_leaf='chains.callExpDateMap.*.volatility',
        justification='Reads strike/IV/OI/DTE/putCall leaves from the Schwab contract; normalizes IV-in-percent.',
    ),
    Row(
        file='math_levels.py', derivation='_dominant', disposition='DERIVED',
        producer_refs=('server.py:_fetch_state', 'market_state.py:build_market_state'),
        justification='Dominant side selection.',
    ),
    Row(
        file='math_levels.py', derivation='_interp_profile_at', disposition='DERIVED',
        producer_refs=('math_levels.py:compute_gamma_profile',),
        justification='Linear interpolation of net GEX$ at an arbitrary price on the ascending profile compute_gamma_profile materialised; clamps to the endpoints outside the profile span. Operates purely on that derived profile — no vendor field is read here.',
    ),
    Row(
        file='math_levels.py', derivation='_norm_pdf', disposition='DERIVED',
        producer_refs=('math_levels.py:bs_gamma',),
        justification='Standard normal PDF; pure math constant, no market field.',
    ),
    Row(
        file='math_levels.py', derivation='_pick_inflection_closest_zero', disposition='DERIVED',
        producer_refs=('server.py:_fetch_state', 'market_state.py:build_market_state'),
        justification='Zero-cross inflection picker.',
    ),
    Row(
        file='math_levels.py', derivation='_pick_oi_center', disposition='DERIVED',
        producer_refs=('server.py:_fetch_state', 'market_state.py:build_market_state'),
        justification='OI-weighted center.',
    ),
    Row(
        file='math_levels.py', derivation='_pin_strength', disposition='DERIVED',
        producer_refs=('server.py:_fetch_state', 'market_state.py:build_market_state'),
        justification='Net-GEX peak concentration vs neighbors (High/Med/Low of |net GEX$| at the analytics peak). Not the terrain pin lead %.',
    ),
    Row(
        file='math_levels.py', derivation='_total_gamma_at_strike', disposition='DERIVED',
        producer_refs=('server.py:_fetch_state', 'market_state.py:build_market_state'),
        justification='Total gamma measure at strike.',
    ),
    Row(
        file='math_levels.py', derivation='bs_charm', disposition='DERIVED',
        producer_refs=('math_levels.py:compute_charm_by_strike',),
        justification='Black-Scholes charm dDelta/dt per share; verified against a finite-difference derivative of BS delta.',
    ),
    Row(
        file='math_levels.py', derivation='bs_gamma', disposition='DERIVED',
        producer_refs=('math_levels.py:compute_gamma_profile',),
        justification="Black-Scholes gamma N'(d1)/(S*sigma*sqrt(T)); refuses T<=0 or sigma<=0.",
    ),
    Row(
        file='math_levels.py', derivation='bs_vanna', disposition='DERIVED',
        producer_refs=('math_exposure_core.py:compute_exposures_by_strike',),
        justification='Black-Scholes vanna dDelta/dSigma per share, closed form -e^(-qT) phi(d1) d2 / sigma — identical for calls and puts, sign driven entirely by -d2 so it flips through SPOT and never through the call/put boundary. Independently verified 2026-08-02 against a central finite difference of BS delta over 27 (K,T,sigma) points to max |err| 9.1e-9, and against both the vega and gamma identities; the gamma identity is a standing cross-check in tests/test_charm_sign_finite_difference.py. Units are delta-change per 1.00 of IV.',
    ),
    Row(
        file='math_levels.py', derivation='build_summary_rows', disposition='DERIVED',
        producer_refs=('math_exposure_core.py:compute_exposures_by_strike', 'market_state.py:build_market_state'),
        justification='KEY LEVELS summary table rows.',
    ),
    Row(
        file='math_levels.py', derivation='build_summary_rows.aggregate', disposition='DERIVED',
        producer_refs=('math_levels.py:build_summary_rows',),
        justification='Nested strike-window aggregate inside build_summary_rows.',
    ),
    Row(
        file='math_levels.py', derivation='build_totals_rows', disposition='DERIVED',
        producer_refs=('math_exposure_core.py:compute_exposures_by_strike',),
        justification='Totals table aggregation.',
    ),
    Row(
        file='math_levels.py', derivation='build_totals_rows.strikes_for', disposition='DERIVED',
        producer_refs=('math_levels.py:build_totals_rows',),
        justification='Nested strike list filter inside build_totals_rows.',
    ),
    Row(
        file='math_levels.py', derivation='build_walls_rows', disposition='DERIVED',
        producer_refs=('math_exposure_core.py:compute_exposures_by_strike', 'market_state.py:build_market_state'),
        justification='Walls table for UI.',
    ),
    Row(
        file='math_levels.py', derivation='compute_charm_by_strike', disposition='DERIVED',
        producer_refs=('terrain_engine.py:compute_terrain',),
        justification='Per-strike dealer charm exposure in delta-shares/day, +call/-put convention.',
    ),
    Row(
        file='math_levels.py', derivation='compute_gamma_flip_v2', disposition='DERIVED',
        producer_refs=('server.py:_fetch_state',),
        justification='Gamma flip plus chain-span confidence flag; narrow chains are never served as trustworthy.',
    ),
    Row(
        file='math_levels.py', derivation='compute_gamma_profile', disposition='DERIVED',
        producer_refs=('server.py:_fetch_state',),
        justification='Dealer gamma recomputed at each hypothetical spot (+call/-put); canonical profile.',
    ),
    Row(
        file='math_levels.py', derivation='compute_gamma_support_levels', disposition='DERIVED',
        producer_refs=('math_levels.py:compute_gamma_profile', 'math_levels.py:_interp_profile_at'),
        justification='RC-354: the Gamma Support Floor (highest s < spot with N(s) <= phi*N(spot)) and Gamma Resistance Ceiling (lowest s > spot with the same condition) on the SAME materialised net-GEX profile the flip and regime read (RC-345 one-profile rule), located by walking outward from spot and linearly interpolating the crossing. Fail-closed: N(spot) <= eps returns state=BELOW_SUPPORT with both levels None, an unusable profile returns state=UNAVAILABLE — never a fabricated price.',
    ),
    Row(
        file='math_levels.py', derivation='compute_gamma_void_zones', disposition='DERIVED',
        producer_refs=('math_exposure_core.py:compute_exposures_by_strike',),
        justification='Delegates to Schwab transport producers for compute_gamma_void_zones.',
    ),
    Row(
        file='math_levels.py', derivation='compute_gamma_void_zones._get_gex', disposition='DERIVED',
        producer_refs=('math_levels.py:compute_gamma_void_zones',),
        justification='Nested GEX reader; parent REPLACED forbids or-zero synthesis.',
    ),
    Row(
        file='math_levels.py', derivation='compute_gamma_void_zones._get_oi', disposition='DERIVED',
        producer_refs=('math_levels.py:compute_gamma_void_zones',),
        justification='Nested OI reader inside compute_gamma_void_zones.',
    ),
    Row(
        file='math_levels.py', derivation='compute_hvl', disposition='DERIVED',
        producer_refs=('math_exposure_core.py:compute_exposures_by_strike', 'market_state.py:build_market_state'),
        justification='Delegates pick_hvl_strike.',
    ),
    Row(
        file='math_levels.py', derivation='compute_level_density', disposition='DERIVED',
        producer_refs=('server.py:_fetch_state', 'market_state.py:build_market_state'),
        justification='Density metric for level bands.',
    ),
    Row(
        file='math_levels.py', derivation='compute_max_pain', disposition='DERIVED',
        producer_refs=('math_exposure_core.py:compute_exposures_by_strike', 'server.py:_fetch_state'),
        justification='Max pain from OI; no Schwab max-pain leaf.',
    ),
    Row(
        file='math_levels.py', derivation='compute_max_pain._pain_at', disposition='DERIVED',
        producer_refs=('math_levels.py:compute_max_pain',),
        justification='Nested pain calc at settlement inside compute_max_pain.',
    ),
    Row(
        file='math_levels.py', derivation='compute_pin_width_pts', disposition='DERIVED',
        producer_refs=('market_state.py:build_market_state', 'server.py:_fetch_state'),
        justification='RC-345/F20 one authority for pin width: call_gamma_wall - put_gamma_wall in points; None unless both walls present.',
    ),
    Row(
        file='math_levels.py', derivation='consensus_walls_bind_terrain_ssot', disposition='DERIVED',
        producer_refs=('terrain_engine.py:compute_terrain', 'math_levels.py:build_walls_rows'),
        justification='RC-420/RC-422: CONSENSUS gamma/delta wall strikes bind to the terrain cache; OI/vanna wall slots are withheld because terrain does not compute them.',
    ),
    Row(
        file='math_levels.py', derivation='gamma_at_price', disposition='DERIVED',
        producer_refs=('math_levels.py:compute_gamma_flip_v2',),
        justification='Net dealer gamma interpolated at a price; the SIGN of this value defines the regime, independent of whether a flip exists.',
    ),
    Row(
        file='math_levels.py', derivation='gamma_flip_from_profile', disposition='DERIVED',
        producer_refs=('math_levels.py:compute_gamma_flip_v2',),
        justification='Interpolated zero-crossing of the gamma profile.',
    ),
    Row(
        file='math_levels.py', derivation='hvl_gamma_strength', disposition='DERIVED',
        producer_refs=('math_levels.py:_total_gamma_at_strike',),
        justification='Strength at HVL.',
    ),
    Row(
        file='math_levels.py', derivation='infer_strike_increment', disposition='SCHWAB_LEAF',
        schwab_leaf='chains.callExpDateMap.*.strikePrice',
        justification='Median adjacent difference of strikePrice values from an already-fetched chain; junk rows skipped, thin chains return None.',
    ),
    Row(
        file='math_levels.py', derivation='is_pin_zone', disposition='ALLOWLISTED',
        allowlist_id='mega2_internal_helper',
        justification='Zone classifier constant check.',
    ),
    Row(
        file='math_levels.py', derivation='max_pain_oi_strength', disposition='DERIVED',
        producer_refs=('server.py:_fetch_state', 'market_state.py:build_market_state'),
        justification='OI at max pain strike.',
    ),
    Row(
        file='math_levels.py', derivation='parity_f_minus_spot_from_contracts', disposition='SCHWAB_LEAF',
        schwab_leaf='chains.callExpDateMap.*.mark',
        justification='Parity residual; mark-only mid per strike.',
    ),
    Row(
        file='math_levels.py', derivation='parity_f_minus_spot_from_contracts._mid', disposition='SCHWAB_LEAF',
        schwab_leaf='chains.callExpDateMap.*.mark',
        justification='Nested mid from Schwab bid/ask/mark only.',
    ),
    Row(
        file='math_levels.py', derivation='pick_charm_wall_strikes', disposition='DERIVED',
        producer_refs=('terrain_engine.py:compute_terrain',),
        justification='Strikes of maximum call-side and put-side charm exposure.',
    ),
    Row(
        file='math_levels.py', derivation='snap_level_to_shelf_strike', disposition='DERIVED',
        producer_refs=('math_exposure_core.py:compute_exposures_by_strike', 'math_levels.py:compute_gamma_support_levels'),
        justification='RC-354 snap-to-shelf: moves a profile-derived GSF/GRC onto a real positive-GEX strike when one clearing the caller-supplied theta sits within snap_pct of it on the correct side of spot. Both inputs are already-derived — the level from compute_gamma_support_levels, the per-strike GEX$ from the exposures book — so no vendor field is read; a None level and an empty strike map pass through unchanged.',
    ),
    Row(
        file='math_probabilities.py', derivation='_oe_wall_consensus_row', disposition='DERIVED',
        producer_refs=('server.py:_fetch_state', 'market_state.py:build_market_state'),
        justification='Delegates to Schwab transport producers for _oe_wall_consensus_row.',
    ),
    Row(
        file='math_probabilities.py', derivation='_wlevel', disposition='DERIVED',
        producer_refs=('server.py:_fetch_state', 'market_state.py:build_market_state'),
        justification='Delegates to Schwab transport producers for _wlevel.',
    ),
    Row(
        file='math_probabilities.py', derivation='atm_flow_window_totals', disposition='DERIVED',
        producer_refs=('server.py:_fetch_state', 'market_state.py:build_market_state'),
        justification='ATM window flow totals.',
    ),
    Row(
        file='math_probabilities.py', derivation='bucket_hi', disposition='ALLOWLISTED',
        allowlist_id='mega2_internal_helper',
        justification='Bucket upper bound map.',
    ),
    Row(
        file='math_probabilities.py', derivation='bucket_lo', disposition='ALLOWLISTED',
        allowlist_id='mega2_internal_helper',
        justification='Bucket lower bound map.',
    ),
    Row(
        file='math_probabilities.py', derivation='classify_direction', disposition='DERIVED',
        producer_refs=('server.py:_fetch_state', 'market_state.py:build_market_state'),
        justification='Direction from move threshold.',
    ),
    Row(
        file='math_probabilities.py', derivation='classify_reversal_risk', disposition='DERIVED',
        producer_refs=('server.py:_fetch_state', 'market_state.py:build_market_state'),
        justification='Derived field logic for classify_reversal_risk.',
    ),
    Row(
        file='math_probabilities.py', derivation='compute_breakout_score', disposition='DERIVED',
        producer_refs=('server.py:_fetch_state', 'market_state.py:build_market_state'),
        justification='Breakout composite.',
    ),
    Row(
        file='math_probabilities.py', derivation='compute_dealer_pressure_index', disposition='DERIVED',
        producer_refs=('server.py:_fetch_state', 'market_state.py:build_market_state'),
        justification='DPI composite.',
    ),
    Row(
        file='math_probabilities.py', derivation='compute_gamma_gradient', disposition='DERIVED',
        producer_refs=('server.py:_fetch_state', 'market_state.py:build_market_state'),
        justification='dGEX/dPrice near spot.',
    ),
    Row(
        file='math_probabilities.py', derivation='compute_hedging_flow_score', disposition='DERIVED',
        producer_refs=('server.py:_fetch_state', 'market_state.py:build_market_state'),
        justification='Hedging flow score.',
    ),
    Row(
        file='math_probabilities.py', derivation='compute_iwm_confluence', disposition='DERIVED',
        producer_refs=('server.py:_fetch_state', 'market_state.py:build_market_state'),
        justification='IWM blended participation.',
    ),
    Row(
        file='math_probabilities.py', derivation='compute_option_flow_imbalance', disposition='SCHWAB_LEAF',
        schwab_leaf='chains.callExpDateMap.*.bidSize',
        justification='Bid/ask size imbalance from Schwab leaves.',
    ),
    Row(
        file='math_probabilities.py', derivation='compute_percentile_range', disposition='DERIVED',
        producer_refs=('server.py:_fetch_state', 'market_state.py:build_market_state'),
        justification='Percentile band from history.',
    ),
    Row(
        file='math_probabilities.py', derivation='compute_pin_score', disposition='DERIVED',
        producer_refs=('server.py:_fetch_state', 'market_state.py:build_market_state'),
        justification='Pin score from GEX.',
    ),
    Row(
        file='math_probabilities.py', derivation='compute_probs', disposition='DERIVED',
        producer_refs=('server.py:_fetch_state', 'market_state.py:build_market_state'),
        justification='Historical outcome probabilities.',
    ),
    Row(
        file='math_probabilities.py', derivation='compute_sector_strength', disposition='DERIVED',
        producer_refs=('server.py:_fetch_state', 'market_state.py:build_market_state'),
        justification='Sector strength from context quotes.',
    ),
    Row(
        file='math_probabilities.py', derivation='compute_smart_money_signal', disposition='DERIVED',
        producer_refs=('server.py:_fetch_state', 'market_state.py:build_market_state'),
        justification='Fail-closed Schwab leaf read: chains.* volume,OI,bid/ask size.',
    ),
    Row(
        file='math_probabilities.py', derivation='compute_sweep_score', disposition='DERIVED',
        producer_refs=('server.py:_fetch_state', 'market_state.py:build_market_state'),
        justification='Sweep detection score.',
    ),
    Row(
        file='math_probabilities.py', derivation='compute_vol_expansion_signal', disposition='DERIVED',
        producer_refs=('server.py:_fetch_state', 'market_state.py:build_market_state'),
        justification='Vol expansion signal.',
    ),
    Row(
        file='math_probabilities.py', derivation='compute_volume_oi_ratio', disposition='DERIVED',
        producer_refs=('server.py:_fetch_state', 'market_state.py:build_market_state'),
        justification='Volume/OI per strike.',
    ),
    Row(
        file='math_probabilities.py', derivation='compute_wall_score_components', disposition='DERIVED',
        producer_refs=('math_probabilities.py:_oe_wall_consensus_row', 'math_probabilities.py:_wlevel'),
        justification='Wall proximity scoring.',
    ),
    Row(
        file='math_probabilities.py', derivation='determine_confidence', disposition='DERIVED',
        producer_refs=('server.py:_fetch_state',),
        justification='Confidence label.',
    ),
    Row(
        file='math_probabilities.py', derivation='dist_bucket', disposition='DERIVED',
        producer_refs=('server.py:_fetch_state', 'market_state.py:build_market_state'),
        justification='Distance bucket label.',
    ),
    Row(
        file='math_probabilities.py', derivation='dominant_direction', disposition='DERIVED',
        producer_refs=('server.py:_fetch_state', 'market_state.py:build_market_state'),
        justification='Dominant class from probs.',
    ),
    Row(
        file='math_probabilities.py', derivation='flow_imbalance_normalized_with_fallback', disposition='DERIVED',
        producer_refs=('math_probabilities.py:atm_flow_window_totals', 'math_probabilities.py:compute_option_flow_imbalance'),
        justification='Normalized flow with explicit fallback policy.',
    ),
    Row(
        file='math_probabilities.py', derivation='score_option_expression', disposition='DERIVED',
        producer_refs=('math_probabilities.py:compute_wall_score_components',),
        justification='OE score; spread from bid-ask pts only.',
    ),
    Row(
        file='math_snapshot_derive.py', derivation='derive_pressure_trend', disposition='DERIVED',
        producer_refs=('market_state.py:build_market_state',),
        justification='DPI trend label; not a Schwab wire field.',
    ),
    Row(
        file='math_snapshot_derive.py', derivation='derive_vwap_side', disposition='DERIVED',
        producer_refs=('market_context.py:fetch_price_levels', 'market_state.py:build_market_state'),
        justification='spot vs vwap side; no Schwab vwap_side leaf.',
    ),
    Row(
        file='math_volatility.py', derivation='_extract_iv_for_strike', disposition='SCHWAB_LEAF',
        schwab_leaf='chains.*.volatility',
        justification='Mean call/put IV at strike; skip invalid.',
    ),
    Row(
        file='math_volatility.py', derivation='_spot_atm_strike', disposition='DERIVED',
        producer_refs=('server.py:_fetch_state', 'market_state.py:build_market_state'),
        justification='ATM strike from chain.',
    ),
    Row(
        file='math_volatility.py', derivation='blend_garch_sigma', disposition='DERIVED',
        producer_refs=('server.py:_fetch_state', 'market_state.py:build_market_state'),
        justification='Blend GARCH+IV+RV per-bar sigma.',
    ),
    Row(
        file='math_volatility.py', derivation='charm_intraday_context', disposition='DERIVED',
        producer_refs=('server.py:_fetch_state', 'market_state.py:build_market_state'),
        justification='Banner from charm_result dict.',
    ),
    Row(
        file='math_volatility.py', derivation='compute_25d_risk_reversal', disposition='SCHWAB_LEAF',
        schwab_leaf='chains.callExpDateMap.*.volatility',
        justification='RC-358: IV(25-delta call) minus IV(25-delta put) on the front expiry, in vol points. Unlike the other RC-35x metrics this one reads the vendor contract dicts directly — putCall, daysToExpiration, delta and the `volatility` leaf, which Schwab reports in PERCENT and which stays in vol points here. Front expiry is the smallest usable dte >= 0; each wing must sit within RR25_DELTA_TOL of its +/-0.25 target and the -999 missing-greek sentinel is rejected, so a missing or off-target wing withholds the whole reading rather than producing a fabricated skew.',
    ),
    Row(
        file='math_volatility.py', derivation='compute_atr', disposition='DERIVED',
        producer_refs=('math_volatility.py:compute_atr._get',),
        justification='ATR from Schwab candles; skip incomplete bars.',
    ),
    Row(
        file='math_volatility.py', derivation='compute_atr._get', disposition='DERIVED',
        producer_refs=('server.py:_fetch_state', 'market_state.py:build_market_state'),
        justification='Nested candle field reader inside compute_atr.',
    ),
    Row(
        file='math_volatility.py', derivation='compute_em_progress', disposition='DERIVED',
        producer_refs=('server.py:_fetch_state', 'market_state.py:build_market_state'),
        justification='Progress through EM range.',
    ),
    Row(
        file='math_volatility.py', derivation='compute_expected_move_iv', disposition='DERIVED',
        producer_refs=('market_state.py:build_market_state', 'server.py:_fetch_state'),
        justification='EM from IV + time; IV from Schwab volatility leaf.',
    ),
    Row(
        file='math_volatility.py', derivation='compute_expected_move_straddle', disposition='DERIVED',
        producer_refs=('server.py:_fetch_state', 'market_state.py:build_market_state'),
        justification='EM from ATM marks; not single EM leaf.',
    ),
    Row(
        file='math_volatility.py', derivation='compute_garch_forecast', disposition='DERIVED',
        producer_refs=('math_volatility.py:estimate_garch_params',),
        justification='Forward sigma from GARCH.',
    ),
    Row(
        file='math_volatility.py', derivation='compute_iv_model_spread', disposition='DERIVED',
        producer_refs=('server.py:_fetch_state', 'market_state.py:build_market_state'),
        justification='Market vs model IV (OP-012).',
    ),
    Row(
        file='math_volatility.py', derivation='compute_iv_percentile', disposition='DERIVED',
        producer_refs=('server.py:_fetch_state', 'market_state.py:build_market_state'),
        justification='IV percentile vs history.',
    ),
    Row(
        file='math_volatility.py', derivation='compute_iv_rank', disposition='DERIVED',
        producer_refs=('server.py:_fetch_state', 'market_state.py:build_market_state'),
        justification='IV rank vs history series.',
    ),
    Row(
        file='math_volatility.py', derivation='compute_iv_skew', disposition='SCHWAB_LEAF',
        schwab_leaf='chains.*.volatility',
        justification='Put IV minus call IV at ATM.',
    ),
    Row(
        file='math_volatility.py', derivation='compute_realized_vol', disposition='DERIVED',
        producer_refs=('server.py:_fetch_state', 'market_state.py:build_market_state'),
        justification='RV from closes; Schwab OHLC input.',
    ),
    Row(
        file='math_volatility.py', derivation='compute_volatility_envelope', disposition='DERIVED',
        producer_refs=('server.py:_fetch_state', 'market_state.py:build_market_state'),
        justification='ATR bands around spot.',
    ),
    Row(
        file='math_volatility.py', derivation='estimate_garch_params', disposition='DERIVED',
        producer_refs=('server.py:_fetch_state', 'market_state.py:build_market_state'),
        justification='GARCH param estimation from returns.',
    ),
    Row(
        file='math_volatility.py', derivation='iv_percent_from_em_pts', disposition='DERIVED',
        producer_refs=('server.py:_fetch_state', 'market_state.py:build_market_state'),
        justification='Invert IV-EM formula.',
    ),
    Row(
        file='math_volatility.py', derivation='resolve_kl_em_anchor', disposition='DERIVED',
        producer_refs=('server.py:_fetch_state', 'market_state.py:build_market_state'),
        justification='Anchor policy for KL+MC alignment.',
    ),
    Row(
        file='math_volatility.py', derivation='resolve_mc_iv_for_kl_em_anchor', disposition='DERIVED',
        producer_refs=('market_state.py:build_market_state',),
        justification='MC IV reconciled to KL anchor.',
    ),
    Row(
        file='math_volatility.py', derivation='session_bucket', disposition='DERIVED',
        producer_refs=('server.py:_fetch_state', 'market_state.py:build_market_state'),
        justification='No Schwab session_label leaf.',
    ),
    Row(
        file='math_volatility.py', derivation='vix_bucket', disposition='DERIVED',
        producer_refs=('math_volatility.py:vix_tier_token',),
        justification='SignalInput vix_* label from vix_tier_token authority.',
    ),
    Row(
        file='math_volatility.py', derivation='vix_tier_token', disposition='DERIVED',
        producer_refs=('server.py:_fetch_state', 'market_state.py:build_market_state'),
        justification='Canonical VIX tier token (15/20/30 cuts); shared authority for vix_bucket and L1 vol regime.',
    ),
    Row(
        file='mc_fusion_adjustment.py', derivation='_argmax_dir', disposition='ALLOWLISTED',
        allowlist_id='mega3_internal_helper',
        justification='Pure probability blending helper.',
    ),
    Row(
        file='mc_fusion_adjustment.py', derivation='_blend_uniform', disposition='ALLOWLISTED',
        allowlist_id='mega3_internal_helper',
        justification='Pure probability blending helper.',
    ),
    Row(
        file='mc_fusion_adjustment.py', derivation='_max_uniform_blend_preserving_argmax', disposition='ALLOWLISTED',
        allowlist_id='mega3_internal_helper',
        justification='Pure probability blending helper.',
    ),
    Row(
        file='mc_fusion_adjustment.py', derivation='_triplet', disposition='ALLOWLISTED',
        allowlist_id='mega3_internal_helper',
        justification='Pure probability blending helper.',
    ),
    Row(
        file='mc_fusion_adjustment.py', derivation='apply_mc_adjustment', disposition='DERIVED',
        producer_refs=('mc_fusion_adjustment.py:_triplet', 'mc_fusion_adjustment.py:_argmax_dir', 'mc_fusion_adjustment.py:_max_uniform_blend_preserving_argmax', 'mc_fusion_adjustment.py:_blend_uniform', 'market_state.py:build_market_state'),
        justification='Blends MC path features into fusion probabilities.',
    ),
    Row(
        file='mc_fusion_adjustment.py', derivation='fuse_payload_apply_mc_adjustment', disposition='DERIVED',
        producer_refs=('mc_fusion_adjustment.py:normalize_mc', 'mc_fusion_adjustment.py:apply_mc_adjustment', 'mc_fusion_adjustment.py:_argmax_dir'),
        justification='Applies MC adjustment on fusion payload object.',
    ),
    Row(
        file='mc_fusion_adjustment.py', derivation='normalize_mc', disposition='DERIVED',
        producer_refs=('market_state.py:build_market_state',),
        justification='Normalizes MC output relative to spot.',
    ),
    Row(
        file='ml_data_common.py', derivation='attach_5m_additive_context', disposition='ALLOWLISTED',
        allowlist_id='mega1_sqlite_internal',
        justification='Orchestrator: calls fetch_m5_additive_dict for SQLite read, attaches 5m additive context onto caller-supplied snapshot rows. No direct Schwab wire derivation.',
    ),
    Row(
        file='ml_data_common.py', derivation='confluence_features_for_bar', disposition='ALLOWLISTED',
        allowlist_id='mega1_sqlite_internal',
        justification='RC-332: the production authority for cf_* at one bar — it obtains its own population through fetch_confluence_history and applies lstm_data.compute_confluence_features, deliberately refusing a caller-supplied population because six lanes passing six populations under one feature name was the measured defect (179 divergent cells over 826 SPY bars). The optional cache holds one UTC-day pool per ticker and changes no value. Mega4 internal SQLite read; no Schwab wire derivation.',
    ),
    Row(
        file='ml_data_common.py', derivation='fetch_confluence_history', disposition='ALLOWLISTED',
        allowlist_id='mega1_sqlite_internal',
        justification='RC-328 part A: opens the internal SQLite read on caller-supplied db_path and returns the UNFILTERED canonical 1m series from SERVE_SNAPSHOT_TABLE between two timestamps, bound under the canonical storage key. It is the one population both the training and serve lanes derive cf_* from — previously training reused its label/RTH-filtered frame as history, so one name carried two quantities. Mega4 internal SQLite read; the persisted rows trace to Mega1 producers, no Schwab wire derivation here.',
    ),
    Row(
        file='ml_data_common.py', derivation='fetch_m5_additive_dict', disposition='ALLOWLISTED',
        allowlist_id='mega1_sqlite_internal',
        justification='Opens SQLite read on caller-supplied conn (db_path → sqlite3 Connection upstream); fetches 5m additive features per (ticker, ts) for snapshot join. Mega4 internal SQLite read; no Schwab wire derivation.',
    ),
    Row(
        file='ml_data_common.py', derivation='prepare_row_for_xgb_features', disposition='ALLOWLISTED',
        allowlist_id='mega1_sqlite_internal',
        justification='RC-340: the one enrichment applied to a DB-shaped row before engineer_single_snapshot — attach_net_gamma_prev_for_dgex followed by confluence_features_for_bar — so scheduler and cascade routes cannot build vectors with NaN dgex and flat cf_*. Reads the DB only through those two delegates. Mega4 internal SQLite read; no Schwab wire derivation.',
    ),
    Row(
        file='ml_horizon.py', derivation='live_stack_probs_bundle_key', disposition='DERIVED',
        producer_refs=('market_state.py:build_market_state',),
        justification='Inference on canonical features; no Schwab wire ingest.',
    ),
    Row(
        file='ml_predict.py', derivation='_cascade_challenger_inference_scope', disposition='DERIVED',
        producer_refs=('market_state.py:build_market_state',),
        justification='Inference on canonical features; no Schwab wire ingest.',
    ),
    Row(
        file='ml_predict.py', derivation='_model_dir_for_ticker', disposition='ALLOWLISTED',
        allowlist_id='mega1_filesystem',
        justification='Path resolver for the per-ticker per-horizon model directory under models/; filesystem path construction with no Schwab wire output. Producer-leaf of the model-inference chain.',
    ),
    Row(
        file='ml_predict.py', derivation='_model_registry_key', disposition='ALLOWLISTED',
        allowlist_id='mega1_internal_helper',
        justification='In-memory cache key builder for the base-stack model registry; pure parse/format with no Schwab wire output. Producer-leaf of the model-inference chain.',
    ),
    Row(
        file='ml_predict.py', derivation='_normalize_binary_head_probs', disposition='DERIVED',
        producer_refs=('market_state.py:build_market_state',),
        justification='Inference on canonical features; no Schwab wire ingest.',
    ),
    Row(
        file='ml_predict.py', derivation='_predict_xgb_movement_heads', disposition='DERIVED',
        producer_refs=('market_state.py:build_market_state', 'ml_predict.py:_model_dir_for_ticker', 'ml_predict.py:_normalize_binary_head_probs', 'ml_predict.py:_model_registry_key'),
        justification='XGB movement-head inference on features composed from market_state.build_market_state (Mega1 producer) + in-memory movement-head model loaded by registry key. Output is model probability, not a direct Schwab field.',
    ),
    Row(
        file='ml_predict.py', derivation='_probs_dict_to_arr', disposition='DERIVED',
        producer_refs=('market_state.py:build_market_state',),
        justification='Inference on canonical features; no Schwab wire ingest.',
    ),
    Row(
        file='ml_predict.py', derivation='_stack_probs', disposition='DERIVED',
        producer_refs=('market_state.py:build_market_state',),
        justification='Inference on canonical features; no Schwab wire ingest.',
    ),
    Row(
        file='ml_predict.py', derivation='stack_probs_bundle_key', disposition='DERIVED',
        producer_refs=('market_state.py:build_market_state',),
        justification='Inference on canonical features; no Schwab wire ingest.',
    ),
    Row(
        file='ml_scheduler.py', derivation='_diagnostic_db_tickers_not_enrolled', disposition='ALLOWLISTED',
        allowlist_id='mega1_sqlite_internal',
        justification='Opens SQLite read on caller-supplied db_path; returns tickers in the DB that are not in the configured enrolled universe (diagnostic). Mega4 internal SQLite read; no Schwab wire derivation.',
    ),
    Row(
        file='ml_scheduler.py', derivation='_evaluate_cascade_on_full_rth', disposition='ALLOWLISTED',
        allowlist_id='mega1_sqlite_internal',
        justification='Cascade-architecture evaluator: same db_path → _load_rth_rows_for_ticker SQLite read → cascade ML stack layer inference + realized metrics. Mega4 orchestrator; no direct Schwab wire derivation.',
    ),
    Row(
        file='ml_scheduler.py', derivation='_evaluate_parallel_on_full_rth', disposition='ALLOWLISTED',
        allowlist_id='mega1_sqlite_internal',
        justification='Parallel-architecture evaluator: takes db_path, calls _load_rth_rows_for_ticker for SQLite reads, runs ML stack layer inference on each RTH row, computes realized metrics. Mega4 orchestrator; no direct Schwab wire derivation.',
    ),
    Row(
        file='ml_scheduler.py', derivation='_get_tickers_with_rth_data', disposition='ALLOWLISTED',
        allowlist_id='mega1_sqlite_internal',
        justification='Opens SQLite read on caller-supplied db_path; returns the set of tickers with RTH snapshots in the canonical timeframe. Mega4 internal SQLite read; no Schwab wire derivation.',
    ),
    Row(
        file='ml_scheduler.py', derivation='_load_rth_rows_for_ticker', disposition='ALLOWLISTED',
        allowlist_id='mega1_sqlite_internal',
        justification='Opens SQLite read on caller-supplied db_path; loads RTH snapshot rows for a ticker into the training pipeline. Mega4 internal SQLite read; no Schwab wire derivation.',
    ),
    Row(
        file='ml_scheduler.py', derivation='_strict_off_for_candidate_inference', disposition='DERIVED',
        producer_refs=('market_state.py:build_market_state',),
        justification='Inference on canonical features; no Schwab wire ingest.',
    ),
    Row(
        file='ml_scheduler.py', derivation='_train_cascade', disposition='ALLOWLISTED',
        allowlist_id='mega1_sqlite_internal',
        justification='Inner cascade training helper: delegates to train_all cascade training functions on caller-supplied historical DB shim. Mega4 internal; no direct Schwab wire derivation.',
    ),
    Row(
        file='ml_scheduler.py', derivation='_train_parallel', disposition='ALLOWLISTED',
        allowlist_id='mega1_sqlite_internal',
        justification='Inner parallel training helper: delegates to train_all training functions on caller-supplied historical DB shim. Mega4 internal; no direct Schwab wire derivation.',
    ),
    Row(
        file='ml_scheduler.py', derivation='run_once', disposition='ALLOWLISTED',
        allowlist_id='mega1_sqlite_internal',
        justification='Per-tick scheduler orchestrator: walks the enrolled ticker universe, calls train_parallel_candidate + train_cascade_candidate + the architecture evaluator + promotion engine. Mega4 entry point; no direct Schwab wire derivation.',
    ),
    Row(
        file='ml_scheduler.py', derivation='start_background_scheduler', disposition='ALLOWLISTED',
        allowlist_id='mega1_sqlite_internal',
        justification='Spins up a background thread that loops run_once at the scheduled cadence. Mega4 scheduler entry point; no direct Schwab wire derivation.',
    ),
    Row(
        file='ml_scheduler.py', derivation='start_background_scheduler._loop', disposition='ALLOWLISTED',
        allowlist_id='mega1_sqlite_internal',
        justification='Nested loop body for start_background_scheduler: sleeps until next scheduled run then invokes run_once. Mega4 internal; no direct Schwab wire derivation.',
    ),
    Row(
        file='ml_scheduler.py', derivation='train_cascade_candidate', disposition='ALLOWLISTED',
        allowlist_id='mega1_sqlite_internal',
        justification='Cascade candidate training orchestrator: takes db_path, calls _load_rth_rows_for_ticker for SQLite reads, fits cascade architecture ML stack layers + meta, persists artifacts. No direct Schwab wire derivation.',
    ),
    Row(
        file='ml_scheduler.py', derivation='train_parallel_candidate', disposition='ALLOWLISTED',
        allowlist_id='mega1_sqlite_internal',
        justification='Parallel candidate training orchestrator: takes db_path, calls _load_rth_rows_for_ticker for SQLite reads, fits xgb / lstm / transformer ML stack layers + meta, persists artifacts. No direct Schwab wire derivation.',
    ),
    Row(
        file='ml_train.py', derivation='load_data', disposition='ALLOWLISTED',
        allowlist_id='mega1_sqlite_internal',
        justification='Opens SQLite on caller-supplied db_path; reads snapshots table for the target ticker, returns list of row dicts. Mega4 internal SQLite read; no Schwab wire derivation here (persisted rows trace to Mega1 producers).',
    ),
    Row(
        file='ml_train.py', derivation='train_ticker', disposition='ALLOWLISTED',
        allowlist_id='mega1_sqlite_internal',
        justification='Per-ticker training orchestrator: takes db_path, calls load_data for SQLite read, engineer_features for the feature matrix, fits the XGB model + persists artifact. No direct Schwab wire derivation.',
    ),
    Row(
        file='monte_carlo.py', derivation='MonteCarloOutput.mc_feature_dict', disposition='DERIVED',
        producer_refs=('market_state.py:build_market_state',),
        justification='MC feature dict for fusion; not quote fields.',
    ),
    Row(
        file='monte_carlo.py', derivation='_blend_sigma', disposition='DERIVED',
        producer_refs=('market_state.py:build_market_state',),
        justification='Sigma blend; inputs from Schwab-first chain/candles upstream.',
    ),
    Row(
        file='monte_carlo.py', derivation='_compute_drift', disposition='DERIVED',
        producer_refs=('market_state.py:build_market_state',),
        justification='Drift from regime + model confidence; not a Schwab leaf.',
    ),
    Row(
        file='monte_carlo.py', derivation='simulate', disposition='DERIVED',
        producer_refs=('market_state.py:build_market_state', 'monte_carlo.py:_compute_drift', 'monte_carlo.py:_blend_sigma'),
        justification='MC paths from upstream vol/spot; no Schwab wire ingest.',
    ),
    Row(
        file='normalized_training_sync.py', derivation='compute_snapshots_training_fingerprint', disposition='ALLOWLISTED',
        allowlist_id='mega1_sqlite_internal',
        justification='Opens SQLite connection on the snapshots DB, computes a stable training fingerprint (SUM + COUNT aggregates over caller-specified columns) for materialise-detection. Persistence-only; no Schwab wire derivation.',
    ),
    Row(
        file='normalized_training_sync.py', derivation='ensure_normalized_training_table', disposition='ALLOWLISTED',
        allowlist_id='mega1_sqlite_internal',
        justification='Opens SQLite write connection on the snapshots DB to CREATE TABLE IF NOT EXISTS for the normalized_training_meta governance table. Persistence-only; no Schwab wire derivation.',
    ),
    Row(
        file='normalized_training_sync.py', derivation='persist_training_fingerprint_after_materialize', disposition='ALLOWLISTED',
        allowlist_id='mega1_sqlite_internal',
        justification='Opens SQLite write connection on the snapshots DB to record the post-materialise fingerprint + timestamp into normalized_training_meta. Persistence-only; no Schwab wire derivation.',
    ),
    Row(
        file='normalized_training_sync.py', derivation='schedule_debounced_normalized_refresh', disposition='ALLOWLISTED',
        allowlist_id='mega1_sqlite_internal',
        justification='Background-thread scheduler: invokes verify_normalized_freshness + (if drift) materialise; both downstream do SQLite reads/writes. Persistence-only; no Schwab wire derivation.',
    ),
    Row(
        file='normalized_training_sync.py', derivation='verify_normalized_freshness', disposition='ALLOWLISTED',
        allowlist_id='mega1_sqlite_internal',
        justification='Opens SQLite read connection on the snapshots DB to compare current compute_snapshots_training_fingerprint vs the persisted fingerprint and report drift. Persistence-only; no Schwab wire derivation.',
    ),
    Row(
        file='order_flow_engine.py', derivation='OrderFlowEngine._empty_result', disposition='ALLOWLISTED',
        allowlist_id='mega2_schwab_stream_l1',
        justification='Schwab LEVEL_ONE/stream book fields ingested via streaming adapter (OrderFlowEngine._empty_result).',
    ),
    Row(
        file='order_flow_engine.py', derivation='OrderFlowEngine.compute', disposition='DERIVED',
        producer_refs=('order_flow_live_state.py:get_content_for_symbol',),
        justification='Public OF engine entry; composes sub-metrics.',
    ),
    Row(
        file='order_flow_engine.py', derivation='_book_concentration', disposition='ALLOWLISTED',
        allowlist_id='mega2_schwab_stream_l1',
        justification='Schwab LEVEL_ONE/stream book fields ingested via streaming adapter (_book_concentration).',
    ),
    Row(
        file='order_flow_engine.py', derivation='_book_imbalance_from_totals', disposition='ALLOWLISTED',
        allowlist_id='mega2_schwab_stream_l1',
        justification='Schwab LEVEL_ONE/stream book fields ingested via streaming adapter (_book_imbalance_from_totals).',
    ),
    Row(
        file='order_flow_engine.py', derivation='_book_pressure_curve', disposition='ALLOWLISTED',
        allowlist_id='mega2_schwab_stream_l1',
        justification='Schwab LEVEL_ONE/stream book fields ingested via streaming adapter (_book_pressure_curve).',
    ),
    Row(
        file='order_flow_engine.py', derivation='_book_side_depth_total', disposition='ALLOWLISTED',
        allowlist_id='mega2_schwab_stream_l1',
        justification='Schwab LEVEL_ONE/stream book fields ingested via streaming adapter (_book_side_depth_total).',
    ),
    Row(
        file='order_flow_engine.py', derivation='_book_slope', disposition='ALLOWLISTED',
        allowlist_id='mega2_schwab_stream_l1',
        justification='Schwab LEVEL_ONE/stream book fields ingested via streaming adapter (_book_slope).',
    ),
    Row(
        file='order_flow_engine.py', derivation='_book_wall_candidates', disposition='ALLOWLISTED',
        allowlist_id='mega2_schwab_stream_l1',
        justification='Schwab LEVEL_ONE/stream book fields ingested via streaming adapter (_book_wall_candidates).',
    ),
    Row(
        file='order_flow_engine.py', derivation='_compute_book_imbalance', disposition='ALLOWLISTED',
        allowlist_id='mega2_schwab_stream_l1',
        justification='Schwab LEVEL_ONE/stream book fields ingested via streaming adapter (_compute_book_imbalance).',
    ),
    Row(
        file='order_flow_engine.py', derivation='_compute_cum_delta_proxy', disposition='ALLOWLISTED',
        allowlist_id='mega2_schwab_stream_l1',
        justification='Schwab LEVEL_ONE/stream book fields ingested via streaming adapter (_compute_cum_delta_proxy).',
    ),
    Row(
        file='order_flow_engine.py', derivation='_compute_cum_delta_slope', disposition='ALLOWLISTED',
        allowlist_id='mega2_schwab_stream_l1',
        justification='Schwab LEVEL_ONE/stream book fields ingested via streaming adapter (_compute_cum_delta_slope).',
    ),
    Row(
        file='order_flow_engine.py', derivation='_compute_institutional_flow_proxy', disposition='ALLOWLISTED',
        allowlist_id='mega2_schwab_stream_l1',
        justification='Schwab LEVEL_ONE/stream book fields ingested via streaming adapter (_compute_institutional_flow_proxy).',
    ),
    Row(
        file='order_flow_engine.py', derivation='_compute_options_flow', disposition='DERIVED',
        producer_refs=('order_flow_engine.py:_iter_option_exp_levels', 'order_flow_engine.py:_option_contract_volume'),
        justification='Options flow from chain/stream maps.',
    ),
    Row(
        file='order_flow_engine.py', derivation='_compute_rvol', disposition='ALLOWLISTED',
        allowlist_id='mega2_schwab_stream_l1',
        justification='Schwab LEVEL_ONE/stream book fields ingested via streaming adapter (_compute_rvol).',
    ),
    Row(
        file='order_flow_engine.py', derivation='_compute_spread', disposition='DERIVED',
        producer_refs=('order_flow_engine.py:_resolve_quote_mark',),
        justification='Schwab LEVEL_ONE/stream book fields ingested via streaming adapter (_compute_spread).',
    ),
    Row(
        file='order_flow_engine.py', derivation='_compute_tape_pressure', disposition='ALLOWLISTED',
        allowlist_id='mega2_schwab_stream_l1',
        justification='Schwab LEVEL_ONE/stream book fields ingested via streaming adapter (_compute_tape_pressure).',
    ),
    Row(
        file='order_flow_engine.py', derivation='_compute_top_book_pressure', disposition='ALLOWLISTED',
        allowlist_id='mega2_schwab_stream_l1',
        justification='Schwab LEVEL_ONE/stream book fields ingested via streaming adapter (_compute_top_book_pressure).',
    ),
    Row(
        file='order_flow_engine.py', derivation='_earliest_book_snapshot', disposition='ALLOWLISTED',
        allowlist_id='mega2_schwab_stream_l1',
        justification='Schwab LEVEL_ONE/stream book fields ingested via streaming adapter (_earliest_book_snapshot).',
    ),
    Row(
        file='order_flow_engine.py', derivation='_extract_canonical_book', disposition='ALLOWLISTED',
        allowlist_id='mega2_schwab_stream_l1',
        justification='Schwab LEVEL_ONE/stream book fields ingested via streaming adapter (_extract_canonical_book).',
    ),
    Row(
        file='order_flow_engine.py', derivation='_get_nested', disposition='ALLOWLISTED',
        allowlist_id='mega2_schwab_stream_l1',
        justification='Schwab LEVEL_ONE/stream book fields ingested via streaming adapter (_get_nested).',
    ),
    Row(
        file='order_flow_engine.py', derivation='_iter_asks_levels', disposition='ALLOWLISTED',
        allowlist_id='mega2_schwab_stream_l1',
        justification='Schwab LEVEL_ONE/stream book fields ingested via streaming adapter (_iter_asks_levels).',
    ),
    Row(
        file='order_flow_engine.py', derivation='_iter_bids_levels', disposition='ALLOWLISTED',
        allowlist_id='mega2_schwab_stream_l1',
        justification='Schwab LEVEL_ONE/stream book fields ingested via streaming adapter (_iter_bids_levels).',
    ),
    Row(
        file='order_flow_engine.py', derivation='_iter_content', disposition='ALLOWLISTED',
        allowlist_id='mega2_schwab_stream_l1',
        justification='Schwab LEVEL_ONE/stream book fields ingested via streaming adapter (_iter_content).',
    ),
    Row(
        file='order_flow_engine.py', derivation='_iter_option_exp_levels', disposition='ALLOWLISTED',
        allowlist_id='mega2_schwab_stream_l1',
        justification='Schwab LEVEL_ONE/stream book fields ingested via streaming adapter (_iter_option_exp_levels).',
    ),
    Row(
        file='order_flow_engine.py', derivation='_iter_tape_prints', disposition='ALLOWLISTED',
        allowlist_id='mega2_schwab_stream_l1',
        justification='Schwab LEVEL_ONE/stream book fields ingested via streaming adapter (_iter_tape_prints).',
    ),
    Row(
        file='order_flow_engine.py', derivation='_latest_book_snapshot', disposition='ALLOWLISTED',
        allowlist_id='mega2_schwab_stream_l1',
        justification='Schwab LEVEL_ONE/stream book fields ingested via streaming adapter (_latest_book_snapshot).',
    ),
    Row(
        file='order_flow_engine.py', derivation='_latest_content_field', disposition='ALLOWLISTED',
        allowlist_id='mega2_schwab_stream_l1',
        justification='PR214 Gap 1: the ONE freshness-aware per-field resolver over Schwab LEVELONE_OPTIONS/EQUITIES partial/delta content items (_latest_content_field).',
    ),
    Row(
        file='order_flow_engine.py', derivation='_latest_quote_snapshot', disposition='ALLOWLISTED',
        allowlist_id='mega2_schwab_stream_l1',
        justification='Schwab LEVEL_ONE/stream book fields ingested via streaming adapter (_latest_quote_snapshot).',
    ),
    Row(
        file='order_flow_engine.py', derivation='_microprice', disposition='ALLOWLISTED',
        allowlist_id='mega2_schwab_stream_l1',
        justification='Schwab LEVEL_ONE/stream book fields ingested via streaming adapter (_microprice).',
    ),
    Row(
        file='order_flow_engine.py', derivation='_microstructure_structural', disposition='DERIVED',
        producer_refs=('order_flow_engine.py:_book_side_depth_total', 'order_flow_engine.py:_microprice', 'order_flow_engine.py:_book_wall_candidates'),
        justification='Structural book microstructure: depth totals, imbalance, microprice, slope, concentration and wall candidates from one canonical book snapshot.',
    ),
    Row(
        file='order_flow_engine.py', derivation='_mock_data', disposition='ALLOWLISTED',
        allowlist_id='mega2_test_fixture',
        justification='Order-flow metric from Schwab stream/quote fields.',
    ),
    Row(
        file='order_flow_engine.py', derivation='_nonnegative_float', disposition='ALLOWLISTED',
        allowlist_id='mega2_schwab_stream_l1',
        justification='Schwab LEVEL_ONE/stream book fields ingested via streaming adapter (_nonnegative_float).',
    ),
    Row(
        file='order_flow_engine.py', derivation='_normalize', disposition='ALLOWLISTED',
        allowlist_id='mega2_schwab_stream_l1',
        justification='Schwab LEVEL_ONE/stream book fields ingested via streaming adapter (_normalize).',
    ),
    Row(
        file='order_flow_engine.py', derivation='_option_contract_volume', disposition='ALLOWLISTED',
        allowlist_id='mega2_schwab_stream_l1',
        justification='Schwab LEVEL_ONE/stream book fields ingested via streaming adapter (_option_contract_volume).',
    ),
    Row(
        file='order_flow_engine.py', derivation='_resolve_bid_ask_prices', disposition='ALLOWLISTED',
        allowlist_id='mega2_schwab_stream_l1',
        justification='Schwab LEVEL_ONE/stream book fields ingested via streaming adapter (_resolve_bid_ask_prices).',
    ),
    Row(
        file='order_flow_engine.py', derivation='_resolve_quote_mark', disposition='ALLOWLISTED',
        allowlist_id='mega2_schwab_stream_l1',
        justification='Schwab LEVEL_ONE/stream book fields ingested via streaming adapter (_resolve_quote_mark).',
    ),
    Row(
        file='order_flow_engine.py', derivation='_safe_float', disposition='ALLOWLISTED',
        allowlist_id='mega2_schwab_stream_l1',
        justification='Schwab LEVEL_ONE/stream book fields ingested via streaming adapter (_safe_float).',
    ),
    Row(
        file='order_flow_engine.py', derivation='_safe_int', disposition='ALLOWLISTED',
        allowlist_id='mega2_schwab_stream_l1',
        justification='Schwab LEVEL_ONE/stream book fields ingested via streaming adapter (_safe_int).',
    ),
    Row(
        file='order_flow_engine.py', derivation='_sorted_valid_levels', disposition='ALLOWLISTED',
        allowlist_id='mega2_schwab_stream_l1',
        justification='Schwab LEVEL_ONE/stream book fields ingested via streaming adapter (_sorted_valid_levels).',
    ),
    Row(
        file='order_flow_engine.py', derivation='_weighted_mean_present', disposition='DERIVED',
        producer_refs=('order_flow_engine.py:OrderFlowEngine.compute',),
        justification='Composite mean over present legs only — derives order_flow composite from Schwab-derived inputs (_weighted_mean_present).',
    ),
    Row(
        file='order_flow_engine.py', derivation='compute_book_microstructure', disposition='DERIVED',
        producer_refs=('order_flow_engine.py:_extract_canonical_book', 'order_flow_engine.py:_microstructure_structural'),
        justification='Canonical book microstructure producer: extracts the book once, carries structural state per book identity, stamps ages; the API route serializes it.',
    ),
    Row(
        file='order_flow_live_state.py', derivation='_get_book', disposition='ALLOWLISTED',
        allowlist_id='mega2_schwab_stream_l1',
        justification='Schwab LEVEL_ONE/stream book fields ingested via streaming adapter (_get_book).',
    ),
    Row(
        file='order_flow_live_state.py', derivation='_get_tape', disposition='ALLOWLISTED',
        allowlist_id='mega2_schwab_stream_l1',
        justification='Schwab LEVEL_ONE/stream book fields ingested via streaming adapter (_get_tape).',
    ),
    Row(
        file='order_flow_live_state.py', derivation='clear_all_live_state', disposition='ALLOWLISTED',
        allowlist_id='mega2_schwab_stream_l1',
        justification='Clears tape/book/top/prev-print identity on disconnect/reconnect so prior-session restatements cannot bind the new session.',
    ),
    Row(
        file='order_flow_live_state.py', derivation='clear_symbol', disposition='ALLOWLISTED',
        allowlist_id='mega2_schwab_stream_l1',
        justification='Schwab LEVEL_ONE/stream book fields ingested via streaming adapter (clear_symbol).',
    ),
    Row(
        file='order_flow_live_state.py', derivation='forget_unsubscribed_symbols', disposition='ALLOWLISTED',
        allowlist_id='mega2_schwab_stream_l1',
        justification='Clears live state for symbols leaving the active LEVELONE subscription set.',
    ),
    Row(
        file='order_flow_live_state.py', derivation='get_content_for_symbol', disposition='DERIVED',
        producer_refs=('order_flow_live_state.py:push_level_one', 'order_flow_live_state.py:push_book'),
        justification='Schwab LEVEL_ONE/stream book fields ingested via streaming adapter (get_content_for_symbol).',
    ),
    Row(
        file='order_flow_live_state.py', derivation='get_l1_stream_input_probe', disposition='ALLOWLISTED',
        allowlist_id='mega1_l1_sse_counters',
        justification='Schwab LEVEL_ONE/stream book fields ingested via streaming adapter (get_l1_stream_input_probe).',
    ),
    Row(
        file='order_flow_live_state.py', derivation='get_stats', disposition='ALLOWLISTED',
        allowlist_id='mega2_schwab_stream_l1',
        justification='Schwab LEVEL_ONE/stream book fields ingested via streaming adapter (get_stats).',
    ),
    Row(
        file='order_flow_live_state.py', derivation='get_stream_chg_pct', disposition='ALLOWLISTED',
        allowlist_id='mega2_schwab_stream_l1',
        justification='Schwab LEVEL_ONE/stream book fields ingested via streaming adapter (get_stream_chg_pct).',
    ),
    Row(
        file='order_flow_live_state.py', derivation='get_stream_volume', disposition='ALLOWLISTED',
        allowlist_id='mega2_schwab_stream_l1',
        justification='Schwab LEVEL_ONE/stream book fields ingested via streaming adapter (get_stream_volume).',
    ),
    Row(
        file='order_flow_live_state.py', derivation='get_top_of_book_sizes', disposition='ALLOWLISTED',
        allowlist_id='mega2_schwab_stream_l1',
        justification='Schwab LEVEL_ONE/stream book fields ingested via streaming adapter (get_top_of_book_sizes).',
    ),
    Row(
        file='order_flow_live_state.py', derivation='is_rth_open', disposition='ALLOWLISTED',
        allowlist_id='mega1_session_calendar',
        justification='No Schwab market-field derivation in function body.',
    ),
    Row(
        file='order_flow_live_state.py', derivation='push_book', disposition='ALLOWLISTED',
        allowlist_id='mega2_schwab_stream_l1',
        justification='Schwab LEVEL_ONE/stream book fields ingested via streaming adapter (push_book).',
    ),
    Row(
        file='order_flow_live_state.py', derivation='push_level_one', disposition='ALLOWLISTED',
        allowlist_id='mega2_schwab_stream_l1',
        justification='Schwab LEVEL_ONE/stream book fields ingested via streaming adapter (push_level_one).',
    ),
    Row(
        file='order_flow_streaming.py', derivation='_feed_loop', disposition='ALLOWLISTED',
        allowlist_id='mega2_schwab_stream_l1',
        justification='Poll loop replacing the retired StreamClient message loop; opens zero Schwab connections (_feed_loop).',
    ),
    Row(
        file='order_flow_streaming.py', derivation='_log_stream', disposition='ALLOWLISTED',
        allowlist_id='mega2_schwab_stream_l1',
        justification='Schwab LEVEL_ONE/stream book fields ingested via streaming adapter (_log_stream).',
    ),
    Row(
        file='order_flow_streaming.py', derivation='_open_capture_db_readonly', disposition='ALLOWLISTED',
        allowlist_id='mega2_schwab_stream_l1',
        justification='SINGLE-STREAM-AUTHORITY repair 2026-08-30: read-only capture-DB handle for the live-plane feed, replacing the retired second StreamClient (_open_capture_db_readonly).',
    ),
    Row(
        file='order_flow_streaming.py', derivation='_option_streaming_healthy', disposition='ALLOWLISTED',
        allowlist_id='mega2_schwab_stream_l1',
        justification='FRESHNESS/HEALTH 2026-08-30: same feed-connection health gate as _streaming_healthy, mirrored for the independent option-contract slot (_option_streaming_healthy).',
    ),
    Row(
        file='order_flow_streaming.py', derivation='_read_daemon_upstream_health', disposition='ALLOWLISTED',
        allowlist_id='mega1_diagnostic_log',
        justification="FRESHNESS/HEALTH SEMANTIC AUDIT 2026-08-30: reads the canonical daemon's own status file (stream_spine.HealthRegistry via tools/run_stream_capture.py's write_status) for the REAL per-service Schwab-socket truth, distinct from this module's local-replay-proxy streaming_healthy (_read_daemon_upstream_health).",
    ),
    Row(
        file='order_flow_streaming.py', derivation='_read_producer_option_contracts', disposition='ALLOWLISTED',
        allowlist_id='mega1_diagnostic_log',
        justification="PR214 premerge gap 1A: PRODUCER-side option subscription identity -- the current OPEN coverage epoch symbol per Schwab option service, read from the canonical stream_capture.db, distinct from the server's DESIRED/requested contract (_read_producer_option_contracts).",
    ),
    Row(
        file='order_flow_streaming.py', derivation='_replay_new_rows', disposition='ALLOWLISTED',
        allowlist_id='mega2_schwab_stream_l1',
        justification='Replays daemon-captured L1/book rows into order_flow_live_state/live_market_plane, the same plane-ingest calls the retired direct-socket handlers made (_replay_new_rows).',
    ),
    Row(
        file='order_flow_streaming.py', derivation='_replay_option_contract_rows', disposition='ALLOWLISTED',
        allowlist_id='mega2_schwab_stream_l1',
        justification="Same replay shape as _replay_new_rows for the one active option contract's LEVELONE_OPTIONS/OPTIONS_BOOK rows (_replay_option_contract_rows).",
    ),
    Row(
        file='order_flow_streaming.py', derivation='_stream_db_identity_status', disposition='ALLOWLISTED',
        allowlist_id='mega1_diagnostic_log',
        justification="PR214 Gap 2: producer identity via the shared data plane -- reads the daemon's stream_producer_heartbeat row through this process's own resolved stream_capture.db connection, proving identity structurally rather than by comparing two independently-resolved path strings (_stream_db_identity_status).",
    ),
    Row(
        file='order_flow_streaming.py', derivation='_streaming_healthy', disposition='ALLOWLISTED',
        allowlist_id='mega2_schwab_stream_l1',
        justification='Schwab LEVEL_ONE/stream book fields ingested via streaming adapter (_streaming_healthy).',
    ),
    Row(
        file='order_flow_streaming.py', derivation='get_option_contract_book_microstructure', disposition='DERIVED',
        producer_refs=('order_flow_engine.py:compute_book_microstructure',),
        justification="Order-flow semantic product for one option contract's live book — delegates to the SAME producer the equity route reads, never a second book-imbalance computation (get_option_contract_book_microstructure).",
    ),
    Row(
        file='order_flow_streaming.py', derivation='get_option_contract_streaming_diagnostics', disposition='ALLOWLISTED',
        allowlist_id='mega1_diagnostic_log',
        justification='FRESHNESS/HEALTH 2026-08-30: same diagnostics shape as get_streaming_diagnostics, mirrored for the independent option-contract slot (get_option_contract_streaming_diagnostics).',
    ),
    Row(
        file='order_flow_streaming.py', derivation='get_plane_authority_for_ticker', disposition='ALLOWLISTED',
        allowlist_id='mega2_schwab_stream_l1',
        justification='Schwab LEVEL_ONE/stream book fields ingested via streaming adapter (get_plane_authority_for_ticker).',
    ),
    Row(
        file='order_flow_streaming.py', derivation='get_stream_thread', disposition='ALLOWLISTED',
        allowlist_id='mega2_schwab_stream_l1',
        justification='Schwab LEVEL_ONE/stream book fields ingested via streaming adapter (get_stream_thread).',
    ),
    Row(
        file='order_flow_streaming.py', derivation='get_streaming_diagnostics', disposition='ALLOWLISTED',
        allowlist_id='mega1_diagnostic_log',
        justification='Schwab LEVEL_ONE/stream book fields ingested via streaming adapter (get_streaming_diagnostics).',
    ),
    Row(
        file='order_flow_streaming.py', derivation='is_order_flow_stream_running', disposition='ALLOWLISTED',
        allowlist_id='mega2_schwab_stream_l1',
        justification='Schwab LEVEL_ONE/stream book fields ingested via streaming adapter (is_order_flow_stream_running).',
    ),
    Row(
        file='order_flow_streaming.py', derivation='set_active_option_contract', disposition='ALLOWLISTED',
        allowlist_id='mega2_schwab_stream_l1',
        justification='Requests LEVELONE_OPTIONS/OPTIONS_BOOK for one option contract via the daemon signal file (set_active_option_contract).',
    ),
    Row(
        file='order_flow_streaming.py', derivation='set_streaming_active_ticker', disposition='ALLOWLISTED',
        allowlist_id='mega2_schwab_stream_l1',
        justification='Schwab LEVEL_ONE/stream book fields ingested via streaming adapter (set_streaming_active_ticker).',
    ),
    Row(
        file='order_flow_streaming.py', derivation='start_order_flow_stream', disposition='DERIVED',
        producer_refs=('order_flow_live_state.py:get_content_for_symbol',),
        justification='Delegates to Schwab transport producers for start_order_flow_stream.',
    ),
    Row(
        file='order_flow_streaming.py', derivation='stop_order_flow_stream', disposition='ALLOWLISTED',
        allowlist_id='mega2_schwab_stream_l1',
        justification='Schwab LEVEL_ONE/stream book fields ingested via streaming adapter (stop_order_flow_stream).',
    ),
    Row(
        file='order_flow_streaming.py', derivation='streaming_l1_cache_usable', disposition='ALLOWLISTED',
        allowlist_id='mega2_schwab_stream_l1',
        justification='Fast-quote gate: plane row fresh within FAST_QUOTE_STREAM_CACHE_MAX_AGE_MS (streaming_l1_cache_usable).',
    ),
    Row(
        file='polling_adapter.py', derivation='_prev_trading_day', disposition='ALLOWLISTED',
        allowlist_id='mega1_session_calendar',
        justification='Calendar helper for session window; no Schwab leaf.',
    ),
    Row(
        file='polling_adapter.py', derivation='fetch_bars_via_schwab', disposition='SCHWAB_LEAF',
        schwab_leaf='pricehistory.candles.*.datetime',
        justification='Day-period pricehistory → schwab_candles_to_bars.',
    ),
    Row(
        file='polling_adapter.py', derivation='fetch_bars_via_schwab_for_session', disposition='SCHWAB_LEAF',
        schwab_leaf='pricehistory.candles.*.datetime',
        justification='Session-bounded pricehistory → schwab_candles_to_bars.',
    ),
    Row(
        file='polling_adapter.py', derivation='poll_and_callback', disposition='SCHWAB_LEAF',
        schwab_leaf='pricehistory.candles.*.datetime',
        justification='Poll loop delegates to fetch_bars_via_schwab.',
    ),
    Row(
        file='regime_engine.py', derivation='_micro_regimes', disposition='DERIVED',
        producer_refs=('market_state.py:build_market_state',),
        justification='Composes Mega1 producers for _micro_regimes output fields.',
    ),
    Row(
        file='regime_engine.py', derivation='_score_acceleration', disposition='DERIVED',
        producer_refs=('market_state.py:build_market_state',),
        justification='Composes Mega1 producers for _score_acceleration output fields.',
    ),
    Row(
        file='regime_engine.py', derivation='_score_breakout', disposition='DERIVED',
        producer_refs=('market_state.py:build_market_state',),
        justification='Composes Mega1 producers for _score_breakout output fields.',
    ),
    Row(
        file='regime_engine.py', derivation='_score_mean_reversion', disposition='DERIVED',
        producer_refs=('market_state.py:build_market_state',),
        justification='Composes Mega1 producers for _score_mean_reversion output fields.',
    ),
    Row(
        file='regime_engine.py', derivation='_score_pinning', disposition='DERIVED',
        producer_refs=('market_state.py:build_market_state',),
        justification='Composes Mega1 producers for _score_pinning output fields.',
    ),
    Row(
        file='regime_engine.py', derivation='_score_reversal_prone', disposition='DERIVED',
        producer_refs=('market_state.py:build_market_state',),
        justification='Composes Mega1 producers for _score_reversal_prone output fields.',
    ),
    Row(
        file='regime_engine.py', derivation='_score_trend_continuation', disposition='DERIVED',
        producer_refs=('market_state.py:build_market_state',),
        justification='Composes Mega1 producers for _score_trend_continuation output fields.',
    ),
    Row(
        file='regime_engine.py', derivation='_score_vol_compression', disposition='DERIVED',
        producer_refs=('market_state.py:build_market_state',),
        justification='Composes Mega1 producers for _score_vol_compression output fields.',
    ),
    Row(
        file='regime_engine.py', derivation='_score_vol_expansion', disposition='DERIVED',
        producer_refs=('market_state.py:build_market_state',),
        justification='Composes Mega1 producers for _score_vol_expansion output fields.',
    ),
    Row(
        file='regime_engine.py', derivation='_unknown_regime', disposition='DERIVED',
        producer_refs=('market_state.py:build_market_state',),
        justification='Composes Mega1 producers for _unknown_regime output fields.',
    ),
    Row(
        file='regime_engine.py', derivation='classify_regime', disposition='DERIVED',
        producer_refs=('market_state.py:build_market_state',),
        justification='8-family regime from upstream levels/greeks/zone.',
    ),
    Row(
        file='schwab_client.py', derivation='build_client_from_token', disposition='ALLOWLISTED',
        allowlist_id='mega1_schwab_py_client',
        justification='Constructs schwab-py client from token file.',
    ),
    Row(
        file='schwab_client.py', derivation='safe_get_chain', disposition='SCHWAB_LEAF',
        schwab_leaf='chains.callExpDateMap.*.openInterest',
        justification='Schwab option chain wrapper.',
    ),
    Row(
        file='schwab_client.py', derivation='safe_get_daily_price_history', disposition='SCHWAB_LEAF',
        schwab_leaf='pricehistory.candles.*.datetime',
        justification='Schwab DAILY price history wrapper (RC-484 radar fallback); candles passed downstream.',
    ),
    Row(
        file='schwab_client.py', derivation='safe_get_price_history', disposition='SCHWAB_LEAF',
        schwab_leaf='pricehistory.candles.*.datetime',
        justification='Schwab price history wrapper; candles passed downstream.',
    ),
    Row(
        file='schwab_client.py', derivation='safe_get_quote', disposition='SCHWAB_LEAF',
        schwab_leaf='quotes.quote.lastPrice',
        justification='Schwab get_quote wrapper; returns raw quote JSON.',
    ),
    Row(
        file='server.py', derivation='_CandleAccumulator.__init__', disposition='ALLOWLISTED',
        allowlist_id='mega1_sqlite_internal',
        justification='Reads persisted snapshot SQLite rows, not Schwab wire JSON (_CandleAccumulator.__init__).',
    ),
    Row(
        file='server.py', derivation='_CandleAccumulator.get_bars', disposition='ALLOWLISTED',
        allowlist_id='mega1_sqlite_internal',
        justification='Reads persisted snapshot SQLite rows, not Schwab wire JSON (_CandleAccumulator.get_bars).',
    ),
    Row(
        file='server.py', derivation='_CandleAccumulator.get_bars_source', disposition='DERIVED',
        producer_refs=('server.py:_fetch_state',),
        justification='Bar provenance label for VWAP path.',
    ),
    Row(
        file='server.py', derivation='_CandleAccumulator.seed', disposition='SCHWAB_LEAF',
        schwab_leaf='pricehistory.candles.*.datetime',
        justification='Seeds from Schwab pricehistory candles; datetime required.',
    ),
    Row(
        file='server.py', derivation='_CandleAccumulator.tick', disposition='DERIVED',
        producer_refs=('server.py:_CandleAccumulator.seed', 'schwab_client.py:safe_get_quote'),
        justification='Poll-synthesized OHLCV from spot ticks + totalVolume delta.',
    ),
    Row(
        file='server.py', derivation='_VIXTracker.vs_prev', disposition='ALLOWLISTED',
        allowlist_id='mega1_sqlite_internal',
        justification='Reads persisted snapshot SQLite rows, not Schwab wire JSON (_VIXTracker.vs_prev).',
    ),
    Row(
        file='server.py', derivation='_accrue_chain_observation', disposition='ALLOWLISTED',
        allowlist_id='mega1_sqlite_internal',
        justification='Banks one wide-chain per-strike observation into option_chain_accrual and never raises into the producer; the per-strike values are already derived upstream.',
    ),
    Row(
        file='server.py', derivation='_app_lifespan', disposition='ALLOWLISTED',
        allowlist_id='mega1_sqlite_internal',
        justification='Reads persisted snapshot SQLite rows, not Schwab wire JSON (_app_lifespan).',
    ),
    Row(
        file='server.py', derivation='_attach_stack_runtime_and_governance', disposition='ALLOWLISTED',
        allowlist_id='mega1_sqlite_internal',
        justification='Reads persisted snapshot SQLite rows, not Schwab wire JSON (_attach_stack_runtime_and_governance).',
    ),
    Row(
        file='server.py', derivation='_bars_collect_one', disposition='DERIVED',
        producer_refs=('server.py:_memoized_quote_response', 'server.py:_parse_quote_node_session_fields'),
        justification='Quote to accumulator to price_bars_1m for ONE ticker, never raising. The price comes from the parsed session fields through numeric_contract.float_positive_or_none, so an absent, zero, negative, NaN or infinite price returns skip:no_price and the accumulator is never ticked — absence reads as absence, never a fabricated bar (RC-38/RC-308).',
    ),
    Row(
        file='server.py', derivation='_broadcast_live_quote_sse_payloads', disposition='ALLOWLISTED',
        allowlist_id='mega1_sqlite_internal',
        justification='Reads persisted snapshot SQLite rows, not Schwab wire JSON (_broadcast_live_quote_sse_payloads).',
    ),
    Row(
        file='server.py', derivation='_build_raw_levels_used', disposition='ALLOWLISTED',
        allowlist_id='mega1_sqlite_internal',
        justification='Reads persisted snapshot SQLite rows, not Schwab wire JSON (_build_raw_levels_used).',
    ),
    Row(
        file='server.py', derivation='_build_rest_fast_quote_payload', disposition='DERIVED',
        producer_refs=('schwab_client.py:safe_get_quote',),
        justification='Fail-closed Schwab leaf read: quotes.quote.mark.',
    ),
    Row(
        file='server.py', derivation='_canonical_price_level_bars', disposition='ALLOWLISTED',
        allowlist_id='mega1_sqlite_internal',
        justification='Phase 2A: resolves the ONE bar input for the canonical snapshot (live accumulator, else banked price_bars_1m); no direct Schwab read.',
    ),
    Row(
        file='server.py', derivation='_charm_book_scope', disposition='SCHWAB_LEAF',
        schwab_leaf='chains.*.expirationDate',
        justification="RC-288: counts the DISTINCT expirations in the contracts actually summed and reports single_expiry_banked:<date>, full_chain_banked, or unknown. It replaced a hardcoded literal that matched the client's own fallback, so the label could never disagree with itself. An empty or unreadable chain yields unknown, never a confident book for a chain nobody looked at.",
    ),
    Row(
        file='server.py', derivation='_enrollment_history_seed', disposition='DERIVED',
        producer_refs=('schwab_client.py:safe_get_price_history',),
        justification='RC-484 day-1 history seed: delegates to Schwab price-history transport (period_days=2) and persists via _persist_1m_bars; no leaf extracted here.',
    ),
    Row(
        file='server.py', derivation='_fetch_and_store_mkt_ctx', disposition='DERIVED',
        producer_refs=('market_context.py:fetch_market_context',),
        justification='Market-context sweep + cache store + confluence-tick persist, extracted verbatim from _get_mkt_ctx; Schwab quote reads unchanged inside fetch_market_context.',
    ),
    Row(
        file='server.py', derivation='_fetch_expiries_light', disposition='DERIVED',
        producer_refs=('schwab_client.py:safe_get_chain',),
        justification='Schwab API wrapper or wire JSON ingest path.',
    ),
    Row(
        file='server.py', derivation='_fetch_fast_quote_payload', disposition='ALLOWLISTED',
        allowlist_id='mega1_sqlite_internal',
        justification='Reads persisted snapshot SQLite rows, not Schwab wire JSON (_fetch_fast_quote_payload).',
    ),
    Row(
        file='server.py', derivation='_fetch_state', disposition='DERIVED',
        producer_refs=('schwab_client.py:safe_get_quote', 'schwab_client.py:safe_get_chain', 'schwab_client.py:safe_get_price_history'),
        justification='Day 1.5: spread_frac mark-denom only; composes quote+chain+pricehistory via schwab_client.',
    ),
    Row(
        file='server.py', derivation='_fetch_state._post_publish_persistence_tail', disposition='ALLOWLISTED',
        allowlist_id='mega1_sqlite_internal',
        justification='Relocated persistence/telemetry tail (FIX_B_PUBLISH_BEFORE_LOG_REORDER_V1): snapshot INSERT + bars/outcomes + accuracy scans + calibration append, moved verbatim to run after the generated_at-stamping publish; writes persisted SQLite rows, no new Schwab wire read.',
    ),
    Row(
        file='server.py', derivation='_filter_contracts_by_selected_expiry', disposition='ALLOWLISTED',
        allowlist_id='mega1_sqlite_internal',
        justification='Reads persisted snapshot SQLite rows, not Schwab wire JSON (_filter_contracts_by_selected_expiry).',
    ),
    Row(
        file='server.py', derivation='_gated_safe_get_chain', disposition='DERIVED',
        producer_refs=('schwab_client.py:safe_get_chain',),
        justification='Schwab get_chain wrapper serialized behind the chain-fetch gate; call shape unchanged, fail-open on gate timeout.',
    ),
    Row(
        file='server.py', derivation='_get_fast_quote_executor', disposition='ALLOWLISTED',
        allowlist_id='mega1_sqlite_internal',
        justification='Reads persisted snapshot SQLite rows, not Schwab wire JSON (_get_fast_quote_executor).',
    ),
    Row(
        file='server.py', derivation='_get_mkt_ctx', disposition='DERIVED',
        producer_refs=('market_context.py:fetch_market_context',),
        justification='Schwab API wrapper or wire JSON ingest path.',
    ),
    Row(
        file='server.py', derivation='_hydrate_logger_tickers_from_db', disposition='ALLOWLISTED',
        allowlist_id='mega1_sqlite_internal',
        justification='Reads persisted snapshot SQLite rows, not Schwab wire JSON (_hydrate_logger_tickers_from_db).',
    ),
    Row(
        file='server.py', derivation='_is_loggable_session', disposition='ALLOWLISTED',
        allowlist_id='mega1_sqlite_internal',
        justification='Reads persisted snapshot SQLite rows, not Schwab wire JSON (_is_loggable_session).',
    ),
    Row(
        file='server.py', derivation='_kl_expiry_source_label', disposition='ALLOWLISTED',
        allowlist_id='mega1_sqlite_internal',
        justification='Reads persisted snapshot SQLite rows, not Schwab wire JSON (_kl_expiry_source_label).',
    ),
    Row(
        file='server.py', derivation='_l1_adaptive_materiality_context', disposition='ALLOWLISTED',
        allowlist_id='mega1_sqlite_internal',
        justification='Reads persisted snapshot SQLite rows, not Schwab wire JSON (_l1_adaptive_materiality_context).',
    ),
    Row(
        file='server.py', derivation='_l1_attach_freshness_semantics', disposition='ALLOWLISTED',
        allowlist_id='mega1_sqlite_internal',
        justification='Reads persisted snapshot SQLite rows, not Schwab wire JSON (_l1_attach_freshness_semantics).',
    ),
    Row(
        file='server.py', derivation='_l1_http_get_projection', disposition='ALLOWLISTED',
        allowlist_id='mega1_sqlite_internal',
        justification='Reads persisted snapshot SQLite rows, not Schwab wire JSON (_l1_http_get_projection).',
    ),
    Row(
        file='server.py', derivation='_l1_maybe_rebuild_quote_scope', disposition='ALLOWLISTED',
        allowlist_id='mega1_sqlite_internal',
        justification='Reads persisted snapshot SQLite rows, not Schwab wire JSON (_l1_maybe_rebuild_quote_scope).',
    ),
    Row(
        file='server.py', derivation='_l1_next_generation', disposition='ALLOWLISTED',
        allowlist_id='mega1_sqlite_internal',
        justification='Reads persisted snapshot SQLite rows, not Schwab wire JSON (_l1_next_generation).',
    ),
    Row(
        file='server.py', derivation='_l1_on_quote_updated', disposition='ALLOWLISTED',
        allowlist_id='mega1_sqlite_internal',
        justification='Reads persisted snapshot SQLite rows, not Schwab wire JSON (_l1_on_quote_updated).',
    ),
    Row(
        file='server.py', derivation='_l1_quote_hook_order_flow_signature', disposition='ALLOWLISTED',
        allowlist_id='mega1_sqlite_internal',
        justification='Reads persisted snapshot SQLite rows, not Schwab wire JSON (_l1_quote_hook_order_flow_signature).',
    ),
    Row(
        file='server.py', derivation='_l1_sync_of_probe_cache_from_authoritative_build', disposition='ALLOWLISTED',
        allowlist_id='mega1_sqlite_internal',
        justification='Reads persisted snapshot SQLite rows, not Schwab wire JSON (_l1_sync_of_probe_cache_from_authoritative_build).',
    ),
    Row(
        file='server.py', derivation='_l1_touch_scope', disposition='ALLOWLISTED',
        allowlist_id='mega1_sqlite_internal',
        justification='Reads persisted snapshot SQLite rows, not Schwab wire JSON (_l1_touch_scope).',
    ),
    Row(
        file='server.py', derivation='_latest_chain_and_spot', disposition='SCHWAB_LEAF',
        schwab_leaf='chains.callExpDateMap.*.openInterest',
        justification='Reads the most recent stored Schwab chain and spot for a ticker, read-only; no Schwab call, no derivation.',
    ),
    Row(
        file='server.py', derivation='_learn_strike_geometry', disposition='ALLOWLISTED',
        allowlist_id='mega1_sqlite_internal',
        justification='Caches (spot, strike increment) per ticker from a chain already fetched by the traced terrain path; no new Schwab field read.',
    ),
    Row(
        file='server.py', derivation='_liquidity_fusion_from_cache', disposition='ALLOWLISTED',
        allowlist_id='mega1_sqlite_internal',
        justification='Reads persisted snapshot SQLite rows, not Schwab wire JSON (_liquidity_fusion_from_cache).',
    ),
    Row(
        file='server.py', derivation='_liquidity_live_1m_overlay_bars', disposition='ALLOWLISTED',
        allowlist_id='mega1_sqlite_internal',
        justification='Reads persisted snapshot SQLite rows, not Schwab wire JSON (_liquidity_live_1m_overlay_bars).',
    ),
    Row(
        file='server.py', derivation='_liquidity_spot_from_cache_any_expiry', disposition='ALLOWLISTED',
        allowlist_id='mega1_sqlite_internal',
        justification='Reads persisted snapshot SQLite rows, not Schwab wire JSON (_liquidity_spot_from_cache_any_expiry).',
    ),
    Row(
        file='server.py', derivation='_liquidity_zone_tradeable_fields', disposition='ALLOWLISTED',
        allowlist_id='mega1_sqlite_internal',
        justification='Reads persisted snapshot SQLite rows, not Schwab wire JSON (_liquidity_zone_tradeable_fields).',
    ),
    Row(
        file='server.py', derivation='_load_persisted_tickers', disposition='ALLOWLISTED',
        allowlist_id='mega1_sqlite_internal',
        justification='Reads persisted snapshot SQLite rows, not Schwab wire JSON (_load_persisted_tickers).',
    ),
    Row(
        file='server.py', derivation='_log_schwab_startup_diagnostics', disposition='ALLOWLISTED',
        allowlist_id='mega1_sqlite_internal',
        justification='Reads persisted snapshot SQLite rows, not Schwab wire JSON (_log_schwab_startup_diagnostics).',
    ),
    Row(
        file='server.py', derivation='_logger_fetch_and_log', disposition='ALLOWLISTED',
        allowlist_id='mega1_sqlite_internal',
        justification='Reads persisted snapshot SQLite rows, not Schwab wire JSON (_logger_fetch_and_log).',
    ),
    Row(
        file='server.py', derivation='_logger_loop', disposition='ALLOWLISTED',
        allowlist_id='mega1_sqlite_internal',
        justification='Reads persisted snapshot SQLite rows, not Schwab wire JSON (_logger_loop).',
    ),
    Row(
        file='server.py', derivation='_market_context_panel_auto_candidates', disposition='ALLOWLISTED',
        allowlist_id='mega1_sqlite_internal',
        justification='Reads persisted snapshot SQLite rows, not Schwab wire JSON (_market_context_panel_auto_candidates).',
    ),
    Row(
        file='server.py', derivation='_memoized_quote_response', disposition='DERIVED',
        producer_refs=('server.py:_safe_get_quote_with_retry',),
        justification='The single Schwab quote read per ticker per TTL, shared by the fast lane and resolve_spot. Extracts NO leaf itself — it returns the vendor response object and only a 200 is memoised, so a failure is never cached and the next caller goes back to the vendor.',
    ),
    Row(
        file='server.py', derivation='_ms_to_dict', disposition='ALLOWLISTED',
        allowlist_id='mega1_sqlite_internal',
        justification='Reads persisted snapshot SQLite rows, not Schwab wire JSON (_ms_to_dict).',
    ),
    Row(
        file='server.py', derivation='_on_tick_broadcast_sync', disposition='ALLOWLISTED',
        allowlist_id='mega1_sqlite_internal',
        justification='Reads persisted snapshot SQLite rows, not Schwab wire JSON (_on_tick_broadcast_sync).',
    ),
    Row(
        file='server.py', derivation='_parse_quote_node_session_fields', disposition='DERIVED',
        producer_refs=('schwab_client.py:safe_get_quote',),
        justification='Canonical Schwab quote-node reader (quote → extended → regular fallbacks). Reads Schwab quote leaves (lastPrice / mark / bid / ask / quoteTime / tradeTime + extended + regular variants) and derives ``spot`` + ``spot_source`` via lastPrice/mark precedence.',
    ),
    Row(
        file='server.py', derivation='_project_l1', disposition='ALLOWLISTED',
        allowlist_id='mega1_sqlite_internal',
        justification='Reads persisted snapshot SQLite rows, not Schwab wire JSON (_project_l1).',
    ),
    Row(
        file='server.py', derivation='_radar_atr', disposition='DERIVED',
        producer_refs=('server.py:_radar_atr_compute_into_cache',),
        justification='Cache front for ATR: stale-while-revalidate; no direct Schwab read.',
    ),
    Row(
        file='server.py', derivation='_radar_atr_compute_into_cache', disposition='ALLOWLISTED',
        allowlist_id='mega1_sqlite_internal',
        justification='ATR from persisted price_bars_1m (traced collector output); single-flight cache fill.',
    ),
    Row(
        file='server.py', derivation='_radar_contact', disposition='DERIVED',
        producer_refs=('server.py:_radar_row',),
        justification='Ring classification from existing levels/ATR; thresholds are terrain_atr constants.',
    ),
    Row(
        file='server.py', derivation='_radar_daily_atr_vendor_fallback', disposition='DERIVED',
        producer_refs=('schwab_client.py:safe_get_daily_price_history',),
        justification='RC-484 radar fallback: daily ATR from Schwab DAILY candles when local 1m history spans <15 sessions; delegates to the daily transport wrapper.',
    ),
    Row(
        file='server.py', derivation='_radar_fallback_recompute', disposition='DERIVED',
        producer_refs=('server.py:_fetch_state',),
        justification='Heavy off-request radar sweep recomputed from cached terrain/analytics; no direct leaf read.',
    ),
    Row(
        file='server.py', derivation='_radar_row', disposition='DERIVED',
        producer_refs=('server.py:get_terrain_radar',),
        justification='Projects already-computed terrain fields + ATR distances into a radar row; no new field read.',
    ),
    Row(
        file='server.py', derivation='_reprice_cached_terrain', disposition='DERIVED',
        producer_refs=('server.py:resolve_spot',),
        justification='Re-evaluates cached gamma profile at the fresh authoritative spot (RC-28); both inputs from traced producers.',
    ),
    Row(
        file='server.py', derivation='_safe_float_quote', disposition='ALLOWLISTED',
        allowlist_id='mega1_sqlite_internal',
        justification='Reads persisted snapshot SQLite rows, not Schwab wire JSON (_safe_float_quote).',
    ),
    Row(
        file='server.py', derivation='_safe_get_quote_with_retry', disposition='DERIVED',
        producer_refs=('schwab_client.py:safe_get_quote',),
        justification='Schwab get_quote wrapper with token retry.',
    ),
    Row(
        file='server.py', derivation='_seed_strike_geometry_from_storage', disposition='DERIVED',
        producer_refs=('server.py:_latest_chain_and_spot',),
        justification='Replays stored chains through _learn_strike_geometry at boot; stored rows were produced by traced writers.',
    ),
    Row(
        file='server.py', derivation='_selected_schwab_days_to_expiration', disposition='ALLOWLISTED',
        allowlist_id='mega1_sqlite_internal',
        justification='Reads persisted snapshot SQLite rows, not Schwab wire JSON (_selected_schwab_days_to_expiration).',
    ),
    Row(
        file='server.py', derivation='_snapshot_expiry_hours_from_schwab_dte', disposition='ALLOWLISTED',
        allowlist_id='mega1_sqlite_internal',
        justification='Reads persisted snapshot SQLite rows, not Schwab wire JSON (_snapshot_expiry_hours_from_schwab_dte).',
    ),
    Row(
        file='server.py', derivation='_spot_from_quote', disposition='DERIVED',
        producer_refs=('schwab_client.py:safe_get_quote',),
        justification='Live-quote leg of the spot authority: delegates to Schwab transport, parses via the canonical quote-node parser.',
    ),
    Row(
        file='server.py', derivation='_spot_from_stored', disposition='ALLOWLISTED',
        allowlist_id='mega1_sqlite_internal',
        justification='Reads persisted snapshot SQLite rows, not Schwab wire JSON; lowest-precedence leg of the spot authority.',
    ),
    Row(
        file='server.py', derivation='_sse_background_loop', disposition='ALLOWLISTED',
        allowlist_id='mega1_sqlite_internal',
        justification='Reads persisted snapshot SQLite rows, not Schwab wire JSON (_sse_background_loop).',
    ),
    Row(
        file='server.py', derivation='_sse_live_quote_loop', disposition='ALLOWLISTED',
        allowlist_id='mega1_sqlite_internal',
        justification='Reads persisted snapshot SQLite rows, not Schwab wire JSON (_sse_live_quote_loop).',
    ),
    Row(
        file='server.py', derivation='_stream_spot_and_of_regime', disposition='ALLOWLISTED',
        allowlist_id='mega1_sqlite_internal',
        justification='Reads persisted snapshot SQLite rows, not Schwab wire JSON (_stream_spot_and_of_regime).',
    ),
    Row(
        file='server.py', derivation='_sync_market_context_panel_into_logging_universe', disposition='ALLOWLISTED',
        allowlist_id='mega1_sqlite_internal',
        justification='Reads persisted snapshot SQLite rows, not Schwab wire JSON (_sync_market_context_panel_into_logging_universe).',
    ),
    Row(
        file='server.py', derivation='_terrain_kl_overlay', disposition='ALLOWLISTED',
        allowlist_id='mega1_internal_helper',
        justification='W3-C1 / RC-122: overlays the terrain wall book onto the key-levels payload so ONE wall book reaches the screen; consumes already-derived terrain output and reads no vendor leaf.',
    ),
    Row(
        file='server.py', derivation='_terrain_refresh_one', disposition='DERIVED',
        producer_refs=('server.py:flatten_chain_contracts',),
        justification='Fetches one chain and computes terrain into the cache; no model stack, never raises.',
    ),
    Row(
        file='server.py', derivation='_terrain_snapshots_for_radar', disposition='ALLOWLISTED',
        allowlist_id='mega1_sqlite_internal',
        justification='Reads persisted snapshot SQLite rows, not Schwab wire JSON; merges the live terrain cache over a memoised stored-chain fallback.',
    ),
    Row(
        file='server.py', derivation='_tier_a_live_state_dict', disposition='DERIVED',
        producer_refs=('server.py:_fetch_state',),
        justification='Schwab API wrapper or wire JSON ingest path.',
    ),
    Row(
        file='server.py', derivation='_tier_c_analytics_json_response', disposition='ALLOWLISTED',
        allowlist_id='mega1_sqlite_internal',
        justification='Reads persisted snapshot SQLite rows, not Schwab wire JSON (_tier_c_analytics_json_response).',
    ),
    Row(
        file='server.py', derivation='_update_rest_cum_delta', disposition='DERIVED',
        producer_refs=('server.py:_safe_float_quote',),
        justification='REST tape proxy when stream unavailable.',
    ),
    Row(
        file='server.py', derivation='api_live_plane', disposition='ALLOWLISTED',
        allowlist_id='mega1_sqlite_internal',
        justification='Reads persisted snapshot SQLite rows, not Schwab wire JSON (api_live_plane).',
    ),
    Row(
        file='server.py', derivation='api_order_flow_microstructure', disposition='DERIVED',
        producer_refs=('live_market_plane.py:get_quote',),
        justification='Read-only ORDER_FLOW_MARKET_MICROSTRUCTURE_V1 endpoint serializing the canonical book microstructure computed by order_flow_engine.compute_book_microstructure; stamps the exchange quote clock from the live plane get_quote and never recomputes.',
    ),
    Row(
        file='server.py', derivation='api_order_flow_options_microstructure', disposition='ALLOWLISTED',
        allowlist_id='mega1_live_plane_state',
        justification="Same ORDER_FLOW_MARKET_MICROSTRUCTURE_V1 shape as api_order_flow_microstructure, for one option contract's live book. This row serializes over in-memory live-plane state; the actual computation it delegates to (order_flow_streaming.get_option_contract_book_microstructure -> order_flow_engine.compute_book_microstructure, never a second book-imbalance computation) lives in mega2-owned files and is registered + chain-closed there, not re-derived here.",
    ),
    Row(
        file='server.py', derivation='api_vol_observability', disposition='DERIVED',
        producer_refs=('market_context.py:fetch_market_context',),
        justification='Read-only VOL_OBSERVABILITY_V1 endpoint serializing already-fetched $VIX/$VXN/$RVX observations; native consumption stays FETCHED_UNCONSUMED (no money-path routing).',
    ),
    Row(
        file='server.py', derivation='canonical_price_level_snapshot', disposition='DERIVED',
        producer_refs=('server.py:_canonical_price_level_bars',),
        justification='Phase 2A single-materialization entry point; delegates to liquidity_value_engine.materialize_price_level_snapshot (outside MEGA1 scope), computes no market field itself.',
    ),
    Row(
        file='server.py', derivation='chain_underlying_spot', disposition='SCHWAB_LEAF',
        schwab_leaf='chains.underlying.last',
        justification='Underlying last/mark/close from the chain payload; returns None rather than inventing a spot.',
    ),
    Row(
        file='server.py', derivation='debug_charm', disposition='DERIVED',
        producer_refs=('schwab_client.py:safe_get_chain',),
        justification='Schwab API wrapper or wire JSON ingest path.',
    ),
    Row(
        file='server.py', derivation='debug_prediction', disposition='ALLOWLISTED',
        allowlist_id='mega1_sqlite_internal',
        justification='Reads persisted snapshot SQLite rows, not Schwab wire JSON (debug_prediction).',
    ),
    Row(
        file='server.py', derivation='fast_quote', disposition='ALLOWLISTED',
        allowlist_id='mega1_sqlite_internal',
        justification='Reads persisted snapshot SQLite rows, not Schwab wire JSON (fast_quote).',
    ),
    Row(
        file='server.py', derivation='flatten_chain_contracts', disposition='SCHWAB_LEAF',
        schwab_leaf='chains.callExpDateMap.*.strikePrice',
        justification='Flattens the Schwab chain response into a contract list; single source shared by _fetch_state and the terrain loop.',
    ),
    Row(
        file='server.py', derivation='get_analytics_light', disposition='ALLOWLISTED',
        allowlist_id='mega1_sqlite_internal',
        justification='Reads persisted snapshot SQLite rows, not Schwab wire JSON (get_analytics_light).',
    ),
    Row(
        file='server.py', derivation='get_analytics_light_stream', disposition='ALLOWLISTED',
        allowlist_id='mega1_sqlite_internal',
        justification='Reads persisted snapshot SQLite rows, not Schwab wire JSON (get_analytics_light_stream).',
    ),
    Row(
        file='server.py', derivation='get_analytics_state', disposition='ALLOWLISTED',
        allowlist_id='mega1_sqlite_internal',
        justification='Reads persisted snapshot SQLite rows, not Schwab wire JSON (get_analytics_state).',
    ),
    Row(
        file='server.py', derivation='get_bars1m', disposition='DERIVED',
        producer_refs=('server.py:_fetch_state',),
        justification='Serves canonical 1m OHLCV bars from the cached bars store; no direct chain leaf.',
    ),
    Row(
        file='server.py', derivation='get_chain', disposition='DERIVED',
        producer_refs=('server.py:_latest_chain_and_spot',),
        justification='OPTIONS_ORDER_FLOW_V1 contract-selection surface: serializes the stored per-contract chain (symbol/putCall/strikePrice/bid/ask/greeks/OI/volume) verbatim from _latest_chain_and_spot, the SAME stored-chain reader terrain/radar/order-flow-microstructure already use — no new Schwab fetch, no reshaping.',
    ),
    Row(
        file='server.py', derivation='get_client', disposition='ALLOWLISTED',
        allowlist_id='mega1_sqlite_internal',
        justification='Reads persisted snapshot SQLite rows, not Schwab wire JSON (get_client).',
    ),
    Row(
        file='server.py', derivation='get_desk_brief', disposition='ALLOWLISTED',
        allowlist_id='mega1_sqlite_internal',
        justification='The newest research brief held at `as_of`, with each block aged against that instant rather than against now.',
    ),
    Row(
        file='server.py', derivation='get_desk_dossier', disposition='ALLOWLISTED',
        allowlist_id='mega1_sqlite_internal',
        justification="One name's measured structure as it stood at `as_of`, from the desk fact store.",
    ),
    Row(
        file='server.py', derivation='get_desk_radar', disposition='ALLOWLISTED',
        allowlist_id='mega1_sqlite_internal',
        justification='Candidate structure as it stood at `as_of`, read from the desk fact store; the as-of bound is what keeps a replay honest.',
    ),
    Row(
        file='server.py', derivation='get_desk_structure', disposition='ALLOWLISTED',
        allowlist_id='mega1_sqlite_internal',
        justification='Deterministic payoff plus the PHYSICAL terminal distribution for one candidate, as of the requested instant.',
    ),
    Row(
        file='server.py', derivation='get_exposure_book', disposition='ALLOWLISTED',
        allowlist_id='mega1_sqlite_internal',
        justification='RC-209: per-strike call/put GEX split, net DEX and volumes from the NEWEST banked wide chain, all through the shared exposure faucet.',
    ),
    Row(
        file='server.py', derivation='get_exposure_flow', disposition='ALLOWLISTED',
        allowlist_id='mega1_sqlite_internal',
        justification='RC-208: serves banked option_chain_accrual frames for the latest banked session; reads rows this repo already persisted rather than re-deriving them.',
    ),
    Row(
        file='server.py', derivation='get_exposure_history', disposition='ALLOWLISTED',
        allowlist_id='mega1_sqlite_internal',
        justification='RC-209: per-day per-strike net GEX$ for the multi-day scroll-back, assembled from banked captures.',
    ),
    Row(
        file='server.py', derivation='get_forces', disposition='ALLOWLISTED',
        allowlist_id='mega1_sqlite_internal',
        justification='RC-192/RC-199: per-side OI delta from the two newest banked trading-day chains, plus DEX and dealer-signed CHARM summed on the NEWER capture alone. Serves charm_book_scope and charm_error beside the numbers so a surface can state which book was summed and whether the charm failed (RC-288/RC-304).',
    ),
    Row(
        file='server.py', derivation='get_l1_diagnostics', disposition='ALLOWLISTED',
        allowlist_id='mega1_sqlite_internal',
        justification='Reads persisted snapshot SQLite rows, not Schwab wire JSON (get_l1_diagnostics).',
    ),
    Row(
        file='server.py', derivation='get_levels', disposition='DERIVED',
        producer_refs=('server.py:resolve_spot', 'server.py:_liquidity_live_1m_overlay_bars'),
        justification='The single levels contract, schema v1: id, price, family, evidence_tier, provenance and staleness for every served level. Assembles already-derived level producers; the gamma family is explicitly excluded from the Tier-B slice and served by /api/terrain until that migration completes, and the payload says so rather than omitting it silently.',
    ),
    Row(
        file='server.py', derivation='get_liquidity_playbook_state', disposition='ALLOWLISTED',
        allowlist_id='mega1_sqlite_internal',
        justification='Reads persisted snapshot SQLite rows, not Schwab wire JSON (get_liquidity_playbook_state).',
    ),
    Row(
        file='server.py', derivation='get_liquidity_snapshot', disposition='ALLOWLISTED',
        allowlist_id='mega1_sqlite_internal',
        justification='Reads persisted snapshot SQLite rows, not Schwab wire JSON (get_liquidity_snapshot).',
    ),
    Row(
        file='server.py', derivation='get_live_state', disposition='ALLOWLISTED',
        allowlist_id='mega1_sqlite_internal',
        justification='Reads persisted snapshot SQLite rows, not Schwab wire JSON (get_live_state).',
    ),
    Row(
        file='server.py', derivation='get_price_levels', disposition='SCHWAB_LEAF',
        schwab_leaf='quotes.quote.lastPrice',
        justification='Schwab API wrapper or wire JSON ingest path.',
    ),
    Row(
        file='server.py', derivation='get_spot', disposition='DERIVED',
        producer_refs=('server.py:resolve_spot',),
        justification='Featherweight live spot via the single spot authority resolve_spot (RC-14); no direct leaf here.',
    ),
    Row(
        file='server.py', derivation='get_terrain', disposition='ALLOWLISTED',
        allowlist_id='mega1_sqlite_internal',
        justification='Reads persisted snapshot SQLite rows, not Schwab wire JSON (get_terrain); delegates all level math to terrain_engine.compute_terrain.',
    ),
    Row(
        file='server.py', derivation='get_terrain_radar', disposition='ALLOWLISTED',
        allowlist_id='mega1_sqlite_internal',
        justification='Radar API handler: ranks cached terrain by proximity to the nearest wall; all level math is delegated to terrain_engine.',
    ),
    Row(
        file='server.py', derivation='get_terrain_strikes', disposition='SCHWAB_LEAF',
        schwab_leaf='chains.*.strikePrice',
        justification='Per-strike GEX$ endpoint: reads strikePrice/daysToExpiration/totalVolume from the chain.',
    ),
    Row(
        file='server.py', derivation='get_terrain_strikes._per_strike', disposition='SCHWAB_LEAF',
        schwab_leaf='chains.*.daysToExpiration',
        justification='Nested: builds one per-strike row from the chain leaves; near/far split now via the canonical terrain_engine._dte_of (Cursor-audit F8, replacing the removed nested _dte).',
    ),
    Row(
        file='server.py', derivation='get_terrain_strikes._side_sums', disposition='ALLOWLISTED',
        allowlist_id='mega1_internal_helper',
        justification="Nested: sums the already-computed per-strike GEX$ and volume per side of the payload's OWN spot. One aggregator, one spot basis — the in-browser re-sum was killed because a client loop could straddle a different spot and broke silently on payload changes.",
    ),
    Row(
        file='server.py', derivation='logger_remove', disposition='ALLOWLISTED',
        allowlist_id='mega1_sqlite_internal',
        justification='Reads persisted snapshot SQLite rows, not Schwab wire JSON (logger_remove).',
    ),
    Row(
        file='server.py', derivation='logger_status', disposition='ALLOWLISTED',
        allowlist_id='mega1_sqlite_internal',
        justification='Reads persisted snapshot SQLite rows, not Schwab wire JSON (logger_status).',
    ),
    Row(
        file='server.py', derivation='logger_universe', disposition='ALLOWLISTED',
        allowlist_id='mega1_sqlite_internal',
        justification='Reads persisted snapshot SQLite rows, not Schwab wire JSON (logger_universe).',
    ),
    Row(
        file='server.py', derivation='post_streaming_active_option_contract', disposition='ALLOWLISTED',
        allowlist_id='mega1_sqlite_internal',
        justification='Subscribes LEVELONE_OPTIONS+OPTIONS_BOOK to one option contract via the daemon signal file — mirrors post_streaming_active_ticker for the separate option-contract slot (post_streaming_active_option_contract).',
    ),
    Row(
        file='server.py', derivation='post_streaming_active_ticker', disposition='ALLOWLISTED',
        allowlist_id='mega1_sqlite_internal',
        justification='Reads persisted snapshot SQLite rows, not Schwab wire JSON (post_streaming_active_ticker).',
    ),
    Row(
        file='server.py', derivation='reset_schwab_client', disposition='ALLOWLISTED',
        allowlist_id='mega1_sqlite_internal',
        justification='Reads persisted snapshot SQLite rows, not Schwab wire JSON (reset_schwab_client).',
    ),
    Row(
        file='server.py', derivation='resolve_chain_strike_count', disposition='ALLOWLISTED',
        allowlist_id='mega1_sqlite_internal',
        justification='RC-59 single chain-width faucet (renamed from _terrain_strike_count, which survives as a back-compat alias): strike-count REQUEST parameter derived from learned geometry and the span bar; consumes no Schwab response field.',
    ),
    Row(
        file='server.py', derivation='resolve_spot', disposition='DERIVED',
        producer_refs=('server.py:_spot_from_quote',),
        justification='THE single spot authority (RC-14): live quote, then chain underlying, then stored snapshot; returns the value with its source.',
    ),
    Row(
        file='server.py', derivation='schwab_capability_state', disposition='DERIVED',
        producer_refs=('schwab_client.py:build_client_from_token',),
        justification='RC-514: capability verdict for /api/health, taken from the canonical client and the same _client cache get_client() uses.',
    ),
    Row(
        file='server.py', derivation='sse_stream', disposition='ALLOWLISTED',
        allowlist_id='mega1_sqlite_internal',
        justification='Reads persisted snapshot SQLite rows, not Schwab wire JSON (sse_stream).',
    ),
    Row(
        file='server.py', derivation='sse_stream.event_generator', disposition='ALLOWLISTED',
        allowlist_id='mega1_sqlite_internal',
        justification='Reads persisted snapshot SQLite rows, not Schwab wire JSON (sse_stream.event_generator).',
    ),
    Row(
        file='snapshot_access.py', derivation='require_snapshot_timeframe', disposition='ALLOWLISTED',
        allowlist_id='mega1_sqlite_internal',
        justification='Enforces explicit timeframe on snapshot SQL reads.',
    ),
    Row(
        file='snapshot_normalizer.py', derivation='_minute_bucket', disposition='ALLOWLISTED',
        allowlist_id='mega1_internal_helper',
        justification='int(ts_utc//60) bucket key.',
    ),
    Row(
        file='snapshot_normalizer.py', derivation='fetch_raw_subminute_rows', disposition='ALLOWLISTED',
        allowlist_id='mega1_sqlite_internal',
        justification='Reads persisted snapshot SQLite rows, not Schwab wire JSON (fetch_raw_subminute_rows).',
    ),
    Row(
        file='snapshot_normalizer.py', derivation='fetch_rows_for_normalization', disposition='ALLOWLISTED',
        allowlist_id='mega1_sqlite_internal',
        justification='Reads persisted snapshot SQLite rows, not Schwab wire JSON (fetch_rows_for_normalization).',
    ),
    Row(
        file='snapshot_normalizer.py', derivation='load_normalized_rows', disposition='ALLOWLISTED',
        allowlist_id='mega1_sqlite_internal',
        justification='Reads persisted snapshot SQLite rows, not Schwab wire JSON (load_normalized_rows).',
    ),
    Row(
        file='snapshot_normalizer.py', derivation='materialize_normalized_table', disposition='ALLOWLISTED',
        allowlist_id='mega1_sqlite_internal',
        justification='Reads persisted snapshot SQLite rows, not Schwab wire JSON (materialize_normalized_table).',
    ),
    Row(
        file='snapshot_normalizer.py', derivation='normalize_ticker', disposition='ALLOWLISTED',
        allowlist_id='mega1_sqlite_internal',
        justification='Reads persisted snapshot SQLite rows, not Schwab wire JSON (normalize_ticker).',
    ),
    Row(
        file='snapshot_normalizer.py', derivation='resample_to_1m', disposition='DERIVED',
        producer_refs=('snapshot_normalizer.py:fetch_rows_for_normalization',),
        justification='Synthetic 1m from sub-minute rows; spot proxies tagged in missing_fields.',
    ),
    Row(
        file='snapshot_normalizer.py', derivation='resolve_source_timeframe', disposition='ALLOWLISTED',
        allowlist_id='mega1_sqlite_internal',
        justification='Reads persisted snapshot SQLite rows, not Schwab wire JSON (resolve_source_timeframe).',
    ),
    Row(
        file='terrain_engine.py', derivation='_dte_of', disposition='SCHWAB_LEAF',
        schwab_leaf='chains.*.daysToExpiration',
        justification="Reads the contract's own daysToExpiration and returns None when it cannot be read; RC-290 removed the 999.0 sentinel that was putting unknown-maturity contracts into the FAR scope and rendering them there.",
    ),
    Row(
        file='terrain_engine.py', derivation='_per_strike_map', disposition='SCHWAB_LEAF',
        schwab_leaf='chains.*.totalVolume',
        justification='Per-strike net GEX$ and session volume from the chain that just built `exposures`; volume stays None until a contract supplies one, so a missing totalVolume cannot render as a real zero (RC-290).',
    ),
    Row(
        file='terrain_engine.py', derivation='_per_strike_rows', disposition='SCHWAB_LEAF',
        schwab_leaf='chains.*.totalVolume',
        justification="Builds the [[strike, net_gex_1pct$, session_volume], ...] triples the per-strike panel renders; volume is summed from the chain's own totalVolume through float_nonnegative_or_none, strikes through float_finite_or_none, so a NaN can never become a key or a bar.",
    ),
    Row(
        file='terrain_engine.py', derivation='_per_strike_scopes', disposition='DERIVED',
        producer_refs=('terrain_engine.py:compute_terrain',),
        justification='Splits the per-strike rows into the {all, near, far} sets the ALL / <=7DTE / MONTHLY+ chips switch between; the maturity split comes from _dte_of and a contract that cannot answer it lands in NEITHER side (RC-290).',
    ),
    Row(
        file='terrain_engine.py', derivation='compute_implied_one_day_move', disposition='SCHWAB_LEAF',
        schwab_leaf='chains.*.volatility',
        justification='RC-113 institutional sigma band EM_1d = S x sigma_ATM x sqrt(1/252); selects the ATM contract by putCall and strikePrice and takes its volatility leaf directly.',
    ),
    Row(
        file='terrain_engine.py', derivation='compute_terrain', disposition='DERIVED',
        producer_refs=('server.py:_latest_chain_and_spot',),
        justification='Assembles the terrain payload (regime, walls, pin, HVL, max pain, charm walls) from one chain; no model stack.',
    ),
    Row(
        file='terrain_engine.py', derivation='compute_wall_value_area', disposition='DERIVED',
        producer_refs=('terrain_engine.py:compute_terrain',),
        justification="RC-115 Market-Profile value area over SIDE gamma mass — the wall's earned range. Consumes exposures already derived upstream; reads no vendor leaf itself.",
    ),
    Row(
        file='terrain_engine.py', derivation='qualify_pin_candidate', disposition='DERIVED',
        producer_refs=('terrain_engine.py:compute_terrain', 'math_probabilities.py:compute_pin_score'),
        justification='RC-292 operator disposition: pin_candidate is the absolute-gamma strike published as a candidate pin ONLY after regime (net long gamma at spot), proximity (<=0.5% of spot, study_pin_residence_v1 cut), DTE (front expiry <=1 day, same study), liquidity (committed pin-score thresholds above negligible) and completeness (RC-413 magnitude bundle present) qualification; every gate fail-closed, absence ships with its blocker names.',
    ),
    Row(
        file='terrain_engine.py', derivation='strongest_strike_storm1', disposition='DERIVED',
        producer_refs=('terrain_engine.py:compute_terrain',),
        justification='RC-159 spot-independent strongest strike, ranked over the [[strike, net_gex, volume], ...] triples _per_strike_rows already produced; reads no vendor leaf.',
    ),
    Row(
        file='terrain_engine.py', derivation='strongest_strike_storm1._inv_ranks', disposition='DERIVED',
        producer_refs=('terrain_engine.py:strongest_strike_storm1',),
        justification='Nested: n+1-rank with AVERAGE ranks for ties (rank 1 = highest), so tied strikes cannot be ordered by list position.',
    ),
    Row(
        file='terrain_engine.py', derivation='wall_geometry_state', disposition='DERIVED',
        producer_refs=('server.py:get_terrain', 'terrain_engine.py:compute_terrain'),
        justification='RC-130: answers whether a wall is in the configuration its support/resistance label claims (contains / breached / unknown) from spot and the wall strike; the UI renders NO behavioural claim without a positive state.',
    ),
    Row(
        file='train_all.py', derivation='_HistoricalDB.get_recent_snapshots', disposition='ALLOWLISTED',
        allowlist_id='mega1_sqlite_internal',
        justification='Caching shim around lstm_data.get_recent_snapshots; on cache miss, delegates to that producer which opens SQLite and reads persisted snapshots. Mega4 boundary into Mega1; no direct Schwab wire derivation here.',
    ),
    Row(
        file='train_all.py', derivation='main', disposition='DERIVED',
        producer_refs=('features/live_feature_adapter.py:build_live_mvp_feature_row',),
        justification='No market-field derivation: CLI orchestration for batch training.',
    ),
    Row(
        file='train_all.py', derivation='preload_historical_db_for_eval', disposition='ALLOWLISTED',
        allowlist_id='mega1_sqlite_internal',
        justification='Opens SQLite read on caller-supplied db_path; preloads historical snapshot rows into an in-memory PreloadedHistoricalDB shim for offline eval. Mega4 internal SQLite read; no Schwab wire derivation.',
    ),
    Row(
        file='train_all.py', derivation='run_lstm', disposition='ALLOWLISTED',
        allowlist_id='mega1_sqlite_internal',
        justification='Training orchestrator: opens SQLite via _HistoricalDB, builds rolling-window sequences, fits LSTM model, persists torch artifact. No Schwab wire derivation.',
    ),
    Row(
        file='train_all.py', derivation='run_meta', disposition='ALLOWLISTED',
        allowlist_id='mega1_sqlite_internal',
        justification='Meta-model training orchestrator: opens SQLite via _HistoricalDB, runs ML stack layers via ml_predict, fits meta-stack from layer outputs + labels, persists pickle artifact. No Schwab wire derivation.',
    ),
    Row(
        file='train_all.py', derivation='run_transformer', disposition='ALLOWLISTED',
        allowlist_id='mega1_sqlite_internal',
        justification='Training orchestrator: opens SQLite via _HistoricalDB, builds rolling-window sequences, fits Transformer model, persists torch artifact. No Schwab wire derivation.',
    ),
    Row(
        file='train_all.py', derivation='run_xgb', disposition='ALLOWLISTED',
        allowlist_id='mega1_sqlite_internal',
        justification='Training orchestrator: opens SQLite connection on the snapshots DB via _HistoricalDB.get_recent_snapshots, builds train/eval slices, fits XGBoost model, persists artifact via pickle. No Schwab wire derivation.',
    ),
    Row(
        file='training_cache.py', derivation='db_distinct_rth_et_dates_for_ticker', disposition='ALLOWLISTED',
        allowlist_id='mega1_sqlite_internal',
        justification='Opens SQLite read on caller-supplied db_path; returns the distinct ET dates with RTH snapshots for a ticker. Persistence-only; no Schwab wire derivation.',
    ),
    Row(
        file='training_cache.py', derivation='db_training_fingerprint', disposition='ALLOWLISTED',
        allowlist_id='mega1_sqlite_internal',
        justification='Opens SQLite read on caller-supplied db_path; computes a stable training fingerprint (aggregate over caller-specified columns/filters) for cache-invalidation detection. Persistence-only; no Schwab wire derivation.',
    ),
    Row(
        file='training_cache.py', derivation='min_ts_utc_for_last_n_rth_sessions', disposition='ALLOWLISTED',
        allowlist_id='mega1_sqlite_internal',
        justification='Opens SQLite read on caller-supplied db_path; computes the min ts_utc for the most recent N RTH sessions to set the training window lower bound. Persistence-only; no Schwab wire derivation.',
    ),
    Row(
        file='training_pipeline_status.py', derivation='enrollment_category_counts', disposition='ALLOWLISTED',
        allowlist_id='mega1_sqlite_internal',
        justification='Opens `EdDB(db_path).logging_universe_list_rows()` to count enrolled tickers by category for the run-start payload. Mega4 internal SQLite read via Mega1 producer; no Schwab wire derivation.',
    ),
    Row(
        file='training_pipeline_status.py', derivation='record_run_start', disposition='ALLOWLISTED',
        allowlist_id='mega1_sqlite_internal',
        justification='Run-start aggregator: composes payload from caller-supplied (ml_horizon, target_column, tickers) + `enrollment_category_counts(db_path)` SQLite read, writes via `write_status`. No Schwab wire derivation.',
    ),
    Row(
        file='transformer_model.py', derivation='predict', disposition='DERIVED',
        producer_refs=('features/inference_snapshot.py:build_inference_snapshot_v1', 'market_state.py:build_market_state'),
        justification='Transformer inference: takes inference_snapshot_v1 (built from build_market_state Mega1 producer + canonical features), runs forward pass on the in-memory model, returns probability triplet.',
    ),
    Row(
        file='volatility_regime.py', derivation='classify_volatility_regime', disposition='DERIVED',
        producer_refs=('market_state.py:build_market_state',),
        justification='Vol policy from rv/iv/atr/vix upstream fields.',
    ),
    Row(
        file='xgboost_model.py', derivation='predict', disposition='DERIVED',
        producer_refs=('features/inference_snapshot.py:build_inference_snapshot_v1', 'market_state.py:build_market_state'),
        justification='Inference on canonical features; no Schwab wire ingest.',
    ),
    Row(
        file='server.py', derivation='_attach_analytics_freshness_contract', disposition='ALLOWLISTED',
        allowlist_id='analytics_cache_state',
        justification='Stamps analytics_stale / pending / refresh flags from the in-process cache clock (RC-532).',
    ),
    Row(
        file='server.py', derivation='_attach_card_freshness_v1_block', disposition='ALLOWLISTED',
        allowlist_id='analytics_cache_state',
        justification='Card freshness block derived from the same cache clock (RC-532).',
    ),
    Row(
        file='governed_stack_contract.py', derivation='resolve_guest_anchor_for_ticker', disposition='ALLOWLISTED',
        allowlist_id='mega4_governed_stack_contract',
        justification='Guest-anchor route from the governed stack contract (authoritative-ticker set, anchor affiliation); None when the ticker is authoritative.',
    ),
    Row(
        file='multi_horizon_decision.py', derivation='_horizon_skill_weights_cached', disposition='ALLOWLISTED',
        allowlist_id='mega1_sqlite_internal',
        justification='Rolling horizon skill weights from the calibration DB (TTL-cached); equal weights fail-closed. The ONLY pool-weight source (RC-533: the pool_weights parameter is gone).',
    ),
    Row(
        file='decision_gate.py', derivation='registry_path', disposition='ALLOWLISTED',
        allowlist_id='mega1_env_config',
        justification='Admissions registry path: ED_DECISION_ADMISSIONS_PATH override, else config/decision_path_admissions.json.',
    ),
    Row(
        file='decision_gate.py', derivation='evaluate_decision_path_admission', disposition='ALLOWLISTED',
        allowlist_id='mega1_filesystem',
        justification='Reads the on-disk admissions registry JSON for DECISION_PATH_COMPONENT; fail-closed WAIT on every error (RC-533: the component parameter is gone).',
    ),
    Row(
        file='setup_readiness.py', derivation='score_readiness', disposition='ALLOWLISTED',
        allowlist_id='mega3_internal_helper',
        justification='THE readiness scoring authority: tiers + probability + validation -> call_state / forecast_state; pure over already-typed inputs.',
    ),
    Row(
        file='setup_readiness.py', derivation='compute_call_readiness', disposition='DERIVED',
        producer_refs=('setup_readiness.py:score_readiness',),
        justification='CALL-side tier classification feeding the one scorer.',
    ),
    Row(
        file='setup_readiness.py', derivation='compute_put_readiness', disposition='DERIVED',
        producer_refs=('setup_readiness.py:score_readiness',),
        justification='PUT-side tier classification feeding the one scorer.',
    ),
    Row(
        file='signals.py', derivation='production_fusion_payload_for_stack', disposition='DERIVED',
        producer_refs=('market_state.py:build_market_state', 'features/inference_snapshot.py:build_inference_snapshot_v1_from_signal_input', 'bayesian_fusion.py:fuse', 'bayesian_fusion.py:build_fusion_tick_cache', 'mc_fusion_adjustment.py:fuse_payload_apply_mc_adjustment',),
        justification='Per-horizon governed stack + Bayesian fusion payload; the fusion object every decision engine consumes.',
    ),
    Row(
        file='signals.py', derivation='canonical_forecast_from_fusion', disposition='DERIVED',
        producer_refs=('signals.py:production_fusion_payload_for_stack',),
        justification='Canonical forecast triplet projected from the live-horizon fusion payload.',
    ),
    Row(
        file='multi_horizon_ml_bundle.py', derivation='build_multi_horizon_ml_fusion_bundle', disposition='DERIVED',
        producer_refs=('signals.py:production_fusion_payload_for_stack',),
        justification='Authoritative multi-horizon ML fusion bundle from the primary-horizon fusion payloads.',
    ),
    Row(
        file='rules_engine.py', derivation='compute_rules', disposition='DERIVED',
        producer_refs=('market_state.py:build_market_state', 'features/inference_snapshot.py:build_inference_snapshot_v1_from_signal_input',),
        justification='Right Now micro-regime card from SignalInput candles + MVP features.',
    ),
    Row(
        file='db.py', derivation='EdDB.get_avg_move', disposition='ALLOWLISTED',
        allowlist_id='mega1_sqlite_internal',
        justification='Average-move statistics from persisted console rows (prediction empirical histograms).',
    ),
    Row(
        file='prediction_engine.py', derivation='compute_prediction_core', disposition='DERIVED',
        producer_refs=('market_state.py:build_market_state', 'db.py:EdDB.get_avg_move', 'regime_engine.py:classify_regime', 'signals.py:production_fusion_payload_for_stack', 'rules_engine.py:compute_rules', 'math_probabilities.py:compute_percentile_range', 'signals.py:canonical_forecast_from_fusion', 'multi_horizon_ml_bundle.py:build_multi_horizon_ml_fusion_bundle', 'features/inference_snapshot.py:build_inference_snapshot_v1_from_signal_input',),
        justification='Hot-path prediction card (the object MH + The Call consume); compute_prediction wraps it with UI enrichment.',
    ),
    Row(
        file='multi_horizon_decision.py', derivation='compute_multi_horizon_synthesis', disposition='DERIVED',
        producer_refs=('market_state.py:build_market_state', 'prediction_engine.py:compute_prediction_core', 'signals.py:canonical_forecast_from_fusion', 'multi_horizon_ml_bundle.py:build_multi_horizon_ml_fusion_bundle', 'multi_horizon_decision.py:_horizon_skill_weights_cached', 'governed_stack_contract.py:resolve_guest_anchor_for_ticker',),
        justification='THE multi-horizon verdict owner: pooled consensus -> final_bias / tradeable / wait_reason / size; the guest-anchor veto is applied here (RC-533).',
    ),
    Row(
        file='call_engine.py', derivation='_validate_trade', disposition='DERIVED',
        producer_refs=('market_state.py:build_market_state', 'prediction_engine.py:compute_prediction_core', 'signals.py:production_fusion_payload_for_stack', 'signals.py:canonical_forecast_from_fusion', 'regime_engine.py:classify_regime', 'volatility_regime.py:classify_volatility_regime',),
        justification='Trade validation gate result (trade_valid) inside The Call.',
    ),
    Row(
        file='call_engine.py', derivation='compute_position_size', disposition='DERIVED',
        producer_refs=('market_state.py:build_market_state', 'regime_engine.py:classify_regime', 'signals.py:production_fusion_payload_for_stack', 'volatility_regime.py:classify_volatility_regime', 'call_engine.py:_validate_trade',),
        justification='Position-size cue from the call verdict, regime, fusion, volatility and validation; every argument is computed by compute_call or its inputs.',
    ),
    Row(
        file='call_engine.py', derivation='compute_call', disposition='DERIVED',
        producer_refs=('market_state.py:build_market_state', 'rules_engine.py:compute_rules', 'prediction_engine.py:compute_prediction_core', 'regime_engine.py:classify_regime', 'signals.py:production_fusion_payload_for_stack', 'volatility_regime.py:classify_volatility_regime', 'signals.py:canonical_forecast_from_fusion', 'features/inference_snapshot.py:build_inference_snapshot_v1_from_signal_input', 'multi_horizon_decision.py:compute_multi_horizon_synthesis', 'decision_gate.py:evaluate_decision_path_admission', 'setup_readiness.py:compute_call_readiness', 'setup_readiness.py:compute_put_readiness', 'call_engine.py:_validate_trade', 'call_engine.py:compute_position_size', 'trade_impacting_gate.py:validate_trade_impacting_gate',),
        justification='THE Call owner: signal / conviction / call_state / forecast_state / trade plan; admission veto and readiness inside.',
    ),
    Row(
        file='multi_horizon_decision.py', derivation='finalize_multi_horizon_bundle', disposition='DERIVED',
        producer_refs=('multi_horizon_decision.py:compute_multi_horizon_synthesis', 'call_engine.py:compute_call', 'market_state.py:build_market_state', 'multi_horizon_ml_bundle.py:build_multi_horizon_ml_fusion_bundle',),
        justification='Attaches the call-derived plan to the synthesis: final_bias / final_confidence / final_tradeable / entry_state / wait_reason / supporting assessments (mhap_rows).',
    ),
    Row(
        file='market_state.py', derivation='is_bias_actionable', disposition='DERIVED',
        producer_refs=('math_levels.py:build_summary_rows',),
        justification='Exact-match bias gate over consensus_summary.bias_signal (summary row 0).',
    ),
    Row(
        file='market_state.py', derivation='dte_style', disposition='DERIVED',
        producer_refs=('market_state.py:_schwab_days_to_expiration_for_contract',),
        justification="DTE warning label + colour from the selected contract's Schwab daysToExpiration.",
    ),
    Row(
        file='trade_impacting_gate.py', derivation='validate_trade_impacting_gate', disposition='DERIVED',
        producer_refs=('server.py:_fetch_state',),
        justification='Emission FACTS (route class, spot sanity, spread age, staleness, quarantine, production_emission_allowed) validated on the facts server._fetch_state knows before the state is built; consumed by The Call as an input (RC-534). Rewrites no verdict.',
    ),
)
