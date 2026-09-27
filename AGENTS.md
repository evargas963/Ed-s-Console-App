# Ed Console — rules for every change

Design: `docs/DATA_FLOW.md`. Work order: `ACTIVE_PROGRAM.md`. Code map: `docs/ARCHITECTURE.md`.
Read the parts a change touches before writing it.

## Rules (operator; a change that cannot meet one stops and goes to the operator)

1. **Simple.** Fewest files, functions and hops that do the job. No prose in code.
2. **Schwab fields as sent.** No bounds, no substitution. Only -999 or an absent field is not a number.
3. **One producer.** A value on screen is a Schwab field as sent, or a derived value computed by
   exactly one function. Consumers carry it; none recompute it.
4. **The UI computes nothing.** Page code formats and draws. Every number, total, choice,
   comparison and date the page shows is served.
5. **No fallbacks.** Missing, stale or invalid shows absent, with its reason. No second source,
   copy or default.
6. **One path.** Schwab → daemon memory → pushed to the screen. The database is history: one
   writer; read at startup, after the close and for research; never for a live screen.
7. **Nothing without a job.** A change deletes what it replaces, in the same PR.
8. **All tickers.** Measure and report across the board, never one ticker.
9. **Clocks.** Market logic in ET; the UI shows Central Time.

## Before writing code

- Name each value the change touches and its one producer. One exists: call it. None exists:
  write it once, on the server.
- Page code: no arithmetic, sum, min/max, sort by value or date math on served data.
- A rule check fails on today's code before its fix lands; its exception list starts empty.

## Before saying done

- `npm run test:all` (Playwright, then pytest) and `python -m ruff check . --select F401,F821,E9`
  pass. Market hours: push; CI runs them.
- Every factual claim cites same-turn output, or is marked `[UNVERIFIED]`.
- After deploy, check the real screen.

## Found broken → fix it

Same session, or name the exact blocker. "Pre-existing", "out of scope" and "follow-up" are not
dispositions.

## Authority

- Merge on green CI. Stop for: the operator's STOP / PAUSE / HANG IT UP / DO NOT CONTINUE; a task
  marked AUDIT ONLY or DO NOT MERGE; a destructive data action; a product decision code cannot settle.
- Production checkout `EdWebConsole`: `main == origin/main`, changed only by `git pull --ff-only`.
  Work in a worktree.
- Never: `git reset`, `git checkout --`, `git stash`, force push, `--no-verify`, `git add -A` / `.`,
  deleting anything under `data/`, `backups/`, `models/`.
- May restart the console and the capture daemon; confirm both came back.

## Running it

- Console: `start_ed_console.bat` (`uvicorn server:app`, port 8000). Capture daemon:
  `start_capture_daemon.bat`.
- Python 3.13, the project `.venv`.
- Offline: `ED_CI_OFFLINE=1`, placeholder `SCHWAB_API_KEY` / `SCHWAB_APP_SECRET`. Live:
  `schwab_token.json` (`python reauth_schwab.py`).
- Probe `127.0.0.1`, never `localhost`.
