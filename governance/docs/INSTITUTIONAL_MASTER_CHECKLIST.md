> **Classification:** Operational Ledger | **Scope:** Institutional master checklist — MIT / Bloomberg / world-class trading-app bar; program backlog and status tracker (not mechanical enforcement).

# Institutional Master Checklist

**Purpose:** Preserve the expanded institutional checklist so card fidelity, signal validation, data truth, model governance, execution realism, and real-money readiness are tracked as **distinct lanes** — not collapsed into a single “green CI” verdict.

**Authority:** This document is a **program tracker**. Mechanical truth for agent behavior remains `governance/docs/AGENT_OPERATING_CONTRACT.md`, `AGENTS.md`, and `governance/artifacts/SEVERITY_1_CONTROL_VALIDATION_REGISTER.json`. Maturity is **not** upgraded by adding rows here alone.

**Last aligned SHA:** `caf15635d67939a012114cde47ac0f500b66e30d`  
**Regen / update:** Manual edit when lane status changes; cite commit SHA + remote CI run ids in closure rows.

**Alignment note:** Card-freshness / proof-drift reconciliation in this file is aligned through `caf15635`. Historical rows anchored at `77675a6` or `216702c` remain **preserved** unless this section explicitly re-records them with a newer SHA. **Do not** infer every historical lane was revalidated at `caf15635`.

**Related (inspect only — do not treat as duplicate truth):**
- `governance/REVIEWER_README.md` — reviewer reproduction entry point
- `governance/CURRENT_LIMITATIONS.md` — honest open gaps (generated)
- `governance/artifacts/CARD_CONSUMER_CONTRACT_V1.json` — card field dispositions
- `docs/CARD_TRUST_CONTRACT.md` — card trust product law
- `OPEN_ITEMS.md` — active execution queue (near-term lanes only; not a duplicate of this file)

**Column legend (ordered roadmap tables):** **OPEN_ITEMS now?** = `YES` when the lane should have a short active row in `OPEN_ITEMS.md`; `NO` = master-only backlog until promoted.

---

## Current status facts @ `caf15635` (card-freshness reconciliation aligned through this SHA)

**Composite non-closure (explicit — do not upgrade):**

| Fact | Status |
|------|--------|
| `CARD_FIDELITY_OVERALL_STATUS` | **NOT_CLOSED** / **NOT_PROVEN** |
| `STALE_WITHHELD_RTH_FRESHNESS_STATUS` | **FAIL** |
| `UNIVERSAL_RUNTIME_LIVE_PROOF_STATUS` | **NOT_PROVEN** |
| `REAL_MONEY_READINESS_STATUS` | **NOT_PROVEN** |
| `UNIVERSAL_CLOSURE_CLAIMED` | **NO** |

### Card-freshness / proof-drift program lanes (`STALE_CARDS_RTH_CARD_FIDELITY_AUDIT_V1`)

| Lane | Status | Evidence SHA / note |
|------|--------|-------------------|
| S1 — stale-card contract / design | **CLOSED_WITH_EVIDENCE** | `0745484` (`docs/CARD_TRUST_CONTRACT.md`, `CARD_CONSUMER_CONTRACT_V1.json`) |
| S2A — additive backend/API `card_freshness_v1` | **CLOSED_WITH_EVIDENCE** | `0a9a6c0` (remote CI green @ S2A CI fix) |
| S2B-1 — top-level operator actionability mirrors | **CLOSED_WITH_EVIDENCE** | `50f07aa2308512c0117a39646e902885acac78b5` (remote CI green) |
| S2B-2 | **NOT_APPROVED** | — |
| S2C — trade-gate consumer wiring | **NOT_APPROVED** | — |
| S3 — UI fail-closed design review | **REPORTED_COMPLETE_READ_ONLY** | design only |
| S3A — UI operator-mirror local diff | **NOT_APPROVED** | operator authorization required — drift repair **PUSHED_PROVEN** @ `caf15635` |
| S3 implementation | **NOT_APPROVED** | — |
| `DRIFT_RECOVERY_AND_PROOF_STANDARD_REPAIR_V1` | **PUSHED_PROVEN** @ `caf15635` · **REMOTE_CI_NOT_PROVEN** · **NOT_CLOSED** | Proof-label ladder; await remote CI @ `caf15635` before `CLOSED_WITH_EVIDENCE` |

**Git history (card-freshness cone, `77675a6`..`50f07aa`):** `0745484` contract · `f837c8c` analytics freshness metadata · `0a9a6c0` S2A governance/CI · `50f07aa` S2B-1 operator mirrors.

### Stale mechanism closed vs runtime freshness FAIL (do not conflate)

Closed stale/fallback **mechanism** lanes (`CARD_FIDELITY_STALE_FALLBACK_LANE`, `analyticsCardTrustGate`, card-trust withhold paint) prove the **withhold/trust-gate mechanism only**. They **do not** close runtime freshness. The **2026-06-29 RTH observation** remains **FAIL** / **SAMPLE_OBSERVED_NOT_UNIVERSAL**: analytics/card bundle stale while quote was current; cards are **not** safe as live parity when stale/quote-ahead warning is present.

### Preserved composite @ prior anchors (mechanism lanes — not runtime closure)

| Fact | Status |
|------|--------|
| Card stale/fallback **mechanism** lane | **CLOSED_WITH_EVIDENCE** (historical — `@77675a6` era) |
| Execution channel surface lane | **CLOSED_WITH_EVIDENCE** |
| `call_signal` reclassification lane | **CLOSED_WITH_EVIDENCE** |
| `call_headline` deprecation lane | **CLOSED_WITH_EVIDENCE** |
| Remaining operator orphans | `pred_headline`, `reversal_risk`, `reversal_label` |
| Orphan payload field handling overall | **NOT_PROVEN** |
| RTH all-supported-ticker audit | **BLOCKED** |
| D17 full closure | **NOT_CLOSED** |

### D2 dual-label research board @ `623e088f` (lint-green tip `c74da7a`; scratch-scoped — production untouched)

| Lane | Status | Evidence |
|------|--------|----------|
| NORMALIZER_COLUMN_CARRY (scratch-only) | **CLOSED_WITH_EVIDENCE** | `623e088f` — scratch `snapshots_1m_normalized` created from production DDL + 16 TB columns; unchanged production materializer carried 31,662 `outcome_tb_5c` rows (intersection-driven insert list) |
| SCRATCH_NORMALIZED_TB_COLUMNS | **PROVEN** | scratch manifest `normalized_rows=66887`, `normalized_rows_with_tb_5c=31662`, zero errors |
| PRODUCTION_NORMALIZER_UNCHANGED | **PROVEN** | source TB-free lock (`test_production_normalizer_is_intersection_driven_and_tb_free`) + production PRAGMA: zero TB columns on `snapshots` and `snapshots_1m_normalized` |
| MATRIX_RUNNER_ARTIFACT_ISOLATION | **PROVEN** | `tools/research/d2_run_dual_label_matrix.py` guards exercised live + locked: production DB refused, `models/*` outputs refused, out forced under `data/research/`, promotion disabled |
| PRODUCTION_MODEL_TREE_UNTOUCHED | **PROVEN** | outputs only under gitignored `data/research/d2_models/`; nothing staged/modified under `models/` |
| D2_XGB_DUAL_LABEL_MATRIX | **READY_FOR_OPERATOR_POWERSHELL** | command file `data/research/d2_models/d2_matrix_commands.ps1` (12 xgb cells); production-fidelity pilot: SPY 5c fixed balanced-acc 0.3357 vs TB 0.5215 through unchanged `train_ticker` |

**Preserved (do not upgrade):** `FULL_DUAL_LABEL_MATRIX` = **PARTIAL / XGB_READY / SEQUENCE_FAMILIES_BLOCKED_PENDING_LABEL_THREADING_APPROVAL** · `TRIPLE_BARRIER_ADOPTION` = **NOT_APPROVED_FOR_PRODUCTION** · `MODEL_PROMOTION` = **NOT_APPROVED** · `MODEL_REAL_MONEY_EDGE` = **NOT_PROVEN** · `REAL_MONEY_READINESS` = **NOT_PROVEN** · `MONDAY_RTH_PROOF` = **WAITING_FOR_MARKET**.

---

## Historical status facts @ `77675a6` (preserved — not revalidated @ `caf15635`)

```
card stale/fallback lane = CLOSED_WITH_EVIDENCE
execution channel surface lane = CLOSED_WITH_EVIDENCE
call_signal reclassification lane = CLOSED_WITH_EVIDENCE
call_headline deprecation lane = CLOSED_WITH_EVIDENCE
remaining operator orphans = pred_headline, reversal_risk, reversal_label
orphan payload field handling overall = NOT_PROVEN
RTH all-supported-ticker audit = BLOCKED
universal runtime live proof = NOT_PROVEN
card fidelity overall = NOT_PROVEN
real-money readiness = NOT_PROVEN
D17 full closure = NOT_CLOSED
```

| Fact | Status |
|------|--------|
| Card stale/fallback lane | **CLOSED_WITH_EVIDENCE** |
| Execution channel surface lane | **CLOSED_WITH_EVIDENCE** |
| `call_signal` reclassification lane | **CLOSED_WITH_EVIDENCE** |
| `call_headline` deprecation lane | **CLOSED_WITH_EVIDENCE** |
| Remaining operator orphans | `pred_headline`, `reversal_risk`, `reversal_label` |
| Orphan payload field handling overall | **NOT_PROVEN** |
| RTH all-supported-ticker audit | **BLOCKED** |
| Universal runtime live proof | **NOT_PROVEN** |
| Card fidelity overall | **NOT_PROVEN** |
| Real-money readiness | **NOT_PROVEN** |
| D17 full closure | **NOT_CLOSED** |

**D17 wording (do not conflate):** pinned register @ `77675a6` has `closure_admissible: false` and `unreviewed_count` = 52,237 — **not** D17 full closure. **HISTORICAL/SUPERSEDED:** prior scoped-register snapshot (174,459 rows / 0 UNREVIEWED / `closure_admissible: true` @ `25cb2e3` era) is not current pinned truth. Full closure requires wire-true disposition across the program plus bare GOVERNED_EXCEPTION closure — tracked separately under the Schwab epic in `OPEN_ITEMS.md`, not mixed into card-fidelity lanes.

### D17 Path-A wave train status board @ `77675a6`

**Wave train:** D17 strict non-money LINE_SCOPE NMD identity rekeys — **COMPLETE_WITH_EVIDENCE**. Does **not** close D17 or Schwab V4.

| Wave | SHA | Files | Rows | Status |
|------|-----|------:|-----:|--------|
| Pilot | `2e29f12` | 3 | 6 | **CLOSED_WITH_EVIDENCE** |
| Wave 2 | `bccc18e` | 3 | 26 | **CLOSED_WITH_EVIDENCE** |
| Wave 3 | `b03f042` | 2 | 43 | **CLOSED_WITH_EVIDENCE** |
| Wave 4 | `03a3eaa` | 1 | 51 | **CLOSED_WITH_EVIDENCE** |
| Wave 5 | `9cb0f65` | 2 | 18 (9 unique targets) | **CLOSED_WITH_EVIDENCE** |
| Wave 6 | `77675a6` | 4 | 11 (8 unique targets) | **CLOSED_WITH_EVIDENCE** |

| Path-A totals | Value |
|---------------|------:|
| Tracked slice files | 15 |
| `register_id` row changes | 155 |
| Pinned register changed | **no** |
| Register repin | **NOT_APPROVED** |
| Production semantic-key merge | **NOT_APPROVED** |
| D17 full closure | **NOT_CLOSED** |
| Schwab V4 Register Closure | **NOT_CLOSED** |

---

## Ordered execution roadmap (dependency / risk order)

Execute in phase order unless operator explicitly preempts. Non-RTH live parity is **inadmissible** as fix-approval evidence for card fidelity (Phase 2 rule).

### PHASE 0 — Governance / proof discipline

| Lane | Status | Phase | Priority | Dependencies | Why it matters | OPEN_ITEMS now? |
|------|--------|-------|----------|--------------|----------------|-----------------|
| Agent preload + operating contract | **ENFORCED** | 0 | P0 | — | Every edit starts from binding law | NO (mechanical) |
| Fix loop + Tier 0 / Tier A sign-off | **ENFORCED** | 0 | P0 | — | Prevents “green CI” without proof | YES (`INST-PROGRAM-TIER-A-HABIT`) |
| Maturity truth (`SEVERITY_1_CONTROL_VALIDATION_REGISTER.json`) | **BINDING** | 0 | P0 | — | No inflation from docs alone | NO |
| MIT / world-class gate | **BINDING** | 0 | P0 | — | Correctness bar before ship | NO |
| Remote CI (Objective Audit, Pytest, Hardening, Schwab CSV First) | **PROVEN** @ `216702c` (baseline); **REMOTE_CI_NOT_PROVEN** @ `caf15635` (drift repair — await CI) | 0 | P0 | Push to main | Baseline repo health | NO |
| GitHub branch protection API proof | **NOT_PROVEN** | 0 | P1 | Authenticated `gh` | External enforcement gap | NO |
| Live Schwab traffic proof | **NOT_PROVEN** | 0 | P2 | Operator host + auth | Cannot claim live wire proof from simulation | NO |
| Mechanical rules / no prose-only promotions | **ENFORCED** | 0 | P1 | — | Rules must have checkers | YES (`INST-PROGRAM-MECH-RULES`) |

### PHASE 1 — Current card-fidelity closure

| Lane | Status | Phase | Priority | Dependencies | Why it matters | OPEN_ITEMS now? |
|------|--------|-------|----------|--------------|----------------|-----------------|
| `CARD_FIDELITY_STALE_FALLBACK_LANE` | **CLOSED_WITH_EVIDENCE** (mechanism only) | 1 | — | — | Stale/partial withhold on cards — **not** runtime RTH parity | NO (closed) |
| `EXECUTION_CHANNEL_SURFACE_LANE` (`call_state` chip) | **CLOSED_WITH_EVIDENCE** | 1 | — | — | Execution readiness visible | NO (closed) |
| `CALL_SIGNAL_RECLASSIFICATION_LANE` | **CLOSED_WITH_EVIDENCE** | 1 | — | — | MH promotion chip contract | NO (closed) |
| `CALL_HEADLINE_DEPRECATION_LANE` | **CLOSED_WITH_EVIDENCE** | 1 | — | — | Dead headline path retired | NO (closed) |
| S2A `card_freshness_v1` nested metadata | **CLOSED_WITH_EVIDENCE** @ `0a9a6c0` | 1 | — | S1 contract | Tier C descriptive freshness block | NO (closed) |
| S2B-1 operator actionability mirrors | **CLOSED_WITH_EVIDENCE** @ `50f07aa` | 1 | — | S2A | Top-level `operator_*` mirrors on Tier C | NO (closed) |
| Card trust gate (`analyticsCardTrustGate`) | **CLOSED_WITH_EVIDENCE** (mechanism only) | 1 | — | — | STALE/PENDING/DEGRADED withhold — UI still client-side until S3 | NO (closed) |
| S3 UI fail-closed (operator mirrors) | **NOT_APPROVED** | 1 | **P0** | S2B-1 + drift repair | UI must read `operator_card_actionable` | YES (pointer below) |
| Proof-label drift repair | **PUSHED_PROVEN** @ `caf15635` / **NOT_CLOSED** | 0 | P0 | — | Agent packet ladder; remote CI pending | YES |
| Orphan payload field handling (overall) | **NOT_PROVEN** | 1 | **P0** | Per-field disposition | Backend fields without honest UI contract | YES |
| `pred_headline` disposition | **OPERATOR_DECISION_REQUIRED** | 1 | **P0** | Operator choice | Explanation rail vs `backend_only` | YES |
| `reversal_risk` / `reversal_label` disposition | **OPERATOR_DECISION_REQUIRED** | 1 | **P0** | Operator choice | Risk rail vs `backend_only` | YES |
| `EXPLAINABILITY_AND_OPERATOR_DECISION_SURFACE_V1` (orphan subset) | **NOT_STARTED** | 1 | **P0** | Orphan decisions | Operator decision surface completeness | YES |
| Horizon / ALL / PLAN harness parity | **NOT_PROVEN** | 1 | P1 | Phase 2 RTH | Harness green ≠ live DOM proof | YES (`STACK-WIRE-*`, `LIVE-UI-*`) |
| Card fidelity overall | **NOT_PROVEN** | 1 | **P0** | Phases 1–2 | Composite card-truth gate | YES (pointer) |
| `STACK-WIRE-7` … `STACK-WIRE-15` (wiring sign-off) | **OPEN** | 1 | P1 | Phase 1 orphans | Producer→UI map completion | YES (existing rows) |

**Harness / contract:** `tools/run_universal_card_fidelity_runtime.py` · `governance/artifacts/CARD_CONSUMER_CONTRACT_V1.json`

**Rule:** Do **not** combine orphan field fixes with RTH universal parity in one implementation lane.

### PHASE 2 — RTH live card truth

| Lane | Status | Phase | Priority | Dependencies | Why it matters | OPEN_ITEMS now? |
|------|--------|-------|----------|--------------|----------------|-----------------|
| `RTH_ALL_SUPPORTED_TICKER_AUDIT` | **BLOCKED** | 2 | **P0** | `session_gate.loggable_now:true` | All enrolled tickers under RTH harness | YES |
| `UNIVERSAL_RUNTIME_LIVE_PROOF` | **NOT_PROVEN** | 2 | **P0** | RTH unblocked | Live DOM + transport proof for all tickers | YES |
| Trust-aware harness (stale withhold vs mismatch) | **NOT_PROVEN** | 2 | P1 | Harness semantics | Distinguish trusted withhold from true mismatch | YES |
| Guest vs anchor switch validation | **NOT_PROVEN** | 2 | P1 | RTH | Ticker switch coherence | NO (promote when RTH opens) |
| `LIVE-UI-3` same-moment acceptance | **OPEN** | 2 | P1 | RTH + transport | `decision_generation_id` coherence | YES (existing row) |
| `FIND-LIVEUI-7` L1 SSE diag on ops UI | **OPEN** | 2 | P2 | — | Observability for L1 identity violations | YES (existing row) |

**Rule:** Non-RTH live parity is **inadmissible** as fix-approval evidence for card fidelity.

### PHASE 3 — Data quality and timestamp truth

| Lane | Status | Phase | Priority | Dependencies | Why it matters | OPEN_ITEMS now? |
|------|--------|-------|----------|--------------|----------------|-----------------|
| `MARKET_DATA_QUALITY_AND_CORPORATE_ACTIONS_V1` | **NOT_STARTED** | 3 | P1 | Schwab wire baseline | Splits, dividends, stale quotes, mapping | NO (master backlog) |
| Tier A/B/C transport merge honesty | **PARTIAL** | 3 | P1 | Phase 2 transport | Quote vs analytical timestamp truth | YES (`LIVE-UI-1/2` closed; residual in STACK-WIRE) |
| `trade_impacting_gate` quarantine | **ENFORCED** | 3 | P0 | — | Bad data fail-closed on money path | NO |
| Schwab leaf wire (D17 program) | **NOT_CLOSED** | 3 | P1 | Separate epic | Market-field disposition — not card paint | YES (`INST-PROGRAM-SCHWAB-CONES`) |
| DATA-PIPELINE-INTEGRITY / absorption NULL class | **PARTIAL** | 3 | P1 | — | Training boundary data truth | YES (existing chain rows) |

### PHASE 4 — Feature lineage / lookahead-bias / train-live parity

| Lane | Status | Phase | Priority | Dependencies | Why it matters | OPEN_ITEMS now? |
|------|--------|-------|----------|--------------|----------------|-----------------|
| `FEATURE_LINEAGE_AND_LOOKAHEAD_BIAS_AUDIT_V1` | **NOT_STARTED** | 4 | P1 | Phase 3 data truth | Train-serve identity, causal ordering | NO (master backlog; pointer in cross-link) |
| Lane A operator field lineage labeling | **CLOSED_WITH_EVIDENCE** @ `eceb500` | 4 | — | — | Additive `field_lineage` metadata; remote CI green | NO (closed) |
| `VOLATILITY_INDEX_CONFLUENCE_AND_CALL_PUT_SIGNAL_CORRECTNESS_AUDIT_V1` | **OPEN** | 4 | **P1** | Phase 3 data truth; RTH timing | SPY↔VIX · QQQ↔VXN · IWM↔RVX + call/put symmetry | YES |
| Train-serve parity (I-05) | **ENFORCED** | 4 | P0 | — | Encoder cone mechanical lock | NO |
| ZERO-BIAS ablation placement | **ENFORCED** (mechanical) | 4 | P1 | Runnable grid | No pre-decided feature routing | YES (`INST-PROGRAM-ABLATION-RUNNABLE`) |
| Ablation ingest purity | **ENFORCED** | 4 | P1 | — | Wire-only scoring path | NO |
| ML-PIPELINE-CORRECTNESS / leakage closeouts | **OPEN** | 4 | P1 | — | Cascade stacking, B3 leakage | YES (existing rows) |
| `STACK-WIRE-6` ms_dict replay reconstruction | **CLOSED_WITH_EVIDENCE** @ `9d4c8a4` | 4 | — | — | Live vs replay ms_dict parity (subset) | YES (reconciliation row) |

### PHASE 5 — Decision ledger and replay

| Lane | Status | Phase | Priority | Dependencies | Why it matters | OPEN_ITEMS now? |
|------|--------|-------|----------|--------------|----------------|-----------------|
| `DECISION_LEDGER_AND_REPLAY_V1` | **NOT_STARTED** | 5 | P1 | Phase 1–2 card truth | Immutable decision id + blind reconstruction | NO (master backlog; pointer in cross-link) |
| Decision reconstruction tests | **PARTIAL** | 5 | P2 | — | `tests/decision_reconstruction/` exists | NO |
| `/api/build` tip = disk tip | **ENFORCED** | 5 | P1 | — | Runtime tip honesty | NO |
| Calibration / ops visibility | **PARTIAL** | 5 | P2 | — | Persistence consumer map | NO |

### PHASE 6 — Signal outcome validation

| Lane | Status | Phase | Priority | Dependencies | Why it matters | OPEN_ITEMS now? |
|------|--------|-------|----------|--------------|----------------|-----------------|
| `SIGNAL_OUTCOME_VALIDATION_V1` | **NOT_STARTED** | 6 | P1 | Phase 5 ledger + labels | Did signal match realized outcome? | NO (master backlog; pointer in cross-link) |
| `CARD_PREDICTION_HINDSIGHT_VALIDATION_V1` | **NOT_STARTED** | 6 | P1 | Phase 6 signal outcome | Horizon card vs realized move | NO (master only) |
| Card signal fidelity reports | **INVENTORY** | 6 | P2 | — | `tools/check_card_signal_fidelity.py` | NO |
| Live diag parity | **PARTIAL** | 6 | P2 | — | `live_diag_compare.py` — not universal RTH | NO |

### PHASE 7 — Backtest-to-live and simulation truth

| Lane | Status | Phase | Priority | Dependencies | Why it matters | OPEN_ITEMS now? |
|------|--------|-------|----------|--------------|----------------|-----------------|
| `BACKTEST_TO_LIVE_PARITY_V1` | **NOT_STARTED** | 7 | P1 | Phase 4–5 | Same code path, features, clocks | NO (master backlog; pointer in cross-link) |
| Replay hold bars / causal clock | **PARTIAL** | 7 | P2 | — | `time_et.py`, replay modules | NO |
| Arch competition eval integrity | **ENFORCED** | 7 | P1 | — | Governed eval row alignment | NO |
| Monte Carlo / fusion offline vs live | **PARTIAL** | 7 | P2 | — | Documented env splits | NO |
| A2 replay/live runtime parity (OBS-A2OE1) | **OPEN** | 7 | P2 | Phase 5 | Runtime gating beyond ms_dict reconstruction | NO |

### PHASE 8 — Risk, sizing, stops, execution assumptions

| Lane | Status | Phase | Priority | Dependencies | Why it matters | OPEN_ITEMS now? |
|------|--------|-------|----------|--------------|----------------|-----------------|
| `RISK_ENGINE_AND_POSITION_SIZING_AUDIT_V1` | **NOT_STARTED** | 8 | P1 | Phase 7 simulation truth | Limits supersede model output | NO (master backlog; pointer in cross-link) |
| `EXECUTION_ASSUMPTIONS_AND_SLIPPAGE_MODEL_V1` | **NOT_STARTED** | 8 | P1 | Phase 8 risk | Fill assumptions, spread, partial fills | NO (master backlog; pointer in cross-link) |
| `call_state` execution readiness | **CLOSED_WITH_EVIDENCE** | 8 | — | — | WAIT/WATCH/ACTIVE chip | NO (closed) |
| `final_tradeable` / PLAN entry state | **PARTIAL** | 8 | P2 | Phase 2 RTH | UI + harness; RTH proof pending | YES (`LIVE-UI-*`) |
| Real-money readiness (overall) | **NOT_PROVEN** | 8 | **P0** | Phases 1–10 | Composite — not a single green check | NO (master composite) |

### PHASE 9 — Model promotion, demotion, drift, calibration

| Lane | Status | Phase | Priority | Dependencies | Why it matters | OPEN_ITEMS now? |
|------|--------|-------|----------|--------------|----------------|-----------------|
| `MODEL_PROMOTION_AND_DEMOTION_GOVERNANCE_V1` | **PARTIAL** | 9 | P1 | Phase 4 ablation | Single promotion authority | NO (master backlog; pointer in cross-link) |
| `MODEL_DRIFT_AND_REGIME_DECAY_MONITORING_V1` | **NOT_STARTED** | 9 | P2 | Phase 9 promotion | Live vs train drift | NO (master only) |
| Active model verification | **ENFORCED** | 9 | P1 | — | `verify_active_models.py` | NO |
| Training anchor roster (SPY/QQQ/IWM) | **ENFORCED** | 9 | P1 | — | Scheduler default | NO |
| Full seven-layer stack | **ENFORCED** | 9 | P0 | — | No partial stack in production claims | YES (`INST-PROGRAM-STACK-HONESTY`) |
| Fusion-only horizon cards | **ENFORCED** | 9 | P1 | — | No silent empirical fill | YES (stack honesty rows) |

### PHASE 10 — Failure modes, security, observability, kill switches

| Lane | Status | Phase | Priority | Dependencies | Why it matters | OPEN_ITEMS now? |
|------|--------|-------|----------|--------------|----------------|-----------------|
| `FAILURE_MODE_AND_KILL_SWITCH_AUDIT_V1` | **NOT_STARTED** | 10 | P2 | Phase 8 money-path | Kill switches, degraded modes | NO (master backlog; pointer in cross-link) |
| `SECURITY_AND_SECRET_HANDLING_AUDIT_V1` | **PARTIAL** | 10 | P2 | — | I-09 locks; full audit backlog | NO (master only) |
| `OBSERVABILITY_AND_PRODUCTION_MONITORING_V1` | **NOT_STARTED** | 10 | P2 | Phase 2 harness | Metrics, alerts, runbooks | NO (master backlog; pointer in cross-link) |
| `PERFORMANCE_AND_LATENCY_BUDGET_V1` | **NOT_STARTED** | 10 | P3 | — | Tier A/B/C latency, SSE, DB | NO (master only) |
| Stack integrity / signals engine failed chips | **LIVE** | 10 | P1 | — | Decision rail degradation surfaces | YES (`LIVE-UI-B`) |

### PHASE 11 — Dead-code / retirement / docs truth

| Lane | Status | Phase | Priority | Dependencies | Why it matters | OPEN_ITEMS now? |
|------|--------|-------|----------|--------------|----------------|-----------------|
| `DEAD_CODE_AND_RETIREMENT_GOVERNANCE_V1` | **PARTIAL** | 11 | P2 | Fix-as-we-touch | `REPO_HYGIENE_*` artifacts | NO (master backlog; pointer in cross-link) |
| `briefWhyWait` / `setupForecastSentence` | **DEAD** | 11 | P3 | — | Documented; optional retirement | NO |
| Persistence consumer map | **ENFORCED** | 11 | P1 | — | No orphan writers without consumers | NO |
| Check stack right-sizing | **INVENTORY** | 11 | P3 | — | `CHECK_STACK_INVENTORY.json` | NO |
| Docs dual-truth hygiene (this file ↔ OPEN_ITEMS) | **PARTIAL** | 11 | P1 | — | Master = roadmap; OPEN_ITEMS = queue | YES (this docs lane) |

### PHASE 12 — Bloomberg-terminal UI/product refinement

| Lane | Status | Phase | Priority | Dependencies | Why it matters | OPEN_ITEMS now? |
|------|--------|-------|----------|--------------|----------------|-----------------|
| `USER_TRUST_AND_VISUAL_SEMANTICS_AUDIT_V1` | **NOT_STARTED** | 12 | P1 | Phase 1–2 | Legibility, WAIT vs chrome, chip semantics | NO (master backlog; pointer in cross-link) |
| Fusion-only horizon cards (product) | **ENFORCED** | 12 | P1 | — | No silent empirical fill on cards | YES (stack honesty) |
| Card trust withhold labels | **CLOSED_WITH_EVIDENCE** | 12 | — | — | STALE/PENDING/DEGRADED | NO (closed) |
| Operator-surface legibility (Issue 18) | **PARTIAL** | 12 | P1 | Phase 2 RTH visual | Contract tests; RTH visual proof pending | YES (`LIVE-UI-D/E`, `UI-HARDENING-FULL-AUDIT`) |
| `LIVE-UI-4` UI honesty pass | **OPEN** | 12 | P1 | Phase 2 | L1 overlay + Tier C merge audit | YES (existing row) |

### PHASE 13 — Research backlog / future enhancements

Explicit lane IDs — **not** closed by card contract work @ `216702c`:

| Lane ID | Status | Phase | Priority | Dependencies | Why it matters | OPEN_ITEMS now? |
|---------|--------|-------|----------|--------------|----------------|-----------------|
| `SIGNAL_OUTCOME_VALIDATION_V1` | **NOT_STARTED** | 13 | High | Phase 5–6 | Outcome-linked signal proof | NO |
| `CARD_PREDICTION_HINDSIGHT_VALIDATION_V1` | **NOT_STARTED** | 13 | High | Phase 6 | Card vs realized move hindsight | NO |
| `DECISION_LEDGER_AND_REPLAY_V1` | **NOT_STARTED** | 13 | High | Phase 5 | Immutable audit trail | NO |
| `MARKET_DATA_QUALITY_AND_CORPORATE_ACTIONS_V1` | **NOT_STARTED** | 13 | High | Phase 3 | Corp actions + quote quality | NO |
| `FEATURE_LINEAGE_AND_LOOKAHEAD_BIAS_AUDIT_V1` | **NOT_STARTED** | 13 | High | Phase 4 | Leakage + train-serve audit | NO |
| `VOLATILITY_INDEX_CONFLUENCE_AND_CALL_PUT_SIGNAL_CORRECTNESS_AUDIT_V1` | **OPEN** | 13 | **High** | Phase 3–4; `MARKET_OPEN_CT=08:30` | SPY↔VIX · QQQ↔VXN · IWM↔RVX; call/put audit; wait if unsafe before session | YES |
| `BACKTEST_TO_LIVE_PARITY_V1` | **NOT_STARTED** | 13 | High | Phase 7 | Simulation ≡ live path | NO |
| `EXECUTION_ASSUMPTIONS_AND_SLIPPAGE_MODEL_V1` | **NOT_STARTED** | 13 | High | Phase 8 | Tradability realism | NO |
| `RISK_ENGINE_AND_POSITION_SIZING_AUDIT_V1` | **NOT_STARTED** | 13 | High | Phase 8 | Limits supersede model | NO |
| `MODEL_PROMOTION_AND_DEMOTION_GOVERNANCE_V1` | **PARTIAL** | 13 | Medium | Phase 9 | Governed promote/demote | NO |
| `MODEL_DRIFT_AND_REGIME_DECAY_MONITORING_V1` | **NOT_STARTED** | 13 | Medium | Phase 9 | Drift monitoring | NO |
| `EXPLAINABILITY_AND_OPERATOR_DECISION_SURFACE_V1` | **NOT_STARTED** | 13 | Medium | Phase 1 orphans | Full operator UX program | YES (Phase 1 subset active) |
| `FAILURE_MODE_AND_KILL_SWITCH_AUDIT_V1` | **NOT_STARTED** | 13 | Medium | Phase 10 | Ops readiness | NO |
| `SECURITY_AND_SECRET_HANDLING_AUDIT_V1` | **PARTIAL** | 13 | Medium | Phase 10 | Secrets + trust boundaries | NO |
| `OBSERVABILITY_AND_PRODUCTION_MONITORING_V1` | **NOT_STARTED** | 13 | Medium | Phase 10 | Production ops | NO |
| `PERFORMANCE_AND_LATENCY_BUDGET_V1` | **NOT_STARTED** | 13 | Medium | Phase 10 | Latency SLOs | NO |
| `DEAD_CODE_AND_RETIREMENT_GOVERNANCE_V1` | **PARTIAL** | 13 | Low | Phase 11 | Hygiene inventory | NO |
| `USER_TRUST_AND_VISUAL_SEMANTICS_AUDIT_V1` | **NOT_STARTED** | 13 | Medium | Phase 12 | UI legibility program | NO |
| LFE / triple-barrier / feature epic | **PARKED** | 13 | Medium | Phase 4 ablation | Research expansion | YES (existing epic rows) |

---

## Governing distinctions (do not conflate)

| Distinction | Question it answers | **Not** equivalent to |
|-------------|---------------------|------------------------|
| **Card fidelity** | Do live cards honestly paint trusted payload on Horizon/ALL/PLAN/execution? | Green pytest alone |
| **Signal validation** | Did the signal match realized outcomes over time? | Card paint correctness |
| **Risk validation** | Do limits, sizing, and gates supersede model output? | Fusion confidence |
| **Execution validation** | Are fills, slippage, and tradability assumptions honest? | `call_state` chip alone |
| **Data validation** | Is market data timely, complete, and corp-action clean? | Schwab wire presence |
| **Model validation** | Are promote/demote, drift, and stack integrity governed? | Training completed once |
| **Operational validation** | Kill switches, monitoring, security, latency budgets? | Local CI pass |
| **Real-money readiness** | Composite of above + RTH live proof + operator trust | Any single lane closure |

---

## Quick reference — open card-fidelity orphans

| Field | Contract status | Next lane (operator choice) |
|-------|-----------------|------------------------------|
| `pred_headline` | `OPERATOR_DECISION_REQUIRED` | Explanation rail vs `backend_only` |
| `reversal_risk` | `OPERATOR_DECISION_REQUIRED` | Risk rail vs `backend_only` |
| `reversal_label` | `OPERATOR_DECISION_REQUIRED` | Paired with `reversal_risk` |

---

## Reference — standing operating contract (Phase 0 detail)

| Item | Requirement | Status |
|------|-------------|--------|
| Agent preload | Read `governance/docs/AGENT_OPERATING_CONTRACT.md` before edits | **ENFORCED** |
| Fix loop | Exact test → group → governance → artifacts → report | **ENFORCED** |
| Sign-off ladder | Tier 0 upfront → Tier A objective audit | **ENFORCED** |
| No patch-generator posture | Own loop until proof or `[REAL-GATE: …]` | **BINDING** |

---

## Reviewer commands (sanity — not lane closure)

```bash
python tools/check_agent_preload_contract.py
python tools/enforce_all_rules.py --objective-audit
python -m pytest tests/test_universal_card_fidelity_runtime.py -q
```

RTH universal proof (when unblocked):

```bash
python tools/run_universal_card_fidelity_runtime.py --no-write-report --require-browser-dom --require-live-transport --tickers <all from logger/status> --stable-reads 3 --max-wait-sec 180
```

---

*End of institutional master checklist.*
