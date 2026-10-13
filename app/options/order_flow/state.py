"""
app/options/order_flow/state.py — In-memory live order flow state from streaming.
Stores recent book snapshots and each option contract's record from Schwab streaming; the trade
prints are the one tape's (history.TAPE). Feeds OrderFlowEngine with the books (content.*).
"""

from __future__ import annotations

import logging
import threading
from collections import deque
from dataclasses import dataclass
from typing import Optional
from app.options.order_flow import history
from instrument_identity import ticker_storage_key
from numeric_contract import schwab_count, schwab_number

# Limits to prevent unbounded growth
MAX_BOOK_SNAPSHOTS = 20

log = logging.getLogger(__name__)


#: a contract record's top of book, as the order-flow engine names it: (record field, name, reader)
_OPTION_TOP_FIELDS = (("bid", "bid", schwab_number), ("ask", "ask", schwab_number),
                      ("bidSize", "bid_size", schwab_count), ("askSize", "ask_size", schwab_count),
                      ("mark", "mark", schwab_number))


@dataclass(frozen=True)
class ContractRecord:
    """An option contract's one record as the daemon's ledger holds it (option_ledger), mirrored
    here read-only: its fields, named as the chain names them, and each field's (Schwab time in
    ms, the daemon's receive time)."""
    fields: dict
    times: dict


class OrderFlowState:
    """The one state-transition owner for live and isolated historical replay."""

    def __init__(self) -> None:
        # RLock: get_content_for_symbol holds the lock and calls the deque accessors.
        self._lock = threading.RLock()
        self._book: dict[str, deque] = {}
        #: the daemon's contract records, mirrored (push_contract): contract -> its record, and
        #: each watchlist ticker's contracts, in the order Schwab listed them
        self._contracts: dict[str, ContractRecord] = {}
        self._by_ticker: dict[str, dict[str, None]] = {}

    def _get_book(self, symbol: str) -> deque:
        with self._lock:
            if symbol not in self._book:
                self._book[symbol] = deque(maxlen=MAX_BOOK_SNAPSHOTS)
            return self._book[symbol]

    def push_book(self, symbol: str, content_item: dict, service: str) -> None:
        """Apply one Schwab book observation (from `service`: NYSE_BOOK, NASDAQ_BOOK or
        OPTIONS_BOOK) to this state instance."""
        if not content_item or not isinstance(content_item, dict):
            return
        bids = content_item.get("BIDS")
        asks = content_item.get("ASKS")
        if bids is None and asks is None:
            return
        sym = ticker_storage_key(symbol or content_item.get("key"))
        if not sym:
            return

        def _side(levels) -> list:      # a side Schwab sent no levels for is empty, as sent
            return [] if levels is None else list(levels) if isinstance(levels, list) else [levels]

        item = {
            "BIDS": _side(bids),
            "ASKS": _side(asks),
            "BOOK_TIME": content_item.get("BOOK_TIME"),
            "SERVICE": service,
        }
        with self._lock:
            self._get_book(sym).append(item)

    def get_content_for_symbol(self, symbol: str, venue: Optional[str] = None) -> list[dict]:
        """The symbol's books, the engine's content; with `venue`, only that Schwab book
        service's (an equity has two: NYSE_BOOK and NASDAQ_BOOK)."""
        sym = ticker_storage_key(symbol)
        if not sym:
            return []
        with self._lock:
            return [dict(item) for item in self._get_book(sym) if venue is None or item["SERVICE"] == venue]

    def clear_all(self) -> None:
        """Drop the books, the prints and the option records of every symbol (the stream stopped)."""
        history.TAPE.forget_all()
        with self._lock:
            for values in self._book.values():
                values.clear()
            self._contracts.clear()
            self._by_ticker.clear()

    def clear_symbol(self, symbol: str) -> None:
        """Clear one symbol's streamed state, its recent prints and books included (a contract's
        record stays: the ledger's, which REST keeps posting to)."""
        sym = ticker_storage_key(symbol)
        history.TAPE.forget(sym)
        history.BOOKS.forget(sym)
        with self._lock:
            if sym in self._book:
                self._book[sym].clear()

    def push_contract(self, symbol: str, record: ContractRecord) -> None:
        """Mirror `symbol`'s record as the daemon pushed it, whole, in place of the one held."""
        sym = ticker_storage_key(symbol)
        with self._lock:
            self._contracts[sym] = record
            ticker = record.fields.get("ticker")
            if ticker:
                self._by_ticker.setdefault(ticker, {})[sym] = None

    def drop_unlisted(self, ticker: str, opened_at: float) -> None:
        """After `ticker`'s day's opening (begun at `opened_at`, the daemon's receive time), forget
        each of its records the opening did not post: a contract Schwab no longer lists, as the
        daemon forgot it (capture.Daemon._took_chain)."""
        with self._lock:
            listed = self._by_ticker.get(ticker, {})
            for sym in [s for s in listed
                        if max(stamp[1] for stamp in self._contracts[s].times.values()) < opened_at]:
                del listed[sym]
                del self._contracts[sym]

    def contracts_of(self, ticker: str) -> "dict[str, ContractRecord]":
        """`ticker`'s contracts and their records (none when the daemon has pushed none)."""
        with self._lock:
            if ticker not in self._by_ticker:
                return {}
            return {s: self._contracts[s] for s in self._by_ticker[ticker]}

    def contract(self, symbol: str) -> Optional[ContractRecord]:
        with self._lock:
            return self._contracts.get(ticker_storage_key(symbol))

    def option_top(self, symbol: str) -> Optional[dict]:
        """An option contract's top of book (bid/ask price and size, mark) from its record; a
        field that is not a number is absent."""
        record = self.contract(symbol)
        if record is None:
            return None
        top = {name: v for field, name, read in _OPTION_TOP_FIELDS
               if field in record.fields and (v := read(record.fields[field])) is not None}
        return top or None


_LIVE_STATE = OrderFlowState()


def push_contract(symbol: str, record: ContractRecord) -> None:
    _LIVE_STATE.push_contract(symbol, record)


def drop_unlisted(ticker: str, opened_at: float) -> None:
    _LIVE_STATE.drop_unlisted(ticker, opened_at)


def contracts_of(ticker: str) -> "dict[str, ContractRecord]":
    return _LIVE_STATE.contracts_of(ticker)


def contract(symbol: str) -> Optional[ContractRecord]:
    return _LIVE_STATE.contract(symbol)


def option_top(symbol: str) -> Optional[dict]:
    return _LIVE_STATE.option_top(symbol)


def push_book(symbol: str, content_item: dict, service: str) -> None:
    """Apply a book observation to the live singleton."""
    _LIVE_STATE.push_book(symbol, content_item, service)


def get_content_for_symbol(symbol: str, venue: Optional[str] = None) -> list[dict]:
    """Return canonical engine content from the live singleton."""
    return _LIVE_STATE.get_content_for_symbol(symbol, venue)




def clear_all_live_state() -> None:
    """Drop the books, the prints and the option records of every symbol, when the stream stops:
    the last window left resident would mix pre-disconnect restatements with the new session."""
    _LIVE_STATE.clear_all()




def clear_symbol(symbol: str) -> None:
    """Clear stored data for a symbol (e.g. on unsubscribe)."""
    _LIVE_STATE.clear_symbol(symbol)








