# Ed Console — Data Flow

How data moves from Schwab to the screen: the processes, how they talk, where data lives, and the
journey of each kind of data. The design was agreed by the operator on 2026-09-23 ("Instant UI");
the decisions of 2026-09-26 are in §6. Where the code lives is `docs/ARCHITECTURE.md`. Every change
is built to this document and checked against it; a change that does not fit stops and goes to the
operator.

## 1. The agreed design

```
[Schwab] ─ one WebSocket ─► [Capture daemon: in-memory state] ─ push ─► [Browser]
                                        │
                              queue (never blocks the push)
                                        ▼
                             [The one database writer] ─► [Database: history]
```

- One Schwab connection, owned by the daemon (Schwab allows one streamer connection per user).
- Data is pushed at every hop. Nothing polls.
- The database is history, written in the background by one writer. Nothing on screen waits on it.
- At startup the in-memory state is loaded once from the latest stored values, so a restart, a
  weekend or the close shows the last reading with its time.

## 2. The rules

`AGENTS.md` § Rules. One copy; it loads with every agent session.

## 3. Today (measured 2026-09-26)

### 3.1 The processes

| Process | Started by | What it does |
|---|---|---|
| **Capture daemon** | `start_capture_daemon.bat` (its own window, restarts itself) | Holds the one Schwab WebSocket. Subscribes to what the console asks for. Every Schwab message goes once onto its in-memory message bus, and from there to three places: its database writer, the console, and the browser's price socket. Keeps the latest equity quote per symbol in memory to build the price row the browser shows. Every 30 minutes of the session it downloads the full chain of each board ticker and writes it to the chain history in `ed_console.db` (decision 7). |
| **Console** | `start_ed_console.bat` (`uvicorn server:app`, port 8000) | Receives the daemon's messages into its own in-memory copy of the live state. Downloads full option chains from Schwab over REST, computes the levels every 5 s for the tickers on the board and being viewed, and keeps them in memory. Writes the 1-minute bars, level crosses and daily OI/IV to its own database. Serves the page and every `/api` route. Tells the daemon what to subscribe. |
| **Browser** | the operator | Loads one page from the console. Gets prices pushed from the daemon; gets a "levels changed" signal pushed from the console; reads everything else from the console's `/api` routes. |

### 3.2 How they talk

| From → to | Channel | What travels |
|---|---|---|
| Schwab → daemon | Schwab's streamer WebSocket | equity quotes, option quotes, both order books, 1-minute bars, news — the fields that changed |
| daemon → console | local WebSocket 127.0.0.1:8799 | every Schwab message as sent; on connect, the current state first |
| console → daemon | same socket | the "wanted" list: every symbol per Schwab service |
| daemon → browser | local WebSocket :8800 | the finished price row per symbol, on every change, plus a heartbeat every second |
| Schwab → console | Schwab REST | full option chains; one quote at startup to validate the login |
| console → browser | HTTP `/api/*` | everything else, on request |
| console → browser | Server-Sent Events | "levels for this ticker were just published" |

### 3.3 Where data lives

| Place | Owner | What it holds |
|---|---|---|
| Daemon memory | daemon | the message bus; the latest equity quote per symbol (for the browser's price row) |
| Console memory | console | a second copy of the live quotes and books (fed from 8799); the downloaded chains; the computed levels |
| `stream_capture.db` (21.8 GB) | daemon's writer | every raw Schwab message: quotes, books, option quotes, bars, news, subscription answers |
| `ed_console.db` (77.0 GB) | console | 1-minute bars, level crosses, daily OI and IV, the ticker board, chain captures (22.2 GB) and a morning chain per ticker (2.7 GB) — plus about 49 GB of tables of the deleted ML pipeline |

### 3.4 The journey of each kind of data

- **Equity quote.** Schwab → daemon bus → (a) daemon writer → `stream_capture.db`; (b) daemon's
  price row → browser socket → header and watchlist; (c) console socket → console memory → the
  spot the levels use. Pushed end to end.
- **Option quote and order book.** Schwab → daemon bus → writer, and → console memory → the
  order-flow and heatmap routes → browser, **read on a timer**.
- **1-minute bar.** Schwab → daemon bus → writer (`stream_capture.db`), and → console → the
  console's own bar writer → `ed_console.db` → `/api/bars1m` → browser, **read on a timer**. The
  forming candle rides the price row.
- **Option chain.** Schwab REST → console memory, downloaded by the console every 5 s per board or
  viewed ticker. Separately the daemon stores the full chain on the §4.2 schedule (#312).
- **Levels** (walls, flip, GEX, vanna, charm, max pain, PCR). Computed by the console from the
  chain in memory + spot → console memory → a push signal → the browser reads `/api/terrain` and
  four other slice routes. Not stored; at startup and after the close they are computed from the
  newest chain capture (#312).
- **Alerts and level crosses.** Computed by the console at each levels publish; crosses written to
  `ed_console.db` → `/api/alerts` → browser.
- **Market session.** From the market calendar → `/api/session`, read at load and at each change.

### 3.5 Where today breaks the design

1. **Two copies of live state** (daemon memory and console memory).
2. **Two writers and two databases** (the daemon's and the console's).
3. **The console talks to Schwab** (REST chains) — the daemon should own every Schwab call.
4. **The console computes the levels** in the same process that serves the page.
5. **The browser polls** for bars, order flow, liquidity and the levels themselves.
6. **The standalone pages compute values** in their inline scripts (`static/chart.html`,
   `static/exposure.html`): P2-4. The console's page scripts compute none (the 64
   sites inventoried 2026-09-27 moved to the server, P1-3; the Chain view's grouping and sort, P2-4).

## 4. The target

### 4.1 The processes

| Process | What it does |
|---|---|
| **Capture daemon** | Holds the one Schwab connection: the streamer, and the REST chain fetch. Holds the one in-memory state: latest quotes, books, bars, chains. Pushes every change. Its writer thread is the one database writer. At startup it loads the latest stored values into memory. |
| **Levels producer** | Its own process. Receives the chain and quotes from the daemon, computes each derived value once, and hands the results back to the daemon to push and write. The daemon never waits on it: it sends and moves on, and results arrive as their own message. Kept out of the daemon because heavy computing in the daemon's process stalls its event loop and Schwab drops the socket (measured 2026-09-24). |
| **Console** | Serves the page and the read routes, from the daemon's state. Computes nothing and holds no copy. |
| **Browser** | One page, one push connection. Every panel reads from what is pushed; opening the Chain view reads one expiry from the state. |

### 4.2 The journey of each kind of data

- **Quote, option quote, book, bar:** Schwab → daemon state → pushed to the browser; written by the
  one writer.
- **Chain:** Schwab REST, fetched by the daemon → daemon state → the producer. The browser is never
  pushed a whole chain.
- **Chain history:** every 30 minutes from 9:30 to 16:00 ET, and at 16:15 ET (the close capture:
  SPY, QQQ, IWM and the index options trade until 16:15) on market days (15 a day), the daemon
  writes the full chain (every expiry) of each ticker on the board, compressed, one row per expiry,
  through the one writer. Nothing is captured while the market is closed. This is what research
  reads and what startup loads (the newest capture per ticker).
- **Levels and alerts:** producer → daemon state → pushed to the browser; not stored (decision 7).
- **Level crosses:** producer → written by the one writer.
- **After a restart, a weekend or the close:** at startup the newest stored chain per ticker and the
  bars are loaded, the levels are computed from them once, and the screens show them with their
  time.

## 5. Checks (measured 2026-09-27)

What each existing check covers and what it cannot. `hardening` fails a PR only on NEW violations of
`tools/check_institutional_correctness.py` (62 stand on main). A scan that finds one named producer
does not prove no second one exists under another name.

| Rule | Check | Covers | Does not cover |
|---|---|---|---|
| Schwab as sent | `vendor_field_coercion` (`tools/check_vendor_field_coercion.py`) | every chain, quote and stream numeric field read only through `schwab_number` / `schwab_count`: any other converter or local delegate on one fails | bar fields (`open`/`high`/`low`/`close`/`volume` share names with internal rows); a bound applied after the reader |
| One producer | `one_producer` (`governance/computation_registry.json`) | 9 registered fields (net GEX, DEX, delta, gamma, vanna, charm at a strike; strike OI and volume totals; the price levels), each found at exactly its producer (measured 2026-09-27) | a duplicate under other names (the 2026-09-27 heatmap `c + p`); a semantic duplicate such as two gamma sources; the 338 fields `server.py` serves that are not registered |
| One producer: spot | `single_spot_authority` | spot read only through `resolve_spot` in `server.py`, `terrain_engine.py` | page scripts |
| One producer: levels | `domain_faucet_registry`, `phase2a_single_level_computation`, `chain_width_single_faucet` | level routes registered; price levels computed once; the chain not narrowed | exposure values outside the levels list |
| UI computes nothing | `single_faucet_provenance` (`tools/data_faucet_audit.py`, `PAGE_CALCULATIONS`) | spot reads in `static/chart.html`; sums, weighted sums, distance to spot, sort by distance, calendar arithmetic, first-key picks in every `static/js/` script | a threshold or comparison that picks a label; the standalone pages' inline scripts |
| No fallbacks | `no_fake_defaults`, `absence_has_a_type`, `no_silent_swallow` | default literals, absent-as-value return types, swallowed exceptions | a branch that picks a second source |
| One path, no polling | none | | page timers that read `/api` |
| One writer | `single_stream_authority`, `collect_window_single_law` | one Schwab stream; the 1-minute bar write seam | other writes outside the one writer |
| Nothing without a job | `level_producers_have_consumers` (reported, not blocking) | a level route has a page consumer | unused code, routes, tables, timers |
| Real data | `test_hygiene` | inline synthetic option contracts in tests | other hand-built test inputs |
| Documents match the tree | `tests/test_governing_docs_v1.py` | every path the four governing documents name exists; `AGENTS.md` under 200 lines | whether a statement is true |

A gap gets a check only when a failure it would have caught has happened (ACTIVE_PROGRAM names each).

## 6. Operator decisions (2026-09-26)

1. **The daemon fetches the option chain.** Schwab's stream has no chain service; the contract
   list and open interest come only from Schwab's REST chain endpoint.
2. **The levels producer runs in its own process**, not inside the daemon.
3. **The browser is never pushed a whole chain.**
4. **One shell, one connection.** One page; tabs switch what is shown; one push connection.
5. **One database, written only by the daemon's writer; the console reads it read-only.** The
   one database is `ed_console.db` (operator 2026-09-26: the chain history is already there);
   the stream tables move into it, and the console's writes today (bars, level crosses, daily
   OI/IV, the ticker board) move to the daemon's writer. Until then the daemon writes the chain
   history into `ed_console.db` while the console writes its own tables there. The stored chain is the chain history of decision 7, not every 5-second
   chain; no table without a job (no alerts table — alerts are derived and expire).
6. **Before any table is dropped:** each table's size is measured read-only; dropping needs a
   verified copy or the operator's explicit word; reclaiming space (VACUUM) is an offline
   maintenance window, never part of a code change.
7. **Chain history is kept for research.** Schwab's API has no past option chains: a chain not
   saved is gone. One table holds it (§4.2): full chain, every 30 minutes, market hours only,
   compressed, with Schwab's own underlying price. Levels are not stored as history; research
   runs the one levels producer over the stored chains, so research and the screen are one
   computation. After the close, the levels are that producer run on the newest capture, with
   the capture's price and time (operator 2026-09-26; a weekend chain blanks open interest).
   The morning table folds into this table (P2-DB3).

The work that closes the gaps in §3.5, in order, is `ACTIVE_PROGRAM.md`.
