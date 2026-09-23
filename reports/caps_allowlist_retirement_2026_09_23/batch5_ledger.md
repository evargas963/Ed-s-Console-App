# CAPS batch 5 ledger (tools/, second half)

tools/legacy/horizon_7/run_phase9_decision_policy_v1.py:64 GET_WITH_DEFAULT -> FIX: missing isotonic x_thresholds became [] and _interp_piecewise returned raw prob as "calibrated"; now mapping["x_thresholds"] (KeyError on broken artifact)
tools/legacy/horizon_7/run_phase9_decision_policy_v1.py:65 GET_WITH_DEFAULT -> FIX: same for y_thresholds; mapping["y_thresholds"]
tools/legacy/horizon_7/run_phase9_decision_policy_v1.py:68 GET_WITH_DEFAULT -> FIX: missing Platt coef became 0.0 -> every row p=sigmoid(b); now mapping["coef"]
tools/legacy/horizon_7/run_phase9_decision_policy_v1.py:69 GET_WITH_DEFAULT -> FIX: missing Platt intercept became 0.0; now mapping["intercept"]
tools/legacy/horizon_7/run_phase9_decision_policy_v1.py:101 GET_WITH_DEFAULT -> FIX: missing "thresholds" in phase8 remediation artifact silently produced zero signals; producer (_phase8_remediate_tmp.py:131) always writes it, now rem["thresholds"]
tools/legacy/horizon_7/run_phase9_decision_policy_v1.py:161 GET_WITH_DEFAULT -> FIX: fabricated 1.1 threshold reported as "move_threshold"; now None when no threshold selected for (move,hz), and tier logic requires a real threshold (row stays TIER_3, same no-entry outcome, honest report)
tools/legacy/horizon_7/run_phase9_decision_policy_v1.py:177 GET_WITH_DEFAULT -> FIX: fabricated 0.60 direction threshold asserted long/short bias with no calibrated threshold; now bias only set when (dir,hz) threshold exists, direction_threshold reported None otherwise
tools/legacy/horizon_7/run_phase9_decision_policy_v1.py:185 GET_OR_DEFAULT -> FIX: NULL ts_utc became epoch 0 in signal rows (and sorted last in selection); now d["ts_utc"] (snapshots.ts_utc is the row key)
tools/legacy/horizon_7/run_phase9_decision_policy_v1.py:233 IF_TRUTHY_ELSE -> FIX: no signals reported as 0% hit rate; now None, edge_delta None, edge_positive False (verdict FAIL)
tools/legacy/horizon_7/run_phase9_decision_policy_v1.py:239 IF_TRUTHY_ELSE -> FIX: no labeled rows reported as 0% baseline (made edge look positive); now None
tools/legacy/horizon_7/run_phase9_decision_policy_v1.py:246 GET_WITH_DEFAULT -> FIX: missing excluded_family_horizon reported as "no exclusions"; producer always writes it; now rem["excluded_family_horizon"]
tools/legacy/horizon_7/run_phase9_decision_policy_v1.py:286 IF_TRUTHY_ELSE -> FIX: zero rows reported signal_rate 0.0; now None
tools/legacy/horizon_7/run_phase9_policy_remediation_v1.py:63 GET_WITH_DEFAULT -> FIX: missing isotonic x_thresholds -> identity "calibration"; now mapping["x_thresholds"]
tools/legacy/horizon_7/run_phase9_policy_remediation_v1.py:64 GET_WITH_DEFAULT -> FIX: same, mapping["y_thresholds"]
tools/legacy/horizon_7/run_phase9_policy_remediation_v1.py:69 GET_WITH_DEFAULT -> FIX: Platt coef 0.0 fabricated; mapping["coef"]
tools/legacy/horizon_7/run_phase9_policy_remediation_v1.py:70 GET_WITH_DEFAULT -> FIX: Platt intercept 0.0 fabricated; mapping["intercept"]
tools/legacy/horizon_7/run_phase9_policy_remediation_v1.py:105 GET_WITH_DEFAULT -> FIX: missing excluded_family_horizon silently re-admitted excluded dir heads; producer always writes it; now phase8r["excluded_family_horizon"]
tools/legacy/horizon_7/run_phase9_policy_remediation_v1.py:143 GET_OR_DEFAULT -> FIX: NULL ts_utc -> epoch 0 (and grouped all such rows into one top-N bucket); now d["ts_utc"]
tools/legacy/horizon_7/run_phase9_policy_remediation_v1.py:152 IF_TRUTHY_ELSE -> FIX: empty candidate set gave baseline 0.0 so every selection showed positive edge; now SystemExit with explicit message when no labeled rows
tools/legacy/horizon_7/run_phase9_policy_remediation_v1.py:163 IF_TRUTHY_ELSE -> FIX: dead else-0.0 branch (n=len(arr)>=1 inside the loop) removed; also pct.get(i, 0.0) lookups replaced by pct[i] (every cand index has a percentile)
tools/legacy/horizon_7/run_phase9_policy_remediation_v1.py:253 IF_TRUTHY_ELSE -> FIX: cand guaranteed non-empty by the baseline guard, fabricated 0.0 branch removed
tools/legacy/horizon_7/run_phase9_policy_remediation_v1.py:287 GET_WITH_DEFAULT -> FIX: producer run_phase9_decision_policy_v1 always writes sanity.move_hit_rate_on_signals; now indexed directly (foreign artifact fails loudly)
tools/legacy/horizon_7/run_phase9_policy_remediation_v1.py:288 GET_WITH_DEFAULT -> FIX: same for sanity.edge_delta
  (same-file, non-scanner-visible fixes in the same defect class: _edge_for_indices empty selection returned hit_rate 0.0 / edge_delta -baseline -> now None with _edge_beats() comparisons and EDGE_UNMEASURED_NO_SIGNALS class; direction gate's fabricated {"threshold": 0.55} fallback (2 sites) replaced by _dir_gate requiring a selected dir threshold)
tools/legacy/horizon_7/validate_movement_prediction_coverage_v1.py:86 IF_TRUTHY_ELSE -> FIX: zero governed rows reported coverage_move 0.0 (a fabricated measurement); now coverage None, verdict FAIL with reason "coverage undefined: zero governed rows"
tools/legacy/horizon_7/validate_movement_prediction_coverage_v1.py:87 IF_TRUTHY_ELSE -> FIX: same for coverage_dir
tools/liquidity_gamma_hold_horizon_experiments_v1.py:96 CAST_OR_DEFAULT -> FIX: NULL bar volume fabricated as 0.0 in the bar dict; now None (no consumer in this file reads volume)
tools/liquidity_gamma_hold_horizon_experiments_v1.py:104 IF_TRUTHY_ELSE -> FIX: unmeasurable session ATR returned 0.0 sentinel; now None, callers skip on None (and <=0)
tools/liquidity_gamma_hold_horizon_experiments_v1.py:110 IF_TRUTHY_ELSE -> FIX: same for causal ATR; _triple_barrier and the touch-hold loop treat None as unlabeled/skip
tools/liquidity_gamma_hold_horizon_experiments_v1.py:742 GET_OR_DEFAULT -> FIX: missing faucet became "unknown" bucket; _load_obs_chains always sets it, now meta["faucet"]
tools/liquidity_gamma_hold_horizon_experiments_v1.py:994 GET_WITH_DEFAULT -> MARK: defaultdict day counter; zero LONG_GAMMA days is a true count
tools/liquidity_gamma_hold_horizon_experiments_v1.py:995 GET_WITH_DEFAULT -> MARK: same, SHORT_GAMMA
tools/liquidity_gamma_hold_horizon_experiments_v1.py:996 GET_WITH_DEFAULT -> MARK: morning_full day counter
tools/liquidity_gamma_hold_horizon_experiments_v1.py:997 GET_WITH_DEFAULT -> MARK: morning_full day counter
tools/liquidity_gamma_hold_horizon_experiments_v1.py:1233 GET_WITH_DEFAULT -> FIX: markdown rendered "{}" faucet mix if key absent; the sample dict always carries faucet_counts, now s["faucet_counts"]
tools/liquidity_gamma_levels_experiment_v1.py:82 CAST_OR_DEFAULT -> FIX: NULL bar volume fabricated 0.0; now None (volume unread in this file)
tools/liquidity_gamma_levels_experiment_v1.py:90 IF_TRUTHY_ELSE -> FIX: unmeasurable session ATR 0.0 sentinel -> None; caller skips on None
tools/liquidity_gamma_levels_experiment_v1.py:96 IF_TRUTHY_ELSE -> FIX: unmeasurable causal ATR 0.0 -> None; _triple_barrier returns unlabeled on None
tools/liquidity_gamma_levels_experiment_v1.py:492 GET_OR_DEFAULT -> FIX: "unknown" faucet bucket fabricated; _load_obs_chains always sets faucet; meta["faucet"]
tools/liquidity_gamma_levels_experiment_v1.py:706 GET_WITH_DEFAULT -> FIX: markdown "{}" faucet mix on missing key; sample dict always has faucet_counts; s["faucet_counts"]
tools/liquidity_gamma_levels_experiment_v1.py:743 GET_WITH_DEFAULT -> FIX: same
tools/liquidity_gamma_levels_experiment_v1.py:768 GET_WITH_DEFAULT -> FIX: level_presence is pre-seeded with every LEVEL_KINDS key incl. GAMMA_FLIP; now indexed directly (a missing key can no longer print "0 ticker-days")
tools/liquidity_gamma_vs_ov_pull_v1.py:234 CAST_OR_DEFAULT -> FIX: strike with neither net_gex_1pct nor raw gamma became a 0-gamma strike in the IC cross-section; now skipped
tools/liquidity_gamma_vs_ov_pull_v1.py:638 GET_OR_DEFAULT -> FIX: None hit_rate coerced to 0 in PASS gate; now explicit None check (still not PASS, no coercion)
tools/liquidity_gamma_vs_ov_pull_v1.py:1264 GET_WITH_DEFAULT -> FIX: payload always carries plain_english_verdict; p["plain_english_verdict"] (no silent "—")
tools/liquidity_intraday_volume_ic_v1.py:326 IF_TRUTHY_ELSE -> FIX: missing freeze chain / strike fabricated FREEZE_OI=0; now None, _day_ic drops None pairs so the day blanks (insufficient_pairs) instead of an all-zero cross-section; drop counter renamed freeze_signals_zeroed -> freeze_signals_absent
tools/liquidity_intraday_volume_ic_v1.py:327 IF_TRUTHY_ELSE -> FIX: same for FREEZE_VOL (and FREEZE_PRODUCT None)
tools/liquidity_intraday_volume_ic_v1.py:650 GET_OR_DEFAULT -> FIX: lag_min "or 0" would record a fabricated zero lag; _load_snaps_at_or_before_T always sets int lag; meta["lag_min"]
tools/liquidity_intraday_volume_ic_v1.py:737 GET_OR_DEFAULT -> FIX: None edge_vs_placebo coerced to 0; explicit None check
tools/liquidity_oi_volume_stickiness_v1.py:102 CAST_OR_DEFAULT -> FIX: NULL bar volume fabricated 0.0; now None (no importer/consumer reads bar volume)
tools/liquidity_oi_volume_stickiness_v1.py:586 IF_TRUTHY_ELSE -> FIX: dead unused `_wins` assignment (scanner read its ternary as a default) removed
tools/liquidity_oi_volume_stickiness_v1.py:607 GET_WITH_DEFAULT -> FIX: verdict gate defaulted n_sessions to 0; summary built in main() always has it; summary["n_sessions"]
tools/liquidity_oi_volume_stickiness_v1.py:615 GET_WITH_DEFAULT -> FIX: summary["time_in_band_halves"]["halves_agree"] (always built by _half_agreement)
tools/liquidity_oi_volume_stickiness_v1.py:617 GET_WITH_DEFAULT -> FIX: n_pierce_real defaulted to 0 in the power gate; summary["n_pierce_real"]
tools/liquidity_oi_volume_stickiness_v1.py:622 GET_WITH_DEFAULT -> FIX: summary["failed_break_halves"]["halves_agree"]
tools/liquidity_oi_volume_stickiness_v1.py:633 GET_WITH_DEFAULT -> FIX: summary["time_in_band_shuffle_halves"]["halves_agree"] (also removed two dead shuf_a/shuf_b pre-assignments)
tools/liquidity_oi_volume_stickiness_v1.py:638 GET_WITH_DEFAULT -> FIX: summary["n_pierce_shuffle"]
tools/liquidity_oi_volume_stickiness_v1.py:726 GET_OR_DEFAULT -> FIX: faucet "unknown" bucket; _load_obs_chains always sets it; meta["faucet"]
tools/liquidity_oi_volume_stickiness_v1.py:1205 GET_WITH_DEFAULT -> FIX: arm_days pre-seeded for every ARM so every arm has a summary; a["n_sessions"] and arm_summaries[arm]
tools/liquidity_oi_volume_stickiness_v1.py:1215 GET_WITH_DEFAULT -> FIX: verdict placeholder "?" removed; a["verdict"] always set
tools/liquidity_oi_volume_stickiness_v1.py:1242 GET_WITH_DEFAULT -> FIX: a["pin_near_expiry_n_sessions"] always set
tools/liquidity_strike_ic_v1.py:490 CAST_OR_DEFAULT -> FIX: COUNT(*) is never NULL; dead `or 0` coercion removed
tools/liquidity_strike_ic_v1.py:537 GET_OR_DEFAULT -> FIX: faucet from _sticky._load_obs_chains always set; meta["faucet"]
tools/liquidity_strike_ic_v1.py:655 GET_OR_DEFAULT -> FIX: None edge_vs_placebo coerced to 0 in the WEAK_FAIL gate; explicit None check
tools/liquidity_strike_ic_v1.py:798 GET_WITH_DEFAULT -> FIX: result always carries raw_geometry_note; index directly (no silent empty NOTE)
tools/liquidity_strike_ic_v1.py:916 GET_OR_DEFAULT -> FIX: result always carries ranked_resid_by_mean_ic; index directly (no silently empty table)
tools/liquidity_synthesis_experiments_v1.py:91 CAST_OR_DEFAULT -> FIX: NULL bar volume fabricated 0.0; now None (volume unread)
tools/liquidity_synthesis_experiments_v1.py:121 IF_TRUTHY_ELSE -> FIX: unmeasurable session ATR 0.0 -> None; all 8 consumer checks (triple barrier, _scan_zone_touches, _scan_formed_zones, exp B/OB/FVG loops) now skip on None
tools/liquidity_synthesis_experiments_v1.py:127 IF_TRUTHY_ELSE -> FIX: same for causal ATR
tools/liquidity_synthesis_experiments_v1.py:387 GET_OR_DEFAULT -> FIX: every zone producer sets n_families; `or 0` would silently bucket a malformed event as 0-family; now e["n_families"] (event builder now z["n_families"]/z["n_tags"] too)
tools/liquidity_synthesis_experiments_v1.py:388 GET_OR_DEFAULT -> FIX: same
tools/liquidity_synthesis_experiments_v1.py:390 GET_OR_DEFAULT -> FIX: same (placebo)
tools/liquidity_synthesis_experiments_v1.py:391 GET_OR_DEFAULT -> FIX: same (placebo)
tools/liquidity_synthesis_experiments_v1.py:396 GET_OR_DEFAULT -> FIX: e["n_tags"]
tools/liquidity_synthesis_experiments_v1.py:400 GET_OR_DEFAULT -> FIX: e["n_families"]
tools/liquidity_synthesis_experiments_v1.py:401 GET_OR_DEFAULT -> FIX: e["n_families"]
tools/liquidity_synthesis_experiments_v1.py:531 GET_WITH_DEFAULT -> MARK: GROUP BY omits zero-row tickers so absent = true 0 days; min_days<20 forces BLOCKED (fail-closed)
tools/live_diag_compare.py:163 GET_WITH_DEFAULT -> FIX: redundant {} default (guarded by isinstance) removed; absent `available` flag reports layer missing (fail-closed stack check)
tools/live_diag_compare.py:164 GET_WITH_DEFAULT -> FIX: same (lstm)
tools/live_diag_compare.py:165 GET_WITH_DEFAULT -> FIX: same (transformer)
tools/live_diag_compare.py:213 GET_OR_DEFAULT -> FIX: missing alignment_state_display was normalized as a fabricated "unknown" state; now prints "alignment=ABSENT"
tools/live_diag_compare.py:247 GET_WITH_DEFAULT -> FIX: missing validation_summary printed as empty; now prints None
tools/live_diag_compare.py:264 GET_OR_DEFAULT -> MARK: ED_DIAG_BASE env var with documented local console default URL
tools/live_diag_compare.py:273 IF_TRUTHY_ELSE -> MARK: CLI positional ticker default (first anchor ticker)
tools/lp01_touch_study_v1.py:105 CAST_OR_DEFAULT -> FIX: NULL bar volume fabricated 0.0; now None. Consumer liquidity_value_engine reads volume via _positive_float_or_none (None and 0.0 both -> None), so PD_POC/VAH/VAL unchanged, row now honest
tools/migrate_snapshots_drop_retired_horizons_v1.py:314 IF_TRUTHY_ELSE -> FIX: missing PRAGMA integrity_check row became "" in the audit; now an explicit "integrity_check returned no row" verdict (still != "ok")
tools/migrate_snapshots_drop_retired_horizons_v1.py:334 IF_NOT_NONE_ELSE -> MARK: scanner false positive, else-branch is None; callers record present_* as `is not None`
tools/migrate_snapshots_drop_retired_horizons_v1.py:352 CAST_OR_DEFAULT -> FIX: PRAGMA table_info.notnull is never NULL; dead `or 0` removed
tools/migrate_snapshots_drop_retired_horizons_v1.py:354 CAST_OR_DEFAULT -> FIX: PRAGMA table_info.pk never NULL; dead `or 0` removed
tools/migrate_snapshots_drop_retired_horizons_v1.py:364 CAST_OR_DEFAULT -> FIX: col["pk"] already int from _column_dict; direct compare
tools/migrate_snapshots_drop_retired_horizons_v1.py:368 CAST_OR_DEFAULT -> FIX: col["notnull"] already int; direct truth test
tools/migrate_snapshots_drop_retired_horizons_v1.py:420 SETDEFAULT -> MARK: error-list accumulator in audit
tools/migrate_snapshots_schema_repair_v1.py:187 IF_TRUTHY_ELSE -> FIX: same integrity_check "" -> explicit anomaly string (pre/post gates compare != "ok")
tools/migrate_snapshots_schema_repair_v1.py:199 CAST_OR_DEFAULT -> FIX: PRAGMA notnull never NULL (all _column_dict inputs are PRAGMA rows); dead coercion removed
tools/migrate_snapshots_schema_repair_v1.py:201 CAST_OR_DEFAULT -> FIX: PRAGMA pk never NULL; dead coercion removed
tools/migrate_snapshots_schema_repair_v1.py:301 CAST_OR_DEFAULT -> FIX: absent table reported first_pk 0 / first_type ""; now None for both (exists False); is_repaired unchanged
tools/migrate_snapshots_schema_repair_v1.py:341 CAST_OR_DEFAULT -> FIX: SQL already COALESCE(MAX,0) (new ids start at 1 on empty table); dead Python `or 0` removed
tools/migrate_snapshots_schema_repair_v1.py:342 CAST_OR_DEFAULT -> MARK: SUM over zero rows is NULL in SQLite; empty table has a true 0 NULL ids
tools/migrate_snapshots_schema_repair_v1.py:348 CAST_OR_DEFAULT -> FIX: COUNT(*) never NULL; dead coercion removed
tools/migrate_snapshots_schema_repair_v1.py:364 CAST_OR_DEFAULT -> FIX: COUNT(*) never NULL; dead coercion removed
tools/migrate_snapshots_schema_repair_v1.py:404 CAST_OR_DEFAULT -> FIX: col["notnull"] already int; direct truth test
tools/migrate_snapshots_schema_repair_v1.py:479 GET_WITH_DEFAULT -> FIX: a missing indexes_before capture would silently DROP every non-required snapshots index during the rebuild (DB writer); main() always captures it first, now audit["indexes_before"] so a broken flow fails loudly
tools/migrate_snapshots_schema_repair_v1.py:529 SETDEFAULT -> MARK: error-list accumulator in audit
tools/mission_latch.py:277 NEXT_DEFAULT -> MARK: next(..., None); next line branches on `if hit else`
tools/mission_latch.py:331 GET_WITH_DEFAULT -> FIX: b.get("text", "") -> b.get("text"); the existing `t for t in texts if t` filter drops None, so no fabricated empty text enters the operator-halt read
tools/ml_item4_fleet_migration.py:595 GET_WITH_DEFAULT -> MARK: census counter
tools/ml_item4_fleet_migration.py:598 GET_WITH_DEFAULT -> MARK: explicit NO_PROVENANCE_FIELD bucket names the absence in the method census
tools/normalize_survivorship_anchor_json.py:19 GET_WITH_DEFAULT -> FIX: missing anchors_used made the rewrite a silent no-op that still printed "Updated"; now data["anchors_used"]
tools/operable_surface_gate.py:147 CAST_OR_DEFAULT -> MARK: SUM over zero attached rows is NULL; true count 0 of >59s gaps
tools/operable_surface_gate.py:148 CAST_OR_DEFAULT -> FIX: max_attach_gap_sec reported 0.0 (SQL COALESCE + `or 0.0`) with no attached rows; COALESCE removed, now None
tools/operable_surface_gate.py:149 CAST_OR_DEFAULT -> MARK: SUM-over-zero-rows NULL; true 0 in 29-59s band
tools/operable_surface_gate.py:164 CAST_OR_DEFAULT -> FIX: signed_gap_max_pos 0.0 fabricated (SQL COALESCE + `or 0.0`); now None when no attached rows
tools/operable_surface_gate.py:165 CAST_OR_DEFAULT -> FIX: same for signed_gap_max_neg
tools/operable_surface_gate.py:209 IF_TRUTHY_ELSE -> FIX (GATE): zero live decisions reported live_30m_rate 1.0 and G4 passed vacuously, letting the gate print OPERABLE_SURFACE_CLEAN with G4 unproven. Now live_rate None, G4 None, and verdict OPERABLE_SURFACE_G4_UNMEASURED / SENTINEL_SURFACE_G4_UNMEASURED (never *_CLEAN); label_law documents it
tools/phase2_forward_write_verify.py:184 CAST_OR_DEFAULT -> MARK: SUM over zero post-cutoff rows is NULL; true 0 negatives, row_count printed alongside
tools/phase2_forward_write_verify.py:185 CAST_OR_DEFAULT -> MARK: same (nbd)
tools/phase2a_level_lock.py:198 GETATTR_DEFAULT -> MARK: AST duck typing, non-Attribute callee has no simple name
tools/phase2a_level_lock.py:206 GETATTR_DEFAULT -> MARK: end_lineno always present on py3.8+; fallback only narrows span
tools/phase2a_level_lock.py:338 GETATTR_DEFAULT -> MARK: ast.expr always has lineno; fallback = enclosing Dict line (same location)
tools/phase2a_level_lock.py:356 GETATTR_DEFAULT -> MARK: same, owner lookup
tools/phase2a_level_lock.py:358 GETATTR_DEFAULT -> MARK: same, message location
tools/pr238_live_vendor_proof_v1.py:184 GET_WITH_DEFAULT -> MARK: scanner false positive, HTTP client.get(path, params)
tools/pr238_live_vendor_proof_v1.py:188 GET_WITH_DEFAULT -> MARK: scanner false positive, HTTP client.get
tools/pr238_live_vendor_proof_v1.py:190 GET_WITH_DEFAULT -> MARK: scanner false positive, HTTP client.get
tools/pr238_live_vendor_proof_v1.py:198 GET_WITH_DEFAULT -> MARK: scanner false positive, HTTP client.get
tools/pr238_live_vendor_proof_v1.py:219 GET_WITH_DEFAULT -> FIX: putCall "" default removed; str(None) never equals "CALL", so contracts without putCall stay excluded without a fabricated value
tools/pr238_live_vendor_proof_v1.py:267 GET_WITH_DEFAULT -> MARK: scanner false positive, HTTP client.get
tools/pr238_live_vendor_proof_v1.py:364 GET_WITH_DEFAULT -> MARK: scanner false positive, HTTP client.get
tools/pr238_live_vendor_proof_v1.py:462 GET_OR_DEFAULT -> MARK: output-dir label only; evidence JSON keeps running_sha None and sha match None
tools/probe_chain_depth_v1.py:107 GET_OR_DEFAULT -> FIX: None span coerced to 0 -> covers_5pct_span False (asserted "does not cover"); now None when either span is unmeasured
tools/process_lock_guard.py:136 NEXT_DEFAULT -> MARK: -1 sentinel index checked on the next line (`if gi < 0`)
tools/process_lock_guard.py:182 IF_TRUTHY_ELSE -> MARK: display-only message string
tools/producer_inventory_v1.py:74 GETATTR_DEFAULT -> MARK: AST duck typing, non-Name callee has no builtin name
tools/producer_inventory_v1.py:280 IF_TRUTHY_ELSE -> MARK: scanner false positive, process exit code
tools/profile_full_stack_runtime.py:421 GET_WITH_DEFAULT -> MARK: defaultdict(float) timing accumulator; never-timed = 0.0s accumulated, count printed
tools/profile_full_stack_runtime.py:483 GET_WITH_DEFAULT -> MARK: same accumulator
tools/profile_full_stack_runtime.py:484 GET_WITH_DEFAULT -> MARK: defaultdict(int) call counter
tools/rebuild_snapshots_1m_normalized_v1.py:147 GET_WITH_DEFAULT -> FIX: measure() always records snapshots_prior_net_gamma; indexed directly (refusal gate no longer relies on a falsy default)
tools/rebuild_snapshots_1m_normalized_v1.py:219 SETDEFAULT -> MARK: non-fatal DDL error list accumulator
tools/rebuild_snapshots_1m_normalized_v1.py:257 GET_WITH_DEFAULT -> FIX: prove gate before os.replace of the live DB; materialize assigned unconditionally above, now indexed
tools/rebuild_snapshots_1m_normalized_v1.py:258 GET_WITH_DEFAULT -> FIX: same, repaired_prior
tools/rebuild_snapshots_1m_normalized_v1.py:259 GET_WITH_DEFAULT -> FIX: same, repaired_count (was .get(..., 0))
tools/rebuild_snapshots_1m_normalized_v1.py:284 GET_WITH_DEFAULT -> FIX: live_prior assigned just above; indexed
tools/replay_money_path_probe.py:92 CAST_OR_DEFAULT -> FIX: COUNT(*) never NULL; dead coercion removed
tools/replay_money_path_probe.py:113 CAST_OR_DEFAULT -> FIX: same
tools/replay_money_path_probe.py:115 CAST_OR_DEFAULT -> FIX: same
tools/replay_money_path_probe.py:116 IF_NOT_NONE_ELSE -> MARK: scanner false positive, else-branch is None
tools/replay_money_path_probe.py:179 GET_WITH_DEFAULT -> MARK: absent blocker -> no reason, falls through to explicit policy_other label
tools/replay_money_path_probe.py:260 IF_TRUTHY_ELSE -> FIX: fusion object lacking `available` was reported fusion_available False (and classified fusion_unavailable); now None (unknown); no fusion object at all stays False
tools/replay_money_path_probe.py:271 GETATTR_DEFAULT -> FIX: MultiHorizonDecision.supporting_assessments is a declared list field; direct attribute
tools/replay_money_path_probe.py:311 GET_OR_DEFAULT -> FIX: data_coverage_row always sets normalized_rows_rth; indexed
tools/replay_money_path_probe.py:366 SETDEFAULT -> MARK: offline-replay import-time env placeholder, never overrides real creds
tools/replay_money_path_probe.py:367 SETDEFAULT -> MARK: same
tools/replay_money_path_probe.py:368 SETDEFAULT -> MARK: same
tools/repo_exposure_audit.py:157 GET_WITH_DEFAULT -> FIX (AUDIT): missing faucet_violations would report "violations: 0" (clean); data_faucet_audit.run always returns it, now indexed so a broken report surfaces as "unmeasurable"
tools/repo_exposure_audit.py:158 GET_WITH_DEFAULT -> FIX: same
tools/repo_exposure_audit.py:161 GET_WITH_DEFAULT -> FIX: same for stale_sources (missing would read as "no stale sources")
tools/repo_exposure_audit.py:217 IF_TRUTHY_ELSE -> MARK: explicit "(collection unavailable)" absence label
tools/repo_exposure_audit.py:270 SETDEFAULT -> MARK: elapsed-time metadata only when section did not set its own
tools/repo_scoreboard.py:112 GET_WITH_DEFAULT -> FIX (SCOREBOARD): coverage.xml without line-rate reported 0.0% OPEN; now UNMEASURED row naming the missing attribute
tools/repo_scoreboard.py:113 GET_WITH_DEFAULT -> FIX: same for branch-rate
tools/repo_scoreboard.py:146 IF_TRUTHY_ELSE -> FIX: mutation artefact with no % parsed reported 0%; now UNMEASURED
tools/repo_scoreboard.py:205 IF_TRUTHY_ELSE -> MARK: OPEN/OK state label computed from the real unwired list
tools/repo_scoreboard.py:283 IF_TRUTHY_ELSE -> FIX (SCOREBOARD): zero parsed spacing values gave pct 0 -> GRID "OK"; now UNMEASURED. Same-function defect also fixed: no static/*.html pages made PAL report 0 colours "OK" -> now both rows UNMEASURED
tools/research/d2_build_dual_label_scratch_db.py:95 IF_TRUTHY_ELSE -> MARK: scanner false positive, "flat" is the measured vertical-barrier outcome class
tools/reversion_rule_a_study_v1.py:149 IF_TRUTHY_ELSE -> FIX: dead `else 0.0` z_trigger branch removed (candidates only emitted with positive sigma)
tools/reversion_rule_a_study_v1.py:298 IF_TRUTHY_ELSE -> FIX: placebo-halted study reported n_survivors 0 / survivors []; now None (voided, status HALT_PLACEBO_EDGE), not a measured zero
tools/rth_completeness_check_v1.py:175 SETDEFAULT -> MARK: import-guard env flag (server import without lifespan), not data
tools/run_adaptive_shadow_v2_calibration.py:49 GETATTR_DEFAULT -> MARK: argparse safety flag; False keeps canonical-only restriction
tools/run_batch_universe_study.py:71 IF_TRUTHY_ELSE -> FIX: no tradable bars reported real_bar_share 0.0; now None with explicit exclusion reason real_share_unmeasured_no_tradable_bars (still not qualified)
tools/run_final_fused_vs_xgb_comparison_v1.py:120 IF_TRUTHY_ELSE -> FIX: empty sample signal_rate 0.0 made both models tie (FUSED_EQUAL vote); now NaN like sibling hit_rate, _classify_winner votes INCONCLUSIVE
tools/run_final_fused_vs_xgb_comparison_v1.py:121 IF_TRUTHY_ELSE -> FIX: no_trade_rate 1.0 fabricated on empty sample; now NaN (new line marked: scanner false positive on the complement arithmetic)
tools/run_final_fused_vs_xgb_comparison_v1.py:287 CAST_OR_DEFAULT -> FIX: NULL valid_dir coerced to 0; explicit `is not None and int(..) == 1` (same exclusion, no coercion)
tools/run_final_fused_vs_xgb_comparison_v1.py:401 GET_WITH_DEFAULT -> FIX: final_intersection set for every ML_HORIZON_SLUGS entry in the loop; indexed directly
tools/run_phase8_calibration_global_v1.py:100 GET_WITH_DEFAULT -> FIX: missing "slices" silently excluded no cloned/non-native slices; producer (legacy build_checkpoint_provenance_bundle_v1) always writes it; indexed
tools/run_phase8_calibration_global_v1.py:171 IF_TRUTHY_ELSE -> FIX: dead else-0.0 separation removed (n>=50 guarantees decile bins); empty would now raise instead of failing as a fabricated 0.0 separation
tools/run_phase8_calibration_global_v1.py:179 IF_TRUTHY_ELSE -> FIX: same for calibrated separation
tools/run_phase8_calibration_global_v1.py:192 IF_TRUTHY_ELSE -> FIX: empty shares gave max_share 0.0 -> cross_ok PASS; count_map mirrors the n>=50 rows so the branch is dead; removed so an empty map raises instead of passing the gate
tools/run_phase10_reliability_enforcement_v1.py:42 GET_WITH_DEFAULT -> FIX: mapping["x_thresholds"] (missing knots = identity calibration)
tools/run_phase10_reliability_enforcement_v1.py:43 GET_WITH_DEFAULT -> FIX: mapping["y_thresholds"]
tools/run_phase10_reliability_enforcement_v1.py:46 GET_WITH_DEFAULT -> FIX: mapping["coef"]
tools/run_phase10_reliability_enforcement_v1.py:47 GET_WITH_DEFAULT -> FIX: mapping["intercept"]
tools/run_phase10_reliability_enforcement_v1.py:73 GET_WITH_DEFAULT -> FIX: lookup_payload["lookup"] (producer enforce_universal_ticker_readiness_v1 always writes it)
tools/run_phase10_reliability_enforcement_v1.py:79 GET_WITH_DEFAULT -> FIX: phase9r["edge_positive_horizons"] (missing key would evaluate zero horizons)
tools/run_phase10_reliability_enforcement_v1.py:80 GET_WITH_DEFAULT -> FIX: phase9r["excluded_horizons"] (missing key would silently exclude nothing)
tools/run_phase10_reliability_enforcement_v1.py:84 GET_WITH_DEFAULT -> FIX: phase9["thresholds_selected"]
tools/run_phase10_reliability_enforcement_v1.py:89 GET_WITH_DEFAULT -> FIX: inventory["rows"]
tools/run_phase10_reliability_enforcement_v1.py:152 GET_OR_DEFAULT -> FIX (GATE): NULL ts coerced to 0.0 in the "now" reference; and the reference itself was max(latest-row ts), so a fleet-wide stall never tripped DATA_STALE. Now now_ts = wall clock (behavior change: off-hours runs flag DATA_STALE)
tools/run_phase10_reliability_enforcement_v1.py:168 GET_OR_DEFAULT -> FIX: ts None -> None (data_present False) and counted stale, not epoch 0
tools/run_phase10_reliability_enforcement_v1.py:197 GET_WITH_DEFAULT -> FIX: top-level final_calibration_functions/move indexed; per-hz absence still yields CALIBRATION_MAPPING_MISSING
tools/run_phase10_reliability_enforcement_v1.py:205 GET_WITH_DEFAULT -> FIX: fabricated unreachable 1.1 threshold silently dropped the horizon; now explicit THRESHOLD_MISSING failure (registered in failure_modes)
tools/run_phase10_reliability_enforcement_v1.py:215 GET_WITH_DEFAULT -> FIX: top-level final_calibration_functions/dir indexed; per-hz absence = no dir mapping
tools/run_phase10_reliability_enforcement_v1.py:219 GET_WITH_DEFAULT -> FIX: fabricated 0.55 dir threshold removed; a bias is only asserted with a selected threshold
tools/run_phase10_reliability_enforcement_v1.py:288 GET_WITH_DEFAULT -> FIX: phase9r["sanity_new_policy"]["hit_rate"] (always written)
tools/run_phase10_reliability_enforcement_v1.py:294 NEXT_DEFAULT -> MARK: next(..., None) guarded by `if rr`
tools/run_phase11_artifact_reconciliation_v1.py:28 GET_WITH_DEFAULT -> FIX: phase9["edge_positive_horizons"] (missing key = reconcile against zero horizons)
tools/run_phase11_artifact_reconciliation_v1.py:33 GET_WITH_DEFAULT -> FIX: phase8["thresholds"]
tools/run_phase11_artifact_reconciliation_v1.py:36 GET_WITH_DEFAULT -> FIX: threshold rows always carry horizon; r["horizon"] (no "" bucket)
tools/run_phase11_artifact_reconciliation_v1.py:38 GET_OR_DEFAULT -> FIX: edge_delta None coerced to 0.0 in best-threshold choice; rows always carry it, indexed
tools/run_phase11_artifact_reconciliation_v1.py:71 GET_WITH_DEFAULT -> FIX: top-level final_calibration_functions/move indexed (missing section would report has_calibration_mapping False everywhere)
tools/run_phase11_artifact_reconciliation_v1.py:73 GET_WITH_DEFAULT -> FIX: same, dir
tools/run_phase11_artifact_reconciliation_v1.py:171 GET_WITH_DEFAULT -> FIX: old_inventory["rows"]
tools/run_rth_base_capture_normalization_validation.py:70 GET_WITH_DEFAULT -> FIX (VALIDATOR): a failed COUNT (None) and a missing DB were both reported as "starved"; now db_unavailable / base_*_unmeasured vs base_*_starved (0 rows); still FAIL
tools/run_rth_base_capture_normalization_validation.py:72 GET_WITH_DEFAULT -> FIX: same for normalized
tools/run_rth_db_contention_validation.py:39 GET_OR_DEFAULT -> FIX (VALIDATOR): missing lock-wait counter read as 0 -> "RTH_VALIDATION_NOT_RUN"; now SQLITE_METRICS_MISSING failure
tools/run_rth_db_contention_validation.py:40 GET_OR_DEFAULT -> FIX: same for locked counter
tools/run_shuffled_label_control.py:148 IF_TRUTHY_ELSE -> FIX: empty train window reported range [] ; now None (no range), train_sessions 0 alongside
tools/run_with_repo_venv.py:65 GET_WITH_DEFAULT -> MARK: opt-in env flag
tools/schwab_market_derivation_catalog_v1.py:266 GETATTR_DEFAULT -> FIX: every _add caller passes an ast.expr (always located); fabricated line 0 fallback removed, node.lineno
tools/schwab_market_derivation_catalog_v1.py:267 GETATTR_DEFAULT -> FIX: same, node.col_offset
tools/schwab_minute_history_probe_v1.py:70 GETATTR_DEFAULT -> MARK: error-path print, resp may be None; exits 1
tools/schwab_oxx_validator.py:209 GET_WITH_DEFAULT -> FIX: register_id "" label -> row.get (prints None). Same-file VALIDATOR defect fixed: a missing --register CSV made both validators return [] and exit 0 ("clean" with nothing read); main now exits 2 "Missing <register>"
tools/schwab_oxx_validator.py:273 IF_TRUTHY_ELSE -> MARK: scanner false positive, exit code
tools/select_movement_thresholds_percentile_v1.py:60 IF_TRUTHY_ELSE -> FIX: dead else-0.0 (n==0 returns earlier) removed
tools/select_movement_thresholds_percentile_v1.py:138 IF_TRUTHY_ELSE -> FIX: unreachable bal=1.0 fallback removed (retained rows are all signed and non-empty); written config unaffected
tools/select_movement_thresholds_percentile_v1.py:139 IF_TRUTHY_ELSE -> FIX: unreachable maj_dir=0.5 fallback removed
tools/similarity_feature_survivorship_report.py:50 GETATTR_DEFAULT -> MARK: argparse safety flag (canonical-only default)
tools/similarity_feature_universe_report.py:125 GETATTR_DEFAULT -> MARK: same
tools/stack_validation_runner_v1.py:61 GET_WITH_DEFAULT -> FIX: main() stamps ml_horizon_slug on every manifest; indexed (no "" horizon rows)
tools/stack_validation_runner_v1.py:70 GET_WITH_DEFAULT -> FIX: same
tools/stack_validation_runner_v1.py:98 GET_WITH_DEFAULT -> FIX: same
tools/stop_guard.py:95 NEXT_DEFAULT -> MARK: next(..., None) handled by `if hit:`
tools/study_flip_span_convergence_v1.py:115 GET_WITH_DEFAULT -> FIX: empty ladder rows had share coerced to 0; now explicit None check (empty rows cannot justify a span)
tools/study_flip_span_convergence_v1.py:132 IF_TRUTHY_ELSE -> MARK: CLI positional DB path default
tools/study_lateday_atlas_v1.py:98 IF_TRUTHY_ELSE -> FIX: no rows reported split_day ""; now None
tools/study_lateday_atlas_v1.py:128 GET_WITH_DEFAULT -> MARK: absent half = true 0-row cell (grid only records halves with rows)
tools/study_lateday_atlas_v1.py:129 GET_WITH_DEFAULT -> MARK: n always set on real cells; placeholder is a true 0 count
tools/sync_schwab_field_dictionary.py:105 GETATTR_DEFAULT -> MARK: display-only "?" status label on NOT OBSERVED line
tools/sync_schwab_field_dictionary.py:160 SETDEFAULT -> MARK: empty CSV cell = "not recorded" (row predates tracking), not a date
tools/sync_schwab_field_dictionary.py:165 SETDEFAULT -> MARK: same
tools/sync_schwab_field_dictionary.py:166 SETDEFAULT -> MARK: same (last_seen)
tools/terrain_backtest_report_v1.py:579 GET_WITH_DEFAULT -> FIX: missing scorecard slice printed "n both = 0"; now "—" like the sibling rho/winner cells
tools/terrain_backtest_report_v1.py:641 GET_WITH_DEFAULT -> FIX: wall_hold_stats always returns *_excluded_breached_at_obs; indexed (RC-130 disclosure line can no longer print a fabricated 0)
tools/terrain_backtest_report_v1.py:642 GET_WITH_DEFAULT -> FIX: same
tools/terrain_backtest_report_v1.py:643 GET_WITH_DEFAULT -> FIX: same
tools/terrain_backtest_report_v1.py:644 GET_WITH_DEFAULT -> FIX: same
tools/terrain_backtest_report_v1.py:732 GET_WITH_DEFAULT -> MARK: sort key only, day-less history rows kept verbatim
tools/validate_feature_contracts.py:34 IF_TRUTHY_ELSE -> MARK: scanner false positive, exit code
tools/validate_fusion_backfill_complete_v1.py:74 IF_TRUTHY_ELSE -> FIX: zero eligible rows reported fused coverage 0.0%; now None
tools/validate_fusion_backfill_complete_v1.py:135 IF_TRUTHY_ELSE -> FIX (VALIDATOR): FULL_DATASET_RUN_WITHOUT_LIMIT was False with no summary (unknown asserted as a negative) and True when the summary merely lacked limit_debug (absence read as proof of "no limit", also feeding full_run). Now None without a summary; True only on an explicit limit_debug: null written by backfill_fusion_policy_complete_v1
tools/world_data_ingest.py:187 NEXT_DEFAULT -> MARK: next(..., None) -> _f(None) keeps close NULL, mirrors source absence

## Same-class defects fixed in batch files beyond scanner hits (no scanner line)
- tools/liquidity_intraday_volume_ic_v1.py _causal_atr_pre_T and tools/liquidity_oi_volume_stickiness_v1.py _causal_atr_pre_obs returned a 0.0 ATR sentinel when <5 ranged bars; now None, all 4 callers (intraday, stickiness, strike_ic, gamma_vs_ov) skip on None; drop counter renamed atr_zero -> atr_unmeasurable_or_zero
- tools/operable_surface_gate.py G4 vacuous pass (see line 209), tools/repo_scoreboard.py PAL row with no pages, tools/schwab_oxx_validator.py missing --register exit 0, tools/run_phase10 wall-clock staleness, tools/legacy/horizon_7/run_phase9_policy_remediation_v1.py _edge_for_indices / 0.55 dir fallback -- detailed on their hit lines above
