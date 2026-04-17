# Calibration canonical 1m enforcement (v1)

This document proves that **calibration workflows** cannot silently mix **non-1m** snapshot rows into canonical studies. Enforcement is **fail loud** (exceptions / exit code **2**), not warnings.

Checklist: **A** files changed · **B** queries/paths audited · **C** enforcement · **D** residual risk · **E** binary PASS/FAIL.

---

## A. Exact files changed

| File | Change |
|------|--------|
| `calibration/canonical_enforcement.py` | **New:** `enforce_calibration_decision_log_only_1m`, `snapshots_1m_labeled_counts`, `enforce_snapshots_fallback_is_1m_only`, `provenance_dict`, `run_binary_gate`, CLI `python -m calibration.canonical_enforcement` |
| `calibration/backfill_outcomes.py` | Calls `enforce_calibration_decision_log_only_1m` before work; exits **2** on `CalibrationCanonicalViolationError` |
| `calibration/validate_outcome_join.py` | Same gate before analysis; exit **2** on violation |
| `calibration/validate_logging.py` | Same gate; exit **2** on violation |
| `calibration/analyze_phase3.py` | Gate + `WHERE canonical_timeframe='1m'` on calibration queries; **`timeframe=?`** bind for snapshots fallback; provenance + excluded counts + snapshot contract |
| `calibration/analyze_phase4.py` | Gate + filtered calibration SQL; **`CANONICAL_TIMEFRAME`** bind for snapshots baselines; provenance on log + baselines |
| `calibration/payload_audit.py` | Schema + gate before stats; `effective_timeframe` / `source_tables` / `nearest_snapshot_query_timeframe` in JSON |
| `calibration/writer.py` | **Refuses** inserts with `canonical_timeframe != '1m'` (returns `None`, logs error) |
| `calibration/audit_phase1.py` | Symbol normalization `DISTINCT ticker` now **`WHERE timeframe='1m'`** (was all timeframes) |
| `calibration/__init__.py` | Docstring lists `canonical_enforcement` and `validate_outcome_join` CLIs |
| `docs/calibration_canonical_enforcement_v1.md` | This document |

---

## B. Every query / path audited

| Module | Role | Timeframe / contract |
|--------|------|----------------------|
| `audit_phase1.py` | Integrity audit | Gap/labels/structure uses `CANONICAL_TIMEFRAME` bind; §1 reports **all** `snapshots` timeframes for visibility (not a pooled study). Symbol normalization **1m-only** |
| `validate_logging.py` | Schema + gate | Gate on `calibration_decision_log` |
| `validate_logging_e2e.py` | E2E test | `SignalInput(timeframe="1m")`, `SnapshotRow(timeframe=CANONICAL_TIMEFRAME)` — unchanged |
| `payload_audit.py` | Payload audit | Joins `snapshots` with **`timeframe='1m'`** (nearest + exact match); gate on log |
| `backfill_outcomes.py` | Outcome join | `snapshots` **`timeframe='1m'`** (documented) |
| `validate_outcome_join.py` | Join verification | **`timeframe='1m'`** on all snapshot queries |
| `analyze_phase3.py` | Phase 3 | `calibration_decision_log` **`canonical_timeframe=?`**; fallback **`snapshots` `timeframe=?`** |
| `analyze_phase4.py` | Phase 4 | Same calibration filter; baselines **`snapshots` `timeframe=?`** |
| `writer.py` | Inserts | Only **`canonical_timeframe == '1m'`** accepted |

No calibration script pools **5m** into these studies. The DB may still **store** 5m rows for other subsystems; **`snapshots_rows_non_canonical_timeframe_in_db`** in provenance counts them as **ignored by contract**, not merged.

---

## C. Exact enforcement added

1. **`enforce_calibration_decision_log_only_1m(conn)`**  
   - Raises `CalibrationCanonicalViolationError` if any row has **`canonical_timeframe IS NULL`** or **`!= '1m'`**.

2. **`append_calibration_decision` (writer)**  
   - Rejects **`canonical_timeframe`** if not **`'1m'`** before INSERT.

3. **SQL filters**  
   - Phase 3/4: `WHERE ... AND canonical_timeframe=?` with `CANONICAL_TIMEFRAME`.  
   - Snapshot reads: `WHERE timeframe=?` bound to **`'1m'`** (no string drift).

4. **Provenance (outputs)**  
   - **`effective_timeframe`**: `1m`  
   - **`source_tables`**: e.g. `calibration_decision_log`, `snapshots`  
   - **`labeled_sample_count`**: rows used in the analysis query  
   - **`excluded_by_reason`**: e.g. pending outcomes, unlabeled 1m snapshots, non-1m rows present in DB but not queried, **LIMIT 200000** cap in phase 4 baselines

5. **Snapshot fallback (phase 3 empty log)**  
   - Query uses **`timeframe=?`** only.  
   - **`enforce_snapshots_fallback_is_1m_only`** documents counts; **does not** SELECT across timeframes.

6. **Binary gate CLI**  
   - `python -m calibration.canonical_enforcement` → JSON with **`binary_pass`** and exit **0** / **2**.

---

## D. Any remaining contamination risk (in scope)

| Risk | Mitigation |
|------|------------|
| **Code outside `calibration/`** (e.g. `signals`, `prediction_engine`) queries `snapshots` without `timeframe` | Not part of **calibration package** workflows; this task hardens **calibration** only |
| **JSON columns** (`fusion_json`, `canonical_json`, …) reference multi-clock semantics in text | Not SQL-level mixing; studies aggregate **decision log + 1m snapshot** joins as coded |
| **Ad-hoc SQL** by operators | Institutional process: run `python -m calibration.canonical_enforcement` before studies; gate fails on bad `canonical_timeframe` rows |
| **`audit_phase1`** still **reports** `snapshots_by_timeframe` including 5m | Informational distribution; **no** calibration metric pools 5m into 1m queries |

---

## Reproduce (binary proof)

```bash
python -m calibration.canonical_enforcement --db data/ed_console.db
python -m calibration.validate_logging --db data/ed_console.db
python -m calibration.analyze_phase3 --db data/ed_console.db
python -m calibration.analyze_phase4 --db data/ed_console.db
python -m calibration.payload_audit
```

Expected: **`canonical_enforcement`** prints **`"binary_pass": true`**; other commands exit **0**; **`CalibrationCanonicalViolationError`** never raised on a clean DB.

---

## E. PASS / FAIL (binary)

**PASS** — canonical calibration paths enforce **`1m`** and **fail loudly** on non-canonical `calibration_decision_log` rows; snapshot fallbacks **cannot** pool 5m by construction (parameterized `timeframe='1m'` only).
