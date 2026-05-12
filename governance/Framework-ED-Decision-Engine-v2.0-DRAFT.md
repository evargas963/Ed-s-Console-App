# Framework: ED Institutional Decision Engine v2.0

**Document ID:** `governance/Framework-ED-Decision-Engine-v2.0-DRAFT.md`  
**Version:** 2.0-DRAFT  
**Status:** DRAFT / PROPOSAL - Target Architecture Pending Governance Binding  
**Supersedes:** Nothing until separately approved, prereg-bound, and content-hash validated.

This draft does not supersede `governance/Framework-ED-Decision-Engine-v1.1.md`. The v1.1 framework and its bound prereg remain authoritative for the current pilot unless and until a v2.0 framework is approved, bound to a new preregistration artifact, and validated by runtime integrity checks.

---

## Purpose

Define the governance structure for the maximum-edge ED Institutional Trading Decision Engine: a multi-strategy, multi-expression, execution-aware, portfolio-aware decision system governed by V3 institutional controls.

This document is the canonical working target draft for v2.0. It locks the target direction for design work, but it does not create production authority, lock thresholds, bind preregistration, or authorize implementation until separately approved.

---

## Core Status Label

Until approved and prereg-bound, the architecture is:

**Target Architecture Pending Governance Binding**

Permitted use:
- research discussion;
- architecture review;
- draft governance design;
- non-authoritative planning.

Forbidden use:
- citing v1.1 as authority for v2.0 components;
- promotion claims;
- production claims;
- trade-impacting deployment claims.

---

## Working Target Architecture

v2.0 is a **meta-framework**, not one monolithic strategy stretched across every timeframe. Short-horizon trading, 0DTE options, swing trading, LEAPS, and on-demand portfolio analysis are separate strategy modules or expression profiles under one shared governance framework.

Shared framework responsibilities:
- define edge domains;
- define strategy-module contracts;
- define expression-profile contracts;
- define portfolio coordination across modules;
- define lifecycle policy requirements;
- define validation and approximate-guarantee discipline;
- define preregistration and artifact governance.

The key distinction:

| Concept | Meaning |
|---|---|
| Strategy Module | Why and when the system wants exposure. |
| Expression Profile | How that exposure is expressed in the market. |
| Portfolio Layer | Whether the exposure is allowed alongside the current book. |
| Lifecycle Policy | How the position is managed after entry. |

### Shared Edge Domains

Every strategy module is audited across four edge domains:

1. **Signal Edge** — whether the opportunity is predictive.
2. **Implementation Edge** — whether the opportunity can be traded at acceptable cost and quality.
3. **Portfolio Edge** — whether the opportunity is the best use of risk budget across the whole account.
4. **Lifecycle Edge** — whether the system manages the open position better than a static baseline.

### Strategy Modules And Expression Profiles

| Module | Strategy family | Primary expression profile | Additional / future expression profiles |
|---|---|---|---|
| **Module A** | Short-horizon event-driven trading | **A1: Equity / ETF** | **A2: Options / 0DTE** |
| **Module B** | Swing trading | **B1: Equity / ETF** | B2: Defined-risk options |
| **Module C** | Long-horizon equity / LEAPS | C1: Equity | C2: LEAPS |
| **Module D** | On-demand portfolio analysis | Recommendation with rationale | No autonomous trade expression by default |

Pilot sequence:
- **Pilot 1:** Module A, A1 equity/ETF, SPY, horizons 1m / 5m / 15m / 60m.
- **Pilot 1B:** Module A, A2 options/0DTE, initially SPY / QQQ unless separately amended.
- **Later pilots:** Module B swing, Module C long-horizon / LEAPS, Module D on-demand portfolio analysis.

0DTE remains in scope as **Expression Profile A2**. It shares Module A's short-horizon signal logic where appropriate, but it has separate option-chain, **`volatility`**, Greeks, execution, lifecycle, and validation contracts.

### Cross-Module Portfolio Coordination

The Portfolio Edge layer coordinates across modules, not only within each module. It must aggregate net exposure by ticker, factor, sector, theme, expression type, and module.

Default conflict protocol:
1. Hard risk gates always win.
2. Longer-horizon thesis modules may veto contradictory shorter-horizon trades.
3. Pre-registered hedge contracts may allow apparent conflicts.
4. Thesis-break events escalate to the longer-horizon module for re-evaluation.
5. Unclassified conflicts block the lower-priority trade.

Hedges are governed contracts, not runtime discretion. A hedge contract must include:
- `hedge_contract_id`;
- `protected_module`;
- `hedging_module`;
- ticker / exposure scope;
- allowed side;
- max hedge size;
- max duration;
- trigger conditions;
- attribution target;
- expiry / review cadence.

Conflict outcomes must be machine-readable:
- `approved_hedge`;
- `thesis_break_escalation`;
- `blocked_lower_priority_trade`;
- `no_conflict`.

### Module D Explainability

Module D is a meta-consumer of all modules, not a wrapper around Module C. It consumes Module A, B, and C context plus portfolio, tax/account, risk, and user-horizon inputs.

Module D outputs must include:
- recommendation;
- rationale;
- contributing modules and weights;
- confidence and disagreement;
- factor exposures;
- tax/account constraints where available;
- portfolio constraints;
- user-horizon alignment;
- what would change the answer.

All decision modes, including Module D, must expose counterfactual sensitivity where practical: what input, regime, price, portfolio, tax, horizon, or execution condition would change the recommendation or decision.

### Fundamental Data Contract

Fundamental data belongs in the v2.0 data-plane contract even if implementation is deferred for Pilot 1. Required future contract surfaces include earnings, financial statements, analyst revisions, valuation metrics, growth/quality metrics, institutional ownership, short interest, borrow cost, and sector/theme classifications.

### Decision Latency Contract

Every event type or module decision mode must declare:
- `decision_latency_budget`;
- `decision_ttl`;
- stale-decision behavior;
- which optional layers are synchronous, asynchronous, or advisory.

Optional models that cannot fit inside the latency budget cannot be trade-impacting for that event type.

---

## Proposed Table Of Contents

### 0. Scope, Authority, And Binding

0.1 Draft status and non-authority statement  
0.2 Relationship to V3 institutional standard  
0.3 Relationship to v1.1 pilot framework  
0.4 Required v2.0 preregistration artifact  
0.5 `content_hash`, framework ID, and framework version binding  
0.6 Locked items vs moving parts  
0.7 Amendment and version-bump rules  
0.8 Migration path from v1.1 pilot scope

### 1. System Boundary And Edge Domains

1.1 Signal edge domain  
1.2 Implementation / execution edge domain  
1.3 Portfolio allocation edge domain  
1.4 Lifecycle edge domain  
1.5 Required separation between signal, execution, portfolio, and lifecycle logic  
1.6 No double-counting of costs, liquidity, risk, or lifecycle adjustments  
1.7 Advisory vs gating vs trade-impacting components  
1.8 Decision trace requirements across all domains

### 1.5 Strategy Modules And Expression Profiles

1.5.1 Strategy module contract  
1.5.2 Expression profile contract  
1.5.3 Module A: short-horizon event-driven trading  
1.5.4 Expression Profile A1: equity / ETF  
1.5.5 Expression Profile A2: options / 0DTE  
1.5.6 Module B: swing trading  
1.5.7 Module C: long-horizon equity / LEAPS  
1.5.8 Module D: on-demand portfolio analysis  
1.5.9 Pilot 1 and Pilot 1B scope  
1.5.10 Future module registration process

### 2. Controlled Vocabulary

2.1 Event  
2.2 Candidate trade  
2.3 Ticker / instrument identifier  
2.4 Horizon  
2.5 Regime  
2.6 Signal model  
2.7 Execution model  
2.8 Portfolio allocator  
2.9 Policy object  
2.10 Approximate guarantee  
2.11 Calibration health  
2.12 Coverage health  
2.13 Drift gate  
2.14 Trade-impacting output  
2.15 Strategy module  
2.16 Expression profile  
2.17 Lifecycle policy  
2.18 Hedge contract  
2.19 Thesis-break escalation  
2.20 Decision-plane mode  
2.21 Source indicator  
2.22 Field source classification

### 3. Approximate Guarantees

Controlled term:

**Source indicator:** machine-readable status attached to every leaf decision field stating how the field was produced relative to the v2 contract.

Allowed source indicators:
- `v2_compliant` — field is produced by the v2 contract specified for the relevant module/expression profile.
- `v1_approximation` — field is approximated from existing v1 data or logic and is not full v2 compliance.
- `not_implemented` — field is structurally present but not yet produced.
- `policy_object_pending` — field depends on a governed policy object that has not yet been approved or bound.

Controlled term:

**Field source classification:** machine-readable data-origin class attached to, or auditably associated with, market-data fields and derived analytics.

Allowed field source classifications:
- `schwab_native_normalized` — Schwab provides the primitive field and the app consumes it through the canonical normalization boundary.
- `schwab_native_raw_fallback` — Schwab provides the primitive field, but the app is reading it from preserved raw payload because normalization has not yet promoted it or a transition path is being audited.
- `derived_because_schwab_does_not_provide` — Schwab does not provide the requested analytic; the value is legitimately produced by governed app math from declared inputs.
- `derived_fallback_because_schwab_unavailable` — Schwab normally provides or may provide the primitive, but it was unavailable in the selected payload, so the app used a fallback derivation.
- `presentation_only` — field is a display label, color, string, arrow, or UI formatting value and is not a data-plane or decision primitive.

Source indicator and field source classification are orthogonal axes. Source indicator states whether a v2 leaf satisfies the v2 contract; field source classification states where the data came from. A field may be `v2_compliant` and `schwab_native_normalized` (for example, normalized Schwab theta), `v2_compliant` and `derived_because_schwab_does_not_provide` (for example, governed GEX), or `v1_approximation` and `derived_fallback_because_schwab_unavailable` (for example, Black-Scholes theta when Schwab theta is missing).

**Approximate guarantee:** A procedure whose stated mathematical guarantee depends on data assumptions that financial data may violate. Examples include DSR, conformal prediction, bootstrap confidence intervals, and CV-based estimates.

Reports citing an approximate guarantee must:
- name the assumption;
- name the likely mode of violation;
- cite the assumption-relaxed variant used, if any;
- qualify the correction or interval as approximate, not exact;
- report empirical diagnostics showing whether the approximation held in the evaluated window.

`v1_approximation` is a companion source-indicator state for v1 metrics reused under v2 output contracts. Such fields must be treated as approximations of the intended v2 metric, not as v2-compliant values.

### 4. Data Ingestion And Canonical Store

4.1 Source inventory  
4.2 Per-source staging tables  
4.3 Canonical store contracts  
4.4 As-of timestamp and availability timestamp requirements  
4.5 Survivorship-safe symbol/ticker mapping  
4.6 Revision and backfill policy  
4.7 Multi-source data quality gates  
4.8 Broker/API credential and secrets boundaries  
4.9 Data-source failure modes and response policy  
4.10 Fundamental data contract surfaces  
4.11 Option-chain and per-contract **`volatility`** surface data contracts  
4.12 Tax-lot and account data contracts where available

Current Schwab market-data source inventory:

- `docs/SCHWAB_FIELD_REFERENCE.md` - live Schwab field inventory reference, captured 2026-05-05 after re-authentication.
- `docs/FIELD_SOURCE_AUDIT.md` - source classification for Schwab-native, normalized, raw-only, derived, and presentation fields.
- `docs/SCHWAB_FIELD_NORMALIZATION_AUDIT.md` - option-chain normalization gap list and bound fix sequence.
- `schwab_field_inventory/` - generated inventory artifacts, including the raw path catalog and canonical field dictionary.

These artifacts are data-plane contracts for v2 design work. A Schwab field addition, removal, or semantic change must be treated as a data-governance event, not a silent runtime assumption change. Refresh cadence and artifact hash binding remain policy-object pending until v2.0 preregistration is approved.

### 5. Event Generation

5.1 Multi-source event detector registry  
5.2 CUSUM events  
5.3 Volatility events  
5.4 News/sentiment events  
5.5 Options flow events  
5.6 Dealer positioning events  
5.7 Dark-pool events  
5.8 ETF flow events  
5.9 Cross-asset divergence events  
5.10 Liquidity shock events  
5.11 Event identity, deduplication, and causality  
5.12 Event proposal vs trade decision distinction

### 5.5 Event Reconciliation

5.5.1 Event clustering by ticker, time window, and catalyst  
5.5.2 Evidence aggregation  
5.5.3 Contradiction flags  
5.5.4 Candidate suppression / split / aggregate policy  
5.5.5 One candidate per reconciled cluster unless pre-registered otherwise

### 6. Regime Context

6.1 Regime definition contract  
6.2 Volatility regime  
6.3 Trend regime  
6.4 Liquidity regime  
6.5 Sector dispersion regime  
6.6 Macro/event regime  
6.7 Session/time-of-day regime  
6.8 Learned regime artifacts, including HMM only if earned  
6.9 Regime confidence and fallback behavior  
6.10 Regime use in monitoring, calibration, thresholds, and gating

### 7. Labeling

7.1 Candidate trade path definition  
7.2 Triple-barrier labels  
7.3 Trend-scanning labels  
7.4 Production label selection per strategy module  
7.5 Diagnostic label use  
7.6 Label horizon, stop, target, and timeout contracts  
7.7 Same-bar and force-flat policy  
7.8 Sample uniqueness weighting  
7.9 Label leakage controls  
7.10 Label comparison and change governance  
7.11 Module-specific label families  
7.12 Expression-specific payoff labels

### 8. Feature Contracts

8.1 Signal feature contracts  
8.2 Execution feature contracts  
8.3 Portfolio feature contracts  
8.4 Feature availability timestamp enforcement  
8.5 Feature neutralization policy by strategy role  
8.6 Market/sector/volatility/liquidity exposure treatment  
8.7 Train/serve feature parity  
8.8 Feature drift and stale-feature gates  
8.9 Feature contract versioning

### 9. Horizon Signal Models

9.1 Horizon set and economic meaning  
9.2 Mandatory XGBoost/CatBoost baseline per horizon  
9.3 Optional model inclusion gate  
9.4 Sequential/deep architecture candidates  
9.5 OOF-only downstream consumption  
9.6 Purged CV and embargo requirements  
9.7 Walk-forward evaluation requirements  
9.8 After-cost and capacity-aware utility criteria  
9.9 Model artifact manifests and child attachments

### 10. Horizon Fusion And Regime-Conditioned Weighting

10.1 Fusion role and input contract  
10.2 OOF input requirement  
10.3 Shrinkage toward global weights  
10.4 Minimum regime sample requirements  
10.5 Degradation to global weights  
10.6 Horizon calibration quality inputs  
10.7 Fusion artifact governance  
10.8 Divergence monitoring and breach response

### 11. Meta-Labeling

11.1 Single meta-model default  
11.2 Use of both label families as features  
11.3 Meta target definition  
11.4 OOF stacking discipline  
11.5 Trade geometry inputs  
11.6 Cross-horizon agreement inputs  
11.7 Dual-meta architecture only if earned  
11.8 Meta artifact manifest, lineage, and replay

### 12. Calibration And Uncertainty

12.1 Calibration method registry  
12.2 Calibration windows and refit cadence  
12.3 Per-regime ECE, Brier, and reliability reporting  
12.4 Conformal or quantile interval methods  
12.5 Coverage health by regime  
12.6 Interval widening or confidence degradation  
12.7 Hard-fail coverage gates  
12.8 Approximate-guarantee reporting for uncertainty claims

### 13. Execution And Microstructure

13.1 Execution model as first-class governed artifact  
13.2 Spread and slippage target definitions  
13.3 Fill probability target definition  
13.4 Market impact model ID  
13.5 Order type policy  
13.6 Queue and adverse-selection features  
13.7 Quote staleness and decision TTL  
13.8 Execution drift monitoring  
13.9 Realized vs predicted execution shortfall  
13.10 Execution-model failure modes  
13.11 Capacity / participation-rate model  
13.12 Borrow and shortability gates  
13.13 Options spread/fill quality model  
13.14 0DTE expiration, Greeks, and **`volatility`** execution constraints

### 14. Cross-Module Portfolio Coordination

14.1 Candidate set construction  
14.2 Cross-sectional expected utility objective  
14.3 Cross-module position aggregation  
14.4 Cross-module capital budgets  
14.5 Correlation and concentration constraints  
14.6 Liquidity and capacity constraints  
14.7 Opportunity cost of capital  
14.8 Rank trace and allocation trace  
14.9 Dominated-candidate policy  
14.10 Hierarchical conflict protocol  
14.11 Pre-registered hedge contracts  
14.12 Thesis-break escalation  
14.13 Portfolio-level validation metrics

### 15. Policy Objects Under V3 I-13

The following are governed policy objects when trade-impacting:
- trade threshold;
- avoid threshold;
- Kelly fraction;
- max position size;
- drawdown reduction rule;
- sector, theme, ticker, and regime exposure caps;
- execution quality gates;
- calibration health gates;
- coverage health gates;
- drift block thresholds;
- degradation mode responses;
- halt and release criteria.

Each policy object requires:
- versioned identity;
- owner/approver;
- signed or otherwise approved change record;
- effective window;
- rollback pointer;
- audit event on change;
- replay impact assessment where applicable.

### 16. Position Sizing

16.1 Fractional Kelly default  
16.2 Conservative probability input, usually `p_low`  
16.3 Drawdown-constrained reduction  
16.4 Correlation-adjusted scaling  
16.5 Liquidity and capacity caps  
16.6 Hard max size caps  
16.7 RL sizing as research candidate only  
16.8 Sizing policy-object governance  
16.9 Pre-trade stress / scenario checks  
16.10 Gap, volatility, liquidity, and correlation shock scenarios  
16.11 Stress-driven size reduction or rejection rules

### 16.5 Lifecycle Policy

16.5.1 Lifecycle action sets by strategy module  
16.5.2 Static baseline policy  
16.5.3 Dynamic lifecycle policy candidate  
16.5.4 Hold / tighten / scale-out / exit / extend / convert actions  
16.5.5 BUY / HOLD / ADD / TRIM / EXIT actions for long-horizon modules  
16.5.6 Lifecycle validation by same-entry policy substitution  
16.5.7 Lifecycle-adjusted calibration  
16.5.8 Lifecycle thrashing and timeout-extension controls  
16.5.9 Lifecycle policy objects

### 17. Final Decision Policy

17.1 EV calculation  
17.2 Execution-adjusted EV  
17.3 Lower-bound and upper-bound EV  
17.4 TRADE / WAIT / AVOID rules  
17.5 Required gates before TRADE  
17.6 AVOID triggers  
17.7 WAIT semantics  
17.8 Tax overlay for taxable accounts and tax-aware modules  
17.9 Preferred order type output  
17.10 Trader-facing reason codes  
17.11 Machine-readable output schema  
17.12 Blackout and participation gates  
17.13 Decision latency budget per event type  
17.14 Decision TTL and stale-decision behavior

### 18. Output Schema And Decision Trace

18.1 Required probability fields  
18.2 Required uncertainty fields  
18.3 Required EV fields  
18.4 Required execution fields  
18.5 Required ranking/allocation fields  
18.6 Required Module D recommendation fields  
18.7 Required policy object IDs  
18.8 Required artifact hashes  
18.9 Required decomposition trace  
18.10 Counterfactual sensitivity / "what would change the answer" fields  
18.11 Source indicator on every leaf decision field  
18.12 Schema versioning and semantic change rules  
18.13 Invalid-output fail-closed behavior

### 19. Validation Protocol

19.1 Pre-registered evaluation plan  
19.2 Purged CV  
19.3 Embargo policy  
19.4 Walk-forward windows  
19.5 Refit cadence  
19.6 OOF-only stacking  
19.7 Sample uniqueness weighting  
19.8 DSR  
19.9 PBO  
19.10 CSCV  
19.11 Reality-check / multiple-hypothesis correction  
19.12 After-cost expected utility  
19.13 Capacity-aware evaluation  
19.14 Calibration validation  
19.15 Coverage validation  
19.16 Execution validation  
19.17 Portfolio-level validation  
19.18 Approximate-guarantee disclosures  
19.19 Per-module validation contracts  
19.20 Module A validation: short-horizon event-driven  
19.21 Module A2 validation: options / 0DTE  
19.22 Module B validation: swing  
19.23 Module C validation: long-horizon / LEAPS  
19.24 Module D validation: recommendation quality and explanation audit

### 20. Monitoring, Drift, And Failure Modes

20.1 Calibration drift  
20.2 Coverage drift  
20.3 Feature drift  
20.4 Label drift  
20.5 Execution drift  
20.6 Regime coverage degradation  
20.7 Model divergence  
20.8 Data-source outage  
20.9 Broker/API outage  
20.10 Degraded mode signaling  
20.11 Hard-fail gates  
20.12 Governance event emission

### 20.5 Post-Trade Attribution And Learning Loop

20.5.1 Structured close-out record  
20.5.2 Signal contribution attribution  
20.5.3 Execution shortfall attribution  
20.5.4 Portfolio allocation and sizing attribution  
20.5.5 Lifecycle action attribution  
20.5.6 Tax impact attribution where applicable  
20.5.7 Reason-code outcome analysis  
20.5.8 Feedback into calibration, execution, lifecycle, and refit cycles

### 21. Promotion And Lifecycle Governance

21.1 Artifact registry roles  
21.2 Lifecycle tier requirements  
21.3 Operational tier requirements  
21.4 Artifact hash immutability  
21.5 Child attachment allowlists  
21.6 Policy object promotion  
21.7 Human approval boundaries  
21.8 Single-operator limitations  
21.9 G2.v2 artifact-contract implications  
21.10 Migration from paused G2

### 22. Preregistration Package

22.1 Required prereg file path  
22.2 Required framework binding fields  
22.3 Required content hash  
22.4 Required source inventory  
22.5 Required label definitions  
22.6 Required validation windows  
22.7 Required model inclusion gates  
22.8 Required policy object IDs  
22.9 Required approximate-guarantee disclosures  
22.10 Amendment procedure

### 23. Governance Cleanup Dependencies

23.1 V3 authority-chain cleanup status  
23.2 G2 pause status  
23.3 INF-5 secrets/access-control workstream candidate  
23.4 I-13 policy-object gap closure  
23.5 I-09 secrets exclusion gap closure  
23.6 V1/V2 archive hygiene candidate  
23.7 Open conformance-audit dependencies

### 24. Approval Checklist

24.1 v2.0 full text approved  
24.2 New preregistration approved  
24.3 `content_hash` computed and bound  
24.4 Runtime loader updated for v2.0 binding  
24.5 Policy object registry defined  
24.6 Output schema defined  
24.7 Validation protocol locked  
24.8 G2.v2 decision recorded  
24.9 v1.1 relationship explicitly preserved or superseded  
24.10 Operator sign-off recorded

---

## Drafting Notes

This draft intentionally stops at table-of-contents depth. The next reconciliation pass should decide section ownership, which sections become locked semantics, and which details remain prereg moving parts.

