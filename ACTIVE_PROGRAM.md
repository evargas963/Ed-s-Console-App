# ACTIVE_PROGRAM.md — the current work, in order

The one record of operator-directed work: what is in flight, queued or blocked. The design every
item is built to is `docs/DATA_FLOW.md`; where code lives is `docs/ARCHITECTURE.md`. Rows leave this
file when they finish (git keeps them). Rewritten 2026-09-26: the rows for the ML stack, the
research program and the scheduled tasks were removed with that code and those tasks.

Status values: `NEXT` | `IN PROGRESS` | `QUEUED` | `BLOCKED` | `OPERATOR`.

## Phase 1 — restore and stabilize

| ID | Status | Work item |
|---|---|---|
| P1-1 | NEXT | **Chain and levels through the daemon's writer, loaded at startup.** Every publish sends the latest chain per ticker as Schwab sent it and the derived levels, with their time, to the daemon's writer (not a new console writer); the latest are loaded at startup. Deletes #303's closed-market branch and its saved files. Restores the weekend/after-close screens. Checked on the running app. |
| P1-2 | IN PROGRESS | **Console noise + the page's one reader** (branch `rehab/host-jobs`): no per-request log lines, no idle terrain line; every panel reads through one store; no page timer reads `/api` on a closed market. Open: 8 pytest + 1 browser test failing; then full suites, then checked on the running app. |

## Phase 2 — the rest of the design, then decomposition

| ID | Status | Work item |
|---|---|---|
| P2-1 | QUEUED | **The daemon fetches the chain** (DATA_FLOW decision 1). |
| P2-2 | QUEUED | **The levels producer in its own process** (DATA_FLOW decision 2); results pushed and written. |
| P2-3 | QUEUED | **Everything pushed to the browser**: bars, order flow, liquidity; the page has no refresh timer; one push connection. |
| P2-4 | OPERATOR | **The four standalone pages** (/chart, /desk, /exposure, /options): list what each has that the console lacks; the operator decides what moves into the console; the pages are deleted. |
| P2-5 | QUEUED | **db.py**: delete the methods and tables only the deleted ML stack used, and `ml_horizon`, `movement_target_threshold`, `horizon_outcomes`, `decision_record`, `execution_identity`; move what remains (bars, level history, enrollment, connection) to `daemon/`. |
| P2-6 | QUEUED | **server.py**: the chain fetch to `daemon/`, the levels loop and gamma-surface projection to `producer/`, the routes and startup to `console/`. |
| P2-7 | QUEUED | **The other large files**: liquidity_value_engine.py, app/options/order_flow/streaming.py and engine.py, math_exposure_core.py, ed-core.js, ed-gamma.js — cut what has no job, move each part to the process that runs it (`daemon/`, `producer/`, `console/`). |
| P2-DB1 | IN PROGRESS | **Measure each table's size** in ed_console.db, read-only (operator approved 2026-09-26). |
| P2-DB2 | OPERATOR | **Review the sizes; decide the copy and which tables are dropped.** Dropping needs a verified copy or the operator's word. |
| P2-DB3 | QUEUED | **Drop the orphaned ML tables** on the operator's word; VACUUM in an offline maintenance window. |
| P2-DB4 | QUEUED | **One database**: the console's tables move into the daemon's database; the daemon's writer writes them. |
| P2-DB5 | QUEUED | **The console reads read-only.** |
| P2-8 | QUEUED | **Docs pass**: every document matches the tree. Known stale: AGENTS.md (the Decide layer, `decision_gate.py`, the `/governance` and `/ops` pages, the decision-path admission law — all deleted); OPEN_ITEMS.md; DATA_STEWARDSHIP.md, PIPELINE_QUALITY.md, PROMOTION_POLICY.md, MODEL_RESTORE_LOG.md, TRAINING_AND_MAINTENANCE.md (describe deleted systems); docs/ (about 60 reports on deleted code). |

## Carried from the previous file — the operator keeps or drops

| ID | Work item |
|---|---|
| LP-01 | Session value levels: volume profile across each bar's range (not typical price), overnight window from the prior trading session, raw levels on the chart. Authority: liquidity_value_engine.py, /api/liquidity-snapshot. |
| TU-05..TU-12 | Terrain upgrades: vanna/charm exposure units, call−put IV spread and implied 1-day move, ΔOI flow, regime dead-zone around the flip, GEX/ADV normalization, external GEX benchmark, skew/term fields, intraday DDOI. |
| RECON-02 | Disk purge of ~53 GB quarantined files, after the operator's purge word. |
| RUNTIME-SEPARATION | Move the runtime state (database, logs, token, diagnostics) out of the production checkout into a runtime folder (operator host step). |
