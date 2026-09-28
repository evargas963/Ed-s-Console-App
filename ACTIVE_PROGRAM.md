# ACTIVE_PROGRAM.md — the current work, in order

The one record of operator-directed work: what is in flight, queued or blocked. The design every
item is built to is `docs/DATA_FLOW.md`; where code lives is `docs/ARCHITECTURE.md`. Rows leave this
file when they finish (git keeps them). The first rule is simple: the simplest plan that fits the
design, with nothing kept that has no job. Plan approved by the operator 2026-09-26.

Status values: `NEXT` | `IN PROGRESS` | `QUEUED` | `BLOCKED` | `OPERATOR`.

## Phase 1 — restore and stabilize

| ID | Status | Work item |
|---|---|---|
| P1-9 | QUEUED | **Enforce the code rules** (AGENTS.md "Before writing code", "Authority"), each starting with no exceptions: `.gitattributes` makes every file LF, normalized in one commit; ruff forbids imports outside the module top (PLC0415); one formatter per format (Central Time: `time_et.ct_label`, 2026-09-27); typed records for values crossing modules; history prose out of code. Time passed as an input (`now`), with the conftest session-clock stand-in deleted, is built with P2-3's remaining part, which rebuilds the live price path (36 call sites of `resolve_spot`, `live_spot`, `price_row` and the live rule today). |
| P1-6 | QUEUED | **Fallback audit 2026-09-27**: after P2-3 and P2-1, the rows of `governance/fallback_register.md` still in the tree are fixed at their source (rule 1); rows in deleted code close with it. |
| P1-8 | QUEUED | **CI clean-up**: dead tests and tools; the E2E suite's fixed sleeps (35.6 s of 122 s); the hardening job's unneeded installs (torch and others); the flaky console-gamma-controls QQQ test. |
| LIVE-SESSION | QUEUED | **Next-session checks** (not done on 2026-09-28; each is runtime evidence only for what it observes): an off-board ticker kept open on the Liquidity workspace for more than 5 minutes is refreshed each cycle (its levels' as-of advances), and a board ticker the same; the heatmap stays live through RTH (ONE-05 fix); AM-settled $SPX monthly contracts stop pricing at the 09:30 open on 2026-10-16; the 9:30 and 4:15 chain captures and their log lines; Schwab's gamma against the model curve in session (the flip's clock); IV units; TIMESALE_EQUITY re-tested; IEX prints inside NYSE_BOOK; the zeros taken as sent (operator ruling 2026-09-27: open interest, price and IV 0 are 0) measured in session against the weekend's ($SPX 2026-09-14: 19,440 of 19,520 contracts OI 0); rule 5 both ways: a valid past observation on screen shows its source, time and a label saying so, and none feeds current logic; the price reads LIVE from 04:00 ET and MARKET CLOSED with the last trade's time from 20:00 ET, across the board; the charts' last completed bar advances each minute about 3 s after it closes (Schwab CHART_EQUITY), each candle equal to Schwab's bar, and the chart's LAST line moves with the header's price on every update, across the board; each Schwab book (NYSE_BOOK, NASDAQ_BOOK) arriving and shown under its own venue, across the board. |
| DATA-SYN | OPERATOR | **Fabricated bars in `price_bars_1m`**: 14,491 rows with source `synthetic_interior_grid_repair_v1` (14,490, 47 tickers, 2026-03-24 to 2026-07-17) and `synthetic_anchor_coverage_pad_v1` (1); no code writes them; every bar reader reads them. Deleting data is the operator's. |

## One producer — the 2026-09-28 audit (rule 3, rule 6)

Each row is a second copy or a second computation found by the audit of in-code ownership claims
(18 of 24 false) and of per-ticker logic. It is fixed by deleting down to one producer, with a
behavior test that fails if the second one returns, and the false claim comments removed. Done:
the console's copy of the live price (its spot is the daemon's price row; test
`test_the_console_spot_is_the_daemons_price_row_and_the_console_keeps_no_copy`) and the on-screen
spot (Key Levels = header, #372).

| ID | Status | Work item |
|---|---|---|
| ONE-02 | QUEUED | Equity last price and size kept a second time in the console's order-flow tape (`state.py` tape and receive log). |
| ONE-03 | QUEUED | Feed liveness judged in both processes: the daemon applies its own heartbeat to its price rows (`live_ui.beat`), and the console applies the pushed copy again (`feed_live_for`); one rule since ONE-15, two places it runs. |
| ONE-04 | QUEUED | Equity books: the console's order-flow copy and the database copy read by the Book Heatmap (`history.book_heatmap_for_ticker`, a live screen reading the DB). |
| ONE-05 | QUEUED | Option quotes: the options tape reads the database copy (`history.tape_rows_for_symbol`, a live screen reading the DB) beside the order-flow copy. (The merge-by-time of streamed fields into the chain, which flipped the heatmap to stale, is fixed: the stream owns a live contract's fields.) The MU heatmap route took 10-21 s under load (3.7 MB). |
| ONE-06 | QUEUED | 1-minute bars in two databases, and live charts and levels reading `price_bars_1m` (with P2-DB4). |
| ONE-07 | QUEUED | Option chains fetched by two processes with two writers to `ed_console.db` (with P2-1). |
| ONE-12 | QUEUED | Trade side: history's quote rule beside the live tick rule (with the trade-side decision, directive 3). |

## Phase 2 — the rest of the design, then decomposition

| ID | Status | Work item |
|---|---|---|
| P2-1 | QUEUED | **The daemon fetches the chain** (DATA_FLOW decision 1); the console's chain fetch is deleted. Ships with its check: a Schwab call outside the daemon fails. |
| P2-2 | QUEUED | **The levels producer in its own process** (DATA_FLOW decision 2); results pushed. First measured against the simpler complete design (levels computed in the console, off the request path): page response during a board sweep, failure isolation, who owns the process. Not built unless that proves it necessary; the result goes to the operator. Ships with its check: the console imports no calculation module. |
| P2-3 | IN PROGRESS | **Everything pushed to the browser**, two push connections (operator 2026-09-27): the daemon pushes prices and bars, the console pushes what changed. Part 1 (2026-09-27): the console's `/api/changes` (`push_changes.py`) pushes `levels`, `chain`, `flow`, `liquidity` and the session label; every page timer that read `/api` is deleted (the 3 s/12 s poll, the Chain view's 60 s poll, `/api/session`), with its check (Playwright: a minute with no push makes no `/api` read). Left: the daemon pushes the 1-minute bars (the charts read `/api/bars1m` after a `liquidity` push today); the option-contract demand lease re-sent every 30 s (`ed-stream.js`) ends with the page's connection instead; time passed as an input (`now`) on the live path, with the conftest session-clock stand-in deleted (P1-9). |
| P2-5 | QUEUED | **db.py**: move what remains (bars, level history, enrollment, connection) to `daemon/`. Part 1 (2026-09-27) deleted the snapshot writer, the outcome-label pipeline, the snapshot column migrations and the modules only they used (ml_horizon, movement_target_threshold, horizon_outcomes, decision_record, execution_identity, the calibration schema, snapshot_access, timeframe_config); the bar writer takes only the streamed Candle bars and refuses and counts a bar off the minute grid. |
| P2-6 | QUEUED | **server.py**: the chain fetch to `daemon/`, the levels loop and gamma-surface projection to `producer/`, the routes and startup to `console/`. |
| P2-7 | QUEUED | **The other large files**: liquidity_value_engine.py, app/options/order_flow/streaming.py and engine.py, math_exposure_core.py, ed-core.js, ed-gamma.js — cut what has no job, move each part to the process that runs it. |
| P2-DB3 | QUEUED | **One offline maintenance window, after P2-5** (sizes measured 2026-09-26): copy `ed_console.db` whole; stop the app; drop the ML tables (~49 GB; no code creates, writes or reads them since P2-5 part 1: `snapshots_1m_normalized`, `model_accuracy`, `gamma_surface_last_valid`, `ed_schema_flags`, `confluence_quote_ticks`, `logging_universe_eviction_log`, `calibration_decision_log`, `production_decision_records`, `model_execution_identities`, `decision_persistence_ledger` and the identity triggers on them and on `snapshots`; `snapshots` and `iv_daily`, whose DDL left with P1-7), the bar leftovers (`price_bars_1m_quarantine`, `price_bars_1m_staging`), the desk tables and option_chain_accrual (no writer or reader since the standalone pages were deleted, 2026-09-27); in `stream_capture.db`, `stream_prints_raw` (no writer since the Alpaca print feed was removed 2026-09-24; Schwab refuses trade prints); compress the plain-text chain rows; move the morning chains into `complete_chain_captures` and drop the morning table; VACUUM; restart and check. Rows captured while the market was closed are deleted only on the operator's word. The codec's plain-text branch and the backfill tool are deleted after. |
| P2-DB4 | QUEUED | **One database, `ed_console.db`** (operator 2026-09-26): the stream tables move into it; the daemon's writer writes every table, including the console's (bars, level crosses, daily OI, the ticker board). |
| P2-DB5 | QUEUED | **The console reads read-only.** Ships with its check: a database write outside the one writer fails. |
| P2-8 | QUEUED | **Docs pass**: every statement in the remaining documents (README, AGENTS, ACTIVE_PROGRAM, `docs/`) matches the tree. The documents about deleted systems left with P1-7. |

## Phase 3 — the placeholders on screen (after Phase 1 and 2)

| ID | Placeholder | What fills it |
|---|---|---|
| TU-05 | Options → Multi-Map; Key Levels → Vanna Support, Charm Resistance | vanna/charm exposure in dollar units per strike × expiry |
| TU-08 | Key Levels → Zero Gamma, Volatility Trigger | regime dead-zone around the flip |
| TU-11 | Options → Multi-Map | skew and term fields |
| TU-06, 07, 09, 10, 12 | none yet | call−put IV spread and implied 1-day move, ΔOI flow, GEX/ADV normalization, external GEX benchmark, intraday DDOI (meaning confirmed from its source before building) |
| LP-01 | Liquidity | steps 1–3 are in `liquidity_models.py` / `liquidity_value_engine.py` (`/api/liquidity-snapshot`); left: check the raw levels show on the Trade Desk chart |

## Operator designing — nothing is built until the operator decides

| ID | Item |
|---|---|
| RESEARCH | Quant formulas that decide stock, calls, puts or spreads, and research run on the stored chain history. Where it lives (Trade Desk or its own screen) is undecided. |
| PLAN | Trade Desk → Plan. |
| PORTFOLIO | Portfolio / Risk: needs the operator's positions from Schwab's account API, fetched by the daemon. |
| RATE-DIV | The risk-free rate and dividend yield Schwab sends with each chain (stamped on every contract since #326), used or not by the model curve, vanna and charm. |
| PIN-FLOOR | The pin score's $50,000 GEX floor (binds for MTA, NBIX, TSL): keep, change or remove, after research. |
| VOL-GAMMA | Option volume in the gamma read (e.g. volume-weighted gamma for same-day expiries). |
| UNSHOWN | Nine values the levels producer computes and `/api/terrain` serves are shown by no screen and read by no code (found 2026-09-28): `absolute_gamma_strength_pct`, `absolute_gamma_gex_dollars`, `absolute_gamma_oi`, `book_oi_total`, `pin_candidate_blockers`, `gsf_state`, `zero_dte_gamma_share_pct`, `rr_25d`, `vanna_agg`. Show each or delete it. |

## Operator host steps

| ID | Item |
|---|---|
| RECON-02 | `Trading/_disk_cleanup_quarantine_20260716` (53 GB, manifest read 2026-09-26): about 50 GB is old copies of the database (2026-05-27, 06-10, 06-11 and a 16 GB `db_backups` folder) and about 3 GB old report copies. They are the only database backups, so they are purged, on the operator's word, only after the P2-DB3 copy is made and verified. |
| CALENDAR-2029 | Add the NYSE 2029 holidays and early closes to time_et (US_EQUITY_CALENDAR_YEARS covers 2025-2028) when the NYSE publishes them, before 2029-01-01. From that date the calendar treats every uncovered day as closed (by design: never a guessed session), so the app would stop capturing and refreshing. Checked 2026-09-27: not yet published. |
| RUNTIME-SEPARATION | Move the runtime state (database, logs, token, diagnostics) out of the production checkout into a runtime folder. |
