# Ed Console — Architecture

Where the code lives. The structure follows the data flow (`docs/DATA_FLOW.md`): one folder per
process, plus what they share and the page. Nothing else. A file belongs to the process that runs
it; a function exists in one place. This document is updated in the same change as every move.

## 1. The structure

```
EdWebConsole/
├── daemon/      the capture daemon: the one Schwab connection (stream and REST), the in-memory
│                state, the push to the console and the browser, the one database writer, the
│                database schema
├── producer/    the levels producer: every derived value (gamma, exposure, vanna, charm, flip,
│                walls, max pain, PCR, liquidity levels, order-flow measures), computed once
├── console/     the web server: the page and the read routes; computes nothing, writes nothing
├── shared/      what more than one process uses: market calendar and sessions, config, runtime
│                paths, instrument identity
├── static/      the page (one shell)
├── tests/
├── tools/       the few checks and scripts the repository needs
├── docs/
└── start_ed_console.bat, start_capture_daemon.bat, and the launch checks they run
```

Outside the repository: the runtime folder (the one database, the token, logs) and worktrees.

## 2. Where each file goes

Moves happen one change at a time. `delete` rows go with the change named in `ACTIVE_PROGRAM.md`.

| Today | Goes to |
|---|---|
| `app/market_data/schwab/streaming/` (capture, live_push, live_ui), `stream_spine.py`, `live_market_plane.py`, `live_price_rows.py` | `daemon/` |
| `schwab_client.py`, `api_pressure.py`, `market_context.py` (Schwab REST calls) | `daemon/` |
| From `server.py`: the chain gate (`_gated_safe_get_chain`; the chain download itself is `schwab_client.fetch_full_chain`) | `daemon/` |
| `calibration/complete_chain_capture.py` (the chain history, DATA_FLOW decision 7) | `daemon/` |
| `db.py` (the parts that stay: bars, level history, enrollment, connection), `db_authority.py`, `db_safety.py`, `json_blob_codec.py` | `daemon/` (writes) — the console opens the database read-only |
| `terrain_engine.py`, `terrain_read.py`, `terrain_atr.py`, `math_exposure_core.py`, `math_levels.py`, `math_probabilities.py`, `math_volatility.py` | `producer/` |
| `liquidity_value_engine.py`, `liquidity_models.py` | `producer/` |
| `app/options/order_flow/`, `l1_trade_observation.py`, `micro_structure.py` | `producer/` |
| From `server.py`: the levels loop, `_publish_levels`, the gamma-surface projection | `producer/` |
| From `server.py`: the routes, startup; `release_object.py` | `console/` |
| `time_et.py`, `config.py`, `runtime_layout.py`, `instrument_identity.py`, `production_universe.py`, `scheduler_user_tickers.py`, `numeric_contract.py` | `shared/` |
| `static/index.html`, `static/js/`, `static/css/` | `static/` |
| `start_*.bat`, `runtime_preflight.py`, `live_schwab_env.py`, `launcher_port_guard.py`, `wait_for_ready_then_open.py`, `reauth_schwab.py` | stay at the root |
| `schwab_field_dictionary_builder.py` | checked at its step: delete if nothing needs it |

## 3. Taking apart the two big files (measured 2026-09-26)

Each step is one change: delete what has no job, move what remains, update §2, pass the full test
suite and the browser suite, check the running app. Nothing is copied.

**db.py (1,343 lines after P2-5 part 1).** The snapshot writer, `SnapshotRow`, the ML outcome
labels, the snapshot column migrations, `market_session` and `get_db_stats` are deleted.
- Left to delete: the one-time JSON migration once its flag shows it ran. The `snapshots` and
  `iv_daily` DDL is gone (no writer, no reader); their tables leave the database in P2-DB3.
- Keep, and move to `daemon/`: bars, level history (crosses, daily OI and IV), enrollment (the
  ticker board), the connection.
- The console stops writing (DATA_FLOW decision 5); its writes go to the daemon's writer, into `ed_console.db`.

**server.py (6,130 lines: 40 routes, 112 functions).**
- To `daemon/`: the chain fetch and chain captures.
- To `producer/`: the levels loop, `_publish_levels`, the gamma-surface projection and its
  stream-state stamping.
- To `console/`: the routes (grouped by what they serve) and startup.
- What remains is the app assembly: create the app, include the routes, start.

**The other large files** (`liquidity_value_engine.py` 1,947; order-flow `streaming.py` 1,124 and
`engine.py` 1,093; `math_exposure_core.py` 1,018; `ed-core.js` 1,063; `ed-gamma.js` 1,039): each is
measured the same way (part, lines, used or not) and the plan written here before its step starts.

## 4. Failure domains

The app and each capability fail separately. If Schwab (or its stream) is unavailable, the app
still starts and serves; the Schwab-dependent panels say they are unavailable, and nothing is
filled in from elsewhere. The app refuses to start only when it cannot run at all (a broken Python
environment, core code that will not load).

## 5. Runtime state lives outside the source

The database, the Schwab token, logs and diagnostics are runtime state, not source.
`runtime_layout.py` is the one owner of where they live: `ED_RUNTIME_ROOT` moves them; unset, a
standalone checkout uses itself and a linked worktree uses the primary checkout's runtime (it
reads, and never starts a live console or daemon on it). Source changes never touch runtime state,
and runtime output never lands in the source tree.
