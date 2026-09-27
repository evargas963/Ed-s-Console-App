# ACTIVE_PROGRAM.md — the current work, in order

The one record of operator-directed work: what is in flight, queued or blocked. The design every
item is built to is `docs/DATA_FLOW.md`; where code lives is `docs/ARCHITECTURE.md`. Rows leave this
file when they finish (git keeps them). The first rule is simple: the simplest plan that fits the
design, with nothing kept that has no job. Plan approved by the operator 2026-09-26.

Status values: `NEXT` | `IN PROGRESS` | `QUEUED` | `BLOCKED` | `OPERATOR`.

## Phase 1 — restore and stabilize

| ID | Status | Work item |
|---|---|---|
| P1-0 | NEXT | **Clean production.** Delete `docs/CARD_TRUST_CONTRACT.md` (it describes a UI that no longer exists; the freshness badges it asked for live in `ed-core.js`). The terrain quarantine ledger becomes log lines: delete the tracked `reports/terrain_quarantine_ledger.jsonl`, its environment override and the test machinery that guarded the tracked file. In production: discard the local edits to those two files and delete the untracked `RUN_COMPRESSION_BACKFILL.md` (its chain steps are P2-DB3; its ML steps die with the drop). Close PR #267 (a fix to the backfill tool for tables being dropped). |
| P1-1 | IN PROGRESS | **Chain history, and the screens after the close** (branch `rehab/chain-history`). The daemon captures the full chain (every expiry) of each board ticker every 30 minutes from 9:30 to the close ET plus a close capture 15 minutes after it (options on SPY, QQQ, IWM and the indexes trade until 4:15 PM), market days only, into `complete_chain_captures` in `ed_console.db`, compressed, one row per expiry, with Schwab's underlying price (DATA_FLOW decisions 5 and 7). The console stops writing chain captures and the morning chain; at startup it prices each board ticker's newest capture once, with that capture's price and time. `/api/terrain/strikes` and `/api/forces` read the previous market days from the same table; the strikes route's stand-in from the per-minute table is deleted. #303's saved files are deleted. The first capture is Monday 2026-09-28 09:30 ET; until then there is nothing to load. Checked on the running app. |
| P1-2 | IN PROGRESS | **Console noise + the page's one reader** (branch `rehab/host-jobs`): no per-request log lines, no idle terrain line; every panel reads through one store; no page timer reads `/api` on a closed market. Open: 8 pytest + 1 browser test failing; then full suites; the Trade Desk checked on the running app before merge. |

## Phase 2 — the rest of the design, then decomposition

| ID | Status | Work item |
|---|---|---|
| P2-1 | QUEUED | **The daemon fetches the chain** (DATA_FLOW decision 1); the console's chain fetch is deleted. |
| P2-2 | QUEUED | **The levels producer in its own process** (DATA_FLOW decision 2); results pushed. |
| P2-3 | QUEUED | **Everything pushed to the browser**: bars, order flow, liquidity; the page has no refresh timer; one push connection. |
| P2-4 | OPERATOR | **The four standalone pages** (/chart, /desk, /exposure, /options): list what each has that the console lacks, including anything a placeholder waits for; the operator decides what moves into the console; the pages are deleted. |
| P2-5 | QUEUED | **db.py**: delete the methods and tables only the deleted ML stack used, and `ml_horizon`, `movement_target_threshold`, `horizon_outcomes`, `decision_record`, `execution_identity`, `calibration/schema.py`; move what remains (bars, level history, enrollment, connection) to `daemon/`. |
| P2-6 | QUEUED | **server.py**: the chain fetch to `daemon/`, the levels loop and gamma-surface projection to `producer/`, the routes and startup to `console/`. |
| P2-7 | QUEUED | **The other large files**: liquidity_value_engine.py, app/options/order_flow/streaming.py and engine.py, math_exposure_core.py, ed-core.js, ed-gamma.js — cut what has no job, move each part to the process that runs it. |
| P2-DB3 | QUEUED | **One offline maintenance window, after P2-5** (sizes measured 2026-09-26): copy `ed_console.db` whole; stop the app; drop the ML tables (~49 GB) and the bar leftovers (`price_bars_1m_quarantine`, `price_bars_1m_staging`); in `stream_capture.db`, `stream_prints_raw` (no writer since the Alpaca print feed was removed 2026-09-24; Schwab refuses trade prints); compress the plain-text chain rows; move the morning chains into `complete_chain_captures` and drop the morning table; VACUUM; restart and check. Rows captured while the market was closed are deleted only on the operator's word. The codec's plain-text branch and the backfill tool are deleted after. |
| P2-DB4 | QUEUED | **One database, `ed_console.db`** (operator 2026-09-26): the stream tables move into it; the daemon's writer writes every table, including the console's (bars, level crosses, daily OI/IV, the ticker board, desk facts). |
| P2-DB5 | QUEUED | **The console reads read-only.** |
| P2-8 | QUEUED | **Docs pass**: every document matches the tree. Known stale: AGENTS.md (the Decide layer, `decision_gate.py`, the `/governance` and `/ops` pages, the decision-path admission law — all deleted); OPEN_ITEMS.md; DATA_STEWARDSHIP.md, PIPELINE_QUALITY.md, PROMOTION_POLICY.md, MODEL_RESTORE_LOG.md, TRAINING_AND_MAINTENANCE.md (describe deleted systems); docs/ (about 60 reports on deleted code). |

## Phase 3 — the placeholders on screen (after Phase 1 and 2)

| ID | Placeholder | What fills it |
|---|---|---|
| TU-05 | Options → Multi-Map; Key Levels → Vanna Support, Charm Resistance | vanna/charm exposure in dollar units per strike × expiry |
| TU-08 | Key Levels → Zero Gamma, Volatility Trigger | regime dead-zone around the flip |
| TU-11 | Options → Multi-Map | skew and term fields |
| TU-06, 07, 09, 10, 12 | none yet | call−put IV spread and implied 1-day move, ΔOI flow, GEX/ADV normalization, external GEX benchmark, intraday DDOI (meaning confirmed from its source before building) |
| LP-01 | Liquidity | steps 1–3 are in `liquidity_models.py` / `liquidity_value_engine.py` (`/api/liquidity-snapshot`); left: check the raw levels show on the chart |

## Operator designing — nothing is built until the operator decides

| ID | Item |
|---|---|
| RESEARCH | Quant formulas that decide stock, calls, puts or spreads, and research run on the stored chain history. Where it lives (Trade Desk or its own screen) is undecided. |
| PLAN | Trade Desk → Plan. |
| PORTFOLIO | Portfolio / Risk: needs the operator's positions from Schwab's account API, fetched by the daemon. |

## Operator host steps

| ID | Item |
|---|---|
| RECON-02 | `Trading/_disk_cleanup_quarantine_20260716` (53 GB, manifest read 2026-09-26): about 50 GB is old copies of the database (2026-05-27, 06-10, 06-11 and a 16 GB `db_backups` folder) and about 3 GB old report copies. They are the only database backups, so they are purged, on the operator's word, only after the P2-DB3 copy is made and verified. |
| CALENDAR-2029 | Add the NYSE 2029 holidays and early closes to time_et (US_EQUITY_CALENDAR_YEARS covers 2025-2028) when the NYSE publishes them, before 2029-01-01. From that date the calendar treats every uncovered day as closed (by design: never a guessed session), so the app would stop capturing and refreshing. Checked 2026-09-27: not yet published. |
| RUNTIME-SEPARATION | Move the runtime state (database, logs, token, diagnostics) out of the production checkout into a runtime folder. |
