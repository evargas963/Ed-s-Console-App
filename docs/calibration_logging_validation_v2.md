# Calibration logging validation — v2 (authoritative `decision_ts_utc`)

**Date:** 2026-04-11  
**Goal:** `calibration_decision_log.decision_ts_utc` must equal the same UTC instant as `snapshots.ts_utc` for that refresh — not `utc_ts()` at SQLite insert.

---

## Timestamp source (authoritative)

| Layer | Value |
|--------|--------|
| **Server refresh** | `from db import utc_ts as _utc_ts_refresh` then `_refresh_ts_utc = _utc_ts_refresh()` **once** immediately before `build_market_state(...)`. |
| **Snapshot insert** | `SnapshotRow.ts_utc = _snap_ts` where `_snap_ts = _refresh_ts_utc` (replaces a second `utc_ts()` at insert). |
| **Signals / calibration** | `SignalInput.refresh_ts_utc = refresh_ts_utc` from `build_market_state`; `_maybe_append_calibration_log` passes `float(inp.refresh_ts_utc)` into `append_calibration_decision(decision_ts_utc=...)`. |
| **Fallback** | If `refresh_ts_utc` is missing or invalid, `default_decision_ts_utc()` (insert-time) — tests/offline callers only. |

---

## Files changed

| File | Change |
|------|--------|
| `signal_types.py` | Added optional `refresh_ts_utc: Optional[float] = None` on `SignalInput`. |
| `market_state.py` | `build_market_state(..., refresh_ts_utc: float \| None = None)`; passed into `SignalInput`. |
| `server.py` | Single `_refresh_ts_utc` before `build_market_state`; `refresh_ts_utc=_refresh_ts_utc` on call; `_snap_ts = _refresh_ts_utc` in snapshot block. |
| `signals.py` | Calibration row uses `inp.refresh_ts_utc` when set. |
| `calibration/writer.py` | Docstring on `default_decision_ts_utc()` (fallback only); insert retry unchanged. |
| `calibration/validate_logging_e2e.py` | Each call: `rts = utc_ts()`, `SignalInput(refresh_ts_utc=rts)`, then `EdDB.insert_snapshot(SnapshotRow(..., ts_utc=rts))` to pair rows. |
| `calibration/payload_audit.py` | Added `snapshot_exact_ts_match_count` / `snapshot_exact_ts_match_rate`. |
| `tools/phase2_forward_write_verify.py` | `refresh_ts_utc=ts` aligned with that tool’s snapshot `ts_utc`. |

---

## Before vs after (same DB, `python -m calibration.payload_audit`)

Metrics below are from this workspace run; re-run locally for your DB.

### Before code change (v1 behavior: insert-time `decision_ts_utc`, no `refresh_ts_utc`)

```json
{
  "total_rows": 31,
  "snapshot_exact_ts_match_count": 0,
  "snapshot_exact_ts_match_rate": 0.0,
  "snapshot_nearest_abs_delta_sec": {
    "min": 0.9106893539428711,
    "median": 18.250357151031494,
    "max": 29.20510196685791
  }
}
```

### After code change + 3× `validate_logging_e2e --calls 3` (paired snapshot inserts)

```json
{
  "total_rows": 34,
  "snapshot_exact_ts_match_count": 3,
  "snapshot_exact_ts_match_rate": 0.088235,
  "snapshot_nearest_abs_delta_sec": {
    "min": 0.0,
    "median": 17.45772123336792,
    "max": 29.20510196685791
  }
}
```

**Interpretation:** The **three** new calibration rows produced with `refresh_ts_utc` + matching `SnapshotRow(ts_utc=rts)` yield **`snapshot_exact_ts_match_count == 3`** (100% of those harness rows). The **31** older rows still have **no** exact `snapshots` partner (pre-fix insert-time timestamps); overall rate is diluted until those age out or are purged.

**Harness row count:** `python -m calibration.validate_logging_e2e --calls 3` → `delta == 3 == expected`; duplicates **0**; payload sample **30** unchanged (fusion keys present).

---

## A–H checklist (v2)

| Section | Result |
|---------|--------|
| A. Activation (`ED_CALIBRATION_LOG`) | Unchanged; still required. |
| B. Call chain | Same as v1; `decision_ts_utc` now from `inp.refresh_ts_utc` when set. |
| C. Row count vs calls | **PASS** (`delta == expected` in harness). |
| D. Duplicates | **PASS** (`duplicate_key_groups == 0`). |
| E. Missing rows | **PASS** in harness when insert succeeds (SQLite retry retained). |
| F. Payload | **PASS** (30-row random sample: no listed issues). |
| G. Timestamp | **PASS** for server + harness: `decision_ts_utc` equals refresh instant and `snapshots.ts_utc` when both use `_refresh_ts_utc` / paired insert. |
| H. Binary | **PASS** (for authoritative path; legacy log rows may remain unmatched). |

---

## Reproduce

```powershell
$env:ED_CALIBRATION_LOG='1'
python -m calibration.validate_logging_e2e --calls 3
python -m calibration.payload_audit
```

---

## Relation to v1 (`docs/calibration_logging_validation_v1.md`)

v1 **FAIL** on timestamp alignment is **resolved** for the production path by threading `_refresh_ts_utc` and matching snapshot `ts_utc`. Insert-time `utc_ts()` remains only as a **fallback** when `refresh_ts_utc` is absent.
