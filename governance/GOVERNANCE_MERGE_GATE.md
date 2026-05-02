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
| **G3 — Cross-artifact** | **PASS** if, at the run log’s recorded **HEAD**, phase plan references to route/claim IDs are consistent with `TRADE_IMPACTING_ROUTE_INVENTORY.md` and `PRODUCTION_CLAIMS_REGISTER.md`; run log states **artifacts reviewed** and **how** consistency was verified; R-08 / R-09 observed (no contradictions among authoritative sources vs register). |
| **G4 — Scope** | **PASS** if, at the run log’s recorded **HEAD**, the committed governance set matches an **explicit path list** in the run log; excluded files per register **O-14** / **O-15** (or successors) are documented there; no untracked governance orphans; working tree review supports that the commit set contains no unaccounted governance artifacts. |
| **G5 — Working tree** | All modified **non-governance** tracked files are **accounted for** (separate commit, stash, revert, or documented intent). Governance commit is **not** conflated with unexplained code churn. |
| **G6 — Provenance** | Each binding decision row in the register has **owner + date + source + operator sign-off** (or this run’s sign-off block references them). |
| **G7 — Closure semantics** | No hidden bypass paths; “CLOSED” criteria in the plan are satisfiable as written. |

---

## Merge Gate Execution Protocol

- Each governance commit requires a new merge gate run.
- Run logs are append-only; prior runs must not be modified.
- Each run must record:
  - commit hash (HEAD)
  - run date/time
  - operator sign-off
- All gates (G1–G7) must be re-evaluated against current HEAD.
- PASS applies only to the recorded commit.

---

## Run log (operator fills)

| Field | Value |
|--------|--------|
| Run date | 2026-05-01 |
| Commit / PR | f423c6d |
| G1 | ☑ PASS — register **O-01–O-15** approved; phase plan §6–§14 aligned |
| G2 | ☑ PASS — G3-R1 no waiver (§8 / §15) |
| G3 | ☑ PASS — Cross-artifact consistency verified against HEAD f423c6d. Method: Python extraction of `PHASE_PLAN_INFRASTRUCTURE.md` §5 (from heading `## 5. Route and claim binding summary` through `## 6. INF-3`): Route IDs `R-001`–`R-035` (including ranges `R-018–R-026`, `R-029–R-030` expanded to discrete IDs) each found as substrings in `TRADE_IMPACTING_ROUTE_INVENTORY.md`; explicit Claim IDs from §5.2–§5.3 (including `C-SRV-03`, `C-UI-03`, table rows, and ranges expanded to `C-UI-12`–`C-UI-15`, `C-UI-17`–`C-UI-18`, `C-UI-20`–`C-UI-21`) each found in `PRODUCTION_CLAIMS_REGISTER.md`. Artifacts reviewed: `PHASE_PLAN_INFRASTRUCTURE.md`, `OPERATOR_DECISION_REGISTER.md`, `TRADE_IMPACTING_ROUTE_INVENTORY.md`, `PRODUCTION_CLAIMS_REGISTER.md`. Result: no mismatches identified between IDs cited in phase plan §5 and source artifacts; R-08/R-09 alignment confirmed. |
| G4 | ☑ PASS — Scope control verified at HEAD f423c6d. Committed file list: `OPERATOR_DECISION_REGISTER.md`, `GOVERNANCE_MERGE_GATE.md`, `PHASE_PLAN_INFRASTRUCTURE.md`, `TRADE_IMPACTING_ROUTE_INVENTORY.md`, `PRODUCTION_CLAIMS_REGISTER.md`, `GOVERNANCE_EVENT_MODEL.md`, `EXISTING_ARTIFACT_TRANSITION_POLICY.md` (verified via `git show f423c6d --name-only`). Exclusions: `PHASE_PLAN_TARGET_STATE.md` (O-14, deferred), `INFRASTRUCTURE_GOVERNANCE_LOCK_PACKAGE.md` (O-15, deferred); both subsequently committed in 5ad7cb2 (verified via `git show 5ad7cb2 --name-only`). Working tree state at run time: 22 paths flagged M by git status --short (later determined to be CRLF/racy-git noise per G5; no substantive code diffs); no unaccounted governance artifacts in this commit set. |
| G5 | ☑ PASS — operator directed full pass (working tree disposition accepted for this gate) |
| G6 | ☑ PASS — owner + date + source + sign-off on register |
| G7 | ☑ PASS — closure criteria as written |
| **Overall** | ☑ **PASS** — operator directive **2026-05-01** |

**Operator approval** is defined as:

- evaluation of the merge gate against the current HEAD commit,
- confirmation that `OPERATOR_DECISION_REGISTER.md` is aligned and authoritative,
- Git commit by repository owner representing approval of the evaluated state.

**Operator signature:** **Date:** 2026-05-01  

---

*End of merge gate.*
