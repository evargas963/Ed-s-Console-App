# ACTIVE_PROGRAM.md — the current work, in order

The one record of operator-directed work: what is in flight, queued or blocked. The design every
item is built to is `docs/DATA_FLOW.md`; where code lives is `docs/ARCHITECTURE.md`. Rows leave this
file when they finish (git keeps them). The first rule is simple: the simplest plan that fits the
design, with nothing kept that has no job. Plan approved by the operator 2026-09-26.

Status values: `NEXT` | `IN PROGRESS` | `QUEUED` | `BLOCKED` | `OPERATOR`.

## Phase 1 — restore and stabilize

| ID | Status | Work item |
|---|---|---|
| P1-6 | QUEUED | **Fallback register.** The OPEN rows of `governance/fallback_register.md`, fixed. |
| P1-7 | QUEUED | **Governance cut** (measured 2026-09-27). A check, register or document is consolidated only after confirming what replaces it covers what it covered. Candidates: the host scripts no job runs (branch `rehab/host-jobs`, 2026-09-26, stale: redo on main — the console liveness and RTH completeness checks, the retrain and scoreboard launchers, the host manifest export); the 45 checks of `tools/check_institutional_correctness.py` (62 violations stand on main; CI blocks only new ones); `level_faucets.json` (`computation_registry.json` stays: since 2026-09-27 it sees each of its 9 fields at its producer); `governance/root_cause_log.md` (594 lines, 53 violations of its own rules); `unproven_register.md`; `fallback_register.md` after P1-6; `OPERATOR_DECISION_REGISTER.md`; `host_scheduled_jobs.md` (lists tasks that do not exist); the tests of what goes (75 of 278 test files test tools or governance). Kept: the hooks that block destructive git and edits to the production checkout. |
| P1-8 | QUEUED | **CI clean-up**: dead tests and tools; the E2E suite's fixed sleeps (35.6 s of 122 s); the hardening job's unneeded installs (torch and others); the flaky console-gamma-controls QQQ test. |
| LIVE-0928 | QUEUED | **Monday 2026-09-28 session checks**: the 9:30 and 4:15 chain captures and their log lines; Schwab's gamma against the model curve in session (the flip's clock); IV units; TIMESALE_EQUITY re-tested; IEX prints inside NYSE_BOOK; the zeros taken as sent (operator ruling 2026-09-27: open interest, price and IV 0 are 0) measured in session against the weekend's ($SPX 2026-09-14: 19,440 of 19,520 contracts OI 0). |
| DATA-SYN | OPERATOR | **Fabricated bars in `price_bars_1m`**: 14,491 rows with source `synthetic_interior_grid_repair_v1` (14,490, 47 tickers, 2026-03-24 to 2026-07-17) and `synthetic_anchor_coverage_pad_v1` (1); no code writes them; every bar reader reads them. Deleting data is the operator's. |

## Phase 2 — the rest of the design, then decomposition

| ID | Status | Work item |
|---|---|---|
| P2-2 | QUEUED | **The levels producer in its own process** (DATA_FLOW decision 2); results pushed. First measured against the simpler complete design (levels computed in the console, off the request path): page response during a board sweep, failure isolation, who owns the process. Not built unless that proves it necessary; the result goes to the operator. Ships with its check: the console imports no calculation module. |
| P2-3 | QUEUED | **Everything pushed to the browser**: bars, order flow, liquidity; every panel reads through one store; the page has no refresh timer (none reads `/api` on a closed market); one push connection. Ships with its check: a page timer that reads `/api` fails. |
| P2-4 | IN PROGRESS | **The standalone pages** (operator 2026-09-27: options into the console, chart features kept, desk dropped; /exposure undecided). Done: /options (Chain columns, in-the-money and ladder served; Flow feed health served); /desk, its five `/api/desk/*` research routes, the desk store module and the console's empty Desk / Research workspace deleted (the desk tables go in P2-DB3). Next: /chart's features moved into the Trade Desk, each calculation served first (done: every terrain level and the ±1σ move on the Market Map; the walls' value-area bands and dealer lean; 3m, line mode, levels beyond the range pinned at the edge; proximity alerts from the one served near-spot rule; the FORCES split on the Options card; GEX by Strike's change vs yesterday). /chart deleted with the routes and files only it used (/api/terrain/scorecard, /api/level_crosses, /static/rth_clock_authority.js, forces_provenance.js). Left: /exposure (operator decision pending). |
| P2-5 | QUEUED | **db.py**: delete the methods and tables only the deleted ML stack used, and `ml_horizon`, `movement_target_threshold`, `horizon_outcomes`, `decision_record`, `execution_identity`, `calibration/schema.py`; move what remains (bars, level history, enrollment, connection) to `daemon/`. |
| P2-6 | QUEUED | **server.py**: the chain fetch to `daemon/`, the levels loop and gamma-surface projection to `producer/`, the routes and startup to `console/`. |
| P2-7 | QUEUED | **The other large files**: liquidity_value_engine.py, app/options/order_flow/streaming.py and engine.py, math_exposure_core.py, ed-core.js, ed-gamma.js — cut what has no job, move each part to the process that runs it. |
| P2-DB3 | QUEUED | **One offline maintenance window, after P2-5** (sizes measured 2026-09-26): copy `ed_console.db` whole; stop the app; drop the ML tables (~49 GB) and the bar leftovers (`price_bars_1m_quarantine`, `price_bars_1m_staging`); in `stream_capture.db`, `stream_prints_raw` (no writer since the Alpaca print feed was removed 2026-09-24; Schwab refuses trade prints); compress the plain-text chain rows; move the morning chains into `complete_chain_captures` and drop the morning table; VACUUM; restart and check. Rows captured while the market was closed are deleted only on the operator's word. The codec's plain-text branch and the backfill tool are deleted after. |
| P2-DB4 | QUEUED | **One database, `ed_console.db`** (operator 2026-09-26): the stream tables move into it; the daemon's writer writes every table, including the console's (bars, level crosses, daily OI/IV, the ticker board, desk facts). |
| P2-DB5 | QUEUED | **The console reads read-only.** Ships with its check: a database write outside the one writer fails. |
| P2-8 | QUEUED | **Docs pass**: every document matches the tree. Known stale: OPEN_ITEMS.md; DATA_STEWARDSHIP.md, PIPELINE_QUALITY.md, PROMOTION_POLICY.md, MODEL_RESTORE_LOG.md, TRAINING_AND_MAINTENANCE.md (describe deleted systems); `docs/` (82 files, 46 about deleted work). |

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

## Operator host steps

| ID | Item |
|---|---|
| RECON-02 | `Trading/_disk_cleanup_quarantine_20260716` (53 GB, manifest read 2026-09-26): about 50 GB is old copies of the database (2026-05-27, 06-10, 06-11 and a 16 GB `db_backups` folder) and about 3 GB old report copies. They are the only database backups, so they are purged, on the operator's word, only after the P2-DB3 copy is made and verified. |
| CALENDAR-2029 | Add the NYSE 2029 holidays and early closes to time_et (US_EQUITY_CALENDAR_YEARS covers 2025-2028) when the NYSE publishes them, before 2029-01-01. From that date the calendar treats every uncovered day as closed (by design: never a guessed session), so the app would stop capturing and refreshing. Checked 2026-09-27: not yet published. |
| RUNTIME-SEPARATION | Move the runtime state (database, logs, token, diagnostics) out of the production checkout into a runtime folder. |
