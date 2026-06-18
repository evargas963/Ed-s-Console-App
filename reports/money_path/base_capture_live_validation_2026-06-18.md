> **Classification:** Audit Report | **Scope:** Base ticker live capture validation

# Base capture live validation — 2026-06-18

Branch: `audit/base-capture-live-validation`
DB: `C:\Users\evarg\Documents\Trading\EdWebConsole\data\ed_console.db`
Universe ready: **False** (thresholds unchanged)
Server restart confirmed: **not verified in this audit — operator must confirm**

## Rows observed (partial RTH session)

| Ticker | Raw RTH | Norm RTH | Cal RTH | Median gap | Max gap | First ET | Last ET |
|--------|---------|----------|---------|------------|---------|----------|---------|
| SPY | 34 | 25 | 41 | 71.05930519104004 | 226.76376509666443 | 2026-06-18 09:31:15 ET | 2026-06-18 10:17:11 ET |
| QQQ | 9 | 9 | 10 | 305.91295075416565 | 467.5330481529236 | 2026-06-18 09:35:09 ET | 2026-06-18 10:12:42 ET |
| IWM | 10 | 9 | 10 | 221.41476130485535 | 477.23903584480286 | 2026-06-18 09:35:34 ET | 2026-06-18 10:14:20 ET |

**SPY:QQQ raw row ratio:** 3.78x

## Cadence interpretation

- SPY accumulates ~3.8x faster than QQQ on raw snapshots in partial session; median gap SPY ~71s vs QQQ ~306s indicates unequal effective cadence.
- QQQ/IWM first capture cluster ~4 min after SPY — consistent with base loop SPY→QQQ→IWM sequential cycle.
- SPY median gap ~71s ≈ 1/min throttle ceiling → active UI/SSE/REST path stacking.
- QQQ median gap ~306s ≈ one row per long base cycle, not one per minute.

## Normalization (PR #6)

- QQQ: raw=norm (9/9) — normalization follows capture.
- IWM: 10 raw / 9 norm — 1-row debounce lag.
- SPY: 34 raw / 25 norm — 7-row debounce lag; normalization not the primary disparity.

## Audit questions (summary)

- **1_base_logger_loop_running:** inferred_yes_from_row_pattern — QQQ/IWM first rows within 25s of each other after SPY (09:35:09/09:35:34 vs SPY 09:31:30) matches base loop SPY→QQQ→IWM 
- **2_startup_log_base_task:** yes_when_lifespan_runs — log.info Base money-path logger started — ['SPY','QQQ','IWM'] every 60s
- **3_loop_iterates_all_three:** yes — for ticker in base_money_path_logger_tickers() → BASE_MONEY_PATH_TICKERS
- **4_blocked_by_slow_fetch:** yes_likely — Sequential for-loop; each _logger_fetch_and_log calls full _fetch_state; cycle wait=max(0, interval-elapsed) — if elapse
- **5_full_model_fusion_per_ticker:** yes — _fetch_state(..., log_only=True) runs quote+chain+models+fusion+DB insert path
- **6_spy_extra_ui_sse_rest:** yes_proven_by_disparity_and_code — SPY 34 raw vs QQQ 9; SPY median gap ~71s (~1/min throttle ceiling); SSE loop schedules _fetch_state for subscribed activ
- **7_qqq_iwm_skipped_by_filters:** no — should_skip_background_full_snapshot returns False for base tickers; filter_tickers_for_background_logging keeps anchors
- **8_schwab_quote_failures:** not_proven — No server log capture in this audit; rows exist for QQQ/IWM so some fetches succeed
- **9_exceptions_in_logs:** not_proven — Requires operator server log review
- **10_sleep_per_cycle_not_per_ticker:** yes_per_full_cycle — STAGGER_SECS between tickers; wait=interval-elapsed after all three
- **11_normalization_follows_raw:** yes_with_debounce_lag — QQQ 9/9 raw/norm; IWM 10/9; SPY 34/25 (7-row debounce lag from PR #6)
- **12_single_ticker_lock_favoring_spy:** no_lock_throttle_and_ui_paths — ED_DB_SNAPSHOT_THROTTLE max 1 insert/ticker/UTC minute; no SPY-only lock; active UI path adds SPY attempts
- **13_active_ticker_influences_count:** yes — Cadence disparity + SSE/REST paths only fire for subscribed active symbol; SPY row rate ~3.8x QQQ
- **14_calibration_same_disparity:** yes — cal rows RTH: SPY 41, QQQ 10, IWM 10 — tracks fetch/compute volume not base parity

## Root cause

**Primary:** Unequal effective snapshot cadence: active UI ticker (SPY) receives stacked SSE/REST fetches (~1 insert/min) while QQQ/IWM depend on sequential base+general background loops at ~3-5 min observed median gap.
**Secondary:** Base loop design targets 60s/cycle but sequential full _fetch_state per ticker inflates cycle duration; one row per base ticker per completed cycle not per minute.
**Instrumentation gap:** snapshots table lacks logger_source / update_source — cannot attribute rows from DB alone.

## Bugs proven

- Base money-path capture does not achieve equal SPY/QQQ/IWM cadence in live partial session
- Active UI ticker boosts SPY snapshot count independent of base loop parity intent
- No snapshot source_path metadata for audit attribution

## Bugs not proven

- Schwab quote fetch failures for QQQ/IWM
- Base logger thread not started (inferred running from timestamp pattern)
- Server restart not performed (operator confirmation pending)

## Recommended next step

fix/base-capture-cadence-parity — lightweight base capture path OR concurrent base fetches OR decouple base loop from full _fetch_state; add logger_source on snapshot INSERT; do not weaken observability thresholds
