# CAPS batch 1 ledger (line numbers = ORIGINAL hit inventory lines)

adaptive_shadow_v2_calibration.py:88 GET_WITH_DEFAULT -> FIX: resolve_overlay_for_anchor always returns resolution.tries; `.get("resolution",{}).get("tries") or []` would turn a changed/broken producer into overlay_found=False. Now strict r["resolution"]["tries"].
adaptive_shadow_v2_calibration.py:131 IF_TRUTHY_ELSE -> FIX: mean_pool_size reported 0.0 when zero anchors measured; now None (consumer distance_option_a_backfill_v1.py:464 updated too).
adaptive_shadow_v2_calibration.py:204 IF_TRUTHY_ELSE -> MARK: bool->int encoding of computed tier_stop_viable for a fraction; no missing value involved.
adaptive_shadow_v2_calibration.py:252 GET_OR_DEFAULT -> FIX: sort key read unmeasured (None) mean Jaccard as 0.0; replaced with explicit None-last sort key over required aggregate keys.
adaptive_shadow_v2_calibration.py:253 GET_OR_DEFAULT -> FIX: same, fraction_tier_stop_viable None -> sorted last, not 0.0.
adaptive_shadow_v2_calibration.py:254 GET_OR_DEFAULT -> FIX: stdev None read as 0.0 ranked an unmeasured config as MOST stable (ascending key); now None sorts last.
adaptive_shadow_v2_calibration.py:261 NEXT_DEFAULT -> MARK: next(...,None) lookup of mid_baseline; None handled explicitly (baseline None -> delta None).
adaptive_shadow_v2_calibration.py:269 IF_TRUTHY_ELSE -> FIX: missing mid_baseline fabricated base_j=[0.0] / base_mean_j=0.0 so "mean_delta_jaccard_vs_mid_baseline" reported raw Jaccard as a delta; now base_mean_j None and the delta is None.
adaptive_shadow_v2_calibration.py:303 GET_OR_DEFAULT -> FIX: structural_pool_size is always written (int candidate_pool_size); `or 0` would count a missing value as an empty pool. Now strict index.
app/options/order_flow/engine.py:558 IF_TRUTHY_ELSE -> MARK: no book snapshot -> empty level list; absence carried by has_book=False/status no_book/book_source unavailable, and depth total/slope/concentration all return None on an empty side.
app/options/order_flow/engine.py:559 IF_TRUTHY_ELSE -> MARK: same as 558 for the ask side.
app/options/order_flow/state.py:287 IF_TRUTHY_ELSE -> MARK: count of buffered book events; no buffer = zero events stored (true count).
app/options/order_flow/state.py:288 IF_TRUTHY_ELSE -> MARK: count of buffered tape prints; no buffer = zero prints stored (true count).
audit_gate_labels.py:56 IF_TRUTHY_ELSE -> FIX: printed "0.00%" bad rows when there were 0 RTH rows (undefined ratio); now None printed "n/a (0 RTH rows)".
audit_gate_labels.py:57 IF_TRUTHY_ELSE -> FIX: same for confirmed-bad percentage.
audit_model_readiness.py:606 GET_WITH_DEFAULT -> FIX: check_artifact_compliance (verify_active_models.py) always returns "issues"; strict index.
audit_snapshot_data.py:100 IF_TRUTHY_ELSE -> FIX: branch only reachable after prev_ts was set; `if prev_ts else 0` fabricated a 0 gap (and mis-read ts 0). Now direct subtraction.
backfill_flow_imbalance.py:174 GET_WITH_DEFAULT -> MARK: provenance bucket counter, empty bucket = 0 rows.
backfill_flow_imbalance.py:177 GET_WITH_DEFAULT -> MARK: provenance bucket counter, empty bucket = 0 rows.
bar_rehydration_issue19_v1.py:248 GET_OR_DEFAULT -> FIX: collect_bar_recovery_audit always sets pin_neutral_anchor_feasible_count; `or 0` would silently skip schema flag + repair on a producer change. Strict index.
bar_rehydration_issue19_v1.py:278 GET_OR_DEFAULT -> FIX: fill_outcomes_pin_neutral_backfill_v1 always sets updates_executed; strict index.
bar_rehydration_issue19_v1.py:325 GETATTR_DEFAULT -> FIX: flag is always registered by register_allow_noncanonical_flag in main(); strict attribute access.
bayesian_fusion.py:223 GETATTR_DEFAULT -> MARK: fail-closed availability gate; output counts only on explicit available=True, missing attr -> None dominant class.
bayesian_fusion.py:238 GETATTR_DEFAULT -> MARK: fail-closed availability gate; missing attr -> triplet None.
bayesian_fusion.py:258 GETATTR_DEFAULT -> MARK: fail-closed; XGB evidence excluded ({}) unless producer set available=True.
bayesian_fusion.py:283 GETATTR_DEFAULT -> MARK: fail-closed; LSTM evidence excluded unless available=True.
bayesian_fusion.py:308 GETATTR_DEFAULT -> MARK: fail-closed; transformer evidence excluded unless available=True.
bayesian_fusion.py:333 GETATTR_DEFAULT -> FIX: RulesCard.signal is a required field; getattr default "wait" fabricated a rules read that was fused as real pinning/mean-reversion evidence. Now rules.signal (missing -> fuse() fails closed, available=False). Test test_bayesian_fusion_v2 encoded the fabricated default; corrected.
bayesian_fusion.py:334 GETATTR_DEFAULT -> FIX: RulesCard.conviction required; default "low" fabricated a conviction multiplier. Now rules.conviction.
bayesian_fusion.py:378 GETATTR_DEFAULT -> FIX: direction_hint default "wait" fabricated; now rules.signal (FusionTickCache path).
bayesian_fusion.py:508 GETATTR_DEFAULT -> FIX: same as 378 on the non-cached path.
bayesian_fusion.py:526 GETATTR_DEFAULT -> MARK: fail-closed; missing available attr zeroes XGB weight and lists it in missing_models.
bayesian_fusion.py:527 GETATTR_DEFAULT -> MARK: fail-closed; LSTM weight zeroed + listed missing.
bayesian_fusion.py:528 GETATTR_DEFAULT -> MARK: fail-closed; transformer weight zeroed + listed missing.
bayesian_fusion.py:605 GETATTR_DEFAULT -> MARK: fail-closed; only explicit available=True counts toward ensemble diversity (keeps dampening on).
bayesian_fusion.py:607 GETATTR_DEFAULT -> MARK: same for LSTM.
bayesian_fusion.py:649 GETATTR_DEFAULT -> MARK: fail-closed; directional triplet only from explicitly available model. (Adjacent weights.get(src,0.0) also made strict weights[src].)
bayesian_fusion.py:687 GET_WITH_DEFAULT -> MARK: env knob ED_SIGNAL_LAYER_FUSION_BLEND, documented default 0.0 = blend off.
bayesian_fusion.py:720 GETATTR_DEFAULT -> MARK: fail-closed; MC evidence text only on explicit available=True.
bayesian_fusion.py:726 GETATTR_DEFAULT -> MARK: fail-closed; XGB evidence text only on explicit available=True.
bayesian_fusion.py:775 GETATTR_DEFAULT -> MARK: fail-closed; MC pass-through fields None unless available=True.
bayesian_fusion.py:797 GET_WITH_DEFAULT -> FIX: weights always holds every BASE_WEIGHTS key; .get(k,0) would publish a missing weight as 0.0 in the served FusionPayload. Strict index.
bayesian_fusion.py:798 GET_WITH_DEFAULT -> FIX: same (lstm).
bayesian_fusion.py:799 GET_WITH_DEFAULT -> FIX: same (transformer).
bayesian_fusion.py:801 GET_WITH_DEFAULT -> FIX: same (rules).
bayesian_fusion.py:802 GET_WITH_DEFAULT -> FIX: same (regime).
call_engine.py:181 GETATTR_DEFAULT -> FIX: provenance read strictly (required CanonicalForecast field); withheld readiness now returns (None, None) instead of fabricated ("flat", 0.0). setup_readiness handles None dir (no match) and None prob ("unavailable"); readiness score/wording unchanged. Test test_action11_9 updated (encoded "flat"/0.0).
call_engine.py:327 GETATTR_DEFAULT -> MARK: fail-closed; MC reasoning snippet only on explicit mc_available=True.
call_engine.py:341 IF_TRUTHY_ELSE -> MARK: scanner false positive; chooses between two measured MC probs proven non-None.
call_engine.py:375 GET_WITH_DEFAULT -> FIX: fabricated reason label "unknown" removed; .get("reason") None -> generic WAIT text branch.
call_engine.py:377 GET_WITH_DEFAULT -> FIX: stack blocker always carries long_count (compute_call); `.get(...,0)` would render a fabricated "0 long" in the served headline. Strict.
call_engine.py:378 GET_WITH_DEFAULT -> FIX: same, short_count.
call_engine.py:379 GET_WITH_DEFAULT -> FIX: same, threshold (default 2 disagreed with STACK_THRESHOLD source of truth).
call_engine.py:380 GET_WITH_DEFAULT -> FIX: same, long_names.
call_engine.py:381 GET_WITH_DEFAULT -> FIX: same, short_names.
call_engine.py:391 GET_WITH_DEFAULT -> FIX: every vol_regime blocker sets detail; canned "unstable" text could mislabel a "vol_regime unavailable" WAIT. Strict.
call_engine.py:393 GET_WITH_DEFAULT -> FIX: every vol_regime blocker sets full_detail. Strict.
call_engine.py:395 GET_WITH_DEFAULT -> FIX: gates blocker always sets gate_reasons. Strict.
call_engine.py:399 GET_WITH_DEFAULT -> FIX: time blockers always set detail; canned "<=30 min to close" would mislabel the "mins_to_close unavailable" WAIT. Strict.
call_engine.py:401 GET_WITH_DEFAULT -> FIX: time blockers always set full_detail. Strict.
call_engine.py:520 GETATTR_DEFAULT -> FIX: canonical.direction strict (required field; dominant_probability() already called on same object).
call_engine.py:521 GETATTR_DEFAULT -> FIX: canonical.confidence strict.
call_engine.py:870 GETATTR_DEFAULT -> FIX: canonical.confidence strict; None/invalid now flows into the existing explicit invalid->"low" (logged) handler instead of a silent pre-default.
call_engine.py:1331 GETATTR_DEFAULT -> FIX: vol_regime.vol_regime strict with explicit `is not None`.
call_engine.py:1366 GETATTR_DEFAULT -> MARK: symbol used only as a debug-log label.
call_engine.py:1414 GETATTR_DEFAULT -> MARK: MC EAE gate runs only on explicit mc_available=True; mc_eae None handled explicitly.
call_engine.py:1418 GETATTR_DEFAULT -> FIX: vol_regime.risk_multiplier strict (required field); `or 1.0` masked a present value.
call_engine.py:1438 GETATTR_DEFAULT -> MARK: the default False mirrors MicroRead's own declared field default (is_compressing: bool = False); no flag = compression not detected. (A strict read was tried and broke duck-typed micro stubs in 9 call tests with no semantic gain.)
call_engine.py:1522 IF_TRUTHY_ELSE -> FIX: vol regime block rewritten: present payload read strictly; absent -> explicit no-regime branch (label "unknown", directional forced WAIT downstream).
call_engine.py:1523 IF_TRUTHY_ELSE -> FIX: trade_permissive defaulted to True (fail-OPEN) when vol_regime missing; now False in the explicit no-regime branch.
call_engine.py:1524 GETATTR_DEFAULT -> FIX: `or 1.0` turned a real 0.0 conviction_multiplier (documented 0.0-1.5 range) into "no dampening"; now strict. No-regime branch uses explicit identity 1.0 (call is forced WAIT).
call_engine.py:1525 GETATTR_DEFAULT -> FIX: risk_multiplier strict; no-regime branch explicit identity 1.0 (no vol scaling of WAIT-path geometry).
call_engine.py:1526 GETATTR_DEFAULT -> FIX: breakout_bias now read strictly (vol_regime.breakout_bias) at its single consumer, the compression branch (only reachable with a present payload); `or 0.6` had masked a real 0.0.
call_engine.py:1527 GETATTR_DEFAULT -> FIX: _vol_reversal_bias had no consumer (dead fabricated 0.5); removed.
call_engine.py:1535 IF_TRUTHY_ELSE -> FIX+MARK: regime.primary strict when regime present; absent -> declared "unknown" absence label (not a REGIMES member), marked.
call_engine.py:1568 IF_TRUTHY_ELSE -> FIX: fusion dominant direction fabricated "flat" when unavailable; now None (vote 0). Dead `fusion_dominant_direction` attr lookup (not a FusionPayload attribute) removed.
call_engine.py:1614 GETATTR_DEFAULT -> FIX: canonical.provenance strict.
call_engine.py:1629 GETATTR_DEFAULT -> FIX: canonical.provenance strict.
call_engine.py:1770 GETATTR_DEFAULT -> FIX: inp.emission_block_reasons strict (declared SignalInput field).
call_engine.py:1807 GET_WITH_DEFAULT -> FIX: _validate_trade always sets structure_reason; strict. ALSO FIXED adjacent real gate bypass found while tracing: _validate_trade's missing-spot early return left trade_valid=True, so a directional call with no canonical spot passed compute_call's final gate. Now trade_valid=False; test_spot_fail_closed_contract now asserts it.
call_engine.py:1809 GET_WITH_DEFAULT -> FIX: probability_reason strict.
call_engine.py:1811 GET_WITH_DEFAULT -> FIX: risk_reason strict.
call_engine.py:1870 GETATTR_DEFAULT -> FIX: `_micro_sweeps` was a dead variable holding a fabricated [] default; removed.
call_engine.py:1880 GETATTR_DEFAULT -> FIX+MARK: regime.confidence strict when present; absent -> "low" = most conservative sizing tier (applies the low-confidence size cut), marked.
call_engine.py:1890 GETATTR_DEFAULT -> FIX: fusion_confidence fabricated "low" when fusion unavailable; now None (sizer only acts on =="high"); signature widened to Optional.
call_engine.py:1892 IF_TRUTHY_ELSE -> FIX: n_models_active fabricated 0 when fusion unavailable; now None (sizer guards `is not None`); signature widened.
call_engine.py:1999 GETATTR_DEFAULT -> FIX: rules.zone_label strict (required RulesCard field).
call_engine.py:2000 GET_WITH_DEFAULT -> FIX: missing 15m read passed through as None instead of fabricated "" (setup_readiness._safe_lower is the explicit None handler).
call_engine.py:2001 GET_WITH_DEFAULT -> FIX: same for 60m read.
call_engine.py:2014 GET_WITH_DEFAULT -> FIX: compute_call_readiness always returns call_state; strict.
call_engine.py:2015 GET_WITH_DEFAULT -> FIX: forecast_state strict.
call_engine.py:2016 GET_WITH_DEFAULT -> FIX: reasons strict.
call_engine.py:2017 GET_WITH_DEFAULT -> FIX: missing_conditions strict.
call_engine.py:2018 GET_WITH_DEFAULT -> FIX: component_scores strict.
call_engine.py:2046 GETATTR_DEFAULT -> FIX: rules.zone_label strict (put side).
call_engine.py:2047 GET_WITH_DEFAULT -> FIX: 15m read None pass-through (put side).
call_engine.py:2048 GET_WITH_DEFAULT -> FIX: 60m read None pass-through (put side).
call_engine.py:2061 GET_WITH_DEFAULT -> FIX: compute_put_readiness always returns call_state; strict.
call_engine.py:2062 GET_WITH_DEFAULT -> FIX: forecast_state strict.
call_engine.py:2063 GET_WITH_DEFAULT -> FIX: reasons strict.
call_engine.py:2064 GET_WITH_DEFAULT -> FIX: missing_conditions strict.
call_engine.py:2065 GET_WITH_DEFAULT -> FIX: component_scores strict.
call_engine.py:2090 GET_WITH_DEFAULT -> FIX: _validate_trade always sets summary; strict.
compare_clustering_modes.py:159 GET_OR_DEFAULT -> FIX: fabricated 500.0 reference price (and a percent threshold derived from it) reported as clustering_settings.reference_price/effective_threshold when no level existed; now None for both when no real level.
compare_clustering_modes.py:456 GET_WITH_DEFAULT -> FIX: summary dict is always built with value_state; strict (values may be None and print as None).
compare_clustering_modes.py:457 GET_WITH_DEFAULT -> FIX: same, vwap_relation.
compare_clustering_modes.py:458 GET_WITH_DEFAULT -> FIX: same, auction_interpretation.
crash_trace.py:10 GET_WITH_DEFAULT -> MARK: opt-in DIAG env flag; unset = diagnostics off.
db_authority.py:112 GET_WITH_DEFAULT -> MARK: opt-in env flag; unset = non-canonical DB not allowed (fail-closed).
db_health_audit.py:290 GET_WITH_DEFAULT -> FIX: default True let the audit PASS the duplicate-id check if the key went missing; snapshot_inventory always sets it -> strict.
db_health_audit.py:294 GET_OR_DEFAULT -> FIX: flow_range.out_of_range always set by snapshot_inventory -> strict (missing no longer reads as 0 out-of-range).
db_health_audit.py:301 GET_WITH_DEFAULT -> FIX: validate_normalization always sets "ok" -> strict.
db_health_audit.py:340 GET_OR_DEFAULT -> FIX: audit_flow_consistency always returns mismatch_stored_vs_recompute -> strict (missing no longer reads as 0 issues).
db_health_audit.py:341 GET_OR_DEFAULT -> FIX: null_stale strict.
db_health_audit.py:343 GET_OR_DEFAULT -> FIX: rows_scanned strict.
db_safety.py:389 GETATTR_DEFAULT -> FIX: fallback action codes were WRONG (measured: sqlite3.SQLITE_DROP_TABLE=11, DROP_INDEX=10, DROP_VIEW=17, DROP_TRIGGER=16, DETACH=25, UPDATE=23). A fallback would have denied every UPDATE (23) and let DROP VIEW/TRIGGER/DETACH through. Stdlib defines all; now strict constants.
db_safety.py:390 GETATTR_DEFAULT -> FIX: same (DROP_INDEX).
db_safety.py:391 GETATTR_DEFAULT -> FIX: same (DROP_VIEW fallback 12 = DROP_TEMP_INDEX).
db_safety.py:392 GETATTR_DEFAULT -> FIX: same (DROP_TRIGGER fallback 13 = DROP_TEMP_TABLE).
db_safety.py:393 GETATTR_DEFAULT -> FIX: same (DETACH fallback 23 = SQLITE_UPDATE).
distance_option_a_backfill_v1.py:236 IF_NOT_NONE_ELSE -> MARK: else branch is None (absent flag row stays None).
distance_option_a_backfill_v1.py:462 IF_TRUTHY_ELSE -> FIX: majority verdict False when 0 anchors (undefined); now None.
distance_option_a_backfill_v1.py:464 GET_WITH_DEFAULT -> FIX: strict cov["mean_pool_size"] (producer now reports None, not 0.0, for zero anchors).
feature_contract_validation.py:89 GET_WITH_DEFAULT -> FIX: a missing "xgb" registry silently passed the xgb allowed-output policy check (empty list); build_all_layer_registries always returns it -> strict.
feature_contract_validation.py:135 GET_WITH_DEFAULT -> FIX: strict registries["lstm"].
feature_contract_validation.py:151 GET_WITH_DEFAULT -> FIX: strict registries["transformer"].
feature_contract_validation.py:170 GET_WITH_DEFAULT -> FIX: missing xgb registry silently passed the forbidden-family check; strict.
features/fusion_policy_contract.py:93 GETATTR_DEFAULT -> MARK: "?" is the unknown marker inside the fused_stack_status audit text; its only reader (fusion_replay_grade_v1) matches fusion_ok/fusion_unavailable, never parses dir=.
features/fusion_policy_contract.py:94 GETATTR_DEFAULT -> MARK: same for lbl=.
features/inference_snapshot.py:159 GETATTR_DEFAULT -> FIX: empty-string ticker identity fabricated for a serving snapshot; now inp.ticker strict (required SignalInput field).
features/signal_layer_v1.py:588 CAST_OR_DEFAULT -> MARK: dir_sign None only when impulse==0, product is the true 0 signed length.
features/signal_layer_v1.py:604 GET_OR_DEFAULT -> FIX: consecutive_impulse_count always set above; strict.
features/signal_layer_v1.py:668 IF_TRUTHY_ELSE -> FIX: missing last-bar open fabricated body 0.0 -> "part.move_efficiency_last_vs_tr5"=0.0 (a 0%-efficient move); now None. `is not None` also stops a 0.0 open being read as missing.
features/signal_layer_v1.py:809 IF_TRUTHY_ELSE -> MARK: bool->float encoding of an isinstance-checked present bool.
fusion_contract.py:15 GETATTR_DEFAULT -> MARK: fail-closed authority predicate; only explicit available=True is authoritative.
governed_stack_contract.py:170 GET_WITH_DEFAULT -> FIX: _registered_ml_columns always returns "xgb"; `.get(...,set())` would ablate an EMPTY column set as if it were the xgb layer. Strict.
governed_stack_contract.py:172 GET_WITH_DEFAULT -> FIX: same for lstm_5m / lstm_1m.
governed_stack_contract.py:210 GET_WITH_DEFAULT -> MARK: env knob ED_GUEST_ANCHOR_INFERENCE, documented default on.
governed_stack_contract.py:451 GETATTR_DEFAULT -> MARK: fail-closed availability map.
governed_stack_contract.py:452 GETATTR_DEFAULT -> MARK: same.
governed_stack_contract.py:453 GETATTR_DEFAULT -> MARK: same.
governed_stack_contract.py:486 GETATTR_DEFAULT -> MARK: fail-closed; layer enters MC drift average only on explicit available=True.
governed_stack_contract.py:488 GETATTR_DEFAULT -> FIX: `getattr(out,"prob_up",0.33) or 0.33` injected a 0.33 placeholder into the Monte Carlo drift input for a missing prob AND turned a real 0.0 into 0.33. Now float_finite_or_none; unreadable -> layer skipped. Consumer chain: mc_model_direction_inputs -> signals._run_model_stack -> monte_carlo.simulate drift (MC is currently operator-disabled, #262, but the path is live code).
governed_stack_contract.py:489 GETATTR_DEFAULT -> FIX: same for prob_down.
governed_stack_contract.py:518 GETATTR_DEFAULT -> MARK: fail-closed triplet-complete predicate.
governed_stack_contract.py:600 IF_TRUTHY_ELSE -> MARK: reason text on an authorization already denied (returns False).
governed_stack_contract.py:679 GETATTR_DEFAULT -> MARK: evidence-derived scored-layer list; listed only on explicit available=True.
governed_stack_contract.py:681 GETATTR_DEFAULT -> MARK: same (lstm).
governed_stack_contract.py:683 GETATTR_DEFAULT -> MARK: same (transformer).
governed_stack_contract.py:713 GETATTR_DEFAULT -> MARK: same (monte_carlo).
institutional_behavior.py:146 IF_NOT_NONE_ELSE -> MARK: scanner false positive; else branch is None.
levels.py:329 GET_WITH_DEFAULT -> FIX: every row builder (_row/Spot/Regime) sets _level_f (Regime carries its own explicit -1.0 non-level marker); strict index so a malformed row fails instead of being silently binned as "special".
levels.py:330 GET_WITH_DEFAULT -> FIX: same.
levels.py:337 GET_WITH_DEFAULT -> FIX: _side always set; strict.
levels.py:358 GET_WITH_DEFAULT -> FIX: _raw_metric always set; strict.
levels.py:370 GET_WITH_DEFAULT -> FIX: same.
levels.py:375 GET_WITH_DEFAULT -> FIX: same (both occurrences on the line).
levels.py:389 GET_WITH_DEFAULT -> FIX: Metric always set; strict.
liquidity_value_engine.py:82 IF_TRUTHY_ELSE -> MARK: `inside` is a computed bool; 0.0 is the score term for not-inside.
liquidity_value_engine.py:184 GETATTR_DEFAULT -> MARK: attribute alias (timestamp else ts) ending in None; None ts -> _ts None -> bar dropped by dt filters.
liquidity_value_engine.py:260 GET_OR_DEFAULT -> FIX: sort key `_ts or 0` sent a bar whose time lived only in "timestamp" to epoch 0 (front of the merged session); now ordered by the resolved minute key.
liquidity_value_engine.py:639 GET_OR_DEFAULT -> FIX: same epoch-0 stand-in in the ATR bar sort could mis-order TR inputs; now sorted by _bar_dt_et (every filtered bar has one).
liquidity_value_engine.py:1185 IF_TRUTHY_ELSE -> FIX: dead `else 0` (enclosing `if poc and prev_pd_poc` guarantees non-zero); removed.
live_decision_bundle.py:268 GET_WITH_DEFAULT -> MARK: env knob, default = named constant TICK_REFRESH_SPOT_PCT_DEFAULT.
live_decision_bundle.py:269 GET_WITH_DEFAULT -> MARK: env knob, default = TICK_REFRESH_SPOT_ABS_DEFAULT.
live_pipeline_diag.py:37 GETATTR_DEFAULT -> MARK: fail-closed availability read for the ED_LIVE_DIAG dump.
live_pipeline_diag.py:45 GETATTR_DEFAULT -> MARK: same.
live_pipeline_diag.py:46 GETATTR_DEFAULT -> FIX: unknown dominant class coerced to "" in the diag JSON; now None.
live_pipeline_diag.py:47 GETATTR_DEFAULT -> FIX: unknown confidence label coerced to ""; now None.
live_pipeline_diag.py:103 CAST_OR_DEFAULT -> FIX: HorizonForecast.confidence is declared; missing/None was reported as 0.0; now strict attr, None stays None.
live_pipeline_diag.py:104 GETATTR_DEFAULT -> FIX: declared HorizonForecast.tradeable; strict.
live_pipeline_diag.py:105 GETATTR_DEFAULT -> FIX: declared .unavailable; default False reported "available" for a missing flag. Strict.
live_pipeline_diag.py:106 GETATTR_DEFAULT -> FIX: declared .missing; default False reported "not missing". Strict.
live_pipeline_diag.py:118 GETATTR_DEFAULT -> FIX: declared MultiHorizonDecision.final_tradeable; strict.
live_pipeline_diag.py:124 GETATTR_DEFAULT -> FIX: declared supporting_assessments list; strict.
live_pipeline_diag.py:177 IF_NOT_NONE_ELSE -> MARK: fail-closed availability; presence reported separately.
live_pipeline_diag.py:185 GETATTR_DEFAULT -> FIX: "" stand-in for unknown fusion direction -> None.
live_pipeline_diag.py:186 GETATTR_DEFAULT -> FIX: "" stand-in for unknown fusion confidence -> None.
live_pipeline_diag.py:190 GETATTR_DEFAULT -> FIX: canonical.direction strict (declared); absent canonical -> None.
live_pipeline_diag.py:191 GETATTR_DEFAULT -> FIX: canonical.confidence strict.
live_pipeline_diag.py:192 GETATTR_DEFAULT -> FIX: canonical.provenance strict.
live_vs_replay_validation.py:163 IF_TRUTHY_ELSE -> FIX: unknown live side became ""; both-unknown sides normalised to "" and compared EQUAL, so contract_hit counted an unverified contract as a live-vs-replay match. live_side now None and contract_hit requires a known side.
live_vs_replay_validation.py:198 IF_TRUTHY_ELSE -> MARK: scanner false positive; SQL WHERE clause construction.
live_vs_replay_validation.py:215 CAST_OR_DEFAULT -> FIX: COUNT(*) is never NULL; `or 0` removed.
live_vs_replay_validation.py:386 GET_WITH_DEFAULT -> FIX: coverage always reports both validation tables; strict.
live_vs_replay_validation.py:388 GET_WITH_DEFAULT -> FIX: strict; a missing count read as 0 would emit the false "No snapshots rows with both ..." remediation.
live_vs_replay_validation.py:389 GET_WITH_DEFAULT -> FIX: same (nested get).
live_vs_replay_validation.py:390 GET_WITH_DEFAULT -> FIX: same (rows_with_full_bundle).
lstm_data.py:227 GET_WITH_DEFAULT -> MARK: checkpoints predating the key are the pre-versioning v1 encoder; v1 < LEGACY min (2) so all consumers raise "unsupported" (fail-closed).
lstm_data.py:678 GET_WITH_DEFAULT -> FIX: missing et_hour fabricated a 00:00 clock (row then skipped only by accident of _is_rth); now None and explicitly skipped.
lstm_data.py:679 GET_WITH_DEFAULT -> FIX: same for et_minute.
lstm_data.py:680 GET_WITH_DEFAULT -> FIX: missing ts_et -> "" -> "unknown" day bucket; now None -> explicitly skipped (the old "unknown" check removed).
lstm_data.py:1228 GET_WITH_DEFAULT -> FIX: per-sample timestamp metadata "" for missing ts_et; now None.
lstm_model.py:64 CAST_OR_DEFAULT -> MARK: fail-closed guard; unknown count -> 0 -> raises InsufficientLstmSamplesError (after also consulting len(y)).
lstm_model.py:65 CAST_OR_DEFAULT -> MARK: n_days only interpolated into the raised error text.
lstm_model.py:79 GETATTR_DEFAULT -> MARK: fail-closed shape guard; no ndim -> degenerate -> raise.
lstm_model.py:80 GETATTR_DEFAULT -> MARK: "?" only in the raised error message.
lstm_model.py:81 GETATTR_DEFAULT -> MARK: "?" only in the raised error message.
lstm_model.py:424 IF_TRUTHY_ELSE -> FIX: "unknown" ticker identity would have named model/meta/resume artifacts lstm_UNKNOWN_*; now raises ValueError when no ticker identity exists.
lstm_model.py:550 GET_WITH_DEFAULT -> MARK: fail-closed; missing width (-1) never equals a real width -> resume refused.
lstm_model.py:551 GET_WITH_DEFAULT -> MARK: same.
lstm_model.py:552 GET_WITH_DEFAULT -> MARK: same.
lstm_model.py:555 GET_WITH_DEFAULT -> FIX: missing next_epoch defaulted to 1 and resumed (loaded weights, restarted at epoch 1); resume writer always sets it, so missing now refuses the resume.
lstm_model.py:560 GET_WITH_DEFAULT -> FIX: best_loss always written; strict (KeyError -> existing except -> clean train).
lstm_model.py:630 IF_TRUTHY_ELSE -> MARK: scanner false positive; early-stop counter reset/increment.
market_context.py:329 GET_WITH_DEFAULT -> MARK: {} stand-in for absent Schwab "quote" sub-object; fields read via .get -> None, last=None, no price fabricated.
market_context.py:330 GET_WITH_DEFAULT -> MARK: same ("extended").
market_context.py:331 GET_WITH_DEFAULT -> MARK: same ("regular").
market_context.py:599 GETATTR_DEFAULT -> MARK: lookup key only; "" matches no ticker -> item left unpatched (chg_pct None).
market_context.py:610 GETATTR_DEFAULT -> MARK: same for sector rows.
market_context.py:895 GETATTR_DEFAULT -> MARK: display-only alert wording; no role -> generic "Key level".
market_context.py:896 GETATTR_DEFAULT -> MARK: display-only alert name; falls back to the true source list name.
market_context.py:1041 GET_WITH_DEFAULT -> MARK: {} stand-in for absent quote block; _sf -> float_finite_or_none -> None.
market_context.py:1093 GETATTR_DEFAULT -> FIX: declared slot always set by the level snapshot __init__; strict (missing no longer reads as 0 VWAP-input bars).
market_context.py:1149 GETATTR_DEFAULT -> MARK: display-only "—" badge text; numeric push carried separately as None.
market_context.py:1150 GETATTR_DEFAULT -> MARK: display-only neutral badge color.
market_context.py:1152 GETATTR_DEFAULT -> MARK: display-only "—" (qqq).
market_context.py:1153 GETATTR_DEFAULT -> MARK: display-only color (qqq).
market_context.py:1155 GETATTR_DEFAULT -> MARK: display-only "—" (iwm holdings).
market_context.py:1156 GETATTR_DEFAULT -> MARK: display-only color (iwm holdings).
market_context.py:1158 GETATTR_DEFAULT -> MARK: display-only "—" (iwm).
market_context.py:1159 GETATTR_DEFAULT -> MARK: display-only color (iwm).
adaptive_similarity_engine.py:314 GET_OR_DEFAULT -> FIX: equal-score tie-break gave a row with no ts_utc a fabricated epoch-0 time; now explicit None-last _recency_tiebreak_key.
adaptive_similarity_engine.py:315 GET_OR_DEFAULT -> FIX: same for snapshot_id (fabricated id 0).
adaptive_similarity_engine.py:418 GET_WITH_DEFAULT -> FIX: per-call `.get(k, 1.0)` hid the equal-weight default in four places; run_weighted_selection now merges default_equal_weights() with caller overrides once (the single explicit default) and _score_row indexes strictly.
adaptive_similarity_engine.py:422 GET_WITH_DEFAULT -> FIX: same (vwap_side).
adaptive_similarity_engine.py:426 GET_WITH_DEFAULT -> FIX: same (above_bucket).
adaptive_similarity_engine.py:434 GET_WITH_DEFAULT -> FIX: same (below_bucket).
adaptive_similarity_engine.py:472 IF_TRUTHY_ELSE -> FIX: dead `else 0.0` (n > 0 guaranteed by early return); removed.
adaptive_similarity_engine.py:524 IF_TRUTHY_ELSE -> FIX: dead `else 0.0` (union > 0 after the both-empty return); removed.
adaptive_similarity_engine.py:525 IF_TRUTHY_ELSE -> FIX: recall undefined when A empty was reported 0.0 (tools/adaptive_shadow_report then flagged "ordering suboptimal" on recall < 0.25); now None (consumer already handles None).
adaptive_similarity_engine.py:526 IF_TRUTHY_ELSE -> FIX: precision undefined when B empty reported 0.0; now None.
adaptive_similarity_engine.py:606 GET_OR_DEFAULT -> FIX: same epoch-0/id-0 tie-break as 314/315; now _recency_tiebreak_key.
adaptive_similarity_engine.py:668 IF_TRUTHY_ELSE -> FIX: redundant conditional ([1.0]*0 == []); simplified, no default involved.
market_state.py:834 GET_OR_DEFAULT -> FIX: _oe_composite_strike_row always writes a float total_score_after_walls; `or 0` could fabricate one side of wall_delta_on_winner. Strict.
market_state.py:835 GET_OR_DEFAULT -> FIX: same (other side).
market_state.py:853 GET_WITH_DEFAULT -> MARK: filter key; missing Schwab putCall matches neither CALL nor PUT, contract skipped.
market_state.py:922 GET_WITH_DEFAULT -> MARK: same filter semantics (DTE lookup).
market_state.py:967 GET_WITH_DEFAULT -> MARK: same filter semantics (breakeven row lookup).
market_state.py:1136 GETATTR_DEFAULT -> FIX: ExposureRow.bias_signal is a required field; `or "Neutral"` relabelled a missing bias as Neutral (-> derive_zone pin_neutral). Strict.
market_state.py:1138 GETATTR_DEFAULT -> FIX: ExposureRow.pin_strength required; `or "Very Low"` fabricated. Strict.
market_state.py:1147 GETATTR_DEFAULT -> FIX: ExposureRow has NO gex_magnitude attribute, so the except-path fallback was always the constant "negligible"; now logged + None. MarketState.gex_magnitude default changed "negligible" -> None.
market_state.py:1148 GETATTR_DEFAULT -> FIX (LIVE MONEY-PATH FINDING): ExposureRow has NO dex_magnitude attribute, so ms.dex_magnitude was ALWAYS the fabricated constant "negligible". Chain: ms.dex_magnitude -> SignalInput.dex_magnitude (market_state SignalInput build) -> call_engine.compute_call greek_bias(dex_magnitude=...) -> MAG_SCALE["negligible"]=0.0 -> the net-delta term of the "Greeks" tape vote was silently zeroed on every live tick. Now dex_magnitude=None (no producer exists; governance/provenance_roots already records producer=None) and call_engine withholds the net-delta term explicitly when the magnitude is unknown (net_delta passed as None). Live Greeks-vote output is unchanged (delta term still excluded) but the exclusion is explicit instead of a fake label. MarketState.dex_magnitude default "negligible" -> None.
market_state.py:1194 GETATTR_DEFAULT -> MARK: presentation label (mkt_ctx optional); numeric vix carries None.
market_state.py:1195 GETATTR_DEFAULT -> MARK: presentation color.
market_state.py:1196 GETATTR_DEFAULT -> MARK: presentation text.
market_state.py:1199 GETATTR_DEFAULT -> MARK: presentation glyph (provenance_roots PRESENTATION); pcr_val carries None.
market_state.py:1200 GETATTR_DEFAULT -> MARK: presentation color.
market_state.py:1201 GETATTR_DEFAULT -> MARK: presentation label (PRESENTATION).
market_state.py:1520 GETATTR_DEFAULT -> FIX: RulesCard.headline_1m required; strict.
market_state.py:1529 GETATTR_DEFAULT -> FIX: MicroRead.sweeps declared list; strict (missing no longer reports 0 sweeps).
market_state.py:1556 GETATTR_DEFAULT -> FIX: TheCall.trade_type declared and set by compute_call; strict (no invented 'none').
market_state.py:1557 GETATTR_DEFAULT -> FIX: same.
market_state.py:1559 GETATTR_DEFAULT -> FIX: TheCall.invalidation strict.
market_state.py:1560 GETATTR_DEFAULT -> FIX: TheCall.confluence_count strict (no invented 0).
market_state.py:1562 GETATTR_DEFAULT -> FIX: TheCall.confluence_detail strict.
market_state.py:1563 GETATTR_DEFAULT -> FIX: TheCall.mh_promoted_directional strict.
market_state.py:1564 GETATTR_DEFAULT -> FIX: TheCall.time_qualifier strict.
market_state.py:1565 CAST_OR_DEFAULT -> FIX: TheCall.replay_max_hold_bars strict.
market_state.py:1566 GETATTR_DEFAULT -> FIX: TheCall.size_cue strict (no invented 'SKIP').
market_state.py:1575 GETATTR_DEFAULT -> FIX: TheCall.validation_summary strict.
market_state.py:1578 GETATTR_DEFAULT -> FIX: TheCall.execution_mode strict (no invented NO_TRADE).
market_state.py:1579 GETATTR_DEFAULT -> FIX: TheCall.sizing_summary strict.
market_state.py:1581 GETATTR_DEFAULT -> FIX: TheCall.readiness_score strict (no invented 0 score).
market_state.py:1582 GETATTR_DEFAULT -> FIX: TheCall.call_state strict (no invented WAIT).
market_state.py:1583 GETATTR_DEFAULT -> FIX: TheCall.forecast_state strict.
market_state.py:1584 GETATTR_DEFAULT -> FIX: TheCall.readiness_reasons strict.
market_state.py:1585 GETATTR_DEFAULT -> FIX: TheCall.missing_conditions strict.
market_state.py:1586 GETATTR_DEFAULT -> FIX: TheCall.readiness_component_scores strict.
market_state.py:1589 GETATTR_DEFAULT -> FIX: TheCall.put_readiness_score strict.
market_state.py:1590 GETATTR_DEFAULT -> FIX: TheCall.put_state strict.
market_state.py:1591 GETATTR_DEFAULT -> FIX: TheCall.put_forecast_state strict.
market_state.py:1592 GETATTR_DEFAULT -> FIX: TheCall.put_readiness_reasons strict.
market_state.py:1593 GETATTR_DEFAULT -> FIX: TheCall.put_missing_conditions strict.
market_state.py:1594 GETATTR_DEFAULT -> FIX: TheCall.put_readiness_component_scores strict.
market_state.py:1606 GETATTR_DEFAULT -> FIX: MultiHorizonDecision.final_bias declared; `or "WAIT"` published an invented decision. Strict.
market_state.py:1609 GETATTR_DEFAULT -> FIX: final_quality strict (no invented "D").
market_state.py:1610 GETATTR_DEFAULT -> FIX: final_tradeable strict.
market_state.py:1611 GETATTR_DEFAULT -> FIX: primary_horizon strict (no invented "1c").
market_state.py:1612 GETATTR_DEFAULT -> FIX: trade_mode strict (no invented "intraday").
market_state.py:1613 GETATTR_DEFAULT -> FIX: supporting_horizon_summary strict.
market_state.py:1617 GETATTR_DEFAULT -> FIX: contradiction_state strict (no invented "none").
market_state.py:1618 GETATTR_DEFAULT -> FIX: HorizonAlignmentReport.conflict_level strict (no invented "high"); alignment_report / final_trade_plan also read strictly.
market_state.py:1619 GETATTR_DEFAULT -> FIX: entry_state strict (no invented "no_setup").
market_state.py:1620 GETATTR_DEFAULT -> FIX: risk_note strict.
market_state.py:1621 GETATTR_DEFAULT -> FIX: wait_reason strict.
market_state.py:1622 GETATTR_DEFAULT -> FIX: decision_provenance strict.
market_state.py:1623 GETATTR_DEFAULT -> FIX: SignalOutput.guest_anchor_active declared; strict.
market_state.py:1628 GETATTR_DEFAULT -> FIX: FinalTradePlan.entry_display_text strict.
market_state.py:1629 GETATTR_DEFAULT -> FIX: stop_display_text strict.
market_state.py:1630 GETATTR_DEFAULT -> FIX: targets_display strict.
market_state.py:1631 GETATTR_DEFAULT -> FIX: hold_style strict.
market_state.py:1632 GETATTR_DEFAULT -> FIX: size_modifier_display strict (old "0.00x" claimed a zero size modifier).
market_state.py:1634 GETATTR_DEFAULT -> FIX: supporting_assessments strict.
market_state.py:1635 GETATTR_DEFAULT -> FIX: SupportingHorizonAssessment.missing strict (default False could publish an absent row as ok).
market_state.py:1636 GETATTR_DEFAULT -> FIX: horizon strict.
market_state.py:1644 GETATTR_DEFAULT -> FIX: role strict.
market_state.py:1645 GETATTR_DEFAULT -> FIX: call strict.
market_state.py:1648 GETATTR_DEFAULT -> FIX: effect strict.
market_state.py:1649 GETATTR_DEFAULT -> FIX: row_state strict (no invented "weak").
market_state.py:1651 GETATTR_DEFAULT -> FIX: reason_code strict.
market_state.py:1656 GET_WITH_DEFAULT -> FIX+MARK: x["horizon"] strict; `_rank.get(h, len(_rank))` kept and marked as display ordering (unranked horizons sort last).
market_state.py:1735 GETATTR_DEFAULT -> FIX: PredictiveCard.model_version strict (producer default lives on the dataclass).
market_state.py:1763 GETATTR_DEFAULT -> FIX: reversal_severity strict.
market_state.py:1767 GET_WITH_DEFAULT -> MARK: {} for an absent model layer; every read .get -> None (available None, probs None).
market_state.py:1768 GET_WITH_DEFAULT -> MARK: same (lstm).
market_state.py:1769 GET_WITH_DEFAULT -> MARK: same (transformer).
market_state.py:1805 GETATTR_DEFAULT -> FIX: RegimePayload.primary strict (no invented "unknown").
market_state.py:1806 GETATTR_DEFAULT -> FIX: secondary_tags strict.
market_state.py:1807 GETATTR_DEFAULT -> FIX: confidence strict (no invented "low").
market_state.py:1808 GETATTR_DEFAULT -> FIX: confidence_score strict (no invented 0.0).
market_state.py:1809 GETATTR_DEFAULT -> FIX: summary strict.
market_state.py:1810 GETATTR_DEFAULT -> FIX: support_factors strict.
market_state.py:1811 GETATTR_DEFAULT -> FIX: contradiction_factors strict.
market_state.py:1820 GETATTR_DEFAULT -> FIX: FusionPayload.dominant_outcome strict (no invented "unknown").
market_state.py:1822 GETATTR_DEFAULT -> FIX: fusion_confidence strict (no invented "low").
market_state.py:1824 GETATTR_DEFAULT -> FIX: fusion_summary strict.
market_state.py:1832 GETATTR_DEFAULT -> FIX: model_agreement_label strict (no invented "low").
market_state.py:1833 GETATTR_DEFAULT -> FIX: n_sources_active strict.
market_state.py:1837 GETATTR_DEFAULT -> FIX: dominant_direction strict (no invented "flat").
market_state.py:1838 GETATTR_DEFAULT -> FIX: evidence_summary strict.
market_state.py:1839 GETATTR_DEFAULT -> FIX: contradiction_summary strict.
market_state.py:1842 GETATTR_DEFAULT -> FIX: mc_available strict.
market_state.py:1871 GETATTR_DEFAULT -> FIX: VolRegimePayload.vol_regime strict (no invented "unknown").
market_state.py:1872 GETATTR_DEFAULT -> FIX: summary strict.
market_state.py:1893 GETATTR_DEFAULT -> FIX: StackStage.stage_id strict.
market_state.py:1894 GETATTR_DEFAULT -> FIX: StackStage.status strict (no invented "inactive").
market_state.py:1898 GETATTR_DEFAULT -> FIX: StackStage.note strict.

## Adjacent defects fixed while tracing (not scanner hits)
- call_engine._validate_trade: missing-spot early return left trade_valid=True (gate bypass) -> now False; test_spot_fail_closed_contract asserts it.
- call_engine greek_bias call: withholds net-delta term when dex_magnitude is unknown (pairs with market_state.py:1148).
- market_state.MarketState: gex_magnitude/dex_magnitude defaults 'negligible' -> None.
- compare_clustering_modes._zone_diagnostics: empty-zone width stats 0.0 -> None; _final_assessment no longer ranks a zone-less mode with an inf stand-in and reports it as 'Zones too wide'.
- adaptive_shadow_v2_calibration line ~263: fabricated base_j=[0.0] removed (see :269).
