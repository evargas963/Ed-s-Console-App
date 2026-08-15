# DB validity audit v1 — non-trading-day contamination, whole database

**Ordered by:** operator, 2026-08-01 ("we need to do a full audit of the db and the validity of
the data with respect to its accuracy and the day that it should collect/persist").
**Method:** every table's time/date column re-dated in **ET** via `time_et.et_date_str_from_ts_utc`
and judged by `time_et.is_trading_day_et` (the calendar authority). UTC dating is not used —
a Friday 20:00 ET bar lands on Saturday in UTC, and the first pass of this very audit made that
mistake (see "Audit's own errors" below).
**Reproduce any row count:**
`.venv/Scripts/python.exe -c "import sqlite3,time_et; from collections import Counter; c=sqlite3.connect('file:data/ed_console.db?mode=ro',uri=True); rows=c.execute('select ts_utc from snapshots').fetchall(); print(sum(1 for (t,) in rows if not time_et.is_trading_day_et(time_et.et_date_str_from_ts_utc(float(t)))))"`
(swap table/column per the matrix).

## The matrix (measured 2026-08-01)

| Table | Rows | On non-trading ET dates | % | Verdict |
|---|---|---|---|---|
| price_bars_1m | 1,484,957 | **92,195** (20,981 with volume>0) | 6.2% | **DEFECT — RC-177** |
| snapshots | 320,464 | **49,011** (33,929 labeled `rth`) | 15.3% | **DEFECT — RC-178** |
| snapshots_1m_normalized | 210,921 | **36,979** | 17.5% | **CONTAMINATED — feeds studies (RC-58/RC-178)** |
| greeks_recomputed_v1 | 160,489 | **26,905** | 16.8% | contaminated downstream of snapshots |
| confluence_quote_ticks | 2,247,801 | **394,048** | 17.5% | weekend console sessions; display-only path |
| production_decision_records | 173,268 | **39,943** | 23.1% | weekend decisions persisted into the ledger |
| option_chain_morning_full | 401 | **72** (et_dates 07-19, 07-25, 07-26 — weekends) | 18.0% | weekend captures stamped as sessions |
| option_chain_accrual | 2,604 | 0 | 0% | CLEAN (accrual window is ET-minute gated) |
| level_crosses | 9,212 | 0 | 0% | CLEAN |
| world_finra_short_volume | 48,565 | 0 | 0% | CLEAN |
| world_cftc_tff | 189 | 0 | 0% | CLEAN |
| world_earnings | 6,595 | 3 | 0.05% | vendor noise; 3 weekend-dated announcements |
| desk_facts | 55,235 | 3 | 0.01% | inherited from world_earnings rows above |
| world_vol_index | 28,438 | — | — | **AUDIT ARTIFACT** — dates are `MM/DD/YYYY` and reach 1990; the calendar authority fails closed on uncovered years. Not a data defect finding; format+coverage prevent the question from being asked. |
| world_dix | 3,826 | — | — | **AUDIT ARTIFACT** — ISO dates but history reaches 2011, outside covered calendar years. Same non-finding. |

## price_bars_1m breakdown (the RC-177 defect)

By writer: `synthetic_interior_grid_repair_v1` **62,553** · `schwab_1m_accumulator_sqlite`
**25,780** · `schwab_pricehistory` **3,854** · gap_fill/edge_carry 8.
Worst dates: 2026-05-25 (Memorial Day) 11,898 · 2026-04-12 10,256 · 2026-04-11 9,978 ·
July 4th weekend (07-03/04/05) 8,574. Fifty tickers affected. 30 distinct non-trading dates
back to 2026-02-22.

The July 4th sample proves fabrication rather than mislabeling: every one of the 8,548
weekend-ET rows on 07-03..07-05 carries source `synthetic_interior_grid_repair_v1` — a repair
tool "filled" a gap that was actually a market holiday.

## RTH completeness census (added 2026-08-01, operator question: "are RTH rows missing?")

Scope: every (ticker, trading day) where the ticker logged at least one RTH bar; expected
minutes from 09:30 to that date's session close (half-days honoured via
`session_close_mins_for_et_date`).

| Quantity | Count | % of expected |
|---|---|---|
| Session-minutes expected | 1,066,650 | — |
| Minutes with a row | 967,269 | 90.68% |
| **TRUE HOLES — no row at all** | **99,381** | **9.32%** |
| **FAKE FILLS — synthetic row occupying a real minute** | **7,451** | 0.70% |

Worst tickers by holes: TSL 7,732 · PSCI 5,021 · PLTR 2,837 · PCG 2,833 · RKLB 2,825 ·
SMCI 2,765 · NFLX 2,752 · MU 2,746.

**Vendor floor, MEASURED 2026-08-01 (binary search over live `pricehistory` calls):** Schwab 1m
history starts at **2026-06-17** — ~45 days of reach (Feb/Mar/Apr/May windows all return HTTP
200 with 0 candles; 06-16 returns 0, 06-17 returns 34, 06-19 returns 758). The window SLIDES
DAILY: every day of delay pushes another day of holes past the floor forever.

| Split at the floor | Holes | Fake-filled | Disposition |
|---|---|---|---|
| **Recoverable (≥ 2026-06-17)** | **49,478** | **800** | **backfill NOW — 50,278 minutes, decaying daily** |
| Unrecoverable (< floor) | 49,903 | 6,651 | permanently empty; fakes quarantine |

**Answer to the operator's hypothesis:** the weekend rows did not displace RTH rows one-for-one
— they are bridge spillover — but the underlying suspicion is confirmed and larger: the repair
machinery fabricated data across closed periods while 99,381 genuine session minutes stayed
empty and 7,451 more were filled with fakes. **Backfill target = 99,381 + 7,451 ≈ 106,832 RTH
minutes**, fetched real from Schwab via the proven FP-10 machine. Known nuance: FP-18 measured
~7,724 clock-gap bars in (29s,60s] — some "holes" are jitter-displaced bars, and the backfill
reconciliation tolerance already handles that class; the census number is therefore an upper
bound on truly absent data. Reproduce:
`.venv/Scripts/python.exe` census script per the matrix note (same connection, group RTH minutes
per (ticker, ET trading date), diff against the session grid).

## Audit's own errors (kept per the fair-method clause)

1. First pass dated bars in **UTC** and reported five suspect dates; ET re-dating showed one of
   them (07-18) was entirely legitimate Friday-evening data. The corrected full-table number
   (92,195) comes from the ET pass only.
2. First pass reported world_vol_index "100%" and world_dix "89.9%" non-trading; both are
   format/coverage artifacts of the audit script, not data findings. A flawed check is more
   dangerous than no check — both numbers are retracted here by name.

## Dispositions (operator decisions needed)

1. **RC-177 rows (92,195 bars):** quarantine-move or flag — never silent deletion (stewardship
   rule). Reader-side containment is already live (`desk_store.is_rth_trading_ts`, RC-176), but
   every OTHER consumer of `price_bars_1m` still reads them.
   **Operator asked (2026-08-01): "can we backfill from Schwab instead?" Answer — partially,
   and the combination is better than either alone.** Schwab has NOTHING for the non-trading
   timestamps (the market was closed; there is no true bar for Saturday 10:00), so the 92,195
   weekend/holiday rows cannot be backfilled — only removed to quarantine. But the synthetic
   sources total **109,343** rows, of which **46,786 sit on legitimate trading days** — those
   were fabricated to fill real gaps, and THOSE can be replaced with vendor truth: the existing
   backfill machine (FP-10, `historical_backfill_enrolled_1m_v1`, 125,487 bars landed in its
   proven run) re-fetches the gap universe from Schwab, and every synthetic row where a vendor
   bar lands is retired. End state: zero fabricated bars anywhere — weekends quarantined because
   nothing real exists there, trading-day gaps refilled with real prints, residual unfillable
   gaps left HONESTLY EMPTY (an empty minute is true; an interpolated one is not). One check
   first: Schwab's 1m history depth must cover the oldest synthetic date (2026-02-22) —
   measured, not assumed, before the run is sized.
   **Sized by the census (2026-08-01): the backfill target is ≈106,832 RTH minutes — 99,381
   true holes plus 7,451 fake-filled — an upper bound pending jitter reconciliation. The weekend
   rows displaced nothing; they are removal-only.**
2. **RC-178 labeler:** `market_session` must consult the calendar, and the 33,929 `rth`-labeled
   weekend rows need relabeling or flagging.
3. **Weekend collector policy:** console runs on weekends by operator habit; collectors persist
   what they see. Either gate persistence on `is_trading_day_et`, or stamp a `non_session` flag
   so downstream can exclude mechanically. Studies protocol (OPEN_ITEMS "Validity") already
   requires exclusion either way.
4. world_vol_index date format (`MM/DD/YYYY`) should be normalized at ingest if that table is
   ever consumed by session-aware code.
