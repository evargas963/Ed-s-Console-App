# FIND-CAL-TS — hour-resolution consumer audit

**Tip:** `1b27d03` · **COH-I-A fix:** `99ea0e0` (`time_et.now_et`, DST-aware `America/New_York`)

## Problem statement

Pre-`99ea0e0` snapshot rows may carry **EST-fixed** `et_hour`, `et_minute`, `market_session`, and hour portion of `ts_et` while `ts_utc` remains authoritative UTC. Consumers that read stored hour fields from historical rows inherit up to **1 hour skew** during EDT (~8 months/year). Day-only bucketing via `ts_et[:10]` is usually safe for RTH intraday data.

## Classification key

| Class | Meaning | Calibration widen |
|-------|---------|-------------------|
| **A — SAFE** | Re-derives ET from `ts_utc` / `decision_time_ms` | May widen on this path |
| **B — STORED-HOUR** | Reads `et_hour` / `et_minute` / `market_session` from DB or snapshot dict | Gate: upgrade or backfill first |
| **C — HYBRID** | Date from `ts_et[:10]`; hour gate from stored fields | Date widen OK; hour gate needs B fix |

---

## A — DST-safe (re-derive from `ts_utc` / `decision_time_ms`)

| Site | Mechanism |
|------|-----------|
| `server.py` L3955-3956 | Live `et_h`/`et_m` from `now_et()` at fetch time |
| `server.py` L4206-4369 | Snapshot write uses `now_et()` + `build_ts_et(_et_now)` |
| `calibration/v2_advisory_backfill.py` L117 | `decision_time_ms = int(ts_utc * 1000)` |
| `v2_decision/a2_eod_force_exit.py` L23-31 | `derive_et_clock_from_decision_time_ms` |
| `v2_decision/a2_option_expression.py` L784-792 | Same via `decision_time_ms` |
| `v2_decision/a2_session_calendar.py` L57 | `decision_time_ms` → `astimezone(ET)` |
| `features/xgb_model_input.py` L100-124 | `_et_from_ts_utc(ts)` on inference path |
| `verification/daily_health.py` L205-218 | `_et_minute_of_day(ts_utc)`, `_et_date(ts)` |
| `live_decision_bundle.py` L221 | Bundle timestamps from `ts_utc` |
| `calibration/validate_logging_e2e.py` L165-167 | Test writer uses `now_et()` |

---

## B — STORED-HOUR (historical skew risk)

| Site | Field read | Impact |
|------|------------|--------|
| `db.py` L4234-4243 | `market_session(et_hour, et_minute)` | Session label wrong at edges if args from stored row |
| `ml_data_common.py` L24-28 | `rth_where_clause()` SQL on `et_hour`,`et_minute` | **Training cohort shifts 1h during EDT:** stored window 9:30–16:00 maps to **10:30–17:00 actual** (drops 9:30–10:30 RTH; includes 16:00–17:00 after-hours) |
| `ml_train.py` L237, L334-375 | `rth_where_clause` + feature `time_sin/cos`, `minutes_since_open`, volume TOD | **Feature skew** on historical rows |
| `training_cache.py` L93, L221, L253 | Same SQL fragment | Same as ml_train |
| `ml_scheduler.py` L174, L218 | Same SQL fragment | Scheduler eligibility skew |
| `lstm_data.py` L393-397 | `_is_rth(d["et_hour"], d["et_minute"])` | **Row drop/include** wrong at RTH edges |
| `call_engine.py` L491-497 | `inp.et_hour` / `inp.et_minute` | Live OK (from `now_et`); **replay/backfill ms** skewed |
| `prediction_engine.py` L516-522 | Pass-through `inp.et_hour` | Same |
| `math_volatility.py` L96-97 | `session_bucket(et_hour, et_minute)` | Bucket skew when inputs from stored row |
| `v2_decision/a2_lifecycle_sidecar.py` L419-423 | `ms["et_hour"]` fallback for mins-since-open | **Skewed** when ms from `ms_dict_from_snapshot_row` |
| `calibration/phase6_edge_discovery_governed_v1.py` L376 | `r["market_session"]` bucketing | **Calibration cohort** mis-bucketed |
| `calibration/phase65_edge_isolation_v1.py` L482 | Same | Same |
| `calibration/anchor_audit.py` L102-110, L345+ | `market_session` from snapshots | Audit aggregates skewed |
| `audit_model_readiness.py` L32-33 | Inline RTH SQL on `et_hour` | Readiness counts skewed |
| `tools/select_movement_thresholds_percentile_v1.py` | `rth_where_clause()` | Tooling skew |
| `tools/calibrate_movement_threshold_v1.py` | `rth_where_clause()` | Tooling skew |

---

## C — HYBRID (date OK; hour gate at risk)

| Site | Notes |
|------|-------|
| `lstm_data.py` L401-403 | `day_key = ts_et[:10]` — **date bucket robust** for RTH; RTH filter still uses stored hour (B) |
| `ml_train.py` L247-250 | `substr(ts_et, 1, 10) IN (...)` date filter — date OK; row set still filtered by `rth_where_clause` (B) |

---

## Remediation recommendations (paired-fix order)

### FIND-CAL-TS-RDERIVE (forward path — unblock widen)

1. **`time_et.et_clock_from_ts_utc(ts_utc) -> (hour, minute, weekday)`** — single authority.
2. **Training/calibration eligibility** — post-fetch RTH filter via helper (replace trusting `rth_where_clause` alone); **and** derive time-of-day **features** from `ts_utc` at train time (`ml_train` L334–375 must not trust stored `et_hour`/`et_minute` on old rows).
3. **Calibration phase6/anchor** — re-derive `market_session` from `ts_utc` when bucketing (do not trust stored field).
4. **`v2_advisory_backfill.ms_dict_from_snapshot_row`** — stamp `et_hour`/`et_minute` from `ts_utc` on reconstruct (isolates `a2_lifecycle_sidecar` L419–423 without sidecar change).
5. **Pragmatic widen interim:** `min_ts_utc >= <99ea0e0_landing_ts>` cohort on rows logged by fixed `now_et()` path.

### Historical backfill (required for full closure — not optional)

6. **`UPDATE` backfill** — rewrite `et_hour`, `et_minute`, `market_session`, `ts_et` from `ts_utc` for pre-cutover rows. Items 1–5 fix forward behavior; **trained artifacts on pre-99ea0e0 EDT data retain skew** until backfill or full retrain on re-derived features only.

---

## Operator gate (FIND-CAL-TS)

| Lane | Status |
|------|--------|
| Live Tier C / v2 advisory backfill | **OPEN** for widen (A) |
| Day-bucket / `decision_time_ms` paths | **OPEN** |
| Widen with `min_ts_utc` cutover post-99ea0e0 | **OPEN** after RDERIVE (items 1–5) |
| `rth_where_clause` SQL training/calibration | **GATED** until RDERIVE |
| `market_session` cohort calibration | **GATED** until RDERIVE |
| Full historical replay / promoted models on old EDT | **GATED** until backfill (item 6) |

**Next:** `FIND-CAL-TS-RDERIVE` (items 1–5) → calibration widen on cutover cohort → backfill (item 6) for full historical closure.
