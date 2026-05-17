"""
Section 13 Schwab-leaf derivation audit inventory (similarity engines).

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


SECTION13_DERIVATION_INVENTORY: tuple[DerivationRecord, ...] = (

    DerivationRecord("adaptive_similarity_engine.py", "61", "default_tier3_mid_weights_v1", "—", "NONE", "Static config/contract helper."),
    DerivationRecord("adaptive_similarity_engine.py", "69", "calibration_weight_profiles_v1", "snapshots.* / features", "KEEP_DERIVED", "Similarity scoring or filtering on snapshot-derived features."),
    DerivationRecord("adaptive_similarity_engine.py", "81", "calibration_weight_profiles_v1.push", "—", "NONE", "No Schwab market-field derivation in function body."),
    DerivationRecord("adaptive_similarity_engine.py", "105", "_fetch_issue19_tier1_candidate_rows", "snapshots.*", "PASS_THROUGH", "Issue 19 tier-1 SQL candidate pool fetch."),
    DerivationRecord("adaptive_similarity_engine.py", "156", "_adaptive_v2_score_row", "snapshots.* / features", "KEEP_DERIVED", "Similarity analysis on persisted snapshot features."),
    DerivationRecord("adaptive_similarity_engine.py", "208", "run_adaptive_shadow_v2", "snapshots.* / tier SQL pool", "KEEP_DERIVED", "Shadow v2 selection on Issue 19 tier-1 candidate rows from DB."),
    DerivationRecord("adaptive_similarity_engine.py", "349", "default_equal_weights", "snapshots.* / features", "KEEP_DERIVED", "Similarity scoring or filtering on snapshot-derived features."),
    DerivationRecord("adaptive_similarity_engine.py", "358", "_bucket_adjacency_score", "snapshots.* / features", "KEEP_DERIVED", "Similarity analysis on persisted snapshot features."),
    DerivationRecord("adaptive_similarity_engine.py", "385", "_categorical_soft_match", "snapshots.* / features", "KEEP_DERIVED", "Similarity scoring or filtering on snapshot-derived features."),
    DerivationRecord("adaptive_similarity_engine.py", "398", "_score_row", "snapshots.* / features", "KEEP_DERIVED", "Similarity analysis on persisted snapshot features."),
    DerivationRecord("adaptive_similarity_engine.py", "450", "_score_distribution", "—", "NONE", "No Schwab market-field derivation in function body."),
    DerivationRecord("adaptive_similarity_engine.py", "467", "_score_distribution._pct", "—", "NONE", "No Schwab market-field derivation in function body."),
    DerivationRecord("adaptive_similarity_engine.py", "482", "_fetch_candidate_rows", "snapshots.*", "PASS_THROUGH", "Loads candidate rows from DB for similarity scoring."),
    DerivationRecord("adaptive_similarity_engine.py", "503", "_selected_ids", "snapshots.*", "KEEP_DERIVED", "Operates on persisted snapshot/feature rows."),
    DerivationRecord("adaptive_similarity_engine.py", "512", "_overlap_metrics", "—", "NONE", "No Schwab market-field derivation in function body."),
    DerivationRecord("adaptive_similarity_engine.py", "548", "run_weighted_selection", "snapshots.*", "KEEP_DERIVED", "Weighted similarity ranking on broad candidate pool."),
    DerivationRecord("adaptive_similarity_engine.py", "629", "run_baseline_control", "snapshots.*", "KEEP_DERIVED", "Delegates to production get_similar_setups baseline."),
    DerivationRecord("adaptive_similarity_engine.py", "682", "run_order_variant", "snapshots.* / features", "KEEP_DERIVED", "Similarity analysis on persisted snapshot features."),
    DerivationRecord("adaptive_similarity_engine.py", "722", "run_feature_ablations", "snapshots.* / features", "KEEP_DERIVED", "Similarity analysis on persisted snapshot features."),
    DerivationRecord("adaptive_similarity_engine.py", "790", "shadow_run_to_dict", "snapshots.* / features", "KEEP_DERIVED", "Similarity analysis on persisted snapshot features."),
    DerivationRecord("adaptive_similarity_engine.py", "807", "compare_heuristic_to_shadow", "snapshots.* / features", "KEEP_DERIVED", "Similarity analysis on persisted snapshot features."),
    DerivationRecord("similarity_audit.py", "33", "baseline_feature_contract_v1", "feature contract", "NONE", "Static feature contract definition for similarity tiers."),
    DerivationRecord("similarity_audit.py", "107", "contract_expected_structural_filter_keys", "snapshots.* / features", "KEEP_DERIVED", "Similarity scoring or filtering on snapshot-derived features."),
    DerivationRecord("similarity_audit.py", "125", "_bucket_interval", "—", "NONE", "No Schwab market-field derivation in function body."),
    DerivationRecord("similarity_audit.py", "133", "normalize_anchor_distances_for_issue19_sql", "snapshots.*", "PASS_THROUGH", "DB fetch for similarity candidate rows."),
    DerivationRecord("similarity_audit.py", "153", "query_context_for_similarity", "snapshots.*", "KEEP_DERIVED", "Builds anchor query context from snapshot feature columns."),
    DerivationRecord("similarity_audit.py", "183", "structured_constraints_for_tier", "snapshots.*", "PASS_THROUGH", "DB fetch for similarity candidate rows."),
    DerivationRecord("similarity_audit.py", "260", "relaxed_constraints_vs_previous_tier", "snapshots.* / features", "KEEP_DERIVED", "Similarity scoring or filtering on snapshot-derived features."),
    DerivationRecord("similarity_audit.py", "273", "widening_summary_from_tiers", "labeled counts / tiers", "NONE", "Tier viability audit counters."),
    DerivationRecord("similarity_audit.py", "307", "withheld_horizons_report", "labeled counts / tiers", "NONE", "Tier viability audit counters."),
    DerivationRecord("similarity_audit.py", "325", "tier_stop_weak_horizons", "labeled counts / tiers", "NONE", "Tier viability audit counters."),
    DerivationRecord("similarity_audit.py", "341", "weakest_tracked_horizons", "labeled counts / tiers", "NONE", "Tier viability audit counters."),
    DerivationRecord("similarity_audit.py", "357", "_dist_matches_null_or_between", "snapshots.* / features", "KEEP_DERIVED", "Similarity scoring or filtering on snapshot-derived features."),
    DerivationRecord("similarity_audit.py", "372", "validate_row_matches_tier_constraints", "labeled counts / tiers", "NONE", "Tier viability audit counters."),
    DerivationRecord("similarity_audit.py", "419", "validate_selected_rows_match_tier", "labeled counts / tiers", "NONE", "Tier viability audit counters."),
    DerivationRecord("similarity_audit.py", "443", "widening_steps_are_sequential", "labeled counts / tiers", "NONE", "Tier viability audit counters."),
    DerivationRecord("similarity_audit.py", "451", "inspection_row_projection", "snapshots.* / features", "KEEP_DERIVED", "Similarity scoring or filtering on snapshot-derived features."),
    DerivationRecord("similarity_audit.py", "452", "inspection_row_projection._b", "—", "NONE", "No Schwab market-field derivation in function body."),
    DerivationRecord("similarity_audit.py", "486", "similarity_trace_machine_summary", "snapshots.* / features", "KEEP_DERIVED", "Similarity scoring or filtering on snapshot-derived features."),
    DerivationRecord("similarity_audit.py", "505", "build_similar_inspection_bundle", "trace + rows", "KEEP_DERIVED", "Inspection bundle from similarity trace and selected rows."),
    DerivationRecord("similarity_audit.py", "525", "merge_trace_with_shadow_extension", "—", "NONE", "Similarity audit/trace helper; no live market ingest."),
    DerivationRecord("similarity_feature_search.py", "78", "weights_for_band", "—", "NONE", "No Schwab market-field derivation in function body."),
    DerivationRecord("similarity_feature_search.py", "84", "run_staged_shadow_search", "snapshots.* / features", "KEEP_DERIVED", "Similarity analysis on persisted snapshot features."),
    DerivationRecord("similarity_feature_search.py", "218", "analyze_baseline_feature_outcome_divergence", "snapshots.*", "PASS_THROUGH", "DB fetch for similarity candidate rows."),
    DerivationRecord("similarity_feature_search.py", "295", "synthesize_per_feature_recommendations", "snapshots.*", "PASS_THROUGH", "DB fetch for similarity candidate rows."),
    DerivationRecord("similarity_feature_search.py", "388", "anchor_overlay_from_snapshot_row", "snapshots.* / features", "KEEP_DERIVED", "Similarity scoring or filtering on snapshot-derived features."),
    DerivationRecord("similarity_feature_search.py", "400", "latest_snapshot_as_anchor_overlay", "snapshots.* / features", "KEEP_DERIVED", "Similarity scoring or filtering on snapshot-derived features."),
    DerivationRecord("similarity_feature_search.py", "421", "_overlay_bucket_clauses", "snapshots.*", "PASS_THROUGH", "DB fetch for similarity candidate rows."),
    DerivationRecord("similarity_feature_search.py", "445", "_zone_predicate_for_overlay_lookup", "snapshots.*", "PASS_THROUGH", "DB fetch for similarity candidate rows."),
    DerivationRecord("similarity_feature_search.py", "464", "diagnose_overlay_match_counts", "snapshots.*", "PASS_THROUGH", "DB fetch for similarity candidate rows."),
    DerivationRecord("similarity_feature_search.py", "530", "matching_snapshot_overlay_for_anchor", "snapshots.* / features", "KEEP_DERIVED", "Similarity scoring or filtering on snapshot-derived features."),
    DerivationRecord("similarity_feature_search.py", "557", "resolve_overlay_for_anchor", "snapshots.*", "PASS_THROUGH", "DB fetch for similarity candidate rows."),
    DerivationRecord("similarity_feature_survivorship.py", "45", "default_multi_anchor_set_v1", "snapshots.*", "PASS_THROUGH", "DB fetch for similarity candidate rows."),
    DerivationRecord("similarity_feature_survivorship.py", "108", "discover_tickers_for_survivorship", "snapshots.*", "PASS_THROUGH", "DB fetch for similarity candidate rows."),
    DerivationRecord("similarity_feature_survivorship.py", "130", "_infer_role_for_extra", "snapshots.*", "KEEP_DERIVED", "Operates on persisted snapshot/feature rows."),
    DerivationRecord("similarity_feature_survivorship.py", "136", "_top_k_trial_keys", "—", "NONE", "No Schwab market-field derivation in function body."),
    DerivationRecord("similarity_feature_survivorship.py", "148", "run_multi_anchor_survivorship", "snapshots.*", "PASS_THROUGH", "DB fetch for similarity candidate rows."),
    DerivationRecord("similarity_feature_survivorship.py", "330", "final_structure_from_survivorship", "snapshots.* / features", "KEEP_DERIVED", "Similarity analysis on persisted snapshot features."),
    DerivationRecord("similarity_feature_survivorship.py", "376", "overall_confidence", "—", "NONE", "No Schwab market-field derivation in function body."),
    DerivationRecord("similarity_feature_universe.py", "34", "_is_outcome_field", "—", "NONE", "No Schwab market-field derivation in function body."),
    DerivationRecord("similarity_feature_universe.py", "42", "_metadata_field", "snapshots.*", "KEEP_DERIVED", "Operates on persisted snapshot/feature rows."),
    DerivationRecord("similarity_feature_universe.py", "53", "_infer_data_type", "snapshots.* / features", "KEEP_DERIVED", "Similarity scoring or filtering on snapshot-derived features."),
    DerivationRecord("similarity_feature_universe.py", "93", "_similarity_suitability", "snapshots.* / features", "KEEP_DERIVED", "Similarity scoring or filtering on snapshot-derived features."),
    DerivationRecord("similarity_feature_universe.py", "126", "_signal_input_only_fields", "snapshots.*", "KEEP_DERIVED", "Operates on persisted snapshot/feature rows."),
    DerivationRecord("similarity_feature_universe.py", "135", "_lstm_feature_rows", "snapshots.* / features", "KEEP_DERIVED", "Similarity scoring or filtering on snapshot-derived features."),
    DerivationRecord("similarity_feature_universe.py", "163", "_partition_entries", "snapshots.*", "PASS_THROUGH", "DB fetch for similarity candidate rows."),
    DerivationRecord("similarity_feature_universe.py", "204", "build_feature_universe_inventory_v1", "snapshots.*", "PASS_THROUGH", "DB fetch for similarity candidate rows."),
    DerivationRecord("similarity_feature_universe.py", "293", "sqlite_snapshot_column_names", "snapshots.*", "PASS_THROUGH", "DB fetch for similarity candidate rows."),
)

SECTION13_FILES = frozenset({
    "adaptive_similarity_engine.py",
    "similarity_audit.py",
    "similarity_feature_search.py",
    "similarity_feature_survivorship.py",
    "similarity_feature_universe.py",
})

