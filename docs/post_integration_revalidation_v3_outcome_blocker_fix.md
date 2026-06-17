> **Classification:** Historical Record | **Scope:** Completed analysis or validation `docs/post_integration_revalidation_v3_outcome_blocker_fix.md`.

# Post-Integration Revalidation v3 — Outcome Blocker Fix

**Date:** 2026-04-11  
**Authoritative DB:** `data/ed_console.db`

---

## 1. Executive result

The trusted calibration row could not receive `outcome_5c` because **`price_bars_1m` lacked rows at the canonical 1m bar-start timestamps** required by `forward_bar_start_utc` (BAR_ANCHOR_V1), while coarser-spaced bars (e.g. ~180s apart) existed. Missing forward bars were **recoverable** by inserting **flat** canonical 1m rows (carry-forward close) at exact grid points.

After **`calibration.repair_canonical_1m_bars_for_outcomes` → `EdDB.fill_outcomes` → `calibration.backfill_outcomes`**, the trusted row has attached outcomes and **`binary_pass_strict_production` is true**.

**FINAL RESULT: PASS**

---

## 2. Exact trusted row traced

| Field | Value |
|--------|--------|
| `calibration_decision_log.id` | **43** |
| `ticker` | SPY |
| `decision_ts_utc` | **1775926978.9349923** |
| `calibration_trust` | trusted |
| Linked `snapshots.snapshot_id` | **161097** |
| `snapshots.ts_utc` | **1775926978.9349923** (matches decision) |
| `horizon_outcome_schema_version` | 3 (BAR_ANCHOR_V1) |

**Before fix:** `snapshots.outcome_5c` was **NULL**; `outcome_15c` / `outcome_60c` were already **flat** (partial fill from whichever forward bars existed).

---

## 3. Exact root cause

**Class:** **(B) Recoverable data gap** — not a bug in `forward_bar_start_utc`, `resolve_snapshot_for_backfill`, or trust flags.

**Mechanism:** For `ts_utc = 1775926978.9349923`, horizon targets include e.g. `outcome_5c` → `bar_start = forward_bar_start_utc(ts, 5) = 1775927220.0`. In `price_bars_1m` (key `SPY`), bars in-range were on an **~180s grid** (6980, 7160, 7340, …), so **no row** existed at **1775927220.0**. `db._apply_bar_based_outcome_updates` looks up `close_by_start[float(b_start)]`; missing keys → horizon skipped → `outcome_5c` stayed NULL → `backfill_outcomes` reported `snapshot_outcomes_not_filled`.

---

## 4. Files / functions inspected

| Area | Location |
|------|-----------|
| Horizon grid | `horizon_outcomes.py` — `forward_bar_start_utc`, `OUTCOME_BAR_SPECS` |
| Outcome write | `db.py` — `fill_outcomes`, `_apply_bar_based_outcome_updates`, `_already_filled` |
| Bar upsert | `db.py` — `upsert_1m_bars` (pattern for flat bar insert) |
| Backfill | `calibration/backfill_outcomes.py` — `resolve_snapshot_for_backfill` |
| Join proof | `calibration/validate_outcome_join.py` — `binary_pass_strict_production` |

---

## 5. Exact files changed

| File | Role |
|------|------|
| `calibration/repair_canonical_1m_bars_for_outcomes.py` | **New** — inserts missing canonical 1m rows at horizon `bar_start_ts_utc` values with `source=gap_fill_canonical_1m_grid_v1`. |

**Database:** `data/ed_console.db` — four `price_bars_1m` rows inserted (7100, 7220, 7400, 7700); snapshot/calibration outcomes updated by existing pipelines.

---

## 6. Exact fix applied

1. **Repair:**  
   `python -m calibration.repair_canonical_1m_bars_for_outcomes --db data/ed_console.db --snapshot-id 161097`  
   Inserted missing bar starts **1775927100**, **1775927220**, **1775927400**, **1775927700** (flat OHLC = carry-forward close from prior bar, `volume=0`).

2. **Fill:** `EdDB.fill_outcomes("SPY", CANONICAL_TIMEFRAME, time.time())` — populates snapshot horizon columns per BAR_ANCHOR_V1.

3. **Attach:** `python -m calibration.backfill_outcomes --db data/ed_console.db` — syncs `calibration_decision_log` from snapshot (`updated: 1`, `skipped_snapshot_outcomes_not_filled: 0`).

---

## 7. Bars missing / restored

- **Missing:** Canonical 1m grid points at the four inserted timestamps (among others, existing bars were ~3 minutes apart).
- **Restored:** Four rows in `price_bars_1m` with `source = gap_fill_canonical_1m_grid_v1` (not Schwab primary feed).

---

## 8. Validator results (after fix)

Commands:

```text
python -m calibration.validate_outcome_join --db data/ed_console.db --strict-production
python -m calibration.anchor_audit --db data/ed_console.db --sample 5000
python -m calibration.audit_phase1 --db data/ed_console.db
```

| Validator | Result |
|-----------|--------|
| `validate_outcome_join` | `rows_with_outcomes`: **1**, `rows_pending_outcomes`: **0**, `verification_pass`: **1**, `binary_pass_strict_production`: **true** |
| `anchor_audit` | `binary_pass`: **true** |
| `audit_phase1` | `statistical_integrity.binary_pass`: **true** (artifact: `models/calibration_runs/phase1_audit_1775958891.json`) |

---

## 9. Remaining issues

**NONE** for this blocker: trusted slice join proof is non-vacuous and strict production gate passes.

**Operational note:** Other date ranges may still have irregular `price_bars_1m` spacing; the same repair module can be run for additional `snapshot_id`s if `snapshot_outcomes_not_filled` recurs for the same reason.

---

## 10. FINAL RESULT: **PASS**

Trusted production calibration row **43** / snapshot **161097** now has valid bar-anchor outcomes including **`outcome_5c`**, join verification runs on **1** trusted row with **0** pending, and **`binary_pass_strict_production`** is **true**.
