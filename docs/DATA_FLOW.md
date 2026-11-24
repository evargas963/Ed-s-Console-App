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
  newer value replaces the older at once; nothing old waits in a queue. That is the rule of a topic
  whose messages are versions of one thing (`stream_spine.VERSIONED`: a symbol's quote or book, a
  ticker's chain, a series' candles, a date's sessions). A message that is its own item (a `/quotes`
  answer for its own contracts, one minute's bar, a news story, the answer to one watchlist request)
  is no newer value of the one before it: each live reader takes every one, once, in the order
  published, and none replaces another before it is taken. A quote's record keeps one thing more,
  the quote its newest quote replaced (`quote_before`, whole as the record held it): Schwab sends a
  trade with the quote that followed it, so the tape reads a trade against the quote in force when
  it was made (§3.4 Tape). Of a topic with versions only the Recorder takes every message, and while
  the database refuses writes it holds them (D4). Enforced by: `tests/test_data_path_rules_v1.py`;
  an item never replaced, `tests/test_stream_spine_v1.py`,
  `tests/test_rest_quotes_reach_the_levels_v1.py`, `tests/test_data_path_one_watchlist_v1.py` and
  `tests/test_data_path_header_news_v1.py`; the quote kept before, `tests/test_quote_in_force_v1.py`
  and `tests/test_stream_greeks_capture_v1.py`.
- **D4. The stream's tables in `ed.db` are the record.** One writer, `stream_spine.CaptureWriter`,
  records every bus message but option quotes and option books, which it records for the kept
  contracts only (`capture.Daemon.saves`): every contract of each ticker's soonest expiration whose
  time to expiry has not run out (`capture.saved_window`), and the Flow panel's contract. Those come
  first in the option rule's order, so each ticker's front expiry is streamed in full before the
  rest (`capture.Daemon.pick_options`). Quotes, option quotes, bars and news are kept whole; order
  books before the regular open plus 30 minutes and in the session's last 30 minutes
  (`stream_spine._book_kept`). After five sessions (`capture.SESSIONS_KEPT`,
  `capture.keep_sessions`) those rows move into `stream_archive` as compressed blocks
  (`stream_spine.ARCHIVED`, read back by `stream_spine.archived_rows`); the tables of
  `stream_spine.KEPT_BY_TIME` (price history, chain and quote answers, operational tables) drop rows
  older than five sessions. A row the database refuses, or a statement of the writer's own (a keep
  part, a spill's progress row) that fails for its own reason, is kept as sent with its error in
  `stream_write_failures` and the writer goes on: an error is every write's when its SQLite code is
  in `stream_spine.REFUSAL_CODES` (busy, locked, full, I/O, read-only and the like), else that row's
  or statement's alone (`stream_spine._its_own`). While the database refuses every write, the writer
  holds messages in memory up to `stream_spine.HOLD_CAP_BYTES`, then in spill files beside the
  database (`<stem>.<ms>.<n>.spill`), and writes them back in order, recording progress in
  `stream_spill_progress`; files a stop or crash left are written back at the next start. Its state
  (`stream_spine.WriterStatus`) rides the daemon's heartbeat to the header's Record cell: its one
  word, with the whole line as the title and, while it is not recording, on the alert line (§6,
  decision 11). Enforced by: `tests/test_data_path_stream_kept_v1.py`,
  `tests/test_data_path_rules_v1.py`, `tests/test_data_path_writer_failures_v1.py`.
- **D5. The last value stands, marked** (`AGENTS.md` rule 5). A value is LIVE while its feed
  delivers it and its market trades (`live_market_plane.live_state`): the daemon's heartbeat in
  force at the time judged (the latest stamped at or before it, `live_market_plane.feed_now`;
  `docs/SOURCES.md` as-of-join) is no older than `live_market_plane.FEED_HEARTBEAT_MAX_AGE_SEC`, the
  Schwab socket is open, the symbol is held on its service, and its market is in a window of
  Schwab's /markets answer (stocks: `time_et.session_label`, with the pre-market starting at the
  day's first streamed trade, `time_et.record_trade`; options: `time_et.options_open`). Otherwise
  the last value stands with its Schwab time and age, marked OFFLINE (the feed down) or NOT LIVE,
  and every value computed from it is marked too. The levels carry their own verdict (§3.4 Levels).
  A value never received, or sent invalid, shows "-". Calculations keep every digit; rounding is on
  screen only. Enforced by: `tests/test_data_path_rules_v1.py`, `tests/test_markets_sessions_v1.py`,
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
- Its memory is collected without a full collection during the session. A full collection stops
  every thread for as long as it takes to visit every long-lived object ("proportional to the total
  number of long-lived objects", `docs/SOURCES.md` cpython-gc-design), and the program replaces
  long-lived objects all session, which is what sets one off. Owner: the program's start
  (`capture.set_collector`, called by `capture.main` before anything large is held) sets Python's
  collector once, the oldest generation never reached (`capture.NO_FULL_COLLECTION`), the young and
  middle generations at Python's own thresholds, and its log line carries the thresholds read back;
  nothing changes them after. One full collection runs after each close of the last option market
  the program was running for (`capture.collect_after_close`, the task `collection`), and its log
  line says how long it took, how many objects it freed and how many it could not free. A close
  before the program's start, a day with no session and a stop have none: a new process holds
  nothing a session left, and a stopped one gives its memory back. When it fails: an unreachable
  reference cycle that reached the oldest generation holds its memory until that collection or the
  next start; the count in the log line is where it shows. Every Schwab REST answer is freed once
  read: httpx holds each answer in a cycle through its stream (`docs/SOURCES.md`
  httpx-bound-stream), which `schwab_client.log_request` replaces with the body it read. Enforced
  by: `tests/test_full_collection_after_close_v1.py`; the answers,
  `tests/test_data_path_rest_one_connection_v1.py`.
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
  (`order_flow.streaming._bus_loop`): each topic's current record as it changes, a chain in parts,
  and each message that is its own item (D3). A record that fails to apply is counted
  (`apply_failures` on the daemon's status beat, beside `tick_failures`) and logged with its
  traceback, and the next is applied. Enforced by: `tests/test_live_push_channel_v1.py`.
- **Console part → daemon part:** a call (`capture.Daemon.console_frame`): the Flow panel's contract
  and each watchlist add or removal, answered by the daemon's `watchlist` record.
- **Program → page:** `/ws` (`live_ui.page_socket`, `live_ui.LiveUiServer`): each symbol's price row
  on every change, every panel the page shows of its ticker (`server.PAGE_PANELS`) at once and again
  when its producer marks it changed (`live_ui.changed`), and the daemon's status every second
  (`live_ui.HEARTBEAT_SEC`), which carries the header's news line (`push.news.news`) on a page's
  first beat and on the first beat after the line changed or the Central day turned
  (`LiveUiServer.mark_news`). A client that stops reading is dropped (`live_ui.PageSocket`); the
  page reconnects. A frame, symbol or panel a page sends that the server cannot take is logged and
  counted (`page_refused`), and the beat carries the socket's counts (`page_socket`). The header
  shows these with the records not applied and the reprices failed, while any is above 0
  (`live_ui.left_out_line`, the beat's `left_out`). Enforced by:
  `tests/test_live_ui_daemon_to_browser_v1.py`, `tests/test_data_path_silent_price_v1.py`,
  `tests/e2e/console-sign-in.spec.js`.
- **Page → program:** HTTP for the page itself, `/api/health`, `/api/build`, `/api/watchlist` (POST,
  DELETE) and `/api/flow-contract`.

### 3.3 Where data lives

- **Daemon memory:** the bus's current records and each ticker's newest whole chain; the watchlist
  (`capture.Daemon.watchlist`); the option rule's order and the Flow panel's contract; each
  service's symbol limit as Schwab last stated it (`feed.connection.Connection.limit`); the price
  rows (`live_market_plane`); the header's news line, the newest `news_store.STORIES_HELD` stories
  (`state/news_store.py`).
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
  (`live_price_rows.price_row`) → `/ws` → header, watchlist and every price the pages show (the one
  producer of the live price on screen: `EdShell.paintLivePrice`, the Confluence matrix's price line
  among them), and every panel's calculations from the live price (`push.spot.resolve_spot`); (c)
  the console's intake → the tape and the level-cross check. The last trade's price, size and time
  have one reader, `calc.l1_trade_observation.last_print`. Every page asks for the market context's
  rows with its own ticker's (`live_push.MARKET_CONTEXT`): the header's second row draws all three
  on every page, the volatility index (`live_push.VOLATILITY_INDEX`) first, and the Trade Desk's
  Desk page draws the same rows (§6, decision 11). Enforced by:
  `tests/test_last_print_one_reader_v1.py`, `tests/test_data_path_quote_time_v1.py`,
  `tests/e2e/console-header.spec.js`.
- **Order book.** NYSE_BOOK, NASDAQ_BOOK and OPTIONS_BOOK → the bus → the Recorder,
  `stream_book_raw` (D4) → the console (`order_flow.state.OrderFlowState`, one book per service,
  never combined) → the `book` and `book_heatmap` panels (`push.book.book`, `push/book_heatmap.py`),
  sent again on each book (`server.FLOW_PANELS`). The Liquidity card's order-imbalance readout of
  both books and their aggregate is computed once per book (`calc.order_flow.book_readout`) and kept
  a second at a time (`order_flow.history.LEAN`): (bid − ask) / (bid + ask) over the shares Schwab
  sent at the best 1, 3 and 5 levels, Top 5 the screen's default. A side Schwab sent with no levels
  is empty, never an older book's. Enforced by: `tests/test_data_path_book_time_v1.py`,
  `tests/test_data_path_book_size_v1.py`.
- **Option quote.** LEVELONE_OPTIONS → the bus → the Recorder for kept contracts (D4) → the console
  reads each contract's top of book, Greeks and volume from its bus record
  (`stream_spine.streamed_record`: read on the first read after a message changes the record and
  held in it, `stream_spine.read_streamed`), never a copy → the `contract` and `chain` panels
  (`server.OPTION_PANELS`) and the levels (a reprice, below). A contract's streamed Greeks are one
  set, taken only while all six arrived in this hold (`option_contract.streamed_greek_set`,
  `capture.Daemon.option_record`). Enforced by: `tests/test_data_path_option_quote_time_v1.py`,
  `tests/test_data_path_rest_one_connection_v1.py`.
- **Options Level II** (each contract's resting book and volume, their summary and the options
  lean). One expiry of the published chain with each contract's newest values
  (`push.chain.expiry_asked`, the chain screens' own), each contract's newest OPTIONS_BOOK
  (`order_flow.state.newest_book`) and the live price → the one producer, `calc.option_book` (a
  Calculator: each side's levels summed, the summary over the rows whose call and put both have a
  book, the lean; registered in `docs/derived_register.md`) → the `option_book` panel
  (`push.option_book.option_book`, every text formatted there), sent again on each quote or book of
  the ticker or its contracts (`server.FLOW_PANELS`, `server.OPTION_PANELS`) and each publication of
  its levels (`server.LEVELS_PANELS`). Its lifecycle owner is the order-flow state's books (State)
  and the levels producer's chain; when the OPTIONS_BOOK feed stops, the last books stand and the
  panel says NOT LIVE or OFFLINE with why and the oldest book's time; a contract with no book held
  is "-", never 0. The rows' volumes and their listing are the chain's, so the panel carries the
  levels' verdict and the subview shows it beside the books' own state: a chain no longer delivered
  stands, marked STALE with its time, its age and why. With no live price the window is the chain's
  middle strikes and the subview says so. Read by the Options Level II subview at the selected
  expiry and the Trade Desk's Options Positioning card (its gauge) at the front one. Enforced by:
  `tests/test_option_book_v1.py`, `tests/e2e/console-options-book.spec.js`.
- **The option contracts streamed (the option rule).** `capture.Daemon.pick_options` orders what is
  asked on LEVELONE_OPTIONS and OPTIONS_BOOK: the Flow panel's contract, then every ticker's kept
  contracts, then every contract of the tickers a page shows, then every other ticker's; each
  ticker's chain in `capture.shown_first` order, dealt across tickers. No number of ours caps it:
  when Schwab refuses with its symbol limit (code 19), the order is cut at the limit it stated
  (`feed.connection.Connection.ask`). An expired contract is never streamed. A contract no longer
  held keeps its last quote, marked NOT STREAMED. Its lifecycle owner is the daemon's market
  follower (`capture.Daemon.follow_market`): each chain the sweep delivers is laid out and ordered
  as it arrives, or at its ticker's first price, on the ordering thread (§4), behind no pricing.
  While a chain waits its turn there, or its ticker has no price, the contracts held stand; a
  follower that ends ends the program with an error naming it (`capture.run`). Enforced by:
  `tests/test_option_contract_rule_v1.py`, `tests/test_data_path_one_watchlist_v1.py`,
  `tests/test_data_path_released_contract_v1.py`.
- **Schwab's symbol limit on a service.** Schwab states it in the message of a refusal (code 19:
  "(LEVELONE_OPTIONS=3000, DISCARDED=1362)"; `docs/SOURCES.md`, `schwab-symbol-limit-recorded`),
  read once by `feed.connection.stated_limit` (a `SymbolLimit`). It is the service's, not the
  connection's, and it stands until Schwab states another, so a request past a limit Schwab has
  stated is not sent again: the connection that hears it holds it (`Connection.limit`) and keeps it
  when it reconnects, and a start reads each service's newest statement from the record of Schwab's
  answers (`capture.stored_limits`, from `stream_subscriptions`, once, before the connection is
  built). A service Schwab has stated no limit for, in the rows the record keeps (D4), is asked for
  the whole order once and Schwab states it; a refusal that states another number replaces the one
  held, and one that states none changes nothing. No number of ours is typed anywhere. Its lifecycle
  owner is the connection: a read of the record that fails ends the start with its error
  (`capture.run`). Enforced by: `tests/test_option_contract_rule_v1.py` (a new connection and a
  restart ask within it, and hold the same contracts as a start that knew none),
  `tests/test_stream_limit_remembered_v1.py` (Schwab's recorded answers, and the record's read).
- **1-minute bars and price history.** CHART_EQUITY → the bus → the Recorder (`stream_bars_raw`) and
  the console's bar writer (`server._bar_writer`) → `state/bar_store.py`. The chain sweep asks
  `/pricehistory` for the 10 series of `chain_sweep.PRICE_HISTORY`, each when due
  (`ChainSweep.series_due`), before the chains, ticker by ticker, a ticker a page shows before each
  other one (`ChainSweep.candles`, which reads the pages' tickers before each ticker's history, so
  one selected while the round is asked has its own next) → the bus
  (`pricehistory.<ticker>.<series>`) → the Recorder (`stream_pricehistory_raw`) and the bar writer.
  A bar is checked once (`server._schwab_bar`); no bar built from quotes enters the bar store. → the
  `bars`, `liquidity` and `desk` panels (`server.BARS_PANELS`). Enforced by:
  `tests/test_data_path_pricehistory_v1.py`,
  `tests/test_data_path_rules_v1.py::test_d5_a_start_asks_every_tickers_price_history_before_any_chain`,
  `tests/test_data_path_rules_v1.py::test_d5_a_ticker_selected_while_the_price_history_is_asked_has_its_own_next`.
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
- **Reference levels** (prior day, extended hours, opening range, VWAP, value area). Producer
  `server._publish_price_levels`, from the bar store's bars after each bar, for the market's session
  (`time_et.market_session_date`), reading every bar from the prior session's regular open as
  Schwab's /markets sent it (`calc.liquidity_value_engine.levels_start`; a prior session whose bars
  do not cover that window is disclosed as partial) → `state/price_level_store.py` → the `levels`
  panel (`push.levels.levels_payload`) and the liquidity zones
  (`push.liquidity.liquidity_snapshot`). The `levels` panel and the liquidity zones are sent again
  with each price row (`server.PRICED_PANELS`), since each level's distance and each zone's side are
  from the live price. What the Trade Desk chart draws from them is served whole: the prior
  session's value area band (`prior_value_area`), the VWAP's words (`vwap_text`) and the volume
  profile's POC label (`volume_profile.poc_label`). Both panels serve the snapshot's time and age
  with its levels (`push.levels.snapshot_stamp`), and every screen that draws them shows both: the
  Levels view in its two homes, Key Levels' reference levels, the zones chart, Right Now's Frame and
  the Desk's LEVELS pill. Enforced by: `tests/test_e2e_panels_two_day_v1.py`,
  `tests/test_data_path_snapshot_time_v1.py`, `tests/e2e/console-gamma-levels.spec.js`,
  `tests/e2e/console-gamma-heatmap.spec.js`, `tests/e2e/console-trade-desk.spec.js`.
- **Option chain.** The chain sweep (`chain_sweep.ChainSweep`, on its own thread) asks each
  watchlist ticker's expiration chain once per ET date, then `/chains` per expiry (`range=ALL`) once
  in an option window Schwab sends (its pre-market, then its regular session:
  `time_et.option_window_began`) and once more after the ticker's option close, every other chain
  taking those answers again (`ChainSweep.fetch_chain`): the contract list, terms and open interest
  change once a day. `schwab_client.REQUESTS_AT_ONCE` of its `/chains` and `/quotes` requests are
  with Schwab at a time, the next sent as an answer is taken (`ChainSweep.send_quotes`), and a
  request answered 429 is sent again at once, then after 1 and 2 seconds
  (`chain_sweep.REFUSED_WAITS_SEC`), keeping its place meanwhile, so the rate falls to what Schwab
  takes (`chain_sweep.asked_again_if_refused`). A chain is asked while the option windows of
  Schwab's /markets answer are open (`ChainSweep.chain_due`), and once more after the close. The
  rotation is sorted, a ticker a page shows before each other one (`ChainSweep.rotation`). Greeks
  are never the chain's (Schwab rounds them): a streamed contract takes the stream's, every other
  one its `/quotes` answer, `schwab_client.QUOTES_BATCH_MAX` symbols a request
  (`ChainSweep.send_quotes`), each answer to the console at once
  (`order_flow.state.push_rest_quotes`): every answer, since each carries its own contracts (D3),
  and a contract keeps the answer received last. Each contract is read once
  (`option_contract.read_chain`, in `chain_sweep.chain_messages`) → the bus in parts of
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
  sweep's rounds, or NOT LIVE, with the levels' time and age. Each panel that serves the levels'
  values serves that verdict with them and its screen shows it as its badge: Key Levels, the
  heatmap, GEX by strike, Vanna and Charm by strike, the Chain, Strike Detail, Contract
  Specifications, Options Level II, the Levels view in its two homes, the zones chart (its zones
  hold the option levels) and Right Now's Frame, Confirm and migration
  (`tests/test_vanna_charm_by_strike_v1.py`, `tests/test_option_book_v1.py`,
  `tests/test_e2e_panels_two_day_v1.py`, `tests/e2e/console-options-vanna-charm.spec.js`,
  `tests/e2e/console-options-book.spec.js`, `tests/e2e/console-gamma-heatmap.spec.js`,
  `tests/e2e/console-gamma-levels.spec.js`, `tests/e2e/console-trade-desk.spec.js`). Enforced by:
  `tests/test_instant_ui_blockers_a_v1.py`, `tests/test_one_levels_producer_v1.py`,
  `tests/test_data_path_silent_price_v1.py`, `tests/test_data_path_startup_v1.py`,
  `tests/test_data_path_confluence_v1.py`, `tests/test_rest_quotes_reach_the_levels_v1.py`,
  `tests/test_data_path_chain_spot_v1.py`, `tests/test_data_path_charm_side_unknown_v1.py`.
- **Served words.** A state the program serves is served with the words the screen shows for it,
  from one table where the frame is built: the regime (`regime_text`:
  `calc.terrain_read.REGIME_TEXT`), the price's side of the flip (`flip_relation_text`), a level
  move's level and where the busiest strikes sit against the walls (`level_text`,
  `busiest_vs_walls_text`: `push.strikes`), where a tape print landed (`classification_text`:
  `history.LANDED_TEXT`), a chain answer's scope (`scope.kind_text`: `push.chain.SCOPE_TEXT`), a
  venue of the Liquidity card (`name`: `push.book.VENUE_NAMES`), the value area's and the VWAP's
  relations (`value_state_text`, `vwap_relation_text`: `push.liquidity`), a contract's side
  (`put_call_text`: `push.contract.SIDE_TEXT`), the option stream's badge for a contract
  (`subscription_text`, with `subscription_active` for its tone:
  `app.options.order_flow.streaming`), a tilt as running text says it (`tilt_text`, beside the
  headline's `side_word`: `calc.order_flow.TILT_WORDS`), and a zone list that lists none
  (`no_zones_text`: `push.liquidity.NO_ZONES_TEXT`). A choice of what a screen draws is served the
  same way: each level says whether the zones chart draws it as a reference line (`reference_line`:
  `push.levels.REFERENCE_LINE_FAMILIES`). The page draws them and holds no table from a served state
  to words; a table from a state to a colour, a tone or an arrow is drawing and stays on the page.
  Enforced by: `tests/test_positioning_migration_v1.py`, `tests/test_options_flow_tape_v1.py`,
  `tests/test_chain_api_v1.py`, `tests/test_liquidity_readout_v1.py`,
  `tests/test_one_levels_producer_v1.py`, `tests/test_trade_desk_served_v1.py`,
  `tests/test_data_path_liquidity_zero_v1.py`, `tests/test_options_order_flow_api_v1.py`,
  `tests/test_options_order_flow_production_v1.py`,
  `tests/test_data_path_silent_subscription_v1.py`,
  `tests/test_liquidity_snapshot_spot_identity_v1.py`, `tests/test_e2e_panels_two_day_v1.py`,
  `tests/e2e/console-trade-desk.spec.js`, `tests/e2e/console-options-flow-tape.spec.js`,
  `tests/e2e/console-gamma-asof.spec.js`, `tests/e2e/console-liquidity-card.spec.js`,
  `tests/e2e/console-gamma-heatmap.spec.js`, `tests/e2e/console-confluence.spec.js`,
  `tests/e2e/console-gamma-flow.spec.js`; that no page script holds such a table: no machine check,
  ENF-12.
- **Price relations.** Each level's distance and side from the live price, the walls' state and the
  side of the flip are computed when served, at the live price
  (`calc.terrain_engine.price_relations`, `calc.terrain_read.level_side`). The price itself, its
  trade time and whether it is live have one producer, the price row (`live_price_rows.price_row`):
  no panel serves a copy of them, and the page draws them, and the mark beside every value computed
  from the price, from that row alone (`EdShell.paintLivePrice`, `EdShell.livePriceMark`), its age
  counting with each beat. While the published levels are not live, `server.refresh_not_live_pages`
  tells their pages to read them again each minute so their age keeps counting. Enforced by:
  `tests/test_level_crosses_wire.py`, `tests/test_trade_desk_served_v1.py`,
  `tests/test_page_one_faucet_v1.py`, `tests/e2e/console-confluence.spec.js`,
  `tests/e2e/console-gamma-levels.spec.js`.
- **Heatmap cells.** The `surface` panel (`push.surface.gamma_surface`): every listed strike a row,
  each cell the book's value for its strike and expiry; a cell with no value is None, drawn "-". Its
  streaming words come from `push.surface._stream_coverage`. Enforced by:
  `tests/test_data_path_heatmap_absent_v1.py`.
- **Strike windows.** Every per-strike panel shows the rows `calc.terrain_engine.strike_window`
  picks: Auto 11 strikes, Wider 23, All every one, centred on the strike nearest the live price or
  the strike the operator panned to; with neither, the middle of the chain, with the note
  `push.strike_rows.WINDOW_NO_PRICE`. The page sends the scope and pan and picks nothing: the scope,
  the centre (a strike, or null to follow the price) and the shift with every window
  (`EdShell.windowParams`). A request that names no centre is answered with why, never read as one
  that follows the price (`push.strike_rows.window_asked`). Enforced by:
  `tests/test_vanna_charm_by_strike_v1.py`, `tests/test_option_book_v1.py`.
- **One expiry choice.** The strike views follow the expiry the operator picks in the one expiry
  dropdown (`state.expiryFilter`, sent as `expiry` by `EdShell.windowAtExpiry`), shown on the
  Options and the Trade Desk bars: the heatmap, GEX by Strike, the Chart's GEX, DEX and OI profiles,
  Vanna and Charm by strike, Right Now's migration, and Options Level II and the Desk map's options
  lean (an expiry each, so none chosen is the front one, as on the chain screens:
  `push.chain.expiry_asked`), and the Confluence matrix (one expiry ranked by its days to
  expiration, so none chosen is the front one still open: `push.confluence.confluence_payload`). A
  listed expiry's rows are its contracts alone, by Schwab's expirationDate
  (`calc.terrain_engine.per_strike_view`'s `by_expiry`, one pricing pass with the whole book, its
  charm the expiry's own charm map); All Expirations (null) is the whole book; an expiry the chain
  does not list is answered with why, never another expiry's rows (`push.strike_rows.rows_of`). One
  rule reads the expiry a request asks for, for every panel that takes one
  (`push.strike_rows.expiry_unreadable`): a request that names no expiry is answered with why, never
  read as one whose expiry is null. The migration compares the same expiry on the prior day; where
  that day did not list it, no strike is compared and the migration says why. No fixed DTE bucket of
  ours stands in for the choice. The walls, the flip and their moves since the prior close stay the
  whole book's: they are defined over every contract, and Key Levels says all-exp beside a chosen
  expiry. Enforced by: `tests/test_strikes_follow_the_expiry_v1.py`,
  `tests/test_vanna_charm_by_strike_v1.py`, `tests/test_data_path_confluence_v1.py`,
  `tests/e2e/console-gamma-heatmap.spec.js`, `tests/e2e/console-trade-desk.spec.js`,
  `tests/e2e/console-options-vanna-charm.spec.js`, `tests/e2e/console-confluence.spec.js`.
- **The Confluence matrix's levels and distances.** The matrix marks only the key levels
  (`push.confluence.KEY_OPTION_LEVELS`, `KEY_SAME_DAY_LEVELS`, `KEY_SESSION_LEVELS`, defined in
  `docs/derived_register.md` "Confluence key levels"): Gamma Flip, Gamma Call, Gamma Put, Gamma
  Total and OI Pin from the published levels, their same-day copies only when the chosen expiry
  settles that day, and VWAP and the prior close from the session's price levels; each inside the
  strikes shown a tag on the row of the strike nearest its price, its own price on it and its hold
  rate on hover, the rest listed above or below. Each strike and each level carries its distance
  from the live price in points and in the expiry's implied moves (σ), one producer
  (`calc.confluence_composite.distance`). Enforced by: `tests/test_matrix_key_levels_v1.py`,
  `tests/test_data_path_confluence_v1.py`, `tests/e2e/console-confluence.spec.js`.
- **The Confluence matrix's readings.** One expiry's strikes, read left to right by importance
  (matrix decisions 59 to 64): the Composite (`calc.confluence_composite.composite`: the sign of the
  expiry's gamma if the price were at the strike, `calc.math_levels.expiry_gamma`, for the shown
  expiry alone at the levels' valuation instant, and the equal vote of the families measured there);
  the price and levels; the gamma there and today's hits (`calc.liquidity_value_engine.visits`); the
  positions (net GEX, open interest, its change since the prior day's capture, DEX); charm, vanna
  and volatility; and the look-back's volume, volatility change, bought less sold and hedging flow
  (`calc.option_window`). The headline is the kind of move the whole book's gamma at the price
  makes, with each family's vote (`calc.confluence_composite.family_votes`), every reading untested.
  Enforced by: `tests/test_data_path_confluence_v1.py`, `tests/test_matrix_look_back_v1.py`,
  `tests/e2e/console-confluence.spec.js`.
- **The option look-back record.** LEVELONE_OPTIONS → the bus → the console's intake →
  `OrderFlowState._take_record`: for each contract, at the first message of each minute, its volume,
  volatility and running totals of bought, sold, unknown and hedging flow in force before it (each
  rise of TOTAL_VOLUME one step, read by its last trade against the quote in force,
  `calc.option_window.step_totals`). Its lifecycle owner is the order-flow state: a record begins at
  a contract's first message of the ET day, takes every message after it, and is begun again on the
  next day and when the program starts, so a window reaching before that is "-", never a part. A
  reconnect of Schwab's stream keeps it: Schwab's counts run on, so the window's volume stays exact,
  and the gap's trades arrive as one rise of volume, read by its last trade as any rise Schwab
  merges is (on the day it was measured, 2026-11-23, 63% of the first hour's volume came in rises
  larger than their last trade). When the stream stops, the newest values stand and the header says
  OFFLINE. Read by the matrix (`push.confluence._looks`) over the look-back the page picks. Enforced
  by: `tests/test_matrix_look_back_v1.py`.
- **Tape.** A print is a record whose last trade (time, price, size) differs from the print kept
  before it (derived register, "A print on the tape"). Each print is kept with the quote in force
  when it traded (`calc.l1_trade_observation.quote_in_force`, taken once, in
  `state.OrderFlowState.push_level_one`): the newest bid and ask Schwab timed (QUOTE_TIME_MILLIS) at
  or before the trade (TRADE_TIME_MILLIS) and on its ET date. Schwab's update carries a trade with
  the quote that followed it ("quotes may be recorded ahead of trades that triggered them", Lee and
  Ready 1991), so that quote is the update's own only when Schwab timed it no later than the trade;
  otherwise it is the quote the update replaced, which the bus keeps (D3). A quote of an earlier ET
  date is not in force: the market closed between them (no window Schwab's /markets sends crosses
  midnight ET). A print with no such quote has no bid and ask: where it landed is unknown and it is
  unsigned, never read against a later quote. Each print is signed by Lee and Ready against that bid
  and ask (`calc.l1_trade_observation.trade_sign`), marked estimated; an unsigned print is no value,
  with its share served beside each sum. The options tape (`push.tape.tape`) lists the newest trade
  first by Schwab's trade time, each with that bid and ask and where its price landed against them.
  Enforced by: `tests/test_tape_lee_ready_v1.py`, `tests/test_options_flow_tape_v1.py`,
  `tests/test_quote_in_force_v1.py`, `tests/test_l1_trade_observation_v1.py`.
- **Level crosses.** On each streamed equity quote (`server._on_stream_tick`) the four levels of
  `server.CROSS_LEVELS` (Gamma Flip, Gamma Call, Gamma Put and Gamma Total) are checked for a cross
  between the previous and the new price (`calc.terrain_read.crossed`). Each price's crosses are
  stored by the Recorder first (`server._log_level_crosses`, `CaptureWriter.store_crosses`,
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
  by hand. Each option market's day is its regular and post-market windows, joined
  (`time_et.Session.options`): on a full day both end at 16:15 ET, the close Schwab's own Greeks run
  to, and there an expiring contract's time to expiry runs out (`time_et.settles_at`; Schwab's
  `expirationDate` says 16:00) and it stops being streamed and recorded (`capture.shown_first`,
  `capture.saved_window`). Enforced by: `tests/test_markets_sessions_v1.py`,
  `tests/test_data_path_stored_sessions_v1.py`, `tests/test_option_contract_rule_v1.py`.
- **News.** NEWS_HEADLINE, asked for every watchlist ticker and the market context's symbols
  (`capture.MARKET_CONTEXT_SERVICES`). Feed reads each item's numbered fields once, where it arrives
  (`feed.connection.news_headline`, their one reader: no Schwab document lists them,
  `docs/SOURCES.md`, `schwab-news-headline-recorded`), into a typed record
  (`state.news_store.NewsHeadline`: the story's time, the headline id, the status, the headline, the
  source and the language, each as sent, None where Schwab sent none) → the bus (`news.<symbol>`:
  Schwab's item verbatim, and that record beside it) → (a) the Recorder, `stream_news_raw`, every
  message as sent; (b) the daemon's follower (`capture.Daemon._took_news`), which the bus hands
  every message, once, in the order published (a story is its own item, D3) →
  `state.news_store.take`, which takes the record. A story is held once, by its headline id, with
  the wording of its newest message by Schwab's frame time (D1) and every symbol it was sent under;
  a message Schwab marks withdrawn (status D) removes its story; a message in another language than
  English, by Schwab's own language field, is counted and left out, and so is one with no headline,
  id or time; the newest `news_store.STORIES_HELD` by each story's own time are held →
  `push.news.news` (each story's time, symbols, headline and source as texts, and the count left
  out) → the beat (§3.2) → the header's second row on every page, a ticker chosen or not (§6,
  decision 11). Its lifecycle owner is the daemon's market follower
  (`capture.Daemon.follow_market`): a follower that ends ends the program with an error naming it
  (`capture.run`). The store is empty at each start and the line reads "-" until Schwab sends a
  headline; Schwab sends its recent stories again when the stream reconnects, and one already held
  changes nothing. When NEWS_HEADLINE stops, the stories held stand, each with its own time. Nothing
  reads the database. Registered in `docs/derived_register.md` "The header's news line". Enforced
  by: `tests/test_data_path_header_news_v1.py`, `tests/e2e/console-header.spec.js`.
- **Watchlist.** One list, the daemon's (`capture.Daemon.watchlist`), read at start from
  `stream_watchlist` (`capture.stored_watchlist`). An add or removal (`POST /api/watchlist`,
  `DELETE /api/watchlist/{ticker}`) goes to the daemon, which checks an added ticker with one
  `/quotes` request and answers each request with a `watchlist` record of its own (D3), stored by
  the Recorder. It takes effect at once on every stream service and REST request. The page draws the
  list each beat carries.

Not yet one State: the console part keeps its own parsed books and tape
(`order_flow.state.OrderFlowState`) beside the bus's records; the work is `ACTIVE_PROGRAM.md`
ENF-23.

## 4. Where each part runs

- **Feed:** the event loop reads Schwab's stream; the chain sweep runs on its own thread.
- **Calculators:** never the event loop, so the loop always reads Schwab's next frame. One pricing
  thread (`server.chain_pricing`): the levels and the heatmap's restamp
  (`server.restamp_off_the_loop`). One ordering thread (`capture.chain_ordering`): a chain's layout
  and its order for the option rule (`capture.strike_ladders`, `capture.shown_first`), one chain at
  a time in the order asked, so Schwab is asked for a chain's contracts behind no pricing and a
  ticker's newest chain is ordered last. Enforced by: `tests/test_stream_reader_keeps_up_v1.py`,
  `tests/test_option_contract_rule_v1.py`.
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
  signed by Lee and Ready against the bid and ask in force when it traded, never a later quote, and
  marked estimated (§3.4 Tape). Enforced by: `tests/test_tape_lee_ready_v1.py`,
  `tests/test_quote_in_force_v1.py`.
- **10. Same-day levels, every ticker.** One producer, `calc.terrain_engine.same_day_levels`,
  defined in `docs/derived_register.md` "Same-day levels (0DTE)". Each level has one name, from
  `calc.terrain_engine.OPTION_LEVELS`, on every screen. The key levels rail draws Gamma Flip, Gamma
  Call, Gamma Put, Gamma Total, Delta Call, Delta Put, Charm Call and Charm Put, each regular and
  same-day, then the price levels of the `levels:kl` panel. Enforced by:
  `tests/test_data_path_same_day_levels_v1.py`, `tests/test_level_names_one_list_v1.py`,
  `tests/test_data_path_charm_side_unknown_v1.py`. A move of Gamma Total (the largest total gamma
  strike), in either column, is announced on the Gamma page: the producer compares each
  publication's two strikes with the last known (`calc.terrain_engine.total_gamma_record`, in
  `server._publish_levels`, the levels' one lifecycle owner), the newest move is held with the
  levels (`PublishedLevels.total_gamma`) and served on the terrain panel in words
  (`push.terrain.total_gamma_text`), and the page shows it as a toast with a chime
  (`static/js/ed-core.js` `toast`), once per move it sees arrive; a ticker's first levels on the
  page, and the first levels after a start, announce nothing. A column not known keeps the strike
  last known. If the producer stops, no move is served and none shown. Enforced by:
  `tests/test_total_gamma_move_v1.py`, `tests/e2e/console-gamma-heatmap.spec.js`.
- **11. One header, the same on every page, in two rows.** The page has one header, drawn by the
  shell alone (`static/js/ed-core.js`); no style or script changes it by workspace or view, and each
  value in it is drawn from its one served producer. Row 1, the instrument and the system: the
  selected ticker's price row (`live_price_rows.price_row`), its last trade's time and age in the
  stale colour while the row is not live; then the program's beat (`capture.Daemon.status`, sent by
  `live_ui.LiveUiServer.beat`): the feed, the recorder and the Schwab sign-in, each a dot and the
  program's one word for it (the row's `feed_label`, `stream_spine.WriterStatus` `word`,
  `capture.sign_in_line` `word`) with its whole line as the title, the page never cutting a served
  sentence into a word; what the program left out, shown only while the beat serves it
  (`live_ui.left_out_line`); the session; and the clock to the second (`time_et.ct_time`;
  `time_et.ct_clock`, to the millisecond, is the logs'). Row 2, the market and the line: the market
  context's three price rows (`live_push.MARKET_CONTEXT`, the rows the Desk draws too), the
  volatility index first (`live_push.VOLATILITY_INDEX`), each its served display name, price and
  percent change, and, not live, its value dimmed with its trade time and age beside it and why as
  its title. How a row reads is decided once, in the shell (`static/js/ed-core.js` `paintMarket`),
  and the Desk's two drawings of the same rows, its Volatility card and its foot strip, are told
  (`ed:market_row`) and mark a stopped index the same way, with the served word (`feed_label`)
  before its trade time and age and why as the title. Then the news line (§3.4 News): each story's
  time, symbols, headline and source as served, newest first, the count left out its label's title.
  A line longer than its room runs at a constant speed the drawing module sets from its width
  (`static/js/ed-draw.js` `tapeSeconds`), rests under the pointer, stands still when the system asks
  for reduced motion and starts again from the newest when a story arrives; no timer of the page
  moves it. The alert line takes the news' place while something is wrong, each sentence the
  program's own, in this order: Schwab's connection (the beat's `schwab_down`), the recorder's whole
  line while its class is "neg", the sign-in's line and Schwab's reason while it is refused, and
  what was left out where its cell has no room for the sentence, which draws its dot alone there,
  never a part of a count. While the push itself is silent the page says so on that line in its own
  words, the feed word reads OFFLINE, every time stands with no age (D5) and the Desk's index rows
  are marked OFFLINE. A value not yet received reads "-". The header is 82 pixels high
  (`--ed-header-h`); nothing in it wraps or leaves it at the window widths the browser tests use,
  and a window under 1,500 pixels wide draws the search box as its icon, which opens while it holds
  the focus. Its layout is fitted to the console's own faces (`--ed-faces`); a machine with none of
  them draws the header in a wide system face scaled to their width (`static/index.html`,
  `Ed Header Fallback`), and the layout holds in both. Under it, at a 1920×950 window, the Trade
  Desk's Desk page does not scroll, with every line of its Liquidity card drawn and with the market
  context's rows arriving, live or stopped: its price chart's floor is 356 pixels, and 380 in a
  window 1,400 pixels wide or narrower, which wraps the chart's toolbar and legend
  (`static/css/ed-trade-desk.css` `.tdm`). Enforced by: `tests/e2e/console-header.spec.js`,
  `tests/e2e/console-sign-in.spec.js`, `tests/e2e/console-trade-desk.spec.js`,
  `tests/e2e/console-liquidity-card.spec.js`, `tests/test_data_path_header_volatility_v1.py`,
  `tests/test_data_path_header_news_v1.py`, `tests/test_data_path_sign_in_v1.py`,
  `tests/test_live_ui_daemon_to_browser_v1.py`.
