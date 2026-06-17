> **Classification:** Audit Report | **Scope:** Card direction integrity vs price movement (SPY/QQQ/IWM)

# Card direction integrity — 2026-06-16

DB: `C:\Users\evarg\Documents\Trading\EdWebConsole\data\ed_console.db`
Min decline window: 30 minutes

## Summary

- Decline intervals: 4
- Tickers with decline: SPY
- LONG-during-decline samples (any horizon): 3

## Base ticker observability

- **SPY**: PASS_BASE_OBSERVABILITY — norm_rows=368 cal_rows=499 (meets base RTH observability thresholds)
- **QQQ**: FAIL_SPARSE_SNAPSHOTS — norm_rows=19 cal_rows=19 (snapshot_rows_rth=19 normalized_rows_rth=19 below minimum 300; median_gap_seconds=1287.4 exceeds 90.0; max_gap_seconds=1604.4 exceeds 300.0)
- **IWM**: FAIL_SPARSE_SNAPSHOTS — norm_rows=19 cal_rows=19 (snapshot_rows_rth=19 normalized_rows_rth=19 below minimum 300; median_gap_seconds=1276.6 exceeds 90.0; max_gap_seconds=1604.5 exceeds 300.0)

## SPY
- Decline 2026-06-16 12:17:19 ET → 2026-06-16 12:47:03 ET (29.7 min, seg_ret=-0.00069)
- Decline 2026-06-16 12:40:11 ET → 2026-06-16 13:11:10 ET (31.0 min, seg_ret=-0.000252)
- Decline 2026-06-16 13:05:20 ET → 2026-06-16 13:46:04 ET (40.7 min, seg_ret=-0.000492)
- Decline 2026-06-16 14:38:10 ET → 2026-06-16 15:25:01 ET (46.8 min, seg_ret=-0.00081)
- Primary: **valid_forecast_explainability_gap**
- Payloads fresh in decline: False
- LONG-during-decline samples: 3
- Horizon 1c hit rate: 0.5312
- Classifications: {'VALID_REVERSAL_FORECAST': 2, 'MODEL_DIRECTION_DRIFT': 1}

## QQQ
- Primary: **None**
- Payloads fresh in decline: None
- LONG-during-decline samples: 0
- Horizon 1c hit rate: None
- Classifications: {}
- Note: no timeline samples in decline intervals

## IWM
- Primary: **None**
- Payloads fresh in decline: None
- LONG-during-decline samples: 0
- Horizon 1c hit rate: None
- Classifications: {}
- Note: no timeline samples in decline intervals
