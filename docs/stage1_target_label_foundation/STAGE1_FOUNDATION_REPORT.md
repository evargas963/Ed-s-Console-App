> **Classification:** Research Foundation Record | **Scope:** INSTITUTIONAL_TARGET_AND_LABEL_FOUNDATION_STAGE1_V1. Design + mechanical governance only. No production model/fusion/card/label change; no predictive-validity, calibration, or winner claim; nothing PRODUCTION_APPROVED.

# Stage 1 — institutional target & label foundation report

**Base:** `main @ f7de7b3b168f444a6fc7693922b57d6d8265a561`. **Branch:** `institutional-target-label-foundation-stage1-v1`.

## A. Canonical architecture delta (vs audit tip 27b9520)

`27b9520` is an ancestor of `main`; `main`'s tree hash `5c149cfa…` is **byte-identical** to `27b9520`'s (the PR-#41 merge brought exactly the audited tree onto main). **Architecture delta = EMPTY** — no subsequent commit changed target generation, outcome attachment, feature construction, model inference, empirical analog, fusion, cards, or decision policy.

## B. Current target / label inventory (audited)

Production labels are produced by `db.fill_outcomes → _apply_bar_based_outcome_updates` from the immutable `price_bars_1m` series (schema anchor `BAR_ANCHOR_V1 = 3`; spot-anchor v2 is dead/invalidated). Formula per anchor T: `anchor_close` = close of last bar with `bar_end_ts_utc ≤ T`; `forward_close` = close at `floor((T+N·60)/60)·60`; `pts = forward_close − anchor_close` (**raw, no cost**); `outcome = classify_direction_pts(pts, threshold)`; written only when the forward bar is complete. **No RTH/session filter is applied at label time.**

| Target | Columns | Horizons | Status |
|---|---|---|---|
| tri-class `outcome_{H}` (+`_pts`) up/down/flat | 1c/5c/15c/60c | 4 | **PRODUCTION default, but NOT_APPROVED**; flat-majority 35–61% |
| raw `outcome_{H}_pts` | 4 | 4 | research/regression signal |
| conditional `outcome_dir_{H}` + `valid_dir_{H}` | 4 | 4 | **RESEARCH; movement-v1 verdict FAIL**, ~9.1% coverage |
| movement `outcome_move_{H}` + `threshold_move_{H}` | 4 | 4 | **RESEARCH FAIL** |
| triple-barrier `outcome_tb_{H}` | scratch DB only | 4 | RESEARCH scratch (never in production DB) |
| empirical-analog outcome | similarity cols | 4 | RESEARCH; 500-neighbor cap + 21-day decay unjustified |
| spot-anchor v2 | — | — | **INVALID/dead** |

Key defects grounded first-hand: the committed `movement_target_thresholds_by_horizon_v1.json` is a **placeholder** (`selected_percentile: null`) inconsistent with the report's own selected p50 values; the DB materializes **only 4 horizons** (1c/5c/15c/60c) though the threshold JSON lists 7 (3c/8c/13c are O-10 diagnostic-only); movement labels cover **~9.1%** of governed rows; **no persisted movement/direction predictions** (movement-v1 FAIL).

The machine-readable inventory is `governance/research/stage1_target_label_foundation/target_registry_v1.json`.

## C–D. Candidate target families & horizon contracts

Fifteen candidate families are defined in the registry without selecting a winner, and NOT forced onto every horizon: execution-relevant (cost-adjusted move, prob-exceed-costs, immediate adverse excursion, abstention/OOD) lean 1c/5c; barrier/excursion (favorable-before-adverse, realized MFE/MAE, time-to-barrier) span 5c/15c; structure (continuation, failed breakout, value accept/reject) and regime (trend persistence, regime transition) are scoped to 15c/60c only. Each names its cost/barrier version and expected metrics.

## E. Causal timestamp & row identity

`research/stage1_target_foundation/causal_label_contract.py` reconstructs the production label from immutable `(ticker, bar_start_ts_utc, close)` identity and fails closed on lookahead, incomplete-bar use, timestamp aliasing (non-60s grid), duplicate anchors, cross-ticker attachment, and horizon confusion. Session is derived from the canonical `ts_utc → DST-ET` authority (`time_et.is_rth_ts_utc`), never a stored `et_hour`. Proven by `tests/test_stage1_causal_label_contract.py` (golden reconstruction cross-checked against an independent inline formula) and a 4-mutant matrix (lookahead/duplicate-anchor/aliasing/direction all DETECTED).

## F. Session & cohort contracts

`session_cohort_contract_v1.json` enumerates cohort dimensions (session, opening/closing window, intraday bucket, day-of-week, half-day/early-close, volatility regime, liquidity regime) and cross-cohort transfer policy (session pooling FORBIDDEN by default; half-day CONDITIONALLY_TESTABLE; open/close windows PERMITTED_AS_FEATURE/EXPERIMENT). It documents — and `rth_integrity_audit.py` mechanically detects — the **OPEN RTH cohort-integrity contradiction**: `db.py:4417-4420` (operator accuracy) and `audit_model_readiness.py:29-34` still filter RTH on the DST-skewed stored `et_hour/et_minute` (the deprecated `ml_data_common.rth_where_clause` pattern), and `math_volatility.session_bucket` feeds the skewed session label back as a feature. **Not fixed in Stage 1** — the fix changes production accuracy/audit surfaces and requires separate authorization.

## G. Cost & utility foundation

`cost_model_registry_v1.json` versions the research cost models (`COST_V1_UNDERLYING_SPY` post-label-only from the pilot prereg; `EXEC_EV_SCAFFOLD_V1` fail-closed eval-time). Every economic target MUST name a non-NONE cost-model id (validator-enforced). Gaps: no observed-cost ledger in the governed DB (all economic labels estimated/scenario), no per-ticker/time-of-day cost surface, options costs unmodeled.

## H. Barrier / MFE / MAE foundation

Realized MFE/MAE are implemented as causal research labels in `causal_label_contract.py` (path max/min over the horizon window from OHLC), **distinct from the runtime Monte-Carlo forecast** (`monte_carlo.efe/eae`, which is not a label). Triple-barrier exists only in research (`research/pilot_step3/labeling.py` next-bar-open entry + T-1 Wilder ATR; D2 scratch DB) — barrier versions are registered as CANDIDATE and `TRIPLE_BARRIER_ADOPTION = NOT_APPROVED_FOR_PRODUCTION`.

## I. Target registry

`target_registry_v1.json` + fail-closed validator (`target_registry.py`): 4 VALID_FOR_EXPERIMENT, 7 CANDIDATE, 1 INVALID, **0 PRODUCTION_APPROVED** (hard Stage 1 rule, test-locked).

## J. Golden label dataset & reconstruction proof

`research/stage1_target_foundation/golden/` holds an immutable synthetic bar set and independently-computed expected labels; every label reconstructs deterministically. **Limitation:** the local governed DB (`data/ed_console.db`) is schema-only (0 rows) — reconstruction from the **real 62k-row governed population is NOT_PROVEN locally**; the golden proof establishes the label machinery is causal and correct, not that the governed DB is clean.

## K. Stage 2 experiment contract (design only)

`stage2_experiment_contract_v1.json`: eligible = VALID_FOR_EXPERIMENT targets; mandatory purge + embargo + walk-forward (all **MISSING** in `arch_competition/` today, which does single-window OOS + half-split stability only); baselines incl. always-WAIT, persistence, and a shuffle control that must score at chance; costs applied to every economic comparison; **STOP if no candidate beats simple baselines after costs**. Not executed.

## L. Production containment (verified, already correct)

Existing governance already states the required containment, verified this mission: `INSTITUTIONAL_MASTER_CHECKLIST.md:82` (TRIPLE_BARRIER_ADOPTION NOT_APPROVED_FOR_PRODUCTION, MODEL_PROMOTION NOT_APPROVED, REAL_MONEY_READINESS NOT_PROVEN); `CARD_TRUST_CONTRACT.md` (cards research telemetry; foundation-model excluded); `calibration_phase5_adaptive_weighting_foundation.md:21` (static fusion weights only); `promotion_engine.py:106-107` (auto-promote forbidden, raises). No false containment claim required correction.

## M. Readiness determinations

- `STAGE1_TARGET_INVENTORY = PROVEN` — every existing target identified + registered.
- `STAGE1_CAUSAL_LABEL_CONTRACTS = PROVEN` — candidate labels have reconstructable causal contracts with mechanical guards + mutation proof.
- `STAGE1_SESSION_COHORT_CONTRACTS = PROVEN` — cohort dimensions explicit; session mixing mechanically detected; contradiction disclosed OPEN.
- `STAGE1_COST_MODEL_CONTRACT = PROVEN` — every economic target names a versioned cost model (validator-enforced).
- `STAGE1_GOLDEN_LABEL_RECONSTRUCTION = PROVEN (synthetic)` — golden rows reconstruct; **real-governed-DB reconstruction NOT_PROVEN (no governed DB present)**.
- `DATA_FOUNDATION_READY_FOR_STAGE2_BASELINES = NO` — blocked on: real governed-DB golden reconstruction, movement/economic label coverage (~9.1%), the OPEN RTH cohort-integrity fix, and the missing purge/embargo/walk-forward machinery.

## Mandatory statuses

CURRENT_PRODUCTION_ARCHITECTURE = NOT_APPROVED · CURRENT_CARDS = UNTRUSTED_RESEARCH_TELEMETRY · CURRENT_FUSION_VALID = CONTRADICTED · CURRENT_LABEL_SYSTEM = NOT_APPROVED · PREDICTIVE_VALIDITY = NOT_PROVEN · CALIBRATION_VALIDITY = NOT_PROVEN · LEAKAGE_ABSENCE = NOT_PROVEN · TRAIN_LIVE_PARITY = NOT_PROVEN · FULL_MODEL_STACK = NOT_CLOSED · REAL_MONEY_APPROVAL = NOT_APPROVED · IMPLEMENTATION_CHANGE_TO_PRODUCTION_MODELS = NOT_APPROVED.
