# Pytest infrastructure inventory (auditor dump)

**Date (UTC):** `2026-08-23T12:20:58Z`  
**Authority:** Cursor adversarial auditor (operator request). Not a rehab plan. Not LIVE proof.  
**UNIVERSAL:** this is a repo-wide `tests/` tree inventory. Existing filenames that mention a single ticker are quoted as-is from disk.  
**OUT-OF-SCOPE:** Collect / Chart / Decide product completeness; no weekday-named next-RTH proof; no implementation.

Reproduce (same commands the operator named):

```bash
find tests/ -name "*.py" -type f | sort
find tests/ -name "*.py" -type f | wc -l
find tests/ -name "test_*.py" | wc -l
grep -r "def test_" tests/ | wc -l
grep -r --include='*.py' "def test_" tests/ --exclude-dir=archive --exclude-dir=__pycache__ | wc -l
find tests/ -name "test_v1_*.py" | sort
find tests/ -name "test_v2_*.py" | sort
find tests/ -name "test_a1_*.py" | sort
find tests/ -name "test_a2_*.py" | sort
find tests/ -name "test_*_artifact_*.py" | sort
find tests/ -type d ! -path '*/__pycache__*' | sort
test -f pytest.ini && echo EXISTS || echo "pytest.ini DOES NOT EXIST"
python3 -c "import tomllib; d=tomllib.load(open('pyproject.toml','rb')); print('tool.pytest' in d.get('tool',{})); print(list(d.get('tool',{}).keys()))"
```

Measured this turn:

| Metric | Value | Command |
|---|---:|---|
| Python files under `tests/` | 593 | `find tests/ -name "*.py" -type f \| wc -l` |
| `test_*.py` files | 583 | `find tests/ -name "test_*.py" \| wc -l` |
| top-level `tests/test_*.py` | 554 | `len(list(Path('tests').glob('test_*.py')))` |
| `def test_` line matches (requested grep) | 5624 | `grep -r "def test_" tests/ \| wc -l` |
| `def test_` in `*.py` excluding archive/pycache | 5525 | see reproduce block |
| `test_v1_*.py` | 0 | `find tests/ -name 'test_v1_*.py' \| wc -l` |

The requested `grep -r "def test_" tests/ | wc -l` count includes `__pycache__/*.pyc` binary hits. It is a line-match count, not a collected pytest node count.

---

## 1. FULL TEST FILE LISTING

`find tests/ -name "*.py" -type f | sort` — 593 paths, untruncated:

```
tests/adversarial/__init__.py
tests/adversarial/test_bypass_register_reconciliation.py
tests/adversarial/test_live_decision_record_reconstruction.py
tests/adversarial/test_override_registry.py
tests/adversarial/test_r004_live_path_gate.py
tests/adversarial/test_r031_cli_classification.py
tests/adversarial/test_remaining_route_inventory.py
tests/adversarial/test_route_universality.py
tests/adversarial/test_stale_cache_revalidation.py
tests/adversarial/test_wrong_price_quarantine.py
tests/archive/conftest.py
tests/archive/legacy_section_audits_v1/test_section10_schwab_derivation_audit.py
tests/archive/legacy_section_audits_v1/test_section11_schwab_derivation_audit.py
tests/archive/legacy_section_audits_v1/test_section12_schwab_derivation_audit.py
tests/archive/legacy_section_audits_v1/test_section13_schwab_derivation_audit.py
tests/archive/legacy_section_audits_v1/test_section14_schwab_derivation_audit.py
tests/archive/legacy_section_audits_v1/test_section15_schwab_derivation_audit.py
tests/archive/legacy_section_audits_v1/test_section16_schwab_derivation_audit.py
tests/archive/legacy_section_audits_v1/test_section1_schwab_derivation_audit.py
tests/archive/legacy_section_audits_v1/test_section2_schwab_derivation_audit.py
tests/archive/legacy_section_audits_v1/test_section3_schwab_derivation_audit.py
tests/archive/legacy_section_audits_v1/test_section4_schwab_derivation_audit.py
tests/archive/legacy_section_audits_v1/test_section5_schwab_derivation_audit.py
tests/archive/legacy_section_audits_v1/test_section6_schwab_derivation_audit.py
tests/archive/legacy_section_audits_v1/test_section7_schwab_derivation_audit.py
tests/archive/legacy_section_audits_v1/test_section8_schwab_derivation_audit.py
tests/archive/legacy_section_audits_v1/test_section9_schwab_derivation_audit.py
tests/conftest.py
tests/decision_reconstruction/__init__.py
tests/decision_reconstruction/test_immutable_decision_id.py
tests/__init__.py
tests/mvp_test_fixtures.py
tests/perf_proof/__init__.py
tests/perf_proof/validate.py
tests/playwright_ready.py
tests/release_object/__init__.py
tests/release_object/test_release_stamping.py
tests/runtime_proof/test_env_override_hardening.py
tests/runtime_proof/test_live_path_decision_reconstruction.py
tests/test_a1_conformal_artifact_loader.py
tests/test_a1_conformal_artifact_production.py
tests/test_a1_isotonic_artifact_loader.py
tests/test_a1_isotonic_artifact_production.py
tests/test_a1_isotonic_runtime.py
tests/test_a2_eod_force_exit.py
tests/test_a2_market_state_proof_row_completeness.py
tests/test_a2_price_precedence.py
tests/test_a2_session_calendar.py
tests/test_a2_staleness_trade_time_fallback.py
tests/test_a2_theta_schwab_first.py
tests/test_ablation_static_lock_index.py
tests/test_absence_has_a_type_gate_v1.py
tests/test_absence_is_not_zero_v1.py
tests/test_action10_6_thecall_validation_defaults.py
tests/test_action10_fail_closed_defaults.py
tests/test_action11_12_regime_engine_fail_closed.py
tests/test_action11_1_math_levels_fail_closed.py
tests/test_action11_2_order_flow_verdict_fail_closed.py
tests/test_action11_3_server_ms_dict_fail_closed.py
tests/test_action11_4_math_probabilities_fail_closed.py
tests/test_action11_5_compute_net_charm_fail_closed.py
tests/test_action11_8_signals_mc_fusion_fail_closed.py
tests/test_action11_9_call_engine_fail_closed.py
tests/test_action12_10_regime_mvp_context_fail_closed.py
tests/test_action12_11_parallel_stack_schema_fail_closed.py
tests/test_action12_12_similar_setup_filters_fail_closed.py
tests/test_action12_13_signal_layer_v1_fail_closed.py
tests/test_action12_14_signal_layer_discrimination_fail_closed.py
tests/test_action12_1_through_12_5_fail_closed.py
tests/test_action12_6_micro_liquidity_fail_closed.py
tests/test_action12_7_market_state_fail_closed.py
tests/test_action12_8_fusion_policy_fail_closed.py
tests/test_action12_9_index_html_fail_closed.py
tests/test_action12_layer5_upstream_fail_closed.py
tests/test_active_bundle_contract_v1.py
tests/test_active_horizon_layout_pr3.py
tests/test_adaptive_shadow_similarity.py
tests/test_adaptive_shadow_v2.py
tests/test_agent_worktree_db_v1.py
tests/test_analytics_state_freshness_api.py
tests/test_analytics_undated_is_not_fresh_v1.py
tests/test_anti_pattern_family_repo_wide.py
tests/test_arch_competition_audit.py
tests/test_arch_competition_auto_promote.py
tests/test_arch_competition_eval_promotion.py
tests/test_arch_competition_eval_runner.py
tests/test_arch_competition_manual_control.py
tests/test_arch_competition_metrics.py
tests/test_arch_competition_numeric_safe.py
tests/test_arch_competition_operational_policy.py
tests/test_arch_competition_scheduler_integration_authority.py
tests/test_architecture_a_bypass_class_v1.py
tests/test_atomic_io.py
tests/test_attach_5m_additive_context.py
tests/test_audit_cand_server_py_full_read_v1.py
tests/test_audit_outcome_is_typed_v1.py
tests/test_audit_snapshot_columns.py
tests/test_auto_promote_rollback.py
tests/test_axiom_brand_landing_v1.py
tests/test_backfill_et_clock_from_ts_utc_v1.py
tests/test_backfill_greeks_certification_v1.py
tests/test_backfill_greeks_p2_gate_v1.py
tests/test_backfill_outcomes.py
tests/test_backfill_outcomes_ticker_key.py
tests/test_backfill_signal_layer_v1_bundle.py
tests/test_bars_collected_for_all_tickers_v1.py
tests/test_bars_collection_service_v1.py
tests/test_base_ticker_observability.py
tests/test_batch2_analytics_bg_fail_counter.py
tests/test_batch2_signals_engine_error.py
tests/test_batch_movement_backfill_contract_v1.py
tests/test_batch_universe_smoke_v1.py
tests/test_bayesian_fusion_fail_closed.py
tests/test_bayesian_fusion_numeric_contract_v1.py
tests/test_bootstrap_worktree_venv_v1.py
tests/test_build_identity_process_drift_v1.py
tests/test_build_identity_semantics.py
tests/test_build_market_state_spot_fail_closed.py
tests/test_cache_skip_streak_cap.py
tests/test_calibration_accumulation_validation.py
tests/test_calibration_analyze_phase3.py
tests/test_calibration_analyze_phase4.py
tests/test_calibration_anchor_stability.py
tests/test_calibration_bypass_closure.py
tests/test_calibration_daily_scoreboard.py
tests/test_calibration_edge_validation.py
tests/test_calibration_legacy_quarantine.py
tests/test_calibration_logging_production_path.py
tests/test_calibration_outcome_join_scale.py
tests/test_calibration_schema.py
tests/test_calibration_statistical_integrity.py
tests/test_calibration_v2_live_logging.py
tests/test_calibration_writer_fail_closed.py
tests/test_call_engine_chunk1_fail_closed.py
tests/test_call_engine_layer5_chunk2b.py
tests/test_call_engine_layer5_chunk2c.py
tests/test_call_engine_lifecycle_rewire.py
tests/test_call_prediction_vote.py
tests/test_call_time_warning.py
tests/test_canonical_closeout_issue13.py
tests/test_canonical_contract_layer5_chunk1.py
tests/test_canonical_distances.py
tests/test_canonical_enforcement.py
tests/test_caps_marker_is_line_scoped_v1.py
tests/test_card_direction_integrity.py
tests/test_card_wiring_transport_locks.py
tests/test_cascade_challenger_stack.py
tests/test_cascade_stack_layer5_chunk1.py
tests/test_centralization.py
tests/test_chain_accrual_and_storm1_v1.py
tests/test_chain_gate_v2.py
tests/test_challenger_eval_v1.py
tests/test_charm_book_scope_is_derived_v1.py
tests/test_charm_by_strike_v1.py
tests/test_charm_docstring_states_the_physics_v1.py
tests/test_charm_publishes_one_name_v1.py
tests/test_charm_sign_finite_difference.py
tests/test_charm_vote_gate.py
tests/test_chart_accrual_consumer_v1.py
tests/test_chart_intent_lock_v1.py
tests/test_ci_tooling_dependencies.py
tests/test_claims_are_executed_gate_v1.py
tests/test_classify_schwab_csv_crosswalk.py
tests/test_cleanup_validation_passed_orphans.py
tests/test_client_spot_single_faucet_v1.py
tests/test_clocks_tz_explicit_v1.py
tests/test_coh_sa1_float_consolidation.py
tests/test_coh_sa2_et_authority.py
tests/test_collect_window_law_v1.py
tests/test_confluence_log_drop.py
tests/test_console_reload_url_env.py
tests/test_context_layer.py
tests/test_control_authority_surfaces_v1.py
tests/test_cost_aware_eval_research_smoke_v1.py
tests/test_credential_leak_v1.py
tests/test_daily_scoreboard_rc32_cohort_gate.py
tests/test_daily_system_health_check.py
tests/test_datetime_silent_default_repo_wide.py
tests/test_day_level_gex_study_v1.py
tests/test_db_feature_adapter_layer5_chunk1.py
tests/test_db_health_faucet_precommit_v1.py
tests/test_db_health_v1.py
tests/test_db_maintenance_v1.py
tests/test_db_perf_rc166_v1.py
tests/test_db_safety.py
tests/test_db_sqlite_tier1_retry.py
tests/test_dead_tests_audit_v1.py
tests/test_debt_canonical_paths.py
tests/test_debt_ratchet_policy_v1.py
tests/test_debt_ratchet_read_only_v1.py
tests/test_debug_charm_has_counters.py
tests/test_decide_direction_gate_v1.py
tests/test_decision_gate.py
tests/test_delta_adds_no_debt_v1.py
tests/test_desk_store_v1.py
tests/test_dfr017_multiplier_repo_sweep.py
tests/test_direction_triplet_authority.py
tests/test_distance_option_a_backfill_v1.py
tests/test_duplication_audit_v1.py
tests/test_edge_discovery_fail_closed.py
tests/test_edge_discovery.py
tests/test_ed_server_warn_quiet_window.py
tests/test_em_fail_closed.py
tests/test_empirical_calibration_layer.py
tests/test_empirical_internal_missing.py
tests/test_enforced_check_negative_controls_v1.py
tests/test_eol_style_invariant_v1.py
tests/test_execution_identity_v1.py
tests/test_expiry_fail_closed.py
tests/test_exposure_tab_v1.py
tests/test_f1_input_gates_v1.py
tests/test_f1_labeler_v2_seams.py
tests/test_f1_s4_battery_dst_placebo.py
tests/test_f2_tb_grid_v1.py
tests/test_f39_confluence_missingness.py
tests/test_fast_lane_contract.py
tests/test_feature_contract_mvp.py
tests/test_feature_contract_validation.py
tests/test_feature_leakage_get_recent_snapshots.py
tests/test_feature_leakage_similarity_as_of.py
tests/test_find_cal_ts_rderive.py
tests/test_find_liveui_6_v1.py
tests/test_find_prove_locks_v1.py
tests/test_five_why_reaches_bedrock_v1.py
tests/test_five_why_recursion_lock_v1.py
tests/test_five_why_recursive_lock_v1.py
tests/test_flip_iv_sensitivity_v1.py
tests/test_forces_provenance_v1.py
tests/test_fp24_calibration_colocated_snapshot.py
tests/test_fusion_contract.py
tests/test_fusion_model_input_layer5_chunk1.py
tests/test_fusion_model_input.py
tests/test_fusion_policy_contract_fail_closed.py
tests/test_fusion_policy_contract_layer5_chunk1.py
tests/test_fusion_stack_status_ui.py
tests/test_fusion_temperature_calibration.py
tests/test_fusion_tick_cache.py
tests/test_gamma_conditioned_study_v1.py
tests/test_gamma_fullchain_strikes_v1.py
tests/test_gamma_pin_semantic_split.py
tests/test_gamma_profile_v1.py
tests/test_gate_scope_is_the_git_index_v1.py
tests/test_gex_r1_screen_signal.py
tests/test_git_index_lock_v1.py
tests/test_governance_dashboard.py
tests/test_governance_ui_dashboard.py
tests/test_governed_executor_required_for_active_writes.py
tests/test_governed_outcome_refresh_after_bar_mutation_v1.py
tests/test_governed_stack_contract.py
tests/test_greek_sanitization_v1.py
tests/test_historical_backfill_enrolled_1m_v1.py
tests/test_honesty_guard_v1.py
tests/test_horizon_bar_outcomes.py
tests/test_horizon_tier_contract.py
tests/test_incumbent_eval_v1.py
tests/test_inference_snapshot_l1_equiv_contract.py
tests/test_institutional_closure_gate.py
tests/test_institutional_key_levels.py
tests/test_instrument_identity_and_repair_v1.py
tests/test_isolated_worktree_boundary_v1.py
tests/test_issue14_horizon_training_eligibility.py
tests/test_issue15_ml_horizon_5c.py
tests/test_issue16_ml_horizon_15c.py
tests/test_issue16_normalized_outcome_materialize.py
tests/test_issue16_normalized_training_sync.py
tests/test_issue17_ml_horizon_60c.py
tests/test_issue18_multi_horizon_decision.py
tests/test_issue18_ui_contract.py
tests/test_issue19_option_a_post_validate.py
tests/test_issue19_similarity_viability.py
tests/test_issue20_23_live_bundle.py
tests/test_issue21_similarity_audit.py
tests/test_issue22_logging_universe.py
tests/test_iv_schwab_primary.py
tests/test_key_levels_schwab_zero_open_sweep.py
tests/test_l1_adaptive_thresholds.py
tests/test_l1_cache_lifecycle_validation.py
tests/test_l1_cold_start_transition.py
tests/test_l1_cross_scope_isolation.py
tests/test_l1_fingerprint_scope_integrity.py
tests/test_l1_generation_atomicity.py
tests/test_l1_light_sse.py
tests/test_l1_material_propagation_integrity.py
tests/test_l1_no_flicker.py
tests/test_l1_of_probe_hook.py
tests/test_l1_operational_diagnostics.py
tests/test_l1_order_flow_one_faucet_v1.py
tests/test_l1_overlay_projection_contract.py
tests/test_l1_partial_payload_semantics.py
tests/test_l1_remediation.py
tests/test_l1_sse_backpressure.py
tests/test_l1_sse_guards_client.py
tests/test_l1_sse_scaling_safety.py
tests/test_l1_trade_observation_v1.py
tests/test_l1_type_stability.py
tests/test_level_crosses_wire.py
tests/test_levels_single_producer_v1.py
tests/test_level_test_chip.py
tests/test_lifecycle_rule_core_numeric_contract_v1.py
tests/test_lifecycle_rule_core.py
tests/test_liquidity_engine.py
tests/test_liquidity_tradeable_score.py
tests/test_liquidity_value_engine_chunk1_fail_closed.py
tests/test_liquidity_value_engine_chunk2_atr_fallback_log.py
tests/test_liquidity_value_engine_p1d_prev_trading_day.py
tests/test_live_decision_bundle_tick_triggers.py
tests/test_live_drift_monitoring.py
tests/test_live_market_plane_streaming.py
tests/test_live_ui_a_e.py
tests/test_live_ui_integrity_v1.py
tests/test_logging_universe_snapshot_orphans_v1.py
tests/test_log_law_v1.py
tests/test_lp01_touch_study_v1.py
tests/test_lstm_insufficient_samples.py
tests/test_lstm_sequence_input_layer5_chunk1.py
tests/test_lstm_sequence_input.py
tests/test_m5_additive_source_timeframe_v1.py
tests/test_manual_governance.py
tests/test_market_context_fetch_fail_closed.py
tests/test_market_context_spot_semantics_v1.py
tests/test_market_state_final_confidence_none_preserved.py
tests/test_market_state_numeric_contract_v1.py
tests/test_math_levels_hvl_max_pain.py
tests/test_math_probabilities_volume_contract.py
tests/test_mc_em_anchor.py
tests/test_mc_fusion_adjustment_chunk1_fail_closed.py
tests/test_mc_fusion_adjustment_layer5_mcf1.py
tests/test_mc_fusion_adjustment.py
tests/test_mc_fusion_fail_closed.py
tests/test_mcsi_spot_fusion_adjustment.py
tests/test_measure_cold_start_stages_v1.py
tests/test_measure_cold_start_v1.py
tests/test_measure_post_fix_theta_v1.py
tests/test_mechanism_claims_cite_a_source_v1.py
tests/test_mega1_traceable_audit.py
tests/test_mega2_traceable_audit.py
tests/test_mega3_traceable_audit.py
tests/test_mega4_traceable_audit.py
tests/test_meta_xgb_tb_ingest_v1.py
tests/test_mhmlb_namespace_v1.py
tests/test_migrate_snapshots_drop_retired_horizons_v1.py
tests/test_migrate_snapshots_schema_repair_v1.py
tests/test_ml_data_common_et_helpers.py
tests/test_ml_feature_provenance.py
tests/test_ml_feature_schema_parity.py
tests/test_ml_item4_fleet_migration.py
tests/test_ml_predict_chunk1_fail_closed.py
tests/test_ml_predict_fail_closed.py
tests/test_ml_predict_horizon_registry.py
tests/test_ml_train_readonly_arrays.py
tests/test_ml_train_rth_authority.py
tests/test_model_accuracy_wire.py
tests/test_model_contract_enforcement.py
tests/test_model_edge_absent_is_not_zero_v1.py
tests/test_model_registry_reload_after_promote.py
tests/test_model_serve_policy.py
tests/test_module_a_adapter_numeric_contract_v1.py
tests/test_money_path_orphan_keys_v1.py
tests/test_money_path_roster.py
tests/test_monte_carlo_chunk1_fail_closed.py
tests/test_movement_target_phase_eval_contract_v1.py
tests/test_movement_target_v1.py
tests/test_movement_target_v2_contract.py
tests/test_multi_horizon_decision_numeric_contract_v1.py
tests/test_multi_horizon_ml_bundle_numeric_contract.py
tests/test_multiplier_no_default.py
tests/test_mvp1_mvp_zone_returns_none.py
tests/test_mvp_source_coercion_layer5_chunk1.py
tests/test_news_events_drop.py
tests/test_non_trading_row_quarantine_v1.py
tests/test_no_promote_candidate_in_scheduler.py
tests/test_notification_delivery_dedup.py
tests/test_notification_delivery.py
tests/test_numeric_contract_tier15.py
tests/test_ohlcv_schwab_first.py
tests/test_one_faucet_live_v1.py
tests/test_one_producer_gate_v1.py
tests/test_oof_stacker.py
tests/test_open_interest_contract.py
tests/test_open_item_law_not_ratchet_v1.py
tests/test_operable_surface_gate.py
tests/test_operating_process_lock_v1.py
tests/test_operational_policy_drift_reasons.py
tests/test_operational_policy.py
tests/test_operator_law_guard_repo_scope_v1.py
tests/test_operator_path_privacy.py
tests/test_option_volume_is_live_v1.py
tests/test_order_flow_engine_chunk1_fail_closed.py
tests/test_order_flow_engine_chunk2_or_fallthrough.py
tests/test_order_flow_engine_chunk3_present_weighted.py
tests/test_order_flow_engine_chunk4_label_defaults.py
tests/test_order_flow_live_state_tape_contract.py
tests/test_order_flow_microstructure_v1.py
tests/test_order_flow_schwab_first.py
tests/test_order_flow_streaming_disconnect.py
tests/test_order_flow_tape_contract.py
tests/test_order_flow_volume_contract.py
tests/test_orphan_dict_keys_data_sources_v1.py
tests/test_panic_disable_auto_promote.py
tests/test_parallel_stack_runtime.py
tests/test_parallel_stack_schema_chunk1_fail_closed.py
tests/test_partial_remediations_closed_v1.py
tests/test_path_authority_v1.py
tests/test_payload_audit.py
tests/test_perf_proof_harness.py
tests/test_persistent_ticker_enrollment_v1.py
tests/test_phase2a_and_producer_probes_v1.py
tests/test_phase2a_premarket_carries_canonical_v1.py
tests/test_phase2a_price_level_snapshot_v1.py
tests/test_phase2a_snapshot_integrity_v1.py
tests/test_phase4c_equivalence_smoke.py
tests/test_pilot_prereg_framework_binding.py
tests/test_pilot_step3_data_loader.py
tests/test_pilot_step3_events.py
tests/test_pilot_step3_sigma_contract.py
tests/test_pilot_step3_trade_labels.py
tests/test_pin_neutral_1m_5m_divergence_audit_v1.py
tests/test_pinning_score_needs_a_pin_v1.py
tests/test_planes_l1_runtime.py
tests/test_playwright_enforcement.py
tests/test_playwright_must_run.py
tests/test_plus_player_law_v1.py
tests/test_pm_full_coverage_lock_v1.py
tests/test_pm_verify_repo_lock_v1.py
tests/test_position_sizing_policy.py
tests/test_post_promote_verify_and_rollback.py
tests/test_pred_1c_eddb_and_audit_contract_v1.py
tests/test_pred_1c_horizon_persistence_v1.py
tests/test_prediction_engine_chunk1_fail_closed.py
tests/test_prediction_engine_layer5_mcf2.py
tests/test_pretooluse_guard_repo_scope_v1.py
tests/test_pricehistory_payload_key_required.py
tests/test_protected_paths_v1.py
tests/test_purity_canonical_single_path.py
tests/test_quarantine_outside_window_v1.py
tests/test_radar_levels_provenance_v1.py
tests/test_radar_two_sided_wall_v1.py
tests/test_rc191_zero_debt_product_v1.py
tests/test_rc193_morning_full_calendar_gate_v1.py
tests/test_rc199_charm_forces_unlock_v1.py
tests/test_rc31_session_universe_v1.py
tests/test_rc6_normalized_blob_repoint_v1.py
tests/test_rc_document_without_resolve_v1.py
tests/test_rc_status_vocabulary_v1.py
tests/test_realized_contract_eval_layer5.py
tests/test_realized_contract_lifecycle_rewire.py
tests/test_regime_engine_chunk1_find_re1.py
tests/test_regime_mvp_context_layer5_chunk1.py
tests/test_rehab_daily_scan_v1.py
tests/test_rehab_plan_v1.py
tests/test_repair_canonical_1m_bars_for_outcomes.py
tests/test_repair_canonical_1m_edge_carry_v1.py
tests/test_repair_canonical_1m_interior_gaps_v1.py
tests/test_replay_hold_bars.py
tests/test_replay_money_path_probe.py
tests/test_replay_signal_input_v1.py
tests/test_repo_scoreboard_v1.py
tests/test_repo_semantic_purity.py
tests/test_repo_sweep_error_propagation_v1.py
tests/test_repo_sweep_lrc_nan_guards_v1.py
tests/test_repo_sweep_magic_thresholds_v1.py
tests/test_resample_to_1m_skips_missing_ohlc.py
tests/test_reset_guard_v1.py
tests/test_reversion_rule_a_v1.py
tests/test_rth_completeness_check_v1.py
tests/test_rules_engine_chunk1_fail_closed.py
tests/test_run_once_exit_code_aggregation.py
tests/test_run_provenance_v1.py
tests/test_scheduler_arch_competition_integration.py
tests/test_scheduler_log_loss_winner_field.py
tests/test_scheduler_user_tickers_return_type.py
tests/test_schwab_auth_context_scope.py
tests/test_schwab_client_import_boundary.py
tests/test_schwab_days_to_expiration_contract.py
tests/test_schwab_field_dictionary_classifier_v1.py
tests/test_schwab_field_dictionary_sync_v1.py
tests/test_schwab_gate_fail_closed_working_sync_v1.py
tests/test_schwab_market_derivation_catalog_v1.py
tests/test_schwab_market_field_semantics_lock_v1.py
tests/test_scoreboard_stale_is_withheld_v1.py
tests/test_scorecard_stale_fails_closed_v1.py
tests/test_score_option_expression_greek_sentinel.py
tests/test_server_iv_fail_closed.py
tests/test_server_quote_source_contract.py
tests/test_server_rest_cum_delta_contract.py
tests/test_server_schwab_dte_snapshot.py
tests/test_server_sweep_score_post_build_market_state.py
tests/test_session_calendar_authority_v1.py
tests/test_session_log_drop.py
tests/test_shared_input_two_questions_v1.py
tests/test_shared_sequence_context_layer5_chunk1.py
tests/test_shared_sequence_context.py
tests/test_shuffled_label_control_v1.py
tests/test_signal_engineering_fail_closed.py
tests/test_signal_engineering.py
tests/test_signal_layer_v1.py
tests/test_signals_canonical_forecast_layer5.py
tests/test_signals_fail_closed.py
tests/test_silent_zero_reasons_are_true_v1.py
tests/test_similarity_feature_audit.py
tests/test_similarity_feature_survivorship.py
tests/test_similarity_feature_universe.py
tests/test_single_producer_batch_f02_f13_v1.py
tests/test_spot_authority_v1.py
tests/test_spot_binding_single_payload_v1.py
tests/test_spot_fail_closed_contract.py
tests/test_sqlite_wal_contract_v1.py
tests/test_stack_bundle_eval_metrics_pack_v1.py
tests/test_stack_bundle_eval_v1.py
tests/test_stack_integrity_v1_layer5_chunk1.py
tests/test_stack_integrity_v1.py
tests/test_stack_wire_0_v1.py
tests/test_stack_wire_1_v1.py
tests/test_stack_wire_2_v1.py
tests/test_stack_wire_3_ui_phase3_closure.py
tests/test_stack_wire_3_v1.py
tests/test_stack_wire_4_cand_ui_fusion_gate.py
tests/test_stack_wire_4_v1.py
tests/test_stack_wire_5_v1.py
tests/test_stack_wire_6b_v1.py
tests/test_stack_wire_6c_v1.py
tests/test_stack_wire_6_v1.py
tests/test_stage1_causal_label_contract.py
tests/test_stage1_ct_session.py
tests/test_stage1_golden_expansion.py
tests/test_stage1_session_cohort_contract.py
tests/test_stage1_target_registry.py
tests/test_static_index_html_confidence_labels.py
tests/test_stop_guard_v1.py
tests/test_stream_capture_daemon_v1.py
tests/test_stream_spine_v1.py
tests/test_strict_core_freshness_env.py
tests/test_structural_eval_v1.py
tests/test_study_calendar_gates_v1.py
tests/test_study_volume_vs_oi_terrain_v1.py
tests/test_t5_sse_db_contention.py
tests/test_terrain_atr_radar_v1.py
tests/test_terrain_backtest_report_v1.py
tests/test_terrain_engine_v1.py
tests/test_terrain_per_strike_live_v1.py
tests/test_terrain_read_v1.py
tests/test_tier3_design.py
tests/test_time_et_authority.py
tests/test_traceable_derivation_schema.py
tests/test_track_b_calibration_backfill_insert.py
tests/test_training_cache_layer5_chunk1.py
tests/test_training_cache_layer5.py
tests/test_training_canonical_input.py
tests/test_training_manifest_lineage_sync.py
tests/test_training_outcome_enum.py
tests/test_training_pipeline_status_v1.py
tests/test_training_sample_weighting_canonical.py
tests/test_transformer_sequence_input.py
tests/test_turn_self_audit_contract_v1.py
tests/test_typed_state_measurements_v1.py
tests/test_ui_mockup_lock_v1.py
tests/test_universal_card_fidelity_runtime.py
tests/test_universality_drift_closure.py
tests/test_universal_ticker_scope_v1.py
tests/test_v2_a1_calibration.py
tests/test_v2_a1_conformal_artifact_attachment.py
tests/test_v2_a1_conformal_promotion.py
tests/test_v2_a1_conformal.py
tests/test_v2_a1_ev_bounds.py
tests/test_v2_a1_execution_ev.py
tests/test_v2_a1_isotonic_calibration_attachment.py
tests/test_v2_a1_primary_horizon_propagation.py
tests/test_v2_a1_raw_probability.py
tests/test_v2_a2_lifecycle_sidecar.py
tests/test_v2_a2_option_expression.py
tests/test_v2_a2_pin_risk.py
tests/test_v2_a2_replay_labels.py
tests/test_v2_advisory_backfill.py
tests/test_v2_decision_schema.py
tests/test_v2_desk_confidence_adapter.py
tests/test_v2_post_trade_attribution.py
tests/test_v2_tier_c_payload.py
tests/test_validate_outcome_join_fail_closed.py
tests/test_vendor_coercion_detector.py
tests/test_vendor_field_coercion_completeness.py
tests/test_venv_parity_v1.py
tests/test_venv_wrapper_propagates_exit_v1.py
tests/test_verification_harness.py
tests/test_vix_tier_authority.py
tests/test_volatility_regime_chunk1_fail_closed.py
tests/test_volatility_regime_fail_closed.py
tests/test_vol_observability_v1.py
tests/test_worktree_handoff_v1.py
tests/test_world_data_ingest_v1.py
tests/test_writer_drift_lock_v1.py
tests/test_xgb_envelope_ticker_required.py
tests/test_xgb_inference_snapshot_v1_input.py
tests/test_xgb_model_input_layer5_chunk1.py
```

---

## 2. COMPLETE `tests/conftest.py`

246 lines. Entire file:

```python
"""
Pytest: allow EdDB against temp paths (non-canonical) without per-call flags.

Production processes must NOT set ED_CONSOLE_ALLOW_NONCANONICAL_DB globally.

Schwab placeholders (CI / adversarial): ``server`` calls ``build_config`` at import
time. Objective-audit adversarial tests import ``server`` without live Schwab access.
Module-level setdefault here runs before test collection so ``import server`` never
requires real GitHub secrets. Production uvicorn startup is unchanged — these vars are
not set outside pytest. Fail-closed without secrets is locked by
``test_build_config_fail_closed_without_secrets`` (monkeypatch.delenv).
"""
from __future__ import annotations

import os
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

import pytest

os.environ.setdefault("ED_CONSOLE_ALLOW_NONCANONICAL_DB", "1")

# GOV-GATE-PERF-V1: the governance gate cache is a CLI-entry-point optimization.
# Tests must always exercise REAL compute — many inject failures via in-process
# monkeypatched state that file-identity cache keys cannot represent, so a stored
# success must never satisfy an injected-failure test. Force-no-cache is the
# cache's own designated verification mode (tools/governance_gate_cache.py).
os.environ.setdefault("ED_GATE_CACHE_DISABLE", "1")

# Hermetic Schwab config for pytest only — not real credentials; no network at import.
os.environ.setdefault("SCHWAB_API_KEY", "ci-placeholder-api-key")
os.environ.setdefault("SCHWAB_APP_SECRET", "ci-placeholder-app-secret")
os.environ.setdefault("SCHWAB_CALLBACK_URL", "https://127.0.0.1:8182")


def pytest_configure(config) -> None:
    """xdist workers must not share one console DB file.

    `db.DB_PATH` is resolved at import from ED_CONSOLE_DB. Each worker is a fresh
    process; set the override here (before test modules import db) so schema-init
    and writes cannot collide. Serial pytest is unchanged (no PYTEST_XDIST_WORKER).
    """
    worker = os.environ.get("PYTEST_XDIST_WORKER")
    if not worker:
        return
    root = Path(os.environ.get("TMPDIR") or "/tmp") / f"ed-pytest-{worker}-{os.getpid()}"
    root.mkdir(parents=True, exist_ok=True)
    db = root / "ed_console.db"
    db.touch()
    os.environ["ED_CONSOLE_DB"] = str(db)
    os.environ["ED_CONSOLE_ALLOW_NONCANONICAL_DB"] = "1"


@pytest.fixture(autouse=True)
def _no_fusion_temperature_calibration(monkeypatch):
    """Hermetic tests: never read the operator's live fusion calibration artifact.

    models/calibration/fusion_temperature.json is machine-fit operator state; with
    it present, every bundle-path test would change behavior by environment. Tests
    that exercise the serve hook monkeypatch _applied_fusion_temperatures themselves
    (their setattr runs after this fixture and wins).
    """
    import multi_horizon_ml_bundle as mhb

    monkeypatch.setattr(mhb, "_applied_fusion_temperatures", lambda: {})


@pytest.fixture(autouse=True)
def _equal_mh_pool_weights(monkeypatch):
    """Hermetic tests: never read the operator's live calibration DB for ALL-card
    pool weights. Equal weights = unweighted log opinion pool (the fail-closed
    default). Tests exercising skill weighting pass pool_weights explicitly or
    monkeypatch after this fixture (their setattr wins)."""
    import multi_horizon_decision as mhd

    monkeypatch.setattr(
        mhd,
        "_horizon_skill_weights_cached",
        lambda: ({h: 1.0 / len(mhd.PRODUCT_HORIZONS) for h in mhd.PRODUCT_HORIZONS}, True),
    )


@pytest.fixture(scope="session", autouse=True)
def _ensure_console_db_snapshots_1m_normalized_schema():
    """Hermetic pytest/CI: governance live-drift reads ``db_training_fingerprint`` on ``DB_PATH``."""
    from db import ensure_console_db_training_schema

    ensure_console_db_training_schema()


@pytest.fixture(autouse=True)
def _ensure_console_db_schema_before_each_test():
    """Playwright / early tests may touch ``data/ed_console.db`` without normalized schema."""
    from db import ensure_console_db_training_schema

    ensure_console_db_training_schema()


@pytest.fixture(scope="session")
def _admitted_decision_registry_path(tmp_path_factory):
    """Session-scoped registry file that admits the decision path (test default)."""
    import json

    from decision_gate import (
        DECISION_PATH_COMPONENT,
        REQUIRED_EVIDENCE_FIELDS,
        SCHEMA_VERSION,
    )

    doc = {
        "schema_version": SCHEMA_VERSION,
        "admissions": [
            {
                "component": DECISION_PATH_COMPONENT,
                "status": "ADMITTED",
                "evidence": {f: f"pytest-fixture:{f}" for f in REQUIRED_EVIDENCE_FIELDS},
                "operator_decision": {"date": "2026-01-01", "decided_by": "pytest-fixture"},
            }
        ],
    }
    p = tmp_path_factory.mktemp("decision_gate") / "decision_path_admissions.json"
    p.write_text(json.dumps(doc), encoding="utf-8")
    return p


@pytest.fixture(autouse=True)
def _decision_path_admitted_by_default(monkeypatch, _admitted_decision_registry_path):
    """Hermetic tests: stack/policy tests exercise compute_call behavior, not the
    charter admission gate — run them with an admitted registry so a directional
    call is reachable. Production default (committed registry is EMPTY → forced
    WAIT) is locked explicitly by tests/test_decision_gate.py, which overrides
    ED_DECISION_ADMISSIONS_PATH / passes explicit paths (its setenv wins)."""
    monkeypatch.setenv("ED_DECISION_ADMISSIONS_PATH", str(_admitted_decision_registry_path))


def most_recent_trading_day_et(*, on_or_before: date | None = None) -> date:
    """The newest ET date the market calendar admits, at or before `on_or_before` (today).

    RC-306. Fixtures that need a session date had two obvious sources and both are wrong.
    A hard-coded date goes stale against readers that default to today — that broke twice
    across 2026-07-30. The wall clock does not go stale, but it does not know about
    weekends or holidays, and RC-278 gave the accrual writers `is_trading_day_et` as their
    calendar authority, so on a Saturday a clock-derived fixture hands the writer a date
    the writer is REQUIRED to reject. Five tests then failed two days in seven while
    reporting nothing about the code.

    The third source is the authority itself. Drawing the fixture date from the same
    function the code validates against means the test can no longer disagree with the
    calendar, and there is no literal to rot.
    """
    from time_et import ET, is_trading_day_et

    day = on_or_before or datetime.now(ET).date()
    for _ in range(14):          # the longest market closure gap is far under two weeks
        if is_trading_day_et(day.isoformat()):
            return day
        day -= timedelta(days=1)
    raise AssertionError(
        f"no trading day found in the 14 ET days before {on_or_before or 'today'} — "
        "the market calendar authority (time_et.is_trading_day_et) is answering False "
        "for every date, which is a calendar defect, not a fixture one")


@pytest.fixture(autouse=True)
def _clear_quote_memo_between_tests():
    """RC-314: `server._quote_memo` is process-global and outlives every pytest boundary.

    `test_rest_fast_quote_spot_fail_closed_not_zero` passed as a single node and FAILED as
    part of its own file, with `quote_attempts=0` in the log: a sibling had left SPY at
    501.25 in the memo, `_memoized_quote_response` served it, and the fail-closed path under
    test never ran. tmp_path, fresh DBs and monkeypatch all isolate what the TEST owns; a
    cache owned by the import is invisible to them.

    Guarded on `server` already being imported, so the tests that never touch it pay nothing
    and none of them triggers a server import it did not ask for.
    """
    srv = sys.modules.get("server")
    memo = getattr(srv, "_quote_memo", None) if srv is not None else None
    if isinstance(memo, dict):
        memo.clear()
    yield


def in_window_ts(hour: int = 10, minute: int = 0, *, span_minutes: int = 0) -> float:
    """A bar timestamp the COLLECT-WINDOW LAW admits: RTH, on a real trading day.

    RC-306, shared. Fixtures reached the write seam three different wrong ways — a wall
    clock (fails on weekends), a literal epoch from a year the calendar does not cover, and
    a synthetic small integer like 1_020_000.0, which is 1970-01-12. RC-214's collect-window
    law narrowed `upsert_1m_bars` to (555, min(975, close+15)] on trading days, so all three
    are refused, no bars are written, and the outcome columns the test asserts on come back
    None — a true statement about the calendar, not about the code.

    `span_minutes` is the length of the bar series that will start here: it is checked
    against the window's end so a fixture cannot half-fit and fail on its tail alone.
    """
    from time_et import COLLECT_WINDOW_END_MINS, COLLECT_WINDOW_START_MINS, ET

    start = hour * 60 + minute
    if start <= COLLECT_WINDOW_START_MINS:
        raise AssertionError(
            f"{hour:02d}:{minute:02d} ET is at or before the collect window's open "
            f"({COLLECT_WINDOW_START_MINS} minutes); the seam would refuse these bars")
    if start + span_minutes > COLLECT_WINDOW_END_MINS:
        raise AssertionError(
            f"a {span_minutes}-minute series from {hour:02d}:{minute:02d} ET runs past the "
            f"window's close ({COLLECT_WINDOW_END_MINS} minutes); start it earlier")
    day = most_recent_completed_session_et()
    return datetime(day.year, day.month, day.day, hour, minute, tzinfo=ET).timestamp()


def most_recent_completed_session_et() -> date:
    """The newest ET trading day whose COLLECT WINDOW has already CLOSED.

    A trading day is not the same thing as a FINISHED trading day, and every fixture that
    reaches this helper writes a forward-running bar series and then asserts on an outcome
    computed from its tail. `most_recent_trading_day_et` answers "today" from the moment
    the date rolls over, so between midnight and the window's close those fixtures were
    generating bars for a session that HAS NOT HAPPENED YET: the writer accepts them, the
    outcome columns come back None, and the test reports a true statement about the clock
    instead of about the code.

    That is the same defect a previous repair had already closed in ONE fixture. It
    survived here because the fix was applied to the instance rather than to the shared
    authority the other fixtures draw from — the exact "fixed the instance, not the class"
    loop RC-286's docstring names. The completion rule now lives in one place, so a fixture
    cannot anchor to an unfinished session by forgetting to ask.
    """
    from time_et import COLLECT_WINDOW_END_MINS, ET

    now = datetime.now(ET)
    day = most_recent_trading_day_et()
    if day == now.date() and (now.hour * 60 + now.minute) <= COLLECT_WINDOW_END_MINS:
        day = most_recent_trading_day_et(on_or_before=day - timedelta(days=1))
    return day


@pytest.fixture
def fresh_ablation_static_lock_index():
    """Opt-in reset for tests that mutate manifest/DB/spec inputs or fake the index builder."""
    from tools.ablation_static_lock_index import reset_ablation_static_lock_index_for_tests

    reset_ablation_static_lock_index_for_tests()
    yield
    reset_ablation_static_lock_index_for_tests()
```

### Second conftest (`tests/archive/conftest.py`)

```python
# Archived legacy section audit tests — not collected (categorical inventory superseded).
collect_ignore = ["legacy_section_audits_v1"]
```

### Hooks / fixtures / module setup in the root file

| Kind | Name |
|---|---|
| module env | `ED_CONSOLE_ALLOW_NONCANONICAL_DB`, `ED_GATE_CACHE_DISABLE`, `SCHWAB_*` setdefault |
| hook | `pytest_configure` (xdist per-worker `ED_CONSOLE_DB`) |
| autouse fixture | `_no_fusion_temperature_calibration` |
| autouse fixture | `_equal_mh_pool_weights` |
| session autouse | `_ensure_console_db_snapshots_1m_normalized_schema` |
| autouse fixture | `_ensure_console_db_schema_before_each_test` |
| session fixture | `_admitted_decision_registry_path` |
| autouse fixture | `_decision_path_admitted_by_default` |
| autouse fixture | `_clear_quote_memo_between_tests` |
| opt-in fixture | `fresh_ablation_static_lock_index` |
| helpers (not fixtures) | `most_recent_trading_day_et`, `in_window_ts`, `most_recent_completed_session_et` |

No `pytest_addoption`, no markers registered, no `addopts` in this file.

---

## 3. SAMPLE DUPLICATES

**Exact filename twins: none.**

- `test_v1_*.py`: **0 files**. There is no `test_v1_*` / `test_v2_*` pair.
- `*_v1.py` vs `*_v2.py` same-stem twins: **0** (checked by replacing `_v1.` with `_v2.` on every `tests/**/*.py` name).
- `test_a1_*` vs `test_a2_*` same-stem twins: **0**. The `a1` and `a2` prefixes are different topics, not versions of each other.

### `test_v2_*.py` (no v1 twins)

```
tests/test_v2_a1_calibration.py
tests/test_v2_a1_conformal_artifact_attachment.py
tests/test_v2_a1_conformal_promotion.py
tests/test_v2_a1_conformal.py
tests/test_v2_a1_ev_bounds.py
tests/test_v2_a1_execution_ev.py
tests/test_v2_a1_isotonic_calibration_attachment.py
tests/test_v2_a1_primary_horizon_propagation.py
tests/test_v2_a1_raw_probability.py
tests/test_v2_a2_lifecycle_sidecar.py
tests/test_v2_a2_option_expression.py
tests/test_v2_a2_pin_risk.py
tests/test_v2_a2_replay_labels.py
tests/test_v2_advisory_backfill.py
tests/test_v2_decision_schema.py
tests/test_v2_desk_confidence_adapter.py
tests/test_v2_post_trade_attribution.py
tests/test_v2_tier_c_payload.py
```

### `test_a1_*.py` (conformal/isotonic artifacts; not paired with a2)

```
tests/test_a1_conformal_artifact_loader.py
tests/test_a1_conformal_artifact_production.py
tests/test_a1_isotonic_artifact_loader.py
tests/test_a1_isotonic_artifact_production.py
tests/test_a1_isotonic_runtime.py
```

### `test_a2_*.py` (market-state / session / theta; not paired with a1)

```
tests/test_a2_eod_force_exit.py
tests/test_a2_market_state_proof_row_completeness.py
tests/test_a2_price_precedence.py
tests/test_a2_session_calendar.py
tests/test_a2_staleness_trade_time_fallback.py
tests/test_a2_theta_schwab_first.py
```

### `test_*_artifact_*.py`

```
tests/test_a1_conformal_artifact_loader.py
tests/test_a1_conformal_artifact_production.py
tests/test_a1_isotonic_artifact_loader.py
tests/test_a1_isotonic_artifact_production.py
tests/test_v2_a1_conformal_artifact_attachment.py
```

Three examples, full content:

#### `tests/test_a1_conformal_artifact_loader.py`

```python
from __future__ import annotations

import json
from pathlib import Path

from calibration.a1_conformal_artifact_production import (
    augment_conformal_artifact_with_lifecycle_fields,
    current_pointer_path,
    write_artifact_atomically,
    update_current_pointer_atomically,
)
from v2_decision.a1_conformal_artifact_loader import load_a1_conformal_artifact


def _artifact(**overrides) -> dict:
    base = {
        "schema_version": "1",
        "calibration_run_id": "cal-test-run",
        "calibration_window_id": "window-test",
        "conformal_run_id": "cal-test-run-conformal",
        "module_id": "A",
        "expression_profile_id": "A1",
        "horizon": "5c",
        "status": "ok",
        "interval_model": {"type": "split_conformal_probability_band", "score_quantile": 0.1},
        "coverage_evaluation": {
            "source": "separate_evaluation_predictions",
            "same_rows_as_quantile_fit": False,
        },
        "evaluation_diagnostics": {"empirical_coverage": 0.9},
        "sample_gate": {"aggregate_holdout": {"sufficient_sample": True, "n": 500}},
    }
    base.update(overrides)
    return augment_conformal_artifact_with_lifecycle_fields(
        conformal_artifact=base,
        ticker=str(overrides.pop("lifecycle_ticker", "SPY")),
        governed_max_age_seconds=float(overrides.pop("governed_max_age_seconds", 3600)),
        generated_at_epoch_seconds=float(overrides.pop("generated_at_epoch_seconds", 1000)),
        calibration_lineage_id=str(overrides.pop("calibration_lineage_id", "cal-test-run:hash")),
    )


def _write_pointer_artifact(tmp_path: Path, artifact: dict) -> Path:
    data_root = tmp_path / "data"
    artifact_path = (
        data_root
        / "v2_calibration"
        / "conformal"
        / "A"
        / "A1"
        / "SPY"
        / "5c"
        / "cal-test-run.json"
    )
    write_artifact_atomically(artifact=artifact, output_path=artifact_path)
    update_current_pointer_atomically(
        artifact_relative_path="v2_calibration/conformal/A/A1/SPY/5c/cal-test-run.json",
        pointer_path=current_pointer_path(ticker="SPY", horizon="5c", data_root=data_root),
    )
    return artifact_path


def test_load_returns_artifact_when_pointer_and_eligibility_pass(tmp_path, monkeypatch):
    artifact = _artifact()
    _write_pointer_artifact(tmp_path, artifact)
    monkeypatch.chdir(tmp_path)

    loaded = load_a1_conformal_artifact(ticker="SPY", horizon="5c", now_epoch_seconds=1100)

    assert loaded == artifact


def test_load_returns_none_when_pointer_missing(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    assert load_a1_conformal_artifact(ticker="SPY", horizon="5c", now_epoch_seconds=1100) is None


def test_load_returns_none_when_pointer_points_to_nonexistent_artifact(tmp_path, monkeypatch):
    pointer = current_pointer_path(ticker="SPY", horizon="5c", data_root=tmp_path / "data")
    update_current_pointer_atomically(
        artifact_relative_path="v2_calibration/conformal/A/A1/SPY/5c/missing.json",
        pointer_path=pointer,
    )
    monkeypatch.chdir(tmp_path)

    assert load_a1_conformal_artifact(ticker="SPY", horizon="5c", now_epoch_seconds=1100) is None


def test_load_returns_none_when_artifact_schema_version_mismatch(tmp_path, monkeypatch):
    artifact = _artifact(schema_version="bad")
    _write_pointer_artifact(tmp_path, artifact)
    monkeypatch.chdir(tmp_path)

    assert load_a1_conformal_artifact(ticker="SPY", horizon="5c", now_epoch_seconds=1100) is None


def test_load_returns_none_when_lifecycle_schema_version_mismatch(tmp_path, monkeypatch):
    artifact = _artifact()
    artifact["artifact_lifecycle_schema_version"] = "bad"
    _write_pointer_artifact(tmp_path, artifact)
    monkeypatch.chdir(tmp_path)

    assert load_a1_conformal_artifact(ticker="SPY", horizon="5c", now_epoch_seconds=1100) is None


def test_load_returns_none_when_ticker_universe_excludes_requested_ticker(tmp_path, monkeypatch):
    artifact = _artifact(lifecycle_ticker="QQQ")
    _write_pointer_artifact(tmp_path, artifact)
    monkeypatch.chdir(tmp_path)

    assert load_a1_conformal_artifact(ticker="SPY", horizon="5c", now_epoch_seconds=1100) is None


def test_load_returns_none_when_horizon_mismatch(tmp_path, monkeypatch):
    artifact = _artifact(horizon="15c")
    _write_pointer_artifact(tmp_path, artifact)
    monkeypatch.chdir(tmp_path)

    assert load_a1_conformal_artifact(ticker="SPY", horizon="5c", now_epoch_seconds=1100) is None


def test_load_returns_none_when_artifact_stale_per_governed_max_age(tmp_path, monkeypatch):
    artifact = _artifact(governed_max_age_seconds=10, generated_at_epoch_seconds=1000)
    _write_pointer_artifact(tmp_path, artifact)
    monkeypatch.chdir(tmp_path)

    assert load_a1_conformal_artifact(ticker="SPY", horizon="5c", now_epoch_seconds=1011) is None


def test_load_returns_none_when_artifact_json_malformed(tmp_path, monkeypatch):
    artifact_path = _write_pointer_artifact(tmp_path, _artifact())
    artifact_path.write_text("{not json", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    assert load_a1_conformal_artifact(ticker="SPY", horizon="5c", now_epoch_seconds=1100) is None


def test_load_returns_none_when_required_field_missing(tmp_path, monkeypatch):
    artifact = _artifact()
    artifact.pop("calibration_lineage_id")
    _write_pointer_artifact(tmp_path, artifact)
    monkeypatch.chdir(tmp_path)

    assert load_a1_conformal_artifact(ticker="SPY", horizon="5c", now_epoch_seconds=1100) is None


def test_load_does_not_raise_for_unexpected_io_failure(tmp_path, monkeypatch):
    _write_pointer_artifact(tmp_path, _artifact())
    monkeypatch.chdir(tmp_path)

    def fail_read_text(self, *args, **kwargs):
        raise OSError("simulated io failure")

    monkeypatch.setattr(Path, "read_text", fail_read_text)

    assert load_a1_conformal_artifact(ticker="SPY", horizon="5c", now_epoch_seconds=1100) is None


def test_loader_uses_now_epoch_seconds_parameter_when_provided(tmp_path, monkeypatch):
    artifact = _artifact(governed_max_age_seconds=10, generated_at_epoch_seconds=1000)
    _write_pointer_artifact(tmp_path, artifact)
    monkeypatch.chdir(tmp_path)

    assert load_a1_conformal_artifact(ticker="SPY", horizon="5c", now_epoch_seconds=1005) == artifact
    assert load_a1_conformal_artifact(ticker="SPY", horizon="5c", now_epoch_seconds=1011) is None


def test_load_returns_none_when_pointer_json_malformed(tmp_path, monkeypatch):
    pointer = current_pointer_path(ticker="SPY", horizon="5c", data_root=tmp_path / "data")
    pointer.parent.mkdir(parents=True, exist_ok=True)
    pointer.write_text(json.dumps({"not_artifact_relative_path": "x"}), encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    assert load_a1_conformal_artifact(ticker="SPY", horizon="5c", now_epoch_seconds=1100) is None
```

#### `tests/test_a1_isotonic_artifact_loader.py`

```python
from __future__ import annotations

import json
from pathlib import Path

from calibration.a1_conformal_artifact_production import (
    augment_artifact_with_lifecycle_fields,
    current_pointer_path,
    update_current_pointer_atomically,
    write_artifact_atomically,
)
from v2_decision.a1_isotonic_artifact_loader import load_a1_isotonic_artifact


def _artifact(**overrides) -> dict:
    lifecycle_ticker = overrides.pop("lifecycle_ticker", "SPY")
    governed_max_age_seconds = overrides.pop("governed_max_age_seconds", 3600)
    generated_at_epoch_seconds = overrides.pop("generated_at_epoch_seconds", 1000)
    calibration_lineage_id = overrides.pop("calibration_lineage_id", "cal-test-run:hash")
    base = {
        "schema_version": "1",
        "calibration_run_id": "cal-test-run",
        "calibration_window_id": "window-test",
        "module_id": "A",
        "expression_profile_id": "A1",
        "horizon": "5c",
        "method": "isotonic_regression",
        "raw_probability_field": "v2_decision.decision.P_entry_success",
        "target_label": "outcome_5c_direction_matches_v2_direction",
        "sample_gate": {"aggregate_holdout": {"sufficient_sample": True, "n": 500}},
        "window": {
            "train_start": 0,
            "train_end": 1,
            "calibration_start": 1,
            "calibration_end": 2,
            "holdout_start": 2,
            "holdout_end": 3,
        },
        "status": "ok",
        "reason": None,
        "model": {"type": "isotonic_regression", "x_thresholds": [0.0, 1.0], "y_thresholds": [0.2, 0.8]},
    }
    base.update(overrides)
    return augment_artifact_with_lifecycle_fields(
        artifact=base,
        ticker=str(lifecycle_ticker),
        governed_max_age_seconds=float(governed_max_age_seconds),
        generated_at_epoch_seconds=float(generated_at_epoch_seconds),
        calibration_lineage_id=str(calibration_lineage_id),
    )


def _write_pointer_artifact(tmp_path: Path, artifact: dict) -> Path:
    data_root = tmp_path / "data"
    artifact_path = (
        data_root
        / "v2_calibration"
        / "isotonic"
        / "A"
        / "A1"
        / "SPY"
        / "5c"
        / "cal-test-run.json"
    )
    write_artifact_atomically(artifact=artifact, output_path=artifact_path)
    update_current_pointer_atomically(
        artifact_relative_path="v2_calibration/isotonic/A/A1/SPY/5c/cal-test-run.json",
        pointer_path=current_pointer_path(ticker="SPY", horizon="5c", data_root=data_root, artifact_kind="isotonic"),
    )
    return artifact_path


def test_load_returns_isotonic_artifact_when_pointer_and_eligibility_pass(tmp_path, monkeypatch):
    artifact = _artifact()
    _write_pointer_artifact(tmp_path, artifact)
    monkeypatch.chdir(tmp_path)

    loaded = load_a1_isotonic_artifact(ticker="SPY", horizon="5c", now_epoch_seconds=1100)

    assert loaded == artifact


def test_load_returns_none_when_isotonic_pointer_missing(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    assert load_a1_isotonic_artifact(ticker="SPY", horizon="5c", now_epoch_seconds=1100) is None


def test_load_returns_none_when_isotonic_pointer_points_to_nonexistent_artifact(tmp_path, monkeypatch):
    pointer = current_pointer_path(ticker="SPY", horizon="5c", data_root=tmp_path / "data", artifact_kind="isotonic")
    update_current_pointer_atomically(
        artifact_relative_path="v2_calibration/isotonic/A/A1/SPY/5c/missing.json",
        pointer_path=pointer,
    )
    monkeypatch.chdir(tmp_path)

    assert load_a1_isotonic_artifact(ticker="SPY", horizon="5c", now_epoch_seconds=1100) is None


def test_load_returns_none_when_isotonic_artifact_schema_version_mismatch(tmp_path, monkeypatch):
    artifact = _artifact(schema_version="bad")
    _write_pointer_artifact(tmp_path, artifact)
    monkeypatch.chdir(tmp_path)

    assert load_a1_isotonic_artifact(ticker="SPY", horizon="5c", now_epoch_seconds=1100) is None


def test_load_returns_none_when_isotonic_lifecycle_schema_version_mismatch(tmp_path, monkeypatch):
    artifact = _artifact()
    artifact["artifact_lifecycle_schema_version"] = "bad"
    _write_pointer_artifact(tmp_path, artifact)
    monkeypatch.chdir(tmp_path)

    assert load_a1_isotonic_artifact(ticker="SPY", horizon="5c", now_epoch_seconds=1100) is None


def test_load_returns_none_when_isotonic_ticker_universe_excludes_requested_ticker(tmp_path, monkeypatch):
    artifact = _artifact(lifecycle_ticker="QQQ")
    _write_pointer_artifact(tmp_path, artifact)
    monkeypatch.chdir(tmp_path)

    assert load_a1_isotonic_artifact(ticker="SPY", horizon="5c", now_epoch_seconds=1100) is None


def test_load_returns_none_when_isotonic_horizon_mismatch(tmp_path, monkeypatch):
    artifact = _artifact(horizon="15c")
    _write_pointer_artifact(tmp_path, artifact)
    monkeypatch.chdir(tmp_path)

    assert load_a1_isotonic_artifact(ticker="SPY", horizon="5c", now_epoch_seconds=1100) is None


def test_load_returns_none_when_isotonic_artifact_stale_per_governed_max_age(tmp_path, monkeypatch):
    artifact = _artifact(governed_max_age_seconds=10, generated_at_epoch_seconds=1000)
    _write_pointer_artifact(tmp_path, artifact)
    monkeypatch.chdir(tmp_path)

    assert load_a1_isotonic_artifact(ticker="SPY", horizon="5c", now_epoch_seconds=1011) is None


def test_load_returns_none_when_isotonic_artifact_json_malformed(tmp_path, monkeypatch):
    artifact_path = _write_pointer_artifact(tmp_path, _artifact())
    artifact_path.write_text("{not json", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    assert load_a1_isotonic_artifact(ticker="SPY", horizon="5c", now_epoch_seconds=1100) is None


def test_load_returns_none_when_isotonic_required_field_missing(tmp_path, monkeypatch):
    artifact = _artifact()
    artifact.pop("calibration_lineage_id")
    _write_pointer_artifact(tmp_path, artifact)
    monkeypatch.chdir(tmp_path)

    assert load_a1_isotonic_artifact(ticker="SPY", horizon="5c", now_epoch_seconds=1100) is None


def test_load_does_not_raise_for_isotonic_unexpected_io_failure(tmp_path, monkeypatch):
    _write_pointer_artifact(tmp_path, _artifact())
    monkeypatch.chdir(tmp_path)

    def fail_read_text(self, *args, **kwargs):
        raise OSError("simulated io failure")

    monkeypatch.setattr(Path, "read_text", fail_read_text)

    assert load_a1_isotonic_artifact(ticker="SPY", horizon="5c", now_epoch_seconds=1100) is None


def test_load_returns_none_when_isotonic_pointer_json_malformed(tmp_path, monkeypatch):
    pointer = current_pointer_path(ticker="SPY", horizon="5c", data_root=tmp_path / "data", artifact_kind="isotonic")
    pointer.parent.mkdir(parents=True, exist_ok=True)
    pointer.write_text(json.dumps({"not_artifact_relative_path": "x"}), encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    assert load_a1_isotonic_artifact(ticker="SPY", horizon="5c", now_epoch_seconds=1100) is None


def test_load_uses_now_epoch_seconds_parameter_for_isotonic(tmp_path, monkeypatch):
    artifact = _artifact(governed_max_age_seconds=10, generated_at_epoch_seconds=1000)
    _write_pointer_artifact(tmp_path, artifact)
    monkeypatch.chdir(tmp_path)

    assert load_a1_isotonic_artifact(ticker="SPY", horizon="5c", now_epoch_seconds=1005) == artifact
    assert load_a1_isotonic_artifact(ticker="SPY", horizon="5c", now_epoch_seconds=1011) is None
```

#### `tests/test_v2_a1_conformal_artifact_attachment.py`

```python
from __future__ import annotations

from pathlib import Path


def test_attachment_sets_artifact_when_loader_returns_one(monkeypatch):
    from v2_decision import a1_conformal_artifact_attachment as attachment

    artifact = {"calibration_run_id": "cal-test-run"}
    monkeypatch.setattr(attachment, "load_a1_conformal_artifact", lambda **kwargs: artifact)
    ms_dict = {"primary_horizon": "5c"}

    attachment.attach_a1_conformal_artifact_to_ms_dict(ms_dict, ticker="SPY")

    assert ms_dict["a1_conformal_artifact"] == artifact


def test_attachment_sets_none_when_loader_returns_none(monkeypatch):
    from v2_decision import a1_conformal_artifact_attachment as attachment

    monkeypatch.setattr(attachment, "load_a1_conformal_artifact", lambda **kwargs: None)
    ms_dict = {"primary_horizon": "5c"}

    attachment.attach_a1_conformal_artifact_to_ms_dict(ms_dict, ticker="SPY")

    assert ms_dict["a1_conformal_artifact"] is None


def test_attachment_calls_loader_with_correct_ticker_and_horizon(monkeypatch):
    from v2_decision import a1_conformal_artifact_attachment as attachment

    calls = []

    def fake_loader(**kwargs):
        calls.append(kwargs)
        return {"artifact": True}

    monkeypatch.setattr(attachment, "load_a1_conformal_artifact", fake_loader)
    ms_dict = {"primary_horizon": " 5C "}

    attachment.attach_a1_conformal_artifact_to_ms_dict(ms_dict, ticker="SPY")

    assert calls == [{"ticker": "SPY", "horizon": "5c"}]


def test_attachment_sets_none_when_primary_horizon_missing(monkeypatch):
    from v2_decision import a1_conformal_artifact_attachment as attachment

    calls = []
    monkeypatch.setattr(attachment, "load_a1_conformal_artifact", lambda **kwargs: calls.append(kwargs))
    ms_dict = {}

    attachment.attach_a1_conformal_artifact_to_ms_dict(ms_dict, ticker="SPY")

    assert calls == []
    assert ms_dict["a1_conformal_artifact"] is None


def test_attachment_sets_none_when_ticker_empty(monkeypatch):
    from v2_decision import a1_conformal_artifact_attachment as attachment

    calls = []
    monkeypatch.setattr(attachment, "load_a1_conformal_artifact", lambda **kwargs: calls.append(kwargs))
    ms_dict = {"primary_horizon": "5c"}

    attachment.attach_a1_conformal_artifact_to_ms_dict(ms_dict, ticker="")

    assert calls == []
    assert ms_dict["a1_conformal_artifact"] is None


def test_attachment_does_not_inject_calibrated_probability_or_lineage_id(monkeypatch):
    from v2_decision import a1_conformal_artifact_attachment as attachment

    monkeypatch.setattr(attachment, "load_a1_conformal_artifact", lambda **kwargs: {"artifact": True})
    ms_dict = {"primary_horizon": "5c"}

    attachment.attach_a1_conformal_artifact_to_ms_dict(ms_dict, ticker="SPY")

    assert "a1_calibrated_probability" not in ms_dict
    assert "a1_calibrated_probability_lineage_id" not in ms_dict


def test_server_imports_attachment_helper():
    source = _server_source()

    assert (
        "from v2_decision.a1_conformal_artifact_attachment "
        "import attach_a1_conformal_artifact_to_ms_dict"
    ) in source


def test_server_logging_path_invokes_attachment_between_stamp_and_build():
    source = _server_source()
    window = source[source.index("_v2_logging_ms_dict = _ms_to_dict(ms)") : source.index("from calibration.v2_live_logging")]

    stamp_idx = window.index("stamp_decision_bundle(_v2_logging_ms_dict)")
    attach_idx = window.index("attach_a1_conformal_artifact_to_ms_dict(_v2_logging_ms_dict, ticker=ticker)")
    build_idx = window.index("build_module_a_a1_decision(_v2_logging_ms_dict)")

    assert stamp_idx < attach_idx < build_idx


def test_server_response_path_invokes_attachment_before_v2_decision_build():
    source = _server_source()
    build_anchor = 'ms_dict["v2_decision"] = _v2_decision_for_response or build_module_a_a1_decision(ms_dict)'
    build_pos = source.index(build_anchor)
    start = source.rindex("_attach_stack_runtime_and_governance(ms_dict, ticker=ticker)", 0, build_pos)
    end = source.index("_lmp.merge_into_state", build_pos)
    window = source[start:end]

    stamp_idx = window.index("_finalize_production_decision(ms_dict, _decision_route)")
    attach_idx = window.index("attach_a1_conformal_artifact_to_ms_dict(ms_dict, ticker=ticker)")
    build_idx = window.index(build_anchor)

    assert stamp_idx < attach_idx < build_idx


def _server_source() -> str:
    return Path("server.py").read_text(encoding="utf-8")
```

Thematic near-duplicates (not exact pairs):

- `test_a1_conformal_artifact_loader.py` vs `test_a1_isotonic_artifact_loader.py` — same loader-fail-closed shape
- `test_a1_conformal_artifact_production.py` vs `test_a1_isotonic_artifact_production.py`
- `test_a1_*` loaders vs `test_v2_a1_*` attachment/promotion (different layer, same A1 / `v2_decision` family)

---

## 4. DIRECTORY STRUCTURE

`tree` is not installed in this environment. `find tests/ -type d ! -path '*/__pycache__*'`:

```
tests/
tests/adversarial
tests/archive
tests/archive/legacy_section_audits_v1
tests/decision_reconstruction
tests/e2e
tests/fixtures
tests/perf_proof
tests/release_object
tests/runtime_proof
```

Organization (file counts exclude `__pycache__`):

| Path | Contents |
|---|---|
| `tests/` root | 554 `test_*.py` plus helpers (`conftest.py`, `mvp_test_fixtures.py`, `playwright_ready.py`, 3 `*_node.mjs`) |
| `tests/adversarial/` | 9 test files + `__init__.py` |
| `tests/archive/legacy_section_audits_v1/` | 16 Schwab section audits — not collected (`collect_ignore`) |
| `tests/decision_reconstruction/` | 1 test |
| `tests/e2e/` | 9 Playwright `*.spec.js` (not pytest) |
| `tests/fixtures/` | 1 JSON fixture |
| `tests/perf_proof/` | `validate.py` (not `test_*.py`) |
| `tests/release_object/` | 1 test |
| `tests/runtime_proof/` | 2 tests |

Almost everything is a flat `tests/test_*.py` pile. Subdirs are a thin overlay.

Playwright specs under `tests/e2e/`:

- `card-fidelity-stale-fallback-dom.spec.js`
- `find-liveui-6-direction-withhold.spec.js`
- `issue18-card-render-behavioral.spec.js`
- `l1-sse-scaling.spec.js`
- `l1-sse.spec.js`
- `smoke.spec.js`
- `stack-wire-3-ui-phase3-behavioral.spec.js`
- `stack-wire-4-cand-ui-fusion-gate.spec.js`
- `ticker-switch-expiry-reset.spec.js`

---

## 5. CI/CD WORKFLOW

Only two GitHub workflows exist: `.github/workflows/pytest.yml` and `.github/workflows/hardening.yml`. No pytest markers, no path filters, no test-group matrix.

### Required job `pytest-full` (`.github/workflows/pytest.yml`)

Triggers: `pull_request` + `push` to `main` only.

Command actually run:

```bash
npm run test:e2e &
python -m pytest -n "$(nproc)" --dist loadfile --durations=20 --ignore=tests/test_playwright_must_run.py
wait
python -m pytest tests/test_playwright_must_run.py --tb=short
```

Env: `CI=true`, `ED_CI_OFFLINE=1`, `ED_CONSOLE_ALLOW_NONCANONICAL_DB=1`, placeholder `SCHWAB_*`. Python 3.13.

Grouping: **none by marker or directory**. The only split is:

1. Playwright E2E (`tests/e2e/*.spec.js`) overlapped with the full pytest tree
2. xdist `--dist loadfile` (file-level shard, not semantic groups)
3. `test_playwright_must_run.py` held until E2E writes `.playwright_last_run_success`

Local equivalents:

- `make test-all` / `npm run test:all` → `npm run test:e2e && python -m pytest -n auto --dist loadfile --durations=20` (serial E2E then pytest; CI overlaps them)
- `hardening.yml` does not run pytest (ruff / compileall / money-path / institutional gates)

Full `pytest.yml`:

```yaml
name: Pytest Full Suite

# Full Python suite + Playwright E2E (npm run test:all): the required runtime-correctness
# gate under the ED CONSOLE SLIMMING charter (AGENTS.md), alongside the Hardening quality job.

on:
  pull_request:
  # RC-405 (engineering-cycle latency): run the full suite once per change. `pull_request`
  # already runs full CI before merge (branch protection's required check), so a `push` event
  # on a FEATURE branch only duplicates it. Restrict the push trigger to `main` — that keeps
  # post-merge validation of the trunk while removing the redundant per-feature-push run. No
  # check is weakened or skipped; the pre-merge proof is unchanged.
  push:
    branches: [main]

jobs:
  pytest-full:
    runs-on: ubuntu-latest
    timeout-minutes: 45
    steps:
      - name: Check out repository
        uses: actions/checkout@v4
        with:
          # FULL_FIXES_ONLY_V2: FINAL_SHA verification needs full history
          fetch-depth: 0

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.13"

      - name: Set up uv
        uses: astral-sh/setup-uv@v5
        with:
          enable-cache: true

      - name: Set up Node.js
        uses: actions/setup-node@v4
        with:
          node-version: "22"
          cache: npm

      - name: Install Python dependencies
        shell: bash
        run: |
          uv pip install --system -r requirements-dev.txt -r requirements.txt

      - name: Install Node dependencies
        run: npm ci

      - name: Cache Playwright browsers
        uses: actions/cache@v4
        with:
          path: ~/.cache/ms-playwright
          key: playwright-${{ runner.os }}-${{ hashFiles('package-lock.json') }}

      - name: Install Playwright system deps (Linux)
        # Bound this step. Unbounded apt-get is what cancelled required pytest-full:
        # run 32223509912 (#134) and 32161696563 (main, #129) both sat ~43m on
        # `playwright install-deps` after `Ign: azure.archive.ubuntu.com`, then the
        # job `timeout-minutes: 45` cancelled before E2E/pytest started.
        timeout-minutes: 8
        run: |
          sudo tee /etc/apt/apt.conf.d/99ci-acquire-timeout >/dev/null <<'EOF'
          Acquire::http::Timeout "20";
          Acquire::https::Timeout "20";
          Acquire::Retries "2";
          EOF
          sudo python3 - <<'PY'
          from pathlib import Path
          old = "azure.archive.ubuntu.com"
          new = "archive.ubuntu.com"
          apt = Path("/etc/apt")
          files = [apt] if apt.is_file() else []
          if apt.is_dir():
              files.extend(p for p in apt.rglob("*") if p.is_file())
          n = 0
          for path in files:
              try:
                  text = path.read_text(encoding="utf-8")
              except (OSError, UnicodeDecodeError):
                  continue
              if old in text:
                  path.write_text(text.replace(old, new), encoding="utf-8")
                  print(f"rewrote {path}")
                  n += 1
          print(f"rewrote {n} apt file(s) off azure.archive.ubuntu.com")
          PY
          # Apt still hung after the .list/.sources-only rewrite (run 32231391764)
          # because ubuntu-24.04 GHA uses /etc/apt/apt-mirrors.txt. Bound each
          # attempt so a dead mirror cannot consume the 8-minute step budget.
          ok=0
          for attempt in 1 2 3; do
            if timeout 90 npx playwright install-deps chromium; then
              ok=1
              break
            fi
            echo "install-deps attempt ${attempt} failed"
          done
          if [ "$ok" -ne 1 ]; then
            echo "install-deps failed after retries; ubuntu-24.04 already ships Chromium libs via the runner image"
            npx playwright install chromium
          fi

      - name: Run Playwright E2E then full pytest
        env:
          CI: "true"
          ED_CI_OFFLINE: "1"
          ED_CONSOLE_ALLOW_NONCANONICAL_DB: "1"
          # Placeholders satisfy config startup in CI — not live Schwab credentials.
          # ED_CI_OFFLINE + config.is_schwab_ci_offline_mode() block live API calls.
          SCHWAB_API_KEY: "ci-not-live-placeholder"
          SCHWAB_APP_SECRET: "ci-not-live-placeholder"
        run: |
          # MEASURED on required pytest-full 32234684073: nproc=4 and
          # os.cpu_count()=4 but `pytest -n auto` still created 2/2 workers
          # (Python 3.13 `os.process_cpu_count()` is what xdist `auto` reads).
          # Pin the worker count to the runner's nproc — same suite, more cores.
          echo "CI_CPUS nproc=$(nproc) cpu_count=$(python -c 'import os; print(os.cpu_count())') process_cpu_count=$(python -c 'import os; p=getattr(os,"process_cpu_count",None); print(p() if p else None)')"
          # Overlap E2E with the pytest wave. MEASURED on 32235863378: E2E is
          # 78 passed / 54.4s serial *before* pytest's 232s. The marker file
          # is written at E2E success; the two tests in
          # tests/test_playwright_must_run.py still run after E2E (not skipped).
          # Local `npm run test:all` stays serial.
          set +e
          npm run test:e2e &
          e2e_pid=$!
          python -m pytest -n "$(nproc)" --dist loadfile --durations=20 --ignore=tests/test_playwright_must_run.py
          pytest_rc=$?
          wait "$e2e_pid"
          e2e_rc=$?
          set -e
          if [ "$e2e_rc" -ne 0 ]; then
            echo "Playwright E2E failed with ${e2e_rc}"
            exit "$e2e_rc"
          fi
          python -m pytest tests/test_playwright_must_run.py --tb=short
          exit "$pytest_rc"
```

---

## 6. `pytest.ini` / `pyproject.toml`

| Question | Measured |
|---|---|
| Does `pytest.ini` exist? | No. `ls pytest.ini` → `No such file or directory` |
| `setup.cfg` / `tox.ini`? | Neither exists |
| `[tool.pytest.ini_options]` in `pyproject.toml`? | No. `tomllib` keys under `[tool]` are only `ruff`, `mypy`, `bandit`, `coverage` |

Entire `pyproject.toml` (no pytest section):

```toml
# Tooling config for the hardening program (2026-06-03). Tool sections only — no [build-system]
# so pip/packaging behavior is unchanged. Each tool is wired into .github/workflows/hardening.yml.

[tool.ruff]
line-length = 100
target-version = "py313"
extend-exclude = [
    ".venv", "venv", "node_modules", "__pycache__",
    "models/_artifact_archive", "models/_xgb_dirty_quarantine",
]

[tool.ruff.lint]
# Start enforcing the high-signal correctness rules (the ones that caught the real bugs this
# session); style/complexity rules are added as the baseline is cleaned (ratchet, not big-bang).
select = ["F", "E9"]   # pyflakes (unused/undefined/redefine) + syntax errors
# F-rules that are intentional in this repo (documented re-exports already carry # noqa: F401).

[tool.ruff.format]
quote-style = "double"

[tool.mypy]
# Lenient first pass — money-path modules get tightened incrementally; ignore third-party stubs
# so CI isn't drowned in import-stub noise on day one.
python_version = "3.13"
ignore_missing_imports = true
warn_unused_ignores = false
warn_redundant_casts = true
# Hard errors only at first (undefined names, bad calls); widen `disallow_untyped_defs` per-module later.
exclude = "(^|/)(node_modules|\\.venv|venv|models/)"

[tool.bandit]
# Security scan. The known surface (pickle.load on model files, sqlite f-string SQL on internal
# tooling) is triaged in the hardening tracker; exclude tests + vendored/archive trees.
exclude_dirs = ["tests", "node_modules", ".venv", "venv", "models"]

[tool.coverage.run]
branch = true
omit = ["tests/*", "*/node_modules/*", "models/*"]
```

Pytest flags live only in the invocation, not in an ini file:

- CI: `python -m pytest -n "$(nproc)" --dist loadfile --durations=20 --ignore=tests/test_playwright_must_run.py`
- Local: `python -m pytest -n auto --dist loadfile --durations=20`

---

## 7. TEST COUNT AND PATTERNS

Exact commands the operator named:

```
find tests/ -name "*.py" -type f | wc -l
593

find tests/ -name "test_*.py" | wc -l
583

grep -r "def test_" tests/ | wc -l
5624
```

Additional measured splits (same turn):

| Count | Method |
|---|---|
| 593 | `find tests/ -name "*.py" -type f` |
| 583 | `find tests/ -name "test_*.py"` |
| 554 | top-level `tests/test_*.py` |
| 29 | `test_*.py` in subdirs |
| 5624 | requested `grep -r "def test_"` (includes pycache) |
| 5525 | `grep` on `*.py` excluding archive and `__pycache__` |

Pattern prefix counts:

| Pattern | Count |
|---|---:|
| `test_v1_*.py` | 0 |
| `test_v2_*.py` | 18 |
| `test_a1_*.py` | 5 |
| `test_a2_*.py` | 6 |
| `test_*_artifact_*.py` | 5 |

---

## Auditor note (not a plan)

This file is the inventory the operator asked for so a rehabilitation plan can name concrete file changes. No tests were moved, deleted, or rewritten in the turn that produced this dump.
