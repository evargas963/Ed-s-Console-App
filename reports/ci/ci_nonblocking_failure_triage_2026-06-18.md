> **Classification:** CI Triage | **Scope:** Non-blocking failures — triage and fixes (audit/ci-nonblocking-failures-triage)

# CI non-blocking failure triage (2026-06-18)

**Updated:** 2026-06-20 @ **`0068226`** — GitHub `pytest-full` showed **22 failed, 3765 passed, 7 skipped** (run **27877046342**) = **product matrix only**. `ACTIVE_BUNDLE_ENCODER_LAYOUT` (3 tests) is **CLOSED_WITH_EVIDENCE** (25 → 22); the +2 governance meta-artifact pin drift remains CLOSED.

## GitHub PR #19 checks (@ `0068226`)

| Check | Status |
|-------|--------|
| objective-audit | **CLOSED_WITH_EVIDENCE** — pass |
| hardening | **CLOSED_WITH_EVIDENCE** — pass |
| schwab-csv-first | **CLOSED_WITH_EVIDENCE** — push [27870946302](https://github.com/evargas963/Ed-s-Console-App/actions/runs/27870946302) + PR [27870946980](https://github.com/evargas963/Ed-s-Console-App/actions/runs/27870946980) @ `741091b` |
| pytest-full | **OPEN_BLOCKING** — `22 failed, 3765 passed, 7 skipped` (run **27877046342** @ `0068226`) = **product matrix only** |

**Merge gate:** `pytest-full` (22 open product matrix rows). **Do not merge** PR #19 until pytest-full is green on GitHub OR every open product matrix row carries operator sign-off.

### Closure ladder (proven on GitHub)

| Bucket | Tests | Cleared @ | Run | Delta |
|--------|-------|-----------|-----|-------|
| `PYTEST_GOVERNANCE_META_PIN_DRIFT` | 2 | `5c6e967` | 27875496094 | 27 → 25 |
| `ACTIVE_BUNDLE_ENCODER_LAYOUT` | 3 | `0068226` | 27877046342 | 25 → 22 |

`ACTIVE_BUNDLE_ENCODER_LAYOUT` is now `number_of_tests: 0` in the matrix; its three tests are absent from the GitHub failure list at `0068226`.

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

## Failure matrix (pytest-full) — 22 product tests (observed @ `0068226`)

Machine-readable: `reports/ci/ci_nonblocking_failure_triage_2026-06-18.json` → `pytest_full_failure_matrix` (sum of `number_of_tests` = 22 = `pytest_full_product_matrix_failure_count` = current observed).

### In-progress pytest bucket

**`CALIBRATION_BYPASS_ALLOWLIST`** — 2 tests, `audit/ci-nonblocking-failures-triage`, not branch-blocked. Allowlist fix **landed locally** in `tests/test_calibration_bypass_closure.py` (server.py log/probe strings, read-only audit/observability tooling + verification modules, and three test fixtures — all verified non-INSERT/UPDATE in production). 2/2 calibration tests pass locally. Expected (projection, unproven until GitHub): 22 → 20.

### Recommended next unblocked pytest bucket (after CALIBRATION GitHub proof)

**`ET_AUTHORITY_DAILY_SCOREBOARD`** — 2 tests. **FIX_NOW** — `calibration/daily_scoreboard.py` assigns `ZoneInfo` outside `time_et.py`; closure on importing the NY zone from `time_et` only.

---

## Decision

- `ci_triage_gate_pass: false`
- `operator_readiness_gate_pass: false`
- `card_explainability_allowed: false`
- `next_allowed_step: resolve_pytest_full_failures`
- `current_ci_verified_commit: 0068226` (run 27877046342, 22 failed — product matrix only)
- `pytest_full_matrix_verified_commit: 0068226`
- `expected_after_pending_push: 20` (CALIBRATION_BYPASS_ALLOWLIST fix landed locally; projection, unproven until GitHub)
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
| **CI link** | PR [27870946980](https://github.com/evargas963/Ed-s-Console-App/actions/runs/27870946980) + push [27870946302](https://github.com/evargas963/Ed-s-Console-App/actions/runs/27870946302) @ `741091b` |
| **Closure criteria** | `pull_request` + push schwab-csv-first green on PR #19 — met @ `741091b` (canonical run pair; matches `ci_nonblocking_failure_triage_2026-06-18.json` `github_checks_last_observed`) |

## pytest-full

| Field | Value |
|-------|-------|
| **Classification** | `OPEN_BLOCKING` |
| **CI link** | run **27877046342** @ `0068226` — `22 failed, 3765 passed, 7 skipped` = product matrix only (ACTIVE_BUNDLE + meta-artifact drift CLOSED_WITH_EVIDENCE) |
| **Closure criteria** | pytest-full green OR every product matrix row accepted with operator sign-off |
