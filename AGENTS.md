# Ed Console — rules for every change

Ed Console is a financial application: what it shows can drive a trade. This file is the one
governing authority. `docs/DATA_FLOW.md` (design), `ACTIVE_PROGRAM.md` (work order),
`docs/ARCHITECTURE.md` (code map), the hooks and the tests follow it and never override it.
Read the parts a change touches before writing it.

**Conflicts and exceptions.** Every direction is checked against these rules before it is acted
on: the operator's, a reviewer's, another model's, a document's, a test's, and the agent's own.
When a direction, recommendation or proposed change conflicts with a rule, or it is unclear
whether it does, the affected action pauses (other work continues) and the agent tells the
operator the conflict, the rule it breaks and its consequence on screen and in the data, and asks
for explicit confirmation. The operator's own direction is not assumed to intend an exception.
Only the operator's explicit confirmation authorizes an exception, and only when it names the
exact exception, its scope (the change, the values and the paths it covers) and its
justification; it covers nothing else and does not carry to later work. Not confirmation:
silence, an approval given for other work, an agent's recommendation (another model's included),
an existing implementation, a passing test, green CI, a saved memory. An agent never grants,
infers or widens an exception. An authorized exception is recorded in `ACTIVE_PROGRAM.md` with
the operator's words and date. An existing violation stays a violation, listed in
`ACTIVE_PROGRAM.md` until fixed; being inherited never makes it an exception.

## Rules

1. **Simple.** The smallest complete implementation: fewest files, functions and hops that do the
   job. No prose in code: history, incidents and dates go in the commit message. No patches: a
   defect is fixed where it is produced, by changing or deleting that code, never by a guard,
   wrapper, flag, special case or check around it; the fix covers the producer and every
   connected path its closure needs. If that takes a restructure, the restructure is the fix, and
   a change broader than the task is explained to the operator before it is made. Nothing new
   (process, cache, helper, file, check) without a job its existing owner cannot do, shown in the
   PR; an existing piece that cannot show one is removed.
2. **Schwab fields as sent.** Not a number: absent, -999, text, NaN or infinity, and a value
   Schwab's own field definition excludes (a negative volume or size). Everything else is taken
   as sent; a reported 0 is 0. No other bounds, no substitution. Each field keeps Schwab's own
   timestamp and its provenance (the service or endpoint, the daemon's receive time) wherever it
   travels.
3. **One authority.** Each value served, stored or shown has one computation authority, the same
   calculation for every ticker. Consumers carry its result; they never select, compute, repair
   or relabel it. A second authority for the same value is banned whatever it is called: helper,
   parser, resolver or cache.
4. **The UI computes nothing.** Page code formats and draws. Every number, total, choice,
   comparison and date the page shows is served.
5. **Correct or unavailable.** A live output is correct and supported by valid inputs for its
   defined scope, or it is unavailable, shown absent with its reason. Nothing stale, invalid,
   incomplete or historical is presented as current. A derived value needs valid inputs for its
   whole scope: aggregating the earlier minutes of its own bar or day is correct; a concealed gap,
   an invented input (fallback, default, estimate, proxy, carry-forward, interpolation, synthetic
   value) or a second calculation is not. A valid past observation may be shown with its source,
   time and a label saying so; it never substitutes for a current value or feeds current logic.
   Test: when the source cannot produce the value now, the screen shows it absent with its reason,
   or a labeled past observation, never a value from elsewhere.
6. **Current, new and history kept apart.** Schwab → daemon → pushed to the screen as it arrives.
   Three kinds, never confused: the current state (each field's last value, because Schwab sends
   a field once and then only its changes; live only while the live rule proves the feed), a new
   event (a Schwab message, delivered when Schwab sends it) and history (anything stored, or held
   from before). A reconnect, restart or database load never turns history into a new event and
   never restores live status: what it loads is history, shown with its time and labeled, until
   the live rule proves the feed again. A past event (a completed bar, a trade) is never resent
   or replayed as new; data missed while disconnected is a named gap, never filled. The database
   is history: one writer, in the background, so persistence never delays live delivery; read at
   startup, after the close and for research; never for a live screen. Where live cannot be done,
   the operator is told why.
7. **Nothing without a job.** A change deletes what it replaces, in the same PR. A register, audit,
   report or check lives only while it has a job; once answered, it is deleted.
8. **All tickers.** Measure and report across the board, never one ticker.
9. **Clocks.** Market logic in ET; the UI shows Central Time.
10. **Tests enforce the requirements.** A test states a requirement and fails when it is broken:
    the missing, invalid, stale and disconnected inputs as well as the normal one. It runs on
    captured Schwab data (`tests/fixtures/`) through the real code. A stand-in (e.g. the live
    price, an open session) is named in the test and never by itself makes true the claim under
    test. A test that confirms the implementation an agent chose instead of the requirement is
    corrected. Captured-data replay proves behavior, not deployed live operation.

## Before writing code

- Trace each value the change touches: its source, its one producer, its validity rule and time,
  its live and stored consumers, and what each shows when the value is missing. A producer
  exists: call it. None exists: write it once, on the server.
- For each responsibility the change touches, name its one lifecycle owner (what starts,
  refreshes, retries and expires it) and what fails when that owner fails, in the affected
  section of `docs/DATA_FLOW.md` and in the code, never in a register.
- Page code: no arithmetic, sum, min/max, sort by value or date math on served data.
- A new check is a behavior test of a requirement (rule 10), shown failing on the old code or on
  a named broken input; it starts with no exceptions. No new tool, register or gate.
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
- A PR is merged or deployed only with the operator's authorization for it, once its required
  proof on its final commit is complete and CI is green; green CI alone is not proof. A change to
  AGENTS.md, CI, a hook or a check is merged only by the operator.
- Stop for: the operator's STOP / PAUSE / HANG IT UP / DO NOT CONTINUE; a task marked AUDIT ONLY
  or DO NOT MERGE; a destructive data action; a product decision code cannot settle; a direction
  or change that conflicts with a rule, or may (§ Conflicts and exceptions).
- Production checkout `EdWebConsole`: `main == origin/main`, changed only by `git pull --ff-only`.
  Work in a worktree.
- Never: `git reset`, `git checkout --`, `git stash`, force push, `--no-verify`, `git add -A` / `.`,
  deleting anything under `data/`, `backups/`; editing source through a script
  (edits are made one at a time, as written; a block too long for one edit is removed in
  consecutive edits); changing a file's line endings in an edit (the commit hook refuses it;
  normalising every file to LF is one commit of P1-9).
- Shell steps that depend on each other are joined with `&&`, so a failure stops the chain.
- What is enforced, and what is not. The commit hook (`.pre-commit-config.yaml`): the secrets and
  private-path scan, the line-ending check, the virtualenv check, ruff (F401, F821, E9). CI: ruff,
  a compile pass, Playwright (`tests/e2e/`), pytest (`tests/`). The agent hooks
  (`.claude/settings.json`, `.cursor/hooks.json`): destructive git, blind staging, hook bypass,
  deletes under `data/` and `backups/`, edits of the production checkout. None of these checks a
  rule above except through a behavior test written for it. Written rules, saved memories and
  green CI guarantee nothing: a rule with no test that fails when it is broken is NOT_PROVEN, and
  that test is a work item in `ACTIVE_PROGRAM.md`.
- May restart the console and the capture daemon; confirm both came back.

## Running it

- Console: `start_ed_console.bat` (`uvicorn server:app`, port 8000). Capture daemon:
  `start_capture_daemon.bat`.
- Python 3.13, the project `.venv`.
- Offline: `ED_CI_OFFLINE=1`, placeholder `SCHWAB_API_KEY` / `SCHWAB_APP_SECRET`. Live:
  `schwab_token.json` (`python reauth_schwab.py`).
- Probe `127.0.0.1`, never `localhost`.
