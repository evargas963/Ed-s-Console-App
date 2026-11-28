# ACTIVE_PROGRAM.md — the current work, in order

The one record of open work: what is in flight, next, queued, waiting on the operator's decision or
still being designed. Each item serves the goal in `AGENTS.md`: Schwab's data on screen, live, one
producer per value, every record kept. The design every item is built to is `docs/DATA_FLOW.md`;
where code lives is `docs/ARCHITECTURE.md`. An item leaves this file in the pull request that
finishes it (git keeps its history). An ID other files cite stays here while its work is open; an
item that absorbed another lists the old ID as "also".

Each item is one line: `- ID (STATE): what is left, and its next action.`

## In progress

- SIZE (IN PROGRESS): the repository cut to what serves the app, as we go (operator 2026-11-19:
  "this is a ridiculous number of lines"). Measured 2026-11-19: tests 46,676 lines in 249 files,
  program 19,725 (Python), page 14,414, check tools 7,077, test data 71 MB in 114 files. Tests
  first: mutation testing (`.github/workflows/mutation.yml`, mutmut, `calc/` first, then all the
  Python) and the per-test coverage CI records (`--cov-context=test`) show each test's worth; a test
  that catches no mistake another test misses and covers no line of its own is deleted, and a weak
  one is strengthened. Then each capture in `tests/fixtures/` kept only while a test reads it, and
  the check tools under STANDARD-CHECKS. `tools/check_locks.py` reports every part's size on every
  pull request.
- ONE-DB (IN PROGRESS): one database, `data/ed.db` (`db_authority.canonical_db_path`), every column
  tied to its writer, reader and Schwab field. Left: `stream_feed_status`'s `socket_open` and
  `schwab_last_frame_ts` (the same in every service's row of a round); `level_crosses`' `ts_et`,
  `timeframe` (always "1m") and `zone_before`/`zone_after` (None since the zones left); the chain
  rows stored as plain text and the codec's plain-text branch; Schwab's `/expirationchain` answer,
  the one market-data answer not recorded (`feed.schwab_client.option_expiries`). Every step that
  deletes data is planned to the operator and run by him.
- CENSUS (IN PROGRESS; also LINTERS): `tools/census/census.py` (`.github/workflows/census.yml`)
  counts every issue in the repository, each above its row's design target: an item at the target a
  rule sets (the one clock in `time_et.py`, the Recorder's and the loader's sqlite3, the builder's
  audit) is reported with that rule (`tools/census/decisions.json`), so every issue left is work;
  each count is driven to 0, then becomes a failing `locks` check. Every language's standard checker
  (ESLint, Stylelint, html-validate, Prettier, markdownlint, taplo, yamllint, actionlint, Blinter,
  `json.tool`) runs over every tracked file; Markdown's layout is Prettier's alone. It counts the
  statements no test runs (coverage.py, from pytest.yml's run of the same commit) and bandit's
  security rules (ruff `S`); what only the working machine holds (its database, branches, stashes,
  worktrees and the files git does not hold) is counted there (`--machine`), and a clone reports it
  as not counted, never as 0 (operator 2026-11-27: the census reports every issue repo wide, every
  file and every language, the scope never narrowed). It also counts every dependency not pinned to
  one version or pinned nowhere (a library's own), each with a known vulnerability (pip-audit, npm
  audit), each key read in Schwab's spelling that the field list does not hold, and each kind of
  failure in the program's newest log, and, from the record of the newest regular session, each
  watchlist ticker's minutes with no quote received, Schwab's quote time to its receipt and the
  stream's longest silences (on the machine), and the lines of the page's scripts no browser test
  runs (V8 coverage, `tests/e2e/fixtures/test.js`). Left: rows still to build: the page's lag behind
  the program (SPEED's numbers, each session), each streamed option contract's minutes with no
  record, and the contrast of text drawn on a canvas and of panels holding data (every page's empty
  state is held by `tests/e2e/console-contrast.spec.js`, AGENTS.md rule 4); the census's own npm
  checkers updated past their 11 known vulnerabilities; each finding fixed; each checker made a
  failing check at 0; one shared git reader for the check tools (`_git` in
  `tools/check_end_to_end.py`, `tools/check_integrity.py`, `tools/check_one_reader.py`,
  `tools/hook_chain.py`). Untracked files nothing uses go to an archive beside the checkout; their
  deletion is the operator's.
- REVIEW (IN PROGRESS): the repo-wide review's findings, each checked against the code and the
  sources and fixed with a test that fails on the old code. Next: the support and resistance line,
  once a longer price history shows which levels hold, and the other screens that print key levels.
- OPEN-5MIN (IN PROGRESS): a sense of direction for the first five minutes of trading. The
  EXPERIMENTAL open-gap record is on the Desk (`open_gap.py`, `docs/derived_register.md`); on
  Schwab's 5-minute bars no input yet separates the opens from chance. Next: test the kept
  pre-market tape and books once about two months of opens are held; extend the record past Schwab's
  reach with the kept 1-minute bars. An auction-imbalance source (Nasdaq NOII, NYSE) is by
  subscription only and is the operator's call.
- STORE-ENOUGH (IN PROGRESS): keep enough to make informed decisions. The keep table is built in
  `stream_spine.py`. Left: the order books (about 77% of a day's bytes): measure the open
  (04:00-10:00 ET) and close (15:30-16:00) windows and their lossless compression, then the operator
  decides their long-term keep; until then they are kept whole.

## Next

- STREAM-ONE (NEXT): what Schwab streams comes only from the stream (AGENTS.md rule 3). Left: a
  streamed contract's open interest, volume and quote fields, which `/chains` still sends, read from
  the stream alone (open interest stays the chain's, rule 3's exception).
- SPEED (NEXT; also LIVE-MEASURE): one regular session's numbers across the watchlist, from the
  daemon log and py-spy: the chain rotation time, the program's memory and CPU, the levels' age, and
  how far the push runs behind Schwab, a streamed contract's chain ladder cell among them (a median
  4.4 s behind on 2026-11-18, before #1194 showed each streamed value as it arrives). Then the $SPX
  levels computation. The requests a minute and every answer that is not 200 are the census's (M,
  each machine run's newest ended session).

## Queued

- REPRICE-ROWS (QUEUED): the once-a-second reprice (`server._publish_levels`, queued by
  `server._reprice_from_tick`, `server.REPRICE_EVERY_SEC`) publishes a whole new set of long-lived
  objects each time: about 36,000 for QQQ, 25,822 of them per-strike rows (`calc/terrain_engine.py`
  `StrikeValue`, `StrikeRow`), and its thread used 51 of 90 seconds of one core in the replay of
  2026-11-20 10:35 ET. It is what set off the full collections the session now runs without
  (`docs/DATA_FLOW.md` §3.1), and what held the lock when `/api/health` took over 1 s (1 of 60 live
  requests on 2026-11-18). Next: the confirming measurement on the live program at the next
  regular-hours open (the lock's holder by py-spy, each thread's CPU time read from outside, the
  day's `garbage collection after the close` line); then the reprice publishes only what changed, in
  records the collector does not track.
- HTTPX2 (QUEUED, on upgrade): authlib 1.9.1 warns that its httpx fallback is deprecated ("please
  use httpx2"); schwab-py 1.5.1 is built on httpx. Left as is (operator 2026-11-19): authlib, httpx
  and schwab-py stay pinned in `requirements.txt`, and are upgraded together, with the sign-in
  refresh tested before a deploy, when schwab-py moves to httpx2 or authlib drops the fallback.
- STANDARD-CHECKS (QUEUED; also ENF-01, REPO-WIDE-SHAPES): each hand-built check goes once a
  standard tool refuses what it refuses: `tools/check_end_to_end.py` first, then
  `tools/check_integrity.py`, `tools/check_locks.py`, `tools/check_one_reader.py` and the command
  guards. Before `check_end_to_end` can go, every old patch shape it counts is fixed at its source,
  file by file, to 0 (`python tools/check_end_to_end.py --base origin/main` prints them), and the
  fallbacks below with them. Left to the builder's audit meanwhile: a design-level patch, a clamp
  (`max(0, x)`), a bare `if x is None: return`. Sorted: the page's shapes are navigation defaults,
  CSS class names, a title attribute, environment flags and an argument default, none a value (the
  two that were values are fixed); a test's `contextlib.suppress(psutil.NoSuchProcess)` while it
  stops processes that may have ended already is the form ruff's own SIM105 asks for, so that shape
  is settled by the standard tool when `check_end_to_end` goes, not rewritten. Ruff's flake8-async
  rules (`ASYNC`) are in force: no blocking call in an async function.
- NUMBERS (QUEUED; also ENF-22, DASH): code and tests to AGENTS.md rule 5: a value that stops stands
  marked not live with its time and age, everything computed from it marked too, OFFLINE in the
  header during an outage, no rounding or dropped contract in a calculation, each with a behavior
  test on captured data. Left from DASH: values still served with a reason instead of "-": levels
  with no price (`push.levels.NO_PRICE_LEVELS_REASON`), the outage words, and `calc.terrain_read`'s
  sentences for a missing input. Decided: the header is one, the same on every page, each value from
  its one producer, in two rows: the instrument and the system, then the market context's three
  indexes and the news line, which gives way to the alerts (`docs/DATA_FLOW.md` §6, decision 11,
  `tests/e2e/console-header.spec.js`).
- STAND-INS (QUEUED; also ENF-07): every test runs captured Schwab data through the real code. Left:
  each stand-in a test file names under STAND-INS replaced by a capture carrying its condition, at
  its own instant, fixed in `tests/fixtures/`; the induced conditions the operator allowed (a 0
  price, a -999 delta) replaced once Schwab sends one.
- ENF-23 (QUEUED; also ENF-02, ONE-02, ONE-21, ONE-25): one producer per value (rule 3), held by
  `tools/check_one_reader.py` in `hardening`. Left: plain-word fields (gamma, delta, volatility,
  multiplier, symbol), reads through a helper or a table of names, page code, and the derived half
  (a served value `docs/derived_register.md` does not name). Known second producers, each deleted to
  one with a test: the strike at the price (`calc.terrain_engine.nearest_strike`,
  `calc.confluence_composite.under_strike`); the front expiry's five definitions (max pain, same-day
  levels, heatmap front, confluence default); equity prints kept again in the order-flow tape
  (`app/options/order_flow/state.py`); and the second computations the 2026-10-02 review listed,
  each re-checked against the code before it is fixed.
- ENF-11 (QUEUED; also P1-9): one formatter per format, on the server, and a machine check of it
  (`tests/test_served_numbers_v1.py` holds the number formatters; ruff `PLC0415` is already at 0).
  The census counts each date, time or number formatted outside `time_et` and `numeric_contract`,
  each moved to its formatter; left: the count becomes a failing check.
- SIMPLIFY (ACTIVE; also ENF-04, TEST-CLEANUP, TEST-REVIEW, P2-6, P2-7): every line earns its place,
  one pull request per slice, each run through /simplify. Left: history notes in `static/index.html`
  (a comment-only HTML change counts as a behavior change, so it needs the operator's approval of
  the diff or a browser test); test read-back connections never closed
  (`git grep -c "with sqlite3.connect(" -- tests/`); served fields no page reads; one computation
  where there are two (the expiry key, the tick-rule walk); the page's own sorting and selection;
  tests and check tools that guard nothing live, duplicate another or test a deleted path; each
  run's slowest tests read for length and purpose; what has no job cut from the large files
  (`server.py`, including the gamma surface's served record, `calc/liquidity_value_engine.py`,
  `app/options/order_flow/streaming.py`, `calc/order_flow.py`, `calc/math_exposure_core.py`,
  `ed-core.js`, `ed-gamma.js`), with no folder moves.
- LEG-TERMS (QUEUED): every served chain leg carries the terms Contract Specifications shows
  (`settlementType`, `multiplier`, `nonStandard`, `pennyPilot`, `exerciseType`, `expirationType`,
  `lastTradingDay`), and no page reads them there: that panel draws the row's `series`, which
  `push.chain._series` builds by reading them off the leg. Next: `_series` reads the contract's
  record and the leg drops them; `calc.terrain_engine.chain_ladder` hands on only the served rows,
  so the ladder then carries the records.
- ENF-13 (QUEUED; also GUARD-SHRINK): the command guards (`tools/operator_yes_guard.py`,
  `tools/operator_law_guard.py`, `tools/process_lock_guard.py`, `tools/shell_parse.py`) cut to the
  least code that keeps every verdict their tests check, the hand lexer in `tools/shell_parse.py`
  replaced where a standard parser reads the same (bashlex for bash, PowerShell's own
  `System.Management.Automation.Language.Parser`). This is the one list of their known open forms
  (no test, not refused):
  - `gh` run by another program: `Start-Process`, `winpty`, `xargs -a f gh`, a git alias, a program
    built by python or node, cmd's `start`, `[Diagnostics.Process]::Start`,
    `wmic process call create`, PowerShell splatting; an alias written into gh's `config.yml`;
    `curl` or python with a token.
  - Forms the reader does not see: `$r=& $gh ...` with no spaces, `$r += & $gh ...`,
    `[string]$r = & $gh ...`; python in a quoted combined `-I` option; a query held in a variable or
    read from a substitution; a command inside bash arithmetic, a PowerShell expandable here-string,
    `xargs ... sh -c` or `hatch run`; `bash -oe pipefail` reading a pipe; a bare command in a
    PowerShell `@{ }` table; a script file's contents; aliases and functions defined earlier; `*>`
    redirects.
  - The reset guard (`tools/operating_process_lock.py`): a git alias naming `stash`, `reset --hard`,
    `clean -f`, `checkout --` or `push --force`. The law guard: `icacls` on the `data` folder
    itself. A production kill written inside a double-quoted word, PowerShell's `$(( ))`, or `.Kill`
    spelled another way.
- ENF-14 (QUEUED): no source edit through a script. sed is refused; left: `perl -i`,
  `awk -i inplace`, python or node scripts that write files, PowerShell `Set-Content`/`Out-File`/
  `Add-Content`, `tee`, `ed`/`ex`/`vim` batch edits, `truncate`, `dd`, sed's own `w` command, and
  `git update-ref --stdin`. The standard tools' own safe fixes stay allowed.
- ENF-05 (QUEUED): every measurement and report covers every watchlist ticker; a check of the report
  scripts.
- ENF-06 (QUEUED): a browser test that every shown time is Central Time.
- ENF-08 (QUEUED): the "Before writing code" practices (trace each value, name its lifecycle owner,
  list failure modes): a PR template whose sections a check requires.
- ENF-09 (QUEUED): no function below an entry point takes the time; a check for a chain through
  another root module and a global.
- ENF-10 (QUEUED): typed records across module boundaries (pyright strict already covers every
  product module, Feed through `typings/`): a check that a value crossing a boundary is a dataclass.
- ENF-12 (QUEUED): the practices no machine can see (claims cite output, proof reproducible, another
  agent's work read in full, deploy means restarted and checked, `&&` chains, every requirement
  naming its enforcement, a screen's state said in its producer's words and not the page's), each
  held by the builder's audit until a check exists.
- ENF-21 (QUEUED): a statement about what Schwab sends, accepts or limits cites `docs/schwab/` by
  section or Schwab's own reply; no machine check yet.
- LIVE-SESSION (QUEUED): checks only a live session can show, across the watchlist: the heatmap
  stays live; chains captured on schedule from Schwab's /markets windows; Schwab's zeros taken as
  sent; the price shows Schwab's last trade and its time in every session and stands marked not live
  when its feed stops, with OFFLINE in the header; each 1-minute bar equals Schwab's about 3 s after
  it closes; each book shown under its own venue; a viewed ticker's levels and heatmap repriced on
  every tick with no visible lag; the option rule's contracts held and updating; the heatmap chip's
  counts match its cells; every ticker's levels and Greeks against Schwab's own numbers (the
  watchlist's prices and changes matched Schwab's exactly on 2026-11-18, all 9).
- CARRIED-PRS (QUEUED): what the closed pull requests still wanted, each re-checked against main
  first: the status push on its own clock; the opening range from Schwab's open; settled contracts
  leave the book; a missing flip says what was searched; the charts name a gap after a drop; a chain
  valued at Schwab's `quoteTimeInLong` (operator call); the regime's reason and walls worded by
  their side of the price; one rule for whether options are open, from Schwab's windows, for every
  reader; a pre-market real chain's Greeks, volume and open interest; a half day's windows when
  Schwab sends one.
- TU-05 (QUEUED, after the rest): Options → Small Multiples and Key Levels: vanna and charm exposure
  in dollars per strike and expiry.
- TU-08 (QUEUED, after the rest): Key Levels: the regime's dead zone around the gamma flip.
- TU-11 (QUEUED, after the rest): Options → Small Multiples: skew and term fields.
- TU-06 (QUEUED, after the rest; also TU-07, TU-09, TU-10, TU-12): call-put IV spread, ΔOI flow,
  GEX/ADV normalization, an external GEX benchmark, intraday DDOI; each meaning confirmed from its
  source before it is built. No implied one-day move or band of standard deviations is built: the
  operator removed them from everywhere.
- LIQ-CARD (QUEUED): the order-imbalance build: step 1, the Desk Liquidity card
  (`push.book.liquidity_readout`), is built. Next: step 2, Level II with its balance scale; step 3,
  the Heatmap with TradingView-style controls, each to the operator's spec. Separate items when
  asked: a daily accumulator, a per-stock depth measure.
- LP-01 (QUEUED): check that the raw liquidity levels show on the Trade Desk chart.

## Operator decides

- ONE-30 (OPERATOR): an option contract's own SECURITY_STATUS is not read; inside its option window
  a Halted contract reads LIVE (`live_market_plane.not_trading`). Re-subscription snapshots resend
  old statuses, so taking the field needs a rule for which message is current.
- TAPE-BACKLOG (OPERATOR): the push sends each symbol's newest state, so a live tape can skip a
  print between pushes (the database keeps every one). Keep it so, or deliver each print once.
- DESK-INDEX-LINE (OPERATOR): the Trade Desk's foot strip repeats the three indexes the header's
  second row now shows on every page (`static/js/ed-trade-desk-map.js` `paintIndexes`), each with
  its last trade's time, on a line of its own. Whether that line stays is his. With it, at the
  1920×950 window, the Readings row's track is 27 pixels under its 36-pixel panel, and with every
  line of the Liquidity card at once as well (INDUCED) the Desk needs 823 pixels of its 808 and
  scrolls 15, as it needed 847 of 832 before the header changed; without that line both fit.
- INDEX-CLOSED (OPERATOR): on 2026-11-20 Schwab sent `SECURITY_STATUS` Closed for $VIX at 16:00:03
  ET and 46 more last-price messages after it; the live rule (`live_market_plane.live_state`) reads
  NOT LIVE from that status, so the header's index cells say NOT LIVE while their numbers still
  move. What the rule reads for an index after the stock close is his.
- ONE-ASK (OPERATOR): what Schwab is still asked more than once for, beside a streamed contract's
  fields in `/chains` (STREAM-ONE). Each changes a request rate, a setting or what the program
  holds, so each is his. The counts are the daemon's log of 2026-11-20 (20.5 hours, 25 starts). A
  start asks again for what the run before it was answered the same ET date, because the sweep
  remembers what it asked in memory only (`feed/chain_sweep.py` `_markets_day`, `_expiries`,
  `_candled`): each market date's sessions, each ticker's expiration chain and its ten price-history
  series, about 3,100 requests (911 of the 949 `/markets`, 199 of the 207 `/expirationchain`, about
  2,000 `/pricehistory`). Measured on the start of 2026-11-21 17:06 CT (the market closed, nine
  tickers): $SPX's 52 expiry dates' sessions took 16 s before its chain was asked, the other eight
  tickers' price history 43 s, and the first rotation delivered 9 of 9 tickers in 129 s. The record
  holds the sessions and the price history (`stream_markets_raw`, `stream_pricehistory_raw`), not
  the expiration chains. Whether a start reads the day's answers from the record instead of asking
  again changes what Schwab is asked and how fresh a start's first values are. Since
  `tests/test_data_path_rules_v1.py`
  `test_d5_a_ticker_selected_while_the_price_history_is_asked_has_its_own_next` the ticker on a page
  no longer waits for the others' price history. The 5-, 15- and 30-minute price history is asked
  whole, ten days of bars, each time one bar completes (about 2,300 requests). `/quotes` is asked
  again with every chain for the symbols it named invalid (1,725 named in 48 answers). The request
  rate is his decision: raised until Schwab refuses a few requests, for every endpoint and every
  pushed service, never held below what Schwab takes. Measured with four requests at once: 243 to
  310 a minute in regular hours (2026-11-18 to 11-20), the four slots full 45% of the time before
  `ChainSweep.send_quotes` kept them full; Schwab support states 120 a minute for non-order
  endpoints (`schwab-support-2026-10-06`) and answered no `/quotes` request 429 at up to 515 in a
  minute (1,339,785 requests, 2026-10-10 to 11-22). Next: a regular session measured at the full
  four (429s, a round's time, the stream's lag), then `schwab_client.REQUESTS_AT_ONCE` up one step
  at a time until Schwab refuses a few.
- AS-SENT (OPERATOR): what still stands between Schwab and the screen, each his to keep or delete:
  model gates on derived reads (GSF/GRC under `GSF_EPS_FRAC`; the 25Δ risk reversal's 0.10 delta
  tolerance; depth to 5 levels); a book side with no levels has no depth total.
- INTERPRET (NEXT; operator 2026-11-20): every reading of ours laid over Schwab's data, found and
  listed with what it adds over the field as sent: a buyer/seller label (Lee-Ready against the bid
  and ask, `calc/l1_trade_observation.py`), a sum or split of ours (Options Level II's lean, marked
  INTERPRET in `docs/derived_register.md`), a threshold, a rule that blanks or merges a value. Each
  one shown to be needed and sourced, or deleted; one Schwab sends only changed fields (Streamer
  API), so a field missing from a message is unchanged, its held value current. The option book's
  resting size (OPTIONS_BOOK, up to 100 contracts) is the confluence matrix revamp's input. Decided:
  the tape's buyer/seller signing (Lee-Ready) stays, marked estimated on screen ("Flow observations
  (estimated)", `tests/e2e/console-gamma-flow.spec.js`); a print is read against Schwab's bid and
  ask in force when it traded, never the quote that followed it
  (`calc.l1_trade_observation.quote_in_force`, `tests/test_quote_in_force_v1.py`); the page writes
  no reading of its own (a session volume of 0 is served with what it means,
  `push.strikes._shown_migration`); the Confluence matrix's readings say "untested" and carry no
  direction word (`tests/e2e/console-confluence.spec.js`): a reading of ours is called a direction
  only once recorded data supports it (operator 2026-11-21). The matrix revamp (decisions 61 to 64
  of the operator's matrix plan) is built as one change and deployed when ready (operator
  2026-11-23); what it leaves for later, each needing sessions of the record: each reading's running
  record session by session, pace's 20-session baseline, and the stock book and tape's vote.
- Review decisions (OPERATOR, from REVIEW): the zone-width cap
  (`calc.liquidity_models.PlaybookConfig.max_zone_width`); compileall at push;
  `tools/bootstrap_worktree_venv.py`; an estimate of who holds the contracts from where streamed
  option trades land against the bid and ask (tabled by him).

## Designing (nothing is built until the operator decides)

- RESEARCH (DESIGNING): quant formulas that decide stock, calls, puts or spreads, run on the stored
  chain history; where it lives is undecided.
- PLAN (DESIGNING): Trade Desk → Plan.
- QUANT (DESIGNING): studies on the recorded data, after the census, each making a screen message
  rest on measured evidence: event studies at levels, look-forward returns by served value, implied
  against realized volatility, regime detection, order-flow decay, the same study over every ticker,
  and the data's own gaps. Each with a fixed design, walk-forward testing and a multiple-testing
  correction; a study that finds nothing changes or removes the message it tested.
- OI-STREAM (DESIGNING): the stream's OPEN_INTEREST misses some contracts' daily update; left: the
  other recorded days, why, and what a change in open interest says for trading.
- PORTFOLIO (DESIGNING): Portfolio / Risk, from Schwab's account API, fetched by Feed.
- VOL-GAMMA (DESIGNING): option volume in the gamma read (for example volume-weighted gamma for
  same-day expiries).
- DESK-GAPS (DESIGNING): Trade Desk elements with no canonical value yet, each keeping its place and
  saying why: high- and low-volume nodes; absorption, liquidity pull and replenishment (need
  per-trade prints the stream does not carry); R1/R2/S1/S2; severity and each card's 1-hour change.
  The tick-rule trade-side estimate (`calc/order_flow.py`, labelled PROXY in Options → Flow) is
  still to be deleted.
