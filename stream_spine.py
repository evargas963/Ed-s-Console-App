"""The pieces the capture daemon and its readers share.

They are the stream database path and schema, the message shapes, the in-process message bus,
feed health, and the database writer.

  - Every Schwab message is published once on the MessageBus and becomes its topic's current
    record (the newest by Schwab's time); the writer reads every message (LOG), the live readers
    each changed topic's current record and every message that is its own item (LATEST).
  - Every message goes to the one database (db_authority.canonical_db_path).
  - The writer runs on its own thread with its own SQLite connection, so a slow disk can
    never stall the Schwab socket.
  - A message the writer cannot store as a row is kept as sent, with its error, in
    stream_write_failures; while the database refuses writes the writer holds the messages, in
    memory up to a cap and then in spill files beside the database, and writes them back in
    order when it can, at its next start when it stopped first; its state (WriterStatus) rides
    the daemon's heartbeat.
"""

from __future__ import annotations

import asyncio
import itertools
import json
import logging
import os
import queue
import sqlite3
import sys
import threading
import time
from collections import Counter
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import IO, TYPE_CHECKING, Any, TypedDict, cast, override

import time_et
from calc.l1_trade_observation import PRINT_FIELDS
from calc.order_flow import Book, Exchanges, Json, Level
from calibration.complete_chain_capture import ensure_schema, store_capture_message
from db_authority import resolve_stream_db_path
from json_blob_codec import decode_text_blob, encode_text_blob
from numeric_contract import schwab_count, schwab_number
from option_contract import (
    NO_GREEKS,
    NO_TOP,
    QUOTE_FIELDS,
    Received,
    Streamed,
    StreamedGreeks,
    StreamedTop,
    streamed_greeks,
    streamed_top,
)
from time_et import ET, ct_label

if TYPE_CHECKING:
    from state.news_store import NewsHeadline

log = logging.getLogger(__name__)

#: A message as published on the bus (MessageBus.publish): one of the stream's shapes, or a plain
#: dict (the chain sweep's answers and chains, the watchlist, the feed status).
type BusMessage = (
    QuoteMessage
    | BarMessage
    | VerbatimMessage
    | BookMessage
    | NewsMessage
    | SubscriptionMessage
    | dict[str, Any]
)
#: A bus message as a reader may find it: the dict its builder made, or, read back from a spill
#: file or handed in by a test, any JSON value. Code that reads one checks it is a dict first.
type Payload = dict[str, Any] | list[Any] | str | float | None
#: What the writer holds: a bus message with its topic, or a message kept as sent with its error.
type Item = tuple[str, Payload] | KeptFailure
#: What became of a held message: its row, its kept failure, or nothing to write (insert).
type Outcome = RowWritten | KeptFailure | None


STREAM_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS stream_quotes_raw (
    ts_recv REAL NOT NULL,
    symbol TEXT NOT NULL,
    native_json TEXT,
    schwab_ts INTEGER
);
CREATE TABLE IF NOT EXISTS stream_book_raw (
    ts_recv REAL NOT NULL,
    symbol TEXT NOT NULL,
    service TEXT NOT NULL,
    native_json TEXT NOT NULL,
    schwab_ts INTEGER
);
CREATE TABLE IF NOT EXISTS stream_options_quotes_raw (
    ts_recv REAL NOT NULL,
    symbol TEXT NOT NULL,
    native_json TEXT NOT NULL,
    schwab_ts INTEGER
);
CREATE TABLE IF NOT EXISTS stream_bars_raw (
    ts_recv REAL NOT NULL,
    symbol TEXT NOT NULL,
    native_json TEXT,
    schwab_ts INTEGER
);
-- NEWS_HEADLINE items, verbatim (not in Schwab's Streamer API,
-- docs/schwab/schwab_streamer_api.pdf §1.1 "Services available"; answers code 0).
CREATE TABLE IF NOT EXISTS stream_news_raw (
    ts_recv REAL NOT NULL,
    symbol TEXT NOT NULL,
    native_json TEXT NOT NULL,
    schwab_ts INTEGER
);
CREATE INDEX IF NOT EXISTS idx_snr_sym_ts ON stream_news_raw(symbol, ts_recv);
-- Schwab's /pricehistory answers, verbatim: one row per series asked (PRICE_HISTORY), the whole
-- answer.
CREATE TABLE IF NOT EXISTS stream_pricehistory_raw (
    ts_recv REAL NOT NULL,
    symbol TEXT NOT NULL,
    series TEXT NOT NULL,
    native_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_sphr_sym_ts ON stream_pricehistory_raw(symbol, series, ts_recv);
-- Schwab's /chains answers (one expiry each) and /quotes answers, every one the chain sweep asked
-- for, the body exactly as received, gzip-compressed (json_blob_codec.encode_text_blob), with its
-- HTTP status; kept five sessions (KEPT_BY_TIME).
CREATE TABLE IF NOT EXISTS rest_chains_raw (
    ts_recv REAL NOT NULL,
    symbol TEXT NOT NULL,
    expiry TEXT NOT NULL,
    status INTEGER NOT NULL,
    body BLOB NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_rcr_ts ON rest_chains_raw(ts_recv);
CREATE TABLE IF NOT EXISTS rest_quotes_raw (
    ts_recv REAL NOT NULL,
    status INTEGER NOT NULL,
    body BLOB NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_rqr_ts ON rest_quotes_raw(ts_recv);
-- The rows of ARCHIVED tables received before the newest five sessions, moved here by the
-- nightly keep in blocks: their table, the first and last receipt time, how many, the column
-- names, and the rows (archive_block: a JSON list per row, gzip-compressed, lossless).
CREATE TABLE IF NOT EXISTS stream_archive (
    source TEXT NOT NULL,
    first_ts REAL NOT NULL,
    last_ts REAL NOT NULL,
    rows INTEGER NOT NULL,
    columns TEXT NOT NULL,
    body BLOB NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_sa_source_ts ON stream_archive(source, first_ts);
-- Schwab's /markets answers, verbatim: one row per market date asked, its status and the whole
-- answer.
CREATE TABLE IF NOT EXISTS stream_markets_raw (
    ts_recv REAL NOT NULL,
    date TEXT NOT NULL,
    status INTEGER NOT NULL,
    native_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_smkr_date_ts ON stream_markets_raw(date, ts_recv);
-- The watchlist, the one list of tickers Schwab is asked for (written only by the daemon): one row
-- per add or removal the console asked for -- the whole list after it, what happened to the
-- ticker, and Schwab's /quotes answer to an add's check, as sent. The newest row is the list.
CREATE TABLE IF NOT EXISTS stream_watchlist (
    ts_recv REAL NOT NULL,
    symbol TEXT NOT NULL,
    op TEXT NOT NULL,
    tickers_json TEXT NOT NULL,
    status INTEGER,
    native_json TEXT
);
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
-- Every message a write refused, kept as sent: when it failed, its topic (a bus topic,
-- chain_history.<TICKER> for a chain whose history write failed, keep.<table> or
-- stream_spill_progress for a statement of the writer's own), the message as JSON, and the
-- error (type and text). Nothing here is a correction; each row is what could not be stored.
CREATE TABLE IF NOT EXISTS stream_write_failures (
    ts REAL NOT NULL,
    topic TEXT NOT NULL,
    msg_json TEXT NOT NULL,
    error TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_swf_ts ON stream_write_failures(ts);
-- Every level a price reached or passed, one row per cross, each price's crosses written together
-- (store_first: the console holds a cross only once it is here).
CREATE TABLE IF NOT EXISTS level_crosses (
    cross_id        INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker          TEXT    NOT NULL,
    ts_utc          REAL    NOT NULL,
    ts_et           TEXT    NOT NULL,
    level_name      TEXT    NOT NULL,
    level_value     REAL    NOT NULL,
    direction       TEXT    NOT NULL,
    spot_at_cross   REAL    NOT NULL,
    zone_before     TEXT,
    zone_after      TEXT,
    timeframe       TEXT
);
CREATE INDEX IF NOT EXISTS idx_cross_ticker_ts ON level_crosses(ticker, ts_utc);
-- How far each spill file's write-back got, written in the same transaction as each part it
-- wrote: how many of its records are in the database.
CREATE TABLE IF NOT EXISTS stream_spill_progress (
    spill TEXT PRIMARY KEY,
    written_back INTEGER NOT NULL
);
"""

#: Quotes, books and option quotes arrive in receipt order, thousands of symbols a second: indexed
#: by receipt time, which grows at one end, so an insert writes few index pages. Built only with a
#: new table; an existing table is reindexed by hand (docs/DATA_FLOW.md §3.3), never at a start.
RECEIPT_TIME_INDEXES = {
    "stream_quotes_raw": "CREATE INDEX idx_sqr_ts ON stream_quotes_raw(ts_recv)",
    "stream_book_raw": "CREATE INDEX idx_sbkr_ts ON stream_book_raw(ts_recv)",
    "stream_options_quotes_raw": "CREATE INDEX idx_soqr_ts ON stream_options_quotes_raw(ts_recv)",
}

WAL_SIZE_LIMIT_BYTES = 256 * 1024 * 1024


# ---------------------------------------------------------------------------- message shapes
# The one shape per topic; the daemon builds through these and the writer reads them.


#: Every Schwab message carries `schwab_ts`: the timestamp (ms) Schwab put on the frame that
#: delivered it. Which value is current is decided by it (docs/DATA_FLOW.md §2 D1).


class QuoteMessage(TypedDict):
    """quote.* (LEVELONE_EQUITIES) as quote_msg builds it: the flat columns and `native`."""

    ts_recv: float
    schwab_ts: int | None
    symbol: str
    bid: float | None
    ask: float | None
    last: float | None
    bid_size: int | None
    ask_size: int | None
    last_size: int | None
    total_volume: int | None
    quote_time_ms: int | None
    trade_time_ms: int | None
    src: str
    native: dict[str, Any] | None


class VerbatimMessage(TypedDict):
    """optquote.* (LEVELONE_OPTIONS) as verbatim_msg builds it: Schwab's item as `content`."""

    ts_recv: float
    schwab_ts: int | None
    symbol: str
    content: dict[str, Any]
    src: str


class BookMessage(VerbatimMessage):
    """book.* (NYSE_BOOK / NASDAQ_BOOK / OPTIONS_BOOK) as book_msg builds it, with its service."""

    service: str


class NewsMessage(VerbatimMessage):
    """news.* (NEWS_HEADLINE): Schwab's item and Feed's read of its fields (`headline`).

    Feed builds it (feed.connection._message, its fields read by feed.connection.news_headline);
    the header's news line takes `headline`.
    """

    headline: NewsHeadline


class BarMessage(TypedDict):
    """bar1m.* (CHART_EQUITY) as bar_msg builds it: the flat columns and `native`."""

    ts_recv: float
    schwab_ts: int | None
    symbol: str
    bar_start_ms: int | None
    open: float | None
    high: float | None
    low: float | None
    close: float | None
    volume: int | None
    src: str
    native: dict[str, Any] | None


class SubscriptionMessage(TypedDict):
    """sub.* as subscription_msg builds it: one request the daemon sent and Schwab's answer."""

    ts: float
    service: str
    command: str
    symbols: list[str]
    code: int | None
    reason: str


def quote_msg(
    *,
    symbol: str,
    bid: float | None = None,
    ask: float | None = None,
    last: float | None = None,
    bid_size: int | None = None,
    ask_size: int | None = None,
    last_size: int | None = None,
    total_volume: int | None = None,
    quote_time_ms: int | None = None,
    trade_time_ms: int | None = None,
    src: str,
    ts_recv: float,
    native: dict[str, Any] | None = None,
    schwab_ts: int | None = None,
) -> QuoteMessage:
    """quote.* (LEVELONE_EQUITIES).

    `native` is Schwab's item verbatim -- readers need fields the flat columns do not carry
    (BID_TIME_MILLIS, LAST_MIC_ID, ...).
    """
    return {
        "ts_recv": ts_recv,
        "schwab_ts": schwab_ts,
        "symbol": symbol,
        "bid": bid,
        "ask": ask,
        "last": last,
        "bid_size": bid_size,
        "ask_size": ask_size,
        "last_size": last_size,
        "total_volume": total_volume,
        "quote_time_ms": quote_time_ms,
        "trade_time_ms": trade_time_ms,
        "src": src,
        "native": native,
    }


def book_msg(
    *,
    symbol: str,
    service: str,
    content: dict[str, Any],
    src: str,
    ts_recv: float,
    schwab_ts: int | None = None,
) -> BookMessage:
    """book.* (NYSE_BOOK / NASDAQ_BOOK / OPTIONS_BOOK), Schwab's item verbatim, and its service."""
    return {
        **verbatim_msg(
            symbol=symbol, content=content, src=src, ts_recv=ts_recv, schwab_ts=schwab_ts
        ),
        "service": service,
    }


def verbatim_msg(
    *,
    symbol: str,
    content: dict[str, Any],
    src: str,
    ts_recv: float,
    schwab_ts: int | None = None,
) -> VerbatimMessage:
    """optquote.* (LEVELONE_OPTIONS) and news.* (NEWS_HEADLINE), Schwab's item verbatim.

    A news message carries one thing more: Feed's read of the item's fields, `headline`
    (feed.connection.news_headline), which the header's news line takes.
    """
    return {
        "ts_recv": ts_recv,
        "schwab_ts": schwab_ts,
        "symbol": symbol,
        "content": content,
        "src": src,
    }


def bar_msg(
    *,
    symbol: str,
    bar_start_ms: int | None = None,
    open: float | None = None,
    high: float | None = None,
    low: float | None = None,
    close: float | None = None,
    volume: int | None = None,
    src: str,
    ts_recv: float,
    native: dict[str, Any] | None = None,
    schwab_ts: int | None = None,
) -> BarMessage:
    """bar1m.* (CHART_EQUITY). `native` is Schwab's item verbatim (SEQUENCE, CHART_DAY, ...)."""
    return {
        "ts_recv": ts_recv,
        "schwab_ts": schwab_ts,
        "symbol": symbol,
        "bar_start_ms": bar_start_ms,
        "open": open,
        "high": high,
        "low": low,
        "close": close,
        "volume": volume,
        "src": src,
        "native": native,
    }


def subscription_msg(
    *,
    service: str,
    command: str,
    symbols: list[str],
    code: int | None,
    reason: str,
    ts: float,
) -> SubscriptionMessage:
    """sub.* -- one request the daemon sent and Schwab's answer."""
    return {
        "ts": ts,
        "service": service,
        "command": command,
        "symbols": list(symbols),
        "code": code,
        "reason": reason,
    }


# ---------------------------------------------------------------------------- the bus

#: How a reader takes the bus. LOG: every message, in order -- the database writer, the record of
#: everything Schwab sent (docs/DATA_FLOW.md §2 D4). LATEST, every live reader: for each topic
#: with versions (VERSIONED) that changed since its last read, that topic's current record -- a
#: newer value replaces an older one at once and nothing old waits -- and every message that is
#: its own item, once, in the order published: a message of a topic without versions, and a
#: LEVELONE message that brings a field of the last trade (a trade, MessageBus.publish). What a
#: reader holds is bounded by the number of topics and the items it has not yet taken, never by
#: how fast Schwab sends a value (D3).
LOG, LATEST = "log", "latest"
#: the topics whose messages are versions of one thing, by their kind: a symbol's quote or book, a
#: ticker's chain, a series' candles, a date's sessions. A message of any other topic is its own
#: item -- a /quotes answer for its own contracts, one minute's bar, a news story, the answer to
#: one watchlist request, a raw answer or a status for the record -- and replaces nothing a reader
#: has not yet taken
VERSIONED = frozenset({"quote", "optquote", "book", "chain", "pricehistory", "markets"})
#: the end of a LOG reader's messages, put in its queue once the stop is set (_end_at): no topic
LOG_END: tuple[str, Any] = ("", None)
#: the topics whose messages carry only the fields that changed (Schwab's LEVELONE services),
#: by the key of the Schwab item in the message: their current record merges field by field
FIELD_DELTA = {"quote": "native", "optquote": "content"}
#: what a message makes of its topic's current record (MessageBus._newest, _chain): nothing new
#: (it is older, or every field it carries is); a newer version; or a newer version of a LEVELONE
#: record that took a field of the last trade (calc.l1_trade_observation.PRINT_FIELDS), which is
#: also the trade's own item for each LATEST reader
KEPT, NEWER, TRADE = "kept", "newer", "trade"
#: what the stream holds of a symbol it has sent nothing of
NOT_STREAMED = Streamed(NO_TOP, NO_GREEKS)


def read_streamed(content: dict[str, Any], stamps: dict[str, tuple[Any, Any]]) -> Streamed:
    """Read a LEVELONE record's fields (`content`, each received at its `stamps` time).

    Its top of book, and its Greeks, volatility, volume and the stock's price it carries, each
    with the time its own field was received (a message carries only the fields that changed); a
    Greek Schwab sends as -999 is no value, and TOTAL_VOLUME is a count as sent (a reported 0 is
    0, AGENTS.md rule 2). Read once per version of the record, on its first read
    (streamed_record).
    """
    sent = {
        name: Received(v, stamps[name.upper()][1]) for name, v in streamed_greeks(content).items()
    }
    volume = schwab_count(content.get("TOTAL_VOLUME"))
    if volume is not None:
        sent["total_volume"] = Received(volume, stamps["TOTAL_VOLUME"][1])
    if "UNDERLYING_PRICE" in content:
        underlying = schwab_number(content["UNDERLYING_PRICE"])
        sent["underlying_price"] = Received(underlying, stamps["UNDERLYING_PRICE"][1])
    return Streamed(StreamedTop(**streamed_top(content)), StreamedGreeks(**sent))


def streamed_record(record: tuple[str, dict[str, Any]] | None) -> Streamed:
    """Return what the stream holds of a LEVELONE record on the bus, (topic, record).

    Its fields read on the first read of this version of the record (read_streamed) and held in
    it as `streamed`; NOT_STREAMED when the bus holds no record. A version is never changed: a
    message makes a new record (MessageBus._newest), so a read on any thread reads one version
    whole, and two first reads at once read the same fields and hold equal values.
    """
    if record is None:
        return NOT_STREAMED
    topic, rec = record
    held: Streamed | None = rec["streamed"]
    if held is None:
        held = read_streamed(rec[FIELD_DELTA[topic.split(".", 1)[0]]], rec["field_ts"])
        rec["streamed"] = held
    return held


def quotes_at_trade(record: tuple[str, dict[str, Any]]) -> tuple[StreamedTop, StreamedTop]:
    """Return the quotes a version of a LEVELONE record held when it came, read as its top is.

    `record` is the version a message that brought a trade made (MessageBus.publish: the trade's
    own item): its newest quote and the one that quote replaced (`quote_before`), each its quote
    fields (QUOTE_FIELDS) as they stood when the trade came, however many messages came after it.
    NO_TOP's values for a quote not yet sent. Read when a print is kept
    (state.OrderFlowState.push_level_one), not on every message.
    """
    topic, rec = record
    held = rec[FIELD_DELTA[topic.split(".", 1)[0]]]
    return (
        StreamedTop(**streamed_top({q: held[q] for q in QUOTE_FIELDS if q in held})),
        StreamedTop(**streamed_top(rec["quote_before"])),
    )


def read_book(content_item: dict[str, Any], service: str) -> Book | None:
    """Read a Schwab book message; this is its one reader.

    None when it carries neither side (a side Schwab sent no levels for is empty).
    """
    if content_item.get("BIDS") is None and content_item.get("ASKS") is None:
        return None
    return Book(
        service,
        schwab_number(content_item.get("BOOK_TIME")),
        tuple(_side_levels(content_item, "BIDS")),
        tuple(_side_levels(content_item, "ASKS")),
    )


def _side_levels(content_item: dict[str, Any], side: str) -> list[Level]:
    """Return one side of a Schwab book, "BIDS" or "ASKS".

    (price, TOTAL_VOLUME, the level's per-exchange sizes) for each level, as sent. A level
    without a number for both price and size is not a level.
    """
    price_key, size_key = (
        ("BID_PRICE", "BID_VOLUME") if side == "BIDS" else ("ASK_PRICE", "ASK_VOLUME")
    )
    raw: Json = content_item.get(side)
    if not raw:
        return []
    out: list[Level] = []
    for level in raw if isinstance(raw, list) else [raw]:
        for lv in level if isinstance(level, list) else [level]:
            if not isinstance(lv, dict):
                continue
            p = schwab_number(lv.get(price_key))
            v = schwab_count(lv.get("TOTAL_VOLUME"))
            if p is not None and v is not None:
                out.append((p, v, _exchange_sizes(lv.get(side), size_key)))
    return out


def _exchange_sizes(rows: Json, size_key: str) -> Exchanges | None:
    """Return a level's own rows, one per exchange or market maker, as sent.

    Each row is (EXCHANGE, BID_VOLUME or ASK_VOLUME, its quote time;
    docs/schwab/schwab_streamer_api.pdf §4 Book Market Makers: field 2, "Quote time in
    milliseconds", which schwab-py names SEQUENCE; None when not sent). None when the level
    carries none, or a row lacks its code or size.
    """
    if not isinstance(rows, list) or not rows:
        return None
    out: list[tuple[str, float, float | None]] = []
    for row in rows:
        if not isinstance(row, dict):
            return None
        code, size = row.get("EXCHANGE"), schwab_count(row.get(size_key))
        if not isinstance(code, str) or not code or size is None:
            return None
        out.append((code, size, schwab_number(row.get("SEQUENCE"))))
    return tuple(out)


def current_key(topic: str, msg: BusMessage | Payload) -> str:
    """Return a topic's key in the current state, by its source and, for a book, its service.

    By its source (`src`: a message from elsewhere is never merged into Schwab's record) and,
    for a book, its service (NYSE_BOOK and NASDAQ_BOOK are two books of one symbol).
    """
    if not isinstance(msg, dict):
        return topic
    if topic.startswith("book."):
        return f"{topic}@{msg.get('service')}#{msg.get('src')}"
    return f"{topic}#{msg.get('src')}"


#: each Schwab service's bus topic kind and the source its messages carry
SERVICE_TOPIC = {
    "LEVELONE_EQUITIES": ("quote", "schwab_l1"),
    "CHART_EQUITY": ("bar1m", "schwab_chart"),
    "LEVELONE_OPTIONS": ("optquote", "schwab_options_l1"),
    "NEWS_HEADLINE": ("news", "schwab_news"),
    "NYSE_BOOK": ("book", "schwab_book"),
    "NASDAQ_BOOK": ("book", "schwab_book"),
    "OPTIONS_BOOK": ("book", "schwab_book"),
}


def held_key(service: str, sym: str) -> str:
    """Return the current-record key of `sym` streamed on Schwab `service` (current_key)."""
    kind, src = SERVICE_TOPIC[service]
    return current_key(f"{kind}.{sym}", {"service": service, "src": src})


def _older(t: float | None, than: float | None) -> bool:
    """`t` is older than `than` by Schwab's time; a message without one cannot be compared."""
    return t is not None and than is not None and t < than


def _own(topic: str) -> bool:
    """Tell whether a topic's message is its own item, no version of the one before (VERSIONED)."""
    return topic.split(".", 1)[0] not in VERSIONED


@dataclass
class Subscription:
    prefix: str
    policy: str
    current: dict[str, tuple[str, Any]]  # the bus's current state
    #: LOG: every message, then LOG_END at the stop (_end_at)
    queue: asyncio.Queue[tuple[str, Any]] = field(default_factory=asyncio.Queue[tuple[str, Any]])
    #: LATEST, in the order each came: a changed topic's key (its current record is read when it
    #: is taken, so a newer version replaces one that still waits), or a message that is its own
    #: item, under a key of its own (`items`), with the message (a trade's: the version of its
    #: record it made)
    changed: dict[str, tuple[str, Any] | None] = field(
        default_factory=dict[str, tuple[str, Any] | None]
    )
    wake: asyncio.Event = field(default_factory=asyncio.Event)
    items: itertools.count[int] = field(default_factory=itertools.count)

    def deliver(self, key: str, topic: str, msg: Any, own: bool) -> None:
        """Hand over a message: its topic's record at `key`, or `own`, the item itself.

        An item stands in for its topic's record waiting at `key`: a trade's item is that record's
        newest version (MessageBus.publish), so a reader takes each version in the order made and
        never one older than one it took.
        """
        if self.policy == LOG:
            self.queue.put_nowait((topic, msg))
            return
        if own:
            self.changed.pop(key, None)
            self.changed[f"#{next(self.items)}"] = (topic, msg)
        else:
            self.changed[key] = None
        self.wake.set()

    def _take(self, key: str) -> tuple[str, Any] | None:
        """Take what waits at `key`: an item itself, or its topic's current record."""
        item = self.changed.pop(key)
        return self.current.get(key) if item is None else item

    async def get(self) -> tuple[str, Any]:
        """Return the next message (LOG), or the next of what waits (LATEST).

        LATEST: a changed topic's (topic, current record), or an item's (topic, message). A
        chain's record is its parts, in order.
        """
        if self.policy == LOG:
            return await self.queue.get()
        while True:
            while self.changed:
                entry = self._take(next(iter(self.changed)))
                if entry is not None:
                    return entry
            self.wake.clear()
            await self.wake.wait()

    def taken(self, most: int) -> list[tuple[str, Any]]:
        """Return up to `most` of what waits for a LATEST reader, now, in the order each came.

        A changed topic's current record, or an item's message.
        """
        keys = list(itertools.islice(self.changed, most))
        return [entry for key in keys if (entry := self._take(key)) is not None]


async def _end_at(stop: asyncio.Event, sub: Subscription) -> None:
    """Put the end of a LOG reader's messages (LOG_END) into its queue once `stop` is set.

    It goes behind every message delivered before the stop, so the reader takes those first.
    """
    await stop.wait()
    sub.queue.put_nowait(LOG_END)


class MessageBus:
    """Every Schwab message is published once.

    It becomes its topic's current record -- the newest by Schwab's time (`schwab_ts`, the
    frame's timestamp; a chain by its fetch time): a LEVELONE message merged field by field, its
    fields read on the first read of each version (streamed_record), a book, bar or news item whole,
    a chain whole once all its parts are in -- and each reader takes it by its policy (LOG or
    LATEST). A message that is its own item (a topic not VERSIONED) is also handed to each LATEST
    reader itself: the one after it never replaces it before it is taken, and a reader that
    subscribes later starts with the newest alone. So is a trade: a LEVELONE message that brings a
    field of the last trade (`brought_trade`) hands each LATEST reader the version of the record
    it made, so no trade is replaced by the next before a reader takes it; a reader that
    subscribes later starts with each record's newest trade and record. A LEVELONE record also
    keeps the quote its newest quote replaced (`quote_before`): Schwab sends a trade with the quote
    that followed it, so a trade is read against the quote in force when it was made
    (calc.l1_trade_observation.quote_in_force), of the quotes its own version holds
    (quotes_at_trade).
    """

    def __init__(self) -> None:
        self._subs: list[Subscription] = []
        #: key (current_key) -> (topic, record)
        # a topic's record (a dict); a chain's, its parts (a list)
        self.current: dict[str, tuple[str, Any]] = {}
        #: chain topic -> (fetch time, {part: message}, parts): the newest fetch, filling
        self._chains: dict[str, tuple[float, dict[int, Mapping[str, Any]], int]] = {}
        #: key (current_key) -> the version of a LEVELONE record that brought its last trade: the
        #: trade's item a reader that subscribes later starts with (subscribe)
        self._trades: dict[str, dict[str, Any]] = {}

    def subscribe(self, prefix: str, *, policy: str = LATEST) -> Subscription:
        """Subscribe a reader; a LATEST one starts with every current record under `prefix`.

        A LEVELONE record that a message bringing no trade made newer comes after its last trade's
        item: the newest trade is never lost behind a later quote.
        """
        sub = Subscription(prefix=prefix, policy=policy, current=self.current)
        if policy == LATEST:
            for key, (topic, record) in self.current.items():
                if not topic.startswith(prefix):
                    continue
                if key in self._trades and self._trades[key] is not record:
                    sub.deliver(key, topic, self._trades[key], True)
                sub.deliver(key, topic, record, _own(topic))
        self._subs.append(sub)
        return sub

    def unsubscribe(self, sub: Subscription) -> None:
        if sub in self._subs:
            self._subs.remove(sub)

    def publish(self, topic: str, msg: BusMessage) -> None:
        key = current_key(topic, msg)
        chain = topic.startswith("chain.")
        made = self._chain(key, topic, msg) if chain else self._newest(key, topic, msg)
        # a message that is its own item reaches every live reader itself: the next one of its
        # topic is another answer, bar or story, never a newer version of this one. So does a
        # trade, as the version of its record it made: the next message of its symbol never
        # replaces it before a reader takes it
        item = msg if _own(topic) else self.current[key][1] if made == TRADE else None
        for sub in self._subs:
            if not topic.startswith(sub.prefix):
                continue
            # a chain's record is its own history (the chain sweep writes it), never the log's
            if sub.policy == LOG and not chain:
                sub.deliver(key, topic, msg, False)
            elif sub.policy == LATEST and (item is not None or made != KEPT):
                sub.deliver(key, topic, item, item is not None)

    def _newest(self, key: str, topic: str, msg: BusMessage) -> str:
        """Make `msg` part of its topic's current record where it is the newest by Schwab's time.

        Returns what it made of the record: KEPT, NEWER, or TRADE.
        """
        held = self.current.get(key)
        t: int | None = msg.get("schwab_ts")
        body_key = FIELD_DELTA.get(topic.split(".", 1)[0])
        body: Payload = msg.get(body_key) if body_key is not None else None
        if body_key is None or not isinstance(body, dict):  # a whole record: replaced whole
            if held is not None and _older(t, held[1].get("schwab_ts")):
                return KEPT
            self.current[key] = (topic, msg)
            return NEWER
        stamp = (t, msg.get("ts_recv"))
        before: dict[str, Any] = {}
        # a message that brings a field of the last trade, among those it takes, is a trade: the
        # version it makes holds the trade with the quotes in force then (quotes_at_trade).
        # Whether it is a new trade or the held one restated is the tape's to read, by
        # calc.l1_trade_observation.is_adjacent_restatement
        if held is None:  # every field it brings is taken
            merged, stamps, top = dict(body), dict.fromkeys(body, stamp), msg
            traded = not body.keys().isdisjoint(PRINT_FIELDS)
        else:
            rec = held[1]
            merged, stamps = dict(rec[body_key]), dict(rec["field_ts"])
            took = [f for f in body if f not in stamps or not _older(t, stamps[f][0])]
            if not took:
                return KEPT
            # the quote this message replaces, whole as the record held it: a message that changes
            # a quote field the record holds. One that brings no quote field, restates the quote
            # held, or only fills in a field never sent, leaves the one kept before
            before = rec["quote_before"]
            for f in QUOTE_FIELDS:
                if f in body and f in merged and body[f] != merged[f] and f in took:
                    before = {q: merged[q] for q in QUOTE_FIELDS if q in merged}
                    break
            for f in took:
                merged[f], stamps[f] = body[f], stamp
            top = rec if _older(t, rec.get("schwab_ts")) else msg  # the record's own time
            traded = not PRINT_FIELDS.isdisjoint(took)
        # a new version of the record, whose fields are read on its first read (streamed_record)
        version: dict[str, Any] = {
            **top,
            body_key: merged,
            "field_ts": stamps,
            "streamed": None,
            "quote_before": before,
            "brought_trade": traded,
        }
        self.current[key] = (topic, version)
        if not traded:
            return NEWER
        self._trades[key] = version
        return TRADE

    def _chain(self, key: str, topic: str, msg: Mapping[str, Any]) -> str:
        """Take a chain part (a failed fetch is its one part).

        The newest fetch of the ticker is kept; once all its parts are in it replaces the current
        chain whole (NEWER; else KEPT).
        """
        ts = msg["ts_recv"]
        held: tuple[float, dict[int, Mapping[str, Any]], int] | None
        held = self._chains.get(key)
        if held is not None and ts < held[0]:
            return KEPT  # an older fetch: never current
        if held is None or ts > held[0]:
            held = (ts, {}, msg["parts"])
            self._chains[key] = held
        held[1][msg["part"]] = msg
        if len(held[1]) < held[2]:
            return KEPT
        self.current[key] = (topic, [held[1][i] for i in sorted(held[1])])
        return NEWER


class ServiceAge(TypedDict):
    """How long before the report a Schwab service last carried data (HealthRegistry.report)."""

    age_sec: float


class HealthRegistry:
    """When each Schwab service last carried data: an observation, not a liveness verdict.

    Live is live_market_plane.feed_live_for -- Schwab sends only changes, so a quiet service on
    an open socket is live.
    """

    def __init__(self) -> None:
        self._last: dict[str, float] = {}

    def beat(self, feed: str, ts: float) -> None:
        self._last[feed] = ts

    def last(self, feed: str) -> float | None:
        """When this feed last carried data (None: never, this connection)."""
        return self._last.get(feed)

    def report(self, now: float) -> dict[str, ServiceAge]:
        return {f: {"age_sec": now - ts} for f, ts in self._last.items()}


# ---------------------------------------------------------------------------- the writer

#: each kind's insert and the row it binds, built from the message. The builder is handed every
#: message of its kind as it came, one without the shape its table needs included: what it raises
#: then is the message's own failure (ROW_FAILURES), so its parameter is not a dict by type.
_INSERTS: dict[str, tuple[str, Callable[[Any], tuple[Any, ...]]]] = {
    "feedstatus": (
        "INSERT INTO stream_feed_status(ts,service,socket_open,schwab_last_frame_ts,"
        "held,last_data_ts) VALUES(?,?,?,?,?,?)",
        lambda m: (
            m["ts"],
            m["service"],
            int(m["socket_open"]),
            m.get("schwab_last_frame_ts"),
            m["held"],
            m.get("last_data_ts"),
        ),
    ),
    "quote": (
        "INSERT INTO stream_quotes_raw(ts_recv,symbol,native_json,schwab_ts) VALUES(?,?,?,?)",
        lambda m: (
            m["ts_recv"],
            m["symbol"],
            _json(m["native"]),
            m["schwab_ts"],
        ),
    ),
    "book": (
        "INSERT INTO stream_book_raw(ts_recv,symbol,service,native_json,schwab_ts) "
        "VALUES(?,?,?,?,?)",
        lambda m: (
            m["ts_recv"],
            m["symbol"],
            m["service"],
            json.dumps(m["content"]),
            m["schwab_ts"],
        ),
    ),
    "optquote": (
        "INSERT INTO stream_options_quotes_raw(ts_recv,symbol,native_json,schwab_ts) "
        "VALUES(?,?,?,?)",
        lambda m: (
            m["ts_recv"],
            m["symbol"],
            json.dumps(m["content"]),
            m["schwab_ts"],
        ),
    ),
    "bar1m": (
        "INSERT INTO stream_bars_raw(ts_recv,symbol,native_json,schwab_ts) VALUES(?,?,?,?)",
        lambda m: (
            m["ts_recv"],
            m["symbol"],
            _json(m["native"]),
            m["schwab_ts"],
        ),
    ),
    "news": (
        "INSERT INTO stream_news_raw(ts_recv,symbol,native_json,schwab_ts) VALUES(?,?,?,?)",
        lambda m: (
            m["ts_recv"],
            m["symbol"],
            json.dumps(m["content"]),
            m["schwab_ts"],
        ),
    ),
    "pricehistory": (
        "INSERT INTO stream_pricehistory_raw(ts_recv,symbol,series,native_json) VALUES(?,?,?,?)",
        lambda m: (m["ts_recv"], m["symbol"], m["series"], json.dumps(m["answer"])),
    ),
    "chainanswer": (
        "INSERT INTO rest_chains_raw(ts_recv,symbol,expiry,status,body) VALUES(?,?,?,?,?)",
        lambda m: (
            m["ts_recv"],
            m["symbol"],
            m["expiry"],
            m["status"],
            encode_text_blob(m["body"]),
        ),
    ),
    "quotesanswer": (
        "INSERT INTO rest_quotes_raw(ts_recv,status,body) VALUES(?,?,?)",
        lambda m: (m["ts_recv"], m["status"], encode_text_blob(m["body"])),
    ),
    "markets": (
        "INSERT INTO stream_markets_raw(ts_recv,date,status,native_json) VALUES(?,?,?,?)",
        lambda m: (m["ts_recv"], m["date"], m["status"], json.dumps(m["answer"])),
    ),
    "watchlist": (
        "INSERT INTO stream_watchlist(ts_recv,symbol,op,tickers_json,status,native_json) "
        "VALUES(?,?,?,?,?,?)",
        lambda m: (
            m["ts_recv"],
            m["ticker"],
            m["op"],
            json.dumps(m["tickers"]),
            m["status"],
            json.dumps(m["answer"]),
        ),
    ),
    "sub": (
        "INSERT INTO stream_subscriptions(ts,service,command,symbols_json,code,reason) "
        "VALUES(?,?,?,?,?,?)",
        lambda m: (
            m["ts"],
            m["service"],
            m["command"],
            json.dumps(m["symbols"]),
            m["code"],
            m["reason"],
        ),
    ),
}


#: a chain capture's topic kind and its table: the sweep's capture of a capture window, one row
#: per expiry (store_capture)
CAPTURE, CAPTURE_TABLE = "capture", "complete_chain_captures"
#: what became of a capture handed to the writer (store_capture): committed with at least one
#: row; refused (kept as sent in stream_write_failures, nothing to store, lost, or not recorded:
#: the writer dead or stopped); held, not committed in the wait (the database refuses writes) and
#: written once it takes them
CAPTURE_STORED, CAPTURE_REFUSED, CAPTURE_HELD = "stored", "refused", "held"


@dataclass(frozen=True, eq=False)
class StoredFirst:
    """A message of a kind stored first (a capture, a price's crosses), handed to the writer.

    The writer's thread tells it once the batch that holds it is committed (CaptureWriter
    _committed), or once it never will be: lost (_spill) or not recorded (_unrecorded), a dead
    writer at once; any thread reads it (`outcome`), so one its wait did not see committed is
    told all the same, and one that is not held is never left held.
    """

    done: threading.Event = field(default_factory=threading.Event)
    #: what became of it once committed: its row record, its kept failure, or None (one item)
    out: list[Outcome] = field(default_factory=list[Outcome])

    def told(self, out: Outcome) -> None:
        """Set what became of it (the writer, holding its lock)."""
        self.out.append(out)
        self.done.set()

    def outcome(self, wait_sec: float = 0.0) -> str:
        """Return CAPTURE_STORED or CAPTURE_REFUSED once committed; CAPTURE_HELD until then.

        It waits up to `wait_sec` for the commit. Stored: at least one of its rows written;
        refused: none (kept as sent in stream_write_failures, nothing to store, or lost or not
        recorded, counted so); held: the writer holds it, in memory or a spill file, and writes
        it once the database takes writes.
        """
        if not self.done.wait(wait_sec):
            return CAPTURE_HELD
        out = self.out[0]
        stored = isinstance(out, RowWritten) and bool(out.values[2])
        return CAPTURE_STORED if stored else CAPTURE_REFUSED


def _capture_written(conn: sqlite3.Connection, msg: Any) -> RowWritten:
    """Write a capture message's rows; its row record: (ticker, capture time, rows written)."""
    return RowWritten(
        CAPTURE_TABLE, (msg["ticker"], msg["ts_utc"], store_capture_message(conn, msg))
    )


#: a price's level crosses and their table: one row per cross (store_crosses)
CROSS, CROSS_TABLE = "cross", "level_crosses"
#: a cross's columns, in its row's order; its cross_id is the database's
CROSS_COLUMNS = (
    "ticker",
    "ts_utc",
    "ts_et",
    "level_name",
    "level_value",
    "direction",
    "spot_at_cross",
    "zone_before",
    "zone_after",
    "timeframe",
)
_CROSS_INSERT = (
    f"INSERT INTO {CROSS_TABLE}({','.join(CROSS_COLUMNS)}) "
    f"VALUES({','.join('?' for _ in CROSS_COLUMNS)}) RETURNING cross_id"
)


def _crosses_written(conn: sqlite3.Connection, msg: Any) -> RowWritten:
    """Write a price's crosses (`crosses`, each a row of CROSS_COLUMNS) in `conn`'s transaction.

    Every row is written or none: a row the database refuses rolls back the price's rows and
    raises. Its row record: (ticker, time, each row's cross_id).
    """
    conn.execute("SAVEPOINT crosses")
    try:
        ids = tuple(
            conn.execute(_CROSS_INSERT, [c[k] for k in CROSS_COLUMNS]).fetchone()[0]
            for c in msg["crosses"]
        )
    except BaseException:
        conn.execute("ROLLBACK TO crosses")
        raise
    finally:
        conn.execute("RELEASE crosses")
    return RowWritten(CROSS_TABLE, (msg["ticker"], msg["ts_utc"], ids))


def cross_ids(stored: StoredFirst) -> tuple[int, ...]:
    """Return each row's cross_id of a price's crosses the writer stored (_crosses_written).

    () until it is told, or when refused (StoredFirst.outcome).
    """
    out = stored.out[0] if stored.outcome() == CAPTURE_STORED else None
    return out.values[2] if isinstance(out, RowWritten) else ()


#: the kinds stored first, each message written as its several rows, all or none (_stored_first)
_STORED_FIRST = {CAPTURE: _capture_written, CROSS: _crosses_written}


#: Topics stored as Schwab's item verbatim: a message without that item is not a row.
_VERBATIM = {"book", "optquote", "news"}


def _json(v: dict[str, Any] | None) -> str | None:
    return json.dumps(v) if v is not None else None


#: what one message's row can raise while it is built and written: the row refused by the
#: database (a constraint, a value it cannot bind or store) or a message without the shape its
#: table needs. Each belongs to that message alone: it is kept as sent and the writer goes on.
ROW_FAILURES = (
    sqlite3.IntegrityError,
    sqlite3.DataError,
    sqlite3.InterfaceError,
    sqlite3.ProgrammingError,
    sqlite3.NotSupportedError,
    KeyError,
    TypeError,
    ValueError,
    AttributeError,
    OverflowError,
)
#: an error from the database while writing (opening, a row, a commit); a row's error is the
#: database refusing every write when its SQLite code is one of REFUSAL_CODES, else that row's own
DATABASE_REFUSALS = (sqlite3.DatabaseError,)
#: SQLite's primary result codes for a database that takes no write now: SQLITE_PERM, BUSY,
#: LOCKED, NOMEM, READONLY, IOERR, CORRUPT, FULL, CANTOPEN, PROTOCOL, NOTADB
#: (https://www.sqlite.org/rescode.html). The writer holds the messages and tries again.
REFUSAL_CODES = frozenset({3, 5, 6, 7, 8, 10, 11, 13, 14, 15, 26})


def _refuses_every_write(error: sqlite3.DatabaseError) -> bool:
    # an error Python's sqlite3 raises itself carries no code attribute: no row of its own
    return not hasattr(error, "sqlite_errorcode") or error.sqlite_errorcode & 0xFF in REFUSAL_CODES


def _its_own(error: Exception) -> bool:
    """Whether `error`, from one row or statement, is that one's alone (else every write's)."""
    return isinstance(error, ROW_FAILURES) or (
        isinstance(error, sqlite3.DatabaseError) and not _refuses_every_write(error)
    )


#: the writer's states, on the heartbeat
WRITER_NOT_STARTED, WRITER_RECORDING, WRITER_BLOCKED, WRITER_DEAD, WRITER_STOPPED = (
    "not_started",
    "recording",
    "blocked",
    "dead",
    "stopped",
)
_STATE_WORD = {
    WRITER_NOT_STARTED: "NOT STARTED",
    WRITER_RECORDING: "RECORDING",
    WRITER_BLOCKED: "BLOCKED",
    WRITER_DEAD: "DEAD",
    WRITER_STOPPED: "STOPPED",
}
#: each table's name and columns, from its insert
_TABLES = {
    kind: (name, tuple(c.strip() for c in columns.split(",")))
    for kind, (sql, _row) in _INSERTS.items()
    for name, _, columns in [sql.removeprefix("INSERT INTO ").partition(")")[0].partition("(")]
}
#: what the writer holds in memory while the database refuses writes, before newer messages go to
#: a spill file (the operator's setting: about 2 GB of memory), each held message counted once at
#: its memory size (_held_size)
HOLD_CAP_BYTES = 2 * 1024**3
#: spill records written back in one transaction
SPILL_CHUNK = 5000
#: the tables the daily keep (CaptureWriter.prune) removes old rows from, each by its receipt time:
#: what Schwab sends again on request (price history), every chain round's answers, and the
#: daemon's own operational record. Schwab's quotes, books, option quotes, bars, news, market
#: hours and the watchlist are kept (the keep table in ACTIVE_PROGRAM.md STORE-ENOUGH)
KEPT_BY_TIME = (
    ("stream_pricehistory_raw", "ts_recv"),
    ("rest_chains_raw", "ts_recv"),
    ("rest_quotes_raw", "ts_recv"),
    ("stream_subscriptions", "ts"),
    ("stream_feed_status", "ts"),
    ("stream_write_failures", "ts"),
)
#: rows removed in one transaction, so a live write never waits behind a long delete
PRUNE_ROWS = 20000
#: how long after Schwab's regular open, and before its regular close, the order books are kept
#: (the operator's setting, ACTIVE_PROGRAM.md STORE-ENOUGH)
BOOK_OPEN_WINDOW = timedelta(minutes=30)
BOOK_CLOSE_WINDOW = timedelta(minutes=30)


def _whole_day(_ts: float) -> bool:
    return True


def _book_kept(ts: float) -> bool:
    """Whether a book received at `ts` is kept: in its day's pre-market or open, or its close.

    By that day's session as Schwab's /markets answered it (time_et.sessions; AGENTS.md rule 8):
    every book before the regular open plus BOOK_OPEN_WINDOW, and the last BOOK_CLOSE_WINDOW of
    the regular session. A day whose session is not held, or with no regular session, keeps
    every book: its hours are unknown, never guessed.
    """
    at = datetime.fromtimestamp(ts, ET)
    held = time_et.sessions()
    day = at.date().isoformat()
    if day not in held or not held[day].regular:
        return True
    opened, closed = held[day].regular[0][0], held[day].regular[-1][1]
    return at < opened + BOOK_OPEN_WINDOW or closed - BOOK_CLOSE_WINDOW <= at < closed


#: the tables whose rows received before the newest five sessions move into stream_archive, each
#: with whether a row received at a time is kept (a row not kept goes)
ARCHIVED: dict[str, Callable[[float], bool]] = {
    "stream_quotes_raw": _whole_day,
    "stream_options_quotes_raw": _whole_day,
    "stream_bars_raw": _whole_day,
    "stream_news_raw": _whole_day,
    "stream_book_raw": _book_kept,
}
#: rows taken into one archive block, in one transaction (a book block is about 13 MB before
#: compression, a fraction of a second's work between rounds of live writes)
ARCHIVE_ROWS = 5000
#: the next rows the keep moves from a table: those received before its time, oldest first, read
#: through the table's receipt-time index (RECEIPT_TIME_INDEXES), so a part reads only the rows it
#: takes, never the whole table
ARCHIVE_TAKE = "SELECT rowid, * FROM {table} WHERE {column} < ? ORDER BY {column}, rowid LIMIT ?"


def archive_block(rows: list[tuple[Any, ...]]) -> bytes:
    """Rows as one archive block: a JSON list per row, one per line, gzip-compressed (lossless)."""
    return encode_text_blob("\n".join(json.dumps(list(r)) for r in rows))


def archived_rows(conn: sqlite3.Connection, source: str) -> list[tuple[Any, ...]]:
    """Every archived row of table `source`, in the order received, as its columns held it."""
    out: list[tuple[Any, ...]] = []
    for (body,) in conn.execute(
        "SELECT body FROM stream_archive WHERE source = ? ORDER BY first_ts, rowid", (source,)
    ):
        out.extend(tuple(json.loads(line)) for line in decode_text_blob(body).split("\n"))
    return out


def _every_message(_topic: str, _msg: Any) -> bool:
    """Save every message: the writer's rule when no one has set one (CaptureWriter.saves)."""
    return True


@dataclass(frozen=True)
class RowWritten:
    """A message's row written to its table, with the values bound."""

    table: str
    values: tuple[Any, ...]


@dataclass(frozen=True)
class KeptFailure:
    """A message kept as sent in stream_write_failures.

    Its topic, the message, the error (type and text) and when the write failed.
    """

    topic: str
    msg: Any
    error: str
    ts: float


class SpillStatus(TypedDict):
    """A spill file as the heartbeat carries it (_Spill.status).

    Its path, bytes, messages and how many are written back.
    """

    path: str
    bytes: int
    messages: int
    written_back: int


class _WriterCounts(TypedDict):
    """The writer's state and counts, counted at commit, from which its Record is made.

    `failures`: messages kept in stream_write_failures; `held`: messages in memory not yet in
    the database (queued, taken in the round being written, in the open batch or waiting);
    `waiting`: those the writer took from the queue to write again while the database refuses
    writes (each try takes every queued one; those arriving during the pause between tries stay
    queued until the next), `held_bytes` the memory they take, each counted once when held
    (_held_size; the cap's measure); `spill`: the spill file being written back (its path,
    bytes, messages and how many are written back), None when there is none;
    `spills_after`: the spill files after it, in order, the last taking new messages;
    `left_on_disk`: spill files a stop or the writer's death left for the next writer,
    with how many records are written back; `lost`: messages neither the
    database nor the spill file took, received from `lost_first_ts` to `lost_last_ts`;
    `unrecorded`: messages a dead writer could not write; `error`: the database's refusal
    (blocked) or what ended the thread (dead), from `error_ct`.
    """

    state: str
    rows_written: int
    failures: int
    last_failure: str | None
    last_failure_ct: str | None
    queue_depth: int
    waiting: int
    held: int
    held_bytes: int
    spill: SpillStatus | None
    spills_after: list[SpillStatus]
    left_on_disk: list[SpillStatus]
    lost: int
    lost_first_ts: float | None
    lost_last_ts: float | None
    unrecorded: int
    error: str | None
    error_ct: str | None


class WriterStatus(_WriterCounts):
    """The writer as the heartbeat carries it (CaptureWriter.status): its counts and its Record.

    `word`, `line` and `cls`: the header's Record, as the page prints it: its cell's one word,
    the whole line (the cell's title, and the header's alert while the class is "neg") and its
    class.
    """

    word: str
    line: str
    cls: str


def _record_line(s: Mapping[str, Any]) -> tuple[str, str, str]:
    """Return the header's Record for a writer status: its word, the line, and its class.

    The line begins with the word. The class is "neg" for anything but recording with nothing
    kept, spilled, lost or left.
    """
    spill = s["spill"]
    if spill is None:
        word = _STATE_WORD[s["state"]]
    elif s["state"] == WRITER_BLOCKED:
        word = "BLOCKED, SPILLING TO DISK"
    else:
        word = "WRITING BACK THE SPILL"
    parts = [word]
    if s["error"] is not None:
        parts.append(
            f"{'since' if s['state'] == WRITER_BLOCKED else 'at'} {s['error_ct']}: {s['error']}"
        )
    parts += [f"{s['rows_written']} rows", f"{s['failures']} failed, kept as sent"]
    if s["last_failure"] is not None:
        parts.append(f"last {s['last_failure_ct']}: {s['last_failure']}")
    parts.append(
        f"held in memory: {s['held']} messages, {s['held_bytes'] / 1e6:.1f} MB "
        f"({s['waiting']} waiting for the database)"
    )
    if spill is not None:
        parts += [
            f"spilled to disk: {f['messages']} messages, {f['bytes']:,} bytes in "
            f"{Path(f['path']).name}, {f['written_back']} written back"
            for f in [spill, *s["spills_after"]]
        ]
    parts += [
        f"left on disk: {Path(k['path']).name} ({k['messages']} messages, "
        f"{k['bytes']:,} bytes, {k['written_back']} written back)"
        for k in s["left_on_disk"]
    ]
    if s["lost"]:
        lost = f"LOST {s['lost']} messages"
        if s["lost_first_ts"] is not None:  # the window of those whose receipt time is known
            lost += f", received {ct_label(s['lost_first_ts'])} to {ct_label(s['lost_last_ts'])}"
        parts.append(lost)
    parts.append(f"{s['unrecorded']} not recorded")
    ok = (
        s["state"] == WRITER_RECORDING
        and s["failures"] == 0
        and s["unrecorded"] == 0
        and spill is None
        and not s["left_on_disk"]
        and s["lost"] == 0
    )
    return word, " · ".join(parts), "" if ok else "neg"


def _object_bytes(obj: object, seen: set[int]) -> int:
    """Memory of `obj` and everything it holds that is its own.

    Each object once (`seen`), not None, True, False, CPython's cached small ints and
    one-character strings.
    """
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
            held = cast(dict[object, object], o)
            stack.extend(held.keys())
            stack.extend(held.values())
        elif type(o) is list or type(o) is tuple:
            stack.extend(cast(list[object] | tuple[object, ...], o))
    return total


def _held_size(item: Item) -> int:
    """Return the memory a held message takes.

    The (topic, message) pair, its topic, the message dict and every value it carries (Schwab's
    item decoded from the wire, its fields). The message's keys and its `src` are the writer's
    code constants, shared by every message, and not counted. Measured against tracemalloc on
    production's stream mix decoded from JSON:
    tests/test_data_path_writer_failures_v1.py::test_the_hold_cap_holds_memory_to_its_size.
    """
    seen: set[int] = set()
    if isinstance(item, KeptFailure):
        return sys.getsizeof(item) + sum(
            _object_bytes(v, seen) for v in (item.topic, item.msg, item.error)
        )
    topic, msg = item
    total = sys.getsizeof(item) + _object_bytes(topic, seen)
    if not isinstance(msg, dict):
        return total + _object_bytes(msg, seen)
    total += sys.getsizeof(msg)
    for key, value in msg.items():
        if key != "src":
            total += _object_bytes(value, seen)
    return total


def _received(item: Item) -> float | None:
    """When the daemon received a message.

    Its `ts_recv` (`ts` for a status or a subscription answer; a kept failure's time).
    """
    if isinstance(item, KeptFailure):
        return item.ts
    msg = item[1]
    if not isinstance(msg, dict):
        return None
    return msg["ts_recv"] if msg.get("ts_recv") is not None else msg.get("ts")


def _spill_record(item: Item) -> bytes:
    """Return a held message as one spill record's JSON.

    The topic and the message as sent (a kept failure with its error and time).
    """
    if isinstance(item, KeptFailure):
        rec = {"kept": {"topic": item.topic, "msg": item.msg, "error": item.error, "ts": item.ts}}
    else:
        rec = {"topic": item[0], "msg": item[1]}
    return json.dumps(rec, default=repr, separators=(",", ":")).encode("utf-8")


def _from_spill(raw: bytes) -> Item:
    rec = json.loads(raw)
    if "kept" in rec:
        return KeptFailure(**rec["kept"])
    return rec["topic"], rec["msg"]


def _spill_order(path: Path) -> tuple[int, ...]:
    """Return a spill file's place in arrival order, from its name (<stem>.<ms>.<n>.spill)."""
    return tuple(int(part) for part in path.name.split(".")[1:-1])


class _Spill:
    """One append-only spill file: each record a 4-byte big-endian length and the record's JSON.

    Appended in arrival order (_NewSpill); written back from the start, `read_at` advancing at
    each commit. One an earlier writer left (found) is read only.
    """

    def __init__(self, path: Path) -> None:
        self.path = path
        self.size = 0  # bytes of whole records written
        self.messages = 0
        self.read_at = 0  # bytes written back and committed
        self.written_back = 0
        self._in: IO[bytes] | None = None

    def read(self, n: int, now: float) -> list[tuple[Item, int]]:
        """Up to `n` records from `read_at`: (message, end offset) each, read at `now`.

        A record that does not decode (a damaged file) is its bytes as a KeptFailure with where
        and why, kept as sent in stream_write_failures; its length still places the next
        record. A length that runs past the file's whole records (a damaged length) places
        nothing: every byte from it to the end is one KeptFailure (_unframed).
        """
        if self._in is None:
            self._in = open(self.path, "rb")
        self._in.seek(self.read_at)
        out: list[tuple[Item, int]]
        out, at = [], self.read_at
        while len(out) < n and at < self.size:
            length = int.from_bytes(self._in.read(4), "big")
            if at + 4 + length > self.size:
                self._in.seek(at)
                out.append((self._unframed(at, self._in.read(self.size - at), now), self.size))
                break
            raw = self._in.read(length)
            try:
                item = _from_spill(raw)
            except (ValueError, KeyError, TypeError) as e:
                item = KeptFailure(
                    "spill",
                    raw.decode("latin-1"),
                    f"{self.path.name}: the record at byte {at} "
                    f"does not decode, kept as its bytes (latin-1): {type(e).__name__}: {e}",
                    now,
                )
            at += 4 + length
            out.append((item, at))
        return out

    def _unframed(self, at: int, raw: bytes, now: float) -> KeptFailure:
        """Bytes from `at` that make no whole record, as one KeptFailure.

        A damaged length, or a crash cut a record off: kept as sent, never cut away unrecorded.
        """
        return KeptFailure(
            "spill",
            raw.decode("latin-1"),
            f"{self.path.name}: the {len(raw)} bytes from byte "
            f"{at} make no whole record, kept as their bytes (latin-1)",
            now,
        )

    def committed(self, records: int, end: int) -> None:
        """Record that a written-back part of `records` records is in the database.

        The next starts at `end`.
        """
        self.written_back += records
        self.read_at = end

    @classmethod
    def found(cls, path: Path, written_back: int) -> _Spill:
        """Open a spill file an earlier writer left beside the database, to be written back.

        Written back from after the `written_back` records its stream_spill_progress row counts
        as committed (no row: none of it was; a count past its whole records: all of them).
        Bytes after its last whole record (a crash cut a record off, or a damaged length) are its
        last message, kept as sent when the write-back reaches them (read). It is read only:
        nothing is appended to it, so no new message lands behind bytes that frame nothing (new
        ones go to a new spill file).
        """
        spill = cls(path)
        disk, whole = path.stat().st_size, 0
        with open(path, "rb") as f:
            while whole + 4 <= disk:
                f.seek(whole)
                end = whole + 4 + int.from_bytes(f.read(4), "big")
                if end > disk:
                    break
                whole, spill.messages = end, spill.messages + 1
                if spill.messages <= written_back:
                    spill.read_at = end
        spill.messages += whole < disk
        spill.size, spill.written_back = disk, min(written_back, spill.messages)
        if spill.written_back == spill.messages:  # its cut bytes, if any, were kept too
            spill.read_at = disk
        return spill

    def status(self) -> SpillStatus:
        """Return the spill file as the heartbeat carries it, and as listed when left on disk."""
        return {
            "path": str(self.path),
            "bytes": self.size,
            "messages": self.messages,
            "written_back": self.written_back,
        }

    def close(self) -> None:
        if self._in is not None:
            self._in.close()


class _NewSpill(_Spill):
    """A spill file this writer created: new messages are appended to it, unbuffered."""

    def __init__(self, path: Path) -> None:
        super().__init__(path)
        self.out = open(path, "xb", buffering=0)

    @classmethod
    def new(cls, db_path: Path, ms: int, n: int) -> _NewSpill:
        """Create a new spill file beside the database, <stem>.<ms>.<n>.spill.

        It is named for its place in arrival order: created, never opened over another file (a
        name taken moves it to the next millisecond). Raises the disk's refusal.
        """
        while True:
            try:
                return cls(db_path.with_name(f"{db_path.stem}.{ms}.{n}.spill"))
            except FileExistsError:
                ms += 1

    def append(self, record: bytes) -> None:
        """Append one record; the disk's refusal (OSError) is raised.

        A refused record is cut away first, so the file holds only whole records. The file is
        unbuffered, so a write may take part of the bytes; the rest is written next,
        as Python's buffered writer does, and a disk that takes no more raises.
        """
        data = len(record).to_bytes(4, "big") + record
        left = memoryview(data)
        try:
            while left:
                left = left[self.out.write(left) :]
        except OSError:
            self.out.truncate(self.size)  # no partial record stays behind the whole ones
            raise
        self.size += len(data)  # its message is counted by the writer (_spill)

    @override
    def close(self) -> None:
        self.out.close()
        super().close()


@dataclass
class _Keep:
    """The daily keep in progress (CaptureWriter.prune).

    Rows received before `before` leave each table still in `tables`, a part at a time;
    `removed` counts them per table.
    """

    before: float
    tables: list[tuple[str, str]]
    removed: Counter[str] = field(default_factory=Counter[str])


def _prepared(p: Path) -> list[_Spill]:
    """Prepare the database at `p` for the writer, and return the spill files found beside it.

    WAL, its size limit, the tables (the chain history's captures among them) and the receipt
    time indexes of tables new here. Spill files an earlier writer left beside the database
    (named in the order they began) hold the oldest messages there are: the writer thread writes
    them back first, each from after its committed parts, and deletes one whose every record is
    committed (ended between its last part and its deletion) without writing it again; new
    messages go after the newest. They are returned oldest first. No message is written here: a
    database that refuses writes at the start never stops the daemon starting.
    """
    conn = sqlite3.connect(str(p))
    try:
        conn.executescript("PRAGMA journal_mode=WAL; PRAGMA synchronous=NORMAL;")
        conn.execute(f"PRAGMA journal_size_limit={WAL_SIZE_LIMIT_BYTES}")
        tables = {
            name for (name,) in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        conn.executescript(STREAM_SCHEMA_SQL)
        ensure_schema(conn)  # the chain history's captures (store_capture)
        for table, index in RECEIPT_TIME_INDEXES.items():
            if table not in tables:
                conn.execute(index)
        conn.commit()
        progress = dict(conn.execute("SELECT spill, written_back FROM stream_spill_progress"))
        return [
            _Spill.found(f, progress[f.name] if f.name in progress else 0)
            for f in sorted(p.parent.glob(f"{p.stem}.*.spill"), key=_spill_order)
        ]
    finally:
        conn.close()


class CaptureWriter:
    """Writes every bus message to the one database from its own thread, in batches.

    Each round writes up to `batch_rows` queued messages, and commits once the batch has
    `batch_rows` rows or `batch_sec` has passed. A message
    whose row is refused is kept as sent in stream_write_failures, in the same batch, and so is a
    statement of the writer's own (a keep part, a spill's progress row) that fails for its own
    reason. While the
    database refuses every write (DATABASE_REFUSALS, each wait `timeout_sec`), the open batch
    is rolled back and its messages, and every one after, are held in order and written again,
    on a new connection, every `retry_sec` plus up to `batch_sec` (state blocked, with the
    refusal; each try also waits up to `timeout_sec` on a locked database). Held messages stay
    in memory up to `hold_cap_bytes`; every newer one goes to a spill file beside the database,
    in order. When the database takes writes again, memory is written first, then the spill files,
    oldest first, then what arrived meanwhile (the newest spill takes it, behind the rest); each
    part of a spill is committed with how far its write-back got, and the file is deleted once all
    of it is in. Spill files found beside the database at start are written back first, each from
    after its committed parts. A message the spill file cannot take (a full disk) is lost:
    counted, with when it was received. Only an error outside these ends the thread (dead): what
    it held in memory and what reaches it after are counted unrecorded.
    """

    def __init__(
        self,
        db_path: Path | str | None = None,
        *,
        batch_rows: int = 500,
        batch_sec: float = 0.25,
        timeout_sec: float = 30.0,
        retry_sec: float = 1.0,
        hold_cap_bytes: int = HOLD_CAP_BYTES,
        clock: Callable[[], float] = time_et.now,
    ) -> None:
        p = resolve_stream_db_path(db_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        self.db_path = p
        self.batch_rows = int(batch_rows)
        self.batch_sec = float(batch_sec)
        self.timeout_sec = float(timeout_sec)
        self.retry_sec = float(retry_sec)
        self.hold_cap_bytes = int(hold_cap_bytes)
        #: the time of day a failure, a block and a spill file are stamped with (time_et.now)
        self.clock = clock
        self._lock = threading.Lock()
        self._q: queue.SimpleQueue[Item | None] = queue.SimpleQueue()  # None: the stop
        self._batch: list[tuple[Item, Outcome]] = []  # (message, outcome) in the open transaction
        self._batch_spilled = False  # the open batch is spill records (they stay in the file)
        self._waiting: list[Item] = []  # messages held while the database refuses writes
        self._waiting_bytes = 0
        self.lost = 0
        self.lost_first_ts: float | None = None
        self.lost_last_ts: float | None = None
        self._round: list[Item] = []  # the messages the writer is writing now, in order
        self._stored = 0  # how many of them are in the open batch
        self._admitting: list[Item] = []  # the messages _admit or the stop's spill is holding now
        self._admitted = 0  # how many of them are held (in memory, on disk or lost)
        #: log line kind -> [minute last logged, count since]
        self._logged: dict[tuple[str, str], tuple[int, int]] = {}  # kind -> (minute, more since)
        self.state = WRITER_NOT_STARTED
        self.rows_written = 0
        self.failures = 0
        self.last_failure: str | None = None
        self.last_failure_ts: float | None = None
        self.unrecorded = 0
        #: (kind, ticker, ts_utc) -> told when that message's batch is committed, with its outcome
        #: (_stored_first: a capture or a price's crosses)
        self._waiters: dict[tuple[str, str, float], StoredFirst] = {}
        self.error: str | None = None
        self.error_ts: float | None = None
        self.left_on_disk: list[SpillStatus] = []
        #: which bus messages are recorded (topic, message) -> bool; the daemon sets its own
        #: (Daemon.saves: option quotes and option books of the contracts it keeps)
        self.saves: Callable[[str, Any], bool] = _every_message
        self._keeping: _Keep | None = None  # the daily keep in progress (prune)
        #: spill files, oldest first: the first is written back, new messages go to the last
        self._spills = _prepared(p)

    def insert(
        self, topic: str, msg: Payload, *, conn: sqlite3.Connection | None = None
    ) -> Outcome:
        """One bus message -> one row.

        Its RowWritten, the KeptFailure when its row is refused, or None (a topic without a
        table, or nothing Schwab sent to keep). A DATABASE_REFUSALS error is raised. Without
        `conn` (a test, a recovery tool) it opens, writes, commits and counts a connection of its
        own.
        """
        kind = topic.split(".", 1)[0]
        spec = _INSERTS.get(kind)
        if spec is None and kind not in _STORED_FIRST:
            return None
        if isinstance(msg, dict) and kind in _VERBATIM and msg.get("content") is None:
            return None
        if conn is None:
            own = sqlite3.connect(str(self.db_path), timeout=self.timeout_sec)
            try:
                with own:  # commits, or rolls back on an error
                    out = self.insert(topic, msg, conn=own)
            finally:
                own.close()
            with self._lock:
                self._committed([((topic, msg), out)])
            return out
        try:
            if spec is None:  # a capture or a price's crosses: its rows, all or none
                return _STORED_FIRST[kind](conn, msg)
            values = spec[1](msg)
            conn.execute(spec[0], values)
        except (*ROW_FAILURES, *DATABASE_REFUSALS) as e:
            if not _its_own(e):
                raise
            return self._kept_row(conn, topic, msg, e)
        return RowWritten(_TABLES[kind][0], values)

    def _kept_row(
        self, conn: sqlite3.Connection, topic: str, msg: Any, error: BaseException
    ) -> KeptFailure:
        reason = f"{type(error).__name__}: {error}"
        self._log_once_a_minute(
            ("row", reason),
            "stream writer: %s not stored as a row, kept as sent: %s",
            topic,
            reason,
        )
        return self._keep(conn, KeptFailure(topic, msg, reason, self.clock()))

    def _own_failure(
        self, conn: sqlite3.Connection, error: Exception, topic: str, msg: dict[str, Any]
    ) -> None:
        """Keep `msg`, a statement of the writer's own that failed for its own reason, as sent.

        Committed with what the open transaction holds and counted, so the writer goes on (a
        refusal of every write is the caller's to raise: the writer holds what it has and tries
        again).
        """
        kept = self._kept_row(conn, topic, msg, error)
        conn.commit()
        with self._lock:
            self._committed([(kept, kept)])

    def _log_once_a_minute(self, key: tuple[str, str], fmt: str, *args: object) -> None:
        """One log line per kind a minute, with how many came since the last line."""
        minute = int(self.clock() // 60)
        with self._lock:
            last, since = self._logged.get(key, (None, 0))
            if last == minute:
                self._logged[key] = (minute, since + 1)
                return
            self._logged[key] = (minute, 0)
        log.warning(fmt + " (%d more since the last line)", *args, since)

    def keep_failure(self, topic: str, msg: Any, error: BaseException, now: float) -> None:
        """Keep `msg`, which another thread could not store, as sent.

        Another thread: a chain whose history write failed. While the writer thread runs it
        takes it in turn, the one writer; a writer whose thread is not running (not started, or
        stopped) writes it here, on a connection of its own.
        """
        kept = KeptFailure(topic, msg, f"{type(error).__name__}: {error}", now)
        with self._lock:
            standalone = self.state in (WRITER_NOT_STARTED, WRITER_STOPPED)
            if self.state == WRITER_DEAD:
                self.unrecorded += 1
            elif not standalone:
                self._q.put(kept)
        if standalone:
            self._write_alone(kept)

    def _write_alone(self, item: Item) -> None:
        """Write `item` on a connection of its own: the writer's thread is not running."""
        own = sqlite3.connect(str(self.db_path), timeout=self.timeout_sec)
        try:
            with own:  # commits, or rolls back on an error
                out = self._store(own, item)
        finally:
            own.close()
        with self._lock:
            self._committed([(item, out)])

    def store_capture(self, msg: dict[str, Any]) -> StoredFirst:
        """Write a chain capture (capture_message); its StoredFirst is told once it is committed.

        Another thread: the chain sweep, which waits on it before it tells the console of the
        chain (store first), and keeps one its wait did not see committed until it is told
        (chain_sweep.ChainSweep.publish_held).
        """
        return self._stored_first(CAPTURE, msg)

    def store_crosses(self, msg: dict[str, Any]) -> StoredFirst:
        """Write a price's level crosses; its StoredFirst is told once they are committed.

        `msg` is {"ticker", "ts_utc", "crosses": [a row of CROSS_COLUMNS, ...]}. Another thread:
        the console's pricing thread, which waits on it and holds the crosses only once they are
        stored (store first), each with its cross_id (cross_ids), and keeps those its wait did
        not see committed until it is told (server._hold_answered_crosses).
        """
        return self._stored_first(CROSS, msg)

    def _stored_first(self, kind: str, msg: dict[str, Any]) -> StoredFirst:
        """Write `msg`, a message of a kind stored first; its StoredFirst is told at its commit.

        A dead writer tells it at once, nothing written (counted unrecorded); a writer whose
        thread is not running writes it here, on a connection of its own.
        """
        item = (f"{kind}.{msg['ticker']}", msg)
        stored = StoredFirst()
        with self._lock:
            standalone = self.state in (WRITER_NOT_STARTED, WRITER_STOPPED)
            if self.state == WRITER_DEAD:
                self.unrecorded += 1
                stored.told(None)
                return stored
            self._waiters[(kind, msg["ticker"], msg["ts_utc"])] = stored
            if not standalone:
                self._q.put(item)
        if standalone:
            self._write_alone(item)
        return stored

    def _keep(self, conn: sqlite3.Connection, kept: KeptFailure) -> KeptFailure:
        """One stream_write_failures row.

        The message as JSON (Python's repr when it is not JSON).
        """
        try:
            sent = json.dumps(kept.msg, default=repr)
        except (ValueError, TypeError, RecursionError) as e:
            log.warning("stream writer: %s is not JSON (%s), kept as its repr", kept.topic, e)
            sent = repr(kept.msg)
        conn.execute(
            "INSERT INTO stream_write_failures(ts,topic,msg_json,error) VALUES(?,?,?,?)",
            (kept.ts, kept.topic, sent, kept.error),
        )
        return kept

    def _committed(self, batch: list[tuple[Item, Outcome]]) -> None:
        """Count a batch that is in the database: its rows and kept failures; the writer records.

        The caller holds the lock, so a batch is counted written and stops being held at one time.
        """
        for item, out in batch:
            if isinstance(out, RowWritten):
                self.rows_written += 1
            elif isinstance(out, KeptFailure):
                self.failures += 1
                self.last_failure, self.last_failure_ts = f"{out.topic}: {out.error}", out.ts
            self._tell(item, out)
        if self.state == WRITER_BLOCKED:
            self.state, self.error, self.error_ts = WRITER_RECORDING, None, None

    def _unrecorded(self, items: list[Item]) -> None:
        """Count `items` not recorded: neither the database nor a spill file will hold them.

        The caller holds the lock.
        """
        self.unrecorded += len(items)
        for item in items:
            self._tell(item, None)

    def _tell(self, item: Item, out: Outcome) -> None:
        """Tell a message stored first (_stored_first) what became of it; the caller holds the lock.

        `out` is its row record or kept failure once committed, or None once it never will be
        (lost, or not recorded): its waiter reads it refused (StoredFirst.outcome).
        """
        if (
            isinstance(item, tuple)
            and (kind := item[0].split(".", 1)[0]) in _STORED_FIRST
            and isinstance(msg := item[1], dict)
        ):
            waiter = self._waiters.pop((kind, msg["ticker"], msg["ts_utc"]), None)
            if waiter is not None:
                waiter.told(out)

    def status(self) -> WriterStatus:
        """Return the writer's WriterStatus, as the heartbeat carries it."""
        with self._lock:
            s: _WriterCounts = {
                "state": self.state,
                "rows_written": self.rows_written,
                "failures": self.failures,
                "last_failure": self.last_failure,
                "last_failure_ct": (
                    ct_label(self.last_failure_ts) if self.last_failure_ts is not None else None
                ),
                "queue_depth": self._q.qsize(),
                "waiting": len(self._waiting),
                # the open batch and the round's messages not yet in it; a retry's are part of what
                # is waiting; those _admit has not yet held; spill records are on disk
                "held": self._q.qsize()
                + max(
                    len(self._waiting),
                    (0 if self._batch_spilled else len(self._batch))
                    + len(self._round)
                    - self._stored,
                )
                + len(self._admitting)
                - self._admitted,
                "held_bytes": self._waiting_bytes,
                "spill": self._spills[0].status() if self._spills else None,
                "spills_after": [s.status() for s in self._spills[1:]],
                "left_on_disk": [k.copy() for k in self.left_on_disk],
                "lost": self.lost,
                "lost_first_ts": self.lost_first_ts,
                "lost_last_ts": self.lost_last_ts,
                "unrecorded": self.unrecorded,
                "error": self.error,
                "error_ct": ct_label(self.error_ts) if self.error_ts is not None else None,
            }
        word, line, cls = _record_line(s)
        return WriterStatus(**s, word=word, line=line, cls=cls)

    async def run(self, sub: Subscription, *, stop: asyncio.Event) -> None:
        """Hand every bus message to the writer thread until `stop`.

        Each message is awaited as it comes, with no timer of its own; the stop goes into the
        same queue, behind every message delivered before it (LOG_END, _end_at), so everything
        delivered before the stop is written and committed before this returns. Once the thread
        is dead, each message is counted unrecorded instead of queued for a thread that will not
        take it.
        """
        thread = threading.Thread(
            target=self._thread, args=(self._q,), name="stream-capture-writer", daemon=True
        )
        with self._lock:
            self.state = WRITER_RECORDING
        thread.start()
        ending = asyncio.ensure_future(_end_at(stop, sub))
        try:
            while (item := await sub.get()) is not LOG_END:
                self._hand(item)
        finally:
            ending.cancel()
            with self._lock:  # a dead thread takes no stop message (the thread sets it)
                if cast(str, self.state) != WRITER_DEAD:
                    self._q.put(None)
            await asyncio.to_thread(thread.join)

    def _hand(self, item: tuple[str, Any]) -> None:
        if not self.saves(*item):
            return
        with self._lock:
            if self.state == WRITER_DEAD:
                self.unrecorded += 1
                return
            self._q.put(item)

    def _thread(self, q: queue.SimpleQueue[Item | None]) -> None:
        try:
            self._write(q)
        except Exception as e:  # recorded as the writer's death, then raised
            log.exception("stream writer died")
            with self._lock:
                self.state, self.error, self.error_ts = (
                    WRITER_DEAD,
                    f"{type(e).__name__}: {e}",
                    self.clock(),
                )
                # not recorded: the open batch, the round's messages not yet in it (the one that
                # ended the thread first; a retry's round holds its batch and what was waiting),
                # those _admit had not yet held, and the queue. A spill file's messages are on
                # disk: the file stays, listed as left
                self._unrecorded(
                    self._unwritten() + self._admitting[self._admitted :] + self._drained(q)
                )
                self._leave_spills()
                self._batch, self._waiting, self._round, self._stored = [], [], [], 0
                self._admitting, self._admitted = [], 0
                self._batch_spilled = False
            raise
        with self._lock:  # anything handed in after the stop is not written
            self.state = WRITER_STOPPED
            self._unrecorded(self._drained(q))

    def _unwritten(self) -> list[Item]:
        """Return the messages a refusal or the writer's death leaves unwritten, in order.

        The open batch's (none when it is spill records, which stay in their file), then the
        round's not yet in it.
        """
        batch = [] if self._batch_spilled else [item for item, _out in self._batch]
        return batch + self._round[self._stored :]

    @staticmethod
    def _drained(q: queue.SimpleQueue[Item | None]) -> list[Item]:
        """Empty the queue; the messages it held, in order."""
        items: list[Item] = []
        while True:
            try:
                item = q.get_nowait()
            except queue.Empty:
                return items
            if item is not None:
                items.append(item)

    def _store(self, conn: sqlite3.Connection, item: Item) -> Outcome:
        if isinstance(item, KeptFailure):
            return self._keep(conn, item)
        return self.insert(*item, conn=conn)

    def _open(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), timeout=self.timeout_sec)
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute(f"PRAGMA journal_size_limit={WAL_SIZE_LIMIT_BYTES}")
        return conn

    def _take_round(
        self, q: queue.SimpleQueue[Item | None], stopping: bool, last_commit: float
    ) -> tuple[list[Item], bool]:
        """Take one round's messages from `q`, and whether the stop is taken.

        The first is waited for until the batch is due (a moment only while a spill file or a
        prune has work); then the messages already queued are taken, up to `batch_rows` and none
        after the stop: a round is one batch at most, so a writer that is behind commits as often
        as one that is not, and what it has not taken stays queued. While messages are held
        (the database refuses writes) every queued one is taken, to be held with them.
        """
        most = None if self._waiting or self._spills else self.batch_rows
        unread = (
            bool(self._spills) and self._spills[0].read_at < self._spills[0].size
        ) or self._keeping is not None
        timeout = 0.001 if unread else max(self.batch_sec - (time_et.elapsed() - last_commit), 0.01)
        incoming: list[Item] = []
        block = True  # the first is waited for; after it, only what is already queued
        while (block or not stopping) and (most is None or len(incoming) < most):
            try:
                item = q.get(block=block, timeout=timeout)
            except queue.Empty:
                if not block:
                    break
            else:
                stopping = stopping or item is None
                incoming += [item] if item else []
            block = False
        return incoming, stopping

    def _store_round(self, conn: sqlite3.Connection) -> None:
        """Store the round's messages into the open batch, counted stored together.

        A refusal on the way leaves none of them counted: the open transaction is rolled back
        and the whole round is held (_refused).
        """
        stored = self._stored_all(conn, self._round)
        with self._lock:
            self._batch += stored
            self._stored = len(self._round)

    def _stored_all(
        self, conn: sqlite3.Connection, items: list[Item]
    ) -> list[tuple[Item, Outcome]]:
        """Store `items`, each with its outcome; each table's rows in one INSERT of many rows.

        SQLite gives up Python's interpreter lock for each statement, and the writer then waits
        to take it back from the program's busy threads, up to the switch interval
        (sys.getswitchinterval, 5 ms) each time: one statement a table, not one a row. A table's
        rows keep their order. A capture, a kept failure and a message with no row are stored
        one by one (_store). All of it in the open batch's transaction, begun here when none is
        open: a savepoint (a capture's, a price's crosses') outside a transaction begins one and
        commits it at its RELEASE (https://sqlite.org/lang_savepoint.html), and Python opens one
        only before an INSERT, UPDATE, DELETE or REPLACE.
        """
        if not conn.in_transaction:
            conn.execute("BEGIN")
        out: list[tuple[Item, Outcome]] = []
        rows: dict[str, list[tuple[str, Payload]]] = {}
        for item in items:
            if isinstance(item, tuple):
                kind, msg = item[0].split(".", 1)[0], item[1]
                if kind in _INSERTS and not (
                    isinstance(msg, dict) and kind in _VERBATIM and msg.get("content") is None
                ):
                    rows.setdefault(kind, []).append(item)
                    continue
            out.append((item, self._store(conn, item)))
        for kind, taken in rows.items():
            step = conn.getlimit(sqlite3.SQLITE_LIMIT_VARIABLE_NUMBER) // len(_TABLES[kind][1])
            for i in range(0, len(taken), step):
                out += self._many(conn, kind, taken[i : i + step])
        return out

    def _many(
        self, conn: sqlite3.Connection, kind: str, items: list[tuple[str, Payload]]
    ) -> list[tuple[Item, Outcome]]:
        """Write `kind`'s messages in one INSERT, each with its RowWritten.

        SQLite undoes a refused statement whole, so when one of them cannot be a row each is
        written by itself (insert), its own row or its own kept failure. A refusal of every
        write is raised, as insert raises it.
        """
        sql, row = _INSERTS[kind]
        head, _, one = sql.partition("VALUES")
        try:
            values = [row(msg) for _topic, msg in items]
            conn.execute(
                head + "VALUES" + ",".join([one] * len(values)), [v for r in values for v in r]
            )
        except (*ROW_FAILURES, *DATABASE_REFUSALS) as e:
            if not _its_own(e):
                raise
            return [(item, self.insert(*item, conn=conn)) for item in items]
        table = _TABLES[kind][0]
        return [(item, RowWritten(table, r)) for item, r in zip(items, values, strict=True)]

    def _write(self, q: queue.SimpleQueue[Item | None]) -> None:
        """Run the writer thread's loop.

        After a refusal the connection is closed and the next try opens a new one: a connection
        SQLite opened on a database that refused writes (a read-only file) keeps refusing after
        the database accepts them again.
        """
        conn = None
        try:
            last_commit, stopping = time_et.elapsed(), False
            while not (stopping and not self._waiting and not self._spills):
                incoming, stopping = self._take_round(q, stopping, last_commit)
                holding = bool(self._waiting) or bool(self._spills)
                with self._lock:
                    self._round, self._stored = self._waiting if holding else incoming, 0
                if holding:  # the round's messages join the held ones, in order
                    self._admit(incoming)
                del incoming  # the round is held by _round only; what was spilled, on disk only
                try:
                    if conn is None:
                        conn = self._open()
                    self._store_round(conn)
                    if self._batch and (
                        holding
                        or stopping
                        or len(self._batch) >= self.batch_rows
                        or time_et.elapsed() - last_commit >= self.batch_sec
                    ):
                        conn.commit()
                        last_commit = time_et.elapsed()
                        with self._lock:
                            self._committed(self._batch)
                            self._batch, self._waiting, self._waiting_bytes = [], [], 0
                    if self._spills and not self._waiting:
                        self._write_back(conn)
                    if (
                        (keep := self._keeping) is not None
                        and not stopping
                        and not self._spills
                        and not self._batch
                        and q.empty()
                    ):
                        # one part between rounds, none while messages wait or once the stop
                        # is taken
                        self._prune_part(conn, keep)
                except DATABASE_REFUSALS as e:
                    if conn is not None:
                        conn.close()  # its open transaction is rolled back
                    conn = None
                    self._refused(e, self._unwritten(), holding, stopping)
                with self._lock:  # a finished round's messages are not kept
                    self._round, self._stored = [], 0
        finally:
            if conn is not None:
                conn.close()

    def _refused(
        self, error: BaseException, held: list[Item], holding: bool, stopping: bool
    ) -> None:
        """Handle the database's refusal of a write.

        The open batch is rolled back and `held` (its messages and the ones not yet written, in
        order; spill records stay in their file) is written again after `retry_sec`. At the stop
        what is held is left on disk.
        """
        reason = f"{type(error).__name__}: {error}"
        self._log_once_a_minute(
            ("refused", reason),
            "stream writer: the database refused a write, %d messages held: %s",
            len(held),
            reason,
        )
        with self._lock:  # rolled back: none of the round is stored
            self._batch, self._batch_spilled, self._stored = [], False, 0
            if self.state != WRITER_BLOCKED:
                self.error_ts = self.clock()
            self.state, self.error = WRITER_BLOCKED, reason
            if not holding:  # held now: in memory up to the cap, then spilled
                self._waiting, self._waiting_bytes = [], 0
                self._admitting, self._admitted = held, 0
            self._round = (
                self._waiting
            )  # the round is what memory holds (a commit may have emptied it)
        if not holding:
            self._admit(held)
        if stopping:
            self._leave_on_disk()
            return
        time.sleep(self.retry_sec)

    def _admit(self, items: list[Item]) -> None:
        """Hold `items`, in order.

        While no spill file is open, in memory while the held bytes stay within the cap; then,
        and for every newer message, in the newest spill file. Those not yet held are counted
        held (status) and, if the writer dies, not recorded.
        """
        with self._lock:
            self._admitting, self._admitted = items, 0
        for item in items:
            if not self._spills:
                size = _held_size(item)
                if self._waiting_bytes + size <= self.hold_cap_bytes:
                    with self._lock:
                        self._waiting.append(item)
                        self._waiting_bytes += size
                        self._admitted += 1
                    continue
            try:
                held: _NewSpill | OSError = self._tail()
            except OSError as e:
                held = e
            self._spill(item, held)
        with self._lock:
            self._admitting, self._admitted = [], 0

    def _tail(self) -> _NewSpill:
        """Return the spill file new messages go to.

        The newest, when this writer opened it; a new one, named for now and after the file
        memory goes to at a stop (_leave_on_disk), when there is none or the newest was found at
        start (read only). Raises the disk's refusal.
        """
        newest = self._spills[-1] if self._spills else None
        if isinstance(newest, _NewSpill):
            return newest
        spill = _NewSpill.new(self.db_path, int(self.clock() * 1000), 1)
        with self._lock:
            self._spills.append(spill)
        log.warning("stream writer: messages go to %s before the database", spill.path)
        return spill

    def _leave_spills(self) -> None:
        """Every spill file stays on disk, listed as left; the next writer writes it back.

        The caller holds the lock.
        """
        for spill in self._spills:
            spill.close()
            self.left_on_disk.append(spill.status())
        self._spills = []

    def _spill(self, item: Item, held: _NewSpill | OSError) -> None:
        """Append one message of _admit or the stop's spill to the spill file `held`.

        It is counted in one locked section with its being held (_admitted): in `held`, or,
        refused by the disk (`held` is the refusal when no spill file could be opened), lost
        (neither the database nor a spill file holds it), with when it was received, a message
        stored first told so (_tell).
        """
        if isinstance(held, _NewSpill):
            try:
                held.append(_spill_record(item))
            except OSError as e:
                held = e
        refused = held if isinstance(held, OSError) else None
        ts = _received(item) if refused is not None else None
        with self._lock:
            if isinstance(held, _NewSpill):
                held.messages += 1
            else:
                self.lost += 1
                self._tell(item, None)
                if ts is not None:
                    self.lost_first_ts = (
                        ts if self.lost_first_ts is None else min(self.lost_first_ts, ts)
                    )
                    self.lost_last_ts = (
                        ts if self.lost_last_ts is None else max(self.lost_last_ts, ts)
                    )
            self._admitted += 1
        if refused is not None:
            self._log_once_a_minute(
                ("lost", type(refused).__name__),
                "stream writer: a message is lost: %s: %s",
                type(refused).__name__,
                refused,
            )

    def prune(self, before: float) -> None:
        """Remove every row received before `before` from the tables of KEPT_BY_TIME.

        It runs on the writer thread, one part of
        PRUNE_ROWS at a time between rounds of live writes (each round takes every message
        queued) while nothing is held on disk; a stop before it ends leaves the rest for the
        next one.
        """
        with self._lock:
            self._keeping = _Keep(before, [*KEPT_BY_TIME, *((t, "ts_recv") for t in ARCHIVED)])

    def _prune_part(self, conn: sqlite3.Connection, keep: _Keep) -> None:
        """Run the next part of `keep`, the keep in progress (prune), in one transaction.

        A keep asked again meanwhile starts over; this one's count stays its own. A part that
        fails for its own reason is undone and kept as sent, and the keep goes on to the next table.
        """
        table, column = keep.tables[0]
        try:
            if table in ARCHIVED:
                removed, part = self._archive_part(conn, table, column, keep.before), ARCHIVE_ROWS
            else:
                removed = conn.execute(
                    f"DELETE FROM {table} WHERE rowid IN (SELECT rowid FROM {table} "
                    f"WHERE {column} < ? LIMIT ?)",
                    (keep.before, PRUNE_ROWS),
                ).rowcount
                part = PRUNE_ROWS
        except (*ROW_FAILURES, *DATABASE_REFUSALS) as e:
            conn.rollback()
            if not _its_own(e):
                raise
            sent = {"table": table, "column": column, "before": keep.before}
            self._own_failure(conn, e, f"keep.{table}", sent)
            removed, part = 0, 1  # fewer than a part: the table is done
        conn.commit()
        with self._lock:
            keep.removed[table] += removed
            if removed < part:
                keep.tables.pop(0)
            done = not keep.tables
            if done and self._keeping is keep:
                self._keeping = None
        if done:
            log.info(
                "stream writer: rows received before %s removed: %s",
                ct_label(keep.before),
                ", ".join(f"{t} {n}" for t, n in keep.removed.items()),
            )

    def _archive_part(
        self, conn: sqlite3.Connection, table: str, column: str, before: float
    ) -> int:
        """Move the next ARCHIVE_ROWS rows received before `before` into stream_archive.

        The rows in the table's kept parts of the day (ARCHIVED) become one block; every row
        taken leaves the table, in the caller's transaction. Returns how many were taken.
        """
        cur = conn.execute(ARCHIVE_TAKE.format(table=table, column=column), (before, ARCHIVE_ROWS))
        names = [d[0] for d in cur.description][1:]
        taken = cur.fetchall()
        at = names.index(column)
        kept = [r[1:] for r in taken if ARCHIVED[table](r[1 + at])]
        if kept:
            conn.execute(
                "INSERT INTO stream_archive(source, first_ts, last_ts, rows, columns, body) "
                "VALUES (?,?,?,?,?,?)",
                (
                    table,
                    min(r[at] for r in kept),
                    max(r[at] for r in kept),
                    len(kept),
                    json.dumps(names),
                    archive_block(kept),
                ),
            )
        conn.executemany(f"DELETE FROM {table} WHERE rowid = ?", [(r[0],) for r in taken])
        return len(taken)

    def _write_back(self, conn: sqlite3.Connection) -> None:
        """Write the next part of the oldest spill file into the database.

        In one transaction with how far its write-back got; once all of it is in, the file is
        done (_finish_spill).
        """
        spill = self._spills[0]
        records = spill.read(SPILL_CHUNK, self.clock())
        if records:
            self._batch_spilled = True
            self._batch += self._stored_all(conn, [item for item, _end in records])
            end = records[-1][1]
            progress = {"spill": spill.path.name, "written_back": spill.written_back + len(records)}
            try:
                conn.execute(
                    "INSERT INTO stream_spill_progress(spill, written_back) VALUES(?,?) "
                    "ON CONFLICT(spill) DO UPDATE SET written_back=excluded.written_back",
                    tuple(progress.values()),
                )
            except (*ROW_FAILURES, *DATABASE_REFUSALS) as e:
                if not _its_own(e):
                    raise
                self._own_failure(conn, e, "stream_spill_progress", progress)
            conn.commit()
            with self._lock:
                self._committed(self._batch)
                self._batch, self._batch_spilled = [], False
                spill.committed(len(records), end)
        if spill.read_at == spill.size:
            with self._lock:
                self._spills.pop(0)
            self._finish_spill(spill, conn)

    def _finish_spill(self, spill: _Spill, conn: sqlite3.Connection) -> None:
        """Delete a spill whose every record is in the database, then its progress row.

        A file the disk will not delete (another process holds it open) keeps its row, which
        counts every record committed: the next writer's start deletes it without writing it
        again.
        """
        spill.close()
        try:
            os.remove(spill.path)
        except OSError:
            log.exception(
                "stream writer: %s written back (%d messages), not deleted, deleted at the next "
                "start",
                spill.path,
                spill.messages,
            )
            with self._lock:
                self.left_on_disk.append(spill.status())
            return
        try:
            conn.execute("DELETE FROM stream_spill_progress WHERE spill = ?", (spill.path.name,))
        except (*ROW_FAILURES, *DATABASE_REFUSALS) as e:
            if not _its_own(e):
                raise
            self._own_failure(conn, e, "stream_spill_progress", {"spill": spill.path.name})
        conn.commit()
        log.info(
            "stream writer: %s written back (%d messages); deleted", spill.path, spill.messages
        )

    def _leave_on_disk(self) -> None:
        """At a stop while the database refuses writes, leave what is held on disk.

        What is held in memory goes to a spill file named for when the block began (before the
        spill file's, _tail), and both stay, listed as left (here, or by the writer's death).
        Those not yet in it are counted as _admit's are (held; not recorded if the writer dies).
        """
        with self._lock:
            items, self._waiting, self._waiting_bytes = self._waiting, [], 0
            self._round, self._stored = self._waiting, 0
            self._admitting, self._admitted = items, 0
        if items:
            began = self.error_ts if self.error_ts is not None else self.clock()
            try:
                held: _NewSpill | OSError = _NewSpill.new(self.db_path, int(began * 1000), 0)
            except OSError as e:
                held = e
            else:
                with self._lock:
                    self._spills.insert(0, held)
            for item in items:
                self._spill(item, held)
        with self._lock:
            self._leave_spills()
            self._admitting, self._admitted = [], 0
