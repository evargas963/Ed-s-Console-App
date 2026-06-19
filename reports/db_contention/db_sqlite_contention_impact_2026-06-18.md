> **Classification:** Audit Report | **Scope:** SQLite contention impact on UI/data freshness

**Branch:** `audit/db-sqlite-contention-impact`
**Date/session audited:** 2026-06-18 (offline_static + log scrape)

## Operating stance

SQLite locked but eventually recovered is NOT acceptable without measurement, operator surfacing, and reduction — per Card Trust Contract

## Lock wait evidence

- sqlite_lock_wait_count: **0**
- sqlite_lock_wait_total_ms: **0.0**
- sqlite_lock_wait_max_ms: **0.0**
- operations: `{}`
- tickers: `{}`
- threads: `{}`

## Database locked evidence

- sqlite_database_locked_count: **0**
- sqlite_tier1_fail_count: **0**
- sqlite_busy_retry_count: **0**

## Classifications

- `DELAYED_NORMALIZATION_RISK`
- `INSTRUMENTATION_GAP`
- `TRANSPORT_FRESHNESS_RISK`
- `UI_DEGRADED_STATE_MISSING`

## Impact summary

**1_lock_wait_producers:** EdDB._tier1_snapshot_write threading lock + sqlite busy/locked retries on insert_snapshot and upsert_1m_bars

**2_database_locked_producers:** sqlite3.OperationalError after SQLITE_BUSY_MAX_RETRIES exhausted; also calibration writer, normalized materialize, non-tier1 writers without tier1 lock

**3_read_vs_write:** writes: ['insert_snapshot', 'upsert_1m_bars']; reads: Tier C similarity/history SELECTs, observability probes — fresh connection per call

**4_lock_wait_vs_stale:** NOT PROVEN offline — lane STALE driven by quote-ahead / gen-behind / pending analytics; no timestamp join to sqlite_tier1_lock_wait in production buffers

**5_lock_wait_vs_loading:** NOT PROVEN offline — LOADING/ANALYTICS… driven by Tier C pending; DB wait may extend duration but is not measured on client

**6_lock_wait_vs_ticker_switch:** NOT PROVEN offline — switch diag lacks sqlite_lock_wait_ms field

**7_tier_c_delay:** RISK: server comments + audit/ui-transport note Tier C _fetch_state blocked on DB; get_analytics_state offloads to thread pool but still waits on SQLite

**8_missed_snapshots:** PROVEN only if sqlite_tier1_fail / database is locked in logs; retries may mask gaps

**9_delayed_normalization:** RISK: normalized_training_sync cross-process lock + long materialize can lag snapshots

**10_calibration_gaps:** RISK when ED_CALIBRATION_LOG=1 — writer retries busy/locked then may skip silently

**11_errors_swallowed:** ["calibration writer: retries then skip row", "many server streaming catches log.debug only", "tier1_fail re-raises after log.error"]

**12_ui_surfaces_db:** operator_db_degraded_surface=False — STALE/LOADING do not cite DB

**13_write_frequency:** Base capture ~1/min/ticker concurrent; UI path throttled per-minute; Tier C writes on refresh

**14_shared_writer_contention:** ["base_money_path_logger (SPY/QQQ/IWM quote-only inserts)", "background_logger / UI-active ticker capture", "Tier C _fetch_state (DB reads + optional snapshot write)", "SSE / REST analytics cache refresh", "normalized_training_sync materialize (cross-process lock)", "calibration_decision_log append (when ED_CALIBRATION_LOG=1)"]

**15_wal_mode:** True

**16_busy_timeout:** 2000

**17_batching:** one-row insert_snapshot; upsert_1m_bars batched per bar batch

**18_long_read_transactions:** Reads use per-call connections; materialize may hold write lock longer

**19_background_connections:** ThreadPoolExecutor base capture + analytics executor + logger threads

**20_operator_should_see:** Explicit DB DEGRADED / SQLITE SLOW chip + /api/diagnostics/sqlite-contention; not present on cards today

**classifications:** DELAYED_NORMALIZATION_RISK, INSTRUMENTATION_GAP, TRANSPORT_FRESHNESS_RISK, UI_DEGRADED_STATE_MISSING

## Bugs proven

- No operator-facing surface names SQLite/DB contention (STALE/LOADING are transport/analytics)
- Code path: Tier C + snapshot writes share SQLite file — contention can delay analytics bundle

## Bugs not proven

- Lock wait timestamps causally drive STALE pill (needs correlated RTH capture)
- Lock wait timestamps causally extend LOADING duration (needs switch diag + server metrics join)
- Missed snapshot rows from contention (needs insert outcome audit vs expected cadence)
- Calibration log gaps solely from SQLite (needs ED_CALIBRATION_LOG=1 window)
- Any live contention in this offline audit run — log scrape may be empty

## Instrumentation gaps

- No client join between STALE/LOADING and sqlite_lock_wait timestamps
- switch diag schema lacks db_lock_wait_ms
- Historical logs required for offline proof — empty scrape ≠ clean bill of health

## Live RTH validation required

- RTH: ED_SWITCH_TIMING=1 + scrape server log for sqlite_tier1_* while switching SPY→NVDA→SPY
- Correlate lane STALE chip timestamps with sqlite_contention_metrics_snapshot() deltas
- Measure Tier C _pipeline_ms p95 during concurrent base capture (SPY/QQQ/IWM)
- Compare snapshots/minute for SPY vs logger_stats during lock-wait bursts
- GET /api/diagnostics/sqlite-contention every 1s during stress — verify counters move
- If calibration enabled: row count/min vs decision_generation_id advance during lock events

## Recommended fix branches

- `fix/db-sqlite-contention-surface` — Operator-visible DB degraded chip + payload field per Card Trust Contract §8
- `fix/db-tier1-write-isolation` — Reduce tier-1 lock hold time / separate read replica if impact proven live
- `fix/ui-transport-guest-switch-sla` — Guest switch SLA after DB contention measured on switch diag
- `fix/card-price-conflict-explainability` — Reason classes — must not attribute STALE to fusion when DB is root cause

## Card Trust Contract tie-back

docs/CARD_TRUST_CONTRACT.md §8 freshness; §13 must not imply STALE=model wrong

## Prior observations (not standalone proof)

- sqlite_tier1_lock_wait op=insert_snapshot ticker=SPY wait_ms=748.6 thread=ed-base-money-path-logger
- sqlite_tier1_ok op=insert_snapshot ticker=SPY attempts=1 exec_ms=33.5 lock_wait_ms_total=748.6
- sqlite3.OperationalError: database is locked
- STALE pills intermittent; LOADING sometimes long; ticker switch sometimes slow