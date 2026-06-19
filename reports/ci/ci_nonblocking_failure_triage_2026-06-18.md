> **Classification:** CI Triage | **Scope:** Non-blocking failures — triage and fixes (audit/ci-nonblocking-failures-triage)

# CI non-blocking failure triage (2026-06-18)

**Updated:** 2026-06-19 @ **`6e3157c`** — pytest-full matrix regenerated for current CI run.

## GitHub PR #19 checks (@ `6e3157c`)

| Check | Status |
|-------|--------|
| objective-audit | pass |
| hardening | **CLOSED_WITH_EVIDENCE** |
| schwab-csv-first | **CLOSED_WITH_EVIDENCE** |
| pytest-full | **OPEN_BLOCKING** — `46 failed, 3736 passed` (run **27829108946**) |

**Merge decision basis:** current matrix only (`6e3157c` / 46 failures). Historical 51-failure snapshot @ `9bdc864` is audit trail in JSON `pytest_full_matrix_history` — not used for merge.

**Not EXTERNAL_SECRET_REQUIRED:** Schwab credentials/startup resolved. Remaining failures are test/fixture/contract.

### Fixed @ `6e3157c` (5 tests — no longer in failure set)

- `test_build_client_from_token_fails_closed_without_token_file`
- `test_safe_get_chain_raises_schwab_auth_error_on_invalid_grant`
- `test_safe_get_chain_latched_skips_second_call`
- `test_schedule_analytics_recompute_wires_fail_counter`
- `test_schedule_analytics_recompute_resets_counter_on_success`

---

## Failure matrix (pytest-full) — 46 tests @ `6e3157c`

Machine-readable: `reports/ci/ci_nonblocking_failure_triage_2026-06-18.json` → `pytest_full_failure_matrix`.

### Classification totals

| Classification | Tests |
|----------------|-------|
| PRE_EXISTING_BUT_BLOCKING | 36 |
| INTENTIONAL_CONTRACT_LOCK | 7 |
| PRE_EXISTING_AND_ACCEPTED_WITH_EVIDENCE | 2 |
| INFRASTRUCTURE_FLAKE_WITH_EVIDENCE | 1 |
| FIX_NOW | 0 |
| OBSOLETE_TEST_UPDATE_REQUIRED | 0 |

### Matrix by group

| Failure group | # | Classification | Owner branch | Blocked owner? | Operator sign-off for merge? |
|---------------|---|----------------|--------------|----------------|------------------------------|
| ABLATION_GRID_RUNNABLE_ACCOUNTING | 4 | PRE_EXISTING_BUT_BLOCKING | `fix/ablation-grid-runnable-accounting-ci` | no | no |
| MEGA_INVENTORY_CONTRACT_LOCK | 4 | INTENTIONAL_CONTRACT_LOCK | `fix/mega-inventory-sync` | no | no |
| MISSING_SNAPSHOTS_1M_NORMALIZED_FIXTURE | 11 | PRE_EXISTING_BUT_BLOCKING | `fix/ci-governance-db-fixture` | no | no |
| PRODUCTION_DB_PRED_1C_ABSENT_IN_CI | 2 | PRE_EXISTING_AND_ACCEPTED_WITH_EVIDENCE | `fix/ci-pred-1c-fixture-or-skip` | no | **yes** |
| ACTIVE_BUNDLE_ENCODER_LAYOUT | 3 | PRE_EXISTING_BUT_BLOCKING | `fix/ci-active-bundle-fixture` | no | no |
| CALIBRATION_BYPASS_ALLOWLIST | 2 | PRE_EXISTING_BUT_BLOCKING | `fix/calibration-bypass-allowlist-sync` | no | no |
| ET_AUTHORITY_DAILY_SCOREBOARD | 2 | PRE_EXISTING_BUT_BLOCKING | `fix/daily-scoreboard-et-authority` | no | no |
| ANTI_PATTERN_CAPS_VIOLATIONS | 1 | PRE_EXISTING_BUT_BLOCKING | `fix/anti-pattern-caps-allowlist` | no | no |
| GOVERNANCE_MUTATION_CALIBRATION_LOG_ENV | 1 | INFRASTRUCTURE_FLAKE_WITH_EVIDENCE | `fix/governance-mutation-test-hermetic` | no | no |
| LIVE_BUNDLE_SSE_CACHE | 3 | PRE_EXISTING_BUT_BLOCKING | `fix/live-bundle-test-isolation` | no | no |
| UI_LEVEL_TEST_CHIP_CONTRACT | 2 | INTENTIONAL_CONTRACT_LOCK | `fix/card-price-conflict-explainability` | **yes** — gated branch | **yes** — not PR #19 deferral without sign-off |
| ML_PREDICT_STRICT_VERSION | 1 | PRE_EXISTING_BUT_BLOCKING | `fix/ml-predict-strict-version-contract` | no | no |
| SILENT_EXCEPT_PASS_REMAINING | 1 | PRE_EXISTING_BUT_BLOCKING | `fix/silent-except-pass-sweep` | no | no |
| STACK_WIRE_INTEGRITY | 3 | PRE_EXISTING_BUT_BLOCKING | `fix/stack-wire-ci-contract` | no | no |
| UI_V2_CONFIDENCE_LABELS | 1 | INTENTIONAL_CONTRACT_LOCK | `fix/ui-v2-confidence-readout` | UI lane — readiness gate | **yes** |
| V2_CONFORMAL_TIER_C_PAYLOAD | 2 | PRE_EXISTING_BUT_BLOCKING | `fix/v2-tier-c-ci-fixture` | no | no |
| XGB_CONFLUENCE_SNAPSHOT_PARITY | 1 | PRE_EXISTING_BUT_BLOCKING | `fix/xgb-confluence-snapshot-parity` | no | no |
| AUDIT_CAND_SERVER_CI_OFFLINE | 2 | PRE_EXISTING_BUT_BLOCKING | `fix/audit-cand-server-ci-mocks` | no | no |

---

## hardening

| Field | Value |
|-------|-------|
| **Classification** | `CLOSED_WITH_EVIDENCE` |
| **Closure criteria** | GitHub pass @ `6e3157c` |

## schwab-csv-first

| Field | Value |
|-------|-------|
| **Classification** | `CLOSED_WITH_EVIDENCE` |
| **Closure criteria** | GitHub pass @ `6e3157c` |

## pytest-full

| Field | Value |
|-------|-------|
| **Classification** | `OPEN_BLOCKING` |
| **CI link** | run **27829108946** — `46 failed, 3736 passed` |
| **Closure criteria** | pytest-full green OR every matrix row accepted with operator sign-off |

## Decision

- `ci_triage_gate_pass: false`
- `next_allowed_step: resolve_pytest_full_failures`
- `last_verified_commit: 6e3157c`
- `card_explainability_allowed: false`
- **Do not merge** until pytest-full green or operator accepts every remaining row with evidence.
