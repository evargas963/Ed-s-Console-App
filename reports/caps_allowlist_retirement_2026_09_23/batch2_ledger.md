# CAPS batch 2 ledger (one line per original hit)

math_exposure_core.py:307 GET_WITH_DEFAULT -> FIX: bid/ask size buckets were pre-initialised 0.0 and summed with a 0.0 default, so a strike whose legs omitted bidSize/askSize reported a measured 0 resting size; buckets now init None (same contract as call_volume) and accumulate prev-is-None; readers already go through bucket_metric (None-aware). Test test_multiplier_no_default corrected (it asserted the fabricated 0.0).
math_exposure_core.py:309 GET_WITH_DEFAULT -> FIX: bid/ask size buckets were pre-initialised 0.0 and summed with a 0.0 default, so a strike whose legs omitted bidSize/askSize reported a measured 0 resting size; buckets now init None (same contract as call_volume) and accumulate prev-is-None; readers already go through bucket_metric (None-aware). Test test_multiplier_no_default corrected (it asserted the fabricated 0.0).
math_exposure_core.py:315 GET_WITH_DEFAULT -> FIX: bid/ask size buckets were pre-initialised 0.0 and summed with a 0.0 default, so a strike whose legs omitted bidSize/askSize reported a measured 0 resting size; buckets now init None (same contract as call_volume) and accumulate prev-is-None; readers already go through bucket_metric (None-aware). Test test_multiplier_no_default corrected (it asserted the fabricated 0.0).
math_exposure_core.py:317 GET_WITH_DEFAULT -> FIX: bid/ask size buckets were pre-initialised 0.0 and summed with a 0.0 default, so a strike whose legs omitted bidSize/askSize reported a measured 0 resting size; buckets now init None (same contract as call_volume) and accumulate prev-is-None; readers already go through bucket_metric (None-aware). Test test_multiplier_no_default corrected (it asserted the fabricated 0.0).
math_exposure_core.py:413 GET_WITH_DEFAULT -> FIX: dollarized net fields 'remained 0.0 if spot is None' (fabricated $0 book); per-side keys are always initialised so they are now indexed directly, and with spot=None all 9 dollar fields are set None (_DOLLAR_BUCKET_KEYS). No live caller passes spot=None.
math_exposure_core.py:414 GET_WITH_DEFAULT -> FIX: dollarized net fields 'remained 0.0 if spot is None' (fabricated $0 book); per-side keys are always initialised so they are now indexed directly, and with spot=None all 9 dollar fields are set None (_DOLLAR_BUCKET_KEYS). No live caller passes spot=None.
math_exposure_core.py:415 GET_WITH_DEFAULT -> FIX: dollarized net fields 'remained 0.0 if spot is None' (fabricated $0 book); per-side keys are always initialised so they are now indexed directly, and with spot=None all 9 dollar fields are set None (_DOLLAR_BUCKET_KEYS). No live caller passes spot=None.
math_exposure_core.py:722 CAST_OR_DEFAULT -> FIX: compute_delta_oi_walls: `pc or 0.0` turned a strike PRESENT yesterday with UNKNOWN (None) OI into a 0 baseline -> phantom OI build; absent strike keeps the documented true-0 baseline, present-but-None side is now skipped.
math_exposure_core.py:724 CAST_OR_DEFAULT -> FIX: compute_delta_oi_walls: `pc or 0.0` turned a strike PRESENT yesterday with UNKNOWN (None) OI into a 0 baseline -> phantom OI build; absent strike keeps the documented true-0 baseline, present-but-None side is now skipped.
math_levels.py:525 IF_NOT_NONE_ELSE -> MARK: put/call OI ratio is None (not computable) when either OI leg is missing or call OI is 0 -- the else branch is the honest absence, no value is fabricated
math_probabilities.py:184 GET_WITH_DEFAULT -> MARK: a contract without putCall becomes "" which can never equal CALL/PUT, so it is EXCLUDED from the candidates, never assigned a side
math_probabilities.py:202 IF_NOT_NONE_ELSE -> MARK: delta/gamma ratio is None when gamma is missing/zero or delta is missing -- honest absence, no fabricated ratio
math_probabilities.py:203 IF_NOT_NONE_ELSE -> MARK: volume/OI ratio is None when OI is missing/zero or volume is missing -- honest absence, no fabricated ratio
math_probabilities.py:209 GET_WITH_DEFAULT -> MARK: a contract without putCall becomes "" != side_up and is SKIPPED from the max-gamma scan, never counted on either side
math_probabilities.py:406 GET_WITH_DEFAULT -> FIX: determine_confidence: out-of-contract tier silently fell back to tier_7 'low' (and a non-int tier could never match); now CONFIDENCE_RULES[tier]['base'] with ValueError on an unknown tier; dead legacy tuple-rule branch removed.
math_probabilities.py:409 GET_WITH_DEFAULT -> FIX: determine_confidence: out-of-contract tier silently fell back to tier_7 'low' (and a non-int tier could never match); now CONFIDENCE_RULES[tier]['base'] with ValueError on an unknown tier; dead legacy tuple-rule branch removed.
math_volatility.py:122 GET_WITH_DEFAULT -> FIX: charm_intraday_context: missing net_charm_daily/charm_direction became 0.0/'neutral' ('Charm balanced' card); now any absent input -> available False (producer compute_net_charm publishes None with contracts_used 0). Function currently has no callers.
math_volatility.py:123 GET_WITH_DEFAULT -> FIX: charm_intraday_context: missing net_charm_daily/charm_direction became 0.0/'neutral' ('Charm balanced' card); now any absent input -> available False (producer compute_net_charm publishes None with contracts_used 0). Function currently has no callers.
math_volatility.py:125 GET_WITH_DEFAULT -> FIX: charm_intraday_context: missing net_charm_daily/charm_direction became 0.0/'neutral' ('Charm balanced' card); now any absent input -> available False (producer compute_net_charm publishes None with contracts_used 0). Function currently has no callers.
math_volatility.py:145 IF_TRUTHY_ELSE -> MARK: display prose -- the urgency note prefix is omitted ("") when no et_hour was given; net is a guaranteed real value here (absent net returns unavailable above)
math_volatility.py:904 IF_TRUTHY_ELSE -> MARK: numerical positivity floor, not a vol estimate -- without RV the blend is the measured GARCH/IV sigma and 1e-5/bar only binds if that collapses to ~0, keeping the per-bar sigma strictly positive for the simulator
mc_fusion_adjustment.py:287 GETATTR_DEFAULT -> MARK: an MC output without an `available` flag is treated as NOT available, so the fusion triplet is returned untouched (fail-closed, no MC adjustment applied)
mc_fusion_adjustment.py:400 IF_NOT_NONE_ELSE -> MARK: None propagates an invalid rounded triplet; _rt_keeps_authority is then False and the adjustment is rejected (fail-closed)
micro_structure.py:827 GETATTR_DEFAULT -> FIX: collapse_sweep_alerts: getattr defaults filed a sweep without a recognised type under 'swing low' and without `held` under 'continuation'; SweepEvent.type/.held are required fields -> direct access + explicit type map (KeyError on unknown type).
micro_structure.py:828 GETATTR_DEFAULT -> FIX: collapse_sweep_alerts: getattr defaults filed a sweep without a recognised type under 'swing low' and without `held` under 'continuation'; SweepEvent.type/.held are required fields -> direct access + explicit type map (KeyError on unknown type).
micro_structure.py:1266 IF_TRUTHY_ELSE -> FIX: 'confirming pattern' fallback text claimed a pattern that did not exist; REVERSAL_UP/DN are only classified when the same candle_pats list holds a confirming pattern, so confirm_names[0] is used directly.
micro_structure.py:1276 IF_TRUTHY_ELSE -> FIX: 'confirming pattern' fallback text claimed a pattern that did not exist; REVERSAL_UP/DN are only classified when the same candle_pats list holds a confirming pattern, so confirm_names[0] is used directly.
ml_data_common.py:837 IF_TRUTHY_ELSE -> MARK: no 5m rows fetched -> empty frame, and the `if m5.empty: return df` below returns the input unmerged (m5_* stay absent), nothing fabricated
ml_data_common.py:911 IF_TRUTHY_ELSE -> MARK: with no M5 source columns configured no row can carry an m5 proxy, so False (clear the source-timeframe stamp) is the true value, not a default
ml_predict.py:183 GET_WITH_DEFAULT -> FIX: check_active_bundle_complete always returns issues/artifacts and each artifact carries issues; `.get(..., [])` would report a malformed verdict as 'nothing missing' -> indexed directly.
ml_predict.py:185 GET_WITH_DEFAULT -> FIX: check_active_bundle_complete always returns issues/artifacts and each artifact carries issues; `.get(..., [])` would report a malformed verdict as 'nothing missing' -> indexed directly.
ml_predict.py:376 GET_WITH_DEFAULT -> FIX: _probs_dict_to_arr spliced a 1/3 into a partial probability dict; a present dict now requires up/down/flat (cascade contract: validated outputs only).
ml_predict.py:386 GET_WITH_DEFAULT -> MARK: _load_transformer accepts a mask-less checkpoint ONLY after verifying n_features == the full encoder width, so all-True IS that model's real column set; norm_mean/std widths are cross-checked against it just below and raise on mismatch
ml_predict.py:424 GET_WITH_DEFAULT -> MARK: same load-verified mask-less transformer contract as _transformer_normalize_and_select (n_features == full encoder width checked at load), so all-True is the model's real column set for the ablation channel map
ml_predict.py:765 GET_WITH_DEFAULT -> MARK: operator env switch whose documented default "1" is the STRICT (active-bundle-only) posture; only an explicit 0/false/no relaxes it
ml_predict.py:1026 GET_WITH_DEFAULT -> FIX: XGB (and movement-head) meta category_maps/vol_medians `{}` default made every categorical feature and volume_ratio NaN while still predicting; ml_train writes both since the file's first commit -> required. Test fixtures in test_ml_predict_horizon_registry / test_model_contract_enforcement corrected to carry the writer's keys.
ml_predict.py:1027 GET_WITH_DEFAULT -> FIX: XGB (and movement-head) meta category_maps/vol_medians `{}` default made every categorical feature and volume_ratio NaN while still predicting; ml_train writes both since the file's first commit -> required. Test fixtures in test_ml_predict_horizon_registry / test_model_contract_enforcement corrected to carry the writer's keys.
ml_predict.py:1206 GET_WITH_DEFAULT -> FIX: XGB (and movement-head) meta category_maps/vol_medians `{}` default made every categorical feature and volume_ratio NaN while still predicting; ml_train writes both since the file's first commit -> required. Test fixtures in test_ml_predict_horizon_registry / test_model_contract_enforcement corrected to carry the writer's keys.
ml_predict.py:1207 GET_WITH_DEFAULT -> FIX: XGB (and movement-head) meta category_maps/vol_medians `{}` default made every categorical feature and volume_ratio NaN while still predicting; ml_train writes both since the file's first commit -> required. Test fixtures in test_ml_predict_horizon_registry / test_model_contract_enforcement corrected to carry the writer's keys.
ml_predict.py:1461 GET_WITH_DEFAULT -> FIX: LSTM checkpoint mask_conf/mask_5m/mask_1m all-True defaults made the width checks pass trivially, and a missing norm_stats silently skipped normalization; lstm_model always writes them -> required (outer except returns no prediction). test_cf_vwap_real_seam_fail_closed_v1 fixture corrected (added norm_stats).
ml_predict.py:1523 IF_NOT_NONE_ELSE -> MARK: with no caller snapshot the overlay is the newest REAL row of the same causal window the sequence ends on (not an invented value); it only feeds the non-parallel cascade stage-1 XGB call, and parallel runtime raises before that
ml_predict.py:1525 GET_WITH_DEFAULT -> FIX: LSTM checkpoint mask_conf/mask_5m/mask_1m all-True defaults made the width checks pass trivially, and a missing norm_stats silently skipped normalization; lstm_model always writes them -> required (outer except returns no prediction). test_cf_vwap_real_seam_fail_closed_v1 fixture corrected (added norm_stats).
ml_predict.py:1561 GET_WITH_DEFAULT -> FIX: LSTM checkpoint mask_conf/mask_5m/mask_1m all-True defaults made the width checks pass trivially, and a missing norm_stats silently skipped normalization; lstm_model always writes them -> required (outer except returns no prediction). test_cf_vwap_real_seam_fail_closed_v1 fixture corrected (added norm_stats).
ml_predict.py:1562 GET_WITH_DEFAULT -> FIX: LSTM checkpoint mask_conf/mask_5m/mask_1m all-True defaults made the width checks pass trivially, and a missing norm_stats silently skipped normalization; lstm_model always writes them -> required (outer except returns no prediction). test_cf_vwap_real_seam_fail_closed_v1 fixture corrected (added norm_stats).
ml_predict.py:1589 GET_WITH_DEFAULT -> FIX: LSTM checkpoint mask_conf/mask_5m/mask_1m all-True defaults made the width checks pass trivially, and a missing norm_stats silently skipped normalization; lstm_model always writes them -> required (outer except returns no prediction). test_cf_vwap_real_seam_fail_closed_v1 fixture corrected (added norm_stats).
ml_predict.py:1722 GET_WITH_DEFAULT -> FIX: _load_transformer: n_features defaulted to 0, which the `if n_enc and ...` guards read as 'skip the width check' (gate passed on missing data); now required and both guards always compare.
ml_predict.py:1751 GET_WITH_DEFAULT -> MARK: 20 is transformer_train.SEQUENCE_LENGTH, the fixed window every transformer checkpoint was trained at; the writer stores it as seq_len, a checkpoint predating that field was trained at the same 20
ml_predict.py:1808 GET_WITH_DEFAULT -> MARK: 20 is transformer_train.SEQUENCE_LENGTH (unchanged across the file's whole history), the window every transformer checkpoint was trained at and the value the writer stores as seq_len
ml_predict.py:1858 IF_NOT_NONE_ELSE -> MARK: with no caller snapshot the overlay is the newest REAL row of the same causal window the sequence ends on; it only feeds the non-parallel cascade upstream XGB/LSTM calls, and parallel runtime raises before that
ml_predict.py:1874 GET_WITH_DEFAULT -> MARK: mask-less transformer checkpoint was admitted by _load_transformer only with n_features == full encoder width, so all-True is its true column set; the width check right below still rejects a mismatch
ml_predict.py:2615 GET_WITH_DEFAULT -> MARK: "" is only the no-ticker sentinel and is rejected on the next line (CascadeChallengerError), never used as a ticker
ml_predict.py:2743 GET_WITH_DEFAULT -> MARK: "" is only the no-ticker sentinel; the next line returns all three models as None (unavailable), never a prediction
ml_predict.py:2774 GET_WITH_DEFAULT -> MARK: "" is only the no-ticker sentinel; the next line returns all three models as None (unavailable), never a prediction
ml_predict.py:2807 GET_WITH_DEFAULT -> MARK: "" is only the no-ticker sentinel; the next line reports every model available=False, never a fabricated output
ml_scheduler.py:199 GET_WITH_DEFAULT -> MARK: operator env opt-out; unset ("") means the pre-train DB health gate RUNS -- only an explicit 1/true/yes skips it
ml_scheduler.py:523 GET_OR_DEFAULT -> MARK: fail-closed skip gate -- an absent/None row_count is treated as "no labeled rows" so the ticker is NOT trained; no count is persisted from this
ml_scheduler.py:640 GET_WITH_DEFAULT -> MARK: run counter -- a manifest that never recorded a skip streak has had zero consecutive skips; 0 only delays the forced-retrain cap, it asserts no market value
ml_scheduler.py:641 GET_WITH_DEFAULT -> MARK: run counter, same zero-skips-recorded semantics as the parallel streak
ml_scheduler.py:652 GET_WITH_DEFAULT -> FIX: --promote-from-manifests: eval_accuracy/balanced_accuracy/n_rows defaulted to 0.0/0 and then drove the parallel-vs-cascade promotion comparison and were re-persisted as measured; now requires _manifest_eval_complete on both manifests (else ticker skipped with warning) and indexes directly.
ml_scheduler.py:653 GET_WITH_DEFAULT -> FIX: --promote-from-manifests: eval_accuracy/balanced_accuracy/n_rows defaulted to 0.0/0 and then drove the parallel-vs-cascade promotion comparison and were re-persisted as measured; now requires _manifest_eval_complete on both manifests (else ticker skipped with warning) and indexes directly.
ml_scheduler.py:654 GET_WITH_DEFAULT -> FIX: --promote-from-manifests: eval_accuracy/balanced_accuracy/n_rows defaulted to 0.0/0 and then drove the parallel-vs-cascade promotion comparison and were re-persisted as measured; now requires _manifest_eval_complete on both manifests (else ticker skipped with warning) and indexes directly.
ml_scheduler.py:662 GET_WITH_DEFAULT -> FIX: --promote-from-manifests: eval_accuracy/balanced_accuracy/n_rows defaulted to 0.0/0 and then drove the parallel-vs-cascade promotion comparison and were re-persisted as measured; now requires _manifest_eval_complete on both manifests (else ticker skipped with warning) and indexes directly.
ml_scheduler.py:663 GET_WITH_DEFAULT -> FIX: --promote-from-manifests: eval_accuracy/balanced_accuracy/n_rows defaulted to 0.0/0 and then drove the parallel-vs-cascade promotion comparison and were re-persisted as measured; now requires _manifest_eval_complete on both manifests (else ticker skipped with warning) and indexes directly.
ml_scheduler.py:664 GET_WITH_DEFAULT -> FIX: --promote-from-manifests: eval_accuracy/balanced_accuracy/n_rows defaulted to 0.0/0 and then drove the parallel-vs-cascade promotion comparison and were re-persisted as measured; now requires _manifest_eval_complete on both manifests (else ticker skipped with warning) and indexes directly.
ml_scheduler.py:676 GET_WITH_DEFAULT -> FIX: promote path provenance flags were asserted False when the prior manifest did not record them; now carried verbatim (None = unknown).
ml_scheduler.py:677 GET_WITH_DEFAULT -> FIX: promote path provenance flags were asserted False when the prior manifest did not record them; now carried verbatim (None = unknown).
ml_scheduler.py:678 GET_WITH_DEFAULT -> FIX: promote path trained_at defaulted to THIS run's timestamp (laundering unknown training time into a fresh one that the next max-age check trusts); trained_at now required (ticker skipped with warning if absent).
ml_scheduler.py:680 GET_WITH_DEFAULT -> FIX: promote path provenance flags were asserted False when the prior manifest did not record them; now carried verbatim (None = unknown).
ml_scheduler.py:681 GET_WITH_DEFAULT -> FIX: promote path provenance flags were asserted False when the prior manifest did not record them; now carried verbatim (None = unknown).
ml_scheduler.py:682 GET_WITH_DEFAULT -> FIX: promote path provenance flags were asserted False when the prior manifest did not record them; now carried verbatim (None = unknown).
ml_scheduler.py:683 GET_WITH_DEFAULT -> FIX: promote path trained_at defaulted to THIS run's timestamp (laundering unknown training time into a fresh one that the next max-age check trusts); trained_at now required (ticker skipped with warning if absent).
ml_scheduler.py:694 GET_WITH_DEFAULT -> MARK: run counter -- a manifest that never recorded a skip streak has had zero consecutive skips; 0 only delays the forced-retrain cap, it asserts no market value
ml_scheduler.py:695 GET_WITH_DEFAULT -> MARK: run counter, same zero-skips-recorded semantics as the parallel streak
ml_scheduler.py:766 GET_WITH_DEFAULT -> FIX: cache-hit path reused manifest evaluation with 0.0/0 defaults; a cache hit now additionally requires _manifest_eval_complete (else it is a cache MISS: retrain_reason manifest_evaluation_incomplete) and indexes directly.
ml_scheduler.py:767 GET_WITH_DEFAULT -> FIX: cache-hit path reused manifest evaluation with 0.0/0 defaults; a cache hit now additionally requires _manifest_eval_complete (else it is a cache MISS: retrain_reason manifest_evaluation_incomplete) and indexes directly.
ml_scheduler.py:768 GET_WITH_DEFAULT -> FIX: cache-hit path reused manifest evaluation with 0.0/0 defaults; a cache hit now additionally requires _manifest_eval_complete (else it is a cache MISS: retrain_reason manifest_evaluation_incomplete) and indexes directly.
ml_scheduler.py:778 GET_WITH_DEFAULT -> FIX: cache-hit provenance flags carried verbatim from the manifest (None if never recorded) instead of asserted False.
ml_scheduler.py:779 GET_WITH_DEFAULT -> FIX: cache-hit provenance flags carried verbatim from the manifest (None if never recorded) instead of asserted False.
ml_scheduler.py:780 GET_WITH_DEFAULT -> FIX: cache-hit trained_at: full_skip_eligible already refuses a skip without a parseable trained_at, so it is indexed directly (the run_ts default was unreachable-but-fabricating).
ml_scheduler.py:798 GET_WITH_DEFAULT -> FIX: ED_ML_SCHEDULER_SKIP_PARALLEL_TRAIN path (artifacts not trained this run): provenance without a prior manifest is unknown -> None; trained_at None (was run_ts) so the next run refuses a skip instead of trusting an invented age.
ml_scheduler.py:799 GET_WITH_DEFAULT -> FIX: ED_ML_SCHEDULER_SKIP_PARALLEL_TRAIN path (artifacts not trained this run): provenance without a prior manifest is unknown -> None; trained_at None (was run_ts) so the next run refuses a skip instead of trusting an invented age.
ml_scheduler.py:800 GET_WITH_DEFAULT -> FIX: ED_ML_SCHEDULER_SKIP_PARALLEL_TRAIN path (artifacts not trained this run): provenance without a prior manifest is unknown -> None; trained_at None (was run_ts) so the next run refuses a skip instead of trusting an invented age.
ml_scheduler.py:825 GET_WITH_DEFAULT -> FIX: train_*_candidate return always carries used_feature_cache/used_cascade_tensor_cache (train_compare already indexes them) -> indexed directly.
ml_scheduler.py:826 GET_WITH_DEFAULT -> FIX: train_*_candidate return always carries used_feature_cache/used_cascade_tensor_cache (train_compare already indexes them) -> indexed directly.
ml_scheduler.py:833 GET_WITH_DEFAULT -> FIX: cache-hit path reused manifest evaluation with 0.0/0 defaults; a cache hit now additionally requires _manifest_eval_complete (else it is a cache MISS: retrain_reason manifest_evaluation_incomplete) and indexes directly.
ml_scheduler.py:834 GET_WITH_DEFAULT -> FIX: cache-hit path reused manifest evaluation with 0.0/0 defaults; a cache hit now additionally requires _manifest_eval_complete (else it is a cache MISS: retrain_reason manifest_evaluation_incomplete) and indexes directly.
ml_scheduler.py:835 GET_WITH_DEFAULT -> FIX: cache-hit path reused manifest evaluation with 0.0/0 defaults; a cache hit now additionally requires _manifest_eval_complete (else it is a cache MISS: retrain_reason manifest_evaluation_incomplete) and indexes directly.
ml_scheduler.py:845 GET_WITH_DEFAULT -> FIX: cache-hit provenance flags carried verbatim from the manifest (None if never recorded) instead of asserted False.
ml_scheduler.py:846 GET_WITH_DEFAULT -> FIX: cache-hit provenance flags carried verbatim from the manifest (None if never recorded) instead of asserted False.
ml_scheduler.py:847 GET_WITH_DEFAULT -> FIX: cache-hit provenance flags carried verbatim from the manifest (None if never recorded) instead of asserted False.
ml_scheduler.py:848 GET_WITH_DEFAULT -> FIX: cache-hit trained_at: full_skip_eligible already refuses a skip without a parseable trained_at, so it is indexed directly (the run_ts default was unreachable-but-fabricating).
ml_scheduler.py:874 GET_WITH_DEFAULT -> FIX: train_*_candidate return always carries used_feature_cache/used_cascade_tensor_cache (train_compare already indexes them) -> indexed directly.
ml_scheduler.py:875 GET_WITH_DEFAULT -> FIX: train_*_candidate return always carries used_feature_cache/used_cascade_tensor_cache (train_compare already indexes them) -> indexed directly.
ml_scheduler.py:876 GET_WITH_DEFAULT -> FIX: two train_cascade_candidate early returns omit used_parallel_cascade_bridge even when the bridge WAS used; absent key now None (unknown) instead of False.
ml_scheduler.py:905 GET_WITH_DEFAULT -> FIX: partial-bundle governed_slice: check_active_bundle_complete always returns issues -> indexed ([] default would have published 'no issues' for a failed bundle).
ml_scheduler.py:906 GET_WITH_DEFAULT -> FIX: partial-bundle governed_slice: check_active_bundle_complete always returns issues -> indexed ([] default would have published 'no issues' for a failed bundle).
ml_scheduler.py:1155 GET_WITH_DEFAULT -> MARK: "none" is the repo-wide "no architecture active" sentinel (same as promotion_execution / manual_control); a ticker absent from arch_state has never been promoted
ml_scheduler.py:1276 IF_TRUTHY_ELSE -> MARK: counter reset -- a run that trained breaks the consecutive-skip streak, so 0 is the true new count
ml_scheduler.py:1277 IF_TRUTHY_ELSE -> MARK: counter reset -- a run that trained breaks the consecutive-skip streak, so 0 is the true new count
ml_scheduler.py:1515 GET_WITH_DEFAULT -> MARK: operator env config with the documented default horizon slug (DEFAULT_ML_HORIZON_SLUG)
ml_scheduler.py:1532 GET_WITH_DEFAULT -> FIX: run_once always returns exit_code; the 0 default reported a malformed summary as a successful horizon / process exit 0 -> indexed.
ml_scheduler.py:1623 GET_WITH_DEFAULT -> MARK: argparse default from operator env, falling back to the documented DEFAULT_ML_HORIZON_SLUG
ml_scheduler.py:1652 IF_TRUTHY_ELSE -> MARK: CLI flag logic -- --run-now means "do not wait for the 16:15 slot", otherwise honour --wait
ml_scheduler.py:1660 GET_WITH_DEFAULT -> FIX: run_once always returns exit_code; the 0 default reported a malformed summary as a successful horizon / process exit 0 -> indexed.
ml_scheduler.py:1664 IF_TRUTHY_ELSE -> MARK: CLI flag logic -- --run-now means "do not wait for the 16:15 slot", otherwise honour --wait
ml_scheduler.py:1672 GET_WITH_DEFAULT -> FIX: run_once always returns exit_code; the 0 default reported a malformed summary as a successful horizon / process exit 0 -> indexed.
ml_train.py:848 GET_WITH_DEFAULT -> MARK: tkr is used ONLY to build the vol_median_{tkr}_{h}_{m} lookup key; "?" matches no fitted median, so volume_ratio stays absent (NaN) -- no value is fabricated
ml_train.py:890 GET_WITH_DEFAULT -> MARK: NaN is this feature row's missing-value marker (XGBoost missing, same as training's to_numeric coerce); absent/NaN qqq_vs_spy only triggers the numeric-twin lookup, which is itself NaN when absent
ml_train.py:940 GET_WITH_DEFAULT -> MARK: NaN is the missing-value marker of this XGB feature row (training's to_numeric coerce yields the same NaN); fk_body_range_ratio propagates NaN, nothing is invented
ml_train.py:942 GET_WITH_DEFAULT -> MARK: NaN = missing marker of this XGB feature row; fk_dgex/fk_sign_positive propagate NaN (documented "missing is never 'not positive'")
ml_train.py:945 GET_WITH_DEFAULT -> MARK: NaN = missing marker; fk_sign_positive / fk_agreement_positive return NaN for an absent leg
ml_train.py:946 GET_WITH_DEFAULT -> MARK: NaN = missing marker; fk_agreement_positive returns NaN when either leg is absent
ml_train.py:951 GET_WITH_DEFAULT -> MARK: NaN = missing marker; fk_alignment multiplies (NaN propagates) and fk_cross_change_stats needs >= 2 finite legs
ml_train.py:952 GET_WITH_DEFAULT -> MARK: NaN = missing marker; propagates through fk_alignment / fk_cross_change_stats
ml_train.py:953 GET_WITH_DEFAULT -> MARK: NaN = missing marker; propagates through fk_alignment / fk_cross_change_stats
ml_train.py:1053 GET_WITH_DEFAULT -> FIX: _xgb_append_only_ok (warm-start GATE): missing ticker compared ''=='' and missing max_ts/row_count defaulted to 0 so a prior fp lacking them always passed; every compared field must now be present on both sides or the gate returns False.
ml_train.py:1059 GET_OR_DEFAULT -> FIX: _xgb_append_only_ok (warm-start GATE): missing ticker compared ''=='' and missing max_ts/row_count defaulted to 0 so a prior fp lacking them always passed; every compared field must now be present on both sides or the gate returns False.
ml_train.py:1061 GET_WITH_DEFAULT -> FIX: _xgb_append_only_ok (warm-start GATE): missing ticker compared ''=='' and missing max_ts/row_count defaulted to 0 so a prior fp lacking them always passed; every compared field must now be present on both sides or the gate returns False.
ml_train.py:1129 IF_TRUTHY_ELSE -> MARK: branch on the evaluate_only bool flag -- evaluate-only fits nothing, so "no holdout (n_val=0), whole frame" is the real split, not a default
ml_train.py:1264 GET_WITH_DEFAULT -> FIX: warm-start condition: preprocessing_version '' default and target_mode defaulting to TRICLASS -- a meta that did not state its target mode could warm-start; absent keys now refuse warm-start.
ml_train.py:1268 GET_WITH_DEFAULT -> FIX: warm-start condition: preprocessing_version '' default and target_mode defaulting to TRICLASS -- a meta that did not state its target mode could warm-start; absent keys now refuse warm-start.
ml_train.py:1467 GET_WITH_DEFAULT -> FIX: CLI summary printed a measured-looking 'acc=0.0% edge=+0.0pp' for a result lacking them; now prints n/a.
ml_train.py:1468 GET_WITH_DEFAULT -> FIX: CLI summary printed a measured-looking 'acc=0.0% edge=+0.0pp' for a result lacking them; now prints n/a.
monte_carlo.py:321 IF_TRUTHY_ELSE -> MARK: model design -- SHOCK_CONFIG lists only the jump-bearing regimes (breakout/acceleration/vol_expansion/reversal_prone); every other regime is simulated without a jump component, so probability 0 is the specified model, not a missing input
monte_carlo.py:322 IF_TRUTHY_ELSE -> MARK: same model design -- no jump component for regimes outside SHOCK_CONFIG (and shock_size stays 0 because shock_prob is 0)
monte_carlo.py:498 GET_WITH_DEFAULT -> FIX: __main__ demo printed a fabricated 0 drift; simulate() always records per_bar_drift -> indexed.
movement_target_threshold.py:52 GET_WITH_DEFAULT -> FIX: key-level defaults 0.0005/0.5 were NOT the calibrated values (0.0008/0.55 in calibration/movement_target_threshold_v1.json and the loader's own fallback) -> both params required.
movement_target_threshold.py:53 GET_WITH_DEFAULT -> FIX: key-level defaults 0.0005/0.5 were NOT the calibrated values (0.0008/0.55 in calibration/movement_target_threshold_v1.json and the loader's own fallback) -> both params required.
movement_target_threshold.py:93 GET_WITH_DEFAULT -> MARK: opt-in exclusion flag in the by-horizon calibration JSON (every shipped horizon states it explicitly); a horizon that does not set it has not been ruled invalid, so the directional target stays enabled
multi_horizon_decision.py:154 GET_OR_DEFAULT -> MARK: operator-visible WAIT explanation text only -- the setup is already vetoed (WAIT); a blocker without a reason is labelled literally "unknown", never parsed as a gate result
multi_horizon_decision.py:350 IF_NOT_NONE_ELSE -> MARK: trade_mode label when mins_to_close is absent; "unknown" matches none of scalp/intraday/session so no mode-specific branch fires, and it is surfaced literally as unknown (never as a real mode)
multi_horizon_decision.py:503 GETATTR_DEFAULT -> FIX: per-horizon audit published fusion_top_probability (and dominant direction) from UNAVAILABLE snapshots' 1/3 / 'flat' placeholders; both now None unless horizon_fusion_available (top_probability is a required field, the 0.0 default was dead).
multi_horizon_decision.py:590 GETATTR_DEFAULT -> MARK: fail-closed -- no call / no call signal reads as "wait", which VETOES a tradeable setup (tradeable=False, size 0); it can never create a trade
multi_horizon_decision.py:608 GETATTR_DEFAULT -> MARK: fail-closed entry-state input -- absent call state/signal is "WAIT" (no entry armed), never an entry signal
multi_horizon_decision.py:860 GET_WITH_DEFAULT -> MARK: operator env knob; documented default 0.0 = no canonical blend into the empirical fallback triplet
multi_horizon_ml_bundle.py:213 GETATTR_DEFAULT -> FIX: missing/unrecognised FusionPayload.fusion_confidence recorded as 'low'; now None (dataclass field widened to str | None; no consumers).
multi_horizon_ml_bundle.py:229 GETATTR_DEFAULT -> MARK: boolean capability flag -- FusionPayload.mc_available itself defaults False ("Monte Carlo did not contribute"); a payload without the attribute had no MC input, so False is the true state
news_sentiment.py:32 GET_WITH_DEFAULT -> MARK: operator env config -- news refresh throttle, documented default 90s
news_sentiment.py:111 GET_WITH_DEFAULT -> MARK: operator env config -- per-request HTTP timeout, documented default 5s
news_sentiment.py:458 GET_WITH_DEFAULT -> MARK: operator env config -- news-context deadline, documented default 5s (<=0 disables the deadline)
normalized_training_sync.py:58 GET_WITH_DEFAULT -> MARK: operator env config -- cross-process materialize lock staleness, documented default 7200s
normalized_training_sync.py:228 IF_NOT_NONE_ELSE -> MARK: no stored fingerprint row -> None ("never materialized"), which the caller treats as a mismatch requiring materialization
normalized_training_sync.py:397 GET_WITH_DEFAULT -> MARK: operator env override; unset ("") falls through to the capture-interval-derived debounce below
normalized_training_sync.py:513 GET_WITH_DEFAULT -> MARK: operator env config -- normalized refresh debounce, documented default 120s
ops_runner.py:23 GET_WITH_DEFAULT -> MARK: operator env opt-in; unset means the ops runner stays DISABLED
ops_runner.py:27 GET_WITH_DEFAULT -> MARK: operator env opt-in; unset means remote triggering stays DENIED (local only)
ops_runner.py:199 GET_WITH_DEFAULT -> MARK: optional human-readable text of an ops sequence in the static registry; blank when the entry has none, display-only
patch_active_artifact_provenance.py:53 GET_OR_DEFAULT -> MARK: 0 only means "no alternate row count found" and is never written -- the `if alt:` guard below skips the patch, leaving rows_used unset
pin_neutral_outcome_repair_v1.py:81 GETATTR_DEFAULT -> MARK: argparse opt-in flag registered by register_allow_noncanonical_flag; absent = the safe canonical-DB-only posture
planes/context_light.py:214 GET_WITH_DEFAULT -> MARK: 0 is the repo-wide "no analytics version yet" sentinel of the L2 cache entry (analytics_bg_recompute seeds entries with 0; l1_runtime.compute_l2_version uses the same), a generation counter, not a measurement
planes/context_light.py:215 GET_OR_DEFAULT -> MARK: internal sentinel -- 0.0 is never served as a time: `if src_ts > 0` below leaves structural_age None (context marked STALE) and l2_snapshot_ts_used_iso None
planes/l1_operational.py:123 GET_WITH_DEFAULT -> MARK: rebuild-reason counter histogram -- a reason key is only created on its first increment, so an absent key is a true count of 0
planes/l1_operational.py:124 GET_WITH_DEFAULT -> MARK: rebuild-reason counter histogram, absent key = 0 occurrences
planes/l1_operational.py:125 GET_WITH_DEFAULT -> MARK: rebuild-reason counter histogram, absent key = 0 occurrences
planes/l1_operational.py:130 GET_WITH_DEFAULT -> MARK: rebuild-reason counter histogram, absent keys = 0 occurrences
planes/l1_operational.py:133 IF_TRUTHY_ELSE -> MARK: a 0 scope cap means uncapped (no LRU cap to press against), so pressure 0 is the true ratio; the served cap is the constant l1_runtime.L1_MAX_CACHE_SCOPES=128
planes/l1_operational.py:300 GET_WITH_DEFAULT -> FIX: every area is built in-function with status+interpretation; the 'unknown'/'' defaults could only hide an area that forgot its verdict -> indexed directly.
planes/l1_operational.py:315 GET_WITH_DEFAULT -> FIX: every area is built in-function with status+interpretation; the 'unknown'/'' defaults could only hide an area that forgot its verdict -> indexed directly.
planes/l1_operational.py:317 GET_WITH_DEFAULT -> FIX: every area is built in-function with status+interpretation; the 'unknown'/'' defaults could only hide an area that forgot its verdict -> indexed directly.
planes/l1_operational.py:319 GET_WITH_DEFAULT -> FIX: every area is built in-function with status+interpretation; the 'unknown'/'' defaults could only hide an area that forgot its verdict -> indexed directly.
planes/l1_runtime.py:56 GET_OR_DEFAULT -> MARK: 0 is the repo-wide "no analytics version yet" generation sentinel (analytics_bg_recompute seeds L2 entries with 0); it is a cache-key/version counter, not a market value
polling_adapter.py:66 GETATTR_DEFAULT -> MARK: error-message text only -- resp may be None here, so '?' marks "no HTTP status" inside the raised error; the fetch still fails
polling_adapter.py:123 GETATTR_DEFAULT -> MARK: error-message text only -- resp may be None here, so '?' marks "no HTTP status" inside the raised error; the fetch still fails
prediction_engine.py:81 GET_WITH_DEFAULT -> MARK: operator env switch, documented default "1" (enrichment on); only an explicit 0/false/no disables it
prediction_engine.py:164 GETATTR_DEFAULT -> MARK: fail-closed -- a snapshot without the availability flag is treated as fusion UNAVAILABLE and yields no triplet (None)
prediction_engine.py:251 GET_WITH_DEFAULT -> MARK: operator env knob, documented default 0.0 = no empirical support blend into the fusion triplet
prediction_engine.py:261 GETATTR_DEFAULT -> MARK: provenance string only selects the WITHHELD reason label; "" (no snapshot / no provenance) falls to the generic fusion_unavailable/missing label and the triplet stays withheld either way
prediction_engine.py:267 GETATTR_DEFAULT -> MARK: fail-closed reason label -- missing availability flag reads as fusion unavailable; the horizon is withheld in both branches
prediction_engine.py:308 GETATTR_DEFAULT -> MARK: fail-closed -- a snapshot without the availability flag is not counted as available
prediction_engine.py:881 GET_WITH_DEFAULT -> FIX: similar[0].get('match_tier', 7) re-labelled a tier-less row as tier 7 ('general dataset', low confidence); db_snapshots always stamps match_tier -> indexed.
prediction_engine.py:974 GETATTR_DEFAULT -> MARK: capability flag (FusionPayload.mc_available defaults False = MC did not contribute); absent -> MC band not used, move range stays empirical-only / None
prediction_engine.py:1164 GETATTR_DEFAULT -> MARK: capability flag, absent = MC did not contribute -> no MC-based reversal-risk boost is applied
prediction_engine.py:1194 IF_NOT_NONE_ELSE -> MARK: percent stays None when there is no empirical probability; every text branch below checks `pct is not None`
prediction_engine.py:1321 GETATTR_DEFAULT -> MARK: capability flag, absent = MC did not contribute -> the MC sentence is simply omitted from the rationale
realized_contract_eval.py:625 CAST_OR_DEFAULT -> MARK: SQL COUNT(*) is never NULL; guard only
realized_contract_eval.py:626 CAST_OR_DEFAULT -> MARK: SQL SUM(CASE..1/0) is NULL only over ZERO rows, where the true count is 0
realized_contract_eval.py:627 CAST_OR_DEFAULT -> MARK: SQL SUM(CASE..1/0) is NULL only over ZERO rows, where the true count is 0
realized_contract_eval.py:628 CAST_OR_DEFAULT -> MARK: SQL SUM(CASE..1/0) is NULL only over ZERO rows, where the true count is 0
realized_contract_eval.py:636 IF_TRUTHY_ELSE -> FIX: coverage rates over ZERO rows were 0.0 ('0% replayable'); now None (matches replay_bundle_coverage).
realized_contract_eval.py:637 IF_TRUTHY_ELSE -> FIX: coverage rates over ZERO rows were 0.0 ('0% replayable'); now None (matches replay_bundle_coverage).
realized_contract_eval.py:638 IF_TRUTHY_ELSE -> FIX: coverage rates over ZERO rows were 0.0 ('0% replayable'); now None (matches replay_bundle_coverage).
realized_contract_eval.py:790 GET_OR_DEFAULT -> FIX: blank/missing pnl_dollars read as $0 -> fabricated parallel-minus-cascade pnl diff; such pairs are now skipped.
realized_contract_eval.py:791 GET_OR_DEFAULT -> FIX: blank/missing pnl_dollars read as $0 -> fabricated parallel-minus-cascade pnl diff; such pairs are now skipped.
realized_contract_eval.py:1118 IF_TRUTHY_ELSE -> MARK: CSV encoding of the computed boolean sb_conf (both stop and target hit in one bar) -- a real True/False, not a default
realized_contract_eval.py:1223 IF_TRUTHY_ELSE -> FIX: same_bar_conflict_share_of_valid over zero valid trades was 0.0; now None (matches win_rate/avg_pnl in the same report).
regime_engine.py:494 GETATTR_DEFAULT -> MARK: "UNKNOWN" is micro_structure.R_UNKNOWN, the explicit no-micro-read regime; the family scorers give it no directional support (regime_direction -> neutral)
regime_engine.py:526 IF_TRUTHY_ELSE -> MARK: no scored family -> 0.0, which the very next line turns into _unknown_regime() (fail-closed), never a regime
release_object.py:35 GET_WITH_DEFAULT -> MARK: optional operator env override; unset ("") falls through to reading the real git HEAD sha
release_object.py:106 GET_WITH_DEFAULT -> MARK: optional operator env; unset collapses to None (no approval record), never a placeholder string
release_object.py:107 GET_WITH_DEFAULT -> MARK: optional operator env; unset collapses to None (no rollback target), never a placeholder string
replay_bundle_coverage.py:66 IF_TRUTHY_ELSE -> MARK: SQL WHERE construction -- no timeframe filter requested means match all rows ("1=1"), not a value default
replay_bundle_coverage.py:124 CAST_OR_DEFAULT -> MARK: SQL COUNT(*) of a GROUP BY group is never NULL (>=1 row); guard only
replay_bundle_coverage.py:125 CAST_OR_DEFAULT -> MARK: SQL SUM(CASE..1/0) is NULL only over zero rows, where the true count is 0
replay_bundle_coverage.py:126 CAST_OR_DEFAULT -> MARK: SQL SUM(CASE..1/0) is NULL only over zero rows, where the true count is 0
replay_bundle_coverage.py:127 CAST_OR_DEFAULT -> MARK: SQL SUM(CASE..1/0) is NULL only over zero rows, where the true count is 0
replay_bundle_coverage.py:138 CAST_OR_DEFAULT -> MARK: SQL COUNT(*) is never NULL; guard only
replay_bundle_coverage.py:139 CAST_OR_DEFAULT -> MARK: SQL SUM(CASE..1/0) is NULL only over zero rows, where the true count is 0
replay_bundle_coverage.py:140 CAST_OR_DEFAULT -> MARK: SQL SUM(CASE..1/0) is NULL only over zero rows, where the true count is 0
replay_bundle_coverage.py:141 CAST_OR_DEFAULT -> MARK: SQL SUM(CASE..1/0) is NULL only over zero rows, where the true count is 0
replay_bundle_coverage.py:171 GET_OR_DEFAULT -> FIX: _enrich_with_expansion read absent counts as 0 (error dict for a missing table flowed in, fabricating a rows-needed estimate before a KeyError); error dicts are now skipped by the caller and counts indexed directly.
replay_bundle_coverage.py:172 GET_OR_DEFAULT -> FIX: _enrich_with_expansion read absent counts as 0 (error dict for a missing table flowed in, fabricating a rows-needed estimate before a KeyError); error dicts are now skipped by the caller and counts indexed directly.
replay_bundle_coverage.py:190 GET_OR_DEFAULT -> FIX: _enrich_with_expansion read absent counts as 0 (error dict for a missing table flowed in, fabricating a rows-needed estimate before a KeyError); error dicts are now skipped by the caller and counts indexed directly.
replay_bundle_coverage.py:191 GET_OR_DEFAULT -> FIX: _enrich_with_expansion read absent counts as 0 (error dict for a missing table flowed in, fabricating a rows-needed estimate before a KeyError); error dicts are now skipped by the caller and counts indexed directly.
rules_engine.py:153 GET_WITH_DEFAULT -> MARK: fail-closed freshness filter -- a cross without bars_ago is treated as OLD and raises no "just crossed" alert; server builds every cross with bars_ago from the NOT NULL level_crosses.ts_utc
rules_engine.py:155 GET_WITH_DEFAULT -> MARK: alert display text only; server always sets level_name from the NOT NULL level_crosses.level_name column, "level" is a wording fallback never parsed back
rules_engine.py:208 GETATTR_DEFAULT -> MARK: "UNKNOWN" is micro_structure.R_UNKNOWN (analyze_micro's own value when no 1m regime was classified); regime_direction maps it to neutral, so no 1m/5m conflict downgrade fires
schwab_client.py:51 GETATTR_DEFAULT -> MARK: schwab-py library constant; older schwab.auth builds lack the attribute, and the fallback is Schwab's documented production API host, the same value the library defines
schwab_client.py:294 GET_WITH_DEFAULT -> MARK: operator env config -- OAuth callback wait, documented default 900s
schwab_client.py:372 GET_OR_DEFAULT -> MARK: parse_qs omits absent query params; a redirect without `state` yields None, exactly _get_auth_context_with_scope's own state=None default (no state carried), not an invented value
schwab_client.py:373 GET_OR_DEFAULT -> MARK: absent OAuth `code` -> None -> the request is REJECTED on the next line, never exchanged
schwab_client.py:404 GET_WITH_DEFAULT -> MARK: operator env config -- auth-failure latch window, documented default 300s
schwab_field_dictionary_builder.py:221 GET_WITH_DEFAULT -> MARK: CSV row without field_path -> "" -> skipped by `if fp and ep` below, never recorded
schwab_field_dictionary_builder.py:222 GET_WITH_DEFAULT -> MARK: CSV row without endpoint -> "" -> skipped by `if fp and ep` below, never recorded
schwab_field_dictionary_builder.py:264 IF_TRUTHY_ELSE -> MARK: no known endpoint -> "" -> normalize_path adds NO endpoint prefix (its documented falsy-endpoint branch), rather than guessing one
schwab_full_field_inventory.py:480 GET_WITH_DEFAULT -> MARK: field-inventory tool -- a captured sample is either a {"payload": ...} wrapper or the raw stream message itself; both are real captured data whose keys are flattened
schwab_full_field_inventory.py:565 GET_OR_DEFAULT -> MARK: identity lookup across Schwab's two documented account-id leaves; absent both -> falsy -> next line's fallback / no account_id, no value invented
server.py:397 GETATTR_DEFAULT -> MARK: logging-handler dedup -- a FileHandler without baseFilename resolves to the cwd path, which only affects whether a duplicate log handler is added, never data
server.py:415 GETATTR_DEFAULT -> MARK: duck typing on an optional stream method -- a stderr replacement without isatty() is not a TTY, so no ANSI colouring (console cosmetics only)
server.py:822 IF_NOT_NONE_ELSE -> MARK: condition-variable poll slice -- no deadline (remaining None) waits in 1s slices and re-checks, a scheduling interval not a data value
server.py:1015 GETATTR_DEFAULT -> MARK: hard-exit flush loop -- a logger without handlers has nothing to flush
server.py:1317 GET_WITH_DEFAULT -> MARK: operator env config -- viewer SSE cadence, documented default 5.0s (see comment above)
server.py:1318 GET_WITH_DEFAULT -> MARK: operator env config -- viewer cache TTL, documented default 5.0s (= cadence)
server.py:1341 GET_WITH_DEFAULT -> MARK: operator env config -- bounded SSE recompute wait, documented default 12.0s
server.py:1346 GET_WITH_DEFAULT -> MARK: operator env config -- which panels to pre-warm, documented default SPY,QQQ,IWM
server.py:1349 GET_WITH_DEFAULT -> MARK: operator env config -- warm stagger, documented default 2.0s
server.py:1351 GET_WITH_DEFAULT -> MARK: operator env config -- UI SLA budget, documented default 500ms
server.py:1352 GET_WITH_DEFAULT -> MARK: operator env config -- UI SLA budget, documented default 2000ms
server.py:1353 GET_WITH_DEFAULT -> MARK: operator env config -- UI SLA budget, documented default 15000ms
server.py:1356 GET_WITH_DEFAULT -> MARK: operator env config -- live quote SSE interval, documented default 0.12s
server.py:1374 GET_WITH_DEFAULT -> MARK: operator env switch, documented default "1" = throttle ON; only an explicit 0/false/no/off disables it
server.py:1515 GET_WITH_DEFAULT -> MARK: diagnostics counter increment -- an absent key means no rejection counted yet
server.py:1529 GET_WITH_DEFAULT -> MARK: diagnostics counter increment -- an absent key means no rejection counted yet
server.py:1546 GET_WITH_DEFAULT -> MARK: diagnostics counter increment, absent = none counted yet
server.py:1570 GET_WITH_DEFAULT -> MARK: live-connection gauge increment, absent = no connection counted yet
server.py:1572 GET_WITH_DEFAULT -> MARK: running-max gauge -- no recorded peak yet is 0, immediately replaced by the real current count
server.py:1583 GET_WITH_DEFAULT -> MARK: live-connection gauge decrement, floored at 0
server.py:1625 GET_OR_DEFAULT -> MARK: identity/freshness comparison key only; epoch 0 always compares oldest, never presented as a time
server.py:1631 GET_WITH_DEFAULT -> MARK: violation counter increment, absent = none counted yet
server.py:1645 GET_WITH_DEFAULT -> MARK: diagnostics counter increment, absent = none counted yet
server.py:1651 GET_WITH_DEFAULT -> MARK: diagnostics counter increment, absent = none counted yet
server.py:1655 GET_WITH_DEFAULT -> MARK: diagnostics counter increment, absent = none counted yet
server.py:1675 GET_WITH_DEFAULT -> MARK: diagnostics counter increment, absent = none counted yet
server.py:1681 GET_WITH_DEFAULT -> MARK: diagnostics counter increment, absent = none counted yet
server.py:1685 GET_WITH_DEFAULT -> MARK: diagnostics counter increment, absent = none counted yet
server.py:1863 GET_WITH_DEFAULT -> MARK: operator env config -- background analytics failure cap, documented default 3
server.py:2117 GET_WITH_DEFAULT -> MARK: price-level cache-validity key carried forward; "" never equals today's date, so a carrier without it is a cache MISS (refetch)
server.py:2145 GET_WITH_DEFAULT -> MARK: 0 is the analytics generation counter's documented "no version yet" sentinel (the missing-bundle branch below publishes the same 0); a counter, not a market value
server.py:2277 GET_OR_DEFAULT -> MARK: broadcast-dedup identity tuple only -- an unstamped payload's epoch-0 can never equal a real build ts, so it is never suppressed as a duplicate
server.py:2278 GET_OR_DEFAULT -> MARK: dedup identity only -- 0 is the analytics generation counter's "no version yet" sentinel
server.py:2297 GET_OR_DEFAULT -> MARK: dedup identity tuple only -- compared against the recorded broadcast identity, never displayed or persisted
server.py:2298 GET_OR_DEFAULT -> MARK: dedup identity only -- 0 is the analytics generation counter's "no version yet" sentinel
server.py:2583 GET_WITH_DEFAULT -> MARK: carries the previous entry's generation counter; 0 = the documented "no analytics version yet" sentinel for a first write
server.py:2589 GET_WITH_DEFAULT -> MARK: price-level cache-validity key carried forward; "" never matches today's date -> cache MISS (refetch)
server.py:2666 GET_WITH_DEFAULT -> MARK: operator env opt-out; unset means startup warm RUNS
server.py:2718 GET_WITH_DEFAULT -> MARK: operator env opt-out; unset means model prewarm RUNS
server.py:3243 GET_WITH_DEFAULT -> MARK: operator env config -- tick-coherent gate, documented default 0.5s
server.py:3245 GET_WITH_DEFAULT -> MARK: operator env config -- tick-coherent minimum spacing, documented default 0.45s
server.py:3260 GET_OR_DEFAULT -> MARK: selection sort key only (freshest cache entry), never served as a time
server.py:3484 GET_WITH_DEFAULT -> MARK: operator env config -- max cumulative-volume attribution gap, documented default 60s
server.py:3582 GET_OR_DEFAULT -> MARK: sum accumulator -- only runs when a REAL vol_delta exists; an unopened bar sum (None) starts from the additive identity 0.0, so the stored volume is exactly the sum of observed deltas
server.py:3745 GET_WITH_DEFAULT -> MARK: operator env config -- logger startup delay, documented default 60s
server.py:3776 GET_WITH_DEFAULT -> MARK: operator env opt-in; unset means FIFO eviction stays OFF
server.py:3786 GET_WITH_DEFAULT -> MARK: operator env override; unset ("") falls through to the documented default cap below
server.py:4472 GET_WITH_DEFAULT -> MARK: per-ticker log-cycle counter increment, absent = none logged yet
server.py:4667 GET_WITH_DEFAULT -> MARK: per-ticker log-cycle counter increment, absent = none logged yet
server.py:4715 GET_WITH_DEFAULT -> MARK: operator env config -- base capture timeout, documented default 45s
server.py:5311 GET_WITH_DEFAULT -> MARK: instrumentation counter increment, absent = none assigned yet
server.py:5769 GET_OR_DEFAULT -> MARK: generation counter sentinel -- 0 = pre-first-publish, real generations start at 1
server.py:5828 GET_OR_DEFAULT -> MARK: selection sort key only (freshest cache entry), never served as a time
server.py:5982 GET_WITH_DEFAULT -> MARK: cache-validity key -- "" never equals today's date, so an entry without pl_date is a cache MISS and levels are refetched
server.py:6006 GETATTR_DEFAULT -> FIX: PriceLevels declares session_rth_positive_volume_bars; getattr 0 default could mis-classify a missing count as 'no RTH volume' and hide a VWAP producer failure -> direct attribute.
server.py:6014 GETATTR_DEFAULT -> FIX: PriceLevels declares session_rth_positive_volume_bars; getattr 0 default could mis-classify a missing count as 'no RTH volume' and hide a VWAP producer failure -> direct attribute.
server.py:6023 GETATTR_DEFAULT -> FIX: PriceLevels declares session_rth_positive_volume_bars; getattr 0 default could mis-classify a missing count as 'no RTH volume' and hide a VWAP producer failure -> direct attribute.
server.py:6177 IF_TRUTHY_ELSE -> MARK: internal tracker sentinel (epoch 0 = "no bar yet"); it can never exceed a stored bar ts, so no bar is counted -- never served as a time
server.py:6178 IF_TRUTHY_ELSE -> MARK: internal tracker sentinel (epoch 0 = "no bar yet"); no 5m bar is counted from it -- never served as a time
server.py:6193 GET_WITH_DEFAULT -> MARK: tracker dict is always created with last_bar_ts_1m (epoch-0 "no bar counted yet" sentinel), so any real bar ts counts as new
server.py:6196 GET_WITH_DEFAULT -> MARK: tracker dict is always created with last_bar_ts_5m (epoch-0 "no bar counted yet" sentinel), so any real bar ts counts as new
server.py:6243 GET_WITH_DEFAULT -> FIX: recent-cross bars_ago: level_crosses.ts_utc is NOT NULL, epoch-0 default would invent a ~29M-bar age -> indexed.
server.py:6333 GET_WITH_DEFAULT -> MARK: operator env config -- news throttle, documented default 90s (same default as news_sentiment)
server.py:6896 GET_WITH_DEFAULT -> FIX: snapshot counts: _db_counts_and_crosses_for_state pre-initialised {'total':0,'filled':0}, so no-DB / failed query served '0 snapshots'; now None-initialised and both consumers index the always-present keys.
server.py:6897 GET_WITH_DEFAULT -> FIX: snapshot counts: _db_counts_and_crosses_for_state pre-initialised {'total':0,'filled':0}, so no-DB / failed query served '0 snapshots'; now None-initialised and both consumers index the always-present keys.
server.py:7356 CAST_OR_DEFAULT -> FIX: kl_gex_input_completeness forced 0/max(total,1)=0.0 for an empty chain; diag is always ExposureDiagnostics -> direct fields, None when contracts_total == 0. Also (same block, not a scanner hit) kl_net_gex_mag/regime were served 'negligible'/'neutral' for an ABSENT net GEX -> now None.
server.py:7358 CAST_OR_DEFAULT -> FIX: kl_gex_input_completeness forced 0/max(total,1)=0.0 for an empty chain; diag is always ExposureDiagnostics -> direct fields, None when contracts_total == 0. Also (same block, not a scanner hit) kl_net_gex_mag/regime were served 'negligible'/'neutral' for an ABSENT net GEX -> now None.
server.py:7425 GETATTR_DEFAULT -> MARK: a LIST of driver strikes -- with no consensus summary there are no identified drivers, and an empty list states exactly that (no strike or value is invented)
server.py:7426 GETATTR_DEFAULT -> MARK: a LIST of driver strikes -- empty = none identified, no strike or value invented
server.py:7524 GETATTR_DEFAULT -> FIX: ms is always a MarketState (build_market_state re-raises) and every field is declared on it; the server-side getattr defaults were a second default authority for market_state.py's values -> direct attribute access (values unchanged).
server.py:7531 GETATTR_DEFAULT -> FIX: ms is always a MarketState (build_market_state re-raises) and every field is declared on it; the server-side getattr defaults were a second default authority for market_state.py's values -> direct attribute access (values unchanged).
server.py:7535 GETATTR_DEFAULT -> FIX: ms is always a MarketState (build_market_state re-raises) and every field is declared on it; the server-side getattr defaults were a second default authority for market_state.py's values -> direct attribute access (values unchanged).
server.py:7536 GETATTR_DEFAULT -> FIX: ms is always a MarketState (build_market_state re-raises) and every field is declared on it; the server-side getattr defaults were a second default authority for market_state.py's values -> direct attribute access (values unchanged).
server.py:7537 GETATTR_DEFAULT -> FIX: ms is always a MarketState (build_market_state re-raises) and every field is declared on it; the server-side getattr defaults were a second default authority for market_state.py's values -> direct attribute access (values unchanged).
server.py:7538 GETATTR_DEFAULT -> FIX: ms is always a MarketState (build_market_state re-raises) and every field is declared on it; the server-side getattr defaults were a second default authority for market_state.py's values -> direct attribute access (values unchanged).
server.py:7539 GETATTR_DEFAULT -> FIX: ms is always a MarketState (build_market_state re-raises) and every field is declared on it; the server-side getattr defaults were a second default authority for market_state.py's values -> direct attribute access (values unchanged).
server.py:7540 GETATTR_DEFAULT -> FIX: ms is always a MarketState (build_market_state re-raises) and every field is declared on it; the server-side getattr defaults were a second default authority for market_state.py's values -> direct attribute access (values unchanged).
server.py:7546 GETATTR_DEFAULT -> FIX: ms is always a MarketState (build_market_state re-raises) and every field is declared on it; the server-side getattr defaults were a second default authority for market_state.py's values -> direct attribute access (values unchanged).
server.py:7547 GETATTR_DEFAULT -> FIX: ms is always a MarketState (build_market_state re-raises) and every field is declared on it; the server-side getattr defaults were a second default authority for market_state.py's values -> direct attribute access (values unchanged).
server.py:7548 GETATTR_DEFAULT -> FIX: ms is always a MarketState (build_market_state re-raises) and every field is declared on it; the server-side getattr defaults were a second default authority for market_state.py's values -> direct attribute access (values unchanged).
server.py:7549 GETATTR_DEFAULT -> FIX: ms is always a MarketState (build_market_state re-raises) and every field is declared on it; the server-side getattr defaults were a second default authority for market_state.py's values -> direct attribute access (values unchanged).
server.py:7550 GETATTR_DEFAULT -> FIX: ms is always a MarketState (build_market_state re-raises) and every field is declared on it; the server-side getattr defaults were a second default authority for market_state.py's values -> direct attribute access (values unchanged).
server.py:7551 GETATTR_DEFAULT -> FIX: ms is always a MarketState (build_market_state re-raises) and every field is declared on it; the server-side getattr defaults were a second default authority for market_state.py's values -> direct attribute access (values unchanged).
server.py:7556 GETATTR_DEFAULT -> FIX: ms is always a MarketState (build_market_state re-raises) and every field is declared on it; the server-side getattr defaults were a second default authority for market_state.py's values -> direct attribute access (values unchanged).
server.py:7557 GETATTR_DEFAULT -> FIX: ms is always a MarketState (build_market_state re-raises) and every field is declared on it; the server-side getattr defaults were a second default authority for market_state.py's values -> direct attribute access (values unchanged).
server.py:7643 GETATTR_DEFAULT -> MARK: optional configured contract SYMBOL (ED_FUTURES_ES); "" = none configured, a label not a quote -- the price/chg fields beside it stay None
server.py:7646 GETATTR_DEFAULT -> MARK: optional configured contract SYMBOL (ED_FUTURES_NQ); "" = none configured, a label not a quote
server.py:7649 GETATTR_DEFAULT -> MARK: optional configured contract SYMBOL (ED_FUTURES_RTY); "" = none configured, a label not a quote
server.py:7652 GETATTR_DEFAULT -> MARK: display-only prose sentence; blank when the market context carries none, never parsed as data
server.py:7696 GETATTR_DEFAULT -> MARK: display-only sector caption; blank when the proxy row has none, the symbol/chg fields carry the data
server.py:7710 GET_WITH_DEFAULT -> FIX: snapshot counts: _db_counts_and_crosses_for_state pre-initialised {'total':0,'filled':0}, so no-DB / failed query served '0 snapshots'; now None-initialised and both consumers index the always-present keys.
server.py:7711 GET_WITH_DEFAULT -> FIX: snapshot counts: _db_counts_and_crosses_for_state pre-initialised {'total':0,'filled':0}, so no-DB / failed query served '0 snapshots'; now None-initialised and both consumers index the always-present keys.
server.py:7870 GET_WITH_DEFAULT -> MARK: generation counter increment -- no previous version means 0 so the first published bundle is version 1
server.py:7918 GET_WITH_DEFAULT -> MARK: price-level cache-validity key carried forward; "" never matches today's date -> cache MISS (refetch)
server.py:8082 GETATTR_DEFAULT -> MARK: fail-closed token check -- a response without a status code is treated as NOT 200 and the token validation warning fires
server.py:8086 GETATTR_DEFAULT -> MARK: log-message text only -- prints "None" when there was no response/status
server.py:8150 GET_WITH_DEFAULT -> MARK: operator env opt-in, documented default "0" = background scheduler OFF
server.py:8421 IF_TRUTHY_ELSE -> MARK: TTL lookup key -- the resolved cache key's expiry when one was found, else the caller's requested expiry (both real identifiers)
server.py:8452 IF_NOT_NONE_ELSE -> MARK: telemetry expiry label -- requested expiry, else the resolved cache key's, else None; no value invented
server.py:9099 GET_WITH_DEFAULT -> MARK: fail-closed -- a capture result without status is not "ok", so nothing is persisted as a successful morning capture
server.py:9281 GET_OR_DEFAULT -> FIX: _log_flip_drift stamped an undated terrain payload with the append wall clock (measurement row with invented time); undated payloads are now not logged.
server.py:9960 IF_NOT_NONE_ELSE -> MARK: age stays None when the leg has no receive timestamp -- honest absence
server.py:10062 IF_TRUTHY_ELSE -> FIX: stream_coverage live_pct over zero contract-bearing cells was 0.0; now None (client computes its own on-screen coverage).
server.py:10607 IF_NOT_NONE_ELSE -> MARK: distance stays None when there is no gap to a wall -- honest absence
server.py:11101 SETDEFAULT -> MARK: per-cell timestamp row initialised to None per expiry (unknown until stamped below), not a fabricated time
server.py:11318 GET_WITH_DEFAULT -> MARK: SSE event-name routing -- envelopes that do not name an event are the default L1 projection stream by contract (only the gamma surface stamps its own name)
server.py:11324 CAST_OR_DEFAULT -> MARK: 0.0 = "no drop ever recorded" sentinel; the age is None unless drop_m > 0
server.py:11336 GET_WITH_DEFAULT -> MARK: violation counter, absent = none counted
server.py:11490 IF_TRUTHY_ELSE -> MARK: loop scheduling -- no viewers sleeps the slower CACHE_TTL cadence (documented idle behaviour), not a data value
