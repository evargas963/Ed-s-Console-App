> **Classification:** CI Triage | **Scope:** Non-blocking failures — triage and fixes (audit/ci-nonblocking-failures-triage)

# CI non-blocking failure triage (2026-06-18)

**Updated:** 2026-06-19 on branch `audit/ci-nonblocking-failures-triage` @ post-PR-#18 merge.

Objective-audit remains the merge gate. This report records root causes, fixes applied, and closure criteria per check.

## hardening

| Field | Value |
|-------|-------|
| **Classification** | `FIXED_NOW` |
| **CI link / log excerpt** | `ruff (correctness rules — blocking)` — `F401 [*] time imported but unused` in `verification/operator_trust_rth_validation.py`; 55 F401 repo-wide |
| **Root cause** | Unused imports across repo (PR #18 stabilization files + pre-existing debt) |
| **Fix applied** | `python -m ruff check . --select F401 --fix`; manual removal of `configure_sqlite_connection` import in `verification/db_sqlite_contention_impact_audit.py` |
| **Files changed** | PR #18 cone + repo-wide F401 cleanup |
| **Tests added** | `python -m ruff check . --select F401,F821,E9` in CI hardening job |
| **Residual risk** | F841/F811 lint debt still ratchet-only |
| **Closure criteria** | `hardening` workflow `ruff (correctness rules — blocking)` step green on `main` |

## pytest-full

| Field | Value |
|-------|-------|
| **Classification** | `FIXED_NOW` |
| **CI link / log excerpt** | `RuntimeError: Missing required environment variable 'SCHWAB_API_KEY'` during Playwright `webServer` uvicorn startup |
| **Root cause** | `config.build_config` requires Schwab env at import; CI job did not provide placeholders |
| **Fix applied** | `.github/workflows/pytest.yml` sets `SCHWAB_API_KEY` / `SCHWAB_APP_SECRET` to `ci-not-live-placeholder` (startup only — not live API credentials) |
| **Files changed** | `.github/workflows/pytest.yml` |
| **Tests added** | Existing Playwright + pytest suite (CI) |
| **Residual risk** | Tests that call live Schwab APIs must remain skipped or mocked |
| **Closure criteria** | `pytest-full` workflow completes Playwright webServer startup and pytest without missing-env failure |

## schwab-csv-first

| Field | Value |
|-------|-------|
| **Classification** | `FIXED_NOW` |
| **CI link / log excerpt** | `market-fact emission (open)` on governance strings in `tools/check_operator_trust_governance.py`; `(VIX)` in switch matrix; `conn.close()` |
| **Root cause** | Diff-emission gate matched homonyms (`open`, `close`, `vix`) and scanned operator-trust governance paths |
| **Fix applied** | `tools/check_schwab_csv_first.py`: `EMISSION_EXCLUDE_PATH_PREFIXES` for operator-trust cone; `AMBIGUOUS_MARKET_TOKENS` require quoted key context |
| **Files changed** | `tools/check_schwab_csv_first.py`, `tests/test_check_schwab_csv_first.py` |
| **Tests added** | `test_diff_emission_skips_operator_trust_governance_paths`, `test_diff_emission_ignores_english_open_close_without_quoted_keys`, `test_diff_emission_still_flags_real_market_fact_emission` |
| **Residual risk** | True market-fact emissions in money-path files still gated |
| **Closure criteria** | `schwab-csv-first` diff-emission gate green on stabilization/CI-triage PRs |

## Decision

**Next allowed branch after CI green on `main`:** operator RTH validation run (harnesses exist); then revisit `operator_readiness_gate_pass`.

**Card explainability:** `card_explainability_allowed: false` — unchanged.

**Closure criteria (ledger):** Each check `FIXED_NOW` verified green on GitHub `main` push, or `PRE_EXISTING_AND_ACCEPTED_WITH_EVIDENCE` with operator narrative.
