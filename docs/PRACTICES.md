# EdWebConsole: Python practices for this repo

Drawn from python.org (PEP 20, PEP 8, PEP 484, the standard library docs, the CPython Developer's Guide), Google's Python Style Guide, and Cosmic Python (Architecture Patterns with Python). Each rule names its source, why it matters for EdWebConsole, where the repo stands on main (as read 10/07-10/08), and the lock that enforces it. "Repo today" items not read directly are NOT VERIFIED.

## A. Design principles

1. **One obvious way: one source per value.**
   - Source: PEP 20 ("There should be one-- and preferably only one --obvious way to do it").
   - Why: this is the one-faucet rule. A value with two sources shows two answers.
   - Repo today: Greeks reach a contract from up to 4 sources; one contract can show two bids on two panels (CONFIRMED, faucet audit 10/07).
   - Lock: the wiring register, plus a test that fails when a Schwab field is read outside its one registered reader.

2. **Errors never pass silently.**
   - Source: PEP 20; Google: never catch `Exception` unless you re-raise it or you are at the outermost isolation point.
   - Why: a swallowed error becomes a wrong number that looks right.
   - Repo today: `except Exception ... # noqa: BLE001` in capture.py (CONFIRMED); the total count is NOT VERIFIED.
   - Lock: ruff `BLE001`, `S110`, `E722`, with no new `noqa`.

3. **In the face of ambiguity, refuse to guess.**
   - Source: PEP 20.
   - Why: unknown stays unknown. No default fills a missing value.
   - Repo today: the rule exists (AGENTS rule 2). Whether every path follows it is NOT VERIFIED.
   - Lock: type checker (rule 10) and the test's question 1.

4. **Special cases aren't special enough to break the rules.**
   - Source: PEP 20.
   - Why: every ticker is treated the same.
   - Repo today: hand-typed lists `BROKER_INDEX_BARE_ROOTS` and `MARKET_CONTEXT` (CONFIRMED).
   - Lock: review checklist item 4; ruff `PLR2004` for hand-typed numbers.

5. **Simple, flat, small.**
   - Source: PEP 20 ("Simple is better than complex", "Flat is better than nested"); Google ("Prefer small and focused functions", reconsider past about 40 lines).
   - Repo today: function sizes NOT VERIFIED.
   - Lock: ruff `C901`, `PLR0912`, `PLR0915`, `SIM`.

6. **If it's hard to explain, it's a bad idea.**
   - Source: PEP 20.
   - Why: every wire should be explainable in one sentence (Schwab field → reader → screen).
   - Lock: the register entry is that sentence.

## B. Architecture

7. **The outside world stays at the edges.**
   - Source: Cosmic Python ("Functional Core, Imperative Shell"; "disentangle the logic... from the low-level details of I/O").
   - Why: Schwab, the clock, the database and the screen are edges. The levels math is the core and does no I/O.
   - Repo today: `schwab_client.py` is the Schwab edge. Whether the math modules do any I/O is NOT VERIFIED.
   - Lock: a test that the math modules import no client, database or clock.

8. **One adapter per external system.**
   - Source: Cosmic Python ("abstracting out a wrapper around your API"; "integration tests to test your adapter, and unit tests for your business logic").
   - Why: every Schwab call goes through one module, which is also the only place that knows Schwab's field names.
   - Lock: ruff `TID251` bans importing the Schwab client outside the adapter and the daemon.

9. **Dependencies are passed in, not reached for.**
   - Source: Cosmic Python (dependency injection); AGENTS ("Time is an input").
   - Why: the clock, the client and the database path are parameters, so tests run real code with no patches.
   - Repo today: tests are moving from `pin_clock` patches to passing time in.
   - Lock: ruff `TID251` bans `monkeypatch` and `mock.patch`; ruff `DTZ`.

10. **Typed records, checked by machine.**
    - Source: PEP 484; Google ("You are strongly encouraged to enable Python type analysis").
    - Why: `float | None` makes "zero is a value, missing is unknown" a compile-time fact, not a promise.
    - Repo today: AGENTS asks for dataclasses, but there is **no type checker** (CONFIRMED: no mypy or pyright config).
    - Lock: pyright (or mypy) in commit hook and CI, strict on new and changed code.

11. **No mutable global state.**
    - Source: Google ("Avoid mutable global state").
    - Why: module globals (for example `server._bars`) leak between tests and between tickers.
    - Repo today: count NOT VERIFIED.
    - Lock: review; ruff `PLW0603` (the `global` statement).

12. **One owner per lifecycle.**
    - Source: Cosmic Python (unit of work / service layer); AGENTS.
    - Why: the daemon owns subscriptions; the page asks for nothing.
    - Repo today: done for stream subscriptions (#486, #488); the console as a middleman goes in step 6.
    - Lock: the register names each owner.

## C. Data correctness

13. **Exact numbers for money.**
    - Source: python.org `decimal` docs.
    - Why: binary floats can't hold 1.885 exactly. "Every digit" needs Schwab's numbers read exactly (`json` with `parse_float=decimal.Decimal`, or text), with rounding only on screen.
    - Repo today: NOT VERIFIED (default JSON parsing likely gives floats).
    - Lock: the adapter's parser, plus a test that a captured answer round-trips digit for digit.

14. **Aware datetimes only.**
    - Source: python.org `datetime` and `zoneinfo` docs.
    - Why: market logic in ET, the screen in Central Time, no naive times.
    - Lock: ruff `DTZ`.

15. **Explicit None checks.**
    - Source: Google ("Always use `if foo is None:`"; compare against `0` explicitly).
    - Why: `if not oi:` treats a real 0 and a missing value the same.
    - Lock: type checker; ruff `PLC1901` and related rules; review.

16. **Parse once, at the boundary.**
    - Source: Cosmic Python (adapter); Google (types).
    - Why: Schwab JSON becomes a typed record once, by Schwab's field definitions. After that nobody re-reads raw keys.
    - Lock: register (one reader); `TID251`.

## D. Testing

17. **Fakes from real data, not mocks.**
    - Source: Cosmic Python ("writing your own fakes"; mocks are "brittle"; "Mock Hell"); Ed's three questions.
    - Why: a fake Schwab built from captured answers, run through the real code.
    - Repo today: `tests/schwab_rest_standin.py` and `tests/schwab_stream_standin.py` exist (CONFIRMED); patched tests remain.
    - Lock: `TID251` bans patching tools; no-new-patches check (exists).

18. **Contract tests against the real Schwab.**
    - Source: Cosmic Python ("lightweight, mostly read-only checks against the real API... to confirm that the fake matches reality").
    - Why: proves our stand-ins still match Schwab, so the earlier subscription bug (each part replacing the last) can't recur unnoticed.
    - Lock: a scheduled read-only contract test.

19. **Deterministic tests.**
    - Source: Google; Cosmic Python.
    - Why: no fixed sleeps, no shared state; the clock passed in.
    - Repo today: two timing-flaky tests found 10/07 (CONFIRMED).
    - Lock: ban `time.sleep` in tests (`TID251`).

20. **Every fix comes with a test that failed before.**
    - Source: CPython Developer's Guide.
    - Repo today: enforced by `check_fails_before.py` (CONFIRMED).

## E. Concurrency, logs, operations

21. **Never block the event loop; a timeout on every network call.**
    - Source: python.org `asyncio` docs ("Running blocking code").
    - Why: the daemon's stream loop must not stall behind a REST call.
    - Repo today: the request timeout is in #486; blocking calls NOT VERIFIED.
    - Lock: ruff `ASYNC` rules.

22. **Logs sized for what they must keep.**
    - Source: python.org `logging` docs (handlers, rotation).
    - Why: one 50 MB backup lost 05:53-10:07 of 10/07 to a flood (CONFIRMED).
    - Lock: rotation by time, kept 30-45 days to match the data window; one line per event, never per loop pass.

23. **Pinned dependencies, audited.**
    - Source: Python Packaging guide (pip-audit).
    - Repo today: pinned (#481, CONFIRMED); no audit.
    - Lock: `pip-audit` in CI.

## F. Enforcement: how the rules become locks

24. **Ratchet, don't big-bang.**
    - Turn rules on in report mode, count violations per file, then require that **new and changed code passes** and the total can never go up. Each PR lowers it.

25. **Run the checks in three places:**
    - a Claude Code hook after every edit (Claude sees and fixes at once),
    - the commit hook,
    - required CI.

26. **No silent escape hatches.**
    - Source: Google ("Suppress warnings only when appropriate", with an explanation).
    - Lock: refuse a new `# noqa` or `# type: ignore` unless Ed approves it; ruff `RUF100` removes unused ones.

27. **Comments say why, never history.**
    - Source: Google; AGENTS.
    - Repo today: history in code, for example "gamma audit 2026-08-26" and "VALIDATED 2026-07-26" (CONFIRMED).
    - Lock: review; `ERA001` for commented-out code.

28. **One formatter.**
    - Source: PEP 8.
    - Repo today: none (CONFIRMED).
    - Lock: `ruff format` in the commit hook.

29. **One wiring register.**
    - Not in any generic guide: EdWebConsole's own First gate.
    - Content: one line per value, with its Schwab endpoint and field, Schwab's definition, its one reader, and its consumers; or, for a derived value, its one producer and definition.
    - Lock: the test in rule 1.

## G. Institutional and quant standards (added 10/08)

These come from how banks and trading firms govern systems with money on the line, not from Python guides. Sources: the Federal Reserve and OCC's SR 11-7 (Supervisory Guidance on Model Risk Management, 2011) and the Basel Committee's BCBS 239 (Principles for effective risk data aggregation and risk reporting, 2013). Both are cited from knowledge, not re-read this session.

30. **Model inventory and validation (SR 11-7).**
    - Rule: every calculation that turns data into a decision number (levels, Greeks we compute, ATR) is a "model". It is listed in an inventory, with its definition, inputs, assumptions and limits.
    - Validation: it is checked by someone other than its builder, against an independent reference, and monitored once it is live.
    - For us: the canonical derived register is the model inventory. The independent reference for Black-Scholes values is a standard library such as QuantLib. Repo today: no register (NOT VERIFIED that one exists).

31. **Data accuracy, completeness, timeliness and lineage (BCBS 239).**
    - Rule: every number can be traced back to its source record, and its freshness is known.
    - For us: raw Schwab answers are kept as received, each value's lineage (Schwab field → reader → producer → screen) is in the register, and every value carries Schwab's own time.

32. **Reconcile against the system of record.**
    - Rule: compare our values with Schwab's on a schedule, and report each break, never plug it.
    - For us: our computed gamma against Schwab's gamma, our screen against Schwab's raw answer, our open interest against thinkorswim's (as checked by hand on 10/07).

33. **Point-in-time records.**
    - Rule: every record keeps two times, when it happened (Schwab's time) and when we received it.
    - For us: a backtest uses only what was known at that moment, with no look-ahead. Repo today: ts_recv and schwab_ts exist on stream records (CONFIRMED); REST records NOT VERIFIED.

34. **Deterministic replay.**
    - Rule: feeding recorded raw answers through the same code reproduces the same screen and the same levels.
    - For us: this is the strongest test there is, and it answers all three test questions at once.

35. **Measured latency against a target.**
    - Rule: for each update, measure Schwab's time to our screen against the goal (under 1 second), and report it.

36. **One-step rollback.**
    - Rule: every deploy can be undone to the previous commit in one step, and that step is written down before the deploy.

37. **Stated numerical tolerance.**
    - Rule: every comparison of computed numbers says its tolerance and why. Values Schwab sends are compared exactly.

## H. The Schwab field dictionary (the First gate's "Schwab field list", made complete)

- `docs/schwab_fields.csv` lists 4,387 field names and types that our own tool observed. It holds **no definitions**.
- Schwab's definitions exist in two places:
  - **The Streamer guide** (`docs/schwab/schwab_streamer_api.pdf`) has a definition table for every stream field, including whether it updates in regular and AM/PM hours and when it resets. Examples for LEVELONE_OPTIONS: "Volatility is reset to 0 at 3:30am ET"; "Total Volume ... set to zero at 3:30am ET"; open interest, bid, ask and volatility "Update AM/PM Hours: No"; field 14 "Digits: Number of decimal places".
  - **The developer portal's REST schemas** (OptionContract, QuoteOption and others). In our saved copy every description is collapsed to `[...]`, so these must be expanded and pasted from the portal, or requested from Schwab.
- One dictionary line per field: endpoint or service; Schwab's name; Schwab's definition; update and reset timing; observed precision; observed quirks with evidence; our one reader.
- Observed quirks so far (10/07):
  - /chains rounds Greeks to 3 decimals; /quotes and the stream carry about 8.
  - /chains volatility is shared by the call and put at a strike (exact for SPY; not always for QQQ and AMD).
  - After hours, open interest answers 0.
  - Call deltas above 1 occur on both /chains and /quotes.
  - Field names in real /chains answers (bid, ask, mark) differ from Schwab's documented names (bidPrice, askPrice, markPrice).
