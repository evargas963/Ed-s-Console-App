---
name: v2.0 Pilot 1A spine landed; Pilot 1B (A2/0DTE) is next
description: v2.0 meta-framework drafted, target-locked, rationale documented, blueprint committed, Pilot 1A advisory spine implemented and live in Tier C. Pilot 1B (A2/0DTE) is the next phase under contract-first sequence.
type: project
originSessionId: 271dae5b-4d4f-416a-876c-54b093f89dc6
---
Multi-tool reconciliation between Claude and Cursor produced converged v2.0 architecture and Pilot 1A is now live as advisory spine in Tier C. 8 governance commits total.

**Commit chain on main:**

1. `3998e56` governance: repair authority chain references
2. `da7e668` governance: pause G2 pending v2 framework
3. `7c1ed1b` governance: draft v2 framework toc
4. `40dd80a` governance: record version hygiene updates (V3.1 + v1.1 admin correction)
5. `6ab4689` governance: lock v2 target architecture
6. `18c72e2` governance: draft v2 implementation planning (rationale, blueprint, Pilot 1A plan)
7. `b268765` governance: require honest v2 source indicators
8. `541f635` v2 decision: add Pilot 1A advisory spine — first code commit, +653 lines across 7 files, server.py +2 lines only (clean git add -p), 9/9 tests pass
9. `ab02e34` governance: define Pilot 1B A2 0DTE contract — single-file +267 lines; theta hard gate w/ BS approximation; signal-to-expression handoff protocol; 0DTE risk gates (pin/gamma/assignment) as soft gates AND named gaps; multi-leg explicitly out; threshold policy object IDs (`a2_quote_staleness_threshold_ms`, `a2_spread_hard_threshold`); A1/A2 coherence test required; v1.1 prereg authority clarified as not consumed by Pilot 1B.
10. `862eb5f` v2 decision: add Pilot 1B A2 baseline — 4 files, +493 lines. New `v2_decision/a2_option_expression.py` (289 lines) + 10 contract-referenced tests. A2 integrated inside `module_a_adapter.py` as `v2_decision["expression_profiles"]["A2"]` — no server.py change needed since Tier C wiring from Pilot 1A still produces v2_decision; A2 just rides inside it. Green-only commit per testing strictness policy (advisory phase). 19/19 tests passing.
11. `7671550` governance: codify v2 testing strictness policy — single-file +12 lines in `IMPLEMENTATION_BLUEPRINT_V2.md`. Rule: strictness scales with authority. Advisory phases = green-only with contract-referenced tests. Trade-impacting phases = red-green required, failing-test output captured.
12. `625db62` v2 decision: show A2 0DTE advisory card — UI card for A2 nested inside existing v2-pilot-card; "READ ONLY" chip; 4 columns (Action/Contract/Theta, Spread/Liquidity/P(underlying), gates/gaps); test asserts no buttons, source indicators visible.
13. `365fb55` v2 decision: harden A2 data gates — 5 contract-referenced hard gate tests (missing expiry, non-0DTE, missing chain proof, no side-compatible contracts, missing strike/right) + gate logic.
14. `716abe3` v2 decision: approximate missing A2 theta — Black-Scholes fallback when chain theta absent. Later superseded by Schwab field discipline (286aa65) which made BS the rare path, not the default.
15. `286aa65` v2 decision: prefer Schwab option fields — Tier A normalization fix. `chains.contract_fields()` adds theta, rho, timestamps. `realized_contract_eval.serialize_option_chain_for_eval()` preserves them. A2 theta priority: normalized → raw.theta → BS. Regression tests added.
16. `fc5dc85` governance: codify Schwab field source discipline — v2.0 §2.22 Field source classification controlled term (`schwab_native_normalized`, `schwab_native_raw_fallback`, `derived_because_schwab_does_not_provide`, `derived_fallback_because_schwab_unavailable`, `presentation_only`). Schwab inventory bound as data-plane contract. `governance/DERIVED_ANALYTICS_REGISTRY.md` (21 analytics: GEX, walls, EM, IV skew, RVOL, options flow, etc.). Audit docs updated with FIELD_SOURCE_DISAGREEMENT monitoring concept and regression-test pattern.
17. `2d47686` data: add curated Schwab field inventory — canonical txt + 2 dictionary CSVs (~7,200 lines) + README documenting capture date 2026-05-05 + regenerate procedure. Raw 468K-path master gitignored.
18. `8bb089b` calibration: add A1 conformal scaffold — sidecar; runtime `p_low`/`p_high` remain `not_implemented`.
19. `97c731c` calibration: add A1 EV bounds scaffold — sidecar; runtime `EV_lower`/`EV_upper` remain `not_implemented`.
20. `4369363` governance: register execution EV derived analytics (`market_impact_estimate`, `adverse_selection_score`, `capacity_participation_cap`).
21. `33959eb` calibration: add A1 execution-adjusted EV scaffold — sidecar; runtime `execution_adjusted_EV` remains `not_implemented`.
22. `afe2385` v2 decision: add A2 replay-label scaffold — sidecar over `realized_contract_eval` trade-log rows. 4 files, +291 lines. `contract_profit_label` registered as `derived_because_schwab_does_not_provide` with cross-reference to cleanup-queue gap `realized_contract_eval_raw_chain_reads_pending_normalization` (raw chain reads at `realized_contract_eval.py:846,961,990,1013`). Tests cite contract clauses §31/§192/§219/§265. No runtime wiring, no UI, no leaf flips.
23. `9c69cad` replay: normalize realized contract chain reads — closes raw-chain gap. 3 files, hand-rolled dict at L146-188 replaced with `chains.contract_fields()` + raw-strip wrapper `_replay_contract_fields`; `_normalize_contract_chain` applied to entry/exit chains post-parse; `_find_contract_row` returns normalized dicts. Behavioral-parity test (raw vs normalized PnL identical) and source-discipline tests (monkeypatch + accessor call assertion) added. Three fields (`underlyingSymbol`, contract-level `volume`, `expiration`) NOT promoted into `contract_fields()` because Schwab inventory does not list them at contract level — verified always-None pre-commit, no consumer breakage. Cleanup queue gap `realized_contract_eval_raw_chain_reads_pending_normalization` marked resolved.
24. `132561f` governance: draft A2 lifecycle contract — doc-only, 3 files, +205 net. New `governance/PILOT_1B_A2_LIFECYCLE_CONTRACT.md` (advisory authority block; boundary statement that neither `_simulate_exit` nor `call_engine.py` is canonical alone; 5-step sequence with explicit anti-skip clause; cadence + 6-event vocab; lifecycle conflict vocab parallel-not-mapped to entry-vs-portfolio with `lifecycle_warning_only` as advisory default; umbrella `a2_lifecycle_policy_pending` + 12 child gaps including `a2_lifecycle_legacy_exit_logic_divergence_audit_pending`; crosswalk preserves `P_lifecycle_adjusted_profit`/`timeout_policy`/`lifecycle_policy_id` without rename; 7 promotion criteria including replay-label validation and post-trade attribution coherence). Cross-references inserted into `IMPLEMENTATION_BLUEPRINT_V2.md` (L219/L293/L308) and `PILOT_1B_A2_0DTE_CONTRACT.md` (L228 area). No registry change yet — deferred until real input field lists exist (locked as Non-Goal).
25. `77032a2` governance: audit A2 static lifecycle divergence — doc-only, 2 files, +141 net. New `governance/A2_STATIC_LIFECYCLE_DIVERGENCE_AUDIT.md` (source-pinned to origin/main 132561f; by-concern coverage matrix not by-file side-by-side; 17 rows with 8-column schema; non-peer framing — `call_engine.py` = threshold/setup geometry producer, `_simulate_exit` = exit trigger / replay firing; in-scope fence for call_engine: `_stop_distance`, `_compute_rules`, `_snap_to_structural`, VIX/time-of-day adjustments; invalidation messaging adjacent-not-extracted; extraction must not silently pick winner). Lifecycle contract amended to add child gap `a2_lifecycle_eod_force_exit_logic_not_implemented` (firing-mechanism gap upstream of clock-threshold policy gap). Gatekeeping observation logged: divergence_flag column reads `false` everywhere due to strict "owner=both" schema, but two rows (missing-data behavior, output reason vocabulary) describe divergence in finding text and link to `a2_lifecycle_legacy_exit_logic_divergence_audit_pending`; future extraction commit should filter on linked_named_gap column, not divergence_flag.

26. `dcc9968` feat: add lifecycle rule core module — Commit A in 3-commit extraction sequence. 3 files, +new top-level `lifecycle_rule_core.py` with both halves: 6 threshold-derivation functions (`derive_stop_distance_pct`, `apply_vix_adjustment`, `apply_time_decay`, `apply_risk_multiplier`, `snap_target_to_structural`, `derive_target_levels`), 2 exit-firing functions (`fire_exit`, `resolve_same_bar_conflict`), 4 spec'd types + 1 unannounced `SameBarConflictResult`. 13 tests, each mapped to an audit row. No consumer rewires. Cleanup queue entry `lifecycle_rule_core_awaiting_consumers` opened transitionally. Red-green discipline applied: red = ModuleNotFoundError (structurally weak); green = 13 passed. Risk-multiplier semantics preserved per audit row 84 mandate.

27. `abb5587` refactor: rewire _simulate_exit to lifecycle_rule_core — Commit B. 2 files, `_simulate_exit` body shrank from ~115 lines to thin adapter (~40 lines). Imports `SameBarResolution`, `fire_exit`, `resolve_same_bar_conflict`. All 7 caller-read fields preserved including renamed `same_bar_stop_target_conflict`. Substantive red achieved: 2 monkeypatch delegation tests fail pre-rewire, 6 parity tests + 1 housekeeping pass. Green: 34 passed across 4 scopes. Caller `evaluate_realized_contract_trades_for_rows` untouched. Cleanup queue entry `lifecycle_rule_core_awaiting_consumers` stays open until Commit C. **Watch item:** `path_model_used` conservative-stop branch now emits `"ohlc_stop_priority_no_open_close"` — verify in Commit C pre-check that this matches legacy string and no downstream consumer reads `path_model_used` with hard string dependency.

28. `cd797e1` refactor: rewire call_engine threshold geometry to lifecycle_rule_core — Commit C. 3 files. `_stop_distance` shrank ~24→12 lines (delegates to `derive_stop_distance_pct`); `_compute_levels` delegates to `derive_target_levels`; nested `_snap_to_structural` deleted; `MAX_RR_T1`/`MAX_RR_T2` constants and `from math_exposure import STOP_*` deleted. Cleanup queue `lifecycle_rule_core_awaiting_consumers` closed with detailed verification note enumerating each concern (VIX >20/>30 thresholds, time decay, risk multiplier clamp, structural snap math). Substantive red: 2 monkeypatch delegation tests fail + 14 parity tests pass pre-rewire. Green: 29 passed (16 rewire + 13 rule core). 14 parity tests exceeded the 7-8 spec — coverage breadth strong. No pre-existing tests reference rewired functions (Cursor explicit statement, verified). Out-of-scope VIX sizing logic preserved unchanged.

**3-commit extraction sequence complete.** lifecycle_rule_core is now the canonical static lifecycle baseline, consumed by both replay (`_simulate_exit`) and live geometry (`_stop_distance`/`_compute_levels`).

**Outstanding follow-ups carried forward:**
- Audit doc patch deferred per cd797e1 commit message: `governance/A2_STATIC_LIFECYCLE_DIVERGENCE_AUDIT.md:L80` names `_compute_rules()` but actual function is `_compute_levels()`. One-line edit, doc-only.
- Named gap `a2_lifecycle_legacy_exit_logic_divergence_audit_pending` technically still open: rewires preserved divergent behaviors (missing-data: explicit-skip vs fallback; output reason vocabulary: structured vs free-text) per operator's deliberate "later, separate governed commit" anchor. Resolution awaits future behavior-change commit.

29. `9a13727` chore: prepare lifecycle sidecar runway — 3 files. Audit typo `_compute_rules → _compute_levels` fixed at both occurrences (L31 in-scope list AND L80 matrix row, bonus catch). Added `LIFECYCLE_RULE_CORE_VERSION = "0.1.0"` at lifecycle_rule_core.py:24. Single test `test_lifecycle_rule_core_version_constant_exists`. Red-green discipline. Green: 14 passed.
30. `d28ca67` v2 decision: add A2 lifecycle sidecar v0 — 3 files, posture α (honest minimal). Sidecar nested at `lifecycle.sidecar` (option b — preserves existing 7 lifecycle leaves byte-identical). Schema walker option (III) verified naturally exempt — `_walk_leaf_fields` only validates dicts containing both `value` and `source`, so governance metadata flows through. 12 fields per contract §148-163. `lifecycle_action="no_active_position"`, `lifecycle_conflict_state="lifecycle_warning_only"`, `static_rule_core_version` imported from runway constant. 11 tests citing contract clauses; substantive red (1 KeyError pre-attach). Green: 46 passed (sidecar + a2_option_expression + decision_schema). **Finding (open follow-up):** `LIFECYCLE_GAP_NAMES` tuple has 13 entries (umbrella + 12) but the contract's named-gap list now has 14 (umbrella + 13, post-77032a2 amendment). Missing: `a2_lifecycle_promotion_to_runtime_authority_not_authorized`. Test `test_a2_lifecycle_sidecar_named_gaps_match_contract_verbatim` passes despite the omission because it's self-referential against the constant rather than parsing the contract markdown. Recommended one-file follow-up to add the missing gap and harden the test.

31. `78b1cb6` fix: align A2 lifecycle sidecar gap inventory — 2 files. Added missing `a2_lifecycle_promotion_to_runtime_authority_not_authorized` to `LIFECYCLE_GAP_NAMES`. Test hardened with belt-and-suspenders: count assertion bumped 13→14 AND hardcoded contract list extended. Future drift between constant and test now loud; future drift between contract markdown and either list still requires manual reconciliation (acceptable v0 tradeoff). Substantive red: 1 failed (13≠14). Green: 46 passed.

**Lifecycle contract step 4 (advisory sidecar) complete.** Sequence steps remaining: future behavior-change commit to resolve `a2_lifecycle_legacy_exit_logic_divergence_audit_pending`; eventually step 5 — dynamic lifecycle candidate.

**Open follow-ups carried forward:**
- Named gap `a2_lifecycle_legacy_exit_logic_divergence_audit_pending` open: resolution awaits future governed behavior-change commit per operator's "later, separate" anchor.
- Sidecar gap-list contract-markdown drift: belt-and-suspenders test catches constant/test desync but not contract additions that bypass both. Manual reconciliation discipline assumed.

32. `1dbd60b` governance: amend A2 lifecycle contract for projected preview — doc-only, 1 file, +140 lines. Defines `sidecar.projected_preview` as v1 pre-entry projection surface, additive to v0 with explicit "does not wrap, rename, or move" guarantee. New sections: Current State vs Projected Preview; Projected Preview Output Shape; preview_status enum (4 values: available / not_available_no_entry_candidate / not_available_missing_inputs / policy_pending) with field-fill mapping table; preview_named_gaps with "iff preview-blocking" subset rule; 9 preview field definitions; source classification (option III walker pattern cited from d28ca67); No Silent Partial Fills discipline; Backward Compatibility (v1); Follow-Up Intent naming the parent 7-leaf deprecation as non-binding future commit. Output Shape For Future Sidecar section gained `projected_preview` as 13th listed field.

33. `0eea118` feat: implement A2 lifecycle sidecar v1 projected preview — 2 files. Predicate order: no_entry_candidate → missing_inputs → policy_pending. `available` structurally unreachable in v1 (EOD gap blocks `projected_eod_force_exit_time`); documented in code + tested as inverted. `_has_entry_candidate` checks `is_no_trade` / `execution_mode` / `option_chain_selection_proof.winner.chain_row`. Required inputs: spot, mins_elapsed_since_open, entry, direction, risk. PREVIEW_BLOCKING_GAPS = 3 entries (eod_force_exit_logic, eod_window_threshold_minutes, time_stop_force_exit_clock_threshold). Schema-walker solution: `_classified_leaf` uses `{value, source, source_classification}` with `source` always valid enum and `source_classification` a third optional key carrying contract classifications including `missing_from_ms_dict`. Risk derivation fallback: |entry-stop| if available else compute via rule core. ms_dict mutation guard + active-position guard tested. 13 new tests + 11 v0 = 24 total. Substantive red (KeyError) → green 59 passed across sidecar + a2_option_expression + decision_schema scopes.

**Sidecar v1 complete.** Lifecycle contract step 4 is now substantive (not just structural).

**Open follow-ups carried forward:**
- Named gap `a2_lifecycle_legacy_exit_logic_divergence_audit_pending` open: resolution awaits future governed behavior-change commit per operator's "later, separate" anchor.
- `available` preview state unreachable until `a2_lifecycle_eod_force_exit_logic_not_implemented` closes; that gap requires implementing EOD force-exit logic (separate future commit).
- Sidecar gap-list contract-markdown drift: belt-and-suspenders test catches constant/test desync but not contract additions that bypass both. Manual reconciliation discipline assumed.
- `source_classification` as a third leaf key: not pre-named in contract amendment 1dbd60b; renaming later requires contract amendment, not breaking change.

34. `cf85ef2` governance: define A1 conformal interval promotion contract — doc-only, 1 file. New `governance/A1_CONFORMAL_INTERVAL_PROMOTION_CONTRACT.md`. Narrow scope: `p_low`/`p_high` only (EV/execution-EV explicitly OOS). Decisions: O1 honest-evaluation gate (refuse promotion under same-holdout coverage); G3 aggregate gating with `a1_conformal_per_regime_coverage_pending` named for future; v1_approximation only (v2_compliant requires future operator decision). 6 ordered preconditions: artifact present, schema_version match, separate-post-fit coverage ≥ 0.85, aggregate sample threshold, horizon match, freshness discipline (policy object bound OR governed self-describing artifact field). 2 named gaps. No-synthetic-intervals discipline explicit (`source="v1_approximation" iff value is non-None`). Crosswalk preserves existing v1_approximation leaves + names OOS leaves. Anti-bloat clause forbids gating field/status enum/sidecar wrapper for these two leaves. p_low/p_high promote together or neither (paired-output honesty).

35. `a1d0891` governance: amend A1 conformal contract for calibrated probability and freshness fields — doc-only, 1 file, +5 changes. Added Precondition 7: `ms_dict["a1_calibrated_probability"]` ∈ [0, 1] required (path (b) — load-bearing enough to be explicit, not hidden as extraction sub-condition). Tightened Precondition 6: requires artifact-carried `governed_max_age_seconds` + `generated_at_epoch_seconds`; v1 has no external policy fallback; explicit prohibition on using `calibration_run_id`/`calibration_window_id` as freshness proxies. Test bar count 6→7. Named-gap freshness text reflects tightened path. Non-Goals add: no implicit calibration assumption + no calibration ID as freshness signal.

36. `c2eedf0` feat: promote A1 conformal probability bounds — 3 files. New `v2_decision/a1_conformal_promotion.py` with `derive_a1_conformal_bounds(ms_dict)` returning `(p_low, p_high, status)`. 7 preconditions in contract order; failure mode strings match contract verbatim (`precondition_<N>_<name>_failed`). Delegates to `apply_a1_conformal_interval` from calibration scaffold (no quantile math reimplemented). Symmetric leaves guaranteed by single function call. Belt-and-suspenders honest-evaluation: separate-evaluation-predictions source check + explicit same_rows rejection. `now` injected as parameter for testable freshness. 14 tests + 6 schema = 20 passed. Substantive red captured (delegation len(calls)==0). Pushed to origin/main.

37. `db233f4` chore: import A1 calibration sample threshold from canonical source — 2 files. Removed local `A1_CONFORMAL_AGGREGATE_HOLDOUT_MIN_SAMPLES = 500` in v2_decision/a1_conformal_promotion.py. Added function-local `from calibration.v2_a1_calibration import A1_CALIBRATION_AGGREGATE_HOLDOUT_MIN_SAMPLES` inside `_aggregate_sample_gate_passes` (function-local required for monkeypatch test pattern; also avoids reintroducing import cycle). Pre-checks: upstream value confirmed = 500 (drift-risk-only cleanup, not value bug); no test references to old constant name. Substantive red: drift test monkeypatches upstream to 1000 with artifact n=750, expects REJECT (post-fix) vs ACCEPT (pre-fix). Green: 21 passed. Branch ahead 1, not yet pushed (operator deliberately retained for review).

38. `51d3c89` governance: define A1 conformal artifact lifecycle contract — doc-only, 1 file, sub-commit 2A in track 2 (artifact lifecycle → injection chain). Filesystem JSON venue at `data/v2_calibration/conformal/<module>/<expr>/<ticker>/<horizon>/<calibration_run_id>.json`. `_current.json` pointer with atomic-rename. `generated_at_epoch_seconds` (not mtime) is freshness source — reinforced at top level. New required lifecycle fields including `calibration_lineage_id` phrased as minimum-required-semantics (uniqueness + identity), not frozen format; 2B may refine encoding but cannot weaken semantic. Loader contract surface signature-only with `now_epoch_seconds` testability hook. **Lineage discipline locked as forward-looking binding for 2B:** even if existing 7 preconditions pass, lineage match precondition (future precondition 8) is unsatisfied, so leaves stay `not_implemented`. 3 named gaps: persistence_venue_pending, calibration_lineage_match_pending, loader_implementation_pending. 2B contract filename pinned: `governance/A1_CALIBRATED_PROBABILITY_PROVENANCE_CONTRACT.md`.

39. `e2e1dbc` governance: define A1 calibrated probability provenance contract — doc-only, 1 file, sub-commit 2B. Declares `calibration.v2_a1_calibration` canonical for A1 conformal lineage. `ml_predict._apply_5c_xgb_plus_transformer_isotonic_calibration` remains production-active but non-canonical (ineligible for A1 conformal promotion unless future bridge contract). ms_dict marker `a1_calibrated_probability_lineage_id` with minimum-required-semantics phrasing matching 2A. Lineage match = exact string equality, explicit list of disallowed tolerance modes (no fuzzy, version-suffix, whitespace, case, or inferred compatibility). Future precondition 8 wording locked verbatim with binding clause against future weakening. Failure status `precondition_8_calibration_lineage_match_failed`. 3 named gaps: canonical_source_pending_implementation, lineage_id_propagation_pending_implementation, ml_predict_to_v2_calibration_bridge_pending. Test bar enumerates 5 future code-commit scenarios.

**Track 2 sub-commit progression (locked):**
- 2A: ✅ artifact lifecycle contract (51d3c89)
- 2B: ✅ calibrated-probability provenance contract (e2e1dbc)
- 2C: artifact production hookup (offline batch, code)
- 2D: runtime artifact loader (code)
- 2E: primary_horizon injection (code, possibly subsumed by existing `_apply_trader_horizon_contract`)
- 2F: ms_dict injection wiring (code, originally-proposed work)
- ✅ Follow-up: amendment commit adding precondition 8 to A1_CONFORMAL_INTERVAL_PROMOTION_CONTRACT.md (7c9e124)
- ✅ Precondition 8 implementation in `derive_a1_conformal_bounds` (5bcc138)

40. `7c9e124` governance: add precondition 8 to A1 conformal promotion contract — doc-only, 1 file, 4 changes. Inserted precondition 8 at position 8 with verbatim text from 2B §94-100 (including "even if the value happens to be in [0, 1]" clause). Test bar count seven→eight. Added test-bar bullet referencing 2B's enumeration with explicit `precondition_8_calibration_lineage_match_failed` status assertion. Added "Related contracts:" sub-section under Crosswalk with 2A + 2B references. Existing preconditions 1-7 / authority / scope / population / no-synthetic / named gaps / v2_compliant / Non-Goals all byte-identical.

41. `5bcc138` feat: enforce A1 conformal precondition 8 lineage match — 2 files. Inserted precondition 8 check between L42 and L45 of `derive_a1_conformal_bounds`. New `_lineage_match_passes` helper enforces: both strings, both non-empty, exact equality (no normalization/fuzzy/tolerance). Failure emits `precondition_8_calibration_lineage_match_failed`. 5 new tests: match passes, mismatch fails, missing marker fails, empty marker fails, plus new `ms_overrides8` parametrized case. Existing fixtures updated (α path) so all-preconditions-pass test still green. Substantive red: pre-impl old code returned `ok` for mismatched lineages; post-impl returns precondition 8 failure status. Green: 26 passed (5 new + 21 prior).

42. `7297697` governance: define A1 conformal artifact production contract — doc-only, 1 file, sub-commit 2C.0+2C.1 bundled. Locks: 10-step pipeline shape; honest evaluation = separate forward window with `eval_start >= holdout_end`; per-ticker artifacts (single-element `ticker_universe`); calibration_lineage_id format `<calibration_run_id>:<sha256(json.dumps(model, sort_keys=True, separators=(",",":")))>`; 7-criterion `_current.json` eligibility; atomic-rename promotion mechanics; manual CLI v1 cadence with explicit args (no implicit defaults). 4 named gaps: scheduler_pending, governed_max_age_seconds_policy_pending, walkforward_window_policy_pending, evaluation_window_minimum_size_policy_pending. Audit-not-promote rule: failed artifacts written to disk but not promoted to `_current.json`. Recommended max_age value 691200s (8 days) cited as starting point; operator-binding deferred. Test bar enumerates 7 future-code minimums.

**Track 2 sub-commit progression:**
- 2A ✅ (51d3c89)
- 2B ✅ (e2e1dbc)
- Precondition 8 amendment ✅ (7c9e124)
- Precondition 8 implementation ✅ (5bcc138)
- 2C.0+2C.1 production contract ✅ (7297697)
- 2C.2 ✅ (8526b59)
- 2D ✅ (fe3c8a9)
- 2E ✅ (43aad3a)
- 2F ✅ (ed18036) — artifact-only injection. Two server.py call sites (logging + response) call `attach_a1_conformal_artifact_to_ms_dict`. Honest scope: NOT injecting `a1_calibrated_probability` or `a1_calibrated_probability_lineage_id` because canonical calibration source not yet wired. Preconditions 7/8 fail honestly until track 3 wires v2_a1_calibration through runtime.

**TRACK 2 STRUCTURAL PLUMBING COMPLETE** (2A-2F). Runtime A1 conformal `p_low`/`p_high` will continue to emit `not_implemented` until track 3 closes the load-bearing gap below.

45. `43aad3a` test: verify A1 primary_horizon propagation contract (2E) — verification-only, 1 new test file. 7 tests (4 parametrized over canonical horizons + 1 dataclass field check + 2 derive_a1_conformal_bounds match/mismatch). No production code. No red phase per discipline (existing behavior already satisfies contract; tests pass on first run as early-warning regression for future MarketState refactors). Confirms: `MarketState.primary_horizon` is a dataclass field; `_ms_to_dict` auto-propagates it via `__dataclass_fields__` iteration; canonical 1c/5c/15c/60c slug format; precondition 5 horizon-match check works as wired.

46. `ed18036` feat: wire A1 conformal artifact ms_dict injection (2F) — 3 files. New `v2_decision/a1_conformal_artifact_attachment.py` with `attach_a1_conformal_artifact_to_ms_dict(ms_dict, *, ticker)` mutating in place. Server.py adds 1 import + 2 single-line call-site insertions (logging path L4178, response path L4704). Strict scope: artifact-only — no calibrated_probability or lineage_id injection because canonical source not wired. Helper docstring explicitly cites "would fake provenance" and "fail honestly" disciplines from 2B contract. 9 tests (6 helper + 3 server-delegation including lightweight `test_server_imports_attachment_helper`). Green: 52 passed across 4 scopes.

47. `81f080c` governance: retire 3 closed-in-code A1/A2 named gaps — 4 files. Annotated `a2_lifecycle_static_rule_core_pending` (lifecycle contract), `a1_conformal_artifact_loader_implementation_pending` (2A), and `a1_conformal_calibration_lineage_match_pending` (2A) as **resolved** with closing-commit citations. Each retirement preserves the gap text rather than deleting (audit-trail discipline). Lineage retirement explicitly distinguishes mechanism (implemented) from runtime behavior (still gated by canonical-source gap). Static-rule-core retirement explicitly narrows scope (A2 sidecar `available` still blocked by EOD gap). Sidecar `LIFECYCLE_GAP_NAMES` tuple drops static_rule_core (14→13); test count assertion updated. Audit doc untouched per snapshot discipline. Green: 24 sidecar tests pass.

48. `c03878c` governance: bind A1 conformal production policy values (B1) — 4 files. Added 4 register rows (O-28 through O-31) plus footer sign-off update (O-01 through O-31). O-28: persistence venue = filesystem JSON. O-29: governed_max_age_seconds = 691200s (operator's wording locked verbatim: "operational freshness bound, not a statistical validity claim about the conformal coverage guarantee"). O-30: walkforward window = weekly 90/30/7/7. O-31: eval window minimum = 500 (tied to O-24). 5 named gaps retired across 3 contracts: persistence_venue → O-28; freshness_threshold (consolidated) → O-29; governed_max_age → O-29; walkforward → O-30; eval_window_min → O-31. Precondition 6 wording removes "remains unbound." Two A1 production-side gaps remain open by design (production_scheduler_pending = manual cadence is v1; per_regime_coverage_pending = future enhancement).

49. `8b3e147` governance: define A1 isotonic artifact lifecycle and runtime contract (3.0) — doc-only, 1 file. Locks the additive v2 isotonic path: filesystem JSON under `data/v2_calibration/isotonic/<module>/<expr>/<ticker>/<horizon>/<run_id>.json`; lineage hash recipe REUSED from 2C.0/2C.1 verbatim; operator decisions REUSED from O-28/O-29/O-30/O-31 (no new register rows). Runtime apply surface NEW: `apply_a1_v2_calibration_to_raw_probability(*, isotonic_artifact, raw_probability) -> tuple[float|None, str|None]`. Eligibility simpler than conformal (no O1 coverage gate; no coverage measurement on isotonic). Additive declaration locked verbatim: ml_predict unchanged; v2 path used ONLY for A1 conformal lineage; bridge gap stays open with "paper waiver for model mismatch" rationale. 4 new named gaps for sub-commits 3.1-3.4.

**Track 3 sub-commit progression:**
- 3.0 ✅ (8b3e147)
- 3.1 ✅ (fa72201)
- 3.2 ✅ (1d177ca)
- 3.3 ✅ (f96a5a3)
- Pre-3.4 ✅ (bb648db)
- 3.4 ✅ (b4c8f7d) — **TRACK 3 COMPLETE**

**TRACK 3 COMPLETE.** Canonical calibration source pipeline fully wired end-to-end. A1 conformal `p_low`/`p_high` now structurally reachable: when artifacts exist on disk for `(ticker, horizon)`, runtime loads → attaches → applies isotonic → derive_a1_conformal_bounds passes all 8 preconditions → v2_decision emits populated `v1_approximation` bounds. Operational unlock complete; only operator-initiated artifact production via the manual CLI is missing for actual runtime population.

53. `bb648db` refactor: extract dominant_probability to public helper (pre-3.4) — 3 files. New `v2_decision/a1_raw_probability.py` with public `dominant_probability(ms_dict) -> float | None`. `module_a_adapter.py` imports + uses public name; private `_dominant_probability` removed entirely (no alias). 5 tests: substantive red via monkeypatch delegation, parity with legacy logic, None for empty ms_dict, invariant assertion that private name no longer exists, signature regression. Green: 91 passed across 6 regression scopes (existing tests stayed green = byte-equivalent extraction).

54. `b4c8f7d` feat: wire A1 isotonic calibration ms_dict injection (3.4) — 4 files. **Closes track 3.** New `v2_decision/a1_isotonic_calibration_attachment.py` with `attach_a1_isotonic_calibration_to_ms_dict(ms_dict, *, ticker)` orchestrating loader (3.2) + dominant_probability (pre-3.4) + runtime apply (3.3). Server.py adds 1 import + 2 single-line call-sites immediately after 2F conformal attachment. 2F docstring updated (removes "Does NOT inject..." disclaimer; cross-references sibling). 12 tests (9 helper + 3 server-delegation). Green: 71 passed across 6 regression scopes. Both ms_dict keys (`a1_calibrated_probability`, `a1_calibrated_probability_lineage_id`) populate together or stay None — no silent partial fills.

55. `9b5cf64` governance: retire 6 closed-in-code track 3 named gaps — 2 files. Top-level closure notes added to both 2B and 3.0 contracts citing the full Track 3 commit chain. 6 gaps formally retired: 2 in 2B (canonical_source, lineage_id_propagation), 4 in 3.0 (producer, loader, apply, ms_dict_injection). Each retirement preserves original gap text + adds resolved annotation with closing-commit citation. `a1_ml_predict_to_v2_calibration_bridge_pending` preserved open verbatim in both contracts per the additive discipline.

56. `b44ceee` governance: bind A2 timing operator decisions (B2) — 5 files. Added O-32/O-33/O-34 to register; footer updated O-01 through O-34. 3 gap retirements: lifecycle contract (eod_window_threshold + force_exit_clock) and A2 0DTE contract (late_day_gamma_policy). Disambiguation section rewritten inline with bindings. Sidecar LIFECYCLE_GAP_NAMES drops 2 entries (13→11). 24 sidecar tests pass.

57. `ce46d98` fix: align sidecar tuples with B2 policy bindings (B2.1) — 2 files. Follow-up to b44ceee: caught drift between LIFECYCLE_GAP_NAMES (correctly updated) and THRESHOLD_POLICY_OBJECTS / PREVIEW_BLOCKING_GAPS (still had retired entries). THRESHOLD_POLICY_OBJECTS becomes empty; PREVIEW_BLOCKING_GAPS keeps only the EOD logic gap. Test assertions updated. 24 sidecar tests pass. **Gatekeeping miss flagged in memory:** my locked B2 spec didn't catch the other tuples in the same file. Pattern lesson: when retiring tuple-referenced gaps, scan ALL tuples in the file.

58. `20a1c14` governance: define A2 EOD force-exit and cadence contract — doc-only, 1 file. Contract-first pass for closing `a2_lifecycle_eod_force_exit_logic_not_implemented`. Bundles force-exit + cadence shift. Position state = entry_state == "filled" v1 proxy (INTENT-based, named gap for broker-realized state). Clock = decision_time_ms + ZoneInfo("America/New_York"). Force-exit predicate (4 conditions). Cadence shift at 15:30 (per O-32). Sidecar gains `cadence_observation_mode` field; `lifecycle_action` value range expands. RTH-only v1 with 3 named session gaps (shortened, holiday, out-of-session). 5 named gaps total.

**Track A2 EOD force-exit progression:**
- Contract ✅ (20a1c14)
- Code ✅ (3bf0b48) — closes `a2_lifecycle_eod_force_exit_logic_not_implemented`

**Outstanding follow-up:** cleanup queue entry for `a2_option_expression.py:383` mins_to_close unpropagated input (operator's directive: separate commit, not bundled with EOD contract). ✅ landed as 88297dd.

59. `88297dd` governance: flag a2_option_expression mins_to_close unpropagated input — 1 file. Cleanup queue entry for both call sites (L383 + L512) reading `ms_dict.get("mins_to_close")` when key isn't propagated by `_ms_to_dict`. Status open. Found during EOD contract Map-1 pre-check. Resolution path: verify downstream behavior, fix or remove.

60. `3bf0b48` feat: implement A2 EOD force-exit and cadence (closes EOD logic gap) — 5 files. New `v2_decision/a2_eod_force_exit.py` with 4 predicate helpers + orchestrator; ZoneInfo("America/New_York") clock derivation; two-layer never-raises (per-helper + orchestrator try/except). Sidecar emission consumes orchestrator: `lifecycle_action` dynamic, NEW `cadence_observation_mode` field. LIFECYCLE_GAP_NAMES drops `eod_force_exit_logic_not_implemented` (12→11). PREVIEW_BLOCKING_GAPS becomes empty tuple. Lifecycle contract retirement annotation cites this commit. 43 tests pass (helper + sidecar). 71 A1 regression tests pass (no regression). Position-realization-state and 3 session-handling gaps remain open by design (RTH-only v1).

**Operator's planned A2 sequence COMPLETE:**
- Track 3 retirement ✅ (9b5cf64)
- B2 ✅ (b44ceee + ce46d98)
- A2 EOD force-exit contract ✅ (20a1c14)
- A2 EOD force-exit code ✅ (3bf0b48)

**Major load-bearing gaps closed:**
- Track 3: A1 conformal canonical calibration source (b4c8f7d + bb648db + f96a5a3 + 1d177ca + fa72201)
- A2 EOD force-exit logic (3bf0b48)
- Both now wired end-to-end. Production CLIs need to be invoked manually for actual artifact production; runtime now reads/uses correctly.

61. `f86a889` governance: defer a2_lifecycle_legacy_exit_logic_divergence_audit_pending with explicit trigger — 1 file. Replaced ambiguous "later, separate, governed" with formal deferral: gap remains open until either (a) a commit attempts to promote A2 lifecycle behavior beyond advisory preview OR (b) a commit uses lifecycle sidecar outputs for replay/live parity gates. Explicit "does NOT block advisory sidecar v1 emission" clause preserved. Closes the only genuinely-stuck (no-date) gap that had been pending across 30+ commits.

62. `ad6d2e5` fix: derive A2 mins_to_close from decision_time_ms when explicit absent — 3 files. Real production-bug fix. Investigation of cleanup queue gap (88297dd) confirmed both call sites are load-bearing: L383 drives late_day_gamma.status / soft gates, L512 unlocks Black-Scholes theta fallback when Schwab theta/DTE absent. Existing tests masked the gap because fixtures inject mins_to_close directly. Production reads silently returned None. New `_mins_to_close(ms_dict)` helper honors explicit value first, otherwise derives from decision_time_ms via `derive_et_clock_from_decision_time_ms` (reused from a2_eod_force_exit; single source of truth for ET clock derivation). 2 substantive-red tests pre-fix; 5 new tests + 29 prior = 34 passed post-fix. Cleanup queue status flipped open → resolved with detailed citation. Self-referential commit hash is "this fix commit" placeholder per standard practice (alternative would be amend or follow-up commit; operator chose placeholder).

63. `0d0fa4c` governance: define A2 session calendar hardening contract — doc-only, 2 files. New `governance/A2_LIFECYCLE_SESSION_CALENDAR_HARDENING_CONTRACT.md` defines the future calendar-aware session handling for A2 EOD lifecycle. Repo-local operator-curated JSON at `data/trading_calendar/us_equities.json` (no external dependency). Schema spec with full_closures + early_closes + valid_through_date + freshness fields. 4 session categories (normal_rth / early_close / full_closure / out_of_session) with precedence rules. Force-exit derivation = `session_close − O-35 (10 min)`; cadence derivation = `session_close − O-36 (30 min)`. O-32/O-33 retain literal absolute-clock bindings for normal RTH. Stale calendar falls back to RTH-only v1. Register modified: O-35 + O-36 added; footer O-01 through O-36. 3 named gaps closed when code lands (shortened_session, holiday_session, out_of_session). 3 new gaps opened (calendar_freshness, multi_exchange, extended_hours). `a2_lifecycle_position_realization_state_pending` stays open per separate broker-realization track. Other session-aware code paths (db, market_context, ml_scheduler, signal_engineering) explicitly NOT touched.

64. `775948d` chore: exempt data/trading_calendar/ from gitignore for A2 session calendar fixture — 1 file. Replaced `data/` rule (line 31) with `data/*` to allow nested exemptions; added `!data/trading_calendar/` and `!data/trading_calendar/us_equities.json`. Original `data/` rule was incompatible with nested exception because Git excludes parent directory before evaluating child exceptions. `data/*` ignores contents only (not the directory itself), allowing un-ignore to descend. Initial 9d2fc82 attempt amended locally pre-push (not yet shared). git check-ignore now returns no match for the fixture path.

65. `cac88a6` data: add operator-curated A2 session calendar fixture for 2026 US equities — 1 file. New `data/trading_calendar/us_equities.json` per schema in 0d0fa4c §62-102. 10 full closures (Jan 1, Jan 19, Feb 16, Apr 3, May 25, Jun 19, Jul 3, Sep 7, Nov 26, Dec 25) + 2 early closes (Nov 27, Dec 24 at 13:00 ET). valid_through_date = "2026-12-31". Operator-curated content sourced from public NYSE/NASDAQ reference + cross-verified against 2026 calendar. JSON parses cleanly. Loader implementation follows next.

66. `7fa4693` feat: add A2 session calendar loader and classifier — 2 files. New `v2_decision/a2_session_calendar.py` with `SessionInfo` NamedTuple (5 fields), `load_a2_session_calendar(data_root, now_et_date)` (testability hook per 2D/3.2 pattern), `get_session_info(decision_time_ms, calendar)`. Schema validation centralized in `_is_valid_calendar` (reused by both helpers). Classification precedence: full_closure (weekend OR closure date) > early_close > normal_rth. Multi-layer never-raises (try/except + per-helper defensive parsers). 14 tests covering loader (7) + classifier (7); ImportError-class red captured. Green: 14 passed. EOD rewire + named-gap retirements deferred to next commit per operator's split discipline.

**Track A2 session/calendar hardening progression:**
- Contract ✅ (0d0fa4c) + register update for O-35/O-36
- Gitignore exemption ✅ (775948d)
- Calendar fixture ✅ (cac88a6)
- Loader + classifier ✅ (7fa4693)
- Next: EOD rewire + 3 named-gap retirements (`shortened_session`, `holiday_session`, `out_of_session`)

**(D) deferral resolved.** No genuinely "stale" open gaps remain — every open named gap is either operator-bound by-design (E1-E5) or has explicit trigger conditions for closure.

**Track 3 retirement ✅** (9b5cf64). 6 named gaps formally retired with closing-commit citations across 2B and 3.0 contracts. Top-level closure notes added to both. Bridge gap preserved open in both contracts.

**A2 work remaining (per operator's prior plan):**
- B2: A2 timing operator decisions (3 gaps)
- A2 EOD force-exit track (load-bearing for A2 sidecar `available`)
- D: legacy_exit_logic_divergence_audit (still no date)
- E: ~22 by-design open gaps

52. `f96a5a3` feat: implement A1 v2 calibration runtime apply (3.3) — 2 files. Pure-function helper `apply_a1_v2_calibration_to_raw_probability` wrapping `apply_isotonic_model` + `compute_calibration_lineage_id`. Try/except wrapper enforces never-raises. Defensive checks: bool short-circuit (Python's True/False are int instances), calibrated post-condition validation, lineage_id format validation. 12 tests covering 8 failure modes + does-not-raise + lineage-recipe-exactness + does-not-mutate + bonus (not_numeric, calibrated_out_of_range). Green: 12 passed.

51. `1d177ca` feat: implement A1 isotonic artifact loader (3.2) — 2 files. Mirrors 2D conformal loader pattern with isotonic-specific changes: uses `artifact_kind="isotonic"` for path resolution, imports `is_eligible_for_current_pointer_isotonic` from contract module (placed there in fa72201). Inline freshness check (duplication with `_freshness_passes` accepted for v1 per 2D operator decision). Never raises in production. 13 tests covering all 11 contract failure modes + does-not-raise + `now_epoch_seconds` testability + bonus pointer-JSON-malformed. Green: 46 passed (33 prior + 13 new); existing tests stayed green = no regression.

50. `fa72201` feat: implement A1 isotonic artifact production pipeline (3.1) — 5 files. Helper neutralization (backward-compat preserving): contract module gains `is_eligible_for_current_pointer_isotonic` + `artifact_kind: Literal["conformal", "isotonic"] = "conformal"` parameter on path helpers; producer module gains neutral `augment_artifact_with_lifecycle_fields` with conformal wrapper preserved. Isotonic producer with 8-step orchestrator (no eval window — isotonic has no coverage measurement). Thin CLI with 9 required args (no eval-start/eval-end). 10 tests including parametrization regression test. Green: 33 passed (10 isotonic + 10 conformal + 13 loader; existing 23 tests confirm neutralization is byte-equivalent).

**Track 2 + B1 complete. Open named gaps remaining (high-level):**
- **Track 3 (load-bearing for A1 runtime payload):** `a1_runtime_calibration_canonical_source_pending_implementation` + `a1_calibration_lineage_id_propagation_pending_implementation`. Closure unblocks A1 conformal `p_low`/`p_high` runtime emission.
- **Track A2 EOD (load-bearing for A2 sidecar `available`):** `a2_lifecycle_eod_force_exit_logic_not_implemented`.
- **B2 (A2 timing operator decisions, 3 gaps):** `a2_lifecycle_eod_window_threshold_minutes_policy_object_pending`, `a2_lifecycle_time_stop_force_exit_clock_threshold_policy_object_pending`, `a2_late_day_gamma_policy_pending`.
- **D (deferred without date):** `a2_lifecycle_legacy_exit_logic_divergence_audit_pending` — needs date or formal-permanent-defer.
- **E (permanently deferred by-design):** ~22 gaps including A2 lifecycle handlers, A2 entry-side risk handlers, A2 EV/execution/labels future contracts, Module A conformance gaps. These should NOT close in v1.
- **F (cleanup queue residuals):** `multi_horizon_ml_bundle.py` placeholder risk, `db.py` snapshot invariant, 3 governance archival decisions.

44. `fe3c8a9` feat: implement A1 conformal artifact loader (2D) — 4 files. R2-lite extraction: new `v2_decision/a1_conformal_artifact_contract.py` is canonical for 4 schema/path helpers + `_float_or_none`. Producer module imports + re-exports for backward compat (existing 10 producer tests stay green = byte-equivalent extraction proof). New `v2_decision/a1_conformal_artifact_loader.py` implements `load_a1_conformal_artifact` per 2A §125-148. Reads `_current.json` pointer, applies 7-criterion eligibility + freshness check (inline; mirrors `_freshness_passes` in `a1_conformal_promotion.py`; duplication accepted for v1). Never raises in production. 13 loader tests covering 11 contract failure modes + now_epoch_seconds testability + bonus pointer-JSON-malformed. Green: 23 passed (10 producer + 13 loader).

43. `8526b59` feat: implement A1 conformal artifact production pipeline (2C.2) — 3 files. New helper module with 8 pure functions: compute_calibration_lineage_id (locked SHA-256 recipe verbatim), augment_conformal_artifact_with_lifecycle_fields, is_eligible_for_current_pointer (7-criterion gate with specific reason strings per failure), artifact_output_path / current_pointer_path (data_root testability hook), write_artifact_atomically, update_current_pointer_atomically (os.replace for Windows-safe atomic rename), produce_a1_conformal_artifact (10-step orchestrator with now_epoch_seconds injected). Thin argparse CLI with 12 required window args (no implicit defaults per contract §74). 10 tests covering all 8 contract-bar minimums + helper unit + determinism. Hash recipe byte-exact: `sha256(json.dumps(model, sort_keys=True, separators=(",", ":")).encode('utf-8')).hexdigest()`. Tests use tmp_path; no pollution of real data/. ImportError-class red acceptable per Commit A precedent for fresh-module introduction. Green: 10 passed.

**Open follow-ups carried forward:**
- Named gap `a2_lifecycle_legacy_exit_logic_divergence_audit_pending` open: future governed behavior-change commit.
- A1 conformal `available` blocked through 2A's lineage discipline AND existing 7 preconditions until 2B + 2C + 2D + 2F all land.
- A2 lifecycle `available` reachable iff `a2_lifecycle_eod_force_exit_logic_not_implemented` closes (separate future commit).

**Next step:** operator decision among open tracks — (a) tiny constant-import follow-up for c2eedf0 finding, (b) upstream artifact injection commit (the next logical step to actually exercise the A1 conformal promotion path), (c) close one of the lifecycle child gaps to unblock A2 sidecar `available` state, (d) other.

**Source-consistency sweep findings (2026-05-05):** the user's question "are we deriving fields when Schwab provides them?" caught a real bug class. Cursor's BS theta fallback (`716abe3`) was technically correct but masked that `chains.contract_fields()` had never normalized theta — the BS path was firing as the default for every contract, not as a fallback. Inventory pass after Schwab re-auth confirmed Schwab provides theta + rho. Tier A normalization fix and field source discipline framework now prevent recurrence. Tier B (timestamps) covered by the same commit. Tier C (theoretical values) and Tier D (OHLC/OI/volume) remain for later.

**Pilot 1A: complete (in `v2_decision/` namespace):**

- `v2_decision/schema.py` — `LEAF_FIELD_REQUIRED_KEYS = ("value", "source")` enforced via recursive `_walk_leaf_fields`; `ALLOWED_SOURCE_INDICATORS` = {`v2_compliant`, `v1_approximation`, `not_implemented`, `policy_object_pending`}; authority block validates `mode == "advisory_non_authoritative"`, `tier == "C_analytics_only"`, `changes_trade_behavior == False`.
- `v2_decision/module_a_adapter.py` — emits all v2 §18 named leaves (`P_entry_success` → v1_approximation; `P_lifecycle_adjusted_success`, `p_low`, `p_high`, `EV_lower`, `EV_upper` → not_implemented with honest detail strings). 4 named conformance gaps in array.
- Wired into `server.py:4680` AFTER `stamp_decision_bundle` (L4666), BEFORE `_state_cache` write (L4686). Test asserts ordering.
- UI card at `static/index.html:3005` titled "V2 Pilot 1A Advisory" with non-authority banner, source indicator suffix on every leaf, no actionable controls. Test asserts no `<button>` in card markup.
- 9/9 tests pass: 6 schema tests + 3 Tier C / UI tests.

**v2 design conventions (binding for v2.0):**

- Edge domains: Signal / Implementation / Portfolio / Lifecycle.
- Strategy Module = why/when; Expression Profile = how; Portfolio Layer = whether allowed; Lifecycle Policy = how managed after entry.
- Conflict outcomes: `approved_hedge` / `thesis_break_escalation` / `blocked_lower_priority_trade` / `no_conflict`.
- Hedge contracts pre-registered with 10-field schema.
- Approximate guarantee = controlled term flagging procedures (DSR, conformal, bootstrap, CV) whose mathematical guarantees depend on data assumptions financial data violates.
- Counterfactual sensitivity ("what would change the answer") required across all decision modes.
- Source indicator on every leaf decision field per v2.0 §2.21 / §18.11.
- "Complete in structure, honest in substance" schema design rule.

**Strategy module roadmap:**

- **Module A / A1**: short-horizon event-driven equity/ETF (Pilot 1A — DONE as advisory spine; full implementation pending v2 calibration/conformal/lifecycle layers).
- **Module A / A2**: 0DTE options (Pilot 1B — NEXT). Contract-first sequence required: design A2 expression-profile contract → audit existing modules (`recommend_option_expression`, `score_option_expression`, `realized_contract_eval.py`, `live_vs_replay_validation.py`) → gap list → adapt as deterministic baseline → attach to v2_decision.
- Module B / B1, B2: swing trading equity + defined-risk options (later).
- Module C / C1, C2: long-horizon equity / LEAPS (later).
- Module D: on-demand portfolio analysis, meta-consumer of all modules (later, "should I buy AAPL?" vision lives here).

**Outstanding non-blocking items:**

- V3.0 effective date in V3.1 changelog reads 2026-05-02 but V3.0 file commit was 2026-04-30. One-character edit pending operator decision.
- Dirty worktree: ~25 modified files + ~12 untracked files unrelated to Pilot 1A still present (panel_auto sync work in server.py, ml_predict, db.py, market_state, signals, etc.). Need eventual disposition — separate logical commits or revert.
- Push status: 8 commits not pushed yet. Operator preference; backup justifies push.
- V1/V2/audit-template archive hygiene (later).
- INF-5 secrets/access-control workstream (later, scope-decision needed first).

**v1.1 status:** still cryptographically bound to `research/pilot_step3/prereg_v1.json` (content_hash `fd2b1ab608e5...`). Must be completed-and-archived OR explicitly abandoned before v2.0 prereg binds. Pilot 1A advisory spine does NOT promote v2; v1.1 remains authoritative.

**G2 status:** paused with three-state language. v2.0 adopted as target → G2 will be rewritten as G2.v2 when v2 lifecycle/promotion implementation begins.

**Multi-tool workflow:** Cursor primary code/codebase ground truth; Claude Code (this) primary for design review/verification. Operator runs reconciliation loops between tools and commits when consensus reached. Pattern: Claude reviews → Cursor sharpens/operationalizes → Claude verifies → commit. Both tools converged with Cursor's operationalization usually sharper on contract specifics, Claude's sharper on architectural completeness and verification discipline.
