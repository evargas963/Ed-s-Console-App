# Framework v2.0 Target Lock Record

**Status:** TARGET LOCKED FOR DESIGN WORK  
**Date:** 2026-05-05  
**Target draft:** `governance/Framework-ED-Decision-Engine-v2.0-DRAFT.md`  
**Current production/pilot authority:** `governance/Framework-ED-Decision-Engine-v1.1.md` remains authoritative until a v2.0 framework is approved, prereg-bound, and content-hash validated.

---

## Lock Decision

The v2.0 target architecture is locked as a **meta-framework** for design work.

This lock does not authorize production deployment, promotion claims, or trade-impacting behavior. It records the architecture direction all future v2.0 planning should align with unless explicitly amended.

---

## Locked Target Concepts

### Four Edge Domains

All strategy modules are audited across:

1. **Signal Edge** — why/when the opportunity exists.
2. **Implementation Edge** — whether the opportunity can be expressed and executed.
3. **Portfolio Edge** — whether the opportunity is allowed and useful alongside the whole book.
4. **Lifecycle Edge** — how the position is managed after entry.

### Strategy Modules

v2.0 is not one horizon stack. It is a framework for separate strategy modules:

| Module | Strategy family | Status |
|---|---|---|
| **Module A** | Short-horizon event-driven trading | Pilot 1 target |
| **Module B** | Swing trading | Future module |
| **Module C** | Long-horizon equity / LEAPS | Future module |
| **Module D** | On-demand portfolio analysis | Future module |

### Expression Profiles

Strategy modules answer why/when to seek exposure. Expression profiles answer how that exposure is expressed.

| Profile | Meaning | Status |
|---|---|---|
| **A1** | Equity / ETF expression for Module A | Pilot 1 target |
| **A2** | Options / 0DTE expression for Module A | Pilot 1B target |
| **B1** | Equity / ETF expression for swing trading | Future |
| **B2** | Defined-risk options for swing trading | Future |
| **C1** | Equity expression for long-horizon thesis | Future |
| **C2** | LEAPS expression for long-horizon thesis | Future |

0DTE remains explicitly in scope as **Module A, Expression Profile A2**. It is not treated as a generic longer horizon and not forced into the equity/ETF expression contract.

---

## Pilot Sequence

### Pilot 1

- **Module:** A — short-horizon event-driven trading
- **Expression profile:** A1 — equity / ETF
- **Initial ticker:** SPY
- **Horizons:** 1m / 5m / 15m / 60m
- **Output shape:** TRADE / WAIT / AVOID

### Pilot 1B

- **Module:** A — short-horizon event-driven trading
- **Expression profile:** A2 — options / 0DTE
- **Initial tickers:** SPY / QQQ unless separately amended
- **Output shape:** TRADE / WAIT / AVOID with option structure, strike/expiry, max loss, Greeks, execution quality, and lifecycle plan

### Later Pilots

- Module B swing trading
- Module C long-horizon equity / LEAPS
- Module D on-demand portfolio analysis

---

## Cross-Module Coordination

The Portfolio Edge layer coordinates across modules. It must prevent separate modules from issuing conflicting trade-impacting decisions without a governed resolution path.

Default conflict outcomes:

- `approved_hedge`
- `thesis_break_escalation`
- `blocked_lower_priority_trade`
- `no_conflict`

Longer-horizon thesis modules may veto contradictory shorter-horizon trades unless a pre-registered hedge contract permits the conflict.

Hedges require a governed contract with:

- `hedge_contract_id`
- `protected_module`
- `hedging_module`
- ticker / exposure scope
- allowed side
- max hedge size
- max duration
- trigger conditions
- attribution target
- expiry / review cadence

---

## Module D Requirement

Module D is a meta-consumer of all modules, not a wrapper around Module C.

Required outputs:

- recommendation;
- rationale;
- contributing modules and weights;
- confidence and disagreement;
- factor exposures;
- tax/account constraints where available;
- portfolio constraints;
- user-horizon alignment;
- what would change the answer.

---

## Validation Direction

Each strategy module requires its own validation contract.

- Module A uses short-horizon event-driven validation: purged CV, embargo, OOF stacking, walk-forward, execution-adjusted EV, DSR/PBO/CSCV where applicable.
- Module A2 adds options/0DTE validation: option-chain as-of discipline, IV/Greeks, spread/fill simulation, expiration handling, assignment/exercise semantics, and lifecycle validation.
- Module B uses swing validation: daily-bar walk-forward, event-study logic, lower trade-count correction, factor attribution, and after-tax reporting where applicable.
- Module C uses long-horizon validation: cross-sectional pooling, Bayesian shrinkage, multi-year holdouts, survivorship-safe universe construction, factor attribution, and fundamental-data as-of discipline.
- Module D uses recommendation-quality and explanation-audit validation.

Lifecycle policies must prove incremental edge versus static baselines and must be recalibrated when they change the realized outcome distribution.

---

## Boundaries

This target lock does not:

- supersede v1.1;
- bind a v2.0 preregistration;
- authorize implementation;
- authorize production deployment;
- change existing pilot runtime behavior.

This target lock does:

- define the v2.0 architecture direction;
- preserve the 0DTE model as an explicit A2 expression profile;
- define the module/expression/profile vocabulary for future v2.0 work;
- provide a durable reference for future design and planning.

