> **Classification:** Historical Record | **Scope:** Root historical reference `MIGRATION_1M_CANONICAL.md`.

# Migration: 1m Canonical Timeframe

## Summary

The system now uses **1m as the canonical timeframe** for live state, snapshot generation, feature engineering, and model training. 5m remains available as derived context for structure analysis.

## Outcome Horizon Semantics (FLAGGED)

**CRITICAL:** With `timeframe='1m'`, outcome column semantics change:

| Column      | With 5m (legacy)   | With 1m (canonical) |
|-------------|--------------------|----------------------|
| outcome_1c  | ~5 min ahead       | ~1 min ahead         |
| outcome_3c  | ~15 min ahead      | ~3 min ahead         |
| outcome_5c  | ~25 min ahead      | ~5 min ahead         |
| outcome_8c  | ~40 min ahead      | ~8 min ahead         |
| outcome_13c | ~65 min ahead      | ~13 min ahead        |

**Affected components:**

1. **db.fill_outcomes** — Bar windows (0.9–2.5 bars for 1c, etc.) are in bar units. Physical time = bars × 60 sec for 1m.
2. **lstm_data.TARGET_HORIZON** — `outcome_1c` now means ~1 min ahead.
3. **XGB/LSTM/Transformer models** — All trained on outcome_1c/5c/etc. **Retrain required** for 1m data. Existing models trained on 5m data will produce misaligned predictions.
4. **prediction_engine** — `compute_probs(similar, "outcome_1c")` etc. — Similar-setup lookup uses whatever timeframe the DB has. With 1m snapshots, similar setups will have 1m outcomes.
5. **ml_train.load_data** — Now filters `timeframe = CANONICAL_TIMEFRAME`. XGB training uses 1m rows.
6. **train_compare, audit_model_readiness** — Accuracy metrics compare against outcome_1c/5c. Ensure test data is 1m.

## Migration Risks

1. **Empty DB after switch** — Existing snapshots have `timeframe='5m'`. New snapshots will have `timeframe='1m'`. Queries filtering by `timeframe='1m'` will return no rows until new data accumulates. **Mitigation:** Run server for at least one RTH session to populate 1m snapshots before training.

2. **Model retrain required** — All ML models (XGB, LSTM, Transformer) were trained on 5m snapshots. They must be retrained on 1m snapshots. Old model files will produce invalid/wrong predictions.

3. **Higher snapshot volume** — 1m bars close 5× more often than 5m. With ~30s refresh, we still get ~2 snapshots per 1m bar. DB growth rate similar; outcome windows are shorter so fills happen sooner.

4. **Outcome fill timing** — `fill_outcomes` uses `_tf_seconds(timeframe)` (60 for 1m). Outcome_1c fills when 0.9–2.5 bars ago = 54–150 seconds. Ensure server runs continuously so refreshes occur within that window.

5. **Backward compatibility** — To read legacy 5m snapshots, pass `timeframe="5m"` explicitly to `extract_rth_snapshots`, `load_data`, etc. Default is now 1m.

## Files Changed

- `timeframe_config.py` (new) — Central CANONICAL_TIMEFRAME constant
- `server.py` — 1m primary for snapshot OHLC, ATR, vol, etc.; timeframe=CANONICAL_TIMEFRAME
- `db.py` — Test uses CANONICAL_TIMEFRAME
- `lstm_data.py` — extract_rth_snapshots default 1m; build_lstm_dataset timeframe param
- `market_state.py` — SignalInput timeframe=CANONICAL_TIMEFRAME
- `signal_types.py` — Docstring update
- `prediction_engine.py` — timeframe default, candles_1m volume fallback
- `transformer_train.py` — timeframe param default 1m
- `ml_scheduler.py` — CANONICAL_TIMEFRAME in queries
- `ml_predict.py` — get_recent_snapshots with CANONICAL_TIMEFRAME
- `ml_train.py` — load_data filters by timeframe (default 1m)
- `train_all.py` — Ticker discovery uses CANONICAL_TIMEFRAME
- `train_compare.py` — extract_rth_snapshots with CANONICAL_TIMEFRAME
- `verify_snapshot_pipeline.py` — TIMEFRAME from config
- `audit_model_readiness.py` — SPY query uses CANONICAL_TIMEFRAME
- `test_call_stack_driven.py` — Hardcoded timeframe="1m"

## Snapshot Insert Enforcement (2026-03)

**Root cause of zero 1m rows:** Existing snapshots were written by a server process when `CANONICAL_TIMEFRAME` was `"5m"` (pre-migration). The code already used `timeframe=CANONICAL_TIMEFRAME` in `server.py`; the live process had not been restarted after the config change.

**Fix:** `db.insert_snapshot()` now enforces canonical 1m:
- If caller passes `timeframe != "1m"`, it is overridden to `"1m"` and a warning is logged.
- Server startup asserts `CANONICAL_TIMEFRAME == "1m"` and fails loudly if misconfigured.
- `verify_snapshot_pipeline.py` checks that the most recent snapshot has `timeframe='1m'` (fails if no new 1m rows yet).

**How to verify new 1m inserts:**
1. Restart the server (ensures fresh import of `CANONICAL_TIMEFRAME`).
2. Run during RTH; wait for at least one snapshot insert.
3. Run `python verify_snapshot_pipeline.py` — should pass once the most recent row is 1m.
4. Query: `SELECT timeframe, COUNT(*) FROM snapshots GROUP BY timeframe` — should show new 1m rows accumulating.

**Old 5m rows:** Unchanged. They remain in the DB. New inserts are 1m only.

## Rollback

To revert to 5m canonical:

1. Set `CANONICAL_TIMEFRAME = "5m"` in `timeframe_config.py`
2. In `server.py`: Change `_candles_1m` back to `_candles_5m` for snapshot candle fields, ATR, realized vol, volume
3. Retrain models on 5m data
