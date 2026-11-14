# Ed Console — Data Flow

How data moves from Schwab to the screen: the design (§1), the rules for the data (§2), today's
code (§3, being replaced step by step), and the journey of each kind of data. The operator's
decisions are in §6. Where the code lives is `docs/ARCHITECTURE.md`. Every change is built to this
document and checked against it; a change that does not fit stops and goes to the operator.

## 1. The design (operator 2026-10-29)

```
[Schwab] ─ stream + REST ─► [ one program:  Feed ─► State ─► Calculators ─► State ─► Push ] ─ one WebSocket ─► [page]
                                                      │
                                                      └─► Recorder ─► [databases: history]
```

One program in five parts (`AGENTS.md` "The shape"): **Feed** talks to Schwab and takes each field
as sent; **State** holds the newest value of everything with its time; **Calculators** compute each
derived value once, as pure functions; **Push** sends the page a snapshot, then every change, on one
WebSocket, and the page draws it; **Recorder** writes every message to the databases, which no live
screen reads. Hops: Schwab → program → page.

Today the program is one process with two parts (the capture daemon and the console, §3.1) on one
port, and the page re-reads routes after each push (§3.2). `ACTIVE_PROGRAM.md` SHAPE step 3 makes
them one program and step 4 makes the push the page's only data; each step rewrites the sections
of §3 it replaces, in the same PR.

The facts below hold today and in the design, except where a bullet says what today lacks:

- One Schwab connection, owned by Feed (today the daemon; Schwab allows one streamer connection per user).
  Enforced by: `tests/test_schwab_client_import_boundary.py` (the console makes no Schwab call).
- One owner of the Schwab token while the app runs: the daemon's one client
  (`capture.one_schwab_client`), used by the stream and every chain request, built from
  `schwab_token.json` once and kept for the daemon's life. The token file's other writers are
  run by hand and write under its lock: `python reauth_schwab.py` (a new sign-in) and
  `tools/schwab_field_inventory.py` (its own client, which takes a token the daemon saved
  before refreshing one itself). Its session (`schwab_client.OneRefreshSession`) starts nothing else: it refreshes
  the token when it is within 300 s of expiry, one request at a time (the others carry the token
  it returned), and writes it to the token file atomically. Its session holds as many connections as
  the quotes requests it sends together for a ticker a page shows (`schwab_client.CONNECTIONS`,
  `QUOTES_AT_ONCE`: two, operator 2026-11-12: "lets go up in step"), each kept through a pause
  (operator 2026-11-02: "Yes, keep it open"): every other request is sent alone, in turn. Nothing of ours closes it. When Schwab closes it,
  the pool drops it before the next request; a request caught in that close fails, and its caller
  logs it and asks again, a watchlist add excepted, which reports NOT_CHECKED for the operator to
  repeat; one dropped in silence stalls that request to schwab-py's 30 s timeout,
  and the next opens a new connection. The session is the one owner
  of the sign-in: once Schwab answers a refresh with a refusal (the refresh token expired, revoked
  or invalid; a network failure or Schwab's edge 403 page is no refusal), it logs it once and every request raises
  `SignInRefused` with nothing sent, the stream's logins too; the chain sweep asks for nothing
  while signed out (`ChainSweep.work`). A new sign-in saved to the token file (`python
  reauth_schwab.py`; a new creation time) is taken, its token and creation time, the streamer's
  too, with no restart: while refused, at the next request or sweep look; while signed in, when
  the next refresh is due, in place of the refresh. Every writer of the token file holds its lock
  (`schwab_client.token_file_lock`, across processes): the daemon's session from its look at the
  file through its refresh and write, the client's read when it is built, a sign-in being saved
  or the old one removed (`reauth_schwab.py`), and the field inventory's client; so no sign-in is
  saved during a refresh and none is written over. A token file that holds no sign-in is logged
  once. The client is never rebuilt. Enforced by:
  `tests/test_data_path_sign_in_v1.py`, `tests/test_data_path_rules_v1.py`
  (`test_twenty_requests_at_a_refresh_send_one_refresh_and_all_carry_the_new_token`,
  `test_the_daemon_builds_one_schwab_client_and_a_failed_refresh_never_rebuilds_it`).
- Data is pushed at every hop. Nothing polls. Today the page still re-reads routes after each push
  (§3.2) until SHAPE step 4. Enforced by: no machine check — ENF-15.
- The databases are history, written in the background (two writers today, §3.5). Nothing on screen waits on them.
  Enforced by: D4 and D6 below.
- At startup the in-memory state is loaded once from the latest stored values, so a restart, a
  weekend or the close shows the last values with their time, marked not live (§2 D5).
  Enforced by: `tests/test_one_levels_producer_v1.py` (the stored load) and D5 below.

## 2. The rules

The rules for every change are `AGENTS.md` § Rules. The rules for the data itself, at every hop
from Schwab to the screen (daemon, console, page), are these:

### The data rules (enforced)

- **D1. Newest by Schwab's time wins.** Which value is current is decided by Schwab's own
  timestamp on it (quote time, trade time, book time, bar time, the frame's timestamp, the chain's
  fetch), never by the order messages arrive. Enforced by: `tests/test_data_path_rules_v1.py`.
- **D2. Everything Schwab sends is kept.** Every field and every timestamp of every message,
  the frame's own timestamp included, reaches the daemon's record as sent; the database records
  it as D4 says (option quotes and books for the kept contracts only, five sessions). `docs/schwab_fields.csv` lists every field Schwab has sent (one row
  per field path; regenerated by `python -m tools.schwab_field_inventory`, which opens no second
  streaming socket; its `schwab_doc` and `sample` columns are written from a probe's raw replies
  and kept by the tool); a value Schwab sends is taken as sent, never computed. The daemon asks
  every service for every field number Schwab accepts (0-150 on LEVELONE_*, 0-300 on the others;
  Schwab answers code 22 past them), so a field Schwab sends without documenting it is kept too;
  owner: `capture.Daemon.send_requests`, with `capture.HIGHEST_FIELD`.
  Enforced by: `tests/test_data_path_rules_v1.py`; the field request and an undocumented field
  reaching the record, `tests/test_data_path_one_watchlist_v1.py`.
- **D3. The live path holds only the newest.** One current record per symbol (a quote merged
  field by field, Schwab sending only the fields that changed; a book or a bar replaced whole) and
  one current chain per ticker (replaced whole). A newer value replaces the older one at once;
  nothing old waits in a queue. The live path's memory is bounded by the number of symbols, never
  by how fast Schwab sends. The one exception is the database writer's record of every message it
  records (D4): while the database refuses writes it holds every message, in memory up to its cap and
  past it on disk, growing with Schwab's rate. Enforced by: `tests/test_data_path_rules_v1.py`.
- **D4. `stream_capture.db` is the memory, of what the operator trades, for five trading sessions.** Its
  one writer records every message Schwab sends but option quotes and option books, which it
  records only for the contracts the daemon keeps (`capture.Daemon.saves`, operator 2026-10-09):
  each watchlist ticker's soonest expiration not passed (today's when one is listed, else the
  nearest), at the strike nearest its price (the price row's) and the 5 listed strikes each side
  (`capture.saved_window`, redone on each price and chain; while the price row has no price the
  ticker keeps the window last computed, so its contracts go on being recorded), and the contract selected on the Flow
  panel. What the daemon streams and pushes, and the levels, are unchanged. Once after each close
  of the last option market the daemon has the writer remove every row received before the newest
  five sessions in Schwab's /markets answers began (`capture.keep_sessions`,
  `time_et.sessions_since`, `CaptureWriter.prune`: `PRUNE_ROWS` rows a transaction, one between
  rounds of live writes, each round writing at most one batch (`batch_rows`) of the messages
  queued, so a writer that is behind commits as often as one that is not; none while messages
  wait in the queue, and none once the writer has taken the stop, which waits at most for the part in progress; the newest watchlist row always kept); while today's market is unknown or open, or fewer
  sessions are held, nothing is removed. The freed pages are reused (no VACUUM), so the file stays
  about one week's size. Enforced by: `tests/test_data_path_stream_kept_v1.py`. Nothing
  else in `stream_capture.db` keeps old data (`ed_console.db` keeps the chain captures and level
  crosses, §3.3), except the writer's own spill files below that hold Schwab's messages
  until they are written back: those that hold messages while the database refuses writes, those
  a stop, a kill or the writer's death left on disk (written back at the next start), and one
  the disk would not delete once written back (deleted at the next start). A message whose row is refused (a constraint, a value SQLite cannot
  hold, a message without its table's shape) is kept as sent, with its error and time, in
  `stream_write_failures`, and the writer goes on. While the database refuses every write
  (locked past the writer's wait, full, read-only), the writer holds the messages in memory, in
  order, and every `retry_sec` plus up to `batch_sec` (1.25 s at the defaults; a locked
  database also its 30 s wait) opens a new connection and writes them again until it can; it reads
  blocked with the refusal and how many messages it holds. The writer's state
  (`stream_spine.WriterStatus`, counted at commit) rides the daemon's heartbeat to the header's
  Record, a line the daemon serves (its times in Central Time). Owner: the writer thread
  (`CaptureWriter.run`, started with the daemon). Production's stream decoded from the wire takes
  about 1.1 KB of memory per message (production's mix of 2026-10-05 14:00:00-14:00:03 CT, held by
  the writer, measured with tracemalloc), and Schwab sent 2,211.7 messages a second in all, so a
  block holds about 2.5 MB more each second, about 9 GB an hour. So memory holds them up to a cap
  (operator 2026-10-05: about 2 GB of memory, `HOLD_CAP_BYTES` = 2 GiB): each held message's
  memory is counted once, when it is held (`stream_spine._held_size`: the message's own objects;
  the test `test_the_hold_cap_holds_memory_to_its_size` fills the cap with the mix to within 5%
  and finds the count within 5% of tracemalloc), and the Record shows it. Counting costs about
  26 µs per option quote and 216 µs per book (about 6% of one core at 2,173 quotes a second),
  only while holding, and it competes with the stream's event loop for Python's interpreter
  lock. Every
  newer message goes to a spill file beside the stream database (`stream_capture.<ms>.1.spill`,
  append-only, each record a 4-byte length and the topic with the message as sent), behind the
  older ones. A spill file is only ever created, never opened over another file (a name taken
  moves it to the next millisecond). When the database takes writes again the writer writes
  memory, then the spill files, oldest first, then what arrived meanwhile (the newest spill file
  takes it, in order). Each part of a spill file's write-back is committed in one transaction
  with how far the write-back got (how many records, `stream_spill_progress`), so a part is in
  the database exactly when its count is; once every record is in, the file is deleted, then its
  count. Spill files a stop, a death or a kill left beside the database are written back when the
  next writer runs, before what it receives, each from after its last committed part, with each
  message's own receipt time; one whose every record is committed (a kill between its last part
  and its deletion) is deleted, not written again. A record that does not decode (a damaged file)
  is kept as its bytes in `stream_write_failures` with the file and byte it was at; its length
  places the next, so every record after it is written back and the file deleted as any other.
  Bytes that make no whole record (a crash cut a record off, or a damaged length, which places
  nothing after it) are kept the same way, as one row: nothing in a spill file is cut away
  unrecorded. A file found at start is read only: what arrives during its write-back goes to a
  new spill file behind it, never behind bytes that frame nothing. A file the disk will not
  delete (held open by another process) keeps its progress row, which counts every record
  committed: the next start deletes it without writing it again, and recording goes on. A message the
  spill file cannot take (a full disk) is lost: counted, with the window it was received in
  (first and last receive time, served as epoch seconds and shown in Central Time). A daemon
  that stops while blocked leaves what it holds on disk (memory in a spill file named for when
  the block began, `stream_capture.<ms>.0.spill`, before the spill file's). Only an error outside these ends the thread: it reads
  dead with the error; its spill file stays, listed as left on disk with its messages (they are
  on disk, not counted not recorded); what it held in memory and what reaches it after are
  counted not recorded until the daemon restarts.
  Enforced by: `tests/test_data_path_rules_v1.py`, `tests/test_data_path_writer_failures_v1.py`.
- **D5. The last value stands, marked** (`AGENTS.md` rule 5). Every value carries Schwab's time and
  the newest by that time is the current one; a reconnect never replays an older value as live. A
  value is live only while it is updating: its feed delivers it and its market trades
  (`live_market_plane.live_state`). Its market trades on a day Schwab's /markets answer gave
  windows for, while Schwab's SECURITY_STATUS for it is not Closed or Halted. One rule (operator
  2026-11-02): a valid session is live, and with none the screen reads CLOSED and the last value
  stands. The sessions are Schwab's /markets windows as sent (`time_et.session_label`: stocks 07:00
  to 20:00 ET in its schedule of 2026-10-30), and before the first of them the pre-market begins
  with the first stock trade Schwab streams that was made that day (`time_et.record_trade`, from
  LEVELONE_EQUITIES TRADE_TIME_MILLIS; measured 2026-11-04 to 11-11: 04:00:00 ET on every market
  day, the last at 20:00 ET, none between and none on a weekend, while SECURITY_STATUS stays
  Normal for SPY and IWM all night; operator 2026-11-11: "it is premarket", "the data should be
  live"; `tests/test_markets_sessions_v1.py`). An option contract, the chain sweep and the levels follow the option windows it sends,
  pre-market and post-market included (`time_et.options_open`: 07:30 to 09:25, 09:30 to 16:15),
  while `time_et.option_market_open` stays the option markets' regular window, which decides the close
  values. In the option pre-market Schwab sends, a delivered chain is published and its levels are
  live (`server._closed_since`; operator 2026-11-12: "Yes, make them live"; Schwab pushed option
  quotes with that morning's quote times and Greeks from 07:30 ET); between that window and the
  regular one the levels stand. No chain is asked for between two of Schwab's windows, so when
  the regular one starts the levels are from before the break: they stand, not live, with their
  age, and the reason says so ("Schwab's option session reopened ... and its first chain since
  has not arrived") until that chain arrives; past two of the sweep's rounds with none, the
  reason is the sweep's (`server._levels_state`, `time_et.option_window_began`; operator
  2026-11-13, asked what a bank would do: "i agree with bank analogy";
  `tests/test_markets_sessions_v1.py`). When it stops
  updating, for any reason (feed down, market closed, an input missing), the last value stands,
  marked not live with its time and its served age, and every value computed from it is marked not
  live too. While the daemon's push to the page has stopped, no age is served and the page computes
  none, so the screen keeps the trade time Schwab sent and no age (operator 2026-10-25: the last
  served age is not the age now).
  The state's one word is served beside the values (`live_state`): LIVE; OFFLINE, the feed itself
  down (the header during a feed outage); NOT LIVE, the feed up and this symbol not held or its
  market not trading. The page shows the served word. A value never received, or sent invalid, shows as
  "-". Calculations keep every digit and every contract; rounding is on screen
  only. Where today's code differs: §3.5 items 5 and 6.
  Enforced by: `tests/test_data_path_rules_v1.py` (newest by Schwab's time, no replay as live),
  `tests/test_data_path_live_status_v1.py` (the daemon's status is current when it is not older
  than 3 s), `tests/test_data_path_strike_counts_v1.py` (a strike's volume and open interest
  keep every digit), `tests/test_data_path_side_volume_v1.py` (the volume below and above
  spot keeps every digit), `tests/test_data_path_book_size_v1.py` (the book's top size
  keeps every digit), `tests/test_data_path_tape_size_v1.py` (a tape print's size
  keeps every digit), `tests/test_data_path_silent_subscription_v1.py` (a missing heartbeat
  keeps the last subscription),   `tests/test_data_path_quote_time_v1.py` (the row carries
  Schwab's quote time), `tests/test_data_path_book_time_v1.py` (the book panel carries
  Schwab's quote time and book time), `tests/test_data_path_option_quote_time_v1.py` (the Flow
  panel carries the contract's quote time and book time), `tests/test_data_path_level_spot_v1.py` (a down price marks the
  levels and the wall stays), `tests/test_data_path_chain_spot_time_v1.py` (the chain
  ladder's spot carries Schwab's trade time), `tests/test_data_path_desk_spot_time_v1.py`
  (the trade desk's spot carries Schwab's trade time), `tests/test_data_path_chain_time_v1.py`
  (the desk map's chain age carries the chain's time), `tests/test_data_path_strike_chain_time_v1.py`
  (the GEX-by-strike badge carries the chain's time), `tests/test_data_path_snapshot_time_v1.py`
  (the desk map's LEVELS pill carries the snapshot's time), `tests/test_data_path_level_asof_time_v1.py`
  (the levels page As-of column carries each level's time), `tests/test_data_path_served_verdicts_v1.py`
  (the levels verdict by the ticker's own option market, an option contract by the session, and a
  page told to read again while its price or its levels are not live);
  the rest — ENF-22.
- **D6. No live screen reads the database.** Every live route serves from memory; the database
  is read at startup, after the close and for research only.
  Enforced by: `tests/test_data_path_rules_v1.py`.

## 3. Today

Today's code, accurate as of the last PR that touched each part. Ed Console is one program (SHAPE
step 3): the capture daemon runs the console's pages and routes (`server.app`, port 8000) in its own
event loop (`capture.serve_console`), and the console reads the daemon's one bus in memory
(`app.options.order_flow.streaming._bus_loop`), never a copy over a socket. Still to come from §1:
the console's own stores built from the bus (§3.3) are deleted into the one State. The page has one
connection, its socket (`/ws`): every panel it draws is sent on it (`server.PAGE_PANELS`).

### 3.1 The program

One program, started by `launch.py` (`start_ed_console.bat`) in the "Ed Capture Daemon" window
(`start_capture_daemon.bat`, which restarts it when it exits), stopped cleanly by
`python launch.py stop`, which sets the program's stop request (`program_lock.StopRequest`: a
named event of the operator's Windows session, no port). The program opens its one socket first (`capture.open_sockets`, port 8000 or `ED_CONSOLE_PORT`) and
writes the port it holds into its lock, after its pid (`program_lock.record_ports`); the launcher
and the stop read it there (`program_lock.program_ports`), never a port chosen before the program
bound it. The launcher
starts it unless this checkout's program runs (`launch.running`), waits for its ports and then
for its pages to answer `/api/health` (`launch.START_WAIT_SEC`), and opens the browser; it
starts nothing else. The rows below are its
two parts, in the same process: the daemon's (Schwab, the bus, the recording) and the console's
(the pages and routes). There is no second process: everything the console shows is read from the
daemon's memory, in the same program; a crash of either part ends both, and the window restarts
the program.

| Part | Started by | What it does |
|---|---|---|
| **Daemon part** | `launch.py` (`start_ed_console.bat`), unless this checkout's program runs: it runs `start_capture_daemon.bat` in its own window (`launch.daemon_window`), which restarts the program when it exits and closes when the batch ends (a stop on request: 30 s after its last line). Stopped cleanly by `python launch.py stop`, which acts only on this checkout's own program (`launch.running`: the processes started from its folder that run its module right after their program, so one still loading is found; one it cannot ask is logged and the stop exits 1, "still running" or "ended, not asked by this stop"; its window's 5 s before a restart, with no process, reads "not running", exit 0, and the window then starts it, STOP-GAP): it sets the program's stop request (`program_lock.ask_to_stop`), whose one waiter (`capture.stop_on_request`) sets its stop, the one Ctrl+C in its window sets, which ends the console's pages and each page's price socket (`capture.serve_console`: uvicorn closes each connection and waits for its handler, at most `timeout_graceful_shutdown`, 10 s; a page that stopped reading is dropped, §3.2), its writer writes what it holds (to the spill files while the database refuses writes), and it exits 5, which the window does not restart. Killing it from outside is refused by `tools/operator_yes_guard.py`: on Windows it skips the shutdown | The only part that talks to Schwab: it reads its own `.env` (the Schwab credentials), however it is started; why Schwab is not connected, and since when, is in its log and rides its heartbeat (`schwab_down`) to `/api/health` (the header's one indicator stays OFFLINE). A chain sweep that ends on an error is logged. Its log is one file a day, `logs/stream_capture.<date>.log` (`capture.DailyLog`, by each line's own time; no file is renamed, so a viewer holding one open never stops it), the newest 45 kept (`capture.LOG_DAYS_KEPT`). It runs under `python` in its window, its error output: an error before its modules load shows there, and from the log's start every line goes to the day's log file and to the window (operator 2026-11-04). Holds the watchlist, the one list of tickers Schwab is asked for (`capture.Daemon.watchlist`), and is its only writer: the operator adds or removes a ticker on the page, the console passes it on (`{"op": "watchlist"}`, §3.2), the daemon checks an added ticker with one `/quotes` request (one Schwab names in `errors.invalidSymbols`, or does not quote, is not added) and answers with a `watchlist` record (the whole list, what happened, Schwab's answer to the check), which its writer stores in `stream_capture.db` `stream_watchlist`; the newest row is read at its start (`stored_watchlist`). A change takes effect at once, with no restart: every stream service and every REST request (chains, quotes, price history) asks for an added ticker and stops asking for a removed one; what was recorded for it stays. Holds the one Schwab WebSocket and subscribes once per connection (`Daemon.ask`): every watchlist ticker on each equity service (quotes, 1-minute bars, news, both books), the header's market context (`live_push.MARKET_CONTEXT`) on quotes, bars and news, and the option contracts its option rule picks (§3.4); a change to the watchlist or the contracts is asked once (UNSUBS what left, ADD what came), and nothing is asked again on that connection whatever Schwab answers. Every Schwab answer is matched to its own request by its requestid (`Daemon.answered`; one reader reads every frame), logged and recorded (`stream_subscriptions`) exactly as Schwab sent it. Fetches full option chains over REST (`ChainSweep`, `calibration/complete_chain_capture.py`, on its own thread, one request at a time): every watchlist ticker, each in its turn in one rotation, a ticker a page has selected before each other one, without end; hands each chain to the console. Every Schwab message goes once onto its in-memory message bus, which keeps each topic's current record, the newest by Schwab's time (§2 D1, D3); its database writer records every equity message and the kept contracts' option quotes and books (D4); the console and the browser's price socket get each record that changed. Builds the price row the browser shows from the current equity quotes. Writes the first chain of each ticker fetched in each capture window to the chain history in `ed_console.db` (decision 7). |
| **Console part** | the daemon part, at its start (`capture.serve_console`: `server.app` on port 8000, `ED_CONSOLE_PORT` read by `capture.open_sockets`, in the same event loop, with the page's price socket at `/ws` on the same port, serving the app's state `server.app.state.prices`, set while the program serves prices and None before and after). Before it starts, `launch.py` brings the checkout to origin/main when the program is not running (`launch.bring_to_origin_main`: fetch, fast-forward main); moved, it runs the new `launch.py` as its child (`start_ed_console.bat` reads its one line whole before running it, so a rewritten batch file is never read mid-run); with local changes, a checkout not on main, a history split from origin/main or origin out of reach it starts from the commit the checkout is at and says "commit check: refused" or "unknown" with why, never passed (whether the app starts is never the repository's to decide, RC-512). Running, the check is not run, so the checkout never moves under the running program. It stops with the program |  Makes no Schwab call itself. Reads every Schwab record from the daemon's bus as it changes (`streaming._bus_loop`: books, option quotes, the equity tape, the chains), the price row from the daemon's own builder (`live_price_rows.price_row`) and the daemon's status from the one `live_market_plane`; it keeps no price of its own. Prices each chain the daemon delivers into the levels and keeps them in memory. Writes the level crosses to `ed_console.db` (it writes no bar). Serves the page and every `/api` route, the watchlist's changes included (`POST /api/watchlist`, `DELETE /api/watchlist/{ticker}` passed to the daemon, answered with its record); the list itself reaches the page only on the page's socket (each beat's status, below). Tells the daemon the contract selected on the Flow panel. |
| **Browser** | the operator | Loads one page from the console. Shows the watchlist as each beat on its socket carries it (`/ws` `feed`, the daemon's status), redrawn only when it changes; before the first beat the rail reads "-", and a beat with no status keeps the list drawn and says the daemon is not reporting (`tests/e2e/console-watchlist-socket.spec.js`). Edits it only through the console, whose answer carries the new list (it keeps no list of its own). Each list carries its time on the program's one clock (the beat's `ts`, the answer's `ts` from the daemon's `watchlist` record), and a list stamped before the one drawn is not taken: a beat built before an add that arrives after the add's answer leaves the added ticker on the rail. Gets prices pushed from the daemon for the symbols it shows (the watchlist, the header's context); gets change signals (levels, chain, flow, liquidity) and the session label pushed from the console; reads everything else from the console's `/api` routes. |

### 3.2 How they talk

| From → to | Channel | What travels |
|---|---|---|
| Schwab → daemon | Schwab's streamer WebSocket | equity quotes, option quotes, both order books, 1-minute bars, news — the fields that changed |
| Schwab → daemon | Schwab REST | full option chains, each with its contracts' quotes (their Greeks, §3.4 Option chain); each ticker's price history: 1-minute bars and daily candles (§3.4 1-minute bar) |
| daemon part → console part | the daemon's bus, in memory (`streaming._bus_loop`: a LATEST subscription) | each topic's current record the moment it changes (a quote merged field by field with each field's times in `field_ts`; a book, bar or news item whole), at the start every current record; never an older value behind a newer one (§2 D1, D3); each ticker's newest whole chain, in parts of 500 contracts (`chain.TK`: part i of n, with the time the chain began, which the chain history stores too, so a chain begun before the close is never the close values however late it is delivered; a failed fetch with Schwab's answer); only Schwab's records (`live_push.is_forwarded`) |
| console part → daemon part | a call, in memory (`capture.Daemon.console_frame`) | the contract selected on the Flow panel (`{"op": "flow_contract", "contract": symbol or null}`: only one Schwab listed in a chain the console holds, refused otherwise (409)); the daemon holds it in memory only. And each add or removal of a watchlist ticker the operator makes (`{"op": "watchlist", "action", "ticker", "id"}`), answered by the daemon's `watchlist` record on the bus, carrying the same id |
| `launch.py stop` → the program | its stop request, by name (`program_lock.StopRequest`, made before the program takes its lock; set by `program_lock.ask_to_stop`): on Windows a named manual-reset event, `Local\EdConsoleStop-<hash of the lock's path>` (`stop_event_name`), in the operator's session namespace with default security, so only his session's processes can open it, and each runtime (production's, a test's) has its own; elsewhere (Linux CI) SIGTERM to the process the lock names | the clean stop, nothing back: set twice it stays set; a runtime with no program's request (none runs, or it has not made it yet) is an `OSError` that `launch.py stop` reports, "not asked to stop", exit 1. The program's one waiter (`capture.stop_on_request`, on its own thread, `STOP_WAIT_SEC` at a time, so any other stop ends it) sets the program's stop (`tests/test_program_stop_v1.py`, `tests/test_data_path_startup_v1.py`) |
| daemon → browser | the page's WebSocket, `/ws` on the program's own port (8000; `live_ui.page_socket`, routed by `server.app`; refused, 403, while the program serves no prices, `server.app.state.prices` None) | on each subscribe, what every asked-for symbol is (its key, e.g. `$SPX`, and display name `SPX`, from `instrument_identity`); then each panel the page shows of its selected ticker (the subscribe's `ticker`, and its `panels`: each panel the page shows with its own parameters; `server.PAGE_PANELS`, each kind's producer, given what the page asked (`live_ui.Asked`: ticker, now, parameters), run on a worker thread as a route's read ran, so a producer waiting on the levels' lock never holds the beat; a producer that raises fails its panel alone, `{"failed": words}` drawn as the panel's words, its traceback logged (`live_ui.LiveUiServer._produce`); a kind read with different parameters names each reader's panel `<kind>:<reader>`; the Vanna and Charm tabs, `server.strike_bars`, the published levels' per-strike rows in the window the page asks (scope, the operator's panned centre and shift; a window it cannot draw is unavailable with its words), marked changed with the levels (`server._levels_changed`, `server.LEVELS_PANELS`); the expiry list, `server.expiries`, Schwab's listed expiries and daysToExpiration from the published levels, or, while none are published, unknown (`expiries` null) with the levels' own reason; a page switching ticker puts no expiry in force until that ticker's list arrives; the gamma group, each marked changed with the levels: the terrain, `server.terrain` (`terrain:levels`, `terrain:chart`, `terrain:desk`, `terrain:map`), the per-strike rows, `server.strikes` (`strikes:gbs`, `strikes:chart`, `strikes:migration`, `strikes:desk`, each in its window), the heatmap, `server.gamma_surface` (`surface`, its window), one expiry of the chain, `server.chain` (`chain:ladder`, `chain:detail`, `chain:structures`, each at its `expiry`, null the chain's front one), and the price levels, `server.levels` (`levels:view`, `levels:liquidity`, `levels:desk`, `levels:map`, each in its timeframe `tf`; a `tf` not served fails that panel in words), which carry each level's distance from the live price and so are sent again with each price row of the ticker (`server.PRICED_PANELS`, `live_ui.LiveUiServer.on_row`); a frame of an expiry or timeframe the page no longer shows is not drawn), at once and again each time its producer marks it changed (`live_ui.changed`: `_publish_levels` on each new chain), only to the pages on that ticker showing that panel; the page draws a panel only for the ticker it shows, and '-' for one not yet received since a switch (`tests/test_live_ui_daemon_to_browser_v1.py`, `tests/e2e/console-gamma-chain.spec.js`, `tests/e2e/console-options-vanna-charm.spec.js`); then the finished price row per symbol, on every change, plus a heartbeat every second: the daemon's whole status (Schwab socket, why it is not connected, symbols held per service, the watchlist, the chain sweep's last round time, health). The page matches rows by that key and shows that name; the market-context symbols come in the page (meta `ed-market-context`, from `live_push.MARKET_CONTEXT`). A client (a browser) has stopped reading when asyncio's flow control keeps writing to it paused (its buffers full) for `live_ui.HEARTBEAT_SEC`, so its beat is not taken, or when it does not answer uvicorn's keepalive ping (every 20 s, within 20 s): the web server's protocol for the socket (`live_ui.PageSocket`, `capture.PAGES`, the one place a client that stopped reading is dropped; each connection's handler, `serve_client`, owns its lifetime) drops it by aborting its connection, since no close frame can be written to a client that does not read and uvicorn's own close waits for the bytes it never takes, so its handler ends, the beat it held ends within a beat, and the program's stop is not held; the page reconnects (`tests/test_data_path_startup_v1.py`, `tests/test_live_ui_daemon_to_browser_v1.py`) |
| console → browser | HTTP | the page itself (`/`, `/static`), the program's health and build (`/api/health`, `/api/build`), and what the operator sends: a watchlist add or removal (`/api/watchlist`) and the Flow panel's contract (`/api/flow-contract`). No panel's data: every panel is sent on the socket, each group again when its input changes (`server.CHAIN_PANELS` on a new chain, `LEVELS_PANELS` on each publication of the levels, `BARS_PANELS` on a new bar, `FLOW_PANELS` on a streamed equity quote or book), and the session label with each beat (`feed.session`) |

### 3.3 Where data lives

| Place | Owner | What it holds |
|---|---|---|
| Daemon memory | daemon | the message bus: each topic's current record (one per symbol and service; an unsubscribed symbol's is forgotten) and each ticker's newest chain; the watchlist; the option rule's inputs and pick, and the Flow panel's contract; the equity quotes the browser's price row is built from |
| Console memory | console part (still to be folded into the daemon's one State, §3 intro) | no price row: it reads the daemon's (`live_price_rows.price_row`); a second copy of the books (each symbol's newest book from each Schwab service, so a book Schwab has not changed stands however many the other service sends: `state.OrderFlowState`), option quotes and the equity tape (fed from the daemon's bus, §3.5 item 1); the chains the daemon delivered; the computed levels; each ticker's 1-minute bars (`server._bars`, the newest 24,000: Schwab's price history pushed by the daemon, each streamed bar on top) and daily candles (`server._daily`); the level crosses (`server._crosses`), loaded from `ed_console.db` once at startup and then fed live (§2 D6); each symbol's newest 500 trade prints, kept once (the live state's tape, `state.push_level_one`: the options tape and the order-flow numbers both read it) and each equity book of the last 240 minutes, one per second of Schwab's BOOK_TIME, placed at that time and not at its arrival (`history.BOOKS`), and each ticker's order-imbalance readout of both books and their composite, one per second for 308 s and the one standing before (`history.LEAN`: computed once as each book arrives by its owner, the console's intake; while no book arrives the last stands and the live rule marks it not live), held in memory from the console's start (no database read) |
| `stream_capture.db` | daemon's writer | the newest five trading sessions (§2 D4): every raw Schwab message but option quotes and option books outside the kept contracts: quotes, books, option quotes, bars, news, price history answers (`stream_pricehistory_raw`), subscription answers; every message a write refused, kept as sent with its error (`stream_write_failures`: the writer's refused rows, and each chain whose history write was refused); how far each spill file's write-back got (`stream_spill_progress`). Quotes, books and option quotes are indexed by receipt time, the order they arrive in (an index by symbol wrote a page per row: `tests/test_data_path_writer_failures_v1.py::test_the_indexes_add_no_more_pages_than_the_rows_they_index`); bars by symbol and bar start. A new database gets those indexes with its tables (`stream_spine.RECEIPT_TIME_INDEXES`); a writer never changes an existing table's index at its start. Production's old database (indexed by symbol) is not reindexed: it is replaced by a new one holding the last five sessions, with these indexes (`ACTIVE_PROGRAM.md` STREAM-DB-SWITCH). The tables the daily keep trims are `stream_spine.KEPT_BY_TIME`, the watchlist, markets, feed-status and subscription tables among them. |
| `stream_capture.<ms>.<n>.spill` (beside `stream_capture.db`) | daemon's writer | while the database refuses writes, the held messages past the memory cap, in order (n 1), and at a stop what memory held (n 0); deleted once every record is written back (a record that does not decode or frame kept as its bytes in `stream_write_failures`); one a stop, a death or a kill leaves is written back at the next start (§2 D4) |
| `ed_console.db` | console (level crosses), and the daemon (the chain captures) | level crosses (`level_crosses`) and the chain captures (`complete_chain_captures`, decision 7), kept beyond five sessions — plus tables nothing writes or reads, dropped in P2-DB3: the old bars (`price_bars_1m*`), the former ticker board (`logging_universe*`), the morning chains (`option_chain_morning_full`), the ML pipeline's tables |

### 3.4 The journey of each kind of data

- **Equity quote.** Schwab → daemon bus → (a) daemon writer → `stream_capture.db`; (b) daemon's
  price row → browser socket → header and watchlist, and the same row → the console → the spot the
  levels and top of book use; (c) the raw message → the console's order-flow tape. Pushed
  end to end; one price row everywhere.
- **Option quote and order book.** Schwab → daemon bus → writer, and → console memory → the
  book, book map, tape and contract panels on `/ws` (`server.FLOW_PANELS`). An equity
  has two Schwab books, NYSE_BOOK (exchanges) and NASDAQ_BOOK (market makers); each is stored
  under its service and served for the `venue` the screen's venue switch names, never combined,
  but in the Desk Liquidity card's order-imbalance readout (operator 2026-11-03, step 1 of 3):
  the book panel (`server.book`) serves `readout` whatever the venue, both books and their
  composite (`engine.book_readout`, the operator's decision of 2026-11-04, "the most recent
  balance is the most accurate balance": every quote of the books Schwab sends for the ticker,
  one per contributor, codes matched without regard to case; a contributor in both books (NSDQ,
  for SPY and IWM, the only tickers NYSE_BOOK carries) from the copy with the newer quote time,
  Schwab's market-maker field 2, which schwab-py names SEQUENCE; with one book held, that book;
  the shares summed at each distinct price; a level with no per-exchange rows taken whole, and a
  copy sent without its quote time never newer than one sent with it, each marking the dedup
  partial), read over at most one value a second per ticker that the console's intake
  records as each book arrives, the newest in that second (`history.LEAN`, 308 s), and judged
  live per book by the one live rule, the composite only while both are; a venue not live is read
  to the reading its readout has stood from (a stopped book from its last arrival; a composite
  with one book still running moves with it), with its book's time and age. The exchange auction
  windows are the 5 minutes before and the 10 minutes before the end of Schwab's regular window
  for the date (`time_et.auction`); inside them the number stands and a line says the auction
  imbalance is a different number, not shown (continuous trading runs through them).
  The books streamed are every watchlist ticker's. For each option contract the daemon holds
  (the option rule, below), each field has one producer, whichever arrived last: its volume is
  the stream's (`math_exposure_core.overlay_streamed_contract_fields`; one the stream has not sent
  shows "-"), its Greeks the stream's as the sweep took them (Option chain, below), and its open
  interest the chain's, for every contract: the stream does not send it for every contract it
  streams (measured 2026-11-05: none all day for 137 of 375 streamed, while the chain sent each
  one's). The feed's state labels the heatmap leg; it never picks the value. A contract the
  daemon does not hold takes every field from the chain, its Greeks from Schwab's quotes. A book message is the book Schwab sent, a
  side with no levels included (empty, never replaced by an older two-sided book); a side Schwab
  sent no level for at a price is absent in the book heatmap, never a 0 size. The book heatmap and
  the options tape serve from the console's memory (§3.3), never the database. The book's Mark is
  Schwab's MARK as sent (Mark Price: LEVELONE_OPTIONS field 37 for a contract, LEVELONE_EQUITIES
  field 33 for an equity, `docs/schwab/schwab_streamer_api.pdf` §3.2 and §3.1), never a midpoint
  of ours; microprice is computed from the quotes Schwab sent, a crossed book included (served
  with `crossed`).
  A contract is a ticker's when Schwab listed it in that ticker's chain (whatever its root:
  SPX and SPXW are both $SPX's).
- **The option contracts streamed (the option rule).** What streams live is the most actionable
  information at any moment (operator 2026-10-08). The daemon picks the contracts from each
  watchlist ticker's newest whole chain on its bus (owner `capture.Daemon.pick_options`, run when
  a chain is put in the rule's order, by `Daemon.follow_market`; on a watchlist change,
  `Daemon.watchlist_request`; and on the Flow panel's selection, `Daemon.console_frame`). A chain is put in the rule's order once, `capture.shown_first`, at the
  daemon's time and the ticker's live price, the price row's (`live_price_rows.spot`, the rule
  reads LAST_PRICE nowhere else): as it arrives, or, while the row has no price, at the next price
  row. The plane is fed by `Daemon.follow_market` (each equity quote on the bus,
  `Daemon._took_quote`, which then hands the ticker's row to the rule), the owner of its rows for
  the browsers (`live_ui.serve_live_ui` reads them, served at `/ws`) and for this rule. A daemon task that ends before the stop
  (a local socket whose port cannot be bound, a follower or the chain sweep ended on an error)
  makes `capture.run` end the daemon with the error in its log, and `start_capture_daemon.bat`
  restarts it (`tests/test_data_path_startup_v1.py`). While the row has no price (none received
  yet, or Schwab sent it invalid) the ticker keeps the order and the recorded window it has, and
  its newest chain is ordered at the next price; each row places only its own ticker's window
  (`tests/test_option_contract_rule_v1.py`). The contract
  selected on the Flow panel (`POST /api/flow-contract`, only one Schwab listed in a chain the
  console holds; the console names it to the daemon on every connection, `{"op":
  "flow_contract"}`, §3.2) streams on LEVELONE_OPTIONS and OPTIONS_BOOK, first in the order
  Schwab is asked in. After it come every ticker's recorded contracts (its window), then every
  contract of the tickers a page has selected (operator 2026-11-11: "all resources are behind
  it", "the others may lag some"), then every other ticker's; each group dealt across its tickers (each
  ticker's first, then each one's second, `Daemon.pick_options`), and a page's selection runs
  the rule again (`Daemon.page_selected`); a ticker's own order is the
  contracts the heatmap shows first (`shown_first`, operator 2026-11-10): by the larger of the
  expiration's place among the chain's expirations and twice the strike's count of listed
  strikes from the one nearest the price, the nearest first; of contracts equally near, the
  highest gamma first, Schwab's as sent, the gamma the levels
  take (none sent, -999, or a -999 volatility is no gamma, ranked last); of equal gammas the
  nearest expiration, then the strike nearest the price, calls before puts. No number of ours
  caps what is asked: on each connection every contract of the order is asked on both services,
  and a service that takes fewer says so itself, code 19 (REACHED_SYMBOL_LIMIT,
  `docs/schwab/schwab_streamer_api.pdf`, response codes) with its limit in the message, as on
  2026-10-07: "(LEVELONE_OPTIONS=3000, DISCARDED=2181)", "(OPTIONS_BOOK=100, DISCARDED=1)". The
  daemon takes the limit Schwab stated (`Daemon.limit`, for that connection only) and asks the
  service once more from nothing: one SUBS of the first that many of the order, which overwrites
  whatever Schwab kept of the refused request (its document does not say which symbols those
  are). From then the order is cut at that limit (`Daemon.wanted`). A refusal that states no
  limit, or the one already known, is published as sent (`sub.<service>`) and not asked again on
  that connection. What the daemon counts as held (`Daemon.held`) follows Schwab's commands on
  each request's first answer (`Daemon.answered`): an accepted SUBS replaces what the service
  held, an accepted ADD adds to it, an accepted UNSUBS removes from it, and a refused SUBS holds
  nothing. A contract has expired once now passes Schwab's expirationDate: it stays in the records
  and is never streamed (Schwab still lists an expired Friday on a weekend); one that expires
  between chains streams until the ticker's next chain (one is asked after each option close). Each
  change is one UNSUBS and one ADD of only the difference (`Daemon.ask`). The levels use every
  contract of the full chain, streamed or not. When the owner fails (the daemon down), nothing
  streams: every cell keeps its value and the header says OFFLINE. A contract the daemon stops
  holding keeps its last quote; the Flow panel marks it NOT STREAMED
  (`get_option_contract_streaming_diagnostics`). Tests:
  `tests/test_option_contract_rule_v1.py` (the order, the limit Schwab states, a chain that
  arrives later, a new connection), `tests/test_data_path_one_watchlist_v1.py` (a refusal that
  states no limit), `tests/test_data_path_released_contract_v1.py`.
- **1-minute bar and daily candles.** Schwab's price history: the daemon's chain sweep
  asks `/pricehistory` for each ticker (`complete_chain_capture.PRICE_HISTORY`,
  per `docs/schwab/schwab_market_data_parameters_pricehistory_markets.txt`, each request ending
  now, extended hours included): the 1-minute bars (10 days) and the daily, weekly and monthly candles (2 years) once
  per ET date (`ChainSweep.candles_due`), asked before the chains in each pass of the sweep
  (`ChainSweep.work`: the price-built levels wait for it, a rotation of the chains takes minutes)
  -- every watchlist ticker, options listed or not; each answer whole, as Schwab sent it →
  daemon bus (`pricehistory.TK.SERIES`) → the daemon's writer (`stream_capture.db`
  `stream_pricehistory_raw`, every answer, as sent: recorded like every stream message, §2 D4) and
  → console (the daemon's bus) → the bar writer. Schwab CHART_EQUITY → daemon bus → the daemon's writer
  (`stream_capture.db` `stream_bars_raw`, every bar every hour Schwab sends it), and → the console's
  bar writer. Console memory: `_bars`, Schwab's 1-minute history with each streamed bar standing
  over its minute (a history sent again is taken only for the minutes not held: one that adds
  none changes nothing, pushes nothing and rebuilds no level; daily candles the same as those
  held push nothing, new ones push like a new bar); `_daily`, the daily candles (the console reads no database
  for them, and writes no bar) → the bars, liquidity and desk panels on `/ws`
  (`server.BARS_PANELS`). Enforced by: `tests/test_data_path_pricehistory_v1.py`; the order,
  `tests/test_data_path_rules_v1.py::test_d5_a_start_asks_every_tickers_price_history_before_any_chain`. Charts show completed Schwab bars only, exactly as Schwab sent them, with
  the newest bar's minute (`last_bar`). The live Schwab LAST_PRICE (the header's price row, with
  its age since the trade) is drawn on the chart as its own line and moves with every update; no
  candle is built from quotes (level-one prices do not reproduce a bar's high and low).
- **Price levels** (prior day, overnight, opening range, VWAP, value area). Computed once per
  bar input from the bars into the one price-level snapshot (`canonical_price_level_snapshot`)
  → the levels panel on `/ws` (`server.levels`), and the liquidity zones of the liquidity panel (`server.liquidity`) are built from that same
  snapshot (the market's session, `time_et.market_session_date`: today's while a session is
  open, the newest session's while Closed, whose levels stand until the next session opens; no
  checkpoint or past-date path). Producer `_publish_price_levels`: the bar writer
  (`_write_streamed_bars`) after each bar of every ticker, on its own thread, once every bar
  waiting has been written and pushed as `liquidity` (a `levels` push when the published
  snapshot changed); and the levels loop (`_publish_missing_price_levels`) for a ticker with
  none yet for the market's session (the console's start, a new session). It reads the
  console's bars (`_bars_1m`), whose one owner is the bar writer (`_bar_writer`): it loads them
  from the daemon's record (`stream_bars_raw`, Schwab's newest bar of each minute) before it
  takes any pushed bar (the push queue holds the bars that arrive meanwhile), then keeps each
  pushed bar, and stops at the console's shutdown once the bars queued are kept
  (`stop_bar_writer`). The console's old bar store (`ed_console.db` `price_bars_1m`: bars its
  quote accumulator built and price-history re-seeds before 2026-09-26, then Schwab's streamed
  bars to 2026-10-04) is neither written nor read. The levels loop builds nothing until that load is
  done. If the load fails, no level is built and the console window shows the error. Each bar
  is checked once, where it comes in (`server._schwab_bar`); the levels take the bar writer's
  bars as kept (`liquidity_value_engine.bars_from_candles`), every level function the same.
  The panels serve what it published and build nothing. The confluence panel reads the ranking
  `_publish_levels` stored for the expiry the operator picks. It does not rank again. It does not read a
  chain, the database, or Schwab. It has no loop of its own. The page asks again when the
  console pushes `levels` or `chain` for that ticker, the same re-read ENF-15 still owes for
  every pane. Charm for that expiry is the map `compute_terrain` stored
  (`compute_charm_by_strike` once for the expiry). The volatility blend for that expiry is
  the map `compute_terrain` stored (`iv_by_strike` once for the expiry). The ranking is
  `score_magnitudes` once for that expiry, every strike of it, stored with the publication. The
  matrix does not call any of them again; the request draws only its window's rows
  (`confluence_composite.window_rows`). Vanna
  is the book's `net_vanna`. After that ticker's option market has closed for the day
  (`time_et.option_market_open`), the publication is valued at that day's close
  (`time_et.valuation_instant`, the index close for a symbol on the exchanges' 4:15 p.m. ET list,
  SPY, QQQ and IWM among its 65, the equity-option close for every other ticker), so the close numbers stay for the rest of it. On a day Schwab says is closed
  and before the next open it is valued at the clock: a closed day has no same-day close, so no
  0DTE level is made from a later expiry (operator 2026-10-25). A later
  equity print keeps the price that publication was priced at; the matrix's
  window (every per-strike panel's, Auto; "Strike windows" below), its spot, each row's distance
  from it and the row it sits under are the live price's (`confluence_composite.at_price`). The
  chain's own time stays `computed_ts_utc` and is the line above the matrix. The expiry is a dropdown; a same-day expiry is labeled 0DTE. Each level is sent at its own price and drawn on the rail. An expiry dated before today is not offered. A request that names a date before
  today opens on the next expiry, and the page keeps that one. When every expiry
  on the held chain is before today, the route says no expiry on this chain is
  still open. When no priced book
  is held, the route says so and the page draws that sentence. When the request fails, the
  page says the request failed. When the push stops, the last drawn table stays; the header
  chip is the not-live mark.
  The levels panel also serves the order the
  chart draws them in (`by_distance`): nearest the spot (Schwab's last trade under §2 D5, with
  its trade time `spot_as_of_ts_utc`), each level's distance and side from it,
  and the session's volume profile (`volume_profile`: each RTH 1-minute bar's volume spread
  evenly over its range, one bin per tick, flagged inside or outside the value area).
- **Option chain.** Schwab REST → the daemon's chain sweep (`ChainSweep`) → the daemon's bus, in
  parts → the console (`streaming.assemble_chain_part`: a chain is priced only with every part;
  one that arrived incomplete, or a fetch that failed, keeps the last levels with that reason) →
  `_on_chain` → priced on one pricing thread (`_price_chain`, the only caller of
  `_publish_levels`: delivered chains, stored captures and the tick reprices all wait in one
  queue, at most one entry per ticker, every ticker the same: longest waiting first, a stored
  capture after every delivered chain waiting, and a reprice in its turn behind the stored
  captures queued before it (a ticker's ticks queue another during each of its pricings, so
  a reprice put first would leave the stored ones waiting until their chain was delivered:
  Enforced by: `tests/test_data_path_startup_v1.py::test_the_stored_levels_are_priced_while_a_page_on_another_ticker_takes_ticks`);
  the startup load queues a ticker's stored captures, read from the database when
  priced, only while the daemon has delivered no chain of that ticker, and a chain delivered while
  they wait replaces them, so a stored capture never replaces a delivered chain and no delivered
  chain waits behind a stored one). The daemon's bus keeps each ticker's newest whole chain:
  once all its parts are in it replaces the older one, which is never sent again. The sweep runs on
  one thread on the daemon's one Schwab client (§1), one request at a time, by the option markets
  Schwab's /markets sends (`ChainSweep.chain_due`, `time_et.options_open`; a day Schwab says is
  closed is outside every window): inside its option windows, to the last close (IND, 16:15 ET, when the options on the exchanges' 4:15 p.m. list, SPY's, QQQ's and IWM's among them, stop too; Schwab's EQO
  window ends at 16:00 and has no window of its own for them; the exchanges' rule, not a
  decision of ours: `docs/SOURCES.md` cboe-rule-5-1 and nasdaq-options-hours). While one is
  open (and while today's answer, or a ticker before its first chain, is not known) the
  ticker is fetched in one rotation with every other such watchlist ticker, sorted, without end;
  a ticker a page has selected is fetched, with all its quotes, before each other ticker's chain,
  never twice in a row (`ChainSweep.rotation`; operator 2026-11-11: the ticker on the screen
  first, replacing his 2026-10-06 "no priority: every ticker is treated the same, in one
  rotation"; `tests/test_data_path_rules_v1.py`). At a start the ticker on a page has its own
  price history and then its chain before the other tickers' candles; every other ticker's
  price history is still asked before the first other chain (operator 2026-11-13, on the wait
  for levels after a start: "this is too long and needs investigation and repair end to end";
  measured that day: 40 s of price history and /markets requests went before the first
  chain); a ticker added is in the next rotation, and one removed is not asked for again, its
  queued quotes included. Schwab's /chains answers (the listed contracts, their terms and open
  interest, which Schwab says is the prior trading day's:
  `docs/schwab/schwab_support_emails_2026_10_12.txt`, item 5; measured 2026-11-11, it changed
  on 0 of 62,181 contracts between the day's first and last capture) are asked for at most every
  five minutes, at any hour (`CHAINS_AGAIN_SEC`; operator 2026-11-12: "every five
  minutes should do"), and each chain begun within that time takes them
  again as sent and asks only for its Greeks and quotes (`ChainSweep.fetch_chain`,
  `tests/test_chain_history_v1.py`); a chain that begins a capture window, the close's among
  them, asks for them, so each stored capture is a new answer. An
  exchange may add an option series during the trading day (`docs/SOURCES.md`,
  occ-listing-procedures-plan), so a contract listed during the session is seen within five
  minutes. After that market's close (and on a weekend, a holiday, and when the
  daemon starts while it is closed) the ticker is fetched once more, its close values (one added
  then too); a fetch that fails is tried again in the next pass. A ticker whose expiration chain
  lists nothing has no option market: its chain is asked once per ET date, only to learn whether
  options are listed (operator 2026-10-08). Then no chain is requested
  until its market opens again: the close values stand (D5), and a ticker not on the watchlist is not fetched — it shows
  its levels absent with the reason (`server.terrain_staleness`, the one levels verdict every
  screen shows, `levels_state`: once the ticker's own option market has closed (its
  `time_et.option_close_product`: stock options at 16:00 ET, index-close options at 16:15),
  After-Hours included, levels from a chain fetched after that close are its close values and read
  CLOSE, with their time and age, however old (operator 2026-10-25); older ones read STALE, "this
  ticker's options are closed and its close values have not been fetched"; inside the option windows,
  after the day's first round, until its market closes, LIVE until two of the sweep's rounds pass without its chain, then STALE; NOT LIVE when
  Schwab's /markets answer for today is not held), never a zero or a
  value from elsewhere. Enforced by: `tests/test_data_path_rules_v1.py` (the D5 sweep and
  staleness tests). Each ticker's chain is asked for as Schwab documents it: its expiration chain
  (`/expirationchain`) once per ET date, then `/chains` once per listed expiry (fromDate = toDate
  = the expiry, `range=ALL`; an expiry that has passed is not asked for: a past fromDate is
  refused with 400), as Schwab says to break up a large chain (Schwab Trader API Support,
  2026-10-06, `docs/schwab/schwab_support_emails_2026_10_06.txt`). Every request is logged once,
  when answered: endpoint, symbol, status, the times it was sent and answered
  (`schwab_client.log_request`). No throttle, pace, limit, gate or priority of ours sits between
  Schwab and the screen (operator 2026-10-06): an answer other than 200, or none, fails that
  ticker's chain with the reason and the next request goes at once. One exception (operator
  2026-10-15, the refused sign-in): once Schwab refuses the sign-in, nothing is sent until a new
  one is saved (§1, `OneRefreshSession`, `ChainSweep.waits`); the refusal and what to run ride the
  daemon's status (`chains_waiting`) to the levels' stale reason on every screen
  (`server._levels_state`; `tests/test_data_path_sign_in_v1.py`). Enforced by:
  `tests/test_data_path_rest_one_connection_v1.py` (the requests, one at a time on one
  connection, quotes across tickers, no pause after a 429, a 429 on an expiry asked once more) and `tests/test_data_path_rules_v1.py`
  (`test_a_403_from_schwabs_edge_reaches_the_console_and_the_next_ticker_is_asked_at_once`, on
  Schwab's captured 403 page). The chain is always the full chain, every expiry and
  every strike: measured on the 38 tickers' 2026-10-01 close captures, leaving out the
  farthest expiry changed a level (a wall, the flip, max pain) on 4 tickers, the two farthest on
  25, and 5 strikes off each side on 9. Every ticker's publication keeps its chain and its
  heatmap, so a ticker put on screen shows at once. A ticker removed from the watchlist keeps
  its last levels in the console, stale, until the console restarts. Owner:
  the daemon (`run_chains`, started with it); when it stops or its socket to the console drops,
  every ticker's levels go stale with that reason (`terrain_staleness`, judged against two of
  the sweep's delivered rounds, carried on the heartbeat). The first chain of each ticker whose
  fetch began in a capture window is also written to the chain history (§4.2, `capture_slot`), in
  one transaction before the console hears of the chain (operator 2026-11-01), so a read on its
  arrival finds that capture, whole (`tests/test_data_path_capture_whole_v1.py`); a
  stored capture is never replaced (a second write of its ticker, expiry and time is refused,
  `test_a_stored_chain_capture_is_never_overwritten_by_a_second_write_of_its_key`); a
  history write that fails (that refusal included) is a write failure, never the chain's: the
  chain as the sweep delivered it (when it began, each expiry's underlying price, the chain's spot
  and the contracts) is handed to
  the daemon's writer, which keeps it in `stream_write_failures` and counts it on its state (§2
  D4); the delivered chain stands, and the window's next chain, if any, tries again. The sweep
  (`ChainSweep.fetch_chain`, `send_quotes`) is the one place a chain enters, so every consumer
  (levels, walls, flip, the heatmap, per-strike rows, forces, the chain ladder, Strike Detail,
  the captures) reads the Greeks it sets. Each contract's fields are read once, by
  `option_contract.read_contract` (rule 2 for each: -999, text and NaN are no value; a -999
  volatility leaves the contract's Greeks no value), where the chain arrives: a fetched chain once,
  on the sweep's thread as it is put on the bus (`complete_chain_capture.chain_messages`), so the
  console's pricing (`_price_chain`) and the daemon's option rule (`Daemon._took_chain`) both take
  that one read; a stored capture by its loader `last_capture_per_day`; every calculator, the
  carry rules, the gamma surface and the chain panel (`option_contract.chain_row`) take the
  record. Enforced by: `tests/test_canonical_gex_input_validity_v1.py`, `tools/check_one_reader.py`,
  `tests/test_stream_reader_keeps_up_v1.py` (a delivered chain read once, for both). The Greeks (gamma, delta, theta, vega, rho,
  volatility) are never the chain's: the chain sends them rounded, which Schwab cannot change
  (Schwab Trader API Support, 2026-10-06; measured 2026-10-01, SPY 261120C00875000: chain gamma
  0.0, quote gamma 0.00037225; on SPY's 2026-11-20 column 86 of 221 cells with open interest
  read $0 GEX on the chain's gamma). Operator, 2026-10-01: "use what schwab gives us... no
  rounding, use the exact data that schwab gives us everywhere". What Schwab pushes is taken
  from the push and never asked for again; REST is asked only for what the stream does not send
  (operator 2026-11-05; Schwab Streamer API §1.1 and §1.5: LEVELONE_OPTIONS is delivered on
  Change). A contract whose LEVELONE_OPTIONS record on the daemon's bus
  (`Daemon.option_record`) carries all six as values (`option_contract.streamed_greeks`, the one
  reader of those stream fields) takes the stream's, each with its field's Schwab time
  (`greeksTime`, {field: ms}), and is not asked for on `/quotes`. A contract's Greeks are one
  set, never some from the stream and some from `/quotes`
  (`option_contract.streamed_greek_set`). An option record
  ends with its hold: the daemon forgets it when Schwab drops the contract or the connection
  ends (`Daemon.disconnect`), so the next hold starts from what Schwab sends then. Every other
  contract (one the stream does not hold: past the limit Schwab stated, or not yet answered) is
  asked for
  on `/quotes`, comma-separated, 300 to a request across tickers (`QUOTES_BATCH_MAX`, Schwab
  Trader API Support 2026-10-06: not more than 300), and takes its quote's, as sent (its
  `greeksTime` is None). Each `/quotes` answer goes to the console at once, as Schwab sent it,
  with the time the daemon received it (topic `optquotes`, `state.push_rest_quotes`).
  Enforced by:
  `tests/test_data_path_rest_one_connection_v1.py` (a contract the stream holds is not asked
  for on `/quotes`; each answer reaches the bus as sent with its receive time).
  Outside that ticker's option window — after it has ended, and before the next one opens; a
  day Schwab says is closed is outside every window (`time_et.option_market_open`) — the close
  values are the balance until the next open (operator 2026-11-09: "upon market close (when the
  bank closes) that is the balance until the bank opens again, post market, pre market, etc."):
  the first chain begun at or after that ticker's close, the one this process published or the
  ticker's newest capture stored after the close (`server._publish_levels`), priced as Schwab
  sent it. A reported 0 is 0 in them, Schwab's no-value code and a missing count are no value,
  and no earlier count or greek is carried in. Nothing Schwab sends after them replaces them: no
  later chain, and no pushed value (no reprice, no streamed value over the chain; the chain panel
  shows the contracts as the levels priced them). Until the close values are held, a chain is
  priced as sent; one begun inside the window keeps its reported zero even when it is priced
  after the close. During the window, Schwab's no-value code is not a greek and a count of zero
  is the count. Enforced by: `tests/test_data_path_confluence_v1.py`
  (`test_the_close_values_stand_until_the_next_open`,
  `test_a_close_capture_of_zeros_is_the_balance_not_the_capture_before_it`,
  `test_a_streamed_zero_before_the_next_open_does_not_replace_the_capture`) and
  `tests/test_data_path_served_verdicts_v1.py` (Sunday's chain on Schwab's captured answer). A
  chain is published once all its quotes are in. A quotes request Schwab refuses
  fails every chain in it with its status and reason, so the levels keep their last good
  publication, stale with that reason. A contract missing from an answered request has no Greeks (None, logged with the count), never the
  chain's: its leg's exposure and its strike's net read absent (a leg's sum is known only when
  every contract on it sent its open interest and multiplier, and every one with open interest
  above 0 sent the Greek: `bucket_metric`). A contract with open interest 0 adds 0 whatever its
  Greeks (Schwab sends -999 Greeks for a contract that has not traded): a strike listing only
  such contracts is a computed 0, drawn "$0" (operator 2026-10-01: "shouldn't be a dash should be
  0"; SPY 2026-10-14 had 121 such strikes drawn "—"). Open interest stays the chain's. Chain captures stored before 2026-10-01 carry the chain's rounded
  Greeks; the startup load prices them until newer captures exist. Counted on the stored
  chains (2026-10-06): 44 tickers, 917 expiries, 182,437 contracts, 629 quotes requests at
  300 — about 1,546 requests a rotation. The request rate and rotation time on the live watchlist
  are unmeasured (`ACTIVE_PROGRAM.md` SPEED).
- **Levels** (walls, flip, GEX, vanna, charm, max pain, PCR). Computed by the console from the
  chain in memory + spot → console memory → the browser reads no
  route for them: the program sends the levels themselves on `/ws` (`server.terrain`, the
  `terrain` panel, one per reader: `terrain:levels` Key Levels, `terrain:chart` the Gamma chart,
  `terrain:desk` Right Now, `terrain:map` the Desk map; marked changed by `server._levels_changed`
  wherever the `levels` push is). Not stored; at startup they are computed from the
  newest chain capture of each watchlist ticker the daemon has not yet delivered a chain for (once the
  daemon's heartbeat says what the watchlist is), queued on the pricing thread behind the delivered
  chains while the console
  already serves the page (each ticker's levels appear as they are priced). The values read from the stored captures (forces: ΔOI, DEX and
  charm by side; the prior day's per-strike rows) are computed by the same producer, each capture at its own time or at that ticker's option
  close once the capture is past it, only when the ticker's newest capture or its chain's day changes; the forces panel (`server.forces`) and the strikes panel
  (`server.strikes`, on `/ws`, one per reader in its own window: `strikes:gbs` GEX by Strike,
  `strikes:chart` the Gamma chart's profile, `strikes:migration` Right Now, `strikes:desk` the
  Desk map) serve that result and read no stored chain. The same publication carries each
  strike's net DEX $ and total OI (`terrain_engine._per_strike_measure_rows`, by the heatmap
  cell's readers), sent as the strikes panel's `measures` for the Chart view of Delta / DEX and Open
  Interest. The book's values at spot (gamma at spot, regime, posture, confidence, headline) are
  computed in that one publication at that publication's price; the terrain panel sends them as
  published and recomputes none. Each relation of the live price to the levels is served beside
  them, at the live price (below).
  A publication carries the same fields whatever its chain's source (a live download or a stored
  capture). The terrain panel adds the daily, weekly and monthly ATR(14) when it is read (`server._atr`):
  the daily from Schwab's daily candles before today and today's candle as Schwab pushes it; the
  weekly and monthly from Schwab's own weekly and monthly candles, as sent (operator 2026-11-12:
  "we should not be calculating anything that schwab sends us"), so the current week and month
  are as of Schwab's newest answer, asked once per ET date and after the close. The day-over-day
  open-interest change has one producer: the forces, from the stored captures (the forces panel,
  shown on the Trade Desk). Fewer than two market days of captures leaves each forces number
  absent (`server._forces_from_captures`), and a charm, DEX, ΔOI, GEX or volume side with a strike not known, or no strike at all, leaves that side
  absent (enforced by `tests/test_data_path_charm_side_unknown_v1.py` and `tests/test_data_path_side_volume_v1.py`); the screen draws "-". ΔOI is a side's total on the newer day less its total on the older day, both cut at the newer price: a strike a whole chain does not list holds no contracts that day, and the card names the older day. An ATR that cannot be computed is absent (`server._atr_fields`); the
  screen draws "-". None of these rules names a ticker; the
  watchlist decides which tickers are fetched and priced. Every tick of a ticker (an
  equity quote, a LEVELONE_OPTIONS message of one of its contracts carrying a Greek or its
  volume, `streaming._REPRICE_FIELDS`, or a `/quotes` answer for one of its contracts) queues a
  reprice of that ticker on the pricing thread while a page shows it (`live_ui.selected`). A
  ticker no page shows is priced by each chain the daemon delivers, with every value Schwab has
  pushed since, and repriced at once when a page selects it (`server.ticker_selected`, called by
  the page socket's subscribe). Operator 2026-11-10: "yes i like this fix.", replacing the
  2026-11-06 reprice of every ticker on every tick, which put 60% of the program's samples in
  pricing on the one thread and the levels on screen 10 to 16 s behind (py-spy, production,
  2026-11-10 10:58 CT). The ticks that arrive while one waits or runs are all in the next.
  A ticker's ticks queue at most one reprice a second (`server.REPRICE_EVERY_SEC`, the operator's
  setting, 2026-11-12: "Yes, once a second"; repricing on every tick took 38% of the program's
  samples and left a round of the watchlist at about 5 minutes): the first tick after a second
  queues it at once, and one that comes sooner sets the ticker's one timer for the rest of it,
  so the newest values are priced when it ends (`server._reprice_from_tick`).
  Enforced by: `tests/test_instant_ui_blockers_a_v1.py::test_a_tick_queues_a_reprice_only_for_a_ticker_a_page_shows`,
  `test_a_tickers_ticks_queue_one_reprice_a_second_and_the_last_tick_is_not_lost` there,
  `tests/test_one_levels_producer_v1.py::test_a_push_on_a_ticker_no_page_shows_is_priced_with_its_next_chain`
  and `tests/test_data_path_silent_price_v1.py::test_a_page_selecting_a_ticker_queues_its_reprice_and_its_ticks_end_with_the_page`.
  Every pricing runs at the job's own instant (`server._price_waiting_chain`), so the daemon's
  newest beat judges which of its contracts stream; it is pushed to the page the moment it
  changes, and the next beat stamps the new heatmap (`server.restamp_open_surfaces`). Enforced by:
  `tests/test_data_path_live_status_v1.py` (a push's reprice keeps a held contract live; the beat
  after a new surface stamps it). A streamed contract's Greeks and volatility are the stream's newest once the stream
  holds all six, else the chain's (`math_exposure_core.overlay_streamed_contract_fields`); its
  volume, bid and ask are the stream's: the chain as delivered and as stored carries them as
  the stream held them when the chain was complete (`ChainSweep.take_greeks`,
  `option_contract.streamed_top`, `streamed_volume`), so the close values and a stored capture
  hold a quote for every contract, and the console lays the newest over while the option market
  is open. A contract the stream does not hold takes its newest
  `/quotes` answer received since its chain began, the moment it arrives; an answer received
  before the chain began is older than the chain's own values and is not laid over it
  (`state.rest_quotes`). The levels' time (`levels_ts_utc`, served as `levels_time_ct` and the
  age) is the newest Schwab option value in them: the chain, a value pushed since, or a
  `/quotes` answer received since (its receive time); their
  verdict is judged on the chain's own time (`computed_ts_utc`), so a chain that stops arriving
  still turns them stale (enforced by `tests/test_rest_quotes_reach_the_levels_v1.py`). A viewed
  ticker is one an open page shows (the ticker its socket subscribes, `live_ui.selected`, on any
  workspace). Which page opened last decides nothing. With the daemon not reporting (no
  current heartbeat), no ticker reads "warming": its reason says first that the daemon is not
  reporting, then any other reason (no levels yet, stale levels). A viewed ticker on the
  watchlist reads "warming" until its first chain is priced; any other reads that it is not on
  the watchlist.
  Levels older
  than two of the sweep's delivered rounds are stale with the reason (the daemon's last answer
  for its chain, or not delivered), whatever the hour.
  Its `spot` is the price the levels were computed at (`spot_source`, `spot_as_of_ts_utc`): for a
  delivered chain, the chain's one spot, Schwab's LAST_PRICE with its trade time as the daemon's
  price row (`live_price_rows.price_row`) holds it when the chain's last quote is in
  (`ChainSweep.deliver`). The chain carries it to the console (`chain_messages`) and to the chain
  history. A reprice of the kept chain is at the live price (`resolve_spot`, operator 2026-11-06,
  replacing 2026-10-23's one spot per chain), or at the price the levels were last computed at
  while Schwab has sent this program none; a capture stored without the chain's spot has no
  price (the underlyingPrice of its /chains answers is recorded with it and read by nothing:
  the stream's LAST_PRICE is the price's one source, operator 2026-11-10: "we only have one
  producer, one source"; `tests/test_data_path_chain_spot_v1.py`). No panel serves that price, which no page read (operator 2026-11-12: "Yes, remove it"); every panel serves `spot`
  as the live price (`resolve_spot`), one meaning on every panel (`tests/test_page_one_faucet_v1.py`
  checks every GET route that answers a ticker and every page panel that serves a price). Every relation of the price to the levels is at
  that live price, computed when served, never stored with the publication: each wall's state
  and lean, the price's side of the flip and the pin candidate
  (`terrain_engine.price_relations`, a `PriceRelations` record, on the terrain panel, the levels panel
  and the chart's markers; the read's advice sentences, which no page read, are no longer made:
  operator 2026-11-13, "if they do not then proceed with your recommendation"). The flip's note
  (`flip_note`, `terrain_read.flip_note`: the flip's modelled curve and Schwab's gamma disagree
  on the sign at the chain's price) is published with the levels and drawn beside the flip on
  Right Now, the desk map's Options card and Key Levels (`tests/test_gamma_as_sent_v1.py`); each level's distance (level minus price), side and the words for
  both (`from_spot_text`, "1.30 below spot") on the levels panel, sent again with each price row
  of its ticker, the one distance the desk's nearest
  level and its Walls line print (each wall with its own side of the price; the line was
  labelled "Box", which a put wall above the price or both walls on one strike is not); the price inside, above or below each liquidity zone
  (`terrain_read.within`); and the level crosses (below). One side rule, exact values:
  `terrain_read.level_side` (ABOVE, AT, BELOW), with `price_side` (the price's side of a level),
  `within` and `crossed` built on it (`tests/test_level_crosses_wire.py`,
  `tests/test_trade_desk_served_v1.py`). Each answer serving them (the terrain panel, the levels panel,
  the confluence panel) serves the price's mark beside them (`server.price_mark`: whether Schwab's
  feed delivers the price, why not, its trade time and age, and the words the page prints,
  `spot_not_live_text`, "not live · last trade Thu 10/22 03:39 PM CT, 81m old", from the one age
  formatter `time_et.age_text`); the levels panel puts it on the pin candidate's row too
  (`not_live_text`). When the price stops, every relation stands, marked with it: the desk's wall
  labels, GAMMA cell, pin candidate, nearest level and Walls line, and the confluence screen's spot.
  While the price stays stopped, the levels loop tells each open page on that ticker to read
  again every minute (`server.refresh_not_live_pages`, its owner `server._terrain_loop`; when that
  loop stops, the age stays as of the page's last read and the trade time beside it stays true),
  so the age keeps counting
  (`tests/test_level_crosses_wire.py::test_relations_from_a_stopped_price_stand_marked_not_live_with_its_time_and_age`,
  `test_a_page_whose_price_has_stopped_is_told_each_minute_to_read_its_levels_again`;
  `tests/e2e/console-trade-desk.spec.js` and `tests/e2e/console-confluence.spec.js` render the
  routes' own answers, `tests/fixtures/real_spy_levels_at_a_stopped_price_2026_10_22.json` and
  `tests/fixtures/real_spy_confluence_at_a_stopped_price_2026_10_22.json`, kept equal to them by
  `test_the_stopped_price_answers_the_browser_renders_are_the_routes_own`). The one-day move's two prices are the live price
  plus and minus the publication's implied move (`server.expected_move`, the one producer;
  the levels panel and the confluence panel carry it). A chain delivered with no spot (the daemon held no
  price) has no levels, with its reason.
- **Heatmap cells.** Every strike Schwab listed in any expiry is a row; a cell is the book's
  value for its strike and expiry, exact. A cell with no value (no contract listed at that strike
  in that expiry, or Schwab sent nothing for it) is served as None, with no reason, and the page
  draws "-" (operator 2026-10-12). The surface is served whenever the levels projected one; no
  count of cells withholds it.
- **Strike windows.** Every per-strike panel (the heatmap, GEX by strike, the chart's profiles,
  vanna, charm, the migration, the confluence matrix at Auto) shows the window the server sends: `terrain_engine.strike_window`
  picks the scope's strikes (Auto 11, Wider 23, All every one) around the strike nearest the
  live price, or around the strike the operator panned to (`centre`, moved `shift` rows by a
  drag), and each answer carries its `view`: the centre, the largest |value| drawn (the bar and
  colour scale) and `note`: with no live price and no pan the rows are the middle of the chain,
  and the note says so (`WINDOW_NO_PRICE`, drawn on the panel; no row is marked as the price).
  The confluence matrix takes only the rows and the note, which it serves among its `notes`; its
  colours stay on the whole expiry's scale, its `peaks` (`docs/derived_register.md` Heat color).
  The heatmap is the `surface` panel on `/ws` (`server.gamma_surface`, its window the page's
  parameters: scope, centre, shift, `cols` and `expiry`, each sent, null for none), marked
  changed wherever the `levels` push is (`server._levels_changed`).
  The heatmap's view (`server._surface_view`) also picks the columns (the selected expiry
  alone; for Auto the nearest unexpired the page fits, `cols`; Wider twice that; All every one;
  an expired column is a past observation, drawn labelled EXPIRED, and with none unexpired Auto
  draws the expired ones so labelled), marks the row at the price and the front column, names a
  selected expiry the surface lacks (`missing_expiry`: nothing drawn), and counts the unexpired cells drawn
  that are streaming (`_stream_coverage`): the header chip's words, ALL STREAMING only when every
  one is, N% STREAMING (the share rounded down; "<1%" under one), EXPIRED (every column drawn has
  expired) or WARMING, with a one-line tooltip. The page is served the words for each cell's and
  column's streaming state (meta `ed-stream-words`, `server.STREAM_WORDS`) and the scopes and
  their words (meta `ed-scopes`); the volume profile serves its scale (`max_volume`). Each cell
  shows the number of the newest publication the page read; no cell flashes (operator: the
  moving number is the signal). The page sends the scope, its pan and the columns it fits; it
  picks, counts and compares nothing.
- **Live.** Every value is the last one Schwab sent, with Schwab's own time (the price with its
  TRADE_TIME, `trade_time_ct`), under §2 D5 (today's outage blanking: §3.5 item 5). Whether
  the feed is delivering a symbol now is stated beside its values: the
  daemon's heartbeat, sent every second, is not older than 3 s at the time judged
  (`live_market_plane.FEED_HEARTBEAT_MAX_AGE_SEC`), says the Schwab socket is open, and holds the
  symbol on that Schwab service, and its market trades (`live_market_plane.live_state`; the
  header's LIVE / OFFLINE / NOT LIVE, a book's `book_live`, a heatmap leg's and a gamma cell's
  state). An option contract is live inside Schwab's option windows (`time_et.options_open`).
  Only the daemon holds Schwab's
  SECURITY_STATUS, so the console carries the daemon's verdict (`streaming.price_state`, for a
  symbol's quote and for a venue's equity book): the one rule on that service while it is not
  LIVE (the feed down, the symbol not held, its market not trading); while it is LIVE, the
  quote's own state, the same verdict the daemon's price row carries (`live_price_rows.price_row`).
  The levels, the chain and the heatmap carry the levels verdict
  (`server.terrain_staleness`, §3.4's chain sweep: LIVE / CLOSE / STALE / NOT LIVE with the
  chain's time and age, its age kept counting by `server.refresh_not_live_pages` while it is not
  LIVE), and Key Levels its mark (`server.levels_mark`: the levels' word, or the price's while
  the levels are LIVE). A value's age is never the test: Schwab sends a
  field only when it changes. The daemon's status is read from the same heartbeat
  (`live_market_plane.daemon_status`). Owner: the daemon's beat (`live_ui`, every
  `HEARTBEAT_SEC`), in the same program; the console's bus reader yields after each record, so a
  backlog of chain parts never holds the beat. When Schwab's socket closes or the beat stops,
  every symbol reads feed down within 3 s; the last price row stands, marked not live. The
  contracts that beat last named keep their last streamed greeks on the levels; those cells are
  not live. The last watchlist stands; the page says the daemon is not reporting.
- **Tape.** The cumulative delta (PROXY, tick rule) sums every print the tape holds; no clock
  resets it, and the window it sums (its first and last print's Schwab trade time,
  `cum_delta_window`) is served beside it and printed with it. A print of size 0 adds 0.
  The options tape (`server.tape`) lists the newest trade first by Schwab's own trade time
  (`TRADE_TIME_MILLIS`), not by when a message arrived (operator 2026-11-12: "yes we should use
  schwab's data", after SPY's tape showed trades of 08:55 and 08:30 above trades of 15:14); a
  print Schwab sent no trade time with comes after every one that has one. A contract's first
  streamed message carries its last trade, made before the program was watching; it is a tape
  row with Schwab's trade time, so after a restart the tape shows the last trades (operator
  2026-11-12, asked whether to keep or drop it: "your recommendation.", which was to keep it).
  Enforced by: `tests/test_options_flow_tape_v1.py` (the put's messages received after calls
  that traded later; the call's first message, traded before it was received, is one row).
- **Level crosses.** Four levels are watched, each under its name in the one list of option
  levels (`server.CROSS_LEVELS`, drawn from `terrain_engine.OPTION_LEVELS`; operator 2026-11-13:
  "if we have all kinds of levels and we consider all levels important then no level is really
  important", the choice left to the research): the gamma flip, where the regime changes
  (`docs/SOURCES.md` baltussen-2021); the call and put walls, the range the industry reads
  (modelled: squeezemetrics-gex-2017); and the largest gamma strike, the pin
  (ni-pearson-poteshman-2005). The net gamma peaks and max pain (no source, or one not
  verified) and the delta walls (no study of a price reaction; a wall can sit on a strike far
  in the money) are not watched; the charm walls matter on an expiration day, where the
  same-day pin already stands. A cross stored before this keeps the name it was written with.
  Found by the console at the live price on each streamed equity quote
  (`server._on_stream_tick`, on the event loop, the owner): each of those levels the price
  reached or passed going from the ticker's previous streamed price to this one
  (`server._last_tick_spot`, kept on every equity quote, since the price row holds only the
  newest; `terrain_read.crossed`, the one side rule). No quote, no check; a new publication moves
  the levels, not the price, and is not a cross. Stored on the pricing thread as `LevelCrossEvent`
  records (`server._log_level_crosses`, `EdDB.record_level_crosses`): every cross of every
  watched level, one row per level, as it happened, with nothing held back (operator
  2026-11-13: "we take what we get from schwab, and we record what happens", "why put in an
  interpreter when one is not needed"; the 60-second hold that left a repeated cross out of the
  record is deleted; `tests/test_level_crosses_wire.py`); a ticker's held crosses are read from
  `ed_console.db` once, the first time they are needed. A failed store
  is logged, and that cross is not held or stored. Written to `ed_console.db`
  and kept in the console's memory (§3.3) → the desk panel (`server.desk`), sent after the cross is
  held, which serves
  each cross as recorded, from memory, and flags the
  newest cross at each level, for the newest six levels, as the chart's numbered callouts (one
  served item is both a callout and its queue entry). The window is the timeframe's
  (`server.DESK_LOOKBACK`; 5m and 30m: this session). No proximity alerts. Absorption,
  liquidity pull and replenishment are not produced (open; `ACTIVE_PROGRAM.md` DESK-GAPS).
- **Market session.** Schwab's GET /markets?markets=equity,option, asked by the daemon's chain
  sweep (`ChainSweep.fetch_markets`) once per date per ET day -- today, the 7 days before it
  Schwab answers, and each expiry date of the chains inside the year Schwab answers
  (`markets_last_day`, a calendar year; a later expiry is not asked until it is inside it, and its date stays
  unknown), whatever the number of tickers -- each answer
  as sent → daemon bus (`markets.DATE`) → the daemon's writer (`stream_capture.db`
  `stream_markets_raw`, every answer with its status) and → console (the daemon's bus) → `time_et.record_markets`
  (a 200 is that date's sessions; a 400, such as "more than 7 days back", is no session: the date
  stays unknown). At startup, before its loops and the feed, the console reads the recorded 200
  answers (`server._load_stored_sessions`, `tests/test_data_path_stored_sessions_v1.py`), as a
  stored chain's expiries reach it before the daemon's answers do. A stream database that cannot
  be read stops the console's start with its error. The label (`time_et.session_label`: Pre-Market, RTH, After-Hours,
  Closed, Unknown) is sent on `/ws` with the daemon's status, every beat (`feed.session`). The same answers decide every session window: the prior-day, overnight, VWAP and
  value-area windows (the regular session), the Trade Desk's "this session" window
  (`time_et.last_open`), the chain history's capture windows (the option markets, to the last close), and
  each contract's time to expiry (the EQO regular close of its expiry date, or its open for
  settlementType "A": Schwab's expirationDate is not the settlement, an AM-settled $SPX monthly
  carries 16:00 ET). On an expiry date with no /markets answer held, a PM-settled contract runs to
  Schwab's own expirationDate as sent (operator 2026-10-08), and an AM-settled one does past the
  year /markets answers (operator 2026-10-31, asked which to use: "Use Schwab's date"; up to 6.5
  hours past its open); nearer, its settlement may have passed and it has no time to expiry until
  Schwab's expirationDate passes. Past that a contract has settled. No
  hand-typed
  holiday, early-close or covered-year table exists. A day with no session has an empty window.
  The label decides the live word (§2 D5): no session window starts, stops or clears a streamed value (stock
  quotes from 04:00 ET are shown and recorded), and the order-flow state keeps every book,
  top-of-book field, print and streamed Greek through the open. Enforced by:
  `tests/test_markets_sessions_v1.py`, `tests/test_data_path_charm_side_unknown_v1.py`.
- **Lifecycle.** The page's socket (`/ws`, `live_ui.LiveUiServer`): the levels producer, the
  stream handler (equity quote and book) and the bar writer mark a ticker's panels changed
  (`live_ui.changed`); each page showing one is sent it again at once. The socket down:
  the page's session label reads `—` with its reason and no panel changes until the page
  reconnects and subscribes again, when every panel it shows is sent at once. A Trade Desk
  timeframe switch subscribes that timeframe's bars, levels and desk panels.

### 3.5 Where today breaks the design

1. **Two copies of live state** (daemon memory and console memory) for books, option quotes and
   the equity tape; the live price is one row (the daemon's). Each remaining copy and duplicate
   computation is a row in `ACTIVE_PROGRAM.md` (ONE-*), with its behavior test when fixed.
2. **Two writers and two databases** (the daemon's and the console's).
3. **The console computes the levels** in the same process that serves the page, so a request
   waits behind that work.
4. **The browser reads a route after each push** for bars, order flow, liquidity and the levels,
   instead of receiving the values; bars are not yet on the daemon's push.
5. **Values blank when they stop** (D5, operator 2026-10-11): the price row keeps the last
   values and the header says OFFLINE (`live_price_rows.price_row`, the page's feed chip). The
   age line keeps that price's last trade time (`static/js/ed-core.js`). The key levels
   spot carries that same time and the header's state, and clears on a ticker switch (`#klSpot`,
   painted by the header's `static/js/ed-core.js`). The chain ladder's spot carries it too
   (`server.get_chain`, the chain head). The trade desk's spot carries it too
   (`server.levels_payload`, the Right Now line). The levels page's spot carries it too
   (`static/js/ed-gamma-levels.js`). The gamma chart's spot and its live price line carry it too
   (`static/js/ed-gamma-chart.js`). The desk map's index prices and its VIX row carry it
   too, and an offline order-flow card keeps it beside the outage
   (`static/js/ed-trade-desk-map.js`). The liquidity map's live price line carries it too
   (`static/js/ed-liquidity-map.js`). The desk chart's live price line carries it too
   (`static/js/ed-trade-desk-map.js`). The desk map's BOOK pill keeps the book's time beside
   that age, and its liquidity card keeps each book's last numbers, greyed, with the book's time
   and that it is not live (`server.liquidity_readout`, `static/js/ed-trade-desk-map.js`). The Right Now
   book-age row keeps that same time (`static/js/ed-trade-desk.js`). The desk map's
   options card, volatility card, and GAMMA pill keep the chain's time beside that
   age (`server.get_terrain`, `static/js/ed-trade-desk-map.js`). The key levels
   keep the last wall when that price has stopped, and the rail says that price's served state
   (`levels_mark`, from `price_state`) beside the chain's time (`server.terrain`, `#klSrc`, `static/js/ed-gamma-panels.js`); the chain's own verdict stays `levels_state`. The
   GEX-by-strike badge keeps that same time beside its age (`server.terrain_strikes_payload`, `#gbsSrc`). The
   gamma chart's GEX badge keeps it too (`static/js/ed-gamma-chart.js`). The desk map's
   LEVELS pill keeps the snapshot's time beside that age (`server.levels_payload`,
   `static/js/ed-trade-desk-map.js`). The levels glance shows each price with the
   time the payload already carries for it (`server.levels_payload`,
   `static/js/ed-gamma-levels.js`). The
   book's top keeps the last bid and ask, and that panel says its served state (`top_feed_label`
   beside `top_outage`); the book badge says the book's (`book_feed_label`).
   The book's quote time and book time stay on that panel (`server.order_flow_microstructure`,
   `static/js/ed-order-flow.js`). The Flow panel keeps the contract's quote time and book time
   (`server.options_microstructure`, `static/js/ed-gamma-flow.js`). A contract
   the daemon stops holding keeps its last quote; the Flow panel marks it NOT STREAMED. A missing
   heartbeat keeps that last subscription, and the panel says OFFLINE; a held contract whose option
   market is closed says NOT LIVE (`streaming.get_option_contract_streaming_diagnostics`, the Flow
   badge). A missing
   heartbeat keeps the last streamed greeks on the levels; the cells are not live. A feed
   down while the market is closed keeps the last price and the book, and that panel says
   OFFLINE (`live_market_plane.outage`). A strike's session volume and open interest keep
   every digit Schwab sent (`terrain_engine._per_strike_rows`,
   `_per_strike_measure_rows`), and so do the volume sums below and above spot
   (`server.terrain_strikes_payload`), and so does the book's top size
   (`app.options.order_flow.engine._extract_canonical_book`), and so does a tape print's
   size (`l1_trade_observation.extract_vendor_print`); the screen rounds those counts
   for display. The last trade Schwab streams (LAST_PRICE, LAST_SIZE, TRADE_TIME_MILLIS) has
   one reader, `l1_trade_observation.last_print`: the price row (`live_market_plane`) and the
   tape both take the three fields from it, a stock's and an option contract's alike
   (operator 2026-11-13: "this currently violates the one producer, one faucet rule",
   "whatever faucet we get water from then we need to keep getting from that faucet";
   `tests/test_last_print_one_reader_v1.py`). Still
   blank: levels fetched before the option close are marked apart from a feed stop
   (`server.terrain_staleness`); some calculations still drop
   contracts. The §3 descriptions of these are today's behavior. Each remaining place is
   listed in PR #515's description and fixed by `ACTIVE_PROGRAM.md` NUMBERS.
6. **Missing values served with a reason** (D5, operator 2026-10-12: a missing value shows "-";
   operator 2026-10-16: one producer, the number or nothing). An ATR that cannot be computed, a
   same-day absolute-gamma strike with no same-day book, the forces before two capture days and
   a forces side (charm, DEX, ΔOI) with a strike not known or no strike at all are absent (`server._atr_fields`, `terrain_engine.compute_terrain`,
   `server._forces_from_captures`; the forces side by `tests/test_data_path_charm_side_unknown_v1.py`); the screen draws "-". The levels with no price and the
   outage words are still served with their reason (§3 above). The gamma heatmap's cells draw "-".

The work that closes these gaps, in order, is `ACTIVE_PROGRAM.md`.

## 4. The target, in the one program (§1)

### 4.1 Where each part runs

| Part | Runs on | Why |
|---|---|---|
| **Feed** | the program's event loop (the Schwab stream) and one thread (the REST chain sweep, one request at a time) | the stream must read every frame as it comes |
| **Calculators** | one pricing thread the program owns (`server._chain_pricing`), never the event loop: the levels and their heatmap's stream states (`server.restamp_off_the_loop`, each surface restamped only when its own contracts' hold, the socket or the option market changes), and the option rule's ladders and order of a chain (`strike_ladders`, `shown_first`); a fetched chain is read once, on the chain sweep's thread (`chain_messages`) | heavy computing ON the event loop stalls it, and a stalled loop stops answering Schwab's stream; the console's loop did stall this way (2026-09-24, per-tick repricing; 2026-10-02, chain-part decoding on the loop, gone with the socket; 2026-11-09, the heatmap restamp and the option rule's chain read on the loop, up to 80% and 58% of it in 10-s windows, the reader 17.97 s behind Schwab, `tests/test_stream_reader_keeps_up_v1.py`). Feed and Push never wait on a calculation: it is handed off, and its result returns to State as its own update. The pool was measured in step 3 (2026-11-05: an event loop ticking every 10 ms while every watchlist ticker's newest stored chain, every expiry, SPY's 12,890 contracts among them, is priced back to back; read_chain, compute_terrain and the gamma surface): idle, the loop's lag p50 5.6 ms, p99 19 ms, max 50 ms; on the one thread, all 10 in 14.0 s, p50 20.7 ms, p99 64 ms, max 224 ms; in a process pool sent the raw chain, 11.3 s, p50 5.6 ms, p99 54 ms, max 203 ms; in a process pool sent the read chain, 17.1 s, p50 5.9 ms, p99 119 ms, max 309 ms. Handing a chain to another process costs the interpreter as much as pricing it, so a process pool does not lower the worst wait; the one thread keeps it near 0.2 s, far inside the 1 s beat and Schwab's 30 s silence limit, and adds no code |
| **State** | the event loop | one writer of each value, read by Push and the Recorder |
| **Push** | the event loop | a snapshot on connect, then every change |
| **Recorder** | its own thread (the writer) | the page never waits on a database |
| **Page** | the browser | one WebSocket; it draws what is pushed, with no refresh timer and no route reads |

### 4.2 The journey of each kind of data

- **Quote, option quote, book, bar:** Schwab → Feed → State → pushed to the page; written by the
  Recorder.
- **Chain:** Schwab REST, fetched by Feed → State → Calculators → State. The page is never pushed a
  whole chain.
- **Chain history:** in each capture window of the option markets as Schwab's /markets sent them
  -- every 30 minutes from their open, and at the last close (the close capture: 16:15 ET, 13:15
  on an early close) -- the Recorder
  writes the first full chain (every expiry) Feed begins of each watchlist ticker, compressed, one
  row per expiry, into `ed_console.db`. Nothing is captured outside those windows. This is what
  research reads and what startup loads (the newest capture per ticker).
- **Levels:** Calculators → State → pushed to the page; not stored (decision 7).
- **Level crosses:** Calculators → State → written by the Recorder.
- **After a restart, a weekend or the close:** at startup the Recorder's loader reads the recorded
  /markets answers, the newest stored chain per ticker and the bars once, the levels are computed from them once, and the
  screens show them with their time.

## 5. Checks

The rules and the tool that enforces each are `AGENTS.md` "Rules and what enforces them". Today:
ruff at commit and in CI, with `pyproject.toml`'s one selection (unused imports, undefined names,
syntax errors, the UP rules but UP042, whose only fix is unsafe, the W rules, S110, a catch-all `except` (bare, `Exception` or `BaseException`) passed in silence, BLE, a catch-all `except` that neither records its traceback nor re-raises, TID251, the banned names (the one clock: `time_et.py` alone reads the computer's clock),
the E rules but E711, E712 and E731, whose only fix is unsafe: E402, imports at the top, E501, lines at most 100 columns, E741, no `l`, `O` or `I` as a name; the B rules but those whose only fix is unsafe; I, import order, and the SIM rules with a safe fix or with no fix and nothing to fix), and `ruff format` (the one Python formatter, ruff pinned in `requirements-dev.txt`);
a compile pass in CI (every file CPython compiles); the behavior tests (`pytest`, `tests/`) and the
browser tests (Playwright, `tests/e2e/`) in CI; the secrets and home-path scan at commit and in CI
(every tracked file, and each commit of a pull request, merge resolutions included); the line-ending check at commit and
in CI (the pull request's change); for agents, the hooks that block destructive git. A passing check proves only what its tests exercise; every rule beyond
them stays NOT_PROVEN.

A gap gets a check only when a failure it would have caught has happened; the check is a test of
behavior (AGENTS.md).

## 6. Operator decisions (enforced)

1. **The daemon fetches the option chain.** Schwab's stream has no chain service; the contract
   list and open interest come only from Schwab's REST chain endpoint. Built 2026-10-01: the
   daemon is the only Schwab client; every watchlist ticker is fetched in its turn, none first.
   Enforced by: `tests/test_schwab_client_import_boundary.py`.
2. **The levels producer runs in its own process**, not inside the daemon. Superseded by SHAPE
   (operator 2026-10-29): the Calculators run in a worker pool the one program owns, off its event
   loop (§4.1). Enforced by: not built — SHAPE step 3.
3. **The browser is never pushed a whole chain.** Enforced by: no machine check — ENF-16.
4. **One shell, two connections** (operator 2026-09-27). One page; tabs switch what is shown;
   the daemon pushes prices and bars, the console pushes that levels, flow or liquidity changed.
   Superseded by SHAPE (operator 2026-10-29): one shell, one WebSocket from the one program, which
   carries every value (§1). Enforced by: no machine check — SHAPE step 4.
5. **Two databases, each with one job** (operator 2026-10-09/10): `stream_capture.db`, the
   daemon's writer, five sessions (§2 D4); `ed_console.db`, the chain history (decision 7, written
   by the daemon's chain sweep) and the level crosses (the console's one write today; under SHAPE
   (operator 2026-10-29) the Recorder writes both databases and nothing else does, P2-DB5). The stored chain is the chain history of decision 7,
   not every 5-second chain; no table without a job.
   Enforced by: not built (the console still writes its level crosses) — ENF-16.
6. **Before any table is dropped:** each table's size is measured read-only; dropping needs the
   operator's explicit word (no backup copies are kept, operator 2026-10-10); reclaiming space (VACUUM) is an offline
   maintenance window, never part of a code change. Enforced by: deleting or moving the database
   files is refused by the agent hook `tools/operator_law_guard.py`
   (`tests/test_protected_paths_v1.py`); starting the console's database (`EdDB`) leaves every
   schema object and row it finds, shown on a database holding the three tables it used to drop
   (`tests/test_data_path_tables_stand_v1.py`); any other table drop — ENF-16.
7. **Chain history is kept for research.** Schwab's API has no past option chains: a chain not
   saved is gone. One table holds it (§4.2): full chain, every 30 minutes, market hours only,
   compressed, with Schwab's own underlying price of each expiry as sent and the chain's one spot
   (`chain_spot`, `chain_spot_ts`). Levels are not stored as history; research
   runs the one levels producer over the stored chains, so research and the screen are one
   computation. After the close, the levels are that producer run on the newest capture, with
   the capture's price and time (operator 2026-09-26; a weekend chain blanks open interest).
   The morning table (no writer or reader) folds into this table or is dropped, on the
   operator's word (P2-DB3). Enforced by: `tests/test_chain_history_v1.py`.
8. **A panel scales its bars to what is visible** (operator 2026-09-28, ONE-16). Fitting bar
   lengths to the largest value in the visible strike window is drawing, like fitting a chart
   axis: the server does not know the pan position. The panel draws the server's values
   unchanged; the visible maximum is never shown as a number, never a market metric, and never
   alters a displayed value. Enforced by: no machine check — ENF-16.
9. **No trade side** (operator 2026-09-28, ONE-12). Schwab supplies no aggressor side, so no
   inferred buy/sell side (tick rule, quote rule) is computed or shown as order flow.
   Enforced by: no machine check — ENF-16.
10. **Same-day levels, every ticker** (operator 2026-10-17; 2026-11-09: "schwab does not have a
    0DTE field that is one we compute ... we must have one producer at the source to compute all
    levels for all tickers on a 0dte basis"). One producer (`terrain_engine.same_day_levels`): the
    whole book's own producers read on the nearest listed expiry alone. An expiry listed today is
    read as the book holds it: Schwab's gamma and delta as sent, its flip, GSF and GRC from its
    gamma profile, its charm walls from its charm map. With none listed today, the next listed
    expiry keeps its open interest and implied volatility, and its gamma and delta are rebuilt as
    if it expired at today's option close (`math_levels.repriced_to_close`): Black-Scholes-Merton
    with the chain's own rate and dividend yield as sent (`interestRate`, `dividendYield`; never
    the stock stream's Dividend Yield, another field), at the time every other greek uses
    (`time_to_expiry_years`, including its 10-minute floor) from the valuation instant to that
    close; its gamma profile and charm are priced at that same time. A contract with open
    interest whose gamma is not known (not sent, or it cannot be rebuilt) leaves its side and that
    strike's total unknown, as in the whole book; the other side's known value still ranks
    (operator 2026-10-31: "you're guide is how would a financial banking app work"). Charm follows
    the same rule, in both books, and a strike whose contracts all have open interest 0 is 0 on
    the charm map (`math_levels.compute_charm_by_strike`, its one producer; operator 2026-11-11:
    "Yes, move it"). The close is the regular window Schwab's /markets sent: the
    index window for an index it names with "$" and for every symbol on the exchanges' 4:15 p.m.
    ET list, the equity-option window for every other ticker (the exchanges keep designated ETF
    options open to 4:15 p.m. ET: `docs/SOURCES.md` cboe-rule-5-1, and nasdaq-options-hours for
    the 65 symbols, which `time_et._INDEX_CLOSE_UNDERLYINGS` holds; operator 2026-11-13: "yes
    you should bring the program 4:15 list to the exchanges full list"). After that close the levels stand as priced at it, a later expiry's at
    the 10-minute floor, until the next open (the close values, §3.4). A later expiry's levels are
    absent where a chain is priced on a day with no option window held (a weekend or a holiday
    with no close values held, or Schwab's /markets answer for today not held); every ticker's are
    when the chain lists no expiry from today on. The whole-book levels are unchanged.
    The 0DTE pin is `same_day.absolute_gamma_strike` only. The listed-expiry pin
    (`zero_dte_abs_gamma_strike`) is not produced: it was a second pin.
    One name for each level on every screen (operator 2026-11-13: "make sure they all follow
    the same nomenclature. if you are going to use the greek symbols then do that where
    applicable"): the name `terrain_engine.OPTION_LEVELS` gives it, in sentence case, with Γ
    for gamma and Δ for delta wherever a level's name holds one (Γ flip, Abs Γ, Net call Γ
    peak, Key Δ strike, Call Δ wall); charm has no letter, and the call and put walls keep the
    industry's name. The Key Levels card, the Levels tab, the Gamma chart, Right Now, the desk
    map, the chart markers and the cross alerts print that name; a tag in capitals is that
    name, capitalised by its style. Enforced by: `tests/test_level_names_one_list_v1.py`,
    which reads every page file and refuses a level name typed differently from the list's
    (operator 2026-11-13, asked whether to add that check: "Yes, add it").
    The key levels rail draws each strike once, the regular price beside the same-day
    price. Spot has no same-day cell. Its lines are chosen by what published work supports
    (operator 2026-11-13: "only include those that are most important", "what is included is
    based on your research"; "include the delta and charm walls"; `docs/SOURCES.md`): the
    gamma flip, as the line where the regime changes (baltussen-2021); the call and put
    walls (the industry's convention, modelled: squeezemetrics-gex-2017); the largest gamma
    strike, the pin (ni-pearson-poteshman-2005, at expiration); the call and put delta
    walls and the call and put charm walls, on his order (charm at expiration:
    golez-jackwerth-2012; the delta walls are the strikes with the most call and the most put
    delta exposure, a published measure, flashalpha-dex, under a name of the program's own;
    a strike far in the money holds a delta near 1, so one can be the wall: AMD's and TSLA's
    call delta wall read 5.00 on 2026-11-13, AMD's $5 strike holding $2.6 billion of delta),
    each on the same-day basis too, as every level of the one list is
    (`terrain_engine.OPTION_LEVELS`; operator 2026-11-13: "we need to ensure that we have 0dte
    levels as well just as we have on the key levels card an the levels tab"); then the price levels, each the `levels` panel's own row
    (`levels:kl`): the expected move up and down, the prior day's high, low and close
    (osler-2000) and VWAP. The net call and net put gamma peaks are off the rail: no source
    was found for either. A support or resistance line is not on it: on 88 ticker-days of
    Schwab's one-minute candles none of the program's levels stopped the price clearly more
    often than an arbitrary price (osler-2000's test; 7 days a ticker is too few), so none
    is proven. Exposure (net GEX, the two put/call ratios, the dealer regime) stays under
    those rows. Zero Gamma, Volatility Trigger, Vanna Support
    and Charm Resistance are not on the rail: nothing is served for them.
    The levels list is one table, Level, Regular, 0DTE, same-day rows first, then the
    other served levels. Family, evidence and source are not drawn. Each price is shown
    with the time the server sent for it.
    Enforced by: `tests/test_data_path_same_day_levels_v1.py`,
    `tests/test_data_path_charm_side_unknown_v1.py`.
