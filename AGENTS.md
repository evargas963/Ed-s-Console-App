# Ed Console — rules for every change

Design: `docs/DATA_FLOW.md`. Work order: `ACTIVE_PROGRAM.md`. Code map: `docs/ARCHITECTURE.md`.
Read the parts a change touches before writing it.

Every requirement in a section marked (enforced), in this file and in `docs/DATA_FLOW.md`, ends
with "Enforced by:" naming the test, hook or required check that blocks a violation, or, where
none exists yet, "no machine check" and the ENF work item in `ACTIVE_PROGRAM.md` that builds one.
Enforced by: `tests/test_governing_docs_v1.py` fails CI when a requirement lacks the line, names
a file that does not exist, or names an ENF item that is not in `ACTIVE_PROGRAM.md`.

## Rules (enforced) (operator; a change that cannot meet one stops and goes to the operator)

1. **Simple.** Fewest files, functions and hops that do the job. No prose in code: history,
   incidents and dates go in the commit message. No patches: a defect is fixed where it is
   produced, by changing or deleting that code, never by a guard, wrapper, flag, special case or
   check around it. If that takes a restructure, the restructure is the fix. Every fix is end to
   end: Schwab to the screen. Nothing new (process, cache, helper, file, check) without a job its
   existing owner cannot do, shown in the PR; an existing piece that cannot show one is removed.
   Enforced by: `tools/check_end_to_end.py` in the required `hardening` job
   (`.github/workflows/hardening.yml`) refuses every pull request that changes product code
   without adding a real line to an end-to-end path test, that adds a patch shape (a catch-all
   or swallowing except, `contextlib.suppress`, a literal standing in for a missing value,
   missing data repaired), or whose description lacks "Schwab → screen:", "Deleted:" or
   "End-to-end test:" or leaves one empty (`tests/test_check_end_to_end_v1.py`). It checks code
   shapes only. The path tests of `docs/DATA_FLOW.md` §2 fail any change that leaves the path
   broken. What no machine can see (a design-level patch, a test that does not cover the change)
   — ENF-01.
2. **Schwab fields as sent.** Not a number: absent, -999, text, NaN or infinity, and a value
   Schwab's own field definition excludes (a negative volume or size). Everything else is taken
   as sent; a reported 0 is 0. No other bounds, no substitution. What Schwab sends or accepts is
   settled by Schwab's own documentation, cited by section: `docs/schwab/schwab_market_data_api_spec.pdf`
   (Market Data API, with `docs/schwab/schwab_market_data_parameters_chains_quotes.txt` for the
   expanded /chains and /quotes parameters) and `docs/schwab/schwab_streamer_api.pdf` (Streamer API), from
   Schwab's Developer Portal (operator 2026-10-05). A limit not stated there or in Schwab's own
   reply is our defect until shown otherwise.
   Enforced by: `tests/test_schwab_as_sent_v1.py`, `tests/test_absence_is_not_zero_v1.py`.
3. **One authority.** Each value served, stored or shown has one computation authority.
   Consumers carry its result; they never select, compute, repair or relabel it. A second authority
   for the same value is banned whatever it is called: helper, parser, resolver or cache.
   Enforced by: `tests/test_page_one_faucet_v1.py`, `tests/test_one_levels_producer_v1.py` for
   the values they drive; the second producers found 2026-10-02 — ENF-02.
4. **The UI computes nothing.** Page code formats and draws. Every number, total, choice,
   comparison and date the page shows is served.
   Enforced by: no machine check — ENF-03.
5. **No substitute paths.** Like a bank balance: live while the market is open, and the balance as
   of the close while it is closed. In an open session a value whose feed is down, or whose input
   is missing or invalid, has no current value: it is shown absent with its reason. While Closed,
   the values as of the close stand until the next session. No value is labeled "past"; no
   fallback, default, estimate, proxy, carry-forward, interpolation or synthetic value. Test: when
   the source cannot produce the value now in an open session, the screen shows it absent with its
   reason, never a value from elsewhere.
   Enforced by: `tests/test_live_quote_and_order_flow_no_fallbacks_v1.py`,
   `tests/test_gamma_exposure_honest_absence_v1.py`, and `docs/DATA_FLOW.md` §2 D5.
6. **One path.** Schwab → daemon memory → pushed to the screen. The database is history: one
   writer; read at startup, after the close and for research; never for a live screen.
   Enforced by: `docs/DATA_FLOW.md` §2 D1–D6, each with its own test.
7. **Nothing without a job.** A change deletes what it replaces, in the same PR. A register, audit,
   report or check lives only while it has a job; once answered, it is deleted.
   Enforced by: ruff F401 (unused imports) at commit and in the required `hardening` check; the
   rest — ENF-04.
8. **All tickers.** Measure and report across the board, never one ticker.
   Enforced by: no machine check — ENF-05.
9. **Clocks.** Market logic in ET; the UI shows Central Time.
   Enforced by: `tests/test_time_et_authority.py`, `tests/test_session_calendar_authority_v1.py`
   (ET); the Central Time display — ENF-06.
10. **Real data.** Tests run on captured Schwab data (`tests/fixtures/`) through the real code.
    A stand-in (e.g. the live price) is named in the test.
    Enforced by: no machine check — ENF-07.

## Before writing code (enforced)

- Trace each value the change touches: its source, its one producer, its validity rule and time,
  its live and stored consumers, and what each shows when the value is missing. A producer
  exists: call it. None exists: write it once, on the server. Enforced by: no machine check — ENF-08.
- For each responsibility the change touches, name its one lifecycle owner (what starts,
  refreshes, retries and expires it) and what fails when that owner fails, in the affected
  section of `docs/DATA_FLOW.md` and in the code. Enforced by: no machine check — ENF-08.
- Page code: no arithmetic, sum, min/max, sort by value or date math on served data.
  Enforced by: no machine check — ENF-03.
- A new check is a test of behavior, for a failure that happened; it fails on the old code; it
  starts with no exceptions. Enforced by: `tools/check_fails_before.py` in the required
  `pytest-full` job refuses a PR that changes product code unless one of its changed tests fails
  on the base (`tests/test_check_fails_before_v1.py`); the rest — ENF-08.
- Time is an input: a function that depends on the clock takes `now`; only an entry point (a
  route, a loop, a stream handler) reads the clock. Enforced by: no machine check — ENF-09.
- A value that crosses a module boundary is a typed record (dataclass), not a dict of string keys;
  its states are named constants, not free strings. Enforced by: no machine check — ENF-10.
- Imports at the top of the module. One formatter per format (price, Central Time, dollars), on
  the server. Enforced by: no machine check — ENF-11.
- A test exercises behavior through the real code. It never reads source text or pins a private
  helper; a test whose subject is deleted is deleted with it. Enforced by: no machine check — ENF-08.
- A test, fixture or helper a pull request adds or changes never patches the code it tests
  (monkeypatch, mock.patch, a fixture that does, or a patching autouse fixture in its file);
  the existing ones are cleaned as their files are touched. Enforced by:
  `tools/check_no_new_patches.py` in the required `hardening` job
  (`tests/test_check_no_new_patches_v1.py`); the existing ones — TEST-PATCHES.

## Before saying done (enforced)

- While working: the tests of the files touched. Before the PR is offered: `npm run test:all`
  (Playwright, then pytest) and `python -m ruff check . --select F401,F821,E9` on its final
  commit. Enforced by: GitHub branch protection on `main` requires `pytest-full`
  (`.github/workflows/pytest.yml`: Playwright, then pytest) and `hardening`
  (`.github/workflows/hardening.yml`: ruff, compile) to pass on the branch's final commit, kept
  current with `main`; the pre-commit hooks run ruff on every commit.
- Never kill a commit hook mid-run; a long one runs in the background. Enforced by: no machine
  check — ENF-12.
- Claims. Every statement about how something is now (a process, a file, a branch, a pull
  request, a test result, data, the screen) is CONFIRMED only by command output shown in the
  same reply. Anything else is NOT VERIFIED, with when it was last checked. An earlier check
  is not current evidence; state changes. This applies to every part of a reply, including
  summaries, "seen, not fixed" and next steps. Enforced by: no machine check — ENF-12.
- Proof is reproducible: a committed test or a command anyone can re-run. A scratch script is
  not proof. Enforced by: no machine check — ENF-12.
- No hand-maintained counts, floors or lists that a check compares against; the check computes
  them. Enforced by: no machine check — ENF-12.
- Work another agent wrote is read in full by the agent offering the PR, as its own work.
  Enforced by: no machine check — ENF-12.
- A runtime change is on disk only until the process restarts after it; say which. Merged is not
  deployed; deployed is production at the merge commit, both processes restarted, the real screen
  checked during market hours. Enforced by: no machine check — ENF-12.

## Close the change (enforced)

- A PR that changes code, a design, a plan or a sequence updates, in the same PR, every affected
  instruction, design, work item, check, test and caller; removes superseded statements and
  paths; and lists each affected path without proof as NOT_PROVEN. A finished work item
  leaves `ACTIVE_PROGRAM.md` in the PR that finishes it. Enforced by:
  `tests/test_governing_docs_v1.py` (every path the documents name exists); the rest — ENF-12.

## Review verdicts (enforced)

- A verdict judges a change against its requirements; it is not a label on a statement (that is
  "Claims", above). **PASS**: every required condition proven. **FAIL**: any condition violated.
  **NOT_PROVEN**: any condition without proof. A proof is CONFIRMED evidence on the change's
  final commit; evidence from an earlier commit or an earlier check proves nothing for it. Never
  PASS with a FAIL or NOT_PROVEN open. Each proof names its tier: unit, integration, browser,
  deployed app, live market; one tier never stands in for another. A check proves only the
  paths it covers. Enforced by: no machine check — ENF-12.

## Found broken → fix it (enforced)

- Same session, at its source, end to end (rule 1), or name the exact blocker. "Pre-existing",
  "out of scope" and "follow-up" are not dispositions. Enforced by: no machine check — ENF-12.

## Authority (enforced)

- Checkpoints: about every 15 minutes of work the agent reports to the operator what changed,
  what was deleted, each proof and its tier, and which requirements are NOT_PROVEN, then continues.
  Enforced by: no machine check — ENF-12.
- A PR merges when its required proof on its final commit is complete and CI is green; green CI
  alone is not proof. Enforced by: GitHub branch protection requires the `pytest-full` job of
  `.github/workflows/pytest.yml` and the `hardening` job of `.github/workflows/hardening.yml`,
  on a branch current with `main`.
- A change to AGENTS.md, `docs/DATA_FLOW.md`, CI, a hook or a check is merged only by the
  operator. Enforced by: no machine check — ENF-13.
- Stop for: the operator's STOP / PAUSE / HANG IT UP / DO NOT CONTINUE / NO; a task marked AUDIT
  ONLY or DO NOT MERGE; a destructive data action; a product decision code cannot settle; an
  operator setting (a count, a rate, a switch) is never changed without the operator's explicit
  yes to that change. Enforced by: the agent hook `tools/operator_yes_guard.py` puts a start,
  stop or restart of the daemon or console, a merge, a push to main and a change to a test on
  main to the operator as an Allow/Deny prompt (`tests/test_operator_yes_guard_v1.py`); the
  rest — ENF-12.
- Production checkout `EdWebConsole`: `main == origin/main`, changed only by `git pull --ff-only`.
  Work in a worktree; main itself moves only by a PR merged on GitHub. Enforced by: the agent hook
  `tools/process_lock_guard.py` refuses an edit, a shell write or a git verb that moves it off
  main (`tests/test_operating_process_lock_v1.py`), and a git command from any checkout that
  writes `refs/heads/main` (`tests/test_hook_chain_v1.py`).
- Never: `git reset`, `git checkout --`, `git stash`, force push. Enforced by: the agent hook
  `tools/process_lock_guard.py` (`tests/test_reset_guard_v1.py`).
- Never: `--no-verify`, `git add -A` / `.`, deleting or moving anything under `data/` or
  `backups/`. Enforced by: the agent hook `tools/operator_law_guard.py`
  (`tests/test_operator_law_guard_action_bans_v1.py`, `tests/test_protected_paths_v1.py`).
- Never edit source through a script: edits are made one at a time, as written; a block too long
  for one edit is removed in consecutive edits. Enforced by: the agent hook
  `tools/sed_edit_guard.py` refuses a sed that writes a file (`tests/test_sed_edit_guard_v1.py`);
  the other in-place editors — ENF-14.
- A file keeps its line endings (most are LF; some are CRLF). Enforced by: the commit hook
  `tools/check_eol_style_invariant.py` (`tests/test_eol_style_invariant_v1.py`).
- No credential or operator-home path is committed. Enforced by: the commit hook
  `tools/check_credential_leak.py` (`tests/test_credential_leak_v1.py`).
- Shell steps that depend on each other are joined with `&&`, so a failure stops the chain.
  Enforced by: no machine check — ENF-12.

## Running it

Console: `start_ed_console.bat` (`uvicorn server:app`, port 8000). Capture daemon:
`start_capture_daemon.bat`. Python 3.13, the project `.venv`. Offline: `ED_CI_OFFLINE=1`,
placeholder `SCHWAB_API_KEY` / `SCHWAB_APP_SECRET`. Live: `schwab_token.json`
(`python reauth_schwab.py`). Probe `127.0.0.1`, never `localhost`. The agent may restart the
console and the capture daemon, and confirms both came back.
