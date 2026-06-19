> **Classification:** CI Triage | **Scope:** Non-blocking failures — triage and fixes (audit/ci-nonblocking-failures-triage)

# CI non-blocking failure triage (2026-06-18)

**Updated:** 2026-06-19 @ **`89837cd`** — GitHub CI observed (objective-audit fail run **27847001817**); ABLATION fix landed locally (uncommitted).

## GitHub PR #19 checks (@ `89837cd`)

| Check | Status |
|-------|--------|
| objective-audit | **FIXED_IN_THIS_BRANCH_AWAITING_GITHUB_CI** — fail [27847001817](https://github.com/evargas963/Ed-s-Console-App/actions/runs/27847001817) (`ABLATION_GRID_RUNNABLE_ACCOUNTING`; fix uncommitted on disk) |
| hardening | **CLOSED_WITH_EVIDENCE** — pass |
| schwab-csv-first | **CLOSED_WITH_EVIDENCE** — pass |
| pytest-full | **OPEN_BLOCKING** — `34 failed, 3750 passed, 7 skipped` @ `e3ba4a9` (run **27845075770**); pending re-run after push |

**Merge decision basis:** current matrix (`e3ba4a9` / **34** failures until GitHub re-run). Expected **30** failures after ABLATION fix clears 4 tests.

### `ABLATION_GRID_RUNNABLE_ACCOUNTING` — fix landed (awaiting GitHub)

**GitHub failure excerpt (objective-audit @ `89837cd`, run 27847001817):**

```text
enforce_all_rules --objective-audit: FAIL (audit_status=DEFECTS)
static_errors: [
  "ablation grid: whole_stack_fusion_cell_target must equal runnable_target (enriched row sample required for fidelity-first runnable count)"
]
```

| Field | Value |
|-------|-------|
| Checker | `check_ablation_seven_model_four_horizon_grid()` in `tools/check_fix_everything_we_touch.py` |
| Manifest | `governance/artifacts/feature_ablation_manifest_leaf.json` |
| CI DB | `data/ed_console.db` (`ensure_console_db_training_schema` — schema only, zero snapshot rows) |
| Enriched sample | `build_ablation_enriched_row_sample()` → `[]` on CI |
| At fail | `whole_stack_fusion_cell_target=0`, `runnable_target=2044` |
| Root cause | `enriched or None` collapsed `[]` to `None` in `ablation_static_lock_index` — specs used candidate knockout path |
| Fix | `enriched_rows_for_spec_build()` preserves `[]`; grid check always requires fusion==runnable |
| Local verify | `enforce_all_rules --objective-audit` PASS; 6 ablation accounting tests PASS |

**Merge decision basis:** current matrix (`e3ba4a9` / **34** failures). Historical runs in JSON `pytest_full_matrix_history` only.

**Delta vs `2007768`:** 46→**34** failed (+13 passed, +1 skipped). **12 tests cleared** @ `e3ba4a9`.

### `MISSING_SNAPSHOTS_1M_NORMALIZED_FIXTURE` — **CLOSED_WITH_EVIDENCE** (snapshots scope)

| File | GitHub @ `e3ba4a9` |
|------|---------------------|
| `test_governance_dashboard.py` | **green** (3 tests) |
| `test_governance_ui_dashboard.py` | **green** (`test_api_governance_panel_emit_notifications_query`) |
| `test_live_drift_monitoring.py` | **green** (7 tests) |
| `test_governance_mutation_detection.py::test_objective_audit_does_not_mutate_governance_artifacts` | **still red** — reclassified to `GOVERNANCE_MUTATION_CALIBRATION_LOG_ENV` (ED_CALIBRATION_LOG subprocess env, not missing table) |

**Not EXTERNAL_SECRET_REQUIRED:** Schwab credentials resolved. Remaining failures are test/fixture/contract.

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
| PRE_EXISTING_BUT_BLOCKING | 25 |
| INTENTIONAL_CONTRACT_LOCK | 7 |
| PRE_EXISTING_AND_ACCEPTED_WITH_EVIDENCE | 1 |
| INFRASTRUCTURE_FLAKE_WITH_EVIDENCE | 1 |
| CLOSED_WITH_EVIDENCE | 11 |
| FIX_NOW | 0 |
| OBSOLETE_TEST_UPDATE_REQUIRED | 0 |

### Matrix by group

| Failure group | # | Classification | Owner branch | Blocked owner? | Operator sign-off for merge? |
|---------------|---|----------------|--------------|----------------|------------------------------|
| ABLATION_GRID_RUNNABLE_ACCOUNTING | 4 | **FIXED_IN_THIS_BRANCH_AWAITING_GITHUB_CI** | `audit/ci-nonblocking-failures-triage` | no | no |
| MEGA_INVENTORY_CONTRACT_LOCK | 4 | INTENTIONAL_CONTRACT_LOCK | `fix/mega-inventory-sync` | no | no |
| MISSING_SNAPSHOTS_1M_NORMALIZED_FIXTURE | 0 | **CLOSED_WITH_EVIDENCE** @ `e3ba4a9` | `fix/ci-governance-db-fixture` | no | no |
| PRODUCTION_DB_PRED_1C_ABSENT_IN_CI | 1 | PRE_EXISTING_AND_ACCEPTED_WITH_EVIDENCE | `fix/ci-pred-1c-fixture-or-skip` | no | **yes** |
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
- `last_verified_commit: e3ba4a9`
- `card_explainability_allowed: false`
- **Do not merge** until pytest-full green or operator accepts every remaining row with evidence.
