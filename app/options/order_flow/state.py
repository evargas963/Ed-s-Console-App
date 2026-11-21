"""
app/options/order_flow/state.py — In-memory live order flow state from streaming.

Keeps recent book snapshots and tape prints from Schwab streaming; each symbol's top of book,
Greeks and volume are its record's on the daemon's bus, read once when the record changed
(stream_spine.streamed_record), never kept here.
Feeds OrderFlowEngine with content.* structure for book_imbalance_5 and cum_delta_proxy.
"""

from __future__ import annotations

import logging
import threading
from collections import defaultdict, deque
from collections.abc import Iterable
from dataclasses import asdict
from typing import Any

from app.options.order_flow import history
from calc.l1_trade_observation import (
    TAPE_CLASSIFICATION,
    TAPE_COMPLETENESS,
    VENDOR_LAST_PRICE,
    VENDOR_LAST_SIZE,
    VENDOR_TRADE_TIME,
    extract_vendor_print,
    is_adjacent_restatement,
    quote_in_force,
    vendor_triple,
)
from calc.order_flow import Book
from instrument_identity import ticker_storage_key
from option_contract import Streamed, StreamedTop, quote_values
from stream_spine import NOT_STREAMED, held_key, read_book, streamed_record

# Limits to prevent unbounded growth
MAX_TAPE_PRINTS = 500
#: a print's three fields: a new value of any makes a new print
_PRINT_FIELDS = (VENDOR_LAST_PRICE, VENDOR_LAST_SIZE, VENDOR_TRADE_TIME)

log = logging.getLogger(__name__)


class OrderFlowState:
    """The one state-transition owner for live and isolated historical replay."""

    def __init__(self) -> None:
        # RLock: prints holds the lock and calls the tape's accessor.
        self._lock = threading.RLock()
        # each symbol's newest book from each Schwab service, the newest arrival last: a book
        # Schwab has not changed stands, however many the other service sends
        self._book: defaultdict[str, dict[str, Book]] = defaultdict(dict)
        self._tape: dict[str, deque[dict[str, Any]]] = {}
        self._prev_trade: dict[str, tuple[int | None, float | None, float | None]] = {}
        self._receive_seq: dict[str, int] = {}
        #: the bus's current records (stream_spine.MessageBus.current, bind): each symbol's top of
        #: book, Greeks and volume are read from them, never kept here
        self.current: dict[str, tuple[str, Any]] = {}

    def streamed(self, service: str, symbol: str) -> Streamed:
        """Return what Schwab `service` last sent of `symbol`, from its record on the bus."""
        return streamed_record(self.current.get(held_key(service, ticker_storage_key(symbol))))

    def _get_tape(self, symbol: str) -> deque[dict[str, Any]]:
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

    def push_level_one(
        self,
        service: str,
        symbol: str,
        content_item: dict[str, Any],
        ts_recv: float | None = None,
        field_received: dict[str, Any] | None = None,
    ) -> None:
        """Keep the print one Schwab L1 record of `service` carries, with the quote in force then.

        That quote is the newest Schwab timed at or before the trade (quote_in_force): Schwab
        sends a trade with the quote that followed it. A current record merged from several
        messages (the daemon's bus) carries each field's own receive time in `field_received`;
        the print is stamped with the newest of its fields'.
        """
        if not content_item:
            return
        sym = ticker_storage_key(symbol)
        if not sym:
            return
        if ts_recv is None:
            # the daemon's receive time is required: stamping "now" would make a replayed or
            # delayed message read as live
            raise TypeError("push_level_one: ts_recv (the daemon receive time) is required")

        def received(field: str) -> float:
            return ts_recv if field_received is None else field_received[field]

        trade = extract_vendor_print(content_item)
        if trade is None:
            return
        key = vendor_triple(trade.time_millis, trade.price, trade.size)
        sent = self.streamed(service, sym)
        with self._lock:
            # an adjacent repeat of the same trade is a restatement (l1_trade_observation): a
            # whole record, or the merged record on a quote change; never a second print
            if is_adjacent_restatement(self._prev_trade.get(sym), key):
                return
            self._prev_trade[sym] = key
            self._receive_seq[sym] = self._receive_seq.get(sym, 0) + 1
            self._get_tape(sym).append(
                {
                    **asdict(trade),
                    "receive_seq": self._receive_seq[sym],
                    # the daemon's receive time of the message that carried the trade, not the
                    # console's clock: the newest of the print's own fields, since a trade at an
                    # unchanged price carries a new time and size but no LAST_PRICE (Change)
                    "server_received_ts": float(
                        max(received(f) for f in _PRINT_FIELDS if f in content_item)
                    ),
                    "classification": TAPE_CLASSIFICATION,
                    "completeness": TAPE_COMPLETENESS,
                    # the bid and ask in force when the trade was made, by Schwab's own quote and
                    # trade times (never the quote that followed it), and the record's Greeks
                    **history.quoted(
                        trade.price,
                        quote_in_force(trade.time_millis, sent.top, sent.before),
                        sent.greeks,
                    ),
                }
            )

    def prints(self, symbol: str) -> list[dict[str, Any]]:
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
        """Drop tape/book/top/prev-print identity for every symbol."""
        with self._lock:
            self._clear_all_session_state_unlocked()

    def _clear_all_session_state_unlocked(self) -> None:
        """Drop session state. Caller holds ``self._lock``."""
        for values in self._tape.values():
            values.clear()
        for values in self._book.values():
            values.clear()
        self._prev_trade.clear()
        self._receive_seq.clear()

    def clear_symbol(self, symbol: str) -> None:
        """Clear all state for one symbol, its recent prints and books included."""
        sym = ticker_storage_key(symbol)
        history.BOOKS.forget(sym)
        history.LEAN.forget(sym)
        with self._lock:
            self._book.pop(sym, None)
            if sym in self._tape:
                self._tape[sym].clear()
            self._prev_trade.pop(sym, None)
            self._receive_seq.pop(sym, None)


_LIVE_STATE = OrderFlowState()


def bind_bus(current: dict[str, tuple[str, Any]]) -> None:
    """Read each symbol's top of book, Greeks and volume from the daemon's bus records."""
    _LIVE_STATE.current = current


#: each option contract's newest /quotes answer: symbol -> (the time it was received, its values
#: as option_contract.quote_values reads them). The sweep asks one request at a time, so each
#: answer is the newest.
_REST_QUOTES: dict[str, tuple[float, dict[str, Any]]] = {}
_rest_lock = threading.Lock()


def push_rest_quotes(answer: dict[str, Any], received: float) -> None:
    """Keep one /quotes answer (symbol -> Schwab's `quote`), received at `received`."""
    read = {sym: (received, quote_values(quote)) for sym, quote in answer.items()}
    with _rest_lock:
        _REST_QUOTES.update(read)


def rest_quotes(symbols: Iterable[str], since: float) -> dict[str, tuple[float, dict[str, Any]]]:
    """Return each of `symbols`' newest /quotes answer received at or after `since`.

    Each as (its receive time, its values). An answer received before `since` is left out: the
    chain that began at `since` carries newer values of that contract.
    """
    with _rest_lock:
        kept = {s: _REST_QUOTES[s] for s in symbols if s in _REST_QUOTES}
    return {s: answer for s, answer in kept.items() if answer[0] >= since}


def option_top(symbol: str) -> StreamedTop:
    """Return a contract's top of book as LEVELONE_OPTIONS last sent each field (NO_TOP: none)."""
    return _LIVE_STATE.streamed("LEVELONE_OPTIONS", symbol).top


def push_book(symbol: str, content_item: dict[str, Any], service: str) -> Book | None:
    """Apply a book observation to the live singleton: the book as read, or None."""
    return _LIVE_STATE.push_book(symbol, content_item, service)


def push_level_one(
    service: str,
    symbol: str,
    content_item: dict[str, Any],
    ts_recv: float | None = None,
    field_received: dict[str, Any] | None = None,
) -> None:
    """Apply an L1 observation to the live singleton."""
    _LIVE_STATE.push_level_one(
        service, symbol, content_item, ts_recv=ts_recv, field_received=field_received
    )


def prints(symbol: str) -> list[dict[str, Any]]:
    """Return the live singleton's tape of `symbol`: each print it kept, in receive order."""
    return _LIVE_STATE.prints(symbol)


def newest_book(symbol: str, venue: str) -> Book | None:
    """Return the live singleton's newest book of `symbol` from `venue`."""
    return _LIVE_STATE.newest_book(symbol, venue)


def clear_all_live_state() -> None:
    """Drop tape/book/top/prev-print identity for every symbol.

    Required on stream disconnect/reconnect. Leaving the last window resident
    mixes pre-disconnect restatements with the new session.
    """
    _LIVE_STATE.clear_all()


def clear_symbol(symbol: str) -> None:
    """Clear stored data for a symbol (e.g. on unsubscribe)."""
    _LIVE_STATE.clear_symbol(symbol)


def streamed_values(symbols: Iterable[str]) -> dict[str, Streamed]:
    """Return what LEVELONE_OPTIONS holds of each of `symbols`; one it sent nothing of: left out."""
    out: dict[str, Streamed] = {}
    for sym in symbols:
        held = _LIVE_STATE.streamed("LEVELONE_OPTIONS", sym)
        if held is not NOT_STREAMED:
            out[sym] = held
    return out
