# Ed Console — rules for every change

The app is a wire: Schwab → one program → the page. Every value has one producer. The shape below
is the target (operator 2026-10-29); each rule names the standard tool that enforces it, and the
step of `ACTIVE_PROGRAM.md` SHAPE that turns that check on. Until its step lands, a rule is still
the rule: a change that breaks it stops and goes to the operator.

Read before writing a change: the parts it touches of `docs/DATA_FLOW.md` (the data and its
producers), `docs/ARCHITECTURE.md` (where code lives), `ACTIVE_PROGRAM.md` (the work order) and
`docs/PRACTICES.md` (the Schwab field list). Rules for one area load with its files
(`.claude/rules/`); procedures are skills (`.claude/skills/`).

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

Each rule's check runs at commit (`.pre-commit-config.yaml`) and in the required `hardening` or
`pytest-full` job. "Step N" is the SHAPE step that turns the check on; until then the rule binds
with no machine check.

| # | Rule | Enforced by |
|---|---|---|
| 1 | **Simple.** Fewest files, functions and hops that do the job. No prose in code: history, incidents and dates go in the commit message. A defect is fixed where it is produced, by changing or deleting that code, never by a guard, wrapper, flag or special case around it. A change deletes what it replaces, in the same PR. | ruff `C90` complexity cap, `SIM`, `B` (step 1b); `tools/check_fails_before.py` in `pytest-full` (in force); `tools/check_end_to_end.py` in `hardening` until ruff `BLE`, `S110` and `TRY` replace it (step 1b, deleted in step 7) |
| 2 | **Schwab fields as sent.** Not a number: absent, -999, text, NaN or infinity, a value Schwab's own field definition excludes (a negative volume or size), and a gamma more than twice the largest any option can have at its own volatility, price and time left (operator 2026-10-23). Everything else is taken as sent; a reported 0 is 0. What Schwab sends or accepts is settled by Schwab's own documentation, `docs/schwab/schwab_market_data_api_spec.pdf` and `docs/schwab/schwab_streamer_api.pdf`, cited by section; a limit not stated there or in Schwab's own reply is our defect until shown otherwise. | `tests/test_schwab_as_sent_v1.py`, `tests/test_absence_is_not_zero_v1.py`, `tests/test_data_path_impossible_gamma_v1.py` (in force) |
| 3 | **One producer.** Each value served, stored or shown has one producer; consumers carry its result and never select, compute, repair or relabel it. One module reads each Schwab field. | `tools/check_one_reader.py` in `hardening` (in force); import-linter layers (step 1d) |
| 4 | **The page draws; it computes nothing.** Every number, total, choice, comparison and date it shows is served. It gets data only from the one push. | ESLint: `fetch`, `XMLHttpRequest` and `EventSource` only in the transport module (step 4); `Math.*`, `.sort(`, `.reduce(` and date arithmetic banned outside the drawing module (step 5) |
| 5 | **The numbers.** Every value comes from its one producer and matches what Schwab sent. Calculations keep every digit and use every contract; rounding happens only on screen. Every value is shown with its time. While it updates it is live; when it stops, for any reason, the last value stands, marked not live with its time and age, and everything computed from it is marked too; during a feed outage the header says OFFLINE. A value never received, or sent invalid, shows "-". Never a fallback, default, estimate, proxy, interpolation or synthetic value. | `tests/test_live_quote_and_order_flow_no_fallbacks_v1.py`, `tests/test_gamma_exposure_honest_absence_v1.py`, `tests/test_data_path_heatmap_absent_v1.py` (in force) |
| 6 | **One program, one path.** Schwab → program memory → pushed to the page. The databases are history, written by the Recorder, read at startup, after the close and for research, never for a live screen. | import-linter: `sqlite3` only in the Recorder and the startup loader; a test that the launcher starts one process (step 3); the data path tests of `docs/DATA_FLOW.md` §2 (in force) |
| 7 | **All tickers.** Measure and report across every watchlist ticker, never one. Every ticker is treated the same. | no machine check |
| 8 | **Clocks.** Market logic in ET; the page shows Central Time. The market's sessions are Schwab's /markets answers; no session table is typed by hand. | `tests/test_time_et_authority.py`, `tests/test_markets_sessions_v1.py` (in force) |
| 9 | **Real data.** Tests run on captured Schwab data (`tests/fixtures/`) through the real code; no stand-ins, no patches of the code under test. | `tools/check_no_new_patches.py` with `tools/patch_record.py` in `pytest-full` until ruff `TID251` (no `unittest.mock`) and a conftest that refuses `monkeypatch` replace them (step 7) |
| 10 | **Only Feed talks to Schwab.** | import-linter: `schwab`, `httpx` and `authlib` importable only from Feed (step 1d) |
| 11 | **Calculators are pure.** They take `now` and their inputs; they read no clock, database, global or network. Only an entry point (a route, a loop, a stream handler) reads the clock. | import-linter forbidden imports and ruff `TID251` banned `time.time` / `datetime.now` outside the entry points (step 2) |
| 12 | **Typed records across boundaries.** A value that crosses a module boundary is a dataclass whose states are named constants. | pyright, strict on State, Calculators and Push (step 6) |
| 13 | **Python's guidelines.** PEP 8 and PEP 257 as `ruff format` and ruff's rules read them; PEP 20 as the shape. Imports at the top. One formatter per format (price, Central Time, dollars), on the server. | `ruff format` and ruff `I` (in force); ruff `E`, `W`, `UP`, `D` (pep257, no docstring required) (steps 1b and 1c) |

## Fix what you find (operator 2026-10-29: "fix what you find anywhere, everywhere, repo wide")

- A defect found anywhere in the repository, while doing any task, is fixed: in the task that
  found it, or as the next small PR when it lies outside that task's files. It is never left as
  "pre-existing", "out of scope" or "follow-up", and never parked in a list. A standard tool's own
  fix for what its check flags (`ruff format`, `ruff check --fix`) needs no separate yes.
- Every check runs over the whole repository, never only the lines a change touches, so a finding
  anywhere fails the required job and nothing merges while it stands. A check that cannot pass
  repo-wide is not turned on until what it finds is fixed; it never gets an exception list.
  Enforced by: `ruff check .` and `ruff format --check .` over the whole repository at commit and in
  `hardening` (in force); each tool SHAPE adds (import-linter, ESLint, pyright) runs the same way
  (steps 1d to 6).

## Writing a change

- Trace each value it touches: its source, its one producer, its time, its consumers, and what
  each shows when it is missing. A producer exists: call it. None exists: write it once, in its part.
- A function that depends on the clock takes `now`.
- A new check is a test of behavior for a failure that happened, fails on the old code, and starts
  with no exceptions.
- Edit source by hand, one edit at a time; a formatter or linter fix (`ruff format`, `ruff --fix`)
  is the one exception. Enforced by: `tools/operator_law_guard.py` for sed (`tests/test_sed_edit_guard_v1.py`).
- A file keeps its line endings. Enforced by: `tools/check_eol_style_invariant.py` at commit and in
  `hardening` (`tests/test_eol_style_invariant_v1.py`).
- No credential or operator-home path is committed. Enforced by: `tools/check_credential_leak.py`
  at commit and in `hardening` (`tests/test_credential_leak_v1.py`).

## Before saying done

- The `before-done` skill's checks pass on the PR's final commit, their output shown, and both
  reviewers (`.claude/agents/correctness-reviewer.md`, `.claude/agents/requirements-reviewer.md`)
  give their verdicts. Branch protection on `main` requires `pytest-full`
  (`.github/workflows/pytest.yml`) and `hardening` (`.github/workflows/hardening.yml`) on the final
  commit, current with `main`.
- Claims: a statement about how something is now is CONFIRMED only by command output in the same
  reply; anything else is NOT VERIFIED, with when it was last checked. "Done" = a test that failed
  before passes after, the full suite passes, and the live screen shows it working (a PR with no app
  code gets no screen check). Proof is a committed test or a command anyone can re-run.
- Verdicts: PASS, every condition proven; FAIL, any violated; NOT_PROVEN, any without proof. A proof
  names its tier (unit, integration, browser, deployed app, live market).
- Say whether a runtime change is live or on disk until a restart. Deployed means production at the
  merge commit, the program restarted, and the screen checked during market hours (the `deploy` skill).
- A PR updates, in itself, every document, work item, test and caller its change affects, and
  removes what it supersedes. Each decision the operator gives in chat is written into
  `ACTIVE_PROGRAM.md` or this file in the PR that acts on it.
- Settle code, test and design questions with these rules, the banking analogy, Python's guidelines
  and outside research, and say what was decided and why. Bring the operator only what is his:
  merges, production starts and stops in regular hours, product behavior he decided, money.

## Authority

- A PR merges on the operator's yes after CI is green on its final commit; that yes also covers its
  deploy. No CODEOWNERS file. Enforced by: branch protection; `tools/operator_yes_guard.py` asks
  Allow/Deny for merges, and for production starts and stops in regular hours or an unknown session
  (`tests/test_operator_yes_guard_v1.py`).
- Stop for the operator's STOP / PAUSE / HANG IT UP / DO NOT CONTINUE / NO, a task marked AUDIT ONLY
  or DO NOT MERGE, and a destructive data action.
- The production checkout `EdWebConsole` stays `main == origin/main` and moves only by a
  fast-forward; work happens in a worktree. Enforced by: `tools/process_lock_guard.py`
  (`tests/test_operating_process_lock_v1.py`).
- Never `git reset`, `git checkout --`, `git stash`, a force push, `--no-verify`, `git add -A` / `.`,
  or a delete or move under `data/`. Enforced by: `tools/process_lock_guard.py` and
  `tools/operator_law_guard.py` (`tests/test_reset_guard_v1.py`,
  `tests/test_operator_law_guard_action_bans_v1.py`, `tests/test_protected_paths_v1.py`).
- Shell steps that depend on each other are joined with `&&`.
