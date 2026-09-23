# CAPS batch 4 ledger (tools/ first half)
hits=295 FIX=132 MARK=162 SKIP=1 unresolved=0

tools/_build_institutional_audit_phase2.py:170 GET_WITH_DEFAULT -> MARK: descriptive label for a bypass vector with no text; the literal 'unknown' is shown, not a claim
tools/_build_institutional_audit_phase2.py:171 GET_WITH_DEFAULT -> MARK: fail-closed: an unclassified bypass vector is recorded as unacceptable, never as accepted
tools/_build_institutional_audit_phase2.py:182 GET_WITH_DEFAULT -> MARK: a control without a runtime flag is labelled build-time only; it never claims runtime enforcement it did not declare
tools/_build_institutional_audit_phase2.py:193 GET_WITH_DEFAULT -> MARK: display title falls back to the control id itself
tools/_build_institutional_audit_phase2.py:194 GET_WITH_DEFAULT -> MARK: fail-closed: an unvalidated control is assigned the lowest maturity L1, never a higher one
tools/_build_institutional_audit_phase2.py:196 GET_WITH_DEFAULT -> FIX: coverage_percent default 0 -> None (unmeasured, not a claimed 0%)
tools/_build_institutional_audit_phase3.py:79 GET_WITH_DEFAULT -> MARK: fail-closed: an unparsed pytest run proposes only the lowest maturity L1
tools/_build_institutional_audit_phase3.py:87 GET_WITH_DEFAULT -> MARK: fail-closed: no collected adversarial tests means bypass detection is NOT claimed
tools/_build_institutional_audit_phase3c.py:44 IF_TRUTHY_ELSE -> MARK: display summary line only; the verdict is carried by exit_code, and an empty pytest output yields an empty summary (adv_count stays 0 passed)
tools/_build_institutional_audit_phase3c.py:90 GET_WITH_DEFAULT -> MARK: fail-toward-open: an entry without a control id matches none of the control-specific closure rules, so its bypasses stay open
tools/_build_institutional_audit_phase3c.py:93 GET_WITH_DEFAULT -> MARK: fail-closed: an empty bypass path matches no closure pattern and _reconcile_bypass_path returns 'open'
tools/_build_institutional_audit_phase3c.py:96 GET_WITH_DEFAULT -> MARK: an empty bypass path cannot contain a test path, so no test can close it
tools/_build_institutional_audit_phase3c.py:142 GET_WITH_DEFAULT -> MARK: fail-closed: a route without an id has no inventory evidence and is classified still_unproven (listed in routes_with_gaps)
tools/_build_institutional_audit_phase3c.py:163 GET_WITH_DEFAULT -> MARK: every branch above writes enforcement_state; an unrecognised value counts toward no proven/blocked bucket
tools/_build_institutional_audit_phase3c.py:180 GET_WITH_DEFAULT -> FIX: mandatory_controls always declared by phase2 -> direct (missing no longer reads as 'no controls required')
tools/_build_institutional_audit_phase3c.py:284 GET_WITH_DEFAULT -> FIX: reconciliation counts always written -> direct
tools/_build_institutional_audit_phase3c.py:285 GET_WITH_DEFAULT -> FIX: direct
tools/_issue16_verify_row_match.py:37 CAST_OR_DEFAULT -> FIX: NULL pts coerced to 0 so NULL vs 0.0 'matched' -> _pts_match (both NULL match, one NULL mismatches)
tools/_issue16_verify_row_match.py:38 CAST_OR_DEFAULT -> FIX: same
tools/_multi_timeframe_audit_v1.py:87 IF_TRUTHY_ELSE -> FIX: min 0 with no rows -> None
tools/_multi_timeframe_audit_v1.py:89 IF_TRUTHY_ELSE -> FIX: max 0 -> None
tools/_multi_timeframe_audit_v1.py:164 IF_TRUTHY_ELSE -> FIX: min_rows_any_day 0 -> None
tools/_multi_timeframe_audit_v1.py:165 IF_TRUTHY_ELSE -> FIX: max_rows_any_day 0 -> None
tools/_phase4a_fast_count.py:62 IF_TRUTHY_ELSE -> FIX: pct 0 with zero trusted rows -> None (marked)
tools/_phase4a_quantify_anchor_miss.py:67 IF_TRUTHY_ELSE -> FIX: pct 0 -> None (marked)
tools/_phase4a_quantify_anchor_miss.py:70 IF_TRUTHY_ELSE -> FIX: pct 0 -> None (marked)
tools/_phase8_remediate_tmp.py:18 GET_WITH_DEFAULT -> MARK: optional exclusion list in the phase8 artifact; absent means no family/horizon is excluded
tools/_phase8_remediate_tmp.py:104 IF_NOT_NONE_ELSE -> MARK: sort key only; a method with no rank_diff ranks last and its None stays in methods[best]['rank_diff'], which the verdict below checks for None
tools/_sweep3_apply_silent_pass_logging.py:130 EXCEPT_RETURN_DEFAULT -> FIX: hardcoded silent_exception_pass_after: 0 -> measured by re-scanning the roster after rewrite
tools/_ticker_coverage_audit_v1.py:66 IF_TRUTHY_ELSE -> FIX: max gap 0.0 with <2 rows -> None
tools/_ticker_coverage_audit_v1.py:86 IF_TRUTHY_ELSE -> FIX: [0,0] -> None
tools/ablation_integrity.py:147 GETATTR_DEFAULT -> FIX: getattr(lstm_data,'CONFLUENCE_FEATURES',[]) -> direct (missing attr now reported via the except)
tools/ablation_integrity.py:487 GET_OR_DEFAULT -> FIX: accounting runnable_target always returned -> direct
tools/ablation_integrity.py:657 GET_OR_DEFAULT -> MARK: this check targets only the more-than-one-layer violation; a spec with no entry layers is one with no knockout columns (layers = [model_family] only when group_columns exist)
tools/ablation_static_lock_index.py:104 IF_NOT_NONE_ELSE -> MARK: every branch above assigns dbp, so the else arm is unreachable; a missing file yields db_exists False and db_resolved None
tools/adaptive_shadow_report.py:45 GET_OR_DEFAULT -> FIX: jaccard always written -> direct (missing no longer ranks as max divergence)
tools/adaptive_shadow_report.py:64 GET_OR_DEFAULT -> FIX: direct
tools/adaptive_shadow_report.py:69 GET_WITH_DEFAULT -> FIX: overlap always written -> direct
tools/adaptive_shadow_report.py:110 GET_WITH_DEFAULT -> MARK: db_snapshots._finish writes the same ftsv under both names on every finished selection; a trace with neither is treated as not tier-stop viable (the conservative reading) in this analysis-only report
tools/adaptive_shadow_report.py:256 GETATTR_DEFAULT -> MARK: argparse flag registered by register_allow_noncanonical_flag; absent means the canonical-DB guard stays on (fail-closed)
tools/anti_pattern_sweep.py:121 NEXT_DEFAULT -> SKIP: coordinator-owned gate file
tools/apply_row_retention_v1.py:68 IF_NOT_NONE_ELSE -> MARK: now_ts is a test-injection clock; production callers omit it and get the real wall clock
tools/apply_row_retention_v1.py:81 IF_TRUTHY_ELSE -> FIX: dry-run batches_run `1 if n else 0` -> n // batch_size + 1 (what the real loop runs)
tools/audit_similarity_features.py:55 GETATTR_DEFAULT -> MARK: flag from register_allow_noncanonical_flag; absent keeps the canonical-DB guard on
tools/audit_snapshot_columns.py:273 IF_TRUTHY_ELSE -> FIX: empty table gave null_pct 0.0 (fully populated) -> None; classify() refuses cull/pending verdicts on None
tools/backfill_greeks_from_chain_archive_v1.py:302 IF_TRUTHY_ELSE -> FIX: zero sampled rows gave parse_fail_share 0.0 and verdict P0_OK -> None + new verdict STOP_NO_ROWS_SAMPLED (exit 2)
tools/backfill_greeks_from_chain_archive_v1.py:404 IF_TRUTHY_ELSE -> FIX: parity 0.0 with nothing compared -> None (gate on unrounded value)
tools/backfill_greeks_from_chain_archive_v1.py:405 IF_TRUTHY_ELSE -> FIX: sign parity 0.0 -> None
tools/backfill_greeks_from_chain_archive_v1.py:502 GET_WITH_DEFAULT -> FIX: CERTIFIED report without parity returned 0.0, which P2 persisted as certified_parity in greeks_recomputed_v1_meta -> refuse (None) unless parity >= gate
tools/backfill_greeks_from_chain_archive_v1.py:664 GET_WITH_DEFAULT -> MARK: fail-closed exit code: a P2 report without a verdict exits 4
tools/bind_v4b_perf_proofs_register_retroactive.py:144 SETDEFAULT -> MARK: creates the register_link container this binder writes into
tools/bind_v4b_perf_proofs_register_retroactive.py:153 SETDEFAULT -> MARK: creates the register_link container this binder writes into
tools/bind_v4b_perf_proofs_register_retroactive.py:211 NEXT_DEFAULT -> MARK: None = no proof binds this register id; the next line skips it
tools/build_feature_assignment_matrix_v2.py:153 GET_WITH_DEFAULT -> MARK: framing matrix cell: per-horizon text, else the '*' all-horizon text, else a blank display cell (no framing written)
tools/build_feature_assignment_matrix_v2.py:374 GET_OR_DEFAULT -> MARK: blank maps to the dictionary's own 'unknown' category, which the ML_INGEST_CANDIDATE branch explicitly rejects
tools/build_feature_assignment_matrix_v2.py:375 GET_OR_DEFAULT -> MARK: blank maps to the dictionary's own 'unknown' likely_use, which routes to the conservative catalog tiers
tools/build_feature_assignment_matrix_v2.py:395 IF_TRUTHY_ELSE -> MARK: keeps the canonical leaf when no example path is supplied; no value is invented
tools/build_feature_assignment_matrix_v2.py:458 GET_OR_DEFAULT -> MARK: fail-closed cache check: an on-disk registry without a count is treated as invalid and rebuilt
tools/build_feature_assignment_matrix_v2.py:512 GET_OR_DEFAULT -> FIX: `null_pct or 100.0` turned a real 0.0 (fully populated) into 100% and dropped the column; missing now skipped explicitly (also blank priority now 'unreviewed', not 'medium')
tools/build_feature_assignment_matrix_v2.py:562 GET_WITH_DEFAULT -> FIX: registered keys always present -> direct index
tools/build_feature_assignment_matrix_v2.py:563 GET_WITH_DEFAULT -> FIX: direct index
tools/build_feature_assignment_matrix_v2.py:564 GET_WITH_DEFAULT -> FIX: direct index
tools/build_feature_assignment_matrix_v2.py:667 SETDEFAULT -> MARK: grouping: creates the lineage list to append into
tools/build_feature_assignment_matrix_v2.py:816 GET_WITH_DEFAULT -> MARK: xlsx display cell for the operator workbook; blank cell, never parsed back as data
tools/build_feature_assignment_matrix_v2.py:817 GET_WITH_DEFAULT -> MARK: xlsx display cell for the operator workbook; blank cell, never parsed back as data
tools/build_feature_assignment_matrix_v2.py:818 GET_WITH_DEFAULT -> MARK: xlsx display cell; groups without an atomic column show blank, never parsed back
tools/build_feature_assignment_matrix_v2.py:819 GET_WITH_DEFAULT -> MARK: xlsx display cell; registry-native groups carry no Schwab catalog tier, shown blank
tools/build_feature_assignment_matrix_v2.py:820 GET_WITH_DEFAULT -> MARK: xlsx display cell; blank cell, never parsed back as data
tools/build_feature_assignment_matrix_v2.py:821 GET_WITH_DEFAULT -> MARK: xlsx display cell; groups with no Schwab lineage show an empty list
tools/build_snapshot_sql_registry.py:71 GETATTR_DEFAULT -> MARK: ast.Call parsed from source always carries lineno; the default is unreachable
tools/canonical_1m_grid_validator_v1.py:46 IF_TRUTHY_ELSE -> FIX: zero scanned anchors passed the grid gate -> requires snapshots_bar_anchor_total > 0 (exit line marked)
tools/check_base_ticker_observability.py:76 IF_TRUTHY_ELSE -> MARK: exit code IS the verdict; --tickers is nargs='+' so the all() above is never vacuous
tools/check_card_direction_integrity.py:166 GET_WITH_DEFAULT -> MARK: a calibration row without the fusion bundle yields no by_horizon blocks, and every horizon triplet below is then None (absence kept), never a fabricated probability
tools/check_card_direction_integrity.py:494 SETDEFAULT -> MARK: import-time config placeholder so this read-only audit can import server helpers offline; no Schwab call is made and the value is never data
tools/check_card_direction_integrity.py:495 SETDEFAULT -> MARK: import-time config placeholder so this read-only audit can import server helpers offline; no Schwab call is made and the value is never data
tools/check_card_direction_integrity.py:496 SETDEFAULT -> MARK: import-time config placeholder so this read-only audit can import server helpers offline; no Schwab call is made and the value is never data
tools/check_card_direction_integrity.py:538 GET_OR_DEFAULT -> FIX: long_during_decline_samples always written -> direct index
tools/check_card_direction_integrity.py:549 GET_WITH_DEFAULT -> FIX: obs["tickers"] always written -> direct index
tools/check_card_direction_integrity.py:567 GET_WITH_DEFAULT -> MARK: markdown display placeholder for an older report without the field; never parsed back
tools/check_card_direction_integrity.py:578 GET_WITH_DEFAULT -> FIX: report["base_ticker_observability"]["tickers"] -> direct index
tools/check_card_direction_integrity.py:612 GET_WITH_DEFAULT -> MARK: markdown display: a block without horizon metrics prints None for the hit rate (absence shown, not a number)
tools/check_card_signal_fidelity.py:96 GET_WITH_DEFAULT -> MARK: a missing metrics block yields None (no hit rate), never a number
tools/check_card_signal_fidelity.py:97 GET_WITH_DEFAULT -> MARK: a missing metrics block yields None (no hit rate), never a number
tools/check_card_signal_fidelity.py:196 GET_WITH_DEFAULT -> FIX: integrity.get("meta", {}) -> integrity["meta"]
tools/check_db_health.py:91 IF_TRUTHY_ELSE -> FIX: empty/missing price_bars_1m passed every rule -> new COMPLETENESS check run_bars_present_check (pct line marked)
tools/check_db_health.py:97 IF_TRUTHY_ELSE -> MARK: documented field contract (max_pct 0 => any violation fails): a rate-capped rule uses pct, every other rule requires zero violations
tools/check_db_health.py:329 IF_TRUTHY_ELSE -> MARK: documented contract in the comment above: an absent DEFAULT DB (fresh clone/CI) is reported on stderr and exits 0; repo_scoreboard.row_db checks existence first and shows UNMEASURED; an explicit --db that is absent exits 2
tools/check_db_health.py:342 IF_TRUTHY_ELSE -> MARK: exit code IS the verdict: 1 when any check failed
tools/check_db_health.py:358 IF_TRUTHY_ELSE -> MARK: exit code IS the verdict: 1 when any check failed
tools/check_env_override_hardening.py:98 GET_WITH_DEFAULT -> MARK: env flag; unset CI means not a CI run
tools/check_env_override_hardening.py:100 GET_WITH_DEFAULT -> MARK: explicit opt-in flag; unset keeps production rules
tools/check_env_override_hardening.py:104 GET_WITH_DEFAULT -> MARK: register O-06 contract: the serving process marks itself with ED_SERVING_PROCESS=1; unset means not the serving process
tools/check_eol_style_invariant.py:199 IF_TRUTHY_ELSE -> MARK: documented --measure mode reports violations without failing; the enforcing (staged) mode exits 1
tools/check_field_naming_consistency.py:127 IF_TRUTHY_ELSE -> MARK: argparse help text only (docstring stripped under -OO)
tools/check_institutional_correctness.py:78 GETATTR_DEFAULT -> MARK: ast.parse on 3.8+ always sets end_lineno on FunctionDef; the fallback only narrows the span to the def line, never widens it
tools/check_institutional_correctness.py:187 GETATTR_DEFAULT -> MARK: duck typing: only def/class nodes have decorator_list; any other node truly has no decorators
tools/check_institutional_correctness.py:825 GETATTR_DEFAULT -> MARK: ast.Dict parsed from source always carries lineno; the default is unreachable for parsed nodes
tools/check_institutional_correctness.py:827 IF_TRUTHY_ELSE -> MARK: module-level dict literal has no enclosing function; the justification marker is looked up in the surrounding lines instead
tools/check_institutional_correctness.py:919 GETATTR_DEFAULT -> MARK: ast.parse on 3.8+ always sets end_lineno on FunctionDef; the fallback narrows the marker search span (fail-closed)
tools/check_institutional_correctness.py:987 IF_TRUTHY_ELSE -> MARK: subprocess args may be positional or args=; when neither exists first is None and the isinstance check returns False
tools/check_institutional_correctness.py:1078 GETATTR_DEFAULT -> MARK: ast.Dict parsed from source always carries lineno; the default is unreachable for parsed nodes
tools/check_institutional_correctness.py:1083 GETATTR_DEFAULT -> MARK: ast.parse on 3.8+ always sets end_lineno on FunctionDef; used only to match the span computed by _enclosing_func_span with the same rule
tools/check_institutional_correctness.py:1088 IF_TRUTHY_ELSE -> MARK: module-level call has no enclosing function; the marker is looked up on the call's own line instead
tools/check_institutional_correctness.py:1237 GETATTR_DEFAULT -> MARK: parsed statement/expression nodes always carry lineno; the default is unreachable for parsed nodes
tools/check_institutional_correctness.py:1238 GETATTR_DEFAULT -> MARK: fallback narrows the marker search to the start line (fail-closed: fewer lines, fewer escapes)
tools/check_institutional_correctness.py:1908 NEXT_DEFAULT -> MARK: None means no timeout= keyword, and the very next line raises a Violation for it (fail-closed)
tools/check_institutional_correctness.py:2613 GET_WITH_DEFAULT -> FIX: rep.get("faucet_violations", []) -> rep["faucet_violations"] (a malformed faucet report no longer passes the gate as zero violations)
tools/check_institutional_correctness.py:3240 GET_WITH_DEFAULT -> MARK: fail-closed: a registry without producers yields an empty set, so every level-domain route is reported as an unregistered producer
tools/check_live_path_is_main.py:74 IF_TRUTHY_ELSE -> MARK: message text only; git gave no stderr, and rc carries the failure
tools/check_one_faucet_live.py:320 IF_TRUTHY_ELSE -> FIX: partial endpoint outage still returned PASS -> exit 2 / INCOMPLETE when any endpoint unreachable (both json and text modes)
tools/check_skip_ledger.py:52 GET_WITH_DEFAULT -> MARK: JUnit attribute; a blank classname yields a node id no ledger file stem matches, so the skip is reported
tools/check_skip_ledger.py:53 GET_WITH_DEFAULT -> MARK: JUnit attribute; display part of the node id, never a pass condition
tools/check_skip_ledger.py:54 GET_WITH_DEFAULT -> MARK: a skip with no message carries no PRODUCTION-DATA-ONLY marker and matches no reason_contains, so it is reported
tools/check_ui_data_integration.py:107 GET_OR_DEFAULT -> MARK: env override of the documented local console URL (127.0.0.1, not localhost)
tools/check_vendor_field_coercion.py:146 IF_TRUTHY_ELSE -> MARK: no recognisable source name -> not in SOURCE_DENYLIST, so the var is still tracked (fail-toward-flag)
tools/check_venv_parity.py:28 GET_WITH_DEFAULT -> MARK: documented bootstrap escape env flag; unset keeps the parity check on
tools/daily_system_health_check.py:99 GET_WITH_DEFAULT -> MARK: console display; '?' shows the count is absent, the verdict is overall_pass
tools/daily_system_health_check.py:100 GET_WITH_DEFAULT -> MARK: console display label only
tools/daily_system_health_check.py:105 IF_TRUTHY_ELSE -> MARK: exit code IS the verdict
tools/data_faucet_audit.py:440 GET_WITH_DEFAULT -> FIX: client_violations always written -> direct (missing no longer prints [OK] binds)
tools/data_faucet_audit.py:573 NEXT_DEFAULT -> MARK: CLI positional; absent uses the canonical console DB (only measure_ages reads it)
tools/db_maintenance.py:57 IF_TRUTHY_ELSE -> FIX: no checkpoint row returned (0,0,0)=success -> raise; also busy=1 now returns 5 instead of printing 'WAL truncated'
tools/db_maintenance.py:103 IF_TRUTHY_ELSE -> MARK: CLI positional; absent uses the canonical console DB
tools/duplication_audit.py:551 GETATTR_DEFAULT -> FIX: import failure returned [] (no duplicate gates) and getattr(K,'CHECKS',[]) -> live D-GATE:unmeasured finding + K.CHECKS
tools/duplication_audit.py:618 IF_TRUTHY_ELSE -> MARK: exit code IS the verdict (1 = unexempted duplication)
tools/duplication_audit.py:652 IF_TRUTHY_ELSE -> MARK: exit code IS the verdict (1 = unexempted duplication)
tools/feature_curation_gate.py:199 GET_OR_DEFAULT -> MARK: skip-reason histogram key; a non-runnable spec without a stamped reason is tallied under an explicit 'unknown' bucket, never as a real reason
tools/feature_curation_gate.py:209 GET_WITH_DEFAULT -> MARK: counter accumulation into the skip-reason histogram
tools/feature_curation_gate.py:212 GET_WITH_DEFAULT -> FIX: group_id is always present on manifest groups -> g["group_id"] (missing id no longer silently counted as non-schwab)
tools/feature_curation_gate.py:224 GET_OR_DEFAULT -> MARK: runnable_by_model is a tally built just above; no meta key means zero meta cells were counted runnable
tools/feature_curation_gate.py:292 GET_OR_DEFAULT -> MARK: fail-closed: an ok cell with no permuted-count is demoted to skipped/noop_knockout, never left ok
tools/feature_curation_gate.py:335 GET_WITH_DEFAULT -> MARK: operator overrides file: keep_all_members is an optional list; absent means no protected columns
tools/feature_curation_gate.py:337 GET_WITH_DEFAULT -> MARK: optional members list inside an overrides group; absent contributes no protected columns
tools/feature_curation_gate.py:380 IF_TRUTHY_ELSE -> FIX: total==0 fabricated 0.0 population for every column (all declared dead) -> SystemExit 'population cannot be measured'
tools/feature_curation_gate.py:471 GET_WITH_DEFAULT -> FIX: manifest.get("groups", []) -> manifest["groups"] (a manifest without groups no longer yields an empty ablation grid)
tools/feature_curation_gate.py:472 GET_WITH_DEFAULT -> FIX: sort key g.get("group_id","") -> g["group_id"]
tools/feature_curation_gate.py:643 GET_WITH_DEFAULT -> FIX: _registered_ml_columns always returns xgb/lstm_5m/lstm_1m -> direct index (missing key no longer makes knockouts silently empty)
tools/feature_curation_gate.py:655 GET_WITH_DEFAULT -> FIX: registered.get("lstm_5m", set()) -> registered["lstm_5m"]
tools/feature_curation_gate.py:657 GET_WITH_DEFAULT -> FIX: registered.get("lstm_1m", set()) -> registered["lstm_1m"]
tools/feature_curation_gate.py:746 GET_WITH_DEFAULT -> FIX: reg.get("lstm_5m", set()) -> reg["lstm_5m"]
tools/feature_curation_gate.py:747 GET_WITH_DEFAULT -> FIX: reg.get("lstm_1m", set()) -> reg["lstm_1m"]
tools/feature_curation_gate.py:1030 IF_TRUTHY_ELSE -> MARK: fail-closed self-check: if the function block is not found the empty text fails the max_rows=None assertion
tools/feature_curation_gate.py:1183 GET_WITH_DEFAULT -> MARK: env flag; unset means full-history mode is off
tools/feature_curation_gate.py:1188 GET_WITH_DEFAULT -> MARK: env override; unset falls through to the explicit else branch below
tools/feature_curation_gate.py:1307 IF_TRUTHY_ELSE -> FIX: COUNT(*) always returns a row -> int(row[0]) (dead `else 0` removed)
tools/feature_curation_gate.py:1317 GET_WITH_DEFAULT -> MARK: fail-closed: when the DB read failed the count is absent and db_ok evaluates False
tools/feature_curation_gate.py:1475 GET_WITH_DEFAULT -> FIX: horizon_slug always stamped on whole-stack cells -> cell["horizon_slug"] (no '' survivor bucket)
tools/feature_curation_gate.py:1476 GET_WITH_DEFAULT -> FIX: group_id always stamped -> cell["group_id"] (no '' survivor group)
tools/feature_curation_gate.py:1559 GET_OR_DEFAULT -> MARK: explicit 'unknown' label; only status=='complete' drives the completeness checks, so a missing status never passes them
tools/feature_curation_gate.py:1591 GET_WITH_DEFAULT -> FIX: missing preflight verdict defaulted to READY and suppressed the FAIL flag -> new FAIL PREFLIGHT_MISSING_BUT_SCORING; explicit False keeps PREFLIGHT_NOT_READY_BUT_SCORING
tools/feature_curation_gate.py:1618 GET_OR_DEFAULT -> MARK: a runnable cell without model_family lands in its own '' bucket, which makes counts unequal and raises PREPLACEMENT_UNEQUAL_MODEL_RUNNABLE rather than hiding it
tools/feature_curation_gate.py:1639 IF_TRUTHY_ELSE -> MARK: inside `if placement_mismatch:`, so the else arm is unreachable; evidence always carries a real sample
tools/feature_curation_gate.py:1659 GET_OR_DEFAULT -> MARK: fail-closed: an ok cell with no permuted-count is counted as a noop knockout and fails NOOP_KNOCKOUT_SCORED_OK
tools/feature_curation_gate.py:1673 GET_OR_DEFAULT -> MARK: a missing count is excluded here because NOOP_KNOCKOUT_SCORED_OK above already fails it as a zero-column knockout
tools/feature_curation_gate.py:1674 GET_OR_DEFAULT -> FIX: ok cell with missing log_loss_delta was counted as zero-delta -> excluded from the tally and flagged by new FAIL OK_CELL_MISSING_DELTA
tools/feature_curation_gate.py:1689 GET_OR_DEFAULT -> MARK: skip-reason rollup key; a skipped cell without a reason is tallied under an explicit 'unknown' bucket
tools/feature_curation_gate.py:1717 GET_OR_DEFAULT -> MARK: noop tally: a missing permuted-count is counted as noop (the suspicious side), consistent with NOOP_KNOCKOUT_SCORED_OK
tools/feature_curation_gate.py:1768 GET_OR_DEFAULT -> FIX: meta zero-delta tally counted missing deltas as 0.0 -> only real deltas counted
tools/feature_curation_gate.py:1769 GET_OR_DEFAULT -> MARK: a missing count is already failed as a zero-column knockout by NOOP_KNOCKOUT_SCORED_OK, so it is excluded from this knockout-with-zero-delta tally
tools/feature_curation_gate.py:1795 GET_OR_DEFAULT -> MARK: sort key only; missing count ranks as noop so the suspicious cell is traced first
tools/feature_curation_gate.py:1796 GET_OR_DEFAULT -> FIX: trace-rank zero-delta used `or 0.0` -> explicit None handling (None ranks as suspicious, no magnitude)
tools/feature_curation_gate.py:1797 GET_OR_DEFAULT -> FIX: same sort key rewritten with explicit None handling
tools/feature_curation_gate.py:1921 GET_WITH_DEFAULT -> MARK: the delta in this row is computed from multiclass_log_loss (b_ll/t_ll above), so the label is true regardless of cmp
tools/feature_curation_gate.py:1994 GET_OR_DEFAULT -> FIX: paired_rows_all_modes always written by run_stack_bundle_evaluation -> direct index (missing no longer reads as 0 paired rows)
tools/feature_curation_gate.py:2043 CAST_OR_DEFAULT -> FIX: min_paired is always set (comparisons non-empty, guarded) -> int(min_paired)
tools/feature_curation_gate.py:2121 SETDEFAULT -> MARK: env config: prefer parallel bundles unless the operator already chose one
tools/feature_curation_gate.py:2135 SETDEFAULT -> MARK: creates the run_meta container to stamp a timestamp; no value is fabricated
tools/feature_curation_gate.py:2282 SETDEFAULT -> MARK: legacy resumed cells lacked the flag; the value supplied is the spec's computed runnability, not a guess
tools/feature_curation_gate.py:2321 GET_WITH_DEFAULT -> MARK: falls back to the real spec horizon this cell was built for
tools/feature_curation_gate.py:2324 GET_WITH_DEFAULT -> MARK: status is already non-ok (skipped); the label names the failed step when prep gave no reason
tools/feature_curation_gate.py:2432 GET_WITH_DEFAULT -> MARK: falls back to the real spec horizon this cell was built for
tools/feature_curation_gate.py:2435 GET_WITH_DEFAULT -> MARK: status is already non-ok (skipped); the label names the failed step when prep gave no reason
tools/feature_curation_gate.py:2497 GET_WITH_DEFAULT -> FIX: manifest.get("groups", []) -> manifest["groups"]
tools/feature_curation_gate.py:2508 GET_WITH_DEFAULT -> FIX: reg.get(...) | reg.get(...) -> reg["lstm_5m"] | reg["lstm_1m"]
tools/feature_curation_gate.py:2511 GET_WITH_DEFAULT -> FIX: reg.get("lstm_5m", set()) -> reg["lstm_5m"]
tools/feature_curation_gate.py:2513 GET_WITH_DEFAULT -> FIX: reg.get("lstm_1m", set()) -> reg["lstm_1m"]
tools/feature_curation_gate.py:2609 GET_WITH_DEFAULT -> MARK: status is skipped; the label names the failed step when prep gave no reason
tools/feature_curation_gate.py:2653 GET_WITH_DEFAULT -> FIX: manifest.get("groups", []) -> manifest["groups"]
tools/feature_curation_gate.py:2725 GET_WITH_DEFAULT -> MARK: falls back to the real loop horizon this cell was built for
tools/feature_curation_gate.py:2728 GET_WITH_DEFAULT -> MARK: status is already non-ok (skipped); the label names the failed step when prep gave no reason
tools/feature_curation_gate.py:2863 GET_WITH_DEFAULT -> MARK: carries a prior completion stamp forward; absent stays None (not completed)
tools/feature_curation_gate.py:2905 SETDEFAULT -> MARK: creates the run_meta container to stamp a timestamp; no value is fabricated
tools/feature_curation_gate.py:2913 GET_OR_DEFAULT -> MARK: fail-closed: confirm_complete requires expected > 0, so an absent count can never read complete
tools/feature_curation_gate.py:2982 GET_OR_DEFAULT -> MARK: fail-closed: an absent scored count is < matrix_target and the authority stamp raises
tools/feature_curation_gate.py:3020 SETDEFAULT -> MARK: creates the run_meta container to stamp a timestamp; no value is fabricated
tools/feature_curation_gate.py:3672 GET_WITH_DEFAULT -> MARK: resume bookkeeping: keeps the original start when recorded, else this invocation's start is the earliest start known for the report
tools/feature_curation_gate.py:3691 GET_OR_DEFAULT -> FIX: report stamped stack_authority_cell_count=0 when the manifest (real leaf manifest) carries none -> None (pass retired from this entrypoint; not a measured 0)
tools/feature_curation_gate.py:3742 GET_WITH_DEFAULT -> MARK: env flag; unset means full-history mode is off
tools/feature_curation_gate.py:3965 GET_OR_DEFAULT -> FIX: lock without pid was treated as pid 0 (dead) and cleared, allowing a second run -> SystemExit refusing a pid-less lock
tools/feature_curation_gate.py:3996 GET_OR_DEFAULT -> FIX: status reported ablation_process_live=False for a pid-less lock -> None (unknown); no lock stays False
tools/feature_curation_gate.py:3997 IF_TRUTHY_ELSE -> FIX: same status fix (lock_live computed explicitly)
tools/feature_curation_gate.py:4257 GET_WITH_DEFAULT -> MARK: env flag read for status display; unset means survivors are not applied
tools/feature_curation_gate.py:4395 GET_WITH_DEFAULT -> MARK: env override of a documented constant floor SURVIVOR_MIN_PAIRED_ROWS_POWERED
tools/feature_curation_gate.py:4493 GET_WITH_DEFAULT -> MARK: issue-message text; falls back to the real status when no reason was given
tools/feature_curation_gate.py:4494 GET_WITH_DEFAULT -> MARK: issue-message text; falls back to the real status when no reason was given
tools/feature_curation_gate.py:4508 GET_OR_DEFAULT -> FIX: drop_group_count always written on base cells -> direct index
tools/feature_curation_gate.py:4630 GET_WITH_DEFAULT -> MARK: issue-message text; falls back to the real status when no reason was given
tools/feature_curation_gate.py:4685 GET_OR_DEFAULT -> MARK: fail-closed: an absent scored count is < matrix_target and the authority stamp raises
tools/feature_curation_gate.py:4845 SETDEFAULT -> MARK: creates the notes list container
tools/feature_curation_gate.py:4920 GET_OR_DEFAULT -> MARK: fail-closed: absent labeled_rows blocks promotion (ready=False) and the issue prints the raw None
tools/feature_curation_gate.py:4925 GET_OR_DEFAULT -> MARK: fail-closed: absent usable_days blocks promotion (ready=False)
tools/feature_curation_gate.py:4999 GET_WITH_DEFAULT -> MARK: display-only column in a printed status table; blank cell, never parsed back
tools/feature_curation_gate.py:5003 GET_WITH_DEFAULT -> MARK: display-only column in a printed status table; blank cell, never parsed back
tools/feature_curation_gate.py:5020 IF_TRUTHY_ELSE -> MARK: display label for a non-compliant bundle; the bundle is already listed under MISSING
tools/feature_curation_gate.py:5351 GET_WITH_DEFAULT -> FIX: console summary printed 0 for absent counts -> prints the real value or None
tools/feature_curation_gate.py:5352 GET_WITH_DEFAULT -> FIX: same console summary fix
tools/feature_curation_gate.py:5353 GET_WITH_DEFAULT -> FIX: same console summary fix
tools/feature_curation_gate.py:5410 GET_WITH_DEFAULT -> FIX: console print dry_run default False -> report.get('dry_run') (None if absent)
tools/final_system_validation_pre_accumulation_v1.py:90 GETATTR_DEFAULT -> MARK: flag from register_allow_noncanonical_flag; absent keeps the canonical-DB guard on
tools/find_prove_locks.py:75 GET_WITH_DEFAULT -> MARK: label in a violation message only; the row is still judged on its evidence block
tools/flip_iv_sensitivity_v1.py:79 GET_OR_DEFAULT -> MARK: admission filter: a contract without open interest is EXCLUDED from the usable set, never counted as zero OI
tools/flip_iv_sensitivity_v1.py:100 GET_OR_DEFAULT -> FIX: openInterest guaranteed > 0 by usable_contracts -> x["openInterest"] (accumulator marked)
tools/flip_iv_sensitivity_v1.py:110 IF_TRUTHY_ELSE -> FIX: oi_per_strike 0 for empty bin -> None
tools/flip_iv_sensitivity_v1.py:223 IF_TRUTHY_ELSE -> MARK: CLI positional argument; absent uses the canonical console DB path
tools/historical_backfill_enrolled_1m_v1.py:188 GET_OR_DEFAULT -> FIX: window n_candles always initialised by the run loop -> w["n_candles"]
tools/historical_backfill_enrolled_1m_v1.py:189 GET_OR_DEFAULT -> FIX: w["bars_upsert_count"]
tools/historical_backfill_enrolled_1m_v1.py:214 GET_OR_DEFAULT -> FIX: w["n_candles"]
tools/historical_backfill_enrolled_1m_v1.py:215 GET_OR_DEFAULT -> FIX: w["bars_upsert_count"]
tools/historical_backfill_enrolled_1m_v1.py:269 GET_OR_DEFAULT -> FIX: w["n_candles"]
tools/historical_backfill_enrolled_1m_v1.py:343 CAST_OR_DEFAULT -> FIX: COUNT(*) never NULL -> dead `or 0` removed
tools/historical_backfill_enrolled_1m_v1.py:346 CAST_OR_DEFAULT -> FIX: COUNT(DISTINCT) never NULL -> removed
tools/historical_backfill_enrolled_1m_v1.py:347 CAST_OR_DEFAULT -> FIX: COUNT(*) never NULL -> removed
tools/historical_backfill_enrolled_1m_v1.py:375 CAST_OR_DEFAULT -> FIX: count always int -> removed
tools/historical_backfill_enrolled_1m_v1.py:510 SETDEFAULT -> MARK: creates the window_errors list on first failure to append the real error record
tools/historical_backfill_enrolled_1m_v1.py:605 GET_WITH_DEFAULT -> MARK: fail-closed exit gate: an audit that never recorded persistence_success exits 1
tools/hook_chain.py:83 CAST_OR_DEFAULT -> MARK: a guard main() returning None follows the sys.exit(None) convention, which is exit status 0
tools/hook_chain.py:85 CAST_OR_DEFAULT -> MARK: SystemExit(None) is exit status 0 by Python's own contract
tools/hook_chain.py:92 IF_TRUTHY_ELSE -> MARK: exit code IS the verdict (2 = any member refused)
tools/ingest_1m_to_staging.py:76 GET_WITH_DEFAULT -> MARK: a bar with no timestamp yields 0, which the `bar_start <= 0: continue` guard below drops; it is never staged
tools/ingest_1m_to_staging.py:237 IF_NOT_NONE_ELSE -> MARK: MIN/MAX over an empty batch are NULL and stay None
tools/inspect_similar_set.py:55 GET_OR_DEFAULT -> FIX: missing chosen_tier became tier 0 (strictest constraints audited) -> None and audit reported not runnable
tools/inspect_similar_set.py:99 GETATTR_DEFAULT -> MARK: flag from register_allow_noncanonical_flag; absent keeps the canonical-DB guard on
tools/inspect_similar_set.py:123 GETATTR_DEFAULT -> MARK: flag from register_allow_noncanonical_flag; absent keeps the canonical-DB guard on
tools/issue19_forward_canonical_validation_v1.py:74 IF_TRUTHY_ELSE -> FIX: COUNT(*) always one row -> dead else removed
tools/issue19_forward_canonical_validation_v1.py:150 IF_TRUTHY_ELSE -> FIX: COUNT(*) always one row -> dead else removed
tools/issue19_option_a_post_validate.py:239 IF_TRUTHY_ELSE -> FIX: rescue rate 0.0 over empty population -> None
tools/issue19_option_a_post_validate.py:300 IF_TRUTHY_ELSE -> FIX: unreachable else (bucket has >=1 anchor) removed
tools/issue19_option_a_post_validate.py:301 IF_TRUTHY_ELSE -> FIX: unreachable else removed
tools/issue19_option_a_post_validate.py:302 IF_TRUTHY_ELSE -> FIX: unreachable else removed
tools/issue19_option_a_post_validate.py:303 IF_TRUTHY_ELSE -> FIX: unreachable else removed
tools/issue19_option_a_post_validate.py:311 IF_TRUTHY_ELSE -> FIX: rate 0.0 with zero anchors -> None
tools/issue19_option_a_post_validate.py:313 IF_TRUTHY_ELSE -> FIX: rate 0.0 with zero anchors -> None
tools/issue19_option_a_post_validate.py:317 IF_TRUTHY_ELSE -> FIX: mean 0.0 with zero anchors -> None
tools/issue19_option_a_post_validate.py:318 IF_TRUTHY_ELSE -> FIX: median 0.0 -> None
tools/issue19_option_a_post_validate.py:319 IF_TRUTHY_ELSE -> FIX: mean 0.0 -> None
tools/issue19_option_a_post_validate.py:320 IF_TRUTHY_ELSE -> FIX: median 0.0 -> None
tools/issue19_rehydration_range_v1.py:105 IF_NOT_NONE_ELSE -> MARK: no gap measured -> None carried through
tools/legacy/horizon_7/_phase4e_dataset_adequacy_v1.py:168 IF_TRUTHY_ELSE -> MARK: row COUNT of the top ticker; with no rows that count is genuinely 0
tools/legacy/horizon_7/_phase5_discrimination_audit_v1.py:74 IF_TRUTHY_ELSE -> MARK: an empty table has zero columns; the n == 0 branch right below returns before any statistic is computed from it
tools/legacy/horizon_7/_phase5_discrimination_audit_v1.py:222 IF_TRUTHY_ELSE -> FIX: unreachable else (n_pred>0 guarded) removed
tools/legacy/horizon_7/_phase5_discrimination_audit_v1.py:236 GET_WITH_DEFAULT -> MARK: Counter tally of actual outcomes; no key means zero rows had that outcome
tools/legacy/horizon_7/_phase5_discrimination_audit_v1.py:237 GET_WITH_DEFAULT -> MARK: Counter tally of actual outcomes; no key means zero rows had that outcome
tools/legacy/horizon_7/_phase5_discrimination_audit_v1.py:238 GET_WITH_DEFAULT -> MARK: Counter tally of actual outcomes; no key means zero rows had that outcome
tools/legacy/horizon_7/_phase5_discrimination_audit_v1.py:245 GET_WITH_DEFAULT -> FIX: cond[pcl] always has n -> direct index
tools/legacy/horizon_7/_phase5_discrimination_audit_v1.py:249 GET_WITH_DEFAULT -> MARK: Counter tally of actual outcomes; no key means zero rows had that outcome
tools/legacy/horizon_7/_phase5_discrimination_audit_v1.py:250 GET_WITH_DEFAULT -> MARK: Counter tally of actual outcomes; no key means zero rows had that outcome
tools/legacy/horizon_7/_phase5_discrimination_audit_v1.py:251 GET_WITH_DEFAULT -> MARK: Counter tally of actual outcomes; no key means zero rows had that outcome
tools/legacy/horizon_7/backfill_pred_1c_snapshots_v1.py:130 GETATTR_DEFAULT -> MARK: flag from register_allow_noncanonical_flag; absent keeps the canonical-DB guard on
tools/legacy/horizon_7/backfill_pred_1c_snapshots_v1.py:158 GETATTR_DEFAULT -> MARK: CLI option; 0 is the documented 'no chunking' setting
tools/legacy/horizon_7/build_checkpoint_provenance_bundle_v1.py:95 GET_OR_DEFAULT -> FIX: missing meta samples fabricated 0 -> min-row-exception/augmented verdicts True; now None/unknown
tools/legacy/horizon_7/build_checkpoint_provenance_bundle_v1.py:118 GET_WITH_DEFAULT -> MARK: free-text rationale column; blank when the meta file wrote no clone note (display text, not a value)
tools/legacy/horizon_7/build_checkpoint_provenance_bundle_v1.py:238 SETDEFAULT -> MARK: keeps the FIRST bare segment of the session id as its scope; later bare segments do not overwrite it
tools/legacy/horizon_7/build_checkpoint_provenance_bundle_v1.py:311 GET_WITH_DEFAULT -> MARK: absent inventory yields None (unknown), never a count
tools/legacy/horizon_7/build_checkpoint_provenance_bundle_v1.py:315 GET_WITH_DEFAULT -> FIX: policy_usable_count 0 when list absent -> None
tools/legacy/horizon_7/enforce_universal_ticker_readiness_v1.py:134 GET_WITH_DEFAULT -> FIX: policy_usable required (missing no longer published as [])
tools/legacy/horizon_7/enforce_universal_ticker_readiness_v1.py:251 IF_TRUTHY_ELSE -> FIX: coverage 0.0 with no governed rows -> None
tools/legacy/horizon_7/enforce_universal_ticker_readiness_v1.py:252 IF_TRUTHY_ELSE -> FIX: same
tools/legacy/horizon_7/run_phase11_monitoring_drift_live_readiness_v1.py:88 CAST_OR_DEFAULT -> FIX: MAX(ts_utc) NULL fabricated epoch 0.0 timestamp -> None; last_data_timestamp now None
tools/legacy/horizon_7/run_phase11_monitoring_drift_live_readiness_v1.py:89 IF_TRUTHY_ELSE -> FIX: global_last_ts 0.0 when unknown -> None; staleness inf
tools/legacy/horizon_7/run_phase11_monitoring_drift_live_readiness_v1.py:102 GET_WITH_DEFAULT -> FIX: lookup.get("lookup", {}) -> lookup["lookup"]
tools/legacy/horizon_7/run_phase11_monitoring_drift_live_readiness_v1.py:108 GET_WITH_DEFAULT -> FIX: missing expected-artifact matrix silently gave zero missing artifacts -> required key
tools/legacy/horizon_7/run_phase11_monitoring_drift_live_readiness_v1.py:109 GET_WITH_DEFAULT -> FIX: ticker_minimum_requirements optional -> .get() without fabricated []
tools/legacy/horizon_7/run_phase11_monitoring_drift_live_readiness_v1.py:125 GET_WITH_DEFAULT -> FIX: extra_artifact_count 0 when not reported -> None (also inventory-path extra/optional counts and reconciled-path load-fail count now None, not 0)
tools/legacy/horizon_7/run_phase11_monitoring_drift_live_readiness_v1.py:131 GET_WITH_DEFAULT -> FIX: phase10.get("decision_traces", []) -> required key (missing traces no longer read as 0 inference failures)
tools/legacy/horizon_7/run_phase11_monitoring_drift_live_readiness_v1.py:167 IF_TRUTHY_ELSE -> FIX: coverage 0.0 over zero rows -> None; coverage_ok treats None as failing
tools/legacy/horizon_7/run_phase11_monitoring_drift_live_readiness_v1.py:168 IF_TRUTHY_ELSE -> FIX: same (dir coverage)
tools/legacy/horizon_7/run_phase11_monitoring_drift_live_readiness_v1.py:192 GET_WITH_DEFAULT -> MARK: fail-toward-flag: a missing calibration map increments map_missing, which raises the recalibration trigger
tools/legacy/horizon_7/run_phase11_monitoring_drift_live_readiness_v1.py:194 GET_WITH_DEFAULT -> FIX: missing cal_deciles silently skipped calibration checks -> st["cal_deciles"] required
tools/legacy/horizon_7/run_phase11_monitoring_drift_live_readiness_v1.py:201 GET_WITH_DEFAULT -> FIX: signal_rate `or 0.0` -> policy["signal_rate"] required
tools/legacy/horizon_7/run_phase11_monitoring_drift_live_readiness_v1.py:202 GET_WITH_DEFAULT -> FIX: dead expression statement (signals_generated or 0) removed
tools/legacy/horizon_7/run_phase11_monitoring_drift_live_readiness_v1.py:205 GET_WITH_DEFAULT -> FIX: edge_positive_horizons required
tools/legacy/horizon_7/run_phase11_monitoring_drift_live_readiness_v1.py:206 GET_WITH_DEFAULT -> FIX: horizon n `or 0` -> required
tools/legacy/horizon_7/run_phase11_monitoring_drift_live_readiness_v1.py:208 IF_TRUTHY_ELSE -> FIX: threshold pass rate 0.0 when no labeled rows -> None
tools/legacy/horizon_7/run_phase11_monitoring_drift_live_readiness_v1.py:211 GET_WITH_DEFAULT -> FIX: signal_examples required
tools/legacy/horizon_7/run_phase11_monitoring_drift_live_readiness_v1.py:212 GET_WITH_DEFAULT -> FIX: signal_examples required
tools/legacy/horizon_7/run_phase11_monitoring_drift_live_readiness_v1.py:215 GET_WITH_DEFAULT -> FIX: hit_rate `or 0.0` -> required
tools/legacy/horizon_7/run_phase11_monitoring_drift_live_readiness_v1.py:216 GET_WITH_DEFAULT -> FIX: baseline_move_rate `or 0.0` -> required
tools/legacy/horizon_7/run_phase11_monitoring_drift_live_readiness_v1.py:217 GET_WITH_DEFAULT -> FIX: edge_delta `or 0.0` -> required (also hardcoded api/sse_health_status 'PASS' -> None: this tool never probes them)
tools/legacy/horizon_7/run_phase11_monitoring_drift_live_readiness_v1.py:218 GET_WITH_DEFAULT -> FIX: per-horizon edge_delta `or 0.0` -> required
tools/legacy/horizon_7/run_phase11_monitoring_drift_live_readiness_v1.py:225 GET_WITH_DEFAULT -> FIX: decision_traces `[]` made trace integrity vacuously True -> required key
tools/legacy/horizon_7/run_phase11_monitoring_drift_live_readiness_v1.py:237 GET_WITH_DEFAULT -> FIX: missing raw_deciles silently skipped drift test -> required
tools/legacy/horizon_7/run_phase11_monitoring_drift_live_readiness_v1.py:254 GET_WITH_DEFAULT -> FIX: ref signal_rate `or 0.0` -> required
tools/legacy/horizon_7/run_phase11_monitoring_drift_live_readiness_v1.py:264 GET_WITH_DEFAULT -> FIX: ref edge_delta `or 0.0` -> required
tools/legacy/horizon_7/run_phase11_monitoring_drift_live_readiness_v1.py:274 GET_WITH_DEFAULT -> MARK: Counter tally over the readiness matrix; no key means zero tickers carry that verdict
tools/legacy/horizon_7/run_phase11_monitoring_drift_live_readiness_v1.py:369 GET_WITH_DEFAULT -> MARK: Counter tally; zero ready tickers makes readiness_valid False (fail-closed)
