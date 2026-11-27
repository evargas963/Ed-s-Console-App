# Ed Console — Architecture

Where the code lives. One program in five parts (`AGENTS.md` "The shape"): Feed in `feed/`, State in
`state/`, every Calculator in `calc/`, every panel in `push/`. The Recorder's database modules and
the modules every part uses stay at the root; no `recorder/` or `shared/` folder is built (operator
2026-11-16: "you should make everything as simple as possible now"). This document is updated in the
same change as every move.

## 1. The structure

```text
EdWebConsole/
├── feed/        the only code that talks to Schwab: the stream, the REST calls (chains, quotes,
│                price history, /markets), the sign-in; each field taken as sent
├── state/       the one in-memory store: the newest value of everything, with its time
├── calc/        pure functions: every derived value (exposures, levels, walls, flip, max pain,
│                confluence, liquidity, order-flow measures), from inputs and `now` passed in
├── push/        each panel's served record, built from State
├── app/         the program itself: capture_main.py (its start), capture.py (the daemon: what the
│                stream is asked for, the stop, the daily keep), live_ui.py (the page's one
│                WebSocket, /ws), program_lock.py (one program at a time), live_push.py, and the
│                order-flow stores (app/options/order_flow/)
├── calibration/ complete_chain_capture.py: a chain capture as the Recorder takes it (its message)
│                and as a start reads it back (StoredCapture)
├── static/      the page, which draws what is pushed
├── *.py         at the root: the Recorder (stream_spine.py's writer) and the startup loader
│                (db.py), the only modules that use sqlite3; server.py (the routes and startup);
│                and what every part uses (market sessions from Schwab's /markets, config,
│                runtime paths, instrument identity, formatters)
├── typings/     type stubs for schwab-py and authlib, which ship none (read by type checkers only)
├── scripts/     the test runners (npm run test:all)
├── tests/
├── tools/       the few checks the standard tools cannot do
├── docs/
├── start_ed_console.cmd     runs launch.py, which starts the one program
└── start_capture_daemon.cmd the program's window, which launch.py opens (launch.window)
```

Imports flow one way: push → state → calc; feed → state. `locks.imports.toml` holds the rules that
matter (only Feed talks to Schwab; the Calculators read no State, Push, Feed, database or network)
and ruff's ban on `sqlite3` holds the Recorder's; no layers contract is built (operator 2026-11-16).
Its contracts read the checkout as one package, because grimp takes no top-level module, so an
import of a root module is an outside name and no layer can be drawn across them. Outside the
repository: the runtime folder (the one database, the token, logs) and worktrees.

## 2. Failure domains

The app and each capability fail separately. If Schwab (or its stream) is unavailable, the app still
starts and serves; the Schwab-dependent panels draw "-" (operator 2026-10-12 and 2026-10-16), and
nothing is filled in from elsewhere. The app refuses to start only when it cannot run at all (a
broken Python environment, core code that will not load).

## 3. Runtime state is not source

The database, the Schwab token, logs and diagnostics are runtime state, not source.
`runtime_layout.py` is the one owner of where they live: `ED_RUNTIME_ROOT` moves them; unset, a
standalone checkout uses itself and a linked worktree uses the primary checkout's runtime (it reads,
and never starts a live program on it). Runtime state lives in the runtime root's `data/`, `logs/`
and `schwab_token.json`, each ignored by git, so source changes never touch it; in a standalone
checkout they sit inside the checkout. Production stays where it is, in the operator's Documents
folder (operator 2026-11-19: "lets not move it. lets leave it alone"): the folder is local, not
synced, on the same drive, and a move would mean lifting the database's delete protection.
