"""
app/options/order_flow/state.py — In-memory live order flow state from streaming.
Stores recent book snapshots, tape prints, and each option contract's record from Schwab streaming.
Feeds OrderFlowEngine with content.* structure for book_imbalance_5 and cum_delta_proxy.
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
from l1_trade_observation import (
    TAPE_COMPLETENESS,
    is_adjacent_restatement,
    vendor_triple,
)

# Limits to prevent unbounded growth
MAX_BOOK_SNAPSHOTS = 20
MAX_TAPE_PRINTS = 500

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
        self._tape: dict[str, deque] = {}
        self._prev_trade: dict[str, dict] = {}
        self._receive_seq: dict[str, int] = {}
        #: the daemon's contract records, mirrored (push_contract): contract -> its record, and
        #: each watchlist ticker's contracts, in the order Schwab listed them
        self._contracts: dict[str, ContractRecord] = {}
        self._by_ticker: dict[str, dict[str, None]] = {}

    def _get_book(self, symbol: str) -> deque:
        with self._lock:
            if symbol not in self._book:
                self._book[symbol] = deque(maxlen=MAX_BOOK_SNAPSHOTS)
            return self._book[symbol]

    def _get_tape(self, symbol: str) -> deque:
        with self._lock:
            if symbol not in self._tape:
                self._tape[symbol] = deque(maxlen=MAX_TAPE_PRINTS)
            return self._tape[symbol]

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

    def push_level_one(
        self, symbol: str, content_item: dict, ts_recv: Optional[float] = None,
        field_received: Optional[dict] = None,
    ) -> None:
        """Apply one Schwab L1 observation with canonical merge/freshness/tape semantics. A
        current record merged from several messages (the daemon's bus) carries each field's own
        receive time in `field_received`; each value is stamped with it."""
        if not content_item or not isinstance(content_item, dict):
            return
        sym = ticker_storage_key(symbol or content_item.get("key"))
        if not sym:
            return
        if ts_recv is None:
            # the daemon's receive time is REQUIRED -- stamping "now" made a replayed or
            # delayed message read as live (same P0 as the live plane, 2026-09-23)
            raise TypeError("push_level_one: ts_recv (the daemon receive time) is required")

        if content_item.get("LAST_PRICE") is None:
            return
        # the daemon's receive time of the message that carried the trade, not the console's
        # clock, and not a later tick merged into the same record
        self.push_trade(sym, content_item["LAST_PRICE"], content_item.get("LAST_SIZE"),
                        content_item.get("TRADE_TIME_MILLIS"),
                        float(ts_recv if field_received is None else field_received["LAST_PRICE"]))

    def push_trade(self, sym: str, last_price, last_size, trade_ms, received_ts: float) -> None:
        """One trade as Schwab sent it (price, size, trade time in ms) into the symbol's tape,
        never a restatement of the trade before it."""
        curr_key = vendor_triple(trade_ms, last_price, last_size)
        with self._lock:
            seq = self._receive_seq.get(sym, 0) + 1
            self._receive_seq[sym] = seq
            prev = self._prev_trade.get(sym)
            prev_key = None
            if prev:
                prev_key = vendor_triple(
                    prev.get("time_millis"), prev.get("price"), prev.get("size")
                )
            restatement = is_adjacent_restatement(prev_key, curr_key)
            receipt = {
                "LAST_PRICE": last_price,
                "LAST_SIZE": last_size,
                "TRADE_TIME_MILLIS": trade_ms,
                "receive_seq": seq,
                "server_received_ts": received_ts,
                "is_restatement": restatement,
                "completeness": TAPE_COMPLETENESS,
                "native_event_id": False,
            }
            if restatement:
                return
            self._prev_trade[sym] = {
                "price": last_price,
                "size": last_size,
                "time_millis": trade_ms,
            }
            self._get_tape(sym).append(receipt)

    def get_content_for_symbol(self, symbol: str, venue: Optional[str] = None) -> list[dict]:
        """Return the canonical engine-facing state for one symbol; with `venue`, only that
        Schwab book service's books (an equity has two: NYSE_BOOK and NASDAQ_BOOK)."""
        sym = ticker_storage_key(symbol)
        if not sym:
            return []
        out: list[dict] = []
        with self._lock:
            out.extend(dict(item) for item in self._get_book(sym)
                       if venue is None or item["SERVICE"] == venue)
            out.extend(dict(item) for item in self._get_tape(sym))
        return out


    def clear_all(self) -> None:
        """Drop tape/book/option records/prev-print identity for every symbol."""
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
            if sym in self._tape:
                self._tape[sym].clear()
            self._prev_trade.pop(sym, None)
            self._receive_seq.pop(sym, None)

    def push_contract(self, symbol: str, record: ContractRecord) -> None:
        """Mirror `symbol`'s record as the daemon pushed it, whole, in place of the one held."""
        sym = ticker_storage_key(symbol)
        with self._lock:
            self._contracts[sym] = record
            ticker = record.fields.get("ticker")
            if ticker:
                self._by_ticker.setdefault(ticker, {})[sym] = None

    def clear_contracts(self) -> None:
        """Forget the mirror: a new connection to the daemon pushes every record again."""
        with self._lock:
            self._contracts.clear()
            self._by_ticker.clear()

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


def clear_contracts() -> None:
    _LIVE_STATE.clear_contracts()


def contracts_of(ticker: str) -> "dict[str, ContractRecord]":
    return _LIVE_STATE.contracts_of(ticker)


def contract(symbol: str) -> Optional[ContractRecord]:
    return _LIVE_STATE.contract(symbol)


def option_top(symbol: str) -> Optional[dict]:
    return _LIVE_STATE.option_top(symbol)


def push_book(symbol: str, content_item: dict, service: str) -> None:
    """Apply a book observation to the live singleton."""
    _LIVE_STATE.push_book(symbol, content_item, service)


def push_level_one(
    symbol: str, content_item: dict, ts_recv: Optional[float] = None,
    field_received: Optional[dict] = None,
) -> None:
    """Apply an L1 observation to the live singleton."""
    _LIVE_STATE.push_level_one(symbol, content_item, ts_recv=ts_recv, field_received=field_received)


def push_trade(sym: str, last_price, last_size, trade_ms, received_ts: float) -> None:
    _LIVE_STATE.push_trade(sym, last_price, last_size, trade_ms, received_ts)


def get_content_for_symbol(symbol: str, venue: Optional[str] = None) -> list[dict]:
    """Return canonical engine content from the live singleton."""
    return _LIVE_STATE.get_content_for_symbol(symbol, venue)




def clear_all_live_state() -> None:
    """Drop tape/book/option records/prev-print identity for every symbol.

    Required on stream disconnect/reconnect. Leaving the last window resident
    mixes pre-disconnect restatements with the new session.
    """
    _LIVE_STATE.clear_all()




def clear_symbol(symbol: str) -> None:
    """Clear stored data for a symbol (e.g. on unsubscribe)."""
    _LIVE_STATE.clear_symbol(symbol)








