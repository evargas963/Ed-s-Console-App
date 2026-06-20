> **Classification:** CI Triage | **Scope:** Non-blocking failures — triage and fixes (audit/ci-nonblocking-failures-triage)

# CI non-blocking failure triage (2026-06-18)

**Updated:** 2026-06-20 @ **`ab7029a`** — GitHub `pytest-full` showed **27 failed, 3760 passed, 7 skipped** (run **27871627823**) = **25 product matrix** + **2 governance meta-artifact pin drift**. The +2 are fixed in this commit; the product matrix is unchanged at **25**.

## GitHub PR #19 checks (@ `ab7029a`)

| Check | Status |
|-------|--------|
| objective-audit | **CLOSED_WITH_EVIDENCE** — pass |
| hardening | **CLOSED_WITH_EVIDENCE** — pass |
| schwab-csv-first | **CLOSED_WITH_EVIDENCE** — push [27870946302](https://github.com/evargas963/Ed-s-Console-App/actions/runs/27870946302) + PR [27870946980](https://github.com/evargas963/Ed-s-Console-App/actions/runs/27870946980) @ `741091b` |
| pytest-full | **OPEN_BLOCKING** — `27 failed, 3760 passed, 7 skipped` (run **27871627823** @ `ab7029a`) = **25 product matrix** + **2 governance meta-artifact pin drift** |

**Merge gate:** `pytest-full` (25 open product matrix rows). **Do not merge** PR #19 until pytest-full is green on GitHub OR every open product matrix row carries operator sign-off.

### `25 → 27` delta @ `ab7029a` — explained

| | `a72ed54` run 27857853572 | `ab7029a` run 27871627823 |
|--|--|--|
| Failed | 25 | 27 |
| Product matrix | 25 | 25 (unchanged set) |
| Governance meta-artifact pin drift | 0 | 2 (added) |

The added **+2** are both meta-tests that guard the triage/gate artifacts themselves:

1. `tests/test_operator_trust_governance.py::test_stabilization_gate_blocks_card_explainability`
2. `tests/test_operator_trust_governance.py::test_ci_triage_has_classifications_and_closure_criteria`

**Classification: governance meta-artifact pin drift.** They are **not** product regressions, **not** Schwab runtime regressions, and **not** `ACTIVE_BUNDLE_ENCODER_LAYOUT` failures. They broke when the gate JSON / triage docs were edited for the schwab-csv-first closure without re-syncing the values these tests pin (`last_verified_commit` and the `FIX_NOW` token). This commit resyncs the pins to explicit, non-overloaded fields and restores the token — no product/Schwab/ACTIVE_BUNDLE code is touched.

### Workflow gate (non-pytest)

| Failure group | Classification | Run | Notes |
|---------------|----------------|-----|-------|
| `SCHWAB_V4_DIFF_EMISSION_PR_GATE` | **CLOSED_WITH_EVIDENCE** @ `741091b` | PR 27870946980 + push 27870946302 | Excluded `governance/megaN_traceable_inventory.py` from diff-emission scan |
| `PYTEST_GOVERNANCE_META_PIN_DRIFT` | **FIXED_NOW** (local; pending GitHub re-run) | 27871627823 | +2 meta-artifact pin drift — not product regression |

### Cleared @ `bc2e8a9` / `704b4b9`

| Bucket | Tests | Evidence |
|--------|-------|----------|
| `MEGA_INVENTORY_CONTRACT_LOCK` | 4 | GitHub pytest-full @ `a72ed54`: mega audit tests green |
| `ABLATION_GRID_RUNNABLE_ACCOUNTING` | 4 | objective-audit + ablation matrix green @ `704b4b9` |
| `GOVERNANCE_MUTATION_CALIBRATION_LOG_ENV` | 1 | mutation test green @ `704b4b9` |

---

## Failure matrix (pytest-full) — 25 product tests

Machine-readable: `reports/ci/ci_nonblocking_failure_triage_2026-06-18.json` → `pytest_full_failure_matrix` (sum of `number_of_tests` = 25 = `pytest_full_product_matrix_failure_count`).

### Recommended next unblocked pytest bucket (NOT started in this commit)

**`ACTIVE_BUNDLE_ENCODER_LAYOUT`** — 3 tests, `fix/ci-active-bundle-fixture`, not branch-blocked. **FIX_NOW** — CI lacks complete `active_5c/SPY` strict bundle fixture. This bucket is a separate commit; it is intentionally **not** part of this +2 pin-drift fix.

> After `ACTIVE_BUNDLE_ENCODER_LAYOUT` clears on a **future** GitHub run, the projected count is 22. That 22 is unproven until GitHub produces it and is **not** asserted in any authoritative count field here. `expected_after_pending_push` for this commit is **25** (the product matrix once the +2 pin drift clears).

---

## Decision

- `ci_triage_gate_pass: false`
- `operator_readiness_gate_pass: false`
- `card_explainability_allowed: false`
- `next_allowed_step: resolve_pytest_full_failures`
- `current_ci_verified_commit: ab7029a` (run 27871627823, 27 failed)
- `pytest_full_matrix_verified_commit: a72ed54` (product matrix baseline, 25)
- `latest_artifact_update_commit: ab7029a`
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
| **CI link** | run **27871627823** @ `ab7029a` — `27 failed, 3760 passed, 7 skipped` = **25 product matrix** + **2 governance meta-artifact pin drift** |
| **Closure criteria** | pytest-full green OR every product matrix row accepted with operator sign-off |
