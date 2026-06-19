> **Classification:** CI Triage | **Scope:** Non-blocking failures — triage and fixes (audit/ci-nonblocking-failures-triage)

# CI non-blocking failure triage (2026-06-18)

**Updated:** 2026-06-19 on branch `audit/ci-nonblocking-failures-triage` @ `999a4cd` (+ pending schwab emission fix).

**GitHub PR #19 checks (@ `999a4cd`):**

| Check | Status |
|-------|--------|
| objective-audit | pass |
| hardening | **pass** (runs 27824991489, 27824992744) |
| pytest-full | fail — `52 failed, 3729 passed` (mixed pre-existing + CI offline; run 27824991443) |
| schwab-csv-first | mixed — push pass; PR fail on diff-emission false positives (run 27824992738) |

## hardening

| Field | Value |
|-------|-------|
| **Classification** | `CLOSED_WITH_EVIDENCE` |
| **CI link / log excerpt** | GitHub hardening pass @ `999a4cd` (runs 27824991489, 27824992744) |
| **Root cause** | Hardening job installed `requirements.txt` only; `enforce-static` imports `openpyxl` via `build_feature_assignment_matrix_v2.py` |
| **Fix applied** | `.github/workflows/hardening.yml` adds `pip install -r requirements-dev.txt`; F401 cleanup retained |
| **Files changed** | `.github/workflows/hardening.yml`, repo-wide F401 |
| **Tests added** | hardening workflow ruff F401/F821/E9 + enforce-static |
| **Residual risk** | F841/F811 lint debt still ratchet-only |
| **Closure criteria** | `hardening` workflow green on GitHub PR #19 — **met** |

## pytest-full

| Field | Value |
|-------|-------|
| **Classification** | `OPEN_BLOCKING` |
| **CI link / log excerpt** | WebServer starts; `52 failed, 3729 passed` @ `999a4cd` (run 27824991443); CI offline blocks live Schwab (proof: no network) |
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
| **CI link / log excerpt** | PR diff-emission: `lastPrice` test fixtures + `AMBIGUOUS_MARKET_TOKENS` catalog line (run 27824992738) |
| **Root cause** | Diff-emission false positives on checker self-definition and schwab test fixtures |
| **Fix applied** | Exclude `tests/test_check_schwab_csv_first.py`; skip homonym catalog definition lines |
| **Files changed** | `tools/check_schwab_csv_first.py`, `tests/test_check_schwab_csv_first.py` |
| **Tests added** | homonym + operator-trust path exclusion tests |
| **Residual risk** | PR register pin must match meta on merge |
| **Closure criteria** | `schwab-csv-first` green on GitHub PR #19 → `CLOSED_WITH_EVIDENCE` |

## Decision

**Gate:** `ci_triage_gate_pass: false`, `next_allowed_step: await_pr19_ci_results`, `card_explainability_allowed: false`.

**After CI green on PR #19 merge:** `ci_triage_gate_pass: true`, `next_allowed_step: operator_rth_validation`, branch `audit/rth-operator-trust-validation`.

**Do not merge PR #19** until GitHub checks prove fixes or formal external-secret classification.
