"""
app/options/order_flow/state.py — In-memory live order flow state from streaming.
Stores recent book snapshots, tape prints, and top-of-book from Schwab streaming.
Feeds OrderFlowEngine with content.* structure for book_imbalance_5 and cum_delta_proxy.
"""

from __future__ import annotations

import logging
import threading
from collections import deque
from typing import Any, Optional
from time_et import now_et, RTH_END_MINS, RTH_OPEN_MINS
from instrument_identity import ticker_storage_key
from l1_trade_observation import (
    TAPE_COMPLETENESS,
    is_adjacent_restatement,
    vendor_triple,
)
import time as _time

# Limits to prevent unbounded growth
MAX_BOOK_SNAPSHOTS = 20
MAX_TAPE_PRINTS = 500

log = logging.getLogger(__name__)

def is_rth_open() -> bool:
    """Return True if current ET time is between 09:30:00 and 16:00:00 Monday-Friday."""
    try:
        now = now_et()
        if now.weekday() >= 5:  # Saturday=5, Sunday=6
            return False
        hour, minute = now.hour, now.minute
        mins = hour * 60 + minute
        return RTH_OPEN_MINS <= mins < RTH_END_MINS
    except Exception:
        return False


class OrderFlowState:
    """The one state-transition owner for live and isolated historical replay."""

    def __init__(self) -> None:
        # RLock: get_content_for_symbol holds the lock and calls the deque accessors.
        self._lock = threading.RLock()
        self._book: dict[str, deque] = {}
        self._tape: dict[str, deque] = {}
        self._top: dict[str, dict] = {}
        self._prev_trade: dict[str, dict] = {}
        self._receive_seq: dict[str, int] = {}
        self._receive_log: dict[str, deque] = {}
        self._stream_volume: dict[str, float] = {}
        self._stream_chg_pct: dict[str, float] = {}
        # A newly constructed instance is already empty. If it is created during
        # RTH (as isolated history states are), mark that session current so its
        # first L1 observation cannot erase an earlier book observation from the
        # same replay. A long-lived premarket live singleton still resets once at
        # the next RTH boundary.
        try:
            self._last_rth_date = (
                now_et().strftime("%Y-%m-%d") if is_rth_open() else ""
            )
        except Exception:
            self._last_rth_date = ""

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

    def _get_receive_log(self, symbol: str) -> deque:
        with self._lock:
            if symbol not in self._receive_log:
                self._receive_log[symbol] = deque(maxlen=MAX_TAPE_PRINTS)
            return self._receive_log[symbol]

    def push_book(self, symbol: str, content_item: dict) -> None:
        """Apply one Schwab book observation to this state instance."""
        if not content_item or not isinstance(content_item, dict):
            return
        bids = content_item.get("BIDS")
        asks = content_item.get("ASKS")
        if not bids or not asks:
            return
        sym = ticker_storage_key(symbol or content_item.get("key"))
        if not sym:
            return
        item = {
            "BIDS": list(bids) if isinstance(bids, list) else [bids],
            "ASKS": list(asks) if isinstance(asks, list) else [asks],
            "BOOK_TIME": content_item.get("BOOK_TIME"),
        }
        with self._lock:
            self._get_book(sym).append(item)

    def push_level_one(
        self, symbol: str, content_item: dict, ts_recv: Optional[float] = None
    ) -> None:
        """Apply one Schwab L1 observation with canonical merge/freshness/tape semantics."""
        if not content_item or not isinstance(content_item, dict):
            return
        sym = ticker_storage_key(symbol or content_item.get("key"))
        if not sym:
            return
        if ts_recv is None:
            ts_recv = _time.time()

        vol = content_item.get("TOTAL_VOLUME") or content_item.get("VOLUME")
        if vol is not None:
            try:
                vf = float(vol)
                if vf > 0:
                    with self._lock:
                        self._stream_volume[sym] = vf
            except (TypeError, ValueError):
                pass

        chg = content_item.get("REGULAR_MARKET_CHANGE_PERCENT") or content_item.get(
            "CHANGE_PERCENT"
        )
        if chg is not None:
            try:
                cf = float(chg)
                with self._lock:
                    self._stream_chg_pct[sym] = cf
            except (TypeError, ValueError):
                pass

        try:
            now_et_dt = now_et()
            current_date = now_et_dt.strftime("%Y-%m-%d")
            if is_rth_open() and current_date != self._last_rth_date:
                with self._lock:
                    self._clear_all_session_state_unlocked()
                    self._last_rth_date = current_date
                log.info(
                    "RTH open — full state reset "
                    "(tape + book + top + prev_trade) for all symbols"
                )
        except Exception as e:
            log.debug("RTH reset check failed (continuing): %s", e)

        with self._lock:
            top_item = dict(
                self._top.get(sym)
                or {
                    "BID_PRICE": None,
                    "ASK_PRICE": None,
                    "BID_SIZE": None,
                    "ASK_SIZE": None,
                    "BID_TIME_MILLIS": None,
                    "ASK_TIME_MILLIS": None,
                }
            )
            for field in (
                "BID_PRICE",
                "ASK_PRICE",
                "BID_SIZE",
                "ASK_SIZE",
                "BID_TIME_MILLIS",
                "ASK_TIME_MILLIS",
            ):
                if field in content_item:
                    top_item[field] = content_item[field]
                    top_item[f"{field}_TS_RECV"] = ts_recv
            self._top[sym] = top_item

        trade_ms = content_item.get("TRADE_TIME_MILLIS")
        last_price = content_item.get("LAST_PRICE")
        last_size = content_item.get("LAST_SIZE")
        if last_price is None:
            return

        curr_key = vendor_triple(trade_ms, last_price, last_size)
        received_ts = _time.time()
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
            self._get_receive_log(sym).append(dict(receipt))
            if restatement:
                return
            self._prev_trade[sym] = {
                "price": last_price,
                "size": last_size,
                "time_millis": trade_ms,
            }
            self._get_tape(sym).append(receipt)

    def get_content_for_symbol(self, symbol: str) -> list[dict]:
        """Return the canonical engine-facing state for one symbol."""
        sym = ticker_storage_key(symbol)
        if not sym:
            return []
        out: list[dict] = []
        with self._lock:
            out.extend(dict(item) for item in self._get_book(sym))
            if sym in self._top:
                out.append(dict(self._top[sym]))
            out.extend(dict(item) for item in self._get_tape(sym))
        return out

    def get_l1_stream_input_probe(self, symbol: str) -> tuple[Any, ...]:
        """Return the cheap L1 gate snapshot for one symbol."""
        sym = ticker_storage_key(symbol)
        if not sym:
            return (0, 0, None, None, None)
        with self._lock:
            book = self._book.get(sym)
            tape = self._tape.get(sym)
            bl = len(book) if book else 0
            tl = len(tape) if tape else 0
            last_ms = tape[-1].get("TRADE_TIME_MILLIS") if tape else None
            top = self._top.get(sym)
            tb = top.get("BID_PRICE") if top else None
            ta = top.get("ASK_PRICE") if top else None
        return (bl, tl, last_ms, tb, ta)

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
        for values in self._receive_log.values():
            values.clear()
        self._stream_volume.clear()
        self._stream_chg_pct.clear()

    def forget_unsubscribed_symbols(self, old: list[str], new: list[str]) -> None:
        """Clear state for symbols leaving a subscription set."""
        new_keys = {ticker_storage_key(s) for s in new if s}
        for raw in old:
            key = ticker_storage_key(raw)
            if key and key not in new_keys:
                self.clear_symbol(key)

    def get_receive_log(self, symbol: str) -> list[dict]:
        """Return receipts including restatements for one symbol."""
        sym = ticker_storage_key(symbol)
        if not sym:
            return []
        with self._lock:
            return [dict(x) for x in self._receive_log.get(sym, ())]

    def clear_symbol(self, symbol: str) -> None:
        """Clear all state for one symbol."""
        sym = ticker_storage_key(symbol)
        with self._lock:
            if sym in self._book:
                self._book[sym].clear()
            if sym in self._tape:
                self._tape[sym].clear()
            self._top.pop(sym, None)
            self._prev_trade.pop(sym, None)
            self._receive_seq.pop(sym, None)
            if sym in self._receive_log:
                self._receive_log[sym].clear()
            self._stream_volume.pop(sym, None)
            self._stream_chg_pct.pop(sym, None)

    def get_stream_volume(self, symbol: str) -> Optional[float]:
        """Return the latest positive streamed total volume."""
        sym = ticker_storage_key(symbol)
        if not sym:
            return None
        with self._lock:
            return self._stream_volume.get(sym)

    def get_stream_chg_pct(self, symbol: str) -> Optional[float]:
        """Return the latest streamed regular/all-session change percent."""
        sym = ticker_storage_key(symbol)
        if not sym:
            return None
        with self._lock:
            return self._stream_chg_pct.get(sym)

    def get_top_of_book_sizes(self, symbol: str) -> dict[str, Optional[int]]:
        """Return latest L1 bid/ask sizes for one symbol."""
        sym = ticker_storage_key(symbol)
        if not sym:
            return {"bid_size": None, "ask_size": None}

        def _to_int(value: Any) -> Optional[int]:
            if value is None:
                return None
            try:
                return int(float(value))
            except (TypeError, ValueError):
                return None

        with self._lock:
            top = self._top.get(sym) or {}
            return {
                "bid_size": _to_int(top.get("BID_SIZE")),
                "ask_size": _to_int(top.get("ASK_SIZE")),
            }

    def get_stats(self) -> dict[str, Any]:
        """Return counts per symbol for diagnostics."""
        with self._lock:
            return {
                "book": {k: len(v) for k, v in self._book.items()},
                "tape": {k: len(v) for k, v in self._tape.items()},
                "top": list(self._top),
            }


_LIVE_STATE = OrderFlowState()


def push_book(symbol: str, content_item: dict) -> None:
    """Apply a book observation to the live singleton."""
    _LIVE_STATE.push_book(symbol, content_item)


def push_level_one(
    symbol: str, content_item: dict, ts_recv: Optional[float] = None
) -> None:
    """Apply an L1 observation to the live singleton."""
    _LIVE_STATE.push_level_one(symbol, content_item, ts_recv=ts_recv)


def get_content_for_symbol(symbol: str) -> list[dict]:
    """Return canonical engine content from the live singleton."""
    return _LIVE_STATE.get_content_for_symbol(symbol)


def get_l1_stream_input_probe(symbol: str) -> tuple[Any, ...]:
    """Return the live singleton's cheap L1 gate snapshot."""
    return _LIVE_STATE.get_l1_stream_input_probe(symbol)


def clear_all_live_state() -> None:
    """Drop tape/book/top/prev-print identity for every symbol.

    Required on stream disconnect/reconnect. Leaving the last window resident
    mixes pre-disconnect restatements with the new session.
    """
    _LIVE_STATE.clear_all()


def forget_unsubscribed_symbols(old: list[str], new: list[str]) -> None:
    """Clear live state for symbols leaving the active stream set."""
    _LIVE_STATE.forget_unsubscribed_symbols(old, new)


def get_receive_log(symbol: str) -> list[dict]:
    """Local receive receipts including restatements. Not a native trade id."""
    return _LIVE_STATE.get_receive_log(symbol)


def clear_symbol(symbol: str) -> None:
    """Clear stored data for a symbol (e.g. on unsubscribe)."""
    _LIVE_STATE.clear_symbol(symbol)


def get_stream_volume(symbol: str) -> Optional[float]:
    """Return latest TOTAL_VOLUME from WebSocket level_one_equity for symbol, or None."""
    return _LIVE_STATE.get_stream_volume(symbol)


def get_stream_chg_pct(symbol: str) -> Optional[float]:
    """Return REGULAR_MARKET_CHANGE_PERCENT or CHANGE_PERCENT from WebSocket for symbol, or None."""
    return _LIVE_STATE.get_stream_chg_pct(symbol)


def get_top_of_book_sizes(symbol: str) -> dict[str, Optional[int]]:
    """Latest L1 BID_SIZE / ASK_SIZE from streaming top-of-book, if present."""
    return _LIVE_STATE.get_top_of_book_sizes(symbol)


def get_stats() -> dict[str, Any]:
    """Return counts per symbol for debugging."""
    return _LIVE_STATE.get_stats()
