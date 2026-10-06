# Ed Console — Architecture

Where the code lives. The structure it moves to follows the data flow (`docs/DATA_FLOW.md`): one
folder per process, plus what they share and the page. Nothing else. A file belongs to the process
that runs it; a function exists in one place. §1 is the target (none of its process folders exists
yet); §2 is today's files and where each goes. This document is updated in the same change as
every move.

## 1. The target structure

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
└── start_ed_console.bat (runs launch.py), start_capture_daemon.bat
```

Outside the repository: the runtime folder (the one database, the token, logs) and worktrees.

## 2. Where each file goes

Moves happen one change at a time. `delete` rows go with the change named in `ACTIVE_PROGRAM.md`.

| Today | Goes to |
|---|---|
| `app/market_data/schwab/streaming/` (capture, live_push, live_ui), `stream_spine.py`, `live_market_plane.py`, `live_price_rows.py` | `daemon/` |
| `schwab_client.py` (Schwab REST calls) | `daemon/` |
| `calibration/complete_chain_capture.py` (the board, the chain sweep and the chain history, DATA_FLOW decisions 1 and 7) | `daemon/` |
| `db.py` (the parts that stay: bars, level history, enrollment, connection), `db_authority.py`, `db_safety.py`, `json_blob_codec.py` | `daemon/` (writes) — the console opens the database read-only |
| `terrain_engine.py`, `terrain_read.py`, `terrain_atr.py`, `math_exposure_core.py`, `math_levels.py`, `math_probabilities.py`, `math_volatility.py` | `producer/` |
| `liquidity_value_engine.py`, `liquidity_models.py` | `producer/` |
| `app/options/order_flow/`, `app/options/contracts/`, `l1_trade_observation.py`, `micro_structure.py` | `producer/` |
| From `server.py`: the levels loop, `_publish_levels`, `_publish_price_levels`, the gamma-surface projection | `producer/` |
| From `server.py`: the routes, startup; `push_changes.py` (the `/api/changes` push and the ticker on screen) | `console/` |
| `time_et.py`, `config.py`, `runtime_layout.py`, `instrument_identity.py`, `production_universe.py`, `numeric_contract.py` | `shared/` |
| `static/` (the page, its icons, manifest and the vendored chart library) | `static/` |
| `start_*.bat`, `launch.py`, `reauth_schwab.py` | stay at the root |
| `tools/` (the git hooks and checks), `scripts/` (the test runners), `tests/`, `docs/`, the config files | stay |

## 3. Taking apart the big files

Each step is one change: delete what has no job, move what remains, update §2, pass the full test
suite and the browser suite, check the running app. Nothing is copied.

**db.py.** Keep, and move to `daemon/`: bars, level crosses, enrollment (the ticker board), the
connection. The console stops writing (DATA_FLOW decision 5); its writes go to the daemon's
writer, into `ed_console.db`.

**server.py.**
- To `producer/`: the levels loop, `_publish_levels`, `_publish_price_levels`, the gamma-surface
  projection and its stream-state stamping.
- To `console/`: the routes (grouped by what they serve) and startup.
- What remains is the app assembly: create the app, include the routes, start.

**The other large files** (`liquidity_value_engine.py`; order-flow `streaming.py` and `engine.py`;
`math_exposure_core.py`; `ed-core.js`; `ed-gamma.js`): each is measured the same way (part, used
or not) and the plan written here before its step starts.

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
