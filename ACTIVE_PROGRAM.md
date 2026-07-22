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

## Terrain upgrade program — TU (2026-07-21 research synthesis)

Source: four-track deep research (positioning inference / beyond-GEX exposures / vol-surface
fields / world data), full citations in the 2026-07-21 session. Operator mechanical lock:
world data is always in scope; "not adoptable with our data" is a banned disposition.
Verified already-held (no work): per-contract-IV (skew-adjusted) gamma profile;
hypothetical-spot flip recompute (the method SqueezeMetrics/Perfiliev/FlashAlpha document);
`pick_hvl_strike` ≡ SpotGamma Absolute Gamma Strike.

| ID | Status | Work item |
|---|---|---|
| TU-01 | DONE | **World-data collectors** `tools/world_data_ingest.py` + tests. Tables populated 2026-07-21: `world_dix` 3,826 (2011→), `world_vol_index` 28,438 (VIX/VIX9D/VIX1D/VVIX/SKEW full history), `world_finra_short_volume` 48,565 (4 days), `world_occ_volume` 1,509 (account-type-classified C/F/M — the free open-close proxy), `world_cftc_tff` 189. FINRA 403=not-published-yet handled. Needs: daily cron + retention policy. |
| TU-02 | DONE | **New levels** `pick_key_delta_strike` (total DEX$ magnet) + `pick_volatility_point_strikes` (HVP/LVP signed net-GEX$ extremes), fail-closed without dollarization. Tests in `tests/test_institutional_key_levels.py` (8 pass). Server/UI wiring = next commit (import from `math_exposure_core`). |
| TU-03 | DONE | **Wall hold-rate scorecard** in `tools/terrain_backtest_report_v1.py`. Baseline 2026-07-21 (1,054 ticker-days): call walls held 70.6% / close≤CW 83.2% (n=802); put walls held 72.3% / close≥PW 85.6% (n=776). External context: SpotGamma SPX 83/88/89/93. This metric replaces the median-split as the primary wall KPI. |
| TU-04 | QUEUED | **Single-name dealer-sign A/B.** Garleanu-Pedersen-Poteshman Table 1: single-name puts are dealer-LONG on average — naive −putOI is backwards for equities. Build `sign_model=empirical_prior` as a PARALLEL profile (never silent swap; index/ETF keeps naive — validated by Baltussen JFE 2021), score both in the scorecard, promote on evidence. Merges with registered single-name row due 2026-08-03. |
| TU-05 | QUEUED | **VEX/CEX**: closed-form BS vanna aggregation (charm exists); publish per-vol-pt and spot-vol-beta-coupled units. Capture-side: persist chain top-level `interestRate`, `dividendYield`, `isChainTruncated` (currently dropped before storage). |
| TU-06 | QUEUED | **Cremers-Weinbaum call−put IV spread** (matched-strike, OI-weighted; ~50bps/wk JFQA 2010) + **implied 1-day move** (total-variance interpolation, VIX-style) + own containment stats per ticker. |
| TU-07 | QUEUED | **ΔOI flow signals** (Fodor 2011 call/put ΔOI ratio — the only published signed daily-data signal). Backfillable from 103 days × 52 tickers already in `snapshots`. Join OCC account-type volume (MM share, customer P/C split) as conditioning fields. |
| TU-08 | QUEUED | **Regime dead-zone**: NEUTRAL band + N-close persistence around the flip (SpotGamma ZG-vs-VT architecture; SqueezeMetrics near-zero = no interference). Thresholds backtested in-house, placebo-anchored. |
| TU-09 | QUEUED | **GEX$/ADV$ normalization** (Barbon-Buraschi — only peer-reviewed cross-ticker scaling) using our own 1m-bar ADV; add cross-ticker rank to terrain. |
| TU-10 | QUEUED | **External GEX benchmark**: reconcile our SPY dealer-gamma series against SqueezeMetrics 15y `world_dix.gex` (SPX). Divergence = investigation, not silent trust. |
| TU-11 | QUEUED | **Skew/term fields**: XZZ smirk (10.9%/yr JFQA 2010), Vasquez term-slope, delta-interpolated 25Δ RR — into daily per-ticker logging for later admission testing. |
| TU-12 | QUEUED | **DDOI-lite** intraday snapshot-signing reconciled vs nightly ΔOI (SqueezeMetrics worked example). UNPROVEN at snapshot frequency — register on build; validation design = reproduce Baltussen conditional-momentum split on our own history. |

**Won't build** (dispositioned, not deferred): unsigned net-premium (direction-blind folklore);
max-pain-as-target (expiry-day pinning only — NPP 2005); BKM risk-neutral-skew quadrature
(documented sparse-strike bias; RR25 first); paid Cboe Open-Close (only if TU-07's free OCC
signal proves decision-critical).

## Console rebuild program — CR (v1.2 CONSENSUS-STAMPED; operator GO 2026-07-21 "lets build it")

**GO given on the v1.2 spine. CR-01 IN PROGRESS** — `stream_spine.py` landed (bus with
cache-then-publish + bounded queues w/ drop counters, HealthRegistry RUNNING/DEGRADED/
STALE/DOWN, CaptureWriter into dedicated stream_capture.db with a construction-time
refusal of ed_console.db; 6 contract tests). Next unit: the capture daemon
(`tools/run_stream_capture.py`, schwab-py StreamClient → bus), live-acceptance at the
next market open per CR-01's measured criteria. v1.3 delta (15 agreed items incl. Kimi
round: CR-08 three-way MBP/MBO redesign, CR-07 statistical spec + pre-registered N,
measure-then-freeze numeric bounds, MM-share chip, market_stress_index candidate, three
pre-registered ML paths) rides OFF the GO-critical path — next consensus round folds it in.

Cursor architectural review 2026-07-21: **CONDITIONAL APPROVE / BLOCK GO until v1.1** —
all findings incorporated in `governance/CONSOLE_REBUILD_PLAN_CR_V1.md` (v1.1): separate
`stream_capture.db` (RC-6 lesson, was blocking), bounded-queue + parse-p99 + contention
matrix in CR-01 acceptance, mechanical CR-CAP capture gate, CR-03 rescoped (registry and
volume profile deferred; ML demote-not-delete), pre-registered arming thresholds, UI-copy
law (no paper rates in tiles), CR-06 trust labels gated on CR-08, sentinel-first book
subscriptions, canonical-1m stays sole bar authority, decision-path admission for any
TRADE-shaping tile.

Verdict: REBUILD the console's decision layer (ML-stack surfaces retire per the demotion
decision); KEEP the data spine (Schwab ingest, canonical 1m, SQLite, terrain). Free
order-flow stack verified live: Schwab Streamer (L1 bid/ask/sizes conflated ~500ms +
NYSE/NASDAQ_BOOK depth + CHART_EQUITY 1m; ≤500 keys/connection — assume OVER budget for
L1+dual-books+internals until CR-01 measures the real key accounting, sentinel-first
books; NO trade prints — TIMESALE dropped from the new API) + Alpaca free IEX websocket
(true trade prints, 30 symbols). Evidence
law from the four-track review: every surviving intraday effect is flow-MECHANICAL and
tail-concentrated; OFI/flow EXPLAINS (contemporaneous OOS R² 65-84%) but does NOT predict
minutes ahead (forward R² negative) — flow is instrumentation and regime, never a
standalone directional oracle.

| ID | Status | Work item |
|---|---|---|
| CR-01 | IN PROGRESS | **Streaming spine**: Schwab streamer client (LEVELONE_EQUITIES QOS-Express + CHART_EQUITY + sentinel-first books), topic bus + last-value cache, single batched writer into dedicated **`stream_capture.db`** (ed_console.db grows by ZERO bytes), per-feed health states. Acceptance: bounded queues w/ recorded max depth + drop count + parse p99; REST/streamer/terrain contention matrix; measured key accounting. |
| CR-02 | QUEUED | **Trade prints + CVD (capture)**: Alpaca free IEX websocket (operator opens free account), 30-symbol prints, quote-rule signing, CVD; Schwab-signed vs IEX-signed correlation recorded ≥3 sessions. |
| CR-CAP | QUEUED | **Mechanical capture gate**: ≥3 full RTH sessions in stream_capture.db before ANY UI consumes stream topics — display paths refuse to mount pre-gate (fail-closed test). |
| CR-03 | QUEUED | **Console shell**: typed-message websocket replaces polling loops; main chart panel (lightweight-charts, levels-on-chart, VWAP as fair-value reference only); **demote/hide chance-level ML DOM (hard-delete only per §8.3)**. Panels registry + volume profile deferred to CR-03b. |
| CR-04 | QUEUED | **Regime internals (self-computed, register rows)**: U-shape-normalized RVOL ("range/vol conditioning" copy, never "forecast" pre-CR-07); cross-sectional dispersion + tick-breadth/A-D over streamed constituents (universe sized by CR-01's measured key budget; TICK thresholds = folklore, self-validate vs $TICK). |
| CR-05 | IN PROGRESS | **Evidence tiles / CARD PIPELINE** — referee decoupled from player: ALL designs authored externally (Gemini adversarial audits 2026-07-21/22), executed here verbatim, verdicts by 10k-permutation + power gates. STATE: **#1 Baltussen gamma** PENDING (index arm accrues from wide captures — untestable on narrow-chain history; singles n=42/100, needs earnings scrub); **#2 Gao RV momentum** KILLED on singles (n=295, margin −2.1pts, p=0.7524; sentinels accrue; AM/hist gates disclosed); **#3 MOC anticipation** WAITING on sub-minute stream TWAP (NO 1m approximation — external constraint); **#4 Exhaustion reversal** PRE-REGISTERED 2026-07-22 (external spec verbatim: predictor 09:30→15:30, arm ≥1.0× 20d median intraday range, response 15:30→15:55, hit = sign flip, placebo <0.5× quiet days, OUT-OF-SAMPLE LOCK — forward data from 2026-07-22 ONLY, Mar–Jul history contaminated by discovery; singles additionally blocked on earnings scrub; ship bar: n≥100 forward, p<0.05, margin ≥+4.0pts for spread costs). Named data task: free earnings calendar → scrub #1, unblock #4 singles. |
| CR-06 | QUEUED | **Flow instrumentation pane**: snapshot-OFI + signed-volume + depth imbalance with the literal label "explains, does not predict"; impact coefficient on an explicit trailing window with written leakage rules; **trust labels gated on CR-08's conflation numbers**. |
| CR-07 | QUEUED | **Promotion gate (mechanical)**: unproven-register row + PDCA scorecard per construct; no directional prompt before beating its placebo; **TRADE-shaping tiles additionally pass decision-path admission (`decision_gate.py`)**. ORB-on-RVOL = validation candidate only. |
| CR-08 | QUEUED | **One-time calibration study**: Databento $125 credits — measure what 500ms conflation destroys vs full tape for OFI/signing on SPY; gates CR-06 trust labels. |

**Kills (do not build as predictors)**: VPIN (Andersen-Bondarenko: zero incremental power
vs volume+RV), TICK-extreme rules, VWAP-magnet, unconditional intraday momentum,
overnight-drift harvest (NightShares liquidated), minutes cross-asset lead-lag (ES/VIX/
bond→equity all HFT-arbed), DIX thresholds (vendor-only evidence; replicate in-house from
FINRA inputs before any use), naive FINRA short-ratio reads (FINRA's own notice), 0DTE
net-flow direction (retail lottery demand), gap-fill percentages, book heatmap/footprint/
DOM eye-candy at minutes horizons.

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
