> **Classification:** CI Triage | **Scope:** Non-blocking failures — triage and fixes (audit/ci-nonblocking-failures-triage)

# CI non-blocking failure triage (2026-06-18)

**Updated:** 2026-06-20 — schwab PR diff-emission fix in flight; pytest-full **25** confirmed @ `a72ed54`.

## GitHub PR #19 checks (@ `a72ed54`)

| Check | Status |
|-------|--------|
| objective-audit | **CLOSED_WITH_EVIDENCE** — pass [27857853561](https://github.com/evargas963/Ed-s-Console-App/actions/runs/27857853561) |
| hardening | **CLOSED_WITH_EVIDENCE** — pass |
| schwab-csv-first | **OPEN_BLOCKING** — push pass [27857852538](https://github.com/evargas963/Ed-s-Console-App/actions/runs/27857852538); **PR fail** [27857853589](https://github.com/evargas963/Ed-s-Console-App/actions/runs/27857853589) |
| pytest-full | **OPEN_BLOCKING** — `25 failed, 3761 passed, 7 skipped` (run **27857853572**) |

**Merge gate:** `pytest-full` + **pull_request** `schwab-csv-first` (push-only pass is not merge sign-off).

### Workflow gate (non-pytest)

| Failure group | Classification | Run | Notes |
|---------------|----------------|-----|-------|
| `SCHWAB_V4_DIFF_EMISSION_PR_GATE` | **OPEN_BLOCKING** | 27857853589 | Step 9 V4 diff-emission failed; CSV-first guard passed; 35 false sites from mega inventory diff — fix excludes `governance/megaN_traceable_inventory.py` |

### Cleared @ `a72ed54`

| Bucket | Tests | Evidence |
|--------|-------|----------|
| `MEGA_INVENTORY_CONTRACT_LOCK` | 4 | GitHub pytest-full @ `a72ed54`: mega audit tests green |

### Cleared @ `704b4b9`

| Bucket | Tests | Evidence |
|--------|-------|----------|
| `ABLATION_GRID_RUNNABLE_ACCOUNTING` | 4 | objective-audit + ablation matrix green |
| `GOVERNANCE_MUTATION_CALIBRATION_LOG_ENV` | 1 | mutation test green |

---

## Failure matrix (pytest-full) — 25 tests @ `a72ed54`

Machine-readable: `reports/ci/ci_nonblocking_failure_triage_2026-06-18.json` → `pytest_full_failure_matrix`.

### Recommended next unblocked pytest bucket

**`ACTIVE_BUNDLE_ENCODER_LAYOUT`** — 3 tests (after schwab PR path green).

---

## Decision

- `ci_triage_gate_pass: false`
- `next_allowed_step: resolve_pytest_full_failures`
- `last_verified_commit: a72ed54`
- `card_explainability_allowed: false`
- **Do not merge** until pytest-full green + schwab-csv-first **pull_request** green with no unexplained paired failure.

---

## hardening

| Field | Value |
|-------|-------|
| **Classification** | `CLOSED_WITH_EVIDENCE` |
| **Closure criteria** | GitHub pass @ `a72ed54` |

## schwab-csv-first

| Field | Value |
|-------|-------|
| **Classification** | `OPEN_BLOCKING` |
| **CI link** | PR fail [27857853589](https://github.com/evargas963/Ed-s-Console-App/actions/runs/27857853589/job/82448505652) — V4 diff-emission register gate; push pass [27857852538](https://github.com/evargas963/Ed-s-Console-App/actions/runs/27857852538) |
| **Closure criteria** | `pull_request` schwab-csv-first green on PR #19; push + PR both pass |

## pytest-full

| Field | Value |
|-------|-------|
| **Classification** | `OPEN_BLOCKING` |
| **CI link** | run **27857853572** — `25 failed, 3761 passed, 7 skipped` @ `a72ed54` |
| **Closure criteria** | pytest-full green OR every matrix row accepted with operator sign-off |
