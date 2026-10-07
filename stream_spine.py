"""The pieces the capture daemon and its readers share: the stream database path and schema,
the message shapes, the in-process message bus, feed health, and the database writer.

  - Every Schwab message is published once on the MessageBus and becomes its topic's current
    record (the newest by Schwab's time); the writer reads every message (LOG), the console
    socket and the browser socket read each changed topic's current record (LATEST).
  - Raw stream data goes ONLY to stream_capture.db -- ed_console.db is never written here.
  - The writer runs on its own thread with its own SQLite connection, so a slow disk can
    never stall the Schwab socket (measured 2026-09-23: in-loop commits dropped 9,784 msgs).
  - A message the writer cannot store as a row is kept as sent, with its error, in
    stream_write_failures; while the database refuses writes the writer holds the messages, in
    memory up to a cap and then in a spill file beside the database, and writes them back in
    order when it can; its state (WriterStatus) rides the daemon's heartbeat.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import queue
import re
import sqlite3
import sys
import threading
import time
from collections import Counter
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from db_authority import canonical_stream_db_path
from time_et import ct_label

log = logging.getLogger(__name__)


def resolve_stream_db_path(default: "Path | str | None" = None) -> Path:
    """The one stream-database path (runtime_layout / RC-534). `default` is for tests."""
    if default is not None:
        return Path(default).resolve()
    return canonical_stream_db_path()


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
-- NEWS_HEADLINE items, verbatim (not in Schwab's Streamer API, docs/schwab/schwab_streamer_api.pdf §1.1 "Services available"; answers code 0).
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
CREATE TABLE IF NOT EXISTS stream_feed_status (
    ts REAL NOT NULL,
    service TEXT NOT NULL,
    socket_open INTEGER NOT NULL,
    schwab_last_frame_ts REAL,
    held INTEGER NOT NULL,
    last_data_ts REAL
);
CREATE INDEX IF NOT EXISTS idx_sfs_ts ON stream_feed_status(ts);
-- Every message a write refused, kept as sent: when it failed, its topic (a bus topic, or
-- chain_history.<TICKER> for a chain whose history write failed), the message as JSON, and the
-- error (type and text). Nothing here is a correction; each row is what could not be stored.
CREATE TABLE IF NOT EXISTS stream_write_failures (
    ts REAL NOT NULL,
    topic TEXT NOT NULL,
    msg_json TEXT NOT NULL,
    error TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_swf_ts ON stream_write_failures(ts);
-- How far each spill file's write-back got, written in the same transaction as each part it
-- wrote: how many of its records are in the database.
CREATE TABLE IF NOT EXISTS stream_spill_progress (
    spill TEXT PRIMARY KEY,
    written_back INTEGER NOT NULL
);
"""

WAL_SIZE_LIMIT_BYTES = 256 * 1024 * 1024


# ---------------------------------------------------------------------------- message shapes
# The one shape per topic; the daemon builds through these and the writer reads them.

def _now(ts_recv: "float | None") -> float:
    return ts_recv if ts_recv is not None else time.time()


#: Every Schwab message carries `schwab_ts`: the timestamp (ms) Schwab put on the frame that
#: delivered it. Which value is current is decided by it (docs/DATA_FLOW.md §2 D1).

def quote_msg(*, symbol: str, bid=None, ask=None, last=None, bid_size=None, ask_size=None,
              last_size=None, total_volume=None, quote_time_ms=None, trade_time_ms=None,
              src: str, ts_recv: float | None = None, native: dict | None = None,
              schwab_ts: int | None = None) -> dict:
    """quote.* (LEVELONE_EQUITIES). `native` is Schwab's item verbatim -- readers need fields
    the flat columns do not carry (BID_TIME_MILLIS, LAST_MIC_ID, ...)."""
    return {"ts_recv": _now(ts_recv), "schwab_ts": schwab_ts, "symbol": symbol,
            "bid": bid, "ask": ask, "last": last, "bid_size": bid_size,
            "ask_size": ask_size, "last_size": last_size, "total_volume": total_volume,
            "quote_time_ms": quote_time_ms, "trade_time_ms": trade_time_ms, "src": src,
            "native": native}


def book_msg(*, symbol: str, service: str, content: dict, src: str,
             ts_recv: float | None = None, schwab_ts: int | None = None) -> dict:
    """book.* (NYSE_BOOK / NASDAQ_BOOK / OPTIONS_BOOK), Schwab's item verbatim."""
    return {"ts_recv": _now(ts_recv), "schwab_ts": schwab_ts, "symbol": symbol,
            "service": service, "content": content, "src": src}


def options_quote_msg(*, symbol: str, content: dict, src: str,
                      ts_recv: float | None = None, schwab_ts: int | None = None) -> dict:
    """optquote.* (LEVELONE_OPTIONS), Schwab's item verbatim."""
    return {"ts_recv": _now(ts_recv), "schwab_ts": schwab_ts, "symbol": symbol,
            "content": content, "src": src}


def bar_msg(*, symbol: str, bar_start_ms=None, open=None, high=None, low=None, close=None,  # noqa: A002
            volume=None, src: str, ts_recv: float | None = None, native: dict | None = None,
            schwab_ts: int | None = None) -> dict:
    """bar1m.* (CHART_EQUITY). `native` is Schwab's item verbatim (SEQUENCE, CHART_DAY, ...)."""
    return {"ts_recv": _now(ts_recv), "schwab_ts": schwab_ts, "symbol": symbol,
            "bar_start_ms": bar_start_ms, "open": open, "high": high, "low": low,
            "close": close, "volume": volume, "src": src, "native": native}


def news_msg(*, symbol: str, content: dict, src: str, ts_recv: float | None = None,
             schwab_ts: int | None = None) -> dict:
    """news.* (NEWS_HEADLINE), Schwab's item verbatim."""
    return {"ts_recv": _now(ts_recv), "schwab_ts": schwab_ts, "symbol": symbol,
            "content": content, "src": src}


def subscription_msg(*, service: str, command: str, symbols: "list[str]", code: "int | None",
                     reason: str, ts: float | None = None) -> dict:
    """sub.* -- one request the daemon sent and Schwab's answer."""
    return {"ts": _now(ts), "service": service, "command": command,
            "symbols": list(symbols), "code": code, "reason": reason}


# ---------------------------------------------------------------------------- the bus

#: How a reader takes the bus. LOG: every message, in order -- the database writer, the record of
#: everything Schwab sent (docs/DATA_FLOW.md §2 D4). LATEST: for each topic that changed since
#: its last read, that topic's current record -- every live reader: a newer value replaces an
#: older one at once, nothing old waits, and what a reader holds is bounded by the number of
#: topics, never by how fast Schwab sends (D3).
LOG, LATEST = "log", "latest"
#: the topics whose messages carry only the fields that changed (Schwab's LEVELONE services),
#: by the key of the Schwab item in the message: their current record merges field by field
_FIELD_DELTA = {"quote": "native", "optquote": "content"}


def current_key(topic: str, msg: Any) -> str:
    """A topic's key in the current state, by its source (`src`: a message from elsewhere is
    never merged into Schwab's record) and, for a book, its service (NYSE_BOOK and NASDAQ_BOOK
    are two books of one symbol)."""
    if not isinstance(msg, dict):
        return topic
    if topic.startswith("book."):
        return f"{topic}@{msg.get('service')}#{msg.get('src')}"
    return f"{topic}#{msg.get('src')}"


def _older(t: "float | None", than: "float | None") -> bool:
    """`t` is older than `than` by Schwab's time; a message without one cannot be compared."""
    return t is not None and than is not None and t < than


@dataclass
class Subscription:
    prefix: str
    policy: str
    current: dict                                                     # the bus's current state
    queue: asyncio.Queue = field(default_factory=asyncio.Queue)      # LOG: every message
    changed: dict = field(default_factory=dict)                      # LATEST: keys, in order
    wake: asyncio.Event = field(default_factory=asyncio.Event)

    def deliver(self, key: str, topic: str, msg: Any) -> None:
        if self.policy == LOG:
            self.queue.put_nowait((topic, msg))
        else:
            self.changed[key] = None
            self.wake.set()

    async def get(self) -> tuple[str, Any]:
        """LOG: the next message. LATEST: (topic, current record) of the next changed topic; a
        chain's record is its parts, in order."""
        if self.policy == LOG:
            return await self.queue.get()
        while True:
            while self.changed:
                key = next(iter(self.changed))
                del self.changed[key]
                entry = self.current.get(key)
                if entry is not None:
                    return entry
            self.wake.clear()
            await self.wake.wait()


class MessageBus:
    """Every Schwab message is published once. It becomes its topic's current record -- the
    newest by Schwab's time (`schwab_ts`, the frame's timestamp; a chain by its fetch time):
    a LEVELONE message merged field by field, a book, bar or news item whole, a chain whole once
    all its parts are in -- and each reader takes it by its policy (LOG or LATEST)."""

    def __init__(self) -> None:
        self._subs: list[Subscription] = []
        #: key (current_key) -> (topic, record)
        self.current: dict[str, tuple[str, Any]] = {}
        #: chain topic -> (fetch time, {part: message}, parts): the newest fetch, filling
        self._chains: dict[str, tuple[float, dict, int]] = {}

    def subscribe(self, prefix: str, *, policy: str = LATEST) -> Subscription:
        """A LATEST reader starts with every current record under `prefix` to read."""
        sub = Subscription(prefix=prefix, policy=policy, current=self.current)
        if policy == LATEST:
            sub.changed.update((k, None) for k, (t, _r) in self.current.items() if t.startswith(prefix))
            if sub.changed:
                sub.wake.set()
        self._subs.append(sub)
        return sub

    def unsubscribe(self, sub: Subscription) -> None:
        if sub in self._subs:
            self._subs.remove(sub)

    def publish(self, topic: str, msg: Any) -> None:
        key = current_key(topic, msg)
        chain = topic.startswith("chain.")
        changed = self._chain(key, topic, msg) if chain else self._newest(key, topic, msg)
        # a chain's record is its own history (the chain sweep writes it), and a price history is
        # Schwab's own record (asked again each day): neither is the log's
        logged = not chain and not topic.startswith("pricehistory.")
        for sub in self._subs:
            if not topic.startswith(sub.prefix):
                continue
            if (sub.policy == LOG and logged) or (sub.policy == LATEST and changed):
                sub.deliver(key, topic, msg)

    def forget(self, key: str) -> None:
        """The daemon stopped holding what `key` (current_key) names: its record is no longer
        current and is never handed out again (D5)."""
        self.current.pop(key, None)

    def _newest(self, key: str, topic: str, msg: Any) -> bool:
        """Make `msg` part of its topic's current record where it is the newest by Schwab's
        time. Returns whether the record changed."""
        held = self.current.get(key)
        t = msg.get("schwab_ts") if isinstance(msg, dict) else None
        body_key = _FIELD_DELTA.get(topic.split(".", 1)[0])
        body = msg.get(body_key) if body_key is not None and isinstance(msg, dict) else None
        if not isinstance(body, dict):                       # a whole record: replaced whole
            if held is not None and isinstance(held[1], dict) and _older(t, held[1].get("schwab_ts")):
                return False
            self.current[key] = (topic, msg)
            return True
        stamp = (t, msg.get("ts_recv"))
        if held is None:
            self.current[key] = (topic, {**msg, body_key: dict(body), "field_ts": dict.fromkeys(body, stamp)})
            return True
        rec = held[1]
        merged, stamps = dict(rec[body_key]), dict(rec["field_ts"])
        took = [f for f in body if f not in stamps or not _older(t, stamps[f][0])]
        if not took:
            return False
        for f in took:
            merged[f], stamps[f] = body[f], stamp
        top = rec if _older(t, rec.get("schwab_ts")) else msg   # the record's own time: its newest
        self.current[key] = (topic, {**top, body_key: merged, "field_ts": stamps})
        return True

    def _chain(self, key: str, topic: str, msg: dict) -> bool:
        """A chain part (or a failed fetch, which has no parts): the newest fetch of the ticker
        is kept; once all its parts are in it replaces the current chain whole."""
        ts, part = msg.get("ts_recv"), msg.get("part")
        held = self._chains.get(key)
        if held is not None and ts < held[0]:
            return False                                      # an older fetch: never current
        if held is None or ts > held[0]:
            held = (ts, {}, msg.get("parts") if part is not None else 1)
            self._chains[key] = held
        held[1][part if part is not None else 0] = msg
        if len(held[1]) < held[2]:
            return False
        self.current[key] = (topic, [held[1][i] for i in sorted(held[1])])
        return True



class HealthRegistry:
    """When each Schwab service last carried data: an observation, not a liveness verdict
    (live is live_market_plane.feed_live_for -- Schwab sends only changes, so a quiet service
    on an open socket is live)."""

    def __init__(self) -> None:
        self._last: dict[str, float] = {}

    def beat(self, feed: str, ts: float | None = None) -> None:
        self._last[feed] = ts if ts is not None else time.time()

    def last(self, feed: str) -> float | None:
        """When this feed last carried data (None: never, this connection)."""
        return self._last.get(feed)

    def report(self, now: float) -> dict[str, dict]:
        return {f: {"age_sec": now - ts} for f, ts in self._last.items()}


# ---------------------------------------------------------------------------- the writer

#: columns added after a table was first made: (table, column, type)
_ADDED_COLUMNS = (("stream_quotes_raw", "native_json", "TEXT"),
                  ("stream_quotes_raw", "schwab_ts", "INTEGER"),
                  ("stream_book_raw", "schwab_ts", "INTEGER"),
                  ("stream_options_quotes_raw", "schwab_ts", "INTEGER"),
                  ("stream_bars_raw", "schwab_ts", "INTEGER"),
                  ("stream_bars_raw", "native_json", "TEXT"),
                  ("stream_news_raw", "schwab_ts", "INTEGER"))

_INSERTS = {
    "feedstatus": ("INSERT INTO stream_feed_status(ts,service,socket_open,schwab_last_frame_ts,"
                   "held,last_data_ts) VALUES(?,?,?,?,?,?)",
                   lambda m: (m["ts"], m["service"], int(m["socket_open"]),
                              m.get("schwab_last_frame_ts"), m["held"], m.get("last_data_ts"))),
    "quote": ("INSERT INTO stream_quotes_raw(ts_recv,symbol,bid,ask,last,bid_size,ask_size,"
              "last_size,total_volume,quote_time_ms,trade_time_ms,src,native_json,schwab_ts) "
              "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
              lambda m: (m.get("ts_recv"), m.get("symbol"), m.get("bid"), m.get("ask"),
                         m.get("last"), m.get("bid_size"), m.get("ask_size"), m.get("last_size"),
                         m.get("total_volume"), m.get("quote_time_ms"), m.get("trade_time_ms"),
                         m["src"], _json(m.get("native")), m.get("schwab_ts"))),
    "book": ("INSERT INTO stream_book_raw(ts_recv,symbol,service,native_json,src,schwab_ts) "
             "VALUES(?,?,?,?,?,?)",
             lambda m: (m.get("ts_recv"), m.get("symbol"), m.get("service"),
                        json.dumps(m["content"]), m["src"], m.get("schwab_ts"))),
    "optquote": ("INSERT INTO stream_options_quotes_raw(ts_recv,symbol,native_json,src,schwab_ts) "
                 "VALUES(?,?,?,?,?)",
                 lambda m: (m.get("ts_recv"), m.get("symbol"), json.dumps(m["content"]), m["src"],
                            m.get("schwab_ts"))),
    "bar1m": ("INSERT INTO stream_bars_raw(ts_recv,symbol,bar_start_ms,open,high,low,close,"
              "volume,src,native_json,schwab_ts) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
              lambda m: (m.get("ts_recv"), m.get("symbol"), m.get("bar_start_ms"), m.get("open"),
                         m.get("high"), m.get("low"), m.get("close"), m.get("volume"), m["src"],
                         _json(m.get("native")), m.get("schwab_ts"))),
    "news": ("INSERT INTO stream_news_raw(ts_recv,symbol,native_json,src,schwab_ts) VALUES(?,?,?,?,?)",
             lambda m: (m.get("ts_recv"), m.get("symbol"), json.dumps(m["content"]), m["src"],
                        m.get("schwab_ts"))),
    "sub": ("INSERT INTO stream_subscriptions(ts,service,command,symbols_json,code,reason) "
            "VALUES(?,?,?,?,?,?)",
            lambda m: (m.get("ts"), m.get("service"), m.get("command"),
                       json.dumps(m.get("symbols") or []), m.get("code"), m.get("reason"))),
}


#: Topics stored as Schwab's item verbatim: a message without that item is not a row.
_VERBATIM = {"book", "optquote", "news"}


def _json(v) -> "str | None":
    return json.dumps(v) if v is not None else None


#: what one message's row can raise while it is built and written: the row refused by the
#: database (a constraint, a value it cannot bind or store) or a message without the shape its
#: table needs. Each belongs to that message alone: it is kept as sent and the writer goes on.
ROW_FAILURES = (sqlite3.IntegrityError, sqlite3.DataError, sqlite3.InterfaceError,
                sqlite3.ProgrammingError, sqlite3.NotSupportedError, KeyError, TypeError,
                ValueError, AttributeError, OverflowError)
#: an error from the database while writing (opening, a row, a commit); a row's error is the
#: database refusing every write when its SQLite code is one of REFUSAL_CODES, else that row's own
DATABASE_REFUSALS = (sqlite3.DatabaseError,)
#: SQLite's primary result codes for a database that takes no write now: SQLITE_PERM, BUSY,
#: LOCKED, NOMEM, READONLY, IOERR, CORRUPT, FULL, CANTOPEN, PROTOCOL, NOTADB
#: (https://www.sqlite.org/rescode.html). The writer holds the messages and tries again.
REFUSAL_CODES = frozenset({3, 5, 6, 7, 8, 10, 11, 13, 14, 15, 26})


def _refuses_every_write(error: sqlite3.DatabaseError) -> bool:
    return error.sqlite_errorcode is None or error.sqlite_errorcode & 0xFF in REFUSAL_CODES

#: the writer's states, on the heartbeat
WRITER_NOT_STARTED, WRITER_RECORDING, WRITER_BLOCKED, WRITER_DEAD, WRITER_STOPPED = (
    "not_started", "recording", "blocked", "dead", "stopped")
_STATE_WORD = {WRITER_NOT_STARTED: "NOT STARTED", WRITER_RECORDING: "RECORDING",
               WRITER_BLOCKED: "BLOCKED", WRITER_DEAD: "DEAD", WRITER_STOPPED: "STOPPED"}
#: each table's name and columns, from its insert
_TABLES = {kind: (m.group(1), tuple(c.strip() for c in m.group(2).split(",")))
           for kind, (sql, _row) in _INSERTS.items()
           for m in [re.match(r"INSERT INTO (\w+)\(([^)]*)\)", sql)]}
_COLUMNS = dict(_TABLES.values())
#: each written table's column a spill's rows are counted by (its topic's symbol, or service)
_KEY_COLUMN = {**{table: "symbol" if "symbol" in cols else "service" for table, cols in _COLUMNS.items()},
               "stream_write_failures": "topic"}
#: what the writer holds in memory while the database refuses writes, before newer messages go to
#: the spill file (operator, 2026-10-05: about 2 GB of memory), each held message counted once at
#: its memory size (_held_size)
HOLD_CAP_BYTES = 2 * 1024 ** 3
#: spill records written back in one transaction
SPILL_CHUNK = 5000


@dataclass(frozen=True)
class RowWritten:
    """A message's row written to its table, with the values bound."""
    table: str
    values: tuple


@dataclass(frozen=True)
class KeptFailure:
    """A message kept as sent in stream_write_failures: its topic, the message, the error (type
    and text) and when the write failed."""
    topic: str
    msg: Any
    error: str
    ts: float


@dataclass(frozen=True)
class WriterStatus:
    """The writer as the heartbeat carries it, counted at commit. `failures`: messages kept in
    stream_write_failures; `held`: messages in memory not yet in the database (queued, in the
    open batch or waiting); `waiting`: those the writer took from the queue to write again while
    the database refuses writes (each try takes every queued one; those arriving during the pause
    between tries stay queued until the next), `held_bytes` the memory they take, each counted
    once when held (_held_size; the cap's measure); `spill`: the spill file the messages past the
    cap went to (its path, bytes, messages and how many are written back), None when there is
    none; `spills_kept`: spill files kept because their write-back did not verify or a record
    did not decode; `left_on_disk`: spill files left unwritten (by a stop, the writer's death, or
    found at start), with how many records are written back; `lost`: messages neither the
    database nor the spill file took, received from `lost_first_ts` to `lost_last_ts`;
    `unrecorded`: messages a dead writer could not write; `error`: the database's refusal
    (blocked) or what ended the thread (dead), from `error_ct`. `line` and `cls`: the header's
    Record, as the page prints it."""
    state: str
    rows_written: int
    failures: int
    last_failure: "str | None"
    last_failure_ct: "str | None"
    queue_depth: int
    waiting: int
    held: int
    held_bytes: int
    spill: "dict | None"
    spills_kept: list
    left_on_disk: list
    lost: int
    lost_first_ts: "float | None"
    lost_last_ts: "float | None"
    unrecorded: int
    error: "str | None"
    error_ct: "str | None"
    line: str
    cls: str


def _record_line(s: dict) -> "tuple[str, str]":
    """The header's Record for a writer status: the line, and its class ("neg" for anything
    but recording with nothing kept, spilled, lost or left)."""
    spill = s["spill"]
    if spill is None:
        word = _STATE_WORD[s["state"]]
    elif s["state"] == WRITER_BLOCKED:
        word = "BLOCKED, SPILLING TO DISK"
    else:
        word = "WRITING BACK THE SPILL"
    parts = [word]
    if s["error"] is not None:
        parts.append(f"{'since' if s['state'] == WRITER_BLOCKED else 'at'} {s['error_ct']}: {s['error']}")
    parts += [f"{s['rows_written']} rows", f"{s['failures']} failed, kept as sent"]
    if s["last_failure"] is not None:
        parts.append(f"last {s['last_failure_ct']}: {s['last_failure']}")
    parts.append(f"held in memory: {s['held']} messages, {s['held_bytes'] / 1e6:.1f} MB "
                 f"({s['waiting']} waiting for the database)")
    if spill is not None:
        parts.append(f"spilled to disk: {spill['messages']} messages, {spill['bytes']:,} bytes in "
                     f"{Path(spill['path']).name}, {spill['written_back']} written back")
    parts += [f"spill kept: {k['reason']} ({Path(k['path']).name}, {k['written_back']} of "
              f"{k['messages']} written back)" for k in s["spills_kept"]]
    parts += [f"left on disk, not written back: {Path(k['path']).name} ({k['messages']} messages, "
              f"{k['bytes']:,} bytes, {k['written_back']} written back)" for k in s["left_on_disk"]]
    if s["lost"]:
        parts.append(f"LOST {s['lost']} messages, received {ct_label(s['lost_first_ts'])} to "
                     f"{ct_label(s['lost_last_ts'])}")
    parts.append(f"{s['unrecorded']} not recorded")
    ok = (s["state"] == WRITER_RECORDING and s["failures"] == 0 and s["unrecorded"] == 0
          and spill is None and not s["spills_kept"] and not s["left_on_disk"]
          and s["lost"] == 0)
    return " · ".join(parts), "" if ok else "neg"


def _object_bytes(obj, seen: set) -> int:
    """Memory of `obj` and everything it holds that is its own: each object once (`seen`), not
    None, True, False, CPython's cached small ints and one-character strings."""
    stack, total = [obj], 0
    while stack:
        o = stack.pop()
        if o is None or o is True or o is False or id(o) in seen:
            continue
        if (type(o) is int and -5 <= o <= 256) or (type(o) is str and len(o) <= 1):
            continue
        seen.add(id(o))
        total += sys.getsizeof(o)
        if type(o) is dict:
            stack.extend(o.keys())
            stack.extend(o.values())
        elif type(o) in (list, tuple):
            stack.extend(o)
    return total


def _held_size(item) -> int:
    """The memory a held message takes: the (topic, message) pair, its topic, the message dict
    and every value it carries (Schwab's item decoded from the wire, its fields). The message's
    keys and its `src` are the writer's code constants, shared by every message, and not counted.
    Measured against tracemalloc on production's stream mix decoded from JSON:
    tests/test_data_path_writer_failures_v1.py::test_the_hold_cap_holds_memory_to_its_size."""
    seen: set = set()
    if isinstance(item, KeptFailure):
        return sys.getsizeof(item) + sum(_object_bytes(v, seen) for v in (item.topic, item.msg, item.error))
    topic, msg = item
    total = sys.getsizeof(item) + _object_bytes(topic, seen)
    if not isinstance(msg, dict):
        return total + _object_bytes(msg, seen)
    total += sys.getsizeof(msg)
    for key, value in msg.items():
        if key != "src":
            total += _object_bytes(value, seen)
    return total


def _received(item) -> "float | None":
    """When the daemon received a message: its `ts_recv` (`ts` for a status or a subscription
    answer; a kept failure's time)."""
    if isinstance(item, KeptFailure):
        return item.ts
    msg = item[1]
    if not isinstance(msg, dict):
        return None
    return msg["ts_recv"] if msg.get("ts_recv") is not None else msg.get("ts")


def _spill_record(item) -> bytes:
    """A held message as one spill record's JSON: the topic and the message as sent (a kept
    failure with its error and time)."""
    if isinstance(item, KeptFailure):
        rec = {"kept": {"topic": item.topic, "msg": item.msg, "error": item.error, "ts": item.ts}}
    else:
        rec = {"topic": item[0], "msg": item[1]}
    return json.dumps(rec, default=repr, separators=(",", ":")).encode("utf-8")


def _from_spill(raw: bytes):
    rec = json.loads(raw)
    if "kept" in rec:
        return KeptFailure(**rec["kept"])
    return rec["topic"], rec["msg"]


class _Spill:
    """One append-only spill file: each record a 4-byte big-endian length and the record's JSON.
    Appended in arrival order; written back from the start, `read_at` advancing at each commit."""

    def __init__(self, path: Path):
        self.path = path
        self.out = open(path, "ab", buffering=0)
        self.size = 0                  # bytes of whole records written
        self.messages = 0
        self.read_at = 0               # bytes written back and committed
        self.written_back = 0
        self.before: "dict | None" = None     # each table's newest rowid when write-back began
        self.expected: Counter = Counter()    # (table, key) -> rows written back
        self.first: "RowWritten | None" = None
        self.last: "RowWritten | None" = None
        self._in = None

    def append(self, record: bytes) -> "OSError | None":
        """Append one record; the disk's refusal (OSError) is returned, the file cut back to its
        whole records."""
        data = len(record).to_bytes(4, "big") + record
        try:
            if self.out.write(data) != len(data):
                raise OSError(f"short write to {self.path}")
        except OSError as e:
            self.out.truncate(self.size)   # no partial record stays behind the whole ones
            return e
        self.size += len(data)
        self.messages += 1
        return None

    def read(self, n: int) -> "tuple[list, str | None]":
        """Up to `n` records from `read_at`: (message, end offset) each, and why the read stopped
        early at a record that does not decode (its byte offset and error), else None."""
        if self._in is None:
            self._in = open(self.path, "rb")
        self._in.seek(self.read_at)
        out, at = [], self.read_at
        while len(out) < n and at < self.size:
            length = int.from_bytes(self._in.read(4), "big")
            try:
                item = _from_spill(self._in.read(length))
            except (ValueError, KeyError, TypeError) as e:
                return out, f"the record at byte {at} does not decode: {type(e).__name__}: {e}"
            at += 4 + length
            out.append((item, at))
        return out, None

    def committed(self, batch: list, end: int) -> None:
        """A written-back part is in the database: what it wrote, and where the next part starts."""
        for _item, out in batch:
            if isinstance(out, RowWritten):
                self.expected[(out.table, out.values[_COLUMNS[out.table].index(_KEY_COLUMN[out.table])])] += 1
                self.first = self.first or out
                self.last = out
            elif isinstance(out, KeptFailure):
                self.expected[("stream_write_failures", out.topic)] += 1
        self.written_back += len(batch)
        self.read_at = end

    def left(self) -> dict:
        """The spill file as listed when it is left on disk unwritten."""
        return {"path": str(self.path), "messages": self.messages, "bytes": self.size,
                "written_back": self.written_back}

    def status(self) -> dict:
        """The spill file as the heartbeat carries it."""
        return {"path": str(self.path), "bytes": self.size, "messages": self.messages,
                "written_back": self.written_back}

    def close(self) -> None:
        self.out.close()
        if self._in is not None:
            self._in.close()


def _found_spill(path: Path, progress: dict) -> dict:
    """A spill file found on disk, as listed: its whole records, bytes, and how many records an
    earlier writer wrote back (its stream_spill_progress row; none written back without one)."""
    size, at, n = path.stat().st_size, 0, 0
    with open(path, "rb") as f:
        while at + 4 <= size:
            f.seek(at)
            length = int.from_bytes(f.read(4), "big")
            if at + 4 + length > size:
                break
            at, n = at + 4 + length, n + 1
    # no row: no part of it was ever committed (each part's row is in its own transaction)
    written_back = progress[path.name] if path.name in progress else 0
    return {"path": str(path), "messages": n, "bytes": size, "written_back": written_back}


def _verify(conn: sqlite3.Connection, spill: _Spill) -> "str | None":
    """Why the spill's write-back does not match the database (None when it does): the rows of
    every table since the write-back began, per topic, against what the write-back wrote; and the
    spill's first and last row, as written; and every record of the file written back."""
    if spill.written_back != spill.messages:
        return f"{spill.written_back} of the file's {spill.messages} records written back"
    for table, before in spill.before.items():
        key = _KEY_COLUMN[table]
        got = Counter({(table, k): n for k, n in conn.execute(
            f"SELECT {key}, COUNT(*) FROM {table} WHERE rowid > ? GROUP BY {key}", (before,))})
        want = Counter({k: n for k, n in spill.expected.items() if k[0] == table})
        if got != want:
            differ = sorted(set(got) | set(want), key=str)
            k = next(k for k in differ if got[k] != want[k])
            return (f"{table}: {sum(1 for k in differ if got[k] != want[k])} topics differ, e.g. "
                    f"{k[1]}: {want[k]} written back, {got[k]} in the database")
    for which, agg, row in (("first", "MIN", spill.first), ("last", "MAX", spill.last)):
        if row is None:
            continue
        found = conn.execute(
            f"SELECT {','.join(_COLUMNS[row.table])} FROM {row.table} WHERE rowid = "
            f"(SELECT {agg}(rowid) FROM {row.table} WHERE rowid > ?)", (spill.before[row.table],)).fetchone()
        if found is None or tuple(found) != tuple(row.values):
            return f"the spill's {which} row is not in {row.table} as written"
    return None


class CaptureWriter:
    """Writes every bus message to stream_capture.db from its own thread, in batches
    (commit every `batch_rows` rows or `batch_sec`). Never points at ed_console.db. A message
    whose row is refused is kept as sent in stream_write_failures, in the same batch. While the
    database refuses every write (DATABASE_REFUSALS, each wait `timeout_sec`), the open batch
    is rolled back and its messages, and every one after, are held in order and written again,
    on a new connection, every `retry_sec` plus up to `batch_sec` (state blocked, with the
    refusal; each try also waits up to `timeout_sec` on a locked database). Held messages stay
    in memory up to `hold_cap_bytes`; every newer one goes to a spill file beside the database,
    in order. When the database takes writes again, memory is written first, then the spill
    file, then what arrived meanwhile (the spill takes it, behind the rest); the spill's rows are
    verified (rows per topic, its first and last row) and the file deleted only then. A message
    the spill file cannot take (a full disk) is lost: counted, with when it was received. Only
    an error outside these ends the thread (dead): what it held in memory and what reaches it
    after are counted unrecorded."""

    def __init__(self, db_path: "Path | str | None" = None, *,
                 batch_rows: int = 500, batch_sec: float = 0.25,
                 timeout_sec: float = 30.0, retry_sec: float = 1.0,
                 hold_cap_bytes: int = HOLD_CAP_BYTES) -> None:
        p = resolve_stream_db_path() if db_path is None else Path(db_path).resolve()
        if p.name == "ed_console.db":
            raise ValueError("CaptureWriter must never write the operational DB (RC-6 law)")
        p.parent.mkdir(parents=True, exist_ok=True)
        self.db_path = p
        self.batch_rows = int(batch_rows)
        self.batch_sec = float(batch_sec)
        self.timeout_sec = float(timeout_sec)
        self.retry_sec = float(retry_sec)
        self.hold_cap_bytes = int(hold_cap_bytes)
        self._lock = threading.Lock()
        self._q: "queue.SimpleQueue" = queue.SimpleQueue()
        self._batch: list = []         # (message, outcome) in the open transaction
        self._batch_spilled = False    # the open batch is spill records (they stay in the file)
        self._waiting: list = []       # messages held while the database refuses writes
        self._waiting_bytes = 0
        self._spill: "_Spill | None" = None
        self.spills_kept: list = []    # {"path", "reason"}: write-backs that did not verify
        self.lost = 0
        self.lost_first_ts: "float | None" = None
        self.lost_last_ts: "float | None" = None
        self._round: list = []         # the messages the writer is writing now, in order
        self._stored = 0               # how many of them are in the open batch
        self._logged: dict = {}        # log line kind -> [minute last logged, count since]
        self.state = WRITER_NOT_STARTED
        self.rows_written = 0
        self.failures = 0
        self.last_failure: "str | None" = None
        self.last_failure_ts: "float | None" = None
        self.unrecorded = 0
        self.error: "str | None" = None
        self.error_ts: "float | None" = None
        conn = sqlite3.connect(str(p))
        try:
            conn.executescript("PRAGMA journal_mode=WAL; PRAGMA synchronous=NORMAL;")
            conn.execute(f"PRAGMA journal_size_limit={WAL_SIZE_LIMIT_BYTES}")
            conn.executescript(STREAM_SCHEMA_SQL)
            for table, column, kind in _ADDED_COLUMNS:          # a database made before them
                if column not in {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}:
                    conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {kind}")
            conn.commit()
            progress = dict(conn.execute("SELECT spill, written_back FROM stream_spill_progress"))
        finally:
            conn.close()
        # spill files an earlier writer left beside the database: shown, not written back
        self.left_on_disk = [_found_spill(f, progress) for f in sorted(p.parent.glob(f"{p.stem}.*.spill"))]

    def insert(self, topic: str, msg: dict, *, conn: "sqlite3.Connection | None" = None):
        """One bus message -> one row: its RowWritten, the KeptFailure when its row is refused,
        or None (a topic without a table, or nothing Schwab sent to keep). A DATABASE_REFUSALS error
        is raised. Without `conn` (a test, a recovery tool) it opens, writes, commits and counts
        a connection of its own."""
        kind = topic.split(".", 1)[0]
        spec = _INSERTS.get(kind)
        if spec is None:
            return None
        if isinstance(msg, dict) and kind in _VERBATIM and msg.get("content") is None:
            return None
        if conn is None:
            with sqlite3.connect(str(self.db_path), timeout=self.timeout_sec) as own:
                out = self.insert(topic, msg, conn=own)
            self._committed([((topic, msg), out)])
            return out
        try:
            values = spec[1](msg)
            conn.execute(spec[0], values)
        except ROW_FAILURES as e:
            return self._kept_row(conn, topic, msg, e)
        except DATABASE_REFUSALS as e:
            if _refuses_every_write(e):
                raise
            return self._kept_row(conn, topic, msg, e)
        return RowWritten(_TABLES[kind][0], values)

    def _kept_row(self, conn: sqlite3.Connection, topic: str, msg: Any, error: BaseException) -> "KeptFailure":
        reason = f"{type(error).__name__}: {error}"
        self._log_once_a_minute(("row", reason), "stream writer: %s not stored as a row, kept as sent: %s",
                                topic, reason)
        return self._keep(conn, KeptFailure(topic, msg, reason, time.time()))

    def _log_once_a_minute(self, key: tuple, fmt: str, *args) -> None:
        """One log line per kind a minute, with how many came since the last line."""
        minute = int(time.time() // 60)
        with self._lock:
            seen = self._logged.setdefault(key, [None, 0])
            if seen[0] == minute:
                seen[1] += 1
                return
            since, seen[0], seen[1] = seen[1], minute, 0
        log.warning(fmt + " (%d more since the last line)", *args, since)

    def keep_failure(self, topic: str, msg: Any, error: BaseException, now: float) -> None:
        """Keep `msg`, which another thread could not store (a chain whose history write
        failed), as sent. While the writer thread runs it takes it in turn, the one writer; a
        writer whose thread is not running (not started, or stopped) writes it here, on a
        connection of its own."""
        kept = KeptFailure(topic, msg, f"{type(error).__name__}: {error}", now)
        with self._lock:
            standalone = self.state in (WRITER_NOT_STARTED, WRITER_STOPPED)
            if self.state == WRITER_DEAD:
                self.unrecorded += 1
            elif not standalone:
                self._q.put(kept)
        if not standalone:
            return
        with sqlite3.connect(str(self.db_path), timeout=self.timeout_sec) as own:
            self._keep(own, kept)
        self._committed([(kept, kept)])

    def _keep(self, conn: sqlite3.Connection, kept: KeptFailure) -> KeptFailure:
        """One stream_write_failures row: the message as JSON (Python's repr when it is not
        JSON)."""
        try:
            sent = json.dumps(kept.msg, default=repr)
        except (ValueError, TypeError, RecursionError) as e:
            log.warning("stream writer: %s is not JSON (%s), kept as its repr", kept.topic, e)
            sent = repr(kept.msg)
        conn.execute("INSERT INTO stream_write_failures(ts,topic,msg_json,error) VALUES(?,?,?,?)",
                     (kept.ts, kept.topic, sent, kept.error))
        return kept

    def _committed(self, batch: list) -> None:
        """A batch is in the database: count its rows and kept failures; the writer records."""
        with self._lock:
            for _item, out in batch:
                if isinstance(out, RowWritten):
                    self.rows_written += 1
                elif isinstance(out, KeptFailure):
                    self.failures += 1
                    self.last_failure, self.last_failure_ts = f"{out.topic}: {out.error}", out.ts
            if self.state == WRITER_BLOCKED:
                self.state, self.error, self.error_ts = WRITER_RECORDING, None, None

    def status(self) -> dict:
        """The writer's WriterStatus, as the heartbeat carries it."""
        with self._lock:
            s = {"state": self.state, "rows_written": self.rows_written,
                 "failures": self.failures, "last_failure": self.last_failure,
                 "last_failure_ct": (ct_label(self.last_failure_ts)
                                     if self.last_failure_ts is not None else None),
                 "queue_depth": self._q.qsize(), "waiting": len(self._waiting),
                 # a retry's open batch is part of what is waiting; spill records are on disk
                 "held": self._q.qsize() + max(len(self._waiting),
                                               0 if self._batch_spilled else len(self._batch)),
                 "held_bytes": self._waiting_bytes,
                 "spill": self._spill.status() if self._spill is not None else None,
                 "spills_kept": [dict(k) for k in self.spills_kept],
                 "left_on_disk": [dict(k) for k in self.left_on_disk],
                 "lost": self.lost, "lost_first_ts": self.lost_first_ts,
                 "lost_last_ts": self.lost_last_ts,
                 "unrecorded": self.unrecorded, "error": self.error,
                 "error_ct": ct_label(self.error_ts) if self.error_ts is not None else None}
        line, cls = _record_line(s)
        return asdict(WriterStatus(**s, line=line, cls=cls))

    async def run(self, sub: Subscription, *, stop: asyncio.Event) -> None:
        """Hand every bus message to the writer thread until `stop`; everything delivered
        before the stop is written and committed before this returns. Once the thread is dead,
        each message is counted unrecorded instead of queued for a thread that will not take it."""
        thread = threading.Thread(target=self._thread, args=(self._q,),
                                  name="stream-capture-writer", daemon=True)
        with self._lock:
            self.state = WRITER_RECORDING
        thread.start()
        try:
            while not stop.is_set():
                try:
                    self._hand(await asyncio.wait_for(sub.get(), timeout=0.25))
                except asyncio.TimeoutError:
                    continue
            while not sub.queue.empty():
                self._hand(await sub.get())
        finally:
            with self._lock:               # a dead thread takes no stop message
                if self.state != WRITER_DEAD:
                    self._q.put(None)
            await asyncio.to_thread(thread.join)

    def _hand(self, item) -> None:
        with self._lock:
            if self.state == WRITER_DEAD:
                self.unrecorded += 1
                return
            self._q.put(item)

    def _thread(self, q: "queue.SimpleQueue") -> None:
        try:
            self._write(q)
        except Exception as e:  # noqa: BLE001 -- recorded as the writer's death, then raised
            log.error("stream writer died: %s: %s", type(e).__name__, e)
            with self._lock:
                self.state, self.error, self.error_ts = WRITER_DEAD, f"{type(e).__name__}: {e}", time.time()
                # not recorded: the open batch, the round's messages not yet in it (the one that
                # ended the thread first; a retry's round holds its batch and what was waiting) and
                # the queue. A spill file's messages are on disk: the file stays, listed as left
                batch = 0 if self._batch_spilled else len(self._batch)
                self.unrecorded += batch + len(self._round) - self._stored + self._drained(q)
                if self._spill is not None:
                    self._spill.close()
                    self.left_on_disk.append(self._spill.left())
                self._batch, self._waiting, self._round, self._stored = [], [], [], 0
                self._spill, self._batch_spilled = None, False
            raise
        with self._lock:                   # anything handed in after the stop is not written
            self.state = WRITER_STOPPED
            self.unrecorded += self._drained(q)

    @staticmethod
    def _drained(q: "queue.SimpleQueue") -> int:
        """Empty the queue; how many messages it held."""
        n = 0
        while True:
            try:
                n += q.get_nowait() is not None
            except queue.Empty:
                return n

    def _store(self, conn: sqlite3.Connection, item):
        if isinstance(item, KeptFailure):
            return self._keep(conn, item)
        return self.insert(*item, conn=conn)

    def _open(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), timeout=self.timeout_sec)
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute(f"PRAGMA journal_size_limit={WAL_SIZE_LIMIT_BYTES}")
        return conn

    def _write(self, q: "queue.SimpleQueue") -> None:
        """The writer thread's loop. After a refusal the connection is closed and the next try
        opens a new one: a connection SQLite opened on a database that refused writes (a
        read-only file) keeps refusing after the database accepts them again."""
        conn = None
        try:
            last_commit, stopping = time.monotonic(), False
            while not (stopping and not self._waiting and self._spill is None):
                unread = self._spill is not None and self._spill.read_at < self._spill.size
                try:
                    item = q.get(timeout=0.001 if unread else
                                 max(self.batch_sec - (time.monotonic() - last_commit), 0.01))
                except queue.Empty:
                    item = False
                stopping = stopping or item is None
                incoming = [item] if item else []
                holding = bool(self._waiting) or self._spill is not None
                if holding:                # every queued message joins the held ones, in order
                    while not stopping:
                        try:
                            item = q.get_nowait()
                        except queue.Empty:
                            break
                        stopping = item is None
                        incoming += [item] if item else []
                    self._admit(incoming)
                    del incoming           # what was spilled is held on disk only
                    items = self._waiting
                else:
                    items = incoming
                self._round, self._stored = items, 0
                try:
                    if conn is None:
                        conn = self._open()
                    for item in items:
                        self._batch.append((item, self._store(conn, item)))
                        self._stored += 1
                    if self._batch and (holding or stopping or len(self._batch) >= self.batch_rows
                                        or time.monotonic() - last_commit >= self.batch_sec):
                        conn.commit()
                        batch, self._batch = self._batch, []
                        self._committed(batch)
                        last_commit = time.monotonic()
                        with self._lock:
                            self._waiting, self._waiting_bytes = [], 0
                    if self._spill is not None and not self._waiting:
                        self._write_back(conn)
                except DATABASE_REFUSALS as e:
                    if conn is not None:
                        conn.close()       # its open transaction is rolled back
                    conn = None
                    held = [] if self._batch_spilled else [item for item, _out in self._batch]
                    self._refused(e, held + items[self._stored:], holding, stopping)
        finally:
            if conn is not None:
                conn.close()

    def _refused(self, error: BaseException, held: list, holding: bool, stopping: bool) -> None:
        """The database refused a write: the open batch is rolled back and `held` (its messages
        and the ones not yet written, in order; spill records stay in their file) is written
        again after `retry_sec`. At the stop what is held is left on disk."""
        reason = f"{type(error).__name__}: {error}"
        self._log_once_a_minute(("refused", reason),
                                "stream writer: the database refused a write, %d messages held: %s",
                                len(held), reason)
        with self._lock:
            self._batch, self._batch_spilled = [], False
            if self.state != WRITER_BLOCKED:
                self.error_ts = time.time()
            self.state, self.error = WRITER_BLOCKED, reason
        if not holding:                    # held now: in memory up to the cap, then spilled
            with self._lock:
                self._waiting, self._waiting_bytes = [], 0
            self._admit(held)
        if stopping:
            self._leave_on_disk()
            return
        time.sleep(self.retry_sec)

    def _admit(self, items: list) -> None:
        """Hold `items`, in order: in memory while the held bytes stay within the cap, then, and
        for every newer message, in the spill file."""
        for item in items:
            if self._spill is None:
                size = _held_size(item)
                if self._waiting_bytes + size <= self.hold_cap_bytes:
                    with self._lock:
                        self._waiting.append(item)
                        self._waiting_bytes += size
                    continue
                path = self.db_path.with_name(f"{self.db_path.stem}.{int(time.time() * 1000)}.spill")
                try:
                    spill = _Spill(path)
                except OSError as e:
                    self._lose(item, e)
                    continue
                with self._lock:
                    self._spill = spill
                log.warning("stream writer: held messages past %d bytes go to %s", self.hold_cap_bytes, path)
            refused = self._spill.append(_spill_record(item))
            if refused is not None:
                self._lose(item, refused)

    def _lose(self, item, error: BaseException) -> None:
        """A message neither the database nor the spill file took: counted, with when it was
        received."""
        ts = _received(item)
        with self._lock:
            self.lost += 1
            if ts is not None:
                self.lost_first_ts = ts if self.lost_first_ts is None else min(self.lost_first_ts, ts)
                self.lost_last_ts = ts if self.lost_last_ts is None else max(self.lost_last_ts, ts)
        self._log_once_a_minute(("lost", type(error).__name__),
                                "stream writer: a message the spill file could not take is lost: %s: %s",
                                type(error).__name__, error)

    def _write_back(self, conn: sqlite3.Connection) -> None:
        """The next part of the spill file into the database, in one transaction; once all of
        it is in, verify it and delete the file, or keep the file when it does not verify."""
        spill = self._spill
        if spill.before is None:
            spill.before = {t: conn.execute(f"SELECT COALESCE(MAX(rowid), 0) FROM {t}").fetchone()[0]
                            for t in _KEY_COLUMN}
        if spill.read_at < spill.size:
            records, damaged = spill.read(SPILL_CHUNK)
            if records:
                self._batch_spilled = True
                for item, _end in records:
                    self._batch.append((item, self._store(conn, item)))
                end = records[-1][1]
                conn.execute("INSERT INTO stream_spill_progress(spill, written_back) VALUES(?,?) "
                             "ON CONFLICT(spill) DO UPDATE SET written_back=excluded.written_back",
                             (spill.path.name, spill.written_back + len(records)))
                conn.commit()
                batch, self._batch, self._batch_spilled = self._batch, [], False
                self._committed(batch)
                with self._lock:
                    spill.committed(batch, end)
            if damaged is not None:        # every good record before it is written back
                self._finish_spill(spill, conn, damaged)
            return
        self._finish_spill(spill, conn, _verify(conn, spill))

    def _finish_spill(self, spill: _Spill, conn: sqlite3.Connection, reason: "str | None") -> None:
        """A spill whose write-back is done: deleted when it verified (`reason` None), with its
        progress row; else kept, with the reason and how far its write-back got."""
        spill.close()
        if reason is None:
            os.remove(spill.path)
            log.info("stream writer: %s written back (%d messages) and verified; deleted",
                     spill.path, spill.messages)
        else:
            log.error("stream writer: %s kept, %d of its %d records written back: %s",
                      spill.path, spill.written_back, spill.messages, reason)
        with self._lock:
            if reason is not None:
                self.spills_kept.append({"path": str(spill.path), "reason": reason,
                                         "messages": spill.messages, "written_back": spill.written_back})
            self._spill = None
        if reason is None:
            conn.execute("DELETE FROM stream_spill_progress WHERE spill = ?", (spill.path.name,))
            conn.commit()

    def _leave_on_disk(self) -> None:
        """At a stop while the database refuses writes: what is held in memory goes to a spill
        file named for when the block began (older than the spill file's), and both stay."""
        if self._waiting:
            began = self.error_ts if self.error_ts is not None else time.time()
            try:
                held = _Spill(self.db_path.with_name(f"{self.db_path.stem}.{int(began * 1000)}.spill"))
            except OSError as e:
                for item in self._waiting:
                    self._lose(item, e)
                held = None
            if held is not None:
                for item in self._waiting:
                    refused = held.append(_spill_record(item))
                    if refused is not None:
                        self._lose(item, refused)
                held.close()
                with self._lock:
                    self.left_on_disk.append(held.left())
        with self._lock:
            if self._spill is not None:
                self._spill.close()
                self.left_on_disk.append(self._spill.left())
            self._spill, self._waiting, self._waiting_bytes = None, [], 0
