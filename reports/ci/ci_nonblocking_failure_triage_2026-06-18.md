> **Classification:** CI Triage | **Scope:** Non-blocking failures — triage and fixes (audit/ci-nonblocking-failures-triage)

# CI non-blocking failure triage (2026-06-18)

**Updated:** 2026-06-19 @ `9bdc864` — pytest-full failure matrix added.

## GitHub PR #19 checks (@ `9bdc864`)

| Check | Status |
|-------|--------|
| objective-audit | pass |
| hardening | **CLOSED_WITH_EVIDENCE** — pass |
| schwab-csv-first | **CLOSED_WITH_EVIDENCE** — pass |
| pytest-full | **OPEN_BLOCKING** — `51 failed, 3731 passed` (run 27827558746) |

**Not EXTERNAL_SECRET_REQUIRED:** Schwab startup/placeholder issue is resolved. Remaining failures are categorized below.

---

## pytest-full failure matrix (51 tests)

Machine-readable copy: `reports/ci/ci_nonblocking_failure_triage_2026-06-18.json` → `pytest_full_failure_matrix`.

### FIX_NOW (6 tests — fixes in this branch)

| Failure group | # | Representative tests | Root cause | Closure criteria |
|---------------|---|----------------------|------------|------------------|
| PR19_CI_SCHWAB_OFFLINE_CREDENTIAL_BLOCK | 3 | `test_build_client_from_token_fails_closed_without_token_file`, `test_safe_get_chain_*` | Global offline block ignored explicit non-placeholder creds | All 3 pass with `ED_CI_OFFLINE=1` |
| PR19_ANALYTICS_EXECUTOR_NOT_STARTED | 2 | `test_schedule_analytics_recompute_*` | `_analytics_executor` None without lifespan | `_startup_analytics_executor()` in test |
| PR18_SILENT_EXCEPT_TICKER_SWITCH | 1 | `test_no_silent_exception_pass_in_production_tree` (partial) | `ticker_switch_diagnostics.py` bare `except: pass` | Removed from silent-except hits |

### Triage-owned groups (45 tests)

| Failure group | # | Classification | Owner branch | Closure criteria |
|---------------|---|----------------|--------------|------------------|
| ABLATION_GRID_RUNNABLE_ACCOUNTING | 4 | PRE_EXISTING_BUT_BLOCKING | `fix/ablation-grid-runnable-accounting-ci` | runnable_target == whole_stack_fusion_cell_target in CI |
| MEGA_INVENTORY_CONTRACT_LOCK | 4 | INTENTIONAL_CONTRACT_LOCK | `fix/mega-inventory-sync` | mega1–4 inventory tests pass |
| MISSING_SNAPSHOTS_1M_NORMALIZED_FIXTURE | 11 | PRE_EXISTING_BUT_BLOCKING | `fix/ci-governance-db-fixture` | `snapshots_1m_normalized` schema fixture |
| PRODUCTION_DB_PRED_1C_ABSENT_IN_CI | 2 | PRE_EXISTING_AND_ACCEPTED_WITH_EVIDENCE | `fix/ci-pred-1c-fixture-or-skip` | Hermetic DB or explicit skip without prod DB |
| ACTIVE_BUNDLE_ENCODER_LAYOUT | 3 | PRE_EXISTING_BUT_BLOCKING | `fix/ci-active-bundle-fixture` | Minimal strict bundle in CI or mock paths |
| CALIBRATION_BYPASS_ALLOWLIST | 2 | PRE_EXISTING_BUT_BLOCKING | `fix/calibration-bypass-allowlist-sync` | New test modules on allowlist |
| ET_AUTHORITY_DAILY_SCOREBOARD | 2 | PRE_EXISTING_BUT_BLOCKING | `fix/daily-scoreboard-et-authority` | ZoneInfo from `time_et` only |
| ANTI_PATTERN_CAPS_VIOLATIONS | 1 | PRE_EXISTING_BUT_BLOCKING | `fix/anti-pattern-caps-allowlist` | CAPS allowlist or code fix |
| GOVERNANCE_MUTATION_CALIBRATION_LOG_ENV | 1 | INFRASTRUCTURE_FLAKE_WITH_EVIDENCE | `fix/governance-mutation-test-hermetic` | `ED_CALIBRATION_LOG` isolated in test |
| LIVE_BUNDLE_SSE_CACHE | 3 | PRE_EXISTING_BUT_BLOCKING | `fix/live-bundle-test-isolation` | Hermetic SSE/subscriber state |
| UI_LEVEL_TEST_CHIP_CONTRACT | 2 | INTENTIONAL_CONTRACT_LOCK | `fix/card-price-conflict-explainability` | `#dr-level-test-chip` in UI |
| ML_PREDICT_STRICT_VERSION | 1 | PRE_EXISTING_BUT_BLOCKING | `fix/ml-predict-strict-version-contract` | Version string contract aligned |
| SILENT_EXCEPT_PASS_REMAINING | 1 | PRE_EXISTING_BUT_BLOCKING | `fix/silent-except-pass-sweep` | Baseline 0 (2 hits remain after ticker_switch fix) |
| STACK_WIRE_INTEGRITY | 3 | PRE_EXISTING_BUT_BLOCKING | `fix/stack-wire-ci-contract` | decision_generation_id / build_ts present |
| UI_V2_CONFIDENCE_LABELS | 1 | INTENTIONAL_CONTRACT_LOCK | `fix/ui-v2-confidence-readout` | `v2-confidence` slot in index.html |
| V2_CONFORMAL_TIER_C_PAYLOAD | 2 | PRE_EXISTING_BUT_BLOCKING | `fix/v2-tier-c-ci-fixture` | Tier C attachment markers in response |
| XGB_CONFLUENCE_SNAPSHOT_PARITY | 1 | PRE_EXISTING_BUT_BLOCKING | `fix/xgb-confluence-snapshot-parity` | cf_* dict parity |
| AUDIT_CAND_SERVER_CI_OFFLINE | 2 | PRE_EXISTING_BUT_BLOCKING | `fix/audit-cand-server-ci-mocks` | Mock quote layer in CI |

---

## hardening

| Field | Value |
|-------|-------|
| **Classification** | `CLOSED_WITH_EVIDENCE` |
| **Closure criteria** | GitHub pass @ `9bdc864` (runs 27827560146, 27827558762) |

## schwab-csv-first

| Field | Value |
|-------|-------|
| **Classification** | `CLOSED_WITH_EVIDENCE` |
| **Closure criteria** | GitHub pass @ `9bdc864` (runs 27827560058, 27827558742) |

## pytest-full

| Field | Value |
|-------|-------|
| **Classification** | `OPEN_BLOCKING` |
| **CI link** | run 27827558746 — `51 failed, 3731 passed` |
| **Fix applied** | Credential-scoped `schwab_live_blocked_for()`; analytics executor startup; ticker_switch logging |
| **Closure criteria** | pytest-full green OR all 45 triage-owned matrix rows accepted with owner branch + evidence |

## Decision

- `ci_triage_gate_pass: false`
- `next_allowed_step: resolve_pytest_full_failures`
- `card_explainability_allowed: false`
- **Do not merge** until pytest-full green or operator accepts remaining triage-owned matrix rows.
