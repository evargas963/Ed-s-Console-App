> **Classification:** Policy Specification | **Scope:** Technical documentation `docs/calibration_phase2_logging_layer.md`.

# Phase 2 — Calibration logging layer

## Objective

Persist **one row per decision cycle** in an analysis-ready schema, parallel to the existing `DECISION_BUNDLE` log line in `signals.py`, so calibration does not depend on scraping server logs.

## Schema

Defined in `calibration/schema.py` as table **`calibration_decision_log`**.

**Identity / context:** `decision_ts_utc`, `ticker`, `canonical_timeframe` (default `1m`), `session_label`, `expiry`, `build_generation` (from `ED_BUILD_GENERATION` if set).

**Structural:** `zone`, `vwap_side`, `nearest_above_dist`, `nearest_below_dist`, `structural_json` (nearest level names/values).

**Regime:** `regime_primary`, `regime_confidence`, `vol_regime`, `vix_bucket`, `session_bucket`, `regime_json`.

**Models / fusion / canonical:** `model_outputs_json` (XGB/LSTM/Transformer serialization + stack bundle), `monte_carlo_json`, `fusion_json`, `canonical_json`.

**Decision:** `final_signal`, `call_conviction`, `entry_price`, `stop_price`, `target_price`, `target2_price`, `validation_summary`, `multi_horizon_json` (MHAP / alignment fields).

**Outcomes (backfilled):** `outcome_1c` … `outcome_60c`, point columns, `outcomes_attached_ts_utc`.

**Raw:** `raw_bundle_json` (compact excerpts for audit).

**Indexes:** `(ticker, decision_ts_utc)`; partial index on rows pending `outcome_5c`.

## Write path

1. Set **`ED_CALIBRATION_LOG=1`** (or `true` / `yes` / `on`).
2. On each successful `compute_signals` completion, `signals._maybe_append_calibration_log` calls `calibration.writer.append_calibration_decision(...)`.
3. The writer opens the console DB (`db.DB_PATH` / `data/ed_console.db`), runs `ensure_calibration_schema`, and **INSERT**s one row.

`decision_ts_utc` uses `db.utc_ts()` for alignment with snapshot timing (same clock as the rest of the console).

## Backfill / attach outcomes

After `fill_outcomes` has populated snapshot rows:

```text
python -m calibration.backfill_outcomes --db data/ed_console.db --tol 5.0
```

Join rule: same `ticker`, `ABS(snapshots.ts_utc - decision_ts_utc) <= tol` (default 5 seconds), preferring the closest snapshot row. **Sample counts** after backfill should be reported in every analysis script.

## Validation

```text
python -m calibration.validate_logging --db data/ed_console.db
```

## Current status (this repo snapshot)

Until live or replay traffic runs with `ED_CALIBRATION_LOG=1`, the table may be **empty**. Phase 3/4 analyses therefore support a **snapshots fallback** where noted — authoritative metrics require the log + backfill path above.
