# ACTIVE_PROGRAM.md — the current work, in order

The one record of operator-directed work: what is in flight, queued or blocked. The design every
item is built to is `docs/DATA_FLOW.md`; where code lives is `docs/ARCHITECTURE.md`. Rows leave this
file when they finish (git keeps them). The first rule is simple: the simplest plan that fits the
design, with nothing kept that has no job.

Status values: `NEXT` | `IN PROGRESS` | `QUEUED` | `BLOCKED` | `OPERATOR`.

## Phase 1 — restore and stabilize

| ID | Status | Work item |
|---|---|---|
| P1-9 | QUEUED | **Enforce the code rules** (AGENTS.md "Before writing code", "Authority"), each starting with no exceptions: `.gitattributes` makes every file LF, normalized in one commit; ruff forbids imports outside the module top (PLC0415); one formatter per format (Central Time: `time_et.ct_label`, 2026-09-27); typed records for values crossing modules; history prose out of code. Time passed as an input (`now`) is built with P2-3's remaining part, which rebuilds the live price path (the call sites of `resolve_spot`, `price_row` and `feed_live_for`). |
| P1-6 | QUEUED | **Fallbacks and second authorities**: each item in the list below is fixed at its source (rule 1), with a behavior test; an item leaves the list when it is fixed. The list is every row of the old fallback register still present in the code (checked 2026-09-29 against 1e44ff5c, each by name). |
| P1-8 | QUEUED | **CI clean-up**: dead tests and tools; the E2E suite's fixed sleeps (35.6 s of 122 s); the hardening job's unneeded installs (torch and others); the flaky console-gamma-controls QQQ test; the CI log keeps only a 13-line tail, so a failure's received value and error context are lost. |
| LIVE-SESSION | QUEUED | **Next-session checks** (each is runtime evidence only for what it observes): the heatmap stays live through RTH (ONE-05 fix); AM-settled $SPX monthly contracts stop pricing at the 09:30 open on 2026-10-16; the 9:30 and 4:15 chain captures and their log lines; Schwab's gamma against the model curve in session (the flip's clock); IV units; TIMESALE_EQUITY re-tested; IEX prints inside NYSE_BOOK; the zeros taken as sent (operator ruling 2026-09-27: open interest, price and IV 0 are 0) measured in session against the weekend's ($SPX 2026-09-14: 19,440 of 19,520 contracts OI 0); the price shows Schwab's last trade with its trade time at every hour (pre-market, after 20:00 ET, a weekend) and the header reads LIVE or FEED DOWN by the feed alone, the levels computed from that price, across the board; SPY's 2026-10-14 and 2026-10-15 heatmap columns read $0 for every strike whose contracts have open interest 0 and "no contract listed" where none is listed (measured before the fix on 2026-10-01 08:59 ET: 121 and 30 such cells drawn "—"); the charts' last completed bar advances each minute about 3 s after it closes (Schwab CHART_EQUITY), each candle equal to Schwab's bar, and the chart's LAST line moves with the header's price on every update, across the board; each Schwab book (NYSE_BOOK, NASDAQ_BOOK) arriving and shown under its own venue, across the board; every board ticker's levels as-of advancing pre-market, after hours and on a weekend (the daemon's chain sweep fetches at any hour), with each failed fetch's reason, across the board; a ticker put on screen (on or off the board) is the daemon's active ticker within a second and its chain is fetched back to back, its levels and heatmap repriced on every tick with no visible lag. |
| SPEED | NEXT | **Measure the opened-wide path** (operator 2026-10-01: "no caps, no throttling. open it up wide and lets see how it goes. we can dial back if we need to"). The daemon runs 8 chain workers, the active ticker back to back, every part and quote batch of a chain at once; the console reprices a viewed ticker back to back and pushes each change at once. NOT_PROVEN on the live board: each chain's request times (the daemon log's `chain TK: N contracts; chain P part(s) s; quotes Q request(s) s; total s` line), the round time (the console's status line), every 429 in the daemon log (a 429 pauses every chain request 10 s, the active ticker's included; any other failed fetch, 5 s), the requests waiting on the Schwab client's 100 connections (httpx's default; schwab-py passes no limit, the pool wait has no timer of ours), one token refresh racing across the 8 workers and the stream's client, and the console's page response while repricing back to back (2026-09-24: per-tick repricing starved the event loop; `/api/health` took 6 s). Next: one session's numbers across the board, to the operator. Then: one live WebSocket to the page instead of a push then a route read (P2-3), and the $SPX levels computation (1.4 s measured 2026-10-01). Chain captures stored before 2026-10-01 carry the chain's rounded Greeks until newer captures exist. |
| DATA-SYN | OPERATOR | **Fabricated bars in `price_bars_1m`**: 14,491 rows with source `synthetic_interior_grid_repair_v1` (14,490, 47 tickers, 2026-03-24 to 2026-07-17) and `synthetic_anchor_coverage_pad_v1` (1); no code writes them; every bar reader reads them. Deleting data is the operator's. |

### P1-6 — what is still open, by file

**server.py**
- S-02 `_write_streamed_bar` reads `bar_start_ms` raw (not `schwab_number`): text, -999 or NaN passes the None check.
- S-10 `_gamma_surface_coverage_summary` serves `live_pct` 0.0 when no cell is relevant (absent with a reason instead).
- S-11 `_publish_levels` seeds level crosses with a stored capture's past spot (`prev_spot`), stamped now.
- S-22 `_prior_strikes` and `terrain_engine.per_strike_view` each define the 7-DTE near/far split.
- S-23 `_side_sums` leaves a row's missing strike, gamma or volume out of its sum without counting them; its sums use the live spot while the rows were priced at the snapshot's.
- S-38 `_publish_levels` reads the database (`newest_capture_ts`) on every new chain to learn whether a newer capture exists; the daemon, which writes the captures, could carry that time on the chain it delivers.
- S-39 the daemon reloads `stream_wanted.json` at its start and streams the option contracts and the active ticker last asked for until the console reconnects.
- S-24 live screens read the database: `/api/bars1m` and the price levels (`_read_bars_1m`), `/api/options/tape` (`tape_rows_for_symbol`), the book heatmap, `/api/desk/events` (level crosses), the ATR (with ONE-04/05/06).
- S-30 the equity microstructure route (`flow`), the options one (`streaming_plane`), `_contract_admission` and the microstructure content build return None/{} after an exception with no reason.
- S-35 `get_levels` expected-move levels: live spot ± the chain-time move, stamped with the terrain's time and stale flag, computed in the route.
- S-36 `_build_raw_levels_used` takes `prev_day` or `prev` (the two snapshot builders name it differently).
- S-37 / M-03 `_liquidity_zone_tradeable_fields`: midpoint anchor when `zone_mid` is missing; with no spot, `liquidity_zone_tradeable_score` uses another formula instead of absent; the distance penalty is computed in the route; `/api/options/tape` turns an invalid `limit` into 100.
- M-28 `gsf_state` (model curve at spot) and `regime` (Schwab's book) judge gamma at spot from two sources; `gsf_state` is documented as the regime and carries no basis.

**liquidity_value_engine.py, liquidity_models.py**
- M-01 `_resolve_bar_timestamp` takes the first of `timestamp`/`date`/`ts`; `_bars_to_list` guesses the unit by size (`> 1e12`).
- M-02 `_bars_to_list` and `volume_profile` drop bars (no time, non-number price, `hi < lo`) without counting them.
- M-04 `compute_opening_range` hard-codes 9:30 instead of `RTH_OPEN_MINS`.
- M-05 `compute_session_vwap_series` skips volume-less bars without disclosing the count.
- M-08 truthiness drops a 0 price (`if prev.get("pdh")`, `if vah:`, `if poc:`, `p and p > 0`, …).
- M-09 a missing poc, pd_poc or vwap yields `value_state="unchanged"` / `vwap_relation="at_value"` (and `else 0`).
- M-11 `cutoff_et` (now) is served as the values' time (they are as of the last bar); `session_scope` relabels an unknown scope; prior-day POC/VAH/VAL missing is not in `families_absent`.
- M-12 fused option levels: raw `float()`, rejected ones dropped silently.
- `build_price_level_snapshot` reads the clock (`produced_ts`) instead of taking `now`.

**math_exposure_core.py, math_levels.py**
- M-13 one strike/multiplier validity rule for both files (core accepts strike 0, levels rejects ≤ 0; both reject multiplier ≤ 0, unconfirmed against Schwab's field reference); count IV ≤ 0 in the vanna path.
- M-14 contracts with no strike or side are dropped uncounted.
- M-16 the vanna path re-checks IV inline (`_iv_ok`) beside `schwab_iv_to_sigma`; stale comment cites a removed guard.
- M-19 `_total_dex` fills a missing side with 0.
- M-21 `compute_zero_dte_gamma_share` serves 0% when the 0DTE book has no valid gamma; `pick_pin_and_strength` serves 100% with no runner-up.
- M-22 `book_net_gex` sums only strikes with valid gamma, without saying how many it left out.
- M-24 `compute_charm_by_strike` returns {} with no reason (no spot) and skips unpriced contracts uncounted.
- M-25 the flip profile turns a non-finite gamma into 0.
- M-27 two interpolators for gamma at a price (`_interp_profile_at`, `gamma_at_price`), both returning the end value off the profile.

**terrain_engine.py, terrain_atr.py, math_volatility.py, math_probabilities.py, time_et.py**
- M-31 `computed_ts_utc` is compute time documented as fetch time, with two writers.
- M-32 per-expiry PCR/IV maps key by date alone while books key by (date, dte): same-date books overwrite.
- M-33 the ATM IV expiry is the one nearest 30 days; its docs say "front expiry".
- M-34 `terrain_atr` uses DB OHLC raw (no `schwab_number`).
- M-35 `compute_atr` reads first-of keys with raw `float()`, skips candles uncounted and carries `prev_close` across them.
- M-36 the pin score clamps `oi_concentration` to [0, 1] and divides by an unsourced $50,000 (PIN-FLOOR).
- M-37 `time_to_expiry_years` floors T at 10 minutes.
- M-38 04:00/20:00 are literals in `session_label`; `time_to_expiry_years` does its own close lookup; 9:30 has two names.

**app/options/order_flow/, live_price_rows.py, live_market_plane.py**
- O-02 equity TOTAL_VOLUME is written into `_stream_greeks` (read only for options).
- O-04 a 0 MARK, BOOK_TIME or quote time reads as missing (truthiness / `> 0`).
- O-09 the price display (`spot_disp`) is formatted in three places.
- O-13 malformed push messages and bad frames are dropped uncounted; `_pick_producer_contract` falls back to `symbols[0]`.
- O-15 `_trade_age_sec` clamps a negative age to 0.
- O-17 the book heatmap's `method` text says "both venues merged".
- O-18 `history`: an invented 0.01 axis width; contract context carried forward; read failures return [] with no reason; EXPIRATION_* read raw and truth-tested.
- O-20 the default contract at startup/closed is picked from the stored capture's spot with no age.
- O-24 on reconnect the last `bar1m` is replayed and processed as a new bar.

**The daemon and Schwab client**
- O-21 `stream_spine._now` substitutes `time.time()`; no capture builder passes the receive time.
- O-22 symbols keyed with `.upper().strip()` instead of `ticker_storage_key` (stream_spine, capture, streaming).
- O-23 flat L1 columns copied raw into `stream_quotes_raw` beside `native_json`, read by no product code.
- O-25 `FullChainResponse.json()` returns {} on failure; a split chain's top-level fields come from the first part only.
- D-13 `complete_chain_capture` reads `underlyingPrice` raw: text aborts the whole round.
- D-14 `complete_chain_capture` drops non-dict and no-expiry contracts uncounted and counts `written` per ticker, not from `persist`.
- D-16 `live_schwab_env` keeps a second placeholder-credential list beside `config`.
- D-18 `runtime_preflight` reports a missing requirements.txt as satisfied.

**Page code (static/js)**
- P-01 `scopeSelect` picks the middle strike when no `spot_strike` is served; the window and hidden count are computed on the page.
- P-02 ages formatted and thresholded on the page (`fmtAge`, `Math.round(trade_age_sec)`); the push-silence verdict is the page's clock (`PRICE_SILENCE_MS`).
- P-06 the heatmap's zero threshold, changed-cell comparison and coverage counts are computed on the page.
- P-07 the heatmap's as-of shows browser-local time, not Central.
- P-08 the heatmap picks its columns and falls back to expired ones when none are unexpired.
- P-09 an absent `live` reads live; first-of and "undefined" reasons; stale cells drawn as normal values; a column-0 default; every error relabelled "no console serving".
- P-10 six or more page formatters for dollars and volume with different precision.
- P-12 Strike Detail matches contracts by tolerance, substitutes the put for the call, uses a UTC date and reads the raw contracts (a -999 prints).
- P-13 Key Levels: a fallback age formatter and a page-computed live badge.
- P-14 the chart drops old tail revisions and markers with no bar uncounted, colours a missing change as up, and picks the levels shown.
- P-16 Trade Desk ages, dates, percents and the LEVELS age are computed on the page; PD value-area picked by id.
- P-18 Trade Desk labels first-of, a sign flipped on the page, and strike-to-wall matching on the page.
- P-19 a second and third ACK validator in `ed-stream.js`.
- P-22 an unknown subscription state shows PENDING; the Flow header's strike and expiry come from page state.
- P-24 the order book matches walls on the page and gives one reason for every no-book cause.

## One producer (rule 3, rule 6)

Each row is a second copy or a second computation of one value. It is fixed by deleting down to one
producer, with a behavior test that fails if the second one returns.

| ID | Status | Work item |
|---|---|---|
| ONE-02 | QUEUED | Equity last price and size kept a second time in the console's order-flow tape (`state.py` tape and receive log). |
| ONE-03 | QUEUED | Feed liveness judged in both processes: the daemon applies its own heartbeat to its price rows (`live_ui.beat`), and the console applies the pushed copy again (`feed_live_for`); one rule since ONE-15, two places it runs. |
| ONE-04 | QUEUED | Equity books: the console's order-flow copy and the database copy read by the Book Heatmap (`history.book_heatmap_for_ticker`, a live screen reading the DB). |
| ONE-05 | QUEUED | Option quotes: the options tape reads the database copy (`history.tape_rows_for_symbol`, a live screen reading the DB) beside the order-flow copy. |
| ONE-06 | QUEUED | 1-minute bars in two databases (with P2-DB4). A chart's bar history (`/api/bars1m`) and the price-level producer (after each bar) read `price_bars_1m` (`_read_bars_1m`): a live screen reading the database (rule 6). |
| ONE-12 | QUEUED | Trade side: history's quote rule beside the live tick rule (with the trade-side decision, directive 3). |

## Phase 2 — the rest of the design, then decomposition

| ID | Status | Work item |
|---|---|---|
| P2-2 | QUEUED | **The levels producer in its own process** (DATA_FLOW decision 2); results pushed. First measured against the simpler complete design (levels computed in the console, off the request path): page response during a board sweep, failure isolation, who owns the process. Not built unless that proves it necessary; the result goes to the operator. Ships with its check: the console imports no calculation module. |
| P2-3 | IN PROGRESS | **Everything pushed to the browser**, two push connections (operator 2026-09-27): the daemon pushes prices and bars, the console pushes what changed (`/api/changes`, `push_changes.py`: `levels`, `chain`, `flow`, `liquidity`, the session label). Left: the daemon pushes the 1-minute bars (the charts read `/api/bars1m` after a `liquidity` push today); the option-contract demand lease re-sent every 30 s (`ed-stream.js`) ends with the page's connection instead; time passed as an input (`now`) on the live path (P1-9). |
| P2-5 | QUEUED | **db.py**: move what remains (bars, level history, enrollment, connection) to `daemon/`. |
| P2-6 | QUEUED | **server.py**: the levels loop and gamma-surface projection to `producer/`, the routes and startup to `console/`. |
| P2-7 | QUEUED | **The other large files**: liquidity_value_engine.py, app/options/order_flow/streaming.py and engine.py, math_exposure_core.py, ed-core.js, ed-gamma.js — cut what has no job, move each part to the process that runs it. |
| P2-DB3 | QUEUED | **One offline maintenance window, after P2-5** (sizes measured 2026-09-26): copy `ed_console.db` whole; stop the app; drop the ML tables (~49 GB; no code creates, writes or reads them since P2-5 part 1: `snapshots_1m_normalized`, `model_accuracy`, `gamma_surface_last_valid`, `ed_schema_flags`, `confluence_quote_ticks`, `logging_universe_eviction_log`, `calibration_decision_log`, `production_decision_records`, `model_execution_identities`, `decision_persistence_ledger` and the identity triggers on them and on `snapshots`; `snapshots` and `iv_daily`, whose DDL left with P1-7), the bar leftovers (`price_bars_1m_quarantine`, `price_bars_1m_staging`), the desk tables and option_chain_accrual (no writer or reader since the standalone pages were deleted, 2026-09-27); in `stream_capture.db`, `stream_prints_raw` (no writer since the Alpaca print feed was removed 2026-09-24; Schwab refuses trade prints); compress the plain-text chain rows; move the morning chains into `complete_chain_captures` and drop the morning table; VACUUM; restart and check. Rows captured while the market was closed are deleted only on the operator's word. The codec's plain-text branch and the backfill tool are deleted after. |
| P2-DB4 | QUEUED | **One database, `ed_console.db`** (operator 2026-09-26): the stream tables move into it; the daemon's writer writes every table, including the console's (bars, level crosses, the ticker board). |
| P2-DB5 | QUEUED | **The console reads read-only.** Ships with its check: a database write outside the one writer fails. |

## Phase 3 — the placeholders on screen (after Phase 1 and 2)

| ID | Placeholder | What fills it |
|---|---|---|
| TU-05 | Options → Multi-Map; Key Levels → Vanna Support, Charm Resistance | vanna/charm exposure in dollar units per strike × expiry |
| TU-08 | Key Levels → Zero Gamma, Volatility Trigger | regime dead-zone around the flip |
| TU-11 | Options → Multi-Map | skew and term fields |
| TU-06, 07, 09, 10, 12 | none yet | call−put IV spread and implied 1-day move, ΔOI flow, GEX/ADV normalization, external GEX benchmark, intraday DDOI (meaning confirmed from its source before building) |
| LP-01 | Liquidity | steps 1–3 are in `liquidity_models.py` / `liquidity_value_engine.py` (`/api/liquidity-snapshot`); left: check the raw levels show on the Trade Desk chart |

## Operator designing — nothing is built until the operator decides

| ID | Item |
|---|---|
| RESEARCH | Quant formulas that decide stock, calls, puts or spreads, and research run on the stored chain history. Where it lives (Trade Desk or its own screen) is undecided. |
| PLAN | Trade Desk → Plan. |
| PORTFOLIO | Portfolio / Risk: needs the operator's positions from Schwab's account API, fetched by the daemon. |
| RATE-DIV | The risk-free rate and dividend yield Schwab sends with each chain (stamped on every contract), used or not by the model curve, vanna and charm. |
| PIN-FLOOR | The pin score's $50,000 GEX floor (binds for MTA, NBIX, TSL): keep, change or remove, after research. |
| VOL-GAMMA | Option volume in the gamma read (e.g. volume-weighted gamma for same-day expiries). |
| DESK-GAPS | The Trade Desk reference shows elements with no canonical value yet; each keeps its place and says why. (2) High- and low-volume nodes: no producer and not drawn (a 70% value area is not a node; peaks and troughs need a rule of their own; `hvp`/`lvp` are gamma strikes, not volume). (3) Absorption, liquidity pull, replenishment: not produced (open). Each needs per-trade prints at price and venue, which the stream does not carry; TIMESALE is to be asked in market hours in a window the operator agrees (it stops the capture daemon, the one Schwab stream, for about a minute). The chart's events are level crosses as recorded, drawn as numbered callouts. (4) R1/R2/S1/S2: no producer. (5) Severity and each card's 1-hour change: no producer (each card's chart draws a served series: book depth by price, 1-minute volume, put/call OI and ATM IV by expiry; no axis numbers, a page-derived number is not printed). (6) The Trade Desk's Order Flow card shows Schwab's session volume, last trade size, top of book and level crosses; the tick-rule trade-side estimate is off it, and is still shown, labelled PROXY, in Options → Flow (`static/js/ed-gamma-flow.js`; its producer in `app/options/order_flow/engine.py`) until ONE-12 deletes it. |
| AS-SENT | What stays between Schwab and the screen after the 2026-10-01 removal (operator: "From Schwab's mouth to our UI's ears. Period."; "remove all these silly rules already"), each the operator's to keep or delete: (1) AGENTS.md rule 5 says a past observation never feeds current logic, and the spot is now Schwab's last trade at any hour, feeding the levels with its trade time: rule 5's wording is the operator's to change (AGENTS.md is operator-only). (2) Model gates on derived reads, not on Schwab fields: the regime withheld under the flip's ±5% strike-span floor (`terrain_read`), the pin candidate's four gates and $50,000 floor (PIN-FLOOR), GSF/GRC withheld under 0.5% of max \|N\| (`GSF_EPS_FRAC`), the 25Δ risk reversal's 0.10 delta tolerance, same-day expiries out of the 1-day move, wall candidates at 3× the median level, depth to 5 levels. (3) Bounds: the tape's last 500 prints, the book heatmap's 20,000 rows. (4) A book side with no levels has no depth total (its imbalance is absent, not -1 or +1). (5) The market-session badge reads CLOSED by the calendar (it gates nothing). (6) The console drops its copy of the daemon's price rows after 3 s with no frame from the daemon. |
| UNSHOWN | Nine values the levels producer computes and `/api/terrain` serves are shown by no screen and read by no code: `absolute_gamma_strength_pct`, `absolute_gamma_gex_dollars`, `absolute_gamma_oi`, `book_oi_total`, `pin_candidate_blockers`, `gsf_state`, `zero_dte_gamma_share_pct`, `rr_25d`, `vanna_agg`. Show each or delete it. |

## Operator host steps

| ID | Item |
|---|---|
| RECON-02 | `Trading/_disk_cleanup_quarantine_20260716` (53 GB): about 50 GB is old copies of the database (2026-05-27, 06-10, 06-11 and a 16 GB `db_backups` folder) and about 3 GB old report copies. They are the only database backups, so they are purged, on the operator's word, only after the P2-DB3 copy is made and verified. |
| CALENDAR-2029 | Add the NYSE 2029 holidays and early closes to time_et (US_EQUITY_CALENDAR_YEARS covers 2025-2028) when the NYSE publishes them, before 2029-01-01. From that date the calendar treats every uncovered day as closed (by design: never a guessed session), so the app would stop capturing and refreshing. |
| RUNTIME-SEPARATION | Move the runtime state (database, logs, token, diagnostics) out of the production checkout into a runtime folder. |
