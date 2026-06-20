> **Classification:** CI Triage | **Scope:** Non-blocking failures — triage and fixes (audit/ci-nonblocking-failures-triage)

# CI non-blocking failure triage (2026-06-18)

**Updated:** 2026-06-20 @ **`8c22aa9`** — GitHub `pytest-full` showed **17 failed, 3770 passed, 7 skipped** (run **27884930874**) = **product matrix only**. `ANTI_PATTERN_CAPS_VIOLATIONS` (1 test) is **CLOSED_WITH_EVIDENCE** (18 → 17); ACTIVE_BUNDLE, CALIBRATION_BYPASS, ET_AUTHORITY, and meta-artifact drift remain CLOSED; schwab-csv-first PASS.

## GitHub PR #19 checks (@ `8c22aa9`)

| Check | Status |
|-------|--------|
| objective-audit | **CLOSED_WITH_EVIDENCE** — pass (run 27884930889) |
| hardening | **CLOSED_WITH_EVIDENCE** — pass |
| schwab-csv-first | **CLOSED_WITH_EVIDENCE** — pass (run 27884930876 @ `8c22aa9`; first closed @ `741091b`) |
| pytest-full | **OPEN_BLOCKING** — `17 failed, 3770 passed, 7 skipped` (run **27884930874** @ `8c22aa9`) = **product matrix only** |

**Merge gate:** `pytest-full` (17 open product matrix rows). **Do not merge** PR #19 until pytest-full is green on GitHub OR every open product matrix row carries operator sign-off.

### Closure ladder (proven on GitHub)

| Bucket | Tests | Cleared @ | Run | Delta |
|--------|-------|-----------|-----|-------|
| `PYTEST_GOVERNANCE_META_PIN_DRIFT` | 2 | `5c6e967` | 27875496094 | 27 → 25 |
| `ACTIVE_BUNDLE_ENCODER_LAYOUT` | 3 | `0068226` | 27877046342 | 25 → 22 |
| `CALIBRATION_BYPASS_ALLOWLIST` | 2 | `7bf369c` | 27878597275 | 22 → 20 |
| `ET_AUTHORITY_DAILY_SCOREBOARD` | 2 | `ad96844`+`afb361d` | 27882570666 | 20 → 18 |
| `ANTI_PATTERN_CAPS_VIOLATIONS` | 1 | `8c22aa9` | 27884930874 | 18 → 17 |

### Remaining open product matrix buckets (17 tests, largest first)

| Bucket | Tests | Notes |
|--------|-------|-------|
| `STACK_WIRE_INTEGRITY` | 3 | stack_wire_1 ×2 + stack_integrity ×1 — server build_ts / decision_generation_id / mh_overlay contract drift in CI |
| `LIVE_BUNDLE_SSE_CACHE` | 3 | issue20_23 live bundle / SSE subscriber state not hermetic in full-suite order |
| `AUDIT_CAND_SERVER_CI_OFFLINE` | 2 | fast-quote / debug-prediction need quote data; CI offline |
| `UI_LEVEL_TEST_CHIP` | 2 | **BLOCKED** — INTENTIONAL_CONTRACT_LOCK; requires card-explainability lane (do not start) |
| `V2_CONFORMAL_TIER_C_PAYLOAD` | 2 | Tier C / conformal attachment markers absent in CI server path |
| `ML_PREDICT_STRICT_VERSION` | 1 | strict-bundle-blocked version string contract |
| `PRODUCTION_DB_PRED_1C_ABSENT_IN_CI` | 1 | CI has no prod ed_console.db; PRE_EXISTING_AND_ACCEPTED, operator sign-off for merge |
| `SILENT_EXCEPT_PASS_REMAINING` | 1 | remaining silent except:pass sites |
| `UI_V2_CONFIDENCE_LABELS` | 1 | **BLOCKED** — INTENTIONAL_CONTRACT_LOCK; UI lane (do not start) |
| `XGB_CONFLUENCE_SNAPSHOT_PARITY` | 1 | cf_* confluence columns differ between pipeline paths |

Largest open **non-blocked** buckets: `STACK_WIRE_INTEGRITY` (3) and `LIVE_BUNDLE_SSE_CACHE` (3). `UI_LEVEL_TEST_CHIP` (2) and `UI_V2_CONFIDENCE_LABELS` (1) are contract-locked to the UI / card-explainability lane and must not be started without operator authorization.

### Workflow gate (non-pytest)

| Failure group | Classification | Run | Notes |
|---------------|----------------|-----|-------|
| `SCHWAB_V4_DIFF_EMISSION_PR_GATE` | **CLOSED_WITH_EVIDENCE** @ `741091b` | PR 27870946980 + push 27870946302 | Excluded `governance/megaN_traceable_inventory.py` from diff-emission scan |

---

## Failure matrix (pytest-full) — 17 product tests (observed @ `8c22aa9`)

Machine-readable: `reports/ci/ci_nonblocking_failure_triage_2026-06-18.json` → `pytest_full_failure_matrix` (sum of `number_of_tests` = 17 = `pytest_full_product_matrix_failure_count` = current observed).

### Recommended next unblocked pytest bucket

**FIX_NOW** candidates (operator to select; not started): `STACK_WIRE_INTEGRITY` (3) or `LIVE_BUNDLE_SSE_CACHE` (3) — largest open non-blocked buckets.

---

## Decision

- `ci_triage_gate_pass: false`
- `operator_readiness_gate_pass: false`
- `card_explainability_allowed: false`
- `next_allowed_step: resolve_pytest_full_failures`
- `current_ci_verified_commit: 8c22aa9` (run 27884930874, 17 failed — product matrix only)
- `pytest_full_matrix_verified_commit: 8c22aa9`
- `expected_after_pending_push: 17` (artifact sync only; no pending local fix in this commit)
- **Do not merge** PR #19 until pytest-full green on GitHub PR #19 **and** schwab-csv-first `pull_request` green, with no unexplained paired failure.

---

## hardening

| Field | Value |
|-------|-------|
| **Classification** | `CLOSED_WITH_EVIDENCE` |
| **Closure criteria** | GitHub pass on PR #19 — met |

## schwab-csv-first

| Field | Value |
|-------|-------|
| **Classification** | `CLOSED_WITH_EVIDENCE` |
| **CI link** | pass run [27884930876](https://github.com/evargas963/Ed-s-Console-App/actions/runs/27884930876) @ `8c22aa9` (first closed @ `741091b`) |
| **Closure criteria** | schwab-csv-first green on PR #19 — met (run matches `ci_nonblocking_failure_triage_2026-06-18.json` `github_checks_last_observed`) |

## pytest-full

| Field | Value |
|-------|-------|
| **Classification** | `OPEN_BLOCKING` |
| **CI link** | run **27884930874** @ `8c22aa9` — `17 failed, 3770 passed, 7 skipped` = product matrix only (5 buckets CLOSED_WITH_EVIDENCE to date) |
| **Closure criteria** | pytest-full green OR every product matrix row accepted with operator sign-off |
