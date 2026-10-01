"""
app/options/order_flow/state.py — In-memory live order flow state from streaming.
Stores each symbol's recent books, an option contract's top of book and type, and its streamed
greeks, as Schwab sent them. Feeds engine.compute_book_microstructure.
"""

from __future__ import annotations

import logging
import threading
from collections import deque
from typing import Optional
from time_et import now_et, session_label
from instrument_identity import ticker_storage_key
from numeric_contract import schwab_count, schwab_number

# Limits to prevent unbounded growth
MAX_BOOK_SNAPSHOTS = 20

log = logging.getLogger(__name__)


_OPTION_TOP_FIELDS = (("BID_PRICE", "bid", schwab_number), ("ASK_PRICE", "ask", schwab_number),
                      ("BID_SIZE", "bid_size", schwab_count), ("ASK_SIZE", "ask_size", schwab_count),
                      ("MARK", "mark", schwab_number))
#: the LEVELONE_OPTIONS fields the stream owns for a live contract (the chain overlay), each read
#: as sent: a reported 0 is 0
_OPTION_GREEK_FIELDS = (("GAMMA", "gamma", schwab_number), ("DELTA", "delta", schwab_number),
                        ("OPEN_INTEREST", "open_interest", schwab_count),
                        ("TOTAL_VOLUME", "total_volume", schwab_count),
                        ("VOLATILITY", "volatility", schwab_number))


class OrderFlowState:
    """The one state-transition owner for live and isolated historical replay."""

    def __init__(self) -> None:
        # RLock: get_content_for_symbol holds the lock and calls the deque accessors.
        self._lock = threading.RLock()
        self._book: dict[str, deque] = {}
        self._top: dict[str, dict] = {}
        self._contract_type: dict[str, str] = {}
        self._stream_greeks: dict[str, dict] = {}
        # A newly constructed instance is already empty. If it is created during
        # RTH (as isolated history states are), mark that session current so its
        # first L1 observation cannot erase an earlier book observation from the
        # same replay. A long-lived premarket live singleton still resets once at
        # the next RTH boundary.
        try:
            now = now_et()
            self._last_rth_date = now.strftime("%Y-%m-%d") if session_label(now) == "RTH" else ""
        except Exception:
            self._last_rth_date = ""

    def _get_book(self, symbol: str) -> deque:
        with self._lock:
            if symbol not in self._book:
                self._book[symbol] = deque(maxlen=MAX_BOOK_SNAPSHOTS)
            return self._book[symbol]

    def push_book(self, symbol: str, content_item: dict, service: str) -> None:
        """Apply one Schwab book observation (from `service`: NYSE_BOOK, NASDAQ_BOOK or
        OPTIONS_BOOK) to this state instance. Schwab sends the whole book each time, both
        sides: an empty side is that side with nothing resting, and it replaces the book
        before it (a book with a side missing from the message is not a book)."""
        if not content_item or not isinstance(content_item, dict):
            return
        bids = content_item.get("BIDS")
        asks = content_item.get("ASKS")
        if bids is None or asks is None:
            return
        sym = ticker_storage_key(symbol or content_item.get("key"))
        if not sym:
            return
        item = {
            "BIDS": list(bids) if isinstance(bids, list) else [bids],
            "ASKS": list(asks) if isinstance(asks, list) else [asks],
            "BOOK_TIME": content_item.get("BOOK_TIME"),
            "SERVICE": service,
        }
        with self._lock:
            self._get_book(sym).append(item)

    def push_level_one(
        self, symbol: str, content_item: dict, ts_recv: Optional[float] = None
    ) -> None:
        """Apply one LEVELONE_OPTIONS message's GAMMA / DELTA / OPEN_INTEREST / TOTAL_VOLUME /
        VOLATILITY: each field it carries is merged on its own and stamped with the message's
        receive time, so a field it does not carry keeps its value and its time. A field it
        carries as not a number (-999, text, NaN, a negative count) is held as None: Schwab says
        it has no value now, and the chain overlay makes the contract's field unavailable."""
        if not content_item or not isinstance(content_item, dict):
            return
        sym = ticker_storage_key(symbol or content_item.get("key"))
        if not sym:
            return
        if ts_recv is None:
            # the daemon's receive time is REQUIRED -- stamping "now" made a replayed or
            # delayed message read as live (same P0 as the live plane, 2026-09-23)
            raise TypeError("push_level_one: ts_recv (the daemon receive time) is required")

        # the session reset runs before the message is applied, so the first message of a
        # session is kept
        try:
            now_et_dt = now_et()
            current_date = now_et_dt.strftime("%Y-%m-%d")
            if session_label(now_et_dt) == "RTH" and current_date != self._last_rth_date:
                with self._lock:
                    self._clear_all_session_state_unlocked()
                    self._last_rth_date = current_date
                log.info("RTH open — full state reset (book + top + greeks) for all symbols")
        except Exception as e:
            log.debug("RTH reset check failed (continuing): %s", e)

        sent = [(name, read(content_item[field])) for field, name, read in _OPTION_GREEK_FIELDS
                if field in content_item]
        if sent:
            with self._lock:
                g = self._stream_greeks.setdefault(sym, {})
                for name, value in sent:
                    g[name], g[name + "_ts_recv"] = value, ts_recv

    def get_content_for_symbol(self, symbol: str, venue: Optional[str] = None) -> list[dict]:
        """The symbol's recent books, oldest first; with `venue`, only that Schwab book
        service's (an equity has two: NYSE_BOOK and NASDAQ_BOOK)."""
        sym = ticker_storage_key(symbol)
        if not sym:
            return []
        with self._lock:
            return [dict(item) for item in self._get_book(sym)
                    if venue is None or item["SERVICE"] == venue]


    def clear_all(self) -> None:
        """Drop the book, top of book, contract type and greeks of every symbol."""
        with self._lock:
            self._clear_all_session_state_unlocked()

    def _clear_all_session_state_unlocked(self) -> None:
        """Drop session state. Caller holds ``self._lock``."""
        for key in list(self._top):
            self._top[key] = {}
        for values in self._book.values():
            values.clear()
        self._contract_type.clear()
        self._stream_greeks.clear()

    def forget_unsubscribed_symbols(self, old: list[str], new: list[str]) -> None:
        """Clear state for symbols leaving a subscription set."""
        new_keys = {ticker_storage_key(s) for s in new if s}
        for raw in old:
            key = ticker_storage_key(raw)
            if key and key not in new_keys:
                self.clear_symbol(key)


    def clear_symbol(self, symbol: str) -> None:
        """Clear all state for one symbol."""
        sym = ticker_storage_key(symbol)
        with self._lock:
            if sym in self._book:
                self._book[sym].clear()
            self._top.pop(sym, None)
            self._contract_type.pop(sym, None)
            self._stream_greeks.pop(sym, None)


    def push_option_top(self, symbol: str, content_item: dict) -> None:
        """An option contract's top of book (LEVELONE_OPTIONS BID/ASK price and size, MARK) and
        its CONTRACT_TYPE, merged per field as Schwab sends changes only; not a number clears
        the field."""
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
            if content_item.get("CONTRACT_TYPE") is not None:
                self._contract_type[sym] = content_item["CONTRACT_TYPE"]

    def option_contract_type(self, symbol: str) -> Optional[str]:
        """Schwab's LEVELONE_OPTIONS CONTRACT_TYPE for the contract, as last sent; None when
        the stream has not sent it."""
        with self._lock:
            return self._contract_type.get(ticker_storage_key(symbol))

    def option_top(self, symbol: str) -> Optional[dict]:
        sym = ticker_storage_key(symbol)
        with self._lock:
            t = self._top.get(sym)
            return dict(t) if t else None

    def get_stream_greeks(self, symbol: str) -> Optional[dict]:
        """Return the latest streamed GAMMA/DELTA/OPEN_INTEREST/TOTAL_VOLUME for one OPTION
        contract symbol, each field paired with its own ``_ts_recv`` (the field's own
        last-update wall-clock receive time, not merely this call's time) -- a per-field
        freshness stamp is what lets a caller judge one field newer than a same-tick sibling
        that was absent this update, per the sparse-overlay pattern below. Returns None when
        nothing has ever been observed for this symbol (never a dict of Nones)."""
        sym = ticker_storage_key(symbol)
        if not sym:
            return None
        with self._lock:
            g = self._stream_greeks.get(sym)
            return dict(g) if g else None




_LIVE_STATE = OrderFlowState()


def push_option_top(symbol: str, content_item: dict) -> None:
    _LIVE_STATE.push_option_top(symbol, content_item)


def option_top(symbol: str) -> Optional[dict]:
    return _LIVE_STATE.option_top(symbol)


def option_contract_type(symbol: str) -> Optional[str]:
    return _LIVE_STATE.option_contract_type(symbol)


def push_book(symbol: str, content_item: dict, service: str) -> None:
    """Apply a book observation to the live singleton."""
    _LIVE_STATE.push_book(symbol, content_item, service)


def push_level_one(
    symbol: str, content_item: dict, ts_recv: Optional[float] = None
) -> None:
    """Apply an L1 observation to the live singleton."""
    _LIVE_STATE.push_level_one(symbol, content_item, ts_recv=ts_recv)


def get_content_for_symbol(symbol: str, venue: Optional[str] = None) -> list[dict]:
    """Return canonical engine content from the live singleton."""
    return _LIVE_STATE.get_content_for_symbol(symbol, venue)




def clear_all_live_state() -> None:
    """Drop the book, top of book, contract type and greeks of every symbol (when the
    order-flow stream stops)."""
    _LIVE_STATE.clear_all()


def forget_unsubscribed_symbols(old: list[str], new: list[str]) -> None:
    """Clear live state for symbols leaving the active stream set."""
    _LIVE_STATE.forget_unsubscribed_symbols(old, new)




def clear_symbol(symbol: str) -> None:
    """Clear stored data for a symbol (e.g. on unsubscribe)."""
    _LIVE_STATE.clear_symbol(symbol)




def get_stream_greeks(symbol: str) -> Optional[dict]:
    """Return the live singleton's latest streamed GAMMA/DELTA/OPEN_INTEREST for one option
    contract symbol (each paired with its own `_ts_recv`), or None if never observed."""
    return _LIVE_STATE.get_stream_greeks(symbol)




