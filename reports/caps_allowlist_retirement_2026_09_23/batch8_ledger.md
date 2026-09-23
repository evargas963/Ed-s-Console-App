# CAPS batch 8 ledger

hits=177 FIX=79 MARK=98

verification/base_ticker_observability.py:70 GET_WITH_DEFAULT -> FIX: gate threshold shadow-defaulted in code; contract JSON (base_ticker_money_path_contract.json) is the single owner -> thr[key], missing key raises
verification/base_ticker_observability.py:71 GET_WITH_DEFAULT -> FIX: gate threshold shadow-defaulted in code; contract JSON (base_ticker_money_path_contract.json) is the single owner -> thr[key], missing key raises
verification/base_ticker_observability.py:72 GET_WITH_DEFAULT -> FIX: gate threshold shadow-defaulted in code; contract JSON (base_ticker_money_path_contract.json) is the single owner -> thr[key], missing key raises
verification/base_ticker_observability.py:73 GET_WITH_DEFAULT -> FIX: gate threshold shadow-defaulted in code; contract JSON (base_ticker_money_path_contract.json) is the single owner -> thr[key], missing key raises
verification/base_ticker_observability.py:91 CAST_OR_DEFAULT -> FIX: COUNT(*) is never NULL; dead `or 0` removed
verification/base_ticker_observability.py:108 CAST_OR_DEFAULT -> FIX: COUNT(*) is never NULL; dead `or 0` removed
verification/card_direction_integrity.py:193 CAST_OR_DEFAULT -> FIX: missing probability leg coerced to 0.0 produced a real-looking LONG/SHORT (or WAIT for an absent triple); fusion_direction_from_probs now returns None when any leg is None (consumers: card_signal_fidelity classifiers, tools/check_card_direction_integrity rows)
verification/card_direction_integrity.py:194 CAST_OR_DEFAULT -> FIX: missing probability leg coerced to 0.0 produced a real-looking LONG/SHORT (or WAIT for an absent triple); fusion_direction_from_probs now returns None when any leg is None (consumers: card_signal_fidelity classifiers, tools/check_card_direction_integrity rows)
verification/card_direction_integrity.py:195 CAST_OR_DEFAULT -> FIX: missing probability leg coerced to 0.0 produced a real-looking LONG/SHORT (or WAIT for an absent triple); fusion_direction_from_probs now returns None when any leg is None (consumers: card_signal_fidelity classifiers, tools/check_card_direction_integrity rows)
verification/card_signal_fidelity.py:57 CAST_OR_DEFAULT -> FIX: histogram_is_flat coerced missing legs to 0 -> all-missing histogram tagged HISTOGRAM_TOO_FLAT; now returns None; UNDERCONDITIONED requires a measured non-flat LONG/FLAT histogram
verification/card_signal_fidelity.py:185 IF_NOT_NONE_ELSE -> FIX: unknown normalized_rows_rth asserted normalized_rows_degraded=False (healthy); now None (unknown), propagated to deep-dive answer 7
verification/card_signal_fidelity.py:224 GET_WITH_DEFAULT -> MARK: tag-count histogram; every horizon pre-seeded; now indexes by_horizon['1c']
verification/card_signal_fidelity.py:225 GET_WITH_DEFAULT -> MARK: tag-count histogram; by_horizon['5c'] pre-seeded
verification/card_signal_fidelity.py:231 GET_WITH_DEFAULT -> MARK: tag-count histogram; by_horizon['60c'] pre-seeded
verification/card_signal_fidelity.py:244 GET_WITH_DEFAULT -> FIX: deep-dive answered '0 cells' from the not-run stub audit {cell_count:0,cells:[]}; stub now yields histogram_shape_audit_run=False; real audit indexed
verification/card_signal_fidelity.py:251 GET_WITH_DEFAULT -> FIX: same as 244 (histogram_short_fusion_long_cells indexed)
verification/card_signal_fidelity.py:595 GET_WITH_DEFAULT -> FIX: rows must be enriched (enrich_timeline_row_provenance writes provenance for every horizon); indexed so an un-enriched row raises instead of counting zero overrides
verification/card_signal_fidelity.py:600 GET_WITH_DEFAULT -> FIX: same as 595 (signal_semantics indexed)
verification/card_signal_fidelity.py:611 NEXT_DEFAULT -> MARK: next(..., None); None = no wait_reason, served as null
verification/daily_health.py:184 GET_WITH_DEFAULT -> FIX: every check dict carries id; indexed
verification/daily_health.py:267 CAST_OR_DEFAULT -> FIX: COUNT(*) is never NULL; dead `or 0` removed
verification/daily_health.py:322 CAST_OR_DEFAULT -> FIX: COUNT(*) is never NULL; dead `or 0` removed
verification/daily_health.py:486 GET_OR_DEFAULT -> FIX: _gap_stats_bars always sets the key; indexed
verification/daily_health.py:598 GET_WITH_DEFAULT -> FIX: _snapshot_pred_coverage sets partial_triad_rows on all paths; indexed
verification/daily_health.py:673 IF_NOT_NONE_ELSE -> MARK: output-directory argument default (repo root)
verification/daily_health.py:698 GET_WITH_DEFAULT -> FIX: summary keys always set by run_daily_health; indexed instead of printing '0 FAIL checks'
verification/daily_health.py:699 GET_WITH_DEFAULT -> FIX: as 698
verification/daily_health.py:700 GET_WITH_DEFAULT -> FIX: as 698
verification/daily_health.py:701 GET_WITH_DEFAULT -> FIX: as 698
verification/daily_health.py:711 GET_WITH_DEFAULT -> FIX: by_category entries are seeded FAIL/WARN counters; indexed
verification/daily_health.py:727 GET_WITH_DEFAULT -> FIX: bars=None (no price_bars_1m table) rendered as '0' bars; now 'n/a'
verification/daily_health.py:728 GET_OR_DEFAULT -> FIX: redundant `or 0` under an is-not-None guard removed; blank cell when unmeasured (new line marked display-only)
verification/daily_health.py:731 GET_WITH_DEFAULT -> MARK: markdown cell; '' = gap stats not computed
verification/daily_health.py:732 GET_WITH_DEFAULT -> MARK: markdown cell; '' = gap stats not computed
verification/daily_health.py:740 GET_WITH_DEFAULT -> MARK: markdown cells; '' = unlabeled horizon, never parsed back
verification/daily_health.py:741 GET_WITH_DEFAULT -> MARK: markdown cells; '' = unlabeled horizon, never parsed back
verification/db_coverage.py:144 IF_TRUTHY_ELSE -> MARK: CSV fieldnames; nothing written when no rows
verification/db_sqlite_contention_impact_audit.py:186 CAST_OR_DEFAULT -> MARK: max-merge of non-negative counters; absent runtime value adds no evidence (0 = identity of max)
verification/db_sqlite_contention_impact_audit.py:190 GET_WITH_DEFAULT -> MARK: as 186 (lock wait total ms)
verification/db_sqlite_contention_impact_audit.py:194 GET_WITH_DEFAULT -> MARK: as 186 (lock wait max ms)
verification/db_sqlite_contention_impact_audit.py:244 GET_OR_DEFAULT -> FIX (LIVE operator pill, server.py + /api/diagnostics): event without ts_utc read as ts=0 and silently dropped out of the recent window; producer record_sqlite_contention_event always stamps it -> indexed
verification/db_sqlite_contention_impact_audit.py:248 GET_OR_DEFAULT -> FIX (LIVE): lifetime counters no longer coerced to 0; absent -> None in metrics_summary + lifetime_counters_complete flag
verification/db_sqlite_contention_impact_audit.py:249 GET_OR_DEFAULT -> FIX (LIVE): as 248
verification/db_sqlite_contention_impact_audit.py:250 GET_OR_DEFAULT -> FIX (LIVE): as 248
verification/db_sqlite_contention_impact_audit.py:251 GET_OR_DEFAULT -> FIX (LIVE): as 248; DB_LOCKED lifetime test only on a known count
verification/db_sqlite_contention_impact_audit.py:252 GET_OR_DEFAULT -> FIX (LIVE): as 251
verification/db_sqlite_contention_impact_audit.py:254 GET_OR_DEFAULT -> FIX (LIVE): second hard-coded 100ms threshold replaced by the owner constant db_sqlite_utils.SQLITE_LOCK_WAIT_WARN_MS when config block absent (marked)
verification/db_sqlite_contention_impact_audit.py:261 GET_OR_DEFAULT -> FIX (LIVE): lock_wait events always carry wait_ms; indexed
verification/db_sqlite_contention_impact_audit.py:264 GET_OR_DEFAULT -> FIX (LIVE): indexed wait_ms; empty-window max 0 ms marked (measured window)
verification/db_sqlite_contention_impact_audit.py:286 GET_OR_DEFAULT -> FIX (LIVE): indexed ts_utc; None when no recent event (marked)
verification/db_sqlite_contention_impact_audit.py:408 IF_TRUTHY_ELSE -> FIX: no PRAGMA row asserted wal_mode_enabled=False; now stays None (unknown)
verification/db_sqlite_contention_impact_audit.py:526 GET_WITH_DEFAULT -> FIX: writer_map literal always has the list; indexed instead of reporting '[]'
verification/db_sqlite_contention_impact_audit.py:534 GET_WITH_DEFAULT -> FIX: as 526
verification/db_sqlite_contention_impact_audit.py:688 GET_WITH_DEFAULT -> FIX: report header keys always set by builder; indexed
verification/db_sqlite_contention_impact_audit.py:689 GET_WITH_DEFAULT -> FIX: as 688
verification/db_sqlite_contention_impact_audit.py:693 GET_WITH_DEFAULT -> FIX: as 688
verification/db_sqlite_contention_impact_audit.py:739 GET_WITH_DEFAULT -> FIX: as 688
verification/horizon_health.py:32 IF_TRUTHY_ELSE -> MARK: withheld horizon keeps an all-None triplet
verification/horizon_health.py:93 GET_WITH_DEFAULT -> MARK: sample-floor constant (same MIN_SAMPLES_STATISTICAL module reports); only picks WITHHELD vs UNAVAILABLE for a non-OK row
verification/operator_trust_rth_validation.py:119 GET_WITH_DEFAULT -> MARK: documented env flag/default (opt-in or config), not market data
verification/operator_trust_rth_validation.py:122 GET_WITH_DEFAULT -> MARK: provenance metadata env (branch)
verification/operator_trust_rth_validation.py:124 GET_WITH_DEFAULT -> MARK: 'unknown' records unset env, gates nothing
verification/operator_trust_rth_validation.py:127 GET_WITH_DEFAULT -> MARK: as 124
verification/operator_trust_rth_validation.py:147 GET_WITH_DEFAULT -> MARK: fail-closed; missing reject count RUNS the wrong-ticker check
verification/operator_trust_rth_validation.py:152 GET_WITH_DEFAULT -> MARK: fail-closed; missing reject count RUNS the stale-generation check
verification/operator_trust_rth_validation.py:156 GET_WITH_DEFAULT -> MARK: fail-closed; missing state is not credited as CACHE
verification/operator_trust_rth_validation.py:269 GET_WITH_DEFAULT -> MARK: pair filter excludes unattributable events
verification/operator_trust_rth_validation.py:270 GET_WITH_DEFAULT -> MARK: as 269
verification/operator_trust_rth_validation.py:310 GET_WITH_DEFAULT -> MARK: markdown header label
verification/replay_diagnostic.py:57 GET_WITH_DEFAULT -> FIX: missing (or real 0) mins_to_close became 180 -> forced 'session' trade mode in multi_horizon_decision._infer_trade_mode; now None (consumer handles). Also removed hard-coded SPY level fallbacks 441.3/441.8 applied to every ticker
verification/similarity_feature_audit.py:72 IF_TRUTHY_ELSE -> FIX: dead `else 0.0` removed (both-empty case returns earlier)
verification/similarity_feature_audit.py:399 GET_WITH_DEFAULT -> FIX: every tier entry carries row_count_after_query_limit; indexed
verification/similarity_feature_audit.py:400 GET_WITH_DEFAULT -> FIX: as 399
verification/similarity_feature_audit.py:446 GET_OR_DEFAULT -> FIX: absent chosen_tier read as tier 0; now None -> explicit rationale, verdict becomes 'with cautions'
verification/similarity_feature_audit.py:468 NEXT_DEFAULT -> MARK: next(..., None) lookup; None skips the check
verification/similarity_feature_audit.py:469 NEXT_DEFAULT -> MARK: as 468
verification/ui_realtime_transport_audit.py:572 IF_TRUTHY_ELSE -> MARK: count derived from a computed bool
verification/ui_realtime_transport_audit.py:574 IF_TRUTHY_ELSE -> MARK: as 572
verification/ui_realtime_transport_audit.py:924 GET_WITH_DEFAULT -> FIX: sqlite_log from parse_sqlite_contention_from_text always has all keys; indexed
verification/ui_realtime_transport_audit.py:1057 GET_OR_DEFAULT -> MARK: pre-versioning records are v1; normalizer upgrades to >=2
verification/ui_realtime_transport_audit.py:1134 GET_WITH_DEFAULT -> FIX: producer always emits list; indexed instead of reporting no validation required
arch_competition/ablation_bundle_inference.py:97 GET_OR_DEFAULT -> MARK: persisted checkpoint predating the mask/norm field was trained on every channel / un-normalized inputs; current writers (lstm_model.py, transformer_train.py) always store it
arch_competition/ablation_bundle_inference.py:106 GET_OR_DEFAULT -> MARK: persisted checkpoint predating the mask/norm field was trained on every channel / un-normalized inputs; current writers (lstm_model.py, transformer_train.py) always store it
arch_competition/ablation_bundle_inference.py:115 GET_OR_DEFAULT -> MARK: persisted checkpoint predating the mask/norm field was trained on every channel / un-normalized inputs; current writers (lstm_model.py, transformer_train.py) always store it
arch_competition/ablation_bundle_inference.py:280 GET_WITH_DEFAULT -> MARK: 20 = transformer_train.SEQUENCE_LENGTH, the window every transformer checkpoint was trained at
arch_competition/ablation_bundle_inference.py:318 GET_WITH_DEFAULT -> MARK: persisted checkpoint predating the mask/norm field was trained on every channel / un-normalized inputs; current writers (lstm_model.py, transformer_train.py) always store it
arch_competition/ablation_bundle_inference.py:345 GET_WITH_DEFAULT -> MARK: persisted checkpoint predating the mask/norm field was trained on every channel / un-normalized inputs; current writers (lstm_model.py, transformer_train.py) always store it
arch_competition/ablation_bundle_inference.py:346 GET_WITH_DEFAULT -> MARK: persisted checkpoint predating the mask/norm field was trained on every channel / un-normalized inputs; current writers (lstm_model.py, transformer_train.py) always store it
arch_competition/ablation_bundle_inference.py:355 GET_WITH_DEFAULT -> MARK: persisted checkpoint predating the mask/norm field was trained on every channel / un-normalized inputs; current writers (lstm_model.py, transformer_train.py) always store it
arch_competition/ablation_bundle_inference.py:468 IF_TRUTHY_ELSE -> FIX: empty merged_days zero-filled every confluence channel into a fabricated input; now raises (only caller always passes >=1 bar)
arch_competition/ablation_bundle_inference.py:502 GET_WITH_DEFAULT -> MARK: persisted checkpoint predating the mask/norm field was trained on every channel / un-normalized inputs; current writers (lstm_model.py, transformer_train.py) always store it
arch_competition/ablation_bundle_inference.py:596 GETATTR_DEFAULT -> FIX: RulesCard.signal is required; getattr/'wait' fallback removed
arch_competition/ablation_bundle_inference.py:609 GET_WITH_DEFAULT -> FIX: missing XGB class injected uniform 1/3 into cascade confluence input; indexed. Also removed the adjacent 1/3 fill when xgb probs are absent/malformed and honored the ignored parallel_runtime flag (returns None like ml_predict raises)
arch_competition/ablation_bundle_inference.py:631 GET_WITH_DEFAULT -> MARK: 20 = transformer_train.SEQUENCE_LENGTH, the window every transformer checkpoint was trained at
arch_competition/encoder_lineage_v2.py:110 GET_OR_DEFAULT -> MARK: fail-closed (0 != v2 -> invalid)
arch_competition/encoder_lineage_v2.py:133 GET_OR_DEFAULT -> MARK: fail-closed (0 -> unsupported error)
arch_competition/governance_visibility.py:62 SETDEFAULT -> MARK: accumulator list
arch_competition/governance_visibility.py:297 GET_WITH_DEFAULT -> MARK: ticker filter
arch_competition/governance_visibility.py:320 GET_WITH_DEFAULT -> MARK: falls back to record's own flag, else None
arch_competition/governance_visibility.py:396 GET_WITH_DEFAULT -> MARK: documented env flag/default (opt-in or config), not market data
arch_competition/governance_visibility.py:402 GET_WITH_DEFAULT -> MARK: documented env flag/default (opt-in or config), not market data
arch_competition/live_drift_monitoring.py:189 GET_WITH_DEFAULT -> FIX: normalize_ml_horizon_slug('') returns default '1c', so a manifest with no horizon passed as a 1c baseline; absent slug now = mismatch (critical)
arch_competition/live_drift_monitoring.py:397 GET_WITH_DEFAULT -> FIX: missing calibration baseline became {} under state 'ok'; now None + state 'unavailable'
arch_competition/live_model_reload.py:83 SETDEFAULT -> MARK: row inherits the real HTTP status of the carrying response
arch_competition/manual_control.py:99 GET_WITH_DEFAULT -> MARK: fail-closed (cwd never equals canonical dir -> raises)
arch_competition/manual_control.py:100 GET_WITH_DEFAULT -> MARK: as 99
arch_competition/notification_delivery.py:67 GET_WITH_DEFAULT -> MARK: documented env flag/default (opt-in or config), not market data
arch_competition/notification_delivery.py:68 GET_WITH_DEFAULT -> MARK: documented env flag/default (opt-in or config), not market data
arch_competition/notification_delivery.py:70 GET_WITH_DEFAULT -> MARK: documented env flag/default (opt-in or config), not market data
arch_competition/notification_delivery.py:71 GET_WITH_DEFAULT -> MARK: documented env flag/default (opt-in or config), not market data
arch_competition/notification_delivery.py:130 GET_WITH_DEFAULT -> MARK: dedup-hash input, '' stable at write and lookup
arch_competition/notification_delivery.py:131 GET_WITH_DEFAULT -> MARK: as 130
arch_competition/notification_delivery.py:132 GET_WITH_DEFAULT -> MARK: as 130
arch_competition/notification_delivery.py:133 GET_WITH_DEFAULT -> MARK: as 130
arch_competition/notification_delivery.py:362 SETDEFAULT -> MARK: persisted dedup store initialisation
arch_competition/operational_policy.py:261 GET_WITH_DEFAULT -> MARK: ticker filter
arch_competition/promotion_execution.py:357 GET_OR_DEFAULT -> MARK: label inside a blocking reason
arch_competition/scheduler_auto_promote_policy.py:50 GET_WITH_DEFAULT -> MARK: documented env flag/default (opt-in or config), not market data
arch_competition/scheduler_auto_promote_policy.py:55 GET_WITH_DEFAULT -> MARK: env secret, unset -> None
arch_competition/scheduler_integration.py:197 GET_WITH_DEFAULT -> MARK: leaf stays None
arch_competition/scheduler_integration.py:198 GET_WITH_DEFAULT -> MARK: leaf stays None
arch_competition/scheduler_integration.py:266 GET_WITH_DEFAULT -> MARK: new summary starts empty map; non-dict raises
arch_competition/stack_bundle_eval_v1.py:307 GET_WITH_DEFAULT -> FIX: absent n_rows_scored read as 0 (passes a min_rows=0 floor); now None excluded from authority ranking
arch_competition/stack_bundle_eval_v1.py:525 GETATTR_DEFAULT -> FIX: RulesCard.signal required; fallback removed
arch_competition/stack_bundle_eval_v1.py:1311 GET_OR_DEFAULT -> MARK: fail-closed (0 < matrix target -> incomplete)
arch_competition/stack_bundle_eval_v1.py:1419 GET_OR_DEFAULT -> MARK: fail-closed (need=len(group), strictest)
arch_competition/stack_bundle_eval_v1.py:1491 GET_OR_DEFAULT -> MARK: fail-closed
arch_competition/stack_bundle_eval_v1.py:1705 GET_OR_DEFAULT -> MARK: fail-closed (raises)
arch_competition/stack_bundle_eval_v1.py:2522 GET_WITH_DEFAULT -> MARK: skipped-record metadata (requested slug)
arch_competition/stack_bundle_eval_v1.py:2525 GET_WITH_DEFAULT -> MARK: skip-reason label, no metric
arch_competition/stack_bundle_eval_v1.py:2750 GET_WITH_DEFAULT -> MARK: as 2522
arch_competition/stack_bundle_eval_v1.py:2753 GET_WITH_DEFAULT -> MARK: as 2525
research/abstention_eval_v1/runner.py:119 IF_TRUTHY_ELSE -> FIX: n_te==0 reported oos_coverage=0.0 (measured-looking); now None + NO_OOS_TEST_ROWS warning
research/challenger_eval_v1/runner.py:56 GET_WITH_DEFAULT -> MARK: fail-closed prereg check (absent name -> '' != MCC -> PreregViolationError)
research/challenger_eval_v1/runner.py:373 IF_TRUTHY_ELSE -> MARK: console-only '?' placeholder for a cell with no CI
research/cost_aware_eval_v1/faint_lead_kill_v1.py:76 IF_TRUTHY_ELSE -> FIX: empty nets -> [0.0] array, mean 0.0, CI [0,0] -> 'measured' KILL; now UNDER_SAMPLED with None metrics
research/cost_aware_eval_v1/faint_lead_kill_v1.py:124 IF_TRUTHY_ELSE -> MARK: zero-row design matrix with correct width, no values invented; empty X routes cell to UNDER_SAMPLED
research/cost_aware_eval_v1/faint_lead_kill_v1.py:164 IF_TRUTHY_ELSE -> MARK: zero-row design matrix with correct width, no values invented; empty X routes cell to UNDER_SAMPLED
research/cost_aware_eval_v1/runner.py:50 IF_TRUTHY_ELSE -> FIX: _day_bootstrap_ci returned [0,0] for no days (fabricated CI -> KILL); now None; unreachable `else 0.0` removed. _score_nets returns UNDER_SAMPLED for empty nets; study verdict INCONCLUSIVE_UNDER_SAMPLED instead of ECONOMIC_KILL when a cell is empty
research/cost_aware_eval_v1/runner.py:130 IF_TRUTHY_ELSE -> FIX: trade_rate 0.0 with no rows -> None
research/cost_aware_eval_v1/runner.py:156 IF_TRUTHY_ELSE -> MARK: zero-row design matrix with correct width, no values invented; empty X routes cell to UNDER_SAMPLED
research/cost_aware_eval_v1/runner.py:171 IF_TRUTHY_ELSE -> FIX: dead `else 0.0` removed; also the 0.01 threshold fallback when no session-safe moves -> skip fold
research/cost_aware_eval_v1/runner.py:212 IF_TRUTHY_ELSE -> FIX: as 130
research/cost_aware_eval_v1/stress_survivor_v1.py:84 IF_TRUTHY_ELSE -> FIX: no trades -> [0.0] array -> trades-only mean 0.0 bp; now None; empty input returns UNDER_SAMPLED; main refuses (exit 1) with zero OOS rows
research/cost_aware_eval_v1/stress_survivor_v1.py:87 IF_TRUTHY_ELSE -> FIX: as 84
research/cross_asset_eval_v1/runner.py:57 IF_TRUTHY_ELSE -> MARK: zero-row design matrix with correct width, no values invented; empty X routes cell to UNDER_SAMPLED
research/gex_r1_screen_v1/runner.py:64 IF_TRUTHY_ELSE -> MARK: NaN = undefined rate, same convention as avg()
research/gex_r1_screen_v1/runner.py:112 GET_OR_DEFAULT -> FIX: warm-up NaN gex_z entered training as 0.0 (median GEX); those rows now excluded from training
research/gex_r1_screen_v1/runner.py:129 GET_OR_DEFAULT -> FIX: test day with no gex_z was scored at z=0.0; now dropped from all paired series
research/har_micro_eval_v1/runner.py:82 IF_TRUTHY_ELSE -> MARK: zero-row design matrix with correct width, no values invented; empty X routes cell to UNDER_SAMPLED
research/incumbent_eval_v1/runner.py:47 GET_WITH_DEFAULT -> MARK: fail-closed prereg check (absent name -> '' != MCC -> PreregViolationError)
research/incumbent_eval_v1/runner.py:297 IF_TRUTHY_ELSE -> MARK: console-only '?' placeholder for a cell with no CI
research/interaction_eval_v1/runner.py:69 IF_TRUTHY_ELSE -> MARK: zero-row design matrix with correct width, no values invented; empty X routes cell to UNDER_SAMPLED
research/pilot_step3/data_loader.py:140 IF_TRUTHY_ELSE -> MARK: no rows -> no columns; zero-iteration loop
research/pilot_step3/event_generation.py:142 GET_WITH_DEFAULT -> FIX: prereg sigma contract params shadow-defaulted (390/on/120/0.25) -> unregistered contract could run silently; indexed (every prereg + F1 draft declares them)
research/pilot_step3/event_generation.py:145 GET_WITH_DEFAULT -> FIX: as 142
research/pilot_step3/event_generation.py:146 GET_WITH_DEFAULT -> FIX: as 142
research/pilot_step3/event_generation.py:147 GET_WITH_DEFAULT -> FIX: as 142
research/pilot_step3/event_generation.py:178 GET_WITH_DEFAULT -> FIX: prereg exclude_first_30min_rth indexed
research/pilot_step3/event_generation.py:181 GET_WITH_DEFAULT -> FIX: prereg near_equal_tolerance indexed
research/pilot_step3/f1_s5_spy_battery.py:87 IF_NOT_NONE_ELSE -> MARK: literal 'NULL' grouping key for NULL source rows
research/pilot_step3/f2_tb_grid_runner.py:477 IF_TRUTHY_ELSE -> MARK: preregistered hard halt voids survivors; status HALT_* + hard_halt_engaged explain the 0
research/pilot_step3/gamma_conditioned_study_v1.py:307 IF_TRUTHY_ELSE -> MARK: preregistered hard halt voids survivors; status HALT_* + hard_halt_engaged explain the 0
research/pilot_step3/meta_xgb_tb_runner.py:454 IF_TRUTHY_ELSE -> MARK: preregistered hard halt voids survivors; status HALT_* + hard_halt_engaged explain the 0
research/pilot_step3/pilot_runner.py:290 GET_WITH_DEFAULT -> FIX: generate_events always seeds the counter; indexed
research/pilot_step3/sigma_contract_compare_diagnostic.py:46 GET_WITH_DEFAULT -> FIX: prereg param indexed (same as event_generation)
research/pilot_step3/sigma_contract_compare_diagnostic.py:49 GET_WITH_DEFAULT -> FIX: as 46
research/pilot_step3/sigma_contract_compare_diagnostic.py:131 GET_WITH_DEFAULT -> FIX: legacy span now read from sigma_contract.ewm_span_bars, identical to the new-contract span
research/regime_har_eval_v1/runner.py:127 IF_TRUTHY_ELSE -> MARK: zero-row design matrix with correct width, no values invented; empty X routes cell to UNDER_SAMPLED
research/stage1_target_foundation/target_registry.py:131 GET_WITH_DEFAULT -> MARK: validator error label; missing id reported by REQUIRED_TARGET_FIELDS
research/stage1_target_foundation/target_registry.py:165 GET_WITH_DEFAULT -> MARK: family is required; its absence already fails validation
research/stage1_target_foundation/target_registry.py:226 GET_WITH_DEFAULT -> MARK: explicit '?' grouping bucket
research/structural_eval_v1/runner.py:57 GET_WITH_DEFAULT -> MARK: fail-closed prereg check (absent name -> '' != MCC -> PreregViolationError)
research/structural_eval_v1/runner.py:281 IF_TRUTHY_ELSE -> MARK: console-only '?' placeholder for a cell with no CI
research/survival_eval_v1/runner.py:68 IF_TRUTHY_ELSE -> MARK: zero-row design matrix with correct width, no values invented; empty X routes cell to UNDER_SAMPLED
research/survival_eval_v1/runner.py:122 IF_TRUTHY_ELSE -> FIX: dead `else 0.0` removed; 0.01 barrier fallback -> skip fold
research/vol_regime_har_eval_v1/runner.py:128 IF_TRUTHY_ELSE -> MARK: zero-row design matrix with correct width, no values invented; empty X routes cell to UNDER_SAMPLED
