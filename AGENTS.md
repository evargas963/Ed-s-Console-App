# Ed Console — rules for every change

**The goal.** A simple, dependable, accurate app: Schwab's data on Ed's screen, live, through one
correct producer, with every record kept. Every file, test, check and tool serves that goal or is
deleted. Enforced by: the test hierarchy in `.claude/rules/tests.md`.

**The order of every decision.** When two pull against each other, the higher wins:

1. **Best practice.** Every choice rests on how the industry and the standard tools do it, the
   source named.
2. **Simple code.** The fewest files, functions and steps that do the job; a change deletes what it
   replaces.
3. **A wrong number is worse than "-".** Every number is Schwab's as sent or computed once by its
   one producer; an unknown shows "-", never filled in.
4. **Fix at the source, end to end.** The cause found down to the line with evidence, fixed there,
   proved from Schwab to the screen; never a wrapper around a problem.
5. **Verify before saying done.** A test that failed before passes after, CI green, and the live
   screen shows it.
6. **Ask before deciding for the operator.** A decision that is his (what the screen shows, request
   rates, limits, money) comes to him as a short recommendation with its sources, and waits; his
   thinking aloud is not an order.

Enforced by: the builder's audit (rule 14), no machine check.

**The first rule: we wire up what Schwab gives us.** Schwab's value goes to the screen as Schwab
sent it, read once; no special rule, bound, default, interpretation or substitute of ours sits in
between, and only the math Schwab does not send is computed (the derived register). A live screen's
window in memory (the tape's prints, the books, the bars) is no bound between: it changes no value,
every message is recorded in full, and each window covers the longest one its screen reads
(`tests/test_memory_windows_cover_the_screen_v1.py`). Enforced by: rule 2's tests (a field as sent),
`tools/check_one_reader.py` in `hardening` (one reader of each Schwab field) and
`tools/check_end_to_end.py` in `locks` (no missing value filled in) (in force); a rule of ours added
between Schwab and the screen — the builder's audit (rule 14), no machine check.

The app is a wire: Schwab → one program → the page. Every value has one producer. Each rule names
the standard tool that enforces it. A rule with no machine check is still the rule: a change that
breaks it stops and goes to the operator.

Read before writing a change: the parts it touches of `docs/DATA_FLOW.md` (the data and its
producers), `docs/ARCHITECTURE.md` (where code lives), `ACTIVE_PROGRAM.md` (the work order) and
`docs/SOURCES.md` (the source documents and the Schwab field list). Rules for one area load with its
files (`.claude/rules/`); procedures are skills (`.claude/skills/`).

Every requirement in this file's sections after the Shared rules (whose Standard of care the
numbered rules hold, each naming the items it serves), in `.claude/rules/` and in
`docs/DATA_FLOW.md` names what enforces it: a test, hook or required check, or "no machine check"
and the item in `ACTIVE_PROGRAM.md` (an ENF item or STANDARD-CHECKS) that builds one. Enforced by:
no machine check — ENF-12.

## Shared rules (master copy: the operator's wording, identical to his project instructions; a change is proposed to him separately)

### First gate (EdWebConsole)

Applies to every proposal: Ed's, the prompt builder's, and Claude's. EdWebConsole is a wiring job.
Every value has exactly one producer and any number of consumers.

- Schwab fields are wired straight to the screen. Schwab is the producer. Each is listed in the
  Schwab field list.
- Derived values exist only where Schwab does not send the value. Each is computed once by its one
  canonical derived producer and listed in the canonical derived register, with its definition and
  why Schwab does not supply it. Check every request and every proposal:

1. For each value it touches: which Schwab field, or which canonical derived producer?
2. Would it compute something Schwab sends, create a second producer, or add a derived value not in
   the register?
3. Would it add code, tests, checks, tables, or tools beyond what is needed to wire Schwab's values,
   run the canonical producers, and test and enforce both? If anything fails, report what failed and
   why, and leave the failing part out. Claude proposes the smallest, simplest path that passes,
   using the repo. That proposal is checked against this gate before it goes to Ed for approval.
4. For every problem, first answer why it happens, down to the code or data that causes it, with
   evidence. Only then the fix. Never offer a choice about limits, settings or tests until the cause
   is known.
5. Every item labeled NOT VERIFIED gets verified, and every item labeled SEEN, NOT FIXED gets fixed
   at the source, before the work is reported done. An item that can't be closed comes to Ed as a
   decision, with its evidence and the reason. Enforced by (items 4 and 5): the builder's audit
   (rule 14) and `.claude/skills/flaky-test-fix/SKILL.md`.

### Standard of care

Run Ed Console the way a bank runs a system with real money on it (the banks' own standard, BCBS
239: one trusted source, accurate, complete and on time, every difference explained). These twelve
points are what that means here; the numbered rules below say how each one is kept.

1. Schwab is the record. Our numbers match Schwab's; if they ever differ, we say so and never paper
   over it.
2. One source for each number. Each Schwab field is read once, where it arrives. Each number we
   calculate is calculated once, in one place.
3. Schwab's data as Schwab sends it. We calculate only what Schwab does not send, and each such
   calculation is listed in the register.
4. A wrong number is worse than "-". A value we don't know shows "-", never a guess, a default or a
   stand-in.
5. Live and honest. Every value shows its time. A value that stops updating stays on screen marked
   with its age, and the header says OFFLINE during an outage. How live the screen is gets measured,
   not assumed.
6. Records are never changed. What Schwab sent is never overwritten or deleted; a correction is a
   new, labeled entry. Data is deleted only by the keep rule Ed sets.
7. Nothing disappears silently. Anything left out is counted and shown, and no error is hidden.
8. The page only draws. Every number, choice and comparison it shows comes from the program; the
   page calculates nothing.
9. Fix the cause, end to end. Find the cause, fix it where it starts, and prove it from Schwab to
   the screen. No patches or workarounds.
10. Everything, everywhere. Every rule applies to the whole repository and to every ticker the same
    way.
11. Change control. A change goes live only after its checks pass: a test that failed before passes
    after, every required CI check is green, and the screen is checked. Ed decides what is his: what
    the screen shows, request rates, limits, settings and money. The agent that builds a change
    checks it end to end and answers for it. Credentials are kept safe.
12. Facts come from the source. What Schwab sends, accepts or limits is settled by Schwab's own
    documents. A limit we can't find there is our bug until shown otherwise.

### EdWebConsole requirements

- Fix problems at the source, and remove what the fix replaces.
- Clean up along the way in the area changed, listing each item. Behavior or data changes need
  approval.
- Zero is a value; missing is unknown. Never treat one as the other.
- Tests use only real captured data, with expected results from verified definitions. No fake data.
- Every ticker is treated the same.
- Treat existing code, tests, and documents as claims to challenge.
- Display live values promptly and record everything completely. Measure performance; don't assume
  it.
- Verify end to end, including the actual screen.
- Run authorized inspection and testing without asking.
- Protect credentials and unrelated work.
- Label findings as confirmed evidence, induced test conditions, hypotheses, or NOT_PROVEN.

## The shape

One program in five parts, as a bank runs a ledger, a teller window and a journal:

| Part            | Owns                                                                                                      | Never                                              |
| --------------- | --------------------------------------------------------------------------------------------------------- | -------------------------------------------------- |
| **Feed**        | the only code that talks to Schwab (the stream and REST), taking each field as sent                       | computes a value, writes a database                |
| **State**       | one in-memory store: the newest value of everything, with its time (the ledger)                           | keeps a second copy                                |
| **Calculators** | pure functions: each derived value computed once, when its inputs change, from inputs and `now` passed in | reads a clock, a database, a global or the network |
| **Push**        | one WebSocket from the program to the page: a snapshot, then the changes (the teller window)              | serves a value State does not hold                 |
| **Recorder**    | the only writer of the databases (the journal)                                                            | is read by a live screen                           |

Hops: Schwab → program → page. Nothing else travels.

Why, from outside practice: one user and one account call for one program (Fowler, "MonolithFirst");
"simple is better than complex" and "flat is better than nested" (PEP 20); build only what is needed
(KISS, YAGNI); systems that work grow from simple ones that work (Gall's law); and rules are held by
standard linters, not by hand-written checks.

## Locks

The repository is meant to get simpler: less code, fewer tests, fewer hand-built check tools, fewer
open work rows. `.github/workflows/locks.yml` runs `tools/check_end_to_end.py`,
`tools/check_integrity.py` and `tools/check_locks.py`, which counts on the base and on the head
under the base's rules: lines and bytes of everything that is not data (product code, tests, check
tools), open work items, patching lines in tests, format suppressions, and every finding of
`locks.ruff.toml` with each `noqa` ignored. A count at 0 is an absolute ban. Above 0, a finding may
not rise; size and work items may rise and are reported, never judged (`check_locks.FREE`); that a
change deletes what it replaces — no machine check, ENF-12. No number is kept by hand
(`tests/test_check_locks_v1.py`). A banned name (`sqlite3`, the clock, `websockets`, `http.client`,
`urllib.request`) counts per product file, so no module that does not hold one may start. The same
job runs import-linter on `locks.imports.toml`, the base's: no import statement outside the modules
it names takes `schwab`, `authlib` or `httpx`, and none anywhere takes `aiohttp` or `requests`, with
no count (`tests/test_data_path_only_feed_v1.py`); a file Python can load that it may not read is a
count at 0, so absolute (`tools/check_locks.py`), and a type stub (`.pyi`), which no loader of
Python's takes, is not one. The builtin `__import__("schwab")` and a module loaded from a zip on
`sys.path` are seen by no tool: the builder's audit (rule 14), no machine check. GitHub runs that
workflow from the base (`pull_request_target`), and it runs no code of the head, so a change cannot
edit its judge. `locks` is a required check on `main`: a change it refuses cannot merge, and nothing
approves past it. No step waits on the operator's click, and none is built: enforcement is checks
that fail outright. `gh` is allowed by a list and `gh api` only reads, in the forms
`tests/test_operator_law_guard_action_bans_v1.py` checks (`tools/operator_law_guard.py`).

## Rules and what enforces them

Each rule names what enforces it and where it runs. "(in force)" means it runs today: at commit
(`.pre-commit-config.yaml`: the credential scan, `ruff check .`, `ruff format --check .`), at push
(the same file: compileall, `check_one_reader`, `check_end_to_end`, `check_integrity` and
`check_locks` against `origin/main`, so nothing `hardening` or `locks` refuses leaves the machine)
or in the required `hardening` (`.github/workflows/hardening.yml`), `pytest-full` or
`pytest-windows` (`.github/workflows/pytest.yml`) job. "(locks)" means it runs in
`.github/workflows/locks.yml`, a required job too.

1. **Simple** (serves 9). Fewest files, functions and hops that do the job. No prose in code:
   history, incidents and dates go in the commit message. No patches: a defect is fixed where it is
   produced, by changing or deleting that code, never by a guard, wrapper, flag, special case or
   check around it; if that takes a restructure, the restructure is the fix. Every fix is end to
   end: Schwab to the screen. Nothing new (process, cache, helper, file, check) without a job its
   existing owner cannot do, shown in the PR; an existing piece that cannot show one is removed. A
   change deletes what it replaces, in the same PR; a register, audit, report or check lives only
   while it has a job, and once answered, it is deleted. Enforced by: `tools/check_end_to_end.py` in
   `locks`, over the whole repository (every patch shape of product code counted on the base and the
   head) and on each line a change adds (in force); that a defect is fixed at its source — the
   builder's own audit (rule 14), no machine check; two constructs `check_end_to_end` allows: the
   running total `d[k] = d.get(k, 0) + x` (the sum of nothing is 0, a real value), and the program's
   port setting, exactly `os.environ.get("<name>", "<digits>")` for `ED_CONSOLE_PORT`, the one port
   the program listens on, with its written default, which a test points at a free port of its own
   (`check_end_to_end.PORT_SETTINGS`); ruff `S110` (a catch-all `except` passed in silence) and
   `BLE` (a catch-all `except` that neither records its traceback nor re-raises) over the whole
   repository (in force); ruff `C90` complexity cap and `TRY` (but `TRY003`, which flags a built-in
   exception's message as Python's own library writes it), as one-way counts (locks);
   `check_end_to_end` is deleted once a standard tool refuses every shape its docstring lists
   (swallowing excepts, missing values replaced or repaired, the page's patch shapes) — the shapes
   left — STANDARD-CHECKS
2. **Schwab fields as sent** (serves 1, 3, 12). Not a number: absent, -999, text, NaN or infinity, a
   value Schwab's own field definition excludes (a negative volume or size). Everything else is
   taken as sent, a gamma included whatever its size; a reported 0 is 0. No other bounds, no
   substitution. What Schwab sends or accepts is settled by Schwab's own documentation,
   `docs/schwab/schwab_market_data_api_spec.pdf` (with
   `docs/schwab/schwab_market_data_parameters_chains_quotes.txt` for the expanded /chains and
   /quotes parameters) and `docs/schwab/schwab_streamer_api.pdf`, cited by section; a limit not
   stated there or in Schwab's own reply is our defect until shown otherwise. Enforced by:
   `tests/test_schwab_as_sent_v1.py`, `tests/test_absence_is_not_zero_v1.py`,
   `tests/test_gamma_as_sent_v1.py` (in force)
3. **One producer** (serves 2). Each value served, stored or shown has one producer; consumers carry
   its result and never select, compute, repair or relabel it. A second authority for the same value
   is banned whatever it is called: helper, parser, resolver or cache. One module reads each Schwab
   field. Each value is received once: what Schwab pushes (Schwab Streamer API §1.5, delivery
   Change, Whole or All Sequence) is taken from the push and never asked for again, and REST is
   asked only for what the stream does not send; where two endpoints send the same field, the pushed
   one is its producer. Open interest is the exception: the OCC's once-a-day figure, its producer
   the chain for every contract, which holds the day's figure all day, while the stream's
   OPEN_INTEREST arrives near 06:30 ET and for some contracts never updates. Enforced by:
   `tests/test_data_path_rest_one_connection_v1.py`: a contract Schwab streams is not asked for on
   /quotes and takes the stream's Greeks as one set, and an option record ends with its connection
   (in force); a streamed contract's open interest, volume and quote fields, which `/chains` still
   sends — STREAM-ONE; every other REST request for a field the stream sends — no machine check,
   ENF-12; `tools/check_one_reader.py` in `hardening` refuses a pull request that adds a second
   reader (in force); the fields already read by more than one module
   (`python -m tools.check_one_reader --list`) — ENF-23
4. **The page draws; it computes nothing** (serves 8). Every number, total, choice, comparison and
   date it shows is served. It gets data only from the one push. Enforced by: ESLint's
   `no-restricted-globals`: `fetch`, `XMLHttpRequest` and `EventSource` only in the transport
   module, `static/js/ed-core.js`, and `Date` and `Intl` in every page script, every time it shows
   served (`time_et.ct_label`, `ct_ticks`) (`tools/census/eslint.config.mjs`, a count in the census;
   a failing job with LINTERS); and `Math`, `.sort(` and `.reduce(` outside the drawing module
   (`static/js/ed-draw.js`) and the chart (`static/js/ed-tv-chart.js`) (the same config, a count in
   the census)
5. **The numbers** (serves 4, 5, 7). Every value comes from its one producer and matches what Schwab
   sent. Calculations keep every digit and use every contract; rounding happens only on screen.
   Every value is shown with its time. While it updates it is live; when it stops, for any reason,
   the last value stands, marked not live with its time and age, and everything computed from it is
   marked too; during a feed outage the header says OFFLINE. While the program's push to the page
   has stopped, the time stands with no age (the page computes none, and the last age served is not
   the age now) and the header says OFFLINE. A value never received, or sent invalid, shows "-".
   Never a fallback, default, estimate, proxy, interpolation or synthetic value. Enforced by:
   `tests/test_live_quote_and_order_flow_no_fallbacks_v1.py`,
   `tests/test_gamma_exposure_honest_absence_v1.py`, `tests/test_data_path_heatmap_absent_v1.py` (in
   force)
6. **One program, one path** (serves 2, 6). Schwab → program memory → pushed to the page. The
   databases are history, written by the Recorder, read at startup, after the close and for
   research, never for a live screen. Enforced by: `sqlite3`, a banned name counted per product file
   in `locks.ruff.toml`, so no module that does not hold it may start (locks), and refused in every
   Calculator by import-linter (`locks.imports.toml`); a test that the launcher starts one process;
   the data path tests of `docs/DATA_FLOW.md` §2 (in force)
7. **All tickers** (serves 10). Measure and report across every watchlist ticker, never one. Every
   ticker is treated the same, but in what Schwab is asked for first: the ticker a page shows comes
   first on the stream and on the request line, and the others may lag. Enforced by: the order:
   `tests/test_option_contract_rule_v1.py`, `tests/test_data_path_rules_v1.py` (in force); the rest
   — no machine check, ENF-05
8. **Clocks** (serves 5). Market logic in ET; the page shows Central Time. The market's sessions are
   Schwab's /markets answers, and before a day's first window the pre-market begins with the first
   stock trade Schwab streams that was made that day; no session table is typed by hand. Enforced
   by: `tests/test_time_et_authority.py`, `tests/test_markets_sessions_v1.py`, which refuses a clock
   time typed in product code (in force)
9. **Real data** (serves 11). Tests run on captured Schwab data (`tests/fixtures/`) through the real
   code; no stand-ins, no patches of the code under test. Enforced by: `tools/check_locks.py`:
   patching lines in tests may not rise (locks); stand-ins left in the tests — STAND-INS
10. **Only Feed talks to Schwab** (serves 2). Enforced by: import-linter on `locks.imports.toml` for
    Schwab's clients (locks); `locks.ruff.toml` banned names, per product file, for `http.client`,
    `urllib.request` and `websockets` (locks); a call made through Feed's own client
    (`feed/schwab_client.py`) from outside Feed — import-linter's "Only the daemon reaches Feed" in
    `locks.imports.toml` (`tests/test_data_path_only_feed_v1.py`, locks)
11. **Calculators are pure** (serves 2, 5). They take `now` and their inputs; they read no clock,
    database, global or network. Only an entry point (a route, a loop, a stream handler) reads the
    clock. One clock, repo wide: the computer's clock is read in `time_et.py` alone (`time_et.now`,
    `time_et.elapsed`), and the page reads none. Its one timer is the price push's silence watch
    (`static/js/ed-core.js` `PRICE_SILENCE_MS`, 3 s against the program's 1 s beat): it reads no
    time of day and computes no shown value, and marks the push down when nothing arrives, which a
    stalled program cannot say itself. Enforced by: the one clock: ruff `TID251` in
    `pyproject.toml`, every file but `time_et.py` (in force); that only an entry point takes the
    time — `time_et.now` and `time_et.elapsed` counted per product file in `locks.ruff.toml`
    (locks): today's entry points hold them, and a module at 0 (every calculator) may never start;
    that a Calculator imports no State, Push, Feed, database or network — import-linter's "The
    Calculators read no State, Push, Feed, database or network" in `locks.imports.toml`, on each
    Calculator's own import statements (`tests/test_data_path_only_feed_v1.py`, locks); a chain
    through another root module, and a global — no machine check, ENF-09
12. **Typed records across boundaries** (serves 11). A value that crosses a module boundary is a
    dataclass whose states are named constants. Enforced by: pyright 1.1.414
    (`requirements-dev.txt`, the census's own pin), strict over the files `pyproject.toml`
    `[tool.pyright]` lists, in `hardening` (in force on every product module); schwab-py and authlib
    ship no types, so Feed's calls into them read the stubs in `typings/`, which state only what
    Feed uses: mypy's stubtest checks each signature against the installed libraries in `hardening`,
    and every name Feed takes from them is imported for real by Feed's tests (in force)
13. **Python's guidelines** (serves 11; the order's best practice). PEP 8 and PEP 257 as
    `ruff format` and ruff's rules read them; PEP 20 as the shape. Imports at the top, with no
    exception: the daemon runs under `python` in its window, so an error while it loads shows there,
    and `capture_main` imports it at the top. Ruff `PLC0415` holds the rule (locks). One formatter
    per format (price, Central Time, dollars), on the server (no machine check — ENF-11). Enforced
    by: `ruff format` and ruff `UP`, `W`, `S110`, `BLE`, `E` (`E501`: lines at most 100 columns;
    `E741`: no `l`, `O` or `I` as a name), `B`, `I` (import order) and the `SIM` rules with a safe
    fix (`SIM114`, `SIM117`, `SIM118`, `SIM208`, `SIM300`, `SIM905`, `SIM910`, `SIM911`) or with no
    fix and nothing to fix (`SIM107`, `SIM113`, `SIM116`) (in force; `UP042`, `E711`, `E712`, `E731`
    and the `B` and `SIM` rules whose only fix is unsafe deselected, in `pyproject.toml`, and
    `SIM115`, whose findings are mostly files held open past the function, which a `with` would
    close); ruff `TRY` (but `TRY003`, rule 1), `C90` and `PLC0415` as one-way counts (locks)
14. **The builder answers for the change** (serves 9, 11). The agent that builds a change audits it
    end to end, Schwab to the screen, the right amount, not too much and not too little: it moves a
    value onto the one wire and deletes what it replaces; product code that grows beside the old
    path, a new helper, label, gate or branch beside it, or a deleted function back under a new
    name, is a patch and is not merged; a construct a check refused is fixed, never reshaped to
    pass; coverage of live code is not dropped. Tests are written with the wiring, on real data. No
    reviewer verdict or review record is required. Enforced by: the test suite in `pytest-full` and
    `pytest-windows` (in force); the audit itself — no machine check
15. **Tests are not taken from** (serves 11). An assertion of a surviving test is not lost, a test
    is not skipped and deferred-work markers are not added, with no opt-out of any kind. A deleted
    test goes with the code it tested, and so does an assertion with the function it calls or the
    value it reads: what is deleted is no longer tested, in the same change. Enforced by:
    `tools/check_integrity.py` in `locks`, a net loss per test by its name, an assertion that names
    a function or a record's key the change deleted from the product not counted
    (`tests/test_check_integrity_v1.py`, locks); the rest — the builder's audit, no machine check
16. **An agent never changes repository settings** (serves 11): branch protection, rulesets and
    required checks are the operator's, applied in GitHub. Enforced by:
    `tools/operator_law_guard.py`: `gh` by a list, `gh api` only reads
    (`tests/test_operator_law_guard_action_bans_v1.py`)

## Fix what you find

- A defect found anywhere in the repository, while doing any task, is fixed: in the task that found
  it, or as the next small PR when it lies outside that task's files. "Pre-existing", "out of scope"
  and "follow-up" are not dispositions. A row in `ACTIVE_PROGRAM.md` holds a found defect only as
  the next work in its order, never as a place to leave it. A standard tool's own fix for what its
  check flags (`ruff format`, `ruff check --fix`) needs no separate yes; never an unsafe fix: no
  `--unsafe-fixes`, no `unsafe-fixes` or `extend-safe-fixes` in `pyproject.toml`, and a rule whose
  only fix is unsafe stays deselected. Enforced by: `tools/check_end_to_end.py` takes only ruff's
  safe fixes as the tools' own, and none at all when ruff's own resolved settings for the committed
  `pyproject.toml` (extended files included) turn unsafe fixes on, force a fix safe, require an
  import of every file, or target another Python than the base's, so an unsafe rewrite of a product
  file is a product change that needs its failing test; it refuses a change whose committed
  settings, in any `pyproject.toml`, `ruff.toml` or `.ruff.toml` the repository tracks, turn unsafe
  fixes on or force one safe, whatever file the change touches, and the agent's hook refuses a ruff
  run that asks for one (`--unsafe-fixes`, or an inline `--config` setting of `unsafe-fixes` or
  `extend-safe-fixes`), so neither the repository's settings nor a ruff command line takes one, in
  any file (`tests/test_check_end_to_end_v1.py`, `tests/test_operator_law_guard_action_bans_v1.py`);
  the rest of this bullet (a found defect fixed, the same rewrite typed by hand outside product
  code, settings ruff reads from a file the repository does not track) — no machine check, ENF-12.
- **Everything is repo wide.** Every check, test, hook, lock, rule and fix covers every file of the
  repository, old code and new alike, with no exception list, no skipped path or line, and no "the
  change only" mode; a finding in old code is counted and fixed, never let stand because it is old.
  At 0 findings a rule fails the required job outright, and above 0 it is a count (Locks). A
  conflict with this rule is reported to the operator at once. Enforced by: `ruff check .` and
  `ruff format --check .` over the whole repository at commit and in `hardening` (in force);
  `tools/check_locks.py`, every tracked file (locks); `tools/check_end_to_end.py`, every file's
  patch shapes counted on the base and the head, and in every file whose code a change touches,
  tests and tools included, a shape refused on an added line or on an unchanged line that did not
  hold it before (`tests/test_check_end_to_end_v1.py`, locks); `tools/check_one_reader.py`, the
  whole repository's second readers printed on every run and a new one refused (in force); gitleaks,
  every tracked file in `hardening`, no path or line skipped (`.gitleaks.toml`, in force); the
  production-checkout rail, every file of that checkout (`tools/process_lock_guard.py`,
  `tests/test_hook_chain_v1.py`, in force). `check_integrity` judges a change itself (a test's
  assertions kept), not what files hold, and reads every file of any kind a change touches.
  Import-linter, ESLint and pyright run over the whole repository the same way. What follows from
  it:
  - Tests stay independent: a test runs real captured Schwab data through the real code and checks
    it against values worked out outside that code, so the tests read Schwab's captured answers
    themselves; every other file has one reader per field (`check_one_reader`,
    `tests/test_check_one_reader_v1.py`). The captured data each test uses is representative of what
    it tests and free of flaws such as two snapshots 30 minutes apart read as consecutive values
    (TEST-CLEANUP, no machine check, ENF-12).
  - Size is not a rule: lines, bytes and work items are reported and never judged
    (`check_locks.FREE`); simple code is held by the checks of correctness (one producer, no patch
    shapes, no dead code, the complexity cap, the builder's audit) and by `/simplify` on every
    change (no machine check, ENF-12).
  - A test is known by what it asserts, not by its name: a test renamed with an assertion dropped is
    a lost assertion. A machine cannot tell that from a test deleted beside a new one, so it is the
    builder's audit (rule 14, no machine check). No test duplicates another
    (`tools/check_integrity.py`, `tests/test_check_integrity_v1.py`); a change updates every test it
    affects in the same PR.
  - The daemon runs under `python` in its own window, where an error while it loads shows and its
    requests and answers can be watched. Closing that window ends the daemon without its clean stop
    (the rows held for the next write are lost); `python launch.py stop` is the stop.
  - The vendored chart library's one patch shape is left as it is: this repository cannot fix it at
    its source.
  - Every language the repository holds gets its standard checker, run over the whole repository
    (Python: ruff; JavaScript, HTML, CSS, JSON, YAML, Markdown: ESLint, html-validate, Stylelint and
    Prettier; workflows: actionlint; TOML: taplo; Markdown: markdownlint, in its Prettier style,
    Prettier alone setting a document's layout): LINTERS, in progress.

## Before writing code

- Every change, in any file of the repository (product code, the page, scripts, tools, tests), lists
  how it can fail in real use and carries a test that forces each one: anything that can block,
  stall, crash, restart halfway, arrive late, arrive twice or not arrive, and a screen that is slow.
  The failure is traced end to end, every link of it repaired at its source, never only the one that
  showed first. Enforced by: the builder's audit (rule 14), no machine check.
- The operator's five rules: this is a simple wiring job; we use Schwab's data as Schwab sends it;
  this is a financial app, and a question is answered by what a bank would do; everything is repo
  wide; every repair is end to end. They apply to all code in the repository and to every answer,
  proposal and change. Enforced by: `tools/wiring_rules.py`, which puts them before the agent on
  every message in Claude Code (`tests/test_wiring_rules_v1.py`); that they were applied — the
  builder's audit (rule 14), no machine check.
- Source documents first. A question of fact (what Schwab or an exchange sends, lists, limits or
  times) is answered from its source document, read that turn and cited from `docs/SOURCES.md`,
  before any measurement of ours; no change rests on a belief. A measurement on the repository's own
  data says what that data can show (how often it was recorded, for which contracts); data that
  cannot show the thing is not evidence of it. A source that answers a new question is added to the
  register in the change that rests on it. Enforced by: `tests/test_source_register_v1.py` (every
  listed file exists, every source has its dates, none is past the date it is read again by); that a
  change rests on a source — the builder's audit (rule 14), no machine check.
- Trace each value it touches: its source, its one producer, its validity rule and time, its live
  and stored consumers, and what each shows when it is missing. A producer exists: call it. None
  exists: write it once, in its part. Enforced by: no machine check — ENF-08.
- Name each touched responsibility's one lifecycle owner (what starts, refreshes, retries and
  expires it) and what fails when that owner fails, in `docs/DATA_FLOW.md` and in the code. Enforced
  by: no machine check — ENF-08.
- A function that depends on the clock takes `now`; only an entry point (a route, a loop, a stream
  handler) reads the clock, and the clock is read only in `time_et.py` (rule 11). Enforced by: ruff
  `TID251` (rule 11); that only an entry point takes the time — ENF-09.
- A product change carries end-to-end tests of what it wires, on real captured data, written with
  it. Enforced by: the builder's audit (rule 14), no machine check.
- Edit source by hand, one edit at a time, never through a script; the exceptions are ENF-14's (a
  standard tool's own fix, `ruff format` and ruff's safe fixes). Enforced by:
  `tools/operator_law_guard.py` for sed (`tests/test_sed_edit_guard_v1.py`); the other in-place
  editors — ENF-14.

## Before saying done

- The `before-done` skill's checks pass on the PR's final commit, their output shown; the full suite
  is the required CI jobs green there, not a local repeat. Branch protection on `main` requires
  `pytest-full`, `pytest-windows`, `hardening` and `locks` on the final commit, current with `main`;
  `pytest-windows` runs the browser tests and the full pytest suite on Windows as production runs.
  On each system the two suites run side by side, each on a runner of its own, and the required job
  reads both results.
- Claims. Every statement about how something is now (a process, a file, a branch, a pull request, a
  test result, data, the screen) is CONFIRMED only by command output shown in the same reply.
  Anything else is NOT VERIFIED, with when it was last checked. "Done" = a test that failed before
  passes after, the full suite passes, and the live screen shows it working (a PR with no app code
  gets no screen check). "Across the board" = every watchlist ticker. Proof is a committed test or a
  command anyone can re-run. Enforced by: no machine check — ENF-12.
- No hand-maintained count, floor or list that a check compares against; the check computes it.
  Enforced by: no machine check — ENF-12.
- Work another agent wrote is read in full by the agent offering the PR. Enforced by: no machine
  check — ENF-12.
- Say whether a runtime change is live or on disk until a restart. Deployed means production at the
  merge commit, restarted, and the screen checked during market hours (the `deploy` skill).
  Production runs main at all times: enforced by the Stop hook `tools/keep_going.py`, which refuses
  a stop while the production checkout is not at its `origin/main` or nothing listens on the
  console's port, unless the message begins `WAITING ON OPERATOR:` (`tests/test_keep_going_v1.py`);
  the screen check during market hours — no machine check, ENF-12.
- Never kill a commit hook mid-run. Enforced by: no machine check — ENF-12.
- Settle code, test and design questions with these rules, the banking analogy, Python's guidelines
  and outside research, and say what was decided and why. Bring the operator what is his: changes to
  request rates, limits and settings; behavior or data changes; money. Enforced by: no machine check
  — ENF-12.

## Close the change

- A PR updates, in itself, every instruction, design, work item, check, test and caller its change
  affects, removes what it supersedes, and lists each affected path without proof as NOT_PROVEN. A
  finished work item leaves `ACTIVE_PROGRAM.md` in the PR that finishes it. Enforced by:
  `tests/test_governing_docs_v1.py` (every path named exists); the rest — ENF-12.
- Each decision the operator gives in chat is written into `ACTIVE_PROGRAM.md` or this file in the
  PR that acts on it, as the rule it sets, not as a quote or a date. Enforced by: no machine check —
  ENF-12.

## Proof

- A proof is CONFIRMED evidence on the final commit and names its tier (unit, integration, browser,
  deployed app, live market); one tier never stands in for another, and a check proves only the
  paths it covers. NOT VERIFIED labels a statement without proof.

## Authority

- At each milestone (a commit, a failed check, a finding that changes the plan), report to the
  operator what changed, what was deleted, each proof and its tier, and what is NOT_PROVEN, then
  continue. Enforced by: no machine check — ENF-12.
- A PR merges, without waiting on the operator, once CI is green on its final commit and current
  with `main`; its deploy follows. No CODEOWNERS file. Enforced by: branch protection (green CI,
  current with `main`).
- A pull request is opened for a group, never for one small fix: what it finishes whole (a census
  category, an order of the operator's) with every fix found along the way, named in its
  description's `## Group` section; his override is his word in chat, quoted there. Enforced by:
  `tools/operator_law_guard.py` refuses the agent's `gh pr create` without it
  (`tests/test_operator_law_guard_action_bans_v1.py`); that the group is whole — the builder's audit
  (rule 14), no machine check.
- The one program stands in its five parts, and the hand-built checks a standard tool covers are
  deleted (the line-ending check for git's `.gitattributes`, the credential scanner for gitleaks);
  each other hand-built check goes once a standard tool refuses what it refuses (STANDARD-CHECKS). A
  wait on CI is not a stop: every pull request has auto-merge and Auto-fix on, so it merges by
  itself or the app wakes the session on a failure, and the next work starts meanwhile; the agent
  never polls CI itself. Work stops only for what the operator must decide, and a report, a finished
  order or a wait is not a stop. Two failed attempts at the same thing send the agent to the cause,
  down to the line of code or data with evidence (First gate 4), and a different approach (CLAUDE.md
  item 6). Enforced by: the Stop hook `tools/keep_going.py` refuses every stop whose final message
  does not begin `WAITING ON OPERATOR:` with what he must decide (`tests/test_keep_going_v1.py`);
  that the wait is real — the builder's audit (rule 14), no machine check; the rest — ENF-12.
- Once the operator tells the agent to do something, it does it; it does not choose whether, when or
  what instead. It pushes back only when the thing is not allowed or not possible, and says so with
  the reason at once. Enforced by: `tools/wiring_rules.py` records every message he sends as a
  numbered message, read by the agent as an order with what it breaks or conflicts with, or as not
  one, put to him to correct, and the Stop hook `tools/keep_going.py` refuses to end a turn while
  any message lacks its reading or any order a line `ORDER n DONE: <evidence>` or
  `ORDER n PUSHBACK: <reason>` (`tests/test_keep_going_v1.py`, `tests/test_wiring_rules_v1.py`);
  that the evidence is true and a pushback's reason real — the builder's audit (rule 14), no machine
  check.
- Stop for the operator's STOP / PAUSE / HANG IT UP / DO NOT CONTINUE / NO, a task marked AUDIT ONLY
  or DO NOT MERGE, a destructive data action, and a product decision code cannot settle. Say in chat
  what a guarded action is for before running it. A daemon or console start or clean stop needs no
  yes at any hour. Enforced by: `tools/operator_yes_guard.py` asks Allow/Deny for machine restarts
  and refuses the kills of production, in the forms its tests cover
  (`tests/test_operator_yes_guard_v1.py`); the rest — ENF-12.
- The production checkout `EdWebConsole` stays `main == origin/main` and moves only by a
  fast-forward (`git pull --ff-only`, or `launch.bring_to_origin_main` at a start); work happens in
  a worktree. Enforced by: `tools/process_lock_guard.py` (`tests/test_operating_process_lock_v1.py`,
  `tests/test_hook_chain_v1.py`).
- Never `git reset`, `git checkout --`, `git stash` or a force push. Enforced by:
  `tools/process_lock_guard.py` for the forms its test table refuses
  (`tests/test_reset_guard_v1.py`); a git alias — ENF-13; every other form — ENF-12.
- Never `--no-verify`, `git add -A` / `.`, delete or move anything under `data/`, a python reading
  its program from stdin (use a script file or `python -c`), or a command the guards cannot see
  into. Enforced by: `tools/operator_law_guard.py`, in the forms the tests in
  `tests/test_operator_law_guard_action_bans_v1.py`, `tests/test_protected_paths_v1.py` and
  `tests/test_guards_read_statements_v1.py` check; the forms ENF-13 lists as known open, a script
  file's contents among them — no machine check, ENF-13.
- Every text file is stored with LF line endings, a batch file is checked out with CRLF, and
  captured Schwab data (`tests/fixtures/`) is kept byte for byte. Enforced by: git itself, as it
  saves each file (`.gitattributes`).
- No credential or operator-home path is committed. Enforced by: gitleaks 8.30.1 with
  `.gitleaks.toml` (its own rules, ours for a bearer token, a key assigned, an AWS key id, a private
  key's header and the three home-path spellings), at commit on what the commit adds
  (`.pre-commit-config.yaml`; the program beside `pre-commit` on PATH) and in `hardening` on every
  tracked file and the PR's commits.
- Shell steps that depend on each other are joined with `&&`. Enforced by: no machine check —
  ENF-12.
