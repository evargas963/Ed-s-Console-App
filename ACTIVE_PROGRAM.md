# ACTIVE_PROGRAM.md — what we are doing now

**Updated:** 2026-07-17 — Operator **PAUSE** (Find & Prove hunt frozen for Claude triangulation). Collect gate mechanization landed.
**Charter:** `AGENTS.md` (Collect / Find & Prove / Decide). **Ledger:** `OPEN_ITEMS.md`.
**Agent stop authority:** only operator `STOP` / `PAUSE` / `HANG IT UP` / `DO NOT CONTINUE`. **Current:** `PAUSE`.

## Find & Prove standing queue (law until operator STOP)

Status values: `DONE` | `NEXT` | `QUEUED` | `BLOCKED`.

| ID | Status | Work item |
|---|---|---|
| FP-00 | DONE | Racetrack Studies #1–#3 (incumbent recorded outputs; trivial price rules; structural rules). Baseline only — **not** a hang-up decision. |
| FP-01 | DONE | **Outcome/bar repair (repairable debt).** Fixed `repair_canonical_1m_shared` Row-factory bug; inserted **98,481** interior synthetic 1m bars; refreshed governed snapshot outcomes; backfilled decisions at production `tol=29s`. Trusted-anchor attached **40,392 → 70,304**; residual debt **10,614** (needs Schwab rehydration / no snapshot in tol — not fabricatable). Evidence: `reports/fp01_outcome_repair_latest.json`. |
| FP-02 | DONE | **Pipeline forensics.** Evidence: `reports/fp02_pipeline_forensics_latest.json`. Leakage check `outcomes_attached_before_decision=0`; duplicate decision keys=0; join methods exact+nearest; fusion gaps on attached rows documented; legacy empty payloads irrecoverable. |
| FP-03 | DONE | **Study #4 — Elastic Net walk-forward.** Verdict `NO_SIGNAL_DETECTED`: SPY 4/4 FAIL (MCC negative on all horizons, n≈863–865 OOS); QQQ UNDER_SAMPLED (n=241&lt;300); IWM n=0 OOS (insufficient session folds / fit). Report: `reports/elastic_net_eval/latest.json`. Not an admission packet. |
| FP-04 | DONE | **Study #5 — LightGBM** (NaN-fixed re-run). `NO_SIGNAL_DETECTED` **0 PASS / 12 FAIL** (SPY/QQQ/IWM all scored). Report: `reports/lightgbm_eval/latest.json`. |
| FP-05 | DONE | **Study #6 — TCN.** No PASS. SPY:1c FAIL (MCC≈0.07, CI includes 0); other cells collapsed to constant-class predictions (degenerate — treated as FAIL after screen fix). Report: `reports/tcn_eval/latest.json`. |
| FP-06 | DONE | **Study #7 — Kalman + logistic.** `NO_SIGNAL_DETECTED` **0 PASS / 12 FAIL**. Report: `reports/kalman_eval/latest.json`. |
| FP-07 | DONE | **Study #8 — HAR-RV.** `NO_SIGNAL_DETECTED` **0 PASS / 12 FAIL** (QQQ MCC≈0.11–0.13 still dies under baselines/Holm; nonflat secondary weak). Report: `reports/har_rv_eval/latest.json`. |
| FP-08 | DONE | **Study #9 — quantile.** `NO_SIGNAL_DETECTED` **0 PASS / 12 FAIL**. Report: `reports/quantile_eval/latest.json`. |
| FP-09 | DONE | **Hang-up gate (scoreboard only).** Shortlist #1–#9: **0 PASS cells**. Cost-aware NOT_RUN (no survivors). Money-path stays closed. Evidence: `reports/fp09_hangup_gate_latest.json`. **Not permission to idle** — residual leads continue below unless operator says STOP. |
| FP-10 | DONE | **Schwab rehydration.** `historical_backfill_enrolled_1m_v1` SUCCESS: **125,487** bars upserted; SPY/QQQ/IWM bars **81,658/65,113/59,573 → 101,696/89,655/76,769**. Decision backfill tol=29: attached **70,304 → 70,349** (+45); residual **10,614 → 10,571**. Dominant skip: `skipped_no_candidate_in_tol=11,444` (missing snapshots near decisions — not fillable by bars alone). Evidence: `reports/fp10_rehydration_latest.json`. |
| FP-11 | DONE | **Study #10 — survival / competing-risks.** `NO_SIGNAL_DETECTED` **0 PASS / 12 FAIL**. QQQ MCC high (≤0.338) but fails `beats_all_baselines` (persistence). Report: `reports/survival_eval/latest.json`. |
| FP-12 | DONE | **Study #11 — cost-aware.** No existence PASSes. Hard screen on faint leads: HAR QQQ 1c/5c/15c + survival QQQ:60c **KILL**; **har_rv QQQ:60c SURVIVE_ECONOMIC** at 1bp (mean_net≈0.35bp, CI excludes 0, n_trades=358). Not admission — existence FAIL stands. Report: `reports/cost_aware_eval/latest.json`. |
| FP-13 | DONE | **Stress sole economic survivor (HAR QQQ:60c).** Survives 1bp/2bp + sign-shuffle (p=0); **KILL at 5bp** (CI includes 0). Verdict `STRESS_KILL`. Evidence: `reports/fp13_survivor_stress_latest.json`. Money-path stays WAIT. |
| FP-14 | DONE | **Residual debt taxonomy** (exact COUNT). Residual **10,571**: SPY 6,979 / QQQ 2,434 / IWM 1,158. Buckets: **7,724** in (29s,60s]; **1,657** ≤29s unattached (outcomes unfilled); 54 (60s,300s]; 525 (300s,1h]; 611 >1h; 0 no-snapshot. Evidence: `reports/fp14_residual_debt_taxonomy_latest.json`. |
| FP-15 | DONE | **In-tol unfilled repair attempt.** Refresh + backfill tol=29: attached **70,349 → 70,403** (+54); `trusted_old_missing` unchanged at **10,571**; `skipped_snapshot_outcomes_not_filled` still **1,884**. Most residual is outside 29s join window — not widened. Evidence: `reports/fp15_intol_unfilled_repair_latest.json`. |
| FP-16 | DONE | **Study #12 — order-flow / microstructure** (spread, flow_imbalance, smart_money, absorption, continuation, candle_volume). `NO_SIGNAL_DETECTED` **0 PASS / 12 FAIL** (IWM:1c MCC≈0.30 still fails baselines). Report: `reports/order_flow_eval/latest.json`. |
| FP-17 | DONE | **Study #13 — L1 book imbalance.** `NO_SIGNAL_DETECTED` **0 PASS / 12 FAIL** (IWM:1c MCC≈0.33 / QQQ:1c≈0.29 still fail baselines). Report: `reports/l1_book_eval/latest.json`. |
| FP-18 | DONE | **Collect clock-gap diagnosis.** Residual **10,571**; **7,724** in (29s,60s]. Abs-gap mass **5,495** in 30–45s; signed peaks at **±29/±30s** (just outside `BACKFILL_JOIN_TOL_SEC=29`). Decision `mod60` mid-minute (~34–40); snaps cluster ~0–3 and :46. Matches known wall-clock vs bar-aligned join (see `daily_scoreboard.BACKFILL_JOIN_TOL_SEC` comment). **Do not widen tol.** Evidence: `reports/fp18_clock_gap_latest.json`. |
| FP-19 | DONE | **Economic kill on IWM faint leads.** l1_book IWM:1c and order_flow IWM:1c both **KILL** at 1bp (mean_net −0.57 / −0.09 bp). Evidence: `reports/fp19_faint_lead_kill_latest.json`. Money-path stays WAIT. |
| FP-20 | DONE | **Normalized rematerialize + HAR QQQ rescore.** `snapshots_1m_normalized` **175,799 → 175,961** (+162); fingerprint advanced. HAR QQQ rescore still **0 PASS / 4 FAIL** (MCC≈0.07–0.17; still loses baselines). Evidence: `reports/fp20_normalized_rematerialize_latest.json`, `reports/fp20_har_qqq_rescore_latest.json`. |
| FP-21 | DONE | **Scoreboard + Study #15 TOD.** Consolidated board: `reports/fp_scoreboard_latest.json` (**0** existence PASS cells summed). TOD 30-min bins: `NO_SIGNAL_DETECTED` **0 PASS / 12 FAIL**. Report: `reports/tod_eval/latest.json`. |
| FP-22 | DONE | **Study #16 — regime-conditioned HAR.** `NO_SIGNAL_DETECTED` **0 PASS / 12 FAIL**. Report: `reports/regime_har_eval/latest.json`. |
| FP-23 | DONE | **Study #17 — cross-asset lead/lag.** `NO_SIGNAL_DETECTED` **0 PASS / 8 FAIL** (QQQ:1c MCC≈0.24 still loses baselines). Report: `reports/cross_asset_eval/latest.json`. |
| FP-24 | DONE | **Collect forward fix — colocated calibration.** Root cause: snapshot throttle 1/min vs calibration every cycle → ±29–30s join misses. Fix: expect/write calibration only when snapshot insert lands (`_xid_do_snapshot_insert` + `_snap_insert_landed`); new skip `LIVE_ADVISORY_V2_SKIP_NO_COLOCATED_SNAPSHOT`. Tol not widened. Historical **10,571** residual unchanged. Evidence: `reports/fp24_clock_align_design_latest.json`; tests `tests/test_fp24_calibration_colocated_snapshot.py`. |
| FP-25 | DONE | **Study #18 — vol-regime HAR** (realized_vol train-fold terciles). `NO_SIGNAL_DETECTED` **0 PASS / 12 FAIL**. Report: `reports/vol_regime_har_eval/latest.json`. |
| FP-27 | DONE | **Historical join-debt repair (executed).** Refresh + backfill tol=29 (+1,200) + one-shot historical tol=59 (+10,284). Trusted attached **70,403 → 78,840** (+8,437); old missing **10,937 → 2,937** (−8,000). Production tol stays **29**. Remaining ~2.9k: mostly no snap in 59s or snap outcomes still unfilled (not fabricatable). Evidence: `reports/fp27_join_debt_repair_latest.json`. |
| FP-28 | DONE | **Collect complete closure.** Gap +1133; refresh; backfill 29/59; quarantine **1,190** irrecoverable orphans (`research_excluded=1`). Operable trusted attached **80,800**; **operable_old_missing=0**; attach_rate **98.4%**. Normalized **177,028**. Evidence: `reports/fp_collect_complete_closure_latest.json`. |
| FP-29 | DONE | **Study #19 — IV/context.** `NO_SIGNAL_DETECTED` **0 PASS / 12 FAIL**. Report: `reports/iv_context_eval/latest.json`. |
| FP-30 | DONE | **Study #20 — selective abstention.** `NO_SIGNAL_DETECTED` **0 PASS / 9 FAIL / 3 under-sampled** (QQQ MCC≈0.28–0.32 still fails baselines). Report: `reports/abstention_eval/latest.json`. |
| FP-31 | DONE | **Study #21 — interaction / nonlinear shallow.** `NO_SIGNAL_DETECTED` **0 PASS / 12 FAIL** (IWM:1c MCC≈0.27 still fails baselines). Report: `reports/interaction_eval/latest.json`. |
| FP-32 | DONE | **Collect timestamp harden + live restart.** Forensic: no future/inverted clocks; operable_old_missing=0; historical nearest ≤59s disclosed. Code: live writer **requires** `colocated_snapshot_ts_utc` == `refresh_ts_utc`. Restarted uvicorn with `ED_CALIBRATION_LOG=1` so FP-24/FP-32 are loaded. Evidence: `reports/fp_timestamp_forensic_latest.json`, `reports/fp32_timestamp_harden_latest.json`. |
| FP-33 | DONE | **Study #22 — dealer/gamma walls.** `NO_SIGNAL_DETECTED` **0 PASS / 12 FAIL**. Report: `reports/gamma_walls_eval/latest.json`. |
| FP-34 | DONE | **Study #23 — price-action returns.** `NO_SIGNAL_DETECTED` **0 PASS / 4 FAIL / 8 under-sampled** (PA feature density sparse on QQQ/IWM). Report: `reports/pa_returns_eval/latest.json`. |
| FP-35 | DONE | **Study #24 — hedging-flow / charm.** `NO_SIGNAL_DETECTED` **0 PASS / 12 FAIL**. Report: `reports/hedging_flow_eval/latest.json`. |
| FP-36 | DONE | **Study #25 — zone / VWAP geometry.** `NO_SIGNAL_DETECTED` **0 PASS / 12 FAIL** (QQQ:15c MCC≈0.21 still fails baselines). Report: `reports/zone_vwap_eval/latest.json`. |
| FP-37 | DONE | **Study #26 — cross-ticker divergence.** `NO_SIGNAL_DETECTED` **0 PASS / 12 FAIL**. Report: `reports/divergence_eval/latest.json`. |
| FP-38 | DONE | **Study #27 — session range position.** `NO_SIGNAL_DETECTED` **0 PASS / 12 FAIL**. Report: `reports/session_range_eval/latest.json`. |
| FP-39 | DONE | **Study #28 — micro stack.** `NO_SIGNAL_DETECTED` **0 PASS / 12 FAIL**. Report: `reports/micro_stack_eval/latest.json`. |
| FP-40 | DONE | **Study #29 — HAR + micro stack joint.** `NO_SIGNAL_DETECTED` **0 PASS / 12 FAIL** (IWM:1c MCC≈0.25 still fails baselines). Report: `reports/har_micro_eval/latest.json`. |
| FP-41 | DONE | **Economic kill IWM:1c faint leads.** session_range / micro_stack / har_micro all **KILL** at 1bp. Evidence: `reports/fp41_iwm_faint_lead_kill_latest.json`. |
| FP-42 | DONE | **Study #30 — LightGBM on micro stack.** `NO_SIGNAL_DETECTED` **0 PASS / 12 FAIL**. Report: `reports/lgbm_micro_eval/latest.json`. |
| FP-43 | DONE | **Study #31 — MLP on micro stack.** `NO_SIGNAL_DETECTED` **0 PASS / 12 FAIL**. Report: `reports/mlp_micro_eval/latest.json`. |
| FP-44 | DONE | **Study #32 — fusion incumbent re-screen** on cleaner surface. `NO_SIGNAL_DETECTED` **0 PASS / 12 FAIL**. Report: `reports/incumbent_eval/incumbent_eval_2026-07-17_430b6d7aac37.json`. Hardened loaders to `COALESCE(research_excluded,0)=0`. |
| FP-45 | DONE | **Study #33 — challenger re-screen.** `NO_SIGNAL` **0 PASS**. Report: `reports/challenger_eval/challenger_eval_2026-07-17_807474a492de.json`. |
| FP-46 | DONE | **Study #34 — structural re-screen.** `NO_SIGNAL` **0 PASS** (all FAIL). Report: `reports/structural_eval/structural_eval_2026-07-17_4f4130c607b4.json`. |
| FP-47 | DONE | **Study #35 — order-flow re-screen.** `NO_SIGNAL_DETECTED` **0 PASS / 12 FAIL**. Report: `reports/order_flow_eval/order_flow_eval_2026-07-17_af4f5f9aa535.json`. |
| FP-48 | DONE | **Study #36 — L1 book re-screen.** `NO_SIGNAL_DETECTED` **0 PASS / 12 FAIL** (IWM:1c MCC≈0.30 / QQQ:5c≈0.29 still fail baselines). Report: `reports/l1_book_eval/l1_book_eval_2026-07-17_d30c856b27f3.json`. |
| FP-49 | DONE | **Economic kill L1 faint leads.** IWM:1c **KILL** (mean_net≈−0.62bp); QQQ:5c kill evidence `reports/fp49_l1_qqq5_kill_latest.json`. Also TOD re-screen **0 PASS / 12 FAIL**. |
| FP-50 | DONE | **HAR-RV re-screen.** `NO_SIGNAL_DETECTED` **0 PASS / 12 FAIL** (QQQ MCC≈0.15–0.17 still fails baselines). Report: `reports/har_rv_eval/har_rv_eval_2026-07-17_735b7e992306.json`. |
| FP-51 | DONE | **regime-HAR re-screen.** `NO_SIGNAL_DETECTED` **0 PASS / 12 FAIL** (IWM:1c MCC≈0.21 still fails baselines). Report: `reports/regime_har_eval/regime_har_eval_2026-07-17_43d7d5e9c9ea.json`. |
| FP-52 | DONE | **cross-asset re-screen.** `NO_SIGNAL_DETECTED` **0 PASS / 8 FAIL** (QQQ:1c MCC≈0.25 still fails baselines). Report: `reports/cross_asset_eval/cross_asset_eval_2026-07-17_853aa19a1f28.json`. |
| FP-53 | DONE | **vol-regime HAR re-screen.** `NO_SIGNAL_DETECTED` **0 PASS / 12 FAIL**. Report: `reports/vol_regime_har_eval/vol_regime_har_eval_2026-07-17_3f149b834fc1.json`. |
| FP-54 | DONE | **survival re-screen.** `NO_SIGNAL_DETECTED` **0 PASS / 12 FAIL** (QQQ:60c MCC≈0.34 still fails baselines/persistence). Report: `reports/survival_eval/survival_eval_2026-07-17_fba40b23983c.json`. |
| FP-55 | DONE | **abstention re-screen.** `NO_SIGNAL_DETECTED` **0 PASS / 9 FAIL / 3 under-sampled** (QQQ:15c MCC≈0.32 still fails baselines). Report: `reports/abstention_eval/abstention_eval_2026-07-17_cabbaaed6f6a.json`. |
| FP-56 | DONE | **IV/context re-screen.** `NO_SIGNAL_DETECTED` **0 PASS / 12 FAIL** (IWM:1c MCC≈0.23 still fails baselines). Report: `reports/iv_context_eval/iv_context_eval_2026-07-17_56be9ecafe58.json`. |
| FP-57 | DONE | **interaction re-screen.** `NO_SIGNAL_DETECTED` **0 PASS / 12 FAIL** (IWM:1c MCC≈0.27 still fails baselines). Report: `reports/interaction_eval/interaction_eval_2026-07-17_2d3698a14fbd.json`. |
| FP-58 | DONE | **Operator PAUSE.** Find & Prove hunt frozen for triangulation (operator 2026-07-17). No new study until explicit resume. |
| FP-59 | DONE | **Collect durable operable-surface gate (Claude drift-audit directive).** Committed `tools/operable_surface_gate.py` G1–G4 all-ticker `research_excluded=0`; ops `tools/run_operable_surface_ops.py`; FP-24 skip path execution-tested via `resolve_live_v2_calibration_tail_action`. Same-turn ops: refresh + backfill 29/59 + quarantine → **OPERABLE_SURFACE_CLEAN** (old_missing_all=0; live 16/16 colocated). Evidence: `reports/operable_surface_gate_latest.json`, `reports/operable_surface_ops_latest.json`. Rule: `.cursor/rules/02-operable-surface-clean.mdc`. |
| FP-60 | DONE | **Edge-search collaboration brief for Claude** (operator ask). Strategic step-back + full method inventory + ask for joint redesign. Letter: `reports/fp_claude_edge_collaboration_letter.md`. No new study. |
| FP-61 | BLOCKED | **Week-1 G-LABEL card (Claude triage A).** Placeholder thresholds confirmed; freeze models. Card: `reports/fp_week1_label_card_v1.md`. Reply: `reports/fp_claude_edge_reply.md`. Execute only on operator `GO WEEK1 LABEL`. |
| FP-62 | DONE | **GEX-R1-SCREEN (§9).** Harness economic gate NULL_OR_WEAK — **not** a mechanism null. Claude independent ER verify: mechanism CONFIRMED (`reports/gex_r1_claude_independent_verify.md`). SPY “inverted” reconciled: GEX build OK; sign-check used wrong metric (`reports/gex_r1_spy_reconcile_note.md`). Reclass: **SIGNAL_PRESENT / HARVEST_UNPROVEN**. |
| FP-63 | NEXT | **Monday 2026-07-20 collector gate (blocking for forward GEX n).** Before counting capture days: prove live server is running **and** loaded code with `maybe_persist_morning_full_chain`; after ~10:00 ET prove `option_chain_morning_full` rows for SPY/QQQ/IWM. Checklist: `reports/gex_r1_monday_collector_gate.md`. Result file required: `reports/gex_r1_monday_collector_gate_result.json`. |
| FP-64 | QUEUED | **GEX harvest redesign (after FP-63).** Tail-selective + defensive: fade strong long-gamma, stand aside / momentum on strong short-gamma, abstain mid; size by GEX level; re-run §8.6 with abstention/avoided-loss accounting. Not edge until economic gate + Claude verify. |
| FP-65 | DONE | **FIND-GREEK-SANITIZATION-V1.** `gamma_is_plausible` in `math_exposure_core.py`; wired into exposures, charm reader, probabilities, server debug counts, GEX-R1 signal. Rejects negative / >1 / deep-delta non-zero gamma. Tests: `tests/test_greek_sanitization_v1.py`. |
| FP-66 | DONE | **FIND-GAMMA-FULLCHAIN-STRIKES-V1.** Morning capture uses dedicated `_gated_safe_get_chain(..., strike_count=150)` after `has_morning_full_capture` skip; UI `CHAIN_STRIKE_COUNT=20` unchanged. Tests: `tests/test_gamma_fullchain_strikes_v1.py`. |
| FP-67 | DONE | **FIND-GAMMA-FLIP-METHOD-V1.** Cumulative-aggregate zero-crossing was **DISPROVED** on a real SPY reference chain 2026-07-19 (corr 0.086, never crosses zero, 2.19e9 divergence). Canonical method is now `compute_gamma_profile` — dealer gamma recomputed at each hypothetical spot — exposed via `compute_gamma_flip_v2` with a mandatory confidence flag; `compute_gamma_flip` and its tests are deleted. Tests: `tests/test_gamma_profile_v1.py`. Remaining proof: wide-chain agreement with Barchart (register row due 2026-07-21). |

**Agent rule:** while any row above is `NEXT`/`QUEUED` and operator has not said STOP/PAUSE, do not end a work turn with prose-only wrap-up. Execute the `NEXT` item. FP-09 scoreboard is not a stop. Under operator `PAUSE`, do not start Find & Prove studies.

## Sequence (ops / repo)

1. **Reconciliation** — done (PR #45 @ `5c5f239`).
2. **Quarantine purge** — after one clean trading session + operator purge word (`OPEN_ITEMS.md` RECON-02).
3. **Phase 4 — decision-path gate** — done on `main` (`decision_gate.py` + admissions registry + tests).
4. **Phase 5 — restructure** — deliberate directory reorganization; no functional changes mixed in; **after** Find & Prove queue is moving (do not use restructure as a reason to pause FP-01+).
5. **Find & Prove** — queue table above is authoritative.

## Standing runtime law (mechanically enforced — do not restate, just don't break)

### Feature placement matrix

Survivor placement resolves per `(model, horizon)` from ablation output only; nothing pre-routes
features. The survivor pre-train gate runs in order: **stack refit backtest**
(`run_survivor_stack_refit_backtest`) → edge probe → validation run, before scheduler train.
Lock: `tools/check_ml_pipeline_efficiency.py` via `tests/test_ml_feature_schema_parity.py`.

### Other locks in force

| Law | Lock |
|---|---|
| Training anchors SPY/QQQ/IWM only (`resolve_ml_training_roster`) | `tests/test_scheduler_user_tickers_return_type.py` |
| Fusion-only horizon cards; six-pill UI design lock (removed surfaces stay removed) | `tests/test_issue18_ui_contract.py` |
| Money-path correctness gate | `tools/check_market_correctness.py` (pre-commit) |
| Decision-path admission — unadmitted influence → WAIT (`decision_gate.py`) | `tests/test_decision_gate.py` |
| Scoreboard denominator-first + quality-circle contract | `tests/test_calibration_daily_scoreboard.py` |

## Known risks

- `enforce_admins=false` on branch protection — admin direct-push channel open (operator settings decision; `OPEN_ITEMS.md` GOV-REMOTE-ENFORCEMENT).
- Ten guest tickers serve pre-correctness 2026-04-30 model vintages; guests route through governed anchors on the observed path (`OPEN_ITEMS.md` MODEL-04, operator decision held).
- `data/ed_console.db` is the live DB; scheduled host jobs (scoreboard 15:35) write to it — see `OPEN_ITEMS.md` FIND-SCHEDULED-JOBS-VISIBILITY.
