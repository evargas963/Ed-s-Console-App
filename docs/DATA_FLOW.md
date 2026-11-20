# Ed Console — Data Flow

The data and its producers: how each value travels from Schwab to the screen and into the record,
which code produces it, and the test that holds it. Where code lives is `docs/ARCHITECTURE.md`; the
rules for every change are `AGENTS.md`. Every requirement here names what enforces it: a test, or
"no machine check" and the `ACTIVE_PROGRAM.md` item that builds one.

## 1. The design

```text
[Schwab] ─ stream + REST ─► [ one program:  Feed ─► State ─► Calculators ─► State ─► Push ] ─ one WebSocket ─► [page]
                                                      │
                                                      └─► Recorder ─► [ed.db: history]
```

The five parts are `AGENTS.md` "The shape". The facts that hold for every value:

- One program, one process, one port (§3.1). It holds the one Schwab streamer connection (Schwab
  allows one per user) and the one Schwab client (`capture.one_schwab_client`), built once and kept
  for the program's life. Enforced by: `tests/test_schwab_client_import_boundary.py`.
- One owner of the Schwab token: the client's session (`schwab_client.OneRefreshSession`) refreshes
  it one request at a time and writes it under the token file's lock
  (`schwab_client.token_file_lock`). Once Schwab refuses a refresh, every request raises
  `SignInRefused` and nothing is sent; a new sign-in saved by `python reauth_schwab.py` is taken
  with no restart. The session holds `schwab_client.REQUESTS_AT_ONCE` connections
  (`schwab_client.CONNECTIONS`), kept open until Schwab or the network ends one. Enforced by:
  `tests/test_data_path_sign_in_v1.py`, `tests/test_data_path_rules_v1.py`
  (`test_twenty_requests_at_a_refresh_send_one_refresh_and_all_carry_the_new_token`,
  `test_the_daemon_builds_one_schwab_client_and_a_failed_refresh_never_rebuilds_it`).
- One producer per value. A Schwab field is read once, where it arrives; a derived value is computed
  once, by its producer in `docs/derived_register.md`.
- Data is pushed at every hop; nothing polls. The page gets every panel on its one socket, `/ws`,
  and draws it; no route serves it data. Enforced by: `tests/test_page_one_faucet_v1.py`
  (`test_the_page_reads_no_route_only_its_socket`).
- The databases are history. Nothing on screen waits on them or reads them (D6). At startup the
  program loads the newest stored values once, so a restart, a weekend or the close shows the last
  values with their time, marked not live (D5). Enforced by: `tests/test_one_levels_producer_v1.py`.
- Where each part runs is §4.

## 2. The data rules

The rules for the data itself, at every hop from Schwab to the screen.

- **D1. Newest by Schwab's time wins.** Which value is current is decided by Schwab's own timestamp
  on it (quote time, trade time, book time, bar time, the chain's fetch), never by arrival order.
  Enforced by: `tests/test_data_path_rules_v1.py`.
- **D2. Everything Schwab sends is kept.** Every field and timestamp of every message reaches the
  record as sent; the database keeps it as D4 says. The daemon asks every streaming service for
  every field number Schwab accepts (`feed.connection.HIGHEST_FIELD`, sent by
  `feed.connection.Connection.send_requests`), so an undocumented field is kept too.
  `docs/schwab_fields.csv` lists every field Schwab has sent
  (`python -m tools.schwab_field_inventory`). Enforced by: `tests/test_data_path_rules_v1.py`; the
  field request, `tests/test_data_path_one_watchlist_v1.py`.
- **D3. The live path holds only the newest.** The message bus (`stream_spine.MessageBus`) keeps one
  current record per topic: a quote merged field by field, a book, bar or chain replaced whole. A
  newer value replaces the older at once; nothing old waits in a queue. Only the Recorder takes
  every message, and while the database refuses writes it holds them (D4). Enforced by:
  `tests/test_data_path_rules_v1.py`.
- **D4. The stream's tables in `ed.db` are the record.** One writer, `stream_spine.CaptureWriter`,
  records every bus message but option quotes and option books, which it records for the kept
  contracts only (`capture.Daemon.saves`): each ticker's soonest unexpired expiration at the strike
  nearest its price and `capture.STRIKES_SAVED` strikes each side (`capture.saved_window`), and the
  Flow panel's contract. Quotes, option quotes, bars and news are kept whole; order books before the
  regular open plus 30 minutes and in the session's last 30 minutes (`stream_spine._book_kept`).
  After five sessions (`capture.SESSIONS_KEPT`, `capture.keep_sessions`) those rows move into
  `stream_archive` as compressed blocks (`stream_spine.ARCHIVED`, read back by
  `stream_spine.archived_rows`); the tables of `stream_spine.KEPT_BY_TIME` (price history, chain and
  quote answers, operational tables) drop rows older than five sessions. A row the database refuses,
  or a statement of the writer's own (a keep part, a spill's progress row) that fails for its own
  reason, is kept as sent with its error in `stream_write_failures` and the writer goes on: an error
  is every write's when its SQLite code is in `stream_spine.REFUSAL_CODES` (busy, locked, full, I/O,
  read-only and the like), else that row's or statement's alone (`stream_spine._its_own`). While the
  database refuses every write, the writer holds messages in memory up to
  `stream_spine.HOLD_CAP_BYTES`, then in spill files beside the database (`<stem>.<ms>.<n>.spill`),
  and writes them back in order, recording progress in `stream_spill_progress`; files a stop or
  crash left are written back at the next start. Its state (`stream_spine.WriterStatus`) rides the
  daemon's heartbeat to the header's Record line. Enforced by:
  `tests/test_data_path_stream_kept_v1.py`, `tests/test_data_path_rules_v1.py`,
  `tests/test_data_path_writer_failures_v1.py`.
- **D5. The last value stands, marked** (`AGENTS.md` rule 5). A value is LIVE while its feed
  delivers it and its market trades (`live_market_plane.live_state`): the daemon's heartbeat is no
  older than `live_market_plane.FEED_HEARTBEAT_MAX_AGE_SEC`, the Schwab socket is open, the symbol
  is held on its service, and its market is in a window of Schwab's /markets answer (stocks:
  `time_et.session_label`, with the pre-market starting at the day's first streamed trade,
  `time_et.record_trade`; options: `time_et.options_open`). Otherwise the last value stands with its
  Schwab time and age, marked OFFLINE (the feed down) or NOT LIVE, and every value computed from it
  is marked too. The levels carry their own verdict (§3.4 Levels). A value never received, or sent
  invalid, shows "-". Calculations keep every digit; rounding is on screen only. Enforced by:
  `tests/test_data_path_rules_v1.py`, `tests/test_markets_sessions_v1.py`,
  `tests/test_data_path_live_status_v1.py`, `tests/test_data_path_strike_counts_v1.py`,
  `tests/test_data_path_side_volume_v1.py`, `tests/test_data_path_book_size_v1.py`,
  `tests/test_data_path_tape_size_v1.py`, `tests/test_data_path_silent_subscription_v1.py`,
  `tests/test_data_path_quote_time_v1.py`, `tests/test_data_path_book_time_v1.py`,
  `tests/test_data_path_option_quote_time_v1.py`, `tests/test_data_path_level_spot_v1.py`,
  `tests/test_data_path_chain_spot_time_v1.py`, `tests/test_data_path_desk_spot_time_v1.py`,
  `tests/test_data_path_chain_time_v1.py`, `tests/test_data_path_strike_chain_time_v1.py`,
  `tests/test_data_path_snapshot_time_v1.py`, `tests/test_data_path_level_asof_time_v1.py`,
  `tests/test_data_path_served_verdicts_v1.py`; the rest — ENF-22.
- **D6. No live screen reads the database.** Every panel is served from memory; the database is read
  at startup, after the close and for research only. Enforced by:
  `tests/test_data_path_rules_v1.py`.

## 3. The program

### 3.1 Start, stop and the port

The program is `app/market_data/schwab/streaming/capture.py` (`capture`), with the console part in
`server.py` and `app/options/order_flow/`.

- Started by `launch.py` (`start_ed_console.bat`), which brings the checkout to origin/main when the
  program is not running (`launch.bring_to_origin_main`), opens `start_capture_daemon.bat` in its
  own window (`launch.daemon_window`), waits for `/api/health` and opens the browser.
- `start_capture_daemon.bat` runs the program and restarts it 5 s after it exits, except after a
  clean stop (exit 5, `capture.EXIT_STOPPED`).
- Stopped only by `python launch.py stop`, which sets the program's stop request
  (`program_lock.ask_to_stop`, a named event); the program's waiter (`capture.stop_on_request`)
  stops it, and its writer writes what it holds. Enforced by: `tests/test_program_stop_v1.py`,
  `tests/test_data_path_startup_v1.py`.
- Its one socket (`capture.open_sockets`, port 8000 or `ED_CONSOLE_PORT`) serves the pages, the five
  `/api` routes and `/ws` (`capture.serve_console`, `server.app`); the port it holds is written to
  its lock (`program_lock.record_ports`).
- Its log is one file a day, `logs/stream_capture.<date>.log` (`capture.DailyLog`), the newest
  `capture.LOG_DAYS_KEPT` kept, and the same lines show in its window.
- Two parts in one process: the daemon part (Schwab, the bus, the Recorder) and the console part
  (pricing and the page's panels), which reads the daemon's bus in memory
  (`order_flow.streaming._bus_loop`). A crash of either ends both, and the window restarts the
  program.

### 3.2 How they talk

- **Schwab → daemon, stream:** equity quotes, option quotes, both equity books, option books,
  1-minute bars, news (`feed.connection.Connection`, one request per change, each answer matched by
  its request id and recorded in `stream_subscriptions`).
- **Schwab → daemon, REST:** option chains, option quotes, price history and market hours, by the
  chain sweep (`feed/chain_sweep.py`); every request logged once (`schwab_client.log_request`).
- **Daemon part → console part:** the bus in memory, a LATEST subscription
  (`order_flow.streaming._bus_loop`): each topic's current record as it changes, a chain in parts. A
  record that fails to apply is counted (`apply_failures` on the daemon's status beat, beside
  `tick_failures`) and logged with its traceback, and the next is applied. Enforced by:
  `tests/test_live_push_channel_v1.py`.
- **Console part → daemon part:** a call (`capture.Daemon.console_frame`): the Flow panel's contract
  and each watchlist add or removal, answered by the daemon's `watchlist` record.
- **Program → page:** `/ws` (`live_ui.page_socket`, `live_ui.LiveUiServer`): each symbol's price row
  on every change, every panel the page shows of its ticker (`server.PAGE_PANELS`) at once and again
  when its producer marks it changed (`live_ui.changed`), and the daemon's status every second
  (`live_ui.HEARTBEAT_SEC`). A client that stops reading is dropped (`live_ui.PageSocket`); the page
  reconnects. A frame, symbol or panel a page sends that the server cannot take is logged and
  counted (`page_refused`), and the beat carries the socket's counts (`page_socket`). The header
  shows these with the records not applied and the reprices failed, while any is above 0
  (`live_ui.left_out_line`, the beat's `left_out`). Enforced by:
  `tests/test_live_ui_daemon_to_browser_v1.py`, `tests/test_data_path_silent_price_v1.py`,
  `tests/e2e/console-sign-in.spec.js`.
- **Page → program:** HTTP for the page itself, `/api/health`, `/api/build`, `/api/watchlist` (POST,
  DELETE) and `/api/flow-contract`.

### 3.3 Where data lives

- **Daemon memory:** the bus's current records and each ticker's newest whole chain; the watchlist
  (`capture.Daemon.watchlist`); the option rule's order and the Flow panel's contract; the price
  rows (`live_market_plane`).
- **Console memory:** each symbol's newest book per service and its newest
  `order_flow.state.MAX_TAPE_PRINTS` trade prints (`order_flow.state.OrderFlowState`); the books of
  the last 240 minutes (`order_flow.history.BOOKS`) and the order-imbalance readout, one value a
  second for `calc.order_flow.OF_LEAN_KEPT_SEC` (`order_flow.history.LEAN`); the published levels
  (`state/level_store.py`); the price-level snapshots (`state/price_level_store.py`); the 1-minute
  bars and other price-history series (`state/bar_store.py`); the two newest days' chain captures
  (`state/capture_store.py`); the level crosses (`state/cross_store.py`).
- **`ed.db`** (`db_authority.canonical_db_path`): the stream's tables (D4), written by
  `stream_spine.CaptureWriter`; the chain captures (`complete_chain_captures`), written by the same
  writer (`CaptureWriter.store_capture`); the level crosses (`level_crosses`), written by the same
  writer (`CaptureWriter.store_crosses`). The console part reads it read-only (`db.EdDB`, SQLite's
  `mode=ro`). A new database gets its receipt-time indexes with its tables
  (`stream_spine.RECEIPT_TIME_INDEXES`); an existing table is never reindexed at a start.
- **Spill files** (`ed.<ms>.<n>.spill`, beside `ed.db`): the writer's held messages while the
  database refuses writes (D4).

### 3.4 The journey of each kind of data

- **Equity quote.** LEVELONE_EQUITIES → the bus → (a) the Recorder, `stream_quotes_raw`; (b)
  `capture.Daemon._took_quote` → `live_market_plane.record_from_level_one_equity` → the price row
  (`live_price_rows.price_row`) → `/ws` → header, watchlist and every panel's live price
  (`push.spot.resolve_spot`); (c) the console's intake → the tape and the level-cross check. The
  last trade's price, size and time have one reader, `calc.l1_trade_observation.last_print`.
  Enforced by: `tests/test_last_print_one_reader_v1.py`, `tests/test_data_path_quote_time_v1.py`.
- **Order book.** NYSE_BOOK, NASDAQ_BOOK and OPTIONS_BOOK → the bus → the Recorder,
  `stream_book_raw` (D4) → the console (`order_flow.state.OrderFlowState`, one book per service,
  never combined) → the `book` and `bookmap` panels (`push.book.book`, `push/bookmap.py`), sent
  again on each book (`server.FLOW_PANELS`). The Liquidity card's order-imbalance readout of both
  books and their composite is computed once per book (`calc.order_flow.book_readout`) and kept a
  second at a time (`order_flow.history.LEAN`). A side Schwab sent with no levels is empty, never an
  older book's. Enforced by: `tests/test_data_path_book_time_v1.py`,
  `tests/test_data_path_book_size_v1.py`.
- **Option quote.** LEVELONE_OPTIONS → the bus → the Recorder for kept contracts (D4) → the console
  reads each contract's top of book, Greeks and volume from its bus record
  (`stream_spine.streamed_record`: read on the first read after a message changes the record and
  held in it, `stream_spine.read_streamed`), never a copy → the `contract` and `chain` panels
  (`server.OPTION_PANELS`) and the levels (a reprice, below). A contract's streamed Greeks are one
  set, taken only while all six arrived in this hold (`option_contract.streamed_greek_set`,
  `capture.Daemon.option_record`). Enforced by: `tests/test_data_path_option_quote_time_v1.py`,
  `tests/test_data_path_rest_one_connection_v1.py`.
- **Options Book** (each contract's resting book and volume, their summary and the options lean).
  One expiry of the published chain with each contract's newest values (`push.chain.expiry_asked`,
  the chain screens' own), each contract's newest OPTIONS_BOOK (`order_flow.state.newest_book`) and
  the live price → the one producer, `calc.option_book` (a Calculator: each side's levels summed,
  the summary over the rows whose call and put both have a book, the lean; registered in
  `docs/derived_register.md`) → the `option_book` panel (`push.option_book.option_book`, every text
  formatted there), sent again on each quote or book of the ticker or its contracts
  (`server.FLOW_PANELS`, `server.OPTION_PANELS`) and each publication of its levels
  (`server.LEVELS_PANELS`). Its lifecycle owner is the order-flow state's books (State) and the
  levels producer's chain; when the OPTIONS_BOOK feed stops, the last books stand and the panel says
  NOT LIVE or OFFLINE with why and the oldest book's time; a contract with no book held is "-",
  never 0. Read by the Options Book subview at the selected expiry and the Trade Desk's Options
  Positioning card (its gauge) at the front one. Enforced by: `tests/test_option_book_v1.py`,
  `tests/e2e/console-options-book.spec.js`.
- **The option contracts streamed (the option rule).** `capture.Daemon.pick_options` orders what is
  asked on LEVELONE_OPTIONS and OPTIONS_BOOK: the Flow panel's contract, then every ticker's kept
  contracts, then every contract of the tickers a page shows, then every other ticker's; each
  ticker's chain in `capture.shown_first` order, dealt across tickers. No number of ours caps it:
  when Schwab refuses with its symbol limit (code 19), the order is cut at the limit it stated
  (`feed.connection.Connection.ask`). An expired contract is never streamed. A contract no longer
  held keeps its last quote, marked NOT STREAMED. Enforced by:
  `tests/test_option_contract_rule_v1.py`, `tests/test_data_path_one_watchlist_v1.py`,
  `tests/test_data_path_released_contract_v1.py`.
- **1-minute bars and price history.** CHART_EQUITY → the bus → the Recorder (`stream_bars_raw`) and
  the console's bar writer (`server._bar_writer`) → `state/bar_store.py`. The chain sweep asks
  `/pricehistory` for the 10 series of `chain_sweep.PRICE_HISTORY`, each when due
  (`ChainSweep.series_due`), before the chains → the bus (`pricehistory.<ticker>.<series>`) → the
  Recorder (`stream_pricehistory_raw`) and the bar writer. A bar is checked once
  (`server._schwab_bar`); no bar built from quotes enters the bar store. → the `bars`, `liquidity`
  and `desk` panels (`server.BARS_PANELS`). Enforced by: `tests/test_data_path_pricehistory_v1.py`,
  `tests/test_data_path_rules_v1.py::test_d5_a_start_asks_every_tickers_price_history_before_any_chain`.
- **The forming bar.** Each price row (the equity quote, above) → `calc.forming_bar.next_built`,
  called as the row is written (`live_market_plane.record_from_level_one_equity`), the plane holding
  each ticker's built minutes (`live_market_plane.built_minutes`, the newest `forming_bar.KEPT`) →
  the `forming` panel (`push.bars.forming`): each built minute Schwab has not sent its CHART_EQUITY
  bar for (a held minute as new or newer drops it), rolled up to the chart's timeframe with the
  minutes held in its bar (`push.bars.chart_bars`); the daily chart's is today's pushed candle. Its
  open, high, low and close move with each trade; its volume is not built ("-", no volume bar) until
  Schwab's CHART_EQUITY bar for the minute brings it (the operator's decision). Sent with each price
  row and each new bar, after `bars` (`server.PRICED_PANELS`, `server.BARS_PANELS`), for the ticker
  on screen only; the chart draws it over the newest bars (`ed-tv-chart.js` `forming`, Lightweight
  Charts `series.update`). Its lifecycle owner is the price row's writer: a feed that stops leaves
  the bar as it was, with its last trade's time; the program started within a minute builds none for
  it. Enforced by: `tests/test_forming_bar_v1.py`, `tests/e2e/console-forming-bar.spec.js`.
- **Price levels** (prior day, overnight, opening range, VWAP, value area). Producer
  `server._publish_price_levels`, from the bar store's bars after each bar, for the market's session
  (`time_et.market_session_date`) → `state/price_level_store.py` → the `levels` panel
  (`push.levels.levels_payload`) and the liquidity zones (`push.liquidity.liquidity_snapshot`). The
  `levels` panel and the liquidity zones are sent again with each price row
  (`server.PRICED_PANELS`), since each level's distance and each zone's side are from the live
  price. What the Trade Desk chart draws from them is served whole: the prior session's value area
  band (`prior_value_area`), the VWAP's words (`vwap_text`) and the volume profile's POC label
  (`volume_profile.poc_label`).
- **Option chain.** The chain sweep (`chain_sweep.ChainSweep`, on its own thread) asks each
  watchlist ticker's expiration chain once per ET date, then `/chains` per expiry (`range=ALL`),
  taking those answers again for `chain_sweep.CHAINS_AGAIN_SEC`; `/chains` and `/quotes` requests go
  `schwab_client.REQUESTS_AT_ONCE` together. A chain is asked while the option windows of Schwab's
  /markets answer are open (`ChainSweep.chain_due`), and once more after the close. The rotation is
  sorted, a ticker a page shows before each other one (`ChainSweep.rotation`). Greeks are never the
  chain's (Schwab rounds them): a streamed contract takes the stream's, every other one its
  `/quotes` answer, `schwab_client.QUOTES_BATCH_MAX` symbols a request (`ChainSweep.send_quotes`),
  each answer to the console at once (`order_flow.state.push_rest_quotes`). Each contract is read
  once (`option_contract.read_chain`, in `chain_sweep.chain_messages`) → the bus in parts of
  `chain_sweep.CHAIN_PART_CONTRACTS` → the console (`order_flow.streaming.assemble_chain_part`; a
  chain missing a part is never priced) → `server._on_chain` → the pricing thread. The first chain
  begun at or after a ticker's option close each day (`chain_sweep.capture_slot`) is the close
  capture: the Recorder commits it (`CaptureWriter.store_capture`) before the console hears of the
  chain, and it is never replaced. A non-200 answer fails that ticker's chain with its reason and
  the next request goes at once. Enforced by: `tests/test_chain_history_v1.py`,
  `tests/test_data_path_rest_one_connection_v1.py`, `tests/test_data_path_capture_whole_v1.py`,
  `tests/test_data_path_records_stand_v1.py`, `tests/test_canonical_gex_input_validity_v1.py`,
  `tests/test_capture_store_v1.py`, `tests/test_data_path_rules_v1.py`
  (`test_a_403_from_schwabs_edge_reaches_the_console_and_the_next_ticker_is_asked_at_once`).
- **Levels** (walls, flip, GEX, vanna, charm, max pain). One producer, `server._publish_levels`,
  called only on the pricing thread (`server._price_chain`): for each delivered chain, for a reprice
  at most once a second (`server.REPRICE_EVERY_SEC`) while a page shows the ticker and its quotes or
  contracts tick, and at startup from the newest stored captures (`state.capture_store`) →
  `state/level_store.py` → the panels of `server.LEVELS_PANELS`, marked changed by
  `server._levels_changed`. Streamed values are laid over the chain
  (`calc.math_exposure_core.overlay_streamed_contract_fields`). After the ticker's option close the
  chain is valued at that close (`time_et.valuation_instant`) and the close values stand until the
  next open. The verdict (`push.verdict.terrain_staleness`): LIVE, CLOSE, STALE past two of the
  sweep's rounds, or NOT LIVE, with the levels' time and age. Enforced by:
  `tests/test_instant_ui_blockers_a_v1.py`, `tests/test_one_levels_producer_v1.py`,
  `tests/test_data_path_silent_price_v1.py`, `tests/test_data_path_startup_v1.py`,
  `tests/test_data_path_confluence_v1.py`, `tests/test_rest_quotes_reach_the_levels_v1.py`,
  `tests/test_data_path_chain_spot_v1.py`, `tests/test_data_path_charm_side_unknown_v1.py`.
- **Price relations.** Each level's distance and side from the live price, the walls' state and the
  side of the flip are computed when served, at the live price
  (`calc.terrain_engine.price_relations`, `calc.terrain_read.level_side`), with the price's own mark
  (`push.spot.price_mark`). While a price is stopped, `server.refresh_not_live_pages` tells its
  pages to read again each minute so the age keeps counting. Enforced by:
  `tests/test_level_crosses_wire.py`, `tests/test_trade_desk_served_v1.py`.
- **Heatmap cells.** The `surface` panel (`push.surface.gamma_surface`): every listed strike a row,
  each cell the book's value for its strike and expiry; a cell with no value is None, drawn "-". Its
  streaming words come from `push.surface._stream_coverage`. Enforced by:
  `tests/test_data_path_heatmap_absent_v1.py`.
- **Strike windows.** Every per-strike panel shows the rows `calc.terrain_engine.strike_window`
  picks: Auto 11 strikes, Wider 23, All every one, centred on the strike nearest the live price or
  the strike the operator panned to; with neither, the middle of the chain, with the note
  `push.strike_rows.WINDOW_NO_PRICE`. The page sends the scope and pan and picks nothing.
- **Tape.** Each print is signed by Lee and Ready against the bid and ask its record held
  (`calc.l1_trade_observation.trade_sign`), marked estimated; an unsigned print is no value, with
  its share served beside each sum. The options tape (`push.tape.tape`) lists the newest trade first
  by Schwab's trade time. Enforced by: `tests/test_tape_lee_ready_v1.py`,
  `tests/test_options_flow_tape_v1.py`.
- **Level crosses.** On each streamed equity quote (`server._on_stream_tick`) the four levels of
  `server.CROSS_LEVELS` (gamma flip, call wall, put wall, largest gamma strike) are checked for a
  cross between the previous and the new price (`calc.terrain_read.crossed`). Each price's crosses
  are stored by the Recorder first (`server._log_level_crosses`, `CaptureWriter.store_crosses`,
  `level_crosses`); a cross the Recorder did not store is logged and not held. Held in
  `state/cross_store.py` and served by the `desk` panel (`push.desk.desk_events_payload`, window
  `push.desk.DESK_LOOKBACK`), which counts and words the chart's markers before the first bar of the
  span its chart asks (`markers_off_chart`, the `bars` panel's `push.bars.chart_bars`). Enforced by:
  `tests/test_level_crosses_wire.py`, `tests/test_trade_desk_served_v1.py`.
- **Market session.** The chain sweep asks `GET /markets` for today, the 7 days before it and each
  chain expiry date within a year (`ChainSweep.fetch_markets`) → the bus (`markets.<date>`) → the
  Recorder (`stream_markets_raw`) and `time_et.record_markets`. At startup the recorded answers are
  read once (`server._load_stored_sessions`). The session label rides each beat
  (`capture.Daemon.status`). Every session window and each contract's time to expiry
  (`time_et.time_to_expiry_years`, to the second) come from these answers; no session table is typed
  by hand. Enforced by: `tests/test_markets_sessions_v1.py`,
  `tests/test_data_path_stored_sessions_v1.py`.
- **Watchlist.** One list, the daemon's (`capture.Daemon.watchlist`), read at start from
  `stream_watchlist` (`capture.stored_watchlist`). An add or removal (`POST /api/watchlist`,
  `DELETE /api/watchlist/{ticker}`) goes to the daemon, which checks an added ticker with one
  `/quotes` request and answers with a `watchlist` record, stored by the Recorder. It takes effect
  at once on every stream service and REST request. The page draws the list each beat carries.

Not yet one State: the console part keeps its own parsed books and tape
(`order_flow.state.OrderFlowState`) beside the bus's records; the work is `ACTIVE_PROGRAM.md`
ENF-23.

## 4. Where each part runs

- **Feed:** the event loop reads Schwab's stream; the chain sweep runs on its own thread.
- **Calculators:** one pricing thread (`server.chain_pricing`), never the event loop, so the loop
  always reads Schwab's next frame: the levels, the heatmap's restamp
  (`server.restamp_off_the_loop`) and the option rule's order of a chain (`capture.shown_first`).
  Enforced by: `tests/test_stream_reader_keeps_up_v1.py`.
- **State and Push:** the event loop. Each panel's frame is built on a worker thread
  (`live_ui.LiveUiServer._frame`).
- **Recorder:** its own thread (`stream_spine.CaptureWriter`), so a slow disk never stalls the
  stream.

## 5. Checks

The tools that enforce the rules are in `AGENTS.md` rules 1 and 13 and "Rules and what enforces
them".

## 6. Operator decisions (enforced)

- **1. The daemon fetches the option chain.** Schwab's stream has no chain service; the contract
  list and open interest come only from REST. The daemon is the only Schwab client. Enforced by:
  `tests/test_schwab_client_import_boundary.py`.
- **3. The browser is never pushed a whole chain.** Enforced by: no machine check — ENF-16.
- **5. One database.** `ed.db` holds the stream's tables (D4), the chain history (decision 7) and
  the level crosses, with one writer, the Recorder. Enforced by: `tests/test_one_database_v1.py`;
  the console's read-only reads, `tests/test_level_crosses_wire.py`
  (`test_the_console_reads_the_crosses_and_a_write_through_it_fails`).
- **6. Before any table is dropped:** each table's size is measured read-only, dropping needs the
  operator's word, and VACUUM is an offline maintenance step. Enforced by:
  `tools/operator_law_guard.py` (`tests/test_protected_paths_v1.py`); starting `EdDB` drops nothing
  (`tests/test_data_path_tables_stand_v1.py`); any other table drop — ENF-16.
- **7. Chain history is kept for research.** Schwab keeps no past chains. One close capture a day
  per ticker (`chain_sweep.capture_slot`), every expiry, compressed, with each expiry's underlying
  price as sent and the chain's spot. Levels are not stored; research runs the one levels producer
  over the stored chains. Enforced by: `tests/test_chain_history_v1.py`.
- **8. A panel scales its bars to what is visible.** Fitting bar lengths to the visible window is
  drawing; the values drawn are the server's, unchanged. Enforced by: no machine check — ENF-16.
- **9. The trade side is estimated, and says so.** Schwab sends no aggressor side, so each print is
  signed by Lee and Ready and marked estimated (§3.4 Tape). Enforced by:
  `tests/test_tape_lee_ready_v1.py`.
- **10. Same-day levels, every ticker.** One producer, `calc.terrain_engine.same_day_levels`,
  defined in `docs/derived_register.md` "Same-day levels (0DTE)". Each level has one name, from
  `calc.terrain_engine.OPTION_LEVELS`, on every screen. The key levels rail draws the gamma flip,
  the call and put walls, the largest gamma strike, the delta walls and the charm walls, each
  regular and same-day, then the price levels of the `levels:kl` panel. Enforced by:
  `tests/test_data_path_same_day_levels_v1.py`, `tests/test_level_names_one_list_v1.py`,
  `tests/test_data_path_charm_side_unknown_v1.py`.
