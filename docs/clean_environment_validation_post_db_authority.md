# Clean environment validation (post DB authority enforcement)

## 1. Executive result

**FINAL RESULT: FAIL**

The DB authority layer behaves correctly under a clean process environment (`ED_CONSOLE_DB` and `ED_CONSOLE_ALLOW_NONCANONICAL_DB` unset before interpreter start): **default resolution matches canonical**, **non-canonical targets are refused** without `--allow-noncanonical-db`, and **representative smoke commands** (canonical enforcement, ontology JSON) succeed.

**However**, the full test suite **`pytest -q` does not pass** (13 failures). Under the strict criterion (“all tests and smoke scripts pass”), this run is **FAIL** until those tests are green or explicitly exempted by project policy.

---

## 2. Environment setup details

| Step | Action |
|------|--------|
| Bytecode cache | Removed `__pycache__` trees and `*.pyc` under the repo (best-effort). |
| Env vars | For pytest and verification snippets, **`ED_CONSOLE_DB`** and **`ED_CONSOLE_ALLOW_NONCANONICAL_DB`** were **unset** in the child process before `import db` / pytest. |
| Note on pytest | `tests/conftest.py` uses `os.environ.setdefault("ED_CONSOLE_ALLOW_NONCANONICAL_DB", "1")` so tests using **temporary** DBs remain valid; this is intentional and runs **after** process start. |

**Default DB check (env unset):**

```text
DB_PATH == canonical_console_db_path() → True
```

---

## 3. Pytest results summary

| Metric | Value |
|--------|------:|
| **Total outcomes** | 722 (709 + 13) |
| **Passed** | 709 |
| **Failed** | 13 |
| **Skipped** | 0 |
| **Warnings** | 1 (websockets deprecation) |
| **Duration** | ~160–170 s |

Command pattern: run `python -c` that `pop`s `ED_CONSOLE_DB` / `ED_CONSOLE_ALLOW_NONCANONICAL_DB`, then `subprocess` → `pytest -q`.

---

## 4. Failure classification table

| Test | Cause class | Notes |
|------|----------------|-------|
| `test_calibration_bypass_closure::test_no_unauthorized_python_references_to_calibration_decision_log` | **Legacy governance** | Offender: `tools/_phase4_prod_probe.py` references `calibration_decision_log` (not introduced by DB path resolver). |
| `test_calibration_bypass_closure::test_update_calibration_decision_log_only_backfill_and_tests` | **Legacy governance** | `UPDATE calibration_decision_log` in `calibration/backfill_signal_layer_v1_bundle.py` (signal-layer work; not DB resolver). |
| `test_ml_predict_run_base_models_once_default_unchanged` | **ML stack / governance** | Expects `parallel_runtime=True` in `run_base_models_once` source; current implementation differs. |
| `test_ml_predict_default_parallel_runtime_unchanged` | **Same** | Same. |
| `test_manual_governance::test_run_base_models_once_still_parallel_default` | **Same** | Same. |
| `test_parallel_stack_runtime` (4 tests) | **Same** | Parallel stack / inference snapshot contract. |
| `test_scheduler_arch_competition_integration::test_run_base_models_once_unchanged_parallel` | **Same** | Same. |
| `test_xgb_inference_snapshot_v1_input::test_run_base_models_once_requires_inference_snapshot_v1` | **Same** | Same. |
| `test_playwright_must_run::test_playwright_marker_newer_than_e2e_sources` | **E2E staleness** | `last_run_utc` older than source mtime; **not** DB authority. |
| `test_signal_engineering::test_signal_engineering_runs` | **Data-dependent drift** | Asserts fixed `pct_canonical_effective["long"] == 120`; DB contents differ. |
| `test_verification_harness::test_no_valid_primary_sets_wait_reason` | **Harness / assertion drift** | Expected `WAIT` vs `LONG`. |

**DB authority enforcement regression:** **None identified** in these failures (no failures tied to `DB_PATH` / `DEFAULT_DB` / CLI `--db` / `--allow-noncanonical-db`).

---

## 5. Smoke test results

| Script / command | Env | Result |
|------------------|-----|--------|
| `from db import DB_PATH` vs `canonical_console_db_path()` | Unset | **Match** |
| `python -m calibration.canonical_enforcement` | Unset | **`binary_pass: true`** |
| `python -m calibration.canonical_enforcement --db data/calibration_accumulation_validation.db` (no flag) | Unset | **Exit 2**, stderr: refusing non-canonical |
| `python tools/ontology_mismatch_evidence.py` | Unset | **Exit 0**, JSON; `db_path` = canonical `ed_console.db` |
| `python smoke_predict_active.py --tickers ZZZZ_NO_SUCH_TICKER` | Unset | **Exit 1** (“No tickers found…”) — **no crash**; models/active empty or no match |
| `python ml_train.py --help` | Unset | Shows `--db` and `--allow-noncanonical-db` |

---

## 6. DB resolution verification

| Check | Outcome |
|-------|---------|
| Default DB with env unset | Resolves to **`data/ed_console.db`** (resolved path) |
| Non-canonical harness DB without opt-in | **Blocked** (exit 2) |
| Ontology script | Uses default `--db` → canonical path in JSON |
| New shadow `ed_console` files | **Not** created by smoke commands (ontology read-only; enforcement read-only) |

---

## 7. Exact files changed (if fixes applied)

**None** for this validation pass. The deliverable is measurement and documentation only.

---

## 8. Remaining issues

1. **Full `pytest -q` is not green** (13 failures). Addressing them requires either fixing code to satisfy governance contracts, updating tests where contracts changed, or refreshing E2E/stale markers — **outside** narrow DB-path remediation unless scoped to DB CLI.
2. **`smoke_predict_active.py`** did not execute a full inference loop (no matching tickers under `models/active` in this environment); exit was **non-zero** for “no tickers,” not a DB error.

---

## 9. FINAL RESULT

| Field | Value |
|-------|--------|
| **FINAL RESULT** | **FAIL** (strict: full pytest not passing) |
| **DB authority behavior in clean env** | **PASS** (resolution + guards + ontology smoke) |
