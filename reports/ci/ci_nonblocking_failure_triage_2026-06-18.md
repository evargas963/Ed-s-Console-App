> **Classification:** CI Triage | **Scope:** Non-blocking failures — triage and fixes (audit/ci-nonblocking-failures-triage)

# CI non-blocking failure triage (2026-06-18)

**Updated:** 2026-06-20 @ **`5c6e967`** — GitHub `pytest-full` showed **25 failed, 3762 passed, 7 skipped** (run **27875496094**) = **product matrix only**. The +2 governance meta-artifact pin drift is **CLOSED_WITH_EVIDENCE** (27 → 25). The next bucket, `ACTIVE_BUNDLE_ENCODER_LAYOUT` (3 tests), is **fixed locally and pending GitHub proof** (expected 25 → 22).

## GitHub PR #19 checks (@ `5c6e967`)

| Check | Status |
|-------|--------|
| objective-audit | **CLOSED_WITH_EVIDENCE** — pass |
| hardening | **CLOSED_WITH_EVIDENCE** — pass |
| schwab-csv-first | **CLOSED_WITH_EVIDENCE** — push [27870946302](https://github.com/evargas963/Ed-s-Console-App/actions/runs/27870946302) + PR [27870946980](https://github.com/evargas963/Ed-s-Console-App/actions/runs/27870946980) @ `741091b` |
| pytest-full | **OPEN_BLOCKING** — `25 failed, 3762 passed, 7 skipped` (run **27875496094** @ `5c6e967`) = **product matrix only** |

**Merge gate:** `pytest-full` (25 open product matrix rows). **Do not merge** PR #19 until pytest-full is green on GitHub OR every open product matrix row carries operator sign-off.

### `27 → 25` delta — CLOSED

The +2 added at `ab7029a` were both meta-tests guarding the triage/gate artifacts (`test_operator_trust_governance.py::test_stabilization_gate_blocks_card_explainability` and `::test_ci_triage_has_classifications_and_closure_criteria`). They were governance meta-artifact pin drift — not product, Schwab, or `ACTIVE_BUNDLE` regressions. Fixed at `5c6e967` (artifacts + meta-test pins resynced together); GitHub run `27875496094` confirms **25** with both meta-tests passing.

### `25 → 22` in progress — `ACTIVE_BUNDLE_ENCODER_LAYOUT` (local fix pending GitHub proof)

`ACTIVE_BUNDLE_ENCODER_LAYOUT` (3 tests) is fixed locally in `tests/test_active_bundle_contract_v1.py` + `tests/test_active_horizon_layout_pr3.py` (real strict-bundle stubs: `torch.save` seq stub with current encoder widths + pickled meta; v1 < minimum-v2 rejection assertions). **10/10 active-bundle tests pass locally.** The bucket stays counted at 3 in the product matrix until GitHub proves the drop — **22 is a projection, not written as an observed count** until a future GitHub run produces it.

### Workflow gate (non-pytest)

| Failure group | Classification | Run | Notes |
|---------------|----------------|-----|-------|
| `SCHWAB_V4_DIFF_EMISSION_PR_GATE` | **CLOSED_WITH_EVIDENCE** @ `741091b` | PR 27870946980 + push 27870946302 | Excluded `governance/megaN_traceable_inventory.py` from diff-emission scan |
| `PYTEST_GOVERNANCE_META_PIN_DRIFT` | **CLOSED_WITH_EVIDENCE** @ `5c6e967` | 27875496094 | +2 meta-artifact pin drift; proven 27 → 25 |

### Cleared @ `bc2e8a9` / `704b4b9`

| Bucket | Tests | Evidence |
|--------|-------|----------|
| `MEGA_INVENTORY_CONTRACT_LOCK` | 4 | GitHub pytest-full @ `a72ed54`: mega audit tests green |
| `ABLATION_GRID_RUNNABLE_ACCOUNTING` | 4 | objective-audit + ablation matrix green @ `704b4b9` |
| `GOVERNANCE_MUTATION_CALIBRATION_LOG_ENV` | 1 | mutation test green @ `704b4b9` |

---

## Failure matrix (pytest-full) — 25 product tests (observed @ `5c6e967`)

Machine-readable: `reports/ci/ci_nonblocking_failure_triage_2026-06-18.json` → `pytest_full_failure_matrix` (sum of `number_of_tests` = 25 = `pytest_full_product_matrix_failure_count` = current observed). `ACTIVE_BUNDLE_ENCODER_LAYOUT` carries `local_fix_status: FIXED_LOCAL_PENDING_GITHUB_PROOF` and stays counted at 3 until GitHub proves 22.

### Recommended next unblocked pytest bucket

**`ACTIVE_BUNDLE_ENCODER_LAYOUT`** — 3 tests, `audit/ci-nonblocking-failures-triage`, not branch-blocked. **FIX_NOW** — local strict-bundle fixture fix landed; closure on GitHub pytest-full 25 → 22. After GitHub proof, the next bucket is `CALIBRATION_BYPASS_ALLOWLIST` (2 tests).

---

## Decision

- `ci_triage_gate_pass: false`
- `operator_readiness_gate_pass: false`
- `card_explainability_allowed: false`
- `next_allowed_step: resolve_pytest_full_failures`
- `current_ci_verified_commit: 5c6e967` (run 27875496094, 25 failed — product matrix only)
- `pytest_full_matrix_verified_commit: 5c6e967`
- `expected_after_pending_push: 22` (ACTIVE_BUNDLE local fix; unproven until a future GitHub run)
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
| **CI link** | run **27875496094** @ `5c6e967` — `25 failed, 3762 passed, 7 skipped` = product matrix only (+2 meta-artifact drift CLOSED_WITH_EVIDENCE) |
| **Closure criteria** | pytest-full green OR every product matrix row accepted with operator sign-off |
