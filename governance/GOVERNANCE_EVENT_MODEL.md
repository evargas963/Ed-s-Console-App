> **Classification:** Policy Specification | **Scope:** Governance documentation `GOVERNANCE_EVENT_MODEL.md`.

# Governance Event Model

**Status:** **ACTIVE** — in-force operational authority for field semantics and payload shapes referenced by `PHASE_PLAN_INFRASTRUCTURE.md` §10 and bound by register entries **O-16**, **O-17**, **O-18**, and **O-19**. **ACTIVE** is not **LOCKED**; amendments follow register-coordinated updates (binding values remain upstream in `OPERATOR_DECISION_REGISTER.md` and the phase plan per **R-08** / **R-09**).  
**Date:** 2026-05-01  

---

## 1. Event types (required minimum)

| Event type | When emitted | Typical invariant |
|------------|----------------|-------------------|
| `REPLAY_FAILURE` | Replay harness outside tolerance or path identity mismatch | I-17 |
| `CLOCK_SKEW_BREACH` | Skew beyond declared bound or unknown clock for trade path | I-19 |
| `INFRA_DRIFT` | Environment fingerprint mismatch or missing blessed env | I-20 |
| `HALT_ACTIVATION` | Any scope enters halted state | §14.6 |
| `HALT_RELEASE` | Transition from halt to active (via `REACTIVATION_PENDING` if required) | §14.6 |
| `VALIDATION_FAILURE` | Tuple health / schema / bundle validator failure on trade path | I-15, I-08 |
| `SYNTHETIC_BUNDLE_SERVED` | Once per synthetic bundle response to a **non-localhost** client (per phase plan §5.2 / §10 synthetic policy) | Synthetic policy |

Extensions (optional, **non-authoritative** unless promoted via register — register **O-18**): `REGRESSION_CONFORMS`, `CLAIM_BOUNDARY_CHANGE`, `CLAIM_WITHDRAWN`, `GOVERNANCE_OVERRIDE_APPLIED`.

---

## 2. Required schema (every event)

| Field | Type | Required |
|-------|------|----------|
| `event_id` | UUID string | YES |
| `event_type` | enum string | YES |
| `invariant` | e.g. `I-17`, `I-19`, `I-20`, `§14.6` | YES |
| `severity` | e.g. `SEVERITY_1`, `INFO` | YES |
| `scope` | JSON object (ticker, horizon, route_id, etc.) | YES |
| `actor` | string (user id, `system`, `scheduler`) | YES |
| `timestamp_utc` | RFC3339 | YES |
| `artifact_identity` | string or structured ref (manifest hashes) | YES when applicable |
| `environment_fingerprint` | string or ref | YES when applicable (INF-3) |
| `details` | human + machine readable | YES |
| `resolution_status` | `OPEN` \| `RESOLVED` | YES |
| `supersedes_event_id` | UUID optional | For corrections without UPDATE-in-place |

---

## 3. Storage (register **O-16**)

Governance events are stored in the SQLite table **`governance_events`** at **`DB_PATH`**. This uses the same SQLite database authority as application data under the **Single-Operator Control Model**; same-DB coupling is accepted for the current implementation, and a dedicated audit store is deferred until a future register decision. Application code is **INSERT-only** — no **UPDATE** or **DELETE**. **INSERT** authority is limited to the serving process (`uvicorn server:app` with **`ED_SERVING_PROCESS=1`**) unless a future register decision explicitly authorizes a tool or script writer.

---

## 4. Retention & deletion

**Retention duration**, archival behavior, and deletion policy are **non-authoritative** / **deferred** per `OPERATOR_DECISION_REGISTER.md` **O-19** until a future register entry defines them.

- **Append-only** ingestion; corrections via new row + `supersedes_event_id`.
- **Severity-1:** no delete in normal ops; archival to cold storage with integrity manifest permitted.

---

## 5. Reviewer / resolution workflow

1. **On emit:** automated sink + optional notify.  
2. **On SEVERITY-1:** on-call + governance lead within SLA (operator-defined).  
3. **Resolution:** human sets follow-up event or updates workflow tool; `resolution_status` closed only with two-person rule if program requires.

---

## 6. Regression behavior

If a control was `CONFORMS` and a later check fails → emit `VALIDATION_FAILURE` or `REPLAY_FAILURE`; **withdraw** affected production claims; track remediation per `V3_LOCK_RECORD.md`.

---

**RESULT:** **PASS** — **ACTIVE** (event types, storage, and INSERT authority bound by register **O-16**/**O-17**/**O-18**; retention deferred per **O-19**).
