> **Classification:** Historical Record | **Scope:** Completed analysis or validation `docs/calibration_logging_validation_v1.md`.

# Calibration logging validation — v1

**Date:** 2026-04-11  
**Database:** `data/ed_console.db` (workspace path)  
**Controlled harness:** `python -m calibration.validate_logging_e2e` with `ED_CALIBRATION_LOG=1`  
**Metrics script:** `python -m calibration.payload_audit`

This report documents **observed** behavior from code inspection and the runs above. It does **not** prove production server behavior unless the server process sets `ED_CALIBRATION_LOG` the same way.

---

## A. Logging activation status

| Check | Result |
|--------|--------|
| `ED_CALIBRATION_LOG=1` enables logging | **Yes** — `calibration.writer.calibration_logging_enabled()` returns true only for `1`, `true`, `yes`, `on` (case-insensitive). |
| `ED_CALIBRATION_LOG` unset / other | **No row** — `_maybe_append_calibration_log` returns immediately when the env var is not one of those tokens. |

---

## B. Call chain proof (exact)

Authoritative decision bundle is built in `_compute_signals_impl`; after the in-memory snapshot dict is built and **`_log_decision_bundle`** runs, **`_maybe_append_calibration_log`** runs **once per successful** completion of `compute_signals` (no early exception).

```698:733:c:\Users\evarg\Documents\Trading\EdWebConsole\signals.py
    _log_decision_bundle(
        ticker,
        canonical,
        getattr(fusion, "available", False) if fusion is not None else False,
        final_signal=call.signal,
        call_conviction=call.conviction,
        size_cue=call.size_cue,
        gate_summary=call.validation_summary or "",
        pred_override_applied=pred_override_applied,
        multi_horizon={
            "primary_horizon": mh_dec.primary_horizon,
            "trade_mode": mh_dec.trade_mode,
            "alignment_state": mh_dec.alignment_state,
            "conflict_level": mh_dec.alignment_report.conflict_level,
            "final_bias": mh_dec.final_bias,
            "final_tradeable": mh_dec.final_tradeable,
            "wait_reason": mh_dec.wait_reason,
        },
    )

    _maybe_append_calibration_log(
        inp=inp,
        ticker=ticker,
        regime=regime,
        vol_regime=vol_regime,
        fusion=fusion,
        canonical=canonical,
        pred=pred,
        call=call,
        xgb_out=xgb_out,
        lstm_out=lstm_out,
        transformer_out=transformer_out,
        mc_out=mc_out,
        ml_bundle=ml_bundle,
        mh_bundle=mh_bundle,
    )
```

```164:212:c:\Users\evarg\Documents\Trading\EdWebConsole\signals.py
def _maybe_append_calibration_log(
    ...
) -> None:
    """Persistent calibration row (Phase 2). Off unless ED_CALIBRATION_LOG=1."""
    if os.environ.get("ED_CALIBRATION_LOG", "").strip().lower() not in (
        "1",
        "true",
        "yes",
        "on",
    ):
        return
    try:
        from calibration.writer import append_calibration_decision, default_decision_ts_utc

        append_calibration_decision(
            decision_ts_utc=default_decision_ts_utc(),
            ...
        )
    except Exception as e:
        log.debug("calibration decision log skipped: %s", e)
```

**Chain:** `compute_signals` → `_compute_signals_impl` → … stack … → `_log_decision_bundle` → `_maybe_append_calibration_log` → `append_calibration_decision` → SQLite `INSERT`.

**Conditions under which logging fires**

1. **`ED_CALIBRATION_LOG` ∈ {`1`,`true`,`yes`,`on`}** (case-insensitive).
2. **`compute_signals` returns normally** — any exception before `_maybe_append_calibration_log` produces **no** calibration row.
3. **`append_calibration_decision` succeeds** — DB file must exist; insert must not fail after retries (see below).
4. **`db` passed to `compute_signals` must be `EdDB`** (or compatible) for full stack; raw `sqlite3.Connection` breaks prediction paths and was **not** used in the successful harness.

---

## C. Row count vs expected events (controlled run)

| Step | Value |
|------|--------|
| Harness | `python -m calibration.validate_logging_e2e --calls 3` after writer retry fix |
| `rows_before` | 2 (prior failed inserts from an earlier experiment) |
| `rows_after` | 5 |
| `delta` | **3** |
| `expected` | **3** |
| Match | **Yes** (`delta == expected`) |

Second run: `--calls 26` on top of existing rows: `delta=26`, `expected=26` — **match.**

**Conclusion (controlled environment):** One successful `compute_signals` invocation produces **one** inserted row when logging is enabled and the insert succeeds.

**Prior failure (documented):** Before bounded retries on `database is locked`, one of three inserts failed; **no** missing-row detection is possible in that configuration. **Change applied:** `calibration/writer.py` now retries `INSERT` on SQLite busy/locked up to 12 attempts with backoff and uses `timeout=60.0` on connect.

---

## D. Duplicate analysis

Query: `GROUP BY ticker, decision_ts_utc HAVING COUNT(*) > 1`

**Result (n = 31 rows in table at audit time):**

- `duplicate_key_groups`: **0**
- `duplicate_extra_rows`: **0**

**Note:** There is **no** `UNIQUE(ticker, decision_ts_utc)` constraint; duplicates are possible if two decisions share the same float timestamp. None observed in this dataset.

---

## E. Missing row analysis

| Scenario | Row written? |
|----------|----------------|
| `ED_CALIBRATION_LOG` off | **No** (early return) |
| `compute_signals` raises before `_maybe_append_calibration_log` | **No** |
| DB missing / insert fails after retries | **No** |
| Successful `compute_signals` + enabled + insert OK | **Yes** (observed in harness) |

**Missing vs “decision events”:** In this harness, **decision events = number of `compute_signals` calls**. **Missing count = 0** when `delta == calls`.

**Production:** Not measured here — would require correlating server “refresh” or `DECISION_BUNDLE` log lines to DB rows.

---

## F. Payload completeness (random sample n = 30)

Script: `python -m calibration.payload_audit`

**Results:**

- `sample_size`: **30**
- `fusion_prob_keys_missing_in_sample`: **0** (all 30 had `prob_up`, `prob_down`, `prob_flat` in `fusion_json`)
- `payload_rows_with_listed_issues`: **0** (no empty `fusion_json` / `canonical_json` / `model_outputs_json`; all had `xgb`, `lstm`, `transformer` keys in `model_outputs_json`; `final_signal` non-null)
- `monte_carlo_json`: present (not individually asserted in script; column non-null in sampled rows)

**Structural / regime columns:** `zone`, `vwap_side`, `nearest_above_dist`, `nearest_below_dist`, `regime_primary`, `regime_confidence`, `vol_regime` populated for sampled rows (SPY harness — zone `pin_bull`, VWAP `above`, distances `2.0`).

---

## G. Timestamp correctness

**What is logged:** `decision_ts_utc = default_decision_ts_utc()` → `db.utc_ts()` (wall-clock seconds at **insert** time in `append_calibration_decision`), **not** a field from `SignalInput` (there is **no** `ts_utc` on `SignalInput` in `signal_types.py`).

**G1 — Wall time at writer:** **PASS** — timestamp is the instant the writer runs (end of successful `compute_signals`).

**G2 — Equality to `snapshots.ts_utc` for the same refresh:** **FAIL** — the writer does **not** receive or persist the snapshot row’s `ts_utc`. Empirical check: nearest `snapshots` row by `ABS(ts_utc - decision_ts_utc)` (ticker `SPY`, `timeframe='1m'`), **n = 31**:

| Stat | Seconds |
|------|---------|
| min | **0.911** |
| median | **18.25** |
| max | **29.21** |

Those deltas compare to **historical** snapshot rows, not a snapshot created in the same harness refresh — they prove **non-equality** to any notion of “same-bar” snapshot key unless the refresh timestamp is threaded in.

---

## H. PASS / FAIL (binary)

**FAIL**

| Criterion | Verdict |
|-----------|---------|
| Activation + call chain + one-row-per-successful-`compute_signals` (harness) | **PASS** |
| No duplicates (exact ticker+ts in this DB) | **PASS** |
| Payload fields (30-row sample) | **PASS** |
| Timestamp vs `snapshots.ts_utc` / market snapshot key | **FAIL** |

**Exact reasons (FAIL):**

1. **`decision_ts_utc` is wall time at writer execution**, not the canonical refresh / `snapshots.ts_utc` used for feature alignment.
2. **Empirical gap** to nearest stored snapshot: **0.91s–29.2s** in this database (not zero).

**Exact fixes required (for a future PASS on G2):**

1. **Thread** the authoritative refresh timestamp (the same value written to `snapshots.ts_utc` for that tick) into `append_calibration_decision` — e.g. extend `SignalInput` or pass an explicit `snapshot_ts_utc` from the server path that calls `compute_signals` and `insert_snapshot`.
2. **Persist that value** as `decision_ts_utc` (or add a dedicated column) so joins are deterministic with `snapshots`.

**Change already applied for insert reliability (not optional for trust):** SQLite busy/locked retries in `calibration/writer.py` so `rows == calls` under concurrent DB access.

---

## Reproduce

```powershell
$env:ED_CALIBRATION_LOG='1'
python -m calibration.validate_logging_e2e --calls 3
python -m calibration.payload_audit
```
