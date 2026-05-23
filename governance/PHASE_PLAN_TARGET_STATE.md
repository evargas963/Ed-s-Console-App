> **Classification:** Policy Specification | **Scope:** Governance policy/contract `PHASE_PLAN_TARGET_STATE.md`.

# Phase Plan — Institutional Target State (Strategic)

**Document class:** Strategic north-star and gap map.  
**Not:** Implementation checklist, INF execution order, or remediation tickets.

**Normative references:**

- `governance/INSTITUTIONAL_STANDARD_V3.md`
- `governance/V3_LOCK_RECORD.md`
- `governance/V3_CONFORMANCE_AUDIT.md`
- `OPEN_ITEMS.md`

**Companion (executable infrastructure work):** `governance/PHASE_PLAN_INFRASTRUCTURE.md`  
**Lock-package index:** `governance/INFRASTRUCTURE_GOVERNANCE_LOCK_PACKAGE.md`

---

## 0. Core doctrine (non-negotiable)

1. **Design** for institutional capability — not the ceiling of the current application.  
2. **Execute** against evidenced gaps (audit + this plan’s gap map).  
3. **Closure** of any conformance claim = enforceable + auditable + non-bypassable + proof + claim binding (see infrastructure plan §0).

---

## 1. Purpose

This artifact defines the **institutional end-state** the program intends to reach, independent of the current application shape. It exists so execution plans (model lifecycle G2–G5, infrastructure INF-1–INF-4, future phases) cannot silently redefine “done” as “best possible version of today’s shortcuts.”

**Enforceable claim:** Any phase plan that does not trace requirements to a capability in §3 is out of authority for institutional conformance claims.

---

## 2. Definition of institutional quality (operational)

Institutional quality means the organization can produce **evidence** that:

| Claim | Evidence class |
|--------|------------------|
| Every production decision is traceable | Manifest chain: data snapshot → transforms → weights/config → promotion record → blessed pointer |
| Failure behavior is bounded | Versioned degradation matrix; machine-readable degraded-mode signals; no silent substitution |
| Change is attributable | Actor, rationale, rollback pointer; separation of duties for material changes |
| Conformance is binary where declared | `CONFORMS` vs tracked non-conformance; no “mostly conforms” |
| Runtime is provable | Tuple health, determinism or declared tolerance, pinned serving environment, clock health, halt authority |

Source principles: `INSTITUTIONAL_STANDARD_V3.md` §1, §2 (invariants I-01–I-20), §5.5, §12–§14.

---

## 3. Capability model (P0–P7)

Phases are **capabilities**, not calendar quarters. Multiple capabilities may advance in parallel once upstream gates are satisfied.

### P0 — Risk and operating model (non-software)

**Outcomes:** MRM-style inventory; materiality tiers; RACI; incident classes; approval rules for production promotion; retention/legal hold for decision logs.

**Gate:** Signed architecture declaration and degradation policy matrix owned by model risk and technical risk (V3 §3, §5.5).

### P1 — Canonical contracts and causal discipline

**Outcomes:** Single clock hierarchy; causal “as-of” contract for all joins and labels; versioned feature/label contracts per tuple `(symbol, horizon, architecture role)`; output schema versioning with explicit bump discipline.

**Gate:** Paths that cannot prove contract version + causal gate are **non-loadable** for trade impact (I-03, I-04, I-05, V3 §6, §8).

### P2 — Immutable artifacts and lineage

**Outcomes:** Content-addressed artifact store; immutable bundles; child attachments bound to parent hashes; no orphan loadable paths; periodic integrity checks on blessed pointers.

**Gate:** Promotion consumes only hashed bundles; active influence flows only through blessed records (I-06, I-07, V3 §12).

### P3 — Comparator evaluation and single promotion authority

**Outcomes:** Exactly one governed promotion mechanism; pre-declared OOS/embargo; peer evaluation under identical contract slots; signed evaluation artifacts; binding promotion decision record.

**Gate:** No alternate writers to serving pointers; no authoritative-looking fields that are non-binding (I-02, I-11, I-12, I-14).

### P4 — Train–serve parity and tuple health

**Outcomes:** Parity evidence (fixtures/reports) for train–serve transform identity; tuple health matrix enforced before capital exposure; validator and runtime agree on bundle validity.

**Gate:** No tuple influences capital without passing health for its operational tier (I-05, I-15, V3 §4).

### P5 — Deterministic, observable inference

**Outcomes:** Per-architecture determinism policy with published tolerance; decomposition traces; telemetry and drift monitors; expected divergence bands for peer comparison where applicable.

**Gate:** Severity-1 invariant breaches page governance and operations (I-01, I-16, I-17, V3 §13).

### P6 — Production operations: capacity, environment, continuity

**Outcomes:** Bounded concurrency and explicit fairness; **environment fingerprint** on serving bundle; dependency drift as governance event; clock sync monitoring; BC/DR for artifacts and audit logs.

**Gate:** Serving manifest pins dependencies; sync skew monitored; kill switch / halt exercised under drill conditions (I-18–I-20, V3 §14, §16).

### P7 — Continuous conformance and attestation

**Outcomes:** Recurring automated conformance audits; periodic human review; governed override with time-box; regulator/board-ready attestation from recurring evidence.

**Gate:** Binary posture per scope; **no silent non-conformance** (V3 lock record; V3 §20).

---

## 4. Current-system gap map (Ed Web Console)

Mapping is **descriptive** of the repository and governance artifacts as of the V3 conformance audit and `OPEN_ITEMS.md`. It does not assign implementation tickets.

| Target capability | Gap (summary) | Primary evidence |
|-------------------|---------------|-------------------|
| P0 | Written standard and audit exist; **organizational** MRM cadence and attestation are not proven by code alone. | `INSTITUTIONAL_STANDARD_V3.md`, `V3_CONFORMANCE_AUDIT.md` |
| P1 | Label/horizon presentation vs training columns still reconciling; **global causal gate** not enforced on all production emissions. | `OPEN_ITEMS.md` (label vs presentation); audit I-03, I-04 |
| P2 | Candidate manifests include hashes; **active path** can still be touched by non-governed writers; partial bundles / fallbacks reachable. | `OPEN_ITEMS.md` G4; audit I-06, I-07 |
| P3 | Multiple promotion/write paths; **G3-R3** blocks governed evaluation output; **G3-R2** non-authoritative promotion field. | `OPEN_ITEMS.md`; audit I-02, I-11 |
| P4 | **G3-R1:** validator vs runtime disagree on “complete active bundle”; tuple-health matrix not a single production gate. | `OPEN_ITEMS.md` G3-R1; audit §4, I-15 |
| P5 | **INF-1** HIGH gap: no formal determinism contract + verifier; path-dependent stack behavior. | `V3_CONFORMANCE_AUDIT.md` I-17 |
| P6 | **INF-2, INF-3, INF-4** HIGH gaps; partial backpressure (e.g. SSE) ≠ global capacity policy. | Audit I-18–I-20; `OPEN_ITEMS.md` Workstream 2 |
| P7 | Audit shows **predominantly non-CONFORMS**; infrastructure phase plan was **previously absent** (now `PHASE_PLAN_INFRASTRUCTURE.md`). | `OPEN_ITEMS.md`, this file |

**Cross-cutting:** Monolithic FastAPI + filesystem `models/` convenience patterns conflict with **active path sanctity** (V3 §12) unless explicitly bounded or replaced by pointer/indirection + enforcement.

---

## 5. Traceability to V3

| P-phase | Primary V3 anchors |
|---------|-------------------|
| P0 | §1, §20, lock record |
| P1 | I-03, I-04, I-05, §6, §8 |
| P2 | I-06, I-07, §12 |
| P3 | I-02, I-11, I-12, I-14, §12 |
| P4 | I-05, I-15, §4 |
| P5 | I-01, I-16, I-17, §13 |
| P6 | I-18, I-19, I-20, §14, §16 |
| P7 | Lock conditions 2–3, §20 |

---

## 6. Document control

| Field | Value |
|--------|--------|
| **Owner** | Program governance lead (delegate until named in audit) |
| **Classification** | Internal governance |
| **Amendment** | V3 §20; breaking changes to capability definitions require version bump of this document |
| **Related** | `PHASE_PLAN_INFRASTRUCTURE.md` (INF execution), `OPEN_ITEMS.md` (tracked items) |

**Version:** 1.0  
**Status:** ACTIVE
