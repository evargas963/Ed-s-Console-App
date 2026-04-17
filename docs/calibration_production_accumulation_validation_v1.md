# Calibration production accumulation validation (v1)

**Purpose:** Prove the full calibration pipeline remains correct across a **non-trivial accumulation window** of **trusted** `calibration_decision_log` rows using the **real** production stack (`compute_signals` → `calibration.writer` → `backfill_outcomes` → validators).

**Date:** 2026-04-11

---

## A. Exact files changed

| File | Role |
|------|------|
| `calibration/run_production_accumulation_validation.py` | **New.** Deterministic harness: isolated DB, `N_ACCUM=48` decision events, seeded `price_bars_1m` + `snapshots`, production logging, backfill ×2, `validate_outcome_join`, `anchor_audit`, `legacy_report`, JSON report. |
| `tests/test_calibration_accumulation_validation.py` | **New.** CI re-proof: runs harness with temp DB paths (`binary_pass` and key counts). |
| `docs/calibration_production_accumulation_validation_v1.md` | This proof document. |

**Generated artifacts (from a successful local run; reproducible via command below):**

- `data/calibration_accumulation_validation.db`
- `data/calibration_accumulation_validation_report.json`

---

## B. Dataset / window used

| Field | Value |
|-------|--------|
| **Mode** | Deterministic **production-path** accumulation (not a simplified insert-only fixture) |
| **Harness** | `python -m calibration.run_production_accumulation_validation` |
| **Decision events** | 48 sequential `compute_signals(..., db=EdDB)` calls with distinct `(ticker_storage_key, decision_ts_utc)` |
| **Tickers** | SPY / QQQ rotated |
| **Time grid** | `base_ts_utc = 1712200000.0`, step `100` seconds |
| **Prerequisites** | For each event: one `price_bars_1m` bar ending before `ts`, one `snapshots` row at exact `ts_utc` with filled outcomes |
| **ML stack** | `run_base_models_once` stubbed as in `tests.test_calibration_logging_production_path` (CI-safe; **same** `compute_signals` / writer path) |
| **Backfill** | `backfill_outcomes.backfill(tol_sec=0.0)` — exact timestamp join only |
| **Resync** | Second backfill pass exercises **re-sync** of rows that already have outcomes (no pending left; verification re-run) |

---

## C. Exact counts tables

Values taken from `data/calibration_accumulation_validation_report.json` after a successful run.

### C.1 Row inventory

| Metric | Value |
|--------|------:|
| `calibration_decision_log` total rows | 48 |
| Trusted rows | 48 |
| Legacy rows | 0 |
| Duplicate `(ticker, decision_ts_utc)` groups | **0** |
| Decision events executed | 48 |
| Missing rows (events − trusted rows) | **0** |

### C.2 Outcome attachment & join

| Metric | After 1st backfill |
|--------|-------------------:|
| Pending trusted rows (`outcome_5c` NULL) before backfill | 48 |
| Rows updated (new attach) | 48 |
| `skipped_ambiguous_duplicate_snapshots` | **0** |
| `skipped_ambiguous_nearest_tie` | **0** |
| `skipped_no_exact_match` (trusted pending) | **0** |
| Rows with outcomes | 48 |
| Rows pending outcomes | 0 |
| `validate_outcome_join` `verification_pass` | 48 |
| `validate_outcome_join` `verification_fail` | **0** |
| Ambiguous duplicate snapshot keys | **0** |
| Trusted rows with non-`exact` join method (unsafe for tol=0 policy) | **0** |

### C.3 Second backfill (resync)

| Metric | Value |
|--------|------:|
| Pending candidates | 0 |
| New attaches (`updated`) | 0 |
| `resynced` (existing outcomes refreshed from snapshot) | 48 |
| `resync_skipped_duplicate_snapshots` | **0** |
| `resync_skipped_no_snapshot` | **0** |

### C.4 Post-resync join verification

| Metric | Value |
|--------|------:|
| `verification_fail` after 2nd backfill | **0** |
| `binary_pass` | **true** |

### C.5 Anchor (BAR_ANCHOR_V1) — trusted calibration

| Metric | Value |
|--------|------:|
| `trusted_rows_total` | 48 |
| `trusted_rows_with_anchor` | 48 |
| `trusted_rows_without_anchor` | **0** |
| `anchor_audit` `binary_pass` (strict: zero unanchored trusted) | **true** |

### C.6 Legacy / quarantine

| Metric | Value |
|--------|------:|
| `legacy_rows` | **0** |
| `legacy_subcategory_sum_equals_legacy_rows` | **true** |

### C.7 Runtime diagnostics

| Observation | Classification |
|-------------|------------------|
| SQLite migration log lines on first `EdDB` open | Expected one-time schema/migration messages |
| `MC_INPUT` / `MC_DEBUG` lines on stdout during `compute_signals` | Monte Carlo diagnostics; **not** validation failures |
| Harness `warnings` array | **empty** |

---

## D. End-to-end consistency checks

| Requirement | Evidence |
|-------------|----------|
| **Logging** one row per successful decision | `trusted_rows == 48` and `decision_events == 48`; unique `(ticker, decision_ts_utc)` |
| **Duplicate prevention** | `duplicate_key_groups == 0` |
| **Join correctness** | `verification_fail == 0`; `ambiguous_exact_ts_duplicate_snapshots == 0`; all joins `exact` for tol=0 |
| **Anchor gating** | `trusted_rows_without_anchor == 0`; phase analyzers exclude unanchored rows by design |
| **Trusted/legacy quarantine** | `legacy_rows == 0`; all rows trusted writer path |
| **Resync stability** | After 2nd backfill, `verification_fail == 0` (no drift vs `snapshots`) |
| **No bypass / leakage regression** | Not re-proven line-by-line here; **authoritative** closures remain `tests/test_calibration_bypass_closure.py`, `tests/test_calibration_legacy_quarantine.py`, and related docs. This harness uses the same production modules. |

---

## E. Mismatches / errors and resolution

| Issue | Resolution |
|-------|------------|
| None | Full gate set in `pass_gates` passed; `binary_pass: true` in report |

---

## F. FINAL: **PASS**

**PASS criteria (all satisfied):**

| Criterion | Status |
|-----------|--------|
| Trusted population non-trivial (≥ 30) | **48** trusted rows |
| Duplicates | **0** |
| Missing rows vs decision events | **0** |
| Unsafe joins (non-exact with tol=0 policy) | **0** |
| Post-resync verification failures | **0** |
| Quarantine + anchor behavior | Correct; **0** legacy, **0** unanchored trusted |
| Remaining issues | **NONE** |

---

## Validation commands used

```text
python -m calibration.run_production_accumulation_validation
```

Expected: exit code **0**, `binary_pass: true` in printed JSON; report written to `data/calibration_accumulation_validation_report.json`.

```text
python -m pytest tests/test_calibration_accumulation_validation.py -q --tb=short
```

Expected: **1 passed** (re-runs harness on a temporary database).
