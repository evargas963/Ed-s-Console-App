# Governance Event Model (Draft)

**Status:** DRAFT for INF workstream  
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

Extensions (optional): `REGRESSION_CONFORMS`, `CLAIM_WITHDRAWN`, `GOVERNANCE_OVERRIDE_APPLIED`.

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

## 3. Storage options

| Option | Pros | Cons |
|--------|------|------|
| **Append-only JSONL** | Simple, git-friendly exports | Query tooling manual |
| **SQLite table** | Queryable, transactional | Same-DB as app if cohosted — document threat model |
| **External** (SIEM, cloud log) | Independence | Ops cost |

**Recommended for current monolith (draft):** **SQLite dedicated table** `governance_events` with INSERT-only application policy **or** JSONL under `var/governance_events/` with fsync policy — **operator chooses** in Operator Decision Register.

---

## 4. Retention & deletion

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

**RESULT:** **PASS** (model sufficient for INF authoring; storage choice remains operator decision).
