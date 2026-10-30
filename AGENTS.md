# Ed Console — rules for every change

The app is a wire: Schwab → one program → the page. Every value has one producer. The shape below
is the target (operator 2026-10-29); each rule names the standard tool that enforces it, and the
step of `ACTIVE_PROGRAM.md` SHAPE that turns that check on. Until its step lands, a rule is still
the rule: a change that breaks it stops and goes to the operator.

Read before writing a change: the parts it touches of `docs/DATA_FLOW.md` (the data and its
producers), `docs/ARCHITECTURE.md` (where code lives), `ACTIVE_PROGRAM.md` (the work order) and
`docs/PRACTICES.md` (the Schwab field list). Rules for one area load with its files
(`.claude/rules/`); procedures are skills (`.claude/skills/`).

Every requirement in this file's sections after the Shared rules (whose Standard of care is judgment,
not things to build), in `.claude/rules/` and in `docs/DATA_FLOW.md` names what enforces it: a
test, hook or required check, or "no machine check" and the item in `ACTIVE_PROGRAM.md` (an ENF item
or a SHAPE step) that builds one. Enforced by: no machine check — ENF-12.

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

## The shape (operator 2026-10-29)

One program in five parts, as a bank runs a ledger, a teller window and a journal:

| Part | Owns | Never |
|---|---|---|
| **Feed** | the only code that talks to Schwab (the stream and REST), taking each field as sent | computes a value, writes a database |
| **State** | one in-memory store: the newest value of everything, with its time (the ledger) | keeps a second copy |
| **Calculators** | pure functions: each derived value computed once, when its inputs change, from inputs and `now` passed in | reads a clock, a database, a global or the network |
| **Push** | one WebSocket from the program to the page: a snapshot, then the changes (the teller window) | serves a value State does not hold |
| **Recorder** | the only writer of the databases (the journal) | is read by a live screen |

Hops: Schwab → program → page. Nothing else travels.

Why, from outside practice: one user and one account call for one program (Fowler, "MonolithFirst");
"simple is better than complex" and "flat is better than nested" (PEP 20); build only what is
needed (KISS, YAGNI); systems that work grow from simple ones that work (Gall's law); and rules are
held by standard linters, not by hand-written checks.

## Rules and what enforces them

Each rule names what enforces it and where it runs. "(in force)" means it runs today: at commit
(`.pre-commit-config.yaml`: the credential scan, the line-ending check, `ruff check .`, `ruff format
--check .`) or in the required `hardening` (`.github/workflows/hardening.yml`) or `pytest-full`
(`.github/workflows/pytest.yml`) job. "Step N" is the SHAPE step that turns the check on; until
then the rule binds with no machine check.

| # | Rule | Enforced by |
|---|---|---|
| 1 | **Simple.** Fewest files, functions and hops that do the job. No prose in code: history, incidents and dates go in the commit message. No patches: a defect is fixed where it is produced, by changing or deleting that code, never by a guard, wrapper, flag, special case or check around it; if that takes a restructure, the restructure is the fix. Every fix is end to end: Schwab to the screen. Nothing new (process, cache, helper, file, check) without a job its existing owner cannot do, shown in the PR; an existing piece that cannot show one is removed. A change deletes what it replaces, in the same PR; a register, audit, report or check lives only while it has a job, and once answered, it is deleted. | `tools/check_fails_before.py` in `pytest-full` and `tools/check_end_to_end.py` in `hardening`, on a pull request's change (in force); ruff `S110` (a catch-all `except` passed in silence) over the whole repository (in force); ruff `C90` complexity cap, `SIM`, `B`, `BLE`, `TRY` over the whole repository (step 1b); `check_end_to_end` is deleted in step 7 only once a standard tool refuses every shape its docstring lists (swallowing excepts, missing values replaced or repaired, the page's patch shapes) and what `check_fails_before` imports from it (`code_identical`, `behavior_change`, `deleted_product`) has moved — the shapes left — SHAPE step 7 |
| 2 | **Schwab fields as sent.** Not a number: absent, -999, text, NaN or infinity, a value Schwab's own field definition excludes (a negative volume or size), and a gamma more than twice the largest any option can have at its own volatility, price and time left (operator 2026-10-23). Everything else is taken as sent; a reported 0 is 0. No other bounds, no substitution. What Schwab sends or accepts is settled by Schwab's own documentation, `docs/schwab/schwab_market_data_api_spec.pdf` (with `docs/schwab/schwab_market_data_parameters_chains_quotes.txt` for the expanded /chains and /quotes parameters) and `docs/schwab/schwab_streamer_api.pdf`, cited by section; a limit not stated there or in Schwab's own reply is our defect until shown otherwise. | `tests/test_schwab_as_sent_v1.py`, `tests/test_absence_is_not_zero_v1.py`, `tests/test_data_path_impossible_gamma_v1.py` (in force) |
| 3 | **One producer.** Each value served, stored or shown has one producer; consumers carry its result and never select, compute, repair or relabel it. A second authority for the same value is banned whatever it is called: helper, parser, resolver or cache. One module reads each Schwab field. | `tools/check_one_reader.py` in `hardening` refuses a pull request that adds a second reader (in force); the fields already read by more than one module (`python tools/check_one_reader.py --list`) — ENF-23; import-linter layers (step 1d) |
| 4 | **The page draws; it computes nothing.** Every number, total, choice, comparison and date it shows is served. It gets data only from the one push. | ESLint: `fetch`, `XMLHttpRequest` and `EventSource` only in the transport module (step 4); `Math.*`, `.sort(`, `.reduce(` and date arithmetic banned outside the drawing module (step 5) |
| 5 | **The numbers.** Every value comes from its one producer and matches what Schwab sent. Calculations keep every digit and use every contract; rounding happens only on screen. Every value is shown with its time. While it updates it is live; when it stops, for any reason, the last value stands, marked not live with its time and age, and everything computed from it is marked too; during a feed outage the header says OFFLINE. A value never received, or sent invalid, shows "-". Never a fallback, default, estimate, proxy, interpolation or synthetic value. | `tests/test_live_quote_and_order_flow_no_fallbacks_v1.py`, `tests/test_gamma_exposure_honest_absence_v1.py`, `tests/test_data_path_heatmap_absent_v1.py` (in force) |
| 6 | **One program, one path.** Schwab → program memory → pushed to the page. The databases are history, written by the Recorder, read at startup, after the close and for research, never for a live screen. | import-linter: `sqlite3` only in the Recorder and the startup loader; a test that the launcher starts one process (step 3); the data path tests of `docs/DATA_FLOW.md` §2 (in force) |
| 7 | **All tickers.** Measure and report across every watchlist ticker, never one. Every ticker is treated the same. | no machine check — ENF-05 |
| 8 | **Clocks.** Market logic in ET; the page shows Central Time. The market's sessions are Schwab's /markets answers; no session table is typed by hand. | `tests/test_time_et_authority.py`, `tests/test_markets_sessions_v1.py` (in force) |
| 9 | **Real data.** Tests run on captured Schwab data (`tests/fixtures/`) through the real code; no stand-ins, no patches of the code under test. | `tools/check_no_new_patches.py` with `tools/patch_record.py` in `pytest-full`, on a pull request's change (in force), until ruff `TID251` (no `unittest.mock`) and a conftest that refuses `monkeypatch` replace them (step 7); stand-ins left in the tests — STAND-INS |
| 10 | **Only Feed talks to Schwab.** | import-linter: `schwab`, `httpx` and `authlib` importable only from Feed (step 1d) |
| 11 | **Calculators are pure.** They take `now` and their inputs; they read no clock, database, global or network. Only an entry point (a route, a loop, a stream handler) reads the clock. | import-linter forbidden imports and ruff `TID251` banned `time.time` / `datetime.now` outside the entry points (step 2) |
| 12 | **Typed records across boundaries.** A value that crosses a module boundary is a dataclass whose states are named constants. | pyright, strict on State, Calculators and Push (step 6) |
| 13 | **Python's guidelines.** PEP 8 and PEP 257 as `ruff format` and ruff's rules read them; PEP 20 as the shape. Imports at the top. One formatter per format (price, Central Time, dollars), on the server (no machine check — ENF-11). | `ruff format` and ruff `UP`, `W` and `S110` (in force; `UP042` deselected, its one fix unsafe, in `pyproject.toml`); ruff `E`, `B`, `SIM`, `BLE`, `TRY`, `C90`, `I` (step 1b), `D` (pep257, no docstring required; step 1c) |

## Fix what you find (operator 2026-10-29: "fix what you find anywhere, everywhere, repo wide")

- A defect found anywhere in the repository, while doing any task, is fixed: in the task that
  found it, or as the next small PR when it lies outside that task's files. "Pre-existing", "out of
  scope" and "follow-up" are not dispositions. A row in `ACTIVE_PROGRAM.md` holds a found defect
  only as the next work in its order, never as a place to leave it. A standard tool's own fix for
  what its check flags (`ruff format`, `ruff check --fix`) needs no separate yes; never an unsafe
  fix (operator 2026-10-29: "I DID NOT ALLOW FOR ANY UNSAFE FIXES"): no `--unsafe-fixes`, no
  `unsafe-fixes` or `extend-safe-fixes` in `pyproject.toml`, and a rule whose only fix is unsafe
  stays deselected. Enforced by: `tools/check_end_to_end.py` takes only ruff's safe fixes as the
  tools' own, and none at all when ruff's own resolved settings for the committed `pyproject.toml`
  (extended files included) turn unsafe fixes on, force a fix safe, or target another Python than
  the base's, so an unsafe rewrite of a product file is a product change that needs its failing test
  (`tests/test_check_end_to_end_v1.py`); the rest of this bullet (a found defect fixed, those
  settings themselves, an unsafe rewrite outside product code) — no machine check, ENF-12.
- A check runs over the whole repository wherever it can, so a finding anywhere fails the required
  job and nothing merges while it stands; a check is turned on only once what it finds repo-wide is
  fixed, never with an exception list. Enforced by: `ruff check .` and `ruff format --check .` over
  the whole repository at commit and in `hardening` (in force); each tool SHAPE adds (import-linter,
  ESLint, pyright) runs over the whole repository the same way (steps 1d to 6). Today's hand-built
  checks judge a pull request's change only (`check_end_to_end`, `check_one_reader`,
  `check_credential_leak`, `check_eol_style_invariant`, `check_fails_before`,
  `check_no_new_patches`, each with `--base`); step 7 deletes or replaces them.

## Before writing code

- Trace each value it touches: its source, its one producer, its validity rule and time, its live
  and stored consumers, and what each shows when it is missing. A producer exists: call it. None
  exists: write it once, in its part. Enforced by: no machine check — ENF-08.
- Name each touched responsibility's one lifecycle owner (what starts, refreshes, retries and
  expires it) and what fails when that owner fails, in `docs/DATA_FLOW.md` and in the code.
  Enforced by: no machine check — ENF-08.
- A function that depends on the clock takes `now`; only an entry point (a route, a loop, a stream
  handler) reads the clock. Enforced by: ruff `TID251` (SHAPE step 2); until then no machine check — ENF-09.
- A new check is a test of behavior for a failure that happened, fails on the old code, and starts
  with no exceptions. Enforced by: `tools/check_fails_before.py` in `pytest-full`
  (`tests/test_check_fails_before_v1.py`).
- Edit source by hand, one edit at a time, never through a script; the exceptions are ENF-14's (a
  standard tool's own fix, `ruff format` and ruff's safe fixes; `unix2dos`/`dos2unix` for line
  endings). Enforced by: `tools/operator_law_guard.py` for
  sed (`tests/test_sed_edit_guard_v1.py`); the other in-place editors — ENF-14.

## Before saying done

- The `before-done` skill's checks pass on the PR's final commit, their output shown. Branch
  protection on `main` requires `pytest-full` and `hardening` on the final commit, current with
  `main`.
- Claims. Every statement about how something is now (a process, a file, a branch, a pull request,
  a test result, data, the screen) is CONFIRMED only by command output shown in the same reply.
  Anything else is NOT VERIFIED, with when it was last checked. "Done" = a test that failed before
  passes after, the full suite passes, and the live screen shows it working (a PR with no app code
  gets no screen check). "Across the board" = every watchlist ticker. Proof is a committed test or
  a command anyone can re-run. Enforced by: no machine check — ENF-12.
- No hand-maintained count, floor or list that a check compares against; the check computes it.
  Enforced by: no machine check — ENF-12.
- Work another agent wrote is read in full by the agent offering the PR. Enforced by: no machine
  check — ENF-12.
- Say whether a runtime change is live or on disk until a restart. Deployed means production at the
  merge commit, restarted, and the screen checked during market hours (the `deploy` skill).
  Enforced by: no machine check — ENF-12.
- Never kill a commit hook mid-run. Enforced by: no machine check — ENF-12.
- Settle code, test and design questions with these rules, the banking analogy, Python's guidelines
  and outside research, and say what was decided and why. Bring the operator what is his:
  production starts and stops in regular hours; changes to request rates, limits and settings;
  behavior or data changes; money. Enforced by: no machine check — ENF-12.

## Close the change

- A PR updates, in itself, every instruction, design, work item, check, test and caller its change
  affects, removes what it supersedes, and lists each affected path without proof as NOT_PROVEN. A
  finished work item leaves `ACTIVE_PROGRAM.md` in the PR that finishes it. Enforced by:
  `tests/test_governing_docs_v1.py` (every path named exists); the rest — ENF-12.
- Each decision the operator gives in chat is written into `ACTIVE_PROGRAM.md` or this file in the
  PR that acts on it. Enforced by: no machine check — ENF-12.

## Review verdicts

- **PASS**: every required condition proven. **FAIL**: any condition violated. **NOT_PROVEN**: any
  condition without proof. A proof is CONFIRMED evidence on the final commit and names its tier
  (unit, integration, browser, deployed app, live market); one tier never stands in for another, and
  a check proves only the paths it covers. Never PASS with a FAIL or NOT_PROVEN open. NOT_PROVEN
  judges a change; NOT VERIFIED labels a statement. `docs/PRACTICES.md` §H, the First gate's "the
  prompt builder" and the Shared rules' "NOT_PROVEN" in their labels line stay as written.
- The two reviewers (`.claude/agents/correctness-reviewer.md`; `.claude/agents/requirements-reviewer.md`,
  the architecture reviewer, which starts with the First gate) check every change, because the
  operator has not decided the repo is stable, and flag only correctness problems and breaks of the
  stated requirements. `.claude/skills/before-done/SKILL.md` step 7 runs them.

## Authority

- At each milestone (a commit, a failed check, a finding that changes the plan), report to the
  operator what changed, what was deleted, each proof and its tier, and what is NOT_PROVEN, then
  continue. Enforced by: no machine check — ENF-12.
- A PR merges, without waiting on the operator, once CI is green on its final commit, current with
  `main`, and both reviewers have no FAIL and no NOT_PROVEN open but the deployed-screen tier its
  deploy proves; its deploy follows (operator 2026-10-29: "i don't
  want for you to wait on my yes for merges, etc. you are allowed to continue until you finish").
  No CODEOWNERS file. Enforced by: branch protection (green CI, current with `main`); the reviewers'
  verdicts — no machine check, ENF-12.
- Work continues until SHAPE is finished: a stop is refused while its row is IN PROGRESS, unless
  the rules require the stop (his yes to a plan for work outside SHAPE, CLAUDE.md item 3; his yes
  to a production start or stop in regular hours, or to a change of request rates, limits or
  settings, CLAUDE.md item 5; the next
  bullet's stop list: his stop words, an AUDIT ONLY or DO NOT MERGE task, a destructive data action,
  a product decision), said in a message that begins `WAITING ON OPERATOR:`. From the third
  refused stop in a row since the operator last wrote, what is being done is suspect (operator
  2026-10-30: "at that point in time i would suspect that what you are doing isn't working"): the
  agent does not try again what already failed, finds the cause down to the line of code or data
  with evidence (First gate 4), takes a different approach, the simplest that fits Python's
  guidelines and the shape, and keeps going ("go to bedrock or try some other solution based on
  our python guidelines ... instead of just churning"); two failed attempts at the same thing are
  met the same way (CLAUDE.md item 6, operator 2026-10-30). Enforced by: the Stop hook
  `tools/keep_going.py` refuses every other stop while SHAPE is open, and from the third refusal
  in a row since the operator last wrote its reason says "If you are trying again what already
  failed, it is not working" and the rest of the above (`tests/test_keep_going_v1.py`); that a
  stop marked so is one the rules require, and that the next approach differs — no machine check,
  ENF-12.
- Stop for the operator's STOP / PAUSE / HANG IT UP / DO NOT CONTINUE / NO, a task marked AUDIT ONLY
  or DO NOT MERGE, a destructive data action, and a product decision code cannot settle. Say in chat
  what a guarded action is for before running it. Enforced by: `tools/operator_yes_guard.py` asks
  Allow/Deny for the daemon or console starts and stops (in regular hours or an unknown session),
  machine restarts, and refuses the kills of production, in the forms its tests cover
  (`tests/test_operator_yes_guard_v1.py`); the rest — ENF-12.
- The production checkout `EdWebConsole` stays `main == origin/main` and moves only by a
  fast-forward (`git pull --ff-only`, or `launch.bring_to_origin_main` at a start); work happens in a
  worktree. Enforced by: `tools/process_lock_guard.py` (`tests/test_operating_process_lock_v1.py`,
  `tests/test_hook_chain_v1.py`).
- Never `git reset`, `git checkout --`, `git stash` or a force push. Enforced by:
  `tools/process_lock_guard.py` for the forms its test table refuses (`tests/test_reset_guard_v1.py`);
  a git alias — ENF-13; every other form — ENF-12.
- Never `--no-verify`, `git add -A` / `.`, delete or move anything under `data/`, a python reading
  its program from stdin (use a script file or `python -c`), or a command the guards cannot see
  into. Enforced by: `tools/operator_law_guard.py`, in the forms the tests in
  `tests/test_operator_law_guard_action_bans_v1.py`, `tests/test_protected_paths_v1.py` and
  `tests/test_guards_read_statements_v1.py` check; the forms ENF-13 lists as known open, a script
  file's contents among them — no machine check, ENF-13.
- A file keeps its line endings. Enforced by: `tools/check_eol_style_invariant.py` at commit and in
  `hardening` (`tests/test_eol_style_invariant_v1.py`).
- No credential or operator-home path is committed. Enforced by: `tools/check_credential_leak.py`
  at commit and in `hardening` (`tests/test_credential_leak_v1.py`).
- Shell steps that depend on each other are joined with `&&`. Enforced by: no machine check — ENF-12.
