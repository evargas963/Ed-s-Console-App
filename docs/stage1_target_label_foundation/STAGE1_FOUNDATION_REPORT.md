> **Classification:** Research Foundation Record | **Scope:** INSTITUTIONAL_TARGET_AND_LABEL_FOUNDATION_STAGE1_V1. Design + mechanical governance only. No production model/fusion/card/label change; no predictive-validity, calibration, or winner claim; nothing PRODUCTION_APPROVED.

# Stage 1 — institutional target & label foundation report

**Base:** `main @ a0f1a0eff4f02e3b5544db397ae5ee05516c9fd6` (finalized foundation, transplanted from original base `f7de7b3b`). **Branch:** `institutional-target-label-foundation-stage1-v1`.

## A. Canonical architecture delta (vs audit tip 27b9520)

`27b9520` is an ancestor of `main`; `main`'s tree hash `5c149cfa…` is **byte-identical** to `27b9520`'s (the PR-#41 merge brought exactly the audited tree onto main). **Architecture delta = EMPTY** — no subsequent commit changed target generation, outcome attachment, feature construction, model inference, empirical analog, fusion, cards, or decision policy.

## B. Current target / label inventory (audited)

Production labels are produced by `db.fill_outcomes → _apply_bar_based_outcome_updates` from the immutable `price_bars_1m` series (schema anchor `BAR_ANCHOR_V1 = 3`; spot-anchor v2 is dead/invalidated). Formula per anchor T: `anchor_close` = close of last bar with `bar_end_ts_utc ≤ T`; `forward_close` = close at `floor((T+N·60)/60)·60`; `pts = forward_close − anchor_close` (**raw, no cost**); `outcome = classify_direction_pts(pts, threshold)`; written only when the forward bar is complete. **No RTH/session filter is applied at label time.**

Status uses the **separated model** (schema_version 2): `CAUSAL_CONTRACT_PROVEN` (reconstructable — a causality statement only) is distinct from `EXPERIMENT_ELIGIBLE` (all readiness gates pass). Reconstructability does **not** confer eligibility.

| Target | Columns | Horizons | Status |
|---|---|---|---|
| tri-class `outcome_{H}` (+`_pts`) up/down/flat | 1c/5c/15c/60c | 4 | **LEGACY_BASELINE_ONLY** (deployed default, NOT_APPROVED; baseline to beat, never an entrant on its own merit); flat-majority 35–61% |
| raw `outcome_{H}_pts` | 4 | 4 | **CAUSAL_CONTRACT_PROVEN** (blocked from eligible by unflagged synthetic provenance + undefined overlap purge/embargo) |
| conditional `outcome_dir_{H}` + `valid_dir_{H}` | 4 | 4 | **CAUSAL_CONTRACT_PROVEN** (NOT eligible: placeholder thresholds, ~9.1% coverage, movement-v1 FAIL) |
| movement `outcome_move_{H}` + `threshold_move_{H}` | 4 | 4 | **CAUSAL_CONTRACT_PROVEN** (NOT eligible: same defects) |
| triple-barrier `outcome_tb_{H}` | scratch DB only | 4 | **CANDIDATE** (research scratch; idealized fills are a research assumption) |
| empirical-analog outcome | similarity cols | 4 | **CANDIDATE**; 500-neighbor cap + 21-day decay unjustified, neighbor set unpinned |
| spot-anchor v2 | — | — | **INVALID/dead** |

**Zero targets are `EXPERIMENT_ELIGIBLE`.** Stage 2 cannot run until at least one target's readiness gates are closed.

Key defects grounded first-hand: the committed `movement_target_thresholds_by_horizon_v1.json` is a **placeholder** (`selected_percentile: null`) inconsistent with the report's own selected p50 values; the DB materializes **only 4 horizons** (1c/5c/15c/60c) though the threshold JSON lists 7 (3c/8c/13c are O-10 diagnostic-only); movement labels cover **~9.1%** of governed rows; **no persisted movement/direction predictions** (movement-v1 FAIL).

The machine-readable inventory is `governance/research/stage1_target_label_foundation/target_registry_v1.json`.

## C–D. Candidate target families & horizon contracts

Fifteen candidate families are defined in the registry without selecting a winner, and NOT forced onto every horizon: execution-relevant (cost-adjusted move, prob-exceed-costs, immediate adverse excursion, abstention/OOD) lean 1c/5c; barrier/excursion (favorable-before-adverse, realized MFE/MAE, time-to-barrier) span 5c/15c; structure (continuation, failed breakout, value accept/reject) and regime (trend persistence, regime transition) are scoped to 15c/60c only. Each names its cost/barrier version and expected metrics.

## E. Causal timestamp & row identity

`research/stage1_target_foundation/causal_label_contract.py` reconstructs the production label from immutable `(ticker, bar_start_ts_utc, close)` identity and fails closed on lookahead, incomplete-bar use, timestamp aliasing (non-60s grid), duplicate anchors, cross-ticker attachment, and horizon confusion. **Correction (finalization):** the reconstruction applies **no session filter** — matching the deployed formula, which does **not** protect against session crossover; the module never contained a session guard. Session crossover is now surfaced **advisory-only** (`session_crossover`/`anchor_session`/`forward_session`) from the canonical `ts_utc → America/Chicago + exchange-calendar` authority (`ct_session`), and it **never** alters `outcome`/`pts`. **Horizon span:** the nominal `Nc` label realizes an anchor→forward span of **(N+1) minutes** (60c = 61 min), not N. Proven by `tests/test_stage1_causal_label_contract.py` (golden reconstruction cross-checked against an independent inline formula; crossover-advisory and MFE/MAE fail-closed cases) and a mutation matrix (lookahead/duplicate-anchor/aliasing/direction/incomplete-path all DETECTED).

## F. Session & cohort contracts

**Central Time is canonical (finalization).** `time_session_contract_v1.json` binds UTC as the immutable storage/join/causal authority and **America/Chicago** as the canonical application/research/cohort/display timezone; RTH is represented as **08:30–15:00 CT** (equivalent UTC instants to the exchange's 09:30–16:00 ET). `research/stage1_target_foundation/ct_session.py` is the session authority — DST resolved via `zoneinfo`, holidays/half-days from the exchange calendar (`data/trading_calendar/us_equities.json`), **no fixed offset**. `time_et.is_rth_ts_utc` is disclosed as **INSUFFICIENT** (no holiday/half-day awareness). Proven by `tests/test_stage1_ct_session.py` (12 cases: CST/CDT, spring-forward, fall-back, holiday closure, early-close half-day, RTH open/close and premarket/after-hours boundaries, no hard-coded offset).

`session_cohort_contract_v1.json` enumerates cohort dimensions (session, opening/closing window, intraday bucket, day-of-week, half-day/early-close, volatility regime, liquidity regime) with CT semantics and cross-cohort transfer policy (session pooling FORBIDDEN by default; half-day authoritative in Stage 1 research via the calendar; open/close windows PERMITTED_AS_FEATURE/EXPERIMENT). It documents — and `rth_integrity_audit.py` mechanically detects — the **OPEN RTH cohort-integrity contradiction**: `db.py:4417-4420` (operator accuracy) and `audit_model_readiness.py:29-34` still filter RTH on the DST-skewed stored `et_hour/et_minute` (the deprecated `ml_data_common.rth_where_clause` pattern), and `math_volatility.session_bucket` feeds the skewed session label back as a feature. **Not fixed in Stage 1** — the fix changes production accuracy/audit surfaces and requires separate authorization.

**Open-world blast radius (finalization).** The one-time open-world session/RTH blast-radius sweep and its artifact were retired under the ED CONSOLE SLIMMING directive (research tooling, not substance); the OPEN RTH cohort-integrity contradiction above remains mechanically detected by the retained `rth_integrity_audit.py`.

## G. Cost & utility foundation

`cost_model_registry_v1.json` versions the research cost models (`COST_V1_UNDERLYING_SPY` post-label-only from the pilot prereg; `EXEC_EV_SCAFFOLD_V1` fail-closed eval-time). Every economic target MUST name a non-NONE cost-model id (validator-enforced). Gaps: no observed-cost ledger in the governed DB (all economic labels estimated/scenario), no per-ticker/time-of-day cost surface, options costs unmodeled.

## H. Barrier / MFE / MAE foundation

Realized MFE/MAE are implemented as causal research labels in `causal_label_contract.py` (path max/min over the horizon window from OHLC), **distinct from the runtime Monte-Carlo forecast** (`monte_carlo.efe/eae`, which is not a label). **Fail-closed (finalization):** an incomplete path (any missing 1-minute bar in the excursion window) yields a NULL excursion with `reconstructable=false` — never a partial-path excursion — with declared basis (anchor close), sign, high/low-vs-close, and session-crossover conventions. Triple-barrier exists only in research (`research/pilot_step3/labeling.py` next-bar-open entry + T-1 Wilder ATR; D2 scratch DB) — barrier versions are registered as CANDIDATE, its **idealized barrier-price fill is marked a research assumption**, and `TRIPLE_BARRIER_ADOPTION = NOT_APPROVED_FOR_PRODUCTION`.

## I. Target registry

`target_registry_v1.json` (schema_version 2) + fail-closed validator (`target_registry.py`): **1 LEGACY_BASELINE_ONLY, 3 CAUSAL_CONTRACT_PROVEN, 7 CANDIDATE, 1 INVALID, 0 EXPERIMENT_ELIGIBLE, 0 PRODUCTION_APPROVED** (hard Stage 1 rule, test-locked). The validator computes `eligible = causal_contract_proven AND every applicable readiness gate`, and rejects any target whose declared status disagrees with its computed eligibility (`tests/test_stage1_target_registry.py`).

## J. Golden label dataset & reconstruction proof

`research/stage1_target_foundation/golden/` holds an immutable synthetic bar set and independently-computed expected labels; every label reconstructs deterministically. **Limitation:** the local governed DB (`data/ed_console.db`) is schema-only (0 rows) — reconstruction from the **real 62k-row governed population is NOT_PROVEN locally**; the golden proof establishes the label machinery is causal and correct, not that the governed DB is clean.

## K. Stage 2 experiment contract (design only)

`stage2_experiment_contract_v1.json` (schema_version 2): eligible entrants are selected **only** by the fail-closed `stage2_eligible_targets()` (registry `EXPERIMENT_ELIGIBLE` whose gates independently recompute eligible) — **currently empty**, so Stage 2 MUST NOT run. **Multiple-comparison control (finalization):** MCC is the preregistered primary classification metric; nested walk-forward with an **untouched single-use final holdout**; **FWER (Holm) / FDR (Benjamini-Hochberg)**, **White's Reality Check / Hansen SPA**, and **Deflated Sharpe** across the declared family; ≥5 seeds; class-imbalance by weighting/threshold (no SMOTE on overlapping series); an append-only model-selection log; **no post-hoc** target/metric/horizon switching. Purge + **embargo use the true span (≥61 min for 60c)**, still **MISSING** in `arch_competition/` (single-window OOS + half-split only). Baselines include always-WAIT, persistence, the legacy label, and a shuffle control that must score at chance. **STOP if no candidate beats the simple + legacy baselines after costs and multiple-comparison adjustment.** Not executed.

## L. Production containment (verified, already correct)

Existing governance already states the required containment, verified this mission: `the institutional master checklist (retired under ED CONSOLE SLIMMING):82` (TRIPLE_BARRIER_ADOPTION NOT_APPROVED_FOR_PRODUCTION, MODEL_PROMOTION NOT_APPROVED, REAL_MONEY_READINESS NOT_PROVEN); `CARD_TRUST_CONTRACT.md` (cards research telemetry; foundation-model excluded); `calibration_phase5_adaptive_weighting_foundation.md:21` (static fusion weights only); `promotion_engine.py:106-107` (auto-promote forbidden, raises). No false containment claim required correction.

## M. Readiness determinations

- `STAGE1_TARGET_INVENTORY = PROVEN` — every existing target identified + registered.
- `STAGE1_CAUSAL_LABEL_CONTRACTS = PROVEN` — candidate labels have reconstructable causal contracts with mechanical guards + mutation proof.
- `STAGE1_SESSION_COHORT_CONTRACTS = PROVEN` — cohort dimensions explicit; session mixing mechanically detected; contradiction disclosed OPEN.
- `STAGE1_COST_MODEL_CONTRACT = PROVEN` — every economic target names a versioned cost model (validator-enforced).
- `STAGE1_GOLDEN_LABEL_RECONSTRUCTION = PROVEN (synthetic)` — golden rows reconstruct; **real-governed-DB reconstruction NOT_PROVEN (no governed DB present)**.
- `DATA_FOUNDATION_READY_FOR_STAGE2_BASELINES = NO` — blocked on: real governed-DB golden reconstruction, movement/economic label coverage (~9.1%), the OPEN RTH cohort-integrity fix, and the missing purge/embargo/walk-forward machinery.

## N. Finalization & main transplant

The finalization corrected all independently-identified Stage 1 defects (status conflation, false session-crossover claim, ET-oriented session vocabulary, N-vs-N+1 span, absent multiple-comparison controls, MFE/MAE partial-path, bypassable Stage 2 entry) and transplanted the branch onto current canonical main by `git rebase --onto origin/main f7de7b3b` — clean, linear, no merge commit. Old→new commit map: `8e3476a → bebffa7`, `774cb1d → 16a3484`, `2d6c824 → b93d66f`. Lane-B (`calibration/backfill_outcomes.py`, `tests/test_backfill_outcomes.py`) was parked across the rebase and restored byte-exact (pins `84b080ac` / `383594a4`); it is not part of this branch. No push, PR, or merge was performed.

## Mandatory statuses

CURRENT_PRODUCTION_ARCHITECTURE = NOT_APPROVED · CURRENT_CARDS = UNTRUSTED_RESEARCH_TELEMETRY · CURRENT_FUSION_VALID = CONTRADICTED · CURRENT_LABEL_SYSTEM = NOT_APPROVED · PREDICTIVE_VALIDITY = NOT_PROVEN · CALIBRATION_VALIDITY = NOT_PROVEN · LEAKAGE_ABSENCE = NOT_PROVEN · TRAIN_LIVE_PARITY = NOT_PROVEN · FULL_MODEL_STACK = NOT_CLOSED · REAL_MONEY_APPROVAL = NOT_APPROVED · IMPLEMENTATION_CHANGE_TO_PRODUCTION_MODELS = NOT_APPROVED.
