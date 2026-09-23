# CAPS batch 7 ledger (calibration/) — line numbers are the ORIGINAL hit lines

calibration/analyze_phase3.py:144 GET_WITH_DEFAULT -> FIX: gate["snapshots_rows_non_canonical_timeframe_in_db"]; snapshots_1m_labeled_counts always emits it, the 0 default would have reported "0 non-1m rows ignored" on schema drift (provenance count).
calibration/analyze_phase3.py:212 GET_WITH_DEFAULT -> FIX: out["reliability_by_canonical_confidence"]; analyze() initialises it, a dropped section would have reported 0 insufficient buckets in statistical_integrity.
calibration/analyze_phase3.py:214 GET_WITH_DEFAULT -> FIX: out["regime_buckets"] (same reason).
calibration/analyze_phase3.py:216 GET_WITH_DEFAULT -> FIX: out["model_by_regime_buckets"] (same reason).
calibration/analyze_phase3.py:220 GET_WITH_DEFAULT -> FIX: out["probability_bucket_expectancy_5c_pts"] (same reason).
calibration/analyze_phase3.py:226 GET_WITH_DEFAULT -> FIX: iterate sf["by_combined_conviction"] only when the fallback ran (sf truthy); _snapshot_fallback always emits the key.
calibration/analyze_phase3.py:485 GET_WITH_DEFAULT -> FIX: data["statistical_integrity"]["binary_pass"]; both analyze() return paths set it.
calibration/analyze_phase3.py:490 GET_WITH_DEFAULT -> FIX: same direct index for the exit code.
calibration/analyze_phase4.py:92 GET_WITH_DEFAULT -> FIX: out["decision_performance_from_log"]; analyze() initialises it (insufficient-bucket count).
calibration/analyze_phase4.py:117 SETDEFAULT -> FIX: out["notes"].append; analyze() initialises notes.
calibration/analyze_phase4.py:355 GET_WITH_DEFAULT -> FIX: snap_counts[...] for all three provenance counts (347/350/355 — two sibling .get(...,0) the scanner missed on split lines also fixed); snapshots_1m_labeled_counts always emits them.
calibration/analyze_phase4.py:393 GET_WITH_DEFAULT -> FIX: data["statistical_integrity"]["binary_pass"].
calibration/analyze_phase4.py:398 GET_WITH_DEFAULT -> FIX: same for exit code.
calibration/anchor_audit.py:478 GET_WITH_DEFAULT -> FIX: cal_detail["trusted_rows_without_anchor"]; the 0 default fed binary_pass = cal_miss == 0, i.e. a missing miss-count PASSED the anchor gate.
calibration/anchor_audit.py:520 IF_TRUTHY_ELSE -> FIX+MARK: --sample 0 is documented as "full table scan" but max(1, 0) silently ran a 1-row sample (a 1-row audit could pass); now sample<=0 means full scan. Remaining `None if full_scan else args.sample` marked: None is run_anchor_audit's explicit no-LIMIT contract.
calibration/audit_phase1.py:268 CAST_OR_DEFAULT -> FIX: int(oc["n"]) (COUNT(*) never NULL).
calibration/audit_phase1.py:273 CAST_OR_DEFAULT -> FIX: inside the n>=30 gate SUM(CASE) is non-NULL; float(oc["o1_null"]) / n.
calibration/audit_phase1.py:274 CAST_OR_DEFAULT -> FIX: same (o5_null).
calibration/audit_phase1.py:275 CAST_OR_DEFAULT -> FIX: same (o15_null).
calibration/audit_phase1.py:276 CAST_OR_DEFAULT -> FIX: same (o60_null).
calibration/audit_phase1.py:313 CAST_OR_DEFAULT -> FIX: int(st["n"]) (COUNT(*)). Sibling int(weird["c"] or 0) / int(weird2["c"] or 0) (COUNT, unflagged split lines) also fixed.
calibration/audit_phase1.py:316 CAST_OR_DEFAULT -> FIX: nn>0 inside gate, float(st["zone_null"]) / nn.
calibration/audit_phase1.py:317 CAST_OR_DEFAULT -> FIX: same (vwap_null).
calibration/audit_phase1.py:325 CAST_OR_DEFAULT -> FIX: above_neg = int(st["above_neg"]) if nn > 0 else 0 — SUM over an empty set is NULL only when nn==0, where 0 violating rows is the exact count; a NULL with nn>0 now raises.
calibration/audit_phase1.py:326 CAST_OR_DEFAULT -> FIX: same (below_neg).
calibration/audit_phase1.py:327 CAST_OR_DEFAULT -> FIX: canonical_option_a_violation from the two explicit counts above.
calibration/backfill_et_clock_from_ts_utc_v1.py:103 IF_TRUTHY_ELSE -> FIX: int(row[0]); aggregate COUNT(*) always returns one row.
calibration/backfill_et_clock_from_ts_utc_v1.py:256 IF_TRUTHY_ELSE -> FIX: "updated": updated (only incremented under apply, so dry-run reports its true 0).
calibration/backfill_et_clock_from_ts_utc_v1.py:295 GET_OR_DEFAULT -> FIX: stats["updated"] / stats["would_update"]; backfill_table returns both on every path (budget accounting).
calibration/backfill_outcomes.py:59 IF_TRUTHY_ELSE -> FIX: int(r["n"]); COUNT(*) always one row.
calibration/build_trusted_anchor_proof_dataset.py:154 GET_WITH_DEFAULT -> FIX: explicit FAIL on rep["error"] (the early-return paths), then rep["calibration_trusted_anchor_audit"]["trusted_rows_total"]; the -1 sentinel produced a misleading "not positive" message.
calibration/daily_scoreboard.py:535 IF_TRUTHY_ELSE -> MARK: _production_tallies creates an entry for every ticker with >=1 log row; no entry = measured zero rows today.
calibration/daily_scoreboard.py:539 IF_TRUTHY_ELSE -> MARK: score loop creates a (ticker,horizon) cell on first prediction; no cell = zero predictions.
calibration/daily_scoreboard.py:540 IF_TRUTHY_ELSE -> MARK: no cell = zero predictions hence zero scored; not_scored_reason explains why.
calibration/daily_scoreboard.py:546 IF_TRUTHY_ELSE -> MARK: no tallies entry = zero log rows, so zero outcome-pending.
calibration/daily_scoreboard.py:547 IF_TRUTHY_ELSE -> MARK: no tallies entry = zero log rows, so zero fusion-unavailable.
calibration/daily_scoreboard.py:1189 GET_WITH_DEFAULT -> MARK: self-check fails closed; missing coverage_requirement -> "" -> error appended.
calibration/daily_scoreboard.py:1581 GET_WITH_DEFAULT -> FIX: float(ann["ts_lo"]) <= ts < float(ann["ts_hi"]); a bound-less annotation became an epoch-0-based window that could paint all prior history VETO/UI_MISMATCH; load_harness_annotations always sets both.
calibration/daily_scoreboard.py:1779 GET_OR_DEFAULT -> FIX: ac["combined_trade_calls"], int(comb["n_scored"]), ac["accuracy_presentation"]; a malformed all_card rendered "no scored trade calls" instead of raising.
calibration/daily_scoreboard.py:1788 GET_OR_DEFAULT -> FIX: ci_lo, ci_hi = comb["wilson_95ci"] (n_scored>0 => _wilson_ci returns a pair).
calibration/daily_scoreboard.py:1789 GET_OR_DEFAULT -> FIX: same.
calibration/daily_scoreboard.py:1794 GET_OR_DEFAULT -> FIX: same.
calibration/daily_scoreboard.py:1795 GET_OR_DEFAULT -> FIX: same.
calibration/daily_scoreboard.py:1802 GET_WITH_DEFAULT -> MARK: HTML-only text; target_threshold_validity is attached by build_daily_scoreboard, an all_card rendered without it (tests render raw _all_card_trade_metrics) must SAY validity unknown.
calibration/daily_scoreboard.py:1803 GET_WITH_DEFAULT -> FIX: pres["leading_text"] (always emitted by _all_card_trade_metrics).
calibration/db_guard.py:30 GETATTR_DEFAULT -> MARK: callers that never register --allow-noncanonical-db (calibration/validate_logging.py) have not opted in; False keeps the strict canonical-only guard.
calibration/edge_discovery.py:103 GET_WITH_DEFAULT -> FIX: boot["n"]; every _bootstrap_delta return and the len<2 stub carry n.
calibration/edge_discovery.py:575 GETATTR_DEFAULT -> MARK: provenance label; partial-like callables fall back to repr, None names the _effective_directional_signal default row_metrics uses.
calibration/edge_discovery.py:634 GETATTR_DEFAULT -> FIX: args.allow_noncanonical_db (flag registered 5 lines above).
calibration/eval_movement_targets_phase_style_v1.py:68 IF_TRUTHY_ELSE -> FIX: coverage over zero snapshots = None, not 0.0 (report metric). Also the unflagged valid_dir count now None (not 0) when the column is missing.
calibration/movement_target_phase5_discrimination_v1.py:112 IF_TRUTHY_ELSE -> FIX: outcome_move_coverage_vs_governed = None when n_gov == 0 (was 0.0).
calibration/movement_target_phase65_cleanup_v1.py:70 GET_WITH_DEFAULT -> FIX: _n = rec["metrics"]["n"] (only ACCEPTED records reach it).
calibration/movement_target_phase65_cleanup_v1.py:81 GET_WITH_DEFAULT -> FIX: _prior indexes prior_majority_accuracy (move) / conditional_majority_accuracy (dir); a missing prior was 0.0 that every accuracy beats.
calibration/movement_target_phase65_cleanup_v1.py:100 GET_WITH_DEFAULT -> FIX: b["always_move_accuracy"], b["always_no_move_accuracy"] — 0 defaults made a missing baseline a PASS of the hard filter.
calibration/movement_target_phase65_cleanup_v1.py:103 GET_WITH_DEFAULT -> FIX: b["always_up_accuracy"], b["always_down_accuracy"] (same).
calibration/movement_target_phase65_cleanup_v1.py:105 GET_WITH_DEFAULT -> FIX: b["random_accuracy_mean"] (same).
calibration/movement_target_phase65_cleanup_v1.py:112 GET_OR_DEFAULT -> FIX: int(rec["oos"]["n_oos"]).
calibration/movement_target_phase65_isolation_v1.py:164 IF_TRUTHY_ELSE -> FIX: ys_is is never empty (n>=min_n>=100, _split_is_oos keeps >=1 IS row); dropped the fabricated class-0 prior.
calibration/movement_target_phase65_isolation_v1.py:165 IF_TRUTHY_ELSE -> MARK: NaN = undefined on empty OOS; isnan -> INCONCLUSIVE, serialised None.
calibration/movement_target_phase65_isolation_v1.py:166 IF_TRUTHY_ELSE -> MARK: same.
calibration/movement_target_phase65_isolation_v1.py:175 IF_TRUTHY_ELSE -> MARK: NaN on empty half; stab_fail needs >=30 rows per half; serialised None.
calibration/movement_target_phase65_isolation_v1.py:176 IF_TRUTHY_ELSE -> MARK: same.
calibration/movement_target_phase65_isolation_v1.py:256 SETDEFAULT -> MARK: nested grouping container.
calibration/movement_target_phase65_isolation_v1.py:262 SETDEFAULT -> MARK: nested grouping container.
calibration/movement_target_phase65_isolation_v1.py:268 SETDEFAULT -> MARK: nested grouping container.
calibration/movement_target_phase65_isolation_v1.py:274 SETDEFAULT -> MARK: nested grouping container.
calibration/movement_target_phase65_isolation_v1.py:318 GET_WITH_DEFAULT -> FIX: rep["inventories"]["accepted_total"]. ALSO FIXED (found while tracing): the accepted inventory walker skipped by_horizon (one level shallower), so global ACCEPTED slices were never counted in accepted_total.
calibration/option_chain_morning_full.py:127 IF_TRUTHY_ELSE -> MARK: et_date=None is the documented current-ET-session call; real clock date, empty day still returns None.
calibration/phase65_cleanup_v1.py:71 GET_WITH_DEFAULT -> FIX: _n = rec["metrics"]["n"].
calibration/phase65_cleanup_v1.py:83 GET_WITH_DEFAULT -> FIX: rec["metrics"]["class_balance"].
calibration/phase65_cleanup_v1.py:87 GET_WITH_DEFAULT -> MARK: class_balance is dict(Counter(ys)); absent "flat" is a measured zero count.
calibration/phase65_cleanup_v1.py:102 GET_WITH_DEFAULT -> FIX: b["prior_majority_accuracy"] (0 default = missing baseline PASSED the filter).
calibration/phase65_cleanup_v1.py:104 GET_WITH_DEFAULT -> FIX: b["always_up_accuracy"].
calibration/phase65_cleanup_v1.py:106 GET_WITH_DEFAULT -> FIX: b["always_down_accuracy"].
calibration/phase65_cleanup_v1.py:108 GET_WITH_DEFAULT -> FIX: b["random_uniform_accuracy_mean"]. (b["prior_majority_class"] and rec["baselines"] also indexed.)
calibration/phase65_cleanup_v1.py:118 GET_OR_DEFAULT -> FIX: int(rec["oos"]["n_oos"]).
calibration/phase65_cleanup_v1.py:235 GET_WITH_DEFAULT -> FIX: h = rec["horizon"] (stamped by _evaluate_slice) instead of a "?" cluster label.
calibration/phase65_cleanup_v1.py:236 GET_WITH_DEFAULT -> MARK: cluster label; slices without a regime dimension group under literal "_none".
calibration/phase65_cleanup_v1.py:245 IF_TRUTHY_ELSE -> FIX: members are ACCEPTED (n>0) so tn>0; removed the 0.0 weighted-accuracy stand-in.
calibration/phase65_edge_isolation_v1.py:297 IF_TRUTHY_ELSE -> FIX: dropped fabricated "up" IS prior; ys_is never empty.
calibration/phase65_edge_isolation_v1.py:298 IF_TRUTHY_ELSE -> MARK: NaN on empty OOS -> INCONCLUSIVE, serialised None.
calibration/phase65_edge_isolation_v1.py:299 IF_TRUTHY_ELSE -> MARK: same.
calibration/phase65_edge_isolation_v1.py:304 IF_TRUTHY_ELSE -> MARK: NaN on empty half; stab_fail needs >=30 per half.
calibration/phase65_edge_isolation_v1.py:305 IF_TRUTHY_ELSE -> MARK: same.
calibration/phase65_edge_isolation_v1.py:382 IF_TRUTHY_ELSE -> MARK: slice-grouping label zone=unknown for rows without zone, evaluated as its own slice.
calibration/phase65_edge_isolation_v1.py:396 IF_TRUTHY_ELSE -> MARK: slice-grouping label regime=unknown.
calibration/phase65_edge_isolation_v1.py:529 SETDEFAULT -> MARK: grouping container.
calibration/phase65_edge_isolation_v1.py:532 SETDEFAULT -> MARK: grouping container.
calibration/phase65_edge_isolation_v1.py:666 GET_WITH_DEFAULT -> FIX: explicit None for absent/INSUFFICIENT cell, else cell["metrics"]["accuracy"].
calibration/phase65_edge_isolation_v1.py:674 IF_TRUTHY_ELSE -> FIX: tri-state mapping {True: PASS, False: FAIL, None: INSUFFICIENT}[mono] (same semantics, no truthiness).
calibration/phase65_edge_isolation_v1.py:743 GET_WITH_DEFAULT -> FIX: rep["phase65_verdict"], rep["inventories"]["accepted_total"].
calibration/phase6_edge_discovery_governed_v1.py:343 GET_OR_DEFAULT -> MARK: sort-key tiebreak; leading is-not-None element ranks None last, stored delta stays None.
calibration/phase6_edge_discovery_governed_v1.py:458 GET_OR_DEFAULT -> MARK: same.
calibration/phase6_edge_discovery_governed_v1.py:477 GET_WITH_DEFAULT -> FIX: hm["bootstrap_model_minus_long"], explicit ci_lo None check, hm["n"] (no 0 stand-ins in the edge classifier).
calibration/phase6_edge_discovery_governed_v1.py:479 GET_WITH_DEFAULT -> FIX: explicit mean_diff None check.
calibration/phase6_edge_discovery_governed_v1.py:488 GET_WITH_DEFAULT -> FIX: x["n"], x["mean_ev_model"] (every conf_curve entry carries them).
calibration/phase6_edge_discovery_governed_v1.py:544 GET_WITH_DEFAULT -> FIX: rep["meta"]["snapshots_after_anchor"]; also prints rep.get("error") so a missing final_classification is explained.
calibration/repair_anchor_coverage_pad_v1.py:85 SETDEFAULT -> MARK: skip-grouping list.
calibration/repair_anchor_coverage_pad_v1.py:91 SETDEFAULT -> MARK: skip-grouping list.
calibration/repair_anchor_coverage_pad_v1.py:137 GETATTR_DEFAULT -> FIX: args.allow_noncanonical_db (registered above).
calibration/repair_canonical_1m_edge_carry_v1.py:157 GETATTR_DEFAULT -> FIX: args.allow_noncanonical_db.
calibration/repair_canonical_1m_interior_gaps_v1.py:179 GETATTR_DEFAULT -> FIX: args.allow_noncanonical_db.
calibration/run_production_accumulation_validation.py:175 IF_TRUTHY_ELSE -> FIX: int(r[0]) (COUNT(*)).
calibration/run_production_accumulation_validation.py:283 GET_WITH_DEFAULT -> FIX: None (not -1) when the anchor-audit section is absent (error return); gate fails on None.
calibration/run_production_accumulation_validation.py:284 GET_WITH_DEFAULT -> FIX: same.
calibration/run_production_accumulation_validation.py:291 GET_WITH_DEFAULT -> FIX: bf1["skipped_ambiguous_duplicate_snapshots"].
calibration/run_production_accumulation_validation.py:292 GET_WITH_DEFAULT -> FIX (real masked defect): looked up "ambiguous_nearest_tie", a key backfill() never writes (it writes skipped_ambiguous_nearest_tie), so the 0 default made this half of backfill_first_no_ambiguity ALWAYS pass; now bf1["skipped_ambiguous_nearest_tie"].
calibration/run_production_accumulation_validation.py:294 GET_WITH_DEFAULT -> FIX: join1["verification_fail"] (pre-seeded by analyze).
calibration/run_production_accumulation_validation.py:295 GET_WITH_DEFAULT -> FIX: join1["ambiguous_exact_ts_duplicate_snapshots"].
calibration/run_production_accumulation_validation.py:297 GET_WITH_DEFAULT -> FIX: join2["verification_fail"] (binary_pass also indexed).
calibration/signal_engineering.py:229 IF_TRUTHY_ELSE -> MARK: only feeds a key-name listing; no rows -> no keys.
calibration/signal_engineering.py:230 IF_TRUTHY_ELSE -> MARK: same.
calibration/signal_engineering.py:287 GET_OR_DEFAULT -> FIX: missing utc_hour -> exclude (False), not hour 0.
calibration/signal_engineering.py:293 GET_OR_DEFAULT -> FIX (real masked defect): missing utc_hour became 0 and PASSED the 0-5 UTC window filter; now excluded.
calibration/signal_engineering.py:507 GETATTR_DEFAULT -> FIX: args.allow_noncanonical_db.
calibration/signal_layer_discrimination.py:267 IF_TRUTHY_ELSE -> MARK: zero layer policies raises the single-bucket warning flag (fails loud).
calibration/statistical_integrity.py:109 GET_OR_DEFAULT -> MARK: fail-closed leak gate; no n -> insufficient gate -> any numeric fails.
calibration/statistical_integrity.py:133 GET_WITH_DEFAULT -> MARK: leak detector; absent section has nothing to leak; producer (analyze_phase3) now indexes it directly.
calibration/statistical_integrity.py:139 GET_WITH_DEFAULT -> MARK: same.
calibration/statistical_integrity.py:145 GET_WITH_DEFAULT -> MARK: same.
calibration/statistical_integrity.py:154 GET_WITH_DEFAULT -> MARK: same.
calibration/statistical_integrity.py:163 GET_WITH_DEFAULT -> MARK: sf is {} when fallback never ran.
calibration/statistical_integrity.py:195 GET_WITH_DEFAULT -> MARK: leak detector; analyze_phase4 indexes the section directly.
calibration/statistical_integrity.py:359 GET_OR_DEFAULT -> MARK: no pearson_n -> insufficient gate -> Pearson value fails the leak check.
calibration/v2_a1_calibration.py:267 GET_WITH_DEFAULT -> MARK: [] hits the explicit "invalid isotonic model thresholds" ValueError; v2_decision/a1_isotonic_runtime turns it into None.
calibration/v2_a1_calibration.py:268 GET_WITH_DEFAULT -> MARK: same.
calibration/v2_a1_execution_ev.py:242 GET_OR_DEFAULT -> FIX: unstated fill_history_n reported as None (was a fabricated 0 in the validation record) and explicitly fails the fill-history floor.
calibration/v2_advisory_backfill.py:106 SETDEFAULT -> FIX: _set_if_absent_stamped("ts_utc") — same pass-through semantics, reconstructed value now stamped in live_ms_field_sources.
calibration/v2_advisory_backfill.py:117 SETDEFAULT -> FIX: same helper for ticker (stamped only when a value is supplied).
calibration/v2_advisory_backfill.py:118 SETDEFAULT -> FIX: decision_generation_id <- snapshot_id, now provenance-stamped.
calibration/v2_advisory_backfill.py:119 SETDEFAULT -> FIX: _server_build_ts <- snapshot ts, now provenance-stamped.
calibration/v2_advisory_backfill.py:120 SETDEFAULT -> FIX: decision_time_ms computed explicitly (None when ts unknown), stamped when supplied.
calibration/v2_advisory_backfill.py:367 GET_WITH_DEFAULT -> MARK: skip-reason counter increment.
calibration/validate_logging_e2e.py:19 SETDEFAULT -> MARK: harness enables the default-OFF writer flag for its own process; explicit operator value respected.
calibration/validate_outcome_join.py:105 IF_TRUTHY_ELSE -> MARK: SQL predicate chosen by explicit trusted_only flag.
calibration/validate_outcome_join.py:106 IF_TRUTHY_ELSE -> MARK: same.
calibration/validate_outcome_join.py:264 GET_OR_DEFAULT -> FIX: int(out["rows_pending_outcomes"]) (set from COUNT(*)).
calibration/writer.py:52 GET_WITH_DEFAULT -> MARK: blank env = no override, falls through to git-SHA fingerprint.
calibration/writer.py:118 GET_WITH_DEFAULT -> MARK: documented default-OFF opt-in; server.py:465-471 warns at boot when off.
calibration/writer.py:382 IF_NOT_NONE_ELSE -> FIX: prior_max = prior[0]; MAX() aggregate always returns one row, NULL when none.
