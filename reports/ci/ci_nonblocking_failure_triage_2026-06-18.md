> **Classification:** CI Triage | **Scope:** Non-blocking failures — triage and fixes (audit/ci-nonblocking-failures-triage)

# CI non-blocking failure triage (2026-06-18)

**Updated:** 2026-06-19 on branch `audit/ci-nonblocking-failures-triage` — awaiting GitHub PR #19 CI proof.

Objective-audit remains the merge gate. Classifications below are **not** `CLOSED_WITH_EVIDENCE` until GitHub workflows green.

**GitHub PR #19 checks (last observed @ `6c5a782`):**

| Check | Status |
|-------|--------|
| objective-audit | pass |
| hardening | fail — `ModuleNotFoundError: No module named 'openpyxl'` in enforce-static |
| pytest-full | fail — 49 failed (webServer starts; Schwab token/API paths) |
| schwab-csv-first | mixed — push pass; PR fail on register pin step |

## hardening

| Field | Value |
|-------|-------|
| **Classification** | `FIXED_IN_THIS_BRANCH_AWAITING_GITHUB_CI` |
| **CI link / log excerpt** | `enforce-static` → `check_zero_bias_ablation_contract` → `import openpyxl` → `ModuleNotFoundError` (run 27815811385) |
| **Root cause** | Hardening job installed `requirements.txt` only; `enforce-static` imports `openpyxl` via `build_feature_assignment_matrix_v2.py` |
| **Fix applied** | `.github/workflows/hardening.yml` adds `pip install -r requirements-dev.txt`; F401 cleanup retained |
| **Files changed** | `.github/workflows/hardening.yml`, repo-wide F401 |
| **Tests added** | hardening workflow ruff F401/F821/E9 + enforce-static |
| **Residual risk** | F841/F811 lint debt still ratchet-only |
| **Closure criteria** | `hardening` workflow green on GitHub PR #19 → `CLOSED_WITH_EVIDENCE` |

## pytest-full

| Field | Value |
|-------|-------|
| **Classification** | `OPEN_BLOCKING` |
| **CI link / log excerpt** | WebServer starts with placeholders; `49 failed, 3731 passed`; `Schwab client init failed: Token file not found` on `/api/liquidity-snapshot` (run 27815811424) |
| **Root cause** | (1) Missing `SCHWAB_API_KEY` at startup — fixed with placeholders. (2) Tests hitting live Schwab paths without token still fail. |
| **Fix applied** | `pytest.yml`: `ED_CI_OFFLINE=1`, `ci-not-live-placeholder` credentials; `config.is_schwab_ci_offline_mode()` blocks client build + `safe_get_*` API calls |
| **Files changed** | `.github/workflows/pytest.yml`, `config.py`, `schwab_client.py` |
| **Tests added** | `tests/test_schwab_client_import_boundary.py::test_ci_offline_blocks_live_schwab_client_and_api` |
| **Residual risk** | Suite failures unrelated to Schwab startup may remain |
| **Closure criteria** | `pytest-full` green on GitHub PR #19, or `EXTERNAL_SECRET_REQUIRED_WITH_EVIDENCE` with exact logs if truly secret-gated |

## schwab-csv-first

| Field | Value |
|-------|-------|
| **Classification** | `FIXED_IN_THIS_BRANCH_AWAITING_GITHUB_CI` |
| **CI link / log excerpt** | Push event pass; PR event `register_content_sha256 mismatch` after V4 register generation (run 27815811429) |
| **Root cause** | Diff-emission false positives on governance homonyms; PR-only register pin step |
| **Fix applied** | `EMISSION_EXCLUDE_PATH_PREFIXES` + `AMBIGUOUS_MARKET_TOKENS` quoted-key rule |
| **Files changed** | `tools/check_schwab_csv_first.py`, `tests/test_check_schwab_csv_first.py` |
| **Tests added** | homonym + operator-trust path exclusion tests |
| **Residual risk** | PR register pin must match meta on merge |
| **Closure criteria** | `schwab-csv-first` green on GitHub PR #19 → `CLOSED_WITH_EVIDENCE` |

## Decision

**Gate:** `ci_triage_gate_pass: false`, `next_allowed_step: await_pr19_ci_results`, `card_explainability_allowed: false`.

**After CI green on PR #19 merge:** `ci_triage_gate_pass: true`, `next_allowed_step: operator_rth_validation`, branch `audit/rth-operator-trust-validation`.

**Do not merge PR #19** until GitHub checks prove fixes or formal external-secret classification.
