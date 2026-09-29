# ACTIVE_PROGRAM.md — the current work, in order

The one record of operator-directed work: what is in flight, queued or blocked. The design every
item is built to is `docs/DATA_FLOW.md`; where code lives is `docs/ARCHITECTURE.md`. Rows leave this
file when they finish (git keeps them). The first rule is simple: the simplest plan that fits the
design, with nothing kept that has no job.

Status values: `NEXT` | `IN PROGRESS` | `QUEUED` | `BLOCKED` | `OPERATOR`.

## Phase 1 — restore and stabilize

| ID | Status | Work item |
|---|---|---|
| P1-9 | QUEUED | **Enforce the code rules** (AGENTS.md "Before writing code", "Authority"), each starting with no exceptions: `.gitattributes` makes every file LF, normalized in one commit; ruff forbids imports outside the module top (PLC0415); one formatter per format (Central Time: `time_et.ct_label`, 2026-09-27); typed records for values crossing modules; history prose out of code. Time passed as an input (`now`), with the conftest session-clock stand-in deleted, is built with P2-3's remaining part, which rebuilds the live price path (36 call sites of `resolve_spot`, `live_spot`, `price_row` and the live rule today). |
| P1-6 | QUEUED | **Fallbacks and second authorities**: each item in the list below is fixed at its source (rule 1), with a behavior test; an item leaves the list when it is fixed. The list is every row of the old fallback register still present in the code (checked 2026-09-29 against 1e44ff5c, each by name). |
| P1-8 | QUEUED | **CI clean-up**: dead tests and tools; the E2E suite's fixed sleeps (35.6 s of 122 s); the hardening job's unneeded installs (torch and others); the flaky console-gamma-controls QQQ test; `console-gamma-chart.spec.js` "with no expiry filter set" failed twice on CI (2026-09-29; cause not established: not reproduced locally at 8x CPU throttle, not a late expiry list, not a delayed click; its click tests now wait for the selection) — the CI log keeps only a 13-line tail, so the failure's received value and error context are lost. |
| LIVE-SESSION | QUEUED | **Next-session checks** (each is runtime evidence only for what it observes): an off-board ticker kept open on the Liquidity workspace for more than 5 minutes is refreshed each cycle (its levels' as-of advances), and a board ticker the same; the heatmap stays live through RTH (ONE-05 fix); AM-settled $SPX monthly contracts stop pricing at the 09:30 open on 2026-10-16; the 9:30 and 4:15 chain captures and their log lines; Schwab's gamma against the model curve in session (the flip's clock); IV units; TIMESALE_EQUITY re-tested; IEX prints inside NYSE_BOOK; the zeros taken as sent (operator ruling 2026-09-27: open interest, price and IV 0 are 0) measured in session against the weekend's ($SPX 2026-09-14: 19,440 of 19,520 contracts OI 0); rule 5 both ways: a valid past observation on screen shows its source, time and a label saying so, and none feeds current logic; the price reads LIVE from 04:00 ET and MARKET CLOSED with the last trade's time from 20:00 ET, across the board; the charts' last completed bar advances each minute about 3 s after it closes (Schwab CHART_EQUITY), each candle equal to Schwab's bar, and the chart's LAST line moves with the header's price on every update, across the board; each Schwab book (NYSE_BOOK, NASDAQ_BOOK) arriving and shown under its own venue, across the board. |
| DATA-SYN | OPERATOR | **Fabricated bars in `price_bars_1m`**: 14,491 rows with source `synthetic_interior_grid_repair_v1` (14,490, 47 tickers, 2026-03-24 to 2026-07-17) and `synthetic_anchor_coverage_pad_v1` (1); no code writes them; every bar reader reads them. Deleting data is the operator's. |

### P1-6 — what is still open, by file

**server.py**
- S-02 `_write_streamed_bar` reads `bar_start_ms` raw (not `schwab_number`): text, -999 or NaN passes the None check.
- S-03 `_hydrate_logger_tickers_from_db` keeps the unpruned roster when the prune fails; the daemon's `board_tickers` never prunes.
- S-08 `terrain_staleness` calls a snapshot of any age not stale when not refreshing (closed market): label it a past observation with its time.
- S-09 `terrain_staleness` uses `TERRAIN_REFRESH_SEC` when no cycle time has been measured.
- S-10 `_gamma_surface_coverage_summary` serves `live_pct` 0.0 when no cell is relevant (absent with a reason instead).
- S-11 `_publish_levels` seeds level crosses with a stored capture's past spot (`prev_spot`), stamped now.
- S-12 `get_levels` treats a spot of 0 as missing (`and spot`).
- S-22 `_prior_strikes` and `terrain_engine.per_strike_view` each define the 7-DTE near/far split.
- S-23 `_side_sums` drops rows with a missing strike, gamma or volume without counting them; its sums use the live spot while the rows were priced at the snapshot's.
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
- M-14 contracts with no strike or side are dropped uncounted; a bad multiplier is counted as "greeks missing" and its OI never reaches `oi_unreported`, so the strike's OI reads a known 0.
- M-15 `bucket_metric` gates GEX/DEX/vanna per strike, not per leg: an invalid leg reads its 0.0 start as data.
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
- M-38 04:00/20:00 are literals in two functions; `time_to_expiry_years` does its own close lookup; 9:30 has two names.

**app/options/order_flow/, live_price_rows.py, live_market_plane.py**
- O-02 equity TOTAL_VOLUME is written into `_stream_greeks` (read only for options).
- O-03 two spread producers in the engine (`_compute_spread`, `_microstructure_structural`); MARK relabelled `quote_mid` and back.
- O-04 a 0 MARK, book price, bid/ask, BOOK_TIME or quote time reads as missing (truthiness / `> 0`).
- O-06 `_compute_institutional_flow_proxy` clamps with invented 10,000/50,000 divisors.
- O-07 `state.py` swallows a failed clock read and RTH reset (debug log only) and reads the console clock, not the message time.
- O-09 the price display (`spot_disp`) is formatted in three places.
- O-13 malformed push messages and bad frames are dropped uncounted; `_pick_producer_contract` falls back to `symbols[0]`.
- O-15 `_trade_age_sec` clamps a negative age to 0.
- O-16 `closed_last` carries no source.
- O-17 book heatmap cells start at bid/ask 0.0 (an unobserved side reads 0); its `method` text says "both venues merged".
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
- P-04 first-of reads (`q.spotState || q.spot_state`, `q.spot_disp || fmt(q.spot)`); dead `'stale'` branches; the header shows the change in every state while the watchlist does not.
- P-06 the heatmap's zero threshold, changed-cell comparison and coverage counts are computed on the page.
- P-07 the heatmap's as-of shows browser-local time, not Central.
- P-08 the heatmap picks its columns and falls back to expired ones when none are unexpired.
- P-09 an absent `live` reads live; first-of and "undefined" reasons; stale cells drawn as normal values; a column-0 default; every error relabelled "no console serving".
- P-10 six or more page formatters for dollars and volume with different precision.
- P-12 Strike Detail matches contracts by tolerance, substitutes the put for the call, uses a UTC date and reads the raw contracts (a -999 prints).
- P-13 Key Levels: a fallback age formatter and a page-computed live badge.
- P-14 the chart drops old tail revisions and markers with no bar uncounted, colours a missing change as up, and picks the levels shown.
- P-16 Trade Desk ages, dates, percents and the LEVELS age are computed on the page; PD value-area picked by id.
- P-18 Trade Desk labels first-of, a sign flipped on the page, `/1e6`, and strike-to-wall matching on the page.
- P-19 a second and third ACK validator in `ed-stream.js`.
- P-22 an unknown subscription state shows PENDING; the Flow header's strike and expiry come from page state.
- P-24 the order book matches walls on the page and gives one reason for every no-book cause.

**Code with no job (to delete)**
- X-04 `config.py` `barchart_*` directories and `diagnostics_dir` (no reader, or a test only).
- X-05 `engine.py` `_compute_options_flow`, `_compute_rvol`, `_compute_institutional_flow_proxy` (no caller supplies their inputs) and the constant-None `order_flow_*` keys.
- X-08 unused parameters and branches: `compute_gamma_profile` `span_pct`/`steps`; `compute_exposures_by_strike` `use_only_dte_max` (and `require_oi=False`, test-only); `compute_flip_diagnostics`'s `profile is None` branch (its caller always passes one); `pick_net_gex_peak_strike(institutional=...)` raw branch; `_regime_for` `spot`/`flip` and its stale docstrings; `PlaybookConfig.max_distance_from_anchor`; `Candle.mid`; the per-strike bid/ask size and OI-dollar fields (read only by a test).
- X-09 `EdStream.status` and what only it reaches (`subscriptionState`, `planeIsBoundToContract`), `getDesiredAdditional`, the gate's `isCurrent`/`pendingContract`; `EdGamma.cellStyle`/`renderSurface` exports (tests only); the fallback `usd` formatters behind `EdGamma.formatUsd ||` and the loader stubs behind `EdL1SseGuards ?` (ed-gamma-chart, -chain, -flow, -levels, -panels).
- X-10 a test probes `rl.describe()` and `db.DB_DIR` (neither exists); the `db_safety.py` docstring names functions that do not exist; a `time_et.py` comment names a deleted tool.
- S-05 `_merged_recent_crosses` writes a `level_name` nothing reads; M-26 the flip's unreachable no-spot branch; X-02 a test keeps its own 11-ticker list and count.

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
| ONE-07 | QUEUED | Option chains fetched by two processes with two writers to `ed_console.db` (with P2-1). |
| ONE-12 | QUEUED | Trade side: history's quote rule beside the live tick rule (with the trade-side decision, directive 3). |

## Phase 2 — the rest of the design, then decomposition

| ID | Status | Work item |
|---|---|---|
| P2-1 | QUEUED | **The daemon fetches the chain** (DATA_FLOW decision 1); the console's chain fetch is deleted. Ships with its check: a Schwab call outside the daemon fails. |
| P2-2 | QUEUED | **The levels producer in its own process** (DATA_FLOW decision 2); results pushed. First measured against the simpler complete design (levels computed in the console, off the request path): page response during a board sweep, failure isolation, who owns the process. Not built unless that proves it necessary; the result goes to the operator. Ships with its check: the console imports no calculation module. |
| P2-3 | IN PROGRESS | **Everything pushed to the browser**, two push connections (operator 2026-09-27): the daemon pushes prices and bars, the console pushes what changed (`/api/changes`, `push_changes.py`: `levels`, `chain`, `flow`, `liquidity`, the session label). Left: the daemon pushes the 1-minute bars (the charts read `/api/bars1m` after a `liquidity` push today); the option-contract demand lease re-sent every 30 s (`ed-stream.js`) ends with the page's connection instead; time passed as an input (`now`) on the live path, with the conftest session-clock stand-in deleted (P1-9). |
| P2-5 | QUEUED | **db.py**: move what remains (bars, level history, enrollment, connection) to `daemon/`. |
| P2-6 | QUEUED | **server.py**: the chain fetch to `daemon/`, the levels loop and gamma-surface projection to `producer/`, the routes and startup to `console/`. |
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
| UNSHOWN | Nine values the levels producer computes and `/api/terrain` serves are shown by no screen and read by no code: `absolute_gamma_strength_pct`, `absolute_gamma_gex_dollars`, `absolute_gamma_oi`, `book_oi_total`, `pin_candidate_blockers`, `gsf_state`, `zero_dte_gamma_share_pct`, `rr_25d`, `vanna_agg`. Show each or delete it. |

## Operator host steps

| ID | Item |
|---|---|
| RECON-02 | `Trading/_disk_cleanup_quarantine_20260716` (53 GB): about 50 GB is old copies of the database (2026-05-27, 06-10, 06-11 and a 16 GB `db_backups` folder) and about 3 GB old report copies. They are the only database backups, so they are purged, on the operator's word, only after the P2-DB3 copy is made and verified. |
| CALENDAR-2029 | Add the NYSE 2029 holidays and early closes to time_et (US_EQUITY_CALENDAR_YEARS covers 2025-2028) when the NYSE publishes them, before 2029-01-01. From that date the calendar treats every uncovered day as closed (by design: never a guessed session), so the app would stop capturing and refreshing. |
| RUNTIME-SEPARATION | Move the runtime state (database, logs, token, diagnostics) out of the production checkout into a runtime folder. |
