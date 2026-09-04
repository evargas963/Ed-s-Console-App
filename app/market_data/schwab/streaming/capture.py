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
    python -m app.market_data.schwab.streaming.capture --symbols SPY,QQQ,IWM --duration-min 0
"""

from __future__ import annotations

import argparse
import asyncio
import inspect
import json
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))

from stream_spine import (  # noqa: E402
    COALESCE,
    COUNT_DROPS,
    PRODUCER_CLAIM_TTL_SEC,
    CaptureWriter,
    CoverageWriteError,
    HealthRegistry,
    MessageBus,
    bar_msg,
    book_msg,
    options_quote_msg,
    print_msg,
    quote_msg,
    read_active_option_contract_signal,
    read_active_ticker_signal,
    resolve_stream_db_path,
)
from time_et import is_capturable_session  # noqa: E402

STATUS_PATH = ROOT / "reports" / "stream_capture_status.json"


def owner_lock_path(db_path: str | Path | None = None) -> Path:
    """Lock sits beside the resolved stream DB, not the checkout.

    A checkout-relative lock lets a worktree daemon and a production daemon
    both open Schwab — the same split-brain PR214 closed for the DB path.
    """
    return resolve_stream_db_path(db_path).with_name("stream_capture.lock")


def acquire_owner_lock(db_path: str | Path | None = None) -> tuple[int, Path]:
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
    lock = owner_lock_path(db_path)
    lock.parent.mkdir(parents=True, exist_ok=True)
    for attempt in (1, 2):
        try:
            fd = os.open(str(lock), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(fd, str(os.getpid()).encode())
            return fd, lock
        except FileExistsError:
            try:
                pid = int(lock.read_text().strip() or 0)  # caps-ok: empty pidfile is not a live owner; 0 fails alive-check and reclaims
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
                    f"FATAL: another stream-capture owner holds {lock} (pid {pid}). "
                    "Single-streamer-owner rule: stop it first, or remove a stale lock."
                ) from None
            if attempt == 1:
                lock.unlink(missing_ok=True)   # stale (dead pid): reclaim once
    raise SystemExit(f"FATAL: could not acquire {lock}")


def release_owner_lock(fd: int, lock: Path) -> None:
    import os
    try:
        os.close(fd)
    finally:
        lock.unlink(missing_ok=True)

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
#: Status-write + watchdog evaluation cadence. Named (not an inline literal) so the
#: recycle path can be driven deterministically at its REAL seam in tests instead of
#: through a copied state machine — the recycle ordering is a correctness contract and
#: has to be provable against the code that actually runs.
STATUS_LOOP_INTERVAL_SEC = 10.0
#: Upper bound on retiring one StreamClient (bounded logout, then bounded transport
#: close). A half-open socket is one of the exact conditions that triggers watchdog
#: recovery, so cleanup must never be able to prevent that recovery — see
#: _retire_stream_client.
STREAM_RETIRE_TIMEOUT_SEC = 5.0


def stream_needs_recycle(age_sec: float | None, seen_data: bool,
                         since_last_reconnect: float,
                         collect_session_live: bool) -> bool:
    """Half-open-guard decision (pure; unit-tested).

    Recycle ONLY during an intended live collection session
    (``time_et.is_capturable_session``: trading day, 04:00-20:00 ET).
    Overnight / closed-market silence is not a half-open socket and must
    not login-spam Schwab. During the live session: data has flowed before
    (a never-beat service is a subscribe problem, not a half-open socket),
    the feed has been quiet past the stale bar, and the cooldown has passed.
    """
    if not collect_session_live:
        return False
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


def make_options_quote_handler(bus: MessageBus, health: HealthRegistry, stats: CaptureStats):
    """LEVELONE_OPTIONS — content stored verbatim (options_quote_msg), never flattened.
    57 native fields (greeks, OI, IV, DTE, ...); no existing consumer needs a flattened
    projection, so inventing scalar columns here would be speculative schema."""
    service = "LEVELONE_OPTIONS"

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
            bus.publish(f"optquote.{sym}", options_quote_msg(
                symbol=sym, content=item, src="schwab_options_l1"))
        stats.record(service, (time.perf_counter() - t0) * 1000.0)
    return handler


class OptionCoverageCompensationError(RuntimeError):
    """A vendor option subscription is live, its durable coverage-epoch open FAILED, and
    the compensating unsubscribe ALSO failed (PR214 premerge gap 4).

    At this point true vendor state is uncertain AND durable coverage truth cannot be
    guaranteed, so continuing steady-state capture would silently produce exactly the
    unattributable gap the coverage ledger exists to prevent. This is raised so the poll
    loop escalates into the EXISTING stream-recycle path (which tears the session down,
    closes epochs, and rebuilds from the operator's current desired contract) rather
    than being absorbed as an ordinary bad tick."""


#: epoch_state key -> the Schwab service its coverage epoch belongs to. The ONE place the
#: daemon's internal per-service key names are mapped to the service names a consumer
#: reads, so a published claim cannot drift from the coverage rows it refers to.
COVERAGE_CLAIM_SERVICES = {"l1": "LEVELONE_OPTIONS", "book": "OPTIONS_BOOK"}


def _publish_coverage_claim(writer, epoch_state: dict) -> bool:
    """Publish WHAT THIS PRODUCER CURRENTLY CLAIMS to be subscribed, per option service.

    An open coverage row is history, not an assertion. A durable CLOSE that fails leaves
    `ended_ts IS NULL` on an epoch this daemon has already knowingly surrendered — and a
    consumer reading that row as producer identity reported a contract the vendor was no
    longer subscribed to, which the UI rendered as "subscribed". The claim published here
    is what makes surrender visible ACROSS PROCESSES the moment it happens, without a
    second source of truth: it rides the existing producer heartbeat row.

    Called on every epoch_state transition (open, close, failed close, retry) rather than
    only on the status cadence, so a surrender is visible immediately instead of up to one
    heartbeat interval later, and a successful switch confirms immediately instead of
    reading as UNKNOWN until the next beat.

    RETURNS whether the claim actually landed, and callers surrendering coverage MUST
    check it. A claim is a LATCHED POSITIVE: once published it stands until something
    overwrites it. If a retraction cannot be written, the PREVIOUS claim is still there
    and still inside the liveness TTL, so a consumer reading it confirms a subscription
    the daemon has already given up — measured at the pre-write-ahead shape:
    contract_match=true against a 0.07s-old heartbeat claiming a surrendered epoch.
    "The heartbeat will go stale" is not a defence; staleness is up to a full TTL away.

    Passing an empty mapping publishes a FULL RETRACTION (nothing claimed), which is how
    a caller gives up coverage it cannot describe per-key yet.

    Never raises: truth publication is a side effect, not the caller's work — but its
    failure is reported to the caller as False, never swallowed."""
    if writer is None or epoch_state is None:
        return False
    try:
        writer.write_heartbeat(claimed_coverage={
            service: epoch_state.get(key)
            for key, service in COVERAGE_CLAIM_SERVICES.items()})
        return True
    except Exception as e:  # noqa: BLE001 — reported to the caller, see above
        print(f"coverage claim publish FAILED — the previously published claim still "
              f"stands and is still within the liveness TTL, so this surrender cannot be "
              f"made visible yet: {type(e).__name__}: {e}")
        return False


#: How often the forced-surrender barrier re-attempts the retraction while waiting out a
#: standing claim. Only ever reached when the durable write is failing, so the cadence
#: just balances "recover as soon as writes come back" against log noise.
CLAIM_BARRIER_RETRY_SEC = 2.0


async def _surrender_claim_or_wait_out_lease(writer, *, reason: str) -> float:
    """Give up the published coverage claim, or WAIT until it can no longer confirm.

    For a CONTROLLED surrender (a watchdog/forced recycle, a clean shutdown) the daemon
    chooses when the subscription dies. That freedom is the fix: a published claim is a
    latched positive with a KNOWN expiry, so if the retraction cannot be written the
    surrender does not have to happen now — it can wait behind the claim's own lease.

      retraction lands   -> surrender immediately, nothing can confirm the old contract;
      retraction fails   -> the claim is still standing AND STILL TRUE, because we have
                            not surrendered anything yet. Hold the subscription until the
                            claim is past PRODUCER_CLAIM_TTL_SEC and can no longer confirm,
                            retrying the retraction throughout, then let the caller
                            surrender into a window where no positive evidence exists.

    There is therefore no instant at which the old contract can be confirmed while it is
    not held: before the barrier the claim is true, after it the claim is unusable.

    Returns the delay it imposed, in seconds — 0.0 on the normal path. The wait is bounded
    by PRODUCER_CLAIM_TTL_SEC from the last successful positive publication, and is only
    reachable while durable writes are failing.

    Waiting here is safe for the two invariants it could threaten: it happens BEFORE any
    teardown, so exactly one live Schwab authority exists throughout and no stream
    generation is retired or created while it runs.

    This covers CONTROLLED paths only. An uncatchable death (SIGKILL, power loss) runs no
    code at all, so no barrier can exist for it; that case is already handled the way it
    always was — the claim expires on its own TTL and startup orphan reconciliation closes
    the epochs the dead lifetime left open. No new machinery is introduced for it."""
    if writer is None:
        return 0.0
    if _publish_coverage_claim(writer, {}):
        return 0.0
    started = time.monotonic()
    announced = False
    while True:
        ts = getattr(writer, "positive_claim_published_ts", None)  # caps-ok: optional claim timestamp; None means no standing claim
        if ts is None:
            break                      # nothing positive stands; surrender is safe
        remaining = (ts + PRODUCER_CLAIM_TTL_SEC) - time.time()
        if remaining <= 0:
            break                      # the standing claim can no longer confirm
        if not announced:
            print(f"{reason}: coverage-claim retraction could not be written — HOLDING "
                  f"the subscription for up to {remaining:.0f}s until the standing claim "
                  f"expires, rather than surrendering behind a claim that would still "
                  f"confirm it")
            announced = True
        await asyncio.sleep(min(remaining, CLAIM_BARRIER_RETRY_SEC))
        if _publish_coverage_claim(writer, {}):
            break                      # writes recovered; retracted for real
    waited = time.monotonic() - started
    if announced:
        print(f"{reason}: claim barrier cleared after {waited:.1f}s — surrendering now")
    return waited


def _epoch_close_is_pending(epoch_state: dict, key: str, epoch_id: "int | None") -> bool:
    """True when `epoch_id`'s durable close FAILED and it is sitting in the pending-close
    retry map — i.e. that epoch is still OPEN in the table (PR214 defect 1C)."""
    if epoch_id is None:
        return False
    return epoch_id in (epoch_state.get(f"{key}_pending_close") or {})


def _discard_pending_close(epoch_state: dict, key: str, epoch_id: "int | None") -> None:
    """Drop `epoch_id` from the pending-close retry set (PR214 defect 1D).

    Used ONLY when the epoch's subscription is KNOWN to still be live, so closing it is
    no longer the correct action and the retry machinery must not later close it behind
    that live subscription's back. Since the durable-close-first reordering there is
    exactly one such caller: a durable CLOSE that failed BEFORE the vendor was touched.
    The vendor never unsubscribed, so the still-open epoch is a true description of a
    live subscription and becomes the current epoch again. This is not 'forgetting' a
    failed close — under close-first, a failed close means nothing happened at all."""
    pending = epoch_state.get(f"{key}_pending_close")
    if pending:
        pending.pop(epoch_id, None)


def _add_pending_close(epoch_state: dict, key: str, epoch_id: int,
                       surrendered_ts: float) -> None:
    """Queue a failed close for retry, REMEMBERING WHEN COVERAGE WAS SURRENDERED.

    The timestamp is the whole point. The pending set used to hold bare ids, so a retry
    that landed minutes later stamped ended_ts at RETRY time — recording coverage across
    the entire durable-write outage, a window in which the subscription was already gone.
    That is the same false-positive claim the close-first ordering exists to prevent,
    just deferred. The surrender time is captured once, when the close is first
    attempted, and every later retry replays THAT instant."""
    pending = epoch_state.setdefault(f"{key}_pending_close", {})
    pending.setdefault(epoch_id, surrendered_ts)


def _try_close_one(writer, epoch_state: dict, key: str, epoch_id: int, *, reason: str,
                   surrendered_ts: float) -> bool:
    """Attempt one close; a failure MOVES the id into the pending-close map rather than
    dropping it — close_coverage_epoch is idempotent (only touches ended_ts IS NULL rows),
    so retrying a call that actually landed is always safe.

    `surrendered_ts` is stamped as ended_ts rather than letting the writer default to
    time.time(): ended_ts must mean "coverage was given up HERE", not "the database
    finally accepted the write here"."""
    try:
        writer.close_coverage_epoch(epoch_id, reason=reason, ts=surrendered_ts)
        return True
    except CoverageWriteError as e:
        print(f"coverage epoch close failed ({key}={epoch_id}, retry pending): {e}")
        _add_pending_close(epoch_state, key, epoch_id, surrendered_ts)
        return False


def _close_coverage_epoch_tracked(writer, epoch_state: dict, key: str, *, reason: str,
                                  surrendered_ts: float | None = None,
                                  require_publish: bool = False) -> bool:
    """Close the CURRENT epoch for `key` (epoch_state[key]), if any. On failure the id
    moves into a per-key pending-close set instead of being discarded — retried by
    _retry_pending_epoch_closes on every later reconciliation tick until it durably
    closes. NEVER silently forgets an epoch id: an unclosed epoch would permanently
    misreport an ended coverage window as still open (the exact class of bug this
    function exists to prevent — see CoverageWriteError's own docstring).

    RETURNS whether the surrender was PUBLISHED (the retraction of the producer claim
    landed). False means the previously published claim still stands: the caller has not
    actually been able to give this coverage up as far as any consumer can tell, and must
    not proceed to surrender the vendor subscription behind it."""
    epoch_id = epoch_state.get(key)
    epoch_state[key] = None
    if epoch_id is None:
        return True
    # Coverage is surrendered HERE — at the decision, before the durable write is even
    # attempted and (under close-first) before the vendor is touched. Pinning ended_ts to
    # this instant is what keeps the claim conservative when the write has to be retried.
    #
    # `surrendered_ts` overrides it for callers whose surrender boundary is EARLIER than
    # this call: a recycle decides to abandon the socket before it tears the generation
    # down, and a shutdown surrenders capture before the writer drain (which alone may
    # take up to 60s). Passing that earlier instant keeps the ledger conservative; taking
    # time.time() here would claim coverage across a window we already know was dead.
    # WRITE-AHEAD RETRACTION. The claim is withdrawn BEFORE the durable close is even
    # attempted, and its success is what the caller gates the vendor surrender on. Doing
    # it afterwards was not enough: if the close AND the retraction both failed, the row
    # stayed open, the previous claim stayed published, and that claim was still inside
    # the liveness TTL — so a consumer confirmed a subscription already given up. Ordering
    # it first means a caller can learn it cannot publish the surrender BEFORE performing
    # one, exactly as the durable-close-first law already governs the vendor transition.
    published = _publish_coverage_claim(writer, epoch_state)
    if not published and require_publish:
        # `require_publish` callers CAN decline to surrender (the vendor transition is
        # theirs to defer), so nothing is given up at all: the epoch stays current and the
        # row is deliberately NOT closed. Closing it here while the standing claim still
        # named it would leave memory and ledger disagreeing — a closed row the daemon
        # still believes it holds. Callers that MUST surrender (a recycle tearing down a
        # dying socket, a shutdown) leave this False and proceed; their residual exposure
        # is documented at those call sites.
        epoch_state[key] = epoch_id
        return False
    _try_close_one(writer, epoch_state, key, epoch_id, reason=reason,
                   surrendered_ts=time.time() if surrendered_ts is None else surrendered_ts)
    return published


def _open_coverage_epoch_tracked(writer, epoch_state: dict, key: str, symbol: str,
                                 service: str, *, reason: str) -> None:
    """Open one durable coverage epoch. On failure epoch_state[key] stays None, so the
    caller must not treat `symbol` as durably covered for `service` this tick — retried
    on the next reconciliation tick, never assumed."""
    try:
        epoch_state[key] = writer.open_coverage_epoch(symbol, service, reason=reason)
    except CoverageWriteError as e:
        print(f"coverage epoch open failed ({key}={symbol}, retry pending): {e}")
        epoch_state[key] = None
    # Publish either outcome: a successful open must be claimable immediately (otherwise a
    # completed switch reads as UNKNOWN until the next beat), and a failed one must not.
    _publish_coverage_claim(writer, epoch_state)


def _retry_pending_epoch_closes(writer, epoch_state: dict, key: str, *, reason: str) -> None:
    """Retry any previously-failed epoch closes for `key` — called every reconciliation
    tick so a transient durable-write outage self-heals without operator action, and a
    stuck epoch never silently sits open forever.

    Each id is replayed with the surrender time recorded when its close was FIRST
    attempted, so however long the outage lasts the recorded ended_ts does not drift
    forward into a window the subscription no longer covered."""
    pending_key = f"{key}_pending_close"
    pending = epoch_state.get(pending_key)
    if not pending:
        return
    still_open = {eid: ts for eid, ts in pending.items()
                  if not _try_close_one(writer, epoch_state, key, eid, reason=reason,
                                        surrendered_ts=ts)}
    epoch_state[pending_key] = still_open
    # A landed retry removes the last open row for a surrendered epoch; republish so the
    # claim and the rows are re-stated together rather than drifting between beats.
    _publish_coverage_claim(writer, epoch_state)


async def _reconcile_option_service(stream, held: str | None, requested: str | None, *,
                                    subs_fn, unsubs_fn, writer, epoch_state: dict | None,
                                    epoch_key: str, service_name: str) -> str | None:
    """Reconcile ONE Schwab option service (LEVELONE_OPTIONS or OPTIONS_BOOK)
    independently of the other — they are two SEPARATE vendor operations, not a
    transactional pair, so one succeeding while the other fails must not be collapsed
    into a single all-or-nothing outcome (the old code returned the STALE `current` on
    any exception, discarding a real vendor-side success and inviting a duplicate
    subscribe on the next tick). Returns the symbol now actually held at the vendor for
    THIS service (None if none) — vendor-held truth advances only on a confirmed vendor
    ack, durable coverage-epoch truth (epoch_state[epoch_key]) advances only on a
    confirmed sqlite write, and neither is ever assumed from the other.

    TRANSITION ORDER IS THE CORRECTNESS CONTRACT (PR214 coverage-interval causality).
    An A->B switch runs strictly:

        durable CLOSE A  ->  vendor UNSUB A  ->  vendor SUB B  ->  durable OPEN B

    The durable close comes FIRST, before the vendor is touched. The previous ordering
    (unsub first, close second, resubscribe on close failure) kept vendor and ledger
    agreeing at the TICK BOUNDARY but not across the INTERVAL: measured with a
    deterministic clock, A's epoch stayed continuously open (started_ts=101.0,
    ended_ts=NULL) across [102.0 unsub-complete, 104.0 resubscribe-complete] -- a window
    in which the vendor was definitively NOT subscribed. That is a false-positive
    coverage claim, and it is exactly the confusion stream_coverage_epochs exists to
    prevent: our own subscription hole would later read as observed market silence.

    Closing first makes the ledger's claim conservative by construction:
      A.ended_ts   <= the confirmed vendor UNSUB A completion time
      B.started_ts >= the confirmed vendor SUB B completion time
    so the ledger may describe a slightly WIDER uncovered interval than the true vendor
    transition, but it can never bridge a known period of no subscription. That bias is
    deliberate and fail-closed. These timestamps are therefore transition BOUNDARIES,
    not vendor acknowledgement times, and must not be described as the latter.

    The A.ended_ts bound holds even when the durable write has to be RETRIED: the close
    is stamped with the instant coverage was surrendered, carried in the pending-close
    map, not with the instant sqlite finally accepted it (see _add_pending_close). Before
    that, a close deferred by a 300s write outage recorded ended_ts 300s late and claimed
    the whole outage as covered — the same false-positive, merely postponed.

    ENTRY-STATE INVARIANT (production coverage authority only). When a writer and
    epoch_state are supplied, this service's remembered vendor state and its durable
    coverage must AGREE on the way in. The two disagreeing shapes are handled below and
    neither is allowed to become a steady state — see the guard at the top of the body."""
    if writer is not None and epoch_state is not None:
        entry_epoch = epoch_state.get(epoch_key)
        if held is not None and entry_epoch is None:
            # VENDOR-HELD WITH NO DURABLE EPOCH. `held` is a remembered string, not a
            # fresh vendor acknowledgement, so opening an epoch from it would fabricate
            # coverage for a subscription nobody re-confirmed. Left alone it is worse
            # than a one-tick under-claim: an unsubscribe failure returns this same shape
            # again, and the state re-enters itself indefinitely — REAL CAPTURE FLOWING
            # WITH ZERO DURABLE COVERAGE, which defeats the ledger's entire purpose of
            # separating "not subscribed" from "subscribed, vendor silent". Treat it as
            # an inconsistent stream generation and fail closed: the replacement stream
            # must EARN coverage through vendor SUB success -> durable OPEN success.
            raise OptionCoverageCompensationError(
                f"{service_name}: vendor-held {held} with NO durable coverage epoch at "
                f"tick entry — a remembered held symbol is not a subscription "
                f"acknowledgement and must not be used to open one; forcing stream "
                f"recycle so a fresh generation can earn coverage")
        if held is None and entry_epoch is not None:
            # OPEN EPOCH WITH NO VENDOR SUBSCRIPTION — the inverse. Claiming coverage
            # while holding nothing is a false-positive by definition, and it must be
            # resolved BEFORE any new subscribe rather than left beside a B epoch.
            # Surrendering conservatively is both correct and sufficient here: there is
            # no vendor state to be uncertain about, so a recycle would buy nothing.
            print(f"{service_name}: durable coverage epoch open with NO vendor "
                  f"subscription held — surrendering the stale claim before reconciling")
            _close_coverage_epoch_tracked(writer, epoch_state, epoch_key,
                                          reason="stale_coverage_no_vendor_hold")
    if held != requested:
        if held is not None:
            # True only once a durable coverage claim has actually been surrendered for
            # `held` this tick. Callers without a writer/epoch_state (no ledger at all)
            # never surrender anything, so they keep the historical unsub-failure
            # behaviour: stay on the last KNOWN vendor-held symbol and retry next tick.
            coverage_surrendered = False
            if writer is not None and epoch_state is not None:
                # CASE A: durable CLOSE FIRST. If it fails, the vendor has NOT been
                # touched, so the prior state is still exactly true (A held, A epoch
                # open) -- nothing to compensate, and critically no vendor operation
                # whose interval could go unrecorded. Retry the whole transition next
                # tick. This replaces the old unsub-then-resubscribe rollback, which
                # only restored the END state and could not undo the interval.
                closing_epoch_id = epoch_state.get(epoch_key)
                surrender_published = _close_coverage_epoch_tracked(
                    writer, epoch_state, epoch_key, reason="active_contract_changed",
                    require_publish=True)
                # An UNPUBLISHABLE surrender is as disqualifying as an unwritable close.
                # If the retraction did not land, the previously published claim still
                # names this epoch and is still inside the liveness TTL, so surrendering
                # the vendor now would make that standing claim FALSE with no way to say
                # so. Keeping the subscription keeps the standing claim TRUE instead —
                # the same fail-closed shape as the durable-close failure beside it.
                if (not surrender_published
                        or _epoch_close_is_pending(epoch_state, epoch_key, closing_epoch_id)):
                    why = ("durable coverage-epoch CLOSE failed" if surrender_published
                           else "the coverage-claim RETRACTION could not be published")
                    print(f"{service_name}: {why} for {held} — leaving the vendor "
                          f"subscription untouched and NOT subscribing {requested}; "
                          f"retrying the transition later")
                    # The epoch is still open and still describes a live subscription,
                    # so it is the CURRENT epoch again and closing it is not the correct
                    # action to retry behind a subscription we deliberately kept.
                    epoch_state[epoch_key] = closing_epoch_id
                    _discard_pending_close(epoch_state, epoch_key, closing_epoch_id)
                    _retry_pending_epoch_closes(writer, epoch_state, epoch_key,
                                                reason="retry_pending_close")
                    # Re-assert the claim we just withdrew: the subscription is still
                    # live. If THIS write fails too the claim stays retracted, which
                    # under-claims — the safe direction, never a false positive.
                    _publish_coverage_claim(writer, epoch_state)
                    return held
                # Surrendered only if there was an actual open claim to surrender. Under
                # production coverage authority the entry invariant above guarantees one
                # existed (held != None implies a current epoch), so this is always True
                # here; it stays explicit because the flag also governs the no-ledger
                # callers below, for whom nothing is ever surrendered.
                coverage_surrendered = closing_epoch_id is not None
            try:
                await unsubs_fn([held])
                held = None
            except Exception as e:
                if not coverage_surrendered:
                    # No ledger involved (no writer/epoch_state): nothing was surrendered,
                    # so there is no coverage-truth divergence to escalate. Historical
                    # behaviour — stay on the last KNOWN vendor-held symbol, do not also
                    # subscribe this tick (two live keys on one service), retry next tick.
                    print(f"{service_name} unsub {held} failed, retry pending: {e}")
                    # This early return skips the bottom block, so drain the pending-close
                    # queue here as CASE A does — otherwise a durable-write outage that
                    # coincides with a failing unsubscribe would leave stale ids unretried
                    # for as long as both persist.
                    if writer is not None and epoch_state is not None:
                        _retry_pending_epoch_closes(writer, epoch_state, epoch_key,
                                                    reason="retry_pending_close")
                    return held
                # CASE C: the ledger has ALREADY surrendered this symbol's coverage claim,
                # but the vendor unsubscribe is unconfirmed. Do not pretend the old steady
                # state is intact, and above all do not re-open an epoch to make the two
                # look equal -- that would fabricate coverage over an interval whose
                # vendor state we do not know. A conservative uncovered interval is
                # correct; a fabricated subscribed interval is not. Escalate into the
                # existing stream-recycle path.
                raise OptionCoverageCompensationError(
                    f"{service_name}: durable coverage for {held} was closed but the "
                    f"vendor unsubscribe then failed ({type(e).__name__}: {e}) — vendor "
                    f"state unconfirmed with its coverage claim already surrendered; "
                    f"forcing stream recycle rather than continuing or fabricating an "
                    f"open epoch") from e
        if requested is not None and held is None:
            try:
                await subs_fn([requested])
                held = requested
                print(f"{service_name} subscribed -> {requested}")
            except Exception as e:
                print(f"{service_name} sub {requested} failed, retry pending: {e}")
                # held stays None; retried next tick without a stale duplicate-sub risk.
    if writer is not None and epoch_state is not None:
        _retry_pending_epoch_closes(writer, epoch_state, epoch_key, reason="retry_pending_close")
        if held is not None:
            if epoch_state.get(epoch_key) is None:
                _open_coverage_epoch_tracked(writer, epoch_state, epoch_key, held,
                                             service_name, reason="active_contract_set")
                # PR214 premerge gap 4: a LIVE VENDOR SUBSCRIPTION whose coverage start
                # could not be durably recorded defeats the entire causal purpose of the
                # ledger — a later gap in the data becomes unattributable between "not
                # subscribed" and "subscribed, vendor silent". Steady-state capture must
                # therefore never continue in that shape. COMPENSATE: give the vendor
                # subscription back, so the invariant VENDOR_HELD ⇒ DURABLE_OPEN_EPOCH
                # holds at every tick boundary, and let the next tick retry cleanly.
                if epoch_state.get(epoch_key) is None:
                    print(f"{service_name}: durable coverage-epoch open FAILED for {held} — "
                          f"compensating by unsubscribing (a vendor subscription must not "
                          f"outlive its coverage record)")
                    try:
                        await unsubs_fn([held])
                        held = None       # vendor no longer holds it; retried next tick
                    except Exception as e:
                        # True vendor state is now UNCERTAIN and durable coverage cannot
                        # be guaranteed. Do not continue as if held/healthy — raise into
                        # the caller's existing stream-recycle/session-failure path,
                        # which tears the session down and restores a known state.
                        raise OptionCoverageCompensationError(
                            f"{service_name}: coverage-epoch open failed for {held} AND the "
                            f"compensating unsubscribe also failed ({type(e).__name__}: {e}) "
                            f"— vendor state uncertain with no durable coverage; forcing "
                            f"stream recycle rather than continuing") from e
        else:
            _close_coverage_epoch_tracked(writer, epoch_state, epoch_key,
                                          reason="active_contract_changed")
    return held


async def _apply_active_option_contract_subs(stream, contract_state: dict, *,
                                             writer=None, epoch_state: dict | None = None) -> dict:
    """Diff the server's requested active OPTION CONTRACT against what is currently held,
    PER SERVICE (LEVELONE_OPTIONS and OPTIONS_BOOK reconciled independently — see
    _reconcile_option_service). Same bounded-key shape as the equity book poll: at most
    ONE contract carries each service at a time (2 services x 1 contract = 2 keys),
    independent of anything else the daemon watches.

    `requested` MUST already be a chain response's own "symbol" field (enforced by
    stream_spine.write_active_option_contract_signal's caller, not re-validated here) —
    a bare ticker was PROVEN to fail this exact subscribe call ("no option symbol from
    chain", reports/of_schwab_live_capability_matrix_20260820.md).

    ``contract_state``: {"l1": symbol|None, "book": symbol|None} — the symbol currently
    held AT THE VENDOR for each service; mutated in place and returned. ``writer``/
    ``epoch_state``: when given, durably records COVERAGE EPOCHS (which windows this
    contract was actually subscribed, per service) — mutated in place ({"l1": epoch_id|
    None, "book": epoch_id|None} plus retry-tracking keys) so a gap in
    stream_options_quotes_raw is later interpretable as "not subscribed" vs "subscribed,
    vendor silent". Optional: tests exercising only the subscribe-diff behavior can omit
    both."""
    requested = read_active_option_contract_signal()
    contract_state["l1"] = await _reconcile_option_service(
        stream, contract_state.get("l1"), requested,
        subs_fn=stream.level_one_option_subs, unsubs_fn=stream.level_one_option_unsubs,
        writer=writer, epoch_state=epoch_state, epoch_key="l1", service_name="LEVELONE_OPTIONS")
    contract_state["book"] = await _reconcile_option_service(
        stream, contract_state.get("book"), requested,
        subs_fn=stream.options_book_subs, unsubs_fn=stream.options_book_unsubs,
        writer=writer, epoch_state=epoch_state, epoch_key="book", service_name="OPTIONS_BOOK")
    return contract_state


async def _active_option_contract_poll_loop(get_stream, get_current, set_current,
                                            stop: asyncio.Event, writer=None,
                                            epoch_state: dict | None = None,
                                            interval_sec: float = 1.0,
                                            request_recycle: asyncio.Event | None = None) -> None:
    """Fast poll of the active-option-contract signal — same shape and cadence as
    _active_ticker_book_poll_loop, independent of it (a different signal file, a
    different pair of Schwab services).

    `request_recycle` (PR214 premerge gap 4): set when a coverage-compensation failure
    leaves vendor state uncertain with no durable coverage. The generic handler below
    deliberately survives one bad tick, which is right for a transient vendor/DB error
    but WRONG for that condition — absorbing it would let capture continue in exactly
    the unattributable shape the ledger exists to prevent. That one error escalates into
    the EXISTING stream-recycle path instead of being swallowed."""
    # The stream an escalation was raised on. Requesting a recycle is asynchronous — the
    # main loop services it on its own (slower) cadence — so without this the loop would
    # keep reconciling the very stream it just declared unusable. That is not academic:
    # an escalation leaves the per-service held NAME stale (the raise skips the caller's
    # assignment) while the durable epoch is already surrendered, so if the operator's
    # signal flips back to that symbol first, `held == requested`, the transition block is
    # skipped entirely, and the bottom block opens a BRAND NEW epoch for it — claiming
    # coverage for a subscription whose vendor state is precisely what we just admitted we
    # do not know. Measured before this guard: a fabricated second epoch row for SPY.
    # "Forcing stream recycle rather than continuing" has to actually stop the continuing.
    poisoned_stream = None
    while not stop.is_set():
        try:
            await asyncio.wait_for(stop.wait(), timeout=interval_sec)
            return
        except asyncio.TimeoutError:
            pass
        stream = get_stream()
        if stream is None:
            continue
        if stream is poisoned_stream:
            # Quiet by design: this repeats every tick until the recycle lands, and the
            # escalation itself was already reported loudly.
            continue
        try:
            new_cur = await _apply_active_option_contract_subs(
                stream, get_current(), writer=writer, epoch_state=epoch_state)
            set_current(new_cur)
        except OptionCoverageCompensationError as e:
            # NOT an ordinary bad tick: vendor state uncertain AND no durable coverage.
            # This stream is done — no further vendor ops or coverage claims on it. The
            # guard clears itself when the recycle installs a different stream object.
            poisoned_stream = stream
            print(f"active-option-contract poll: FORCING STREAM RECYCLE — {e}")
            if request_recycle is not None:
                request_recycle.set()
            else:   # no recycle channel wired (direct/unit call) — never swallow it
                raise
        except Exception as e:  # noqa: BLE001 — poll loop must survive one bad tick
            print(f"active-option-contract poll: {type(e).__name__}: {e}")


def write_status(bus: MessageBus, health: HealthRegistry, writer: CaptureWriter,
                 stats: CaptureStats, max_qdepth: int,
                 epoch_state: dict | None = None) -> None:
    # PR214_RTH_DEFECT_REMEDIATION_FINAL_GAPS (Gap 2): the producer identity/liveness
    # signal now lives INSIDE stream_capture.db itself (write_heartbeat), on the SAME
    # cadence as this file-based status write -- one call site, one clock, not a second
    # independently-scheduled heartbeat loop. The file-based status below is unchanged
    # and still serves _read_daemon_upstream_health's per-service Schwab-socket truth.
    # The heartbeat carries the producer's CURRENT coverage claim, so the liveness signal
    # and the subscription assertion advance together on one clock. Re-stating it here
    # (as well as on every epoch transition) is what makes a daemon that has stopped
    # writing go UNKNOWN rather than leaving its last claim standing indefinitely.
    try:
        writer.write_heartbeat(claimed_coverage=None if epoch_state is None else {
            service: epoch_state.get(key)
            for key, service in COVERAGE_CLAIM_SERVICES.items()})
    except Exception as e:  # noqa: BLE001 — a heartbeat write failure must not kill the daemon's status loop
        print(f"write_heartbeat failed (continuing): {type(e).__name__}: {e}")
    STATUS_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATUS_PATH.write_text(json.dumps({
        "ts": time.time(), "health": health.report(),
        "published": bus.published, "drops": bus.drop_counts(),
        "rows_written": writer.rows_written, "commits": writer.commits,
        "insert_errors": writer.insert_errors,
        "max_writer_queue_depth": max_qdepth,
        "per_service": stats.per_service,
        "handle_ms_p50": stats.p(50), "handle_ms_p99": stats.p(99),
        # PR214_RTH_DEFECT_REMEDIATION_V1: the resolved ABSOLUTE stream DB identity
        # this daemon is actually writing, so a consumer can directly compare it
        # against its own resolved path rather than assuming they match because
        # both processes were "healthy" (the RTH failure mode: both healthy, two
        # different files).
        "db_path": str(writer.db_path),
    }, indent=2), encoding="utf-8")


async def run(symbols: list[str], duration_min: float, db_path: str | None) -> int:
    lock_fd, lock = acquire_owner_lock(db_path)
    try:
        return await _run_locked(symbols, duration_min, db_path)
    finally:
        # The lock's lifetime is the WHOLE session — login/subscribe failures and
        # KeyboardInterrupt included (Cursor round-2 HIGH: it leaked on init paths).
        release_owner_lock(lock_fd, lock)


async def _retire_stream_client(stream, *, reason: str,
                                timeout: float = STREAM_RETIRE_TIMEOUT_SEC) -> None:
    """THE one seam that terminally retires a Schwab StreamClient. Never raises.

    AT MOST ONE live/logged-in production Schwab stream session may exist, and the static
    single-constructor gate cannot enforce that at runtime: an abandoned StreamClient is
    still logged in until something says so. Relying on garbage collection is not
    retirement — nothing in schwab-py logs out on __del__, so a dropped reference leaves
    a live session on the account holding subscriptions we no longer read.

    Verified against the INSTALLED schwab-py 1.5.1 (site-packages/schwab/streaming.py):
      * StreamClient.logout() is the library's supported termination operation — it sends
        ADMIN/LOGOUT and AWAITS the vendor's response ("no further stream operations are
        possible" afterwards). Because it awaits a reply, it is precisely the call that
        hangs on the half-open socket that triggered the recycle in the first place.
      * logout() does NOT close the websocket: login() assigns self._socket via
        ws_client.connect() and nothing in logout() touches it. Graceful logout alone
        therefore leaves the transport open, so the socket is closed afterwards.

    Both steps are separately bounded. A cleanup that can hang would make watchdog
    recovery impossible, which is strictly worse than the leak it is trying to prevent —
    so a timeout is REPORTED and then stepped past, never awaited indefinitely."""
    if stream is None:
        return
    logout = getattr(stream, "logout", None)  # caps-ok: optional schwab-py logout; missing means skip
    if logout is not None:
        try:
            await asyncio.wait_for(logout(), timeout=timeout)
        except asyncio.TimeoutError:
            print(f"retire stream ({reason}): logout timed out after {timeout:.0f}s — "
                  f"closing the transport anyway")
        except Exception as e:  # noqa: BLE001 — retirement must never raise
            print(f"retire stream ({reason}): logout failed "
                  f"({type(e).__name__}: {e}) — closing the transport anyway")
    # Close the transport whether or not the graceful logout landed: after a timed-out or
    # failed logout the socket is exactly what still has to go.
    sock = getattr(stream, "_socket", None)  # caps-ok: optional transport handle
    close = getattr(sock, "close", None)  # caps-ok: optional closer; missing means already gone
    if close is None:
        return
    try:
        result = close()
        if inspect.isawaitable(result):
            await asyncio.wait_for(result, timeout=timeout)
    except asyncio.TimeoutError:
        print(f"retire stream ({reason}): socket close timed out after {timeout:.0f}s")
    except Exception as e:  # noqa: BLE001
        print(f"retire stream ({reason}): socket close failed ({type(e).__name__}: {e})")


async def _cancel_and_await(tasks, *, what: str) -> None:
    """Cancel tasks and WAIT for them to actually finish.

    The await is the point. cancel() only schedules the cancellation; until the task has
    been awaited it may still be suspended inside a vendor operation and may still resume
    and mutate shared state. Awaiting is what makes "this task can no longer touch
    anything" a fact rather than a hope."""
    live = [t for t in tasks if t is not None]
    for t in live:
        t.cancel()
    for t in live:
        try:
            await t
        except asyncio.CancelledError:
            pass  # expected: we cancelled it
        except Exception as e:  # noqa: BLE001 — teardown reports, never hangs
            print(f"{what}: task ended with {type(e).__name__}: {e}")


async def _retire_stream_generation(stream, pump_task, control_tasks, *,
                                    reason: str) -> None:
    """Retire ONE stream generation completely: its control tasks, its pump, its session.

    STREAM GENERATION OWNERSHIP IS THE CONTRACT. A control operation belonging to
    generation N must never mutate vendor subscriptions, contract state, epoch state or
    durable coverage belonging to generation N+1. The poll loops are the only things that
    can, because they survive across generations by construction and can be suspended
    inside a vendor await exactly when a recycle begins.

    MEASURED before this existed, through the real _run_streaming/poll/recycle seams: a
    generation-1 option tick parked inside level_one_option_unsubs(SPY) resumed AFTER
    generation 2 was live and covered, and then issued FIVE vendor operations on the
    retired stream (including subscribing the current contract on a dead session),
    CLOSED generation 2's live OPTIONS_BOOK coverage epoch (row id 4), opened a duplicate
    (row id 5), and replaced generation 2's epoch id in the shared state (4 -> 5).

    The fix is ownership, not locking: the control tasks are cancelled AND AWAITED before
    anything else is touched, so no stale tick exists to race. A lock around vendor awaits
    would be worse — a hung vendor operation is one of the exact conditions the watchdog
    recovers from, and a lock held across it would block the recovery.

    Cancelling mid-vendor-operation can leave the OLD session's vendor state uncertain.
    That is acceptable here and only here: the whole point is that the entire old
    StreamClient is being retired, so its subscriptions die with it."""
    await _cancel_and_await(control_tasks, what=f"retire generation ({reason})")
    await _cancel_and_await((pump_task,), what=f"retire generation ({reason})")
    await _retire_stream_client(stream, reason=reason)


async def _shutdown_sequence(pump_task, writer_task, stop, wsub,
                             extra_producers: tuple = ()) -> None:
    """SHUTDOWN ORDER IS THE CONTRACT (Cursor round-2 HIGHs).

    1) Quiesce the PRODUCER first — after this await nothing can publish, so the
       writer's drain sees a queue that only shrinks (closes the in-flight
       pump→bus→queue loss window).
    2) THEN stop the writer with drain time sized to worst-case depth (8192 rows is
       seconds; 60s is generous) — and a timeout is REPORTED as loss, never silent.

    Any argument may be None: this same sequence retires a FAILED INITIALIZATION, where
    only some of the resources were ever acquired. `None` means "never created, nothing
    to retire" — never "skip the rest of the shutdown".

    On return the writer task is TERMINAL in every case (drained, failed, or cancelled by
    the timeout), which is what makes the caller's writer.close() safe.
    """
    # ALL producers quiesce together — the Alpaca leg is a producer exactly like the
    # Schwab pump, so it must be dead before the writer drain starts (same law).
    await _cancel_and_await((pump_task, *extra_producers), what="shutdown: producer")
    stop.set()
    if writer_task is None:
        return
    try:
        await asyncio.wait_for(writer_task, timeout=60)
    except asyncio.TimeoutError:
        # wait_for cancels the task and awaits that cancellation before raising, so the
        # writer task is terminal here too — the loss is reported, not left running.
        print(f"shutdown: WRITER DRAIN TIMED OUT — up to {wsub.queue.qsize()} "
              "queued rows may be lost (counted, not hidden)")
    except asyncio.CancelledError:
        pass  # already retired
    except Exception as exc:  # noqa: BLE001
        print(f"shutdown: writer ended with {type(exc).__name__}: {exc}")


async def _run_locked(symbols: list[str], duration_min: float, db_path: str | None) -> int:
    from config import build_config
    from schwab_client import build_client_from_token

    # ── STARTUP ORDER IS A CORRECTNESS CONTRACT (PR214 premerge gap 3) ──────────
    # Coverage reconciliation depends on the OWNER LOCK (already held by run()) and the
    # CANONICAL STREAM DB — it does NOT depend on Schwab authentication. Building the
    # Schwab client first meant a prior hard death plus an expired/broken token exited
    # at the auth check BEFORE reconciliation ever ran, leaving that dead lifetime's
    # epochs falsely open — indefinitely subscribed while no daemon is running, which is
    # precisely the historically-false observability 2A exists to prevent, and it
    # persisted for exactly as long as the operator's token stayed broken.
    # DB + reconciliation now come FIRST; the external vendor dependency comes after.
    writer = CaptureWriter(db_path) if db_path else CaptureWriter()
    try:
        # Close any coverage epoch left open by a PRIOR daemon lifetime, BEFORE this one
        # opens any new live epoch. The reconciliation timestamp is an UPPER BOUND
        # ("known closed no later than this startup"), never a fabricated crash time —
        # see CaptureWriter.reconcile_orphan_coverage_epochs. Idempotent: a clean prior
        # shutdown leaves nothing open and this closes 0 rows.
        try:
            _orphans = writer.reconcile_orphan_coverage_epochs()
            if _orphans:
                print(f"coverage-epoch reconciliation: closed {_orphans} orphan epoch(s) "
                      f"left open by a prior daemon lifetime "
                      f"(reason={CaptureWriter.COVERAGE_ORPHAN_REASON})")
        except Exception as e:  # noqa: BLE001 — surfaced, never silently skipped
            print(f"coverage-epoch reconciliation FAILED: {type(e).__name__}: {e}")
            raise

        # Only NOW take the external Schwab dependency. A failure here returns without
        # ever opening a live epoch; reconciliation above is already committed, and the
        # `finally` closes the writer on this path exactly as on every other.
        cfg = build_config(str(ROOT))
        state = build_client_from_token(api_key=cfg.api_key, app_secret=cfg.app_secret,
                                        token_path=cfg.token_path)
        if not state.ok or state.client is None:
            print(f"FATAL: Schwab client init failed: {state.message}")
            return 2

        bus = MessageBus()
        health = HealthRegistry()
        stats = CaptureStats(sample_dir=ROOT / "reports")
        wsub = bus.subscribe("", policy=COUNT_DROPS, maxsize=8192)   # writer sees everything
        _ui_future = bus.subscribe("quote.", policy=COALESCE)        # proves coalesce path live
        stop = asyncio.Event()

        return await _run_streaming(symbols, duration_min, bus, health, stats,
                                    writer, wsub, stop, state)
    finally:
        writer.close()   # every exit path incl. auth/login/subscribe failure (round-3 MEDIUM)


async def _schwab_connect(state, symbols, bus, health, stats, stop, active_book_ticker=None,
                          active_option_contract=None, writer=None, epoch_state=None):
    """Fresh Schwab stream: login + handlers + subs -> (stream, running pump task,
    option_contract_state). Used at start AND by the half-open watchdog (a recycle is a
    clean rebuild — never an attempt to resuscitate a dead StreamClient).

    ``active_book_ticker`` / ``active_option_contract``: re-apply these subscriptions
    immediately after connecting — a fresh StreamClient carries no subscriptions, so a
    recycle that forgot this would silently drop live depth/options data until the next
    poll tick noticed the (unchanged) signal file and had nothing to diff against.

    ``writer``/``epoch_state``: when given, opens a NEW options coverage epoch for
    ``active_option_contract`` (a stream recycle genuinely ends the old subscription
    window, however briefly — the caller is responsible for closing the epoch that died
    with the old stream before calling this).

    The returned ``option_contract_state`` ({"l1": symbol|None, "book": symbol|None})
    reflects what ACTUALLY got resubscribed per service — a partial failure (e.g.
    LEVELONE_OPTIONS resubscribes but OPTIONS_BOOK errors) must not be reported to the
    caller as a uniform success on both services."""
    from schwab.streaming import StreamClient

    stream = StreamClient(state.client)
    # ── OWNERSHIP BOUNDARY ──────────────────────────────────────────────────────
    # It starts BEFORE login, not after. schwab-py's login() establishes the websocket in
    # _init_from_preferences() and only THEN sends ADMIN/LOGIN and awaits the reply, which
    # raises (UnexpectedResponse / UnexpectedResponseCode) on a rejected or mismatched
    # login and never closes the socket it just opened. With the boundary after login(),
    # that transport escaped every retirement path and no reference to it survived —
    # measured: 1 socket opened, 0 closed, while the identical failure one step later was
    # retired cleanly. Each watchdog retry during a token outage repeated it.
    #
    # _retire_stream_client is bounded and tolerates a client that never logged in (a
    # logout attempt on a dead session is reported, then the transport is closed anyway),
    # so extending the existing lifecycle over login() needs no second mechanism.
    # Past this point a session this function OWNS may hold a transport and may be logged
    # in, and it has not yet been handed to the caller. Anything that raises here — the
    # login itself, a failed resubscribe, an OptionCoverageCompensationError out of the
    # reconciliation — used to abandon it: the caller's `except Exception` printed
    # "reconnect FAILED", no pump was ever created to read it, and nothing logged it out
    # or closed it, on an account that permits one live session. Retire it before the
    # failure propagates.
    try:
        await stream.login()
        return await _schwab_connect_after_login(
            stream, symbols, bus, health, stats, stop,
            active_book_ticker=active_book_ticker,
            active_option_contract=active_option_contract,
            writer=writer, epoch_state=epoch_state)
    except BaseException:
        # BaseException, not Exception: a cancelled connect must not leak a session
        # either. The original failure is re-raised unchanged — retirement is cleanup,
        # never a verdict, and must not mask why the connect failed.
        await _retire_stream_client(stream, reason="partial connect failure")
        raise


async def _schwab_connect_after_login(stream, symbols, bus, health, stats, stop, *,
                                      active_book_ticker=None, active_option_contract=None,
                                      writer=None, epoch_state=None):
    """Everything _schwab_connect does once a live session exists. Split out ONLY so the
    ownership boundary above is a single try/except around one call rather than a large
    indented block — every path out of here is covered by that retirement."""
    stream.add_level_one_equity_handler(
        make_handler("LEVELONE_EQUITIES", LEVELONE_FIELDS, "quote", bus, health, stats))
    stream.add_chart_equity_handler(
        make_handler("CHART_EQUITY", CHART_FIELDS, "bar1m", bus, health, stats))
    stream.add_nasdaq_book_handler(make_book_handler("NASDAQ_BOOK", bus, health, stats))
    stream.add_nyse_book_handler(make_book_handler("NYSE_BOOK", bus, health, stats))
    stream.add_level_one_option_handler(make_options_quote_handler(bus, health, stats))
    stream.add_options_book_handler(make_book_handler("OPTIONS_BOOK", bus, health, stats))
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
    option_contract_state = {"l1": None, "book": None}
    if active_option_contract:
        # A fresh StreamClient holds nothing (held=None for both services) — reconciles
        # through the SAME per-service function the normal poll tick uses, so a partial
        # failure here (e.g. LEVELONE_OPTIONS resubscribes but OPTIONS_BOOK errors) gets
        # the identical per-service-truth handling instead of a duplicated, coarser
        # all-or-nothing block. The ACTUAL per-service outcome is captured, never assumed.
        option_contract_state["l1"] = await _reconcile_option_service(
            stream, None, active_option_contract,
            subs_fn=stream.level_one_option_subs, unsubs_fn=stream.level_one_option_unsubs,
            writer=writer, epoch_state=epoch_state, epoch_key="l1", service_name="LEVELONE_OPTIONS")
        option_contract_state["book"] = await _reconcile_option_service(
            stream, None, active_option_contract,
            subs_fn=stream.options_book_subs, unsubs_fn=stream.options_book_unsubs,
            writer=writer, epoch_state=epoch_state, epoch_key="book", service_name="OPTIONS_BOOK")

    async def pump() -> None:
        while not stop.is_set():
            await stream.handle_message()

    return stream, asyncio.create_task(pump()), option_contract_state


async def _run_streaming(symbols, duration_min, bus, health, stats,
                         writer, wsub, stop, state) -> int:
    max_qdepth = 0
    # ── OWNED RESOURCES, DECLARED BEFORE THE LIFECYCLE BOUNDARY ─────────────────
    # Every async task and vendor session this function creates is named here and
    # acquired INSIDE the try below, so the single `finally` retires whatever was
    # actually acquired — including on a failure during initialization.
    #
    # This used to be split: writer_task was created before the try, and the initial
    # connect + producer/control task creation happened between the two. A failure in
    # that window bypassed the finally entirely, so nothing ever set `stop`, nothing
    # awaited the writer task, and _run_locked's own `finally: writer.close()` then ran
    # while writer.run() was still executing. MEASURED at that shape: writer.run()
    # entered and never exited, task done()=False cancelled()=False, stop never set, one
    # orphan task still live — and after the close it consumed five real bus messages and
    # failed every insert against the closed database (insert_errors=5, rows_written=0).
    # Initialization failure now gets the same ownership discipline as steady-state
    # failure; `None`/`()` mean "never acquired, nothing to retire".
    writer_task = None
    stream = None
    pump_task = None
    alpaca_task = None
    control_tasks: tuple = ()
    #: Shared with the active-ticker book-poll task (below) — a plain dict, not a
    #: closure-captured local, because BOTH the recycle path here and the poll loop's
    #: coroutine need to read/write the SAME current values.
    book_state: dict = {"stream": None, "ticker": None}
    #: Same shared-dict shape, for the options-contract poll loop — a SEPARATE signal
    #: (stream_active_option_contract.json) and a separate pair of Schwab services, so it
    #: is tracked independently rather than folded into book_state. "contract" holds the
    #: symbol currently held AT THE VENDOR per service ({"l1": symbol|None, "book":
    #: symbol|None}) — the two services are reconciled independently (see
    #: _reconcile_option_service) since one can subscribe while the other fails.
    option_state: dict = {"stream": None, "contract": {"l1": None, "book": None}}
    #: Durable coverage-epoch row ids for the CURRENTLY active option contract — mutated
    #: by _apply_active_option_contract_subs / _schwab_connect's reconnect-reapply.
    option_epoch_state: dict = {"l1": None, "book": None}
    # PR214 premerge gap 4: the option poll loop sets this when a coverage-compensation
    # failure leaves vendor state uncertain with no durable coverage; the main loop below
    # treats it exactly like the half-open watchdog and recycles the stream.
    option_recycle_request = asyncio.Event()

    async def _start_control_tasks() -> tuple:
        """The poll loops are BOUND TO ONE STREAM GENERATION and die with it.

        They used to be created once and survive every recycle, reading whatever stream
        was current at each tick. That is what let a tick suspended inside a generation-1
        vendor await resume after generation 2 was live and mutate generation 2's vendor
        subscriptions, contract state, epoch state and durable coverage rows — measured,
        see _retire_stream_generation. Re-creating them per generation makes stale work
        impossible instead of merely unlikely: retirement cancels AND awaits them before
        any shared coverage state is touched.

        Partial construction is owned here rather than by the caller: until this returns,
        the caller has no reference to retire, so a failure building the SECOND task would
        strand the first outside every lifecycle boundary."""
        started: list = []
        try:
            started.append(asyncio.create_task(_active_ticker_book_poll_loop(
                lambda: book_state["stream"], lambda: book_state["ticker"],
                lambda t: book_state.__setitem__("ticker", t), stop)))
            started.append(asyncio.create_task(_active_option_contract_poll_loop(
                lambda: option_state["stream"], lambda: option_state["contract"],
                lambda c: option_state.__setitem__("contract", c), stop,
                writer=writer, epoch_state=option_epoch_state,
                request_recycle=option_recycle_request)))
        except BaseException:
            await _cancel_and_await(started, what="control-task construction failed")
            raise
        return tuple(started)

    deadline = time.monotonic() + duration_min * 60 if duration_min > 0 else None
    last_reconnect = time.monotonic()
    try:
        # ── INITIALIZATION IS INSIDE THE LIFECYCLE BOUNDARY ─────────────────────
        # The writer must be draining before any producer can publish, so it starts
        # first — see the ordering note on _shutdown_sequence. Delaying it until after
        # _schwab_connect() was the alternative fix and was REJECTED: _schwab_connect
        # returns an already-running pump task, so the pump would publish into a bus
        # nobody was draining. That window is small but real and entirely avoidable,
        # and it would have traded a deterministic leak for a data-loss race.
        writer_task = asyncio.create_task(writer.run(wsub, stop=stop))
        stream, pump_task, option_state["contract"] = await _schwab_connect(
            state, symbols, bus, health, stats, stop)
        book_state["stream"] = stream
        option_state["stream"] = stream
        # CR-02 prints leg — optional co-producer on the SAME bus/writer/health. NOT part
        # of a Schwab stream generation: it owns its own Alpaca socket and survives
        # recycles.
        alpaca_task = asyncio.create_task(alpaca_pump(symbols, bus, health, stats, stop))
        control_tasks = await _start_control_tasks()
        while not stop.is_set():
            await asyncio.sleep(STATUS_LOOP_INTERVAL_SEC)
            max_qdepth = max(max_qdepth, wsub.queue.qsize())
            write_status(bus, health, writer, stats, max_qdepth,
                         epoch_state=option_epoch_state)
            # half-open watchdog: quiet LEVELONE past the bar -> rebuild stream
            age = (health.report().get("LEVELONE_EQUITIES") or {}).get("age_sec")
            seen = stats.per_service.get("LEVELONE_EQUITIES", 0) > 0  # caps-ok: diagnostic unseen-count; 0 means never seen
            _coverage_forced = option_recycle_request.is_set()
            if _coverage_forced or stream_needs_recycle(
                    age, seen, time.monotonic() - last_reconnect,
                    is_capturable_session()):
                if _coverage_forced:
                    # gap 4: option coverage compensation failed — vendor state uncertain
                    # with no durable coverage. Same teardown/rebuild as the watchdog.
                    option_recycle_request.clear()
                    print("option coverage compensation failed — recycling Schwab stream "
                          "to restore a known vendor/coverage state")
                else:
                    print(f"watchdog: LEVELONE_EQUITIES quiet {age:.0f}s — recycling "
                          f"Schwab stream (half-open guard)")
                # WRITE-AHEAD RETRACTION, before the subscription actually dies below —
                # and if it cannot be written, HOLD the subscription until the standing
                # claim can no longer confirm it. A recycle is a CONTROLLED surrender: the
                # daemon picks the moment, so it can wait behind the claim's own lease
                # rather than tearing down while a positive claim is still usable. The
                # barrier runs before any teardown, so one live authority throughout.
                _claim_barrier_sec = await _surrender_claim_or_wait_out_lease(
                    writer, reason="stream_recycle")
                if _claim_barrier_sec:
                    # Recovery was deliberately delayed to avoid a false positive. Say so
                    # with a number, so an operator sees the cost rather than a mystery.
                    print(f"watchdog: recycle delayed {_claim_barrier_sec:.1f}s by the "
                          f"coverage-claim barrier (durable writes were failing)")
                # BOTH CLOCKS START AFTER THE BARRIER, and that placement is the point.
                #
                # ended_ts: coverage is surrendered when the teardown below begins, not
                # when the recycle was DECIDED. The barrier deliberately keeps the old
                # subscription alive while it waits — quotes are still arriving — so a
                # timestamp taken before it precedes the real surrender by up to the whole
                # lease. Measured at that placement: ended_ts 1.47s before the teardown
                # across a 1.47s barrier. That is an under-claim, and under-claiming is
                # not free here: rows captured during the wait would sit outside every
                # epoch, and a gap inside that window would read as "not subscribed" when
                # the daemon was subscribed and the vendor silent. Still taken BEFORE the
                # teardown, so the bounded vendor logout is never claimed as covered.
                #
                # last_reconnect: the cooldown exists to stop login-spam, so it must
                # measure the gap between reconnect ATTEMPTS. Time spent held at the
                # barrier is not time spent connected, and counting it would shorten the
                # next effective cooldown by up to the lease.
                last_reconnect = time.monotonic()
                recycle_surrendered_ts = time.time()
                book_state["stream"] = None   # poll loop must not use the dying stream
                option_state["stream"] = None
                # RETIRE THE WHOLE GENERATION FIRST — control tasks (cancelled AND
                # awaited), then the pump, then the session itself. Only after this is it
                # true that nothing else can still be suspended inside a vendor await and
                # resume into the shared coverage state we are about to rewrite.
                await _retire_stream_generation(stream, pump_task, control_tasks,
                                                reason="stream_recycle")
                stream, pump_task, control_tasks = None, None, ()
                # The dying stream's subscription window genuinely ends here — close its
                # coverage epochs now (tracked: a failed close moves the id into a
                # pending-close retry set rather than being forgotten — see
                # _close_coverage_epoch_tracked), before the reconnect attempt (which may
                # itself fail and retry next tick; the epoch table must not claim coverage
                # through a window we know the socket was down for). The vendor-held
                # bookkeeping is reset too — a fresh stream holds nothing regardless of
                # what the dying one held.
                _retry_pending_epoch_closes(writer, option_epoch_state, "l1", reason="stream_recycle")
                _retry_pending_epoch_closes(writer, option_epoch_state, "book", reason="stream_recycle")
                _close_coverage_epoch_tracked(writer, option_epoch_state, "l1", reason="stream_recycle",
                                              surrendered_ts=recycle_surrendered_ts)
                _close_coverage_epoch_tracked(writer, option_epoch_state, "book", reason="stream_recycle",
                                              surrendered_ts=recycle_surrendered_ts)
                # The RECONNECT TARGET is the operator's current desired symbol, read fresh
                # from the signal file — not the (about-to-be-discarded) per-service held
                # state, which may be stale or partially set from a prior partial failure.
                reconnect_option_contract = read_active_option_contract_signal()
                option_state["contract"] = {"l1": None, "book": None}
                try:
                    stream, pump_task, option_state["contract"] = await _schwab_connect(
                        state, symbols, bus, health, stats, stop,
                        active_book_ticker=book_state["ticker"],
                        active_option_contract=reconnect_option_contract,
                        writer=writer, epoch_state=option_epoch_state)
                    book_state["stream"] = stream
                    option_state["stream"] = stream
                except OptionCoverageCompensationError as exc:
                    # A coverage escalation is NOT an ordinary connect failure and must
                    # not be silently downgraded into one. _schwab_connect has already
                    # retired the partial session, so nothing is live; re-arm the forced
                    # recycle so the next pass rebuilds immediately instead of waiting on
                    # the half-open heuristic's cooldown, which this condition never trips.
                    print(f"watchdog: reconnect raised a COVERAGE COMPENSATION failure "
                          f"({exc}) — partial session retired; rebuild re-armed")
                    option_recycle_request.set()
                    pump_task = asyncio.create_task(asyncio.sleep(0))  # placeholder
                except Exception as exc:  # noqa: BLE001 — retry next tick, loudly
                    print(f"watchdog: reconnect FAILED ({type(exc).__name__}: {exc}) "
                          f"— retrying after cooldown")
                    pump_task = asyncio.create_task(asyncio.sleep(0))  # placeholder
                # Control tasks are re-created for the NEW generation either way: on a
                # failed reconnect both stream handles are None, so they idle harmlessly
                # until a later pass succeeds.
                control_tasks = await _start_control_tasks()
            if deadline and time.monotonic() > deadline:
                break
    except (KeyboardInterrupt, asyncio.CancelledError):
        pass
    finally:
        # ── SHUTDOWN SURRENDER BOUNDARY ─────────────────────────────────────────
        # Capture the instant continuous capture is given up, ONCE, BEFORE any teardown.
        # The shutdown sequence quiesces the producers and then drains the writer with a
        # bound of up to 60s; stamping ended_ts after that drain claimed coverage across
        # a window in which capture had already stopped and no quote could arrive. That
        # turns "our capture had already stopped" into "we remained subscribed and the
        # vendor was silent" — the same false-positive class as the transition-interval
        # defect, at the other end of the session.
        #
        # This boundary is deliberately at or BEFORE the true producer stop (a few
        # messages may still land between here and the cancel), so the ledger under-claims
        # rather than over-claims. Physical persistence happens later; the RECORDED time
        # does not move, and if the durable write has to be retried the pending-close map
        # replays this same instant.
        # WRITE-AHEAD RETRACTION, for the same reason as the recycle: capture stops below,
        # and a claim retracted only afterwards stands (and stays fresh) across the whole
        # teardown and writer drain. A clean shutdown is likewise a CONTROLLED surrender,
        # so if the retraction cannot be written the exit waits out the standing claim
        # rather than leaving one that would confirm a contract nothing holds. This is the
        # controlled path only — an uncatchable kill runs none of this, and is covered as
        # it always was by the claim's own expiry plus startup orphan reconciliation.
        await _surrender_claim_or_wait_out_lease(writer, reason="shutdown")
        # AFTER the barrier: capture is still live while it waits, so a timestamp taken
        # before it would end coverage up to a whole lease early. Measured at that
        # placement: 1.48s early across a 1.48s barrier. Still BEFORE the teardown and the
        # writer drain below, so the conservative bound this boundary has always carried
        # is unchanged — it is the same instant relative to the surrender, just no longer
        # measured from the decision to surrender instead of the surrender itself.
        shutdown_surrendered_ts = time.time()
        await _shutdown_sequence(pump_task, writer_task, stop, wsub,
                                 extra_producers=(alpaca_task, *control_tasks))
        # The daemon's own Schwab session must not outlive the daemon. _shutdown_sequence
        # cancels the pump, but a cancelled handle_message() is not a logged-out session:
        # nothing in schwab-py logs out on garbage collection, so without this the process
        # exits leaving a live session holding subscriptions on an account that allows one.
        await _retire_stream_client(stream, reason="shutdown")
        # A clean exit ends the option contract's coverage window too — an OPEN epoch
        # surviving process exit would misreport coverage through a period the daemon
        # was not even running. Tracked closes: a failure here still moves the id into
        # the pending-close set rather than discarding it — on the NEXT daemon start,
        # reconcile_open_epochs_on_start-style startup reconciliation (or, absent that,
        # the operator) can still find and close the never-cleanly-ended row rather than
        # it being silently forgotten by this process's own bookkeeping alone.
        _retry_pending_epoch_closes(writer, option_epoch_state, "l1", reason="shutdown")
        _retry_pending_epoch_closes(writer, option_epoch_state, "book", reason="shutdown")
        _close_coverage_epoch_tracked(writer, option_epoch_state, "l1", reason="shutdown",
                                      surrendered_ts=shutdown_surrendered_ts)
        _close_coverage_epoch_tracked(writer, option_epoch_state, "book", reason="shutdown",
                                      surrendered_ts=shutdown_surrendered_ts)
        for _key in ("l1", "book"):
            _pending = option_epoch_state.get(f"{_key}_pending_close")
            if _pending:
                print(f"WARNING: shutdown leaves {len(_pending)} unclosed coverage "
                      f"epoch(s) for {_key}: {sorted(_pending)} — durable write kept "
                      f"failing; row(s) remain open in stream_coverage_epochs")
        # The final status write includes a producer HEARTBEAT into stream_capture.db, so
        # it has to happen while the writer still owns its connection. It ran after the
        # close, which meant the daemon's last liveness record never landed and every
        # clean shutdown printed "write_heartbeat failed (continuing): Cannot operate on
        # a closed database". Nothing may use the writer after close — task or not.
        # Shutdown re-states the claim from the (now closed-out) epoch_state, so the final
        # persisted claim is "this producer holds nothing" rather than its last live one.
        write_status(bus, health, writer, stats, max_qdepth,
                     epoch_state=option_epoch_state)
        writer.close()
        # Counters only below: safe to read once the connection is gone.
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
