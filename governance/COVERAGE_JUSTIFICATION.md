# Coverage Justification — Severity-1 Controls

> **Classification:** Operational Ledger | **Scope:** Validated maturity and coverage % per Severity-1 control.

**Date:** 2026-06-15 | **Source:** Institutional Audit Phase 1 validation register

No control may claim maturity above what evidence justifies. Matrix `ENFORCED` labels are **overstated** where noted.

| Control | Matrix claim | Validated | Coverage % | Why not higher |
|---------|--------------|-----------|------------|----------------|
| I-01 | PARTIALLY_ENFORCED | L3 | 35 | all silent-default patterns repo-wide |
| I-02 | PARTIALLY_ENFORCED | L3 | 55 | manual promotion without executor |
| I-05 | PARTIALLY_ENFORCED | L2 | 40 | live artifact swap without re-train |
| I-07 | PARTIALLY_ENFORCED | L3 | 45 | orphan API endpoints |
| I-15 | PARTIALLY_ENFORCED | L2 | 30 | continuous runtime tuple health monitor |
| I-17 | PARTIALLY_ENFORCED | L2 | 25 | full-stack deterministic replay proof |
| I-19 | PARTIALLY_ENFORCED | L2 | 20 | NTP health gate |
| I-20 | PARTIALLY_ENFORCED | L1 | 15 | lockfile hash in release manifest |
| I-21 | NOT_IMPLEMENTED | L1 | 12 | immutable lineage graph |
| I-22 | NOT_IMPLEMENTED | L1 | 8 | config manifest pinned to release |
| I-24 | NOT_IMPLEMENTED | L0 | 0 | required independent approver on promotion/risk/schema/ov... |
| I-25 | NOT_IMPLEMENTED | L0 | 0 | versioned release manifest |
| I-26 | NOT_IMPLEMENTED | L0 | 0 | RTO/RPO on release artifact |
| I-28 | PARTIALLY_ENFORCED | L2 | 18 | wrong data / outlier quarantine |
| I-29 | NOT_IMPLEMENTED | L1 | 5 | signed risk policy objects |
| I-30 | NOT_IMPLEMENTED | L1 | 10 | append-only override event linked to Decision ID |
| I-31 | NOT_IMPLEMENTED | L0 | 0 | immutable Decision ID |
| PL-ABLATION-GRID | ENFORCED | L3 | 45 | runtime enforcement |
| PL-FULL-STACK | ENFORCED | L3 | 35 | runtime enforcement |
| PL-FUSION-CARDS | ENFORCED | L3 | 28 | runtime enforcement |
| PL-NO-DEFERRAL | ENFORCED | L3 | 50 | runtime enforcement |
| PL-PROMOTION | ENFORCED | L3 | 55 | runtime enforcement |
| PL-REGISTRY | ENFORCED | L3 | 35 | runtime enforcement |
| PL-SCHWAB-CSV | ENFORCED | L3 | 40 | runtime enforcement |
| PL-SIGNOFF | ENFORCED | L3 | 40 | runtime enforcement |
| PL-STORAGE-CONSUMER | ENFORCED | L3 | 55 | runtime enforcement |
| PL-TRAINING-ROSTER | ENFORCED | L3 | 60 | runtime enforcement |
| PL-UPFRONT-GATE | ENFORCED | L3 | 55 | runtime enforcement |
| PL-ZERO-BIAS | ENFORCED | L3 | 50 | runtime enforcement |

## Checker honesty (critical finding)

Many checkers are **presence/marker scans**, not behavioral proofs:

- `check_fusion_only_card_contract` — verifies strings exist in source files (`(retired)`:2638`)
- `test_fusion_only_card_contract_passes_on_current_repo` — asserts checker returns `[]` on current repo only
- **No test proves `--no-verify` is detected or blocked**

## Adversarial testing gap

Controls with dedicated adversarial tests: **5** / 29

Missing suites (Priority 0):
- I-28: inject SPY 0.01 / 50000 / negative / duplicate ticks → expect quarantine + audit
- I-31: delete feature/promotion records → expect loud reconstruction failure
- I-24: single-actor promotion change → expect hard failure
- Governance: commit governance weaken with `--no-verify` → expect block (currently none)

## Severity classification (audit Phase 5)

**Severity-1 (trade/audit foundational):** I-31, I-28, I-29, I-30, I-24, I-25, I-02, PL-PROMOTION, I-01/PL-FUSION-CARDS

**Severity-2:** I-05, I-07, I-11, I-15, I-17, code quality, documentation

**Severity-3:** Developer experience, DX tooling

Matrix currently marks 31 rows severity-1 — several (I-20 dependency pins) are **Severity-2** in practice.
