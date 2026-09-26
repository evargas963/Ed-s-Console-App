"""The pieces the capture daemon and its readers share: the stream database path and schema,
the message shapes, the in-process message bus, feed health, and the database writer.

  - Every Schwab message is published once on the MessageBus; the writer, the console socket
    and the browser socket each read their own bounded queue from it (drops are counted).
  - Raw stream data goes ONLY to stream_capture.db -- ed_console.db is never written here.
  - The writer runs on its own thread with its own SQLite connection, so a slow disk can
    never stall the Schwab socket (measured 2026-09-23: in-loop commits dropped 9,784 msgs).
"""
from __future__ import annotations

import asyncio
import json
import queue
import sqlite3
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from db_authority import canonical_stream_db_path

STREAM_DB_DEFAULT = canonical_stream_db_path()


def resolve_stream_db_path(default: "Path | str | None" = None) -> Path:
    """The one stream-database path (runtime_layout / RC-534). `default` is for tests."""
    if default is not None:
        return Path(default).resolve()
    return canonical_stream_db_path()


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
CREATE TABLE IF NOT EXISTS stream_options_quotes_raw (
    ts_recv REAL NOT NULL,
    symbol TEXT NOT NULL,
    native_json TEXT NOT NULL,
    src TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_soqr_sym_ts ON stream_options_quotes_raw(symbol, ts_recv);
CREATE TABLE IF NOT EXISTS stream_bars_raw (
    ts_recv REAL NOT NULL,
    symbol TEXT NOT NULL,
    bar_start_ms INTEGER,
    open REAL, high REAL, low REAL, close REAL, volume INTEGER,
    src TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_sbr_sym_ts ON stream_bars_raw(symbol, bar_start_ms);
-- NEWS_HEADLINE items, verbatim (not in Schwab's Streamer Guide; answers code 0, 2026-09-25).
CREATE TABLE IF NOT EXISTS stream_news_raw (
    ts_recv REAL NOT NULL,
    symbol TEXT NOT NULL,
    native_json TEXT NOT NULL,
    src TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_snr_sym_ts ON stream_news_raw(symbol, ts_recv);
-- Every subscribe/unsubscribe the daemon sent and Schwab's answer. With it, a gap in the
-- data tables can be told apart: "we were not subscribed" versus "subscribed, nothing
-- changed". code 0 = accepted; anything else carries Schwab's reason.
CREATE TABLE IF NOT EXISTS stream_subscriptions (
    ts REAL NOT NULL,
    service TEXT NOT NULL,
    command TEXT NOT NULL,
    symbols_json TEXT NOT NULL,
    code INTEGER,
    reason TEXT
);
CREATE INDEX IF NOT EXISTS idx_ssub_ts ON stream_subscriptions(ts);
"""

#: Most equities the console asks the daemon to stream on LEVELONE_EQUITIES (ranked by the
#: console: the active ticker, then the market context, then the watchlist, then the board).
EQUITY_SYMBOLS_MAX_HELD = 150
#: Most option contracts on LEVELONE_OPTIONS (measured 2026-09-23: 510-1,080 contracts on the
#: one socket caused 4-9 socket deaths an hour; 200 held clean).
OPTION_CONTRACTS_MAX_HELD = 200

WAL_SIZE_LIMIT_BYTES = 256 * 1024 * 1024


def rank_option_contracts(requested, contract_inputs: "dict[str, dict]",
                          budget: int = OPTION_CONTRACTS_MAX_HELD,
                          ) -> "tuple[list[str], dict[str, str]]":
    """(admitted, {not_admitted_symbol: reason}) -- which contracts fit the budget, ranked by
    expirationDate, then |strikePrice - spot|, then symbol (Schwab's own fields; a contract
    missing any of them is not admitted and says which)."""
    from numeric_contract import float_finite_or_none

    not_admitted: "dict[str, str]" = {}
    rankable = []
    for sym in sorted({str(s).upper().strip() for s in requested or ()} - {""}):
        inp = contract_inputs.get(sym)
        if inp is None:
            not_admitted[sym] = "not admitted: contract not in the console's current Schwab chain"
            continue
        strike = float_finite_or_none(inp.get("strikePrice"))
        spot = float_finite_or_none(inp.get("spot"))
        missing = [k for k, v in (("expirationDate", inp.get("expirationDate")),
                                  ("strikePrice", strike), ("spot", spot)) if v is None]
        if missing:
            not_admitted[sym] = f"not admitted: no {', '.join(missing)}"
            continue
        rankable.append((str(inp["expirationDate"]), abs(strike - spot), sym))
    rankable.sort()
    admitted = [sym for _e, _d, sym in rankable[:max(budget, 0)]]
    for _e, _d, sym in rankable[max(budget, 0):]:
        not_admitted[sym] = f"not admitted: outside the live-stream budget ({budget})"
    return admitted, not_admitted


# ---------------------------------------------------------------------------- message shapes
# The one shape per topic; the daemon builds through these and the writer reads them.

def _now(ts_recv: "float | None") -> float:
    return ts_recv if ts_recv is not None else time.time()


def quote_msg(*, symbol: str, bid=None, ask=None, last=None, bid_size=None, ask_size=None,
              last_size=None, total_volume=None, quote_time_ms=None, trade_time_ms=None,
              src: str, ts_recv: float | None = None, native: dict | None = None) -> dict:
    """quote.* (LEVELONE_EQUITIES). `native` is Schwab's item verbatim -- readers need fields
    the flat columns do not carry (BID_TIME_MILLIS, LAST_MIC_ID, ...)."""
    return {"ts_recv": _now(ts_recv), "symbol": symbol,
            "bid": bid, "ask": ask, "last": last, "bid_size": bid_size,
            "ask_size": ask_size, "last_size": last_size, "total_volume": total_volume,
            "quote_time_ms": quote_time_ms, "trade_time_ms": trade_time_ms, "src": src,
            "native": native}


def book_msg(*, symbol: str, service: str, content: dict, src: str,
             ts_recv: float | None = None) -> dict:
    """book.* (NYSE_BOOK / NASDAQ_BOOK / OPTIONS_BOOK), Schwab's item verbatim."""
    return {"ts_recv": _now(ts_recv), "symbol": symbol, "service": service,
            "content": content, "src": src}


def options_quote_msg(*, symbol: str, content: dict, src: str,
                      ts_recv: float | None = None) -> dict:
    """optquote.* (LEVELONE_OPTIONS), Schwab's item verbatim."""
    return {"ts_recv": _now(ts_recv), "symbol": symbol, "content": content, "src": src}


def bar_msg(*, symbol: str, bar_start_ms=None, open=None, high=None, low=None, close=None,  # noqa: A002
            volume=None, src: str, ts_recv: float | None = None) -> dict:
    """bar1m.* (CHART_EQUITY)."""
    return {"ts_recv": _now(ts_recv), "symbol": symbol, "bar_start_ms": bar_start_ms,
            "open": open, "high": high, "low": low, "close": close, "volume": volume, "src": src}


def news_msg(*, symbol: str, content: dict, src: str, ts_recv: float | None = None) -> dict:
    """news.* (NEWS_HEADLINE), Schwab's item verbatim."""
    return {"ts_recv": _now(ts_recv), "symbol": symbol, "content": content, "src": src}


def subscription_msg(*, service: str, command: str, symbols: "list[str]", code: "int | None",
                     reason: str, ts: float | None = None) -> dict:
    """sub.* -- one request the daemon sent and Schwab's answer."""
    return {"ts": _now(ts), "service": service, "command": command,
            "symbols": list(symbols), "code": code, "reason": reason}


# ---------------------------------------------------------------------------- the bus

@dataclass
class Subscription:
    prefix: str
    policy: str
    queue: asyncio.Queue
    pending: dict[str, Any] = field(default_factory=dict)
    dropped: int = 0

    def deliver(self, topic: str, msg: Any) -> None:
        if self.policy == COALESCE:
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
        self._sub_names: dict[int, str] = {}           # id(subscription) -> consumer name
        self._retired_drops: dict[str, int] = {}       # drops of unsubscribed consumers, by name
        self.cache: dict[str, Any] = {}
        self.published = 0

    def subscribe(self, prefix: str, *, policy: str = COUNT_DROPS, maxsize: int = 2048,
                  name: str | None = None) -> Subscription:
        """`name` identifies the consumer in drop_counts (default: the prefix)."""
        sub = Subscription(prefix=prefix, policy=policy, queue=asyncio.Queue(maxsize=maxsize))
        self._sub_names[id(sub)] = name if name is not None else prefix
        self._subs.append(sub)
        return sub

    def unsubscribe(self, sub: Subscription) -> None:
        """Stop delivering to `sub`; its drop count is kept under its name."""
        if sub in self._subs:
            self._subs.remove(sub)
            name = self._sub_names.pop(id(sub), sub.prefix)
            if sub.dropped:
                self._retired_drops[name] = self._retired_drops.get(name, 0) + sub.dropped

    def publish(self, topic: str, msg: Any) -> None:
        self.cache[topic] = msg
        self.published += 1
        for sub in self._subs:
            if topic.startswith(sub.prefix):
                sub.deliver(topic, msg)

    def snapshot(self, prefix: str = "") -> dict[str, Any]:
        return {t: v for t, v in self.cache.items() if t.startswith(prefix)}

    def drop_counts(self) -> dict[str, int]:
        """Dropped messages per consumer name: live subscriptions plus disconnected ones."""
        out = dict(self._retired_drops)
        for s in self._subs:
            if s.dropped:
                name = self._sub_names.get(id(s), s.prefix)
                out[name] = out.get(name, 0) + s.dropped
        return {k: v for k, v in out.items() if v}


#: Seconds since a service's last message: DEGRADED past the first, STALE past the second.
HEALTH_DEGRADED_SEC = 5.0
HEALTH_STALE_SEC = 30.0


class HealthRegistry:
    """Per-service liveness: RUNNING / DEGRADED / STALE / DOWN, judged by message age."""

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
        return {f: {"state": self.state(f, t), "age_sec": round(t - ts, 3)}
                for f, ts in self._last.items()}


# ---------------------------------------------------------------------------- the writer

_INSERTS = {
    "quote": ("INSERT INTO stream_quotes_raw(ts_recv,symbol,bid,ask,last,bid_size,ask_size,"
              "last_size,total_volume,quote_time_ms,trade_time_ms,src,native_json) "
              "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
              lambda m: (m.get("ts_recv"), m.get("symbol"), m.get("bid"), m.get("ask"),
                         m.get("last"), m.get("bid_size"), m.get("ask_size"), m.get("last_size"),
                         m.get("total_volume"), m.get("quote_time_ms"), m.get("trade_time_ms"),
                         m["src"], _json(m.get("native")))),
    "book": ("INSERT INTO stream_book_raw(ts_recv,symbol,service,native_json,src) VALUES(?,?,?,?,?)",
             lambda m: (m.get("ts_recv"), m.get("symbol"), m.get("service"),
                        json.dumps(m["content"]), m["src"])),
    "optquote": ("INSERT INTO stream_options_quotes_raw(ts_recv,symbol,native_json,src) "
                 "VALUES(?,?,?,?)",
                 lambda m: (m.get("ts_recv"), m.get("symbol"), json.dumps(m["content"]), m["src"])),
    "bar1m": ("INSERT INTO stream_bars_raw(ts_recv,symbol,bar_start_ms,open,high,low,close,"
              "volume,src) VALUES(?,?,?,?,?,?,?,?,?)",
              lambda m: (m.get("ts_recv"), m.get("symbol"), m.get("bar_start_ms"), m.get("open"),
                         m.get("high"), m.get("low"), m.get("close"), m.get("volume"), m["src"])),
    "news": ("INSERT INTO stream_news_raw(ts_recv,symbol,native_json,src) VALUES(?,?,?,?)",
             lambda m: (m.get("ts_recv"), m.get("symbol"), json.dumps(m["content"]), m["src"])),
    "sub": ("INSERT INTO stream_subscriptions(ts,service,command,symbols_json,code,reason) "
            "VALUES(?,?,?,?,?,?)",
            lambda m: (m.get("ts"), m.get("service"), m.get("command"),
                       json.dumps(m.get("symbols") or []), m.get("code"), m.get("reason"))),
}


#: Topics stored as Schwab's item verbatim: a message without that item is not a row.
_VERBATIM = {"book", "optquote", "news"}


def _json(v) -> "str | None":
    return json.dumps(v) if v is not None else None


class CaptureWriter:
    """Writes every bus message to stream_capture.db from its own thread, in batches
    (commit every `batch_rows` rows or `batch_sec`). Never points at ed_console.db."""

    def __init__(self, db_path: "Path | str | None" = None, *,
                 batch_rows: int = 500, batch_sec: float = 0.25) -> None:
        p = resolve_stream_db_path() if db_path is None else Path(db_path).resolve()
        if p.name == "ed_console.db":
            raise ValueError("CaptureWriter must never write the operational DB (RC-6 law)")
        p.parent.mkdir(parents=True, exist_ok=True)
        self.db_path = p
        self.batch_rows = int(batch_rows)
        self.batch_sec = float(batch_sec)
        self.rows_written = 0
        self.insert_errors = 0
        conn = sqlite3.connect(str(p))
        try:
            conn.executescript("PRAGMA journal_mode=WAL; PRAGMA synchronous=NORMAL;")
            conn.execute(f"PRAGMA journal_size_limit={WAL_SIZE_LIMIT_BYTES}")
            conn.executescript(STREAM_SCHEMA_SQL)
            cols = {r[1] for r in conn.execute("PRAGMA table_info(stream_quotes_raw)")}
            if "native_json" not in cols:
                conn.execute("ALTER TABLE stream_quotes_raw ADD COLUMN native_json TEXT")
            conn.commit()
        finally:
            conn.close()

    def insert(self, topic: str, msg: dict, *, conn: "sqlite3.Connection | None" = None) -> None:
        """One bus message -> one row (topics without a table are skipped). Without `conn`
        (a test, a recovery tool) it opens, writes and commits a connection of its own."""
        kind = topic.split(".", 1)[0]
        spec = _INSERTS.get(kind)
        if spec is None:
            return
        if isinstance(msg, dict) and kind in _VERBATIM and msg.get("content") is None:
            return                         # nothing Schwab sent to keep
        if conn is None:
            with sqlite3.connect(str(self.db_path), timeout=30.0) as own:
                self.insert(topic, msg, conn=own)
            return
        try:
            conn.execute(spec[0], spec[1](msg))
            self.rows_written += 1
        except Exception:  # noqa: BLE001 -- counted in status; capture continues
            self.insert_errors += 1

    async def run(self, sub: Subscription, *, stop: asyncio.Event) -> None:
        """Hand every bus message to the writer thread until `stop`; everything delivered
        before the stop is written and committed before this returns."""
        q: "queue.SimpleQueue" = queue.SimpleQueue()
        thread = threading.Thread(target=self._thread, args=(q,), name="stream-capture-writer",
                                  daemon=True)
        thread.start()
        try:
            while not stop.is_set():
                try:
                    q.put(await asyncio.wait_for(sub.get(), timeout=0.25))
                except asyncio.TimeoutError:
                    continue
            while not sub.queue.empty():
                q.put(await sub.get())
        finally:
            q.put(None)
            await asyncio.to_thread(thread.join)

    def _thread(self, q: "queue.SimpleQueue") -> None:
        conn = sqlite3.connect(str(self.db_path), timeout=30.0)
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute(f"PRAGMA journal_size_limit={WAL_SIZE_LIMIT_BYTES}")
        pending, last_commit = 0, time.monotonic()
        try:
            while True:
                try:
                    item = q.get(timeout=max(self.batch_sec - (time.monotonic() - last_commit), 0.01))
                except queue.Empty:
                    item = False
                if item is None:
                    break
                if item:
                    self.insert(*item, conn=conn)
                    pending += 1
                if pending and (pending >= self.batch_rows
                                or time.monotonic() - last_commit >= self.batch_sec):
                    conn.commit()
                    pending, last_commit = 0, time.monotonic()
            conn.commit()
        finally:
            conn.close()
