> **Classification:** CI Triage | **Scope:** Non-blocking failures — triage and fixes (audit/ci-nonblocking-failures-triage)

# CI non-blocking failure triage (2026-06-18)

**Updated:** 2026-06-20 @ **`afb361d`** — GitHub `pytest-full` showed **18 failed, 3769 passed, 7 skipped** (run **27882570666**) = **product matrix only**. `ET_AUTHORITY_DAILY_SCOREBOARD` (2 tests) is **CLOSED_WITH_EVIDENCE** (20 → 18); meta-artifact drift, ACTIVE_BUNDLE, and CALIBRATION_BYPASS remain CLOSED; schwab-csv-first back to PASS.

## GitHub PR #19 checks (@ `afb361d`)

| Check | Status |
|-------|--------|
| objective-audit | **CLOSED_WITH_EVIDENCE** — pass |
| hardening | **CLOSED_WITH_EVIDENCE** — pass |
| schwab-csv-first | **CLOSED_WITH_EVIDENCE** — push [27882569786](https://github.com/evargas963/Ed-s-Console-App/actions/runs/27882569786) + PR [27882570654](https://github.com/evargas963/Ed-s-Console-App/actions/runs/27882570654) @ `afb361d` (first closed @ `741091b`) |
| pytest-full | **OPEN_BLOCKING** — `18 failed, 3769 passed, 7 skipped` (run **27882570666** @ `afb361d`) = **product matrix only** |

**Merge gate:** `pytest-full` (18 open product matrix rows). **Do not merge** PR #19 until pytest-full is green on GitHub OR every open product matrix row carries operator sign-off.

### Closure ladder (proven on GitHub)

| Bucket | Tests | Cleared @ | Run | Delta |
|--------|-------|-----------|-----|-------|
| `PYTEST_GOVERNANCE_META_PIN_DRIFT` | 2 | `5c6e967` | 27875496094 | 27 → 25 |
| `ACTIVE_BUNDLE_ENCODER_LAYOUT` | 3 | `0068226` | 27877046342 | 25 → 22 |
| `CALIBRATION_BYPASS_ALLOWLIST` | 2 | `7bf369c` | 27878597275 | 22 → 20 |
| `ET_AUTHORITY_DAILY_SCOREBOARD` | 2 | `ad96844`+`afb361d` | 27882570666 | 20 → 18 |

> The ET commit (`ad96844`) cleared the ET tests but regressed `schwab-csv-first` (a `calibration/` market-data file changed without a CSV-first declaration); fixed-forward in `afb361d` (declaration added). schwab-csv-first is green again at `afb361d`.

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

## Failure matrix (pytest-full) — 18 product tests (observed @ `afb361d`)

Machine-readable: `reports/ci/ci_nonblocking_failure_triage_2026-06-18.json` → `pytest_full_failure_matrix` (sum of `number_of_tests` = 18 = `pytest_full_product_matrix_failure_count` = current observed).

### In-progress pytest bucket

**`ANTI_PATTERN_CAPS_VIOLATIONS`** — 1 test, `audit/ci-nonblocking-failures-triage`, not branch-blocked. Fix **landed locally**: 15 reviewed non-market-leaf hits across 8 files exempted via **exact file+line+variant** entries in `CAPS_LINE_ALLOWLIST` (no whole-file prefix; money-path-adjacent files line-level only); register CAPS block mirrors. No detection regex / `DEFAULT_VALUE_RE` / runtime change. 9/9 anti-pattern tests pass locally. Expected (projection, unproven until GitHub): 18 → 17.

### Recommended next unblocked pytest bucket (after ANTI_PATTERN GitHub proof)

**`ML_PREDICT_STRICT_VERSION`** (1 test) / **`SILENT_EXCEPT_PASS_REMAINING`** (1 test). **FIX_NOW** candidates per the matrix.

---

## Decision

- `ci_triage_gate_pass: false`
- `operator_readiness_gate_pass: false`
- `card_explainability_allowed: false`
- `next_allowed_step: resolve_pytest_full_failures`
- `current_ci_verified_commit: afb361d` (run 27882570666, 18 failed — product matrix only)
- `pytest_full_matrix_verified_commit: afb361d`
- `expected_after_pending_push: 17` (ANTI_PATTERN_CAPS_VIOLATIONS line-level allowlist landed locally; projection, unproven until GitHub)
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
| **CI link** | PR [27882570654](https://github.com/evargas963/Ed-s-Console-App/actions/runs/27882570654) + push [27882569786](https://github.com/evargas963/Ed-s-Console-App/actions/runs/27882569786) @ `afb361d` (first closed @ `741091b`) |
| **Closure criteria** | `pull_request` + push schwab-csv-first green on PR #19 — met @ `afb361d` (run pair matches `ci_nonblocking_failure_triage_2026-06-18.json` `github_checks_last_observed`) |

## pytest-full

| Field | Value |
|-------|-------|
| **Classification** | `OPEN_BLOCKING` |
| **CI link** | run **27882570666** @ `afb361d` — `18 failed, 3769 passed, 7 skipped` = product matrix only (meta-artifact drift + ACTIVE_BUNDLE + CALIBRATION_BYPASS + ET_AUTHORITY CLOSED_WITH_EVIDENCE) |
| **Closure criteria** | pytest-full green OR every product matrix row accepted with operator sign-off |
