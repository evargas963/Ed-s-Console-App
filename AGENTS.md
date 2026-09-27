# Ed Console — rules for every change

Design: `docs/DATA_FLOW.md`. Work order: `ACTIVE_PROGRAM.md`. Code map: `docs/ARCHITECTURE.md`.
Read the parts a change touches before writing it.

## Rules (operator; a change that cannot meet one stops and goes to the operator)

1. **Simple.** Fewest files, functions and hops that do the job. No prose in code.
2. **Schwab fields as sent.** Not a number: absent, -999, text, NaN or infinity, and a value
   Schwab's own field definition excludes (a negative volume or size). Everything else is taken
   as sent; a reported 0 is 0. No other bounds, no substitution.
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
10. **Real data.** Tests run on captured Schwab data (`tests/fixtures/`) through the real code.
    A stand-in (e.g. the live price) is named in the test.

## Before writing code

- Trace each value the change touches: its source, its one producer, its live and stored
  consumers, and what each shows when the value is missing. A producer exists: call it. None
  exists: write it once, on the server.
- Page code: no arithmetic, sum, min/max, sort by value or date math on served data.
- A new check exists only for a failure that happened; it fails on the old code; it starts with
  no exceptions.

## Before saying done

- While working: the tests of the files touched. Once per PR, before pushing: `npm run test:all`
  (Playwright, then pytest) and `python -m ruff check . --select F401,F821,E9`. Market hours:
  push; CI runs them.
- Never kill a commit hook mid-run; a long one runs in the background.
- Every factual claim cites same-turn output, or is marked `[UNVERIFIED]`.
- A runtime change is on disk only until the process restarts after it; say which.
- Merged is not deployed; deployed is production at the merge commit, both processes restarted,
  the real screen checked.

## Close the change

A PR that changes code, a design, a plan or a sequence updates, in the same PR, every affected
instruction, design, work item, check, test and caller; removes superseded statements and paths;
verifies that the documents agree with the implemented behavior and current work status; and
lists each affected path it did not verify as NOT_PROVEN. Only affected items: no edits for their
own sake. A finished work item leaves
`ACTIVE_PROGRAM.md` in the PR that finishes it. A changed sequence updates its dependents there
and every document that states the old one.

## Review verdicts

- **PASS**: every required condition proven. **FAIL**: any condition violated, whatever else
  passed. **NOT_PROVEN**: any condition without proof. Never PASS with a FAIL or NOT_PROVEN open.
- Name the tier of each proof: unit, integration, browser, deployed app, live market. A pass at
  one tier does not stand in for another.
- A changed test expectation cites the required behavior that changed.

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
