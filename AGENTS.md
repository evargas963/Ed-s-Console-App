# Ed Console — rules for every change

Design: `docs/DATA_FLOW.md`. Work order: `ACTIVE_PROGRAM.md`. Code map: `docs/ARCHITECTURE.md`.
Read the parts a change touches before writing it. The rules in force are `main`'s: a session or
reviewer in a worktree whose `AGENTS.md` differs from `origin/main`'s reads `main`'s first.

Every requirement in a section marked (enforced), in this file and in `docs/DATA_FLOW.md`, ends with
"Enforced by:" naming the test, hook or required check that blocks a violation, or, where none exists
yet, "no machine check" and the ENF work item in `ACTIVE_PROGRAM.md` that builds one. Enforced by:
`tests/test_governing_docs_v1.py` fails CI when a requirement lacks the line, names a file that does
not exist, or names an ENF item that is not in `ACTIVE_PROGRAM.md`.

## Shared rules (master copy)

### First gate (EdWebConsole)
Applies to every proposal: Ed's, the prompt builder's, and Claude's.
EdWebConsole is a wiring job. Every value has exactly one producer and any number of consumers.
- Schwab fields are wired straight to the screen. Schwab is the producer. Each is listed in the Schwab field list.
- Derived values exist only where Schwab does not send the value. Each is computed once by its one canonical derived producer and listed in the canonical derived register, with its definition and why Schwab does not supply it.
Default: Schwab sends what we need. A derived value, or any use of our own clock, is allowed only with cited proof that Schwab does not send it.
Check every request and every proposal:
1. For each value it touches: which Schwab field, or which canonical derived producer?
2. Would it compute something Schwab sends, create a second producer, or add a derived value not in the register?
3. Would it add code, tests, checks, tables, or tools beyond what is needed to wire Schwab's values, run the canonical producers, and test and enforce both, or protect production, credentials and records?
If anything fails, report what failed and why, and leave the failing part out. Claude proposes the smallest, simplest path that passes, using the repo. That proposal is checked against this gate before it goes to Ed for approval.

### Standard of care
Hold EdWebConsole to how a financial institution handles systems with real money on the line. These are judgments to apply to every proposal, not things to build:
- System of record: Schwab is the statement. Our data matches it, and any difference is reported, never plugged.
- Records stand: what Schwab sent is never overwritten or deleted; with Ed's approval it may only be moved to a verified archive. Data we computed may be removed only with Ed's approval of that removal and a verified copy first. A correction is a new, labeled entry.
- Unknowns surface: an unknown shows as unknown, never estimated or filled in.
- Change control: no change reaches production without Ed's approval of that change; the approval names what it covers (merge, restart, data), and the hook's prompt at each step is answered by it.
- Four eyes: whoever builds a change is not the only one who verifies it. Two read-only reviewers check every change: an architecture reviewer, against the First gate, and a correctness reviewer, that the change does what it claims, with evidence. While the repo is being brought under control, this applies to every change. Once Ed decides it is stable, it narrows to changes touching stored data, money values, or production.

### EdWebConsole requirements
- Fix problems at the source, and remove what the fix replaces.
- Clean up along the way in the area changed, listing each item. Behavior or data changes need approval.
- Zero is a value; missing is unknown. Never treat one as the other.
- Tests use only real captured data; an induced condition (feed down, a clock instant) is named in the test; expected results come from verified definitions, cited. No fake data.
- Every ticker is treated the same.
- Treat existing code, tests, and documents as claims to challenge.
- Display live values promptly and record everything completely. Measure performance; don't assume it.
- Verify end to end, including the actual screen (live values during market hours; otherwise NOT_PROVEN).
- Run read-only inspection and local, reversible testing without asking.
- Protect credentials and unrelated work.
- Label findings CONFIRMED / INDUCED / HYPOTHESIS / NOT_PROVEN; verdicts PASS / FAIL / NOT_PROVEN.

## Enforcement map (enforced)

- **First gate.** Schwab's fields: `docs/schwab_fields.csv`; derived values: `docs/DATA_FLOW.md` §3.6. A PR names each value it
  adds or changes under "Wiring:". Consumers carry the producer's result; they never select, compute, repair or relabel
  it; a second producer is banned whatever it is called (helper, parser, resolver, cache). Enforced by:
  `tools/check_end_to_end.py` requires "Wiring:" on a product change (`tests/test_check_end_to_end_v1.py`);
  `tests/test_page_one_faucet_v1.py`, `tests/test_one_levels_producer_v1.py` for the values they drive; the second
  producers found 2026-10-02 — ENF-02; the register's check — ENF-17.
- **System of record.** Enforced by: no machine check — ENF-18.
- **Records stand.** Never delete or move anything under `data/` or `backups/`. Put to Ed, for a `data/*.db` file: an
  Edit/Write of it; cp / copy / Copy-Item with it as the last argument; mv, rm, Set-Content, tee or another guard writer
  naming it; a `>` / `>>` to it; python or sqlite3 naming it without `mode=ro` / `-readonly`. Other writes are not seen.
  Enforced by: `tools/operator_law_guard.py` (`tests/test_protected_paths_v1.py`); `tools/operator_yes_guard.py`
  (`tests/test_operator_yes_guard_v1.py`); the writes not seen — ENF-20; a table drop — ENF-16.
- **Unknowns surface.** In an open session a value whose feed is down, or whose input is missing or invalid, is absent
  with its reason; while Closed the close values stand until the next session. No "past" label, fallback, default,
  estimate, proxy, carry-forward, interpolation or synthetic value. Enforced by:
  `tests/test_live_quote_and_order_flow_no_fallbacks_v1.py`, `tests/test_gamma_exposure_honest_absence_v1.py`, `docs/DATA_FLOW.md` §2 D5.
- **Change control.** A merge, a push to main, a start, stop or restart of the daemon or console and a change to a test
  on main are put to Ed as an Allow/Deny prompt (database writes: Records stand); an operator setting (a count, a rate,
  a switch) changes only with Ed's yes to it. Enforced by: `tools/operator_yes_guard.py`
  (`tests/test_operator_yes_guard_v1.py`); the operator setting — ENF-12.
- **Four eyes.** Reviewers: `.claude/agents/architecture-reviewer.md`, `.claude/agents/correctness-reviewer.md`. Their
  read-only rests on their tool list (no Edit or Write), their instructions and the repo's hooks; Bash can write.
  Enforced by: `tools/check_end_to_end.py` requires "Architecture review:" and "Correctness review:" on a product
  change; that each is a reviewer's report on the final commit — ENF-19.
- **Fix at the source.** No guard, wrapper, flag, special case or check around a defect; a needed restructure
  is the fix; end to end, Schwab to the screen. A PR that only removes product lines names under "End-to-end test:"
  the existing tests that cover it (`tests/<file>.py::<test>`), never an invented line. Enforced by: `tools/check_end_to_end.py`
  in `hardening` refuses a product change with no real line added to an end-to-end path test (removal only: no existing
  test named), a patch shape, or no "Schwab → screen:", "Deleted:", "End-to-end test:"; the rest — ENF-01.
- **Clean up along the way.** Nothing new without a job its existing owner cannot do, shown in the PR. An existing
  piece with no job, and a register, audit, report or check whose question is answered, is deleted.
  Enforced by: "Deleted:" (`tools/check_end_to_end.py`); ruff F401 at commit and in `hardening`; the rest — ENF-04.
- **Zero is a value (rule 2: Schwab fields as sent).** Not a number: absent, -999, text, NaN or infinity, and a value
  Schwab's own field definition excludes (a negative volume or size); all else as sent, a reported 0 is 0, no other
  bounds, no substitution. Enforced by: `tests/test_schwab_as_sent_v1.py`, `tests/test_absence_is_not_zero_v1.py`.
- **Real captured data.** Captured Schwab data is in `tests/fixtures/`; no test patches the code it
  tests. Enforced by: `tools/check_no_new_patches.py` (`tests/test_check_no_new_patches_v1.py`); the rest — ENF-07.
- **Every ticker.** Measured and reported across every ticker, never one. Enforced by: no machine check — ENF-05.
- **Challenge claims.** Enforced by: no machine check — ENF-12.
- **Live and complete.** Enforced by: `tests/test_data_path_rules_v1.py` (D2, D4); measurement — ENF-12.
- **End to end.** Enforced by: the required `pytest-full` job (`.github/workflows/pytest.yml`); the screen — ENF-12.
- **Read-only and local without asking.** Enforced by: `tools/operator_yes_guard.py` passes ordinary work
  (`tests/test_operator_yes_guard_v1.py`).
- **Protect credentials and unrelated work.** No credential or operator-home path is committed; never `git reset`,
  `git checkout --`, `git stash`, force push, `--no-verify`, `git add -A` / `.`. Enforced by: `tools/check_credential_leak.py`
  at commit and in `hardening` (`tests/test_credential_leak_v1.py`); `tools/process_lock_guard.py`
  (`tests/test_reset_guard_v1.py`); `tools/operator_law_guard.py` (`tests/test_operator_law_guard_action_bans_v1.py`).
- **Labels.** They apply to every part of a reply, summaries, "found, not fixed" and next steps included. CONFIRMED:
  shown by command output in the same reply (an earlier check is not current evidence). INDUCED: observed under a
  condition made on purpose, named. HYPOTHESIS: inferred, not observed. NOT_PROVEN: no proof yet, with when last
  checked. Verdicts on a change's final commit: PASS, every condition proven; FAIL, any violated; NOT_PROVEN, any
  without proof. Each proof names its tier (unit, integration, browser, deployed app, live market); one tier never
  stands in for another, and a check proves only the paths it covers. Done: a test that failed before passes after,
  the full suite passes, and the live screen shows it working. Enforced by: no machine check — ENF-12.

## Operational rules (enforced)

- **4. The UI computes nothing.** Page code formats and draws. Every number, total, choice,
  comparison and date the page shows is served. Enforced by: no machine check — ENF-03.
- **6. One path.** Schwab → daemon memory → pushed to the screen. The database is history: one
  writer; read at startup, after the close and for research; never for a live screen.
  Enforced by: `docs/DATA_FLOW.md` §2 D1–D6, each with its own test.
- **9. Clocks.** Market logic in ET; the UI shows Central Time.
  Enforced by: `tests/test_time_et_authority.py`, `tests/test_session_calendar_authority_v1.py`
  (ET); the Central Time display — ENF-06.

## Before writing code (enforced)

- Trace each value the change touches: its source, its one producer, its validity rule and time, its live and stored
  consumers, and what each shows when it is missing. A producer exists: call it. None: write it once, on the server.
  Enforced by: no machine check — ENF-08.
- For each responsibility the change touches, name its one lifecycle owner (what starts, refreshes, retries and expires
  it) and what fails when it fails, in `docs/DATA_FLOW.md` and in the code. Enforced by: no machine check — ENF-08.
- Page code: no arithmetic, sum, min/max, sort by value or date math on served data.
  Enforced by: no machine check — ENF-03.
- A new check is a test of behavior, for a failure that happened; it fails on the old code; it starts with
  no exceptions. Enforced by: `tools/check_fails_before.py` in the required `pytest-full` job refuses a PR that
  changes product code unless one of its changed tests fails on the base, except a PR that adds no product or test line and
  whose test files only lose whole definitions nothing left names, no autouse fixture (`tests/test_check_fails_before_v1.py`); the rest — ENF-08.
- Time is an input: a function that depends on the clock takes `now`; only an entry point (a
  route, a loop, a stream handler) reads the clock. Enforced by: no machine check — ENF-09.
- A value that crosses a module boundary is a typed record (dataclass), not a dict of string keys;
  its states are named constants, not free strings. Enforced by: no machine check — ENF-10.
- Imports at the top of the module. One formatter per format (price, Central Time, dollars), on
  the server. No prose in code: history, incidents and dates go in the commit message.
  Enforced by: no machine check — ENF-11.
- A test exercises behavior through the real code. It never reads source text or pins a private
  helper; a test whose subject is deleted is deleted with it. Enforced by: no machine check — ENF-08.
- A test, fixture or helper a pull request adds or changes never patches the code it tests (monkeypatch, mock.patch,
  a fixture that does, or a patching autouse fixture in its file); the existing ones are cleaned as their files are
  touched. Enforced by: `tools/check_no_new_patches.py` in `hardening` (`tests/test_check_no_new_patches_v1.py`); the existing ones — TEST-PATCHES.

## Before saying done (enforced)

- While working: the tests of the files touched. Before the PR is offered: `npm run test:all` and
  `python -m ruff check . --select F401,F821,E9` on its final commit. Enforced by: branch protection
  on `main` requires `pytest-full` (`.github/workflows/pytest.yml`: Playwright, then pytest) and
  `hardening` (`.github/workflows/hardening.yml`) on the final commit, current with `main`.
- Never kill a commit hook mid-run; a long one runs in the background. Enforced by: no machine check — ENF-12.
- Proof is reproducible: a committed test or a command anyone can re-run. A scratch script is
  not proof. No hand-maintained counts, floors or lists that a check compares against; the check
  computes them. Enforced by: no machine check — ENF-12.
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
- Found broken in the area changed: fixed in this change and listed; elsewhere: reported with its
  location; a behavior or data change needs Ed's approval. Enforced by: no machine check — ENF-12.

## Authority (enforced)

- Checkpoints: about every 15 minutes of work the agent reports to the operator what changed, what was deleted,
  each proof and its tier, and which requirements are NOT_PROVEN, then continues. Enforced by: no machine check — ENF-12.
- A PR merges when its required proof on its final commit is complete and CI is green; green CI alone is not proof.
  Enforced by: GitHub branch protection requires the `pytest-full` job of `.github/workflows/pytest.yml` and the
  `hardening` job of `.github/workflows/hardening.yml`, on a branch current with `main`.
- A change to AGENTS.md, `docs/DATA_FLOW.md`, CI, a hook or a check is merged only by the
  operator. Enforced by: no machine check — ENF-13.
- Stop for: the operator's STOP / PAUSE / HANG IT UP / DO NOT CONTINUE / NO; a task marked AUDIT
  ONLY or DO NOT MERGE; a destructive data action; a product decision code cannot settle.
  Enforced by: no machine check — ENF-12.
- Production checkout `EdWebConsole`: `main == origin/main`, changed only by `git pull --ff-only`.
  Work in a worktree; main itself moves only by a PR merged on GitHub. Enforced by: the agent hook
  `tools/process_lock_guard.py` refuses an edit, a shell write or a git verb that moves it off
  main (`tests/test_operating_process_lock_v1.py`), and a git command from any checkout that
  writes `refs/heads/main` (`tests/test_hook_chain_v1.py`).
- Never edit source through a script: edits are made one at a time, as written; a block too long
  for one edit is removed in consecutive edits. Enforced by: the agent hook
  `tools/sed_edit_guard.py` refuses a sed that writes a file (`tests/test_sed_edit_guard_v1.py`);
  the other in-place editors — ENF-14.
- A file keeps its line endings (most are LF; some are CRLF). Enforced by: the commit hook
  `tools/check_eol_style_invariant.py` (`tests/test_eol_style_invariant_v1.py`).
- Shell steps that depend on each other are joined with `&&`, so a failure stops the chain.
  Enforced by: no machine check — ENF-12.

## Running it

Console: `start_ed_console.bat` (`uvicorn server:app`, port 8000). Capture daemon: `start_capture_daemon.bat`.
Python 3.13, the project `.venv`. Offline: `ED_CI_OFFLINE=1`, placeholder `SCHWAB_API_KEY` / `SCHWAB_APP_SECRET`.
Live: `schwab_token.json` (`python reauth_schwab.py`). Probe `127.0.0.1`, never `localhost`. A restart deploys
code and needs Ed's approval of the change it deploys; the agent confirms both came back.
