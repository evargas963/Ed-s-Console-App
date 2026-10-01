# ACTIVE_PROGRAM.md — the current work, in order

The operator-directed work: what is in flight, queued or blocked. Rows leave this file when they
finish (git keeps them). Evidence: **observed** (seen on real data), **code-proven** (a test or a
traced path shows it), **unverified** (reported by the 2026-09-30 review, not yet reproduced).

Status values: `NEXT` | `IN PROGRESS` | `QUEUED` | `BLOCKED` | `OPERATOR`.

## Exceptions

None.

## Wrong on screen now

| ID | Evidence | Violation | Owner | Closed by |
|---|---|---|---|---|
| W-01 | observed | A held quote from an earlier session reads live: real PCG messages (2026-09-29 19:55 to 09-30 04:01 ET) give 12.14, +1.59%, 46,270,430 shares, "live" at 04:00:05 ET. | `live_market_plane` | Each field current only in the session it was received; the test on those messages (branch `fix/session-boundary-freshness`). |
| W-02 | code-proven | Live is judged by heartbeat, socket and subscription only (`feed_live_for`), so a symbol Schwab stops sending mid-session reads live (§3.5 6). | `live_market_plane`, `capture` | The live verdict needs the service to be delivering the symbol; a test with the feed up and the symbol silent. |
| W-03 | code-proven | A lost message is invisible: no Schwab frame time or sequence is kept, queue drops are counted and read by nothing (§3.5 7). | `capture`, `stream_spine` | A drop withdraws the live state of the symbol it would have changed; a test that drops one delta. |
| W-04 | code-proven | Tests approve violations: S-39, M-15, P-09 (below), and `test_order_flow_book_heatmap_v1` requires a 1970 book served as available. | the tests named | Each corrected to the requirement in the change that fixes its violation; never xfail. |
| W-07 | unverified | Panels fed through `/api/changes` (order book, chain, levels ages) are not told when their source stops; their LIVE badges stay. | `push_changes`, the producers | A push on every change of a value's live state; a test with the source stopped and no further tick. |
| W-08 | unverified | The console keeps a price row after its ticker leaves the stream (only silence or disconnect clears it), and `resolve_spot` serves it. | `app/options/order_flow/streaming.py` | Rows not wanted are dropped on each subscribe; a test. |
| W-09 | unverified | A console restart replaces the daemon's standing roster with the console's first, partial list (2026-09-29 12:19 ET: 45 → 13 symbols held for 139 s). | `capture` | The board roster is standing demand the console only adds to; a test. |
| W-10 | unverified | Chain captures lost with no record or retry (2026-09-28 10:00 and 12:00 ET, 2026-09-30 16:00 and 16:15 ET; tickers dropped on HTTP 429). | `calibration/complete_chain_capture.py` | Per-ticker retry within the slot and an outcome row per ticker per slot; a test. |
| W-11 | unverified | Eight injected faults no test caught: a negative size served; a missing bar volume set to 0; the console row kept on silence and on disconnect; trade age forced to 0; bar open and close swapped; the closed label dropped; a missing price printed `0.00`. | the tests of those producers | A test per fault that fails with the fault in place. |
| W-12 | unverified | The calendar misses the 2025-01-09 NYSE closure; the $SPX default contract can be the AM-settled monthly on its expiry day; the posture defaults to STAND_ASIDE with no data. | `time_et`, `app/options/contracts/default.py`, `terrain_read` | Each reproduced, then fixed with its test. |
| W-13 | unverified | The option contract's top of book is held with no receive time, and the console's order-flow state is not cleared when its push reconnects. | `app/options/order_flow/state.py` | Each field with its receive time; state cleared on reconnect; a test. |

## Governance and operations

| ID | Status | Work item |
|---|---|---|
| BASIS | QUEUED | **Thresholds whose basis cannot be reproduced** (code-proven: the study scripts they cite were deleted): `math_levels.GAMMA_FLIP_MIN_SPAN_PCT` (0.05, its own comment measures it insufficient), `terrain_engine.PIN_CANDIDATE_PROXIMITY_MAX_FRAC` (0.005), `PIN_CANDIDATE_DTE_MAX` (1) and the pin candidate's long-gamma cut; VWAP is an estimate from 1-minute bars and is not labeled one. Each gets a reproducible basis (a committed test or study on captured data) or goes to the operator; the operator items PIN-FLOOR, DRIFT, ZONE-WIDTH and VALUE-SHIFT are the same class. |
| VALIDATE | QUEUED | **Trade-affecting logic shown without validation** (code-proven: no validation evidence is committed): the posture (`terrain_read`, Trade Desk), the regime call and the pin candidate. Each gets committed evidence (no lookahead, train/serve parity, out-of-sample against a baseline, costs, calibration) or stops being shown as a call. |
| OPS-HOST | QUEUED | **Host state** (measured 2026-09-30 17:39 CT): C: 146 GB free; `ed_console.db` 77.9 GB, `stream_capture.db` 27.8 GB, no retention; the only backups are dated 2026-09-07/08, on the same disk, never restored; ports 8000 and 8800 listen on 0.0.0.0 on a network the host classes Public; the console is not supervised (the daemon restarts itself). Each gets an owner and its failure behavior (`docs/host/README.md`). |
| ENFORCE | QUEUED | **Controls that do not yet exist**: nothing checks that a Schwab field is read only through `schwab_number` / `schwab_count`; the credential scan runs only in the local commit hook; CI runs on Linux, so the Windows-only guard tests never run there. |

## Phase 1 — restore and stabilize

| ID | Status | Work item |
|---|---|---|
| P1-9 | QUEUED | **Enforce the code rules**, each starting with no exceptions: `.gitattributes` makes every file LF, normalized in one commit; ruff forbids imports outside the module top (PLC0415); one formatter per format (Central Time: `time_et.ct_label`, 2026-09-27); typed records for values crossing modules; history prose out of code. Time passed as an input (`now`): done on the live price path (the live rule, `daemon_status`, `price_row`, the daemon's price socket `live_ui`, which judges every row, beat and gap at the clock its entry point passes; the conftest session-clock stand-in is deleted, P2-3); done on the levels path (`_is_loggable_session`, `terrain_staleness`, `terrain_cache_get`, the refresh hold, `_terrain_refresh_one`, `_price_stored_chain_when_closed`, `options_gamma_surface`, the status line); done on the levels' ATR and the gamma surface's session stamp (`_atr_pair`, `_stamp_surface_session`: one response, one clock); left, functions below an entry point that still read the clock themselves: `server._stamp_gamma_surface_cell_stream_state`, `_publish_price_levels`, `canonical_price_level_snapshot`, and the modules outside `server.py` (not yet enumerated). No check enforces a Schwab field being read only through `schwab_number` / `schwab_count`. |
| P1-6 | QUEUED | **Fallbacks and second authorities**: each item in the list below is fixed at its source, with a behavior test; an item leaves the list when it is fixed. The list is every row of the old fallback register still present in the code (checked 2026-09-29 against 1e44ff5c, each by name). |
| P1-8 | QUEUED | **CI clean-up**: dead tests and tools; the E2E suite's fixed sleeps (35.6 s of 122 s); the hardening job's unneeded installs (torch and others); the flaky console-gamma-controls QQQ test; the CI log keeps only a 13-line tail, so a failure's received value and error context are lost. Tests not on captured Schwab data through the real code (reviewed 2026-09-30): hand-built data with no stated reason (`test_trade_desk_desk_v1`, `test_session_vwap_semantic_fidelity_v1`, `test_bars_from_stream_v1`, `test_action11_1_math_levels_fail_closed`, `test_live_ui_daemon_to_browser_v1`, `test_options_order_flow_api_v1`'s "real" book, the Flow tape spec's row); e2e fixtures that re-implement the server (`tests/e2e/fixtures/served_chain.js`'s ladder, the heatmap spec's cell roll-up) instead of being generated by it; `options_microstructure_payload.json` stamped with a 20-day-old book time; tests of private helpers or signatures (`test_terrain_per_strike_live_v1`, `test_charm_docstring_states_the_physics_v1`, `test_live_market_plane_streaming`, `test_db_sqlite_tier1_retry`); missing failure cases (-999 gamma at spot, charm with -999 IV or NaN gamma, a stale or empty book on the order-flow heatmap spec, invalid IV/delta/OI on the tape spec). |
| LIVE-SESSION | QUEUED | **Next-session checks** (each is runtime evidence only for what it observes): an off-board ticker kept open on the Liquidity workspace for more than 5 minutes is refreshed each cycle (its levels' as-of advances), and a board ticker the same; the heatmap stays live through RTH (ONE-05 fix); AM-settled $SPX monthly contracts stop pricing at the 09:30 open on 2026-10-16; the 9:30 and 4:15 chain captures and their log lines; Schwab's gamma against the model curve in session (the flip's clock); IV units; TIMESALE_EQUITY re-tested; IEX prints inside NYSE_BOOK; the zeros taken as sent (open interest, price and IV 0 are 0) measured in session against the weekend's ($SPX 2026-09-14: 19,440 of 19,520 contracts OI 0); a valid past observation on screen shows its source, time and a label saying so, and none feeds current logic; the price reads LIVE from 04:00 ET and MARKET CLOSED with the last trade's time from 20:00 ET, across the board; the charts' last completed bar advances each minute about 3 s after it closes (Schwab CHART_EQUITY), each candle equal to Schwab's bar, and the chart's LAST line moves with the header's price on every update, across the board; each Schwab book (NYSE_BOOK, NASDAQ_BOOK) arriving and shown under its own venue, across the board. |
| DATA-SYN | OPERATOR | **Fabricated bars in `price_bars_1m`**: 14,491 rows with source `synthetic_interior_grid_repair_v1` (14,490, 47 tickers, 2026-03-24 to 2026-07-17) and `synthetic_anchor_coverage_pad_v1` (1); no code writes them; every bar reader reads them. Deleting data is the operator's. |

### P1-6 — what is still open, by file

Evidence: code-proven, each item checked by name against the code on 2026-09-29 (1e44ff5c); owner:
the file it is listed under; closed by the fix at that owner with a behavior test that fails on
the old code.

**server.py**
- S-03 `_hydrate_logger_tickers_from_db` keeps the unpruned roster when the prune fails; the daemon's `board_tickers` never prunes.
- S-08 `terrain_staleness` calls a snapshot of any age not stale when not refreshing (closed market): label it a past observation with its time.
- S-09 `terrain_staleness` uses `TERRAIN_REFRESH_SEC` when no cycle time has been measured.
- S-10 `_gamma_surface_coverage_summary` serves `live_pct` 0.0 when no cell is relevant (absent with a reason instead).
- S-22 `_prior_strikes` and `terrain_engine.per_strike_view` each define the 7-DTE near/far split.
- S-24 live screens read the database: `/api/bars1m` and the price levels (`_read_bars_1m`), `/api/options/tape` (`tape_rows_for_symbol`), the book heatmap, `/api/desk/events` (level crosses), the ATR (with ONE-04/05/06).
- S-30 the options microstructure route (`streaming_plane`) and `_contract_admission` return None/{} after an exception with no reason.
- S-35 `get_levels` expected-move levels: live spot ± the chain-time move, stamped with the terrain's time and stale flag, computed in the route.
- S-39 the gamma surface's per-cell stream state is stamped when the levels are published and served as current: once the feed stops, a cell stamped live still reads live until the next publication, and none follows after the levels loop stops. `tests/test_gamma_surface_cell_stream_state_v1.py` (the endpoint tests) serves stamps made with the feed down as live: its expectation is corrected with the fix.
- S-38 `_forces_from_captures` ΔOI is the change in each strike's total between two days' books: an expiry open in the older capture and settled in the newer reads as an open-interest change (2026-09-28 → 09-29: SPY 173,365 and QQQ 213,310 contracts of open interest on such contracts), and opposite changes on two contracts at one strike cancel.

**liquidity_value_engine.py, liquidity_models.py**
- M-01 `_resolve_bar_timestamp` takes the first of `timestamp`/`date`/`ts`; `_bars_to_list` guesses the unit by size (`> 1e12`).
- M-02 `_bars_to_list` and `volume_profile` drop bars (no time, non-number price, `hi < lo`) without counting them.
- M-05 `compute_session_vwap_series` skips volume-less bars without disclosing the count.
- M-11 `session_scope` relabels an unknown scope.
- M-39 the opening range of a ticker that trades in few minutes stays "forming" until its first bar after the window ends (no clock in the producer: a bar is the only proof the window's last minute is complete).

**math_exposure_core.py, math_levels.py**
- M-13 one strike/multiplier validity rule for both files (core accepts strike 0, levels rejects ≤ 0; both reject multiplier ≤ 0, unconfirmed against Schwab's field reference); count IV ≤ 0 in the vanna path.
- M-14 contracts with no strike or side are dropped uncounted; a bad multiplier is counted as "greeks missing" and its OI never reaches `oi_unreported`, so the strike's OI reads a known 0.
- M-15 `bucket_metric` gates GEX/DEX/vanna per strike, not per leg: an invalid leg reads its 0.0 start as data, so a strike whose put has -999 volatility serves the call's GEX as the strike's net. `tests/test_canonical_gex_input_validity_v1.py` asserts this (the put leg's 0.0): its expectation is corrected with the fix.
- M-16 the vanna path re-checks IV inline (`_iv_ok`) beside `schwab_iv_to_sigma`; stale comment cites a removed guard.
- M-19 `_total_dex` fills a missing side with 0.
- M-21 `pick_pin_and_strength` serves 100% with no runner-up.
- M-22 `book_net_gex` sums only strikes with valid gamma, without saying how many it left out.
- M-24 `compute_charm_by_strike` returns {} with no reason (no spot) and skips unpriced contracts uncounted.

**terrain_engine.py, terrain_atr.py, math_volatility.py, math_probabilities.py, time_et.py**
- M-31 `computed_ts_utc` is compute time documented as fetch time, with two writers.
- M-32 per-expiry PCR/IV maps key by date alone while books key by (date, dte): same-date books overwrite. An expiry date holding AM- and PM-settled roots ($SPX: SPX and SPXW on the third Friday, same date and DTE) is one book, one ATM IV (the first listed root's) and one max pain.
- M-34 `terrain_atr` uses DB OHLC raw (no `schwab_number`).
- M-35 `compute_atr` reads first-of keys with raw `float()`, skips candles uncounted and carries `prev_close` across them.
- M-36 the pin score clamps `oi_concentration` to [0, 1] and divides by an unsourced $50,000 (PIN-FLOOR).
- M-37 `time_to_expiry_years` floors T at 10 minutes.
- M-38 04:00/20:00 are literals in two functions; `time_to_expiry_years` does its own close lookup; 9:30 has two names.

**app/options/order_flow/, live_price_rows.py, live_market_plane.py**
- O-04 a 0 MARK, book price, bid/ask, BOOK_TIME or quote time reads as missing (truthiness / `> 0`).
- O-07 `state.py` swallows a failed clock read and RTH reset (debug log only) and reads the console clock, not the message time.
- O-09 the price display (`spot_disp`) is formatted in three places.
- O-13 malformed push messages and bad frames are dropped uncounted; `_pick_producer_contract` falls back to `symbols[0]`.
- O-15 `_trade_age_sec` clamps a negative age to 0.
- O-16 `closed_last` carries no source.
- O-17 book heatmap cells start at bid/ask 0.0 (an unobserved side reads 0); its `method` text says "both venues merged".
- O-18 `history`: an invented 0.01 axis width; read failures return [] with no reason; EXPIRATION_* read raw and truth-tested.
- O-27 a streamed option greek, open interest or volume sent as not a number leaves the last valid value in `_stream_greeks` (the top of book clears its field). Not seen in 2,114,423 stored LEVELONE_OPTIONS messages (2026-09-29/30, 1,194 contracts): no failure to test against yet.
- O-28 `price_bars_1m.source`: rows written before 2026-09-30 say `schwab_1m_accumulator_sqlite` whatever wrote them; new rows say `schwab_chart_equity`. Nothing reads the column.
- O-20 the default contract at startup/closed is picked from the stored capture's spot with no age.

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
- P-09 an absent `live` reads live; first-of and "undefined" reasons; stale cells drawn as normal values; a column-0 default; every error relabelled "no console serving". `tests/e2e/console-gamma-heatmap.spec.js` asserts the cells drawn as normal values (a cell whose legs are unavailable, a partial cell, and a `gex: [null]` cell marked live): its expectations are corrected with the fix.
- P-10 six or more page formatters for dollars and volume with different precision.
- P-12 Strike Detail matches contracts by tolerance, substitutes the put for the call, uses a UTC date and reads the raw contracts (a -999 prints).
- P-13 Key Levels: a fallback age formatter and a page-computed live badge.
- P-14 the chart drops old tail revisions and markers with no bar uncounted, colours a missing change as up, and picks the levels shown.
- P-16 Trade Desk ages, dates and the VIX percent are formatted or computed on the page; PD value-area picked by id.
- P-18 Trade Desk labels first-of, a sign flipped on the page, `/1e6`, and strike-to-wall matching on the page.
- P-19 a second and third ACK validator in `ed-stream.js`.
- P-22 an unknown subscription state shows PENDING; the Flow header's strike and expiry come from page state.
- P-24 the order book matches walls on the page and gives one reason for every no-book cause.

## One producer

Each row is a second copy or a second computation of one value (evidence: code-proven, the copies
named in the row). It is fixed by deleting down to one producer, with a behavior test that fails
if the second one returns.

| ID | Status | Work item |
|---|---|---|
| ONE-03 | QUEUED | Feed liveness judged in both processes: the daemon applies its own heartbeat to its price rows (`live_ui.beat`), and the console applies the pushed copy again (`feed_live_for`); one rule since ONE-15, two places it runs. |
| ONE-04 | QUEUED | Equity books: the console's order-flow copy and the database copy read by the Book Heatmap (`history.book_heatmap_for_ticker`, a live screen reading the DB). |
| ONE-05 | QUEUED | Option quotes: the options tape reads the database copy (`history.tape_rows_for_symbol`, a live screen reading the DB) while the console's memory holds the same contract's quote fields (`state.py`). |
| ONE-06 | QUEUED | 1-minute bars in two databases (with P2-DB4), and the day's minutes in the daemon's memory (`live_ui`, which pushes each new bar to the charts, P2-3). A chart's bar history as it opens (`/api/bars1m`) and the price-level producer (after each bar) read `price_bars_1m` (`_read_bars_1m`): a live screen reading the database. |
| ONE-07 | QUEUED | Option chains fetched by two processes with two writers to `ed_console.db` (with P2-1). |

## Phase 2 — the rest of the design, then decomposition

| ID | Status | Work item |
|---|---|---|
| P2-1 | QUEUED | **The daemon fetches the chain** (DATA_FLOW decision 1); the console's chain fetch is deleted. Ships with its check: a Schwab call outside the daemon fails. |
| P2-2 | QUEUED | **The levels producer in its own process** (DATA_FLOW decision 2); results pushed. First measured against the simpler complete design (levels computed in the console, off the request path): page response during a board sweep, failure isolation, who owns the process. Not built unless that proves it necessary; the result goes to the operator. Ships with its check: the console imports no calculation module. |
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
| LP-01 | Liquidity | steps 1–3 are in `liquidity_models.py` / `liquidity_value_engine.py` (`/api/liquidity-snapshot`); left: check on the deployed app that the Trade Desk chart draws the session levels of `/api/levels` (the zones route no longer serves a second copy of them) |

## Operator designing — nothing is built until the operator decides

| ID | Item |
|---|---|
| RESEARCH | Quant formulas that decide stock, calls, puts or spreads, and research run on the stored chain history. Where it lives (Trade Desk or its own screen) is undecided. |
| PLAN | Trade Desk → Plan. |
| PORTFOLIO | Portfolio / Risk: needs the operator's positions from Schwab's account API, fetched by the daemon. |
| RATE-DIV | The risk-free rate and dividend yield Schwab sends with each chain (stamped on every contract), used or not by the model curve, vanna and charm. |
| PIN-FLOOR | The pin candidate's "liquidity" gate (`qualify_pin_candidate` → `compute_pin_score`). (a) Its $50,000 GEX floor (binds for MTA, NBIX, TSL): keep, change or remove, after research. (b) What it measures: the absolute-gamma strike's share of the open interest of the whole multi-expiry book, passing at 10%. A broad chain cannot reach that (MRVL's full chain 0.5%, a single-expiry SPY chain 7.1%) while a thin one does (PCG 11.3%), so on the board's liquid tickers no pin candidate can publish. Recommended: measure the share within the front expiry, the expiry the gate's own DTE rule says pinning belongs to. Until decided the gate is unchanged; its inputs (`absolute_gamma_strength_pct`, `absolute_gamma_gex_dollars`, `absolute_gamma_oi`, `book_oi_total`) stay on the snapshot with it. |
| RR-25 | The 25-delta risk reversal (`rr_25d`, for the TU-11 skew fields; shown nowhere yet). It takes the listed call and put whose deltas are nearest ±0.25 within ±0.10 and reports their IVs as the 25-delta IVs: on PCG 2026-09-24 the "25-delta call" is a 0.194-delta contract, and the next day's reading moved from +4.84 to −30.86 on two contracts with no bid. Recommended: the IV at 0.25 delta interpolated between the two listed contracts that bracket it on each side, absent when a side is not bracketed. Unchanged until decided. |
| DRIFT | The positioning drift on the Trade Desk (`positioning_migration`): UP or DOWN when the positive-gamma-weighted strike moved more than $0.15 from the prior day, for every ticker at every price (the constant's origin is not recorded). PCG's move of 0.03 reads FLAT; the same positioning at 100 times the price reads UP; for $SPX FLAT is out of reach. Recommended: compare the move with the spacing of the listed strikes around spot (a move of less than one strike step is FLAT). Unchanged until decided. |
| VOL-GAMMA | Option volume in the gamma read (e.g. volume-weighted gamma for same-day expiries). |
| SETTLE-ETF | When an expiring option of a late-close ETF leaves the book. The one settlement rule takes every PM-settled contract out at the 16:00 ET cash close, which is when SPXW and single-stock options stop trading. Expiring options on the ETFs that trade to 16:15 ET (on the board: SPY, QQQ, IWM, SMH, XLE) trade until 16:15 on expiration day (Cboe, checked 2026-09-30), and the levels loop publishes until 16:30, so for those 15 minutes their expiring contracts are out of the book while still trading; their time to expiry is measured to 16:00 as well. Schwab sends no per-contract field for it (`expirationDate` is 16:00 ET and `lastTradingDay` a date for every contract), so matching it needs a list of those products kept by hand. Keep 16:00 for all, or authorize that list. |
| FLIP-DOMAIN | The prices the gamma flip is looked for at: spot ±15% today. On the 2026-09-29 close captures 11 of 43 tickers had no sign change there; evaluated over every listed strike, 10 of them have one further out (INTC −15.9%, MU −15.8%, MSFT −16.6%, SMCI −17.0%, NET −27.6%, META −28.0%, PCG −32.1%, MTA −50.8%, TSL −56.8%, CRWD −60.1% from spot) and CIFR has none. Keep ±15%, change it, or show the nearest sign change wherever it is, with its distance. The curve holds each contract's implied volatility fixed, which is less true the further the price is moved. |
| DESK-GAPS | The Trade Desk reference shows elements with no canonical value yet; each keeps its place and says why. (2) High- and low-volume nodes: no producer and not drawn (a 70% value area is not a node; peaks and troughs need a rule of their own; `hvp`/`lvp` are gamma strikes, not volume). (3) Absorption, liquidity pull, replenishment: not produced (open). Each needs per-trade prints at price and venue, which the stream does not carry; TIMESALE is to be asked in market hours in a window the operator agrees (it stops the capture daemon, the one Schwab stream, for about a minute). The chart's events are level crosses as recorded, drawn as numbered callouts. (4) R1/R2/S1/S2: no producer. (5) Severity and each card's 1-hour change: no producer (each card's chart draws a served series: book depth by price, 1-minute volume, put/call OI and ATM IV by expiry; no axis numbers, a page-derived number is not printed). (6) The Trade Desk's Order Flow card shows Schwab's session volume, last trade size, top of book and level crosses; no trade side is computed or shown anywhere (DATA_FLOW decision 9). |
| LIVE-ROLLUP | A live chart bar above 1 minute (3m to D) is the roll-up of the minutes in its bucket, because Schwab streams only 1-minute bars (CHART_EQUITY); aggregating earlier minutes is allowed (operator, 2026-09-30). The store is read at the daemon's startup only (`live_ui.day_minutes`): the day's stored minutes of its chart symbols, then only what Schwab streams. Open: a bucket missing a minute is rolled up with no mark of the gap; whether Schwab sends a bar for a minute with no trade is NOT_PROVEN (measure across the board in session), and until it is, a missing minute cannot be told from a quiet one. Unchanged until decided. |
| OVERNIGHT-BARS | The overnight high and low. The bar store keeps 09:15 ET to 15 minutes after the close (no bar outside it: all 43 board tickers, 7 days, measured 2026-09-30), so the "overnight" levels were the range of the 15 minutes before the open and after the prior close; they are absent now, with that reason. The daemon receives Schwab's 1-minute bars through the extended session. Store them (the collect window, RC-183, is the operator's law) and the overnight range is real; or leave it absent. Recommended: store 04:00–20:00 ET and build the level from the prior close to the open. |
| VALUE-SHIFT | "Value shifted higher / lower" on the Trade Desk: today's point of control more than 0.2% from the prior day's (the figure's origin is not recorded; 0.2% is $1.53 on SPY and $0.02 on PCG). Recommended: shifted when today's point of control is outside the prior day's value area. Unchanged until decided. |
| ZONE-WIDTH | No zone is wider than $2.00, for every ticker at every price (`server.ZONE_MAX_WIDTH_DOLLARS`; origin not recorded), beside the 0.2% merge distance: on $SPX (7,671) the 0.2% is $15.34, so the $2 cap decides what merges; on PCG (12.17) the 0.2% is $0.02 and the cap never binds. Recommended: drop the dollar cap and keep the percentage. Unchanged until decided. |
| ATR-DEF | The ATR on the Trade Desk is the simple average of the last 14 true ranges (`math_volatility.compute_atr`, as its docstring states); Wilder's ATR, the usual meaning of "ATR(14)", smooths them (each new value is 13/14 of the last plus 1/14 of the new range). Its daily candle is every stored bar of the day (09:15 to 15 minutes after the close), not the 09:30–16:00 session. Recommended: Wilder's smoothing on regular-session candles. Unchanged until decided. |
| BAR-TF | Rolled-up chart bars. A 60-minute bar is a clock hour (the first is 09:15–09:59, then 10:00–10:59; a session-anchored chart shows 09:30–10:29); a daily bar is every stored bar of the date, so its open is the 09:15 price and its range takes in the 15 minutes before the open and after the close. Recommended: anchor intraday bars to the 09:30 open and build the daily bar from the regular session. Unchanged until decided. |
| TAPE | The Options Flow tape shows each change of Schwab's last trade, which is not every trade (the stream reports the last trade when it sends; one captured message moves volume by 2 with a last size of 1). It is labelled so. Keep it as labelled, or remove the panel; every trade needs TIMESALE (DESK-GAPS 3). |
| UNSHOWN | Values served that no screen shows yet, each kept for a named purpose and shown by its item or deleted with it. On `/api/terrain`: `rr_25d` (TU-11, RR-25), `vanna_agg` (TU-05), the pin gate's four inputs (PIN-FLOOR), and `flip_diag` (the flip's search range, crossings and unpriced counts: FLIP-DOMAIN's evidence). On the price row: Schwab's OPEN_PRICE, HIGH_PRICE, LOW_PRICE and NET_CHANGE (the day's open, high and low are the daily bar's if BAR-TF is decided that way). |
| DESK-CARD-LINE | Each Trade Desk card prints one line of facts, cut where the card ends (the reference's layout). At 1672 px the Options Positioning line ends after P/C OI: Max pain, Contracts and the FORCES split (GEX, ΔOI, DEX and charm below / above, with the captures and price they are split at) are on the line and not visible; the whole line is the card's hover text. Where the FORCES split is shown is the operator's layout call. |

## Operator host steps

| ID | Item |
|---|---|
| RECON-02 | `Trading/_disk_cleanup_quarantine_20260716` (53 GB): about 50 GB is old copies of the database (2026-05-27, 06-10, 06-11 and a 16 GB `db_backups` folder) and about 3 GB old report copies. They are the only database backups, so they are purged, on the operator's word, only after the P2-DB3 copy is made and verified. |
| CALENDAR-2029 | Add the NYSE 2029 holidays and early closes to time_et (US_EQUITY_CALENDAR_YEARS covers 2025-2028) when the NYSE publishes them, before 2029-01-01. From that date the calendar treats every uncovered day as closed (by design: never a guessed session), so the app would stop capturing and refreshing. |
| RUNTIME-SEPARATION | Move the runtime state (database, logs, token, diagnostics) out of the production checkout into a runtime folder. |
