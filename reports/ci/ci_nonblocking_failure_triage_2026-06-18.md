> **Classification:** CI Triage | **Scope:** Non-blocking failures — triage and fixes (audit/ci-nonblocking-failures-triage)
<!-- FULL_FIX_GRANDFATHERED_PRE_V2: operator-approved migration 2026-07-09 — legacy CLOSED_WITH_EVIDENCE vocabulary in this artifact predates the V2 evidence gate; new closures must use the FULL_FIX template + FULL_FIX_EVIDENCE block (AGENTS § FULL_FIXES_ONLY_V2). -->

# CI non-blocking failure triage (2026-06-18)

**Updated:** 2026-06-21 @ **`4e252b3`** — GitHub `pytest-full` showed **7 failed, 3780 passed, 7 skipped** (run **27910195029**) = **product matrix only**. `REMOTE_ENFORCEMENT_EVIDENCE_LIVE_API` is **CLOSED_WITH_EVIDENCE** as a governance/external-flake blocker (objective-audit restored **PASS**; product matrix unchanged at 7, flaky test absent); nine prior buckets remain CLOSED; schwab-csv-first PASS.

## GitHub PR #19 checks (@ `4e252b3`)

| Check | Status |
|-------|--------|
| objective-audit | **CLOSED_WITH_EVIDENCE** — pass (run 27910195014; restored after REMOTE_ENFORCEMENT flake fix) |
| hardening | **CLOSED_WITH_EVIDENCE** — pass |
| schwab-csv-first | **CLOSED_WITH_EVIDENCE** — pass (run 27910195022 @ `4e252b3`; first closed @ `741091b`) |
| pytest-full | **OPEN_BLOCKING** — `7 failed, 3780 passed, 7 skipped` (run **27910195029** @ `4e252b3`) = **product matrix only** |

**Merge gate:** `pytest-full` (7 open product matrix rows). **Do not merge** PR #19 until pytest-full is green on GitHub OR every open product matrix row carries operator sign-off.

### Closure ladder (proven on GitHub)

| Bucket | Tests | Cleared @ | Run | Delta |
|--------|-------|-----------|-----|-------|
| `PYTEST_GOVERNANCE_META_PIN_DRIFT` | 2 | `5c6e967` | 27875496094 | 27 → 25 |
| `ACTIVE_BUNDLE_ENCODER_LAYOUT` | 3 | `0068226` | 27877046342 | 25 → 22 |
| `CALIBRATION_BYPASS_ALLOWLIST` | 2 | `7bf369c` | 27878597275 | 22 → 20 |
| `ET_AUTHORITY_DAILY_SCOREBOARD` | 2 | `ad96844`+`afb361d` | 27882570666 | 20 → 18 |
| `ANTI_PATTERN_CAPS_VIOLATIONS` | 1 | `8c22aa9` | 27884930874 | 18 → 17 |
| `STACK_WIRE_INTEGRITY` | 3 | `b44d5ab` | 27888713242 | 17 → 14 |
| `LIVE_BUNDLE_SSE_CACHE` | 3 | `d55dd5d` | 27890689248 | 14 → 11 |
| `AUDIT_CAND_SERVER_CI_OFFLINE` | 2 | `78c9192` | 27896087973 | 11 → 9 |
| `V2_CONFORMAL_TIER_C_PAYLOAD` | 2 | `0edb7ac` | 27903963832 | 9 → 7 |
| `REMOTE_ENFORCEMENT_EVIDENCE_LIVE_API` (governance/flake — not a product row) | 0 | `4e252b3` | 27910195029 | 7 → 7 (objective-audit red → green) |

### Remaining open product matrix buckets (7 tests, largest first)

| Bucket | Tests | Status / note |
|--------|-------|---------------|
| `UI_LEVEL_TEST_CHIP` | **2** | **BLOCKED** — INTENTIONAL_CONTRACT_LOCK, card-explainability lane (do not start) |
| `ML_PREDICT_STRICT_VERSION` | **1** | open, not blocked |
| `PRODUCTION_DB_PRED_1C_ABSENT_IN_CI` | **1** | PRE_EXISTING_AND_ACCEPTED — needs hermetic fixture/skip + operator sign-off |
| `SILENT_EXCEPT_PASS_REMAINING` | **1** | open, not blocked |
| `UI_V2_CONFIDENCE_LABELS` | **1** | **BLOCKED** — INTENTIONAL_CONTRACT_LOCK, UI lane (do not start) |
| `XGB_CONFLUENCE_SNAPSHOT_PARITY` | **1** | open, not blocked |

### Workflow gate (non-pytest)

| Failure group | Classification | Run | Notes |
|---------------|----------------|-----|-------|
| `SCHWAB_V4_DIFF_EMISSION_PR_GATE` | **CLOSED_WITH_EVIDENCE** @ `741091b` | PR 27870946980 + push 27870946302 | Excluded `governance/megaN_traceable_inventory.py` from diff-emission scan |

### Cleared @ `bc2e8a9` / `704b4b9`

| Bucket | Tests | Evidence |
|--------|-------|----------|
| `MEGA_INVENTORY_CONTRACT_LOCK` | 4 | GitHub pytest-full @ `a72ed54`: mega audit tests green |
| `ABLATION_GRID_RUNNABLE_ACCOUNTING` | 4 | objective-audit + ablation matrix green @ `704b4b9` |
| `GOVERNANCE_MUTATION_CALIBRATION_LOG_ENV` | 1 | mutation test green @ `704b4b9` |

---

## Failure matrix (pytest-full) — 7 product tests (observed @ `4e252b3`)

Machine-readable: `reports/ci/ci_nonblocking_failure_triage_2026-06-18.json` → `pytest_full_failure_matrix` (sum of `number_of_tests` = 7 = `pytest_full_product_matrix_failure_count` = current observed).

### Recommended next unblocked pytest bucket

**`ML_PREDICT_STRICT_VERSION`** (1). **FIX_NOW** — `test_get_model_version_fail_closed_when_strict_bundle_blocked`. Projected (unproven until GitHub): 7 → 6. Alternatives: `SILENT_EXCEPT_PASS_REMAINING` (1), `XGB_CONFLUENCE_SNAPSHOT_PARITY` (1).

---

## Decision

- `ci_triage_gate_pass: false`
- `operator_readiness_gate_pass: false`
- `card_explainability_allowed: false`
- `next_allowed_step: resolve_pytest_full_failures`
- `current_ci_verified_commit: 4e252b3` (run 27910195029, 7 failed — product matrix only; objective-audit restored PASS)
- `pytest_full_matrix_verified_commit: 4e252b3`
- `expected_after_pending_push: 7` (artifact sync only; observed == projected; ML_PREDICT_STRICT_VERSION projects 6 only after its fix lands, unproven until GitHub)
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
| **CI link** | pass run [27910195022](https://github.com/evargas963/Ed-s-Console-App/actions/runs/27910195022) @ `4e252b3` (first closed @ `741091b`) |
| **Closure criteria** | schwab-csv-first green on PR #19 — met (run matches `ci_nonblocking_failure_triage_2026-06-18.json` `github_checks_last_observed`) |

## pytest-full

| Field | Value |
|-------|-------|
| **Classification** | `OPEN_BLOCKING` |
| **CI link** | run **27910195029** @ `4e252b3` — `7 failed, 3780 passed, 7 skipped` = product matrix only (9 product buckets CLOSED_WITH_EVIDENCE + REMOTE_ENFORCEMENT governance/flake closed) |
| **Closure criteria** | pytest-full green OR every product matrix row accepted with operator sign-off |
