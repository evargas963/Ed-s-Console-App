# 48-close set proof — defect-side reproduction (2026-08-25)

**Question (operator, audit round 3):** are the 48 historical closures independently proven AS A COMPLETE SET from underlying defect evidence — not from governance prose?

**Method:** four parallel auditor agents, 12 rows each, every row probed by ATTEMPTING TO REPRODUCE THE ORIGINAL DEFECT on the current tree (executed probe scripts + the row's own locking tests), never by reading the close narrative. Workflow run wf_7e79e307-050, 4/4 agents completed, 0 errors, 171 tool calls. Each row below carries its probe so the operator can re-run it.

**Verdicts over the 48:** DEFECT_ABSENT: 44, DEFECT_PRESENT: 3, NOT_PROBEABLE: 1.

The 3 DEFECT_PRESENT rows are RC-326, RC-329 and RC-345 — precisely the three rows this audit already REOPENED on 2026-08-25 (AUDIT-REOPEN entries in governance/root_cause_log.md). The ledger and the ground truth agree: no row claims CLOSED while its defect is reproducible. RC-472 is NOT_PROBEABLE by an offline probe (its observable is live agent behaviour) and its enforcement was retired by dated operator ruling (commit 992a9d9a) via the declared-retirement seam; stand-in census evidence executed this run.

Probe scripts under `<TEMP>/rcprobe/` were transient session scripts; each probe cell describes exactly what the script executed so it can be reconstructed, and the pytest components are directly re-runnable from the repo.

## RC-257 — DEFECT_ABSENT

**Defect (as originally measured):** Any status token other than the exact string CLOSED (CLOSED_WITH_EVIDENCE, DONE, a typo) silently disabled the close-contract clauses, so a deficient row passed freely.

**Probe (re-runnable):** <TEMP>/rcprobe/rc257_probe.py (feeds the row's deficient RC-999 fixture through _rc_row_violations under 5 status tokens, then executes the shipped _rc_status_vocabulary_violations gate on a synthetic ledger carrying CLOSED_WITH_EVIDENCE, monkeypatching K.REPO to a temp dir); plus .venv/Scripts/python.exe -m pytest tests/test_rc_status_vocabulary_v1.py -q

**Observed on current tree:** Clauses still key on CLOSED (CLOSED -> 1 violation, all other tokens -> 0), but the enforced vocabulary gate raised 1 violation on the CLOSED_WITH_EVIDENCE row — an undeclared token now FAILS instead of falling through. Gate is registered as 'rc_status_vocabulary' at tools/check_institutional_correctness.py:386 with DECLARED_RC_STATUSES={OPEN,CLOSED,REMEDIATED} at :2668. Negative-control suite: 20 passed.

**Note:** _five_why_lock_violations from the row's original repro was retired under RC-470; the surviving clause set (_rc_row_violations) plus the vocabulary gate were probed instead — the six equality comparisons are now safe by construction because the token vocabulary is constrained at the source.

## RC-286 — DEFECT_ABSENT

**Defect (as originally measured):** tools/anti_pattern_sweep.py enumerated the disk via ROOT.rglob behind a hand-maintained SKIP_DIR_PARTS, so untracked scratchpad/ scripts failed the repo-wide product gate.

**Probe (re-runnable):** <TEMP>/rcprobe/rc286_probe.py (executes anti_pattern_sweep.iter_py_files(production_only=True) and diffs the result against git ls-files -z -- '*.py'); plus .venv/Scripts/python.exe -m pytest tests/test_anti_pattern_family_repo_wide.py tests/test_gate_scope_is_the_git_index_v1.py -q

**Observed on current tree:** Scanner scope = 388 files, 0 outside the git index, 0 under scratchpad/; negative control confirms server.py, terrain_engine.py and math_levels.py are all in scope (scan not collapsed). Enumeration is git ls-files at tools/anti_pattern_sweep.py:156. Tests: 15 passed.

**Note:** Scope is the git index by definition; an untracked directory cannot enter the scan.

## RC-287 — DEFECT_ABSENT

**Defect (as originally measured):** The caps gate offered only a file-prefix allowlist and a line-number allowlist to excuse a correct line — both defective — so it stayed red over code that is right, and there was no line-attached escape.

**Probe (re-runnable):** <TEMP>/rcprobe/rc287_probe.py (executes _CAPS_OK_RE against a reasoned marker, a bare '# caps-ok:' and a bare marker with trailing spaces, then runs find_unallowlisted_hits(production_only=True) on the real tree); plus .venv/Scripts/python.exe -m pytest tests/test_caps_marker_is_line_scoped_v1.py -q

**Observed on current tree:** Marker with reason matches True; bare marker False; bare+spaces False (a reason is mandatory, so a say-nothing marker cannot suppress). find_unallowlisted_hits = 0 production hits with no prefix or line-number entry added. Test suite 10 passed, including the property test that inserts a line above an excused statement to prove the marker travels with its own line.

**Note:** Row was REOPENED 2026-08-16 and re-closed 2026-08-24; its re-close citation (test_gate_scope_is_the_git_index_v1.py) also ran green in the RC-286 probe this run.

## RC-290 — DEFECT_ABSENT

**Defect (as originally measured):** Two false '# caps-ok' exemption reasons: (i) a contract with unreadable DTE got a fabricated 999.0 and was RENDERED in the far scope as if measured; (ii) missing totalVolume and a genuine zero both produced volume 0.0, indistinguishable on the rendered path.

**Probe (re-runnable):** <TEMP>/rcprobe/rc290_probe.py (executes terrain_engine._dte_of on contracts with absent/garbage DTE, _per_strike_scopes on a no-DTE contract at spot 100, and _per_strike_map twice — once with no totalVolume key, once with totalVolume 0); plus .venv/Scripts/python.exe -m pytest tests/test_terrain_per_strike_live_v1.py tests/test_option_volume_is_live_v1.py -q

**Observed on current tree:** _dte_of -> None for both absent and garbage DTE (no 999.0); unknown-DTE contract lands in NEITHER scope (near rows = 0, far rows = 0 — Cursor's probe previously returned far:['missing-dte']); missing totalVolume -> volume None while genuine zero -> 0.0, distinguishable = True. Tests: 12 passed. Both fixes carry their RC-290 rationale in the source (terrain_engine.py:283, :415-420, :454-460).

**Note:** Both of Cursor's probes now return the opposite of the defect measurements the row records.

## RC-295 — DEFECT_ABSENT

**Defect (as originally measured):** The pinning regime scored +1.0 and emitted the support string 'charm drifting upward/downward toward pin' for a geometric agreement with a value that is not a pin (the signed-net peak of the selected expiry), asserting pinning evidence the inputs cannot establish.

**Probe (re-runnable):** .venv/Scripts/python.exe -m pytest tests/test_pinning_score_needs_a_pin_v1.py -q (the row's own measure, 5 locks incl. the tripwire); plus git grep for 'charm drifting' / 'toward pin' across tracked *.py excluding tests

**Observed on current tree:** 5 passed. The scoring branch is gone: regime_engine.py:140 carries only the 'RC-295: REMOVED' comment block (updated post-RC-292/RC-315 to record why the point stays removed even now that absolute_gamma_strike exists); the support string appears in no production code — the only near-match is an unrelated display note in math_volatility.py:131.

**Note:** The removal, not a rework, is the shipped state — matching the row's fix cell; rebuilding the point is explicitly owed as its own future row.

## RC-297 — DEFECT_ABSENT

**Defect (as originally measured):** The derivation inventory drifted from the code — missing pick_pin_and_strength, pick_net_gex_peak_strike, bs_vanna and nine terrain entries, and carrying a stale entry for the renamed pick_gamma_pin_strike — leaving the register blind to the RC-292 two-definitions-one-name collision.

**Probe (re-runnable):** .venv/Scripts/python.exe -m pytest tests/test_mega2_traceable_audit.py -q (the row's own measure) plus grep of governance/mega2_traceable_inventory.py for the four named symbols

**Observed on current tree:** 10 passed. The once-missing entries are present: pick_pin_and_strength at :130, pick_net_gex_peak_strike at :131, bs_vanna at :169; the stale pick_gamma_pin_strike entry is replaced by a comment at :126 recording its removal and the RC-124 split. Both sides of the former collision are now separately registered with distinct semantics (gross-gamma pin candidate vs signed-net peak).

**Note:** The coverage audit runs green in an enforced lane rather than inside a red suite, which was the root cause (a register nobody reads).

## RC-307 — DEFECT_ABSENT

**Defect (as originally measured):** tests/test_coh_sa2_et_authority.py (and test_calibration_bypass_closure.py) enumerated the disk with rglob behind hand-written skip lists, judging 93 untracked scratchpad scripts as production code and failing on files the repository does not contain.

**Probe (re-runnable):** <TEMP>/rcprobe/rc307_probe.py (imports both test modules and executes their enumerators — A._iter_repo_py_files(root) and B._tracked_py_files() — diffing every yielded path against git ls-files); plus .venv/Scripts/python.exe -m pytest tests/test_coh_sa2_et_authority.py tests/test_calibration_bypass_closure.py tests/test_gate_scope_is_the_git_index_v1.py -q

**Observed on current tree:** et_authority enumerator: 684 files, 0 outside the index, 0 scratchpad; calibration_bypass enumerator: 1279 files, 0 outside, 0 scratchpad. Both are git ls-files subprocess calls (test_coh_sa2_et_authority.py:32, test_calibration_bypass_closure.py:29). All three tests green: 13 passed, including the widened one-number scanner sweep covering tools/ AND tests/.

**Note:** Untracked files cannot enter either test's scope by construction; the class sweep that missed tests/ now counts both trees.

## RC-310 — DEFECT_ABSENT

**Defect (as originally measured):** The Call card's size slot passed numeric r_units as fstr's third argument; fstr returns the first non-empty STRING, so a numeric value — 2.5, 0, anything — could never render and the sizing fallback never fired, while the guarding test asserted only the absence of the name.

**Probe (re-runnable):** node <TEMP>/rcprobe/rc310_probe.mjs (regex-proves r_units is never passed to fstr anywhere in static/index.html, confirms the live binding fstr(s.size_cue, s.sizing_summary) || rUnitsText(s.r_units) at :13563, and EXECUTES the rUnitsText source extracted verbatim from the page across 2.5, 0, -1.25, null, undefined, NaN, Infinity, '3'); plus node tests/index_html_contracts_node.mjs and .venv/Scripts/python.exe -m pytest tests/test_stack_wire_3_ui_phase3_closure.py -q

**Observed on current tree:** r_units-in-fstr: false; typed binding present: true; rUnitsText(0)='0.00 R' (zero is a real size), 2.5->'2.50 R', -1.25->'-1.25 R', null/undefined/NaN/Infinity/string->null (withheld keeps the em-dash). Node contract suite: all assertions passed. Pytest: 7 passed.

**Note:** The formatter mismatch is structurally impossible now: the numeric path has its own typed renderer, exported so the contract executes rather than string-matches.

## RC-316 — DEFECT_ABSENT

**Defect (as originally measured):** RC-313's ledger claim was false: it described editing _greek_notes as an operator-facing Call-card fix, but _greek_notes/_add_greek_color are a dead pair with no production caller — the corrected sentence reaches no screen.

**Probe (re-runnable):** <TEMP>/rcprobe/rc316_probe.py (re-executes the fix cell's caller scan: git ls-files -z -- '*.py' '*.html' scoped search for both symbols, plus an in-file call-site scan of call_engine.py excluding the def line)

**Observed on current tree:** _greek_notes carriers: call_engine.py (definition), its own test, and one archived inventory record — exactly what the corrected row records; _add_greek_color likewise. Zero call sites of _greek_notes inside call_engine.py. Both defs still present (pair retained un-deleted per the operator's read-before-delete law).

**Note:** The defect is a false impact claim, not a code behavior; the probe shows the ledger's corrected record (dead pair, retained, no operator surface changed) matches the executed caller scan on the current tree, so no false claim stands.

## RC-317 — DEFECT_ABSENT

**Defect (as originally measured):** The enforced claims-are-executed gate did not catch the exact file shape it was built for: docstring text normalised through a helper into a local scored (0 prose, 1 subject) and PASSED — the helper call counted as subject execution and the tainted local was not counted as prose.

**Probe (re-runnable):** <TEMP>/rcprobe/rc317_probe.py runs check_test_claims_are_executed.analyse() on <TEMP>/rcprobe/rc317_fixture.py — a reconstructed RC-294-shape fixture (blob = _norm(inspect.getdoc(math_levels.bs_charm)); three asserts on blob); plus .venv/Scripts/python.exe -m pytest tests/test_claims_are_executed_gate_v1.py -q

**Observed on current tree:** Fixture scores (3 prose, 0 subject) -> CAUGHT: the helper call carrying tainted text is a text transform, not subject execution, and the asserts on the tainted local are prose. This is the exact flip the RC-477 fix cell records (from (0,1)-pass to (3,0)-caught). Gate suite: 9 passed, including the new negative control test_a_prose_only_file_cannot_hide_behind_a_local_name_or_helper.

**Note:** This row was re-fixed on this branch under RC-477 (commit a565ef8d, analyser taint-wired via _names_holding_file_text in both counters); the probe verifies the CURRENT branch state as instructed.

## RC-322 — DEFECT_ABSENT

**Defect (as originally measured):** build_live_snapshot's two clock-selected early exits (future session date, pre-RTH-open) delegated to build_premarket_snapshot WITHOUT the canonical snapshot, so the pre-open path recomputed Phase 2A levels and /api/levels vs /api/liquidity-snapshot disagreed live (overnight low 773.3975 vs 772.55).

**Probe (re-runnable):** .venv/Scripts/python.exe -m pytest tests/test_phase2a_premarket_carries_canonical_v1.py -q (the row's locking test: drives build_live_snapshot and build_premarket_snapshot on ONE canonical snapshot and asserts every Phase 2A level identical), plus read of the signature and both delegation sites

**Observed on current tree:** 4 passed. build_premarket_snapshot (liquidity_value_engine.py:708) accepts keyword-only canonical and, when supplied, carries families via _phase2a_families_from_canonical with no level helper running; both early exits (:1270 and :1277) now pass canonical=canonical, with the RC-322 comment stating the contract.

**Note:** The live two-endpoint disagreement itself needs the running console; the locking test executes the same producer-equivalence offline and stands in. Scope honored as the row wrote it: this closes the pre-open branch only — the opening/midday/afternoon builders (call sites :1503/:1548, historical paths) still self-compute and remain OPEN under the operator's order, outside this row.

## RC-326 — DEFECT_PRESENT

**Defect (as originally measured):** The one-producer gate was narrowed to kill false positives without measuring what the narrowing stopped detecting: it reports zero/PASS while structural clones, semantic field collisions and identical returned formulas — duplication the surface gate cannot see — stand in the tree.

**Probe (re-runnable):** .venv/Scripts/python.exe tools/check_one_producer.py (the enforced surface gate) and .venv/Scripts/python.exe tools/deep_duplicate_probe_v1.py (the row's PART 1 ground-truth probe, three orthogonal detectors), both executed this run from the worktree

**Observed on current tree:** check_one_producer: PASS over 6 registered fields, 596 fields NOT_PROVEN. deep_duplicate_probe_v1 still measures: 37 structural clone groups (including the row's named instances — 16 statements duplicated 4 ways across tools/_build_section{11,13,14,15}_inventory.py, 15 statements 7 ways across _build_section{2,3,5,6}_inventory.py, and ml_scheduler.py:945 _train_parallel_meta_oof vs :1704 _train_cascade_meta_oof), 18 identical-formula groups (3+ sites), 222 concepts with 2+ spellings. The duplication is measurable by the probe but invisible to the enforced lane.

**Note:** OPEN by design — the AUDIT-REOPEN 2026-08-25 entry rules the row stays OPEN until PART 2 (an enforced deep gate with a corpus-fed recall control) lands or the operator records a permanent descope in the row. The verdict describes what the current tree exhibits, as instructed: ground-truth probe exists and runs, enforced gate still cannot see what it measures.

## RC-328 — DEFECT_ABSENT

**Defect (as originally measured):** cf_* confluence windows were list slices — 'cf_trend_1h' could span up to 90.4 hours — and train/serve read different row populations through one function

**Probe (re-runnable):** Executed lstm_data.compute_confluence_features via scratchpad rc_probes.py (cwd=worktree, .venv python): (A) 61 rows 1s apart with strong drift, (B) 61 rows 60s apart, (C) history pool ending 90h before the current row; plus F32 one-population lock: env -u ED_AGENT_ROLE .venv/Scripts/python.exe -m pytest tests/test_single_producer_batch_f02_f13_v1.py -q

**Observed on current tree:** A: cf_momentum_5m/cf_structure_15m/cf_trend_1h all 0.0 (ABSENT) where slot logic would emit a saturated trend from 60 seconds of data; B: 0.948/1.0/1.0 (window genuinely present); C: all 0.0 despite 60 uptrending rows 90h back. F32 lock green in 56/56; import even emitted the RC-340 'GOVERNED ABSENCE (0.0) ... no substitute population' warning, confirming both lanes route through ml_data_common.fetch_confluence_history

**Note:** Windows are clock-defined at the single producer; absence reports 0.0, never a widened span. Both defect triggers (sub-minute spacing and multi-day gap) failed to reproduce the defect.

## RC-329 — DEFECT_PRESENT

**Defect (as originally measured):** the one-producer gate counts DEFINITION SITES, so a shared callee fed two different input populations (D5 shadow / D6 diverged) reads as one producer and PASSes

**Probe (re-runnable):** Executed the gate itself: env -u ED_AGENT_ROLE .venv/Scripts/python.exe tools/check_one_producer.py (rc=0); read its module docstring; repo-wide search for the promised call-path parity control

**Observed on current tree:** Gate prints 'check_one_producer: PASS over 6 registered field(s); 596 field(s) NOT_PROVEN'. Docstring (tools/check_one_producer.py:18-28) declares D5/D6 CANNOT be answered and defers the call-path parity control to 'RC-329 PART 2'. That control does not exist anywhere — the only hit for 'call-path parity' in .py files is the forward reference at tools/check_one_producer.py:26

**Note:** OPEN by design (AUDIT-REOPEN 2026-08-25). The detection gap is real on the current tree: unit of analysis is still function bodies, D5/D6 remain NOT_PROVEN by the tool's own declaration, and the PART 2 parity control is unbuilt. The one confirmed member (RC-328) was structurally eliminated, but the gate still could not detect a new member of the class.

## RC-345 — DEFECT_PRESENT

**Defect (as originally measured):** single-producer master batch F02..F42; remaining scope is F10 — candle-direction preprocessing was aligned to the dead-band authority but PREPROCESSING_VERSION was never bumped via the coordinated retrain, leaving a train/serve preprocessing skew

**Probe (re-runnable):** env -u ED_AGENT_ROLE .venv/Scripts/python.exe -m pytest tests/test_single_producer_batch_f02_f13_v1.py -q; then executed .venv/Scripts/python.exe -c "import model_contract; print(model_contract.CURRENT_PREPROCESSING_VERSION)"

**Observed on current tree:** 56 passed (all F02..F42 batch locks green, including the F10 dead-band-authority lock and the F32 cf_* one-authority lock). CURRENT_PREPROCESSING_VERSION prints 'v5_no_m5_lag' — unchanged, pinned at tests/test_single_producer_batch_f02_f13_v1.py:161 and tests/test_ml_feature_schema_parity.py:447, so the retrain-then-bump the row's body requires has not run

**Note:** OPEN by design, scope narrowed to the F10 remainder. Every closed lane re-verified green by execution this run; the open remainder (retrain evidence absent, version still v5_no_m5_lag) manifests exactly as the AUDIT-REOPEN 2026-08-25 note records, shielded per the row only by the RC-436 fleet-wide abstain (32/32 metas).

## RC-352 — DEFECT_ABSENT

**Defect (as originally measured):** 34 display-label sites used house/misleading terms (Gamma Pin, Gamma Wall Call/Put, Gamma/Delta Inflection, King node, EFE/EAE, Net GEX · Agg) instead of verified institutional vocabulary

**Probe (re-runnable):** env -u ED_AGENT_ROLE .venv/Scripts/python.exe -m pytest tests/test_charm_vote_gate.py tests/test_client_spot_single_faucet_v1.py tests/test_live_ui_integrity_v1.py tests/test_decision_gate.py -q; plus executed label counts + regex context dump over static/index.html and static/chart.html (rc_probes.py)

**Observed on current tree:** 162 passed. Institutional labels render: Absolute Gamma x10, Call Wall x5, Put Wall x4, Net GEX Peak x3, Charm Flow x2, Exp. MFE/MAE x2/x2, Total Net GEX x2 in index.html; chart.html has Absolute Gamma x3, ABS GAMMA x3, Net GEX Peak x1, Gamma Pin x0. Every residual house-term hit is a 'Formerly "X"' transition tooltip, a code comment, or a substring false-match ('REFERENCE' contains 'EFE'); zero display labels carry a house term

**Note:** Display-lock suites executed green and the rendered-source label census shows the institutional vocabulary is the only display vocabulary.

## RC-353 — DEFECT_ABSENT

**Defect (as originally measured):** after the RC-352 renames the Exp. MFE/MAE rows had no tooltip at all and renamed labels lacked a 'formerly X' bridge, so the operator had no on-screen old-to-new mapping

**Probe (re-runnable):** Executed counts + context extraction over static/index.html (rc_probes.py + regex context pass): count('Formerly'), count('Expected Maximum Favorable Excursion'), count('Expected Maximum Adverse Excursion')

**Observed on current tree:** 'Formerly' bridges: 15 (contexts confirmed as tooltips, e.g. formerly "Gamma Pin", Formerly "Gamma Inflection", Formerly 'Net GEX · Agg', Formerly 'EFE'/'EAE'); the MFE/MAE rows carry definition tooltips — 'Expected Maximum Favorable Excursion' x1 and 'Expected Maximum Adverse Excursion' x1, each with the Sweeney definition text and the Formerly note

**Note:** Both halves of the defect (missing MC-row tooltips, missing formerly-bridges) fail to manifest in the rendered source.

## RC-356 — DEFECT_ABSENT

**Defect (as originally measured):** the RC-113 wall-range corridor shade (translucent fill between put wall and call wall) painted over the candle field in static/chart.html

**Probe (re-runnable):** Executed a scan of static/chart.html for every 'corridor' occurrence and every wall+fill draw line, read the draw path at chart.html:1360-1381, and ran env -u ED_AGENT_ROLE .venv/Scripts/python.exe -m pytest tests/test_chart_accrual_consumer_v1.py tests/test_chart_intent_lock_v1.py tests/test_numeric_contract_tier15.py tests/test_direction_triplet_authority.py -q

**Observed on current tree:** Only 2 'corridor' hits, both comments: line 1172 (range-semantics comment) and lines 1367-1371 — the RC-356 removal note standing where the fill draw used to be; no fill draw between the walls exists (the only other wall+fill line is a fillText caption). Wall level lines survive via band(). Combined suite run: 55 passed (18 chart-lock + 37 triplet-authority, matching the two rows' close-time counts)

**Note:** The shade draw is gone from the render path; boundary information is preserved by the wall level lines.

## RC-357 — DEFECT_ABSENT

**Defect (as originally measured):** no 0DTE gamma share metric existed — the operator could not tell whether today's walls/flip evaporate at the close (0DTE-dominated) or persist (dated gamma)

**Probe (re-runnable):** Executed math_exposure_core.compute_zero_dte_gamma_share on synthetic books (rc_probes.py): full={5000:+100, 5100:-50} net_gex_1pct, 0dte={5000:+60}; empty full book; empty 0dte book. Wiring: counted kl_zero_dte_share in server.py and static/index.html

**Observed on current tree:** Mixed book -> 40.0 (=100*60/150, correct abs-share); empty full book -> None (fail-closed, no fabricated 0%); no 0DTE gamma -> 0.0. Wiring: kl_zero_dte_share server.py x1 (producer), index.html x1 (consumer row)

**Note:** The producer exists, computes the declared ratio, fails closed, and is wired end-to-end to the display.

## RC-358 — DEFECT_ABSENT

**Defect (as originally measured):** no 25-delta risk reversal (front-expiry IV(25d call) - IV(25d put)) existed, so the intraday put-bid build — the GSF-breach confirm — was unreadable

**Probe (re-runnable):** Executed math_volatility.compute_25d_risk_reversal on a synthetic chain (rc_probes.py): dte=0 call delta .26 IV 20 / put delta -.24 IV 24 plus dte=7 decoys; a chain with no usable 25d call (delta .60); an empty chain. Wiring: counted kl_rr25 in server.py and static/index.html

**Observed on current tree:** Front expiry correctly selected (dte 0, decoys at dte 7 ignored): rr_pts -4.0, call_iv_25d 20.0, put_iv_25d 24.0; tolerance gate fail-closed -> None when no wing within |delta-target|<=0.10; empty -> None. Wiring: kl_rr25 server.py x2 (produce+guard), index.html x2 (render+label)

**Note:** Producer computes the skew read as specified and fails closed on unusable wings; wired to the console row.

## RC-361 — DEFECT_ABSENT

**Defect (as originally measured):** aggregate dealer DEX $ was summed nowhere despite per-strike call/put_dex_dollars in the exposures book — dealer directional inventory was unsizeable

**Probe (re-runnable):** Executed math_exposure_core.compute_net_dex_dollars (rc_probes.py) on a two-strike book (call_dex 1.0e6/2.0e5, put_dex -4.0e5/-1.0e5) and on an empty book. Wiring: counted kl_dex_net in server.py and static/index.html

**Observed on current tree:** net_dex 1,700,000.00 = sum(call)-sum(put) with the negative put leg flipped to the dealer side correctly (call_dex 1.2e6, put_dex -5.0e5); empty book -> None (fail-closed, never a fabricated $0). Wiring: kl_dex_net server.py x1, index.html x1

**Note:** The aggregate producer exists under the same naive dealer-sign model as GEX and reaches the operator display.

## RC-362 — DEFECT_ABSENT

**Defect (as originally measured):** per-strike vanna was summed nowhere and charm displayed as raw shares/day — vol-driven hedge flow was not dollarized or sizeable

**Probe (re-runnable):** Executed math_exposure_core.compute_net_vanna (rc_probes.py): book {5000:{call_vanna:5000, put_vanna:2000}} at spot 500; empty book; missing spot. Wiring: counted kl_vanna_net in server.py and static/index.html

**Observed on current tree:** net_vanna_shares_per_volpt 30.0 (=(5000-2000)/100) and net_vanna_dollars_per_volpt 15,000.0 (=30*spot); empty book -> None; spot None -> None (both fail-closed). Wiring: kl_vanna_net server.py x1, index.html x1

**Note:** The vanna aggregate exists, is dollarized per vol-point, fails closed, and is wired to the Net Vanna console row.

## RC-363 — DEFECT_ABSENT

**Defect (as originally measured):** direction_from_normalized_triplet raised TypeError on a None leg and emitted an order-dependent garbage label on a NaN leg, which eval paths scored as a real prediction

**Probe (re-runnable):** Executed numeric_contract.direction_from_normalized_triplet (rc_probes.py) on the exact triggering inputs: (None,.5,.5), (nan,.2,.1), (.2,nan,.1), (inf,.2,.1), ('0.5',.2,.1), plus finite controls (.5,.3,.2) and the (.4,.4,.2) tie; and ran the pinned suites tests/test_numeric_contract_tier15.py + tests/test_direction_triplet_authority.py

**Observed on current tree:** None leg -> None (no TypeError); NaN leg -> None in BOTH argument orders (no order-dependent label); inf -> None; non-numeric -> None; finite control -> 'up'; tie -> 'up' (documented stable tie-break). Pinned suites green: 37 of the 55-passed combined run (matches the row's close-time 37)

**Note:** The authority returns WITHHELD (None) on every non-finite leg class the row enumerates; the crash and the garbage label both fail to reproduce.

## RC-364 — DEFECT_ABSENT

**Defect (as originally measured):** the board re-marked frozen closes as done on SHA ancestry alone while the tree lacked the content — false [x] rows hiding live defects (worst: server.py publishing LSTM val_accuracy x100 as edge)

**Probe (re-runnable):** Executed a PORT-NEEDED census over OPEN_ITEMS.md with checkbox-state extraction (rc_probes.py); checked server.py for the val_accuracy-as-edge registration; ran env -u ED_AGENT_ROLE .venv/Scripts/python.exe -m pytest tests/test_model_edge_absent_is_not_zero_v1.py tests/test_liquidity_engine.py -q

**Observed on current tree:** Both PORT NEEDED rows (OPEN_ITEMS.md:228 UI-01 analytics_cache_key, :393 gamma_pin_semantic migration) are still '[ ]' — open and honest, no false [x]; analytics_cache_key remains absent from code, matching the open marking. The worst cited live defect is gone from the tree: server.py:9356-9396 bans the fallback ('RC-291: NO val_accuracy fallback', 'never val_accuracy masquerading as edge'), stamps val_accuracy under its own name and leaves edge None. Cited suites: 62 passed

**Note:** The board correction stands (tree-false rows open with PORT-NEEDED provenance) and the live defect the false [x] had been hiding is verified fixed by the executed edge-absence suite.

## RC-365 — DEFECT_ABSENT

**Defect (as originally measured):** Absent confluence renders as fabricated 0/0 dots — /api/state stamped getattr-zero defaults so a session with NO computed confluence looked like a measured zero

**Probe (re-runnable):** Executed market_context.stamp_confluence_display_fields on a no-confluence ctx and a measured-0.0 ctx, plus scanned server.py for the inline getattr-zero block (scratchpad rc_defect_probes.py, .venv python, cwd=EdWebConsole-audit-response); env -u ED_AGENT_ROLE .venv/Scripts/python.exe -m pytest tests/test_f39_confluence_missingness.py tests/test_model_edge_absent_is_not_zero_v1.py -q

**Observed on current tree:** Absent confluence -> cf_weighted_push=None, cf_dot_green=None, cf_dot_total=None (withheld, not 0/0); measured 0.0 control -> 0.0 with dots 0/6 preserved; server.py stamps via stamp_confluence_display_fields with no inline dot_count_green-0 defaults; suites 14 passed

## RC-366 — DEFECT_ABSENT

**Defect (as originally measured):** Undeclared second spot faucet — charm dollarization read raw Number(d.spot) at static/index.html while the declared effectiveDisplaySpot value was already in scope

**Probe (re-runnable):** Python content assertion over the full static/index.html (rc_defect_probes.py): 'const _cSpot = spot;' must be present and 'Number(d.spot)' must appear nowhere in the file

**Observed on current tree:** const _cSpot = spot; present (line ~8451 region); zero occurrences of Number(d.spot) anywhere in static/index.html — one producer for the rendered spot concept

**Note:** The defect is a source-level dual-faucet; the probe executes the exact scan the stop_guard faucet law uses (raw payload read present/absent)

## RC-369 — DEFECT_ABSENT

**Defect (as originally measured):** Silent-zero absence coercion — a bucket MISSING net_gex_1pct contributed a fabricated zero weight to the 0DTE share-of-book ratio ('or 0.0' idiom)

**Probe (re-runnable):** Executed math_exposure_core.compute_zero_dte_gamma_share on the triggering inputs (rc_defect_probes.py): a book with one bucket missing net_gex_1pct, a NaN book, and a complete control book; env -u ED_AGENT_ROLE .venv/Scripts/python.exe -m pytest tests/test_gamma_profile_v1.py tests/test_radar_two_sided_wall_v1.py -q

**Observed on current tree:** Missing-field book -> None (whole share WITHHELD), NaN book -> None, complete book -> 20.0 (real ratio); path routes through float_finite_or_none per the RC-369 comment at math_exposure_core.py:567-575; suites 44 passed, 1 warning

## RC-371 — DEFECT_ABSENT

**Defect (as originally measured):** Audit identity counted its own recordings (reports/ writes flipped worktree identity mid-audit -> self-INCOMPLETE) plus 3 stale suite expectations reddening every owned run

**Probe (re-runnable):** Executed tools.turn_self_audit.capture_identity twice with ScopeResults differing only by a reports/terrain_quarantine_ledger.jsonl entry (rc_defect_probes.py); env -u ED_AGENT_ROLE pytest tests/test_audit_cand_server_py_full_read_v1.py -q; pytest tests/test_caps_marker_is_line_scoped_v1.py::test_the_gate_passes_on_merit tests/test_datetime_silent_default_repo_wide.py::test_fetch_price_levels_skips_candle_missing_datetime -q

**Observed on current tree:** worktree_identity byte-identical with and without the reports/ entry (exclusion at tools/turn_self_audit.py:340-344 executed live, errors=[]); the vwap re-anchor suite 22 passed; the other two re-anchored tests 2 passed

## RC-372 — DEFECT_ABSENT

**Defect (as originally measured):** Negative-control test restored the real AGENTS.md via platform-newline text write — charter flipped LF->CRLF on every run, breaking audit identity

**Probe (re-runnable):** sha256sum AGENTS.md governance/root_cause_log.md; env -u ED_AGENT_ROLE .venv/Scripts/python.exe -m pytest tests/test_enforced_check_negative_controls_v1.py -q; git status --porcelain -- AGENTS.md; sha256sum both files again (cwd=EdWebConsole-audit-response)

**Observed on current tree:** 24 passed; AGENTS.md sha256 0baa5079... identical before and after the run, root_cause_log.md sha256 017842aa... identical too; porcelain empty for AGENTS.md (the ledger's ' M' is a pre-existing 1-line uncommitted branch edit whose bytes the run did not touch — sha constant across the run)

**Note:** The 3 failures RC-373's close once recorded against this file are gone — the full-file run is 24/24 on this tree

## RC-373 — DEFECT_ABSENT

**Defect (as originally measured):** Machine-local enforcement: a test premised on an uncommitted fixture, _listening_pid crashing FileNotFoundError where `ss` is absent, and ledger round-trips restoring platform-translated newlines

**Probe (re-runnable):** Executed opl._listening_pid(port=59999) with sys.platform forced to 'linux' on this ss-less host (rc_defect_probes.py); env -u ED_AGENT_ROLE pytest tests/test_ui_mockup_lock_v1.py tests/test_operating_process_lock_v1.py -q on this clean-checkout worktree; ledger byte-fidelity via the RC-372 sha256 pre/post run

**Observed on current tree:** _listening_pid returned None with no exception (typed absence, guard at tools/operating_process_lock.py:385-392); 60 passed — every fixture reference resolves on a checkout that is not the author worktree; governance/root_cause_log.md sha identical across the negative-controls run (no EOL flap)

## RC-374 — DEFECT_ABSENT

**Defect (as originally measured):** CI red on F401 unused imports, .cursor/hooks.json existing only untracked, and index_worktree_mismatches skipping a planted NEW untracked enforcement-path file (invisible plant)

**Probe (re-runnable):** .venv/Scripts/python.exe -m ruff check --select F401 tests/test_gamma_profile_v1.py; git ls-files .cursor/hooks.json; executed the exact plant in a scratch git repo — untracked tools/check_planted_backdoor.py fed to OPL.index_worktree_mismatches(repo, paths=[...]) then staged as control (scratchpad rc374_plant_probe.py)

**Observed on current tree:** Ruff: All checks passed (F401 gone); .cursor/hooks.json is tracked; plant TRIPPED with 'exists in worktree but not in the index (untracked enforcement surface)' (fail-closed branch at tools/operating_process_lock.py:254-260) and the staged control cleared to []; test_operating_process_lock_v1 green within the 60-passed run

**Note:** The 22 Playwright E2E reds the row recorded belong to RC-351's lane per the row itself, not this closure

## RC-375 — DEFECT_ABSENT

**Defect (as originally measured):** Board stale in the inverse direction — claimed 'DEFECT ALIVE at server.py:9298' for RC-291 after the same commit fixed it; plus two gates weaker than the sentences they certify

**Probe (re-runnable):** Python scan of every governance/ file except the ledger (which quotes the claim historically) for 'DEFECT ALIVE' / 'server.py:9298' (rc_defect_probes.py); env -u ED_AGENT_ROLE pytest tests/test_model_edge_absent_is_not_zero_v1.py tests/test_f39_confluence_missingness.py -q (the strengthened AST producer lock and stamp-uniqueness scan)

**Observed on current tree:** Zero governance files still carry the alive claim (hits=[]); the strengthened gates executed green — 14 passed, including the AST no-multiply edge_pp producer control and the f39 single-stamp uniqueness scan

## RC-382 — DEFECT_ABSENT

**Defect (as originally measured):** Line-ending style was an unowned property — any writer could silently flip a whole file's terminators and bury the real diff (3 measured occurrences in one session)

**Probe (re-runnable):** env -u ED_AGENT_ROLE pytest tests/test_eol_style_invariant_v1.py -q (planted controls reproduce all 3 historical flips and prove refusal); .venv/Scripts/python.exe tools/check_eol_style_invariant.py --measure on the current tree; roster + wiring checks: 'eol_style_invariant' in cic.CHECKS and the eol-style-invariant hook in .pre-commit-config.yaml (rc_defect_probes.py)

**Observed on current tree:** 11 passed — charter CRLF flip, settings.json flip, and the slice-1 flip all reproduced and REFUSED by the check; live --measure: [PASS] no line-ending flips in worktree changes, rc=0; check registered enforced and wired at commit time (.pre-commit-config.yaml lines 49-54)

## RC-391 — DEFECT_ABSENT

**Defect (as originally measured):** Pre-commit gate demanded absolute zero on a repo carrying 57 inherited violations (blocked every commit, routed around 15x); its replacement graded HEAD not the index and count-only comparison rewarded deleting a check

**Probe (re-runnable):** Executed the live gate: env -u ED_AGENT_ROLE .venv/Scripts/python.exe tools/precommit_institutional.py on this inherited-debt tree; env -u ED_AGENT_ROLE pytest tests/test_delta_adds_no_debt_v1.py -q (controls: index_candidate is the staged tree/partial staging, removed/renamed/demoted enforced check blocks, backlog never masks a fresh regression, worktrees strip caller git bindings)

**Observed on current tree:** Gate exit 0: 'enforced-check roster intact (42 enforced); whole-tree added-violation delta enforced in CI (same check_delta_adds_no_debt.py owner)' — no absolute-zero block; 45 passed including test_index_candidate_is_the_staged_tree_and_excludes_unstaged_work and test_removing_an_enforced_check_blocks_and_cannot_read_as_paydown

**Note:** Post-RC-406 the whole-tree delta runs in CI hardening.yml via the same owner; the commit seam keeps the RC-391 roster-removal block — verified by test_the_precommit_seam_measures_the_check_roster_not_the_whole_tree_delta in the 45

## RC-392 — DEFECT_ABSENT

**Defect (as originally measured):** Relocating pre-commit into a clean worktree silently disarmed two staged-scope enforced checks — they interrogated an index matching HEAD and could never fail (presence without capability)

**Probe (re-runnable):** env -u ED_AGENT_ROLE pytest tests/test_delta_adds_no_debt_v1.py -q — test_the_candidate_worktree_presents_the_change_as_STAGED asserts the plain worktree shows nothing staged (the defect) and the repaired _stage_the_delta seam shows exactly the changed path; roster query [n for n,*_ in cic.CHECKS if 'no_drift'/'research_before'/'recursive_five_why' in n] (rc_defect_probes.py)

**Observed on current tree:** 45 passed including the staged-presentation control; roster query returned [] — both once-disarmed checks are retired per governance/retired_checks.md, so no staged-scope check remains for the seam to disarm, and the seam that would carry one presents the change as STAGED

## RC-396 — DEFECT_ABSENT

**Defect (as originally measured):** Required CI convicted the environment — hardening exported a fabricated ED_AGENT_ROLE=cursor (writer_no_drift 0->27) and research_before_act read a deliberately-untracked local log's absence as a violation on every clean runner

**Probe (re-runnable):** Python scan of every .github/workflows/*.yml for ED_AGENT_ROLE lines (rc_defect_probes.py); the row's own verify executed — cic.CHECKS filtered for no_drift/research_before names; test_ci_never_fabricates_an_agent_identity ran green inside the 45-passed delta suite

**Observed on current tree:** Only hit is hardening.yml:21, a comment recording the RC-396 repair — no active export of any agent identity in any workflow; roster query -> [] (both convicting checks retired per governance/retired_checks.md); the workflow-scanning control passes live

## RC-401 — DEFECT_ABSENT

**Defect (as originally measured):** db_authority forked the money path to data/ed_console_claude.db under ED_AGENT_ROLE=claude, a path EdDB's canonical check then refused

**Probe (re-runnable):** scratchpad/probe_rc_batch.py: set os.environ['ED_AGENT_ROLE']='claude', reload db_authority, call default_console_db_path()/canonical_console_db_path()/is_canonical_db_path(default), hasattr checks for the fork functions; then env -u ED_AGENT_ROLE .venv/Scripts/python.exe -m pytest tests/test_agent_worktree_db_v1.py -q

**Observed on current tree:** With the triggering role env set, default_console_db_path() == canonical data/ed_console.db (no 'claude' in the name); agent_worktree_console_db_path and is_agent_worktree_db_path have no def; is_canonical_db_path(default)=True so the opener admits the default (the contradiction is gone); the 6-test ONE-DB suite passed (within the 54-passed run)

**Note:** The row deliberately left the stray ed_console_claude.db data-merge/discard decision OPEN as an operator matter; this probe covers only the fork defect, as the row scopes it.

## RC-402 — DEFECT_ABSENT

**Defect (as originally measured):** operator_go_granted's 'staged_lock_surface' wildcard disjunct returned True for every scope, disarming the LOCK-2 reset guard (git reset --hard would be waved through)

**Probe (re-runnable):** scratchpad/probe_rc_batch.py: hasattr(operating_process_lock,'operator_go_granted'), os.path.exists('governance/operator_go.json'), reset_guard_violations('git reset --hard HEAD~1') and ('git checkout -- db.py server.py') and benign control ('git status'); env -u ED_AGENT_ROLE .venv/Scripts/python.exe -m pytest tests/test_reset_guard_v1.py -q

**Observed on current tree:** operator_go_granted no longer exists at all (attr False; tests/test_operating_process_lock_v1.py:44 pins its absence) and governance/operator_go.json is deleted; the reset guard FIRED on both the bare and path forms ('RESET_GUARD (LOCK-2/RC-231)...') and returned [] on the benign control; test_reset_guard_v1.py passed (within 54-passed run)

**Note:** Hardened past the original fix: not just the wildcard removed — the whole grant predicate and grant file are gone, so no scope query can be granted by a standing file.

## RC-403 — DEFECT_ABSENT

**Defect (as originally measured):** PM identity lived in two disagreeing records (sole_writer.json pm=cursor vs pm_mission.json pm=operator) and rehab_daily_scan raised P1 rehab.pm_not_cursor recommending reversal of the operator's decision

**Probe (re-runnable):** scratchpad/probe_rc_batch.py: os.path.exists on governance/sole_writer.json, pm_mission.json, PM_MANDATE.md; import tools.rehab_daily_scan and inspect.getsource census for 'pm_not_cursor'/'sole_writer'/'pm_mission'

**Observed on current tree:** All three PM-identity files are absent (False/False/False) and the imported scanner's live source contains zero references to pm_not_cursor, sole_writer, or pm_mission — there is no record pair to disagree and no check keyed on the stale cursor literal

**Note:** Closure superseded the dual-record reconciliation: PM identity no longer persists in the repository at all (operator-is-PM by ruling RC-475, in chat); the defect's precondition cannot recur in-tree.

## RC-442 — DEFECT_ABSENT

**Defect (as originally measured):** (a) nothing blocked a claude-worktree edit targeting the primary/production checkout; (b) _db_content_change_epoch used checkout-stamped fs mtime, producing FALSE DISK_ONLY in fresh worktrees

**Probe (re-runnable):** scratchpad/probe_rc_batch.py: process_lock_guard.cross_checkout_edit_violations({'file_path': '<TEMP>/Documents/Trading/EdWebConsole/server.py'}) from this linked worktree, plus in-worktree negative control; operating_process_lock._db_content_change_epoch(WT, WT/'db.py') vs git log -1 --format=%ct -- db.py and db.py fs mtime; env -u ED_AGENT_ROLE pytest tests/test_operating_process_lock_v1.py -q

**Observed on current tree:** (a) the primary-checkout target BLOCKED with 'CROSS_CHECKOUT_EDIT (RC-442/RC-477)' and the in-worktree target returned []; (b) db.py is clean vs HEAD and the function returned 1787662103.0 == git commit time, NOT the fs mtime 1787661357.78 — content time, not checkout artifact; the 24-test suite passed (within 54-passed run)

**Note:** Gap (a)'s original role-based guard was deleted in the teardown; the RC-477 successor is role-free (.git-topology based) and is what fired here — the defect's protection exists and executes, under a different mechanism than the one this row originally shipped.

## RC-450 — DEFECT_ABSENT

**Defect (as originally measured):** Mandatory guards were subject-disableable via ED_*_GUARD/LOCK=off env, and a committed grant file authorized git commit --no-verify

**Probe (re-runnable):** scratchpad/probe_rc_batch.py: set six ED_*_GUARD/_LOCK=off env vars, reload operating_process_lock, call reset_guard_violations('git reset --hard HEAD~1'); operator_law_guard.bash_violations on 'git commit --no-verify -m msg', 'git commit -n -m msg', 'git -c core.hooksPath=/dev/null commit -m msg'; hasattr(_no_verify_grant_covers); exists(governance/operator_grants.json); env -u ED_AGENT_ROLE pytest tests/test_guard_bypass_class_v1.py tests/test_reset_guard_v1.py -q

**Observed on current tree:** With all kill-switch envs set to off the reset guard STILL blocked; --no-verify, git commit -n, and core.hooksPath each returned 'ACTION BLOCKED: this disables a mechanical lock. Only the operator may.'; _no_verify_grant_covers has no def and operator_grants.json does not exist; both class-lock suites passed (within 54-passed run)

**Note:** The env-off attempt was executed live against reloaded modules, not just asserted by tests — the subject-disable path does not exist in the current guard code.

## RC-453 — DEFECT_ABSENT

**Defect (as originally measured):** Privilege hard-coded to vendor names (current_agent_role default cursor, cursor-only role-flip checks, agent-writable enforcement surfaces, CODEOWNERS over the money path)

**Probe (re-runnable):** scratchpad/probe_rc_batch.py: import tools.writer_drift_lock (expect failure); os.path.exists('CODEOWNERS'); 'ED_AGENT_ROLE' in .claude/settings.json text; hasattr(operating_process_lock, 'current_agent_role'/'pm_status_field_violations'/'is_enforcement_surface')

**Observed on current tree:** tools.writer_drift_lock raises ModuleNotFoundError; CODEOWNERS absent; ED_AGENT_ROLE not in .claude/settings.json; current_agent_role, pm_status_field_violations and is_enforcement_surface all absent from operating_process_lock — no vendor-keyed privilege code path can execute

**Note:** Closure is teardown-by-removal: the vendor-role machinery was deleted wholesale (54e766dc), so the probe is executed absence (failed import, absent attrs) rather than corrected behavior — there is no role machinery left to be vendor-biased.

## RC-454 — DEFECT_ABSENT

**Defect (as originally measured):** Persisted writer=claude in governance/sole_writer.json / pm_mission.json was treated as executable authorization, letting the repository (not the operator) choose the working AI

**Probe (re-runnable):** scratchpad/probe_rc_batch.py: json.load attempts on governance/sole_writer.json and pm_mission.json; import tools.writer_drift_lock (resolved_writer machinery); executed text census over tools/*.py + server.py + db.py for any 'sole_writer'/'pm_mission' reference

**Observed on current tree:** Both loads raise FileNotFoundError (no persisted writer identity exists); writer_drift_lock (the resolved_writer reader) raises ModuleNotFoundError; the production census found ZERO files referencing either authority file — no executable path can read a repo-persisted writer as authorization

**Note:** Working-AI selection is now the operator's word in chat (RC-475); nothing in-tree persists or reads an agent assignment, so a stale assignment cannot outrank a live one.

## RC-455 — DEFECT_ABSENT

**Defect (as originally measured):** PreToolUse text classification of shell commands could not stop an assigned AI from taking pm_mission.json/sole_writer.json to deleted/malformed/pm!=operator states

**Probe (re-runnable):** scratchpad/probe_rc_batch.py: hasattr(pm_authority_shell_violations) on operating_process_lock, process_lock_guard, and operator_law_guard; os.path.exists on both protected files; executed reader census over tools/*.py + server.py + db.py

**Observed on current tree:** The leftover text classifier is gone (attr absent from all three guard modules), both target files do not exist, and the census shows zero production readers — even a recreated pm_mission.json with pm!=operator would authorize nothing, so the state the classifier failed to prevent is now meaningless

**Note:** The defect was closed by removing the resource and its authority-reader, not by better regex: PM authority moved out of the repository into the operator's chat ruling (RC-475), which no shell command can rewrite.

## RC-456 — DEFECT_ABSENT

**Defect (as originally measured):** Executable PM authority lived in the AI-owned git checkout; the demanded fix was a host-level external vault with fail-closed reads and no git-JSON fallback

**Probe (re-runnable):** scratchpad/probe_rc_batch.py: os.path.exists on tools/pm_authority.py, tools/pm_authority_helper.py, tools/install_pm_authority_host.sh, governance/pm_mission.json, governance/sole_writer.json; executed reader census over tools/*.py + server.py + db.py for authority-JSON references

**Observed on current tree:** Neither the planned external-vault wiring nor the git-tracked authority files exist (all False), and zero production code references them — there is no in-checkout executable PM state for the assigned principal to rewrite, and no fallback reader of git-tracked JSON

**Note:** The host-vault NEXT-DEPTH became moot by supersession: the teardown removed in-repo PM authority entirely rather than fencing it, which eliminates the defect's subject (authority-in-checkout) rather than hardening it.

## RC-472 — NOT_PROBEABLE

**Defect (as originally measured):** The FIND IT -> FIX IT law was not mechanically enforced, so the agent parked fixable defects as queued/recorded with no machine binding truth-status to permission-to-stop

**Probe (re-runnable):** scratchpad/probe_rc_batch.py: any('find_it_fix_it' in n for n,_,_ in check_institutional_correctness.CHECKS); hasattr fix_law_offenders/check_find_it_fix_it; 'fix_law' in inspect.getsource(tools.stop_guard); exists(governance/active_defects.json); plus Grep of governance/retired_checks.md row 'find_it_fix_it' and AGENTS.md line 25 principle

**Observed on current tree:** The enforcement machinery is wholly absent (check not in CHECKS, no fix_law_offenders, stop_guard has no fix_law wiring, active_defects.json deleted); governance/retired_checks.md carries the dated 2026-08-24 operator-teardown retirement row and AGENTS.md line 25 carries the surviving plain-instruction principle

**Note:** The defect's observable (an agent prematurely parking fixable work) needs a live agent session to manifest, and the enforcement machinery was retired wholesale by operator ruling (commit 992a9d9a) — deliberately, via the declared-retirement seam. Stand-in evidence executed this run: CHECKS census confirms the retirement is real (no half-wired remnant), retired_checks.md row names the operator ruling, AGENTS.md retains the principle. The current tree's lack of a mechanical enforcer is the operator-chosen state, not a regression.

## RC-473 — DEFECT_ABSENT

**Defect (as originally measured):** (A) the find-it-fix-it lock was vocabulary-driven and did not enforce; (B) compute_order_flow_verdict double-counted book/cum-delta/options and emitted a false BUYING/SELLING PRESSURE claim from an unvalidated composite

**Probe (re-runnable):** scratchpad/probe_rc_batch.py: AST FunctionDef census of order_flow_engine.py for _compute_order_flow_score/_direction/_readiness and of math_exposure.py for compute_order_flow_verdict; env -u ED_AGENT_ROLE .venv/Scripts/python.exe -m pytest tests/test_order_flow_engine_chunk1..4 tests/test_action11_2_order_flow_verdict_fail_closed.py -q

**Observed on current tree:** (B) the composite producers set intersection is [] and compute_order_flow_verdict has no def in math_exposure.py — the false operator claim has no producer to emit it; all 19 tests passed including the producer-deletion pins. (A) the rebuilt lock and active_defects.json are absent (probed under RC-472)

**Note:** Verdict covers the product half (B), which is the operator-facing defect and fully probeable: the emitting code path is deleted and its resurrection is pinned by executed tests. Half (A) shares RC-472's disposition — machinery retired by operator ruling via the declared seam (retired_checks.md row find_it_fix_it), confirmed absent by executed census.

## RC-474 — DEFECT_ABSENT

**Defect (as originally measured):** The retired order-flow composite's producers (_compute_order_flow_score/_direction/_readiness, compute_order_flow_verdict, OF_* constants) survived as dead false-semantic code that a call site could re-wire

**Probe (re-runnable):** scratchpad/probe_rc_batch.py: AST census of order_flow_engine.py (FunctionDefs + Assign targets prefixed OF_COMPOSITE_WEIGHT/OF_DIRECTION/OF_READINESS/OF_RVOL) and math_exposure.py; env -u ED_AGENT_ROLE pytest of the 5 order-flow chunk/action suites containing test_composite_score_direction_readiness_producers_are_deleted and test_compute_order_flow_verdict_producer_is_deleted

**Observed on current tree:** Producer intersection [], compute_order_flow_verdict absent, live OF_* composite constant assignments [], while canonical primitives (_compute_book_imbalance, _compute_spread, _compute_microprice-family, _compute_tape_pressure, _compute_cum_delta_proxy/_slope) remain defined; 19 tests passed including the resurrection-blocking pins

**Note:** Complete retirement verified at the producer level by executed AST census, not just at the call site — no executable path in the current tree can reconstruct the composite, and the pinning tests that would catch a resurrection ran green this session.
