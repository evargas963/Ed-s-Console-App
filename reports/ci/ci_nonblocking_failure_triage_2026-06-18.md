> **Classification:** CI Triage | **Scope:** Non-blocking failures — triage and fixes (audit/ci-nonblocking-failures-triage)

# CI non-blocking failure triage (2026-06-18)

**Updated:** 2026-06-20 @ **`d55dd5d`** — GitHub `pytest-full` showed **11 failed, 3776 passed, 7 skipped** (run **27890689248**) = **product matrix only**. `LIVE_BUNDLE_SSE_CACHE` (3 tests) is **CLOSED_WITH_EVIDENCE** (14 → 11); six prior buckets remain CLOSED; schwab-csv-first PASS.

## GitHub PR #19 checks (@ `d55dd5d`)

| Check | Status |
|-------|--------|
| objective-audit | **CLOSED_WITH_EVIDENCE** — pass (run 27890689276) |
| hardening | **CLOSED_WITH_EVIDENCE** — pass |
| schwab-csv-first | **CLOSED_WITH_EVIDENCE** — pass (run 27890689256 @ `d55dd5d`; first closed @ `741091b`) |
| pytest-full | **OPEN_BLOCKING** — `11 failed, 3776 passed, 7 skipped` (run **27890689248** @ `d55dd5d`) = **product matrix only** |

**Merge gate:** `pytest-full` (11 open product matrix rows). **Do not merge** PR #19 until pytest-full is green on GitHub OR every open product matrix row carries operator sign-off.

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

### Remaining open product matrix buckets (11 tests, largest first)

| Bucket | Tests | Status / note |
|--------|-------|---------------|
| `AUDIT_CAND_SERVER_CI_OFFLINE` | **2** | **in progress** (test-only fix landed locally, pending GitHub proof) — debug-endpoint env enable + nested-quote mock repoint |
| `V2_CONFORMAL_TIER_C_PAYLOAD` | **2** | open, not blocked — Tier C / conformal attachment markers absent in CI |
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

## Failure matrix (pytest-full) — 11 product tests (observed @ `d55dd5d`)

Machine-readable: `reports/ci/ci_nonblocking_failure_triage_2026-06-18.json` → `pytest_full_failure_matrix` (sum of `number_of_tests` = 11 = `pytest_full_product_matrix_failure_count` = current observed).

### In-progress pytest bucket

**`AUDIT_CAND_SERVER_CI_OFFLINE`** — 2 tests, fix **landed locally** (test-only, no production change): `test_debug_prediction` now enables the R-011 fail-closed debug gate via `monkeypatch.setenv("ED_ALLOW_DEBUG_ENDPOINTS","1")` (test-only; production gate unchanged); `test_spread_semantic` uses one shared patch context (`get_client` + `_safe_get_quote_with_retry`) with a **nested** Schwab quote-envelope mock (`_parse_quote_node_session_fields` needs `node["quote"][...]`), dropping the stale `_build_rest_fast_quote_payload` mock. No real Schwab/OAuth. 22/22 `audit_cand` tests pass locally. Projected (unproven until GitHub): 11 → 9.

### Recommended next unblocked pytest bucket (after AUDIT_CAND GitHub proof)

**`V2_CONFORMAL_TIER_C_PAYLOAD`** (2). **FIX_NOW** — Tier C / conformal attachment markers absent in CI server response path.

---

## Decision

- `ci_triage_gate_pass: false`
- `operator_readiness_gate_pass: false`
- `card_explainability_allowed: false`
- `next_allowed_step: resolve_pytest_full_failures`
- `current_ci_verified_commit: d55dd5d` (run 27890689248, 11 failed — product matrix only)
- `pytest_full_matrix_verified_commit: d55dd5d`
- `expected_after_pending_push: 9` (AUDIT_CAND_SERVER_CI_OFFLINE test-only fix landed locally; projection, unproven until GitHub)
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
| **CI link** | pass run [27890689256](https://github.com/evargas963/Ed-s-Console-App/actions/runs/27890689256) @ `d55dd5d` (first closed @ `741091b`) |
| **Closure criteria** | schwab-csv-first green on PR #19 — met (run matches `ci_nonblocking_failure_triage_2026-06-18.json` `github_checks_last_observed`) |

## pytest-full

| Field | Value |
|-------|-------|
| **Classification** | `OPEN_BLOCKING` |
| **CI link** | run **27890689248** @ `d55dd5d` — `11 failed, 3776 passed, 7 skipped` = product matrix only (7 buckets CLOSED_WITH_EVIDENCE to date) |
| **Closure criteria** | pytest-full green OR every product matrix row accepted with operator sign-off |
