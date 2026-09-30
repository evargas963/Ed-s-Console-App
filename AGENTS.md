# Ed Console — rules for every change

## Ed Console is a financial application

Its output can drive real financial decisions. The app is live; a value that cannot be live says
so, with its reason. These requirements govern the entire repository end to end: data intake,
calculations, storage, APIs, push channels, screens, processes, configuration, tests, CI and
release. No convenience, recommendation, existing implementation or passing test overrides them.

This file is the one governing authority. Subordinate to it, each with one job: `docs/DATA_FLOW.md`
(the architecture and the definition of every value), `ACTIVE_PROGRAM.md` (every defect,
violation and unfinished item: the only such list), `docs/ARCHITECTURE.md` (the code map),
`docs/host/` (operations), and the hooks, CI and tests that enforce the rules. Examples in any of
them never narrow a requirement. Read the parts a change touches first.

**Every value** served, stored, calculated or shown has, in `docs/DATA_FLOW.md` § 7:
1. its meaning, units, sign and scope;
2. its native Schwab source (field, service or endpoint), or an approved derived definition;
3. one computation authority, and one lifecycle owner that starts, refreshes, invalidates and
   recovers it;
4. its instrument identity, Schwab's timestamps, the daemon's receive time and its provenance,
   carried wherever it goes;
5. when it is valid, current and complete, how it recovers, and what it shows when it is not;
6. every consumer (calculation, route, push, screen, store) and each one's behavior when it is
   invalid;
7. the tests and runtime evidence that prove the above.
A value missing any of these is NOT_PROVEN and listed in `ACTIVE_PROGRAM.md`.

**Conflicts and exceptions.** Only the operator authorizes an exception: explicitly, naming the
exception, its scope and its justification; it covers nothing else. Any direction that conflicts
or may conflict with a rule, the operator's included, is brought to the operator with the
conflict and its consequence before the affected action proceeds; other work continues. A
direction given for one task governs that task only; it never becomes a standing rule without the
operator saying so. Not authorization: silence, an approval for other work, an agent's or another
model's recommendation, existing code, a passing test, green CI, a saved memory. An authorized
exception is recorded in `ACTIVE_PROGRAM.md` with the operator's words and date. An existing
violation stays a violation, listed there until fixed; being inherited never excuses it.

## Rules

1. **Simple.** The smallest complete implementation: fewest files, functions and hops. No prose in
   code: history, incidents and dates go in the commit message. No patches: a defect is fixed where
   it is produced, never by a guard, wrapper, flag or special case around it, and the fix covers
   every connected path. A restructure that a fix needs is the fix; a change broader than the task
   is explained to the operator first. Nothing new (process, cache, helper, file, check) without a
   job its existing owner cannot do, shown in the PR.
2. **Schwab fields as sent.** Not a number: absent, -999, text, NaN or infinity, and a value
   Schwab's own field definition excludes (a negative volume or size). Everything else is taken as
   sent; a reported 0 is 0. No other bounds, no substitution. Each field keeps Schwab's timestamp
   and its provenance (service or endpoint, the daemon's receive time) wherever it travels.
3. **One authority.** Each value and each responsibility has one owner, the same for every ticker.
   Consumers carry its result; they never select, compute, repair or relabel it. A second
   authority for the same value is banned whatever it is called: helper, parser, resolver, cache.
4. **The UI computes nothing.** Page code formats and draws. Every number, total, choice,
   comparison and date the page shows is served; the one page-side rule is the transport rule in
   `docs/DATA_FLOW.md` (a silent channel withdraws what came on it).
5. **Correct or unavailable.** A current output is correct and supported by valid inputs for its
   defined scope, or it is unavailable with its reason. Losing validity removes a value's
   authority from every dependent, a screen already open included; a warning while a calculation
   or consumer still uses the value does not. A heartbeat, an open socket or a subscription alone
   never makes a value current: the value itself arrived from Schwab for the current session. A
   derived value needs valid inputs for its whole scope: aggregating the earlier minutes of its
   own bar or day is correct; a concealed gap, an invented input (fallback, default, estimate,
   proxy, carry-forward, interpolation, synthetic value) or a second calculation is not. A valid
   past observation may be shown labeled with its source and time; it never substitutes for a
   current value or feeds current logic. A wrong or fabricated value is not made acceptable by a
   label.
6. **Current, new and history kept apart.** Schwab → daemon → pushed to the screen as it arrives,
   the database written in the background by one writer so persistence never delays live delivery
   (`docs/DATA_FLOW.md`; the architecture changes only for a reason agreed with the operator).
   Three kinds, never confused: the current state (each field's last value: Schwab sends a field
   once, then only its changes), a new event (a Schwab message, delivered when Schwab sends it)
   and history (anything stored, or held from before). A reconnect, restart, restore or database
   load never turns history into a new event and never restores live status. A past event (a
   completed bar, a trade) is never resent as new; data missed while disconnected is a named gap,
   never filled. The database is read at startup, after the close and for research, never for a
   live screen.
7. **Nothing without a job.** A change deletes what it replaces, in the same PR. A register,
   audit, report or check lives only while it has a job.
8. **All tickers.** One rule for every instrument; a real difference between instruments follows
   Schwab's own metadata for it, never a ticker-specific repair. Measure and report across the
   board, never one ticker.
9. **Clocks.** Market logic in ET; the UI shows Central Time. Time is an input: a function that
   depends on the clock takes `now`; only an entry point (a route, a loop, a stream handler)
   reads it.
10. **Tests enforce the requirements.** A test states a requirement and fails when it is broken:
    the missing, invalid, stale and disconnected inputs as well as the normal one. It runs on
    captured Schwab data (`tests/fixtures/`) through the real code; a stand-in is named and never
    by itself makes the claim true; the behavior a test claims to prove is never mocked; its
    expected result is computed independently, never by the function under test. A test that
    approves a violation is corrected; required behavior is never hidden behind xfail, a skip, a
    weakened assertion or a relaxed threshold. Each tier proves only itself: producer (unit),
    intake and consumers (integration), page against served results (browser), processes on the
    host, deployed app, live market. Captured-data replay proves behavior, not live operation.
11. **Every assumption has a basis.** A threshold, constant, convention or model choice that
    shapes financial output rests on Schwab's definition, a cited public definition, a committed
    test or study on captured data, or the operator's recorded decision. A basis that cannot be
    reproduced is no basis. Labels say what is actually measured.
12. **Trade-affecting logic is validated.** An output that recommends or classifies a trading
    action (a posture, a regime call, a pin candidate, a signal) is shown only with committed
    evidence: no lookahead or leakage, train/serve parity, out-of-sample results against a
    baseline, costs and calibration. Missing proof does not authorize its use.
13. **Operations are part of the app.** Each runtime responsibility (the two processes, the
    Schwab sign-in, network exposure, disk, backups and restore, deploy and rollback) has an owner
    in code or host configuration and a defined behavior on screen when it fails (`docs/host/`).
    Restored data keeps its provenance and never regains live authority.

## Changing the code

- Before writing: trace each value the change touches against its definition (§ Every value). A
  producer exists: call it. None exists: write it once, on the server, and define it.
- Page code: no arithmetic, sum, min/max, sort by value or date math on served data.
- A value that crosses a module boundary is a typed record (dataclass), its states named
  constants. Imports at the top of the module. One formatter per format, on the server.
- A new check is a behavior test of a requirement, shown failing on the old code or on a named
  broken input. A test never reads source text or pins a private helper; a test whose subject is
  deleted is deleted with it.
- The author runs the tests of the files touched while working, and before offering the PR
  `npm run test:all` and `python -m ruff check . --select F401,F821,E9` on its final commit;
  after any later change the affected tests run again. In market hours the full suite is not run
  locally: push and let CI run it.
- **Independent verification.** Before a PR merges, a reviewer with fresh context (an agent given
  only this file, the definitions the change touches and the diff, or the operator) checks the
  change against them, including every changed test, fixture, expected value, hook and CI step
  for a weakened requirement, and records in the PR what it checked, its evidence and its verdict.
  An agent's agreement is not proof; the verdict rests on the evidence it cites.
- Every factual claim cites same-turn output or is marked `[UNVERIFIED]`. Proof is a committed
  test or a command anyone can re-run; a scratch script is not proof. No hand-maintained counts,
  floors or lists that a check compares against.
- Work another agent wrote is read in full by the agent offering it, as its own work.
- A runtime change is on disk only until the process restarts; say which. Merged is not
  deployed; deployed is production at the merge commit, both processes restarted, the real
  screen checked.

## Close the change

A PR that changes code, a design, a plan or a sequence updates, in the same PR, every affected
instruction, definition, work item, check, test and caller; removes superseded statements and
paths; verifies that the documents agree with the implemented behavior; and lists each affected
path it did not verify as NOT_PROVEN. A finished work item leaves `ACTIVE_PROGRAM.md` in the PR
that finishes it.

## Review verdicts

- **PASS**: every required condition proven. **FAIL**: any condition violated, whatever else
  passed. **NOT_PROVEN**: any condition without proof. Never PASS with a FAIL or NOT_PROVEN open.
- Name the tier of each proof; a pass at one tier does not stand in for another. A check proves
  only the paths it covers. A changed test expectation cites the requirement that changed.
- Governance being correct does not make the application compliant: each is proven on its own.

## Found broken → fix it

At its source (rule 1), or name the exact blocker. "Pre-existing", "out of scope" and "follow-up"
are not dispositions. A defect that shows a wrong, stale or unsupported value as current comes
before other work; until it is fixed it is in `ACTIVE_PROGRAM.md` with its evidence (observed,
code-proven or unverified), owner, blocker and closure proof.

## Authority

- Checkpoints: about every 15 minutes the agent reports what changed, what was deleted, each proof
  and its tier, and what is NOT_PROVEN, then continues.
- The agent merges a PR when its required proof on its final commit is complete, CI is green and
  the independent verification is recorded with PASS.
- Stop for: the operator's STOP / PAUSE / HANG IT UP / DO NOT CONTINUE; a task marked AUDIT ONLY
  or DO NOT MERGE; a destructive data action; a product decision code cannot settle; a direction
  or change that conflicts with a rule, or may.
- Production checkout `EdWebConsole`: `main == origin/main`, changed only by `git pull --ff-only`.
  Work in a worktree. May restart the console and the capture daemon; confirm both came back.
- Never: `git reset`, `git checkout --`, `git stash`, force push, `--no-verify`, `git add -A` /
  `.`, pushing to `main` (it changes only through a PR), deleting anything under `data/` or
  `backups/`, editing source through a script (edits are made one at a time, as written),
  changing a file's line endings in an edit.
- Shell steps that depend on each other are joined with `&&`, so a failure stops the chain.
- What is enforced, and what is not. Commit hook (`.pre-commit-config.yaml`): secrets and
  private-path scan, line endings, the virtualenv, ruff (F401, F821, E9). CI, required on `main`
  (Linux): ruff, a compile pass, Playwright, pytest. Agent hooks (`.claude/settings.json`,
  `.cursor/hooks.json`): every "Never" above but editing through a script, plus edits of the
  production checkout. GitHub: `main` takes a change only through a PR with both checks green; no
  review is required. Nothing else enforces a rule except the behavior test written for it.
  Written rules, saved memories and green CI guarantee nothing: a rule with no test or control
  that fails when it is broken is NOT_PROVEN and listed in `ACTIVE_PROGRAM.md`.

## Running it

- Console: `start_ed_console.bat` (`uvicorn server:app`, port 8000). Capture daemon:
  `start_capture_daemon.bat`. Python 3.13, the project `.venv`.
- Offline: `ED_CI_OFFLINE=1`, placeholder `SCHWAB_API_KEY` / `SCHWAB_APP_SECRET`. Live:
  `schwab_token.json` (`python reauth_schwab.py`). Probe `127.0.0.1`, never `localhost`.
