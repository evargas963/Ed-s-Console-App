"""
order_flow_live_state.py — In-memory live order flow state from streaming.
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

_lock = threading.RLock()  # RLock: get_content_for_symbol holds lock and calls _get_book/_get_tape which also need it
_book: dict[str, deque] = {}      # symbol -> deque of book content items
_tape: dict[str, deque] = {}     # symbol -> deque of tape print dicts
_top: dict[str, dict] = {}       # symbol -> latest top-of-book
_prev_trade: dict[str, dict] = {}  # symbol -> last accepted vendor triple
_receive_seq: dict[str, int] = {}  # symbol -> monotonic local receive sequence (not native)
_receive_log: dict[str, deque] = {}  # symbol -> all L1 last-print receipts (incl. restatements)
_stream_volume: dict[str, float] = {}  # symbol -> TOTAL_VOLUME from level_one_equity (content.*.TOTAL_VOLUME / VOLUME)
_stream_chg_pct: dict[str, float] = {}  # symbol -> REGULAR_MARKET_CHANGE_PERCENT or CHANGE_PERCENT from stream
_last_rth_date: str = ""


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


def _get_book(symbol: str) -> deque:
    with _lock:
        if symbol not in _book:
            _book[symbol] = deque(maxlen=MAX_BOOK_SNAPSHOTS)
        return _book[symbol]


def _get_tape(symbol: str) -> deque:
    with _lock:
        if symbol not in _tape:
            _tape[symbol] = deque(maxlen=MAX_TAPE_PRINTS)
        return _tape[symbol]


def push_book(symbol: str, content_item: dict) -> None:
    """
    Push a book snapshot from nasdaq_book or nyse_book.
    content_item must have BIDS, ASKS (and optionally BOOK_TIME).
    """
    if not content_item or not isinstance(content_item, dict):
        return
    bids = content_item.get("BIDS")
    asks = content_item.get("ASKS")
    if not bids or not asks:
        return
    sym = ticker_storage_key(symbol or content_item.get("key"))  # RC-345/F25: canonical OF-state key (write+read consistent; idempotent on stream symbols)
    if not sym:
        return
    # Ensure format matches engine: BIDS/ASKS with BID_PRICE, TOTAL_VOLUME, etc.
    item = {
        "BIDS": list(bids) if isinstance(bids, list) else [bids],
        "ASKS": list(asks) if isinstance(asks, list) else [asks],
        "BOOK_TIME": content_item.get("BOOK_TIME"),
    }
    q = _get_book(sym)
    with _lock:
        q.append(item)


def _get_receive_log(symbol: str) -> deque:
    with _lock:
        if symbol not in _receive_log:
            _receive_log[symbol] = deque(maxlen=MAX_TAPE_PRINTS)
        return _receive_log[symbol]


def push_level_one(symbol: str, content_item: dict) -> None:
    """
    Push level_one_equity update. Extracts:
    - Top-of-book: BID_PRICE, ASK_PRICE, BID_SIZE, ASK_SIZE
    - Tape observation: adjacent identical LAST_PRICE+LAST_SIZE+TRADE_TIME_MILLIS
      restatements are not counted as new prints. Distinct same-ms triples are
      kept. TRADE_TIME_MILLIS is not a unique trade id. Each receipt gets a
      local receive_seq (not native identity).
    """
    if not content_item or not isinstance(content_item, dict):
        return
    sym = ticker_storage_key(symbol or content_item.get("key"))  # RC-345/F25: canonical OF-state key (write+read consistent; idempotent on stream symbols)
    if not sym:
        return

    # Store TOTAL_VOLUME from WebSocket (content.*.TOTAL_VOLUME / content.*.VOLUME) for candle accumulator
    vol = content_item.get("TOTAL_VOLUME") or content_item.get("VOLUME")
    if vol is not None:
        try:
            vf = float(vol)
            if vf > 0:
                with _lock:
                    _stream_volume[sym] = vf
        except (TypeError, ValueError):
            pass

    # Store REGULAR_MARKET_CHANGE_PERCENT (RTH) or CHANGE_PERCENT (all session) as authoritative chg_pct
    chg = content_item.get("REGULAR_MARKET_CHANGE_PERCENT") or content_item.get("CHANGE_PERCENT")
    if chg is not None:
        try:
            cf = float(chg)
            with _lock:
                _stream_chg_pct[sym] = cf
        except (TypeError, ValueError):
            pass

    # FIX 2: RTH session reset at 9:30 ET
    try:
        global _last_rth_date
        now_et_dt = now_et()
        current_date = now_et_dt.strftime("%Y-%m-%d")
        if is_rth_open() and current_date != _last_rth_date:
            with _lock:
                # Use loop-local names to avoid shadowing the outer `sym`
                # (the symbol being pushed). Reassigning `sym` here previously
                # caused subsequent writes in this call to land on the wrong
                # symbol when other tickers were already in _top / _book.
                _clear_all_session_state_unlocked()
                _last_rth_date = current_date
            log.info("RTH open — full state reset (tape + book + top + prev_trade) for all symbols")
    except Exception as e:
        log.debug(f"RTH reset check failed (continuing): {e}")

    # Update top-of-book: MERGE, never overwrite. Schwab's LEVELONE_OPTIONS/EQUITIES
    # stream sends partial/delta ticks -- a size-only update carries no BID_PRICE key
    # at all -- so a field absent from THIS tick must keep its last known value, not
    # be wiped to None. RTH proof (2026-08-31): the prior full-overwrite form dropped
    # a valid, seconds-old price the moment a size-only delta arrived. `in
    # content_item` (not `.get(...) is not None`), so a tick that explicitly carries a
    # field with value `0` still updates it -- 0 is a real size, not "absent".
    with _lock:
        top_item = dict(_top.get(sym) or {
            "BID_PRICE": None, "ASK_PRICE": None, "BID_SIZE": None, "ASK_SIZE": None,
            "BID_TIME_MILLIS": None, "ASK_TIME_MILLIS": None,
        })
        for field in ("BID_PRICE", "ASK_PRICE", "BID_SIZE", "ASK_SIZE",
                      "BID_TIME_MILLIS", "ASK_TIME_MILLIS"):
            if field in content_item:
                top_item[field] = content_item[field]
        _top[sym] = top_item

    trade_ms = content_item.get("TRADE_TIME_MILLIS")
    last_price = content_item.get("LAST_PRICE")
    last_size = content_item.get("LAST_SIZE")
    if last_price is None:
        return

    curr_key = vendor_triple(trade_ms, last_price, last_size)
    received_ts = _time.time()
    with _lock:
        seq = _receive_seq.get(sym, 0) + 1
        _receive_seq[sym] = seq
        prev = _prev_trade.get(sym)
        prev_key = None
        if prev:
            prev_key = vendor_triple(prev.get("time_millis"), prev.get("price"), prev.get("size"))
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
        _get_receive_log(sym).append(dict(receipt))
        if restatement:
            return
        _prev_trade[sym] = {
            "price": last_price,
            "size": last_size,
            "time_millis": trade_ms,
        }
        _get_tape(sym).append(receipt)


def get_content_for_symbol(symbol: str) -> list[dict]:
    """
    Return content list for OrderFlowEngine. Merges:
    1. Book snapshots (BIDS, ASKS)
    2. Tape prints as content items (LAST_PRICE, LAST_SIZE, TRADE_TIME_MILLIS)
    3. Latest top-of-book as a content item (BID_PRICE, ASK_PRICE, BID_SIZE, ASK_SIZE)
    Engine expects content.*.BIDS, content.*.ASKS, content.*.LAST_PRICE, etc.
    """
    sym = ticker_storage_key(symbol)  # RC-345/F25: canonical OF-state key (write+read consistent; idempotent on stream symbols)
    if not sym:
        return []

    out: list[dict] = []
    with _lock:
        # Book snapshots (oldest first for absorption compare)
        for item in _get_book(sym):
            out.append(item)

        # Top-of-book (if we have level_one data)
        if sym in _top:
            out.append(dict(_top[sym]))

        # Tape prints as content items
        for p in _get_tape(sym):
            out.append(dict(p))

    return out


def get_l1_stream_input_probe(symbol: str) -> tuple[Any, ...]:
    """
    Cheap snapshot of streaming buffers for L1 quote-hook OF gating (no OrderFlowEngine).
    Book/tape lengths, last tape id/timestamp, top-of-book bid/ask when present.
    """
    sym = ticker_storage_key(symbol)  # RC-345/F25: canonical OF-state key (write+read consistent; idempotent on stream symbols)
    if not sym:
        return (0, 0, None, None, None)
    with _lock:
        book = _book.get(sym)
        tape = _tape.get(sym)
        bl = len(book) if book else 0
        tl = len(tape) if tape else 0
        last_ms = None
        if tape and len(tape) > 0:
            last_ms = tape[-1].get("TRADE_TIME_MILLIS")
        top = _top.get(sym)
        if top:
            tb = top.get("BID_PRICE")
            ta = top.get("ASK_PRICE")
        else:
            tb, ta = None, None
    return (bl, tl, last_ms, tb, ta)


def clear_all_live_state() -> None:
    """Drop tape/book/top/prev-print identity for every symbol.

    Required on stream disconnect/reconnect. Leaving the last window resident
    mixes pre-disconnect restatements with the new session.
    """
    with _lock:
        _clear_all_session_state_unlocked()


def _clear_all_session_state_unlocked() -> None:
    """Drop every symbol's tape/book/top/prev-print identity. Caller holds _lock."""
    for _k in list(_tape.keys()):
        _tape[_k].clear()
    for _k in list(_top.keys()):
        _top[_k] = {}
    for _k in list(_book.keys()):
        _book[_k].clear()
    _prev_trade.clear()
    _receive_seq.clear()
    for _k in list(_receive_log.keys()):
        _receive_log[_k].clear()
    _stream_volume.clear()
    _stream_chg_pct.clear()


def forget_unsubscribed_symbols(old: list[str], new: list[str]) -> None:
    """Clear live state for symbols leaving the active stream set."""
    new_keys = {ticker_storage_key(s) for s in new if s}
    for raw in old:
        key = ticker_storage_key(raw)
        if key and key not in new_keys:
            clear_symbol(key)


def get_receive_log(symbol: str) -> list[dict]:
    """Local receive receipts including restatements. Not a native trade id."""
    sym = ticker_storage_key(symbol)
    if not sym:
        return []
    with _lock:
        return [dict(x) for x in _receive_log.get(sym, ())]


def clear_symbol(symbol: str) -> None:
    """Clear stored data for a symbol (e.g. on unsubscribe)."""
    sym = ticker_storage_key(symbol)  # RC-345/F25: canonical OF-state key (write+read consistent; idempotent on stream symbols)
    with _lock:
        if sym in _book:
            _book[sym].clear()
        if sym in _tape:
            _tape[sym].clear()
        if sym in _top:
            del _top[sym]
        if sym in _prev_trade:
            del _prev_trade[sym]
        if sym in _receive_seq:
            del _receive_seq[sym]
        if sym in _receive_log:
            _receive_log[sym].clear()
        if sym in _stream_volume:
            del _stream_volume[sym]
        if sym in _stream_chg_pct:
            del _stream_chg_pct[sym]


def get_stream_volume(symbol: str) -> Optional[float]:
    """Return latest TOTAL_VOLUME from WebSocket level_one_equity for symbol, or None."""
    sym = ticker_storage_key(symbol)  # RC-345/F25: canonical OF-state key (write+read consistent; idempotent on stream symbols)
    if not sym:
        return None
    with _lock:
        return _stream_volume.get(sym)


def get_stream_chg_pct(symbol: str) -> Optional[float]:
    """Return REGULAR_MARKET_CHANGE_PERCENT or CHANGE_PERCENT from WebSocket for symbol, or None."""
    sym = ticker_storage_key(symbol)  # RC-345/F25: canonical OF-state key (write+read consistent; idempotent on stream symbols)
    if not sym:
        return None
    with _lock:
        return _stream_chg_pct.get(sym)


def get_top_of_book_sizes(symbol: str) -> dict[str, Optional[int]]:
    """Latest L1 BID_SIZE / ASK_SIZE from streaming top-of-book, if present."""
    sym = ticker_storage_key(symbol)  # RC-345/F25: canonical OF-state key (write+read consistent; idempotent on stream symbols)
    if not sym:
        return {"bid_size": None, "ask_size": None}

    def _to_int(x: Any) -> Optional[int]:
        if x is None:
            return None
        try:
            return int(float(x))
        except (TypeError, ValueError):
            return None

    with _lock:
        ti = _top.get(sym) or {}
    return {
        "bid_size": _to_int(ti.get("BID_SIZE")),
        "ask_size": _to_int(ti.get("ASK_SIZE")),
    }


def get_stats() -> dict[str, Any]:
    """Return counts per symbol for debugging."""
    with _lock:
        return {
            "book": {k: len(v) for k, v in _book.items()},
            "tape": {k: len(v) for k, v in _tape.items()},
            "top": list(_top.keys()),
        }
