# CAPS batch 3 ledger (line numbers = original hit inventory)

setup_readiness.py:89 IF_TRUTHY_ELSE -> MARK: 0 is the policy's point award for "validation not passed" (scored tier, not a missing measurement)
setup_readiness.py:134 CAST_OR_DEFAULT -> FIX: _prob_float returned 0.0 for absent/unreadable probability; readiness then printed "current 0.00%" as if measured and scored it in the "weak" band (3 pts). Now returns None; score_readiness scores it as band "unavailable" (READINESS_PROB_UNAVAILABLE_POINTS = 0) and both sides word it "Dominant probability is unavailable." Consumer chain: setup_readiness.compute_{call,put}_readiness -> call_engine.compute_call sections 10/11 (_readiness_score/_put_score, reasons, missing_conditions, component_scores) -> TheCall -> market_state call readiness -> UI. Live caller always passes a float (call_engine._readiness_canonical_fields), so no live output change.
setup_readiness.py:180 GET_WITH_DEFAULT -> FIX: redundant "" default removed (.get(k) -> _safe_lower(None) -> "", tier "none" = no structure read)
setup_readiness.py:181 GET_WITH_DEFAULT -> FIX: same as :180
setup_readiness.py:185 GET_WITH_DEFAULT -> FIX: 0.0 default removed; absence -> None -> "unavailable" band (see :134)
setup_readiness.py:186 GET_WITH_DEFAULT -> MARK: fail-closed - unasserted validation is "not passed"; call_engine always supplies _post_gate_ok
setup_readiness.py:187 GET_WITH_DEFAULT -> MARK: optional trigger flag; absence falls through to level_proximity / explicit "unknown" tier
setup_readiness.py:188 GET_WITH_DEFAULT -> MARK: optional trigger flag; absence = no breakout asserted
setup_readiness.py:286 GET_WITH_DEFAULT -> FIX: same as :180 (put side)
setup_readiness.py:287 GET_WITH_DEFAULT -> FIX: same as :180 (put side)
setup_readiness.py:291 GET_WITH_DEFAULT -> FIX: same as :185 (put side)
setup_readiness.py:292 GET_WITH_DEFAULT -> MARK: fail-closed validation flag (put side)
setup_readiness.py:293 GET_WITH_DEFAULT -> FIX: PUT near_resistance fell back to the CALL key near_support (support is the opposite trigger for a PUT). Fallback removed; own key only, marked.
setup_readiness.py:294 GET_WITH_DEFAULT -> FIX: PUT breakdown_ready fell back to the CALL key breakout_ready (an upside breakout scored as a PUT trigger). Fallback removed; own key only, marked.
signals.py:102 GET_WITH_DEFAULT -> MARK: ED_LIVE_MODEL_STACK_ENABLED env switch; unset = documented OFF (RC-REHAB-1 directive)
signals.py:226 GET_WITH_DEFAULT -> MARK: ED_CONSOLE_ALLOW_PRED_OVERRIDE debug opt-in; unset = overrides refused
signals.py:600 GETATTR_DEFAULT -> FIX: getattr(inp,"ticker","") -> inp.ticker (SignalInput.ticker is a required field; log context)
signals.py:605 GETATTR_DEFAULT -> MARK: fail-closed; horizon skipped, mc_efe_/mc_eae_ keys stay absent (None)
signals.py:652 GETATTR_DEFAULT -> FIX: `getattr(inp,"ticker","") or ""` -> inp.ticker (empty-string identity would key DB/model lookups on "")
signals.py:692 GETATTR_DEFAULT -> FIX: fallback overlay {"ticker": ""} -> inp.ticker
signals.py:904 GETATTR_DEFAULT -> MARK: conditioning provenance stamped only onto an explicitly available simulation
signals.py:955 GETATTR_DEFAULT -> FIX: -> inp.ticker (replay stack identity)
signals.py:1010 GETATTR_DEFAULT -> FIX: -> inp.ticker (replay fallback overlay)
signals.py:1108 GETATTR_DEFAULT -> MARK: absent availability renders stage "inactive" (fail-closed)
signals.py:1137 GETATTR_DEFAULT -> MARK: mc_out may be None; absent availability renders MC stage "inactive"
signals.py:1152 IF_TRUTHY_ELSE -> MARK: scanner false positive - ternary between two measured non-None MC probabilities
signals.py:1170 GETATTR_DEFAULT -> FIX: getattr(call,"signal","wait") -> call.signal (TheCall.signal required; missing would fabricate "supports stack"/"contradicts" vs a WAIT that never existed)
signals.py:1228 IF_NOT_NONE_ELSE -> MARK: absence stays None (suffix omitted)
signals.py:1232 IF_NOT_NONE_ELSE -> MARK: absence stays None (suffix omitted)
signals.py:1246 GETATTR_DEFAULT -> FIX: -> call.signal (was fabricating "Final Call: WAIT (low)" stage)
signals.py:1247 GETATTR_DEFAULT -> FIX: -> call.conviction
signals.py:1339 GETATTR_DEFAULT -> FIX: compute_signals ticker -> inp.ticker
signals.py:1351 GETATTR_DEFAULT -> FIX: _compute_signals_impl ticker fallback -> inp.ticker
signals.py:1459 GETATTR_DEFAULT -> FIX: shared-tick fallback overlay -> inp.ticker
signals.py:1646 GETATTR_DEFAULT -> FIX: `_n_base_live` counter was dead (assigned, never read) - deleted
signals.py:1666 GETATTR_DEFAULT -> FIX: fusion is a non-None FusionOutput (hard invariant raised above); `getattr(..., []) or []` -> list(fusion.contributing_models) so a missing field raises instead of serving "no models"
signals.py:1667 GETATTR_DEFAULT -> FIX: same for fusion.missing_models (a missing list would have served "no models missing")
similarity_audit.py:239 GET_WITH_DEFAULT -> FIX: fabricated LIMIT 500 in the served constraint definition -> ctx["n_similar_limit"] (always set by query_context_for_similarity)
similarity_audit.py:317 GET_OR_DEFAULT -> FIX: missing row count became 0 and reported skip_reason "zero_rows_in_limited_pool" -> entry["row_count_after_query_limit"] (always written by db_snapshots._append_tier)
similarity_audit.py:318 GET_WITH_DEFAULT -> FIX: legacy-alias fallback removed -> entry["tier_stop_viable"] (always written)
similarity_audit.py:517 GET_WITH_DEFAULT -> MARK: chosen_tier is the same value under its older name (db_snapshots._finish writes both); both absent -> None
similarity_audit.py:518 GET_WITH_DEFAULT -> MARK: final_similar_count alias of the same len(out); both absent -> None
similarity_audit.py:520 GET_WITH_DEFAULT -> MARK: final_empirically_viable alias of the same ftsv; both absent -> None
similarity_audit.py:536 GET_OR_DEFAULT -> FIX: unknown tier served as tier 0 (tiers are 1..5) -> None
similarity_feature_search.py:142 GET_WITH_DEFAULT -> FIX: WEIGHT_BAND_SCALARS["MEDIUM"] (module-constant key; default could never fire, now fails loudly if renamed)
similarity_feature_search.py:326 GET_OR_DEFAULT -> FIX: missing jaccard entered the survival mean as 0.0 (drives LOW/MEDIUM weight-band recommendation) -> t["overlap_vs_heuristic"]["jaccard"] (always produced by _overlap_metrics)
similarity_feature_search.py:517 NEXT_DEFAULT -> MARK: None = true answer "no stage hit zero"
similarity_feature_survivorship.py:245 GET_OR_DEFAULT -> FIX: best_jaccard = 0.0 when no tier-stop-viable trial existed -> None
similarity_feature_survivorship.py:246 GET_WITH_DEFAULT -> FIX: part of the same statement; now indexes the producer's required keys
similarity_feature_survivorship.py:277 IF_TRUTHY_ELSE -> FIX: inclusion_frequency 0.0 for features with zero eligible anchors (undefined ratio) -> None; classification branches on None (OMIT), table row serves None
similarity_feature_survivorship.py:278 IF_TRUTHY_ELSE -> FIX: stability 0.0 with zero anchors -> function now raises ValueError on empty anchors (every ratio, incl. structural 1.0 rows, was fabricated); stab computed directly
similarity_feature_survivorship.py:341 GET_WITH_DEFAULT -> FIX: report["feature_survivorship_table"] (missing table silently produced an empty final structure)
similarity_feature_survivorship.py:377 GET_WITH_DEFAULT -> FIX: report["anchor_count"] (missing count silently produced "LOW")
smoke_predict_active.py:105 GETATTR_DEFAULT -> FIX: args.allow_noncanonical_db (flag always registered by register_allow_noncanonical_flag)
snapshot_normalizer.py:588 GET_WITH_DEFAULT -> FIX: success gate now mat["errors"] / val["ok"] (both always initialised by producers)
snapshot_normalizer.py:639 IF_TRUTHY_ELSE -> MARK: scanner false positive - optional SQL WHERE fragment
snapshot_normalizer.py:782 GET_OR_DEFAULT -> FIX: r["materialize"]["raw_rows"] (always initialised)
snapshot_normalizer.py:783 GET_OR_DEFAULT -> FIX: r["materialize"]["normalized_rows"]
snapshot_normalizer.py:792 GET_WITH_DEFAULT -> FIX: v["per_ticker_counts"]
tier3_design.py:290 GET_WITH_DEFAULT -> MARK: display-only reasoning text; {} avoids AttributeError, value renders as visible "None"
tier3_design.py:291 GET_WITH_DEFAULT -> MARK: same
train_all.py:225 GET_WITH_DEFAULT -> MARK: ED_META_TRAIN_MAX_ROWS env; "0 = all rows" documented
train_all.py:262 IF_TRUTHY_ELSE -> FIX: meta-learner training filled a missing LSTM leg with a 0.333/0.333/0.334 prior (and missing classes with 0.333) while the live meta input ml_predict._stack_probs is fail-closed (None unless all three legs return full triplets) - train/serve skew + fabricated features. run_meta now builds each row with _stack_probs itself (ONE computation) and skips rows the live path could never score.
train_all.py:263 IF_TRUTHY_ELSE -> FIX: same for the Transformer leg
train_all.py:315 IF_TRUTHY_ELSE -> MARK: scanner false positive - optional SQL WHERE fragment
train_compare.py:261 GET_WITH_DEFAULT -> FIX: par_ret["used_feature_cache"] (every _train_parallel return carries it)
train_compare.py:262 GET_WITH_DEFAULT -> FIX: par_ret["used_cascade_tensor_cache"]
train_compare.py:296 GET_WITH_DEFAULT -> FIX: cas_ret["used_feature_cache"]
train_compare.py:297 GET_WITH_DEFAULT -> FIX: cas_ret["used_cascade_tensor_cache"]
train_compare.py:355 IF_NOT_NONE_ELSE -> FIX (restructure): "—" placeholders moved into a display-only _txt() helper outside the f-string (a marker inside the triple-quoted report would have been printed into it)
train_compare.py:356 IF_NOT_NONE_ELSE -> FIX (restructure): same
training_cache.py:531 GET_WITH_DEFAULT -> MARK: compare-only fp normalization; live fp always complete -> "" never equals -> cache miss
training_cache.py:532 GET_WITH_DEFAULT -> MARK: same (timeframe)
training_cache.py:533 GET_WITH_DEFAULT -> MARK: same (ticker)
training_cache.py:624 GETATTR_DEFAULT -> FIX: dataset.training_timeframe (declared LSTMDataset field)
training_cache.py:625 GETATTR_DEFAULT -> FIX: dataset.target_column
training_cache.py:626 GETATTR_DEFAULT -> FIX: dataset.ml_horizon_slug
training_cache.py:627 GETATTR_DEFAULT -> FIX: dataset.target_definition
training_cache.py:685 GET_WITH_DEFAULT -> FIX: load_lstm_feature_cache now requires every meta key the saver writes; a meta missing any is an invalid cache (return None -> rebuild), no dataset with empty tickers
training_cache.py:686 GET_WITH_DEFAULT -> FIX: same (timestamps)
training_cache.py:687 GET_WITH_DEFAULT -> FIX: same (days - drives walk-forward splits)
training_cache.py:688 GET_WITH_DEFAULT -> FIX: same (training_timeframe)
training_cache.py:691 GET_WITH_DEFAULT -> FIX: same (target_definition)
training_cache.py:696 GET_WITH_DEFAULT -> FIX: same (n_days 0)
training_cache.py:697 GET_WITH_DEFAULT -> FIX: same (n_tickers 0)
training_cache.py:698 GET_WITH_DEFAULT -> FIX: same (class_distribution)
training_cache.py:699 GET_WITH_DEFAULT -> FIX: same (skipped_reasons)
training_cache.py:818 GET_OR_DEFAULT -> MARK: missing count -> 0 -> rejected by the `n_stored <= 0` guard on the next line
training_cache.py:927 GET_WITH_DEFAULT -> MARK: -1 impossible row count -> identity mismatch (cache miss)
training_cache.py:994 GET_WITH_DEFAULT -> MARK: "" never equals the computed 64-hex tensor sha -> mismatch
training_cache.py:1112 GET_WITH_DEFAULT -> MARK: 0 < MIN_MANIFEST_SCHEMA_FOR_FULL_SKIP (2) -> retrain
training_cache.py:1130 GET_WITH_DEFAULT -> MARK: "" is trained_at_age_days' documented missing input -> 1e9 sentinel -> retrain "manifest_trained_at_unavailable"
training_cache_policy.py:40 GET_WITH_DEFAULT -> MARK: env opt-in flag (resume allowed unless set)
training_cache_policy.py:48 GET_WITH_DEFAULT -> MARK: env; "0" = documented full history
training_cache_policy.py:54 GET_WITH_DEFAULT -> MARK: env; "0" = documented full history
training_cache_policy.py:59 GET_WITH_DEFAULT -> MARK: env; 7-day staleness policy default
training_cache_policy.py:61 GET_WITH_DEFAULT -> MARK: env; 14 consecutive-skip policy default
training_cache_policy.py:65 GET_WITH_DEFAULT -> MARK: env opt-in; default full refit
training_cache_policy.py:76 GET_WITH_DEFAULT -> MARK: env; checkpoint cadence config
training_cache_policy.py:103 GET_WITH_DEFAULT -> MARK: env; documented Default ON
training_cache_policy.py:110 GET_WITH_DEFAULT -> MARK: env; early-stop noise filter config
training_cache_policy.py:123 GET_WITH_DEFAULT -> MARK: env; cache retention housekeeping
training_cache_policy.py:124 GET_WITH_DEFAULT -> MARK: env; cache prune age housekeeping
training_cache_policy.py:127 GET_WITH_DEFAULT -> MARK: env; archive ON unless disabled
training_cache_policy.py:129 GET_WITH_DEFAULT -> MARK: env; archive retention count
training_cache_policy.py:130 GET_WITH_DEFAULT -> MARK: env; archive retention age
training_provenance.py:176 GET_WITH_DEFAULT -> FIX: from_dict fabricated promotion_score 0 when no score was recorded; the promotion gate (validate_for_promotion: candidate eval-accuracy >= incumbent promotion_score) then let ANY candidate beat the incumbent. promotion_score is now Optional (None = not recorded) and validate_for_promotion refuses to compare against an incumbent with no score (reason names reconcile_pre_b_incumbent_scores, which still writes the deliberate 0.0). Also found in the same call: target_column defaulted to EXPECTED_TARGET_COLUMN (1c) - a meta lacking it read as 1c-compliant; now "" (non-compliant).
training_provenance.py:303 GET_OR_DEFAULT -> FIX: provenance_rows returned 0 when no row count recorded (and the `or` chain skipped a real 0). Now Optional[int] with explicit None checks; TrainingProvenance.rows_used Optional; validate_for_promotion refuses "rows_used not recorded".
training_provenance.py:333 GET_WITH_DEFAULT -> FIX: xgb trained_at defaulted to datetime.now() (fabricated training time) -> meta["trained_at"] (ml_train always writes it)
training_provenance.py:337 GET_WITH_DEFAULT -> FIX: xgb promotion_score default 0 -> float(meta["train_accuracy"])
training_provenance.py:354 GETATTR_DEFAULT -> FIX: dataset.timestamps (declared field). Same edit: tf fell back to CANONICAL_TIMEFRAME when the dataset recorded none (provenance asserted a timeframe it never had, passing compliance) -> dataset.training_timeframe
training_provenance.py:355 IF_TRUTHY_ELSE -> MARK: "" = TrainingProvenance's declared "not recorded" str value; only an untrainable empty dataset reaches it; no consumer parses it
training_provenance.py:356 IF_TRUTHY_ELSE -> MARK: same
training_provenance.py:372 GETATTR_DEFAULT -> FIX: dataset.n_samples (declared field)
training_provenance.py:373 GET_WITH_DEFAULT -> FIX: lstm trained_at now() default -> meta["trained_at"]
training_provenance.py:377 GET_WITH_DEFAULT -> FIX: lstm promotion_score default 0 -> float(meta["val_accuracy"])
training_provenance.py:394 IF_TRUTHY_ELSE -> MARK: same as :355 (transformer)
training_provenance.py:395 IF_TRUTHY_ELSE -> MARK: same
training_provenance.py:410 GET_WITH_DEFAULT -> FIX: transformer trained_at now() default -> meta["trained_at"]
training_provenance.py:414 GET_WITH_DEFAULT -> FIX: transformer promotion_score default 0 -> float(meta["val_accuracy"])
transformer_model.py:147 IF_TRUTHY_ELSE -> FIX: _prepare_sequence wrote volume 0.0 for a missing print, and (same dict, unflagged `or 0`) net_gamma/net_delta/gamma-wall distances/vix_level 0 for missing reads -> all stay None. (_prepare_sequence has no production caller; tests only.)
transformer_model.py:197 GET_WITH_DEFAULT -> MARK: model_version display label; same family name as the no-meta branch
transformer_train.py:377 IF_TRUTHY_ELSE -> MARK: scanner false positive - train partition vs full array
transformer_train.py:385 IF_TRUTHY_ELSE -> MARK: scanner false positive - same
transformer_train.py:479 GET_WITH_DEFAULT -> MARK: -1 impossible width -> no resume
transformer_train.py:482 GET_WITH_DEFAULT -> FIX: missing next_epoch defaulted to 1, which PASSES the 1 <= ne resume guard and loaded the checkpoint weights with an unknown epoch count; default now 0 (fails guard -> clean train), marked
transformer_train.py:487 GET_WITH_DEFAULT -> FIX: best_loss default inf -> blob["best_loss"]; KeyError lands in the existing except -> clean train
transformer_train.py:519 IF_TRUTHY_ELSE -> FIX: dead `else 0` removed (empty loader already raises on train_loss/train_total two lines later)
transformer_train.py:541 IF_TRUTHY_ELSE -> MARK: scanner false positive - early-stop streak counter
transformer_train.py:596 IF_TRUTHY_ELSE -> MARK: scanner false positive - holdout vs in-sample loader
v2_decision/a1_conformal_artifact_loader.py:53 GET_WITH_DEFAULT -> MARK: fail-closed - no ticker_universe covers no ticker -> None
v2_decision/a1_isotonic_artifact_loader.py:57 GET_WITH_DEFAULT -> MARK: same
verify_ml_pipeline.py:110 NEXT_DEFAULT -> MARK: fail-closed - {} reports every key missing -> check FAILS
verify_snapshot_pipeline.py:169 GET_WITH_DEFAULT -> MARK: GROUP BY COUNT emits no row for zero -> absent key IS 0
verify_snapshot_pipeline.py:170 GET_WITH_DEFAULT -> MARK: same
xgboost_model.py:110 GET_WITH_DEFAULT -> FIX: missing class probs filled with 0.33/0.33/0.34 and returned available=True -> requires ml_predict._require_direction_probability_triplet, else _fallback. (module has no production importer)
xgboost_model.py:111 GET_WITH_DEFAULT -> FIX: same
xgboost_model.py:112 GET_WITH_DEFAULT -> FIX: same

Tests edited: tests/test_call_engine_layer5_chunk2c.py - test_rc338_both_sides_deliver_the_authoritys_result fed {} (prob now None) against a sentinel "strong" band; now supplies a probability. Added test_readiness_missing_probability_is_unavailable_not_zero_percent and test_put_readiness_never_reads_call_side_trigger_keys.
tests/test_training_cache_layer5.py - test_load_lstm_feature_cache_accepts_valid_meta used an author-written meta missing keys the real saver always writes (it encoded the tolerant defaults); fixture now carries every saver key, plus a negative control that dropping days / n_days / training_timeframe yields a cache miss.
tests/test_arch_competition_auto_promote.py - added test_caps_promotion_gate_refuses_unrecorded_incumbent_score_and_rows.
