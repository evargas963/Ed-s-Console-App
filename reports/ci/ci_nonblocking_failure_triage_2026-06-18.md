> **Classification:** CI Triage | **Scope:** Non-blocking failures — triage and fixes (audit/ci-nonblocking-failures-triage)

# CI non-blocking failure triage (2026-06-18)

**Updated:** 2026-06-19 @ **`bc2e8a9`** — MEGA inventory sync landed; GitHub pytest-full awaiting observation on push.

## GitHub PR #19 checks (@ `704b4b9` last observed)

| Check | Status |
|-------|--------|
| objective-audit | **CLOSED_WITH_EVIDENCE** — pass [27851943226](https://github.com/evargas963/Ed-s-Console-App/actions/runs/27851943226) |
| hardening | **CLOSED_WITH_EVIDENCE** — pass |
| schwab-csv-first | **CLOSED_WITH_EVIDENCE** — pass |
| pytest-full | **OPEN_BLOCKING** — `29 failed, 3757 passed, 7 skipped` (run **27851943230** @ `704b4b9`) |

**Local expectation @ `bc2e8a9`:** **25 failed** (+4 passed) after `MEGA_INVENTORY_CONTRACT_LOCK` cleared — awaiting GitHub run.

**Merge gate:** `pytest-full` (objective-audit cleared @ `704b4b9`).

**Delta vs `704b4b9`:** 29→**25** failed expected (+4 mega inventory tests).

### Cleared @ `bc2e8a9` (local verification)

| Bucket | Tests | Evidence |
|--------|-------|----------|
| `MEGA_INVENTORY_CONTRACT_LOCK` | 4 | `sync_traceable_inventory_to_ast` + NONE stubs; mega1–mega4 audit **35/35** locally |

### Cleared @ `704b4b9`

| Bucket | Tests | Evidence |
|--------|-------|----------|
| `ABLATION_GRID_RUNNABLE_ACCOUNTING` | 4 | Ablation enriched-row accounting unified; objective-audit + 4 matrix tests green |
| `GOVERNANCE_MUTATION_CALIBRATION_LOG_ENV` | 1 | `test_objective_audit_does_not_mutate_governance_artifacts` green |

### `MISSING_SNAPSHOTS_1M_NORMALIZED_FIXTURE` — **CLOSED_WITH_EVIDENCE** @ `e3ba4a9`

12 tests cleared @ `e3ba4a9` (governance dashboard, live drift, snapshots schema bootstrap).

---

## Failure matrix (pytest-full) — 25 tests expected @ `bc2e8a9`

Machine-readable: `reports/ci/ci_nonblocking_failure_triage_2026-06-18.json` → `pytest_full_failure_matrix`.

### Classification totals (open failures only)

| Classification | Tests |
|----------------|-------|
| PRE_EXISTING_BUT_BLOCKING | 21 |
| INTENTIONAL_CONTRACT_LOCK | 3 |
| PRE_EXISTING_AND_ACCEPTED_WITH_EVIDENCE | 1 |
| CLOSED_WITH_EVIDENCE (cumulative cleared) | 20 |

### Matrix by group (open @ `bc2e8a9` expected)

| Failure group | # | Classification | Owner branch | Blocked owner? | Operator sign-off? |
|---------------|---|----------------|--------------|----------------|-------------------|
| ABLATION_GRID_RUNNABLE_ACCOUNTING | 0 | **CLOSED** @ `704b4b9` | — | — | — |
| GOVERNANCE_MUTATION_CALIBRATION_LOG_ENV | 0 | **CLOSED** @ `704b4b9` | — | — | — |
| MEGA_INVENTORY_CONTRACT_LOCK | 0 | **CLOSED** @ `bc2e8a9` | — | — | — |
| MISSING_SNAPSHOTS_1M_NORMALIZED_FIXTURE | 0 | **CLOSED** @ `e3ba4a9` | — | — | — |
| PRODUCTION_DB_PRED_1C_ABSENT_IN_CI | 1 | PRE_EXISTING_AND_ACCEPTED_WITH_EVIDENCE | `fix/ci-pred-1c-fixture-or-skip` | no | **yes** |
| ACTIVE_BUNDLE_ENCODER_LAYOUT | 3 | PRE_EXISTING_BUT_BLOCKING | `fix/ci-active-bundle-fixture` | no | no |
| CALIBRATION_BYPASS_ALLOWLIST | 2 | PRE_EXISTING_BUT_BLOCKING | `fix/calibration-bypass-allowlist-sync` | no | no |
| ET_AUTHORITY_DAILY_SCOREBOARD | 2 | PRE_EXISTING_BUT_BLOCKING | `fix/daily-scoreboard-et-authority` | no | no |
| ANTI_PATTERN_CAPS_VIOLATIONS | 1 | PRE_EXISTING_BUT_BLOCKING | `fix/anti-pattern-caps-allowlist` | no | no |
| LIVE_BUNDLE_SSE_CACHE | 3 | PRE_EXISTING_BUT_BLOCKING | `fix/live-bundle-test-isolation` | no | no |
| UI_LEVEL_TEST_CHIP_CONTRACT | 2 | INTENTIONAL_CONTRACT_LOCK | `fix/card-price-conflict-explainability` | **yes** | **yes** |
| ML_PREDICT_STRICT_VERSION | 1 | PRE_EXISTING_BUT_BLOCKING | `fix/ml-predict-strict-version-contract` | no | no |
| SILENT_EXCEPT_PASS_REMAINING | 1 | PRE_EXISTING_BUT_BLOCKING | `fix/silent-except-pass-sweep` | no | no |
| STACK_WIRE_INTEGRITY | 3 | PRE_EXISTING_BUT_BLOCKING | `fix/stack-wire-ci-contract` | no | no |
| UI_V2_CONFIDENCE_LABELS | 1 | INTENTIONAL_CONTRACT_LOCK | `fix/ui-v2-confidence-readout` | UI lane | **yes** |
| V2_CONFORMAL_TIER_C_PAYLOAD | 2 | PRE_EXISTING_BUT_BLOCKING | `fix/v2-tier-c-ci-fixture` | no | no |
| XGB_CONFLUENCE_SNAPSHOT_PARITY | 1 | PRE_EXISTING_BUT_BLOCKING | `fix/xgb-confluence-snapshot-parity` | no | no |
| AUDIT_CAND_SERVER_CI_OFFLINE | 2 | PRE_EXISTING_BUT_BLOCKING | `fix/audit-cand-server-ci-mocks` | no | no |

### Recommended next largest unblocked bucket

**`ACTIVE_BUNDLE_ENCODER_LAYOUT`** — 3 tests, `fix/ci-active-bundle-fixture`, not branch-blocked.

---

## Decision

- `ci_triage_gate_pass: false`
- `next_allowed_step: resolve_pytest_full_failures`
- `last_verified_commit: bc2e8a9` (local mega fix); GitHub pytest-full last @ `704b4b9`
- `card_explainability_allowed: false`
- **Do not merge** until pytest-full green or operator accepts every remaining open row with evidence.

---

## hardening

| Field | Value |
|-------|-------|
| **Classification** | `CLOSED_WITH_EVIDENCE` |
| **Closure criteria** | GitHub pass @ `704b4b9` |

## schwab-csv-first

| Field | Value |
|-------|-------|
| **Classification** | `CLOSED_WITH_EVIDENCE` |
| **Closure criteria** | GitHub pass @ `704b4b9` |

## pytest-full

| Field | Value |
|-------|-------|
| **Classification** | `OPEN_BLOCKING` |
| **CI link** | run **27851943230** — `29 failed` @ `704b4b9`; **25 expected** @ `bc2e8a9` (GitHub run not yet observed) |
| **Closure criteria** | pytest-full green OR every matrix row accepted with operator sign-off |
