> **Classification:** Policy Specification | **Scope:** Governance documentation `INFRASTRUCTURE_GOVERNANCE_LOCK_PACKAGE.md`.

# Infrastructure Governance — Lock Package (Reviewer Index)

**Status:** DEFERRED per `governance/OPERATOR_DECISION_REGISTER.md` O-15. This file is a reviewer index only and is not normative versus `INSTITUTIONAL_STANDARD_V3.md` or `PHASE_PLAN_INFRASTRUCTURE.md`.

**Purpose:** Single entry point for final review before declaring Workstream 2 plans **locked** for implementation.  
**Does not replace:** normative text in `INSTITUTIONAL_STANDARD_V3.md` or executable detail in `PHASE_PLAN_INFRASTRUCTURE.md`.

---

## 1. Core doctrine (non-negotiable)

1. Design for **institutional capability**.  
2. Execute against **evidenced gaps**.  
3. **Closure** = enforceable + auditable + non-bypassable + proof + production-claim binding.

---

## 2. Two-artifact model (must stay separate)

| Artifact | Path | Role |
|----------|------|------|
| Target state | `governance/PHASE_PLAN_TARGET_STATE.md` | P0–P7 capability model; strategic gap map |
| Execution plan | `governance/PHASE_PLAN_INFRASTRUCTURE.md` | INF-3 → INF-2 → INF-1 → INF-4 order; enforcement; events; proof; closure |

---

## 3. Governing rule (one line)

**No infrastructure gap may invalidate a production claim.** If an invariant is not enforced → remove, downgrade, or block the claim. No exceptions.

---

## 4. Execution order (locked)

1. INF-3 (I-20)  
2. INF-2 (I-19)  
3. INF-1 (I-17) — **blocked by** G3-R1 and **Trade-Impacting Route Inventory**  
4. INF-4 (§14.6) — **blocked by** route inventory + INF-3/INF-2 readiness  

Dependencies: `INF-3 → INF-1`, `INF-2 → INF-1`, `G3-R1 → INF-1`, inventory `→` INF-1 & INF-4 closure.

---

## 5. Critical policy locks (synthesis)

| Topic | Lock |
|--------|------|
| MC on trade path | **OFF** — advisory only (`PHASE_PLAN_INFRASTRUCTURE.md` §6.2) |
| INF-3 mismatch default | **BLOCK** (governed DEGRADE only with policy object) |
| INF-4 when halted | **Hard halt** — no normal prediction shape |
| Events | **Append-only** sink; minimum schema + types in `PHASE_PLAN_INFRASTRUCTURE.md` §10 |

---

## 6. Required next artifact (before INF-1 / INF-4 close)

**Trade-Impacting Route Inventory** — all decision paths, all trade-impacting outputs, all enforcement points. See `PHASE_PLAN_INFRASTRUCTURE.md` §5.

---

## 7. Rest of normative stack (already in repo)

- `governance/INSTITUTIONAL_STANDARD_V3.md`  
- `governance/V3_LOCK_RECORD.md`  
- `governance/V3_CONFORMANCE_AUDIT.md`  
- `OPEN_ITEMS.md`  

---

## 8. Document control

| Field | Value |
|--------|--------|
| **Version** | 1.0 |
| **Status** | REVIEW — bump to LOCKED after sign-off |
| **Owner** | Workstream 2 lead |
