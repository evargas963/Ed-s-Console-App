"""
app/options/order_flow/state.py — In-memory live order flow state from streaming.

Stores recent book snapshots, tape prints, and top-of-book from Schwab streaming.
Feeds OrderFlowEngine with content.* structure for book_imbalance_5 and cum_delta_proxy.
"""

from __future__ import annotations

import logging
import threading
from collections import defaultdict, deque
from collections.abc import Iterable

from app.options.order_flow import history
from app.options.order_flow.engine import Book, read_book
from instrument_identity import ticker_storage_key
from l1_trade_observation import (
    TAPE_CLASSIFICATION,
    TAPE_COMPLETENESS,
    extract_vendor_print,
    is_adjacent_restatement,
    vendor_triple,
)
from numeric_contract import schwab_count, schwab_number
from option_contract import quote_values, streamed_greeks

# Limits to prevent unbounded growth
MAX_TAPE_PRINTS = 500

log = logging.getLogger(__name__)


_OPTION_TOP_FIELDS = (
    ("BID_PRICE", "bid", schwab_number),
    ("ASK_PRICE", "ask", schwab_number),
    ("BID_SIZE", "bid_size", schwab_count),
    ("ASK_SIZE", "ask_size", schwab_count),
    ("MARK", "mark", schwab_number),
    ("QUOTE_TIME_MILLIS", "quote_time_ms", schwab_number),
)


class OrderFlowState:
    """The one state-transition owner for live and isolated historical replay."""

    def __init__(self) -> None:
        # RLock: get_content_for_symbol holds the lock and calls the tape's accessor.
        self._lock = threading.RLock()
        # each symbol's newest book from each Schwab service, the newest arrival last: a book
        # Schwab has not changed stands, however many the other service sends
        self._book: defaultdict[str, dict[str, Book]] = defaultdict(dict)
        self._tape: dict[str, deque] = {}
        self._top: dict[str, dict] = {}
        self._prev_trade: dict[str, tuple[int | None, float | None, float | None]] = {}
        self._receive_seq: dict[str, int] = {}
        self._stream_greeks: dict[str, dict] = {}

    def _get_tape(self, symbol: str) -> deque:
        with self._lock:
            if symbol not in self._tape:
                self._tape[symbol] = deque(maxlen=MAX_TAPE_PRINTS)
            return self._tape[symbol]

    def push_book(self, symbol: str, content_item: dict, service: str) -> Book | None:
        """Apply one Schwab book observation to this state instance.

        It comes from `service`: NYSE_BOOK, NASDAQ_BOOK or OPTIONS_BOOK. The book as read once
        (engine.read_book) is returned; None when the message carries no book.
        """
        if not content_item or not isinstance(content_item, dict):
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
        symbol: str,
        content_item: dict,
        ts_recv: float | None = None,
        field_received: dict | None = None,
    ) -> None:
        """Apply one Schwab L1 observation with canonical merge/freshness/tape semantics.

        A current record merged from several messages (the daemon's bus) carries each field's own
        receive time in `field_received`; each value is stamped with it.
        """
        if not content_item or not isinstance(content_item, dict):
            return
        sym = ticker_storage_key(symbol)
        if not sym:
            return
        if ts_recv is None:
            # the daemon's receive time is required: stamping "now" would make a replayed or
            # delayed message read as live
            raise TypeError("push_level_one: ts_recv (the daemon receive time) is required")

        # TOTAL_VOLUME as sent; a reported 0 is 0 (AGENTS.md rule 2).
        vf = schwab_count(content_item.get("TOTAL_VOLUME"))

        # (change percent lives on the live plane only: NET_CHANGE_PERCENT, one store.)

        # The contract's own Greeks and volume, each with its own receive time: a message carries
        # only the fields that changed (Change delivery), so each field is merged alone; a Greek
        # Schwab sends as -999 is no value, and stands as None. Open interest is the chain's:
        # the stream does not send it for every contract it streams.
        greeks = streamed_greeks(content_item)

        def received(field: str) -> float:
            return ts_recv if field_received is None else field_received[field]

        if greeks or vf is not None:
            with self._lock:
                g = self._stream_greeks.setdefault(sym, {})
                for name, value in greeks.items():
                    g[name], g[f"{name}_ts_recv"] = value, received(name.upper())
                if vf is not None:
                    g["total_volume"], g["total_volume_ts_recv"] = vf, received("TOTAL_VOLUME")

        trade = extract_vendor_print(content_item)
        if trade is None:
            return
        key = vendor_triple(trade["time_millis"], trade["price"], trade["size"])
        with self._lock:
            # an adjacent repeat of the same trade is a restatement: never a second print
            if is_adjacent_restatement(self._prev_trade.get(sym), key):
                return
            self._prev_trade[sym] = key
            seq = self._receive_seq.get(sym, 0) + 1
            self._receive_seq[sym] = seq
            self._get_tape(sym).append(
                {
                    **trade,
                    "receive_seq": seq,
                    # the daemon's receive time of the message that carried the trade, not the
                    # console's clock, and not a later tick merged into the same record
                    "server_received_ts": float(received("LAST_PRICE")),
                    "classification": TAPE_CLASSIFICATION,
                    "completeness": TAPE_COMPLETENESS,
                    "native_event_id": False,
                }
            )

    def get_content_for_symbol(self, symbol: str, venue: str | None = None) -> list:
        """Return the engine's input for one symbol.

        That is its newest book of each Schwab service (engine.Book) then its tape's prints
        (dicts), in receive order; with `venue`, only that Schwab book service's book (an equity
        has two: NYSE_BOOK and NASDAQ_BOOK).
        """
        sym = ticker_storage_key(symbol)
        if not sym:
            return []
        out: list = []
        with self._lock:
            out.extend(
                book for book in self._book[sym].values() if venue is None or book.service == venue
            )
            out.extend(dict(item) for item in self._get_tape(sym))
        return out

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
        for key in list(self._top):
            self._top[key] = {}
        for values in self._book.values():
            values.clear()
        self._prev_trade.clear()
        self._receive_seq.clear()
        self._stream_greeks.clear()

    def clear_symbol(self, symbol: str) -> None:
        """Clear all state for one symbol, its recent prints and books included."""
        sym = ticker_storage_key(symbol)
        history.TAPE.forget(sym)
        history.BOOKS.forget(sym)
        history.LEAN.forget(sym)
        with self._lock:
            self._book.pop(sym, None)
            if sym in self._tape:
                self._tape[sym].clear()
            self._top.pop(sym, None)
            self._prev_trade.pop(sym, None)
            self._receive_seq.pop(sym, None)
            self._stream_greeks.pop(sym, None)

    def push_option_top(self, symbol: str, content_item: dict) -> None:
        """Merge an option contract's top of book (LEVELONE_OPTIONS BID/ASK price and size, MARK).

        It is merged per field as Schwab sends changes only; not a number clears the field.
        """
        sym = ticker_storage_key(symbol)
        if not sym:
            return
        with self._lock:
            top = self._top.setdefault(sym, {})
            for field, name, read in _OPTION_TOP_FIELDS:
                if field in content_item:
                    v = read(content_item[field])
                    if v is None:
                        top.pop(name, None)
                    else:
                        top[name] = v

    def option_top(self, symbol: str) -> dict | None:
        sym = ticker_storage_key(symbol)
        with self._lock:
            t = self._top.get(sym)
            return dict(t) if t else None

    def get_stream_greeks(self, symbol: str) -> dict | None:
        """Return the latest streamed Greeks, OPEN_INTEREST and TOTAL_VOLUME for one contract.

        The contract is one OPTION contract symbol, each field paired with its own ``_ts_recv``
        (the field's own last-update wall-clock receive time, not merely this call's time) -- a
        per-field freshness stamp is what lets a caller judge one field newer than a same-tick
        sibling that was absent this update, per the sparse-overlay pattern below. Returns None
        when nothing has ever been observed for this symbol (never a dict of Nones).
        """
        sym = ticker_storage_key(symbol)
        if not sym:
            return None
        with self._lock:
            g = self._stream_greeks.get(sym)
            return dict(g) if g else None


_LIVE_STATE = OrderFlowState()


#: each option contract's newest /quotes answer: symbol -> (the time it was received, its values
#: as option_contract.quote_values reads them). The sweep asks one request at a time, so each
#: answer is the newest.
_REST_QUOTES: dict[str, tuple[float, dict]] = {}
_rest_lock = threading.Lock()


def push_rest_quotes(answer: dict, received: float) -> None:
    """Keep one /quotes answer (symbol -> Schwab's `quote`), received at `received`."""
    read = {sym: (received, quote_values(quote)) for sym, quote in answer.items()}
    with _rest_lock:
        _REST_QUOTES.update(read)


def rest_quotes(symbols: Iterable[str], since: float) -> dict[str, tuple[float, dict]]:
    """Return each of `symbols`' newest /quotes answer received at or after `since`.

    Each as (its receive time, its values). An answer received before `since` is left out: the
    chain that began at `since` carries newer values of that contract.
    """
    with _rest_lock:
        kept = {s: _REST_QUOTES[s] for s in symbols if s in _REST_QUOTES}
    return {s: answer for s, answer in kept.items() if answer[0] >= since}


def push_option_top(symbol: str, content_item: dict) -> None:
    _LIVE_STATE.push_option_top(symbol, content_item)


def option_top(symbol: str) -> dict | None:
    return _LIVE_STATE.option_top(symbol)


def push_book(symbol: str, content_item: dict, service: str) -> Book | None:
    """Apply a book observation to the live singleton: the book as read, or None."""
    return _LIVE_STATE.push_book(symbol, content_item, service)


def push_level_one(
    symbol: str,
    content_item: dict,
    ts_recv: float | None = None,
    field_received: dict | None = None,
) -> None:
    """Apply an L1 observation to the live singleton."""
    _LIVE_STATE.push_level_one(symbol, content_item, ts_recv=ts_recv, field_received=field_received)


def get_content_for_symbol(symbol: str, venue: str | None = None) -> list:
    """Return canonical engine content from the live singleton."""
    return _LIVE_STATE.get_content_for_symbol(symbol, venue)


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


def get_stream_greeks(symbol: str) -> dict | None:
    """Return the live singleton's latest streamed GAMMA/DELTA/OPEN_INTEREST for one contract.

    The contract is one option contract symbol; each value is paired with its own `_ts_recv`,
    or None is returned if never observed.
    """
    return _LIVE_STATE.get_stream_greeks(symbol)
