> **Classification:** CI Triage | **Scope:** Non-blocking failures — triage required

# CI non-blocking failure triage (2026-06-18)

## Summary

Objective-audit is the merge gate for transport PRs #14–#16. **hardening**, **pytest-full**, and **schwab-csv-first** remain red. This is **OPEN_BLOCKING** technical debt — not normalized acceptance.

## hardening

| Field | Value |
|-------|-------|
| **Classification** | `PRE_EXISTING_BUT_BLOCKING` |
| **Current failing** | Institutional / governance checks in hardening workflow |
| **Related to recent PRs** | Partial — transport PRs did not target hardening.yml |
| **Why non-blocking** | Operator gate: objective-audit only |
| **Fix required** | Run hardening locally; fix root failures |
| **Recommended branch** | `audit/ci-nonblocking-failures-triage` |

## pytest-full

| Field | Value |
|-------|-------|
| **Classification** | `EXTERNAL_SECRET_REQUIRED` |
| **Current failing** | Full suite; common: `ModuleNotFoundError: No module named 'schwab'`, missing `SCHWAB_API_KEY` / `SCHWAB_APP_SECRET` in CI |
| **Related to recent PRs** | Pre-existing CI env gaps |
| **Why non-blocking** | Secrets not in GitHub Actions for all jobs |
| **Fix required** | CI secrets OR mark schwab-dependent tests with skip contract |
| **Recommended branch** | `audit/ci-nonblocking-failures-triage` |

## schwab-csv-first

| Field | Value |
|-------|-------|
| **Classification** | `FIX_NOW` |
| **Current failing** | Register / diff-emission workflow |
| **Related to recent PRs** | Transport PRs may touch server.py without register slice |
| **Why non-blocking** | Objective-audit covers broader static locks |
| **Fix required** | Per-job log root cause; register regen or workflow fix |
| **Recommended branch** | `audit/ci-nonblocking-failures-triage` |

## Decision

**Recommend immediate next fix branch:** `audit/ci-nonblocking-failures-triage` before `fix/card-price-conflict-explainability`.

**Closure criteria:** Each check green OR `ACCEPTED_WITH_EVIDENCE` with operator narrative in this file. Historical red-check normalization is not an admissible justification.
