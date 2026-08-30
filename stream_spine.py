"""CR-01 streaming spine: topic bus + last-value cache + capture writer + feed health.

Consensus plan v1.2 (governance/CONSOLE_REBUILD_PLAN_CR_V1.md §4). Laws encoded here:
  - cache-then-publish: the cache is written BEFORE subscribers are notified, so any
    consumer can snapshot-then-ride-deltas without a poll-to-hydrate step.
  - every queue is BOUNDED with an explicit policy: quotes coalesce-to-latest,
    prints are NEVER coalesced (drops are counted and surface in health).
  - raw streams write ONLY to stream_capture.db — ed_console.db grows zero bytes.
  - health is first-class: a stale feed must look different from a quiet market.

Pure asyncio; no Schwab/Alpaca imports here. The capture daemon (tools/) plugs feed
clients into `MessageBus.publish` and runs `CaptureWriter.run` + `HealthRegistry`.
"""

from __future__ import annotations

import asyncio
import json
import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

STREAM_DB_DEFAULT = Path(__file__).resolve().parent / "data" / "stream_capture.db"

#: Cross-process signal: the server process (one active UI viewer's ticker) writes here;
#: the canonical daemon polls it to dynamically add/drop book-depth subscription for that
#: one symbol. This is the ONLY channel by which the server influences the daemon's Schwab
#: subscriptions — it never opens its own StreamClient (single-stream-authority law).
ACTIVE_TICKER_SIGNAL_DEFAULT = Path(__file__).resolve().parent / "data" / "stream_active_ticker.json"

#: Queue policies. COALESCE keeps only the newest pending message per topic (quotes).
#: COUNT_DROPS rejects new messages when full and counts them loudly (prints).
COALESCE = "coalesce"
COUNT_DROPS = "count_drops"

STREAM_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS stream_quotes_raw (
    ts_recv REAL NOT NULL,
    symbol TEXT NOT NULL,
    bid REAL, ask REAL, last REAL,
    bid_size INTEGER, ask_size INTEGER, last_size INTEGER,
    total_volume INTEGER,
    quote_time_ms INTEGER, trade_time_ms INTEGER,
    src TEXT NOT NULL,
    native_json TEXT
);
CREATE INDEX IF NOT EXISTS idx_sqr_sym_ts ON stream_quotes_raw(symbol, ts_recv);
CREATE TABLE IF NOT EXISTS stream_book_raw (
    ts_recv REAL NOT NULL,
    symbol TEXT NOT NULL,
    service TEXT NOT NULL,
    native_json TEXT NOT NULL,
    src TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_sbkr_sym_ts ON stream_book_raw(symbol, ts_recv);
CREATE TABLE IF NOT EXISTS stream_prints_raw (
    ts_recv REAL NOT NULL,
    symbol TEXT NOT NULL,
    price REAL, size INTEGER,
    exchange TEXT, conditions TEXT,
    trade_ts_ms INTEGER,
    src TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_spr_sym_ts ON stream_prints_raw(symbol, ts_recv);
CREATE TABLE IF NOT EXISTS stream_bars_raw (
    ts_recv REAL NOT NULL,
    symbol TEXT NOT NULL,
    bar_start_ms INTEGER,
    open REAL, high REAL, low REAL, close REAL, volume INTEGER,
    src TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_sbr_sym_ts ON stream_bars_raw(symbol, bar_start_ms);
"""


def quote_msg(*, symbol: str, bid=None, ask=None, last=None, bid_size=None, ask_size=None,
              last_size=None, total_volume=None, quote_time_ms=None, trade_time_ms=None,
              src: str, ts_recv: float | None = None, native: dict | None = None) -> dict:
    """The ONE producer shape for quote.* topics — daemon and tests both build through
    here so the writer's reads and the producers' writes can never drift (RC-15 class).

    ``native``: the Schwab content-item dict verbatim, when the caller has it (e.g. a
    LEVEL_ONE_EQUITY handler). Stored alongside the flattened columns so a downstream
    consumer that needs FIELD FIDELITY (e.g. live-plane hydration, which reads
    BID_TIME_MILLIS / REGULAR_MARKET_CHANGE_PERCENT — fields the flattened columns do
    not carry) is not forced to re-derive a lossy approximation from them. Optional:
    existing quote producers that lack the native dict are unaffected."""
    return {"ts_recv": ts_recv if ts_recv is not None else time.time(), "symbol": symbol,
            "bid": bid, "ask": ask, "last": last, "bid_size": bid_size,
            "ask_size": ask_size, "last_size": last_size, "total_volume": total_volume,
            "quote_time_ms": quote_time_ms, "trade_time_ms": trade_time_ms, "src": src,
            "native": native}


def book_msg(*, symbol: str, service: str, content: dict, src: str,
             ts_recv: float | None = None) -> dict:
    """The ONE producer shape for book.* topics (NASDAQ_BOOK / NYSE_BOOK).

    ``content`` is the Schwab content-item dict verbatim (BIDS/ASKS/BOOK_TIME) — stored
    as-is, never flattened, since book depth has no meaningful scalar projection."""
    return {"ts_recv": ts_recv if ts_recv is not None else time.time(), "symbol": symbol,
            "service": service, "content": content, "src": src}


def write_active_ticker_signal(ticker: str, *, path: Path = ACTIVE_TICKER_SIGNAL_DEFAULT) -> None:
    """The server's ONE write into the daemon's book-subscription decision.

    Atomic (write-temp-then-replace): the daemon polls this file on its own schedule and
    must never observe a half-written JSON body."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps({"ticker": (ticker or "").upper().strip(),
                               "requested_at": time.time()}), encoding="utf-8")
    tmp.replace(path)


def read_active_ticker_signal(*, path: Path = ACTIVE_TICKER_SIGNAL_DEFAULT) -> str | None:
    """The daemon's read of the server's requested active ticker. None on any absence/
    corruption — a missing signal means 'no book subscription', never a guessed symbol."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    t = str(data.get("ticker") or "").upper().strip()
    return t or None


def print_msg(*, symbol: str, price=None, size=None, exchange=None, conditions=None,
              trade_ts_ms=None, src: str, ts_recv: float | None = None) -> dict:
    return {"ts_recv": ts_recv if ts_recv is not None else time.time(), "symbol": symbol,
            "price": price, "size": size, "exchange": exchange, "conditions": conditions,
            "trade_ts_ms": trade_ts_ms, "src": src}


def bar_msg(*, symbol: str, bar_start_ms=None, open=None, high=None, low=None, close=None,  # noqa: A002
            volume=None, src: str, ts_recv: float | None = None) -> dict:
    return {"ts_recv": ts_recv if ts_recv is not None else time.time(), "symbol": symbol,
            "bar_start_ms": bar_start_ms, "open": open, "high": high, "low": low,
            "close": close, "volume": volume, "src": src}


@dataclass
class Subscription:
    prefix: str
    policy: str
    queue: asyncio.Queue
    #: COALESCE keeps the newest pending message per exact topic here instead of the queue.
    pending: dict[str, Any] = field(default_factory=dict)
    dropped: int = 0

    def deliver(self, topic: str, msg: Any) -> None:
        if self.policy == COALESCE:
            # Newest wins per topic; the queue carries topic keys, payload rides pending.
            fresh = topic not in self.pending
            self.pending[topic] = msg
            if fresh:
                try:
                    self.queue.put_nowait(topic)
                except asyncio.QueueFull:
                    self.pending.pop(topic, None)
                    self.dropped += 1
            return
        try:
            self.queue.put_nowait((topic, msg))
        except asyncio.QueueFull:
            self.dropped += 1

    async def get(self) -> tuple[str, Any]:
        item = await self.queue.get()
        if self.policy == COALESCE:
            topic = item
            return topic, self.pending.pop(topic)
        return item


class MessageBus:
    """Topic pub/sub with a last-value cache written BEFORE publish (cache-then-publish)."""

    def __init__(self) -> None:
        self._subs: list[Subscription] = []
        self.cache: dict[str, Any] = {}
        self.published = 0

    def subscribe(self, prefix: str, *, policy: str = COUNT_DROPS, maxsize: int = 2048) -> Subscription:
        sub = Subscription(prefix=prefix, policy=policy, queue=asyncio.Queue(maxsize=maxsize))
        self._subs.append(sub)
        return sub

    def publish(self, topic: str, msg: Any) -> None:
        self.cache[topic] = msg
        self.published += 1
        for sub in self._subs:
            if topic.startswith(sub.prefix):
                sub.deliver(topic, msg)

    def snapshot(self, prefix: str = "") -> dict[str, Any]:
        return {t: v for t, v in self.cache.items() if t.startswith(prefix)}

    def drop_counts(self) -> dict[str, int]:
        return {s.prefix: s.dropped for s in self._subs if s.dropped}


#: Health thresholds (seconds since last message). DEGRADED warns; STALE is the
#: fail-closed state that CR-07's law hooks (STALE -> directional prompts suppressed).
HEALTH_DEGRADED_SEC = 5.0
HEALTH_STALE_SEC = 30.0


class HealthRegistry:
    """Per-feed liveness: RUNNING / DEGRADED / STALE / DOWN, judged by message age."""

    def __init__(self) -> None:
        self._last: dict[str, float] = {}

    def beat(self, feed: str, ts: float | None = None) -> None:
        self._last[feed] = ts if ts is not None else time.time()

    def state(self, feed: str, now: float | None = None) -> str:
        last = self._last.get(feed)
        if last is None:
            return "DOWN"
        age = (now if now is not None else time.time()) - last
        if age <= HEALTH_DEGRADED_SEC:
            return "RUNNING"
        if age <= HEALTH_STALE_SEC:
            return "DEGRADED"
        return "STALE"

    def report(self, now: float | None = None) -> dict[str, dict]:
        t = now if now is not None else time.time()
        return {
            f: {"state": self.state(f, t), "age_sec": round(t - ts, 3)}
            for f, ts in self._last.items()
        }

    def any_stale(self, now: float | None = None) -> bool:
        return any(v["state"] in ("STALE", "DOWN") for v in self.report(now).values())


class CaptureWriter:
    """Single writer draining bus subscriptions into stream_capture.db in batches.

    NEVER points at ed_console.db — guarded at construction, not by convention.
    Commit every `batch_rows` rows or `batch_sec`, whichever first.
    """

    def __init__(self, db_path: Path | str = STREAM_DB_DEFAULT, *,
                 batch_rows: int = 500, batch_sec: float = 0.25) -> None:
        # RESOLVED path, not basename: `data/x/../ed_console.db`, symlinks and junctions
        # all collapse under resolve() (Cursor review 2026-07-21: basename-only guard
        # was bypassable — an RC-6 law hole).
        p = Path(db_path).resolve()
        if p.name == "ed_console.db":
            raise ValueError("CaptureWriter must never write the operational DB (RC-6 law)")
        p.parent.mkdir(parents=True, exist_ok=True)
        self.db_path = p
        self.batch_rows = int(batch_rows)
        self.batch_sec = float(batch_sec)
        self.rows_written = 0
        self.commits = 0
        self.insert_errors = 0
        self._closed = False
        self._conn = sqlite3.connect(str(p))
        try:
            self._conn.executescript("PRAGMA journal_mode=WAL; PRAGMA synchronous=NORMAL;")
            self._conn.executescript(STREAM_SCHEMA_SQL)
            # CREATE TABLE IF NOT EXISTS does not add columns to a table that already
            # exists from a prior daemon run. Migrate forward, idempotently.
            cols = {r[1] for r in self._conn.execute("PRAGMA table_info(stream_quotes_raw)")}
            if "native_json" not in cols:
                self._conn.execute("ALTER TABLE stream_quotes_raw ADD COLUMN native_json TEXT")
            self._conn.commit()
        except Exception:
            # Init failed after connect — close before the object is discarded so the
            # SQLite handle cannot leak until GC (Bugbot 2026-07-21 HIGH).
            self._conn.close()
            self._closed = True
            raise

    def insert(self, topic: str, msg: dict) -> None:
        kind = topic.split(".", 1)[0]
        if kind == "quote":
            native = msg.get("native")
            self._conn.execute(
                "INSERT INTO stream_quotes_raw(ts_recv,symbol,bid,ask,last,bid_size,ask_size,"
                "last_size,total_volume,quote_time_ms,trade_time_ms,src,native_json) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (msg.get("ts_recv"), msg.get("symbol"), msg.get("bid"), msg.get("ask"),
                 msg.get("last"), msg.get("bid_size"), msg.get("ask_size"), msg.get("last_size"),
                 msg.get("total_volume"), msg.get("quote_time_ms"), msg.get("trade_time_ms"),
                 msg.get("src", "?"),  # caps-ok: src is a required kwarg on quote_msg (no default); "?" only guards a dict built outside that constructor, never a legitimately-absent value
                 json.dumps(native) if native is not None else None))
        elif kind == "book":
            content = msg.get("content")
            if content is None:
                return
            self._conn.execute(
                "INSERT INTO stream_book_raw(ts_recv,symbol,service,native_json,src) "
                "VALUES(?,?,?,?,?)",
                (msg.get("ts_recv"), msg.get("symbol"), msg.get("service"),
                 json.dumps(content),
                 msg.get("src", "?")))  # caps-ok: src is a required kwarg on book_msg (no default); same guard as the quote branch above
        elif kind == "print":
            self._conn.execute(
                "INSERT INTO stream_prints_raw(ts_recv,symbol,price,size,exchange,conditions,"
                "trade_ts_ms,src) VALUES(?,?,?,?,?,?,?,?)",
                (msg.get("ts_recv"), msg.get("symbol"), msg.get("price"), msg.get("size"),
                 msg.get("exchange"), msg.get("conditions"), msg.get("trade_ts_ms"),
                 msg.get("src", "?")))  # caps-ok: src is a required kwarg on print_msg (no default); same guard as the quote branch above
        elif kind == "bar1m":
            self._conn.execute(
                "INSERT INTO stream_bars_raw(ts_recv,symbol,bar_start_ms,open,high,low,close,"
                "volume,src) VALUES(?,?,?,?,?,?,?,?,?)",
                (msg.get("ts_recv"), msg.get("symbol"), msg.get("bar_start_ms"), msg.get("open"),
                 msg.get("high"), msg.get("low"), msg.get("close"), msg.get("volume"),
                 msg.get("src", "?")))  # caps-ok: src is a required kwarg on bar_msg (no default); same guard as the quote branch above
        else:
            return
        self.rows_written += 1

    def commit(self) -> None:
        self._conn.commit()
        self.commits += 1

    def _insert_guarded(self, topic: str, msg: Any) -> int:
        """1 if a row landed; insert failures are COUNTED, never kill the writer
        (Cursor review MEDIUM: an uncaught insert() death silently stopped capture)."""
        try:
            before = self.rows_written
            self.insert(topic, msg)
            return self.rows_written - before
        except Exception:  # noqa: BLE001 — counted + surfaced in status; capture continues
            self.insert_errors += 1
            return 0

    async def run(self, sub: Subscription, *, stop: asyncio.Event) -> None:
        pending = 0
        last_commit = time.monotonic()
        while not stop.is_set():
            timeout = max(self.batch_sec - (time.monotonic() - last_commit), 0.01)
            try:
                topic, msg = await asyncio.wait_for(sub.get(), timeout=timeout)
                pending += self._insert_guarded(topic, msg)
            except asyncio.TimeoutError:
                pass
            if pending and (pending >= self.batch_rows
                            or time.monotonic() - last_commit >= self.batch_sec):
                self.commit()
                pending = 0
                last_commit = time.monotonic()
        # DRAIN on stop — Cursor review HIGH: stopping must not vaporize up to a full
        # queue of buffered rows. Everything already delivered to the subscription is
        # written and committed before the writer exits.
        while not sub.queue.empty():
            topic, msg = await sub.get()
            pending += self._insert_guarded(topic, msg)
        if pending:
            self.commit()

    def close(self) -> None:
        """Idempotent — the daemon closes in a finally that may run after an inner
        close (Cursor round-3 MEDIUM: login-failure paths leaked the connection).

        Commit-then-close: `_closed` is set only after both attempts so a failed
        commit cannot skip a later close and leak the handle (Bugbot 2026-07-21)."""
        if self._closed:
            return
        try:
            self._conn.commit()
        finally:
            try:
                self._conn.close()
            finally:
                self._closed = True
