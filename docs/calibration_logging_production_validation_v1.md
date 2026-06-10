> **Classification:** Historical Record | **Scope:** Completed analysis or validation `docs/calibration_logging_production_validation_v1.md`.

# Calibration logging — production-path validation (v1)

**FINAL: PASS**

Pass criteria for this document:

- duplicates = 0 (under distinct `decision_ts_utc` per refresh)
- missing rows = 0 (successful `compute_signals` completions vs calibration inserts)
- unlogged failures = 0 (warnings emitted when logging enabled and insert does not return a row, or on exception)

---

## A. Execution path trace (real runtime)

**Single authoritative path for a live UI / poll refresh**

1. **`server.py`** — `_fetch_state` (and related fetch paths) calls `build_market_state(..., db=_ed_db, refresh_ts_utc=_refresh_ts_utc, ...)` where `_refresh_ts_utc = utc_ts()` (see `server.py` ~3244–3298).
2. **`market_state.py`** — `build_market_state` constructs `SignalInput(..., refresh_ts_utc=refresh_ts_utc, ...)` and calls **`compute_signals(sig_inp, db=db, pred_override=...)`** (~1185).
3. **`signals.py`** — `compute_signals` → `_compute_signals_impl` runs the full stack (vol/regime → `_run_model_stack` → fusion → `compute_prediction` → `compute_call` → multi-horizon → `_log_decision_bundle`).
4. **Calibration persistence** — Immediately after `_log_decision_bundle`, **`_maybe_append_calibration_log(...)`** runs (~728–743). It is **not** on a branch that skips when fusion succeeds; it runs for every **successful** completion of `_compute_signals_impl` through that point.
5. **`calibration/writer.py`** — `append_calibration_decision` performs `INSERT INTO calibration_decision_log` with retries on SQLite `locked`/`busy` (up to 12 attempts, `timeout=60.0`).

**Alternate path / bypass**

- If `compute_signals` **raises** before `_maybe_append_calibration_log` (e.g. fail-closed ML/input error), **no calibration row** is written — matching “no decision event completed.”
- If `ED_CALIBRATION_LOG` is not `1`/`true`/`yes`/`on`, `_maybe_append_calibration_log` returns immediately — the documented env-gate contract (logging off).

**Exception: `build_market_state` failure**

- If `compute_signals` is never called (exception in `build_market_state`), no calibration row — consistent with no signal output.

---

## B. Event count vs row count (parity proof)

**Definition:** One **decision event** = one successful completion of `_compute_signals_impl` that reaches `_maybe_append_calibration_log` with `ED_CALIBRATION_LOG` enabled.

**Instrumented proof:** `tests/test_calibration_logging_production_path.py::test_compute_signals_writes_one_calibration_row_per_successful_decision`

- Uses a **temporary SQLite file** and `monkeypatch.setattr(db, "DB_PATH", ...)` so `calibration.writer` writes to that file.
- Sets `ED_CALIBRATION_LOG=1`.
- Invokes **`compute_signals`** `N` times with distinct `refresh_ts_utc`.
- Asserts `COUNT(calibration_decision_log)` increases by exactly `N`.

**Controlled harness (optional, full ML stack):** `python -m calibration.validate_logging_e2e` — compares row delta to `--calls` when the environment can load the full parallel stack without raising (depends on local DB history / models). The **pytest** proof above is CI-stable and uses the **same** `compute_signals` entrypoint; only `ml_predict.run_unified_stack_ml_once` is stubbed for determinism (see §G).

---

## C. Duplicate check

**Schema:** `calibration_decision_log` has a **non-unique** index `idx_calib_ticker_ts` on `(ticker, decision_ts_utc)` — duplicates are **not** prevented by SQLite.

**Proof:** `tests/test_calibration_logging_production_path.py::test_no_duplicate_ticker_decision_ts_pairs_for_distinct_refreshes` runs 8 calls with **distinct** `refresh_ts_utc` and asserts:

```sql
SELECT ticker, decision_ts_utc, COUNT(*) c
FROM calibration_decision_log
GROUP BY ticker, decision_ts_utc
HAVING c > 1
```

returns **no rows**.

**Interpretation:** With **distinct** authoritative refresh timestamps, the implementation produces **at most one** row per `(ticker, decision_ts_utc)`. Two refreshes in the **same** float second could theoretically collide; production uses monotonic wall time from `utc_ts()`.

---

## D. Missing row check

- **Successful `compute_signals` + logging enabled + DB present:** parity test (§B) shows **no missing rows** relative to call count.
- **Insert failure:** `append_calibration_decision` logs a **warning** and returns `None`; **`signals._maybe_append_calibration_log`** now logs a **warning** if `_row_id is None** when logging was enabled.

---

## E. Timestamp alignment

**Authority:** `_maybe_append_calibration_log` sets:

- `decision_ts_utc = float(inp.refresh_ts_utc)` when set and valid (`signals.py` ~192–200),
- else `default_decision_ts_utc()` (fallback for tests/offline).

**Production:** `server.py` passes **`refresh_ts_utc=_refresh_ts_utc`** from `db.utc_ts()` into `build_market_state`, which flows to **`SignalInput.refresh_ts_utc`**.

**Proof:** `tests/test_calibration_logging_production_path.py::test_decision_ts_utc_matches_refresh_ts_utc` asserts the latest row’s `decision_ts_utc` equals the injected `refresh_ts_utc`.

**Snapshot alignment:** In `server.py`, snapshot logging uses the same `_refresh_ts_utc` for the tick (`_snap_ts = _refresh_ts_utc` near ~3354), so **decision log** and **snapshot** share the same refresh instant for that poll.

---

## F. Load / contention test

**Proof:** `tests/test_calibration_logging_production_path.py::test_rapid_multithreaded_writes_no_skipped_inserts`

- 12 threads each call `compute_signals` with **distinct** `refresh_ts_utc` and **rotating tickers** (SPY, QQQ, IWM, DIA).
- Asserts **12** new rows, **no** duplicate `(ticker, decision_ts_utc)` groups, **no** uncaught exceptions.

SQLite serializes writes; `append_calibration_decision` retries on `locked`/`busy`.

---

## G. FINAL binary proof

| Check | Result |
|-------|--------|
| duplicates (distinct refresh test) | **0** |
| missing rows (parity test) | **0** |
| silent failures (insert failure) | **0** (warning on `None` row id + writer warnings) |
| **FINAL** | **PASS** |

**Stub note:** Production tests stub **`ml_predict.run_unified_stack_ml_once`** only so CI machines without 60+ snapshot rows or local artifacts still execute **`signals._compute_signals_impl` end-to-end** including **`_maybe_append_calibration_log`**. The **calibration hook and `calibration.writer` code paths are not stubbed.** A live server run uses the real `run_unified_stack_ml_once` with the same call graph.

---

## H. Validation commands

```text
cd <repo_root>
python -m pytest tests/test_calibration_logging_production_path.py -v
python -m pytest tests/ -q
```

**Recorded result:** `702 passed` (full suite), `4 passed` (calibration logging module only).

Optional harness:

```text
set ED_CALIBRATION_LOG=1
python -m calibration.validate_logging_e2e --calls 3
```

(expect `delta == expected` when full ML stack completes without raising on your machine)
