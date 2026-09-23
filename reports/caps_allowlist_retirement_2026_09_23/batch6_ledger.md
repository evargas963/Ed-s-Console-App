# CAPS batch 6 (tests/) ledger -- one line per original hit

tests/adversarial/test_bypass_register_reconciliation.py:36 GET_WITH_DEFAULT -> FIX (tightened): recon['bypass_paths_total'] (0 > 0 already failed on absence); line 35 recon = data['reconciliation'] instead of `or {}`
tests/adversarial/test_bypass_register_reconciliation.py:38 GET_WITH_DEFAULT -> FIX (tightened): recon[<bucket>] -- reconcile_bypass_register always emits all six buckets; a missing bucket now fails instead of summing as 0
tests/adversarial/test_bypass_register_reconciliation.py:39 GET_WITH_DEFAULT -> FIX (tightened): recon[<bucket>] -- reconcile_bypass_register always emits all six buckets; a missing bucket now fails instead of summing as 0
tests/adversarial/test_bypass_register_reconciliation.py:40 GET_WITH_DEFAULT -> FIX (tightened): recon[<bucket>] -- reconcile_bypass_register always emits all six buckets; a missing bucket now fails instead of summing as 0
tests/adversarial/test_bypass_register_reconciliation.py:41 GET_WITH_DEFAULT -> FIX (tightened): recon[<bucket>] -- reconcile_bypass_register always emits all six buckets; a missing bucket now fails instead of summing as 0
tests/adversarial/test_bypass_register_reconciliation.py:42 GET_WITH_DEFAULT -> FIX (tightened): recon[<bucket>] -- reconcile_bypass_register always emits all six buckets; a missing bucket now fails instead of summing as 0
tests/adversarial/test_bypass_register_reconciliation.py:43 GET_WITH_DEFAULT -> FIX (tightened): recon[<bucket>] -- reconcile_bypass_register always emits all six buckets; a missing bucket now fails instead of summing as 0
tests/adversarial/test_bypass_register_reconciliation.py:52 GET_WITH_DEFAULT -> FIX (masking): default 'open' is a member of VALID_STATES, so a bypass path with NO reconciliation_state passed; now bp['reconciliation_state'] (producer always sets it); also data['entries'] indexed + asserted non-empty (the loop was vacuous on an empty/missing register)
tests/adversarial/test_bypass_register_reconciliation.py:66 GET_WITH_DEFAULT -> FIX (tightened): bp['path'] (line 64 already required it)
tests/adversarial/test_bypass_register_reconciliation.py:67 GET_WITH_DEFAULT -> FIX (tightened): bp['path'] (line 64 already required it)
tests/adversarial/test_r004_live_path_gate.py:35 GET_OR_DEFAULT -> FIX (tightened): out['market_data_quarantine']['active'] is True
tests/adversarial/test_stale_cache_revalidation.py:28 GET_OR_DEFAULT -> FIX (tightened): out['market_data_quarantine']['active'] is True
tests/adversarial/test_wrong_price_quarantine.py:46 GET_OR_DEFAULT -> FIX (tightened): out['market_data_quarantine']['active'] is True
tests/conftest.py:35 GET_WITH_DEFAULT -> MARK: pytest-xdist env var; absent means no xdist worker, and the value only names the temp-dir prefix
tests/conftest.py:40 SETDEFAULT -> MARK: test-harness env switch; setdefault lets an invoker who exported it explicitly keep their value, it seeds no data
tests/conftest.py:331 GETATTR_DEFAULT -> MARK: scanner false positive: docstring quoting the retired route-listing idiom this helper replaced
tests/perf_proof/validate.py:41 GET_WITH_DEFAULT -> MARK: a missing iterations key is already reported by the required-key loop above, and 0 < 1 appends a second error, so absence can never validate
tests/test_absence_is_not_zero_v1.py:4 CAST_OR_DEFAULT -> MARK: scanner false positive: module docstring naming the anti-pattern family this file guards against
tests/test_absence_is_not_zero_v1.py:75 CAST_OR_DEFAULT -> MARK: scanner false positive: docstring quoting the removed production line
tests/test_absence_is_not_zero_v1.py:142 CAST_OR_DEFAULT -> MARK: scanner false positive: docstring quoting the removed production line
tests/test_absence_is_not_zero_v1.py:253 CAST_OR_DEFAULT -> MARK: scanner false positive: docstring quoting the removed production line
tests/test_absence_is_not_zero_v1.py:303 GET_OR_DEFAULT -> MARK: scanner false positive: string fixture fed to the silent-zero detector to prove a reasonless escape is still flagged
tests/test_absence_is_not_zero_v1.py:304 GET_OR_DEFAULT -> MARK: scanner false positive: string fixture fed to the silent-zero detector to prove a reasoned escape is honoured
tests/test_absence_is_not_zero_v1.py:320 CAST_OR_DEFAULT -> MARK: scanner false positive: literal the test asserts is ABSENT from get_terrain_strikes
tests/test_absence_is_not_zero_v1.py:358 GET_OR_DEFAULT -> MARK: scanner false positive: literal located in server._CandleAccumulator source to check its silent-zero-ok reason
tests/test_absence_is_not_zero_v1.py:359 GET_OR_DEFAULT -> MARK: scanner false positive: literal used to find the accumulator line in inspected source (next() without default raises if absent)
tests/test_absence_is_not_zero_v1.py:370 CAST_OR_DEFAULT -> MARK: scanner false positive: string fixture proving the silent-zero detector still fires
tests/test_acceptance_gamma_availability_honesty_v1.py:17 GET_WITH_DEFAULT -> MARK: scanner false positive: module docstring describing the fail-closed read under test
tests/test_acceptance_gamma_availability_honesty_v1.py:63 GET_WITH_DEFAULT -> MARK: scanner false positive: docstring naming the mutation this test catches
tests/test_acceptance_gamma_availability_honesty_v1.py:64 GET_WITH_DEFAULT -> MARK: scanner false positive: docstring naming the mutation this test catches
tests/test_action11_3_server_ms_dict_fail_closed.py:16 GET_WITH_DEFAULT -> MARK: scanner false positive: forbidden-pattern literal this test asserts is ABSENT from server.py
tests/test_action11_3_server_ms_dict_fail_closed.py:17 GET_WITH_DEFAULT -> MARK: scanner false positive: forbidden-pattern literal this test asserts is ABSENT from server.py
tests/test_action11_3_server_ms_dict_fail_closed.py:18 GET_WITH_DEFAULT -> MARK: scanner false positive: forbidden-pattern literal this test asserts is ABSENT from server.py
tests/test_action11_3_server_ms_dict_fail_closed.py:19 GET_WITH_DEFAULT -> MARK: scanner false positive: forbidden-pattern literal this test asserts is ABSENT from server.py
tests/test_action11_3_server_ms_dict_fail_closed.py:20 GET_WITH_DEFAULT -> MARK: scanner false positive: forbidden-pattern literal this test asserts is ABSENT from server.py
tests/test_action11_3_server_ms_dict_fail_closed.py:21 GET_WITH_DEFAULT -> MARK: scanner false positive: forbidden-pattern literal this test asserts is ABSENT from server.py
tests/test_action11_3_server_ms_dict_fail_closed.py:22 GET_WITH_DEFAULT -> MARK: scanner false positive: forbidden-pattern literal this test asserts is ABSENT from server.py
tests/test_action11_3_server_ms_dict_fail_closed.py:23 GET_WITH_DEFAULT -> MARK: scanner false positive: forbidden-pattern literal this test asserts is ABSENT from server.py
tests/test_action11_3_server_ms_dict_fail_closed.py:24 GET_WITH_DEFAULT -> MARK: scanner false positive: forbidden-pattern literal this test asserts is ABSENT from server.py
tests/test_action11_3_server_ms_dict_fail_closed.py:25 GET_WITH_DEFAULT -> MARK: scanner false positive: forbidden-pattern literal this test asserts is ABSENT from server.py
tests/test_action11_3_server_ms_dict_fail_closed.py:26 GET_WITH_DEFAULT -> MARK: scanner false positive: forbidden-pattern literal this test asserts is ABSENT from server.py
tests/test_action11_3_server_ms_dict_fail_closed.py:27 GET_WITH_DEFAULT -> MARK: scanner false positive: forbidden-pattern literal this test asserts is ABSENT from server.py
tests/test_action11_3_server_ms_dict_fail_closed.py:28 GET_WITH_DEFAULT -> MARK: scanner false positive: forbidden-pattern literal this test asserts is ABSENT from server.py
tests/test_action11_3_server_ms_dict_fail_closed.py:29 GET_WITH_DEFAULT -> MARK: scanner false positive: forbidden-pattern literal this test asserts is ABSENT from server.py
tests/test_action11_3_server_ms_dict_fail_closed.py:30 GET_WITH_DEFAULT -> MARK: scanner false positive: forbidden-pattern literal this test asserts is ABSENT from server.py
tests/test_action11_3_server_ms_dict_fail_closed.py:33 GET_WITH_DEFAULT -> MARK: scanner false positive: forbidden-pattern literal this test asserts is ABSENT from server.py
tests/test_action11_3_server_ms_dict_fail_closed.py:36 GET_WITH_DEFAULT -> MARK: scanner false positive: forbidden-pattern literal this test asserts is ABSENT from server.py
tests/test_action11_3_server_ms_dict_fail_closed.py:37 GET_WITH_DEFAULT -> MARK: scanner false positive: forbidden-pattern literal this test asserts is ABSENT from server.py
tests/test_action11_3_server_ms_dict_fail_closed.py:38 GET_WITH_DEFAULT -> MARK: scanner false positive: forbidden-pattern literal this test asserts is ABSENT from server.py
tests/test_action11_3_server_ms_dict_fail_closed.py:39 GET_WITH_DEFAULT -> MARK: scanner false positive: forbidden-pattern literal this test asserts is ABSENT from server.py
tests/test_action11_3_server_ms_dict_fail_closed.py:40 GET_WITH_DEFAULT -> MARK: scanner false positive: forbidden-pattern literal this test asserts is ABSENT from server.py
tests/test_action11_3_server_ms_dict_fail_closed.py:41 GET_WITH_DEFAULT -> MARK: scanner false positive: forbidden-pattern literal this test asserts is ABSENT from server.py
tests/test_action11_3_server_ms_dict_fail_closed.py:42 GET_WITH_DEFAULT -> MARK: scanner false positive: forbidden-pattern literal this test asserts is ABSENT from server.py
tests/test_action11_3_server_ms_dict_fail_closed.py:43 GET_WITH_DEFAULT -> MARK: scanner false positive: forbidden-pattern literal this test asserts is ABSENT from server.py
tests/test_action11_3_server_ms_dict_fail_closed.py:44 GET_WITH_DEFAULT -> MARK: scanner false positive: forbidden-pattern literal this test asserts is ABSENT from server.py
tests/test_action11_8_signals_mc_fusion_fail_closed.py:17 IF_TRUTHY_ELSE -> MARK: scanner false positive: forbidden-pattern literal this test asserts is ABSENT from signals.py
tests/test_action11_8_signals_mc_fusion_fail_closed.py:18 GETATTR_DEFAULT -> MARK: scanner false positive: forbidden-pattern literal this test asserts is ABSENT from signals.py
tests/test_action11_8_signals_mc_fusion_fail_closed.py:19 GETATTR_DEFAULT -> MARK: scanner false positive: forbidden-pattern literal this test asserts is ABSENT from signals.py
tests/test_action11_8_signals_mc_fusion_fail_closed.py:20 GETATTR_DEFAULT -> MARK: scanner false positive: forbidden-pattern literal this test asserts is ABSENT from signals.py
tests/test_action11_9_call_engine_fail_closed.py:26 CAST_OR_DEFAULT -> MARK: scanner false positive: forbidden-pattern literal this test asserts is ABSENT from call_engine.py
tests/test_action11_9_call_engine_fail_closed.py:31 GETATTR_DEFAULT -> MARK: scanner false positive: forbidden-pattern literal this test asserts is ABSENT from call_engine.py
tests/test_action11_9_call_engine_fail_closed.py:32 GETATTR_DEFAULT -> MARK: scanner false positive: forbidden-pattern literal this test asserts is ABSENT from call_engine.py
tests/test_action11_9_call_engine_fail_closed.py:33 GETATTR_DEFAULT -> MARK: scanner false positive: forbidden-pattern literal this test asserts is ABSENT from call_engine.py
tests/test_action11_9_call_engine_fail_closed.py:35 GETATTR_DEFAULT -> MARK: scanner false positive: forbidden-pattern literal this test asserts is ABSENT from call_engine.py
tests/test_action12_1_through_12_5_fail_closed.py:159 GETATTR_DEFAULT -> MARK: scanner false positive: forbidden-pattern literal this test asserts is ABSENT from prediction_engine.py
tests/test_action12_7_market_state_fail_closed.py:168 GETATTR_DEFAULT -> FIX (tightened): _mhd.supporting_assessments (real dataclass field)
tests/test_action12_7_market_state_fail_closed.py:169 GETATTR_DEFAULT -> FIX (tightened): _a.missing (real dataclass field; a False default made the 60c row's None confidence pass for the wrong reason)
tests/test_action12_7_market_state_fail_closed.py:170 GETATTR_DEFAULT -> FIX (tightened): _a.horizon (real dataclass field)
tests/test_action12_8_fusion_policy_fail_closed.py:60 GETATTR_DEFAULT -> MARK: scanner false positive: forbidden-pattern literal this test asserts is ABSENT from fusion_policy_contract.py
tests/test_adaptive_shadow_v2.py:265 GET_WITH_DEFAULT -> FIX (tightened): a['tier1_pool_coverage']['schema']
tests/test_analytics_state_freshness_api.py:44 SETDEFAULT -> MARK: fixture builder: a caller-supplied _server_build_ts wins, otherwise the seeded entry is stamped with the fixture's own generation time
tests/test_analytics_state_freshness_api.py:661 GET_WITH_DEFAULT -> MARK: deliberately the same expression as server's full-publish _next_ver site; a lost version reads 0 and 0+1 != 8 fails the assertion
tests/test_analytics_state_freshness_api.py:753 NEXT_DEFAULT -> MARK: scanner false positive: next() here has NO default argument; a missing match raises StopIteration and fails the test
tests/test_analytics_state_freshness_api.py:862 GET_WITH_DEFAULT -> MARK: scanner false positive: literal located in _fetch_state source (the production line itself is reviewed in the server.py batch)
tests/test_analytics_state_freshness_api.py:863 GET_WITH_DEFAULT -> MARK: scanner false positive: literal located in _fetch_state source (the production line itself is reviewed in the server.py batch)
tests/test_anti_pattern_family_repo_wide.py:40 GET_OR_DEFAULT -> MARK: scanner false positive: string fixture proving the CAPS GET_OR_DEFAULT regex still fires
tests/test_anti_pattern_family_repo_wide.py:45 GET_OR_DEFAULT -> MARK: scanner false positive: string fixture proving the CAPS CAST_OR_DEFAULT regex still fires
tests/test_arch_competition_eval_runner.py:31 IF_NOT_NONE_ELSE -> MARK: fixture builder parameter: callers that pass prob_rows get theirs, the rest get the explicit near-uniform triplet this helper uses as its fixture input
tests/test_audit_cand_server_py_full_read_v1.py:362 GET_WITH_DEFAULT -> FIX (tightened): float(r['iv_level']) -- the default was unreachable behind the `is not None` guard
tests/test_audit_cand_server_py_full_read_v1.py:384 GETATTR_DEFAULT -> MARK: scanner false positive: forbidden-pattern literal asserted ABSENT from server.py
tests/test_backfill_signal_layer_v1_bundle.py:63 GET_OR_DEFAULT -> FIX (tightened): int(payload['signal_layer_v1']['meta.n_bars']) > 0
tests/test_bars_collected_for_all_tickers_v1.py:18 SETDEFAULT -> MARK: test-boot env switch read by import-time guards to recognise a pytest process; setdefault keeps a value pytest already set, it seeds no market data
tests/test_base_ticker_observability.py:438 GET_WITH_DEFAULT -> FIX (masking): `'NVDA' not in mat.get('by_ticker', {})` passes when by_ticker is missing; now mat['by_ticker']
tests/test_base_ticker_observability.py:818 GET_WITH_DEFAULT -> MARK: scanner false positive: literal searched for in server.py source to prove the scheduler gate defaults OFF
tests/test_batch2_analytics_bg_fail_counter.py:42 GET_WITH_DEFAULT -> FIX (tightened): md['state_error_detail']
tests/test_batch2_analytics_bg_fail_counter.py:63 GET_WITH_DEFAULT -> FIX (tightened): md['remediation']
tests/test_batch2_analytics_bg_fail_counter.py:176 GET_WITH_DEFAULT -> FIX (tightened): md['analytics_age_sec'] < 2.0
tests/test_batch2_analytics_bg_fail_counter.py:331 GET_OR_DEFAULT -> FIX (tightened): len(md['summary_rows']) == 1
tests/test_calibration_analyze_phase3.py:130 GET_WITH_DEFAULT -> FIX (tightened): out['model_by_regime_buckets']
tests/test_calibration_analyze_phase3.py:147 GET_WITH_DEFAULT -> FIX (tightened): out['regime_buckets']
tests/test_calibration_anchor_stability.py:46 GET_WITH_DEFAULT -> FIX (masking): `p3.get('calibration_rows', 0) == 0` passed with the key missing; now p3['calibration_rows'] == 0
tests/test_calibration_anchor_stability.py:48 GET_WITH_DEFAULT -> FIX (tightened): p3['provenance']['excluded_by_reason']['rows_without_bar_anchor_BAR_ANCHOR_V1'] (line 47's `or {}` chain removed too)
tests/test_calibration_anchor_stability.py:85 GET_WITH_DEFAULT -> FIX (tightened): p3['calibration_rows'] == 1
tests/test_calibration_anchor_stability.py:86 GET_OR_DEFAULT -> FIX (tightened): p3['provenance']['labeled_sample_count'] == 1
tests/test_calibration_daily_scoreboard.py:679 NEXT_DEFAULT -> MARK: scanner false positive: next() here has NO default argument; a missing function raises StopIteration and fails the test
tests/test_calibration_daily_scoreboard.py:968 GET_WITH_DEFAULT -> MARK: fixture row builder: callers override join_cohort via kwargs; the default is the explicit exact-timestamp cohort this helper builds
tests/test_calibration_daily_scoreboard.py:969 GET_WITH_DEFAULT -> MARK: fixture row builder: callers override bundle_identity_proven via kwargs; True is the helper's explicit proven-identity fixture value
tests/test_calibration_daily_scoreboard.py:1216 NEXT_DEFAULT -> MARK: scanner false positive: next() here has NO default argument; a missing function raises StopIteration and fails the test
tests/test_calibration_daily_scoreboard.py:1286 GET_WITH_DEFAULT -> MARK: the assertion is that NO SPY 60c extended cell exists; a missing SPY bucket is itself that outcome, not masked data
tests/test_calibration_daily_scoreboard.py:1467 NEXT_DEFAULT -> MARK: scanner false positive: next() here has NO default argument; a missing grid row raises StopIteration and fails the test
tests/test_calibration_daily_scoreboard.py:1798 NEXT_DEFAULT -> MARK: scanner false positive: next() here has NO default argument; a missing function raises StopIteration and fails the test
tests/test_calibration_legacy_quarantine.py:82 GET_WITH_DEFAULT -> FIX (tightened): out['provenance']['excluded_by_reason']['legacy_rows_excluded_from_study_dataset'] (line 81's `or {}` removed)
tests/test_calibration_legacy_quarantine.py:83 GET_WITH_DEFAULT -> FIX (masking): `out.get('calibration_rows', 0) == 0` passed with the key missing; now out['calibration_rows'] == 0
tests/test_calibration_logging_production_path.py:89 GETATTR_DEFAULT -> FIX (tightened): inp.refresh_ts_utc (SignalInput field); the 0.0 default would have fabricated a decision timestamp
tests/test_calibration_logging_production_path.py:90 GETATTR_DEFAULT -> FIX (tightened): inp.ticker (SignalInput field); the 'SPY' default would have fabricated the decision identity's ticker
tests/test_calibration_logging_production_path.py:96 GETATTR_DEFAULT -> FIX (tightened): inp.ticker; same fabricated-'SPY' identity default removed
tests/test_calibration_outcome_join_scale.py:84 GET_WITH_DEFAULT -> FIX (tightened): stats['skipped_no_exact_match'] == N_UNMATCHED
tests/test_calibration_outcome_join_scale.py:85 GET_WITH_DEFAULT -> FIX (masking): PHANTOM KEY: backfill() never emits 'ambiguous_duplicate_snapshots' (that is the reason code; the stat key is 'skipped_ambiguous_duplicate_snapshots'), so `.get(..., 0) == 0` was ALWAYS true and checked nothing; now stats['skipped_ambiguous_duplicate_snapshots'] == 0
tests/test_calibration_outcome_join_scale.py:86 GET_WITH_DEFAULT -> FIX (masking): PHANTOM KEY: backfill() never emits 'ambiguous_nearest_tie' (stat key is 'skipped_ambiguous_nearest_tie'); the assertion was always true; now stats['skipped_ambiguous_nearest_tie'] == 0
tests/test_call_owner_emission_veto_v1.py:154 NEXT_DEFAULT -> MARK: scanner false positive: next() here has NO default argument; a missing function raises StopIteration and fails the test
tests/test_call_owner_emission_veto_v1.py:158 GETATTR_DEFAULT -> MARK: AST duck typing: a Call.func that is neither Name nor Attribute (Subscript, Call, Lambda) has no name, and '' never matches the callees being counted
tests/test_call_owner_emission_veto_v1.py:172 NEXT_DEFAULT -> MARK: scanner false positive: next() here has NO default argument; a missing function raises StopIteration and fails the test
tests/test_call_owner_emission_veto_v1.py:174 NEXT_DEFAULT -> MARK: scanner false positive: next() here has NO default argument; a missing call raises StopIteration and fails the test
tests/test_call_owner_emission_veto_v1.py:179 NEXT_DEFAULT -> MARK: scanner false positive: next() here has NO default argument; a missing call raises StopIteration and fails the test
tests/test_call_prediction_vote.py:158 GET_WITH_DEFAULT -> FIX (tightened): out['component_scores']['confluence_score'] (default 15 > 7 already failed)
tests/test_caps_marker_is_line_scoped_v1.py:6 IF_NOT_NONE_ELSE -> MARK: scanner false positive: module docstring quoting the retired terrain_engine sort-key line
tests/test_caps_marker_is_line_scoped_v1.py:111 IF_NOT_NONE_ELSE -> MARK: scanner false positive: literal asserted ABSENT from terrain_engine.py
tests/test_centralization.py:340 GET_WITH_DEFAULT -> FIX (masking): model-health report printed `edge=+0.0pp` under _pass for a meta file with no edge metric (fabricated measured edge); now picks the first numeric edge_pp/val_accuracy/train_accuracy and prints `edge=n/a (...)` when none exists
tests/test_centralization.py:341 CAST_OR_DEFAULT -> FIX (masking): `float(edge or 0)` removed with the rewrite above; edge_pp is computed only from a real numeric metric
tests/test_centralization.py:562 GET_WITH_DEFAULT -> FIX (tightened): r_up.assumptions['per_bar_drift'] (monte_carlo always emits it; a 0 default would print as a measured drift in the fail message)
tests/test_centralization.py:563 GET_WITH_DEFAULT -> FIX (tightened): r_dn.assumptions['per_bar_drift']
tests/test_chain_accrual_and_storm1_v1.py:12 SETDEFAULT -> MARK: test-boot env switch read by import-time guards to recognise a pytest process; setdefault keeps a value pytest already set, it seeds no market data
tests/test_chain_api_v1.py:326 GET_WITH_DEFAULT -> FIX (tightened): body['stream_overlay_contracts'] >= 1
tests/test_chain_api_v1.py:402 GET_WITH_DEFAULT -> FIX (masking): `body.get('stream_overlay_contracts', 0) == 0` passed with the disclosure field missing; now body['stream_overlay_contracts'] == 0 (route always emits it on this path)
tests/test_chain_api_v1.py:500 GET_WITH_DEFAULT -> MARK: scanner false positive: HTTP GET via TestClient (path + query params), not a dict read with a default
tests/test_chart_accrual_consumer_v1.py:16 SETDEFAULT -> MARK: test-boot env switch read by import-time guards to recognise a pytest process; setdefault keeps a value pytest already set, it seeds no market data
tests/test_classify_schwab_csv_crosswalk.py:29 GET_OR_DEFAULT -> MARK: scanner false positive: code-string fixture fed to the CSV crosswalk classifier
tests/test_classify_schwab_csv_crosswalk.py:44 GET_OR_DEFAULT -> MARK: scanner false positive: code-string fixture fed to the CSV crosswalk classifier
tests/test_classify_schwab_csv_crosswalk.py:70 GET_WITH_DEFAULT -> MARK: scanner false positive: code-string fixture fed to the CSV crosswalk classifier
tests/test_classify_schwab_csv_crosswalk.py:82 GET_OR_DEFAULT -> MARK: scanner false positive: code-string fixture fed to the CSV crosswalk classifier
tests/test_classify_schwab_csv_crosswalk.py:121 GET_OR_DEFAULT -> MARK: scanner false positive: code-string fixture fed to the CSV crosswalk classifier
tests/test_classify_schwab_csv_crosswalk.py:135 CAST_OR_DEFAULT -> MARK: scanner false positive: code-string fixture fed to the CSV crosswalk classifier
tests/test_classify_schwab_csv_crosswalk.py:297 GET_OR_DEFAULT -> MARK: scanner false positive: code-string fixture fed to the CSV crosswalk classifier
tests/test_collect_window_law_v1.py:21 SETDEFAULT -> MARK: test-boot env switch read by import-time guards to recognise a pytest process; setdefault keeps a value pytest already set, it seeds no market data
tests/test_complete_chain_universal_capture_v1.py:374 GET_WITH_DEFAULT -> FIX (tightened): row['symbol'] -- every real TSLA template row carries symbol (236/236 measured); the 'X' default would have fabricated contract identity
tests/test_daily_system_health_check.py:121 GET_WITH_DEFAULT -> FIX (tightened): c['message'] (all 20 checks.append sites in verification/daily_health.py set id+message)
tests/test_daily_system_health_check.py:261 GET_WITH_DEFAULT -> FIX (tightened): gap_checks[0]['message']
tests/test_daily_system_health_check.py:262 GET_WITH_DEFAULT -> FIX (masking): inside `not any(...)`: a FAIL check with no id read '' and was never counted as a gap FAIL; now c['id']
tests/test_daily_system_health_check.py:289 GET_WITH_DEFAULT -> FIX (tightened): c['message'] (both reads)
tests/test_datetime_silent_default_repo_wide.py:1 GET_WITH_DEFAULT -> MARK: scanner false positive: module docstring naming the forbidden pattern
tests/test_datetime_silent_default_repo_wide.py:47 GET_WITH_DEFAULT -> MARK: scanner false positive: assertion message naming the forbidden pattern
tests/test_db_sqlite_tier1_retry.py:105 GET_WITH_DEFAULT -> FIX (tightened): snapshot['sqlite_lock_wait_count'] (always emitted by db_sqlite_utils)
tests/test_db_sqlite_tier1_retry.py:113 GET_WITH_DEFAULT -> FIX (tightened): snap['operations_affected']
tests/test_db_sqlite_tier1_retry.py:172 GET_WITH_DEFAULT -> FIX (tightened): snapshot['sqlite_database_locked_count']
tests/test_db_sqlite_tier1_retry.py:175 GET_WITH_DEFAULT -> FIX (tightened): snapshot['sqlite_database_locked_count']
tests/test_db_sqlite_tier1_retry.py:248 GET_WITH_DEFAULT -> FIX (tightened): report['classifications']
tests/test_delta_adds_no_debt_v1.py:214 NEXT_DEFAULT -> MARK: scanner false positive: next() here has NO default argument; a missing git worktree add call raises StopIteration and fails the test
tests/test_delta_adds_no_debt_v1.py:217 NEXT_DEFAULT -> MARK: scanner false positive: next() here has NO default argument; a missing gate invocation raises StopIteration and fails the test
tests/test_delta_adds_no_debt_v1.py:243 GETATTR_DEFAULT -> FIX (tightened): n.names -- both ast.Import and ast.ImportFrom always carry .names
tests/test_delta_adds_no_debt_v1.py:318 GETATTR_DEFAULT -> MARK: AST duck typing: an Attribute/Subscript callee has no .id, and '' never matches declared_retirements
tests/test_delta_adds_no_debt_v1.py:319 GETATTR_DEFAULT -> MARK: AST duck typing: an argument that is not a Name has no .id, and '' fails the == 'cand_wt' equality, so a wrong argument fails the test
tests/test_desk_store_v1.py:13 SETDEFAULT -> MARK: test-boot env switch read by import-time guards to recognise a pytest process; setdefault keeps a value pytest already set, it seeds no market data
tests/test_desk_store_v1.py:726 GET_WITH_DEFAULT -> FIX (tightened): payload['source']
tests/test_desk_store_v1.py:792 GETATTR_DEFAULT -> MARK: AST duck typing: an assignment target that is a Tuple/Attribute/Subscript has no .id, and '' never matches 'seed'
tests/test_duplication_audit_v1.py:265 GET_WITH_DEFAULT -> MARK: '' feeds the next line's assert reason with message 'the validation_summary exemption is missing', so absence fails with that named message
tests/test_ed_gamma_client_v1.py:58 GET_WITH_DEFAULT -> FIX (tightened): r.headers['content-type']
tests/test_f1_labeler_v2_seams.py:161 NEXT_DEFAULT -> MARK: scanner false positive: next() here has NO default argument; a missing exit bar raises StopIteration and fails the test
tests/test_f39_confluence_missingness.py:56 GETATTR_DEFAULT -> MARK: AST duck typing: a returned Call whose func is neither Name nor Attribute has no name, and '' never matches ConfluenceRead
tests/test_f39_confluence_missingness.py:70 SETDEFAULT -> MARK: scanner false positive: docstring quoting the RC-378 pattern this test locks out of server.py
tests/test_fast_lane_contract.py:34 GET_WITH_DEFAULT -> MARK: scanner false positive: HTTP GET via TestClient (path + query params), not a dict read with a default
tests/test_fast_lane_contract.py:83 GET_WITH_DEFAULT -> MARK: scanner false positive: HTTP GET via TestClient (path + query params), not a dict read with a default
tests/test_fast_lane_contract.py:112 GET_WITH_DEFAULT -> MARK: scanner false positive: HTTP GET via TestClient (path + query params), not a dict read with a default
tests/test_fast_lane_contract.py:116 GET_WITH_DEFAULT -> FIX (tightened): body['remediation']
tests/test_fetch_state_charm_phase_v1.py:36 GET_WITH_DEFAULT -> FIX (tightened): raw['contracts_used'] > 0
tests/test_fetch_state_pcr_phase_v1.py:79 GETATTR_DEFAULT -> MARK: scanner false positive: assertion message text
tests/test_fetch_state_predictive_positioning_phase_v1.py:82 CAST_OR_DEFAULT -> FIX (masking): REAL FINDING: the fixture buckets carried net_gex_1pct but no call_gex_1pct/put_gex_1pct, so aggregate_net_gex() returned None and BOTH production (server_state_predictive_positioning.py:132 `float(_gex_raw or 0.0)`) and this test's expected side fabricated 0.0 GEX -- the hedging-flow equality passed while never exercising the GEX term. Test now asserts _gex_raw is not None and uses float(_gex_raw); fixture given real per-side dollar GEX (net = call - put). Verified: the new assert FAILED on the old fixture, all 7 tests pass on the corrected one
tests/test_five_why_recursive_lock_v1.py:19 IF_NOT_NONE_ELSE -> MARK: fixture row builder: an explicit why argument wins, otherwise the helper's well-formed five-link chain is used
tests/test_fusion_contract.py:73 NEXT_DEFAULT -> MARK: scanner false positive: next(iter(set)) with NO default picks a real member of the tradable set and raises if the set were empty
tests/test_gamma_profile_v1.py:75 GET_WITH_DEFAULT -> FIX (tightened): c['putCall'] (fixture: 40/40 rows carry putCall)
tests/test_gamma_surface_cell_stream_state_v1.py:403 GET_WITH_DEFAULT -> FIX (masking): `cov.get('unavailable', 0) == 0` passed with the key missing; now cov['unavailable'] (server always emits it)
tests/test_gamma_surface_cell_stream_state_v1.py:437 GET_WITH_DEFAULT -> FIX (masking): `cov.get('pending', 0) == 0` passed with the key missing; now cov['pending']
tests/test_gamma_surface_cell_stream_state_v1.py:438 GET_WITH_DEFAULT -> FIX (masking): `cov.get('unavailable', 0) == 0` passed with the key missing; now cov['unavailable']
tests/test_gamma_surface_projection_v1.py:90 GET_OR_DEFAULT -> FIX (tightened): ct['openInterest'] > 0 (CRWD fixture: 218/218 rows carry OI)
tests/test_gamma_surface_projection_v1.py:91 GET_OR_DEFAULT -> FIX (tightened): ct['openInterest'] > 0 (CDE fixture: 74/74 rows carry OI)
tests/test_gamma_surface_projection_v1.py:188 NEXT_DEFAULT -> MARK: scanner false positive: next() here has NO default argument; an expiry with no DTE-bearing row raises StopIteration and fails the test
tests/test_gamma_surface_projection_v1.py:199 GET_OR_DEFAULT -> FIX (tightened): max key ct['openInterest']
tests/test_gamma_surface_projection_v1.py:219 GET_OR_DEFAULT -> FIX (tightened): max key ct['openInterest']
tests/test_gamma_surface_projection_v1.py:266 GET_OR_DEFAULT -> FIX (tightened): max key ct['openInterest']
tests/test_gamma_surface_projection_v1.py:285 GET_OR_DEFAULT -> FIX (tightened): max key ct['openInterest']
tests/test_gamma_surface_projection_v1.py:535 GET_WITH_DEFAULT -> FIX (masking): prior_view.get('near', []) let a prior view missing 'near' compare equal to an empty updated 'near'; now prior_view['near']
tests/test_gamma_surface_projection_v1.py:536 GET_WITH_DEFAULT -> FIX (masking): same for 'far'; now prior_view['far']
tests/test_governance_dashboard.py:266 GET_WITH_DEFAULT -> FIX (masking): all(...) over the audit list: a["ticker"] replaces the '' default, and the list is now asserted non-empty (an empty list made the ticker-scope check vacuous)
tests/test_governance_ui_dashboard.py:105 GET_WITH_DEFAULT -> MARK: scanner false positive: HTTP GET via TestClient (path + query params), not a dict read with a default
tests/test_greek_sanitization_v1.py:65 GET_WITH_DEFAULT -> FIX (masking): `bad_bucket.get('put_gamma', 0.0) == 0.0` (and exp_bad.get(748.0, {}) on line 64) passed with no bucket/key; now exp_bad[748.0]['put_gamma'] == 0.0 plus has_valid_gamma is False, proving the 0.0 is flagged as an absence
tests/test_greek_sanitization_v1.py:71 GET_OR_DEFAULT -> FIX (tightened): float(b['net_gamma']) -- every bucket carries a numeric net_gamma
tests/test_historical_backfill_enrolled_1m_v1.py:164 GET_WITH_DEFAULT -> FIX (tightened): out['candles_fetched'] >= 1
tests/test_hook_chain_v1.py:252 GETATTR_DEFAULT -> MARK: AST duck typing: a callee that is neither Attribute nor Name has no name, and '' is never one of the forbidden write callees
tests/test_institutional_key_levels.py:226 GET_WITH_DEFAULT -> FIX (tightened): c['putCall'] in the fixture-row selector
tests/test_institutional_key_levels.py:227 GET_OR_DEFAULT -> FIX (tightened): float(c['strikePrice']) in the fixture-row selector
tests/test_institutional_key_levels.py:231 GET_OR_DEFAULT -> FIX (tightened): int(src['daysToExpiration']) + 30 -- the `or 0` default would have fabricated a 30-DTE contract from a row with no DTE
tests/test_institutional_key_levels.py:277 GET_WITH_DEFAULT -> FIX (tightened): audit['proximity_detail']
tests/test_institutional_key_levels.py:321 GET_WITH_DEFAULT -> FIX (masking): all(... for d in audit.get('proximity_detail', [])) is vacuously true when compute_wall_score_components takes its early-return path (walls_empty / no_consensus_row audits carry no proximity_detail); now audit['proximity_detail']
tests/test_institutional_key_levels.py:334 GET_WITH_DEFAULT -> FIX (masking): 'dom_gamma_wall' not in [] passes on the early-return audit; now audit2['proximity_detail']
tests/test_institutional_key_levels.py:345 GET_WITH_DEFAULT -> FIX (masking): 'dom_gamma_wall' not in [] passes on the early-return audit; now audit3['proximity_detail']
tests/test_institutional_key_levels.py:894 NEXT_DEFAULT -> MARK: None is asserted against on the very next line (assert spy is not None), so a missing SPY snapshot fails the test
tests/test_institutional_key_levels.py:908 NEXT_DEFAULT -> FIX (tightened): next() without the None default; a missing SPY snapshot now raises instead of a TypeError on None
tests/test_issue20_23_live_bundle.py:256 IF_NOT_NONE_ELSE -> MARK: fake fetch mirrors server cache keying: an auto (None) expiry writes to the auto-expiry slot the test registered, a real expiry to its own slot
tests/test_issue20_23_live_bundle.py:276 GET_WITH_DEFAULT -> MARK: scanner false positive: HTTP GET via TestClient (path + query params), not a dict read with a default
tests/test_issue20_23_live_bundle.py:286 GET_WITH_DEFAULT -> MARK: scanner false positive: HTTP GET via TestClient (path + query params), not a dict read with a default
tests/test_issue20_23_live_bundle.py:293 GET_WITH_DEFAULT -> MARK: scanner false positive: HTTP GET via TestClient (path + query params), not a dict read with a default
tests/test_issue20_23_live_bundle.py:297 GET_WITH_DEFAULT -> FIX (tightened): body3['decision_generation_id'] >= 424201
tests/test_issue20_23_live_bundle.py:306 GET_WITH_DEFAULT -> MARK: scanner false positive: HTTP GET via TestClient (path + query params), not a dict read with a default
tests/test_issue20_23_live_bundle.py:402 IF_NOT_NONE_ELSE -> MARK: fake fetch mirrors server cache keying: an auto (None) expiry writes to the auto-expiry slot the test registered, a real expiry to its own slot
tests/test_issue20_23_live_bundle.py:423 GET_WITH_DEFAULT -> MARK: scanner false positive: HTTP GET via TestClient (path + query params), not a dict read with a default
tests/test_issue20_23_live_bundle.py:426 GET_WITH_DEFAULT -> MARK: scanner false positive: HTTP GET via TestClient (path + query params), not a dict read with a default
tests/test_l1_generation_atomicity.py:62 GET_WITH_DEFAULT -> FIX (tightened): srv._l1_instrumentation['l1_generation_assign_total'] (pre-initialised in server.py)
tests/test_l1_generation_atomicity.py:64 GET_WITH_DEFAULT -> FIX (tightened): same key indexed
tests/test_l1_light_sse.py:86 GET_WITH_DEFAULT -> FIX (tightened): srv._l1_sse_diag['l1_light_sse_events_throttled'] (pre-initialised)
tests/test_l1_light_sse.py:96 GET_WITH_DEFAULT -> FIX (tightened): same key indexed
tests/test_l1_remediation.py:84 GET_OR_DEFAULT -> FIX (masking): `(out.get('l2_snapshot_version_used') or 0) == 0` passed with the field missing; now out['l2_snapshot_version_used'] == 0 (planes/context_light always emits it)
tests/test_l1_remediation.py:135 GET_WITH_DEFAULT -> FIX (tightened): snap['l1_instrumentation']['l1_build_reason']
tests/test_l1_remediation.py:166 GET_WITH_DEFAULT -> FIX (tightened): inst['l1_build_scope']['ticker'] (line 164's `or {}` removed too)
tests/test_l1_remediation.py:167 GET_WITH_DEFAULT -> FIX (tightened): inst['l1_build_scope']['expiry']
tests/test_l1_remediation.py:180 GET_WITH_DEFAULT -> FIX (tightened): l1_build_by_reason['quote_material_of']
tests/test_l1_remediation.py:196 GET_WITH_DEFAULT -> FIX (tightened): d2['l1_projection']['mode']
tests/test_l1_remediation.py:243 GET_WITH_DEFAULT -> FIX (tightened): d['l1_instrumentation']['l1_build_reason']
tests/test_l1_remediation.py:245 GET_WITH_DEFAULT -> FIX (tightened): d2['l1_projection']['mode']
tests/test_l1_remediation.py:246 GET_WITH_DEFAULT -> FIX (tightened): d2['l1_instrumentation']['l1_projection_read']
tests/test_l1_sse_backpressure.py:24 GET_WITH_DEFAULT -> FIX (tightened): _l1_sse_diag['l1_light_sse_client_queue_evicted_oldest'] (pre-initialised)
tests/test_l1_sse_backpressure.py:27 GET_WITH_DEFAULT -> FIX (tightened): same key indexed
tests/test_l1_sse_backpressure.py:41 GET_WITH_DEFAULT -> FIX (tightened): _l1_sse_diag['l1_light_sse_thread_queue_evicted_oldest']
tests/test_l1_sse_backpressure.py:44 GET_WITH_DEFAULT -> FIX (tightened): same key indexed
tests/test_l1_sse_backpressure.py:74 GET_WITH_DEFAULT -> FIX (masking): v0 and the after-read both defaulted to 0, so `== v0` passed with the counter missing; now indexed
tests/test_l1_sse_backpressure.py:77 GET_WITH_DEFAULT -> FIX (masking): see line 74; now indexed
tests/test_l1_sse_backpressure.py:94 GET_WITH_DEFAULT -> FIX (tightened): _l1_sse_diag['l1_payload_identity_violation']
tests/test_l1_sse_backpressure.py:97 GET_WITH_DEFAULT -> FIX (tightened): same key indexed
tests/test_l1_sse_scaling_safety.py:144 GET_WITH_DEFAULT -> FIX (tightened): _l1_sse_diag['l1_light_sse_rejected_total']
tests/test_l1_sse_scaling_safety.py:175 GET_WITH_DEFAULT -> FIX (tightened): _l1_sse_diag['l1_light_sse_duplicate_scope_same_client_warn_total']
tests/test_l1_sse_scaling_safety.py:179 GET_WITH_DEFAULT -> FIX (tightened): same key indexed
tests/test_level_crosses_wire.py:254 NEXT_DEFAULT -> MARK: scanner false positive: next() here has NO default argument; a missing api_level_crosses raises StopIteration and fails the test
tests/test_levels_single_producer_v1.py:86 GETATTR_DEFAULT -> MARK: AST duck typing: a Call.func that is neither Name nor Attribute has no name, and '' never matches compute_terrain
tests/test_levels_single_producer_v1.py:109 GETATTR_DEFAULT -> MARK: AST duck typing: a Call.func that is neither Name nor Attribute has no name; '' in the callee set matches no real producer name
tests/test_levels_single_producer_v1.py:389 NEXT_DEFAULT -> MARK: scanner false positive: next() has NO default; StopIteration is caught on purpose three lines below
tests/test_levels_single_producer_v1.py:390 NEXT_DEFAULT -> MARK: scanner false positive: next() has NO default; StopIteration is caught on purpose two lines below
tests/test_levels_single_producer_v1.py:604 NEXT_DEFAULT -> MARK: scanner false positive: next() here has NO default argument; a missing census concept raises StopIteration and fails the test
tests/test_levels_single_producer_v1.py:605 GET_WITH_DEFAULT -> FIX (tightened): vwap['status']
tests/test_levels_single_producer_v1.py:607 NEXT_DEFAULT -> MARK: scanner false positive: next() here has NO default argument; a missing census concept raises StopIteration and fails the test
tests/test_levels_single_producer_v1.py:609 NEXT_DEFAULT -> MARK: scanner false positive: next() here has NO default argument; a missing census concept raises StopIteration and fails the test
tests/test_levels_single_producer_v1.py:611 NEXT_DEFAULT -> MARK: scanner false positive: next() here has NO default argument; a missing census concept raises StopIteration and fails the test
tests/test_levels_single_producer_v1.py:612 GET_WITH_DEFAULT -> FIX (tightened): prior['status']
tests/test_levels_single_producer_v1.py:936 GET_WITH_DEFAULT -> FIX (tightened): reg['operator_quote']
tests/test_liquidity_engine.py:525 GETATTR_DEFAULT -> MARK: enum-or-str duck typing: an Enum zone_type exposes .value, a plain-string zone_type already is the value
tests/test_liquidity_engine.py:567 GETATTR_DEFAULT -> MARK: display-only: the line number is printed in the offender report; '?' is never parsed back
tests/test_liquidity_engine.py:843 GET_WITH_DEFAULT -> FIX (tightened): out.raw_levels['prev_day']
tests/test_live_drift_monitoring.py:138 GET_WITH_DEFAULT -> FIX (tightened): [s['reason_code'] for s in pl['signals']]
tests/test_live_drift_monitoring.py:189 GET_WITH_DEFAULT -> FIX (masking): `REASON not in codes` passed when 'signals' was missing; now pl['signals'] / s['reason_code']
tests/test_live_drift_monitoring.py:312 GET_WITH_DEFAULT -> FIX (tightened): payload['signals'] / s['reason_code']
tests/test_live_drift_monitoring.py:464 GET_WITH_DEFAULT -> FIX (tightened): pl['signals'] / s['reason_code']
tests/test_live_ui_integrity_v1.py:647 GET_WITH_DEFAULT -> FIX (masking): for-loop over report.get('classifications', []) was vacuous on a missing key; now report['classifications']
tests/test_lp01_touch_study_v1.py:12 SETDEFAULT -> MARK: test-boot env switch read by import-time guards to recognise a pytest process; setdefault keeps a value pytest already set, it seeds no market data
tests/test_market_state_numeric_contract_v1.py:23 GET_WITH_DEFAULT -> MARK: fixture builder: callers override the probability through pred_kw; 0.2 is the helper's explicit fixture input, not a read of real data
tests/test_market_state_numeric_contract_v1.py:24 GET_WITH_DEFAULT -> MARK: fixture builder: callers override the probability through pred_kw; 0.2 is the helper's explicit fixture input, not a read of real data
tests/test_mc_base_neutral_mode_v1.py:94 SETDEFAULT -> MARK: test seam pins the RNG seed only when the caller passed none, so two simulations compare model effect, not sampling noise (see comment above)
tests/test_ml_data_common_et_helpers.py:289 GET_WITH_DEFAULT -> FIX (tightened): doc['snapshots_prior_net_gamma']['ok']
tests/test_ml_feature_schema_parity.py:517 GET_WITH_DEFAULT -> FIX (masking): `len(whole) == report.get('whole_stack_feature_cell_count', len(whole))` compared len(whole) to itself when the key was missing; now report['whole_stack_feature_cell_count']
tests/test_ml_feature_schema_parity.py:1458 GET_WITH_DEFAULT -> FIX (tightened): summary['drops_by_model_horizon']['xgb/1c']
tests/test_ml_feature_schema_parity.py:2078 GETATTR_DEFAULT -> MARK: AST duck typing: a callee with neither .id nor .attr has no name, and '' never equals prepare_row_for_xgb_features, so it is reported as bare
tests/test_ml_feature_schema_parity.py:2223 GETATTR_DEFAULT -> MARK: AST duck typing: a callee with neither .id nor .attr has no name, and '' never equals train_ticker
tests/test_model_edge_absent_is_not_zero_v1.py:6 GET_WITH_DEFAULT -> MARK: scanner false positive: module docstring quoting the removed server.py line
tests/test_model_edge_absent_is_not_zero_v1.py:7 CAST_OR_DEFAULT -> MARK: scanner false positive: module docstring quoting the removed server.py line
tests/test_model_edge_absent_is_not_zero_v1.py:47 GET_WITH_DEFAULT -> MARK: scanner false positive: literal asserted ABSENT from server.py
tests/test_model_edge_absent_is_not_zero_v1.py:49 CAST_OR_DEFAULT -> MARK: scanner false positive: literal asserted ABSENT from server.py
tests/test_money_path_orphan_keys_v1.py:5 GET_WITH_DEFAULT -> MARK: scanner false positive: module docstring quoting the RC-85 defect
tests/test_movement_target_phase_eval_contract_v1.py:38 GET_WITH_DEFAULT -> FIX (masking): `'label_statistics' in hz or hz == {}` passed when horizons/5c were missing; the phase-5 producer writes every HORIZONS_MV horizon with label_statistics, so now data['horizons']['5c'] and a plain membership assert (test is skipif-guarded on the production JSON)
tests/test_operator_law_guard_repo_scope_v1.py:548 GETATTR_DEFAULT -> FIX (tightened): node.end_lineno -- always set on ast.parse FunctionDef nodes
tests/test_option_volume_is_live_v1.py:36 GET_OR_DEFAULT -> FIX (tightened): ground-truth builder now reads int(c['totalVolume']) (40/40 fixture rows carry it); the remaining out.get(k, 0) is the per-strike accumulator
tests/test_options_history_state_equivalence_v1.py:501 NEXT_DEFAULT -> MARK: scanner false positive: next() here has NO default argument; a sample without an l1 event raises StopIteration and fails the test
tests/test_options_history_state_equivalence_v1.py:512 NEXT_DEFAULT -> MARK: scanner false positive: next() here has NO default argument; a sample without a book event raises StopIteration and fails the test
tests/test_options_order_flow_api_v1.py:164 GET_WITH_DEFAULT -> FIX (tightened): body['error']
tests/test_options_order_flow_api_v1.py:228 GET_WITH_DEFAULT -> FIX (tightened): body['error']
tests/test_options_order_flow_production_v1.py:211 GET_WITH_DEFAULT -> MARK: fixture-regeneration normaliser: rewrites the machine-specific path only when present; a payload missing the block is written as-is and the key-path contract test then fails on it
tests/test_order_flow_book_heatmap_v1.py:37 IF_NOT_NONE_ELSE -> MARK: fixture book builder: a None bid price builds a one-sided book with an empty BIDS array, the shape Schwab sends for an empty side
tests/test_order_flow_book_heatmap_v1.py:38 IF_NOT_NONE_ELSE -> MARK: fixture book builder: a None ask price builds a one-sided book with an empty ASKS array, the shape Schwab sends for an empty side
tests/test_partial_remediations_closed_v1.py:127 GET_WITH_DEFAULT -> MARK: scanner false positive: literal asserted ABSENT from server.py
tests/test_pilot_step3_events.py:28 GET_WITH_DEFAULT -> MARK: fixture config builder: a test that passes no candidate_generator override gets the base config unchanged
tests/test_pinning_score_needs_a_pin_v1.py:99 GETATTR_DEFAULT -> FIX (tightened): SignalInput.__annotations__ (dataclass always has it)
tests/test_pred_1c_eddb_and_audit_contract_v1.py:27 GET_WITH_DEFAULT -> MARK: opt-in env flag: unset means the hard production-data gate was not requested for this run
tests/test_probe_failure_is_not_success_v1.py:168 IF_TRUTHY_ELSE -> MARK: subprocess.run stub: echoes the argv it was called with into the fake CompletedProcess; the failure under test is the rc/stderr
tests/test_quarantine_outside_window_v1.py:15 SETDEFAULT -> MARK: test-boot env switch read by import-time guards to recognise a pytest process; setdefault keeps a value pytest already set, it seeds no market data
tests/test_radar_levels_provenance_v1.py:19 SETDEFAULT -> MARK: test-boot env switch read by import-time guards to recognise a pytest process; setdefault keeps a value pytest already set, it seeds no market data
tests/test_radar_two_sided_wall_v1.py:17 SETDEFAULT -> MARK: test-boot env switch read by import-time guards to recognise a pytest process; setdefault keeps a value pytest already set, it seeds no market data
tests/test_rth_completeness_check_v1.py:16 SETDEFAULT -> MARK: test-boot env switch read by import-time guards to recognise a pytest process; setdefault keeps a value pytest already set, it seeds no market data
tests/test_runtime_governance_decoupling_v1.py:305 GETATTR_DEFAULT -> MARK: AST duck typing: a callee that is neither Attribute nor Name has no name, and '' never ends with Path
tests/test_schwab_capability_boundary_v1.py:93 NEXT_DEFAULT -> MARK: scanner false positive: next() here has NO default argument; a launcher without the sanitize line raises StopIteration and fails the test
tests/test_schwab_gate_fail_closed_working_sync_v1.py:46 GET_OR_DEFAULT -> MARK: scanner false positive: code-string fixture fed to the CSV crosswalk classifier
tests/test_schwab_market_derivation_catalog_v1.py:55 GET_WITH_DEFAULT -> MARK: scanner false positive: line of a source-string fixture the derivation catalog must flag as DICT_GET_MARKET_DEFAULT
tests/test_scorecard_stale_fails_closed_v1.py:17 SETDEFAULT -> MARK: test-boot env switch read by import-time guards to recognise a pytest process; setdefault keeps a value pytest already set, it seeds no market data
tests/test_semantic_faucet_definition_scope_v1.py:104 GET_WITH_DEFAULT -> FIX (tightened): c['putCall'] in the fixture-row selector
tests/test_semantic_faucet_definition_scope_v1.py:105 GET_OR_DEFAULT -> FIX (tightened): float(c['strikePrice']) in the fixture-row selector
tests/test_semantic_faucet_definition_scope_v1.py:109 GET_OR_DEFAULT -> FIX (tightened): int(src['daysToExpiration']) + 30 -- removes a fabricated-DTE fixture path
tests/test_single_producer_batch_f02_f13_v1.py:599 GET_WITH_DEFAULT -> MARK: scanner false positive: HTTP GET via TestClient (path + query params), not a dict read with a default
tests/test_single_producer_batch_f02_f13_v1.py:1633 NEXT_DEFAULT -> MARK: scanner false positive: next() here has NO default argument; a missing builder def raises StopIteration and fails the test
tests/test_single_producer_batch_f02_f13_v1.py:1723 NEXT_DEFAULT -> MARK: scanner false positive: next() here has NO default argument; a missing def raises StopIteration and fails the test
tests/test_single_producer_batch_f02_f13_v1.py:1743 NEXT_DEFAULT -> MARK: scanner false positive: next() here has NO default argument; a missing def raises StopIteration and fails the test
tests/test_single_producer_batch_f02_f13_v1.py:1869 NEXT_DEFAULT -> MARK: scanner false positive: next() here has NO default argument; a missing def raises StopIteration and fails the test
tests/test_stack_wire_2_v1.py:56 GETATTR_DEFAULT -> FIX (masking): the test re-implemented the fallback branch in-test (with an unreachable getattr default) and asserted on its own assignment -- a tautology; it now reads the real branch from inspect.getsource(market_state.build_market_state) and asserts the stamped provenance is not tradable
tests/test_stage1_session_cohort_contract.py:113 GET_WITH_DEFAULT -> MARK: the assertion is that NO target is experiment-eligible; targets_by_status only creates keys for statuses that occur, so a missing key is exactly the asserted outcome
tests/test_stage1_target_registry.py:40 GET_WITH_DEFAULT -> MARK: the assertion is that NO target is production-approved; targets_by_status only creates keys for statuses that occur, so a missing key is exactly the asserted outcome
tests/test_stage1_target_registry.py:48 GET_WITH_DEFAULT -> MARK: the assertion is that NO target is experiment-eligible; targets_by_status only creates keys for statuses that occur, so a missing key is exactly the asserted outcome
tests/test_stage1_target_registry.py:142 GET_WITH_DEFAULT -> MARK: mutation-target selector: a target without a family is simply not selected; if none is selected the error assertion below fails
tests/test_static_asset_revalidation_v1.py:30 GET_WITH_DEFAULT -> MARK: scanner false positive: HTTP GET via TestClient (path + headers), not a dict read with a default
tests/test_stream_capture_daemon_v1.py:2148 SETDEFAULT -> MARK: first-write-wins timing mark: the first surrender instant is the one under test, a later shutdown pass must not overwrite it
tests/test_stream_capture_daemon_v1.py:2152 SETDEFAULT -> MARK: first-write-wins timing mark: the first surrender instant is the one under test, a later shutdown pass must not overwrite it
tests/test_stream_capture_daemon_v1.py:2160 SETDEFAULT -> MARK: first-write-wins timing mark: the recycle barrier start must not be overwritten by the later shutdown barrier
tests/test_stream_capture_daemon_v1.py:2164 SETDEFAULT -> MARK: first-write-wins timing mark: the recycle barrier's wait must not be overwritten by the later shutdown barrier
tests/test_stream_capture_daemon_v1.py:2199 GET_WITH_DEFAULT -> MARK: 0.0 means the barrier never ran; both callers assert waited >= 0.9 with 'the barrier must actually have engaged', so absence fails loudly
tests/test_streamed_greeks_hook_v1.py:748 GET_WITH_DEFAULT -> MARK: negative control asserting != 3: an unpublished surface, or one no overlay pass touched, genuinely overlaid zero contracts
tests/test_t5_sse_db_contention.py:126 GET_WITH_DEFAULT -> MARK: mirrors server's documented env default (5.0s) so the assertion holds whether or not the operator env sets it
tests/test_t5_sse_db_contention.py:129 GET_WITH_DEFAULT -> MARK: mirrors server's documented env default (5.0s) so the assertion holds whether or not the operator env sets it
tests/test_terrain_atr_radar_v1.py:109 GET_WITH_DEFAULT -> FIX (tightened): r.headers['cache-control']
tests/test_terrain_engine_v1.py:120 GETATTR_DEFAULT -> FIX (tightened): snap.lines (TerrainSnapshot field, default_factory=list)
tests/test_terrain_engine_v1.py:373 GET_OR_DEFAULT -> FIX (tightened): float(c['strikePrice']) in the pin-row selector
tests/test_terrain_engine_v1.py:378 GET_OR_DEFAULT -> FIX (tightened): int(c['daysToExpiration']) + 30 -- removes a fabricated-DTE fixture path
tests/test_terrain_engine_v1.py:380 GET_OR_DEFAULT -> FIX (tightened): float(c['openInterest']) + 50_000 -- removes a fabricated-OI fixture path
tests/test_terrain_engine_v1.py:396 GET_OR_DEFAULT -> FIX (masking): `float(sb.get('call_oi') or 0) + float(sb.get('put_oi') or 0)` turned a bucket with no gated OI into a measured 0; new _bucket_oi() helper (None when neither side cleared the OI gate, shared with _book_oi) + assert the pin bucket carries real OI
tests/test_terrain_engine_v1.py:407 GET_OR_DEFAULT -> FIX (masking): same expression in the selected-expiry pin-score ratio; now sel_pin_oi from _bucket_oi()
tests/test_training_pipeline_status_v1.py:17 GET_WITH_DEFAULT -> FIX (tightened): counts['core'] >= 2
tests/test_training_pipeline_status_v1.py:18 GET_WITH_DEFAULT -> FIX (tightened): counts['pinned'] >= 1
tests/test_verification_wave_lock_v1.py:111 IF_TRUTHY_ELSE -> MARK: assertion-message text only: prints captured stdout when a pipe exists
tests/test_watchlist_chg_pct_universality_v1.py:241 GET_WITH_DEFAULT -> MARK: scanner false positive: HTTP GET via TestClient (path + query params), not a dict read with a default
tests/test_watchlist_chg_pct_universality_v1.py:265 GET_WITH_DEFAULT -> MARK: scanner false positive: HTTP GET via TestClient (path + query params), not a dict read with a default
tests/test_watchlist_chg_pct_universality_v1.py:298 GET_WITH_DEFAULT -> MARK: scanner false positive: HTTP GET via TestClient (path + query params), not a dict read with a default
tests/test_watchlist_chg_pct_universality_v1.py:329 GET_WITH_DEFAULT -> MARK: scanner false positive: HTTP GET via TestClient (path + query params), not a dict read with a default
tests/test_watchlist_chg_pct_universality_v1.py:363 GET_WITH_DEFAULT -> MARK: scanner false positive: HTTP GET via TestClient (path + query params), not a dict read with a default

TOTAL 324 | MARK 183 | FIX (masking) 31 | FIX (tightened) 110
