# Ed Console — rules for every change

Before writing a change, read the parts it touches of `docs/DATA_FLOW.md` (design), `ACTIVE_PROGRAM.md` (work order),
`docs/ARCHITECTURE.md` (code map) and `docs/PRACTICES.md`. Rules for one area load with its files (`.claude/rules/`);
procedures are skills (`.claude/skills/`). A change that breaks a rule stops and goes to the operator.

Every requirement in a section marked (enforced), here, in `.claude/rules/` and in `docs/DATA_FLOW.md`, ends with
"Enforced by:" naming the test, hook or required check that blocks a violation, or "no machine check" and the ENF item in
`ACTIVE_PROGRAM.md` that builds one. Enforced by: `tests/test_governing_docs_v1.py`.

## Shared rules (master copy: the operator's wording, identical to his project instructions; a change is proposed to him separately)

### First gate (EdWebConsole)
Applies to every proposal: Ed's, the prompt builder's, and Claude's.
EdWebConsole is a wiring job. Every value has exactly one producer and any number of consumers.
- Schwab fields are wired straight to the screen. Schwab is the producer. Each is listed in the Schwab field list.
- Derived values exist only where Schwab does not send the value. Each is computed once by its one canonical derived producer and listed in the canonical derived register, with its definition and why Schwab does not supply it.
Check every request and every proposal:
1. For each value it touches: which Schwab field, or which canonical derived producer?
2. Would it compute something Schwab sends, create a second producer, or add a derived value not in the register?
3. Would it add code, tests, checks, tables, or tools beyond what is needed to wire Schwab's values, run the canonical producers, and test and enforce both?
If anything fails, report what failed and why, and leave the failing part out. Claude proposes the smallest, simplest path that passes, using the repo. That proposal is checked against this gate before it goes to Ed for approval.
4. For every problem, first answer why it happens, down to the code or data that causes it, with evidence. Only then the fix. Never offer a choice about limits, settings or tests until the cause is known.
5. Every item labeled NOT VERIFIED gets verified, and every item labeled SEEN, NOT FIXED gets fixed at the source, before the work is reported done. An item that can't be closed comes to Ed as a decision, with its evidence and the reason.
Enforced by (items 4 and 5): `.claude/skills/before-done/SKILL.md` step 7 and `.claude/skills/flaky-test-fix/SKILL.md`.

### Standard of care
Hold EdWebConsole to how a financial institution handles systems with real money on the line. These are judgments to apply to every proposal, not things to build:
- System of record: Schwab is the statement. Our data matches it, and any difference is reported, never plugged.
- Records stand: received data is never overwritten or deleted. A correction is a new, labeled entry. Data is deleted only by the keep rule Ed sets.
- Unknowns surface: an unknown shows as unknown, never estimated or filled in.
- Change control: no change reaches production without Ed's approval, and one approval covers the change.
- Four eyes: whoever builds a change is not the only one who verifies it. Two read-only reviewers check every change: an architecture reviewer, against the First gate, and a correctness reviewer, that the change does what it claims, with evidence. While the repo is being brought under control, this applies to every change. Once Ed decides it is stable, it narrows to changes touching stored data, money values, or production.

### EdWebConsole requirements
- Fix problems at the source, and remove what the fix replaces.
- Clean up along the way in the area changed, listing each item. Behavior or data changes need approval.
- Zero is a value; missing is unknown. Never treat one as the other.
- Tests use only real captured data, with expected results from verified definitions. No fake data.
- Every ticker is treated the same.
- Treat existing code, tests, and documents as claims to challenge.
- Display live values promptly and record everything completely. Measure performance; don't assume it.
- Verify end to end, including the actual screen.
- Run authorized inspection and testing without asking.
- Protect credentials and unrelated work.
- Label findings as confirmed evidence, induced test conditions, hypotheses, or NOT_PROVEN.

## Rules (enforced) (operator)

1. **Simple.** Fewest files, functions and hops that do the job. No prose in code: history, incidents and dates go in
   the commit message. No patches: a defect is fixed where it is produced, by changing or deleting that code, never by a
   guard, wrapper, flag, special case or check around it. If that takes a restructure, the restructure is the fix. Every
   fix is end to end: Schwab to the screen. Nothing new (process, cache, helper, file, check) without a job its existing
   owner cannot do, shown in the PR; an existing piece that cannot show one is removed.
   Enforced by: `tools/check_end_to_end.py` in the required `hardening` job (`.github/workflows/hardening.yml`,
   `tests/test_check_end_to_end_v1.py`) refuses a pull request that changes product code without a real line added to an
   end-to-end path test, that adds a patch shape (a catch-all or swallowing except that does not log,
   `contextlib.suppress`, a literal standing in for a missing value), or whose description lacks "Schwab → screen:",
   "Deleted:" or "End-to-end test:"; the path tests of `docs/DATA_FLOW.md` §2 fail a broken path; a design-level patch —
   ENF-01.
2. **Schwab fields as sent.** Not a number: absent, -999, text, NaN or infinity, and a value Schwab's own field
   definition excludes (a negative volume or size). Everything else is taken as sent; a reported 0 is 0. No other
   bounds, no substitution. What Schwab sends or accepts is settled by Schwab's own documentation, cited by section:
   `docs/schwab/schwab_market_data_api_spec.pdf` (Market Data API, with
   `docs/schwab/schwab_market_data_parameters_chains_quotes.txt` for the expanded /chains and /quotes parameters) and
   `docs/schwab/schwab_streamer_api.pdf` (Streamer API), from Schwab's Developer Portal. A limit not stated there or in
   Schwab's own reply is our defect until shown otherwise.
   Enforced by: `tests/test_schwab_as_sent_v1.py`, `tests/test_absence_is_not_zero_v1.py`; the documentation authority — ENF-21.
3. **One authority.** Each value served, stored or shown has one computation authority.
   Consumers carry its result; they never select, compute, repair or relabel it. A second authority
   for the same value is banned whatever it is called: helper, parser, resolver or cache.
   Enforced by: `tests/test_page_one_faucet_v1.py`, `tests/test_one_levels_producer_v1.py`; the rest — ENF-02.
4. **The UI computes nothing.** Page code formats and draws. Every number, total, choice,
   comparison and date the page shows is served.
   Enforced by: no machine check — ENF-03.
5. **The numbers.** The Standard of care applies to every value the app shows or calculates, at all times. Every value
   comes from its one producer (First gate) and matches what Schwab sent (System of record). Calculations keep every
   digit and use every contract Schwab sends; rounding happens only on screen. Every value is shown with its time. While
   it keeps updating, it is live. When it stops updating, for any reason (feed down, market closed, an input missing),
   the last value stands, marked not live with its time and age, and every value computed from it is marked not live
   too; during a feed outage the header says OFFLINE. A value never received, or sent by Schwab as invalid (such as
   -999), shows as unknown with its reason. Never a fallback, default, estimate, proxy, interpolation or synthetic value.
   Enforced by: `tests/test_live_quote_and_order_flow_no_fallbacks_v1.py`, `tests/test_gamma_exposure_honest_absence_v1.py`
   and `tests/test_absence_is_not_zero_v1.py` (Schwab's value as sent, unknown when never sent); the rest — ENF-22.
6. **One path.** Schwab → daemon memory → pushed to the screen. The databases are history:
   `stream_capture.db` every equity message and the kept option contracts for five trading
   sessions (DATA_FLOW D4); `ed_console.db` the chain captures and level crosses; read at
   startup, after the close and for research; never for a live screen.
   Enforced by: `docs/DATA_FLOW.md` §2 D1–D6, each with its own test.
7. **Nothing without a job.** A change deletes what it replaces, in the same PR. A register, audit,
   report or check lives only while it has a job; once answered, it is deleted.
   Enforced by: ruff F401 at commit and in the required `hardening` job; the rest — ENF-04.
8. **All tickers.** Measure and report across every watchlist ticker, never one ticker.
   Enforced by: no machine check — ENF-05.
9. **Clocks.** Market logic in ET; the UI shows Central Time. The market's sessions are Schwab's
   /markets answers; no session table is typed by hand.
   Enforced by: `tests/test_time_et_authority.py`, `tests/test_markets_sessions_v1.py`; the Central
   Time display — ENF-06.
10. **Real data.** Tests run on captured Schwab data (`tests/fixtures/`) through the real code; no stand-ins.
    Enforced by: no machine check — ENF-07.

## Before writing code (enforced)

- Trace each value the change touches: its source, its one producer, its validity rule and time,
  its live and stored consumers, and what each shows when it is missing. A producer exists: call it.
  None exists: write it once, on the server. Enforced by: no machine check — ENF-08.
- Name each touched responsibility's one lifecycle owner (what starts, refreshes, retries and expires
  it) and what fails when that owner fails, in `docs/DATA_FLOW.md` and in the code.
  Enforced by: no machine check — ENF-08.
- A new check is a test of behavior for a failure that happened, fails on the old code, and starts
  with no exceptions. Enforced by: `tools/check_fails_before.py` in the required `pytest-full` job
  (`tests/test_check_fails_before_v1.py`); the rest — ENF-08.
- A function that depends on the clock takes `now`; only an entry point (a route, a loop, a stream
  handler) reads the clock. Enforced by: no machine check — ENF-09.
- A value that crosses a module boundary is a typed record (dataclass) whose states are named
  constants. Enforced by: no machine check — ENF-10.
- Imports at the top of the module. One formatter per format (price, Central Time, dollars), on the
  server. Enforced by: no machine check — ENF-11.

## Before saying done (enforced)

- The `before-done` skill's checks pass on the PR's final commit, their output shown, before the PR
  is offered. Enforced by: branch protection on `main` requires `pytest-full`
  (`.github/workflows/pytest.yml`) and `hardening` (`.github/workflows/hardening.yml`) on the final
  commit, current with `main`; the commit hook and `tools/ruff_edited_file.py` run ruff; the Stop hook
  `tools/stop_gate.py` holds the turn until ruff and the touched test files pass.
- Claims. Every statement about how something is now (a process, a file, a branch, a pull request, a test result,
  data, the screen) is CONFIRMED only by command output shown in the same reply. Anything else is NOT VERIFIED, with
  when it was last checked. An earlier check is not current evidence; state changes. This applies to every part of a
  reply, including summaries, "seen, not fixed" and next steps. Definitions: "Done" = a test that failed before passes
  after, the full suite passes, and the live screen shows it working (a PR with no app code gets no screen check).
  "Across the board" = every watchlist ticker, not one. Enforced by: no machine check — ENF-12.
- Proof is a committed test or a command anyone can re-run. "Pre-existing", "out of scope" and
  "follow-up" are not dispositions. Enforced by: no machine check — ENF-12.
- No hand-maintained count, floor or list that a check compares against; the check computes it.
  Enforced by: no machine check — ENF-12.
- Work another agent wrote is read in full by the agent offering the PR. Enforced by: no machine
  check — ENF-12.
- Say whether a runtime change is live or on disk until a restart. Deployed means production at the
  merge commit, both processes restarted, and the screen checked during market hours (the `deploy`
  skill). Enforced by: no machine check — ENF-12.
- Never kill a commit hook mid-run. Enforced by: no machine check — ENF-12.

## Close the change (enforced)

- A PR updates, in itself, every instruction, design, work item, check, test and caller its change
  affects, removes what it supersedes, and lists each affected path without proof as NOT_PROVEN. A
  finished work item leaves `ACTIVE_PROGRAM.md` in the PR that finishes it.
  Enforced by: `tests/test_governing_docs_v1.py` (every path named exists); the rest — ENF-12.
- Each decision the operator gives in chat is written into `ACTIVE_PROGRAM.md` or this file in the PR
  that acts on it. Enforced by: no machine check — ENF-12.

## Review verdicts (enforced)

- **PASS**: every required condition proven. **FAIL**: any condition violated. **NOT_PROVEN**: any
  condition without proof. A proof is CONFIRMED evidence on the final commit and names its tier (unit,
  integration, browser, deployed app, live market); one tier never stands in for another, and a check
  proves only the paths it covers. Never PASS with a FAIL or NOT_PROVEN open. NOT_PROVEN judges a change; NOT
  VERIFIED labels a statement ("Claims"). `docs/PRACTICES.md` §H, the First gate's "the prompt builder"
  and the Shared rules' "NOT_PROVEN" in their labels line stay as written. Enforced by: no machine check — ENF-12.
- The two reviewers (`.claude/agents/correctness-reviewer.md`; `.claude/agents/requirements-reviewer.md`, the
  architecture reviewer, which starts with the First gate) check every change, because the operator has not decided the
  repo is stable, and flag only correctness problems and breaks of the stated requirements.
  `.claude/skills/before-done/SKILL.md` step 7 runs them. Enforced by: no machine check — ENF-12.

## Authority (enforced)

- At each milestone (a commit, a failed check, a finding that changes the plan), report to the operator
  what changed, what was deleted, each proof and its tier, and what is NOT_PROVEN, then continue.
  Enforced by: no machine check — ENF-12.
- A PR merges on the operator's yes after CI is green on its final commit; that yes also covers its deploy, and a
  merge on the GitHub page is the operator's own. No CODEOWNERS file. Enforced by: branch protection on `main` requires
  `.github/workflows/pytest.yml` and `.github/workflows/hardening.yml` to pass on a branch current with `main`;
  `tools/operator_yes_guard.py` asks Allow/Deny for the merge routes its tests cover (`tests/test_operator_yes_guard_v1.py`);
  a merge from inside a heredoc body, `python -c`, a script file or a query held in a variable, and no CODEOWNERS — ENF-12.
- Stop for the operator's STOP / PAUSE / HANG IT UP / DO NOT CONTINUE / NO, a task marked AUDIT ONLY
  or DO NOT MERGE, a destructive data action, and a product decision code cannot settle. Say in chat
  what a guarded action is for before running it. Enforced by: `tools/operator_yes_guard.py` asks Allow/Deny for
  the daemon or console starts and stops (in regular hours or an unknown session), machine restarts and merges, and
  refuses the kills of production and pushes to main, in the forms its tests cover (`tests/test_operator_yes_guard_v1.py`); the
  rest — ENF-12.
- The production checkout `EdWebConsole` stays `main == origin/main` and moves only by a fast-forward
  (`git pull --ff-only`, or `launch.bring_to_origin_main` at a start); work happens in a worktree.
  Enforced by: `tools/process_lock_guard.py` (`tests/test_operating_process_lock_v1.py`,
  `tests/test_hook_chain_v1.py`).
- Never `git reset`, `git checkout --`, `git stash` or a force push. Enforced by: `tools/process_lock_guard.py` for
  the forms its test table refuses (`tests/test_reset_guard_v1.py`); every other form — ENF-12.
- Never `--no-verify`, `git add -A` / `.`, delete or move anything under `data/`, a python reading its program from
  stdin (use a script file or `python -c`), or a command the guards cannot see into (a `$variable` as the program, text
  piped into a shell or interpreter, `-EncodedCommand`, `Invoke-Expression`). Enforced by: `tools/operator_law_guard.py`,
  in the forms its tests cover (`tests/test_operator_law_guard_action_bans_v1.py`, `tests/test_protected_paths_v1.py`,
  `tests/test_guards_read_statements_v1.py`); a script file's contents — ENF-12.
- Edit source one edit at a time, never through a script. Enforced by: `tools/sed_edit_guard.py`
  (`tests/test_sed_edit_guard_v1.py`); the other in-place editors — ENF-14.
- A file keeps its line endings. Enforced by: `tools/check_eol_style_invariant.py`
  (`tests/test_eol_style_invariant_v1.py`).
- No credential or operator-home path is committed. Enforced by: `tools/check_credential_leak.py`
  (`tests/test_credential_leak_v1.py`).
- Shell steps that depend on each other are joined with `&&`. Enforced by: no machine check — ENF-12.
