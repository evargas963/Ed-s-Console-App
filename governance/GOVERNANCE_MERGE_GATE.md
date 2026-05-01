# Governance merge gate

**Status:** **ACTIVE** — operator approved register 2026-05-01; use this gate before governance commits.  
**Version:** 2026-05-01  
**Audience:** Operator, Copilot, reviewers  

---

## Purpose

A **governance commit** (or promotion of INF docs to commit-eligible) is allowed **only** if every gate below is **PASS**. Any **FAIL** → remain draft; fix **only** failing items, re-run.

**Global rules (normative):**

- **R-08:** Any value not recorded in `governance/OPERATOR_DECISION_REGISTER.md` is **non-authoritative** for committed artifacts.  
- **R-09:** Any value proposed by any system is **invalid** until **explicitly approved and recorded** in that register.

---

## Exemption (non-circular)

This merge gate document is **not** evaluated by gates G1–G7 as if it were a phase-plan execution spec. Changes to **this file** are ordinary **version-controlled documentation** commits and require **operator approval** of the gate text itself. G1–G7 still apply to **`PHASE_PLAN_INFRASTRUCTURE.md`** and related normative bundles listed in G4.

---

## Gates (binary)

| Gate | PASS if |
|------|---------|
| **G1 — Authority** | Every numeric or policy value in `PHASE_PLAN_INFRASTRUCTURE.md` §6–§14 exists in `OPERATOR_DECISION_REGISTER.md` with no **UNKNOWN** for any field the plan asserts. Plan does not claim “exact” ahead of register. |
| **G2 — Internal consistency** | No contradictions (e.g. G3-R1: **external gate, no waiver** for INF-1 closure; §8 and §15 aligned). |
| **G3 — Cross-artifact** | Route / claim tables in the phase plan match `TRADE_IMPACTING_ROUTE_INVENTORY.md` and `PRODUCTION_CLAIMS_REGISTER.md` for referenced IDs (spot-check or scripted diff as operator prefers). |
| **G4 — Scope** | Commit set is an **explicit file list**; no untracked governance orphans; extra files disposition recorded (see register **O-14**, **O-15** or successor IDs). |
| **G5 — Working tree** | All modified **non-governance** tracked files are **accounted for** (separate commit, stash, revert, or documented intent). Governance commit is **not** conflated with unexplained code churn. |
| **G6 — Provenance** | Each binding decision row in the register has **owner + date + source + operator sign-off** (or this run’s sign-off block references them). |
| **G7 — Closure semantics** | No hidden bypass paths; “CLOSED” criteria in the plan are satisfiable as written. |

---

## Run log (operator fills)

| Field | Value |
|--------|--------|
| Run date | 2026-05-01 |
| Commit / PR | f423c6d |
| G1 | ☑ PASS — register **O-01–O-15** approved; phase plan §6–§14 aligned |
| G2 | ☑ PASS — G3-R1 no waiver (§8 / §15) |
| G3 | ☑ PASS — operator directed full pass; cross-artifact spot-check accepted |
| G4 | ☑ PASS — operator directed full pass; commit-set list at commit time |
| G5 | ☑ PASS — operator directed full pass (working tree disposition accepted for this gate) |
| G6 | ☑ PASS — owner + date + source + sign-off on register |
| G7 | ☑ PASS — closure criteria as written |
| **Overall** | ☑ **PASS** — operator directive **2026-05-01** |

**Operator signature:** *(electronic approval — same as register)* **Date:** 2026-05-01  

---

*End of merge gate.*
