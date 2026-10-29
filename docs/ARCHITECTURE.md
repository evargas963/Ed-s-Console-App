# Ed Console — Architecture

Where the code lives. The target is one program in five parts, each part a folder (`AGENTS.md`
"The shape", operator 2026-10-29). §1 is the target, none of whose folders exists yet; §2 is
today's files and the part each goes to; §3 is the order, the steps of `ACTIVE_PROGRAM.md` SHAPE.
This document is updated in the same change as every move.

## 1. The target structure

```
EdWebConsole/
├── feed/        the only code that talks to Schwab: the stream, the REST calls (chains, quotes,
│                price history, /markets), the sign-in; each field taken as sent
├── state/       the one in-memory store: the newest value of everything, with its time
├── calc/        pure functions: every derived value (exposures, levels, walls, flip, max pain,
│                confluence, liquidity, order-flow measures), from inputs and `now` passed in
├── push/        the web app: the page and the one WebSocket that sends it a snapshot, then changes
├── recorder/    the only database writer, and the startup loader that reads history once
├── shared/      what every part uses: market sessions (Schwab's /markets), config, runtime paths,
│                instrument identity, formatters
├── static/      the page, which draws what is pushed
├── tests/
├── tools/       the few checks the standard tools cannot do
├── docs/
└── start_ed_console.bat (runs launch.py, which starts the one program)
```

Imports flow one way, enforced by import-linter: push → state → calc; feed → state; recorder ←
state; every part may use shared. Outside the repository: the runtime folder (the two databases,
the token, logs) and worktrees.

## 2. Where each file goes

| Today | Goes to |
|---|---|
| `schwab_client.py`; the Schwab half of `app/market_data/schwab/streaming/capture.py` (the stream, the subscriptions, the watchlist check); `calibration/complete_chain_capture.py` (the chain sweep and price history requests) | `feed/` |
| `live_market_plane.py`, `live_price_rows.py`, `stream_spine.py` (the bus), the console's live stores (`server._terrain_cache`, `server._bars`, `server._crosses`, `app/options/order_flow/state.py`, `app/options/order_flow/history.py`) | `state/`, one store |
| `terrain_engine.py`, `terrain_read.py`, `terrain_atr.py`, `math_exposure_core.py`, `math_levels.py`, `math_probabilities.py`, `math_volatility.py`, `confluence_composite.py`, `liquidity_value_engine.py`, `liquidity_models.py`, `micro_structure.py`, `l1_trade_observation.py`, the order-flow engine | `calc/` |
| `server.py` (the routes and startup), `static/` | `push/`, `static/` |
| `stream_spine.py` (the writer, `CaptureWriter`), `db.py`, `db_authority.py`, `db_safety.py`, `json_blob_codec.py`, the chain history writes | `recorder/` |
| `time_et.py`, `config.py`, `runtime_layout.py`, `instrument_identity.py`, `numeric_contract.py` | `shared/` |
| `app/market_data/schwab/streaming/live_push.py` (daemon → console, :8799), `app/options/order_flow/streaming.py` (the console's consumer), `push_changes.py` (SSE `/api/changes`), `static/js/l1_sse_guards.js` | deleted: one program needs no channel between processes, and the page gets the one push |
| `start_capture_daemon.bat` | deleted with the second program |
| `launch.py`, `reauth_schwab.py`, `start_ed_console.bat` | stay at the root |

## 3. The order

The steps of `ACTIVE_PROGRAM.md` SHAPE, one small PR each. A step turns its check on with no
exception list, fixes what the check finds in the same PR, and deletes what it replaces. Files
move into their folders as the step that owns them lands; nothing is copied.

## 4. Failure domains

The app and each capability fail separately. If Schwab (or its stream) is unavailable, the app
still starts and serves; the Schwab-dependent panels say they are unavailable and why, and nothing
is filled in from elsewhere. The app refuses to start only when it cannot run at all (a broken
Python environment, core code that will not load).

## 5. Runtime state is not source

The database, the Schwab token, logs and diagnostics are runtime state, not source.
`runtime_layout.py` is the one owner of where they live: `ED_RUNTIME_ROOT` moves them; unset, a
standalone checkout uses itself and a linked worktree uses the primary checkout's runtime (it
reads, and never starts a live program on it). Runtime state lives in the runtime root's `data/`,
`logs/` and `schwab_token.json`, each ignored by git, so source changes never touch it; in a
standalone checkout they sit inside the checkout.
