#!/usr/bin/env python3
"""CR-01 capture daemon: Schwab Streamer -> bus -> stream_capture.db. CAPTURE-ONLY.

Consensus plan v1.2: this process owns the ONLY Schwab stream (single-streamer-owner
rule) and writes ONLY stream_capture.db.

SINGLE-STREAM-AUTHORITY (root-fixed 2026-08-30): order_flow_streaming.py — the live UI's
book/L1 feed — now reads these rows read-only instead of opening its own StreamClient.
This process additionally captures NASDAQ_BOOK / NYSE_BOOK for the one symbol the server
signals as the active UI viewer's ticker (stream_active_ticker.json, polled every ~1s by
_active_ticker_book_poll_loop), and stores the native content dict for quotes alongside
the flattened columns (see stream_spine.quote_msg's `native` field) so a downstream reader
needing field fidelity does not have to re-derive a lossy approximation.

Acceptance instrumentation built in (measured, not asserted):
  - JSON-handle latency p50/p99, per-service message counts, bus drop counters,
    max writer-queue depth, rows/commits — printed at exit and written every 10s to
    reports/stream_capture_status.json (the operator-visible heartbeat).
  - First raw message per service saved to reports/stream_raw_sample_<svc>.json.
    Field maps are NAMED-KEY, verified live 2026-07-21 against those samples (the
    original numeric maps parsed all-None and were caught by this exact mechanism).

Usage:
    python tools/run_stream_capture.py --symbols SPY,QQQ,IWM --duration-min 390
"""

from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from stream_spine import (  # noqa: E402
    COALESCE,
    COUNT_DROPS,
    CaptureWriter,
    HealthRegistry,
    MessageBus,
    bar_msg,
    book_msg,
    print_msg,
    quote_msg,
    read_active_ticker_signal,
)

STATUS_PATH = ROOT / "reports" / "stream_capture_status.json"
OWNER_LOCK = ROOT / "data" / "stream_capture.lock"


def acquire_owner_lock() -> int:
    """ENFORCE the single-streamer-owner rule (Cursor review HIGH: it was prose only).

    Exclusive pidfile: a second daemon refuses to start; a stale lock (dead pid) is
    reclaimed. The formerly-known conflict — server.py's order_flow_streaming opening a
    SECOND independent Schwab stream — is root-fixed (2026-08-30): that module now reads
    this daemon's stream_capture.db read-only and opens no Schwab session of its own
    (tools/check_single_stream_authority.py enforces PRODUCTION_SCHWAB_STREAMCLIENT_
    CONSTRUCTORS == 1, this file being the one). This lock now guards the ONLY remaining
    way to violate single-streamer-owner: two copies of THIS daemon.
    """
    import os
    for attempt in (1, 2):
        try:
            fd = os.open(str(OWNER_LOCK), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(fd, str(os.getpid()).encode())
            return fd
        except FileExistsError:
            try:
                pid = int(OWNER_LOCK.read_text().strip() or 0)
            except (OSError, ValueError):
                pid = 0
            alive = False
            if pid:
                try:
                    import psutil
                    alive = psutil.pid_exists(pid)
                except ImportError:
                    alive = True   # can't verify -> fail closed, require manual removal
            if alive:
                raise SystemExit(
                    f"FATAL: another stream-capture owner holds {OWNER_LOCK} (pid {pid}). "
                    "Single-streamer-owner rule: stop it first, or remove a stale lock."
                ) from None
            if attempt == 1:
                OWNER_LOCK.unlink(missing_ok=True)   # stale (dead pid): reclaim once
    raise SystemExit(f"FATAL: could not acquire {OWNER_LOCK}")


def release_owner_lock(fd: int) -> None:
    import os
    try:
        os.close(fd)
    finally:
        OWNER_LOCK.unlink(missing_ok=True)

#: VERIFIED live 2026-07-21 against reports/stream_raw_sample_levelone_equities.json:
#: this schwab-py install labels fields by NAME (numeric map parsed all-None — caught by
#: the raw-sample check on first connection, as designed).
LEVELONE_FIELDS = {"BID_PRICE": "bid", "ASK_PRICE": "ask", "LAST_PRICE": "last",
                   "BID_SIZE": "bid_size", "ASK_SIZE": "ask_size",
                   "TOTAL_VOLUME": "total_volume", "LAST_SIZE": "last_size",
                   "QUOTE_TIME_MILLIS": "quote_time_ms", "TRADE_TIME_MILLIS": "trade_time_ms"}
CHART_FIELDS = {"OPEN_PRICE": "open", "HIGH_PRICE": "high", "LOW_PRICE": "low",
                "CLOSE_PRICE": "close", "VOLUME": "volume", "CHART_TIME_MILLIS": "bar_start_ms"}


def parse_stream_item(item: dict, field_map: dict[str, str]) -> dict:
    """Numeric-keyed streamer item -> named dict; 'key' carries the symbol."""
    out: dict = {"symbol": str(item.get("key") or "").upper()}
    for k, name in field_map.items():
        if k in item:
            out[name] = item[k]
    return out


# ── CR-02: Alpaca IEX prints + NBBO quotes (capture half) ────────────────────
# Schwab's streamer REFUSES trade prints — proven live 2026-07-22 by differential
# probe on one authenticated session: LEVELONE_EQUITIES SUBS -> code 0 "SUBS command
# succeeded"; TIMESALE_EQUITY SUBS (identical framing via schwab-py _make_request)
# -> code 11 "Service not available or temporary down." Alpaca's free IEX websocket
# supplies real executions (verified same day: REST latest trade + WS auth OK with
# the operator's paper keys). This leg records RAW prints and RAW NBBO quotes into
# stream_capture.db via the same bus/writer; SIGNING is computed by the CR-02
# correlation study, never here (capture stays raw). Optional by design: no keys ->
# one printed line, Schwab capture unaffected.
ALPACA_WS_URL = "wss://stream.data.alpaca.markets/v2/iex"
ALPACA_ENV_PATH = ROOT / ".env"
#: IEX slice scale, MEASURED on-roster 2026-07-22: SPY IEX daily volume 1,223,790 vs
#: Schwab consolidated TOTAL_VOLUME 24,067,157 (~5.1%). Coverage is a sample, not the
#: tape — the pre-registered CR-02 study decides whether the sample is trustworthy.
ALPACA_SRC = "alpaca_iex"

# ── half-open-socket guard (2026-07-23, observed live) ───────────────────────
# A network blip left BOTH websockets half-open: connected on paper, silent in
# practice. No error ever fires on a half-open TCP socket, so error-driven
# reconnect logic never triggers — the feeds sat STALE for minutes while the
# process looked healthy (py-spy: event loop idle at _poll). Staleness itself
# must therefore force the reconnect.
ALPACA_STALE_RECONNECT_SEC = 120.0   #: no frames this long -> recycle the socket
STREAM_STALE_RECONNECT_SEC = 90.0    #: LEVELONE quiet this long -> recycle stream
RECONNECT_COOLDOWN_SEC = 180.0       #: never login-spam Schwab on quiet tape


def stream_needs_recycle(age_sec: float | None, seen_data: bool,
                         since_last_reconnect: float) -> bool:
    """Half-open-guard decision (pure; unit-tested). Recycle ONLY when:
    data has flowed before (a never-beat service is a subscribe problem, not a
    half-open socket), the feed has been quiet past the stale bar, and the
    cooldown has passed (quiet after-hours tape must not cycle logins)."""
    if age_sec is None or not seen_data:
        return False
    return (age_sec > STREAM_STALE_RECONNECT_SEC
            and since_last_reconnect > RECONNECT_COOLDOWN_SEC)


def alpaca_keys_from_env() -> tuple[str, str] | None:
    """Paper keys from .env (ALPACA_API_KEY_ID / ALPACA_API_SECRET_KEY) or process env.

    Values are never logged. Missing keys are a SKIP, not an error — the Schwab
    capture must never be hostage to the optional prints leg."""
    kv: dict[str, str] = {}
    try:
        for line in ALPACA_ENV_PATH.read_text(encoding="utf-8-sig").splitlines():
            s = line.strip()
            if not s or s.startswith("#") or "=" not in s:
                continue
            k, _, v = s.partition("=")
            kv[k.strip()] = v.strip().strip('"').strip("'")
    except OSError:
        pass
    import os
    kid = kv.get("ALPACA_API_KEY_ID") or os.environ.get("ALPACA_API_KEY_ID")
    sec = kv.get("ALPACA_API_SECRET_KEY") or os.environ.get("ALPACA_API_SECRET_KEY")
    return (kid, sec) if kid and sec else None


def alpaca_rfc3339_to_ms(t) -> int | None:
    """Alpaca timestamps are RFC-3339 with NANOSECOND fractions (9 digits) —
    datetime.fromisoformat accepts at most 6, so the fraction is trimmed. Capture
    stores milliseconds (matches stream schema *_ms columns)."""
    if not t or not isinstance(t, str):
        return None
    from datetime import datetime
    s = t.rstrip("Z")
    if "." in s:
        head, frac = s.split(".", 1)
        s = f"{head}.{frac[:6]}"
    try:
        return int(datetime.fromisoformat(s + "+00:00").timestamp() * 1000)
    except ValueError:
        return None


#: Alpaca stream field dictionary (schema verified live 2026-07-22 with the operator's
#: keys — see the roster snapshot + docs). NAMED here once, the same single-source
#: discipline as LEVELONE_FIELDS/CHART_FIELDS above and the Schwab field CSV.
ALPACA_TYPE_KEY = "T"      #: message type: "t" trade, "q" NBBO quote, control/bars other
ALPACA_SYMBOL_KEY = "S"
ALPACA_STAMP_KEY = "t"     #: RFC-3339 with NANOSECOND fraction
ALPACA_TRADE_FIELDS = {"p": "price", "s": "size", "x": "exchange", "c": "conditions",
                       "i": "trade_id", "z": "tape"}
#: `bs`/`as` are ROUND LOTS per Alpaca's schema — recorded AS GIVEN; src
#: distinguishes them from Schwab's share-denominated sizes (no raw-layer conversion).
ALPACA_QUOTE_FIELDS = {"bp": "bid", "ap": "ask", "bs": "bid_size", "as": "ask_size",
                       "bx": "bid_exchange", "ax": "ask_exchange", "z": "tape"}


def alpaca_item_to_topic_msg(item: dict) -> tuple[str, dict] | None:
    """One Alpaca stream item -> (topic, spine message) or None for non-capture types.

    Trades -> print.SYM; NBBO -> quote.SYM. Bars/status/control frames return None:
    canonical 1m bars remain Schwab's (sole-bar-authority law); statuses are a later,
    separately-argued addition.
    """
    kind = item.get(ALPACA_TYPE_KEY)
    sym = str(item.get(ALPACA_SYMBOL_KEY) or "").upper()
    if not sym:
        return None
    if kind == "t":
        f = parse_stream_item({**item, "key": sym}, ALPACA_TRADE_FIELDS)
        conds = f.get("conditions")
        return (f"print.{sym}", print_msg(
            symbol=sym, price=f.get("price"), size=f.get("size"),
            exchange=f.get("exchange"),
            conditions=",".join(str(x) for x in conds) if isinstance(conds, list) else conds,
            trade_ts_ms=alpaca_rfc3339_to_ms(item.get(ALPACA_STAMP_KEY)), src=ALPACA_SRC))
    if kind == "q":
        f = parse_stream_item({**item, "key": sym}, ALPACA_QUOTE_FIELDS)
        return (f"quote.{sym}", quote_msg(
            symbol=sym, bid=f.get("bid"), ask=f.get("ask"),
            bid_size=f.get("bid_size"), ask_size=f.get("ask_size"),
            quote_time_ms=alpaca_rfc3339_to_ms(item.get(ALPACA_STAMP_KEY)), src=ALPACA_SRC))
    return None


def alpaca_handle_frame(raw: str, bus: MessageBus, health: HealthRegistry,
                        stats: CaptureStats) -> None:
    """One websocket frame (JSON array of items) -> bus publishes + health beats."""
    t0 = time.perf_counter()
    frame = json.loads(raw)
    items = frame if isinstance(frame, list) else [frame]
    for item in items:
        if not isinstance(item, dict):
            continue
        if item.get(ALPACA_TYPE_KEY) == "error":
            print(f"alpaca: stream error frame: {item}")
            continue
        out = alpaca_item_to_topic_msg(item)
        if out is None:
            continue
        save_raw_sample(f"ALPACA_{item.get(ALPACA_TYPE_KEY)}", item, stats)
        bus.publish(out[0], out[1])
        health.beat("ALPACA_IEX")
    stats.record("ALPACA_IEX", (time.perf_counter() - t0) * 1000.0)


async def _alpaca_session(ws, symbols: list[str], kid: str, sec: str, bus: MessageBus,
                          health: HealthRegistry, stats: CaptureStats,
                          stop: asyncio.Event) -> bool:
    """Auth + subscribe + receive loop on an open socket. Returns False on auth
    refusal (permanent for this run), True when the loop ends via `stop`."""
    await asyncio.wait_for(ws.recv(), 10)              # {"T":"success","msg":"connected"}
    await ws.send(json.dumps({"action": "auth", "key": kid, "secret": sec}))
    auth = json.loads(await asyncio.wait_for(ws.recv(), 10))
    a0 = auth[0] if isinstance(auth, list) and auth else auth
    if not (isinstance(a0, dict) and a0.get(ALPACA_TYPE_KEY) == "success"):
        print(f"alpaca: auth REFUSED: {a0} — prints leg stopped for this run")
        return False
    await ws.send(json.dumps({"action": "subscribe",
                              "trades": symbols, "quotes": symbols}))
    print(f"alpaca: subscribed trades+quotes for {len(symbols)} symbols "
          f"(free tier cap 30; separate from Schwab key budget)")
    last_rx = time.monotonic()
    while not stop.is_set():
        try:
            raw = await asyncio.wait_for(ws.recv(), timeout=1.0)
        except asyncio.TimeoutError:
            # half-open guard: a dead socket raises NOTHING — quiet past the
            # bar means recycle (outer loop reconnects with fresh auth+subs)
            quiet = time.monotonic() - last_rx
            if quiet > ALPACA_STALE_RECONNECT_SEC:
                print(f"alpaca: no frames for {quiet:.0f}s — recycling socket "
                      f"(half-open guard)")
                return True
            continue
        last_rx = time.monotonic()
        alpaca_handle_frame(raw, bus, health, stats)
    return True


async def alpaca_pump(symbols: list[str], bus: MessageBus, health: HealthRegistry,
                      stats: CaptureStats, stop: asyncio.Event) -> None:
    """Hold the Alpaca IEX socket open; publish prints/quotes onto the bus.

    Reconnects with bounded backoff (5s..60s) until `stop`; every disconnect is
    printed and the feed's health state degrades honestly in the interim (a dead
    socket must never look like a quiet market — spine law)."""
    keys = alpaca_keys_from_env()
    if keys is None:
        print("alpaca: no ALPACA_API_KEY_ID/ALPACA_API_SECRET_KEY in .env — "
              "prints leg skipped (Schwab capture unaffected)")
        return
    import websockets
    kid, sec = keys
    backoff = 5.0
    while not stop.is_set():
        try:
            async with websockets.connect(ALPACA_WS_URL, open_timeout=15) as ws:
                backoff = 5.0
                if not await _alpaca_session(ws, symbols, kid, sec, bus, health,
                                             stats, stop):
                    return
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 — reconnect loop; every drop is printed
            if stop.is_set():
                return
            print(f"alpaca: connection lost ({type(exc).__name__}: {exc}) — "
                  f"reconnect in {backoff:.0f}s")
            try:
                await asyncio.wait_for(stop.wait(), timeout=backoff)
                return
            except asyncio.TimeoutError:
                backoff = min(backoff * 2, 60.0)


class CaptureStats:
    def __init__(self, sample_dir: Path | None = None) -> None:
        #: None (tests' default) = record which services were seen, write NO files.
        #: The daemon passes reports/ so live raw samples land for field-map verification.
        self.sample_dir = sample_dir
        self.handle_ms: list[float] = []
        self.per_service: dict[str, int] = {}
        self.raw_sampled: set[str] = set()

    def record(self, service: str, dur_ms: float) -> None:
        self.per_service[service] = self.per_service.get(service, 0) + 1
        if len(self.handle_ms) < 500_000:
            self.handle_ms.append(dur_ms)

    def p(self, q: float) -> float | None:
        # statistics.quantiles requires n>=2; a quiet first heartbeat must not
        # abort the capture loop (Bugbot 2026-07-21 MEDIUM).
        n = len(self.handle_ms)
        if n == 0:
            return None
        if n == 1:
            return round(self.handle_ms[0], 3)
        return round(statistics.quantiles(self.handle_ms, n=100)[int(q) - 1], 3)


def save_raw_sample(service: str, msg: dict, stats: CaptureStats) -> None:
    if service in stats.raw_sampled:
        return
    stats.raw_sampled.add(service)
    if stats.sample_dir is None:
        return
    p = stats.sample_dir / f"stream_raw_sample_{service.lower()}.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(msg, indent=2, default=str), encoding="utf-8")


def make_handler(service: str, field_map: dict, topic_kind: str, bus: MessageBus,
                 health: HealthRegistry, stats: CaptureStats):
    def handler(msg: dict) -> None:
        t0 = time.perf_counter()
        save_raw_sample(service, msg, stats)
        health.beat(service)
        for item in msg.get("content") or []:
            parsed = parse_stream_item(item, field_map)
            sym = parsed.get("symbol")
            if not sym:
                continue
            if topic_kind == "quote":
                out = quote_msg(symbol=sym, bid=parsed.get("bid"), ask=parsed.get("ask"),
                                last=parsed.get("last"), bid_size=parsed.get("bid_size"),
                                ask_size=parsed.get("ask_size"),
                                last_size=parsed.get("last_size"),
                                total_volume=parsed.get("total_volume"),
                                quote_time_ms=parsed.get("quote_time_ms"),
                                trade_time_ms=parsed.get("trade_time_ms"), src="schwab_l1",
                                # Native content item verbatim — the live-plane hydrator
                                # (daemon_plane_feed.py) needs fields the flattened
                                # columns do not carry (BID_TIME_MILLIS, REGULAR_MARKET_
                                # CHANGE_PERCENT, ...); field meaning is carried 1:1.
                                native=item)
            else:
                out = bar_msg(symbol=sym, bar_start_ms=parsed.get("bar_start_ms"),
                              open=parsed.get("open"), high=parsed.get("high"),
                              low=parsed.get("low"), close=parsed.get("close"),
                              volume=parsed.get("volume"), src="schwab_chart")
            bus.publish(f"{topic_kind}.{sym}", out)
        stats.record(service, (time.perf_counter() - t0) * 1000.0)
    return handler


def make_book_handler(service: str, bus: MessageBus, health: HealthRegistry, stats: CaptureStats):
    """NASDAQ_BOOK / NYSE_BOOK — content stored verbatim (book_msg), never flattened."""
    def handler(msg: dict) -> None:
        t0 = time.perf_counter()
        save_raw_sample(service, msg, stats)
        health.beat(service)
        for item in msg.get("content") or []:
            if not isinstance(item, dict):
                continue
            sym = str(item.get("key") or "").upper()
            if not sym:
                continue
            bus.publish(f"book.{sym}", book_msg(symbol=sym, service=service, content=item,
                                                src="schwab_book"))
        stats.record(service, (time.perf_counter() - t0) * 1000.0)
    return handler


async def _apply_active_ticker_book_subs(stream, current: str | None) -> str | None:
    """Diff the server's requested active ticker against the currently book-subscribed
    one; unsub the old, sub the new. Bounded key cost: at most ONE symbol carries book
    depth at a time (2 services x 1 symbol = 2 keys), independent of the L1/CHART roster
    size — the daemon does not re-derive Section 1's whole-roster budget problem because
    it never puts books on more than one symbol.

    Called after every (re)connect (a fresh StreamClient carries no subscriptions) and
    polled on its own fast cadence so a UI ticker switch is not held to the 10s status
    loop (SWITCH-LATENCY: server.py's prior direct-subscribe path was tuned for
    sub-second turnaround; a signal-file poll must not regress that to 10s)."""
    requested = read_active_ticker_signal()
    if requested == current:
        return current
    if current:
        try:
            await stream.nasdaq_book_unsubs([current])
            await stream.nyse_book_unsubs([current])
        except Exception as e:
            print(f"book unsub {current}: {e}")
    if requested:
        try:
            await stream.nasdaq_book_subs([requested])
            await stream.nyse_book_subs([requested])
            print(f"book subscribed active ticker -> {requested}")
        except Exception as e:
            print(f"book sub {requested}: {e}")
            return current
    return requested


async def _active_ticker_book_poll_loop(get_stream, get_current, set_current,
                                        stop: asyncio.Event,
                                        interval_sec: float = 1.0) -> None:
    """Fast poll of the active-ticker signal, independent of the 10s status/watchdog
    loop and of stream recycles (reads whatever StreamClient is current at each tick)."""
    while not stop.is_set():
        try:
            await asyncio.wait_for(stop.wait(), timeout=interval_sec)
            return
        except asyncio.TimeoutError:
            pass
        stream = get_stream()
        if stream is None:
            continue
        try:
            new_cur = await _apply_active_ticker_book_subs(stream, get_current())
            set_current(new_cur)
        except Exception as e:  # noqa: BLE001 — poll loop must survive one bad tick
            print(f"active-ticker book poll: {type(e).__name__}: {e}")


def write_status(bus: MessageBus, health: HealthRegistry, writer: CaptureWriter,
                 stats: CaptureStats, max_qdepth: int) -> None:
    STATUS_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATUS_PATH.write_text(json.dumps({
        "ts": time.time(), "health": health.report(),
        "published": bus.published, "drops": bus.drop_counts(),
        "rows_written": writer.rows_written, "commits": writer.commits,
        "insert_errors": writer.insert_errors,
        "max_writer_queue_depth": max_qdepth,
        "per_service": stats.per_service,
        "handle_ms_p50": stats.p(50), "handle_ms_p99": stats.p(99),
    }, indent=2), encoding="utf-8")


async def run(symbols: list[str], duration_min: float, db_path: str | None) -> int:
    lock_fd = acquire_owner_lock()
    try:
        return await _run_locked(symbols, duration_min, db_path)
    finally:
        # The lock's lifetime is the WHOLE session — login/subscribe failures and
        # KeyboardInterrupt included (Cursor round-2 HIGH: it leaked on init paths).
        release_owner_lock(lock_fd)


async def _shutdown_sequence(pump_task, writer_task, stop, wsub,
                             extra_producers: tuple = ()) -> None:
    """SHUTDOWN ORDER IS THE CONTRACT (Cursor round-2 HIGHs).

    1) Quiesce the PRODUCER first — after this await nothing can publish, so the
       writer's drain sees a queue that only shrinks (closes the in-flight
       pump→bus→queue loss window).
    2) THEN stop the writer with drain time sized to worst-case depth (8192 rows is
       seconds; 60s is generous) — and a timeout is REPORTED as loss, never silent.
    """
    # ALL producers quiesce together — the Alpaca leg is a producer exactly like the
    # Schwab pump, so it must be dead before the writer drain starts (same law).
    for task in (pump_task, *extra_producers):
        task.cancel()
    for task in (pump_task, *extra_producers):
        try:
            await task
        except asyncio.CancelledError:
            pass  # expected: we cancelled it
        except Exception as exc:  # noqa: BLE001 — bounded shutdown; report, never hang
            print(f"shutdown: producer ended with {type(exc).__name__}: {exc}")
    stop.set()
    try:
        await asyncio.wait_for(writer_task, timeout=60)
    except asyncio.TimeoutError:
        print(f"shutdown: WRITER DRAIN TIMED OUT — up to {wsub.queue.qsize()} "
              "queued rows may be lost (counted, not hidden)")
    except Exception as exc:  # noqa: BLE001
        print(f"shutdown: writer ended with {type(exc).__name__}: {exc}")


async def _run_locked(symbols: list[str], duration_min: float, db_path: str | None) -> int:
    from config import build_config
    from schwab_client import build_client_from_token

    cfg = build_config(str(ROOT))
    state = build_client_from_token(api_key=cfg.api_key, app_secret=cfg.app_secret,
                                    token_path=cfg.token_path)
    if not state.ok or state.client is None:
        print(f"FATAL: Schwab client init failed: {state.message}")
        return 2

    bus = MessageBus()
    health = HealthRegistry()
    stats = CaptureStats(sample_dir=ROOT / "reports")
    writer = CaptureWriter(db_path) if db_path else CaptureWriter()
    wsub = bus.subscribe("", policy=COUNT_DROPS, maxsize=8192)   # writer sees everything
    _ui_future = bus.subscribe("quote.", policy=COALESCE)        # proves coalesce path live
    stop = asyncio.Event()

    try:
        return await _run_streaming(symbols, duration_min, bus, health, stats,
                                    writer, wsub, stop, state)
    finally:
        writer.close()   # every exit path incl. login/subscribe failure (round-3 MEDIUM)


async def _schwab_connect(state, symbols, bus, health, stats, stop, active_book_ticker=None):
    """Fresh Schwab stream: login + handlers + subs -> (stream, running pump task).
    Used at start AND by the half-open watchdog (a recycle is a clean rebuild —
    never an attempt to resuscitate a dead StreamClient).

    ``active_book_ticker``: re-apply book depth for this ONE symbol immediately after
    connecting — a fresh StreamClient carries no subscriptions, so a recycle that forgot
    this would silently drop the live UI's book depth until the next poll tick noticed
    the (unchanged) signal file and there was nothing to diff against."""
    from schwab.streaming import StreamClient

    stream = StreamClient(state.client)
    await stream.login()
    stream.add_level_one_equity_handler(
        make_handler("LEVELONE_EQUITIES", LEVELONE_FIELDS, "quote", bus, health, stats))
    stream.add_chart_equity_handler(
        make_handler("CHART_EQUITY", CHART_FIELDS, "bar1m", bus, health, stats))
    stream.add_nasdaq_book_handler(make_book_handler("NASDAQ_BOOK", bus, health, stats))
    stream.add_nyse_book_handler(make_book_handler("NYSE_BOOK", bus, health, stats))
    await stream.level_one_equity_subs(symbols)
    await stream.chart_equity_subs(symbols)
    print(f"subscribed {len(symbols)} symbols x2 services (key accounting: "
          f"{len(symbols) * 2} keys used)")
    if active_book_ticker:
        try:
            await stream.nasdaq_book_subs([active_book_ticker])
            await stream.nyse_book_subs([active_book_ticker])
            print(f"book resubscribed active ticker -> {active_book_ticker} (post-reconnect)")
        except Exception as e:
            print(f"book resub {active_book_ticker} after reconnect: {e}")

    async def pump() -> None:
        while not stop.is_set():
            await stream.handle_message()

    return stream, asyncio.create_task(pump())


async def _run_streaming(symbols, duration_min, bus, health, stats,
                         writer, wsub, stop, state) -> int:
    max_qdepth = 0
    writer_task = asyncio.create_task(writer.run(wsub, stop=stop))
    #: Shared with the active-ticker book-poll task (below) — a plain dict, not a
    #: closure-captured local, because BOTH the recycle path here and the poll loop's
    #: coroutine need to read/write the SAME current values.
    book_state: dict = {"stream": None, "ticker": None}
    stream, pump_task = await _schwab_connect(state, symbols, bus, health, stats, stop)
    book_state["stream"] = stream
    # CR-02 prints leg — optional co-producer on the SAME bus/writer/health.
    alpaca_task = asyncio.create_task(alpaca_pump(symbols, bus, health, stats, stop))
    book_poll_task = asyncio.create_task(_active_ticker_book_poll_loop(
        lambda: book_state["stream"], lambda: book_state["ticker"],
        lambda t: book_state.__setitem__("ticker", t), stop))
    deadline = time.monotonic() + duration_min * 60 if duration_min > 0 else None
    last_reconnect = time.monotonic()
    try:
        while not stop.is_set():
            await asyncio.sleep(10)
            max_qdepth = max(max_qdepth, wsub.queue.qsize())
            write_status(bus, health, writer, stats, max_qdepth)
            # half-open watchdog: quiet LEVELONE past the bar -> rebuild stream
            age = (health.report().get("LEVELONE_EQUITIES") or {}).get("age_sec")
            seen = stats.per_service.get("LEVELONE_EQUITIES", 0) > 0
            if stream_needs_recycle(age, seen, time.monotonic() - last_reconnect):
                print(f"watchdog: LEVELONE_EQUITIES quiet {age:.0f}s — recycling "
                      f"Schwab stream (half-open guard)")
                last_reconnect = time.monotonic()
                book_state["stream"] = None   # poll loop must not use the dying stream
                pump_task.cancel()
                try:
                    await pump_task
                except asyncio.CancelledError:
                    pass
                except Exception as exc:  # noqa: BLE001 — recycle path; reported
                    print(f"watchdog: old pump ended with {type(exc).__name__}: {exc}")
                try:
                    stream, pump_task = await _schwab_connect(
                        state, symbols, bus, health, stats, stop,
                        active_book_ticker=book_state["ticker"])
                    book_state["stream"] = stream
                except Exception as exc:  # noqa: BLE001 — retry next tick, loudly
                    print(f"watchdog: reconnect FAILED ({type(exc).__name__}: {exc}) "
                          f"— retrying after cooldown")
                    pump_task = asyncio.create_task(asyncio.sleep(0))  # placeholder
            if deadline and time.monotonic() > deadline:
                break
    except (KeyboardInterrupt, asyncio.CancelledError):
        pass
    finally:
        await _shutdown_sequence(pump_task, writer_task, stop, wsub,
                                 extra_producers=(alpaca_task, book_poll_task))
        writer.close()
        write_status(bus, health, writer, stats, max_qdepth)
        print(json.dumps({
            "rows_written": writer.rows_written, "commits": writer.commits,
            "published": bus.published, "drops": bus.drop_counts(),
            "insert_errors": writer.insert_errors,
            "max_writer_queue_depth": max_qdepth,
            "handle_ms_p50": stats.p(50), "handle_ms_p99": stats.p(99),
            "per_service": stats.per_service, "db": str(writer.db_path),
        }, indent=2))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--symbols", default="SPY,QQQ,IWM")
    ap.add_argument("--duration-min", type=float, default=0.0, help="0 = until Ctrl+C")
    ap.add_argument("--db", default=None, help="override stream_capture.db path (tests)")
    a = ap.parse_args()
    syms = [s.strip().upper() for s in a.symbols.split(",") if s.strip()]
    return asyncio.run(run(syms, a.duration_min, a.db))


if __name__ == "__main__":
    raise SystemExit(main())
