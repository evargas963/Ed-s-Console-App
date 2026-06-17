> **Classification:** Audit Report | **Scope:** Card direction integrity vs price movement (SPY/QQQ/IWM)

# Card direction integrity — 2026-06-17

DB: `C:\Users\evarg\Documents\Trading\EdWebConsole\data\ed_console.db`
Min decline window: 30 minutes

## Summary

- Decline intervals: 4
- Tickers with decline: SPY
- LONG-during-decline samples (any horizon): 30

## Base ticker observability

- **SPY**: FAIL_MISSING_NORMALIZED — norm_rows=0 cal_rows=488 (zero normalized rows in RTH window)
- **QQQ**: FAIL_MISSING_NORMALIZED — norm_rows=0 cal_rows=17 (zero normalized rows in RTH window; median_gap_seconds=1313.5 exceeds 90.0; max_gap_seconds=1688.7 exceeds 300.0)
- **IWM**: FAIL_SPARSE_SNAPSHOTS — norm_rows=17 cal_rows=17 (snapshot_rows_rth=17 normalized_rows_rth=17 below minimum 300; median_gap_seconds=1304.8 exceeds 90.0; max_gap_seconds=1671.2 exceeds 300.0)

## Data limitations

- **SPY**: price=`snapshots` rows=374 observability=FAIL_MISSING_NORMALIZED
- **QQQ**: price=`snapshots` rows=17 observability=FAIL_MISSING_NORMALIZED
- **IWM**: price=`snapshots_1m_normalized` rows=17 observability=FAIL_SPARSE_SNAPSHOTS
- SPY/QQQ normalized rows missing on 2026-06-17; audit used raw `snapshots` fallback. PR #4 base capture loop requires server restart before post-merge dense rows appear.

## SPY
- Price series: `snapshots` · replay rows: `snapshots`
- Decline 2026-06-17 12:43:48 ET → 2026-06-17 13:20:26 ET (36.6 min, seg_ret=-0.00084)
- Decline 2026-06-17 13:45:37 ET → 2026-06-17 14:19:14 ET (33.6 min, seg_ret=-0.002149)
- Decline 2026-06-17 14:40:02 ET → 2026-06-17 15:14:21 ET (34.3 min, seg_ret=-0.002605)
- Decline 2026-06-17 15:00:44 ET → 2026-06-17 15:56:05 ET (55.4 min, seg_ret=-0.007193)
- Primary: **valid_forecast_explainability_gap**
- Payloads fresh in decline: False
- LONG-during-decline samples: 30
- Horizon 1c hit rate: 0.7188
- Classifications: {'VALID_REVERSAL_FORECAST': 11, 'VALID_MEAN_REVERSION_FORECAST': 2, 'MISSING_PRICE_INTEGRITY_GUARD': 6, 'MODEL_DIRECTION_DRIFT': 4, 'INSUFFICIENT_EVIDENCE': 1}

## QQQ
- Price series: `snapshots` · replay rows: `snapshots`
- Primary: **None**
- Payloads fresh in decline: None
- LONG-during-decline samples: 0
- Horizon 1c hit rate: None
- Classifications: {}
- Note: no timeline samples in decline intervals

## IWM
- Price series: `snapshots_1m_normalized` · replay rows: `snapshots_1m_normalized`
- Primary: **None**
- Payloads fresh in decline: None
- LONG-during-decline samples: 0
- Horizon 1c hit rate: None
- Classifications: {}
- Note: no timeline samples in decline intervals
