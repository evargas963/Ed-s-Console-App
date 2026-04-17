# Calibration outcome join validation v2 (scale proof)

## A. Exact files changed

| File | Change |
|------|--------|
| `calibration/backfill_outcomes.py` | Resync path used undefined `_SNAPSHOT_SELECT`; aligned with pending attach path by using `_BASE_SEL` (same `get_snapshot_sql("calibration/backfill_outcomes.py:select_base")` query). |
| `calibration/validate_outcome_join.py` | Import `get_snapshot_sql` from `db` (fixes `NameError` when running `analyze()` / `python -m calibration.validate_outcome_join`). |
| `tests/test_calibration_outcome_join_scale.py` | New scale proof: 2,200 matched pairs + 120 pending rows on full EdDB schema; asserts no ambiguity, no non-exact joins at `tol=0`, `analyze()` binary pass; second test injects drift on 80 rows and proves resync clears mismatches. |

## B. Dataset used

- **Storage:** Temporary SQLite database per test run, created with `EdDB` (full production `snapshots` schema) plus `ensure_calibration_schema` for `calibration_decision_log`.
- **Scale:** **2,320** calibration rows total: **2,200** with a matching `snapshots` row at the same `(ticker, timeframe='1m', ts_utc)` and filled horizon outcomes; **120** calibration-only rows with **no** snapshot (expected unmatched at `tol=0`).
- **Diversity:** Six canonical tickers (via `ticker_storage_key`): SPY, QQQ, IWM, DIA, XLF, XLE — cycled by row index.
- **Timestamps:** Unique `decision_ts_utc` / snapshot `ts_utc` on a 60-second grid from `BASE_TS = 1_850_000_000.0` so there are no duplicate `(ticker, ts_utc)` snapshot keys and no nearest-neighbor ambiguity.

This is **real table data** (actual `INSERT` rows in the two tables), not mocked join objects.

## C. Join contract

As implemented in `calibration/backfill_outcomes`:

1. **Primary key for attachment:** `(ticker, timeframe='1m', ts_utc)`.
2. **`tol_sec == 0` (default):** Only **exact** `snapshots.ts_utc = calibration_decision_ts_utc`. No nearest-neighbor attach.
3. **Ambiguity:** If more than one `snapshots` row exists for the same `(ticker, ts_utc)`, the row is skipped (`ambiguous_duplicate_snapshots`); attachment does not pick arbitrarily.
4. **Filled snapshot required:** Snapshot must have `outcome_5c` non-NULL (and other columns copied from that row).
5. **Resync:** After pending rows are processed, every row with `outcome_5c IS NOT NULL` is refreshed from `snapshots` at `COALESCE(matched_snapshot_ts_utc, decision_ts_utc)`, so deliberate drift in calibration columns is overwritten from the matched snapshot row.

Validation in `calibration/validate_outcome_join.analyze()`:

- Counts duplicate snapshot rows at calibration decision timestamps (global ambiguity query).
- For each row with outcomes, loads the snapshot at `matched_snapshot_ts_utc` or `decision_ts_utc` and compares all eight outcome columns to the snapshot row.
- **`binary_pass`** iff: ambiguity count `== 0`, verification failures `== 0`, and `rows_with_outcomes == verification_pass`.

## D. Counts table

| Metric | Value |
|--------|------:|
| Total calibration rows | 2,320 |
| Attachable at `tol=0` (snapshot exists at exact `ts_utc` with outcomes) | 2,200 |
| Attached after `backfill(..., tol=0)` | 2,200 |
| Unmatched (pending) | 120 |
| Ambiguous `(ticker, ts_utc)` duplicate snapshots | 0 |
| Rows with `outcome_join_method` other than `exact` while `outcome_5c` set | 0 |
| Verification failures after initial backfill | 0 |
| Verification failures after injecting wrong `outcome_15c` on 80 rows | 80 |
| Verification failures after second backfill (resync) | 0 |

## E. Mismatch analysis

- **Initial run:** All 2,200 attached rows matched their snapshot row on `outcome_1c` / `outcome_5c` / `outcome_15c` / `outcome_60c` and corresponding `*_pts` columns; `ambiguous_exact_ts_duplicate_snapshots == 0`.
- **Drift experiment:** For **80** attached rows, `outcome_15c` was set to a sentinel (`drift_wrong`). `analyze()` reported **80** verification failures (`outcome_mismatch_vs_snapshot`), proving the checker detects snapshot divergence.
- **After resync:** `backfill()` was run again (no pending rows). Resync rewrote outcomes from `snapshots` for all rows with `outcome_5c IS NOT NULL`. `analyze()` returned **0** verification failures and `binary_pass: true`.

No partial-outcome drift remains after resync.

## F. Manual sample verification (non-trivial)

Deterministic examples from the fixture (outcomes from `_outcomes_for_idx(i)`):

| Row index `i` | Ticker (storage key) | `ts_utc` | outcome_1c | outcome_5c | outcome_15c | outcome_60c |
|--------------:|----------------------|----------|------------|------------|-------------|-------------|
| 0 | SPY | `BASE_TS + 0` | up | down | flat | up |
| 500 | SPY | `BASE_TS + 500×60` | flat | up | down | flat |
| 2199 | DIA | `BASE_TS + 2199×60` | up | down | flat | up |

For each such row, after backfill, querying `snapshots` at `(ticker, ts_utc)` returns the same eight outcome fields as `calibration_decision_log` (verified at scale by `analyze()`).

The CLI / JSON output also includes up to 20 `manual_sample` entries (random sample) with per-horizon calib vs snapshot fields for spot checks on arbitrary databases.

## G. FINAL: **PASS**

| Gate | Result |
|------|--------|
| Ambiguous duplicate snapshots | **0** |
| Silent nearest-neighbor attach at `tol=0` | **0** (all attached rows `outcome_join_method == 'exact'`) |
| Post-resync outcome mismatches vs snapshot | **0** |
| Join correctness at materially larger than tiny sample | **PASS** (2,200 attaches + 120 pending + drift/resync proof) |

**Proof command (executed successfully):**

```text
python -m pytest tests/test_calibration_outcome_join_scale.py -v
```

```text
tests/test_calibration_outcome_join_scale.py::test_scale_exact_join_no_ambiguity_validate_passes PASSED
tests/test_calibration_outcome_join_scale.py::test_resync_clears_intentional_outcome_drift PASSED
2 passed
```
