> **Classification:** Policy Specification | **Scope:** Technical documentation `docs/calibration_phase1_data_integrity.md`.

# Phase 1 — Data integrity audit

**Purpose:** Establish whether the SQLite feature store is fit for institutional calibration before trusting any threshold or decision-metrics.

**How to reproduce**

```text
python -m calibration.audit_phase1 --db data/ed_console.db
```

JSON artifacts are written to `models/calibration_runs/phase1_audit_<unix_ts>.json`. The audit bootstraps `calibration_decision_log` if missing so the schema is present for downstream phases.

---

## Methodology (short)

| Check | What it tests |
|--------|----------------|
| Canonical timeframe | `snapshots.timeframe` distribution vs `CANONICAL_TIMEFRAME` (`1m`) |
| Gap / continuity | Per-ticker gaps on `ts_utc` (1m snapshots); RTH gap counts when `market_session='rth'`; parallel stats on `price_bars_1m.bar_start_ts_utc` |
| Snapshot ↔ bar anchor | Random sample: existence of `MAX(bar_end_ts_utc)` with `bar_end_ts_utc <= snapshot.ts_utc` in `price_bars_1m` |
| Outcome labels | Null rates; direction vs points sign sanity (strict threshold 0.25 pts) |
| Structural completeness | Zone / VWAP null rates; negative `nearest_*_dist` counts (Option A) |
| Symbol normalization | `ticker_storage_key` fragmentation across distinct raw tickers |

---

## Findings (representative run on this workspace’s `data/ed_console.db`)

Values below come from `models/calibration_runs/phase1_audit_1775870789.json` unless noted. **Re-run the script** on your database before treating numbers as current.

### Proven

- **Canonical structural distances (Option A):** Among 55,372 canonical `1m` snapshot rows, **zero** rows store negative `nearest_above_dist` or `nearest_below_dist` (`canonical_option_a_violation: false`).
- **Outcome direction vs points (spot checks):** `suspect_up_negative_pts_gt_0_25` and `suspect_down_positive_pts_gt_0_25` are both **0** at the audited threshold — no gross sign/direction mismatch in stored pairs.
- **Symbol fragmentation:** 26 distinct raw tickers map to 26 distinct storage keys; **`fragmented_key_count: 0`** (no `SPX` vs `$SPX` split in this dataset).
- **`price_bars_1m` cadence:** For many liquid symbols, median inter-bar gaps are **60s** with controlled p95 (e.g. SPY p95 gap 60s in the artifact), consistent with a 1m grid when history is contiguous.

### Uncertain

- **Forward leakage into *features*:** The audit **cannot** prove that each training/inference feature vector excludes post-`ts_utc` information without a full feature replay. Outcome **labels** are contractually forward (`horizon_outcomes.py` + `fill_outcomes`). Treat feature-time isolation as a **separate** line of evidence (replay tests, not this SQL audit).
- **Snapshot rows without anchor bar:** In a 5,000-row random sample, **22.6%** had no `price_bars_1m` row with `bar_end_ts_utc <= ts_utc`. This may reflect early history before bar backfill, symbol coverage, or clock skew — **requires** ticker-level drill-down before using those rows for bar-anchored similarity.

### Failed / violations (for calibration scope)

- **Non-canonical timeframe mass:** **103,109** snapshot rows are stored with `timeframe='5m'` vs **55,371** with `1m`. Any calibration that accidentally pools both **violates** the canonical 1m policy. **Remediation:** restrict calibration SQL to `timeframe='1m'` (and/or migrate legacy 5m to derived tables only, as already described in `timeframe_config.py`).

### Remediation required

1. **Enforce `timeframe='1m'` filters** in all calibration / training extracts (explicit `WHERE timeframe='1m'`).
2. **Investigate anchor miss rate:** For tickers used in production calibration, reconcile `snapshots.ts_utc` with `price_bars_1m` coverage; backfill bars or exclude pre-coverage rows from bar-anchored metrics.
3. **Outcome null rates** (same run): `outcome_5c` null rate ≈ **60.8%** on all 1m rows — expected for horizons not yet filled; calibration must **subset** to labeled rows and report **effective n** everywhere.

---

## Classification summary

| Category | Summary |
|----------|---------|
| **Proven** | Option A distances hold; no symbol fragmentation; no coarse outcome sign bugs in sample |
| **Uncertain** | Feature-time leakage; exact anchor coverage for every snapshot |
| **Failed** | Large legacy `5m` snapshot pool coexists with canonical `1m` — must not mix for calibration |
| **Remediation** | Filter to 1m; bar coverage audit per ticker; always report labeled sample counts |
