"""
app/options/order_flow/state.py — In-memory live order flow state from streaming.

Keeps recent book snapshots and tape prints from Schwab streaming; each symbol's top of book,
Greeks and volume are its record's on the daemon's bus, read once when the record changed
(stream_spine.streamed_record), never kept here.
Feeds OrderFlowEngine with content.* structure for book_imbalance_5 and cum_delta_proxy.
"""

from __future__ import annotations

import logging
import math
import threading
from array import array
from bisect import bisect_left
from collections import defaultdict, deque
from collections.abc import Iterable
from datetime import datetime
from typing import Any

from app.options.order_flow import history
from calc.l1_trade_observation import (
    PRINT_FIELDS,
    KeptPrint,
    TradePrint,
    extract_vendor_print,
    is_adjacent_restatement,
    quote_in_force,
)
from calc.option_window import TOTALS, LookBack, step_totals
from calc.order_flow import Book
from instrument_identity import ticker_storage_key
from option_contract import NO_TOP, QuoteValues, Streamed, StreamedTop, quote_values
from stream_spine import (
    FIELD_DELTA,
    NOT_STREAMED,
    held_key,
    quotes_at_trade,
    read_book,
    streamed_record,
)
from time_et import ET

# Limits to prevent unbounded growth
MAX_TAPE_PRINTS = 500
#: the fields a contract's look-back record takes: a message bringing neither only marks its minute
_LOOK_FIELDS = ("TOTAL_VOLUME", "VOLATILITY")

log = logging.getLogger(__name__)


def _held(value: float | None) -> float:
    return math.nan if value is None else value


def _value(held: float) -> float | None:
    return None if math.isnan(held) else held


class _Record:
    """One contract's look-back record of one ET market day (OrderFlowState.look_back).

    At the first message of each minute: the minute, and the contract's volume, volatility and
    running totals (calc.option_window.TOTALS) in force at its start, before that message; and
    the newest of each. A value not yet received is NaN in the arrays, None outside them.
    """

    __slots__ = (
        "day",
        "iv",
        "iv_at",
        "minute",
        "minutes",
        "totals",
        "totals_at",
        "volume",
        "volume_at",
    )

    def __init__(self, day: str) -> None:
        self.day = day
        self.minutes = array("q")
        self.volume_at = array("d")
        self.iv_at = array("d")
        self.totals_at = [array("d") for _ in TOTALS]
        self.minute = -1
        self.volume: float | None = None
        self.iv: float | None = None
        self.totals = [0.0] * len(TOTALS)

    def take(self, minute: int, volume: float | None, iv: float | None, adds: list[float]) -> None:
        """Take one message's values at `minute`: a new minute keeps the values before it."""
        if minute != self.minute:
            self.minutes.append(minute)
            self.volume_at.append(_held(self.volume))
            self.iv_at.append(_held(self.iv))
            for held, total in zip(self.totals_at, self.totals, strict=True):
                held.append(total)
            self.minute = minute
        for k, add in enumerate(adds):
            self.totals[k] += add
        if volume is not None:
            self.volume = volume
        if iv is not None:
            self.iv = iv

    def look_back(self, start: int) -> LookBack | None:
        """Return the record over the window from minute `start` to now.

        None when the record began at or after `start` (its values then are not known). The values
        in force at `start` are those at the first minute recorded from it on, no message having
        come between; with none, they are the newest.
        """
        if not self.minutes or self.minutes[0] >= start:
            return None
        j = bisect_left(self.minutes, start)
        if j == len(self.minutes):
            volume, iv, totals = self.volume, self.iv, list(self.totals)
        else:
            volume, iv = _value(self.volume_at[j]), _value(self.iv_at[j])
            totals = [held[j] for held in self.totals_at]
        return LookBack(
            volume=(volume, self.volume),
            iv=(iv, self.iv),
            totals=(
                self.totals[0] - totals[0],
                self.totals[1] - totals[1],
                self.totals[2] - totals[2],
                self.totals[3] - totals[3],
                self.totals[4] - totals[4],
            ),
        )


class OrderFlowState:
    """The one state-transition owner for live and isolated historical replay."""

    def __init__(self) -> None:
        # RLock: prints holds the lock and calls the tape's accessor.
        self._lock = threading.RLock()
        # each symbol's newest book from each Schwab service, the newest arrival last: a book
        # Schwab has not changed stands, however many the other service sends
        self._book: defaultdict[str, dict[str, Book]] = defaultdict(dict)
        self._tape: dict[str, deque[KeptPrint]] = {}
        #: each option contract's look-back record of the market day (_Record), from its first
        #: LEVELONE_OPTIONS message of the day since the program started
        self._records: dict[str, _Record] = {}
        #: the bus's current records (stream_spine.MessageBus.current, bind): each symbol's top of
        #: book, Greeks and volume are read from them, never kept here
        self.current: dict[str, tuple[str, Any]] = {}

    def streamed(self, service: str, symbol: str) -> Streamed:
        """Return what Schwab `service` last sent of `symbol`, from its record on the bus."""
        return streamed_record(self.current.get(held_key(service, ticker_storage_key(symbol))))

    def _get_tape(self, symbol: str) -> deque[KeptPrint]:
        with self._lock:
            if symbol not in self._tape:
                self._tape[symbol] = deque(maxlen=MAX_TAPE_PRINTS)
            return self._tape[symbol]

    def push_book(self, symbol: str, content_item: dict[str, Any], service: str) -> Book | None:
        """Apply one Schwab book observation to this state instance.

        It comes from `service`: NYSE_BOOK, NASDAQ_BOOK or OPTIONS_BOOK. The book as read once
        (stream_spine.read_book) is returned; None when the message carries no book.
        """
        if not content_item:
            return None
        book = read_book(content_item, service)
        sym = ticker_storage_key(symbol)
        if book is None or not sym:
            return None
        with self._lock:
            books = self._book[sym]
            books.pop(service, None)
            books[service] = book
        return book

    def push_level_one(self, service: str, record: tuple[str, dict[str, Any]]) -> None:
        """Take one version of a symbol's Schwab L1 record of `service`, as a live reader takes it.

        `record` is the version the bus handed over (stream_spine.MessageBus), read whole: never
        the bus's newer one. An option contract's version goes to its look-back record
        (_take_record). A version whose message brought a field of the last trade
        (`brought_trade`: the trade's own item) is a print, unless it restates the print kept just
        before it, kept with the quote in force when it traded: the newest Schwab timed at or
        before the trade (quote_in_force) of the quotes the version holds
        (stream_spine.quotes_at_trade), since Schwab sends a trade with the quote that followed
        it; and with the version's Greeks, stamped with the newest receive time of its fields.
        """
        topic, rec = record
        sym = ticker_storage_key(rec["symbol"])
        content = rec[FIELD_DELTA[topic.split(".", 1)[0]]]
        # the trade this version brought; a version that brought none carries no trade of its own
        trade = extract_vendor_print(content) if rec["brought_trade"] else None
        if service == "LEVELONE_OPTIONS":
            self._take_record(sym, record, trade)
        if trade is None:
            return
        sent = streamed_record(record)
        with self._lock:
            tape = self._get_tape(sym)
            # an adjacent repeat of the same trade is a restatement (l1_trade_observation): a
            # subscription's whole record restating the held trade; never a second print. The
            # trade before it is the tape's last print
            if is_adjacent_restatement(tape[-1] if tape else None, trade):
                return
            tape.append(
                history.quoted(
                    trade,
                    # the daemon's receive time of the message that carried the trade, not the
                    # console's clock: the newest of the print's own fields, since a trade at an
                    # unchanged price carries a new time and size but no LAST_PRICE (Change)
                    float(max(rec["field_ts"][f][1] for f in PRINT_FIELDS if f in content)),
                    # the bid and ask in force when the trade was made, by Schwab's own quote and
                    # trade times (never a quote that followed it), and the version's Greeks
                    quote_in_force(trade.time_millis, *quotes_at_trade(record)),
                    sent.greeks,
                )
            )

    def _take_record(
        self, sym: str, record: tuple[str, dict[str, Any]], trade: TradePrint | None
    ) -> None:
        """Take one version of a LEVELONE_OPTIONS record into the contract's look-back record.

        At its receive time, with its fields as the version carries them (read once per version,
        stream_spine.streamed_record): a rise of its TOTAL_VOLUME is one step, read by the trade
        the version brought (`trade`, None for a version that brought none) against the quote in
        force then (calc.option_window.step_totals). A record of an earlier ET day is begun anew:
        Schwab's volume counts from each day's start.
        """
        rec = record[1]
        ts, content, stamps = rec["ts_recv"], rec[FIELD_DELTA["optquote"]], rec["field_ts"]
        minute = int(ts // 60)
        # a message bringing neither (a quote alone) only marks the minute: its values stand
        brought = any(f in content and stamps[f][1] == ts for f in _LOOK_FIELDS)
        own = streamed_record(record) if brought else None
        volume = None if own is None else own.greeks.total_volume.value
        iv = None if own is None else own.greeks.volatility.value
        adds = [0.0] * len(TOTALS)
        with self._lock:
            if sym not in self._records or self._records[sym].minute != minute:
                # the ET day is read only on a new minute: one minute is one day
                day = datetime.fromtimestamp(ts, ET).date().isoformat()
                if sym not in self._records or self._records[sym].day != day:
                    self._records[sym] = _Record(day)
            held = self._records[sym]
            if (
                own is not None
                and volume is not None
                and held.volume is not None
                and volume > held.volume
            ):
                quote = (
                    NO_TOP
                    if trade is None
                    else quote_in_force(trade.time_millis, *quotes_at_trade(record))
                )
                adds = list(
                    step_totals(
                        volume - held.volume,
                        None if trade is None else trade.price,
                        quote.bid,
                        quote.ask,
                        own.greeks.delta.value,
                        own.greeks.underlying_price.value,
                    )
                )
            held.take(minute, volume, iv, adds)

    def look_back(self, symbols: Iterable[str], day: str, start: int) -> dict[str, LookBack]:
        """Return each of `symbols`' look-back from minute `start` of ET day `day` to now.

        A contract with no record of that day, or one begun at or after `start` (the stream did
        not hold it over the whole window), is left out.
        """
        out: dict[str, LookBack] = {}
        with self._lock:
            for sym in symbols:
                key = ticker_storage_key(sym)
                if key not in self._records or self._records[key].day != day:
                    continue
                look = self._records[key].look_back(start)
                if look is not None:
                    out[sym] = look
        return out

    def prints(self, symbol: str) -> list[KeptPrint]:
        """Return the symbol's tape: each print it kept, in receive order."""
        sym = ticker_storage_key(symbol)
        with self._lock:
            return list(self._get_tape(sym))  # a kept print is never changed: no copy of it

    def newest_book(self, symbol: str, venue: str) -> Book | None:
        """Return the newest book held for `symbol` from Schwab service `venue`; None: none held."""
        sym = ticker_storage_key(symbol)
        with self._lock:
            return self._book[sym].get(venue)

    def clear_all(self) -> None:
        """Drop every symbol's tape and books; with a tape goes the trade a restatement repeats."""
        with self._lock:
            self._clear_all_session_state_unlocked()

    def _clear_all_session_state_unlocked(self) -> None:
        """Drop session state, each contract's look-back record with it. Caller holds the lock."""
        for values in self._tape.values():
            values.clear()
        for values in self._book.values():
            values.clear()
        self._records.clear()


_LIVE_STATE = OrderFlowState()


def bind_bus(current: dict[str, tuple[str, Any]]) -> None:
    """Read each symbol's top of book, Greeks and volume from the daemon's bus records."""
    _LIVE_STATE.current = current


#: each option contract's newest /quotes answer: symbol -> (the time it was received, its values
#: as option_contract.quote_values reads them). Newest by the answer's receive time: Schwab's
#: /quotes answer carries no time of its own.
_REST_QUOTES: dict[str, tuple[float, QuoteValues]] = {}
_rest_lock = threading.Lock()


def push_rest_quotes(answer: dict[str, Any], received: float) -> None:
    """Keep one /quotes answer (symbol -> Schwab's `quote`), received at `received`.

    A contract whose held answer was received later keeps it: an older answer never replaces a
    newer value.
    """
    read = {sym: (received, quote_values(quote)) for sym, quote in answer.items()}
    with _rest_lock:
        _REST_QUOTES.update(
            {
                sym: values
                for sym, values in read.items()
                if sym not in _REST_QUOTES or _REST_QUOTES[sym][0] <= received
            }
        )


def rest_quotes(symbols: Iterable[str], since: float) -> dict[str, tuple[float, QuoteValues]]:
    """Return each of `symbols`' newest /quotes answer received at or after `since`.

    Each as (its receive time, its values). An answer received before `since` is left out: the
    chain that began at `since` carries newer values of that contract.
    """
    with _rest_lock:
        kept = {s: _REST_QUOTES[s] for s in symbols if s in _REST_QUOTES}
    return {s: answer for s, answer in kept.items() if answer[0] >= since}


def look_back(symbols: Iterable[str], day: str, start: int) -> dict[str, LookBack]:
    """Return the live singleton's look-back of each of `symbols` (OrderFlowState.look_back)."""
    return _LIVE_STATE.look_back(symbols, day, start)


def option_top(symbol: str) -> StreamedTop:
    """Return a contract's top of book as LEVELONE_OPTIONS last sent each field (NO_TOP: none)."""
    return _LIVE_STATE.streamed("LEVELONE_OPTIONS", symbol).top


def push_book(symbol: str, content_item: dict[str, Any], service: str) -> Book | None:
    """Apply a book observation to the live singleton: the book as read, or None."""
    return _LIVE_STATE.push_book(symbol, content_item, service)


def push_level_one(service: str, record: tuple[str, dict[str, Any]]) -> None:
    """Apply one version of an L1 record, as the bus handed it over, to the live singleton."""
    _LIVE_STATE.push_level_one(service, record)


def prints(symbol: str) -> list[KeptPrint]:
    """Return the live singleton's tape of `symbol`: each print it kept, in receive order."""
    return _LIVE_STATE.prints(symbol)


def newest_book(symbol: str, venue: str) -> Book | None:
    """Return the live singleton's newest book of `symbol` from `venue`."""
    return _LIVE_STATE.newest_book(symbol, venue)


def clear_all_live_state() -> None:
    """Drop every symbol's tape, books and look-back records, when the console stops streaming.

    Its one caller is the console's stop (streaming.stop_order_flow_stream). A reconnect of
    Schwab's stream keeps them: Schwab's counts run on, so a look-back's volume across the gap
    stays exact, and the gap's trades arrive as one rise of volume, read by its last trade as
    any rise Schwab merges is.
    """
    _LIVE_STATE.clear_all()


def streamed_values(symbols: Iterable[str]) -> dict[str, Streamed]:
    """Return what LEVELONE_OPTIONS holds of each of `symbols`; one it sent nothing of: left out."""
    out: dict[str, Streamed] = {}
    for sym in symbols:
        held = _LIVE_STATE.streamed("LEVELONE_OPTIONS", sym)
        if held is not NOT_STREAMED:
            out[sym] = held
    return out
