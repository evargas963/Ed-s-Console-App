# Framework: ED Institutional Decision Engine v2.0

**Document ID:** `governance/Framework-ED-Decision-Engine-v2.0-DRAFT.md`  
**Version:** 2.0-DRAFT  
**Status:** DRAFT / PROPOSAL - Target Architecture Pending Governance Binding  
**Supersedes:** Nothing until separately approved, prereg-bound, and content-hash validated.

This draft does not supersede `governance/Framework-ED-Decision-Engine-v1.1.md`. The v1.1 framework and its bound prereg remain authoritative for the current pilot unless and until a v2.0 framework is approved, bound to a new preregistration artifact, and validated by runtime integrity checks.

---

## Purpose

Define the governance structure for the maximum-edge ED Institutional Trading Decision Engine: a multi-source, multi-horizon, execution-aware, portfolio-aware decision system governed by V3 institutional controls.

This document is a table-of-contents draft only. It establishes the review surface for v2.0; it does not lock semantics, thresholds, labels, or implementation obligations.

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
1.4 Required separation between signal, execution, and portfolio logic  
1.5 No double-counting of costs, liquidity, or risk adjustments  
1.6 Advisory vs gating vs trade-impacting components  
1.7 Decision trace requirements across all domains

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

### 3. Approximate Guarantees

Controlled term:

**Approximate guarantee:** A procedure whose stated mathematical guarantee depends on data assumptions that financial data may violate. Examples include DSR, conformal prediction, bootstrap confidence intervals, and CV-based estimates.

Reports citing an approximate guarantee must:
- name the assumption;
- name the likely mode of violation;
- cite the assumption-relaxed variant used, if any;
- qualify the correction or interval as approximate, not exact;
- report empirical diagnostics showing whether the approximation held in the evaluated window.

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
7.4 Production label selection per strategy role  
7.5 Diagnostic label use  
7.6 Label horizon, stop, target, and timeout contracts  
7.7 Same-bar and force-flat policy  
7.8 Sample uniqueness weighting  
7.9 Label leakage controls  
7.10 Label comparison and change governance

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

### 14. Cross-Sectional Ranking And Portfolio Allocation

14.1 Candidate set construction  
14.2 Expected utility objective  
14.3 Correlation and concentration constraints  
14.4 Liquidity and capacity constraints  
14.5 Opportunity cost of capital  
14.6 Rank trace and allocation trace  
14.7 Dominated-candidate policy  
14.8 Portfolio-level validation metrics

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

### 17. Final Decision Policy

17.1 EV calculation  
17.2 Execution-adjusted EV  
17.3 Lower-bound and upper-bound EV  
17.4 TRADE / WAIT / AVOID rules  
17.5 Required gates before TRADE  
17.6 AVOID triggers  
17.7 WAIT semantics  
17.8 Preferred order type output  
17.9 Trader-facing reason codes  
17.10 Machine-readable output schema

### 18. Output Schema And Decision Trace

18.1 Required probability fields  
18.2 Required uncertainty fields  
18.3 Required EV fields  
18.4 Required execution fields  
18.5 Required ranking/allocation fields  
18.6 Required policy object IDs  
18.7 Required artifact hashes  
18.8 Required decomposition trace  
18.9 Schema versioning and semantic change rules  
18.10 Invalid-output fail-closed behavior

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

