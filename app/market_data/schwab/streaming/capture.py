"""The capture daemon: the ONE Schwab streaming connection (Schwab allows one per account).

    python -m app.market_data.schwab.streaming.capture          (start_capture_daemon.bat)

It does four things, in one loop:

  1. WANTED  The console sends the complete list of what it wants streamed, per Schwab
             service, over the local console socket (live_push, ws://127.0.0.1:8799):
               {"op": "wanted", "wanted": {"LEVELONE_EQUITIES": ["SPY", ...], ...}}
             The daemon keeps the last list on disk (stream_wanted.json) so a restart
             resumes it before the console reconnects.
  2. SYNC    Every SYNC_SEC it compares wanted with what Schwab has accepted on this
             connection and sends the difference: UNSUBS for what is no longer wanted, then
             SUBS (the first request of a service) or ADD (every later one -- a repeated SUBS
             can replace the whole set). Requests are split so none exceeds Schwab's 64 KB
             message limit (measured 2026-09-22: a 71 KB request closed the socket).
             Schwab's answer to every request goes to the stream_subscriptions table. A symbol
             Schwab refused is not asked for again until the console's list changes.
  3. FAN-OUT Every Schwab message is published once on the bus: the database writer
             (stream_capture.db), the console socket (8799) and the browser price socket
             (8800) all read from it.
  4. HEALTH  Any frame from Schwab -- data or Schwab's own heartbeat -- proves the connection
             is alive. None for DEAD_SEC: reconnect with backoff and resubscribe the wanted
             list. There is nothing else to recover.

What Schwab offers (probed live 2026-09-25): LEVELONE_EQUITIES, CHART_EQUITY, NYSE_BOOK
(exchange book), NASDAQ_BOOK (market-maker quotes), LEVELONE_OPTIONS, OPTIONS_BOOK and
NEWS_HEADLINE answer code 0; both books accepted 30 symbols. TIMESALE_* and ACTIVES_* answer
code 11 (not available) -- there is no trade-by-trade tape and no trade side.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))

from stream_spine import (  # noqa: E402
    COUNT_DROPS,
    CaptureWriter,
    HealthRegistry,
    MessageBus,
    bar_msg,
    book_msg,
    news_msg,
    options_quote_msg,
    quote_msg,
    resolve_stream_db_path,
    subscription_msg,
)

#: Seconds between wanted-vs-held comparisons. It is also the debounce: a burst of console
#: updates inside one interval becomes one set of Schwab requests.
SYNC_SEC = 0.25
#: No frame at all from Schwab (data or heartbeat) for this long -> the connection is dead.
DEAD_SEC = 30.0
#: Reconnect waits, in order; the last repeats.
RECONNECT_BACKOFF_SEC = (1.0, 2.0, 5.0, 10.0, 30.0, 60.0)
#: Schwab closes the socket on a request over 65,535 bytes; stay well under it.
MAX_REQUEST_BYTES = 48_000
#: A request Schwab does not answer in this long means the connection is broken.
REQUEST_TIMEOUT_SEC = 15.0

SERVICES = ("LEVELONE_EQUITIES", "CHART_EQUITY", "NYSE_BOOK", "NASDAQ_BOOK",
            "LEVELONE_OPTIONS", "OPTIONS_BOOK", "NEWS_HEADLINE")

#: LEVELONE_EQUITIES / CHART_EQUITY fields copied into the database's flat columns (the full
#: Schwab item is kept verbatim beside them in native_json).
LEVELONE_FIELDS = {"BID_PRICE": "bid", "ASK_PRICE": "ask", "LAST_PRICE": "last",
                   "BID_SIZE": "bid_size", "ASK_SIZE": "ask_size",
                   "TOTAL_VOLUME": "total_volume", "LAST_SIZE": "last_size",
                   "QUOTE_TIME_MILLIS": "quote_time_ms", "TRADE_TIME_MILLIS": "trade_time_ms"}
CHART_FIELDS = {"OPEN_PRICE": "open", "HIGH_PRICE": "high", "LOW_PRICE": "low",
                "CLOSE_PRICE": "close", "VOLUME": "volume", "CHART_TIME_MILLIS": "bar_start_ms"}
#: NEWS_HEADLINE is not in the Streamer Guide and schwab-py has no helper for it; these are
#: the fields it answered with on 2026-09-25 (time, id, ..., headline, ..., categories).
NEWS_FIELDS = tuple(range(0, 11))


# ---------------------------------------------------------------------------- the wanted list

def wanted_path(db_path: "Path | str | None" = None) -> Path:
    return resolve_stream_db_path(db_path).with_name("stream_wanted.json")


def normalize_wanted(raw) -> "dict[str, frozenset[str]]":
    """{service: frozenset(symbols)} for the known services; anything else is ignored."""
    out: "dict[str, frozenset[str]]" = {s: frozenset() for s in SERVICES}
    if isinstance(raw, dict):
        for svc in SERVICES:
            syms = raw.get(svc)
            if isinstance(syms, list):
                out[svc] = frozenset(str(s).strip().upper() for s in syms if str(s).strip())
    return out


def load_wanted(path: Path) -> "dict[str, frozenset[str]]":
    try:
        return normalize_wanted(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, ValueError):
        return normalize_wanted(None)


def save_wanted(path: Path, wanted: "dict[str, frozenset[str]]") -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps({s: sorted(v) for s, v in wanted.items()}), encoding="utf-8")
    os.replace(tmp, path)


def plan(wanted: "dict[str, frozenset[str]]", held: "dict[str, frozenset[str]]",
         refused: "dict[str, dict[str, str]]") -> "list[tuple[str, str, list[str]]]":
    """The Schwab requests that turn `held` into `wanted`: [(service, command, symbols)].
    Per service: UNSUBS what is held but not wanted, then SUBS (nothing held yet) or ADD the
    wanted symbols not held and not refused. Pure function -- the whole sync decision."""
    out: "list[tuple[str, str, list[str]]]" = []
    for svc in SERVICES:
        want, have = wanted.get(svc, frozenset()), held.get(svc, frozenset())
        drop = sorted(have - want)
        add = sorted(want - have - set(refused.get(svc, {})))
        if drop:
            out.append((svc, "UNSUBS", drop))
        if add:
            out.append((svc, "ADD" if have - set(drop) else "SUBS", add))
    return out


def split_request(symbols: "list[str]", max_bytes: int = MAX_REQUEST_BYTES) -> "list[list[str]]":
    """Chunks whose comma-joined key list stays under max_bytes."""
    chunks: "list[list[str]]" = []
    cur: "list[str]" = []
    size = 0
    for s in symbols:
        n = len(s) + 1
        if cur and size + n > max_bytes:
            chunks.append(cur)
            cur, size = [], 0
        cur.append(s)
        size += n
    if cur:
        chunks.append(cur)
    return chunks


# ---------------------------------------------------------------------------- Schwab messages

def _publish_equity(service: str, bus: MessageBus, health: HealthRegistry):
    def handler(msg: dict) -> None:
        published = False
        for item in msg.get("content") or []:
            sym = str(item.get("key") or "").upper() if isinstance(item, dict) else ""
            if not sym:
                continue
            if service == "LEVELONE_EQUITIES":
                f = {name: item.get(k) for k, name in LEVELONE_FIELDS.items()}
                bus.publish(f"quote.{sym}", quote_msg(symbol=sym, src="schwab_l1", native=item, **f))
            else:
                f = {name: item.get(k) for k, name in CHART_FIELDS.items()}
                bus.publish(f"bar1m.{sym}", bar_msg(symbol=sym, src="schwab_chart", **f))
            published = True
        if published:           # alive = data delivered, not merely a frame (audit of #280)
            health.beat(service)
    return handler


def _publish_book(service: str, bus: MessageBus, health: HealthRegistry):
    def handler(msg: dict) -> None:
        published = False
        for item in msg.get("content") or []:
            sym = str(item.get("key") or "").upper() if isinstance(item, dict) else ""
            if sym:
                bus.publish(f"book.{sym}", book_msg(symbol=sym, service=service, content=item,
                                                    src="schwab_book"))
                published = True
        if published:
            health.beat(service)
    return handler


def _publish_option_quote(bus: MessageBus, health: HealthRegistry):
    def handler(msg: dict) -> None:
        published = False
        for item in msg.get("content") or []:
            sym = str(item.get("key") or "").upper() if isinstance(item, dict) else ""
            if sym:
                bus.publish(f"optquote.{sym}", options_quote_msg(symbol=sym, content=item,
                                                                 src="schwab_options_l1"))
                published = True
        if published:
            health.beat("LEVELONE_OPTIONS")
    return handler


def _publish_news(bus: MessageBus, health: HealthRegistry):
    def handler(msg: dict) -> None:
        published = False
        for item in msg.get("content") or []:
            sym = str(item.get("key") or "").upper() if isinstance(item, dict) else ""
            if sym:
                bus.publish(f"news.{sym}", news_msg(symbol=sym, content=item, src="schwab_news"))
                published = True
        if published:
            health.beat("NEWS_HEADLINE")
    return handler


class _RawHandler:
    """schwab-py handler shape for a service it has no helper for (NEWS_HEADLINE)."""

    def __init__(self, fn) -> None:
        self.fn = fn

    def label_message(self, msg: dict) -> dict:
        return msg

    def __call__(self, msg: dict):
        return self.fn(msg)


def _open_stream(client):
    """schwab-py's StreamClient, recording the time of every frame Schwab sends -- data,
    responses and Schwab's heartbeats alike. That one timestamp is the liveness test."""
    from schwab.streaming import StreamClient
    stream = StreamClient(client)
    stream.last_frame_ts = time.time()
    receive = stream._receive

    async def timed_receive():
        msg = await receive()
        stream.last_frame_ts = time.time()
        return msg
    stream._receive = timed_receive
    return stream


def _fields(stream, service: str) -> str:
    if service == "NEWS_HEADLINE":
        return ",".join(str(f) for f in NEWS_FIELDS)
    enum = {"LEVELONE_EQUITIES": stream.LevelOneEquityFields,
            "CHART_EQUITY": stream.ChartEquityFields,
            "LEVELONE_OPTIONS": stream.LevelOneOptionFields}.get(service, stream.BookFields)
    return ",".join(str(f) for f in sorted(int(x.value) for x in enum))


async def _request(stream, service: str, command: str, symbols: "list[str]") -> None:
    """One Schwab request; raises (schwab-py UnexpectedResponse / connection errors) unless
    Schwab answers code 0. Every service goes through this one path, including NEWS_HEADLINE."""
    params = {"keys": ",".join(symbols)}
    if command != "UNSUBS":
        params["fields"] = _fields(stream, service)
    req, rid = stream._make_request(service=service, command=command, parameters=params)

    async def send_and_wait() -> None:
        async with stream._lock:
            await stream._send({"requests": [req]})
            await stream._await_response(rid, service, command)
    try:
        await asyncio.wait_for(send_and_wait(), timeout=REQUEST_TIMEOUT_SEC)
    except asyncio.TimeoutError:
        raise ConnectionError(f"no answer to {service} {command} in {REQUEST_TIMEOUT_SEC:.0f} s") from None


def _connection_lost(e: BaseException) -> bool:
    """The socket itself is gone (as opposed to Schwab refusing one request)."""
    from websockets.exceptions import ConnectionClosed
    return isinstance(e, (ConnectionClosed, ConnectionError, OSError, asyncio.IncompleteReadError))


# ---------------------------------------------------------------------------- the daemon

class Daemon:
    def __init__(self, bus: MessageBus, health: HealthRegistry, path: Path) -> None:
        self.bus = bus
        self.health = health
        self.path = path
        self.wanted = load_wanted(path)
        self.held: "dict[str, frozenset[str]]" = {s: frozenset() for s in SERVICES}
        self.refused: "dict[str, dict[str, str]]" = {s: {} for s in SERVICES}
        self.stream = None
        self.connected_ts: "float | None" = None

    def set_wanted(self, raw) -> None:
        """The console's list (live_push calls this for every {"op": "wanted"} frame)."""
        new = normalize_wanted(raw)
        if new == self.wanted:
            return
        for svc in SERVICES:                       # a changed list gets one fresh try
            if new[svc] != self.wanted[svc]:
                self.refused[svc] = {}
        self.wanted = new
        try:
            save_wanted(self.path, new)
        except OSError as e:
            print(f"could not save {self.path.name}: {e}")

    def status(self) -> dict:
        """What the console and browsers are told every second (live_push / live_ui)."""
        now = time.time()
        last = self.stream.last_frame_ts if self.stream is not None else 0.0
        return {"ts": now,
                "schwab_socket_open": bool(last) and now - last < DEAD_SEC,
                "last_frame_age_sec": round(now - last, 2) if last else None,
                "connected_ts": self.connected_ts,
                "equities_held": sorted(self.held["LEVELONE_EQUITIES"]),
                "held": {k: sorted(v) for k, v in self.held.items()},
                "refused": {k: dict(v) for k, v in self.refused.items() if v},
                "health": self.health.report(),
                "drops": self.bus.drop_counts()}

    async def sync(self) -> None:
        for svc, cmd, symbols in plan(self.wanted, self.held, self.refused):
            for chunk in split_request(symbols):
                try:
                    await _request(self.stream, svc, cmd, chunk)
                    code, reason = 0, "ok"
                except Exception as e:       # noqa: BLE001 -- Schwab said no, or the socket died
                    if _connection_lost(e):
                        raise
                    code, reason = -1, f"{type(e).__name__}: {e}"[:300]
                self.bus.publish(f"sub.{svc}", subscription_msg(
                    service=svc, command=cmd, symbols=chunk, code=code, reason=reason))
                if code == 0:
                    held = set(self.held[svc])
                    held = held - set(chunk) if cmd == "UNSUBS" else held | set(chunk)
                    self.held[svc] = frozenset(held)
                else:
                    print(f"{svc} {cmd} refused ({len(chunk)} symbols): {reason}")
                    if cmd != "UNSUBS":
                        self.refused[svc].update({sym: reason for sym in chunk})

    async def connect(self, client) -> None:
        stream = _open_stream(client)
        await stream.login()
        stream.add_level_one_equity_handler(_publish_equity("LEVELONE_EQUITIES", self.bus, self.health))
        stream.add_chart_equity_handler(_publish_equity("CHART_EQUITY", self.bus, self.health))
        stream.add_nyse_book_handler(_publish_book("NYSE_BOOK", self.bus, self.health))
        stream.add_nasdaq_book_handler(_publish_book("NASDAQ_BOOK", self.bus, self.health))
        stream.add_options_book_handler(_publish_book("OPTIONS_BOOK", self.bus, self.health))
        stream.add_level_one_option_handler(_publish_option_quote(self.bus, self.health))
        stream._handlers["NEWS_HEADLINE"].append(_RawHandler(_publish_news(self.bus, self.health)))
        self.stream = stream
        self.held = {s: frozenset() for s in SERVICES}    # a new connection holds nothing
        self.connected_ts = time.time()
        print("schwab: connected")

    async def disconnect(self) -> None:
        s, self.stream = self.stream, None
        self.held = {k: frozenset() for k in SERVICES}
        if s is not None:
            try:
                await asyncio.wait_for(s.logout(), timeout=5)
            except Exception:  # noqa: BLE001 -- it is being thrown away either way
                pass

    async def read_for(self, seconds: float) -> None:
        """Handle Schwab frames for `seconds`. One task does both reading and requesting, so
        a request never waits behind a reader holding schwab-py's lock (websockets' recv is
        safe to cancel, so the timeout never loses a frame)."""
        end = time.monotonic() + seconds
        while (left := end - time.monotonic()) > 0:
            try:
                await asyncio.wait_for(self.stream.handle_message(), timeout=left)
            except asyncio.TimeoutError:
                return
            except Exception as e:  # noqa: BLE001
                if _connection_lost(e):
                    raise
                print(f"schwab: skipped a frame ({type(e).__name__}: {e})"[:300])

    async def run_connection(self, client, stop: asyncio.Event) -> None:
        """One connection's life: sync, read, repeat -- until it dies or stop is set."""
        await self.connect(client)
        try:
            while not stop.is_set():
                if time.time() - self.stream.last_frame_ts > DEAD_SEC:
                    raise ConnectionError(f"no frame from Schwab for {DEAD_SEC:.0f} s")
                await self.sync()
                await self.read_for(SYNC_SEC)
        finally:
            await self.disconnect()

    async def run(self, make_client, stop: asyncio.Event) -> None:
        """Connect, and reconnect with backoff whenever the connection ends, until stop."""
        failures = 0
        while not stop.is_set():
            started = time.time()
            try:
                state = make_client()
                if not state.ok or state.client is None:
                    raise ConnectionError(f"Schwab client: {state.message}")
                await self.run_connection(state.client, stop)
            except Exception as e:  # noqa: BLE001 -- every failure is a reconnect
                print(f"schwab: connection ended ({type(e).__name__}: {e})"[:400])
            if stop.is_set():
                break
            # a connection that lasted 5 minutes starts the backoff over
            failures = 1 if time.time() - started > 300 else failures + 1
            wait = RECONNECT_BACKOFF_SEC[min(failures, len(RECONNECT_BACKOFF_SEC)) - 1]
            print(f"schwab: reconnecting in {wait:.0f} s")
            try:
                await asyncio.wait_for(stop.wait(), timeout=wait)
            except asyncio.TimeoutError:
                pass


# ---------------------------------------------------------------------------- process

def owner_lock_path(db_path: "str | Path | None" = None) -> Path:
    """Beside the stream database, so a worktree and production can never both stream."""
    return resolve_stream_db_path(db_path).with_name("stream_capture.lock")


#: Exit code when another daemon already owns the stream (start_capture_daemon.bat stops its
#: restart loop on it). 2 is the live-binding refusal (runtime_layout).
EXIT_OWNER_LOCK_HELD = 3


def acquire_owner_lock(db_path: "str | Path | None" = None) -> "tuple[int, Path]":
    """Exclusive pidfile: one daemon at a time; a lock left by a dead process is reclaimed."""
    import psutil
    lock = owner_lock_path(db_path)
    lock.parent.mkdir(parents=True, exist_ok=True)
    for attempt in (1, 2):
        try:
            fd = os.open(str(lock), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(fd, str(os.getpid()).encode())
            return fd, lock
        except FileExistsError:
            try:
                pid = int(lock.read_text().strip() or 0)  # caps-ok: an empty pidfile is not a live owner
            except (OSError, ValueError):
                pid = 0
            if pid and psutil.pid_exists(pid):
                print(f"FATAL: another capture daemon holds {lock} (pid {pid}).",
                      file=sys.stderr, flush=True)
                raise SystemExit(EXIT_OWNER_LOCK_HELD) from None
            if attempt == 1:
                lock.unlink(missing_ok=True)
    raise SystemExit(f"FATAL: could not acquire {lock}")


def release_owner_lock(fd: int, lock: Path) -> None:
    try:
        os.close(fd)
    finally:
        lock.unlink(missing_ok=True)


class _TimestampedLog:
    """Line-buffered append log that stamps each line with local wall time."""

    def __init__(self, fh) -> None:
        self._fh = fh
        self._at_line_start = True

    def write(self, text: str) -> int:
        out = []
        for part in text.splitlines(keepends=True):
            if self._at_line_start and part.strip():
                out.append(time.strftime("%Y-%m-%d %H:%M:%S "))
            out.append(part)
            self._at_line_start = part.endswith("\n")
        self._fh.write("".join(out))
        self._fh.flush()
        return len(text)

    def flush(self) -> None:
        self._fh.flush()


STREAM_CAPTURE_LOG_MAX_BYTES = 50 * 1024 * 1024


def _ensure_daemon_output_is_recorded() -> "Path | None":
    """Under pythonw.exe there is no stdout/stderr and every print() would vanish (measured
    2026-09-23: 42 socket deaths, not one reason on disk). Then output goes to
    <runtime>/logs/stream_capture.log (one rotation at 50 MB)."""
    if sys.stdout is not None and sys.stderr is not None:
        return None
    from runtime_layout import logs_dir
    path = logs_dir() / "stream_capture.log"
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        if path.exists() and path.stat().st_size > STREAM_CAPTURE_LOG_MAX_BYTES:
            path.replace(path.with_suffix(".log.1"))
    except OSError:
        pass
    sink = _TimestampedLog(open(path, "a", encoding="utf-8", buffering=1))
    if sys.stdout is None:
        sys.stdout = sink
    if sys.stderr is None:
        sys.stderr = sink
    return path


async def run(db_path: "Path | str | None" = None, *, make_client=None,
              stop: "asyncio.Event | None" = None) -> int:
    """The whole daemon. `make_client` / `stop` are injectable for tests."""
    from app.market_data.schwab.streaming.live_push import serve_live_push
    from app.market_data.schwab.streaming.live_ui import serve_live_ui

    if make_client is None:
        from config import build_config
        from schwab_client import build_client_from_token
        cfg = build_config(str(ROOT))

        def make_client():
            return build_client_from_token(api_key=cfg.api_key, app_secret=cfg.app_secret,
                                           token_path=cfg.token_path)

    stop = stop or asyncio.Event()
    bus, health = MessageBus(), HealthRegistry()
    writer = CaptureWriter(db_path)
    daemon = Daemon(bus, health, wanted_path(db_path))
    wsub = bus.subscribe("", policy=COUNT_DROPS, maxsize=8192, name="db_writer")
    tasks = [asyncio.create_task(writer.run(wsub, stop=stop)),
             asyncio.create_task(serve_live_push(bus, stop, heartbeat_fn=daemon.status,
                                                 on_wanted=daemon.set_wanted)),
             asyncio.create_task(serve_live_ui(bus, stop, heartbeat_fn=daemon.status))]
    try:
        await asyncio.sleep(0)                    # servers subscribe before the first message
        await daemon.run(make_client, stop)
    finally:
        stop.set()
        await asyncio.gather(*tasks, return_exceptions=True)
    return 0


def main() -> int:
    argparse.ArgumentParser(description=__doc__).parse_args()
    # A worktree must not run a live daemon against production's runtime
    # (runtime_layout.live_binding_error, 2026-09-25).
    from runtime_layout import live_binding_error
    binding = live_binding_error()
    if binding is not None:
        print(f"CAPTURE DAEMON REFUSED: {binding}", file=sys.stderr, flush=True)
        return 2
    _ensure_daemon_output_is_recorded()
    fd, lock = acquire_owner_lock()
    try:
        return asyncio.run(run())
    except KeyboardInterrupt:
        return 0
    finally:
        release_owner_lock(fd, lock)


if __name__ == "__main__":
    raise SystemExit(main())
