# Ed Console — rules for every change

Design: `docs/DATA_FLOW.md`. Work order: `ACTIVE_PROGRAM.md`. Code map: `docs/ARCHITECTURE.md`.
Read the parts a change touches before writing it.

## Rules (operator; a change that cannot meet one stops and goes to the operator)

1. **Simple.** Fewest files, functions and hops that do the job. No prose in code: history,
   incidents and dates go in the commit message. No patches: a defect is fixed where it is
   produced, by changing or deleting that code, never by a guard, wrapper, flag, special case or
   check around it. If that takes a restructure, the restructure is the fix. Nothing new (process,
   cache, helper, file, check) without a job its existing owner cannot do, shown in the PR; an
   existing piece that cannot show one is removed.
2. **Schwab fields as sent.** Not a number: absent, -999, text, NaN or infinity, and a value
   Schwab's own field definition excludes (a negative volume or size). Everything else is taken
   as sent; a reported 0 is 0. No other bounds, no substitution.
3. **One authority.** Each value served, stored or shown has one computation authority.
   Consumers carry its result; they never select, compute, repair or relabel it. A second authority
   for the same value is banned whatever it is called: helper, parser, resolver or cache.
4. **The UI computes nothing.** Page code formats and draws. Every number, total, choice,
   comparison and date the page shows is served.
5. **No substitute paths.** Input missing, invalid, or stale for its use: no current value, shown
   absent with its reason. A valid past observation may be shown with its source, time and a label
   saying so; it never substitutes for a current value or feeds current logic. No fallback,
   default, estimate, proxy, carry-forward, interpolation or synthetic value. Test: when the source
   cannot produce the value now, the screen shows it absent with its reason, or a labeled past
   observation, never a value from elsewhere.
6. **One path.** Schwab → daemon memory → pushed to the screen. The database is history: one
   writer; read at startup, after the close and for research; never for a live screen.
7. **Nothing without a job.** A change deletes what it replaces, in the same PR. A register, audit,
   report or check lives only while it has a job; once answered, it is deleted.
8. **All tickers.** Measure and report across the board, never one ticker.
9. **Clocks.** Market logic in ET; the UI shows Central Time.
10. **Real data.** Tests run on captured Schwab data (`tests/fixtures/`) through the real code.
    A stand-in (e.g. the live price) is named in the test.

## Before writing code

- Trace each value the change touches: its source, its one producer, its validity rule and time,
  its live and stored consumers, and what each shows when the value is missing. A producer
  exists: call it. None exists: write it once, on the server.
- For each responsibility the change touches, name its one lifecycle owner (what starts,
  refreshes, retries and expires it) and what fails when that owner fails, in the affected
  section of `docs/DATA_FLOW.md` and in the code, never in a register.
- Page code: no arithmetic, sum, min/max, sort by value or date math on served data.
- A new check is a test of behavior, for a failure that happened; it fails on the old code; it
  starts with no exceptions. No new tool, register or gate.
- Time is an input: a function that depends on the clock takes `now`; only an entry point (a
  route, a loop, a stream handler) reads the clock.
- A value that crosses a module boundary is a typed record (dataclass), not a dict of string keys;
  its states are named constants, not free strings.
- Imports at the top of the module. One formatter per format (price, Central Time, dollars), on
  the server.
- A test exercises behavior through the real code. It never reads source text or pins a private
  helper; a test whose subject is deleted is deleted with it.

## Before saying done

- While working: the tests of the files touched. Before the PR is offered: `npm run test:all`
  (Playwright, then pytest) and `python -m ruff check . --select F401,F821,E9` on its final
  commit; after any later change to it (a fix, a merge, a conflict resolution) the affected tests
  run again, and CI tests that commit. Market hours: push; CI runs them.
- Never kill a commit hook mid-run; a long one runs in the background.
- Every factual claim cites same-turn output, or is marked `[UNVERIFIED]`.
- Proof is reproducible: a committed test or a command anyone can re-run. A scratch script is
  not proof.
- No hand-maintained counts, floors or lists that a check compares against; the check computes
  them.
- Work another agent wrote is read in full by the agent offering the PR, as its own work.
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
- A check proves only the paths it covers. A report names them; "check passed" never stands for
  "compliant" beyond them, and the rest stays NOT_PROVEN.

## Found broken → fix it

Same session, at its source (rule 1), or name the exact blocker. "Pre-existing", "out of scope" and
"follow-up" are not dispositions.

## Authority

- Checkpoints: about every 15 minutes of work the agent reports to the operator what changed,
  what was deleted, each proof and its tier, and what is NOT_PROVEN, then continues.
- A PR merges when its required proof on its final commit is complete and CI is green; green CI
  alone is not proof. A change to AGENTS.md, CI, a hook or a check is merged only by the operator.
- Stop for: the operator's STOP / PAUSE / HANG IT UP / DO NOT CONTINUE; a task marked AUDIT ONLY
  or DO NOT MERGE; a destructive data action; a product decision code cannot settle.
- Production checkout `EdWebConsole`: `main == origin/main`, changed only by `git pull --ff-only`.
  Work in a worktree.
- Never: `git reset`, `git checkout --`, `git stash`, force push, `--no-verify`, `git add -A` / `.`,
  deleting anything under `data/`, `backups/`, `models/`; editing source through a script
  (edits are made one at a time, as written; a block too long for one edit is removed in
  consecutive edits); changing a file's line endings (every file is LF, set by `.gitattributes`).
- Shell steps that depend on each other are joined with `&&`, so a failure stops the chain.
- Every rule above is enforced by ruff settings, `.gitattributes`, or a behavior test once the
  code meets it; until then its enforcement is a work item in `ACTIVE_PROGRAM.md`.
- May restart the console and the capture daemon; confirm both came back.

## Running it

- Console: `start_ed_console.bat` (`uvicorn server:app`, port 8000). Capture daemon:
  `start_capture_daemon.bat`.
- Python 3.13, the project `.venv`.
- Offline: `ED_CI_OFFLINE=1`, placeholder `SCHWAB_API_KEY` / `SCHWAB_APP_SECRET`. Live:
  `schwab_token.json` (`python reauth_schwab.py`).
- Probe `127.0.0.1`, never `localhost`.
