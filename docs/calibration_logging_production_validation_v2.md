# Calibration logging — production validation (v2)

**FINAL: PASS**

Pass gates:

- Duplicate rows for the **same calibration decision identity** are **impossible** (enforced by SQLite UNIQUE + `ON CONFLICT DO NOTHING`, not timing assumptions).
- `duplicates` (within-key): **0**
- `missing rows` for distinct decision events: **0** (parity tests)
- Insert **failures** (hard errors): **0** in validation runs

---

## A. Exact files changed

| File | Change |
|------|--------|
| `calibration/schema.py` | Migration `_migrate_calibration_unique_ticker_decision_ts`: legacy dedupe by `MIN(id)` per `(ticker, decision_ts_utc)`, `DROP INDEX IF EXISTS idx_calib_ticker_ts`, `CREATE UNIQUE INDEX uq_calib_ticker_decision_ts_utc ON calibration_decision_log(ticker, decision_ts_utc)`. Removed non-unique `idx_calib_ticker_ts` from initial DDL; unique index is created only after migration (avoids migration failure on duplicate legacy rows). |
| `calibration/writer.py` | `ticker_storage_key(ticker)` for stored `ticker`; `INSERT ... ON CONFLICT(ticker, decision_ts_utc) DO NOTHING`; idempotent success returns `CALIBRATION_INSERT_IDEMPOTENT` (-1) when `conn.total_changes` unchanged after insert; fixed use of `conn.total_changes` as **attribute** (not callable). |
| `signals.py` | Import `CALIBRATION_INSERT_IDEMPOTENT`; no warning when insert is idempotent (-1); debug log for idempotent skip. |
| `tests/test_calibration_logging_production_path.py` | Assertions use `ticker_storage_key("SPY")`; new tests: repeated same `refresh_ts_utc`, concurrent identical key. |

---

## B. Exact uniqueness contract

**One calibration decision row** is uniquely identified by:

**( `ticker_storage_key(ticker)` , `decision_ts_utc` )**

- **`decision_ts_utc`**: authoritative decision instant for that refresh, taken from `SignalInput.refresh_ts_utc` (production: same as server `utc_ts()` passed into `build_market_state`), or `default_decision_ts_utc()` when unset.
- **`ticker`**: normalized with `instrument_identity.ticker_storage_key` so symbol aliases align with `snapshots` / backfill joins.

**Why this is correct:** Each poll/refresh of the signals engine for a given instrument at a given UTC instant should produce **at most one** persisted calibration record. Re-entrancy, retries, or duplicate `compute_signals` calls with the same inputs must not create a second row.

---

## C. Exact enforcement mechanism

1. **SQLite `UNIQUE` index** `uq_calib_ticker_decision_ts_utc` on `(ticker, decision_ts_utc)`.
2. **`INSERT ... ON CONFLICT(ticker, decision_ts_utc) DO NOTHING`** — second insert with the same key **does not add a row** (not an error).
3. **Idempotent return** `CALIBRATION_INSERT_IDEMPOTENT` (-1) when `conn.total_changes` is unchanged after the statement (conflict / no-op).
4. **Legacy DBs:** Before creating the unique index, duplicate groups are reduced to a **single surviving row** (`MIN(id)` per group).

---

## D. Duplicate-insert test results

| Test | Result |
|------|--------|
| `test_repeated_identical_refresh_ts_inserts_at_most_one_row` | **PASS** — two `compute_signals` with identical `refresh_ts_utc`; row count +1 only; exactly one row for `(ticker, decision_ts_utc)`. |

---

## E. Concurrent test results

| Test | Result |
|------|--------|
| `test_concurrent_identical_decision_key_single_row` | **PASS** — 16 threads, same `(SPY, shared_ts)`; exactly **one** new row; `GROUP BY ... HAVING COUNT(*)>1` is empty. |
| `test_rapid_multithreaded_writes_no_skipped_inserts` | **PASS** — 12 threads, distinct timestamps; +12 rows; no duplicate groups. |

---

## F. Parity results (distinct decision events)

| Test | Result |
|------|--------|
| `test_compute_signals_writes_one_calibration_row_per_successful_decision` | **PASS** — N distinct `refresh_ts_utc` → +N rows. |
| `test_no_duplicate_ticker_decision_ts_pairs_for_distinct_refreshes` | **PASS** — no duplicate groups. |
| `test_decision_ts_utc_matches_refresh_ts_utc` | **PASS** — stored `decision_ts_utc` matches injected `refresh_ts_utc`. |

**Legitimate rows not dropped:** Distinct keys each receive an insert (parity). Only **repeated** same key is suppressed — by design (idempotency), not data loss for distinct refreshes.

---

## G. FINAL: PASS

| Metric | Value |
|--------|-------|
| duplicates (same decision key) | **0** (enforced) |
| missing rows (distinct keys) | **0** |
| failures (validation suite) | **0** |

**Validation command:**

```text
cd <repo_root>
python -m pytest tests/test_calibration_logging_production_path.py -v
python -m pytest tests/ -q
```

**Recorded:** `704 passed` (full suite), `6 passed` (calibration logging module).

---

## H. Relation to v1

v1 allowed duplicate rows when the schema only had a **non-unique** index. **v2 closes that path** with a **UNIQUE** constraint plus **idempotent** insert semantics.
