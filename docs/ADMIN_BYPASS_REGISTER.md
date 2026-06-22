> **Classification:** Register | **Scope:** Admin merge bypasses when CI checks fail

# Admin bypass register

**Rule:** `--admin` merge or merge with failed required checks must have a row here. **Closure criteria** and **Follow-up branch** are mandatory.

## PR #14 — SQLite contention impact audit

| Field | Value |
|-------|-------|
| **PR number** | 14 |
| **Checks failing** | hardening, pytest-full, schwab-csv-first |
| **Required check status** | objective-audit PASS |
| **Reason merge proceeded** | Operator gate: objective-audit only for audit PRs |
| **Risk accepted** | Non-blocking CI debt remains triaged separately |
| **Follow-up branch** | `audit/ci-nonblocking-failures-triage` |
| **Closure criteria** | Each failing check classified + green or `ACCEPTED_WITH_EVIDENCE` |

## PR #15 — DB contention surface

| Field | Value |
|-------|-------|
| **PR number** | 15 |
| **Checks failing** | hardening, pytest-full, schwab-csv-first |
| **Required check status** | objective-audit PASS |
| **Reason merge proceeded** | Surface-only visibility fix; objective-audit green |
| **Risk accepted** | CI red checks not triaged at merge time |
| **Follow-up branch** | `audit/ci-nonblocking-failures-triage` |
| **Closure criteria** | CI triage report + fix branch decision |

## PR #16 — Guest switch SLA diagnostics

| Field | Value |
|-------|-------|
| **PR number** | 16 |
| **Checks failing** | hardening, pytest-full, schwab-csv-first |
| **Required check status** | objective-audit PASS |
| **Reason merge proceeded** | Transport diagnostics scoped; objective-audit green |
| **Risk accepted** | `LIVE_GUEST_SLA_NOT_PROVEN` left without harness at merge — **process miss** |
| **Follow-up branch** | `stabilize/operator-trust-backtrack` |
| **Closure criteria** | `tools/run_rth_guest_switch_validation.py` + RTH run PASS evidence |

## PR #18 — Operator-trust stabilization backtrack

| Field | Value |
|-------|-------|
| **PR number** | 18 |
| **Checks failing** | hardening, pytest-full, schwab-csv-first (mixed) |
| **Required check status** | objective-audit PASS |
| **Reason merge proceeded** | Stabilization mechanics (harnesses + checker + gate); objective-audit green |
| **Risk accepted** | CI checks red/mixed — fixes required in `audit/ci-nonblocking-failures-triage` |
| **Follow-up branch** | `audit/ci-nonblocking-failures-triage` |
| **Closure criteria** | Each CI check `FIXED_NOW` verified green on GitHub `main` |
